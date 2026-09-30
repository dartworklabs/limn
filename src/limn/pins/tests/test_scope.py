"""Pin revision projections and revision scoping on their own.

Every revision route runs end to end through the handler in test_revisions.py. Here: limn.revisions.scope stays pure (no file,
process, clock or HTTP import), neither module reads the server's globals or imports server.py or the HTTP layer,
and a refusal is a returned value of the ScopeRefusal set. The classes after them are the attribution rules of
pin-scoped [View changes] (v0.3, issue #9, docs/adr/0005-pin-scoped-changes.md): git's -U0 output read into blocks,
which blocks of a commit belong to a pin (recorded changes, else the pin's range mapped through the commit), the
pin's patch with git's own line numbers, and the synthetic new version (old + only the pin's blocks), checked
against real git.

Run: uv run pytest -q src/limn/pins/tests/test_scope.py
"""

import ast
import json
import random
import shutil
import subprocess
import sys
import tempfile
import typing
import unittest
from pathlib import Path

from limn.pins.location.mapping import anchor_of
from limn.pins.revision import revision_pin, valid_changes
from limn.revisions import core as revisions, scope as scoping
from limn.revisions.answer import SCOPE_REJECTIONS, scope_http_error
from limn.revisions.core import matching_pin_changes

from helpers import extract_js_fn, run_node
from helpers_access import REPO_NEW as NEW, REPO_OLD as OLD

PKG = Path(__file__).resolve().parents[4] / "src" / "limn"
PURE_IMPORTS = {
    "__future__",
    "re",
    "collections.abc",
    "dataclasses",
    "typing",
    "limn.pins",
    "limn.pins.location.mapping",
}


def imports_of(path: Path) -> set:
    """Every module name a file imports (import x / from x import y)."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


class Boundaries(unittest.TestCase):
    """What each module may reach."""

    def test_scope_imports_only_pure_modules(self):
        """A file, subprocess or HTTP import in revisions.scope would put an effect inside the decision."""
        self.assertLessEqual(imports_of(PKG / "revisions/scope.py"), PURE_IMPORTS)

    def test_neither_module_reads_server_globals(self):
        """The document and the instance's settings arrive as arguments (R5): no C., no cur_doc()."""
        for name in (
            "pins/revision.py",
            "revisions/scope.py",
            "revisions/core.py",
            "revisions/execution.py",
            "revisions/jobs.py",
            "runtime/documents.py",
        ):
            with self.subTest(module=name):
                source = (PKG / name).read_text(encoding="utf-8")
                self.assertNotRegex(source, r"(?<![\w.])C\.[a-z_]")
                self.assertNotIn("cur_doc(", source)

    def test_no_current_document_anywhere(self):
        """The document is an argument (R5): server.py and the HTTP layer keep no thread-local "current document"."""
        for path in [PKG / "server.py"] + sorted((PKG / "web").glob("*.py")):
            with self.subTest(module=path.name):
                source = path.read_text(encoding="utf-8")
                for name in ("cur_doc(", "using_doc(", "threading.local("):
                    self.assertNotIn(name, source)

    def test_revisions_loads_without_server_or_the_http_layer(self):
        """The revision core answers with values; the HTTP layer imports it, never the other way round."""
        for name in ("core.py", "execution.py", "jobs.py"):
            with self.subTest(module=name):
                self.assertFalse(
                    {n for n in imports_of(PKG / "revisions" / name) if n.startswith("limn.web") or n == "limn.server"}
                )
        code = "import sys, limn.revisions.core; print(sorted(m for m in sys.modules if m.startswith('limn.web') or 'server' in m))"
        r = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False, cwd=str(PKG.parent)
        )
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "[]"), r.stderr)


