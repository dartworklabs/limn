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
import time
import unittest
from pathlib import Path
from unittest import mock

from test_access import ALICE, AccessBase, talk_to
from test_qa_021 import BrowserBase, actor
from test_server import Base, ps, req, split_resp

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
    return ps.FileChange(old_path, new_path, ps.git_lines(o), ps.git_lines(n), tuple(ps.parse_u0_blocks(patch)), False)


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
    def test_git_lines_split_on_newline_only_and_keep_a_missing_final_newline(self):
        self.assertEqual(ps.git_lines(b"a\r\nb\rc\nd"), (b"a\r\n", b"b\rc\n", b"d"))
        self.assertEqual(ps.git_lines(b""), ())
        self.assertEqual(ps.git_lines(b"x\n"), (b"x\n",))

    def test_u0_headers_become_zero_based_blocks(self):
        self.assertEqual([tuple(b) for b in ps.parse_u0_blocks(U0)], [A_BLK, B_BLK, C_BLK])
        # pure insertion after old line 5: the old span is empty and sits before old index 5
        self.assertEqual(tuple(ps.parse_u0_blocks(b"@@ -5,0 +6,2 @@\n+x\n+y\n")[0]), (5, 0, 5, 2))
        self.assertEqual(tuple(ps.parse_u0_blocks(b"@@ -0,0 +1,3 @@\n+a\n+b\n+c\n")[0]), (0, 0, 0, 3))   # new file
        self.assertEqual(ps.parse_u0_blocks(b"diff --git a/x b/x\nBinary files a/x and b/x differ\n"), [])

    def test_touch_range_covers_the_lines_around_an_insertion_or_deletion_point(self):
        self.assertEqual(ps.touch_range(3, 2), (4, 5))
        self.assertEqual(ps.touch_range(18, 0), (18, 19))
        self.assertEqual(ps.touch_range(0, 0), (1, 1))


class Attribution(unittest.TestCase):
    def setUp(self):
        self.files = [fc()]

    def blocks_for(self, pin, rel="ms/main.tex", changes=None):
        source, chosen = ps.attribute_blocks(self.files, pin, rel, changes or [])
        return source, sorted(tuple(self.files[fi].blocks[bi]) for fi, bi in chosen)

    def test_overlap_on_the_new_side(self):
        # alpha was edited in place (its first 40 characters survived), so its anchor is found on the new side
        self.assertEqual(self.blocks_for(anchored(4, 4)), ("inferred", [A_BLK]))

    def test_mapping_through_line_shifts(self):
        # beta's own text changed, so the pin kept its pre-edit line 11 (stale); on the new side line 11 is blank
        # (alpha's extra line shifted beta to 12). Mapping the range through the commit still finds beta's hunk.
        self.assertEqual(self.blocks_for(anchored(11, 11, stale=True, sync="lost")), ("inferred", [B_BLK]))
        # and a pin that was re-synced to the new side (line 12) lands on the same hunk
        self.assertEqual(self.blocks_for(anchored(12, 12, text=NEW)), ("inferred", [B_BLK]))

    def test_raw_range_without_an_anchor(self):
        self.assertEqual(self.blocks_for({"id": 1, "file": "/x", "lo": 12, "hi": 12}), ("inferred", [B_BLK]))
        self.assertEqual(self.blocks_for({"id": 1, "file": "/x", "lo": 11, "hi": 11, "stale": True}), ("inferred", [B_BLK]))
        self.assertEqual(self.blocks_for({"id": 1, "file": "/x", "lo": 7, "hi": 8}), ("none", []))

    def test_deleted_range(self):
        self.assertEqual(self.blocks_for(anchored(18, 18, stale=True, sync="lost")), ("inferred", [C_BLK]))

    def test_three_pins_in_one_commit_get_disjoint_hunks_that_cover_the_commit(self):
        pins = [anchored(4, 4), anchored(11, 11, stale=True), anchored(18, 18, stale=True)]
        got = [set(ps.attribute_blocks(self.files, p, "ms/main.tex", [])[1]) for p in pins]
        self.assertEqual([len(g) for g in got], [1, 1, 1])
        self.assertEqual(set.union(*got), {(0, 0), (0, 1), (0, 2)})

    def test_other_files_and_renames(self):
        self.assertEqual(self.blocks_for(anchored(4, 4), rel="ms/other.tex"), ("none", []))
        self.files = [fc(old_path="ms/old.tex", new_path="ms/new.tex")]
        self.assertEqual(self.blocks_for(anchored(4, 4), rel="ms/new.tex"), ("inferred", [A_BLK]))
        self.assertEqual(self.blocks_for(anchored(11, 11, stale=True), rel="ms/old.tex"), ("inferred", [B_BLK]))

    def test_recorded_changes_win_over_inference(self):
        pin = anchored(4, 4)
        self.assertEqual(self.blocks_for(pin, changes=[("ms/main.tex", 12, 12)]), ("changes", [B_BLK]))
        # the line after a deletion names the deletion
        self.assertEqual(self.blocks_for(pin, changes=[("ms/main.tex", 19, 19)]), ("changes", [C_BLK]))
        self.assertEqual(self.blocks_for(pin, changes=[("ms/main.tex", 4, 5), ("ms/main.tex", 12, 12)]),
                         ("changes", [A_BLK, B_BLK]))
        # ranges that hit nothing in this commit (a different commit, a wrong file) fall back to inference
        self.assertEqual(self.blocks_for(pin, changes=[("ms/main.tex", 7, 8)]), ("inferred", [A_BLK]))
        self.assertEqual(self.blocks_for(pin, changes=[("ms/x.tex", 4, 5)]), ("inferred", [A_BLK]))

    def test_a_region_pin_or_a_pin_without_lines_gets_nothing(self):
        self.assertEqual(self.blocks_for({"id": 1, "pdf": "/x.pdf", "page": 1, "frac": [0, 0, 1, 1]}, rel=None), ("none", []))


