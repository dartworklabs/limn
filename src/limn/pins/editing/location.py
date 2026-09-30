"""Validate line and PDF region locations for pin creation and editing."""

from dataclasses import dataclass
from typing import Any

from limn.builds import MAP_MAX_DEPTH, MAP_MAX_LINE, MAP_MAX_PATH, MAP_MAX_TEXT, is_canonical_path, valid_build_name
from limn.pins.editing.fields import parse_scope
from limn.pins.editing.values import PDF_QUOTE_MAX, Scope
from limn.pins.element import ElementImpl, PinElement
from limn.pins.location.mapping import VIAS, Via, norm, truncate_quote
from limn.pins.model import Record
from limn.platform.values import is_int
from limn.web.errors import InputRejected
from limn.web.parse import PDF_BUILD_REFUSAL, DocumentFacts, Frac, Json, int_field, num_field, source_file


@dataclass(frozen=True)
class LineLoc:
    """A line pin's checked location (parse_loc): the file inside the manuscript tree (absolute, resolved) and its
    name, the range 1 <= lo <= hi <= the file's line count, the page (>= 1), and each optional field the request sent
    - None when it did not; el is the figure element, kept on a figure document only."""

    file: str
    name: str
    lo: int
    hi: int
    page: int
    raw_lo: int | None = None
    raw_hi: int | None = None
    kind: str | None = None
    via: Via | None = None
    score: float | None = None
    frac: Frac | None = None
    scope: Scope | None = None
    quote: str | None = None
    pdf_build: str | None = None
    el: PinElement | None = None

    def to_record(self) -> Record:
        """The fields as a pin record stores them: file, name, lo, hi, page, then each optional field that was sent,
        in this order (the key order pin records have always had; frac as a JSON list), a figure pin's el last."""
        out: dict[str, Any] = {"file": self.file, "name": self.name, "lo": self.lo, "hi": self.hi, "page": self.page}
        optional: tuple[tuple[str, object], ...] = (
            ("raw_lo", self.raw_lo),
            ("raw_hi", self.raw_hi),
            ("kind", self.kind),
            ("via", self.via),
            ("score", self.score),
            ("frac", None if self.frac is None else list(self.frac)),
            ("scope", self.scope),
            ("quote", self.quote),
            ("pdf_build", self.pdf_build),
            ("el", None if self.el is None else self.el.to_record()),
        )
        out.update((k, v) for k, v in optional if v is not None)
        return out


@dataclass(frozen=True)
class RegionLoc:
    """A region pin's checked location (parse_region): the document's PDF and its name, the page (within the build's
    pages when it has any), the region frac inside the page, and the optional quote (normalized and cut) and
    pdf_build - None when not sent - and a figure pin's el."""

    pdf: str
    name: str
    page: int
    frac: Frac
    quote: str | None = None
    pdf_build: str | None = None
    el: PinElement | None = None

    def to_record(self) -> Record:
        """The fields as a pin record stores them: pdf, name, kind "region", page, frac (a JSON list), then quote,
        pdf_build and a figure pin's el when present - the key order region pins have always had, el last."""
        out: dict[str, Any] = {
            "pdf": self.pdf,
            "name": self.name,
            "kind": "region",
            "page": self.page,
            "frac": list(self.frac),
        }
        if self.quote is not None:
            out["quote"] = self.quote
        if self.pdf_build is not None:
            out["pdf_build"] = self.pdf_build
        if self.el is not None:
            out["el"] = self.el.to_record()
        return out


def _frac4(v: object, refusal: InputRejected) -> Frac | InputRejected:
    """Four finite JSON numbers as a Frac, or the first one's num_field refusal; `refusal` when v is not a list of
    exactly four."""
    if not isinstance(v, list) or len(v) != 4:
        return refusal
    nums: list[float] = []
    for x in v:
        n = num_field(x, "frac")
        if isinstance(n, InputRejected):
            return n
        nums.append(n)
    return nums[0], nums[1], nums[2], nums[3]


# What a pin's el may hold. They are the limits a map is parsed by (limn.builds.figure_map), so every element a map
# accepts can be pinned: a longer text, a deeper path or a higher line would make a pin the map itself could not have
# described.
EL_TEXT_MAX = MAP_MAX_TEXT  # characters of an element id, path entry, label or part
EL_PATH_MAX = MAP_MAX_DEPTH  # ids from the page root down to the element
EL_FILE_MAX = MAP_MAX_PATH  # characters of impl.file
EL_LINE_MAX = MAP_MAX_LINE  # the highest impl line, as for a close's changes
EL_REFUSAL = (
    "el 은 pick 이 준 요소 {id, path, label?, part?, impl?: {file, lo, hi}, frac?} 여야 합니다"
    "(문자열 %d자 이하, path 는 뿌리부터 그 요소까지의 id, impl.file 은 문서 폴더 기준 상대 경로)." % EL_TEXT_MAX
)


