"""One build per document: request gate, lock, worker, state and history lifecycle."""

import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar

from limn import build
from limn.build import (
    BuildAborted,
    BuildBusy,
    BuildDoc,
    BuildFailed,
    BuildOk,
    BuildOkWithErrors,
    BuildStarted,
    CopyFailed,
    Describe,
    FinishedBuild,
    FinishedState,
    Json,
    LatexError,
    ViewOnlyNoRebuild,
)
from limn.features.builds import engine


class Rebuildable(Protocol):
    """What request_rebuild reads of a document: its key and whether it is a view-only PDF."""

    @property
    def key(self) -> str:
        """The document key (?doc=), which the view-only refusal names."""

    @property
    def is_pdf(self) -> bool:
        """A view-only PDF document (no LaTeX source)."""


R = TypeVar("R")
Target = TypeVar("Target", bound=Rebuildable)


def request_rebuild(D: Target, run: Callable[[Target], R]) -> R | ViewOnlyNoRebuild:
    """POST /api/rebuild's rule: a LaTeX document is built by run (the composition root's synchronous or background
    build) and its outcome returned; a view-only document is never rebuilt on request (ViewOnlyNoRebuild) - its pages
    follow the PDF file (refresh_pdf_doc)."""
    if D.is_pdf:
        return ViewOnlyNoRebuild(D.key)
    return run(D)


def needs_build(D: BuildDoc, no_build: bool, dpi: int) -> bool:
    """Whether startup builds D: a view-only document when its PDF changed since its pages were rendered or it has no
    page images at dpi (--no-build does not apply to it); a LaTeX document unless no_build (--no-build), and even then
    when its PDF or its page images are missing. Reads the page directory on screen and, for a view-only document,
    its PDF signature."""
    if D.is_pdf:
        return engine.pdf_changed(D) or not build.page_list(build.cur_pages(D), dpi)
    return not no_build or not build.cur_pdf(D).exists() or not build.page_list(build.cur_pages(D), dpi)


def build_now(D: BuildDoc, run: Callable[[], FinishedBuild]) -> FinishedBuild | BuildBusy:
    """Run one build of D synchronously. If D is already building, returns BuildBusy without waiting.

    run is the tracked build (see run_tracked) bound to D by the caller. One lock per document - different
    documents build concurrently (each has its own build folder)."""
    lock = D.lock
    if not lock.acquire(blocking=False):
        return BuildBusy()
    try:
        return run()
    finally:
        lock.release()


def build_in_background(
    D: BuildDoc, run: Callable[[], FinishedBuild], started_at: str, describe: Describe
) -> BuildStarted | BuildBusy:
    """POST /api/rebuild?async=1: if D's lock is free, runs the same tracked build on a daemon thread and returns
    BuildStarted at once; BuildBusy when D is already building.

    The state turns running before the thread starts, so the next poll already sees it. Failure to prepare that
    state releases the lock. If the thread cannot start or run itself dies, the build is finished as a failure
    (BuildAborted worker_crashed, its log text from describe) and its lock is released - the chip must never stay
    at running."""
    if not D.lock.acquire(blocking=False):
        return BuildBusy()
    try:
        build.state_update(D, state="running", phase="copy", started_at=started_at, start_ts=time.time())
    except BaseException:
        try:
            with D.bstate_lock:
                D.bstate.update(state="fail", phase=None, start_ts=None)
        finally:
            D.lock.release()
        raise

    def finish_crash(error: Exception) -> None:
        """Record a failed worker, and clear running even when recording itself fails."""
        try:
            finish_build(D, BuildAborted("worker_crashed", repr(error)), None, describe)
        finally:
            with D.bstate_lock:
                D.bstate.update(state="fail", phase=None, start_ts=None)

    def worker() -> None:
        """Run the build, record an unexpected death as a failed build, and always release D's lock."""
        try:
            run()
        except Exception as e:  # noqa: BLE001 — must not stay stuck at running even if the tracked build itself dies
            finish_crash(e)
        finally:
            D.lock.release()

    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception as e:
        try:
            finish_crash(e)
        finally:
            D.lock.release()
        raise
    return BuildStarted()


def run_tracked(
    D: BuildDoc, state_dir: Path, compile_step: Callable[[], FinishedBuild], started_at: str, describe: Describe
) -> FinishedBuild:
    """Wraps one build (compile_step) to fill in D's build state (progress chip / error panel) and the build history.

    compile_step is compile_tex for a LaTeX document or the view-only PDF render, bound to D by the caller.
    An unexpected source-mtime scan or compile error becomes BuildAborted crashed, so the build state does not stay
    running. An unexpected final persistence error propagates, marks the in-memory state fail, and does not roll back
    published pages. built_src_mtime is fixed to the mtime of
    "the manuscript this build actually compiled" - with --git-pull that's after the pull (fast-forward can bump
    the .tex mtime); otherwise compile_tex measures it right before the copy and returns it as the outcome's
    src_mtime (force=True, skipping the 2-second cache). Only when the outcome has no such value (a PDF document,
    or a build that stopped before measuring) does the build start time
    (src_mtime_at_start) stand in instead.
    It's only committed to file on a successful build - on failure the screen still shows the old PDF, so the
    "manuscript modified" badge must not turn off. describe gives a failure its log text (build state, history)."""
    with D.bstate_lock:
        last_s = D.bstate.get("last_s")
    build.state_update(
        D,
        state="running",
        phase="copy",
        started_at=started_at,
        start_ts=time.time(),
        last_s=last_s,
        errors=[],
        log_tail="",
    )
    src_mtime_at_start: float | None = None
    res: FinishedBuild
    try:
        src_mtime_at_start = build.src_mtime(D, state_dir, force=True)
        res = compile_step()
    except Exception as e:  # noqa: BLE001 — must not stay stuck at running even if the build dies
        res = BuildAborted("crashed", repr(e))
    compiled = compiled_mtime(res)
    # fallback for outcomes without one - a PDF document, or a build that stopped before measuring
    src_mtime_for_build = src_mtime_at_start if compiled is None else compiled
    try:
        if isinstance(res, BuildOk | BuildOkWithErrors):
            build.write_built_src_mtime(D, state_dir, src_mtime_for_build)
        finish_build(D, res, src_mtime_for_build, describe)
    except BaseException:
        # Keep the original persistence error and published pages, but clear the in-memory running state.
        with D.bstate_lock:
            D.bstate.update(state="fail", phase=None, start_ts=None)
        raise
    return res


