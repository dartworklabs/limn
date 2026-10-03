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
    ViewOnlyNoRebuild,
)
from limn.builds.contracts import DocumentBuildQueries, PinBuildQueries, RevisionBuildQueries
from limn.builds.queries import BuildQueries
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

    def refresh_now(self, doc: Doc) -> bool:
        """Bring a watched document's pages up to date in the caller's thread (BuildRequests.refresh_watched_now): True
        when an import or redraw ran, whatever its outcome; False when there was nothing to do or the document stayed
        busy."""
        return self._requests.refresh_watched_now(doc) is not None


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
    figure_shown: Callable[[], None] = lambda: None,
) -> BuildSubsystem:
    """Assemble build reads, commands, routes, and startup without import-time adapters."""
    from limn.builds.routes import POST_PATH, get, post
    from limn.web.routes import PostDocRoute, RouteBundle

    commands = BuildCommands(requests or BuildRequests(settings, pull, docs, now, describe, figure_shown))
    routes = RouteBundle(
        get=(lambda request: get(request.path, request.query, request.doc, header_text),),
        post_documents=(
            PostDocRoute(
                POST_PATH,
                lambda request: post(request.query, request.body, request.doc, commands._requests, request.actor),
            ),
        ),
    )
    owned_maps = maps or BuildMapCache()
    queries = BuildQueries(lambda: owned_maps() if callable(owned_maps) else owned_maps)
    return BuildSubsystem(
        queries.documents(),
        queries.pins(),
        queries.revisions(lambda: settings().dpi),
        artifacts.last_build_failed,
        queries.published_head,
        commands,
        routes,
        commands.initialize,
    )
