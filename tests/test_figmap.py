"""limn.figmap - the element map a figure repository writes (limn-figure-map/1), parsed once at the boundary.

The module is pure, so these tests hand it bytes and a path check and look only at the values it returns (coding rule
R9). Every rejection reason has examples that break exactly that rule. The accepted edges are pinned too: unknown keys,
elements drawn without code (ADR-0011 D7), a root listed last, rounding at the page edge, each bound a pin relies on
(path length, line number, depth) at its limit, a file exactly at the size cap. Hypothesis checks that parse_map never raises, whatever bytes or JSON
it gets, and that every map it accepts is one tree per page rooted at the page's figure.

Run: uv run pytest -q tests/test_figmap.py
"""

import ast
import copy
import json
import unittest
from collections.abc import Callable
from pathlib import Path

from hypothesis import given, strategies as st

from limn import figmap
from limn.figmap import (
    FULL_PAGE,
    MAP_FORMAT,
    MAP_MAX_BYTES,
    MAP_MAX_DEPTH,
    MAP_MAX_ELEMENTS,
    MAP_MAX_LINE,
    MAP_MAX_PATH,
    MAP_MAX_TEXT,
    FigureMap,
    MapElement,
    MapRejected,
    SourceRef,
    parse_map,
)

from helpers import MINI_PDF, figure_map, map_bytes

FIGMAP_PY = Path(figmap.__file__)
PURE_IMPORTS = {"__future__", "json", "collections.abc", "dataclasses", "typing", "limn.pins.shapes"}


def anywhere(path: str) -> bool:
    """A source check that accepts every path: the rules under test are the map's own."""
    return True


def parse(m: dict, source_inside: Callable[[str], bool] = anywhere) -> FigureMap | MapRejected:
    """parse_map of the bytes a producer writes for map m."""
    return parse_map(map_bytes(m), source_inside=source_inside)


def page0(m: dict) -> dict:
    """The first page object of map m."""
    return m["pages"][0]


def elements0(m: dict) -> list:
    """The element list of map m's first page."""
    return m["pages"][0]["elements"]


def changed(change: Callable[[dict], object]) -> dict:
    """The design's example map (helpers.figure_map) after change(m) has edited it in place."""
    m = figure_map(MINI_PDF)
    change(m)
    return m


def second_page(figure: str, *elements: dict, number: int = 2) -> Callable[[dict], object]:
    """A change that appends page `number`, whose figure is `figure`, with these elements."""
    return lambda m: m["pages"].append({"page": number, "figure": figure, "elements": list(elements)})


ROOT_ONLY = {"id": "C1", "frac": [0, 0, 1, 1]}


def path_of(length: int, suffix: str) -> str:
    """A canonical relative path of exactly length characters (at least len(suffix) + 3) ending in suffix."""
    return "d/" + "x" * (length - 2 - len(suffix)) + suffix


def chain_of(depth: int) -> list[dict]:
    """A first page's elements as one parent chain: root B2 and depth - 1 descendants, each the child of the one
    before, so the last one is depth ids from the root, both counted."""
    return [{"id": "B2", "frac": [0, 0, 1, 1]}] + [
        {"id": "B2/%d" % i, "parent": "B2" if i == 0 else "B2/%d" % (i - 1), "frac": [0, 0, 1, 1]}
        for i in range(depth - 1)
    ]


# Source paths that are not canonical relative POSIX paths, which a pin could not store: path_outside before the
# document's folder is ever asked (index §Shared contract: canonical paths).
NOT_CANONICAL = {
    "absolute": "/src/B2_calendar.py",
    "climbing out": "../src/B2_calendar.py",
    "climbing out and back in": "src/../src/B2_calendar.py",
    "a . part": "./src/B2_calendar.py",
    "an empty part": "src//B2_calendar.py",
    "a trailing /": "src/",
    "a backslash": "src\\B2_calendar.py",
    "a NUL": "src/B2\x00.py",
}


def put_figure(m: dict, text: str) -> None:
    """Rename the first page's figure to text, and its root (and the root's child) with it, so the page stays rooted."""
    page0(m)["figure"] = text
    elements0(m)[0]["id"] = text
    elements0(m)[1]["parent"] = text


