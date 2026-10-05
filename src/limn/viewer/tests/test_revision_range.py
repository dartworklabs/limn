"""The changes view's commit picker (issue #188, variant C, docs/handbook/viewer.md §변경 보기): the quick range
[마지막으로 본 뒤 N | 이 커밋부터 | 이 커밋만], the commit list that stays on screen, a row press, the last-seen commit kept
in this browser, and the desktop and phone layouts - against real Git history, with the comparison build faked.

The pure rules (rangePress, rangeRequest, rangeMode, seenCount) run under node from the served source; the rest drives
Chromium.

Run: LIMN_TEST_REQUIRE_BROWSER=1 uv run pytest -q src/limn/viewer/tests/test_revision_range.py
"""

import json
import os
import subprocess
import unittest
from unittest import mock

from limn.revisions import core as revisions, execution as revision_execution
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, extract_js_fn, jreq, ps, run_node
from helpers_browser import BrowserBase

PHONE = {"viewport": {"width": 411, "height": 908}, "is_mobile": True, "has_touch": True}
DESKTOP = {"viewport": {"width": 1440, "height": 900}}


def fake_compile(spec, jobdir, timeout):
    """A comparison build that writes a minimal one-page PDF instead of running latexdiff and latexmk."""
    pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    )
    (jobdir / "revision.pdf").write_bytes(pdf)
    return revisions.ComparisonBuilt([])


class RangeRules(unittest.TestCase):
    """The picker's rules as pure functions of the loaded rows (newest first)."""

    ROWS = [
        {"id": "c4", "parents": ["c3"]},
        {"id": "c3", "parents": ["c2", "x9"]},
        {"id": "c2", "parents": ["c1"]},
        {"id": "c1", "parents": []},
    ]

    def run_rules(self, expr: str):
        """Evaluate expr under node with the served rule functions and ROWS defined; its JSON value."""
        js = "".join(extract_js_fn(n) + "\n" for n in ("rangePress", "rangeRequest", "rangeMode", "paintedIds"))
        out = run_node(js + "const ROWS=%s;\nconsole.log(JSON.stringify(%s));" % (json.dumps(self.ROWS), expr))
        if out is None:
            self.skipTest("node not available")
        return json.loads(out)

    def test_a_row_press_starts_from_that_commit_and_a_newer_press_ends_it(self):
        """In 'from' (and 'last') a press is that commit to the newest; a newer row pressed next becomes the end; the
        start pressed again is that commit alone; in 'one' a press is that commit alone."""
        last = {"mode": "last", "start": "c4", "end": "c4", "endSet": False}
        first = self.run_rules("rangePress(ROWS,%s,'c2')" % json.dumps(last))
        self.assertEqual(first, {"mode": "from", "start": "c2", "end": "c4", "endSet": False})
        second = self.run_rules("rangePress(ROWS,%s,'c3')" % json.dumps(first))
        self.assertEqual(second, {"mode": "from", "start": "c2", "end": "c3", "endSet": True})
        again = self.run_rules("rangePress(ROWS,%s,'c2')" % json.dumps(second))
        self.assertEqual((again["start"], again["end"]), ("c2", "c2"))
        older = self.run_rules("rangePress(ROWS,%s,'c1')" % json.dumps(second))
        self.assertEqual(older, {"mode": "from", "start": "c1", "end": "c4", "endSet": False})
        one = self.run_rules("rangePress(ROWS,{mode:'one',start:'c4',end:'c4',endSet:false},'c3')")
        self.assertEqual(one, {"mode": "one", "start": "c3", "end": "c3", "endSet": False})

    def test_the_request_of_each_mode(self):
        """'one' asks for the commit alone; 'from' for its first parent to the end; 'last' for the last-seen commit
        to the newest; a root start or a start that is its end is the commit alone."""
        req = self.run_rules(
            "["
            "rangeRequest(ROWS,{mode:'one',start:'c3',end:'c3'},null),"
            "rangeRequest(ROWS,{mode:'from',start:'c3',end:'c4'},null),"
            "rangeRequest(ROWS,{mode:'last',start:'c3',end:'c4'},{id:'c2'}),"
            "rangeRequest(ROWS,{mode:'from',start:'c1',end:'c4'},null),"
            "rangeRequest(ROWS,{mode:'from',start:'c2',end:'c2'},null)"
            "]"
        )
        self.assertEqual(
            req,
            [
                {"commit": "c3", "base": ""},
                {"commit": "c4", "base": "c2"},
                {"commit": "c4", "base": "c2"},
                {"commit": "c1", "base": ""},
                {"commit": "c2", "base": ""},
            ],
        )

    def test_segments_keep_the_commit_in_focus(self):
        """'from' starts at the commit in focus, 'one' shows it, 'last' compares the last-seen commit with the newest
        (how many commits that is, the server says - never the list's positions)."""
        modes = self.run_rules(
            "["
            "rangeMode(ROWS,{mode:'one',start:'c2',end:'c2'},'from',null),"
            "rangeMode(ROWS,{mode:'from',start:'c2',end:'c3'},'one',null),"
            "rangeMode(ROWS,{mode:'one',start:'c1',end:'c1'},'last',{id:'c2'})"
            "]"
        )
        self.assertEqual(
            modes,
            [
                {"mode": "from", "start": "c2", "end": "c4", "endSet": False},
                {"mode": "one", "start": "c2", "end": "c2", "endSet": False},
                {"mode": "last", "start": "c4", "end": "c4", "endSet": False},
            ],
        )

    def test_the_rows_painted_are_the_servers(self):
        """A range paints the commits the server's answer names (commit_ids), nothing while it is unknown; one commit
        paints itself."""
        painted = self.run_rules(
            "[paintedIds({commit:'c4',base:'c1'},['c4','x9','c3']),paintedIds({commit:'c4',base:'c1'},null),"
            "paintedIds({commit:'c3',base:''},null)]"
        )
        self.assertEqual(painted, [["c4", "x9", "c3"], [], ["c3"]])


