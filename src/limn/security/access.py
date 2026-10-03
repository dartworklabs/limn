"""Access control (docs/adr/0002-access-control.md): who a request is, whether it may use the instance, what it may change.

The handler runs three checks before it dispatches. identify() picks one identity provider per instance (tailscale
headers, the local owner, or a trusted proxy's headers), and every provider also accepts agent API tokens. admit()
applies --allow and --members-only. check_role() applies the people.json role (viewer / agent / editor / owner) to a
POST. Host/Origin checks (host_ok, origin_ok) and pins.md's base URL (remote_base_for) read the same host rules.

This module is the security boundary, so a refusal RAISES limn.web.errors.HTTPError instead of returning a value. A
thrown refusal cannot be ignored by a caller; a returned one could be dropped by a new call site, and the request
would pass (docs/handbook/code-style-roadmap.md §R10). Status, reason code and text are part of the HTTP contract.

Nothing here reads the run settings or imports server.py. The composition root (server.py) passes:
- AccessSettings: the run options identify/admit read, built from its C per call;
- AccessLookups: the file-backed facts read at request time (tokens.json entries, people.json roles) and the one-time
  loopback-agent warning. server.py owns the process's FileCache for each file and the WarnOnce. An unusable
  people.json reaches here as PeopleUnreadable and grants nothing (person_role, is_member), as an unusable tokens.json
  accepts no token.
The administration slice owns token and member state changes. This module interprets request-time tokens and roles;
the people store owns people.json validation and storage format for both the server and CLI.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import re
import sys
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from email.errors import HeaderParseError
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path
from typing import Any, Generic, Literal, NamedTuple, TypeAlias, TypeGuard, TypeVar, get_args
from urllib.parse import urlparse

from limn.security.guidance import UNAUTHENTICATED, loopback_refused_text
from limn.security.people import PeopleUnreadable
from limn.security.values import CONFIRM_BY_HUMAN, LOCAL_LOGIN, AuthorityScope as AuthorityScope
from limn.web.errors import HTTPError

Json: TypeAlias = dict[str, Any]
IPNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network
HostEntry: TypeAlias = tuple[str, int | None]  # one --public-host: (lowercase name, port or None)
T = TypeVar("T")

LOCAL_ACTOR = {"login": LOCAL_LOGIN, "name": "로컬/에이전트"}
AGENT_LOGIN_PREFIX = "agent:"  # API-token principals are {"login": "agent:<token name>", "name": "<token name>"}

# The security values are closed types: a comparison with a value outside them is a type error (mypy strict, whose
# strict_equality flags a non-overlapping ==, != or in). Text from outside - people.json, the command line - becomes
# one of them only through is_role / is_auth_provider (role_value, access_options, member_add); the tuples are the
# runtime side of the same sets.
AuthProvider: TypeAlias = Literal["tailscale", "local", "trusted-proxy"]  # the identity provider of an instance
Role: TypeAlias = Literal["owner", "editor", "viewer", "agent"]  # what a principal may change (check_role)
Via: TypeAlias = Literal["header", "token", "loopback-agent", "local-owner"]  # how identify() knew the principal
AUTH_PROVIDERS: tuple[AuthProvider, ...] = get_args(AuthProvider)
ROLES: tuple[Role, ...] = get_args(Role)
DEFAULT_ROLE: Role = "editor"  # a person without a role field - every v0.1 person
# people.json as a role lookup reads it: {login: role} of everyone listed, or why the file cannot be used (fail closed)
PeopleRoles: TypeAlias = Mapping[str, Role] | PeopleUnreadable
VIEWER_POSTS = ("/api/pick", "/api/revision-build")  # computations a viewer may still run (no state change)
HEADER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
LOGIN_MAX = 200
NAME_MAX = 100
LOOPBACK_AGENT_DEPRECATION = (
    "a request from loopback without an identity header or token is treated as the agent - "
    "this is deprecated and will be removed; give agents a token (limn token create <instance>) "
    "and turn it off with --no-agent-loopback (AGENT_LOOPBACK=0)"
)
TAILNET_HEADERLESS = (
    "신원 헤더 없는 원격 요청입니다(테일넷의 태그 장치 등) — 에이전트는 `Authorization: Bearer <토큰>` 을 "
    "보내세요(`limn token create <인스턴스>`)."
)
OWNER_POSTS = ("/api/clear",)  # bulk-destructive: only the owner (a person), and only with a confirmation
OWNER_POST_RE = re.compile(r"/api/pins/\d+/purge")  # permanent delete from the Trash (v0.2.2): only the owner
LOOPBACK = ("127.0.0.1", "localhost", "::1")
DEFAULT_PORT = {"http": 80, "https": 443}
# Headers a reverse proxy adds (tailscale serve sets X-Forwarded-For/-Host/-Proto). A local curl sends none of them.
FORWARDED_HEADERS = (
    "X-Forwarded-For",
    "X-Forwarded-Host",
    "X-Forwarded-Proto",
    "X-Forwarded-Port",
    "X-Real-IP",
    "Forwarded",
    "Via",
)


# ---------------------------------------------------------------- what the composition root passes in


@dataclass(frozen=True)
class AccessSettings:
    """The run options identify() and admit() read (server.py builds this from its C per call).

    No field has a default: every caller states every option, so a field added later can never fall back silently to
    a permissive legacy value (such as agent_loopback=True) at a call site that did not think about it."""

    auth: AuthProvider  # identity provider
    agent_loopback: bool  # a headerless loopback request is the agent (deprecated)
    tailnet_agent: bool  # ...also one that came through tailscale serve (opt-in, deprecated)
    trusted_proxies: tuple[IPNetwork, ...]  # peers whose identity headers --auth trusted-proxy trusts
    proxy_user_header: str  # the header carrying the user under --auth trusted-proxy
    proxy_name_header: str  # ...the display name
    proxy_email_header: str | None  # ...the e-mail, the login when present (None = not configured)
    members_only: bool  # admit only logins in people.json or allow
    allow: frozenset[str]  # --allow: the logins admitted when set
    local_user: str | None  # the owner's login under --auth local (None = $USER, then "owner")
    agent_token_file: Path | None  # where this machine's agents keep the token (ADR-0007); never read


@dataclass(frozen=True)
class AccessLookups:
    """What identify() and admit() read at request time besides the request itself. Each call reads the current
    state, so `limn token revoke` and `limn member role` take effect on the next request without a restart."""

    tokens: Callable[[], Sequence[Json]]  # the valid entries of tokens.json now
    roles: Callable[[], PeopleRoles]  # {login: role} of everyone in people.json now, or PeopleUnreadable
    warn_loopback_agent: Callable[[], None]  # the loopback-agent deprecation warning (printed once per process)


class FileCache(Generic[T]):
    """One value derived from a file, derived again only when the file's stat key (_stat_key) changes.

    The key is the path together with that stat, so one cache follows a state folder that changes (tests, a
    restart). A missing file gives `empty` without calling load. A file that cannot be stat'ed still calls load, and
    load decides what an unreadable file means. The owner (server.py) keeps one per file for the process. get() is
    thread-safe, and a caller must not mutate the value it returns."""

    def __init__(self) -> None:
        """An empty cache: the first get() loads."""
        self._lock = threading.Lock()
        self._entry: tuple[tuple[str, object], T] | None = None

    def get(self, path: Path, load: Callable[[], T], empty: T) -> T:
        """The value for path: the cached one while path's stat key is unchanged, else load() (or empty when path
        does not exist), which is then cached under the new key."""
        key = (str(path), _stat_key(path))
        with self._lock:
            if self._entry is None or self._entry[0] != key:
                self._entry = (key, load() if key[1] is not None else empty)
            return self._entry[1]


def _stat_key(p: Path) -> object:
    """What identifies this version of file p: (inode, mtime_ns, size, mode, ctime_ns); None if it does not exist,
    "unreadable" if it cannot be stat'ed. The mode and ctime make a chmod or chown - which change neither the content
    nor mtime but decide whether the file can be read - a new version, so a people.json or tokens.json made readable
    again is read again without a restart."""
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return "unreadable"
    return (st.st_ino, st.st_mtime_ns, st.st_size, st.st_mode, st.st_ctime_ns)


class WarnOnce:
    """A warning printed on stderr the first time it is called, and never again. There is no per-request log. One
    instance per process (server.py owns it); calls from several threads print it once."""

    def __init__(self, text: str) -> None:
        """The warning text, without the "warning: " prefix that is printed before it."""
        self._text = text
        self._lock = threading.Lock()
        self._done = False

    def __call__(self) -> None:
        """Print "warning: <text>" on stderr and flush, unless it was printed before."""
        with self._lock:
            if self._done:
                return
            self._done = True
        print("warning: " + self._text, file=sys.stderr)
        sys.stderr.flush()


# ---------------------------------------------------------------- identity headers and hosts


def hdr_text(v: object) -> str:
    """A header value as printable text, at most 300 characters. tailscale sends non-ASCII values as RFC 2047
    (=?utf-8?q?...?=). If raw UTF-8 arrives instead, a latin-1 mis-decode is undone. A bad header is never an error."""
    if not v:
        return ""
    s = str(v).strip()
    if "=?" in s:
        with contextlib.suppress(Exception):  # noqa: BLE001 — a single bad header must never drop the request
            s = str(make_header(decode_header(s)))
    else:
        with contextlib.suppress(UnicodeEncodeError, UnicodeDecodeError):
            s = s.encode("latin-1").decode("utf-8")
    return "".join(ch for ch in s if ch.isprintable())[:300]


def actor_of(headers: Message) -> tuple[Json, bool]:
    """(actor, whether it came from a header) from the Tailscale-User-* headers. identify() only calls this for a
    loopback peer under --auth tailscale - tailscale serve connects from loopback; any other peer's headers are ignored.
    A nonempty malformed login raises 401 unauthenticated rather than becoming another login or the local actor."""
    raw_login = headers.get("Tailscale-User-Login")
    if not raw_login:
        return dict(LOCAL_ACTOR), False
    login = _identity_login(raw_login)
    a: Json = {
        "login": login,
        "name": (hdr_text(headers.get("Tailscale-User-Name")) or login.split("@")[0])[:100],
    }
    pic = hdr_text(headers.get("Tailscale-User-Profile-Pic"))
    if pic.startswith("https://") and len(pic) <= 1000:
        a["pic"] = pic
    return a, True


def _identity_login(value: str) -> str:
    """Decode a provider's complete login without display cleanup; refuse malformed identities with 401.

    Decode RFC 2047 and raw UTF-8 carried as Latin-1 without replacement characters. Reject surrounding
    whitespace and raw ASCII controls before decoding, then check length, whitespace, controls and reserved
    names before a role lookup. Display cleanup and truncation never apply to a login."""
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")
    login = value
    if "=?" in login:
        try:
            login = "".join(
                part.decode(charset or "ascii") if isinstance(part, bytes) else part
                for part, charset in decode_header(login)
            )
        except (HeaderParseError, LookupError, UnicodeError, ValueError):
            raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated") from None
    else:
        with contextlib.suppress(UnicodeEncodeError, UnicodeDecodeError):
            login = login.encode("latin-1").decode("utf-8")
    if not valid_login(login):
        raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")
    return login


def split_host(v: str) -> tuple[str, int | None]:
    """'name:port' / '[::1]:port' -> (lowercase name, port or None). ('', None) if malformed."""
    v = (v or "").strip().lower()
    if v.startswith("["):
        name, _, rest = v[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    else:
        name, _, port = v.partition(":")
    if port and not re.fullmatch(r"[0-9]{1,5}", port):
        return "", None
    return name.rstrip("."), (int(port) if port else None)


def public_host(name: str, public_hosts: Sequence[HostEntry]) -> HostEntry | None:
    """The (name, port) entry of --public-host matching this Host/Origin name, or None."""
    return next((h for h in public_hosts if h[0] == name), None) if name else None


def host_ok(host: str, public_hosts: Sequence[HostEntry]) -> bool:
    """Is Host a loopback name, *.ts.net or a --public-host? For a loopback name the port is never checked:
    forwarding via SSH -L to a different local port can make Host something like 'localhost:9000', different from
    the actual server port. A DNS-rebinding attack's Host is never a loopback name (an external domain resolving to
    127.0.0.1 doesn't turn the Host header itself into 'localhost'), so leaving the port out here doesn't weaken that
    defense. Cross-origin (CSRF) defense is origin_ok's job."""
    name, _ = split_host(host)
    if name in LOOPBACK:
        return True
    return name.endswith(".ts.net") or public_host(name, public_hosts) is not None


