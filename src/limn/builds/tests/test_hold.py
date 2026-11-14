"""Build holds: a held build keeps its reverse-mapping material past current + previous (docs/handbook/build-sync.md
§쪽 교체, docs/handbook/api.md POST /api/hold).

A held page directory that is neither current nor previous is slimmed by commit_pages - its page images go, its PDF,
SyncTeX and recorder files stay - and is never current or previous afterwards. POST /api/hold sets and releases a hold.

Run: uv run pytest -q src/limn/builds/tests/test_hold.py
"""

import json
import subprocess
from datetime import datetime, timedelta
from unittest import mock

from limn.builds import artifacts as build, engine as build_engine, holds
from limn.builds.artifacts import BuildOk
from limn.platform import files

from helpers import blank_png, needs_tex, pick, ps
from helpers_access import CAROL, TS_HOST, AccessBase

B1, B2, B3, B4 = (
    "pages-20261101100000",
    "pages-20261101110000",
    "pages-20261101120000",
    "pages-20261101130000",
)
KEPT = ("main.pdf", "main.synctex.gz", "main.aux", "main.fls", "recipe.json")


def no_git(*_a, **_k):
    """git for commit_pages' head: answers "abc1234" without running."""
    return subprocess.CompletedProcess([], 0, stdout="abc1234\n")


