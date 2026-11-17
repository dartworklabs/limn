"""The guards on values that enter the viewer untyped, fed the real data that reaches them (docs/handbook/viewer.md
§타입 검사): a guard that refuses a value a real source sends turns working data into a failure the person sees, so each
is run over what its source actually produces - not over a sample written for the test.

- ``MarkdownWorkerTokens`` runs the Markdown parse worker's own handler (md-parse.mjs on the vendored markdown-it) over
  every Markdown file in the repository and over a document that uses every construct the viewer's parser reads, and
  holds each answer to markdownParseAnswer and each token to the MarkdownToken declaration.
- ``StoredDrafts`` writes the composer's draft with the real writer (draftRecord, as syncDraft stores it) for every
  selection the composer keeps - the server's own pick answers (traced lines, weighed and unweighed, a figure's
  element, a figure's region), each with every rung the composer can choose, a text document's lines with its real
  ladder, an offline drag - with and without each optional part, and reads it back with storedDraft: each comes back
  as it was written. The releases' earlier forms come back too.
- ``StoredViews`` writes the reading spots (saveView), the preferences the pin list keeps (savePrefs with its section
  states and every order) and what this browser saw (setSeenDoc, setSeenPin) with their own writers, and reads each
  back with its guard (loadViews' isKeptView, readSectionsExpanded, listOrderOf, seenDoc, seenPin).

``StoredDrafts`` also holds isRefusal to the server's real pick bodies. The other guards on real data are held where
their source is: isPdfLibrary and isKatexLibrary by test_vendor_pdfjs_types.py and test_vendor_katex_types.py on the
vendored builds, isApiError by test_viewer_guards.py on what api() throws, and the offline store's guards by the
browser tests of test_viewer_offline_ui.py, which queue and keep through the real writers.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_guard_data.py
"""

import json
import re
import shutil
import unittest
from unittest import mock

from limn.pins.location import (
    http as location_http,
    input as location_input,
    resolve as pick_resolve,
    source as pick_source,
)

from helpers import PKG, ROOT, Base, extract_js_fn, js_const, ps, run_node

VIEW_TS = PKG / "viewer" / "js" / "markdown" / "view.ts"
# Every construct the viewer's markdown-it reads (md-parse.mjs mdParser: CommonMark, GFM tables and strikethrough, raw
# HTML, no linkify, no typographer) and the rules it adds (front matter, display and inline math), so each token type
# and attribute the build can send is sent at least once.
EVERY_CONSTRUCT = r"""---
title: Every construct
tags: [a, b]
---

# Heading one
## Heading *two* with `code`
Setext heading
==============

Setext two
----------

Paragraph with **strong**, __strong__, *em*, _em_, ~~strike~~, `code`, ``code with ` tick``, a [link](http://example.com
"title"), a [bare link](</a path>), an autolink <https://example.com>, an email <alice@example.com>, an image
![alt *text*](img.png "image title"), a reference image ![ref alt][ref], entities &amp; &copy; &#35; &#x41;, an escape
\* and \_, inline <span class="x">html</span> and <br/>, a hard break with spaces<two spaces>
next line\
after a backslash break.
A soft break.

> A quote with **bold**
> > and a nested quote
>
> - a list in a quote

- bullet
  - nested bullet
    1. nested ordered
       > deep quote
- [ ] task-like item
* star bullet

+ plus bullet, loose

  with a second paragraph

1. one
2. two

5) five
6) six

3. three onward

| left | center | right | none |
|:-----|:------:|------:|------|
| a | b | c | d |
| `x` | **y** | [z](u) | |
| \| pipe | ~~s~~ | <i>h</i> | $m$ |

```python {.cls}
fenced code
```

~~~
tilde fence
~~~

```
fence with no info
```

    indented code

***
- - -
___

<div>
html block
</div>

<!-- a comment -->

<details><summary>s</summary>

inner *markdown*

</details>

[ref]: http://example.com "Ref Title"
[text][ref], [ref], [collapsed][] and [collapsed]: /c.

$$
x^2 + y^2
$$

\[
\int f
\]

$$ inline display $$ and inline $a+b$, \(c\), $5 and $10, a cut $x
y$ here, `$not math$` and \$ escaped.
""".replace("<two spaces>", "  ")
# The declared field types of MarkdownToken this test knows how to observe, as JSON kinds: a declaration this table
# does not name fails the test, so a change to the declaration changes the table with it.
KINDS = {
    "string": {"string"},
    "number": {"number"},
    "boolean": {"boolean"},
    "[number, number] | null": {"null", "line pair"},
    "[string, string | number][] | null": {"null", "empty list", "attributes"},
    "MarkdownToken[] | null": {"null", "empty list", "tokens"},
}


