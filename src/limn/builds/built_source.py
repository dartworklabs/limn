"""The source a build was made from, kept with its pages.

SyncTeX of a build numbers the lines of the files that build read. Once the manuscript is edited, those numbers name
other text in the files as they are now, and a pick against that build - a pin queued offline, a drag on a PDF older
than the manuscript - would land on it. So a LaTeX build publishes, next to its PDF and SyncTeX, the lines of the
manuscript files it read (SOURCE_NAME); a pick carries SyncTeX's range from those lines over to today's
(limn.pins.location.mapping.carry_range).

    {"format": 1, "files": {"<path below the build root, POSIX>": ["<line>", ...]}}

Only text sources a pick answers lines in are kept (LINE_SUFFIXES), read from the build copy after latexmk ran, each
through descriptors that follow no link below the copy's root. The record is written into the page folder before the
folder gets its name, so it is published with the pages, kept when a held folder is slimmed and removed with the
folder. A folder without one (a build of an older Limn, a figure or view-only document) has no record, and a pick
against it uses SyncTeX's numbers as they are. See docs/handbook/build-sync.md §빌드가 읽은 원고 줄.
"""

import io
import json
import os
import stat
from collections.abc import Iterable, Mapping
from pathlib import Path

SOURCE_NAME = "source.json"  # the record, in a LaTeX build's page folder
SOURCE_FORMAT = 1
# The suffixes of the manuscript's source list (artifacts.SRC_TEX_EXTS) a pick answers lines in: a .bib is refused
# (GeneratedFile) and a .bst is never TeX input.
LINE_SUFFIXES = (".tex", ".sty", ".cls")
FILE_MAX_BYTES = 4 * 1024 * 1024  # a source file larger than this is left out of the record
TOTAL_MAX_BYTES = 16 * 1024 * 1024  # the bytes of source one record holds; files past it are left out
# A record larger than this is not read. JSON doubles a backslash, so a full record of LaTeX can near twice its bytes.
RECORD_MAX_BYTES = 2 * TOTAL_MAX_BYTES + 1024 * 1024


def text_lines(raw: bytes) -> list[str] | None:
    """The lines of a file's bytes as a pick reads the file itself (limn.platform.files.ManuscriptFile.snapshot: UTF-8,
    universal newlines, str.splitlines), so the two lists compare line for line; None when the bytes are not UTF-8."""
    try:
        return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8").read().splitlines()
    except UnicodeDecodeError:
        return None


def read_below(root: Path, rel: str, limit: int) -> bytes | None:
    """The bytes of the plain file at rel ('a/b.tex', POSIX) below the folder root, when it holds at most limit of them.

    Every folder on the way and the file itself are opened by name from the descriptor of the folder above with
    O_NOFOLLOW, so no symlink below root is followed, and the file is checked on its own descriptor: it must be a
    regular file. None for an empty or absolute path, a part that is empty, '.', '..' or dot-named (the manuscript
    tree's rule for dot names), a missing file, a link, a folder, a device, a file over limit (never read) and any
    read error."""
    parts = rel.split("/")
    if not rel or any(not part or part.startswith(".") or "\x00" in part for part in parts):
        return None
    opened: list[int] = []
    try:
        opened.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY))
        for part in parts[:-1]:
            opened.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=opened[-1]))
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=opened[-1])
        opened.append(leaf)
        found = os.fstat(leaf)
        if not stat.S_ISREG(found.st_mode) or found.st_size > limit:
            return None
        with os.fdopen(leaf, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
    except OSError:
        return None
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
    return None if len(data) > limit else data


def collect(root: Path, names: Iterable[str]) -> dict[str, list[str]]:
    """The lines of the files `names` ('a/b.tex' below root, the build copy) that a record keeps, in name order: those
    with a suffix of LINE_SUFFIXES (any case) that read_below reads within FILE_MAX_BYTES and that are UTF-8, while the
    bytes kept stay within TOTAL_MAX_BYTES. A file that does not qualify is left out; a pick on it then uses SyncTeX's
    numbers as they are."""
    kept: dict[str, list[str]] = {}
    total = 0
    for rel in sorted(set(names)):
        if os.path.splitext(rel)[1].lower() not in LINE_SUFFIXES:
            continue
        raw = read_below(root, rel, min(FILE_MAX_BYTES, TOTAL_MAX_BYTES - total))
        lines = None if raw is None else text_lines(raw)
        if raw is None or lines is None:
            continue
        kept[rel] = lines
        total += len(raw)
    return kept


def encode(files: Mapping[str, list[str]]) -> str:
    """The text of a record holding files (collect's answer)."""
    return json.dumps({"format": SOURCE_FORMAT, "files": files}, ensure_ascii=False)


def source_key(src: Path, file: Path) -> str | None:
    """The name a record keeps the manuscript file `file` under: its path below the build root src, both with
    symlinks resolved, as 'a/b.tex'. None when the file is not below src or a path cannot be resolved."""
    try:
        below = file.resolve().relative_to(src.resolve())
    except (ValueError, OSError, RuntimeError):
        return None
    return below.as_posix() if below.parts else None


def built_lines(pages: Path, key: str) -> tuple[str, ...] | None:
    """The lines of the file `key` (source_key) as the build of page folder pages read it, from that folder's record.
    None when the folder has no record, the record is not a plain file of at most RECORD_MAX_BYTES, is not JSON of this
    format, or does not hold the file as a list of strings. Nothing is looked up on disk by key: it only names an entry
    of the parsed record."""
    raw = read_below(pages, SOURCE_NAME, RECORD_MAX_BYTES)
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(record, dict) or record.get("format") != SOURCE_FORMAT:
        return None
    files = record.get("files")
    lines = files.get(key) if isinstance(files, dict) else None
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        return None
    return tuple(lines)
