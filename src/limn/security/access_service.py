"""The owner's membership actions: single edits, and the transition that makes the member list and the access flag one
target state (docs/handbook/api.md §접근 관리).

The transition (apply_managed) is the action the whole design's safety rests on: it must never widen who can get in
without the owner having seen it, and never lock the owner out. So it takes a target list - the people the owner
checked on the screen - and writes exactly that, under the one people lock: people.json first, access.json last. If the
second write fails the instance keeps the new member list but is still not managed, which runs today's --allow
judgement, so nobody gained entry; the operation writes a target state, so pressing again finishes it.

Every refusal is judged before any file is opened, so a refusal changes nothing. The refusals are raised as values that
carry the login or the role, never a path: the HTTP layer composes the text for the viewer.

The module knows no run arguments beyond what its callers pass in, no HTTP and no server.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from limn.runtime.paths import ACCESS_FILE
from limn.security.access_store import write_access
from limn.security.people_store import (
    PEOPLE_FILE,
    MemberChange,
    PeopleAudit,
    Row,
    add_member,
    people_transaction,
    remove_member,
    row_login,
    set_member_role,
)
from limn.security.values import role_value, valid_login

# The roles the transition screen can give: owner and agent are made elsewhere (the first owner with the CLI).
SETTABLE_ROLES = ("viewer", "editor")


@dataclass(frozen=True)
class TargetMember:
    """One person the owner checked on the transition screen, with the role chosen for them."""

    login: str
    role: str


@dataclass(frozen=True)
class ManagedResult:
    """What a transition did: the logins it added, removed and gave another role, and the flag it wrote."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    managed: bool


class LocksOutOwner(Exception):
    """The target list does not contain the owner who asked, so the instance would refuse them at once. `login` is
    the owner."""

    login: str

    def __init__(self, login: str) -> None:
        """Remember the owner's login."""
        super().__init__(login)
        self.login = login


class RoleNotSettable(Exception):
    """A target gives `login` a role the screen cannot set: owner and agent, or a name that is no role at all."""

    login: str
    role: str

    def __init__(self, login: str, role: str) -> None:
        """Remember who was given which role."""
        super().__init__(login, role)
        self.login = login
        self.role = role


class DuplicateTarget(Exception):
    """The target list names `login` twice. Refused rather than resolved, so what the screen showed is what is written."""

    login: str

    def __init__(self, login: str) -> None:
        """Remember the repeated login."""
        super().__init__(login)
        self.login = login


def current_admitted(allow: Collection[str], members_only: bool, rows: Sequence[Row]) -> tuple[str, ...]:
    """The logins the transition screen starts with checked: who gets in today, sorted. --members-only admits --allow
    and the people.json members; --allow alone admits only its logins; with neither everyone a header identifies gets
    in, of whom the instance knows those in people.json (and any --allow login). A login no person could hold
    (valid_login) is left out. Pure."""
    members = {row_login(x) for x in rows}
    if members_only:
        admitted = set(allow) | members
    elif allow:
        admitted = set(allow)
    else:
        admitted = members
    return tuple(sorted(login for login in admitted if valid_login(login)))


def _is_fixed(row: Row) -> bool:
    """Is this people.json row an owner or an agent - a row the transition never edits or removes?"""
    return role_value(row.get("role")) in ("owner", "agent")


def _judge(targets: Sequence[TargetMember]) -> dict[str, str]:
    """The target list as {login: role}, or the refusal it deserves. Reads no file. Raises DuplicateTarget for a login
    twice, RoleNotSettable for a role other than viewer and editor, and ValueError for a login no person could hold."""
    wanted: dict[str, str] = {}
    for t in targets:
        if t.login in wanted:
            raise DuplicateTarget(t.login)
        if t.role not in SETTABLE_ROLES:
            raise RoleNotSettable(t.login, t.role)
        if not valid_login(t.login):
            raise ValueError("invalid login %r" % t.login)
        wanted[t.login] = t.role
    return wanted


def _judge_against(rows: Sequence[Row], wanted: dict[str, str], by: Row, managed: bool) -> None:
    """The refusals that need the member list, judged on the rows read under the lock and before anything is written.
    RoleNotSettable for a target that names a current owner or agent: the screen does not send those rows, so a request
    that does disagrees with the file, and the owner's approval binds to what they were shown. LocksOutOwner when the
    instance is to be managed and the requester would not be admitted: a person a header identifies who is neither in
    the targets nor an owner row (owner rows are kept, so they stay admitted).

    The lock-out rule applies only to a managed result: turning management off only widens who may enter (admission
    returns to --allow and --members-only), so it cannot lock anyone out. The machine's own user (login `local`, not a
    valid login) is exempt: under --auth local the loopback owner is admitted whatever people.json says."""
    fixed = {row_login(x) for x in rows if _is_fixed(x)}
    for login, role in wanted.items():
        if login in fixed:
            raise RoleNotSettable(login, role)
    requester = str(by.get("login"))
    if managed and valid_login(requester) and requester not in wanted and requester not in fixed:
        raise LocksOutOwner(requester)


