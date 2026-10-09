"""In-document text search in the viewer (docs/handbook/viewer.md §본문 검색).

The pure parts - folding text for matching, grouping PDF.js text items into lines, finding, stepping, the field's width
rule and a hit's box - run under node on the served source. The rest runs in Chromium against the in-process server with
a hand-built PDF (search_pdf): Latin in Helvetica and Hangul in a CID font that only a ToUnicode map names, so PDF.js
reads real text without any TeX tool. The geometry classes measure the field against its row on the fixed viewports of
the search work (desktop 1440x900 with a mouse; phones 390x844 and 320x720; tablets 768x1024 and 1024x768; a foldable's
outer 344x882 and inner 673x841 and 841x673, all touch), at a device pixel ratio of 2.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_search.py
"""

import base64
import json
import shutil
import unicodedata
import unittest
from pathlib import Path

from hypothesis import given, settings, strategies as st

import helpers_figure
from helpers import blank_png, extract_js_fn, minimal_pdf, ps, run_node
from helpers_browser import BrowserBase, booted, fonts_ready, settle, watch_idle

# ---------------------------------------------------------------- the fixture PDF

LETTER = (612, 792)
# The fixture's pages: each line is (x, baseline y, [(font, text)]) at 12pt on a US Letter page. F1 is Helvetica (Latin),
# F2 the CID font (anything; every character is its own glyph one em wide). What each line is for:
PAGES = [
    [
        (72, 700, [("F1", "Shore station notes")]),
        (72, 676, [("F1", "The tide turns twice a day and the Tide table hangs by the door.")]),  # two hits, one line
        (72, 652, [("F1", "A quiet dawn; the first")]),  # 'first reading' breaks across these two lines
        (72, 628, [("F1", "reading comes later.")]),
        (72, 604, [("F1", "Tide "), ("F2", "조류"), ("F1", " height")]),  # one line, three text items
        (72, 580, [("F2", "관측소의 조류 기록")]),
        (72, 556, [("F2", unicodedata.normalize("NFD", "한낮 관측"))]),  # stored as conjoining jamo
        (72, 532, [("F2", unicodedata.normalize("NFD", "résumé") + " of the day")]),  # e + combining acute
        (72, 508, [("F1", "ob-")]),  # 'observation' hyphenated across a line break
        (72, 484, [("F1", "servation")]),
    ],
    [
        (72, 700, [("F1", "Midday: the tide is high.")]),
        (72, 676, [("F2", "조류는 하루에 두 번 바뀐다")]),
        (72, 652, [("F1", "wind    speed   4.1")]),  # runs of spaces
    ],
    [
        (72, 700, [("F1", "Evening tide. TIDE. tide")]),
        (72, 300, [("F1", "The last line of the fixture mentions the ebb once.")]),
    ],
]


def search_pdf(pages=PAGES):
    """A PDF of `pages` (the PAGES shape) that PDF.js reads as text: F1 is the standard Helvetica, F2 an unembedded CID
    font whose ToUnicode map gives each code its character, so Hangul - composed or as jamo - and combining marks come
    back from getTextContent() exactly as written here."""
    chars = sorted({c for page in pages for _, _, runs in page for font, text in runs if font == "F2" for c in text})
    cid = {c: i + 1 for i, c in enumerate(chars)}

    def utf16(c):
        """The character as UTF-16BE hex, a ToUnicode map's target."""
        return c.encode("utf-16-be").hex().upper()

    def show(font, text):
        """The operators that set `font` at 12pt and show `text` in it."""
        if font == "F2":
            return "/F2 12 Tf <%s> Tj" % "".join("%04X" % cid[c] for c in text)
        return "/F1 12 Tf (%s) Tj" % text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    maps = ["<%04X> <%s>" % (n, utf16(c)) for c, n in cid.items()]
    blocks = [maps[i : i + 100] for i in range(0, len(maps), 100)]
    cmap = (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        + "".join("%d beginbfchar\n%s\nendbfchar\n" % (len(b), "\n".join(b)) for b in blocks)
        + "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend"
    ).encode("ascii")

    def stream(data):
        """A stream object's body for `data`."""
        return b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"

    n = len(pages)
    kids = " ".join("%d 0 R" % (8 + 2 * i) for i in range(n))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /LimnFixture /Encoding /Identity-H"
        b" /DescendantFonts [5 0 R] /ToUnicode 7 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /LimnFixture"
        b" /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >>"
        b" /FontDescriptor 6 0 R /DW 1000 /CIDToGIDMap /Identity >>",
        b"<< /Type /FontDescriptor /FontName /LimnFixture /Flags 4 /FontBBox [0 -200 1000 900]"
        b" /ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 700 /StemV 80 >>",
        stream(cmap),
    ]
    for i, page in enumerate(pages):
        body = "\n".join(
            "BT 1 0 0 1 %d %d Tm %s ET" % (x, y, " ".join(show(f, t) for f, t in runs)) for x, y, runs in page
        )
        objs.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R"
                " /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>" % (*LETTER, 9 + 2 * i)
            ).encode()
        )
        objs.append(stream(body.encode("ascii")))
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


# ---------------------------------------------------------------- the pure parts, under node


def node_json(test, js):
    """Run js under node and return what it printed as JSON; skip the calling test when node is missing."""
    if not shutil.which("node"):
        test.skipTest("node not available")
    return json.loads(run_node(js))


