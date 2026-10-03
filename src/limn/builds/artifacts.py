"""Shared build facts: outcomes, artifact paths, history and source fingerprints.

The builds feature owns requests and execution. Other features also read the build
artifacts and source fingerprints here to locate pins and report document state.
Each function takes its document and settings explicitly (coding rule R5).
See docs/handbook/build-sync.md for the build lifecycle.
"""

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Protocol, TypeGuard, TypeVar

from limn.builds.completion import render_progress
from limn.builds.figure_map import MAP_MAX_BYTES, FigureMap, MapRejected, parse_map
from limn.builds.values import (
    BUILD_STATES as BUILD_STATES,
    AbortKind as AbortKind,
    BuildAborted as BuildAborted,
    BuildBusy as BuildBusy,
    BuildFailed as BuildFailed,
    BuildFailureKind as BuildFailureKind,
    BuildOk as BuildOk,
    BuildOkWithErrors as BuildOkWithErrors,
    BuildSkipped as BuildSkipped,
    BuildStarted as BuildStarted,
    BuildState as BuildState,
    BuildUnchanged as BuildUnchanged,
    CopyFailed as CopyFailed,
    Describe as Describe,
    FailedBuild as FailedBuild,
    FinishedBuild as FinishedBuild,
    FinishedState as FinishedState,
    Json as Json,
    LatexError as LatexError,
    OutputFailureKind as OutputFailureKind,
    PagesDrawn as PagesDrawn,
    PagesNotRendered as PagesNotRendered,
    RenderFailureKind as RenderFailureKind,
    ViewOnlyNoRebuild as ViewOnlyNoRebuild,
)
from limn.platform.files import PATH_MAX_CHARS, atomic_write
from limn.platform.values import is_finite_num, is_int, is_num
from limn.runtime.documents import NO_APART, ApartPaths, InputSetCache

PAGES_DIR_RE = re.compile(r"pages(-\d{14}(-\d+)?)?")
# Directories excluded from the build copy (rsync). The manuscript fingerprint and src_mtime use the same
# list - a latexdiff artifact changing must not turn on "manuscript modified" / location re-estimation
# when it isn't part of the build (observed: 17 PDFs under diff/).
BUILD_EXCLUDE_DIRS = ("diff", "diff_temporary")
BUILDS_KEEP = 200  # number of successful builds kept in builds.json (roughly 200 bytes each)

