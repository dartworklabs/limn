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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias

from limn.security.values import AuthorityScope

MAP_SUFFIX = ".limnmap.json"

DOC_KEY_RE = re.compile(r"[a-z0-9-]{1,24}")
DOC_NAME_MAX = 40
DOCS_MAX = 12
DEFAULT_DOC_KEY = "main"

# What a document is, read once from a --doc path's suffix (limn.administration.serve_documents.parse_doc_arg);
# an instance started without --doc serves one "tex" document; a path ending in MAP_SUFFIX is a "figure".
# Branches ask a capability of Doc - builds_from_source, watches_files, takes_line_pins, shows_revisions, view_only -
# never the kind. Only what reports the kind itself reads it: the API's kind, a document's authority identity, the
# startup line (docs/handbook/domain.md §여러 문서).
DocKind: TypeAlias = Literal["tex", "pdf", "figure"]


def kind_builds_from_source(kind: DocKind) -> bool:
    """Whether documents of `kind` are built from their source by latexmk - "tex" only.

    The one rule behind Doc.builds_from_source, for the startup decisions made on a parsed --doc
    (serve_documents.DocSpec) before its Doc exists."""
    return kind == "tex"


@dataclass(frozen=True)
class RunPaths:
    """The instance's run paths a document reads (limn.runtime.config.RunConfig.paths), fixed when the run starts: the
    composition root makes the documents once the state folder is known and hands each this value."""

    src: Path  # --manuscript: the manuscript tree
    main: Path  # the main .tex of an instance started without --doc
    state: Path  # the instance state folder

    @property
    def build(self) -> Path:
        """The build copy of an instance started without --doc."""
        return self.state / "build"


@dataclass(frozen=True)
class ApartPaths:
    """What a LaTeX document leaves out of its source list because another document owns it, as path parts below its
    build root (docs/handbook/build-sync.md §원고 변화 감지): `folders` are the folders of figure documents, whose
    figure-set files (images and PDFs) are left out; `files` are view-only PDFs, left out one by one - never their
    folder, which is often the manuscript root itself. Only the build's source list reads this; it names no document and
    no pin. A suffix is not part of the answer: the source list decides which suffixes it asks about."""

    folders: tuple[tuple[str, ...], ...] = ()
    files: tuple[tuple[str, ...], ...] = ()

    @property
    def empty(self) -> bool:
        """Nothing is set apart: the document has no other document's files inside its tree."""
        return not (self.folders or self.files)

    def covers(self, parts: tuple[str, ...]) -> bool:
        """Is the file at `parts` (below the build root) inside a set-apart folder, or one of the set-apart files?"""
        if parts in self.files:
            return True
        return any(len(parts) > len(folder) and parts[: len(folder)] == folder for folder in self.folders)


NO_APART = ApartPaths()

INPUT_CACHE_MAX = (
    32  # parsed recorder files one document keeps: its current and previous builds, with room for a few more
)


@dataclass
class InputSetCache:
    """One document's memo of parsed latexmk recorder files (.fls), so a poll or a pick does not read and parse a build's
    .fls again (limn.builds.artifacts.build_inputs). It belongs to the Doc, next to the src_mtime memo and its lock, so
    two documents - or two servers in one process - never share it. An entry is keyed by the caller (the file's path, its
    (mtime_ns, size) and the folders its paths were resolved against), so a file written again misses; what an entry
    holds is a function of that key's bytes alone, a frozen set, so a warm memo answers what a cold one does. At most
    `limit` entries, the oldest dropped first.

    Request threads share it: every read and write of the entries is under the lock. `parse` runs outside the lock, so
    two threads that miss the same key at once both parse it, each gets an equal set, and the later one is kept."""

    limit: int = INPUT_CACHE_MAX
    _entries: dict[tuple[str, int, int, str, str], frozenset[str]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, key: tuple[str, int, int, str, str], parse: Callable[[], frozenset[str]]) -> frozenset[str]:
        """The entry for key - from the memo while it is there, else what parse() answers, which is then kept."""
        with self._lock:
            hit = self._entries.get(key)
        if hit is not None:
            return hit
        got = parse()
        with self._lock:
            self._entries[key] = got
            while len(self._entries) > self.limit:
                del self._entries[next(iter(self._entries))]
        return got

    def held(self) -> int:
        """How many parsed recorder files the memo holds now: at most `limit`."""
        with self._lock:
            return len(self._entries)


