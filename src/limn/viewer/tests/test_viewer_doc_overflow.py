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
from urllib.parse import urlparse

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
# Twelve documents, two of them with names of the server's longest (40 characters), one Hangul and one Latin.
LONG = [
    MANY[0],
    "rr=심사위원 의견에 대한 상세 답변서와 수정 내역을 정리한 개정 문서 최종본:rr.pdf",
    "sp=Supplementary information, adaptive mode:sp.pdf",
    *MANY[3:],
]
FEW = [MANY[0], MANY[2], MANY[5], MANY[10]]  # four short names: every bar has room for them
FIVE = [MANY[0], MANY[2], MANY[5], MANY[7], MANY[10]]  # five short names: the crowded 1300px desktop has room for them
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
    current: (row.querySelector('[aria-current=page]') || {dataset: {}}).dataset.doc,
    fit: more.getClientRects().length ? more.dataset.fit : null, label: more.querySelector('.lbl').textContent,
    labelCut: (l => l.getClientRects().length > 0 && l.scrollWidth > l.clientWidth)(more.querySelector('.lbl')),
    name: more.getAttribute('aria-label'), width: R.width,
    past: (() => {const N = document.querySelector('#doc-nav').getBoundingClientRect(), next = row.nextElementSibling;
      const after = [...row.parentElement.children].filter(e => e !== row && e.getClientRects().length && (row.compareDocumentPosition(e) & 4))
        .map(e => e.getBoundingClientRect().left).filter(x => x > R.left);
      return {nav: R.right > N.right + 0.01, next: after.length ? R.right > Math.min(...after) + 0.01 : false};})()};}"""
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


class MetaPatch:
    """A Playwright route whose fulfil merges patch into the JSON body the handler answered (the rest passes through)."""

    def __init__(self, route, patch):
        """Wrap route; patch is merged into the answer's top-level object."""
        self._route, self._patch = route, patch

    def __getattr__(self, name):
        """Everything but fulfill is the route's own (forward() reads its request)."""
        return getattr(self._route, name)

    def fulfill(self, status, headers, body):
        """Fulfil the route with the handler's JSON answer, patch merged in."""
        data = json.loads(body)
        data.update(self._patch)
        self._route.fulfill(status=status, headers=headers, body=json.dumps(data))


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
    STALE = False  # when true, /api/meta says the manuscript is newer than its PDF: the status line has a message

    def route(self, route):
        """BrowserBase's routes, with GET /api/meta saying stale_build while STALE."""
        if self.STALE and urlparse(route.request.url).path == "/api/meta":
            return self.forward(MetaPatch(route, {"stale_build": True, "src_age_s": 120}))
        return super().route(route)

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
        """Press the row's button ([+N] or the chooser) as the screen's pointer does and wait for the popover."""
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
        icon: (b => [b.width, b.height])(m.querySelector(':scope>.ic').getBoundingClientRect()),
        text: [cs.fontSize, cs.color, cs.fontWeight], tabText: [ts.fontSize, ts.color, ts.fontWeight],
        off: labels.map(l => c(l) - c(m.querySelector('.lbl'))), icon_off: c(m.querySelector(':scope>.ic')) - c(m.querySelector('.lbl')),
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
                self.assertEqual(g["name"], "+%d 문서 더 보기" % n)  # its visible '+N' first (label in name)
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
        """In English the button's name is the message table's plural with its visible '+N' ('+7 more documents')."""
        page = self.view(BARS["desktop 1440x900"], "ms", lang="en")
        r = self.row(page)
        self.assertEqual((r["label"], r["name"]), ("+%d" % r["n"], "+%d more documents" % r["n"]))


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

    def test_it_follows_its_button(self):
        """Open on the 1440 desktop, the window narrowed to 1300, 1100 and 1000px and the pin panel collapsed (Ctrl+\\)
        move the button: after each the popover stands 4px under it with their left edges together (within 0.5px), or
        against the window's right margin of 8px when it would pass it."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        self.open_menu(page)
        page.keyboard.press("ArrowDown")  # the focus on a row: Ctrl+\\ is not taken in the filter

        def placed(where):
            p = page.evaluate(POP)
            vw = page.evaluate("innerWidth")
            self.assertTrue(p["open"], where)
            self.assertAlmostEqual(p["box"][1], round(p["button"][3]) + 4, delta=0.01, msg=where)
            self.assertTrue(
                abs(p["box"][0] - p["button"][0]) <= 0.5 or abs(p["box"][2] - (vw - 8)) <= 0.5,
                (where, p["box"], p["button"]),
            )

        for w in (1300, 1100, 1000):
            page.set_viewport_size({"width": w, "height": 900})
            page.wait_for_function("innerWidth===%d" % w)
            settle(page)
            placed(w)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_function("innerWidth===1440")
        settle(page)
        page.keyboard.press("Control+Backslash")
        page.wait_for_function("!SIDE_OPEN")
        settle(page)
        placed("panel collapsed")

    def test_a_redraw_keeps_the_focused_node(self):
        """A redraw by polling (another document starts a build) with the focus on a link, on [+N] or on a popover row
        sends no focusout or focusin and leaves the very same element focused."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        page.evaluate(
            "window.__ev=[]; for (const t of ['focusin','focusout']) document.addEventListener(t, e=>window.__ev.push(t), true)"
        )
        redraw = "(()=>{const a=document.activeElement; window.__ev.length=0; const d=docInfo('hl'); d.building=!d.building; drawDocTabs(); return [document.activeElement===a, window.__ev.slice()];})()"
        for target in ("#doc-links [data-doc=rr]", "#doc-more"):
            page.focus(target)
            self.assertEqual(page.evaluate(redraw), [True, []], target)
        self.open_menu(page)
        page.keyboard.press("ArrowDown")
        page.keyboard.press("ArrowDown")
        self.assertEqual(page.evaluate(POP)["focus"], "rr")
        self.assertEqual(page.evaluate(redraw), [True, []])
        self.assertTrue(page.evaluate(POP)["open"])


