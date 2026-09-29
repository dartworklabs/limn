"""Revision result types, scoped git history and source diff for one document.

Git reads use bounded subprocess calls; the comparison snapshot and PDF live in execution.py,
and the cache and worker lifecycle live in jobs.py. Request settings arrive through RevisionContext.
"""

import contextlib
import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Protocol, TypeAlias

from limn import scope
from limn.gitrun import GIT_TIMEOUT, git, git_command, git_env, open_git
from limn.pins.model import is_region_pin
from limn.scope import (
    FileChange,
    PinFacts,
    PinNotInDoc,
    PinScope,
    RepoRange,
    ScopeItem,
    ScopeMeta,
    ScopeRefusal,
    git_lines,
    parse_raw_entries,
    parse_u0_blocks,
    pin_facts,
    pin_scope,
    recorded_changes,
    scope_meta,
    scope_payload,
)
from limn.store import find_pin

if TYPE_CHECKING:
    from limn.features.revisions.jobs import RunningComparison

Record: TypeAlias = Mapping[str, Any]
Json: TypeAlias = dict[str, Any]

REVISION_ID_RE = re.compile(r"[0-9a-f]{40}")
SCOPE_FILES_MAX = 60  # a commit touching more manuscript files than this stays a whole-commit view
SCOPE_BYTES_MAX = 16 * 1024 * 1024  # both sides of every changed file together
SCOPE_CACHE_KEEP = 32  # entries: counts, block key and the two patches, each cut at REVISION_DIFF_MAX + 1 bytes
SCOPE_SLOTS = 2  # scope computations (cache misses) reading git at once; more wait, then show whole
SCOPE_SECONDS_MAX = 60  # reading one commit's files for scoping, all git calls together
REVISION_CACHE_VERSION = "latex-pdf-v1"
REVISION_FILES_MAX = 4000
REVISION_TREE_MAX = 256 * 1024 * 1024
REVISION_FILE_MAX = 64 * 1024 * 1024
REVISION_PDF_MAX = 32 * 1024 * 1024
REVISION_CACHE_KEEP = 6
REVISION_SCOPED_KEEP = 6  # pin-scoped comparisons, counted apart so they never evict whole-commit ones
SCOPED_MARK = "scoped"  # empty file in a pin-scoped comparison's cache folder
REVISION_CACHE_TTL = 24 * 3600
SCOPE_META = ("scope", "pin", "source", "hunks", "other")  # per-request fields; never stored in a (shared) status


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
    "tool_start",
    "timeout",
    "size",
    "snapshot_read",
    "unsafe_snapshot",
    "snapshot_size",
    "snapshot_timeout",
    "snapshot_blob",
    "missing_main",
    "sandbox_tools",
    "sandbox_system",
    "diff_failed",
    "compile_failed",
    "invalid_pdf",
]


@dataclass(frozen=True)
class StepFailed:
    """A step of a comparison build (or of reading a commit for it) failed. Every kind is handled the same way - the
    build records an "error" status - so one type carries the kind; limn.web.errors.REVISION_FAILURES gives each kind
    its text and API reason."""

    kind: FailureKind


BuildFailure: TypeAlias = StepFailed | ScopeRefusal


@dataclass(frozen=True)
class ComparisonBuilt:
    """A comparison build succeeded: its PDF is jobdir/revision.pdf, and warnings are what its "ready" status shows
    (the fixed notes first, then the final engine log's warning lines)."""

    warnings: list[str]


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
        self.active: dict[str, RunningComparison] = {}
        self.slots = threading.BoundedSemaphore(slots)


@dataclass(frozen=True)
class RevisionContext:
    """What a revision service needs from the instance, made per request by the composition root."""

    timeout: int  # --build-timeout; a comparison is bounded by min(180, it)
    pins: Callable[[], list[Json]]  # the pin records as the API shows them (read only for a pin request)
    doc_of: Callable[[Record], str]  # the document key a pin record belongs to
    locate: Callable[[str, RevisionDoc], Path | None]  # where a recorded absolute path of document D is now, or None
    cache: ScopeCache
    jobs: RevisionJobs
    describe: Callable[[BuildFailure], tuple[str, str]]  # (message, API reason) a failed build records


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
    paths: tuple[str, ...] = ()  # the manuscript pathspec (revision_scope) - a scoped build re-reads the commit with it
    scope: tuple[ScopeItem, ...] = ()  # v0.3: the pin's blocks (scope_key); () = the whole commit
    pin: int | None = None  # the pin that asked, when the request named one
    meta: ScopeMeta | None = None  # additive status fields for a pin request: scope, pin, source, hunks, other


