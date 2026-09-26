"""The manuscript build: copy, compile, render page images, keep build history (docs/handbook/build-sync.md).

One build turns one document's manuscript into a new page-image directory:

    copy (rsync to the build folder) -> latexmk -synctex=1 -> pdftoppm into pages-<time>/ -> swap pages.cur

and records what it compiled (builds.json, built_src_mtime.txt, built_at.txt, head.txt) so the server can tell
later whether a pin was placed on the same manuscript as the build on screen.

Every function takes the document it works on and the settings it needs as arguments (coding rule R5): nothing
here reads the server's run arguments or "the current request's document". So two documents can build at the
same time, each in its own build folder, from any thread. The long-lived resources of a document - its build
lock, build-state dict and lock, history lock and src_mtime memo - belong to the document object the caller
passes (server.Doc); this module creates none of them.

What stays with the caller: which document and settings (server.py binds them per request), the --git-pull
step (it coordinates every document of the repository, so it is passed in as `pull`), and the view-only PDF
"build" (passed in as the compile step).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TypeAlias, TypeGuard

from limn.files import atomic_write

PAGES_DIR_RE = re.compile(r"pages(-\d{14}(-\d+)?)?")
# Directories excluded from the build copy (rsync). The manuscript fingerprint and src_mtime use the same
# list - a latexdiff artifact changing must not turn on "manuscript modified" / location re-estimation
# when it isn't part of the build (observed: 17 PDFs under diff/).
BUILD_EXCLUDE_DIRS = ("diff", "diff_temporary")
BUILDS_KEEP = 200                  # number of successful builds kept in builds.json (roughly 200 bytes each)

SRC_TEX_EXTS = (".tex", ".bib", ".sty", ".cls", ".bst")
SRC_FIG_EXTS = (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg")
SRC_MTIME_EXTS = SRC_TEX_EXTS + SRC_FIG_EXTS
# Build artifact directories (in case the state directory is placed inside the manuscript) + directories the build rsync excludes.
BUILD_OUTDIRS = ("build", "out") + BUILD_EXCLUDE_DIRS

# One build's outcome, as the HTTP answer of POST /api/rebuild carries it (see compile_tex for the keys).
BuildResult: TypeAlias = dict[str, Any]

# Guards the read-and-refill of every document's src_mtime memo (BuildDoc.mcache). A leaf lock: nothing is
# called while holding it, and it owns nothing that needs closing.
_MTIME_LOCK = threading.Lock()


class BuildDoc(Protocol):
    """What the build needs from a document. server.Doc provides it; this module never imports the server.

    The paths say where the manuscript is and where this document's artifacts go; the rest are the document's
    own build resources - one build at a time (lock), the progress/error state the viewer polls (bstate and
    its lock), the builds.json read-modify-write lock (builds_lock) and the 2-second src_mtime memo (mcache,
    a [key, value, measured-at] list)."""

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
    def bstate(self) -> dict[str, Any]:
        """The build state GET /api/build reports (see state_snapshot)."""

    @property
    def bstate_lock(self) -> threading.Lock:
        """Guards bstate."""

    @property
    def builds_lock(self) -> threading.Lock:
        """Guards the read-modify-write of builds.json."""

    @property
    def mcache(self) -> list[Any]:
        """The src_mtime memo: [key, value, measured-at]."""


@dataclass(frozen=True)
class BuildConfig:
    """The instance settings a LaTeX build reads. The composition root (server.py) makes one from its run arguments.

    state is the instance state folder: a state folder placed inside the manuscript is skipped when the
    manuscript is scanned. dpi is the page-image resolution, timeout the latexmk limit in seconds."""
    state: Path
    dpi: int
    timeout: int


class ManuscriptCopyError(Exception):
    """The build copy of the manuscript is incomplete or stale; the message says why (exit code, last error line)."""


def _is_int(v: object) -> TypeGuard[int]:
    """An int that is not a bool (JSON true must not pass as a count)."""
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: object) -> TypeGuard[int | float]:
    """An int or float that is not a bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


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


