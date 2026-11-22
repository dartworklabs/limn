"""The transition the owner presses: write the member list and the access flag as one target state under one lock.

docs/superpowers/plans/2026-11-22-viewer-access-management.md Task 4. The state-folder tests run on a temporary
directory; the last class drives the real request handler to show what a transition does to who gets in.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from limn.security.access import LOCAL_ACTOR
from limn.security.access_service import (
    DuplicateTarget,
    LocksOutOwner,
    ManagedResult,
    RoleNotSettable,
    TargetMember,
    add_one,
    apply_managed,
    current_admitted,
    remove_one,
    set_one_role,
)
from limn.security.access_store import read_access
from limn.security.people_store import LastOwner
from limn.security.values import role_value

from helpers import ps
from helpers_access import ALICE, BOB, CAROL, AccessBase

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"

OWNER = {"login": "owner@example.com", "name": "Owner"}
NOW = 1_800_000_000.0


def row(login, role=None):
    """One people.json row; a role of None leaves the field out (the default role)."""
    return dict({"login": login, "name": login.split("@")[0]}, **({} if role is None else {"role": role}))


def target(login, role="editor"):
    """One checked line of the transition screen."""
    return TargetMember(login, role)


def shown(rows):
    """The targets a screen that lists these rows unchanged would send: each viewer and editor row with its role. Owner
    and agent rows are not on the screen's list (the transition keeps them whatever it sends)."""
    return [
        target(r["login"], role_value(r.get("role"))) for r in rows if role_value(r.get("role")) in ("viewer", "editor")
    ]


