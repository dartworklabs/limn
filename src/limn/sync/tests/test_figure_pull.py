"""--git-pull for figure documents (docs/handbook/build-sync.md §자동 확인): the remote-main watch fast-forwards the
checkout a figure document is watched in, starts no build for it, and the figure watch imports the merged pair.

An instance whose only document is a figure set, served through server.py's wiring against a real checkout with an
upstream (helpers_figure.FigureRepo); Poppler is stood in for (helpers_figure.fake_poppler).

Run: uv run pytest -q src/limn/sync/tests/test_figure_pull.py
"""

import shutil
from pathlib import Path

from limn.builds.artifacts import BuildOk, cur_pages, state_snapshot

from helpers import Base, minimal_pdf, ps, set_config
from helpers_figure import FIGURE_SPEC, FigureRepo, fake_poppler, make_figure_set_docs


class FigureOnlyInstance(Base):
    """--git-pull on an instance that serves only a figure set, committed in a checkout that tracks origin."""

    def setUp(self):
        """The figure set in a checkout tracking origin (FigureRepo), served as fig alone with --git-pull and imported
        once (v1), then a re-render (v2) merged upstream."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        root = Path(self.tmp.name)
        fake_poppler(self, root)
        self.repo = FigureRepo(self.src, root)
        set_config(git_pull=True)
        docs = make_figure_set_docs(self.src, ps.APP.C.paths, [FIGURE_SPEC])
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)
        self.fig = docs[0]
        self.assertIsInstance(ps.APP.build_requests.init_doc(self.fig, no_build=True, wait=True), BuildOk)
        self.first = cur_pages(self.fig).name
        self.merged = self.repo.publish(minimal_pdf("fig v2"), "Enlarge the July cell")

    def test_the_round_fast_forwards_and_the_watch_imports_the_merged_figure(self):
        """The watch round moves the checkout to the merged commit and starts no build ("updated", seq still 1); the
        next tick of the figure watch imports the merged PDF."""
        out = ps.APP.sync_service.once()
        self.assertEqual((out["state"], out["head_after"]), ("updated", self.merged))
        self.assertEqual(self.repo.head(), self.merged)
        self.assertEqual((state_snapshot(self.fig)["seq"], cur_pages(self.fig).name), (1, self.first))
        self.assertTrue(ps.APP.build_requests.refresh_watched(self.fig))
        self.assertTrue(self.fig.lock.acquire(timeout=10))  # the import runs on its own thread until it is done
        self.fig.lock.release()
        self.assertEqual((cur_pages(self.fig) / "figures.pdf").read_bytes(), minimal_pdf("fig v2"))
