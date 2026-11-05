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
it is). An image over ASSET_MAX_BYTES is refused without being read, and a raster image whose header gives it more than
ASSET_MAX_PIXELS pixels is refused before any browser decodes it (raster_size: a few kilobytes of PNG can stand for a
picture whose decoded pixels take gigabytes). An SVG has no such size: a browser rasterizes it at the size it is drawn.

The ETag is a hash of the content (ADR-0030 D6). A run remembers the tag of each image it read under the identity of
the descriptor it read (AssetTags: path, device, inode, size, mtime and ctime), so a revalidation of an image that has
not changed since is a stat and a 304, never a read of the file; any change to the file is a new identity and a new read.

Nothing here writes: one bounded read of one checked descriptor, and a bounded map in memory
(docs/adr/0027-get-write-guard.md).
"""

import hashlib
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

from limn.platform.files import BoundedBytes, FileIdentity, ManuscriptFile, OverLimit, ReadRefused

# The most bytes of one image the server reads and sends. A screenshot or a figure is well under it; a larger file is
# answered 413 asset_too_large and never read past its size.
ASSET_MAX_BYTES = 8 * 1024 * 1024
# The most pixels (width x height, as the image's header gives them) of one raster image the server sends: 8192 x 8192,
# 256 MiB once decoded at 4 bytes a pixel. An 8K screenshot (33 Mpx) and an A4 page at 600 dpi (35 Mpx) are under it; a
# small file standing for a larger picture is answered 413 asset_too_many_pixels and never reaches a browser's decoder.
ASSET_MAX_PIXELS = 8192 * 8192
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
# The most images (by resolved path and suffix) one run keeps the content tag of (AssetTags), far more than a document
# shows at once. Past it the least recently asked is dropped, and its next revalidation reads and hashes it again.
ASSET_TAGS_MAX = 1024
# How long after its last change (its ctime) an image's tag is not kept: a file system's clock ticks coarsely (a few ms
# on Linux, 2 s on FAT), and two writes within one tick can leave one size, mtime and ctime - the second one's content
# would then be answered with the first one's tag. A tag is kept only for a file left alone this long before the read.
ASSET_TAG_SETTLE_NS = 2_000_000_000

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
    """The image's bytes, its media type (from its suffix), an entity tag of its content and the identity of the
    descriptor they were read from (AssetTags keeps the tag under it)."""

    data: bytes
    media: str
    etag: str
    identity: FileIdentity


@dataclass(frozen=True)
class AssetTooLarge:
    """The file holds more than `limit` bytes (size as its descriptor reported it, or limit + 1 if it grew while read)."""

    size: int
    limit: int


@dataclass(frozen=True)
class AssetTooManyPixels:
    """The raster image's header gives it width x height pixels, more than `limit` (ASSET_MAX_PIXELS)."""

    width: int
    height: int
    limit: int


@dataclass(frozen=True)
class AssetNotImage:
    """The file's bytes do not start as its suffix's format starts (an HTML page named .png, a text file named .svg), or a
    raster image's header gives no size (raster_size)."""


@dataclass(frozen=True)
class AssetUnreadable:
    """The checked handle gave no bytes: removed, replaced by a link or something that is not a regular file."""


AssetRead: TypeAlias = AssetBytes | AssetTooLarge | AssetTooManyPixels | AssetNotImage | AssetUnreadable


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


def raster_size(data: bytes, suffix: str) -> tuple[int, int] | None:
    """(width, height) in pixels of the raster image data of the format suffix names, as its header gives them, or None
    when the header gives none (cut short, malformed, an SVG). Each scan moves forward only, so it is linear in len(data).
    Pure.

    PNG: the IHDR chunk, which must come first. GIF: the logical screen, widened to the first frame's extent (a frame may
    reach past the screen it is declared in). JPEG: the first start-of-frame segment before the scan starts. WebP: the
    canvas of an extended file (VP8X), or the frame of a simple lossy (VP8) or lossless (VP8L) one."""
    if suffix == ".png":
        if len(data) < 24 or data[12:16] != b"IHDR":
            return None
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if suffix == ".gif":
        return _gif_size(data)
    if suffix in (".jpg", ".jpeg"):
        return _jpeg_size(data)
    if suffix == ".webp":
        return _webp_size(data)
    return None


def _gif_size(data: bytes) -> tuple[int, int] | None:
    """A GIF's logical screen, widened to its first frame's extent (left + width, top + height); None without a frame."""
    if len(data) < 13:
        return None
    w, h = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    at = 13 + (3 << ((data[10] & 7) + 1) if data[10] & 0x80 else 0)  # past the global colour table
    while at < len(data):
        block = data[at]
        if block == 0x2C:  # an image descriptor: left, top, width, height
            if at + 9 > len(data):
                return None
            left, top = int.from_bytes(data[at + 1 : at + 3], "little"), int.from_bytes(data[at + 3 : at + 5], "little")
            fw, fh = int.from_bytes(data[at + 5 : at + 7], "little"), int.from_bytes(data[at + 7 : at + 9], "little")
            return max(w, left + fw), max(h, top + fh)
        if block != 0x21 or at + 2 > len(data):  # neither a frame nor an extension: a trailer, or no GIF
            return None
        at += 2  # the introducer and the label, then the extension's sub-blocks up to an empty one
        while at < len(data) and data[at]:
            at += data[at] + 1
        at += 1
    return None