def cur_pdf(D: BuildDoc, pdir: Path | None = None) -> Path:
    """The PDF matched to the page images. Uses the copy in the version directory if present, otherwise (legacy layout) the one in build/.

    Why matching matters: even if a build fails, the screen still shows the old PDF - if pick read the
    newly broken PDF instead, it would point at a different spot than what's visible."""
    f = (pdir or cur_pages(D)) / D.pdf_name
    if f.exists():
        return f
    if D.is_pdf:                                          # view-only: the original PDF if pages haven't been rendered yet
        return D.main
    return D.out / D.pdf_name


def build_ref_mtime(D: BuildDoc, name: str) -> float | None:
    """The manuscript src_mtime at the time that build started (looked up via build history -> built_src_mtime.txt -> PDF timestamp, in that order)."""
    ent = load_builds(D)["by"].get(name)
    if ent and _is_num(ent.get("src_mtime")):
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


# ---------------------------------------------------------------- One build at a time per document

def build_now(D: BuildDoc, run: Callable[[], BuildResult]) -> BuildResult:
    """Run one build of D synchronously. If D is already building, returns busy without waiting.

    run is the tracked build (see run_tracked) bound to D by the caller. One lock per document - different
    documents build concurrently (each has its own build folder)."""
    lock = D.lock
    if not lock.acquire(blocking=False):
        return {"ok": False, "busy": True}
    try:
        return run()
    finally:
        lock.release()


def build_in_background(D: BuildDoc, run: Callable[[], BuildResult], started_at: str) -> dict[str, Any]:
    """POST /api/rebuild?async=1: if D's lock is free, runs the same tracked build on a daemon thread and returns immediately.

    The state turns running before the thread starts, so the next poll already sees it. If run itself dies,
    the build is still finished as fail - the chip must never stay at running."""
    if not D.lock.acquire(blocking=False):
        return {"state": "running", "busy": True}
    state_update(D, state="running", phase="copy", started_at=started_at, start_ts=time.time())

    def worker() -> None:
        """Run the build, record an unexpected death as a failed build, and always release D's lock."""
        try:
            run()
        except Exception as e:                     # noqa: BLE001 — must not stay stuck at running even if the tracked build itself dies
            finish_build(D, {"ok": False, "state": "fail", "errors": [],
                             "log": "빌드 스레드에서 예상 밖 예외가 났습니다: %r" % e, "elapsed_s": 0.0}, None)
        finally:
            D.lock.release()
    threading.Thread(target=worker, daemon=True).start()
    return {"state": "running"}


def run_tracked(D: BuildDoc, state_dir: Path, compile_step: Callable[[], BuildResult], started_at: str) -> BuildResult:
    """Wraps one build (compile_step) to fill in D's build state (progress chip / error panel) and the build history.

    compile_step is compile_tex for a LaTeX document or the view-only PDF render, bound to D by the caller.
    Even if it raises an unexpected exception (e.g. an OSError near an rsync/latexmk call), the build state is
    never left stuck at running - if this function died inside an async worker, the next poll would show
    "building" forever. built_src_mtime is fixed to the mtime of "the manuscript this build actually
    compiled" - with --git-pull that's after the pull (fast-forward can bump the .tex mtime); otherwise
    compile_tex measures it right before the copy and returns it as res["src_mtime"] (force=True, skipping the
    2-second cache). Only when the step can't return that value (a PDF document, or a failure before
    res["src_mtime"] gets filled in) does the build start time (src_mtime_at_start) stand in instead. It's
    only committed to file on ok|ok_errors - on failure the screen still shows the old PDF, so the
    "manuscript modified" badge must not turn off."""
    with D.bstate_lock:
        last_s = D.bstate.get("last_s")
    state_update(D, state="running", phase="copy", started_at=started_at, start_ts=time.time(),
                 last_s=last_s, errors=[], log_tail="")
    src_mtime_at_start = src_mtime(D, state_dir, force=True)
    try:
        res = compile_step()
    except Exception as e:                            # noqa: BLE001 — must not stay stuck at running even if the build dies
        res = {"ok": False, "state": "fail", "errors": [],
               "log": "빌드 중 예상 밖 예외가 났습니다: %r" % e, "elapsed_s": 0.0}
    src_mtime_for_build = res.get("src_mtime")
    if not _is_num(src_mtime_for_build):
        src_mtime_for_build = src_mtime_at_start          # fallback for cases res couldn't fill in - a PDF document, or a failure before the copy
    if res.get("state") in ("ok", "ok_errors"):
        write_built_src_mtime(D, state_dir, src_mtime_for_build)
    finish_build(D, res, src_mtime_for_build)
    return res


