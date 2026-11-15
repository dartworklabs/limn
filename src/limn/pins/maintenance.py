"""Request-independent pin upkeep at startup, on source changes and every sixty seconds."""

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from limn.pins.store import PinStore
from limn.platform.diagnostics import diagnostics
from limn.platform.effects import require_writer

# A few metadata calls every two seconds keep saved positions fresh without idle content reads.
CHECK_INTERVAL = 2.0
PERIODIC_INTERVAL = 60.0
# One mark pass asks SyncTeX at most this many pins' worth of marks and stops at this many seconds; the pins it left
# are taken on the next run (the cache remembers what it filled), so a big document makes progress and never starves.
MARK_LIMIT = 200
MARK_SECONDS = 10.0
# The tighter budget of the pass a build runs inline (PinCommands.fill_line_marks_after_build); upkeep takes the rest.
MARK_BUILD_SECONDS = 2.0
# How long a build waits for an upkeep run in progress before it leaves the resync and the marks to that run.
MARK_BUILD_WAIT_SECONDS = 1.0


def signature(path: Path) -> tuple[int, int, int] | None:
    """Read only metadata, treating disappearance or stat failure as a change that can later recover."""
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size, stat.st_ino
    except OSError:
        return None


@dataclass
class PinMaintenance:
    """One run's upkeep; overlapping passes do no work and idle checks only stat cached names."""

    store: Callable[[], PinStore]
    days: int
    sources: Callable[[], Iterable[Path]] = lambda: ()
    # The pass that fills line pins' marks for the builds on screen (PinCommands.fill_line_marks): memory only, it writes
    # no pin and takes no lock, so it runs after the store lock is released.
    marks: Callable[[], int] = lambda: 0
    _running: threading.Lock = field(default_factory=threading.Lock)
    _observed: dict[Path, tuple[int, int, int] | None] = field(default_factory=dict)
    _completed: float = 0.0

    def run(self, marks: Callable[[], int] | None = None, wait: bool = False) -> None:
        """Converge once, keeping originals and the last successful baseline on failure.

        marks replaces the mark pass of this run (the build path passes its own, shorter-budget pass). wait is a separate
        decision: False skips at once when another run is in progress; True (the build path, on a request thread) waits
        at most MARK_BUILD_WAIT_SECONDS for it and then skips this run with a diagnostic. Skipping is safe: the run in
        progress resyncs and fills marks itself, and the worst outcome is a mark missing for up to a minute (the old,
        dotted position), never a mark computed from lines that did not follow the manuscript. A pin the pass budget
        cut off waits as long: this run resets the upkeep cycle's own timers, so the next fill comes with the
        periodic run, not on the next tick.

        Capture source stamps before reading them, so a change during a pass is still pending next tick.
        The JSONL stamp discovers pins added by POST without reading that file on idle ticks.
        """
        require_writer()
        got = self._running.acquire(timeout=MARK_BUILD_WAIT_SECONDS) if wait else self._running.acquire(blocking=False)
        if not got:
            if wait:
                diagnostics.emit("pin maintenance:busy", lambda: "warning: pin maintenance busy: build run skipped")
            return
        resynced = False
        try:
            store = self.store()
            with store.lock:
                observed = {path: signature(path) for path in self.sources()}
                store.maintain(self.days, time.time())
                observed[store.files.pins_jsonl] = signature(store.files.pins_jsonl)
                self._observed = observed
                self._completed = time.monotonic()
            resynced = True
        except Exception as error:  # noqa: BLE001 — upkeep must retry without stopping the listener
            message = "warning: pin maintenance failed: %s" % error
            diagnostics.emit("pin maintenance:" + type(error).__name__, lambda: message)
        finally:
            self._running.release()
        # After the store lock and the overlap guard are released: a pass that overshoots its budget must hold up
        # neither a pin write nor the next upkeep run.
        if (
            resynced
        ):  # a mark computed from lines that did not follow the manuscript would stand solid in the wrong place
            self._fill_marks(marks or self.marks)

    def _fill_marks(self, marks: Callable[[], int]) -> None:
        """Run the mark pass, outside the pin store lock: SyncTeX may take up to its own timeout per lookup, which no pin
        write should wait for. A failure is reported and never stops the upkeep."""
        try:
            marks()
        except Exception as error:  # noqa: BLE001 — marks are derived and refilled by the next run
            message = "warning: line mark pass failed: %s" % error
            diagnostics.emit("pin marks:" + type(error).__name__, lambda: message)

    def watch(self, stop: threading.Event, every: float = PERIODIC_INTERVAL) -> None:
        """Check cached source/registry stamps without requests; stop promptly while waiting.

        A changed signature retries at the next tick until a pass completes. Periodic upkeep also refreshes
        time-derived Markdown and Trash when the manuscript is unchanged.
        """
        while not stop.wait(min(CHECK_INTERVAL, every)):
            if (
                not self._observed
                or time.monotonic() - self._completed >= every
                or any(signature(path) != stamp for path, stamp in self._observed.items())
            ):
                self.run()
