"""Supervise real Poppler or one tracked PDF build for the snapshot regression tests.

Executable wrappers preserve Poppler's arguments and bytes. They pause only at an owned TCP barrier,
so the test can replace its own source while the production build remains in progress.
"""

import dataclasses
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from limn.builds import engine, run
from limn.builds.artifacts import BuildConfig
from limn.runtime.documents import Doc, RunPaths


def barrier() -> None:
    """Tell the supervisor this stage is reached and wait at most ten seconds for its release."""
    with socket.create_connection(("127.0.0.1", int(os.environ["LIMN_SNAPSHOT_PORT"])), timeout=10) as gate:
        gate.sendall(b"ready\n")
        if gate.recv(32) != b"release\n":
            raise RuntimeError("snapshot supervisor did not release Poppler")


def wait_for_first_page() -> None:
    """Keep later pages before their real render until the supervisor replaces the source."""
    release = Path(os.environ["LIMN_SNAPSHOT_RELEASE"])
    deadline = time.monotonic() + 10
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("snapshot supervisor did not release later pages")
        time.sleep(0.01)


def poppler(tool: str) -> int:
    """Run the real executable, with a bounded pause before pdfinfo or after page one's real output."""
    mode = os.environ["LIMN_SNAPSHOT_MODE"]
    page = int(sys.argv[4]) if tool == "pdftoppm" else None
    if tool == "pdfinfo" and mode == "before-info":
        barrier()
    if tool == "pdftoppm" and mode == "during-pages" and page != 1:
        wait_for_first_page()
    result = subprocess.run(
        [os.environ["LIMN_SNAPSHOT_REAL_" + tool.upper()], *sys.argv[1:]],
        capture_output=True,
        timeout=10,
        check=False,
    )
    if tool == "pdftoppm" and page == 1 and mode in ("after-page", "during-pages") and result.returncode == 0:
        barrier()
    sys.stderr.buffer.write(result.stderr)
    sys.stdout.buffer.write(result.stdout)
    return result.returncode


def render() -> int:
    """Run one production tracked build against the supervisor's synthetic manuscript and emit its result."""
    source, state = map(Path, sys.argv[1:])
    doc = Doc("rv", "Review", "pdf", source.parent, source, paths=RunPaths(source.parent, source, state))
    cfg = BuildConfig(state=state, dpi=72, timeout=10)
    result = run.run_tracked(doc, state, lambda: engine.render_pdf_doc(doc, cfg), "2026-10-11T00:00:00Z", repr)
    print(json.dumps({"type": type(result).__name__, "result": dataclasses.asdict(result)}), flush=True)
    return 0


if __name__ == "__main__":
    name = Path(sys.argv[0]).name
    raise SystemExit(poppler(name) if name in ("pdfinfo", "pdftoppm") else render())
