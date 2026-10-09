"""Real loopback listeners and bounded observation deadlines for transport lifecycle tests."""

import errno
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from socketserver import BaseRequestHandler

import pytest

from limn.web.connections import BoundedServer, BoundedServer6


@dataclass
class ListenerRun:
    """One real serving thread's completion and failures, owned by the enclosing test context."""

    server: BoundedServer
    done: threading.Event = field(default_factory=threading.Event)
    errors: list[BaseException] = field(default_factory=list)


@contextmanager
def running_listener(server: BoundedServer) -> Iterator[ListenerRun]:
    """Serve an already-bound test listener; controller shutdown and joins remain bounded on failure."""
    run = ListenerRun(server)

    def serve() -> None:
        """Publish a fatal serving result to the controller instead of leaking a thread exception."""
        try:
            server.serve_forever(poll_interval=0.02)
        except BaseException as error:
            run.errors.append(error)
        finally:
            run.done.set()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield run
    finally:
        # shutdown is called only by this controller, never by the serving thread.
        shutdown = threading.Thread(target=server.shutdown, daemon=True)
        shutdown.start()
        shutdown.join(2)
        server.server_close()
        thread.join(2)
        assert not shutdown.is_alive(), "Listener shutdown exceeded the observation deadline"
        assert not thread.is_alive(), "Serving thread did not retire"
        assert server.socket.fileno() == -1, "Listener socket was not physically closed"


@contextmanager
def open_listener(limit: int, family: int, handler: type[BaseRequestHandler]) -> Iterator[BoundedServer]:
    """Bind IPv4/IPv6 loopback port zero; skip IPv6 only for actual address-family bind errors."""
    listener = BoundedServer6 if family == socket.AF_INET6 else BoundedServer
    address = "::1" if family == socket.AF_INET6 else "127.0.0.1"
    try:
        server = listener((address, 0), handler, max_connections=limit)
    except OSError as error:
        if family == socket.AF_INET6 and error.errno in (
            errno.EAFNOSUPPORT,
            errno.EADDRNOTAVAIL,
            errno.EPROTONOSUPPORT,
        ):
            pytest.skip("IPv6 loopback bind unavailable: errno %s" % error.errno)
        raise
    with running_listener(server) as run:
        yield server
    assert not run.errors, run.errors


def assert_transport_closed(client: socket.socket) -> None:
    """Require EOF/reset within two seconds and reject any HTTP bytes on a refused socket."""
    client.settimeout(2)
    try:
        observed = client.recv(4096)
    except ConnectionResetError:
        observed = b""
    assert observed == b"", "Refused transport emitted bytes: %r" % observed
