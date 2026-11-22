"""The owner's access routes after the shared request guard: GET /api/access and the four member POSTs
(docs/superpowers/specs/2026-11-22-viewer-access-management-design.md §D).

The role rule - only the owner reaches any of them - is access.py's (check_read, check_role); by the time a function
here runs the caller is the owner. What is judged here is the request: its body, whether the instance is managed, and
the refusals the member operations raise, each turned into one HTTPError whose text names a login or a role and never
a path of the state folder. The writes are limn.security.access_service's; each sink first asks require_authority
whether the authority it was handed is the people store's, for this very operation.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NamedTuple, TypeGuard

from limn.runtime.config import RunConfig
from limn.security.access_service import (
    SETTABLE_ROLES,
    AlreadyMember,
    DuplicateTarget,
    LastOwner,
    LocksOutOwner,
    RoleNotSettable,
    TargetMember,
    TransitionView,
    add_one,
    apply_managed,
    remove_one,
    set_one_role,
    transition_view,
)
from limn.security.values import ManagedAccess, role_value, valid_login
from limn.web.errors import HTTPError

Json = dict[str, object]
CONFIRM_MANAGED = "manage access from the viewer"


class TailnetDirectoryView(NamedTuple):
    """The people the tailnet shows this server who are not members yet: their {login, name, pic?} rows, whether the
    list may be incomplete, and why there is none (reason) when it could not be read."""

    users: tuple[Json, ...]
    partial: bool
    reason: str | None


class AccessFacts(NamedTuple):
    """What access.json says now: the flag (or "unusable" for a file that cannot be used) and its stamp and actor."""

    managed: ManagedAccess
    at: str | None
    by: str | None


@dataclass(frozen=True)
class AccessWiring:
    """What the access routes read and write, bound to one run: its settings, the flag, the member rows (None while
    people.json cannot be used), the tailnet directory (given the logins to leave out), the people store's authority
    scope, the audit sink (action, who, details) and the clock.

    `authorize(authority, operation)` is access.require_authority bound to the people store's scope, with no target: it
    raises invalid_authority unless the authority was minted for exactly this operation on this instance. It is
    injected because the authority's type and its check belong to limn.security.access, which no HTTP module imports;
    the sink still calls it first and cannot be reached without it. `warn` takes the text of a failure that stays in
    the server's log."""

    settings: Callable[[], RunConfig]
    authorize: Callable[[object, str], object]
    warn: Callable[[str], object]
    facts: Callable[[], AccessFacts]
    rows: Callable[[], list[Json] | None]
    directory: Callable[[frozenset[str]], TailnetDirectoryView]
    audit: Callable[[str, Mapping[str, object], Mapping[str, object]], object]
    now: Callable[[], float]


# ---------------------------------------------------------------- refusals


def _bad_login() -> HTTPError:
    """400 for a login no person could hold."""
    return HTTPError(
        400, "로그인이 올바르지 않습니다 — 공백 없는 계정 이름(예: alice@example.com)을 보내세요.", reason="bad_login"
    )


def _bad_request(what: str) -> HTTPError:
    """400 for a body that is not the shape the route reads; what names the field."""
    return HTTPError(400, "요청 본문의 %s 이(가) 올바르지 않습니다." % what, reason="bad_access_request")


def _role_not_settable(login: object) -> HTTPError:
    """400 for a role the screen cannot give: owner and agent are made with the command line."""
    return HTTPError(
        400,
        "화면에서는 viewer 와 editor 역할만 줄 수 있습니다(%s) — 소유자·에이전트는 `limn member` 로 만듭니다." % login,
        reason="role_not_settable",
    )


def _last_owner(e: LastOwner) -> HTTPError:
    """409 for an edit that would leave the instance with no owner."""
    return HTTPError(
        409,
        "%s 은(는) 마지막 소유자(owner)입니다 — 다른 소유자를 먼저 추가한 뒤에 빼거나 내리세요." % e.login,
        reason="last_owner",
    )


def _people_unreadable() -> HTTPError:
    """403 for a people.json that cannot be used; it names the file, not its place."""
    return HTTPError(
        403,
        "people.json 을 읽을 수 없어 멤버를 바꿀 수 없습니다 — 소유자가 파일을 고쳐야 합니다.",
        reason="people_unreadable",
    )


def _access_unreadable() -> HTTPError:
    """403 for an access.json that cannot be used; it names the file, not its place."""
    return HTTPError(
        403,
        "access.json 을 읽을 수 없어 입장을 확인할 수 없습니다 — 소유자가 파일을 고치거나 지워야 합니다.",
        reason="access_unreadable",
    )


def _write_failed(wiring: AccessWiring, e: OSError) -> HTTPError:
    """500 for a file that could not be written. The system's text names a path, so it stays in the server's log."""
    wiring.warn("warning: access change not written: %s" % e)
    return HTTPError(500, "파일을 쓰지 못했습니다 — 서버 로그를 확인한 뒤 다시 눌러 보세요.", reason="internal")


