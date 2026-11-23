"""The owner's membership actions: single edits, and the transition that makes the member list and the access flag one
target state (docs/superpowers/specs/2026-11-22-viewer-access-management-design.md).

The transition (apply_managed) is the action the whole design's safety rests on: it must never widen who can get in
without the owner having seen it, and never lock the owner out. So it takes a target list - the people the owner
checked on the screen - and writes exactly that, under the one people lock: people.json first, access.json last. If the
second write fails the instance keeps the new member list and is still not managed (FlagNotWritten). That half is safe
to leave but is not nothing: under --members-only an unmanaged instance already admits by people.json, so a row this
press wrote admits that person at once. The failure says which of the two writes stands, and the operation writes a
target state, so pressing again finishes it.

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
    PeopleUnusable as PeopleUnusable,
    Row,
    add_member,
    people_transaction,
    remove_member,
    row_login,
    set_member_role,
)
from limn.security.values import (
    ROLES,
    SETTABLE_ROLES as SETTABLE_ROLES,
    ManagedAccess,
    is_role,
    is_settable_role,
    role_value,
    valid_login,
)

# The audit action one press of the switch records for the flag itself, next to the member_* lines of the rows it
# changed: a flag-only press changes no row and would otherwise leave no record of an access change.
FLAG_AUDIT_ACTION = "access_managed"


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


class NotManagedNow(Exception):
    """A member change read the access flag under the people lock, about to write, and the flag was not on: the member
    list does not decide who is admitted in that state, so the change the API promises `409 not_managed` for must not
    land. `flag` is what access.json said then - "not-managed" or "unusable"."""

    flag: ManagedAccess

    def __init__(self, flag: ManagedAccess) -> None:
        """Remember what the flag said."""
        super().__init__(flag)
        self.flag = flag


class FlagNotWritten(Exception):
    """people.json was written (and its changes audited) but access.json was not, so the member list stands and the
    flag did not change. Told apart from a people.json that could not be written at all, because here the member
    changes are already in effect for whatever admission the unchanged flag runs - under --members-only a row written
    for a target admits them at once. `error` is the write's own OSError, whose text names a path and so stays in the
    server's log."""

    error: OSError

    def __init__(self, error: OSError) -> None:
        """Remember the failed write."""
        super().__init__(str(error))
        self.error = error


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


def _admitted(
    managed: bool, allow: Collection[str], members_only: bool, members: Collection[str]
) -> frozenset[str] | None:
    """The logins admission lets in with the flag as `managed`, these people.json logins and these run arguments
    (access.admit); None when everyone a header identifies gets in (an open instance), which cannot be listed. Two
    things read it, so both follow the same rule: the result's `newly_admitted`, by comparing the state before the
    press with the state after, and _judge_against, by asking whether the state after lets the requester in."""
    if managed:
        return frozenset(members)
    if members_only:
        return frozenset(members) | frozenset(allow)
    if allow:
        return frozenset(allow)
    return None


def _member_logins(rows: Sequence[Row]) -> set[str]:
    """The logins of these people.json rows."""
    return {row_login(x) for x in rows}


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
        if not is_settable_role(t.role):
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


