"""The documents one viewer serves (docs/handbook/domain.md §여러 문서): a document, and what a lookup by key answers.

A single paper repo has several documents - the body, the review response, the cover letter. One viewer (one
address) switches between them by key (?doc=). The pin store is singular - pin numbers are unique across documents
so "handle #12" is unambiguous - while build, page images, PDF copy and build history live under a per-document
folder (Doc.dir). Every service that acts on a document takes it as an argument: nothing reads a "current document"
(docs/handbook/code-style-roadmap.md R5). A request that names a key the instance does not serve is answered with
the keys it does serve; silently falling back to the first document would attach a pin to the wrong document.

The lookups over the instance's documents (by key, by file, a pin's document, a request's document) take the list
as an argument; the list itself is the composition root's (server.DOCS). DocumentFacts is what the request parsers
read about a document from the disk, and to_source maps a SyncTeX path in a document's build copy back to the
manuscript.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from limn import build
from limn.files import tex_lines

DOC_KEY_RE = re.compile(r"[a-z0-9-]{1,24}")
DOC_NAME_MAX = 40
DOCS_MAX = 12
DEFAULT_DOC_KEY = "main"


class RunPaths(Protocol):
    """The instance's run paths a document reads (server.py's run settings C): read at every access, so a change to
    them (main() filling them in, a test pointing them elsewhere) is seen at once."""

    @property
    def src(self) -> Path:
        """--manuscript: the manuscript tree."""
        ...

    @property
    def main(self) -> Path:
        """The main .tex of an instance started without --doc."""
        ...

    @property
    def state(self) -> Path:
        """The instance state folder."""
        ...

    @property
    def build(self) -> Path:
        """The build copy of an instance started without --doc."""
        ...


def fresh_build_state() -> dict[str, Any]:
    """A document's build state before its first build (what GET /api/build reports then)."""
    return {
        "state": "idle",
        "phase": None,
        "started_at": None,
        "start_ts": None,
        "last_s": None,
        "pages": 0,
        "errors": [],
        "log_tail": "",
        "built_at": None,
        "seq": 0,
        "finished_at": None,
        "last": None,
        "head": None,
        "pull": None,
    }


class Doc:
    """One document. kind is 'tex' (LaTeX, lines traced back via SyncTeX) or 'pdf' (view-only - page/region only).

    paths are the instance's run paths (RunPaths), given at construction by the composition root. legacy=True means
    a single document started without --doc: its manuscript and build folders are the run paths' own (read on each
    access, so the legacy state-folder layout keeps working). root=True puts build artifacts at the state folder
    root (the same place as for a single document). Under --doc, only the LaTeX document keyed main gets this - so
    adding documents to a single-document instance keeps the body's build history (the source of location
    estimation) continuous. A Doc carries its own build lock, build state and its lock, history lock and src_mtime
    memo (limn.build.BuildDoc)."""

    def __init__(
        self,
        key: str,
        name: str,
        kind: str = "tex",
        src: Path | None = None,
        main: Path | None = None,
        legacy: bool = False,
        root: bool | None = None,
        lock: threading.Lock | None = None,
        bstate: dict[str, Any] | None = None,
        bstate_lock: threading.Lock | None = None,
        builds_lock: threading.Lock | None = None,
        mcache: list[Any] | None = None,
        *,
        paths: RunPaths,
    ) -> None:
        """A document; src/main are its build root and main file unless legacy (then the run paths' own)."""
        self.key, self.name, self.kind = key, name, kind
        self._src, self._main, self.legacy = src, main, legacy
        self.paths = paths
        self.root = legacy if root is None else root
        self.lock = lock or threading.Lock()
        self.bstate = bstate if bstate is not None else fresh_build_state()
        self.bstate_lock = bstate_lock or threading.Lock()
        self.builds_lock = builds_lock or threading.Lock()
        self.mcache = mcache if mcache is not None else [None, 0.0, 0.0]

    @property
    def src(self) -> Path:
        """Build root - the scope copied into the build copy. For view-only, the folder holding the PDF."""
        if self.legacy:
            return self.paths.src
        assert self._src is not None, "a document started with --doc has its own src"
        return self._src

    @property
    def main(self) -> Path:
        """The main .tex for LaTeX, or the PDF file for view-only."""
        if self.legacy:
            return self.paths.main
        assert self._main is not None, "a document started with --doc has its own main"
        return self._main

    @property
    def dir(self) -> Path:
        """Per-document state folder - page images, build history, built_at, etc."""
        return self.paths.state if self.root else self.paths.state / "docs" / self.key

    @property
    def build(self) -> Path:
        """The build copy of the manuscript."""
        return self.paths.build if self.legacy else self.dir / "build"

    @property
    def main_rel(self) -> Path:
        """The main file relative to src (just its name when it lies elsewhere)."""
        try:
            return self.main.relative_to(self.src)
        except ValueError:
            return Path(self.main.name)

    @property
    def out(self) -> Path:
        """The folder where latexmk runs and the PDF comes out. A --doc document runs in the folder holding
        its main .tex (the same as running latexmk there normally would - the build root before '::' is only
        the copy scope). A single document is the build root, as before."""
        return self.build if self.legacy else self.build / self.main_rel.parent

    @property
    def pdf_name(self) -> str:
        """Name of the PDF copy inside the page directory."""
        return self.main.stem + ".pdf"

    @property
    def is_pdf(self) -> bool:
        """A view-only PDF document (no LaTeX source, no rebuild)."""
        return self.kind == "pdf"

    def rel_path(self) -> str:
        """Path relative to --manuscript (for display / the pins.md header). Points at the main file."""
        try:
            return str(self.main.resolve().relative_to(self.paths.src.resolve()))
        except (ValueError, OSError, RuntimeError):
            return str(self.main)


