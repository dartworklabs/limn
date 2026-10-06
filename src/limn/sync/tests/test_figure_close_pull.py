"""The pull a figure pin's close runs (docs/handbook/api.md §닫을 때 사유 남기기): when an agent closes a pin of a
watched document with a close reference, the merged change is fast-forwarded and imported before the close is written
and its notice emitted, so the person who gets "처리됨" already sees the edited figure.

RefreshWatched drives the sync service's refresh_watched with a recording git runner and refresh hook; the classes
after it go through server.py's wiring and the HTTP handler against a real checkout with an upstream
(helpers_figure.FigureRepo), with Poppler stood in for (helpers_figure.fake_poppler).

Run: uv run pytest -q src/limn/sync/tests/test_figure_close_pull.py
"""

import contextlib
import dataclasses
import io
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn.builds.artifacts import BuildAborted, BuildOk, cur_pages
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

    def service(self, enabled=True, budget=30.0, git=None):
        """A sync service over the two documents with a refresh budget of `budget` seconds. Its git (by default one that
        answers 'not a repository') and its refresh log each call; the refresh logs the wait it was given."""

        def not_git(args, cwd, timeout=30.0):
            """Log the git subcommand and answer as outside a repository."""
            self.log.append(("git", args[2] if args[0] == "-C" else args[0]))
            return 128, "", "not a git repository"

        self.share = PullShare()
        return SyncService(
            lambda: SyncContext(
                manuscript=Path("/srv/paper"),
                enabled=enabled,
                docs=[self.ms, self.fig],
                share=self.share,
                watch=SyncWatch(),
                start_build=lambda doc: self.log.append(("build", doc.key)),
                last_failed=lambda doc: False,
                built_head=lambda doc: "",
                refresh_now=lambda doc, wait: self.log.append(("refresh", doc.key, wait)),
                git=git or not_git,
                clock=lambda: 0.0,
                refresh_budget=budget,
            )
        )

    def kinds(self):
        """The kinds of the logged calls, in order."""
        return [entry[0] for entry in self.log]

    def hold(self, lock, seconds):
        """Hold lock on another thread for `seconds` (as a pull or build in flight does); returns once it is held."""
        held = threading.Event()

        def run():
            """Take the lock, say so, keep it, let it go."""
            with lock:
                held.set()
                time.sleep(seconds)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        held.wait(5)
        self.addCleanup(worker.join, 10)

    def test_the_round_pulls_before_the_document_is_refreshed(self):
        """Every git call of the round comes before the figure's refresh, which gets what is left of the budget, and
        the round's status is returned."""
        out = self.service().refresh_watched("fig")
        self.assertEqual((out["state"], out["reason"]), ("blocked", "not_git"))
        self.assertEqual(self.log[-1][:2], ("refresh", "fig"))
        self.assertTrue(0 < self.log[-1][2] <= 30.0)
        self.assertTrue(self.log[:-1] and set(self.kinds()[:-1]) == {"git"})

    def test_without_git_pull_nothing_is_pulled_and_the_document_is_still_refreshed(self):
        """--git-pull off: no git call at all (the checkout is never touched), and files changed in place still come
        in before the close."""
        out = self.service(enabled=False).refresh_watched("fig")
        self.assertEqual((out, self.kinds()), ({"state": "disabled"}, ["refresh"]))

    def test_an_unknown_document_is_pulled_for_but_refreshed_never(self):
        """A key this instance does not serve refreshes nothing."""
        self.service().refresh_watched("gone")
        self.assertNotIn("refresh", self.kinds())

    def test_a_round_in_flight_is_waited_for_then_the_pull_runs(self):
        """Another round holds the LaTeX document's build lock while it pulls: the close's round waits for it to end,
        then pulls itself (it is not deferred), and only then is the figure refreshed."""
        service = self.service()
        self.hold(self.ms.lock, 0.3)
        out = service.refresh_watched("fig")
        self.assertEqual((out["state"], out["reason"]), ("blocked", "not_git"))
        self.assertIn("git", self.kinds())
        self.assertEqual(self.kinds()[-1], "refresh")

    def test_a_pull_in_flight_without_a_latex_document_is_waited_for_too(self):
        """With only the figure served, the round in flight holds the pull lock: the close's round waits for it."""
        service = self.service()
        self.ms = self.fig  # the document list becomes [fig, fig]: nothing built from source
        self.hold(self.share.lock, 0.3)
        out = service.refresh_watched("fig")
        self.assertEqual(out["state"], "blocked")
        self.assertIn("git", self.kinds())

    def test_a_round_held_up_past_the_budget_gives_up_in_time(self):
        """A LaTeX build that keeps its lock past the budget: the round is deferred when the budget runs out, nothing
        is pulled, and the figure's refresh gets no time left - the whole call ends within the budget and a margin."""
        service = self.service(budget=0.6)
        self.hold(self.ms.lock, 3.0)
        start = time.monotonic()
        out = service.refresh_watched("fig")
        self.assertLess(time.monotonic() - start, 0.6 + 0.5)
        self.assertEqual(out["state"], "deferred")
        self.assertNotIn("git", self.kinds())
        self.assertLessEqual(self.log[-1][2], 0.05)

    def test_a_git_call_never_outlasts_the_budget(self):
        """A fetch that would hang is given at most what is left of the budget as its timeout, so the round ends in
        time and the figure is still refreshed."""

        def slow_git(args, cwd, timeout=30.0):
            """Answer a repository at once; let the fetch run until its timeout (at most 3 s) and fail."""
            self.log.append(("git", args[2] if args[0] == "-C" else args[0], timeout))
            if "fetch" in args:
                time.sleep(min(timeout, 3.0))
                return None, "", ""
            return 0, "/srv/paper" if "--show-toplevel" in args else "a" * 40, ""

        service = self.service(budget=0.6, git=slow_git)
        start = time.monotonic()
        out = service.refresh_watched("fig")
        self.assertLess(time.monotonic() - start, 0.6 + 0.5)
        self.assertEqual((out["state"], out["reason"]), ("error", "fetch_timeout"))
        self.assertTrue(all(entry[2] <= 0.6 for entry in self.log if entry[0] == "git"))
        self.assertEqual(self.kinds()[-1], "refresh")


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
        # A fast-forward rebuilds the LaTeX document in the background: stand in for latexmk, and let that build end
        # before the folders go.
        no_latex = mock.patch.object(ps.APP.build_requests, "compile", return_value=BuildAborted("crashed", "no TeX"))
        no_latex.start()
        self.addCleanup(no_latex.stop)
        self.addCleanup(self.builds_done, docs)
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
        emit = ps.APP.emit_events  # the pin capability's notice delivery (PinCommands.emit_events)

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

    def test_two_simultaneous_agent_closes_both_announce_the_merged_figure(self):
        """Two agents close two figure pins at the same moment, on an instance that also serves a LaTeX document: the
        close that finds the other's pull in flight waits for it and its import, so both notices go out with the
        checkout at the merged commit and the merged PDF on screen."""
        script = self.src / "figs" / "src" / "B2_calendar.py"
        second = add_pin(
            {"doc": "fig", "file": str(script), "lo": 12, "hi": 20, "page": 1, "note": "제목 줄이기"},
            dict(ALICE_ACTOR),
        ).record["id"]
        start, answers = threading.Barrier(2), {}

        def close(pid):
            """Close pin pid as the loopback agent with a reference, once both threads are ready."""
            start.wait(5)
            answers[pid] = self.call("POST", "/api/pins/%d/close" % pid, {"ref": "PR #3 (%s)" % self.merged[:7]})

        workers = [threading.Thread(target=close, args=(pid,)) for pid in (self.pid, second)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(60)
        self.assertEqual(sorted((code, body["state"]) for code, body in answers.values()), [(200, "review")] * 2)
        notices = [(head, pages) for types, head, pages in self.seen if types == ["review_requested"]]
        self.assertEqual(len(notices), 2)
        for head, pages in notices:
            self.assertEqual(head, self.merged)
            self.assertEqual((self.fig.dir / pages / "figures.pdf").read_bytes(), minimal_pdf("fig v2"))

    def test_a_refresh_that_fails_still_closes_and_announces(self):
        """A pull or import that raises (a full disk) is logged once to stderr and the close goes on: 200, the pin
        awaits review and its notice goes out."""
        err = io.StringIO()
        with (
            mock.patch.object(ps.APP.sync_service, "refresh_watched", side_effect=OSError("No space left on device")),
            contextlib.redirect_stderr(err),
        ):
            answer = self.close({"ref": "PR #3 (%s)" % self.merged[:7]})
        self.assertEqual(answer["state"], "review")
        self.assertEqual([types for types, _, _ in self.seen], [["review_requested"]])
        self.assertEqual(err.getvalue().count("OSError: No space left on device"), 1)

    def test_a_refresh_held_up_past_its_budget_still_closes_within_it(self):
        """With the LaTeX document building and the figure importing for longer than the refresh budget (1 s here),
        the close answers within the budget and a margin, unpulled, and is announced; the watch catches up later."""
        context = ps.APP.sync_service.context
        mock.patch.object(
            ps.APP.sync_service, "context", lambda: dataclasses.replace(context(), refresh_budget=1.0)
        ).start()
        self.addCleanup(mock.patch.stopall)
        held, done = threading.Event(), threading.Event()

        def busy():
            """Hold both documents' build locks until the test is over."""
            with ps.APP.docs[0].lock, self.fig.lock:
                held.set()
                done.wait(30)

        worker = threading.Thread(target=busy, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 30)
        self.addCleanup(done.set)
        held.wait(5)
        began = time.monotonic()
        answer = self.close({"ref": "PR #3 (%s)" % self.merged[:7]})
        self.assertLess(time.monotonic() - began, 1.0 + 1.5)
        self.assertEqual(answer["state"], "review")
        self.assertEqual(self.seen, [(["review_requested"], self.before, self.first)])

    def test_without_git_pull_a_close_never_pulls(self):
        """--git-pull off: the agent's close with a reference leaves the checkout at its commit (Limn moves a checkout
        only when the instance pulls), and nothing new is imported."""
        set_config(git_pull=False)
        self.close({"ref": "PR #3 (%s)" % self.merged[:7]})
        self.assertEqual((self.repo.head(), cur_pages(self.fig).name), (self.before, self.first))

    def builds_done(self, docs):
        """Wait until no build of docs is running (each build lock comes free within 30 s)."""
        for doc in docs:
            self.assertTrue(doc.lock.acquire(timeout=30), doc.key)
            doc.lock.release()

    def reopen_authority(self):
        """An authority for the loopback agent to reopen the pin, so the next subtest closes an open pin again."""
        return post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "reopen", self.pid)