class ScopedPatch(unittest.TestCase):
    def setUp(self):
        self.files = [fc()]

    def test_pin_hunk_keeps_real_new_side_line_numbers_and_no_foreign_lines(self):
        text, n = ps.scoped_patch(self.files, {(0, 1)}, True)
        self.assertEqual(n, 1)
        self.assertEqual(text, "diff --git a/ms/main.tex b/ms/main.tex\n--- a/ms/main.tex\n+++ b/ms/main.tex\n"
                               "@@ -8,7 +9,7 @@\n Filler three.\n Filler four.\n \n-Beta paragraph talks about bananas.\n"
                               "+Beta paragraph talks about blueberries.\n \n Filler five.\n Filler six.\n")
        other, n_other = ps.scoped_patch(self.files, {(0, 1)}, False)
        self.assertEqual(n_other, 2)
        self.assertIn("+A second alpha sentence.", other)
        self.assertIn("-Gamma paragraph talks about cherries.", other)
        self.assertNotIn("Beta", other)

    def test_context_stops_at_a_foreign_block_and_close_pin_blocks_merge(self):
        old = "".join("l%d\n" % i for i in range(1, 11))
        new = old.replace("l3\n", "L3\n").replace("l5\n", "L5\n").replace("l7\n", "L7\n")
        patch = b"@@ -3 +3 @@\n-l3\n+L3\n@@ -5 +5 @@\n-l5\n+L5\n@@ -7 +7 @@\n-l7\n+L7\n"
        files = [fc(old, new, patch)]
        text, n = ps.scoped_patch(files, {(0, 0), (0, 2)}, True)
        self.assertEqual(n, 2)                                     # l5 (someone else's) splits them
        self.assertNotIn("l5", text)
        self.assertNotIn("L5", text)
        self.assertIn("@@ -1,4 +1,4 @@\n l1\n l2\n-l3\n+L3\n l4\n", text)
        self.assertIn("@@ -6,5 +6,5 @@\n l6\n-l7\n+L7\n l8\n l9\n l10\n", text)
        text, n = ps.scoped_patch(files, {(0, 0), (0, 1)}, True)
        self.assertEqual(n, 1)                                     # adjacent blocks of the same pin are one place
        self.assertIn("@@ -1,5 +1,5 @@\n l1\n l2\n-l3\n+L3\n l4\n-l5\n+L5\n", text)

    def test_missing_final_newline_is_marked_like_git(self):
        files = [fc("a\nb", "a\nc", b"@@ -2 +2 @@\n-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n")]
        text, _ = ps.scoped_patch(files, {(0, 0)}, True)
        self.assertTrue(text.endswith("-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n"), text)

    def test_file_headers_for_new_deleted_and_renamed_files(self):
        files = [fc("", "x\n", b"@@ -0,0 +1 @@\n+x\n", old_path=None, new_path="ms/n.tex"),
                 fc("y\n", "", b"@@ -1 +0,0 @@\n-y\n", old_path="ms/d.tex", new_path=None),
                 fc(OLD, NEW, U0, old_path="ms/a.tex", new_path="ms/b.tex")]
        text, n = ps.scoped_patch(files, {(0, 0), (1, 0), (2, 0)}, True)
        self.assertIn("diff --git a/ms/n.tex b/ms/n.tex\nnew file mode 100644\n--- /dev/null\n+++ b/ms/n.tex\n@@ -0,0 +1,1 @@\n+x\n", text)
        self.assertIn("diff --git a/ms/d.tex b/ms/d.tex\ndeleted file mode 100644\n--- a/ms/d.tex\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-y\n", text)
        self.assertIn("diff --git a/ms/a.tex b/ms/b.tex\nrename from ms/a.tex\nrename to ms/b.tex\n--- a/ms/a.tex\n+++ b/ms/b.tex\n", text)
        self.assertEqual(n, 3)

    def test_blockless_changes_count_as_other_places(self):
        files = [fc(), ps.FileChange("ms/fig.tex", "ms/fig2.tex", (), (), (), False),
                 ps.FileChange("ms/x.bib", "ms/x.bib", (), (), (), True)]
        text, n = ps.scoped_patch(files, {(0, 0), (0, 1), (0, 2)}, False)
        self.assertEqual(n, 2)
        self.assertIn("rename from ms/fig.tex", text)
        self.assertIn("Binary files a/ms/x.bib and b/ms/x.bib differ", text)


