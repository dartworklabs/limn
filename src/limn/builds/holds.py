"""Build holds: keep one build's reverse-mapping material alive past the current + previous retention.

A viewer that caches a document for offline use asks the server (POST /api/hold) to keep the build its pins will be
drawn on. engine.commit_pages then slims a held directory (artifacts.slim_pages) instead of deleting it, so a pin
queued offline still resolves on that build after later rebuilds. The holds live in <document state>/holds.json:

    {"<build name>": {"until": "<ISO 8601 with offset>", "at": "<ISO 8601>", "by": "<login>"}}

Expired and malformed entries are dropped whenever the file is read or written. See docs/handbook/build-sync.md
§쪽 교체.
"""

import contextlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from limn.builds.artifacts import BuildDoc, valid_build_name
from limn.platform.files import atomic_write

HOLDS_NAME = "holds.json"
MAX_HOLDS = 8  # live holds per document; a new one past this drops the one expiring soonest
MAX_DAYS = 7.0  # the longest hold, in days; also the default length
HOLDS_MAX_BYTES = 64 * 1024  # a holds.json larger than this is not read (8 entries take well under 1 KiB)

# One lock for every document's read-modify-write of holds.json: POST /api/hold and engine.commit_pages run on
# different threads, and both are rare and short.
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Hold:
    """One live hold: until when, set at what time, by whom."""

    until: datetime
    at: str
    by: str


def _now() -> datetime:
    """The aware local time now."""
    return datetime.now().astimezone()


def _path(D: BuildDoc) -> Path:
    """Document D's holds file."""
    return D.dir / HOLDS_NAME


def _parse_until(v: object) -> datetime | None:
    """An ISO 8601 time with an offset, or None for anything else (a naive time cannot be compared safely)."""
    if not isinstance(v, str):
        return None
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def _read(D: BuildDoc, now: datetime) -> tuple[dict[str, Hold], bool]:
    """(D's live holds, whether the file held anything that is not one: an expired or malformed entry). A missing or
    unreadable file has no holds."""
    try:
        raw = _path(D).read_bytes()
    except OSError:
        return {}, False
    if len(raw) > HOLDS_MAX_BYTES:
        return {}, True
    try:
        data = json.loads(raw)
    except ValueError:
        return {}, True
    if not isinstance(data, dict):
        return {}, True
    live: dict[str, Hold] = {}
    dropped = False
    for name, entry in data.items():
        until = _parse_until(entry.get("until")) if isinstance(entry, dict) else None
        if not valid_build_name(name) or until is None or until <= now:
            dropped = True
            continue
        at, by = entry.get("at"), entry.get("by")
        live[name] = Hold(until, at if isinstance(at, str) else "", by if isinstance(by, str) else "")
    return live, dropped


def _write(D: BuildDoc, holds: dict[str, Hold]) -> None:
    """Replace D's holds file with holds (atomically)."""
    body = {
        name: {"until": h.until.isoformat(timespec="seconds"), "at": h.at, "by": h.by}
        for name, h in sorted(holds.items())
    }
    atomic_write(_path(D), json.dumps(body, ensure_ascii=False, indent=1) + "\n")


@contextmanager
def retention(D: BuildDoc, now: datetime | None = None) -> Iterator[set[str]]:
    """Hold the holds lock while the caller decides which of D's page directories to keep, and give it the names of
    the builds held and unexpired at `now`. engine.commit_pages deletes and slims inside this block, and set_hold checks
    that its build is still there under the same lock, so a hold answered 200 is never on a directory that a commit
    then deletes: either the commit runs first and the hold finds the directory gone (HoldBuildGone), or the hold runs
    first and the commit sees it. Rewrites the file when it held an expired or malformed entry; a failed rewrite only
    leaves those entries for the next read to drop."""
    now = now or _now()
    with _LOCK:
        live, dropped = _read(D, now)
        if dropped:
            with contextlib.suppress(OSError):
                _write(D, live)
        yield set(live)


def held_builds(D: BuildDoc, now: datetime | None = None) -> set[str]:
    """The names of D's builds held and unexpired at `now` (retention, without keeping the lock)."""
    with retention(D, now) as held:
        return held


class HoldBuildGone(Exception):
    """set_hold found the build directory gone (a commit removed it after the request was checked)."""


def set_hold(D: BuildDoc, name: str, days: float, by: str, now: datetime | None = None) -> datetime | None:
    """Hold build `name` of D for `days` days from now and answer until when; days 0 releases it and answers None.
    Setting a hold that exists moves its end. Past MAX_HOLDS live holds, the other hold expiring soonest is dropped.
    Raises HoldBuildGone, storing nothing, when the build directory is not there under the lock (see retention). The
    caller checks name (valid_build_name) and days (a finite number from 0 to MAX_DAYS)."""
    now = now or _now()
    with _LOCK:
        if not (D.dir / name).is_dir():
            raise HoldBuildGone(name)
        live, _dropped = _read(D, now)
        if days <= 0:
            live.pop(name, None)
            until = None
        else:
            until = now + timedelta(days=days)
            live[name] = Hold(until, now.isoformat(timespec="seconds"), by)
            while len(live) > MAX_HOLDS:
                others = [n for n in live if n != name]
                del live[min(others, key=lambda n: (live[n].until, n))]
        _write(D, live)
    return until