# The JPEG markers that stand alone, without a length: TEM, the restart markers and SOI.
_JPEG_ALONE = frozenset({0x01, *range(0xD0, 0xD9)})
# The start-of-frame markers (every SOFn: C0-CF but DHT C4, JPG C8 and DAC CC).
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """A JPEG's frame size from its first SOFn segment; None when the scan (SOS) or the end comes first."""
    at = 2
    while at + 4 <= len(data):
        if data[at] != 0xFF:
            return None
        marker = data[at + 1]
        if marker == 0xFF:  # a fill byte
            at += 1
            continue
        if marker in _JPEG_ALONE:
            at += 2
            continue
        if marker == 0xDA:
            return None
        if marker in _JPEG_SOF:
            if at + 9 > len(data):
                return None
            return int.from_bytes(data[at + 7 : at + 9], "big"), int.from_bytes(data[at + 5 : at + 7], "big")
        at += 2 + int.from_bytes(data[at + 2 : at + 4], "big")
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    """A WebP's canvas (VP8X) or frame (VP8, VP8L) size; None for another first chunk or one cut short."""
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def read_asset(
    file: ManuscriptFile, suffix: str, limit: int = ASSET_MAX_BYTES, pixels: int = ASSET_MAX_PIXELS
) -> AssetRead:
    """The image in the checked manuscript file `file`, of the format `suffix` names: at most limit bytes in one bounded
    read of its no-follow descriptor. AssetBytes when they start as that format does and, for a raster format, its header
    gives a size of at most `pixels` pixels; AssetNotImage when they do not start so or a raster header gives no size,
    AssetTooManyPixels above `pixels`, AssetTooLarge above limit (nothing past the size is read), AssetUnreadable when the
    handle refuses. Writes nothing."""
    match file.read_bounded(limit):
        case BoundedBytes(data=data, identity=identity):
            if not asset_kind(data, suffix):
                return AssetNotImage()
            if suffix != ".svg":
                size = raster_size(data, suffix)
                if size is None:
                    return AssetNotImage()
                if size[0] * size[1] > pixels:
                    return AssetTooManyPixels(size[0], size[1], pixels)
            tag = '"%s"' % hashlib.blake2b(data, digest_size=12).hexdigest()
            return AssetBytes(data, ASSET_TYPES[suffix], tag, identity)
        case OverLimit(signature=signature):
            return AssetTooLarge(max(signature.size, limit + 1), limit)
        case ReadRefused():
            return AssetUnreadable()


@dataclass
class AssetTags:
    """One run's content tags of the tree images it has sent, so that the revalidation of an unchanged image is a stat
    and a 304 (GET /api/asset with If-None-Match), not a read and a hash of up to ASSET_MAX_BYTES.

    keep(read, suffix) remembers the tag of an image read (AssetBytes) under the identity of the descriptor it was read
    from (FileIdentity: resolved path, st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns), keyed by that path and the
    suffix it was asked under (the suffix decides the checks its bytes passed). known(file, suffix) answers that tag
    only while a no-follow stat of the file (ManuscriptFile.identity, the file not opened) gives the same identity: a
    file written again - at its old size, its mtime put back - has a new ctime and is read again. The tag stays a hash
    of the content (ADR-0030 D6); this only skips a read whose hash is known. A read of a file changed less than
    settle_ns before it is not kept (ASSET_TAG_SETTLE_NS: the file system's clock may not have ticked between two
    writes). At most `limit` entries, the least recently used dropped first; nothing is written (ADR-0027). Request
    threads share it under one lock, held only to look an entry up or publish one, never across a stat or a read.
    `read` is the read a request no tag answers makes (read_asset); a test gives one that records what was read."""

    limit: int = ASSET_TAGS_MAX
    settle_ns: int = ASSET_TAG_SETTLE_NS
    clock: Callable[[], int] = time.time_ns
    read: Callable[[ManuscriptFile, str], AssetRead] = read_asset
    _held: OrderedDict[tuple[str, str], tuple[FileIdentity, str]] = field(default_factory=OrderedDict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def known(self, file: ManuscriptFile, suffix: str) -> str | None:
        """The content tag of `file` as last read under `suffix`, when its identity now is the one that read had; else
        None (never read, dropped, changed, or no longer a regular file). One stat; the file is not opened."""
        now = file.identity()
        if now is None:
            return None
        key = (now.path, suffix)
        with self._lock:
            held = self._held.get(key)
            if held is None or held[0] != now:
                return None
            self._held.move_to_end(key)
            return held[1]

    def keep(self, read: AssetBytes, suffix: str) -> None:
        """Remember read's tag under its identity and suffix, unless the file changed less than settle_ns before now."""
        if read.identity.ctime_ns > self.clock() - self.settle_ns:
            return
        key = (read.identity.path, suffix)
        with self._lock:
            self._held[key] = (read.identity, read.etag)
            self._held.move_to_end(key)
            while len(self._held) > self.limit:
                self._held.popitem(last=False)

    def __len__(self) -> int:
        """How many entries are held."""
        with self._lock:
            return len(self._held)
