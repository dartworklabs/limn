"""A long outline and a figure document's page list (docs/handbook/viewer.md §모바일 레이아웃, §쪽 목록).

The viewer reads the first OUTLINE_MAX_ENTRIES entries of a PDF's outline, down to five levels, and says at the end of the
outline - and of its filter's results - how many entries it left unread; the outline panel keeps the current section in view
unless the person has it in hand; a figure document's page list shows each page's
title. The pure decisions run under node, the rest in the real viewer against helpers_figure.viewer_docs' three documents
(a LaTeX manuscript, a figure document and a view-only PDF), the long outlines read from real PDF bytes (helpers_outline)
or, where only the count matters, from a stand-in for PDF.js's document.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_outline_cap.py
"""

import json
import unittest
from urllib.parse import parse_qs, urlparse

import helpers_figure
from helpers import extract_js_fn, ps, run_node
from helpers_access import ALICE
from helpers_browser import BrowserBase, nothing_follows, settle
from helpers_notices import node_or_skip
from helpers_outline import chain_tree, grouped_tree, outline_pdf

DESKTOP = {"viewport": {"width": 1400, "height": 850}}
FOLD = {"viewport": {"width": 841, "height": 673}, "is_mobile": True, "has_touch": True}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1}}))}catch(e){}"
CAP = 2000  # OUTLINE_MAX_ENTRIES
LEVELS = 5  # OUTLINE_MAX_DEPTH + 1


class OutlineLogic(unittest.TestCase):
    """The pure parts: counting what a cut leaves unread, and the title each page of a figure document shows."""

    def run_js(self, names, expr):
        """Evaluate expr (JSON) with the named shipped functions defined."""
        node_or_skip(self)
        js = "\n".join([extract_js_fn(n) for n in names] + ["console.log(JSON.stringify(%s));" % expr])
        return json.loads(run_node(js))

    def test_the_unread_entries_are_the_ones_that_name_a_place(self):
        """outlineCount(item): the item and everything under it that has a destination - a heading with none (a group
        label) is not an entry the viewer could have shown - and an outline nested far deeper than the call stack is
        counted without overflowing it."""
        got = self.run_js(
            ["outlineCount"],
            "[outlineCount({dest:[1],items:[{dest:[1],items:[]},{dest:null,items:[{dest:'x',items:[]}]}]}),"
            "outlineCount({items:[]}),outlineCount({dest:[1]}),"
            "(()=>{let n={dest:[1],items:[]}; for(let i=0;i<200000;i++)n={dest:[1],items:[n]}; return outlineCount(n);})()]",
        )
        self.assertEqual(got, [3, 0, 1, 200001])

    def test_a_page_shows_its_meta_title_else_the_outline_entry_else_nothing(self):
        """pageTitles(pages, entries, n, byOutline): the meta's title wins (trimmed); a page without one shows the entry
        of the outline that points at it - the deepest, of equally deep ones the first listed, with its number - when
        byOutline; a page nothing names, or any page when not byOutline, is ''. A blank or non-text title is no title."""
        got = self.run_js(
            ["pageTitles"],
            "(()=>{const E=[{title:'Group',page:2,depth:0,number:''},{title:'Fig A',page:2,depth:1,number:''},"
            "{title:'Fig B',page:2,depth:1,number:''},{title:'Panel',page:3,depth:2,number:'3.1'},{title:'Late',page:9,depth:0}];"
            "const P=[{title:'  From map  '},{},{title:''},{title:7},{title:'   '}];"
            "return [pageTitles(P,E,5,true),pageTitles(P,E,5,false),pageTitles(null,E,3,true),pageTitles(P,[],2,true)];})()",
        )
        self.assertEqual(
            got,
            [
                ["From map", "Fig A", "3.1 Panel", "", ""],
                ["From map", "", "", "", ""],
                ["", "Fig A", "3.1 Panel"],
                ["From map", ""],
            ],
        )

    def test_a_filter_names_the_group_of_an_entry_another_group_also_has(self):
        """outlineGrouped(entries): the entries under a group whose number and title another entry has under another group -
        a figure under its status and under the manuscript figure that holds it - and no others: a name said once, twice under
        one group, or at the top has no group to say; a different number or a different spelling of a title (case, width,
        spaces) is judged by what it is. outlineGroupName: the group's number and title."""
        got = self.run_js(
            ["outlineGrouped", "outlineGroupName"],
            "(()=>{OUTLINE_GROUPED={for:null,set:new Set()};"
            "const E=[{title:'채택',up:-1},{title:'PL64 · 달력',up:0},{title:'PL65',up:0},{title:'본문 그림',up:-1},"
            "{title:'pl64  · 달력',up:3},{title:'PL65',up:0},{title:'PL66',up:3},{title:'PL66',up:3},"
            "{title:'PL64 · 달력',up:-1},{title:'Results',number:'3.1',up:3},{title:'Results',number:'4.2',up:0}];"
            "const a=outlineGrouped(E),again=outlineGrouped(E);"
            "return {set:[...a],memo:a===again,fresh:outlineGrouped(E.slice())!==a,"
            "name:[outlineGroupName({number:'2',title:'Methods'}),outlineGroupName({title:'채택'}),outlineGroupName(undefined)],"
            "bare:[...outlineGrouped([{title:'A'},{title:'A'}])]};})()",
        )
        # 1 and 4 are the same figure under two groups; 8 is the same name again at the top (nothing to say there); 5 is under
        # the same group as 2's name 'PL65'; 6 and 7 are one name twice under one group.
        self.assertEqual(got["set"], [1, 4])
        self.assertTrue(got["memo"])
        self.assertTrue(got["fresh"])
        self.assertEqual(got["name"], ["2 Methods", "채택", ""])
        self.assertEqual(got["bare"], [])

    def test_a_row_comes_in_from_the_nearest_side_with_room_beyond_it(self):
        """outlineRevealTop(st, h, sh, top, bottom, m, head): a row m px clear of both edges moves nothing; one that has
        entered that margin, or left the view, comes to the margin's edge on its nearest side - on a short view half of what is
        left, by the top when it is taller than the view - and stops where the list ends. Where only the head would stay over
        it the list goes to the very top, and a list that cannot get any nearer has nowhere to go. The view starts `cover` px
        down (the filter's band): the margin counts from there, and the room left on a short view is what is left under it."""
        got = self.run_js(
            ["outlineRevealTop"],
            """[outlineRevealTop(0,800,5000,100,124,48,100),outlineRevealTop(0,800,5000,728,752,48,100),
            outlineRevealTop(1000,800,5000,1048,1072,48,100),
            outlineRevealTop(0,800,5000,729,753,48,100),outlineRevealTop(1000,800,5000,1047,1071,48,100),
            outlineRevealTop(0,800,5000,776,800,48,100),outlineRevealTop(2000,800,5000,2000,2024,48,100),
            outlineRevealTop(0,800,5000,790,814,48,100),outlineRevealTop(0,800,5000,3000,3024,48,100),
            outlineRevealTop(2000,800,5000,1900,1924,48,100),outlineRevealTop(2000,800,5000,1990,2014,48,100),
            outlineRevealTop(4000,800,4900,4880,4900,48,100),outlineRevealTop(0,100,5000,300,380,48,100),
            outlineRevealTop(0,100,5000,300,500,48,100),outlineRevealTop(1000,100,5000,300,500,48,100),
            outlineRevealTop(1000,800,5000,130,154,48,100),outlineRevealTop(1000,800,5000,100,124,48,100),
            outlineRevealTop(1000,800,5000,300,324,48,100),
            outlineRevealTop(4100,800,4900,4880,4950,48,100),
            outlineRevealTop(1000,800,5000,1100,1124,48,100,52),outlineRevealTop(1000,800,5000,1099,1123,48,100,52),
            outlineRevealTop(1000,800,5000,900,924,48,100,52),outlineRevealTop(1000,800,5000,1776,1800,48,100,52),
            outlineRevealTop(1000,152,5000,1000,1024,48,100,52),outlineRevealTop(1000,100,5000,1500,1600,48,100,52)]""",
        )
        self.assertEqual(
            got,
            [None, None, None, 1, 999, 48, 1952, 62, 2272, 1852, 1942, 4100, 290, 300, 300, 0, 0, 252, None]
            + [None, 999, 800, 1048, 910, 1448],
        )

    def test_going_up_the_rows_above_and_the_sections_head_show_where_they_fit(self):
        """outlineRevealTop(..., cover, near, group): over a row the list keeps what starts at near (the two rows above it)
        when that is more than the margin and fits with the row and the margin under it - so a row 48px under the band, clear
        before, now moves. Coming up, the list goes on to group (its section's head and two rows above that) where that fits
        too, and to the very top where only the panel's head would be left. A row clear of near moves nothing even when its
        head is out of sight; going down, on a view too short for near and with fewer rows than the margin above, nothing
        changes."""
        got = self.run_js(
            ["outlineRevealTop"],
            """[outlineRevealTop(1000,800,5000,1100,1124,48,100,52),outlineRevealTop(1000,800,5000,1100,1124,48,100,52,1044),
            outlineRevealTop(1000,800,5000,1110,1134,48,100,52,1054),
            outlineRevealTop(1000,800,5000,1100,1124,48,100,52,1044,800),outlineRevealTop(1000,800,5000,1100,1124,48,100,52,1044,300),
            outlineRevealTop(1000,800,5000,500,524,48,100,52,444,200),outlineRevealTop(1000,800,5000,210,234,48,100,52,154),
            outlineRevealTop(1000,800,5000,210,234,48,100,52,154,100),
            outlineRevealTop(1000,800,5000,1300,1324,48,100,52,1244,800),outlineRevealTop(1000,800,5000,1790,1814,48,100,52,1734,800),
            outlineRevealTop(1000,152,5000,1000,1024,48,100,52,944,600),outlineRevealTop(1000,800,5000,1060,1084,48,100,52,1040,1040)]""",
        )
        self.assertEqual(got, [None, 992, None, 748, 992, 148, 102, 0, None, 1062, 910, 960])

    REFERENCE = """function referenceIndexAt(entries,page,frac){
      const at=e=>e.frac||0,deep=e=>e.depth||0,above=e=>e.page<page||(e.page===page&&at(e)<=frac+1e-6);
      const x=e=>typeof e.x==='number'?e.x:null,sameX=(a,b)=>x(a)===null||x(b)===null?x(a)===x(b):Math.abs(x(a)-x(b))<=1e-3;
      const same=(a,b)=>Math.abs(at(a)-at(b))<=1e-6&&sameX(a,b);
      let top=0; for(const e of entries)if(above(e)&&e.page>top)top=e.page;
      if(!top){let first=-1; entries.forEach((e,i)=>{if(first<0||e.page<entries[first].page)first=i;}); return first;}
      const on=[]; entries.forEach((e,i)=>{if(e.page===top&&above(e))on.push(i);});
      const outranked=i=>on.some(j=>{const a=entries[i],b=entries[j];
        return j!==i&&same(a,b)&&(deep(b)>deep(a)||(deep(b)===deep(a)&&j<i));});
      let sel=-1; for(const i of on)if(!outranked(i))sel=i;
      return sel;}"""

    def test_the_lookup_gives_the_answer_of_the_pairwise_rule(self):
        """outlineIndexAt against the rule it replaced (every entry on the page compared with every other, as 0.4.30 wrote it):
        the same entry for 4000 random outlines whose spots collide exactly, within 1e-6 of one another, and not at all, with
        left edges that are absent, equal, within 1e-3 and apart, over pages out of order and at every depth."""
        got = self.run_js(
            ["outlineIndexAt"],
            "(()=>{"
            + self.REFERENCE
            + """
            let seed = 12345; const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
            const pick = a => a[Math.floor(rnd() * a.length)];
            const FR = [0, 0.1, 0.1 + 5e-7, 0.1 + 2e-6, 0.3, 0.3 + 9e-7, 0.5, 0.9], XS = [null, null, 10, 10.0005, 10.002, 300];
            let bad = [], n = 0;
            for (let c = 0; c < 4000; c++) {
              const entries = Array.from({length: 1 + Math.floor(rnd() * 40)}, () => ({page: 1 + Math.floor(rnd() * 4), depth: Math.floor(rnd() * 4),
                frac: pick(FR), x: pick(XS)}));
              for (let q = 0; q < 6; q++) {const page = 1 + Math.floor(rnd() * 5), frac = pick([0, 0.05, 0.1, 0.1 + 1e-6, 0.4, 0.95]);
                n++; const a = outlineIndexAt(entries, page, frac), b = referenceIndexAt(entries, page, frac);
                if (a !== b && bad.length < 3) bad.push({entries, page, frac, a, b});}}
            return {n, bad};})()""",
        )
        self.assertEqual(got["bad"], [])
        self.assertEqual(got["n"], 24000)

    def test_the_lookup_gives_the_pairwise_answer_for_crowded_heights_and_edges(self):
        """The same check where the entries of a page crowd onto few heights with many left edges - apart, inside the 1e-3
        window of one another, exactly equal, and absent - so that the windows the lookup walks (by height, by edge) have
        several members, in either list, and the shorter one is not always the same."""
        got = self.run_js(
            ["outlineIndexAt"],
            "(()=>{"
            + self.REFERENCE
            + """
            let seed = 987654; const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
            const pick = a => a[Math.floor(rnd() * a.length)];
            const FR = [0.2, 0.2 + 4e-7, 0.2 + 9e-7, 0.2 + 1.5e-6, 0.6], XS = [null, 40, 40.0004, 40.0009, 40.0016, 41, 42.5, 200, 200.0006];
            let bad = [], n = 0, deepest = 0;
            for (let c = 0; c < 3000; c++) {
              const entries = Array.from({length: 2 + Math.floor(rnd() * 60)}, () => ({page: 1 + Math.floor(rnd() * 2), depth: Math.floor(rnd() * 4),
                frac: pick(FR), x: pick(XS)}));
              for (let q = 0; q < 5; q++) {const page = 1 + Math.floor(rnd() * 3), frac = pick([0.1, 0.2, 0.2 + 1e-6, 0.5, 0.95]);
                n++; const a = outlineIndexAt(entries, page, frac), b = referenceIndexAt(entries, page, frac);
                deepest = Math.max(deepest, a);
                if (a !== b && bad.length < 3) bad.push({entries, page, frac, a, b});}}
            return {n, bad, found: deepest > 0};})()""",
        )
        self.assertEqual(got["bad"], [])
        self.assertEqual(got["n"], 15000)
        self.assertTrue(got["found"])

    def test_the_lookup_stays_fast_where_many_entries_share_a_page(self):
        """The cost of one lookup at 2,000 entries: all distinct spots on one page (the pairwise rule took ~26 ms), all at one
        spot, forty to a spot, fifty pages of forty, and - what the first fix left at ~15 ms - all at one height with left edges
        apart, in clumps within 1e-3 and (the crowded case) every edge within 1e-3 of the next; also all at one edge with the
        heights apart. Each under 5 ms (measured under 1) and equal to the old answer."""
        got = self.run_js(
            ["outlineIndexAt"],
            "(()=>{"
            + self.REFERENCE
            + """
            const mk = f => Array.from({length: 2000}, (_, i) => f(i));
            const cases = {
              distinct: [mk(i => ({page: 1, depth: i % 4, frac: i / 2001, x: null})), 1, 0.99],
              one_spot: [mk(i => ({page: 1, depth: i % 5, frac: 0.3, x: null})), 1, 0.9],
              forty_a_spot: [mk(i => ({page: 1, depth: i % 4, frac: Math.floor(i / 40) / 50, x: i % 3 ? null : 12})), 1, 0.99],
              fifty_pages: [mk(i => ({page: 1 + Math.floor(i / 40), depth: i % 3, frac: (i % 40) / 41, x: null})), 30, 0.7],
              one_height_edges_apart: [mk(i => ({page: 1, depth: i % 4, frac: 0.3, x: i * 0.25})), 1, 0.9],
              one_height_edge_clumps: [mk(i => ({page: 1, depth: i % 4, frac: 0.3, x: 10 + (i % 50) * 0.0004 + Math.floor(i / 50) * 5})), 1, 0.9],
              one_height_edges_crowded: [mk(i => ({page: 1, depth: i % 4, frac: 0.3, x: 10 + i * 1e-7})), 1, 0.9],
              one_edge_heights_apart: [mk(i => ({page: 1, depth: i % 4, frac: i / 2001, x: 72})), 1, 0.99],
            };
            const out = {};
            for (const [k, [E, page, frac]] of Object.entries(cases)) {
              const t0 = performance.now(); let a; for (let r = 0; r < 20; r++) a = outlineIndexAt(E, page, frac);
              out[k] = {ms: (performance.now() - t0) / 20, same: a === referenceIndexAt(E, page, frac)};}
            return out;})()""",
        )
        for name, row in got.items():
            self.assertTrue(row["same"], name)
            self.assertLess(row["ms"], 5, (name, got))


