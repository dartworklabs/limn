"""v0.3 (issue #9): pin-scoped [View changes].

Layers (docs/adr/0005-pin-scoped-changes.md):
1. agents commit once per pin and close with ref = that commit (docs and skill only),
2. an optional `changes: [{file, lo, hi}]` on POST /api/pins/{id}/close - the new-side lines the agent changed for the pin,
3. for pins without it, the server infers the pin's hunks from the pin's range mapped through the commit.

The source diff shows only the pin's hunks (the rest folded under one control) and the comparison PDF compiles a synthetic
new version = old version + only the pin's hunks, with a single toggle back to the whole commit.

Run: uv run pytest -q tests/test_v03.py
"""
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
import typing
import unittest
from pathlib import Path
from unittest import mock

from limn.web.errors import SCOPE_REJECTIONS, scope_http_error
from test_access import ALICE, AccessBase, talk_to
from limn import revisions
from limn import scope as scoping
from limn.web import parse
from test_qa_021 import BrowserBase, actor
from helpers import add_pin, extract_js_fn, ps, req, revision_spec, run_node, split_resp

HANGUL = re.compile(r"[가-힣]")
A = actor(ALICE)

OLD = """\\documentclass{article}
\\begin{document}
\\section{Intro}
Alpha paragraph talks about apples.

Filler one.
Filler two.
Filler three.
Filler four.

Beta paragraph talks about bananas.

Filler five.
Filler six.
Filler seven.
Filler eight.

Gamma paragraph talks about cherries.
\\end{document}
"""
# One commit touching three pins: alpha grows by a line (shifting everything below by +1), beta is rewritten, gamma is deleted.
NEW = OLD.replace("Alpha paragraph talks about apples.\n", "Alpha paragraph talks about apples and pears.\nA second alpha sentence.\n") \
         .replace("Beta paragraph talks about bananas.", "Beta paragraph talks about blueberries.") \
         .replace("Gamma paragraph talks about cherries.\n", "")
# The -U0 hunks git prints for OLD -> NEW (checked against real git in GitBlocks below).
U0 = (b"@@ -4 +4,2 @@\n-Alpha paragraph talks about apples.\n+Alpha paragraph talks about apples and pears.\n+A second alpha sentence.\n"
      b"@@ -11 +12 @@\n-Beta paragraph talks about bananas.\n+Beta paragraph talks about blueberries.\n"
      b"@@ -18 +18,0 @@\n-Gamma paragraph talks about cherries.\n")
A_BLK, B_BLK, C_BLK = (3, 1, 3, 2), (10, 1, 11, 1), (17, 1, 18, 0)


def fc(old=OLD, new=NEW, patch=U0, old_path="ms/main.tex", new_path="ms/main.tex"):
    o, n = old.encode(), new.encode()
    return scoping.FileChange(old_path, new_path, scoping.git_lines(o), scoping.git_lines(n), tuple(scoping.parse_u0_blocks(patch)), False)


def anchored(lo, hi, text=OLD, **extra):
    """A pin record whose anchor was captured from `text` (what add_pin stores)."""
    lines = text.split("\n")
    return dict({"id": 1, "file": "/x/ms/main.tex", "lo": lo, "hi": hi, "anchor": ps.anchor_of(lines, lo, hi)}, **extra)


def minimal_pdf(label: str = "") -> bytes:
    """A valid one-page PDF (pdf.js renders it) - browser tests stand in for latexdiff/latexmk, which CI does not have."""
    stream = b"BT /F1 24 Tf 72 700 Td (" + label.encode("ascii") + b") Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


# ---------------------------------------------------------------- 1. hunks: parsing, attribution, rendering, applying

class BlockParsing(unittest.TestCase):
    """Reading git's -U0 output into blocks (pure)."""

    def test_git_lines_split_on_newline_only_and_keep_a_missing_final_newline(self):
        """git_lines() counts lines like git (\n only), so block numbers from git index the right bytes."""
        self.assertEqual(scoping.git_lines(b"a\r\nb\rc\nd"), (b"a\r\n", b"b\rc\n", b"d"))
        self.assertEqual(scoping.git_lines(b""), ())
        self.assertEqual(scoping.git_lines(b"x\n"), (b"x\n",))

    def test_u0_headers_become_zero_based_blocks_including_empty_sides(self):
        """The -U0 header convention for a zero count (the line before) maps to the block's insertion point."""
        self.assertEqual([tuple(b) for b in scoping.parse_u0_blocks(U0)], [A_BLK, B_BLK, C_BLK])
        # pure insertion after old line 5: the old span is empty and sits before old index 5
        self.assertEqual(tuple(scoping.parse_u0_blocks(b"@@ -5,0 +6,2 @@\n+x\n+y\n")[0]), (5, 0, 5, 2))
        self.assertEqual(tuple(scoping.parse_u0_blocks(b"@@ -0,0 +1,3 @@\n+a\n+b\n+c\n")[0]), (0, 0, 0, 3))   # new file
        self.assertEqual(scoping.parse_u0_blocks(b"diff --git a/x b/x\nBinary files a/x and b/x differ\n"), [])

    def test_touch_range_covers_the_lines_around_an_insertion_or_deletion_point(self):
        """A pure insertion or deletion can be named by the line before or after it."""
        self.assertEqual(scoping.touch_range(3, 2), (4, 5))
        self.assertEqual(scoping.touch_range(18, 0), (18, 19))
        self.assertEqual(scoping.touch_range(0, 0), (1, 1))


class Attribution(unittest.TestCase):
    """Which blocks of a commit belong to a pin: recorded changes, else the pin's range mapped through the commit (pure)."""

    def setUp(self):
        self.files = [fc()]

    def blocks_for(self, pin, rel="ms/main.tex", changes=None):
        source, chosen = scoping.attribute_blocks(self.files, scoping.pin_facts(pin, rel), changes or [])
        return source, sorted(tuple(self.files[fi].blocks[bi]) for fi, bi in chosen)

    def test_block_is_chosen_when_the_anchor_overlaps_it_on_the_new_side(self):
        """A pin whose anchor survived the edit is placed on the new side and gets the block it overlaps."""
        # alpha was edited in place (its first 40 characters survived), so its anchor is found on the new side
        self.assertEqual(self.blocks_for(anchored(4, 4)), ("inferred", [A_BLK]))

    def test_block_is_found_through_line_shifts_from_either_side(self):
        """A stale pin keeps pre-edit numbers; mapping through the commit still finds its block despite an earlier insertion."""
        # beta's own text changed, so the pin kept its pre-edit line 11 (stale); on the new side line 11 is blank
        # (alpha's extra line shifted beta to 12). Mapping the range through the commit still finds beta's hunk.
        self.assertEqual(self.blocks_for(anchored(11, 11, stale=True, sync="lost")), ("inferred", [B_BLK]))
        # and a pin that was re-synced to the new side (line 12) lands on the same hunk
        self.assertEqual(self.blocks_for(anchored(12, 12, text=NEW)), ("inferred", [B_BLK]))

    def test_a_generic_anchor_is_placed_on_the_side_nearer_the_recorded_line(self):
        """Real-state incident: a generic anchor (\begin{equation}) must be placed by distance, not new-side-first."""
        # "\begin{equation}" is found on both sides. The pin kept old-side lines (closed before the server's checkout
        # reached the commit); on the new side the nearest equation to line 8 is a different, unchanged one (line 7).
        old = "a\n\\begin{equation}\nx=1\n\\end{equation}\nb\nc\nd\n\\begin{equation}\ny=2\n\\end{equation}\ne\n"
        new = "".join("n%d\n" % i for i in range(1, 6)) + old.replace("y=2", "y=3")
        self.files = [fc(old, new, b"@@ -0,0 +1,5 @@\n+n1\n+n2\n+n3\n+n4\n+n5\n@@ -9 +14 @@\n-y=2\n+y=3\n")]
        pin = anchored(8, 10, text=old)
        self.assertEqual(self.blocks_for(pin), ("inferred", [(8, 1, 13, 1)]))
        # recorded on the new side instead (line 13), the same anchor lands on the new side
        self.assertEqual(self.blocks_for(dict(pin, lo=13, hi=15)), ("inferred", [(8, 1, 13, 1)]))

    def test_pin_lines_are_mapped_from_splitlines_to_git_numbering(self):
        """Review finding: pins count lines with str.splitlines(), git with \n; a form feed must not shift attribution."""
        # a form feed splits a line for str.splitlines() (how pins are numbered) but not for git: line 3 of the pin is
        # git's line 2, and the change on git line 4 is the pin's line 5
        old = "a\nb\x0cc\nd\ne\n"
        new = "a\nb\x0cc\nd\nE\n"
        self.files = [fc(old, new, b"@@ -4 +4 @@\n-e\n+E\n")]
        self.assertEqual(self.blocks_for({"id": 1, "file": "/x", "lo": 5, "hi": 5}), ("inferred", [(3, 1, 3, 1)]))
        self.assertEqual(self.blocks_for({"id": 1, "file": "/x", "lo": 4, "hi": 4}), ("none", []))
        self.assertEqual(self.blocks_for(anchored(5, 5, text=old.replace("\x0c", "\n"))), ("inferred", [(3, 1, 3, 1)]))

    def test_raw_range_is_used_when_there_is_no_anchor(self):
        """Without an anchor the recorded range is read on the new side, or the old side for a stale pin."""
        self.assertEqual(self.blocks_for({"id": 1, "file": "/x", "lo": 12, "hi": 12}), ("inferred", [B_BLK]))
        self.assertEqual(self.blocks_for({"id": 1, "file": "/x", "lo": 11, "hi": 11, "stale": True}), ("inferred", [B_BLK]))
        self.assertEqual(self.blocks_for({"id": 1, "file": "/x", "lo": 7, "hi": 8}), ("none", []))

    def test_deleted_lines_are_attributed_through_the_old_side(self):
        """A pin whose text the commit deleted gets that deletion."""
        self.assertEqual(self.blocks_for(anchored(18, 18, stale=True, sync="lost")), ("inferred", [C_BLK]))

    def test_three_pins_in_one_commit_get_disjoint_hunks_that_cover_the_commit(self):
        """The issue #9 case: three pins fixed in one commit each get their own block, and together all of them."""
        pins = [anchored(4, 4), anchored(11, 11, stale=True), anchored(18, 18, stale=True)]
        got = [set(scoping.attribute_blocks(self.files, scoping.pin_facts(p, "ms/main.tex"), [])[1]) for p in pins]
        self.assertEqual([len(g) for g in got], [1, 1, 1])
        self.assertEqual(set.union(*got), {(0, 0), (0, 1), (0, 2)})

    def test_pin_matches_a_renamed_file_by_either_name_and_no_other_file(self):
        """A pin on a renamed file matches by old or new name; a pin on another file gets nothing."""
        self.assertEqual(self.blocks_for(anchored(4, 4), rel="ms/other.tex"), ("none", []))
        self.files = [fc(old_path="ms/old.tex", new_path="ms/new.tex")]
        self.assertEqual(self.blocks_for(anchored(4, 4), rel="ms/new.tex"), ("inferred", [A_BLK]))
        self.assertEqual(self.blocks_for(anchored(11, 11, stale=True), rel="ms/old.tex"), ("inferred", [B_BLK]))

    def test_recorded_changes_win_over_inference_unless_they_hit_nothing(self):
        """Layer 2 before layer 3: recorded changes decide, and ranges that hit no block fall back to inference."""
        pin = anchored(4, 4)
        self.assertEqual(self.blocks_for(pin, changes=[scoping.RepoRange("ms/main.tex", 12, 12)]), ("changes", [B_BLK]))
        # the line after a deletion names the deletion
        self.assertEqual(self.blocks_for(pin, changes=[("ms/main.tex", 19, 19)]), ("changes", [C_BLK]))
        self.assertEqual(self.blocks_for(pin, changes=[("ms/main.tex", 4, 5), ("ms/main.tex", 12, 12)]),
                         ("changes", [A_BLK, B_BLK]))
        # ranges that hit nothing in this commit (a different commit, a wrong file) fall back to inference
        self.assertEqual(self.blocks_for(pin, changes=[("ms/main.tex", 7, 8)]), ("inferred", [A_BLK]))
        self.assertEqual(self.blocks_for(pin, changes=[("ms/x.tex", 4, 5)]), ("inferred", [A_BLK]))

    def test_a_region_pin_or_a_pin_without_lines_gets_nothing(self):
        """A view-only PDF pin has no lines, so it is never attributed (whole commit)."""
        self.assertEqual(self.blocks_for({"id": 1, "pdf": "/x.pdf", "page": 1, "frac": [0, 0, 1, 1]}, rel=None), ("none", []))