def _parts_below(root: Path, path: Path) -> tuple[str, ...] | None:
    """The parts of `path` below `root`, both with symlinks resolved, when it lies strictly inside; None when it is
    root itself, lies elsewhere or a path cannot be resolved."""
    try:
        parts = path.resolve().relative_to(root).parts
    except (ValueError, OSError, RuntimeError):
        return None
    return parts or None


def apart_paths(src: Path, main: Path, others: Iterable[tuple[DocKind, Path, Path]]) -> ApartPaths:
    """What the LaTeX document with build root `src` and main file `main` sets apart, given the (kind, src, main) of
    every other document the instance serves.

    - A figure document's folder, when it lies strictly inside src and does not hold this document's main file: its
      figure-set files are another document's output, not this document's source. A folder equal to src or holding
      src sets nothing apart - every file of the tree would be left out.
    - A view-only PDF, when the file lies strictly inside src: that one file. Its folder (what the document calls its
      src) is not set apart; it is the manuscript root as often as not.
    - Another LaTeX document's folder and anything outside src set nothing apart.
    Symlinks are resolved on both sides, as limn.builds.artifacts.state_in_source does."""
    try:
        root = src.resolve()
        main_real = main.resolve()
    except (OSError, RuntimeError):
        return NO_APART
    folders: list[tuple[str, ...]] = []
    files: list[tuple[str, ...]] = []
    for kind, other_src, other_main in others:
        if kind == "figure":
            below = _parts_below(root, other_src)
            if below is None:
                continue
            try:
                main_real.relative_to(other_src.resolve())
            except ValueError:
                folders.append(below)
            except (OSError, RuntimeError):
                continue
        elif kind == "pdf":
            below = _parts_below(root, other_main)
            if below is not None:
                files.append(below)
    return ApartPaths(tuple(folders), tuple(files))


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
    """One document of a kind (DocKind): 'tex' is LaTeX, lines traced back via SyncTeX; 'pdf' is a view-only PDF,
    pinned by page and region; 'figure' is a PDF a figure repository renders with its element map (limn.builds.figure_map),
    imported rather than built. What it can do is read from its capability properties (builds_from_source,
    watches_files, takes_line_pins, shows_revisions, view_only), never from kind.

    paths are the instance's run paths (RunPaths, a frozen value), given at construction by the composition root.
    legacy=True means a single document started without --doc: its manuscript and build folders are the run paths'
    own, so the legacy state-folder layout keeps working. root=True puts build artifacts at the state folder
    root (the same place as for a single document). Under --doc, only the LaTeX document keyed main gets this - so
    adding documents to a single-document instance keeps the body's build history (the source of location
    estimation) continuous. A Doc carries its own build lock, build state and its lock, history lock, src_mtime memo
    with its lock and its epoch (a count of the times the memo was expired, so an answer measured across an expiry is
    never stored), the memo of the recorder files parsed for it (input_sets), and the paths its source list leaves out
    (apart) (limn.builds.artifacts.BuildDoc)."""

    def __init__(
        self,
        key: str,
        name: str,
        kind: DocKind = "tex",
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
        apart: ApartPaths = NO_APART,
    ) -> None:
        """A document; src/main are its build root and main file unless legacy (then the run paths' own).
        A supplied mcache is copied so its mutable memo and lock belong only to this document. apart is what its source
        list leaves out because another document owns it (apart_paths); only a LaTeX document is given any."""
        self.key, self.name, self.kind = key, name, kind
        self.apart = apart
        self._src, self._main, self.legacy = src, main, legacy
        self.paths = paths
        self.root = legacy if root is None else root
        self.lock = lock or threading.Lock()
        self.bstate = bstate if bstate is not None else fresh_build_state()
        self.bstate_lock = bstate_lock or threading.Lock()
        self.builds_lock = builds_lock or threading.Lock()
        self.mcache = list(mcache) if mcache is not None else [None, 0.0, 0.0]
        self.mcache_lock = threading.Lock()
        self.mcache_epoch = 0
        self.input_sets = InputSetCache()

    @property
    def src(self) -> Path:
        """Build root - the scope copied into the build copy. For view-only, the folder holding the PDF; for a figure
        document, its folder - the base of the map's source paths (the root before '::', else the map's folder)."""
        if self.legacy:
            return self.paths.src
        assert self._src is not None, "a document started with --doc has its own src"
        return self._src

    @property
    def main(self) -> Path:
        """The main .tex for LaTeX, the PDF file for view-only, the element map for a figure document."""
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
        """Name of the PDF copy inside the page directory: the main file's stem + .pdf, and for a document with an
        element map the map's name without MAP_SUFFIX + .pdf (figures.limnmap.json -> figures.pdf)."""
        if self.has_element_map:
            return self.main.name.removesuffix(MAP_SUFFIX) + ".pdf"
        return self.main.stem + ".pdf"

    @property
    def builds_from_source(self) -> bool:
        """latexmk builds it from its source tree: startup and POST /api/rebuild compile it, --git-pull rebuilds it,
        stale_build and the .aux outline apply, and its fingerprint and src_mtime scan the tree. False: its pages come
        from a file Limn only reads."""
        return kind_builds_from_source(self.kind)

    @property
    def watches_files(self) -> bool:
        """The watch thread brings in new pages when its files change - a view-only PDF's file, a figure document's
        map and the PDF the map names - and startup does so when they changed since the last time (--no-build or
        not)."""
        return self.kind in ("pdf", "figure")

    @property
    def takes_line_pins(self) -> bool:
        """Its pins are file/lo/hi line ranges with anchor re-sync, and a request that names only a file can route to
        it (doc_for_file): a LaTeX document, and a figure document - its pins are lines of the code that drew it
        (docs/handbook/domain.md §여러 문서)."""
        return self.kind in ("tex", "figure")

    @property
    def shows_revisions(self) -> bool:
        """The changes view is available: the Git history of its files - a LaTeX document's manuscript files, compared
        as a latexdiff PDF; a figure document's map, PDF and drawing files, compared by laying the previous build's
        pages over the current ones (docs/handbook/viewer.md §변경 보기)."""
        return self.kind in ("tex", "figure")

    @property
    def view_only(self) -> bool:
        """Its pins are page regions only - the API's view_only. Exactly the absence of line pins."""
        return not self.takes_line_pins

    @property
    def has_element_map(self) -> bool:
        """Its pages come with a producer-written element map (limn.builds.figure_map) - a figure document: the watch imports the
        map with the PDF it names instead of rendering one file, and every page directory keeps the map it was
        imported with."""
        return self.kind == "figure"

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