def declared_token_fields() -> dict[str, str]:
    """interface MarkdownToken's fields in markdown/view.ts, as name -> type text."""
    body = re.search(r"^interface MarkdownToken \{\n(.*?)^\}", VIEW_TS.read_text(encoding="utf-8"), re.M | re.S)
    assert body, "interface MarkdownToken not found"
    return dict(re.findall(r"^  (\w+): (.+);$", body.group(1), re.M))


def markdown_corpus() -> dict[str, str]:
    """Every Markdown file of the repository (docs, the Handbook, the READMEs, test data), by path, and the
    every-construct document."""
    skip = {"node_modules", ".venv", ".git", "dist"}
    out = {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(ROOT.rglob("*.md"))
        if not skip.intersection(path.relative_to(ROOT).parts)
    }
    out["<every construct>"] = EVERY_CONSTRUCT
    return out


@unittest.skipUnless(shutil.which("node"), "node not available")
class MarkdownWorkerTokens(unittest.TestCase):
    """The worker's answers to real documents are what the page's answer guard and token declaration say."""

    def test_every_answer_to_a_real_document_passes_the_guard_and_every_token_is_as_declared(self):
        """Each Markdown file of the repository and the every-construct document, parsed by md-parse.mjs's handler
        with the page's limits: markdownParseAnswer gives back each answer unchanged, every token (children too) has
        exactly MarkdownToken's fields, each of a JSON kind its declared type allows, an attribute value is a string
        except an ordered list's numeric start, and the every-construct document sends each token type the build can
        send."""
        fields = declared_token_fields()
        self.assertEqual(sorted(set(fields.values()) - set(KINDS)), [])
        corpus = markdown_corpus()
        self.assertGreater(len(corpus), 100)
        worker = (PKG / "viewer" / "md-parse.mjs").read_text(encoding="utf-8")
        bundle = (PKG / "vendor" / "markdown-it" / "markdown-it.esm.min.mjs").as_uri()
        out = run_node(
            "\n".join(
                [
                    extract_js_fn("isRecord"),
                    extract_js_fn("isMarkdownToken"),
                    extract_js_fn("markdownParseAnswer"),
                    "const answers = []; const self = {}; const postMessage = (m) => answers.push(m);"
                    " let markdownit = null;",
                    worker[worker.index("function mdParser(") :],
                    r"""
                    const CORPUS = %s, LIMITS = {nesting: 20, blocks: 30000, inlines: 150000};
                    const kindOf = (value) => {
                      if (value === null) return 'null';
                      if (!Array.isArray(value)) return typeof value;
                      if (!value.length) return 'empty list';
                      if (value.length === 2 && value.every((n) => typeof n === 'number')) return 'line pair';
                      if (value.every((a) => Array.isArray(a) && a.length === 2 && typeof a[0] === 'string'
                          && (typeof a[1] === 'string' || typeof a[1] === 'number'))) return 'attributes';
                      if (value.every((t) => t && typeof t === 'object' && !Array.isArray(t))) return 'tokens';
                      return 'other array';
                    };
                    import(%s).then((module) => {
                      markdownit = module.default;
                      const keys = new Set(), kinds = {}, types = {}, attributes = {}, refused = [], limited = [];
                      const walk = (tokens, where) => tokens.forEach((token) => {
                        keys.add(Object.keys(token).sort().join());
                        for (const [key, value] of Object.entries(token)) (kinds[key] = kinds[key] || new Set()).add(kindOf(value));
                        types[token.type] = (types[token.type] || 0) + 1;
                        for (const [name, value] of token.attrs || [])
                          (attributes[token.type + ' ' + name] = attributes[token.type + ' ' + name] || new Set()).add(typeof value);
                        if (token.children) walk(token.children, where);
                      });
                      Object.entries(CORPUS).forEach(([path, text], index) => {
                        answers.length = 0;
                        self.onmessage({data: {id: index, text, limits: LIMITS}});
                        const answer = answers[0], read = markdownParseAnswer(answer);
                        if (!read || JSON.stringify(read) !== JSON.stringify(answer)) refused.push(path);
                        if (answer.ok) walk(answer.tokens, path); else limited.push([path, answer.limit]);
                      });
                      const sets = (record) => Object.fromEntries(Object.entries(record).map(([k, v]) => [k, [...v].sort()]));
                      console.log(JSON.stringify({keys: [...keys], kinds: sets(kinds), types, attributes: sets(attributes),
                        refused, limited}));
                    });
                    """
                    % (json.dumps(corpus), json.dumps(bundle)),
                ]
            )
        )
        got = json.loads(out)
        self.assertEqual(got["refused"], [])
        self.assertEqual(got["limited"], [])
        self.assertEqual(got["keys"], [",".join(sorted(fields))])
        for name, seen in got["kinds"].items():
            self.assertLessEqual(set(seen), KINDS[fields[name]], name)
        numeric = sorted(name for name, kinds in got["attributes"].items() if kinds != ["string"])
        self.assertEqual(numeric, ["ordered_list_open start"])
        expected_types = {
            "front_matter", "heading_open", "heading_close", "inline", "paragraph_open", "paragraph_close", "text",
            "softbreak", "hardbreak", "strong_open", "strong_close", "em_open", "em_close", "s_open", "s_close",
            "code_inline", "link_open", "link_close", "image", "html_inline", "html_block", "blockquote_open",
            "blockquote_close", "bullet_list_open", "bullet_list_close", "ordered_list_open", "ordered_list_close",
            "list_item_open", "list_item_close", "table_open", "table_close", "thead_open", "thead_close",
            "tbody_open", "tbody_close", "tr_open", "tr_close", "th_open", "th_close", "td_open", "td_close", "fence",
            "code_block", "hr", "math_block", "math_inline",
        }  # fmt: skip
        self.assertEqual(sorted(expected_types - set(got["types"])), [])
        self.assertEqual(
            sorted(got["attributes"]),
            sorted(
                [
                    "image alt", "image src", "image title", "link_open href", "link_open title",
                    "ordered_list_open start", "td_open style", "th_open style",
                ]
            ),
        )  # fmt: skip