class SideRows(unittest.TestCase):
    """A merged line's commits are drawn as a side line under their merge."""

    def test_rows_between_a_merge_and_its_first_parent_are_its_side_line(self):
        """Pages come in ancestry order, so the rows between a merge and its first parent are the merged line; a merge
        whose first parent is not loaded marks nothing."""
        rows = [
            {"id": "m", "parents": ["t", "s2"]},
            {"id": "s2", "parents": ["s1"]},
            {"id": "s1", "parents": ["t"]},
            {"id": "t", "parents": ["r"]},
            {"id": "m2", "parents": ["gone", "x"]},
            {"id": "x", "parents": ["r"]},
        ]
        out = run_node(extract_js_fn("sideRows") + "console.log(JSON.stringify([...sideRows(%s)]));" % json.dumps(rows))
        if out is None:
            self.skipTest("node not available")
        self.assertEqual(json.loads(out), ["s2", "s1"])


class PickerBase(BrowserBase):
    """The picker's helpers in Chromium: opening the changes view, its segments, the last-seen record; the comparison
    build faked."""

    def fake_builds(self) -> None:
        """Answer every comparison build with fake_compile for this test."""
        patcher = mock.patch.object(revision_execution, "revision_compile", side_effect=fake_compile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args: str) -> str:
        """Run Git in the manuscript folder; its stdout, stripped."""
        return subprocess.check_output(["git", *args], cwd=self.main.parent, text=True).strip()

    def seen_script(self, commit: str) -> str:
        """An init script that records commit as last seen for the document (the viewer's localStorage form)."""
        record = {ps.APP.docs[0].key: {"id": commit, "at": "2026-10-05 14:10"}}
        return "localStorage.setItem('limnRevSeen',%s)" % json.dumps(json.dumps(record))

    def changes(self, page, phone=False):
        """Open the changes view (the nav bar's tab, or the phone's navigation sheet) and wait until this visit has read
        the commit list and shown a commit."""
        if phone:
            page.click("#btn-pos")
            page.locator("#nav-sheet [data-mode=revisions]").click()
        else:
            page.click("#view-revisions")
        page.wait_for_function("REV.rowsDoc===DOC&&REV.commit!==''", timeout=15000)
        page.wait_for_selector("#revision-commits .rc-row", timeout=15000)
        return page

    def segment(self, page, mode: str):
        """The quick-range segment for mode."""
        return page.locator("#revision-range [data-range=%s]" % mode)


