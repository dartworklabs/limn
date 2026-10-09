"""Bounded TCP ownership for opt-in listeners; existing unbounded listeners remain independent."""

import socket
import sys
import threading
from collections.abc import Callable
from socketserver import BaseRequestHandler
from typing import NoReturn

from limn.web.connection_policy import (
    AdmissionState,
    Cancelled,
    Claimed,
    LeaseToken,
    Reserved,
    Stopped,
    claim,
    release,
    reserve,
    stop,
)
from limn.web.handler import Server, Server6

ClientAddress = tuple[str, int] | tuple[str, int, int, int]


class FatalConnectionStart(SystemExit):
    """Uncertain start or cleanup cannot safely resume serving and must escape with nonzero status."""

    def __init__(self, original: BaseException) -> None:
        """Keep the initiating failure independently of later listener-cleanup faults."""
        super().__init__(1)
        self.original = original


class BoundedServer(Server):
    """A listener-local positive cap counts pending starts, handlers and idle keep-alive sockets."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: Callable[..., BaseRequestHandler],
        *,
        max_connections: int,
    ) -> None:
        """Validate capacity before binding; own admission even if stdlib startup closes a partial listener."""
        self._admission_lock = threading.Lock()
        self._admission = AdmissionState(max_connections, object())
        self._fatal: BaseException | None = None
        self._fatal_reported = False
        super().__init__(server_address, handler)

    def process_request(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: ClientAddress
    ) -> None:
        """Reserve before worker construction; refuse excess sockets before parsing any HTTP bytes."""
        if not isinstance(request, socket.socket):
            raise TypeError("Bounded HTTP listeners require a TCP socket")
        with self._admission_lock:
            result = reserve(self._admission) if self._fatal is None else Stopped()
            if isinstance(result, Reserved):
                self._admission = result.state
        if not isinstance(result, Reserved):
            try:
                self._cleanup_connection(request)
            except BaseException as original:
                self._fail_start(original)
            return
        token = result.token
        try:
            worker = self._make_worker(request, client_address, token)
        except BaseException as original:
            try:
                self._cleanup_connection(request)
            except BaseException:
                self._fail_start(original)
            with self._admission_lock:
                self._admission = release(self._admission, token)
            self.handle_error(request, client_address)
            return
        try:
            self._start_worker(worker)
        except BaseException as original:
            self._fail_start(original)

    def _make_worker(
        self, request: socket.socket, client_address: ClientAddress, token: LeaseToken
    ) -> threading.Thread:
        """Construct one real daemon worker without invoking its uncertain start boundary."""
        return threading.Thread(target=self._run_connection, args=(request, client_address, token), daemon=True)

    def _start_worker(self, worker: threading.Thread) -> None:
        """Invoke real Thread.start; any failure from this call leaves possible worker ownership uncertain."""
        worker.start()

    def _run_connection(self, request: socket.socket, client_address: ClientAddress, token: LeaseToken) -> None:
        """Claim before handler construction and retain the lease through all physical-cleanup paths."""
        try:
            with self._admission_lock:
                result = claim(self._admission, token) if self._fatal is None else Cancelled()
                if isinstance(result, Claimed):
                    self._admission = result.state
            if not isinstance(result, Claimed):
                return
            try:
                self.finish_request(request, client_address)
            except Exception:
                self.handle_error(request, client_address)
        finally:
            try:
                self._cleanup_connection(request)
            except BaseException as cleanup_error:
                try:
                    self._fence_fatal(cleanup_error)
                finally:
                    if self._fatal is None:
                        self._fatal = cleanup_error
                    self._record_fatal(self._fatal)
            else:
                with self._admission_lock:
                    self._admission = release(self._admission, token)

    def _cleanup_connection(self, request: socket.socket) -> None:
        """Try stdlib shutdown and real close fallback; succeed only when the actual socket attests closed."""
        original: BaseException | None = None
        try:
            self.shutdown_request(request)
        except BaseException as error:
            original = error
        if request.fileno() != -1:
            try:
                request.close()
            except BaseException as error:
                if original is None:
                    original = error
        if request.fileno() != -1:
            if original is not None:
                raise original
            raise OSError("Connection socket cleanup did not attest physical closure")

    def _fence_fatal(self, original: BaseException) -> BaseException:
        """Publish the first cause under the same lock that gates reservation and worker entry."""
        with self._admission_lock:
            if self._fatal is None:
                self._fatal = original
            return self._fatal

    def _record_fatal(self, original: BaseException) -> None:
        """Stop new entry atomically and publish the first failure without releasing uncertain leases."""
        with self._admission_lock:
            self._admission = stop(self._admission)
            if self._fatal is None:
                self._fatal = original

    def _fail_start(self, original: BaseException) -> NoReturn:
        """Fence entry even if coordination fails; all secondary effects preserve the nonzero initiating cause."""
        initiating = original
        try:
            try:
                initiating = self._fence_fatal(original)
            finally:
                # Even failed fuse coordination cannot leave the accepting shell without a fatal cause.
                if self._fatal is None:
                    self._fatal = original
                initiating = self._fatal
                try:
                    self._record_fatal(initiating)
                finally:
                    try:
                        self.server_close()
                    finally:
                        if self.socket.fileno() != -1:
                            self.socket.close()
        finally:
            try:
                if not self._fatal_reported:
                    self._fatal_reported = True
                    self._report_fatal(initiating)
            except BaseException:
                pass
            raise FatalConnectionStart(initiating) from initiating

    def _report_fatal(self, original: BaseException) -> None:
        """Report a safe cause type on stderr because SystemExit itself suppresses uncaught tracebacks."""
        detail = type(original).__name__
        if isinstance(original, SystemExit) and isinstance(original.code, int):
            detail += " (code %d)" % original.code
        print("error: bounded connection lifecycle failed: %s" % detail, file=sys.stderr)

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        """Preserve fatal escape when stdlib's parent socket cleanup replaces the dispatch exception."""
        try:
            super().serve_forever(poll_interval)
        finally:
            if self._fatal is not None:
                self._fail_start(self._fatal)

    def service_actions(self) -> None:
        """Escape the accepting loop on worker-published fatal cleanup without calling self-deadlocking shutdown."""
        original = self._fatal
        if original is not None:
            self._fail_start(original)

    def server_close(self) -> None:
        """Fence future admission before stdlib listener closure; repeated or partial-start cleanup is safe."""
        with self._admission_lock:
            self._admission = stop(self._admission)
        super().server_close()


class BoundedServer6(BoundedServer, Server6):
    """The same bounded ownership on the existing IPv6 listener's binding and backlog policy."""
