"""limn.locate - the effectful half of the position rules, driven by the arguments it is given (coding rule R5).

Re-sync and estimation are pinned through server.py at the end of this file (Anchor, Estimate); picking and overlaps
through the server in test_server.py (Overlaps), test_v032.py and test_moved_paths.py. The classes above call the
module directly, with no server and no run arguments: it must not read them, and its re-sync and token weights work
on the files and cache they are handed.

Run: uv run pytest -q tests/test_locate.py
"""
import ast
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from limn import build as limn_build, locate
from limn.access import LOCAL_ACTOR
from limn.mapping import anchor_of
from limn.pins import position

from helpers import TEX, Base, add_pin, edit_pin, ps, req

LOCATE_PY = Path(locate.__file__)
SERVER_GLOBALS = {"C", "cur_doc", "using_doc", "DOCS", "LEGACY_DOC", "BUILD_STATE", "BUILD_LOCK", "PIN_LOCK",
                  "doc_by_key", "snapshot_pins"}


class NoServerState(unittest.TestCase):
    """The moved services must not reach the server's run arguments, document list or pins (roadmap stage 6)."""

    def test_reads_no_server_global(self):
        """No name the server keeps as hidden state appears in the module."""
        tree = ast.parse(LOCATE_PY.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertEqual(names & SERVER_GLOBALS, set())
        self.assertNotIn("C.", LOCATE_PY.read_text(encoding="utf-8"))

    def test_never_imports_the_server_or_the_http_layer(self):
        """The server is the composition root and the HTTP layer sits above the services: neither is imported."""
        tree = ast.parse(LOCATE_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse({m for m in modules if m in ("server", "limn.server") or m.startswith("limn.web")})


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
        return locate.PinLocation("main.tex", self.tex)

    def test_changed_rows_are_replaced_and_others_kept(self):
        """After an insertion, the open pin follows its anchor (a new row object); done, view-only and unlocatable pins
        are the same objects as before; the result says something changed."""
        pin = {"id": 1, "file": str(self.tex), "lo": 2, "hi": 2, "anchor": anchor_of(self.lines, 2, 2), "synced_at": 0}
        done = dict(pin, id=2, done=True)
        region = {"id": 3, "page": 1}
        rows = [pin, done, region]
        self.tex.write_text("inserted\n" + "\n".join(self.lines) + "\n", encoding="utf-8")
        self.assertTrue(locate.sync_all(rows, self.locator))
        self.assertEqual((rows[0]["lo"], rows[0]["sync"], rows[0]["rev"]), (3, "moved +1", 1))
        self.assertIs(rows[1], done)
        self.assertIs(rows[2], region)
        self.assertEqual(pin["lo"], 2)                                  # the old record is not mutated

    def test_nothing_changes_when_the_file_is_not_newer_or_not_found(self):
        """synced_at at the file's mtime: no change; a pin the locator cannot place: skipped."""
        mtime = os.stat(self.tex).st_mtime
        pin = {"id": 1, "file": str(self.tex), "lo": 2, "hi": 2, "anchor": anchor_of(self.lines, 2, 2),
               "synced_at": mtime}
        rows = [pin]
        self.assertFalse(locate.sync_all(rows, self.locator))
        self.assertFalse(locate.sync_all([dict(pin, synced_at=0)], lambda r: None))
        self.assertIs(rows[0], pin)


class TokenWeights(unittest.TestCase):
    """The token-weight cache weighs rare words and keeps one file's frequencies."""

    def test_rare_tokens_weigh_more_and_common_ones_drop(self):
        """A word on more than 5% of the lines is dropped; a rarer word weighs 1 / (1 + its line count)."""
        lines = ["common word here"] * 30 + ["rareword once"]
        got = dict(locate.TokenCache().weights("common rareword", lines, ("f", 1, 1)))
        self.assertEqual(got, {"rareword": 0.5})

    def test_cache_is_keyed_by_file_version(self):
        """The same key reuses the first lines' frequencies even when handed other lines; a new key recounts."""
        cache = locate.TokenCache()
        first, other = ["alpha beta"] + ["filler"] * 39, ["filler"] * 40
        self.assertEqual(dict(cache.weights("alpha", first, ("f", 1, 1))), {"alpha": 0.5})
        self.assertEqual(dict(cache.weights("alpha", other, ("f", 1, 1))), {"alpha": 0.5})
        self.assertEqual(dict(cache.weights("alpha", other, ("f", 2, 1))), {"alpha": 1.0})


class Overlaps(unittest.TestCase):
    """Overlaps count each open line pin in the file the locator finds for it now, else its stored file."""

    NEW = Path("/ms/new/main.tex")

    def locator(self, r):
        """Places pins stored under /old/ at NEW (a moved checkout); every other file cannot be placed."""
        return locate.PinLocation("main.tex", self.NEW) if str(r.get("file", "")).startswith("/old/") else None

    def setUp(self):
        """Pin 1 from before the move, pin 2 after it (same lines inside), a done pin and one in another file."""
        self.rows = [{"id": 1, "file": "/old/main.tex", "lo": 3, "hi": 9},
                     {"id": 2, "file": str(self.NEW), "lo": 4, "hi": 5},
                     {"id": 3, "file": str(self.NEW), "lo": 4, "hi": 5, "done": True},
                     {"id": 4, "file": "/elsewhere.tex", "lo": 4, "hi": 5}]

    def test_pins_before_and_after_a_move_are_one_file(self):
        """The moved pin and the new one relate; the done pin has no entry; the other file relates to nothing."""
        self.assertEqual(locate.overlaps_by_id(self.rows, self.locator),
                         {1: [{"id": 2, "rel": "contains"}], 2: [{"id": 1, "rel": "inside"}], 4: []})

    def test_a_range_is_compared_in_the_located_file(self):
        """A new selection of NEW meets the moved pin and the new one, not the done pin."""
        self.assertEqual(locate.overlaps_for_range(str(self.NEW), 4, 5, self.rows, self.locator),
                         [{"id": 1, "lo": 3, "hi": 9, "rel": "inside"}, {"id": 2, "lo": 4, "hi": 5, "rel": "equal"}])

    def test_overlaps_api_asks_the_contexts_overlaps(self):
        """GET /api/overlaps' body is {"overlaps": ctx.overlaps(file, lo, hi)} for the parsed range."""
        asked = []

        def overlaps(file, lo, hi):
            """Records the question and answers one overlap."""
            asked.append((file, lo, hi))
            return [{"id": 7, "lo": lo, "hi": hi, "rel": "equal"}]
        ctx = locate.PickContext(Path("/ms"), (), Path("/state"), locate.TokenCache(), overlaps)
        rng = type("Range", (), {"file": self.NEW, "lines": ["a"] * 9, "lo": 2, "hi": 3})()
        self.assertEqual(locate.overlaps_api(rng, ctx), {"overlaps": [{"id": 7, "lo": 2, "hi": 3, "rel": "equal"}]})
        self.assertEqual(asked, [(str(self.NEW), 2, 3)])


# ---------------------------------------------------------------- through server.py's wiring
#
# Anchor re-sync on read and the est judgment of GET /api/pins. These classes load server.py (helpers.ps) and drive
# the module through its bindings; the tests above call the module on its own.

class Anchor(Base):
    def _shift(self, n):
        lines = TEX.splitlines()
        lines[3:3] = ["inserted %d" % i for i in range(n)]      # n lines before L4
        time.sleep(0.01)
        self.main.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.utime(self.main, (time.time() + 5, time.time() + 5))

    def test_trailing_comment_kept(self):
        pid = self.add(8, 10)                     # two body lines + a trailing comment
        self._shift(3)
        p = self.pin(pid)
        self.assertEqual((p["lo"], p["hi"], p["sync"]), (11, 13, "moved +3"))

    def test_leading_comment_kept(self):
        pid = self.add(7, 10)                     # leading comment + body + trailing comment
        self._shift(3)
        p = self.pin(pid)
        self.assertEqual((p["lo"], p["hi"], p["sync"]), (10, 13, "moved +3"))

    def test_old_anchor_without_offsets(self):
        pid = self.add(8, 9)
        rows = ps.snapshot_pins()
        for r in rows:
            r["anchor"].pop("head_off")
            r["anchor"].pop("tail_off")
        ps.write_pins(rows)
        self._shift(2)
        p = self.pin(pid)
        self.assertEqual((p["lo"], p["hi"]), (10, 11))


# ---------------------------------------------------------------- location estimation (.est) — server-side judgment

class Estimate(Base):
    """Design 1: est = (pin.pdf_build != current build) AND (the two builds' source fingerprints differ), or sync moved/lost.
    The judgment is made by the server and carried as est in GET /api/pins — it never uses the wall clock (browser timezone/edited_at)."""

    def _fake_build(self, name, src_hash, src_mtime=None):
        (ps.C.state / name).mkdir(exist_ok=True)
        ps.C.pages_ptr.write_text(name)
        limn_build.finish_build(ps.DOCS[0], {"ok": True, "state": "ok", "errors": [], "log": "", "elapsed_s": 0.1, "pages": 1,
                         "build": name, "src_hash": src_hash}, src_mtime if src_mtime is not None else time.time())
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
        edit_pin(pid, {"note": "메모만", "base_rev": 0}, dict(LOCAL_ACTOR))        # must-2(a)
        self.assertIs(self.est_of(pid), True)
        edit_pin(pid, {"note_append": "덧붙임"}, dict(LOCAL_ACTOR))
        self.assertIs(self.est_of(pid), True)

    def test_relocating_on_current_build_clears_estimate(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()
        self._fake_build("pages-20260101000100", "h2")
        p = self.pin(pid)
        edit_pin(pid, {"loc": {"file": str(self.main), "lo": 4, "hi": 5, "frac": [0, 0, 0.5, 0.5]},
                          "base_rev": p["rev"]}, dict(LOCAL_ACTOR))
        self.assertIs(self.est_of(pid), False)

    def test_pin_on_stale_pdf_is_estimated_after_rebuild(self):
        # must-2(b): a pin placed on the old PDF after the manuscript was edited. Even if it was placed
        # later than the next build, it's caught by build identity.
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()                                  # the screen shows the h1 build (the manuscript has already changed)
        self._fake_build("pages-20260101000100", "h2")
        self.assertIs(self.est_of(pid), True)

    def test_unknown_pin_build_is_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "pdf_build": "pages"},
                         dict(LOCAL_ACTOR)).record["id"]            # a build not in history — treat unknown as estimated (conservative)
        self.assertIs(self.est_of(pid), True)

    def test_sync_moved_or_lost_is_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add(8, 8)
        self.assertIs(self.est_of(pid), False)
        time.sleep(0.02)
        self.main.write_text("new first line\n" + TEX, encoding="utf-8")
        os.utime(self.main, (time.time() + 5, time.time() + 5))
        self.assertIs(self.est_of(pid), True)             # moved +1
        self.assertEqual(self.pin(pid)["sync"], "moved +1")

    def test_same_source_falls_back_to_src_mtime_without_hash(self):
        a = {"src_hash": None, "src_mtime": 100.0}
        self.assertTrue(position.same_source(a, {"src_hash": None, "src_mtime": 100.0}))
        self.assertFalse(position.same_source(a, {"src_hash": None, "src_mtime": 101.0}))
        self.assertFalse(position.same_source(a, None))
        self.assertFalse(position.same_source({"src_hash": "x"}, {"src_hash": "y", "src_mtime": 1}))

    def test_legacy_pin_uses_epoch_heuristic_on_server(self):
        # a legacy pin without pdf_build: the server resolves at (server local-time string) to epoch and compares against built_at / the build-start src_mtime.
        (ps.C.state / "built_at.txt").write_text("2026-09-22T10:00:00+09:00")
        limn_build.write_built_src_mtime(ps.DOCS[0], ps.C.state, position.epoch("2026-09-22T09:30:00+09:00"))
        ctx = locate.est_context(ps.DOCS[0])
        old = {"at": "2026-09-22T09:00:00+09:00", "sync": "ok"}
        self.assertTrue(position.pin_est(old, ctx))
        # editing just the note pushes edited_at past the build, but estimated stays true (must-2 a) — the only criterion is at
        self.assertTrue(position.pin_est(dict(old, edited_at="2026-09-22T11:00:00+09:00"), ctx))
        # the manuscript hasn't changed since
        self.assertFalse(position.pin_est({"at": "2026-09-22T09:45:00+09:00"}, ctx))
        self.assertFalse(position.pin_est({"at": "2026-09-22T10:30:00+09:00"}, ctx))   # placed after the build
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
        h0 = limn_build.source_fingerprint(ps.DOCS[0], self.src, ps.C.state)
        for d in ("diff", "diff_temporary"):
            (self.src / d).mkdir()
            (self.src / d / "x.tex").write_text("latexdiff", encoding="utf-8")
            (self.src / d / "y.pdf").write_bytes(b"%PDF")
        self.assertEqual(limn_build.source_fingerprint(ps.DOCS[0], self.src, ps.C.state), h0)
        os.utime(self.main, (time.time() + 10, time.time() + 10))                 # only the timestamp changed
        self.assertEqual(limn_build.source_fingerprint(ps.DOCS[0], self.src, ps.C.state), h0)
        self.main.write_text(TEX + "% x\n", encoding="utf-8")
        self.assertNotEqual(limn_build.source_fingerprint(ps.DOCS[0], self.src, ps.C.state), h0)

    def test_build_history_and_seq_in_meta(self):
        m0 = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR), light=True)
        self.assertEqual(m0["build_seq"], 0)
        self._fake_build("pages-20260101000000", "h1")
        limn_build.finish_build(ps.DOCS[0], {"ok": False, "state": "fail", "errors": [{"line": 3, "msg": "x"}], "log": "boom",
                         "elapsed_s": 0.1}, None)
        m = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR), light=True)
        self.assertEqual(m["build_seq"], 2)
        self.assertEqual(m["last_build"]["state"], "fail")
        self.assertEqual(m["last_build"]["errors"], [{"line": 3, "msg": "x"}])
        self.assertTrue(m["last_build"]["finished_at"])
        h = limn_build.load_builds(ps.DOCS[0])
        self.assertEqual(h["seq"], 2)
        # a failure doesn't leave a build in history
        self.assertEqual([b["build"] for b in h["builds"]], ["pages-20260101000000"])
        self.assertEqual(h["by"]["pages-20260101000000"]["src_hash"], "h1")

    def test_seed_builds_restores_last_state_and_seq_after_restart(self):
        self._fake_build("pages-20260101000000", "h1")
        limn_build.finish_build(ps.DOCS[0], {"ok": False, "state": "ok_errors", "errors": [{"line": 1, "msg": "m"}], "log": "L",
                         "elapsed_s": 0.1}, None)
        ps.BUILD_STATE.update(state="idle", seq=0, last=None, errors=[], log_tail="")   # simulate a restart
        limn_build.seed_builds(ps.DOCS[0], ps.C.state)
        st = limn_build.state_snapshot(ps.DOCS[0])
        self.assertEqual((st["state"], st["seq"]), ("ok_errors", 2))
        self.assertEqual(st["errors"], [{"line": 1, "msg": "m"}])
        self.assertEqual(st["log_tail"], "L")

    def test_seed_builds_fingerprints_current_build_when_source_unchanged(self):
        d = ps.C.state / "pages"
        d.mkdir()
        (d / "page-1.png").write_bytes(b"x")
        limn_build.write_built_src_mtime(ps.DOCS[0], ps.C.state, limn_build.src_mtime(ps.DOCS[0], ps.C.state, force=True) + 1)
        limn_build.seed_builds(ps.DOCS[0], ps.C.state)
        ent = limn_build.load_builds(ps.DOCS[0])["by"]["pages"]
        self.assertEqual(ent["src_hash"], limn_build.source_fingerprint(ps.DOCS[0], self.src, ps.C.state))
        # first pin after startup -> no false positive from a rebuild that didn't change the manuscript
        pid = self.add()
        self._fake_build("pages-20260101000100", limn_build.source_fingerprint(ps.DOCS[0], self.src, ps.C.state))
        self.assertIs(self.est_of(pid), False)

    def test_seed_builds_leaves_hash_empty_when_source_is_newer(self):
        d = ps.C.state / "pages"
        d.mkdir()
        (d / "page-1.png").write_bytes(b"x")
        limn_build.write_built_src_mtime(ps.DOCS[0], ps.C.state, limn_build.src_mtime(ps.DOCS[0], ps.C.state, force=True) - 100)
        limn_build.seed_builds(ps.DOCS[0], ps.C.state)
        self.assertIsNone(limn_build.load_builds(ps.DOCS[0])["by"]["pages"]["src_hash"])

    def test_light_meta_does_not_write_builds_file(self):
        self._fake_build("pages-20260101000000", "h1")
        st = ps.C.builds_file.stat()
        for _ in range(3):
            self.talk(req("GET", "/api/meta?light=1"))
        st2 = ps.C.builds_file.stat()
        self.assertEqual((st.st_mtime_ns, st.st_size), (st2.st_mtime_ns, st2.st_size))

    def test_real_build_est_end_to_end(self):
        """With the real latexmk: an unchanged rebuild -> no est, a rebuild after editing the manuscript -> est, and it stays after editing the note."""
        import shutil as _sh
        if not (_sh.which("latexmk") and _sh.which("pdftoppm")):
            self.skipTest("latexmk/pdftoppm not available")
        self.assertEqual(ps.build_all(ps.DOCS[0])["state"], "ok")
        b1 = limn_build.cur_pages(ps.DOCS[0]).name
        pid = self.add()
        self.assertEqual(self.pin(pid)["pdf_build"], b1)
        time.sleep(1.1)                                      # build directory names are second-granularity
        self.assertEqual(ps.build_all(ps.DOCS[0])["state"], "ok")
        self.assertNotEqual(limn_build.cur_pages(ps.DOCS[0]).name, b1)
        self.assertIs(self.est_of(pid), False)
        self.main.write_text(TEX.replace("After table epsilonunique.", "After table epsilonunique longer."),
                             encoding="utf-8")
        time.sleep(1.1)
        self.assertEqual(ps.build_all(ps.DOCS[0])["state"], "ok")
        self.assertIs(self.est_of(pid), True)
        edit_pin(pid, {"note": "메모만", "base_rev": self.pin(pid)["rev"]}, dict(LOCAL_ACTOR))
        self.assertIs(self.est_of(pid), True)



if __name__ == "__main__":
    unittest.main()
