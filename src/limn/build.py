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
import struct
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias, TypeGuard, TypeVar, get_args

from limn.files import atomic_write
from limn.pins.shapes import is_finite_num, is_int, is_num

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

# The build state's "state" (GET /api/build, builds.json `last.state`): no build yet, a build running, or how the last
# one finished. The viewer's chip and error panel read the same names.
BuildState: TypeAlias = Literal["idle", "running", "ok", "ok_errors", "fail"]
BUILD_STATES: tuple[BuildState, ...] = get_args(BuildState)
FinishedState: TypeAlias = Literal["ok", "ok_errors", "fail"]
# One LaTeX error of the error panel: {"line": <int or None>, "msg": <text>} (latex_errors).
LatexError: TypeAlias = dict[str, Any]
Json: TypeAlias = dict[str, Any]

# ---------------------------------------------------------------- Build outcomes
#
# A build ends in one of these values; nothing here writes their JSON or their failure texts. The HTTP answer of POST
# /api/rebuild is written once, at the build feature edge (limn.features.builds.answer.rebuild_answer), and a failure's log text comes from
# the web layer's table (limn.web.errors.BUILD_FAILURES) through the `describe` function the composition root passes
# to the calls that record a finished build. Where a field is "None: no key", the answer leaves that key out - the
# answer has always carried only what the build got as far as.

# Why a build failed; each kind has one text in limn.web.errors.BUILD_FAILURES. The narrower kinds are what each
# failure type can carry (tests pin that together they are every kind but "copy", which is CopyFailed's own).
BuildFailureKind: TypeAlias = Literal[
    "copy", "timeout", "no_pdf", "no_synctex", "render", "pdf_copy", "pdf_missing", "crashed", "worker_crashed"
]
RenderFailureKind: TypeAlias = Literal["render", "pdf_copy"]
OutputFailureKind: TypeAlias = Literal["timeout", "no_pdf", "no_synctex", "render", "pdf_copy"]
AbortKind: TypeAlias = Literal["pdf_missing", "crashed", "worker_crashed"]


@dataclass(frozen=True)
class BuildOk:
    """A build that made new page images with no LaTeX error.

    log is latexmk's last lines ("" for a view-only render); pull is the --git-pull record (None: no pull ran, no key);
    src_mtime the manuscript mtime it compiled (None for a view-only document, no key); src_hash the fingerprint of
    what it compiled (None when it could not be read); head the short commit, build the new page directory's name,
    pages how many page images it holds."""

    log: str
    elapsed_s: float
    pull: Json | None
    src_mtime: float | None
    src_hash: str | None
    head: str
    build: str
    pages: int


@dataclass(frozen=True)
class BuildOkWithErrors:
    """A LaTeX build that made new page images although the log has errors ('! ' lines, at most five in errors).
    The other fields are BuildOk's."""

    errors: list[LatexError]
    log: str
    elapsed_s: float
    pull: Json | None
    src_mtime: float
    src_hash: str | None
    head: str
    build: str
    pages: int


@dataclass(frozen=True)
class CopyFailed:
    """The manuscript copy could not be trusted (limn.build.ManuscriptCopyError, its text in error), so nothing was
    compiled. pull and src_mtime as in BuildOk; no fingerprint was taken."""

    error: str
    elapsed_s: float
    pull: Json | None
    src_mtime: float


@dataclass(frozen=True)
class BuildFailed:
    """The build ran but left no new page images: latexmk timed out, made no fresh PDF or no SyncTeX file, or the
    pages could not be rendered or stored. detail fills the kind's text (the OSError of pdf_copy, else "");
    output is latexmk's last lines, appended after the text (None for a view-only render, which runs no latexmk).
    errors, pull, src_mtime and src_hash as in BuildOk and BuildOkWithErrors."""

    kind: OutputFailureKind
    detail: str
    output: str | None
    errors: list[LatexError]
    elapsed_s: float
    pull: Json | None
    src_mtime: float | None
    src_hash: str | None


@dataclass(frozen=True)
class BuildAborted:
    """The build stopped before it measured anything: a view-only document's PDF is missing (detail: its path), or the
    build died of an unexpected exception (detail: its repr) - in the tracked build (crashed) or in the background
    worker around it (worker_crashed). Reported with elapsed_s 0.0."""

    kind: AbortKind
    detail: str


FailedBuild: TypeAlias = CopyFailed | BuildFailed | BuildAborted
FinishedBuild: TypeAlias = BuildOk | BuildOkWithErrors | FailedBuild
# The text of a failed build's log (limn.web.errors.build_failure_log), passed in by the composition root.
Describe: TypeAlias = Callable[[FailedBuild], str]


@dataclass(frozen=True)
class BuildBusy:
    """The document is already building (its build lock is held); nothing was started."""


@dataclass(frozen=True)
class BuildStarted:
    """A background build of the document was started; its state is running."""


