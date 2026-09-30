"""Request-local source and build facts for a selected runtime document."""

from collections.abc import Callable
from pathlib import Path

from limn.builds import artifacts as build
from limn.builds.figure_map import FigureMap, MapRejected
from limn.platform.files import ManuscriptFile, tex_lines
from limn.runtime.documents import Doc


class DocumentFacts:
    """limn.web.parse.DocumentFacts for document D: what the location parsers read from this machine's disk - the
    manuscript tree root and the state folder the tree never includes, a file's lines, the pages of a build of D
    (sized at dpi). The composition root makes one per
    request (server.document_facts); every method reads at call time."""

    def __init__(
        self,
        D: Doc,
        root: Path,
        state: Path,
        dpi: int,
        figure_map: Callable[[Doc, str], FigureMap | MapRejected | None] = build.load_build_map,
    ) -> None:
        """Bind the document, the manuscript root, the state folder and the dpi the page images were rendered at.
        figure_map reads the map of a build of a figure document by page directory name: the composition root hands in
        the run's cache (server.figure_map); the default parses the build's copy on every call."""
        self._doc, self._root, self._state, self._dpi, self._figure_map = D, root, state, dpi, figure_map

    @property
    def key(self) -> str:
        """The document key."""
        return self._doc.key

    @property
    def has_element_map(self) -> bool:
        """The document is a figure with an element map (Doc.has_element_map): the location parsers keep a pin's el
        only there, and a body without file, lo or hi is a region pin on it."""
        return self._doc.has_element_map

    @property
    def view_only(self) -> bool:
        """True when D's pins are page regions only (Doc.view_only): the parsers refuse file/lo/hi and snippets."""
        return self._doc.view_only

    @property
    def pdf(self) -> Path:
        """The PDF a region pin on D records: a view-only document's own PDF (its main file); for a document with an
        element map, the PDF named by the map of the build on screen (limn.builds.artifacts.build_figure_pdf, the map
        read through the lookup this was made with), or the map file itself before an import has published a loadable
        map."""
        if self._doc.has_element_map:
            named = build.build_figure_pdf(self._doc, build.cur_pages(self._doc).name, self._figure_map)
            if named is not None:
                return named
        return self._doc.main

    @property
    def root(self) -> Path:
        """The manuscript tree."""
        return self._root

    @property
    def state(self) -> Path:
        """The instance's state folder (never part of the tree, limn.platform.files.tree_part)."""
        return self._state

    def lines(self, path: ManuscriptFile) -> list[str]:
        """The file's lines (limn.platform.files.tex_lines: [] when unreadable)."""
        return tex_lines(path)

    def page_count(self, name: str | None) -> int:
        """Pages of build `name` of D, or of the build on screen when name is None or gone (limn.builds.artifacts.pages_dir_for)."""
        return len(build.page_list(build.pages_dir_for(self._doc, name), self._dpi))

    def current_build(self) -> str:
        """The name of D's page directory on screen."""
        return build.cur_pages(self._doc).name

    def valid_build_name(self, value: object) -> bool:
        """Return whether ``value`` names a page directory."""
        return build.valid_build_name(value)

    def pick_pages(self, name: str | None) -> tuple[Path, list[tuple[float, float]]] | None:
        """(page directory, [(width, height) in points]) of build `name` of D - or the one on screen for None - or None
        when name is a page directory of D that is gone."""
        if name is not None and not (self._doc.dir / name).is_dir():
            return None
        pdir = build.pages_dir_for(self._doc, name) if name is not None else build.cur_pages(self._doc)
        return pdir, [(p["pt_w"], p["pt_h"]) for p in build.page_list(pdir, self._dpi)]