class RangePicker(PickerBase):
    """The picker against a real eight-commit history (c0 oldest .. c7 newest)."""

    def setUp(self):
        """Eight commits, each adding a line 'Change n' to main.tex, by two authors; the comparison build faked."""
        super().setUp()
        self.commits = []
        for n in range(8):
            with self.main.open("a", encoding="utf-8") as stream:
                stream.write("%% Change %d\n" % n)
            if n == 0:
                self.git("init", "-q")
            self.git("add", "main.tex")
            self.git(
                "-c",
                "user.name=%s" % ("Alice Kim" if n % 2 else "Bob Park"),
                "-c",
                "user.email=a@example.com",
                "commit",
                "-qm",
                "Change %d" % n,
            )
            self.commits.append(self.git("rev-parse", "HEAD"))
        self.fake_builds()

    def test_without_a_record_the_newest_commit_opens_alone(self):
        """No last-seen record: [마지막으로 본 뒤] is hidden, [이 커밋만] is on and the newest commit opens alone (its
        comparison PDF first, as before); the list shows every loaded commit with author and short hash."""
        page = self.changes(self.open(0))
        self.assertFalse(self.segment(page, "last").is_visible())
        self.assertEqual(self.segment(page, "one").get_attribute("aria-checked"), "true")
        self.assertEqual(page.evaluate("[REV.commit,REV.base,REV.format]"), [self.commits[-1], "", "pdf"])
        self.assertEqual(page.locator("#revision-commits .rc-row").count(), 8)
        top = page.locator("#revision-commits .rc-row").first.inner_text()
        self.assertIn("Change 7", top)
        self.assertIn("Alice Kim", top)
        self.assertIn(self.commits[-1][:7], top)

    def test_since_last_seen_opens_the_range_in_the_source_diff(self):
        """With c4 last seen, the view opens on [마지막으로 본 뒤 3]: the source diff from c4 to the newest (base=c4 on
        the request), the three newer rows marked new and in the range, a line saying where reading stopped."""
        urls = []
        page = self.open(0, init=self.seen_script(self.commits[4]))
        page.on("request", lambda r: urls.append(r.url))
        self.changes(page)
        page.wait_for_function("REV.seenState==='ok'", timeout=15000)
        last = self.segment(page, "last")
        self.assertEqual(last.get_attribute("aria-checked"), "true")
        self.assertIn("3", last.inner_text())
        page.wait_for_function("REV.sourceCommit&&REV.format==='source'", timeout=15000)
        self.assertEqual(page.evaluate("[REV.commit,REV.base]"), [self.commits[-1], self.commits[4]])
        diff = page.inner_text("#revision-diff")
        self.assertIn("Change 7", diff)
        self.assertIn("Change 5", diff)
        self.assertNotIn("+% Change 4", diff)
        self.assertIn("커밋 3개", page.inner_text("#revision-status"))
        self.assertEqual(page.locator("#revision-commits .rc-row.new").count(), 3)
        self.assertEqual(page.locator("#revision-commits .rc-row.in").count(), 3)
        self.assertEqual(page.locator("#revision-commits .rc-seen").count(), 1)
        self.assertTrue(any("base=" + self.commits[4] in u for u in urls if "/api/revision-diff" in u), urls)
        self.assertFalse(any("/api/revision-build" in u for u in urls), "a range builds its PDF only on [변경 PDF]")

    def test_a_row_press_ranges_from_it_to_now_and_this_commit_only_narrows(self):
        """From [마지막으로 본 뒤], pressing c2 compares c2's parent to the newest; pressing c5 then ends the range at c5;
        [이 커밋만] shows c2 alone; [변경 PDF] then builds that commit's comparison."""
        page = self.changes(self.open(0, init=self.seen_script(self.commits[4])))
        page.locator("#revision-commits .rc-row[data-commit='%s']" % self.commits[2]).click()
        page.wait_for_function("REV.base===%s" % json.dumps(self.commits[1]), timeout=15000)
        self.assertEqual(page.evaluate("REV.commit"), self.commits[-1])
        self.assertEqual(self.segment(page, "from").get_attribute("aria-checked"), "true")
        self.assertEqual(page.locator("#revision-commits .rc-row.in").count(), 6)
        page.locator("#revision-commits .rc-row[data-commit='%s']" % self.commits[5]).click()
        page.wait_for_function("REV.commit===%s" % json.dumps(self.commits[5]), timeout=15000)
        self.assertEqual(page.evaluate("REV.base"), self.commits[1])
        self.assertEqual(page.locator("#revision-commits .rc-row.in").count(), 4)
        self.segment(page, "one").click()
        page.wait_for_function("REV.commit===%s&&REV.base===''" % json.dumps(self.commits[2]), timeout=15000)
        page.click("#revision-pdf-tab")
        page.wait_for_selector('.revision-page[data-state="ready"] canvas', timeout=15000)

    def test_last_seen_is_kept_for_the_document_in_this_browser(self):
        """Leaving the changes view records the newest commit; back in it, [마지막으로 본 뒤 0] cannot be pressed; after
        a new commit it reads 1 and opens that commit's range."""
        page = self.changes(self.open(0))
        page.click("#view-manuscript")
        stored = json.loads(page.evaluate("localStorage.getItem('limnRevSeen')"))
        self.assertEqual(stored[ps.APP.docs[0].key]["id"], self.commits[-1])
        self.changes(page)
        last = self.segment(page, "last")
        self.assertTrue(last.is_visible())
        self.assertTrue(last.is_disabled())
        self.assertIn("0", last.inner_text())
        page.click("#view-manuscript")
        with self.main.open("a", encoding="utf-8") as stream:
            stream.write("% Change 8\n")
        self.git("-c", "user.name=Alice Kim", "-c", "user.email=a@example.com", "commit", "-qam", "Change 8")
        newest = self.git("rev-parse", "HEAD")
        self.changes(page)
        page.wait_for_function("REV.commit===%s&&REV.seenState==='ok'" % json.dumps(newest), timeout=15000)
        self.assertEqual(self.segment(page, "last").get_attribute("aria-checked"), "true")
        self.assertIn("1", self.segment(page, "last").inner_text())
        self.assertEqual(page.evaluate("REV.base"), self.commits[-1])

    def stored_seen(self, page) -> str:
        """The last-seen commit this browser holds for the document."""
        return json.loads(page.evaluate("localStorage.getItem('limnRevSeen')"))[ps.APP.docs[0].key]["id"]

    def commit_more(self, n: int) -> None:
        """n more commits, each adding a line."""
        for k in range(n):
            with self.main.open("a", encoding="utf-8") as stream:
                stream.write("%% More %d\n" % k)
            self.git("-c", "user.name=Alice Kim", "-c", "user.email=a@example.com", "commit", "-qam", "More %d" % k)
            self.commits.append(self.git("rev-parse", "HEAD"))

    def test_a_record_beyond_the_first_page_is_counted_by_the_server(self):
        """34 commits after the last-seen one (more than a page of 30): [마지막으로 본 뒤 34] opens that range, every
        loaded row is new, and leaving records the newest commit."""
        seen = self.commits[-1]
        self.commit_more(34)
        page = self.changes(self.open(0, init=self.seen_script(seen)))
        page.wait_for_function("REV.seenState==='ok'", timeout=15000)
        self.assertIn("34", self.segment(page, "last").inner_text())
        self.assertEqual(page.evaluate("[REV.base,REV.commit]"), [seen, self.commits[-1]])
        self.assertEqual(page.locator("#revision-commits .rc-row.new").count(), 30)
        page.click("#view-manuscript")
        self.assertEqual(self.stored_seen(page), self.commits[-1])

    def test_a_record_the_history_no_longer_has_says_so(self):
        """A last-seen commit the server cannot find (rewritten history): the segment says so and cannot be pressed,
        the newest commit opens alone, and leaving then records the newest."""
        page = self.changes(self.open(0, init=self.seen_script("0" * 40)))
        page.wait_for_function("REV.seenState==='gone'&&REV.base===''", timeout=15000)
        last = self.segment(page, "last")
        self.assertTrue(last.is_visible())
        self.assertTrue(last.is_disabled())
        self.assertIn("기록한 커밋을 찾을 수 없음", last.inner_text())
        self.assertEqual(page.evaluate("REV.commit"), self.commits[-1])
        page.click("#view-manuscript")
        self.assertEqual(self.stored_seen(page), self.commits[-1])

    def test_a_record_older_than_the_window_says_so_and_is_kept(self):
        """With a window of 5, the last-seen c1 is this document's commit but older than the window: the segment says
        so (not "not found") and cannot be pressed, and leaving keeps the record."""
        with mock.patch.object(revisions, "REVISION_HISTORY_MAX", 5):
            page = self.changes(self.open(0, init=self.seen_script(self.commits[1])))
            page.wait_for_function("REV.seenState==='old'", timeout=15000)
            last = self.segment(page, "last")
            self.assertTrue(last.is_disabled())
            self.assertIn("기록한 커밋이 최근 500개보다 오래됨", last.inner_text())
            page.click("#view-manuscript")
            self.assertEqual(self.stored_seen(page), self.commits[1])

    def test_an_unresolved_record_is_never_overwritten(self):
        """When the server cannot answer for the last-seen commit (a failed request), leaving keeps the record."""
        page = self.open(0, init=self.seen_script(self.commits[4]))

        def fail_ranges(route):
            """Answer a range request with 503; let the rest through."""
            if "base=" in route.request.url:
                return route.fulfill(
                    status=503, content_type="application/json", body='{"error":"x","reason":"diff_unreadable"}'
                )
            return route.fallback()

        page.route("**/api/revision-diff*", fail_ranges)
        self.changes(page)
        page.wait_for_function("REV.seenState==='error'", timeout=15000)
        page.click("#view-manuscript")
        self.assertEqual(self.stored_seen(page), self.commits[4])

    def test_a_new_build_never_builds_a_range_pdf(self):
        """A range's comparison PDF is built only on [변경 PDF]: when the document is read again while it is shown (a
        new build), the range comes back in its source diff and no build is started."""
        posts = []
        page = self.open(0, init=self.seen_script(self.commits[4]))
        page.on(
            "request", lambda r: posts.append(r.url) if r.method == "POST" and "/api/revision-build" in r.url else None
        )
        self.changes(page)
        page.wait_for_function("REV.seenState==='ok'", timeout=15000)
        page.click("#revision-pdf-tab")
        page.wait_for_selector('.revision-page[data-state="ready"] canvas', timeout=15000)
        self.assertEqual(len(posts), 1)
        page.evaluate("loadRevisions()")
        page.wait_for_function("REV.rowsDoc===DOC&&REV.format==='source'&&REV.sourceCommit!==''", timeout=15000)
        page.wait_for_timeout(500)
        self.assertEqual(len(posts), 1, posts)

    def test_desktop_lays_the_list_beside_the_changes(self):
        """At 1440x900 the list is a 304px column left of the changes, rows at least 48px, the quick range in the
        header, and nothing overflows the view sideways."""
        page = self.changes(self.open(0, **DESKTOP))
        aside = page.locator("#revision-commits").bounding_box()
        pane = page.locator("#revision-pane").bounding_box()
        self.assertAlmostEqual(aside["width"], 304, delta=1)
        self.assertLessEqual(aside["x"] + aside["width"], pane["x"] + 1)
        self.assertGreater(pane["width"], 480)
        heights = page.eval_on_selector_all(
            "#revision-commits .rc-row", "rs=>rs.map(r=>r.getBoundingClientRect().height)"
        )
        self.assertGreaterEqual(min(heights), 48)
        head = page.locator("#revision-head").bounding_box()
        rng = page.locator("#revision-range").bounding_box()
        self.assertGreaterEqual(rng["y"], head["y"])
        self.assertLessEqual(rng["y"] + rng["height"], head["y"] + head["height"] + 1)
        self.assertTrue(page.evaluate("(v=>v.scrollWidth<=v.clientWidth)(document.getElementById('revision-view'))"))

    def test_phone_shows_five_rows_above_the_changes_and_more_on_request(self):
        """On a phone the list sits above the changes with five 56px rows and [더 보기]; pressing it shows the rest.
        Each quick-range segment answers a 44px touch and the control fits the width."""
        page = self.changes(self.open(0, **PHONE), phone=True)
        rows = page.locator("#revision-commits .rc-row")
        self.assertEqual(sum(rows.nth(i).is_visible() for i in range(rows.count())), 5)
        heights = page.eval_on_selector_all(
            "#revision-commits .rc-row", "rs=>rs.filter(r=>r.offsetParent).map(r=>r.getBoundingClientRect().height)"
        )
        self.assertGreaterEqual(min(heights), 56)
        aside = page.locator("#revision-commits").bounding_box()
        pane = page.locator("#revision-pane").bounding_box()
        self.assertLessEqual(aside["y"] + aside["height"], pane["y"] + 1)
        hits = page.eval_on_selector_all(
            "#revision-range button",
            "bs=>bs.filter(b=>b.offsetParent).map(b=>parseFloat(getComputedStyle(b,'::after').height))",
        )
        self.assertTrue(hits and min(hits) >= 44, hits)
        rng = page.locator("#revision-range").bounding_box()
        self.assertLessEqual(rng["x"] + rng["width"], 411)
        page.click("#revision-more")
        self.assertEqual(sum(rows.nth(i).is_visible() for i in range(rows.count())), 8)


