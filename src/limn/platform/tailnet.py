"""The people a tailnet shows this machine: the User map of the local tailscaled's status, read over its LocalAPI.

The list is PARTIAL by construction. The User map holds only the owners of the peers in this node's network map, and
that map is filtered by the tailnet's access rules, so it is neither every user of the tailnet nor free of people who
were removed; it carries no role or account state either. Every result says so (`partial` is always True).

tailscaled is optional. Anything that stops the read - no socket, nobody listening, a timeout, a refusal, a body that
is not JSON or is too long, a node that is not running - is an empty list and a reason, never an exception. The read
is HTTP over the standard library, not the `tailscale` CLI: on macOS, with a stripped environment, that binary exits 0
and prints English prose to stdout, which no exit-code check catches.

Two transports, tried in this order:
- Linux: a unix socket (mode 0666, no operator setting needed to read). The path depends on the distribution, so the
  candidates are tried in order.
- macOS (standalone app): no unix socket. /Library/Tailscale/ipnport is a symlink whose target name is the port, and
  sameuserproof-<port> holds the token; the call is TCP on 127.0.0.1 with HTTP Basic, empty user, the token as password.
  Those files can outlive the app, so a refused connection is an ordinary failure. The App Store build uses another
  mechanism and is not supported: it ends as "not found".

tailscaled answers 403 when any Origin or Referer header is present, and wants Host: local-tailscaled.sock.
"""

import base64
import http.client
import json
import os
import re
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeGuard, final

from limn.security.values import valid_login

STATUS_PATH = "/localapi/v0/status"
LOCAL_HOST = "local-tailscaled.sock"
UNIX_SOCKET_PATHS = (
    "/run/tailscale/tailscaled.sock",
    "/var/run/tailscale/tailscaled.sock",
    "/var/run/tailscaled.socket",
)
MAC_DIR = "/Library/Tailscale"
# One second for the whole read: it runs inside an owner-only GET, and a local daemon answers in milliseconds.
TIMEOUT_SECONDS = 1.0
# 4 MiB: a status with several hundred peers is a few hundred KB; more than this is not a status document.
MAX_BODY_BYTES = 4 << 20
# An answer, a failure included, is reused this long so that a page that polls does not read the daemon each time.
CACHE_SECONDS = 5.0
_READ_CHUNK = 65536
_TOKEN = re.compile(r"[0-9A-Za-z]{8,64}")

Json = Mapping[str, object]


@dataclass(frozen=True)
class TailnetUser:
    """One person the tailnet shows: the login to admit, the name to show, and a picture address (https only) or None."""

    login: str
    name: str
    pic: str | None


@dataclass(frozen=True)
class TailnetDirectory:
    """The candidates, whether the list may be incomplete (always True), and why there are none when it was not read."""

    users: tuple[TailnetUser, ...]
    partial: bool
    reason: str | None


@dataclass(frozen=True)
class Sources:
    """Where to look: the unix socket candidates, the macOS folder, and the body limit. The defaults are the system's."""

    socket_paths: tuple[str, ...] = UNIX_SOCKET_PATHS
    mac_dir: str = MAC_DIR
    max_body: int = MAX_BODY_BYTES


SYSTEM_SOURCES = Sources()


def listed(users: tuple[TailnetUser, ...]) -> TailnetDirectory:
    """A list that was read. It is still partial."""
    return TailnetDirectory(users, True, None)


def unavailable(reason: str) -> TailnetDirectory:
    """No list, and why. The reasons are codes: tailscaled_not_found, _unreachable, _timeout, _refused, _bad_response,
    _too_large, _not_running."""
    return TailnetDirectory((), True, reason)


def _is_object(value: object) -> TypeGuard[Json]:
    """Is value a JSON object (a dict as json.loads makes it)?"""
    return type(value) is dict


def _text(value: object) -> str:
    """A JSON string as is; anything else as the empty string."""
    return value if type(value) is str else ""


def project_users(status: Json, exclude: frozenset[str]) -> tuple[TailnetUser, ...]:
    """The status document's User map as candidates: login, display name and picture only, those whose login could be
    a member and who are not in exclude, ordered by name without regard to case. Pure. A document of another shape
    yields ()."""
    table = status.get("User")
    if not _is_object(table):
        return ()
    found: list[TailnetUser] = []
    for entry in table.values():
        if not _is_object(entry):
            continue
        login = entry.get("LoginName")
        if not valid_login(login) or type(login) is not str or login in exclude:
            continue
        pic = _text(entry.get("ProfilePicURL"))
        found.append(
            TailnetUser(login, _text(entry.get("DisplayName")) or login, pic if pic.startswith("https://") else None)
        )
    return tuple(sorted(found, key=lambda u: (u.name.casefold(), u.login)))


@final
class _Refused(Exception):
    """A definitive failure: stop looking and report this reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@final
class _Skip(Exception):
    """This candidate cannot be used (`found`: something was there but did not answer); try the next."""

    def __init__(self, found: bool):
        super().__init__(found)
        self.found = found


@final
class _UnixConnection(http.client.HTTPConnection):
    """HTTPConnection over a unix socket path."""

    def __init__(self, path: str, timeout: float):
        super().__init__(LOCAL_HOST, timeout=timeout)
        self._path = path

    def connect(self) -> None:
        """Connect the unix socket instead of TCP."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self._path)
        except BaseException:
            sock.close()
            raise
        self.sock = sock


