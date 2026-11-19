"""Production listener selection preserves live TCP capacity and admitted HTTP security contracts."""

import http.client
import json
import socket
import sys
import threading
import time
from contextlib import ExitStack
from dataclasses import replace

import pytest

from limn import server as composition
from limn.pins.location.service import PinLocationService
from limn.runtime.documents import DEFAULT_DOC_KEY, Doc
from limn.runtime.startup import StartupRefused
from limn.web import handler as web_handler
from limn.web.app import RouteRegistry
from limn.web.handler import Server
from limn.web.reply import json_reply
from limn.web.routes import RouteBundle
from limn.web.tests.connection_support import assert_transport_closed, running_listener, skip_unavailable_ipv6_bind

from helpers import TEX, VIEWER_FILES, req, run_config
from helpers_access import ALICE, BOB, member_add, token_create, token_revoke


@pytest.fixture
def http_app(tmp_path):
    """Assemble an isolated real manuscript and pin store with one admitted connection by default."""
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    main = manuscript / "main.tex"
    main.write_text(TEX, encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    config = run_config(manuscript, main, state, port=0, max_connections=1, agent_loopback=False)
    runtime = composition.new_runtime(composition.serve_viewer(VIEWER_FILES, "Test", "#000000", None))
    app = composition.assemble_application(config, runtime)
    app.environment.docs.append(Doc(DEFAULT_DOC_KEY, "Test", legacy=True, paths=config.paths))
    app.pins.startup.initialize_sequence()
    app.pins.commands.refresh_pins_md()
    yield app
    runtime.stop()


def response(client, raw):
    """Close the response stream on every outcome while retaining the real keep-alive socket."""
    if raw:
        client.sendall(raw)
    with http.client.HTTPResponse(client) as result:
        result.begin()
        body = result.read()
        assert len(body) == int(result.getheader("Content-Length"))
        headers = dict((name.lower(), value) for name, value in result.getheaders())
        return result.status, headers, json.loads(body)


def pin_bytes(app):
    """Observe the real pin files, including absence, independently from in-memory request outcomes."""
    config = app.environment.C
    return {
        path.name: path.read_bytes() if path.exists() else None
        for path in (config.pins_jsonl, config.pins_md, config.seq)
    }


def state_bytes(app):
    """Snapshot all persistent files so malformed admitted requests cannot hide identity or notice writes."""
    state = app.environment.C.state
    return {path.relative_to(state): path.read_bytes() for path in state.rglob("*") if path.is_file()}


def recovered_request(address):
    """Wait on observable HTTP recovery after peer closure; the deadline is only test supervision."""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with socket.create_connection(address, timeout=1) as client:
            try:
                return response(client, req("GET", "/api/pins", headers={**ALICE, "Connection": "close"}))
            except (ConnectionResetError, http.client.RemoteDisconnected):
                pass
    raise AssertionError("Released connection capacity did not admit a legitimate HTTP request")


def require_ipv6_loopback(bind):
    """Skip only an actual unavailable IPv6 bind; production startup refusals still fail the HTTP contract."""
    if bind == "::1":
        try:
            with socket.socket(socket.AF_INET6) as probe:
                probe.bind((bind, 0))
        except OSError as error:
            skip_unavailable_ipv6_bind(error, socket.AF_INET6)


@pytest.mark.parametrize("bind", ["127.0.0.1", "::1"])
def test_production_listener_saturates_and_recovers_with_idle_keepalive(http_app, bind):
    """listen selects bounded IPv4/IPv6 transport; idle reuse keeps its lease until actual socket closure."""
    require_ipv6_loopback(bind)
    http_app.environment.C = replace(http_app.environment.C, access=replace(http_app.environment.C.access, bind=bind))
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run:
        address = listener.server_address[:2]
        with socket.create_connection(address, timeout=2) as held:
            assert response(held, req("GET", "/api/pins", headers=ALICE))[0] == 200
            with socket.create_connection(address, timeout=2) as excess:
                assert_transport_closed(excess)
            assert response(held, req("GET", "/api/pins", headers=BOB))[0] == 200
        assert recovered_request(address)[0] == 200
    assert not run.errors


def test_two_production_listeners_have_independent_capacity(http_app):
    """Saturating one full application listener leaves a second listener's admission usable."""
    with ExitStack() as owned:
        first = composition.listen(http_app.web)
        assert not isinstance(first, StartupRefused)
        one = owned.enter_context(running_listener(first))
        second = composition.listen(http_app.web)
        assert not isinstance(second, StartupRefused)
        two = owned.enter_context(running_listener(second))
        held = owned.enter_context(socket.create_connection(first.server_address[:2], timeout=2))
        assert response(held, req("GET", "/api/pins", headers=ALICE))[0] == 200
        with socket.create_connection(first.server_address[:2], timeout=2) as excess:
            assert_transport_closed(excess)
        with socket.create_connection(second.server_address[:2], timeout=2) as other:
            assert response(other, req("GET", "/api/pins", headers=BOB))[0] == 200
    assert not one.errors and not two.errors


@pytest.mark.parametrize("bind", ["127.0.0.1", "::1"])
def test_omitted_cap_admits_more_than_the_opt_in_limit(http_app, bind):
    """The exact legacy listener path keeps three legitimate idle sockets when the optional test cap is one."""
    require_ipv6_loopback(bind)
    http_app.environment.C = replace(
        http_app.environment.C, max_connections=None, access=replace(http_app.environment.C.access, bind=bind)
    )
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run, ExitStack() as clients:
        sockets = [
            clients.enter_context(socket.create_connection(listener.server_address[:2], timeout=2)) for _ in range(3)
        ]
        for client in sockets:
            assert response(client, req("GET", "/api/pins", headers=ALICE))[0] == 200
    assert not run.errors


def test_default_legacy_dispatch_failure_still_continues_serving(http_app, monkeypatch):
    """An owned legacy dispatch fault remains stdlib-recoverable and a later real TCP request succeeds."""
    failed = threading.Event()
    expected_error = RuntimeError("owned legacy worker start failure")

    class LegacyStartFault(Server):
        """Exercise the original listener's dispatch-error boundary without replacing threading globals."""

        def process_request(self, request, client_address):
            """Refuse the first worker dispatch before delegating all later sockets to stdlib."""
            if not failed.is_set():
                failed.set()
                raise expected_error
            super().process_request(request, client_address)

        def handle_error(self, request, client_address):
            """Suppress the exact owned dispatch fault and preserve inherited diagnostics for other errors."""
            if sys.exc_info()[1] is not expected_error:
                super().handle_error(request, client_address)

    monkeypatch.setattr(composition, "Server", LegacyStartFault)
    http_app.environment.C = replace(http_app.environment.C, max_connections=None)
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run:
        with socket.create_connection(listener.server_address[:2], timeout=2) as first:
            assert_transport_closed(first)
        assert failed.is_set()
        assert recovered_request(listener.server_address[:2])[0] == 200
    assert not run.errors


def test_keepalive_rechecks_viewer_role_and_closes_a_fully_framed_refusal(http_app):
    """A proxy's reused editor socket gives a viewer no write authority, and the refused body cannot become a request."""
    state = http_app.environment.C.state
    member_add(state, ALICE["Tailscale-User-Login"], "editor")
    member_add(state, BOB["Tailscale-User-Login"], "viewer")
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run, socket.create_connection(listener.server_address[:2], timeout=2) as client:
        assert response(client, req("GET", "/api/pins", headers=ALICE))[0] == 200
        before = pin_bytes(http_app)
        payload = json.dumps({"file": str(http_app.environment.C.main), "lo": 4, "hi": 5}).encode()
        status, headers, body = response(
            client, req("POST", "/api/pin", payload, {**BOB, "Content-Type": "application/json"})
        )
        assert (status, body) == (
            403,
            {
                "error": "보기 권한(viewer)만 있는 계정입니다 — 핀·답글·닫기 같은 변경은 할 수 없습니다.",
                "reason": "viewer_only",
            },
        )
        assert headers["connection"] == "close"
        assert_transport_closed(client)
        assert pin_bytes(http_app) == before
    assert not run.errors


@pytest.mark.parametrize(
    ("case", "status", "reason"),
    [
        ("missing", 401, "loopback_agent_off"),
        ("bad", 401, "bad_bearer"),
        ("bearer-duplicate", 401, "bad_bearer"),
        ("revoked", 401, "bad_token"),
        ("json", 400, "bad_json"),
        ("json-malformed", 400, "bad_json"),
        ("query", 400, "bad_query"),
        ("query-malformed", 400, "bad_query"),
        ("header", 400, "duplicate_header"),
        ("length", 400, "bad_content_length"),
        ("truncated", 400, "body_truncated"),
        ("oversized", 413, "body_too_large"),
        ("host", 403, "bad_host"),
        ("origin", 403, "bad_origin"),
    ],
)
def test_admitted_tcp_preserves_request_refusals_without_pin_writes(http_app, case, status, reason):
    """Admission does not weaken existing authentication, ambiguity, framing, size, Host or Origin refusals."""
    headers = {**ALICE, "Connection": "close", "Content-Type": "application/json"}
    method, path, payload = "POST", "/api/pin", b"{}"
    if case == "missing":
        headers = {"Connection": "close", "Content-Type": "application/json"}
    elif case == "bad":
        headers["Authorization"] = "Bearer"
    elif case == "revoked":
        entry, token = token_create(http_app.environment.C.state, "test")
        token_revoke(http_app.environment.C.state, entry["id"])
        headers["Authorization"] = "Bearer " + token
    elif case == "json":
        payload = b'{"note":"a","note":"b"}'
    elif case == "json-malformed":
        payload = b"{"
    elif case == "query":
        path += "?doc=a&doc=b"
    elif case == "query-malformed":
        path += "?doc=%ff"
    elif case == "host":
        headers["Host"] = "evil.example"
    elif case == "origin":
        headers["Origin"] = "https://evil.example"
    raw = req(method, path, payload, headers)
    if case == "header":
        raw = raw.replace(b"Host:", b"Host: localhost\r\nHost:", 1)
    elif case == "bearer-duplicate":
        raw = raw.replace(b"Host:", b"Authorization: Bearer one\r\nAuthorization: Bearer two\r\nHost:", 1)
    elif case == "length":
        raw = raw.replace(b"Content-Length: 2", b"Content-Length: 2\r\nContent-Length: 2")
    elif case == "truncated":
        raw = raw.replace(b"Content-Length: 2", b"Content-Length: 3")
    elif case == "oversized":
        raw = raw.replace(b"Content-Length: 2", b"Content-Length: 1048577")
    before = state_bytes(http_app)
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run, socket.create_connection(listener.server_address[:2], timeout=2) as client:
        if case == "truncated":
            client.sendall(raw)
            client.shutdown(socket.SHUT_WR)
            raw = b""
        observed, returned, body = response(client, raw)
        assert (observed, body["reason"]) == (status, reason)
        assert returned["connection"] == "close"
        assert_transport_closed(client)
        assert state_bytes(http_app) == before
    assert not run.errors


@pytest.mark.parametrize("identity,detail", [(ALICE, ": owned lookup failure"), (BOB, "")])
def test_admitted_tcp_internal_error_keeps_role_specific_detail(http_app, monkeypatch, identity, detail):
    """A real admitted HTTP 500 exposes the existing detail only to privileged roles."""
    member_add(http_app.environment.C.state, ALICE["Tailscale-User-Login"], "editor")
    member_add(http_app.environment.C.state, BOB["Tailscale-User-Login"], "viewer")

    def fail_lookup(self, *args, **kwargs):
        """Fail the owned location adapter while retaining real request identity and response framing."""
        raise RuntimeError("owned lookup failure")

    monkeypatch.setattr(PinLocationService, "overlaps", fail_lookup)
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    path = "/api/overlaps?file=%s&lo=1&hi=2" % http_app.environment.C.main
    with running_listener(listener) as run, socket.create_connection(listener.server_address[:2], timeout=2) as client:
        status, _, body = response(client, req("GET", path, headers={**identity, "Connection": "close"}))
        assert (status, body) == (500, {"error": "서버 내부 오류" + detail, "reason": "internal"})
        assert_transport_closed(client)
    assert not run.errors


@pytest.mark.parametrize("host", ["invalid.example", "localhost"])
def test_incomplete_unadmitted_gets_do_not_block_admitted_meta(http_app, monkeypatch, host):
    """Four peers stalled before admission cannot consume the legitimate reader's computation capacity."""
    reading_bodies = threading.Barrier(5)

    class ObservedBodyHandler(composition.Handler):
        """Synchronize real incomplete requests at the body boundary without changing admission or reads."""

        def _read_raw(self):
            """Let the controller observe all stalled bodies before sending its legitimate request."""
            if self.headers.get("Content-Length") == "1":
                reading_bodies.wait(timeout=5)
            return super()._read_raw()

    monkeypatch.setattr(composition, "Handler", ObservedBodyHandler)
    http_app.environment.C = replace(http_app.environment.C, max_connections=None)
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run, ExitStack() as clients:
        stalled = []
        for _ in range(4):
            client = clients.enter_context(socket.create_connection(listener.server_address[:2], timeout=2))
            stalled.append(client)
            client.sendall(
                ("GET /api/meta HTTP/1.1\r\nHost: %s\r\nContent-Length: 1\r\nConnection: close\r\n\r\n" % host).encode()
            )
        reading_bodies.wait(timeout=5)
        try:
            with socket.create_connection(listener.server_address[:2], timeout=2) as admitted:
                admitted.sendall(req("GET", "/api/meta", headers={**ALICE, "Connection": "close"}))
                try:
                    status, _, body = response(admitted, b"")
                except TimeoutError:
                    pytest.fail("Unadmitted incomplete GETs blocked an admitted /api/meta request")
                assert status == 200
                assert "n_open" in body
        finally:
            for client in stalled:
                assert response(client, b"x")[0] in (401, 403)
    assert not run.errors


# A held handler waits this long at most; a client gives up sooner, so a read that waits for a held handler fails
# on the client's deadline and is never let through by the hold running out. Both are test supervision.
HOLD_SECONDS = 30
CLIENT_SECONDS = 10


def answered(client, raw):
    """One response's status and body bytes of any content type, read to its declared length."""
    client.sendall(raw)
    with http.client.HTTPResponse(client) as result:
        result.begin()
        body = result.read()
        assert len(body) == int(result.getheader("Content-Length"))
        return result.status, body


def free_slots():
    """How many GET computation slots are free now: take every free one without waiting, then give them back."""
    taken = 0
    while web_handler.READ_SLOTS.acquire(blocking=False):
        taken += 1
    for _ in range(taken):
        web_handler.READ_SLOTS.release()
    return taken


def free_answers():
    """How many answer slots are free now - GET answers that may still be made and held: take every free one without
    waiting, then give them back."""
    taken = 0
    while web_handler.ANSWER_SLOTS.acquire(blocking=False):
        taken += 1
    for _ in range(taken):
        web_handler.ANSWER_SLOTS.release()
    return taken


# The answers the process holds at most (limn.web.handler.ANSWER_SLOTS), as the Handbook states it.
ANSWERS = 32


def finished(client):
    """Wait until the server has closed a `Connection: close` socket whose response was read. The server closes the
    socket only after the request's handler has returned, so from then on every slot the request held is back -
    where the response's last byte alone can reach the client a moment before the handler releases its answer slot.
    The deadline is test supervision."""
    client.settimeout(CLIENT_SECONDS)
    try:
        rest = client.recv(4096)
    except ConnectionResetError:
        rest = b""
    assert rest == b"", "Bytes after a complete response: %r" % rest


def at_rest():
    """The free computation and answer slots once no handler holds any: wait, within the supervision deadline, for
    handlers that earlier tests of this process left finishing, then return (free_slots(), free_answers())."""
    deadline = time.monotonic() + CLIENT_SECONDS
    free = (free_slots(), free_answers())
    while free != (4, ANSWERS) and time.monotonic() < deadline:
        time.sleep(0.01)
        free = (free_slots(), free_answers())
    return free


@pytest.mark.parametrize(
    "held,status,holding", [("/api/pins", 200, 4), ("/api/version", 200, 4), ("/api/pins/424242", 404, 0)]
)
def test_an_answer_being_sent_holds_no_computation_slot(http_app, monkeypatch, held, status, holding):
    """Four readers whose answers - a listing, one of the viewer's own files, or a route's refusal - are still being
    sent leave every computation slot free: a fifth read is computed and answered while they have taken none of
    their bytes, so a slow client cannot stall the others. Each answer being sent holds one answer slot until its
    last byte has left; a refusal, sent after its route gave everything back, holds none."""
    sending = threading.Barrier(5)
    release = threading.Event()

    class HeldSendHandler(composition.Handler):
        """Hold a finished answer at the send boundary; computation and admission are untouched."""

        def _send(self, code, body, ctype, *rest, **named):
            """Let the controller see four computed answers waiting to be sent before any byte leaves."""
            if self.path == held:
                sending.wait(timeout=HOLD_SECONDS)
                release.wait(timeout=HOLD_SECONDS)
            return super()._send(code, body, ctype, *rest, **named)

    monkeypatch.setattr(composition, "Handler", HeldSendHandler)
    http_app.environment.C = replace(http_app.environment.C, max_connections=None)
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    assert at_rest() == (4, ANSWERS)
    address = listener.server_address[:2]
    with running_listener(listener) as run, ExitStack() as clients:
        slow = []
        for _ in range(4):
            client = clients.enter_context(socket.create_connection(address, timeout=HOLD_SECONDS))
            client.sendall(req("GET", held, headers={**ALICE, "Connection": "close"}))
            slow.append(client)
        try:
            sending.wait(timeout=CLIENT_SECONDS)
            assert (free_slots(), free_answers()) == (4, ANSWERS - holding)
            with socket.create_connection(address, timeout=CLIENT_SECONDS) as other:
                try:
                    answer = response(other, req("GET", "/api/meta", headers={**ALICE, "Connection": "close"}))
                except TimeoutError:
                    pytest.fail("Answers still being sent kept a computed read waiting for a slot")
                assert answer[0] == 200
                assert "n_open" in answer[2]
                finished(other)
        finally:
            release.set()
        for client in slow:
            assert response(client, b"")[0] == status
            finished(client)
        assert (free_slots(), free_answers()) == (4, ANSWERS)
    assert not run.errors


def test_the_answers_held_at_once_are_bounded(http_app, monkeypatch):
    """However many readers stall, the process holds at most ANSWERS answers: with that many being sent no answer
    slot is left, the computation slots are all free, and a further read is answered once one of them has gone."""
    sending = threading.Barrier(ANSWERS + 1)
    release = threading.Event()

    class HeldSendHandler(composition.Handler):
        """Hold the version answer at the send boundary; computation and admission are untouched."""

        def _send(self, code, body, ctype, *rest, **named):
            """Let the controller see every held answer waiting to be sent before any byte leaves."""
            if self.path == "/api/version":
                sending.wait(timeout=HOLD_SECONDS)
                release.wait(timeout=HOLD_SECONDS)
            return super()._send(code, body, ctype, *rest, **named)

    monkeypatch.setattr(composition, "Handler", HeldSendHandler)
    http_app.environment.C = replace(http_app.environment.C, max_connections=None)
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    assert at_rest() == (4, ANSWERS)
    address = listener.server_address[:2]
    with running_listener(listener) as run, ExitStack() as clients:
        slow = []
        for _ in range(ANSWERS):
            client = clients.enter_context(socket.create_connection(address, timeout=HOLD_SECONDS))
            client.sendall(req("GET", "/api/version", headers={**ALICE, "Connection": "close"}))
            slow.append(client)
        waiting = clients.enter_context(socket.create_connection(address, timeout=HOLD_SECONDS))
        try:
            sending.wait(timeout=CLIENT_SECONDS)
            assert (free_slots(), free_answers()) == (4, 0)
            waiting.sendall(req("GET", "/api/meta", headers={**ALICE, "Connection": "close"}))
        finally:
            release.set()
        for client in [*slow, waiting]:
            assert response(client, b"")[0] == 200
            finished(client)
        assert (free_slots(), free_answers()) == (4, ANSWERS)
    assert not run.errors


def test_the_viewers_own_files_answer_while_every_slot_computes(http_app, monkeypatch):
    """With all four slots held by computations and four more reads queued for a slot, the page, its script, its
    workers, its icon, a bundled library file and the version still answer at once - they are read from what the
    run holds and take no computation slot. Only the four computing reads hold an answer slot: a read queued for
    computation holds none. Both kinds of slot come back when the computations end."""
    computing = threading.Barrier(5)
    release = threading.Event()
    arrived = threading.Semaphore(0)
    entered = []
    overlaps = PinLocationService.overlaps

    def held_overlaps(self, *args, **kwargs):
        """Hold the owned location adapter inside its computation until the controller has asked for the files. The
        first four calls meet the controller at the barrier; later ones, let in after the release, pass through."""
        entered.append(1)
        if len(entered) <= 4:
            computing.wait(timeout=HOLD_SECONDS)
        release.wait(timeout=HOLD_SECONDS)
        return overlaps(self, *args, **kwargs)

    class SeenHandler(composition.Handler):
        """Tell the controller when a heavy read has passed every check and is about to ask for its slots."""

        def _request_doc(self, choice):
            """Select the document as always, then report the heavy read's arrival."""
            found = super()._request_doc(choice)
            if self.path.startswith("/api/overlaps"):
                arrived.release()
            return found

    monkeypatch.setattr(composition, "Handler", SeenHandler)
    monkeypatch.setattr(PinLocationService, "overlaps", held_overlaps)
    http_app.environment.C = replace(http_app.environment.C, max_connections=None)
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    assert at_rest() == (4, ANSWERS)
    address = listener.server_address[:2]
    heavy = "/api/overlaps?file=%s&lo=1&hi=2" % http_app.environment.C.main
    own_files = (
        "/",
        "/viewer.js",
        "/sw.js",
        "/md-parse.mjs",
        "/favicon.ico",
        "/vendor/pdfjs/pdf.min.mjs",
        "/vendor/pretendard/pretendard.css",
        "/api/version",
    )
    with running_listener(listener) as run, ExitStack() as clients:
        busy = []
        for _ in range(4):
            client = clients.enter_context(socket.create_connection(address, timeout=HOLD_SECONDS))
            client.sendall(req("GET", heavy, headers={**ALICE, "Connection": "close"}))
            busy.append(client)
        try:
            computing.wait(timeout=CLIENT_SECONDS)
            for _ in range(4):
                client = clients.enter_context(socket.create_connection(address, timeout=HOLD_SECONDS))
                client.sendall(req("GET", heavy, headers={**ALICE, "Connection": "close"}))
                busy.append(client)
            for _ in range(8):
                assert arrived.acquire(timeout=CLIENT_SECONDS), "a heavy read never reached its route"
            assert free_slots() == 0
            for path in own_files:
                with socket.create_connection(address, timeout=CLIENT_SECONDS) as page:
                    try:
                        status, body = answered(page, req("GET", path, headers={**ALICE, "Connection": "close"}))
                    except TimeoutError:
                        pytest.fail("GET %s waited behind four computations" % path)
                    assert (path, status) == (path, 200)
                    assert body
                    finished(page)
            assert (len(entered), free_slots(), free_answers()) == (4, 0, ANSWERS - 4)
        finally:
            release.set()
        for client in busy:
            assert response(client, b"")[0] == 200
            finished(client)
        assert (free_slots(), free_answers()) == (4, ANSWERS)
    assert not run.errors


def test_a_route_that_refuses_or_fails_gives_its_slot_back(http_app, monkeypatch):
    """A read that ends in a refusal, in no route at all or in an unexpected error leaves every computation slot and
    every answer slot free: no failure leaks capacity."""

    def fail_lookup(self, *args, **kwargs):
        """Fail the owned location adapter inside its computation."""
        raise RuntimeError("owned lookup failure")

    monkeypatch.setattr(PinLocationService, "overlaps", fail_lookup)
    http_app.environment.C = replace(http_app.environment.C, max_connections=None)
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    assert at_rest() == (4, ANSWERS)
    address = listener.server_address[:2]
    failing = "/api/overlaps?file=%s&lo=1&hi=2" % http_app.environment.C.main
    with running_listener(listener) as run:
        for path, status in (("/api/pins/424242", 404), (failing, 500), ("/vendor/pdfjs/nosuch.mjs", 404)) * 5:
            with socket.create_connection(address, timeout=CLIENT_SECONDS) as client:
                assert response(client, req("GET", path, headers={**ALICE, "Connection": "close"}))[0] == status
                finished(client)
        assert (free_slots(), free_answers()) == (4, ANSWERS)
    assert not run.errors
    nothing = RouteRegistry(RouteBundle(get=(lambda request: None,), get_packaged=(lambda request: None,)))
    listener = composition.listen(replace(http_app.web, routes=nothing))
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run:
        for _ in range(5):
            with socket.create_connection(listener.server_address[:2], timeout=CLIENT_SECONDS) as client:
                raw = req("GET", "/api/version", headers={**ALICE, "Connection": "close"})
                status, _, body = response(client, raw)
                assert (status, body["reason"]) == (404, "not_found")
                finished(client)
        assert (free_slots(), free_answers()) == (4, ANSWERS)
    assert not run.errors


def test_a_packaged_read_still_names_its_document(http_app):
    """A packaged path answers for the request's document like every read: a key this run does not serve is the
    contract's 404 unknown_doc, not the file."""
    http_app.environment.C = replace(http_app.environment.C, max_connections=None)
    listener = composition.listen(http_app.web)
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run:
        with socket.create_connection(listener.server_address[:2], timeout=CLIENT_SECONDS) as client:
            raw = req("GET", "/api/version?doc=nosuch", headers={**ALICE, "Connection": "close"})
            status, _, body = response(client, raw)
            assert (status, body["reason"]) == (404, "unknown_doc")
        with socket.create_connection(listener.server_address[:2], timeout=CLIENT_SECONDS) as client:
            raw = req("GET", "/api/version", headers={**ALICE, "Connection": "close"})
            assert response(client, raw)[0] == 200
    assert not run.errors


def test_packaged_reads_are_tried_before_computed_ones(http_app):
    """For one path, a packaged read answers ahead of a computed one, and a packaged read that does not serve the
    path lets the computed one answer: the two groups keep one fallthrough order."""

    def packaged(request):
        """Serve the version path only when asked for the packaged answer."""
        return json_reply({"from": "packaged"}) if request.query.get("want") == ["packaged"] else None

    def computed(request):
        """Serve whatever the packaged read declined."""
        return json_reply({"from": "computed"})

    http_app.environment.C = replace(http_app.environment.C, max_connections=None)
    routes = RouteRegistry(RouteBundle(get=(computed,), get_packaged=(packaged,)))
    listener = composition.listen(replace(http_app.web, routes=routes))
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run:
        for query, source in (("?want=packaged", "packaged"), ("", "computed")):
            with socket.create_connection(listener.server_address[:2], timeout=CLIENT_SECONDS) as client:
                raw = req("GET", "/api/version" + query, headers={**ALICE, "Connection": "close"})
                assert response(client, raw)[2] == {"from": source}
    assert not run.errors


def test_no_packaged_read_runs_for_a_path_the_access_table_does_not_declare(http_app):
    """The read-path check comes before every route: a packaged read that would serve any path is never asked about
    a path no declaration admits, and the request is the contract's 404 - and never asked by a caller without an
    identity."""
    asked = []

    def greedy(request):
        """Answer every path, recording that it was reached."""
        asked.append(request.path)
        return json_reply({"served": request.path})

    member_add(http_app.environment.C.state, ALICE["Tailscale-User-Login"], "editor")
    http_app.environment.C = replace(http_app.environment.C, max_connections=None)
    routes = RouteRegistry(RouteBundle(get_packaged=(greedy,)))
    listener = composition.listen(replace(http_app.web, routes=routes))
    assert not isinstance(listener, StartupRefused)
    with running_listener(listener) as run:
        with socket.create_connection(listener.server_address[:2], timeout=CLIENT_SECONDS) as client:
            raw = req("GET", "/undeclared/file.mjs", headers={**ALICE, "Connection": "close"})
            status, _, body = response(client, raw)
            assert (status, body["reason"]) == (404, "not_found")
        with socket.create_connection(listener.server_address[:2], timeout=CLIENT_SECONDS) as client:
            status, _, body = response(client, req("GET", "/api/version", headers={"Connection": "close"}))
            assert status in (401, 403)
        assert asked == []
        with socket.create_connection(listener.server_address[:2], timeout=CLIENT_SECONDS) as client:
            raw = req("GET", "/api/version", headers={**ALICE, "Connection": "close"})
            assert response(client, raw)[2] == {"served": "/api/version"}
        assert asked == ["/api/version"]
    assert not run.errors