# ---------------------------------------------------------------- reads


def _row_login(row: Mapping[str, object]) -> str:
    """The login of a people.json row (the file's reader guarantees a non-empty string)."""
    return str(row["login"])


def _member(row: Mapping[str, object]) -> Json:
    """One people.json row as the answer shows it: login, name, role and, when recorded, last_seen."""
    login = _row_login(row)
    out: Json = {"login": login, "name": str(row.get("name") or login), "role": role_value(row.get("role"))}
    seen = row.get("last_seen")
    if type(seen) is str:
        out["last_seen"] = seen
    return out


def _transition(view: TransitionView) -> Json:
    """The transition screen's contents: who gets in today, the rows the owner may check, the rows that stay."""
    return {
        "admitted_today": list(view.admitted_today),
        "settable": [_member(x) for x in view.settable],
        "fixed": [dict(_member(x.row), admitted_today=x.admitted_today) for x in view.fixed],
    }


def access_view(wiring: AccessWiring) -> Json:
    """GET /api/access: the flag with its stamp, whether turning it off would admit everyone (neither --allow nor
    --members-only: a set that cannot be listed), the run's arguments, the member rows, the transition screen while the
    instance is not managed, and the tailnet's people who are not members. 403 access_unreadable or people_unreadable
    while either file cannot be used. Reads only."""
    facts, rows, config = wiring.facts(), wiring.rows(), wiring.settings()
    if facts.managed == "unusable":
        raise _access_unreadable()
    if rows is None:
        raise _people_unreadable()
    managed = facts.managed == "managed"
    members_only = config.access.members_only
    out: Json = {"managed": managed}
    if facts.at is not None:
        out["managed_at"] = facts.at
    if facts.by is not None:
        out["managed_by"] = facts.by
    out["unmanaged_admits_everyone"] = not config.allow and not members_only
    out["args"] = {"allow": sorted(config.allow), "members_only": members_only}
    out["members"] = [_member(x) for x in rows]
    if not managed:
        out["transition"] = _transition(transition_view(config.allow, members_only, rows))
    directory = wiring.directory(frozenset(_row_login(x) for x in rows))
    tailnet: Json = {"users": list(directory.users), "partial": directory.partial}
    if directory.reason is not None:
        tailnet["reason"] = directory.reason
    out["tailnet"] = tailnet
    return out


# ---------------------------------------------------------------- writes


def _authorize(wiring: AccessWiring, authority: Mapping[str, object], operation: str) -> None:
    """The authority must be the people store's, for this operation (invalid_authority otherwise)."""
    wiring.authorize(authority, operation)


def _require_managed(wiring: AccessWiring) -> None:
    """A member change needs the flag on: 409 not_managed while it is off, 403 access_unreadable while it is unusable."""
    state = wiring.facts().managed
    if state == "unusable":
        raise _access_unreadable()
    if state != "managed":
        raise HTTPError(
            409, "접근 관리를 먼저 켜세요 — 지금은 멤버 목록이 입장을 정하지 않습니다.", reason="not_managed"
        )


def _audit_for(wiring: AccessWiring, authority: Mapping[str, object]) -> Callable[[str, Json], object]:
    """The people store's audit sink for the owner this authority names: each line is recorded through "http"."""
    by = dict(authority)
    return lambda action, details: wiring.audit(action, by, details)


def _login_of(body: Mapping[str, object]) -> str:
    """The body's login, or 400 bad_login."""
    login = body.get("login")
    if type(login) is not str or not valid_login(login):
        raise _bad_login()
    return login


def _role_of(body: Mapping[str, object], login: str) -> str:
    """The body's role when it is one the screen may give, or 400 role_not_settable."""
    role = body.get("role")
    if type(role) is not str or role not in SETTABLE_ROLES:
        raise _role_not_settable(login)
    return role


def member_add(wiring: AccessWiring, authority: Mapping[str, object], body: Mapping[str, object]) -> Json:
    """POST /api/members/add {login, role, name?}: adds a member -> {ok, member}. 409 already_member."""
    _authorize(wiring, authority, "member-add")
    _require_managed(wiring)
    login = _login_of(body)
    role = _role_of(body, login)
    name = body.get("name")
    if name is not None and type(name) is not str:
        raise _bad_request("name")
    try:
        entry = add_one(wiring.settings().state, login, role, name, _audit_for(wiring, authority))
    except AlreadyMember as e:
        raise HTTPError(
            409, "이미 멤버입니다: %s — 역할은 바꾸기로 고치세요." % e.login, reason="already_member"
        ) from None
    except ValueError:
        raise _people_unreadable() from None
    except OSError as e:
        raise _write_failed(wiring, e) from None
    return {"ok": True, "member": _member(entry)}


