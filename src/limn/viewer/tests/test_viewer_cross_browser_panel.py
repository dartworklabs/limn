"""The page verdict panel and the outline's follow in bundled desktop Firefox and WebKit (docs/handbook/viewer.md §판정 패널,
§모바일 레이아웃; issue #335).

test_viewer_verdict_panel.py and test_viewer_outline_cap.py's OutlineFollow pin these down in Chromium. This file runs the
flows whose engine part differs - sticky placement, the room's bar, the keys and the focus moving inside and out of the panel,
the wheel and PageDown over it, content-visibility on far summaries, the pointer, wheel and grip holds on the outline - once
in each other engine, in a few tests sized for CI. The fixture is PanelBase's: helpers_figure.viewer_docs with the figure
rebuilt as five portrait pages (612 x 792 pt) that take a verdict, on a 1920 x 1080 desktop (444px of room with the pin panel
open, so the panel is on); the outline tests read the manuscript with a 120-row outline at CI's 1400 x 850. Desktop WebKit
does not stand for a physical iOS or macOS Safari.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_cross_browser_panel.py
"""

import json
import unittest
from unittest import mock
from urllib.parse import urlparse

from limn.pins.location import source as pick_source

import helpers_figure
from helpers import blank_png, ps, split_resp
from helpers_access import ALICE, talk_to
from helpers_browser import BrowserBase, nothing_follows, settle
from helpers_outline import grouped_tree

WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}]}
N_PAGES = 5
WIDE = {"viewport": {"width": 1920, "height": 1080}}
DESKTOP = {"viewport": {"width": 1400, "height": 850}}
OUTLINE_OPEN = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1},outlineClosed:false}))}catch(e){}"
# What the pages' column holds besides the pages: lines under pages, summaries, the panel - and the body's class.
SHAPE = """() => ({beside: document.body.classList.contains('pv-beside'), panel: !!document.getElementById('pv-panel'),
  lines: document.querySelectorAll('#doc .pgw>.pv').length, sums: document.querySelectorAll('#doc .pv-sum').length})"""
# The panel's page, its text and whether its reason popover is open.
PANEL = """() => {const p = document.getElementById('pv-panel'); return p && {page: +p.dataset.page,
  text: p.innerText.replace(/\\s+/g, ' ').trim(), pop: !!p.querySelector(':scope>.pv-pop')};}"""
# The focused element: its action, its line's page, whether it is in the panel or the pin panel, and its focus ring.
FOCUS = """() => {const a = document.activeElement; if (!a || a === document.body) return null; const l = a.closest('#doc .pv'), c = getComputedStyle(a);
  return {act: a.dataset.act || '', id: a.id || '', page: l ? +l.dataset.page : 0, panel: !!a.closest('#pv-panel'), right: !!a.closest('#right'),
    ring: a.matches(':focus-visible') && c.outlineStyle !== 'none' && parseFloat(c.outlineWidth) > 0};}"""
# The boxes between the focused element and the panel that clip, which its focus ring passes (none: the ring shows whole).
RING_CUT = """() => {const f = document.activeElement, c = getComputedStyle(f), out = parseFloat(c.outlineWidth) + parseFloat(c.outlineOffset), r = f.getBoundingClientRect(), hit = [];
  for (let e = f.parentElement; e && e.id !== 'left'; e = e.parentElement) {const s = getComputedStyle(e); if (s.overflowX === 'visible' && s.overflowY === 'visible') continue;
    const b = e.getBoundingClientRect(); if (r.left - out < b.left || r.right + out > b.right || r.top - out < b.top || r.bottom + out > b.bottom) hit.push(e.id || e.className);}
  return hit;}"""
# Brings page n's top to off px under the PDF area's top, as a hand on the wheel (not a jump's glide).
TO = """([n, off]) => {PV_HAND(); const L = document.querySelector('#left'); L.scrollTop += document.getElementById('p' + n).getBoundingClientRect().top - L.getBoundingClientRect().top - off;}"""
# Whether the pages have rested for ten frames (a smooth scroll is over).
RESTING = """() => {const L = document.querySelector('#left'), w = window.__rest || (window.__rest = {top: -1, n: 0});
  if (L.scrollTop === w.top) w.n++; else {w.top = L.scrollTop; w.n = 0;} if (w.n < 10) return false; window.__rest = null; return true;}"""
