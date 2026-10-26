"""A state folder with verdict pins stays valid for the release before them: v0.4.25, where a rollback from the release
that adds `verdict` lands (docs/superpowers/specs/2026-10-26-verdict-pins.md §호환과 이행).

The verdict is one optional field, `verdict: "<key>"`, on any pin. v0.4.25 does not know it: its typed record check
(limn.pins.record.parse_record) passes a field it does not know, and its store writes every record back in the order
it read it. So it must read every verdict record of tests/data/pin_records.jsonl - live ones and a Trash copy, a
whole figure and a whole PDF page, and hand-edited values that are no verdict - without a broken line and write both
files back byte for byte: rolling back loses no verdict.

The release's src/limn is taken from git and run by a separate interpreter without site-packages, so this checkout's
limn cannot shadow it. A clone without the tag (shallow) skips; any other git failure fails loudly. CI checks out the
full history, so the release runs there. The same approach for suggested edits is tests/contracts/test_suggest_rollback.py.

Run: uv run pytest -q tests/contracts/test_verdict_rollback.py
"""

import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "data" / "pin_records.jsonl"
TAG = "v0.4.25"

# v0.4.25's own store: typed parsing bound to DOC_KEY_RE and is_actor as its server binds them, PinStore(files, lock,
# parse, parse_trashed, sync, render) - one read and one write of pins.jsonl and of the Trash.
STORE = r"""
import json, sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from limn.pins import record, store
from limn.runtime.documents import DOC_KEY_RE
from limn.security.people import is_actor
state = Path(sys.argv[2])


def parse(r):
    return record.parse_record(r, DOC_KEY_RE.fullmatch, is_actor)


def parse_trashed(r):
    return record.parse_trashed(r, DOC_KEY_RE.fullmatch, is_actor)


pins = store.PinStore(store.PinFiles(state), threading.RLock(), parse, parse_trashed, lambda rows: False,
                      lambda rows: "")
rows, bad = pins.read_pins()
pins.write_pins(rows, bad)
dropped, dbad = pins.read_dropped()
pins.write_dropped(dropped, dbad)
print(json.dumps({
    "module": store.__file__,
    "bad": bad,
    "dbad": dbad,
    "ids": [r.core.id for r in rows],
    "dropped_ids": [r.pin.core.id for r in dropped],
}))
"""


def verdict_lines() -> list[str]:
    """The corpus lines of pins that store a verdict field (every record carrying `verdict`), exactly as stored."""
    return [line for line in CORPUS.read_text(encoding="utf-8").splitlines() if '"verdict": ' in line]


def live_lines() -> list[str]:
    """The verdict lines of live pins (no dropped_at)."""
    return [line for line in verdict_lines() if '"dropped_at": ' not in line]


def dropped_lines() -> list[str]:
    """The verdict lines of Trash copies (with dropped_at)."""
    return [line for line in verdict_lines() if '"dropped_at": ' in line]


class RollbackToV0425(unittest.TestCase):
    """v0.4.25's store on a pins.jsonl and a Trash holding only the corpus's verdict records."""

    def setUp(self) -> None:
        """Extract the release's src/limn into a temporary folder and make an empty state folder; skip only when the
        tag is not in this clone."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        found = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "refs/tags/%s" % TAG],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if found.returncode != 0:
            self.skipTest("%s is not in this clone's history (shallow checkout)" % TAG)
        archive = subprocess.run(
            ["git", "archive", "--format=tar", TAG, "src/limn"], cwd=ROOT, capture_output=True, timeout=60, check=True
        )
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(Path(tmp.name) / "release", filter="data")
            else:  # a Python without the extraction filters; the archive is this repository's own tree
                tar.extractall(Path(tmp.name) / "release")
        self.old_src = Path(tmp.name) / "release" / "src"
        self.state = Path(tmp.name) / "state"
        self.state.mkdir()

    def test_reads_every_verdict_record_and_writes_both_files_back_byte_for_byte(self):
        """No line is broken for the release's record check, every pin and Trash copy is read, and its rewrite of
        pins.jsonl and pins.dropped.jsonl is the exact original bytes - verdict included."""
        live, dropped = live_lines(), dropped_lines()
        self.assertGreaterEqual(len(live), 5)
        self.assertGreaterEqual(len(dropped), 1)
        live_bytes = "".join(line + "\n" for line in live).encode("utf-8")
        dropped_bytes = "".join(line + "\n" for line in dropped).encode("utf-8")
        (self.state / "pins.jsonl").write_bytes(live_bytes)
        (self.state / "pins.dropped.jsonl").write_bytes(dropped_bytes)
        r = subprocess.run(
            [sys.executable, "-S", "-c", STORE, str(self.old_src), str(self.state)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(got["module"].startswith(str(self.old_src)), got["module"])
        self.assertEqual((got["bad"], got["dbad"]), ([], []))
        self.assertEqual(got["ids"], [json.loads(line)["id"] for line in live])
        self.assertEqual(got["dropped_ids"], [json.loads(line)["id"] for line in dropped])
        self.assertEqual((self.state / "pins.jsonl").read_bytes(), live_bytes)
        self.assertEqual((self.state / "pins.dropped.jsonl").read_bytes(), dropped_bytes)