# ---------------------------------------------------------------- history and the source diff


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


def _stop_git_group(proc: subprocess.Popen[bytes]) -> None:
    """Stop a streamed Git command and its descendants; an already exited group needs no cleanup."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


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
    cmd = [
        "-C",
        str(repo),
        "show",
        "--format=",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--unified=3",
        commit,
        "--",
    ] + paths
    chunks: list[bytes] = []
    try:
        with open_git(cmd, repo) as proc:
            assert proc.stdout is not None  # stdout=PIPE
            size = 0
            deadline = time.monotonic() + GIT_TIMEOUT
            try:
                with selectors.DefaultSelector() as sel:
                    sel.register(proc.stdout, selectors.EVENT_READ)
                    while size <= cap:
                        ready = sel.select(max(0, deadline - time.monotonic()))
                        if not ready:
                            raise subprocess.TimeoutExpired(git_command(cmd), GIT_TIMEOUT)
                        part = os.read(proc.stdout.fileno(), min(65536, cap + 1 - size))
                        if not part:
                            break
                        chunks.append(part)
                        size += len(part)
                too_large = size > cap
                if too_large:
                    _stop_git_group(proc)
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except (OSError, subprocess.TimeoutExpired):
                _stop_git_group(proc)
                proc.wait()
                raise
            if proc.returncode != 0 and not too_large:
                return DiffFailed()
    except (OSError, subprocess.TimeoutExpired):
        return DiffUnavailable()
    out: Json = {"id": commit, "diff": b"".join(chunks)[:cap].decode("utf-8", errors="replace"), "truncated": too_large}
    if pin is not None:
        base, rows = revision_first_parent(repo, commit), ctx.pins()  # current paths (ADR-0006)
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
    ran = git_exec(["cat-file", "blob", oid], repo, 15, budget[0] + 4096)
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
        ran = git_exec(
            ["diff", "--raw", "-z", "-M", "--abbrev=40", "--no-ext-diff", base, head, "--"] + list(paths),
            repo,
            30,
            2 * 1024 * 1024,
        )
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
            if not text:  # symlink or submodule: never lines (the whole-commit snapshot refuses it)
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
                ran = git_exec(
                    [
                        "diff",
                        "-U0",
                        "--inter-hunk-context=0",
                        "--no-color",
                        "--no-ext-diff",
                        "--no-textconv",
                        old_oid,
                        new_oid,
                    ],
                    repo,
                    30,
                    4 * scope.REVISION_DIFF_MAX + len(old) + len(new),
                )
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


def revision_pin_scope(
    D: RevisionDoc,
    rows: list[Json],
    repo: Path,
    paths: Sequence[str],
    base: str,
    head: str,
    pid: int,
    revisions: Sequence[Record],
    ctx: RevisionContext,
) -> PinScope | PinNotInDoc:
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
            blocks = sc.blocks  # keyed by the block set, not the pin: pins on the same fix share it
            identity += ["blocks", [list(b) for b in blocks]]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return RevisionSpec(repo, source, main, base, commit, key, paths, blocks, pin, meta)


def revision_exec(
    cmd: list[str], cwd: Path, timeout: float, limit: int = 8 * 1024 * 1024, env: Mapping[str, str] | None = None
) -> tuple[int, bytes, bytes] | StepFailed:
    """Run cmd without a shell, without stdin and in its own session, with both pipes and the lifetime bounded:
    (returncode, stdout, stderr), or the step failure - the tool could not start, it ran past timeout seconds, or its
    output passed limit bytes. The whole process group is killed on every exit. env replaces the environment (None:
    the server's, as the sandboxed comparison build gets it; git_exec passes limn.gitrun's)."""
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
    except OSError:
        return StepFailed("tool_start")
    assert proc.stdout is not None and proc.stderr is not None  # stdout/stderr=PIPE
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
                    buffers[key.fileobj].extend(chunk)  # type: ignore[index]  # the keys are the two pipes
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
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        for pipe in buffers:
            pipe.close()


def git_exec(args: Sequence[str], cwd: Path, timeout: float, limit: int) -> tuple[int, bytes, bytes] | StepFailed:
    """`git <args>` through revision_exec's bounded pipes, in limn.gitrun's environment (GIT_TERMINAL_PROMPT=0, the
    server's GIT_* variables dropped): (returncode, stdout, stderr) or the step failure."""
    return revision_exec(git_command(args), cwd, timeout, limit, env=git_env())