# The five names a pin stores, each with a change that sets it to a given text (index §Shared contract: MAP_MAX_TEXT).
# The id is the July cell's: a leaf, so no parent refers to it.
TEXT_FIELDS: dict[str, Callable[[dict, str], object]] = {
    "figure": put_figure,
    "title": lambda m, text: page0(m).update(title=text),
    "id": lambda m, text: elements0(m)[2].update(id=text),
    "part": lambda m, text: elements0(m)[2].update(part=text),
    "label": lambda m, text: elements0(m)[2].update(label=text),
}

# (what breaks, the change to the example map, the reason parse_map names)
REJECTIONS = [
    ("format missing", lambda m: m.pop("format"), "bad_format"),
    ("format of a later version", lambda m: m.update(format="limn-figure-map/2"), "bad_format"),
    ("pdf empty", lambda m: m.update(pdf=""), "bad_shape"),
    ("pdf not a string", lambda m: m.update(pdf=["figures.pdf"]), "bad_shape"),
    ("pdf_sha256 in upper case", lambda m: m.update(pdf_sha256=m["pdf_sha256"].upper()), "bad_shape"),
    ("pdf_sha256 one digit short", lambda m: m.update(pdf_sha256=m["pdf_sha256"][:63]), "bad_shape"),
    ("pages an object", lambda m: m.update(pages={}), "bad_shape"),
    ("a page that is a list", lambda m: m["pages"].append([]), "bad_shape"),
    ("figure empty", lambda m: page0(m).update(figure=""), "bad_shape"),
    ("title a number", lambda m: page0(m).update(title=7), "bad_shape"),
    ("elements an object", lambda m: page0(m).update(elements={}), "bad_shape"),
    ("an element that is a string", lambda m: elements0(m).append("B2/x"), "bad_shape"),
    ("id empty", lambda m: elements0(m)[1].update(id=""), "bad_shape"),
    ("id with a lone surrogate", lambda m: elements0(m)[1].update(id="B2/\ud800"), "bad_shape"),
    ("parent a number", lambda m: elements0(m)[1].update(parent=1), "bad_shape"),
    ("src a string", lambda m: elements0(m)[1].update(src="src/B2_calendar.py"), "bad_shape"),
    ("src file empty", lambda m: elements0(m)[1]["src"].update(file=""), "bad_shape"),
    ("lo a boolean", lambda m: elements0(m)[1]["src"].update(lo=True), "bad_shape"),
    ("lo zero", lambda m: elements0(m)[1]["src"].update(lo=0), "bad_shape"),
    ("lo after hi", lambda m: elements0(m)[1]["src"].update(lo=98, hi=97), "bad_shape"),
    ("impl without hi", lambda m: elements0(m)[2]["impl"].pop("hi"), "bad_shape"),
    ("part a number", lambda m: elements0(m)[1].update(part=3), "bad_shape"),
    ("label a list", lambda m: elements0(m)[1].update(label=["달력"]), "bad_shape"),
    ("page zero", lambda m: page0(m).update(page=0), "bad_page"),
    ("page a string", lambda m: page0(m).update(page="1"), "bad_page"),
    ("page a boolean", lambda m: page0(m).update(page=True), "bad_page"),
    ("page number used twice", second_page("C1", ROOT_ONLY, number=1), "bad_page"),
    ("frac missing", lambda m: elements0(m)[1].pop("frac"), "bad_frac"),
    ("frac of three numbers", lambda m: elements0(m)[1].update(frac=[0, 0, 1]), "bad_frac"),
    ("frac with a string", lambda m: elements0(m)[1].update(frac=[0, 0, "1", 1]), "bad_frac"),
    ("frac with NaN", lambda m: elements0(m)[1].update(frac=[0, 0, float("nan"), 1]), "bad_frac"),
    ("frac with infinity", lambda m: elements0(m)[1].update(frac=[0, 0, float("inf"), 1]), "bad_frac"),
    ("frac left of the page", lambda m: elements0(m)[1].update(frac=[-0.1, 0, 0.5, 0.5]), "bad_frac"),
    ("frac of zero width", lambda m: elements0(m)[1].update(frac=[0.1, 0.1, 0, 0.5]), "bad_frac"),
    ("frac past the right edge", lambda m: elements0(m)[1].update(frac=[0.6, 0, 0.5, 0.5]), "bad_frac"),
    ("frac past the bottom edge", lambda m: elements0(m)[1].update(frac=[0, 0.6, 0.5, 0.5]), "bad_frac"),
    (
        "an id twice on one page",
        lambda m: elements0(m).append({"id": "B2/calendar", "parent": "B2", "frac": [0, 0, 1, 1]}),
        "duplicate_id",
    ),
    ("a figure id used again on the next page", second_page("B2", {"id": "B2", "frac": [0, 0, 1, 1]}), "duplicate_id"),
    ("a parent that is no element", lambda m: elements0(m)[2].update(parent="B2/nothing"), "bad_parent"),
    (
        "a parent on another page",
        second_page("C1", ROOT_ONLY, {"id": "C1/x", "parent": "B2/calendar", "frac": [0, 0, 1, 1]}),
        "bad_parent",
    ),
    ("two elements parenting each other", lambda m: elements0(m)[1].update(parent="B2/calendar/m07"), "bad_parent"),
    ("an element its own parent", lambda m: elements0(m)[1].update(parent="B2/calendar"), "bad_parent"),
    ("pdf longer than MAP_MAX_PATH", lambda m: m.update(pdf=path_of(MAP_MAX_PATH + 1, ".pdf")), "bad_shape"),
    (
        "src file longer than MAP_MAX_PATH",
        lambda m: elements0(m)[1]["src"].update(file=path_of(MAP_MAX_PATH + 1, ".py")),
        "bad_shape",
    ),
    (
        "impl file longer than MAP_MAX_PATH",
        lambda m: elements0(m)[2]["impl"].update(file=path_of(MAP_MAX_PATH + 1, ".py")),
        "bad_shape",
    ),
    ("hi past MAP_MAX_LINE", lambda m: elements0(m)[1]["src"].update(hi=MAP_MAX_LINE + 1), "bad_shape"),
    (
        "impl lo and hi past MAP_MAX_LINE",
        lambda m: elements0(m)[2]["impl"].update(lo=MAP_MAX_LINE + 1, hi=MAP_MAX_LINE + 1),
        "bad_shape",
    ),
    *(
        ("src file with %s" % what, lambda m, path=path: elements0(m)[1]["src"].update(file=path), "path_outside")
        for what, path in NOT_CANONICAL.items()
    ),
    ("impl file climbing out", lambda m: elements0(m)[2]["impl"].update(file="../lib/components.py"), "path_outside"),
    (
        "an element MAP_MAX_DEPTH + 1 ids from its root",
        lambda m: page0(m).update(elements=chain_of(MAP_MAX_DEPTH + 1)),
        "bad_parent",
    ),
    ("no element without a parent", lambda m: elements0(m)[0].update(parent="B2/calendar"), "no_root"),
    ("two elements without a parent", lambda m: elements0(m)[1].pop("parent"), "no_root"),
    ("the root is not the figure", lambda m: page0(m).update(figure="B3"), "no_root"),
    ("the root is not the whole page", lambda m: elements0(m)[0].update(frac=[0, 0, 1, 0.5]), "no_root"),
    ("a page without elements", lambda m: page0(m).update(elements=[]), "no_root"),
]


