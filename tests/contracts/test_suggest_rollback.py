"""A state folder with suggested-edit pins stays valid for the release before them: v0.4.23, where a rollback from the
release that adds `suggest` lands (docs/adr/0020-suggested-edit-pins.md, 결과).

The suggestion is one optional field, `suggest: {base, text}`, on a LaTeX line pin. v0.4.23 does not know it: its
typed record check (limn.pins.record.parse_record) passes a field it does not know, and its store writes every record
back in the order it read it. So it must read every suggestion record of tests/data/pin_records.jsonl without a broken
line and write the file back byte for byte - rolling back loses no suggestion.

The release's src/limn is taken from git and run by a separate interpreter without site-packages, so this checkout's
limn cannot shadow it. A clone without the tag (shallow) skips; any other git failure fails loudly. CI checks out the
full history, so the release runs there. The same approach for figure pins is tests/contracts/test_figure_rollback.py.

Run: uv run pytest -q tests/contracts/test_suggest_rollback.py
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
TAG = "v0.4.23"

# v0.4.23's own store: typed parsing bound to DOC_KEY_RE and is_actor as its server binds them, PinStore(files, lock,
# parse, parse_trashed, sync, render) - one read and one write of pins.jsonl.
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
print(json.dumps({"module": store.__file__, "bad": bad, "ids": [r.core.id for r in rows]}))
"""


def suggestion_lines() -> list[str]:
    """The corpus lines of pins with a suggestion (every record carrying `suggest`), exactly as stored."""
    return [line for line in CORPUS.read_text(encoding="utf-8").splitlines() if '"suggest": ' in line]


class RollbackToV0423(unittest.TestCase):
    """v0.4.23's store on a pins.jsonl holding only the corpus's suggestion records."""

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

    def test_reads_every_suggestion_record_and_writes_it_back_byte_for_byte(self):
        """No line is broken for the release's record check, every pin is read, and its rewrite of pins.jsonl is the
        exact original bytes - suggest included."""
        lines = suggestion_lines()
        self.assertGreaterEqual(len(lines), 2)
        original = "".join(line + "\n" for line in lines).encode("utf-8")
        (self.state / "pins.jsonl").write_bytes(original)
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
        self.assertEqual(got["bad"], [])
        self.assertEqual(got["ids"], [json.loads(line)["id"] for line in lines])
        self.assertEqual((self.state / "pins.jsonl").read_bytes(), original)
