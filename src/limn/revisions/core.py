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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Protocol, TypeAlias

from limn.pins import RevisionPin, RevisionPinQuery
from limn.platform.git import GIT_TIMEOUT, git, git_command, git_env, open_git
from limn.revisions.scope import (
    REVISION_DIFF_MAX as scope_REVISION_DIFF_MAX,
    Block as scope_Block,
    FileChange,
    PinNotInDoc,
    PinScope,
    RepoRange,
    ScopeItem,
    ScopeMeta,
    ScopeRefusal,
    git_lines,
    parse_raw_entries,
    parse_u0_blocks,
    pin_scope,
    scope_meta,
    scope_payload,
)
from limn.runtime.documents import Doc

if TYPE_CHECKING:
    from limn.revisions.jobs import RunningComparison

Record: TypeAlias = Mapping[str, Any]
Json: TypeAlias = dict[str, Any]

REVISION_ID_RE = re.compile(r"[0-9a-f]{40}")
SCOPE_FILES_MAX = 60  # a commit touching more manuscript files than this stays a whole-commit view
SCOPE_BYTES_MAX = 16 * 1024 * 1024  # both sides of every changed file together
SCOPE_CACHE_KEEP = 32  # entries: counts, block key and the two patches, each cut at REVISION_DIFF_MAX + 1 bytes
SCOPE_SLOTS = 2  # scope computations (cache misses) reading git at once; more wait, then show whole
SCOPE_SECONDS_MAX = 60  # reading one commit's files for scoping, all git calls together
REVISION_CACHE_VERSION = "latex-pdf-v2"  # v2: latexdiff marks inside the document's own text commands (issue #162)
REVISION_FILES_MAX = 4000
REVISION_TREE_MAX = 256 * 1024 * 1024
REVISION_FILE_MAX = 64 * 1024 * 1024
REVISION_PDF_MAX = 32 * 1024 * 1024
REVISION_CACHE_KEEP = 6
REVISION_SCOPED_KEEP = 6  # pin-scoped comparisons, counted apart so they never evict whole-commit ones
SCOPED_MARK = "scoped"  # empty file in a pin-scoped comparison's cache folder
REVISION_RANGED_KEEP = 4  # comparisons of a range (issue #188), counted apart so they never evict single-commit ones
RANGED_MARK = "ranged"  # empty file in a ranged comparison's cache folder
REVISION_CACHE_TTL = 24 * 3600
# per-request fields; never stored in a (shared) status. merge_base: a range whose base was on another line (#188)
SCOPE_META = ("scope", "pin", "source", "hunks", "other", "merge_base")
HISTORY_PATHS_MAX = 200  # files a figure document's history names one by one; more are named by their folder
REVISION_RECENT = 12  # rows of GET /api/revisions without paging; a pin's close_ref is resolved among these
REVISION_HISTORY_MAX = 500  # the history window: the commits a request may name (issue #188, ADR-0014)
REVISION_PAGE_MAX = 50  # rows of one page of GET /api/revisions?limit=
RANGE_FILES_MAX = 2 * 1024 * 1024  # bytes of `git diff --numstat -z` read for a range's file list


class RevisionDoc(Protocol):
    """A document as the revision services read it (server.Doc)."""

    @property
    def key(self) -> str:
        """The document key; a pin belongs to one document."""
        ...

    @property
    def shows_revisions(self) -> bool:
        """Whether it has a manuscript history to show (limn.runtime.documents.Doc.shows_revisions); a view-only PDF has none."""
        ...

    @property
    def builds_from_source(self) -> bool:
        """Whether latexmk builds it (limn.runtime.documents.Doc.builds_from_source): only such a document has a
        comparison PDF; a figure document's changes are its pages overlaid in the viewer."""
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
    """The commit (or a range's base) is not in the document's history window (revision_window) - arbitrary objects
    and other documents' history are never read."""


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


@dataclass(frozen=True)
class BaseAfterHead:
    """The range's base is a descendant of its commit (newer than the head): the server never swaps the two ends."""


@dataclass(frozen=True)
class NoMergeBase:
    """The range's base is not an ancestor of its commit and the two have no common ancestor to compare from."""