def finish_build(D: BuildDoc, res: BuildResult, src_mtime_for_build: float | None) -> None:
    """A build finished (success or failure either way) - record it in history, bump build_seq, then update D's build state.

    src_mtime_for_build is the mtime of "the manuscript this build actually compiled" (after the pull with
    --git-pull, otherwise measured right before the copy - see run_tracked()). Because build_ref_mtime()
    looks at this history entry before built_src_mtime.txt, the value recorded here is the effective baseline
    for the "manuscript modified" badge.

    build_seq is "number of finished builds". The viewer notices a build it never saw by checking whether
    this value changed - even a build that starts and finishes inside a single 5-second polling gap (never
    observed as running) still bumps seq. seq and the final state are changed together (so there's never a
    visible moment where the state is final but seq is still the old value)."""
    state = res.get("state", "fail")
    last = {"state": state, "errors": list(res.get("errors") or [])[:5],
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "elapsed_s": res.get("elapsed_s", 0.0), "log_tail": str(res.get("log") or "")[-4000:],
            "head": res.get("head"), "pull": res.get("pull")}
    with D.bstate_lock:
        last["started_at"] = D.bstate.get("started_at")
    ent = None
    if state in ("ok", "ok_errors") and res.get("build"):
        ent = {"build": res["build"], "src_mtime": src_mtime_for_build, "src_hash": res.get("src_hash"),
               "finished_at": last["finished_at"]}
    seq = record_build(D, last, ent)
    state_update(D, state=state, phase=None, start_ts=None, seq=seq, finished_at=last["finished_at"],
                 elapsed_s=last["elapsed_s"], last_s=last["elapsed_s"],
                 pages=res.get("pages", 0), errors=last["errors"], head=last["head"], pull=last["pull"],
                 log_tail=res.get("log", ""), built_at=read_built_at(D),
                 last={"state": state, "errors": last["errors"], "finished_at": last["finished_at"],
                       "seq": seq, "head": last["head"], "pull": last["pull"]})


# ---------------------------------------------------------------- The LaTeX build

def latex_errors(text: str) -> list[dict[str, Any]]:
    """Pulls out up to 5 '! ' lines and the first following 'l.<n>' line each (no file guessing)."""
    out: list[dict[str, Any]] = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if not ln.startswith("! "):
            continue
        line_no = None
        for nxt in lines[i + 1:i + 40]:
            m = re.match(r"l\.(\d+)", nxt)
            if m:
                line_no = int(m.group(1))
                break
            if nxt.startswith("! "):
                break
        out.append({"line": line_no, "msg": ln[2:].strip()[:200]})
        if len(out) >= 5:
            break
    return out


def run_logged(cmd: list[str], cwd: Path, timeout: int) -> tuple[int | None, str, bool]:
    """Runs the whole process group, and kills the whole group on timeout (including pdflatex spawned by latexmk).

    Returns (returncode or None, combined output, timed out)."""
    try:
        p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             encoding="utf-8", errors="replace", start_new_session=True)
    except FileNotFoundError:
        return None, "%s 를 찾지 못했습니다." % cmd[0], False
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or "", False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        out, _ = p.communicate()
        return None, (out or "") + "\n[시간 초과 %d초 — 빌드를 중단했습니다]" % timeout, True


