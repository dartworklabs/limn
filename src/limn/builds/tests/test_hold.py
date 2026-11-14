"""Build holds: a held build keeps its reverse-mapping material past current + previous (docs/handbook/build-sync.md
§쪽 교체, docs/handbook/api.md POST /api/hold).

A held page directory that is neither current nor previous is slimmed by commit_pages - its page images go, its PDF,
SyncTeX and recorder files stay - and is never current or previous afterwards. POST /api/hold sets and releases a hold.

Run: uv run pytest -q src/limn/builds/tests/test_hold.py
"""

import json
import subprocess
import threading
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
KEPT = ("main.pdf", "main.synctex.gz", "main.aux", "main.fls", "recipe.json", "source.json")
HA, HB = "holder-a-0123456789", "holder-b-0123456789"  # two browsers' holder keys


def iso(t):
    """A stored time, as holds.json keeps it."""
    return t.isoformat(timespec="seconds")


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
        now = datetime.now().astimezone().replace(microsecond=0)  # stored times keep whole seconds
        names = ["pages-2026110109%04d" % i for i in range(8)]
        for i, name in enumerate(names):
            (self.D.dir / name).mkdir()
            holds.set_hold(self.D, name, 7 - i * 0.5, "alice@example.com", now=now)
        self.assertEqual(set(self.stored_holds()), set(names))
        newest = "pages-20261101200000"
        (self.D.dir / newest).mkdir()
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
        """400 bad_pdf_build for a name that is not a page directory name; 400 not_number for a length that is not a
        finite number, too_small below 0 - codes the viewer already explains. Nothing is stored."""
        for body in ({}, {"build": "../x"}, {"build": "pages-1"}, {"build": 7}):
            with self.subTest(body=body):
                code, d = self.hold(body)
                self.assertEqual((code, d.get("reason")), (400, "bad_pdf_build"), d)
        for days, reason in (("3", "not_number"), (True, "not_number"), (None, "not_number"), ([1], "not_number")):
            with self.subTest(days=days):
                code, d = self.hold({"build": B1, "days": days})
                self.assertEqual((code, d.get("reason")), (400, reason), d)
        for days in (-1, -0.5):
            with self.subTest(days=days):
                code, d = self.hold({"build": B1, "days": days})
                self.assertEqual((code, d.get("reason")), (400, "too_small"), d)
        self.assertEqual(self.stored_holds(), {})

    def test_a_longer_ask_holds_for_seven_days(self):
        """days past 7 is capped at 7: until is seven days ahead, so the caller learns the real end."""
        code, d = self.hold({"build": B1, "days": 30})
        self.assertEqual(code, 200, d)
        ahead = datetime.fromisoformat(d["until"]) - datetime.now().astimezone()
        self.assertTrue(timedelta(days=6, hours=23) < ahead <= timedelta(days=7), ahead)

    def test_a_hold_on_a_directory_deleted_after_the_check_stores_nothing(self):
        """set_hold checks the directory under the holds lock: a build removed after the request's check raises
        HoldBuildGone and writes no hold, and over HTTP that is the pdf_build_gone 404."""
        (self.D.dir / B1 / "page-1.png").unlink()
        with self.assertRaises(holds.HoldBuildGone):
            holds.set_hold(self.D, "pages-19990101000000", 7, "alice@example.com")
        self.assertEqual(self.stored_holds(), {})
        real = holds.set_hold

        def racing(D, name, days, by, now=None, holder=holds.ANONYMOUS):
            """The commit that removes the build lands between the HTTP check and the hold."""
            for f in (D.dir / name).iterdir():
                f.unlink()
            (D.dir / name).rmdir()
            return real(D, name, days, by, now, holder)

        self.commit(B2)  # B1 becomes previous, so a page folder other than the one removed stays on screen
        with mock.patch.object(holds, "set_hold", racing):
            code, d = self.hold({"build": B1})
        self.assertEqual((code, d.get("reason"), d.get("pages_build")), (404, "pdf_build_gone", B2), d)
        self.assertEqual(self.stored_holds(), {})

    def test_a_commit_and_a_hold_do_not_interleave(self):
        """While a commit decides what to keep (retention), a hold waits; once the commit has deleted the build the
        hold finds it gone, so a 200 is never answered on a directory the commit removes."""
        self.commit(B2)
        self.commit(B3)  # B1, unheld, is deleted here; make it again as a folder the next commit's retention removes
        self.make(B1)
        entered = threading.Event()
        outcome = []

        def hold_now():
            """The concurrent hold."""
            entered.wait(5)
            try:
                outcome.append(holds.set_hold(self.D, B1, 7, "alice@example.com"))
            except holds.HoldBuildGone:
                outcome.append("gone")

        t = threading.Thread(target=hold_now)
        t.start()
        with holds.retention(self.D) as held:
            self.assertNotIn(B1, held)
            entered.set()
            t.join(0.3)
            self.assertTrue(t.is_alive())  # the hold waits for the commit's decision
            for f in (self.D.dir / B1).iterdir():
                f.unlink()
            (self.D.dir / B1).rmdir()
        t.join(5)
        self.assertEqual(outcome, ["gone"])
        self.assertEqual(self.stored_holds(), {})

    def test_post_hold_on_a_gone_build_is_pdf_build_gone(self):
        """404 pdf_build_gone naming the build on screen, as a page URL of a gone build answers."""
        code, d = self.hold({"build": "pages-19990101000000"})
        self.assertEqual(code, 404, d)
        self.assertEqual((d["reason"], d["pages_build"]), ("pdf_build_gone", B1))
        self.assertIn("error", d)
        self.assertEqual(self.stored_holds(), {})

    # ------------------------------------------------------------ a hold per holder

    def store(self, body):
        """Write holds.json as given (an older Limn's file, or a hand edit)."""
        files.atomic_write(self.D.dir / holds.HOLDS_NAME, json.dumps(body))

    def test_a_named_share_joins_an_older_entry_without_dropping_its_anonymous_share(self):
        """An entry an older Limn wrote (no holders) is the one share "": a holder joining it keeps that share, the
        build's until stays the later of the two, and releasing the holder's share leaves the older one holding."""
        now = datetime.now().astimezone().replace(microsecond=0)  # stored times keep whole seconds
        old = now + timedelta(days=3)
        self.store({B1: {"until": iso(old), "at": iso(now), "by": "alice@example.com"}})
        self.assertEqual(holds.set_hold(self.D, B1, 1, "bob@example.com", now=now, holder=HA), old)
        stored = self.stored_holds()[B1]
        self.assertEqual(stored["holders"], {"": iso(old), HA: iso(now + timedelta(days=1))})
        self.assertEqual(stored["until"], iso(old))
        self.assertEqual(holds.set_hold(self.D, B1, 0, "bob@example.com", now=now, holder=HA), old)
        self.assertEqual(self.stored_holds()[B1]["holders"], {"": iso(old)})

    def test_releasing_one_of_two_shares_keeps_the_build_slimmed(self):
        """Two holders hold B1; one releases: the answer is the other share's end, the entry stays with that share, and
        later commits slim B1 rather than delete it."""
        now = datetime.now().astimezone().replace(microsecond=0)  # stored times keep whole seconds
        holds.set_hold(self.D, B1, 7, "alice@example.com", now=now, holder=HA)
        holds.set_hold(self.D, B1, 2, "bob@example.com", now=now, holder=HB)
        until = holds.set_hold(self.D, B1, 0, "alice@example.com", now=now, holder=HA)
        self.assertEqual(until, now + timedelta(days=2))
        stored = self.stored_holds()[B1]
        self.assertEqual(stored["holders"], {HB: iso(now + timedelta(days=2))})
        self.assertEqual(stored["until"], iso(now + timedelta(days=2)))
        self.commit(B2)
        self.commit(B3)
        self.assertTrue(build.is_slimmed(self.D.dir / B1))
        for f in KEPT:
            self.assertTrue((self.D.dir / B1 / f).is_file(), f)

    def test_the_only_share_releasing_lets_the_next_commit_delete(self):
        """A build held by one holder alone is let go when that holder releases: the entry goes, and the commits that
        pass it delete the folder instead of slimming it."""
        holds.set_hold(self.D, B1, 7, "alice@example.com", holder=HA)
        self.assertIsNone(holds.set_hold(self.D, B1, 0, "alice@example.com", holder=HA))
        self.assertEqual(self.stored_holds(), {})
        self.commit(B2)
        self.commit(B3)
        self.assertFalse((self.D.dir / B1).exists())

    def test_the_build_ends_with_its_latest_share_not_its_last_set(self):
        """until is the latest end over the shares: a shorter share set after a longer one does not shorten the build,
        and moving the longer one earlier does."""
        now = datetime.now().astimezone().replace(microsecond=0)  # stored times keep whole seconds
        self.assertEqual(holds.set_hold(self.D, B1, 7, "a", now=now, holder=HA), now + timedelta(days=7))
        self.assertEqual(holds.set_hold(self.D, B1, 1, "b", now=now, holder=HB), now + timedelta(days=7))
        self.assertEqual(self.stored_holds()[B1]["until"], iso(now + timedelta(days=7)))
        self.assertEqual(holds.set_hold(self.D, B1, 0.5, "a", now=now, holder=HA), now + timedelta(days=1))
        self.assertEqual(self.stored_holds()[B1]["until"], iso(now + timedelta(days=1)))

    def test_releasing_a_share_that_is_not_there_is_no_error(self):
        """Releasing a holder that holds nothing answers the build's end as it stands, or None when unheld."""
        now = datetime.now().astimezone().replace(microsecond=0)  # stored times keep whole seconds
        self.assertIsNone(holds.set_hold(self.D, B1, 0, "a", now=now, holder=HA))
        holds.set_hold(self.D, B1, 3, "a", now=now, holder=HA)
        self.assertEqual(holds.set_hold(self.D, B1, 0, "b", now=now, holder=HB), now + timedelta(days=3))
        self.assertEqual(set(self.stored_holds()[B1]["holders"]), {HA})

    def test_expired_shares_go_and_live_ones_stay(self):
        """A file mixing ended and live shares is read as the live ones (and rewritten so), with until their latest
        end; an entry whose shares have all ended is dropped although its stored until is still ahead."""
        now = datetime.now().astimezone().replace(microsecond=0)  # stored times keep whole seconds
        past, soon, later = now - timedelta(hours=1), now + timedelta(days=1), now + timedelta(days=5)
        self.make(B2)
        self.store(
            {
                B1: {"until": iso(later), "at": "", "by": "", "holders": {"": iso(past), HA: iso(soon), HB: iso(past)}},
                B2: {"until": iso(later), "at": "", "by": "", "holders": {HA: iso(past)}},
            }
        )
        self.assertEqual(holds.held_builds(self.D, now), {B1})
        stored = self.stored_holds()
        self.assertEqual(set(stored), {B1})
        self.assertEqual(stored[B1]["holders"], {HA: iso(soon)})
        self.assertEqual(stored[B1]["until"], iso(soon))

    def test_malformed_shares_go(self):
        """A share whose key is neither "" nor a well-formed holder, or whose end is not a time with an offset, is
        dropped; the well-formed shares of the same entry stay."""
        now = datetime.now().astimezone().replace(microsecond=0)  # stored times keep whole seconds
        later = iso(now + timedelta(days=2))
        self.store(
            {
                B1: {
                    "until": later,
                    "holders": {
                        "a" * 15: later,
                        "a" * 65: later,
                        "has space 0123456789": later,
                        "a" * 16: (now + timedelta(days=2)).replace(tzinfo=None).isoformat(),
                        "b" * 16: 5,
                        HA: later,
                    },
                }
            }
        )
        self.assertEqual(holds.held_builds(self.D, now), {B1})
        self.assertEqual(self.stored_holds()[B1]["holders"], {HA: later})

    def test_holders_that_is_not_an_object_reads_as_the_older_single_share(self):
        """An entry whose holders is not an object is read as an older Limn's: the share "" until its until. Its
        until decides whether it is held; the file is rewritten with the share spelled out."""
        now = datetime.now().astimezone().replace(microsecond=0)  # stored times keep whole seconds
        later = iso(now + timedelta(days=2))
        for holders_value in ([HA], HA, 5, None):
            with self.subTest(holders=holders_value):
                self.store({B1: {"until": later, "holders": holders_value}})
                self.assertEqual(holds.held_builds(self.D, now), {B1})
                self.assertEqual(self.stored_holds()[B1]["holders"], {"": later})
        self.store({B1: {"until": iso(now - timedelta(hours=1)), "holders": "x"}})
        self.assertEqual(holds.held_builds(self.D, now), set())
        self.assertEqual(self.stored_holds(), {})

    def test_the_seventeenth_share_drops_the_one_expiring_soonest(self):
        """Past MAX_HOLDERS live shares of one build, the other share expiring soonest goes and the new one stays even
        when it is short; a full file (8 builds of 16 longest holders) stays well under HOLDS_MAX_BYTES."""
        now = datetime.now().astimezone().replace(microsecond=0)  # stored times keep whole seconds
        names = ["h%02d-0123456789abcd" % i for i in range(holds.MAX_HOLDERS)]
        for i, h in enumerate(names):
            holds.set_hold(self.D, B1, 7 - i * 0.25, "a", now=now, holder=h)
        self.assertEqual(set(self.stored_holds()[B1]["holders"]), set(names))
        newest = "h-new-0123456789abcd"
        until = holds.set_hold(self.D, B1, 0.1, "a", now=now, holder=newest)
        self.assertEqual(until, now + timedelta(days=7))
        kept = self.stored_holds()[B1]["holders"]
        self.assertEqual(len(kept), holds.MAX_HOLDERS)
        self.assertNotIn(names[-1], kept)  # 3.25 days: the soonest of the others
        self.assertIn(newest, kept)
        # the largest file the limits allow is read whole
        builds_ = ["pages-2026110109%04d" % i for i in range(holds.MAX_HOLDS)]
        for name in builds_:
            (self.D.dir / name).mkdir()
            for i in range(holds.MAX_HOLDERS):
                holds.set_hold(self.D, name, 7, "x" * 200, now=now, holder="%02d" % i + "z" * 62)
        size = (self.D.dir / holds.HOLDS_NAME).stat().st_size
        self.assertLess(size, holds.HOLDS_MAX_BYTES // 2, size)
        self.assertEqual(len(holds.held_builds(self.D, now)), holds.MAX_HOLDS)
        self.assertEqual(len(self.stored_holds()[builds_[-1]]["holders"]), holds.MAX_HOLDERS)

    def test_post_hold_counts_a_hold_per_holder(self):
        """Over HTTP: two holders hold B1; the answer keeps {build, until}; one releases and the build stays held until
        the other's end; the other releases and until is null."""
        code, a = self.hold({"build": B1, "holder": HA})
        self.assertEqual(code, 200, a)
        self.assertEqual(set(a), {"build", "until"})
        code, b = self.hold({"build": B1, "holder": HB, "days": 1})
        self.assertEqual((code, b["until"]), (200, a["until"]))  # the build's end, the later share's
        self.assertEqual(set(self.stored_holds()[B1]["holders"]), {HA, HB})
        code, d = self.hold({"build": B1, "holder": HA, "days": 0})
        self.assertEqual(code, 200, d)
        self.assertEqual(d["until"], self.stored_holds()[B1]["holders"][HB])
        ahead = datetime.fromisoformat(d["until"]) - datetime.now().astimezone()
        self.assertTrue(timedelta(hours=23) < ahead <= timedelta(days=1), ahead)
        code, d = self.hold({"build": B1, "holder": HB, "days": 0})
        self.assertEqual((code, d), (200, {"build": B1, "until": None}))
        self.assertEqual(self.stored_holds(), {})

    def test_post_hold_without_a_holder_is_the_anonymous_share(self):
        """A request naming no holder holds and releases the share "", beside a named one."""
        self.assertEqual(self.hold({"build": B1, "holder": HA})[0], 200)
        self.assertEqual(self.hold({"build": B1, "days": 2})[0], 200)
        self.assertEqual(set(self.stored_holds()[B1]["holders"]), {"", HA})
        code, d = self.hold({"build": B1, "days": 0})
        self.assertEqual(code, 200, d)
        self.assertIsNotNone(d["until"])
        self.assertEqual(set(self.stored_holds()[B1]["holders"]), {HA})

    def test_post_hold_refuses_a_malformed_holder(self):
        """400 bad_holder for a holder that is not a string of 16..64 characters of [A-Za-z0-9_-]; nothing is
        stored."""
        for holder in (
            "a" * 15,
            "a" * 65,
            "",
            " " * 20,
            "has space 0123456789",
            "가" * 16,
            "a" * 16 + "\n",
            1234567890123456,
            None,
            True,
            [HA],
        ):
            with self.subTest(holder=holder):
                code, d = self.hold({"build": B1, "holder": holder})
                self.assertEqual((code, d.get("reason")), (400, "bad_holder"), d)
        for holder in ("a" * 16, "a" * 64, "A-z_0" * 4):
            with self.subTest(holder=holder):
                self.assertEqual(self.hold({"build": B1, "holder": holder, "days": 0})[0], 200)
        self.assertEqual(self.stored_holds(), {})

    def test_releasing_a_share_of_a_gone_build_is_pdf_build_gone(self):
        """A release naming a holder on a build whose folder is gone is the pdf_build_gone 404, as before holders."""
        code, d = self.hold({"build": "pages-19990101000000", "holder": HA, "days": 0})
        self.assertEqual((code, d.get("reason")), (404, "pdf_build_gone"), d)

    def test_both_meta_forms_say_holds_are_per_holder(self):
        """hold_holder is true in the full meta body and in the light poll's."""
        for path in ("/api/meta", "/api/meta?light=1"):
            with self.subTest(path=path):
                code, d = self.call("GET", path)
                self.assertEqual(code, 200, d)
                self.assertIs(d["hold_holder"], True)

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
