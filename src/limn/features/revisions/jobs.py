"""Comparison cache and worker lifecycle for revision requests."""

import contextlib
import fcntl
import json
import re
import shutil
import threading
import time
import traceback
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from limn.features.revisions import core, execution
from limn.features.revisions.core import (
    REVISION_CACHE_KEEP,
    REVISION_CACHE_TTL,
    REVISION_PDF_MAX,
    REVISION_SCOPED_KEEP,
    SCOPE_META,
    SCOPED_MARK,
    AllSlotsBusy,
    BuildFailure,
    ComparisonBuilt,
    DocumentBusy,
    Json,
    PdfRefusal,
    RevisionContext,
    RevisionDoc,
    RevisionNotReady,
    RevisionPdfMissing,
    RevisionSpec,
    StartRefusal,
    StatusRefusal,
    UnsafeCache,
)
from limn.files import atomic_write


def revision_cache_root(D: RevisionDoc) -> Path | UnsafeCache:
    """The document's comparison cache folder (<state>/revisions for it), created if absent; UnsafeCache when it is a
    symlink."""
    root = D.dir / "revisions"
    if root.is_symlink():
        return UnsafeCache()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _without_meta(d: Mapping[str, Any]) -> Json:
    """d without the per-request pin fields (SCOPE_META), so a stored or shared status never carries another
    request's pin."""
    return {k: v for k, v in d.items() if k not in SCOPE_META}


# ---------------------------------------------------------------- the status of one comparison


@dataclass(frozen=True)
class IdleComparison:
    """No usable comparison of a spec in the cache - never built, expired, or an entry that is corrupt, oversized, a
    symlink, not finished, or "ready" without a sane PDF. Answered as state "idle"."""


@dataclass(frozen=True)
class RunningComparison:
    """A comparison this process is building. fields is its status as answered (state "running"), without the
    per-request pin fields (SCOPE_META); RevisionJobs.active holds it until the worker finishes."""

    fields: Json


@dataclass(frozen=True)
class ReadyComparison:
    """A finished comparison whose PDF is in the cache. fields is its status.json as stored (state "ready"), without
    the per-request pin fields; the spec's identity is laid over it when answered."""

    fields: Json


@dataclass(frozen=True)
class FailedComparison:
    """A finished comparison that failed. fields is its status.json as stored (state "error", the failure's text and
    API reason), without the per-request pin fields."""

    fields: Json

    @property
    def reason(self) -> object:
        """The stored API reason of the failure (compile_failed, timeout, build_failed, ...), as read."""
        return self.fields.get("reason")


CachedComparison: TypeAlias = IdleComparison | ReadyComparison | FailedComparison
ComparisonStatus: TypeAlias = CachedComparison | RunningComparison

# Failures a pin subset meets again on every build of it (two SHA-1s and a fixed pipeline): answered from the cache.
DETERMINISTIC_FAILURES = ("compile_failed", "diff_failed", "scope_failed")


def answered_from_cache(cached: CachedComparison, scoped: bool) -> bool:
    """Whether POST /api/revision-build answers with the cached comparison instead of building it (scoped: the spec
    applies a pin's blocks only). A finished PDF is answered. A pin subset that failed deterministically
    (DETERMINISTIC_FAILURES) would fail the same way again, so its failure is answered too and the viewer falls back at
    once instead of spending a build slot; any other failure - a whole commit's included - builds again, and so does a
    miss. Pure."""
    match cached:
        case ReadyComparison():
            return True
        case FailedComparison():
            return scoped and cached.reason in DETERMINISTIC_FAILURES
        case IdleComparison():
            return False


def status_body(status: ComparisonStatus, spec: RevisionSpec) -> Json:
    """The JSON a revision-build route answers with for spec in status: the stored or running fields with spec's
    identity (job_id, base, head, engine) and, for a pin request, its per-request fields (spec.meta). A running job's
    fields already carry the identity. Pure."""
    meta: Mapping[str, Any] = spec.meta or {}
    identity = dict({"job_id": spec.key, "base": spec.base, "head": spec.head, "engine": "pdflatex"}, **meta)
    match status:
        case RunningComparison(fields=fields):
            return dict(_without_meta(fields), **meta)
        case ReadyComparison(fields=fields) | FailedComparison(fields=fields):
            return dict(fields, **identity)
        case IdleComparison():
            return dict(identity, state="idle", warnings=[], error=None, reason=None)


