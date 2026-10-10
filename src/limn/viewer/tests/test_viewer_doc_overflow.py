"""The nav bar's document row when its links do not all fit (docs/handbook/viewer.md §문서 링크가 넘칠 때).

The row shows whole links only, in the documents' order, the current document's always among them, and [+N] after them
for the N it leaves out; [+N] opens a popover listing every document. These tests drive the real viewer in Chromium with
twelve documents whose names mix Hangul and Latin and differ in length (MANY), and four (FEW) for a bar that has room.

Which links a screen shows is a number a person chose from the names and the screen, written out per viewport
(SHOWN_FIRST, SHOWN_LAST) - not worked out again from the widths, which would repeat the rule under test. The widths those
choices rest on are the bundled Pretendard Variable's (docs/handbook/viewer.md §글꼴); each test that reads the row checks
first that the links are drawn in it, so a machine that draws them in another face fails at that line, not at a count.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_doc_overflow.py
"""

import base64
import json
from pathlib import Path

import helpers_figure
from helpers import blank_png, extract_js_fn, minimal_pdf, ps, run_node, serve_viewer
from helpers_browser import (
    MEASURE,
    ROW_INK,
    VIEWPORTS,
    BrowserBase,
    booted,
    drawn_faces,
    fonts_ready,
    settle,
    watch_idle,
)

# Twelve documents: the manuscript and eleven view-only PDFs, short and long, Hangul and Latin names.
MANY = [
    "ms=본문 원고:main.tex",
    "rr=Response to reviewers:rr.pdf",
    "sp=보충 자료:sp.pdf",
    "cl=Cover letter:cl.pdf",
    "hl=Highlights:hl.pdf",
    "ga=그래픽 초록:ga.pdf",
    "da=Appendix A data:da.pdf",
    "db=부록 B 유도:db.pdf",
    "r1=1차 심사 답변:r1.pdf",
    "r2=Second-round response:r2.pdf",
    "ac=저자 기여:ac.pdf",
    "dv=데이터 가용성 진술:dv.pdf",
]
KEYS = [d.split("=")[0] for d in MANY]
FEW = [MANY[0], MANY[2], MANY[5], MANY[10]]  # four short names: every bar has room for them
BUILD = "pages-20260926100000"
LABEL = "조류 관측 논문 2026"  # the instance's name: wide enough that a squeezed bar would shorten it
PDF_READY = "typeof VEC!=='undefined'&&!!VEC.doc&&!VEC.pumping&&!VEC.cur"  # the PDF on screen is open and drawn
# The viewports with a nav bar (the fixed list's tablets, foldables and desktop) and the phones, which have none.
BARS = {k: v for k, v in VIEWPORTS.items() if not k.startswith(("phone", "fold outer"))}
PHONES = {k: v for k, v in VIEWPORTS.items() if k.startswith(("phone", "fold outer"))}
# A 1100px mouse window with the outline and the pin panel open: the desktop's most crowded bar.
CROWDED = {"viewport": {"width": 1100, "height": 800}, "device_scale_factor": 1}
# The links each bar shows with the first document current, and with the last one current: what fits of the names at
# the row's text size (12px; a link is its name, 4px, its page count '1쪽', with 2px each side - 'Response to reviewers'
# is about 160px, '보충 자료' about 70px), the row's gap (20px on the desktop, 8px on touch) and [+N] (about 48px with a
# mouse, 56px on touch) in the room the bar leaves the row - on 768x1024 about 466px: four links and [+8] need about 481.
SHOWN_FIRST = {
    "desktop 1440x900": ["ms", "rr", "sp", "cl", "hl", "ga"],
    "tablet 768x1024": ["ms", "rr", "sp"],
    "tablet 1024x768": ["ms", "rr", "sp", "cl", "hl", "ga"],
    "fold inner 673x841": ["ms", "rr"],
    "fold inner 841x673": ["ms", "rr", "sp", "cl"],
}
SHOWN_LAST = {
    "desktop 1440x900": ["ms", "rr", "sp", "cl", "dv"],
    "tablet 768x1024": ["ms", "rr", "dv"],
    "tablet 1024x768": ["ms", "rr", "sp", "cl", "hl", "dv"],
    "fold inner 673x841": ["ms", "dv"],
    "fold inner 841x673": ["ms", "rr", "sp", "dv"],
}

