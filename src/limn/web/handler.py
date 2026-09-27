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

import json
import os
import re
import socket
import sys
import traceback
from collections.abc import Callable, Mapping
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, NamedTuple
from urllib.parse import parse_qs, urlparse

from limn.features.pins.lifecycle import http as lifecycle_http
from limn.mark import png as mark_png
from limn.web import answers, parse
from limn.web.answers import accepted
from limn.web.app import App, Document, Json, Principal, Query
from limn.web.errors import HTTPError, error_page_html, page_lang

MAX_BODY = 1 << 20
# A page image name GET /pages/<name> serves: the page-N.png files a build writes into the page directory (limn.build).
PAGE_FILE_RE = re.compile(r"page-\d+\.png")
# The Content-Type of a file the /vendor/pdfjs/ route serves, by suffix (limn.files.vendor_file admits only .mjs).
VENDOR_MIME: Mapping[str, str] = {".mjs": "text/javascript; charset=utf-8"}


class Reply(NamedTuple):
    """One complete response a GET route answers with, for Handler._send: status, body, Content-Type and
    Cache-Control (None: _send's default)."""

    code: int
    body: bytes
    ctype: str
    cache: str | None = None


def _json_reply(obj: object, code: int = 200) -> Reply:
    """obj as a UTF-8 JSON response (non-ASCII kept as is)."""
    return Reply(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")


def _read(path: Path) -> bytes | None:
    """A served file's bytes, or None when it cannot be read (the route then answers 404 or falls through)."""
    try:
        return path.read_bytes()
    except OSError:
        return None


class Server(ThreadingHTTPServer):
    """The IPv4 server: one daemon thread per connection, and a backlog deep enough for bursts."""

    daemon_threads = True
    request_queue_size = 128  # so dozens of concurrent requests don't stall a second at a time on SYN retransmits


class Server6(Server):
    """The same server on an IPv6 --bind address."""

    address_family = socket.AF_INET6


class Handler(BaseHTTPRequestHandler):
    """One connection's requests. Unbound: a subclass sets `app` (server.Handler) before it serves anything."""

    protocol_version = "HTTP/1.1"
    # If the body arrives shorter than Content-Length and the connection never closes, the read would hang forever. Idle keep-alive connections are also closed after this time.
    timeout = 30

    app: ClassVar[App]
    principal: Principal
    _raw: bytes

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's parameter name
        """No access log: requests carry identities and pin text, and the server prints what it needs itself."""

    def _send(self, code: int, body: bytes, ctype: str, cache: str | None = None) -> None:
        """Send one complete response: status, Content-Type/Length, Cache-Control (no-store unless given; page images
        cache privately for 10 minutes - they are manuscript pages, like the PDFs), nosniff, WWW-Authenticate on 401,
        Connection: close on every error, and the anti-framing pair end_headers adds."""
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
        if len(set(v.strip() for v in cls)) > 1:
            self.close_connection = True
            raise HTTPError(400, "Content-Length 가 여러 개입니다.", reason="bad_content_length")
        cl = cls[0].strip() if cls else ""
        if cl == "":
            return b""
        if not re.fullmatch(r"[0-9]+", cl):  # isdigit() would also accept latin-1 digits like '²'
            self.close_connection = True
            raise HTTPError(400, "Content-Length 가 음이 아닌 정수가 아닙니다.", reason="bad_content_length")
        n = int(cl)
        if n > MAX_BODY:
            self.close_connection = True
            raise HTTPError(413, "요청 본문이 너무 큽니다(1 MiB 이하).", reason="body_too_large")
        raw = self.rfile.read(n) if n else b""
        if len(raw) != n:  # a truncated request - never acted on (including /api/clear)
            self.close_connection = True
            raise HTTPError(
                400, "요청 본문이 Content-Length 보다 짧습니다(연결이 끊겼습니다).", reason="body_truncated"
            )
        self._raw = raw
        return raw

    def _check_origin(self) -> None:
        """Blocks cross-origin requests (CSRF) and DNS rebinding.

        - Host: every request must have a loopback name (':' then a port) or *.ts.net.
          DNS rebinding is a browser reaching 127.0.0.1 via evil.example, which shows up in Host.
        - Origin: if present, must be loopback when Host is loopback (port irrelevant - SSH -L), or the same
          origin as that host when Host is *.ts.net (origin_ok).
          A browser always attaches Origin to a cross-origin POST. curl/agents send no Origin, so this has no effect on them."""
        # --no-origin-check: an escape hatch for when the observed path differs from expectations
        if not self.app.C.origin_check:
            return
        host = self.headers.get("Host")
        # Checked independent of whether the Tailscale-User-* header is present. That header can also be
        # carried on a same-origin GET from a rebinding page with no preflight, so exempting it via that header would bypass the defense entirely (observed).
        if host is not None and not self.app.host_ok(host):
            raise HTTPError(403, "허용되지 않은 Host 입니다: %s" % self.app.hdr_text(host)[:100], reason="bad_host")
        origin = self.headers.get("Origin")
        if origin is not None and not self.app.origin_ok(origin, host):
            raise HTTPError(
                403, "다른 출처의 요청은 받지 않습니다: %s" % self.app.hdr_text(origin)[:100], reason="bad_origin"
            )

    def _guard(self) -> Json:
        """Every request: read the body, check Host/Origin, identify (401), admit (403). Leaves the principal on
        self.principal and returns its actor (what pins record)."""
        self._read_raw()
        self._check_origin()
        peer = self.client_address[0] if isinstance(self.client_address, tuple) and self.client_address else ""
        p = self.app.identify(self.headers, peer)
        self.app.admit(p, self.headers.get("Host"), self.headers)
        self.principal = p
        return p.actor

    def _record(self, actor: Json) -> None:
        """people.json for a person who opened the viewer or wrote something (agents never). The local owner is recorded as owner."""
        self.app.record_person(actor, role="owner" if self.principal.via == "local-owner" else None)

    def _me(self, actor: Json) -> Json:
        """The actor as the viewer shows "me": plus the principal's role."""
        return dict(actor, role=self.principal.role)

    def _wants_page(self) -> bool:
        """A browser opening the viewer itself (GET / for HTML) - it gets a readable page on a refusal, not JSON."""
        return (
            self.command == "GET"
            and urlparse(self.path).path == "/"
            and "text/html" in (self.headers.get("Accept") or "")
        )

    def _refuse(self, e: HTTPError) -> None:
        """Send a refusal: the readable HTML page to a browser opening /, the JSON error body to everyone else."""
        if self._wants_page():
            lang = page_lang(self.headers, parse_qs(urlparse(self.path).query))
            return self._send(
                e.code, error_page_html(e, lang, self.app.viewer().messages).encode("utf-8"), "text/html; charset=utf-8"
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
        path, q = u.path, parse_qs(u.query)
        # A document-scoped path takes ?doc=<key> (the first document if absent) and is handled for that document (§Multiple documents).
        return self._get_doc(actor, path, q, self._request_doc(accepted(parse.parse_doc_choice(q))))

    def _request_doc(self, choice: parse.DocChoice) -> Document:
        """The document a request names (parsed by parse.parse_doc_choice), found by the server: the first document, or
        the one holding the file hint, when neither ?doc= nor the body names one. A new pin's own doc in the body then
        wins over ?doc= when it names another (as it always has). 404 unknown_doc for a key this instance does not
        serve (answers.found_doc)."""
        app = self.app
        D = answers.found_doc(app.request_doc(choice.key, choice.file_hint), app.hdr_text)
        if choice.body_key is not None and choice.body_key != D.key:
            D = answers.found_doc(app.request_doc(choice.body_key), app.hdr_text)
        return D

    def _get_doc(self, actor: Json, path: str, q: Query, D: Document) -> None:
        """GET routes that act on the request's document D (?doc=, found in _get), tried group by group in the order
        the routes have always been matched (a /pages/ name with no image falls through to the rest): the viewer
        shell, the document's history and build, the pins, the source, the files. Sends the one response the matching
        route answers, or 404 not_found when none matches; refusals propagate to _run as HTTPError."""
        reply = (
            self._get_viewer(actor, path, q, D)
            or self._get_document(path, q, D)
            or self._get_pins(path, q, D)
            or self._get_source(path, q, D)
            or self._get_files(path, q, D)
        )
        if reply is None:
            raise HTTPError(404, "없는 경로입니다: %s" % path, reason="not_found")
        self._send(*reply)

    def _get_viewer(self, actor: Json, path: str, q: Query, D: Document) -> Reply | None:
        """The viewer shell: the page, its @-tag people, icons, version, meta (with the browser's notifications) and
        service worker. None for any other path."""
        app = self.app
        if path == "/":
            # the tailnet person who opened this viewer (@-tag candidate) - local/agent is never recorded
            self._record(actor)
            return Reply(200, app.viewer().page.encode(), "text/html; charset=utf-8")
        if path == "/api/people":  # @-tag autocomplete candidates (no write), each with its people.json role
            return _json_reply({"people": app.people_payload(), "me": self._me(actor)})
        if path == "/favicon.ico":
            return Reply(204, b"", "image/x-icon")
        if path in ("/favicon-32.png", "/apple-touch-icon.png"):  # PNG fallbacks of the SVG favicon, drawn by limn.mark
            size, rounded = (32, True) if path == "/favicon-32.png" else (180, False)
            return Reply(200, mark_png(size, app.C.accent, rounded), "image/png", "public, max-age=86400")
        if path == "/api/version":  # the installed Limn version - no write
            return _json_reply({"name": app.APP_NAME, "version": app.app_version()})
        if path == "/api/meta":
            light = parse.parse_flag(q, "light")
            if not light:
                self._record(actor)
            out = app.meta(D, actor, light=light)
            out["me"] = self._me(actor)  # + role (additive)
            # browser notifications - no write. ?ev= is parsed only now: a bad cursor is refused after meta, as always
            out.update(app.events_since(actor, accepted(parse.parse_events_query(q))))
            return _json_reply(out)
        if path == "/sw.js":  # the service worker for browser notifications (app data is never cached)
            return Reply(200, app.viewer().service_worker.encode(), "text/javascript; charset=utf-8", "no-cache")
        return None

    def _get_document(self, path: str, q: Query, D: Document) -> Reply | None:
        """Document D's history and build: its recent commits, a commit's changes (revision routes), its outline labels
        and its build state. None for any other path."""
        app = self.app
        if path == "/api/revisions":
            return _json_reply(app.revision_history(D))
        if path in ("/api/revision-diff", "/api/revision-build", "/api/revision-pdf"):
            return self._get_revision(path, D, q)
        if path == "/api/outline-labels":
            return _json_reply(app.outline_labels(D))
        if path == "/api/build":
            return _json_reply(answers.diet_log(app.build_state_snapshot(D), parse.parse_flag(q, "log")))
        return None

    def _get_revision(self, path: str, D: Document, q: Query) -> Reply:
        """The three read routes of a commit's changes for document D (api.md §변경 보기와 비교 PDF). An optional &pin=
        scopes them to one pin (§핀 단위 변경 보기); the pin is parsed before the commit is checked, and every refusal
        is answered through answers.revision_answer (HTTPError to _run)."""
        app = self.app
        commit, pin = accepted(parse.parse_revision_query(q))
        if path == "/api/revision-diff":
            return _json_reply(answers.revision_answer(app.revision_diff(D, commit, pin)))
        if path == "/api/revision-build":
            return _json_reply(answers.revision_answer(app.revision_status(D, commit, pin)))
        return Reply(
            200,
            answers.revision_pdf_answer(app.revision_pdf(D, commit, pin)),
            "application/pdf",
            "private, max-age=600",
        )

    def _get_pins(self, path: str, q: Query, D: Document) -> Reply | None:
        """The pins: pins.md (the remote agent's entry point), the list (all documents, or D's with ?doc=), the
        documents, the Trash and one pin. None for any other path."""
        app = self.app
        # a remote agent's entry point, the same sync path as GET /api/pins (docs/handbook/api.md §원격 에이전트 진입점)
        if path == "/pins.md":
            app.maybe_purge_trash()
            base = app.remote_base_for(self.headers.get("Host") or "")
            text = app.pins_md_text(app.snapshot_pins(), base=base)
            return Reply(200, text.encode("utf-8"), "text/markdown; charset=utf-8")
        if path == "/api/pins":
            app.maybe_purge_trash()  # hourly Trash expiry on a long-running server (this path already writes)
            pins = parse.parse_pins_query(q)
            rows = app.pins_payload(app.snapshot_pins(), pins.all)
            if pins.doc_scoped:  # only that document's pins (overlap/estimation stay computed globally)
                rows = [r for r in rows if r["doc"] == D.key]
            return _json_reply(rows)
        if path == "/api/docs":
            return _json_reply(app.docs_payload())
        if path == "/api/pins/dropped":
            return _json_reply({"dropped": app.dropped_payload()})
        m = re.fullmatch(r"/api/pins/(\d+)", path)
        if m:  # one pin (including its thread) - for when an agent needs to read a long thread in full
            return _json_reply(answers.pin_answer(app.pin_payload(int(m.group(1)))))
        return None

    def _get_source(self, path: str, q: Query, D: Document) -> Reply | None:
        """A range of D's manuscript: its snippet (with the range ladder on ?levels=1) and the pins overlapping it.
        None for any other path."""
        app = self.app
        if path == "/api/snippet":
            rng = accepted(parse.parse_snippet(q, app.document_facts(D)))
            return _json_reply(app.snippet_api(rng, parse.parse_flag(q, "levels")))
        if path == "/api/overlaps":
            return _json_reply(app.overlaps_api(accepted(parse.parse_source_range(q, app.document_facts(D)))))
        return None

    def _get_files(self, path: str, q: Query, D: Document) -> Reply | None:
        """Files: D's page images (a name with no image falls through), the bundled PDF.js (404 for any other name) and
        the PDF of a build (404 through answers.build_pdf_gone). None for any other path."""
        app = self.app
        if path.startswith("/pages/"):
            name = os.path.basename(path)
            if PAGE_FILE_RE.fullmatch(name):
                data = _read(app.cur_pages(D) / name)
                if data is not None:
                    return Reply(200, data, "image/png")
        if path.startswith("/vendor/pdfjs/"):
            # The viewer's vector renderer (PDF.js). Accepts only a single name component - a subpath, '..', or an encoded character gets a 404.
            vf = app.vendor_file(path[len("/vendor/pdfjs/") :])
            data = None if vf is None else _read(vf)
            if vf is not None and data is not None:
                # Since the filename carries no version, the viewer appends ?v=<PDFJS_VERSION> to bust the cache.
                return Reply(200, data, VENDOR_MIME[vf.suffix], "public, max-age=86400")
            raise HTTPError(404, "없는 vendor 파일입니다: %s" % app.hdr_text(path)[:100], reason="not_found")
        if path == "/pdf":
            # The PDF matching the page images' build (for vector rendering). It never falls back to a different
            # build (the viewer falls back to PNG and re-reads /api/meta instead).
            name = parse.parse_build_name(q)
            pf = app.build_pdf(D, name)
            data = None if pf is None else _read(pf)
            if data is None:
                answers.build_pdf_gone(name, app.cur_pages(D).name, app.hdr_text)
            return Reply(200, data, "application/pdf", "private, max-age=600")
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
        try:
            d = json.loads(raw)
        except (ValueError, RecursionError):
            raise HTTPError(400, "본문이 올바른 JSON 이 아닙니다.", reason="bad_json") from None
        if not isinstance(d, dict):
            raise HTTPError(400, "본문은 JSON 객체여야 합니다.", reason="bad_json")
        return d

    def _post(self) -> None:
        """A POST: the guard, the role check (before any state change), the person record, the body, then the route -
        for the request's document when the route acts on one."""
        actor = self._guard()
        u = urlparse(self.path)
        path = u.path
        self.app.check_role(self.principal, path)  # the one place roles are enforced, before any state change
        self._record(actor)
        d = self._body()
        if path in ("/api/pick", "/api/pin", "/api/rebuild", "/api/revision-build"):
            q = parse_qs(u.query)
            D = self._request_doc(accepted(parse.parse_doc_choice(q, d, new_pin=path == "/api/pin")))
            return self._post_doc(actor, path, q, d, D)
        return self._post_other(actor, path, d)

    def _post_other(self, actor: Json, path: str, d: Json) -> None:
        """POST routes that act on no one document: pin changes (_pin_action) and clear; anything else is 404. d is the
        parsed JSON body; refusals propagate to _run."""
        m = re.fullmatch(r"/api/pins/(\d+)/(close|reopen|drop|restore|purge|edit|claim|unclaim|reply|confirm)", path)
        if m:
            return self._pin_action(actor, int(m.group(1)), m.group(2), d)
        if path == "/api/clear":  # owner only (check_role), and only with the confirmation phrase
            accepted(parse.parse_clear(d))
            return self._json(answers.clear_answer(self.app.clear_pins(actor)))
        raise HTTPError(404, "없는 경로입니다: %s" % path, reason="not_found")

    def _post_doc(self, actor: Json, path: str, q: Query, d: Json, D: Document) -> None:
        """POST routes that act on the request's document D: pick, new pins, the revision build and rebuilds. d is the
        parsed JSON body and q the query; each route parses its fields in the order the server has always checked
        them; refusals propagate to _run."""
        app = self.app
        if path == "/api/pick":
            selection = parse.parse_pick(d, app.document_facts(D))
            if isinstance(selection, parse.PickBuildGone):
                return self._json(answers.pick_build_gone())
            return self._json(answers.pick_answer(app.pick(D, accepted(selection))))
        if path == "/api/pin":
            request = accepted(parse.parse_add(d, app.assignee_people(d), app.document_facts(D)))
            return self._json(answers.add_answer(app.add_pin(D, request, actor)))
        if path == "/api/revision-build":
            commit, pin = accepted(parse.parse_revision_build(d))
            return self._json(*answers.revision_start_answer(app.revision_start(D, commit, pin)))
        # /api/rebuild (the only route left; _post sends only these four here)
        rebuild = parse.parse_rebuild_query(q)
        if rebuild.background:
            return self._json(*answers.rebuild_started_answer(app.rebuild_async(D)))
        return self._json(*answers.rebuild_answer(app.rebuild(D), rebuild.full_log))

    def _pin_action(self, actor: Json, pid: int, act: str, d: Json) -> None:
        """POST /api/pins/{pid}/{act}: parse the action's fields (in the order the server has always checked them), call
        its service with the parsed values and answer its outcome. Refusals propagate to _run."""
        app = self.app
        if act == "reply":
            return self._json(lifecycle_http.reply(app, pid, actor, d, self.principal.is_human))
        if act == "confirm":
            return self._json(lifecycle_http.confirm(app, pid, actor))
        if act == "drop":
            return self._json(answers.drop_answer(app.drop_pin(pid, actor)))
        if act == "restore":
            return self._json(answers.restore_answer(app.restore_pin(pid, actor), app.public))
        if act == "purge":  # owner only (check_role)
            return self._json(answers.purge_answer(app.purge_pin(pid, actor), pid))
        if act == "edit":
            # loc is checked against the pin's own document, found before the edit is decided (as always)
            body = accepted(parse.parse_edit(d, app.assignee_people(d)))
            region, pdoc = app.edit_scope(pid)
            place = accepted(parse.parse_edit_place(body, region, app.document_facts(pdoc)))
            return self._json(
                answers.edit_answer(app.edit_pin(pid, replace(body.request, place=place), actor, region), app.public)
            )
        if act == "claim":
            ttl, eta = accepted(parse.parse_claim_body(d))
            return self._json(answers.claim_answer(app.claim_pin(pid, actor, ttl, eta), ttl, eta, app.public))
        if act == "unclaim":
            return self._json(answers.unclaim_answer(app.unclaim_pin(pid, actor), app.public))
        if act == "close":
            return self._json(lifecycle_http.close(app, pid, actor, d, self.principal.review_on_close))
        return self._json(lifecycle_http.reopen(app, pid, actor, d))
