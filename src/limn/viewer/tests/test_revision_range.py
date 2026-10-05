"""The changes view's commit picker (issue #188, variant C, docs/handbook/viewer.md §변경 보기): the quick range
[마지막으로 본 뒤 N | 이 커밋부터 | 이 커밋만], the commit list that stays on screen, a row press, the last-seen commit kept
in this browser, and the desktop and phone layouts - against real Git history, with the comparison build faked.

The pure rules (rangePress, rangeRequest, rangeMode, seenCount) run under node from the served source; the rest drives
Chromium.

Run: LIMN_TEST_REQUIRE_BROWSER=1 uv run pytest -q src/limn/viewer/tests/test_revision_range.py
"""

import json
import subprocess
import unittest
from unittest import mock

from limn.revisions import core as revisions, execution as revision_execution

from helpers import extract_js_fn, ps, run_node
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
        js = "".join(extract_js_fn(n) + "\n" for n in ("rangePress", "rangeRequest", "rangeMode", "seenCount"))
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

    def test_segments_and_the_count_since_last_seen(self):
        """seenCount is the rows newer than the last-seen commit (-1 when it is not loaded); the segments keep the
        commit in focus: 'from' starts at it, 'one' shows it, 'last' starts after the last-seen commit."""
        self.assertEqual(
            self.run_rules("[seenCount(ROWS,{id:'c2'}),seenCount(ROWS,{id:'c4'}),seenCount(ROWS,null)]"), [2, 0, -1]
        )
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
                {"mode": "last", "start": "c3", "end": "c4", "endSet": False},
            ],
        )


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


class RangePicker(BrowserBase):
    """The picker in Chromium against a real eight-commit history (c0 oldest .. c7 newest)."""

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
        page.wait_for_function("REV.commit===%s" % json.dumps(newest), timeout=15000)
        self.assertEqual(self.segment(page, "last").get_attribute("aria-checked"), "true")
        self.assertIn("1", self.segment(page, "last").inner_text())
        self.assertEqual(page.evaluate("REV.base"), self.commits[-1])

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
