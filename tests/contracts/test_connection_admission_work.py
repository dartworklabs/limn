"""Fatal bounded main preserves only existing atomic pin and prepublication build guarantees."""

import json
import os
import select
import socket
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest

from limn import server as composition
from limn.pins.model import parse_pin
from limn.pins.record import Broken
from limn.runtime.startup import StartupRefused
from limn.web.tests.fatal_process_support import assert_retired_port

from helpers import TEX, blank_png, minimal_pdf, req


def child_environment():
    """Import actual checkout code and the fixture module without modifying installed/global configuration."""
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root / "tests" / "support")))
    return environment


def read_observation(child, phase, log):
    """Preserve raw child stdout while waiting on explicit observations with a supervisor deadline."""
    deadline = time.monotonic() + 10
    assert child.stdout is not None
    while time.monotonic() < deadline:
        assert select.select([child.stdout], [], [], max(0, deadline - time.monotonic()))[0], (
            "Child observation deadline expired",
            phase,
            child.poll(),
        )
        line = child.stdout.readline()
        assert line, ("Child exited before observation", phase, child.poll())
        with log.open("ab") as saved:
            saved.write(line)
        if line.startswith(b"OBS "):
            value = json.loads(line[4:])
            assert value["phase"] == phase, value
            return value
    raise AssertionError("Child did not publish " + phase)


def retire_fixture(child):
    """Reap every directly owned fixture process, terminating only if natural retirement failed."""
    if child.poll() is None:
        child.terminate()
        try:
            return child.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            return child.communicate(timeout=2)
    else:
        return child.communicate(timeout=2)


@contextmanager
def build_input_subprocess(directory):
    """The supervisor owns a real input-gated subprocess and releases/reaps it separately from the product child."""
    child = subprocess.Popen(
        [sys.executable, "-u", "-m", "connection_work_child", "gate"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env=child_environment(),
    )
    try:
        address = read_observation(child, "gate-ready", directory / "gate-stdout.log")["address"]
        yield child, address
    finally:
        try:
            if child.poll() is None:
                output, errors = child.communicate(b"release\n", timeout=5)
                assert child.returncode == 0, (output, errors)
                assert b'"phase": "gate-retired"' in output, (output, errors)
        finally:
            output, errors = retire_fixture(child)
            with (directory / "gate-stdout.log").open("ab") as saved:
                saved.write(output)
            (directory / "gate-stderr.log").write_bytes(errors)


@pytest.fixture
def published_manuscript(tmp_path):
    """Make complete old published PDF/page bytes and real source so interrupted work has a durable oracle."""
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    (manuscript / "main.tex").write_text(TEX, encoding="utf-8")
    state = tmp_path / "state"
    pages = state / "pages-20000101000000"
    pages.mkdir(parents=True)
    (pages / "main.pdf").write_bytes(minimal_pdf("old publication"))
    (pages / "page-1.png").write_bytes(blank_png(1250, 1600))
    (state / "pages.cur").write_text(pages.name, encoding="utf-8")
    (state / "pins.jsonl").write_bytes(b"")
    return tmp_path


def interrupted_main(directory, scenario, gate=None):
    """POST real work, cause actual second native-start uncertainty, and require natural nonzero main retirement."""
    child = subprocess.Popen(
        [sys.executable, "-u", "-m", "connection_work_child", "serve", str(directory), scenario, json.dumps(gate)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env=child_environment(),
    )
    try:
        address = tuple(read_observation(child, "ready", directory / "server-stdout.log")["address"])
        before = (directory / "state" / "pins.md").read_bytes()
        with socket.create_connection(address, timeout=2) as work:
            if scenario.startswith("pin-"):
                body = json.dumps(
                    {"file": str(directory / "manuscript" / "main.tex"), "lo": 4, "hi": 5, "note": "interrupted pin"}
                ).encode()
                work.sendall(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
            else:
                work.sendall(req("POST", "/api/rebuild?force=1", b"{}", {"Content-Type": "application/json"}))
            held = read_observation(child, "work-held", directory / "server-stdout.log")
            with socket.create_connection(address, timeout=2) as uncertain:
                uncertain.settimeout(2)
                with suppress(ConnectionResetError):
                    assert uncertain.recv(1) == b""
            stopped = read_observation(child, "stopped", directory / "server-stdout.log")
            output, errors = child.communicate(timeout=10)
        assert child.returncode > 0, (output, errors)
        assert stopped["original_retained"] and stopped["main_thread"], stopped
        assert stopped["runtime_stopped"] and stopped["real_watchers"] > 0, stopped
        assert stopped["listener_closed"] and stopped["work_still_held"], stopped
        assert b"bounded connection lifecycle failed: RuntimeError" in errors
        assert_retired_port(address)
        return held, before
    except BaseException as error:
        output, errors = retire_fixture(child)
        raise AssertionError("Child fixture failed: %s\nstdout: %s\nstderr: %s" % (error, output, errors)) from error
    finally:
        output, errors = retire_fixture(child)
        with (directory / "server-stdout.log").open("ab") as saved:
            saved.write(output)
        (directory / "server-stderr.log").write_bytes(errors)


@pytest.mark.parametrize("phase", ["before", "after"])
def test_actual_pin_post_interruption_preserves_complete_jsonl_and_startup_repairs_markdown(
    published_manuscript, phase
):
    """Fatal main permits complete old/new JSONL and stale Markdown; actual startup repairs the committed projection."""
    directory = published_manuscript
    held, old_md = interrupted_main(directory, "pin-" + phase)
    state = directory / "state"
    expected = b"" if phase == "before" else held["replacement"].encode("utf-8")
    assert (state / "pins.jsonl").read_bytes() == expected
    records = [json.loads(line) for line in expected.splitlines()]
    assert all(not isinstance(parse_pin(record), Broken) for record in records)
    assert len(records) == (0 if phase == "before" else 1)
    assert (state / "pins.md").read_bytes() == old_md
    assert not (state / "events.jsonl").exists()
    parsed = composition.build_arg_parser().parse_args(
        [
            "--manuscript",
            str(directory / "manuscript"),
            "--state-dir",
            str(state),
            "--doc",
            "main=Test:main.tex",
            "--no-build",
            "--port",
            "0",
            "--max-connections",
            "2",
        ]
    )
    restarted = composition.start(parsed)
    assert not isinstance(restarted, StartupRefused)
    try:
        assert (state / "pins.jsonl").read_bytes() == expected
        repaired = (state / "pins.md").read_bytes()
        assert (b"interrupted pin" in repaired) == (phase == "after")
        if phase == "after":
            assert repaired != old_md
    finally:
        restarted.server.server_close()
        restarted.runtime.stop()


def test_actual_build_interruption_keeps_old_publication_and_supervisor_reaps_its_input_subprocess(
    published_manuscript,
):
    """A real rebuild held before render preserves publication/source; fixture subprocess cleanup is its supervisor's duty."""
    directory = published_manuscript
    state = directory / "state"
    observed_paths = [
        state / "pages.cur",
        *(state / "pages-20000101000000").iterdir(),
        directory / "manuscript" / "main.tex",
    ]
    before = {path: path.read_bytes() for path in observed_paths}
    with build_input_subprocess(directory) as (gate, address):
        held, _ = interrupted_main(directory, "build", address)
        assert held["before_render_executor"]
        assert held["command"][0] == "latexmk"
        assert read_observation(gate, "gate-active", directory / "gate-stdout.log")["phase"] == "gate-active"
        assert gate.poll() is None, "The fixture subprocess must remain owned until supervisor release"
        assert {path: path.read_bytes() for path in observed_paths} == before
    assert gate.returncode == 0