TOP = "()=>Math.round(document.querySelector('#left').scrollTop)"
# Where every page's block stands in the column and how tall it is.
BLOCKS = """() => {const d = document.querySelector('#doc').getBoundingClientRect().top;
  return [...document.querySelectorAll('#doc .pgw')].map(w => {const r = w.getBoundingClientRect(); return [Math.round(r.top - d), Math.round(r.height)];});}"""
# Loads `tree` as the outline of the document on screen, as PDF.js's document would hand it over.
LOAD_TREE = """async ([tree, pages]) => {
  const items = rows => rows.map(([title, page, kids]) => ({title, dest: [page], items: items(kids)}));
  const doc = {numPages: pages, getOutline: async () => items(tree), getDestination: async () => null, getPageIndex: async () => 0};
  VEC.doc = doc; await loadOutline(doc, ++VEC.gen); return OUTLINE_ENTRIES.length;}"""
VIEW = """const box = document.querySelector('#outline'), o = box.getBoundingClientRect(),
  edge = document.querySelector('#outline-find').getBoundingClientRect().bottom;"""
# The marked row against the outline panel, and what must stay as it was: the pages' scroll, the window's and the focus.
FOLLOW = (
    "() => {"
    + VIEW
    + """ const row = document.querySelector('#outline-items .ol-active'), r = row.getBoundingClientRect(), a = document.activeElement;
  return {index: +row.dataset.index, top: box.scrollTop, pages: document.querySelector('#left').scrollTop, window: scrollY, focus: a.id || a.tagName};}"""
)
# Whether the marked row shows whole under the filter's band: what a follow ends in.
SHOWN = (
    "() => {"
    + VIEW
    + """ const row = document.querySelector('#outline-items .ol-active'); if (!row) return false;
  const r = row.getBoundingClientRect(); return r.top >= edge - 0.5 && r.bottom <= o.bottom + 0.5;}"""
)
# Resolves when the outline has not scrolled for five frames in a row: a smooth scroll (a wheel's, a follow's glide) is over.
STILL = """() => new Promise(done => {const box = document.querySelector('#outline'); let last = -1, same = 0;
  const look = () => {same = box.scrollTop === last ? same + 1 : 0; last = box.scrollTop; if (same >= 5) done(); else requestAnimationFrame(look);};
  look();})"""
# Puts page n's top at the top of the pages and resolves once the viewer has read it, with the pages' scrollTop.
READ_TO = """n => new Promise(done => {const L = document.querySelector('#left'); document.getElementById('p' + n).scrollIntoView();
  const top = L.scrollTop, look = () => {if (OUTLINE_ACTIVE_PAGE === n) done(top); else requestAnimationFrame(look);}; look();})"""
LONG = 120  # outline rows over the manuscript's two pages: page 2 opens at row 60, below the fold of an 850px window
FIRST_ON_2 = 60


