"""Shared pin location plus the PDF selection feature, driven by their arguments (coding rule R5).

Re-sync, estimation and overlaps are pinned through server.py at the end of this file (Anchor, Estimate,
ServerOverlaps); picking and the overlap routes through the handler in test_server.py (OverlapRoutes) and
test_moved_paths.py. The classes above call the
module directly, with no server and no run arguments: it must not read them, and its re-sync and token weights work
on the files and cache they are handed.

Run: uv run pytest -q src/limn/pins/tests/test_locate.py
"""

import ast
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from limn.builds import artifacts as limn_build, run as build_run
from limn.builds.answer import build_failure_log
from limn.builds.artifacts import BuildFailed, BuildOk, BuildOkWithErrors
from limn.pins.location import (
    input as location_input,
    lookup as locate,
    position,
    range as source_range,
    resolve as pick_resolve,
    source as pick_source,
)
from limn.pins.location.mapping import anchor_of
from limn.pins.model import parse_pin
from limn.security.access import LOCAL_ACTOR

from helpers import TEX, Base, add_pin, edit_pin, needs_tex, ps, records, req, write_records

LOCATION_MODULES = (
    Path(locate.__file__),
    Path(pick_source.__file__),
    Path(pick_resolve.__file__),
    Path(source_range.__file__),
)
SERVER_GLOBALS = {
    "C",
    "cur_doc",
    "using_doc",
    "DOCS",
    "LEGACY_DOC",
    "BUILD_STATE",
    "BUILD_LOCK",
    "PIN_LOCK",
    "doc_by_key",
    "snapshot_pins",
}


class NoServerState(unittest.TestCase):
    """The location services must not reach the server's run arguments, document list or pins (coding rule R5)."""

    def test_reads_no_server_global(self):
        """No name the server keeps as hidden state appears in the module."""
        for path in LOCATION_MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            self.assertEqual(names & SERVER_GLOBALS, set(), path)
            self.assertNotIn("C.", path.read_text(encoding="utf-8"), path)

    def test_never_imports_the_server_or_the_http_layer(self):
        """The server is the composition root and the HTTP layer sits above the services: neither is imported."""
        for path in LOCATION_MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertFalse({m for m in modules if m in ("server", "limn.server") or m.startswith("limn.web")}, path)


class SynctexSampling(unittest.TestCase):
    """The subprocess-facing sampler delegates its observed file and line hits to the pure range choice."""

    def test_sampled_box_returns_the_majority_files_range(self):
        """The smallest grid samples four points and ignores one point mapped to another file."""
        pdf = Path("/ms/pages.pdf")
        with mock.patch.object(
            pick_source,
            "synctex_edit",
            side_effect=[("main.tex", 10), ("other.tex", 30), ("main.tex", 12), ("main.tex", 11)],
        ):
            self.assertEqual(pick_source.by_synctex(pdf, 2, 0, 0, 10, 10), ("main.tex", 10, 12))


class SyncAll(unittest.TestCase):
    """sync_all re-matches the open line pins against the files the given locator finds."""

    def setUp(self):
        """A manuscript file whose first line is later pushed down by an insertion."""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tex = self.root / "main.tex"
        self.lines = ["alpha one", "beta two", "gamma three"]
        self.tex.write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    def tearDown(self):
        """Removes the manuscript."""
        self.tmp.cleanup()

    def locator(self, r):
        """Places every line pin at main.tex under the root."""
        return locate.locate_file(str(self.tex), None, self.root, self.root / "state", None)

    def test_changed_pins_are_replaced_and_others_kept(self):
        """After an insertion, the open pin follows its anchor (a new pin in its place); done, view-only and
        unlocatable pins are the same objects as before; the result says something changed."""
        rec = {"id": 1, "file": str(self.tex), "lo": 2, "hi": 2, "anchor": anchor_of(self.lines, 2, 2), "synced_at": 0}
        pin = parse_pin(rec)
        done = parse_pin(dict(rec, id=2, done=True))
        region = parse_pin({"id": 3, "pdf": "/ms/figure.pdf", "page": 1, "frac": [0, 0, 0.5, 0.5]})
        pins = [pin, done, region]
        self.tex.write_text("inserted\n" + "\n".join(self.lines) + "\n", encoding="utf-8")
        self.assertTrue(locate.sync_all(pins, self.locator))
        moved = pins[0].record
        self.assertEqual((moved["lo"], moved["sync"], moved["rev"]), (3, "moved +1", 1))
        self.assertIs(pins[1], done)
        self.assertIs(pins[2], region)
        self.assertEqual(pin.record["lo"], 2)  # the old pin is not changed

    def test_nothing_changes_when_the_file_is_not_newer_or_not_found(self):
        """synced_at at the file's mtime: no change; a pin the locator cannot place: skipped."""
        mtime = os.stat(self.tex).st_mtime
        pin = {
            "id": 1,
            "file": str(self.tex),
            "lo": 2,
            "hi": 2,
            "anchor": anchor_of(self.lines, 2, 2),
            "synced_at": mtime,
        }
        pins = [parse_pin(pin)]
        kept = pins[0]
        self.assertFalse(locate.sync_all(pins, self.locator))
        self.assertFalse(locate.sync_all([parse_pin(dict(pin, synced_at=0))], lambda r: None))
        self.assertIs(pins[0], kept)


