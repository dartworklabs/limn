"""The owner's membership actions: single edits, and the transition that makes the member list and the access flag one
target state (docs/superpowers/specs/2026-11-22-viewer-access-management-design.md).

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

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from limn.runtime.paths import ACCESS_FILE
from limn.security.access_store import read_access, write_access
from limn.security.people_store import (
    PEOPLE_FILE,
    AlreadyMember as AlreadyMember,
    LastOwner as LastOwner,
    MemberChange,
    PeopleAudit,
    Row,
    add_member,
    people_transaction,
    remove_member,
    row_login,
    set_member_role,
)
from limn.security.values import ROLES, is_role, role_value, valid_login

# The roles the transition screen can give: owner and agent are made elsewhere (the first owner with the CLI).
SETTABLE_ROLES = ("viewer", "editor")


@dataclass(frozen=True)
class TargetMember:
    """One person the owner checked on the transition screen, with the role chosen for them."""

    login: str
    role: str


@dataclass(frozen=True)
class ManagedResult:
    """What a transition did: the logins it added, removed and gave another role, the owner and agent logins it kept
    (their rows are never edited), `newly_admitted` - the logins this press lets in that were not let in before, for
    whatever cause - and the flag it wrote. A press with a non-empty `newly_admitted` widened admission and is not a
    no-op, whatever the other fields say. (Going from a managed or listed instance to one that admits everyone, which
    cannot be listed, is not in it: that is what an open instance is.)"""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    kept: tuple[str, ...]
    newly_admitted: tuple[str, ...]
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


@dataclass(frozen=True)
class FixedMember:
    """An owner or agent row of people.json: the screen shows it but cannot check or uncheck it, and the transition
    keeps it. `admitted_today` says whether the instance lets this login in as it runs now; one that is not admitted
    today is let in by the transition (people.json lists it) and belongs in the screen's "newly admitted" column."""

    row: Row
    admitted_today: bool


@dataclass(frozen=True)
class TransitionView:
    """What the transition screen needs: who gets in today, the viewer/editor rows the owner may check (`settable`)
    and the owner/agent rows that stay whatever is checked (`fixed`)."""

    admitted_today: tuple[str, ...]
    settable: tuple[Row, ...]
    fixed: tuple[FixedMember, ...]


def transition_view(allow: Collection[str], members_only: bool, rows: Sequence[Row]) -> TransitionView:
    """The transition screen's contents for an unmanaged instance run with --allow/--members-only and holding these
    people.json rows. Only `settable` logins may be sent back as targets: current_admitted also lists owners and
    agents, whom a target must not name. Pure."""
    admitted = current_admitted(allow, members_only, rows)
    everyone = not members_only and not allow  # an open instance admits any person a header identifies
    return TransitionView(
        admitted,
        tuple(x for x in rows if not _is_fixed(x)),
        tuple(FixedMember(x, everyone or row_login(x) in admitted) for x in rows if _is_fixed(x)),
    )


def _admitted(managed: bool, allow: Collection[str], members_only: bool, rows: Sequence[Row]) -> frozenset[str] | None:
    """The logins admission lets in with the flag as `managed`, these rows and these run arguments (access.admit); None
    when everyone a header identifies gets in (an open instance), which cannot be listed."""
    members = {row_login(x) for x in rows}
    if managed:
        return frozenset(members)
    if members_only:
        return frozenset(members | set(allow))
    if allow:
        return frozenset(allow)
    return None


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


def _requester(by: Mapping[str, object]) -> str:
    """The login of the owner pressing the button, which the flag records as its provenance. ValueError when `by`
    carries none, so the file never says "None"."""
    login = by.get("login")
    if type(login) is not str or not login:
        raise ValueError("the requester must carry a login")
    return login


def _judge_against(rows: Sequence[Row], wanted: dict[str, str], requester: str, managed: bool) -> None:
    """The refusals that need the member list, judged on the rows read under the lock and before anything is written.
    RoleNotSettable for a target that names a current owner or agent: the screen does not send those rows, so a request
    that does disagrees with the file, and the owner's approval binds to what they were shown. LocksOutOwner when the
    requester would lose their way in by this press:
    - they hold a viewer/editor row the targets leave out, so it would be removed. This holds for the flag off too:
      under --members-only an unmanaged instance still admits by people.json, so removing the row can refuse them
      unless --allow lists them. Turning management off with the current list does not trigger it.
    - the result is managed and they have neither a line in the targets nor an owner/agent row (which is kept).
    The machine's own user (login `local`, not a valid login) is exempt: under --auth local the loopback owner is
    admitted whatever people.json says."""
    fixed = {row_login(x) for x in rows if _is_fixed(x)}
    for login, role in wanted.items():
        if login in fixed:
            raise RoleNotSettable(login, role)
    if not valid_login(requester) or requester in wanted or requester in fixed:
        return
    if managed or any(row_login(x) == requester for x in rows):
        raise LocksOutOwner(requester)


def _stamp(now: float) -> str:
    """The local wall-clock string of now, as audit lines write it."""
    return datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def apply_managed(
    state: Path,
    targets: Sequence[TargetMember],
    by: Row,
    managed: bool,
    now: float,
    audit: PeopleAudit,
    *,
    allow: Collection[str],
    members_only: bool,
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
    target state.

    `allow` and `members_only` are the run's arguments: with the rows and the flag before and after they say who gets
    in, so the result can name the people this press newly lets in (`newly_admitted`) - for instance an owner row
    kept under --allow, whom today's admission refuses."""
    wanted = _judge(targets)
    requester = _requester(by)
    state = Path(state)

    def step(rows: list[Row]) -> tuple[ManagedResult, list[MemberChange]]:
        """Edits rows to the target -> the result, and the audit changes."""
        _judge_against(rows, wanted, requester, managed)
        flag_before = read_access(state / ACCESS_FILE).managed
        before = (
            frozenset[str]()
            if flag_before == "unusable"
            else _admitted(flag_before == "managed", allow, members_only, rows)
        )
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
        after = _admitted(managed, allow, members_only, rows)
        newly = () if after is None or before is None else tuple(sorted(x for x in after - before if valid_login(x)))
        kept = tuple(sorted(row_login(x) for x in rows if _is_fixed(x)))
        return ManagedResult(tuple(added), tuple(removed), tuple(changed), kept, newly, managed), changes

    def write_flag() -> None:
        """The flag, last: the member list it governs is already on disk."""
        write_access(state / ACCESS_FILE, managed, _stamp(now), requester)

    return people_transaction(state, step, audit, then=write_flag)


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
    created). Audits `member_role` when the effective role changes. ValueError for an unknown role - judged before the
    file is looked at, so a malformed role is never answered "not a member"; LastOwner when the entry is the only owner
    and role is not owner."""
    if not is_role(role):
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
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
