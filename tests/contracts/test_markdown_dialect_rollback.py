"""A state folder with front matter and math pins stays valid for the release before them: v0.4.51, where a rollback
from the release that adds them lands (docs/adr/0032-markdown-front-matter.md D4, D9, Trade-off).

A front matter pin is a Markdown block pin whose kind is the new `md:front`; a display math pin's kind is the new
`md:math`; either may carry a suggested edit (here the math's TeX) and be moved onto such a block after it was made.
v0.4.51 knows neither value: its typed record check (limn.pins.record.parse_record) takes scope and kind as strings, and
its store writes every record back in the order it read it. So it must read every such record of
tests/data/pin_records.jsonl - live ones and a Trash copy - without a broken line and write both files back byte for
byte, and its pins.md range column (limn.pins.listing.render.range_label) must name each by its kind: rolling back loses
no pin and no word an agent reads. (v0.4.51 takes the same Markdown document, so no configuration changes; its viewer
draws the front matter as a rule and paragraphs and the math as text, on the same lines.)

The release's src/limn is taken from git and run by a separate interpreter without site-packages, so this checkout's
limn cannot shadow it. A clone without the tag (shallow) skips; any other git failure fails loudly. CI checks out the
full history, so the release runs there. The same approach for Markdown pins is tests/contracts/test_markdown_rollback.py.

Run: uv run pytest -q tests/contracts/test_markdown_dialect_rollback.py
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
TAG = "v0.4.51"
KINDS = ("md:front", "md:math")
# The page fields no Markdown record carries (limn.pins.pages.PAGE_FIELDS).
PAGE_FIELDS = ("page", "frac", "pdf_build", "frac_build")

# v0.4.51's own store: typed parsing bound to DOC_KEY_RE and is_actor as its server binds them, PinStore(files, lock,
# parse, parse_trashed, sync, render) - one read and one write of pins.jsonl and of the Trash - and its pins.md range
# column for every record read.
STORE = r"""
import json, sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from limn.pins import record, store
from limn.pins.listing.render import range_label
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
read = [json.loads(line) for name in ("pins.jsonl", "pins.dropped.jsonl")
        for line in (state / name).read_text(encoding="utf-8").splitlines()]
print(json.dumps({
    "module": store.__file__,
    "bad": bad,
    "dbad": dbad,
    "ids": [r.core.id for r in rows],
    "dropped_ids": [r.pin.core.id for r in dropped],
    "ranges": [range_label(r) for r in read],
}))
"""


def dialect_lines() -> list[str]:
    """The corpus lines of front matter and math pins (kind md:front or md:math), exactly as stored."""
    return [line for line in CORPUS.read_text(encoding="utf-8").splitlines() if json.loads(line).get("kind") in KINDS]


def live_lines() -> list[str]:
    """The lines of live pins (no dropped_at)."""
    return [line for line in dialect_lines() if '"dropped_at": ' not in line]


def dropped_lines() -> list[str]:
    """The lines of Trash copies (with dropped_at)."""
    return [line for line in dialect_lines() if '"dropped_at": ' in line]


class TheCorpus(unittest.TestCase):
    """The front matter and math records this version writes, as the corpus holds them (the dialect contract flow's
    pins.jsonl and Trash)."""

    def test_the_corpus_holds_both_kinds_and_no_page_field(self):
        """A line pin re-placed onto the front matter block after it was made, the front matter block with its quote, a
        suggested edit of the display math and the math block's Trash copy - each a block pin of a .md file; none of them
        carries a page field."""
        records = [json.loads(line) for line in dialect_lines()]
        front = [r for r in records if r["kind"] == "md:front"]
        math = [r for r in records if r["kind"] == "md:math"]
        self.assertTrue(any("edited_at" in r and "quote" not in r for r in front))
        self.assertTrue(any("quote" in r for r in front))
        self.assertTrue(any("suggest" in r and "dropped_at" not in r for r in math))
        self.assertTrue(any("dropped_at" in r for r in math))
        for r in records:
            self.assertEqual(r["scope"], "block", r["id"])
            self.assertTrue(r["file"].endswith(".md"), r["id"])
            for key in PAGE_FIELDS:
                self.assertNotIn(key, r, r["id"])


class RollbackToV0451(unittest.TestCase):
    """v0.4.51's store and pins.md range column on a pins.jsonl and a Trash holding only the corpus's front matter and
    math records."""

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

    def test_reads_every_record_writes_both_files_back_byte_for_byte_and_lists_each_kind(self):
        """No line is broken for the release's record check, every pin and Trash copy is read, its rewrite of pins.jsonl
        and pins.dropped.jsonl is the exact original bytes, and its range column is each record's md:front or md:math."""
        live, dropped = live_lines(), dropped_lines()
        self.assertGreaterEqual(len(live), 3)
        self.assertGreaterEqual(len(dropped), 1)
        original = "".join(line + "\n" for line in live).encode("utf-8")
        original_dropped = "".join(line + "\n" for line in dropped).encode("utf-8")
        (self.state / "pins.jsonl").write_bytes(original)
        (self.state / "pins.dropped.jsonl").write_bytes(original_dropped)
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
        self.assertEqual((self.state / "pins.jsonl").read_bytes(), original)
        self.assertEqual((self.state / "pins.dropped.jsonl").read_bytes(), original_dropped)
        self.assertEqual(got["ranges"], [json.loads(line)["kind"] for line in live + dropped])