class ScopedPatch(unittest.TestCase):
    """The pin's / the other blocks rendered as git-style patches with the commit's real line numbers (pure)."""

    def setUp(self):
        self.files = [fc()]

    def test_payload_cuts_patches_in_bytes_and_says_so(self):
        """Review finding: scoped patches are cut at 256 KiB in UTF-8 bytes and flagged, like the whole diff."""
        big = "".join("줄 %d 한국어 문장입니다\n" % i for i in range(20000))
        f = fc(big, big.replace("줄 5 ", "줄 5! "), b"@@ -6 +6 @@\n", old_path="ms/big.tex", new_path="ms/big.tex")
        files = [f, fc()]
        sc = scoping.pin_scope(files, scoping.pin_facts({"id": 1, "file": "/x", "lo": 2, "hi": 2}, "ms/main.tex"), [scoping.RepoRange("ms/main.tex", 12, 12)])
        out = scoping.scope_payload(sc)
        self.assertEqual((out["mode"], out["truncated"], out["other_truncated"]), ("pin", False, False))
        f = fc(big, big.replace("\n", " x\n"), b"@@ -1,20000 +1,20000 @@\n", old_path="ms/big.tex", new_path="ms/big.tex")
        sc = scoping.pin_scope([f, fc()], scoping.pin_facts({"id": 1, "file": "/x", "lo": 2, "hi": 2}, "ms/main.tex"), [scoping.RepoRange("ms/main.tex", 12, 12)])
        out = scoping.scope_payload(sc)
        self.assertTrue(out["other_truncated"])
        self.assertLessEqual(len(out["other_diff"].encode()), scoping.REVISION_DIFF_MAX)

    def test_pin_hunk_keeps_real_new_side_line_numbers_and_no_foreign_lines(self):
        """The pin's hunk shows the commit's real new-side numbers (so highlighting works) and none of another pin's lines."""
        text, n = scoping.scoped_patch(self.files, {(0, 1)}, True)
        self.assertEqual(n, 1)
        self.assertEqual(text, "diff --git a/ms/main.tex b/ms/main.tex\n--- a/ms/main.tex\n+++ b/ms/main.tex\n"
                               "@@ -8,7 +9,7 @@\n Filler three.\n Filler four.\n \n-Beta paragraph talks about bananas.\n"
                               "+Beta paragraph talks about blueberries.\n \n Filler five.\n Filler six.\n")
        other, n_other = scoping.scoped_patch(self.files, {(0, 1)}, False)
        self.assertEqual(n_other, 2)
        self.assertIn("+A second alpha sentence.", other)
        self.assertIn("-Gamma paragraph talks about cherries.", other)
        self.assertNotIn("Beta", other)

    def test_context_stops_at_a_foreign_block_and_close_pin_blocks_merge(self):
        """Context never shows another pin's change; two close blocks of the same pin share one hunk."""
        old = "".join("l%d\n" % i for i in range(1, 11))
        new = old.replace("l3\n", "L3\n").replace("l5\n", "L5\n").replace("l7\n", "L7\n")
        patch = b"@@ -3 +3 @@\n-l3\n+L3\n@@ -5 +5 @@\n-l5\n+L5\n@@ -7 +7 @@\n-l7\n+L7\n"
        files = [fc(old, new, patch)]
        text, n = scoping.scoped_patch(files, {(0, 0), (0, 2)}, True)
        self.assertEqual(n, 2)                                     # l5 (someone else's) splits them
        self.assertNotIn("l5", text)
        self.assertNotIn("L5", text)
        self.assertIn("@@ -1,4 +1,4 @@\n l1\n l2\n-l3\n+L3\n l4\n", text)
        self.assertIn("@@ -6,5 +6,5 @@\n l6\n-l7\n+L7\n l8\n l9\n l10\n", text)
        text, n = scoping.scoped_patch(files, {(0, 0), (0, 1)}, True)
        self.assertEqual(n, 2)                                     # two changed spots, shown in one hunk
        self.assertEqual(text.count("@@ -"), 1)
        self.assertIn("@@ -1,6 +1,6 @@\n l1\n l2\n-l3\n+L3\n l4\n-l5\n+L5\n l6\n", text)

    def test_missing_final_newline_is_marked_like_git(self):
        """A last line without a newline gets git's marker in both - and + forms."""
        files = [fc("a\nb", "a\nc", b"@@ -2 +2 @@\n-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n")]
        text, _ = scoping.scoped_patch(files, {(0, 0)}, True)
        self.assertTrue(text.endswith("-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n"), text)

    def test_file_headers_name_new_deleted_and_renamed_files_like_git(self):
        """Scoped patches keep git's file headers so the viewer's file list and names still work."""
        files = [fc("", "x\n", b"@@ -0,0 +1 @@\n+x\n", old_path=None, new_path="ms/n.tex"),
                 fc("y\n", "", b"@@ -1 +0,0 @@\n-y\n", old_path="ms/d.tex", new_path=None),
                 fc(OLD, NEW, U0, old_path="ms/a.tex", new_path="ms/b.tex")]
        text, n = scoping.scoped_patch(files, {(0, 0), (1, 0), (2, 0)}, True)
        self.assertIn("diff --git a/ms/n.tex b/ms/n.tex\nnew file mode 100644\n--- /dev/null\n+++ b/ms/n.tex\n@@ -0,0 +1,1 @@\n+x\n", text)
        self.assertIn("diff --git a/ms/d.tex b/ms/d.tex\ndeleted file mode 100644\n--- a/ms/d.tex\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-y\n", text)
        self.assertIn("diff --git a/ms/a.tex b/ms/b.tex\nrename from ms/a.tex\nrename to ms/b.tex\n--- a/ms/a.tex\n+++ b/ms/b.tex\n", text)
        self.assertEqual(n, 3)

    def test_rename_only_and_binary_files_count_as_other_places(self):
        """A pure rename or a binary file is never the pin's; it is one of the "other changes"."""
        files = [fc(), scoping.FileChange("ms/fig.tex", "ms/fig2.tex", (), (), (), False),
                 scoping.FileChange("ms/x.bib", "ms/x.bib", (), (), (), True)]
        text, n = scoping.scoped_patch(files, {(0, 0), (0, 1), (0, 2)}, False)
        self.assertEqual(n, 2)
        self.assertIn("rename from ms/fig.tex", text)
        self.assertIn("Binary files a/ms/x.bib and b/ms/x.bib differ", text)


class ScopeDecisions(unittest.TestCase):
    """The pure decisions around the scoped build and responses (coding rule R1): which recorded changes count, what to
    write into the synthetic tree, and how a refusal becomes a response - no file, git or HTTP needed."""

    def test_recorded_changes_count_only_for_their_close_and_their_commit(self):
        """changes_at must equal done_at, and the commit asked about must be the one close_ref names (review M1:
        another commit's lines must not select a different pin's fix); malformed items are skipped."""
        good = {"file": "/m/main.tex", "lo": 3, "hi": 4}
        X, Y = "a" * 40, "b" * 40
        revs = [{"id": Y, "subject": "fix B (#8)"}, {"id": X, "subject": "fix A (#7)"}]
        pin = {"done_at": "2026-09-25 10:00:00", "changes_at": "2026-09-25 10:00:00", "close_ref": "PR #7 (%s)" % X[:7],
               "changes": [good, {"file": 3, "lo": 1, "hi": 1}]}
        self.assertEqual(scoping.recorded_changes(pin, X, revs), (good,))
        self.assertEqual(scoping.recorded_changes(pin, Y, revs), ())                      # another commit: inference decides
        self.assertEqual(scoping.recorded_changes(dict(pin, close_ref="PR #7"), X, revs), (good,))   # the squash commit by PR
        self.assertEqual(scoping.recorded_changes(dict(pin, close_ref="PR #7 (cccc111)"), X, revs), (good,))
        self.assertEqual(scoping.recorded_changes(dict(pin, close_ref=""), X, revs), ())
        self.assertEqual(scoping.recorded_changes(dict(pin, done_at="2026-09-26 09:00:00"), X, revs), ())
        self.assertEqual(scoping.recorded_changes({"done_at": "2026-09-25 10:00:00"}, X, revs), ())
        self.assertEqual(scoping.recorded_changes({}, X, revs), ())

    def test_ref_commit_matches_the_viewers_match_revision(self):
        """The server binds changes with the same rule the viewer uses to pick the commit (matchRevision): hash prefix
        first, then the PR number in the subject. Both implementations answer every case alike."""
        revs = [{"id": "0a569cc" + "1" * 33, "subject": "Clarify experimental questions (#238)"},
                {"id": "2cb7240" + "2" * 33, "subject": "Resolve manuscript viewer pins 19–41 (#236)"},
                {"id": "f47c6bf" + "3" * 33, "subject": "manuscript: 원고 핀 12건 반영 (#235)"},
                {"id": "1d422a6" + "4" * 33, "subject": "Merge pull request #203 from example-lab/docs"}]
        refs = ["PR #235 (f47c6bf)", "paper PR #236; code PR #75", "paper PR #236", "#203", "PR #999", "", "abcdef1",
                "커밋f47c6bf", "PR #236 (deadbee)", None]
        py = [scoping.ref_commit(r, revs) for r in refs]
        self.assertEqual([x and x[:7] for x in py], ["f47c6bf", "2cb7240", "2cb7240", "1d422a6", None, None, None,
                                                     "f47c6bf", "2cb7240", None])
        if shutil.which("node"):
            js = run_node(extract_js_fn("matchRevision") + "\nconsole.log(JSON.stringify(%s.map(r=>{const m=matchRevision(r,%s);"
                          "return m&&m.id;})));" % (json.dumps(refs), json.dumps(revs)))
            self.assertEqual(json.loads(js), py)

    def test_raw_entries_of_symlinks_and_submodules_have_no_blocks(self):
        """Review m6: --raw modes 120000 (symlink) and 160000 (submodule) are never read as text; the whole-commit
        snapshot rejects them, so the pin view must not turn them into editable blocks either."""
        z = "0" * 40
        raw = (b":100644 120000 " + (b"1" * 40) + b" " + (b"2" * 40) + b" T\0ms/sec.tex\0"
               b":000000 160000 " + z.encode() + b" " + (b"3" * 40) + b" A\0ms/sub\0"
               b":100644 100644 " + (b"4" * 40) + b" " + (b"5" * 40) + b" R087\0ms/a.tex\0ms/b.tex\0")
        got = scoping.parse_raw_entries(raw)
        self.assertEqual([(e.old_path, e.new_path, e.text) for e in got],
                         [("ms/sec.tex", "ms/sec.tex", False), (None, "ms/sub", False), ("ms/a.tex", "ms/b.tex", True)])
        self.assertEqual(got[0].modes, ("100644", "120000"))

    def test_scope_writes_apply_only_the_scope_under_the_build_root(self):
        """Only the scope's blocks are applied, files outside the build root are skipped, a deleted file is removed."""
        f = fc(old_path="ms/main.tex", new_path="ms/main.tex")
        outside = fc(old_path="other/x.tex", new_path="other/x.tex")
        gone = scoping.FileChange("ms/old.tex", None, (b"x\n",), (), (scoping.Block(0, 1, 0, 0),), False)
        scope = [("ms/main.tex", "ms/main.tex") + B_BLK, ("other/x.tex", "other/x.tex") + A_BLK, ("ms/old.tex", "") + (0, 1, 0, 0)]
        writes = scoping.plan_scope_writes([f, outside, gone], scope, "ms")
        self.assertEqual(writes, [scoping.ScopeWrite("main.tex", OLD.replace("bananas", "blueberries").encode()),
                                  scoping.ScopeWrite("old.tex", None)])
        self.assertEqual(scoping.plan_scope_writes([f], [("ms/main.tex", "ms/main.tex") + A_BLK], ".")[0].rel, "ms/main.tex")

    def test_scope_writes_refuse_unreadable_unsafe_and_missing_blocks(self):
        """Each refusal is its own returned value: no files, a path that could leave the snapshot, a block not found again."""
        f = fc()
        cases = ((None, [("ms/main.tex", "ms/main.tex") + A_BLK], scoping.ScopeUnreadable()),
                 ([f], [("ms/main.tex", "ms/main.tex") + (0, 1, 0, 1)], scoping.ScopeMismatch()))
        for files, scope, refusal in cases:
            with self.subTest(refusal=refusal):
                self.assertEqual(scoping.plan_scope_writes(files, scope, "ms"), refusal)
        for bad in ("ms/../x.tex", "ms/.git/config", "ms/a\\b.tex", "ms/\x01.tex"):
            with self.subTest(path=bad):
                self.assertEqual(scoping.plan_scope_writes([f._replace(old_path=bad, new_path=bad)], [(bad, bad) + A_BLK], "ms"),
                                 scoping.UnsafePath())

    def test_every_rejection_maps_to_one_status_and_body(self):
        """The one SCOPE_REJECTIONS table: status, Korean message and API reason per refusal type (agent contract), one
        row for every member of limn.scope.ScopeRefusal. The 404 gained its reason in 0.3.4 (every refusal names one,
        tests/test_errors.py); its text is unchanged."""
        want = {scoping.PinNotInDoc: (404, {"error": "이 문서의 핀이 아닙니다.", "reason": "pin_not_in_doc"}),
                scoping.ScopeUnreadable: (422, {"error": "이 핀의 변경만 골라 적용하지 못했습니다.", "reason": "scope_failed"}),
                scoping.ScopeMismatch: (422, {"error": "이 핀의 변경을 커밋에서 다시 찾지 못했습니다.", "reason": "scope_failed"}),
                scoping.UnsafePath: (422, {"error": "사본에 허용되지 않는 경로가 있습니다.", "reason": "unsafe_snapshot"}),
                scoping.ScopeUnwritable: (422, {"error": "이 핀의 변경만 넣은 사본을 쓰지 못했습니다.", "reason": "scope_failed"})}
        self.assertEqual(set(SCOPE_REJECTIONS), set(want))
        self.assertEqual(set(SCOPE_REJECTIONS), set(typing.get_args(scoping.ScopeRefusal)))
        for kind, (code, body) in want.items():
            e = scope_http_error(kind())
            self.assertEqual((e.code, e.body), (code, body))

    def test_scope_meta_and_payload_have_their_documented_keys(self):
        """ScopeMeta has the five status fields; the payload adds the patches only in mode pin."""
        sc = scoping.pin_scope([fc()], scoping.pin_facts(dict(anchored(4, 4), id=7), "ms/main.tex"), [])
        self.assertEqual(scoping.scope_meta(sc), {"scope": "pin", "pin": 7, "source": "inferred", "hunks": 1, "other": 2})
        self.assertEqual(sorted(scoping.scope_payload(sc)), ["diff", "hunks", "mode", "other", "other_diff", "other_truncated",
                                                        "pin", "source", "truncated"])
        whole = scoping.pin_scope(None, scoping.pin_facts(dict(anchored(4, 4), id=7), "ms/main.tex"), [])
        self.assertEqual(scoping.scope_payload(whole), {"pin": 7, "mode": "commit", "source": "none", "hunks": 0, "other": 0})