def parse_el(v: object) -> PinElement | None | InputRejected:
    """A figure pin's el as a request sends it (POST /api/pin, an edit's loc) - the element the pick answered - as its
    value, None when absent or null, or 400 bad_el.

    id is a non-empty string; path a list of 1..EL_PATH_MAX non-empty strings ending with id; label and part strings
    when sent (an empty one counts as not sent, as the pick leaves it out); impl, when sent, {file, lo, hi} with file a
    canonical relative POSIX path of at most EL_FILE_MAX characters (limn.builds.figure_map.is_canonical_path: no '..',
    '.' or empty part, no leading '/', backslash or NUL) and 1 <= lo <= hi <= EL_LINE_MAX; frac, when sent, four finite
    numbers inside the page with positive area (parse_frac); every other string at most EL_TEXT_MAX characters. Keys
    other than these are dropped, as unknown top-level fields are: the value is the canonical element, and is what is
    stored."""
    if v is None:
        return None
    bad = InputRejected(EL_REFUSAL, "bad_el")
    if not isinstance(v, dict):
        return bad
    eid = v.get("id")
    if not isinstance(eid, str) or not 0 < len(eid) <= EL_TEXT_MAX:
        return bad
    path = v.get("path")
    if not isinstance(path, list) or not 1 <= len(path) <= EL_PATH_MAX or path[-1] != eid:
        return bad
    if not all(isinstance(p, str) and 0 < len(p) <= EL_TEXT_MAX for p in path):
        return bad
    label, part = v.get("label"), v.get("part")
    if any(t is not None and not (isinstance(t, str) and len(t) <= EL_TEXT_MAX) for t in (label, part)):
        return bad
    impl = _el_impl(v.get("impl"))
    if isinstance(impl, InputRejected):
        return impl
    frac: Frac | None = None
    if v.get("frac") is not None:
        got = parse_frac(v["frac"])
        if isinstance(got, InputRejected):
            return bad
        frac = got
    return PinElement(eid, tuple(path), label or None, part or None, impl, frac)


def _el_impl(v: object) -> ElementImpl | None | InputRejected:
    """An el's impl as sent -> ElementImpl, None when absent or null, or parse_el's refusal (see its rule)."""
    if v is None:
        return None
    bad = InputRejected(EL_REFUSAL, "bad_el")
    if not isinstance(v, dict):
        return bad
    file, lo, hi = v.get("file"), v.get("lo"), v.get("hi")
    if not (isinstance(file, str) and 0 < len(file) <= EL_FILE_MAX and is_canonical_path(file)):
        return bad
    if not (is_int(lo) and is_int(hi) and 1 <= lo <= hi <= EL_LINE_MAX):
        return bad
    return ElementImpl(file, lo, hi)


