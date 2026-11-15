"""The line-mark pass in the upkeep cycle and after a build: where it runs, how far it goes, and that it fills the cache the
listing reads (limn.pins.runtime.PinCommands.fill_line_marks, limn.pins.maintenance.PinMaintenance).

Run: uv run pytest -q src/limn/pins/tests/test_maintenance_marks.py
"""

import io
import threading
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

from limn.builds.artifacts import BuildAborted, BuildOk, BuildOkWithErrors
from limn.builds.service import BuildRequests
from limn.pins.location import source as pick_source
from limn.pins.maintenance import MARK_BUILD_SECONDS, MARK_FILL_LIMIT, MARK_SECONDS, PinMaintenance
from limn.pins.runtime import PinCommands
from limn.runtime.documents import Doc
from limn.security.access import LOCAL_ACTOR

from helpers import Base, add_pin, blank_png, built_record, ps

HIT = [(1, 100.0, 200.0, 300.0, 10.0)]


class Pass(Base):
    """A real run with one document whose build on screen has two pages and no PDF: SyncTeX is stood in for."""

    def setUp(self):
        super().setUp()
        pages = ps.APP.C.state / "pages-20260925100000"
        pages.mkdir()
        for i in (1, 2):
            (pages / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
        (ps.APP.C.state / "pages.cur").write_text(pages.name)
        built_record(pages, ps.APP.C.src, ps.APP.C.main)  # as a real build publishes it: the file this build read
        self.doc = ps.APP.docs[0]
        self.build = pages.name

    def marked(self, upto=9):
        return [i for i in range(1, upto + 1) if ps.APP.line_marks.get(self.doc.key, self.build, i) is not None]

    def pin_lines(self, n):
        return [self.add(lo=4 + i, hi=4 + i) for i in range(n)]

    def test_the_marks_a_pass_stores_are_the_ones_a_listing_asks_for(self):
        """The build name and the cache instance are the ones line_mark_of resolves: a mark the pass stored is what GET reads."""
        (pid,) = self.pin_lines(1)
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT):
            self.assertEqual(ps.APP.fill_line_marks(), 1)
        mark = ps.APP.line_mark_of(self.doc.key)(pid)
        self.assertIsNotNone(mark)
        self.assertEqual(mark.page, 1)

    def test_the_pass_stops_at_its_budget_and_takes_the_next_pins_on_the_following_run(self):
        self.pin_lines(5)
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT):
            first = ps.APP.fill_line_marks(fills=2)
            self.assertEqual((first, self.marked()), (2, [1, 2]))
            second = ps.APP.fill_line_marks(fills=2)
        # no starvation: it moves on, it does not redo 1 and 2
        self.assertEqual((second, self.marked()), (2, [1, 2, 3, 4]))

    def test_the_pass_stops_at_its_deadline(self):
        self.pin_lines(3)
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT) as view:
            self.assertEqual(ps.APP.fill_line_marks(seconds=0.0), 0)
        self.assertEqual(view.call_count, 0)

    def test_the_budget_is_two_hundred_marks_and_ten_seconds(self):
        self.assertEqual((MARK_FILL_LIMIT, MARK_SECONDS), (200, 10.0))

    def test_the_budget_counts_marks_filled_not_pins_looked_at(self):
        """What MARK_FILL_LIMIT's name says: an unanswerable pin spends a lookup and no fill, so a budget of one still
        reaches the pin behind it instead of being used up by the one in front."""
        self.pin_lines(2)
        with mock.patch.object(pick_source, "synctex_view", side_effect=[None, HIT]) as view:
            self.assertEqual(ps.APP.fill_line_marks(fills=1), 1)
        self.assertEqual((view.call_count, self.marked()), (2, [2]))

    def test_the_budget_is_shared_by_every_document(self):
        (ps.APP.C.src / "other.tex").write_text("x\n" * 20, encoding="utf-8")
        other = Doc("other", "other", "tex", ps.APP.C.src, ps.APP.C.src / "other.tex", paths=ps.APP.C.paths)
        ps.APP.set_docs([self.doc, other])
        pages = other.dir / "pages-20260925100000"
        pages.mkdir(parents=True)
        (pages / "page-1.png").write_bytes(blank_png(1275, 1650))
        (other.dir / "pages.cur").write_text(pages.name)
        built_record(pages, other.src, other.main)
        self.add(lo=4, hi=4)
        self.add(lo=5, hi=5)
        note = {"file": str(ps.APP.C.src / "other.tex"), "lo": 3, "hi": 3, "page": 1, "note": "o"}
        add_pin(note, dict(LOCAL_ACTOR), doc=other)
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT):
            self.assertEqual(ps.APP.fill_line_marks(fills=2), 2)
            self.assertEqual(ps.APP.fill_line_marks(fills=2), 1)

    def test_only_a_latex_document_is_asked_not_a_figure_a_markdown_a_text_or_a_view_only_document(self):
        """Real Docs: the kind-to-capability mapping decides, so widening or narrowing the exclusion fails here. Every pin
        is made to belong to the document under test, so only the document's own kind can keep it out."""
        src, paths = ps.APP.C.src, ps.APP.C.paths
        kinds = {"tex": True, "figure": False, "markdown": False, "text": False, "pdf": False}
        self.pin_lines(1)
        for kind, asked in kinds.items():
            doc = Doc("d-" + kind, kind, kind, src, src / ("main." + kind), paths=paths)
            with self.subTest(kind=kind):
                ps.APP.set_docs([doc])
                with (
                    mock.patch.object(ps.APP.assembly.pins.commands, "pin_doc_key", return_value=doc.key),
                    mock.patch.object(PinCommands, "mark_context", return_value=None) as context,
                ):
                    ps.APP.fill_line_marks()
                self.assertEqual(context.call_count, 1 if asked else 0)

    def test_a_document_without_a_build_on_screen_gets_no_context(self):
        (ps.APP.C.state / "pages.cur").unlink()
        self.pin_lines(1)
        with mock.patch.object(pick_source, "synctex_view", side_effect=AssertionError("asked")):
            self.assertEqual(ps.APP.fill_line_marks(), 0)

    def test_the_context_names_the_build_the_listing_resolves(self):
        ctx = ps.APP.mark_context(self.doc)
        self.assertEqual(ctx.build, ps.APP.build_view.heading(self.doc).build)
        self.assertEqual((len(ctx.sizes), ctx.stale_src), (2, False))

    def test_a_pass_that_cannot_wait_does_nothing_while_another_runs(self):
        self.pin_lines(1)
        held = ps.APP.assembly.pins.commands._mark_pass
        with held, mock.patch.object(pick_source, "synctex_view", return_value=HIT) as view:
            self.assertEqual(ps.APP.fill_line_marks(wait=False), 0)
        self.assertEqual(view.call_count, 0)

    def test_the_build_pass_runs_on_the_calling_thread(self):
        seen = []
        with mock.patch.object(
            pick_source, "synctex_view", side_effect=lambda *a: seen.append(threading.current_thread()) or HIT
        ):
            self.add(lo=4, hi=4)
            ps.APP.fill_line_marks_after_build()
            self.assertIsNotNone(ps.APP.line_marks.get(self.doc.key, self.build, 1))
        self.assertEqual(seen, [threading.current_thread()])

    def test_the_build_budget_starts_after_the_pass_lock_is_held(self):
        self.pin_lines(1)
        held = ps.APP.assembly.pins.commands._mark_pass
        held.acquire()
        threading.Timer(0.3, held.release).start()
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT):
            self.assertEqual(ps.APP.fill_line_marks(seconds=0.2, wait=True), 1)

    def test_the_pass_writes_no_pin(self):
        self.pin_lines(2)
        path = ps.APP.C.state / "pins.jsonl"
        before = (path.read_bytes(), path.stat().st_ino)
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT):
            ps.APP.fill_line_marks()
        self.assertEqual((path.read_bytes(), path.stat().st_ino), before)


