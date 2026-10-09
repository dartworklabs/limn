"""Own real fatal TCP children and bounded supervision without changing process or socket globals."""

import json
import os
import select
import socket
import subprocess
import sys
import threading
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from socketserver import BaseRequestHandler
from unittest import mock

from limn import server as composition
from limn.web.connection_policy import admitted
from limn.web.connections import BoundedServer, FatalConnectionStart


@dataclass(frozen=True)
class ChildResult:
    """A naturally retired child's TCP address, lifecycle observations and actual stderr/status."""

    address: tuple[str, int]
    status: int
    observation: dict
    stderr: str


def run_fatal_child(directory: Path, scenario: str, effect: str = "none", *, main: bool = False) -> ChildResult:
    """Drive a real MainThread accepting loop; timeout cleanup always fails the observation."""
    env = os.environ.copy()
    source = Path(__file__).resolve().parents[3]
    support = source.parent / "tests" / "support"
    env["PYTHONPATH"] = os.pathsep.join((str(source), str(support)))
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "limn.web.tests.cleanup_race_child"
            if scenario == "cleanup-barrier"
            else "limn.web.tests.fatal_process_support",
            str(directory),
            scenario,
            effect,
            str(main),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert child.stdout is not None
        assert select.select([child.stdout], [], [], 5)[0], "Child did not publish its listener"
        startup = child.stdout.readline()
        address = tuple(json.loads(startup)["address"])
        with ExitStack() as sockets:
            sockets.enter_context(socket.create_connection(address, timeout=2))
            if scenario == "cleanup-barrier":
                sockets.enter_context(socket.create_connection(address, timeout=2))
            output, errors = child.communicate("start\n", timeout=10)
        records = [json.loads(line) for line in output.splitlines()]
        assert len(records) == 1, (child.returncode, startup, output, errors)
        return ChildResult(address, child.returncode, records[0], errors)
    except subprocess.TimeoutExpired as error:
        raise AssertionError("Fatal child did not exit naturally within the supervisor safety deadline") from error
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate(timeout=2)


def assert_retired_port(address: tuple[str, int]) -> None:
    """A naturally exited child cannot serve another TCP connection on its retired ephemeral port."""
    try:
        client = socket.create_connection(address, timeout=1)
    except OSError:
        return
    client.close()
    raise AssertionError("Exited child listener still accepts TCP")


