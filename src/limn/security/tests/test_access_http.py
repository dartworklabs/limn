"""The owner's member routes over HTTP: GET /api/access and the four POSTs, through the real request handler.

docs/superpowers/plans/2026-11-22-viewer-access-management.md Task 5. The role matrix (who may call what) is
test_access_paths.py; this file is what the routes answer and write once the role rule has let the owner in.

Run: uv run pytest -q src/limn/security/tests/test_access_http.py
"""

import json
from unittest import mock

from limn.platform.tailnet import TailnetDirectory, TailnetUser, unavailable
from limn.security import access_service
from limn.security.access_store import write_access

from helpers import ps, set_config
from helpers_access import ALICE, BOB, CAROL, AccessBase

CONFIRM = {"confirm": "manage access from the viewer"}
OWNER_ROW = {"login": "alice@example.com", "name": "Alice", "role": "owner"}
BOB_ROW = {"login": "bob@example.com", "name": "Bob", "role": "editor"}


class AccessHttp(AccessBase):
    """A run whose owner (Alice) is in people.json."""

    def setUp(self):
        """Alice the owner and Bob the editor in people.json; the instance is not managed yet."""
        super().setUp()
        self.set_people([OWNER_ROW, BOB_ROW])

    def manage(self):
        """Turn the access flag on the way the transition leaves it."""
        write_access(ps.APP.C.access_file, True, "2026-01-01 00:00:00", "alice@example.com")

    def audit_lines(self):
        """The audit.jsonl lines written so far, parsed."""
        path = ps.APP.C.state / "audit.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def get_access(self):
        """GET /api/access as the owner; the test fails unless it is a 200."""
        code, d = self.call("GET", "/api/access", headers=ALICE)
        self.assertEqual(code, 200, d)
        return d

    def test_get_access_lists_members_and_args(self):
        """A managed instance answers the flag with its stamp, the run's arguments and the member rows, in this order."""
        self.manage()
        set_config(allow=frozenset({"alice@example.com"}))
        d = self.get_access()
        self.assertEqual(
            list(d), ["managed", "managed_at", "managed_by", "unmanaged_admits_everyone", "args", "members", "tailnet"]
        )
        self.assertEqual(
            (d["managed"], d["managed_at"], d["managed_by"]), (True, "2026-01-01 00:00:00", "alice@example.com")
        )
        self.assertEqual(d["args"], {"allow": ["alice@example.com"], "members_only": False})
        self.assertFalse(d["unmanaged_admits_everyone"])
        self.assertEqual(
            [(m["login"], m["name"], m["role"]) for m in d["members"]],
            [("alice@example.com", "Alice", "owner"), ("bob@example.com", "Bob", "editor")],
        )

    def test_unmanaged_instance_carries_the_transition_screen(self):
        """Before the switch the answer also says who gets in today and which rows the owner may check; with neither
        --allow nor --members-only it says turning the flag off would admit everyone."""
        d = self.get_access()
        self.assertEqual(list(d), ["managed", "unmanaged_admits_everyone", "args", "members", "transition", "tailnet"])
        self.assertFalse(d["managed"])
        self.assertTrue(d["unmanaged_admits_everyone"])
        self.assertEqual([x["login"] for x in d["transition"]["settable"]], ["bob@example.com"])
        self.assertEqual([x["login"] for x in d["transition"]["fixed"]], ["alice@example.com"])
        self.assertTrue(d["transition"]["fixed"][0]["admitted_today"])

    def test_tailnet_block_lists_the_directory_without_the_members(self):
        """The wired directory's people appear as {login, name, pic?} rows, the members among them are left out, and
        the block says the list is partial and carries no reason."""
        read = TailnetDirectory(
            (
                TailnetUser("bob@example.com", "Bob", None),
                TailnetUser("dana@example.com", "Dana", "https://pics.example.com/dana.png"),
                TailnetUser("erin@example.com", "Erin", None),
            ),
            True,
            None,
        )
        with mock.patch.object(ps, "read_tailnet_directory", return_value=read):
            tailnet = self.get_access()["tailnet"]
        self.assertEqual(
            tailnet,
            {
                "users": [
                    {"login": "dana@example.com", "name": "Dana", "pic": "https://pics.example.com/dana.png"},
                    {"login": "erin@example.com", "name": "Erin"},
                ],
                "partial": True,
            },
        )

    def test_tailnet_block_drops_logins_no_person_holds(self):
        """The transport passes every login on; the screen's rows keep only logins that could be members."""
        read = TailnetDirectory(
            tuple(TailnetUser(x, x, None) for x in ("has space@example.com", "local", "agent:x", "ok@example.com")),
            True,
            None,
        )
        with mock.patch.object(ps, "read_tailnet_directory", return_value=read):
            tailnet = self.get_access()["tailnet"]
        self.assertEqual([x["login"] for x in tailnet["users"]], ["ok@example.com"])

    def test_tailnet_block_says_why_there_is_no_list(self):
        """A directory that could not be read is an empty, partial block with the reason code."""
        with mock.patch.object(ps, "read_tailnet_directory", return_value=unavailable("tailscaled_not_found")):
            tailnet = self.get_access()["tailnet"]
        self.assertEqual(tailnet, {"users": [], "partial": True, "reason": "tailscaled_not_found"})

    def test_get_writes_nothing(self):
        """Reading the panel creates no file in the state folder."""
        before = sorted(p.name for p in ps.APP.C.state.iterdir())
        self.get_access()
        self.assertEqual(sorted(p.name for p in ps.APP.C.state.iterdir()), before)

    def test_member_add_applies_without_restart(self):
        """After the POST the very next request of the new member is admitted; before it, it was refused."""
        self.manage()
        self.assertEqual(self.call("GET", "/api/pins", headers=CAROL)[0], 403)
        code, d = self.call(
            "POST", "/api/members/add", {"login": "carol@example.com", "role": "viewer", "name": "Carol"}, ALICE
        )
        self.assertEqual(
            (code, d["ok"], d["member"]["login"], d["member"]["role"]), (200, True, "carol@example.com", "viewer")
        )
        self.assertEqual(self.call("GET", "/api/pins", headers=CAROL)[0], 200)

    def test_member_role_and_remove_apply_at_once(self):
        """Changing a role and removing a member take effect on the next request; an absent member answers ok false."""
        self.manage()
        code, d = self.call("POST", "/api/members/role", {"login": "bob@example.com", "role": "viewer"}, ALICE)
        self.assertEqual((code, d["member"]["role"]), (200, "viewer"))
        self.assertEqual(self.call("POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 5}, BOB)[0], 403)
        code, d = self.call("POST", "/api/members/remove", {"login": "bob@example.com"}, ALICE)
        self.assertEqual((code, d["ok"]), (200, True))
        self.assertEqual(self.call("GET", "/api/pins", headers=BOB)[0], 403)
        code, d = self.call("POST", "/api/members/remove", {"login": "bob@example.com"}, ALICE)
        self.assertEqual((code, d), (200, {"ok": True, "member": None}))

    def test_member_add_of_a_member_or_a_bad_login_is_refused(self):
        """409 already_member for a login people.json holds, 400 bad_login for one no person could have."""
        self.manage()
        code, d = self.call("POST", "/api/members/add", {"login": "bob@example.com", "role": "viewer"}, ALICE)
        self.assertEqual((code, d["reason"]), (409, "already_member"))
        for bad in ("has space", "", "local", None, 7):
            with self.subTest(login=bad):
                code, d = self.call("POST", "/api/members/add", {"login": bad, "role": "viewer"}, ALICE)
                self.assertEqual((code, d["reason"]), (400, "bad_login"), d)

    def test_member_post_on_unmanaged_instance_is_409(self):
        """Without the flag a member change says to switch first, and writes nothing."""
        before = self.people_file()
        for path, body in (
            ("/api/members/add", {"login": "carol@example.com", "role": "viewer"}),
            ("/api/members/role", {"login": "bob@example.com", "role": "viewer"}),
            ("/api/members/remove", {"login": "bob@example.com"}),
        ):
            with self.subTest(path=path):
                code, d = self.call("POST", path, body, ALICE)
                self.assertEqual((code, d["reason"]), (409, "not_managed"), d)
        self.assertEqual(self.people_file(), before)

    def test_role_owner_or_agent_is_400(self):
        """The screen gives viewer and editor only; owner, agent and a made-up role are role_not_settable."""
        self.manage()
        for role in ("owner", "agent", "root", None):
            for path, body in (
                ("/api/members/add", {"login": "carol@example.com", "role": role}),
                ("/api/members/role", {"login": "bob@example.com", "role": role}),
            ):
                with self.subTest(path=path, role=role):
                    code, d = self.call("POST", path, body, ALICE)
                    self.assertEqual((code, d["reason"]), (400, "role_not_settable"), d)
                    self.assertIn(body["login"], d["error"])
                    self.assertIn(str(role), d["error"])
        self.assertEqual(self.people_file(), [OWNER_ROW, BOB_ROW])

    def test_remove_last_owner_is_409(self):
        """Removing or demoting the only owner is refused, and the answer names no path."""
        self.manage()
        for path, body in (
            ("/api/members/remove", {"login": "alice@example.com"}),
            ("/api/members/role", {"login": "alice@example.com", "role": "editor"}),
        ):
            with self.subTest(path=path):
                code, d = self.call("POST", path, body, ALICE)
                self.assertEqual((code, d["reason"]), (409, "last_owner"), d)
                self.assertIn("alice@example.com", d["error"])
                self.assertNotIn(str(ps.APP.C.state), json.dumps(d))
        self.assertEqual(self.people_file(), [OWNER_ROW, BOB_ROW])

    def test_transition_without_confirm_is_400(self):
        """The phrase is required, as /api/clear requires its own."""
        for body in ({"managed": True, "members": []}, {"managed": True, "members": [], "confirm": "yes"}):
            with self.subTest(body=body):
                code, d = self.call("POST", "/api/access/managed", body, ALICE)
                self.assertEqual((code, d["reason"]), (400, "confirm_required"), d)
        self.assertFalse(ps.APP.C.access_file.exists())

    def test_transition_body_must_have_its_shape(self):
        """managed is a boolean, members a list of {login, role}; anything else is bad_access_request."""
        for body in (
            dict(CONFIRM, managed="yes", members=[]),
            dict(CONFIRM, managed=True, members={}),
            dict(CONFIRM, managed=True, members=["bob@example.com"]),
            dict(CONFIRM, managed=True, members=[{"login": "bob@example.com"}]),
            dict(CONFIRM, managed=True, members=[BOB_ROW, BOB_ROW]),
        ):
            with self.subTest(body=body):
                code, d = self.call("POST", "/api/access/managed", body, ALICE)
                self.assertEqual((code, d["reason"]), (400, "bad_access_request"), d)
        self.assertFalse(ps.APP.C.access_file.exists())

    def test_transition_role_owner_names_the_login_and_the_role(self):
        """The transition refuses a row that gives a screen-unsettable role, naming both who and which role."""
        body = dict(CONFIRM, managed=True, members=[{"login": "carol@example.com", "role": "owner"}])
        code, d = self.call("POST", "/api/access/managed", body, ALICE)
        self.assertEqual((code, d["reason"]), (400, "role_not_settable"), d)
        self.assertIn("carol@example.com", d["error"])
        self.assertIn("owner", d["error"])
        self.assertFalse(ps.APP.C.access_file.exists())

    def test_transition_applies_and_reports(self):
        """Switching on with the listed members writes the flag, answers what changed and who is newly admitted, and the
        owner stays in."""
        set_config(allow=frozenset({"alice@example.com"}))
        body = dict(CONFIRM, managed=True, members=[{"login": "bob@example.com", "role": "editor"}])
        code, d = self.call("POST", "/api/access/managed", body, ALICE)
        self.assertEqual(code, 200, d)
        self.assertEqual(
            d,
            {
                "ok": True,
                "managed": True,
                "added": [],
                "removed": [],
                "changed": [],
                "kept": ["alice@example.com"],
                "newly_admitted": ["bob@example.com"],
            },
        )
        self.assertTrue(self.get_access()["managed"])
        self.assertEqual(self.call("GET", "/api/pins", headers=BOB)[0], 200)

    def test_transition_locking_out_requester_is_409(self):
        """The --auth local owner has no people.json row, so a list without their login would shut them out."""
        set_config(auth="local", agent_loopback=False, local_user="dana@example.com")
        body = dict(CONFIRM, managed=True, members=[{"login": "bob@example.com", "role": "editor"}])
        code, d = self.call("POST", "/api/access/managed", body)
        self.assertEqual((code, d["reason"]), (409, "locks_out_owner"), d)
        self.assertNotIn(str(ps.APP.C.state), json.dumps(d))
        self.assertFalse(ps.APP.C.access_file.exists())

    def local_owner(self):
        """Run as --auth local: the owner whose role does not come from people.json, so the only principal that reaches
        the routes while either file is unusable (every header identity is refused or a viewer then)."""
        set_config(auth="local", agent_loopback=False, local_user="dana@example.com")

    def test_unusable_people_file_is_people_unreadable_without_a_path(self):
        """With people.json unusable, the local owner's read and every write answer 403 people_unreadable, and no body
        names a state-folder path. (A header identity never gets here: it is a viewer, refused as such first.)"""
        self.manage()
        ps.APP.C.people_file.write_text("{not json", encoding="utf-8")
        self.local_owner()
        answers = [self.call("GET", "/api/access")]
        for path, body in (
            ("/api/members/add", {"login": "carol@example.com", "role": "viewer"}),
            ("/api/members/role", {"login": "bob@example.com", "role": "viewer"}),
            ("/api/members/remove", {"login": "bob@example.com"}),
            ("/api/access/managed", dict(CONFIRM, managed=False)),
        ):
            answers.append(self.call("POST", path, body))
        for code, d in answers:
            self.assertEqual((code, d["reason"]), (403, "people_unreadable"), d)
            self.assertNotIn(str(ps.APP.C.state), json.dumps(d))

    def test_unusable_access_file_is_access_unreadable_without_a_path(self):
        """With access.json unusable, the local owner's read and the member writes answer 403 access_unreadable (a header
        identity is refused at admission with the same reason)."""
        ps.APP.C.access_file.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.call("GET", "/api/access", headers=ALICE)[1]["reason"], "access_unreadable")
        self.local_owner()
        answers = [self.call("GET", "/api/access")]
        for path, body in (
            ("/api/members/add", {"login": "carol@example.com", "role": "viewer"}),
            ("/api/members/role", {"login": "bob@example.com", "role": "viewer"}),
            ("/api/members/remove", {"login": "bob@example.com"}),
        ):
            answers.append(self.call("POST", path, body))
        for code, d in answers:
            self.assertEqual((code, d["reason"]), (403, "access_unreadable"), d)
            self.assertNotIn(str(ps.APP.C.state), json.dumps(d))

    def test_audit_lines_say_via_http(self):
        """Each change is a line of audit.jsonl by the owner, through "http"."""
        self.manage()
        self.call("POST", "/api/members/add", {"login": "carol@example.com", "role": "viewer"}, ALICE)
        self.call("POST", "/api/members/role", {"login": "carol@example.com", "role": "editor"}, ALICE)
        self.call("POST", "/api/members/remove", {"login": "carol@example.com"}, ALICE)
        lines = self.audit_lines()
        self.assertEqual([x["action"] for x in lines], ["member_added", "member_role", "member_removed"])
        for line in lines:
            self.assertEqual((line["via"], line["by"]["login"]), ("http", "alice@example.com"))

    def test_role_on_a_non_member_is_409(self):
        """The requested state is unreachable: not_a_member, and nothing is written."""
        self.manage()
        code, d = self.call("POST", "/api/members/role", {"login": "nobody@example.com", "role": "viewer"}, ALICE)
        self.assertEqual((code, d["reason"]), (409, "not_a_member"), d)
        self.assertEqual(self.people_file(), [OWNER_ROW, BOB_ROW])

    def test_remove_of_a_non_member_is_200(self):
        """The end state already holds, so it is a success that says it removed no one."""
        self.manage()
        code, d = self.call("POST", "/api/members/remove", {"login": "nobody@example.com"}, ALICE)
        self.assertEqual((code, d), (200, {"ok": True, "member": None}))
        self.assertEqual(self.people_file(), [OWNER_ROW, BOB_ROW])

    def test_turning_off_without_members_keeps_a_row_added_during_the_request(self):
        """Omitted members means "leave the viewer/editor rows as they are", decided from the rows the transaction reads
        under its lock. A member another process adds after the request began but before the transaction opens the file
        stays; a list computed from an earlier read would have removed them."""
        self.manage()
        carol = {"login": "carol@example.com", "name": "Carol", "role": "viewer"}
        real = access_service.people_transaction

        def transaction_after_an_add(state, step, audit, then=None):
            """The real transaction, preceded by `limn member add carol` landing from another process."""
            self.set_people([OWNER_ROW, BOB_ROW, carol])
            return real(state, step, audit, then)

        with mock.patch.object(access_service, "people_transaction", transaction_after_an_add):
            code, d = self.call("POST", "/api/access/managed", dict(CONFIRM, managed=False), ALICE)
        self.assertEqual((code, d["removed"], d["added"], d["managed"]), (200, [], [], False), d)
        self.assertEqual(
            [x["login"] for x in self.people_file()], ["alice@example.com", "bob@example.com", "carol@example.com"]
        )
        self.assertFalse(self.get_access()["managed"])