class ApplyBlocks(unittest.TestCase):
    """The synthetic old + chosen blocks version the scoped comparison PDF compiles (pure)."""

    def test_synthetic_new_version_is_old_plus_only_the_chosen_blocks(self):
        """The comparison PDF's new side is exactly old + the chosen blocks (all = new, none = old)."""
        f = fc()
        self.assertEqual(scoping.apply_blocks(f, {0, 1, 2}), NEW.encode())
        self.assertEqual(scoping.apply_blocks(f, set()), OLD.encode())
        self.assertEqual(scoping.apply_blocks(f, {1}), OLD.replace("bananas", "blueberries").encode())
        self.assertEqual(scoping.apply_blocks(f, {2}), OLD.replace("Gamma paragraph talks about cherries.\n", "").encode())

    def test_apply_keeps_a_missing_final_newline(self):
        """Applying a block to a file without a final newline reproduces the new bytes exactly."""
        f = fc("a\nb", "a\nc", b"@@ -2 +2 @@\n-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n")
        self.assertEqual(scoping.apply_blocks(f, {0}), b"a\nc")


@unittest.skipUnless(shutil.which("git"), "git not available")
class GitBlocks(unittest.TestCase):
    """The parser against what real git prints, and a seeded property check: any subset applied, then the rest, is the new file."""

    def u0(self, old: bytes, new: bytes) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d, "a"), Path(d, "b")
            a.write_bytes(old)
            b.write_bytes(new)
            # --no-index exits 1 when the files differ, which is the normal case here
            r = subprocess.run(["git", "diff", "--no-index", "--no-color", "-U0", str(a), str(b)], capture_output=True, check=False)
            return r.stdout

    def git_apply(self, old: bytes, patch: str) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            Path(d, "m.tex").write_bytes(old)
            subprocess.run(["git", "apply", "--unidiff-zero", "-"], cwd=d, input=patch.encode(), check=True, capture_output=True)
            return Path(d, "m.tex").read_bytes()

    def test_fixture_blocks_match_what_git_prints(self):
        """The hand-written fixture hunks are what real git prints for OLD -> NEW."""
        self.assertEqual([tuple(b) for b in scoping.parse_u0_blocks(self.u0(OLD.encode(), NEW.encode()))], [A_BLK, B_BLK, C_BLK])

    def test_random_edits_round_trip_through_apply_and_git_apply(self):
        """Seeded property check: any subset applies as defined, and git apply of its scoped patch gives the same bytes."""
        rnd = random.Random(20260925)
        for _ in range(60):
            old = [("w%d %s\n" % (rnd.randrange(30), "x" * rnd.randrange(3))) for _ in range(rnd.randrange(0, 40))]
            new = list(old)
            for _ in range(rnd.randrange(1, 6)):
                op, i = rnd.randrange(3), rnd.randrange(len(new) + 1)
                if op == 0:
                    new.insert(i, "ins%d\n" % rnd.randrange(1000))
                elif new and i < len(new):
                    if op == 1:
                        del new[i]
                    else:
                        new[i] = "chg%d\n" % rnd.randrange(1000)
            o, n = "".join(old).encode(), "".join(new).encode()
            if rnd.random() < 0.3 and n.endswith(b"\n"):
                n = n[:-1]
            f = scoping.FileChange("m.tex", "m.tex", scoping.git_lines(o), scoping.git_lines(n), tuple(scoping.parse_u0_blocks(self.u0(o, n))), False)
            self.assertEqual(scoping.apply_blocks(f, set(range(len(f.blocks)))), n)
            self.assertEqual(scoping.apply_blocks(f, set()), o)
            if f.blocks:
                # any subset: old outside the chosen blocks, new inside them, in order
                chosen = {k for k in range(len(f.blocks)) if rnd.random() < 0.5}
                want, pos = [], 0
                for k, b in enumerate(f.blocks):
                    if k in chosen:
                        want += f.old[pos:b.old_lo] + f.new[b.new_lo:b.new_lo + b.new_n]
                        pos = b.old_lo + b.old_n
                self.assertEqual(scoping.apply_blocks(f, chosen), b"".join(want + list(f.old[pos:])))
                # and the scoped patch of those blocks, applied by git to old, gives exactly that
                text, _ = scoping.scoped_patch([f], {(0, k) for k in chosen}, True)
                if chosen:
                    self.assertEqual(self.git_apply(o, text), scoping.apply_blocks(f, chosen))


# ---------------------------------------------------------------- 2. the close contract: optional `changes`

