"""When the open document's meta is known (app/state.ts META, knownMeta; docs/handbook/viewer.md §타입 검사): META is null
until the first /api/meta answer arrives. Code that runs only once a document is open reads knownMeta(), which throws,
naming META, before then. The listeners that can run before it - a zoom, a relayout, a rebuild's end - stop at the read
that needs the document, where they used to throw a TypeError, and leave the page as that throw did.

- ``EarlyReaders`` runs knownMeta and those readers under node, pulled from the served page, with META null and set.
- ``SlowFirstMeta`` drives the real viewer while its first /api/meta is held: the controls a person can reach then
  throw nothing, and once the answer arrives the page is what a page whose answer came at once shows.

Run: LIMN_TEST_REQUIRE_BROWSER=1 uv run pytest -q src/limn/viewer/tests/test_viewer_meta_known.py
"""

import json
import shutil
import time
import unittest
from urllib.parse import parse_qs, urlparse

from helpers import extract_js_fn, run_node
from helpers_browser import BrowserBase, booted, settle, watch_idle


@unittest.skipUnless(shutil.which("node"), "node not available")
class EarlyReaders(unittest.TestCase):
    """knownMeta and the readers that can run before the first meta, as functions of META and what they are given."""

    def run_js(self, *parts: str):
        """The JSON value the last part logs, with the earlier parts (pulled functions, stubs) defined first."""
        return json.loads(run_node("\n".join(parts)))

    def test_the_meta_is_known_only_once_it_is_set_and_an_early_read_names_it(self):
        """knownMeta throws an Error whose message starts with META while META is null, and gives META once it is set."""
        got = self.run_js(
            "let META = null;",
            extract_js_fn("knownMeta"),
            r"""
            const said = [];
            try { knownMeta(); said.push('read'); } catch (error) { said.push(error instanceof Error, error.message.split(' ')[0]); }
            META = { doc: 'a' };
            said.push(knownMeta() === META);
            console.log(JSON.stringify(said));
            """,
        )
        self.assertEqual(got, [True, "META", True])

    # What setScale (pdf/view-pages.ts) reaches besides the scale itself, as stand-ins that record what a person sees:
    # the saved preferences and the zoom figure.
    SCALE_STUBS = r"""
        const POINT_PX = 96 / 72, saved = [], figures = [];
        let LAYOUT = 'wide', META = null, PAGE_SCALE = 0, SCALE_UNBOUNDED = false;
        function widestPagePoints() { return 612; } function fitWidth() { return 800; } function widthBounds() { return [100, 5000]; }
        function pageWidth(points, scale) { return Math.round(points * scale); } function isFigureKind(kind) { return kind === 'figure'; }
        function sizePages() {} function placeChips() {} function invalidateVectorDraws() {}
        function pageMarks() { return { placeBadges() {} }; } function pageVerdicts() { return { sizeLines() {} }; }
        function savePrefs(value) { saved.push(value); } function drawZoom() { figures.push(Math.round(PAGE_SCALE * 100)); }
        """

    def test_a_wide_zoom_before_the_first_meta_saves_nothing_and_leaves_the_figure(self):
        """In wide, a scale set before the first meta is taken but neither saved nor written into the zoom figure (the
        pages' first draw writes it), as the throw from saveScale left it; compact writes the figure and saves nothing,
        and with a meta wide saves the scale and writes the figure."""
        got = self.run_js(
            self.SCALE_STUBS,
            extract_js_fn("setScale"),
            extract_js_fn("saveScale"),
            r"""
            const step = () => [Math.round(PAGE_SCALE * 100), saved.splice(0), figures.splice(0)];
            setScale(1.5); const early = step();
            LAYOUT = 'mid'; setScale(1.25); const compact = step();
            LAYOUT = 'wide'; META = { kind: 'tex' }; setScale(1.2); const known = step();
            console.log(JSON.stringify([early, compact, known]));
            """,
        )
        self.assertEqual(got, [[150, [], []], [125, [], [125]], [120, [{"w": 734}], [120]]])

    def test_a_compact_zoom_before_the_first_meta_leaves_zoomed_as_it_is(self):
        """markZoomed compares the scale with the screen's own (defaultScale, which needs the document's kind): before
        the first meta it leaves ZOOMED as it is, either way; with a meta a scale off the screen's is a chosen one."""
        got = self.run_js(
            r"""
            let LAYOUT = 'mid', META = null, PAGE_SCALE = 2, ZOOMED = true;
            function commonPageWidth() { return 612; } function widestPagePoints() { return 612; } function fitWidth() { return 800; }
            function isFigureKind(kind) { return kind === 'figure'; }
            """,
            extract_js_fn("openScale"),
            extract_js_fn("defaultScale"),
            extract_js_fn("markZoomed"),
            r"""
            const said = [];
            markZoomed(); said.push(ZOOMED);
            ZOOMED = false; markZoomed(); said.push(ZOOMED);
            META = { kind: 'tex' }; markZoomed(); said.push(ZOOMED);
            PAGE_SCALE = 800 / 612; markZoomed(); said.push(ZOOMED);
            console.log(JSON.stringify(said));
            """,
        )
        self.assertEqual(got, [True, False, True, False])

    def test_a_relayout_before_the_first_meta_applies_the_frame_and_fits_nothing_while_the_pages_area_shows(self):
        """relayout (layout/flow.ts) before the first meta applies the layout, the panel width and the outline, and stops
        before the fit while the PDF area is drawn, where the fit's read of the document threw; with the area not drawn
        (the changes view) the steps after the fit go on, as they did; with a meta every step runs."""
        got = self.run_js(
            r"""
            let META = null, DRAWN = true; const COMPOSE = { current: null }, done = [];
            const $ = () => ({ getClientRects: () => (DRAWN ? [{}] : []) });
            function topAnchor() { return null; } function applyLayout() { return false; } function applySideWidth() {}
            function applyOutlineState() { done.push('frame'); } function restoreAnchor() {} function hideTip() {}
            function stickTop() { done.push('stuck heads'); } function keepFieldInView() {}
            function relayoutListeners() {
              return [{ widthsApplied() { done.push('fit'); }, barStuck() { done.push('section strip'); } }];
            }
            """,
            extract_js_fn("relayout"),
            r"""
            const run = () => { relayout(); return done.splice(0); };
            const early = run(); DRAWN = false; const hidden = run(); DRAWN = true; META = { kind: 'tex' }; const known = run();
            console.log(JSON.stringify([early, hidden, known]));
            """,
        )
        full = ["frame", "fit", "stuck heads", "section strip"]
        self.assertEqual(got, [["frame"], full, full])

    def test_a_rebuild_that_ends_before_any_meta_ends_without_a_word(self):
        """pollBuildOnce (documents/view-build-chip.ts): this tab's rebuild finished while no meta has come (the refresh
        failed too) says nothing and leaves the build error and the update check as they were, where its success line
        threw; another build's end goes on to clear them, and with a meta this tab's says its line."""
        got = self.run_js(
            r"""
            let META = null, DOC = 'a', SWITCHSEQ = 0;
            const BUILD = {}, BUILD_ERR_BY = new Map(), DOC_SEQ = new Map(), said = [];
            const $ = () => ({});
            function withDocQuery(url) { return url; } function pullSuffix() { return ''; } function buildsFromSource() { return true; }
            function api() { return Promise.resolve({ data: { state: 'ok', seq: 2, elapsed_s: 3 } }); }
            function refreshDoc() { return Promise.reject(new Error('meta read failed')); }
            function lineNote(text) { said.push('line'); } function hideBuildErr() { said.push('error closed'); }
            function checkDocUpdate() { said.push('update checked'); } function showBuildErr() {} function buildUnchanged() {}
            function buildChipText() { return ''; } function pollBuild() {}
            const start = (asked) => {
              Object.assign(BUILD, { lastSeq: 1, asked, booted: true, timer: null, error: { state: 'fail' } });
              BUILD_ERR_BY.set('a', BUILD.error);
            };
            """,
            extract_js_fn("pollBuildOnce"),
            r"""
            (async () => {
              const run = async (asked) => { start(asked); await pollBuildOnce(); return [said.splice(0), !!BUILD.error, BUILD.lastSeq]; };
              const mine = await run(true), other = await run(false);
              META = { kind: 'tex', pages: [{}, {}] };
              const known = await run(true);
              console.log(JSON.stringify([mine, other, known]));
            })();
            """,
        )
        cleared = ["error closed", "update checked"]
        self.assertEqual(got, [[[], True, 2], [cleared, False, 2], [["line", *cleared], False, 2]])

    def test_the_readers_that_run_early_take_no_one_as_me_and_no_build_as_on_screen(self):
        """Before the first meta, a question pin's tag names everyone it calls and none as me (addressedTag), the
        @-tag list leaves no one out as me (mentionMatches), and a kept draft's pick is not restored whole: no build
        is on screen (draftRestore)."""
        got = self.run_js(
            r"""
            let META = null;
            const html = (parts, ...values) => parts.reduce((out, part, index) => out + values[index - 1] + part);
            function lucideIcon() { return ''; } function peopleName(login) { return login; }
            """,
            extract_js_fn("addressedTag"),
            extract_js_fn("mentionMatches"),
            extract_js_fn("draftRestore"),
            r"""
            const tag = addressedTag({ addressed: ['alice@example.com'] });
            const people = [{ login: 'alice@example.com', name: 'Alice' }];
            console.log(JSON.stringify([
              tag.includes('나를 부름'), tag.includes('alice@example.com'),
              mentionMatches('', people, null).length,
              draftRestore({ v: 1, doc: 'a', cur: {}, build: '', note: 'kept' }, 'a', null),
            ]));
            """,
        )
        self.assertEqual(got, [False, True, 1, "note"])