class PopoverKeys:
    """The popover's keyboard, the same in Chromium and Firefox (run by KeysChromium and KeysFirefox)."""

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

    def test_tab_goes_on_to_the_bars_next_stop(self):
        """Opened from the focused [+N] (Enter: the focus in the filter), Tab goes to the current document's row, and Tab
        again shuts the popover and puts the focus on the bar's next stop after [+N], the view tab '원고'."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        page.focus("#doc-more")
        page.keyboard.press("Enter")
        page.wait_for_function("!document.querySelector('#doc-pop').hidden")
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(POP)["focus"], "ms")
        page.keyboard.press("Tab")
        p = page.evaluate(POP)
        self.assertEqual((p["open"], p["focus"], p["expanded"]), (False, "view-manuscript", "false"))

    def test_shift_tab_goes_back_to_the_button(self):
        """From a row Shift+Tab goes to the filter, and from the filter it shuts the popover with the focus on [+N]."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        page.focus("#doc-more")
        page.keyboard.press("Enter")
        page.wait_for_function("!document.querySelector('#doc-pop').hidden")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate(POP)["focus"], "doc-pop-in")
        page.keyboard.press("Shift+Tab")
        p = page.evaluate(POP)
        self.assertEqual((p["open"], p["focus"]), (False, "doc-more"))

    def test_a_press_outside_shuts_it(self):
        """A press on the page outside the popover and its button shuts it and changes no document."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        self.open_menu(page)
        page.mouse.click(600, 600)
        settle(page)
        self.assertEqual((page.evaluate(POP)["open"], page.evaluate("DOC")), (False, "ms"))

    def test_alt_digit_picks_from_the_filter_and_from_a_row(self):
        """The Alt+number the popover shows works where the focus is when it opens - the filter - and on a row: Alt+3
        from the filter opens the third document, Alt+5 from a row the fifth; each shuts the popover with the focus on
        [+N]."""
        page = self.view(BARS["desktop 1440x900"], "ms")
        for keys, doc in ((["Alt+Digit3"], "sp"), (["ArrowDown", "Alt+Digit5"], "hl")):
            page.focus("#doc-more")
            page.keyboard.press("Enter")
            page.wait_for_function("!document.querySelector('#doc-pop').hidden")
            for key in keys:
                page.keyboard.press(key)
            page.wait_for_function("DOC===%s" % json.dumps(doc))
            settle(page)
            p = page.evaluate(POP)
            self.assertEqual((p["open"], p["focus"]), (False, "doc-more"), keys)


class KeysChromium(PopoverKeys, ManyDocsBase):
    """The popover's keyboard in Chromium."""