def _stamp(now: float) -> str:
    """The local wall-clock string of now, as audit lines write it."""
    return datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def apply_managed(
    state: Path, targets: Sequence[TargetMember], by: Row, managed: bool, now: float, audit: PeopleAudit
) -> ManagedResult:
    """Makes people.json's viewer and editor rows match targets, then writes the access flag `managed`, under one hold
    of the people lock. Rows of someone not in targets are removed; a target without a row gets one; a row whose role
    differs is changed. Owner and agent rows are never touched: the request means "make the viewer/editor rows match
    this list", not "make the file match it", so an owner cannot be dropped by omission; and a target that names one is
    refused rather than ignored. Each change is audited (member_added / member_removed /
    member_role). Idempotent: the same targets again change nothing.

    Raises DuplicateTarget, RoleNotSettable and ValueError before any file is opened (_judge), then, on the rows read
    under the lock and before anything is written, RoleNotSettable and LocksOutOwner (_judge_against); ValueError for an
    unusable people.json. A refusal changes nothing. OSError when a file cannot be written: after people.json was
    written the member changes stand and are audited and the flag stays as it was, so the instance is still unmanaged -
    the deliberately safe failure, nobody gained entry - and the owner can press again, since the operation writes a
    target state."""
    wanted = _judge(targets)
    state = Path(state)

    def step(rows: list[Row]) -> tuple[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], list[MemberChange]]:
        """Edits rows to the target -> (added, removed, changed logins), and their audit changes."""
        _judge_against(rows, wanted, by, managed)
        added: list[str] = []
        removed: list[str] = []
        changed: list[str] = []
        changes: list[MemberChange] = []
        for held in list(rows):
            login = row_login(held)
            if login not in wanted and not _is_fixed(held):
                _, gone = remove_member(rows, login)
                if gone is not None:
                    removed.append(login)
                    changes.append(gone)
        for login, role in wanted.items():
            hit = next((x for x in rows if x["login"] == login), None)
            if hit is None:
                _, new = add_member(rows, login, role, None)
                added.append(login)
                changes.append(new)
            elif not _is_fixed(hit) and role_value(hit.get("role")) != role:
                _, edit = set_member_role(rows, login, role)
                if edit is not None:
                    changed.append(login)
                    changes.append(edit)
        return (tuple(added), tuple(removed), tuple(changed)), changes

    def write_flag() -> None:
        """The flag, last: the member list it governs is already on disk."""
        write_access(state / ACCESS_FILE, managed, _stamp(now), str(by.get("login")))

    (added, removed, changed) = people_transaction(state, step, audit, then=write_flag)
    return ManagedResult(added, removed, changed, managed)


def add_one(state: Path, login: str, role: str, name: str | None, audit: PeopleAudit) -> Row:
    """Adds login to people.json with role -> the new entry; audits `member_added`. ValueError for an invalid login or
    role or an existing member."""

    def step(rows: list[Row]) -> tuple[Row, list[MemberChange]]:
        """Appends the entry -> (entry, its change)."""
        entry, change = add_member(rows, login, role, name)
        return entry, [change]

    return people_transaction(Path(state), step, audit)


def set_one_role(state: Path, login: str, role: str, audit: PeopleAudit) -> Row | None:
    """Sets login's role -> the updated entry, or None if it is not a member (or there is no file, which is then not
    created). Audits `member_role` when the effective role changes. ValueError for an unknown role; LastOwner when the
    entry is the only owner and role is not owner."""
    if not (Path(state) / PEOPLE_FILE).exists():
        return None

    def step(rows: list[Row]) -> tuple[Row | None, list[MemberChange]]:
        """Sets the role -> (entry or None, its change if any)."""
        hit, change = set_member_role(rows, login, role)
        return hit, [] if change is None else [change]

    return people_transaction(Path(state), step, audit)


def remove_one(state: Path, login: str, audit: PeopleAudit) -> Row | None:
    """Removes login -> the removed entry, or None if it is not a member (or there is no file, which is then not
    created). Audits `member_removed`. LastOwner when the entry is the only owner."""
    if not (Path(state) / PEOPLE_FILE).exists():
        return None

    def step(rows: list[Row]) -> tuple[Row | None, list[MemberChange]]:
        """Drops the entry -> (entry or None, its change if any)."""
        hit, change = remove_member(rows, login)
        return hit, [] if change is None else [change]

    return people_transaction(Path(state), step, audit)
