"""An image of the manuscript tree that a browser-drawn document shows: GET /api/asset (docs/adr/0030-markdown-tree-images-and-document-links.md).

A Markdown document may show the images its source names by a relative path. The viewer resolves that path against the
document's own path, and asks for the result here: a path relative to the manuscript tree (--manuscript), already
normalized - forward slashes, no '.' or '..' part, no empty part, no dot-named part - with one of the image suffixes
ASSET_TYPES lists. The server never resolves a document-relative path and never reads Markdown; it checks what it is
given, then reads it through the same checked handle every file route uses (limn.platform.files.file_in_tree: inside the
tree with links resolved, no dot-named part, not the state folder, a regular file, opened no-follow at every step).

What it sends is only what the suffix says it is: the bytes must start as that format starts (asset_kind), the media
type comes from the suffix (never from the bytes or a system table), and every answer carries nosniff, a
Content-Security-Policy of its own (ASSET_POLICY: opened on its own, an SVG is an inert document of an opaque origin)
and Cross-Origin-Resource-Policy: same-origin (another site cannot embed it to learn whether a file exists or how large
it is). An image over ASSET_MAX_BYTES is refused without being read.

Nothing here writes: one bounded read of one checked descriptor (docs/adr/0027-get-write-guard.md).
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

from limn.platform.files import BoundedBytes, ManuscriptFile, OverLimit, ReadRefused

# The most bytes of one image the server reads and sends. A screenshot or a figure is well under it; a larger file is
# answered 413 asset_too_large and never read past its size.
ASSET_MAX_BYTES = 8 * 1024 * 1024
# The longest path the route takes, in characters (the request line is capped at 4096 bytes before this).
ASSET_PATH_MAX = 1024
# Suffix (lower case) -> the media type the image is sent as. Nothing else is served.
ASSET_TYPES: Mapping[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
# The policy of every asset answer. As an <img>, an image runs nothing and loads nothing whatever its policy says; opened
# on its own (a new tab, a link to it, the address typed), an SVG is a document: sandbox gives it an opaque origin with
# no script, default-src 'none' lets it fetch nothing, and its own inline style and data: pictures still draw.
ASSET_POLICY = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox; frame-ancestors 'none'"
# Only pages of this origin may embed an asset.
ASSET_RESOURCE_POLICY = "same-origin"
# Kept, but asked again each time: an image edited in place shows on the next view, and an unchanged one costs a 304.
ASSET_CACHE = "private, no-cache"

# How much of an SVG's text is looked at for its root element: what comes before it must fit in this many characters.
SVG_HEAD_MAX = 8192
# XML white space, the only characters allowed between the parts before an SVG's root element.
_XML_SPACE = " \t\r\n"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class AssetPathRefused:
    """The path is not one the viewer sends: not a string, empty or too long, absolute, with a backslash or a control
    character, with an empty, '.', '..' or dot-named part, or without an image suffix of ASSET_TYPES."""

    why: str


@dataclass(frozen=True)
class AssetPath:
    """A tree-relative image path as the viewer sends it (asset_path) and its suffix in lower case (a key of
    ASSET_TYPES)."""

    rel: str
    suffix: str


@dataclass(frozen=True)
class AssetBytes:
    """The image's bytes, its media type (from its suffix) and an entity tag of its content."""

    data: bytes
    media: str
    etag: str


@dataclass(frozen=True)
class AssetTooLarge:
    """The file holds more than `limit` bytes (size as its descriptor reported it, or limit + 1 if it grew while read)."""

    size: int
    limit: int


@dataclass(frozen=True)
class AssetNotImage:
    """The file's bytes do not start as its suffix's format starts (an HTML page named .png, a text file named .svg)."""


@dataclass(frozen=True)
class AssetUnreadable:
    """The checked handle gave no bytes: removed, replaced by a link or something that is not a regular file."""


AssetRead: TypeAlias = AssetBytes | AssetTooLarge | AssetNotImage | AssetUnreadable


