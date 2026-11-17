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


def sg_json():
    """The suggested edit the stored-draft test keeps, as JSON gives it back."""
    return {
        "on": True,
        "text": "new",
        "base": "old",
        "file": "a.tex",
        "lo": 3,
        "hi": 4,
        "had": None,
        "current": {"text": "old", "file": "a.tex", "lo": 3, "hi": 4},
        "reading": "",
        "fail": None,
    }


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

    def test_an_api_error_is_the_error_api_throws_and_nothing_else_is(self):
        """isApiError (platform/api.ts) tells the refusal api() throws (apiError: an Error with its status and body) from
        what else a request throws - a network failure, an ended request, a value that is no Error."""
        got = self.run_js(
            extract_js_fn("apiError"),
            extract_js_fn("isApiError"),
            r"""
            const refused = apiError(409, {error: 'conflict'});
            const ended = new Error('aborted'); ended.name = 'AbortError';
            console.log(JSON.stringify([
              [refused instanceof Error, refused.message, refused.status, refused.data],
              isApiError(refused),
              isApiError(Object.assign(new Error('HTTP 500'), {status: 500})),
              isApiError(new TypeError('Failed to fetch')),
              isApiError(ended),
              isApiError(Object.assign(new Error('x'), {status: '500'})),
              isApiError({status: 403, data: {error: 'no'}}),
              isApiError(null),
              isApiError(undefined),
              isApiError('HTTP 500'),
            ]));
            """,
        )
        self.assertEqual(
            got,
            [
                [True, "HTTP 409", 409, {"error": "conflict"}],
                True,
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                False,
            ],
        )

    def test_a_record_is_any_object_and_nothing_else_is(self):
        """isRecord (platform/tables.ts) lets a value read from outside the code be read by field: any object (an
        array too), never null or a primitive."""
        got = self.run_js(
            extract_js_fn("isRecord"),
            r"""
            console.log(JSON.stringify([
              isRecord({}), isRecord({a: 1}), isRecord([]),
              isRecord(null), isRecord(undefined), isRecord('x'), isRecord(0), isRecord(true),
            ]));
            """,
        )
        self.assertEqual(got, [True, True, True, False, False, False, False, False])

    def test_a_stored_composer_draft_is_read_as_the_composer_writes_it_and_its_note_is_never_lost(self):
        """storedDraft (composer/flow-draft.ts) reads back what draftRecord writes. A draft written before suggested
        edits (no sg) is read; a part the draft only carries along that is not as written is left out and the note
        stays; a selection or build that is not as written leaves the note to wait for the next pick; a value of another
        version, of no document or without a note is no draft."""
        got = self.run_js(
            extract_js_fn("isRecord"),
            extract_js_fn("isSuggestDraft"),
            extract_js_fn("storedDraft"),
            r"""
            const sg = {on: true, text: 'new', base: 'old', file: 'a.tex', lo: 3, hi: 4, had: null,
              current: {text: 'old', file: 'a.tex', lo: 3, hi: 4}, reading: '', fail: null};
            const draft = {v: 1, doc: 'ms', build: 'pages-1', cur: {page: 2, frac: [0, 0, 1, 1]}, note: '메모',
              mentions: ['alice'], kind: 'question', assign: {v: 'alice', touched: true}, sg};
            const read = (value) => storedDraft(value);
            console.log(JSON.stringify([
              JSON.stringify(read(draft)) === JSON.stringify(draft),
              read({...draft, sg: undefined}).sg,
              read({...draft, doc: null}).doc,
              read({...draft, mentions: [1, 'bob'], kind: 3, assign: {v: 1}, sg: {...sg, fail: 'x'}}),
              read({...draft, cur: 'x'}), read({...draft, build: 5}),
              read({...draft, v: 2}), read({...draft, doc: 3}), read({...draft, note: null}),
              read(null), read('draft'), read([]),
            ]));
            """,
        )
        self.assertEqual(
            got,
            [
                True,
                None,
                None,
                {
                    "v": 1,
                    "doc": "ms",
                    "build": "pages-1",
                    "cur": {"page": 2, "frac": [0, 0, 1, 1]},
                    "note": "메모",
                    "mentions": ["bob"],
                    "assign": None,
                    "sg": None,
                },
                {
                    "v": 1,
                    "doc": "ms",
                    "build": "",
                    "cur": None,
                    "note": "메모",
                    "mentions": ["alice"],
                    "kind": "question",
                    "assign": {"v": "alice", "touched": True},
                    "sg": sg_json(),
                },
                {
                    "v": 1,
                    "doc": "ms",
                    "build": "",
                    "cur": None,
                    "note": "메모",
                    "mentions": ["alice"],
                    "kind": "question",
                    "assign": {"v": "alice", "touched": True},
                    "sg": sg_json(),
                },
                None,
                None,
                None,
                None,
                None,
                None,
            ],
        )

    def test_a_stored_reason_draft_is_read_by_its_fields_and_one_that_is_not_is_none(self):
        """parseDraft (verdict/state-drafts.ts) reads a kept reason draft field by field, each with its default; a
        value without text is no draft, and a part or a lost write that is not as written is left out."""
        got = self.run_js(
            extract_js_fn("isRecord"),
            extract_js_fn("isReasonTry"),
            extract_js_fn("parseDraftParts"),
            extract_js_fn("parseDraft"),
            r"""
            const tried = {text: 't', rev: 2, pre: '', stamp: false, post: ''};
            console.log(JSON.stringify([
              parseDraft({text: 'why', base: 'was', rev: 3, mode: 'add', folded: 1, at: '9', tried: [tried, {text: 1}],
                from: [{k: 'ms:1', s: 0, e: 3, tried: [tried]}, {k: 'ms:2', s: 2, e: 9}, 'ms:3', null]}),
              parseDraft({text: 'why', from: 'ms:4'}).from,
              parseDraft({text: '  '}), parseDraft({}), parseDraft(null), parseDraft('why'), parseDraft([]),
            ]));
            """,
        )
        self.assertEqual(
            got,
            [
                {
                    "text": "why",
                    "base": "was",
                    "rev": 3,
                    "mode": "add",
                    "folded": True,
                    "at": 9,
                    "tried": [{"text": "t", "rev": 2, "pre": "", "stamp": False, "post": ""}],
                    "from": [
                        {
                            "k": "ms:1",
                            "s": 0,
                            "e": 3,
                            "tried": [{"text": "t", "rev": 2, "pre": "", "stamp": False, "post": ""}],
                        }
                    ],
                },
                [{"k": "ms:4", "s": 0, "e": 3, "tried": []}],
                None,
                None,
                None,
                None,
                None,
            ],
        )

    def test_a_kept_view_is_a_page_view_or_a_reading_line_as_save_view_writes_them(self):
        """isKeptView (documents/flow-switch.ts) takes the views saveView writes - a page view with its scale or, as
        releases before the scale wrote it, its page width, and a reading line - and nothing else, so a view of
        another shape is not restored."""
        got = self.run_js(
            extract_js_fn("isRecord"),
            extract_js_fn("isKeptView"),
            r"""
            console.log(JSON.stringify([
              isKeptView({page: 2, frac: 0.5, k: 1.2, zoomed: false, sl: 0, lay: 'wide'}),
              isKeptView({page: 2, frac: 0.5, w: 800, zoomed: true, sl: 4, lay: 'mid'}),
              isKeptView({line: 12, off: 3, lay: 'narrow'}),
              isKeptView({page: 2, frac: 0.5, lay: null}),
              isKeptView({page: 2, frac: null, k: 1, lay: 'wide'}),
              isKeptView({page: '2', frac: 0.5, lay: 'wide'}),
              isKeptView({page: 2, frac: 0.5, zoomed: 'yes', lay: 'wide'}),
              isKeptView({line: 12, off: 3, k: 1, lay: 'wide'}),
              isKeptView({line: 12, lay: 'wide'}),
              isKeptView({page: 2, frac: 0.5}),
              isKeptView(null), isKeptView([2, 0.5]),
            ]));
            """,
        )
        self.assertEqual(got, [True, True, True, True, False, False, False, False, False, False, False, False])

    def test_the_seen_records_read_a_field_only_as_it_is_written(self):
        """seenDoc (documents/flow-updates.ts) and seenRecordOf (revisions/flow.ts) read one document's record of what
        this browser saw; a store or a record that is not as written is read as nothing seen."""
        got = self.run_js(
            extract_js_fn("isRecord"),
            extract_js_fn("seenStore"),
            extract_js_fn("seenDoc"),
            extract_js_fn("readSeenRecords"),
            extract_js_fn("seenRecordOf"),
            r"""
            let SEEN_MEM = null, stored = {};
            const localStorage = {getItem: (key) => stored[key] === undefined ? null : stored[key]};
            const out = [];
            stored = {limnSeen: JSON.stringify({v: 1, docs: {ms: {ver: 'src:1', rev: 'a'}, nt: {ver: 2}, xx: 'src:1'}}),
              limnRevSeen: JSON.stringify({ms: {id: 'c1', at: '11-17 10:00'}, nt: {id: 3}, xx: 'c1'})};
            out.push([seenDoc('ms'), seenDoc('nt'), seenDoc('xx'), seenRecordOf('ms'), seenRecordOf('nt'), seenRecordOf('xx')]);
            stored = {limnSeen: JSON.stringify({v: 1, docs: 'ms'}), limnRevSeen: '5'};
            out.push([seenDoc('ms'), seenRecordOf('ms')]);
            stored = {limnSeen: 'not json', limnRevSeen: 'null'};
            out.push([seenDoc('ms'), seenRecordOf('ms')]);
            console.log(JSON.stringify(out));
            """,
        )
        self.assertEqual(
            got,
            [
                [{"ver": "src:1", "rev": "a"}, None, None, {"id": "c1", "at": "11-17 10:00"}, None, None],
                [None, None],
                [None, None],
            ],
        )

    def test_the_preferences_are_an_object_and_each_reader_takes_its_default_for_another_value(self):
        """prefs (platform/prefs.ts) is the stored object or none; the list order and the list sections read their key
        only when it is as written."""
        got = self.run_js(
            "const SECTION_OPEN_DEFAULT = { open: true, review: true, done: false };",
            extract_js_fn("isRecord"),
            extract_js_fn("prefs"),
            extract_js_fn("listOrderOf"),
            extract_js_fn("readSectionsExpanded"),
            r"""
            let stored = null;
            const localStorage = {getItem: () => stored};
            const out = [];
            for (const value of ['{"order":"page","sec":{"done":true}}', '[1]', '"x"', 'null', 'not json']) {
              stored = value;
              out.push(prefs());
            }
            out.push([listOrderOf('page'), listOrderOf('PAGE'), listOrderOf(3), listOrderOf(undefined)]);
            out.push([readSectionsExpanded('done'), readSectionsExpanded({done: 1})]);
            console.log(JSON.stringify(out));
            """,
        )
        self.assertEqual(
            got,
            [
                {"order": "page", "sec": {"done": True}},
                [1],
                {},
                {},
                {},
                ["page", "new", "new", "new"],
                [{"open": True, "review": True, "done": False}, {"open": True, "review": True, "done": False}],
            ],
        )

    def test_the_parse_workers_answers_are_the_answers_the_page_declares(self):
        """The Markdown parse worker (md-parse.mjs, its own message handler, on the vendored markdown-it) answers each
        question the page asks with a message markdownParseAnswer (markdown/view.ts) reads as declared - the tokens, a
        limit with its counts, a parse error - and every token carries exactly the fields MarkdownToken declares. A
        message of no known form is none, and one to the job in flight ends it as a parse error (jobAnswer)."""
        worker = (PKG / "viewer" / "md-parse.mjs").read_text(encoding="utf-8")
        bundle = (PKG / "vendor" / "markdown-it" / "markdown-it.esm.min.mjs").as_uri()
        source = "\n".join(
            [
                "---\ntitle: x\n---",
                '# Head *em* `code`\n\npara [link](http://example.com "t") ![alt](i.png) <b>html</b>\nnext line',
                "> quote\n\n- a\n  - b\n1. one",
                "| a | b |\n|:--|--:|\n| 1 | 2 |",
                "```py\ncode\n```\n\n    indented",
                "$$\nx^2\n$$\n\ninline $a+b$ and \\(c\\) cut $x\ny$ here",
                "<div>\nblock html\n</div>\n\n***",
            ]
        )
        got = self.run_js(
            extract_js_fn("isRecord"),
            extract_js_fn("isMarkdownToken"),
            extract_js_fn("markdownParseAnswer"),
            extract_js_fn("jobAnswer"),
            "const answers = []; const self = {}; const postMessage = (m) => answers.push(m); let markdownit = null;",
            worker[worker.index("function mdParser(") :],
            r"""
            const DECLARED = ['type', 'tag', 'nesting', 'map', 'content', 'info', 'hidden', 'level', 'markup', 'attrs',
              'children'].sort().join();
            const keys = new Set();
            const walk = (tokens) => tokens.forEach((t) => { keys.add(Object.keys(t).sort().join()); if (t.children) walk(t.children); });
            import(%s).then((module) => {
              markdownit = module.default;
              const limits = {nesting: 20, blocks: 30000, inlines: 150000};
              const ask = (id, text, given) => self.onmessage({data: {id, text, limits: given || limits}});
              ask(1, %s);
              ask(2, '> '.repeat(30) + 'deep');
              ask(3, 'a\n\nb\n\nc', {...limits, blocks: 2});
              ask(4, 'a *b* c', {...limits, inlines: 1});
              ask(5, 7);
              answers.forEach((answer) => { if (answer.ok) walk(answer.tokens); });
              const read = answers.map(markdownParseAnswer);
              const job = {id: 9};
              console.log(JSON.stringify({
                kinds: read.map((answer) => answer && [answer.id, answer.ok, answer.ok ? answer.tokens.length > 20 : answer.limit]),
                same: read.every((answer, i) => JSON.stringify(answer) === JSON.stringify(answers[i])),
                keys: [...keys].every((k) => k === DECLARED),
                attrs: answers[0].tokens.some((t) => (t.children || []).some((c) => c.attrs && c.attrs.length)),
                refused: [
                  markdownParseAnswer({...answers[0], tokens: [{...answers[0].tokens[0], map: [1]}]}),
                  markdownParseAnswer({...answers[0], tokens: [{...answers[0].tokens[0], hidden: 0}]}),
                  markdownParseAnswer({...answers[0], tokens: [{...answers[0].tokens[1], children: [{type: 'text'}]}]}),
                  markdownParseAnswer({id: 1, ok: false, limit: 'blocks', count: 3}),
                  markdownParseAnswer({id: 1, ok: false}),
                  markdownParseAnswer({id: '1', ok: true, tokens: []}),
                  markdownParseAnswer({id: 1, ok: 1, tokens: []}),
                  markdownParseAnswer(null),
                ],
                job: [jobAnswer(job, {id: 9, ok: true, tokens: []}), jobAnswer(job, {id: 9, ok: 'yes'}),
                  jobAnswer(job, {id: 8, ok: true, tokens: []}), jobAnswer(job, null)],
              }));
            });
            """
            % (json.dumps(bundle), json.dumps(source)),
        )
        self.assertEqual(
            got,
            {
                "kinds": [
                    [1, True, True],
                    [2, False, "nesting"],
                    [3, False, "blocks"],
                    [4, False, "inlines"],
                    [5, False, "error"],
                ],
                "same": True,
                "keys": True,
                "attrs": True,
                "refused": [None] * 8,
                "job": [{"id": 9, "ok": True, "tokens": []}, {"ok": False, "limit": "error"}, None, None],
            },
        )

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