# The suffixes of a LaTeX document's own source files (compared case-insensitively). doc_for_file sends such a file to
# the document built from source when two line-pin documents contain it at the same folder depth; any other file
# (a drawing script, a data file) goes to the figure document.
LATEX_SOURCE_SUFFIXES: frozenset[str] = frozenset({".tex", ".bib", ".sty", ".cls", ".bst"})


def doc_for_file(docs: Sequence[Doc], root: Path, path: object) -> Doc:
    """Which document of docs that takes line pins (LaTeX or figure) a request that only gave a file (agent curl)
    belongs to: the one whose folder most deeply contains it (a relative path is taken under the manuscript root), or
    the first document if none does or the path cannot be resolved. Of documents equally deep, a file with a LaTeX
    source suffix (LATEX_SOURCE_SUFFIXES, any case) goes to the one built from source, any other file to the one with
    an element map, and in a tie that leaves the first listed wins. View-only documents never match."""
    try:
        p = Path(str(path)) if os.path.isabs(str(path)) else root / str(path)
        p = p.resolve()
    except (OSError, RuntimeError, ValueError):
        return docs[0]
    latex_file = p.suffix.lower() in LATEX_SOURCE_SUFFIXES
    best, rank = None, (-1, False)
    for d in docs:
        if not d.takes_line_pins:
            continue
        try:
            p.relative_to(d.src.resolve())
        except (ValueError, OSError, RuntimeError):
            continue
        preferred = d.builds_from_source if latex_file else d.has_element_map
        cand = (len(d.src.resolve().parts), preferred)
        if cand > rank:
            best, rank = d, cand
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


def document_authority_target(doc: Doc) -> AuthorityScope:
    """Snapshot the selected document's identity and filesystem destinations.

    A mutable document cannot redirect an issued request by replacing paths while
    retaining the same object or key. Build status and locks are not destinations.
    """
    return AuthorityScope(
        doc,
        (
            doc.key,
            doc.kind,
            str(doc.src.resolve()),
            str(doc.main.resolve()),
            str(doc.dir.resolve()),
            str(doc.build.resolve()),
        ),
    )
