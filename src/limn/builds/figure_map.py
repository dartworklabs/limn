"""The element map a figure repository writes next to its PDF (limn-figure-map/1), parsed into values.

A figure document is a PDF - one figure per page - plus this map: per page, a tree of elements, each with its box on
the page (frac) and the lines of the code that drew it (src). The map takes the place SyncTeX has for a LaTeX
manuscript (docs/handbook/domain.md §여러 문서). Limn never runs the code that wrote it. The map is input: it is
parsed here once (coding rule R3) into frozen values, or into a MapRejected naming the first rule it breaks. The
format grows additively, so unknown keys are ignored; a repeated key is refused, since which value a reader keeps
would be a guess.

Pure: no file, subprocess or HTTP. The caller reads the bytes and passes source_inside, the path check of its
document's folder (limn.builds.artifacts.figure_source_check).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

from limn.platform.values import is_finite_num, is_int

MAP_FORMAT = "limn-figure-map/1"

MAP_MAX_BYTES = 4 * 1024 * 1024
MAP_MAX_ELEMENTS = 5000  # per page
MAP_MAX_TEXT = 200  # characters of a figure, title, element id, part or label: pins store them
MAP_MAX_PATH = 1024  # characters of pdf, src.file and impl.file: a pin stores impl.file
MAP_MAX_LINE = 1_000_000  # the highest lo or hi of src and impl: a pin stores impl's lines
MAP_MAX_DEPTH = 64  # ids from a page's root down to an element, both counted: a pin stores them as its path
Frac: TypeAlias = tuple[float, float, float, float]  # x, y, w, h; top-left origin; page fractions

FRAC_EPS = 1e-6  # how far past the page edge a producer's float rounding may put x + w or y + h
FULL_PAGE: Frac = (0.0, 0.0, 1.0, 1.0)  # the root element's box: the whole page
DETAIL_TEXT_MAX = 80  # how much of the map's own text a rejection's detail quotes
_HEX = frozenset("0123456789abcdef")

MapRejectReason: TypeAlias = Literal[
    "too_large",
    "not_json",
    "bad_format",
    "bad_shape",
    "bad_page",
    "bad_frac",
    "duplicate_id",
    "bad_parent",
    "no_root",
    "too_many_elements",
    "path_outside",
]


@dataclass(frozen=True)
class MapRejected:
    """Why a map is not used: the first rule it breaks (reason) and where in the map (detail - English, for logs;
    never shown as a contract value)."""

    reason: MapRejectReason
    detail: str


@dataclass(frozen=True)
class SourceRef:
    """Lines lo..hi (1-based, lo <= hi) of file, a path relative to the figure document's folder (Doc.src) with POSIX
    separators."""

    file: str
    lo: int
    hi: int


@dataclass(frozen=True)
class MapElement:
    """One element of a figure page: its id (unique in the map, stable across renders), its parent's id (None only for
    the page root), its box on the page, the code lines that called it (src - None for a vector graphic drawn without
    code, ADR-0011 D7), the lines of the shared component that implements it (impl), and the names a person sees
    (part, label)."""

    id: str
    parent: str | None
    frac: Frac
    src: SourceRef | None
    impl: SourceRef | None
    part: str | None
    label: str | None


@dataclass(frozen=True)
class MapPage:
    """One page of the figure PDF: its 1-based number, the figure's id (the root element's id), an optional title, and
    its elements with the root first and the rest in map order. The id index is built once, at construction."""

    page: int
    figure: str
    title: str | None
    elements: tuple[MapElement, ...]
    _by_id: dict[str, MapElement] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Index the elements by id; when an id repeats (parse_map never lets one), the first in order wins."""
        index: dict[str, MapElement] = {}
        for el in self.elements:
            index.setdefault(el.id, el)
        object.__setattr__(self, "_by_id", index)

    def root(self) -> MapElement:
        """The page's root element, the first element (parse_map puts it there). Precondition: the page has one."""
        return self.elements[0]

    def by_id(self, el_id: str) -> MapElement | None:
        """The element of this page whose id is el_id, or None."""
        return self._by_id.get(el_id)

    def ancestors(self, el: MapElement) -> tuple[MapElement, ...]:
        """el's parent, its parent, and so on up to the root: nearest first, root last; () for the root. The walk stops
        at a parent that is not on this page or already seen, so it ends even for a page built by hand."""
        out: list[MapElement] = []
        seen = {el.id}
        parent = el.parent
        while parent is not None and parent not in seen:
            node = self._by_id.get(parent)
            if node is None:
                break
            out.append(node)
            seen.add(parent)
            parent = node.parent
        return tuple(out)


