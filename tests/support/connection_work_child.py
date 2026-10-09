"""Run actual Limn main with owned pin/build barriers and a native second-worker startup failure."""

import json
import socket
import sys
import threading
from contextlib import ExitStack, suppress
from pathlib import Path
from unittest import mock

from limn import server as composition
from limn.builds import engine
from limn.pins import store
from limn.runtime.resources import RuntimeResources
from limn.web.connections import BoundedServer, FatalConnectionStart


def observation(phase, **values):
    """Publish only explicit fixture observations amid the real startup summary."""
    print("OBS " + json.dumps({"phase": phase, **values}), flush=True)


def input_gate():
    """Own one actual subprocess/input barrier; its supervisor releases and reaps it separately from Limn."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(10)
        observation("gate-ready", address=listener.getsockname())
        client, _ = listener.accept()
        with client:
            client.settimeout(10)
            assert client.recv(32) == b"build\n", "Build runner did not enter the input gate"
            observation("gate-active")
            assert sys.stdin.readline() == "release\n", "Supervisor did not release its subprocess"
            with suppress(BrokenPipeError, ConnectionResetError):
                client.sendall(b"go")
        observation("gate-retired")


def serve_interrupted_work(directory, scenario, gate_address):
    """Exercise real parsing/startup/main, pin POST or rebuild POST, then retire naturally on uncertain native start."""
    original = RuntimeError("owned actual-start uncertainty during work")
    hold_work = threading.Event()
    pending_entered = threading.Event()
    hold_pending = threading.Event()
    render_entered = threading.Event()
    observed = {}
    listeners = []
    real_atomic_write = store.atomic_write
    real_runner = engine.run_logged
    real_render = engine.draw_pages
    real_stop = RuntimeResources.stop

    def pin_write(path, text):
        """Hold immediately before or after the actual JSONL replacement, leaving Markdown outside the barrier."""
        if path == directory / "state" / "pins.jsonl":
            if scenario == "pin-after":
                real_atomic_write(path, text)
            observation("work-held", replacement=text)
            hold_work.wait()
        else:
            real_atomic_write(path, text)

    def build_runner(command, cwd, timeout):
        """Hold the actual compile workflow on a supervisor-owned subprocess before TeX or render execution."""
        with socket.create_connection(gate_address, timeout=5) as client:
            client.settimeout(None)
            client.sendall(b"build\n")
            observation("work-held", command=command, cwd=str(cwd), before_render_executor=not render_entered.is_set())
            assert client.recv(2) == b"go", "Build input gate closed unexpectedly"
            hold_work.set()
        return real_runner(command, cwd, timeout)

    def observe_render(*args, **kwargs):
        """Observe actual entry to the owned rendering adapter before it creates an executor."""
        render_entered.set()
        return real_render(*args, **kwargs)

    class WorkListener(BoundedServer):
        """Keep full production HTTP dispatch and fail only the invoked second native start."""

        def __init__(self, address, handler, *, max_connections):
            """Bind an isolated ephemeral port without changing the CLI/settings or socket globals."""
            self.dispatches = 0
            self.uncertain_worker = None
            super().__init__((address[0], 0), handler, max_connections=max_connections)
            listeners.append(self)
            observation("ready", address=self.server_address[:2])

        def _start_worker(self, worker):
            """The second native Thread.start succeeds before the owned adapter raises its original error."""
            self.dispatches += 1
            if self.dispatches == 2:
                self.uncertain_worker = worker
                super()._start_worker(worker)
                assert pending_entered.wait(5), "Actual second native worker did not enter"
                raise original
            super()._start_worker(worker)

        def _run_connection(self, request, client_address, token):
            """Hold the uncertain native worker before claim while the first handler remains in real work."""
            if threading.current_thread() is self.uncertain_worker:
                pending_entered.set()
                hold_pending.wait()
            super()._run_connection(request, client_address, token)

        def serve_forever(self, poll_interval=0.02):
            """Retain the actual fatal identity before composition-root cleanup."""
            try:
                super().serve_forever(poll_interval)
            except FatalConnectionStart as error:
                observed["original_retained"] = error.original is original and error.__cause__ is original
                raise

    def stop_runtime(self, timeout=5.0):
        """Observe the real watcher stop after listener retirement; blocked daemon work is allowed to be interrupted."""
        real_stop(self, timeout)
        listener = listeners[0]
        observation(
            "stopped",
            **observed,
            main_thread=threading.current_thread() is threading.main_thread(),
            runtime_stopped=self.stopping.is_set() and not any(thread.is_alive() for thread in self.threads),
            real_watchers=len(self.threads),
            listener_closed=listener.socket.fileno() == -1,
            work_still_held=not hold_work.is_set(),
        )

    with ExitStack() as seams:
        seams.enter_context(mock.patch.object(composition, "BoundedServer", WorkListener))
        seams.enter_context(mock.patch.object(RuntimeResources, "stop", stop_runtime))
        if scenario.startswith("pin-"):
            seams.enter_context(mock.patch.object(store, "atomic_write", pin_write))
        else:
            seams.enter_context(mock.patch.object(engine, "run_logged", build_runner))
            seams.enter_context(mock.patch.object(engine, "draw_pages", observe_render))
        sys.argv = [
            "limn",
            "--manuscript",
            str(directory / "manuscript"),
            "--state-dir",
            str(directory / "state"),
            "--doc",
            "main=Test:main.tex",
            "--no-build",
            "--port",
            "0",
            "--max-connections",
            "2",
        ]
        composition.main()


if __name__ == "__main__":
    if sys.argv[1] == "gate":
        input_gate()
    else:
        address = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
        serve_interrupted_work(Path(sys.argv[2]), sys.argv[3], address)