def copy_manuscript(src: Path, dest: Path) -> None:
    """Mirror the manuscript folder into the build folder, skipping BUILD_EXCLUDE_DIRS and *.synctex.gz.

    Uses rsync -a --delete when it is installed, otherwise replaces dest with a fresh tree copy.
    Raises ManuscriptCopyError when the copy cannot be trusted: rsync exits non-zero (a partial
    transfer exits 23 and skips --delete, leaving removed files behind), times out, or the copy hits
    an OS error. The caller must not compile dest after that.
    """
    rs = shutil.which("rsync")
    try:
        if rs:
            excl = []
            for d in BUILD_EXCLUDE_DIRS:
                excl += ["--exclude", d + "/"]
            r = subprocess.run([rs, "-a", "--delete"] + excl + ["--exclude", "*.synctex.gz",
                               str(src) + "/", str(dest) + "/"],
                               capture_output=True, text=True, errors="replace", timeout=300, check=False)
            if r.returncode != 0:
                last = (r.stderr.strip().splitlines() or ["(no message)"])[-1]
                raise ManuscriptCopyError("rsync exit %d: %s" % (r.returncode, last))
        else:                                            # must still work without rsync
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*BUILD_EXCLUDE_DIRS, "*.synctex.gz"))
    except (subprocess.TimeoutExpired, OSError) as e:
        raise ManuscriptCopyError(str(e)) from e


def compile_tex(D: BuildDoc, cfg: BuildConfig, pull: Callable[[], dict[str, Any]] | None) -> BuildResult:
    """Builds D with -synctex=1 from a copy, leaving the original untouched, then renders pages into a new directory and only swaps the pointer.

    pull is the --git-pull step (None when the flag is off); its result is reported as res["pull"]. Three
    outcomes: fail = no new PDF or timeout (screen keeps the old PDF), ok_errors = a new PDF came out but there
    are LaTeX errors ('! ' lines), ok = no errors. The result (the HTTP answer of POST /api/rebuild) has ok,
    state, errors, log, elapsed_s and, as far as the build got, pull, src_mtime, src_hash, head, build (the new
    page directory's name) and pages."""
    t0 = time.time()
    D.build.mkdir(parents=True, exist_ok=True)
    res: BuildResult = {"ok": False, "state": "fail", "errors": [], "log": "", "elapsed_s": 0.0}

    if pull is not None:                                  # fast-forward to remote main before the copy step (§P0c-E)
        state_update(D, phase="pull")
        res["pull"] = pull()
        state_update(D, phase="copy")
    # mtime of the manuscript this build will actually compile - after the pull if there was one (a
    # fast-forward can bump the .tex mtime), otherwise measured now (right before the copy). run_tracked()
    # commits this value to built_src_mtime/history - using the build start time (before the pull) instead
    # caused the new mtime from the pull to be misread as "not built yet", leaving the "manuscript modified"
    # badge on even right after a success.
    res["src_mtime"] = src_mtime(D, cfg.state, force=True)

    try:
        copy_manuscript(D.src, D.build)
    except ManuscriptCopyError as e:
        res["log"] = "원고 사본을 만들지 못했습니다: %s" % e
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res
    # The fingerprint is taken from the copy - these are exactly the files this build actually compiles (the original can still change meanwhile).
    try:
        res["src_hash"] = source_fingerprint(D, D.build, cfg.state)
    except OSError:
        res["src_hash"] = None

    state_update(D, phase="latex")
    # A single document runs in the build root as before; a --doc document runs in the folder holding its main .tex (Doc.out).
    _rc, out, timed_out = run_logged(
        ["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode", D.main.name], D.out, cfg.timeout)
    try:
        atomic_write(D.dir / "build.log", out)
    except OSError:
        pass
    tail = "\n".join(out.splitlines()[-40:])[-4000:]
    res["log"] = tail

    pdf = D.out / (D.main.stem + ".pdf")
    syn = D.out / (D.main.stem + ".synctex.gz")
    texlog = D.out / (D.main.stem + ".log")
    try:
        logtxt = texlog.read_text(encoding="utf-8", errors="replace") \
            if texlog.exists() and texlog.stat().st_mtime >= t0 - 1 else out
    except OSError:
        logtxt = out
    res["errors"] = latex_errors(logtxt)

    fresh = (not timed_out) and pdf.exists() and pdf.stat().st_mtime >= t0 - 1
    if not fresh:
        res["log"] = ("시간 초과로 멈췄습니다.\n" if timed_out else "새 PDF 가 나오지 않았습니다.\n") + tail
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res
    if not syn.exists() or syn.stat().st_mtime < t0 - 1:
        res["log"] = "synctex.gz 가 없습니다 — latexmk 가 -synctex=1 을 받았는지 확인하세요.\n" + tail
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res

    extra = [syn]
    aux = D.out / (D.main.stem + ".aux")
    if aux.is_file() and aux.stat().st_mtime >= t0 - 1:
        extra.append(aux)
    rendered = render_pages(D, pdf, extra, cfg.dpi)
    if rendered[0] is None:                          # (None, error message)
        res["log"] = rendered[1] + "\n" + tail
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res
    newdir = rendered[0]
    head_short = commit_pages(D, newdir)
    res["head"] = head_short

    res["state"] = "ok_errors" if res["errors"] else "ok"
    res["ok"] = True
    res["build"] = newdir.name
    res["pages"] = len(list(newdir.glob("page-*.png")))
    res["elapsed_s"] = round(time.time() - t0, 1)
    return res