class TokenWeights(unittest.TestCase):
    """The token-weight cache weighs rare words and keeps one file's frequencies."""

    def test_rare_tokens_weigh_more_and_common_ones_drop(self):
        """A word on more than 5% of the lines is dropped; a rarer word weighs 1 / (1 + its line count)."""
        lines = ["common word here"] * 30 + ["rareword once"]
        got = dict(pick_source.TokenCache().weights("common rareword", lines, ("f", 1, 1)))
        self.assertEqual(got, {"rareword": 0.5})

    def test_cache_is_keyed_by_file_version(self):
        """The same key reuses the first lines' frequencies even when handed other lines; a new key recounts."""
        cache = pick_source.TokenCache()
        first, other = ["alpha beta"] + ["filler"] * 39, ["filler"] * 40
        self.assertEqual(dict(cache.weights("alpha", first, ("f", 1, 1))), {"alpha": 0.5})
        self.assertEqual(dict(cache.weights("alpha", other, ("f", 1, 1))), {"alpha": 0.5})
        self.assertEqual(dict(cache.weights("alpha", other, ("f", 2, 1))), {"alpha": 1.0})


class Overlaps(unittest.TestCase):
    """Overlaps count each open line pin in the file the locator finds for it now, else its stored file."""

    NEW = Path("/ms/new/main.tex")

    def locator(self, pin):
        """Places pins stored under /old/ at NEW (a moved checkout); every other file cannot be placed."""
        return (
            locate.locate_file(str(self.NEW), None, self.NEW.parent, self.NEW.parent / "state", None)
            if pin.core.place.file.startswith("/old/")
            else None
        )

    def setUp(self):
        """Pin 1 from before the move, pin 2 after it (same lines inside), a done pin and one in another file."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.NEW = Path(self.tmp.name) / "main.tex"
        self.NEW.write_text("text", encoding="utf-8")
        self.rows = [
            parse_pin(r)
            for r in (
                {"id": 1, "file": "/old/main.tex", "lo": 3, "hi": 9},
                {"id": 2, "file": str(self.NEW), "lo": 4, "hi": 5},
                {"id": 3, "file": str(self.NEW), "lo": 4, "hi": 5, "done": True},
                {"id": 4, "file": "/elsewhere.tex", "lo": 4, "hi": 5},
            )
        ]

    def test_pins_before_and_after_a_move_are_one_file(self):
        """The moved pin and the new one relate; the done pin has no entry; the other file relates to nothing."""
        self.assertEqual(
            locate.overlaps_by_id(self.rows, self.locator),
            {1: [{"id": 2, "rel": "contains"}], 2: [{"id": 1, "rel": "inside"}], 4: []},
        )

    def test_a_range_is_compared_in_the_located_file(self):
        """A new selection of NEW meets the moved pin and the new one, not the done pin."""
        self.assertEqual(
            locate.overlaps_for_range(str(self.NEW), 4, 5, self.rows, self.locator),
            [{"id": 1, "lo": 3, "hi": 9, "rel": "inside"}, {"id": 2, "lo": 4, "hi": 5, "rel": "equal"}],
        )

    def test_overlaps_api_asks_the_contexts_overlaps(self):
        """GET /api/overlaps' body is {"overlaps": ctx.overlaps(file, lo, hi)} for the parsed range."""
        asked = []

        def overlaps(file, lo, hi):
            """Records the question and answers one overlap."""
            asked.append((file, lo, hi))
            return [{"id": 7, "lo": lo, "hi": hi, "rel": "equal"}]

        rng = type("Range", (), {"file": self.NEW, "lines": ["a"] * 9, "lo": 2, "hi": 3})()
        self.assertEqual(
            source_range.overlaps_api(rng, overlaps), {"overlaps": [{"id": 7, "lo": 2, "hi": 3, "rel": "equal"}]}
        )
        self.assertEqual(asked, [(str(self.NEW), 2, 3)])


