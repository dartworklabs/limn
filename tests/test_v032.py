"""v0.3.2 (issue #7, docs/adr/0006-relative-pin-paths.md): pins follow a moved manuscript.

Pins stored the manuscript file only as an absolute path, so moving the checkout left every pin outside the tree: no
line re-sync, no range edit, no «…» quote, and a bare file name in pins.md. Records now also store `file_rel` (relative
to --manuscript) when the server writes that pin, and every record - old ones included - is located on read by one rule
(pin_rel_path): the stored file if it lies under the current root, else a file_rel that matches the file's tail, else
the longest tail of the file that exists under the root. The API returns the located `file` and a computed `rel_path`.
Old records are never rewritten just to add file_rel, and nothing outside the tree is ever read.

Run: uv run pytest -q tests/test_v032.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from limn import mapping
from limn.store import dump_jsonl
from test_access import AccessBase, configure, mask
from test_server import add_pin, ps
from test_v03 import ScopedRepo

ROOT = Path(__file__).resolve().parent.parent

MAIN = "\\documentclass{article}\n\\begin{document}\n\\input{sections/x}\n\\input{sections/long}\n\\end{document}\n"
X_LINES = ["%% line %d" % i if i in (1, 2) else "Sentence number %d about topic%d." % (i, i) for i in range(1, 21)]
X = "\n".join(X_LINES) + "\n"
LONG = "Long line " + "word " * 150 + "\n"                  # one line over 600 characters (the «…» quote rule)
SECRET = "TOPSECRET outside-the-tree line " + "x" * 700 + "\n"


# ---------------------------------------------------------------- the decision (pure)

class PinRelPathRule(unittest.TestCase):
    """mapping.pin_rel_path() picks where a stored line pin's file lives relative to the current root, from facts passed in."""

    def pick(self, file, file_rel=None, under=None, existing=()):
        return mapping.pin_rel_path(file, file_rel, under, set(existing).__contains__)

    def test_file_under_the_current_root_wins_even_if_missing(self):
        """The stored absolute path is the surest fact on this machine; a deleted file is not re-guessed elsewhere."""
        self.assertEqual(self.pick("/r/sections/x.tex", "sections/y.tex", under="sections/x.tex", existing={"x.tex"}),
                         "sections/x.tex")

    def test_a_file_rel_matching_the_file_tail_locates_a_moved_record(self):
        """file_rel is trusted without an existence check when the stored file ends with it (the server writes both)."""
        self.assertEqual(self.pick("/old/paper/sections/x.tex", "sections/x.tex"), "sections/x.tex")
        self.assertEqual(self.pick("/old/paper/x.tex", "x.tex"), "x.tex")

    def test_a_longer_existing_tail_beats_file_rel_when_the_root_was_widened(self):
        """Moved and widened (paper/ -> the repository): 'paper/x.tex' exists, so it wins over file_rel 'x.tex' - even when
        the root also has an unrelated x.tex; a shorter tail never does."""
        self.assertEqual(self.pick("/old/repo/paper/x.tex", "x.tex", existing={"paper/x.tex", "x.tex"}), "paper/x.tex")
        self.assertEqual(self.pick("/old/paper/sections/x.tex", "sections/x.tex", existing={"x.tex"}), "sections/x.tex")

    def test_a_file_rel_that_no_longer_matches_the_file_is_ignored(self):
        """A 0.3.0 relocation changes file but leaves file_rel: the stale file_rel must not win (ADR-0006 §2.2)."""
        self.assertEqual(self.pick("/old/paper/sections/y.tex", "sections/x.tex", existing={"sections/x.tex", "sections/y.tex"}),
                         "sections/y.tex")
        self.assertIsNone(self.pick("/old/paper/sections/y.tex", "sections/x.tex"))

    def test_unsafe_or_malformed_file_rels_are_ignored(self):
        """Absolute, parent-escaping, empty or non-string file_rel values are never used."""
        for bad in ("/etc/x.tex", "../outside/x.tex", "a/../../x.tex", "", ".", 5, None, ["x.tex"]):
            self.assertIsNone(self.pick("/old/paper/%s" % (bad if isinstance(bad, str) else "q"), bad), repr(bad))

    def test_legacy_records_take_the_longest_existing_tail(self):
        """Without file_rel, the longest tail of the stored path that exists under the root wins (to_source()'s rule)."""
        existing = {"sections/x.tex", "x.tex"}
        self.assertEqual(self.pick("/home/u/paper-a/sections/x.tex", existing=existing), "sections/x.tex")
        self.assertEqual(self.pick("/home/u/paper-a/x.tex", existing=existing), "x.tex")
        self.assertIsNone(self.pick("/home/u/paper-a/sections/z.tex", existing=existing))

    def test_tails_never_contain_parent_parts(self):
        """A stored path with '..' parts cannot produce a candidate that climbs out of the root."""
        self.assertEqual(mapping.file_tails("/a/../../etc/x.tex"), ["etc/x.tex", "x.tex"])
        self.assertEqual(mapping.file_tails("/p/s/x.tex"), ["p/s/x.tex", "s/x.tex", "x.tex"])
        self.assertEqual(self.pick("/a/../../etc/x.tex", existing={"a/../../etc/x.tex", "../../etc/x.tex"}), None)

    def test_redundant_separators_and_dot_parts_are_normalised(self):
        """'//' and '.' parts do not change the answer: a file_rel written as './sections//x.tex' is 'sections/x.tex'."""
        self.assertEqual(self.pick("/old/paper/sections/x.tex", "./sections//x.tex"), "sections/x.tex")
        self.assertEqual(mapping.file_tails("//p/./s//x.tex"), ["p/s/x.tex", "s/x.tex", "x.tex"])

    def test_anchor_holds_only_where_the_head_line_is(self):
        """anchor_holds() checks the head at lo + head_off with find_line()'s matching; a bad offset counts as 0."""
        nlines = ["a", "Sentence number 5 about topic5.", "c"]
        anchor = {"head": "Sentence number 5 about topic5.", "head_off": 1}
        self.assertTrue(mapping.anchor_holds(anchor, 1, nlines))
        self.assertFalse(mapping.anchor_holds(anchor, 2, nlines))
        self.assertTrue(mapping.anchor_holds(dict(anchor, head_off=True), 2, nlines))      # not an int: 0
        self.assertTrue(mapping.anchor_holds({"head": "Sentence number 5 about topic5. (longer)"}, 2,
                                             ["x", "Sentence number 5 about topic5. (longer) and more"]))
        self.assertFalse(mapping.anchor_holds({"head": ""}, 1, nlines))
        self.assertFalse(mapping.anchor_holds(anchor, 5, nlines))