@dataclass(frozen=True)
class DocNotFound:
    """No document of this instance has the key a request named. known lists the keys it serves, in order (the
    404 body's `docs`)."""

    key: str
    known: tuple[str, ...]


# ---------------------------------------------------------------- Which document: lookups over the instance's list
#
# The list of documents is the composition root's (server.DOCS; the first is the default). Each lookup takes it as an
# argument, so nothing here holds "the documents" or "the current document".


def doc_by_key(docs: Sequence[Doc], key: object) -> Doc | None:
    """The document of docs whose key is `key`, or None."""
    return next((d for d in docs if d.key == key), None)


def pin_doc_key(r: Mapping[str, Any], docs: Sequence[Doc]) -> str:
    """The document key pin record r belongs to. A legacy record without a doc field (or with an empty or non-string
    one) is read as the first document's - never migrated by a write."""
    k = r.get("doc")
    return k if isinstance(k, str) and k else docs[0].key


def doc_for_file(docs: Sequence[Doc], root: Path, path: object) -> Doc:
    """Which LaTeX document of docs a request that only gave a file (agent curl) belongs to: the one whose build root
    most deeply contains it (a relative path is taken under the manuscript root), or the first document if none does
    or the path cannot be resolved. View-only documents never match."""
    try:
        p = Path(str(path)) if os.path.isabs(str(path)) else root / str(path)
        p = p.resolve()
    except (OSError, RuntimeError, ValueError):
        return docs[0]
    best, depth = None, -1
    for d in docs:
        if d.is_pdf:
            continue
        try:
            p.relative_to(d.src.resolve())
        except (ValueError, OSError, RuntimeError):
            continue
        n = len(d.src.resolve().parts)
        if n > depth:
            best, depth = d, n
    return best or docs[0]


def request_doc(docs: Sequence[Doc], root: Path, key: str | None, file_hint: object | None = None) -> Doc | DocNotFound:
    """The document of docs that key names (limn.web.parse.parse_doc_key checked it). With no key, the document holding
    file_hint when several are served (agent curl names only a file), else the first. An unknown key is DocNotFound
    with the keys served (answered 404) - silently falling back to the first document would attach the pin to the
    wrong document."""
    if not key:
        if file_hint and len(docs) > 1:
            return doc_for_file(docs, root, file_hint)
        return docs[0]
    D = doc_by_key(docs, key)
    if D is None:
        return DocNotFound(key, tuple(d.key for d in docs))
    return D


# ---------------------------------------------------------------- Source-text access


def to_source(D: Doc, path: str) -> Path:
    """Maps a path in document D's build copy (as SyncTeX reports it) back to the original checkout path.

    If the state directory was moved or cloned, SyncTeX points at the old build path: then the longest tail of the
    path that is a real file inside the manuscript tree wins (never reads outside the tree). A path that matches
    nothing comes back unchanged."""
    p = Path(path)
    for base in (D.build, D.build.resolve()):
        try:
            return D.src / p.relative_to(base)
        except ValueError:
            pass
    try:
        return D.src / p.resolve().relative_to(D.build.resolve())
    except (ValueError, OSError):
        pass
    parts = p.parts
    for k in range(1, len(parts)):
        cand = D.src.joinpath(*parts[k:])
        if cand.is_file():
            return cand
    return p


class DocumentFacts:
    """limn.web.parse.DocumentFacts for document D: what the location parsers read from this machine's disk - the
    manuscript tree root, a file's lines, the pages of a build of D (sized at dpi). The composition root makes one per
    request (server.document_facts); every method reads at call time."""

    def __init__(self, D: Doc, root: Path, dpi: int) -> None:
        """Bind the document, the manuscript root and the dpi the page images were rendered at."""
        self._doc, self._root, self._dpi = D, root, dpi

    @property
    def key(self) -> str:
        """The document key."""
        return self._doc.key

    @property
    def is_pdf(self) -> bool:
        """True for a view-only PDF document."""
        return self._doc.is_pdf

    @property
    def pdf(self) -> Path:
        """The document's main file (a view-only document's PDF)."""
        return self._doc.main

    @property
    def root(self) -> Path:
        """The manuscript tree."""
        return self._root

    def lines(self, path: Path) -> list[str]:
        """The file's lines (limn.files.tex_lines: [] when unreadable)."""
        return tex_lines(path)

    def page_count(self, name: str | None) -> int:
        """Pages of build `name` of D, or of the build on screen when name is None or gone (limn.build.pages_dir_for)."""
        return len(build.page_list(build.pages_dir_for(self._doc, name), self._dpi))

    def current_build(self) -> str:
        """The name of D's page directory on screen."""
        return build.cur_pages(self._doc).name

    def pick_pages(self, name: str | None) -> tuple[Path, list[tuple[float, float]]] | None:
        """(page directory, [(width, height) in points]) of build `name` of D - or the one on screen for None - or None
        when name is a page directory of D that is gone."""
        if name is not None and not (self._doc.dir / name).is_dir():
            return None
        pdir = build.pages_dir_for(self._doc, name) if name is not None else build.cur_pages(self._doc)
        return pdir, [(p["pt_w"], p["pt_h"]) for p in build.page_list(pdir, self._dpi)]
