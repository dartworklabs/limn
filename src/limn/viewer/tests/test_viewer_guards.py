"""The viewer's guards on what its handlers and helpers are given (docs/handbook/viewer.md §타입 검사): a value that is not
what the code reads - an event aimed at no element, a key the server left out, an owner or a pin without its lines, a
control drawn outside a card - is narrowed before it is used, and gets the code's safe nothing.

- ``GuardRules`` runs the shared helpers (eventElement, tableEntry) and the guarded functions under node, pulled from
  the served page.
- ``NonElementTargets`` drives the real viewer: events aimed at a text node, which is no element, reach the handlers
  that look around their target, and a card action outside any card sends nothing.

Run: LIMN_TEST_REQUIRE_BROWSER=1 uv run pytest -q src/limn/viewer/tests/test_viewer_guards.py
"""

import json
import shutil
import unittest

from helpers import PKG, extract_js_fn, js_const, js_listener_body, js_markup, run_node
from helpers_browser import BrowserBase, nothing_follows

PHONE = {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True}


@unittest.skipUnless(shutil.which("node"), "node not available")
class GuardRules(unittest.TestCase):
    """The helpers and guarded functions as pure functions of what they are given."""

    def run_js(self, *parts: str):
        """The JSON value the last part logs, with the earlier parts (pulled functions, stubs) defined first."""
        return json.loads(run_node("\n".join(parts)))

    def test_an_events_element_is_its_target_only_when_that_is_an_element(self):
        got = self.run_js(
            "class Element {}",
            extract_js_fn("eventElement"),
            r"""
            const element = new Element();
            console.log(JSON.stringify([
              eventElement({ target: element }) === element,
              eventElement({ target: null }),
              eventElement({ target: { closest() { return 1; } } }),
            ]));
            """,
        )
        self.assertEqual(got, [True, None, None])

    def test_a_module_is_the_pdf_library_only_with_get_document_and_the_worker_options(self):
        """What the viewer imports as PDF.js is narrowed before it is used: the vendored module is the library, and a
        value without a getDocument function or without the worker options (nothing, a page that answered with
        something else) is not, so importPdfLibrary rejects instead of the first call failing on it."""
        vendored = (PKG / "vendor" / "pdfjs" / "pdf.min.mjs").as_uri()
        got = self.run_js(
            extract_js_fn("isPdfLibrary"),
            r"""
            const options = class { static workerSrc = ''; };
            import(%s).then((real) => console.log(JSON.stringify([
              isPdfLibrary(real),
              isPdfLibrary({ getDocument() {}, GlobalWorkerOptions: options }),
              isPdfLibrary({ GlobalWorkerOptions: options }),
              isPdfLibrary({ getDocument() {} }),
              isPdfLibrary({ getDocument: 1, GlobalWorkerOptions: options }),
              isPdfLibrary({ getDocument() {}, GlobalWorkerOptions: {} }),
              isPdfLibrary({ getDocument() {}, GlobalWorkerOptions: class {} }),
              isPdfLibrary({}),
              isPdfLibrary(null),
              isPdfLibrary(undefined),
              isPdfLibrary('pdf.js'),
            ])));
            """
            % json.dumps(vendored),
        )
        self.assertEqual(got, [True, True, False, False, False, False, False, False, False, False, False])

    def test_a_refusal_is_an_object_with_an_error_and_nothing_else_is(self):
        """isRefusal (platform/api.ts) tells a refusal's body from an endpoint's answer by its error field, and is false
        - never a throw - for an answer the server did not give as JSON (null) or gave as no object."""
        got = self.run_js(
            extract_js_fn("isRefusal"),
            r"""
            console.log(JSON.stringify([
              isRefusal({error: 'conflict', reason: 'conflict', pin: {id: 1}}),
              isRefusal({error: '', reason: 'x'}),
              isRefusal({ok: true, pin: {id: 1}}),
              isRefusal({lines: ['a']}),
              isRefusal(null),
              isRefusal(undefined),
              isRefusal('error'),
              isRefusal(5),
              isRefusal([]),
            ]));
            """,
        )
        self.assertEqual(got, [True, True, False, False, False, False, False, False, False])

    def test_a_table_entry_is_none_without_a_key_as_for_a_key_the_table_lacks(self):
        got = self.run_js(
            extract_js_fn("tableEntry"),
            r"""
            const table = { render: 'rendering', null: 'named null' };
            console.log(JSON.stringify([
              tableEntry(table, 'render'),
              tableEntry(table, 'latex') === undefined,
              tableEntry(table, null) === undefined,
              tableEntry(table, undefined) === undefined,
            ]));
            """,
        )
        self.assertEqual(got, ["rendering", True, True, True])

    def test_a_rung_is_found_by_its_level_or_a_merged_one_and_none_without_a_key(self):
        got = self.run_js(
            extract_js_fn("levelOf"),
            r"""
            const owner = { levels: [{ level: 'para', lo: 1, hi: 2, merged: ['env'] }] };
            console.log(JSON.stringify([
              levelOf(owner, 'para').level,
              levelOf(owner, 'env').level,
              levelOf(owner, null) === undefined,
              levelOf(owner, undefined) === undefined,
              levelOf({}, 'para') === undefined,
            ]));
            """,
        )
        self.assertEqual(got, ["para", "para", True, True, True])

    def test_an_owner_is_on_lines_only_with_its_file_and_both_ends(self):
        got = self.run_js(
            extract_js_fn("onLines"),
            r"""
            console.log(JSON.stringify([
              onLines({ file: '/a.tex', lo: 3, hi: 4 }),
              onLines({ file: '/a.tex', lo: 3 }),
              onLines({ lo: 3, hi: 4 }),
              onLines({ file: null, lo: 3, hi: 4 }),
            ]));
            """,
        )
        self.assertEqual(got, [True, False, False, False])

    def test_the_range_caption_of_an_owner_without_lines_is_empty(self):
        """Without lines there is no range to name: the caption was 'L undefined' and 'NaN' lines, and is empty now."""
        got = self.run_js(
            "function esc(text) { return String(text == null ? '' : text); }",
            js_markup(),
            extract_js_fn("onLines"),
            extract_js_fn("rangeCap"),
            r"""
            console.log(JSON.stringify([rangeCap({ name: 'main.tex', levels: [] }, false).text]));
            """,
        )
        self.assertEqual(got, [""])

    def test_a_range_applied_to_an_owner_without_lines_does_nothing(self):
        got = self.run_js(
            "const LOG = [];",
            "function excerptBox() { LOG.push('box'); return null; }",
            "function setLines() { LOG.push('setLines'); }",
            "function excerptRedraw() { LOG.push('redraw'); }",
            "function refetchSnip() { LOG.push('refetch'); }",
            extract_js_fn("onLines"),
            extract_js_fn("applyRange"),
            r"""
            const owner = { name: 'main.tex', n_lines: 30 };
            applyRange(owner, [3, 5], 3);
            console.log(JSON.stringify([LOG, owner]));
            """,
        )
        self.assertEqual(got, [[], {"name": "main.tex", "n_lines": 30}])

    def test_the_excerpt_of_an_owner_without_lines_is_hidden_and_empty(self):
        """It drew rows for line 'undefined' before; it is cleared and hidden now, as for a region."""
        got = self.run_js(
            "const document = { activeElement: null };",
            "function isRegion() { return false; }",
            extract_js_fn("onLines"),
            extract_js_fn("drawExcerpt"),
            r"""
            const box = { hidden: false, cleared: 0, contains() { return false; }, replaceChildren() { this.cleared++; } };
            drawExcerpt({ name: 'main.tex', levels: [], snippet: '' }, box, true);
            console.log(JSON.stringify([box.hidden, box.cleared]));
            """,
        )
        self.assertEqual(got, [True, 1])

    def test_a_revision_range_press_without_a_mode_does_nothing(self):
        got = self.run_js(
            "const LOG = [];",
            "const REVISION_VIEW = { rows: [{ id: 'abc1234' }], range: { mode: 'one', start: 'abc1234', end: 'abc1234' }, seen: null };",
            "function rangeMode() { LOG.push('rangeMode'); return {}; }",
            "function showRange() { LOG.push('showRange'); }",
            extract_js_fn("setRevisionRange"),
            r"""
            setRevisionRange(undefined);
            setRevisionRange('from');
            console.log(JSON.stringify(LOG));
            """,
        )
        self.assertEqual(got, ["rangeMode", "showRange"])

    def test_a_revision_target_without_lines_touches_no_hunk(self):
        got = self.run_js(
            extract_js_fn("pinFileIndex"),
            extract_js_fn("hunkRanges"),
            extract_js_fn("touchesPin"),
            r"""
            const files = [{ name: 'main.tex', text: '@@ -10,2 +10,3 @@\n+x' }];
            console.log(JSON.stringify([
              touchesPin(files, { file: '/m/main.tex', lo: 11, hi: 11 }),
              touchesPin(files, { file: '/m/main.tex' }),
            ]));
            """,
        )
        self.assertEqual(got, [True, False])

    def test_a_line_without_a_box_has_no_edges_and_changes_no_other_lines(self):
        """searchEdges on a two-column page with a crossing caption: a line without geometry among them gets no edges
        and leaves every other line's edges as they are without it."""
        got = self.run_js(
            js_const("SEARCH_GUTTER"),
            extract_js_fn("searchBlocks"),
            extract_js_fn("searchGutter"),
            extract_js_fn("searchEdges"),
            r"""
            const at = (x0, x1, y) => ({ box: { x0, x1, y, size: 12, ang: 0 } });
            const lines = [];
            for (let i = 0; i < 4; i++) lines.push(at(72, 290, 700 - 15 * i), at(322, 540, 700 - 15 * i));
            lines.push(at(72, 540, 640));
            const without = searchEdges(lines);
            const withBoxless = searchEdges([...lines.slice(0, 3), { box: null }, ...lines.slice(3)]);
            const same = JSON.stringify(withBoxless.toSpliced(3, 1)) === JSON.stringify(without);
            console.log(JSON.stringify([withBoxless[3], same]));
            """,
        )
        self.assertEqual(got, [None, True])

    def test_a_hit_on_a_page_not_read_has_no_boxes(self):
        """A hit's page is read before the hit is found; were it not, searchBoxes answers no boxes, keeps none, and
        throws nothing."""
        got = self.run_js(
            r"""
            const SEARCH = { doc: { numPages: 2 }, text: new Map() };
            """,
            extract_js_fn("searchPages"),
            extract_js_fn("searchBoxes"),
            r"""
            const hit = { page: 2, pieces: [[0, 0, 1]], boxes: null };
            console.log(JSON.stringify([searchBoxes(hit), hit.boxes]));
            """,
        )
        self.assertEqual(got, [[], None])

    def test_a_zoom_point_given_by_half_anchors_on_the_areas_centre(self):
        """Without both coordinates the anchor is the PDF area's centre, as without any; a half point made a NaN anchor."""
        got = self.run_js(
            r"""
            class HTMLElement {}
            const page = Object.assign(new HTMLElement(), {
              getBoundingClientRect: () => ({ left: 0, top: 0, bottom: 400, width: 200, height: 400 }),
            });
            const area = { clientWidth: 200, clientHeight: 400, getBoundingClientRect: () => ({ left: 0, top: 0 }) };
            const $ = () => area, document = { querySelectorAll: () => [page] };
            """,
            extract_js_fn("findAll"),
            extract_js_fn("zoomAnchor"),
            r"""
            const anchor = (x, y) => { const got = zoomAnchor(x, y); return [got.cx, got.cy, got.fx, got.fy]; };
            console.log(JSON.stringify([anchor(), anchor(20), anchor(20, 40)]));
            """,
        )
        self.assertEqual(got, [[100, 200, 0.5, 0.5], [100, 200, 0.5, 0.5], [20, 40, 0.1, 0.1]])

    def test_a_page_press_aimed_at_no_element_prevents_nothing_and_throws_nothing(self):
        """The page's mousedown (pdf/input-selection.ts) keeps the note's focus for a left press on a page: it prevents
        that press, and does nothing for a press whose target is no element (a text node), which threw before."""
        got = self.run_js(
            "class Element { constructor(page) { this.page = page; } closest(s) { return s === '.pg' && this.page ? this : null; } }",
            extract_js_fn("eventElement"),
            "const listener = (event) => {" + js_listener_body("$('#doc')", "mousedown", "eventElement") + "};",
            r"""
            const press = (target, button) => {
              let done = false;
              listener({ target, button, preventDefault() { done = true; } });
              return done;
            };
            console.log(JSON.stringify([
              press(new Element(true), 0),
              press(new Element(false), 0),
              press(new Element(true), 2),
              press({ nodeType: 3 }, 0),
              press(null, 0),
            ]));
            """,
        )
        self.assertEqual(got, [True, False, False, False, False])

    def test_the_grips_hint_is_empty_text_when_the_markup_gives_none(self):
        """GRIP_TIP (layout/flow.ts) is the handle's data-tip, which the open handle's hint is translated from; a handle
        without one gives empty text, not undefined (which the hint would have shown as 'undefined')."""
        got = self.run_js(
            "let TIP;",
            "const $ = () => ({ dataset: TIP === undefined ? {} : { tip: TIP } });",
            "TIP = '끌어서 패널 폭을 바꿉니다';",
            js_const("GRIP_TIP").replace("const GRIP_TIP", "const withTip"),
            "TIP = undefined;",
            js_const("GRIP_TIP").replace("const GRIP_TIP", "const withoutTip"),
            "console.log(JSON.stringify([withTip, withoutTip]));",
        )
        self.assertEqual(got, ["끌어서 패널 폭을 바꿉니다", ""])


