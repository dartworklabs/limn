"""Per-instance build execution, startup initialization and view-only PDF watch."""

import sys
import threading
import traceback
from collections.abc import Callable, Sequence
from typing import Any

from limn import build
from limn.access import AuthorityScope, PostAuthority, require_authority
from limn.build import BuildBusy, BuildConfig, BuildSkipped, BuildStarted, Describe, FinishedBuild, ViewOnlyNoRebuild
from limn.config import RunConfig
from limn.documents import Doc, document_authority_target
from limn.features.builds import engine, figure, run
from limn.features.builds.figure import FigureImport

Json = dict[str, Any]


class BuildRequests:
    """Run and watch document builds with the current run settings and shared document locks."""

    def __init__(
        self,
        settings: Callable[[], RunConfig],
        pull: Callable[[], Json],
        docs: Callable[[], Sequence[Doc]],
        now: Callable[[], str],
        describe: Describe,
    ) -> None:
        """Bind run facts as call-time lookups so a new setting or runtime is seen on the next build, and start this
        run's memo of figure maps."""
        self.settings = settings
        self.pull = pull
        self.docs = docs
        self.now = now
        self.describe = describe
        self.figure_looks = figure.MapLooks()  # this run's memo of each figure map's PDF (figure.watch_signature)

    @property
    def authority_scope(self) -> AuthorityScope:
        """Snapshot this service and the current storage namespace before authorizing a build."""
        return AuthorityScope(self, str(self.settings().state.resolve()))

    def config(self) -> BuildConfig:
        """Current state folder, dpi and timeout for one build."""
        c = self.settings()
        return BuildConfig(state=c.state, dpi=c.dpi, timeout=c.timeout)

    def compile(self, doc: Doc) -> FinishedBuild:
        """Compile one LaTeX document, pulling its repository first when configured."""
        return engine.compile_tex(doc, self.config(), self.pull if self.settings().git_pull else None)

    def tracked(self, doc: Doc, ready: FigureImport | None = None) -> FinishedBuild:
        """Run one build of doc (build_step) and commit its status and page history (run.run_tracked). ready is a
        figure document's verified pair (figure.pending_import); without it such a document reads and checks its files
        itself."""
        return run.run_tracked(
            doc, self.settings().state, lambda: self.build_step(doc, ready), self.now(), self.describe
        )

    def build_step(self, doc: Doc, ready: FigureImport | None = None) -> FinishedBuild:
        """One untracked build of doc, chosen by capability: latexmk for a document built from source; the import of
        its map and PDF for a document with an element map (figure.import_now, with ready when given); otherwise the
        render of its view-only PDF."""
        if doc.builds_from_source:
            return self.compile(doc)
        if doc.has_element_map:
            return figure.import_now(doc, self.config(), ready)
        return engine.render_pdf_doc(doc, self.config())

    def import_figure(self, doc: Doc, ready: FigureImport, wait: bool) -> FinishedBuild | BuildStarted | BuildBusy:
        """Import a verified figure pair through the tracked build: now when wait, else on a daemon thread. BuildBusy
        when doc is already building; nothing was settled then, so the watch tries again on its next tick."""
        if wait:
            return run.build_now(doc, lambda: self.tracked(doc, ready))
        return run.build_in_background(doc, lambda: self.tracked(doc, ready), self.now(), self.describe)

    def build_all(self, doc: Doc) -> FinishedBuild | BuildBusy:
        """Build now, or return busy when this document's build lock is held."""
        return run.build_now(doc, lambda: self.tracked(doc))

    def build_async(self, doc: Doc) -> BuildStarted | BuildBusy:
        """Start a tracked build on a daemon thread, or return busy."""
        return run.build_in_background(doc, lambda: self.tracked(doc), self.now(), self.describe)

    def rebuild(self, doc: Doc, authority: PostAuthority) -> FinishedBuild | BuildBusy | ViewOnlyNoRebuild:
        """Refuse manual rebuild of a view-only document; otherwise build now."""
        require_authority(authority, self.authority_scope, "rebuild", document_authority_target(doc))
        return run.request_rebuild(doc, self.build_all)

    def rebuild_async(self, doc: Doc, authority: PostAuthority) -> BuildStarted | BuildBusy | ViewOnlyNoRebuild:
        """Refuse manual rebuild of a view-only document; otherwise start in the background."""
        require_authority(authority, self.authority_scope, "rebuild", document_authority_target(doc))
        return run.request_rebuild(doc, self.build_async)

    def init_doc(self, doc: Doc, no_build: bool, wait: bool) -> FinishedBuild | BuildStarted | BuildBusy | BuildSkipped:
        """Restore build history and start a needed build, synchronously only when requested. A document with an
        element map is imported only when figure.pending_import (startup rules) finds its map and PDF changed or its
        page images missing, and the two agree; --no-build does not apply to it, as to a view-only PDF."""
        doc.dir.mkdir(parents=True, exist_ok=True)
        if doc.root:
            build.migrate_pages(doc)
        build.seed_builds(doc, self.settings().state)
        if doc.has_element_map:
            ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=True)
            return BuildSkipped() if ready is None else self.import_figure(doc, ready, wait)
        if not run.needs_build(doc, no_build, self.settings().dpi):
            return BuildSkipped()
        return self.build_all(doc) if wait else self.build_async(doc)

    def watch_pdf_docs(self, stop: threading.Event, every: float = 3.0) -> None:
        """Every `every` seconds until this run's stop event is set, give each document whose files are watched one
        refresh_watched tick. An exception is printed and the watch goes on."""
        while not stop.wait(every):
            for doc in list(self.docs()):
                if doc.watches_files:
                    try:
                        self.refresh_watched(doc)
                    except Exception:  # noqa: BLE001 — the watch thread must never die
                        traceback.print_exc(file=sys.stderr)

    def refresh_watched(self, doc: Doc) -> bool:
        """One watch tick for doc. A document with an element map imports its map and PDF once they agree
        (figure.pending_import) and otherwise builds nothing and records no failure; a view-only PDF re-renders when
        its file changed (engine.refresh_pdf_doc). True when a build started; False for a document whose files are not
        watched."""
        if not doc.watches_files:
            return False
        if doc.has_element_map:
            ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=False)
            return ready is not None and isinstance(self.import_figure(doc, ready, wait=False), BuildStarted)
        return engine.refresh_pdf_doc(doc, self.build_async)
