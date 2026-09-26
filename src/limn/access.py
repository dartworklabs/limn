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
  loopback-agent warning. server.py owns the process's FileCache for each file and the WarnOnce.
The state helpers behind `limn token` / `limn member` (token_create, member_add, ...) take the state folder and an
audit sink (AuditSink), which the CLI gets from the composition root. people.json's entry check and stored text are
the people store's own (limn.people.valid_people, people_text), imported from there - one format for the running
server's writes and `limn member`'s.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path
from typing import Any, Generic, NamedTuple, TypeAlias, TypeGuard, TypeVar
from urllib.parse import urlparse

from limn.files import atomic_write, store_lock
from limn.guidance import UNAUTHENTICATED, loopback_refused_text
from limn.people import people_text, valid_people
from limn.pins.edit import LOCAL_LOGIN
from limn.web.answers import CONFIRM_BY_HUMAN
from limn.web.errors import HTTPError

Json: TypeAlias = dict[str, Any]
IPNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network
HostEntry: TypeAlias = tuple[str, int | None]        # one --public-host: (lowercase name, port or None)
T = TypeVar("T")

LOCAL_ACTOR = {"login": LOCAL_LOGIN, "name": "로컬/에이전트"}
AGENT_LOGIN_PREFIX = "agent:"      # API-token principals are {"login": "agent:<token name>", "name": "<token name>"}

AUTH_PROVIDERS = ("tailscale", "local", "trusted-proxy")
ROLES = ("owner", "editor", "viewer", "agent")
DEFAULT_ROLE = "editor"                      # a person without a role field - every v0.1 person
VIEWER_POSTS = ("/api/pick", "/api/revision-build")   # computations a viewer may still run (no state change)
TOKEN_PREFIX = "limn_"
TOKEN_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
HEADER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
LOGIN_MAX = 200
NAME_MAX = 100
LOOPBACK_AGENT_DEPRECATION = ("a request from loopback without an identity header or token is treated as the agent - "
                              "this is deprecated and will be removed; give agents a token (limn token create <instance>) "
                              "and turn it off with --no-agent-loopback (AGENT_LOOPBACK=0)")
TAILNET_HEADERLESS = ("신원 헤더 없는 원격 요청입니다(테일넷의 태그 장치 등) — 에이전트는 `Authorization: Bearer <토큰>` 을 "
                      "보내세요(`limn token create <인스턴스>`).")
OWNER_POSTS = ("/api/clear",)               # bulk-destructive: only the owner (a person), and only with a confirmation
OWNER_POST_RE = re.compile(r"/api/pins/\d+/purge")   # permanent delete from the Trash (v0.2.2): only the owner
LOOPBACK = ("127.0.0.1", "localhost", "::1")
DEFAULT_PORT = {"http": 80, "https": 443}
# Headers a reverse proxy adds (tailscale serve sets X-Forwarded-For/-Host/-Proto). A local curl sends none of them.
FORWARDED_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Forwarded-Port", "X-Real-IP",
                     "Forwarded", "Via")


# ---------------------------------------------------------------- what the composition root passes in

@dataclass(frozen=True)
class AccessSettings:
    """The run options identify() and admit() read (server.py builds this from its C per call).

    No field has a default: every caller states every option, so a field added later can never fall back silently to
    a permissive legacy value (such as agent_loopback=True) at a call site that did not think about it."""
    auth: str                                # identity provider: one of AUTH_PROVIDERS
    agent_loopback: bool                     # a headerless loopback request is the agent (deprecated)
    tailnet_agent: bool                      # ...also one that came through tailscale serve (opt-in, deprecated)
    trusted_proxies: tuple[IPNetwork, ...]   # peers whose identity headers --auth trusted-proxy trusts
    proxy_user_header: str                   # the header carrying the user under --auth trusted-proxy
    proxy_name_header: str                   # ...the display name
    proxy_email_header: str | None           # ...the e-mail, the login when present (None = not configured)
    members_only: bool                       # admit only logins in people.json or allow
    allow: frozenset[str]                    # --allow: the logins admitted when set
    local_user: str | None                   # the owner's login under --auth local (None = $USER, then "owner")
    agent_token_file: Path | None            # where this machine's agents keep the token (ADR-0007); never read