class SearchLogic(unittest.TestCase):
    """The search's pure functions on the served source: what counts as the same text, what a line is, where the hits
    are, how the hits wrap, how wide the field is and where a hit's box lies."""

    def test_fold_ignores_case_width_composition_and_runs_of_spaces(self):
        """Upper case, a non-breaking space and a run of spaces, Hangul stored as jamo, a letter with a combining
        accent, the fi ligature and curly quotes or an en dash all fold to what a person types."""
        js = extract_js_fn("searchFold") + (
            "\nconsole.log(JSON.stringify(%s.map(s=>searchFold(s).t)));"
            % json.dumps(
                [
                    "The  TIDE\u00a0\t turns",
                    unicodedata.normalize("NFD", "한낮 관측"),
                    unicodedata.normalize("NFD", "Résumé"),
                    "de\ufb01ne \u2018it\u2019 2009\u20132010",
                    "soft\u00adhyphen",
                ]
            )
        )
        self.assertEqual(
            node_json(self, js),
            ["the tide turns", "한낮 관측", "résumé", "define 'it' 2009-2010", "softhyphen"],
        )

    def test_fold_maps_every_folded_character_back_to_its_source(self):
        """at[i] is where the source cluster of folded character i starts, and at ends with the source's length: the
        syllable built from three jamo points at the first, and both letters of a ligature at the ligature."""
        src = "A " + unicodedata.normalize("NFD", "한") + "\ufb01  x"
        js = extract_js_fn("searchFold") + "\nconsole.log(JSON.stringify(searchFold(%s)));" % json.dumps(src)
        self.assertEqual(node_json(self, js), {"t": "a 한fi x", "at": [0, 1, 2, 5, 5, 6, 8, 9]})

    @settings(max_examples=25, deadline=None)
    @given(st.lists(st.text(), min_size=1, max_size=30))
    def test_fold_keeps_its_map_in_step_for_any_text(self, values):
        """For any strings: the map has one entry per folded character plus the end, never steps back and stays inside
        the source, and the folded text has no run of spaces."""
        js = extract_js_fn("searchFold") + (
            "\nconsole.log(JSON.stringify(%s.map(s=>{const f=searchFold(s);return [f.t,f.at];})));" % json.dumps(values)
        )
        for value, (text, at) in zip(values, node_json(self, js), strict=True):
            units = len(value.encode("utf-16-le")) // 2
            self.assertEqual(len(at), len(text.encode("utf-16-le")) // 2 + 1, value)  # one entry a UTF-16 unit
            self.assertEqual(at, sorted(at), value)
            self.assertEqual(at[-1], units, value)
            self.assertTrue(all(0 <= i <= units for i in at), value)
            self.assertNotIn("  ", text)

    def test_lines_join_the_items_of_a_line_and_end_at_its_break(self):
        """Items up to one marked hasEOL are one line - whatever their fonts - with where each item's text starts; an
        empty item that only carries the mark ends the line too, and marked content (no str) is skipped."""
        items = [
            {"str": "Tide ", "hasEOL": False},
            {"type": "beginMarkedContent"},
            {"str": "조류", "hasEOL": False},
            {"str": " height", "hasEOL": True},
            {"str": "first", "hasEOL": False},
            {"str": "", "hasEOL": True},
            {"str": "reading", "hasEOL": False},
        ]
        js = "\n".join([extract_js_fn("searchFold"), extract_js_fn("searchLines")]) + (
            "\nconsole.log(JSON.stringify(searchLines(%s).map(l=>[l.t,l.parts])));" % json.dumps(items)
        )
        self.assertEqual(
            node_json(self, js),
            [
                ["tide 조류 height", [{"i": 0, "from": 0}, {"i": 2, "from": 5}, {"i": 3, "from": 7}]],
                ["first", [{"i": 4, "from": 0}]],
                ["reading", [{"i": 6, "from": 0}]],
            ],
        )

    def test_find_lists_every_occurrence_without_overlap(self):
        """Occurrences are listed left to right and never overlap; an empty query finds nothing."""
        js = extract_js_fn("searchFind") + (
            "\nconsole.log(JSON.stringify([searchFind('tide and tide. tide','tide'),searchFind('aaaa','aa'),"
            "searchFind('abc','x'),searchFind('abc','')]));"
        )
        self.assertEqual(node_json(self, js), [[0, 9, 15], [0, 2], [], []])

    def test_step_wraps_both_ways(self):
        """Next after the last hit is the first and previous before the first is the last; with no current hit the
        first step forward is the first hit and backward the last; with no hits there is none."""
        js = extract_js_fn("searchStep") + (
            "\nconsole.log(JSON.stringify([searchStep(0,3,1),searchStep(2,3,1),searchStep(0,3,-1),"
            "searchStep(-1,3,1),searchStep(-1,3,-1),searchStep(0,0,1)]));"
        )
        self.assertEqual(node_json(self, js), [1, 0, 2, 0, 2, -1])

    def test_width_is_full_then_the_room_down_to_the_minimum_then_none(self):
        """With room for it the field is its full width; with less it takes the room, in whole pixels, down to the
        minimum; under the minimum it is 0 - the magnifier alone."""
        js = extract_js_fn("searchWidth") + (
            "\nconsole.log(JSON.stringify([400,240,239.6,200,199.9,0,-30].map(r=>searchWidth(r,240,200))));"
        )
        self.assertEqual(node_json(self, js), [240, 240, 239, 200, 0, 0, 0])

    def test_box_is_the_run_of_characters_on_the_page(self):
        """A 12pt item at (72, 700) on a 612x792 page, 100pt wide, measured at ten units a character: characters 2-5
        of ten lie 20-50pt along it, between the font's ascent above and its descent below the baseline; a quarter
        turn puts the same run along the page's height."""
        js = extract_js_fn("searchBox") + (
            "\nconst m=s=>s.length*10,st={ascent:0.9,descent:-0.2,fontFamily:'serif'},vt=[1,0,0,-1,0,792];"
            "const up={str:'abcdefghij',width:100,transform:[12,0,0,12,72,700]};"
            "const turned={str:'abcdefghij',width:100,transform:[0,12,-12,0,72,700]};"
            "const r=b=>b.map(v=>Math.round(v*1e4)/1e4);"
            "console.log(JSON.stringify([r(searchBox(up,st,vt,612,792,2,5,m)),r(searchBox(turned,st,vt,612,792,2,5,m)),"
            "r(searchBox(up,{},vt,612,792,0,10,m))]));"
        )
        got = node_json(self, js)
        self.assertEqual(
            got[0], [round(92 / 612, 4), round((92 - 10.8) / 792, 4), round(30 / 612, 4), round(13.2 / 792, 4)]
        )
        self.assertEqual(
            got[1], [round((72 - 10.8) / 612, 4), round((92 - 50) / 792, 4), round(13.2 / 612, 4), round(30 / 792, 4)]
        )
        self.assertEqual(got[2][0], round(72 / 612, 4))  # no font metrics: the whole item, with a default ascent
        self.assertEqual(got[2][2], round(100 / 612, 4))


# ---------------------------------------------------------------- the real viewer

TOUCH = {"is_mobile": True, "has_touch": True}


def device(w, h, touch=True):
    """A w x h CSS px viewport at a device pixel ratio of 2: a touch screen (coarse pointer) unless touch is False."""
    return dict({"viewport": {"width": w, "height": h}, "device_scale_factor": 2}, **(TOUCH if touch else {}))


DESKTOP = device(1440, 900, touch=False)
# The viewports with a nav bar, by the band each lands in, and the phones (no nav bar).
BARS = {
    "desktop 1440x900": DESKTOP,
    "tablet 768x1024": device(768, 1024),
    "tablet 1024x768": device(1024, 768),
    "fold inner 673x841": device(673, 841),
    "fold inner 841x673": device(841, 673),
}
PHONES = {"phone 390x844": device(390, 844), "phone 320x720": device(320, 720), "fold outer 344x882": device(344, 882)}

# Until the PDF is open and no page is being drawn: the search reads the open document's text.
PDF_READY = "typeof VEC!=='undefined'&&!!VEC.doc&&!VEC.pumping&&!VEC.cur"
# The count once every page has been read: 'n/m' with no trailing ellipsis.
COUNTED = "/^\\d+\\/\\d+$/.test(document.querySelector('#search-count').textContent)"
# A fallback for the interface font in place of the bundled Pretendard: the given generic family alone.
FONT = (
    "document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');"
    "s.textContent=':root:root{--font-sans:%s}';document.head.append(s);});"
)

# The nav bar as drawn: its box and the band its controls are centred in (from the stripe's bottom to the bar's bottom),
# the visible children in order, each named control's box, and how far the bar's content spills past it.
BAR = """() => {const q = s => document.querySelector(s), vis = e => !!e && e.getClientRects().length > 0;
  const R = e => {const r = e.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height, m: (r.top + r.bottom) / 2};};
  const nav = q('#doc-nav'), cs = getComputedStyle(nav), out = {nav: R(nav), kids: [...nav.children].filter(vis).map(e => e.id)};
  out.band = {t: q('#brand-stripe').getBoundingClientRect().bottom, b: out.nav.b};
  out.padL = parseFloat(cs.paddingLeft); out.padR = parseFloat(cs.paddingRight); out.gap = parseFloat(cs.columnGap);
  out.spill = nav.scrollWidth - nav.clientWidth;
  for (const [k, s] of [['box', '#search-box'], ['search', '#doc-search'], ['open', '#search-open'], ['icon', '#search-field .ic'],
      ['q', '#search-q'], ['hint', '#search-hint'], ['count', '#search-count'], ['prev', '#search-prev'], ['next', '#search-next'],
      ['close', '#search-close'], ['toc', '#nav-toc-toggle'], ['tocIcon', '#nav-toc-toggle .ic'], ['links', '#doc-links'],
      ['view', '#view-switch'], ['viewLbl', '#view-manuscript .lbl'], ['page', '#nav-page'], ['side', '#nav-side']])
    out[k] = vis(q(s)) ? R(q(s)) : null;
  out.mode = q('#doc-search').dataset.mode; out.linksCut = q('#doc-links').scrollWidth - q('#doc-links').clientWidth;
  return out;}"""

# Every visible element matching the selector whose tap area is under 44px wide or high, as "name WxH(hit wxh)": from its
# centre, the px that still answer it going left, right, up and down (each side counted to 60px).
MISSES_44 = """sel => {const out = [];
  const own = (e, x, y) => {if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return false;
    const h = document.elementFromPoint(x, y); return !!h && (h === e || e.contains(h));};
  for (const e of document.querySelectorAll(sel)) {const r = e.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2; let l = 0, ri = 0, u = 0, d = 0;
    if (own(e, cx, cy)) {while (l < 60 && own(e, cx - l - 1, cy)) l++; while (ri < 60 && own(e, cx + ri + 1, cy)) ri++;
      while (u < 60 && own(e, cx, cy - u - 1)) u++; while (d < 60 && own(e, cx, cy + d + 1)) d++;}
    const w = l + ri + 1, h = u + d + 1;
    if (w < 44 || h < 44) out.push('#' + e.id + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + '(hit ' + w + 'x' + h + ')');}
  return out;}"""

# The vertical centre of the ink in each box of a screenshot (base64 PNG at device pixel ratio dpr; boxes [l, t, r, b] in
# the shot's CSS px): the rows holding a pixel that differs from the box's top-left pixel, the first and last counted by
# how strongly they differ. null for a box with no ink.
INK_MID = """async ([b64, dpr, boxes]) => {const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.drawImage(img, 0, 0);
  const D = x.getImageData(0, 0, c.width, c.height).data, W = c.width;
  const lum = (X, Y) => {const i = (Y * W + X) * 4; return 0.2126 * D[i] + 0.7152 * D[i + 1] + 0.0722 * D[i + 2];};
  return boxes.map(([l, t, r, b]) => {const X0 = Math.round(l * dpr), X1 = Math.round(r * dpr), Y0 = Math.round(t * dpr), Y1 = Math.round(b * dpr), bg = lum(X0, Y0);
    let mx = 0; const rows = [];
    for (let y = Y0; y < Y1; y++) {let m = 0; for (let xx = X0; xx < X1; xx++) m = Math.max(m, Math.abs(lum(xx, y) - bg)); rows.push(m); mx = Math.max(mx, m);}
    if (mx < 8) return null; let f = -1, la = -1; rows.forEach((v, i) => {if (v / mx > 0.12) {if (f < 0) f = i; la = i;}});
    return ((Y0 + f + 1 - rows[f] / mx) + (Y0 + la + rows[la] / mx)) / 2 / dpr;});}"""


class SearchBase(BrowserBase):
    """BrowserBase with the fixture PDF as the build on screen (three pages) and the device presets of the search
    work."""

    def setUp(self):
        """The manuscript's build gets a third page image and search_pdf() as its PDF copy."""
        super().setUp()
        doc = ps.APP.docs[0]
        pages = Path(doc.dir) / (Path(doc.dir) / "pages.cur").read_text().strip()
        (pages / "page-3.png").write_bytes(blank_png(1275, 1650))
        (pages / doc.pdf_name).write_bytes(search_pdf())
        self.pages_dir = pages

    def view(self, dev=DESKTOP, lang="ko", dark=False, init=None):
        """The viewer on dev, booted, its PDF open and its pages drawn, settled; first-visit hints are pre-seen."""
        prefs = {"coach": {"touch": 1, "mouse": 1, "sel": 1, "side": 1}, "theme": "dark" if dark else "light"}
        context = self.browser.new_context(**dev)
        self.addCleanup(context.close)
        context.add_init_script(
            "try{if(!sessionStorage.getItem('__t')){sessionStorage.setItem('__t','1');"
            "localStorage.setItem('pinPrefs',%s);}}catch(e){}" % json.dumps(json.dumps(prefs))
        )
        if init:
            context.add_init_script(init)
        watch_idle(context)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=%s" % lang)
        page.wait_for_function(booted(0), timeout=20000)
        page.wait_for_function(PDF_READY, timeout=20000)
        settle(page)
        page.wait_for_function(
            PDF_READY, timeout=20000
        )  # a redraw the settling queued (fonts, a re-fit) has finished too
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def search(self, page, text):
        """Type text into the field (focusing it first) and wait until every page has been read and counted."""
        page.focus("#search-q")
        page.fill("#search-q", text)
        page.wait_for_function(COUNTED, timeout=8000)
        settle(page)

    @staticmethod
    def count(page):
        """The count as shown, 'n/m'."""
        return page.text_content("#search-count")

    @staticmethod
    def hits(page):
        """The hit boxes drawn on the pages near the view: [{page, cur, box: [x, y, w, h] as page fractions}]."""
        return page.evaluate(
            """() => [...document.querySelectorAll('.pg .search-hit')].map(h => {const p = h.parentElement.getBoundingClientRect(), r = h.getBoundingClientRect();
              return {page: +h.parentElement.dataset.page, cur: h.classList.contains('cur'),
                box: [(r.left - p.left - h.parentElement.clientLeft) / h.parentElement.clientWidth, (r.top - p.top - h.parentElement.clientTop) / h.parentElement.clientHeight,
                  r.width / h.parentElement.clientWidth, r.height / h.parentElement.clientHeight]};})"""
        )

    @staticmethod
    def current(page):
        """The current hit: {page, top, bottom, left, right} in viewport px with the PDF area's free band (top, bottom),
        or None with no current hit drawn."""
        return page.evaluate(
            """() => {const h = document.querySelector('.search-hit.cur'); if (!h) return null; const r = h.getBoundingClientRect(), a = searchArea();
              return {page: +h.parentElement.dataset.page, top: r.top, bottom: r.bottom, left: r.left, right: r.right, areaTop: a.top, areaBottom: a.bottom};}"""
        )


class SearchFinds(SearchBase):
    """What a query finds in the fixture and how its hits are shown and stepped through."""

    def test_latin_hits_are_counted_across_pages_whatever_their_case(self):
        """'tide' is on page 1 three times, page 2 once and page 3 three times - 'Tide' and 'TIDE' included: 1/7, the
        first one current, and the pages near the view carry one box a hit."""
        page = self.view()
        self.search(page, "tide")
        self.assertEqual(self.count(page), "1/7")
        self.assertEqual(page.evaluate("SEARCH.hits.map(h=>h.page)"), [1, 1, 1, 2, 3, 3, 3])
        drawn = self.hits(page)
        self.assertEqual([h["page"] for h in drawn if h["page"] == 1], [1, 1, 1])
        self.assertEqual([h["cur"] for h in drawn if h["page"] == 1], [True, False, False])

    def test_a_hit_box_lies_on_its_words(self):
        """The first 'tide' of page 1's second line: it starts 24pt after the line's left edge at x=72pt ('The ' in
        12pt Helvetica) and is 19pt wide, and its box holds the baseline at y=676pt with the letters above it."""
        page = self.view()
        self.search(page, "tide")
        x, y, w, h = self.hits(page)[0]["box"]
        self.assertAlmostEqual(x, 96 / 612, delta=0.012)
        self.assertAlmostEqual(w, 19.3 / 612, delta=0.012)
        base = (792 - 676) / 792
        self.assertLess(y, base - 0.6 * 12 / 792)  # reaches above the x-height
        self.assertGreater(y, base - 1.3 * 12 / 792)  # and not into the line above
        self.assertGreaterEqual(y + h, base - 0.001)
        self.assertLess(y + h, base + 0.5 * 12 / 792)

    def test_hangul_is_found_composed_or_as_jamo_and_latin_with_a_combining_accent(self):
        """'조류' is on page 1 twice and page 2 once; '한낮' and 'résumé' are stored decomposed in the PDF and found by
        the composed text a person types."""
        page = self.view()
        self.search(page, "조류")
        self.assertEqual(self.count(page), "1/3")
        self.assertEqual(page.evaluate("SEARCH.hits.map(h=>h.page)"), [1, 1, 2])
        self.search(page, "한낮")
        self.assertEqual(self.count(page), "1/1")
        self.search(page, "résumé")
        self.assertEqual(self.count(page), "1/1")
        box = self.hits(page)[0]["box"]
        self.assertGreater(box[2], 5 * 12 / 612)  # all six letters and their accents, one em each

    def test_a_query_spans_the_text_items_of_a_line_but_not_a_line_break(self):
        """'tide 조류 height' crosses three text items of one line and is one hit with one box over all three; runs
        of spaces match one space; 'first reading' and 'observation' break across lines and are not found."""
        page = self.view()
        self.search(page, "Tide 조류 height")
        self.assertEqual(self.count(page), "1/1")
        (hit,) = self.hits(page)
        self.assertAlmostEqual(hit["box"][0], 72 / 612, delta=0.004)
        self.assertGreater(hit["box"][2], 80 / 612)
        self.search(page, "wind speed 4.1")
        self.assertEqual(self.count(page), "1/1")
        for missing in ("first reading", "observation"):
            self.search(page, missing)
            self.assertEqual(self.count(page), "0/0", missing)
            self.assertEqual(self.hits(page), [])
            self.assertTrue(page.is_disabled("#search-next"))

    def test_enter_goes_on_shift_enter_goes_back_and_both_wrap(self):
        """From 1/7: Enter twice is 3/7, Shift+Enter three times wraps to 7/7 on page 3, Enter wraps to 1/7 on page 1;
        each time the current hit is in the free part of the PDF area. The arrows do the same."""
        page = self.view()
        self.search(page, "tide")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        self.assertEqual(self.count(page), "3/7")
        for _ in range(3):
            page.keyboard.press("Shift+Enter")
        settle(page)
        self.assertEqual(self.count(page), "7/7")
        cur = self.current(page)
        self.assertEqual(cur["page"], 3)
        self.assertGreaterEqual(cur["top"], cur["areaTop"])
        self.assertLessEqual(cur["bottom"], cur["areaBottom"])
        page.keyboard.press("Enter")
        settle(page)
        self.assertEqual(self.count(page), "1/7")
        self.assertEqual(self.current(page)["page"], 1)
        page.click("#search-prev")
        self.assertEqual(self.count(page), "7/7")
        page.click("#search-next")
        self.assertEqual(self.count(page), "1/7")
        self.assertEqual(page.evaluate("document.querySelectorAll('.search-hit.cur').length"), 1)

    def test_the_first_hit_is_the_first_one_from_the_page_on_screen(self):
        """Scrolled to page 3, 'tide' starts at its first hit there: 5/7."""
        page = self.view()
        page.evaluate("document.getElementById('p3').scrollIntoView()")
        settle(page)
        self.search(page, "tide")
        self.assertEqual(self.count(page), "5/7")
        self.assertEqual(self.current(page)["page"], 3)

    def test_the_count_grows_while_pages_are_read_and_drawing_goes_first(self):
        """While a page is being drawn no text is read and the count says it is not final ('…'); once drawing is done
        the pages are read one by one and the count ends at 1/7."""
        page = self.view()
        page.evaluate("VEC.pumping=true")
        page.focus("#search-q")
        page.fill("#search-q", "tide")
        page.wait_for_function("document.querySelector('#search-count').textContent==='0/0…'")
        self.assertEqual(page.evaluate("searchPages(VEC.doc).filter(Boolean).length"), 0)
        page.evaluate("VEC.pumping=false")
        page.wait_for_function(COUNTED, timeout=8000)
        self.assertEqual(self.count(page), "1/7")
        self.assertEqual(page.evaluate("searchPages(VEC.doc).filter(Boolean).length"), 3)

    def test_the_text_is_read_once_a_build(self):
        """A second query reads no page again: the text of the build on screen is kept."""
        page = self.view()
        self.search(page, "tide")
        page.evaluate(
            "(()=>{window.__reads=0; const g=VEC.doc.getPage.bind(VEC.doc); VEC.doc.getPage=async n=>{const p=await g(n),"
            "t=p.getTextContent.bind(p); p.getTextContent=(...a)=>{window.__reads++; return t(...a);}; return p;};})()"
        )
        self.search(page, "조류")
        self.assertEqual(self.count(page), "1/3")
        self.assertEqual(page.evaluate("window.__reads"), 0)


class SearchKeys(SearchBase):
    """The shortcut, Esc and what typing in the field leaves alone."""

    @staticmethod
    def watch_keys(page):
        """Record, for each keydown that reaches the window, whether the viewer prevented its default."""
        page.evaluate("window.__kd=[]; addEventListener('keydown',e=>window.__kd.push([e.key,e.defaultPrevented]))")

    def test_ctrl_f_focuses_the_field_and_a_second_one_is_the_browsers(self):
        """Outside Apple platforms Ctrl+F from another control focuses the field and is not the browser's; pressed
        again in the field it is left to the browser's own find. The hint names the key."""
        page = self.view()
        self.watch_keys(page)
        page.focus("#jump")
        page.keyboard.press("Control+f")
        self.assertEqual(page.evaluate("document.activeElement.id"), "search-q")
        page.keyboard.press("Control+f")
        self.assertEqual(page.evaluate("window.__kd.filter(k=>k[0]==='f')"), [["f", True], ["f", False]])
        self.assertEqual(page.text_content("#search-hint"), "Ctrl F")

    def test_on_an_apple_platform_the_shortcut_is_command_f(self):
        """With navigator.platform MacIntel, ⌘F focuses the field, Ctrl+F does not, and the hint reads ⌘F."""
        page = self.view(init="Object.defineProperty(navigator,'platform',{get:()=>'MacIntel'});")
        self.watch_keys(page)
        page.keyboard.press("Control+f")
        self.assertNotEqual(page.evaluate("document.activeElement.id"), "search-q")
        page.keyboard.press("Meta+f")
        self.assertEqual(page.evaluate("document.activeElement.id"), "search-q")
        self.assertEqual(page.evaluate("window.__kd.filter(k=>k[0]==='f')"), [["f", False], ["f", True]])
        self.assertEqual(page.text_content("#search-hint"), "⌘F")

    def test_esc_clears_the_search_and_gives_the_focus_back(self):
        """Esc in the field empties it, removes every hit box and returns the focus to the control that had it."""
        page = self.view()
        page.focus("#jump")
        page.keyboard.press("Control+f")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTED)
        self.assertGreater(len(self.hits(page)), 0)
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.hits(page), [])
        self.assertEqual(self.count(page), "")
        self.assertEqual(page.evaluate("document.activeElement.id"), "jump")
        self.assertFalse(page.evaluate("document.body.classList.contains('search-open')"))

    def test_the_close_button_does_what_esc_does(self):
        """[검색 닫기] empties the field, removes the hits and returns the focus."""
        page = self.view()
        page.focus("#jump")
        page.keyboard.press("Control+f")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTED)
        page.click("#search-close")
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.hits(page), [])
        self.assertEqual(page.evaluate("document.activeElement.id"), "jump")

    def test_typing_in_the_field_runs_no_viewer_shortcut(self):
        """'?' typed in the field is a character, not help; Ctrl+= and Ctrl+\\ there neither zoom the page nor fold
        the panel."""
        page = self.view()
        before = page.evaluate("[W,SIDE_OPEN]")
        page.focus("#search-q")
        page.keyboard.type("a?")
        page.keyboard.press("Control+=")
        page.keyboard.press("Control+\\")
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "a?")
        self.assertFalse(page.evaluate("document.querySelector('#help').open"))
        self.assertEqual(page.evaluate("[W,SIDE_OPEN]"), before)

    def test_a_draft_its_selection_and_the_note_popover_survive_a_search(self):
        """With a region picked and a note half written in the popover by the box, Ctrl+F, a query, Enter and Esc
        leave the composer open on the same lines, the dashed box drawn, the note as typed in both fields, and put
        the focus back in the note."""
        page = self.view()
        box = page.evaluate(
            "(()=>{const r=document.getElementById('p1').getBoundingClientRect(); return [r.left+r.width*0.2,r.top+r.height*0.4,r.left+r.width*0.5,r.top+r.height*0.45];})()"
        )
        page.mouse.move(box[0], box[1])
        page.mouse.down()
        page.mouse.move(box[2], box[3], steps=4)
        page.mouse.up()
        page.wait_for_function(
            "COMPOSE.current&&COMPOSE.current.lo&&!document.querySelector('#sel-pop').hidden", timeout=8000
        )
        page.keyboard.type("초안 메모")
        settle(page)
        lines = page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]")
        page.keyboard.press("Control+f")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTED)
        page.keyboard.press("Enter")
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi]"), lines)
        self.assertFalse(page.evaluate("document.querySelector('#composer').hidden"))
        self.assertTrue(page.evaluate("!!COMPOSE.box&&document.contains(COMPOSE.box)"))
        self.assertEqual(page.input_value("#note"), "초안 메모")
        self.assertEqual(page.input_value("#sel-pop textarea"), "초안 메모")
        self.assertFalse(page.evaluate("document.querySelector('#sel-pop').hidden"))
        self.assertEqual(page.evaluate("document.activeElement.closest('#sel-pop')!==null"), True)

    def test_select_mode_stays_on_through_a_search(self):
        """On a tablet with the select mode on, opening the search, a query and closing it leave the mode on."""
        page = self.view(BARS["tablet 1024x768"])
        page.evaluate("setSelMode(true)")
        settle(page)
        page.evaluate("searchOpen()")
        page.fill("#search-q", "tide")
        page.wait_for_function(COUNTED)
        page.evaluate("searchClose(true)")
        settle(page)
        self.assertTrue(page.evaluate("SELMODE&&document.body.classList.contains('selmode')"))


