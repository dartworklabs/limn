"""Synchronization consumes build answers without knowing published storage."""

import threading
from dataclasses import dataclass, field

from limn.sync.rules import UpToDate
from limn.sync.run import PullShare, SyncWatch


@dataclass(eq=False)
class WatchDocument:
    """Only watch policy and mutual exclusion; no marker paths or build-state representation."""

    builds_from_source: bool = True
    lock: object = field(default_factory=threading.Lock)


def test_watch_rebuild_and_settlement_use_owner_answers():
    """A document with no storage handles can catch up and settle using published-head answers."""
    behind, current, pdf = WatchDocument(), WatchDocument(), WatchDocument(False)
    docs = [behind, current, pdf]
    heads = {behind: "old", current: "new"}
    started = []
    watch = SyncWatch()
    result = watch.once(
        docs,
        True,
        lambda: UpToDate("new"),
        PullShare(),
        started.append,
        lambda: "T",
        lambda: 0.0,
        heads.__getitem__,
    )
    assert started == [behind]
    assert result["state"] == "updating"
    assert watch.status(docs, True, lambda doc: False, heads.__getitem__)["state"] == "updating"
    heads[behind] = "new"
    assert watch.status(docs, True, lambda doc: False, heads.__getitem__)["state"] == "current"


def test_missing_published_head_stays_behind_after_noop_pull():
    """Unknown publication identity remains behind and a failed build produces build_failed."""
    doc = WatchDocument()
    watch = SyncWatch()
    started = []
    result = watch.once(
        [doc],
        True,
        lambda: UpToDate("new"),
        PullShare(),
        started.append,
        lambda: "T",
        lambda: 0.0,
        lambda doc: "",
    )
    assert result["state"] == "updating"
    assert started == [doc]
    status = watch.status([doc], True, lambda doc: True, lambda doc: "")
    assert (status["state"], status["reason"]) == ("error", "build_failed")