def _remaining(deadline: float) -> float:
    """Seconds left of the budget; _Refused when it is spent."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise _Refused("tailscaled_timeout")
    return left


def _get(connection: http.client.HTTPConnection, headers: dict[str, str], deadline: float, max_body: int) -> bytes:
    """GET the status over connection within the deadline; the body, at most max_body bytes.
    _Refused for a refusal, a bad answer, an oversized body or the deadline; _Skip when nothing answered."""
    try:
        connection.request("GET", STATUS_PATH, headers=headers)
        if connection.sock is not None:
            connection.sock.settimeout(_remaining(deadline))
        response = connection.getresponse()
        if response.status in (401, 403):
            raise _Refused("tailscaled_refused")
        if response.status != 200:
            raise _Refused("tailscaled_bad_response")
        body = bytearray()
        while True:
            # getresponse() closes connection.sock for an answer that says Connection: close, so a read after it cannot
            # be given a shorter timeout: this check ends a body that trickles in, and one that stalls is cut by the
            # per-read timeout set above (at most the budget again).
            _remaining(deadline)
            piece = response.read1(min(_READ_CHUNK, max_body + 1 - len(body)))
            if not piece:
                return bytes(body)
            body += piece
            if len(body) > max_body:
                raise _Refused("tailscaled_too_large")
    except TimeoutError:
        raise _Refused("tailscaled_timeout") from None
    except FileNotFoundError:
        raise _Skip(False) from None
    except OSError:
        raise _Skip(True) from None
    except http.client.HTTPException:
        raise _Refused("tailscaled_bad_response") from None
    finally:
        connection.close()


def _mac_connection(mac_dir: str, timeout: float) -> tuple[http.client.HTTPConnection, dict[str, str]]:
    """The loopback connection and Basic header the macOS app's port and token files describe; _Skip when they do not."""
    try:
        port_text = os.path.basename(os.readlink(os.path.join(mac_dir, "ipnport")))
    except OSError:
        raise _Skip(False) from None
    if not port_text.isdigit() or not 0 < int(port_text) < 65536:
        raise _Skip(True)
    try:
        with open(os.path.join(mac_dir, "sameuserproof-" + port_text), encoding="ascii") as f:
            token = f.read().strip()
    except (OSError, ValueError):
        raise _Skip(True) from None
    if not _TOKEN.fullmatch(token):
        raise _Skip(True)
    auth = "Basic " + base64.b64encode((":" + token).encode("ascii")).decode("ascii")
    return http.client.HTTPConnection("127.0.0.1", int(port_text), timeout=timeout), {
        "Host": LOCAL_HOST,
        "Authorization": auth,
    }


def _fetch(sources: Sources, deadline: float) -> bytes:
    """The status body from the first transport that answers; _Refused for the reason when none does."""
    found = False
    attempts: list[Callable[[], tuple[http.client.HTTPConnection, dict[str, str]]]] = [
        (lambda path=path: (_UnixConnection(path, _remaining(deadline)), {"Host": LOCAL_HOST}))
        for path in sources.socket_paths
    ]
    attempts.append(lambda: _mac_connection(sources.mac_dir, _remaining(deadline)))
    for attempt in attempts:
        try:
            connection, headers = attempt()
            return _get(connection, headers, deadline, sources.max_body)
        except _Skip as skipped:
            found = found or skipped.found
    raise _Refused("tailscaled_unreachable" if found else "tailscaled_not_found")


def _read(sources: Sources, timeout: float) -> TailnetDirectory:
    """One uncached read of the status, as a directory or the reason it is none."""
    try:
        body = _fetch(sources, time.monotonic() + timeout)
        status = _loads(body.decode("utf-8"))
    except _Refused as refused:
        return unavailable(refused.reason)
    except ValueError:
        return unavailable("tailscaled_bad_response")
    except (OSError, http.client.HTTPException):  # unreachable by construction; the read must never raise
        return unavailable("tailscaled_unreachable")
    if not _is_object(status):
        return unavailable("tailscaled_bad_response")
    if status.get("BackendState") != "Running":
        return unavailable("tailscaled_not_running")
    return listed(project_users(status, frozenset()))


_loads: Callable[..., object] = json.loads
_cache: dict[Sources, tuple[float, TailnetDirectory]] = {}


def clear_cache() -> None:
    """Forget the remembered answers (tests start from none)."""
    _cache.clear()


def read_directory(
    now: float, timeout: float = TIMEOUT_SECONDS, *, sources: Sources = SYSTEM_SOURCES
) -> TailnetDirectory:
    """The tailnet people the local tailscaled shows, or why there are none. Never raises. The answer, a failure
    included, is kept CACHE_SECONDS after the `now` it was read at; there is no thread to refresh it. The list is not
    narrowed to non-members here: the caller leaves its own members out of the users."""
    held = _cache.get(sources)
    if held is not None and 0 <= now - held[0] < CACHE_SECONDS:
        return held[1]
    got = _read(sources, timeout)
    _cache[sources] = (now, got)
    return got