class StateBase(unittest.TestCase):
    """A temporary state folder with the audit sink and the readers the transition tests share."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"
        self.tmp = Path(tmp.name)
        self.audited = []

    def audit(self, action, details):
        """The audit sink: records what the transaction reports."""
        self.audited.append((action, details))

    def seed(self, *rows):
        """Write people.json with these rows."""
        self.state.mkdir(exist_ok=True)
        (self.state / "people.json").write_text(json.dumps({"version": 1, "people": list(rows)}), encoding="utf-8")

    def roles(self):
        """{login: role field or None} of people.json now."""
        doc = json.loads((self.state / "people.json").read_text(encoding="utf-8"))
        return {x["login"]: x.get("role") for x in doc["people"]}

    def files(self):
        """The bytes of people.json and access.json now, None for a file that is not there."""
        return tuple(
            p.read_bytes() if p.exists() else None for p in (self.state / "people.json", self.state / "access.json")
        )

    def apply(self, targets, managed=True, by=OWNER):
        """apply_managed on this state as the owner presses it."""
        return apply_managed(self.state, targets, by, managed, NOW, self.audit)


class CurrentAdmitted(unittest.TestCase):
    """The screen's starting list: who gets in today under the run's --allow and --members-only."""

    ROWS = [row("b@example.com", "viewer"), row("a@example.com")]

    def test_members_only_admits_allow_and_members(self):
        got = current_admitted(frozenset({"z@example.com"}), True, self.ROWS)
        self.assertEqual(got, ("a@example.com", "b@example.com", "z@example.com"))

    def test_allow_alone_admits_only_allow(self):
        self.assertEqual(current_admitted(frozenset({"z@example.com"}), False, self.ROWS), ("z@example.com",))

    def test_an_open_instance_admits_everyone_it_has_seen(self):
        self.assertEqual(current_admitted(frozenset(), False, self.ROWS), ("a@example.com", "b@example.com"))

    def test_an_allow_login_nobody_could_hold_is_left_out(self):
        got = current_admitted(frozenset({"has space", "local"}), True, [])
        self.assertEqual(got, ())


class Transition(StateBase):
    """apply_managed: people.json is made to match the target list, then the flag is written."""

    def test_default_target_is_a_no_op(self):
        rows = [row("owner@example.com", "owner"), row("a@example.com"), row("b@example.com", "viewer")]
        rows.append(row("ci@example.com", "agent"))
        self.seed(*rows)
        admitted = current_admitted(frozenset(), True, rows)
        self.assertEqual(len(admitted), 4)  # the owner and the agent are admitted today as well
        result = self.apply([t for t in shown(rows) if t.login in admitted])
        self.assertEqual(result, ManagedResult((), (), (), True))
        self.assertEqual(self.audited, [])
        self.assertEqual(self.roles()["a@example.com"], None)  # a row with no role field keeps it

    def test_allow_login_without_row_gets_an_editor_row(self):
        self.seed(row("owner@example.com", "owner"))
        result = self.apply([target("carol@example.com")])
        self.assertEqual(result.added, ("carol@example.com",))
        self.assertEqual(self.roles()["carol@example.com"], "editor")
        self.assertEqual(self.audited, [("member_added", {"login": "carol@example.com", "role": "editor"})])

    def test_unchecked_row_is_removed(self):
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        result = self.apply([])
        self.assertEqual(result.removed, ("b@example.com",))
        self.assertNotIn("b@example.com", self.roles())
        self.assertEqual(self.audited, [("member_removed", {"login": "b@example.com", "previous_role": "viewer"})])

    def test_a_changed_role_is_written_and_audited(self):
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        result = self.apply([target("b@example.com", "editor")])
        self.assertEqual(result.changed, ("b@example.com",))
        self.assertEqual(self.roles()["b@example.com"], "editor")
        self.assertEqual(
            self.audited,
            [("member_role", {"login": "b@example.com", "role": "editor", "previous_role": "viewer"})],
        )

    def test_owner_and_agent_rows_are_preserved_when_absent_from_targets(self):
        self.seed(
            row("owner@example.com", "owner"),
            row("second@example.com", "owner"),
            row("ci@example.com", "agent"),
            row("b@example.com", "viewer"),
        )
        result = self.apply([])
        self.assertEqual(result.removed, ("b@example.com",))
        self.assertEqual(
            self.roles(), {"owner@example.com": "owner", "second@example.com": "owner", "ci@example.com": "agent"}
        )

    def test_people_is_written_before_access(self):
        """If the flag cannot be written the member changes stay and the instance is still not managed."""
        self.seed(row("owner@example.com", "owner"))
        targets = [target("carol@example.com")]
        with (
            mock.patch("limn.security.access_service.write_access", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            self.apply(targets)
        self.assertEqual(self.roles()["carol@example.com"], "editor")
        self.assertEqual(read_access(self.state / "access.json").managed, "not-managed")
        self.assertEqual(self.audited, [("member_added", {"login": "carol@example.com", "role": "editor"})])

    def test_applying_twice_is_idempotent(self):
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        targets = [target("carol@example.com"), target("d@example.com", "viewer")]
        first = self.apply(targets)
        people_after_first = (self.state / "people.json").read_bytes()
        second = self.apply(targets)
        self.assertEqual((first.added, first.removed), (("carol@example.com", "d@example.com"), ("b@example.com",)))
        self.assertEqual(second, ManagedResult((), (), (), True))
        self.assertEqual((self.state / "people.json").read_bytes(), people_after_first)
        self.assertEqual(read_access(self.state / "access.json").managed, "managed")
        self.assertEqual(len(self.audited), 3)  # the second press audits nothing

    def test_first_transition_on_an_empty_state_creates_both_files(self):
        """absent people.json, absent access.json: the owner at the machine presses the button."""
        result = self.apply([target("a@example.com")], by=LOCAL_ACTOR)
        self.assertEqual(result.added, ("a@example.com",))
        flag = read_access(self.state / "access.json")
        self.assertEqual((flag.managed, flag.by, flag.at is not None), ("managed", "local", True))
        for name in ("people.json", "access.json"):
            self.assertEqual(stat.S_IMODE((self.state / name).stat().st_mode), 0o600)

    def test_the_local_owner_needs_no_line_of_its_own(self):
        """The machine's own user is admitted whatever people.json says, so it cannot lock itself out."""
        self.seed(row("owner@example.com", "owner"))
        self.apply([], by=LOCAL_ACTOR)
        self.assertEqual(read_access(self.state / "access.json").managed, "managed")

    def test_turning_management_off_writes_managed_false(self):
        self.seed(row("owner@example.com", "owner"))
        self.apply([])
        result = self.apply([], managed=False)
        self.assertFalse(result.managed)
        self.assertEqual(read_access(self.state / "access.json").managed, "not-managed")

    def test_an_unusable_people_file_is_refused_untouched(self):
        self.state.mkdir()
        (self.state / "people.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.apply([target("a@example.com")], by=LOCAL_ACTOR)
        self.assertEqual(self.files(), (b"{not json", None))


class TransitionRefusals(StateBase):
    """Every refusal is judged before a file is opened: refused means nothing changed."""

    def setUp(self):
        super().setUp()
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        self.before = self.files()

    def refused(self, error, targets, managed=True, by=OWNER):
        """Assert apply refuses with error and leaves both files and the audit log as they were; returns the error."""
        with self.assertRaises(error) as caught:
            self.apply(targets, managed, by)
        self.assertEqual(self.files(), self.before)
        self.assertEqual(self.audited, [])
        return caught.exception

    def test_a_requester_the_targets_would_leave_out_refuses(self):
        """b is an editor-or-viewer row that is not in the targets, so it would be removed and locked out."""
        err = self.refused(LocksOutOwner, [], by={"login": "b@example.com", "name": "B"})
        self.assertEqual(err.login, "b@example.com")

    def test_a_requester_with_no_row_and_no_line_refuses(self):
        self.refused(LocksOutOwner, [target("b@example.com")], by={"login": "stranger@example.com", "name": "S"})

    def test_an_owner_requester_is_kept_by_its_row_and_needs_no_line(self):
        self.apply([target("b@example.com")])
        self.assertEqual(read_access(self.state / "access.json").managed, "managed")
        self.assertEqual(self.roles()["owner@example.com"], "owner")

    def test_a_target_naming_an_owner_or_agent_row_refuses(self):
        """Not ignored: the screen and the file would disagree about what the owner approved."""
        self.seed(row("owner@example.com", "owner"), row("ci@example.com", "agent"), row("b@example.com", "viewer"))
        self.before = self.files()
        for login in ("owner@example.com", "ci@example.com"):
            err = self.refused(RoleNotSettable, [target("b@example.com"), target(login, "editor")])
            self.assertEqual(err.login, login)

    def test_owner_or_agent_role_in_targets_refuses(self):
        for role in ("owner", "agent"):
            err = self.refused(RoleNotSettable, [target("c@example.com", role)])
            self.assertEqual((err.login, err.role), ("c@example.com", role))

    def test_an_unknown_role_in_targets_refuses(self):
        self.refused(RoleNotSettable, [target("c@example.com", "boss")])

    def test_duplicate_login_in_targets_refuses(self):
        err = self.refused(DuplicateTarget, [target("c@example.com"), target("c@example.com", "viewer")])
        self.assertEqual(err.login, "c@example.com")

    def test_an_invalid_login_in_targets_refuses(self):
        self.refused(ValueError, [target("has space")])

    def test_refusals_carry_no_state_path(self):
        for error, targets, by in (
            (LocksOutOwner, [], {"login": "b@example.com"}),
            (RoleNotSettable, [target("c@example.com", "owner")], OWNER),
            (RoleNotSettable, [target("owner@example.com")], OWNER),
            (DuplicateTarget, [target("c@example.com"), target("c@example.com")], OWNER),
        ):
            self.assertNotIn(str(self.tmp), str(self.refused(error, targets, by=by)))

    def test_turning_management_off_may_leave_the_requester_out(self):
        """Only a managed instance can lock someone out; turning it off hands admission back to --allow."""
        self.apply([], managed=False, by={"login": "b@example.com", "name": "B"})
        self.assertEqual(read_access(self.state / "access.json").managed, "not-managed")


class SingleEdits(StateBase):
    """add_one, set_one_role and remove_one: one people_transaction each."""

    def test_add_one_adds_and_audits(self):
        entry = add_one(self.state, "a@example.com", "viewer", "Ann", self.audit)
        self.assertEqual(entry, {"login": "a@example.com", "name": "Ann", "role": "viewer"})
        self.assertEqual(self.roles(), {"a@example.com": "viewer"})
        self.assertEqual(self.audited, [("member_added", {"login": "a@example.com", "role": "viewer"})])

    def test_add_one_refuses_an_existing_member(self):
        self.seed(row("a@example.com"))
        with self.assertRaisesRegex(ValueError, "already a member"):
            add_one(self.state, "a@example.com", "viewer", None, self.audit)
        self.assertEqual(self.audited, [])

    def test_set_one_role_changes_and_audits(self):
        self.seed(row("o@example.com", "owner"), row("a@example.com", "viewer"))
        entry = set_one_role(self.state, "a@example.com", "editor", self.audit)
        self.assertEqual(entry["role"], "editor")
        self.assertEqual(
            self.audited, [("member_role", {"login": "a@example.com", "role": "editor", "previous_role": "viewer"})]
        )

    def test_set_one_role_of_a_stranger_is_none_and_creates_nothing(self):
        self.assertIsNone(set_one_role(self.state, "a@example.com", "editor", self.audit))
        self.assertFalse((self.state / "people.json").exists())

    def test_set_one_role_cannot_demote_the_last_owner(self):
        self.seed(row("o@example.com", "owner"))
        with self.assertRaises(LastOwner):
            set_one_role(self.state, "o@example.com", "viewer", self.audit)
        self.assertEqual(self.roles(), {"o@example.com": "owner"})

    def test_remove_one_removes_and_audits(self):
        self.seed(row("o@example.com", "owner"), row("a@example.com", "viewer"))
        entry = remove_one(self.state, "a@example.com", self.audit)
        self.assertEqual(entry["login"], "a@example.com")
        self.assertEqual(self.audited, [("member_removed", {"login": "a@example.com", "previous_role": "viewer"})])

    def test_remove_one_of_a_stranger_is_none_and_creates_nothing(self):
        self.assertIsNone(remove_one(self.state, "a@example.com", self.audit))
        self.assertFalse((self.state / "people.json").exists())

    def test_remove_one_cannot_remove_the_last_owner(self):
        self.seed(row("o@example.com", "owner"))
        with self.assertRaises(LastOwner):
            remove_one(self.state, "o@example.com", self.audit)
        self.assertEqual(self.roles(), {"o@example.com": "owner"})


def run_member_add(state, login):
    """Start `limn member add` on state as a second process; the caller waits for it."""
    env = dict(os.environ, PYTHONPATH=str(SRC), LIMN_CONFIG_DIR=str(Path(state).parent / "cfg"))
    return subprocess.Popen(
        [sys.executable, "-m", "limn", "member", "add", "--state-dir", str(state), login, "--role", "viewer"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


class TransitionRaces(StateBase):
    """The transition and `limn member` share one lock: they take turns, and the later write sees the earlier."""

    def test_cli_member_add_during_transition_serializes(self):
        """The other process is started while the transition holds the lock (from its audit sink, which runs under
        it). It can only run after the flag is written, so its write lands on the target state and loses nothing."""
        self.seed(row("owner@example.com", "owner"))
        children = []

        def audit(action, details):
            self.audited.append((action, details))
            if not children:
                children.append(run_member_add(self.state, "late@example.com"))

        apply_managed(self.state, [target("carol@example.com")], OWNER, True, NOW, audit)
        out, err = children[0].communicate(timeout=120)
        self.assertEqual(children[0].returncode, 0, err)
        self.assertEqual(
            self.roles(), {"owner@example.com": "owner", "carol@example.com": "editor", "late@example.com": "viewer"}
        )
        self.assertEqual(read_access(self.state / "access.json").managed, "managed")

    def test_a_transition_after_the_cli_write_replaces_it_with_the_target(self):
        """The same two actions the other way round: the later write is the transition, and it reflects its target."""
        self.seed(row("owner@example.com", "owner"))
        child = run_member_add(self.state, "late@example.com")
        out, err = child.communicate(timeout=120)
        self.assertEqual(child.returncode, 0, err)
        self.assertIn("late@example.com", self.roles())
        self.apply([target("carol@example.com")])
        self.assertEqual(self.roles(), {"owner@example.com": "owner", "carol@example.com": "editor"})


class TransitionAdmission(AccessBase):
    """What a transition does to who gets in, on the real request handler: the absent -> managed press, and an
    empty people.json under the flag."""

    def status(self, headers):
        """The status and refusal reason of a GET as this identity."""
        code, d = self.call("GET", "/api/pins", headers=headers)
        return code, (d.get("reason") if isinstance(d, dict) else None)

    def press(self, targets, managed=True):
        """The owner at the machine presses the button on the running instance's state."""
        return apply_managed(ps.APP.C.state, targets, LOCAL_ACTOR, managed, NOW, lambda action, details: None)

    def test_absent_to_managed_admits_exactly_the_checked_people(self):
        self.assertEqual(self.status(CAROL)[0], 200)  # open instance: no flag, no list
        self.assertFalse(ps.APP.C.access_file.exists())
        self.press([target("alice@example.com"), target("bob@example.com", "viewer")])
        self.assertEqual(self.status(ALICE)[0], 200)
        self.assertEqual(self.status(BOB)[0], 200)
        self.assertEqual(self.status(CAROL), (403, "not_member"))

    def test_a_present_but_empty_people_file_under_the_flag_admits_nobody(self):
        self.press([])
        doc = json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))
        self.assertEqual(doc, {"version": 1, "people": []})
        self.assertEqual(self.status(ALICE), (403, "not_member"))
        self.assertEqual(self.status(CAROL), (403, "not_member"))
        self.assertEqual(self.call("GET", "/api/pins")[0], 200)  # the loopback agent is not a header person

    def test_turning_management_off_returns_admission_to_the_run_arguments(self):
        self.press([target("alice@example.com")])
        self.assertEqual(self.status(CAROL), (403, "not_member"))
        self.press([target("alice@example.com")], managed=False)
        self.assertEqual(self.status(CAROL)[0], 200)