class MergedPicker(PickerBase):
    """The picker over a history with a merged side line dated before all of trunk: what is painted is what the
    server compares, never the rows' positions."""

    def setUp(self):
        """root, a side line S1..S3 dated in January, trunk B1..B6, the --no-ff merge M of the side line, then B7."""
        super().setUp()
        self.fake_builds()
        self.sha: dict[str, str] = {}
        self.dated("2026-09-01T08:00:00+09:00", "init", "-q", "-b", "main")
        self.step("root", "2026-09-01T08:00:00+09:00")
        self.dated("2026-09-01T08:00:00+09:00", "checkout", "-q", "-b", "side")
        for n in (1, 2, 3):
            self.step("S%d" % n, "2026-01-0%dT08:00:00+09:00" % n)
        self.dated("2026-09-01T08:00:00+09:00", "checkout", "-q", "main")
        for n in range(1, 7):
            self.step("B%d" % n, "2026-09-%02dT08:00:00+09:00" % (n + 1))
        self.dated("2026-09-20T08:00:00+09:00", "merge", "-q", "--no-ff", "-m", "M", "side")
        self.sha["M"] = self.dated("2026-09-20T08:00:00+09:00", "rev-parse", "HEAD")
        self.step("B7", "2026-09-21T08:00:00+09:00")
        self.commits = [self.sha["B7"]]

    def dated(self, when: str, *args: str) -> str:
        """Run Git at the fixed time when; its stdout, stripped."""
        env = dict(
            os.environ,
            GIT_AUTHOR_DATE=when,
            GIT_COMMITTER_DATE=when,
            GIT_AUTHOR_NAME="Alice Kim",
            GIT_COMMITTER_NAME="Alice Kim",
            GIT_AUTHOR_EMAIL="a@example.com",
            GIT_COMMITTER_EMAIL="a@example.com",
        )
        return subprocess.check_output(["git", *args], cwd=self.main.parent, text=True, env=env).strip()

    def step(self, name: str, when: str) -> None:
        """A commit named name at when, writing its own file (so branches merge cleanly); its SHA under name."""
        (self.main.parent / ("%s.tex" % name)).write_text("%s\n" % name, encoding="utf-8")
        self.dated(when, "add", "-A")
        self.dated(when, "commit", "-qm", name)
        self.sha[name] = self.dated(when, "rev-parse", "HEAD")

    def painted(self, page) -> set:
        """The commits the list paints as in the range."""
        return set(page.eval_on_selector_all("#revision-commits .rc-row.in", "rs=>rs.map(r=>r.dataset.commit)"))

    def compared(self, base: str, head: str) -> set:
        """What the server compares for base..head: the manuscript commits git lists in that span."""
        return set(self.dated("2026-09-21T08:00:00+09:00", "rev-list", "%s..%s" % (base, head), "--", ".").split())

    def test_a_side_row_paints_every_commit_its_range_compares(self):
        """[이 커밋부터] on S1 compares S1's parent (root) with the newest: all of trunk and the side line are painted,
        though S1 sits mid-list."""
        page = self.changes(self.open(0))
        self.segment(page, "from").click()
        page.locator("#revision-commits .rc-row[data-commit='%s']" % self.sha["S1"]).click()
        page.wait_for_function("REV.base===%s&&REV.rangeIds" % json.dumps(self.sha["root"]), timeout=15000)
        self.assertEqual(self.painted(page), self.compared(self.sha["root"], self.sha["B7"]))

    def test_the_first_commit_paints_only_itself(self):
        """[이 커밋부터] on the root commit opens that commit alone, and only it is painted."""
        page = self.changes(self.open(0))
        self.segment(page, "from").click()
        page.locator("#revision-commits .rc-row[data-commit='%s']" % self.sha["root"]).click()
        page.wait_for_function("REV.commit===%s&&REV.base===''" % json.dumps(self.sha["root"]), timeout=15000)
        self.assertEqual(self.painted(page), {self.sha["root"]})

    def test_since_last_seen_counts_what_a_merge_brought(self):
        """Last seen at B6, then the side line was merged and B7 pushed: N is every commit the range compares (the
        merged line, the merge and B7), and those are the rows painted and marked new."""
        page = self.changes(self.open(0, init=self.seen_script(self.sha["B6"])))
        page.wait_for_function("REV.seenState==='ok'&&REV.rangeIds", timeout=15000)
        want = self.compared(self.sha["B6"], self.sha["B7"])
        self.assertIn(str(len(want)), self.segment(page, "last").inner_text())
        self.assertEqual(self.painted(page), want)
        new = page.eval_on_selector_all("#revision-commits .rc-row.new", "rs=>rs.map(r=>r.dataset.commit)")
        self.assertEqual(set(new), want)