class KeysFirefox(PopoverKeys, ManyDocsBase):
    """The popover's keyboard in Playwright's bundled Firefox."""

    BROWSER_ENGINE = "firefox"


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


# A focused control's ring as drawn: its outline (style, width, offset), the box the ring's outer edge makes, every box
# that clips it - each ancestor that does not let its content overflow, and the nav bar's band under the instance's 4px
# stripe (the bar's box less its top padding) when the control is in the bar - and how far the ring's inner edge stands
# from the control's words and icons on the left and on the right (the boxes of its drawn children: its word spans and icons).
RING = """sel => {const e = document.querySelector(sel), c = getComputedStyle(e), r = e.getBoundingClientRect(), w = parseFloat(c.outlineWidth),
    o = parseFloat(c.outlineOffset), out = o + w, box = [r.left - out, r.top - out, r.right + out, r.bottom + out], clips = [];
  for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {const s = getComputedStyle(a);
    if (s.overflowX !== 'visible' || s.overflowY !== 'visible') {const b = a.getBoundingClientRect(); clips.push([a.id || a.className, b.left, b.top, b.right, b.bottom]);}}
  const nav = e.closest('#doc-nav');
  if (nav) {const b = nav.getBoundingClientRect(); clips.push(['band', b.left, b.top + parseFloat(getComputedStyle(nav).paddingTop), b.right, b.bottom]);}
  const q = [...e.children].filter(k => k.getClientRects().length).map(k => k.getBoundingClientRect()).filter(b => b.width > 0);   // the boxes drawn (an ellipsis clips its words to its box)
  const clear = q.length ? [Math.min(...q.map(b => b.left)) - (r.left - o), (r.right + o) - Math.max(...q.map(b => b.right))] : null;
  return {focusVisible: e.matches(':focus-visible'), outline: [c.outlineStyle, w, o], box, clips, clear};}"""


class Rings(ManyDocsBase):
    """Focus rings are whole (docs/handbook/viewer.md §문서 링크가 넘칠 때): a link's, [+N]'s and the chooser's inside the
    row and the bar's band, a popover row's inside the scrolling list."""

    def assert_whole(self, page, sel, clear=False):
        """The ring of sel (focused by keyboard) is drawn - 2px, focus-visible - and lies inside every box that clips it;
        with clear, its inner edge stands at least 2px from the control's words on both sides."""
        g = page.evaluate(RING, sel)
        self.assertTrue(g["focusVisible"], sel)
        self.assertEqual(g["outline"][:2], ["solid", 2], sel)
        if clear:
            self.assertTrue(g["clear"] and min(g["clear"]) >= 2 - 0.01, (sel, g["clear"]))
        left, top, right, bottom = g["box"]
        for name, cl, ct, cr, cb in g["clips"]:
            inside = left >= cl - 0.01 and top >= ct - 0.01 and right <= cr + 0.01 and bottom <= cb + 0.01
            self.assertTrue(inside, (sel, name, g["box"], (cl, ct, cr, cb)))

    SCREENS = ("desktop 1440x900", "tablet 768x1024")

    def test_the_rings_of_the_row_and_the_popover_are_whole(self):
        """Desktop and 768x1024: Tab from the outline toggle reaches the first link (the current one) - its ring whole
        inside the row and the band and 2px clear of its words - then [+N] and the view tab '원고', the same; in the
        popover the current row and the next one have whole rings inside the list, which scrolls and clips its sides."""
        for name in self.SCREENS:
            with self.subTest(viewport=name):
                page = self.view(BARS[name], "ms")
                page.focus("#nav-toc-toggle")
                page.keyboard.press("Tab")
                self.assertEqual(
                    page.evaluate("document.activeElement.dataset.doc"), "ms"
                )  # the row has no Tab stop of its own
                self.assert_whole(page, "#doc-links [data-doc=ms]", clear=True)
                page.focus("#doc-more")  # a script focus after a key press is focus-visible
                self.assert_whole(page, "#doc-more", clear=True)
                page.focus("#view-manuscript")
                self.assert_whole(page, "#view-manuscript", clear=True)
                page.focus("#doc-more")
                page.keyboard.press("Enter")
                page.wait_for_function("!document.querySelector('#doc-pop').hidden")
                # a mouse screen opens on the filter; touch starts on the row
                if page.evaluate("document.activeElement.id") == "doc-pop-in":
                    page.keyboard.press("ArrowDown")
                self.assert_whole(page, "#doc-pop-list [data-doc=ms]")
                page.keyboard.press("ArrowDown")
                self.assert_whole(page, "#doc-pop-list [data-doc=rr]")


