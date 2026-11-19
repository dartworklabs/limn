"""Public build reads, commands, and capability assembly."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from limn.builds import artifacts
from limn.builds.answer import build_failure_log
from limn.builds.artifacts import (
    BuildBusy,
    BuildMapCache,
    BuildSkipped,
    BuildStarted,
    BuildStateHolder,
    Describe,
    FailedBuild,
    FinishedBuild,
    PageFolderCache,
    RangeBoxCache,
    ViewOnlyNoRebuild,
)
from limn.builds.contracts import (
    DocumentBuildQueries,
    MarkBoxes,
    MarkComputation,
    PinBuildQueries,
    RevisionBuildQueries,
)
from limn.builds.queries import BuildQueries, no_marks
from limn.builds.service import BuildRequests
from limn.runtime.config import RunConfig
from limn.runtime.documents import Doc
from limn.runtime.startup import StartupRefused
from limn.security.access import AuthorityScope, PostAuthority

if TYPE_CHECKING:
    from limn.web.routes import RouteBundle

Json = dict[str, Any]


@dataclass(frozen=True)
class BuildInitialization:
    """Startup facts without compiler failures or artifact internals crossing into composition."""

    started: bool
    refusal: StartupRefused | None = None


@dataclass(frozen=True)
class BuildCommands:
    """Mutation and lifecycle operations owned by the builds capability."""

    _requests: BuildRequests

    @property
    def authority_scope(self) -> AuthorityScope:
        """Return the authority scope bound by the underlying build service."""
        return self._requests.authority_scope

    def rebuild(
        self, doc: Doc, authority: PostAuthority, force: bool = False
    ) -> FinishedBuild | BuildBusy | ViewOnlyNoRebuild:
        """Run a synchronous authorized rebuild; force builds cold and never answers unchanged."""
        return self._requests.rebuild(doc, authority, force)

    def rebuild_async(
        self, doc: Doc, authority: PostAuthority, force: bool = False
    ) -> BuildStarted | BuildBusy | ViewOnlyNoRebuild:
        """Start an asynchronous authorized rebuild; force as in rebuild."""
        return self._requests.rebuild_async(doc, authority, force)

    def build_async(self, doc: Doc) -> BuildStarted | BuildBusy:
        """Start an internal asynchronous build."""
        return self._requests.build_async(doc)

    def initialize(self, doc: Doc, no_build: bool, wait: bool) -> BuildInitialization:
        """Restore and, when needed, build one document during startup."""
        result = self._requests.init_doc(doc, no_build, wait)
        refusal = (
            StartupRefused("Build failed:\n" + build_failure_log(result)) if isinstance(result, FailedBuild) else None
        )
        return BuildInitialization(not isinstance(result, BuildSkipped), refusal)

    def watch(self, stop: threading.Event, every: float = 3.0) -> None:
        """Watch file-backed documents until ``stop`` is set."""
        self._requests.watch_pdf_docs(stop, every)

    def refresh_now(self, doc: Doc, wait: float) -> bool:
        """Bring a watched document's pages up to date, waiting at most `wait` seconds (BuildRequests.
        refresh_watched_now): True when an import or redraw started here finished in time; False when there was
        nothing to do or a build of the document is still running."""
        return self._requests.refresh_watched_now(doc, wait)


@dataclass(frozen=True)
class BuildSubsystem:
    """The build capability values used by composition."""

    documents: DocumentBuildQueries
    pins: PinBuildQueries
    revisions: RevisionBuildQueries
    last_failed: Callable[[BuildStateHolder], bool]
    published_head: Callable[[Doc], str]
    commands: BuildCommands
    routes: RouteBundle
    startup: Callable[[Doc, bool, bool], BuildInitialization]
    # Where a line range of one document prints on the build it has on screen, behind this run's mark cache; None for
    # a document nothing could print a mark for (BuildQueries.boxes). The composition root hands it to the pin
    # consumer, which declares its shape as limn.pins.needs.DocumentBoxes.
    boxes: Callable[[Doc], MarkBoxes | None] = lambda doc: None


def assemble_builds(
    settings: Callable[[], RunConfig],
    pull: Callable[[], Json],
    docs: Callable[[], Sequence[Doc]],
    now: Callable[[], str],
    describe: Describe = build_failure_log,
    header_text: Callable[[object], str] = str,
    requests: BuildRequests | None = None,
    *,
    maps: BuildMapCache | Callable[[], BuildMapCache] | None = None,
    pages: PageFolderCache | Callable[[], PageFolderCache] | None = None,
    figure_shown: Callable[[], None] = lambda: None,
    marks: MarkComputation = no_marks,
) -> BuildSubsystem:
    """Assemble build reads, commands, routes, and startup without import-time adapters.

    marks is the forward SyncTeX pass itself, which the pin consumer owns and the composition root injects
    (limn.pins.location.resolve.range_boxes, the same binding POST /api/pick and GET /api/snippet use, so the three
    paths cannot draw different boxes for the same lines). Without it no answer carries a mark. The cache the answers
    are kept in is this run's and is made here, beside the parsed maps. pages is what the run keeps of the page
    folders on screen (PageFolderCache): the composition root hands in the run's own, as it does maps; without it
    the queries keep one of their own."""
    from limn.builds.routes import HOLD_PATH, POST_PATH, get, post, post_hold
    from limn.web.routes import PostDocRoute, RouteBundle

    commands = BuildCommands(requests or BuildRequests(settings, pull, docs, now, describe, figure_shown))
    routes = RouteBundle(
        get=(lambda request: get(request.path, request.query, request.doc, header_text),),
        post_documents=(
            PostDocRoute(
                POST_PATH,
                lambda request: post(request.query, request.body, request.doc, commands._requests, request.actor),
            ),
            PostDocRoute(
                HOLD_PATH,
                lambda request: post_hold(
                    request.query, request.body, request.doc, commands._requests, request.actor, header_text
                ),
            ),
        ),
    )
    owned_maps = maps or BuildMapCache()
    owned_marks = RangeBoxCache()
    owned_pages = pages or PageFolderCache()
    queries = BuildQueries(
        lambda: owned_maps() if callable(owned_maps) else owned_maps,
        lambda: owned_marks,
        marks,
        lambda: owned_pages() if callable(owned_pages) else owned_pages,
    )
    return BuildSubsystem(
        queries.documents(),
        queries.pins(),
        queries.revisions(lambda: settings().dpi),
        artifacts.last_build_failed,
        queries.published_head,
        commands,
        routes,
        commands.initialize,
        lambda doc: queries.boxes(doc, settings().dpi),
    )