def compiled_mtime(res: FinishedBuild) -> float | None:
    """The mtime of the manuscript the build compiled (measured after the pull, before the copy), or None when the
    build never measured it (a view-only render, or a build that stopped first)."""
    match res:
        case BuildOk(src_mtime=m) | BuildOkWithErrors(src_mtime=m) | CopyFailed(src_mtime=m) | BuildFailed(src_mtime=m):
            return m
        case BuildAborted():
            return None


def finished_state(res: FinishedBuild) -> FinishedState:
    """The build state name of a finished build: ok, ok_errors (new pages, LaTeX errors) or fail."""
    match res:
        case BuildOk():
            return "ok"
        case BuildOkWithErrors():
            return "ok_errors"
        case CopyFailed() | BuildFailed() | BuildAborted():
            return "fail"


def build_errors(res: FinishedBuild) -> list[LatexError]:
    """The LaTeX errors a finished build reports ([] when it has none or never ran latexmk)."""
    match res:
        case BuildOkWithErrors(errors=errors) | BuildFailed(errors=errors):
            return errors
        case BuildOk() | CopyFailed() | BuildAborted():
            return []


def build_elapsed(res: FinishedBuild) -> float:
    """How long the build took in seconds (rounded to 0.1); 0.0 for a build that stopped before measuring."""
    match res:
        case BuildOk(elapsed_s=s) | BuildOkWithErrors(elapsed_s=s) | CopyFailed(elapsed_s=s) | BuildFailed(elapsed_s=s):
            return s
        case BuildAborted():
            return 0.0


def build_pull(res: FinishedBuild) -> Json | None:
    """The --git-pull record of the build, or None when no pull ran."""
    match res:
        case BuildOk(pull=p) | BuildOkWithErrors(pull=p) | CopyFailed(pull=p) | BuildFailed(pull=p):
            return p
        case BuildAborted():
            return None


def finish_build(D: BuildDoc, res: FinishedBuild, src_mtime_for_build: float | None, describe: Describe) -> None:
    """A build finished (success or failure either way) - record it in history, bump build_seq, then update D's build state.

    src_mtime_for_build is the mtime of "the manuscript this build actually compiled" (after the pull with
    --git-pull, otherwise measured right before the copy - see run_tracked()). Because build_ref_mtime()
    looks at this history entry before built_src_mtime.txt, the value recorded here is the effective baseline
    for the "manuscript modified" badge. A failure's log is describe's text for it.

    build_seq is "number of finished builds". The viewer notices a build it never saw by checking whether
    this value changed - even a build that starts and finishes inside a single 5-second polling gap (never
    observed as running) still bumps seq. seq and the final state are changed together (so there's never a
    visible moment where the state is final but seq is still the old value)."""
    state = finished_state(res)
    new_pages: BuildOk | BuildOkWithErrors | None
    if isinstance(res, BuildOk | BuildOkWithErrors):
        new_pages, log = res, res.log
    else:
        new_pages, log = None, describe(res)
    last = {
        "state": state,
        "errors": list(build_errors(res))[:5],
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_s": build_elapsed(res),
        "log_tail": log[-4000:],
        "head": None if new_pages is None else new_pages.head,
        "pull": build_pull(res),
    }
    with D.bstate_lock:
        last["started_at"] = D.bstate.get("started_at")
    ent = None
    if new_pages is not None and new_pages.build:
        ent = {
            "build": new_pages.build,
            "src_mtime": src_mtime_for_build,
            "src_hash": new_pages.src_hash,
            "finished_at": last["finished_at"],
        }
    seq = build.record_build(D, last, ent)
    build.state_update(
        D,
        state=state,
        phase=None,
        start_ts=None,
        seq=seq,
        finished_at=last["finished_at"],
        elapsed_s=last["elapsed_s"],
        last_s=last["elapsed_s"],
        pages=0 if new_pages is None else new_pages.pages,
        errors=last["errors"],
        head=last["head"],
        pull=last["pull"],
        log_tail=log,
        built_at=build.read_built_at(D),
        last={
            "state": state,
            "errors": last["errors"],
            "finished_at": last["finished_at"],
            "seq": seq,
            "head": last["head"],
            "pull": last["pull"],
        },
    )
