"""The viewer page's elements are what types/page.d.ts says (docs/handbook/viewer.md §타입 검사,
docs/adr/0045-viewer-page-elements.md).

The declaration types $('#id') from index.html with no run-time check: $('#note') is an HTMLTextAreaElement that is
there. These tests are what makes that true:

- the committed declaration is what tools/page_elements.py writes for the page now (a page change without it fails);
- every $('#id') in the modules names an id of PageElements or LiveElements (a typo or a removed id fails);
- every id the modules' markup makes is declared, a live one with the class every module that makes it gives it, a
  page one with the tag index.html gives it (a module that draws a page element anew keeps its tag);
- in the browser, every PageElements id is an element of its class after boot, on each kind of document, after a
  rebuild and after the two redraws that make a page element anew (#c-verdict-l, #queue-h);
- find, findMaybe and findAll (js/platform/dom.ts) give an element only of the class asked for.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_page_elements.py
"""

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

from limn.administration import serve_documents as startup_documents

import helpers_figure
import helpers_js
from helpers import VIEWER, ps
from helpers_browser import BrowserBase, settle

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("page_elements_tool", ROOT / "tools" / "page_elements.py")
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tool
spec.loader.exec_module(tool)

DECLARATION = VIEWER / "types" / "page.d.ts"
MODULES = sorted((VIEWER / "js").rglob("*.ts"))
PAGE = tool.page_elements((VIEWER / "index.html").read_text(encoding="utf-8"))
LIVE = dict(tool.LIVE_ELEMENTS)

# An id as a `#id` selector names it, whole.
PLAIN_ID = re.compile(r"#([A-Za-z][\w-]*)")
# An element with an id in a markup literal: its tag and its id (a computed id, `id="p${n}"`, is not one).
MARKUP_ID = re.compile(r"<([A-Za-z][\w-]*)\b[^<>]*?\bid=\\?\"([A-Za-z][\w-]*)\\?\"")
# An element a module makes with createElement, and an id it gives one: `const box = document.createElement('div');`
# and `box.id = 'md';`.
MADE = re.compile(r"\b(\w+)\s*=\s*document\.createElement\(\s*'([\w-]+)'\s*\)")
GIVEN_ID = re.compile(r"\b(\w+)\.id\s*=\s*'([A-Za-z][\w-]*)'\s*;")


def module_sources() -> dict[str, str]:
    """Every viewer module's code as the build takes it, by path under js/, with each comment blanked to spaces so an
    example in a comment is never read as code."""
    out = {}
    for path, text in zip(MODULES, helpers_js.module_texts(MODULES), strict=True):
        chars = list(text)
        for token in helpers_js.tokenize(text):
            if token.kind in ("comment", "line-comment"):
                chars[token.start : token.end] = " " * (token.end - token.start)
        out[path.relative_to(VIEWER / "js").as_posix()] = "".join(chars)
    return out


def literal_value(token: helpers_js.Token) -> str | None:
    """The text of a string literal, or of a template literal with no substitution; None for anything else."""
    if token.kind == "string":
        return token.text[1:-1]
    if token.kind == "template" and token.text.startswith("`") and token.text.endswith("`") and len(token.text) > 1:
        return token.text[1:-1]
    return None


def id_lookups(sources: dict[str, str]) -> list[tuple[str, str]]:
    """(module, id) for every $('#id') call in the modules: $ called with one literal that is a whole `#id`."""
    out = []
    for name, text in sources.items():
        tokens = helpers_js.code(helpers_js.tokenize(text))
        for k in range(len(tokens) - 3):
            dollar, opening, argument, closing = tokens[k : k + 4]
            if (dollar.kind, dollar.text, opening.text, closing.text) != ("ident", "$", "(", ")"):
                continue
            value = literal_value(argument)
            found = PLAIN_ID.fullmatch(value) if value is not None else None
            if found:
                out.append((name, found[1]))
    return out


