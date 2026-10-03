"""Per-instance build execution, startup initialization and view-only PDF watch."""

import sys
import threading
import traceback
from collections.abc import Callable, Sequence
from typing import Any

from limn.builds import artifacts as build, engine, figure, run
from limn.builds.artifacts import (
    BuildBusy,
    BuildConfig,
    BuildOk,
    BuildSkipped,
    BuildStarted,
    Describe,
    FinishedBuild,
    ViewOnlyNoRebuild,
)
from limn.builds.figure import FigureImport
from limn.runtime.config import RunConfig
from limn.runtime.documents import Doc, document_authority_target
from limn.security.access import AuthorityScope, PostAuthority, require_authority

Json = dict[str, Any]
REFRESH_WAIT_S = 60.0  # how long refresh_watched_now waits for a build of the same document already running


class BuildRequests:
    """Run and watch document builds with the current run settings and shared document locks."""

    def __init__(
        self,
        settings: Callable[[], RunConfig],
        pull: Callable[[], Json],
        docs: Callable[[], Sequence[Doc]],
        now: Callable[[], str],
        describe: Describe,
        figure_shown: Callable[[], None] = lambda: None,
    ) -> None:
        """Bind run facts as call-time lookups so a new setting or runtime is seen on the next build, and start this
        run's memo of figure maps. figure_shown is the composition root's hook, called once each time an import puts a
        new build of a figure document on screen (see announce_figure_shown); by default it does nothing."""
        self.settings = settings
        self.pull = pull
        self.docs = docs
        self.now = now
        self.describe = describe
        self.figure_shown = figure_shown
        self.figure_looks = figure.MapLooks()  # this run's memo of each figure document's map parse (figure.MapLooks)

    @property
    def authority_scope(self) -> AuthorityScope:
        """Snapshot this service and the current storage namespace before authorizing a build."""
        return AuthorityScope(self, str(self.settings().state.resolve()))

    def config(self) -> BuildConfig:
        """Current state folder, dpi and timeout for one build."""
        c = self.settings()
        return BuildConfig(state=c.state, dpi=c.dpi, timeout=c.timeout)

    def compile(self, doc: Doc, force: bool = False) -> FinishedBuild:
        """Compile one LaTeX document, pulling its repository first when configured; force builds cold and never
        skips (engine.compile_tex)."""
        return engine.compile_tex(doc, self.config(), self.pull if self.settings().git_pull else None, force)

    def tracked(self, doc: Doc, ready: FigureImport | None = None, force: bool = False) -> FinishedBuild:
        """Run one build of doc (build_step) and commit its status and page history (run.run_tracked). ready is a
        figure document's verified pair (figure.pending_import); without it such a document reads and checks its files
        itself. force is a LaTeX document's forced cold build."""
        return run.run_tracked(
            doc, self.settings().state, lambda: self.build_step(doc, ready, force), self.now(), self.describe
        )

    def build_step(self, doc: Doc, ready: FigureImport | None = None, force: bool = False) -> FinishedBuild:
        """One untracked build of doc, chosen by capability: latexmk for a document built from source (force: cold, no
        skip); the import of its map and PDF for a document with an element map (figure.import_now, with ready when
        given); otherwise the render of its view-only PDF."""
        if doc.builds_from_source:
            return self.compile(doc, force)
        if doc.has_element_map:
            imported = figure.import_now(doc, self.config(), ready)
            if isinstance(imported, BuildOk):
                self.announce_figure_shown()
            return imported
        return engine.render_pdf_doc(doc, self.config())

    def announce_figure_shown(self) -> None:
        """Tell the composition root (figure_shown) that pages.cur of a figure document now names a new build. The one
        place this is said: every import - startup, the watch, a rebuild call - is a tracked build_step, and no LaTeX
        build or view-only render comes through here. Called after the pages moved and before the build is recorded,
        so a reader that sees the build ok finds the files that follow it already refreshed. The hook only refreshes a
        file for readers, so its failure is printed to stderr and does not fail the import: the pages are on screen
        already."""
        try:
            self.figure_shown()
        except Exception:  # noqa: BLE001 — the import has landed; a failed refresh must not turn it into a failed build
            traceback.print_exc(file=sys.stderr)

    def import_figure(self, doc: Doc, ready: FigureImport, wait: bool) -> FinishedBuild | BuildStarted | BuildBusy:
        """Import a verified figure pair through the tracked build: now when wait, else on a daemon thread. BuildBusy
        when doc is already building; nothing was settled then, so the watch tries again on its next tick."""
        if wait:
            return run.build_now(doc, lambda: self.tracked(doc, ready))
        return run.build_in_background(doc, lambda: self.tracked(doc, ready), self.now(), self.describe)

    def build_all(self, doc: Doc, force: bool = False) -> FinishedBuild | BuildBusy:
        """Build now, or return busy when this document's build lock is held. force builds cold, never skipping."""
        return run.build_now(doc, lambda: self.tracked(doc, force=force))

    def build_async(self, doc: Doc, force: bool = False) -> BuildStarted | BuildBusy:
        """Start a tracked build on a daemon thread, or return busy. force builds cold, never skipping."""
        return run.build_in_background(doc, lambda: self.tracked(doc, force=force), self.now(), self.describe)

    def rebuild(
        self, doc: Doc, authority: PostAuthority, force: bool = False
    ) -> FinishedBuild | BuildBusy | ViewOnlyNoRebuild:
        """Refuse manual rebuild of a view-only document; otherwise build now (force: POST /api/rebuild?force=1)."""
        require_authority(authority, self.authority_scope, "rebuild", document_authority_target(doc))
        return run.request_rebuild(doc, lambda d: self.build_all(d, force))

    def rebuild_async(
        self, doc: Doc, authority: PostAuthority, force: bool = False
    ) -> BuildStarted | BuildBusy | ViewOnlyNoRebuild:
        """Refuse manual rebuild of a view-only document; otherwise start in the background (force as in rebuild)."""
        require_authority(authority, self.authority_scope, "rebuild", document_authority_target(doc))
        return run.request_rebuild(doc, lambda d: self.build_async(d, force))

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

    def refresh_watched_now(self, doc: Doc, wait: float = REFRESH_WAIT_S) -> FinishedBuild | None:
        """The watch tick for doc run in the caller's thread, which waits for its build: first up to `wait` seconds
        for doc's build lock (an import or redraw the watch thread already started finishes first), then, holding it,
        the import of doc's map and PDF when they changed and agree (figure.pending_import), or the redraw of its
        view-only PDF when that changed (engine.pdf_changed), through the tracked build. Returns that build's outcome;
        None when doc's files are not watched, nothing changed, or the lock was still held after `wait`. An agent's
        close calls this through the sync service so the author's notice comes after the new pages
        (docs/handbook/api.md §닫을 때 사유 남기기)."""
        if not doc.watches_files or not doc.lock.acquire(timeout=wait):
            return None
        try:
            if doc.has_element_map:
                ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=False)
                return None if ready is None else self.tracked(doc, ready)
            return self.tracked(doc) if engine.pdf_changed(doc) else None
        finally:
            doc.lock.release()

    def refresh_watched(self, doc: Doc) -> bool:
        """One watch tick for doc. A document with an element map imports its map and PDF once they agree
        (figure.pending_import) and otherwise builds nothing and records no failure; while it is building (its lock
        held) the tick looks at nothing - the running import settles its signature before it lets go of the lock, so
        the next free tick sees exactly what it left, and no file is read or hashed meanwhile. A view-only PDF
        re-renders when its file changed (engine.refresh_pdf_doc). True when a build started; False for a document
        whose files are not watched, or a figure document that is building."""
        if not doc.watches_files:
            return False
        if doc.has_element_map:
            if doc.lock.locked():
                return False
            ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=False)
            return ready is not None and isinstance(self.import_figure(doc, ready, wait=False), BuildStarted)
        return engine.refresh_pdf_doc(doc, self.build_async)
