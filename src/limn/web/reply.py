"""A complete HTTP response and the shared JSON wire format."""

import json
from typing import NamedTuple


class Reply(NamedTuple):
    """Status, body, Content-Type, optional Cache-Control and optional ETag (a quoted entity tag) for one response."""

    code: int
    body: bytes
    ctype: str
    cache: str | None = None
    etag: str | None = None


def json_reply(obj: object, code: int = 200) -> Reply:
    """Encode a JSON response as UTF-8 while preserving non-ASCII characters."""
    return Reply(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")