class RevisionProjection(unittest.TestCase):
    """Stored pin details cross into revision attribution as one immutable projection."""

    def test_revision_pin_keeps_only_commit_scoping_facts(self):
        """The projection binds current location and only the changes recorded for the requested commit."""
        head = "a" * 40
        record = {
            "id": 7,
            "file": "/old/paper/main.tex",
            "lo": 4,
            "hi": 6,
            "done_at": "2026-09-30 10:00:00",
            "changes_at": "2026-09-30 10:00:00",
            "close_ref": head[:8],
            "changes": [{"file": "paper/main.tex", "lo": 10, "hi": 12}],
            "thread": [{"kind": "note", "body": "must not cross"}],
        }

        projection = revision_pin(record, relative_path="paper/main.tex")

        self.assertEqual(projection.id, 7)
        self.assertEqual(projection.changes, (("paper/main.tex", 10, 12),))
        self.assertFalse(hasattr(projection, "thread"))


class Refusals(unittest.TestCase):
    """A pin-scoping refusal is one frozen value per case, named together as ScopeRefusal."""

    def test_refusal_set_names_one_type_per_case(self):
        """Five cases, each a frozen dataclass without data (they differ in their answer, not their data)."""
        kinds = typing.get_args(scoping.ScopeRefusal)
        self.assertEqual(
            {k.__name__ for k in kinds},
            {"PinNotInDoc", "ScopeUnreadable", "ScopeMismatch", "UnsafePath", "ScopeUnwritable"},
        )
        for k in kinds:
            self.assertEqual(k(), k())
        self.assertIn(scoping.PinNotInDoc, typing.get_args(revisions.DiffRefusal))

    def test_plan_refuses_with_values(self):
        """plan_scope_writes returns its refusal instead of raising: nothing to read, or a path that could escape."""
        self.assertEqual(scoping.plan_scope_writes(None, [], "."), scoping.ScopeUnreadable())
        f = scoping.FileChange("../x.tex", "../x.tex", (b"a\n",), (b"b\n",), (scoping.Block(0, 1, 0, 1),), False)
        self.assertEqual(
            scoping.plan_scope_writes([f], [("../x.tex", "../x.tex", 0, 1, 0, 1)], "."), scoping.UnsafePath()
        )
        self.assertEqual(scoping.plan_scope_writes([], [], "."), [])


# ---------------------------------------------------------------- pin-scoped changes (v0.3, issue #9): blocks, attribution, the scoped patch, applying


# The -U0 hunks git prints for OLD -> NEW (checked against real git in GitBlocks below).
U0 = (
    b"@@ -4 +4,2 @@\n-Alpha paragraph talks about apples.\n+Alpha paragraph talks about apples and pears.\n+A second alpha sentence.\n"
    b"@@ -11 +12 @@\n-Beta paragraph talks about bananas.\n+Beta paragraph talks about blueberries.\n"
    b"@@ -18 +18,0 @@\n-Gamma paragraph talks about cherries.\n"
)
A_BLK, B_BLK, C_BLK = (3, 1, 3, 2), (10, 1, 11, 1), (17, 1, 18, 0)


def fc(old=OLD, new=NEW, patch=U0, old_path="ms/main.tex", new_path="ms/main.tex"):
    """The FileChange of one file from old to new text with the -U0 hunks `patch` (U0 describes OLD -> NEW)."""
    o, n = old.encode(), new.encode()
    return scoping.FileChange(
        old_path, new_path, scoping.git_lines(o), scoping.git_lines(n), tuple(scoping.parse_u0_blocks(patch)), False
    )


def anchored(lo, hi, text=OLD, **extra):
    """A pin record whose anchor was captured from `text` (what add_pin stores)."""
    lines = text.split("\n")
    return dict({"id": 1, "file": "/x/ms/main.tex", "lo": lo, "hi": hi, "anchor": anchor_of(lines, lo, hi)}, **extra)


