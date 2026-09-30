"""A state folder with figure pins stays valid for the releases before them: v0.3.5, v0.3.7 (the last release before
P1a's figure documents) and v0.3.8 (the currently deployed release - where a rollback from 0.4.0 lands).

Figure pins add the `el` field and the values via "map", scope el..el8/fig and kind el:<part>/figure. Every one of
these releases must read every such record without a broken line and write it back byte for byte, so rolling back to
any of them loses nothing (docs/superpowers/plans/2026-09-30-figure-documents.md §Global Constraints).

The releases check records in two ways. v0.3.5's valid_rec is an untyped shape predicate (server.valid_rec)
that types kind, via, scope and el only as opaque strings/objects and passes every field it does not know; its
PinStore takes that predicate directly (files, lock, valid, sync, render, refusal). v0.3.7 and v0.3.8 already have
typed parsing (limn.pins.record.parse_record/parse_trashed, the same module this version extends with the `el` check) and a
PinStore built from those two callables (files, lock, parse, parse_trashed, sync, render) bound to
limn.runtime.documents.DOC_KEY_RE and limn.security.people.is_actor, same as server.parse_record does now. Both keep every field
this version does not know and write it back unchanged.

This test runs each release's own store on the figure records of tests/data/pin_records.jsonl: the live figure
lines through read_pins/write_pins, and the one Trash-shaped figure copy (`dropped_at`) through
read_dropped/write_dropped, so the Trash path is exercised too. Each release's src/limn is taken from git and run
by a separate interpreter without site-packages, so this checkout's limn cannot shadow it. A clone missing a tag
(shallow) skips that release only - checked by `git rev-parse -q --verify`, so any other git failure (a corrupt
archive, for instance) fails loudly instead of being mistaken for a missing tag. CI checks out full history, so
every release runs.

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

# v0.3.5: an untyped shape predicate over raw dict rows (server.valid_rec), PinStore(files, lock, valid, sync,
# render, refusal). Both pins.jsonl and pins.dropped.jsonl are read through the same predicate.
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
dropped, dbad = pins.read_dropped()
pins.write_dropped(dropped, dbad)
print(json.dumps({
    "module": server.__file__,
    "bad": bad,
    "dbad": dbad,
    "ids": [r["id"] for r in rows],
    "dropped_ids": [r["id"] for r in dropped],
}))
"""

# v0.3.7 and v0.3.8 (the same flat layout): typed parsing (limn.pins.record.parse_record/parse_trashed) bound to DOC_KEY_RE and is_actor, the same
# way server.parse_record binds them; PinStore(files, lock, parse, parse_trashed, sync, render).
NEW_STORE = r"""
import json, sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from limn import documents, people, store
from limn.pins import record
state = Path(sys.argv[2])


def parse(r):
    return record.parse_record(r, documents.DOC_KEY_RE.fullmatch, people.is_actor)


def parse_trashed(r):
    return record.parse_trashed(r, documents.DOC_KEY_RE.fullmatch, people.is_actor)


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
    "dropped_ids": [d.pin.core.id for d in dropped],
}))
"""


def tag_exists(tag: str) -> bool:
    """Is `tag` reachable in this clone's history (git rev-parse -q --verify refs/tags/<tag>)? The only case this
    test skips for - any other git failure (a corrupt archive, for instance) must fail loudly instead."""
    r = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "refs/tags/%s" % tag],
        cwd=ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    return r.returncode == 0


def extract_release(tag: str, dest: Path) -> Path:
    """The src/ folder of release `tag`, extracted under dest from `git archive` of its src/limn. Callers check
    tag_exists first; this raises (does not swallow) any failure of its own, since a tag known to exist that still
    fails to archive is not a shallow-clone skip."""
    r = subprocess.run(
        ["git", "archive", "--format=tar", tag, "src/limn"], cwd=ROOT, capture_output=True, timeout=60, check=True
    )
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:  # a Python without the extraction filters; the archive is this repository's own tree
            tar.extractall(dest)
    return dest / "src"


def figure_lines() -> list[str]:
    """The corpus lines of figure pins (every record carrying `el`), exactly as stored."""
    return [line for line in CORPUS.read_text(encoding="utf-8").splitlines() if '"el": ' in line]


