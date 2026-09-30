"""Interpret build storage into consumer answers at the build-owned I/O boundary."""

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from limn.builds import artifacts
from limn.builds.contracts import (
    BuildHeading,
    DocumentBuild,
    DocumentBuildQueries,
    ElementFact,
    ElementFollower,
    ElementPosition,
    ElementSelection,
    Frac,
    OutlineInput,
    PinBuildQueries,
    PositionHistory,
    Publication,
    SelectionUnavailable,
)
from limn.builds.figure_map import (
    FigureMap,
    MapElement,
    MapPage,
    element_kind,
    follow_element,
    ladder_scopes,
    pick_element,
)
from limn.platform.values import is_num
from limn.runtime.documents import Doc
from limn.web.parse import DocumentFacts

AUX_MAX_BYTES = 4 * 1024 * 1024


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
    """Detach just the selected identity, source span and display-only implementation span."""
    source = None if el.src is None else (el.src.file, el.src.lo, el.src.hi)
    impl = None if el.impl is None else (el.impl.file, el.impl.lo, el.impl.hi)
    return ElementFact(
        el.id,
        tuple(e.id for e in reversed((el, *page.ancestors(el)))),
        el.label or None,
        el.part or None,
        impl,
        el.frac,
        source,
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
        _element(page, chosen), element_kind(chosen, chosen.id == page.root().id), pick.score, ladder
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


@dataclass(frozen=True)
class BuildQueries:
    """Build-owned implementation of purpose-specific query bindings for one run."""

    maps: Callable[[], artifacts.BuildMapCache]

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
            "pages": artifacts.page_list(pages, dpi),
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

    def publication(self, doc: Doc, name: str, state: Path) -> Publication:
        """Bind pick assets and status to the requested publication, not pages.cur."""
        pages = doc.dir / name
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

    def elements(self, doc: Doc) -> ElementFollower | None:
        """Snapshot one current map privately, or no lookup for a non-figure/invalid build."""
        if not doc.has_element_map:
            return None
        fmap = self.maps().get(doc, artifacts.cur_pages(doc).name)
        return element_follower(fmap if isinstance(fmap, FigureMap) else None)

    def documents(self) -> DocumentBuildQueries:
        """Bind only the document consumer's completed queries."""
        return DocumentBuildQueries(self.summary, self.outline)

    def pins(self) -> PinBuildQueries:
        """Bind only the pin consumer's completed queries."""
        return PinBuildQueries(
            self.publication, self.position, self.heading, self.selection, self.elements, self.document_facts
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
