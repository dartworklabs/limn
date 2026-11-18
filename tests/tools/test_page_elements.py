"""tools/page_elements.py - the declaration of the viewer page's elements, checked on small made-up pages.

The declaration types $('#id') with no run-time check, so a generator that let a duplicate id through, gave a tag the
wrong class, or counted an element the document never holds would make the viewer's types lie. These tests feed it
pages directly and read what it declares.

Run: uv run pytest -q tests/tools/test_page_elements.py
"""

import importlib.util
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("page_elements_tool", ROOT / "tools" / "page_elements.py")
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tool
spec.loader.exec_module(tool)


class Ids(unittest.TestCase):
    """Which ids the page gives, and which it is refused for."""

    def test_every_id_of_the_body_and_head_is_found_with_its_tag_class(self):
        """Ids anywhere in the page, void and self-closed elements included, each with its tag's class."""
        page = (
            '<html><head><title id="t">x</title></head><body><div id="a"><input id="b"><br id="c"/>'
            '<span id="d">x</span></div><textarea id="e"></textarea></body></html>'
        )
        self.assertEqual(
            tool.page_elements(page),
            {
                "t": "HTMLTitleElement",
                "a": "HTMLDivElement",
                "b": "HTMLInputElement",
                "c": "HTMLBRElement",
                "d": "HTMLSpanElement",
                "e": "HTMLTextAreaElement",
            },
        )

    def test_an_id_given_twice_is_refused_with_both_lines(self):
        """Two elements with one id: $ finds only the first and one entry cannot say both tags."""
        with self.assertRaises(tool.PageError) as caught:
            tool.page_elements('<div id="a"></div>\n<span id="a"></span>')
        self.assertIn("'a'", str(caught.exception))
        self.assertIn("lines 1 and 2", str(caught.exception))

    def test_an_id_a_selector_cannot_say_as_written_is_refused(self):
        """An id starting with a digit or holding a space or a dot needs escaping in '#id'."""
        for bad in ("1a", "a b", "a.b", "a:b"):
            with self.subTest(bad=bad), self.assertRaises(tool.PageError):
                tool.page_elements('<div id="%s"></div>' % bad)

    def test_an_empty_id_and_an_element_without_one_are_not_declared(self):
        """`id=""` and a bare `id` name no element."""
        self.assertEqual(tool.page_elements('<div id=""></div><p id></p><b class="x"></b>'), {})

    def test_template_and_noscript_contents_are_not_the_documents(self):
        """What a template (nested ones included) or noscript holds is not in the document the script sees; the
        template element itself and what follows it are."""
        page = (
            '<template id="tpl"><div id="in"><template><span id="deep"></span></template>'
            '<p id="after-inner"></p></div></template><noscript><img id="ns"></noscript><div id="out"></div>'
        )
        self.assertEqual(tool.page_elements(page), {"tpl": "HTMLTemplateElement", "out": "HTMLDivElement"})


class Classes(unittest.TestCase):
    """The class each tag is declared with is true of the element the browser makes."""

    def test_tags_with_their_own_interface_get_it(self):
        """Headings share one class, as do table sections; the rest are the HTML standard's interfaces."""
        for tag, kind in (
            ("h2", "HTMLHeadingElement"),
            ("h6", "HTMLHeadingElement"),
            ("dialog", "HTMLDialogElement"),
            ("details", "HTMLDetailsElement"),
            ("output", "HTMLOutputElement"),
            ("tbody", "HTMLTableSectionElement"),
            ("select", "HTMLSelectElement"),
        ):
            with self.subTest(tag=tag):
                self.assertEqual(tool.tag_class(tag), kind)

    def test_a_tag_with_no_interface_an_unknown_tag_and_a_custom_element_are_html_elements(self):
        """section, b and nav have no interface of their own; an unknown tag is an HTMLUnknownElement and a custom
        element an HTMLElement (or a subclass) - HTMLElement is true of all."""
        page = '<section id="s"></section><b id="b"></b><blink id="u"></blink><x-panel id="c"></x-panel>'
        self.assertEqual(set(tool.page_elements(page).values()), {"HTMLElement"})

    def test_svg_and_mathml_elements_are_declared_as_such(self):
        """An svg root, an element inside it, a math root and its child; HTML back under foreignObject is only an
        Element; after the svg closes, HTML classes again."""
        page = (
            '<svg id="root"><g id="g"><path id="p"/></g><foreignObject><div id="fo"></div></foreignObject></svg>'
            '<math id="m"><mi id="mi">x</mi></math><div id="html"></div>'
        )
        self.assertEqual(
            tool.page_elements(page),
            {
                "root": "SVGSVGElement",
                "g": "SVGElement",
                "p": "SVGElement",
                "fo": "Element",
                "m": "MathMLElement",
                "mi": "MathMLElement",
                "html": "HTMLDivElement",
            },
        )


class Declaration(unittest.TestCase):
    """The text written, and the command that writes and checks it."""

    def test_the_text_is_sorted_and_the_same_whatever_order_the_tables_come_in(self):
        """Same tables, either order: the same bytes; each table lists its ids in sorted order."""
        one = tool.declaration({"b": "HTMLDivElement", "a": "HTMLSpanElement"}, {"z": "HTMLElement"})
        two = tool.declaration({"a": "HTMLSpanElement", "b": "HTMLDivElement"}, {"z": "HTMLElement"})
        self.assertEqual(one, two)
        self.assertLess(one.index("'a': HTMLSpanElement;"), one.index("'b': HTMLDivElement;"))
        self.assertIn("interface LiveElements {\n  'z': HTMLElement;\n}", one)
        self.assertIn("<Id extends keyof PageElements>(selector: `#${Id}`): PageElements[Id];", one)
        self.assertIn("<Id extends keyof LiveElements>(selector: `#${Id}`): LiveElements[Id] | null;", one)

    def test_an_id_in_both_tables_is_refused(self):
        """A live id the page also gives would be hidden by the page's own overload."""
        with self.assertRaises(tool.PageError):
            tool.declaration({"md": "HTMLDivElement"}, {"md": "HTMLElement"})

    def test_the_live_table_holds_no_id_of_the_page(self):
        """LIVE_ELEMENTS and index.html share no id, so the committed declaration can be written."""
        page = tool.page_elements(tool.INDEX.read_text(encoding="utf-8"))
        self.assertEqual(sorted(set(page) & set(tool.LIVE_ELEMENTS)), [])

    def test_check_passes_on_what_it_wrote_and_fails_on_a_stale_or_missing_file(self):
        """main writes the file; --check is 0 on it, 1 after the page gains an id or with no file, 1 for a refused
        page, 2 for an unknown argument."""
        with tempfile.TemporaryDirectory() as folder:
            index, out = Path(folder) / "index.html", Path(folder) / "page.d.ts"
            index.write_text('<div id="a"></div>', encoding="utf-8")
            quiet = StringIO()
            with redirect_stderr(quiet):
                self.assertEqual(tool.main(["--check"], index, out), 1)  # no file yet
                self.assertEqual(tool.main([], index, out), 0)
                self.assertEqual(tool.main(["--check"], index, out), 0)
                index.write_text('<div id="a"></div><p id="b"></p>', encoding="utf-8")
                self.assertEqual(tool.main(["--check"], index, out), 1)
                index.write_text('<div id="a"></div><p id="a"></p>', encoding="utf-8")
                self.assertEqual(tool.main([], index, out), 1)
                self.assertEqual(tool.main(["--write"], index, out), 2)
            self.assertIn("'a': HTMLDivElement;", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