class OldSidePin(PickerBase):
    """Re-review of #188: a side line dated before trunk and merged after it fills the first 12 rows; a pin closed on
    the older trunk commit B5 by hash must still open on B5, as the server resolves it."""

    def setUp(self):
        """root; side S1..S12 (January, own files); trunk B1..B12 (September, line n+2 of main.tex); a pin on B5's
        line closed by the agent with B5's hash; then the --no-ff merge of the side line."""
        super().setUp()
        self.fake_builds()
        self.sha: dict[str, str] = {}
        self.dated("2026-09-01T08:00:00+09:00", "init", "-q", "-b", "main")
        self.save("root", "2026-09-01T08:00:00+09:00")
        self.dated("2026-09-01T08:00:00+09:00", "checkout", "-q", "-b", "side")
        for n in range(1, 13):
            (self.main.parent / ("s%d.tex" % n)).write_text("Side %d.\n" % n, encoding="utf-8")
            self.save("S%d" % n, "2026-01-%02dT08:00:00+09:00" % n)
        self.dated("2026-09-01T08:00:00+09:00", "checkout", "-q", "main")
        for n in range(1, 13):
            lines = self.main.read_text(encoding="utf-8").splitlines(keepends=True)
            lines[n + 1] = "Trunk line %d.\n" % n
            self.main.write_text("".join(lines), encoding="utf-8")
            self.save("B%d" % n, "2026-09-%02dT08:00:00+09:00" % (n + 1))
        pin = add_pin({"file": str(self.main), "lo": 7, "hi": 7, "page": 1, "note": "five"}, dict(LOCAL_ACTOR))
        self.pin = pin.record["id"]
        close = {"ref": "fixed in %s" % self.sha["B5"][:8], "changes": [{"file": "main.tex", "lo": 7, "hi": 7}]}
        status, _, body = self.talk(jreq("POST", "/api/pins/%d/close" % self.pin, close))
        self.assertEqual(status, 200, body)
        self.dated("2026-09-20T08:00:00+09:00", "merge", "-q", "--no-ff", "-m", "merge side", "side")

    def dated(self, when: str, *args: str) -> str:
        """Run Git at the fixed time when; its stdout, stripped."""
        env = dict(
            os.environ,
            GIT_AUTHOR_DATE=when,
            GIT_COMMITTER_DATE=when,
            GIT_AUTHOR_NAME="Alice Kim",
            GIT_COMMITTER_NAME="Alice Kim",
            GIT_AUTHOR_EMAIL="a@example.com",
            GIT_COMMITTER_EMAIL="a@example.com",
        )
        return subprocess.check_output(["git", *args], cwd=self.main.parent, text=True, env=env).strip()

    def save(self, name: str, when: str) -> None:
        """Commit everything at when as name; its SHA under name."""
        self.dated(when, "add", "-A")
        self.dated(when, "commit", "-qm", name)
        self.sha[name] = self.dated(when, "rev-parse", "HEAD")

    def test_a_pin_closed_by_hash_opens_on_that_commit(self):
        """[변경 보기] of the pin opens B5 (via its hash), not the newest commit that touched the line."""
        page = self.open(0)
        page.evaluate("showChange(%d)" % self.pin)
        page.wait_for_function("REV.target&&REV.target.commit", timeout=15000)
        self.assertEqual(page.evaluate("[REV.target.commit,REV.target.via]"), [self.sha["B5"], "sha"])