class CloseChanges(AccessBase):
    """The optional `changes` on POST /api/pins/{id}/close: validation, storage, reopen, pins.md."""

    def setUp(self):
        super().setUp()
        (self.src / "sec").mkdir()
        (self.src / "sec" / "a.tex").write_text("x\n" * 30)
        self.pid = self.add()

    def close(self, body):
        return self.call("POST", "/api/pins/%d/close" % self.pid, body)

    def test_valid_changes_are_stored_as_absolute_paths_and_exposed(self):
        """A valid changes list is stored resolved and absolute on the first close and appears in the pins API."""
        code, d = self.close({"reply": "fixed", "ref": "abc1234", "changes": [
            {"file": "main.tex", "lo": 4, "hi": 5}, {"file": str(self.src / "sec" / "a.tex"), "lo": 7, "hi": 7}]})
        self.assertEqual(code, 200, d)
        want = [{"file": str(self.main.resolve()), "lo": 4, "hi": 5}, {"file": str((self.src / "sec" / "a.tex").resolve()), "lo": 7, "hi": 7}]
        self.assertEqual(d["pin"]["changes"], want)
        code, d = self.call("GET", "/api/pins/%d" % self.pid)
        self.assertEqual(d["pin"]["changes"], want)
        code, d = self.call("GET", "/api/pins?all=1")
        self.assertEqual([p.get("changes") for p in d if p["id"] == self.pid], [want])
        self.assertTrue(ps.valid_rec(self.pin(self.pid)))

    def test_invalid_changes_are_rejected_with_400_and_change_nothing(self):
        """Each malformed changes item or list is a 400 and leaves the pin open (boundary validation)."""
        bad = [{"file": "main.tex", "lo": 5, "hi": 4}, {"file": "main.tex", "lo": 0, "hi": 1}, {"file": "main.tex", "lo": 1.5, "hi": 2},
               {"file": "main.tex", "lo": True, "hi": 2}, {"file": "main.tex", "lo": "1", "hi": 2}, {"file": "main.tex", "lo": 1},
               {"file": "", "lo": 1, "hi": 1}, {"file": 3, "lo": 1, "hi": 1}, {"file": "../outside.tex", "lo": 1, "hi": 1},
               {"file": "/etc/passwd", "lo": 1, "hi": 1}, {"file": "main.tex", "lo": 1, "hi": 1, "extra": 1},
               {"file": "main.tex", "lo": 1, "hi": 10 ** 7}, {"file": "a\x00b", "lo": 1, "hi": 1}, "main.tex:1-2"]
        for item in bad:
            with self.subTest(item=item):
                code, d = self.close({"changes": [item]})
                self.assertEqual(code, 400, d)
                self.assertFalse(self.pin(self.pid).get("done"))
        for whole in ({"file": "main.tex", "lo": 1, "hi": 1}, "x", [{"file": "main.tex", "lo": 1, "hi": 1}] * (parse.CLOSE_CHANGES_MAX + 1)):
            with self.subTest(whole=str(whole)[:40]):
                code, d = self.close({"changes": whole})
                self.assertEqual(code, 400, d)
        self.assertFalse(self.pin(self.pid).get("done"))

    def test_absent_or_empty_changes_close_like_0_2_2(self):
        """Old agents: a close without changes (or with []) stores nothing new."""
        code, d = self.close({"changes": []})
        self.assertEqual(code, 200)
        self.assertNotIn("changes", d["pin"])
        other = self.add(lo=8, hi=9)
        code, d = self.call("POST", "/api/pins/%d/close" % other)
        self.assertEqual((code, "changes" in d["pin"]), (200, False))

    def test_reclose_keeps_and_reopen_clears_changes(self):
        """Changes follow close_reply/close_ref: the first close wins, a reopen clears them."""
        self.close({"changes": [{"file": "main.tex", "lo": 4, "hi": 5}]})
        self.close({"changes": [{"file": "main.tex", "lo": 9, "hi": 9}]})
        self.assertEqual(self.pin(self.pid)["changes"][0]["lo"], 4)
        self.call("POST", "/api/pins/%d/reopen" % self.pid, {})
        self.assertNotIn("changes", self.pin(self.pid))

    def test_a_malformed_stored_changes_field_marks_the_line_broken(self):
        """valid_rec() rejects a record whose stored changes have the wrong shape."""
        r = dict(self.pin(self.pid), changes=[{"file": 3, "lo": 1, "hi": 2}])
        self.assertFalse(ps.valid_rec(r))
        self.assertTrue(ps.valid_rec(dict(r, changes=[{"file": "/a.tex", "lo": 1, "hi": 2}])))

    def test_pins_md_close_instruction_line_asks_for_changes_and_the_merged_commit(self):
        """Owner decision (review of #13): the close line asks for changes and ref = PR #N (hash); the rest of the line is 0.2.2's."""
        # decided after review (ADR-0005, accepted): paper repos squash-merge and agents close after the merge, so the
        # line asks for `changes` in the numbering of the commit `ref` names, and ref = "PR #N (<hash>)"; per-pin commits
        # help but are optional
        text = ps.pins_md_text(ps.snapshot_pins())
        line = next(ln for ln in text.splitlines() if ln.startswith("처리한 핀은 닫는다"))
        self.assertTrue(line.startswith('처리한 핀은 닫는다 — 닫을 때 `changes` 에 이 핀 때문에 바꾼 줄 범위를, `ref` 에 `PR #번호 (커밋 해시)` 를 적는다: `curl'), line)
        self.assertIn('"ref":"PR #12 (커밋 해시)","changes":[{"file":"main.tex","lo":12,"hi":14}]}' + "' http://127.0.0.1:18999/api/pins/N/close`", line)
        self.assertIn('(본문 생략 가능, 그러면 옛 방식처럼 사유 없이 닫힘. `changes` 의 줄 번호는 `ref` 의 커밋이 만든 판 기준 — 스쿼시 머지 뒤 닫으면 머지된 main 기준, 경로는 위치 칸 기준. 핀마다 커밋을 나누면 더 좋지만 필수는 아니다)' + " · 줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다 · '질문' 핀은 원고를 고치지 말고", line)
        self.assertNotIn("스쿼시하지", line)
        self.assertTrue(line.endswith("에이전트는 확인(confirm)하지 않는다 — `/api/pins/N/confirm` 은 사람 신원(테일넷 헤더)이 없으면 403"))


# ---------------------------------------------------------------- 3. the pin-scoped source diff and comparison PDF (server)