class NonElementTargets(BrowserBase):
    """A text node is an event target that is no element: an event dispatched at one inside a handler's box bubbles to
    the handler with that target. Each handler that looks around its target finds no control there and does nothing;
    open() fails the test on any page error, which is what such an event threw before."""

    def text_node_event(self, page, host: str, make: str):
        """Dispatch the event make (a JS expression) at a text node appended to host (a selector, or 'document'),
        then remove the node."""
        page.evaluate(
            """([host, make]) => {
                const box = host === 'document' ? document.body : document.querySelector(host);
                const node = document.createTextNode('');
                box.appendChild(node);
                node.dispatchEvent(new Function('return ' + make)());
                node.remove();
            }""",
            [host, make],
        )

    def test_list_and_panel_handlers_do_nothing_for_a_target_that_is_no_element(self):
        """The pin list's hover, the panel's swipe and the long-press description. The page (#doc) is left out: some of
        its handlers read their target as an element without a guard."""
        page = self.open(0)
        finger = "new PointerEvent('pointerdown', { bubbles: true, isPrimary: true, pointerType: 'touch' })"
        for host, make in (
            ("#pins", "new MouseEvent('mouseover', { bubbles: true })"),
            ("#pins", "new MouseEvent('mouseout', { bubbles: true })"),
            ("#right", finger),
            ("document", finger),
        ):
            with self.subTest(host=host, event=make):
                self.text_node_event(page, host, make)
        self.assertIsNone(page.evaluate("PRESS"))

    def test_the_phone_sheet_takes_no_pull_from_a_target_that_is_no_element(self):
        page = self.open(0, **PHONE)
        page.evaluate("setSide(true)")
        page.evaluate(
            """() => {
                const node = document.createTextNode('');
                document.getElementById('right').appendChild(node);
                const touch = new Touch({ identifier: 1, target: node, clientX: 100, clientY: 600 });
                node.dispatchEvent(new TouchEvent('touchstart', { bubbles: true, touches: [touch], changedTouches: [touch] }));
                node.remove();
            }"""
        )
        nothing_follows(page)

    def test_a_card_action_outside_any_card_sends_nothing(self):
        """A [완료] control drawn in no card has no pin id: it sent POST /api/pins/null/close before, and sends nothing
        now."""
        page = self.open(0)
        sent = []
        page.on("request", lambda request: sent.append(request.url) if "/api/pins/" in request.url else None)
        page.evaluate(
            """() => {
                for (const act of ['close', 'edit', 'view']) {
                    const button = document.createElement('button');
                    button.dataset.act = act;
                    document.body.appendChild(button);
                    button.click();
                    button.remove();
                }
            }"""
        )
        nothing_follows(page)
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