class RingsFirefox(Rings):
    """The same rings in Firefox, on the desktop (Firefox has no mobile emulation). Firefox gives a scroll box with
    anything to scroll a Tab stop of its own; the row is out of the Tab order, so Tab goes from the outline toggle to the
    first link."""

    BROWSER_ENGINE = "firefox"
    SCREENS = ("desktop 1440x900",)


# The bar as drawn, for comparing two layouts: per width, the links shown, the button's step and N, the search's mode, and
# the instance's name - its width to the tenth of a pixel and whether it is shortened.
LAYOUT = """() => {const q = s => document.querySelector(s), m = q('#doc-more'), id = q('#paper-identity'), t = id.lastElementChild;
  return [[...document.querySelectorAll('#doc-links>[data-doc]')].filter(a => a.getClientRects().length).map(a => a.dataset.doc).join(),
    m.getClientRects().length ? m.dataset.fit + ' ' + m.textContent.trim() : '', q('#doc-search').dataset.mode,
    Math.round(id.getBoundingClientRect().width * 10) / 10, t.scrollWidth > t.clientWidth];}"""


class CrowdedBase(ManyDocsBase):
    """The desktop with the outline and the pin panel open: the search folds before the instance's name shortens, and the
    layout at a width does not depend on how the window got there."""

    def same_both_ways(self, doc):
        """Narrow the window from 1440 to 1000px and widen it back, 8px a step: at every width the bar is the same both
        ways (links, button, search, the instance's name), and the name is never shortened."""
        page = self.view({"viewport": {"width": 1440, "height": 800}}, doc)
        seen = {}
        for w in list(range(1440, 999, -8)) + list(range(1000, 1441, 8)):
            page.set_viewport_size({"width": w, "height": 800})
            page.wait_for_function("innerWidth===%d" % w)
            settle(page)
            got = page.evaluate(LAYOUT)
            self.assertFalse(got[4], (w, got))
            self.assertEqual(seen.setdefault(w, got), got, w)


class CrowdedDesktop(CrowdedBase):
    """Five short names on the crowded desktop."""

    DOCS = FIVE

    def test_five_short_documents_at_1300_fit_as_before(self):
        """1300x800 with the outline and the panel open, five short names, a fresh load: all five links and no button, the
        instance's name whole, the search folded to its magnifier - as 0.4.21 drew it."""
        page = self.view({"viewport": {"width": 1300, "height": 800}}, "ms")
        shown, button, search, _, cut = page.evaluate(LAYOUT)
        self.assertEqual((shown, button, search, cut), ("ms,sp,ga,db,ac", "", "icon", False))

    def test_the_layout_at_a_width_is_the_same_narrowing_and_widening(self):
        """The same bar at every width, narrowing and widening (same_both_ways)."""
        self.same_both_ways("ms")


class CrowdedDesktopLong(CrowdedBase):
    """Twelve documents on the crowded desktop, a 40-character name current."""

    DOCS = LONG

    def test_the_layout_at_a_width_is_the_same_narrowing_and_widening(self):
        """The long Hangul name current: the same bar at every width both ways (same_both_ways)."""
        self.same_both_ways("rr")


