"""Resolve a PDF drag to a source range or a view-only region."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, TypeAlias

from limn.pins.editing.values import PDF_QUOTE_MAX
from limn.pins.element import PinElement
from limn.pins.location import figure, source
from limn.pins.location.mapping import (
    BOX_LIMIT,
    Box,
    MarkPiece,
    Traced,
    carry_range,
    norm,
    snippet,
    trace_range,
    truncate_quote,
)
from limn.pins.location.range import RangeBoxes
from limn.pins.location.source import TokenCache
from limn.pins.needs import BuildAnswers, BuildOnScreen
from limn.platform.files import ManuscriptFile, file_in_tree, tex_lines
from limn.runtime.documents import Doc, to_source


class Selection(Protocol):
    """A validated drag (limn.pins.location.input.PickRequest): the page directory it is traced in, the page (1-based), the box
    (x0, y0, x1, y1) in points clamped to the page, the page size (width, height) in points, the viewer's frac as
    sent (None if absent), and every page of that build."""

    @property
    def pdir(self) -> Path:
        """The page directory on screen at drag time."""
        ...

    @property
    def page(self) -> int:
        """The page, 1-based."""
        ...

    @property
    def box(self) -> tuple[float, float, float, float]:
        """x0, y0, x1, y1 in points."""
        ...

    @property
    def size(self) -> tuple[float, float]:
        """The page's width and height in points."""
        ...

    @property
    def frac(self) -> list[float] | None:
        """The viewer's page-relative box, or None."""
        ...

    @property
    def pages(self) -> Sequence[tuple[float, float]]:
        """Every page of the build dragged on, (width, height) in points, page 1 first: the mark's pieces are
        measured against the page each one is on, which is not always the page dragged on."""
        ...


@dataclass(frozen=True)
class PickContext:
    """What resolving a selection needs from the instance: the manuscript root (a SyncTeX answer outside it is
    refused), the float environments of the range ladder (--float-envs), the state folder (for the "PDF older than the
    manuscript" check, and never part of the tree), the process's token-weight cache, the overlaps of a range with the
    stored open pins (file, lo, hi) -> [{"id", "lo", "hi", "rel"}], and build-owned queries for the requested
    publication's assets, status and detached figure selection - the run's injected bundle, required of every caller."""

    root: Path
    envs: Sequence[str]
    state: Path
    tokens: TokenCache
    overlaps: Callable[[str, int, int], list[dict[str, Any]]]
    builds: BuildAnswers


@dataclass(frozen=True)
class PageOnScreen:
    """The pages an answer measures its marks against: the name of the page directory on screen and every page of
    that build as (width, height) in points, page 1 first.

    A snippet names no page - it is a file and a line range - so it takes the build on screen with all of its pages
    and measures each piece of a mark against the page that piece is on. One size for the whole answer would misplace
    every mark on a document whose pages differ in size (a landscape appendix, an \\includepdf page) and would answer
    fractions a pick, which knows the page dragged on, does not. A document with no pages has none of this and
    answers no marks (limn.pins.location.http.snippet)."""

    build: str
    pages: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Picked:
    """A selection traced to lines of a manuscript file: the file (inside the tree), the page, the range the paths
    agreed on (limn.pins.location.mapping.Traced), the file's line count and the chosen range's text, the viewer's frac as sent, the
    region's printed text as a short quote, the stored open pins that range overlaps, and the page directory it was
    traced in. stale: the manuscript is newer than that build's PDF (by more than 2 s) and the answer is not SyncTeX's
    range read against that build's own lines and found standing whole in the file now - the one case where a rebuild
    and a second pick would answer the same lines; building: a LaTeX build is running now. boxes: where the chosen
    range prints on that build's pages (range_boxes), empty when there is no answer - the pin's mark is then the
    dragged rectangle, as it was before marks followed the range. The location feature's HTTP answer turns this into
    the pick body."""

    file: Path
    page: int
    traced: Traced
    n_lines: int
    snippet: str
    frac: list[float] | None
    quote: str
    overlaps: list[dict[str, Any]]
    pdf_build: str
    stale: bool
    building: bool
    boxes: tuple[MarkPiece, ...] = ()


@dataclass(frozen=True)
class PickedRegion:
    """A selection on a document whose pins are regions: its key, the page and page-relative box (frac), the PDF's
    path from the manuscript root and file name (for a document with an element map, the PDF the map of the drag's
    build names), the region's printed text as a quote and its length, and the page directory. blank: the region has
    no printed text (a figure or scan); redrawing: the pages are being redrawn now. el, path_names and fallback are set
    for a drag on a figure document that fell back to the region: the element it chose, if any, the names of that
    element's path, and why (figure.FigureFallback)."""

    doc: str
    page: int
    frac: list[float]
    pdf: str
    name: str
    quote: str
    n_chars: int
    blank: bool
    redrawing: bool
    pdf_build: str
    el: PinElement | None = None
    fallback: figure.FigureFallbackReason | None = None
    path_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeneratedFile:
    """SyncTeX points into a generated file (a .bbl or .bib, by its suffix): the fix belongs in the .bib or the text."""

    suffix: str


