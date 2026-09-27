"""limn.people - people.json's record check, stored text and write, and the @-tag candidates, with no server.

The HTTP side (people recorded on a visit, GET /api/people, roles) is covered in test_server.py and test_access.py;
this file pins the module's own contracts and its import boundary.

Run: uv run pytest -q tests/test_people.py
"""

import ast
import io
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from limn import people
from limn.access import LOCAL_ACTOR
from limn.people import (
    PeopleBook,
    PeopleUnreadable,
    UnreadableWarning,
    is_actor,
    known_people,
    load_people,
    people_text,
    record_person,
    valid_people,
)

from helpers import Base, add_pin, ps, req, split_resp

PEOPLE_PY = Path(people.__file__)


def agent(a):
    """The agent rule the server passes in: 'local' or an API-token login."""
    return a.get("login", "local") == "local" or str(a.get("login")).startswith("agent:")


class ModuleBoundary(unittest.TestCase):
    """people.py sits below the server: the state dir, lock, memo, clock and agent rule come in as arguments."""

    def test_imports_only_the_standard_library_and_limn_files(self):
        """No server, HTTP, subprocess or clock import; of limn only limn.files."""
        tree = ast.parse(PEOPLE_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual({m for m in modules if m.startswith("limn")}, {"limn.files"})
        self.assertFalse({"http", "http.server", "urllib", "subprocess", "time"} & modules)

    def test_reads_no_server_global(self):
        """No run-argument object or server helper is named in the module."""
        tree = ast.parse(PEOPLE_PY.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"C", "PEOPLE_LOCK", "_PEOPLE_SEEN", "read_pins", "DEFAULT_ROLE", "LOCAL_ACTOR"})


class Records(unittest.TestCase):
    """valid_people(), is_actor() and people_text(): what a people.json entry may be and how it is stored."""

    def test_only_entries_with_a_login_and_string_fields_are_kept(self):
        """Bad entries and documents of another shape are dropped, never raised."""
        d = {
            "people": [
                {"login": "a", "name": "A"},
                {"login": ""},
                {"name": "x"},
                {"login": "b", "name": 3},
                "junk",
                {"login": "c", "pic": None},
            ]
        }
        self.assertEqual([x["login"] for x in valid_people(d)], ["a", "c"])
        self.assertEqual(valid_people([1]), [])
        self.assertEqual(valid_people({"people": None}), [])
        self.assertFalse(is_actor({"login": "a", "pic": 1}))
        self.assertFalse(is_actor("a"))

    def test_stored_text_is_sorted_versioned_and_keeps_non_ascii(self):
        """{"version": 1, "people": [...]} by login, one-space indent, newline at the end."""
        text = people_text([{"login": "b", "name": "서준"}, {"login": "a", "name": "A"}])
        self.assertEqual(
            text,
            json.dumps(
                {"version": 1, "people": [{"login": "a", "name": "A"}, {"login": "b", "name": "서준"}]},
                ensure_ascii=False,
                indent=1,
            )
            + "\n",
        )

    def test_a_missing_file_reads_as_nobody(self):
        """load_people() of a file that does not exist is [] - a new instance has recorded no one yet."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_people(Path(tmp) / "people.json"), [])

    def test_a_file_that_exists_but_cannot_be_used_is_unreadable_not_empty(self):
        """Truncated or invalid JSON, bytes that are not UTF-8, an empty file, a document of another shape and a
        directory are PeopleUnreadable naming the file - never [], which would read as "nobody has a role"."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "people.json"
            for raw in (b'{"version": 1, "peo', b"{", b"\xff\xfe", b"", b"[]", b'{"version": 1}', b'{"people": {}}'):
                p.write_bytes(raw)
                got = load_people(p)
                self.assertIsInstance(got, PeopleUnreadable, raw)
                self.assertIn(str(p), got.reason, raw)
            p.unlink()
            p.mkdir()
            self.assertIsInstance(load_people(p), PeopleUnreadable)


