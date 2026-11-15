"""The line-mark pass in the upkeep cycle and after a build: where it runs, how far it goes, and that it fills the cache the
listing reads (limn.pins.runtime.PinCommands.fill_line_marks, limn.pins.maintenance.PinMaintenance).

Run: uv run pytest -q src/limn/pins/tests/test_maintenance_marks.py
"""

import io
import threading
import unittest
from contextlib import redirect_stderr
from unittest import mock

from limn.builds.artifacts import BuildAborted, BuildOk
from limn.builds.service import BuildRequests
from limn.pins.location import source as pick_source
from limn.pins.maintenance import MARK_LIMIT, MARK_SECONDS, PinMaintenance
from limn.pins.runtime import PinCommands
from limn.runtime.documents import Doc
from limn.security.access import LOCAL_ACTOR

from helpers import Base, add_pin, blank_png, ps

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
            first = ps.APP.fill_line_marks(limit=2)
            self.assertEqual((first, self.marked()), (2, [1, 2]))
            second = ps.APP.fill_line_marks(limit=2)
        # no starvation: it moves on, it does not redo 1 and 2
        self.assertEqual((second, self.marked()), (2, [1, 2, 3, 4]))

    def test_the_pass_stops_at_its_deadline(self):
        self.pin_lines(3)
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT) as view:
            self.assertEqual(ps.APP.fill_line_marks(seconds=0.0), 0)
        self.assertEqual(view.call_count, 0)

    def test_the_budget_is_two_hundred_marks_and_ten_seconds(self):
        self.assertEqual((MARK_LIMIT, MARK_SECONDS), (200, 10.0))

    def test_the_budget_is_shared_by_every_document(self):
        (ps.APP.C.src / "other.tex").write_text("x\n" * 20, encoding="utf-8")
        other = Doc("other", "other", "tex", ps.APP.C.src, ps.APP.C.src / "other.tex", paths=ps.APP.C.paths)
        ps.APP.set_docs([self.doc, other])
        pages = other.dir / "pages-20260925100000"
        pages.mkdir(parents=True)
        (pages / "page-1.png").write_bytes(blank_png(1275, 1650))
        (other.dir / "pages.cur").write_text(pages.name)
        self.add(lo=4, hi=4)
        self.add(lo=5, hi=5)
        note = {"file": str(ps.APP.C.src / "other.tex"), "lo": 3, "hi": 3, "page": 1, "note": "o"}
        add_pin(note, dict(LOCAL_ACTOR), doc=other)
        with mock.patch.object(pick_source, "synctex_view", return_value=HIT):
            self.assertEqual(ps.APP.fill_line_marks(limit=2), 2)
            self.assertEqual(ps.APP.fill_line_marks(limit=2), 1)

    def test_a_figure_a_markdown_and_a_text_document_are_not_asked(self):
        figure = mock.Mock(takes_line_pins=True, has_element_map=True, renders_in_browser=False, key="fig")
        md = mock.Mock(takes_line_pins=True, has_element_map=False, renders_in_browser=True, key="md")
        pdf = mock.Mock(takes_line_pins=False, has_element_map=False, renders_in_browser=False, key="rv")
        self.pin_lines(1)
        with (
            mock.patch.object(ps.APP.assembly.pins.commands, "docs", [figure, md, pdf]),
            mock.patch.object(PinCommands, "mark_context") as context,
            mock.patch.object(pick_source, "synctex_view", side_effect=AssertionError("asked")),
        ):
            self.assertEqual(ps.APP.fill_line_marks(), 0)
        context.assert_not_called()

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

    def test_the_composition_root_wires_the_pass_into_upkeep(self):
        """assemble_pins gives the upkeep the writer-side pass (and it does not wait for a pass that is running)."""
        with mock.patch.object(PinCommands, "fill_line_marks", return_value=0) as fill:
            ps.APP.assembly.pins.startup.maintain()
        fill.assert_called_once_with(wait=False)


class AfterBuild(Base):
    """A build that puts new pages on screen asks for the marks at once."""

    def test_the_composition_root_fills_marks_when_a_build_lands(self):
        done = threading.Event()
        with mock.patch.object(PinCommands, "fill_line_marks", side_effect=lambda *a, **k: done.set() or 0) as fill:
            ps.APP.build_requests.latex_built()
            self.assertTrue(done.wait(5))
        fill.assert_called_once_with()

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