def render_pages(D: BuildDoc, pdf: Path, extra: list[Path], dpi: int) -> tuple[Path, None] | tuple[None, str]:
    """Renders pages into a new directory and drops in a copy of the PDF (and extra - synctex). The screen keeps showing the old directory until this finishes.
    Returns (directory, None) or (None, error message)."""
    D.dir.mkdir(parents=True, exist_ok=True)
    bid = time.strftime("%Y%m%d%H%M%S")
    name = "pages-" + bid
    k = 1
    while (D.dir / name).exists():
        name = "pages-%s-%d" % (bid, k)
        k += 1
    newdir = D.dir / name
    newdir.mkdir(parents=True)
    state_update(D, phase="render")
    try:
        r = subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(newdir / "page")],
                           capture_output=True, timeout=600, check=False)
        ok_render = r.returncode == 0 and any(newdir.glob("page-*.png"))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        ok_render = False
    if not ok_render:
        shutil.rmtree(newdir, ignore_errors=True)
        return None, "쪽 이미지를 그리지 못했습니다(pdftoppm)."
    try:
        shutil.copy2(pdf, newdir / D.pdf_name)
        for f in extra:
            shutil.copy2(f, newdir / f.name)
    except OSError as e:
        shutil.rmtree(newdir, ignore_errors=True)
        return None, "PDF 사본을 쪽 디렉토리에 두지 못했습니다: %s" % e
    return newdir, None


