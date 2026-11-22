"""People: <state>/people.json and the @-tag candidates (docs/handbook/api.md §@태그·사람·이벤트).

people.json = people recorded after an authorized changing POST in this viewer {login,name,pic,first_seen,last_seen}
plus the role `limn member` sets. Local/agent is never recorded. The file is written to a temp file under a lock and
then os.replace'd (atomic) - readers only ever see the old file or the new one.

What lives here: the record check of a people.json entry (valid_people, is_actor), its stored text (people_text), its
read (load_people: the rows, or PeopleUnreadable for a file that exists but cannot be used - fail closed, never "no
one"), the warning about such a file (UnreadableWarning), the running server's write (record_person, through a
PeopleBook; never over an unusable file), the @-tag candidates made from people.json rows and the pins
(known_people, pure) and their order and roles as GET /api/people lists them (candidates, pure).

The module knows no run arguments, no HTTP and no server. The collaboration directory binds the file path, process
lock, last-written memo, clock, and the rule that tells an agent from a person.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypeAlias, TypeVar, final

from limn.platform.files import atomic_write, store_lock
from limn.runtime.paths import PEOPLE_FILE as PEOPLE_FILE
from limn.security.values import LOGIN_MAX, NAME_MAX, ROLES, is_role, role_value, valid_login

# One people.json entry, pin record or actor dict as read from JSON.
Row: TypeAlias = dict[str, Any]
# (people.json path, login) -> (name, pic, epoch last written): the running server's memo of what it last wrote.
SeenMemo: TypeAlias = dict[tuple[str, str], tuple[str, Any, float]]

# Where a membership change is recorded: (action, details). The CLI's and the server's audit sinks both fit.
PeopleAudit: TypeAlias = Callable[[str, Row], object]
T = TypeVar("T")

# Coalesce identical profile updates across real changing POSTs, never across visits.
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


@final
@dataclass(frozen=True)
class PeopleUnreadable:
    """people.json exists but cannot be used: it cannot be read, is not UTF-8 JSON (truncated, empty, invalid), or is
    not a Limn people file ({"people": [...]}). `reason` names the file and why, as the server's warning and the CLI's
    refusal show it. While this holds nothing may rewrite the file - the roles in it, the owner's too, would be lost -
    and no one gets a role or a membership from it (limn.security.access.person_role, is_member)."""

    reason: str


def load_people(path: Path) -> list[Row] | PeopleUnreadable:
    """The valid entries of the people.json at path (valid_people); [] when the file does not exist (nobody recorded
    yet); PeopleUnreadable when it exists but cannot be used. An entry that is not a person is dropped as before; only
    a file that is not a people file as a whole is unreadable."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        return PeopleUnreadable("cannot read %s: %s" % (path, e))
    if not isinstance(d, dict) or not isinstance(d.get("people"), list):
        return PeopleUnreadable("%s is not a Limn people file" % path)
    return valid_people(d)


class UnreadableWarning:
    """The stderr warning about an unusable people.json, printed once per breakage: the first read that finds a file
    unusable warns, later ones stay quiet, and a good read re-arms it so a new breakage warns again. The running
    server owns one for the process and hands it to every reader (the role lookup and record_person), so a visit and
    a role check of the same breakage print one line between them. Thread-safe."""

    def __init__(self) -> None:
        """No file is known to be broken yet."""
        self._lock = threading.Lock()
        self._broken: set[str] = set()

    def note(self, path: Path, read: list[Row] | PeopleUnreadable) -> None:
        """Record what a read of path gave: warn for PeopleUnreadable unless this breakage was warned about already;
        forget the breakage after a good read."""
        key = str(path)
        with self._lock:
            if not isinstance(read, PeopleUnreadable):
                self._broken.discard(key)
                return
            if key in self._broken:
                return
            self._broken.add(key)
        print(
            "warning: %s - every person gets the viewer role, --members-only admits no one from it, and no visit is "
            "recorded until it is fixed" % read.reason,
            file=sys.stderr,
        )


def people_text(rows: list[Row]) -> str:
    """The stored text of people.json for rows: {"version": 1, "people": rows} sorted by login, one-space indent,
    non-ASCII kept, ending in a newline. Sorts rows in place (callers pass the list they are about to write)."""
    rows.sort(key=lambda x: x["login"])
    return json.dumps({"version": 1, "people": rows}, ensure_ascii=False, indent=1) + "\n"


@dataclass(frozen=True)
class PeopleBook:
    """The running server's people.json: the state directory it lives in, the process's thread lock, its memo of what
    it last wrote and its unreadable-file warning. The composition root makes the lock, the memo and the warning once;
    a book value is cheap per call."""

    state: Path
    lock: threading.Lock
    seen: SeenMemo
    warning: UnreadableWarning

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
    changed it. first_seen/last_seen are the local wall-clock strings of `now`.

    A file that exists but cannot be used (PeopleUnreadable) is never rewritten - that would replace every role in it
    with this one visitor: nothing is written or memoised, book.warning warns once, and the result is False."""
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
                book.warning.note(book.path, rows)
                if isinstance(rows, PeopleUnreadable):
                    return False
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


@dataclass(frozen=True)
class MemberChange:
    """One membership change as its audit line records it: the action name and its details."""

    action: str
    details: Row


class LastOwner(Exception):
    """Raised by remove_member and set_member_role when the edit would leave the instance without an owner. Raised,
    never returned, so a caller that forgets to look cannot lose the protection. `login` is the owner it protects."""

    login: str

    def __init__(self, login: str) -> None:
        """Remember the last owner's login."""
        super().__init__(login)
        self.login = login


