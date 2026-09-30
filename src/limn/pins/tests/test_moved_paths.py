"""A moved manuscript: pins follow the checkout to a new path (v0.3.2, issue #7, docs/adr/0006-relative-pin-paths.md).

Pins stored the manuscript file only as an absolute path, so moving the checkout left every pin outside the tree: no
line re-sync, no range edit, no «…» quote, and a bare file name in pins.md. Records now also store `file_rel`
(relative to --manuscript) when the server writes that pin, and every record - old ones included - is located on
read by one rule (mapping.pin_rel_path, tested on its own in test_mapping.PinRelPathRule). MovedManuscript,
OutsideTheTree and ScopedChangesAfterAClone pin that; RollbackToV030 and RollbackToV031 check that the released
0.3.0 and 0.3.1 servers read this version's state (skipped in a shallow clone).

The ADR-0006 follow-ups (issue #24), the two paths a moved manuscript still lost:

1. The paths in a closed pin's `changes` (ADR-0005) are absolute. After the checkout moves they are now located on read
   by the same rule as the pin's own file (mapping.pin_rel_path), so pin-scoped [View changes] still uses the lines the
   agent recorded instead of falling back to inference. Nothing is rewritten, nothing outside the tree is read.
2. In a multi-document instance, the tail guess for a moved legacy record is searched in the pin's own document folder
   (its build root), so a same-named file of another document is never picked; a renamed document folder is followed.

The follow-ups add no stored field and change no field's meaning: they are read-side resolution only.

Run: uv run pytest -q src/limn/pins/tests/test_moved_paths.py
"""

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from limn.administration import serve_documents as startup_documents
from limn.pins.location import mapping
from limn.pins.location.lookup import locate_file
from limn.pins.store import dump_jsonl
from limn.security.access import LOCAL_ACTOR

from helpers import ROOT, add_pin, edit_stored, ps, records, req, set_config, split_resp
from helpers_access import MOVED_X as X, AccessBase, MovedManuscriptBase, ScopedRepo, configure, mask, talk_to

MS_MAIN = (
    "\\documentclass{article}\n\\begin{document}\n\\input{response/main}\n"
    + "".join("Body sentence %d.\n" % i for i in range(4, 30))
    + "\\end{document}\n"
)
SUB = "".join("Sub-file sentence %d about the ms appendix.\n" % i for i in range(1, 25))
RR_MAIN = (
    "\\documentclass{article}\n\\begin{document}\n"
    + "".join("Reply sentence %d to the reviewer.\n" % i for i in range(3, 30))
    + "\\end{document}\n"
)


class ScopedTailRule(unittest.TestCase):
    """mapping.pin_rel_path(scope=...): the legacy tail guess is searched under the document folder."""

    def rel(self, file, existing, scope, file_rel=None, under=None):
        """pin_rel_path with the existence check answered from a set of root-relative paths."""
        return mapping.pin_rel_path(file, file_rel, under, set(existing).__contains__, scope)

    def test_a_tail_of_another_document_is_never_picked(self):
        """The shorter tail response/main.tex belongs to another document: with the pin's folder as scope it is skipped."""
        f = "/old/paper/manuscript/response/main.tex"
        self.assertEqual(self.rel(f, {"response/main.tex"}, ""), "response/main.tex")  # 0.3.2: whole root
        self.assertIsNone(self.rel(f, {"response/main.tex"}, "manuscript"))

    def test_a_renamed_document_folder_is_followed(self):
        """Tails are joined to the document folder, so a folder renamed with its --doc spec is found again."""
        f = "/old/paper/response/main.tex"
        self.assertEqual(self.rel(f, {"main.tex", "reply/main.tex"}, "reply"), "reply/main.tex")
        self.assertEqual(self.rel(f, {"main.tex", "reply/main.tex"}, ""), "main.tex")  # 0.3.2: another document

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
        ms, rr = ps.APP.docs
        self.p_ms = add_pin(
            {
                "file": str(self.old / "manuscript" / "response" / "main.tex"),
                "lo": 5,
                "hi": 6,
                "note": "ms appendix",
                "doc": "ms",
            },
            dict(LOCAL_ACTOR),
            doc=ms,
        ).record["id"]
        self.p_rr = add_pin(
            {"file": str(self.old / "response" / "main.tex"), "lo": 6, "hi": 7, "note": "reply", "doc": "rr"},
            dict(LOCAL_ACTOR),
            doc=rr,
        ).record["id"]
        rows = records(ps.APP.read_pins()[0])
        for r in rows:
            r.pop("file_rel", None)  # as 0.3.1 wrote them: absolute file only
        ps.APP.C.pins_jsonl.write_text(dump_jsonl(rows), encoding="utf-8")
        self.addCleanup(ps.APP.set_docs, None)

    def serve(self, root: Path, rr_main: str):
        """Point the server at a manuscript root with the two documents, as a restart with --doc would."""
        set_config(src=root, main=root / "manuscript" / "main.tex")
        ps.APP.set_docs(
            startup_documents.make_docs(["ms=본문:manuscript/main.tex", "rr=답변서:%s" % rr_main], root, ps.APP.C.paths)
        )

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
        self.assertEqual([r["id"] for r in records(ps.APP.read_pins()[0]) if "file_rel" in r], [])