class SearchScope(SearchBase):
    """Where the search ends: another document, a new build, the changes view."""

    def test_a_rebuild_clears_the_search(self):
        """A new build of the document on screen removes the query, its hits and the count."""
        page = self.view()
        self.search(page, "tide")
        doc = ps.APP.docs[0]
        newer = Path(doc.dir) / "pages-20260925110000"
        shutil.copytree(self.pages_dir, newer)
        (Path(doc.dir) / "pages.cur").write_text(newer.name)
        page.evaluate("refreshDoc()")
        page.wait_for_function("META.pages_build==='%s'&&%s" % (newer.name, PDF_READY), timeout=8000)
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.hits(page), [])
        self.assertEqual(self.count(page), "")
        self.assertEqual(page.evaluate("[SEARCH.q,SEARCH.hits.length]"), ["", 0])

    def test_the_changes_view_has_no_search_and_ctrl_f_is_the_browsers_there(self):
        """Entering the changes view clears and hides the field, and Ctrl+F is left to the browser; back in the
        manuscript the field is there again, empty."""
        page = self.view()
        self.search(page, "tide")
        page.evaluate("setViewMode(VIEW_MODE.REVISIONS)")
        settle(page)
        self.assertFalse(page.is_visible("#doc-search"))
        self.assertEqual(page.evaluate("[SEARCH.q,document.querySelectorAll('.search-hit').length]"), ["", 0])
        page.evaluate("window.__kd=[]; addEventListener('keydown',e=>window.__kd.push([e.key,e.defaultPrevented]))")
        page.keyboard.press("Control+f")
        self.assertEqual(page.evaluate("window.__kd.filter(k=>k[0]==='f')"), [["f", False]])
        page.evaluate("setViewMode(VIEW_MODE.MANUSCRIPT)")
        settle(page)
        self.assertTrue(page.is_visible("#search-q"))
        self.assertEqual(page.input_value("#search-q"), "")


