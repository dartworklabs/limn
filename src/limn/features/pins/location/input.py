"""POST /api/pick boundary values and validation."""

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from limn.build import valid_build_name
from limn.pins.shapes import is_finite_num
from limn.web.errors import InputRejected
from limn.web.parse import PDF_BUILD_REFUSAL, DocumentFacts, Json, int_field, num_field


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