class DotPaths(unittest.TestCase):
    """locate_file keeps the tree rule of limn.platform.files.file_in_tree: a path under a dot-named part is not in the tree."""

    def test_a_recorded_path_under_a_dot_folder_is_not_located(self):
        """A stored pin or change path into .git - as recorded, through file_rel, or by the tail guess of a moved
        checkout - is not located, so its lines are never read into a re-sync or a comparison; main.tex still is."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("[remote]\n", encoding="utf-8")
            (root / "main.tex").write_text("x\n", encoding="utf-8")
            self.assertIsNone(
                locate.locate_file(str(root / ".git" / "config"), None, root, root.parent / "state", None)
            )
            self.assertIsNone(
                locate.locate_file("/old/place/.git/config", ".git/config", root, root.parent / "state", None)
            )
            self.assertIsNone(locate.locate_file("/old/place/.git/config", None, root, root.parent / "state", None))
            self.assertEqual(
                locate.locate_file("/old/place/main.tex", None, root, root.parent / "state", None).rel, "main.tex"
            )


class StateFolderPaths(unittest.TestCase):
    """locate_file keeps the state-folder part of the tree rule: with --state-dir inside the manuscript, a stored path
    into it is not in the tree."""

    def test_a_recorded_path_in_the_state_folder_is_not_located(self):
        """A pin recorded on audit.jsonl before the rule - as stored, through file_rel, by the tail guess of a moved
        checkout, or through a normal-looking link - is not located, so its lines never reach a re-sync, pins.md or
        a comparison; main.tex still is."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "limn-state"
            state.mkdir()
            (state / "audit.jsonl").write_text('{"action": "token_created"}\n', encoding="utf-8")
            (root / "main.tex").write_text("x\n", encoding="utf-8")
            (root / "notes.tex").symlink_to(state / "audit.jsonl")
            self.assertIsNone(locate.locate_file(str(state / "audit.jsonl"), None, root, state, None))
            self.assertIsNone(
                locate.locate_file("/old/place/limn-state/audit.jsonl", "limn-state/audit.jsonl", root, state, None)
            )
            self.assertIsNone(locate.locate_file("/old/place/limn-state/audit.jsonl", None, root, state, None))
            self.assertIsNone(locate.locate_file(str(root / "notes.tex"), None, root, state, None))
            self.assertEqual(locate.locate_file("/old/place/main.tex", None, root, state, None).rel, "main.tex")


# ---------------------------------------------------------------- through server.py's wiring
#
# Anchor re-sync on read and the est judgment of GET /api/pins. These classes load server.py (helpers.ps) and drive
# the module through its bindings; the tests above call the module on its own.


class Anchor(Base):
    """Stored anchors preserve adjacent comments and upgrade older offset-free records."""

    def _shift(self, n):
        lines = TEX.splitlines()
        lines[3:3] = ["inserted %d" % i for i in range(n)]  # n lines before L4
        time.sleep(0.01)
        self.main.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.utime(self.main, (time.time() + 5, time.time() + 5))

    def test_trailing_comment_kept(self):
        pid = self.add(8, 10)  # two body lines + a trailing comment
        self._shift(3)
        p = self.pin(pid)
        self.assertEqual((p["lo"], p["hi"], p["sync"]), (11, 13, "moved +3"))

    def test_leading_comment_kept(self):
        pid = self.add(7, 10)  # leading comment + body + trailing comment
        self._shift(3)
        p = self.pin(pid)
        self.assertEqual((p["lo"], p["hi"], p["sync"]), (10, 13, "moved +3"))

    def test_old_anchor_without_offsets(self):
        pid = self.add(8, 9)
        rows = records(ps.APP.snapshot_pins())
        for r in rows:
            r["anchor"].pop("head_off")
            r["anchor"].pop("tail_off")
        write_records(rows)
        self._shift(2)
        p = self.pin(pid)
        self.assertEqual((p["lo"], p["hi"]), (10, 11))