# The draft guards and the writer they read back, pulled from the served page.
DRAFT_FUNCTIONS = (
    "isRecord", "isListOf", "isString", "isNumber", "absentOr", "absentNullOr", "isPinElement", "isRung",
    "isPickOverlap", "hasComposerChoice", "isLinePick", "isPointBox", "isPagePick", "earlierOfflinePick",
    "draftSelection", "isSuggestDraft", "storedDraft", "draftRecord", "suggestCopy", "levelOf", "useLevel",
    "paragraphAround", "indentBlockAround", "indentColumns", "textLevels", "lineSnippet", "clipMarkedText",
)  # fmt: skip
# A text document's source, for the ladder textLevels gives its lines.
TEXT_LINES = [
    "Title",
    "",
    "first paragraph line",
    "second paragraph line",
    "",
    "block:",
    "    inner one",
    "    inner two",
]
# An offline drag's selection as v0.4.60 and v0.4.61 wrote it (offline.js offlinePick), field for field.
EARLIER_OFFLINE = {
    "kind": "region", "page": 2, "frac": [0.1, 0.2, 0.3, 0.1], "quote": "words", "file": None, "name": None,
    "lo": None, "hi": None, "pdf": "pages-1", "pdf_build": "pages-1", "doc": None, "offline": True,
    "rect": {"x0": 10, "y0": 20, "x1": 30, "y1": 40}, "levels": [], "overlaps": [], "scope": None, "env": None,
    "elSel": None, "el": None, "via": None, "score": None, "warn": "", "snippet": "", "n_lines": 0,
    "default_level": None,
}  # fmt: skip


