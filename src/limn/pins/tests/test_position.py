"""limn.pins.location.position - the pure rules of a stored pin's position: estimation, overlap and anchor re-sync.

These tests call the module directly with values: no server, files, clock or subprocess. The same rules are also
pinned through the server in test_locate.py (GET /api/pins's est, re-sync after an edit of the manuscript) and
test_server.py (rel); here each rule's own contract is checked, and that the module stays pure.

Run: uv run pytest -q src/limn/pins/tests/test_position.py
"""

import ast
import time
import unittest
from pathlib import Path

from limn.pins.location import position
from limn.pins.location.mapping import anchor_of, norm
from limn.pins.location.position import AnchorLost, EstContext, Followed
from limn.pins.model import LineSpan, OpenPin, parse_pin

POSITION_PY = Path(position.__file__)
PURE_IMPORTS = {
    "__future__",
    "collections.abc",
    "dataclasses",
    "datetime",
    "typing",
    "limn.pins.location.mapping",
    "limn.pins.thread",
    "limn.pins.model",
    "limn.platform.values",
}

LINES = ["\\section{Intro}", "alpha line one", "beta line two", "", "gamma line four", "delta line five"]


def ctx(cur="pages-2", by=None, built_at=None, bsm=None):
    """An EstContext for the current build cur with the given history entries."""
    return EstContext(cur, by or {}, built_at, bsm)


def parsed(rows):
    """The pins stored records parse to (limn.pins.model.parse_pin), in order."""
    return [parse_pin(r) for r in rows]


def stored_file(pin):
    """A line pin's stored file (its LineSpan's), the file_of the overlap rules count it in when nothing moved."""
    return pin.core.place.file


def resync_record(r, lines, nlines, mtime, path):
    """resync of the open line pin record r parses to, as the record it writes (None when nothing changes)."""
    pin = parse_pin(r)
    new = position.resync(pin, pin.core.place, lines, nlines, mtime, path)
    return None if new is None else new.record