class PickOutcomes(Base):
    """pick_resolve.pick returns one value per outcome: a refusal type for each way a selection is not traced, else Picked.
    SyncTeX and pdftotext are stubbed at the module's two subprocess functions; the rest is the server's context."""

    def pick(self, synctex, text):
        """pick on the first document for a box on page 1, SyncTeX answering synctex and pdftotext printing text."""
        D = ps.APP.docs[0]
        request = location_input.PickRequest(D.dir / "pages", 1, (10.0, 20.0, 150.0, 60.0), (600.0, 800.0), None)
        with (
            mock.patch.object(pick_source, "by_synctex", return_value=synctex),
            mock.patch.object(pick_source, "region_text", return_value=text),
        ):
            return pick_resolve.pick(D, request, ps.APP.location_service.context())

    def test_each_refusal_is_its_own_type_with_its_detail(self):
        """A .bbl/.bib, a file outside the tree, an unreadable file and nothing traced are four refusal values."""
        D = ps.APP.docs[0]
        (self.src / "bin.tex").write_bytes(b"\xff\xfe")
        self.assertEqual(self.pick((str(D.build / "refs.bbl"), 1, 1), "x"), pick_resolve.GeneratedFile(".bbl"))
        self.assertEqual(
            self.pick(("/elsewhere/x.tex", 3, 3), "x"), pick_resolve.SynctexOutside(Path("/elsewhere/x.tex"))
        )
        self.assertEqual(
            self.pick((str(D.build / "bin.tex"), 1, 1), "x"), pick_resolve.SourceUnreadable(self.src / "bin.tex")
        )
        self.assertEqual(self.pick(None, ""), pick_resolve.NoSourceHere())

    def test_a_traced_selection_carries_its_range_and_build_facts(self):
        """SyncTeX's line in the build copy is traced back to the checkout; the facts the answer needs are values."""
        got = self.pick((str(ps.APP.docs[0].build / "main.tex"), 8, 8), "Body line seven betaunique.")
        self.assertIsInstance(got, pick_resolve.Picked)
        self.assertEqual(
            (got.file, got.page, got.traced.via, got.traced.lo, got.traced.hi), (self.main, 1, "synctex", 8, 9)
        )
        self.assertEqual(
            (got.n_lines, got.quote, got.pdf_build, got.building), (20, "Body line seven betaunique.", "pages", False)
        )


# ---------------------------------------------------------------- location estimation (.est) — server-side judgment