class Known(unittest.TestCase):
    """known_people(): the @-tag candidates from people.json rows and the pins."""

    def test_people_and_pin_actors_without_agents(self):
        """people.json first (with last_seen), then author, *_by and thread posters; agents and bad actors skipped."""
        rows = [{"login": "a@example.com", "name": "A", "last_seen": "t1"}]
        pins = [
            {
                "author": {"login": "b@example.com", "name": "B", "pic": "p"},
                "closed_by": {"login": "local", "name": "로컬"},
                "done_by": {"login": "agent:bot", "name": "bot"},
                "note": {"login": "n@example.com"},
                "thread": [{"by": {"login": "a@example.com", "name": "Other", "pic": "q"}}, {"by": {"login": ""}}],
            }
        ]
        self.assertEqual(
            known_people(rows, pins, agent),
            {
                "a@example.com": {"login": "a@example.com", "name": "A", "last_seen": "t1", "pic": "q"},
                "b@example.com": {"login": "b@example.com", "name": "B", "pic": "p"},
            },
        )

    def test_a_name_falls_back_to_the_login(self):
        """An actor without a name is shown by login."""
        self.assertEqual(
            known_people([], [{"author": {"login": "z@example.com"}}], agent),
            {"z@example.com": {"login": "z@example.com", "name": "z@example.com"}},
        )


