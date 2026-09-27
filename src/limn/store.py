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

This module knows no run arguments and no HTTP. What the order needs from outside comes in as fields of PinStore,
set by the composition root (server.pin_store()): where the files are (PinFiles), the process-wide lock, the record
parse of a live line and of a Trash line (parse, parse_trashed), the anchor re-sync of the pins against the .tex
files (sync) and the pins.md renderer (render). It creates no lock and holds no state of its own, so a store value is
cheap to make per call.
"""

import json
import shutil
import sys
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias, TypeVar

from limn.files import atomic_write
from limn.pins.model import Pin, TrashedPin
from limn.pins.record import Broken

# One stored record as JSON gives it: a pin or a Trash entry as written, or a pin as the API shows it.
Row: TypeAlias = dict[str, Any]
T = TypeVar("T")
# What one readable line of a pin file parses to: a live pin or a Trash copy.
Parsed = TypeVar("Parsed")


@dataclass(frozen=True)
class PinFiles:
    """Where the pin store keeps its files: fixed names under one state directory."""

    state: Path

    @property
    def pins_jsonl(self) -> Path:
        """The live pins."""
        return self.state / "pins.jsonl"

    @property
    def pins_md(self) -> Path:
        """The agents' work list, rendered from the live pins."""
        return self.state / "pins.md"

    @property
    def dropped(self) -> Path:
        """The Trash."""
        return self.state / "pins.dropped.jsonl"

    @property
    def seq(self) -> Path:
        """The last pin id handed out."""
        return self.state / "pins.seq"


def dump_jsonl(rows: Iterable[Row]) -> str:
    """rows as the stored text: one compact JSON object per line (non-ASCII kept), each ending in a newline."""
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def find_pin(rows: list[Row], pid: int) -> Row | None:
    """The first record whose id is pid, or None - a lookup over records as the API shows them (limn.revisions)."""
    return next((r for r in rows if r.get("id") == pid), None)


def pin_index(pins: Sequence[Pin], pid: int) -> int | None:
    """The position of the first pin whose id is pid, or None - so a transaction step can replace it in place."""
    return next((i for i, pin in enumerate(pins) if pin.core.id == pid), None)


def top_id(ids: Iterable[int | None]) -> int:
    """The largest pin id among ids, 0 for none. A pin the record parse let through always has an integer id; a
    missing one (a pin built in code without one) counts for nothing."""
    return max((pid for pid in ids if pid is not None), default=0)


