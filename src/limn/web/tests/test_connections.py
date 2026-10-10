"""Real TCP admission holds leases through keep-alive and releases only attested physical cleanup."""

import http.client
import socket
import threading
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler

import pytest

from limn.web.connection_policy import admitted
from limn.web.connections import BoundedServer, BoundedServer6, FatalConnectionStart
from limn.web.tests.connection_support import (
    assert_transport_closed,
    open_listener,
    running_listener,
    skip_unavailable_ipv6_bind,
)


class ObservedServer(BoundedServer):
    """Record real sockets and daemon workers so tests attest cleanup and retire owned resources."""

    def __init__(self, *args, **kwargs):
        """Initialize observation before binding; no worker or close implementation is replaced."""
        self.cleanups = threading.Condition()
        self.closed_sockets = []
        self.workers = []
        self.peak = 0
        super().__init__(*args, **kwargs)

    def _make_worker(self, request, client_address, token):
        """Retain the actual native worker for bounded test cleanup, without changing startup."""
        worker = super()._make_worker(request, client_address, token)
        self.workers.append(worker)
        with self._admission_lock:
            self.peak = max(self.peak, admitted(self._admission))
        return worker

    def _run_connection(self, request, client_address, token):
        """Acknowledge physical socket closure only after the owned worker's cleanup/finally returned."""
        try:
            super()._run_connection(request, client_address, token)
        finally:
            with self.cleanups:
                self.closed_sockets.append(request)
                self.cleanups.notify_all()

    def wait_for_cleanup(self, count):
        """Wait boundedly for retired connection ownership and verify every recorded socket is closed."""
        with self.cleanups:
            assert self.cleanups.wait_for(lambda: len(self.closed_sockets) >= count, timeout=2)
            assert all(request.fileno() == -1 for request in self.closed_sockets)
        with self._admission_lock:
            assert admitted(self._admission) == 0

    def retire_workers(self):
        """Join every actual request worker at context teardown; deadlines fail instead of masking leaks."""
        for worker in self.workers:
            worker.join(2)
            assert not worker.is_alive(), "Request worker did not retire"


class ObservedServer6(ObservedServer, BoundedServer6):
    """Observe real IPv6 transport under the same bounded ownership contract."""


@pytest.fixture
def open_bounded_listener(tmp_path):
    """Create a concrete HTTP probe whose events synchronize entry and real transport cleanup."""

    @contextmanager
    def open_bounded(limit=1, family=socket.AF_INET, handler_fault=None, timeout=30):
        """Yield a loopback listener and per-listener probe events, closing all owned workers on exit."""
        entered = threading.Event()
        active = threading.Event()
        permit = threading.Event()
        marker = tmp_path / ("handler-%s.txt" % len(list(tmp_path.iterdir())))
        marker.touch()

        probe_timeout = timeout

        class ProbeHandler(BaseHTTPRequestHandler):
            """Serve framed keep-alive responses while exposing deterministic owned handler barriers."""

            protocol_version = "HTTP/1.1"
            timeout = probe_timeout

            def setup(self):
                """Complete the real stream setup before publishing entry; optionally fail the first holder."""
                super().setup()
                with marker.open("a") as output:
                    output.write("entered\n")
                entered.set()
                if handler_fault == "setup" and not permit.is_set():
                    permit.set()
                    raise RuntimeError("owned setup failure")

            def handle(self):
                """Exercise an ordinary handler fault once while preserving real TCP cleanup."""
                if handler_fault == "handle" and not permit.is_set():
                    permit.set()
                    raise RuntimeError("owned handle failure")
                super().handle()

            def finish(self):
                """Close real streams before exercising an ordinary finish fault on the first holder."""
                super().finish()
                if handler_fault == "finish" and not permit.is_set():
                    permit.set()
                    raise RuntimeError("owned finish failure")

            def do_GET(self):
                """Return two framed bytes, or hold active execution behind an explicit permission event."""
                if self.path == "/blocked":
                    active.set()
                    assert permit.wait(2), "Active handler permission was withheld past the deadline"
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, format, *args):
                """Avoid access-log noise without changing the probe's TCP or HTTP behavior."""

        listener = ObservedServer6 if family == socket.AF_INET6 else ObservedServer
        host = "::1" if family == socket.AF_INET6 else "127.0.0.1"
        try:
            server = listener((host, 0), ProbeHandler, max_connections=limit)
        except OSError as error:
            skip_unavailable_ipv6_bind(error, family)
        try:
            with running_listener(server) as run:
                yield server, entered, active, permit, marker
            assert not run.errors, run.errors
        finally:
            permit.set()
            server.retire_workers()

    return open_bounded