class Purity(unittest.TestCase):
    """The module must not reach files, processes, the clock or the network (architecture.md stop signal)."""

    def test_imports_only_pure_modules(self):
        """Only pure standard modules and the pure limn modules (mapping, the pin lifecycle, model and shapes) are imported."""
        tree = ast.parse(POSITION_PY.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertLessEqual(imported, PURE_IMPORTS)

    def test_reads_no_server_configuration(self):
        """No run setting (C.) or current document appears: every fact arrives as an argument."""
        source = POSITION_PY.read_text(encoding="utf-8")
        self.assertNotIn("C.", source)
        self.assertNotIn("cur_doc(", source)


class Estimation(unittest.TestCase):
    """pin_est: build identity first, anchors before that, the placement time only for a pin without a build."""

    def test_moved_or_lost_anchor_is_estimated_whatever_the_build(self):
        """A stale pin, or one whose sync is not "ok", is dashed even on the build it was placed on."""
        c = ctx()
        self.assertTrue(position.pin_est({"pdf_build": "pages-2", "stale": True}, c))
        self.assertTrue(position.pin_est({"pdf_build": "pages-2", "sync": "moved +3"}, c))
        self.assertFalse(position.pin_est({"pdf_build": "pages-2", "sync": "ok"}, c))

    def test_other_build_is_estimated_only_when_its_source_differs(self):
        """A pin placed on another build is exact when both builds came from the same manuscript hash."""
        by = {"pages-1": {"src_hash": "h1"}, "pages-2": {"src_hash": "h1"}, "pages-0": {"src_hash": "h0"}}
        self.assertFalse(position.pin_est({"pdf_build": "pages-1"}, ctx(by=by)))
        self.assertTrue(position.pin_est({"pdf_build": "pages-0"}, ctx(by=by)))
        self.assertTrue(position.pin_est({"pdf_build": "pages-9"}, ctx(by=by)))  # unknown build: unsure = dashed

    def test_legacy_frac_build_field_takes_the_identity_path(self):
        """frac_build means pdf_build (83b91a5); an empty pdf_build falls through to it."""
        self.assertEqual(position.pin_build({"pdf_build": "", "frac_build": "pages-1"}), "pages-1")
        self.assertIsNone(position.pin_build({"pdf_build": 3}))

    def test_pin_without_build_uses_placement_time_against_the_build(self):
        """Estimated only if placed before the current build finished and the manuscript changed after placing."""
        at = "2026-09-22T09:00:00+09:00"
        placed = position.epoch(at)
        c = ctx(built_at=placed + 3600, bsm=placed + 600)
        self.assertTrue(position.pin_est({"at": at}, c))
        self.assertFalse(position.pin_est({"at": at}, ctx(built_at=placed + 3600, bsm=placed - 600)))
        self.assertFalse(position.pin_est({"at": at}, ctx(built_at=placed - 1, bsm=placed + 600)))
        self.assertFalse(position.pin_est({"at": "not a time"}, c))

    def test_same_source_by_hash_else_mtime_else_different(self):
        """Hashes decide when both exist; otherwise src_mtime within 0.01 s; a missing entry is a different source."""
        self.assertTrue(position.same_source({"src_hash": "x", "src_mtime": 1}, {"src_hash": "x", "src_mtime": 9}))
        self.assertTrue(position.same_source({"src_mtime": 100.0}, {"src_hash": "y", "src_mtime": 100.004}))
        self.assertFalse(position.same_source({"src_mtime": True}, {"src_mtime": True}))
        self.assertFalse(position.same_source(None, {"src_hash": "x"}))

    def test_est_basis_fills_a_current_build_missing_from_history(self):
        """Before the history has the current build, it is judged by the recorded mtime; without one, by history."""
        c = position.est_basis("pages-2", {}, 50.0, 60.0)
        self.assertEqual(
            (c.by["pages-2"], c.built_src_mtime, c.built_at),
            ({"build": "pages-2", "src_mtime": 50.0, "src_hash": None}, 50.0, 60.0),
        )
        self.assertEqual(position.est_basis("pages-2", {"pages-2": {"src_mtime": 7}}, None, None).built_src_mtime, 7.0)
        history = {"pages-1": {}}
        position.est_basis("pages-2", history, None, None)
        self.assertEqual(history, {"pages-1": {}})  # the history read is not changed

    def test_epoch_reads_local_and_offset_times(self):
        """A local 'YYYY-MM-DD HH:MM:SS' is local time; an offset string is absolute; anything else is None."""
        self.assertEqual(position.epoch("2026-09-22 10:00:00"), time.mktime((2026, 9, 22, 10, 0, 0, 0, 0, -1)))
        self.assertEqual(position.epoch("2026-09-22T09:00:00+09:00"), position.epoch("2026-09-22T00:00:00+00:00"))
        for bad in (None, "", "  ", "yesterday", 17):
            self.assertIsNone(position.epoch(bad), repr(bad))


class Overlap(unittest.TestCase):
    """overlaps_by_id and overlaps_for_range: open line pins of one file, by where the caller counts each pin."""

    def test_pairs_relate_inside_contains_partial_and_equal_ranges_by_id(self):
        """Nested, overlapping and equal ranges get their relationship on both sides; equal ranges: smaller id outer."""
        rows = [
            {"id": 1, "file": "a", "lo": 1, "hi": 10},
            {"id": 2, "file": "a", "lo": 3, "hi": 4},
            {"id": 3, "file": "a", "lo": 9, "hi": 12},
            {"id": 5, "file": "a", "lo": 3, "hi": 4},
        ]
        rel = position.overlaps_by_id(parsed(rows), stored_file)
        self.assertEqual(
            rel[1], [{"id": 2, "rel": "contains"}, {"id": 3, "rel": "partial"}, {"id": 5, "rel": "contains"}]
        )
        self.assertEqual(rel[2], [{"id": 1, "rel": "inside"}, {"id": 5, "rel": "contains"}])
        self.assertEqual(rel[5], [{"id": 1, "rel": "inside"}, {"id": 2, "rel": "inside"}])

    def test_counts_pins_in_the_file_the_caller_locates(self):
        """Two pins whose stored paths differ (before and after a moved checkout) overlap when file_of says one file;
        done pins and view-only pins are left out, a view-only open pin still gets an (empty) entry."""
        rows = [
            {"id": 1, "file": "/old/x.tex", "lo": 1, "hi": 5},
            {"id": 2, "file": "/new/x.tex", "lo": 2, "hi": 3},
            {"id": 3, "file": "/new/x.tex", "lo": 1, "hi": 5, "done": True},
            {"id": 4, "pdf": "/ms/figure.pdf", "page": 1, "frac": [0, 0, 0.5, 0.5]},
        ]
        rel = position.overlaps_by_id(parsed(rows), lambda pin: "x.tex")
        self.assertEqual(rel, {1: [{"id": 2, "rel": "contains"}], 2: [{"id": 1, "rel": "inside"}], 4: []})
        self.assertEqual(position.overlaps_by_id(parsed(rows), stored_file), {1: [], 2: [], 4: []})

    def test_equal_ranges_keep_pair_order_when_ids_are_out_of_order(self):
        """A smaller id is the outer range even when it appears later, and each list follows input pair order."""
        rows = [
            {"id": 9, "file": "a", "lo": 2, "hi": 4},
            {"id": 2, "file": "a", "lo": 2, "hi": 4},
            {"id": 6, "file": "a", "lo": 2, "hi": 4},
        ]
        self.assertEqual(
            position.overlaps_by_id(parsed(rows), stored_file),
            {
                9: [{"id": 2, "rel": "inside"}, {"id": 6, "rel": "inside"}],
                2: [{"id": 9, "rel": "contains"}, {"id": 6, "rel": "contains"}],
                6: [{"id": 9, "rel": "contains"}, {"id": 2, "rel": "inside"}],
            },
        )

    def test_selection_relation_names_equal_separately(self):
        """A new selection has no id, so an identical range is "equal"; the others are as between pins."""
        self.assertEqual(
            [position.selection_rel(*c) for c in ((4, 9, 4, 9), (5, 6, 4, 9), (3, 10, 4, 9), (8, 12, 4, 9))],
            ["equal", "inside", "contains", "partial"],
        )
        self.assertIsNone(position.selection_rel(10, 12, 4, 9))

    def test_overlaps_for_range_lists_open_pins_of_that_file(self):
        """Only open line pins counted in the same file and overlapping the range, with their range and relation."""
        rows = [
            {"id": 1, "file": "a", "lo": 4, "hi": 9},
            {"id": 2, "file": "b", "lo": 4, "hi": 9},
            {"id": 3, "file": "a", "lo": 4, "hi": 9, "done": True},
            {"id": 4, "file": "a", "lo": 20, "hi": 21},
        ]
        self.assertEqual(
            position.overlaps_for_range("a", 4, 9, parsed(rows), stored_file),
            [{"id": 1, "lo": 4, "hi": 9, "rel": "equal"}],
        )


class AnchorResync(unittest.TestCase):
    """follow_anchor and resync: lines follow the anchor; the record says how, and only changes when it must."""

    def pin(self, lo=2, hi=3, **extra):
        """An open pin on LINES lo..hi with its anchor, synced at mtime 100."""
        return dict(
            {
                "id": 1,
                "file": "/ms/main.tex",
                "lo": lo,
                "hi": hi,
                "anchor": anchor_of(LINES, lo, hi),
                "synced_at": 100.0,
                "rev": 2,
            },
            **extra,
        )

    def test_follow_anchor_after_lines_inserted_above(self):
        """Two lines inserted above: the range moves down by two, and says so."""
        edited = ["new a", "new b"] + LINES
        got = position.follow_anchor(anchor_of(LINES, 2, 3), 2, 3, [norm(t) for t in edited])
        self.assertEqual(got, Followed(4, 5, "moved +2"))

    def test_follow_anchor_loses_a_deleted_head(self):
        """The head line is gone: the anchor is lost."""
        edited = [t for t in LINES if t != "alpha line one"]
        self.assertEqual(position.follow_anchor(anchor_of(LINES, 2, 3), 2, 3, [norm(t) for t in edited]), AnchorLost())

    def test_resync_leaves_a_pin_alone_when_the_file_is_not_newer(self):
        """synced_at >= mtime on the stored file: nothing to do (None)."""
        self.assertIsNone(resync_record(self.pin(), LINES, [norm(t) for t in LINES], 100.0, "/ms/main.tex"))

    def test_resync_moves_lines_bumps_rev_and_keeps_key_order(self):
        """A newer file with lines moved: lo/hi follow, sync "moved +1", rev+1, synced_at; the input is not changed and
        the copy keeps the stored key order (pins.jsonl bytes)."""
        r = self.pin(stale=True)
        edited = ["inserted"] + LINES
        new = resync_record(r, edited, [norm(t) for t in edited], 200.0, "/ms/main.tex")
        self.assertEqual(
            (new["lo"], new["hi"], new["sync"], new["rev"], new["synced_at"]), (3, 4, "moved +1", 3, 200.0)
        )
        self.assertNotIn("stale", new)
        self.assertEqual(list(new), ["id", "file", "lo", "hi", "anchor", "synced_at", "rev", "sync"])
        self.assertEqual(r["lo"], 2)

    def test_resync_unmoved_lines_keep_rev(self):
        """A newer file whose pinned lines did not move: sync "ok", synced_at updated, rev unchanged."""
        new = resync_record(self.pin(), LINES, [norm(t) for t in LINES], 200.0, "/ms/main.tex")
        self.assertEqual((new["lo"], new["hi"], new["sync"], new["rev"], new["synced_at"]), (2, 3, "ok", 2, 200.0))

    def test_resync_lost_anchor_marks_stale(self):
        """The anchor's head is gone: stale, sync "lost", rev+1, the old numbers kept."""
        edited = [t for t in LINES if t != "alpha line one"]
        new = resync_record(self.pin(), edited, [norm(t) for t in edited], 200.0, "/ms/main.tex")
        self.assertEqual((new["lo"], new["hi"], new["stale"], new["sync"], new["rev"]), (2, 3, True, "lost", 3))

    def test_resync_backfills_a_legacy_anchor_only_from_its_own_file(self):
        """A pin without an anchor gets one from its stored file, never from a located file it does not name."""
        legacy = {"id": 1, "file": "/ms/main.tex", "lo": 2, "hi": 3}
        new = resync_record(legacy, LINES, [norm(t) for t in LINES], 50.0, "/ms/main.tex")
        self.assertEqual((new["anchor"], new["synced_at"]), (anchor_of(LINES, 2, 3), 50.0))
        self.assertIsNone(resync_record(legacy, LINES, [norm(t) for t in LINES], 50.0, "/new/main.tex"))

    def test_resync_counts_a_null_synced_at_as_never_synced(self):
        """A record the check accepts may store synced_at: null; it reads as 0, so a newer file re-matches the pin
        (the raw read compared None with the mtime and raised on every request)."""
        new = resync_record(self.pin(synced_at=None), LINES, [norm(t) for t in LINES], 200.0, "/ms/main.tex")
        self.assertEqual((new["sync"], new["synced_at"], new["rev"]), ("ok", 200.0, 2))

    def test_resync_blank_anchor_has_nothing_to_follow(self):
        """A pin that selected only blank lines (empty anchor) is never re-matched."""
        self.assertIsNone(resync_record(self.pin(anchor={}), LINES, [norm(t) for t in LINES], 999.0, "/ms/main.tex"))

    def test_resync_moved_record_rematches_when_anchor_no_longer_holds_and_records_the_file(self):
        """Located elsewhere (moved checkout) with synced_at not older: kept while the anchor holds at lo; re-matched,
        with `file` set to the located path, once it does not."""
        nlines = [norm(t) for t in LINES]
        self.assertIsNone(resync_record(self.pin(), LINES, nlines, 50.0, "/new/main.tex"))
        shifted = ["x"] + LINES
        new = resync_record(self.pin(), shifted, [norm(t) for t in shifted], 50.0, "/new/main.tex")
        self.assertEqual((new["lo"], new["file"], new["synced_at"]), (3, "/new/main.tex", 50.0))
        self.assertNotIn("file_rel", new)


class SelectionRelation(unittest.TestCase):
    """selection_rel() names how a selected range relates to a pin's: equal, inside, contains, partial, or None."""

    def test_selection_rel_all_four_relations(self):
        self.assertEqual(position.selection_rel(4, 9, 4, 9), "equal")
        self.assertEqual(position.selection_rel(5, 6, 4, 9), "inside")
        self.assertEqual(position.selection_rel(3, 10, 4, 9), "contains")
        self.assertEqual(position.selection_rel(8, 12, 4, 9), "partial")
        self.assertIsNone(position.selection_rel(10, 12, 4, 9))


class FigureAnchorBackfill(unittest.TestCase):
    """A legacy pin on a Python script gets an anchor that skips # comment lines."""

    def test_a_python_pin_without_an_anchor_is_backfilled_past_its_comment(self):
        """The first line of the range is a # comment: head is the code line after it, head_off 1."""
        lines = ["x = 0", "# July cell", "cell = month(7)"]
        pin = OpenPin.from_record({"id": 1, "file": "/ms/figs/a.py", "lo": 2, "hi": 3})
        out = position.resync(
            pin, LineSpan("/ms/figs/a.py", 2, 3), lines, [norm(t) for t in lines], 5.0, "/ms/figs/a.py"
        )
        self.assertEqual(
            out.record["anchor"], {"head": "cell = month(7)", "tail": "cell = month(7)", "head_off": 1, "tail_off": 0}
        )


if __name__ == "__main__":
    unittest.main()
