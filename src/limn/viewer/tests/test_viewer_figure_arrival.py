"""Arriving at a figure page (docs/handbook/viewer.md §그림 쪽 도착, issue #345 item 2).

A figure page whose map names its figure body (the element `<figure>/@figure`, meta `figure_top`) is arrived at by its
figure: the outline, a page field, the page list and a card's [보기] put the figure's top edge under the free PDF area's
top with up to 24 pt of the page above it (the figure's own label line), not lower than the element above it. The page's
head and text box, above it, used to push the figure below the first screen. The same arrival again while the pages rest
on the figure goes to the page's top, and once more to the figure. A page without a figure body is arrived at by its top,
as before. Arriving at the figure puts the 160 px reading line inside it, so the section strip, the page count, the keys
1-5 and the verdict panel name the arrived page, and the keys wait for the glide as they do for every jump.

The document: seven tall portrait pages (612 x 1152 pt). Pages 1-4 have a head and a text box above a figure body at 55%
of the page and a caption under it; page 5's body starts at the page's top, with nothing above it; page 6 is a figure page
whose map names no body; page 7 is a list page (no verdict).

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_figure_arrival.py
"""

import json
from unittest import mock

from limn.pins.location import source as pick_source

import helpers_figure
from helpers import blank_png, ps, split_resp
from helpers_access import ALICE, talk_to
from helpers_browser import VIEWPORTS, BrowserBase, settle

WORDS = {
    "format": "limn-verdicts/1",
    "page": True,
    "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}],
}
N_PAGES = 7
BODY_PAGES = (1, 2, 3, 4)  # the pages whose map names a figure body under a head and a text box
TOP_BODY = 5  # the page whose figure body starts at its top, nothing above it
PAGE_PNG = (1275, 2400)  # 612 x 1152 pt at 150 dpi: taller than every screen here
HEAD, TEXT, BODY, CAPTION = (
    (0.04, 0.04, 0.92, 0.05),
    (0.04, 0.12, 0.92, 0.38),
    (0.04, 0.55, 0.8, 0.25),
    (0.04, 0.82, 0.92, 0.08),
)
TOUCH = {"is_mobile": True, "has_touch": True, "device_scale_factor": 2}
SIZES = {
    "desktop 1440x900": VIEWPORTS["desktop 1440x900"],
    "fold inner 841x673": VIEWPORTS["fold inner 841x673"],
    "fold inner 882x1104": dict(TOUCH, viewport={"width": 882, "height": 1104}),
    "tablet 1024x768": VIEWPORTS["tablet 1024x768"],
    "tablet 768x1024": VIEWPORTS["tablet 768x1024"],
}
WIDE = {"viewport": {"width": 1920, "height": 1080}}  # the verdict panel beside the pages
# Whether the pages have rested for ten frames (a jump's glide is over).
RESTING = """() => {const L = document.querySelector('#left'), w = window.__rest || (window.__rest = {top: -1, n: 0});
  if (L.scrollTop === w.top) w.n++; else {w.top = L.scrollTop; w.n = 0;} if (w.n < 10) return false; window.__rest = null; return true;}"""
# Where the pages stand for page n: the scroll, page n's figure arrival, its figure's top edge and its page's top under the
# free area's top (px), the room the arrival keeps above the figure, and the page the reading line, the page count, the
# keys and the panel name.
WHERE = """n => {const L = document.querySelector('#left'), pg = document.getElementById('p' + n), m = META.pages[n - 1],
    r = pg.getBoundingClientRect(), a = selPopArea(), p = document.getElementById('pv-panel');
  const room = typeof m.figure_top === 'number' ? Math.max(8, Math.min(24 * r.height / m.pt_h, (m.figure_top - (m.figure_above || 0)) * r.height)) : null;
  return {top: L.scrollTop, arrive: figureTop(n), fig: typeof m.figure_top === 'number' ? r.top + m.figure_top * r.height - a.top : null,
    page: r.top - L.getBoundingClientRect().top - L.clientTop, room, reading: pvReadingPage(), keys: pvKeysPage(pvReadingPage()),
    count: document.getElementById('nav-page').textContent, panel: p ? +p.dataset.page : null};}"""


