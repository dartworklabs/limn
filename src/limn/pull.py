"""The rules of --git-pull and the remote-main watch, with no git, clock or file in sight (docs/handbook/build-sync.md
§재빌드 전 원격 main 당겨오기).

A pull fast-forwards the manuscript repository to its upstream. Each of its git answers is read here - where the
repository is, which commit HEAD is, whether the fetch, the branch, the tree and the merge allow going on - and the
pull ends in one outcome value: Pulled, UpToDate, or a refusal (PullSkipped, PullFailed). pull_record() writes the
outcome as the {"state", "reason", "head_before", "head_after"} object the agent contract shows in a build's `pull`.

The remote-main watch keeps one status object for GET /api/meta's `sync`. What the watch does after a pull, which
documents it rebuilds and when an "updating" status settles are decided here too; the git calls, locks, clock and
threads are limn.gitsync's.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

Json: TypeAlias = dict[str, Any]

SkipReason: TypeAlias = Literal["not_git", "no_upstream", "not_main", "dirty", "diverged"]
FailReason: TypeAlias = Literal["fetch_timeout", "fetch_failed", "status_failed"]
SyncState: TypeAlias = Literal["updated", "current", "blocked", "error"]


# ---------------------------------------------------------------- pull outcomes

@dataclass(frozen=True)
class Pulled:
    """The fast-forward moved HEAD. before is None when HEAD could not be read before the pull."""
    before: str | None
    after: str


@dataclass(frozen=True)
class UpToDate:
    """The pull went through and HEAD did not move (no new commit upstream, or HEAD unreadable after the merge)."""
    head: str | None


@dataclass(frozen=True)
class PullSkipped:
    """The pull stopped before changing anything, for a reason of the checkout: not a repository, no upstream, not
    main (the watch only), a dirty tree, or a history that cannot fast-forward. head is HEAD as it stays (None for
    not_git, or when HEAD is unreadable)."""
    reason: SkipReason
    head: str | None


@dataclass(frozen=True)
class PullFailed:
    """A git call the pull depends on failed or ran out of time (fetch, status); nothing was merged."""
    reason: FailReason
    head: str | None


PullRefusal: TypeAlias = PullSkipped | PullFailed
PullOutcome: TypeAlias = Pulled | UpToDate | PullRefusal


def pull_record(outcome: PullOutcome) -> Json:
    """The outcome as the agent contract shows it in a build's `pull` and in the watch status: state ok, up_to_date,
    skipped or error, the reason (None unless refused), and HEAD before and after (the same commit unless Pulled)."""
    match outcome:
        case Pulled(before=before, after=after):
            return {"state": "ok", "reason": None, "head_before": before, "head_after": after}
        case UpToDate(head=head):
            return {"state": "up_to_date", "reason": None, "head_before": head, "head_after": head}
        case PullSkipped(reason=reason, head=head):
            return {"state": "skipped", "reason": reason, "head_before": head, "head_after": head}
        case PullFailed(reason=reason, head=head):
            return {"state": "error", "reason": reason, "head_before": head, "head_after": head}


# ---------------------------------------------------------------- reading git's answers

def repo_top(rc: int | None, out: str) -> str | None:
    """The repository root from `git rev-parse --show-toplevel`, or None when the folder is not in a repository (or git
    could not run: rc None)."""
    top = out.strip()
    return top if rc == 0 and top else None


def head_of(rc: int | None, out: str) -> str | None:
    """HEAD's commit id from `git rev-parse HEAD`, or None when git refused or could not run."""
    return out.strip() if rc == 0 else None


def fetch_failure(rc: int | None, head: str | None) -> PullFailed | None:
    """None when `git fetch` succeeded; otherwise the failure - fetch_timeout when git did not finish or could not start
    (rc None), fetch_failed when it exited with an error."""
    if rc == 0:
        return None
    return PullFailed("fetch_timeout" if rc is None else "fetch_failed", head)


