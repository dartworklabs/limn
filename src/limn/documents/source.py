"""A browser-drawn document's source as the viewer reads it: GET /api/source (ADR-0025 D7, docs/handbook/api.md §화면·PDF·정적 파일).

A Markdown document has no PDF and no page images; the viewer draws it from its source. The server stays the authority
on line numbers: it sends the source already split into lines, numbered as every other line consumer numbers them
(limn.platform.files.tex_lines, str.splitlines()), and the viewer joins them with "\\n" before parsing and never splits
the raw bytes itself. The file is read through the checked manuscript handle (limn.platform.files.file_in_tree, which
the caller obtains) with a bounded read, so a source over SOURCE_MAX_BYTES is refused without ever being held whole.

Nothing here writes: a read is one bounded read of one checked descriptor, stamped by the fstat that read makes on it
before its first byte. Each outcome is its own value; limn.documents.http answers every one of them in one place.
"""

from dataclasses import dataclass
from typing import TypeAlias

from limn.platform.files import BoundedBytes, ManuscriptFile, OverLimit, ReadRefused

# The most bytes of source the server reads and sends (ADR-0025 D7; the HTML surface spec's §결정 5, item 6, gives the
# measurements behind it). A larger source is answered 413 with no lines.
SOURCE_MAX_BYTES = 1_048_576


@dataclass(frozen=True)
class SourceLines:
    """The source, split as the server numbers lines (source_lines): line n of a pin is lines[n - 1]. src_mtime is the
    file's st_mtime, stat'ed on the very descriptor the lines were read from, before its first byte - the same measure
    GET /api/meta's src_mtime takes of a document that is not built. A save that replaces the file while it is read
    leaves that descriptor on the version it opened, so the lines and the stamp are always one version's: a viewer that
    compares the stamp with the light poll's refetches at worst once too often and never misses an edit."""

    lines: tuple[str, ...]
    src_mtime: float


@dataclass(frozen=True)
class SourceTooLarge:
    """The source holds more than `limit` bytes. size is the file's size as its descriptor reported it, or limit + 1 when
    the file grew past the limit while it was being read (the read stops there, so no more is known)."""

    size: int
    limit: int


@dataclass(frozen=True)
class SourceNotUtf8:
    """The source's bytes are not UTF-8. Every line consumer of the server reads a manuscript file as UTF-8; such a file
    has no lines to number."""


@dataclass(frozen=True)
class SourceUnreadable:
    """The checked handle gave no bytes: the file was removed, replaced by a link or by something that is not a regular
    file after the tree check, or cannot be read."""


SourceRead: TypeAlias = SourceLines | SourceTooLarge | SourceNotUtf8 | SourceUnreadable


def source_lines(data: bytes) -> list[str] | None:
    """data decoded as UTF-8 and split with str.splitlines(), or None when it is not UTF-8.

    These are the lines tex_lines gives for a file holding data: tex_lines reads in text mode, whose universal newlines
    turn "\\r\\n" and a lone "\\r" into "\\n" before the split, and splitlines treats each of those as one line end too, so
    the two agree on every line end - "\\n", "\\r\\n", "\\r", "\\v", "\\f", "\\x1c"-"\\x1e", "\\x85", U+2028, U+2029 - and
    on every line's text. A byte-order mark stays in the first line, as it does there. Pure."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text.splitlines()


def read_source(file: ManuscriptFile, limit: int = SOURCE_MAX_BYTES) -> SourceRead:
    """The source in the checked manuscript file `file`: at most limit + 1 of its bytes and the stamp of the descriptor
    they came from, in one bounded read of its no-follow descriptor (ManuscriptFile.read_bounded). The stamp is never
    taken through a second descriptor, which an atomic save between the two opens would leave on another version.

    SourceLines when it holds at most `limit` bytes of UTF-8; SourceTooLarge (the size and the limit, no lines) above
    that; SourceNotUtf8 for bytes that do not decode; SourceUnreadable when the handle refuses the read. Writes
    nothing."""
    match file.read_bounded(limit):
        case BoundedBytes(data=data, mtime=mtime):
            lines = source_lines(data)
            if lines is None:
                return SourceNotUtf8()
            return SourceLines(tuple(lines), mtime)
        case OverLimit(signature=signature):
            return SourceTooLarge(max(signature.size, limit + 1), limit)
        case ReadRefused():
            return SourceUnreadable()
