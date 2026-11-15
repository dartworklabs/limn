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

    def run(self) -> None:
        """Converge once, keeping originals and the last successful baseline on failure.

        Capture source stamps before reading them, so a change during a pass is still pending next tick.
        The JSONL stamp discovers pins added by POST without reading that file on idle ticks.
        """
        require_writer()
        if not self._running.acquire(blocking=False):
            return
        try:
            store = self.store()
            with store.lock:
                observed = {path: signature(path) for path in self.sources()}
                store.maintain(self.days, time.time())
                observed[store.files.pins_jsonl] = signature(store.files.pins_jsonl)
                self._observed = observed
                self._completed = time.monotonic()
        except Exception as error:  # noqa: BLE001 — upkeep must retry without stopping the listener
            message = "warning: pin maintenance failed: %s" % error
            diagnostics.emit("pin maintenance:" + type(error).__name__, lambda: message)
        finally:
            self._running.release()
        # After the store lock and the overlap guard are released: a pass that overshoots its budget must hold up
        # neither a pin write nor the next upkeep run.
        self._fill_marks()

    def _fill_marks(self) -> None:
        """Run the mark pass, outside the pin store lock: SyncTeX may take up to its own timeout per lookup, which no pin
        write should wait for. A failure is reported and never stops the upkeep."""
        try:
            self.marks()
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