def _judge_against(
    rows: Sequence[Row],
    wanted: dict[str, str],
    requester: str,
    managed: bool,
    *,
    admitted_without_people: bool,
    allow: Collection[str],
    members_only: bool,
) -> None:
    """The refusals that need the member list, judged on the rows read under the lock and before anything is written.

    RoleNotSettable for a target that names a current owner or agent: the screen does not send those rows, so a request
    that does disagrees with the file, and the owner's approval binds to what they were shown.

    LocksOutOwner when the state this press produces would refuse the requester at once. That state's people.json
    logins are the owner and agent rows (kept whatever is sent) plus the targets, and _admitted - the same reasoning
    admission itself follows - says who it lets in with the flag the press writes and the run's arguments. An instance
    that admits everyone a header identifies (no flag, no --allow, no --members-only) can never shut them out, so it is
    never refused; otherwise the requester must be among those logins. Holding a row is not the same as being admitted:
    with --allow alone an owner row grants no entry once the flag is off, which is how turning management off used to
    lock out the only owner.

    `admitted_without_people` is exempt from that judgement: admission lets such a requester in whatever people.json
    holds (a token principal, and the machine's own user under --auth local, whose --local-user login looks like
    anyone else's). The HTTP boundary knows the principal and decides it there; valid_login() cannot stand for it."""
    fixed = _member_logins([x for x in rows if _is_fixed(x)])
    for login, role in wanted.items():
        if login in fixed:
            raise RoleNotSettable(login, role)
    if admitted_without_people:
        return
    after = _admitted(managed, allow, members_only, fixed | set(wanted))
    if after is not None and requester not in after:
        raise LocksOutOwner(requester)


