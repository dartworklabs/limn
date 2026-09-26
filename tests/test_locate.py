"""limn.locate - the effectful half of the position rules, driven by the arguments it is given (coding rule R5).

Picking, estimation, overlaps and re-sync are pinned through the server in test_server.py, test_v032.py and
test_moved_paths.py. Here the module is called directly, with no server and no run arguments: it must not read them,
and its re-sync and token weights work on the files and cache they are handed.

Run: uv run pytest -q tests/test_locate.py
"""
import ast
import os
import tempfile
import unittest
from pathlib import Path

from limn import locate
from limn.mapping import anchor_of

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


if __name__ == "__main__":
    unittest.main()
