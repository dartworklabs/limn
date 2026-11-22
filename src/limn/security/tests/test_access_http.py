"""The owner's member routes over HTTP: GET /api/access and the four POSTs, through the real request handler.

docs/superpowers/plans/2026-11-22-viewer-access-management.md Task 5. The role matrix (who may call what) is
test_access_paths.py; this file is what the routes answer and write once the role rule has let the owner in.

Run: uv run pytest -q src/limn/security/tests/test_access_http.py
"""

import json

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

    def test_tailnet_block_is_empty_until_wired(self):
        """The directory is a stand-in until the tailnet read lands: no users, partial, and a reason."""
        tailnet = self.get_access()["tailnet"]
        self.assertEqual(tailnet["users"], [])
        self.assertIs(tailnet["partial"], True)
        self.assertTrue(tailnet["reason"])

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
        self.assertEqual((code, d), (200, {"ok": False}))

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

    def test_unusable_people_file_refuses_without_a_path(self):
        """A people.json that cannot be used is people_unreadable, and the answer names no state-folder path."""
        self.manage()
        ps.APP.C.people_file.write_text("{not json", encoding="utf-8")
        code, d = self.call("POST", "/api/access/managed", dict(CONFIRM, managed=False, members=[]), ALICE)
        self.assertNotEqual(code, 200)
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