class ApplyBlocks(unittest.TestCase):
    def test_synthetic_new_version_is_old_plus_only_the_chosen_blocks(self):
        f = fc()
        self.assertEqual(ps.apply_blocks(f, {0, 1, 2}), NEW.encode())
        self.assertEqual(ps.apply_blocks(f, set()), OLD.encode())
        self.assertEqual(ps.apply_blocks(f, {1}), OLD.replace("bananas", "blueberries").encode())
        self.assertEqual(ps.apply_blocks(f, {2}), OLD.replace("Gamma paragraph talks about cherries.\n", "").encode())

    def test_missing_final_newline(self):
        f = fc("a\nb", "a\nc", b"@@ -2 +2 @@\n-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n")
        self.assertEqual(ps.apply_blocks(f, {0}), b"a\nc")


@unittest.skipUnless(shutil.which("git"), "git not available")
class GitBlocks(unittest.TestCase):
    """The parser against what real git prints, and a seeded property check: any subset applied, then the rest, is the new file."""

    def u0(self, old: bytes, new: bytes) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d, "a"), Path(d, "b")
            a.write_bytes(old)
            b.write_bytes(new)
            r = subprocess.run(["git", "diff", "--no-index", "--no-color", "-U0", str(a), str(b)], capture_output=True)
            return r.stdout

    def test_fixture_patch_matches_git(self):
        self.assertEqual([tuple(b) for b in ps.parse_u0_blocks(self.u0(OLD.encode(), NEW.encode()))], [A_BLK, B_BLK, C_BLK])

    def test_random_edits_round_trip(self):
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
            f = ps.FileChange("m.tex", "m.tex", ps.git_lines(o), ps.git_lines(n), tuple(ps.parse_u0_blocks(self.u0(o, n))), False)
            self.assertEqual(ps.apply_blocks(f, set(range(len(f.blocks)))), n)
            self.assertEqual(ps.apply_blocks(f, set()), o)
            if f.blocks:
                k = rnd.randrange(len(f.blocks))
                mid = ps.apply_blocks(f, {k})
                # the synthetic version, diffed against old, contains exactly that one change
                self.assertEqual(len(ps.parse_u0_blocks(self.u0(o, mid))) if mid != o else 0, 1 if mid != o else 0)