def made_ids(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    """(module, id, DOM class) for every element with a literal id the modules make: in a markup literal, or made by
    createElement and given the id by an assignment later in the same module."""
    out = []
    for name, text in sources.items():
        for token in helpers_js.tokenize(text):
            if token.kind in ("string", "template"):
                out += [(name, found[2], tool.tag_class(found[1].lower())) for found in MARKUP_ID.finditer(token.text)]
        for given in GIVEN_ID.finditer(text):
            made = [m for m in MADE.finditer(text, 0, given.start()) if m[1] == given[1]]
            if made:
                out.append((name, given[2], tool.tag_class(made[-1][2].lower())))
    return out


def fits(made: str, declared: str) -> bool:
    """Whether an element of class made is of the declared class: the same, or a supertype the generator uses."""
    return made == declared or declared == "Element" or (declared == "HTMLElement" and made.startswith("HTML"))


class GeneratedDeclaration(unittest.TestCase):
    """types/page.d.ts is the generator's output for the page as committed."""

    def test_the_committed_declaration_is_what_the_page_gives_now(self):
        """A page that gained, lost or retagged an id without `uv run python tools/page_elements.py` fails here."""
        self.assertEqual(
            DECLARATION.read_text(encoding="utf-8"),
            tool.declaration(PAGE, LIVE),
            "types/page.d.ts is stale: run uv run python tools/page_elements.py",
        )


class Lookups(unittest.TestCase):
    """Every $('#id') in the modules names an id the declaration has."""

    def test_every_id_looked_up_is_a_page_or_live_element(self):
        """An id in neither table would be typed Element | null by the catch-all; it is a typo or a removed element."""
        lookups = id_lookups(module_sources())
        self.assertGreater(len(lookups), 500)  # the scan reads the modules' calls at all
        missing = sorted({"%s: #%s" % found for found in lookups if found[1] not in PAGE and found[1] not in LIVE})
        self.assertEqual(missing, [])

    def test_a_lookup_of_an_undeclared_id_is_found(self):
        """The scan sees a string, a double-quoted and a plain template literal, and passes over a computed one and a
        selector that is more than one id."""
        source = {
            "x.ts": "$('#nope'); $(\"#nada\"); $(`#zip`); $(`#${name}`); $('#doc .pg'); $$('#also');",
        }
        self.assertEqual(id_lookups(source), [("x.ts", "nope"), ("x.ts", "nada"), ("x.ts", "zip")])


class LiveMarkup(unittest.TestCase):
    """The ids the modules' markup makes and what the declaration says of them."""

    @classmethod
    def setUpClass(cls):
        """The modules' made ids, read once."""
        cls.made = made_ids(module_sources())

    def test_every_live_id_is_made_by_a_module_with_its_class(self):
        """Each LiveElements id is made somewhere, and every element made with it is of the declared class (#md is an
        article or a div: HTMLElement)."""
        for live, declared in LIVE.items():
            with self.subTest(id=live):
                classes = sorted({made for _, found, made in self.made if found == live})
                self.assertTrue(classes, "no module makes #%s" % live)
                self.assertEqual([made for made in classes if not fits(made, declared)], [], declared)

    def test_every_id_a_module_makes_is_declared_and_a_page_id_keeps_its_tag(self):
        """A made id in neither table could not be looked up typed; a page id drawn anew (#c-verdict-l, #queue-h)
        keeps the tag index.html gives it, so its class holds after the redraw."""
        undeclared = sorted({"%s: #%s" % (name, found) for name, found, _ in self.made if found not in PAGE | LIVE})
        self.assertEqual(undeclared, [])
        retagged = sorted(
            "%s: #%s is a %s, index.html's a %s" % (name, found, made, PAGE[found])
            for name, found, made in self.made
            if found in PAGE and made != PAGE[found]
        )
        self.assertEqual(retagged, [])
        redrawn = {found for _, found, _ in self.made if found in PAGE}
        self.assertTrue({"c-verdict-l", "queue-h"} <= redrawn, redrawn)

    def test_markup_and_created_elements_are_both_read(self):
        """The scan reads an id in a markup literal (escaped quotes too) and one given to an element createElement made,
        and passes over a computed id."""
        source = {
            "x.ts": (
                'html`<span class="a" id="one">x</span><b id="p${n}"></b>`;\n'
                "const s = '<input id=\\\"two\\\">';\n"
                "const box = document.createElement('article');\nbox.className = 'md';\nbox.id = 'three';\n"
                "pageBox.id = 'p' + 1;\n"
            )
        }
        self.assertEqual(
            sorted(made_ids(source)),
            [("x.ts", "one", "HTMLSpanElement"), ("x.ts", "three", "HTMLElement"), ("x.ts", "two", "HTMLInputElement")],
        )


# Every PageElements id that $ would not find as an element of its class now, with what it found instead.
ABSENT = """table => Object.entries(table).flatMap(([id, name]) => {
  const found = document.querySelector('#' + id);
  return found instanceof window[name] ? [] : [id + ': ' + (found ? found.tagName : 'missing') + ', not ' + name];
})"""
# Verdict words for the LaTeX document, so the composer draws its verdict row (#c-verdict-l).
WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}], "page": False}
# The condition each kind of document is drawn on: its pages, or its Markdown or text surface.
DRAWN = {
    "pages": "!!document.querySelector('#doc .pg')",
    "lines": "typeof MARKDOWN_VIEW!=='undefined'&&MARKDOWN_VIEW.shown===DOC&&!!document.querySelector('#md')",
}


