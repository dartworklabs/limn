"""Interpret build storage into consumer answers at the build-owned I/O boundary."""

import os
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from limn.builds import artifacts, built_source
from limn.builds.contracts import (
    BuildHeading,
    DocumentBuild,
    DocumentBuildQueries,
    ElementFact,
    ElementFollower,
    ElementPosition,
    ElementSelection,
    Frac,
    MarkBinding,
    MarkBoxes,
    MarkComputation,
    MarkPieces,
    OutlineInput,
    PinBuildQueries,
    PositionHistory,
    Publication,
    RevisionBuildQueries,
    SelectionUnavailable,
)
from limn.builds.figure_map import (
    FigureMap,
    MapElement,
    MapPage,
    element_kind,
    figure_arrival,
    follow_element,
    ladder_scopes,
    map_source_files,
    pick_element,
)
from limn.platform.files import PATH_MAX_CHARS
from limn.platform.values import is_num
from limn.runtime.documents import Doc
from limn.web.parse import DocumentFacts

AUX_MAX_BYTES = 4 * 1024 * 1024


def history_pdf(doc: Doc, figure_map: FigureMap) -> Path | None:
    """The PDF figure_map names, as the path whose Git history is figure document doc's PDF: placed lexically from the
    folder doc's map was registered in (doc.registered_main's parent) - '..' parts folded, nothing resolved - and kept
    only when it lies strictly inside doc.registered_src with no dot-named part below it (the manuscript tree's rule,
    limn.platform.files.tree_part). None for an empty, absolute or over-long path or one holding a backslash or a NUL,
    as artifacts.figure_pdf refuses them. figure_pdf, through which the import reads the file, resolves symlinks; this
    asks the filesystem nothing, so a folder replaced by a symlink after startup cannot make another file's commits
    the document's history. Pure."""
    rel = figure_map.pdf
    if not rel or len(rel) > PATH_MAX_CHARS or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return None
    placed = Path(os.path.normpath(doc.registered_main.parent / rel))
    try:
        below = placed.relative_to(doc.registered_src)
    except ValueError:
        return None
    if not below.parts or any(part.startswith(".") for part in below.parts):
        return None
    return placed


def _epoch(value: str | None) -> float | None:
    """Decode a published local/ISO timestamp; malformed or absent stamps remain unknown."""
    if not value or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace(" ", "T", 1))
        return (parsed.astimezone() if parsed.tzinfo is None else parsed).timestamp()
    except ValueError:
        return None


