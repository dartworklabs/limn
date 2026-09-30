"""Public build reads, commands, and capability assembly."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from limn.builds import artifacts
from limn.builds.answer import build_failure_log
from limn.builds.artifacts import (
    BuildBusy,
    BuildDoc,
    BuildMapCache,
    BuildSkipped,
    BuildStarted,
    BuildStateHolder,
    Describe,
    FailedBuild,
    FinishedBuild,
    ViewOnlyNoRebuild,
)
from limn.builds.figure_map import FigureMap, MapRejected
from limn.builds.service import BuildRequests
from limn.runtime.config import RunConfig
from limn.runtime.documents import Doc
from limn.runtime.startup import StartupRefused
from limn.security.access import AuthorityScope, PostAuthority

if TYPE_CHECKING:
    from limn.web.parse import DocumentFacts
    from limn.web.routes import RouteBundle

Json = dict[str, Any]


@dataclass(frozen=True)
class BuildInitialization:
    """Startup facts without compiler failures or artifact internals crossing into composition."""

    started: bool
    refusal: StartupRefused | None = None


@dataclass(frozen=True)
class BuildView:
    """Stateless access to published build artifacts and source facts."""

    maps: BuildMapCache | Callable[[], BuildMapCache] = field(default_factory=BuildMapCache)

    def _maps(self) -> BuildMapCache:
        """Read the current run cache, including a replaced runtime."""
        return self.maps() if callable(self.maps) else self.maps

    def figure_map(self, doc: Doc, build: str) -> FigureMap | MapRejected | None:
        """Read a figure map once per run, without granting source-read authority."""
        return self._maps().get(doc, build) if doc.has_element_map else None

    def current_pages(self, doc: BuildDoc) -> Path:
        """Return the page directory currently published for ``doc``."""
        return artifacts.cur_pages(doc)

    def pages_for(self, doc: BuildDoc, name: object) -> Path:
        """Return a valid historical page directory or the current directory."""
        return artifacts.pages_dir_for(doc, name)

    def page_metadata(self, pages: Path, dpi: int) -> list[dict[str, Any]]:
        """Return published page sizes in points."""
        return artifacts.page_list(pages, dpi)

    def published_pdf(self, doc: BuildDoc, name: object) -> Path | None:
        """Return the PDF paired with a named published build."""
        return artifacts.build_pdf(doc, name)

    def current_pdf(self, doc: BuildDoc, pages: Path | None = None) -> Path:
        """Return the PDF paired with ``pages`` or the current page directory."""
        return artifacts.cur_pdf(doc, pages)

    def figure_pdf(self, doc: BuildDoc, build: str) -> Path | None:
        """Return the source PDF named by a figure build's published map."""
        return artifacts.build_figure_pdf(doc, build, lambda d, b: self._maps().get(d, b))

    def snapshot(self, doc: BuildDoc) -> dict[str, Any]:
        """Return a copy of the current build state."""
        return artifacts.state_snapshot(doc)

    def source_newer(self, doc: BuildDoc, state: Path, name: str | None = None) -> float:
        """Return how many seconds the source is newer than a published build."""
        return artifacts.source_newer(doc, state, name)

    def source_mtime(self, doc: BuildDoc, state: Path, *, force: bool = False) -> float:
        """Return the document source fingerprint time."""
        return artifacts.src_mtime(doc, state, force)

    def built_source_mtime(self, doc: BuildDoc) -> float | None:
        """Return the source time recorded by the current build."""
        return artifacts.read_built_src_mtime(doc)

    def built_at(self, doc: BuildDoc) -> str | None:
        """Return the current build's recorded timestamp."""
        return artifacts.read_built_at(doc)

    def head(self, doc: BuildDoc) -> str | None:
        """Return the commit recorded by the current build."""
        return artifacts.read_head(doc)

    def history(self, doc: BuildDoc) -> dict[str, Any]:
        """Return the document's bounded build history."""
        return artifacts.load_builds(doc)

    def last_failed(self, doc: BuildStateHolder) -> bool:
        """Return whether the most recently finished build failed."""
        return artifacts.last_build_failed(doc)

    def valid_name(self, value: object) -> bool:
        """Return whether ``value`` names a page directory."""
        return artifacts.valid_build_name(value)

    def document_facts(self, doc: Doc, root: Path, state: Path, dpi: int) -> DocumentFacts:
        """Bind source and page parsing facts without exposing build implementation helpers."""
        from limn.builds.document_facts import DocumentFacts

        return DocumentFacts(doc, root, state, dpi, self.figure_map, builds=self)


@dataclass(frozen=True)
class BuildCommands:
    """Mutation and lifecycle operations owned by the builds capability."""

    _requests: BuildRequests

    @property
    def authority_scope(self) -> AuthorityScope:
        """Return the authority scope bound by the underlying build service."""
        return self._requests.authority_scope

    def rebuild(self, doc: Doc, authority: PostAuthority) -> FinishedBuild | BuildBusy | ViewOnlyNoRebuild:
        """Run a synchronous authorized rebuild."""
        return self._requests.rebuild(doc, authority)

    def rebuild_async(self, doc: Doc, authority: PostAuthority) -> BuildStarted | BuildBusy | ViewOnlyNoRebuild:
        """Start an asynchronous authorized rebuild."""
        return self._requests.rebuild_async(doc, authority)

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


@dataclass(frozen=True)
class BuildSubsystem:
    """The build capability values used by composition."""

    view: BuildView
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
    return BuildSubsystem(BuildView(maps or BuildMapCache()), commands, routes, commands.initialize)