def tracks_main(rc: int | None, branch: str, upstream: str) -> bool:
    """True when the checkout is on branch main (`git symbolic-ref --short HEAD`) and its upstream is some remote's main
    (`*/main`); the watch fast-forwards nothing else."""
    return rc == 0 and branch.strip() == "main" and upstream.strip().endswith("/main")


def is_dirty(porcelain: str) -> bool:
    """True when `git status --porcelain --untracked-files=no` lists a change to a tracked file."""
    return bool(porcelain.strip())


def merged(before: str | None, rc: int | None, out: str) -> Pulled | UpToDate:
    """The outcome of a fast-forward that succeeded, from `git rev-parse HEAD` after it: Pulled when HEAD moved,
    UpToDate when it did not or can no longer be read."""
    after = out.strip() if rc == 0 else before
    if after is None or after == before:
        return UpToDate(before)
    return Pulled(before, after)


# ---------------------------------------------------------------- the remote-main watch

def initial_status() -> Json:
    """The status before the first round has checked: "checking", nothing known yet. A new object each call."""
    return {"state": "checking", "reason": None, "checked_at": None, "head_before": None, "head_after": None}


def disabled() -> Json:
    """The status without --git-pull: there is no watch. A new object each call."""
    return {"state": "disabled"}


def sync_state(outcome: PullOutcome) -> SyncState:
    """The watch's status for a pull: updated (fast-forwarded), current (nothing new), blocked (the checkout refused)
    or error (git failed)."""
    match outcome:
        case Pulled():
            return "updated"
        case UpToDate():
            return "current"
        case PullSkipped():
            return "blocked"
        case PullFailed():
            return "error"


def after_pull(outcome: PullOutcome, checked_at: str) -> Json:
    """The status a watch round records for its pull: the pull's record with the watch state and the check time. It
    replaces the previous status whole."""
    return dict(pull_record(outcome), state=sync_state(outcome), checked_at=checked_at)


def deferred(checked_at: str) -> Json:
    """The fields a round sets when a document was building, so nothing was pulled; merged into the previous status
    (its heads stay)."""
    return {"state": "deferred", "reason": "building", "checked_at": checked_at}


def unexpected(checked_at: str) -> Json:
    """The fields a round sets when it crashed; merged into the previous status (its heads stay)."""
    return {"state": "error", "reason": "unexpected", "checked_at": checked_at}


def behind(head: str, built: str) -> bool:
    """True when a document's PDF was not built from commit `head`: no head.txt, a build outside git ("-"), or a
    built commit that is not a prefix of head (head.txt holds the short id)."""
    return not built or built == "-" or not head.startswith(built)


def needs_rebuild(outcome: PullOutcome, head: str, built: str) -> bool:
    """Whether a watch round rebuilds a LaTeX document after its pull: always after a fast-forward, and after an
    up-to-date pull when the document's PDF is behind (a restart after the checkout moved). Never after a refusal."""
    match outcome:
        case Pulled():
            return True
        case UpToDate():
            return behind(head, built)
        case PullSkipped() | PullFailed():
            return False


@dataclass(frozen=True)
class Building:
    """A LaTeX document whose build is running (its build lock is held)."""


@dataclass(frozen=True)
class Built:
    """A LaTeX document at rest: the commit its PDF was built from (head.txt, "" when unreadable) and whether its last
    build failed."""
    head: str
    failed: bool


DocProgress: TypeAlias = Building | Built


def settled(head: str, docs: Sequence[DocProgress]) -> Json | None:
    """Whether an "updating" status for commit `head` is over, and how: {"state": "current"} once every LaTeX document
    was built from it, {"state": "error", "reason": "build_failed"} when a document still behind it has a failed
    build, else None (still updating). A running build counts as still behind."""
    pending = failed = False
    for doc in docs:
        match doc:
            case Building():
                pending = True
            case Built(head=built, failed=fail):
                if behind(head, built):
                    pending = True
                    failed |= fail
    if pending and not failed:
        return None
    return {"state": "error", "reason": "build_failed"} if failed else {"state": "current", "reason": None}