@dataclass(frozen=True)
class AccessLookups:
    """What identify() and admit() read at request time besides the request itself. Each call reads the current
    state, so `limn token revoke` and `limn member role` take effect on the next request without a restart."""
    tokens: Callable[[], Sequence[Json]]      # the valid entries of tokens.json now
    roles: Callable[[], Mapping[str, str]]    # {login: role} of everyone in people.json now
    warn_loopback_agent: Callable[[], None]   # the loopback-agent deprecation warning (printed once per process)


class FileCache(Generic[T]):
    """One value derived from a file, derived again only when the file's (inode, mtime_ns, size) changes.

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
    """What identifies this version of file p: (inode, mtime_ns, size); None if it does not exist, "unreadable" if
    it cannot be stat'ed."""
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return "unreadable"
    return (st.st_ino, st.st_mtime_ns, st.st_size)


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
        try:
            s = str(make_header(decode_header(s)))
        except Exception:                                # noqa: BLE001 — a single bad header must never drop the request
            pass
    else:
        try:
            s = s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return "".join(ch for ch in s if ch.isprintable())[:300]


def actor_of(headers: Message) -> tuple[Json, bool]:
    """(actor, whether it came from a header) from the Tailscale-User-* headers. identify() only calls this for a
    loopback peer under --auth tailscale - tailscale serve connects from loopback; any other peer's headers are ignored."""
    login = hdr_text(headers.get("Tailscale-User-Login"))
    if not login:
        return dict(LOCAL_ACTOR), False
    a: Json = {"login": login[:200], "name": (hdr_text(headers.get("Tailscale-User-Name")) or login.split("@")[0])[:100]}
    pic = hdr_text(headers.get("Tailscale-User-Profile-Pic"))
    if pic.startswith("https://") and len(pic) <= 1000:
        a["pic"] = pic
    return a, True


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
            if not name or not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*", name) \
                    or name in LOOPBACK or (port is not None and not 1 <= port <= 65535):
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
        return False                                   # includes a 'null' origin (sandboxed iframe/file://)
    try:
        oport = u.port
    except ValueError:
        return False
    name = u.hostname.lower().rstrip(".")
    hname, hport = split_host(host or "")
    if not hname or hname in LOOPBACK:                 # no Host at all (HTTP/1.0) is treated as loopback - the stricter side
        return name in LOOPBACK
    if hname.endswith(".ts.net"):
        dflt = DEFAULT_PORT[u.scheme]
        return name == hname and (oport or dflt) == (hport or dflt)
    ph = public_host(hname, public_hosts)
    if ph is not None:
        return u.scheme == "https" and name == ph[0] and (oport or 443) == (ph[1] or 443)
    return False