class MetaTitled:
    """A Playwright route whose fulfil puts titles into the pages of the JSON /api/meta answered (the rest passes through)."""

    def __init__(self, route, titles):
        """Wrap route; titles maps a 1-based page number to its title (any value: a test can send a bad one)."""
        self._route, self._titles = route, titles

    def __getattr__(self, name):
        """Everything but fulfill is the route's own (forward() reads its request)."""
        return getattr(self._route, name)

    def fulfill(self, status, headers, body):
        """Fulfil the route with the handler's JSON answer, its pages' own titles (the server's, from a figure map) taken
        out and the given titles put in - so a test decides every title the viewer sees."""
        data = json.loads(body)
        for page in data.get("pages", []):
            page.pop("title", None)
        for page, title in self._titles.items():
            if 0 < page <= len(data.get("pages", [])):
                data["pages"][page - 1]["title"] = title
        self._route.fulfill(status=status, headers=headers, body=json.dumps(data))


# loadOutline() over a stand-in for PDF.js's document whose outline is `tree` ([title, page index, children] rows) on `pages`
# pages; what the viewer then holds: [entries read, entries left unread].
LOAD_TREE = """async ([tree, pages]) => {
  const items = rows => rows.map(([title, page, kids]) => ({title, dest: [page], items: items(kids)}));
  const doc = {numPages: pages, getOutline: async () => items(tree), getDestination: async () => null, getPageIndex: async () => 0};
  VEC.doc = doc; await loadOutline(doc, ++VEC.gen);
  return [OUTLINE_ENTRIES.length, OUTLINE_CUT];
}"""
# What each outline list holds: its rows, and its last line when that is the note on unread entries (null when it is a row).
LISTS = """() => Object.fromEntries(['#outline-items', '#ns-outline-items'].map(s => {
  const box = document.querySelector(s), last = box.lastElementChild;
  return [s, {rows: box.querySelectorAll('button').length, note: last && last.classList.contains('ol-more') ? last.textContent : null,
    notes: box.querySelectorAll('.ol-more').length, focusable: box.querySelectorAll('.ol-more button,.ol-more [tabindex]').length}];}))"""