class Write(unittest.TestCase):
    """record_person(): when people.json is written, and what an entry keeps."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = PeopleBook(Path(self.tmp.name), threading.Lock(), {}, UnreadableWarning())

    def rows(self):
        """people.json as stored now."""
        return load_people(self.book.path)

    def test_a_first_visit_writes_a_private_entry_without_a_role(self):
        """first_seen/last_seen are the local time of now; no role field for the default role; mode 0600."""
        self.assertTrue(record_person(self.book, {"login": "a@example.com", "name": "A"}, 0.0, None, "editor"))
        (entry,) = self.rows()
        self.assertEqual(set(entry), {"login", "name", "first_seen", "last_seen"})
        self.assertEqual(stat.S_IMODE(os.stat(self.book.path).st_mode), 0o600)

    def test_a_given_role_is_kept_only_when_it_is_not_the_default(self):
        """The local owner is recorded as owner; 'editor' is not written."""
        record_person(self.book, {"login": "o@example.com", "name": "O"}, 0.0, "owner", "editor")
        record_person(self.book, {"login": "e@example.com", "name": "E"}, 0.0, "editor", "editor")
        self.assertEqual(
            {x["login"]: x.get("role") for x in self.rows()}, {"o@example.com": "owner", "e@example.com": None}
        )

    def test_an_unchanged_person_is_not_rewritten_within_the_touch_interval(self):
        """Same name and pic within PEOPLE_TOUCH_S: no write; a name change or a stale last_seen: a write."""
        actor = {"login": "a@example.com", "name": "A"}
        record_person(self.book, actor, 100.0, None, "editor")
        self.assertFalse(record_person(self.book, actor, 100.0 + people.PEOPLE_TOUCH_S - 1, None, "editor"))
        self.assertTrue(
            record_person(self.book, {"login": "a@example.com", "name": "A2", "pic": "p"}, 101.0, None, "editor")
        )
        self.assertEqual((self.rows()[0]["name"], self.rows()[0]["pic"]), ("A2", "p"))
        self.assertTrue(
            record_person(
                self.book,
                {"login": "a@example.com", "name": "A2", "pic": "p"},
                101.0 + people.PEOPLE_TOUCH_S,
                None,
                "editor",
            )
        )

    def test_a_member_role_set_meanwhile_is_kept(self):
        """The file is re-read under the lock, so a role `limn member` wrote survives the visit."""
        self.book.path.write_text(
            people_text([{"login": "a@example.com", "name": "A", "role": "viewer"}]), encoding="utf-8"
        )
        record_person(self.book, {"login": "a@example.com", "name": "A"}, 0.0, "owner", "editor")
        self.assertEqual(self.rows()[0]["role"], "viewer")

    def test_a_failed_write_returns_false_and_is_not_memoised(self):
        """people.json that cannot be replaced (a directory) is a warning and False; the next call tries again."""
        self.book.path.mkdir()
        self.assertFalse(record_person(self.book, {"login": "a@example.com", "name": "A"}, 0.0, None, "editor"))
        self.assertEqual(self.book.seen, {})


class Unreadable(unittest.TestCase):
    """record_person() never rewrites a people.json it cannot read: that would erase every role in it, the owner's too."""

    def setUp(self):
        """A state folder whose people.json held an owner and is now truncated."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = PeopleBook(Path(self.tmp.name), threading.Lock(), {}, UnreadableWarning())
        self.good = people_text([{"login": "o@example.com", "name": "O", "role": "owner"}]).encode()
        self.book.path.write_bytes(self.good[:-9])

    def test_a_visit_writes_nothing_and_warns_once(self):
        """Every visit returns False and leaves the bytes as they were; only the first prints the warning, and
        nothing is memoised, so the visit is recorded next to the owner once the file reads again."""
        broken = self.book.path.read_bytes()
        with mock.patch("sys.stderr", io.StringIO()) as err:
            for now in (0.0, 1.0, 2.0 + people.PEOPLE_TOUCH_S):
                self.assertFalse(record_person(self.book, {"login": "a@example.com", "name": "A"}, now, None, "editor"))
        self.assertEqual(self.book.path.read_bytes(), broken)
        self.assertEqual(err.getvalue().count("warning:"), 1, err.getvalue())
        self.assertIn(str(self.book.path), err.getvalue())
        self.assertEqual(self.book.seen, {})
        self.book.path.write_bytes(self.good)
        self.assertTrue(record_person(self.book, {"login": "a@example.com", "name": "A"}, 3.0, None, "editor"))
        rows = load_people(self.book.path)
        self.assertEqual(
            [(x["login"], x.get("role")) for x in rows], [("a@example.com", None), ("o@example.com", "owner")]
        )

    def test_a_new_breakage_after_a_good_read_warns_again(self):
        """The warning is once per breakage, not once per process: a good read in between re-arms it."""
        warning, path = self.book.warning, self.book.path
        with mock.patch("sys.stderr", io.StringIO()) as err:
            warning.note(path, load_people(path))
            warning.note(path, load_people(path))
            path.write_bytes(self.good)
            warning.note(path, load_people(path))
            path.write_bytes(b"{")
            warning.note(path, load_people(path))
        self.assertEqual(err.getvalue().count("warning:"), 2, err.getvalue())


class PeopleOnTheServer(Base):
    """people.json through server.py: only people are recorded, at most every ten minutes unless they changed, written
    atomically; opening the viewer records the person, and GET /api/people adds the pins' actors."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    W = {"login": "wendy@example.com", "name": "Wendy Kim"}

    HS = {"Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob Park"}

    HW = {"Tailscale-User-Login": "wendy@example.com", "Tailscale-User-Name": "Wendy Kim"}

    def setUp(self):
        super().setUp()
        ps._PEOPLE_SEEN.clear()
        ps._EVENTS_CACHE.clear()

    def test_people_json_records_humans_only_and_throttles(self):
        self.assertFalse(ps.record_person(dict(LOCAL_ACTOR)))
        self.assertFalse(ps.C.people_file.exists())
        self.assertTrue(ps.record_person(dict(self.S, pic="https://p/s.png"), now=1000))
        # same value within 10 minutes — not written
        self.assertFalse(ps.record_person(dict(self.S, pic="https://p/s.png"), now=1100))
        self.assertTrue(ps.record_person(dict(self.S, name="Bob P."), now=1101))  # written when the name changes
        self.assertTrue(ps.record_person(dict(self.W), now=2000))
        d = json.loads(ps.C.people_file.read_text(encoding="utf-8"))
        self.assertEqual(d["version"], 1)
        self.assertEqual([p["login"] for p in d["people"]], [self.S["login"], self.W["login"]])
        s = d["people"][0]
        self.assertEqual((s["name"], s["pic"]), ("Bob P.", "https://p/s.png"))
        self.assertTrue(s["first_seen"] <= s["last_seen"])

    def test_people_json_write_is_atomic(self):
        ps.record_person(dict(self.S), now=1000)
        before = ps.C.people_file.read_bytes()
        with mock.patch.object(os, "replace", side_effect=OSError("disk full")):
            self.assertFalse(ps.record_person(dict(self.W), now=2000))
        self.assertEqual(ps.C.people_file.read_bytes(), before)  # the old file is unchanged (no half-written file)
        with mock.patch.object(os, "replace", side_effect=OSError("disk full")):
            ps.emit_events([{"type": "mention", "pin": 1, "to": ["x"]}])
        self.assertFalse(ps.C.events_file.exists())

    def test_viewer_open_records_person_and_people_api_merges_pin_actors(self):
        self.talk(req("GET", "/", headers=self.HW))
        self.talk(req("GET", "/api/meta?light=1", headers=self.HS))  # polling doesn't count
        self.assertEqual([p["login"] for p in ps.load_people()], [self.W["login"]])
        add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "x"}, dict(self.S)).record["id"]
        code, _, raw = split_resp(self.talk(req("GET", "/api/people", headers=self.HW)))
        d = json.loads(raw)
        self.assertEqual(sorted(p["login"] for p in d["people"]), sorted([self.S["login"], self.W["login"]]))
        self.assertEqual(d["me"]["login"], self.W["login"])
        self.assertNotIn("local", [p["login"] for p in d["people"]])


if __name__ == "__main__":
    unittest.main()