class ChangesAfterAClone(ScopedRepo):
    """Issue #24 §1: a pin closed with `changes` keeps its recorded lines in [View changes] after a clone elsewhere."""

    def clone(self):
        """Clone the ADR-0005 fixture repository to another path and serve its manuscript folder from there."""
        clone = Path(self.tmp.name) / "clone"
        subprocess.run(["git", "clone", "--quiet", str(self.repo), str(clone)], check=True, capture_output=True)
        set_config(src=clone / "ms", main=clone / "ms" / "main.tex")
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

        edit_stored(fn)
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
        self.assertTrue((ps.APP.C.src / "linked" / "only.tex").is_file())
        self.assertIsNone(locate_file("/old/place/linked/only.tex", None, ps.APP.C.src, ps.APP.C.state, None))
        self.assertEqual(
            locate_file("/old/place/linked/main.tex", None, ps.APP.C.src, ps.APP.C.state, None).rel, "main.tex"
        )


# ---------------------------------------------------------------- moving the manuscript between two server runs (v0.3.2, issue #7)


SECRET = "TOPSECRET outside-the-tree line " + "x" * 700 + "\n"


class MovedManuscript(MovedManuscriptBase):
    """Issue #7: after the move pins keep syncing, range edits work and pins.md keeps the sub-folder."""

    def test_new_records_store_a_relative_path_next_to_the_absolute_one(self):
        """A pin created by this version stores file_rel and a file under the current root; the API calls it rel_path."""
        r = self.stored()[self.p_new]
        self.assertEqual((r["file"], r["file_rel"]), (str(self.a / "sections" / "x.tex"), "sections/x.tex"))
        p = self.api_pins()[self.p_new]
        self.assertEqual(p["rel_path"], "sections/x.tex")
        self.assertNotIn("file_rel", p)

    def test_api_gives_the_current_absolute_path_and_the_relative_path(self):
        """After the move `file` is the path on this machine now and `rel_path` is added - for old records too."""
        self.move()
        pins = self.api_pins()
        for pid in (self.p_new, self.p_old):
            self.assertEqual(pins[pid]["file"], str(self.b / "sections" / "x.tex"), pid)
            self.assertEqual(pins[pid]["rel_path"], "sections/x.tex", pid)
        code, one = self.call("GET", "/api/pins/%d" % self.p_old)
        self.assertEqual(one["pin"]["file"], str(self.b / "sections" / "x.tex"))

    def test_pins_md_keeps_the_sub_folder_and_the_quote(self):
        """The location column stays `sections/x.tex L..` and the long-line «…» quote is still attached."""
        self.move()
        md = self.pins_md()
        self.assertIn("`sections/x.tex L5-L6`", md)
        self.assertIn("`sections/x.tex L10-L11`", md)
        self.assertIn("`sections/long.tex L1-L1`", md)
        self.assertIn("«Long line word word»", md)

    def test_line_numbers_follow_edits_after_the_move(self):
        """Adding two lines above the pins moves both (new and legacy) by +2 via the anchor re-sync."""
        self.move()
        f = self.b / "sections" / "x.tex"
        f.write_text("new line a\nnew line b\n" + X, encoding="utf-8")
        os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))
        pins = self.api_pins()
        self.assertEqual((pins[self.p_new]["lo"], pins[self.p_new]["hi"]), (7, 8))
        self.assertEqual((pins[self.p_old]["lo"], pins[self.p_old]["hi"]), (12, 13))
        self.assertFalse(pins[self.p_old].get("stale"))

    def test_range_edit_works_on_a_legacy_record_and_stamps_the_new_location(self):
        """/edit with lo/hi used to be 400 'outside the manuscript'; now it edits, and the record gets file_rel + the current file."""
        self.move()
        rev = self.api_pins()[self.p_old]["rev"]
        code, d = self.call("POST", "/api/pins/%d/edit" % self.p_old, {"lo": 14, "hi": 15, "base_rev": rev})
        self.assertEqual(code, 200, d)
        self.assertEqual(
            (d["pin"]["lo"], d["pin"]["hi"], d["pin"]["file"]), (14, 15, str(self.b / "sections" / "x.tex"))
        )
        r = self.stored()[self.p_old]
        self.assertEqual((r["file"], r["file_rel"]), (str(self.b / "sections" / "x.tex"), "sections/x.tex"))
        self.assertEqual(r["anchor"]["head"], "Sentence number 14 about topic14.")

    def test_reading_never_rewrites_a_legacy_record(self):
        """No write migration: reads after a plain move (same files) leave pins.jsonl byte for byte as it was."""
        self.move()
        before = ps.APP.C.pins_jsonl.read_bytes()
        self.api_pins()
        self.pins_md()
        self.call("GET", "/api/pins?all=1")
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)
        self.assertNotIn("file_rel", self.stored()[self.p_old])
        self.assertEqual(self.stored()[self.p_old]["file"], str(self.a / "sections" / "x.tex"))

    def test_a_write_for_another_pin_does_not_backfill_a_legacy_record(self):
        """Only writes to the pin itself (create, edit, restore) add file_rel; other writes keep the stored record."""
        self.move()
        self.pin_at("sections/x.tex", 18, 18)
        code, _ = self.call("POST", "/api/pins/%d/close" % self.p_new, {"reply": "done"})
        self.assertEqual(code, 200)
        r = self.stored()[self.p_old]
        self.assertNotIn("file_rel", r)
        self.assertEqual(r["file"], str(self.a / "sections" / "x.tex"))

    def test_overlaps_join_pins_made_before_and_after_the_move(self):
        """A legacy pin and a pin placed after the move on the same range are the same file for the overlap rules."""
        self.move()
        pid = self.pin_at("sections/x.tex", 10, 11)
        pins = self.api_pins()
        self.assertIn({"id": self.p_old, "rel": "inside"}, pins[pid]["rel"])
        code, d = self.call("GET", "/api/overlaps?file=%s&lo=10&hi=11" % (self.b / "sections" / "x.tex"))
        self.assertEqual(code, 200, d)
        self.assertEqual({o["id"] for o in d["overlaps"]}, {self.p_old, pid})

    def test_drop_and_restore_after_the_move(self):
        """The Trash shows the current path, and a restored legacy record comes back with file_rel."""
        self.move()
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % self.p_old)[0], 200)
        code, d = self.call("GET", "/api/pins/dropped")
        self.assertEqual([r["file"] for r in d["dropped"]], [str(self.b / "sections" / "x.tex")])
        code, d = self.call("POST", "/api/pins/%d/restore" % self.p_old)
        self.assertEqual(code, 200, d)
        r = self.stored()[self.p_old]
        self.assertEqual((r["file"], r["file_rel"]), (str(self.b / "sections" / "x.tex"), "sections/x.tex"))

    def test_a_moved_legacy_record_resolves_by_its_tail(self):
        """A 0.3.0 record whose sub-folder is gone falls to the longest existing tail (here the root file)."""
        self.move()
        self.rewrite(
            lambda rows: [r.update(file="/nowhere/paper/old-dir/main.tex") for r in rows if r["id"] == self.p_old]
        )
        self.assertEqual(self.api_pins()[self.p_old]["rel_path"], "main.tex")

    def copy_to_b(self, prefix="new line a\nnew line b\n", mtime_delta=-100.0):
        """B = a copy of A with `prefix` added to sections/x.tex, its mtime set relative to A's (a restored or rsynced copy)."""
        shutil.copytree(self.a, self.b)
        f = self.b / "sections" / "x.tex"
        f.write_text(prefix + X, encoding="utf-8")
        t = (self.a / "sections" / "x.tex").stat().st_mtime + mtime_delta
        os.utime(f, (t, t))

    def test_a_copy_with_an_older_mtime_is_still_re_matched(self):
        """synced_at was measured on A; B's older mtime must not skip the re-match when B's lines differ (review of #19)."""
        self.copy_to_b()
        self.use_root(self.b)
        pins = self.api_pins()
        self.assertEqual((pins[self.p_new]["lo"], pins[self.p_old]["lo"]), (7, 12))
        stored = self.stored()
        self.assertEqual(stored[self.p_old]["file"], str(self.b / "sections" / "x.tex"))  # lines and file describe B
        self.assertNotIn("file_rel", stored[self.p_old])  # still no backfill

    def test_switching_back_to_the_old_checkout_follows_its_lines_again(self):
        """A -> B (newer, two lines added) -> A: back on A the pins are at A's lines, not B's (review of #19)."""
        self.copy_to_b(mtime_delta=100.0)
        self.use_root(self.b)
        self.assertEqual(self.api_pins()[self.p_old]["lo"], 12)
        self.use_root(self.a)
        pins = self.api_pins()
        self.assertEqual((pins[self.p_new]["lo"], pins[self.p_new]["hi"]), (5, 6))
        self.assertEqual((pins[self.p_old]["lo"], pins[self.p_old]["hi"]), (10, 11))
        self.assertEqual(pins[self.p_old]["file"], str(self.a / "sections" / "x.tex"))

    def test_an_anchorless_legacy_record_is_not_backfilled_from_a_moved_file(self):
        """An anchor is only ever taken from the file the record names, never from a located (possibly guessed) one."""
        self.rewrite(lambda rows: [r.pop("anchor", None) for r in rows if r["id"] == self.p_old])
        self.move()
        self.api_pins()
        r = self.stored()[self.p_old]
        self.assertNotIn("anchor", r)
        self.assertEqual(r["file"], str(self.a / "sections" / "x.tex"))

    def test_an_over_long_note_append_leaves_the_pin_unchanged(self):
        """The 400 for a note_append over NOTE_MAX comes before any change, even when the same write re-syncs lines."""
        rev = self.api_pins()[self.p_old]["rev"]
        self.assertEqual(
            self.call("POST", "/api/pins/%d/edit" % self.p_old, {"note": "n" * 3000, "base_rev": rev})[0], 200
        )
        f = self.a / "sections" / "x.tex"
        os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))  # the next transact re-syncs
        before = self.stored()[self.p_old]
        code, d = self.call(
            "POST",
            "/api/pins/%d/edit" % self.p_old,
            {"lo": 14, "hi": 15, "note_append": "x" * 1500, "base_rev": rev + 1},
        )
        self.assertEqual(code, 400, d)
        after = self.stored()[self.p_old]
        self.assertEqual(
            (after["lo"], after["hi"], after["note"], after.get("file_rel")),
            (before["lo"], before["hi"], before["note"], before.get("file_rel")),
        )


