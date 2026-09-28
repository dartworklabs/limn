"""Per-instance build execution, startup initialization and view-only PDF watch."""

import sys
import threading
import traceback
from collections.abc import Callable, Sequence
from typing import Any

from limn import build
from limn.build import BuildBusy, BuildConfig, BuildSkipped, BuildStarted, Describe, FinishedBuild, ViewOnlyNoRebuild
from limn.config import RunConfig
from limn.documents import Doc
from limn.features.builds import engine, run

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
        """Bind run facts as call-time lookups so a new setting or runtime is seen on the next build."""
        self.settings = settings
        self.pull = pull
        self.docs = docs
        self.now = now
        self.describe = describe

    def config(self) -> BuildConfig:
        """Current state folder, dpi and timeout for one build."""
        c = self.settings()
        return BuildConfig(state=c.state, dpi=c.dpi, timeout=c.timeout)

    def compile(self, doc: Doc) -> FinishedBuild:
        """Compile one LaTeX document, pulling its repository first when configured."""
        return engine.compile_tex(doc, self.config(), self.pull if self.settings().git_pull else None)

    def tracked(self, doc: Doc) -> FinishedBuild:
        """Run the document's LaTeX or view-only PDF build and commit its status and page history."""
        step: Callable[[], FinishedBuild] = (
            (lambda: engine.render_pdf_doc(doc, self.config())) if doc.is_pdf else (lambda: self.compile(doc))
        )
        return run.run_tracked(doc, self.settings().state, step, self.now(), self.describe)

    def build_all(self, doc: Doc) -> FinishedBuild | BuildBusy:
        """Build now, or return busy when this document's build lock is held."""
        return run.build_now(doc, lambda: self.tracked(doc))

    def build_async(self, doc: Doc) -> BuildStarted | BuildBusy:
        """Start a tracked build on a daemon thread, or return busy."""
        return run.build_in_background(doc, lambda: self.tracked(doc), self.now(), self.describe)

    def rebuild(self, doc: Doc) -> FinishedBuild | BuildBusy | ViewOnlyNoRebuild:
        """Refuse manual rebuild of a view-only document; otherwise build now."""
        return run.request_rebuild(doc, self.build_all)

    def rebuild_async(self, doc: Doc) -> BuildStarted | BuildBusy | ViewOnlyNoRebuild:
        """Refuse manual rebuild of a view-only document; otherwise start in the background."""
        return run.request_rebuild(doc, self.build_async)

    def init_doc(self, doc: Doc, no_build: bool, wait: bool) -> FinishedBuild | BuildStarted | BuildBusy | BuildSkipped:
        """Restore build history and start a needed build, synchronously only when requested."""
        doc.dir.mkdir(parents=True, exist_ok=True)
        if doc.root:
            build.migrate_pages(doc)
        build.seed_builds(doc, self.settings().state)
        if not run.needs_build(doc, no_build, self.settings().dpi):
            return BuildSkipped()
        return self.build_all(doc) if wait else self.build_async(doc)

    def watch_pdf_docs(self, stop: threading.Event, every: float = 3.0) -> None:
        """Re-render changed view-only PDFs until this run's stop event is set."""
        while not stop.wait(every):
            for doc in list(self.docs()):
                if doc.is_pdf:
                    try:
                        engine.refresh_pdf_doc(doc, self.build_async)
                    except Exception:  # noqa: BLE001 — the watch thread must never die
                        traceback.print_exc(file=sys.stderr)
