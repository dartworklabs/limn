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

This module knows no run arguments and no HTTP. What the order needs from outside comes in as fields of PinStore,
set by the composition root (server.pin_store()): where the files are (PinFiles), the process-wide lock, which
parsed line the store trusts (valid), the anchor re-sync of rows against the .tex files (sync), the pins.md
renderer (render) and the exception a transaction step raises to refuse its request (refusal). It creates no lock
and holds no state of its own, so a store value is cheap to make per call.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias, TypeVar

from limn.files import atomic_write

# One stored pin (or Trash entry) as the store reads and writes it: a JSON object, mutated in place by a transaction.
Row: TypeAlias = dict[str, Any]
T = TypeVar("T")


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


def dump_jsonl(rows: list[Row]) -> str:
    """rows as the stored text: one compact JSON object per line (non-ASCII kept), each ending in a newline."""
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def find_pin(rows: list[Row], pid: int) -> Row | None:
    """The first row whose id is pid (the row itself, so a transaction step can change it in place), or None."""
    return next((r for r in rows if r.get("id") == pid), None)


@dataclass(frozen=True)
class PinStore:
    """The pin files of one state directory and the lock and order every change to them goes through.

    lock is the process-wide lock of this state directory. Every path that touches the pin files holds it - without
    it a read-modify-write race lost most concurrent writes (of 30 pins saved at once only 2 survived, observed). It
    must be re-entrant: a caller bundles a transaction with the Trash write or its notices under the same lock
    (restore_pin, drop_pin). valid decides which parsed line is a record the store trusts; sync re-matches rows'
    line numbers in place and says whether it changed any; render turns the live pins into pins.md's text; a
    transaction step raising refusal is a refused request, after which the re-sync is still written.
    """

    files: PinFiles
    lock: threading.RLock
    valid: Callable[[object], bool]
    sync: Callable[[list[Row]], bool]
    render: Callable[[list[Row]], str]
    refusal: type[Exception]

    def read_jsonl(self, path: Path) -> tuple[list[Row], list[int]]:
        """(records, broken line numbers) of a JSONL file; a missing file is ([], []). Takes no lock.

        A line that is not JSON, or parses to something valid() refuses, is skipped with a warning on stderr and
        its number returned - one bad record must not turn every request into a 500. Blank lines are ignored."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return [], []
        rows, bad = [], []
        for i, t in enumerate(text.splitlines(), 1):
            if not t.strip():
                continue
            try:
                r = json.loads(t)
            except (ValueError, RecursionError):
                r = None
            if not self.valid(r):
                bad.append(i)
                continue
            rows.append(r)
        if bad:
            print(
                "warning: failed to read %d line(s) of %s (line %s)." % (len(bad), path.name, bad[:10]), file=sys.stderr
            )
        return rows, bad

    def read_pins(self) -> tuple[list[Row], list[int]]:
        """The live pins and pins.jsonl's broken line numbers, as read_jsonl(). Takes no lock and never re-syncs."""
        return self.read_jsonl(self.files.pins_jsonl)

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

    def write_pins(self, rows: list[Row], bad: list[int] | None = None) -> None:
        """Rewrites pins.jsonl with rows, then pins.md from them. Callers hold the lock (transact does).

        pins.md is rendered in memory first: if rendering fails nothing is written - committing pins.jsonl and then
        answering 500 would make the client retry and create a duplicate pin. With bad (pins.jsonl had unreadable
        lines) the original file is kept as a .corrupt-*.bak before it is replaced."""
        md = self.render(rows)
        data = dump_jsonl(rows)
        if bad:
            self._keep_corrupt(self.files.pins_jsonl)
        atomic_write(self.files.pins_jsonl, data)
        atomic_write(self.files.pins_md, md)

    def transact(self, fn: Callable[[list[Row]], tuple[T, bool]]) -> tuple[list[Row], T]:
        """The write-order invariant: with the lock -> read -> sync -> fn applies the change -> write_pins.

        fn(rows) changes rows in place, only after its own checks pass, and returns (result, whether it changed
        rows). The change is applied after sync, so a caller-supplied lo/hi is never reverted by a stale anchor.
        The file is written when sync or fn changed rows - a read-only step still writes a re-sync. If fn raises
        refusal, the re-sync (if any) is written and the exception propagates; any other exception writes nothing.
        Returns (rows as written or read, fn's result)."""
        with self.lock:
            rows, bad = self.read_pins()
            synced = self.sync(rows)
            try:
                result, mutated = fn(rows)
            except self.refusal:
                if synced:
                    self.write_pins(rows, bad)
                raise
            if synced or mutated:
                self.write_pins(rows, bad)
            return rows, result

    def snapshot(self) -> list[Row]:
        """The live pins, re-synced (and written back if the re-sync changed them) - a read-only transaction."""
        rows, _ = self.transact(lambda rows: (None, False))
        return rows

    def render_md(self, rows: list[Row]) -> None:
        """Rewrites pins.md from rows alone (startup, clear). Callers hold the lock."""
        atomic_write(self.files.pins_md, self.render(rows))

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

    def read_dropped(self) -> tuple[list[Row], list[int]]:
        """The Trash entries and the Trash file's broken line numbers, as read_jsonl(). Takes no lock: only a file
        that finished an atomic replace is ever read, so a reader never sees a half-written Trash."""
        return self.read_jsonl(self.files.dropped)

    def write_dropped(self, rows: list[Row], bad: list[int] | None = None) -> None:
        """Rewrites the Trash with rows. Callers hold the lock. With bad (the Trash had unreadable lines) the original
        file is kept as a .corrupt-*.bak first, as write_pins does for pins.jsonl."""
        if bad:
            self._keep_corrupt(self.files.dropped)
        atomic_write(self.files.dropped, dump_jsonl(rows))

    def _max_id_in(self, path: Path) -> int:
        """The largest id among path's readable records, 0 for none."""
        rows, _ = self.read_jsonl(path)
        top: int = max((r["id"] for r in rows), default=0)
        return top

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

    def next_id(self, rows: list[Row]) -> int:
        """Hands out the next pin id and records it in pins.seq: one more than both pins.seq and every id in rows
        (an unreadable pins.seq counts as 0). An id is never reused - "#2" in a chat message must never end up
        pointing at a different pin. Called inside a transaction, which holds the lock."""
        try:
            last = int(self.files.seq.read_text().strip() or 0)
        except (OSError, ValueError):
            last = 0
        nid: int = max(last, max((r["id"] for r in rows), default=0)) + 1
        atomic_write(self.files.seq, str(nid))
        return nid
