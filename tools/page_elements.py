"""Declare the viewer page's elements for TypeScript: write src/limn/viewer/types/page.d.ts from the page itself,
src/limn/viewer/index.html (docs/handbook/viewer.md §타입 검사, docs/adr/0045-viewer-page-elements.md).

The viewer looks its elements up with $('#id') (js/platform/dom.ts). The page is one static HTML file and the script is
its body's last child, so every element index.html gives an id exists, with that tag, before any module runs. This
tool reads those ids and tags and writes three declarations:

  PageElements  every id index.html gives an element, with the DOM class of its tag ('note': HTMLTextAreaElement)
  LiveElements  the ids viewer markup gives an element at run time, present only in some states (LIVE_ELEMENTS below)
  PageLookup    the type of $: a page element's id gives its class, a live one's its class or null, any other selector
                Element | null

Nothing checks these at run time. What makes them true is tested: the file equals this tool's output for the page
(test_viewer_page_elements.GeneratedDeclaration), every $('#id') in the modules names an id of the two tables, every
live id is made by a module's markup with its tag, and in the browser every page id is its class after boot, after a
switch to each kind of document, after a rebuild and after the two redraws that make a page id anew
(test_viewer_page_elements).

A page that gives two elements one id is refused: $ would find the first, and the table could say only one tag. So is
an id a `#id` selector cannot name without escaping. An element inside <template> or <noscript> is not in the document
the script sees, so its id is left out; one inside <svg> or <math> is an SVG or MathML element, and declared so.

Usage:
  uv run python tools/page_elements.py           write the declaration
  uv run python tools/page_elements.py --check   exit 1 when the committed declaration is not what the page gives
Standard library only.
"""

import re
import sys
from collections.abc import Mapping, Sequence
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "limn" / "viewer" / "index.html"
DECLARATION = ROOT / "src" / "limn" / "viewer" / "types" / "page.d.ts"

# The DOM class of each HTML tag that has its own (the HTML standard's element interfaces). Every other tag - one with
# no interface of its own (section, b, nav), an unknown one (HTMLUnknownElement) or a custom element - is an
# HTMLElement, which is true of all of them.
TAG_CLASSES: Mapping[str, str] = {
    "a": "HTMLAnchorElement",
    "area": "HTMLAreaElement",
    "audio": "HTMLAudioElement",
    "base": "HTMLBaseElement",
    "blockquote": "HTMLQuoteElement",
    "body": "HTMLBodyElement",
    "br": "HTMLBRElement",
    "button": "HTMLButtonElement",
    "canvas": "HTMLCanvasElement",
    "caption": "HTMLTableCaptionElement",
    "col": "HTMLTableColElement",
    "colgroup": "HTMLTableColElement",
    "data": "HTMLDataElement",
    "datalist": "HTMLDataListElement",
    "del": "HTMLModElement",
    "details": "HTMLDetailsElement",
    "dialog": "HTMLDialogElement",
    "div": "HTMLDivElement",
    "dl": "HTMLDListElement",
    "embed": "HTMLEmbedElement",
    "fieldset": "HTMLFieldSetElement",
    "form": "HTMLFormElement",
    "h1": "HTMLHeadingElement",
    "h2": "HTMLHeadingElement",
    "h3": "HTMLHeadingElement",
    "h4": "HTMLHeadingElement",
    "h5": "HTMLHeadingElement",
    "h6": "HTMLHeadingElement",
    "head": "HTMLHeadElement",
    "hr": "HTMLHRElement",
    "html": "HTMLHtmlElement",
    "iframe": "HTMLIFrameElement",
    "img": "HTMLImageElement",
    "input": "HTMLInputElement",
    "ins": "HTMLModElement",
    "label": "HTMLLabelElement",
    "legend": "HTMLLegendElement",
    "li": "HTMLLIElement",
    "link": "HTMLLinkElement",
    "map": "HTMLMapElement",
    "menu": "HTMLMenuElement",
    "meta": "HTMLMetaElement",
    "meter": "HTMLMeterElement",
    "object": "HTMLObjectElement",
    "ol": "HTMLOListElement",
    "optgroup": "HTMLOptGroupElement",
    "option": "HTMLOptionElement",
    "output": "HTMLOutputElement",
    "p": "HTMLParagraphElement",
    "picture": "HTMLPictureElement",
    "pre": "HTMLPreElement",
    "progress": "HTMLProgressElement",
    "q": "HTMLQuoteElement",
    "script": "HTMLScriptElement",
    "select": "HTMLSelectElement",
    "slot": "HTMLSlotElement",
    "source": "HTMLSourceElement",
    "span": "HTMLSpanElement",
    "style": "HTMLStyleElement",
    "table": "HTMLTableElement",
    "tbody": "HTMLTableSectionElement",
    "td": "HTMLTableCellElement",
    "template": "HTMLTemplateElement",
    "textarea": "HTMLTextAreaElement",
    "tfoot": "HTMLTableSectionElement",
    "th": "HTMLTableCellElement",
    "thead": "HTMLTableSectionElement",
    "time": "HTMLTimeElement",
    "title": "HTMLTitleElement",
    "tr": "HTMLTableRowElement",
    "track": "HTMLTrackElement",
    "ul": "HTMLUListElement",
    "video": "HTMLVideoElement",
}