def successful_request(server):
    """Make a real closing HTTP request and require the probe's complete framed success body."""
    with closing(http.client.HTTPConnection(*server.server_address[:2], timeout=2)) as client:
        client.request("GET", "/", headers={"Connection": "close"})
        response = client.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Length") == "2"
        assert response.read() == b"ok"


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_full_listener_refuses_before_headers_and_recovers(open_bounded_listener, family):
    """A partial-header holder refuses another TCP socket without bytes or handler effects, then recovers."""
    with open_bounded_listener(family=family) as (server, entered, _, _, marker):
        with socket.create_connection(server.server_address[:2], timeout=2) as holder:
            holder.sendall(b"GET / HTTP/1.1\r\n")
            assert entered.wait(2)
            before = marker.read_bytes()
            with socket.create_connection(server.server_address[:2], timeout=2) as refused:
                assert_transport_closed(refused)
            assert marker.read_bytes() == before
            with server._admission_lock:
                assert admitted(server._admission) == 1
        server.wait_for_cleanup(1)
        successful_request(server)
        server.wait_for_cleanup(2)
        assert server.peak == 1


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_idle_keep_alive_reuses_one_slot_until_physical_close(open_bounded_listener, family):
    """Two successful requests keep a single idle connection lease and continue refusing new sockets."""
    with open_bounded_listener(family=family) as (server, _, _, _, marker):
        with closing(http.client.HTTPConnection(*server.server_address[:2], timeout=2)) as holder:
            for _ in range(2):
                holder.request("GET", "/")
                response = holder.getresponse()
                assert response.status == 200 and response.read() == b"ok"
                with server._admission_lock:
                    assert admitted(server._admission) == 1
                before = marker.read_bytes()
                with socket.create_connection(server.server_address[:2], timeout=2) as refused:
                    assert_transport_closed(refused)
                assert marker.read_bytes() == before
        server.wait_for_cleanup(1)
        successful_request(server)
        server.wait_for_cleanup(2)


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_active_handler_keeps_its_slot(open_bounded_listener, family):
    """Blocked request execution remains admitted until a real response and connection close complete."""
    with open_bounded_listener(family=family) as (server, _, active, permit, _):
        with closing(http.client.HTTPConnection(*server.server_address[:2], timeout=2)) as holder:
            try:
                holder.request("GET", "/blocked", headers={"Connection": "close"})
                assert active.wait(2)
                with socket.create_connection(server.server_address[:2], timeout=2) as refused:
                    assert_transport_closed(refused)
            finally:
                permit.set()
            assert holder.getresponse().read() == b"ok"
        server.wait_for_cleanup(1)
        successful_request(server)
        server.wait_for_cleanup(2)


def test_two_live_listeners_have_independent_capacity(open_bounded_listener):
    """Saturating one listener leaves another listener's distinct ownership usable."""
    with open_bounded_listener() as (first, entered, _, _, _), open_bounded_listener() as (second, _, _, _, _):
        with socket.create_connection(first.server_address[:2], timeout=2) as holder:
            holder.sendall(b"GET / HTTP/1.1\r\n")
            assert entered.wait(2)
            with socket.create_connection(first.server_address[:2], timeout=2) as refused:
                assert_transport_closed(refused)
            successful_request(second)
            second.wait_for_cleanup(1)
        first.wait_for_cleanup(1)
        successful_request(first)
        first.wait_for_cleanup(2)


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_immediate_eof_retires_the_lease(open_bounded_listener, family):
    """An accepted socket with immediate peer EOF is physically closed before the next lease succeeds."""
    with open_bounded_listener(family=family) as (server, entered, _, _, _):
        with socket.create_connection(server.server_address[:2], timeout=2):
            assert entered.wait(2)
        server.wait_for_cleanup(1)
        successful_request(server)
        server.wait_for_cleanup(2)


