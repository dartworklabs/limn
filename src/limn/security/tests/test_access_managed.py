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

from limn.security import access_service
from limn.security.access import LOCAL_ACTOR
from limn.security.access_service import (
    DuplicateTarget,
    FlagNotWritten,
    LocksOutOwner,
    ManagedResult,
    NotManagedNow,
    RoleNotSettable,
    TargetMember,
    add_one,
    add_settable,
    apply_managed,
    current_admitted,
    remove_one,
    remove_settable,
    set_one_role,
    set_settable_role,
    transition_view,
)
from limn.security.access_store import read_access, write_access
from limn.security.people_store import LastOwner
from limn.security.values import role_value

from helpers import ps, set_config
from helpers_access import ALICE, BOB, CAROL, AccessBase

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"

OWNER = {"login": "owner@example.com", "name": "Owner"}
NOW = 1_800_000_000.0


def row(login, role=None):
    """One people.json row; a role of None leaves the field out (the default role)."""
    return dict({"login": login, "name": login.split("@")[0]}, **({} if role is None else {"role": role}))


def flag_line(managed=True, by=OWNER["login"]):
    """The audit line a press records for the flag itself, beside the member_* lines of the rows it changed."""
    return ("access_managed", {"managed": managed, "by": by})


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

    def apply(self, targets, managed=True, by=OWNER, allow=frozenset(), members_only=False, admitted=None):
        """apply_managed on this state as the owner presses it, on an instance run with these arguments. `admitted`
        is what the HTTP boundary decides and passes in: whether admission lets this requester in whatever
        people.json says. Unless a test says otherwise that is true for exactly LOCAL_ACTOR, the machine's own user
        under --auth local."""
        return apply_managed(
            self.state,
            targets,
            by,
            managed,
            NOW,
            self.audit,
            allow=frozenset(allow),
            members_only=members_only,
            admitted_without_people=(by is LOCAL_ACTOR) if admitted is None else admitted,
        )


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