def asset_path(raw: object) -> AssetPath | AssetPathRefused:
    """raw and its suffix when it is a tree-relative image path the viewer sends, else why not. Pure.

    The viewer normalizes before it asks, so a path with anything to normalize did not come from it and is refused
    rather than repaired: no leading '/', no backslash or control character, no empty, '.' or '..' part, no part
    starting with '.' (.git, .env - the tree check refuses them too), at most ASSET_PATH_MAX characters, and a suffix of
    ASSET_TYPES in any case."""
    if not isinstance(raw, str) or not raw or len(raw) > ASSET_PATH_MAX:
        return AssetPathRefused("empty or too long")
    if raw.startswith("/") or "\\" in raw or _CONTROL.search(raw):
        return AssetPathRefused("absolute, backslash or control character")
    parts = raw.split("/")
    if any(part in ("", ".", "..") or part.startswith(".") for part in parts):
        return AssetPathRefused("empty, '.', '..' or dot-named part")
    suffix = asset_suffix(raw)
    if suffix is None:
        return AssetPathRefused("not an image suffix")
    return AssetPath(raw, suffix)


def asset_suffix(path: str) -> str | None:
    """path's suffix in lower case when ASSET_TYPES serves it, else None (a name that is nothing but a suffix has none).
    Pure."""
    dot = path.rfind(".")
    if dot < 0 or dot <= path.rfind("/") + 1:
        return None
    suffix = path[dot:].lower()
    return suffix if suffix in ASSET_TYPES else None


def asset_kind(data: bytes, suffix: str) -> bool:
    """Whether data starts as the format of suffix starts: the PNG, JPEG, GIF and WebP signatures, and for SVG UTF-8
    text whose first element (after a declaration, processing instructions, comments and a DOCTYPE without an internal
    subset, within SVG_HEAD_MAX characters: svg_head) is <svg>. Pure."""
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in (".jpg", ".jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".gif":
        return data[:6] in (b"GIF87a", b"GIF89a")
    if suffix == ".webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if suffix == ".svg":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return svg_head(text[:SVG_HEAD_MAX])
    return False


def svg_head(text: str) -> bool:
    """Whether text's first element is <svg>: before it only a byte-order mark, then XML white space, processing
    instructions (the XML declaration among them), comments and DOCTYPEs without an internal subset (no '[': no entity
    definitions). Each part is passed over by one forward search for its end, so the scan is linear in len(text) - a
    regular expression of these alternatives backtracks exponentially over repeated comments. An unterminated part, as at
    the cut of SVG_HEAD_MAX, is no SVG. Pure."""
    at, n = (1 if text.startswith("\ufeff") else 0), len(text)
    while True:
        while at < n and text[at] in _XML_SPACE:
            at += 1
        if text.startswith("<!--", at):
            end = text.find("-->", at + 4)
            if end < 0:
                return False
            at = end + 3
        elif text.startswith("<?", at):
            end = text.find("?>", at + 2)
            if end < 0:
                return False
            at = end + 2
        elif text[at : at + 9].upper() == "<!DOCTYPE":
            end = text.find(">", at + 9)
            if end < 0 or "[" in text[at:end]:
                return False
            at = end + 1
        else:
            return text[at : at + 4].lower() == "<svg" and text[at + 4 : at + 5] in tuple(_XML_SPACE + ">/")


def read_asset(file: ManuscriptFile, suffix: str, limit: int = ASSET_MAX_BYTES) -> AssetRead:
    """The image in the checked manuscript file `file`, of the format `suffix` names: at most limit bytes in one bounded
    read of its no-follow descriptor. AssetBytes when they start as that format does, AssetNotImage when not,
    AssetTooLarge above limit (nothing past the size is read), AssetUnreadable when the handle refuses. Writes nothing."""
    match file.read_bounded(limit):
        case BoundedBytes(data=data):
            if not asset_kind(data, suffix):
                return AssetNotImage()
            tag = '"%s"' % hashlib.blake2b(data, digest_size=12).hexdigest()
            return AssetBytes(data, ASSET_TYPES[suffix], tag)
        case OverLimit(signature=signature):
            return AssetTooLarge(max(signature.size, limit + 1), limit)
        case ReadRefused():
            return AssetUnreadable()