@dataclass(frozen=True)
class EmptyRange:
    """The range's base is its commit: there is nothing to compare, so no comparison PDF is built (the source diff
    answers an empty diff instead)."""


# A range's own refusals (issue #188), answered from limn.revisions.answer.RANGE_REJECTIONS; the other refusals a range
# meets (CommitNotRecent, DiffFailed, ...) are the single commit's.
RangeRefusal: TypeAlias = BaseAfterHead | NoMergeBase | EmptyRange
DiffRefusal: TypeAlias = NoHistory | CommitNotRecent | DiffFailed | DiffUnavailable | PinNotInDoc
SpecRefusal: TypeAlias = CommitNotRecent | NotInRepo | NoParent | PinNotInDoc | DiffFailed
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
    build records an "error" status - so one type carries the kind; limn.revisions.answer.REVISION_FAILURES gives each kind
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
    pins: RevisionPinQuery
    cache: ScopeCache
    jobs: RevisionJobs
    describe: Callable[[BuildFailure], tuple[str, str]]  # (message, API reason) a failed build records
    # The build owner's answers for a figure document, injected by the composition root: which files' history its
    # changes are, and the two builds its overlay lays one over the other; both None for any other document.
    history_files: Callable[[Doc], tuple[Path, ...] | None]
    overlay: Callable[[Doc], dict[str, Any] | None]


class RevisionSpec(NamedTuple):
    """One comparison to build: repo, build root (source, relative to repo) and main (relative to it), the old side
    base (the commit's first parent, or a range's old side) and the commit head, and key - the cache identity
    (revision_spec). For a pin that owns part of the commit, scope names the blocks the new side applies; meta carries
    the per-request status fields for a pin request."""

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
    merge_base: str | None = None  # a range whose base is on another line: base is this merge base (issue #188)
    ranged: bool = False  # a range whose old side is not head's first parent: cached apart (RANGED_MARK)


# ---------------------------------------------------------------- history and the source diff


def files_pathspec(repo: Path, files: Sequence[Path], folder: Path) -> list[str]:
    """files (absolute paths) as literal Git pathspecs relative to repo, in order, each once; a file that is not inside
    repo, or is repo itself, is left out. More than HISTORY_PATHS_MAX of them are named by folder instead (a literal
    pathspec of a folder covers every file under it), so the git command line stays short; [] when that folder is not
    inside repo either. Lexical: the paths are compared as given, so callers pass resolved folders. Pure."""
    out: list[str] = []
    for f in files:
        try:
            rel = f.relative_to(repo).as_posix()
        except ValueError:
            continue
        spec = ":(literal)" + rel
        if rel != "." and spec not in out:
            out.append(spec)
    if len(out) <= HISTORY_PATHS_MAX:
        return out
    try:
        return [":(literal)" + folder.relative_to(repo).as_posix()]
    except ValueError:
        return []


def revision_scope(D: RevisionDoc, files: Sequence[Path] | None = None) -> tuple[Path, list[str]] | None:
    """Returns the repository and Git pathspec of document D's history, or None for a document without revisions (not
    D.shows_revisions), a main file outside its build root, or a folder outside Git.

    files None: a LaTeX document - just the manuscript text inside the chosen main .tex's folder. D.src is the
    build-copy scope, so multiple documents can share the same root. The change history must be filtered to
    D.main.parent, or commits from the body, highlights, and cover letter get mixed together.
    files given: a figure document - exactly those files (RevisionBuildQueries.history_files: its map, the PDF the map
    names and the map's scripts and shared components), found from the repository holding D.src (files_pathspec)."""
    if not D.shows_revisions:
        return None
    if files is not None:
        return _files_scope(D, files)
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