class OutlineBase(BrowserBase):
    """The viewer over helpers_figure.viewer_docs' three documents, with the outline of the document on screen given by a test."""

    WHO = ALICE

    def setUp(self):
        """viewer_docs' three documents."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)

    def on(self, doc, lang="ko", **device):
        """The viewer showing document doc, settled, the outline panel open."""
        init = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1},outlineClosed:false}))}catch(e){}"
        page = self.open(0, lang=lang, init=init, **(device or DESKTOP))
        if doc != "ms":
            page.evaluate("k=>switchDoc(k)", doc)
            page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&document.querySelector('#p1')", arg=doc)
            settle(page)
        return page

    def load(self, page, tree, pages=2):
        """Load `tree` as the outline of the document on screen; (entries read, entries left unread)."""
        got = page.evaluate(LOAD_TREE, [tree, pages])
        settle(page)
        return got


class LongOutline(OutlineBase):
    """The outline of a PDF with more entries than the viewer reads: the first ones whole, the rest counted and said."""

    def test_an_outline_within_the_cap_is_whole_and_has_no_note(self):
        """170 entries (a figure document of ninety pages), 1500 and exactly the cap are all drawn - in the outline panel
        and in the navigation sheet's list - and neither list carries a note."""
        page = self.on("fig")
        for n in (170, 1500, CAP):
            with self.subTest(entries=n):
                self.assertEqual(self.load(page, grouped_tree(n, 2)), [n, 0])
                got = page.evaluate(LISTS)
                for box in got.values():
                    self.assertEqual((box["rows"], box["note"], box["notes"]), (n, None, 0), got)

    def test_what_the_cap_leaves_unread_is_counted_and_said_at_the_end(self):
        """The first CAP entries are drawn in outline order; the note, the last line of both lists, is not a row (no
        button, no tab stop) and gives the count of the unread ones and the limits, in the UI language."""
        page = self.on("fig")
        self.assertEqual(self.load(page, grouped_tree(CAP + 137, 2)), [CAP, 137])
        got = page.evaluate(LISTS)
        for box in got.values():
            self.assertEqual((box["rows"], box["notes"], box["focusable"]), (CAP, 1, 0), got)
            self.assertEqual(box["note"], "목차 항목 137개를 생략했습니다 — 읽는 한도는 2,000개, 5단계입니다")
        self.assertEqual(page.evaluate("OUTLINE_ENTRIES[%d].title" % (CAP - 1)), grouped_titles(CAP + 137)[CAP - 1])
        self.assertEqual(
            page.evaluate("document.querySelector('#outline-items .ol-more').getAttribute('role')"), "note"
        )
        english = self.on("fig", lang="en")
        self.assertEqual(self.load(english, grouped_tree(CAP + 137, 2)), [CAP, 137])
        self.assertEqual(
            english.evaluate(LISTS)["#outline-items"]["note"],
            "137 outline entries are not shown — the viewer reads at most 2,000 entries and 5 levels",
        )

    def test_what_the_depth_limit_leaves_unread_is_counted_too(self):
        """An outline nested eight levels deep is read down to five; the three deeper entries are counted and said."""
        page = self.on("fig")
        self.assertEqual(self.load(page, chain_tree(8)), [LEVELS, 3])
        self.assertEqual(page.evaluate(LISTS)["#outline-items"]["note"].split("개")[0], "목차 항목 3")
        self.assertEqual(self.load(page, chain_tree(LEVELS)), [LEVELS, 0])
        self.assertIsNone(page.evaluate(LISTS)["#outline-items"]["note"])

    def test_a_cap_and_the_depth_limit_add_up(self):
        """Entries cut by the count and by the depth are one number. 1900 entries, then a chain of eight levels (five read,
        three too deep) and 200 more of which the 95 that still fit are read: 3 + 105 unread. A chain after CAP entries is
        counted whole."""
        page = self.on("fig")
        self.assertEqual(self.load(page, grouped_tree(1900, 2) + chain_tree(8) + grouped_tree(200, 2)), [CAP, 3 + 105])
        self.assertEqual(self.load(page, grouped_tree(CAP, 2) + chain_tree(8)), [CAP, 8])

    def test_the_filter_says_what_it_did_not_search(self):
        """A filter's results end with the same note, worded for a search; a filter that finds nothing says so and gives the
        note under it; clearing it brings the whole list and its first note back. With nothing unread, no note."""
        page = self.on("fig")
        self.load(page, grouped_tree(CAP + 40, 2))
        page.fill("#outline-search", "S3.4")
        got = page.evaluate(LISTS)["#outline-items"]
        self.assertGreaterEqual(got["rows"], 1)
        self.assertEqual(got["note"], "생략한 목차 항목 40개는 검색하지 않았습니다 — 읽는 한도는 2,000개, 5단계입니다")
        page.fill("#outline-search", "no such section")
        self.assertEqual(
            page.evaluate("document.querySelector('#outline-items').textContent"),
            "찾은 장·절이 없습니다.생략한 목차 항목 40개는 검색하지 않았습니다 — 읽는 한도는 2,000개, 5단계입니다",
        )
        self.assertEqual(page.evaluate("document.querySelector('#outline-items').className"), "outline-empty")
        page.fill("#outline-search", "")
        got = page.evaluate(LISTS)["#outline-items"]
        self.assertEqual(got["rows"], CAP)
        self.assertTrue(got["note"].startswith("목차 항목 40개를 생략했습니다"), got)
        self.load(page, grouped_tree(200, 2))
        page.fill("#outline-search", "no such section")
        self.assertEqual(
            page.evaluate("document.querySelector('#outline-items').textContent"), "찾은 장·절이 없습니다."
        )
        page.fill("#outline-search", "S2")
        self.assertIsNone(page.evaluate(LISTS)["#outline-items"]["note"])
        phone = self.on("fig", **PHONE)
        self.load(phone, grouped_tree(CAP + 40, 2))
        phone.click("#btn-pos")
        phone.wait_for_function("document.querySelector('#nav-sheet').open")
        phone.fill("#ns-outline-search", "S3.4")
        self.assertTrue(phone.evaluate(LISTS)["#ns-outline-items"]["note"].startswith("생략한 목차 항목 40개는"))

    def test_one_broken_destination_leaves_out_that_entry_only(self):
        """A destination PDF.js cannot resolve (a named destination that rejects, a page reference that throws) left out the
        whole outline when the siblings were resolved together: a root with 1,999 good descendants and a broken sibling was
        read as nothing. Now the good ones are drawn and only the broken ones are not."""
        page = self.on("fig")
        got = page.evaluate(
            """async () => {
              const kids = Array.from({length: 1998}, (_, i) => ({title: 'k' + i, dest: [i % 2], items: []}));
              const rows = [{title: 'root', dest: [0], items: kids}, {title: 'broken name', dest: 'nowhere', items: []},
                {title: 'broken ref', dest: [{num: 9, gen: 0}], items: []}, {title: 'after', dest: [1], items: []}];
              const doc = {numPages: 2, getOutline: async () => rows,
                getDestination: async () => {throw new Error('no such destination');},
                getPageIndex: async () => {throw new Error('no such page');}};
              VEC.doc = doc; await loadOutline(doc, ++VEC.gen);
              return [OUTLINE_ENTRIES.length, OUTLINE_CUT, OUTLINE_ENTRIES[0].title, OUTLINE_ENTRIES.at(-1).title];}"""
        )
        self.assertEqual(got, [CAP, 0, "root", "after"])

    def test_a_newer_open_stops_the_reading_between_batches(self):
        """The document left behind does not go on asking the PDF worker: a switch on the first destination had all 2,000
        destinations asked for. Now only the batch in flight (100) is."""
        page = self.on("fig")
        got = page.evaluate(
            """async () => {
              let asked = 0;
              const rows = Array.from({length: 2000}, (_, i) => ({title: 't' + i, dest: [{num: i, gen: 0}], items: []}));
              const doc = {numPages: 2, getOutline: async () => rows, getDestination: async () => null,
                getPageIndex: async () => {if (++asked === 1) VEC.gen++; return 0;}};
              const before = [OUTLINE_ENTRIES, OUTLINE_CUT];
              VEC.doc = doc; await loadOutline(doc, ++VEC.gen);
              return {asked, kept: OUTLINE_ENTRIES === before[0] && OUTLINE_CUT === before[1]};}"""
        )
        self.assertEqual(got, {"asked": 100, "kept": True})

    def test_an_outline_cut_to_nothing_still_says_so(self):
        """Entries deeper than the limit under ancestors that name no place leave no entry at all, but they are counted: both
        lists say so, the sheet keeps its outline section, and the 'no outline' sentence is not what they claim."""
        page = self.on("fig", **PHONE)
        got = page.evaluate(
            """async () => {
              let n = {title: 'deep', dest: [0], items: []};
              for (let d = 0; d < 6; d++) n = {title: 'group' + d, dest: null, items: [n]};
              const doc = {numPages: 2, getOutline: async () => [n], getDestination: async () => null, getPageIndex: async () => 0};
              VEC.doc = doc; await loadOutline(doc, ++VEC.gen);
              return [OUTLINE_ENTRIES.length, OUTLINE_CUT, document.querySelector('#ns-outline').hidden];}"""
        )
        self.assertEqual(got, [0, 1, False])
        for box in ("#outline-items", "#ns-outline-items"):
            self.assertEqual(
                page.evaluate("s => document.querySelector(s).textContent", box),
                "목차 항목 1개를 생략했습니다 — 읽는 한도는 2,000개, 5단계입니다",
            )
        page.click("#btn-pos")
        page.wait_for_function("document.querySelector('#nav-sheet').open")
        self.assertTrue(page.is_visible("#ns-outline"))

    def test_picking_an_entry_and_opening_the_sheet_move_the_mark_without_drawing_the_lists_again(self):
        """Choosing an outline entry and opening the phone's sheet drew both lists again (50-70 ms at the cap, 200-300 ms on a
        phone). The rows stay the elements they were; only the mark moves, to the entry chosen."""
        page = self.on("fig", **PHONE)
        self.load(page, grouped_tree(CAP, 2))
        page.evaluate(
            "document.querySelectorAll('#outline-items button, #ns-outline-items button').forEach((b, i) => {b.dataset.kept = i;})"
        )
        page.evaluate("pickOutline(1500)")
        marks = """() => ['#outline-items', '#ns-outline-items'].map(s => [...document.querySelectorAll(s + ' .ol-active')].map(b => +b.dataset.index))"""
        self.assertEqual(page.evaluate(marks), [[1500], [1500]])
        page.click("#btn-pos")
        page.wait_for_function("document.querySelector('#nav-sheet').open")
        self.assertEqual(page.evaluate(marks), [[1500], [1500]])
        kept = page.evaluate(
            "[...document.querySelectorAll('#outline-items button, #ns-outline-items button')].every((b, i) => b.dataset.kept === String(i))"
        )
        self.assertTrue(kept, "the rows were drawn again")

    def test_a_real_pdf_outline_is_read_through_pdfjs_with_its_cap(self):
        """The bytes of a PDF with CAP + 300 bookmarks, opened as a view-only document: the viewer draws CAP rows and
        counts the 300 it left unread; a PDF with 170 shows all of them and no note."""
        for n, (rows, cut) in ((CAP + 300, (CAP, 300)), (170, (170, 0))):
            with self.subTest(entries=n):
                self.rv.main.write_bytes(outline_pdf(2, grouped_tree(n, 2)))
                helpers_figure.viewer_build(self.rv, helpers_figure.BUILD1)
                page = self.on("rv")
                page.wait_for_function("OUTLINE_ENTRIES.length>0", timeout=30000)
                settle(page)
                self.assertEqual(page.evaluate("[OUTLINE_ENTRIES.length, OUTLINE_CUT]"), [rows, cut])
                got = page.evaluate(LISTS)["#outline-items"]
                self.assertEqual((got["rows"], got["note"] is not None), (rows, cut > 0))

    def test_the_strip_and_the_filter_stay_fast_at_the_cap(self):
        """With CAP entries the section strip's lookup, a section change and a filter keystroke cost milliseconds. The
        bounds are an order of magnitude over what a laptop measures (lookup 0.01ms, section change 0.5ms, keystroke
        10ms), so a slow runner does not fail them but a lookup or a redraw that grew with the entries' number
        squared would."""
        page = self.on("fig")
        self.load(page, grouped_tree(CAP, 2))
        got = page.evaluate(
            """() => {const t = () => performance.now(), E = OUTLINE_ENTRIES, f = document.querySelector('#outline-search');
              let t0 = t(); for (let i = 0; i < 200; i++) outlineIndexAt(E, 1 + i % 2, (i % 100) / 100);
              const lookup = (t() - t0) / 200;
              t0 = t(); for (let i = 0; i < 20; i++) {OUTLINE_SELECTED = (i * 97) % E.length; OUTLINE_ACTIVE_PAGE = -1; updateSectionStrip();}
              const change = (t() - t0) / 20;
              f.value = 'S'; t0 = t(); f.dispatchEvent(new Event('input')); const key = t() - t0;
              return {lookup, change, key};}"""
        )
        self.assertLess(got["lookup"], 1, got)
        self.assertLess(got["change"], 20, got)
        self.assertLess(got["key"], 400, got)

    def test_a_section_change_moves_the_mark_without_drawing_the_list_again(self):
        """Scrolling a long document changes the section at every page; the rows of the list stay the same elements and
        only the mark (ol-active, aria-current) moves - in both lists, one row each."""
        page = self.on("fig")
        self.load(page, grouped_tree(CAP, 2))
        page.evaluate("document.querySelectorAll('#outline-items button').forEach((b, i) => {b.dataset.kept = i;})")
        page.evaluate("OUTLINE_SELECTED = 5; OUTLINE_ACTIVE_PAGE = -1; markOutline()")
        page.evaluate("OUTLINE_SELECTED = 1200; OUTLINE_ACTIVE_PAGE = -2; markOutline()")
        got = page.evaluate(
            """() => ['#outline-items', '#ns-outline-items'].map(s => {
              const on = [...document.querySelectorAll(s + ' .ol-active')], b = document.querySelectorAll(s + ' button');
              return {n: on.length, index: on.map(x => +x.dataset.index), current: on.map(x => x.getAttribute('aria-current')),
                others: [...b].filter(x => !x.classList.contains('ol-active') && x.getAttribute('aria-current') !== 'false').length,
                kept: s === '#outline-items' ? [...b].every((x, i) => x.dataset.kept === String(i)) : true};})"""
        )
        for box in got:
            self.assertEqual((box["n"], box["index"], box["current"], box["others"]), (1, [1200], ["location"], 0), got)
        self.assertTrue(got[0]["kept"], "the rows were drawn again")
        # a row the filter hides has no mark, and clearing the filter brings the current one back
        page.fill("#outline-search", "S3.4")
        page.evaluate("markOutline()")
        self.assertEqual(page.evaluate("document.querySelectorAll('#outline-items .ol-active').length"), 0)
        page.fill("#outline-search", "")
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#outline-items .ol-active')].map(x => +x.dataset.index)"),
            [1200],
        )

    def test_a_manuscript_outline_is_drawn_as_before(self):
        """A LaTeX manuscript's outline - a few dozen entries - is drawn whole with no note, and the row markup is the one
        the list always had."""
        page = self.on("ms")
        read, cut = self.load(page, grouped_tree(40, 2))
        self.assertEqual((read, cut), (40, 0))
        got = page.evaluate(
            """() => {const b = document.querySelector('#outline-items button');
              return {n: document.querySelectorAll('#outline-items button').length, notes: document.querySelectorAll('.ol-more').length,
                attrs: [...b.attributes].map(a => a.name).sort(), kids: [...b.children].map(c => c.className)};}"""
        )
        self.assertEqual(got["n"], 40)
        self.assertEqual(got["notes"], 0)
        self.assertEqual(
            got["attrs"],
            sorted(
                ["translate", "class", "data-act", "data-index", "data-page", "data-close", "aria-current", "title"]
            ),
        )
        self.assertEqual(got["kids"], ["ol-no", "ol-name", "ol-page"])


# Where a row can be seen: from under the filter's band to the panel's bottom.
VIEW = """const box = document.querySelector('#outline'), o = box.getBoundingClientRect(),
  edge = document.querySelector('#outline-find').getBoundingClientRect().bottom;"""
# The marked row against the panel it scrolls in, and what must stay as it was: the marked entry, whether its row shows whole,
# how far it stands under the filter's band and over the panel's bottom, the panel's scroll, the pages' and the window's, and the
# focus.
FOLLOW = (
    """() => {"""
    + VIEW
    + """ const row = document.querySelector('#outline-items .ol-active'), r = row ? row.getBoundingClientRect() : null,
  a = document.activeElement;
  return {index: row ? +row.dataset.index : null, whole: !!r && r.top >= edge - 0.5 && r.bottom <= o.bottom + 0.5,
    under: r ? r.top - edge : null, over: r ? o.bottom - r.bottom : null, top: box.scrollTop,
    pages: document.querySelector('#left').scrollTop, window: scrollY, focus: a.id || a.tagName};}"""
)
# The marked row going up against the band: its entry, whether it shows whole, how far under the band stand the top of the row two
# above it (null when there is none), of its section's head (null at the top level) and of what the follow keeps over it - two rows
# above that head, else above the row - and the pages' scroll and the focus.
UP = (
    """() => {"""
    + VIEW
    + """ const row = document.querySelector('#outline-items .ol-active'), r = row.getBoundingClientRect(), e = OUTLINE_ENTRIES[+row.dataset.index];
  const two = b => b.previousElementSibling && b.previousElementSibling.previousElementSibling,
    head = e.up >= 0 ? document.querySelector('#outline-items [data-index="' + e.up + '"]') : null, lead = two(head || row), a = document.activeElement;
  return {index: +row.dataset.index, whole: r.top >= edge - 0.5 && r.bottom <= o.bottom + 0.5,
    two: two(row) ? two(row).getBoundingClientRect().top - edge : null, head: head ? head.getBoundingClientRect().top - edge : null,
    lead: lead ? lead.getBoundingClientRect().top - edge : null, pages: document.querySelector('#left').scrollTop, focus: a.id || a.tagName};}"""
)
# Whether the marked row shows whole in the panel: what a follow ends in, so a test waits on it (and fails at the wait without one).
SHOWN = (
    """() => {"""
    + VIEW
    + """ const row = document.querySelector('#outline-items .ol-active');
  if (!row) return false; const r = row.getBoundingClientRect();
  return r.top >= edge - 0.5 && r.bottom <= o.bottom + 0.5;}"""
)
# Resolves when the panel has not scrolled for five frames in a row: a smooth follow is over.
STILL = """() => new Promise(done => {const box = document.querySelector('#outline'); let last = -1, same = 0;
  const look = () => {same = box.scrollTop === last ? same + 1 : 0; last = box.scrollTop; if (same >= 5) done(); else requestAnimationFrame(look);};
  look();})"""