# ---------------------------------------------------------------- 2. the close contract: optional `changes`

class CloseChanges(AccessBase):
    def setUp(self):
        super().setUp()
        (self.src / "sec").mkdir()
        (self.src / "sec" / "a.tex").write_text("x\n" * 30)
        self.pid = self.add()

    def close(self, body):
        return self.call("POST", "/api/pins/%d/close" % self.pid, body)

    def test_valid_changes_are_stored_normalised_and_exposed(self):
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

    def test_invalid_changes_are_rejected_and_change_nothing(self):
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
        for whole in ({"file": "main.tex", "lo": 1, "hi": 1}, "x", [{"file": "main.tex", "lo": 1, "hi": 1}] * (ps.CLOSE_CHANGES_MAX + 1)):
            with self.subTest(whole=str(whole)[:40]):
                code, d = self.close({"changes": whole})
                self.assertEqual(code, 400, d)
        self.assertFalse(self.pin(self.pid).get("done"))

    def test_absent_or_empty_changes_keep_the_old_behaviour(self):
        code, d = self.close({"changes": []})
        self.assertEqual(code, 200)
        self.assertNotIn("changes", d["pin"])
        other = self.add(lo=8, hi=9)
        code, d = self.call("POST", "/api/pins/%d/close" % other)
        self.assertEqual((code, "changes" in d["pin"]), (200, False))

    def test_reclose_keeps_and_reopen_clears_changes(self):
        self.close({"changes": [{"file": "main.tex", "lo": 4, "hi": 5}]})
        self.close({"changes": [{"file": "main.tex", "lo": 9, "hi": 9}]})
        self.assertEqual(self.pin(self.pid)["changes"][0]["lo"], 4)
        self.call("POST", "/api/pins/%d/reopen" % self.pid, {})
        self.assertNotIn("changes", self.pin(self.pid))

    def test_a_malformed_stored_changes_field_marks_the_line_broken(self):
        r = dict(self.pin(self.pid), changes=[{"file": 3, "lo": 1, "hi": 2}])
        self.assertFalse(ps.valid_rec(r))
        self.assertTrue(ps.valid_rec(dict(r, changes=[{"file": "/a.tex", "lo": 1, "hi": 2}])))

    def test_pins_md_close_instruction_line_names_one_commit_per_pin_and_changes(self):
        text = ps.pins_md_text(ps.snapshot_pins())
        line = next(l for l in text.splitlines() if l.startswith("처리한 핀은 닫는다"))
        self.assertTrue(line.startswith("처리한 핀은 닫는다 — 핀 하나에 커밋 하나로 고치고(PR 하나에 커밋 여럿은 괜찮다) "
                                        "`ref` 에 그 커밋 해시를 적는다: `curl -X POST"), line)
        self.assertIn('"ref":"그 핀의 커밋 해시(≤80자)","changes":[{"file":"main.tex","lo":12,"hi":14}]}\' '
                      'http://127.0.0.1:18999/api/pins/N/close`', line)
        self.assertIn("`changes` 는 선택: 그 커밋에서 이 핀 때문에 바꾼 줄 범위, 커밋 뒤 줄 번호, 경로는 위치 칸 기준", line)
        # everything after the close example is the v0.2.2 text, unchanged
        self.assertIn(") · 줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다 · '질문' 핀은 원고를 고치지 말고", line)
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