SRC_TEX_EXTS = (".tex", ".bib", ".sty", ".cls", ".bst")
SRC_FIG_EXTS = (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg")
SRC_MTIME_EXTS = SRC_TEX_EXTS + SRC_FIG_EXTS
# Build artifact directories (in case the state directory is placed inside the manuscript) + directories the build rsync excludes.
BUILD_OUTDIRS = ("build", "out") + BUILD_EXCLUDE_DIRS
RECORDER_MAX_BYTES = 8 * 1024 * 1024  # a latexmk recorder file (.fls) larger than this is not read

FIGMAP_NAME = "figmap.json"  # a figure document's element map, copied into every page directory next to its PDF


class BuildStateHolder(Protocol):
    """A document's build state as a reader outside the build sees it (the remote-main watch, limn.sync.run)."""

    @property
    def bstate(self) -> dict[str, Any]:
        """The build state GET /api/build reports (see state_snapshot); its "state" is a BuildState."""

    @property
    def bstate_lock(self) -> threading.Lock:
        """Guards bstate."""


class BuildDoc(BuildStateHolder, Protocol):
    """What the build needs from a document. server.Doc provides it; this module never imports the server.

    The paths say where the manuscript is and where this document's artifacts go; the rest are the document's
    own build resources - one build at a time (lock), the progress/error state the viewer polls (bstate and
    its lock, from BuildStateHolder), the builds.json read-modify-write lock (builds_lock) and the 2-second
    src_mtime memo (mcache, a [key, value, measured-at] list) and its lock."""

    @property
    def src(self) -> Path:
        """Build root - the scope copied into the build copy. For view-only, the folder holding the PDF."""

    @property
    def main(self) -> Path:
        """The main .tex for LaTeX, or the PDF file for view-only."""

    @property
    def dir(self) -> Path:
        """Per-document state folder - page images, build history, built_at, etc."""

    @property
    def build(self) -> Path:
        """The build copy of the manuscript."""

    @property
    def out(self) -> Path:
        """The folder where latexmk runs and the PDF comes out."""

    @property
    def main_rel(self) -> Path:
        """The main file relative to src."""

    @property
    def pdf_name(self) -> str:
        """Name of the PDF copy inside the page directory."""

    @property
    def builds_from_source(self) -> bool:
        """latexmk builds it from the tree under src; False: its pages come from a file Limn only reads, not built
        from source (limn.runtime.documents.Doc.builds_from_source)."""

    @property
    def apart(self) -> ApartPaths:
        """What its source list leaves out because another document owns it - figure folders and view-only PDFs inside
        src (limn.runtime.documents.apart_paths); empty for a document that has none of them inside."""

    @property
    def input_sets(self) -> InputSetCache:
        """The memo of the recorder files parsed for this document (limn.runtime.documents.Doc.input_sets)."""

    @property
    def watches_files(self) -> bool:
        """The watch re-renders its pages when its file changes (limn.runtime.documents.Doc.watches_files)."""

    @property
    def lock(self) -> threading.Lock:
        """Held for the whole of one build of this document."""

    @property
    def builds_lock(self) -> threading.Lock:
        """Guards the read-modify-write of builds.json."""

    @property
    def mcache(self) -> list[Any]:
        """The src_mtime memo: [key, value, measured-at]."""

    @property
    def mcache_lock(self) -> threading.Lock:
        """Guards this document's src_mtime memo without serializing other documents."""

    mcache_epoch: int
    """How many times the src_mtime memo was expired (expire_src_mtime); changed only under mcache_lock."""


Doc = TypeVar("Doc", bound=BuildDoc)  # one document type through a call that hands the document back to its caller


@dataclass(frozen=True)
class BuildConfig:
    """The instance settings a LaTeX build reads. The composition root (server.py) makes one from its run arguments.

    state is the instance state folder: a state folder placed inside the manuscript is skipped when the build
    copies or scans the manuscript. dpi is the page-image resolution, timeout the latexmk limit in seconds."""

    state: Path
    dpi: int
    timeout: int


class ManuscriptCopyError(Exception):
    """The build copy of the manuscript is incomplete or stale; the message says why (exit code, last error line)."""


# ---------------------------------------------------------------- Page-image version directories


def valid_build_name(v: object) -> TypeGuard[str]:
    """Is v the name of a page directory (pages, pages-<14 digits>, pages-<14 digits>-<n>)? The only names a client may send back."""
    return isinstance(v, str) and PAGES_DIR_RE.fullmatch(v) is not None


def cur_pages(D: BuildDoc) -> Path:
    """The page-image directory to show right now. Pointed to by the pages.cur pointer.

    If the pointer is absent, the legacy layout (<state>/pages/) is used as-is - migrated without a rebuild.
    Per-document (D.dir - the state folder root for a single document)."""
    base = D.dir
    try:
        name = (base / "pages.cur").read_text(encoding="utf-8").strip()
    except OSError:
        name = ""
    if name and PAGES_DIR_RE.fullmatch(name) and (base / name).is_dir():
        return base / name
    return base / "pages"


def pages_dir_for(D: BuildDoc, name: object) -> Path:
    """The page directory of the build the browser is currently looking at. Falls back to the current one if the name is wrong or already deleted.

    A drag made in the gap between a rebuild finishing and the viewer switching to the new view (a polling
    gap) uses coordinates from the old layout - mapping those onto the new PDF would point at a different
    line. Because the previous build directory is kept one generation back (commit_pages keeps current + previous),
    it can usually still be traced back using the same PDF the screen was showing."""
    base = D.dir
    if valid_build_name(name) and (base / name).is_dir():
        return base / name
    return cur_pages(D)


def build_pdf(D: BuildDoc, name: object) -> Path | None:
    """The PDF GET /pdf?build=<name> serves - only the copy that matches that build's page images (pages-<build>/<main>.pdf).

    Unlike cur_pdf, this never falls back to build/. The one in build/ can be overwritten in place by a
    rebuild and drift out of sync with the on-screen page images - measuring coordinates against it would
    point at a different spot than the PNG. Returns None if there is none."""
    if name in (None, ""):
        pdir = cur_pages(D)
    elif valid_build_name(name) and (D.dir / name).is_dir():
        pdir = D.dir / name
    else:
        return None
    f = pdir / D.pdf_name
    return f if f.is_file() else None


# ---------------------------------------------------------------- Figure documents: the PDF and the per-build map
#
# A figure document's import (limn.builds.figure) publishes the map next to the PDF copy in every page
# directory. The pick and the pin input read it back per build; these readers live here, with the other shared build
# artifacts, so no feature imports another. Only the PDF a map names is placed here (figure_pdf: the import must know
# which file to read). A script a map names is placed by whoever reads it, when it reads it.


def _inside_folder(base: Path, start: Path, rel: str) -> Path | None:
    """rel - the PDF path a figure map names, POSIX separators - resolved from the folder start, when it lies strictly
    inside base (already resolved) and no part below base starts with '.', the manuscript tree's rule for dot names
    (limn.platform.files.tree_part). None for an empty, absolute or over-long path, one holding a backslash or a NUL,
    the folder base itself, or a path that cannot be resolved. Symlinks are resolved, so a link that leads out of base
    is outside. The file need not exist; only metadata is read."""
    if not rel or len(rel) > PATH_MAX_CHARS or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return None
    try:
        real = (start / rel).resolve()
        below = real.relative_to(base)
    except (ValueError, OSError, RuntimeError):
        return None
    if not below.parts or any(part.startswith(".") for part in below.parts):
        return None
    return real


def figure_pdf(doc: BuildDoc, figure_map: FigureMap) -> Path | None:
    """The PDF figure_map names, resolved from the folder holding doc's map (doc.main) and kept only when it lies inside
    doc.src (_inside_folder): the one path the import may read, or None. The file need not exist."""
    try:
        base = doc.src.resolve()
    except (OSError, RuntimeError):
        return None
    return _inside_folder(base, doc.main.parent, figure_map.pdf)


def load_build_map(doc: BuildDoc, build: str) -> FigureMap | MapRejected | None:
    """The element map published with page directory `build` of figure document doc (<doc.dir>/<build>/figmap.json),
    parsed from the copy's bytes alone (limn.builds.figure_map.parse_map asks the filesystem nothing), so the same copy
    is the same map on every read. None when build is not a page directory name or that directory has no readable copy.
    Reads at most MAP_MAX_BYTES + 1 bytes; a larger copy is MapRejected too_large."""
    if not valid_build_name(build):
        return None
    try:
        with open(doc.dir / build / FIGMAP_NAME, "rb") as fh:
            raw = fh.read(MAP_MAX_BYTES + 1)
    except OSError:
        return None
    return parse_map(raw)


def build_figure_pdf(
    doc: Doc, build: str, lookup: Callable[[Doc, str], FigureMap | MapRejected | None] = load_build_map
) -> Path | None:
    """The source PDF named by the map published with page directory `build` of figure document doc (the map lookup
    gives, then figure_pdf), or None when that build has no loadable map or its pdf lies outside doc.src. lookup is
    how the map is read: the composition root hands in the run's BuildMapCache, so a request does not parse the copy
    again; without one the copy is parsed on this call (load_build_map)."""
    found = lookup(doc, build)
    return figure_pdf(doc, found) if isinstance(found, FigureMap) else None


MAP_CACHE_MAX = 16  # parsed maps kept per run: the current and previous builds of a few figure documents


@dataclass
class BuildMapCache:
    """The parsed maps of one run's figure builds, so a pick, GET /api/pins and every pins.md render do not parse the
    same map copy again. An entry is keyed by the document's state folder (Doc.dir, docs/<key>/), the build name and
    the copy's (mtime_ns, size): the import writes a build's copy once, so an entry stays right, and a copy written
    again misses. At most MAP_CACHE_MAX entries, the oldest dropped first. What an entry holds is a function of the
    copy's bytes alone (the parse reads no other file), so an entry can never be stale against the filesystem and a
    warm cache answers what a cold one does. Whoever reads a file a map names decides then whether it may be read.

    Request threads share it: every read and write of the entries is under the lock. The entries are frozen
    dataclasses that nothing changes once parsed (FigureMap, MapRejected), so a map handed out stays usable while
    another thread evicts it. The parse runs outside the lock, so two threads that miss the same copy at once may
    both parse it; each gets an equal map and the later one is kept. A copy rewritten between the stat and the read
    is parsed under its older key, which the next read misses. The composition root makes one per run
    (server.Runtime.figure_maps)."""

    _entries: dict[tuple[str, str, int, int], FigureMap | MapRejected] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, doc: BuildDoc, build: str) -> FigureMap | MapRejected | None:
        """The map of build `build` of figure document doc as load_build_map reads it - from the cache while the copy
        is unchanged. The verdict (a FigureMap or a MapRejected) depends on the copy's bytes only, never on the
        filesystem around it, so a cached one equals a fresh parse. None, without reading, when build is not a page
        directory name or the build has no map copy."""
        if not valid_build_name(build):
            return None
        try:
            st = (doc.dir / build / FIGMAP_NAME).stat()
        except OSError:
            return None
        key = (str(doc.dir), build, st.st_mtime_ns, st.st_size)
        with self._lock:
            hit = self._entries.get(key)
        if hit is not None:
            return hit
        got = load_build_map(doc, build)
        if got is None:
            return None
        with self._lock:
            self._entries[key] = got
            while len(self._entries) > MAP_CACHE_MAX:
                del self._entries[next(iter(self._entries))]
        return got

    def held(self) -> int:
        """How many parsed maps the cache holds now: at most MAP_CACHE_MAX."""
        with self._lock:
            return len(self._entries)