class ScopedRepo(AccessBase):
    """A git repo whose second commit fixes three pins at once (alpha: recorded `changes`; beta and gamma: inferred),
    and a third commit that belongs entirely to a fourth pin."""

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.main.write_text(OLD, encoding="utf-8")
        self.git("init", "--quiet")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.commit("first")
        self.p1 = self.add(lo=4, hi=4, note="alpha")
        self.p2 = self.add(lo=11, hi=11, note="beta")
        self.p3 = self.add(lo=18, hi=18, note="gamma")
        self.write(NEW)
        self.fix = self.commit("fix three pins")
        self.call("POST", "/api/pins/%d/close" % self.p1,
                  {"ref": self.fix[:8], "changes": [{"file": "main.tex", "lo": 4, "hi": 5}]})
        self.call("POST", "/api/pins/%d/close" % self.p2, {"ref": self.fix[:8]})
        self.call("POST", "/api/pins/%d/close" % self.p3, {"ref": self.fix[:8]})
        self.p4 = self.add(lo=8, hi=8, note="filler")
        self.write(NEW.replace("Filler two.", "Filler two, reworded."))
        self.solo = self.commit("fix the filler pin")
        self.call("POST", "/api/pins/%d/close" % self.p4, {"ref": self.solo[:8]})

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def write(self, text):
        self.main.write_text(text, encoding="utf-8")
        t = time.time() + 5
        os.utime(self.main, (t, t))

    def commit(self, msg):
        self.git("add", "ms")
        self.git("commit", "--quiet", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()

    def diff(self, commit, pin=None):
        q = "/api/revision-diff?commit=%s" % commit + ("&pin=%s" % pin if pin is not None else "")
        return self.call("GET", q)

    def diff_ok(self, commit, pin=None):
        """The body of a revision-diff request that must succeed. A failure shows the server's answer; a 500 used to
        surface only as KeyError: 'scope'."""
        code, d = self.diff(commit, pin)
        self.assertEqual(code, 200, d)
        return d


class ScopedSourceDiff(ScopedRepo):
    """GET /api/revision-diff?pin= over a real git repository."""

    def test_each_pin_sees_only_its_hunks_and_the_rest_folded(self):
        """The issue #9 case over HTTP: each of three pins in one commit gets only its hunk; the rest is in other_diff."""
        want = {self.p1: ("changes", "apples and pears", ("blueberries", "Gamma")),
                self.p2: ("inferred", "blueberries", ("pears", "Gamma")),
                self.p3: ("inferred", "Gamma", ("pears", "blueberries"))}
        for pid, (source, mine, others) in want.items():
            with self.subTest(pin=pid):
                code, d = self.diff(self.fix, pid)
                self.assertEqual(code, 200, d)
                s = d["scope"]
                self.assertEqual((s["pin"], s["mode"], s["source"], s["hunks"], s["other"]), (pid, "pin", source, 1, 2))
                self.assertIn(mine, s["diff"])
                for o in others:
                    self.assertNotIn(o, s["diff"])
                    self.assertIn(o, s["other_diff"])
                self.assertIn("pears", d["diff"])                  # the whole-commit diff is still there, unchanged
                self.assertIn("blueberries", d["diff"])

    def test_scoped_hunk_header_keeps_the_commits_line_numbers(self):
        """The scoped hunk of a pin after an insertion carries the commit's real new-side numbers."""
        d = self.diff_ok(self.fix, self.p2)
        self.assertIn("@@ -8,7 +9,7 @@", d["scope"]["diff"])

    def test_a_commit_that_belongs_entirely_to_the_pin_is_shown_whole(self):
        """A commit that is all the pin's is mode commit: the viewer shows it as in 0.2.2 without extra controls."""
        d = self.diff_ok(self.solo, self.p4)
        s = d["scope"]
        self.assertEqual((s["mode"], s["hunks"], s["other"]), ("commit", 1, 0))
        self.assertNotIn("other_diff", s)

    def test_a_pin_the_commit_does_not_touch_gets_the_whole_commit(self):
        """A commit that touches none of the pin is mode commit with source none (0.2.2 view)."""
        d = self.diff_ok(self.solo, self.p2)
        self.assertEqual((d["scope"]["mode"], d["scope"]["source"], d["scope"]["hunks"]), ("commit", "none", 0))

    def test_revision_diff_without_pin_has_the_0_2_2_fields_only(self):
        """Backward compatibility: without ?pin= the response keys are exactly 0.2.2's."""
        code, d = self.diff(self.fix)
        self.assertEqual((code, sorted(d)), (200, ["diff", "id", "truncated"]))

    def test_diff_inter_hunk_context_config_cannot_merge_two_pins_blocks(self):
        """Review finding: a user's diff.interHunkContext must not glue two pins' blocks together."""
        # diff.interHunkContext would glue nearby -U0 hunks together and give both pins both edits
        self.git("config", "diff.interHunkContext", "10")
        ps.SCOPE_CACHE.clear()
        d = self.diff_ok(self.fix, self.p2)
        self.assertEqual((d["scope"]["hunks"], d["scope"]["other"]), (1, 2))
        self.assertNotIn("pears", d["scope"]["diff"])

    def test_malformed_pin_is_400_and_unknown_pin_is_404(self):
        """The pin parameter is validated (400) and must be a pin of this document (404)."""
        self.assertEqual(self.diff(self.fix, "x")[0], 400)
        self.assertEqual(self.diff(self.fix, "-1")[0], 400)
        self.assertEqual(self.diff(self.fix, "999")[0], 404)

    def test_pin_on_a_file_renamed_in_the_commit_gets_its_edit_only(self):
        """A rename with an edit is attributed to a pin naming either file name; the other file's change stays other."""
        part = self.src / "part.tex"
        part.write_text("".join("Part line %d.\n" % i for i in range(1, 21)), encoding="utf-8")
        self.write(NEW.replace("Filler two.", "Filler two, reworded.").replace("\\end{document}", "\\input{part}\n\\end{document}"))
        self.commit("add a part")
        old_pin = self.add(lo=12, hi=12, note="part twelve")
        rows = ps.snapshot_pins()
        ps.find_pin(rows, old_pin)["file"] = str(part)
        ps.find_pin(rows, old_pin)["anchor"] = ps.anchor_of(part.read_text().split("\n"), 12, 12)
        ps.write_pins(rows)
        self.git("mv", "ms/part.tex", "ms/chapter.tex")
        chapter = self.src / "chapter.tex"
        chapter.write_text(chapter.read_text().replace("Part line 12.", "Part line twelve."), encoding="utf-8")
        self.write(self.main.read_text().replace("\\input{part}", "\\input{chapter}"))
        mv = self.commit("rename the part")
        ps.set_done(old_pin, True, dict(ps.LOCAL_ACTOR), ref=mv[:8])
        new_pin = self.add(lo=12, hi=12, note="chapter twelve")
        rows = ps.snapshot_pins()
        ps.find_pin(rows, new_pin)["file"] = str(chapter)
        ps.write_pins(rows)
        ps.set_done(new_pin, True, dict(ps.LOCAL_ACTOR), ref=mv[:8])
        for pid in (old_pin, new_pin):              # the pin may name the file before or after the rename
            with self.subTest(pin=pid):
                d = self.diff_ok(mv, pid)
                s = d["scope"]
                self.assertEqual((s["mode"], s["hunks"], s["other"]), ("pin", 1, 1))
                self.assertIn("diff --git a/ms/part.tex b/ms/chapter.tex\nrename from ms/part.tex\nrename to ms/chapter.tex\n", s["diff"])
                self.assertIn("+Part line twelve.", s["diff"])
                self.assertNotIn("input", s["diff"])
                self.assertIn("+\\input{chapter}", s["other_diff"])


class SquashMergedPins(AccessBase):
    """The owner's workflow (ADR-0005, accepted): a PR fixes three pins, is squash-merged into one commit on main, and
    only then does the agent close each pin with ref = "PR #7 (<squash hash>)" and `changes` in the squash commit's
    new-side numbers. Beta's fix is a sentence added two lines below the pin, which the pin's own range cannot find -
    only the recorded `changes` can. A fourth change in the same commit belongs to no pin."""

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.main.write_text(OLD, encoding="utf-8")
        for args in (("init", "--quiet"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T"),
                     ("add", "ms"), ("commit", "--quiet", "-m", "first")):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.pins = [self.add(lo=4, hi=4, note="alpha"), self.add(lo=11, hi=11, note="beta"),
                     self.add(lo=18, hi=18, note="gamma")]
        new = (OLD.replace("Alpha paragraph talks about apples.", "Alpha paragraph talks about pears.")
                  .replace("Filler five.\n", "Filler five.\nBeta follow-up sentence.\n")
                  .replace("Filler seven.", "Filler 7.")
                  .replace("Gamma paragraph talks about cherries.", "Gamma paragraph talks about plums."))
        self.main.write_text(new, encoding="utf-8")
        t = time.time() + 5
        os.utime(self.main, (t, t))
        for args in (("add", "ms"), ("commit", "--quiet", "-m", "Resolve pins 1-3 (#7)")):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.squash = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.ref = "PR #7 (%s)" % self.squash[:7]
        lines = new.split("\n")
        self.new_lines = {"alpha": lines.index("Alpha paragraph talks about pears.") + 1,
                          "beta": lines.index("Beta follow-up sentence.") + 1,
                          "gamma": lines.index("Gamma paragraph talks about plums.") + 1}
        self.assertEqual(self.new_lines, {"alpha": 4, "beta": 14, "gamma": 19})
        for pid, key in zip(self.pins, ("alpha", "beta", "gamma"), strict=True):
            n = self.new_lines[key]
            code, d = self.call("POST", "/api/pins/%d/close" % pid, {
                "reply": key, "ref": self.ref, "changes": [{"file": "main.tex", "lo": n, "hi": n}]})
            self.assertEqual(code, 200, d)

    def test_each_pin_sees_its_own_change_in_the_squash_commit(self):
        """Owner workflow: squash commit of 3 pins, closed after the merge with changes in its numbers - each sees its own change."""
        want = {"alpha": ("+Alpha paragraph talks about pears.", ("follow-up", "plums", "Filler 7"))
                , "beta": ("+Beta follow-up sentence.", ("pears", "plums", "Filler 7")),
                "gamma": ("+Gamma paragraph talks about plums.", ("pears", "follow-up", "Filler 7"))}
        for pid, key in zip(self.pins, ("alpha", "beta", "gamma"), strict=True):
            with self.subTest(pin=key):
                code, d = self.call("GET", "/api/revision-diff?commit=%s&pin=%d" % (self.squash, pid))
                self.assertEqual(code, 200, d)
                s = d["scope"]
                self.assertEqual((s["mode"], s["source"], s["hunks"], s["other"]), ("pin", "changes", 1, 3))
                mine, others = want[key]
                self.assertIn(mine, s["diff"])
                for o in others:
                    self.assertNotIn(o, s["diff"])
                    self.assertIn(o, s["other_diff"])
                spec = revision_spec(self.squash, pid)
                self.assertEqual(len(spec.scope), 1)

    def test_fix_next_to_the_pin_needs_changes_else_whole_commit(self):
        """Why agents always send changes: inference (overlap only) cannot find a fix placed next to the pin."""
        # the reason `changes` is what agents should send: beta's own range does not touch its fix
        rows = ps.snapshot_pins()
        r = ps.find_pin(rows, self.pins[1])
        r.pop("changes")
        ps.write_pins(rows)
        _, d = self.call("GET", "/api/revision-diff?commit=%s&pin=%d" % (self.squash, self.pins[1]))
        self.assertEqual((d["scope"]["mode"], d["scope"]["source"]), ("commit", "none"))

    def test_viewer_finds_the_squash_commit_from_a_pr_and_hash_ref(self):
        """The viewer's matchRevision picks the merged commit from ref = PR #N (hash)."""
        if not shutil.which("node"):
            self.skipTest("node not available")
        revs = ps.revision_history(ps.DOCS[0])["revisions"]
        out = run_node(extract_js_fn("matchRevision") + "\nconsole.log(JSON.stringify(matchRevision(%s,%s)));"
                       % (json.dumps(self.ref), json.dumps(revs)))
        self.assertEqual(json.loads(out)["id"], self.squash)


class ScopedErrorBodies(ScopedRepo):
    """Every refusal this PR adds, with its exact status and JSON body. Error strings are part of the agent contract
    (api.md), so moving the checks between layers (coding rule R3) must not change a byte of them."""

    # Since 0.3.4 every refusal also names a reason code (additive; tests/test_errors.py). The text stays byte-identical.
    PIN_MSG = {"error": "pin 은 핀 번호(양의 정수)여야 합니다.", "reason": "bad_pin"}
    NOT_HERE = {"error": "이 문서의 핀이 아닙니다.", "reason": "pin_not_in_doc"}

    def raw(self, method, path, body=None):
        """(status, parsed JSON body) for one request, without AccessBase's lenient decoding."""
        h, data = {}, b""
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        code, _, out = split_resp(talk_to(ps, req(method, path, data, h)))
        return code, json.loads(out)

    def test_revision_routes_refuse_a_bad_or_foreign_pin_with_the_same_bodies(self):
        """A malformed pin is 400 and a pin of no/another document is 404, on all three GET routes and the POST."""
        for route in ("revision-diff", "revision-build", "revision-pdf"):
            with self.subTest(route=route):
                self.assertEqual(self.raw("GET", "/api/%s?commit=%s&pin=abc" % (route, self.fix)), (400, self.PIN_MSG))
                self.assertEqual(self.raw("GET", "/api/%s?commit=%s&pin=0" % (route, self.fix)), (400, self.PIN_MSG))
                self.assertEqual(self.raw("GET", "/api/%s?commit=%s&pin=999" % (route, self.fix)), (404, self.NOT_HERE))
        for body, want in (({"commit": self.fix, "pin": "2"}, (400, self.PIN_MSG)),
                           ({"commit": self.fix, "pin": True}, (400, self.PIN_MSG)),
                           ({"commit": self.fix, "pin": 0}, (400, self.PIN_MSG)),
                           ({"commit": self.fix, "pin": 999}, (404, self.NOT_HERE)),
                           ({"commit": self.fix, "pins": 1},
                            (400, {"error": "허용되지 않는 비교 PDF 요청 필드입니다.", "reason": "unknown_fields"}))):
            with self.subTest(body=body):
                self.assertEqual(self.raw("POST", "/api/revision-build", body), want)

    def test_close_refuses_malformed_changes_with_the_same_bodies(self):
        """Each rejection of the close body's `changes` keeps its status and message, and names the offending item."""
        pid = self.add(lo=2, hi=2, note="for the bodies")
        ok = {"file": "main.tex", "lo": 1, "hi": 1}
        cases = (("x", "changes 는 [{\"file\", \"lo\", \"hi\"}] 목록이어야 합니다.", "bad_changes"),
                 ([ok] * 51, "changes 는 50개 이하여야 합니다.", "too_many_changes"),
                 ([ok, {"file": "main.tex", "lo": 1}], "changes[1] 는 file·lo·hi 세 필드만 가진 객체여야 합니다.", "bad_changes"),
                 ([{"file": " ", "lo": 1, "hi": 1}], "changes[0].file 은 비어 있지 않은 경로 문자열이어야 합니다.", "bad_changes"),
                 ([{"file": "main.tex", "lo": 3, "hi": 2}], "changes[0] 의 lo·hi 는 1 ≤ lo ≤ hi ≤ 1000000 인 정수여야 합니다.",
                  "bad_changes"),
                 ([{"file": "../x.tex", "lo": 1, "hi": 1}], "changes[0].file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다.",
                  "change_outside_manuscript"))
        for changes, msg, reason in cases:
            with self.subTest(msg=msg):
                self.assertEqual(self.raw("POST", "/api/pins/%d/close" % pid, {"changes": changes}),
                                 (400, {"error": msg, "reason": reason}))
        self.assertFalse(self.pin(pid).get("done"))

    def build_status(self, pid):
        """Start the scoped build for pid on self.fix and wait for its final status."""
        ps.revision_start(ps.DOCS[0], self.fix, pid)
        end = time.time() + 30
        while time.time() < end:
            st = ps.revision_status(ps.DOCS[0], self.fix, pid)
            if st["state"] != "running":
                return st
            time.sleep(0.05)
        self.fail("scoped build did not finish")

    def test_scoped_build_failures_keep_their_status_bodies(self):
        """When the pin's blocks cannot be re-read, do not all come back, or name an unsafe path, the build status says
        so with the same error text and reason as before."""
        revision_spec(self.fix, self.p2)          # warm the scope cache: the spec is not re-read below
        real = revisions.revision_changes
        cases = (("unreadable", lambda *a: None, "이 핀의 변경만 골라 적용하지 못했습니다.", "scope_failed"),
                 ("mismatch", lambda *a: [], "이 핀의 변경을 커밋에서 다시 찾지 못했습니다.", "scope_failed"))
        for name, fake, msg, reason in cases:
            with self.subTest(case=name), mock.patch.object(revisions, "revision_changes", side_effect=fake):
                st = self.build_status(self.p2)
                self.assertEqual((st["state"], st["error"], st["reason"]), ("error", msg, reason))
                shutil.rmtree(revisions.revision_cache_root(ps.DOCS[0]))
        spec = revision_spec(self.fix, self.p2)
        bad = ("ms/../evil.tex", "ms/../evil.tex", 0, 1, 0, 1)
        evil = scoping.FileChange(bad[0], bad[1], (b"x\n",), (b"y\n",), (scoping.Block(0, 1, 0, 1),), False)
        with mock.patch.object(revisions, "revision_spec", return_value=spec._replace(scope=(bad,))), \
                mock.patch.object(revisions, "revision_changes", return_value=[evil]):
            st = self.build_status(self.p2)
        self.assertEqual((st["state"], st["error"], st["reason"]), ("error", "사본에 허용되지 않는 경로가 있습니다.", "unsafe_snapshot"))
        self.assertFalse((self.repo / "evil.tex").exists())
        self.assertIs(revisions.revision_changes, real)


class ScopedPdf(ScopedRepo):
    """The scoped comparison PDF: spec and cache identity, build status fields, real sandboxed builds."""

    def test_spec_key_depends_on_pin_commit_and_hunk_set(self):
        """One cached comparison per (pin, commit, hunk set); a pin owning the whole commit shares the whole-commit key."""
        whole = revision_spec(self.fix)
        s1, s2 = revision_spec(self.fix, self.p1), revision_spec(self.fix, self.p2)
        self.assertEqual(whole.scope, ())
        self.assertEqual(len({whole.key, s1.key, s2.key}), 3)
        self.assertEqual(s1.key, revision_spec(self.fix, self.p1).key)     # stable
        # a pin whose commit is entirely its own shares the whole-commit comparison (and its cache)
        self.assertEqual(revision_spec(self.solo, self.p4).key, revision_spec(self.solo).key)
        # the recorded change set is part of the identity: a different set is a different comparison
        rows = ps.snapshot_pins()
        ps.find_pin(rows, self.p1)["changes"] = [{"file": str(self.main.resolve()), "lo": 12, "hi": 12}]
        ps.write_pins(rows)
        self.assertNotEqual(revision_spec(self.fix, self.p1).key, s1.key)

    def test_changes_recorded_by_an_earlier_close_are_ignored(self):
        """Review finding (rollback): changes whose changes_at is not this close's done_at are ignored."""
        # 0.2.2 (after a rollback) neither clears changes on reopen nor writes them on close: a set whose changes_at is
        # not this close's done_at belongs to an older close, so inference decides (alpha's own hunk), not those lines.
        rows = ps.snapshot_pins()
        r = ps.find_pin(rows, self.p1)
        self.assertEqual(r["changes_at"], r["done_at"])
        r["changes"] = [{"file": str(self.main.resolve()), "lo": 12, "hi": 12}]     # beta's line
        r["done_at"] = "2026-09-26 09:00:00"
        ps.write_pins(rows)
        d = self.diff_ok(self.fix, self.p1)
        self.assertEqual((d["scope"]["source"], "pears" in d["scope"]["diff"]), ("inferred", True))

    def test_status_without_pin_never_carries_another_requests_pin_fields(self):
        """Review finding: pin fields are per request; a shared whole-commit status must not leak them to pin-less requests."""
        def compile(spec, jobdir, timeout):
            (jobdir / "revision.pdf").write_bytes(minimal_pdf("x"))
            return {"state": "ready", "warnings": [], "error": None, "reason": None}
        with mock.patch.object(revisions, "revision_compile", side_effect=compile):
            code, d = self.call("POST", "/api/revision-build", {"commit": self.solo, "pin": self.p4})   # shares the whole key
            self.assertEqual((d["scope"], d["pin"]), ("commit", self.p4))
            end = time.time() + 10
            while time.time() < end and self.call("GET", "/api/revision-build?commit=%s" % self.solo)[1]["state"] == "running":
                time.sleep(0.05)
        for path in ("/api/revision-build?commit=%s" % self.solo,):
            code, d = self.call("GET", path)
            self.assertEqual(d["state"], "ready")
            self.assertFalse(set(d) & set(revisions.SCOPE_META), d)
        code, d = self.call("POST", "/api/revision-build", {"commit": self.solo})
        self.assertFalse(set(d) & set(revisions.SCOPE_META), d)
        code, d = self.call("GET", "/api/revision-build?commit=%s&pin=%d" % (self.solo, self.p4))
        self.assertEqual((d["scope"], d["pin"]), ("commit", self.p4))

    def test_failed_pin_subset_is_answered_from_the_cache_without_rebuilding(self):
        """Review finding: a deterministic scoped failure is not rebuilt on every visit."""
        calls = []

        def fail(spec, jobdir, timeout):
            calls.append(spec.scope)
            return revisions.StepFailed("compile_failed")
        with mock.patch.object(revisions, "revision_compile", side_effect=fail):
            for _ in range(2):
                self.call("POST", "/api/revision-build", {"commit": self.fix, "pin": self.p2})
                end = time.time() + 10
                while time.time() < end and self.call("GET", "/api/revision-build?commit=%s&pin=%d" % (self.fix, self.p2))[1]["state"] == "running":
                    time.sleep(0.05)
            code, d = self.call("POST", "/api/revision-build", {"commit": self.fix, "pin": self.p2})
            self.assertEqual((d["state"], d["reason"], d["scope"]), ("error", "compile_failed", "pin"))
        self.assertEqual(len(calls), 1)                   # built once; the whole commit still retries (0.2.2 behaviour)

    def test_build_routes_accept_pin_and_report_scope_fields(self):
        """POST/GET revision-build and revision-pdf take pin and report scope, pin, hunks and other."""
        seen = []

        def compile(spec, jobdir, timeout):
            seen.append(spec.scope)
            (jobdir / "revision.pdf").write_bytes(minimal_pdf("x"))
            return {"state": "ready", "warnings": [], "error": None, "reason": None}
        with mock.patch.object(revisions, "revision_compile", side_effect=compile):
            code, d = self.call("POST", "/api/revision-build", {"commit": self.fix, "pin": self.p2})
            self.assertIn(code, (200, 202), d)
            self.assertEqual((d["scope"], d["pin"], d["hunks"], d["other"]), ("pin", self.p2, 1, 2))
            end = time.time() + 10
            while time.time() < end and self.call("GET", "/api/revision-build?commit=%s&pin=%d" % (self.fix, self.p2))[1]["state"] == "running":
                time.sleep(0.05)
            code, d = self.call("GET", "/api/revision-build?commit=%s&pin=%d" % (self.fix, self.p2))
            self.assertEqual((d["state"], d["scope"]), ("ready", "pin"))
            code, _ = self.call("GET", "/api/revision-pdf?commit=%s&pin=%d" % (self.fix, self.p2))
            self.assertEqual(code, 200)
            self.assertEqual(self.call("GET", "/api/revision-pdf?commit=%s" % self.fix)[0], 404)   # the whole commit was not built
            code, d = self.call("POST", "/api/revision-build", {"commit": self.solo, "pin": self.p4})
            self.assertEqual(d["scope"], "commit")
        self.assertEqual(len(seen[0]), 1)
        for bad in ({"commit": self.fix, "pin": "2"}, {"commit": self.fix, "pin": True}, {"commit": self.fix, "pin": 999},
                    {"commit": self.fix, "pins": 1}):
            with self.subTest(bad=bad):
                self.assertIn(self.call("POST", "/api/revision-build", bad)[0], (400, 404))

    @unittest.skipUnless(all(shutil.which(t) for t in ("bwrap", "latexdiff", "latexmk", "pdftotext")), "TeX sandbox tools unavailable")
    def test_real_scoped_build_marks_only_the_pins_change(self):
        """With TeX: the sandboxed scoped PDF shows the pin's change and none of the others; the checkout is untouched."""
        dest = self.repo / "job-beta"
        dest.mkdir()
        status = revisions.revision_compile(revision_spec(self.fix, self.p2), dest, 60)
        self.assertEqual(status["state"], "ready", status)
        text = subprocess.check_output(["pdftotext", str(dest / "revision.pdf"), "-"], text=True)
        self.assertIn("blueberries", text)
        self.assertIn("bananas", text)
        self.assertNotIn("pears", text)                    # alpha's change is not applied
        self.assertIn("cherries", text)                    # gamma is still there, unmarked
        self.assertNotIn("second alpha", text)
        whole = self.repo / "job-whole"
        whole.mkdir()
        revisions.revision_compile(revision_spec(self.fix), whole, 60)
        self.assertIn("pears", subprocess.check_output(["pdftotext", str(whole / "revision.pdf"), "-"], text=True))
        self.assertEqual(self.main.read_text(encoding="utf-8"), NEW.replace("Filler two.", "Filler two, reworded."))

    @unittest.skipUnless(all(shutil.which(t) for t in ("bwrap", "latexdiff", "latexmk")), "TeX sandbox tools unavailable")
    def test_scoped_build_is_an_error_when_the_subset_does_not_compile(self):
        """With TeX: half of an environment fix alone does not compile; the error lets the viewer fall back."""
        # one commit opens an environment for one pin and closes it for another: each half alone does not compile
        base = NEW.replace("Filler two.", "Filler two, reworded.")
        self.write(base.replace("Filler one.", "\\begin{itemize}\\item Filler one.").replace("Filler eight.", "Filler eight.\\end{itemize}"))
        both = self.commit("wrap the fillers in a list")
        opener = self.add(lo=7, hi=7, note="open")
        ps.set_done(opener, True, dict(ps.LOCAL_ACTOR), ref=both[:8],
                    changes=(parse.CloseChange(str(self.main.resolve()), 7, 7),))
        spec = revision_spec(both, opener)
        self.assertEqual(len(spec.scope), 1)
        dest = self.repo / "job-half"
        dest.mkdir()
        self.assertIn(revisions.revision_compile(spec, dest, 60),
                      (revisions.StepFailed("compile_failed"), revisions.StepFailed("diff_failed")))
        whole = self.repo / "job-both"
        whole.mkdir()
        self.assertEqual(revisions.revision_compile(revision_spec(both), whole, 60)["state"], "ready")


class ReviewRegressions(AccessBase):
    """Findings of the independent review of PR #13 (probes in /tmp/limn-rev13/probes, kept here as regressions)."""

    BASE = "".join("Line %d of the manuscript.\n" % i for i in range(1, 41))
    DOC = "\\documentclass{article}\n\\begin{document}\n" + BASE + "\\end{document}\n"

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.main.write_text(self.DOC, encoding="utf-8")
        for args in (("init", "--quiet"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T")):
            self.git(*args)
        self.commit("first")
        ps.SCOPE_CACHE.clear()

    def git(self, *args):
        """Run git in the fixture repository and return its stdout."""
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def write(self, text, path=None):
        """Write a manuscript file with an mtime in the future, so the next pin sync sees the change."""
        p = path or self.main
        p.write_text(text, encoding="utf-8")
        t = time.time() + 5
        os.utime(p, (t, t))

    def commit(self, msg):
        """Commit everything under ms/ and return the full hash."""
        self.git("add", "-A", "ms")
        self.git("commit", "--quiet", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()

    def scope(self, commit, pid):
        """The scope object of GET /api/revision-diff?commit=&pin=."""
        code, d = self.call("GET", "/api/revision-diff?commit=%s&pin=%d" % (commit, pid))
        self.assertEqual(code, 200, d)
        return d["scope"]

    def test_changes_recorded_for_one_commit_do_not_select_hunks_of_another(self):
        """M1: pin A closed with changes (line 12) for commit X; a later commit Y edits line 12 for another pin. On Y
        the recorded lines are not A's, so only inference may attribute (labelled inferred); on X they still decide."""
        pa = self.add(lo=12, hi=12, note="A")
        x = self.DOC.replace("Line 10 of", "Line TEN of")
        self.write(x)
        X = self.commit("fix A")
        code, d = self.call("POST", "/api/pins/%d/close" % pa, {"ref": "PR #1 (%s)" % X[:7],
                                                                "changes": [{"file": "main.tex", "lo": 12, "hi": 12}]})
        self.assertEqual(code, 200, d)
        Y = self.commit_y(x)
        self.assertEqual(self.scope(X, pa)["source"], "changes")
        self.assertNotEqual(self.scope(Y, pa)["source"], "changes")
        self.assertEqual(self.scope(Y, pa)["source"], "inferred")

    def commit_y(self, x):
        """Commit Y: pin B's fix on line 12 and another change on line 32."""
        self.write(x.replace("Line TEN of", "Line TEN (B) of").replace("Line 30 of", "Line 30 (C) of"))
        return self.commit("fix B and C")

    def test_a_transient_git_failure_is_not_cached_as_whole_commit(self):
        """m1: one git timeout shows the whole commit once; the next request scopes again."""
        pa, _ = self.add(lo=5, hi=5, note="A"), self.add(lo=30, hi=30, note="B")
        self.write(self.DOC.replace("Line 3 of", "Line THREE of").replace("Line 28 of", "Line 28x of"))
        X = self.commit("fix A and B")
        self.call("POST", "/api/pins/%d/close" % pa, {"ref": X[:8]})
        real, calls = revisions.revision_exec, {"n": 0}

        def flaky(cmd, *a, **k):
            if "--raw" in cmd and calls["n"] == 0:
                calls["n"] += 1
                return revisions.StepFailed("timeout")
            return real(cmd, *a, **k)
        with mock.patch.object(revisions, "revision_exec", flaky):
            first = self.scope(X, pa)["mode"]
        self.assertEqual((first, self.scope(X, pa)["mode"]), ("commit", "pin"))

    def test_scope_cache_entries_are_bounded_by_the_response_cap(self):
        """m2: a huge commit's patches are stored cut at REVISION_DIFF_MAX + 1 bytes (enough to flag truncation)."""
        n = 6000
        big = self.src / "big.tex"
        self.write(("a" * 199 + "\n") * n, big)
        self.commit("big old")
        pa = self.add(lo=5, hi=5, note="A")
        self.write("".join((("b" * 199 + "\n") if i % 2 else ("a" * 199 + "\n")) for i in range(n)), big)
        self.write(self.DOC.replace("Line 3 of", "Line THREE of"))
        X = self.commit("big change + A")
        self.call("POST", "/api/pins/%d/close" % pa, {"ref": X[:8], "changes": [{"file": "main.tex", "lo": 5, "hi": 5}]})
        s = self.scope(X, pa)
        self.assertEqual((s["mode"], s["other_truncated"]), ("pin", True))
        sc = next(iter(ps.SCOPE_CACHE.values()))
        self.assertLessEqual(max(len(sc.diff), len(sc.other_diff)), scoping.REVISION_DIFF_MAX + 1)

    def test_scope_computations_run_at_most_two_at_a_time(self):
        """m3: cache misses read the commit on the request thread; at most SCOPE_SLOTS (2) do so at once."""
        pins = [self.add(lo=3 + i, hi=3 + i, note="p%d" % i) for i in range(5)]
        self.write(self.DOC.replace("Line 1 of", "Line ONE of"))
        X = self.commit("one change")
        base = self.git("rev-parse", X + "^").strip()
        real, lock, now, peak = revisions.revision_changes, threading.Lock(), [0], [0]

        def slow(*a, **k):
            with lock:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            time.sleep(0.3)
            with lock:
                now[0] -= 1
            return real(*a, **k)
        repo, paths = revisions.revision_scope(ps.DOCS[0])
        revs = ps.revision_history(ps.DOCS[0])["revisions"]
        rows = ps.read_pins()[0]
        with mock.patch.object(revisions, "revision_changes", side_effect=slow):
            ts = [threading.Thread(target=revisions.revision_pin_scope,
                                   args=(ps.DOCS[0], rows, repo, tuple(paths), base, X, pid, revs, ps.revision_context()))
                  for pid in pins]
            for t in ts:
                t.start()
            for t in ts:
                t.join(20)
        self.assertEqual(peak[0], 2)

    def test_pins_with_the_same_blocks_share_one_comparison_pdf(self):
        """m4: the comparison is keyed by (commit, block set), not by pin - two pins on the same fix build once."""
        pa, pb = self.add(lo=5, hi=5, note="A"), self.add(lo=5, hi=5, note="B")
        self.write(self.DOC.replace("Line 3 of", "Line THREE of").replace("Line 28 of", "Line 28x of"))
        X = self.commit("fix A and something else")
        ka, kb = (revision_spec(X, p).key for p in (pa, pb))
        self.assertEqual(ka, kb)
        self.assertNotEqual(ka, revision_spec(X).key)

    def test_scoped_comparisons_never_evict_whole_commit_ones(self):
        """m4: pin-scoped cache entries have their own limit, so many pins do not push out the whole-commit PDFs."""
        root = revisions.revision_cache_root(ps.DOCS[0])
        whole = [root / ("%064x" % i) for i in range(3)]
        scoped = [root / ("%064x" % (100 + i)) for i in range(revisions.REVISION_SCOPED_KEEP + 4)]
        for i, d in enumerate(whole + scoped):
            d.mkdir()
            if d in scoped:
                (d / revisions.SCOPED_MARK).write_text("")
            t = time.time() - 1000 + (i if d in whole else 500 + i)       # every scoped entry is newer
            os.utime(d, (t, t))
        revisions.revision_prune(root, "f" * 64, ps.REVISION_JOBS.active)
        self.assertTrue(all(d.exists() for d in whole))
        self.assertEqual(sum(d.exists() for d in scoped), revisions.REVISION_SCOPED_KEEP)

    def test_a_synthetic_tree_that_cannot_be_written_is_a_scope_failure(self):
        """m5: an OSError while writing the synthetic tree is the ScopeUnwritable refusal, reported as scope_failed
        (deterministic, answered from the cache) - not a generic build_failed with a traceback."""
        dest = Path(self.tmp.name) / "dest"
        dest.mkdir()
        (dest / "main.tex").write_text("x")
        spec = revisions.RevisionSpec(self.repo, "ms", Path("main.tex"), "a" * 40, "b" * 40, "k" * 64)
        with mock.patch.object(revisions, "revision_changes", return_value=[]), \
                mock.patch.object(revisions, "plan_scope_writes", return_value=[scoping.ScopeWrite("main.tex/x.tex", b"x")]):
            refused = revisions.revision_apply_scope(spec, dest)
        self.assertEqual(refused, scoping.ScopeUnwritable())
        err = scope_http_error(refused)
        self.assertEqual((err.code, err.body["reason"]), (422, "scope_failed"))

    def test_a_file_that_becomes_a_symlink_is_never_applied_as_text(self):
        """m6: a file -> symlink type change has no blocks (one of the other changes, shown with its modes), and the
        synthetic tree keeps the old regular file instead of the link's target text."""
        sec = self.src / "sec.tex"
        self.write("Section text.\n", sec)
        self.write(self.DOC.replace("\\end{document}", "\\input{sec}\n\\end{document}"))
        self.commit("add sec")
        pa = self.add(lo=5, hi=5, note="A")
        sec.unlink()
        os.symlink("/etc/hostname", sec)
        self.write(self.main.read_text().replace("Line 3 of", "Line THREE of"))
        X = self.commit("typechange sec + A")
        code, d = self.call("POST", "/api/pins/%d/close" % pa, {"ref": X[:8], "changes": [{"file": "main.tex", "lo": 5, "hi": 5}]})
        self.assertEqual(code, 200, d)          # (a changes item naming sec.tex resolves outside the folder: 400)
        s = self.scope(X, pa)
        self.assertEqual((s["mode"], s["source"], s["hunks"], s["other"]), ("pin", "changes", 1, 1))
        self.assertIn("new mode 120000", s["other_diff"])
        spec = revision_spec(X, pa)
        dest = Path(self.tmp.name) / "dest"
        revisions.revision_snapshot(spec, spec.base, dest)
        revisions.revision_apply_scope(spec, dest)
        self.assertFalse((dest / "sec.tex").is_symlink())
        self.assertEqual((dest / "sec.tex").read_text(), "Section text.\n")


# ---------------------------------------------------------------- 4. the real viewer

DEVICES = {
    "desktop": {"viewport": {"width": 1400, "height": 850}},
    "fold": {"viewport": {"width": 842, "height": 758}, "is_mobile": True, "has_touch": True},
    "phone": {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True},
}
TXT = {"ko": {"other": "이 커밋의 다른 변경 2곳", "whole": "커밋 전체 비교", "only": "핀 #%d의 변경만",
              "fallback": "커밋 전체를 비교합니다"},
       "en": {"other": "2 other changes in this commit", "whole": "Whole commit", "only": "Only pin #%d's changes",
              "fallback": "comparing the whole commit"}}


class ScopedViewer(BrowserBase):
    """The viewer's [View changes] for a pin on desktop, fold and phone in Korean and English."""

    WHO = ALICE

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        ps.record_person(A)
        self.repo = self.main.parent.parent
        self.main.write_text(OLD, encoding="utf-8")
        for args in (("init", "--quiet"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T")):
            self.git(*args)
        self.commit("first")
        self.p1 = add_pin({"file": str(self.main), "lo": 4, "hi": 4, "page": 1, "note": "alpha"}, A).record["id"]
        self.p2 = add_pin({"file": str(self.main), "lo": 11, "hi": 11, "page": 1, "note": "beta"}, A).record["id"]
        self.p3 = add_pin({"file": str(self.main), "lo": 18, "hi": 18, "page": 1, "note": "gamma"}, A).record["id"]
        self.write(NEW)
        self.fix = self.commit("fix three pins")
        loc = dict(ps.LOCAL_ACTOR)
        ps.set_done(self.p1, True, loc, reply="alpha", ref=self.fix[:8], changes=(parse.CloseChange(str(self.main.resolve()), 4, 5),))
        ps.set_done(self.p2, True, loc, reply="beta", ref=self.fix[:8])
        ps.set_done(self.p3, True, loc, reply="gamma", ref=self.fix[:8])
        self.p4 = add_pin({"file": str(self.main), "lo": 8, "hi": 8, "page": 1, "note": "filler"}, A).record["id"]
        self.write(NEW.replace("Filler two.", "Filler two, reworded."))
        self.solo = self.commit("fix the filler pin")
        ps.set_done(self.p4, True, loc, reply="filler", ref=self.solo[:8])
        self.builds = []
        self.fail_scoped = False
        patcher = mock.patch.object(revisions, "revision_compile", side_effect=self.fake_compile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_compile(self, spec, jobdir, timeout):
        self.builds.append((spec.head, spec.scope))
        if spec.scope and self.fail_scoped:
            return revisions.StepFailed("compile_failed")
        (jobdir / "revision.pdf").write_bytes(minimal_pdf("pin" if spec.scope else "whole"))
        return {"state": "ready", "warnings": [], "error": None, "reason": None}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def write(self, text):
        self.main.write_text(text, encoding="utf-8")
        t = time.time() + 5
        os.utime(self.main, (t, t))

    def commit(self, msg):
        self.git("add", "ms")
        self.git("commit", "--quiet", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()

    def open_change(self, device, lang, pid):
        page = self._page = self.open(0, lang=lang, **DEVICES[device])
        page.evaluate("showChange(%d)" % pid)
        page.wait_for_function("REVISION_SOURCE_COMMIT&&document.querySelectorAll('#revision-diff .rd-line').length>0", timeout=15000)
        page.wait_for_timeout(150)
        return page

    def visible(self, page, sel):
        return page.evaluate("(()=>{const e=document.querySelector(%s);return !!e&&!e.closest('[hidden]')&&e.getClientRects().length>0;})()" % json.dumps(sel))

    def fits(self, page, sel, device):
        box = page.evaluate("(()=>{const r=document.querySelector(%s).getBoundingClientRect();return [r.left,r.right,r.height,innerWidth];})()" % json.dumps(sel))
        self.assertGreaterEqual(box[0], 0, sel)
        self.assertLessEqual(box[1], box[3] + 0.5, sel)
        if device != "desktop":
            self.assertGreaterEqual(box[2], 44, sel)            # touch target

    def english_only(self, page, sel):
        text = page.inner_text(sel)
        self.assertFalse(HANGUL.search(text), (sel, text))

    def wait_pdf(self, page):
        page.wait_for_function("document.querySelectorAll('#revision-pdf .revision-page').length>0", timeout=15000)

    def test_pin_view_folds_other_changes_and_toggles_the_whole_commit_pdf(self):
        """The two controls on desktop/fold/phone x ko/en: fold toggle, [Whole commit] toggle, cached rebuilds, touch sizes."""
        for device in DEVICES:
            for lang in ("ko", "en"):
                with self.subTest(device=device, lang=lang):
                    self.tearDown()
                    self.setUp()
                    self.flow(device, lang)

    def flow(self, device, lang):
        t = TXT[lang]
        page = self.open_change(device, lang, self.p2)
        diff = page.inner_text("#revision-diff")
        self.assertIn("blueberries", diff)
        self.assertNotIn("pears", diff)
        self.assertNotIn("Gamma", diff)
        tog = "#revision-other-toggle"
        self.assertTrue(self.visible(page, tog))
        self.assertEqual(page.get_attribute(tog, "aria-expanded"), "false")
        self.assertIn(t["other"], page.inner_text(tog))
        self.assertFalse(self.visible(page, "#revision-other"))
        self.fits(page, tog, device)
        page.click(tog)
        self.assertEqual(page.get_attribute(tog, "aria-expanded"), "true")
        other = page.inner_text("#revision-other")
        self.assertIn("pears", other)
        self.assertIn("Gamma", other)
        self.assertNotIn("blueberries", other)
        page.click(tog)
        self.assertFalse(self.visible(page, "#revision-other"))
        if lang == "en":
            self.english_only(page, "#revision-source")
        # the comparison PDF: this pin's hunks only, one toggle to the whole commit
        page.click("#revision-pdf-tab")
        self.wait_pdf(page)
        self.assertEqual(self.builds[-1][0], self.fix)
        self.assertEqual(len(self.builds[-1][1]), 1)
        whole = "#revision-whole"
        self.assertTrue(self.visible(page, whole))
        self.assertEqual(page.get_attribute(whole, "aria-pressed"), "false")
        self.assertIn(t["whole"], page.inner_text(whole))
        self.assertIn(t["only"] % self.p2, page.inner_text("#revision-status"))
        self.fits(page, whole, device)
        page.click(whole)
        page.wait_for_function("document.getElementById('revision-whole').getAttribute('aria-pressed')==='true'")
        self.wait_pdf(page)
        page.wait_for_function("!/%s/.test(document.getElementById('revision-status').textContent)" % re.escape(t["only"] % self.p2))
        self.assertEqual(self.builds[-1], (self.fix, ()))
        page.click(whole)
        self.wait_pdf(page)
        self.assertEqual(page.get_attribute(whole, "aria-pressed"), "false")
        page.wait_for_function("document.getElementById('revision-status').textContent.includes(%s)" % json.dumps(t["only"] % self.p2))
        self.assertEqual(len(self.builds), 2)                    # both comparisons are cached; toggling back builds nothing
        # the approximate-page note stays
        self.assertTrue(self.visible(page, "#revision-pin"))
        if lang == "en":
            self.english_only(page, "#revision-controls")
            self.english_only(page, "#revision-status")
            self.english_only(page, "#revision-pin")

    def test_a_commit_that_is_the_pins_own_has_no_extra_controls(self):
        """A pin that owns its whole commit sees the 0.2.2 view: no fold toggle, no PDF toggle, the whole-commit build."""
        for device in ("desktop", "phone"):
            with self.subTest(device=device):
                self.tearDown()
                self.setUp()
                page = self.open_change(device, "ko", self.p4)
                self.assertIn("reworded", page.inner_text("#revision-diff"))
                self.assertFalse(self.visible(page, "#revision-other-toggle"))
                page.click("#revision-pdf-tab")
                self.wait_pdf(page)
                self.assertFalse(self.visible(page, "#revision-whole"))
                self.assertEqual(self.builds, [(self.solo, ())])

    def test_a_subset_that_fails_to_compile_falls_back_to_the_whole_commit(self):
        """When the scoped build fails the viewer builds the whole commit once, says so in one line, and hides the toggle."""
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                self.tearDown()
                self.setUp()
                self.fail_scoped = True
                page = self.open_change("desktop", lang, self.p3)
                page.click("#revision-pdf-tab")
                self.wait_pdf(page)
                self.assertEqual([len(b[1]) for b in self.builds], [1, 0])
                self.assertIn(TXT[lang]["fallback"], page.inner_text("#revision-status"))
                self.assertFalse(self.visible(page, "#revision-whole"))
                if lang == "en":
                    self.english_only(page, "#revision-status")

    def test_switching_to_another_commit_shows_it_whole_without_pin_scope(self):
        """Review M1 (viewer): the pin's scope applies only to the commit picked for it. Choosing another commit in
        the list shows that commit whole - no &pin= on the diff or the PDF - and choosing the pin's commit again
        scopes it again."""
        page = self.open_change("desktop", "ko", self.p2)
        urls = []
        page.on("request", lambda r: urls.append(r.url))
        page.select_option("#revision-select", self.solo)          # another commit: the list opens its PDF
        self.wait_pdf(page)
        self.assertFalse(self.visible(page, "#revision-whole"))
        self.assertEqual(self.builds[-1], (self.solo, ()))
        page.click("#revision-source-tab")
        page.wait_for_function("REVISION_SOURCE_COMMIT===%s" % json.dumps(self.solo), timeout=15000)
        self.assertIn("reworded", page.inner_text("#revision-diff"))
        self.assertFalse(self.visible(page, "#revision-other-toggle"))
        seen = [u for u in urls if "/api/revision-" in u and self.solo in u]
        self.assertTrue(seen)
        self.assertFalse([u for u in seen if "pin=" in u], seen)
        page.select_option("#revision-select", self.fix)           # back to the pin's own commit: scoped again
        self.wait_pdf(page)
        page.wait_for_function("!document.getElementById('revision-whole').hidden", timeout=15000)
        self.assertEqual(self.builds[-1][0], self.fix)
        self.assertEqual(len(self.builds[-1][1]), 1)
        page.click("#revision-source-tab")
        page.wait_for_function("REVISION_SOURCE_COMMIT===%s&&!document.getElementById('revision-other-toggle').hidden"
                               % json.dumps(self.fix), timeout=15000)
        self.assertNotIn("pears", page.inner_text("#revision-diff"))

    def test_other_changes_start_folded_for_the_next_pin(self):
        """Opening [View changes] for another pin starts with the other changes folded and only that pin's hunks."""
        page = self.open_change("desktop", "ko", self.p2)
        page.click("#revision-other-toggle")
        page.evaluate("showChange(%d)" % self.p1)
        page.wait_for_function("document.getElementById('revision-diff').textContent.includes('pears')", timeout=15000)
        self.assertEqual(page.get_attribute("#revision-other-toggle", "aria-expanded"), "false")
        self.assertFalse(self.visible(page, "#revision-other"))
        self.assertNotIn("blueberries", page.inner_text("#revision-diff"))


# ---------------------------------------------------------------- 5. coordinator follow-ups (E2E re-run): events and the viewer's Trash

from test_access import BOB, CAROL, configure, reset_access  # noqa: E402


def load_v022():
    """The server module exactly as released in v0.2.2 (from git), or None in a shallow clone."""
    import importlib.util
    r = subprocess.run(["git", "show", "v0.2.2:src/limn/server.py"], cwd=Path(__file__).resolve().parent.parent,
                       capture_output=True, timeout=30, check=False)
    if r.returncode != 0 or b"def reply_reopens" not in r.stdout:
        return None
    d = Path(tempfile.mkdtemp(prefix="limn-v022-"))
    (d / "server_v022.py").write_bytes(r.stdout)
    spec = importlib.util.spec_from_file_location("limn_server_v022", d / "server_v022.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    shutil.rmtree(d, ignore_errors=True)
    return mod


# A person's reply that reopens a closed pin (docs/handbook/api.md §답글이 핀을 다시 여는 규칙 (0.2.2)). Each case:
# (pin author, assignee, who closes it (None = the agent), expected events as (type, recipients, actor)).
REOPEN_CASES = {
    "author is not the replier, agent closed": (BOB, None, None, [
        ("review_requested", ["bob@example.com"], "local"), ("reopened", ["bob@example.com"], "alice@example.com")]),
    "author is the replier, agent closed": (ALICE, None, None, [
        ("review_requested", ["alice@example.com"], "local")]),
    "assigned to a person, agent closed": (BOB, "carol@example.com", None, [
        ("assigned", ["carol@example.com"], "bob@example.com"), ("review_requested", ["bob@example.com"], "local"),
        ("reopened", ["bob@example.com"], "alice@example.com")]),
    "closed by a person": (BOB, None, CAROL, [
        ("reopened", ["bob@example.com"], "alice@example.com")]),
    "closed by the replier": (BOB, None, ALICE, [
        ("reopened", ["bob@example.com"], "alice@example.com")]),
}


class ReplyReopenEvents(unittest.TestCase):
    """The E2E re-run reported that a reopening reply only records `replied` on this branch. It does not: the events are
    the ones v0.2.2 records, case by case - asserted literally here, and (when git history is available) against the
    released v0.2.2 module run through the same requests."""

    def run_case(self, mod, author, assignee, closer):
        tmp = Path(tempfile.mkdtemp(prefix="limn-ev-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        src = tmp / "ms"
        src.mkdir()
        main = src / "main.tex"
        main.write_text("\\documentclass{article}\n\\begin{document}\n" + "".join("Line %d.\n" % i for i in range(3, 30))
                        + "\\end{document}\n", encoding="utf-8")
        state = tmp / "state"
        state.mkdir()
        configure(mod, src, main, state)
        reset_access(mod)
        mod._PEOPLE_SEEN.clear()

        def call(method, path, body=None, headers=None):
            h, raw = dict(headers or {}), b""
            if body is not None:
                raw, h["Content-Type"] = json.dumps(body).encode(), "application/json"
            if method == "POST":
                h["Origin"] = "http://127.0.0.1:18999"
            code, _, out = split_resp(talk_to(mod, req(method, path, raw, h)))
            return code, json.loads(out)
        for h in (ALICE, BOB, CAROL):
            call("GET", "/api/meta", headers=h)                     # people.json knows all three
        body = {"file": str(main), "lo": 4, "hi": 5, "page": 1, "note": "고쳐 주세요"}
        if assignee:
            body["assignee"] = assignee
        code, d = call("POST", "/api/pin", body, author)
        self.assertEqual(code, 200, d)
        pid = d["id"]
        self.assertEqual(call("POST", "/api/pins/%d/close" % pid, {}, closer)[0], 200)
        code, d = call("POST", "/api/pins/%d/reply" % pid, {"text": "아직입니다"}, ALICE)
        self.assertEqual((code, d["state"], d["reopened"]), (200, "open", True))
        path = state / "events.jsonl"
        evs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        reset_access(mod)
        return [(e["type"], sorted(e.get("to") or []), (e.get("by") or {}).get("login")) for e in evs]

    def test_reopening_reply_emits_the_v0_2_2_events(self):
        """E2E report (not reproduced): a person's reopening reply records the 0.2.2 events, per author/assignee/closer case."""
        for name, (author, assignee, closer, want) in REOPEN_CASES.items():
            with self.subTest(case=name):
                self.assertEqual(self.run_case(ps, author, assignee, closer), want)

    def test_reopening_reply_events_equal_the_released_v0_2_2(self):
        """The same five cases run through the released v0.2.2 module give identical events."""
        v022 = load_v022()
        if v022 is None:
            self.skipTest("v0.2.2 is not in this clone's history (shallow checkout)")
        for name, (author, assignee, closer, _) in REOPEN_CASES.items():
            with self.subTest(case=name):
                self.assertEqual(self.run_case(ps, author, assignee, closer), self.run_case(v022, author, assignee, closer))


class ViewerTrashControls(BrowserBase):
    """A viewer can open the Trash and read it, but sees no [되살리기]/[영구 삭제] (the server refuses both with 403 anyway)."""
    WHO = CAROL

    def setUp(self):
        super().setUp()
        ps.record_person(A)
        ps.C.people_file.write_text(json.dumps({"version": 1, "people": [
            {"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
            {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"}]}), encoding="utf-8")
        add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "남은 핀"}, A).record["id"]
        self.gone = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "지운 핀"}, A).record["id"]
        ps.drop_pin(self.gone, A)

    def test_viewer_role_sees_no_restore_or_purge_in_the_trash(self):
        """E2E finding: a viewer reads the Trash but gets no [Restore]/[Delete forever] (server refuses with 403 anyway)."""
        for device in DEVICES:
            for lang in ("ko", "en"):
                with self.subTest(device=device, lang=lang):
                    page = self.open(1, lang=lang, **DEVICES[device])
                    page.wait_for_function("DROPPED.length===1", timeout=10000)
                    page.evaluate("openTrash()")
                    page.wait_for_selector("#trash-list .arc-row[data-id=\"%d\"]" % self.gone)
                    row = "#trash-list .arc-row[data-id=\"%d\"]" % self.gone
                    self.assertIn("지운 핀", page.inner_text(row))            # reading stays
                    shown = page.evaluate("[...document.querySelectorAll('#trash [data-act]')].filter(e=>e.getClientRects().length)"
                                          ".map(e=>e.dataset.act)")
                    self.assertFalse({"restore", "purge"} & set(shown), shown)
                    self.assertEqual(page.locator(row + " .b-restore").count() + page.locator(row + " .b-purge").count(), 0)
                    page.evaluate("document.getElementById('trash').close()")
