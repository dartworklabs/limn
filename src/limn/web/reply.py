"""A complete HTTP response and the shared JSON wire format."""

import json
import re
import unicodedata
from typing import NamedTuple
from urllib.parse import quote


class Reply(NamedTuple):
    """Status, body, Content-Type, optional Cache-Control, optional ETag (a quoted entity tag) and optional
    Content-Disposition (a complete header value, e.g. attachment_disposition) for one response."""

    code: int
    body: bytes
    ctype: str
    cache: str | None = None
    etag: str | None = None
    disposition: str | None = None


def json_reply(obj: object, code: int = 200) -> Reply:
    """Encode a JSON response as UTF-8 while preserving non-ASCII characters."""
    return Reply(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")


# Characters no file system takes in a name (Windows' set, the strictest, plus controls), and the device names Windows
# refuses whatever the extension is.
_UNSAFE_NAME_RE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')
_RESERVED_NAME_RE = re.compile(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", re.IGNORECASE)
# What RFC 8187 calls attr-char, beyond letters and digits: the rest of a filename* value is percent-encoded.
_ATTR_CHAR_EXTRA = "!#$&+-.^_`|~"
FALLBACK_STEM = "document"


def safe_file_stem(label: str) -> str:
    """label as the stem of a file name any common file system accepts: a separator, a quote, a control character or
    another character Windows refuses becomes "_", runs of whitespace one space, leading dots and spaces and trailing
    dots and spaces go, a device name (CON, NUL, COM1...) gets a "_" before it. Letters of any script stay (NFC). A
    label with nothing left is FALLBACK_STEM. Pure."""
    text = unicodedata.normalize("NFC", _UNSAFE_NAME_RE.sub("_", " ".join(label.split())))
    text = text.strip(" .")
    if not text:
        return FALLBACK_STEM
    return "_" + text if _RESERVED_NAME_RE.fullmatch(text) else text


def attachment_disposition(label: str, suffix: str = ".pdf") -> str:
    """The Content-Disposition value that saves a response as `<label><suffix>`: `attachment; filename="<ASCII>"`, and
    when the name has anything but plain ASCII, `; filename*=UTF-8''<percent-encoded>` after it (RFC 6266, RFC 8187),
    so a browser that reads filename* keeps the label's own characters and one that does not still gets a usable name.
    The ASCII fallback keeps the printable ASCII of the name, turns every other character (and the quote, backslash,
    percent and semicolon that would break the quoted string) into "_", and falls back to FALLBACK_STEM when nothing
    but underscores and punctuation is left. suffix is the caller's own constant (".pdf"). Pure."""
    name = safe_file_stem(label) + suffix
    ascii_name = "".join(c if " " <= c < "\x7f" and c not in '"\\%;' else "_" for c in name)
    if not any(c.isalnum() for c in ascii_name.removesuffix(suffix)):
        ascii_name = FALLBACK_STEM + suffix
    value = 'attachment; filename="%s"' % ascii_name
    if ascii_name != name:
        value += "; filename*=UTF-8''" + quote(name, safe=_ATTR_CHAR_EXTRA)
    return value