class OutsideTheTree(MovedManuscriptBase):
    """Records that cannot be located under the current root stay out of tree and nothing outside is read."""

    def setUp(self):
        super().setUp()
        self.move()
        self.outside = Path(self.tmp.name) / "outside"
        self.outside.mkdir()
        (self.outside / "secret.tex").write_text(SECRET, encoding="utf-8")

    def put(self, **fields):
        """Replace the legacy pin with a record carrying `fields`, without an anchor (so a read would backfill one)."""

        def fn(rows):
            r = next(r for r in rows if r["id"] == self.p_old)
            for k in ("anchor", "file_rel", "synced_at", "scope"):
                r.pop(k, None)
            r.update(lo=1, hi=1, quote="TOPSECRET", **fields)

        self.rewrite(fn)

    def assert_out_of_tree(self, stored_file):
        """The pin keeps its stored file, gains no rel_path or anchor, leaks no outside text, and refuses range edits."""
        pins = self.api_pins()
        p = pins[self.p_old]
        self.assertEqual(p["file"], stored_file)
        self.assertNotIn("rel_path", p)
        self.assertNotIn("TOPSECRET outside", json.dumps(pins, ensure_ascii=False))
        md = self.pins_md()
        self.assertNotIn("«TOPSECRET", md)
        self.assertIn("`%s L1-L1`" % Path(stored_file).name, md)
        self.assertNotIn("anchor", self.stored()[self.p_old])
        code, d = self.call("POST", "/api/pins/%d/edit" % self.p_old, {"lo": 1, "hi": 1, "base_rev": p["rev"]})
        self.assertEqual(
            (code, d["error"]), (400, "원고 디렉토리 밖을 가리키는 핀입니다 — 위치 다시 잡기(loc)로 고치세요.")
        )

    def test_a_record_whose_tail_matches_nothing_stays_outside(self):
        """Issue #7: an outside file with no matching tail under the root is never read (no anchor, quote or lines)."""
        f = str(self.outside / "secret.tex")
        self.put(file=f)
        self.assert_out_of_tree(f)

    def test_a_parent_escaping_file_rel_is_not_followed(self):
        """file_rel '../outside/secret.tex' (with a file ending the same way) does not climb out of the root."""
        f = str(self.b / ".." / "outside" / "secret.tex")
        self.put(file=f, file_rel="../outside/secret.tex")
        self.assert_out_of_tree(f)

    def test_an_absolute_file_rel_is_not_followed(self):
        """An absolute file_rel would replace the root when joined; it is ignored."""
        f = str(self.outside / "secret.tex")
        self.put(file=f, file_rel=f)
        self.assert_out_of_tree(f)

    def test_a_symlink_inside_the_tree_pointing_outside_is_refused(self):
        """Neither a trusted file_rel nor a tail may reach an outside file through a symlink in the manuscript."""
        (self.b / "linked").symlink_to(self.outside, target_is_directory=True)
        f = "/nowhere/paper-a/linked/secret.tex"
        self.put(file=f, file_rel="linked/secret.tex")
        self.assert_out_of_tree(f)
        self.put(file=f)  # legacy: the tail linked/secret.tex exists via the link
        self.assert_out_of_tree(f)

    def test_a_file_rel_of_the_wrong_type_is_a_broken_line(self):
        """file_rel, when present, must be a string - like every field the store reads."""
        self.rewrite(lambda rows: [r.update(file_rel=5) for r in rows if r["id"] == self.p_old])
        pins, bad = ps.APP.read_pins()
        self.assertNotIn(self.p_old, [p.core.id for p in pins])
        self.assertEqual(len(bad), 1)