class Retention(AccessBase):
    """commit_pages over real page folders of the server copy's single document."""

    def setUp(self):
        """B1 on screen, with two page images and its reverse-mapping files."""
        super().setUp()
        self.D = ps.APP.docs[0]
        self.D.dir.mkdir(parents=True, exist_ok=True)
        self.make(B1)
        files.atomic_write(self.D.dir / "pages.cur", B1)

    def make(self, name):
        """A complete page folder `name`: page-1 30x20 and page-2 40x20, the PDF, SyncTeX, .aux, .fls and recipe."""
        d = self.D.dir / name
        d.mkdir()
        (d / "page-1.png").write_bytes(blank_png(30, 20))
        (d / "page-2.png").write_bytes(blank_png(40, 20))
        for f in KEPT:
            (d / f).write_bytes(b"x " + f.encode())
        return d

    def commit(self, name):
        """Make page folder `name` and commit it (pages.cur moves to it)."""
        d = self.make(name)
        with mock.patch.object(build_engine, "run_git", no_git):
            build_engine.commit_pages(self.D, d)
        return d

    def stored_holds(self):
        """holds.json as stored, or {} when absent."""
        p = self.D.dir / holds.HOLDS_NAME
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def test_a_hold_keeps_the_build_slimmed_across_later_commits(self):
        """B1 held: after B2 it is previous and whole; after B3 and B4 it is still there without page images but with
        its PDF, SyncTeX, .aux, .fls and recipe; B2, not held, is deleted as before."""
        holds.set_hold(self.D, B1, 7, "alice@example.com")
        self.commit(B2)
        self.assertTrue((self.D.dir / B1 / "page-1.png").is_file())
        self.commit(B3)
        self.commit(B4)
        d = self.D.dir / B1
        self.assertTrue(d.is_dir())
        self.assertEqual(sorted(d.glob("page-*.png")), [])
        for f in KEPT:
            self.assertTrue((d / f).is_file(), f)
        self.assertTrue(build.is_slimmed(d))
        self.assertFalse((self.D.dir / B2).exists())
        # the recorded sizes answer what the images would have
        self.assertEqual(
            [(p["name"], p["pt_w"], p["pt_h"]) for p in build.page_sizes(d, 72)],
            [("page-1.png", 30.0, 20.0), ("page-2.png", 40.0, 20.0)],
        )

    def test_an_expired_hold_keeps_nothing(self):
        """A hold that ended is dropped from holds.json and its build is deleted on the next commit, as unheld."""
        past = datetime.now().astimezone() - timedelta(days=3)
        holds.set_hold(self.D, B1, 1, "alice@example.com", now=past)
        self.assertIn(B1, self.stored_holds())
        self.commit(B2)
        self.commit(B3)
        self.assertFalse((self.D.dir / B1).exists())
        self.assertEqual(self.stored_holds(), {})

    def test_the_ninth_hold_drops_the_one_expiring_soonest(self):
        """Past eight live holds the other one expiring soonest goes; the new one stays even when it is short."""
        now = datetime.now().astimezone()
        names = ["pages-2026110110%04d" % i for i in range(8)]
        for i, name in enumerate(names):
            holds.set_hold(self.D, name, 7 - i * 0.5, "alice@example.com", now=now)
        self.assertEqual(set(self.stored_holds()), set(names))
        newest = "pages-20261101200000"
        holds.set_hold(self.D, newest, 0.25, "bob@example.com", now=now)
        kept = self.stored_holds()
        self.assertEqual(len(kept), holds.MAX_HOLDS)
        self.assertNotIn(names[-1], kept)  # 3.5 days: the soonest of the others
        self.assertIn(newest, kept)
        self.assertEqual(kept[newest]["by"], "bob@example.com")

    def test_a_slimmed_build_is_never_current_or_previous(self):
        """With B1 slimmed and the real previous gone, previous_pages has none rather than B1, and the screen stays on
        the newest build; a pick or a pin naming B1 still resolves against it (pages_dir_for)."""
        holds.set_hold(self.D, B1, 7, "alice@example.com")
        self.commit(B2)
        self.commit(B3)
        self.assertTrue(build.is_slimmed(self.D.dir / B1))
        self.assertEqual(build.cur_pages(self.D).name, B3)
        self.assertEqual(build.previous_pages(self.D), self.D.dir / B2)
        (self.D.dir / B2 / "page-1.png").unlink()
        for f in (self.D.dir / B2).iterdir():
            f.unlink()
        (self.D.dir / B2).rmdir()
        self.assertIsNone(build.previous_pages(self.D))
        self.assertEqual(build.cur_pages(self.D).name, B3)
        self.assertEqual(build.pages_dir_for(self.D, B1), self.D.dir / B1)
        # another commit keeps B1 slimmed and never makes it the previous one
        self.commit(B4)
        self.assertEqual(build.previous_pages(self.D), self.D.dir / B3)
        self.assertTrue(build.is_slimmed(self.D.dir / B1))

    # ------------------------------------------------------------ POST /api/hold

    def hold(self, body, **kwargs):
        """POST /api/hold with this body -> (status, JSON)."""
        return self.call("POST", "/api/hold", body, **kwargs)

    def test_post_hold_answers_the_build_and_until(self):
        """200 {build, until}: until is about seven days ahead by default, sooner when days asks; the hold is stored with
        who set it."""
        code, d = self.hold({"build": B1})
        self.assertEqual(code, 200, d)
        self.assertEqual(set(d), {"build", "until"})
        self.assertEqual(d["build"], B1)
        until = datetime.fromisoformat(d["until"])
        self.assertIsNotNone(until.tzinfo)
        ahead = until - datetime.now().astimezone()
        self.assertTrue(timedelta(days=6, hours=23) < ahead <= timedelta(days=7), ahead)
        code, d = self.hold({"build": B1, "days": 1.5})
        self.assertEqual(code, 200, d)
        ahead = datetime.fromisoformat(d["until"]) - datetime.now().astimezone()
        self.assertTrue(timedelta(hours=35) < ahead <= timedelta(hours=36), ahead)
        self.assertEqual(self.stored_holds()[B1]["until"], d["until"])
        self.assertIn("by", self.stored_holds()[B1])

    def test_days_zero_releases_and_the_next_commit_deletes(self):
        """days 0 answers until null and removes the hold; the build then goes on the commit that passes it."""
        self.assertEqual(self.hold({"build": B1})[0], 200)
        code, d = self.hold({"build": B1, "days": 0})
        self.assertEqual((code, d), (200, {"build": B1, "until": None}))
        self.assertEqual(self.stored_holds(), {})
        self.commit(B2)
        self.commit(B3)
        self.assertFalse((self.D.dir / B1).exists())

    def test_post_hold_refuses_a_bad_name_or_length(self):
        """400 bad_pdf_build for a name that is not a page directory name; 400 bad_days for a length outside 0..7 or not a
        number. Nothing is stored."""
        for body in ({}, {"build": "../x"}, {"build": "pages-1"}, {"build": 7}):
            with self.subTest(body=body):
                code, d = self.hold(body)
                self.assertEqual((code, d.get("reason")), (400, "bad_pdf_build"), d)
        for days in (-1, 7.5, 8, "3", True, None, [1]):
            with self.subTest(days=days):
                code, d = self.hold({"build": B1, "days": days})
                self.assertEqual((code, d.get("reason")), (400, "bad_days"), d)
        self.assertEqual(self.stored_holds(), {})

    def test_post_hold_on_a_gone_build_is_pdf_build_gone(self):
        """404 pdf_build_gone naming the build on screen, as a page URL of a gone build answers."""
        code, d = self.hold({"build": "pages-19990101000000"})
        self.assertEqual(code, 404, d)
        self.assertEqual((d["reason"], d["pages_build"]), ("pdf_build_gone", B1))
        self.assertIn("error", d)
        self.assertEqual(self.stored_holds(), {})

    def test_a_viewer_may_not_hold(self):
        """A viewer is refused (403 viewer_only) before anything is stored; an editor and the owner may hold."""
        self.set_people(
            [
                {"login": "alice@example.com", "name": "Alice", "role": "owner"},
                {"login": "carol@example.com", "name": "Carol", "role": "viewer"},
            ]
        )
        code, d = self.hold({"build": B1}, headers=dict(CAROL, Host=TS_HOST))
        self.assertEqual((code, d.get("reason")), (403, "viewer_only"), d)
        self.assertEqual(self.stored_holds(), {})