# A held first meta waits for the page to ask it: the boot asks after the document list, while the page's own listeners
# are already registered.
HOLD_WAIT_S = 10
# What a person sees of the zoom, the frame and the document once the boot is done.
END_STATE = """() => {
  const text = (selector) => { const element = document.querySelector(selector); return element ? element.textContent : null; };
  return {scale: PAGE_SCALE, zoomed: ZOOMED, figure: text('#m-zoom'), button: text('#btn-actual .z'), layout: LAYOUT,
    body: document.body.className, side: SIDE_OPEN, outline: OUTLINE_MID_OPEN, prefs: localStorage.getItem('pinPrefs'),
    doc: DOC, shown: META && META.doc, pages: document.querySelectorAll('#doc .pg').length, strip: text('#section-strip')};
}"""
# The controls a person can reach before the first meta. (kind, what): a key to press, a selector to click when it shows
# on the device, or a Ctrl+wheel over the PDF area (a trackpad pinch takes the same path). ZOOM_STEPS change nothing the
# boot does not set again: the zoom keys, the wheel and the tool bar's zoom buttons, [더보기] (which shows the zoom
# figure) and its zoom button, and the help.
ZOOM_STEPS = (
    ("key", "Control+="),
    ("key", "Control+-"),
    ("key", "Control+0"),
    ("wheel", ""),
    ("click", "#btn-zoom-in"),
    ("click", "#btn-zoom-out"),
    ("click", "#btn-actual"),
    ("click", "#btn-fit"),
    ("click", "#btn-more"),
    ("click", "#more [data-act=zoom-in]"),
    ("key", "Control+="),
    ("key", "Escape"),
    ("key", "?"),
    ("key", "Escape"),
)
# FRAME_STEPS change the frame, which the person keeps: the outline and panel toggles and their key, the changes view
# and back, with a zoom while the changes view is open.
FRAME_STEPS = (
    ("click", "#nav-toc-toggle"),
    ("key", "Control+\\"),
    ("click", "#btn-side"),
    ("click", "#view-revisions"),
    ("click", "#nav-toc-toggle"),
    ("key", "Control+="),
    ("click", "#view-manuscript"),
)
DESK = {"viewport": {"width": 1400, "height": 850}}
MID = {"viewport": {"width": 1000, "height": 800}}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}