class Upkeep(Base):
    """PinMaintenance calls the pass after its locked work, and survives it."""

    def test_the_mark_pass_runs_outside_the_pin_store_lock(self):
        # a pin write on another thread must not wait on the pass, so probe from a thread
        # (a re-entrant lock would hand itself to the calling thread and hide this)
        store, free = ps.APP.pin_store(), []

        def probe():
            got = store.lock.acquire(blocking=False)
            if got:
                store.lock.release()
            free.append(got)

        def marks():
            t = threading.Thread(target=probe)
            t.start()
            t.join()
            return 0

        PinMaintenance(store=lambda: store, days=7, marks=marks).run()
        self.assertEqual(free, [True])

    def test_a_pass_longer_than_the_run_does_not_make_the_next_run_skip(self):
        """The overlap guard is released before the pass: a slow pass must not stop pins being re-synced."""
        store, seen = ps.APP.pin_store(), []
        upkeep = PinMaintenance(store=lambda: store, days=7)

        def marks():
            seen.append(upkeep._running.acquire(blocking=False))
            if seen[-1]:
                upkeep._running.release()
            return 0

        upkeep.marks = marks
        upkeep.run()
        self.assertEqual(seen, [True])

    def test_no_pass_runs_when_the_resync_failed(self):
        calls = []
        with (
            mock.patch("limn.pins.store.PinStore.maintain", side_effect=OSError("x")),
            mock.patch("limn.pins.maintenance.diagnostics"),
        ):
            PinMaintenance(store=ps.APP.pin_store, days=7, marks=lambda: calls.append(1) or 0).run()
        self.assertEqual(calls, [])

    def hold_guard(self, upkeep, seconds):
        """Hold upkeep's overlap guard from another thread for `seconds`, as an upkeep run in progress does."""
        held, release = threading.Event(), threading.Event()

        def hold():
            with upkeep._running:
                held.set()
                release.wait(seconds)

        thread = threading.Thread(target=hold)
        thread.start()
        held.wait(5)
        return thread, release

    def test_a_waiting_run_waits_for_a_run_in_progress_instead_of_skipping(self):
        calls = []
        upkeep = PinMaintenance(store=ps.APP.pin_store, days=7)
        thread, release = self.hold_guard(upkeep, 0.3)
        started = time.monotonic()
        upkeep.run(lambda: calls.append(1) or 0, wait=True)
        thread.join()
        self.assertEqual(calls, [1])
        self.assertGreaterEqual(time.monotonic() - started, 0.25)

    def test_a_run_that_does_not_wait_skips_at_once_while_one_is_in_progress(self):
        calls = []
        upkeep = PinMaintenance(store=ps.APP.pin_store, days=7)
        thread, release = self.hold_guard(upkeep, 5)
        started = time.monotonic()
        upkeep.run(lambda: calls.append(1) or 0)
        release.set()
        thread.join()
        self.assertEqual(calls, [])
        self.assertLess(time.monotonic() - started, 0.5)

    def test_a_waiting_run_gives_up_after_the_wait_runs_no_pass_and_says_so(self):
        calls = []
        upkeep = PinMaintenance(store=ps.APP.pin_store, days=7)
        thread, release = self.hold_guard(upkeep, 5)
        with (
            mock.patch("limn.pins.maintenance.MARK_BUILD_WAIT_SECONDS", 0.2),
            mock.patch("limn.pins.maintenance.diagnostics") as errors,
        ):
            started = time.monotonic()
            upkeep.run(lambda: calls.append(1) or 0, wait=True)
            took = time.monotonic() - started
        release.set()
        thread.join()
        self.assertEqual(calls, [])
        self.assertTrue(0.15 <= took < 2.0, took)
        self.assertEqual(errors.emit.call_args[0][0], "pin maintenance:busy")

    def test_each_run_calls_the_pass_once(self):
        calls = []
        PinMaintenance(store=ps.APP.pin_store, days=7, marks=lambda: calls.append(1) or 0).run()
        self.assertEqual(calls, [1])

    def test_a_failing_pass_does_not_stop_upkeep(self):
        def boom():
            raise OSError("boom")

        with mock.patch("limn.pins.maintenance.diagnostics") as errors:
            upkeep = PinMaintenance(store=ps.APP.pin_store, days=7, marks=boom)
            upkeep.run()  # no raise
            self.assertGreater(upkeep._completed, 0.0)  # the pins were maintained
            upkeep.run()  # and the cycle still runs
        cause, message = errors.emit.call_args[0]
        self.assertEqual(cause, "pin marks:OSError")
        self.assertIn("boom", message())

    def test_a_run_given_its_own_pass_uses_it_instead_of_the_upkeep_pass(self):
        calls = []
        PinMaintenance(store=ps.APP.pin_store, days=7, marks=lambda: calls.append("upkeep") or 0).run(
            lambda: calls.append("build") or 0
        )
        self.assertEqual(calls, ["build"])

    def test_the_composition_root_wires_the_pass_into_upkeep(self):
        """assemble_pins gives the upkeep the writer-side pass (and it does not wait for a pass that is running)."""
        with mock.patch.object(PinCommands, "fill_line_marks", return_value=0) as fill:
            ps.APP.assembly.pins.startup.maintain()
        fill.assert_called_once_with(wait=False)


