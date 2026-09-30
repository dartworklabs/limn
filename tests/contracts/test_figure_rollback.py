"""A state folder with figure pins stays valid for the release before them, v0.3.5.

Figure pins add the `el` field and the values via "map", scope el..el8/fig and kind el:<part>/figure. The
previous release must read every such record without a broken line and write it back byte for byte, so rolling
back loses nothing (docs/superpowers/plans/2026-09-30-figure-documents.md §Global Constraints). v0.3.5's valid_rec
types kind, via and scope only as strings and passes the fields it does not know. This test runs that release's
own store on the figure records of tests/data/pin_records.jsonl: the release's src/limn is taken from git and run by
a separate interpreter without site-packages, so this checkout's limn cannot shadow it. A clone without the tag
(shallow) skips; CI checks out full history.

Run: uv run pytest -q tests/contracts/test_figure_rollback.py
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
TAG = "v0.3.5"

# Run by the old release: its store reads pins.jsonl through its own record check, then writes every row back.
OLD_STORE = r"""
import json, sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from limn import server, store
state = Path(sys.argv[2])
pins = store.PinStore(store.PinFiles(state), threading.RLock(), server.valid_rec, lambda rows: False,
                      lambda rows: "", Exception)
rows, bad = pins.read_pins()
pins.write_pins(rows, bad)
print(json.dumps({"module": server.__file__, "bad": bad, "ids": [r["id"] for r in rows]}))
"""


def extract_release(tag: str, dest: Path) -> Path | None:
    """The src/ folder of release `tag`, extracted under dest from `git archive` of its src/limn; None when this clone
    does not have the tag."""
    r = subprocess.run(
        ["git", "archive", "--format=tar", tag, "src/limn"], cwd=ROOT, capture_output=True, timeout=60, check=False
    )
    if r.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:  # a Python without the extraction filters; the archive is this repository's own tree
            tar.extractall(dest)
    return dest / "src"


def figure_lines() -> list[str]:
    """The corpus lines of figure pins (every record carrying `el`), exactly as stored."""
    return [line for line in CORPUS.read_text(encoding="utf-8").splitlines() if '"el": ' in line]


class RollbackToV035(unittest.TestCase):
    """v0.3.5's store on a state folder that holds only figure records."""

    def setUp(self):
        """Extract the release and make an empty state folder; skip without the tag."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_src = extract_release(TAG, Path(self.tmp.name) / "release")
        if self.old_src is None:
            self.skipTest("%s is not in this clone's history (shallow checkout)" % TAG)
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()

    def run_old_store(self) -> dict:
        """One run of OLD_STORE on self.state by the release; its JSON report."""
        r = subprocess.run(
            [sys.executable, "-S", "-c", OLD_STORE, str(self.old_src), str(self.state)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_corpus_holds_the_figure_shapes(self):
        """Line pins and a region pin with el, and the element scopes: the shapes P1b writes are all checked."""
        records = [json.loads(line) for line in figure_lines()]
        self.assertGreaterEqual(len(records), 4)
        self.assertTrue(any("file" in r for r in records) and any("pdf" in r for r in records))
        self.assertLessEqual({"el", "el2", "fig"}, {r.get("scope") for r in records})

    def test_v035_reads_every_figure_record_and_writes_it_back_byte_for_byte(self):
        """No line is broken for the old record check, every pin is read, and the old rewrite is the original bytes."""
        text = "".join(line + "\n" for line in figure_lines())
        (self.state / "pins.jsonl").write_text(text, encoding="utf-8")
        got = self.run_old_store()
        self.assertTrue(got["module"].startswith(str(self.old_src)), got["module"])
        self.assertEqual(got["bad"], [])
        self.assertEqual(got["ids"], [json.loads(line)["id"] for line in figure_lines()])
        self.assertEqual((self.state / "pins.jsonl").read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