def commit_pages(D: BuildDoc, newdir: Path) -> str:
    """Swaps the pointer to the new page directory in one shot (atomically), keeps only current+previous, and writes built_at/head. head is the short hash."""
    prev = cur_pages(D).name
    atomic_write(D.dir / "pages.cur", newdir.name)       # a single atomic swap
    for d in D.dir.iterdir():                            # keep only current and previous
        if d.is_dir() and PAGES_DIR_RE.fullmatch(d.name) and d.name not in (newdir.name, prev):
            shutil.rmtree(d, ignore_errors=True)
    atomic_write(D.dir / "built_at.txt", datetime.now().astimezone().isoformat(timespec="seconds"))
    try:
        head = subprocess.run(["git", "-C", str(D.src), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10, check=False)
        head_short = head.stdout.strip() or "-"
    except (OSError, subprocess.SubprocessError):
        head_short = "-"
    atomic_write(D.dir / "head.txt", head_short)
    return head_short


# ---------------------------------------------------------------- Build history (builds.json)
#
# For the server to judge location estimation (.est), it needs to know whether "the build on screen when
# the pin was placed" and "the current build" came from the same manuscript. So every build records its
# page-directory name (build id) and a fingerprint of the manuscript it compiled (content hash + src_mtime
# at start). Wall-clock comparison (the old approach) was wrong across the board with browser time zones,
# note edits, and pins placed on a stale PDF (confirmed by independent verification).

def _empty_builds() -> dict[str, Any]:
    """The history of a document that has never built: no seq, no builds, no last result."""
    return {"seq": 0, "builds": [], "last": None}


def _valid_build_entry(b: object) -> bool:
    """Is b a history entry the server can trust (a page-directory name, a numeric or absent src_mtime, a string or absent hash)?"""
    return (isinstance(b, dict) and valid_build_name(b.get("build"))
            and (b.get("src_mtime") is None or _is_num(b.get("src_mtime")))
            and (b.get("src_hash") is None or isinstance(b.get("src_hash"), str)))


def load_builds(D: BuildDoc) -> dict[str, Any]:
    """{seq, builds, last, by}. Empty history if the file is missing or broken - the server still runs without history (estimation just stays conservative)."""
    try:
        d = json.loads((D.dir / "builds.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        d = None
    out = _empty_builds()
    if isinstance(d, dict):
        if _is_int(d.get("seq")) and d["seq"] >= 0:
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
            ent = {"build": cur.name, "seq": h["seq"], "src_mtime": bsm, "src_hash": None,
                   "finished_at": read_built_at(D), "seeded": True}
            now_m = src_mtime(D, state_dir, force=True)
            if ref is not None and now_m <= ref + 1e-6:
                ent["src_hash"] = doc_fingerprint(D, state_dir)
                if ent["src_mtime"] is None:
                    ent["src_mtime"] = now_m
            h["builds"].append(ent)
            _write_builds(D, h)
    last = h.get("last") or {}
    kw = {"seq": h["seq"]}
    if last.get("state") in ("ok", "ok_errors", "fail"):
        errs = [e for e in (last.get("errors") or []) if isinstance(e, dict)][:5]
        kw.update(state=last["state"], errors=errs, log_tail=str(last.get("log_tail") or ""),
                  started_at=last.get("started_at"), finished_at=last.get("finished_at"),
                  last_s=last.get("elapsed_s"), elapsed_s=last.get("elapsed_s"),
                  head=last.get("head"), pull=last.get("pull"),
                  last={"state": last["state"], "errors": errs, "finished_at": last.get("finished_at"),
                        "seq": h["seq"], "head": last.get("head"), "pull": last.get("pull")})
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
    main_at = tuple(D.main_rel.parent.parts)            # the PDF next to the main .tex (a build artifact / committed copy) is not part of the manuscript
    state_in_root = None
    try:
        state_in_root = tuple(state_dir.resolve().relative_to(root.resolve()).parts)
    except (ValueError, OSError, RuntimeError):
        pass

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
    being filled and immediately rebuilding would wrongly record the pre-edit mtime as "the build start time"."""
    cache = D.mcache
    key = str(D.src)
    if not force:
        with _MTIME_LOCK:
            ckey, at = cache[0], cache[2]
            val: float = cache[1]
            if ckey == key and time.time() - at < 2.0:
                return val
    newest = 0.0
    if D.is_pdf:                                          # view-only: that one PDF file is the manuscript
        try:
            newest = D.main.stat().st_mtime
        except OSError:
            pass
    else:
        for _rel, e in iter_sources(D, D.src, state_dir):
            try:
                newest = max(newest, e.stat().st_mtime)
            except OSError:
                pass
    with _MTIME_LOCK:
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