class Estimate(Base):
    """Design 1: est = (pin.pdf_build != current build) AND (the two builds' source fingerprints differ), or sync moved/lost.
    The judgment is made by the server and carried as est in GET /api/pins — it never uses the wall clock (browser timezone/edited_at)."""

    def _fake_build(self, name, src_hash, src_mtime=None):
        (ps.APP.C.state / name).mkdir(exist_ok=True)
        ps.APP.C.pages_ptr.write_text(name)
        build_run.finish_build(
            ps.APP.docs[0],
            BuildOk("", 0.1, None, None, src_hash, "-", name, 1),
            src_mtime if src_mtime is not None else time.time(),
            build_failure_log,
        )
        return name

    def est_of(self, pid):
        out = self.talk(req("GET", "/api/pins?all=1"))
        rows = json.loads(out.split(b"\r\n\r\n", 1)[1])
        return {r["id"]: r["est"] for r in rows}[pid]

    def test_same_build_is_not_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()
        self.assertIs(self.est_of(pid), False)

    def test_rebuild_with_same_source_is_not_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()
        self._fake_build("pages-20260101000100", "h1")
        self.assertIs(self.est_of(pid), False)

    def test_rebuild_with_changed_source_is_estimated_and_survives_note_edit(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()
        self._fake_build("pages-20260101000100", "h2")
        self.assertIs(self.est_of(pid), True)
        edit_pin(pid, {"note": "메모만", "base_rev": 0}, dict(LOCAL_ACTOR))  # must-2(a)
        self.assertIs(self.est_of(pid), True)
        edit_pin(pid, {"note_append": "덧붙임"}, dict(LOCAL_ACTOR))
        self.assertIs(self.est_of(pid), True)

    def test_relocating_on_current_build_clears_estimate(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()
        self._fake_build("pages-20260101000100", "h2")
        p = self.pin(pid)
        edit_pin(
            pid,
            {"loc": {"file": str(self.main), "lo": 4, "hi": 5, "frac": [0, 0, 0.5, 0.5]}, "base_rev": p["rev"]},
            dict(LOCAL_ACTOR),
        )
        self.assertIs(self.est_of(pid), False)

    def test_pin_on_stale_pdf_is_estimated_after_rebuild(self):
        # must-2(b): a pin placed on the old PDF after the manuscript was edited. Even if it was placed
        # later than the next build, it's caught by build identity.
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()  # the screen shows the h1 build (the manuscript has already changed)
        self._fake_build("pages-20260101000100", "h2")
        self.assertIs(self.est_of(pid), True)

    def test_unknown_pin_build_is_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "pdf_build": "pages"}, dict(LOCAL_ACTOR)
        ).record["id"]  # a build not in history — treat unknown as estimated (conservative)
        self.assertIs(self.est_of(pid), True)

    def test_sync_moved_or_lost_is_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add(8, 8)
        self.assertIs(self.est_of(pid), False)
        time.sleep(0.02)
        self.main.write_text("new first line\n" + TEX, encoding="utf-8")
        os.utime(self.main, (time.time() + 5, time.time() + 5))
        self.assertIs(self.est_of(pid), True)  # moved +1
        self.assertEqual(self.pin(pid)["sync"], "moved +1")

    def test_legacy_pin_uses_epoch_heuristic_on_server(self):
        # a legacy pin without pdf_build: the server resolves at (server local-time string) to epoch and compares against built_at / the build-start src_mtime.
        (ps.APP.C.state / "built_at.txt").write_text("2026-09-22T10:00:00+09:00")
        limn_build.write_built_src_mtime(ps.APP.docs[0], ps.APP.C.state, position.epoch("2026-09-22T09:30:00+09:00"))
        ctx = locate.est_context(ps.APP.docs[0])
        old = {"at": "2026-09-22T09:00:00+09:00", "sync": "ok"}
        self.assertTrue(position.pin_est(old, ctx))
        # editing just the note pushes edited_at past the build, but estimated stays true (must-2 a) — the only criterion is at
        self.assertTrue(position.pin_est(dict(old, edited_at="2026-09-22T11:00:00+09:00"), ctx))
        # the manuscript hasn't changed since
        self.assertFalse(position.pin_est({"at": "2026-09-22T09:45:00+09:00"}, ctx))
        self.assertFalse(position.pin_est({"at": "2026-09-22T10:30:00+09:00"}, ctx))  # placed after the build
        # the legacy field name also takes the identity path
        self.assertTrue(position.pin_est({"frac_build": "pages-x", "at": "2026-09-22T10:30:00+09:00"}, ctx))

    def test_legacy_epoch_ignores_process_timezone_for_offset_strings(self):
        with mock.patch.dict(os.environ, {"TZ": "America/New_York"}):
            time.tzset()
            try:
                ny = position.epoch("2026-09-22T09:00:00+09:00")
            finally:
                pass
        with mock.patch.dict(os.environ, {"TZ": "Asia/Seoul"}):
            time.tzset()
            seoul = position.epoch("2026-09-22T09:00:00+09:00")
        time.tzset()
        self.assertEqual(ny, seoul)

    def test_fingerprint_ignores_diff_dirs_and_tracks_content(self):
        h0 = limn_build.source_fingerprint(ps.APP.docs[0], self.src, ps.APP.C.state)
        for d in ("diff", "diff_temporary"):
            (self.src / d).mkdir()
            (self.src / d / "x.tex").write_text("latexdiff", encoding="utf-8")
            (self.src / d / "y.pdf").write_bytes(b"%PDF")
        self.assertEqual(limn_build.source_fingerprint(ps.APP.docs[0], self.src, ps.APP.C.state), h0)
        os.utime(self.main, (time.time() + 10, time.time() + 10))  # only the timestamp changed
        self.assertEqual(limn_build.source_fingerprint(ps.APP.docs[0], self.src, ps.APP.C.state), h0)
        self.main.write_text(TEX + "% x\n", encoding="utf-8")
        self.assertNotEqual(limn_build.source_fingerprint(ps.APP.docs[0], self.src, ps.APP.C.state), h0)

    def test_build_history_and_seq_in_meta(self):
        m0 = ps.APP.document_views.meta(ps.APP.docs[0], dict(LOCAL_ACTOR), light=True)
        self.assertEqual(m0["build_seq"], 0)
        self._fake_build("pages-20260101000000", "h1")
        build_run.finish_build(
            ps.APP.docs[0],
            BuildFailed("no_pdf", "", "boom", [{"line": 3, "msg": "x"}], 0.1, None, 1.0, None),
            None,
            build_failure_log,
        )
        m = ps.APP.document_views.meta(ps.APP.docs[0], dict(LOCAL_ACTOR), light=True)
        self.assertEqual(m["build_seq"], 2)
        self.assertEqual(m["last_build"]["state"], "fail")
        self.assertEqual(m["last_build"]["errors"], [{"line": 3, "msg": "x"}])
        self.assertTrue(m["last_build"]["finished_at"])
        h = limn_build.load_builds(ps.APP.docs[0])
        self.assertEqual(h["seq"], 2)
        # a failure doesn't leave a build in history
        self.assertEqual([b["build"] for b in h["builds"]], ["pages-20260101000000"])
        self.assertEqual(h["by"]["pages-20260101000000"]["src_hash"], "h1")

    def test_seed_builds_restores_last_state_and_seq_after_restart(self):
        self._fake_build("pages-20260101000000", "h1")
        build_run.finish_build(
            ps.APP.docs[0],
            BuildOkWithErrors([{"line": 1, "msg": "m"}], "L", 0.1, None, 1.0, None, "-", "", 1),
            None,
            build_failure_log,
        )
        ps.APP.docs[0].bstate.update(state="idle", seq=0, last=None, errors=[], log_tail="")  # simulate a restart
        limn_build.seed_builds(ps.APP.docs[0], ps.APP.C.state)
        st = limn_build.state_snapshot(ps.APP.docs[0])
        self.assertEqual((st["state"], st["seq"]), ("ok_errors", 2))
        self.assertEqual(st["errors"], [{"line": 1, "msg": "m"}])
        self.assertEqual(st["log_tail"], "L")

    def test_seed_builds_fingerprints_current_build_when_source_unchanged(self):
        d = ps.APP.C.state / "pages"
        d.mkdir()
        (d / "page-1.png").write_bytes(b"x")
        limn_build.write_built_src_mtime(
            ps.APP.docs[0], ps.APP.C.state, limn_build.src_mtime(ps.APP.docs[0], ps.APP.C.state, force=True) + 1
        )
        limn_build.seed_builds(ps.APP.docs[0], ps.APP.C.state)
        ent = limn_build.load_builds(ps.APP.docs[0])["by"]["pages"]
        self.assertEqual(ent["src_hash"], limn_build.source_fingerprint(ps.APP.docs[0], self.src, ps.APP.C.state))
        # first pin after startup -> no false positive from a rebuild that didn't change the manuscript
        pid = self.add()
        self._fake_build(
            "pages-20260101000100", limn_build.source_fingerprint(ps.APP.docs[0], self.src, ps.APP.C.state)
        )
        self.assertIs(self.est_of(pid), False)

    def test_seed_builds_leaves_hash_empty_when_source_is_newer(self):
        d = ps.APP.C.state / "pages"
        d.mkdir()
        (d / "page-1.png").write_bytes(b"x")
        limn_build.write_built_src_mtime(
            ps.APP.docs[0], ps.APP.C.state, limn_build.src_mtime(ps.APP.docs[0], ps.APP.C.state, force=True) - 100
        )
        limn_build.seed_builds(ps.APP.docs[0], ps.APP.C.state)
        self.assertIsNone(limn_build.load_builds(ps.APP.docs[0])["by"]["pages"]["src_hash"])

    def test_light_meta_does_not_write_builds_file(self):
        self._fake_build("pages-20260101000000", "h1")
        st = ps.APP.C.builds_file.stat()
        for _ in range(3):
            self.talk(req("GET", "/api/meta?light=1"))
        st2 = ps.APP.C.builds_file.stat()
        self.assertEqual((st.st_mtime_ns, st.st_size), (st2.st_mtime_ns, st2.st_size))

    @needs_tex("latexmk", "pdftoppm")
    def test_real_build_est_end_to_end(self):
        """With the real latexmk: an unchanged rebuild -> no est, a rebuild after editing the manuscript -> est, and it stays after editing the note."""
        self.assertEqual(type(ps.APP.build_requests.build_all(ps.APP.docs[0])), BuildOk)
        b1 = limn_build.cur_pages(ps.APP.docs[0]).name
        pid = self.add()
        self.assertEqual(self.pin(pid)["pdf_build"], b1)
        # a rebuild within the same second still gets a page directory of its own (test_build.Outcomes)
        self.assertEqual(type(ps.APP.build_requests.build_all(ps.APP.docs[0])), BuildOk)
        self.assertNotEqual(limn_build.cur_pages(ps.APP.docs[0]).name, b1)
        self.assertIs(self.est_of(pid), False)
        self.main.write_text(
            TEX.replace("After table epsilonunique.", "After table epsilonunique longer."), encoding="utf-8"
        )
        self.assertEqual(type(ps.APP.build_requests.build_all(ps.APP.docs[0])), BuildOk)
        self.assertIs(self.est_of(pid), True)
        edit_pin(pid, {"note": "메모만", "base_rev": self.pin(pid)["rev"]}, dict(LOCAL_ACTOR))
        self.assertIs(self.est_of(pid), True)


