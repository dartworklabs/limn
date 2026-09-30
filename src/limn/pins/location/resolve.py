"""Resolve a PDF drag to a source range or a view-only region."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, TypeAlias

from limn.builds import BuildView, FigureMap, MapRejected, build_figure_pdf
from limn.pins.editing.values import PDF_QUOTE_MAX
from limn.pins.element import PinElement
from limn.pins.location import figure, source
from limn.pins.location.mapping import Traced, norm, snippet, trace_range, truncate_quote
from limn.pins.location.source import TokenCache
from limn.platform.files import ManuscriptFile, file_in_tree, tex_lines
from limn.runtime.documents import Doc, to_source

_DEFAULT_BUILDS = BuildView()
# How the composition root reads the element map of a build (page directory name) of a figure document: the run's cache.
FigureMapLookup: TypeAlias = Callable[[Doc, str], FigureMap | MapRejected | None]


class Selection(Protocol):
    """A validated drag (limn.pins.location.input.PickRequest): the page directory it is traced in, the page (1-based), the box
    (x0, y0, x1, y1) in points clamped to the page, the page size (width, height) in points, and the viewer's frac as
    sent (None if absent)."""

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


@dataclass(frozen=True)
class PickContext:
    """What resolving a selection needs from the instance: the manuscript root (a SyncTeX answer outside it is
    refused), the float environments of the range ladder (--float-envs), the state folder (for the "PDF older than the
    manuscript" check, and never part of the tree), the process's token-weight cache, the overlaps of a range with the
    stored open pins (file, lo, hi) -> [{"id", "lo", "hi", "rel"}], and figure_map, the element map of a build of a
    figure document by page directory name (the composition root's per-run cache: a map copy is parsed once per run, for
    the pick and for the region it falls back to alike)."""

    root: Path
    envs: Sequence[str]
    state: Path
    tokens: TokenCache
    overlaps: Callable[[str, int, int], list[dict[str, Any]]]
    figure_map: FigureMapLookup
    builds: BuildView = BuildView()


@dataclass(frozen=True)
class Picked:
    """A selection traced to lines of a manuscript file: the file (inside the tree), the page, the range the paths
    agreed on (limn.pins.location.mapping.Traced), the file's line count and the chosen range's text, the viewer's frac as sent, the
    region's printed text as a short quote, the stored open pins that range overlaps, and the page directory it was
    traced in. stale: the manuscript is newer than that build's PDF (by more than 2 s); building: a LaTeX build is
    running now. The location feature's HTTP answer turns this into the pick body."""

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


@dataclass(frozen=True)
class PickedRegion:
    """A selection on a document whose pins are regions: its key, the page and page-relative box (frac), the PDF's
    path from the manuscript root and file name (for a document with an element map, the PDF the map of the drag's
    build names), the region's printed text as a quote and its length, and the page directory. blank: the region has
    no printed text (a figure or scan); redrawing: the pages are being redrawn now. el and fallback are set for a drag
    on a figure document that fell back to the region: the element it chose, if any, and why (figure.FigureFallback)."""

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
    SyncTeX); when that gives no lines, the region answer carries its element and reason.

    This is the shell: it runs pdftotext and SyncTeX on the build's PDF, maps SyncTeX's file back to the checkout,
    reads the file and weighs the region's tokens, then lets limn.pins.location.mapping.trace_range choose between the two paths.
    The build facts (a manuscript newer than the PDF, a running LaTeX build) and the overlaps are read after that.

    The page directory is the build on screen at drag time (pdf_build, META.pages_build). A drag made after a rebuild
    finishes but before the viewer switches pages uses coordinates from the old layout, so it's traced back
    against that build's PDF and returned as pdf_build in the response - the viewer carries that value
    through unchanged when saving the pin (/api/pin) to record "which build's coordinates these are" (§Position estimation)."""
    pdir, page, box, (pw, ph), frac = request.pdir, request.page, request.box, request.size, request.frac
    x0, y0, x1, y1 = box
    fallback: figure.FigureFallback | None = None
    if D.has_element_map:
        on_map = figure.pick_figure(
            D,
            page,
            box,
            (pw, ph),
            frac,
            pdir,
            ctx.figure_map(D, pdir.name),
            ctx.root,
            ctx.state,
            ctx.overlaps,
            ctx.builds.snapshot(D)["state"] == "running",
        )
        if isinstance(on_map, figure.PickedElement):
            return on_map
        fallback = on_map
    pdf = ctx.builds.current_pdf(D, pdir)
    rtext = source.region_text(pdf, page, x0, y0, x1, y1)
    if fallback is not None:
        region = _pick_region(D, pdir, page, box, (pw, ph), frac, rtext, ctx.root, ctx.builds, ctx.figure_map)
        return replace(region, el=fallback.el, fallback=fallback.reason)
    if D.view_only:
        return _pick_region(D, pdir, page, (x0, y0, x1, y1), (pw, ph), frac, rtext, ctx.root, ctx.builds, ctx.figure_map)
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
    tw = ctx.tokens.weights(rtext, lines, source.file_key(found))
    traced = trace_range(tw, lines, (sy[1], sy[2]) if sy else None, ctx.envs)
    if traced is None:
        return NoSourceHere()

    stale = ctx.builds.source_newer(D, ctx.state, pdir.name) > 2
    bstate = ctx.builds.snapshot(D)
    return Picked(
        file=found.path,
        page=page,
        traced=traced,
        n_lines=len(lines),
        snippet=snippet(lines, traced.lo, traced.hi),
        frac=frac,
        quote=truncate_quote(norm(rtext), 60),
        overlaps=ctx.overlaps(str(found), traced.lo, traced.hi),
        pdf_build=pdir.name,
        stale=stale,
        building=bstate["state"] == "running" and bstate["phase"] == "latex",
    )


def _pick_region(
    D: Doc,
    pdir: Path,
    page: int,
    box: tuple[float, float, float, float],
    size: tuple[float, float],
    frac: list[float] | None,
    rtext: str,
    root: Path,
    builds: BuildView,
    figure_map: FigureMapLookup,
) -> PickedRegion:
    """pick for a document whose pins are regions - only page/region and the region's text (pdftotext), no SyncTeX.
    If frac wasn't sent (agent curl), it's built from the coordinates - for such a pin, the region is the whole
    location. The PDF it names is _region_pdf's, relative to the manuscript root; figure_map is how a figure
    document's map is read (the run's cache), so the map a pick just used is not parsed again for the PDF's name."""
    x0, y0, x1, y1 = box
    pw, ph = size
    if frac is None:
        frac = [x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph]
    text = norm(rtext)
    bstate = builds.snapshot(D)
    pdf, name = _region_pdf(D, pdir, root, builds, figure_map)
    return PickedRegion(
        doc=D.key,
        page=page,
        frac=frac,
        pdf=pdf,
        name=name,
        quote=truncate_quote(text, PDF_QUOTE_MAX),
        n_chars=len(text),
        blank=not text,
        redrawing=bstate["state"] == "running",
        pdf_build=pdir.name,
    )


def _region_pdf(D: Doc, pdir: Path, root: Path, builds: BuildView, figure_map: FigureMapLookup) -> tuple[str, str]:
    """The PDF a region pick names, as (path from the manuscript root, file name). A view-only PDF names itself
    (Doc.rel_path). A document with an element map names the PDF the map of the drag's build (pdir) names
    (limn.builds.build_figure_pdf, the map read through figure_map) - or its map file when that build has no loadable
    map or the map's PDF lies outside the document's folder, so no path outside it is ever named."""
    if D.has_element_map:
        named = build_figure_pdf(D, pdir.name, figure_map)
        if named is not None:
            try:
                return str(named.relative_to(root.resolve())), named.name
            except (ValueError, OSError, RuntimeError):
                return str(named), named.name
    return D.rel_path(), D.main.name