class Purity(unittest.TestCase):
    """The parser reaches no file, process, network or server state (architecture.md stop signal)."""

    def test_imports_only_pure_standard_modules(self):
        """Every import of figmap.py is in PURE_IMPORTS: no os, pathlib, subprocess or limn module with effects."""
        tree = ast.parse(FIGMAP_PY.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertLessEqual(imported, PURE_IMPORTS)


class Accepted(unittest.TestCase):
    """What the example map parses into, and the edges the format allows."""

    def test_the_example_map_becomes_its_values(self):
        """Pages, elements (root first), sources, the ancestor chain nearest first, and lookups by page and id."""
        got = parse(figure_map(MINI_PDF))
        self.assertIsInstance(got, FigureMap)
        page = got.page(1)
        self.assertEqual((got.pdf, len(got.pdf_sha256)), ("figures.pdf", 64))
        self.assertEqual(
            (page.figure, page.title, [e.id for e in page.elements]),
            ("B2", "Deployment calendar", ["B2", "B2/calendar", "B2/calendar/m07"]),
        )
        cell = page.by_id("B2/calendar/m07")
        self.assertEqual(
            cell,
            MapElement(
                "B2/calendar/m07",
                "B2/calendar",
                (0.47, 0.18, 0.07, 0.12),
                SourceRef("src/B2_calendar.py", 88, 95),
                SourceRef("lib/components.py", 410, 470),
                "MonthCell",
                "7월",
            ),
        )
        self.assertEqual([e.id for e in page.ancestors(cell)], ["B2/calendar", "B2"])
        self.assertEqual(page.ancestors(page.root()), ())
        self.assertEqual(got.find("B2/calendar"), (page, page.by_id("B2/calendar")))
        self.assertEqual((got.find("B9"), got.page(2), page.by_id("B9")), (None, None, None))

    def test_unknown_keys_are_ignored_at_every_level(self):
        """The format grows additively: a key this version does not know changes nothing it parses."""
        m = figure_map(MINI_PDF)
        extra = copy.deepcopy(m)
        extra["generator"] = "fig-tool 2"
        page0(extra)["layout"] = {"w": 180}
        for el in elements0(extra):
            el["style"] = ["bold"]
        elements0(extra)[1]["src"]["col"] = 4
        got = parse(extra)
        self.assertIsInstance(got, FigureMap)
        self.assertEqual(got, parse(m))

    def test_an_element_drawn_without_code_has_no_source(self):
        """A vector graphic exported from a design tool has no code lines (ADR-0011 D7): src and impl are None."""

        def drop_code(m: dict) -> None:
            """Remove src and impl from every element."""
            for el in elements0(m):
                el.pop("src", None)
                el.pop("impl", None)

        got = parse(changed(drop_code))
        self.assertEqual([(e.src, e.impl) for e in got.page(1).elements], [(None, None)] * 3)

    def test_a_root_listed_last_comes_first_and_a_null_parent_is_no_parent(self):
        """Element order in the file is free; the parsed page puts its root first. "parent": null means no parent."""

        def root_last(m: dict) -> None:
            """Move the root to the end of the list and give it an explicit null parent."""
            els = elements0(m)
            els.append(els.pop(0))
            els[-1]["parent"] = None

        got = parse(changed(root_last))
        self.assertEqual([e.id for e in got.page(1).elements], ["B2", "B2/calendar", "B2/calendar/m07"])
        self.assertIsNone(got.page(1).root().parent)

    def test_a_box_may_pass_the_page_edge_by_rounding_only(self):
        """x + w and y + h may exceed 1 by at most FRAC_EPS (a producer's float rounding), not by more."""
        ok = parse(changed(lambda m: elements0(m)[1].update(frac=[0.5, 0.5, 0.5000005, 0.5000005])))
        self.assertIsInstance(ok, FigureMap)
        over = parse(changed(lambda m: elements0(m)[1].update(frac=[0.5, 0.5, 0.500002, 0.5])))
        self.assertEqual(over.reason, "bad_frac")

    def test_a_map_without_pages_is_a_map(self):
        """An empty page list is accepted; every lookup answers None."""
        got = parse(changed(lambda m: m.update(pages=[])))
        self.assertEqual((got.pages, got.page(1), got.find("B2")), ((), None, None))

    def test_each_bound_a_pin_relies_on_is_accepted_at_its_limit(self):
        """pdf, src.file and impl.file of MAP_MAX_PATH characters, lo = hi = MAP_MAX_LINE, and a parent chain whose
        last element is MAP_MAX_DEPTH ids from the root, both counted: each is a map, with the value kept."""

        def depth_of_last(got: FigureMap) -> int:
            """How many ids lie from the first page's root down to its last element, both counted."""
            page = got.page(1)
            return len(page.ancestors(page.elements[-1])) + 1

        pdf, file = path_of(MAP_MAX_PATH, ".pdf"), path_of(MAP_MAX_PATH, ".py")
        rows: list[tuple[str, Callable[[dict], object], Callable[[FigureMap], object], object]] = [
            ("pdf", lambda m: m.update(pdf=pdf), lambda got: got.pdf, pdf),
            (
                "src file",
                lambda m: elements0(m)[1]["src"].update(file=file),
                lambda got: got.page(1).elements[1].src.file,
                file,
            ),
            (
                "impl file",
                lambda m: elements0(m)[2]["impl"].update(file=file),
                lambda got: got.page(1).elements[2].impl.file,
                file,
            ),
            (
                "lines",
                lambda m: elements0(m)[1]["src"].update(lo=MAP_MAX_LINE, hi=MAP_MAX_LINE),
                lambda got: got.page(1).elements[1].src,
                SourceRef("src/B2_calendar.py", MAP_MAX_LINE, MAP_MAX_LINE),
            ),
            ("depth", lambda m: page0(m).update(elements=chain_of(MAP_MAX_DEPTH)), depth_of_last, MAP_MAX_DEPTH),
        ]
        for what, change, read, want in rows:
            with self.subTest(what):
                got = parse(changed(change))
                self.assertIsInstance(got, FigureMap)
                self.assertEqual(read(got), want)

    def test_a_file_exactly_at_the_size_cap_is_read(self):
        """MAP_MAX_BYTES bytes (a map padded with trailing whitespace) are still a map."""
        raw = map_bytes(figure_map(MINI_PDF))
        padded = raw + b" " * (MAP_MAX_BYTES - len(raw))
        self.assertIsInstance(parse_map(padded, source_inside=anywhere), FigureMap)

    def test_every_source_path_is_put_to_the_check(self):
        """source_inside is asked about each src.file and impl.file the map names."""
        asked: list[str] = []

        def record(path: str) -> bool:
            """Remember the path and accept it."""
            asked.append(path)
            return True

        parse(figure_map(MINI_PDF), source_inside=record)
        self.assertEqual(sorted(set(asked)), ["lib/components.py", "src/B2_calendar.py"])


class Rejected(unittest.TestCase):
    """Each rule of the map breaks alone and parse_map names it; nothing is raised."""

    def test_each_broken_rule_is_named(self):
        """One change to the example map per row of REJECTIONS; the reason is the row's."""
        for what, change, reason in REJECTIONS:
            with self.subTest(what):
                got = parse(changed(change))
                self.assertIsInstance(got, MapRejected)
                self.assertEqual(got.reason, reason, got.detail)

    def test_names_a_pin_stores_are_at_most_map_max_text_characters(self):
        """figure, title, id, part and label of MAP_MAX_TEXT - 1 and MAP_MAX_TEXT characters are kept whole; one
        character more is bad_shape. Characters, not bytes: the text is Hangul."""
        for field, put in TEXT_FIELDS.items():
            for length in (MAP_MAX_TEXT - 1, MAP_MAX_TEXT, MAP_MAX_TEXT + 1):
                with self.subTest(field=field, length=length):
                    text = "가" * length
                    got = parse(changed(lambda m, put=put, text=text: put(m, text)))
                    if length > MAP_MAX_TEXT:
                        self.assertIsInstance(got, MapRejected)
                        self.assertEqual(got.reason, "bad_shape", got.detail)
                    else:
                        self.assertIsInstance(got, FigureMap)
                        page = got.page(1)
                        cell = page.elements[2]
                        kept = {
                            "figure": page.figure,
                            "title": page.title,
                            "id": cell.id,
                            "part": cell.part,
                            "label": cell.label,
                        }
                        self.assertEqual(kept[field], text)

    def test_the_detail_says_where_the_rule_broke(self):
        """The detail starts with the path into the map, so a producer can find the element."""
        got = parse(changed(lambda m: elements0(m)[1].update(frac=[0.1, 0.1, 0, 0.5])))
        self.assertTrue(got.detail.startswith("pages[0].elements[1].frac"), got.detail)

    def test_a_file_over_the_size_cap_is_refused_before_it_is_decoded(self):
        """MAP_MAX_BYTES + 1 bytes are too_large even though they are not JSON: the size is checked first."""
        self.assertEqual(parse_map(b" " * (MAP_MAX_BYTES + 1), source_inside=anywhere).reason, "too_large")

    def test_bytes_that_are_not_one_json_object_are_refused(self):
        """Broken JSON, bytes that are not UTF-8, a repeated key and nesting deeper than the parser's stack are
        not_json; a JSON array is not a map (bad_shape)."""
        repeated = b'{"format": "limn-figure-map/1", "format": "limn-figure-map/1"}'
        deep = b"[" * 100_000 + b"]" * 100_000
        for raw in (b"{", b"\xff\xfe{}", repeated, deep):
            with self.subTest(raw=raw[:20]):
                self.assertEqual(parse_map(raw, source_inside=anywhere).reason, "not_json")
        self.assertEqual(parse_map(b"[]", source_inside=anywhere).reason, "bad_shape")

    def test_too_many_elements_on_a_page_is_refused_before_they_are_read(self):
        """A root and MAP_MAX_ELEMENTS children are one element over the cap."""
        many = [{"id": "B2", "frac": [0, 0, 1, 1]}] + [
            {"id": "B2/%d" % i, "parent": "B2", "frac": [0, 0, 1, 1]} for i in range(MAP_MAX_ELEMENTS)
        ]
        self.assertEqual(parse(changed(lambda m: page0(m).update(elements=many))).reason, "too_many_elements")

    def test_a_parent_chain_as_long_as_the_element_cap_is_refused_without_recursion(self):
        """MAP_MAX_ELEMENTS elements each the child of the one before, listed root first or leaf first, reach far
        deeper than MAP_MAX_DEPTH: bad_parent, found by an iterative walk - never a RecursionError."""
        chain = chain_of(MAP_MAX_ELEMENTS)
        for order, elements in (("root first", chain), ("leaf first", chain[::-1])):
            with self.subTest(order):
                got = parse(changed(lambda m, elements=elements: page0(m).update(elements=elements)))
                self.assertIsInstance(got, MapRejected)
                self.assertEqual(got.reason, "bad_parent", got.detail)

    def test_a_path_that_is_not_canonical_is_refused_before_the_folder_is_asked(self):
        """The root's src.file set to each NOT_CANONICAL path: path_outside, and source_inside is never asked - the
        root is the first element read, so no path was asked about before it."""
        asked: list[str] = []

        def record(path: str) -> bool:
            """Remember the path and accept it."""
            asked.append(path)
            return True

        for what, path in NOT_CANONICAL.items():
            with self.subTest(what):
                got = parse(
                    changed(lambda m, path=path: elements0(m)[0]["src"].update(file=path)), source_inside=record
                )
                self.assertIsInstance(got, MapRejected)
                self.assertEqual((got.reason, asked), ("path_outside", []))

    def test_a_source_path_the_document_does_not_hold_is_path_outside(self):
        """source_inside decides for src.file and impl.file alike (docs/handbook/code-style-roadmap.md §R10)."""
        for refused in ("src/B2_calendar.py", "lib/components.py"):
            with self.subTest(refused):
                got = parse(figure_map(MINI_PDF), source_inside=lambda f, refused=refused: f != refused)
                self.assertEqual(got.reason, "path_outside")


LEAVES = st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=12)
JSON_VALUES = st.recursive(
    LEAVES,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=24,
)
ELEMENT_KEYS = st.sampled_from(["id", "parent", "frac", "src", "impl", "part", "label", "x"])
ELEMENT_LIKE = st.dictionaries(ELEMENT_KEYS, JSON_VALUES | st.just("F") | st.just([0, 0, 1, 1]), max_size=8)
PAGE_LIKE = st.fixed_dictionaries(
    {
        "page": JSON_VALUES | st.integers(0, 3),
        "figure": JSON_VALUES | st.just("F"),
        "elements": st.lists(ELEMENT_LIKE, max_size=5),
    }
)
MAP_LIKE = st.fixed_dictionaries(
    {
        "format": st.just(MAP_FORMAT),
        "pdf": JSON_VALUES | st.just("figures.pdf"),
        "pdf_sha256": JSON_VALUES | st.just("0" * 64),
        "pages": st.lists(PAGE_LIKE, max_size=3),
    }
)


