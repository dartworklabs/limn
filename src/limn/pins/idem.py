"""The idempotency key of a new pin (docs/handbook/api.md §핀 만들기와 상태 바꾸기, `POST /api/pin` `idem`).

A viewer that queued a pin with no network sends it later with a key of its own choosing. A send whose answer is lost
may or may not have written its pin; sending again with the same key answers with the pin the first send made instead
of making a second one. The key is stored on the pin record as `idem`, a field the API never shows (it is not in
GET /api/pins rows, change responses or pins.md).

The key is looked up among every pin of the instance - open, awaiting review, done, and in the Trash while that entry is
still restorable. A purged or expired Trash entry, or a pin archived by clear, no longer holds its key. A stored value
that is not a well-formed key (a hand edit) is no key: the record is not broken by it, it just answers for nothing.

Pure: the caller passes the live pins and the Trash entries it read under the pin lock.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from limn.pins.model import Pin, TrashedPin

# The stored and request field name.
IDEM_FIELD = "idem"
IDEM_MIN = 16
IDEM_MAX = 64
# ASCII letters, digits, '_' and '-' only: \w would also take Hangul and other letters, and \Z keeps a trailing newline
# out (a `$` would match before it).
_IDEM_RE = re.compile(r"[A-Za-z0-9_-]{%d,%d}\Z" % (IDEM_MIN, IDEM_MAX))


def is_idem(value: object) -> bool:
    """Is value a well-formed key: a string of IDEM_MIN..IDEM_MAX characters of [A-Za-z0-9_-]?"""
    return isinstance(value, str) and _IDEM_RE.match(value) is not None


def idem_of(record: Mapping[str, Any]) -> str | None:
    """The key a stored record holds, or None when it holds none or a value that is not a well-formed key."""
    value = record.get(IDEM_FIELD)
    return value if isinstance(value, str) and is_idem(value) else None


def keyed_pin(key: str, pins: Iterable[Pin], trash: Iterable[TrashedPin]) -> int | None:
    """The id of the pin that holds key - a live pin first, then a Trash entry - or None. trash is the entries still
    restorable (the caller drops expired ones), so a purged or expired pin's key is free again."""
    for pin in pins:
        if idem_of(pin.record) == key:
            return pin.core.pid
    for entry in trash:
        if idem_of(entry.record) == key:
            return entry.pin.core.pid
    return None