class ScopedSourceDiff(ScopedRepo):
    def test_each_pin_sees_only_its_hunks_and_the_rest_folded(self):
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

    def test_beta_keeps_its_real_line_number(self):
        _, d = self.diff(self.fix, self.p2)
        self.assertIn("@@ -8,7 +9,7 @@", d["scope"]["diff"])

    def test_a_commit_that_belongs_entirely_to_the_pin_is_shown_whole(self):
        _, d = self.diff(self.solo, self.p4)
        s = d["scope"]
        self.assertEqual((s["mode"], s["hunks"], s["other"]), ("commit", 1, 0))
        self.assertNotIn("other_diff", s)

    def test_a_pin_the_commit_does_not_touch_gets_the_whole_commit(self):
        _, d = self.diff(self.solo, self.p2)
        self.assertEqual((d["scope"]["mode"], d["scope"]["source"], d["scope"]["hunks"]), ("commit", "none", 0))

    def test_without_pin_the_response_is_unchanged(self):
        code, d = self.diff(self.fix)
        self.assertEqual((code, sorted(d)), (200, ["diff", "id", "truncated"]))

    def test_bad_or_foreign_pins_are_refused(self):
        self.assertEqual(self.diff(self.fix, "x")[0], 400)
        self.assertEqual(self.diff(self.fix, "-1")[0], 400)
        self.assertEqual(self.diff(self.fix, "999")[0], 404)

    def test_rename_in_the_commit(self):
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
                _, d = self.diff(mv, pid)
                s = d["scope"]
                self.assertEqual((s["mode"], s["hunks"], s["other"]), ("pin", 1, 1))
                self.assertIn("diff --git a/ms/part.tex b/ms/chapter.tex\nrename from ms/part.tex\nrename to ms/chapter.tex\n", s["diff"])
                self.assertIn("+Part line twelve.", s["diff"])
                self.assertNotIn("input", s["diff"])
                self.assertIn("+\\input{chapter}", s["other_diff"])