# ---------------------------------------------------------------- moving the manuscript between two server runs

class MovedManuscriptBase(AccessBase):
    """A manuscript with \\input'ed sections at <tmp>/paper-a, pins placed there, then the folder renamed to paper-b."""

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.a, self.b = root / "paper-a", root / "paper-b"
        (self.a / "sections").mkdir(parents=True)
        (self.a / "main.tex").write_text(MAIN, encoding="utf-8")
        (self.a / "sections" / "x.tex").write_text(X, encoding="utf-8")
        (self.a / "sections" / "long.tex").write_text(LONG, encoding="utf-8")
        self.use_root(self.a)
        self.p_new = self.pin_at("sections/x.tex", 5, 6)
        self.p_old = self.pin_at("sections/x.tex", 10, 11)
        self.p_quote = add_pin({"file": str(self.a / "sections" / "long.tex"), "lo": 1, "hi": 1, "scope": "raw",
                                   "quote": "Long line word word", "note": "q"}, dict(ps.LOCAL_ACTOR)).record["id"]
        self.make_legacy(self.p_old, self.p_quote)            # as 0.3.0 wrote them: no file_rel

    def use_root(self, root: Path):
        """Point the server at a manuscript root, as `limn serve --manuscript <root>` would."""
        ps.C.src, ps.C.main = root, root / "main.tex"

    def pin_at(self, rel, lo, hi, note="n"):
        return add_pin({"file": str(ps.C.src / rel), "lo": lo, "hi": hi, "note": note}, dict(ps.LOCAL_ACTOR)).record["id"]

    def stored(self):
        return {r["id"]: r for r in ps.read_pins()[0]}

    def rewrite(self, fn):
        """Edit pins.jsonl directly (a state written by another version, or by hand)."""
        rows = ps.read_pins()[0]
        fn(rows)
        ps.C.pins_jsonl.write_text(dump_jsonl(rows), encoding="utf-8")

    def make_legacy(self, *ids):
        self.rewrite(lambda rows: [r.pop("file_rel", None) for r in rows if r["id"] in ids])

    def move(self):
        """Stop, rename the checkout, start again on the new path (the handler has no state beyond C and the files)."""
        os.rename(self.a, self.b)
        self.use_root(self.b)

    def api_pins(self):
        code, rows = self.call("GET", "/api/pins")
        self.assertEqual(code, 200, rows)
        return {r["id"]: r for r in rows}

    def pins_md(self):
        code, md = self.call("GET", "/pins.md")
        self.assertEqual(code, 200)
        return md


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
        self.assertEqual((d["pin"]["lo"], d["pin"]["hi"], d["pin"]["file"]), (14, 15, str(self.b / "sections" / "x.tex")))
        r = self.stored()[self.p_old]
        self.assertEqual((r["file"], r["file_rel"]), (str(self.b / "sections" / "x.tex"), "sections/x.tex"))
        self.assertEqual(r["anchor"]["head"], "Sentence number 14 about topic14.")

    def test_reading_never_rewrites_a_legacy_record(self):
        """No write migration: reads after a plain move (same files) leave pins.jsonl byte for byte as it was."""
        self.move()
        before = ps.C.pins_jsonl.read_bytes()
        self.api_pins()
        self.pins_md()
        self.call("GET", "/api/pins?all=1")
        self.assertEqual(ps.C.pins_jsonl.read_bytes(), before)
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
        self.rewrite(lambda rows: [r.update(file="/nowhere/paper/old-dir/main.tex") for r in rows if r["id"] == self.p_old])
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
        self.assertEqual(stored[self.p_old]["file"], str(self.b / "sections" / "x.tex"))   # lines and file describe B
        self.assertNotIn("file_rel", stored[self.p_old])                                  # still no backfill

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
        self.assertEqual(self.call("POST", "/api/pins/%d/edit" % self.p_old, {"note": "n" * 3000, "base_rev": rev})[0], 200)
        f = self.a / "sections" / "x.tex"
        os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))                          # the next transact re-syncs
        before = self.stored()[self.p_old]
        code, d = self.call("POST", "/api/pins/%d/edit" % self.p_old,
                            {"lo": 14, "hi": 15, "note_append": "x" * 1500, "base_rev": rev + 1})
        self.assertEqual(code, 400, d)
        after = self.stored()[self.p_old]
        self.assertEqual((after["lo"], after["hi"], after["note"], after.get("file_rel")),
                         (before["lo"], before["hi"], before["note"], before.get("file_rel")))