class TransitionScreen(unittest.TestCase):
    """transition_view: what the screen shows, split so that nothing unsendable is offered as a target."""

    ROWS = [
        row("o@example.com", "owner"),
        row("ci@example.com", "agent"),
        row("a@example.com"),
        row("v@example.com", "viewer"),
    ]

    def test_settable_rows_are_only_viewers_and_editors(self):
        view = transition_view(frozenset(), True, self.ROWS)
        self.assertEqual([r["login"] for r in view.settable], ["a@example.com", "v@example.com"])

    def test_fixed_rows_say_whether_they_are_admitted_today(self):
        view = transition_view(frozenset({"o@example.com"}), False, self.ROWS)
        self.assertEqual(
            [(f.row["login"], f.admitted_today) for f in view.fixed],
            [("o@example.com", True), ("ci@example.com", False)],
        )

    def test_on_an_open_instance_every_fixed_row_is_admitted_today(self):
        view = transition_view(frozenset(), False, self.ROWS)
        self.assertTrue(all(f.admitted_today for f in view.fixed))

    def test_an_allow_login_with_no_row_is_a_settable_row(self):
        """The co-author only --allow names: no line in people.json, so the screen must offer a row of its own, with
        the role person_role gives them now (editor). Without it the default press removes their access."""
        rows = [row("o@example.com", "owner"), row("v@example.com", "viewer")]
        view = transition_view(frozenset({"carol@example.com"}), False, rows)
        self.assertEqual(view.admitted_today, ("carol@example.com",))
        self.assertEqual(
            [(r["login"], role_value(r.get("role"))) for r in view.settable],
            [("v@example.com", "viewer"), ("carol@example.com", "editor")],
        )

    def test_members_only_offers_an_allow_login_with_no_row_too(self):
        """--members-only admits --allow beside the members, so the same login gets in today and needs the same row."""
        view = transition_view(frozenset({"carol@example.com"}), True, self.ROWS)
        self.assertIn("carol@example.com", [r["login"] for r in view.settable])

    def test_every_login_admitted_today_is_in_one_of_the_two_lists(self):
        """What the screen reads from - admitted_today, settable, fixed - agrees: nobody who gets in today is missing
        from both columns, under each of the three run configurations."""
        for allow, members_only in (
            (frozenset({"carol@example.com", "o@example.com"}), False),
            (frozenset({"carol@example.com"}), True),
            (frozenset(), False),
        ):
            with self.subTest(allow=sorted(allow), members_only=members_only):
                view = transition_view(allow, members_only, self.ROWS)
                shown_logins = {r["login"] for r in view.settable} | {f.row["login"] for f in view.fixed}
                self.assertEqual(set(view.admitted_today) - shown_logins, set())

    def test_an_allow_login_that_holds_a_fixed_row_is_not_doubled(self):
        """An owner or agent the list names is already a fixed row; it must not appear as a settable one as well."""
        view = transition_view(frozenset({"o@example.com", "ci@example.com"}), False, self.ROWS)
        self.assertEqual([r["login"] for r in view.settable], ["a@example.com", "v@example.com"])
        self.assertEqual([f.row["login"] for f in view.fixed], ["o@example.com", "ci@example.com"])

    def test_an_allow_login_nobody_could_hold_gets_no_row(self):
        """current_admitted leaves such a login out of today's answer, so the screen offers no row for it either."""
        view = transition_view(frozenset({"has space", "local"}), False, self.ROWS)
        self.assertEqual([r["login"] for r in view.settable], ["a@example.com", "v@example.com"])

    def test_sending_the_settable_rows_back_is_never_refused_for_their_names(self):
        """The button is pressable: the view's own settable logins are valid targets."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "state"
        state.mkdir()
        (state / "people.json").write_text(json.dumps({"version": 1, "people": self.ROWS}), encoding="utf-8")
        view = transition_view(frozenset(), True, self.ROWS)
        targets = [target(r["login"], role_value(r.get("role"))) for r in view.settable]
        result = apply_managed(
            state,
            targets,
            LOCAL_ACTOR,
            True,
            NOW,
            lambda a, d: None,
            allow=frozenset(),
            members_only=True,
            admitted_without_people=True,
        )
        self.assertEqual((result.added, result.removed, result.changed), ((), (), ()))


class Transition(StateBase):
    """apply_managed: people.json is made to match the target list, then the flag is written."""

    def test_default_target_is_a_no_op(self):
        """The screen's own settable rows, sent back as they are, change nothing and widen nothing."""
        rows = [row("owner@example.com", "owner"), row("a@example.com"), row("b@example.com", "viewer")]
        rows.append(row("ci@example.com", "agent"))
        self.seed(*rows)
        view = transition_view(frozenset(), True, rows)
        self.assertEqual(len(view.admitted_today), 4)  # the owner and the agent are admitted today as well
        targets = [target(r["login"], role_value(r.get("role"))) for r in view.settable]
        result = self.apply(targets, members_only=True)
        self.assertEqual(result, ManagedResult((), (), (), ("ci@example.com", "owner@example.com"), (), True))
        self.assertEqual(self.audited, [flag_line()])  # no row changed, and the flag itself is still recorded
        self.assertEqual(self.roles()["a@example.com"], None)  # a row with no role field keeps it

    def test_the_default_press_keeps_a_co_author_only_allow_names(self):
        """The regression the design calls a no-op: the screen's own rows, sent back unchanged, keep every login that
        gets in today - including the --allow co-author with no line - so the press removes nobody's access."""
        rows = [row("owner@example.com", "owner"), row("b@example.com", "viewer")]
        self.seed(*rows)
        allow = frozenset({"carol@example.com", "owner@example.com"})
        view = transition_view(allow, False, rows)
        targets = [target(r["login"], role_value(r.get("role"))) for r in view.settable]
        result = self.apply(targets, allow=allow)
        self.assertEqual(result.added, ("carol@example.com",))
        self.assertEqual((result.removed, result.changed), ((), ()))
        self.assertEqual(self.roles()["carol@example.com"], "editor")
        self.assertEqual(result.newly_admitted, ("b@example.com",))  # b holds a row the --allow list does not name
        for login in view.admitted_today:
            self.assertIn(login, self.roles(), login)

    def test_a_press_that_sends_no_list_keeps_that_co_author_too(self):
        """targets=None means "leave the viewer and editor rows as they are". Turning management on that way must mean
        the same as the default press, or the press that sends nothing drops the login the screen would have kept."""
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        result = self.apply(None, allow=frozenset({"carol@example.com", "owner@example.com"}))
        self.assertEqual(result.added, ("carol@example.com",))
        self.assertEqual(
            self.roles(), {"owner@example.com": "owner", "b@example.com": "viewer", "carol@example.com": "editor"}
        )

    def test_a_press_that_sends_no_list_and_turns_off_adds_no_row(self):
        """Off hands admission back to --allow, which already lets that login in: a row for them would change the file
        without changing who gets in, and the screen's off direction sends no member list at all."""
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        result = self.apply(None, managed=False, allow=frozenset({"carol@example.com", "owner@example.com"}))
        self.assertEqual((result.added, result.removed, result.changed), ((), (), ()))
        self.assertEqual(self.roles(), {"owner@example.com": "owner", "b@example.com": "viewer"})

    def test_allow_login_without_row_gets_an_editor_row(self):
        self.seed(row("owner@example.com", "owner"))
        result = self.apply([target("carol@example.com")])
        self.assertEqual(result.added, ("carol@example.com",))
        self.assertEqual(self.roles()["carol@example.com"], "editor")
        self.assertEqual(
            self.audited, [("member_added", {"login": "carol@example.com", "role": "editor"}), flag_line()]
        )

    def test_unchecked_row_is_removed(self):
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        result = self.apply([])
        self.assertEqual(result.removed, ("b@example.com",))
        self.assertNotIn("b@example.com", self.roles())
        self.assertEqual(
            self.audited, [("member_removed", {"login": "b@example.com", "previous_role": "viewer"}), flag_line()]
        )

    def test_a_changed_role_is_written_and_audited(self):
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        result = self.apply([target("b@example.com", "editor")])
        self.assertEqual(result.changed, ("b@example.com",))
        self.assertEqual(self.roles()["b@example.com"], "editor")
        self.assertEqual(
            self.audited,
            [("member_role", {"login": "b@example.com", "role": "editor", "previous_role": "viewer"}), flag_line()],
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

    def test_a_kept_owner_row_that_admission_refuses_today_is_reported_as_newly_admitted(self):
        """--allow alone: people.json grants no entry today. A managed flag lets the kept owner row in, so the press
        is not a no-op even though no row was added, removed or changed."""
        self.seed(row("bob@example.com", "owner"))
        allow = frozenset({"alice@example.com"})
        view = transition_view(allow, False, [row("bob@example.com", "owner")])
        self.assertEqual([(f.row["login"], f.admitted_today) for f in view.fixed], [("bob@example.com", False)])
        self.assertEqual(view.admitted_today, ("alice@example.com",))
        result = self.apply([target("alice@example.com")], by=LOCAL_ACTOR, allow=allow)
        self.assertEqual(result.kept, ("bob@example.com",))
        self.assertEqual(result.newly_admitted, ("bob@example.com",))

    def test_an_admitted_owner_row_is_not_newly_admitted(self):
        self.seed(row("bob@example.com", "owner"))
        result = self.apply([], by=LOCAL_ACTOR, allow=frozenset({"bob@example.com"}))
        self.assertEqual((result.kept, result.newly_admitted), (("bob@example.com",), ()))

    def test_a_press_that_only_narrows_has_no_newly_admitted(self):
        self.seed(row("b@example.com", "viewer"), row("c@example.com"))
        result = self.apply([target("b@example.com", "viewer")], by=LOCAL_ACTOR, members_only=True)
        self.assertEqual(result.newly_admitted, ())

    def test_turning_off_under_allow_names_who_it_lets_in(self):
        """managed -> off hands admission back to --allow, which may list people people.json does not."""
        self.apply([], by=LOCAL_ACTOR)
        result = self.apply([], managed=False, by=LOCAL_ACTOR, allow=frozenset({"z@example.com"}))
        self.assertEqual(result.newly_admitted, ("z@example.com",))

    def test_people_is_written_before_access(self):
        """If the flag cannot be written the member changes stay and the instance is still not managed. The failure is
        FlagNotWritten, not a bare OSError: what stands differs from a press that wrote nothing, so the caller can say
        which half landed. The flag's own audit line follows its write, so it is not recorded."""
        self.seed(row("owner@example.com", "owner"))
        targets = [target("carol@example.com")]
        with (
            mock.patch("limn.security.access_service.write_access", side_effect=OSError("disk full")),
            self.assertRaises(FlagNotWritten) as caught,
        ):
            self.apply(targets)
        self.assertIsInstance(caught.exception.error, OSError)
        self.assertEqual(self.roles()["carol@example.com"], "editor")
        self.assertEqual(read_access(self.state / "access.json").managed, "not-managed")
        self.assertEqual(self.audited, [("member_added", {"login": "carol@example.com", "role": "editor"})])

    def test_a_failed_flag_write_under_members_only_leaves_the_rows_admitting(self):
        """The case the old docstring called "nobody gained entry": under --members-only an unmanaged instance admits
        by people.json, so the row this press wrote admits carol at once although the flag never changed. The failure
        is the one that says the member list stands."""
        self.seed(row("owner@example.com", "owner"))
        with (
            mock.patch("limn.security.access_service.write_access", side_effect=OSError("disk full")),
            self.assertRaises(FlagNotWritten),
        ):
            self.apply([target("carol@example.com")], members_only=True)
        self.assertIn("carol@example.com", self.roles())
        self.assertEqual(read_access(self.state / "access.json").managed, "not-managed")
        stored = [row("owner@example.com", "owner"), row("carol@example.com")]
        self.assertIn("carol@example.com", current_admitted(frozenset(), True, stored))  # in, with the flag still off
        self.assertEqual([a for a, _ in self.audited], ["member_added"])

    def test_a_flag_only_press_records_one_audit_line(self):
        """A press that changes no row still changes access: the line names the value written and who pressed."""
        self.seed(row("owner@example.com", "owner"))
        self.apply(None, managed=True)
        self.assertEqual(self.audited, [flag_line()])
        self.audited.clear()
        self.apply(None, managed=False)
        self.assertEqual(self.audited, [flag_line(False)])

    def test_the_flag_line_follows_the_row_lines(self):
        """The order of audit.jsonl is the order of the changes: the rows, then the flag that governs them."""
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        self.apply([target("carol@example.com")])
        self.assertEqual([a for a, _ in self.audited], ["member_removed", "member_added", "access_managed"])

    def test_applying_twice_is_idempotent(self):
        self.seed(row("owner@example.com", "owner"), row("b@example.com", "viewer"))
        targets = [target("carol@example.com"), target("d@example.com", "viewer")]
        first = self.apply(targets)
        people_after_first = (self.state / "people.json").read_bytes()
        second = self.apply(targets)
        self.assertEqual((first.added, first.removed), (("carol@example.com", "d@example.com"), ("b@example.com",)))
        self.assertEqual((second.added, second.removed, second.changed, second.newly_admitted), ((), (), (), ()))
        self.assertEqual((self.state / "people.json").read_bytes(), people_after_first)
        self.assertEqual(read_access(self.state / "access.json").managed, "managed")
        self.assertEqual(len(self.audited), 5)  # two rows and the flag, then the flag alone

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

    def refused(self, error, targets, managed=True, by=OWNER, **run):
        """Assert apply refuses with error and leaves both files and the audit log as they were; returns the error.
        `run` carries the instance's arguments (allow, members_only, admitted) through to apply."""
        with self.assertRaises(error) as caught:
            self.apply(targets, managed, by, **run)
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

    def test_turning_management_off_with_the_current_list_is_allowed(self):
        """Turning management off is the normal press; the requester keeps their line."""
        self.apply([target("b@example.com")], managed=False, by={"login": "b@example.com", "name": "B"})
        self.assertEqual(read_access(self.state / "access.json").managed, "not-managed")

    def test_turning_management_off_under_members_only_cannot_remove_the_requesters_own_row(self):
        """Unmanaged under --members-only people.json still governs entry, so a removal of the requester's row can
        refuse them next request. The guard is on the state the press produces, not on the flag."""
        with self.assertRaises(LocksOutOwner):
            self.apply([], managed=False, by={"login": "b@example.com", "name": "B"}, members_only=True)
        self.assertEqual(self.files(), self.before)
        self.assertEqual(self.audited, [])

    def test_turning_management_off_on_an_open_instance_may_drop_the_requesters_row(self):
        """With neither --allow nor --members-only an unmanaged instance admits everyone a header identifies, so
        dropping the requester's row cannot shut them out: refusing here refused a press that is safe."""
        self.apply([], managed=False, by={"login": "b@example.com", "name": "B"})
        self.assertEqual(read_access(self.state / "access.json").managed, "not-managed")
        self.assertNotIn("b@example.com", self.roles())

    def test_turning_management_off_refuses_an_owner_the_allow_list_leaves_out(self):
        """The owner row that stops helping: with --allow alone, people.json grants no entry once the flag is off, so
        an owner the list does not name is shut out by their own press. Holding a row is not being admitted."""
        self.seed(row("b@example.com", "owner"))
        self.before = self.files()
        err = self.refused(
            LocksOutOwner, [], managed=False, by={"login": "b@example.com", "name": "B"}, allow={"alice@example.com"}
        )
        self.assertEqual(err.login, "b@example.com")

    def test_turning_management_off_keeps_an_owner_the_allow_list_names(self):
        """The same press with the requester in --allow is the ordinary one and goes through."""
        self.seed(row("b@example.com", "owner"))
        self.apply([], managed=False, by={"login": "b@example.com", "name": "B"}, allow={"b@example.com"})
        self.assertEqual(read_access(self.state / "access.json").managed, "not-managed")

    def test_a_requester_admission_lets_in_regardless_needs_no_row_or_line(self):
        """The machine's own user under --auth local has a login like anyone else's (--local-user
        alice@example.com), and admission lets them in whatever people.json says. Whether that holds is the HTTP
        boundary's to decide and pass in; valid_login() cannot stand for it."""
        self.apply([target("b@example.com")], by={"login": "alice@example.com", "name": "A"}, admitted=True)
        self.assertEqual(read_access(self.state / "access.json").managed, "managed")
        self.assertNotIn("alice@example.com", self.roles())

    def test_the_same_requester_without_that_exemption_is_refused(self):
        """A header-vouched owner with the same login is judged by the state the press makes, and refused."""
        self.refused(LocksOutOwner, [target("b@example.com")], by={"login": "alice@example.com", "name": "A"})

    def test_a_requester_without_a_login_refuses_and_writes_nothing(self):
        for by in ({}, {"name": "x"}, {"login": None}, {"login": ""}):
            self.refused(ValueError, [target("c@example.com")], by=by)
        self.assertFalse((self.state / "access.json").exists())


class OffDirection(unittest.TestCase):
    """off_preview: what the screen shows before the press that turns management off. Turning off widens admission, so
    the owner sees who gets in now, who gets in after and whether they would shut themselves out - before sending."""

    ROWS = [row("o@example.com", "owner"), row("b@example.com", "viewer"), row("c@example.com")]

    def preview(self, allow=frozenset(), members_only=False, rows=None, requester="o@example.com", admitted=False):
        """off_preview on a managed instance run with these arguments."""
        return access_service.off_preview(
            frozenset(allow),
            members_only,
            self.ROWS if rows is None else rows,
            requester,
            admitted_without_people=admitted,
        )

    def test_under_allow_the_two_columns_are_the_members_and_the_list(self):
        """Managed: the member list decides. Off: --allow alone decides, so the members who are not in it lose entry
        and the listed logins with no row gain it."""
        got = self.preview(allow={"o@example.com", "dana@example.com"})
        self.assertEqual(got.admitted_now, ("b@example.com", "c@example.com", "o@example.com"))
        self.assertEqual(got.admitted_after, ("dana@example.com", "o@example.com"))
        self.assertFalse(got.after_everyone)
        self.assertEqual(got.newly_admitted, ("dana@example.com",))
        self.assertEqual(got.no_longer_admitted, ("b@example.com", "c@example.com"))

    def test_an_open_instance_says_after_is_everyone_rather_than_an_empty_list(self):
        """With neither --allow nor --members-only, off admits everyone a header identifies - a set that cannot be
        listed. The flag says so; the empty list must not be read as "nobody"."""
        got = self.preview()
        self.assertTrue(got.after_everyone)
        self.assertEqual(got.admitted_after, ())
        self.assertEqual(got.admitted_now, ("b@example.com", "c@example.com", "o@example.com"))
        self.assertEqual((got.newly_admitted, got.no_longer_admitted), ((), ()))

    def test_members_only_keeps_the_members_and_adds_the_allow_list(self):
        """Off under --members-only still admits by people.json, plus --allow: nobody loses entry."""
        got = self.preview(allow={"dana@example.com"}, members_only=True)
        self.assertEqual(got.no_longer_admitted, ())
        self.assertEqual(got.newly_admitted, ("dana@example.com",))

    def test_a_login_no_person_could_hold_is_in_neither_column(self):
        got = self.preview(allow={"has space", "local", "ok@example.com"})
        self.assertEqual(got.admitted_after, ("ok@example.com",))

    def test_it_says_before_the_press_that_the_owner_would_be_shut_out(self):
        """The owner's own loss: with --allow alone their row grants no entry once the flag is off."""
        self.assertTrue(self.preview(allow={"dana@example.com"}).locks_out_requester)

    def test_an_owner_the_list_names_is_not_shut_out(self):
        self.assertFalse(self.preview(allow={"o@example.com"}).locks_out_requester)

    def test_an_open_instance_shuts_nobody_out(self):
        self.assertFalse(self.preview(allow=frozenset()).locks_out_requester)

    def test_a_requester_admission_lets_in_regardless_is_never_shut_out(self):
        """The machine's own user under --auth local: admission lets them in whatever people.json holds."""
        self.assertFalse(self.preview(allow={"dana@example.com"}, admitted=True).locks_out_requester)

    def test_the_preview_and_the_refusal_never_disagree(self):
        """The one that matters: locks_out_requester is true exactly when the press it previews raises LocksOutOwner.
        Both ask _would_lock_out, so a screen that says "you keep coming in" cannot be followed by a 409."""
        cases = [
            (allow, members_only, requester, admitted)
            for allow in (frozenset(), frozenset({"o@example.com"}), frozenset({"dana@example.com"}))
            for members_only in (False, True)
            for requester in ("o@example.com", "b@example.com", "stranger@example.com")
            for admitted in (False, True)
        ]
        for allow, members_only, requester, admitted in cases:
            where = (sorted(allow), members_only, requester, admitted)
            with self.subTest(run=where):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                state = Path(tmp.name) / "state"
                state.mkdir()
                (state / "people.json").write_text(json.dumps({"version": 1, "people": self.ROWS}), encoding="utf-8")
                write_access(state / "access.json", True, "2026-01-01 00:00:00", "o@example.com")
                said = self.preview(allow, members_only, requester=requester, admitted=admitted).locks_out_requester
                refused = False
                try:
                    apply_managed(
                        state,
                        None,  # the off press sends no member list
                        {"login": requester, "name": "R"},
                        False,
                        NOW,
                        lambda action, details: None,
                        allow=allow,
                        members_only=members_only,
                        admitted_without_people=admitted,
                    )
                except LocksOutOwner:
                    refused = True
                self.assertEqual(said, refused, where)


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

    def test_set_one_role_judges_the_role_before_the_file(self):
        """A malformed role is never answered "not a member", with or without a people.json."""
        with self.assertRaisesRegex(ValueError, "role must be one of"):
            set_one_role(self.state, "a@example.com", "boss", self.audit)
        self.seed(row("a@example.com"))
        with self.assertRaisesRegex(ValueError, "role must be one of"):
            set_one_role(self.state, "nobody@example.com", "boss", self.audit)

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

        apply_managed(
            self.state,
            [target("carol@example.com")],
            OWNER,
            True,
            NOW,
            audit,
            allow=frozenset(),
            members_only=False,
            admitted_without_people=False,
        )
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
        return apply_managed(
            ps.APP.C.state,
            targets,
            LOCAL_ACTOR,
            managed,
            NOW,
            lambda action, details: None,
            allow=ps.APP.C.allow,
            members_only=ps.APP.C.access.members_only,
            admitted_without_people=True,  # the machine's own user, whom admission never filters
        )

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

    def test_an_owner_row_kept_under_allow_is_let_in_and_the_result_says_so(self):
        """The widening path: --allow alone refuses bob today, a kept owner row lets him in after the press."""
        set_config(allow=frozenset({"alice@example.com"}))
        self.assertTrue(ps.APP.C.people_file.parent.exists())
        ps.APP.C.people_file.write_text(
            json.dumps({"version": 1, "people": [row("bob@example.com", "owner")]}), encoding="utf-8"
        )
        self.assertEqual(self.status(BOB), (403, "not_allowed"))
        result = self.press([target("alice@example.com")])
        self.assertEqual(result.newly_admitted, ("bob@example.com",))
        self.assertEqual(self.status(BOB)[0], 200)


class SettableBackstop(StateBase):
    """The screens' write services refuse a role a screen may not give; the command line's services take all four."""

    def manage(self):
        """Switch the flag on, as a transition leaves it: a screen's member change needs it."""
        write_access(self.state / "access.json", True, "2026-01-01 00:00:00", OWNER["login"])

    def test_add_settable_refuses_owner_agent_and_unknown_before_any_file(self):
        """add_settable raises RoleNotSettable for owner, agent and a made-up role, and creates no file."""
        for role in ("owner", "agent", "root"):
            with self.subTest(role=role), self.assertRaises(RoleNotSettable):
                add_settable(self.state, "bob@example.com", role, None, self.audit)
        self.assertFalse((self.state / "people.json").exists())

    def test_set_settable_role_refuses_owner_and_agent(self):
        """set_settable_role cannot raise a member to owner or agent; the row and the audit are untouched."""
        self.seed(row("bob@example.com", "viewer"))
        for role in ("owner", "agent"):
            with self.subTest(role=role), self.assertRaises(RoleNotSettable):
                set_settable_role(self.state, "bob@example.com", role, self.audit)
        self.assertEqual(self.roles(), {"bob@example.com": "viewer"})
        self.assertEqual(self.audited, [])

    def test_the_command_line_services_still_make_owners(self):
        """add_one and set_one_role take owner: the first owner is made with the command line."""
        add_one(self.state, "alice@example.com", "owner", None, self.audit)
        add_one(self.state, "bob@example.com", "viewer", None, self.audit)
        set_one_role(self.state, "bob@example.com", "owner", self.audit)
        self.assertEqual(self.roles(), {"alice@example.com": "owner", "bob@example.com": "owner"})

    def test_add_settable_and_set_settable_role_give_viewer_and_editor(self):
        """The allowed roles pass through to the same writes."""
        self.state.mkdir(parents=True)
        self.manage()
        add_settable(self.state, "bob@example.com", "viewer", None, self.audit)
        self.assertEqual(set_settable_role(self.state, "bob@example.com", "editor", self.audit)["role"], "editor")
        self.assertEqual(remove_settable(self.state, "bob@example.com", self.audit)["login"], "bob@example.com")


class ManagedUnderTheLock(StateBase):
    """A screen's member change asks whether the flag is on from inside the write transaction, under the people lock.
    A check made before the lock can be stale when the row lands - and under --members-only a row written then admits
    its person at once - so the one that decides is the one the transaction makes."""

    def setUp(self):
        super().setUp()
        self.reset()

    def reset(self):
        """A state folder of its own for the next case: an owner, bob, the flag on and nothing audited yet."""
        self.state = Path(tempfile.mkdtemp(dir=self.tmp)) / "state"
        self.audited = []
        self.seed(row("owner@example.com", "owner"), row("bob@example.com", "viewer"))
        write_access(self.state / "access.json", True, "2026-01-01 00:00:00", OWNER["login"])
        self.before = self.files()

    def unmanage(self, body=None):
        """What another request does between the early check and the write: switch the flag off, or break the file."""
        if body is None:
            write_access(self.state / "access.json", False, "2026-01-01 00:00:01", OWNER["login"])
        else:
            (self.state / "access.json").write_text(body, encoding="utf-8")

    def changes(self):
        """The three member changes a screen makes, as (name, call) pairs."""
        return (
            ("add", lambda: add_settable(self.state, "carol@example.com", "viewer", None, self.audit)),
            ("role", lambda: set_settable_role(self.state, "bob@example.com", "editor", self.audit)),
            ("remove", lambda: remove_settable(self.state, "bob@example.com", self.audit)),
        )

    def race(self, change, body=None):
        """Run change with the flag switched between the transaction opening and the step running, and assert it
        wrote nothing. The switch happens inside the transaction, where only the flag read under the lock can see
        it."""
        real = access_service.people_transaction

        def switched(state, step, audit, then=None):
            """The real transaction, preceded by the other request's switch."""
            self.unmanage(body)
            return real(state, step, audit, then)

        with (
            mock.patch.object(access_service, "people_transaction", switched),
            self.assertRaises(NotManagedNow) as got,
        ):
            change()
        self.assertEqual(self.audited, [])
        self.assertEqual(self.files()[0], self.before[0])  # people.json untouched
        return got.exception

    def test_a_flag_switched_off_mid_request_refuses_every_member_change(self):
        for name, change in self.changes():
            with self.subTest(change=name):
                self.reset()
                self.assertEqual(self.race(change).flag, "not-managed")

    def test_a_flag_that_became_unusable_mid_request_refuses_every_member_change(self):
        for name, change in self.changes():
            with self.subTest(change=name):
                self.reset()
                self.assertEqual(self.race(change, "{not json").flag, "unusable")

    def test_the_same_changes_go_through_while_the_flag_stays_on(self):
        """The check refuses the race, not the ordinary request."""
        for name, change in self.changes():
            with self.subTest(change=name):
                self.reset()
                change()
                self.assertEqual(len(self.audited), 1)

    def test_a_member_change_on_an_unmanaged_instance_writes_nothing(self):
        """The plain case the sink also catches early; here it is the transaction's own read that refuses."""
        self.unmanage()
        for name, change in self.changes():
            with self.subTest(change=name), self.assertRaises(NotManagedNow):
                change()
        self.assertEqual(self.audited, [])
        self.assertEqual(self.files()[0], self.before[0])

    def test_a_change_without_a_people_file_still_reports_the_flag(self):
        """With no people.json nothing is written either way, and the answer says the flag is off rather than
        "not a member"."""
        (self.state / "people.json").unlink()
        self.unmanage()
        for change in (
            lambda: set_settable_role(self.state, "bob@example.com", "viewer", self.audit),
            lambda: remove_settable(self.state, "bob@example.com", self.audit),
        ):
            with self.assertRaises(NotManagedNow):
                change()
        self.assertFalse((self.state / "people.json").exists())