def png_size(path: Path) -> tuple[int, int]:
    """(width, height) in pixels from a PNG's IHDR chunk (bytes 16-24). Raises OSError when the file cannot be read and
    struct.error when it is shorter than a PNG header."""
    with path.open("rb") as fh:
        w, h = struct.unpack(">II", fh.read(24)[16:24])
    return w, h


def page_list(pdir: Path, dpi: int) -> list[dict[str, Any]]:
    """The page images of page directory pdir in name order as {name, pt_w, pt_h}: sizes in points at the dpi they
    were rendered at. An unreadable image is left out; a missing directory has no pages."""
    pages = []
    for p in sorted(pdir.glob("page-*.png")):
        try:
            w, h = png_size(p)
        except (OSError, struct.error):
            continue
        pages.append({"name": p.name, "pt_w": w * 72.0 / dpi, "pt_h": h * 72.0 / dpi})
    return pages


def cur_pdf(D: BuildDoc, pdir: Path | None = None) -> Path:
    """The PDF matched to the page images. Uses the copy in the version directory if present; otherwise a document
    built from source reads latexmk's output in its build copy (the legacy layout's build/), and any other document
    its own main file (a view-only PDF before its first render).

    Why matching matters: even if a build fails, the screen still shows the old PDF - if pick read the
    newly broken PDF instead, it would point at a different spot than what's visible."""
    f = (pdir or cur_pages(D)) / D.pdf_name
    if f.exists():
        return f
    if not D.builds_from_source:  # nothing compiles it: its own file until pages are rendered
        return D.main
    return D.out / D.pdf_name


def build_ref_mtime(D: BuildDoc, name: str) -> float | None:
    """The manuscript src_mtime at the time that build started (looked up via build history -> built_src_mtime.txt -> PDF timestamp, in that order)."""
    ent = load_builds(D)["by"].get(name)
    if ent and is_num(ent.get("src_mtime")):
        return float(ent["src_mtime"])
    if name == cur_pages(D).name:
        v = read_built_src_mtime(D)
        if v is not None:
            return v
    try:
        return cur_pdf(D, pages_dir_for(D, name)).stat().st_mtime
    except OSError:
        return None


