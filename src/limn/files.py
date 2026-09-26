"""File helpers shared across the server: crash-safe replacement, and where a named path lies in the manuscript tree.

atomic_write serves every writer of the state directory (pins, people, tokens, build history): a reader - another
request, another process, an agent reading pins.md - must only ever see the old file or the new one, never a
half-written file. What gets written is the caller's business. store_lock serializes one read-modify-write of a state
file across processes (the server and `limn token` / `limn member`).

file_in_tree is the one rule for a path a request or SyncTeX names inside the manuscript tree: the request parsers
(limn.web.parse) turn its refusals into 400 answers, the selection resolver (server.pick) into its own message.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

PATH_MAX_CHARS = 4096              # a longer name is refused before it reaches the file system


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


@contextlib.contextmanager
def store_lock(state: Path, name: str) -> Iterator[None]:
    """Cross-process lock around one read-modify-write of a state file. The running server (record_person) and
    `limn member` / `limn token` may write the same file at once; a thread lock alone would let one of them
    overwrite the other's change with stale data. The lock file (.<name>.lock) stays in the state dir."""
    fd = os.open(str(Path(state) / (".%s.lock" % name)), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)                                     # closing the descriptor releases the lock


@dataclass(frozen=True)
class BadPath:
    """Not a usable path: not a string, empty, longer than PATH_MAX_CHARS, or containing a NUL."""


@dataclass(frozen=True)
class OutsideTree:
    """The path, symlinks resolved, lies outside the tree - or it cannot be resolved at all."""


@dataclass(frozen=True)
class NotAFile:
    """The path lies inside the tree, but no regular file is there."""


TreePathRefusal: TypeAlias = BadPath | OutsideTree | NotAFile


def file_in_tree(p: object, root: Path) -> Path | TreePathRefusal:
    """The real file inside the tree `root` that p names (absolute, or relative to root) as root / <relative path>, or
    why not. Anything outside is refused - its first line would otherwise leak into pins.md. Resolving symlinks and
    checking the file read file metadata only, never contents."""
    if not isinstance(p, str) or not p or "\x00" in p or len(p) > PATH_MAX_CHARS:
        return BadPath()
    q = Path(p)
    if not q.is_absolute():
        q = root / q
    try:
        rel = q.resolve().relative_to(root.resolve())
    except (ValueError, OSError, RuntimeError):
        return OutsideTree()
    out = root / rel
    if not out.is_file():
        return NotAFile()
    return out
