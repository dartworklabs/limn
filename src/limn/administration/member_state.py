"""Read and change people.json for the `limn member` command.

The edits and the one write transaction live in limn.security.people, which the server's membership routes use
too; this module is the CLI's thin face over them. Request-time role interpretation stays in limn.security.access.
"""

from pathlib import Path

from limn.administration.targets import AuditSink, CliError
from limn.security.access import ROLES, Json, is_role
from limn.security.people import (
    PEOPLE_FILE,
    LastOwner,
    PeopleUnreadable,
    add_member,
    load_people,
    people_transaction,
    remove_member,
    set_member_role,
)


def load_people_file(state: Path) -> list[Json]:
    """people.json for the CLI: its valid entries, [] if absent, ValueError with the reason if it exists but cannot be
    used - the same judgement the server makes (limn.security.people.load_people), so `limn member` never overwrites a file the
    server would not read either."""
    rows = load_people(Path(state) / PEOPLE_FILE)
    if isinstance(rows, PeopleUnreadable):
        raise ValueError(rows.reason)
    return rows


def _last_owner_refusal(state: Path, e: LastOwner) -> CliError:
    """The CLI's refusal of an edit that would leave the instance without an owner."""
    return CliError(
        "%s is the last owner of %s - add another owner first, then remove or demote %s"
        % (e.login, Path(state) / PEOPLE_FILE, e.login)
    )


def member_add(state: Path, login: str, role: str, name: str | None, audit: AuditSink) -> Json:
    """Adds login to people.json with role (name defaults to the part of the login before @) -> the new entry, and
    audits `member_added` {login, role}. Raises ValueError for an invalid login or role (the command line's text is
    parsed here, is_role), or an existing member."""

    def step(rows: list[Json]):
        """Appends the entry -> (entry, its change)."""
        entry, change = add_member(rows, login, role, name)
        return entry, [change]

    return people_transaction(Path(state), step, audit)


def member_remove(state: Path, login: str, audit: AuditSink) -> Json | None:
    """Removes login from people.json -> the removed entry, or None if it was not a member (or there is no file).
    A removal audits `member_removed` {login, previous_role}. Raises CliError for the last owner."""
    if not (Path(state) / PEOPLE_FILE).exists():
        return None

    def step(rows: list[Json]):
        """Drops the entry -> (entry or None, its change if any)."""
        hit, change = remove_member(rows, login)
        return hit, [] if change is None else [change]

    try:
        return people_transaction(Path(state), step, audit)
    except LastOwner as e:
        raise _last_owner_refusal(state, e) from None


def member_set_role(state: Path, login: str, role: str, audit: AuditSink) -> Json | None:
    """Sets login's role in people.json -> the updated entry, or None if it is not a member (or there is no file).
    A change of the effective role audits `member_role` {login, role, previous_role}; setting the role it already has
    writes the field but no audit line. Raises ValueError for an unknown role (the command line's text is parsed
    here, is_role) and CliError for demoting the last owner."""
    if not is_role(role):
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
    if not (Path(state) / PEOPLE_FILE).exists():
        return None

    def step(rows: list[Json]):
        """Sets the role -> (entry or None, its change if any)."""
        hit, change = set_member_role(rows, login, role)
        return hit, [] if change is None else [change]

    try:
        return people_transaction(Path(state), step, audit)
    except LastOwner as e:
        raise _last_owner_refusal(state, e) from None