@st.composite
def valid_maps(draw) -> dict:
    """A map every rule accepts: up to three pages with distinct numbers, each a random tree under its root, the
    elements in any order, some with code lines."""
    numbers = draw(st.lists(st.integers(1, 40), max_size=3, unique=True))
    pages = []
    for k, number in enumerate(numbers):
        figure = "F%d" % k
        elements: list[dict] = [{"id": figure, "frac": [0, 0, 1, 1]}]
        for i in range(draw(st.integers(0, 6))):
            x = draw(st.floats(0, 0.9))
            y = draw(st.floats(0, 0.9))
            el = {
                "id": "%s/%d" % (figure, i),
                "parent": draw(st.sampled_from([e["id"] for e in elements])),
                "frac": [x, y, draw(st.floats(0.01, 1 - x)), draw(st.floats(0.01, 1 - y))],
            }
            if draw(st.booleans()):
                lo = draw(st.integers(1, 500))
                el["src"] = {"file": "src/f%d.py" % k, "lo": lo, "hi": lo + draw(st.integers(0, 50))}
            elements.append(el)
        pages.append({"page": number, "figure": figure, "elements": draw(st.permutations(elements))})
    return {"format": MAP_FORMAT, "pdf": "figures.pdf", "pdf_sha256": "a" * 64, "pages": pages}