def projected(record, rel="ms/main.tex", head="", revisions=()):
    """Build the pin-owned projection used by pure attribution tests."""
    return matching_pin_changes(revision_pin(record, relative_path=rel), head, revisions)


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
        self.assertEqual(tuple(scoping.parse_u0_blocks(b"@@ -0,0 +1,3 @@\n+a\n+b\n+c\n")[0]), (0, 0, 0, 3))  # new file
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
        source, chosen = scoping.attribute_blocks(self.files, projected(pin, rel), changes or [])
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
        self.assertEqual(
            self.blocks_for({"id": 1, "file": "/x", "lo": 11, "hi": 11, "stale": True}), ("inferred", [B_BLK])
        )
        self.assertEqual(self.blocks_for({"id": 1, "file": "/x", "lo": 7, "hi": 8}), ("none", []))

    def test_deleted_lines_are_attributed_through_the_old_side(self):
        """A pin whose text the commit deleted gets that deletion."""
        self.assertEqual(self.blocks_for(anchored(18, 18, stale=True, sync="lost")), ("inferred", [C_BLK]))

    def test_three_pins_in_one_commit_get_disjoint_hunks_that_cover_the_commit(self):
        """The issue #9 case: three pins fixed in one commit each get their own block, and together all of them."""
        pins = [anchored(4, 4), anchored(11, 11, stale=True), anchored(18, 18, stale=True)]
        got = [set(scoping.attribute_blocks(self.files, projected(p), [])[1]) for p in pins]
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
        self.assertEqual(
            self.blocks_for(pin, changes=[("ms/main.tex", 4, 5), ("ms/main.tex", 12, 12)]), ("changes", [A_BLK, B_BLK])
        )
        # ranges that hit nothing in this commit (a different commit, a wrong file) fall back to inference
        self.assertEqual(self.blocks_for(pin, changes=[("ms/main.tex", 7, 8)]), ("inferred", [A_BLK]))
        self.assertEqual(self.blocks_for(pin, changes=[("ms/x.tex", 4, 5)]), ("inferred", [A_BLK]))

    def test_a_region_pin_or_a_pin_without_lines_gets_nothing(self):
        """A view-only PDF pin has no lines, so it is never attributed (whole commit)."""
        self.assertEqual(
            self.blocks_for({"id": 1, "pdf": "/x.pdf", "page": 1, "frac": [0, 0, 1, 1]}, rel=None), ("none", [])
        )


