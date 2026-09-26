"""People: <state>/people.json and the @-tag candidates (docs/handbook/api.md §@태그·사람·이벤트).

people.json = tailnet people who have opened (or done something in) this viewer {login,name,pic,first_seen,last_seen}
plus the role `limn member` sets. Local/agent is never recorded. The file is written to a temp file under a lock and
then os.replace'd (atomic) - readers only ever see the old file or the new one.

What lives here: the record check of a people.json entry (valid_people, is_actor), its stored text (people_text), its
read (load_people), the running server's write (record_person, through a PeopleBook) and the @-tag candidates made
from people.json rows and the pins (known_people, pure).

The module knows no run arguments, no HTTP and no server. The composition root (server.people_book()) passes where the
file is, the process's lock and its last-written memo, the clock, and the rule that tells an agent from a person.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypeAlias

from limn.files import atomic_write, store_lock

# One people.json entry, pin record or actor dict as read from JSON.
Row: TypeAlias = dict[str, Any]
# (people.json path, login) -> (name, pic, epoch last written): the running server's memo of what it last wrote.
SeenMemo: TypeAlias = dict[tuple[str, str], tuple[str, Any, float]]

PEOPLE_FILE = "people.json"
# don't rewrite people.json's last_seen more often than this interval (so every poll doesn't trigger a write)
PEOPLE_TOUCH_S = 600


def is_actor(v: object) -> bool:
    """author/*_by must be a {login,name,pic?} string dict - the UI calls name.trim()."""
    return isinstance(v, dict) and all(v.get(k) is None or isinstance(v[k], str) for k in ("login", "name", "pic"))


def valid_people(d: object) -> list[Row]:
    """The entries of a parsed people.json document that name a person: dicts with a non-empty string login whose
    login/name/pic are strings or absent (is_actor). Anything else - a document of another shape, a bad entry - is
    dropped, never raised."""
    rows = d.get("people") if isinstance(d, dict) else None
    return [
        x
        for x in (rows or [])
        if isinstance(x, dict) and isinstance(x.get("login"), str) and x["login"] and is_actor(x)
    ]


def load_people(path: Path) -> list[Row]:
    """The valid entries of the people.json at path; [] when it is missing, unreadable or not JSON."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return valid_people(d)


def people_text(rows: list[Row]) -> str:
    """The stored text of people.json for rows: {"version": 1, "people": rows} sorted by login, one-space indent,
    non-ASCII kept, ending in a newline. Sorts rows in place (callers pass the list they are about to write)."""
    rows.sort(key=lambda x: x["login"])
    return json.dumps({"version": 1, "people": rows}, ensure_ascii=False, indent=1) + "\n"


@dataclass(frozen=True)
class PeopleBook:
    """The running server's people.json: the state directory it lives in, the process's thread lock and its memo of
    what it last wrote. The composition root makes both the lock and the memo once; a book value is cheap per call."""

    state: Path
    lock: threading.Lock
    seen: SeenMemo

    @property
    def path(self) -> Path:
        """people.json in the state directory."""
        return self.state / PEOPLE_FILE


def record_person(book: PeopleBook, actor: Mapping[str, Any], now: float, role: str | None, default_role: str) -> bool:
    """Records a person into people.json (only written for a new person, a name/picture change, or when last_seen is
    stale past PEOPLE_TOUCH_S). The caller has already left out local/agent actors and actors without a login. The
    request continues even if the write fails (only a warning). Returns True if it wrote.

    A person's `role` (set with `limn member`) is kept as-is. A person seen for the first time gets no role field (=
    default_role) unless `role` is given and differs from it (the local owner is recorded as owner). The file is
    re-read under the thread lock and the cross-process lock (.people.lock), since `limn member` may have just
    changed it. first_seen/last_seen are the local wall-clock strings of `now`."""
    login = actor["login"]
    name, pic = actor.get("name") or login, actor.get("pic")
    key = (str(book.path), login)
    seen = book.seen.get(key)
    if seen and seen[0] == name and seen[1] == pic and now - seen[2] < PEOPLE_TOUCH_S:
        return False
    with book.lock:
        try:
            with store_lock(book.state, "people"):
                rows = load_people(book.path)  # re-read under the lock - `limn member` may have just changed it
                stamp = datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                cur = next((x for x in rows if x["login"] == login), None)
                if cur is None:
                    cur = {"login": login, "first_seen": stamp}
                    if role and role != default_role:
                        cur["role"] = role
                    rows.append(cur)
                cur["name"] = name
                if pic:
                    cur["pic"] = pic
                cur["last_seen"] = stamp
                atomic_write(book.path, people_text(rows), mode=0o600)
        except OSError as e:
            print("warning: failed to write people.json: %s" % e, file=sys.stderr)
            return False
        book.seen[key] = (name, pic, now)
    return True


def known_people(people: Iterable[Row], pins: Iterable[Row], is_agent: Callable[[Row], bool]) -> dict[str, Row]:
    """@-tag candidates {login: {login,name,pic?,last_seen?}} - from people.json rows plus authors/actors (author and
    every *_by field) and thread posters on the pin records. An actor is skipped when it is not a dict with a
    non-empty string login or when is_agent says it is an agent. The first entry seen for a login sets its name; a
    later one only fills a missing pic, and a people.json last_seen is kept. Pure: the caller reads the rows."""
    out: dict[str, Row] = {}

    def add(a: object, seen: object = None) -> None:
        """Adds actor a to out as described above (seen: its people.json last_seen, if any)."""
        if not isinstance(a, dict) or not isinstance(a.get("login"), str) or not a["login"] or is_agent(a):
            return
        cur = out.setdefault(a["login"], {"login": a["login"], "name": a.get("name") or a["login"]})
        if a.get("pic") and not cur.get("pic"):
            cur["pic"] = a["pic"]
        if seen:
            cur["last_seen"] = seen

    for x in people:
        add(x, x.get("last_seen"))
    for r in pins:
        for k, v in r.items():
            if k == "author" or k.endswith("_by"):
                add(v)
        for m in r.get("thread") or []:
            add(m.get("by"))
    return out