class EngineBase(BrowserBase):
    """PanelBase's documents (test_viewer_verdict_panel.py): word files on all three, page lines on the figure (five portrait
    pages, each taking a verdict) and on the PDF; picks on the figure and the PDF reach the real handler."""

    def setUp(self):
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        src = ps.APP.C.src
        for key, path in (
            ("ms", src / "main.limnverdicts.json"),
            ("fig", self.fig.main.parent / "figures.limnverdicts.json"),
            ("rv", src / "reviewer.limnverdicts.json"),
        ):
            path.write_text(json.dumps({**WORDS, "page": key != "ms"}, ensure_ascii=False), encoding="utf-8")
        whole = {"frac": [0, 0, 1, 1], "src": {"file": "src/B2_calendar.py", "lo": 12, "hi": 140}}
        pages = [
            {
                "page": i,
                "figure": "F%02d" % i,
                "title": "[후보] PL%d" % (10 + i),
                "elements": [{"id": "F%02d" % i, **whole}],
            }
            for i in range(1, N_PAGES + 1)
        ]
        fmap = {"format": "limn-figure-map/1", "pdf": "figures.pdf", "pdf_sha256": "0" * 64, "pages": pages}
        d = helpers_figure.write_build(self.fig, helpers_figure.BUILD2, fmap, pages=N_PAGES)
        for i in range(1, N_PAGES + 1):
            (d / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
        patch = mock.patch.object(pick_source, "region_text", return_value="")  # pdftotext answers no text
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(ps.APP.set_docs, None)

    def route(self, route):
        rq = route.request
        if urlparse(rq.url).path == "/api/pick" and json.loads(rq.post_data or "{}").get("doc") in ("fig", "rv"):
            return self.forward(route)
        return super().route(route)

    def pins(self):
        """Every pin as the handler lists it, by id."""
        raw = b"GET /api/pins?all=1 HTTP/1.1\r\nHost: 127.0.0.1:18999\r\n" + b"".join(
            ("%s: %s\r\n" % kv).encode() for kv in ALICE.items()
        )
        return {p["id"]: p for p in json.loads(split_resp(talk_to(ps, raw + b"\r\n"))[2])}

    def on(self, doc="fig", n_open=0, init=None, **device):
        """The viewer showing document doc on device (WIDE unless given), settled at its top."""
        page = self.open(n_open, init=init, **(device or WIDE))
        page.evaluate("k=>switchDoc(k)", doc)
        page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&document.querySelector('#p1')", arg=doc)
        settle(page)
        return page

    def to(self, page, n, off=16):
        page.evaluate(TO, [n, off])
        settle(page)

    def resize(self, page, room):
        """The window made as wide as leaves `room` px beside the pages."""
        for _ in range(3):
            got = page.evaluate("()=>pvSideRoom()")
            if abs(got - room) < 1:
                break
            size = page.viewport_size
            page.set_viewport_size({"width": int(size["width"] + room - got), "height": size["height"]})
            settle(page)
        self.assertLess(abs(page.evaluate("()=>pvSideRoom()") - room), 1)

    def key(self, page, k, n, count):
        """Key k pressed from the PDF area with page n read; waits until page n has `count` verdicts and all is quiet."""
        page.evaluate("searchToPage()")
        page.keyboard.press(k)
        page.wait_for_function("([n,c])=>(pageVerdictPins().get(n)||[]).length===c&&!PV_BUSY.size", arg=[n, count])
        settle(page)

    def outline(self):
        """The manuscript at 1400 x 850 with the outline panel open on LONG rows, reading page 1."""
        page = self.on("ms", init=OUTLINE_OPEN, **DESKTOP)
        self.assertEqual(page.evaluate(LOAD_TREE, [grouped_tree(LONG, 2), 2]), LONG)
        settle(page)
        return page


class PanelFlows:
    """The panel's flows whose engine part differs, shared by the engine classes below."""

    def test_the_panel_comes_and_goes_at_its_bar_and_the_lines_under_the_pages_take_the_keys(self):
        """444px of room: the panel and a summary under each page. 340px (between the bars) keeps it, 320px puts a line
        under every page as 0.4.36 draws them - where a key saves on the page read - 340px keeps them there and 370px brings
        the panel back, showing that verdict."""
        page = self.on()
        self.assertEqual(page.evaluate(SHAPE), {"beside": True, "panel": True, "lines": 0, "sums": N_PAGES})
        for room, beside in ((340, True), (320, False)):
            self.resize(page, room)
            self.assertEqual(page.evaluate(SHAPE)["beside"], beside, room)
        self.assertEqual(page.evaluate(SHAPE), {"beside": False, "panel": False, "lines": N_PAGES, "sums": 0})
        self.to(page, 2)
        self.key(page, "2", 2, 1)
        self.assertEqual([(p["page"], p["verdict"]) for p in self.pins().values()], [(2, "보류")])
        for room, beside in ((340, False), (370, True)):
            self.resize(page, room)
            self.assertEqual(page.evaluate(SHAPE)["beside"], beside, room)
        self.assertEqual(page.evaluate(SHAPE), {"beside": True, "panel": True, "lines": 0, "sums": N_PAGES})
        got = page.evaluate(PANEL)
        self.assertEqual(got["page"], 2, got)
        self.assertIn("보류", got["text"])

    def test_the_panel_stands_still_and_names_the_page_the_strip_names_and_far_summaries_are_skipped(self):
        """Scrolled from page 1 to page 5 in 60px steps, a frame apart: at every step the panel shows the page under the
        reading line, which the section strip names and whose summary is bold; the panel stands at the PDF area's top
        padding, 24px right of that page (position: sticky). No block changes its height. Page 1's summary, now far from the
        view, is skipped (content-visibility) and drawn again when it comes back."""
        page = self.on()
        blocks = page.evaluate(BLOCKS)
        got = page.evaluate(
            """async () => {const L = document.querySelector('#left'), out = []; const frame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
              for (let i = 0; i < 200 && PV_READ < 5; i++) {PV_HAND(); L.scrollTop += 60; await frame(); const p = document.getElementById('pv-panel'), n = pvReadingPage();
                const r = p.getBoundingClientRect(), pg = document.getElementById('p' + n).getBoundingClientRect(), on = document.querySelector('#doc .pv-sum.on');
                out.push({n, panel: +p.dataset.page, strip: (document.getElementById('section-page-t') || {}).textContent || '', bold: on ? +on.dataset.page : 0,
                  top: Math.round(r.top - L.getBoundingClientRect().top - parseFloat(getComputedStyle(L).paddingTop)), gap: Math.round(r.left - pg.right)});}
              return out;}"""
        )
        wrong = [s for s in got if (s["panel"], s["bold"], s["top"], s["gap"]) != (s["n"], s["n"], 0, 24)]
        wrong += [s for s in got if not s["strip"].startswith("%d " % s["n"])]
        self.assertEqual(wrong, [], "steps where the panel, the strip or the bold summary missed the reading page")
        self.assertEqual({s["n"] for s in got}, set(range(1, N_PAGES + 1)))
        settle(page)
        self.assertEqual([b[1] for b in page.evaluate(BLOCKS)], [b[1] for b in blocks], "a block changed its height")
        drawn = """n => {const s = document.querySelector('#doc .pv-sum[data-page="' + n + '"]');
          const far = s.classList.contains('pv-far'), shown = s.firstElementChild.checkVisibility({contentVisibilityAuto: true});
          return far && !shown ? 'skipped' : !far && shown ? 'drawn' : 'far ' + far + ', drawn ' + shown;}"""
        self.assertEqual((page.evaluate(drawn, 1), page.evaluate(drawn, 5)), ("skipped", "drawn"))
        self.to(page, 2, off=300)  # page 1's summary in the view, over page 2
        # Firefox reports the intersection a task or more after the frames settle() waits for.
        page.wait_for_function("()=>(%s)(1)==='drawn'" % drawn, timeout=3000)

    def test_a_key_saves_enter_writes_the_reason_esc_twice_drops_a_draft_and_its_digit_takes_it_back(self):
        """Key 1 saves 채택 on page 2 and hands the focus, its ring showing, to 'Enter 이유 쓰기'; Enter opens the reason in
        the panel with a ring nothing cuts and Enter writes it. Opened again and typed over, Esc twice drops the draft. The
        verdict's own digit takes it back, the focus on [되돌리기], whose Enter brings it back."""
        page = self.on()
        self.to(page, 2)
        self.key(page, "1", 2, 1)
        (pid,) = self.pins()
        got = page.evaluate(FOCUS)
        self.assertEqual((got["panel"], got["act"], got["ring"]), (True, "pv-reason-open", True), got)
        page.keyboard.press("Enter")
        page.wait_for_selector("#pv-panel>.pv-pop .pv-reason")
        self.assertTrue(page.evaluate(FOCUS)["ring"])
        self.assertEqual(page.evaluate(RING_CUT), [], "a box cuts the reason field's focus ring")
        page.keyboard.type("패널의 이유")
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='패널의 이유')", arg=pid)
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "패널의 이유")
        page.locator("#pv-panel button.pv-note").focus()
        page.keyboard.press("Enter")
        page.wait_for_selector("#pv-panel>.pv-pop .pv-reason")
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("버릴 초안")
        page.keyboard.press("Escape")
        settle(page)
        self.assertTrue(page.evaluate(PANEL)["pop"], "the first Esc with text closed the popover")
        page.keyboard.press("Escape")
        settle(page)
        got = page.evaluate(PANEL)
        self.assertFalse(got["pop"], got)
        self.assertNotIn("초안 있음", got["text"])
        self.assertEqual(self.pins()[pid]["note"], "패널의 이유")
        self.key(page, "1", 2, 0)
        self.assertIn("판정 없음", page.evaluate(PANEL)["text"])
        got = page.evaluate(FOCUS)
        self.assertEqual((got["panel"], got["act"]), (True, "pv-undo"), got)
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=pid)
        settle(page)
        self.assertIn("채택", page.evaluate(PANEL)["text"])

    def test_tab_goes_through_the_panel_to_the_pin_panel_and_shift_tab_comes_back(self):
        """From the section strip's page button Tab goes to the panel's first word, its ring showing; Shift+Tab goes back.
        Tab through the panel ends past the pages (the pin panel's grip); Shift+Tab from there comes back to the panel's last
        control. The pages never scroll."""
        page = self.on()
        self.to(page, 2)
        self.key(page, "1", 2, 1)
        page.evaluate(
            "()=>NOTICES.forEach(n=>{if(n.place==='chip')endNotice(n,false);})"
        )  # the save chip, a stop of its own
        settle(page)
        top = page.evaluate(TOP)
        page.locator("#section-page").focus()
        page.keyboard.press("Tab")
        got = page.evaluate(FOCUS)
        self.assertEqual((got["panel"], got["act"], got["ring"]), (True, "pv-save", True), got)
        self.assertEqual(page.evaluate(RING_CUT), [], "a box cuts the word's focus ring")
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate(FOCUS)["id"], "section-page")
        page.keyboard.press("Tab")
        seen = []
        for _ in range(12):
            got = page.evaluate(FOCUS)
            if not got or not got["panel"]:
                break
            seen.append(got["act"])
            page.keyboard.press("Tab")
        self.assertEqual(seen[:3], ["pv-save"] * 3, seen)
        self.assertIn("pv-cancel", seen)
        got = page.evaluate(FOCUS)
        self.assertTrue(
            got and (got["right"] or got["id"] == "grip"), "Tab from the panel's last control went to %s" % got
        )
        page.keyboard.press("Shift+Tab")
        got = page.evaluate(FOCUS)
        self.assertEqual((got["panel"], got["act"]), (True, seen[-1]), got)
        self.assertEqual(page.evaluate(TOP), top)

    def test_a_wheel_over_the_panel_and_page_down_on_its_control_move_the_pages(self):
        """The wheel with the pointer on the panel's name moves the pages by its delta; PageDown with the focus on a word moves
        them by the browser's page step, and once the next page is read the next digit lands there."""
        page = self.on()
        self.to(page, 2)
        box = page.locator("#pv-panel .pv-fig-id").bounding_box()
        page.mouse.move(box["x"] + 4, box["y"] + 4)
        top = page.evaluate(TOP)
        page.mouse.wheel(0, 300)
        page.wait_for_function(RESTING, polling="raf", timeout=10000)
        self.assertEqual(page.evaluate(TOP) - top, 300)
        self.to(page, 2)
        page.locator('#pv-panel button[data-key="채택"]').focus()
        top = page.evaluate(TOP)
        page.keyboard.press("PageDown")
        page.wait_for_function(RESTING, polling="raf", timeout=10000)
        settle(page)
        self.assertGreater(page.evaluate(TOP) - top, 400)
        for _ in range(2):  # WebKit's page step is shorter than Chromium's: a second one reaches page 3
            if page.evaluate("pvReadingPage()") == 3:
                break
            self.assertIsNotNone(page.evaluate(FOCUS), "PageDown left the focus on nothing")
            page.keyboard.press("PageDown")
            page.wait_for_function(RESTING, polling="raf", timeout=10000)
            settle(page)
        self.assertEqual(page.evaluate("pvReadingPage()"), 3)
        self.key(page, "2", 3, 1)
        self.assertEqual([(p["page"], p["verdict"]) for p in self.pins().values()], [(3, "보류")])

    def test_page_down_after_a_press_on_the_panels_text_moves_the_pages(self):
        """A press on the panel's plain text leaves the focus on nothing; PageDown then moves the pages."""
        page = self.on()
        self.to(page, 2)
        box = page.locator("#pv-panel .pv-fig-id").bounding_box()
        page.mouse.click(box["x"] + 4, box["y"] + 4)
        self.assertIsNone(page.evaluate(FOCUS))
        top = page.evaluate(TOP)
        page.keyboard.press("PageDown")
        page.wait_for_function(RESTING, polling="raf", timeout=10000)
        self.assertGreater(page.evaluate(TOP) - top, 400)


