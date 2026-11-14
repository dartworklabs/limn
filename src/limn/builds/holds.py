"""Build holds: keep one build's reverse-mapping material alive past the current + previous retention.

A viewer that caches a document for offline use asks the server (POST /api/hold) to keep the build its pins will be
drawn on. engine.commit_pages then slims a held directory (artifacts.slim_pages) instead of deleting it, so a pin
queued offline still resolves on that build after later rebuilds. The holds live in <document state>/holds.json:

    {"<build name>": {"until": "<ISO 8601 with offset>", "at": "<ISO 8601>", "by": "<login>",
                      "holders": {"<holder>": "<ISO 8601 with offset>"}}}

A build is held once per holder (a browser's own key, or "" for a request that names none), so one device releases
its own share without letting go of another device's. The entry's `until` is the latest end of its live shares, the
one field an older Limn and engine.commit_pages read. An entry without `holders` (an older Limn's) is the one share "".
Expired and malformed shares are dropped whenever the file is read or written, and an entry with no live share goes
with them. See docs/handbook/build-sync.md §쪽 폴더 보존과 빌드 붙잡기.
"""

import contextlib
import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from limn.builds.artifacts import BuildDoc, valid_build_name
from limn.platform.files import atomic_write

HOLDS_NAME = "holds.json"
MAX_HOLDS = 8  # live held builds per document; a new one past this drops the build expiring soonest
MAX_HOLDERS = 16  # live shares per build; a new one past this drops the share expiring soonest
MAX_DAYS = 7.0  # the longest hold, in days; also the default length
HOLDS_MAX_BYTES = 64 * 1024  # a holds.json larger than this is not read (a full file takes under 16 KiB)

# The share of a request that names no holder, and of an entry an older Limn wrote.
ANONYMOUS = ""
HOLDER_MIN = 16
HOLDER_MAX = 64
# The shape of POST /api/pin's idem (limn.pins.idem), kept here because a build module imports nothing a pin module
# owns: ASCII letters, digits, '_' and '-' only, and \Z keeps a trailing newline out.
_HOLDER_RE = re.compile(r"[A-Za-z0-9_-]{%d,%d}\Z" % (HOLDER_MIN, HOLDER_MAX))

# One lock for every document's read-modify-write of holds.json: POST /api/hold and engine.commit_pages run on
# different threads, and both are rare and short.
_LOCK = threading.Lock()


def is_holder(value: object) -> bool:
    """Is value a well-formed holder: a string of HOLDER_MIN..HOLDER_MAX characters of [A-Za-z0-9_-]?"""
    return isinstance(value, str) and _HOLDER_RE.match(value) is not None


@dataclass(frozen=True)
class Hold:
    """One held build: each live share's end (never empty), and when and by whom it was last set."""

    holders: dict[str, datetime]
    at: str
    by: str

    @property
    def until(self) -> datetime:
        """The build's end: the latest end of its shares."""
        return max(self.holders.values())


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


def _shares(entry: dict[str, object], now: datetime) -> tuple[dict[str, datetime], bool]:
    """(an entry's live shares, whether it held anything that is not one). An entry without `holders`, or with a
    `holders` that is not an object, is an older Limn's single share: "" until its `until`. A share whose key is
    neither "" nor a well-formed holder, whose end is not an aware time, or which has ended is dropped."""
    raw = entry.get("holders")
    if not isinstance(raw, dict):
        raw, dropped = {ANONYMOUS: entry.get("until")}, "holders" in entry
    else:
        dropped = False
    live: dict[str, datetime] = {}
    for holder, end in raw.items():
        until = _parse_until(end)
        if (holder != ANONYMOUS and not is_holder(holder)) or until is None or until <= now:
            dropped = True
            continue
        live[holder] = until
    return live, dropped


def _read(D: BuildDoc, now: datetime) -> tuple[dict[str, Hold], bool]:
    """(D's live holds, whether the file held anything that is not one: an expired or malformed entry or share). A
    missing or unreadable file has no holds."""
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
        if not valid_build_name(name) or not isinstance(entry, dict):
            dropped = True
            continue
        shares, lost = _shares(entry, now)
        dropped = dropped or lost
        if not shares:
            dropped = True
            continue
        at, by = entry.get("at"), entry.get("by")
        live[name] = Hold(shares, at if isinstance(at, str) else "", by if isinstance(by, str) else "")
    return live, dropped


def _iso(t: datetime) -> str:
    """A stored time: ISO 8601 to the second, with its offset."""
    return t.isoformat(timespec="seconds")


def _write(D: BuildDoc, holds: dict[str, Hold]) -> None:
    """Replace D's holds file with holds (atomically)."""
    body = {
        name: {
            "until": _iso(h.until),
            "at": h.at,
            "by": h.by,
            "holders": {holder: _iso(end) for holder, end in sorted(h.holders.items())},
        }
        for name, h in sorted(holds.items())
    }
    atomic_write(_path(D), json.dumps(body, ensure_ascii=False, indent=1) + "\n")


@contextmanager
def retention(D: BuildDoc, now: datetime | None = None) -> Iterator[set[str]]:
    """Hold the holds lock while the caller decides which of D's page directories to keep, and give it the names of
    the builds held and unexpired at `now` (by any share). engine.commit_pages deletes and slims inside this block, and
    set_hold checks that its build is still there under the same lock, so a hold answered 200 is never on a directory
    that a commit then deletes: either the commit runs first and the hold finds the directory gone (HoldBuildGone), or
    the hold runs first and the commit sees it. Rewrites the file when it held an expired or malformed entry or share;
    a failed rewrite only leaves those for the next read to drop."""
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


def set_hold(
    D: BuildDoc, name: str, days: float, by: str, now: datetime | None = None, holder: str = ANONYMOUS
) -> datetime | None:
    """Hold build `name` of D for `days` days from now on behalf of `holder`, and answer until when the build is held
    (the latest end of its shares); days 0 releases that holder's share only, and answers the end of the shares left,
    or None when none is. Setting a share that exists moves its end; releasing one that does not exist is no error.
    Past MAX_HOLDERS live shares of the build, the other share expiring soonest is dropped; past MAX_HOLDS live held
    builds, the other build expiring soonest is. Raises HoldBuildGone, storing nothing, when the build directory is not
    there under the lock (see retention). The caller checks name (valid_build_name), days (a finite number from 0 to
    MAX_DAYS) and holder (ANONYMOUS or is_holder)."""
    now = now or _now()
    with _LOCK:
        if not (D.dir / name).is_dir():
            raise HoldBuildGone(name)
        live, _dropped = _read(D, now)
        old = live.pop(name, None)
        shares = dict(old.holders) if old else {}
        at, by_ = (old.at, old.by) if old else ("", "")
        if days <= 0:
            shares.pop(holder, None)
        else:
            shares[holder] = now + timedelta(days=days)
            at, by_ = _iso(now), by
            while len(shares) > MAX_HOLDERS:
                others = [h for h in shares if h != holder]
                del shares[min(others, key=lambda h: (shares[h], h))]
        if shares:
            live[name] = Hold(shares, at, by_)
        if days > 0:
            while len(live) > MAX_HOLDS:
                others = [n for n in live if n != name]
                del live[min(others, key=lambda n: (live[n].until, n))]
        _write(D, live)
    return max(shares.values()) if shares else None
