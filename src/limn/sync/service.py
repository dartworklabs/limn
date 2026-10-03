"""Bind one run's documents, Git runner and build starter to synchronization."""

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from limn.runtime.documents import Doc
from limn.sync import run
from limn.sync.rules import Json

# The most a close waits for its document's files before it is written (refresh_watched): the pull, a round in flight
# and the import together. Agents close with a plain curl and no --max-time, and an agent's shell may stop a command
# after 120 s; past this the close is written and announced anyway, and the watch brings the figure in later.
REFRESH_BUDGET_S = 30.0


@dataclass(frozen=True)
class SyncContext:
    """The current run facts used by pull and the remote main watch. refresh_now brings a watched document's pages up
    to date within the seconds it is given (the builds' refresh_now); refresh_budget and ticks (a monotonic clock) bound
    a close's refresh."""

    manuscript: Path
    enabled: bool
    docs: Sequence[Doc]
    share: run.PullShare
    watch: run.SyncWatch
    start_build: Callable[[Doc], object]
    last_failed: Callable[[Doc], bool]
    built_head: Callable[[Doc], str]
    refresh_now: Callable[[Doc, float], object]
    git: run.Git
    clock: run.Clock
    stamp: run.Stamp = run.local_stamp
    refresh_budget: float = REFRESH_BUDGET_S
    ticks: run.Clock = time.monotonic


@dataclass
class SyncService:
    """One run's synchronization operations, with its current context read on each call."""

    context: Callable[[], SyncContext]

    def repo_pull(self) -> Json:
        """A build's pull record, shared briefly across documents of one manuscript."""
        c = self.context()
        return run.repo_pull(
            c.share, len(c.docs) > 1, lambda: run.pull(c.manuscript, main_only=False, git=c.git), c.clock
        )

    def status(self) -> Json:
        """The current remote main watch status for GET /api/meta."""
        c = self.context()
        return c.watch.status(c.docs, c.enabled, c.last_failed, c.built_head)

    def once(self) -> Json:
        """Pull remote main once and start builds for documents left behind."""
        c = self.context()
        return c.watch.once(
            c.docs,
            c.enabled,
            lambda: run.pull(c.manuscript, main_only=True, git=c.git),
            c.share,
            c.start_build,
            c.stamp,
            c.clock,
            c.built_head,
        )

    def refresh_watched(self, key: str) -> Json:
        """Bring the files of the document keyed `key` up to date before a close of one of its pins is announced
        (docs/handbook/api.md §닫을 때 사유 남기기), all within c.refresh_budget seconds: one watch round now with the
        periodic check's rules (fast-forward only, main only, a clean tree; nothing at all without --git-pull), which
        waits for a round or a LaTeX build in flight instead of deferring at once and gives every git call only what is
        left of the budget; then the import or redraw that document's files call for, given the rest (refresh_now). A
        key this run does not serve is pulled for and refreshed never. Returns the round's status - "deferred" when the
        budget ran out before it could pull."""
        c = self.context()
        deadline = c.ticks() + c.refresh_budget
        bounded = run.within(c.git, deadline, c.ticks)
        out = c.watch.once(
            c.docs,
            c.enabled,
            lambda: run.pull(c.manuscript, main_only=True, git=bounded),
            c.share,
            c.start_build,
            c.stamp,
            c.clock,
            c.built_head,
            deadline=deadline,
            ticks=c.ticks,
        )
        doc = next((d for d in c.docs if d.key == key), None)
        if doc is not None:
            c.refresh_now(doc, max(0.0, deadline - c.ticks()))
        return out

    def watch(self, stop: threading.Event) -> None:
        """Keep checking remote main until this run stops."""
        c = self.context()
        c.watch.watch(stop, run.SYNC_EVERY_S, self.once, c.stamp)