def parse_loc(d: Json, facts: DocumentFacts) -> LineLoc | InputRejected:
    """A line pin's location, or the first field refused.

    file must be a file inside the manuscript tree and 1 <= lo <= hi <= its line count, so this reads that file's
    lines (facts.lines) before checking the range. page defaults to 1; raw_lo, raw_hi, kind, via (one of
    mapping.VIAS), score, frac, scope (one of edit.SCOPES), quote (truncated to 60 characters) and pdf_build (a page
    directory name) are checked in that order when sent (a null counts as not sent), then el on a figure document
    (parse_el; on any other document it is dropped like an unknown field). The checked location is constructed only
    after every field has passed.
    """
    f = source_file(d.get("file"), facts.root, facts.state)
    if isinstance(f, InputRejected):
        return f
    n = len(facts.lines(f))
    lo = int_field(d.get("lo"), "lo")
    if isinstance(lo, InputRejected):
        return lo
    hi = int_field(d.get("hi"), "hi")
    if isinstance(hi, InputRejected):
        return hi
    if not 1 <= lo <= hi <= max(n, 1):
        return InputRejected("줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (n, lo, hi), "range_outside_file")
    page = int_field(d.get("page", 1), "page")
    if isinstance(page, InputRejected):
        return page
    if page < 1:
        return InputRejected("page 는 1 이상이어야 합니다.", "bad_page")
    raw: dict[str, int] = {}
    for k in ("raw_lo", "raw_hi"):
        if d.get(k) is not None:
            v = int_field(d[k], k)
            if isinstance(v, InputRejected):
                return v
            raw[k] = v
    kind = d.get("kind")
    if kind is not None and (not isinstance(kind, str) or len(kind) > 80):
        return InputRejected("kind 가 올바르지 않습니다.", "bad_kind")
    via = d.get("via")
    if via is not None and via not in VIAS:
        return InputRejected("via 는 %s 입니다." % "|".join(VIAS), "bad_via")
    score = d.get("score")
    if score is not None:
        score = num_field(score, "score")
        if isinstance(score, InputRejected):
            return score
    frac = d.get("frac")
    if frac is not None:
        frac = _frac4(frac, InputRejected("frac 은 숫자 4개 목록입니다.", "bad_frac"))
        if isinstance(frac, InputRejected):
            return frac
    scope = d.get("scope")
    if scope is not None:
        scope = parse_scope(scope)
        if isinstance(scope, InputRejected):
            return scope
    quote = d.get("quote")
    if quote is not None:
        if not isinstance(quote, str):
            return InputRejected("quote 는 문자열입니다.", "bad_quote")
        quote = truncate_quote(quote, 60)
    pdf_build = d.get("pdf_build")  # the build on screen at drag time (pdf_build from the pick response)
    if pdf_build is not None and not facts.valid_build_name(pdf_build):
        return InputRejected(PDF_BUILD_REFUSAL, "bad_pdf_build")
    # a figure pin's element (docs/handbook/api.md §그림 문서의 pick·핀)
    el = parse_el(d.get("el")) if facts.has_element_map else None
    if isinstance(el, InputRejected):
        return el
    return LineLoc(
        file=str(f),
        name=f.path.name,
        lo=lo,
        hi=hi,
        page=page,
        raw_lo=raw.get("raw_lo"),
        raw_hi=raw.get("raw_hi"),
        kind=kind,
        via=via,
        score=score,
        frac=frac,
        scope=scope,
        quote=quote,
        pdf_build=pdf_build,
        el=el,
    )


def parse_frac(fr: object) -> Frac | InputRejected:
    """A view-only pin's region [x, y, w, h] as fractions of the page, checked more strictly than a LaTeX pin's
    frac since it is the pin's only location: 4 finite numbers, inside the page (0..1), with positive area."""
    frac = _frac4(fr, InputRejected("frac 은 숫자 4개 목록 [x, y, w, h](쪽 대비 비율)입니다.", "bad_frac"))
    if isinstance(frac, InputRejected):
        return frac
    x, y, w, h = frac
    eps = 1e-6
    if not (
        0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 + eps and 0 < h <= 1 + eps and x + w <= 1 + eps and y + h <= 1 + eps
    ):
        return InputRejected("frac 이 쪽 밖입니다(0..1, 넓이 > 0).", "frac_outside_page")
    return frac


def parse_region(d: Json, facts: DocumentFacts) -> RegionLoc | InputRejected:
    """A region pin's location - on a view-only PDF document (the document's own PDF) or, for an element drawn without
    code, on a figure document (the PDF its build's map names) - or the first field refused.

    file, lo, hi and scope are refused - such a pin has no lines. page is checked against the page count of the build
    the request names (pdf_build) or the current one (facts.page_count); with no pages yet, any page >= 1 passes.
    quote is whitespace-normalized and truncated to PDF_QUOTE_MAX; on a figure document the body's el is checked
    (parse_el) and kept, on any other document it is dropped like an unknown field.
    """
    for k in ("file", "lo", "hi", "scope"):
        if d.get(k) is not None:
            return InputRejected(
                "줄이 없는 영역 핀(%s)에는 %s 가 없습니다 — 쪽(page)과 영역(frac)만 받습니다." % (facts.key, k),
                "no_source_lines",
            )
    pdf = facts.pdf
    page = int_field(d.get("page"), "page")
    if isinstance(page, InputRejected):
        return page
    want = d.get("pdf_build")
    if want is not None and not facts.valid_build_name(want):
        return InputRejected(PDF_BUILD_REFUSAL, "bad_pdf_build")
    n = facts.page_count(want)
    if page < 1 or (n and page > n):
        return InputRejected("page 는 1..%d 이어야 합니다." % max(n, 1), "page_out_of_range")
    frac = parse_frac(d.get("frac"))
    if isinstance(frac, InputRejected):
        return frac
    quote: str | None = None
    if d.get("quote") is not None:
        if not isinstance(d["quote"], str):
            return InputRejected("quote 는 문자열입니다.", "bad_quote")
        quote = truncate_quote(norm(d["quote"]), PDF_QUOTE_MAX)
    el = parse_el(d.get("el")) if facts.has_element_map else None
    if isinstance(el, InputRejected):
        return el
    return RegionLoc(str(pdf), pdf.name, page, frac, quote, want, el)