class FigurePages(BrowserBase):
    """The three viewer documents of helpers_figure.viewer_docs, the figure rebuilt as seven tall pages (module docstring),
    its word file asking for page lines; picks on the figure reach the real handler."""

    def setUp(self):
        super().setUp()
        _ms, self.fig, _rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        (self.fig.main.parent / "figures.limnverdicts.json").write_text(json.dumps(WORDS, ensure_ascii=False), "utf-8")

        def page(i):
            fid = "F%02d" % i
            root = {"id": fid, "frac": [0, 0, 1, 1], "src": {"file": "src/B2_calendar.py", "lo": 12, "hi": 140}}
            if i == N_PAGES:
                return {
                    "page": i,
                    "figure": "LIST",
                    "title": "목록",
                    "verdict": False,
                    "elements": [dict(root, id="LIST")],
                }
            parts = [("@head", HEAD), ("@text", TEXT), ("@caption", CAPTION)] + (
                [("@figure", BODY)] if i in BODY_PAGES else []
            )
            if i == TOP_BODY:
                parts = [("@figure", (0.04, 0.0, 0.8, 0.3)), ("@caption", CAPTION)]
            kids = [{"id": fid + "/" + k, "parent": fid, "frac": list(f)} for k, f in parts]
            return {"page": i, "figure": fid, "title": "[후보] PL%d · 월별 효과" % (10 + i), "elements": [root, *kids]}

        fmap = {"format": "limn-figure-map/1", "pdf": "figures.pdf", "pdf_sha256": "0" * 64, "pages": []}
        fmap["pages"] = [page(i) for i in range(1, N_PAGES + 1)]
        d = helpers_figure.write_build(self.fig, helpers_figure.BUILD2, fmap, pages=N_PAGES)
        for i in range(1, N_PAGES + 1):
            (d / ("page-%d.png" % i)).write_bytes(blank_png(*PAGE_PNG))
        patch = mock.patch.object(pick_source, "region_text", return_value="")  # pdftotext answers no text
        patch.start()
        self.addCleanup(patch.stop)

    def route(self, route):
        rq = route.request
        if rq.url.endswith("/api/pick") and json.loads(rq.post_data or "{}").get("doc") == "fig":
            return self.forward(route)
        return super().route(route)

    def call(self, method, path, body=None):
        """One request to the handler as Alice -> (status, JSON)."""
        data = json.dumps(body).encode() if body is not None else b""
        h = {"Host": "127.0.0.1:18999", **ALICE}
        if data:
            h.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
        if method == "POST":
            h["Origin"] = "http://127.0.0.1:18999"
        raw = ("%s %s HTTP/1.1\r\n" % (method, path) + "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n").encode()
        code, _, out = split_resp(talk_to(ps, raw + data))
        return code, json.loads(out or b"null")

    def verdict(self, n, key):
        """A verdict of Alice's on page n's whole figure, made through the API as the page line makes it; its id."""
        meta = self.call("GET", "/api/meta?doc=fig")[1]
        pg = meta["pages"][n - 1]
        pick = {"doc": "fig", "page": n, "x0": 0, "y0": 0, "x1": pg["pt_w"], "y1": pg["pt_h"], "frac": [0, 0, 1, 1]}
        code, d = self.call("POST", "/api/pick", {**pick, "pdf_build": meta["pages_build"]})
        self.assertEqual(code, 200, d)
        body = {k: d[k] for k in helpers_figure.SAVE_LINE if d.get(k) is not None}
        body.update(scope=d.get("default_level"), doc="fig", note="", kind_req="fix", assignee="agent", verdict=key)
        code, made = self.call("POST", "/api/pin", body)
        self.assertEqual(code, 200, made)
        return made["id"]

    def on(self, device, n_open=0):
        """The viewer showing the figure document on device, settled at its top."""
        page = self.open(n_open, **device)
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("()=>DOC==='fig'&&META&&META.doc==='fig'&&document.querySelector('#p%d')" % N_PAGES)
        settle(page)
        return page

    def rest(self, page):
        page.wait_for_function(RESTING, polling="raf", timeout=10000)
        settle(page)

    def landed(self, page):
        """The pages at rest after an arrival and its settling (pages.js arrivalSettle): rested, then rested again once
        any correction it started has run."""
        self.rest(page)
        page.wait_for_timeout(300)
        self.rest(page)

    def to_top(self, page):
        """The pages at the document's top, as a hand puts them (no arrival watching)."""
        page.evaluate("()=>{PV_HAND(); document.querySelector('#left').scrollTop = 0;}")
        self.rest(page)

    def page_list(self, page, n):
        """Page n's row of the page list, opened from the page count that shows (the section strip's or the nav bar's)."""
        count = (
            page.locator("#section-page") if page.locator("#section-page").is_visible() else page.locator("#nav-page")
        )
        count.click()
        page.locator('#page-pop [data-act="page-go"][data-page="%d"]' % n).click()
        self.rest(page)

    def page_field(self, page, n):
        """Page n typed into the page list's field and Enter pressed."""
        count = (
            page.locator("#section-page") if page.locator("#section-page").is_visible() else page.locator("#nav-page")
        )
        count.click()
        page.locator("#page-pop-in").fill(str(n))
        page.keyboard.press("Enter")
        self.rest(page)

    def outline(self, page, n):
        """An outline entry of page n, as PDF.js would give it (the fixture's stub PDF has no outline), and its pick."""
        page.evaluate("n=>{OUTLINE_ENTRIES=[{page:n,frac:0,title:'F'+n,level:0}]; pickOutline(0);}", n)
        self.rest(page)

    def at_figure(self, where, n):
        """The pages rest on page n's figure arrival: the figure's top edge the arrival's room under the free area's
        top, and the reading line, the page count and the keys on page n."""
        self.assertIsNotNone(where["arrive"], where)
        self.assertLessEqual(abs(where["top"] - where["arrive"]), 2, where)
        self.assertLessEqual(abs(where["fig"] - where["room"]), 2, where)
        self.assertEqual((where["reading"], where["keys"]), (n, n), where)
        self.assertTrue(where["count"].startswith("%d " % n), where)

    def at_top(self, where, n):
        """The pages rest on page n's top, the reading line, the page count and the keys on page n."""
        self.assertLessEqual(abs(where["page"]), 2, where)
        self.assertEqual(where["reading"], n if n != N_PAGES else 0, where)
        self.assertTrue(where["count"].startswith("%d " % n), where)