def source_newer(D: BuildDoc, state_dir: Path, name: str | None = None) -> float:
    """If the manuscript is newer than that build (default: the build currently on screen), returns the difference in seconds; otherwise 0.0.

    If the screen shows a stale PDF, the dragged spot and the source text drift apart. Yet the text path
    can still find a similar-looking paragraph and just barely clear the warning threshold (0.3) - in one
    observed case, selecting the Nomenclature returned the introduction's contribution list at 0.32 with no
    warning. A score alone can't filter that out, so the fact itself is surfaced instead. The comparison
    baseline is "src_mtime at the moment the build started" - this also catches files edited mid-build, and
    src_mtime already excludes diff/, which isn't part of the build (the old implementation looked at every
    *.tex plus the PDF timestamp). state_dir is skipped when the manuscript is scanned (see iter_sources). The
    manuscript is measured as that build saw it: the figure-set files that build read count (build_inputs)."""
    ref = build_ref_mtime(D, name or cur_pages(D).name)
    if ref is None:
        return 0.0
    return max(0.0, src_mtime(D, state_dir, build=name) - ref)


def migrate_pages(D: BuildDoc) -> None:
    """Turns the legacy layout (<state>/pages/ + build/<main>.pdf) into a version directory.

    The PDF/synctex copies must sit in pages/ so pick reads the same PDF as the on-screen pages - the one
    in build/ gets overwritten in place by a rebuild (and drifts if a build is in progress or fails partway). Only a
    document built from source has that layout; any other returns at once."""
    if not D.builds_from_source:  # only latexmk output has the legacy layout
        return
    legacy = D.dir / "pages"
    if not legacy.is_dir():
        return
    ptr = D.dir / "pages.cur"
    if not ptr.exists():
        atomic_write(ptr, "pages")
    if cur_pages(D) != legacy:
        return
    for suf in (".pdf", ".synctex.gz"):
        src, dst = D.out / (D.main.stem + suf), legacy / (D.main.stem + suf)
        if src.is_file() and not dst.exists():
            tmp = dst.with_name(dst.name + ".tmp")
            try:
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
            except OSError as e:
                print("warning: failed to copy %s into the page directory: %s" % (src.name, e), file=sys.stderr)


# ---------------------------------------------------------------- Build state (progress chip / error panel)


def state_update(D: BuildDoc, **kw: Any) -> None:
    """Merge kw into the document's build state under its lock."""
    with D.bstate_lock:
        D.bstate.update(kw)


def state_snapshot(D: BuildDoc) -> dict[str, Any]:
    """The shape GET /api/build returns. If a build is running, elapsed_s is re-measured against the current time.
    The render's count of pages drawn (the state's "drawn", a PagesDrawn) is answered as `progress`, {done, total}
    while a running build renders and null otherwise (completion.render_progress)."""
    with D.bstate_lock:
        d = dict(D.bstate)
    t0 = d.pop("start_ts", None)
    d["progress"] = render_progress(d.get("state"), d.get("phase"), d.pop("drawn", None))
    d["elapsed_s"] = round(time.time() - t0, 1) if d.get("state") == "running" and t0 else d.get("elapsed_s") or 0.0
    if d.get("built_at") is None:
        try:
            d["built_at"] = (D.dir / "built_at.txt").read_text().strip()
        except OSError:
            d["built_at"] = None
    return d


def last_build_failed(D: BuildStateHolder) -> bool:
    """Did the last finished build fail? A running or never-run build has not failed."""
    with D.bstate_lock:
        state: BuildState = D.bstate.get("state", "idle")
    return state == "fail"


# ---------------------------------------------------------------- Source and build history


def state_in_source(src: Path, state: Path) -> tuple[str, ...] | None:
    """The parts of the state folder below the folder src, both with symlinks resolved, when --state-dir puts it
    strictly inside src; None when it lies elsewhere or a path cannot be resolved (then it is not in src's walk)."""
    try:
        parts = state.resolve().relative_to(src.resolve()).parts
    except (ValueError, OSError, RuntimeError):
        return None
    return parts or None


def _empty_builds() -> dict[str, Any]:
    """The history of a document that has never built: no seq, no builds, no last result."""
    return {"seq": 0, "builds": [], "last": None}


def _valid_build_entry(b: object) -> bool:
    """Is b a history entry the server can trust (a page-directory name, a numeric or absent src_mtime, a string or absent hash)?"""
    return (
        isinstance(b, dict)
        and valid_build_name(b.get("build"))
        and (b.get("src_mtime") is None or is_num(b.get("src_mtime")))
        and (b.get("src_hash") is None or isinstance(b.get("src_hash"), str))
    )