class ScopedChangesAfterAClone(ScopedRepo):
    """Pin-scoped [View changes] (revision_diff with pin=) finds a moved pin's hunks: it reads the located rows."""

    def test_an_inferred_pin_keeps_its_hunk_in_a_clone_elsewhere(self):
        """The ADR-0005 repository cloned to another path: beta's pin still gets only its own hunk (was the whole commit)."""
        clone = Path(self.tmp.name) / "clone"
        subprocess.run(["git", "clone", "--quiet", str(self.repo), str(clone)], check=True, capture_output=True)
        set_config(src=clone / "ms", main=clone / "ms" / "main.tex")
        code, d = self.diff(self.fix, self.p2)
        self.assertEqual(code, 200, d)
        s = d["scope"]
        self.assertEqual((s["mode"], s["source"], s["hunks"]), ("pin", "inferred", 1))
        self.assertIn("blueberries", s["diff"])


# ---------------------------------------------------------------- rollback to 0.3.x: the released servers read this version's state


def load_release(tag):
    """The server module exactly as released in `tag` (from git, with its sibling modules), or None in a shallow clone."""
    r = subprocess.run(
        ["git", "show", "%s:src/limn/server.py" % tag], cwd=ROOT, capture_output=True, timeout=30, check=False
    )
    if r.returncode != 0 or b"def revision_pin_scope" not in r.stdout:
        return None
    d = Path(tempfile.mkdtemp(prefix="limn-%s-" % tag))
    name = "server_%s" % tag.replace(".", "")
    (d / (name + ".py")).write_bytes(r.stdout)
    spec = importlib.util.spec_from_file_location("limn_" + name, d / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    shutil.rmtree(d, ignore_errors=True)
    return mod


class RollbackToV030(MovedManuscriptBase):
    """State written by this version is read by the released 0.3.0 server, and 0.3.0's writes are read back correctly.
    RollbackToV031 runs the same tests against 0.3.1, the release this one replaces."""

    TAG = "v0.3.0"

    @classmethod
    def setUpClass(cls):
        cls.v030 = load_release(cls.TAG)

    def setUp(self):
        if self.v030 is None:
            self.skipTest("%s is not in this clone's history (shallow checkout)" % self.TAG)
        super().setUp()

    def old(self, path, method="GET", body=None):
        """One request to the released module on the same manuscript and state directory."""
        configure(self.v030, ps.APP.C.src, ps.APP.C.main, ps.APP.C.state)
        return self.v030_call(method, path, body)

    def v030_call(self, method, path, body):
        raw = json.dumps(body).encode() if body is not None else b""
        h = {"Content-Type": "application/json"} if body is not None else {}
        code, _, out = split_resp(talk_to(self.v030, req(method, path, raw, h)))
        configure(ps, ps.APP.C.src, ps.APP.C.main, ps.APP.C.state)
        text = out.decode("utf-8")
        try:
            return code, json.loads(text)
        except ValueError:
            return code, text

    def test_v030_reads_the_branch_state_unchanged(self):
        """Same pins, lines and files from 0.3.0 (file_rel is just an extra field there), and the same pins.md."""
        new = self.api_pins()
        code, rows = self.old("/api/pins")
        self.assertEqual(code, 200, rows)
        old = {r["id"]: r for r in rows}
        self.assertEqual(sorted(old), sorted(new))
        for pid in old:
            for k in ("file", "lo", "hi", "note", "rev", "state"):
                self.assertEqual(old[pid].get(k), new[pid].get(k), (pid, k))
        self.assertEqual(mask(self.old("/pins.md")[1]), mask(self.pins_md()))

    def test_a_record_the_branch_rewrote_after_the_move_is_in_tree_for_v030(self):
        """After an edit on the branch, 0.3.0 sees the legacy pin under the new root and can edit its range."""
        self.move()
        rev = self.api_pins()[self.p_old]["rev"]
        self.assertEqual(
            self.call("POST", "/api/pins/%d/edit" % self.p_old, {"note": "moved", "base_rev": rev})[0], 200
        )
        code, d = self.old("/api/pins/%d/edit" % self.p_old, "POST", {"lo": 3, "hi": 4, "base_rev": rev + 1})
        self.assertEqual(code, 200, d)
        self.assertIn("`sections/x.tex L3-L4`", self.old("/pins.md")[1])

    def test_a_v030_relocation_wins_over_the_stale_file_rel(self):
        """0.3.0 relocating a pin to another file changes file but keeps file_rel; the branch follows the new file, and
        0.3.0 itself never shows a `rel_path` (only the stored `file_rel`, which no agent is told to read)."""
        (self.a / "sections" / "y.tex").write_text(X, encoding="utf-8")
        rev = self.api_pins()[self.p_new]["rev"]
        loc = {"file": str(self.a / "sections" / "y.tex"), "lo": 2, "hi": 3}
        code, d = self.old("/api/pins/%d/edit" % self.p_new, "POST", {"loc": loc, "base_rev": rev})
        self.assertEqual(code, 200, d)
        self.assertEqual(self.stored()[self.p_new]["file_rel"], "sections/x.tex")  # 0.3.0 left it as it was
        self.assertNotIn("rel_path", self.old("/api/pins/%d" % self.p_new)[1]["pin"])
        self.move()  # and then the checkout moves
        p = self.api_pins()[self.p_new]
        self.assertEqual((p["file"], p["rel_path"]), (str(self.b / "sections" / "y.tex"), "sections/y.tex"))


class RollbackToV031(RollbackToV030):
    """The same rollback checks against 0.3.1 - the release deployed before this one."""

    TAG = "v0.3.1"


if __name__ == "__main__":
    unittest.main()
