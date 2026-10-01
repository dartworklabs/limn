"""The HTTP request handler and server classes: transport, the per-request guard, body reading and route dispatch.

Every request reads its body to completion, passes the Host/Origin check, is identified and admitted (and, for a
POST, role-checked) before any route runs; a refusal anywhere becomes one response in _run. The routes parse what
they take from the body or query string (limn.web.parse) and answer a refused field at once, then call the application
through `app` (limn.web.app.App), which the composition root binds (server.Handler), with the parsed values; no route
reads a body field or a query parameter itself. Each route sends the answer limn.web.answers gives its outcome; the
handler answers only what is its own - a body it cannot read (framing, size, content type, JSON), a Host or Origin it
does not accept, a path no route serves - and the access checks raise their own refusals. The errors are in
limn.web.errors. Statuses, headers and bodies are the agent contract (docs/handbook/api.md).
"""

from __future__ import annotations

import re
import socket
import sys
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import urlparse

from limn.runtime.config import AccessOptions
from limn.web import answers, parse, request_input
from limn.web.answers import accepted
from limn.web.app import Document, Json, Principal, Query, WebApplication
from limn.web.errors import HTTPError, InputRejected, error_page_html, page_lang
from limn.web.reply import Reply, json_reply as _json_reply
from limn.web.routes import GetRequest, OtherPostRequest, PinActionRequest, PostDocRequest

MAX_BODY = 1 << 20


class Server(ThreadingHTTPServer):
    """The IPv4 server: one daemon thread per connection, and a backlog deep enough for bursts."""

    daemon_threads = True
    request_queue_size = 128  # so dozens of concurrent requests don't stall a second at a time on SYN retransmits


class Server6(Server):
    """The same server on an IPv6 --bind address."""

    address_family = socket.AF_INET6


def etag_matches(header: str | None, etag: str) -> bool:
    """Does an If-None-Match header name etag? "*" names any; otherwise a comma-separated list of entity tags, compared
    weakly (a W/ prefix is ignored on either side), as RFC 9110 asks for If-None-Match."""
    if header is None:
        return False
    if header.strip() == "*":
        return True
    want = etag.removeprefix("W/")
    return any(tag.strip().removeprefix("W/") == want for tag in header.split(","))