# The row as drawn: the keys of the links shown, the button's N (0 when it is not drawn), the links hidden, whether the row
# can scroll, the links (and the button) whose box is not wholly inside the row's, and the current document's key.
ROW = """() => {const row = document.querySelector('#doc-links'), more = document.querySelector('#doc-more'), R = row.getBoundingClientRect();
  const links = [...row.querySelectorAll(':scope>[data-doc]')], shown = links.filter(a => a.getClientRects().length);
  const out = e => {const r = e.getBoundingClientRect(); return r.left < R.left - 0.01 || r.right > R.right + 0.01 || r.top < R.top - 0.01 || r.bottom > R.bottom + 0.01;};
  return {shown: shown.map(a => a.dataset.doc), n: more.getClientRects().length ? Number(more.textContent.trim().replace('+', '')) : 0,
    hidden: links.length - shown.length, scrolls: row.scrollWidth > row.clientWidth, drawn: row.getClientRects().length > 0,
    cut: [...shown, ...(more.getClientRects().length ? [more] : [])].filter(out).map(e => e.dataset.doc || e.id),
    current: (row.querySelector('[aria-current=page]') || {dataset: {}}).dataset.doc};}"""
# Whether the instance's name is shortened (an ellipsis).
NAME_CUT = "(e=>e.scrollWidth>e.clientWidth)(document.querySelector('#paper-identity>span:last-child'))"
# The open popover: its box, the button's, the rows (key, shown, height, top, check, name, pages, key hint as drawn) and the
# focused element's id or row key.
POP = """() => {const q = s => document.querySelector(s), B = e => {const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom];};
  const pop = q('#doc-pop'), vis = e => e.getClientRects().length > 0 && getComputedStyle(e).display !== 'none';
  const a = document.activeElement;
  return {open: !pop.hidden, box: pop.hidden ? null : B(pop), button: B(q('#doc-more')), expanded: q('#doc-more').getAttribute('aria-expanded'),
    field: vis(q('#doc-pop-in')), focus: a.dataset.doc || a.id,
    rows: [...q('#doc-pop-list').children].map(r => ({key: r.dataset.doc, shown: vis(r), h: r.getBoundingClientRect().height,
      top: r.getBoundingClientRect().top, check: !!r.querySelector('.dp-c .ic'), name: r.querySelector('.dp-t').textContent,
      pages: r.querySelector('.dp-p').textContent, hint: vis(r.querySelector('.dp-k')) ? r.querySelector('.dp-k').textContent : null,
      selected: r.getAttribute('aria-selected')}))};}"""


