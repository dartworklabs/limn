"""Bind one run's documents, Git runner and build starter to synchronization."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from limn.runtime.documents import Doc
from limn.sync import run
from limn.sync.rules import Json


@dataclass(frozen=True)
class SyncContext:
    """The current run facts used by pull and the remote main watch."""

    manuscript: Path
    enabled: bool
    docs: Sequence[Doc]
    share: run.PullShare
    watch: run.SyncWatch
    start_build: Callable[[Doc], object]
    last_failed: Callable[[Doc], bool]
    built_head: Callable[[Doc], str]
    # brings a watched document's pages up to date in this thread (the builds' refresh_now)
    refresh_now: Callable[[Doc], object]
    git: run.Git
    clock: run.Clock
    stamp: run.Stamp = run.local_stamp


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
        (docs/handbook/api.md §닫을 때 사유 남기기): one watch round right now (once - fast-forward only, main only, a
        clean tree, deferred while a LaTeX document builds: the periodic check's rules; nothing at all without
        --git-pull), then, in this thread, the import or redraw that document's files call for (refresh_now). A key
        this run does not serve is pulled for and refreshed never. Returns the round's status."""
        c = self.context()
        out = self.once()
        doc = next((d for d in c.docs if d.key == key), None)
        if doc is not None:
            c.refresh_now(doc)
        return out

    def watch(self, stop: threading.Event) -> None:
        """Keep checking remote main until this run stops."""
        c = self.context()
        c.watch.watch(stop, run.SYNC_EVERY_S, self.once, c.stamp)