class ScopedPatch(unittest.TestCase):
    """The pin's / the other blocks rendered as git-style patches with the commit's real line numbers (pure)."""

    def setUp(self):
        self.files = [fc()]

    def test_payload_cuts_patches_in_bytes_and_says_so(self):
        """Review finding: scoped patches are cut at 256 KiB in UTF-8 bytes and flagged, like the whole diff."""
        big = "".join("줄 %d 한국어 문장입니다\n" % i for i in range(20000))
        f = fc(big, big.replace("줄 5 ", "줄 5! "), b"@@ -6 +6 @@\n", old_path="ms/big.tex", new_path="ms/big.tex")
        files = [f, fc()]
        sc = scoping.pin_scope(
            files,
            projected({"id": 1, "file": "/x", "lo": 2, "hi": 2}),
            [scoping.RepoRange("ms/main.tex", 12, 12)],
        )
        out = scoping.scope_payload(sc)
        self.assertEqual((out["mode"], out["truncated"], out["other_truncated"]), ("pin", False, False))
        f = fc(
            big, big.replace("\n", " x\n"), b"@@ -1,20000 +1,20000 @@\n", old_path="ms/big.tex", new_path="ms/big.tex"
        )
        sc = scoping.pin_scope(
            [f, fc()],
            projected({"id": 1, "file": "/x", "lo": 2, "hi": 2}),
            [scoping.RepoRange("ms/main.tex", 12, 12)],
        )
        out = scoping.scope_payload(sc)
        self.assertTrue(out["other_truncated"])
        self.assertLessEqual(len(out["other_diff"].encode()), scoping.REVISION_DIFF_MAX)

    def test_pin_hunk_keeps_real_new_side_line_numbers_and_no_foreign_lines(self):
        """The pin's hunk shows the commit's real new-side numbers (so highlighting works) and none of another pin's lines."""
        text, n = scoping.scoped_patch(self.files, {(0, 1)}, True)
        self.assertEqual(n, 1)
        self.assertEqual(
            text,
            "diff --git a/ms/main.tex b/ms/main.tex\n--- a/ms/main.tex\n+++ b/ms/main.tex\n"
            "@@ -8,7 +9,7 @@\n Filler three.\n Filler four.\n \n-Beta paragraph talks about bananas.\n"
            "+Beta paragraph talks about blueberries.\n \n Filler five.\n Filler six.\n",
        )
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
        self.assertEqual(n, 2)  # l5 (someone else's) splits them
        self.assertNotIn("l5", text)
        self.assertNotIn("L5", text)
        self.assertIn("@@ -1,4 +1,4 @@\n l1\n l2\n-l3\n+L3\n l4\n", text)
        self.assertIn("@@ -6,5 +6,5 @@\n l6\n-l7\n+L7\n l8\n l9\n l10\n", text)
        text, n = scoping.scoped_patch(files, {(0, 0), (0, 1)}, True)
        self.assertEqual(n, 2)  # two changed spots, shown in one hunk
        self.assertEqual(text.count("@@ -"), 1)
        self.assertIn("@@ -1,6 +1,6 @@\n l1\n l2\n-l3\n+L3\n l4\n-l5\n+L5\n l6\n", text)

    def test_missing_final_newline_is_marked_like_git(self):
        """A last line without a newline gets git's marker in both - and + forms."""
        files = [
            fc("a\nb", "a\nc", b"@@ -2 +2 @@\n-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n")
        ]
        text, _ = scoping.scoped_patch(files, {(0, 0)}, True)
        self.assertTrue(text.endswith("-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n"), text)

    def test_file_headers_name_new_deleted_and_renamed_files_like_git(self):
        """Scoped patches keep git's file headers so the viewer's file list and names still work."""
        files = [
            fc("", "x\n", b"@@ -0,0 +1 @@\n+x\n", old_path=None, new_path="ms/n.tex"),
            fc("y\n", "", b"@@ -1 +0,0 @@\n-y\n", old_path="ms/d.tex", new_path=None),
            fc(OLD, NEW, U0, old_path="ms/a.tex", new_path="ms/b.tex"),
        ]
        text, n = scoping.scoped_patch(files, {(0, 0), (1, 0), (2, 0)}, True)
        self.assertIn(
            "diff --git a/ms/n.tex b/ms/n.tex\nnew file mode 100644\n--- /dev/null\n+++ b/ms/n.tex\n@@ -0,0 +1,1 @@\n+x\n",
            text,
        )
        self.assertIn(
            "diff --git a/ms/d.tex b/ms/d.tex\ndeleted file mode 100644\n--- a/ms/d.tex\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-y\n",
            text,
        )
        self.assertIn(
            "diff --git a/ms/a.tex b/ms/b.tex\nrename from ms/a.tex\nrename to ms/b.tex\n--- a/ms/a.tex\n+++ b/ms/b.tex\n",
            text,
        )
        self.assertEqual(n, 3)

    def test_rename_only_and_binary_files_count_as_other_places(self):
        """A pure rename or a binary file is never the pin's; it is one of the "other changes"."""
        files = [
            fc(),
            scoping.FileChange("ms/fig.tex", "ms/fig2.tex", (), (), (), False),
            scoping.FileChange("ms/x.bib", "ms/x.bib", (), (), (), True),
        ]
        text, n = scoping.scoped_patch(files, {(0, 0), (0, 1), (0, 2)}, False)
        self.assertEqual(n, 2)
        self.assertIn("rename from ms/fig.tex", text)
        self.assertIn("Binary files a/ms/x.bib and b/ms/x.bib differ", text)


