"""The pin store: the pin files of one state directory, read and written under one lock in one order.

Files (all in the state directory; names and bytes are the stored format, docs/handbook/api.md):

    pins.jsonl          the live pins, one JSON record per line, rewritten whole on every change
    pins.md             the agents' work list, re-rendered from pins.jsonl after every write of it
    pins.dropped.jsonl  the Trash
    pins.seq            the last pin id handed out - ids are never reused
    pins_<ts>.jsonl.bak, *.corrupt-<ts>.bak   an archive made by clear, and the original bytes of a file
                        that had unreadable lines, kept before the first rewrite

The write-order invariant (docs/handbook/architecture.md 불변식 4): every change to the pins goes through
PinStore.transact() - with the lock: read -> re-sync line numbers -> apply the request's change -> atomic write of
pins.jsonl -> pins.md. pins.md is rendered in memory before anything is written, so a failed render writes nothing.

Reading hands out parsed pins: every pins.jsonl line goes through the record parse (limn.pins.record) into its state
type (limn.pins.model.Pin) and every Trash line into a TrashedPin; a line the parse calls Broken is skipped and
numbered. Writing turns each pin back into its stored line (`record`, in the stored field order), so a pin read and
written back unchanged keeps its bytes.

Reading for a caller that only reads may skip the parse of a line it has parsed before (KeptPinReader over the
run's PinLines): what a line parses to is kept under the line's own text, the file is still read at every call, and
only a line whose text was not in the last read is parsed. A kept value is shared by every such reader, so none of
them may change a pin it was handed or anything inside it. A writer never shares: PinStore parses every line of every
read, and neither reads nor fills what is kept, so nothing kept can reach a pin file.

This module knows no run arguments and no HTTP. What the order needs from outside comes in as fields of PinStore,
set by the composition root (server.pin_store()): where the files are (PinFiles), the process-wide lock, the record
parse of a live line and of a Trash line (parse, parse_trashed), the anchor re-sync of the pins against the .tex
files (sync), the pins.md renderer (render) and, for a keeping reader, the run's kept lines (lines). It creates no
lock and holds no state of its own, so a store or reader value is cheap to make per call.
"""

import json
import re
import shutil
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeAlias, TypeVar

from limn.pins.model import Pin, TrashedPin
from limn.pins.record import Broken
from limn.pins.retention import unexpired, without_live_shadows
from limn.platform.diagnostics import diagnostics
from limn.platform.effects import changed, require_writer
from limn.platform.files import atomic_write, replace_files
from limn.runtime.paths import PinFiles as PinFiles

# One stored record as JSON gives it: a pin or a Trash entry as written, or a pin as the API shows it.
Row: TypeAlias = dict[str, Any]
T = TypeVar("T")
# What one readable line of a pin file parses to: a live pin or a Trash copy.
Parsed = TypeVar("Parsed")
# What one line of a pin file is kept as: what it parses to, or Broken.
Value = TypeVar("Value")

# The most characters of line text one KeptLines keeps. What that costs in bytes depends on the lines: a kept line
# holds its text (one byte a character for ASCII, two to four otherwise) and its parsed value, about seven times the
# text for pins of 800 ASCII characters (measured) and more per character for many short lines. A run has two
# KeptLines (PinLines), and while a read builds the next generation the old one is still held. The lines of a file
# past the limit are parsed at every read, as all lines were before anything was kept.
KEPT_LINE_CHARS = 4 * 1024 * 1024


@dataclass(frozen=True)
class PreparedPinWrite:
    """The complete live JSONL and Markdown replacement, rendered before either file changes."""

    jsonl: str
    md: str
    bad: tuple[int, ...]


def dump_jsonl(rows: Iterable[Row]) -> str:
    """rows as the stored text: one compact JSON object per line (non-ASCII kept), each ending in a newline."""
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def line_value(text: str, parse: Callable[[object], Parsed | Broken]) -> tuple[Parsed | Broken, bool]:
    """(what one non-blank line of a pin file parses to, whether that is a function of the line's text alone).

    The line is decoded as JSON and handed to parse; a line that is not JSON is handed over as None, which every
    record parse calls Broken. Both are verdicts about the text. A line json.loads gives up on for its depth
    (RecursionError) is handed over as None too, but that verdict depends on how deep the caller's stack already
    is, so it is not settled: KeptLines parses such a line again at every read. Never raises for any text."""
    try:
        decoded: object = json.loads(text)
    except RecursionError:
        return parse(None), False
    except ValueError:
        return parse(None), True
    return parse(decoded), True


