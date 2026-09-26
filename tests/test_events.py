"""limn.events - building notices, picking a poll's events, and the events.jsonl log, driven with no server.

The HTTP flows (every notice type, the /api/meta?ev= cursor) are covered in test_server.py, test_v022.py and
test_v031.py; this file pins the module's own contracts and its import boundary.

Run: uv run pytest -q tests/test_events.py
"""
import ast
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from limn import events
from limn.events import EventLog, events_since, make_event
from limn.pins import render

EVENTS_PY = Path(events.__file__)
ALICE = {"login": "alice@example.com", "name": "Alice Kim", "pic": "https://example.com/a.png"}
BOB = "bob@example.com"


def who(actor):
    """The recorded actor, the shape server.who() gives: login and name only."""
    return {"login": actor.get("login", "local"), "name": actor.get("name", "")}


def doc_of(r):
    """The pin's document key, 'main' when the record has none (like server.pin_doc_key)."""
    return r.get("doc") or "main"


def notice(typ, r, actor, to, **kw):
    """make_event with this file's who/doc_of and the headerless agent's login 'local'."""
    return make_event(typ, r, actor, to, who, doc_of, "local", **kw)


class ModuleBoundary(unittest.TestCase):
    """events.py sits below the server: its path, lock, cache and clock come in as arguments."""

    def test_imports_only_the_standard_library_files_and_the_pure_text_rule(self):
        """No server, HTTP or subprocess import; of limn only limn.files (atomic_write) and limn.pins.render (flat, the
        one-line rule the excerpt shares with pins.md - a pure module)."""
        tree = ast.parse(EVENTS_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual({m for m in modules if m.startswith("limn")}, {"limn.files", "limn.pins.render"})
        self.assertFalse({"http", "http.server", "urllib", "subprocess", "time"} & modules)

    def test_reads_no_server_global(self):
        """No run-argument object or server helper is named in the module."""
        tree = ast.parse(EVENTS_PY.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"C", "DOCS", "EVENTS_LOCK", "now_str", "pin_doc_key", "is_agent", "LOCAL_ACTOR"})


class MakeEvent(unittest.TestCase):
    """make_event(): one notice and whom it goes to."""

    def test_the_actor_and_the_headerless_agent_are_never_recipients(self):
        """Recipients lose the actor, 'local', empty logins and repeats; none left means no notice."""
        r = {"id": 3, "doc": "appx"}
        ev = notice("mention", r, ALICE, [BOB, ALICE["login"], "local", None, BOB])
        self.assertEqual(ev, {"type": "mention", "pin": 3, "doc": "appx", "to": [BOB],
                              "by": {"login": "alice@example.com", "name": "Alice Kim"}})
        self.assertIsNone(notice("mention", r, ALICE, [ALICE["login"], "local"]))
        self.assertIsNone(notice("mention", r, ALICE, None))

    def test_who_and_doc_of_are_asked_only_for_a_notice(self):
        """With nobody to tell, neither lookup runs (a record without a doc never reaches doc_of)."""
        def boom(_):
            """A lookup that must not be called."""
            raise AssertionError("asked")
        self.assertIsNone(make_event("mention", {}, ALICE, [], boom, boom, "local"))

    def test_a_post_gives_msg_and_its_text_the_excerpt(self):
        """msg is the post's id; the excerpt is text when given, else the post's text, whitespace collapsed."""
        r = {"id": 1, "kind_req": "question"}
        ev = notice("replied", r, ALICE, [BOB], msg={"id": 7, "text": "two\n  lines"})
        self.assertEqual((ev["kind_req"], ev["msg"], ev["excerpt"]), ("question", 7, "two lines"))
        ev = notice("mention", r, ALICE, [BOB], msg={"id": 7, "text": "post"}, text="note")
        self.assertEqual(ev["excerpt"], "note")
        self.assertNotIn("excerpt", notice("dropped", r, ALICE, [BOB], text="  "))

    def test_the_excerpt_is_pins_md_one_line_rule_at_140_characters(self):
        """The excerpt is limn.pins.render.flat at EXCERPT_CHARS: whitespace collapsed, cut with an ellipsis."""
        r = {"id": 3, "doc": "main"}
        text = "a  b\n\tc " + "x" * 500
        ev = notice("replied", r, ALICE, [BOB], text=text)
        self.assertEqual(ev["excerpt"], render.flat(text, events.EXCERPT_CHARS))
        self.assertEqual(len(ev["excerpt"]), events.EXCERPT_CHARS)
        self.assertTrue(ev["excerpt"].startswith("a b c x"))


