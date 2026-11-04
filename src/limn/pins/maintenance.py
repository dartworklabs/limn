"""Request-independent pin upkeep, single-flight at startup and every sixty seconds."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from limn.pins.store import PinStore
from limn.platform.diagnostics import diagnostics
from limn.platform.effects import require_writer


@dataclass
class PinMaintenance:
    """One run's upkeep; calls that overlap an active pass do no work and create no threads."""

    store: Callable[[], PinStore]
    days: int
    _running: threading.Lock = field(default_factory=threading.Lock)

    def run(self) -> None:
        """Converge files once, preserving originals on failure and retrying on the next independent tick."""
        require_writer()
        if not self._running.acquire(blocking=False):
            return
        try:
            self.store().maintain(self.days, time.time())
        except Exception as error:  # noqa: BLE001 — upkeep must retry without stopping the listener
            message = "warning: pin maintenance failed: %s" % error
            diagnostics.emit("pin maintenance:" + type(error).__name__, lambda: message)
        finally:
            self._running.release()

    def watch(self, stop: threading.Event, every: float = 60.0) -> None:
        """Wait between completed passes, exiting promptly on shutdown; requests never trigger a pass."""
        while not stop.wait(every):
            self.run()