# Puts page n's top at the top of the pages and waits until the viewer has read it; #left's scrollTop as that left it.
READ_TO = """n => new Promise(done => {const L = document.querySelector('#left');
  document.getElementById('p' + n).scrollIntoView();
  const top = L.scrollTop, look = () => {if (OUTLINE_ACTIVE_PAGE === n) done(top); else requestAnimationFrame(look);}; look();})"""
# Records in window.SCROLLS what the panel is asked to scroll to, leaving it to scroll.
SCROLLS = """() => {const box = document.querySelector('#outline'), to = box.scrollTo; window.SCROLLS = [];
  box.scrollTo = function (o) {window.SCROLLS.push(o); return to.call(this, o);};}"""
LONG = 120  # rows, over the two pages: page 2 opens at entry 60, well below the fold of an 850px window
FIRST_ON_2 = 60  # that entry: the deepest of those at the page's top, the first listed of them


class OutlineFollow(OutlineBase):
    """The outline panel keeps the current section in view (docs/handbook/viewer.md §모바일 레이아웃): only the panel
    moves, it glides unless reduced motion, it starts at the current row when it opens, and it leaves the list alone while the
    person has it in hand."""

    def long(self, **device):
        """The manuscript's two pages with a LONG-row outline, reading page 1."""
        page = self.on("ms", **device)
        self.assertEqual(self.load(page, grouped_tree(LONG, 2)), [LONG, 0])
        return page

    def read_to(self, page, n):
        """Read page n; the scrollTop of the pages as that left them."""
        return page.evaluate(READ_TO, n)

    def over_outline(self, page):
        """Rest the mouse on the panel, away from its filter."""
        box = page.locator("#outline").bounding_box()
        page.mouse.move(box["x"] + 100, box["y"] + box["height"] / 2)

    def over_pages(self, page):
        """Rest the mouse on the pages."""
        box = page.locator("#left").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    def test_reading_on_brings_the_row_into_view_and_nothing_else_moves(self):
        """The row of the page read lay below the panel's fold: it comes into view from the nearest side with room beyond it,
        and the pages, the window and the focus stay exactly where they were. Reading back, it comes in from the other side
        and at the first row the panel's head shows whole."""
        page = self.long()
        fold = page.evaluate("document.querySelector('#outline').getBoundingClientRect().bottom")
        row = page.locator('#outline-items button[data-index="%d"]' % FIRST_ON_2).bounding_box()
        self.assertGreater(row["y"], fold, "the row is in view already, so this would show nothing")
        pages = self.read_to(page, 2)
        page.wait_for_function(SHOWN, timeout=3000)
        page.evaluate(STILL)
        got = page.evaluate(FOLLOW)
        self.assertEqual(got["index"], FIRST_ON_2, got)
        self.assertGreater(got["top"], 0, got)
        self.assertEqual((got["pages"], got["window"], got["focus"]), (pages, 0, "BODY"), got)
        self.assertAlmostEqual(got["over"], 48, delta=1, msg=got)
        pages = self.read_to(page, 1)
        page.wait_for_function(SHOWN, timeout=3000)
        page.evaluate(STILL)
        got = page.evaluate(FOLLOW)
        self.assertEqual((got["index"], got["top"]), (1, 0), got)  # the deepest of the entries at the page's top
        self.assertEqual((got["pages"], got["window"], got["focus"]), (pages, 0, "BODY"), got)

    def test_a_row_clear_of_the_margin_moves_nothing_and_the_margin_holds(self):
        """A mark that moves within what stands clear of the margin leaves the list where it is. From the row that enters the
        margin on, every row keeps it: the list goes one row at a time, rather than letting the next rows use the margin up
        and then moving by all of it at once."""
        page = self.long()
        page.evaluate(SCROLLS)
        last = page.evaluate(
            """() => {const box = document.querySelector('#outline').getBoundingClientRect();
              return Math.max(...[...document.querySelectorAll('#outline-items button')]
                .filter(b => b.getBoundingClientRect().bottom <= box.bottom - 48).map(b => +b.dataset.index));}"""
        )
        for i in (5, last, 0):
            page.evaluate("i => {OUTLINE_SELECTED = i; markOutline();}", i)
            self.assertEqual(page.evaluate("SCROLLS"), [])
        self.assertEqual(page.evaluate(FOLLOW)["top"], 0)
        for i in range(last + 1, last + 7):
            with self.subTest(row=i):
                page.evaluate("i => {OUTLINE_SELECTED = i; markOutline();}", i)
                page.evaluate(STILL)
                self.assertAlmostEqual(page.evaluate(FOLLOW)["over"], 48, delta=1)
        self.assertEqual(len(page.evaluate("SCROLLS")), 6)

    def test_it_glides_a_short_way_and_jumps_a_long_one(self):
        """Within the panel's height the follow is smooth. A longer way - an outline out of page order sends a row a thousand
        px off - lands at once, and leaves nothing heading anywhere."""
        page = self.long()
        page.evaluate(SCROLLS)
        near = page.evaluate(
            """() => {const box = document.querySelector('#outline'), o = box.getBoundingClientRect();
              return Math.max(...[...document.querySelectorAll('#outline-items button')].filter(b =>
                b.getBoundingClientRect().bottom - o.bottom + 48 <= box.clientHeight).map(b => +b.dataset.index));}"""
        )
        page.evaluate("i => {OUTLINE_SELECTED = i; markOutline();}", near)
        page.wait_for_function(SHOWN, timeout=3000)
        self.assertEqual(page.evaluate("SCROLLS.map(o => o.behavior)"), ["smooth"])
        page.evaluate(STILL)
        page.evaluate("document.querySelector('#outline').scrollTop = 0; SCROLLS.length = 0")
        page.wait_for_function("OUTLINE_AIM === null", timeout=3000)
        page.evaluate("i => {OUTLINE_SELECTED = i; markOutline();}", near + 1)
        self.assertEqual(page.evaluate("SCROLLS.map(o => o.behavior)"), ["auto"])
        self.assertTrue(page.evaluate(SHOWN))
        self.assertIsNone(page.evaluate("OUTLINE_AIM"))

    def test_reduced_motion_jumps(self):
        """With reduced motion the follow is done before the call returns, so nothing moves on screen."""
        page = self.long(reduced_motion="reduce", **DESKTOP)
        page.evaluate(SCROLLS)
        top = page.evaluate(
            """() => {OUTLINE_SELECTED = 60; markOutline(); return document.querySelector('#outline').scrollTop;}"""
        )
        self.assertGreater(top, 0)
        self.assertTrue(page.evaluate(SHOWN))
        self.assertEqual(page.evaluate("SCROLLS.map(o => o.behavior)"), ["auto"])

    def test_a_pointer_over_the_panel_holds_the_list_until_it_leaves(self):
        """While the mouse rests on the panel the list stays, whatever the pages do; when it leaves the row comes in."""
        page = self.long()
        self.over_outline(page)
        self.read_to(page, 2)
        nothing_follows(page)
        got = page.evaluate(FOLLOW)
        self.assertEqual((got["index"], got["top"], got["whole"]), (FIRST_ON_2, 0, False), got)
        self.over_pages(page)
        page.wait_for_function(SHOWN, timeout=3000)

    def test_a_wheel_in_the_panel_holds_the_list_for_a_few_seconds(self):
        """The person's own scroll wins: the mouse gone from the panel, the list stays where the wheel left it for the
        hold, and then the row comes in - without a further move of the mark."""
        page = self.long()
        self.over_outline(page)
        page.mouse.wheel(0, 300)
        page.wait_for_function("document.querySelector('#outline').scrollTop > 0")
        page.evaluate(STILL)
        top = page.evaluate(FOLLOW)["top"]
        self.over_pages(page)
        self.read_to(page, 2)
        nothing_follows(page)
        self.assertEqual(page.evaluate(FOLLOW)["top"], top)
        page.wait_for_function(SHOWN, timeout=6000)

    def test_a_scrollbar_press_or_a_touch_on_the_panel_holds_the_list_too(self):
        """A press (the scroll bar's, a row's) and a touch count as the wheel does: the list waits, then the row comes in."""
        for event in ("pointerdown", "touchstart"):
            with self.subTest(event=event):
                page = self.long()
                page.evaluate("t => document.querySelector('#outline').dispatchEvent(new Event(t))", event)
                self.read_to(page, 2)
                nothing_follows(page)
                self.assertEqual(page.evaluate(FOLLOW)["top"], 0)
                page.wait_for_function(SHOWN, timeout=6000)

    def test_the_hold_goes_on_with_the_persons_own_scroll(self):
        """A scroll that goes on inside a hold (a fling, a smooth wheel) extends it; one outside a hold is a follow's own or a
        script's and holds nothing."""
        page = self.long()
        got = page.evaluate(
            """async () => {const box = document.querySelector('#outline'), tick = () => new Promise(r => box.addEventListener('scroll', r, {once: true}));
              const outside = (box.scrollTop = 30, await tick(), OUTLINE_HANDLED);
              OUTLINE_HANDLED = performance.now() - 2000; const was = OUTLINE_HANDLED;
              box.scrollTop = 60; await tick();
              return {outside: outside === -Infinity, extended: OUTLINE_HANDLED > was};}"""
        )
        self.assertEqual(got, {"outside": True, "extended": True})

    def test_the_filter_holds_the_list_while_it_has_text(self):
        """Typed in, the filter's field holds the list even without the focus: its rows are the results. Emptied, it holds
        nothing: the typing's own hold over, the current row comes in under the list drawn again, with the focus left in the
        field and no event to say the filter was let go - a tap on the pages does not take the focus away."""
        page = self.long()
        page.fill("#outline-search", "S")  # every row matches: the list stays as long, and a follow could show
        page.evaluate("document.activeElement.blur()")
        self.read_to(page, 2)
        nothing_follows(page)
        got = page.evaluate(FOLLOW)
        self.assertEqual((got["index"], got["top"], got["whole"]), (FIRST_ON_2, 0, False), got)
        page.fill("#outline-search", "")  # by the Delete key: a key in the panel is its own hold
        nothing_follows(page)
        self.assertEqual(page.evaluate(FOLLOW)["top"], 0)
        page.wait_for_function(SHOWN, timeout=6000)
        self.assertEqual(page.evaluate(FOLLOW)["focus"], "outline-search")

    def test_a_focus_in_the_empty_filter_holds_nothing(self):
        """A field with the focus and no text is not in use: reading on brings the row in, and the field keeps the focus."""
        page = self.long()
        page.focus("#outline-search")
        self.read_to(page, 2)
        page.wait_for_function(SHOWN, timeout=3000)
        self.assertEqual(page.evaluate(FOLLOW)["focus"], "outline-search")

    def test_the_filter_stays_in_reach_above_the_list(self):
        """However far the list is, the filter and its hint stay at the top of the panel, on every band that has it, and rows
        pass under them: a press on the field reaches the field. With the list at its top it stands where it always stood."""
        for name, device in (("desktop", DESKTOP), ("fold", FOLD)):
            with self.subTest(device=name):
                page = self.long(**device)
                self.read_to(page, 2)
                if device is FOLD:
                    page.tap("#nav-toc-toggle")
                page.wait_for_function(SHOWN, timeout=3000)
                page.evaluate(STILL)
                got = page.evaluate(
                    """() => {const box = document.querySelector('#outline'), o = box.getBoundingClientRect(),
                      f = document.querySelector('#outline-search'), r = f.getBoundingClientRect(),
                      band = document.querySelector('#outline-find'), b = band.getBoundingClientRect(),
                      above = document.elementFromPoint(r.left + r.width / 2, o.top + 2);
                      return {scrolled: box.scrollTop, band: b.top - o.top, field: r.top - o.top,
                        hit: document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === f,
                        rowAbove: !!above && !!above.closest('#outline-items')};}"""
                )
                self.assertGreater(got["scrolled"], 0, got)
                self.assertEqual(got["band"], 0, got)  # flush with the panel's top: no row shows above it
                self.assertFalse(got["rowAbove"], got)
                self.assertGreater(got["field"], 0, got)
                self.assertTrue(got["hit"], got)
        page = self.long()
        self.read_to(page, 2)
        page.wait_for_function(SHOWN, timeout=3000)
        page.evaluate(STILL)
        page.focus("#outline-search")
        hint = page.locator("#outline-hint").bounding_box()
        band = page.locator("#outline-find").bounding_box()
        self.assertGreater(hint["height"], 0)
        self.assertLessEqual(hint["y"] + hint["height"], band["y"] + band["height"])
        self.assertEqual(
            page.evaluate("document.elementFromPoint(%f, %f).id" % (hint["x"] + 20, hint["y"] + 4)), "outline-hint"
        )
        self.assertEqual(
            page.evaluate("parseFloat(document.querySelector('#outline').style.scrollPaddingTop)"), band["height"]
        )

    def test_the_margin_counts_from_under_the_filter(self):
        """Going up, what the list keeps over a row - here its section's head and the two rows above that - starts right under
        the band, not under the panel's top, on a list that is far down."""
        page = self.long()
        self.read_to(page, 2)
        page.wait_for_function(SHOWN, timeout=3000)
        page.evaluate(STILL)
        top = page.evaluate("document.querySelector('#outline').scrollTop")
        row = page.evaluate(
            """top => {const box = document.querySelector('#outline'), o = box.getBoundingClientRect();
              box.scrollTop = top + 600;
              return Math.min(...[...document.querySelectorAll('#outline-items button')]
                .filter(b => b.getBoundingClientRect().top >= o.top + 60 && OUTLINE_ENTRIES[+b.dataset.index].up >= 0)
                .map(b => +b.dataset.index));}""",
            top,
        )
        page.evaluate("i => {OUTLINE_SELECTED = i; markOutline();}", row)
        page.evaluate(STILL)
        got = page.evaluate(UP)
        self.assertEqual(got["index"], row, got)
        self.assertTrue(got["whole"], got)
        self.assertAlmostEqual(got["lead"], 0, delta=1, msg=got)

    def walk_up(self, page, start, stop):
        """Mark start, then each entry above it down to stop as reading back a page at a time does; what UP read at each,
        and how many times the panel was asked to scroll on the way."""
        page.evaluate("i => {OUTLINE_SELECTED = i; markOutline();}", start)
        page.evaluate(STILL)
        page.evaluate(SCROLLS)
        pages = page.evaluate("document.querySelector('#left').scrollTop")
        seen = []
        for i in range(start - 1, stop - 1, -1):
            page.evaluate("i => {OUTLINE_SELECTED = i; markOutline();}", i)
            page.evaluate(STILL)
            got = page.evaluate(UP)
            self.assertEqual((got["index"], got["pages"], got["focus"]), (i, pages, "BODY"), got)
            seen.append(got)
        return seen, len(page.evaluate("SCROLLS"))

    def test_coming_up_into_a_section_shows_its_head_and_the_rows_up_to_it_move_nothing(self):
        """Reading back, the marked row has two whole rows over it, and where its section fits in the panel with it, the head
        it belongs to shows too (#335: 48px kept the row a row and a half under the filter, the head out of sight). The list
        moves once as the reading comes up into a section and not again until it leaves it - never more often than before -
        and the pages and the focus stay where they are."""
        page = self.long()
        seen, moves = self.walk_up(page, 110, 40)
        for got in seen:
            with self.subTest(index=got["index"]):
                self.assertTrue(got["whole"], got)
                self.assertGreaterEqual(got["two"], -0.5, got)  # two whole rows over it
                if got["head"] is not None:
                    self.assertGreaterEqual(got["head"], -0.5, got)  # and the head of its section
        self.assertGreater(moves, 0)
        self.assertLessEqual(moves, 7)  # into each of the seven sections the walk passes through, at most once

    def test_a_section_taller_than_the_panel_keeps_two_rows_over_the_row(self):
        """A section whose head cannot show with the row is followed a row at a time, with the two rows above it right under
        the filter's band: no more moves than one per row."""
        page = self.on("ms")
        self.assertEqual(self.load(page, grouped_tree(LONG, 2, LONG)), [LONG, 0])  # one head and all the rest under it
        seen, moves = self.walk_up(page, 100, 60)
        for got in seen:
            with self.subTest(index=got["index"]):
                self.assertTrue(got["whole"], got)
                self.assertGreaterEqual(got["two"], -0.5, got)
                self.assertLess(got["head"], 0, got)  # the head is too far above to show
        self.assertGreater(moves, 0)
        self.assertLessEqual(moves, len(seen))
        self.assertAlmostEqual(seen[-1]["two"], 0, delta=1, msg=seen[-1])

    def test_a_row_the_keyboard_walks_to_does_not_stop_under_the_filter(self):
        """The browser scrolls a focused row into view without knowing the band: the panel's scroll padding tells it, or a row
        reached by the arrow keys would have the focus and be covered."""
        page = self.long()
        self.read_to(page, 2)
        page.wait_for_function(SHOWN, timeout=3000)
        page.evaluate(STILL)
        page.focus('#outline-items button[data-index="%d"]' % FIRST_ON_2)
        page.evaluate("document.documentElement.dataset.input = 'key'")
        for _ in range(45):
            page.keyboard.press("ArrowUp")
            got = page.evaluate(
                "() => {"
                + VIEW
                + " const a = document.activeElement.getBoundingClientRect(); return {under: a.top - edge, i: document.activeElement.dataset.index};}"
            )
            self.assertGreaterEqual(got["under"], -0.5, got)

    def test_the_keyboard_on_a_row_holds_the_list_and_a_pressed_row_does_not(self):
        """With the keyboard on the rows the list is theirs. A row a mouse pressed keeps the focus after its pick, and that
        holds nothing once the press's own hold is over: reading on must not leave the outline behind."""
        page = self.long()
        page.focus("#outline-search")
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate("document.activeElement.dataset.index"), "0")
        self.read_to(page, 2)
        nothing_follows(page)
        self.assertEqual(page.evaluate(FOLLOW)["top"], 0)
        page.evaluate("document.activeElement.blur()")
        page.wait_for_function(SHOWN, timeout=3000)

        page = self.long()
        page.click('#outline-items button[data-index="3"]')
        settle(page)
        self.assertEqual(page.evaluate("document.activeElement.dataset.index"), "3")
        self.over_pages(page)
        page.evaluate("OUTLINE_HANDLED = -Infinity")  # the press's own hold, over
        self.read_to(page, 2)
        page.wait_for_function(SHOWN, timeout=3000)
        self.assertEqual(page.evaluate("document.activeElement.dataset.index"), "3")

    def test_a_press_that_leaves_the_focus_on_a_row_ends_the_keyboards_hold(self):
        """A press on the pages takes no focus, so the row keeps it and no focusout comes, but the keyboard is no longer the
        input: the follow owed since is made then, with the focus left where it is."""
        page = self.long()
        page.focus("#outline-search")
        page.keyboard.press("ArrowDown")
        self.read_to(page, 2)
        page.evaluate(
            "OUTLINE_HANDLED = -Infinity; outlineCatchUp()"
        )  # the timed hold over: only the keyboard's is left
        nothing_follows(page)
        self.assertEqual(page.evaluate("[OUTLINE_FOLLOW_DUE, document.querySelector('#outline').scrollTop]"), [True, 0])
        self.over_pages(page)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_function(SHOWN, timeout=3000)
        self.assertEqual(page.evaluate("document.activeElement.dataset.index"), "0")

    def test_a_press_in_the_panel_holds_before_the_keyboards_hold_is_let_go(self):
        """The press that ends the keyboard's hold may be in the panel, and one on the panel never moves the list under it:
        the press's own hold comes first, and the owed follow is made when that is over."""
        page = self.long()
        page.focus("#outline-search")
        page.keyboard.press("ArrowDown")
        self.read_to(page, 2)
        page.evaluate("OUTLINE_HANDLED = -Infinity; outlineCatchUp()")
        page.evaluate(
            "document.querySelector('.outline-title').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}))"
        )
        nothing_follows(page)
        self.assertEqual(page.evaluate(FOLLOW)["top"], 0)
        page.wait_for_function(SHOWN, timeout=6000)

    def test_the_width_grip_holds_the_list_for_a_whole_drag_and_lets_go_after_it(self):
        """The grip stands beside the panel, and a hand on it is a hand on the panel: a drag holds the list however long it
        lasts, past the timed hold too, and the owed follow is made after its release or its cancel."""
        for end in ("release", "cancel"):
            with self.subTest(end=end):
                page = self.long()
                grip = page.locator("#outline-grip").bounding_box()
                page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + 300)
                page.mouse.down()
                self.read_to(page, 2)
                nothing_follows(page)
                page.evaluate("OUTLINE_HANDLED = -Infinity; outlineCatchUp()")  # a drag longer than the timed hold
                nothing_follows(page)
                self.assertEqual(page.evaluate(FOLLOW)["top"], 0)
                if end == "release":
                    page.mouse.up()
                else:
                    page.evaluate(
                        """() => document.querySelector('#outline-grip').dispatchEvent(
                          new PointerEvent('pointercancel', {pointerId: 1, bubbles: true}))"""
                    )
                page.wait_for_function(SHOWN, timeout=6000)
                if end == "cancel":
                    page.mouse.up()

    def test_a_key_on_the_width_grip_holds_the_list_for_a_few_seconds(self):
        """The grip's keys count as its press does: the list waits, then the row comes in."""
        page = self.long()
        page.focus("#outline-grip")
        page.keyboard.press("ArrowRight")
        self.read_to(page, 2)
        nothing_follows(page)
        self.assertEqual(page.evaluate(FOLLOW)["top"], 0)
        page.wait_for_function(SHOWN, timeout=6000)

    def test_a_jump_reckons_from_where_the_list_is(self):
        """A glide leaves where it is heading for a while, and that is no place to reckon a jump from: reopened before a glide
        got there, the panel would take the row for shown and stay where it is, the row out of sight."""
        page = self.long()
        page.evaluate(
            """async () => {const box = document.querySelector('#outline'), frame = () => new Promise(requestAnimationFrame);
              document.getElementById('p2').scrollIntoView();
              while (OUTLINE_ACTIVE_PAGE !== 2) await frame();   // the glide has set out...
              box.scrollTo({top: 0, behavior: 'auto'});   // ...and has got nowhere
              toggleOutline(); await frame(); await frame(); toggleOutline();}"""
        )
        page.wait_for_function(SHOWN, timeout=3000)
        page = self.long()
        self.read_to(page, 2)
        page.wait_for_function(SHOWN, timeout=3000)
        page.evaluate(STILL)
        got = page.evaluate(
            """() => {const box = document.querySelector('#outline'), top = box.scrollTop; box.scrollTop = 0;
              OUTLINE_AIM = {top, at: performance.now()}; outlineFollow(true); return box.scrollTop;}"""
        )
        self.assertGreater(got, 0)
        self.assertTrue(page.evaluate(SHOWN))

    def test_nothing_is_left_heading_anywhere_when_a_glide_is_over(self):
        """Where a glide is heading goes with the glide: when it ends, when a hand on the panel stops it, when the filter draws
        the list again, when the panel closes and when another document comes on screen."""
        page = self.long()
        self.read_to(page, 2)
        page.wait_for_function("OUTLINE_AIM === null", timeout=3000)
        heading = "OUTLINE_AIM = {top: 500, at: performance.now()}"
        for name, act in (
            ("wheel", "document.querySelector('#outline').dispatchEvent(new Event('wheel'))"),
            ("press", "document.querySelector('#outline').dispatchEvent(new Event('pointerdown'))"),
            ("filter", "document.querySelector('#outline-search').dispatchEvent(new Event('input'))"),
        ):
            with self.subTest(by=name):
                self.assertIsNone(page.evaluate("() => {%s; %s; return OUTLINE_AIM;}" % (heading, act)))
        page.evaluate(heading)
        page.evaluate("toggleOutline()")
        page.wait_for_function("OUTLINE_AIM === null", timeout=3000)
        page.evaluate("toggleOutline()")
        page.evaluate(heading)
        page.evaluate("switchDoc('fig')")
        page.wait_for_function("DOC === 'fig' && OUTLINE_AIM === null", timeout=8000)

    def test_the_panel_opens_at_the_current_row(self):
        """Opened while a page far down is read, the panel starts there, at once: nobody has the list in hand yet."""
        page = self.long()
        page.evaluate("toggleOutline()")
        self.read_to(page, 2)
        page.evaluate(SCROLLS)
        self.over_pages(page)
        page.click("#nav-toc-toggle")
        page.wait_for_function(SHOWN, timeout=3000)
        self.assertEqual(page.evaluate("SCROLLS.map(o => o.behavior)"), ["auto"])

    def test_a_new_list_starts_at_the_current_row_and_a_new_build_stays_where_it_is(self):
        """The first list of a document jumps to the current row. A new build's list with the same entry current has nothing
        to bring in: a list the person left somewhere stays there."""
        page = self.on("ms")
        self.read_to(page, 2)
        page.evaluate(SCROLLS)
        self.load(page, grouped_tree(LONG, 2))
        page.wait_for_function(SHOWN, timeout=3000)
        self.assertEqual(page.evaluate("SCROLLS.map(o => o.behavior)"), ["auto"])
        page.evaluate("document.querySelector('#outline').scrollTop = 0")
        page.evaluate(STILL)
        self.load(page, grouped_tree(LONG, 2))
        self.assertEqual(page.evaluate(FOLLOW)["top"], 0)

    def test_a_panel_off_screen_is_left_alone_and_only_a_move_of_the_mark_reads_it(self):
        """No panel is asked to scroll while it is closed or on the phone. At a page with the same current entry, and at a
        frame with nothing new, the panel's place is not read at all (a read is a forced layout): only a move of the mark does."""
        page = self.long()
        page.evaluate("toggleOutline()")
        page.evaluate(SCROLLS)
        self.read_to(page, 2)
        nothing_follows(page)
        self.assertEqual(page.evaluate("SCROLLS"), [])
        phone = self.long(**PHONE)
        phone.evaluate(SCROLLS)
        self.read_to(phone, 2)
        nothing_follows(phone)
        self.assertEqual(phone.evaluate("SCROLLS"), [])
        page = self.long()
        got = page.evaluate(
            """() => {const box = document.querySelector('#outline'), read = box.getBoundingClientRect; let n = 0;
              box.getBoundingClientRect = function () {n++; return read.call(this);};
              for (let i = 0; i < 50; i++) updateSectionStrip();
              const still = n; OUTLINE_ACTIVE_PAGE = -1; updateSectionStrip();
              const samePage = n; OUTLINE_SELECTED = 60; markOutline();
              return {still, samePage, moved: n};}"""
        )
        self.assertEqual(got, {"still": 0, "samePage": 0, "moved": 1})

    def test_the_overlay_opens_at_the_current_row_and_the_phones_sheet_keeps_its_rule(self):
        """The overlay of a folded-out phone is the same panel: it opens at the current row, and the focus stays on the toggle.
        The phone's sheet is another list and keeps its own rule (navSheetReveal, SheetFocus): the sheet does not scroll
        past the view switch to reach it."""
        page = self.long(**FOLD)
        self.read_to(page, 2)
        self.assertEqual(page.evaluate(FOLLOW)["top"], 0)
        page.tap("#nav-toc-toggle")
        page.wait_for_function(SHOWN, timeout=3000)
        self.assertEqual(page.evaluate(FOLLOW)["focus"], "nav-toc-toggle")
        phone = self.long(**PHONE)
        self.read_to(phone, 2)
        phone.tap("#btn-pos")
        phone.wait_for_function("document.querySelector('#nav-sheet').open")
        settle(phone)
        got = phone.evaluate(
            """() => {const d = document.querySelector('#nav-sheet'), view = d.querySelector('#ns-view [aria-checked=true]');
              return view.getBoundingClientRect().top - d.querySelector('.ns-head').getBoundingClientRect().bottom;}"""
        )
        self.assertGreaterEqual(got, 0)


