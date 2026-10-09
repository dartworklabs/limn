"""Production listener selection preserves live TCP capacity and admitted HTTP security contracts."""

import http.client
import json
import socket
import threading
import time
from contextlib import ExitStack
from dataclasses import replace

import pytest

from limn import server as composition
from limn.pins.location.service import PinLocationService
from limn.runtime.documents import DEFAULT_DOC_KEY, Doc
from limn.runtime.startup import StartupRefused
from limn.web.handler import Server
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
                excess.sendall(req("GET", "/api/pins", headers=ALICE))
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
            excess.sendall(req("GET", "/api/pins", headers=ALICE))
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

    class LegacyStartFault(Server):
        """Exercise the original listener's dispatch-error boundary without replacing threading globals."""

        def process_request(self, request, client_address):
            """Refuse the first worker dispatch before delegating all later sockets to stdlib."""
            if not failed.is_set():
                failed.set()
                raise RuntimeError("owned legacy worker start failure")
            super().process_request(request, client_address)

        def handle_error(self, request, client_address):
            """Suppress only this test-owned expected failure's traceback."""
            assert failed.is_set()

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