def _same_source(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> bool:
    """Prefer source hashes, falling back to recorded mtimes within the legacy tolerance."""
    if not a or not b:
        return False
    if a.get("src_hash") and b.get("src_hash"):
        return bool(a["src_hash"] == b["src_hash"])
    ma, mb = a.get("src_mtime"), b.get("src_mtime")
    return is_num(ma) and is_num(mb) and abs(float(ma) - float(mb)) < 0.01


def position_basis(
    cur: str, history: Mapping[str, Mapping[str, Any]], mtime: float | None, built_at: float | None
) -> PositionHistory:
    """Interpret owned history without mutating it, including a missing current entry."""
    by = dict(history)
    by.setdefault(cur, {"src_mtime": mtime, "src_hash": None})
    if mtime is None and is_num(by[cur].get("src_mtime")):
        mtime = float(by[cur]["src_mtime"])
    exact = frozenset(name for name, entry in by.items() if _same_source(entry, by[cur]))
    return PositionHistory(cur, exact, built_at, mtime)


def _element(page: MapPage, el: MapElement) -> ElementFact:
    """Detach just the selected identity, source span and display-only implementation span, with the name a person
    reads for each element of its path (root first): its label, else its part, else ""."""
    source = None if el.src is None else (el.src.file, el.src.lo, el.src.hi)
    impl = None if el.impl is None else (el.impl.file, el.impl.lo, el.impl.hi)
    chain = tuple(reversed((el, *page.ancestors(el))))
    return ElementFact(
        el.id,
        tuple(e.id for e in chain),
        el.label or None,
        el.part or None,
        impl,
        el.frac,
        source,
        tuple(e.label or e.part or "" for e in chain),
    )


def select_element(fmap: FigureMap | None, page_no: int, frac: Frac) -> ElementSelection | SelectionUnavailable:
    """Select within an already-owned parsed map; return no graph or unrelated elements."""
    page = fmap.page(page_no) if fmap is not None else None
    if page is None:
        return SelectionUnavailable()
    pick = pick_element(page, frac)
    chosen = pick.chosen
    ladder = tuple(
        (level, _element(page, el)) for level, el in zip(ladder_scopes(pick.ladder), pick.ladder, strict=True)
    )
    return ElementSelection(
        _element(page, chosen),
        element_kind(chosen, chosen.id == page.root().id),
        pick.score,
        ladder,
        pick.fill,
        pick.rival,
    )


def element_follower(fmap: FigureMap | None) -> ElementFollower | None:
    """Bind one published map privately; queries return only the completed element position."""
    if fmap is None:
        return None

    def follow(identifier: str, page: int, frac: Frac) -> ElementPosition:
        """Follow one stored element without exposing the map or reading any source file."""
        got = follow_element(fmap, identifier, page, frac)
        return ElementPosition(got.page, got.frac, got.sync)

    return follow


def no_marks(
    _doc: Doc,
    _file: Path,
    _built: Sequence[str] | None,
    _now: Sequence[str],
    _pdf: Path,
    _pages: Sequence[tuple[float, float]],
) -> MarkBinding:
    """The forward pass of a run whose composition root injected none (the standalone query bindings and the tests of
    other slices): no range is read back into the build's lines, so no answer carries a mark, nothing is kept and no
    process is run."""
    return (lambda _lo, _hi: None, lambda _lo, _hi: ())


def own_marks() -> Callable[[], artifacts.RangeBoxCache]:
    """A mark cache private to one query binding, for a caller that supplies no run-wide one."""
    cache = artifacts.RangeBoxCache()
    return lambda: cache


@dataclass(frozen=True)
class BuildQueries:
    """Build-owned implementation of purpose-specific query bindings for one run."""

    maps: Callable[[], artifacts.BuildMapCache]
    marks: Callable[[], artifacts.RangeBoxCache] = field(default_factory=own_marks)
    compute_marks: MarkComputation = no_marks

    def published_head(self, doc: Doc) -> str:
        """Answer synchronization's publication identity; absent/unreadable markers are unknown."""
        return artifacts.read_head(doc) or ""

    def heading(self, doc: Doc) -> BuildHeading:
        """Interpret optional stamps here so consumers never name marker files."""
        return BuildHeading(artifacts.read_head(doc), artifacts.read_built_at(doc), artifacts.cur_pages(doc).name)

    def summary(self, doc: Doc, state: Path, dpi: int) -> DocumentBuild:
        """Complete the build-owned HTTP fragments without leaking internal state/history."""
        b = artifacts.state_snapshot(doc)
        pages = artifacts.cur_pages(doc)
        sm = artifacts.src_mtime(doc, state)
        stale = doc.builds_from_source and artifacts.source_newer(doc, state) > 2
        heading = self.heading(doc)
        brief = {
            "key": doc.key,
            "name": doc.name,
            "kind": doc.kind,
            "view_only": doc.view_only,
            "path": doc.rel_path(),
            "main": doc.main.name,
            "stale_build": stale,
            "src_mtime": sm,
            "building": doc.lock.locked(),
            "build": {"state": b["state"], "phase": b["phase"]},
            "build_seq": b.get("seq", 0),
            "last_state": (b.get("last") or {}).get("state"),
            "pages_build": pages.name,
            "n_pages": sum(1 for _ in pages.glob("page-*.png")) if pages.is_dir() else 0,
        }
        meta = {
            "pages": self.page_facts(doc, pages.name, artifacts.page_list(pages, dpi)),
            "built_at": heading.built_at if heading.built_at is not None else "?",
            "head": heading.head if heading.head is not None else "?",
            "building": brief["building"],
            "stale_build": stale,
            "src_mtime": sm,
            "build_src_mtime": artifacts.read_built_src_mtime(doc),
            "pages_build": pages.name,
            "build_seq": b.get("seq", 0),
            "last_build": deepcopy(b.get("last") or {"state": None, "errors": [], "finished_at": None, "seq": 0}),
            "build": {"state": b["state"], "phase": b["phase"], "started_at": b.get("started_at")},
        }
        return DocumentBuild(brief, meta)

    def page_facts(self, doc: Doc, build: str, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Meta's pages of build `build` with, on a figure document whose map for that build loads, what its map says of
        each page (in map order, after name and sizes): `figure` (the root element's id), `title` when the map has one,
        `verdict: false` when the page takes no verdict, and where the viewer arrives on a page with a figure body
        (figure_arrival): `figure_top`, and `figure_above` when an element ends above it. Pages the map does not name,
        and every page of any other document or of a map that does not load, keep {name, pt_w, pt_h}. Reads the map
        copy through the run's cache, and no file the map names."""
        if not doc.has_element_map:
            return pages
        fmap = self.maps().get(doc, build)
        if not isinstance(fmap, FigureMap):
            return pages
        for n, entry in enumerate(pages, 1):
            found = fmap.page(n)
            if found is None:
                continue
            entry["figure"] = found.figure
            if found.title is not None:
                entry["title"] = found.title
            if not found.takes_verdict:
                entry["verdict"] = False
            arrival = figure_arrival(found)
            if arrival is not None:
                entry["figure_top"] = arrival.top
                if arrival.above is not None:
                    entry["figure_above"] = arrival.above
        return pages

    def publication(self, doc: Doc, name: str, state: Path) -> Publication:
        """Bind pick assets and status to the requested publication, not pages.cur. Its built_lines reads that
        build's source record (built_source) for a manuscript file named by its checkout path."""
        pages = doc.dir / name

        def built_lines(file: Path) -> tuple[str, ...] | None:
            """The lines of manuscript file `file` as build `name` read it, or None when its record has none."""
            key = built_source.source_key(doc.src, file)
            return None if key is None else built_source.built_lines(pages, key)

        pdf = artifacts.cur_pdf(doc, pages)
        region = (
            artifacts.build_figure_pdf(doc, name, lambda d, n: self.maps().get(d, n)) if doc.has_element_map else None
        )
        b = artifacts.state_snapshot(doc)
        running = b["state"] == "running"
        return Publication(
            name,
            pages,
            pdf,
            region or doc.main,
            artifacts.source_newer(doc, state, name) > 2,
            running,
            running and b["phase"] == "latex",
            built_lines,
        )

    def position(self, doc: Doc) -> PositionHistory:
        """Normalize source equivalence inside builds; no history entry crosses the boundary."""
        return position_basis(
            artifacts.cur_pages(doc).name,
            artifacts.load_builds(doc)["by"],
            artifacts.read_built_src_mtime(doc),
            _epoch(artifacts.read_built_at(doc)),
        )

    def outline(self, doc: Doc) -> OutlineInput:
        """Read only the bounded, non-symlink auxiliary text paired with the current pages."""
        pages = artifacts.cur_pages(doc)
        text = ""
        if doc.builds_from_source:
            aux = pages / (doc.main.stem + ".aux")
            try:
                if not aux.is_symlink() and aux.stat().st_size <= AUX_MAX_BYTES:
                    text = aux.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        return OutlineInput(pages.name, text)

    def selection(self, doc: Doc, build: str, page: int, frac: Frac) -> ElementSelection | SelectionUnavailable:
        """Interpret a drag using exactly its build; cached maps do not authorize source reads."""
        fmap = self.maps().get(doc, build) if doc.has_element_map else None
        return select_element(fmap if isinstance(fmap, FigureMap) else None, page, frac)

    def page_root(self, doc: Doc, build: str, page: int, element: str) -> bool:
        """Whether element is the root - the figure - of page `page` (1-based) on the map build `build` of figure
        document doc published. False for a document without an element map, a build name that names no page
        directory, a build without a loadable map, and a map without that page: an unconfirmed root is never taken
        for one. Reads the map copy through the run's cache, and no file the map names."""
        if not doc.has_element_map:
            return False
        fmap = self.maps().get(doc, build)
        found = fmap.page(page) if isinstance(fmap, FigureMap) else None
        return found is not None and found.root().id == element

    def boxes(self, doc: Doc, dpi: int) -> MarkBoxes | None:
        """Where a line range of document doc prints on the build it has on screen, or None when nothing could print.

        None for a document whose pages no LaTeX build printed from the lines its pins point at - a figure document
        (its pins are lines of a drawing script and its marks come from its element map), a Markdown or text document
        (drawn in the browser, no pages at all), a view-only PDF (no lines) - and for a build that left no page to
        measure a mark against. The caller then answers the pins it always answered, without a single process.

        The build facts are read once here, for the whole answer: the page folder on screen, its PDF and its page
        sizes. What depends on the file - the lines that build read (its source record) and the file as it is today -
        is read on the first range of that file that is asked for, because the record can be tens of megabytes of
        JSON and a listing must read it once rather than once per pin. It is read even when the cache holds every
        range: a kept answer is keyed by the lines of the build the range is, and the file's own lines are what say
        which those are. That is the price of the key, and it is one read of the record per file per listing where
        the version-keyed cache could sometimes make none - but the viewer reads this route only when the pins file or
        the manuscript changed (viewer/js/documents/flow-polling.ts), and a changed manuscript missed every pin of
        the file before. A build that kept no record answers no mark: the range cannot be read back into the
        lines its numbers belong to, and half a range's boxes passed off as the range's would cover text the pin does
        not hold. A pick falls back to the build's numbers there; a stored pin does not, and such a build is replaced
        by the next rebuild (docs/adr/0049-pin-marks-follow-the-range.md).
        """
        if not doc.builds_from_source:
            return None
        pages = artifacts.cur_pages(doc)
        sizes = tuple((page["pt_w"], page["pt_h"]) for page in artifacts.page_sizes(pages, dpi))
        if not sizes:
            return None
        pdf = artifacts.cur_pdf(doc, pages)
        cache, compute = self.marks(), self.compute_marks
        askers: dict[str, MarkBinding | None] = {}

        def bind(file: str) -> MarkBinding | None:
            """The computation bound to that file's two line lists, read once for this answer; None when the build
            kept no record of the file or the file itself cannot be read as text."""
            key = built_source.source_key(doc.src, Path(file))
            built = None if key is None else built_source.built_lines(pages, key)
            if key is None or built is None:
                return None
            raw = built_source.read_below(doc.src, key, built_source.FILE_MAX_BYTES)
            now = None if raw is None else built_source.text_lines(raw)
            return None if now is None else compute(doc, Path(file), built, now, pdf, sizes)

        def answer(file: str, lo: int, hi: int) -> MarkPieces:
            """The run's answer for one range: the lines of the build that range is, then the cache's answer for
            those lines, computed only where it has none."""
            if file not in askers:
                askers[file] = bind(file)
            asker = askers[file]
            if asker is None:
                return ()
            in_build, pieces = asker
            found = in_build(lo, hi)
            if found is None:
                return ()
            key = (str(doc.dir), pages.name, file, dpi, found[0], found[1])
            return cache.answer(key, lambda: pieces(lo, hi))

        return answer

    def elements(self, doc: Doc) -> ElementFollower | None:
        """Snapshot one current map privately, or no lookup for a non-figure/invalid build."""
        if not doc.has_element_map:
            return None
        fmap = self.maps().get(doc, artifacts.cur_pages(doc).name)
        return element_follower(fmap if isinstance(fmap, FigureMap) else None)

    def history_files(self, doc: Doc) -> tuple[Path, ...] | None:
        """The files whose Git history is document doc's changes, chosen by what the document can do; None for a LaTeX
        document, whose history is its folder's manuscript suffixes instead (limn.revisions.core.revision_scope).

        - A document with an element map (a figure document), in this order: its map file, the PDF the map of the build
          on screen names (history_pdf: placed lexically under the folder the document was registered with, only when
          it lies inside it), and every script and shared component that map names, joined to doc.src as the map gives
          them (figure_map.map_source_files). Just the map file when the build on screen has no loadable map. Reads the
          map copy through the run's cache, and no file the map names; nothing here resolves a symlink.
        - A document the browser draws (a Markdown or text document): its own file alone, so another document's file in the
          same folder - a LaTeX main beside it - never enters its history, nor its file a LaTeX document's.
        - Any other document: None."""
        if doc.renders_in_browser:
            return (doc.main,)
        if not doc.has_element_map:
            return None
        fmap = self.maps().get(doc, artifacts.cur_pages(doc).name)
        if not isinstance(fmap, FigureMap):
            return (doc.main,)
        pdf = history_pdf(doc, fmap)
        named = tuple(doc.src / rel for rel in map_source_files(fmap))
        return (doc.main, *(() if pdf is None else (pdf,)), *named)

    def overlay(self, doc: Doc, dpi: int) -> dict[str, Any] | None:
        """The two builds figure document doc's changes view lays one over the other, as the JSON fragment
        {build, pages, prev_build, prev_pages}: the build on screen and its page images, and the build shown before it
        (artifacts.previous_pages) with its page images, or None and [] when that is not kept. Pages are
        artifacts.page_list's {name, pt_w, pt_h} at dpi, as meta's pages are. None for a document without an element
        map."""
        if not doc.has_element_map:
            return None
        cur = artifacts.cur_pages(doc)
        prev = artifacts.previous_pages(doc)
        return {
            "build": cur.name,
            "pages": artifacts.page_list(cur, dpi),
            "prev_build": None if prev is None else prev.name,
            "prev_pages": [] if prev is None else artifacts.page_list(prev, dpi),
        }

    def revisions(self, dpi: Callable[[], int]) -> RevisionBuildQueries:
        """Bind only the changes view's completed queries; dpi is read on each overlay, as the run's settings give it."""
        return RevisionBuildQueries(self.history_files, lambda doc: self.overlay(doc, dpi()))

    def documents(self) -> DocumentBuildQueries:
        """Bind only the document consumer's completed queries."""
        return DocumentBuildQueries(self.summary, self.outline)

    def pins(self) -> PinBuildQueries:
        """Bind only the pin consumer's completed queries."""
        return PinBuildQueries(
            self.publication,
            self.position,
            self.heading,
            self.selection,
            self.elements,
            self.document_facts,
            self.page_root,
        )

    def document_facts(self, doc: Doc, root: Path, state: Path, dpi: int) -> DocumentFacts:
        """Bind checked manuscript and published-page parsing without exposing marker layout."""
        from limn.builds.document_facts import DocumentFacts

        return DocumentFacts(doc, root, state, dpi, lambda d, b: self.maps().get(d, b))


def document_build_queries() -> DocumentBuildQueries:
    """Create standalone document queries; server assembly supplies its per-run bindings."""
    cache = artifacts.BuildMapCache()
    return BuildQueries(lambda: cache).documents()


def pin_build_queries() -> PinBuildQueries:
    """Create standalone pin queries, with a cache private to this binding."""
    cache = artifacts.BuildMapCache()
    return BuildQueries(lambda: cache).pins()