class ScopeDecisions(unittest.TestCase):
    """The pure decisions around the scoped build and responses (coding rule R1): which recorded changes count, what to
    write into the synthetic tree, and how a refusal becomes a response - no file, git or HTTP needed."""

    def test_recorded_ranges_and_stored_list_use_the_same_shape_rule(self):
        """The store rejects a list with one malformed range, while attribution keeps only valid items in that list."""
        good = {"file": "/m/main.tex", "lo": 3, "hi": 4, "future": "kept"}
        malformed = ({"file": 3, "lo": 1, "hi": 1}, {"file": "/m/main.tex", "lo": True, "hi": 2})
        self.assertTrue(valid_changes([good]))
        self.assertFalse(valid_changes([good, *malformed]))
        head = "a" * 40
        pin = {
            "done_at": "2026-09-25 10:00:00",
            "changes_at": "2026-09-25 10:00:00",
            "close_ref": head[:7],
            "changes": [good, *malformed],
        }
        pin["id"] = 1
        self.assertEqual(
            projected(pin, head=head, revisions=[{"id": head, "subject": "fix"}]).changes, (("/m/main.tex", 3, 4),)
        )

    def test_recorded_changes_count_only_for_their_close_and_their_commit(self):
        """changes_at must equal done_at, and the commit asked about must be the one close_ref names (review M1:
        another commit's lines must not select a different pin's fix); malformed items are skipped."""
        good = {"file": "/m/main.tex", "lo": 3, "hi": 4}
        X, Y = "a" * 40, "b" * 40
        revs = [{"id": Y, "subject": "fix B (#8)"}, {"id": X, "subject": "fix A (#7)"}]
        pin = {
            "done_at": "2026-09-25 10:00:00",
            "changes_at": "2026-09-25 10:00:00",
            "close_ref": "PR #7 (%s)" % X[:7],
            "changes": [good, {"file": 3, "lo": 1, "hi": 1}],
        }
        pin["id"] = 1
        self.assertEqual(projected(pin, head=X, revisions=revs).changes, (("/m/main.tex", 3, 4),))
        self.assertEqual(projected(pin, head=Y, revisions=revs).changes, ())  # another commit: inference decides
        # the squash commit by PR
        self.assertEqual(
            projected(dict(pin, close_ref="PR #7"), head=X, revisions=revs).changes, (("/m/main.tex", 3, 4),)
        )
        self.assertEqual(
            projected(dict(pin, close_ref="PR #7 (cccc111)"), head=X, revisions=revs).changes, (("/m/main.tex", 3, 4),)
        )
        self.assertEqual(projected(dict(pin, close_ref=""), head=X, revisions=revs).changes, ())
        self.assertEqual(projected(dict(pin, done_at="2026-09-26 09:00:00"), head=X, revisions=revs).changes, ())
        self.assertEqual(projected({"id": 1, "done_at": "2026-09-25 10:00:00"}, head=X, revisions=revs).changes, ())
        self.assertEqual(projected({"id": 1}, head=X, revisions=revs).changes, ())

    def test_ref_commit_matches_the_viewers_match_revision(self):
        """The server binds changes with the same rule the viewer uses to pick the commit (matchRevision): hash prefix
        first, then the PR number in the subject. Both implementations answer every case alike."""
        revs = [
            {"id": "0a569cc" + "1" * 33, "subject": "Clarify experimental questions (#238)"},
            {"id": "2cb7240" + "2" * 33, "subject": "Resolve manuscript viewer pins 19–41 (#236)"},
            {"id": "f47c6bf" + "3" * 33, "subject": "manuscript: 원고 핀 12건 반영 (#235)"},
            {"id": "1d422a6" + "4" * 33, "subject": "Merge pull request #203 from example-lab/docs"},
        ]
        refs = [
            "PR #235 (f47c6bf)",
            "paper PR #236; code PR #75",
            "paper PR #236",
            "#203",
            "PR #999",
            "",
            "abcdef1",
            "커밋f47c6bf",
            "PR #236 (deadbee)",
            None,
        ]

        def matched(ref):
            record = {
                "id": 1,
                "done_at": "now",
                "changes_at": "now",
                "close_ref": ref,
                "changes": [{"file": "/m.tex", "lo": 1, "hi": 1}],
            }
            return next((row["id"] for row in revs if projected(record, head=row["id"], revisions=revs).changes), None)

        py = [matched(ref) for ref in refs]
        self.assertEqual(
            [x and x[:7] for x in py],
            ["f47c6bf", "2cb7240", "2cb7240", "1d422a6", None, None, None, "f47c6bf", "2cb7240", None],
        )
        if shutil.which("node"):
            js = run_node(
                extract_js_fn("matchRevision") + "\nconsole.log(JSON.stringify(%s.map(r=>{const m=matchRevision(r,%s);"
                "return m&&m.id;})));" % (json.dumps(refs), json.dumps(revs))
            )
            self.assertEqual(json.loads(js), py)

    def test_raw_entries_of_symlinks_and_submodules_have_no_blocks(self):
        """Review m6: --raw modes 120000 (symlink) and 160000 (submodule) are never read as text; the whole-commit
        snapshot rejects them, so the pin view must not turn them into editable blocks either."""
        z = "0" * 40
        raw = (
            b":100644 120000 " + (b"1" * 40) + b" " + (b"2" * 40) + b" T\0ms/sec.tex\0"
            b":000000 160000 " + z.encode() + b" " + (b"3" * 40) + b" A\0ms/sub\0"
            b":100644 100644 " + (b"4" * 40) + b" " + (b"5" * 40) + b" R087\0ms/a.tex\0ms/b.tex\0"
        )
        got = scoping.parse_raw_entries(raw)
        self.assertEqual(
            [(e.old_path, e.new_path, e.text) for e in got],
            [("ms/sec.tex", "ms/sec.tex", False), (None, "ms/sub", False), ("ms/a.tex", "ms/b.tex", True)],
        )
        self.assertEqual(got[0].modes, ("100644", "120000"))

    def test_scope_writes_apply_only_the_scope_under_the_build_root(self):
        """Only the scope's blocks are applied, files outside the build root are skipped, a deleted file is removed."""
        f = fc(old_path="ms/main.tex", new_path="ms/main.tex")
        outside = fc(old_path="other/x.tex", new_path="other/x.tex")
        gone = scoping.FileChange("ms/old.tex", None, (b"x\n",), (), (scoping.Block(0, 1, 0, 0),), False)
        scope = [
            ("ms/main.tex", "ms/main.tex") + B_BLK,
            ("other/x.tex", "other/x.tex") + A_BLK,
            ("ms/old.tex", "") + (0, 1, 0, 0),
        ]
        writes = scoping.plan_scope_writes([f, outside, gone], scope, "ms")
        self.assertEqual(
            writes,
            [
                scoping.ScopeWrite("main.tex", OLD.replace("bananas", "blueberries").encode()),
                scoping.ScopeWrite("old.tex", None),
            ],
        )
        self.assertEqual(
            scoping.plan_scope_writes([f], [("ms/main.tex", "ms/main.tex") + A_BLK], ".")[0].rel, "ms/main.tex"
        )

    def test_scope_writes_refuse_unreadable_unsafe_and_missing_blocks(self):
        """Each refusal is its own returned value: no files, a path that could leave the snapshot, a block not found again."""
        f = fc()
        cases = (
            (None, [("ms/main.tex", "ms/main.tex") + A_BLK], scoping.ScopeUnreadable()),
            ([f], [("ms/main.tex", "ms/main.tex") + (0, 1, 0, 1)], scoping.ScopeMismatch()),
        )
        for files, scope, refusal in cases:
            with self.subTest(refusal=refusal):
                self.assertEqual(scoping.plan_scope_writes(files, scope, "ms"), refusal)
        for bad in ("ms/../x.tex", "ms/.git/config", "ms/a\\b.tex", "ms/\x01.tex"):
            with self.subTest(path=bad):
                self.assertEqual(
                    scoping.plan_scope_writes([f._replace(old_path=bad, new_path=bad)], [(bad, bad) + A_BLK], "ms"),
                    scoping.UnsafePath(),
                )

    def test_every_rejection_maps_to_one_status_and_body(self):
        """The one SCOPE_REJECTIONS table: status, Korean message and API reason per refusal type (agent contract), one
        row for every member of limn.revisions.scope.ScopeRefusal. The 404 gained its reason in 0.3.4 (every refusal names one,
        src/limn/web/tests/test_errors.py); its text is unchanged."""
        want = {
            scoping.PinNotInDoc: (404, {"error": "이 문서의 핀이 아닙니다.", "reason": "pin_not_in_doc"}),
            scoping.ScopeUnreadable: (
                422,
                {"error": "이 핀의 변경만 골라 적용하지 못했습니다.", "reason": "scope_failed"},
            ),
            scoping.ScopeMismatch: (
                422,
                {"error": "이 핀의 변경을 커밋에서 다시 찾지 못했습니다.", "reason": "scope_failed"},
            ),
            scoping.UnsafePath: (422, {"error": "사본에 허용되지 않는 경로가 있습니다.", "reason": "unsafe_snapshot"}),
            scoping.ScopeUnwritable: (
                422,
                {"error": "이 핀의 변경만 넣은 사본을 쓰지 못했습니다.", "reason": "scope_failed"},
            ),
        }
        self.assertEqual(set(SCOPE_REJECTIONS), set(want))
        self.assertEqual(set(SCOPE_REJECTIONS), set(typing.get_args(scoping.ScopeRefusal)))
        for kind, (code, body) in want.items():
            e = scope_http_error(kind())
            self.assertEqual((e.code, e.body), (code, body))

    def test_scope_meta_and_payload_have_their_documented_keys(self):
        """ScopeMeta has the five status fields; the payload adds the patches only in mode pin."""
        sc = scoping.pin_scope([fc()], projected(dict(anchored(4, 4), id=7)), [])
        self.assertEqual(
            scoping.scope_meta(sc), {"scope": "pin", "pin": 7, "source": "inferred", "hunks": 1, "other": 2}
        )
        self.assertEqual(
            sorted(scoping.scope_payload(sc)),
            ["diff", "hunks", "mode", "other", "other_diff", "other_truncated", "pin", "source", "truncated"],
        )
        whole = scoping.pin_scope(None, projected(dict(anchored(4, 4), id=7)), [])
        self.assertEqual(
            scoping.scope_payload(whole), {"pin": 7, "mode": "commit", "source": "none", "hunks": 0, "other": 0}
        )