def test_existing_idle_timeout_retires_the_lease(open_bounded_listener):
    """A shortened probe timeout observes existing idle cleanup without imposing a new production deadline."""
    with open_bounded_listener(timeout=0.05) as (server, entered, _, _, _):
        with socket.create_connection(server.server_address[:2], timeout=2) as holder:
            holder.sendall(b"GET / HTTP/1.1\r\n")
            assert entered.wait(2)
            assert_transport_closed(holder)
        server.wait_for_cleanup(1)
        successful_request(server)
        server.wait_for_cleanup(2)


@pytest.mark.parametrize("fault", ["setup", "handle", "finish"])
def test_handler_faults_release_only_after_real_cleanup(open_bounded_listener, fault, capsys):
    """Setup/handle/finish faults close real sockets and permit a fresh successful TCP request."""
    with open_bounded_listener(handler_fault=fault) as (server, entered, _, _, _):
        with socket.create_connection(server.server_address[:2], timeout=2):
            assert entered.wait(2)
        server.wait_for_cleanup(1)
        successful_request(server)
        server.wait_for_cleanup(2)
    assert "owned %s failure" % fault in capsys.readouterr().err


def test_support_opens_real_ipv4_and_ipv6_listeners():
    """The shared fixture binds ephemeral loopback sockets and actually closes both listener families."""
    for family in (socket.AF_INET, socket.AF_INET6):
        with open_listener(1, family, BaseHTTPRequestHandler) as server:
            assert server.socket.fileno() >= 0
            assert server.server_address[1] > 0
        assert server.socket.fileno() == -1


class ClosingProbe(BaseHTTPRequestHandler):
    """Provide a real framed closing response for isolated lifecycle-fault listeners."""

    protocol_version = "HTTP/1.1"

    def do_GET(self):
        """Write the complete probe response and force normal stream cleanup afterward."""
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"ok")
        self.close_connection = True

    def log_message(self, format, *args):
        """Suppress probe access logs while retaining all real transport operations."""


class ConstructionFaultServer(ObservedServer):
    """Fail one owned pre-start construction boundary without invoking any native worker."""

    def __init__(self, *args, **kwargs):
        """Retain the failed socket and a cleanup acknowledgement separate from thread startup."""
        self.failed_socket = None
        self.recovered = threading.Event()
        super().__init__(*args, **kwargs)

    def _make_worker(self, request, client_address, token):
        """Fail before Thread.start on the first connection; later calls construct real workers."""
        if self.failed_socket is None:
            self.failed_socket = request
            raise RuntimeError("owned construction failure")
        return super()._make_worker(request, client_address, token)

    def handle_error(self, request, client_address):
        """Keep stdlib error output and acknowledge the completed construction-failure cleanup."""
        super().handle_error(request, client_address)
        self.recovered.set()


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_pre_call_construction_failure_recovers_after_attested_close(family, capsys):
    """Proven pre-start failure closes its actual socket and frees capacity for a legitimate request."""

    class ConstructionFaultServer6(ConstructionFaultServer, BoundedServer6):
        """Apply the same owned construction failure to the actual IPv6 transport."""

    listener = ConstructionFaultServer6 if family == socket.AF_INET6 else ConstructionFaultServer
    host = "::1" if family == socket.AF_INET6 else "127.0.0.1"
    try:
        server = listener((host, 0), ClosingProbe, max_connections=1)
    except OSError as error:
        skip_unavailable_ipv6_bind(error, family)
    try:
        with running_listener(server) as run:
            with socket.create_connection(server.server_address[:2], timeout=2) as failed:
                assert_transport_closed(failed)
            assert server.recovered.wait(2)
            assert server.failed_socket.fileno() == -1
            with server._admission_lock:
                assert admitted(server._admission) == 0 and not server._admission.stopped
            successful_request(server)
            server.wait_for_cleanup(1)
        assert not run.errors
    finally:
        server.retire_workers()
    assert "owned construction failure" in capsys.readouterr().err