def flatten(tree):
    """Every node of an outline tree, parents before children."""
    for node in tree:
        yield node
        yield from flatten(node[2])


def grouped_titles(n):
    """The titles of grouped_tree(n, 2) in document order."""
    return [node[0] for node in flatten(grouped_tree(n, 2))]


# A figure set's outline as the map of a paper's figures gives it: each figure under its status and again under the manuscript
# figure that holds it. Entries (in outline order): 0 채택, 1 PL64, 2 PL65, 3 후보, 4 PL70, 5 본문 그림 3, 6 PL64 (again), 7 PL71.
GROUPED = [
    ("채택", 0, [("PL64 · 달력", 0, []), ("PL65 · 지도", 1, [])]),
    ("후보", 1, [("PL70 · 표", 1, [])]),
    ("본문 그림 3", 0, [("PL64 · 달력", 0, []), ("PL71 · 분포", 1, [])]),
]
# What a list shows as its rows: the text of each, whether a group stands in front of the name, and the row's description.
ROWS_OF = """s => [...document.querySelectorAll(s + ' button[data-act="outline-page"]')].map(b => ({
  text: b.querySelector('.ol-name').textContent, group: (b.querySelector('.ol-grp') || {}).textContent || null, title: b.title,
  index: +b.dataset.index}))"""