def fatal_child(directory: Path, scenario: str, effect: str, use_main: bool) -> None:
    """Run native workers and owned fault seams with deterministic entry/cleanup permissions."""
    directory.mkdir(parents=True, exist_ok=True)
    entered = threading.Event()
    handler_entered = threading.Event()
    permit_entry = threading.Event()
    permit_cleanup = threading.Event()
    cleanup_done = threading.Event()
    marker = directory / "handler-entered"
    original = {
        "ordinary": RuntimeError("owned native startup failure"),
        "interrupt": KeyboardInterrupt(),
        "zero": SystemExit(0),
    }["zero" if scenario in ("zero", "cleanup") else "interrupt" if scenario == "interrupt" else "ordinary"]
    observed = {}

    class MarkerHandler(BaseRequestHandler):
        """Expose actual handler construction through a real file and synchronize claimed ownership."""

        def handle(self):
            """Write the external handler marker before allowing claimed cleanup to block."""
            marker.write_text("entered", encoding="utf-8")
            handler_entered.set()

    class FailingCloseSocket(socket.socket):
        """Retain a real listener FD when its owned native-close seam cannot attest success."""

        def close(self):
            """Model failure before physical close, with the OS descriptor still observable."""
            raise OSError("owned listener fallback failure")

    class FaultListener(BoundedServer):
        """Inject only concrete listener lifecycle faults while preserving real TCP and native start."""

        def __init__(self):
            """Keep actual accepted sockets/workers for observing ownership during teardown."""
            self.accepted = None
            self.worker = None
            self.stream = None
            super().__init__(("127.0.0.1", 0), MarkerHandler, max_connections=1)
            if effect == "fallback":
                sock = self.socket
                self.socket = FailingCloseSocket(sock.family, sock.type, sock.proto, fileno=sock.detach())

        def get_request(self):
            """Retain the real accepted descriptor without changing library-wide socket behavior."""
            self.accepted, address = super().get_request()
            return self.accepted, address

        def _run_connection(self, request, client_address, token):
            """Hold pending work before claim, using an explicit barrier rather than thread metadata."""
            entered.set()
            try:
                if scenario == "pending" or (effect == "coordination" and scenario != "cleanup"):
                    assert permit_entry.wait(5), "Pending entry barrier was not released"
                super()._run_connection(request, client_address, token)
            finally:
                cleanup_done.set()

        def _make_worker(self, request, client_address, token):
            """A pre-start failure with a real makefile ref cannot reclaim a still-open descriptor."""
            if scenario == "construction":
                self.stream = request.makefile("rb")
                raise original
            return super()._make_worker(request, client_address, token)

        def _start_worker(self, worker):
            """Every injected failure occurs inside the invoked native-start seam, even without launch."""
            self.worker = worker
            if scenario != "no-worker":
                super()._start_worker(worker)
                assert entered.wait(5), "Native worker did not enter"
                if scenario in ("claimed", "cleanup"):
                    assert handler_entered.wait(5), "Worker never claimed handler entry"
            if scenario == "cleanup":
                return
            raise original

        def _cleanup_connection(self, request):
            """Withhold possible-worker cleanup independently from the parent's physical socket close."""
            if scenario == "cleanup":
                raise original
            if threading.current_thread() is self.worker:
                assert permit_cleanup.wait(5), "Worker cleanup permission was not released"
            super()._cleanup_connection(request)

        def _record_fatal(self, error):
            """Exercise failure before admission-state coordination without replacing the initiating cause."""
            if effect in ("coordination", "all-coordination-parent"):
                raise SystemExit(0)
            super()._record_fatal(error)

        def _fence_fatal(self, error):
            """Failure of the first fuse coordinator still requires fallback fencing and a nonzero marker."""
            if effect in ("fuse-coordination", "fuse-parent", "all-coordination-parent"):
                raise SystemExit(0)
            return super()._fence_fatal(error)

        def _report_fatal(self, error):
            """A broken owned diagnostic sink cannot convert fatal startup into successful exit."""
            if effect == "diagnostic":
                raise SystemExit(0)
            super()._report_fatal(error)

        def shutdown_request(self, request):
            """Force stdlib's parent BaseException cleanup to raise after physically closing the socket."""
            super().shutdown_request(request)
            if effect in ("parent", "fuse-parent", "all-coordination-parent"):
                raise SystemExit(0)

        def server_close(self):
            """Exercise before/after physical close and composition-root secondary cleanup errors."""
            if effect in ("before", "fallback", "main-warning"):
                raise SystemExit(0)
            super().server_close()
            if effect == "after":
                raise OSError("owned post-close failure")

        def serve_forever(self, poll_interval=0.02):
            """Keep the actual fatal object's identity observable before the composition root unwinds."""
            try:
                super().serve_forever(poll_interval)
            except FatalConnectionStart as error:
                observed["original_retained"] = error.original is original and error.__cause__ is original
                raise

    listener = FaultListener()
    address = listener.server_address[:2]
    print(json.dumps({"address": address}), flush=True)
    assert sys.stdin.readline() == "start\n"

    def observe_cleanup(runtime=None):
        """Record real FD/held ownership, release deterministic gates and retire real registered watchers."""
        observed["main_thread"] = threading.current_thread() is threading.main_thread()
        observed["held_before_cleanup"] = admitted(listener._admission)
        observed["listener_closed"] = listener.socket.fileno() == -1
        observed["parent_closed_connection"] = listener.accepted.fileno() == -1
        observed["handler_before_release"] = marker.exists()
        observed["admission_fenced"] = listener._admission.stopped or listener._fatal is not None
        permit_entry.set()
        permit_cleanup.set()
        if scenario not in ("no-worker", "construction"):
            assert cleanup_done.wait(5), "Native worker cleanup did not complete"
            listener.worker.join(1)
            assert not listener.worker.is_alive(), "Test-owned worker failed to retire"
        observed["held_after_cleanup"] = admitted(listener._admission)
        observed["handler_after_release"] = marker.exists()
        if listener.stream is not None:
            listener.stream.close()
            observed["connection_closed_after_stream"] = listener.accepted.fileno() == -1
        if runtime is not None:
            stop_runtime_real()
            observed["runtime_stopped"] = runtime.stopping.is_set() and not any(t.is_alive() for t in runtime.threads)
        print(json.dumps(observed), flush=True)
        if effect == "runtime-zero":
            raise SystemExit(0)

    if use_main:
        # The owning startup adapter returns a real assembly/runtime/listener; production CLI selection is Task 3.
        from helpers import run_config

        config = run_config(directory, directory / "main.tex", directory / "state", port=0)
        runtime = composition.new_runtime(composition.serve_viewer(composition.read_viewer(), "Test", "#000000", None))
        assembly = composition.assemble_application(config, runtime)
        runtime.start_thread(runtime.stopping.wait)
        started = composition.StartedServer(listener, assembly.web, runtime)
        stop_runtime_real = runtime.stop

        def stop_runtime(self, timeout=5.0):
            """Observe the real runtime stop while allowing its owned failure after successful watcher cleanup."""
            observe_cleanup(runtime)

        def fail_warning(*args, **kwargs):
            """An owned composition-root warning sink models zero-exit failure without changing builtins."""
            raise SystemExit(0)

        with ExitStack() as adapters:
            adapters.enter_context(mock.patch.object(composition, "start", return_value=started))
            adapters.enter_context(mock.patch.object(type(runtime), "stop", stop_runtime))
            if effect == "main-warning":
                adapters.enter_context(mock.patch.object(composition, "print", fail_warning, create=True))
            sys.argv = ["limn", "--manuscript", str(directory)]
            composition.main()
    else:
        try:
            listener.serve_forever()
        finally:
            observe_cleanup()


if __name__ == "__main__":
    fatal_child(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] == "True")