class PagePresence(BrowserBase):
    """The real viewer with one document of each kind - the LaTeX manuscript (ms), a figure (fig), a view-only PDF (rv),
    a Markdown document (nt) and a text file (tx) - and verdict words on the manuscript."""

    def setUp(self):
        """The five documents, each drawn from a build or its source."""
        super().setUp()
        src = ps.APP.C.src
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, src)
        (src / "notes.md").write_text("# Notes\n\nA paragraph.\n", encoding="utf-8")
        (src / "check.py").write_text("def check():\n    return 1\n", encoding="utf-8")
        lines = startup_documents.make_docs(["nt=노트:notes.md", "tx=코드:check.py"], src, ps.APP.C.paths)
        assert isinstance(lines, list), lines
        ps.APP.set_docs([self.ms, self.fig, self.rv, *lines])
        self.addCleanup(ps.APP.set_docs, None)
        (src / "main.limnverdicts.json").write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")

    def assert_present(self, page, state):
        """Every PageElements id is an element of its class on the page now; state names the moment."""
        self.assertEqual(page.evaluate(ABSENT, PAGE), [], state)

    def show(self, page, key, drawn):
        """Switch to document key and wait until it is drawn (DRAWN[drawn]) and the page has settled."""
        page.evaluate("k=>switchDoc(k)", key)
        page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&(%s)" % DRAWN[drawn], arg=key, timeout=20000)
        settle(page)

    def test_after_boot_and_on_each_kind_of_document(self):
        """Boot on the manuscript's pages, then the Markdown, text, figure and view-only PDF documents, and back."""
        page = self.open(0)
        page.wait_for_function(DRAWN["pages"], timeout=20000)
        self.assert_present(page, "after boot on the LaTeX manuscript")
        for key, drawn in (("nt", "lines"), ("tx", "lines"), ("fig", "pages"), ("rv", "pages"), ("ms", "pages")):
            self.show(page, key, drawn)
            self.assert_present(page, "on document %s" % key)

    def test_after_a_rebuild(self):
        """A new build of the manuscript taken as the poll takes it (refreshDoc): the pages are drawn anew."""
        page = self.open(0)
        page.wait_for_function(DRAWN["pages"], timeout=20000)
        helpers_figure.viewer_build(self.ms, helpers_figure.BUILD2)
        page.evaluate("async()=>await refreshDoc()")
        page.wait_for_function("b=>META.pages_build===b", arg=helpers_figure.BUILD2, timeout=8000)
        settle(page)
        self.assert_present(page, "after the rebuild")

    def test_after_the_composers_verdict_row_is_drawn_anew(self):
        """A selection opens the composer, whose verdict row (renderVerdictRow) makes #c-verdict-l again."""
        page = self.open(0)
        page.evaluate("window.__lead = document.querySelector('#c-verdict-l')")
        self.open_composer(page)
        settle(page)
        self.assertTrue(page.evaluate("document.querySelector('#c-verdict-l') !== window.__lead"))
        self.assert_present(page, "after the verdict row is drawn")

    def test_after_the_queues_heading_is_drawn_anew(self):
        """A queued pin draws the panel's queue section (offlineUiSync), whose toggle makes #queue-h again."""
        page = self.open(0)
        page.evaluate("window.__heading = document.querySelector('#queue-h')")
        page.evaluate("offlineUiSync([{page: 1, frac: [0.2, 0.2, 0.5, 0.05], note: 'n'}])")
        self.assertTrue(page.evaluate("document.querySelector('#queue-h') !== window.__heading"))
        self.assert_present(page, "after the queue heading is drawn")


