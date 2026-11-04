"""Bounded, process-local diagnostics for failures reachable by repeated reads."""

import hashlib
import sys
import threading
from collections.abc import Callable


class BoundedDiagnostics:
    """Print each cause once, at most 64 causes and 8 KiB per cause over this process's lifetime."""

    def __init__(self) -> None:
        """Keep only fixed-size digests; untrusted messages cannot grow the retained keys."""
        self._seen: set[bytes] = set()
        self._lock = threading.Lock()

    def emit(self, cause: str, message: Callable[[], str]) -> None:
        """Emit a capped diagnostic for a new cause, suppressing duplicates and excess distinct causes."""
        key = hashlib.sha256(cause.encode("utf-8", errors="replace")).digest()
        with self._lock:
            if key in self._seen or len(self._seen) >= 64:
                return
            self._seen.add(key)
            print(message().encode("utf-8", errors="replace")[:8192].decode("utf-8", errors="replace"), file=sys.stderr)


diagnostics = BoundedDiagnostics()
