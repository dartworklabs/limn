"""A state folder with Markdown pins stays valid for the release before them: v0.4.46, where a rollback from the
release that adds Markdown documents lands (docs/adr/0025-html-document-surface.md D2, 결과).

A Markdown pin is a line pin without page, frac and pdf_build, whose scope may be `block` or `section` and whose kind
may be `md:<block>` or `md:section`; it may carry a suggested edit. v0.4.46 knows none of these values: its typed
record check (limn.pins.record.parse_record) checks a line pin's page only when it is there and takes scope and kind
as strings, and its store writes every record back in the order it read it. So it must read every Markdown record of
tests/data/pin_records.jsonl - live ones and a Trash copy - without a broken line and write both files back byte for
byte: rolling back loses no Markdown pin. (The release does not start with a Markdown document in its configuration,
so a rollback first takes the document out; its pins then stand in pins.md's section of documents not configured.)

The release's src/limn is taken from git and run by a separate interpreter without site-packages, so this checkout's
limn cannot shadow it. A clone without the tag (shallow) skips; any other git failure fails loudly. CI checks out the
full history, so the release runs there. The same approach for suggested edits is tests/contracts/test_suggest_rollback.py.

Run: uv run pytest -q tests/contracts/test_markdown_rollback.py
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
TAG = "v0.4.46"
# The page fields no Markdown record carries (limn.pins.editing.rules.PAGE_FIELDS).
PAGE_FIELDS = ("page", "frac", "pdf_build", "frac_build")

# v0.4.46's own store: typed parsing bound to DOC_KEY_RE and is_actor as its server binds them, PinStore(files, lock,
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


def markdown_lines() -> list[str]:
    """The corpus lines of Markdown pins (a line pin whose file is a .md file), exactly as stored."""
    out = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        file = json.loads(line).get("file")
        if isinstance(file, str) and file.endswith(".md"):
            out.append(line)
    return out


def live_lines() -> list[str]:
    """The Markdown lines of live pins (no dropped_at)."""
    return [line for line in markdown_lines() if '"dropped_at": ' not in line]


def dropped_lines() -> list[str]:
    """The Markdown lines of Trash copies (with dropped_at)."""
    return [line for line in markdown_lines() if '"dropped_at": ' in line]


class TheCorpus(unittest.TestCase):
    """The Markdown records this version writes, as the corpus holds them."""

    def test_the_corpus_holds_the_markdown_shapes_and_no_page_field(self):
        """A line pin re-placed after it was made, a block with an md: kind, a section, a suggested edit and a Trash
        copy; none of them carries a page field."""
        records = [json.loads(line) for line in markdown_lines()]
        self.assertTrue(any("edited_at" in r and r.get("kind") == "lines" for r in records))
        self.assertTrue(any(r.get("scope") == "block" and str(r.get("kind")).startswith("md:") for r in records))
        self.assertTrue(any(r.get("scope") == "section" and r.get("kind") == "md:section" for r in records))
        self.assertTrue(any("suggest" in r for r in records))
        self.assertTrue(dropped_lines())
        for r in records:
            for key in PAGE_FIELDS:
                self.assertNotIn(key, r, r["id"])


class RollbackToV0446(unittest.TestCase):
    """v0.4.46's store on a pins.jsonl and a Trash holding only the corpus's Markdown records."""

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

    def test_reads_every_markdown_record_and_writes_both_files_back_byte_for_byte(self):
        """No line is broken for the release's record check, every pin and Trash copy is read, and its rewrite of
        pins.jsonl and pins.dropped.jsonl is the exact original bytes."""
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
