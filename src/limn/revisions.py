"""A document's manuscript history in git: recent commits, one commit's source diff (optionally scoped to one pin), and
comparison PDFs built from two versions of the manuscript (docs/handbook/api.md §변경 보기와 비교 PDF).

This is the git edge: it runs git and the TeX sandbox, reads and writes the comparison cache under the document's
state folder, and runs one build per job in a worker thread. Which hunks belong to a pin is decided by the pure
limn.scope. Everything a request can be refused for is a returned value (the refusal sets below); the HTTP layer
answers each (limn.web.answers.revision_answer). A failed comparison build is recorded in its cache as an "error"
status with the text the RevisionContext's describe() gives - the texts are the agent contract's, kept in
limn.web.errors next to the HTTP answers.

Nothing here reads server.py's settings or the thread's current document: the document is an argument, and what the
instance supplies - its pins, where a recorded path is now, the process's scope cache and job registry, the build
timeout - comes in a RevisionContext made per request by the composition root (server.revision_context).
git runs without a shell; only full SHA-1s that git itself listed, and git's own object ids, reach its arguments.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol, TypeAlias

from limn import scope
from limn.files import atomic_write
from limn.pins.model import is_region_pin
from limn.scope import (
    FileChange, PinFacts, PinNotInDoc, PinScope, RepoRange, ScopeItem, ScopeMeta, ScopeRefusal, ScopeUnwritable,
    UnsafePath, git_lines, parse_raw_entries, parse_u0_blocks, pin_facts, pin_scope, plan_scope_writes, recorded_changes,
    scope_meta, scope_payload,
)
from limn.store import find_pin

Record: TypeAlias = Mapping[str, Any]
Json: TypeAlias = dict[str, Any]

GIT_TIMEOUT = 30                      # seconds - one git call (a history read, a diff, a --git-pull fetch)
REVISION_ID_RE = re.compile(r"[0-9a-f]{40}")
SCOPE_FILES_MAX = 60                  # a commit touching more manuscript files than this stays a whole-commit view
SCOPE_BYTES_MAX = 16 * 1024 * 1024    # both sides of every changed file together
SCOPE_CACHE_KEEP = 32                 # entries: counts, block key and the two patches, each cut at REVISION_DIFF_MAX + 1 bytes
SCOPE_SLOTS = 2                       # scope computations (cache misses) reading git at once; more wait, then show whole
SCOPE_SECONDS_MAX = 60                # reading one commit's files for scoping, all git calls together
REVISION_CACHE_VERSION = "latex-pdf-v1"
REVISION_FILES_MAX = 4000
REVISION_TREE_MAX = 256 * 1024 * 1024
REVISION_FILE_MAX = 64 * 1024 * 1024
REVISION_PDF_MAX = 32 * 1024 * 1024
REVISION_CACHE_KEEP = 6
REVISION_SCOPED_KEEP = 6              # pin-scoped comparisons, counted apart so they never evict whole-commit ones
SCOPED_MARK = "scoped"                # empty file in a pin-scoped comparison's cache folder
REVISION_CACHE_TTL = 24 * 3600
SCOPE_META = ("scope", "pin", "source", "hunks", "other")   # per-request fields; never stored in a (shared) status


class RevisionDoc(Protocol):
    """A document as the revision services read it (server.Doc)."""

    @property
    def key(self) -> str:
        """The document key; a pin belongs to one document."""
        ...

    @property
    def is_pdf(self) -> bool:
        """A view-only PDF document has no manuscript history."""
        ...

    @property
    def src(self) -> Path:
        """The build root - the folder copied for a build, and the root of a comparison's snapshots."""
        ...

    @property
    def main(self) -> Path:
        """The main .tex; its folder scopes the history."""
        ...

    @property
    def dir(self) -> Path:
        """The document's state folder; comparisons are cached under its revisions/."""
        ...


# ---------------------------------------------------------------- outcomes

@dataclass(frozen=True)
class NoHistory:
    """The document has no manuscript history to show: a view-only PDF, a main file outside its build root, or a
    folder outside any git repository."""


@dataclass(frozen=True)
class CommitNotRecent:
    """The commit is not among the document's recent commits - arbitrary objects and other documents' history are
    never read."""


@dataclass(frozen=True)
class DiffFailed:
    """git could not show the commit (it exited with an error)."""


@dataclass(frozen=True)
class DiffUnavailable:
    """git could not be started, or did not finish showing the commit in time."""


@dataclass(frozen=True)
class NotInRepo:
    """The document's build root or main file does not lie inside the repository, so no snapshot can be taken."""


@dataclass(frozen=True)
class NoParent:
    """The commit is the repository's first: there is no earlier manuscript to compare with."""


@dataclass(frozen=True)
class UnsafeCache:
    """The comparison cache folder (or a job's folder in it) is a symlink; it is never followed."""


@dataclass(frozen=True)
class AllSlotsBusy:
    """Both comparison build slots of the process are taken."""


@dataclass(frozen=True)
class DocumentBusy:
    """Another process sharing this state folder is building this document's comparison (its lock file is held)."""


