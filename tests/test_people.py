"""limn.people - people.json's record check, stored text and write, and the @-tag candidates, with no server.

The HTTP side (people recorded on a visit, GET /api/people, roles) is covered in test_server.py and test_access.py;
this file pins the module's own contracts and its import boundary.

Run: uv run pytest -q tests/test_people.py
"""

import ast
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path

from limn import people
from limn.people import PeopleBook, is_actor, known_people, load_people, people_text, record_person, valid_people

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

    def test_a_missing_or_broken_file_reads_as_nobody(self):
        """load_people() of a missing or non-JSON file is []."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "people.json"
            self.assertEqual(load_people(p), [])
            p.write_text("{", encoding="utf-8")
            self.assertEqual(load_people(p), [])


class Known(unittest.TestCase):
    """known_people(): the @-tag candidates from people.json rows and the pins."""

    def test_people_and_pin_actors_without_agents(self):
        """people.json first (with last_seen), then author, *_by and thread posters; agents and bad actors skipped."""
        rows = [{"login": "a@x", "name": "A", "last_seen": "t1"}]
        pins = [
            {
                "author": {"login": "b@x", "name": "B", "pic": "p"},
                "closed_by": {"login": "local", "name": "로컬"},
                "done_by": {"login": "agent:bot", "name": "bot"},
                "note": {"login": "n@x"},
                "thread": [{"by": {"login": "a@x", "name": "Other", "pic": "q"}}, {"by": {"login": ""}}],
            }
        ]
        self.assertEqual(
            known_people(rows, pins, agent),
            {
                "a@x": {"login": "a@x", "name": "A", "last_seen": "t1", "pic": "q"},
                "b@x": {"login": "b@x", "name": "B", "pic": "p"},
            },
        )

    def test_a_name_falls_back_to_the_login(self):
        """An actor without a name is shown by login."""
        self.assertEqual(
            known_people([], [{"author": {"login": "z@x"}}], agent), {"z@x": {"login": "z@x", "name": "z@x"}}
        )


class Write(unittest.TestCase):
    """record_person(): when people.json is written, and what an entry keeps."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = PeopleBook(Path(self.tmp.name), threading.Lock(), {})

    def rows(self):
        """people.json as stored now."""
        return load_people(self.book.path)

    def test_a_first_visit_writes_a_private_entry_without_a_role(self):
        """first_seen/last_seen are the local time of now; no role field for the default role; mode 0600."""
        self.assertTrue(record_person(self.book, {"login": "a@x", "name": "A"}, 0.0, None, "editor"))
        (entry,) = self.rows()
        self.assertEqual(set(entry), {"login", "name", "first_seen", "last_seen"})
        self.assertEqual(stat.S_IMODE(os.stat(self.book.path).st_mode), 0o600)

    def test_a_given_role_is_kept_only_when_it_is_not_the_default(self):
        """The local owner is recorded as owner; 'editor' is not written."""
        record_person(self.book, {"login": "o@x", "name": "O"}, 0.0, "owner", "editor")
        record_person(self.book, {"login": "e@x", "name": "E"}, 0.0, "editor", "editor")
        self.assertEqual({x["login"]: x.get("role") for x in self.rows()}, {"o@x": "owner", "e@x": None})

    def test_an_unchanged_person_is_not_rewritten_within_the_touch_interval(self):
        """Same name and pic within PEOPLE_TOUCH_S: no write; a name change or a stale last_seen: a write."""
        actor = {"login": "a@x", "name": "A"}
        record_person(self.book, actor, 100.0, None, "editor")
        self.assertFalse(record_person(self.book, actor, 100.0 + people.PEOPLE_TOUCH_S - 1, None, "editor"))
        self.assertTrue(record_person(self.book, {"login": "a@x", "name": "A2", "pic": "p"}, 101.0, None, "editor"))
        self.assertEqual((self.rows()[0]["name"], self.rows()[0]["pic"]), ("A2", "p"))
        self.assertTrue(
            record_person(
                self.book, {"login": "a@x", "name": "A2", "pic": "p"}, 101.0 + people.PEOPLE_TOUCH_S, None, "editor"
            )
        )

    def test_a_member_role_set_meanwhile_is_kept(self):
        """The file is re-read under the lock, so a role `limn member` wrote survives the visit."""
        self.book.path.write_text(people_text([{"login": "a@x", "name": "A", "role": "viewer"}]), encoding="utf-8")
        record_person(self.book, {"login": "a@x", "name": "A"}, 0.0, "owner", "editor")
        self.assertEqual(self.rows()[0]["role"], "viewer")

    def test_a_failed_write_returns_false_and_is_not_memoised(self):
        """people.json that cannot be replaced (a directory) is a warning and False; the next call tries again."""
        self.book.path.mkdir()
        self.assertFalse(record_person(self.book, {"login": "a@x", "name": "A"}, 0.0, None, "editor"))
        self.assertEqual(self.book.seen, {})


if __name__ == "__main__":
    unittest.main()