class HeldPick(AccessBase):
    """A real build, held, slimmed by two later builds, still answers a pick with lines."""

    @needs_tex("latexmk", "pdftoppm", "pdftotext", "synctex")
    def test_pick_on_a_held_and_slimmed_build_answers_its_lines(self):
        """B1 held over HTTP, two forced rebuilds slim it; a pick naming B1 answers a quote and B1 as its build."""
        D = ps.APP.docs[0]
        self.assertIsInstance(ps.APP.build_requests.build_all(D), BuildOk)
        b1 = build.cur_pages(D).name
        p = build.page_list(build.cur_pages(D), ps.APP.C.dpi)[0]
        before = pick({"page": 1, "x0": 0, "y0": 0, "x1": p["pt_w"], "y1": p["pt_h"] * 0.4, "pdf_build": b1})
        code, d = self.call("POST", "/api/hold", {"build": b1})
        self.assertEqual(code, 200, d)
        for _ in range(2):
            self.assertIsInstance(ps.APP.build_requests.build_all(D, force=True), BuildOk)
        held = D.dir / b1
        self.assertTrue(build.is_slimmed(held))
        self.assertEqual(sorted(held.glob("page-*.png")), [])
        self.assertNotIn(build.cur_pages(D).name, (b1,))
        self.assertNotEqual(build.previous_pages(D), held)
        after = pick({"page": 1, "x0": 0, "y0": 0, "x1": p["pt_w"], "y1": p["pt_h"] * 0.4, "pdf_build": b1})
        self.assertNotIn("pdf_build_gone", after)
        self.assertEqual(after["pdf_build"], b1)
        self.assertIn("quote", after)
        self.assertEqual(after.get("lo"), before.get("lo"))
        self.assertEqual(after.get("hi"), before.get("hi"))