def revision_cached(spec: RevisionSpec, root: Path) -> CachedComparison:
    """The finished comparison of spec in its cache folder under root: ReadyComparison only with a PDF of sane size,
    FailedComparison for a stored failure, else IdleComparison. Reads files only; a corrupt, oversized, symlinked or
    expired entry is a miss."""
    path = root / spec.key
    status = path / "status.json"
    try:
        if path.is_symlink() or status.is_symlink() or status.stat().st_size > 32768:
            return IdleComparison()
        data = json.loads(status.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or time.time() - status.stat().st_mtime > REVISION_CACHE_TTL:
            return IdleComparison()
        match data.get("state"):
            case "ready":
                pdf = path / "revision.pdf"
                if pdf.is_symlink() or not 0 < pdf.stat().st_size <= REVISION_PDF_MAX:
                    return IdleComparison()
                return ReadyComparison(_without_meta(data))
            case "error":
                return FailedComparison(_without_meta(data))
            case _:
                return IdleComparison()
    except (OSError, ValueError, TypeError):
        return IdleComparison()


def revision_prune(root: Path, keep_key: str, running: Mapping[str, RunningComparison]) -> None:
    """Removes expired comparisons and, newest first, those beyond the limits - REVISION_CACHE_KEEP whole-commit and
    REVISION_SCOPED_KEEP pin-scoped ones (SCOPED_MARK), counted apart so pins never push out whole-commit PDFs. The
    entry about to be built (keep_key, counted as one whole-commit slot as before) and running jobs are kept."""
    entries = [p for p in root.iterdir() if re.fullmatch(r"[0-9a-f]{64}", p.name) and p.is_dir() and not p.is_symlink()]
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    kept = {False: 1, True: 0}
    for path in entries:
        if path.name == keep_key or str(path) in running:
            continue
        scoped = (path / SCOPED_MARK).is_file()
        limit = REVISION_SCOPED_KEEP if scoped else REVISION_CACHE_KEEP
        if kept[scoped] >= limit or time.time() - path.stat().st_mtime > REVISION_CACHE_TTL:
            shutil.rmtree(path)
        else:
            kept[scoped] += 1


def revision_status(D: RevisionDoc, commit: str, pin: int | None, ctx: RevisionContext) -> Json | StatusRefusal:
    """GET /api/revision-build: the running job's status or the cached one, re-authorising the commit (and pin) on
    every poll."""
    spec = core.revision_spec(D, commit, pin, ctx)  # Reauthorize cache hits and poll requests too.
    if not isinstance(spec, RevisionSpec):
        return spec
    with ctx.jobs.lock:
        root = revision_cache_root(D)
        if isinstance(root, UnsafeCache):
            return root
        running = ctx.jobs.active.get(str(root / spec.key))
        return status_body(running if running is not None else revision_cached(spec, root), spec)


def revision_start(D: RevisionDoc, commit: str, pin: int | None, ctx: RevisionContext) -> Json | StartRefusal:
    """POST /api/revision-build: returns the running job's status, or the cached one when answered_from_cache says so,
    or starts a worker thread and returns "running". Refused when both build slots or this document's lock are taken,
    for an unsafe cache folder, and for what revision_spec refuses."""
    spec = core.revision_spec(D, commit, pin, ctx)
    if not isinstance(spec, RevisionSpec):
        return spec
    with ctx.jobs.lock:
        root = revision_cache_root(D)
        if isinstance(root, UnsafeCache):
            return root
        running = ctx.jobs.active.get(str(root / spec.key))
        if running is not None:
            return status_body(running, spec)
        cached = revision_cached(spec, root)
        if answered_from_cache(cached, bool(spec.scope)):
            return status_body(cached, spec)
        started = _start_job(spec, root, cached, ctx)
        return status_body(started, spec) if isinstance(started, RunningComparison) else started


def _start_job(
    spec: RevisionSpec, root: Path, cached: CachedComparison, ctx: RevisionContext
) -> RunningComparison | AllSlotsBusy | DocumentBusy | UnsafeCache:
    """Claims one of the process's build slots and the document's build lock, prunes the cache, makes spec's empty job
    folder and starts the worker thread, which owns the claims from then on (_run_job frees them). Every return or
    exception before the thread starts frees what was claimed so far, in reverse order (ExitStack). The caller holds
    ctx.jobs.lock; cached is the status the job replaces (its fields seed the running status)."""
    jobs, jobdir = ctx.jobs, root / spec.key
    with contextlib.ExitStack() as claimed:
        if not jobs.slots.acquire(blocking=False):
            return AllSlotsBusy()
        claimed.callback(jobs.slots.release)
        # A second server sharing a state directory must not prune or replace this job.
        lock = claimed.enter_context((root / "build.lock").open("a"))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return DocumentBusy()
        revision_prune(root, spec.key, jobs.active)
        if jobdir.is_symlink():
            return UnsafeCache()
        if jobdir.exists():
            shutil.rmtree(jobdir)
        jobdir.mkdir()
        if spec.scope:
            (jobdir / SCOPED_MARK).write_text("")
        running = RunningComparison(
            dict(_without_meta(status_body(cached, spec)), state="running", error=None, reason=None, warnings=[])
        )
        jobs.active[str(jobdir)] = running
        claimed.callback(jobs.active.pop, str(jobdir), None)
        timeout = min(180, max(1, ctx.timeout))
        owned = claimed.pop_all()  # from here the worker frees the slot, the lock and the active entry
    try:
        threading.Thread(target=_run_job, args=(spec, jobdir, timeout, running, ctx, owned), daemon=True).start()
    except BaseException:
        owned.close()
        raise
    return running


def _finished(built: ComparisonBuilt | BuildFailure, running: RunningComparison, ctx: RevisionContext) -> Json:
    """The final status fields of a job whose build returned: running's fields with the build's warnings ("ready"), or
    with the text and API reason ctx.describe gives the failure ("error")."""
    if isinstance(built, ComparisonBuilt):
        return {**running.fields, "state": "ready", "warnings": built.warnings, "error": None, "reason": None}
    message, reason = ctx.describe(built)
    return {**running.fields, "state": "error", "error": message, "reason": reason, "warnings": []}


def _run_job(
    spec: RevisionSpec,
    jobdir: Path,
    timeout: int,
    running: RunningComparison,
    ctx: RevisionContext,
    owned: contextlib.ExitStack,
) -> None:
    """The worker thread of one comparison: runs the build, stores its final status in jobdir/status.json, and frees
    what _start_job claimed for it (owned: the active entry, the document's build lock, the slot) under ctx.jobs.lock.
    An expected failure becomes an "error" status with the text ctx.describe gives it; anything else is build_failed.
    A status that cannot be written leaves the entry uncached (the next request builds again)."""
    try:
        try:
            result = _finished(execution.revision_compile(spec, jobdir, timeout), running, ctx)
        except Exception:
            traceback.print_exc()
            result = {
                **running.fields,
                "state": "error",
                "error": "비교 PDF를 만들지 못했습니다.",
                "reason": "build_failed",
                "warnings": [],
            }
        with contextlib.suppress(OSError):
            atomic_write(jobdir / "status.json", json.dumps(result, ensure_ascii=False))
    finally:
        with ctx.jobs.lock:
            owned.close()


def revision_pdf(D: RevisionDoc, commit: str, pin: int | None, ctx: RevisionContext) -> bytes | PdfRefusal:
    """GET /api/revision-pdf: the finished comparison PDF of the commit (or of the pin's part of it). Refused when it is
    not ready, has expired or cannot be read, and for what revision_spec refuses."""
    spec = core.revision_spec(D, commit, pin, ctx)
    if not isinstance(spec, RevisionSpec):
        return spec
    with ctx.jobs.lock:
        root = revision_cache_root(D)
        if isinstance(root, UnsafeCache):
            return root
        if not isinstance(revision_cached(spec, root), ReadyComparison):
            return RevisionNotReady()
        try:
            return (root / spec.key / "revision.pdf").read_bytes()
        except OSError:
            return RevisionPdfMissing()