class Finding(BrowserBase):
    """find, findMaybe and findAll on the real page: an element of the class asked for, or none."""

    # What a call gives: the element it found ('same' when it is the one querySelector finds), null, or the message of
    # the Error it threw.
    CALL = """([helper, selector, name]) => {
      try {
        const found = window[helper](document, selector, window[name]);
        return found === null ? null : found === document.querySelector(selector) ? 'same' : 'other';
      } catch (error) {
        return error instanceof Error ? error.message : 'not an Error';
      }
    }"""

    def call(self, page, helper, selector, name):
        """What helper(document, selector, window[name]) gives on page (CALL)."""
        return page.evaluate(self.CALL, [helper, selector, name])

    def test_find_gives_the_element_of_its_class_and_else_throws_naming_the_selector(self):
        """The composer's location line is a div: find gives it as an HTMLElement or an HTMLDivElement; as an input it
        throws saying what it is, and for no match it throws saying there is none."""
        page = self.open(0)
        self.assertEqual(self.call(page, "find", "#composer .c-loc-row", "HTMLElement"), "same")
        self.assertEqual(self.call(page, "find", "#composer .c-loc-row", "HTMLDivElement"), "same")
        self.assertEqual(
            self.call(page, "find", "#composer .c-loc-row", "HTMLInputElement"),
            "#composer .c-loc-row: a DIV, not a HTMLInputElement",
        )
        self.assertEqual(
            self.call(page, "find", "#composer .no-such", "HTMLElement"), "#composer .no-such: no HTMLElement"
        )

    def test_find_maybe_gives_null_for_no_match_and_for_another_class(self):
        """findMaybe gives the element of its class, and null where find would throw."""
        page = self.open(0)
        self.assertEqual(self.call(page, "findMaybe", "#composer .c-loc-row", "HTMLElement"), "same")
        self.assertIsNone(self.call(page, "findMaybe", "#composer .c-loc-row", "HTMLInputElement"))
        self.assertIsNone(self.call(page, "findMaybe", "#composer .no-such", "HTMLElement"))

    def test_find_all_gives_only_the_matches_of_its_class_in_document_order(self):
        """Under a box holding a span, an SVG element and a div that all match: HTMLElement gives the span and the div,
        in order; SVGElement the svg alone; HTMLInputElement nothing. The scope bounds the search."""
        page = self.open(0)
        got = page.evaluate(
            """() => {
              const box = document.createElement('div'), outside = document.createElement('p');
              for (const made of [document.createElement('span'),
                  document.createElementNS('http://www.w3.org/2000/svg', 'svg'), document.createElement('div')]) {
                made.classList.add('hit');
                box.append(made);
              }
              outside.classList.add('hit');
              document.body.append(box, outside);
              const names = (found) => found.map((element) => element.tagName.toLowerCase());
              const out = [names(findAll(box, '.hit', HTMLElement)), names(findAll(box, '.hit', SVGElement)),
                names(findAll(box, '.hit', HTMLInputElement))];
              box.remove();
              outside.remove();
              return out;
            }"""
        )
        self.assertEqual(got, [["span", "div"], ["svg"], []])


if __name__ == "__main__":
    unittest.main()