class NeverRaises(unittest.TestCase):
    """parse_map answers every input with a value (coding rule R3: rejections are values)."""

    @given(st.binary(max_size=512))
    def test_any_bytes_give_a_map_or_a_rejection(self, raw):
        """Arbitrary bytes, JSON or not, never raise."""
        self.assertIsInstance(parse_map(raw, source_inside=anywhere), (FigureMap, MapRejected))

    @given(st.one_of(JSON_VALUES, MAP_LIKE))
    def test_any_json_gives_a_map_or_a_rejection(self, value):
        """Any JSON value - and objects shaped almost like a map whose keys hold anything - never raise."""
        raw = json.dumps(value).encode("ascii")
        self.assertIsInstance(parse_map(raw, source_inside=anywhere), (FigureMap, MapRejected))


class AcceptedMaps(unittest.TestCase):
    """Every map the rules accept is a set of trees, one per page, each rooted at its figure."""

    @given(valid_maps())
    def test_an_accepted_map_is_a_tree_per_page_rooted_at_its_figure(self, m):
        """The root is first, is the figure and covers the page; every other element's ancestors start at its parent
        and end at the root; find() returns each element with its page."""
        got = parse(m)
        self.assertIsInstance(got, FigureMap)
        for sent in m["pages"]:
            page = got.page(sent["page"])
            root = page.root()
            self.assertEqual((root.id, root.parent, root.frac), (sent["figure"], None, FULL_PAGE))
            self.assertEqual({e.id for e in page.elements}, {e["id"] for e in sent["elements"]})
            for el in page.elements[1:]:
                chain = page.ancestors(el)
                self.assertEqual((chain[0].id, chain[-1]), (el.parent, root))
                self.assertEqual(got.find(el.id), (page, el))

    @given(valid_maps())
    def test_unknown_keys_never_change_an_accepted_map(self, m):
        """Adding a key the format does not know, at every level, parses to an equal map."""
        extra = copy.deepcopy(m)
        extra["future"] = 1
        for p in extra["pages"]:
            p["future"] = [1]
            for el in p["elements"]:
                el["future"] = {"x": 1}
        got = parse(extra)
        self.assertIsInstance(got, FigureMap)
        self.assertEqual(got, parse(m))