# The entry the outline chose (null until one is picked: the section strip names the entry at the reading line meanwhile) and
# where the keyboard is - the focused element's id, or 'row<index>' for a result.
KEYS_STATE = """() => ({pinned: OUTLINE_PINNED ? OUTLINE_PINNED.index : null,
  focus: document.activeElement.id || ('row' + document.activeElement.dataset.index)})"""


class OutlineFilter(OutlineBase):
    """The outline's filter (docs/handbook/viewer.md §모바일 레이아웃): a name that two groups share says its group in the results, and
    Enter and the arrow keys take the keyboard from the field into the results and back."""

    def figures(self, lang="ko", **device):
        """The figure document on screen with GROUPED as its outline."""
        page = self.on("fig", lang=lang, **device)
        self.assertEqual(self.load(page, GROUPED), [8, 0])
        return page

    def test_a_name_in_two_groups_says_its_group_in_the_results_only(self):
        """Typing PL64 finds the figure twice, as `채택 ›` over `PL64 · 달력` and `본문 그림 3 ›` over `PL64 · 달력` (the group on a
        line of its own above the row, and in the row's description); PL65, which one group has, reads as it is; a row reads the
        same whatever else is typed (PL6 finds the three); with nothing typed the list is the outline and says no group."""
        page = self.figures()
        self.assertEqual(page.evaluate("document.querySelectorAll('#outline-items .ol-grp').length"), 0)
        page.fill("#outline-search", "PL64")
        rows = page.evaluate(ROWS_OF, "#outline-items")
        self.assertEqual(
            [(r["text"], r["group"], r["title"], r["index"]) for r in rows],
            [
                ("PL64 · 달력", "채택 ›", "채택 › PL64 · 달력", 1),
                ("PL64 · 달력", "본문 그림 3 ›", "본문 그림 3 › PL64 · 달력", 6),
            ],
        )
        page.fill("#outline-search", "PL6")
        self.assertEqual(
            [(r["text"], r["group"]) for r in page.evaluate(ROWS_OF, "#outline-items")],
            [("PL64 · 달력", "채택 ›"), ("PL65 · 지도", None), ("PL64 · 달력", "본문 그림 3 ›")],
        )
        page.fill("#outline-search", "PL65")
        self.assertEqual(page.evaluate(ROWS_OF, "#outline-items")[0]["group"], None)
        page.fill("#outline-search", "")
        self.assertEqual(page.evaluate("document.querySelectorAll('#outline-items .ol-grp').length"), 0)
        self.assertEqual(page.evaluate("document.querySelectorAll('#outline-items button').length"), 8)
        # the group is small muted text, not bold, and sits above the number and the name
        page.fill("#outline-search", "PL64")
        look = page.evaluate(
            """() => { const b = document.querySelector('#outline-items .ol-grouped'), g = b.querySelector('.ol-grp'), n = b.querySelector('.ol-name'),
              gs = getComputedStyle(g), ns = getComputedStyle(n);
              return [gs.color !== ns.color, gs.fontWeight, parseFloat(gs.fontSize) < parseFloat(ns.fontSize),
                g.getBoundingClientRect().bottom <= n.getBoundingClientRect().top + 1]; }"""
        )
        self.assertEqual(look, [True, "400", True, True])

    def test_a_long_group_name_is_one_line_cut_and_never_makes_the_list_wider_or_the_row_taller(self):
        """A group named by a whole figure title (the figure document's `Fig. 3 · PL1 · … — 대안 4장`) takes the one line it has
        - 12px in the panel, with an ellipsis, the whole name in the row's description - on the panel (240px), the phone's
        sheet and the foldable; the list does not scroll sideways and the row is the name's lines plus that one line."""
        long = "Fig. 3 · PL1 · " + "아주 긴 그림 제목 " * 8 + "— 대안 4장"
        tree = [(long, 0, [("PL64 · 달력", 0, [])]), ("risk", 1, [("PL64 · 달력", 1, [])])]
        for name, device in (("desktop", DESKTOP), ("phone", PHONE), ("fold", FOLD)):
            with self.subTest(band=name):
                page = self.on("fig", **device)
                self.assertEqual(self.load(page, tree), [4, 0])
                box, field = (
                    ("#ns-outline-items", "#ns-outline-search")
                    if device is PHONE
                    else ("#outline-items", "#outline-search")
                )
                if device is PHONE:
                    page.click("#btn-pos")
                    page.wait_for_function("document.querySelector('#nav-sheet').open")
                elif not page.is_visible(field):  # the foldable's outline is an overlay
                    page.click("#nav-toc-toggle")
                    page.wait_for_selector(field, state="visible")
                page.fill(field, "PL64")
                got = page.evaluate(
                    """s => { const box = document.querySelector(s), g = [...box.querySelectorAll('.ol-grp')],
                      n = box.querySelector('.ol-name'), lh = parseFloat(getComputedStyle(g[0]).lineHeight);
                      return {n: g.length, h: g.map(x => Math.round(x.getBoundingClientRect().height) - Math.round(lh)),
                        ellipsis: getComputedStyle(g[0]).textOverflow, cut: g[0].scrollWidth > g[0].clientWidth,
                        title: box.querySelector('.ol-grouped').title.startsWith('Fig. 3 · PL1 · '), sideways: box.scrollWidth > box.clientWidth + 1,
                        within: g.every(x => x.getBoundingClientRect().right <= box.getBoundingClientRect().right + 1)}; }""",
                    box,
                )
                self.assertEqual(
                    got,
                    {
                        "n": 2,
                        "h": [0, 0],
                        "ellipsis": "ellipsis",
                        "cut": True,
                        "title": True,
                        "sideways": False,
                        "within": True,
                    },
                )

    def test_the_sheets_list_says_the_group_too(self):
        """The phone's navigation sheet has its own filter and the same rule; each field filters its own list."""
        page = self.figures(**PHONE)
        page.click("#btn-pos")
        page.wait_for_function("document.querySelector('#nav-sheet').open")
        page.fill("#ns-outline-search", "PL64")
        self.assertEqual(
            [r["text"] for r in page.evaluate(ROWS_OF, "#ns-outline-items")],
            ["PL64 · 달력", "PL64 · 달력"],
        )
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#ns-outline-items .ol-grp')].map(g => g.textContent)"),
            ["채택 ›", "본문 그림 3 ›"],
        )
        self.assertEqual(page.evaluate("document.querySelectorAll('#outline-items .ol-grp').length"), 0)

    def test_enter_chooses_the_first_result_and_the_arrows_walk_the_results(self):
        """In the field, ↓ moves the focus to the first result without choosing it; ↑ on the first goes back to the field and
        Esc from any result does; ↓/↑ move one result; Enter on a result chooses it (a button); Enter in the field chooses the
        first result and the focus follows it. A filter that finds nothing leaves the keys to the field."""
        page = self.figures()
        field = "#outline-search"
        page.fill(field, "PL6")
        page.focus(field)
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate(KEYS_STATE), {"pinned": None, "focus": "row1"})
        page.keyboard.press("ArrowDown")
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate(KEYS_STATE)["focus"], "row6")
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate(KEYS_STATE)["focus"], "row6")  # the last result: nowhere further
        page.keyboard.press("ArrowUp")
        self.assertEqual(page.evaluate(KEYS_STATE)["focus"], "row2")
        page.keyboard.press("Enter")
        self.assertEqual(page.evaluate(KEYS_STATE), {"pinned": 2, "focus": "row2"})
        page.keyboard.press("ArrowUp")
        page.keyboard.press("ArrowUp")
        self.assertEqual(page.evaluate(KEYS_STATE)["focus"], "outline-search")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Escape")
        self.assertEqual(page.evaluate(KEYS_STATE)["focus"], "outline-search")
        self.assertEqual(page.input_value(field), "PL6")
        self.assertTrue(page.is_visible("#outline"))
        page.keyboard.press("Enter")
        self.assertEqual(page.evaluate(KEYS_STATE), {"pinned": 1, "focus": "row1"})
        page.fill(field, "no such figure")
        page.focus(field)
        for key in ("ArrowDown", "Enter"):
            page.keyboard.press(key)
        self.assertEqual(page.evaluate(KEYS_STATE)["focus"], "outline-search")
        self.assertEqual(page.evaluate("OUTLINE_PINNED.index"), 1)

    def test_enter_in_an_empty_filter_chooses_nothing_and_the_arrow_still_goes_to_the_list(self):
        """With nothing typed (or only spaces) the filter lists every entry and Enter in the field does nothing - it used to go
        to the first of them; ↓ still moves the focus to the first entry without choosing it. Typing then Enter chooses."""
        page = self.figures()
        field = "#outline-search"
        page.focus(field)
        for typed in ("", "   "):
            page.fill(field, typed)
            page.keyboard.press("Enter")
            self.assertEqual(page.evaluate(KEYS_STATE), {"pinned": None, "focus": "outline-search"}, repr(typed))
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate(KEYS_STATE), {"pinned": None, "focus": "row0"})
        page.focus(field)
        page.fill(field, "PL65")
        page.keyboard.press("Enter")
        self.assertEqual(page.evaluate(KEYS_STATE), {"pinned": 2, "focus": "row2"})
        sheet = self.figures(**PHONE)
        sheet.click("#btn-pos")
        sheet.wait_for_function("document.querySelector('#nav-sheet').open")
        sheet.focus("#ns-outline-search")
        sheet.keyboard.press("Enter")
        self.assertTrue(sheet.evaluate("document.querySelector('#nav-sheet').open && OUTLINE_PINNED === null"))

    def test_a_key_that_leaves_a_clicked_field_shows_the_focus_ring_on_the_result(self):
        """The field is clicked with the mouse, which makes the pointer the input the ring answers (html[data-input]); the first
        ↓ - and an Enter that chooses - moves the focus to a result, and from then on the keyboard is the input, so the ring is
        drawn on that row. A press on a row afterwards makes it the pointer again."""
        page = self.figures()
        ring = """() => { const a = document.activeElement, s = getComputedStyle(a);
          return [document.documentElement.dataset.input, a.matches(':focus-visible'), s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0]; }"""
        page.click("#outline-search")
        page.keyboard.type("PL6")
        self.assertEqual(page.evaluate("document.documentElement.dataset.input"), "pointer")
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate("document.activeElement.dataset.index"), "1")
        self.assertEqual(page.evaluate(ring), ["key", True, True])
        page.keyboard.press("Escape")
        page.mouse.click(1, 1)  # a press elsewhere: the pointer again
        self.assertEqual(page.evaluate("document.documentElement.dataset.input"), "pointer")
        page.click("#outline-search")
        page.keyboard.press("Enter")
        self.assertEqual(page.evaluate("[document.activeElement.dataset.index, OUTLINE_PINNED.index]"), ["1", 1])
        self.assertEqual(page.evaluate(ring), ["key", True, True])

    def test_the_filter_is_described_by_its_keys_and_announces_how_many_it_found(self):
        """The field is described by one line of its keys (aria-describedby) - shown under it while it has the focus with a mouse,
        never on a touch screen, where it is still read - and a polite status says the number of results as it is typed, that there
        are none, and nothing for an empty field. The phone sheet's field has its own pair. In English too."""
        for lang, hint, found, none in (
            ("ko", "↓ 결과로 · Enter 첫 결과 · Esc 찾기 칸으로", "결과 3개", "찾은 장·절이 없습니다."),
            (
                "en",
                "↓ to the results · Enter for the first · Esc back to the field",
                "3 results",
                "No chapters or sections found.",
            ),
        ):
            with self.subTest(lang=lang):
                page = self.on("fig", lang=lang)
                self.assertEqual(self.load(page, GROUPED), [8, 0])
                info = """() => { const f = document.querySelector('#outline-search'), h = document.getElementById(f.getAttribute('aria-describedby')),
                  sr = document.getElementById('outline-sr');
                  return {hint: h.textContent, shown: getComputedStyle(h).display !== 'none', live: [sr.getAttribute('role'), sr.getAttribute('aria-live')], said: sr.textContent}; }"""
                self.assertEqual(
                    page.evaluate(info), {"hint": hint, "shown": False, "live": ["status", "polite"], "said": ""}
                )
                page.focus("#outline-search")
                self.assertTrue(page.evaluate(info)["shown"])
                page.fill("#outline-search", "PL6")
                self.assertEqual(page.evaluate(info)["said"], found)
                page.fill("#outline-search", "no such figure")
                self.assertEqual(page.evaluate(info)["said"], none)
                page.fill("#outline-search", "")
                self.assertEqual(page.evaluate(info)["said"], "")
                page.keyboard.press(
                    "ArrowDown"
                )  # an empty field's list takes the focus: the hint goes with the field's focus
                self.assertFalse(page.evaluate(info)["shown"])
        phone = self.figures(**PHONE)
        phone.click("#btn-pos")
        phone.wait_for_function("document.querySelector('#nav-sheet').open")
        phone.focus("#ns-outline-search")
        sheet = """() => { const f = document.querySelector('#ns-outline-search'), h = document.getElementById(f.getAttribute('aria-describedby'));
          return [h.textContent, getComputedStyle(h).position, document.getElementById('ns-outline-sr').textContent]; }"""
        self.assertEqual(phone.evaluate(sheet), ["↓ 결과로 · Enter 첫 결과 · Esc 찾기 칸으로", "absolute", ""])
        phone.fill("#ns-outline-search", "PL64")
        self.assertEqual(phone.evaluate(sheet)[2], "결과 2개")
        self.assertEqual(phone.evaluate("document.getElementById('outline-sr').textContent"), "")
        self.assertFalse(phone.evaluate("getComputedStyle(document.getElementById('outline-hint')).display !== 'none'"))

    def test_the_status_says_a_state_once_not_at_every_keystroke(self):
        """'no such' typed key by key finds nothing from its first letter on: the polite status is written once
        ('찾은 장·절이 없습니다.'), not again at every keystroke - each write was read out again (0.4.34 RC test)."""
        page = self.on("fig")
        self.assertEqual(self.load(page, GROUPED), [8, 0])
        page.evaluate(
            """()=>{const sr=document.getElementById('outline-sr'); window.__srWrites=0;
              new MutationObserver(r=>{window.__srWrites+=r.length;}).observe(sr,{childList:true,characterData:true,subtree:true});}"""
        )
        page.focus("#outline-search")
        page.keyboard.type("qqqq")
        page.wait_for_timeout(100)
        self.assertEqual(page.evaluate("document.getElementById('outline-sr').textContent"), "찾은 장·절이 없습니다.")
        self.assertLessEqual(
            page.evaluate("window.__srWrites"), 2
        )  # set once (a text change may be one or two records)

    def test_a_key_that_an_input_method_or_a_modifier_owns_is_not_ours(self):
        """Korean typing commits its last syllable with Enter (isComposing), and Ctrl+Enter or Shift+↓ are not the filter's:
        none of them chooses or moves."""
        page = self.figures()
        page.fill("#outline-search", "PL64")
        page.focus("#outline-search")
        sent = page.evaluate(
            """() => { const f = document.querySelector('#outline-search'), out = [];
              for (const init of [{key: 'Enter', isComposing: true}, {key: 'ArrowDown', isComposing: true}, {key: 'Enter', keyCode: 229},
                  {key: 'Enter', ctrlKey: true}, {key: 'ArrowDown', shiftKey: true}]) {
                const e = new KeyboardEvent('keydown', Object.assign({bubbles: true, cancelable: true}, init));
                f.dispatchEvent(e); out.push(e.defaultPrevented); }
              return out; }"""
        )
        self.assertEqual(sent, [False] * 5)
        self.assertEqual(page.evaluate(KEYS_STATE), {"pinned": None, "focus": "outline-search"})

    def test_the_sheets_keys_keep_the_sheet_open_until_a_result_is_chosen(self):
        """In the phone's navigation sheet Esc from a result goes back to the field and does not close the sheet (Esc in the
        field does close it, as before); choosing a result with Enter - from the field or on the row - goes there and closes it."""
        page = self.figures(**PHONE)
        field = "#ns-outline-search"
        page.click("#btn-pos")
        page.wait_for_function("document.querySelector('#nav-sheet').open")
        page.fill(field, "PL6")
        page.focus(field)
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate("document.activeElement.dataset.index"), "1")
        page.keyboard.press("Escape")
        settle(page)
        self.assertTrue(page.evaluate("document.querySelector('#nav-sheet').open"))
        self.assertEqual(page.evaluate("document.activeElement.id"), "ns-outline-search")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.wait_for_function("!document.querySelector('#nav-sheet').open")
        self.assertEqual(page.evaluate("OUTLINE_PINNED.index"), 2)
        page.click("#btn-pos")
        page.wait_for_function("document.querySelector('#nav-sheet').open")
        page.focus(field)
        page.keyboard.press("Enter")
        page.wait_for_function("!document.querySelector('#nav-sheet').open")
        self.assertEqual(page.evaluate("OUTLINE_PINNED.index"), 1)

    def test_the_overlay_outline_keeps_to_its_keys(self):
        """Where the outline is an overlay (701-900px), Esc from a result goes back to the field and the overlay stays;
        Esc in the field closes it as before; Enter in the field chooses and the overlay closes."""
        page = self.figures(viewport={"width": 800, "height": 900})
        page.click("#nav-toc-toggle")
        page.wait_for_function("OUTLINE_MID_OPEN")
        page.fill("#outline-search", "PL6")
        page.focus("#outline-search")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Escape")
        self.assertEqual(page.evaluate("[document.activeElement.id, OUTLINE_MID_OPEN]"), ["outline-search", True])
        page.keyboard.press("Escape")
        self.assertFalse(page.evaluate("OUTLINE_MID_OPEN"))
        page.click("#nav-toc-toggle")
        page.wait_for_function("OUTLINE_MID_OPEN")
        page.focus("#outline-search")
        page.keyboard.press("Enter")
        self.assertEqual(page.evaluate("[OUTLINE_PINNED.index, OUTLINE_MID_OPEN]"), [1, False])