@dataclass(frozen=True)
class PinStore:
    """The pin files of one state directory and the lock and order every change to them goes through.

    lock is the process-wide lock of this state directory. Every path that touches the pin files holds it - without
    it a read-modify-write race lost most concurrent writes (of 30 pins saved at once only 2 survived, observed). It
    must be re-entrant: a caller bundles a transaction with the Trash write or its notices under the same lock
    (restore_pin, drop_pin). parse turns one parsed pins.jsonl line into its pin or Broken, parse_trashed one Trash
    line into its TrashedPin or Broken (limn.pins.record); sync re-matches the pins' line numbers, replacing a pin it
    moved in the list, and says whether it changed any; render turns the live pins into pins.md's text.
    """

    files: PinFiles
    lock: threading.RLock
    parse: Callable[[object], Pin | Broken]
    parse_trashed: Callable[[object], TrashedPin | Broken]
    sync: Callable[[list[Pin]], bool]
    render: Callable[[Sequence[Pin]], str]

    def read_jsonl(self, path: Path, parse: Callable[[object], Parsed | Broken]) -> tuple[list[Parsed], list[int]]:
        """(what each readable line of a JSONL file parses to, broken line numbers); a missing file is ([], []). Takes
        no lock.

        A line that is not JSON, or that parse calls Broken, is skipped with a warning on stderr and its number
        returned - one bad record must not turn every request into a 500. Blank lines are ignored."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return [], []
        out: list[Parsed] = []
        bad = []
        for i, t in enumerate(text.splitlines(), 1):
            if not t.strip():
                continue
            try:
                r = json.loads(t)
            except (ValueError, RecursionError):
                r = None
            parsed = parse(r)
            if isinstance(parsed, Broken):
                bad.append(i)
                continue
            out.append(parsed)
        if bad:
            print(
                "warning: failed to read %d line(s) of %s (line %s)." % (len(bad), path.name, bad[:10]), file=sys.stderr
            )
        return out, bad

    def read_pins(self) -> tuple[list[Pin], list[int]]:
        """The live pins, parsed, and pins.jsonl's broken line numbers, as read_jsonl(). Takes no lock and never
        re-syncs."""
        return self.read_jsonl(self.files.pins_jsonl, self.parse)

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
        if path.exists():
            shutil.copy2(path, self.unique_path("%s.corrupt-%s" % (path.name, time.strftime("%Y%m%d-%H%M%S")), ".bak"))

    def write_pins(self, pins: Sequence[Pin], bad: list[int] | None = None) -> None:
        """Rewrites pins.jsonl with pins, each as its stored record, then pins.md from them. Callers hold the lock
        (transact does).

        pins.md is rendered in memory first: if rendering fails nothing is written - committing pins.jsonl and then
        answering 500 would make the client retry and create a duplicate pin. With bad (pins.jsonl had unreadable
        lines) the original file is kept as a .corrupt-*.bak before it is replaced."""
        md = self.render(pins)
        data = dump_jsonl(pin.record for pin in pins)
        if bad:
            self._keep_corrupt(self.files.pins_jsonl)
        atomic_write(self.files.pins_jsonl, data)
        atomic_write(self.files.pins_md, md)

    def transact(self, fn: Callable[[list[Pin]], tuple[T, bool]]) -> tuple[list[Pin], T]:
        """The write-order invariant: with the lock -> read -> sync -> fn applies the change -> write_pins.

        fn(pins) changes the list in place - appends a pin, removes one, or replaces one with its next state - only
        after its own checks pass, and returns (result, whether it changed the pins): a refused request is a result
        with nothing changed, never an exception. The change is applied after sync, so a caller-supplied lo/hi is
        never reverted by a stale anchor. The file is written when sync or fn changed the pins - a read-only step
        still writes a re-sync. If fn raises (a defect or an infrastructure failure), nothing is written, not even
        the re-sync, and the exception propagates. Returns (the pins as written or read, fn's result)."""
        with self.lock:
            pins, bad = self.read_pins()
            synced = self.sync(pins)
            result, mutated = fn(pins)
            if synced or mutated:
                self.write_pins(pins, bad)
            return pins, result

    def snapshot(self) -> list[Pin]:
        """The live pins, re-synced (and written back if the re-sync changed them) - a read-only transaction."""
        pins, _ = self.transact(lambda pins: (None, False))
        return pins

    def render_md(self, pins: Sequence[Pin]) -> None:
        """Rewrites pins.md from pins alone (startup, clear). Callers hold the lock."""
        atomic_write(self.files.pins_md, self.render(pins))

    def clear(self) -> tuple[int, str | None]:
        """Archives pins.jsonl to pins_<local time>.jsonl.bak (never over an earlier archive) and renders an empty
        pins.md, under the lock. pins.seq is untouched, so ids keep incrementing. Returns (how many readable pins
        there were, the archive's file name or None when there was no pins.jsonl)."""
        with self.lock:
            n, archive = len(self.read_pins()[0]), None
            if self.files.pins_jsonl.exists():
                dest = self.unique_path("pins_%s" % time.strftime("%y%m%d_%H%M%S"), ".jsonl.bak")
                self.files.pins_jsonl.rename(dest)
                archive = dest.name
            self.render_md([])
        return n, archive

    def read_dropped(self) -> tuple[list[TrashedPin], list[int]]:
        """The Trash entries, parsed, and the Trash file's broken line numbers, as read_jsonl(). Takes no lock: only a
        file that finished an atomic replace is ever read, so a reader never sees a half-written Trash."""
        return self.read_jsonl(self.files.dropped, self.parse_trashed)

    def write_dropped(self, entries: Sequence[TrashedPin], bad: list[int] | None = None) -> None:
        """Rewrites the Trash with entries, each as its stored record. Callers hold the lock. With bad (the Trash had
        unreadable lines) the original file is kept as a .corrupt-*.bak first, as write_pins does for pins.jsonl."""
        if bad:
            self._keep_corrupt(self.files.dropped)
        atomic_write(self.files.dropped, dump_jsonl(entry.record for entry in entries))

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
        try:
            last = int(self.files.seq.read_text().strip() or 0)
        except (OSError, ValueError):
            last = 0
        nid = max(last, top_id(pin.core.id for pin in pins)) + 1
        atomic_write(self.files.seq, str(nid))
        return nid