def live_lines() -> list[str]:
    """The corpus's figure lines that are live pins (not a Trash copy) - what a release's pins.jsonl holds."""
    return [line for line in figure_lines() if '"dropped_at"' not in line]


def dropped_lines() -> list[str]:
    """The corpus's Trash-shaped figure copies (`dropped_at` present) - what a release's pins.dropped.jsonl holds."""
    return [line for line in figure_lines() if '"dropped_at"' in line]


class _RollbackChecks:
    """Shared body for one release's own PinStore on a state folder seeded with only the corpus's figure records.
    Concrete subclasses set TAG (the release) and SCRIPT (OLD_STORE or NEW_STORE) and also inherit
    unittest.TestCase, so this mixin alone is never collected as a test."""

    TAG: str
    SCRIPT: str

    def setUp(self) -> None:
        """Extract the release and make an empty state folder; skip only when the tag is missing."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        if not tag_exists(self.TAG):
            self.skipTest("%s is not in this clone's history (shallow checkout)" % self.TAG)
        self.old_src = extract_release(self.TAG, Path(self.tmp.name) / "release")
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()

    def run_store(self) -> dict:
        """One run of this release's SCRIPT on self.state; its JSON report."""
        r = subprocess.run(
            [sys.executable, "-S", "-c", self.SCRIPT, str(self.old_src), str(self.state)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_reads_every_figure_record_and_writes_both_files_back_byte_for_byte(self):
        """No line is broken for the release's own record check; every live and Trash pin is read, and the
        release's rewrite of each file is the exact original bytes (read_bytes, not read_text)."""
        live = "".join(line + "\n" for line in live_lines()).encode("utf-8")
        dropped = "".join(line + "\n" for line in dropped_lines()).encode("utf-8")
        (self.state / "pins.jsonl").write_bytes(live)
        (self.state / "pins.dropped.jsonl").write_bytes(dropped)
        got = self.run_store()
        self.assertTrue(got["module"].startswith(str(self.old_src)), got["module"])
        self.assertEqual(got["bad"], [])
        self.assertEqual(got["dbad"], [])
        self.assertEqual(got["ids"], [json.loads(line)["id"] for line in live_lines()])
        self.assertEqual(got["dropped_ids"], [json.loads(line)["id"] for line in dropped_lines()])
        self.assertEqual((self.state / "pins.jsonl").read_bytes(), live)
        self.assertEqual((self.state / "pins.dropped.jsonl").read_bytes(), dropped)


class RollbackToV035(_RollbackChecks, unittest.TestCase):
    """v0.3.5's untyped store (server.valid_rec) on the figure records."""

    TAG = "v0.3.5"
    SCRIPT = OLD_STORE


class RollbackToV037(_RollbackChecks, unittest.TestCase):
    """v0.3.7's typed store (limn.pins.record.parse_record/parse_trashed) on the same figure records - the last
    release before P1a's figure documents."""

    TAG = "v0.3.7"
    SCRIPT = NEW_STORE


class RollbackToV038(_RollbackChecks, unittest.TestCase):
    """v0.3.8's typed store on the same figure records - the currently deployed release, where a rollback from 0.4.0
    lands. It knows figure documents (P1a) but not `el`, and its figure documents do not take line pins; its store
    still keeps every field it does not know."""

    TAG = "v0.3.8"
    SCRIPT = NEW_STORE


class Corpus(unittest.TestCase):
    """The fixture the two rollback checks share, independent of either release."""

    def test_the_corpus_holds_the_figure_shapes(self):
        """Line pins and a region pin with el, the element scopes, and at least one Trash-shaped copy: the shapes
        P1b writes are all present and split correctly between the live and dropped groups."""
        records = [json.loads(line) for line in figure_lines()]
        self.assertGreaterEqual(len(records), 4)
        self.assertTrue(any("file" in r for r in records) and any("pdf" in r for r in records))
        self.assertLessEqual({"el", "el2", "fig"}, {r.get("scope") for r in records})
        self.assertGreaterEqual(len(dropped_lines()), 1)
        self.assertEqual(len(live_lines()) + len(dropped_lines()), len(figure_lines()))


if __name__ == "__main__":
    unittest.main()