# The row's ladder (docs/handbook/viewer.md §문서 링크가 넘칠 때) - chosen per screen from the names and the room the bar
# leaves: 'tabs' with the keys shown (and [+N] for the rest), 'name' (the chooser saying the current document's name,
# whole or shortened to an ellipsis) or 'icon'. The short band at 844, 740 and 667px wide, with and without the stale
# PDF's message on its status line ('원고 수정됨 [재빌드]', about 146px, in this row): beside [목차], 원고|변경사항, the
# magnifier and the page count, '본문 원고' and [+11] need about 135px and 'Response to reviewers' 160px more; at 740px
# with the message only the chooser fits ('본문 원고' whole), at 667px not even three em of it.
SHORT = {"844x390": (844, 390), "740x360": (740, 360), "667x375": (667, 375)}
LADDER_SHORT = {
    ("844x390", False): ("tabs", ["ms", "rr"]),
    ("844x390", True): ("tabs", ["ms"]),
    ("740x360", False): ("tabs", ["ms"]),
    ("740x360", True): ("name", "본문 원고"),
    ("667x375", False): ("tabs", ["ms"]),
    ("667x375", True): ("icon", None),
}
# Twelve documents with two of the longest names, the current one each of them in turn: the Hangul one is about 370px as
# a link, the Latin one about 260px.
LADDER_LONG = {
    ("tablet 768x1024", "rr"): ("tabs", ["rr"]),
    ("tablet 768x1024", "sp"): ("tabs", ["ms", "sp"]),
    ("fold inner 673x841", "rr"): ("name", "…"),
    ("fold inner 673x841", "sp"): ("tabs", ["sp"]),
    ("crowded 1100x800", "rr"): ("name", "…"),
    ("crowded 1100x800", "sp"): ("tabs", ["sp"]),
}


def touch(w, h, dpr):
    """A w x h touch screen at device scale factor dpr."""
    return {"viewport": {"width": w, "height": h}, "is_mobile": True, "has_touch": True, "device_scale_factor": dpr}


class LadderBase(ManyDocsBase):
    """Reads and checks one step of the ladder."""

    def check_step(self, page, want, where):
        """The row is at step want ('tabs' with the keys shown, 'name' with the label - '…' for any shortened name - or
        'icon'), nothing in it is cut or passes the bar or its next neighbour, and its button opens the popover where it
        is pressed. Returns the row's reading."""
        r = self.row(page)
        step, what = want
        self.assertEqual(r["cut"], [], where)
        self.assertEqual(r["past"], {"nav": False, "next": False}, where)
        self.assertFalse(r["scrolls"], where)
        if step == "tabs":
            self.assertEqual((r["fit"] if r["n"] else None, r["shown"]), ("more" if r["n"] else None, what), where)
            self.assertEqual(r["n"], 12 - len(what), where)
        else:
            self.assertEqual((r["fit"], r["shown"], r["current"] in KEYS), (step, [], True), where)
            name = page.evaluate("docInfo(DOC).name")
            self.assertTrue(r["name"].startswith(name + " — "), (where, r["name"]))  # the visible name is in the name
            if step == "name":
                self.assertEqual((r["label"], r["labelCut"]), (name, what == "…"), where)
                if what != "…":
                    self.assertEqual(r["label"], what, where)
        hit = page.evaluate(
            "(()=>{const m=document.querySelector('#doc-more'); if(!m.getClientRects().length) return null; const b=m.getBoundingClientRect();"
            " const h=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2); return !!h&&m.contains(h);})()"
        )
        if hit is not None:
            self.assertTrue(hit, where)
        return r


