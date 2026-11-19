"""Pin the audit that keeps the run's kept pin lines honest (helpers.kept_lines_changed, run by Base.tearDown and
BrowserBase.tearDown after every test).

The pins a read-only reader hands out are shared between requests (limn.pins.store.KeptPinReader), so a read path
that changed one - a nested dict of a record, say - would hand the changed value to every later reader. No type
forbids that in Python; this audit is what does. It compares every kept value with a fresh parse of its own line,
so every existing test that reads pins, by GET or inside a POST, is a check of the path it exercised."""

import unittest

from limn.security.access import LOCAL_ACTOR

from helpers import Base, add_pin, fresh_runtime, kept_lines_changed, ps
from helpers_authority import post_authority


class KeptLinesAudit(Base):
    """kept_lines_changed() names the lines whose kept value is no longer what the line parses to."""

    def setUp(self):
        """Two pins, one with a reply and one in the Trash, each read once so its line is kept."""
        super().setUp()
        self.first = self.add(4, 5, note="first")
        self.second = self.add(8, 9, note="second")
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.reply_pin(self.first, "ok", post_authority(store, dict(LOCAL_ACTOR), "reply", self.first))
        ps.APP.pin_trash.drop_pin(self.second, post_authority(store, dict(LOCAL_ACTOR), "drop", self.second))
        ps.APP.read_pins()
        ps.APP.read_dropped()

    def test_a_reader_that_changes_a_kept_pin_is_reported(self):
        """Changing a value inside a record a reader was handed - here the author's name - is reported with the
        line it belongs to (its first 80 characters); the run is then dropped so the tear-down's own audit sees a clean one."""
        ps.APP.read_pins()[0][0].record["author"]["name"] = "someone else"
        first_line = ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines()[0]
        try:
            self.assertEqual(kept_lines_changed(), [first_line[:80]])
        finally:
            fresh_runtime()

    def test_a_reader_that_changes_a_kept_trash_entry_is_reported(self):
        """The Trash's kept lines are audited like the live ones."""
        ps.APP.read_dropped()[0][0].record["author"]["name"] = "someone else"
        try:
            self.assertEqual(len(kept_lines_changed()), 1)
        finally:
            fresh_runtime()

    def test_changing_the_outer_record_of_a_read_is_not_a_change(self):
        """`record` is a new dict at every call: a caller that adds to or rewrites its top level changed nothing
        that is kept."""
        row = ps.APP.read_pins()[0][0].record
        row["note"] = "mine"
        row["extra"] = [1]
        self.assertEqual(kept_lines_changed(), [])

    def test_reading_every_way_changes_nothing(self):
        """The list, one pin, pins.md, the counts, the people, the Trash list, an edit's target and a pick's
        overlaps leave every kept value equal to a fresh parse of its line."""
        app = ps.APP
        app.pin_listing.list_payload(True)
        app.pin_listing.list_payload(False, app.docs[0].key)
        app.pin_listing.pin_payload(self.first)
        app.pin_markdown.current_text("http://127.0.0.1:1")
        app.assembly.pins.counts.state_counts()
        app.assembly.pins.counts.counts_by_document({app.docs[0].key})
        app.pin_listing.dropped_payload()
        app.overlaps_for_range(str(self.main), 4, 9)
        add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "third"}, dict(LOCAL_ACTOR))
        self.assertGreater(len(app.RT.pin_lines.live.held()), 0)
        self.assertGreater(len(app.RT.pin_lines.dropped.held()), 0)
        self.assertEqual(kept_lines_changed(), [])


class TheTearDownRunsTheAudit(unittest.TestCase):
    """A test on Base ends by auditing the run's kept lines, so the test that exercised a changing reader fails."""

    def outcome(self, body) -> unittest.TestResult:
        """The result of one test on Base whose body is body(test), run here and now."""

        class Case(Base):
            """A one-test case on the shared base."""

            def runTest(self):
                """Run the body handed to outcome()."""
                body(self)

        result = unittest.TestResult()
        Case().run(result)
        return result

    def test_a_test_whose_reads_changed_a_kept_pin_fails_in_tear_down(self):
        """A test that changes a value inside a pin it read fails, in its tear-down, naming the rule."""

        def body(test):
            """Add a pin, read it and change its author's name in place."""
            test.add()
            ps.APP.read_pins()[0][0].record["author"]["name"] = "someone else"

        result = self.outcome(body)
        self.assertEqual((len(result.failures), len(result.errors)), (1, 0))
        self.assertIn("a reader changed a pin the run keeps", result.failures[0][1])

    def test_a_test_that_only_reads_passes(self):
        """A test that reads the pins and changes nothing passes its tear-down."""

        def body(test):
            """Add a pin and read it twice."""
            test.add()
            ps.APP.read_pins()
            ps.APP.pin_listing.list_payload(True)

        result = self.outcome(body)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 1)