def load_builds(D: BuildDoc) -> dict[str, Any]:
    """{seq, builds, last, by}. Empty history if the file is missing or broken - the server still runs without history (estimation just stays conservative)."""
    try:
        d = json.loads((D.dir / "builds.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        d = None
    out = _empty_builds()
    if isinstance(d, dict):
        if is_int(d.get("seq")) and d["seq"] >= 0:
            out["seq"] = d["seq"]
        if isinstance(d.get("builds"), list):
            out["builds"] = [b for b in d["builds"] if _valid_build_entry(b)]
        if isinstance(d.get("last"), dict):
            out["last"] = d["last"]
    out["by"] = {b["build"]: b for b in out["builds"]}
    return out


def _write_builds(D: BuildDoc, h: dict[str, Any]) -> None:
    """Write the history, keeping the last BUILDS_KEEP builds. A failed write only warns - the build itself already succeeded."""
    body = {"seq": h["seq"], "last": h["last"], "builds": h["builds"][-BUILDS_KEEP:]}
    try:
        atomic_write(D.dir / "builds.json", json.dumps(body, ensure_ascii=False, indent=1) + "\n")
    except OSError as e:
        print("warning: failed to write build history: %s" % e, file=sys.stderr)


def record_build(D: BuildDoc, last: dict[str, Any], ent: dict[str, Any] | None) -> int:
    """Add one finished build to the history and return the new seq. seq still advances (in memory) even if the write fails."""
    with D.builds_lock:
        h = load_builds(D)
        with D.bstate_lock:
            seq: int = max(h["seq"], int(D.bstate.get("seq") or 0)) + 1
        h["seq"] = seq
        h["last"] = dict(last, seq=seq, build=ent["build"] if ent else None)
        if ent:
            ent = dict(ent, seq=seq)
            h["builds"] = [b for b in h["builds"] if b["build"] != ent["build"]] + [ent]
        _write_builds(D, h)
        return seq


def confirm_build(D: BuildDoc, name: str, src_mtime: float) -> None:
    """A rebuild found build `name`'s manuscript unchanged at src_mtime (limn.builds.values.BuildUnchanged): move that
    build's history entry src_mtime there, so the "manuscript modified" badge (build_ref_mtime) measures from it. The
    content is the same, so the build stands for the manuscript as it is now. Nothing else in the history changes: no
    seq, no last. An entry that is gone (or a history that cannot be written) is left as it is."""
    with D.builds_lock:
        h = load_builds(D)
        ent = h["by"].get(name)
        if ent is None:
            return
        ent["src_mtime"] = src_mtime
        _write_builds(D, h)


def _restored_last(last: object, seq: int) -> Json | None:
    """Parse a persisted terminal build into display state, discarding malformed fields from a damaged history file.

    A missing or unknown state has no result to restore. The sequence remains the history's validated sequence even
    when individual display fields are unusable; a bad field must not prevent the server from starting.
    """
    if not isinstance(last, dict) or last.get("state") not in ("ok", "ok_errors", "fail"):
        return None
    state = last["state"]
    saved_errors = last.get("errors")
    errors: list[LatexError] = []
    if isinstance(saved_errors, list):
        errors = [
            error
            for error in saved_errors
            if isinstance(error, dict)
            and isinstance(error.get("msg"), str)
            and (error.get("line") is None or is_int(error.get("line")))
        ][:5]
    log = last.get("log_tail")
    started = last.get("started_at")
    finished = last.get("finished_at")
    elapsed = last.get("elapsed_s")
    head = last.get("head")
    pull = last.get("pull")
    started = started if isinstance(started, str) else None
    finished = finished if isinstance(finished, str) else None
    elapsed = elapsed if is_finite_num(elapsed) else None
    head = head if isinstance(head, str) else None
    pull = pull if isinstance(pull, dict) else None
    return {
        "state": state,
        "errors": errors,
        "log_tail": log if isinstance(log, str) else "",
        "started_at": started,
        "finished_at": finished,
        "last_s": elapsed,
        "elapsed_s": elapsed,
        "head": head,
        "pull": pull,
        "last": {
            "state": state,
            "errors": errors,
            "finished_at": finished,
            "seq": seq,
            "head": head,
            "pull": pull,
        },
    }


def seed_builds(D: BuildDoc, state_dir: Path) -> None:
    """Add the current build (made by an earlier instance) to history once if it isn't already there, and restore the last build result into D's build state.

    Which manuscript that build was made from is unknown. But if the current manuscript's src_mtime is at or
    before that build's reference time (built_src_mtime.txt, or the PDF timestamp if absent), no file has
    been edited since, so the current manuscript's fingerprint is adopted as that build's fingerprint - this
    keeps the first pin placed after startup from being misjudged as estimated on a "rebuild that didn't
    change the manuscript". If it can't be determined, the fingerprint is left empty (that build's pins fall
    back to conservative estimation after the next build)."""
    with D.builds_lock:
        h = load_builds(D)
        cur = cur_pages(D)
        if cur.is_dir() and cur.name not in h["by"] and any(cur.glob("page-*.png")):
            bsm = read_built_src_mtime(D)
            ref = bsm
            if ref is None:
                try:
                    ref = cur_pdf(D, cur).stat().st_mtime
                except OSError:
                    ref = None
            ent = {
                "build": cur.name,
                "seq": h["seq"],
                "src_mtime": bsm,
                "src_hash": None,
                "finished_at": read_built_at(D),
                "seeded": True,
            }
            now_m = src_mtime(D, state_dir, force=True)
            if ref is not None and now_m <= ref + 1e-6:
                ent["src_hash"] = doc_fingerprint(D, state_dir)
                if ent["src_mtime"] is None:
                    ent["src_mtime"] = now_m
            h["builds"].append(ent)
            _write_builds(D, h)
    kw = {"seq": h["seq"]}
    restored = _restored_last(h.get("last"), h["seq"])
    if restored is not None:
        kw.update(restored)
    state_update(D, **kw)


def read_built_at(D: BuildDoc) -> str | None:
    """When D's page images were last committed (built_at.txt), or None if never."""
    try:
        return (D.dir / "built_at.txt").read_text().strip()
    except OSError:
        return None


def read_head(D: BuildDoc) -> str | None:
    """The short git hash of the manuscript D's page images came from (head.txt; '-' outside git), or None if never built."""
    try:
        return (D.dir / "head.txt").read_text().strip()
    except OSError:
        return None


# ---------------------------------------------------------------- Manuscript fingerprint and src_mtime
#
# One source list (iter_sources) feeds src_mtime and the fingerprint. A LaTeX document leaves out of it the figure-set
# files that another document owns - a figure document's folder and a view-only PDF inside its build root (D.apart): that
# document's re-render is not an edit of this manuscript. A figure-set file the build on screen actually read stays in:
# latexmk's recorder file (<main>.fls) lists what pdflatex opened, and each build keeps its own next to its pages
# (limn.builds.engine.compile_tex), so the answer needs no field of builds.json. The parsed recorder files are kept in
# the document's own memo (D.input_sets), never in a module global: two servers in one process share nothing.


NO_INPUTS: frozenset[str] = frozenset()  # what a build with no readable recorder file read


def fls_inputs(text: str, cwd: Path, roots: Iterable[Path]) -> frozenset[str]:
    """The figure-set files a latexmk recorder file (.fls) lists as read: its `INPUT <path>` lines, each resolved against
    cwd - the folder pdflatex ran in - when relative, and kept when it lies strictly below one of roots (the build copy
    as a path and with symlinks resolved) and carries a suffix of SRC_FIG_EXTS, as 'a/b.pdf' below that root. The
    resolution is lexical (`.` and `..` folded, no file asked), so a file that is gone since is still named; TeX Live's
    own files, other lines (PWD, OUTPUT), a name with a NUL byte (no file has one; it would only ever be damage) and
    anything outside the copy are dropped."""
    bases = [os.path.normpath(str(r)) for r in roots]
    here = os.path.normpath(str(cwd))
    found: set[str] = set()
    for line in text.split("\n"):
        if not line.startswith("INPUT "):
            continue
        spelled = line[len("INPUT ") :].rstrip("\r")
        if "\x00" in spelled:
            continue
        full = os.path.normpath(spelled if os.path.isabs(spelled) else os.path.join(here, spelled))
        if os.path.splitext(full)[1].lower() not in SRC_FIG_EXTS:
            continue
        for base in bases:
            if full.startswith(base + os.sep):
                found.add(full[len(base) + 1 :].replace(os.sep, "/"))
                break
    return frozenset(found)


def read_recorder(path: Path) -> str | None:
    """The text of the recorder file at path, or None when it is not a plain file (a symlink, a folder), is larger than
    RECORDER_MAX_BYTES or cannot be read. Bytes that are not UTF-8 are replaced, so a damaged file lists what its intact
    lines list."""
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > RECORDER_MAX_BYTES:
            return None
        with open(path, "rb") as fh:
            raw = fh.read(RECORDER_MAX_BYTES + 1)
    except OSError:
        return None
    return None if len(raw) > RECORDER_MAX_BYTES else raw.decode("utf-8", errors="replace")


def recorded_inputs(D: BuildDoc, fls: Path) -> frozenset[str]:
    """The figure-set files the recorder file at `fls` lists for document D (fls_inputs: relative to D.out, inside D.build);
    empty when the file is absent or unreadable (read_recorder)."""
    text = read_recorder(fls)
    if text is None:
        return frozenset()
    return fls_inputs(text, D.out, (D.build, D.build.resolve()))


def build_inputs(D: BuildDoc, name: str | None = None) -> frozenset[str]:
    """The figure-set files build `name` of D read - the build on screen when name is None - as 'a/b.pdf' below the build
    root, from the recorder file kept with its pages (<D.dir>/<name>/<main>.fls), parsed once per file through the
    document's own memo (D.input_sets). NO_INPUTS, without touching the disk, for a document that sets nothing apart
    (D.apart), and for a build with no readable recorder file (made before the rule, a page directory already removed,
    latexmk's recorder switched off) or a name that is not a page directory: such a build reads nothing."""
    if D.apart.empty:
        return NO_INPUTS
    if name is None:
        pages = cur_pages(D)
    elif valid_build_name(name):
        pages = D.dir / name
    else:
        return NO_INPUTS
    fls = pages / (D.main.stem + ".fls")
    try:
        st = os.lstat(fls)
    except OSError:
        return NO_INPUTS
    if not stat.S_ISREG(st.st_mode) or st.st_size > RECORDER_MAX_BYTES:
        return NO_INPUTS
    key = (str(fls), st.st_mtime_ns, st.st_size, str(D.out), str(D.build))
    return D.input_sets.get(key, lambda: recorded_inputs(D, fls))


def _excluded_dir(name: str) -> bool:
    """Directories never scanned as manuscript: dot folders and build artifacts / folders the build copy skips."""
    return name.startswith(".") or name in BUILD_OUTDIRS


def set_apart(apart: ApartPaths, parts: tuple[str, ...], reads: frozenset[str]) -> bool:
    """Is the file at `parts` (below the build root) left out of a LaTeX document's source list because another document
    owns it? Yes when it lies in a set-apart folder or is a set-apart file (apart), carries a figure-set suffix
    (SRC_FIG_EXTS, any case; a .tex or .bib is never set apart) and is not one of `reads`, the files ('a/b.pdf') the
    build read."""
    return (
        apart.covers(parts) and os.path.splitext(parts[-1])[1].lower() in SRC_FIG_EXTS and "/".join(parts) not in reads
    )


def iter_sources(
    D: BuildDoc, root: Path, state_dir: Path, reads: frozenset[str] = frozenset(), keep_apart: bool = False
) -> Iterator[tuple[str, os.DirEntry[str]]]:
    """Yields D's manuscript/figure-extension files under root as (relative path 'a/b.tex', os.DirEntry).

    src_mtime (badge / stale-PDF warning) and source_fingerprint (build fingerprint) look at the same list -
    if they saw different files, mismatches like "badge is off but estimation is on" would appear. Dot (.)
    directories, build artifacts / directories the build rsync excludes (BUILD_OUTDIRS), the state directory
    (state_dir) when placed inside the manuscript, and the root's main PDF are all excluded. So are the files another
    document owns (D.apart, set_apart) - unless the build read them (reads, build_inputs(D)) or keep_apart is
    True, which the build asks for to hash everything once and choose after latexmk has said what it read. The paths of
    D.apart are relative to the build root, so the list is the same over D.src and over the build copy D.build."""
    main_pdf = D.pdf_name
    # the PDF next to the main .tex (a build artifact / committed copy) is not part of the manuscript
    main_at = tuple(D.main_rel.parent.parts)
    state_in_root = state_in_source(root, state_dir)
    apart = NO_APART if keep_apart else D.apart

    def walk(d: Path, rel_parts: tuple[str, ...]) -> Iterator[tuple[str, os.DirEntry[str]]]:
        """Depth-first, name-sorted walk of d (rel_parts is d relative to root), yielding the manuscript files."""
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                if _excluded_dir(e.name):
                    continue
                parts = rel_parts + (e.name,)
                if state_in_root is not None and parts == state_in_root:
                    continue
                yield from walk(Path(e.path), parts)
            elif e.is_file(follow_symlinks=False):
                if e.name == main_pdf and rel_parts == main_at:
                    continue
                if os.path.splitext(e.name)[1].lower() in SRC_MTIME_EXTS:
                    if set_apart(apart, rel_parts + (e.name,), reads):
                        continue
                    yield "/".join(rel_parts + (e.name,)), e

    yield from walk(root, ())


def doc_fingerprint(D: BuildDoc, state_dir: Path) -> str:
    """The document's manuscript fingerprint: its source tree's (source_fingerprint) for a document built from source,
    else the hash of its main file's contents (a view-only PDF). A document built from source is fingerprinted as the
    build on screen saw it (build_inputs): the figure-set files that build read are part of it."""
    if not D.builds_from_source:  # one file, hashed whole
        h = hashlib.sha256()
        with open(D.main, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:32]
    return source_fingerprint(D, D.src, state_dir, build_inputs(D))


class ScannedSource(NamedTuple):
    """One file of a scan of the manuscript: the SHA-256 of its content and its mtime, the mtime taken before the content
    was read, so a file written in between reads as newer than what was hashed - never older."""

    digest: bytes
    mtime: float


COPY_MTIME_SLACK = 1.0  # seconds: how far a copy's mtime may be from its source's and still be the same file


def source_mtime_of(path: Path, copied: float) -> float:
    """The mtime of the plain file at `path` (in the source tree) when it agrees with `copied`, the mtime of its copy, to
    within COPY_MTIME_SLACK; else `copied`. Some copy tools (the rsync of macOS) keep mtimes in whole seconds, so a copy
    can be up to a second older than its source, and a baseline taken from the copy would leave the source newer than the
    build that compiled it. A file that differs by more than that has been written since the copy, a missing file or a
    link is not the copied file: the copy's mtime, the one that belongs to the bytes hashed, stands."""
    try:
        st = os.lstat(path)
    except OSError:
        return copied
    if stat.S_ISREG(st.st_mode) and abs(st.st_mtime - copied) < COPY_MTIME_SLACK:
        return st.st_mtime
    return copied


def scan_sources(
    D: BuildDoc,
    root: Path,
    state_dir: Path,
    reads: frozenset[str] = frozenset(),
    keep_apart: bool = False,
    mtimes_from: Path | None = None,
) -> dict[str, ScannedSource]:
    """Every file iter_sources yields (same arguments) as {relative path: ScannedSource}, in list order; a file that cannot
    be read is left out. The build scans its copy once with keep_apart=True before latexmk runs: that scan is both the
    fingerprint's input and the record of which files, with which mtimes, existed before latexmk could make any.

    The bytes are hashed from root. mtimes_from, a tree laid out like root (the build passes D.src when it scans the copy),
    gives each file the mtime of the same path there (source_mtime_of) so the mtimes do not depend on what the copy
    tool keeps; without it the mtime is root's own."""
    out: dict[str, ScannedSource] = {}
    for rel, e in iter_sources(D, root, state_dir, reads, keep_apart):
        try:
            mtime = e.stat(follow_symlinks=False).st_mtime
            if mtimes_from is not None:
                mtime = source_mtime_of(mtimes_from / rel, mtime)
            with open(e.path, "rb") as fh:
                out[rel] = ScannedSource(hashlib.sha256(fh.read()).digest(), mtime)
        except OSError:
            continue
    return out


def fingerprint_of(scan: Mapping[str, ScannedSource]) -> str:
    """Manuscript fingerprint - a hash of (relative path, content digest) in the order scan lists them. mtime is not
    included: a file whose content is unchanged but timestamp changed (e.g. via git checkout) should not change the
    layout."""
    h = hashlib.sha256()
    for rel, f in scan.items():
        h.update(rel.encode("utf-8", "surrogateescape") + b"\0" + f.digest)
    return h.hexdigest()[:32]


def source_fingerprint(D: BuildDoc, root: Path, state_dir: Path, reads: frozenset[str] = frozenset()) -> str:
    """Manuscript fingerprint over the files iter_sources yields (same arguments): fingerprint_of their scan."""
    return fingerprint_of(scan_sources(D, root, state_dir, reads))


def without_apart(D: BuildDoc, scan: Mapping[str, ScannedSource], reads: frozenset[str]) -> dict[str, ScannedSource]:
    """scan - made with keep_apart=True - narrowed to the list iter_sources gives with the same `reads`: the files
    another document owns drop out, except those the build read. The fingerprint of that equals source_fingerprint over
    the same tree, so a build can hash its copy before latexmk runs and choose after it has said what it read."""
    return {rel: f for rel, f in scan.items() if not set_apart(D.apart, tuple(rel.split("/")), reads)}


def read_in_scan(scan: Mapping[str, ScannedSource], recorded: frozenset[str]) -> frozenset[str]:
    """Of the files a recorder file lists, those the scan made before latexmk ran has: a file latexmk made itself (an
    epstopdf conversion, a generated figure) was not in the manuscript the build compiled, so it is not one of the
    build's sources however the recorder file lists it."""
    return frozenset(rel for rel in recorded if rel in scan)


def newest_read_apart(D: BuildDoc, scan: Mapping[str, ScannedSource], reads: frozenset[str]) -> float:
    """The newest mtime, as the scan made before latexmk ran recorded it, among the files of `reads` that D sets apart;
    0.0 when there is none: what a build that read them compiled. The mtimes come from before latexmk so that a file the
    run touches cannot move the baseline past an edit made while it ran, and (the build scans with mtimes_from) from the
    source tree so that a copy that keeps whole seconds cannot pull it below the source's mtime."""
    return max((scan[rel].mtime for rel in reads if rel in scan and D.apart.covers(tuple(rel.split("/")))), default=0.0)


def expire_src_mtime(D: BuildDoc) -> None:
    """Drop D's 2 second src_mtime memo, so the next read measures now, and make any measurement still in flight drop its
    answer instead of storing it (it was measured against the old build): the epoch counts expiries. A build that puts
    new pages on screen calls this right after it swaps the page pointer, because which recorder file the manuscript is
    measured against has just changed."""
    with D.mcache_lock:
        D.mcache_epoch += 1
        D.mcache[2] = 0.0


def src_mtime(D: BuildDoc, state_dir: Path, force: bool = False, build: str | None = None) -> float:
    """Max mtime over manuscript/figure extensions under D.src (2-second memo in D.mcache). Build artifacts and the main PDF are excluded (iter_sources).
    A document not built from source measures its main file alone.

    The figure-set files another document owns are left out (D.apart) unless build `build` - the one on screen when it is
    None - read them (build_inputs). The memo is keyed by that build as the caller named it, so a read of it is a lock and
    a comparison: the page pointer and the recorder file are looked at only when the memo misses. A build that swaps
    the page pointer expires the memo at once (expire_src_mtime); a measurement that began before that expiry still
    returns what it measured but does not store it, so the first read after the swap is made against the new build. A
    document that sets nothing apart has one answer whatever the build, and one memo key.

    D.build, which the build populates via rsync, is normally under the state folder (i.e. outside D.src), but
    it is also excluded by name so that even the rare layout with the state directory inside the manuscript
    tree doesn't false-positive "manuscript changed" from build artifacts. D.src is included in the memo
    key so that if the manuscript path changes within the same process (tests, or a rare reconfiguration),
    the old path's value is never mistakenly returned for the new path.

    force=True skips the memo and measures now - if write_built_src_mtime() used the 2-second memo value
    as-is when recording the build-start mtime, then editing the manuscript within 2 seconds of the memo
    being filled and immediately rebuilding would wrongly record the pre-edit mtime as "the build start time".
    The cache and its leaf lock belong to D; the file scan runs outside the lock."""
    cache = D.mcache
    key = (str(D.src), None if D.apart.empty else build)
    with D.mcache_lock:
        epoch = D.mcache_epoch
        ckey, at = cache[0], cache[2]
        val: float = cache[1]
        if not force and ckey == key and time.time() - at < 2.0:
            return val
    newest = 0.0
    if not D.builds_from_source:  # not built from a tree: that one file is the manuscript
        with contextlib.suppress(OSError):
            newest = D.main.stat().st_mtime
    else:
        for _rel, e in iter_sources(D, D.src, state_dir, build_inputs(D, build)):
            with contextlib.suppress(OSError):
                newest = max(newest, e.stat().st_mtime)
    with D.mcache_lock:
        if D.mcache_epoch == epoch:  # not measured across an expiry: the answer is still about the build on screen
            cache[0], cache[1], cache[2] = key, newest, time.time()
    return newest


def read_built_src_mtime(D: BuildDoc) -> float | None:
    """The src_mtime of the manuscript D's current page images were built from (built_src_mtime.txt), or None if unknown."""
    try:
        return float((D.dir / "built_src_mtime.txt").read_text().strip())
    except (OSError, ValueError):
        return None


def write_built_src_mtime(D: BuildDoc, state_dir: Path, value: float | None = None) -> None:
    """If value is omitted, measures the current src_mtime(force=True) and records it (skipping the 2-second memo).

    The caller (run_tracked) passes the mtime of "the manuscript this build actually compiled" - after
    the pull with --git-pull (a fast-forward can bump the .tex mtime), otherwise the value measured right
    before the copy. This function is only called to commit that value when the build finished ok|ok_errors -
    a failed build still shows the old PDF on screen, so the "manuscript modified" badge must not turn off."""
    try:
        v = src_mtime(D, state_dir, force=True) if value is None else value
        atomic_write(D.dir / "built_src_mtime.txt", "%f" % v)
    except OSError:
        pass
