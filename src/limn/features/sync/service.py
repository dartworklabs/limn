"""Bind one run's documents, Git runner and build starter to synchronization."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from limn.documents import Doc
from limn.features.sync import run
from limn.features.sync.rules import Json


@dataclass(frozen=True)
class SyncContext:
    """The current run facts used by pull and the remote main watch."""

    manuscript: Path
    enabled: bool
    docs: Sequence[Doc]
    share: run.PullShare
    watch: run.SyncWatch
    start_build: Callable[[Doc], object]
    git: run.Git
    clock: run.Clock
    stamp: run.Stamp


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
        return c.watch.status(c.docs, c.enabled)

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
        )

    def watch(self, stop: threading.Event) -> None:
        """Keep checking remote main until this run stops."""
        c = self.context()
        c.watch.watch(stop, run.SYNC_EVERY_S, self.once, c.stamp)