@pytest.mark.parametrize("after_close", [False, True])
def test_shutdown_fault_falls_back_to_physical_close_and_recovery(after_close):
    """A pre-close fault uses real fallback; an after-close error cannot prevent proven lease retirement."""

    class ShutdownFaultServer(ObservedServer):
        """Inject a concrete shutdown fault while keeping the actual accepted socket and close fallback."""

        def shutdown_request(self, request):
            """Exercise one side of physical close; inherited adapter fallback must attest the actual FD."""
            if after_close:
                super().shutdown_request(request)
            raise OSError("owned shutdown fault")

    server = ShutdownFaultServer(("127.0.0.1", 0), ClosingProbe, max_connections=1)
    try:
        with running_listener(server) as run:
            successful_request(server)
            server.wait_for_cleanup(1)
            successful_request(server)
            server.wait_for_cleanup(2)
            assert server.peak == 1
        assert not run.errors
    finally:
        server.retire_workers()


def test_unattested_cleanup_retains_ownership_and_escapes_serving():
    """Real shutdown and fallback faults leave the FD open, keep its lease and escape nonzero."""

    class UnclosedSocket(socket.socket):
        """A real OS socket whose owned close seam fails before performing physical closure."""

        def close(self):
            """Keep the real descriptor open to make failed cleanup attestation observable."""
            raise OSError("owned fallback close fault")

    class UnattestedServer(ObservedServer):
        """Inject unconfirmed cleanup on a real accepted descriptor without faking socket globals."""

        def get_request(self):
            """Transfer the actual accepted descriptor to the concrete fault socket, retaining its ownership."""
            request, address = super().get_request()
            owned = UnclosedSocket(request.family, request.type, request.proto, fileno=request.detach())
            return owned, address

        def shutdown_request(self, request):
            """Fail before physical shutdown so the adapter must try its real close fallback."""
            raise OSError("owned primary shutdown fault")

    server = UnattestedServer(("127.0.0.1", 0), ClosingProbe, max_connections=1)
    try:
        with running_listener(server) as run:
            successful_request(server)
            assert run.done.wait(2), "Worker fatal cleanup did not escape the accepting loop"
            assert len(run.errors) == 1
            fatal = run.errors[0]
            assert isinstance(fatal, FatalConnectionStart) and fatal.code == 1
            assert str(fatal.original) == "owned primary shutdown fault"
            with server._admission_lock:
                assert server._admission.stopped
                assert admitted(server._admission) == 1
            with server.cleanups:
                assert server.cleanups.wait_for(lambda: len(server.closed_sockets) == 1, timeout=2)
            assert server.closed_sockets[0].fileno() >= 0
            with socket.socket() as later:
                later.settimeout(2)
                assert later.connect_ex(server.server_address[:2]) != 0
    finally:
        server.retire_workers()
        # Controller cleanup is not product success; the retained lease above is the product oracle.
        for request in server.closed_sockets:
            socket.socket.close(request)
            assert request.fileno() == -1


def test_invoked_start_failure_fences_entry_and_retains_ambiguous_lease():
    """An invoked start seam with no observed worker still fails nonzero and never returns its token."""

    class StartFaultServer(ObservedServer):
        """Exercise a failure within invoked start; absence of native launch is deliberately not inferred."""

        def _start_worker(self, worker):
            """Raise inside the invoked boundary without offering proof that native startup was impossible."""
            raise SystemExit(0)

    server = StartFaultServer(("127.0.0.1", 0), ClosingProbe, max_connections=1)
    with running_listener(server) as run:
        with socket.create_connection(server.server_address[:2], timeout=2) as refused:
            assert_transport_closed(refused)
        assert run.done.wait(2)
        fatal = run.errors[0]
        assert isinstance(fatal, FatalConnectionStart) and fatal.code == 1
        assert isinstance(fatal.original, SystemExit) and fatal.original.code == 0
        assert fatal.__cause__ is fatal.original
        with server._admission_lock:
            assert server._admission.stopped and admitted(server._admission) == 1
        assert server.socket.fileno() == -1


