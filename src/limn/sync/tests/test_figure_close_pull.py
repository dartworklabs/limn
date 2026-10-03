"""The pull a figure pin's close runs (docs/handbook/api.md §닫을 때 사유 남기기): when an agent closes a pin of a
watched document with a close reference, the merged change is fast-forwarded and imported before the close is written
and its notice emitted, so the person who gets "처리됨" already sees the edited figure.

RefreshWatched drives the sync service's refresh_watched with a recording git runner and refresh hook; the classes
after it go through server.py's wiring and the HTTP handler against a real checkout with an upstream
(helpers_figure.FigureRepo), with Poppler stood in for (helpers_figure.fake_poppler).

Run: uv run pytest -q src/limn/sync/tests/test_figure_close_pull.py
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from limn.builds.artifacts import BuildOk, cur_pages
from limn.runtime.documents import Doc, RunPaths
from limn.security.access import LOCAL_ACTOR
from limn.sync.run import PullShare, SyncWatch
from limn.sync.service import SyncContext, SyncService

from helpers import add_pin, minimal_pdf, ps, set_config
from helpers_access import ALICE, ALICE_ACTOR, AccessBase
from helpers_authority import post_authority
from helpers_figure import FIGURE_SPEC, FigureRepo, fake_poppler, make_figure_set_docs


class RefreshWatched(unittest.TestCase):
    """SyncService.refresh_watched: one watch round (the pull), then the refresh of the named document, in that order."""

    def setUp(self):
        """A figure document and a LaTeX document over a temporary folder, and a log of git calls and refreshes."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        paths = RunPaths(root, root / "main.tex", root / "state")
        self.fig = Doc("fig", "그림", "figure", root / "figs", root / "figs" / "f.limnmap.json", paths=paths)
        self.ms = Doc("ms", "본문", "tex", root, root / "main.tex", paths=paths)
        self.log = []

    def service(self, enabled=True):
        """A sync service over the two documents whose git answers 'not a repository' and logs each call."""

        def git(args, cwd):
            """Log the git subcommand and answer as outside a repository."""
            self.log.append(("git", args[2] if args[0] == "-C" else args[0]))
            return 128, "", "not a git repository"

        return SyncService(
            lambda: SyncContext(
                manuscript=Path("/srv/paper"),
                enabled=enabled,
                docs=[self.ms, self.fig],
                share=PullShare(),
                watch=SyncWatch(),
                start_build=lambda doc: self.log.append(("build", doc.key)),
                last_failed=lambda doc: False,
                built_head=lambda doc: "",
                refresh_now=lambda doc: self.log.append(("refresh", doc.key)),
                git=git,
                clock=lambda: 0.0,
            )
        )

    def test_the_round_pulls_before_the_document_is_refreshed(self):
        """Every git call of the round comes before the figure's refresh, and the round's status is returned."""
        out = self.service().refresh_watched("fig")
        self.assertEqual((out["state"], out["reason"]), ("blocked", "not_git"))
        self.assertEqual(self.log[-1], ("refresh", "fig"))
        self.assertTrue(self.log[:-1] and all(kind == "git" for kind, _ in self.log[:-1]))

    def test_without_git_pull_nothing_is_pulled_and_the_document_is_still_refreshed(self):
        """--git-pull off: no git call at all (the checkout is never touched), and files changed in place still come
        in before the close."""
        out = self.service(enabled=False).refresh_watched("fig")
        self.assertEqual((out, self.log), ({"state": "disabled"}, [("refresh", "fig")]))

    def test_an_unknown_document_is_pulled_for_but_refreshed_never(self):
        """A key this instance does not serve refreshes nothing."""
        self.service().refresh_watched("gone")
        self.assertNotIn("refresh", [kind for kind, _ in self.log])


