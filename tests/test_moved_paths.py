"""ADR-0006 follow-ups (issue #24): the two paths a moved manuscript still lost.

1. The paths in a closed pin's `changes` (ADR-0005) are absolute. After the checkout moves they are now located on read
   by the same rule as the pin's own file (mapping.pin_rel_path), so pin-scoped [View changes] still uses the lines the
   agent recorded instead of falling back to inference. Nothing is rewritten, nothing outside the tree is read.
2. In a multi-document instance, the tail guess for a moved legacy record is searched in the pin's own document folder
   (its build root), so a same-named file of another document is never picked; a renamed document folder is followed.

No stored field is added or changes meaning: this is read-side resolution only.

Run: uv run pytest -q tests/test_moved_paths.py
"""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from limn import mapping
from limn.store import dump_jsonl
from test_access import AccessBase
from test_server import add_pin, ps
from test_v03 import ScopedRepo

MS_MAIN = "\\documentclass{article}\n\\begin{document}\n\\input{response/main}\n" + "".join(
    "Body sentence %d.\n" % i for i in range(4, 30)) + "\\end{document}\n"
SUB = "".join("Sub-file sentence %d about the ms appendix.\n" % i for i in range(1, 25))
RR_MAIN = "\\documentclass{article}\n\\begin{document}\n" + "".join(
    "Reply sentence %d to the reviewer.\n" % i for i in range(3, 30)) + "\\end{document}\n"


class ScopedTailRule(unittest.TestCase):
    """mapping.pin_rel_path(scope=...): the legacy tail guess is searched under the document folder."""

    def rel(self, file, existing, scope, file_rel=None, under=None):
        """pin_rel_path with the existence check answered from a set of root-relative paths."""
        return mapping.pin_rel_path(file, file_rel, under, set(existing).__contains__, scope)

    def test_a_tail_of_another_document_is_never_picked(self):
        """The shorter tail response/main.tex belongs to another document: with the pin's folder as scope it is skipped."""
        f = "/old/paper/manuscript/response/main.tex"
        self.assertEqual(self.rel(f, {"response/main.tex"}, ""), "response/main.tex")        # 0.3.2: whole root
        self.assertIsNone(self.rel(f, {"response/main.tex"}, "manuscript"))

    def test_a_renamed_document_folder_is_followed(self):
        """Tails are joined to the document folder, so a folder renamed with its --doc spec is found again."""
        f = "/old/paper/response/main.tex"
        self.assertEqual(self.rel(f, {"main.tex", "reply/main.tex"}, "reply"), "reply/main.tex")
        self.assertEqual(self.rel(f, {"main.tex", "reply/main.tex"}, ""), "main.tex")        # 0.3.2: another document

    def test_the_longest_tail_under_the_scope_wins(self):
        """Within the scope the order is ADR-0006's: longest existing tail first."""
        f = "/old/p/ms/sec/x.tex"
        self.assertEqual(self.rel(f, {"ms/sec/x.tex", "ms/x.tex"}, "ms"), "ms/sec/x.tex")
        self.assertEqual(self.rel(f, {"ms/x.tex"}, "ms"), "ms/x.tex")

    def test_known_locations_are_not_scoped(self):
        """Rules 1 and 2 are facts, not guesses: the file under the root and a matching file_rel win whatever the scope."""
        f = "/old/p/sections/x.tex"
        self.assertEqual(self.rel(f, set(), "ms", under="sections/x.tex"), "sections/x.tex")
        self.assertEqual(self.rel(f, set(), "ms", file_rel="sections/x.tex"), "sections/x.tex")

    def test_a_scope_that_climbs_finds_nothing(self):
        """A scope with '..' (never produced by the server) does not widen the search above the root."""
        self.assertIsNone(self.rel("/o/p/x.tex", {"../x.tex", "x.tex"}, "../elsewhere"))