def remote_base_for(host_raw: str, public_hosts: Sequence[HostEntry], port: int) -> str:
    """The base URL used in GET /pins.md's guidance line (§P0c-B). If Host is *.ts.net, 'https://<Host as-is,
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
    return (isinstance(login, str) and 0 < len(login) <= LOGIN_MAX and login.isprintable()
            and not any(c.isspace() for c in login)
            and login != LOCAL_ACTOR["login"] and not login.startswith(AGENT_LOGIN_PREFIX))


def local_owner_actor(local_user: str | None) -> Json:
    """The owner under --auth local: --local-user, else $USER, else 'owner' (read from the environment per call)."""
    login = local_user or os.environ.get("USER") or "owner"
    return {"login": login, "name": login}


def proxy_actor(headers: Message, settings: AccessSettings) -> Json | None:
    """The person an authenticating proxy vouches for, or None without the user header. With --proxy-email-header
    the e-mail (when present) is the login, so people.json / --allow can list e-mail addresses."""
    user = hdr_text(headers.get(settings.proxy_user_header))
    if not user:
        return None
    email = hdr_text(headers.get(settings.proxy_email_header)) if settings.proxy_email_header else ""
    login = (email or user)[:LOGIN_MAX]
    name = (hdr_text(headers.get(settings.proxy_name_header)) or user.split("@")[0])[:NAME_MAX]
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

class Principal(NamedTuple):
    """Who a request is, as identify() decided: what pins record, the role that decides what it may change, and how
    it was identified (admit() treats a header-vouched person differently from a token or the local owner)."""
    actor: Json              # {login, name, pic?} - what pins record
    role: str                # owner | editor | viewer | agent
    via: str                 # header | token | loopback-agent | local-owner


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
        return Principal(a, lookups.roles().get(a["login"], DEFAULT_ROLE), "header")
    if loop:
        a, via = actor_of(headers)
        if via:
            if not valid_login(a["login"]):
                raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")
            return Principal(a, lookups.roles().get(a["login"], DEFAULT_ROLE), "header")
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


def admit(p: Principal, host: str | None, headers: Message | None, settings: AccessSettings,
          roles: Callable[[], Mapping[str, str]]) -> None:
    """May this principal use the instance at all? Only people vouched for by a header are filtered: --members-only
    admits logins in people.json (roles(), read only then) or --allow; otherwise --allow (if set) admits only its
    logins. Without either, everyone the provider identifies is admitted (and recorded in people.json as an editor on
    first visit). Tokens and the local owner are always admitted. A headerless request through the proxy (a tagged
    device) never gets here unless --tailnet-agent is on (identify refuses it), and even then it is refused when a
    list is configured, as in v0.1. A refusal raises HTTPError 403 (not_member / not_allowed / headerless) with its
    browser page."""
    login = p.actor.get("login")
    if p.via == "header":
        if settings.members_only:
            if login not in settings.allow and login not in roles():
                raise HTTPError(403, "이 뷰어의 멤버가 아닙니다: %s — 소유자가 `limn member add` 로 추가해야 합니다." % login,
                                page=("not-member", {"login": login}), reason="not_member")
        elif settings.allow and login not in settings.allow:
            raise HTTPError(403, "이 뷰어에 허용되지 않은 계정입니다: %s" % login, page=("not-allowed", {"login": login}), reason="not_allowed")
    elif p.via == "loopback-agent" and (settings.allow or settings.members_only):
        hname, _ = split_host(host or "")
        if hname.endswith(".ts.net") or (headers is not None and came_through_proxy(headers)):
            raise HTTPError(403, "신원 헤더 없는 테일넷 요청입니다(태그 장치 등). --allow 목록의 계정으로 접속하세요.",
                            page=("no-identity", {}), reason="headerless")


def check_role(p: Principal, path: str, trash_days: int) -> None:
    """Role rule for state-changing (POST) requests, applied once in the handler before dispatch. A viewer may only
    run computations (/api/pick, /api/revision-build); an agent may do everything but confirm; editor and owner may
    do everything a person could in v0.1, except the bulk-destructive OWNER_POSTS (/api/clear, v0.2.1) and the permanent
    delete from the Trash (OWNER_POST_RE, v0.2.2), which only the owner may call; that refusal quotes trash_days, how
    long the Trash keeps a pin. Other owner-only operations - members, tokens, settings - are CLI/file level. A refusal
    raises HTTPError 403 (viewer_only / confirm_by_human / owner_only)."""
    if p.role == "viewer" and path not in VIEWER_POSTS:
        raise HTTPError(403, "보기 권한(viewer)만 있는 계정입니다 — 핀·답글·닫기 같은 변경은 할 수 없습니다.", reason="viewer_only")
    if p.role == "agent" and re.fullmatch(r"/api/pins/\d+/confirm", path):
        raise HTTPError(403, CONFIRM_BY_HUMAN, reason="confirm_by_human")
    if path in OWNER_POSTS and p.role != "owner":
        raise HTTPError(403, "모든 핀을 지우는 일은 소유자(owner)만 합니다 — 에이전트·편집자는 핀을 하나씩 닫으세요.", reason="owner_only")
    if OWNER_POST_RE.fullmatch(path) and p.role != "owner":
        raise HTTPError(403, "휴지통에서 영구 삭제는 소유자(owner)만 합니다 — 삭제한 핀은 %d일 뒤 저절로 지워집니다." % trash_days, reason="owner_only")


# ---------------------------------------------------------------- agent API tokens (<state>/tokens.json, hashed at rest)

# The audit record of a `limn token` / `limn member` change: (action, details) -> appended to audit.jsonl as the OS
# account, via "cli". The composition root wires it (server.cli_audit). Called under the file's lock after the write,
# so audit lines follow the order of the changes. Its return value is ignored; it must not raise for an I/O failure.
AuditSink: TypeAlias = Callable[[str, Json], object]


def token_hash(token: str) -> str:
    """The at-rest form of a token: 'sha256:<hex>'. Only this is stored; the plaintext is never written."""
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _valid_tokens(d: object) -> list[Json]:
    """The token entries of a parsed tokens.json that have a non-empty string id, name and hash; the rest are skipped."""
    rows = d.get("tokens") if isinstance(d, dict) else None
    return [t for t in rows or [] if isinstance(t, dict)
            and all(isinstance(t.get(k), str) and t[k] for k in ("id", "name", "hash"))]


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


def _write_tokens(state: Path, rows: list[Json]) -> None:
    """Replace <state>/tokens.json with rows (atomically, mode 0600)."""
    atomic_write(Path(state) / "tokens.json",
                 json.dumps({"version": 1, "tokens": rows}, ensure_ascii=False, indent=1) + "\n", mode=0o600)


def now_str() -> str:
    """The local wall-clock time as every *_at / created field records it ('YYYY-MM-DD HH:MM:SS')."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def token_create(state: Path, name: str | None, audit: AuditSink) -> tuple[Json, str]:
    """Creates a token -> (entry, plaintext). Only the hash is stored; the plaintext is returned once and never again.
    Records `token_created` {id, name} through audit - never the token or its hash. Raises ValueError for a bad or
    taken name, or an unreadable tokens.json (nothing is written then)."""
    state = Path(state)
    if name is not None and not TOKEN_NAME_RE.fullmatch(name):
        raise ValueError("token name must match [A-Za-z0-9][A-Za-z0-9._-]{0,39}: %r" % name)
    state.mkdir(parents=True, exist_ok=True)
    with store_lock(state, "tokens"):
        rows = load_tokens(state, strict=True)
        names = {t["name"] for t in rows}
        if name is None:
            name, n = "agent", 1
            while name in names:
                n += 1
                name = "agent-%d" % n
        elif name in names:
            raise ValueError("a token named %r already exists (revoke it first, or pick another --name)" % name)
        ids = {t["id"] for t in rows}
        tid = secrets.token_hex(4)
        while tid in ids:
            tid = secrets.token_hex(4)
        plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
        entry = {"id": tid, "name": name, "hash": token_hash(plain), "created": now_str()}
        _write_tokens(state, rows + [entry])
        audit("token_created", {"id": tid, "name": name})
    return entry, plain


