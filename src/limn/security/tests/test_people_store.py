"""The people store's member edits (pure) and its one write transaction."""

import fcntl
import json
import stat
import tempfile
import unittest
from pathlib import Path

from limn.security.people import (
    LastOwner,
    MemberChange,
    add_member,
    people_transaction,
    remove_member,
    set_member_role,
)


def rows_of(*pairs):
    """people.json rows from (login, role) pairs; a role of None leaves the field out."""
    return [dict({"login": login, "name": login}, **({} if role is None else {"role": role})) for login, role in pairs]


class PureMemberEdits(unittest.TestCase):
    """add_member, set_member_role, remove_member edit the rows list in place and take no lock."""

    def test_add_appends_with_role_and_name(self):
        rows = rows_of(("bob@example.com", "owner"))
        entry, change = add_member(rows, "alice@example.com", "editor", None)
        self.assertEqual(entry, {"login": "alice@example.com", "name": "alice", "role": "editor"})
        self.assertEqual(rows[-1], entry)
        self.assertEqual(change, MemberChange("member_added", {"login": "alice@example.com", "role": "editor"}))
        entry, _ = add_member(rows, "carol@example.com", "viewer", "  Carol   C  ")
        self.assertEqual(entry["name"], "Carol C")

    def test_add_rejects_existing_login(self):
        rows = rows_of(("alice@example.com", "viewer"))
        with self.assertRaisesRegex(ValueError, "already a member"):
            add_member(rows, "alice@example.com", "editor", None)
        self.assertEqual(len(rows), 1)

    def test_add_rejects_invalid_login_and_role(self):
        rows = []
        with self.assertRaisesRegex(ValueError, "invalid login"):
            add_member(rows, "has space", "editor", None)
        with self.assertRaisesRegex(ValueError, "role must be one of"):
            add_member(rows, "alice@example.com", "boss", None)
        self.assertEqual(rows, [])

    def test_set_role_returns_none_when_absent(self):
        self.assertEqual(set_member_role(rows_of(("a@example.com", "owner")), "b@example.com", "viewer"), (None, None))

    def test_set_role_rejects_unknown_role(self):
        with self.assertRaisesRegex(ValueError, "role must be one of"):
            set_member_role(rows_of(("a@example.com", "editor")), "a@example.com", "boss")

    def test_set_role_changes_and_reports_previous(self):
        rows = rows_of(("a@example.com", None))
        hit, change = set_member_role(rows, "a@example.com", "viewer")
        self.assertEqual(hit["role"], "viewer")
        self.assertEqual(
            change,
            MemberChange("member_role", {"login": "a@example.com", "role": "viewer", "previous_role": "editor"}),
        )

    def test_set_role_same_role_makes_no_change(self):
        rows = rows_of(("a@example.com", "viewer"))
        hit, change = set_member_role(rows, "a@example.com", "viewer")
        self.assertEqual(hit["role"], "viewer")
        self.assertIsNone(change)

    def test_remove_returns_none_when_absent(self):
        self.assertEqual(remove_member(rows_of(("a@example.com", "owner")), "b@example.com"), (None, None))

    def test_remove_reports_previous_role(self):
        rows = rows_of(("a@example.com", "owner"), ("b@example.com", None))
        hit, change = remove_member(rows, "b@example.com")
        self.assertEqual(hit["login"], "b@example.com")
        self.assertEqual(change, MemberChange("member_removed", {"login": "b@example.com", "previous_role": "editor"}))
        self.assertEqual([x["login"] for x in rows], ["a@example.com"])