class Handler(BaseHTTPRequestHandler):
    """One connection's requests. Unbound: a subclass sets `app` (server.Handler) before it serves anything."""

    protocol_version = "HTTP/1.1"
    # If the body arrives shorter than Content-Length and the connection never closes, the read would hang forever. Idle keep-alive connections are also closed after this time.
    timeout = 30

    app: ClassVar[WebApplication]
    principal: Principal
    _raw: bytes

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's parameter name
        """No access log: requests carry identities and pin text, and the server prints what it needs itself."""

    def _send(self, code: int, body: bytes, ctype: str, cache: str | None = None, etag: str | None = None) -> None:
        """Send one complete response: status, Content-Type/Length, Cache-Control (no-store unless given; page images
        cache privately for 10 minutes - they are manuscript pages, like the PDFs), the ETag when given, nosniff,
        WWW-Authenticate on 401, Connection: close on every error, and the anti-framing pair end_headers adds. A 200
        with an ETag that the request's If-None-Match names is sent as 304 Not Modified without a body."""
        if etag is not None and code == 200 and etag_matches(self.headers.get("If-None-Match"), etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache or "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            return
        if code >= 400:
            # The connection is closed after an error. The request may not have been read to completion, and
            # if the leftover bytes get read as the next request, they'd bypass --allow and author attribution (request smuggling).
            self.close_connection = True
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache is None or code >= 400:
            cache = "private, max-age=600" if ctype == "image/png" and code < 400 else "no-store"
        self.send_header("Cache-Control", cache)
        if etag is not None and code < 400:
            self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        if code == 401:
            self.send_header("WWW-Authenticate", 'Bearer realm="limn"')
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        """Close the header block of every response - _send's and the base class's own error pages (a malformed
        request line, an unsupported method) - with X-Frame-Options: DENY and Content-Security-Policy:
        frame-ancestors 'none', so no other site can frame the viewer and trick a click (clickjacking). The policy
        has no other directive: the viewer's inline scripts and styles are not restricted."""
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        super().end_headers()

    def _json(self, obj: object, code: int = 200) -> None:
        """Send obj as a UTF-8 JSON response (non-ASCII kept as is)."""
        self._send(*_json_reply(obj, code))

    def _read_raw(self) -> bytes:
        """Reads the request body to completion before any response, on every path (including GET/403/404).

        Responding without reading it first would let the same connection's leftover bytes be interpreted
        as a "local request with no headers" - since tailscale serve reuses the backend connection, a tailnet user could slip through that gap."""
        self._raw = b""
        if self.headers.get("Transfer-Encoding") is not None:
            self.close_connection = True
            raise HTTPError(
                400, "Transfer-Encoding 은 받지 않습니다. Content-Length 로 보내세요.", reason="transfer_encoding"
            )
        cls = self.headers.get_all("Content-Length") or []
        if len(cls) > 1:
            self.close_connection = True
            raise HTTPError(400, "Content-Length 가 여러 개입니다.", reason="bad_content_length")
        cl = cls[0].strip() if cls else ""
        if cl == "":
            return b""
        if not re.fullmatch(r"[0-9]+", cl):  # isdigit() would also accept latin-1 digits like '²'
            self.close_connection = True
            raise HTTPError(400, "Content-Length 가 음이 아닌 정수가 아닙니다.", reason="bad_content_length")
        digits = cl.lstrip("0") or "0"
        maximum = str(MAX_BODY)
        if len(digits) > len(maximum) or (len(digits) == len(maximum) and digits > maximum):
            self.close_connection = True
            raise HTTPError(413, "요청 본문이 너무 큽니다(1 MiB 이하).", reason="body_too_large")
        n = int(digits)
        raw = self.rfile.read(n) if n else b""
        if len(raw) != n:  # a truncated request - never acted on (including /api/clear)
            self.close_connection = True
            raise HTTPError(
                400, "요청 본문이 Content-Length 보다 짧습니다(연결이 끊겼습니다).", reason="body_truncated"
            )
        self._raw = raw
        return raw

    def _check_singleton_headers(self, settings: AccessOptions) -> None:
        """Reject ambiguous security headers before either value can become identity.

        Forwarding lists and content negotiation headers retain their list semantics.
        Configured proxy identities are checked only in their provider mode.
        """
        if len(self.headers.get_all("Authorization") or []) > 1:
            raise HTTPError(401, "Authorization: Bearer 헤더가 올바르지 않습니다.", reason="bad_bearer")
        names = [
            "Host",
            "Origin",
            "Content-Type",
            "Tailscale-User-Login",
            "Tailscale-User-Name",
            "Tailscale-User-Profile-Pic",
        ]
        if settings.auth == "trusted-proxy":
            names.extend([settings.proxy_user_header, settings.proxy_name_header])
            if settings.proxy_email_header:
                names.append(settings.proxy_email_header)
        if any(len(self.headers.get_all(name) or []) > 1 for name in names):
            raise HTTPError(400, "보안 헤더는 한 번만 보내세요.", reason="duplicate_header")

    def _check_origin(self) -> None:
        """Blocks cross-origin requests (CSRF) and DNS rebinding.

        - Host: every request must have a loopback name (':' then a port) or *.ts.net.
          DNS rebinding is a browser reaching 127.0.0.1 via evil.example, which shows up in Host.
        - Origin: if present, must be loopback when Host is loopback (port irrelevant - SSH -L), or the same
          origin as that host when Host is *.ts.net (origin_ok).
          A browser always attaches Origin to a cross-origin POST. curl/agents send no Origin, so this has no effect on them."""
        # --no-origin-check: an escape hatch for when the observed path differs from expectations
        config = self.app.settings()
        self._check_singleton_headers(config.access)
        if not config.origin_check:
            return
        host = self.headers.get("Host")
        # Checked independent of whether the Tailscale-User-* header is present. That header can also be
        # carried on a same-origin GET from a rebinding page with no preflight, so exempting it via that header would bypass the defense entirely (observed).
        if host is not None and not self.app.guards.host_ok(host):
            raise HTTPError(403, "허용되지 않은 Host 입니다: %s" % self.app.header_text(host)[:100], reason="bad_host")
        origin = self.headers.get("Origin")
        if origin is not None and not self.app.guards.origin_ok(origin, host):
            raise HTTPError(
                403, "다른 출처의 요청은 받지 않습니다: %s" % self.app.header_text(origin)[:100], reason="bad_origin"
            )

    def _guard(self) -> Json:
        """Every request: read the body, check Host/Origin, identify (401), admit (403). Leaves the principal on
        self.principal and returns its actor (what pins record)."""
        self._read_raw()
        self._check_origin()
        peer = self.client_address[0] if isinstance(self.client_address, tuple) and self.client_address else ""
        p = self.app.guards.identify(self.headers, peer)
        self.app.guards.admit(p, self.headers.get("Host"), self.headers)
        self.principal = p
        return p.actor

    def _record(self, actor: Json) -> None:
        """people.json for a person who opened the viewer or wrote something (agents never). The local owner is recorded as owner."""
        self.app.recorder.record(actor, role="owner" if self.principal.via == "local-owner" else None)

    def _wants_page(self) -> bool:
        """A browser opening the viewer itself (GET / for HTML) - it gets a readable page on a refusal, not JSON."""
        return (
            self.command == "GET"
            and urlparse(self.path).path == "/"
            and "text/html" in (self.headers.get("Accept") or "")
        )

    def _refuse(self, e: HTTPError) -> None:
        """Send a refusal: the readable HTML page to a browser opening / (in page_lang's language, with the run's
        --ui-lang as the default), the JSON error body to everyone else."""
        if self._wants_page():
            query = request_input.query_values(urlparse(self.path).query)
            lang = page_lang(
                self.headers, {} if isinstance(query, InputRejected) else query, self.app.settings().ui_lang
            )
            return self._send(
                e.code, error_page_html(e, lang, self.app.messages()).encode("utf-8"), "text/html; charset=utf-8"
            )
        self._json(e.body, e.code)

    def _run(self, fn: Callable[[], None]) -> None:
        """Runs one request handler and turns its refusal into the response: HTTPError as is (the answers raise it for
        every refused outcome), a dropped connection silently, anything else as a 500 with the traceback on stderr. A
        browser opening / gets an HTML page instead of JSON."""
        try:
            fn()
        except HTTPError as err:
            self._refuse(err)
        except (TimeoutError, BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as e:  # noqa: BLE001 — reports as JSON instead of dropping the connection
            traceback.print_exc(file=sys.stderr)
            try:
                self._json({"error": "서버 내부 오류: %s" % e, "reason": "internal"}, 500)
            except OSError:
                self.close_connection = True

    def do_GET(self) -> None:
        """BaseHTTPRequestHandler's entry for GET."""
        self._run(self._get)

    def do_POST(self) -> None:
        """BaseHTTPRequestHandler's entry for POST."""
        self._run(self._post)

    def _get(self) -> None:
        """A GET: the guard, then the route for the request's document (?doc=, the first document if absent)."""
        actor = self._guard()
        u = urlparse(self.path)
        path, q = u.path, accepted(request_input.query_values(u.query))
        self.app.guards.check_read(path)
        # A document-scoped path takes ?doc=<key> (the first document if absent) and is handled for that document (§Multiple documents).
        return self._get_doc(actor, path, q, self._request_doc(accepted(parse.parse_doc_choice(q))))

    def _request_doc(self, choice: parse.DocChoice) -> Document:
        """The document a request names (parsed by parse.parse_doc_choice), found by the server: the first document, or
        the one holding the file hint, when neither ?doc= nor the body names one. A new pin's own doc in the body then
        wins over ?doc= when it names another (as it always has). 404 unknown_doc for a key this instance does not
        serve (answers.found_doc)."""
        app = self.app
        D = answers.found_doc(app.selector.select(choice.key, choice.file_hint), app.header_text)
        if choice.body_key is not None and choice.body_key != D.key:
            D = answers.found_doc(app.selector.select(choice.body_key, None), app.header_text)
        return D

    def _get_doc(self, actor: Json, path: str, q: Query, D: Document) -> None:
        """GET routes that act on the request's document D (?doc=, found in _get), tried group by group in the order
        the routes have always been matched (a /pages/ name with no image falls through): registered feature routes. Sends the matching
        route answers, or 404 not_found when none matches; refusals propagate to _run as HTTPError."""
        reply = self._get_registered(actor, path, q, D)
        if reply is None:
            raise HTTPError(404, "없는 경로입니다: %s" % path, reason="not_found")
        self._send(*reply)

    def _get_registered(self, actor: Json, path: str, q: Query, D: Document) -> Reply | None:
        """Try the application's feature-owned GET routes in registration order."""
        request = GetRequest(
            path, q, D, actor, self.principal, self.headers.get("Host") or "", lambda: self._record(actor)
        )
        for route in self.app.routes.bundle.get:
            reply = route(request)
            if reply is not None:
                return reply
        return None

    def _body(self) -> Json:
        """The request body (already read in full) as a JSON object; {} when empty. 415 bad_content_type unless it is
        application/json (a cross-origin form post needs no preflight), 400 bad_json unless it is a JSON object."""
        raw = self._raw
        if not raw.strip():
            return {}
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            # A cross-origin "simple request" (text/plain form) arrives with no preflight - accepting only JSON closes off that path.
            raise HTTPError(415, "본문은 Content-Type: application/json 으로 보내세요.", reason="bad_content_type")
        return accepted(request_input.json_object(raw))

    def _post(self) -> None:
        """A POST: the guard, the role check (before any state change), the body/query, scoped authority, the person record, then the route -
        for the request's document when the route acts on one."""
        actor = self._guard()
        u = urlparse(self.path)
        path = u.path
        self.app.guards.check_role(self.principal, path)  # the one place roles are enforced, before any state change
        d = self._body()
        q = accepted(request_input.query_values(u.query))
        registered = next((route for route in self.app.routes.bundle.post_documents if route.path == path), None)
        if registered is not None:
            D = self._request_doc(accepted(parse.parse_doc_choice(q, d, new_pin=registered.new_pin)))
            authority = self.app.guards.authorize_post(self.principal, path, D)
            self._record(dict(authority))
            return self._json(*registered.action(PostDocRequest(q, d, D, authority, authority.principal)))
        return self._post_other(actor, path, d)

    def _post_other(self, actor: Json, path: str, d: Json) -> None:
        """Dispatch guarded POSTs by pin action or exact path; anything else is 404."""
        authority = self.app.guards.authorize_post(self.principal, path)
        self._record(dict(authority))
        m = re.fullmatch(r"/api/pins/(\d+)/([a-z]+)", path)
        if m:
            action = self.app.routes.bundle.pin_actions.get(m.group(2))
            if action is not None:
                return self._json(action(PinActionRequest(int(m.group(1)), authority, d, authority.principal)))
        other_post = self.app.routes.bundle.other_posts.get(path)
        if other_post is not None:
            return self._json(other_post(OtherPostRequest(authority, d, authority.principal)))
        raise HTTPError(404, "없는 경로입니다: %s" % path, reason="not_found")