# ---------------------------------------------------------------- what must stay outside (R10)

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
        self.assertEqual((code, d["error"]), (400, "원고 디렉토리 밖을 가리키는 핀입니다 — 위치 다시 잡기(loc)로 고치세요."))

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
        self.put(file=f)                                            # legacy: the tail linked/secret.tex exists via the link
        self.assert_out_of_tree(f)

    def test_a_file_rel_of_the_wrong_type_is_a_broken_line(self):
        """file_rel, when present, must be a string - like every field the store reads."""
        self.rewrite(lambda rows: [r.update(file_rel=5) for r in rows if r["id"] == self.p_old])
        rows, bad = ps.read_pins()
        self.assertNotIn(self.p_old, [r["id"] for r in rows])
        self.assertEqual(len(bad), 1)


# ---------------------------------------------------------------- [View changes] after the checkout moved

class ScopedChangesAfterAClone(ScopedRepo):
    """Pin-scoped [View changes] (revision_diff with pin=) finds a moved pin's hunks: it reads the located rows."""

    def test_an_inferred_pin_keeps_its_hunk_in_a_clone_elsewhere(self):
        """The ADR-0005 repository cloned to another path: beta's pin still gets only its own hunk (was the whole commit)."""
        clone = Path(self.tmp.name) / "clone"
        subprocess.run(["git", "clone", "--quiet", str(self.repo), str(clone)], check=True, capture_output=True)
        ps.C.src, ps.C.main = clone / "ms", clone / "ms" / "main.tex"
        code, d = self.diff(self.fix, self.p2)
        self.assertEqual(code, 200, d)
        s = d["scope"]
        self.assertEqual((s["mode"], s["source"], s["hunks"]), ("pin", "inferred", 1))
        self.assertIn("blueberries", s["diff"])


# ---------------------------------------------------------------- rollback to 0.3.x

def load_release(tag):
    """The server module exactly as released in `tag` (from git, with its sibling modules), or None in a shallow clone."""
    r = subprocess.run(["git", "show", "%s:src/limn/server.py" % tag], cwd=ROOT, capture_output=True, timeout=30, check=False)
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
        configure(self.v030, ps.C.src, ps.C.main, ps.C.state)
        return self.v030_call(method, path, body)

    def v030_call(self, method, path, body):
        from test_access import talk_to
        from test_server import req, split_resp
        raw = json.dumps(body).encode() if body is not None else b""
        h = {"Content-Type": "application/json"} if body is not None else {}
        code, _, out = split_resp(talk_to(self.v030, req(method, path, raw, h)))
        configure(ps, ps.C.src, ps.C.main, ps.C.state)
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
        self.assertEqual(self.call("POST", "/api/pins/%d/edit" % self.p_old, {"note": "moved", "base_rev": rev})[0], 200)
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
        self.assertEqual(self.stored()[self.p_new]["file_rel"], "sections/x.tex")   # 0.3.0 left it as it was
        self.assertNotIn("rel_path", self.old("/api/pins/%d" % self.p_new)[1]["pin"])
        self.move()                                                                   # and then the checkout moves
        p = self.api_pins()[self.p_new]
        self.assertEqual((p["file"], p["rel_path"]), (str(self.b / "sections" / "y.tex"), "sections/y.tex"))



class RollbackToV031(RollbackToV030):
    """The same rollback checks against 0.3.1 - the release deployed before this one."""

    TAG = "v0.3.1"


if __name__ == "__main__":
    unittest.main()
