"""Read and change people.json for the `limn member` command.

The server and this CLI share the people store's validation and wire format, while
request-time role interpretation stays in limn.access. Changes hold the people lock
through the atomic write and audit record.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

from limn.access import LOGIN_MAX, NAME_MAX, ROLES, Json, is_role, role_value, valid_login
from limn.features.administration.targets import AuditSink
from limn.files import atomic_write, store_lock
from limn.people import PEOPLE_FILE, PeopleUnreadable, load_people, people_text


def load_people_file(state: Path) -> list[Json]:
    """people.json for the CLI: its valid entries, [] if absent, ValueError with the reason if it exists but cannot be
    used - the same judgement the server makes (limn.people.load_people), so `limn member` never overwrites a file the
    server would not read either."""
    rows = load_people(Path(state) / PEOPLE_FILE)
    if isinstance(rows, PeopleUnreadable):
        raise ValueError(rows.reason)
    return rows


# One _people_update step: edits rows in place -> (result, audit), audit being (action, details) or None.
PeopleStep: TypeAlias = Callable[[list[Json]], tuple[Json | None, tuple[str, Json] | None]]


def _people_update(state: Path, fn: PeopleStep, audit: AuditSink) -> Json | None:
    """Read-modify-write of <state>/people.json under the same cross-process lock the server uses.

    fn(rows) edits rows in place and returns (result, audit) where audit is (action, details) for a membership change
    or None. people.json is written in the people store's format (limn.people.people_text); after that, the change
    goes to the audit sink while the lock is still held, so audit lines follow the order of the changes. Returns result; ValueError from fn propagates before anything is written."""
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    with store_lock(state, "people"):
        rows = load_people_file(state)
        out, change = fn(rows)
        atomic_write(state / "people.json", people_text(rows), mode=0o600)
        if change is not None:
            audit(change[0], change[1])
    return out


def member_add(state: Path, login: str, role: str, name: str | None, audit: AuditSink) -> Json:
    """Adds login to people.json with role (name defaults to the part of the login before @) -> the new entry, and
    audits `member_added` {login, role}. Raises ValueError for an invalid login or role (the command line's text is
    parsed here, is_role), or an existing member."""
    if not valid_login(login):
        raise ValueError(
            "invalid login %r (non-empty, no spaces, at most %d characters, not 'local' or 'agent:...')"
            % (login, LOGIN_MAX)
        )
    if not is_role(role):
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
    shown = " ".join((name or login.split("@")[0]).split())[:NAME_MAX] or login

    def fn(rows: list[Json]) -> tuple[Json | None, tuple[str, Json] | None]:
        """The _people_update step: appends the entry -> (entry, member_added audit); ValueError if already a member."""
        if any(x["login"] == login for x in rows):
            raise ValueError("%s is already a member - change the role with `limn member role`" % login)
        entry = {"login": login, "name": shown, "role": role}
        rows.append(entry)
        return entry, ("member_added", {"login": login, "role": role})

    added = _people_update(state, fn, audit)
    assert added is not None  # fn always returns the new entry or raises
    return added


def member_remove(state: Path, login: str, audit: AuditSink) -> Json | None:
    """Removes login from people.json -> the removed entry, or None if it was not a member (or there is no file).
    A removal audits `member_removed` {login, previous_role}."""
    if not (Path(state) / "people.json").exists():
        return None

    def fn(rows: list[Json]) -> tuple[Json | None, tuple[str, Json] | None]:
        """The _people_update step: drops the entry -> (entry, member_removed audit), or (None, None) if absent."""
        hit = next((x for x in rows if x["login"] == login), None)
        if hit is None:
            return None, None
        rows.remove(hit)
        return hit, ("member_removed", {"login": login, "previous_role": role_value(hit.get("role"))})

    return _people_update(state, fn, audit)


def member_set_role(state: Path, login: str, role: str, audit: AuditSink) -> Json | None:
    """Sets login's role in people.json -> the updated entry, or None if it is not a member (or there is no file).
    A change of the effective role audits `member_role` {login, role, previous_role}; setting the role it already has
    writes the field but no audit line. Raises ValueError for an unknown role (the command line's text is parsed
    here, is_role)."""
    if not is_role(role):
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
    if not (Path(state) / "people.json").exists():
        return None

    def fn(rows: list[Json]) -> tuple[Json | None, tuple[str, Json] | None]:
        """The _people_update step: sets the role -> (entry, member_role audit or None when the role is unchanged),
        or (None, None) if absent."""
        hit = next((x for x in rows if x["login"] == login), None)
        if hit is None:
            return None, None
        before = role_value(hit.get("role"))
        hit["role"] = role
        if before == role:
            return hit, None
        return hit, ("member_role", {"login": login, "role": role, "previous_role": before})

    return _people_update(state, fn, audit)