class ServerOverlaps(Base):
    """Overlaps as server.py wires them on the fixture manuscript: overlaps_by_id over the pins, overlaps_for_range for a
    range that is not a pin yet (the pick's banner)."""

    def test_inside_and_contains_pair(self):
        # the first two paragraphs (not blank-line-free — lo/hi adjusted to overlap generously)
        p1 = self.add(4, 9, note="outer")
        p2 = self.add(4, 5, note="inner")
        rel = ps.APP.overlaps_by_id(ps.APP.snapshot_pins())
        self.assertEqual(rel[p2], [{"id": p1, "rel": "inside"}])
        self.assertEqual(rel[p1], [{"id": p2, "rel": "contains"}])

    def test_partial_overlap(self):
        p1 = self.add(4, 5)
        p2 = self.add(5, 6)
        rel = ps.APP.overlaps_by_id(ps.APP.snapshot_pins())
        self.assertEqual(rel[p1], [{"id": p2, "rel": "partial"}])
        self.assertEqual(rel[p2], [{"id": p1, "rel": "partial"}])

    def test_no_overlap_is_empty(self):
        p1 = self.add(4, 5)
        p2 = self.add(8, 9)
        rel = ps.APP.overlaps_by_id(ps.APP.snapshot_pins())
        self.assertEqual(rel[p1], [])
        self.assertEqual(rel[p2], [])

    def test_overlaps_for_range_matches_pick_semantics(self):
        self.add(4, 9, note="outer")
        ov = ps.APP.overlaps_for_range(str(self.main), 4, 5)
        self.assertEqual(len(ov), 1)
        self.assertEqual(ov[0]["rel"], "inside")

    def test_overlaps_for_range_same_range_is_equal(self):
        # design 2: an identical range is reported separately as 'equal' — the viewer states "same range" and shows a banner.
        pid = self.add(4, 9, note="first")
        ov = ps.APP.overlaps_for_range(str(self.main), 4, 9)
        self.assertEqual(ov, [{"id": pid, "lo": 4, "hi": 9, "rel": "equal"}])


if __name__ == "__main__":
    unittest.main()