@dataclass(frozen=True)
class FigureMap:
    """A parsed map: the PDF it describes (relative to the map file's folder), that PDF's SHA-256 (64 lowercase hex
    digits), and its pages in map order. Page numbers and element ids are indexed once, at construction."""

    pdf: str
    pdf_sha256: str
    pages: tuple[MapPage, ...]
    _by_page: dict[int, MapPage] = field(init=False, repr=False, compare=False)
    _by_id: dict[str, tuple[MapPage, MapElement]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Index the pages by number and the elements by id; the first in map order wins a repeat."""
        by_page: dict[int, MapPage] = {}
        by_id: dict[str, tuple[MapPage, MapElement]] = {}
        for p in self.pages:
            by_page.setdefault(p.page, p)
            for el in p.elements:
                by_id.setdefault(el.id, (p, el))
        object.__setattr__(self, "_by_page", by_page)
        object.__setattr__(self, "_by_id", by_id)

    def page(self, n: int) -> MapPage | None:
        """The page numbered n (1-based), or None when the map has none."""
        return self._by_page.get(n)

    def find(self, el_id: str) -> tuple[MapPage, MapElement] | None:
        """The page and the element whose id is el_id, or None."""
        return self._by_id.get(el_id)


def parse_map(raw: bytes, *, source_inside: Callable[[str], bool]) -> FigureMap | MapRejected:
    """The map raw holds, or the first rule it breaks, in this order: the size (at most MAP_MAX_BYTES, checked before
    decoding: too_large); UTF-8 JSON with no repeated key and no nesting deeper than the decoder's stack (not_json); a
    top-level object (bad_shape); format (bad_format); pdf a non-empty string of at most MAP_MAX_PATH characters and
    pdf_sha256 64 lowercase hex digits (bad_shape); pages a list; then each page in map order (_page). What a pin
    stores is bounded, so every element of an accepted map can be pinned: the names - figure, title, element id,
    part, label - are at most MAP_MAX_TEXT characters (bad_shape), src and impl paths at most MAP_MAX_PATH characters
    and canonical, their lines at most MAP_MAX_LINE (_source), and an element at most MAP_MAX_DEPTH ids from its
    root (_tree_rejection). pdf is relative to the map's folder and may climb out of it with '..': where it lands is
    the import's check (limn.builds.artifacts.figure_pdf), not the parser's. Unknown keys are ignored everywhere. Never raises.
    source_inside is asked about every canonical src.file and impl.file and must not raise either."""
    if len(raw) > MAP_MAX_BYTES:
        return MapRejected("too_large", "%d bytes > %d" % (len(raw), MAP_MAX_BYTES))
    try:
        top = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (ValueError, RecursionError) as e:
        return MapRejected("not_json", str(e)[:200])
    if not isinstance(top, dict):
        return MapRejected("bad_shape", "the map is not a JSON object")
    if top.get("format") != MAP_FORMAT:
        return MapRejected("bad_format", "format is %s, not %r" % (_short(top.get("format")), MAP_FORMAT))
    pdf = _text(top.get("pdf"))
    if not pdf or len(pdf) > MAP_MAX_PATH:
        return MapRejected("bad_shape", "pdf must be a non-empty string of at most %d characters" % MAP_MAX_PATH)
    sha = top.get("pdf_sha256")
    if not (isinstance(sha, str) and len(sha) == 64 and set(sha) <= _HEX):
        return MapRejected("bad_shape", "pdf_sha256 must be 64 lowercase hex digits")
    raw_pages = top.get("pages")
    if not isinstance(raw_pages, list):
        return MapRejected("bad_shape", "pages must be a list")
    pages: list[MapPage] = []
    numbers: set[int] = set()
    ids: set[str] = set()
    for i, p in enumerate(raw_pages):
        page = _page(p, "pages[%d]" % i, numbers, ids, source_inside)
        if isinstance(page, MapRejected):
            return page
        pages.append(page)
    return FigureMap(pdf, sha, tuple(pages))


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """json's object hook: a JSON object as a dict. A repeated key raises ValueError, which parse_map answers
    not_json - which of two values a reader keeps is ambiguous."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("repeated key %r" % key[:DETAIL_TEXT_MAX])
        out[key] = value
    return out


def _short(v: object) -> str:
    """A map value for a rejection's detail: a string, number, boolean or null cut to DETAIL_TEXT_MAX characters;
    otherwise only its JSON type (a huge or deep value is never rendered)."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return repr(v)[:DETAIL_TEXT_MAX]
    return type(v).__name__


def _text(v: object) -> str | None:
    """v when it is a string UTF-8 can encode, else None. json.loads lets an escaped lone surrogate through, and such
    a string could never be written to pins.md."""
    if not isinstance(v, str):
        return None
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return v


def _name(v: object) -> str | None:
    """v when it is a non-empty string UTF-8 can encode (_text) of at most MAP_MAX_TEXT characters - a figure id or
    an element id, which pins store - else None."""
    text = _text(v)
    return text if text and len(text) <= MAP_MAX_TEXT else None


def _opt_text(v: object, where: str) -> str | None | MapRejected:
    """An optional name a person sees (title, part, label): None when absent or null, the string when it is one
    (_text) of at most MAP_MAX_TEXT characters, else bad_shape."""
    if v is None:
        return None
    text = _text(v)
    if text is None or len(text) > MAP_MAX_TEXT:
        return MapRejected(
            "bad_shape", "%s must be a string of at most %d characters, or absent" % (where, MAP_MAX_TEXT)
        )
    return text


def _int(v: object) -> int | None:
    """v when it is a JSON integer (not a boolean), else None."""
    return v if is_int(v) else None


def _page(
    v: object, where: str, numbers: set[int], ids: set[str], source_inside: Callable[[str], bool]
) -> MapPage | MapRejected:
    """One page, or the first rule it breaks: an object (bad_shape); page a JSON integer >= 1 no earlier page used
    (bad_page); figure a non-empty string and title absent or a string (bad_shape); elements a list (bad_shape) of at
    most MAP_MAX_ELEMENTS, counted before any is read (too_many_elements); each element (_element, ids unique across
    the map); exactly one root (_rooted: no_root); every parent on this page, no cycle and no element deeper than
    MAP_MAX_DEPTH (_tree_rejection: bad_parent). figure and title are at most MAP_MAX_TEXT characters. numbers and ids collect what this page uses,
    for the pages after it."""
    if not isinstance(v, dict):
        return MapRejected("bad_shape", "%s is not an object" % where)
    number = _int(v.get("page"))
    if number is None or number < 1 or number in numbers:
        return MapRejected(
            "bad_page", "%s.page must be an unused integer >= 1, not %s" % (where, _short(v.get("page")))
        )
    numbers.add(number)
    figure = _name(v.get("figure"))
    if figure is None:
        return MapRejected(
            "bad_shape", "%s.figure must be a non-empty string of at most %d characters" % (where, MAP_MAX_TEXT)
        )
    title = _opt_text(v.get("title"), where + ".title")
    if isinstance(title, MapRejected):
        return title
    raw_elements = v.get("elements")
    if not isinstance(raw_elements, list):
        return MapRejected("bad_shape", "%s.elements must be a list" % where)
    if len(raw_elements) > MAP_MAX_ELEMENTS:
        return MapRejected(
            "too_many_elements", "%s has %d elements > %d" % (where, len(raw_elements), MAP_MAX_ELEMENTS)
        )
    elements: list[MapElement] = []
    for j, e in enumerate(raw_elements):
        el = _element(e, "%s.elements[%d]" % (where, j), ids, source_inside)
        if isinstance(el, MapRejected):
            return el
        elements.append(el)
    ordered = _rooted(elements, figure, where)
    if isinstance(ordered, MapRejected):
        return ordered
    broken = _tree_rejection(ordered, where)
    if broken is not None:
        return broken
    return MapPage(number, figure, title, ordered)


def _element(v: object, where: str, ids: set[str], source_inside: Callable[[str], bool]) -> MapElement | MapRejected:
    """One element, or the first rule it breaks: an object (bad_shape); id a non-empty string of at most MAP_MAX_TEXT
    characters (bad_shape) not used earlier in the map (duplicate_id); parent absent, null or a non-empty string
    (bad_shape); frac (_frac: bad_frac); src and impl (_source: bad_shape, path_outside); part and label absent or
    strings of at most MAP_MAX_TEXT characters (bad_shape). The id is added to ids."""
    if not isinstance(v, dict):
        return MapRejected("bad_shape", "%s is not an object" % where)
    el_id = _name(v.get("id"))
    if el_id is None:
        return MapRejected(
            "bad_shape", "%s.id must be a non-empty string of at most %d characters" % (where, MAP_MAX_TEXT)
        )
    if el_id in ids:
        return MapRejected("duplicate_id", "%s.id %r is used earlier in the map" % (where, el_id[:DETAIL_TEXT_MAX]))
    ids.add(el_id)
    parent: str | None = None
    if v.get("parent") is not None:
        parent = _text(v.get("parent"))
        if not parent:
            return MapRejected("bad_shape", "%s.parent must be a non-empty string or absent" % where)
    frac = _frac(v.get("frac"), where + ".frac")
    if isinstance(frac, MapRejected):
        return frac
    src = _source(v.get("src"), where + ".src", source_inside)
    if isinstance(src, MapRejected):
        return src
    impl = _source(v.get("impl"), where + ".impl", source_inside)
    if isinstance(impl, MapRejected):
        return impl
    part = _opt_text(v.get("part"), where + ".part")
    if isinstance(part, MapRejected):
        return part
    label = _opt_text(v.get("label"), where + ".label")
    if isinstance(label, MapRejected):
        return label
    return MapElement(el_id, parent, frac, src, impl, part, label)


def _frac(v: object, where: str) -> Frac | MapRejected:
    """[x, y, w, h] as page fractions with the origin at the top left, or bad_frac: four finite JSON numbers
    (limn.platform.values.is_finite_num) with 0 <= x, 0 <= y, w > 0, h > 0, x + w <= 1 + FRAC_EPS and
    y + h <= 1 + FRAC_EPS."""
    if not (isinstance(v, list) and len(v) == 4 and all(is_finite_num(n) for n in v)):
        return MapRejected("bad_frac", "%s must be four finite numbers" % where)
    x, y, w, h = float(v[0]), float(v[1]), float(v[2]), float(v[3])
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1 + FRAC_EPS or y + h > 1 + FRAC_EPS:
        return MapRejected("bad_frac", "%s = [%g, %g, %g, %g] is not a box on the page" % (where, x, y, w, h))
    return x, y, w, h


def _source(v: object, where: str, source_inside: Callable[[str], bool]) -> SourceRef | None | MapRejected:
    """An optional {file, lo, hi}: None when absent or null (a vector graphic without code, ADR-0011 D7); bad_shape
    unless an object whose file is a non-empty string of at most MAP_MAX_PATH characters and lo, hi JSON integers with
    1 <= lo <= hi <= MAP_MAX_LINE; path_outside when file is not a canonical relative path (_canonical - refused before
    source_inside is asked) or source_inside refuses it."""
    if v is None:
        return None
    if not isinstance(v, dict):
        return MapRejected("bad_shape", "%s must be an object {file, lo, hi}" % where)
    file = _text(v.get("file"))
    lo, hi = _int(v.get("lo")), _int(v.get("hi"))
    if not file or len(file) > MAP_MAX_PATH or lo is None or hi is None or not 1 <= lo <= hi <= MAP_MAX_LINE:
        return MapRejected(
            "bad_shape",
            "%s must be {file, lo, hi} with a file of at most %d characters and 1 <= lo <= hi <= %d"
            % (where, MAP_MAX_PATH, MAP_MAX_LINE),
        )
    if not _canonical(file):
        return MapRejected(
            "path_outside", "%s.file %r is not a canonical relative path" % (where, file[:DETAIL_TEXT_MAX])
        )
    if not source_inside(file):
        return MapRejected(
            "path_outside", "%s.file %r is outside the figure's folder" % (where, file[:DETAIL_TEXT_MAX])
        )
    return SourceRef(file, lo, hi)


def _rooted(elements: list[MapElement], figure: str, where: str) -> tuple[MapElement, ...] | MapRejected:
    """The elements with the page root first and the rest in map order, or no_root unless exactly one element has no
    parent, its id is the page's figure and its frac is the whole page (FULL_PAGE)."""
    roots = [el for el in elements if el.parent is None]
    if len(roots) != 1 or roots[0].id != figure or roots[0].frac != FULL_PAGE:
        return MapRejected(
            "no_root",
            "%s needs exactly one element without parent, with id %r and frac [0, 0, 1, 1]"
            % (where, figure[:DETAIL_TEXT_MAX]),
        )
    root = roots[0]
    return (root,) + tuple(el for el in elements if el is not root)


def _canonical(path: str) -> bool:
    """Whether path is a canonical relative POSIX path, the only form a pin stores: no leading or trailing '/', no
    empty, '.' or '..' part, and no backslash or NUL. Where it leads is not asked here (source_inside is)."""
    return "\\" not in path and "\x00" not in path and all(part not in ("", ".", "..") for part in path.split("/"))


def _tree_rejection(elements: tuple[MapElement, ...], where: str) -> MapRejected | None:
    """bad_parent when a parent names no element of this page, when following the parents from an element never
    reaches the root (a cycle), or when an element lies more than MAP_MAX_DEPTH ids from the root, both counted (a pin
    stores that chain of ids); None for a tree. elements has the root first. The walk is iterative and remembers each
    element's depth once it is known, so a chain of MAP_MAX_ELEMENTS elements costs one pass, in any order."""
    by_id = {el.id: el for el in elements}
    for el in elements:
        if el.parent is not None and el.parent not in by_id:
            return MapRejected(
                "bad_parent",
                "%s: parent %r of %r is not on this page"
                % (where, el.parent[:DETAIL_TEXT_MAX], el.id[:DETAIL_TEXT_MAX]),
            )
    depth = {elements[0].id: 1}
    for el in elements:
        walk: list[str] = []
        on_walk: set[str] = set()
        cur = el
        while cur.id not in depth:
            if cur.id in on_walk or cur.parent is None:
                return MapRejected("bad_parent", "%s: %r is on a parent cycle" % (where, cur.id[:DETAIL_TEXT_MAX]))
            walk.append(cur.id)
            on_walk.add(cur.id)
            cur = by_id[cur.parent]
        d = depth[cur.id]
        for el_id in reversed(walk):
            d += 1
            if d > MAP_MAX_DEPTH:
                return MapRejected(
                    "bad_parent",
                    "%s: %r is more than %d ids from the root" % (where, el_id[:DETAIL_TEXT_MAX], MAP_MAX_DEPTH),
                )
            depth[el_id] = d
    return None