class KeptLines(Generic[Value]):
    """What each line of one pin file was at the latest read, by the line's own text, so that a line read again is
    not parsed again.

    The key is the whole text of the line and nothing else - no path, no stat, no line number. A parse is a pure
    function of that text, so a kept value is what parsing the line now would give, whatever happened to the file in
    between: there is nothing to invalidate. What is kept is replaced as a whole by every read (values) with the
    lines of that read, so it holds the file as last read and never more, and at most `limit` characters of line
    text (the file's first lines; from the first line that does not fit, none is kept).

    One KeptLines serves one parse for the whole run: values of two different parses must not meet in it (the live
    pins and the Trash each have their own, PinLines). Threads share it without waiting for one another: a
    generation is never changed after it is published, a reader takes the current one and publishes the next, and
    the lock is held only to take or swap that reference - never across a parse. Two readers that miss the same
    line both parse it, to equal values. The values are shared by everyone who reads through it; see KeptPinReader
    for the rule that follows. Nothing is written anywhere (docs/handbook/architecture.md 불변식 10)."""

    def __init__(self, limit: int = KEPT_LINE_CHARS) -> None:
        """Nothing kept yet; at most `limit` characters of line text will be."""
        self._limit: int = limit
        self._held: Mapping[str, Value] = {}
        self._lock: threading.Lock = threading.Lock()

    def held(self) -> Mapping[str, Value]:
        """The lines kept now, each with its value, in the order of the read that kept them. The mapping is the
        published generation itself: it is never changed again, and the caller must not change it or its values."""
        with self._lock:
            return self._held

    def values(self, lines: Sequence[str], fresh: Callable[[str], tuple[Value, bool]]) -> list[Value]:
        """The value of each of lines, in order: the kept one when the line's text was in the last read, else
        fresh(line)[0]. Afterwards what is kept is these lines.

        fresh(line) answers (the line's value, whether to keep it); a value it says not to keep is answered but
        asked for again at the next read. A value is never None: None is how a line that is not kept reads here, so
        a None value would be asked for again at every read. A line that repeats in lines is asked for once. Lines are kept from the
        first on until one does not fit the limit; that line and every later one are not kept."""
        with self._lock:
            old = self._held
        new: dict[str, Value] = {}
        out: list[Value] = []
        chars, full = 0, False
        for text in lines:
            value = old.get(text)
            if value is None:
                value = new.get(text)
            settled = True
            if value is None:
                value, settled = fresh(text)
            out.append(value)
            if settled and not full and text not in new:
                if chars + len(text) > self._limit:
                    full = True
                else:
                    new[text] = value
                    chars += len(text)
        self._swap(new)
        return out

    def _swap(self, new: Mapping[str, Value]) -> Mapping[str, Value]:
        """Publish new as what is kept and answer the generation it replaced, in one step under the lock. The one
        place a kept value leaves: whatever the replaced generation held and new does not is no longer handed out."""
        with self._lock:
            replaced, self._held = self._held, new
        return replaced


@dataclass(frozen=True)
class PinLines:
    """One run's kept lines of its two pin files: `live` for pins.jsonl, `dropped` for the Trash. Each is answered
    by its own parse, so the same text in both files is a pin in one and a Trash copy in the other. The run owns one
    (limn.runtime.resources.RuntimeResources.pin_lines) and hands it to its keeping readers alone."""

    live: KeptLines[Pin | Broken] = field(default_factory=KeptLines)
    dropped: KeptLines[TrashedPin | Broken] = field(default_factory=KeptLines)


def find_pin(rows: list[Row], pid: int) -> Row | None:
    """The first record whose id is pid, or None - a lookup over records as the API shows them (limn.revisions.core)."""
    return next((r for r in rows if r.get("id") == pid), None)


def pin_index(pins: Sequence[Pin], pid: int) -> int | None:
    """The position of the first pin whose id is pid, or None - so a transaction step can replace it in place."""
    return next((i for i, pin in enumerate(pins) if pin.core.id == pid), None)


def top_id(ids: Iterable[int | None]) -> int:
    """The largest pin id among ids, 0 for none. A pin the record parse let through always has an integer id; a
    missing one (a pin built in code without one) counts for nothing."""
    return max((pid for pid in ids if pid is not None), default=0)


