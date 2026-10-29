"""A long outline and a figure document's page list (docs/handbook/viewer.md §모바일 레이아웃, §쪽 목록).

The viewer reads the first OUTLINE_MAX_ENTRIES entries of a PDF's outline, down to five levels, and says at the end of the
outline - and of its filter's results - how many entries it left unread; a figure document's page list shows each page's
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

    def test_the_lookup_stays_fast_where_many_entries_share_a_page(self):
        """The cost of one lookup at 2,000 entries: all distinct spots on one page (the pairwise rule took ~26 ms), all at one
        spot, forty to a spot, and fifty pages of forty. Each under 5 ms (measured under 1) and equal to the old answer."""
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
        """Fulfil the route with the handler's JSON answer, the titles merged into its pages."""
        data = json.loads(body)
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


class LongOutline(BrowserBase):
    """The outline of a PDF with more entries than the viewer reads: the first ones whole, the rest counted and said."""

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


def flatten(tree):
    """Every node of an outline tree, parents before children."""
    for node in tree:
        yield node
        yield from flatten(node[2])


def grouped_titles(n):
    """The titles of grouped_tree(n, 2) in document order."""
    return [node[0] for node in flatten(grouped_tree(n, 2))]


class FigurePageList(BrowserBase):
    """A figure document's page list: each page's title, else its outline entry, else the number; a manuscript's and a
    view-only PDF's lists are what they were."""

    WHO = ALICE
    TITLES: dict[str, dict[int, object]] = {}

    def setUp(self):
        """viewer_docs' three documents; no page has a title in meta yet."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)
        self.TITLES = {}
        self.hold_pdf, self.held = False, []

    def route(self, route):
        """The meta of a document named in self.TITLES gets those titles in its pages."""
        u = urlparse(route.request.url)
        if u.path == "/api/meta":
            key = (parse_qs(u.query).get("doc") or ["ms"])[0]
            if self.TITLES.get(key):
                return self.forward(MetaTitled(route, self.TITLES[key]))
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

    def test_choosing_a_titled_row_still_goes_to_its_page(self):
        """A row with a title is the row it was: choosing it goes to the page at once and closes the list."""
        self.TITLES = {"fig": {1: "첫 그림", 2: "둘째 그림"}}
        page = self.on("fig")
        self.open_list(page, DESKTOP)
        page.click("#page-pop .pl-row[data-page='2']")
        page.wait_for_function("document.querySelector('#page-pop').hidden")
        page.wait_for_function("OUTLINE_ACTIVE_PAGE===2")
        self.assertEqual(page.evaluate("OUTLINE_ACTIVE_PAGE"), 2)