class FigurePageList(BrowserBase):
    """A figure document's page list: each page's title, else its outline entry, else the number; a manuscript's and a
    view-only PDF's lists are what they were."""

    WHO = ALICE
    TITLES: dict[str, dict[int, object]] | None = {}

    def setUp(self):
        """viewer_docs' three documents; no page has a title in meta (the server's map titles are taken out) unless a test
        sets TITLES for its document, or sets TITLES to None to see what the server sends."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)
        self.TITLES = {}
        self.hold_pdf, self.held = False, []

    def route(self, route):
        """The meta of a document named in self.TITLES gets those titles in its pages."""
        u = urlparse(route.request.url)
        if u.path == "/api/meta" and self.TITLES is not None:
            key = (parse_qs(u.query).get("doc") or ["ms"])[0]
            return self.forward(MetaTitled(route, self.TITLES.get(key) or {}))
        if u.path == "/pdf" and self.hold_pdf:  # a PDF still on its way: the outline of the document is not read yet
            self.held.append(route)
            return None
        return super().route(route)

    def on(self, doc, **device):
        """The viewer showing document doc, settled."""
        page = self.open(0, init=NO_COACH, **(device or DESKTOP))
        if doc != "ms":
            page.evaluate("k=>switchDoc(k)", doc)
            page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&document.querySelector('#p1')", arg=doc)
            settle(page)
        return page

    ROWS = """sel => [...document.querySelectorAll(sel + ' .pl-row')].map(r => {const s = r.querySelector('.pl-s');
      return {n: r.querySelector('.pl-n').textContent, s: s.textContent, tip: r.dataset.tip || null, h: r.getBoundingClientRect().height,
        cut: s.scrollWidth > s.clientWidth, overflow: getComputedStyle(s).textOverflow, on: r.getAttribute('aria-selected')};})"""

    def open_list(self, page, device, quiet=True):
        """Open the page list the way the device does and return the selector of its rows' box. quiet: wait for the page to
        settle (not while a request is held)."""
        if device is PHONE:
            page.click("#btn-pos")
            page.wait_for_function("document.querySelector('#nav-sheet').open")
            box = "#ns-pages"
        else:
            page.click("#section-page" if device is DESKTOP else "#nav-page")
            page.wait_for_function("!document.querySelector('#page-pop').hidden")
            box = "#page-pop"
        if quiet:
            settle(page)
        return box

    def test_each_page_shows_its_title_on_every_band(self):
        """With titles in meta the rows read '1쪽' + title on a desktop (the popover), a foldable and a phone (the sheet);
        touch rows keep their 44px; a title that fits carries no tooltip."""
        self.TITLES = {"fig": {1: "[후보] PL26 · 핵심 그림", 2: "검토 흐름"}}
        for name, device in (("desktop", DESKTOP), ("fold", FOLD), ("phone", PHONE)):
            with self.subTest(band=name):
                page = self.on("fig", **device)
                box = self.open_list(page, device)
                rows = page.evaluate(self.ROWS, box)
                self.assertEqual(
                    [(r["n"], r["s"], r["tip"]) for r in rows],
                    [("1쪽", "[후보] PL26 · 핵심 그림", None), ("2쪽", "검토 흐름", None)],
                )
                if device is not DESKTOP:
                    self.assertEqual({r["h"] for r in rows}, {44})
                self.assertEqual(
                    page.evaluate("document.querySelector('#page-pop').classList.contains('pl-titled')"),
                    device is not PHONE,
                )

    def test_a_long_title_ends_in_an_ellipsis(self):
        """A title that does not fit its row is cut with an ellipsis on one line, and the row stays one line high; its full
        text is the row's text and - for a hover, and for a long press on touch - its description (data-tip), which a title
        that fits does not carry."""
        long = "[후보] PL99 · " + "아주 긴 그림 제목 " * 12
        self.TITLES = {"fig": {1: long, 2: "짧은 제목"}}
        for name, device in (("desktop", DESKTOP), ("phone", PHONE)):
            with self.subTest(band=name):
                page = self.on("fig", **device)
                rows = page.evaluate(self.ROWS, self.open_list(page, device))
                self.assertEqual(
                    (rows[0]["cut"], rows[0]["overflow"], rows[0]["tip"]), (True, "ellipsis", long.strip())
                )
                self.assertFalse(rows[1]["cut"], rows)
                self.assertEqual(rows[0]["h"], rows[1]["h"])

    def test_without_a_meta_title_the_outline_entry_names_the_page(self):
        """No title in meta (a server that has none yet): the page shows the outline entry that points at it - the
        deepest of them - and a page no entry points at shows its number only. Titles that arrive later win."""
        page = self.on("fig")
        page.evaluate(
            """() => {OUTLINE_ENTRIES = [{title: '묶음', page: 1, depth: 0, frac: 0, number: ''},
              {title: 'PL1 · 첫 그림', page: 1, depth: 1, frac: 0, number: ''}];
              OUTLINE_DOC = DOC; OUTLINE_BUILD = META.pages_build; renderOutline();}"""
        )
        rows = page.evaluate(self.ROWS, self.open_list(page, DESKTOP))
        self.assertEqual([(r["n"], r["s"]) for r in rows], [("1쪽", "PL1 · 첫 그림"), ("2쪽", "")])
        self.assertIsNone(rows[1]["tip"])
        page.keyboard.press("Escape")
        page.evaluate("META.pages[1].title = '메타 제목'; META.pages[0].title = '메타가 이긴다'")
        rows = page.evaluate(self.ROWS, self.open_list(page, DESKTOP))
        self.assertEqual([r["s"] for r in rows], ["메타가 이긴다", "메타 제목"])

    def test_the_servers_map_titles_name_the_pages(self):
        """With nothing stubbed the server's own `pages[i].title` - the figure map's page title (ADR-0022) - names each
        page of a figure document's list."""
        self.TITLES = None
        page = self.on("fig")
        titles = page.evaluate("META.pages.map(p => p.title || '')")
        self.assertTrue(all(titles), titles)
        rows = page.evaluate(self.ROWS, self.open_list(page, DESKTOP))
        self.assertEqual([r["s"] for r in rows], titles)

    def test_a_bad_title_is_no_title(self):
        """A title that is not text or is blank (a server answering something else) falls back to the entry or the number
        - and nothing throws."""
        self.TITLES = {"fig": {1: 7, 2: "   "}}
        page = self.on("fig")
        rows = page.evaluate(self.ROWS, self.open_list(page, DESKTOP))
        self.assertEqual([(r["n"], r["s"]) for r in rows], [("1쪽", ""), ("2쪽", "")])

    def test_a_manuscript_and_a_view_only_pdf_list_what_they_listed(self):
        """A LaTeX manuscript's page list names its sections from the outline whatever meta carries (its rows have no
        tooltip and the popover is the narrow one); a view-only PDF's lists page numbers only (no title reaches it, nor an
        outline entry: only a figure document names its pages by the outline)."""
        self.TITLES = {"ms": {1: "not a section", 2: "nor this"}}
        page = self.on("ms")
        page.evaluate(
            """() => {OUTLINE_ENTRIES = [{title: 'Introduction', page: 1, depth: 0, frac: 0, number: '1'},
              {title: 'Methods', page: 2, depth: 0, frac: 0, number: '2'}]; renderOutline();}"""
        )
        rows = page.evaluate(self.ROWS, self.open_list(page, DESKTOP))
        self.assertEqual(
            [(r["n"], r["s"], r["tip"]) for r in rows], [("1쪽", "1 Introduction", None), ("2쪽", "2 Methods", None)]
        )
        self.assertFalse(page.evaluate("document.querySelector('#page-pop').classList.contains('pl-titled')"))
        pdf = self.on("rv")
        rows = pdf.evaluate(self.ROWS, self.open_list(pdf, DESKTOP))
        self.assertEqual([r["s"] for r in rows], [""] * len(rows))
        self.assertFalse(pdf.evaluate("document.querySelector('#page-pop').classList.contains('pl-titled')"))

    def test_a_list_opened_while_the_outline_is_read_names_nothing_from_the_old_document(self):
        """On a switch the document, meta and page list move at once and the outline arrives later. A list opened in between
        named a figure's pages by the manuscript's outline (and stayed so); now it shows numbers until the outline of the
        figure is read, is drawn again then - still open, its focus on the row it was on - and the sheet's outline section
        does not show the old document's rows meanwhile."""
        fig_pdf = outline_pdf(2, [("그림 하나", 0, []), ("그림 둘", 1, [])])
        for name, device in (("desktop", DESKTOP), ("phone", PHONE)):
            with self.subTest(band=name):
                self.hold_pdf, self.held = False, []
                page = self.on("ms", **device)
                page.evaluate(
                    """() => {OUTLINE_ENTRIES = [{title: '옛 서론', page: 1, depth: 0, frac: 0, number: '1'},
                      {title: '옛 방법', page: 2, depth: 0, frac: 0, number: '2'}];
                      OUTLINE_DOC = DOC; OUTLINE_BUILD = META.pages_build; renderOutline();}"""
                )
                self.hold_pdf = True
                page.evaluate("k => {switchDoc(k);}", "fig")
                page.wait_for_function("OUTLINE_DOC === 'fig' && DOC === 'fig' && META.doc === 'fig'")
                self.assertEqual(page.evaluate("OUTLINE_ENTRIES.length"), 0)
                box = self.open_list(page, device, quiet=False)
                self.assertEqual([r["s"] for r in page.evaluate(self.ROWS, box)], ["", ""])
                if device is PHONE:
                    self.assertFalse(page.is_visible("#ns-outline"))
                page.focus("%s .pl-row[data-page='2']" % box)
                self.held[0].fulfill(status=200, headers={"content-type": "application/pdf"}, body=fig_pdf)
                page.wait_for_function("OUTLINE_ENTRIES.length === 2", timeout=15000)
                self.hold_pdf = False
                settle(page)
                self.assertEqual([r["s"] for r in page.evaluate(self.ROWS, box)], ["그림 하나", "그림 둘"])
                self.assertEqual(page.evaluate("document.activeElement.dataset.page"), "2")
                self.assertTrue(page.is_visible(box))

    def test_a_long_press_on_a_cut_title_shows_the_whole_title_and_a_tap_still_goes_to_the_page(self):
        """Touch has no native tooltip: a row whose title is cut carries it as its description, and holding a finger on the row
        shows it - over the sheet too, which is in the top layer - without going to the page; a tap goes to the page."""
        long = "[후보] PL99 · " + "아주 긴 그림 제목 " * 12
        self.TITLES = {"fig": {1: long, 2: "짧은 제목"}}
        for name, device in (("fold", FOLD), ("phone", PHONE)):
            with self.subTest(band=name):
                page = self.on("fig", **device)
                box = self.open_list(page, device)
                row = "%s .pl-row[data-page='%d']" % (box, 1)
                cdp = page.context.new_cdp_session(page)
                b = page.locator(row).bounding_box()
                point = {"x": b["x"] + b["width"] / 2, "y": b["y"] + b["height"] / 2, "id": 0}
                cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [point]})
                page.wait_for_function("!document.querySelector('#tip').hidden", timeout=8000)
                shown = page.evaluate(
                    "() => {const t = document.querySelector('#tip'); return [t.textContent, t.matches(':popover-open')];}"
                )
                self.assertEqual(shown, [long.strip(), True])
                cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                nothing_follows(page)
                self.assertTrue(page.is_visible(box), "the long press went to the page")
                self.assertIsNone(page.get_attribute("%s .pl-row[data-page='2']" % box, "data-tip"))
                page.tap("%s .pl-row[data-page='2']" % box)
                page.wait_for_function("OUTLINE_ACTIVE_PAGE === 2 || topAnchor().page === 2", timeout=8000)

    def test_a_long_press_held_for_seconds_does_not_go_to_the_page_when_it_lets_go(self):
        """The click that ends a long press is swallowed for the press that opened the description, however long it was held:
        the window that was set when the box opened (900 ms) was over for a finger held ~1.6 s, and its release went to the
        page. A press that is let go at once after the box opens, one held 1.6 s and one held ~3 s all stay on the list; the
        next tap on a row goes - the swallowing does not outlive the press's own click."""
        long = "[후보] PL99 · " + "아주 긴 그림 제목 " * 12
        self.TITLES = {"fig": {1: long, 2: "짧은 제목"}}
        for name, device in (("fold", FOLD), ("phone", PHONE)):
            with self.subTest(band=name):
                page = self.on("fig", **device)
                box = self.open_list(page, device)
                row = "%s .pl-row[data-page='%d']" % (box, 1)
                cdp = page.context.new_cdp_session(page)
                b = page.locator(row).bounding_box()
                point = {"x": b["x"] + b["width"] / 2, "y": b["y"] + b["height"] / 2, "id": 0}
                for held_ms in (0, 1100, 2500):  # past the moment the box opens (500 ms)
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [point]})
                    page.wait_for_function("!document.querySelector('#tip').hidden", timeout=8000)
                    page.wait_for_timeout(held_ms)
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                    nothing_follows(page)
                    self.assertTrue(page.is_visible(box), "a press held %d ms past the box went to the page" % held_ms)
                    self.assertEqual(page.evaluate("topAnchor().page"), 1)
                page.tap("%s .pl-row[data-page='2']" % box)
                page.wait_for_function("OUTLINE_ACTIVE_PAGE === 2 || topAnchor().page === 2", timeout=8000)

    def test_a_cancelled_long_press_does_not_swallow_the_next_tap(self):
        """The description a long press opens arms the click swallowing; when the browser takes the touch away (a pointercancel)
        no click follows and the hold must go with it: a tap on another row at once - inside the 900 ms the hold was armed for -
        still goes to its page. The same press let go in the ordinary way does swallow its own click."""
        long = "[후보] PL99 · " + "아주 긴 그림 제목 " * 12
        self.TITLES = {"fig": {1: long, 2: "짧은 제목"}}
        for name, device in (("fold", FOLD), ("phone", PHONE)):
            with self.subTest(band=name):
                page = self.on("fig", **device)
                box = self.open_list(page, device)
                row = "%s .pl-row[data-page='%d']" % (box, 1)
                cdp = page.context.new_cdp_session(page)
                b = page.locator(row).bounding_box()
                point = {"x": b["x"] + b["width"] / 2, "y": b["y"] + b["height"] / 2, "id": 0}
                cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [point]})
                page.wait_for_function("!document.querySelector('#tip').hidden", timeout=8000)
                self.assertTrue(page.evaluate("SWALLOW_CLICK > Date.now() && SWALLOW_CLICK === TIP_HOLD"))
                cdp.send("Input.dispatchTouchEvent", {"type": "touchCancel", "touchPoints": []})
                page.wait_for_function("SWALLOW_CLICK === 0 && TIP_HOLD === 0", timeout=3000)
                page.tap("%s .pl-row[data-page='2']" % box)
                page.wait_for_function("OUTLINE_ACTIVE_PAGE === 2 || topAnchor().page === 2", timeout=8000)

    def test_choosing_a_titled_row_still_goes_to_its_page(self):
        """A row with a title is the row it was: choosing it goes to the page at once and closes the list."""
        self.TITLES = {"fig": {1: "첫 그림", 2: "둘째 그림"}}
        page = self.on("fig")
        self.open_list(page, DESKTOP)
        page.click("#page-pop .pl-row[data-page='2']")
        page.wait_for_function("document.querySelector('#page-pop').hidden")
        page.wait_for_function("OUTLINE_ACTIVE_PAGE===2")
        self.assertEqual(page.evaluate("OUTLINE_ACTIVE_PAGE"), 2)