def test_makefile_deferred_close_does_not_attest_a_live_descriptor():
    """Closing a socket with an owned live stream is insufficient proof of physical connection cleanup."""
    server = BoundedServer(("127.0.0.1", 0), ClosingProbe, max_connections=1)
    client, accepted = socket.socketpair()
    stream = accepted.makefile("rb")
    try:
        with pytest.raises(OSError, match="did not attest physical closure"):
            server._cleanup_connection(accepted)
        assert accepted.fileno() >= 0
        stream.close()
        server._cleanup_connection(accepted)
        assert accepted.fileno() == -1
    finally:
        stream.close()
        accepted.close()
        client.close()
        server.server_close()


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_capacity_two_counts_each_live_socket_without_lifetime_tombstones(open_bounded_listener, family):
    """Two holders use exactly two leases; retired generations leave no live collection behind."""
    with open_bounded_listener(limit=2, family=family) as (server, entered, _, _, marker):
        with socket.create_connection(server.server_address[:2], timeout=2) as first:
            first.sendall(b"GET / HTTP/1.1\r\n")
            assert entered.wait(2)
            entered.clear()
            with socket.create_connection(server.server_address[:2], timeout=2) as second:
                second.sendall(b"GET / HTTP/1.1\r\n")
                assert entered.wait(2)
                before = marker.read_bytes()
                with server._admission_lock:
                    assert admitted(server._admission) == 2
                with socket.create_connection(server.server_address[:2], timeout=2) as refused:
                    assert_transport_closed(refused)
                assert marker.read_bytes() == before
        server.wait_for_cleanup(2)
        for retired in range(3, 13):
            successful_request(server)
            server.wait_for_cleanup(retired)
            with server._admission_lock:
                assert server._admission.pending == server._admission.claimed == frozenset()
        assert server.peak == 2
        with server._admission_lock:
            assert server._admission.next_generation == 12


def test_pre_call_unconfirmed_cleanup_is_fatal_and_keeps_the_token():
    """Construction failure cannot recover when a real retained makefile keeps its socket FD alive."""

    class DeferredConstructionServer(ConstructionFaultServer):
        """Exercise pre-call cleanup uncertainty with a real descriptor and an owned stream reference."""

        def get_request(self):
            """Retain a real stream before the owned construction fault, making physical closure defer."""
            request, address = super().get_request()
            self.held_stream = request.makefile("rb")
            return request, address

    server = DeferredConstructionServer(("127.0.0.1", 0), ClosingProbe, max_connections=1)
    try:
        with running_listener(server) as run:
            with socket.create_connection(server.server_address[:2], timeout=2) as failed:
                assert_transport_closed(failed)
            assert run.done.wait(2)
            assert len(run.errors) == 1
            fatal = run.errors[0]
            assert isinstance(fatal, FatalConnectionStart) and fatal.code == 1
            assert str(fatal.original) == "owned construction failure"
            assert server.failed_socket.fileno() >= 0
            assert not server.recovered.is_set()
            with server._admission_lock:
                assert server._admission.stopped and admitted(server._admission) == 1
    finally:
        # Closing this test-owned stream proves the earlier FD was real; it does not reclaim the lease.
        server.held_stream.close()
        assert server.failed_socket.fileno() == -1
        with server._admission_lock:
            assert admitted(server._admission) == 1


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_invalid_listener_capacity_is_rejected_before_socket_binding(invalid):
    """A malformed internal capacity raises ValueError even when the supplied real address is occupied."""
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with pytest.raises((ValueError, OSError)) as outcome:
            BoundedServer(occupied.getsockname(), ClosingProbe, max_connections=invalid)
        assert isinstance(outcome.value, ValueError)
        assert "positive integer" in str(outcome.value)