class SearchAcrossDocuments(BrowserBase):
    """Several documents: the search belongs to the document on screen."""

    def setUp(self):
        """The manuscript, the figure document and the view-only PDF; the manuscript's two-page build holds the
        fixture's first two pages."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)
        build = Path(self.ms.dir) / (Path(self.ms.dir) / "pages.cur").read_text().strip()
        (build / self.ms.pdf_name).write_bytes(search_pdf(PAGES[:2]))

    def test_switching_documents_clears_the_search(self):
        """With hits on the manuscript, switching to the view-only PDF empties the field and leaves no hit box; back
        on the manuscript the field is still empty."""
        page = self.open(0, **DESKTOP)
        page.wait_for_function(PDF_READY, timeout=20000)
        page.focus("#search-q")
        page.fill("#search-q", "tide")
        page.wait_for_function(COUNTED, timeout=8000)
        self.assertEqual(page.text_content("#search-count"), "1/4")
        page.evaluate("async k=>await switchDoc(k)", self.rv.key)
        page.wait_for_function("k=>DOC===k", arg=self.rv.key)
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(
            page.evaluate("[SEARCH.q,SEARCH.hits.length,document.querySelectorAll('.search-hit').length]"), ["", 0, 0]
        )
        page.evaluate("async k=>await switchDoc(k)", self.ms.key)
        page.wait_for_function("k=>DOC===k", arg=self.ms.key)
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "")


def crowded_docs(app, src, extra=5):
    """Serve the manuscript src/main.tex and `extra` view-only PDFs from app, each with a two-page build on screen and
    the manuscript's PDF holding the fixture's first two pages: a nav bar with a row of document links. Returns the
    documents, the manuscript first."""
    for i in range(extra):
        (src / ("extra%d.pdf" % i)).write_bytes(minimal_pdf("extra %d" % i))
    specs = ["ms=본문:main.tex"] + ["x%d=부록 문서 %d:extra%d.pdf" % (i, i + 1, i) for i in range(extra)]
    docs = helpers_figure.startup_documents.make_docs(specs, src, app.C.paths)
    assert isinstance(docs, list), docs
    app.set_docs(docs)
    for D in docs:
        helpers_figure.viewer_build(D, helpers_figure.BUILD1)
    ms = docs[0]
    (Path(ms.dir) / helpers_figure.BUILD1 / ms.pdf_name).write_bytes(search_pdf(PAGES[:2]))
    return docs


class SearchCrowdedBar(BrowserBase):
    """A bar with six document links: the field gives way before its neighbours do."""

    def setUp(self):
        """The manuscript and five view-only PDFs (crowded_docs)."""
        super().setUp()
        crowded_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)

    def bar(self, dev):
        """The viewer on dev with the manuscript's PDF open, and its page."""
        page = self.open(0, **dev)
        page.wait_for_function(PDF_READY, timeout=20000)
        settle(page)
        return page

    def test_the_field_shrinks_to_its_minimum_then_folds_to_the_magnifier(self):
        """A mouse window narrowed from 1090 to 710px: the field is its full 240px, then the room that is left, never
        under 200px, then the magnifier alone - and at every width the view switch ends before the search begins, the
        document links are not cut short while the field shows, and the bar does not spill."""
        page = self.bar(device(1090, 800, touch=False))
        seen = []
        for width in range(1090, 700, -10):
            page.set_viewport_size({"width": width, "height": 800})
            page.wait_for_function("innerWidth===%d&&BAND_IN.w===%d" % (width, width))
            settle(page)
            g = page.evaluate(BAR)
            seen.append((g["mode"], round(g["search"]["w"])))
            self.assertLessEqual(g["view"]["r"], g["search"]["l"] + 0.01, width)
            self.assertLessEqual(g["spill"], 0, width)
            if g["mode"] == "inline":
                self.assertLessEqual(g["linksCut"], 0, width)
                self.assertTrue(200 <= g["search"]["w"] <= 240, (width, g["search"]))
            else:
                self.assertEqual((g["mode"], g["box"]), ("icon", None), width)
                self.assertEqual((g["open"]["w"], g["open"]["h"]), (28, 28), width)
        modes = [m for m, _ in seen]
        self.assertEqual(modes, sorted(modes, key=["inline", "icon"].index), seen)  # once folded it stays folded
        self.assertEqual(seen[0], ("inline", 240))
        self.assertEqual(modes[-1], "icon")
        self.assertTrue(any(m == "inline" and 200 <= w < 240 for m, w in seen), seen)

    def test_the_folded_magnifier_opens_the_field_over_the_bar(self):
        """At 720px the magnifier is all there is; pressing it opens the field at its full width inside the bar, with
        a close button, and Esc folds it back with the focus on the magnifier."""
        page = self.bar(device(720, 800, touch=False))
        self.assertEqual(page.evaluate(BAR)["mode"], "icon")
        page.click("#search-open")
        settle(page)
        g = page.evaluate(BAR)
        self.assertEqual(page.evaluate("document.activeElement.id"), "search-q")
        self.assertEqual(g["box"]["w"], 240)
        self.assertGreaterEqual(g["box"]["l"], g["nav"]["l"] + g["padL"] - 0.01)
        self.assertAlmostEqual(g["box"]["r"], g["search"]["r"], delta=0.01)
        self.assertIsNotNone(g["close"])
        self.assertEqual(page.get_attribute("#search-open", "aria-expanded"), "true")
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.evaluate("document.activeElement.id"), "search-open")
        self.assertIsNone(page.evaluate(BAR)["box"])

    def test_on_touch_the_folded_magnifier_and_the_opened_field_answer_44px(self):
        """A foldable's inner screen (673x841, touch) has no room for the field beside six links: the magnifier is the
        outline toggle's 44px box and answers 44x44px; tapped, the field opens inside the bar, 36px high, and it, its
        arrows and its close button answer 44x44px."""
        page = self.bar(device(673, 841))
        g = page.evaluate(BAR)
        self.assertEqual(g["mode"], "icon")
        self.assertEqual(
            (g["open"]["t"], g["open"]["b"], g["open"]["w"]), (g["toc"]["t"], g["toc"]["b"], g["toc"]["w"])
        )
        self.assertEqual(page.evaluate(MISSES_44, "#search-open"), [])
        self.assertLessEqual(g["spill"], 0)
        page.tap("#search-open")
        page.fill("#search-q", "tide")
        page.wait_for_function(COUNTED, timeout=8000)
        settle(page)
        g = page.evaluate(BAR)
        self.assertEqual(g["box"]["h"], 36)
        self.assertGreaterEqual(g["box"]["l"], g["nav"]["l"] + g["padL"] - 0.01)
        self.assertLessEqual(g["box"]["r"], g["nav"]["r"] - g["padR"] + 0.01)
        self.assertEqual(page.evaluate(MISSES_44, "#search-field,#search-prev,#search-next,#search-close"), [])