# The ids viewer markup gives an element at run time - present only in some states, so $ gives them or null - with the
# DOM class every module that makes one gives it (test_viewer_page_elements.LiveMarkup finds each in a module's
# markup). An id index.html gives an element belongs to PageElements even when a module draws it anew.
LIVE_ELEMENTS: Mapping[str, str] = {
    "acc-login": "HTMLInputElement",  # the access dialog's field for a login the tailnet list does not show (access/view.ts)
    "access-body": "HTMLDivElement",  # the owner's access dialog, drawn for an owner only (access/view.ts)
    "access-h": "HTMLHeadingElement",  # the access dialog's heading (access/view.ts)
    "c-verdict-why": "HTMLSpanElement",  # the composer's verdict row, while a verdict cannot be saved (verdict/flow-line.ts)
    "m-access": "HTMLButtonElement",  # the owner's [접근 관리] entry in [더보기] (access/view.ts)
    "m-access-n": "HTMLSpanElement",  # how many members it counts (access/view.ts)
    "md": "HTMLElement",  # a Markdown or text document, its line view (article) or its notice (div) (markdown/, text/)
    "pv-panel": "HTMLDivElement",  # the verdict panel beside the pages (verdict/view-panel.ts)
    "pv-panel-at": "HTMLDivElement",  # where the verdict panel stands (verdict/view-panel.ts)
    "revision-more": "HTMLButtonElement",  # the changes view's [more commits] (revisions/flow.ts)
    "rv-all": "HTMLInputElement",  # the review pick's tick-all box (pins/flow-review-pick.ts)
    "rv-go": "HTMLButtonElement",  # the review pick's confirm button (pins/flow-review-pick.ts)
}

# An id a `#id` selector names as written (CSS identifiers without escapes, as the viewer writes them).
PLAIN_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
# Tags whose content is not elements of the document the script sees.
INERT = frozenset(["template", "noscript"])
# The foreign roots and the class of an element inside them (the root itself: SVGSVGElement, MathMLElement).
FOREIGN = {"svg": "SVGElement", "math": "MathMLElement"}


class PageError(ValueError):
    """The page gives an id the declaration cannot say truly: one id on two elements, or an id that needs escaping."""


def tag_class(tag: str) -> str:
    """The DOM class of an HTML element with tag (lower case): its own interface, else HTMLElement."""
    return TAG_CLASSES.get(tag, "HTMLElement")