def put_pdf_build(doc, pages=1):
    """Put a one-page build of doc on screen with its one-page PDF copy, so the viewer opens the PDF (and offers its search)."""
    d = Path(doc.dir) / BUILD
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, pages + 1):
        (d / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
    (d / doc.pdf_name).write_bytes(minimal_pdf("main"))
    (Path(doc.dir) / "pages.cur").write_text(d.name)
    (Path(doc.dir) / "built_at.txt").write_text("2026-09-25 10:00:00")
    (Path(doc.dir) / "head.txt").write_text("abc1234")


class ManyDocsBase(BrowserBase):
    """BrowserBase serving the documents of DOCS (MANY): the manuscript with a PDF build, the rest view-only PDFs."""

    DOCS = MANY

    def setUp(self):
        """The documents of DOCS, each with a one-page build whose PDF the viewer opens (so the search is offered), on an
        instance named LABEL."""
        super().setUp()
        serve_viewer(LABEL, "#2563eb", ps)
        src = ps.APP.C.src
        for spec in self.DOCS[1:]:
            name = spec.rsplit(":", 1)[1]
            (src / name).write_bytes(minimal_pdf(name.split(".")[0]))
        docs = helpers_figure.startup_documents.make_docs(self.DOCS, src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)
        for D in docs[1:]:
            (helpers_figure.viewer_build(D, helpers_figure.BUILD1) / "page-2.png").unlink()  # one page, as its PDF
        put_pdf_build(docs[0])

    def view(self, dev, doc="ms", lang="ko", side=None):
        """The viewer on dev with document doc on screen, booted and settled; first-visit hints are seen, the desktop's
        outline is open and its pin panel open unless side is False."""
        prefs = {"coach": {"touch": 1, "mouse": 1, "sel": 1, "side": 1}, "lastDoc": doc, "outlineClosed": False}
        if side is False:
            prefs["sideClosed"] = True
        context = self.browser.new_context(**dev)
        self.addCleanup(context.close)
        context.add_init_script(
            "try{if(!sessionStorage.getItem('__t')){sessionStorage.setItem('__t','1');"
            "localStorage.setItem('pinPrefs',%s);}}catch(e){}" % json.dumps(json.dumps(prefs))
        )
        watch_idle(context)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=%s" % lang)
        page.wait_for_function(booted(0), timeout=20000)
        page.wait_for_function("DOC===%s" % json.dumps(doc), timeout=20000)
        page.wait_for_function(PDF_READY, timeout=20000)
        settle(page)
        fonts_ready(page)
        settle(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def row(self, page):
        """The row as drawn (ROW)."""
        return page.evaluate(ROW)

    def assert_pretendard(self, page):
        """The links are drawn in the bundled Pretendard, the face SHOWN_FIRST and SHOWN_LAST were chosen for."""
        faces = drawn_faces(page, "#doc-links [data-doc] .lbl", "본문원고Response")
        self.assertEqual(faces, {"Pretendard Variable"}, "the links are drawn in %s, not the bundled font" % faces)

    def open_menu(self, page):
        """Press [+N] as the screen's pointer does and wait for the popover."""
        touch = page.evaluate("matchMedia('(pointer:coarse)').matches")
        (page.tap if touch else page.click)("#doc-more")
        page.wait_for_function("!document.querySelector('#doc-pop').hidden")
        settle(page)
        return page.evaluate(POP)


class WholeLinks(ManyDocsBase):
    """Twelve documents on every bar: whole links in order, the current one always shown, [+N] for the rest."""

    def check_row(self, r, shown):
        """The row r shows exactly shown, whole, [+N] saying how many it leaves out, and never scrolls."""
        self.assertEqual(r["shown"], shown)
        self.assertEqual(r["n"], len(KEYS) - len(shown))
        self.assertEqual(r["hidden"], r["n"])
        self.assertEqual(r["cut"], [])
        self.assertFalse(r["scrolls"])
        self.assertIn(r["current"], r["shown"])

    def test_each_bar_shows_the_chosen_links_with_the_first_document_current(self):
        """With the first document on screen each bar shows the first links that fit, whole, then [+N]."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                page = self.view(dev, "ms")
                self.assert_pretendard(page)
                self.check_row(self.row(page), SHOWN_FIRST[name])

    def test_the_current_document_takes_the_last_place(self):
        """With the last document on screen it stands in the last place shown; the links before it keep their order."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                page = self.view(dev, "dv")
                self.check_row(self.row(page), SHOWN_LAST[name])

    def test_the_fit_is_the_same_at_both_scale_factors(self):
        """768x1024 at device scale factor 1 shows the same links as at 2."""
        dev = dict(BARS["tablet 768x1024"], device_scale_factor=1)
        self.check_row(self.row(self.view(dev, "dv")), SHOWN_LAST["tablet 768x1024"])

    def test_switching_to_a_folded_document_shows_it(self):
        """Choosing a document that was folded (Alt+9 on the desktop) puts it in the last place shown ('1차 심사 답변' is
        wider than '그래픽 초록', so one link fewer than with the first document current)."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        page.locator("#left").focus()
        page.keyboard.press("Alt+Digit9")
        page.wait_for_function("DOC==='r1'")
        settle(page)
        self.check_row(self.row(page), ["ms", "rr", "sp", "cl", "r1"])

    def test_the_paper_name_stays_whole_while_links_fold(self):
        """On the desktop and in the crowded 1100px window the instance's name is drawn whole while links are folded:
        the links give way first."""
        for name, dev in (("desktop", BARS["desktop 1440x900"]), ("crowded", CROWDED)):
            with self.subTest(viewport=name):
                page = self.view(dev, "ms")
                r = self.row(page)
                self.assertGreater(r["n"], 0)
                self.assertEqual(r["cut"], [])
                self.assertFalse(page.evaluate(NAME_CUT))

    def test_the_row_refits_as_the_bar_changes(self):
        """The 1440 desktop narrowed to 1100px folds more links, the instance's name still whole; collapsing the pin
        panel there (Ctrl+\\) gives some back; each time the links shown are whole."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        wide = self.row(page)["n"]
        page.set_viewport_size({"width": 1100, "height": 900})
        page.wait_for_function("innerWidth===1100")
        settle(page)
        narrow = self.row(page)
        self.assertGreater(narrow["n"], wide)
        self.assertEqual(narrow["cut"], [])
        self.assertFalse(page.evaluate(NAME_CUT))  # measured while the narrowed bar squeezed it: still whole
        page.locator("#left").focus()
        page.keyboard.press("Control+Backslash")
        page.wait_for_function("!SIDE_OPEN")
        settle(page)
        roomy = self.row(page)
        self.assertLess(roomy["n"], narrow["n"])
        self.assertEqual(roomy["cut"], [])


class FewDocs(ManyDocsBase):
    """Four documents fit every bar: the row is the links alone, as before the button existed."""

    DOCS = FEW

    def test_four_documents_show_every_link_and_no_button(self):
        """On every bar the four links are drawn whole and [+N] is not."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                r = self.row(self.view(dev, "ms"))
                self.assertEqual((r["shown"], r["n"], r["cut"], r["scrolls"]), (["ms", "sp", "ga", "ac"], 0, [], False))


class Phones(ManyDocsBase):
    """The phones have no nav bar: no row and no button; the navigation sheet lists all twelve documents."""

    def test_phones_keep_the_navigation_sheet(self):
        """On each phone the row is not drawn, and [본문 1/2 ▾] opens the sheet with twelve document rows."""
        for name, dev in PHONES.items():
            with self.subTest(viewport=name):
                page = self.view(dev, "ms")
                r = self.row(page)
                self.assertEqual((r["drawn"], r["n"]), (False, 0))
                page.tap("#btn-pos")
                page.wait_for_function("document.querySelector('#nav-sheet').open")
                self.assertEqual(page.locator("#ns-docs-list .dm-item").count(), 12)


class ButtonLooks(ManyDocsBase):
    """[+N] is drawn as the links are and sized on the 4px grid (docs/handbook/viewer.md §글자 가운데, §컴포넌트 규격)."""

    LOOK = """() => {const m = document.querySelector('#doc-more'), cs = getComputedStyle(m), r = m.getBoundingClientRect();
      const tab = [...document.querySelectorAll('#doc-links>[data-doc]:not([hidden])')].find(a => a.getAttribute('aria-current') !== 'page');
      const ts = getComputedStyle(tab), c = e => {const b = e.getBoundingClientRect(); return b.top + b.height / 2;};
      const labels = [...document.querySelectorAll('#doc-links>[data-doc]:not([hidden]) .lbl')];
      return {h: r.height, pad: [parseFloat(cs.paddingLeft), parseFloat(cs.paddingRight)], gap: parseFloat(cs.columnGap),
        icon: (b => [b.width, b.height])(m.querySelector('.ic').getBoundingClientRect()),
        text: [cs.fontSize, cs.color, cs.fontWeight], tabText: [ts.fontSize, ts.color, ts.fontWeight],
        off: labels.map(l => c(l) - c(m.querySelector('.lbl'))), icon_off: c(m.querySelector('.ic')) - c(m.querySelector('.lbl')),
        name: m.getAttribute('aria-label'), popup: [m.getAttribute('aria-haspopup'), m.getAttribute('aria-expanded'), m.getAttribute('aria-controls')]};}"""

    def test_the_button_stands_on_the_links_centre_at_their_size(self):
        """Desktop (mouse) and 768x1024 (touch): '+N' is the links' size, colour and weight; its cap-height centre and
        the chevron's centre are each within 0.5px of every shown link's; its height is the row's control height (28,
        36 on touch), its paddings and gap on the 4px grid, its icon 16px; it answers 24px with a mouse and 44px on
        touch; and its name says how many documents it holds."""
        for name, dev, h, hit in (
            ("desktop 1440x900", BARS["desktop 1440x900"], 28, 24),
            ("tablet 768x1024", BARS["tablet 768x1024"], 36, 44),
        ):
            with self.subTest(viewport=name):
                page = self.view(dev, "ms")
                g = page.evaluate(self.LOOK)
                self.assertEqual(g["text"], g["tabText"])
                self.assertTrue(all(abs(v) <= 0.5 for v in g["off"]), g["off"])
                self.assertLessEqual(abs(g["icon_off"]), 0.5)
                self.assertEqual(g["h"], h)
                self.assertTrue(all(v % 4 == 0 for v in g["pad"] + [g["gap"]]), g)
                self.assertEqual(g["icon"], [16, 16])
                n = 12 - len(SHOWN_FIRST[name])
                self.assertEqual(g["name"], "문서 %d개 더 보기" % n)
                self.assertEqual(g["popup"], ["dialog", "false", "doc-pop"])
                page.evaluate(MEASURE)
                reach = page.evaluate("window.__m.hit(document.querySelector('#doc-more'))")
                self.assertGreaterEqual(reach["l"] + reach["r"], hit - 0.2, reach)
                self.assertGreaterEqual(reach["t"] + reach["b"], hit - 0.2, reach)

    def test_the_painted_ink_of_the_button_and_the_links_agree(self):
        """On the screenshot, at device scale factors 1 and 2, the ink centre of '+N' is within one device pixel of each
        shown link's name (the painted tolerance of §글자 가운데) - the names without a descender or a bracket, whose ink
        the handbook leaves out of the reference (Response, Highlights hang below the baseline)."""
        for dpr in (1, 2):
            with self.subTest(dpr=dpr):
                page = self.view(dict(BARS["desktop 1440x900"], device_scale_factor=dpr), "ms")
                items = page.evaluate(
                    """() => [...[...document.querySelectorAll('#doc-links>[data-doc]:not([hidden]) .lbl')].filter(e => !/[gjpqy(),]/.test(e.textContent)), document.querySelector('#doc-more .lbl')]
                      .map((e, i) => {const r = e.getBoundingClientRect(), b = e.closest('button').getBoundingClientRect();
                        return {k: String(i), box: [r.left - 1, b.top + 2, r.right + 1, b.bottom - 2]};})"""
                )
                shot = base64.b64encode(page.screenshot()).decode()
                ink = page.evaluate(ROW_INK, [shot, dpr, items])
                mids = [ink[str(i)]["mid"] for i in range(len(items))]
                button = mids.pop()
                self.assertTrue(all(abs(m - button) <= 1 / dpr + 0.01 for m in mids), (button, mids))

    def test_the_button_name_is_english_on_an_english_screen(self):
        """In English the button's name is the message table's plural ('6 more documents')."""
        page = self.view(BARS["desktop 1440x900"], "ms", lang="en")
        self.assertEqual(page.get_attribute("#doc-more", "aria-label"), "%d more documents" % self.row(page)["n"])


class Popover(ManyDocsBase):
    """The documents popover: every document, placed under its button inside the window, worked by keys and presses."""

    def test_it_lists_every_document_under_its_button(self):
        """Desktop, 768x1024 and 1024x768: the popover opens under [+N] (4px below it, left edges together) inside the
        window by 8px; it lists the twelve documents in order, the current one checked and selected, each with its
        page count; rows are 32px with a mouse and 44px on touch, on a 4px pitch; the Alt hints of the first nine show
        with a mouse and not on a touch-only screen; the filter is there (twelve documents)."""
        for name, row_h, hints in (
            ("desktop 1440x900", 32, True),
            ("tablet 768x1024", 44, False),
            ("tablet 1024x768", 44, False),
        ):
            with self.subTest(viewport=name):
                dev = BARS[name]
                page = self.view(dev, "ms")
                p = self.open_menu(page)
                vw, vh = dev["viewport"]["width"], dev["viewport"]["height"]
                self.assertEqual(p["expanded"], "true")
                self.assertAlmostEqual(p["box"][1], round(p["button"][3]) + 4, delta=0.01)
                width = p["box"][2] - p["box"][0]
                self.assertAlmostEqual(
                    p["box"][0], min(round(p["button"][0]), vw - 8 - width), delta=0.01
                )  # left-aligned, kept inside
                self.assertTrue(p["box"][0] >= 8 and p["box"][2] <= vw - 8 and p["box"][3] <= vh - 8, p["box"])
                self.assertEqual([r["key"] for r in p["rows"]], KEYS)
                self.assertEqual([r["check"] for r in p["rows"]], [k == "ms" for k in KEYS])
                self.assertEqual([r["selected"] for r in p["rows"]], ["true" if k == "ms" else "false" for k in KEYS])
                self.assertEqual({r["pages"] for r in p["rows"]}, {"1쪽"})
                self.assertEqual({r["h"] for r in p["rows"]}, {row_h})
                tops = [r["top"] - p["rows"][0]["top"] for r in p["rows"]]
                self.assertTrue(all(abs(t % 4) < 0.01 for t in tops), tops)
                self.assertEqual(
                    [r["hint"] for r in p["rows"]],
                    ["Alt+%d" % i for i in range(1, 10)] + ["", "", ""] if hints else [None] * 12,
                )
                self.assertTrue(p["field"])

    def test_a_long_list_scrolls_inside_a_short_window(self):
        """In a 1200x420 mouse window the popover ends 8px above the window's bottom and its list scrolls inside it."""
        page = self.view({"viewport": {"width": 1200, "height": 420}}, "ms")
        p = self.open_menu(page)
        self.assertAlmostEqual(p["box"][3], 420 - 8, delta=0.01)
        self.assertTrue(page.evaluate("(l=>l.scrollHeight>l.clientHeight)(document.querySelector('#doc-pop-list'))"))

    def test_keys_open_filter_choose_and_give_the_focus_back(self):
        """Desktop: ↓ on the focused [+N] opens it with the focus in the filter; typing 'letter' leaves Cover letter alone;
        ↓ goes to its row and Enter opens that document and gives the focus back to [+N]. Opened again with Enter, ↓
        from the filter is the current row, End the last, ↑ ↑ steps back, Home the first, ↑ the filter; Esc shuts it with the
        focus on [+N]."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        page.focus("#doc-more")
        page.keyboard.press("ArrowDown")
        page.wait_for_function("!document.querySelector('#doc-pop').hidden")
        self.assertEqual(page.evaluate(POP)["focus"], "doc-pop-in")
        page.keyboard.type("letter")
        self.assertEqual([r["key"] for r in page.evaluate(POP)["rows"] if r["shown"]], ["cl"])
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate(POP)["focus"], "cl")
        page.keyboard.press("Enter")
        page.wait_for_function("DOC==='cl'")
        settle(page)
        p = page.evaluate(POP)
        self.assertEqual((p["open"], p["focus"], p["expanded"]), (False, "doc-more", "false"))
        page.keyboard.press("Enter")
        page.wait_for_function("!document.querySelector('#doc-pop').hidden")
        self.assertEqual(page.evaluate(POP)["focus"], "doc-pop-in")
        steps = []
        for key in ("ArrowDown", "End", "ArrowUp", "ArrowUp", "Home", "ArrowUp"):
            page.keyboard.press(key)
            steps.append(page.evaluate(POP)["focus"])
        self.assertEqual(steps, ["cl", "dv", "ac", "r2", "ms", "doc-pop-in"])
        page.keyboard.press("Escape")
        p = page.evaluate(POP)
        self.assertEqual((p["open"], p["focus"]), (False, "doc-more"))

    def test_tab_out_and_a_press_outside_shut_it(self):
        """Tab from the current row (the list's one stop) leaves the popover and shuts it; opened again, a press on the
        page shuts it and changes no document."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        self.open_menu(page)
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Tab")
        self.assertFalse(page.evaluate(POP)["open"])
        self.open_menu(page)
        page.mouse.click(600, 600)
        settle(page)
        self.assertEqual((page.evaluate(POP)["open"], page.evaluate("DOC")), (False, "ms"))

    def test_a_tap_opens_it_without_focusing_the_filter(self):
        """On 768x1024 a tap on [+N] puts the focus on the current document's row, not in the filter (no keyboard)."""
        page = self.view(BARS["tablet 768x1024"], "dv")
        self.assertEqual(self.open_menu(page)["focus"], "dv")
        page.tap("#doc-pop-list [data-doc=sp]")
        page.wait_for_function("DOC==='sp'")
        settle(page)
        self.assertFalse(page.evaluate(POP)["open"])

    def test_a_polling_redraw_keeps_it_open_with_the_focus(self):
        """With the focus on a row, another document starting a build redraws the documents (as the light poll does):
        the popover stays open, the focus stays on the same document's row, and that document's row shows the spinner."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        self.open_menu(page)
        page.keyboard.press("ArrowDown")
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate(POP)["focus"], "rr")
        page.evaluate("docInfo('hl').building=true; drawDocTabs()")
        p = page.evaluate(POP)
        self.assertEqual((p["open"], p["focus"]), (True, "rr"))
        self.assertTrue(page.evaluate("!!document.querySelector('#doc-pop-list [data-doc=hl] .spin')"))

    def test_a_polling_redraw_keeps_the_focus_on_the_button(self):
        """A redraw of the links leaves the focused [+N] focused."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        page.focus("#doc-more")
        page.evaluate("drawDocTabs()")
        self.assertEqual(page.evaluate("document.activeElement.id"), "doc-more")


class WithSearch(ManyDocsBase):
    """The search field beside the row (docs/handbook/viewer.md §탐색 줄의 검색 칸)."""

    def test_the_search_opens_over_the_row_and_closing_puts_it_back(self):
        """Desktop: the search is its magnifier beside the twelve documents' row. Ctrl+F opens the field (an open
        popover shuts); Esc closes it and the row, [+N] and every link stand where they stood, the same links shown."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        where = "[...document.querySelectorAll('#doc-links>*')].filter(e=>e.getClientRects().length).map(e=>{const r=e.getBoundingClientRect(); return [e.id||e.dataset.doc,r.left,r.width];})"
        before, row = page.evaluate(where), self.row(page)
        self.assertEqual(page.evaluate("document.querySelector('#doc-search').dataset.mode"), "icon")
        self.open_menu(page)
        page.locator("#left").focus()
        page.keyboard.press("Control+f")
        page.wait_for_function("document.activeElement.id==='search-q'")
        settle(page)
        self.assertFalse(page.evaluate(POP)["open"])
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual((page.evaluate(where), self.row(page)), (before, row))

    def test_four_documents_leave_the_search_its_field(self):
        """With four documents on the desktop the search is a field in the bar, not the magnifier."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        page.evaluate("DOCS=DOCS.slice(0,4); drawDocTabs()")
        settle(page)
        self.assertEqual(page.evaluate("document.querySelector('#doc-search').dataset.mode"), "inline")
        self.assertEqual(self.row(page)["n"], 0)


def test_the_fit_rule_on_chosen_widths():
    """docTabsShown on widths chosen by hand: all fit; the first k and [+N]; the current one in the last place; and
    nothing but the current link when even one link and the button do not fit."""
    js = "\n".join(
        [
            extract_js_fn("docTabsShown"),
            "const w=[50,50,50,50,50], more=n=>30;",
            "console.log(JSON.stringify([docTabsShown(w,10,0,290,more), docTabsShown(w,10,0,210,more),"
            " docTabsShown(w,10,4,210,more), docTabsShown(w,10,2,210,more), docTabsShown(w,10,3,60,more)]));",
        ]
    )
    # 5 links take 290; in 210 three links (170) and the button (10 + 30) fit; the fifth current replaces the third.
    assert json.loads(run_node(js)) == [[0, 1, 2, 3, 4], [0, 1, 2], [0, 1, 4], [0, 1, 2], [3]]