@dataclass(frozen=True)
class PinReader:
    """Read capability for one state directory: saved parsed values with no resynchronization or persistence.

    lock is the process-wide lock of this state directory. Every path that touches the pin files holds it - without
    it a read-modify-write race lost most concurrent writes (of 30 pins saved at once only 2 survived, observed). It
    must be re-entrant: a caller bundles a transaction with the Trash write or its notices under the same lock
    (restore_pin, drop_pin). parse turns one parsed pins.jsonl line into its pin or Broken, parse_trashed one Trash
    line into its TrashedPin or Broken (limn.pins.record).
    """

    files: PinFiles
    lock: threading.RLock
    parse: Callable[[object], Pin | Broken]
    parse_trashed: Callable[[object], TrashedPin | Broken]

    def read_jsonl(
        self,
        path: Path,
        parse: Callable[[object], Parsed | Broken],
        kept: KeptLines[Parsed | Broken] | None = None,
    ) -> tuple[list[Parsed], list[int]]:
        """(what each readable line of a JSONL file parses to, broken line numbers); a missing file is ([], []). Takes
        no lock.

        A line that is not JSON, or that parse calls Broken, is skipped with a warning on stderr and its number
        returned - one bad record must not turn every request into a 500. Blank lines are ignored.

        With kept, a line whose text was in the last read through it is answered with the value kept for it instead
        of being parsed (KeptLines.values), and what is kept becomes this read's lines - none for a missing file.
        The answer is the same either way; the lists are the caller's own, the values in them are shared. kept must
        be the one that serves this parse."""

        def fresh(line: str) -> tuple[Parsed | Broken, bool]:
            """One line's value by this read's parse, and whether it may be kept (line_value)."""
            return line_value(line, parse)

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            if kept is not None:
                kept.values((), fresh)
            return [], []
        numbered = [(i, t) for i, t in enumerate(text.splitlines(), 1) if t.strip()]
        texts = [t for _, t in numbered]
        values = [fresh(t)[0] for t in texts] if kept is None else kept.values(texts, fresh)
        out: list[Parsed] = []
        bad = []
        for (i, _), parsed in zip(numbered, values, strict=True):
            if isinstance(parsed, Broken):
                bad.append(i)
                continue
            out.append(parsed)
        if bad:
            diagnostics.emit(
                "damaged pin file:" + str(path),
                lambda: "warning: failed to read %d line(s) of %s (line %s)." % (len(bad), path.name, bad[:10]),
            )
        return out, bad

    def read_pins(self) -> tuple[list[Pin], list[int]]:
        """The live pins, parsed, and pins.jsonl's broken line numbers, as read_jsonl(). Takes no lock and never
        re-syncs."""
        return self.read_jsonl(self.files.pins_jsonl, self.parse)

    def read_dropped(self) -> tuple[list[TrashedPin], list[int]]:
        """The Trash entries, parsed, and the Trash file's broken line numbers, as read_jsonl(). Takes no lock: only a
        file that finished an atomic replace is ever read, so a reader never sees a half-written Trash."""
        return self.read_jsonl(self.files.dropped, self.parse_trashed)

    def snapshot(self) -> list[Pin]:
        """Return saved pins under the transaction lock; positions and revisions always describe durable records."""
        with self.lock:
            return self.read_pins()[0]


@dataclass(frozen=True)
class KeptPinReader(PinReader):
    """The reader issued to callers that only read: a PinReader whose reads of the two pin files skip the parse of
    every line the run has read before (lines, the run's PinLines).

    The pins it hands out are shared with every other caller of the run's keeping readers, in this request and in
    later ones. A caller owns the list it gets and nothing in it: it must not change a pin, a Trash copy, or any
    value inside one - the dicts and lists a record holds, and so the nested values of `pin.record`, whose outermost
    dict alone is new at every call. A caller that will write what it read to a pin file reads through a PinStore
    instead, which has no kept lines to read."""

    lines: PinLines

    def read_pins(self) -> tuple[list[Pin], list[int]]:
        """The live pins and pins.jsonl's broken line numbers, as PinReader.read_pins(), each line parsed at most
        once per run while its text stays the same. Takes no lock and never re-syncs."""
        return self.read_jsonl(self.files.pins_jsonl, self.parse, self.lines.live)

    def read_dropped(self) -> tuple[list[TrashedPin], list[int]]:
        """The Trash entries and the Trash file's broken line numbers, as PinReader.read_dropped(), each line parsed
        at most once per run while its text stays the same. Takes no lock."""
        return self.read_jsonl(self.files.dropped, self.parse_trashed, self.lines.dropped)


