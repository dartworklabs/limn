"""Pages at their sizes on paper and the actual-size view (docs/handbook/viewer.md §PDF 영역 전용 확대, issue 281).

Every page box is its own paper width times one scale for the document on screen, so a one-column figure is drawn half
as wide as a two-column one; the zoom figure reads against the print size (100% = 96/72 px a point), [100%] and Ctrl/Cmd 1
show the print size, and a figure document opens at it when its widest page fits. A document whose pages are all one
size looks as it did. The checks run the real viewer against helpers_figure.viewer_docs' three documents (a LaTeX
manuscript, a figure document and a view-only PDF), the figure's page images resized where a check needs other sizes.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_actual_size.py
"""

import json
import unittest

import helpers_figure
from helpers import add_pin, blank_png, extract_js_fn, ps, run_node
from helpers_access import ALICE
from helpers_browser import BrowserBase, settle
from helpers_notices import node_or_skip

PT_PX = 96 / 72
DESKTOP = {"viewport": {"width": 1400, "height": 850}}
FOLD = {"viewport": {"width": 841, "height": 673}, "is_mobile": True, "has_touch": True}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1}}))}catch(e){}"
# Every page box: its number, CSS width, left and centre in the PDF scroller's content (scroll offsets included).
PAGES = """() => {const L = document.querySelector('#left'), lr = L.getBoundingClientRect();
  return [...document.querySelectorAll('#doc .pg')].map(p => {const r = p.getBoundingClientRect(),
    left = r.left - lr.left + L.scrollLeft; return {page: +p.dataset.page, w: r.width, left, mid: left + r.width / 2};});}"""


def sized_pdf(sizes):
    """A valid PDF whose pages have these MediaBox sizes in points, each with a filled square (pdf.js draws it)."""
    kids = " ".join("%d 0 R" % (3 + i) for i in range(len(sizes)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(sizes))).encode(),
    ]
    content = 3 + len(sizes)
    for w, h in sizes:
        objects.append(
            ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R >>" % (w, h, content)).encode()
        )
    objects.append(b"<< /Length 24 >>\nstream\n0 0 1 rg 20 20 80 80 re f\nendstream")
    output, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(output)


class ScaleLogic:
    """Shared node runner for the pure scale helpers."""

    def run_js(self, names, expr):
        """Evaluate expr (JSON) with the named shipped functions and PT_PX defined."""
        node_or_skip(self)
        js = "\n".join(
            ["const PT_PX=96/72;"] + [extract_js_fn(n) for n in names] + ["console.log(JSON.stringify(%s));" % expr]
        )
        return json.loads(run_node(js))


class PageScaleLogic(ScaleLogic, unittest.TestCase):
    """The pure decisions: a page's width at a scale, the scale a document opens at, and a kept view's scale."""

    def test_a_page_is_its_paper_width_times_the_scale_in_whole_pixels(self):
        """pageWidth(pt_w, k): rounded to whole px and never 0 - a one-column figure (252pt) is drawn at 336px and a
        two-column one (522pt) at 696px at print size."""
        got = self.run_js(
            ["pageWidth"], "[pageWidth(522,PT_PX),pageWidth(252,PT_PX),pageWidth(612,1.5),pageWidth(0.2,1)]"
        )
        self.assertEqual(got, [696, 336, 918, 1])

    def test_a_figure_opens_at_print_size_while_its_common_page_fits(self):
        """openScale(fig, common, widest, fit, wide): a figure document at print size when its most common page fits the
        fitted width - a wider outlier (664pt beside 522pt) does not decide it - else with the common page fitted; any
        other document with its widest page fitted, at most 900px in wide - as it opened before figure documents had a
        scale of their own."""
        got = self.run_js(
            ["openScale"],
            "[openScale(true,522,664,780,true),openScale(true,522,664,640,true),openScale(true,522,664,366,false),"
            "openScale(false,612,612,1260,true),openScale(false,612,612,780,true),openScale(false,612,792,366,false)]",
        )
        self.assertEqual(
            [round(v, 6) for v in got],
            [round(v, 6) for v in [PT_PX, 640 / 522, 366 / 522, 900 / 612, 780 / 612, 366 / 792]],
        )

    def test_the_common_width_is_the_mode_and_the_wider_on_a_tie(self):
        """commonWidth(ws): the page width most pages have (the concept figures' 522pt among 252pt and 664pt pages), the
        wider of two equally common ones, and 0 for no pages; nonsense widths do not count."""
        got = self.run_js(
            ["commonWidth"],
            "[commonWidth([522,522,252,664,522,664]),commonWidth([612,1152]),commonWidth([]),commonWidth([0,null,252])]",
        )
        self.assertEqual(got, [522, 1152, 0, 252])

    def test_a_kept_view_gives_its_scale_or_the_width_an_older_release_kept(self):
        """viewScale(v, m): the view's k; a view kept before scales (a page width w) over the widest page m; else 0."""
        got = self.run_js(
            ["viewScale"],
            "[viewScale({k:1.25,w:900},612),viewScale({w:918},612),viewScale({w:918},0),viewScale({},612),viewScale({k:0},612)]",
        )
        self.assertEqual(got, [1.25, 1.5, 0, 0, 0])