class FigureArrival(FigurePages):
    """Each way to a page, each device, the re-press, a page without a body, the keys, the panel and a phone."""

    def test_every_way_to_a_page_arrives_at_its_figure_on_each_device(self):
        """On a desktop, the two unfolded foldables and the two tablets the page list, a page field, the outline and a
        verdict card's [보기] each arrive at the figure of a figure page: its top edge under the free area's top with
        the figure's label line above it, the reading line, the page count and the keys on that page."""
        pid = self.verdict(4, "보류")
        for name, device in SIZES.items():
            with self.subTest(device=name):
                page = self.on(device, n_open=1)
                self.page_list(page, 2)
                self.at_figure(page.evaluate(WHERE, 2), 2)
                self.page_field(page, 3)
                self.at_figure(page.evaluate(WHERE, 3), 3)
                self.outline(page, 1)
                self.at_figure(page.evaluate(WHERE, 1), 1)
                if name.startswith("desktop"):
                    page.locator('#list .pin.card[data-id="%d"] button.b-view' % pid).click()
                else:  # the pin list is in a sheet: its [보기]'s own call
                    page.evaluate("id=>jumpPin(id)", pid)
                self.rest(page)
                self.at_figure(page.evaluate(WHERE, 4), 4)
                page.context.close()

    def test_the_same_entry_again_goes_to_the_page_top_and_once_more_to_the_figure(self):
        """The page list's page 2 pressed three times: its figure, its top, its figure; a card's [보기] pressed twice: the
        figure, then the page's top. A page's top keeps the head and the text box in view, for the author who wants it."""
        pid = self.verdict(3, "채택")
        page = self.on(SIZES["desktop 1440x900"], n_open=1)
        self.page_list(page, 2)
        self.at_figure(page.evaluate(WHERE, 2), 2)
        self.page_list(page, 2)
        self.at_top(page.evaluate(WHERE, 2), 2)
        self.page_list(page, 2)
        self.at_figure(page.evaluate(WHERE, 2), 2)
        view = page.locator('#list .pin.card[data-id="%d"] button.b-view' % pid)
        view.click()
        self.rest(page)
        self.at_figure(page.evaluate(WHERE, 3), 3)
        view.click()
        self.rest(page)
        self.at_top(page.evaluate(WHERE, 3), 3)

    def test_a_page_without_a_figure_body_arrives_at_its_top_as_before(self):
        """Page 6 (a figure page whose map names no body) and page 7 (a list page) arrive at their tops, from the page list
        and the outline, and stay there when pressed again; their meta has no figure_top."""
        page = self.on(SIZES["tablet 1024x768"])
        self.assertEqual(page.evaluate("()=>[6,7].map(n=>'figure_top' in META.pages[n-1])"), [False, False])
        for n in (6, 7):
            with self.subTest(page=n):
                self.page_list(page, n)
                self.at_top(page.evaluate(WHERE, n), n)
                self.page_list(page, n)
                self.at_top(page.evaluate(WHERE, n), n)
                self.outline(page, n)
                self.at_top(page.evaluate(WHERE, n), n)

    def test_a_body_at_the_page_s_top_keeps_no_room_above_the_page_at_a_large_zoom(self):
        """Page 5's body starts at its top, nothing above it: zoomed in as far as it goes on the short foldable, its
        arrival keeps no more room than the page has above the body, so the page's top stays under the free area's top
        and the reading line, the page count and the keys are on page 5, not on page 4 above it."""
        page = self.on(SIZES["fold inner 841x673"])
        page.evaluate("()=>zoomTo(K*10)")
        settle(page)
        self.page_list(page, TOP_BODY)
        where = page.evaluate(WHERE, TOP_BODY)
        self.assertLessEqual(abs(where["top"] - where["arrive"]), 2, where)
        self.assertLessEqual(where["page"], 8 + 2, where)
        self.assertEqual((where["reading"], where["keys"]), (TOP_BODY, TOP_BODY), where)
        self.assertTrue(where["count"].startswith("%d " % TOP_BODY), where)

    def test_a_forward_far_arrival_lands_on_the_figure_though_the_layout_above_moves_on_the_way(self):
        """Many verdicts, a digit saved on page 1, then forward to page 4 by its card's [보기], by the page list and by a
        page field - each while the line of a page between grows by 60px as the glide starts, as a save's list reload
        redraws hundreds of lines (and, past a second's stall, gives scroll anchoring back): the glide reckoned its place
        before, so it rested 60px off. Once the pages rest the arrival measures again and glides the rest (#345). On the
        short foldable and a desktop."""
        for n in range(1, 6):
            for key in ("채택", "보류", "삭제"):
                self.verdict(n, key)
        pid = self.verdict(4, "보류")
        grow = """([go, n]) => {(0, eval)(go); const l = document.querySelector('#doc .pv[data-page="' + n + '"]');
          l.style.paddingBottom = (parseFloat(l.style.paddingBottom || '0') + 60) + 'px';}"""
        view = "jumpPin(%d)" % pid
        for name in ("fold inner 841x673", "desktop 1440x900"):
            with self.subTest(device=name):
                page = self.on(SIZES[name], n_open=16)
                had = page.evaluate("()=>OPEN_ALL.length")
                key = page.evaluate(
                    "()=>{const a=(pageVerdictPins().get(1)||[])[0]; return a&&verdictOf(a)==='채택'?'2':'1';}"
                )
                page.locator("#left").focus()
                page.keyboard.press(key)  # a new verdict, not the press that takes the current one back
                page.wait_for_function("n=>OPEN_ALL.length===n+1", arg=had)
                settle(page)
                for i, go in enumerate((view, "goPage(4)", "$('#jump').value='4'; goPage()")):
                    self.to_top(page)
                    page.evaluate(grow, [go, 2 + i % 2])
                    self.landed(page)
                    self.at_figure(page.evaluate(WHERE, 4), 4)
                page.context.close()

    def test_a_person_who_scrolls_while_it_glides_is_not_pulled_back(self):
        """The layout above moves as the arrival glides and the person scrolls the pages themselves on the way: once they
        rest the arrival lets go and leaves them where the person put them."""
        page = self.on(SIZES["desktop 1440x900"])
        page.evaluate(
            """() => {goPage(4); const l = document.querySelector('#doc .pv[data-page="2"]'); l.style.paddingBottom = '60px';}"""
        )
        page.wait_for_function("()=>document.querySelector('#left').scrollTop>1500")
        page.mouse.move(700, 500)
        page.mouse.wheel(0, -400)
        self.landed(page)
        still = page.evaluate("()=>document.querySelector('#left').scrollTop")
        page.wait_for_timeout(600)
        settle(page)
        self.assertEqual(page.evaluate("()=>[document.querySelector('#left').scrollTop, ARRIVAL]"), [still, None])
        self.assertGreater(abs(still - page.evaluate("()=>figureTop(4)")), 50)

    def test_a_key_waits_for_the_glide_then_judges_the_arrived_page(self):
        """A digit pressed in the same task as the page list's jump to page 3's figure, before its first scroll, saves
        nothing and the status line says the pages are on their way; pressed once they rest, it saves its verdict on page
        3's figure - the page the reading line falls on."""
        page = self.on(SIZES["desktop 1440x900"])
        page.evaluate(
            "()=>{goPage(3); document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'2',bubbles:true}));}"
        )
        self.rest(page)
        self.assertEqual(self.call("GET", "/api/pins?all=1")[1], [])
        self.assertTrue(page.evaluate("()=>LINE.some(n=>n.title.includes('쪽으로 가는 중'))"))
        self.at_figure(page.evaluate(WHERE, 3), 3)
        page.evaluate("()=>document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'2',bubbles:true}))")
        page.wait_for_function("()=>OPEN_ALL.length===1")
        settle(page)
        (made,) = self.call("GET", "/api/pins?all=1")[1]
        self.assertEqual((made["page"], made["verdict"], made["el"]["path"]), (3, "보류", ["F03"]), made)

    def test_the_panel_beside_the_pages_shows_the_arrived_page(self):
        """On a wide desktop with the verdict panel beside the pages, the page list and a card's [보기] arrive at the figure
        and the panel shows that page."""
        pid = self.verdict(2, "채택")
        page = self.on(WIDE, n_open=1)
        self.assertTrue(page.evaluate("()=>PV_SIDE"))
        self.page_list(page, 4)
        where = page.evaluate(WHERE, 4)
        self.at_figure(where, 4)
        self.assertEqual(where["panel"], 4, where)
        page.locator('#list .pin.card[data-id="%d"] button.b-view' % pid).click()
        self.rest(page)
        where = page.evaluate(WHERE, 2)
        self.at_figure(where, 2)
        self.assertEqual(where["panel"], 2, where)

    def test_a_phone_arrives_at_the_figure_from_its_navigation_sheet(self):
        """Smoke: on a phone the navigation sheet's page field arrives at page 3's figure and the reading line is there."""
        page = self.on(VIEWPORTS["phone 390x844"])
        page.evaluate("()=>{$('#ns-page-in').value='3'; navGo();}")
        self.rest(page)
        where = page.evaluate(WHERE, 3)
        self.assertLessEqual(abs(where["top"] - where["arrive"]), 2, where)
        self.assertEqual(where["reading"], 3, where)