class AfterBuild(Base):
    """A build that puts new pages on screen asks for the marks at once."""

    def test_the_composition_root_fills_marks_inline_when_a_build_lands(self):
        with mock.patch.object(PinCommands, "fill_line_marks", return_value=0) as fill:
            ps.APP.build_requests.latex_built()
        fill.assert_called_once_with(MARK_FILL_LIMIT, MARK_BUILD_SECONDS, wait=False)

    def test_the_build_path_has_a_tighter_budget_than_upkeep(self):
        self.assertEqual((MARK_BUILD_SECONDS, MARK_SECONDS), (2.0, 10.0))
        self.assertLess(MARK_BUILD_SECONDS, MARK_SECONDS)

    def test_a_build_callback_resyncs_the_lines_before_it_fills_the_marks_in_one_step(self):
        """The anti-goal is a solid mark on the wrong place: the manuscript is edited so the pin's lines move and the build
        lands before any upkeep tick. When the callback returns, SyncTeX was asked about the NEW lines only (never the
        pre-edit ones) and the pin's mark is there, with no second pass."""
        pages = ps.APP.C.state / "pages-20260925100000"
        pages.mkdir()
        (pages / "page-1.png").write_bytes(blank_png(1275, 1650))
        (ps.APP.C.state / "pages.cur").write_text(pages.name)
        built_record(pages, ps.APP.C.src, ps.APP.C.main)
        pid = self.add(lo=4, hi=4)
        main = ps.APP.C.main
        main.write_text("inserted\n" * 20 + main.read_text(encoding="utf-8"), encoding="utf-8")
        asked = []

        def where(pdf, line, name):
            asked.append(line)
            return HIT

        with mock.patch.object(pick_source, "synctex_view", side_effect=where):
            ps.APP.build_requests.latex_built()
        self.assertEqual(asked, [24])
        self.assertIsNotNone(ps.APP.line_mark_of(ps.APP.docs[0].key)(pid))

    def requests(self, hook):
        return BuildRequests(
            lambda: ps.APP.C, lambda: {}, lambda: ps.APP.docs, lambda: "T", lambda r: "", latex_built=hook
        )

    def ok(self):
        return BuildOk("", 0.1, None, None, "h" * 32, "-", "pages-20260926120000", 1)

    def test_a_tracked_latex_build_calls_the_hook_once_after_it_is_recorded(self):
        calls = []
        requests = self.requests(lambda: calls.append(requests.settings and 1))
        with mock.patch.object(requests, "build_step", return_value=self.ok()):
            requests.tracked(ps.APP.docs[0])
        self.assertEqual(calls, [1])

    def test_a_latex_build_that_finished_with_errors_calls_the_hook_too(self):
        """A log with LaTeX errors and a new PDF all the same is a common real outcome (a missing reference, an
        overfull-turned-error package): those pages are on screen, so their marks must be filled now and not wait for
        the next upkeep tick up to 60 s away."""
        calls = []
        requests = self.requests(lambda: calls.append(1))
        errored = BuildOkWithErrors(
            [], "! Undefined control sequence.", 0.1, None, 0.1, "h" * 32, "-", "pages-20260926120000", 1
        )
        with mock.patch.object(requests, "build_step", return_value=errored):
            requests.tracked(ps.APP.docs[0])
        self.assertEqual(calls, [1])

    def test_a_failed_or_figure_or_view_only_build_does_not_call_the_hook(self):
        calls = []
        requests = self.requests(lambda: calls.append(1))
        fig = Doc("fig", "f", "figure", ps.APP.C.src, ps.APP.C.src / "main.tex", paths=ps.APP.C.paths)
        with mock.patch.object(requests, "build_step", return_value=self.ok()):
            requests.tracked(fig)
        with mock.patch.object(requests, "build_step", return_value=BuildAborted("crashed", "x")):
            requests.tracked(ps.APP.docs[0])
        self.assertEqual(calls, [])

    def test_a_hook_that_raises_is_printed_and_the_build_still_lands(self):
        def broken():
            raise RuntimeError("hook broke")

        requests = self.requests(broken)
        err = io.StringIO()
        with mock.patch.object(requests, "build_step", return_value=self.ok()), redirect_stderr(err):
            self.assertIsInstance(requests.tracked(ps.APP.docs[0]), BuildOk)
        self.assertIn("hook broke", err.getvalue())


if __name__ == "__main__":
    unittest.main()
