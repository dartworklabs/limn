"""--git-pull and the remote-main watch: the git calls, the locks, the clock and the watch loop (docs/handbook/build-sync.md
§재빌드 전 원격 main 당겨오기 (`--git-pull`)).

A pull fast-forwards the manuscript repository to its upstream before a build copies it (pull), a rebuild of one
document pulls once per build and several documents share one pull per repository (repo_pull with a PullShare), and
the watch checks remote main right after startup and every SYNC_EVERY_S, rebuilding the LaTeX documents that fell
behind (SyncWatch). What git's answers mean and what the watch does next are limn.pull's pure rules; this module runs
git and keeps the process's state.

Nothing here reads server.py's settings or document list: the composition root passes the manuscript folder, the
documents, whether --git-pull is on, the git runner (limn.revisions.git: no shell, a timeout per call), the clock and
the build starter on every call, and owns the one PullShare and SyncWatch of the process.
"""

from __future__ import annotations

import sys
import threading
import traceback
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TypeAlias, TypeVar

from limn.pull import (
    Building,
    Built,
    DocProgress,
    Json,
    PullFailed,
    PullOutcome,
    PullSkipped,
    after_pull,
    deferred,
    disabled,
    fetch_failure,
    head_of,
    initial_status,
    is_dirty,
    merged,
    needs_rebuild,
    pull_record,
    repo_top,
    settled,
    tracks_main,
    unexpected,
)

PULL_SHARE_S = 20  # seconds - if another document already pulled within this window, reuse its result
SYNC_EVERY_S = 60  # interval for checking remote main. Checked even when no browser is open.
DEFERRED_RETRY_S = 3.0  # a round deferred by a running build retries this soon (or at `every`, if sooner)

Git: TypeAlias = Callable[[Sequence[str], Path | str], tuple[int | None, str, str]]  # limn.revisions.git
Clock: TypeAlias = Callable[[], float]
Stamp: TypeAlias = Callable[[], str]


class SyncDoc(Protocol):
    """A document as the watch reads it (limn.documents.Doc)."""

    @property
    def is_pdf(self) -> bool:
        """A view-only PDF document is never pulled for or rebuilt."""
        ...

    @property
    def dir(self) -> Path:
        """The document's state folder; head.txt there names the commit its PDF was built from."""
        ...

    @property
    def lock(self) -> threading.Lock:
        """The document's build lock: held while it builds; the watch holds every one while it pulls."""
        ...

    @property
    def bstate_lock(self) -> threading.Lock:
        """Guards bstate."""
        ...

    @property
    def bstate(self) -> dict[str, Any]:
        """The document's build state; its "state" is "fail" after a failed build."""
        ...


Doc = TypeVar("Doc", bound=SyncDoc)