class ActualSize(BrowserBase):
    """The real viewer: pages in proportion, the zoom figure and the zoom button, [100%], and the scale each kind opens at."""

    WHO = ALICE

    def setUp(self):
        """viewer_docs' three documents; the figure's page images are 2400px (1152pt) and 1275px (612pt) wide."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)

    def size_figure(self, *sizes):
        """Give the figure's build on screen page images of these pixel sizes (150 dpi: a 1100px page is 528pt)."""
        d = self.fig.dir / helpers_figure.BUILD1
        for old in d.glob("page-*.png"):
            old.unlink()
        for i, (w, h) in enumerate(sizes, 1):
            (d / ("page-%d.png" % i)).write_bytes(blank_png(w, h))

    def on(self, doc, init=NO_COACH, **device):
        """The viewer showing document doc, settled (a fresh context: nothing saved but the coach marks seen)."""
        page = self.open(0, init=init, **(device or DESKTOP))
        if doc != "ms":
            page.evaluate("k=>switchDoc(k)", doc)
            page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&document.querySelector('#p1')", arg=doc)
            settle(page)
        return page

    def zoom_figure(self, page):
        """[더보기]'s zoom figure, as it reads when [더보기] opens."""
        page.click("#btn-more")
        page.wait_for_selector("#more[open]")
        text = page.inner_text("#m-zoom")
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('#more').open")
        return text

    def test_a_figure_opens_at_print_size_its_pages_in_proportion(self):
        """A two-column figure (528pt) and a one-column one (252pt) whose widest page fits the PDF area open at print
        size: 704px and 336px, the narrow page centred under the wide one, and [더보기] reads 100%. Nothing is saved
        until a person zooms."""
        self.size_figure((1100, 700), (525, 900))
        page = self.on("fig")
        self.assertAlmostEqual(page.evaluate("K"), PT_PX, places=6)
        pages = page.evaluate(PAGES)
        self.assertEqual([p["w"] for p in pages], [704, 336])
        self.assertAlmostEqual(pages[0]["mid"], pages[1]["mid"], delta=1)
        self.assertEqual(self.zoom_figure(page), "100%")
        self.assertNotIn("figZoom", page.evaluate("prefs()"))

    def test_a_figure_wider_than_the_pdf_area_opens_fitted(self):
        """The fixture's 1152pt page (the wider of its two, as common as the other) is 1536px at print size, wider than
        the area: the figure opens with that page fitted and its 612pt page in proportion - not stretched to the same
        width."""
        page = self.on("fig")
        fit = page.evaluate("fitWidth()")
        self.assertAlmostEqual(page.evaluate("K"), fit / 1152, places=6)
        pages = page.evaluate(PAGES)
        self.assertEqual([p["w"] for p in pages], [round(fit), round(612 * fit / 1152)])
        self.assertEqual(self.zoom_figure(page), "%d%%" % round(fit / 1152 / PT_PX * 100))

    def test_a_document_of_one_page_size_looks_as_it_did(self):
        """The manuscript's pages are all 612pt: it opens at min(inner width, 900px) on a desktop and the inner width on
        a phone, fit-width is the fitted width, and a zoom step is 1.2 times it - the widths the single page width W
        gave - with every page as wide as the first. The desktop keeps that width in pinPrefs.w as before."""
        page = self.on("ms")
        old = page.evaluate("Math.round(Math.min(innerW(),900))")
        self.assertEqual({p["w"] for p in page.evaluate(PAGES)}, {old})
        page.click("#btn-fit")
        fit = page.evaluate("Math.round(fitWidth())")
        self.assertEqual({p["w"] for p in page.evaluate(PAGES)}, {fit})
        self.assertEqual(page.evaluate("prefs().w"), fit)
        page.click("#btn-zoom-in")
        self.assertEqual({p["w"] for p in page.evaluate(PAGES)}, {round(fit * 1.2)})
        phone = self.on("ms", **PHONE)
        inner = phone.evaluate("Math.round(innerW())")
        self.assertEqual({p["w"] for p in phone.evaluate(PAGES)}, {inner})
        self.assertNotIn("w", phone.evaluate("prefs()"))

    def test_the_zoom_button_shows_the_zoom_and_goes_to_100(self):
        """The desktop tool bar's zoom button shows the zoom now, as [더보기] does, and its name says where it goes
        ('실제 크기(100%)로 · 지금 N%'); pressed it shows the pages at print size (612pt -> 816px) and reads '100%',
        pressed (aria-pressed). It keeps one width whatever it reads. Ctrl/Cmd 1 is left to the browser (its first tab).
        The manuscript keeps its widest page's width (w), the figure its zoom against print size (figZoom) - so a figure
        still opens at its own setting after the manuscript was zoomed, and the other way round, across a reload."""
        page = self.on("ms")
        look = """() => {const b = document.querySelector('#btn-actual');
          return {text: b.textContent.trim(), pressed: b.getAttribute('aria-pressed'), name: b.getAttribute('aria-label'),
            tip: b.dataset.tip, w: b.getBoundingClientRect().width};}"""
        before = page.evaluate(look)
        pct = "%d%%" % page.evaluate("zoomPct(K)")
        self.assertNotEqual(pct, "100%")
        self.assertEqual(before["text"], pct)
        self.assertEqual(before["pressed"], "false")
        self.assertEqual(before["name"], "실제 크기(100%)로 · 지금 " + pct)
        self.assertIn("지금 " + pct, before["tip"])
        self.assertEqual(self.zoom_figure(page), pct)
        page.click("#btn-actual")
        self.assertAlmostEqual(page.evaluate("K"), PT_PX, places=6)
        self.assertEqual({p["w"] for p in page.evaluate(PAGES)}, {816})
        after = page.evaluate(look)
        self.assertEqual((after["text"], after["pressed"]), ("100%", "true"))
        self.assertEqual(after["name"], "실제 크기(100%)로 · 지금 100%")
        self.assertEqual(after["w"], before["w"])
        self.assertEqual(page.evaluate("prefs().w"), 816)
        page.click("#btn-zoom-in")
        self.assertEqual(page.evaluate(look)["pressed"], "false")
        page.click("#btn-fit")
        k = page.evaluate("K")
        page.evaluate("document.activeElement&&document.activeElement.blur()")
        page.keyboard.press("Control+1")
        self.assertEqual(page.evaluate("K"), k)
        # The figure: [100%] keeps figZoom 1 and leaves the manuscript's w alone.
        self.size_figure((1100, 700), (525, 900))
        page.evaluate("async()=>await switchDoc('fig')")
        page.wait_for_function("DOC==='fig'&&document.querySelector('#p2')")
        page.click("#btn-zoom-in")
        self.assertAlmostEqual(page.evaluate("prefs().figZoom"), 1.2, places=3)
        w = page.evaluate("prefs().w")
        page.click("#btn-actual")
        self.assertEqual(page.evaluate("[prefs().figZoom,prefs().w]"), [1, w])
        page.click("#btn-zoom-out")
        page.reload()
        page.wait_for_function("typeof LIGHT_TIMER!=='undefined'&&LIGHT_TIMER!==null&&DOC==='fig'")
        self.assertAlmostEqual(page.evaluate("K"), PT_PX / 1.2, places=3)
        page.evaluate("async()=>await switchDoc('ms')")
        page.wait_for_function("DOC==='ms'&&document.querySelector('#p2')")
        self.assertEqual({p["w"] for p in page.evaluate(PAGES)}, {w})

    def test_the_zoom_button_speaks_english(self):
        """In English the zoom button's name and tip say the same in English, with the zoom now."""
        page = self.open(0, lang="en", init=NO_COACH, **DESKTOP)
        pct = "%d%%" % page.evaluate("zoomPct(K)")
        got = page.evaluate(
            "[document.querySelector('#btn-actual').getAttribute('aria-label'),"
            "document.querySelector('#btn-actual').dataset.tip]"
        )
        self.assertEqual(got[0], "To actual size (100%) · now " + pct)
        self.assertEqual(got[1], "To actual size (100%): shows the PDF pages at their printed size · now " + pct)

    def test_a_wide_outlier_scrolls_sideways_while_the_common_page_opens_at_100(self):
        """Two 528pt pages and one 672pt outlier: the common page (704px at print size) fits the PDF area and the figure
        opens at 100% - the outlier (896px) scrolls sideways; [↔] still fits the widest page, and then nothing scrolls
        sideways."""
        self.size_figure((1100, 700), (1400, 700), (1100, 900))
        page = self.on("fig")
        fit = page.evaluate("fitWidth()")
        self.assertTrue(704 <= fit < 896, fit)
        self.assertAlmostEqual(page.evaluate("K"), PT_PX, places=6)
        self.assertEqual([p["w"] for p in page.evaluate(PAGES)], [704, 896, 704])
        side = "(()=>{const L=document.querySelector('#left');return L.scrollWidth-L.clientWidth;})()"
        self.assertGreater(page.evaluate(side), 0)
        page.click("#btn-fit")
        self.assertAlmostEqual(page.evaluate("K"), fit / 672, places=6)
        self.assertEqual(page.evaluate(side), 0)

    def test_a_fitted_page_never_scrolls_sideways(self):
        """Fit-width is the room inside the PDF area's padding: with a mouse it was 12px wider (the 44px left padding
        against a 48px allowance) and every fitted page scrolled sideways. The manuscript and the figure, fitted and at
        their opening scale, leave nothing to scroll sideways."""
        side = "(()=>{const L=document.querySelector('#left');return L.scrollWidth-L.clientWidth;})()"
        for doc in ("ms", "fig"):
            with self.subTest(doc=doc):
                page = self.on(doc)
                self.assertEqual(page.evaluate(side), 0)
                page.click("#btn-fit")
                self.assertEqual(page.evaluate(side), 0)
                self.assertEqual(
                    page.evaluate("Math.round(document.querySelector('#p1').getBoundingClientRect().width)"),
                    page.evaluate("fitWidth()"),
                )

    def test_a_page_smaller_than_160px_reaches_its_print_size(self):
        """A 72pt page (one inch) is 96px at print size, under the 160px floor of the limits: [100%] still shows it at
        96px and the button reads 100%."""
        self.size_figure((150, 150), (150, 300))
        page = self.on("fig")
        page.click("#btn-actual")
        self.assertAlmostEqual(page.evaluate("K"), PT_PX, places=6)
        self.assertEqual([p["w"] for p in page.evaluate(PAGES)], [96, 96])
        self.assertEqual(page.evaluate("document.querySelector('#btn-actual').textContent.trim()"), "100%")

    def test_a_page_width_saved_before_this_release_carries_over_to_figures_once(self):
        """A browser that saved a 900px page width before figure documents had their own setting opens the figure with
        its common page 900px wide (figZoom seeded once from it); the manuscript keeps its 900px. A width saved after the
        first start of this release is the manuscript's alone: the figure opens at print size."""
        self.size_figure((1100, 700), (525, 900))
        legacy = "try{localStorage.setItem('pinPrefs',JSON.stringify({w:900,coach:{touch:1,mouse:1,sel:1}}))}catch(e){}"
        page = self.on(
            "fig", init="if(!sessionStorage.getItem('seeded')){sessionStorage.setItem('seeded','1');" + legacy + "}"
        )
        self.assertEqual([p["w"] for p in page.evaluate(PAGES)], [900, round(252 * 900 / 528)])
        prefs = page.evaluate("prefs()")
        self.assertAlmostEqual(prefs["figZoom"], round(900 / 528 / PT_PX, 4), places=4)
        self.assertEqual((prefs["w"], prefs.get("figSeeded"), "figFromW" in prefs), (900, 1, False))
        page.evaluate("async()=>await switchDoc('ms')")
        page.wait_for_function("DOC==='ms'&&document.querySelector('#p2')")
        self.assertEqual({p["w"] for p in page.evaluate(PAGES)}, {900})
        later = "try{localStorage.setItem('pinPrefs',JSON.stringify({w:900,figSeeded:1,coach:{touch:1,mouse:1,sel:1}}))}catch(e){}"
        fresh = self.on("fig", init=later)
        self.assertAlmostEqual(fresh.evaluate("K"), PT_PX, places=6)
        self.assertNotIn("figZoom", fresh.evaluate("prefs()"))

    def test_100_is_in_the_zoom_row_of_more_on_every_band(self):
        """[더보기]'s zoom row has [100%] before [↔] on the desktop, the unfolded foldable and the phone; on touch it answers
        44px. On the foldable the figure's common page (528pt, 704px) fits and it opens at 100%; on the phone it does not
        and it opens with that page fitted, and [100%] brings it to print size."""
        self.size_figure((1100, 700), (525, 900))
        for label, device, opens in (("desktop", DESKTOP, "100%"), ("fold", FOLD, "100%"), ("phone", PHONE, None)):
            with self.subTest(band=label):
                page = self.on("fig", **device)
                page.click("#btn-more")
                page.wait_for_selector("#more[open]")
                if opens:
                    self.assertEqual(page.inner_text("#m-zoom"), opens)
                else:
                    fit = page.evaluate("fitK()")
                    self.assertAlmostEqual(page.evaluate("K"), fit, places=6)
                    self.assertEqual(page.inner_text("#m-zoom"), "%d%%" % round(fit / PT_PX * 100))
                row = page.evaluate("""() => {const b = document.querySelector('#m-actual'), f = document.querySelector('#more [data-act=fit]');
                  const r = b.getBoundingClientRect(), a = getComputedStyle(b, '::after');
                  return {order: !!(b.compareDocumentPosition(f) & Node.DOCUMENT_POSITION_FOLLOWING), w: r.width, h: r.height,
                    hit: [parseFloat(a.width) || 0, parseFloat(a.height) || 0], label: b.getAttribute('aria-label')};}""")
                self.assertTrue(row["order"])
                self.assertEqual(row["label"], "100% · 실제 크기")
                if device.get("has_touch"):
                    self.assertGreaterEqual(min(max(row["w"], row["hit"][0]), max(row["h"], row["hit"][1])), 44)
                page.click("#m-actual")
                self.assertAlmostEqual(page.evaluate("K"), PT_PX, places=6)
                self.assertEqual(page.inner_text("#m-zoom"), "100%")
                self.assertEqual([p["w"] for p in page.evaluate(PAGES)], [704, 336])

    def test_each_page_keeps_its_own_line_badge_and_zoom_anchor(self):
        """On a phone the figure opens fitted: its 528pt page fills the column and its 252pt page is centred, narrower.
        Each page verdict line is as wide as its own page; a mark at a page's left edge has its badge inside on the wide
        page (12px margin, short of the 28px reach) and outside on the narrow one (its centring margin); a zoom on the
        narrow page keeps the point under the fingers; and the page list's jump brings the narrow page into view when the
        zoomed pages scroll sideways."""
        self.size_figure((1100, 700), (525, 900))
        (self.fig.main.parent / "figures.limnverdicts.json").write_text(
            json.dumps(
                {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}], "page": True},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        script = str(self.fig.src / "src" / "B2_calendar.py")
        for n in (1, 2):
            add_pin(
                {
                    "doc": "fig",
                    "file": script,
                    "lo": 1,
                    "hi": 10,
                    "page": n,
                    "frac": [0, 0.3, 0.2, 0.1],
                    "note": "p%d" % n,
                },
                ALICE,
            )
        page = self.on("fig", **PHONE)
        page.wait_for_function(
            "document.querySelectorAll('#doc .pv').length===2&&document.querySelectorAll('.mark').length===2"
        )
        pages = page.evaluate(PAGES)
        self.assertEqual(pages[0]["w"], round(page.evaluate("fitWidth()")))
        self.assertEqual(pages[1]["w"], round(252 * page.evaluate("K")))
        self.assertAlmostEqual(pages[0]["mid"], pages[1]["mid"], delta=1)
        lines = page.evaluate("[...document.querySelectorAll('#doc .pv')].map(l=>l.getBoundingClientRect().width)")
        self.assertEqual([round(v) for v in lines], [round(p["w"]) for p in pages])
        badges = page.evaluate(
            "[...document.querySelectorAll('.mark')].map(m=>[+m.parentElement.dataset.page,m.classList.contains('in')])"
        )
        self.assertEqual(sorted(badges), [[1, True], [2, False]])
        # A two-finger zoom over the narrow page keeps that spot under the fingers.
        p2 = page.evaluate(
            "(()=>{const r=document.getElementById('p2').getBoundingClientRect();return [r.left+r.width*0.4,r.top+r.height*0.5];})()"
        )
        page.evaluate("p=>document.getElementById('p2').scrollIntoView({block:'center'})", p2)
        p2 = page.evaluate(
            "(()=>{const r=document.getElementById('p2').getBoundingClientRect();return [r.left+r.width*0.4,r.top+r.height*0.5];})()"
        )
        at = "p=>{const a=zoomAnchor(p[0],p[1]);return [a.pg.id,+a.fx.toFixed(3),+a.fy.toFixed(3)];}"
        before = page.evaluate(at, p2)
        page.evaluate("p=>zoomTo(K*2.5,p[0],p[1])", p2)
        after = page.evaluate(at, p2)
        self.assertEqual(after[0], "p2")
        self.assertAlmostEqual(after[1], before[1], delta=0.01)
        self.assertAlmostEqual(after[2], before[2], delta=0.01)
        lines = page.evaluate("[...document.querySelectorAll('#doc .pv')].map(l=>l.getBoundingClientRect().width)")
        self.assertEqual([round(v) for v in lines], [round(page.evaluate("innerW()"))] * 2)
        # Scrolled to the right end of the zoomed wide page, the jump to the narrow page brings it into view.
        page.evaluate("()=>{const L=document.querySelector('#left');L.scrollLeft=L.scrollWidth;L.scrollTop=0;}")
        page.evaluate("goPage(2)")
        page.wait_for_function("""() => {const r = document.getElementById('p2').getBoundingClientRect(),
          l = document.querySelector('#left').getBoundingClientRect(); return r.right > l.left && r.left < l.right && r.top < l.bottom;}""")

    def test_each_page_is_drawn_by_pdf_js_at_its_own_width(self):
        """With a real two-size PDF (528pt and 252pt) the vector canvas of each page is as wide as its own page box (704
        and 336px at print size, 702 and 334 inside the light theme's 1px border) times the device pixel ratio - so the
        narrow page is drawn as sharp as the wide one, not at the wide one's size."""
        self.size_figure((1100, 700), (525, 900))
        (self.fig.dir / helpers_figure.BUILD1 / self.fig.pdf_name).write_bytes(sized_pdf([(528, 336), (252, 432)]))
        for dpr in (1, 2):
            with self.subTest(dpr=dpr):
                page = self.on("fig", viewport={"width": 1400, "height": 1400}, device_scale_factor=dpr)
                page.wait_for_function("document.querySelectorAll('#doc .pg.drawn').length===2", timeout=15000)
                got = page.evaluate(
                    "[...document.querySelectorAll('#doc .pg')].map(p=>[p.clientWidth,p.querySelector('canvas.vb').width])"
                )
                self.assertEqual(got, [[702, 702 * dpr], [334, 334 * dpr]])

    def test_a_figure_drawn_again_at_another_size_keeps_the_scale(self):
        """When the figure is drawn again and its one-column page became a two-column one (252pt -> 528pt), the new build
        swaps in at the same scale: the grown page is as wide as the other, at print size."""
        self.size_figure((1100, 700), (525, 900))
        page = self.on("fig")
        self.assertEqual([round(p["w"]) for p in page.evaluate(PAGES)], [704, 336])
        helpers_figure.viewer_rerender(self.fig)
        d = self.fig.dir / helpers_figure.BUILD2
        for i, size in enumerate(((1100, 700), (1100, 900)), 1):
            (d / ("page-%d.png" % i)).write_bytes(blank_png(*size))
        page.evaluate("async()=>await refreshDoc()")
        settle(page)
        self.assertEqual(page.evaluate("META.pages_build"), helpers_figure.BUILD2)
        self.assertAlmostEqual(page.evaluate("K"), PT_PX, places=6)
        self.assertEqual([round(p["w"]) for p in page.evaluate(PAGES)], [704, 704])

    def test_the_page_number_stands_outside_a_narrow_page(self):
        """On a phone the one-column page (252pt) is centred beside the two-column one's width: its page number stands
        outside it, left of its top, and covers none of the page; the full-width page keeps its number in its corner. On
        the desktop at print size the narrow page's number is outside too, the wide page's inside."""
        self.size_figure((1100, 700), (525, 900))
        where = """() => [...document.querySelectorAll('#doc .pg')].map(p => {const n = p.querySelector('.no').getBoundingClientRect(),
          r = p.getBoundingClientRect(); return [p.classList.contains('no-out'), n.right <= r.left, n.left >= r.left - 0.5];})"""
        for label, device in (("phone", PHONE), ("desktop", DESKTOP)):
            with self.subTest(band=label):
                page = self.on("fig", **device)
                self.assertEqual(page.evaluate(where), [[False, False, True], [True, True, False]])

    def test_a_drag_from_a_badges_press_area_on_the_page_starts_a_box(self):
        """In [선택] mode on a phone a finger that lands on the page inside a pin badge's 44px press area - the badge sits
        at the narrow page's left edge - and moves draws a box, as anywhere on the page; a tap on the badge still goes to
        its card."""
        self.size_figure((1100, 700), (525, 900))
        script = str(self.fig.src / "src" / "B2_calendar.py")
        pid = add_pin(
            {"doc": "fig", "file": script, "lo": 1, "hi": 10, "page": 2, "frac": [0.1, 0.3, 0.3, 0.1], "note": "n"},
            ALICE,
        ).record["id"]
        page = self.on("fig", **PHONE)
        page.evaluate("document.getElementById('p2').scrollIntoView({block:'center'})")
        page.evaluate("setSelMode(true)")
        settle(page)
        at = page.evaluate("""() => {const p = document.getElementById('p2').getBoundingClientRect(),
          b = document.querySelector('#p2 .mark-jump').getBoundingClientRect(); const x = p.left + 4, y = b.top + b.height / 2;
          const e = document.elementFromPoint(x, y); return [x, y, !!(e && e.closest('.mark-jump'))];}""")
        self.assertTrue(at[2], "the point is not on the badge's press area: %s" % at)
        cdp = page.context.new_cdp_session(page)

        def touch(kind, pts):
            cdp.send(
                "Input.dispatchTouchEvent", {"type": kind, "touchPoints": [{"x": x, "y": y, "id": 0} for x, y in pts]}
            )

        touch("touchStart", [(at[0], at[1])])
        for i in range(1, 9):
            touch("touchMove", [(at[0] + 10 * i, at[1] + 6 * i)])
        page.wait_for_function("!!document.querySelector('#p2 .sel')")
        touch("touchEnd", [])
        settle(page)
        self.assertFalse(page.evaluate("!!document.querySelector('.pin.card.cur')"))
        page.evaluate("cancelSelection(false)")
        settle(page)
        b = page.locator("#p2 .mark-jump").bounding_box()
        touch("touchStart", [(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)])
        touch("touchEnd", [])
        page.wait_for_function("id=>!!document.querySelector('.pin.card.cur[data-id=\"'+id+'\"]')", arg=pid)

    def test_zoomed_far_in_each_page_draws_its_visible_part_at_full_resolution(self):
        """At 500% of the fit on a DPR 2 screen both a two-column page (528pt) and a one-column one (252pt) pass the canvas
        pixel ceiling: each page's base canvas stays under it and a detail canvas covers what is visible of that page,
        placed at its own % of that page; scrolled sideways, the detail is drawn again for the new part."""
        self.size_figure((1100, 700), (525, 900))
        (self.fig.dir / helpers_figure.BUILD1 / self.fig.pdf_name).write_bytes(sized_pdf([(528, 336), (252, 432)]))
        page = self.on("fig", viewport={"width": 1400, "height": 900}, device_scale_factor=2)
        page.wait_for_function("document.querySelectorAll('#doc .pg.drawn').length===2", timeout=15000)
        page.evaluate("zoomTo(fitK()*5)")
        cover = """n => {const pg = document.getElementById('p' + n), L = document.querySelector('#left'), dt = pg.querySelector('canvas.dt');
          const vb = pg.querySelector('canvas.vb'); if (!dt || !vb) return null; const r = pg.getBoundingClientRect(), l = L.getBoundingClientRect(),
          d = dt.getBoundingClientRect(); const vis = [Math.max(r.left, l.left), Math.max(r.top, l.top), Math.min(r.right, l.left + L.clientWidth),
          Math.min(r.bottom, l.top + L.clientHeight)];
          return {base: vb.width * vb.height, covers: d.left <= vis[0] + 1 && d.top <= vis[1] + 1 && d.right >= vis[2] - 1 && d.bottom >= vis[3] - 1,
            dpx: dt.width / d.width};}"""
        for n in (1, 2):
            with self.subTest(page=n):
                page.evaluate("n=>document.getElementById('p'+n).scrollIntoView({block:'center',inline:'center'})", n)
                page.wait_for_function("f=>{const c=(%s)(f);return !!c&&c.covers;}" % cover, arg=n, timeout=15000)
                got = page.evaluate(cover, n)
                self.assertLessEqual(got["base"], 16777216)
                self.assertAlmostEqual(got["dpx"], 2, delta=0.05)
                page.evaluate("()=>{const L=document.querySelector('#left');L.scrollLeft+=L.clientWidth/2;}")
                page.wait_for_function("f=>{const c=(%s)(f);return !!c&&c.covers;}" % cover, arg=n, timeout=15000)