class OutlineFlows:
    """The outline's follow and its holds, whose events differ between engines."""

    def test_the_outline_follows_without_moving_the_pages_or_the_focus_and_a_pointer_on_it_holds_it(self):
        """Reading page 2 brings its row (below the fold) into view: the pages, the window and the focus stay. With the
        mouse on the outline, reading page 1 leaves the list where it is; the mouse gone, the row comes in."""
        page = self.outline()
        pages = page.evaluate(READ_TO, 2)
        page.wait_for_function(SHOWN, timeout=3000)
        page.evaluate(STILL)
        got = page.evaluate(FOLLOW)
        self.assertEqual((got["index"], got["pages"], got["window"], got["focus"]), (FIRST_ON_2, pages, 0, "BODY"), got)
        self.assertGreater(got["top"], 0)
        box = page.locator("#outline").bounding_box()
        page.mouse.move(box["x"] + 100, box["y"] + box["height"] / 2)
        page.evaluate(READ_TO, 1)
        nothing_follows(page)
        self.assertEqual(page.evaluate(FOLLOW)["top"], got["top"], "the list moved under the mouse")
        area = page.locator("#left").bounding_box()
        page.mouse.move(area["x"] + area["width"] / 2, area["y"] + area["height"] / 2)
        page.wait_for_function(SHOWN, timeout=3000)
        page.evaluate(STILL)
        self.assertEqual(page.evaluate(FOLLOW)["top"], 0)

    def test_a_wheel_and_the_width_grips_drag_hold_the_outline_and_an_empty_focused_filter_does_not(self):
        """A wheel in the outline holds the list: read on, it stays, then the row comes in after the hold. A drag of the
        width grip holds it for as long as it lasts and the row comes in after its release. A focus left in the empty
        filter holds nothing, and the field keeps the focus."""
        page = self.outline()
        box = page.locator("#outline").bounding_box()
        page.mouse.move(box["x"] + 100, box["y"] + box["height"] / 2)
        page.mouse.wheel(0, 300)
        page.wait_for_function("document.querySelector('#outline').scrollTop > 0")
        page.evaluate(STILL)  # WebKit's wheel glides
        area = page.locator("#left").bounding_box()
        page.mouse.move(area["x"] + area["width"] / 2, area["y"] + area["height"] / 2)
        top = page.evaluate(FOLLOW)["top"]
        page.evaluate(READ_TO, 2)
        nothing_follows(page)
        self.assertEqual(page.evaluate(FOLLOW)["top"], top, "the list moved inside the wheel's hold")
        page.wait_for_function(SHOWN, timeout=6000)
        page.evaluate(STILL)  # a glide shows the row whole before it ends
        grip = page.locator("#outline-grip").bounding_box()
        page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + 300)
        page.mouse.down()
        self.assertTrue(page.evaluate("document.querySelector('#outline-grip').classList.contains('on')"))
        top = page.evaluate(FOLLOW)["top"]
        page.evaluate(READ_TO, 1)
        page.evaluate("OUTLINE_HANDLED = -Infinity; outlineCatchUp()")  # a drag longer than the timed hold
        nothing_follows(page)
        self.assertEqual(page.evaluate(FOLLOW)["top"], top, "the list moved during the grip's drag")
        page.mouse.up()
        page.wait_for_function(SHOWN, timeout=6000)
        page.focus("#outline-search")
        settle(page)  # WebKit reveals the focused field at its next rendering update, by the list's scroll-padding
        page.evaluate(READ_TO, 2)
        page.wait_for_function(SHOWN, timeout=3000)
        self.assertEqual(page.evaluate(FOLLOW)["focus"], "outline-search")


class FirefoxPanel(PanelFlows, OutlineFlows, EngineBase):
    """The panel and the outline's follow in Playwright's bundled desktop Firefox."""

    BROWSER_ENGINE = "firefox"

    @unittest.skip(
        "Firefox scrolls by keyboard the focused element's scroller or the selection's, else the window: a press on text "
        "that cannot be selected (the panel, a page line, the pages) leaves neither, so PageDown moves nothing in any "
        "scroller - Chromium and WebKit take the pressed node's"
    )
    def test_page_down_after_a_press_on_the_panels_text_moves_the_pages(self):
        """Skipped in Firefox (the reason above)."""


class WebKitPanel(PanelFlows, OutlineFlows, EngineBase):
    """The same flows in desktop WebKit, without claiming a physical iOS or macOS Safari."""

    BROWSER_ENGINE = "webkit"