class SlowFirstMeta(BrowserBase):
    """The first /api/meta answer is held while a person uses the page; the light poll and every other request are
    answered. Nothing the person can reach throws; once the answer arrives a page only zoomed ends as a page whose answer
    came at once (the boot sets the scale), and one whose frame was changed keeps that frame."""

    HOLDING = False

    def route(self, route):
        """Hold the full meta reads while HOLDING; answer the rest (BrowserBase.route)."""
        address = urlparse(route.request.url)
        if self.HOLDING and address.path == "/api/meta" and "light" not in parse_qs(address.query):
            self.held.append(route)
            return None
        return super().route(route)

    def page_on(self, device):
        """A new page on device with the coach marks seen, its page errors collected in self.errors."""
        context = self.browser.new_context(**device)
        self.addCleanup(context.close)
        context.add_init_script(
            "try{if(!sessionStorage.getItem('__t')){sessionStorage.setItem('__t','1');"
            "localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1}}));}}catch(e){}"
        )
        watch_idle(context)
        page = context.new_page()
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.route("**/*", self.route)
        return page

    def booted_end(self, page):
        """The page's END_STATE once the boot is done and the page has settled."""
        page.wait_for_function(booted(0), timeout=20000)
        settle(page)
        return page.evaluate(END_STATE)

    def run_steps(self, page, steps):
        """Run steps (ZOOM_STEPS, FRAME_STEPS) on page; a control that does not show on this device is skipped."""
        for kind, what in steps:
            if kind == "key":
                page.keyboard.press(what)
            elif kind == "wheel":
                page.mouse.move(300, 300)
                page.keyboard.down("Control")
                page.mouse.wheel(0, -100)
                page.keyboard.up("Control")
            elif page.evaluate(
                "s => !!document.querySelector(s) && document.querySelector(s).getClientRects().length > 0", what
            ):
                page.click(what, force=True)
            page.wait_for_timeout(50)

    def held_page(self, device):
        """A page on device whose first meta read is held (self.held), asked once; META is still null."""
        self.errors, self.held, self.HOLDING = [], [], True
        page = self.page_on(device)
        page.goto("http://viewer.test/?lang=ko", wait_until="load")
        deadline = time.monotonic() + HOLD_WAIT_S
        while not self.held and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        self.assertEqual(len(self.held), 1, "the boot asks for its first meta once")
        self.assertIsNone(page.evaluate("META"))
        return page

    def let_go(self, page):
        """Answer the held meta read; page's END_STATE once the boot is done."""
        self.assertIsNone(page.evaluate("META"), "nothing set the meta while it was held")
        self.HOLDING = False
        self.forward(self.held.pop())
        return self.booted_end(page)

    def end_at_once(self, device):
        """The end state of a page on device whose first meta came at once and that nobody touched."""
        self.errors, self.held, self.HOLDING = [], [], False
        page = self.page_on(device)
        page.goto("http://viewer.test/?lang=ko", wait_until="load")
        return self.booted_end(page)

    def check_zoom(self, device):
        """ZOOM_STEPS while the meta is held throw nothing, and the page ends as one whose meta came at once."""
        page = self.held_page(device)
        self.run_steps(page, ZOOM_STEPS)
        end = self.let_go(page)
        self.assertEqual(self.errors, [])
        self.assertEqual(end, self.end_at_once(device))
        self.assertEqual(self.errors, [])

    def check_frame(self, device):
        """ZOOM_STEPS and FRAME_STEPS while the meta is held throw nothing; the boot then draws the document in the
        frame the person left (the panel and the outline as they were)."""
        page = self.held_page(device)
        self.run_steps(page, ZOOM_STEPS + FRAME_STEPS)
        frame = page.evaluate("[SIDE_OPEN, OUTLINE_MID_OPEN, LAYOUT]")
        end = self.let_go(page)
        self.assertEqual(self.errors, [])
        self.assertEqual([end["side"], end["outline"], end["layout"]], frame)
        self.assertEqual([end["shown"], end["pages"]], ["main", 2])

    def test_a_desktop_zoomed_before_its_first_meta_throws_nothing_and_ends_as_at_once(self):
        """Wide: the zoom keys and Ctrl+wheel saved the scale by reading the missing meta, and threw."""
        self.check_zoom(DESK)

    def test_a_mid_window_zoomed_before_its_first_meta_throws_nothing_and_ends_as_at_once(self):
        """The side panel band (compact): the zoom compared with the screen's scale by reading the missing meta."""
        self.check_zoom(MID)

    def test_a_phone_zoomed_before_its_first_meta_throws_nothing_and_ends_as_at_once(self):
        """A touch phone: the zoom keys of an attached keyboard, the sheet's [더보기]."""
        self.check_zoom(PHONE)

    def test_a_desktops_frame_changed_before_its_first_meta_throws_nothing_and_is_kept(self):
        """Wide: the outline toggle fitted the pages by reading the missing meta, and threw."""
        self.check_frame(DESK)

    def test_a_mid_windows_frame_changed_before_its_first_meta_throws_nothing_and_is_kept(self):
        """The side panel band: the outline and panel toggles relaid the page out by reading the missing meta."""
        self.check_frame(MID)

    def test_a_phones_frame_changed_before_its_first_meta_throws_nothing_and_is_kept(self):
        """A touch phone: the sheet's toggle and its key."""
        self.check_frame(PHONE)