class LadderShort(LadderBase):
    """The landscape phone's one row, with and without its status line's message, at device scale factors 1 and 2."""

    def test_each_width_takes_its_step(self):
        """Each short-band width and status takes the chosen step (LADDER_SHORT); with the status line's message its
        icon and [재빌드] stay, and its words are whole - or, at 667px where the row is down to its icon and they still do
        not fit, not drawn at all (never a one- or two-letter stub)."""
        for (size, stale), want in LADDER_SHORT.items():
            for dpr in (1, 2):
                with self.subTest(size=size, stale=stale, dpr=dpr):
                    self.STALE = stale
                    page = self.view(touch(*SHORT[size], dpr), "ms")
                    if stale:
                        page.wait_for_function("document.querySelector('#doc-nav #status:not([hidden])')")
                        settle(page)
                    self.check_step(page, want, (size, stale, dpr))
                    if stale:
                        st = page.evaluate(
                            "(s=>({act: !!s.querySelector('button') && s.querySelector('button').getClientRects().length>0,"
                            " icon: !!s.querySelector('.st-ic') && s.querySelector('.st-ic').getClientRects().length>0}))(document.querySelector('#status'))"
                        )
                        self.assertEqual(st, {"act": True, "icon": True})
                        words = page.evaluate(
                            "(t=>!t.getClientRects().length?'hidden':t.scrollWidth>t.clientWidth?'cut':'whole')(document.querySelector('#status .st-tx'))"
                        )
                        self.assertEqual(words, "hidden" if want[0] == "icon" else "whole", (size, dpr))


class LadderLong(LadderBase):
    """Names of the server's longest, Hangul and Latin, on the tablets, a foldable and the crowded desktop."""

    DOCS = LONG

    def test_each_screen_takes_its_step(self):
        """With a 40-character name current each screen takes the chosen step (LADDER_LONG), at scale factors 1 and 2;
        the crowded desktop keeps the instance's name whole."""
        devs = {
            "tablet 768x1024": BARS["tablet 768x1024"],
            "fold inner 673x841": BARS["fold inner 673x841"],
            "crowded 1100x800": CROWDED,
        }
        for (name, doc), want in LADDER_LONG.items():
            for dpr in (1, 2):
                with self.subTest(viewport=name, doc=doc, dpr=dpr):
                    page = self.view(dict(devs[name], device_scale_factor=dpr), doc)
                    self.check_step(page, want, (name, doc, dpr))
                    if name.startswith("crowded"):
                        self.assertFalse(page.evaluate(NAME_CUT))

    def test_the_chooser_opens_the_popover_and_says_the_document(self):
        """On 673x841 with the long Hangul name current, a tap on the chooser opens the popover under it (the current row
        focused); its name is '<the document> — 문서 12개 중 고르기' and in English '... — choose from 12 documents'."""
        page = self.view(BARS["fold inner 673x841"], "rr")
        name = page.evaluate("docInfo('rr').name")
        self.assertEqual(self.row(page)["name"], name + " — 문서 12개 중 고르기")
        p = self.open_menu(page)
        self.assertEqual((p["open"], p["focus"]), (True, "rr"))
        self.assertAlmostEqual(p["box"][1], round(p["button"][3]) + 4, delta=0.01)
        page = self.view(BARS["fold inner 673x841"], "rr", lang="en")
        self.assertEqual(self.row(page)["name"], name + " — choose from 12 documents")


def test_the_fit_rule_on_chosen_widths():
    """docTabsShown on widths chosen by hand: all fit; the first k and [+N]; the current one in the last place; and none
    when not even one link and the button fit. docChooser: the name while room holds it whole or three em past the chooser's
    own width, else the icon."""
    js = "\n".join(
        [
            extract_js_fn("docTabsShown"),
            extract_js_fn("docChooser"),
            "const w=[50,50,50,50,50], more=n=>30;",
            "console.log(JSON.stringify([docTabsShown(w,10,0,290,more), docTabsShown(w,10,0,210,more),"
            " docTabsShown(w,10,4,210,more), docTabsShown(w,10,2,210,more), docTabsShown(w,10,3,60,more),"
            " docChooser(120,200,40,12), docChooser(76,200,40,12), docChooser(75,200,40,12), docChooser(50,50,40,12), docChooser(49,50,40,12)]));",
        ]
    )
    # 5 links take 290; in 210 three links (170) and the button (10 + 30) fit; the fifth current replaces the third; in 60
    # one link and the button (90) do not fit. A 200px name in 120: shortened (40 + 36 = 76 is the least); in 75 the icon; a
    # 50px name fits whole in 50.
    assert json.loads(run_node(js)) == [
        [0, 1, 2, 3, 4],
        [0, 1, 2],
        [0, 1, 4],
        [0, 1, 2],
        [],
        "name",
        "name",
        "icon",
        "name",
        "icon",
    ]