class _Ids(HTMLParser):
    """Collects (id, DOM class, line) for every element with an id in the document the page's script sees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str, int]] = []
        self.inert = 0  # how many <template>/<noscript> are open
        self.foreign: list[str] = []  # the open tags from an <svg> or <math> root inward

    def _element_class(self, tag: str) -> str:
        """The DOM class of an element with tag opened where the parser is now."""
        if not self.foreign:
            if tag == "svg":
                return "SVGSVGElement"
            return "MathMLElement" if tag == "math" else tag_class(tag)
        if "foreignobject" in self.foreign:
            return "Element"  # back in HTML under an SVG foreignObject: Element is true whatever the tag
        return FOREIGN[self.foreign[0]]

    def _open(self, tag: str, attrs: list[tuple[str, str | None]], closes: bool) -> None:
        """Record the element's id when it has one and is in the document; track the inert and foreign parts."""
        found = [value for name, value in attrs if name == "id"]
        if found and found[0] and not self.inert:
            self.found.append((found[0], self._element_class(tag), self.getpos()[0]))
        if closes:
            return
        if tag in INERT:
            self.inert += 1
        elif self.foreign or tag in FOREIGN:
            self.foreign.append(tag)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """An opening tag: in the foreign part it opens an element until its end tag (void HTML tags are not foreign)."""
        self._open(tag, attrs, closes=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """A self-closing tag (`<path/>`): an element with no content."""
        self._open(tag, attrs, closes=True)

    def handle_endtag(self, tag: str) -> None:
        """A closing tag: ends the inert part it opened, or the foreign elements up to it."""
        if tag in INERT and self.inert:
            self.inert -= 1
        elif tag in self.foreign:
            while self.foreign and self.foreign.pop() != tag:
                pass


def page_elements(page: str) -> dict[str, str]:
    """Every id the page's markup gives an element of the document, with that element's DOM class. Raises PageError
    for an id given twice or one a `#id` selector cannot name as written."""
    parser = _Ids()
    parser.feed(page)
    parser.close()
    out: dict[str, str] = {}
    lines: dict[str, int] = {}
    for found, kind, line in parser.found:
        if not PLAIN_ID.fullmatch(found):
            raise PageError("line %d: id %r is not a plain name a #id selector can say" % (line, found))
        if found in out:
            raise PageError(
                "id %r is given twice (lines %d and %d): $ finds only the first" % (found, lines[found], line)
            )
        out[found] = kind
        lines[found] = line
    return out


def _table(name: str, comment: Sequence[str], entries: Mapping[str, str]) -> list[str]:
    """One interface of the declaration: its comment lines, then one property per id in sorted order."""
    return (
        [*("// " + line for line in comment), "interface %s {" % name]
        + ["  '%s': %s;" % (key, entries[key]) for key in sorted(entries)]
        + ["}"]
    )


def declaration(page: Mapping[str, str], live: Mapping[str, str]) -> str:
    """The text of types/page.d.ts for the page's ids (page_elements) and the live ones: the same text for the same
    tables, whatever their order. Raises PageError for an id in both - the page's own would hide the other."""
    both = sorted(set(page) & set(live))
    if both:
        raise PageError("ids both in index.html and in LIVE_ELEMENTS: %s" % ", ".join(both))
    lines = [
        "// Generated by tools/page_elements.py from src/limn/viewer/index.html - do not edit: change the page (or the",
        "// tool's LIVE_ELEMENTS) and run `uv run python tools/page_elements.py`. docs/handbook/viewer.md §타입 검사,",
        "// docs/adr/0045-viewer-page-elements.md.",
        "",
        *_table(
            "PageElements",
            [
                "The page's fixed elements by id, with the DOM class of the tag index.html gives each. The script is the",
                "body's last child, so each is there before any module runs, and none is removed; a module that draws one",
                "anew gives it the same id and tag. Nothing checks this at run time: test_viewer_page_elements does.",
            ],
            page,
        ),
        "",
        *_table(
            "LiveElements",
            [
                "Elements viewer markup makes at run time, present only in some states, by id, with the class every",
                "module that makes one gives it.",
            ],
            live,
        ),
        "",
        "// $ of js/platform/dom.ts: a fixed element by its id is its own class and present; a live one may be missing;",
        "// any other selector may match nothing or an element of any kind.",
        "interface PageLookup {",
        "  <Id extends keyof PageElements>(selector: `#${Id}`): PageElements[Id];",
        "  <Id extends keyof LiveElements>(selector: `#${Id}`): LiveElements[Id] | null;",
        "  (selector: string): Element | null;",
        "}",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str], index: Path = INDEX, out: Path = DECLARATION) -> int:
    """Write out from index (or with --check, compare them); 0 when it is written or equal, 1 when stale or refused,
    2 for an unknown argument."""
    if any(arg != "--check" for arg in argv):
        print("usage: page_elements.py [--check]", file=sys.stderr)
        return 2
    try:
        text = declaration(page_elements(index.read_text(encoding="utf-8")), LIVE_ELEMENTS)
    except PageError as e:
        print("%s: %s" % (index, e), file=sys.stderr)
        return 1
    if "--check" in argv:
        if out.is_file() and out.read_text(encoding="utf-8") == text:
            return 0
        print("%s is not what %s gives: run uv run python tools/page_elements.py" % (out, index), file=sys.stderr)
        return 1
    out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