@unittest.skipUnless(shutil.which("node"), "node not available")
class StoredDrafts(Base):
    """A draft the composer writes is read back as it was written, for every selection it can keep."""

    def traced_answers(self) -> list[dict]:
        """POST /api/pick's answers for drags on main.tex's page 1, through the server's own pick (SyncTeX and the
        page's text stubbed at their subprocess functions, as PickOutcomes does), each with the frac the viewer always
        sends: a weighed paragraph, a line in the table's environment, and a drag on no text (score null)."""
        D = ps.APP.docs[0]
        out = []
        for line, text in ((8, "Body line seven betaunique."), (14, "x"), (4, "")):
            request = location_input.PickRequest(
                D.dir / "pages", 1, (10.0, 20.0, 150.0, 60.0), (600.0, 800.0), [0.017, 0.025, 0.233, 0.05]
            )
            with (
                mock.patch.object(pick_source, "by_synctex", return_value=(str(D.build / "main.tex"), line, line)),
                mock.patch.object(pick_source, "region_text", return_value=text),
            ):
                picked = pick_resolve.pick(D, request, ps.APP.location_service.context())
            out.append(location_http.pick_answer(picked))
        return out

    def figure_answers(self) -> list[dict]:
        """The recorded figure picks (tests/data/contract_snapshot_figure.json): an element and a region that fell
        back."""
        snapshot = json.loads((ROOT / "tests" / "data" / "contract_snapshot_figure.json").read_text(encoding="utf-8"))
        return [json.loads(e["body"]) for e in snapshot if "picks" in e["step"] and "pins.md" not in e["step"]]

    def test_every_selection_the_composer_keeps_comes_back_from_its_draft_as_written(self):
        """Each selection, as answered and after each rung the composer can choose (useLevel, which also takes a
        figure rung's element as elSel), written by draftRecord with and without @-tags, a touched assignee and a
        suggested edit, and read back by storedDraft: its cur is the selection, its build and note are kept. The
        offline drag of earlier releases comes back in offlinePick's form."""
        answers = self.traced_answers() + self.figure_answers()
        self.assertEqual([a.get("kind") == "region" for a in answers], [False, False, False, False, True])
        self.assertIn(None, [a.get("score") for a in answers])
        got = json.loads(
            run_node(
                "\n".join(
                    [
                        *[extract_js_fn(name) for name in DRAFT_FUNCTIONS],
                        r"""
                        const ANSWERS = %s, TEXT_LINES = %s, EARLIER = %s;
                        const MARKDOWN_VIEW = {lines: TEXT_LINES}, BLOCK_LABEL_CHARS = 12, TAB_COLUMNS = 4;
                        const NOTE = {value: '', _mentions: null}, COMPOSER = {hidden: false};
                        const $ = (selector) => (selector === '#note' ? NOTE : COMPOSER);
                        let DOC = 'main', META = {pages_build: 'pages-1', label: 'L'}, KIND_NEW = 'fix';
                        const COMPOSE = {current: null}, ASSIGN_NEW = {v: 'agent', touched: false};
                        const OFF_SUGGEST = {on: false, text: '', base: null, file: null, lo: 0, hi: 0, had: null,
                          current: null, reading: '', fail: null};
                        let SUGGEST_DRAFT = OFF_SUGGEST;
                        const copy = (value) => JSON.parse(JSON.stringify(value));
                        const selections = [];
                        for (const answer of ANSWERS) {
                          selections.push(copy(answer));
                          for (const rung of answer.levels || []) {
                            const chosen = copy(answer);
                            chosen.scope = null; chosen.elSel = null;
                            useLevel(chosen, rung.level);
                            selections.push(chosen);
                          }
                        }
                        const lines = {lo: 3, hi: 3},
                          lineLevels = textLevels(lines),
                          linePick = {doc: 'notes', file: 'notes.txt', name: 'notes.txt', lo: 3, hi: 3, raw_lo: 3,
                            raw_hi: 3, kind: 'lines', score: null, warn: null, snippet: lineSnippet(3, 3),
                            levels: lineLevels, default_level: 'raw', n_lines: TEXT_LINES.length, quote: 'first',
                            overlaps: []};
                        selections.push(copy(linePick));
                        for (const rung of lineLevels) {
                          const chosen = copy(linePick);
                          chosen.scope = null; chosen.elSel = null;
                          useLevel(chosen, rung.level);
                          selections.push(chosen);
                        }
                        selections.push({kind: 'region', page: 2, frac: [0.1, 0.2, 0.3, 0.1], quote: 'words', name: '',
                          pdf: 'pages-1', pdf_build: '', doc: 'main', offline: true,
                          rect: {x0: 10, y0: 20, x1: 30, y1: 40}, levels: [], overlaps: [], scope: null, env: null,
                          elSel: null, warn: '', snippet: '', n_lines: 0});
                        const parts = [
                          {note: '메모', mentions: null, assign: {v: 'agent', touched: false}, suggest: false},
                          {note: '@bob 봐 주세요', mentions: ['bob@example.com'], assign: {v: 'bob@example.com', touched: true},
                            suggest: true},
                        ];
                        const back = [];
                        for (const selection of selections)
                          for (const part of parts) {
                            COMPOSE.current = selection;
                            NOTE.value = part.note;
                            NOTE._mentions = part.mentions && new Set(part.mentions);
                            Object.assign(ASSIGN_NEW, part.assign);
                            SUGGEST_DRAFT = part.suggest
                              ? {...OFF_SUGGEST, on: true, text: 'new', base: 'old', file: selection.file || null,
                                 lo: selection.lo || 0, hi: selection.hi || 0}
                              : OFF_SUGGEST;
                            const written = JSON.stringify(draftRecord()), record = storedDraft(JSON.parse(written));
                            back.push(!!record && JSON.stringify(record.cur) === JSON.stringify(selection)
                              && record.build === JSON.parse(written).build && record.note === part.note
                              && JSON.stringify(record.mentions) === JSON.stringify(part.mentions || [])
                              && !!record.sg && record.sg.on === part.suggest);
                          }
                        const earlier = storedDraft({v: 1, doc: 'main', build: 'pages-1', cur: EARLIER, note: 'n'});
                        console.log(JSON.stringify({n: selections.length, back, earlier: earlier && earlier.cur}));
                        """
                        % (json.dumps(answers), json.dumps(TEXT_LINES), json.dumps(EARLIER_OFFLINE)),
                    ]
                )
            )
        )
        self.assertGreater(got["n"], 12)
        self.assertEqual(got["back"], [True] * len(got["back"]))
        self.assertEqual(
            got["earlier"],
            {
                "kind": "region", "page": 2, "frac": [0.1, 0.2, 0.3, 0.1], "quote": "words", "name": "",
                "pdf": "pages-1", "pdf_build": "pages-1", "offline": True, "rect": {"x0": 10, "y0": 20, "x1": 30, "y1": 40},
                "levels": [], "overlaps": [], "scope": None, "env": None, "elSel": None, "warn": "", "snippet": "",
                "n_lines": 0,
            },
        )  # fmt: skip

    def test_the_servers_pick_refusals_are_refusals_and_its_answers_are_not(self):
        """isRefusal (platform/api.ts) on POST /api/pick's real bodies: every refusal the server's pick_answer gives
        (each PICK_REFUSALS type, filled with its detail) and the stale-build answer are refusals; the traced, element
        and region answers are not."""
        D = ps.APP.docs[0]
        refusals = [
            location_http.pick_answer(pick_resolve.GeneratedFile(".bbl")),
            location_http.pick_answer(pick_resolve.SynctexOutside(D.dir / "x.tex")),
            location_http.pick_answer(pick_resolve.SourceUnreadable(D.dir / "bin.tex")),
            location_http.pick_answer(pick_resolve.NoSourceHere()),
            location_http.pick_build_gone(),
        ]
        self.assertEqual(len(refusals) - 1, len(location_http.PICK_REFUSALS))
        answers = self.traced_answers() + self.figure_answers()
        got = json.loads(
            run_node(
                "\n".join(
                    [
                        extract_js_fn("isRefusal"),
                        "console.log(JSON.stringify([%s.map(isRefusal), %s.map(isRefusal)]));"
                        % (json.dumps(refusals, default=str), json.dumps(answers)),
                    ]
                )
            )
        )
        self.assertEqual(got, [[True] * len(refusals), [False] * len(answers)])