class MultiDocMoved(AccessBase):
    """Two documents (ms = manuscript/main.tex, rr = response/main.tex); legacy records; the checkout is moved."""

    def setUp(self):
        """paper-a with both documents, one legacy pin in each (file only, no file_rel)."""
        super().setUp()
        self.old = Path(self.tmp.name) / "paper-a"
        (self.old / "manuscript" / "response").mkdir(parents=True)
        (self.old / "response").mkdir()
        (self.old / "manuscript" / "main.tex").write_text(MS_MAIN, encoding="utf-8")
        (self.old / "manuscript" / "response" / "main.tex").write_text(SUB, encoding="utf-8")
        (self.old / "response" / "main.tex").write_text(RR_MAIN, encoding="utf-8")
        self.serve(self.old, "response/main.tex")
        ms, rr = ps.DOCS
        with ps.using_doc(ms):
            self.p_ms = add_pin({"file": str(self.old / "manuscript" / "response" / "main.tex"), "lo": 5, "hi": 6,
                                    "note": "ms appendix", "doc": "ms"}, dict(ps.LOCAL_ACTOR)).record["id"]
        with ps.using_doc(rr):
            self.p_rr = add_pin({"file": str(self.old / "response" / "main.tex"), "lo": 6, "hi": 7,
                                    "note": "reply", "doc": "rr"}, dict(ps.LOCAL_ACTOR)).record["id"]
        rows = ps.read_pins()[0]
        for r in rows:
            r.pop("file_rel", None)                  # as 0.3.1 wrote them: absolute file only
        ps.C.pins_jsonl.write_text(dump_jsonl(rows), encoding="utf-8")
        self.addCleanup(ps.set_docs, None)

    def serve(self, root: Path, rr_main: str):
        """Point the server at a manuscript root with the two documents, as a restart with --doc would."""
        ps.C.src, ps.C.main = root, root / "manuscript" / "main.tex"
        ps.set_docs(ps.make_docs(["ms=본문:manuscript/main.tex", "rr=답변서:%s" % rr_main], root))

    def pins(self):
        """GET /api/pins?all=1 as {id: pin}."""
        code, rows = self.call("GET", "/api/pins?all=1")
        self.assertEqual(code, 200, rows)
        return {r["id"]: r for r in rows}

    def test_a_moved_record_never_resolves_into_another_document(self):
        """Issue #24 §2: the ms pin's sub-folder is gone after the move; the tail response/main.tex (rr's main file)
        exists, but the pin is searched in manuscript/ only. It resolves inside its own document, where the anchor
        does not match and it shows as lost (the ADR-0006 known limit for a guess), never onto rr's lines."""
        new = Path(self.tmp.name) / "paper-b"
        os.rename(self.old, new)
        shutil.rmtree(new / "manuscript" / "response")
        self.serve(new, "response/main.tex")
        p = self.pins()[self.p_ms]
        self.assertNotEqual(p.get("rel_path"), "response/main.tex")
        self.assertFalse(p["file"].startswith(str(new / "response")), p["file"])
        self.assertEqual(p.get("rel_path"), "manuscript/main.tex")
        self.assertTrue(p.get("stale"), p)

    def test_a_renamed_document_folder_is_followed(self):
        """Moving the checkout and renaming response/ to reply/ (with --doc rr=reply/main.tex): the rr pin is found
        there and keeps its lines; 0.3.2 left it outside the tree."""
        new = Path(self.tmp.name) / "paper-b"
        os.rename(self.old, new)
        os.rename(new / "response", new / "reply")
        self.serve(new, "reply/main.tex")
        p = self.pins()[self.p_rr]
        self.assertEqual((p.get("rel_path"), p["file"]), ("reply/main.tex", str(new / "reply" / "main.tex")))
        self.assertEqual((p["lo"], p["hi"]), (6, 7))
        self.assertFalse(p.get("stale"))

    def test_reading_never_backfills_file_rel(self):
        """Resolution is read-side only (ADR-0006 §3): after reads of the moved state no legacy record gains file_rel."""
        new = Path(self.tmp.name) / "paper-b"
        os.rename(self.old, new)
        os.rename(new / "response", new / "reply")
        self.serve(new, "reply/main.tex")
        self.pins()
        self.call("GET", "/pins.md")
        self.assertEqual([r["id"] for r in ps.read_pins()[0] if "file_rel" in r], [])


class ChangesAfterAClone(ScopedRepo):
    """Issue #24 §1: a pin closed with `changes` keeps its recorded lines in [View changes] after a clone elsewhere."""

    def clone(self):
        """Clone the ADR-0005 fixture repository to another path and serve its manuscript folder from there."""
        clone = Path(self.tmp.name) / "clone"
        subprocess.run(["git", "clone", "--quiet", str(self.repo), str(clone)], check=True, capture_output=True)
        ps.C.src, ps.C.main = clone / "ms", clone / "ms" / "main.tex"
        return clone

    def test_recorded_changes_still_count_in_a_clone(self):
        """alpha was closed with changes: its scope source stays `changes` (0.3.2 fell back to `inferred`)."""
        code, d = self.diff(self.fix, self.p1)
        self.assertEqual((code, d["scope"]["source"]), (200, "changes"))
        self.clone()
        code, d = self.diff(self.fix, self.p1)
        self.assertEqual(code, 200, d)
        self.assertEqual((d["scope"]["mode"], d["scope"]["source"]), ("pin", "changes"))

    def test_the_stored_changes_are_not_rewritten(self):
        """The record keeps the absolute path it was closed with; only the read resolves it."""
        stored = [c["file"] for c in self.pin(self.p1)["changes"]]
        self.clone()
        self.diff(self.fix, self.p1)
        self.assertEqual([c["file"] for c in self.pin(self.p1)["changes"]], stored)

    def test_a_change_whose_path_matches_nothing_is_dropped(self):
        """A recorded path with no tail under the new root is not guessed: the pin's hunks are inferred, as before."""
        def fn(rows):
            """Point alpha's recorded changes at a path that exists nowhere."""
            r = next(r for r in rows if r["id"] == self.p1)
            r["changes"] = [dict(c, file="/nowhere/else/other.tex") for c in r["changes"]]
            return None, True
        ps.transact(fn)
        self.clone()
        code, d = self.diff(self.fix, self.p1)
        self.assertEqual((code, d["scope"]["source"]), (200, "inferred"))

    def test_a_change_through_a_symlink_to_outside_is_not_followed(self):
        """A tail that exists only through a link leading outside the manuscript folder is refused (R10); the next tail
        is tried, and when none is left the path stays unresolved."""
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "only.tex").write_text("x\n", encoding="utf-8")
        clone = self.clone()
        (clone / "ms" / "linked").symlink_to(outside, target_is_directory=True)
        self.assertTrue((ps.C.src / "linked" / "only.tex").is_file())
        self.assertIsNone(ps.locate_file("/old/place/linked/only.tex", None, ps.C.src, None))
        self.assertEqual(ps.locate_file("/old/place/linked/main.tex", None, ps.C.src, None).rel, "main.tex")


if __name__ == "__main__":
    unittest.main()