class LastOwnerRule(unittest.TestCase):
    """An instance never ends up with no owner: both edits raise LastOwner instead of leaving none."""

    def test_remove_last_owner_raises(self):
        rows = rows_of(("a@example.com", "owner"), ("b@example.com", "editor"))
        with self.assertRaises(LastOwner) as got:
            remove_member(rows, "a@example.com")
        self.assertEqual(got.exception.login, "a@example.com")
        self.assertEqual(len(rows), 2)

    def test_demote_last_owner_raises(self):
        rows = rows_of(("a@example.com", "owner"))
        with self.assertRaises(LastOwner):
            set_member_role(rows, "a@example.com", "editor")
        self.assertEqual(rows[0]["role"], "owner")

    def test_keeping_the_owner_role_is_not_a_demotion(self):
        rows = rows_of(("a@example.com", "owner"))
        self.assertIsNone(set_member_role(rows, "a@example.com", "owner")[1])

    def test_remove_one_of_two_owners_is_allowed(self):
        rows = rows_of(("a@example.com", "owner"), ("b@example.com", "owner"))
        remove_member(rows, "a@example.com")
        self.assertEqual([x["login"] for x in rows], ["b@example.com"])

    def test_demote_one_of_two_owners_is_allowed(self):
        rows = rows_of(("a@example.com", "owner"), ("b@example.com", "owner"))
        set_member_role(rows, "a@example.com", "viewer")
        self.assertEqual(rows[0]["role"], "viewer")

    def test_remove_non_owner_is_allowed(self):
        rows = rows_of(("a@example.com", "owner"), ("b@example.com", "viewer"))
        remove_member(rows, "b@example.com")
        self.assertEqual([x["login"] for x in rows], ["a@example.com"])

    def test_replacing_an_owner_means_add_first_then_remove(self):
        rows = rows_of(("a@example.com", "owner"))
        add_member(rows, "b@example.com", "owner", None)
        remove_member(rows, "a@example.com")
        self.assertEqual([x["login"] for x in rows], ["b@example.com"])

    def test_last_owner_can_be_raised_inside_a_context_manager(self):
        """Raising passes through store_lock (a context manager), which sets __traceback__ on the exception."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "people.json").write_text(
                json.dumps({"version": 1, "people": rows_of(("a@example.com", "owner"))}), encoding="utf-8"
            )
            with self.assertRaises(LastOwner):
                people_transaction(Path(tmp), lambda rows: remove_member(rows, "a@example.com"), lambda a, d: None)


class Transaction(unittest.TestCase):
    """people_transaction: one lock, read, step, atomic write, audit lines in order - or nothing."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"
        self.audited = []

    def audit(self, action, details):
        """The audit sink: records what the transaction reports."""
        self.audited.append((action, details))

    def test_transaction_writes_and_audits_in_order(self):
        def step(rows):
            _, first = add_member(rows, "b@example.com", "editor", None)
            _, second = add_member(rows, "a@example.com", "owner", "Ann")
            return "done", [first, second]

        self.assertEqual(people_transaction(self.state, step, self.audit), "done")
        path = self.state / "people.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([x["login"] for x in doc["people"]], ["a@example.com", "b@example.com"])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(
            self.audited,
            [
                ("member_added", {"login": "b@example.com", "role": "editor"}),
                ("member_added", {"login": "a@example.com", "role": "owner"}),
            ],
        )

    def test_transaction_without_changes_audits_nothing(self):
        people_transaction(self.state, lambda rows: (None, []), self.audit)
        self.assertEqual(self.audited, [])

    def test_transaction_refuses_unusable_people_file(self):
        self.state.mkdir()
        path = self.state / "people.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            people_transaction(self.state, lambda rows: (None, []), self.audit)
        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")
        self.assertEqual(self.audited, [])

    def test_a_raising_step_writes_and_audits_nothing(self):
        self.state.mkdir()
        path = self.state / "people.json"
        before = json.dumps({"version": 1, "people": rows_of(("a@example.com", "owner"))})
        path.write_text(before, encoding="utf-8")
        with self.assertRaises(LastOwner):
            people_transaction(self.state, lambda rows: remove_member(rows, "a@example.com"), self.audit)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertEqual(self.audited, [])

    def test_transaction_holds_the_lock_while_the_step_runs(self):
        """store_lock does not nest: a second acquisition in the same process would block forever. So the step must
        find the lock already held - a non-blocking flock from another descriptor is refused - and never take it."""
        held = []

        def step(rows):
            with open(self.state / ".people.lock", "a+b") as fh:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    held.append(True)
                else:
                    held.append(False)
            return None, []

        people_transaction(self.state, step, self.audit)
        self.assertEqual(held, [True])

    def test_transaction_releases_the_lock_afterwards(self):
        people_transaction(self.state, lambda rows: (None, []), self.audit)
        with open(self.state / ".people.lock", "a+b") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_audit_runs_while_the_lock_is_held(self):
        held = []

        def audit(action, details):
            with open(self.state / ".people.lock", "a+b") as fh:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    held.append(True)
                else:
                    held.append(False)

        people_transaction(
            self.state, lambda rows: (None, [add_member(rows, "a@example.com", "owner", None)[1]]), audit
        )
        self.assertEqual(held, [True])


if __name__ == "__main__":
    unittest.main()
