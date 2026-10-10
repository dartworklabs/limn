"""A real two-worker child proves entry fencing before a blocked fatal coordinator can stop state."""

import json
import sys
import threading
from pathlib import Path
from socketserver import BaseRequestHandler

from limn.web.connection_policy import admitted
from limn.web.connections import BoundedServer, FatalConnectionStart


def cleanup_race_child(directory: Path) -> None:
    """Hold failing cleanup coordination while the accepting MainThread releases a second pending worker."""
    directory.mkdir(parents=True, exist_ok=True)
    pending_entered = threading.Event()
    permit_pending = threading.Event()
    pending_done = threading.Event()
    coordinator_entered = threading.Event()
    permit_coordinator = threading.Event()
    original = SystemExit(0)
    observed = {}
    forbidden = directory / "pending-handler"

    class MarkerHandler(BaseRequestHandler):
        """Use a real file to expose any forbidden post-fatal handler construction."""

        def handle(self):
            """Only the second worker's handler is forbidden while initial claimed work may complete."""
            if len(listener.accepted) == 2 and self.request is listener.accepted[1]:
                forbidden.write_text("entered", encoding="utf-8")

    class CleanupRaceListener(BoundedServer):
        """Keep native workers and real accepted descriptors behind owned lifecycle permissions."""

        def __init__(self):
            """Own two leases, their native workers and a never-reused pending token."""
            self.workers = []
            self.accepted = []
            self.pending_token = None
            super().__init__(("127.0.0.1", 0), MarkerHandler, max_connections=2)

        def get_request(self):
            """Retain actual accepted sockets to distinguish parent and worker physical cleanup."""
            request, address = super().get_request()
            self.accepted.append(request)
            return request, address

        def _make_worker(self, request, client_address, token):
            """Identify the second pending worker without looking at thread launch acknowledgement fields."""
            if self.workers:
                self.pending_token = token
            worker = super()._make_worker(request, client_address, token)
            self.workers.append(worker)
            return worker

        def _run_connection(self, request, client_address, token):
            """Withhold the second worker's claim until cleanup coordination is observably blocked."""
            if token != self.pending_token:
                super()._run_connection(request, client_address, token)
                return
            pending_entered.set()
            try:
                assert permit_pending.wait(5), "Pending entry permission was not released"
                super()._run_connection(request, client_address, token)
            finally:
                pending_done.set()

        def _cleanup_connection(self, request):
            """Keep the first real FD unclosed and fail only after a second worker is pending."""
            if request is self.accepted[0]:
                assert pending_entered.wait(5), "Second pending worker did not enter"
                raise original
            super()._cleanup_connection(request)

        def _record_fatal(self, error):
            """Block worker coordination before stop; main coordination fails zero to test primary protection."""
            if threading.current_thread() is threading.main_thread():
                raise SystemExit(0)
            coordinator_entered.set()
            assert permit_coordinator.wait(5), "Cleanup coordinator was not released"
            raise SystemExit(0)

        def service_actions(self):
            """Release pending entry while pure stop is still absent and the failing coordinator stays blocked."""
            if len(self.workers) == 2:
                assert coordinator_entered.wait(5), "Fatal coordinator did not reach its barrier"
                observed["pure_state_stopped_before_poll"] = self._admission.stopped
                observed["coordinator_blocked"] = not permit_coordinator.is_set()
                permit_pending.set()
                assert pending_done.wait(5), "Second pending worker failed to finish"
            super().service_actions()

    listener = CleanupRaceListener()
    print(json.dumps({"address": listener.server_address[:2]}), flush=True)
    assert sys.stdin.readline() == "start\n"
    try:
        listener.serve_forever(poll_interval=0.02)
    except FatalConnectionStart as error:
        observed["original_retained"] = error.original is original and error.__cause__ is original
        raise
    finally:
        observed["main_thread"] = threading.current_thread() is threading.main_thread()
        observed["held_before_cleanup"] = admitted(listener._admission)
        observed["listener_closed"] = listener.socket.fileno() == -1
        observed["failing_connection_closed"] = listener.accepted[0].fileno() == -1
        observed["pending_connection_closed"] = listener.accepted[1].fileno() == -1
        observed["pending_handler_entered"] = forbidden.exists()
        permit_pending.set()
        permit_coordinator.set()
        for worker in listener.workers:
            worker.join(1)
            assert not worker.is_alive(), "Test-owned worker failed to retire"
        observed["held_after_cleanup"] = admitted(listener._admission)
        print(json.dumps(observed), flush=True)


if __name__ == "__main__":
    cleanup_race_child(Path(sys.argv[1]))
