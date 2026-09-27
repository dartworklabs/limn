"""POST /api/pick boundary values and validation."""

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from limn.build import valid_build_name
from limn.features.pins.location.range import SourceRange
from limn.pins.shapes import is_finite_num
from limn.web.errors import InputRejected
from limn.web.parse import PDF_BUILD_REFUSAL, DocumentFacts, Json, Query, int_field, num_field, query_first, source_file


class PickRequest(NamedTuple):
    """A validated selection: the page directory it is traced in, the page (1-based), the box (x0, y0, x1, y1) in points
    clamped to the page, the page size (width, height) in points, and the viewer's frac as sent (None if absent)."""

    pdir: Path
    page: int
    box: tuple[float, float, float, float]
    size: tuple[float, float]
    frac: list[float] | None


@dataclass(frozen=True)
class PickBuildGone:
    """The selection names a page directory that is gone: the viewer re-reads /api/meta and asks again (a 200)."""


def parse_pick(d: Json, facts: DocumentFacts) -> PickRequest | PickBuildGone | InputRejected:
    """A POST /api/pick body, in the order the server has always checked it: pdf_build (the build on screen at drag
    time) must be a page directory name, and a gone one is answered at once; then page within that build's pages,
    x0, x1, y0, y1 as finite numbers (clamped to the page), and frac, when sent, as four finite numbers."""
    want = d.get("pdf_build")
    if want is not None and not valid_build_name(want):
        return InputRejected(PDF_BUILD_REFUSAL, "bad_pdf_build")
    found = facts.pick_pages(want)
    if found is None:
        return PickBuildGone()
    pdir, pages = found
    page = int_field(d.get("page"), "page")
    if isinstance(page, InputRejected):
        return page
    if not 1 <= page <= len(pages):
        return InputRejected("page 는 1..%d 이어야 합니다." % len(pages), "page_out_of_range")
    pw, ph = pages[page - 1]
    clamped: list[float] = []
    for k, top in (("x0", pw), ("x1", pw), ("y0", ph), ("y1", ph)):
        v = num_field(d.get(k), k)
        if isinstance(v, InputRejected):
            return v
        clamped.append(min(max(v, 0.0), top))
    x0, x1 = sorted(clamped[:2])
    y0, y1 = sorted(clamped[2:])
    frac = d.get("frac")
    if frac is not None and not (isinstance(frac, list) and len(frac) == 4 and all(is_finite_num(v) for v in frac)):
        return InputRejected("frac 은 숫자 4개 목록입니다.", "bad_frac")
    return PickRequest(pdir, page, (x0, y0, x1, y1), (pw, ph), frac)


def parse_source_range(q: Query, facts: DocumentFacts) -> SourceRange | InputRejected:
    """?file=&lo=&hi= of GET /api/snippet and /api/overlaps: a file in the tree (source_file), whose lines are read
    before lo and hi are parsed as integers (int() of the text) and checked against them."""
    f = source_file(query_first(q, "file", ""), facts.root, facts.state)
    if isinstance(f, InputRejected):
        return f
    lines = facts.lines(f)
    try:
        lo = int(query_first(q, "lo", "") or "")
        hi = int(query_first(q, "hi", "") or "")
    except ValueError:
        return InputRejected("lo·hi 는 정수여야 합니다.", "not_integer")
    if not 1 <= lo <= hi <= len(lines):
        return InputRejected("줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (len(lines), lo, hi), "range_outside_file")
    return SourceRange(f, lines, lo, hi)


def parse_snippet(q: Query, facts: DocumentFacts) -> SourceRange | InputRejected:
    """GET /api/snippet: refused for a view-only document (it has no source lines), else parse_source_range."""
    if facts.is_pdf:
        return InputRejected("보기 전용 문서(%s)에는 원문 줄이 없습니다." % facts.key, "no_source_lines")
    return parse_source_range(q, facts)