def _stamp(now: float) -> str:
    """The local wall-clock string of now, as audit lines write it."""
    return datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def apply_managed(
    state: Path,
    targets: Sequence[TargetMember] | None,
    by: Row,
    managed: bool,
    now: float,
    audit: PeopleAudit,
    *,
    allow: Collection[str],
    members_only: bool,
    admitted_without_people: bool,
) -> ManagedResult:
    """Makes people.json's viewer and editor rows match targets, then writes the access flag `managed`, under one hold
    of the people lock. Rows of someone not in targets are removed; a target without a row gets one; a row whose role
    differs is changed. Owner and agent rows are never touched: the request means "make the viewer/editor rows match
    this list", not "make the file match it", so an owner cannot be dropped by omission; and a target that names one is
    refused rather than ignored. Each change is audited (member_added / member_removed /
    member_role). Idempotent: the same targets again change nothing.

    `targets=None` means "leave the viewer and editor rows as they are": the list is taken from the rows read under
    the lock, never from a read made before it, so a member added by another process meanwhile is kept. A stored role outside the four is read as viewer
    (role_value), so that row is kept as a viewer, not rewritten.

    Raises DuplicateTarget, RoleNotSettable and ValueError before any file is opened (_judge), then, on the rows read
    under the lock and before anything is written, RoleNotSettable and LocksOutOwner (_judge_against); ValueError for an
    unusable people.json. A refusal changes nothing.

    OSError when people.json cannot be written: nothing was written or audited. FlagNotWritten when people.json was
    written and access.json was not: the member changes stand and are audited, the flag stays as it was, and no
    `access_managed` line is written. That is the safe half-done state, not a no-op - under --members-only an
    unmanaged instance already admits by people.json, so a row this press wrote for a target admits them at once,
    while under --allow alone or a managed flag that was already on the rows change who gets in only after the flag
    follows. The caller must say so rather than report a bare failure. Pressing again finishes it, since the
    operation writes a target state.

    `allow` and `members_only` are the run's arguments: with the member logins and the flag before and after they say
    who gets in, so the result can name the people this press newly lets in (`newly_admitted`) - for instance an owner
    row kept under --allow, whom today's admission refuses. `admitted_without_people` is the HTTP boundary's answer to
    "does admission let this requester in whatever people.json says" (_judge_against)."""
    judged = None if targets is None else _judge(targets)
    requester = _requester(by)
    state = Path(state)

    def step(rows: list[Row]) -> tuple[ManagedResult, list[MemberChange]]:
        """Edits rows to the target -> the result, and the audit changes."""
        wanted = (
            judged
            if judged is not None
            else {row_login(x): role_value(x.get("role")) for x in rows if not _is_fixed(x)}
        )
        _judge_against(
            rows,
            wanted,
            requester,
            managed,
            admitted_without_people=admitted_without_people,
            allow=allow,
            members_only=members_only,
        )
        flag_before = read_access(state / ACCESS_FILE).managed
        before = (
            frozenset[str]()
            if flag_before == "unusable"
            else _admitted(flag_before == "managed", allow, members_only, _member_logins(rows))
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
        after = _admitted(managed, allow, members_only, _member_logins(rows))
        newly = () if after is None or before is None else tuple(sorted(x for x in after - before if valid_login(x)))
        kept = tuple(sorted(row_login(x) for x in rows if _is_fixed(x)))
        return ManagedResult(tuple(added), tuple(removed), tuple(changed), kept, newly, managed), changes

    def write_flag() -> None:
        """The flag, last: the member list it governs is already on disk. Its own audit line follows the write, so a
        failure (FlagNotWritten, which the member changes have already been audited before) records nothing."""
        try:
            write_access(state / ACCESS_FILE, managed, _stamp(now), requester)
        except OSError as e:
            raise FlagNotWritten(e) from e
        audit(FLAG_AUDIT_ACTION, {"managed": managed, "by": requester})

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


def _require_managed(state: Path) -> None:
    """Raises NotManagedNow unless access.json says the flag is on. Called from inside a people_transaction step, so
    the flag is read under the people lock, against the file the write is about to replace: a check made before the
    lock can be stale by the time the row lands, and under --members-only such a row admits its person at once. Takes
    no lock of its own (store_lock does not nest; this read needs none)."""
    flag = read_access(Path(state) / ACCESS_FILE).managed
    if flag != "managed":
        raise NotManagedNow(flag)


def add_settable(state: Path, login: str, role: str, name: str | None, audit: PeopleAudit) -> Row:
    """add_one for a screen: the role must be one a screen may give (viewer or editor), so no request can write an owner
    or agent row, and the access flag must be on under the lock that writes (NotManagedNow). RoleNotSettable otherwise,
    before any file is opened; the command line uses add_one, which takes all four roles (the first owner is made with
    it) and needs no flag."""
    if not is_settable_role(role):
        raise RoleNotSettable(login, role)

    def step(rows: list[Row]) -> tuple[Row, list[MemberChange]]:
        """Checks the flag, then appends the entry -> (entry, its change)."""
        _require_managed(state)
        entry, change = add_member(rows, login, role, name)
        return entry, [change]

    return people_transaction(Path(state), step, audit)


def set_settable_role(state: Path, login: str, role: str, audit: PeopleAudit) -> Row | None:
    """set_one_role for a screen: the role must be viewer or editor (RoleNotSettable otherwise, before any file is
    opened), so no request can raise anyone to owner or agent, and the access flag must be on under the lock that
    writes (NotManagedNow)."""
    if not is_settable_role(role):
        raise RoleNotSettable(login, role)
    if not (Path(state) / PEOPLE_FILE).exists():
        _require_managed(state)
        return None  # not a member, and no file is created; nothing is written, so nothing needs the lock

    def step(rows: list[Row]) -> tuple[Row | None, list[MemberChange]]:
        """Checks the flag, then sets the role -> (entry or None, its change if any)."""
        _require_managed(state)
        hit, change = set_member_role(rows, login, role)
        return hit, [] if change is None else [change]

    return people_transaction(Path(state), step, audit)


def remove_settable(state: Path, login: str, audit: PeopleAudit) -> Row | None:
    """remove_one for a screen: the access flag must be on under the lock that writes (NotManagedNow), since while it
    is off the member list does not decide who is admitted. The command line uses remove_one, which needs no flag."""
    if not (Path(state) / PEOPLE_FILE).exists():
        _require_managed(state)
        return None  # not a member, and no file is created

    def step(rows: list[Row]) -> tuple[Row | None, list[MemberChange]]:
        """Checks the flag, then drops the entry -> (entry or None, its change if any)."""
        _require_managed(state)
        hit, change = remove_member(rows, login)
        return hit, [] if change is None else [change]

    return people_transaction(Path(state), step, audit)