class SearchBarGeometry(SearchBase):
    """The field's size and place in the nav bar on every viewport that has one (docs/handbook/viewer.md §본문 검색):
    measured, not judged."""

    def bar(self, dev, dark=False, init=None):
        """The viewer on dev and the bar's geometry (BAR)."""
        page = self.view(dev, dark=dark, init=init)
        self.assertEqual(fonts_ready(page), "loaded")
        return page, page.evaluate(BAR)

    def test_the_search_comes_after_the_view_switch_and_before_the_page_count(self):
        """In every bar the visible controls end ... view switch, search, and then the page count where the band has
        one; nothing spills out of the bar and the search's right neighbour is one bar gap away - or the search ends
        on the bar's content edge."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                _, g = self.bar(dev)
                tail = g["kids"][g["kids"].index("view-switch") :]
                self.assertEqual(tail, ["view-switch", "doc-search"] + (["nav-page"] if g["page"] else []))
                self.assertLessEqual(g["spill"], 0)
                self.assertEqual(g["mode"], "inline")
                self.assertEqual(g["search"]["w"], 240)
                if g["page"]:
                    self.assertAlmostEqual(g["page"]["l"] - g["search"]["r"], g["gap"], delta=0.01)
                    self.assertAlmostEqual(g["page"]["r"], g["nav"]["r"] - g["padR"], delta=0.01)
                else:
                    self.assertAlmostEqual(g["search"]["r"], g["nav"]["r"] - g["padR"], delta=0.01)
                self.assertGreaterEqual(g["search"]["l"] - g["view"]["r"], g["gap"] - 0.01)

    def test_a_collapsed_wide_panel_keeps_its_toggle_last(self):
        """With the desktop panel folded the bar ends ... search, [핀 N ‹]: the toggle stays at the bar's right end,
        one gap after the search."""
        page = self.view()
        page.evaluate("setSide(false)")
        settle(page)
        g = page.evaluate(BAR)
        self.assertEqual(g["kids"][-2:], ["doc-search", "nav-side"])
        self.assertAlmostEqual(g["side"]["l"] - g["search"]["r"], g["gap"], delta=0.01)
        self.assertAlmostEqual(g["side"]["r"], g["nav"]["r"] - g["padR"], delta=0.01)
        self.assertEqual((g["box"]["t"], g["box"]["b"]), (g["side"]["t"], g["side"]["b"]))

    def test_the_field_is_its_rows_control_height_and_centred_in_the_band(self):
        """With a mouse the field is the 28px control, its top and bottom on the outline toggle's; on touch it is drawn
        at 36px, 4px clear of the stripe above and of the bar's line below. Everywhere its centre is the band's, the
        outline toggle's and the view tab's label's, within half a pixel, and its icon is 16px on the same centre."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                _, g = self.bar(dev)
                touch = dev.get("has_touch", False)
                band = (g["band"]["t"] + g["band"]["b"]) / 2
                self.assertEqual(g["box"]["h"], 36 if touch else 28)
                if touch:
                    self.assertEqual((g["box"]["t"] - g["band"]["t"], g["band"]["b"] - g["box"]["b"]), (4, 4))
                else:
                    self.assertEqual((g["box"]["t"], g["box"]["b"]), (g["toc"]["t"], g["toc"]["b"]))
                for k in ("box", "toc", "tocIcon", "viewLbl", "icon"):
                    self.assertAlmostEqual(g[k]["m"], band, delta=0.5, msg=k)
                self.assertEqual((g["icon"]["w"], g["icon"]["h"]), (16, 16))
                self.assertEqual(g["icon"]["t"] % 1, 0)  # icons are drawn on whole pixels

    def test_showing_the_search_moves_nothing_before_it(self):
        """The view switch, the document links and the outline toggle stand where they stand without the search."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                page, g = self.bar(dev)
                page.evaluate("document.querySelector('#doc-search').hidden=true")
                bare = page.evaluate(BAR)
                for k in ("toc", "view", "viewLbl"):
                    self.assertEqual(g[k], bare[k], k)

    def test_spacing_is_on_the_4px_grid(self):
        """Every padding, margin and gap of the search's parts is a multiple of 4px, or a 1px hairline inset; the one
        exception is the search's left margin in the bar, which is the bar's flexible gap."""
        for name, dev in list(BARS.items()) + list(PHONES.items()):
            with self.subTest(viewport=name):
                page = self.view(dev)
                page.evaluate("searchOpen()")
                page.fill("#search-q", "tide")
                page.wait_for_function(COUNTED)
                off = page.evaluate(
                    """() => {const bad = []; for (const e of [document.querySelector('#doc-search'), ...document.querySelectorAll('#doc-search *')]) {
                      if (!e.getClientRects().length || e.closest('svg')) continue; const cs = getComputedStyle(e);
                      for (const p of ['paddingTop','paddingRight','paddingBottom','paddingLeft','marginTop','marginRight','marginBottom','marginLeft','columnGap','rowGap']) {
                        if (e.id === 'doc-search' && p === 'marginLeft') continue;
                        const v = parseFloat(cs[p]); if (!isNaN(v) && Math.abs(v) > 1 && v % 4 !== 0) bad.push((e.id || e.tagName) + ' ' + p + ' ' + cs[p]);}}
                      return bad;}"""
                )
                self.assertEqual(off, [])

    def test_the_hint_is_small_muted_right_aligned_and_gone_with_a_query(self):
        """On the desktop the empty field shows the shortcut at the smallest text size in the muted colour, its right
        end one 8px step inside the field's border and its centre on the field's; focusing the field keeps it, the
        first character removes it. Touch screens show no shortcut."""
        page, g = self.bar(DESKTOP)
        style = page.evaluate(
            "(()=>{const h=getComputedStyle(document.querySelector('#search-hint')),r=getComputedStyle(document.documentElement),"
            "p=document.createElement('i'); p.style.color='var(--muted-foreground)'; document.body.append(p); const c=getComputedStyle(p).color; p.remove();"
            "return [h.fontSize,getComputedStyle(document.querySelector('#search-q')).fontSize,h.color,c,r.getPropertyValue('--text-xs').trim()];})()"
        )
        self.assertEqual(style[0], style[4])
        self.assertLess(float(style[0][:-2]), float(style[1][:-2]))
        self.assertEqual(style[2], style[3])
        self.assertAlmostEqual(g["box"]["r"] - g["hint"]["r"], 8 + 1, delta=0.01)
        self.assertAlmostEqual(g["hint"]["m"], g["box"]["m"], delta=0.5)
        page.focus("#search-q")
        self.assertTrue(page.is_visible("#search-hint"))
        page.keyboard.type("t")
        self.assertFalse(page.is_visible("#search-hint"))
        page.keyboard.press("Backspace")
        self.assertTrue(page.is_visible("#search-hint"))
        touch = self.view(BARS["tablet 768x1024"])
        self.assertFalse(touch.is_visible("#search-hint"))

    def test_the_fields_parts_draw_no_box_inside_its_box(self):
        """The field's border is the one outline: the input, the count and the buttons inside it have no border and
        no outline of their own while the field shows its focus ring."""
        page = self.view()
        self.search(page, "tide")
        inner = page.evaluate(
            """() => [...document.querySelectorAll('#search-box *')].filter(e => e.getClientRects().length && !e.closest('svg')).map(e => {
              const cs = getComputedStyle(e); return [e.id || e.tagName, cs.borderTopWidth, cs.borderLeftWidth, cs.outlineStyle];}).filter(x => x[1] !== '0px' || x[2] !== '0px' || x[3] !== 'none')"""
        )
        self.assertEqual(inner, [])
        ring = page.evaluate(
            "(()=>{const c=getComputedStyle(document.querySelector('#search-box')); return [c.outlineStyle,c.outlineWidth,c.borderTopWidth];})()"
        )
        self.assertEqual(ring, ["solid", "2px", "1px"])

    def ink(self, page, text):
        """With `text` in the unfocused field: the ink centres of the field's text and of the view tab's label, and the
        band's centre (CSS px from the viewport's top)."""
        page.evaluate("t=>{const q=document.querySelector('#search-q'); q.blur(); q.value=t;}", text)
        settle(page)
        self.assertEqual(fonts_ready(page), "loaded")
        g = page.evaluate(BAR)
        shot = page.screenshot(clip={"x": 0, "y": 0, "width": g["nav"]["w"], "height": g["nav"]["b"] + 2})
        text_end = min(g["q"]["r"], g["q"]["l"] + 80) - 2  # the typed text, short of the field's far corner
        boxes = [
            [g["q"]["l"], g["box"]["t"] + 2, text_end, g["box"]["b"] - 2],
            [g["viewLbl"]["l"], g["band"]["t"] + 1, g["viewLbl"]["r"], g["band"]["b"] - 3],
        ]
        mine, tab = page.evaluate(INK_MID, [base64.b64encode(shot).decode(), 2, boxes])
        return mine, tab, (g["band"]["t"] + g["band"]["b"]) / 2

    def test_typed_text_is_centred_on_the_band_in_the_bundled_font_and_in_fallbacks(self):
        """A capital and digits typed in the field have their ink centre on the band's centre within half a pixel - in
        the bundled Pretendard and with the system's sans-serif (the font stack's last resort) or monospace (metrics far
        from it) in its place, with a mouse and on touch. Hangul has its ink centre on that of the view tab's Hangul
        label: within half a pixel in the bundled font, and within the 0.75px that a substitute's own Hangul leaves
        between a 12px label and the field's larger text (docs/handbook/viewer.md §모바일 레이아웃 여백 대칭)."""
        for name in ("desktop 1440x900", "tablet 768x1024"):
            for font in (None, "sans-serif", "monospace"):
                with self.subTest(viewport=name, font=font or "Pretendard Variable"):
                    page = self.view(BARS[name], init=FONT % font if font else None)
                    for text in ("H", "1080"):
                        mine, _, band = self.ink(page, text)
                        self.assertAlmostEqual(mine, band, delta=0.5, msg=text)
                    mine, tab, _ = self.ink(page, "원고")
                    self.assertAlmostEqual(mine, tab, delta=0.75 if font else 0.5, msg="원고")

    def test_dark_theme_keeps_the_geometry(self):
        """The dark theme changes colours only: the bar's boxes are those of the light theme."""
        _, light = self.bar(DESKTOP)
        _, dark = self.bar(DESKTOP, dark=True)
        self.assertEqual(light, dark)