@dataclass(frozen=True)
class RevisionNotReady:
    """No finished comparison PDF for this commit (and pin) is in the cache: never built, still running, failed or
    expired."""


@dataclass(frozen=True)
class RevisionPdfMissing:
    """The cache says the comparison is ready, but its PDF could not be read."""


DiffRefusal: TypeAlias = NoHistory | CommitNotRecent | DiffFailed | DiffUnavailable | PinNotInDoc
SpecRefusal: TypeAlias = CommitNotRecent | NotInRepo | NoParent | PinNotInDoc
StatusRefusal: TypeAlias = SpecRefusal | UnsafeCache
StartRefusal: TypeAlias = SpecRefusal | UnsafeCache | AllSlotsBusy | DocumentBusy
PdfRefusal: TypeAlias = SpecRefusal | UnsafeCache | RevisionNotReady | RevisionPdfMissing
RevisionRefusal: TypeAlias = DiffRefusal | StartRefusal | PdfRefusal

FailureKind: TypeAlias = Literal[
    "tool_start", "timeout", "size", "snapshot_read", "unsafe_snapshot", "snapshot_size", "snapshot_timeout",
    "snapshot_blob", "missing_main", "sandbox_tools", "sandbox_system", "diff_failed", "compile_failed", "invalid_pdf",
]


@dataclass(frozen=True)
class StepFailed:
    """A step of a comparison build (or of reading a commit for it) failed. Every kind is handled the same way - the
    build records an "error" status - so one type carries the kind; limn.web.errors.REVISION_FAILURES gives each kind
    its text and API reason."""
    kind: FailureKind


BuildFailure: TypeAlias = StepFailed | ScopeRefusal


class ScopeCache:
    """Pin scopes already decided, keyed by (repo, base, head, pin facts) - commits are immutable, so an entry stays
    right until evicted (oldest first beyond keep). Holds only complete answers: a commit that could not be read
    (timeout, size) is not stored, so the next request tries again. slot() bounds how many cache misses read git at
    once; waiting longer than SCOPE_SECONDS_MAX gives up (the caller shows the whole commit, uncached). The composition
    root makes the process's one instance."""

    def __init__(self, keep: int = SCOPE_CACHE_KEEP, slots: int = SCOPE_SLOTS) -> None:
        """An empty cache of at most keep entries with `slots` git-reading slots."""
        self._rows: dict[tuple[str, ...], PinScope] = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(slots)
        self.keep = keep

    def get(self, key: tuple[str, ...]) -> PinScope | None:
        """The stored scope for key, or None."""
        with self._lock:
            return self._rows.get(key)

    def put(self, key: tuple[str, ...], value: PinScope) -> None:
        """Stores value, evicting the oldest entry when full."""
        with self._lock:
            if key not in self._rows and len(self._rows) >= self.keep:
                self._rows.pop(next(iter(self._rows)))
            self._rows[key] = value

    @contextlib.contextmanager
    def slot(self) -> Iterator[bool]:
        """Yields True while holding one of the git-reading slots, or False after waiting SCOPE_SECONDS_MAX."""
        got = self._slots.acquire(timeout=SCOPE_SECONDS_MAX)
        try:
            yield got
        finally:
            if got:
                self._slots.release()

    def values(self) -> list[PinScope]:
        """The stored scopes (tests and diagnostics)."""
        with self._lock:
            return list(self._rows.values())

    def clear(self) -> None:
        """Forgets every stored scope."""
        with self._lock:
            self._rows.clear()


class RevisionJobs:
    """The process's comparison builds in progress: a lock, the running jobs' statuses by cache folder (finished ones
    live only in the bounded cache) and the build slots. The composition root makes the one instance."""

    def __init__(self, slots: int = 2) -> None:
        """No job running, `slots` builds allowed at once."""
        self.lock = threading.RLock()
        self.active: dict[str, Json] = {}
        self.slots = threading.BoundedSemaphore(slots)


@dataclass(frozen=True)
class RevisionContext:
    """What a revision service needs from the instance, made per request by the composition root."""
    timeout: int                                           # --build-timeout; a comparison is bounded by min(180, it)
    pins: Callable[[], list[Json]]                          # the pin records as the API shows them (read only for a pin request)
    doc_of: Callable[[Record], str]                         # the document key a pin record belongs to
    locate: Callable[[str, RevisionDoc], Path | None]       # where a recorded absolute path of document D is now, or None
    cache: ScopeCache
    jobs: RevisionJobs
    describe: Callable[[BuildFailure], tuple[str, str]]     # (message, API reason) a failed build records


class RevisionSpec(NamedTuple):
    """One comparison to build: repo, build root (source, relative to repo) and main (relative to it), the first parent
    base and the commit head, and key - the cache identity (revision_spec). For a pin that owns part of the commit,
    scope names the blocks the new side applies; meta carries the per-request status fields for a pin request."""
    repo: Path
    source: str
    main: Path
    base: str
    head: str
    key: str
    paths: tuple[str, ...] = ()       # the manuscript pathspec (revision_scope) - a scoped build re-reads the commit with it
    scope: tuple[ScopeItem, ...] = ()  # v0.3: the pin's blocks (scope_key); () = the whole commit
    pin: int | None = None            # the pin that asked, when the request named one
    meta: ScopeMeta | None = None     # additive status fields for a pin request: scope, pin, source, hunks, other