def _files_scope(D: RevisionDoc, files: Sequence[Path]) -> tuple[Path, list[str]] | None:
    """The repository holding figure document D's folder and files as its pathspec (files_pathspec), or None when the
    folder is not in a Git repository or none of the files lies in it.

    git answers the repository's resolved path, so each file is compared in the same form: its folder with symlinks
    resolved, its own name kept (a script that is itself a link is still named by its own path, as git tracks it). A
    document whose folder is reached through a symlink (macOS's /var -> /private/var) keeps its whole history, as a
    LaTeX document does (revision_scope resolves its main file's folder the same way)."""
    try:
        root = D.src.resolve()
        named = [f.parent.resolve() / f.name for f in files]
    except (OSError, RuntimeError):
        return None
    rc, top, _ = git(["-C", str(root), "rev-parse", "--show-toplevel"], root)
    if rc != 0 or not top.strip():
        return None
    repo = Path(top.strip()).resolve()
    paths = files_pathspec(repo, named, root)
    return (repo, paths) if paths else None


class HistoryPage(NamedTuple):
    """One page of GET /api/revisions: the rows after commit before (None: from the newest), at most limit of them."""

    before: str | None
    limit: int


_LOG_FORMAT = "--format=%H%x1f%P%x1f%an%x1f%cI%x1f%cs%x1f%s"


def parse_log_row(line: str) -> Json | None:
    """One line of `git log` in _LOG_FORMAT as a history row {id, date, subject, author, time, parents}, or None when
    it does not parse (the id or a parent is not a full SHA-1). The subject is cut to 180 characters and the author's
    name to 120. Pure."""
    parts = line.split("\x1f", 5)
    if len(parts) != 6 or not REVISION_ID_RE.fullmatch(parts[0]):
        return None
    parents = parts[1].split()
    if not all(REVISION_ID_RE.fullmatch(p) for p in parents):
        return None
    return {
        "id": parts[0],
        "date": parts[4],
        "subject": parts[5][:180],
        "author": parts[2][:120],
        "time": parts[3],
        "parents": parents,
    }


def _log_rows(repo: Path, paths: Sequence[str], count: int) -> list[Json] | None:
    """The count most recent commits of the pathspec paths in repo, newest first, as history rows (parse_log_row), or
    None when git fails. One `git log` call; rows that do not parse are left out."""
    rc, out, _ = git(["-C", str(repo), "log", "-%d" % count, _LOG_FORMAT, "--"] + list(paths), repo)
    if rc != 0:
        return None
    return [row for row in map(parse_log_row, out.splitlines()) if row is not None]


def revision_window(
    D: RevisionDoc, files: Sequence[Path] | None = None
) -> tuple[Path, list[str], list[Json]] | NoHistory:
    """The document's history window: its repository, pathspec (revision_scope) and its REVISION_HISTORY_MAX most
    recent commits as history rows, newest first - the only commits a revision request may name (no rows when git
    cannot list them). NoHistory for a document without history."""
    found = revision_scope(D, files)
    if found is None:
        return NoHistory()
    repo, paths = found
    return repo, paths, _log_rows(repo, paths, REVISION_HISTORY_MAX) or []


def history_page(rows: Sequence[Json], page: HistoryPage) -> Json | CommitNotRecent:
    """The page of rows (newest first) after the row page.before, at most page.limit of them, and whether more rows
    follow: {revisions, more}; CommitNotRecent when before is not one of rows. Pure."""
    at = 0
    if page.before is not None:
        ids = [row["id"] for row in rows]
        if page.before not in ids:
            return CommitNotRecent()
        at = ids.index(page.before) + 1
    return {"revisions": list(rows[at : at + page.limit]), "more": len(rows) > at + page.limit}


def revision_history(
    D: RevisionDoc, files: Sequence[Path] | None = None, page: HistoryPage | None = None
) -> Json | CommitNotRecent:
    """GET /api/revisions: the document's manuscript commits, newest first, each {id, date, subject, author, time,
    parents}, or available: false when it has no history. Without page, the REVISION_RECENT most recent ones and the
    two keys {available, revisions}, as before paging; with page, that page of the history window (history_page) with
    `more` added, or CommitNotRecent for a before outside it. files are a figure document's history files
    (revision_scope); None for a LaTeX document."""
    found = revision_scope(D, files)
    if found is None:
        return {"available": False, "revisions": []}
    repo, paths = found
    rows = _log_rows(repo, paths, REVISION_RECENT if page is None else REVISION_HISTORY_MAX)
    if rows is None:
        return {"available": False, "revisions": []}
    if page is None:
        return {"available": True, "revisions": rows}
    paged = history_page(rows, page)
    return paged if isinstance(paged, CommitNotRecent) else {"available": True, **paged}


