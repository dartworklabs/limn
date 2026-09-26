"""Crash-safe file replacement shared by every writer of the state directory (pins, people, tokens, build history).

A reader - another request, another process, an agent reading pins.md - must only ever see the old file or the
new one, never a half-written file. That is the whole contract here; what gets written is the caller's business.
"""
from __future__ import annotations

import contextlib
import os
import threading
from pathlib import Path


def atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    """Write to a temp file in the same directory, then os.replace - readers only ever see the old file or the new one.
    With mode (e.g. 0o600 for tokens.json) the temp file is created with that mode, so the content is never readable by others, even briefly."""
    tmp = path.with_name(".%s.tmp%d.%d" % (path.name, os.getpid(), threading.get_ident()))
    if mode is None:
        fh = open(tmp, "w", encoding="utf-8")
    else:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        os.fchmod(fd, mode)                               # the umask may have narrowed or (never) widened it
        fh = open(fd, "w", encoding="utf-8")
    with fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