# ---------------------------------------------------------------- history and the source diff

def git(args: Sequence[str], cwd: Path | str, timeout: float = GIT_TIMEOUT) -> tuple[int | None, str, str]:
    """Run git without a shell. Never puts user input into the args. Returns (returncode, stdout, stderr).
    Timeout and exec failure are both distinguished by returncode=None."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=str(cwd), timeout=timeout, capture_output=True, text=True, check=False)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.TimeoutExpired, OSError):
        return None, "", ""


def revision_scope(D: RevisionDoc) -> tuple[Path, list[str]] | None:
    """Returns a Git pathspec scoped to just the manuscript text inside the chosen main .tex's folder.

    D.src is the build-copy scope, so multiple documents can share the same root. The change history must
    be filtered to D.main.parent, or commits from the body, highlights, and cover letter get mixed together."""
    if D.is_pdf:
        return None
    root = D.main.resolve().parent
    try:
        root.relative_to(D.src.resolve())
    except ValueError:
        return None
    rc, top, _ = git(["-C", str(root), "rev-parse", "--show-toplevel"], root)
    if rc != 0 or not top.strip():
        return None
    repo = Path(top.strip()).resolve()
    try:
        prefix = root.relative_to(repo).as_posix()
    except ValueError:
        return None
    prefix = "" if prefix == "." else prefix + "/"
    # Git :(glob) ** only matches subfolders, so root files are included via a separate pattern.
    exts = ("tex", "bib", "sty", "cls", "bst")
    paths = [":(glob)%s*.%s" % (prefix, ext) for ext in exts]
    paths += [":(glob)%s**/*.%s" % (prefix, ext) for ext in exts]
    return repo, paths


def revision_history(D: RevisionDoc) -> Json:
    """GET /api/revisions: the document's 12 most recent manuscript commits {id, date, subject}, newest first, or
    available: false when it has no history."""
    found = revision_scope(D)
    if found is None:
        return {"available": False, "revisions": []}
    repo, paths = found
    rc, out, _ = git(["-C", str(repo), "log", "-12", "--format=%H%x1f%cs%x1f%s", "--"] + paths, repo)
    if rc != 0:
        return {"available": False, "revisions": []}
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) == 3 and REVISION_ID_RE.fullmatch(parts[0]):
            rows.append({"id": parts[0], "date": parts[1], "subject": parts[2][:180]})
    return {"available": True, "revisions": rows}


def revision_diff(D: RevisionDoc, commit: str, pin: int | None, ctx: RevisionContext) -> Json | DiffRefusal:
    """GET /api/revision-diff: the selected commit's unified diff (commit is a full SHA-1, checked by the request
    parser). With pin (v0.3), an additive `scope` says which of its hunks belong to that pin (scope_payload); the
    whole-commit `diff` is returned unchanged either way. Only a commit in the document's recent list is read."""
    found = revision_scope(D)
    if found is None:
        return NoHistory()
    repo, paths = found
    # Only read commits that appear in the current document's recent list. Never exposes arbitrary Git objects or another document's history.
    revisions = revision_history(D)["revisions"]
    if commit not in {row["id"] for row in revisions}:
        return CommitNotRecent()
    cap = scope.REVISION_DIFF_MAX
    cmd = ["git", "-C", str(repo), "show", "--format=", "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=3",
           commit, "--"] + paths
    chunks: list[bytes] = []
    try:
        with subprocess.Popen(cmd, cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
            assert proc.stdout is not None                # stdout=PIPE
            size = 0
            deadline = time.monotonic() + GIT_TIMEOUT
            try:
                with selectors.DefaultSelector() as sel:
                    sel.register(proc.stdout, selectors.EVENT_READ)
                    while size <= cap:
                        ready = sel.select(max(0, deadline - time.monotonic()))
                        if not ready:
                            raise subprocess.TimeoutExpired(cmd, GIT_TIMEOUT)
                        part = os.read(proc.stdout.fileno(), min(65536, cap + 1 - size))
                        if not part:
                            break
                        chunks.append(part)
                        size += len(part)
                too_large = size > cap
                if too_large:
                    proc.kill()
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
                proc.wait()
                raise
            if proc.returncode != 0 and not too_large:
                return DiffFailed()
    except (OSError, subprocess.TimeoutExpired):
        return DiffUnavailable()
    out: Json = {"id": commit, "diff": b"".join(chunks)[:cap].decode("utf-8", errors="replace"), "truncated": too_large}
    if pin is not None:
        base, rows = revision_first_parent(repo, commit), ctx.pins()   # current paths (ADR-0006)
        if base:
            sc = revision_pin_scope(D, rows, repo, paths, base, commit, pin, revisions, ctx)
        else:
            record = scope_pin_record(rows, D, pin, ctx.doc_of)
            sc = record if isinstance(record, PinNotInDoc) else PinScope(record["id"], "commit", "none", 0, 0)
        if isinstance(sc, PinNotInDoc):
            return sc
        out["scope"] = scope_payload(sc)
    return out


# ---------------------------------------------------------------- the git edge of pin scoping

def _blob(repo: Path, oid: str, budget: list[int]) -> bytes | None:
    """The bytes of one git blob, charged against budget[0] (bytes left for the whole commit, updated in place). None
    when git fails, times out, or the budget runs out - revision_changes() then shows the whole commit."""
    ran = revision_exec(["git", "cat-file", "blob", oid], repo, 15, budget[0] + 4096)
    if isinstance(ran, StepFailed) or ran[0] != 0:
        return None
    data = ran[1]
    budget[0] -= len(data)
    if budget[0] < 0:
        return None
    return data


def revision_changes(repo: Path, base: str, head: str, paths: Sequence[str]) -> list[FileChange] | None:
    """The commit's manuscript files as FileChange values (renames detected), or None when they cannot be read or are
    over the scoping limits - the caller then shows the whole commit, exactly as before 0.3. git runs without a
    shell; only full SHA-1s from revision_history() and git's own object ids reach its arguments."""
    try:
        ran = revision_exec(["git", "diff", "--raw", "-z", "-M", "--abbrev=40", "--no-ext-diff", base, head, "--"]
                            + list(paths), repo, 30, 2 * 1024 * 1024)
        if isinstance(ran, StepFailed) or ran[0] != 0:
            return None
        entries = parse_raw_entries(ran[1])
        if len(entries) > SCOPE_FILES_MAX:
            return None
        budget, zero, files = [SCOPE_BYTES_MAX], "0" * 40, []
        deadline = time.monotonic() + SCOPE_SECONDS_MAX
        for old_path, new_path, old_oid, new_oid, modes, text in entries:
            if time.monotonic() > deadline:
                return None
            if not text:                          # symlink or submodule: never lines (the whole-commit snapshot refuses it)
                files.append(FileChange(old_path, new_path, (), (), (), False, modes))
                continue
            old = _blob(repo, old_oid, budget) if old_path is not None and old_oid != zero else b""
            if old is None:
                return None
            new = _blob(repo, new_oid, budget) if new_path is not None and new_oid != zero else b""
            if new is None:
                return None
            if b"\0" in old[:8000] or b"\0" in new[:8000]:
                files.append(FileChange(old_path, new_path, (), (), (), True, modes))
                continue
            if old == new:
                blocks = []
            elif old_path is None or new_path is None:
                blocks = [scope.Block(0, len(git_lines(old)), 0, len(git_lines(new)))]
            else:
                # --inter-hunk-context=0: a diff.interHunkContext setting must not merge two pins' blocks into one
                ran = revision_exec(["git", "diff", "-U0", "--inter-hunk-context=0", "--no-color", "--no-ext-diff",
                                     "--no-textconv", old_oid, new_oid], repo, 30,
                                    4 * scope.REVISION_DIFF_MAX + len(old) + len(new))
                if isinstance(ran, StepFailed) or ran[0] != 0:
                    return None
                blocks = parse_u0_blocks(ran[1])
            files.append(FileChange(old_path, new_path, git_lines(old), git_lines(new), tuple(blocks), False, modes))
        return files
    except (ValueError, UnicodeError):
        return None


def _repo_rel(repo: Path, path: str) -> str | None:
    """path (absolute, as stored on pins) relative to the repository root in POSIX form, symlinks resolved; None when
    it lies outside the repository or cannot be resolved."""
    try:
        return Path(path).resolve().relative_to(repo.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError, TypeError):
        return None


def scope_pin_record(rows: list[Json], D: RevisionDoc, pid: int, doc_of: Callable[[Record], str]) -> Json | PinNotInDoc:
    """The pin a scoped request names, from rows (the pin records as the caller read them, without the sync write),
    or PinNotInDoc when there is no such pin or it belongs to another document than D (doc_of gives a record's)."""
    r = find_pin(rows, pid)
    if r is None or doc_of(r) != D.key:
        return PinNotInDoc()
    return r


def revision_pin_scope(D: RevisionDoc, rows: list[Json], repo: Path, paths: Sequence[str], base: str, head: str,
                       pid: int, revisions: Sequence[Record], ctx: RevisionContext) -> PinScope | PinNotInDoc:
    """How pin pid of document D sees commit head (compared with its first parent base). rows are the pin records,
    revisions the document's recent commits (revision_history); the recorded changes count only on the commit the
    pin's close_ref names. Their absolute paths are located by ctx.locate - the same rule as the pin's own file
    (issue #24) - so a moved or cloned checkout keeps the agent's lines; a path the rule cannot place is dropped and
    the pin's hunks are inferred as before. Unless the same pin facts were decided for this commit before (ctx.cache),
    reads the commit's files within one of the cache's slots and decides with limn.scope.pin_scope(); an unreadable
    commit is mode "commit" and not stored."""
    r = scope_pin_record(rows, D, pid, ctx.doc_of)
    if isinstance(r, PinNotInDoc):
        return r

    def repo_path(file: str) -> str | None:
        """A recorded change's path relative to the repository, located first; None if it cannot be placed."""
        path = ctx.locate(file, D)
        return _repo_rel(repo, str(path)) if path is not None else None
    changes = [RepoRange(repo_path(c["file"]), c["lo"], c["hi"]) for c in recorded_changes(r, head, revisions)]
    pin: PinFacts = pin_facts(r, _repo_rel(repo, r["file"]) if not is_region_pin(r) else None)
    key = (str(repo), base, head, json.dumps([pin, changes], default=str))
    hit = ctx.cache.get(key)
    if hit is not None:
        return hit
    with ctx.cache.slot() as got:
        files = revision_changes(repo, base, head, paths) if got else None
    out = pin_scope(files, pin, [c for c in changes if c.path])
    if files is not None:
        ctx.cache.put(key, out)
    return out


def revision_first_parent(repo: Path, commit: str) -> str | None:
    """The full SHA-1 of commit's first parent, or None for a root commit or when git cannot tell (the source diff
    then shows the whole commit for a pin)."""
    rc, out, _ = git(["rev-list", "--parents", "-n", "1", commit], repo)
    parents = out.strip().split()
    return parents[1] if rc == 0 and len(parents) >= 2 and REVISION_ID_RE.fullmatch(parents[1]) else None


# ---------------------------------------------------------------- comparison PDFs - independent from the current manuscript build

def revision_spec(D: RevisionDoc, commit: str, pin: int | None, ctx: RevisionContext) -> RevisionSpec | SpecRefusal:
    """What to compare. With pin (v0.3) the new side is old + only that pin's blocks - unless the pin owns the whole
    commit or none of it, in which case the spec (and its cache entry) is the whole-commit one. The cache identity of a
    scoped comparison is (commit, block set) - two pins with the same blocks share one PDF. Refused for a commit not in
    the document's recent list (as before 0.3; a malformed one was refused by the request parser), a build root outside
    the repository, a first commit, and a pin D does not have."""
    found = revision_scope(D)
    revisions = revision_history(D)["revisions"] if found is not None else []
    if found is None or commit not in {r["id"] for r in revisions}:
        return CommitNotRecent()
    repo, paths = found[0], tuple(found[1])
    try:
        source = D.src.resolve().relative_to(repo).as_posix()
        main = D.main.resolve().relative_to(D.src.resolve())
    except ValueError:
        return NotInRepo()
    rc, out, _ = git(["rev-list", "--parents", "-n", "1", commit], repo)
    parents = out.strip().split()
    if rc != 0 or len(parents) < 2 or not REVISION_ID_RE.fullmatch(parents[1]):
        return NoParent()
    base = parents[1]
    identity: list[Any] = [REVISION_CACHE_VERSION, str(repo), source, main.as_posix(), base, commit, "pdflatex"]
    blocks: tuple[ScopeItem, ...] = ()
    meta = None
    if pin is not None:
        sc = revision_pin_scope(D, ctx.pins(), repo, paths, base, commit, pin, revisions, ctx)
        if isinstance(sc, PinNotInDoc):
            return sc
        meta = scope_meta(sc)
        if sc.mode == "pin":
            blocks = sc.blocks                    # keyed by the block set, not the pin: pins on the same fix share it
            identity += ["blocks", [list(b) for b in blocks]]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return RevisionSpec(repo, source, main, base, commit, key, paths, blocks, pin, meta)


def revision_exec(cmd: list[str], cwd: Path, timeout: float, limit: int = 8 * 1024 * 1024) -> tuple[int, bytes, bytes] | StepFailed:
    """Run cmd without a shell with both pipes and the lifetime bounded: (returncode, stdout, stderr), or the step
    failure - the tool could not start, it ran past timeout seconds, or its output passed limit bytes. The whole process
    group is killed on every exit."""
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        return StepFailed("tool_start")
    assert proc.stdout is not None and proc.stderr is not None      # stdout/stderr=PIPE
    buffers = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    size, deadline = 0, time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as sel:
            for pipe in buffers:
                sel.register(pipe, selectors.EVENT_READ)
            while sel.get_map():
                left = deadline - time.monotonic()
                if left <= 0:
                    return StepFailed("timeout")
                for key, _ in sel.select(min(left, 1)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        sel.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    if size > limit:
                        return StepFailed("size")
                    buffers[key.fileobj].extend(chunk)       # type: ignore[index]  # the keys are the two pipes
            try:
                rc = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return StepFailed("timeout")
        return rc, bytes(buffers[proc.stdout]), bytes(buffers[proc.stderr])
    finally:
        # Also remove descendants left behind by a command that has already exited. An empty group is ESRCH; on macOS a
        # group whose members have all exited but are not yet reaped (a zombie leader on the early exits, an orphan
        # the system has not reaped yet) is EPERM. Either way nothing is left to kill, and the command's own answer
        # stands (EPERM raised here used to override it and turn a finished git read into a 500).
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        for pipe in buffers:
            pipe.close()


def revision_snapshot(spec: RevisionSpec, commit: str, dest: Path) -> None | StepFailed:
    """Write the build root of commit (spec.source) into the new folder dest from git objects - regular files only,
    within the file-count and size limits - and check that spec.main is there. The step failure otherwise."""
    prefix = "" if spec.source == "." else spec.source + "/"
    cmd = ["git", "ls-tree", "-r", "-l", "-z", commit]
    if prefix:
        cmd += ["--", ":(literal)" + spec.source]
    ran = revision_exec(cmd, spec.repo, 30, 2 * 1024 * 1024)
    if isinstance(ran, StepFailed):
        return ran
    rc, tree, _ = ran
    if rc != 0:
        return StepFailed("snapshot_read")
    entries, total = [], 0
    for row in tree.split(b"\0"):
        if not row:
            continue
        try:
            meta, rawname = row.split(b"\t", 1)
            mode, kind, oid, size = meta.split()
            name = rawname.decode("utf-8")
            if not name.startswith(prefix):
                raise ValueError()
            name = name[len(prefix):]
            path = Path(name)
            if (mode not in (b"100644", b"100755") or kind != b"blob" or path.is_absolute()
                    or not name or any(p in (".", "..", ".git") for p in name.split("/"))
                    or "\\" in name or any(ord(c) < 32 for c in name)):
                raise ValueError()
            n = int(size)
        except (ValueError, UnicodeError):
            return StepFailed("unsafe_snapshot")
        total += n
        entries.append((path, oid.decode("ascii"), n))
        if n > REVISION_FILE_MAX or total > REVISION_TREE_MAX or len(entries) > REVISION_FILES_MAX:
            return StepFailed("snapshot_size")
    dest.mkdir(parents=True)
    deadline = time.monotonic() + 60
    for path, oid_text, n in entries:
        if time.monotonic() >= deadline:
            return StepFailed("snapshot_timeout")
        ran = revision_exec(["git", "cat-file", "blob", oid_text], spec.repo,
                            min(15, max(.01, deadline - time.monotonic())), n + 4096)
        if isinstance(ran, StepFailed):
            return ran
        rc, data, _ = ran
        if rc != 0 or len(data) != n:
            return StepFailed("snapshot_blob")
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if not (dest / spec.main).is_file():
        return StepFailed("missing_main")
    return None


def revision_apply_scope(spec: RevisionSpec, dest: Path) -> None | ScopeRefusal:
    """Turns dest (a fresh snapshot of the old side) into old + only spec.scope's blocks: re-reads the commit from git
    (deterministic for two SHA-1s), lets limn.scope.plan_scope_writes() decide, and writes or removes those files under
    dest. Refused as ScopeUnreadable, ScopeMismatch, UnsafePath (also for a symlink or a parent outside dest) or
    ScopeUnwritable (an OSError while writing); the build worker records it like any other failure, and a pin's
    scope_failed is answered from the cache next time."""
    writes = plan_scope_writes(revision_changes(spec.repo, spec.base, spec.head, spec.paths), spec.scope, spec.source)
    if not isinstance(writes, list):
        return writes
    for w in writes:
        target = dest / w.rel
        if target.is_symlink() or not target.parent.resolve().is_relative_to(dest.resolve()):
            return UnsafePath()
        try:
            if w.data is None:
                if target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(w.data)
        except OSError:
            return ScopeUnwritable()
    return None


def revision_sandbox(work: Path, main_parent: Path, tool: str, args: list[str]) -> list[str] | StepFailed:
    """The bwrap command that runs tool (latexdiff or latexmk) on work: only the TeX installation and throwaway
    snapshots are visible; no host home or network. A missing sandbox or tool, or one outside /usr, is a step failure;
    any other tool is a programming error (ValueError)."""
    if tool not in ("latexdiff", "latexmk"):
        raise ValueError("unsupported revision tool")
    bwrap, found = shutil.which("bwrap"), shutil.which(tool)
    if not bwrap or not found:
        return StepFailed("sandbox_tools")
    exe = Path(found).resolve()
    if not exe.is_relative_to(Path("/usr")):
        return StepFailed("sandbox_system")
    cmd = [bwrap, "--unshare-all", "--die-with-parent", "--clearenv"]
    for path in ("/usr", "/bin", "/lib", "/lib64", "/etc/fonts", "/etc/texmf", "/var/lib/texmf", "/var/cache/fontconfig"):
        if Path(path).exists():
            cmd += ["--ro-bind", path, path]
    cmd += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--bind", str(work), "/work", "--chdir", "/work/new/" + main_parent.as_posix()]
    # latexmk invokes the engine by name; use the installation's public binary directory,
    # not a symlink-resolved Perl script directory.
    texbin = str(Path(shutil.which("latexmk") or "/usr/bin/latexmk").parent)
    for key, value in {"PATH": texbin + ":/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8",
                       "TEXMFVAR": "/tmp/texmf-var", "TEXMFCONFIG": "/tmp/texmf-config",
                       "openin_any": "p", "openout_any": "p"}.items():
        cmd += ["--setenv", key, value]
    return cmd + ["--", str(exe)] + args


def revision_compile(spec: RevisionSpec, jobdir: Path, timeout: int) -> Json | BuildFailure:
    """Builds the comparison PDF of spec into jobdir/revision.pdf (and jobdir/build.log) inside the bwrap sandbox:
    snapshots of both sides - for a pin scope, old + only its blocks (revision_apply_scope) - then latexdiff, then
    latexmk with timeout seconds. Returns the "ready" status fields with warnings, or the first step that failed (a
    StepFailed as before 0.3, or a ScopeRefusal from the scope step); the worker records either."""
    warnings = ["수식 내부와 같은 파일명의 그림 내용 변경은 강조되지 않을 수 있습니다. 그림·서지·스타일 변경은 소스 변경사항도 확인하세요."]
    with tempfile.TemporaryDirectory(prefix="work-", dir=jobdir) as tmp:
        work = Path(tmp)
        failed: BuildFailure | None = revision_snapshot(spec, spec.base, work / "old")
        if failed is None:
            if spec.scope:                        # v0.3: the new side is old + only the pin's blocks
                failed = revision_snapshot(spec, spec.base, work / "new") or revision_apply_scope(spec, work / "new")
            else:
                failed = revision_snapshot(spec, spec.head, work / "new")
        if failed is not None:
            return failed
        main = spec.main.as_posix()
        head_label = spec.head[:8] + ("+scoped" if spec.scope else "")
        args = ["--encoding=utf8", "--flatten", "--math-markup=off", "--add-to-config",
                "ARRENV=tabularx;tabular;tabular[*]", "--label", spec.base[:8], "--label", head_label,
                "/work/old/" + main, "/work/new/" + main]
        cmd = revision_sandbox(work, spec.main.parent, "latexdiff", args)
        if isinstance(cmd, StepFailed):
            return cmd
        ran = revision_exec(cmd, work, 60)
        if isinstance(ran, StepFailed):
            return ran
        rc, diff, err = ran
        log = err.decode("utf-8", errors="replace")
        if rc != 0 or b"\\begin{document}" not in diff or "Could not find" in log:
            atomic_write(jobdir / "build.log", log[-8000:])
            return StepFailed("diff_failed")
        if not re.search(rb"\\DIF(?:add|del)(?:begin|\{)", diff.split(b"\\begin{document}", 1)[1]):
            warnings.append("본문에 강조할 문장 차이가 없습니다. 서지·스타일 또는 주석만 바뀌었을 수 있습니다.")
        out = work / "new" / spec.main.parent
        # Tracked artifacts must never satisfy the fresh-PDF check or influence latexmk.
        for stale in out.glob("pin_revision.*"):
            if stale.is_file():
                stale.unlink()
        (out / "pin_revision.tex").write_bytes(diff)
        args = ["-norc", "-pdf", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "pin_revision.tex"]
        cmd = revision_sandbox(work, spec.main.parent, "latexmk", args)
        if isinstance(cmd, StepFailed):
            return cmd
        ran = revision_exec(cmd, work, timeout)
        if isinstance(ran, StepFailed):
            return ran
        rc, stdout, stderr = ran
        log += (stdout + stderr).decode("utf-8", errors="replace")
        atomic_write(jobdir / "build.log", log[-8000:])
        pdf = out / "pin_revision.pdf"
        if rc != 0 or not pdf.is_file() or pdf.stat().st_size > REVISION_PDF_MAX:
            return StepFailed("compile_failed")
        if not pdf.read_bytes().startswith(b"%PDF-"):
            return StepFailed("invalid_pdf")
        # Earlier latexmk passes normally contain unresolved citations. Report the final
        # engine log only, otherwise a successful BibTeX pass looks like a broken PDF.
        final_log = out / "pin_revision.log"
        final_text = (final_log.read_text(encoding="utf-8", errors="replace")
                      if final_log.is_file() and final_log.stat().st_size <= 8 * 1024 * 1024 else log)
        warning_lines = [line.strip() for line in final_text.splitlines()
                         if "Warning:" in line or "undefined" in line or "Missing character:" in line]
        warnings += list(dict.fromkeys(warning_lines))[:12]
        os.replace(pdf, jobdir / "revision.pdf")
    return {"state": "ready", "warnings": warnings, "error": None, "reason": None}


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


def revision_cached(spec: RevisionSpec, root: Path) -> Json:
    """The finished status of spec from its cache folder under root ("ready" only with a PDF of sane size), else an
    "idle" status; always with spec's identity and, for a pin request, its per-request fields. Reads files only;
    a corrupt, oversized, symlinked or expired entry is a miss."""
    path = root / spec.key
    identity = dict({"job_id": spec.key, "base": spec.base, "head": spec.head, "engine": "pdflatex"}, **(spec.meta or {}))
    try:
        status = path / "status.json"
        if path.is_symlink() or status.is_symlink() or status.stat().st_size > 32768:
            raise ValueError()
        data = json.loads(status.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("state") not in ("ready", "error") or time.time() - status.stat().st_mtime > REVISION_CACHE_TTL:
            raise ValueError()
        if data["state"] == "ready":
            pdf = path / "revision.pdf"
            if pdf.is_symlink() or not 0 < pdf.stat().st_size <= REVISION_PDF_MAX:
                raise ValueError()
        return dict(_without_meta(data), **identity)
    except (OSError, ValueError, TypeError):
        return dict(identity, state="idle", warnings=[], error=None, reason=None)


def revision_prune(root: Path, keep_key: str, running: Mapping[str, Json]) -> None:
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
    spec = revision_spec(D, commit, pin, ctx)         # Reauthorize cache hits and poll requests too.
    if not isinstance(spec, RevisionSpec):
        return spec
    with ctx.jobs.lock:
        root = revision_cache_root(D)
        if isinstance(root, UnsafeCache):
            return root
        active = ctx.jobs.active.get(str(root / spec.key))
        return dict(_without_meta(active), **(spec.meta or {})) if active else revision_cached(spec, root)


def revision_start(D: RevisionDoc, commit: str, pin: int | None, ctx: RevisionContext) -> Json | StartRefusal:
    """POST /api/revision-build: returns the running or cached status, or starts a worker thread and returns
    "running". A pin subset that failed deterministically is answered from the cache. Refused when both build slots
    or this document's lock are taken, for an unsafe cache folder, and for what revision_spec refuses."""
    spec = revision_spec(D, commit, pin, ctx)
    if not isinstance(spec, RevisionSpec):
        return spec
    jobs = ctx.jobs
    with jobs.lock:
        root = revision_cache_root(D)
        if isinstance(root, UnsafeCache):
            return root
        jobdir, jobkey = root / spec.key, str(root / spec.key)
        if jobkey in jobs.active:
            return dict(_without_meta(jobs.active[jobkey]), **(spec.meta or {}))
        cached = revision_cached(spec, root)
        if cached["state"] == "ready":
            return cached
        # A pin's subset that did not compile will not compile next time either (two SHA-1s, a fixed pipeline): answer
        # from the cache so the viewer falls back at once instead of spending a build slot again. Whole commits retry.
        if spec.scope and cached["state"] == "error" and cached.get("reason") in ("compile_failed", "diff_failed", "scope_failed"):
            return cached
        if not jobs.slots.acquire(blocking=False):
            return AllSlotsBusy()
        lock = None
        try:
            # A second server sharing a state directory must not prune or replace this job.
            lock = (root / "build.lock").open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                jobs.slots.release()
                return DocumentBusy()
            revision_prune(root, spec.key, jobs.active)
            if jobdir.is_symlink():
                lock.close()
                jobs.slots.release()
                return UnsafeCache()
            if jobdir.exists():
                shutil.rmtree(jobdir)
            jobdir.mkdir()
            if spec.scope:
                (jobdir / SCOPED_MARK).write_text("")
            running = dict(_without_meta(cached), state="running", error=None, reason=None, warnings=[])
            jobs.active[jobkey] = running
            timeout = min(180, max(1, ctx.timeout))
        except BaseException:
            if lock is not None and not lock.closed:
                lock.close()
            jobs.slots.release()
            raise
        held = lock

        def worker() -> None:
            """Runs the build, stores its final status in jobdir/status.json, and frees the slot and lock. An expected
            failure becomes an "error" status with the text ctx.describe gives it; anything else is build_failed."""
            try:
                built = revision_compile(spec, jobdir, timeout)
                if isinstance(built, dict):
                    result: Json = built
                else:
                    message, reason = ctx.describe(built)
                    result = {"state": "error", "error": message, "reason": reason, "warnings": []}
            except Exception:
                traceback.print_exc()
                result = {"state": "error", "error": "비교 PDF를 만들지 못했습니다.", "reason": "build_failed", "warnings": []}
            try:
                result = dict(running, **result)          # running carries no per-request pin fields (SCOPE_META)
                atomic_write(jobdir / "status.json", json.dumps(result, ensure_ascii=False))
            except OSError:
                pass
            finally:
                with jobs.lock:
                    jobs.active.pop(jobkey, None)
                    held.close()
                    jobs.slots.release()

        try:
            threading.Thread(target=worker, daemon=True).start()
        except BaseException:
            jobs.active.pop(jobkey, None)
            held.close()
            jobs.slots.release()
            raise
        return dict(running, **(spec.meta or {}))


def revision_pdf(D: RevisionDoc, commit: str, pin: int | None, ctx: RevisionContext) -> bytes | PdfRefusal:
    """GET /api/revision-pdf: the finished comparison PDF of the commit (or of the pin's part of it). Refused when it is
    not ready, has expired or cannot be read, and for what revision_spec refuses."""
    spec = revision_spec(D, commit, pin, ctx)
    if not isinstance(spec, RevisionSpec):
        return spec
    with ctx.jobs.lock:
        root = revision_cache_root(D)
        if isinstance(root, UnsafeCache):
            return root
        if revision_cached(spec, root)["state"] != "ready":
            return RevisionNotReady()
        try:
            return (root / spec.key / "revision.pdf").read_bytes()
        except OSError:
            return RevisionPdfMissing()