def parse_public_hosts(values: Sequence[object] | None) -> tuple[HostEntry, ...]:
    """--public-host values (repeatable, each a comma list of NAME or NAME:PORT) -> ((name, port or None), ...), the
    first entry of a repeated name kept. Raises ValueError for a value that is not a DNS name with an optional port."""
    out: list[HostEntry] = []
    for v in values or []:
        for item in str(v).split(","):
            item = item.strip()
            if not item:
                continue
            name, port = split_host(item)
            if (
                not name
                or not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*", name)
                or name in LOOPBACK
                or (port is not None and not 1 <= port <= 65535)
            ):
                raise ValueError("--public-host takes a DNS name with an optional :port, got %r" % item)
            if all(h[0] != name for h in out):
                out.append((name, port))
    return tuple(out)


def origin_ok(origin: str, host: str | None, public_hosts: Sequence[HostEntry]) -> bool:
    """Is Origin on the same side as the Host this request arrived on? The rule branches on the kind of Host.

    - Host is loopback: Origin must also be loopback. The port is never checked - forwarding via SSH -L
      makes the browser's Origin/Host port differ from the server's bind port (observed: an 18110->18106
      POST got a 403). There is no legitimate path for a *.ts.net Origin to arrive with a loopback Host
      (tailscale serve preserves Host, confirmed in SKILL.md) - accepting one would let another tailnet's
      public Funnel page CSRF the local user's browser (observed: 200).
    - Host is *.ts.net: Origin must match that host's name and port (a missing port falls back to the scheme default).
    - Host is a --public-host name: Origin must be https://<that name> on the configured port (443 if none was given).
    A request with no Origin (curl/agent/same-origin GET) never reaches this function."""
    u = urlparse(origin.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return False  # includes a 'null' origin (sandboxed iframe/file://)
    try:
        oport = u.port
    except ValueError:
        return False
    name = u.hostname.lower().rstrip(".")
    hname, hport = split_host(host or "")
    if not hname or hname in LOOPBACK:  # no Host at all (HTTP/1.0) is treated as loopback - the stricter side
        return name in LOOPBACK
    if hname.endswith(".ts.net"):
        dflt = DEFAULT_PORT[u.scheme]
        return name == hname and (oport or dflt) == (hport or dflt)
    ph = public_host(hname, public_hosts)
    if ph is not None:
        return u.scheme == "https" and name == ph[0] and (oport or 443) == (ph[1] or 443)
    return False


def remote_base_for(host_raw: str, public_hosts: Sequence[HostEntry], port: int) -> str:
    """The base URL used in GET /pins.md's guidance line (docs/handbook/api.md §원격 에이전트 진입점). If Host is *.ts.net, 'https://<Host as-is,
    including port>'; if it's a --public-host name, 'https://<name>[:<configured port>]'; otherwise (loopback/no
    Host) the loopback URL on this server's port. The handler has already validated Host by this point, so only the
    kind needs to be distinguished here."""
    name, _ = split_host(host_raw or "")
    if name.endswith(".ts.net"):
        return "https://%s" % host_raw.strip()
    ph = public_host(name, public_hosts)
    if ph is not None:
        return "https://%s%s" % (ph[0], ":%d" % ph[1] if ph[1] and ph[1] != 443 else "")
    return "http://127.0.0.1:%d" % port


def host_is_loopback(host: object) -> bool:
    """Did the request name this machine (a loopback Host, or none at all as in HTTP/1.0)?"""
    name, _ = split_host(str(host or ""))
    return not host or not str(host).strip() or name in LOOPBACK


def came_through_proxy(headers: Message) -> bool:
    """Did this loopback request come through a reverse proxy such as tailscale serve? Host alone cannot tell:
    tailscale serve picks the route from the TLS server name and passes the client's Host through unchanged, so a
    tagged device can send 'Host: localhost'. It does set X-Forwarded-For/-Host/-Proto itself (overwriting what the
    client sent), so any forwarding header - or a non-loopback Host - marks a proxied request. A local agent's curl
    sends neither. Limit: a raw TCP forwarder that adds no header (tailscale serve --tcp/--tls-terminated-tcp,
    ssh -L/-R, a plain port forward) is indistinguishable from a local request - use tokens and --no-agent-loopback there."""
    if not host_is_loopback(headers.get("Host")):
        return True
    return any(headers.get(h) is not None for h in FORWARDED_HEADERS)


# ---------------------------------------------------------------- peers and startup options


def _peer_ip(addr: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The TCP peer's address as an IP (an IPv4-mapped IPv6 address as IPv4, a zone id dropped), or None if it is
    not an IP address."""
    try:
        ip = ipaddress.ip_address(str(addr).split("%", 1)[0])
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def peer_is_loopback(addr: object) -> bool:
    """Did the connection come from this machine (a loopback IP)? False for anything that is not an IP."""
    ip = _peer_ip(addr)
    return bool(ip is not None and ip.is_loopback)


def peer_is_trusted_proxy(addr: object, networks: Sequence[IPNetwork]) -> bool:
    """Is the TCP peer inside one of the --trusted-proxies networks? False for anything that is not an IP."""
    ip = _peer_ip(addr)
    return ip is not None and any(ip in n for n in networks)


def parse_networks(spec: str) -> tuple[IPNetwork, ...]:
    """'127.0.0.1,::1,10.0.0.0/8' -> ip_network tuple. Raises ValueError for an entry that is not an address or
    range, or for an empty list."""
    out: list[IPNetwork] = []
    for item in (spec or "").split(","):
        item = item.strip()
        if item:
            try:
                out.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                raise ValueError("--trusted-proxies takes IP addresses or CIDR ranges, got %r" % item) from None
    if not out:
        raise ValueError("--trusted-proxies is empty")
    return tuple(out)


def is_loopback_bind(addr: str) -> bool:
    """Is a --bind address loopback? Raises ValueError for anything but an IP address or 'localhost'."""
    if addr == "localhost":
        return True
    return ipaddress.ip_address(addr).is_loopback


def valid_login(login: object) -> bool:
    """A person's login: non-empty, printable, no whitespace anywhere (a tailnet login is an e-mail address or
    user@github; --local-user and LOCAL_USER already required this), not the agent's 'local' or 'agent:...'. The same rule
    for identity headers, --local-user and `limn member add` (v0.2.1: 'bad login' used to be accepted by the CLI)."""
    return (
        isinstance(login, str)
        and 0 < len(login) <= LOGIN_MAX
        and login.isprintable()
        and not any(c.isspace() for c in login)
        and login != LOCAL_ACTOR["login"]
        and not login.startswith(AGENT_LOGIN_PREFIX)
    )


def local_owner_actor(local_user: str | None) -> Json:
    """The owner under --auth local: --local-user, else $USER, else 'owner' (read from the environment per call)."""
    login = local_user or os.environ.get("USER") or "owner"
    return {"login": login, "name": login}


def proxy_actor(headers: Message, settings: AccessSettings) -> Json | None:
    """The person an authenticating proxy vouches for, or None without the user header. With --proxy-email-header
    the e-mail (when present) is the login, so people.json / --allow can list e-mail addresses. A nonempty malformed
    login raises 401 unauthenticated; display cleanup applies only to the person's name."""
    user = headers.get(settings.proxy_user_header)
    if not user:
        return None
    email = headers.get(settings.proxy_email_header) if settings.proxy_email_header else None
    login = _identity_login(email or user)
    name = (hdr_text(headers.get(settings.proxy_name_header)) or hdr_text(user).split("@")[0])[:NAME_MAX]
    return {"login": login, "name": name}


def file_present(p: Path | None) -> TypeGuard[Path]:
    """Whether p exists - False too when that cannot be told: Path.exists() raises PermissionError in a folder this
    process may not search, and a token-file hint must never fail a pin write or turn a 401 into a 500."""
    if p is None:
        return False
    try:
        return p.exists()
    except OSError:
        return False


def home_or_none() -> Path | None:
    """This account's home folder, or None when neither $HOME nor the password database names one."""
    try:
        return Path.home()
    except (RuntimeError, KeyError):
        return None


# ---------------------------------------------------------------- the three checks


def is_agent_actor(actor: Mapping[str, Any] | None) -> bool:
    """An agent actor: a headerless loopback request (LOCAL_ACTOR, login "local") or an API-token principal (login
    "agent:<name>"). A missing login counts as the headerless loopback agent."""
    login = (actor or {}).get("login", LOCAL_ACTOR["login"])
    return bool(login == LOCAL_ACTOR["login"] or str(login).startswith(AGENT_LOGIN_PREFIX))


class Principal(NamedTuple):
    """Who a request is, as identify() decided: what pins record, the role that decides what it may change, and how
    it was identified (admit() treats a header-vouched person differently from a token or the local owner). Besides
    check_role's route rule, the principal answers the role questions a handler asks about an action (is_human,
    review_on_close) and about a failure (sees_error_detail), so no role comparison lives outside this module."""

    actor: Json  # {login, name, pic?} - what pins record
    role: Role
    via: Via

    def is_human(self) -> bool:
        """Does a person act, as a reply counts it (a person's reply may reopen a closed pin)? Not for an agent actor
        (is_agent_actor), and not for a person whose people.json role is agent either."""
        return not is_agent_actor(self.actor) and self.role != "agent"

    def review_on_close(self, asked: bool | None) -> bool | None:
        """The review flag of this principal's close: what the request asked (asked, from `review`), else True for a
        person with the agent role - they close into review like any agent - else None, and the close service decides
        from the actor."""
        if asked is None and self.role == "agent":
            return True
        return asked

    def sees_error_detail(self) -> bool:
        """May an unexpected exception's text reach this principal in a 500 body? Every role but viewer: the owner,
        editors and agents keep it for diagnosis without the server log. A view-only principal (including an unknown
        role value and anyone while people.json cannot be used) does not, because the text can carry state paths and
        implementation details (docs/handbook/api.md §오류 응답)."""
        return self.role != "viewer"


def identify(headers: Message, peer: str, settings: AccessSettings, lookups: AccessLookups) -> Principal:
    """Who is this request? A valid `Authorization: Bearer` token wins under every provider; an invalid or revoked
    one is a 401 and never falls back to another identity. Otherwise the provider decides (settings.auth):

    - tailscale: Tailscale-User-* headers, trusted only from a loopback peer (tailscale serve). A loopback request
      without them is the agent (LOCAL_ACTOR) while settings.agent_loopback is on - the v0.1 behaviour, deprecated.
    - local: a loopback request is the owner (a person). Tailscale headers are ignored.
    - trusted-proxy: the configured user header, trusted only from a --trusted-proxies peer.
    Anything else is a 401. A refusal raises HTTPError (401 bad_bearer / bad_token / unauthenticated /
    loopback_agent_off, 403 headerless with the no-identity page)."""
    tok = bearer_of(headers)
    if tok is not None:
        t = token_lookup(tok, lookups.tokens())
        if t is None:
            raise HTTPError(401, "토큰이 올바르지 않거나 폐기되었습니다.", reason="bad_token")
        return Principal({"login": AGENT_LOGIN_PREFIX + t["name"], "name": t["name"]}, "agent", "token")
    loop = peer_is_loopback(peer)
    if settings.auth == "local":
        if loop and came_through_proxy(headers):
            # every local request is the owner - one that came through a proxy is someone else (v0.2.1 hardening)
            raise HTTPError(403, TAILNET_HEADERLESS, page=("no-identity", {}), reason="headerless")
        if loop:
            return Principal(local_owner_actor(settings.local_user), "owner", "local-owner")
        raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")
    if settings.auth == "trusted-proxy":
        a = proxy_actor(headers, settings) if peer_is_trusted_proxy(peer, settings.trusted_proxies) else None
        if a is None or not valid_login(a["login"]):
            raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")
        return Principal(a, person_role(lookups.roles(), a["login"]), "header")
    if loop:
        a, via = actor_of(headers)
        if via:
            if not valid_login(a["login"]):
                raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")
            return Principal(a, person_role(lookups.roles(), a["login"]), "header")
        if settings.agent_loopback:
            if came_through_proxy(headers) and not settings.tailnet_agent:
                # tailscale serve connects from loopback too. Without identity headers such a request is a tagged
                # device (or anything else behind the proxy) - never the local agent (v0.2.1).
                raise HTTPError(403, TAILNET_HEADERLESS, page=("no-identity", {}), reason="headerless")
            lookups.warn_loopback_agent()
            return Principal(dict(LOCAL_ACTOR), "agent", "loopback-agent")
        if not came_through_proxy(headers):
            # An agent on this machine with the loopback agent off (ADR-0007): say where its token file is.
            f = settings.agent_token_file
            raise HTTPError(401, loopback_refused_text(f, file_present(f), home_or_none()), reason="loopback_agent_off")
    raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")


def admit(
    p: Principal,
    host: str | None,
    headers: Message | None,
    settings: AccessSettings,
    roles: Callable[[], PeopleRoles],
) -> None:
    """May this principal use the instance at all? Only people vouched for by a header are filtered: --members-only
    admits logins in people.json (roles(), read only then) or --allow; otherwise --allow (if set) admits only its
    logins. Without either, everyone the provider identifies is admitted (and recorded in people.json as an editor on
    first visit). While people.json cannot be used, it lists no one (is_member): --members-only then admits only
    --allow's logins. Tokens and the local owner are always admitted. A headerless request through the proxy (a tagged
    device) never gets here unless --tailnet-agent is on (identify refuses it), and even then it is refused when a
    list is configured, as in v0.1. A refusal raises HTTPError 403 (not_member / not_allowed / headerless) with its
    browser page."""
    login = p.actor.get("login")
    if p.via == "header":
        if settings.members_only:
            if login not in settings.allow and not is_member(roles(), login):
                raise HTTPError(
                    403,
                    "이 뷰어의 멤버가 아닙니다: %s — 소유자가 `limn member add` 로 추가해야 합니다." % login,
                    page=("not-member", {"login": login}),
                    reason="not_member",
                )
        elif settings.allow and login not in settings.allow:
            raise HTTPError(
                403,
                "이 뷰어에 허용되지 않은 계정입니다: %s" % login,
                page=("not-allowed", {"login": login}),
                reason="not_allowed",
            )
    elif p.via == "loopback-agent" and (settings.allow or settings.members_only):
        hname, _ = split_host(host or "")
        if hname.endswith(".ts.net") or (headers is not None and came_through_proxy(headers)):
            raise HTTPError(
                403,
                "신원 헤더 없는 테일넷 요청입니다(태그 장치 등). --allow 목록의 계정으로 접속하세요.",
                page=("no-identity", {}),
                reason="headerless",
            )


def check_role(p: Principal, path: str, trash_days: int) -> None:
    """Role rule for state-changing (POST) requests, applied once in the handler before dispatch. A viewer may only
    run computations (/api/pick, /api/revision-build); an agent may use declared actions except confirm; editor and owner may
    do everything a person could in v0.1, except the bulk-destructive OWNER_POSTS (/api/clear, v0.2.1) and the permanent
    delete from the Trash (OWNER_POST_RE, v0.2.2), which only the owner may call; that refusal quotes trash_days, how
    long the Trash keeps a pin. Other owner-only operations - members, tokens, settings - are CLI/file level. A refusal
    raises HTTPError 403 (viewer_only / confirm_by_human / owner_only)."""
    if p.role == "viewer" and path not in VIEWER_POSTS:
        raise HTTPError(
            403, "보기 권한(viewer)만 있는 계정입니다 — 핀·답글·닫기 같은 변경은 할 수 없습니다.", reason="viewer_only"
        )
    if p.role == "agent" and re.fullmatch(r"/api/pins/\d+/confirm", path):
        raise HTTPError(403, CONFIRM_BY_HUMAN, reason="confirm_by_human")
    if path in OWNER_POSTS and p.role != "owner":
        raise HTTPError(
            403,
            "모든 핀을 지우는 일은 소유자(owner)만 합니다 — 에이전트·편집자는 핀을 하나씩 닫으세요.",
            reason="owner_only",
        )
    if OWNER_POST_RE.fullmatch(path) and p.role != "owner":
        raise HTTPError(
            403,
            "휴지통에서 영구 삭제는 소유자(owner)만 합니다 — 삭제한 핀은 %d일 뒤 저절로 지워집니다." % trash_days,
            reason="owner_only",
        )

    post_operation(path)


# Issuance is confined to the composition root; tests enforce that production imports
# cannot acquire the private constructor key or mint an authority in a feature.
_AUTHORITY_KEY = object()
PIN_OPERATIONS = frozenset(
    {"reply", "close", "reopen", "confirm", "edit", "claim", "unclaim", "drop", "restore", "purge"}
)
DOCUMENT_OPERATIONS = {
    "/api/pin": "add",
    "/api/pick": "pick",
    "/api/rebuild": "rebuild",
    "/api/revision-build": "revision-build",
}
READ_PATHS = frozenset(
    {
        "/",
        "/favicon.ico",
        "/favicon-16.png",
        "/favicon-32.png",
        "/apple-touch-icon.png",
        "/api/version",
        "/sw.js",
        "/api/build",
        "/pdf",
        "/api/revisions",
        "/api/revision-diff",
        "/api/revision-build",
        "/api/revision-pdf",
        "/api/meta",
        "/api/docs",
        "/api/outline-labels",
        "/api/people",
        "/pins.md",
        "/api/pins",
        "/api/pins/dropped",
        "/api/snippet",
        "/api/overlaps",
    }
)


def post_operation(path: str) -> tuple[str, int | None]:
    """Recognize only declared POST operations; unknown registrations remain denied."""
    if path in DOCUMENT_OPERATIONS:
        return DOCUMENT_OPERATIONS[path], None
    if path == "/api/clear":
        return "clear", None
    match = re.fullmatch(r"/api/pins/(\d+)/([a-z]+)", path)
    if match and match[2] in PIN_OPERATIONS:
        return match[2], int(match[1])
    raise HTTPError(404, "없는 경로입니다: %s" % path, reason="not_found")


def check_read(path: str) -> None:
    """Admitted principals may read declared paths; new registrations start denied."""
    if path in READ_PATHS or re.fullmatch(r"/api/pins/\d+", path):
        return
    if path.startswith(("/pages/", "/vendor/pdfjs/")):
        return  # These declared resource families validate their leaf names at their sink.
    raise HTTPError(404, "없는 경로입니다: %s" % path, reason="not_found")


def _same_scope(left: object, right: object) -> bool:
    """Compare scoped resources by owner identity and namespace; other owners by identity."""
    if isinstance(left, AuthorityScope) and isinstance(right, AuthorityScope):
        return (
            left.owner is right.owner
            and left.namespace == right.namespace
            and len(left.resources) == len(right.resources)
            and all(a is b for a, b in zip(left.resources, right.resources, strict=True))
        )
    return left is right


@dataclass(frozen=True, init=False)
class PostAuthority(Mapping[str, Any]):
    """Immutable attribution and authority for one operation, target and instance.

    Only the authorization issuer constructs this value. Mapping access is a copy-free
    attribution projection for existing record writers; it never grants another action.
    Python cannot seal constructors, so an independent source guard limits issuance.
    """

    _scope: object
    _operation: str
    _target: object
    _actor: tuple[tuple[str, str], ...]
    _role: Role
    _via: Via

    def __init__(self, key: object, scope: object, operation: str, target: object, principal: Principal) -> None:
        """Snapshot a verified principal only when the private issuer key is supplied."""
        if key is not _AUTHORITY_KEY:
            raise HTTPError(403, "요청 권한이 올바르지 않습니다.", reason="invalid_authority")
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_operation", operation)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_actor", tuple((k, v) for k, v in principal.actor.items() if isinstance(v, str)))
        object.__setattr__(self, "_role", principal.role)
        object.__setattr__(self, "_via", principal.via)

    def __getitem__(self, key: str) -> Any:
        """Read an attribution field without exposing mutable identity storage."""
        return dict(self._actor)[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate only recorded attribution keys, never scope or role metadata."""
        return (key for key, _ in self._actor)

    def __len__(self) -> int:
        """Return the number of attribution fields."""
        return len(self._actor)

    @property
    def principal(self) -> Principal:
        """Return a detached identity projection for human/review decisions."""
        return Principal(dict(self._actor), self._role, self._via)


def require_authority(authority: PostAuthority, scope: object, operation: str, target: object) -> None:
    """Refuse forged attribution or reuse for another effect before touching resources."""
    if (
        not isinstance(authority, PostAuthority)
        or not _same_scope(authority._scope, scope)
        or authority._operation != operation
        or (
            not _same_scope(authority._target, target)
            if operation in DOCUMENT_OPERATIONS.values()
            else authority._target != target
        )
    ):
        raise HTTPError(403, "요청 권한이 올바르지 않습니다.", reason="invalid_authority")


def _authorize_post(
    principal: Principal, path: str, scope: object, document: object | None, trash_days: int
) -> PostAuthority:
    """Issue authority after admission, role policy and final document selection."""
    check_role(principal, path, trash_days)
    operation, pin = post_operation(path)
    target = document if path in DOCUMENT_OPERATIONS else pin
    if path in DOCUMENT_OPERATIONS and document is None:
        raise HTTPError(403, "요청 권한이 올바르지 않습니다.", reason="invalid_authority")
    return PostAuthority(_AUTHORITY_KEY, scope, operation, target, principal)


# ---------------------------------------------------------------- agent API tokens (<state>/tokens.json, hashed at rest)


def token_hash(token: str) -> str:
    """The at-rest form of a token: 'sha256:<hex>'. Only this is stored; the plaintext is never written."""
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _valid_tokens(d: object) -> list[Json]:
    """The token entries of a parsed tokens.json that have a non-empty string id, name and hash; the rest are skipped."""
    rows = d.get("tokens") if isinstance(d, dict) else None
    return [
        t
        for t in rows or []
        if isinstance(t, dict) and all(isinstance(t.get(k), str) and t[k] for k in ("id", "name", "hash"))
    ]


def load_tokens(state: Path, strict: bool = False) -> list[Json]:
    """The token entries of <state>/tokens.json ([] if absent). An unreadable file warns on stderr and accepts no token.
    strict=True (the CLI, before rewriting the file) raises ValueError on an unreadable or malformed file instead."""
    p = Path(state) / "tokens.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        if strict:
            raise ValueError("cannot read %s: %s" % (p, e)) from e
        print("warning: cannot read %s (%s) - no agent token is accepted until it is fixed" % (p, e), file=sys.stderr)
        return []
    if strict and not (isinstance(d, dict) and isinstance(d.get("tokens"), list)):
        raise ValueError("%s is not a Limn token file" % p)
    return _valid_tokens(d)


def token_lookup(token: str, rows: Sequence[Json]) -> Json | None:
    """The entry of rows whose hash matches token, or None. Compares every entry in constant time (hmac.compare_digest)."""
    h = token_hash(token)
    hit = None
    for t in rows:
        if hmac.compare_digest(t["hash"].encode("utf-8"), h.encode("utf-8")):
            hit = t
    return hit


def bearer_of(headers: Message) -> str | None:
    """The token of an `Authorization: Bearer <token>` header, None when there is no Bearer header. Other schemes
    are not Limn's and are ignored. An empty or repeated Bearer header raises HTTPError 401 bad_bearer - it is never
    read as "no token"."""
    vals = headers.get_all("Authorization") or []
    if len(vals) > 1:
        raise HTTPError(401, "Authorization: Bearer 헤더가 올바르지 않습니다.", reason="bad_bearer")
    bearer = [v for v in vals if v.strip().split(" ", 1)[0].lower() == "bearer"]
    if not bearer:
        return None
    parts = bearer[0].strip().split(None, 1)
    if len(bearer) > 1 or len(parts) != 2 or not parts[1].strip():
        raise HTTPError(401, "Authorization: Bearer 헤더가 올바르지 않습니다.", reason="bad_bearer")
    return str(parts[1].strip())


# ---------------------------------------------------------------- people.json roles and members


def is_role(v: object) -> TypeGuard[Role]:
    """Is v one of the four role names (ROLES)?"""
    return isinstance(v, str) and v in ROLES


def is_auth_provider(v: object) -> TypeGuard[AuthProvider]:
    """Is v one of the identity provider names (AUTH_PROVIDERS)?"""
    return isinstance(v, str) and v in AUTH_PROVIDERS


def role_value(v: object) -> Role:
    """A people.json role field -> the role. Missing = editor (every v0.1 person); an unknown value = viewer (fail closed)."""
    if v is None:
        return DEFAULT_ROLE
    return v if is_role(v) else "viewer"


def roles_of(rows: Sequence[Mapping[str, Any]]) -> dict[str, Role]:
    """{login: role} for every row of people.json (role_value of each row's role field)."""
    return {x["login"]: role_value(x.get("role")) for x in rows}


def people_roles_of(read: list[Json] | PeopleUnreadable) -> PeopleRoles:
    """What a role lookup holds for one read of people.json (limn.security.people.load_people): roles_of its rows, or the
    PeopleUnreadable itself - never an empty mapping, which would make everyone the DEFAULT_ROLE (an escalation)."""
    return read if isinstance(read, PeopleUnreadable) else roles_of(read)


def person_role(roles: PeopleRoles, login: str) -> Role:
    """The role of a person a header vouches for: their people.json role, DEFAULT_ROLE when people.json does not list
    them - and viewer for everyone while people.json cannot be used (least privilege). Keeping the roles of an earlier
    good read was considered and rejected: the answer would then depend on the process's history (a restart would
    change it), and tokens.json fails the same way - an unusable file grants nothing."""
    if isinstance(roles, PeopleUnreadable):
        return "viewer"
    return roles.get(login, DEFAULT_ROLE)


def is_member(roles: PeopleRoles, login: object) -> bool:
    """Whether people.json lists login (what --members-only admits besides --allow); never while it cannot be used."""
    return not isinstance(roles, PeopleUnreadable) and login in roles
