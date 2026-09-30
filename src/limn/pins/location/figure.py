"""The figure branch of POST /api/pick: a drag on a figure document traced through its build's element map to the
lines of code that drew the element (the ladder: docs/handbook/domain.md §그림 문서의 요소 pick; the answers:
docs/handbook/api.md §그림 문서의 pick·핀).

resolve.pick sends a figure document here before anything else. The map comes from the composition root
(PickContext.figure_map: the pick's own build's copy, parsed once per build); which element and which ladder are
limn.builds.figure_map's pure rules (pick_element, ladder_scopes, element_kind) and element_rungs below. This module reads
only the chosen element's source file, through the checked-file helpers and only inside the document's folder, and
never the PDF. What it cannot answer with lines it answers with a FigureFallback, which resolve.pick turns into the
region answer. No HTTP here: location.http shapes every body.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, TypeAlias

from limn.builds import (
    ElementPick,
    FigureMap,
    MapElement,
    MapPage,
    MapRejected,
    element_kind,
    ladder_scopes,
    pick_element,
)
from limn.pins.element import ElementImpl, PinElement
from limn.pins.location.mapping import snippet
from limn.platform.files import ManuscriptFile, file_in_tree, tex_lines, tree_part
from limn.runtime.documents import Doc

# Why a drag on a figure is answered with the region body instead of lines; location.http.PICK_WARNINGS words each.
FigureFallbackReason: TypeAlias = Literal["figure_map_unavailable", "element_without_source"]


@dataclass(frozen=True)
class FigureFallback:
    """A drag on a figure that cannot be given code lines: why, and the element it chose when it chose one."""

    reason: FigureFallbackReason
    el: PinElement | None


@dataclass(frozen=True)
class Rung:
    """One range-ladder rung of a map pick: its level name ("el", "el2", ..., "fig"), the lines lo..hi of the chosen
    element's file that drew its element, the name shown for it (the element's label, else part, else id), those lines
    as a snippet, the element as a pin records it, and the level names merged into it (outer rungs with the same
    lines)."""

    level: str
    lo: int
    hi: int
    label: str
    snippet: str
    el: PinElement
    merged: tuple[str, ...] = ()


@dataclass(frozen=True)
class PickedElement:
    """A drag on a figure traced through its build's map: the chosen element's source file (inside the manuscript tree
    and the document's folder) and its line count, the page, the viewer's frac as sent, the pin kind (element_kind),
    the element's cover of the drag (score), the ladder rungs (the chosen element's own first - the default), the quote
    (the element's label or ""), the element as a pin records it, the stored open pins the default rung overlaps, the
    page directory it was traced in, and whether the pages are being redrawn now."""

    file: Path
    n_lines: int
    page: int
    frac: list[float] | None
    kind: str
    score: float
    rungs: tuple[Rung, ...]
    quote: str
    el: PinElement
    overlaps: list[dict[str, Any]]
    pdf_build: str
    redrawing: bool


def drag_frac(box: tuple[float, float, float, float], size: tuple[float, float]) -> tuple[float, float, float, float]:
    """The drag box (x0, y0, x1, y1 in points, already clamped to the page) as page fractions [x, y, w, h]; the point
    (0, 0) without area when the page has no size to divide by."""
    (x0, y0, x1, y1), (pw, ph) = box, size
    if pw <= 0 or ph <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph)


def pin_element(page: MapPage, el: MapElement) -> PinElement:
    """el of page as a pin records it (limn.pins.element): its id, the ids from the page root down to it, its label and
    part, its shared implementation's file and lines when the map names them, and its box on this build. The parser
    keeps an empty label or part as "" (limn.builds.figure_map.parse_map); a pin stores that as absent, like a name the map does
    not give, so "" never reaches a record or an answer."""
    chain = (el, *page.ancestors(el))
    impl = None if el.impl is None else ElementImpl(el.impl.file, el.impl.lo, el.impl.hi)
    return PinElement(el.id, tuple(e.id for e in reversed(chain)), el.label or None, el.part or None, impl, el.frac)


def element_rungs(page: MapPage, pick: ElementPick, lines: Sequence[str]) -> tuple[Rung, ...]:
    """The range ladder of a map pick in the chosen element's source file, whose current lines are `lines`: one rung per
    ladder element (level names from ladder_scopes), nearest first, for each element whose src names that same file
    and fits in it (1 <= lo <= hi <= len(lines)). A rung with the same lines as an earlier one merges into it: the
    earlier, inner rung stays - its element is the more precise answer - and lists the later level name under merged.
    Empty when the chosen element itself has no src or its lines do not fit: the pick then falls back to the region."""
    chosen = pick.chosen
    if chosen.src is None:
        return ()
    file = chosen.src.file
    out: list[Rung] = []
    for level, el in zip(ladder_scopes(pick.ladder), pick.ladder, strict=True):
        ref = el.src
        if ref is None or ref.file != file or not 1 <= ref.lo <= ref.hi <= len(lines):
            continue
        same = next((i for i, r in enumerate(out) if (r.lo, r.hi) == (ref.lo, ref.hi)), None)
        if same is not None:
            out[same] = replace(out[same], merged=(*out[same].merged, level))
            continue
        name = el.label or el.part or el.id
        out.append(Rung(level, ref.lo, ref.hi, name, snippet(lines, ref.lo, ref.hi), pin_element(page, el)))
    return tuple(out) if out and out[0].el.id == chosen.id else ()


def read_source(D: Doc, rel: str, root: Path, state: Path) -> tuple[ManuscriptFile, list[str]] | None:
    """The checked source file a map names (rel, relative to the document's folder D.src) and its lines read now, or
    None: not a regular file inside the manuscript tree (limn.platform.files.file_in_tree), not inside D.src once symlinks are
    resolved (tree_part, which also keeps the state folder and dot-named parts out), or no readable UTF-8 lines.

    The folder check is made here, on every read, and nowhere earlier: the map's parse (limn.builds.figure_map.parse_map) judges a
    source path by its shape only, so the run's cached map (limn.builds.BuildMapCache) says nothing about where a
    script leads. A script that links out of the folder - from the start or since the map was written - is refused
    now and costs only its own elements their lines; the answer is the same from a warm cache and a cold one."""
    found = file_in_tree(str(D.src / rel), root, state)
    if not isinstance(found, ManuscriptFile) or tree_part(found.path, D.src, state) is None:
        return None
    lines = tex_lines(found)
    return (found, lines) if lines else None


def pick_figure(
    D: Doc,
    page_no: int,
    box: tuple[float, float, float, float],
    size: tuple[float, float],
    frac: list[float] | None,
    pdir: Path,
    fmap: FigureMap | MapRejected | None,
    root: Path,
    state: Path,
    overlaps: Callable[[str, int, int], list[dict[str, Any]]],
    redrawing: bool,
) -> PickedElement | FigureFallback:
    """A drag on figure document D's page page_no (box in points, size the page's, frac the viewer's as sent) traced
    through fmap, the map of the page directory pdir it was made on: the element's lines (PickedElement), or why not
    (FigureFallback) - no loadable map or no such page in it (figure_map_unavailable, no element), or a chosen element
    whose src is missing, unreadable, outside D.src or longer than its file now (element_without_source, with that
    element). overlaps gives the stored open pins the default rung overlaps; redrawing says the pages are being
    redrawn. Reads the chosen element's source file once; never the PDF."""
    if not isinstance(fmap, FigureMap):
        return FigureFallback("figure_map_unavailable", None)
    page = fmap.page(page_no)
    if page is None:
        return FigureFallback("figure_map_unavailable", None)
    pick = pick_element(page, drag_frac(box, size))
    chosen = pick.chosen
    source = read_source(D, chosen.src.file, root, state) if chosen.src is not None else None
    rungs = element_rungs(page, pick, source[1]) if source is not None else ()
    if source is None or not rungs:
        return FigureFallback("element_without_source", pin_element(page, chosen))
    found, lines = source
    first = rungs[0]
    return PickedElement(
        file=found.path,
        n_lines=len(lines),
        page=page_no,
        frac=frac,
        kind=element_kind(chosen, chosen.id == page.root().id),
        score=pick.score,
        rungs=rungs,
        quote=chosen.label or "",
        el=first.el,
        overlaps=overlaps(str(found), first.lo, first.hi),
        pdf_build=pdir.name,
        redrawing=redrawing,
    )