def token_revoke(state: Path, ref: str, audit: AuditSink) -> Json | None:
    """Removes the token whose id or name is ref -> the removed entry, or None if there is none. A removal records
    `token_revoked` {id, name} through audit; None writes nothing."""
    state = Path(state)
    if not (state / "tokens.json").exists():
        return None
    with store_lock(state, "tokens"):
        rows = load_tokens(state, strict=True)
        hit = [t for t in rows if t["id"] == ref] or [t for t in rows if t["name"] == ref]
        if not hit:
            return None
        _write_tokens(state, [t for t in rows if t is not hit[0]])
        audit("token_revoked", {"id": hit[0]["id"], "name": hit[0]["name"]})
    return hit[0]


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
    bearer = [v for v in vals if v.strip().split(" ", 1)[0].lower() == "bearer"]
    if not bearer:
        return None
    parts = bearer[0].strip().split(None, 1)
    if len(bearer) > 1 or len(parts) != 2 or not parts[1].strip():
        raise HTTPError(401, "Authorization: Bearer 헤더가 올바르지 않습니다.", reason="bad_bearer")
    return str(parts[1].strip())


# ---------------------------------------------------------------- people.json roles and members

def role_value(v: object) -> str:
    """A people.json role field -> the role. Missing = editor (every v0.1 person); an unknown value = viewer (fail closed)."""
    if v is None:
        return DEFAULT_ROLE
    return v if isinstance(v, str) and v in ROLES else "viewer"


def roles_of(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """{login: role} for every row of people.json (role_value of each row's role field)."""
    return {x["login"]: role_value(x.get("role")) for x in rows}


def load_people_file(state: Path) -> list[Json]:
    """people.json for the CLI: its valid entries (limn.people.valid_people), [] if absent, ValueError if it exists but
    cannot be read (never overwrite what we could not read)."""
    p = Path(state) / "people.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise ValueError("cannot read %s: %s" % (p, e)) from e
    if not isinstance(d, dict) or not isinstance(d.get("people"), list):
        raise ValueError("%s is not a Limn people file" % p)
    return valid_people(d)


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
    audits `member_added` {login, role}. Raises ValueError for an invalid login or role, or an existing member."""
    if not valid_login(login):
        raise ValueError("invalid login %r (non-empty, no spaces, at most %d characters, not 'local' or 'agent:...')"
                         % (login, LOGIN_MAX))
    if role not in ROLES:
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
    assert added is not None                      # fn always returns the new entry or raises
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
    writes the field but no audit line. Raises ValueError for an unknown role."""
    if role not in ROLES:
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