@dataclass(frozen=True)
class SynctexOutside:
    """SyncTeX points at a file that is not in the manuscript tree (path as mapped back from the build copy)."""

    path: Path


@dataclass(frozen=True)
class SourceUnreadable:
    """The source file the selection lands in has no readable UTF-8 lines."""

    path: Path


@dataclass(frozen=True)
class NoSourceHere:
    """Neither SyncTeX nor the region's text leads to a line of the file."""


# Why a selection is not traced to manuscript lines; each is answered with its own 200 {"error", "reason"} body
# (limn.pins.location.http.PICK_REFUSALS).
PickRefusal: TypeAlias = GeneratedFile | SynctexOutside | SourceUnreadable | NoSourceHere


def pick(D: Doc, request: Selection, ctx: PickContext) -> Picked | figure.PickedElement | PickedRegion | PickRefusal:
    """Dragged region -> source line range + range ladder, for document D and a selection parsed by
    limn.pins.location.input.parse_pick: the region of a document whose pins are regions (D.view_only;
    PickedRegion), the traced range (Picked), a figure element's lines (figure.PickedElement), or why the region cannot
    be traced to a manuscript line (PickRefusal).

    A figure document is traced through its build's element map first (location.figure.pick_figure, no pdftotext or
    SyncTeX); when that gives no lines, the region answer carries its element and reason. The map's lines are carried
    to the script as it is now the same way SyncTeX's are below, from that build's source record.

    This is the shell: it runs pdftotext and SyncTeX on the build's PDF, maps SyncTeX's file back to the checkout,
    reads the file and weighs the region's tokens, then lets limn.pins.location.mapping.trace_range choose between the two paths.
    The build facts (a manuscript newer than the PDF, a running LaTeX build) and the overlaps are read after that.

    SyncTeX's lines are numbers in the file as that build read it. When the build kept those lines (its source record,
    BuildOnScreen.built_lines), the range is first carried over to the file as it is now (mapping.carry_range), so an
    edit made since the build does not put the answer on whatever moved into those numbers. A range whose text is gone
    leaves SyncTeX without an answer: the text path may still find the words, and NoSourceHere is the answer when it
    does not. A build without the record (made by an older Limn) is answered with SyncTeX's numbers as they are.

    The page directory is the build on screen at drag time (pdf_build, META.pages_build). A drag made after a rebuild
    finishes but before the viewer switches pages uses coordinates from the old layout, so it's traced back
    against that build's PDF and returned as pdf_build in the response - the viewer carries that value
    through unchanged when saving the pin (/api/pin) to record "which build's coordinates these are" (§Position estimation).

    The last step runs SyncTeX the other way (range_boxes) and answers where the chosen range prints on that build's
    pages, so the mark the person sees covers the lines the agent receives (docs/adr/0045-pin-marks-follow-the-range.md)."""
    pdir, page, box, (pw, ph), frac = request.pdir, request.page, request.box, request.size, request.frac
    x0, y0, x1, y1 = box
    publication = ctx.builds.publication(D, pdir.name, ctx.state)
    fallback: figure.FigureFallback | None = None
    if D.has_element_map:
        on_map = figure.pick_figure(
            D,
            page,
            box,
            (pw, ph),
            frac,
            pdir,
            ctx.builds.selection(D, pdir.name, page, figure.drag_frac(box, (pw, ph))),
            ctx.root,
            ctx.state,
            ctx.overlaps,
            publication.running,
            publication.built_lines,
        )
        if isinstance(on_map, figure.PickedElement):
            return on_map
        fallback = on_map
    pdf = publication.pdf
    rtext = source.region_text(pdf, page, x0, y0, x1, y1)
    if fallback is not None:
        region = _pick_region(D, pdir, page, box, (pw, ph), frac, rtext, ctx.root, publication)
        return replace(region, el=fallback.el, fallback=fallback.reason, path_names=fallback.path_names)
    if D.view_only:
        return _pick_region(D, pdir, page, (x0, y0, x1, y1), (pw, ph), frac, rtext, ctx.root, publication)
    sy = source.by_synctex(pdf, page, x0, y0, x1, y1)

    src = to_source(D, sy[0]) if sy else D.main
    if src.suffix in (".bbl", ".bib"):
        return GeneratedFile(src.suffix)
    found = file_in_tree(str(src), ctx.root, ctx.state)
    if not isinstance(found, ManuscriptFile):
        return SynctexOutside(src)
    lines = tex_lines(found)
    if not lines:
        return SourceUnreadable(found.path)
    # SyncTeX numbers the lines that build read; everything below works on the file as it is now.
    synctex = (sy[1], sy[2]) if sy else None
    stands = False
    # Read whichever path wins: the forward pass below needs that build's lines even when SyncTeX gave no range and
    # the region's words placed the drag.
    built = publication.built_lines(found.path)
    if synctex is not None and built is not None:
        carried = carry_range(built, lines, synctex[0], synctex[1])
        synctex = None if carried is None else (carried.lo, carried.hi)
        stands = carried is not None and carried.whole
    tw = ctx.tokens.weights(rtext, lines, source.file_key(found))
    traced = trace_range(tw, lines, synctex, ctx.envs)
    if traced is None:
        return NoSourceHere()
    marks = range_boxes(D, found.path, built, lines, pdf, request.pages)

    return Picked(
        file=found.path,
        page=page,
        traced=traced,
        n_lines=len(lines),
        snippet=snippet(lines, traced.lo, traced.hi),
        frac=frac,
        quote=truncate_quote(norm(rtext), PDF_QUOTE_MAX),
        overlaps=ctx.overlaps(str(found), traced.lo, traced.hi),
        pdf_build=pdir.name,
        stale=publication.stale and not (stands and traced.via == "synctex"),
        building=publication.latex_running,
        boxes=marks(traced.lo, traced.hi),
    )


