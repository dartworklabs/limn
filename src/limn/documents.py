"""The documents one viewer serves (docs/handbook/domain.md §여러 문서): a document, and what a lookup by key answers.

A single paper repo has several documents - the body, the review response, the cover letter. One viewer (one
address) switches between them by key (?doc=). The pin store is singular - pin numbers are unique across documents
so "handle #12" is unambiguous - while build, page images, PDF copy and build history live under a per-document
folder (Doc.dir). Every service that acts on a document takes it as an argument: nothing reads a "current document"
(docs/handbook/code-style-roadmap.md R5). A request that names a key the instance does not serve is answered with
the keys it does serve; silently falling back to the first document would attach a pin to the wrong document.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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
    return {"state": "idle", "phase": None, "started_at": None, "start_ts": None,
            "last_s": None, "pages": 0, "errors": [], "log_tail": "", "built_at": None,
            "seq": 0, "finished_at": None, "last": None, "head": None, "pull": None}


class Doc:
    """One document. kind is 'tex' (LaTeX, lines traced back via SyncTeX) or 'pdf' (view-only - page/region only).

    paths are the instance's run paths (RunPaths), given at construction by the composition root. legacy=True means
    a single document started without --doc: its manuscript and build folders are the run paths' own (read on each
    access, so the legacy state-folder layout keeps working). root=True puts build artifacts at the state folder
    root (the same place as for a single document). Under --doc, only the LaTeX document keyed main gets this - so
    adding documents to a single-document instance keeps the body's build history (the source of location
    estimation) continuous. A Doc carries its own build lock, build state and its lock, history lock and src_mtime
    memo (limn.build.BuildDoc)."""

    def __init__(self, key: str, name: str, kind: str = "tex", src: Path | None = None, main: Path | None = None,
                 legacy: bool = False, root: bool | None = None, lock: threading.Lock | None = None,
                 bstate: dict[str, Any] | None = None, bstate_lock: threading.Lock | None = None,
                 builds_lock: threading.Lock | None = None, mcache: list[Any] | None = None, *,
                 paths: RunPaths) -> None:
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
