"""Per-instance build request execution, using the established build locks and state flow."""

from collections.abc import Callable

from limn import build
from limn.build import BuildBusy, BuildStarted, Describe, FinishedBuild, ViewOnlyNoRebuild
from limn.documents import Doc


class BuildRequests:
    """Run a document build with this server's tracked step, clock and failure text."""

    def __init__(self, tracked: Callable[[Doc], FinishedBuild], now: Callable[[], str], describe: Describe) -> None:
        """Bind the tracked step and clock supplied by one application instance."""
        self.tracked = tracked
        self.now = now
        self.describe = describe

    def build_all(self, doc: Doc) -> FinishedBuild | BuildBusy:
        """Build now, or return busy when this document's build lock is held."""
        return build.build_now(doc, lambda: self.tracked(doc))

    def build_async(self, doc: Doc) -> BuildStarted | BuildBusy:
        """Start a tracked build on a daemon thread, or return busy."""
        return build.build_in_background(doc, lambda: self.tracked(doc), self.now(), self.describe)

    def rebuild(self, doc: Doc) -> FinishedBuild | BuildBusy | ViewOnlyNoRebuild:
        """Refuse manual rebuild of a view-only document; otherwise build now."""
        return build.request_rebuild(doc, self.build_all)

    def rebuild_async(self, doc: Doc) -> BuildStarted | BuildBusy | ViewOnlyNoRebuild:
        """Refuse manual rebuild of a view-only document; otherwise start in the background."""
        return build.request_rebuild(doc, self.build_async)
