"""Request-local source and build facts for a selected runtime document."""

from pathlib import Path

from limn.builds import BuildView
from limn.platform.files import ManuscriptFile, tex_lines
from limn.runtime.documents import Doc

_DEFAULT_BUILDS = BuildView()


class DocumentFacts:
    """limn.web.parse.DocumentFacts for document D: what the location parsers read from this machine's disk - the
    manuscript tree root and the state folder the tree never includes, a file's lines, the pages of a build of D
    (sized at dpi). The composition root makes one per
    request (server.document_facts); every method reads at call time."""

    def __init__(self, D: Doc, root: Path, state: Path, dpi: int, builds: BuildView = _DEFAULT_BUILDS) -> None:
        """Bind the document, the manuscript root, the state folder and the dpi the page images were rendered at."""
        self._doc, self._root, self._state, self._dpi, self._builds = D, root, state, dpi, builds

    @property
    def key(self) -> str:
        """The document key."""
        return self._doc.key

    @property
    def view_only(self) -> bool:
        """True when D's pins are page regions only (Doc.view_only): the parsers refuse file/lo/hi and snippets."""
        return self._doc.view_only

    @property
    def pdf(self) -> Path:
        """The PDF a region pin on D records: a view-only document's own PDF (its main file); for a document with an
        element map, the PDF named by the map of the build on screen (limn.builds.artifacts.build_figure_pdf), or the map file
        itself before an import has published a loadable map."""
        if self._doc.has_element_map:
            named = self._builds.figure_pdf(self._doc, self._builds.current_pages(self._doc).name)
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
        return len(self._builds.page_metadata(self._builds.pages_for(self._doc, name), self._dpi))

    def current_build(self) -> str:
        """The name of D's page directory on screen."""
        return self._builds.current_pages(self._doc).name

    def valid_build_name(self, value: object) -> bool:
        """Return whether ``value`` names a page directory."""
        return self._builds.valid_name(value)

    def pick_pages(self, name: str | None) -> tuple[Path, list[tuple[float, float]]] | None:
        """(page directory, [(width, height) in points]) of build `name` of D - or the one on screen for None - or None
        when name is a page directory of D that is gone."""
        if name is not None and not (self._doc.dir / name).is_dir():
            return None
        pdir = self._builds.pages_for(self._doc, name) if name is not None else self._builds.current_pages(self._doc)
        return pdir, [(p["pt_w"], p["pt_h"]) for p in self._builds.page_metadata(pdir, self._dpi)]