@dataclass(frozen=True)
class ViewOnlyNoRebuild:
    """A rebuild asked of a view-only PDF document (request_rebuild): there is nothing to compile - its pages are
    redrawn by themselves when the PDF file changes. key names the document for the refusal."""

    key: str


@dataclass(frozen=True)
class BuildSkipped:
    """Startup found the document's page images current, so it did not build."""


@dataclass(frozen=True)
class PagesNotRendered:
    """render_pages made no page directory: pdftoppm failed (render), or the PDF and its companions could not be
    copied next to the pages (pdf_copy; detail is the OSError)."""

    kind: RenderFailureKind
    detail: str


class BuildStateHolder(Protocol):
    """A document's build state as a reader outside the build sees it (the remote-main watch, limn.gitsync)."""

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
    def is_pdf(self) -> bool:
        """A view-only PDF document (no LaTeX source)."""

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
    """The PDF matched to the page images. Uses the copy in the version directory if present, otherwise (legacy layout) the one in build/.

    Why matching matters: even if a build fails, the screen still shows the old PDF - if pick read the
    newly broken PDF instead, it would point at a different spot than what's visible."""
    f = (pdir or cur_pages(D)) / D.pdf_name
    if f.exists():
        return f
    if D.is_pdf:  # view-only: the original PDF if pages haven't been rendered yet
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
    *.tex plus the PDF timestamp). state_dir is skipped when the manuscript is scanned (see iter_sources)."""
    ref = build_ref_mtime(D, name or cur_pages(D).name)
    if ref is None:
        return 0.0
    return max(0.0, src_mtime(D, state_dir) - ref)


def migrate_pages(D: BuildDoc) -> None:
    """Turns the legacy layout (<state>/pages/ + build/<main>.pdf) into a version directory.

    The PDF/synctex copies must sit in pages/ so pick reads the same PDF as the on-screen pages - the one
    in build/ gets overwritten in place by a rebuild (and drifts if a build is in progress or fails partway)."""
    if D.is_pdf:
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
    """The shape GET /api/build returns. If a build is running, elapsed_s is re-measured against the current time."""
    with D.bstate_lock:
        d = dict(D.bstate)
    t0 = d.pop("start_ts", None)
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


def _excluded_dir(name: str) -> bool:
    """Directories never scanned as manuscript: dot folders and build artifacts / folders the build copy skips."""
    return name.startswith(".") or name in BUILD_OUTDIRS


def iter_sources(D: BuildDoc, root: Path, state_dir: Path) -> Iterator[tuple[str, os.DirEntry[str]]]:
    """Yields D's manuscript/figure-extension files under root as (relative path 'a/b.tex', os.DirEntry).

    src_mtime (badge / stale-PDF warning) and source_fingerprint (build fingerprint) look at the same list -
    if they saw different files, mismatches like "badge is off but estimation is on" would appear. Dot (.)
    directories, build artifacts / directories the build rsync excludes (BUILD_OUTDIRS), the state directory
    (state_dir) when placed inside the manuscript, and the root's main PDF are all excluded."""
    main_pdf = D.pdf_name
    # the PDF next to the main .tex (a build artifact / committed copy) is not part of the manuscript
    main_at = tuple(D.main_rel.parent.parts)
    state_in_root = state_in_source(root, state_dir)

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
                    yield "/".join(rel_parts + (e.name,)), e

    yield from walk(root, ())


def doc_fingerprint(D: BuildDoc, state_dir: Path) -> str:
    """The document's manuscript fingerprint. For view-only, this is the hash of the PDF file's contents."""
    if D.is_pdf:
        h = hashlib.sha256()
        with open(D.main, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:32]
    return source_fingerprint(D, D.src, state_dir)


def source_fingerprint(D: BuildDoc, root: Path, state_dir: Path) -> str:
    """Manuscript fingerprint - a hash of (relative path, content) over the files iter_sources yields. mtime is not included:
    a file whose content is unchanged but timestamp changed (e.g. via git checkout) should not change the layout."""
    h = hashlib.sha256()
    for rel, e in iter_sources(D, root, state_dir):
        try:
            with open(e.path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).digest()
        except OSError:
            continue
        h.update(rel.encode("utf-8", "surrogateescape") + b"\0" + digest)
    return h.hexdigest()[:32]


def src_mtime(D: BuildDoc, state_dir: Path, force: bool = False) -> float:
    """Max mtime over manuscript/figure extensions under D.src (2-second memo in D.mcache). Build artifacts and the main PDF are excluded (iter_sources).

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
    key = str(D.src)
    if not force:
        with D.mcache_lock:
            ckey, at = cache[0], cache[2]
            val: float = cache[1]
            if ckey == key and time.time() - at < 2.0:
                return val
    newest = 0.0
    if D.is_pdf:  # view-only: that one PDF file is the manuscript
        with contextlib.suppress(OSError):
            newest = D.main.stat().st_mtime
    else:
        for _rel, e in iter_sources(D, D.src, state_dir):
            with contextlib.suppress(OSError):
                newest = max(newest, e.stat().st_mtime)
    with D.mcache_lock:
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