class SearchTouch(SearchBase):
    """Coarse pointers: targets and text size."""

    def test_every_search_target_answers_44px_and_the_field_types_at_16px(self):
        """On each touch viewport, with a query: the field, previous, next and close each answer at least 44x44px
        while drawn smaller - the three buttons at one height, the field's inside (34px in a bar, the 36px row on a
        phone) - and the input's text is 16px so that focusing it does not zoom the page."""
        for name, dev in list(BARS.items())[1:] + list(PHONES.items()):
            with self.subTest(viewport=name):
                page = self.view(dev)
                page.evaluate("searchOpen()")
                page.fill("#search-q", "tide")
                page.wait_for_function(COUNTED)
                settle(page)
                self.assertEqual(page.evaluate(MISSES_44, "#search-field,#search-prev,#search-next,#search-close"), [])
                drawn = page.evaluate(
                    "['#search-prev','#search-next','#search-close'].map(s=>document.querySelector(s).getBoundingClientRect().height)"
                )
                self.assertEqual(drawn, [36 if name in PHONES else 34] * 3)
                self.assertEqual(
                    page.evaluate("getComputedStyle(document.querySelector('#search-q')).fontSize"), "16px"
                )


class SearchPhone(SearchBase):
    """The phone band (docs/handbook/viewer.md §본문 검색): no field at rest, a row that replaces the bottom bar while
    searching."""

    @staticmethod
    def free(page):
        """The PDF's visible height: from under the stripe to the top of whatever stands at the screen's bottom (the
        sheet, or the search row over it)."""
        return page.evaluate(
            """() => {const top = document.querySelector('#brand-stripe').getBoundingClientRect().bottom, nav = document.querySelector('#doc-nav');
              const tops = [document.querySelector('#right').getBoundingClientRect().top]; if (nav.getClientRects().length) tops.push(nav.getBoundingClientRect().top);
              return Math.min(...tops) - top;}"""
        )

    def disclose(self, page):
        """Open the navigation sheet from the bar and press its search row; the search row is up and has the focus."""
        page.tap("#btn-pos")
        page.wait_for_selector("#nav-sheet[open]")
        settle(page)
        page.tap("#ns-search")
        page.wait_for_function(
            "document.body.classList.contains('search-open')&&!document.querySelector('#nav-sheet').open"
        )
        settle(page)

    def test_at_rest_the_phone_shows_no_field_and_gives_up_no_height(self):
        """On each phone the nav bar and the field are not drawn, and the PDF's visible height is the screen less the
        4px stripe and the 53px sheet bar - what it is without the search."""
        for name, dev in PHONES.items():
            with self.subTest(viewport=name):
                page = self.view(dev)
                self.assertFalse(page.is_visible("#doc-nav"))
                self.assertFalse(page.is_visible("#search-q"))
                self.assertEqual(self.free(page), dev["viewport"]["height"] - 4 - 53)

    def test_the_navigation_sheets_row_discloses_the_field_in_place_of_the_bar(self):
        """The navigation sheet's [본문 검색] row closes the sheet and puts the field with a close button where the bar
        was - same height, so the PDF keeps its visible height - with the focus in the field; a query adds one 36px
        row, 8px above it, that holds the count and the two arrows and nothing else, both rows inside the 12px edge
        lines with nothing spilling sideways; [검색 닫기] brings the bar back and the focus to the position button."""
        for name, dev in PHONES.items():
            with self.subTest(viewport=name):
                page = self.view(dev)
                rest = self.free(page)
                self.disclose(page)
                self.assertEqual(page.evaluate("document.activeElement.id"), "search-q")
                self.assertEqual(self.free(page), rest)
                self.assertTrue(page.is_visible("#search-close"))
                self.assertFalse(page.is_visible("#search-prev"))
                self.assertFalse(
                    page.evaluate(
                        "(()=>{const b=document.querySelector('#btn-pos').getBoundingClientRect(); return document.elementFromPoint(b.left+b.width/2,b.top+b.height/2)===document.querySelector('#btn-pos');})()"
                    )
                )
                page.fill("#search-q", "tide")
                page.wait_for_function(COUNTED)
                settle(page)
                self.assertEqual(self.free(page), rest - 44)
                row = page.evaluate(
                    """() => {const R = s => document.querySelector(s).getBoundingClientRect(), f = R('#search-field'), n = R('#search-nav'), c = R('#search-close');
                      return {above: n.bottom <= f.top + 0.01, h: n.height, shown: [...document.querySelector('#search-nav').children].filter(e => e.getClientRects().length).map(e => e.id),
                        field: f.height, closeRow: Math.abs((c.top + c.bottom) / 2 - (f.top + f.bottom) / 2),
                        edges: [f.left, innerWidth - c.right, n.left, innerWidth - n.right], spill: document.documentElement.scrollWidth - innerWidth};}"""
                )
                self.assertEqual(
                    row,
                    {
                        "above": True,
                        "h": 36,
                        "shown": ["search-count", "search-prev", "search-next"],
                        "field": 36,
                        "closeRow": 0,
                        "edges": [12, 12, 12, 12],  # both rows start and end on the phone's 12px edge line
                        "spill": 0,
                    },
                )
                page.tap("#search-close")
                settle(page)
                self.assertFalse(page.is_visible("#doc-nav"))
                self.assertEqual(self.free(page), rest)
                self.assertEqual(page.evaluate("document.activeElement.id"), "btn-pos")

    def test_a_hit_is_shown_above_the_search_row(self):
        """Stepping to a hit near a page's foot scrolls it into the part of the PDF the search row does not cover."""
        page = self.view(PHONES["phone 390x844"])
        self.disclose(page)
        page.fill("#search-q", "ebb")
        page.wait_for_function(COUNTED)
        settle(page)
        cur = self.current(page)
        top = page.evaluate("document.querySelector('#doc-nav').getBoundingClientRect().top")
        self.assertEqual(cur["page"], 3)
        self.assertLessEqual(cur["bottom"], top)
        self.assertGreaterEqual(cur["top"], 4)

    def test_a_phone_draft_survives_a_search(self):
        """With a note half written in the sheet's composer, a search opened from the navigation sheet and closed again
        leaves the composer open with the note as typed and the sheet up."""
        page = self.view(PHONES["phone 390x844"])
        page.evaluate("LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60})")
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo", timeout=8000)
        page.fill("#note", "휴대폰 초안")
        settle(page)
        page.evaluate("document.activeElement.blur(); openNavSheet()")
        page.wait_for_selector("#nav-sheet[open]")
        settle(page)
        page.tap("#ns-search")
        page.wait_for_function("document.body.classList.contains('search-open')")
        page.fill("#search-q", "tide")
        page.wait_for_function(COUNTED)
        page.tap("#search-close")
        settle(page)
        self.assertEqual(page.input_value("#note"), "휴대폰 초안")
        self.assertTrue(page.evaluate("!document.querySelector('#composer').hidden&&SIDE_OPEN&&!!COMPOSE.current"))