def range_boxes(
    D: Doc,
    file: Path,
    built: Sequence[str] | None,
    now: Sequence[str],
    pdf: Path,
    pages: Sequence[tuple[float, float]],
) -> RangeBoxes:
    """Where a range of manuscript file `file` prints on `pdf`, bound to the facts of one answer: (lo, hi) -> the
    mark's pieces, empty when there is none. `built` is the file as the build whose PDF this is read it (None when
    that build kept no record), `now` the file as it is today - the same order as source.boxes_for_range takes them,
    because both are lines of one file and a swap would type-check - and `pages` every page of that build, so each
    piece can be measured against the page it is on.

    Both answers that carry a mark bind it here - POST /api/pick for its default range (above) and GET /api/snippet
    once per rung (service.PinLocationService.snippet) - so the two cannot drift: the PDF, the name the build copy
    gives the file, the lines that build read and the page sizes are chosen once, in one place, and the computation
    itself is shared (source.boxes_for_range). Binding also keeps the cost to one read of the build's facts per
    answer, not one per rung. The mark's piece count is BOX_LIMIT for both; a reader that wants another cap calls the
    computation directly (docs/adr/0045-pin-marks-follow-the-range.md).

    A line is read from SyncTeX once per answer, not once per rung: the ladder's rungs nest, so a snippet's three
    rungs ask for the drag's own line three times and for the paragraph's lines twice, and each call is a process
    (13 ms measured on a 35-page document). The memo lives in this binding, so it is gone when the answer is - a GET
    changes nothing that outlives it, and a cache across requests is the pin listing's to add, not this route's."""
    tex = source.build_copy_name(D.build, D.src, file)
    seen: dict[tuple[str, int], list[Box]] = {}

    def view(on: Path, named: str, line: int) -> list[Box]:
        """That line's boxes, read once per (file name, line) for this answer."""
        key = (named, line)
        if key not in seen:
            seen[key] = source.synctex_view(on, named, line)
        return seen[key]

    def pieces(lo: int, hi: int) -> tuple[MarkPiece, ...]:
        """The pieces of lines lo..hi, each as fractions of the page it prints on."""
        return source.boxes_for_range(pdf, tex, built, now, lo, hi, pages, BOX_LIMIT, view)

    return pieces


def _pick_region(
    D: Doc,
    pdir: Path,
    page: int,
    box: tuple[float, float, float, float],
    size: tuple[float, float],
    frac: list[float] | None,
    rtext: str,
    root: Path,
    publication: BuildOnScreen,
) -> PickedRegion:
    """pick for a document whose pins are regions - only page/region and the region's text (pdftotext), no SyncTeX.
    If frac wasn't sent (agent curl), it's built from the coordinates - for such a pin, the region is the whole
    location. The build owner supplies the display PDF, named relative to the manuscript root.
    This function does not interpret a map or choose another publication."""
    x0, y0, x1, y1 = box
    pw, ph = size
    if frac is None:
        frac = [x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph]
    text = norm(rtext)
    pdf, name = _region_pdf(D, root, publication)
    return PickedRegion(
        doc=D.key,
        page=page,
        frac=frac,
        pdf=pdf,
        name=name,
        quote=truncate_quote(text, PDF_QUOTE_MAX),
        n_chars=len(text),
        blank=not text,
        redrawing=publication.running,
        pdf_build=pdir.name,
    )


def _region_pdf(D: Doc, root: Path, publication: BuildOnScreen) -> tuple[str, str]:
    """Display the selected publication's region PDF without deriving artifact names."""
    named = publication.region_pdf
    if D.has_element_map and named != D.main:
        try:
            return str(named.relative_to(root.resolve())), named.name
        except (ValueError, OSError, RuntimeError):
            return str(named), named.name
    return D.rel_path(), D.main.name