@unittest.skipUnless(shutil.which("node"), "node not available")
class StoredViews(unittest.TestCase):
    """What the viewer keeps in the browser's storage is read back by its guard as its writer wrote it."""

    def test_each_kept_view_preference_and_seen_record_reads_back_as_its_writer_wrote_it(self):
        """saveView on a PDF document (a page anchor or none, zoomed or not, every layout) and on a drawn document (a
        reading line), stored by saveViews, comes back from loadViews; the list sections and order savePrefs stores
        come back from readSectionsExpanded and listOrderOf; seen records setSeenDoc and setSeenPin store come back
        from seenDoc and seenPin."""
        got = json.loads(
            run_node(
                "\n".join(
                    [
                        js_const("LAYOUT_MODE"),
                        js_const("SECTION_OPEN_DEFAULT"),
                        *[
                            extract_js_fn(name)
                            for name in (
                                "isRecord",
                                "saveView",
                                "saveViews",
                                "loadViews",
                                "isKeptView",
                                "prefs",
                                "savePrefs",
                                "readSectionsExpanded",
                                "listOrderOf",
                                "seenStore",
                                "seenSave",
                                "seenDoc",
                                "setSeenDoc",
                                "verAfter",
                                "seenPin",
                                "setSeenPin",
                            )
                        ],  # fmt: skip
                        r"""
                        const store = (map) => ({getItem: (k) => (map.has(k) ? map.get(k) : null),
                          setItem: (k, v) => map.set(k, String(v)), removeItem: (k) => map.delete(k)});
                        const sessionStorage = store(new Map()), localStorage = store(new Map());
                        class HTMLElement {}
                        const document = {};
                        let DOC = 'a', META = {}, LAYOUT = 'wide', PAGE_SCALE = 1.25, ZOOMED = false, ANCHOR = null,
                          MARKDOWN = false, READING = null, SEEN_MEM = null;
                        const VIEW_BY = new Map(), LEFT = {scrollLeft: 0};
                        const $ = () => LEFT, findMaybe = () => (MARKDOWN ? null : new HTMLElement());
                        const topAnchor = () => ANCHOR, isMarkdownDoc = () => MARKDOWN, multiDoc = () => true;
                        const docInfo = (doc) => ({key: doc});
                        const markdownSurface = () => ({reading: () => ({shown: DOC}), readingAnchor: () => READING});
                        const views = [], results = {};
                        for (const layout of Object.values(LAYOUT_MODE))
                          for (const [anchor, zoomed, left] of [[{page: 3, frac: 0.25}, false, 0], [null, true, 40]]) {
                            DOC = 'pdf-' + layout + '-' + views.length; LAYOUT = layout; MARKDOWN = false;
                            ANCHOR = anchor; ZOOMED = zoomed; LEFT.scrollLeft = left; PAGE_SCALE = 1 + views.length / 10;
                            saveView(); views.push(DOC);
                          }
                        for (const layout of Object.values(LAYOUT_MODE)) {
                          DOC = 'md-' + layout; LAYOUT = layout; MARKDOWN = true; READING = {line: 12, off: 3};
                          saveView(); views.push(DOC);
                        }
                        const written = JSON.stringify([...VIEW_BY.entries()]);
                        VIEW_BY.clear();
                        loadViews();
                        results.views = [views.length, JSON.stringify([...VIEW_BY.entries()]) === written];
                        const sections = [];
                        for (const open of [true, false])
                          for (const review of [true, false])
                            for (const done of [true, false]) {
                              savePrefs({sec: {open, review, done}});
                              sections.push(JSON.stringify(readSectionsExpanded(prefs().sec)) ===
                                JSON.stringify({open, review, done}));
                            }
                        results.sections = sections;
                        results.orders = Object.values(LIST_ORDER).map((order) => {
                          savePrefs({order});
                          return listOrderOf(prefs().order) === order;
                        });
                        const seen = [];
                        for (const [doc, record] of [['a', {ver: 'build:pages-20260101000000', rev: 'abc123'}],
                            ['b', {ver: 'src:1700000000.5', rev: ''}], ['c', {ver: 'build:pages', rev: 'f00d'}]]) {
                          setSeenDoc(doc, record);
                          seen.push(JSON.stringify(seenDoc(doc)) === JSON.stringify(record));
                        }
                        setSeenPin(14);
                        results.seen = [...seen, seenPin() === 14];
                        console.log(JSON.stringify(results));
                        """,
                    ]
                )
            )
        )
        self.assertEqual(got["views"], [9, True])
        self.assertEqual(got["sections"], [True] * 8)
        self.assertEqual(got["orders"], [True] * len(got["orders"]))
        self.assertGreater(len(got["orders"]), 1)
        self.assertEqual(got["seen"], [True] * 4)