class Since(unittest.TestCase):
    """events_since(): what one person's poll returns."""

    ROWS = [{"seq": 1, "type": "mention", "to": [BOB], "by": {"login": "alice@example.com"}, "doc": "main"},
            {"seq": 2, "type": "cleared", "to": [BOB], "by": {"login": "alice@example.com"}},
            {"seq": 3, "type": "replied", "to": [BOB], "by": {"login": BOB}, "doc": "main"},
            {"seq": 4, "type": "assigned", "to": [BOB, "c"], "by": {"login": "c"}, "doc": "gone"}]

    def test_ev_seq_only_without_a_cursor(self):
        """No cursor: just the latest seq (0 for an empty log)."""
        self.assertEqual(events_since(self.ROWS, BOB, None, {}), {"ev_seq": 4})
        self.assertEqual(events_since([], BOB, None, {}), {"ev_seq": 0})

    def test_notify_types_to_me_not_by_me_after_the_cursor(self):
        """Audit types and my own actions are left out; doc_name falls back to the doc key."""
        got = events_since(self.ROWS, BOB, 0, {"main": "본문"})
        self.assertEqual([(e["seq"], e["doc_name"]) for e in got["events"]], [(1, "본문"), (4, "gone")])
        self.assertEqual([e["seq"] for e in events_since(self.ROWS, BOB, 1, {})["events"]], [4])
        self.assertNotIn("doc_name", self.ROWS[0])                                  # the records are not changed

    def test_nobody_to_notify_gets_an_empty_list(self):
        """me None (local/agent, or no login) gets events: [] with the cursor."""
        self.assertEqual(events_since(self.ROWS, None, 0, {}), {"ev_seq": 4, "events": []})

    def test_at_most_twenty_newest(self):
        """Only the newest EVENTS_SINCE_MAX matching events are returned."""
        rows = [{"seq": i, "type": "mention", "to": [BOB], "by": {"login": "a"}} for i in range(1, 31)]
        self.assertEqual([e["seq"] for e in events_since(rows, BOB, 0, {})["events"]], list(range(11, 31)))


class Log(unittest.TestCase):
    """EventLog: seq numbering, the kept window, the read cache and a failing write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = [1000.0]
        self.log = EventLog(Path(self.tmp.name) / "events.jsonl", threading.Lock(), {}, lambda: self.clock[0],
                            lambda: "2026-09-26 10:00:00")

    def test_seq_continues_from_the_file_and_records_are_stamped(self):
        """Each record gets the next seq, the stamp and the clock (rounded to ms); Nones are skipped."""
        self.log.emit([{"type": "a"}, None])
        self.clock[0] = 1001.23456
        self.log.emit([{"type": "b"}, {"type": "c"}])
        rows, _ = self.log.read()
        self.assertEqual([(e["seq"], e["type"], e["ts"]) for e in rows], [(1, "a", 1000.0), (2, "b", 1001.235),
                                                                          (3, "c", 1001.235)])
        self.assertEqual(rows[0]["at"], "2026-09-26 10:00:00")

    def test_only_the_newest_keep_records_stay_and_seq_still_increases(self):
        """Past keep, the oldest records go; the next seq follows the last one written."""
        for i in range(5):
            self.log.emit([{"type": "t%d" % i}], keep=3)
        rows, _ = self.log.read()
        self.assertEqual([e["seq"] for e in rows], [3, 4, 5])

    def test_an_empty_batch_writes_nothing(self):
        """No notice, no file."""
        self.log.emit([None])
        self.assertFalse(self.log.path.exists())
        self.assertEqual(self.log.read(), ([], None))

    def test_unreadable_lines_are_skipped_and_the_cache_follows_the_file(self):
        """Lines that are not objects with an integer seq are skipped; a changed file is re-read."""
        self.log.path.write_text('not json\n{"seq": true}\n{"seq": 5, "type": "x"}\n[1]\n', encoding="utf-8")
        rows, sig = self.log.read()
        self.assertEqual([e["seq"] for e in rows], [5])
        self.assertIs(self.log.read()[0][0], rows[0])                               # same file: the cached records
        self.log.emit([{"type": "y"}])
        self.assertEqual([e["seq"] for e in self.log.read()[0]], [5, 6])
        self.assertNotEqual(self.log.read()[1], sig)

    @unittest.skipIf(os.geteuid() == 0, "root writes into a read-only directory")
    def test_a_failed_write_only_warns(self):
        """events.jsonl that cannot be written (a read-only state dir) leaves a warning, not an exception."""
        state = self.log.path.parent
        os.chmod(state, 0o500)
        self.addCleanup(os.chmod, state, 0o700)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.log.emit([{"type": "a"}])
        self.assertIn("failed to write events.jsonl", err.getvalue())
        self.assertFalse(self.log.path.exists())

    def test_the_stored_lines_are_compact_json_with_non_ascii_kept(self):
        """One JSON object per line, ensure_ascii off."""
        self.log.emit([{"type": "mention", "excerpt": "한글"}])
        line = self.log.path.read_text(encoding="utf-8")
        self.assertEqual(line, json.dumps(self.log.read()[0][0], ensure_ascii=False) + "\n")
        self.assertIn("한글", line)


if __name__ == "__main__":
    unittest.main()