def local_stamp() -> str:
    """Now as the watch status records it: local time with its offset, to the second (checked_at)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- the pull


def pull(manuscript: Path, main_only: bool, git: Git) -> PullOutcome:
    """Fast-forward the repository that holds `manuscript` to its upstream, or say why not.

    Order: locate the repo root (skipped:not_git) -> read HEAD -> fetch (error:fetch_failed|fetch_timeout) -> check the
    upstream (skipped:no_upstream) -> with main_only, check branch main tracking */main (skipped:not_main) -> check for
    a dirty tree (error:status_failed, skipped:dirty) -> --ff-only merge (skipped:diverged) -> read HEAD again. A git
    call that times out or cannot start reads as that step failing. git runs with list arguments (no shell); nothing
    from a request reaches them."""
    rc, out, _ = git(["-C", str(manuscript), "rev-parse", "--show-toplevel"], manuscript)
    root = repo_top(rc, out)
    if root is None:
        return PullSkipped("not_git", None)
    rc, out, _ = git(["-C", root, "rev-parse", "HEAD"], root)
    head = head_of(rc, out)
    rc, _, _ = git(["-C", root, "fetch", "--quiet"], root)
    failed = fetch_failure(rc, head)
    if failed is not None:
        return failed
    rc, upstream, _ = git(["-C", root, "rev-parse", "--abbrev-ref", "@{u}"], root)
    if rc != 0:
        return PullSkipped("no_upstream", head)
    if main_only:
        rc, branch, _ = git(["-C", root, "symbolic-ref", "--quiet", "--short", "HEAD"], root)
        if not tracks_main(rc, branch, upstream):
            return PullSkipped("not_main", head)
    rc, porcelain, _ = git(["-C", root, "status", "--porcelain", "--untracked-files=no"], root)
    if rc != 0:
        return PullFailed("status_failed", head)
    if is_dirty(porcelain):
        return PullSkipped("dirty", head)
    rc, _, _ = git(["-C", root, "merge", "--ff-only", "@{u}"], root)
    if rc != 0:
        return PullSkipped("diverged", head)
    rc, out, _ = git(["-C", root, "rev-parse", "HEAD"], root)
    return merged(head, rc, out)


class PullShare:
    """The process's one --git-pull per repository: a lock that serializes pulls, and the last pull with when it ran
    (the clock's seconds). Owned by the composition root; repo_pull and SyncWatch.once share it."""

    def __init__(self) -> None:
        """No pull yet: the next shared pull runs."""
        self.lock = threading.Lock()
        self.at = 0.0
        self.last: PullOutcome | None = None

    def remember(self, outcome: PullOutcome, at: float) -> None:
        """Record a pull that just ran; the caller holds the lock."""
        self.at, self.last = at, outcome


def repo_pull(
    share: PullShare, several: bool, run: Callable[[], PullOutcome], clock: Clock, window: float = PULL_SHARE_S
) -> Json:
    """A build's pull, as its `pull` record. One document (several False) pulls on every build, unshared. With several
    documents the pulls are serialized, and a pull another document's build made within `window` seconds is reused
    with shared=True instead of pulling again - so two documents rebuilding at once never collide on git fetch/merge
    (.git/index.lock), and the tree never changes while one of them copies it."""
    if not several:
        return pull_record(run())
    with share.lock:
        last = share.last
        if last is not None and clock() - share.at < window:
            return dict(pull_record(last), shared=True)
        outcome = run()
        share.remember(outcome, clock())
        return pull_record(outcome)


# ---------------------------------------------------------------- the remote-main watch


def _built_head(D: SyncDoc) -> str:
    """The commit document D's PDF was built from (head.txt, stripped), or "" when there is none to read."""
    try:
        return (D.dir / "head.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _progress(D: SyncDoc) -> DocProgress:
    """Where LaTeX document D's build stands for the watch status: running, or at rest with its built commit and
    whether its last build failed."""
    if D.lock.locked():
        return Building()
    built = _built_head(D)
    with D.bstate_lock:
        return Built(built, D.bstate.get("state") == "fail")


class SyncWatch:
    """The remote-main watch's status (GET /api/meta's `sync`) and its lock; one per process, owned by the composition
    root. `record` is read and written only under `lock`."""

    def __init__(self) -> None:
        """Before the first round: "checking"."""
        self.lock = threading.Lock()
        self.record: Json = initial_status()

    def status(self, docs: Iterable[SyncDoc], enabled: bool) -> Json:
        """The status for GET /api/meta: "disabled" without --git-pull. An "updating" status is settled here once every
        LaTeX document was built from the pulled commit ("current"), or a document still behind it failed its build
        ("error", build_failed). Returns a copy."""
        if not enabled:
            return disabled()
        with self.lock:
            record = dict(self.record)
        if record.get("state") != "updating" or not record.get("head_after"):
            return record
        head = record["head_after"]
        done = settled(head, [_progress(D) for D in list(docs) if not D.is_pdf])
        if done is None:
            return record
        with self.lock:
            if self.record.get("state") == "updating" and self.record.get("head_after") == head:
                self.record.update(done)
            return dict(self.record)

    def once(
        self,
        docs: Iterable[Doc],
        enabled: bool,
        run: Callable[[], PullOutcome],
        share: PullShare,
        start_build: Callable[[Doc], object],
        stamp: Stamp,
        clock: Clock,
    ) -> Json:
        """One round: pull remote main and start the build of each LaTeX document the pull left behind. Also run on a
        --no-build startup.

        A round is deferred ("deferred", building) when any LaTeX document is building. Otherwise every document's
        build lock is held during the pull, so a fast-forward never lands while a build is mid-copy. The pull is
        shared-recorded (PullShare) like a build's. Returns the round's status; "updating" when builds were started."""
        if not enabled:
            return disabled()
        held: list[threading.Lock] = []
        for D in [D for D in list(docs) if not D.is_pdf]:
            if not D.lock.acquire(blocking=False):
                for lock in reversed(held):
                    lock.release()
                out = deferred(stamp())
                with self.lock:
                    self.record.update(out)
                return out
            held.append(D.lock)
        try:
            with share.lock:
                outcome = run()
                share.remember(outcome, clock())
        finally:
            for lock in reversed(held):
                lock.release()

        out = after_pull(outcome, stamp())
        with self.lock:
            self.record.clear()
            self.record.update(out)
        if out["state"] in ("updated", "current"):
            head = out.get("head_after") or ""
            for D in [D for D in list(docs) if not D.is_pdf]:  # the list as it is now, like the round's start
                if needs_rebuild(outcome, head, _built_head(D)):
                    start_build(D)
                    out["state"] = "updating"
            if out["state"] == "updating":
                with self.lock:
                    self.record["state"] = "updating"
        return out

    def watch(self, stop: threading.Event, every: float, once: Callable[[], Json], stamp: Stamp) -> None:
        """The watch thread's body: a round right away, then one every `every` seconds (a deferred round retries within
        DEFERRED_RETRY_S) until `stop` is set. A round that crashes is printed to stderr and recorded as
        ("error", unexpected); the thread goes on."""
        while not stop.is_set():
            try:
                result = once()
            except Exception:  # noqa: BLE001 — the next round will retry
                traceback.print_exc(file=sys.stderr)
                with self.lock:
                    self.record.update(unexpected(stamp()))
                result = {"state": "error"}
            if stop.wait(min(DEFERRED_RETRY_S, every) if result.get("state") == "deferred" else every):
                break