class ScopedPdf(ScopedRepo):
    def test_spec_key_depends_on_pin_commit_and_hunk_set(self):
        whole = ps.revision_spec(ps.cur_doc(), self.fix)
        s1, s2 = ps.revision_spec(ps.cur_doc(), self.fix, self.p1), ps.revision_spec(ps.cur_doc(), self.fix, self.p2)
        self.assertEqual(whole.scope, ())
        self.assertEqual(len({whole.key, s1.key, s2.key}), 3)
        self.assertEqual(s1.key, ps.revision_spec(ps.cur_doc(), self.fix, self.p1).key)     # stable
        # a pin whose commit is entirely its own shares the whole-commit comparison (and its cache)
        self.assertEqual(ps.revision_spec(ps.cur_doc(), self.solo, self.p4).key, ps.revision_spec(ps.cur_doc(), self.solo).key)
        # the recorded change set is part of the identity: a different set is a different comparison
        rows = ps.snapshot_pins()
        ps.find_pin(rows, self.p1)["changes"] = [{"file": str(self.main.resolve()), "lo": 12, "hi": 12}]
        ps.write_pins(rows)
        self.assertNotEqual(ps.revision_spec(ps.cur_doc(), self.fix, self.p1).key, s1.key)

    def test_http_build_accepts_pin_and_reports_scope(self):
        seen = []

        def compile(spec, jobdir, timeout):
            seen.append(spec.scope)
            (jobdir / "revision.pdf").write_bytes(minimal_pdf("x"))
            return {"state": "ready", "warnings": [], "error": None, "reason": None}
        with mock.patch.object(ps, "revision_compile", side_effect=compile):
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
    def test_actual_scoped_build_marks_only_the_pin(self):
        dest = self.repo / "job-beta"
        dest.mkdir()
        status = ps.revision_compile(ps.revision_spec(ps.cur_doc(), self.fix, self.p2), dest, 60)
        self.assertEqual(status["state"], "ready", status)
        text = subprocess.check_output(["pdftotext", str(dest / "revision.pdf"), "-"], text=True)
        self.assertIn("blueberries", text)
        self.assertIn("bananas", text)
        self.assertNotIn("pears", text)                    # alpha's change is not applied
        self.assertIn("cherries", text)                    # gamma is still there, unmarked
        self.assertNotIn("second alpha", text)
        whole = self.repo / "job-whole"
        whole.mkdir()
        ps.revision_compile(ps.revision_spec(ps.cur_doc(), self.fix), whole, 60)
        self.assertIn("pears", subprocess.check_output(["pdftotext", str(whole / "revision.pdf"), "-"], text=True))
        self.assertEqual(self.main.read_text(encoding="utf-8"), NEW.replace("Filler two.", "Filler two, reworded."))

    @unittest.skipUnless(all(shutil.which(t) for t in ("bwrap", "latexdiff", "latexmk")), "TeX sandbox tools unavailable")
    def test_a_subset_that_does_not_compile_fails_as_an_error(self):
        # one commit opens an environment for one pin and closes it for another: each half alone does not compile
        base = NEW.replace("Filler two.", "Filler two, reworded.")
        self.write(base.replace("Filler one.", "\\begin{itemize}\\item Filler one.").replace("Filler eight.", "Filler eight.\\end{itemize}"))
        both = self.commit("wrap the fillers in a list")
        opener = self.add(lo=7, hi=7, note="open")
        ps.set_done(opener, True, dict(ps.LOCAL_ACTOR), ref=both[:8],
                    changes=[{"file": str(self.main.resolve()), "lo": 7, "hi": 7}])
        spec = ps.revision_spec(ps.cur_doc(), both, opener)
        self.assertEqual(len(spec.scope), 1)
        dest = self.repo / "job-half"
        dest.mkdir()
        with self.assertRaises(ps.HTTPError) as e:
            ps.revision_compile(spec, dest, 60)
        self.assertIn(e.exception.body.get("reason"), ("compile_failed", "diff_failed"))
        whole = self.repo / "job-both"
        whole.mkdir()
        self.assertEqual(ps.revision_compile(ps.revision_spec(ps.cur_doc(), both), whole, 60)["state"], "ready")


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
        self.p1 = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 4, "page": 1, "note": "alpha"}, A)
        self.p2 = ps.add_pin({"file": str(self.main), "lo": 11, "hi": 11, "page": 1, "note": "beta"}, A)
        self.p3 = ps.add_pin({"file": str(self.main), "lo": 18, "hi": 18, "page": 1, "note": "gamma"}, A)
        self.write(NEW)
        self.fix = self.commit("fix three pins")
        loc = dict(ps.LOCAL_ACTOR)
        ps.set_done(self.p1, True, loc, reply="alpha", ref=self.fix[:8], changes=[{"file": str(self.main.resolve()), "lo": 4, "hi": 5}])
        ps.set_done(self.p2, True, loc, reply="beta", ref=self.fix[:8])
        ps.set_done(self.p3, True, loc, reply="gamma", ref=self.fix[:8])
        self.p4 = ps.add_pin({"file": str(self.main), "lo": 8, "hi": 8, "page": 1, "note": "filler"}, A)
        self.write(NEW.replace("Filler two.", "Filler two, reworded."))
        self.solo = self.commit("fix the filler pin")
        ps.set_done(self.p4, True, loc, reply="filler", ref=self.solo[:8])
        self.builds = []
        self.fail_scoped = False
        patcher = mock.patch.object(ps, "revision_compile", side_effect=self.fake_compile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_compile(self, spec, jobdir, timeout):
        self.builds.append((spec.head, spec.scope))
        if spec.scope and self.fail_scoped:
            raise ps.HTTPError(422, "비교 PDF 컴파일에 실패했습니다.", reason="compile_failed")
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

    def test_source_diff_filter_and_pdf_toggle(self):
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

    def test_other_changes_are_hidden_again_for_the_next_pin(self):
        page = self.open_change("desktop", "ko", self.p2)
        page.click("#revision-other-toggle")
        page.evaluate("showChange(%d)" % self.p1)
        page.wait_for_function("document.getElementById('revision-diff').textContent.includes('pears')", timeout=15000)
        self.assertEqual(page.get_attribute("#revision-other-toggle", "aria-expanded"), "false")
        self.assertFalse(self.visible(page, "#revision-other"))
        self.assertNotIn("blueberries", page.inner_text("#revision-diff"))