class FigureCloseThroughTheServer(AccessBase):
    """POST /api/pins/{id}/close through the handler, with --git-pull, on a figure set whose upstream holds a merged
    re-render: what the checkout and the screen hold when the close's notice is emitted."""

    def setUp(self):
        """The manuscript and its figure set committed in a checkout tracking origin (FigureRepo), served as ms and fig
        with --git-pull, fig imported once (v1), a person's pin on the July cell's lines, and a re-render (v2) merged
        upstream; emitted notices are logged with the checkout's HEAD and the page folder on screen at that moment."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        root = Path(self.tmp.name)
        fake_poppler(self, root)
        self.repo = FigureRepo(self.src, root)
        set_config(git_pull=True)
        docs = make_figure_set_docs(self.src, ps.APP.C.paths, ["ms=본문:main.tex", FIGURE_SPEC])
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)
        self.fig = docs[1]
        self.assertIsInstance(ps.APP.build_requests.init_doc(self.fig, no_build=True, wait=True), BuildOk)
        self.first = cur_pages(self.fig).name
        script = self.src / "figs" / "src" / "B2_calendar.py"
        self.pid = add_pin(
            {"doc": "fig", "file": str(script), "lo": 88, "hi": 95, "page": 1, "note": "7월 칸 글자 키우기"},
            dict(ALICE_ACTOR),
        ).record["id"]
        self.before = self.repo.head()
        self.merged = self.repo.publish(minimal_pdf("fig v2"), "Enlarge the July cell")
        self.seen = []
        emit = ps.APP.emit_events  # the pin capability's notice port (PinCommands.emit_events)

        def at_emit(events):
            """Log what is on disk when the notices go out, then emit them."""
            self.seen.append(([e["type"] for e in events if e], self.repo.head(), cur_pages(self.fig).name))
            return emit(events)

        patcher = mock.patch.object(ps.APP, "emit_events", side_effect=at_emit)
        patcher.start()
        self.addCleanup(patcher.stop)

    def close(self, body, headers=None):
        """POST the close of the pin with body, as the loopback agent or as headers' person; the parsed answer."""
        code, answer = self.call("POST", "/api/pins/%d/close" % self.pid, body, headers=headers)
        self.assertEqual(code, 200, answer)
        return answer

    def test_an_agents_close_with_a_reference_shows_the_merged_figure_before_its_notice(self):
        """When review_requested is emitted the checkout is at the merged commit and the screen at a new build holding
        the merged PDF: the pull and the import came first."""
        answer = self.close({"reply": "키웠습니다", "ref": "PR #3 (%s)" % self.merged[:7]})
        self.assertEqual(answer["state"], "review")
        self.assertEqual(len(self.seen), 1)
        types, head, pages = self.seen[0]
        self.assertEqual((types, head), (["review_requested"], self.merged))
        self.assertNotEqual(pages, self.first)
        self.assertEqual((self.fig.dir / pages / "figures.pdf").read_bytes(), minimal_pdf("fig v2"))

    def test_closes_that_announce_nothing_or_name_no_change_never_pull(self):
        """A person's own close (done, no notice to wait for) and an agent's close without a reference leave the
        checkout and the screen as they were."""
        for name, body, headers in (
            ("a person's close", {"ref": "PR #3"}, ALICE),
            ("no reference", {"reply": "done"}, None),
        ):
            with self.subTest(name):
                self.close(body, headers)
                self.assertEqual((self.repo.head(), cur_pages(self.fig).name), (self.before, self.first))
                ps.APP.pin_lifecycle.reopen_pin(self.pid, self.reopen_authority())

    def test_without_git_pull_a_close_never_pulls(self):
        """--git-pull off: the agent's close with a reference leaves the checkout at its commit (Limn moves a checkout
        only when the instance pulls), and nothing new is imported."""
        set_config(git_pull=False)
        self.close({"ref": "PR #3 (%s)" % self.merged[:7]})
        self.assertEqual((self.repo.head(), cur_pages(self.fig).name), (self.before, self.first))

    def reopen_authority(self):
        """An authority for the loopback agent to reopen the pin, so the next subtest closes an open pin again."""
        return post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "reopen", self.pid)