def row_login(row: Mapping[str, object]) -> str:
    """The login of a people.json row (valid_people guarantees a non-empty string)."""
    return str(row["login"])


def _is_owner(row: Row) -> bool:
    """Does the people.json row hold the owner role (a missing role is the default role, an unknown one a viewer)?"""
    return role_value(row.get("role")) == "owner"


def _guard_last_owner(rows: list[Row], hit: Row, login: str) -> None:
    """Raises LastOwner for login when hit, its entry, is the only owner in rows."""
    if _is_owner(hit) and sum(1 for x in rows if _is_owner(x)) == 1:
        raise LastOwner(login)


def add_member(rows: list[Row], login: str, role: str, name: str | None) -> tuple[Row, MemberChange]:
    """Appends login to rows with role (name defaults to the part of the login before @) -> the new entry and its
    `member_added` {login, role} change. Edits rows in place and takes no lock - people_transaction holds it. Raises
    ValueError for an invalid login or role, or a login already in rows."""
    if not valid_login(login):
        raise ValueError(
            "invalid login %r (non-empty, no spaces, at most %d characters, not 'local' or 'agent:...')"
            % (login, LOGIN_MAX)
        )
    if not is_role(role):
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
    shown = " ".join((name or login.split("@")[0]).split())[:NAME_MAX] or login
    if any(x["login"] == login for x in rows):
        raise ValueError("%s is already a member - change the role with `limn member role`" % login)
    entry: Row = {"login": login, "name": shown, "role": role}
    rows.append(entry)
    return entry, MemberChange("member_added", {"login": login, "role": role})


def set_member_role(rows: list[Row], login: str, role: str) -> tuple[Row | None, MemberChange | None]:
    """Sets login's role in rows -> the entry, or None if login is not in rows. The change is `member_role` {login,
    role, previous_role}, or None when the effective role stays the same (the field is still written). Edits rows in
    place and takes no lock. Raises ValueError for an unknown role and LastOwner when the entry is the only owner and
    role is not owner."""
    if not is_role(role):
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
    hit = next((x for x in rows if x["login"] == login), None)
    if hit is None:
        return None, None
    before = role_value(hit.get("role"))
    if role != "owner":
        _guard_last_owner(rows, hit, login)
    hit["role"] = role
    if before == role:
        return hit, None
    return hit, MemberChange("member_role", {"login": login, "role": role, "previous_role": before})


def remove_member(rows: list[Row], login: str) -> tuple[Row | None, MemberChange | None]:
    """Removes login from rows -> the removed entry and its `member_removed` {login, previous_role} change, or
    (None, None) if login is not in rows. Edits rows in place and takes no lock. Raises LastOwner when the entry is
    the only owner."""
    hit = next((x for x in rows if x["login"] == login), None)
    if hit is None:
        return None, None
    _guard_last_owner(rows, hit, login)
    rows.remove(hit)
    return hit, MemberChange("member_removed", {"login": login, "previous_role": role_value(hit.get("role"))})


def people_transaction(
    state: Path,
    step: Callable[[list[Row]], tuple[T, Sequence[MemberChange]]],
    audit: PeopleAudit,
    then: Callable[[], object] | None = None,
) -> T:
    """The one write of people.json for a membership change: takes the people lock once, reads the file, runs
    step(rows), writes the result in people_text's format (atomic, mode 0600), records each change step returned to
    audit and finally runs `then`, all while the lock is still held, so audit lines follow the order of the changes
    and `then` (a second file that must follow people.json, such as the access flag) is serialised with it. Returns
    step's result.

    `then` runs under the lock, after the write and after the audit lines. If it raises, the member changes stand
    and are audited, and the error propagates: for the access flag that leaves the instance unmanaged, the
    deliberately safe failure (nobody gained entry), and the owner can press again since the operation writes a
    target state.

    step edits rows in place and returns (result, changes); it runs under the lock and must not take it again
    (store_lock does not nest). ValueError for an unusable people.json, and anything step raises (ValueError,
    LastOwner), propagates before anything is written or audited. So does LastOwner when the file held an owner and
    step left none: the per-edit guards (remove_member, set_member_role) do not see a step that rewrites rows
    wholesale. An error from `then` propagates after the write and the audit lines, which are not undone."""
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    with store_lock(state, "people"):
        rows = load_people(state / PEOPLE_FILE)
        if type(rows) is PeopleUnreadable:
            raise ValueError(rows.reason)
        owners = [row_login(x) for x in rows if _is_owner(x)]
        out, changes = step(rows)
        if owners and not any(_is_owner(x) for x in rows):
            raise LastOwner(owners[0])
        atomic_write(state / PEOPLE_FILE, people_text(rows), mode=0o600)
        for change in changes:
            audit(change.action, change.details)
        if then is not None:
            then()
    return out


def known_people(people: Iterable[Row], actors: Iterable[Row], is_agent: Callable[[Row], bool]) -> dict[str, Row]:
    """@-tag candidates {login: {login,name,pic?,last_seen?}} - from people.json rows plus flat actor facts.
    The caller's owner extracts actors; this function never interprets their records. An actor is skipped when it is not a dict with a
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
    for actor in actors:
        add(actor)
    return out


def candidates(known: Mapping[str, Row], role_of: Callable[[str], str]) -> list[Row]:
    """GET /api/people's list: the known people (known_people) ordered with everyone who has opened the viewer (a
    last_seen) first, then by name ignoring case, each a copy carrying its role (role_of: the login's role, which the
    caller reads from people.json - limn.security.access.person_role). Pure."""
    ordered = sorted(known.values(), key=lambda x: (x.get("last_seen") is None, x["name"].lower()))
    return [dict(x, role=role_of(x["login"])) for x in ordered]