class SearchAccessible(SearchBase):
    """Names, roles and what is announced."""

    def test_the_search_is_a_landmark_with_a_labelled_field_and_named_buttons(self):
        """A search landmark named 본문 검색 holds a search field labelled by a real <label>, and the previous, next
        and close buttons carry their names; in English every name is English."""
        for lang, names in (
            ("ko", ["본문 검색", "본문 검색", "이전 결과", "다음 결과", "검색 닫기"]),
            ("en", ["Search the text", "Search the text", "Previous result", "Next result", "Close search"]),
        ):
            with self.subTest(lang=lang):
                page = self.view(lang=lang)
                got = page.evaluate(
                    """() => {const s = document.querySelector('#doc-search'), q = document.querySelector('#search-q');
                      return [s.getAttribute('role'), q.type, q.labels.length, s.getAttribute('aria-label'), q.labels[0].textContent.trim(),
                        ...['#search-prev', '#search-next', '#search-close'].map(b => document.querySelector(b).getAttribute('aria-label'))];}"""
                )
                self.assertEqual(got, ["search", "search", 1, *names])

    def test_the_result_is_announced_politely_once_it_is_known(self):
        """A polite live region says the place among the hits and the page once every page has been read, the new
        place after a step, and that there is none for a query without hits; the count on screen is not read twice."""
        page = self.view()
        live = page.evaluate(
            "(()=>{const e=document.querySelector('#search-sr'); return [e.getAttribute('role'),e.getAttribute('aria-live'),document.querySelector('#search-count').getAttribute('aria-hidden')];})()"
        )
        self.assertEqual(live, ["status", "polite", "true"])
        self.search(page, "tide")
        self.assertEqual(page.text_content("#search-sr"), "7개 중 1번째 · 1쪽")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        self.assertEqual(page.text_content("#search-sr"), "7개 중 4번째 · 2쪽")
        self.search(page, "nothing here")
        self.assertEqual(page.text_content("#search-sr"), "결과 없음")
        english = self.view(lang="en")
        self.search(english, "tide")
        self.assertEqual(english.text_content("#search-sr"), "1 of 7 · page 1")


if __name__ == "__main__":
    unittest.main()