class RangeEnds(NamedTuple):
    """The two sides a range compares: old, the commit the diff starts from (the requested base, or the merge base when
    base is not an ancestor of the head), merge_base that merge base (None when base itself is used), and head."""

    old: str
    head: str
    merge_base: str | None


def window_base(rows: Sequence[Json], base: str) -> bool:
    """Whether base may be a range's base: a commit of the window rows, or the first parent of one (what "from this
    commit" sends, even when that parent did not touch the manuscript). Pure."""
    return any(row["id"] == base or row["parents"][:1] == [base] for row in rows)


def resolve_range(repo: Path, base: str, head: str) -> RangeEnds | BaseAfterHead | NoMergeBase | DiffFailed:
    """The sides a range from base to head compares: base itself when it is head or an ancestor of head; the merge base
    of the two when base is on another line (like a three-dot comparison); BaseAfterHead when base descends from head,
    NoMergeBase when the two share no ancestor, DiffFailed when git cannot tell. Both are full SHA-1s the caller has
    checked against the history window."""
    if base == head:
        return RangeEnds(base, head, None)
    rc, _, _ = git(["merge-base", "--is-ancestor", base, head], repo)
    if rc == 0:
        return RangeEnds(base, head, None)
    if rc != 1:
        return DiffFailed()
    rc, _, _ = git(["merge-base", "--is-ancestor", head, base], repo)
    if rc == 0:
        return BaseAfterHead()
    if rc != 1:
        return DiffFailed()
    rc, out, _ = git(["merge-base", base, head], repo)
    mb = out.strip()
    if rc == 1 or (rc == 0 and not mb):
        return NoMergeBase()
    if rc != 0 or not REVISION_ID_RE.fullmatch(mb):
        return DiffFailed()
    return RangeEnds(mb, head, mb)


def range_ends(
    D: RevisionDoc, commit: str, base: str, files: Sequence[Path] | None = None
) -> tuple[Path, list[str], RangeEnds] | NoHistory | CommitNotRecent | DiffFailed | RangeRefusal:
    """The repository, pathspec and resolved ends of document D's range base..commit: commit must be in the history
    window and base in it or the first parent of one of its commits (window_base); then resolve_range."""
    window = revision_window(D, files)
    if isinstance(window, NoHistory):
        return window
    repo, paths, rows = window
    if commit not in {row["id"] for row in rows} or not window_base(rows, base):
        return CommitNotRecent()
    ends = resolve_range(repo, base, commit)
    return ends if not isinstance(ends, RangeEnds) else (repo, paths, ends)


def parse_numstat(raw: bytes) -> list[Json]:
    """`git diff --numstat -z -M` output as [{path, old_path?, add, del}] in git's order: old_path only for a rename or
    copy, add and del the changed line counts (None for a binary file). Paths are decoded as UTF-8 with replacement.
    Pure."""
    out: list[Json] = []
    fields = raw.split(b"\0")
    i = 0
    while i < len(fields):
        head = fields[i]
        i += 1
        if not head:
            continue
        add, _, rest = head.partition(b"\t")
        dele, _, path = rest.partition(b"\t")
        row: Json = {}
        if path:
            row["path"] = path.decode("utf-8", errors="replace")
        else:  # a rename: the old and the new path follow as two fields
            old, new = fields[i : i + 2] if i + 1 < len(fields) else (b"", b"")
            i += 2
            row["path"] = new.decode("utf-8", errors="replace")
            row["old_path"] = old.decode("utf-8", errors="replace")
        row["add"] = int(add) if add.isdigit() else None
        row["del"] = int(dele) if dele.isdigit() else None
        out.append(row)
    return out


