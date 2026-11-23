"""Immutable resource identity shared by authorization and document selection."""

from dataclasses import dataclass
from typing import Literal, TypeAlias, TypeGuard, get_args

# What access.json says: the flag is on, off (or absent), or the file exists but cannot be used (fail closed).
ManagedAccess: TypeAlias = Literal["managed", "not-managed", "unusable"]


@dataclass(frozen=True)
class AuthorityScope:
    """A run resource identity plus its immutable storage namespace.

    A pin store is reconstructed per call; its runtime lock and resolved state
    directory identify the same resource without caching mutable settings. Additional
    resource references are retained and compared by identity, never mutable equality.
    """

    owner: object
    namespace: object
    resources: tuple[object, ...] = ()


LOCAL_LOGIN = "local"
CONFIRM_BY_HUMAN = "확인은 사람이 합니다 — 테일넷 신원으로 접속해 뷰어에서 [확인]을 누르세요."

AGENT_LOGIN_PREFIX = "agent:"  # API-token principals are {"login": "agent:<token name>", "name": "<token name>"}
LOGIN_MAX = 200
NAME_MAX = 100

# The roles are a closed type: a comparison with a value outside it is a type error (basedpyright's
# reportUnnecessaryComparison and reportUnnecessaryContains). Text from outside - people.json, the command line -
# becomes a role only through is_role / role_value; ROLES is the runtime side of the same set.
Role: TypeAlias = Literal["owner", "editor", "viewer", "agent"]  # what a principal may change (check_role)
ROLES: tuple[Role, ...] = get_args(Role)
DEFAULT_ROLE: Role = "editor"  # a person without a role field - every v0.1 person


def valid_login(login: object) -> bool:
    """A person's login: non-empty, printable, no whitespace anywhere (a tailnet login is an e-mail address or
    user@github; --local-user and LOCAL_USER already required this), not the agent's 'local' or 'agent:...'. The same rule
    for identity headers, --local-user and `limn member add` (v0.2.1: 'bad login' used to be accepted by the CLI)."""
    return (
        type(login) is str
        and 0 < len(login) <= LOGIN_MAX
        and login.isprintable()
        and not any(c.isspace() for c in login)
        and login != LOCAL_LOGIN
        and not login.startswith(AGENT_LOGIN_PREFIX)
    )


def is_role(v: object) -> TypeGuard[Role]:
    """Is v one of the four role names (ROLES)?"""
    return type(v) is str and v in ROLES


# The roles the viewer's screens may give a person: owner and agent are made elsewhere (the first owner with the command
# line, agents with tokens), so a screen can never raise anyone's privilege.
SETTABLE_ROLES: tuple[Role, ...] = ("viewer", "editor")


def is_settable_role(v: object) -> TypeGuard[Role]:
    """Is v a role a screen may give: viewer or editor (SETTABLE_ROLES)?"""
    return type(v) is str and v in SETTABLE_ROLES


def role_value(v: object) -> Role:
    """A people.json role field -> the role. Missing = editor (every v0.1 person); an unknown value = viewer (fail closed)."""
    if v is None:
        return DEFAULT_ROLE
    return v if is_role(v) else "viewer"
