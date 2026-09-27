"""File helpers shared across the server: crash-safe replacement, and where a named path lies in the manuscript tree.

atomic_write serves every writer of the state directory (pins, people, tokens, build history): a reader - another
request, another process, an agent reading pins.md - must only ever see the old file or the new one, never a
half-written file. What gets written is the caller's business. store_lock serialises one read-modify-write of a
state file across processes (the server and the `limn member` / `limn token` commands).

tree_part is the one rule for what belongs to the manuscript tree (under the root, symlinks resolved, under no
dot-named part such as .git or .env, and not in the state folder when --state-dir puts it inside the manuscript).
file_in_tree applies it to a path a request or SyncTeX names: the request
parsers (limn.web.parse) turn its refusals into 400 answers, the selection resolver (server.pick) into its own
message. A close's recorded changes (limn.web.parse) and a stored pin path (limn.locate) are judged by tree_part too.

tex_lines is how every line number is counted when a manuscript file is read; vendor_file is the name guard of the
bundled PDF.js files the viewer loads.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

PATH_MAX_CHARS = 4096  # a longer name is refused before it reaches the file system


def atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    """Write to a temp file in the same directory, then os.replace - readers only ever see the old file or the new one.
    With mode (e.g. 0o600 for tokens.json) the temp file is created with that mode, so the content is never readable by others, even briefly."""
    tmp = path.with_name(".%s.tmp%d.%d" % (path.name, os.getpid(), threading.get_ident()))
    if mode is None:
        fh = open(tmp, "w", encoding="utf-8")  # noqa: SIM115 - closed by the `with fh:` below
    else:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        os.fchmod(fd, mode)  # the umask may have narrowed or (never) widened it
        fh = open(fd, "w", encoding="utf-8")  # noqa: SIM115 - closed by the `with fh:` below
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
        os.close(fd)  # closing the descriptor releases the lock


@dataclass(frozen=True)
class BadPath:
    """Not a usable path: not a string, empty, longer than PATH_MAX_CHARS, or containing a NUL."""


@dataclass(frozen=True)
class OutsideTree:
    """The path, symlinks resolved, lies outside the tree, under a dot-named part of it or in the state folder
    (tree_part), or cannot be resolved at all."""


@dataclass(frozen=True)
class NotAFile:
    """The path lies inside the tree, but no regular file is there."""


TreePathRefusal: TypeAlias = BadPath | OutsideTree | NotAFile


def tree_part(p: Path, root: Path, state: Path) -> Path | None:
    """p relative to the manuscript tree `root`, both with symlinks resolved, when p belongs to the tree; else None.

    The tree is what lies under root minus every dot-named part below it and minus the instance's state folder
    `state`. .git, .env, .ssh, .latexmkrc and the like hold repository or machine secrets, and a state folder that
    --state-dir puts inside the manuscript holds people.json, tokens.json (hashes), audit.jsonl and events.jsonl -
    never manuscript text, and a route that reads a named file (snippets, overlaps, a pin's first line in pins.md)
    must not quote them. Only parts below root are judged, after resolving, so a normal name that is a link into .git
    or the state folder is refused, a root that itself lies under ~/.local is fine, and a state folder above or beside
    root takes nothing away (a state folder that is root itself takes everything). None too when a path cannot be
    resolved. Reads file metadata only; p need not exist."""
    try:
        base = root.resolve()
        real = p.resolve()
        rel = real.relative_to(base)
        held = state.resolve()
    except (ValueError, OSError, RuntimeError):
        return None
    if any(part.startswith(".") for part in rel.parts):
        return None
    if held.is_relative_to(base) and real.is_relative_to(held):
        return None
    return rel


def file_in_tree(p: object, root: Path, state: Path) -> Path | TreePathRefusal:
    """The real file inside the tree `root` that p names (absolute, or relative to root) as root / <relative path>, or
    why not. Anything outside the tree (tree_part: outside root, under a dot-named part or in the state folder `state`)
    is refused - its first line would otherwise leak into pins.md. Resolving symlinks and checking the file read file
    metadata only, never contents."""
    if not isinstance(p, str) or not p or "\x00" in p or len(p) > PATH_MAX_CHARS:
        return BadPath()
    q = Path(p)
    if not q.is_absolute():
        q = root / q
    rel = tree_part(q, root, state)
    if rel is None:
        return OutsideTree()
    out = root / rel
    if not out.is_file():
        return NotAFile()
    return out


def tex_lines(path: Path) -> list[str]:
    """The lines of a manuscript file (str.splitlines, so line N is index N-1), or [] when it cannot be read or is
    not UTF-8. Every line number a pin records counts lines this way."""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


VENDOR_FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*\.mjs")


def vendor_file(base: Path, name: object) -> Path | None:
    """The file of the bundled-library directory `base` that GET /vendor/pdfjs/<name> serves, or None. Accepts only a
    single (.mjs) name component and never points outside the directory: the name pattern already filters out '/',
    '..' and '%', and resolve() adds a second check against escaping via symlinks and the like. A missing directory
    or file is None."""
    if not isinstance(name, str) or not VENDOR_FILE_RE.fullmatch(name) or ".." in name:
        return None
    try:
        base = base.resolve()
        f = (base / name).resolve()
    except (OSError, RuntimeError):
        return None
    if f.parent != base or not f.is_file():
        return None
    return f