def _stop_git_group(proc: subprocess.Popen[bytes]) -> None:
    """Stop a streamed Git command and its descendants; an already exited group needs no cleanup."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


def _read_capped(cmd: list[str], repo: Path) -> tuple[bytes, bool] | DiffFailed | DiffUnavailable:
    """The stdout of `git <cmd>` cut at REVISION_DIFF_MAX bytes and whether it was longer (the process group is stopped
    as soon as it is), within GIT_TIMEOUT seconds. DiffFailed when git exits with an error before the cap,
    DiffUnavailable when it cannot start or runs out of time."""
    cap = scope_REVISION_DIFF_MAX
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
    return b"".join(chunks)[:cap], too_large


def revision_diff(
    D: RevisionDoc,
    commit: str,
    pin: int | None,
    ctx: RevisionContext,
    files: Sequence[Path] | None = None,
    base: str | None = None,
) -> Json | DiffRefusal | RangeRefusal:
    """GET /api/revision-diff: the selected commit's unified diff against its first parent (a merge too, as in the
    comparison PDF; a root commit against nothing) (commit is a full SHA-1, checked by the request parser). With pin
    (v0.3), an additive `scope` says which of its hunks belong to that pin (scope_payload); the whole-commit `diff` is
    returned unchanged either way. With base (issue #188, never together with pin - the request parser refuses that),
    the range's answer instead (range_diff). Only a commit in the document's history window is read. files are a
    figure document's history files, which scope both the list and the diff (revision_scope); None for a LaTeX
    document."""
    if base is not None:
        return range_diff(D, commit, base, files)
    window = revision_window(D, files)
    if isinstance(window, NoHistory):
        return window
    repo, paths, rows = window
    # Only read commits that appear in the current document's history. Never exposes arbitrary Git objects or another document's history.
    if commit not in {row["id"] for row in rows}:
        return CommitNotRecent()
    revisions = rows[:REVISION_RECENT]  # a pin's close_ref is resolved among the recent commits, as before the window
    cmd = [
        "-C",
        str(repo),
        "show",
        "--format=",
        "-m",  # a merge is shown against its parents one by one (not as a combined diff, which is usually empty) ...
        "--first-parent",  # ... and only against the first, as the comparison PDF does; no effect on other commits
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--unified=3",
        commit,
        "--",
    ] + paths
    read = _read_capped(cmd, repo)
    if not isinstance(read, tuple):
        return read
    out: Json = {"id": commit, "diff": read[0].decode("utf-8", errors="replace"), "truncated": read[1]}
    if pin is not None:
        base = revision_first_parent(repo, commit)
        if base:
            sc = revision_pin_scope(D, repo, paths, base, commit, pin, revisions, ctx)
        else:
            projection = ctx.pins(pin, D.key, D, lambda path: _repo_rel(repo, str(path)))
            sc = PinNotInDoc() if projection is None else PinScope(projection.id, "commit", "none", 0, 0)
        if isinstance(sc, PinNotInDoc):
            return sc
        out["scope"] = scope_payload(sc)
    return out


def range_diff(
    D: RevisionDoc, commit: str, base: str, files: Sequence[Path] | None = None
) -> Json | DiffRefusal | RangeRefusal:
    """GET /api/revision-diff with base: the cumulative diff of the manuscript from the range's old side to commit
    (range_ends: base, or the merge base for a base on another line), renames paired (-M, ranges only), cut like a
    commit's. The answer adds base (the old side used), merge_base (only when the merge base was used), commits (the
    document's commits in the range) and files ([{path, old_path?, add, del}], complete even when diff is cut). An
    empty range (base == commit) answers an empty diff, commits 0 and no files."""
    found = range_ends(D, commit, base, files)
    if not isinstance(found, tuple):
        return found
    repo, paths, ends = found
    tail: Json = {"base": ends.old}
    if ends.merge_base is not None:
        tail["merge_base"] = ends.merge_base
    if ends.old == commit:
        return {"id": commit, "diff": "", "truncated": False, **tail, "commits": 0, "files": []}
    cmd = [
        "-C",
        str(repo),
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "-M",
        "--unified=3",
        ends.old,
        commit,
    ]
    read = _read_capped(cmd + ["--"] + paths, repo)
    if not isinstance(read, tuple):
        return read
    rc, count, _ = git(["rev-list", "--count", "%s..%s" % (ends.old, commit), "--"] + paths, repo)
    stat = git_exec(
        ["diff", "--numstat", "-z", "-M", "--no-ext-diff", ends.old, commit, "--"] + paths,
        repo,
        GIT_TIMEOUT,
        RANGE_FILES_MAX,
    )
    if rc != 0 or not count.strip().isdigit() or isinstance(stat, StepFailed) or stat[0] != 0:
        return DiffUnavailable()
    return {
        "id": commit,
        "diff": read[0].decode("utf-8", errors="replace"),
        "truncated": read[1],
        **tail,
        "commits": int(count.strip()),
        "files": parse_numstat(stat[1]),
    }


def matching_pin_changes(pin: RevisionPin, head: str, revisions: Sequence[Record]) -> RevisionPin:
    """Apply revision-owned Git/PR reference resolution to detached pin change candidates."""
    return pin if _ref_commit(pin.close_ref, revisions) == head else replace(pin, changes=())


_REF_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.ASCII)
_REF_PR_RE = re.compile(r"#(\d+)", re.ASCII)


def _ref_commit(ref: object, revisions: Sequence[Record]) -> str | None:
    """Return the recent commit named by a close reference."""
    text = ref if isinstance(ref, str) else ""
    for token in _REF_SHA_RE.findall(text):
        for revision in revisions:
            if str(revision["id"]).startswith(token):
                return str(revision["id"])
    for number in _REF_PR_RE.findall(text):
        pattern = re.compile(r"\(#%s\)|pull request #%s\b|#%s\b" % (number, number, number), re.ASCII)
        for revision in revisions:
            if pattern.search(revision.get("subject") or ""):
                return str(revision["id"])
    return None


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
                blocks = [scope_Block(0, len(git_lines(old)), 0, len(git_lines(new)))]
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
                    4 * scope_REVISION_DIFF_MAX + len(old) + len(new),
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


def revision_pin_scope(
    D: RevisionDoc,
    repo: Path,
    paths: Sequence[str],
    base: str,
    head: str,
    pid: int,
    revisions: Sequence[Record],
    ctx: RevisionContext,
) -> PinScope | PinNotInDoc:
    """How pin pid of document D sees commit head (compared with its first parent base).
    Revisions are the document's recent commits (revision_history); recorded changes count only on the commit the
    pin's close_ref names. Their paths are resolved by the pin-owned read view with the same rule as the pin's own file
    (issue #24) - so a moved or cloned checkout keeps the agent's lines; a path the rule cannot place is dropped and
    the pin's hunks are inferred as before. Unless the same pin facts were decided for this commit before (ctx.cache),
    reads the commit's files within one of the cache's slots and decides with revisions.scope.pin_scope(); an unreadable
    commit is mode "commit" and not stored."""
    projected = ctx.pins(
        pid,
        D.key,
        D,
        lambda path: _repo_rel(repo, str(path)),
    )
    if projected is None:
        return PinNotInDoc()
    pin: RevisionPin = matching_pin_changes(projected, head, revisions)
    changes = [RepoRange(change.file, change.lo, change.hi) for change in pin.changes]
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


def revision_spec(
    D: RevisionDoc, commit: str, pin: int | None, ctx: RevisionContext, base: str | None = None
) -> RevisionSpec | SpecRefusal | RangeRefusal:
    """What to compare. With pin (v0.3) the new side is old + only that pin's blocks - unless the pin owns the whole
    commit or none of it, in which case the spec (and its cache entry) is the whole-commit one. The cache identity of a
    scoped comparison is (commit, block set) - two pins with the same blocks share one PDF. With base (issue #188, never
    with pin) the old side is the range's (range_spec). Refused for a commit not in the document's history window (as
    before 0.3; a malformed one was refused by the request parser), a build root outside the repository, a first
    commit, and a pin D does not have. A document not built from LaTeX source has no comparison PDF - a figure
    document's changes are its pages overlaid in the viewer - and is refused as a document without history is
    (CommitNotRecent), before any git call."""
    if not D.builds_from_source:
        return CommitNotRecent()
    window = revision_window(D)
    if isinstance(window, NoHistory) or commit not in {r["id"] for r in window[2]}:
        return CommitNotRecent()
    repo, paths, revisions = window[0], tuple(window[1]), window[2][:REVISION_RECENT]
    try:
        source = D.src.resolve().relative_to(repo).as_posix()
        main = D.main.resolve().relative_to(D.src.resolve())
    except ValueError:
        return NotInRepo()
    if base is not None:
        return range_spec(repo, source, main, paths, window[2], commit, base)
    rc, out, _ = git(["rev-list", "--parents", "-n", "1", commit], repo)
    parents = out.strip().split()
    if rc != 0 or len(parents) < 2 or not REVISION_ID_RE.fullmatch(parents[1]):
        return NoParent()
    base = parents[1]
    blocks: tuple[ScopeItem, ...] = ()
    meta = None
    extra: list[Any] = []
    if pin is not None:
        sc = revision_pin_scope(D, repo, paths, base, commit, pin, revisions, ctx)
        if isinstance(sc, PinNotInDoc):
            return sc
        meta = scope_meta(sc)
        if sc.mode == "pin":
            blocks = sc.blocks  # keyed by the block set, not the pin: pins on the same fix share it
            extra = ["blocks", [list(b) for b in blocks]]
    key = comparison_key(repo, source, main, base, commit, extra)
    return RevisionSpec(repo, source, main, base, commit, key, paths, blocks, pin, meta)


def comparison_key(repo: Path, source: str, main: Path, base: str, head: str, extra: Sequence[Any] = ()) -> str:
    """The cache identity of a comparison: the SHA-256 of [REVISION_CACHE_VERSION, repo, source, main, base, head,
    engine] and, for a pin's subset, its block set (extra). A range keys the same way with its old side as base, so a
    range starting at head's first parent is the single commit's comparison. Pure."""
    identity: list[Any] = [REVISION_CACHE_VERSION, str(repo), source, main.as_posix(), base, head, "pdflatex", *extra]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def range_spec(
    repo: Path, source: str, main: Path, paths: tuple[str, ...], rows: Sequence[Json], commit: str, base: str
) -> RevisionSpec | CommitNotRecent | DiffFailed | RangeRefusal:
    """The comparison of the range base..commit (issue #188): base must be in the history window rows or the first
    parent of one of them (window_base), and is resolved like the source diff's (resolve_range: the merge base for a
    base on another line). An empty range is EmptyRange - nothing to build. A range whose old side is commit's first
    parent is the single commit's comparison (same key, not ranged); any other is ranged, cached apart."""
    if not window_base(rows, base):
        return CommitNotRecent()
    ends = resolve_range(repo, base, commit)
    if not isinstance(ends, RangeEnds):
        return ends
    if ends.old == commit:
        return EmptyRange()
    first: list[str] = next((row["parents"][:1] for row in rows if row["id"] == commit), [])
    key = comparison_key(repo, source, main, ends.old, commit)
    return RevisionSpec(
        repo, source, main, ends.old, commit, key, paths, merge_base=ends.merge_base, ranged=first != [ends.old]
    )


def revision_exec(
    cmd: list[str], cwd: Path, timeout: float, limit: int = 8 * 1024 * 1024, env: Mapping[str, str] | None = None
) -> tuple[int, bytes, bytes] | StepFailed:
    """Run cmd without a shell, without stdin and in its own session, with both pipes and the lifetime bounded:
    (returncode, stdout, stderr), or the step failure - the tool could not start, it ran past timeout seconds, or its
    output passed limit bytes. The whole process group is killed on every exit. env replaces the environment (None:
    the server's, as the sandboxed comparison build gets it; git_exec passes limn.platform.git's)."""
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
    """`git <args>` through revision_exec's bounded pipes, in limn.platform.git's environment (GIT_TERMINAL_PROMPT=0, the
    server's GIT_* variables dropped): (returncode, stdout, stderr) or the step failure."""
    return revision_exec(git_command(args), cwd, timeout, limit, env=git_env())