def member_role(wiring: AccessWiring, authority: Mapping[str, object], body: Mapping[str, object]) -> Json:
    """POST /api/members/role {login, role}: changes a member's role -> {ok, member}, or {ok: false} for a login that
    is not a member. 409 last_owner when it would demote the only owner."""
    _authorize(wiring, authority, "member-role")
    _require_managed(wiring)
    login = _login_of(body)
    role = _role_of(body, login)
    try:
        entry = set_one_role(wiring.settings().state, login, role, _audit_for(wiring, authority))
    except LastOwner as e:
        raise _last_owner(e) from None
    except ValueError:
        raise _people_unreadable() from None
    except OSError as e:
        raise _write_failed(wiring, e) from None
    return {"ok": False} if entry is None else {"ok": True, "member": _member(entry)}


def member_remove(wiring: AccessWiring, authority: Mapping[str, object], body: Mapping[str, object]) -> Json:
    """POST /api/members/remove {login}: removes a member -> {ok, member}, or {ok: false} for a login that is not a
    member. 409 last_owner when it would remove the only owner."""
    _authorize(wiring, authority, "member-remove")
    _require_managed(wiring)
    login = _login_of(body)
    try:
        entry = remove_one(wiring.settings().state, login, _audit_for(wiring, authority))
    except LastOwner as e:
        raise _last_owner(e) from None
    except ValueError:
        raise _people_unreadable() from None
    except OSError as e:
        raise _write_failed(wiring, e) from None
    return {"ok": False} if entry is None else {"ok": True, "member": _member(entry)}


def _is_list(value: object) -> TypeGuard[list[object]]:
    """Is value a JSON array? (The guard types its elements as the opaque values they are.)"""
    return type(value) is list


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    """Is value a JSON object?"""
    return type(value) is dict


def _targets(wiring: AccessWiring, body: Mapping[str, object], managed: bool) -> list[TargetMember]:
    """The checked lines of the transition screen, parsed. Without `members`, turning the flag off keeps the
    viewer/editor rows as they are (the screen shows no list then); turning it on needs the list, since it is what
    the owner approved."""
    members = body.get("members")
    if members is None and not managed:
        rows = wiring.rows()
        if rows is None:
            raise _people_unreadable()
        return _current_targets(wiring, rows)
    if not _is_list(members):
        raise _bad_request("members")
    targets: list[TargetMember] = []
    for item in members:
        fields = item if _is_object(item) else {}
        login, role = fields.get("login"), fields.get("role")
        if type(login) is not str or type(role) is not str:
            raise _bad_request("members")
        if not valid_login(login):
            raise _bad_login()
        targets.append(TargetMember(login, role))
    return targets


def _current_targets(wiring: AccessWiring, rows: list[Json]) -> list[TargetMember]:
    """The viewer and editor rows as targets: the list that leaves people.json's ordinary members as they are."""
    config = wiring.settings()
    view = transition_view(config.allow, config.access.members_only, rows)
    return [TargetMember(_row_login(x), role_value(x.get("role"))) for x in view.settable]


def set_managed(wiring: AccessWiring, authority: Mapping[str, object], body: Mapping[str, object]) -> Json:
    """POST /api/access/managed {managed, members?, confirm}: makes the viewer/editor rows the checked list and sets the
    flag, under one lock (access_service.apply_managed) -> {ok, managed, added, removed, changed, kept,
    newly_admitted}. 400 confirm_required, bad_access_request, bad_login, role_not_settable; 409 locks_out_owner when
    the requester would be shut out, last_owner; 403 people_unreadable."""
    _authorize(wiring, authority, "access-managed")
    if body.get("confirm") != CONFIRM_MANAGED:
        raise HTTPError(
            400,
            '접근 관리를 바꾸려면 본문에 {"confirm": "%s"} 를 보내세요.' % CONFIRM_MANAGED,
            reason="confirm_required",
        )
    managed = body.get("managed")
    if type(managed) is not bool:
        raise _bad_request("managed")
    targets = _targets(wiring, body, managed)
    config = wiring.settings()
    try:
        result = apply_managed(
            config.state,
            targets,
            dict(authority),
            managed,
            wiring.now(),
            _audit_for(wiring, authority),
            allow=config.allow,
            members_only=config.access.members_only,
        )
    except DuplicateTarget:
        raise _bad_request("members") from None
    except RoleNotSettable as e:
        raise _role_not_settable(e.login) from None
    except LocksOutOwner as e:
        raise HTTPError(
            409,
            "이 목록에는 요청한 소유자 %s 이(가) 없어 곧바로 쫓겨납니다 — 본인을 목록에 두세요." % e.login,
            reason="locks_out_owner",
        ) from None
    except LastOwner as e:
        raise _last_owner(e) from None
    except ValueError:
        raise _people_unreadable() from None
    except OSError as e:
        raise _write_failed(wiring, e) from None
    return {
        "ok": True,
        "managed": result.managed,
        "added": list(result.added),
        "removed": list(result.removed),
        "changed": list(result.changed),
        "kept": list(result.kept),
        "newly_admitted": list(result.newly_admitted),
    }