@dataclass(frozen=True)
class PinStore(PinReader):
    """A writer issued only outside the HTTP read scope; all mutations retain the transaction lock."""

    sync: Callable[[list[Pin]], bool]
    render: Callable[[Sequence[Pin]], str]

    def __post_init__(self) -> None:
        """Refuse construction from GET/HEAD, including indirectly through captured feature services."""
        require_writer()

    def unique_path(self, stem: str, suffix: str) -> Path:
        """<state>/<stem><suffix>, or the first free <stem>-1<suffix>, <stem>-2<suffix>, ... - so archiving twice in
        the same second never overwrites."""
        p = self.files.state / (stem + suffix)
        k = 1
        while p.exists():
            p = self.files.state / ("%s-%d%s" % (stem, k, suffix))
            k += 1
        return p

    def _keep_corrupt(self, path: Path) -> None:
        """Copies path's current bytes (and mtime) to <name>.corrupt-<local time>.bak before a rewrite drops its
        unreadable lines - they are never lost silently. Nothing if path does not exist."""
        require_writer()
        if path.exists():
            shutil.copy2(path, self.unique_path("%s.corrupt-%s" % (path.name, time.strftime("%Y%m%d-%H%M%S")), ".bak"))

    def write_pins(self, pins: Sequence[Pin], bad: list[int] | None = None) -> None:
        """Rewrites pins.jsonl with pins, each as its stored record, then pins.md from them. Callers hold the lock
        (transact does).

        pins.md is rendered in memory first: if rendering fails nothing is written - committing pins.jsonl and then
        answering 500 would make the client retry and create a duplicate pin. With bad (pins.jsonl had unreadable
        lines) the original file is kept as a .corrupt-*.bak before it is replaced."""
        self.write_prepared(self.prepare_pins(pins, bad))

    def prepare_pins(self, pins: Sequence[Pin], bad: Sequence[int] | None = None) -> PreparedPinWrite:
        """Render and serialize a complete live replacement without touching disk; callers hold the store lock."""
        md = self.render(pins)
        return PreparedPinWrite(dump_jsonl(pin.record for pin in pins), md, tuple(bad or ()))

    def write_prepared(self, prepared: PreparedPinWrite) -> None:
        """Commit prepared live bytes in JSONL then Markdown order, backing up unreadable original lines first.

        Callers hold the store lock and must not change the pins between preparation and this write."""
        require_writer()
        if prepared.bad:
            self._keep_corrupt(self.files.pins_jsonl)
        atomic_write(self.files.pins_jsonl, prepared.jsonl)
        atomic_write(self.files.pins_md, prepared.md)

    def transact(
        self, fn: Callable[[list[Pin]], tuple[T, bool]], before_write: Callable[[T], None] | None = None
    ) -> tuple[list[Pin], T]:
        """The write-order invariant: with the lock -> read -> sync -> fn applies the change -> prepare -> commit.

        fn(pins) changes the list in place - appends a pin, removes one, or replaces one with its next state - only
        after its own checks pass, and returns (result, whether it changed the pins): a refused request is a result
        with nothing changed, never an exception. The change is applied after sync, so a caller-supplied lo/hi is
        never reverted by a stale anchor. The file is written when sync or fn changed the pins - a read-only step
        still writes a re-sync. If fn raises (a defect or an infrastructure failure), nothing is written, not even
        the re-sync, and the exception propagates. An optional before_write step runs only after both replacement
        texts are prepared and before the live replacement, for the Trash-first drop. Returns (the pins as written or
        read, fn's result). A manuscript read failure propagates before fn or any save, preserving the batch."""
        require_writer()
        with self.lock:
            pins, bad = self.read_pins()
            synced = self.sync(pins)
            result, mutated = fn(pins)
            if synced or mutated:
                prepared = self.prepare_pins(pins, bad)
                if before_write is not None:
                    before_write(result)
                self.write_prepared(prepared)
                if mutated:
                    changed()
            return pins, result

    def render_md(self, pins: Sequence[Pin]) -> None:
        """Rewrites pins.md from pins alone (startup, clear). Callers hold the lock."""
        require_writer()
        atomic_write(self.files.pins_md, self.render(pins))

    def clear(self, before_archive: Callable[[Sequence[Pin]], None] | None = None) -> tuple[int, str | None]:
        """Archives pins.jsonl to pins_<local time>.jsonl.bak (never over an earlier archive) and renders an empty
        pins.md, under the lock. Rendering happens before the archive move, so a renderer error leaves the live file
        in place. An optional before_archive step receives the live snapshot after rendering, for clearing its Trash
        shadows; its failure also leaves the live file in place. pins.seq is untouched, so ids keep incrementing.
        Returns (how many readable pins there were, the archive's file name or None without pins.jsonl)."""
        require_writer()
        with self.lock:
            pins, _ = self.read_pins()
            n, archive = len(pins), None
            md = self.render([])
            if before_archive is not None:
                before_archive(pins)
            if self.files.pins_jsonl.exists():
                dest = self.unique_path("pins_%s" % time.strftime("%y%m%d_%H%M%S"), ".jsonl.bak")
                self.files.pins_jsonl.rename(dest)
                archive = dest.name
            atomic_write(self.files.pins_md, md)
        changed()
        return n, archive

    def write_dropped(self, entries: Sequence[TrashedPin], bad: list[int] | None = None) -> None:
        """Rewrites the Trash with entries, each as its stored record. Callers hold the lock. With bad (the Trash had
        unreadable lines) the original file is kept as a .corrupt-*.bak first, as write_pins does for pins.jsonl."""
        require_writer()
        if bad:
            self._keep_corrupt(self.files.dropped)
        atomic_write(self.files.dropped, dump_jsonl(entry.record for entry in entries))
        changed()

    def _max_id_in(self, path: Path) -> int:
        """The largest id among path's readable records, 0 for none. Read with the live-pin parse: an archive holds
        live records, and a Trash entry passes the same check."""
        return top_id(pin.core.id for pin in self._pins_in(path))

    def _pins_in(self, path: Path) -> list[Pin]:
        """The readable records of path parsed as live pins (read_jsonl with the live-pin parse)."""
        read: tuple[list[Pin], list[int]] = self.read_jsonl(path, self.parse)
        return read[0]

    def init_seq(self) -> None:
        """If pins.seq is missing, fills it once, under the lock, with the largest id across the live, archived
        (pins_*.jsonl.bak) and dropped records - a one-time migration for a state directory older than pins.seq."""
        require_writer()
        with self.lock:
            if self.files.seq.exists():
                return
            m = self._max_id_in(self.files.pins_jsonl)
            for p in list(self.files.state.glob("pins_*.jsonl.bak")) + [self.files.dropped]:
                m = max(m, self._max_id_in(p))
            atomic_write(self.files.seq, str(m))

    def next_id(self, pins: Sequence[Pin]) -> int:
        """Hands out the next pin id and records it in pins.seq: one more than both pins.seq and every id in pins
        (an unreadable pins.seq counts as 0). An id is never reused - "#2" in a chat message must never end up
        pointing at a different pin. Called inside a transaction, which holds the lock."""
        require_writer()
        try:
            last = int(self.files.seq.read_text().strip() or 0)
        except (OSError, ValueError):
            last = 0
        nid = max(last, top_id(pin.core.id for pin in pins)) + 1
        atomic_write(self.files.seq, str(nid))
        return nid

    def maintain(self, days: int, now: float) -> None:
        """Prepare current pins, Markdown and retained Trash before any replacement; leave unchanged bytes alone.

        Original damaged bytes are included as backups in the same prepared replacement set.
        Manuscript read failures propagate before preparation, preserving this entire state-file batch for retry.
        """
        require_writer()
        with self.lock:
            pins, bad = self.read_pins()
            synced = self.sync(pins)
            entries, trash_bad = self.read_dropped()
            keep = unexpired(without_live_shadows(entries, pins), days, now)
            md = self.render(pins)
            if self.files.pins_md.exists():
                old = self.files.pins_md.read_text(encoding="utf-8")
                stamp = r"(?m)^갱신: \d{4}-\d{2}-\d{2} \d{2}:\d{2}"
                if re.sub(stamp, "갱신:", old) == re.sub(stamp, "갱신:", md):
                    md = old
            replacements: dict[Path, str | bytes] = {self.files.pins_md: md}
            if synced:
                replacements[self.files.pins_jsonl] = dump_jsonl(pin.record for pin in pins)
            if len(keep) != len(entries):
                replacements[self.files.dropped] = dump_jsonl(entry.record for entry in keep)
            if synced and bad:
                backup = self.unique_path("pins.jsonl.corrupt-" + time.strftime("%Y%m%d-%H%M%S"), ".bak")
                replacements[backup] = self.files.pins_jsonl.read_bytes()
            if len(keep) != len(entries) and trash_bad:
                backup = self.unique_path("pins.dropped.jsonl.corrupt-" + time.strftime("%Y%m%d-%H%M%S"), ".bak")
                replacements[backup] = self.files.dropped.read_bytes()
            replacements = {
                path: text
                for path, text in replacements.items()
                if not path.exists() or path.read_bytes() != (text.encode("utf-8") if isinstance(text, str) else text)
            }
            replace_files(replacements)