class ApplyBlocks(unittest.TestCase):
    """The synthetic old + chosen blocks version the scoped comparison PDF compiles (pure)."""

    def test_synthetic_new_version_is_old_plus_only_the_chosen_blocks(self):
        """The comparison PDF's new side is exactly old + the chosen blocks (all = new, none = old)."""
        f = fc()
        self.assertEqual(scoping.apply_blocks(f, {0, 1, 2}), NEW.encode())
        self.assertEqual(scoping.apply_blocks(f, set()), OLD.encode())
        self.assertEqual(scoping.apply_blocks(f, {1}), OLD.replace("bananas", "blueberries").encode())
        self.assertEqual(
            scoping.apply_blocks(f, {2}), OLD.replace("Gamma paragraph talks about cherries.\n", "").encode()
        )

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
            r = subprocess.run(
                ["git", "diff", "--no-index", "--no-color", "-U0", str(a), str(b)], capture_output=True, check=False
            )
            return r.stdout

    def git_apply(self, old: bytes, patch: str) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            Path(d, "m.tex").write_bytes(old)
            subprocess.run(
                ["git", "apply", "--unidiff-zero", "-"], cwd=d, input=patch.encode(), check=True, capture_output=True
            )
            return Path(d, "m.tex").read_bytes()

    def test_fixture_blocks_match_what_git_prints(self):
        """The hand-written fixture hunks are what real git prints for OLD -> NEW."""
        self.assertEqual(
            [tuple(b) for b in scoping.parse_u0_blocks(self.u0(OLD.encode(), NEW.encode()))], [A_BLK, B_BLK, C_BLK]
        )

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
            f = scoping.FileChange(
                "m.tex",
                "m.tex",
                scoping.git_lines(o),
                scoping.git_lines(n),
                tuple(scoping.parse_u0_blocks(self.u0(o, n))),
                False,
            )
            self.assertEqual(scoping.apply_blocks(f, set(range(len(f.blocks)))), n)
            self.assertEqual(scoping.apply_blocks(f, set()), o)
            if f.blocks:
                # any subset: old outside the chosen blocks, new inside them, in order
                chosen = {k for k in range(len(f.blocks)) if rnd.random() < 0.5}
                want, pos = [], 0
                for k, b in enumerate(f.blocks):
                    if k in chosen:
                        want += f.old[pos : b.old_lo] + f.new[b.new_lo : b.new_lo + b.new_n]
                        pos = b.old_lo + b.old_n
                self.assertEqual(scoping.apply_blocks(f, chosen), b"".join(want + list(f.old[pos:])))
                # and the scoped patch of those blocks, applied by git to old, gives exactly that
                text, _ = scoping.scoped_patch([f], {(0, k) for k in chosen}, True)
                if chosen:
                    self.assertEqual(self.git_apply(o, text), scoping.apply_blocks(f, chosen))


if __name__ == "__main__":
    unittest.main()
