"""limn.audit - the audit log module on its own: its import boundary and the writer called with a state dir only.

The first classes check that the module stands without the server. The ones after them are the append-only audit
log of v0.3.1 (issue #10 L5) through the server and the CLI: clear, purge, tokens and members are audited; the file
is mode 0600, append-only, never followed through a symlink, and whole under concurrent appends.

Run: uv run pytest -q tests/test_audit.py
"""

import ast
import json
import os
import pwd
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from limn import access, audit
from limn.access import LOCAL_ACTOR
from limn.audit import append_audit, audit_entry
from limn.events import EVENTS_KEEP

from helpers import ps
from helpers_access import A_LOGIN, ALICE, B_LOGIN, BOB, CLEAR_BODY, AccessBase, member_add, token_create

AUDIT_PY = Path(audit.__file__)


class ModuleBoundary(unittest.TestCase):
    """audit.py sits below the server and the CLI: the state directory and the clock come in as arguments."""

    def test_imports_only_the_standard_library_and_limn_files(self):
        """No server, HTTP or subprocess import; of limn only limn.files (store_lock)."""
        tree = ast.parse(AUDIT_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual({m for m in modules if m.startswith("limn")}, {"limn.files"})
        self.assertFalse({"http", "http.server", "urllib", "subprocess", "time"} & modules)

    def test_reads_no_server_global(self):
        """No run-argument object or server helper is named in the module."""
        tree = ast.parse(AUDIT_PY.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"C", "now_str", "who", "LOCAL_ACTOR", "PIN_LOCK"})


class Append(unittest.TestCase):
    """append_audit(state, entry) with no server loaded."""

    def test_appends_one_line_per_entry_in_order(self):
        """Two entries are two lines, in the order written, each the entry's JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            first = audit.audit_entry("member_added", {"login": "u"}, "cli", {"login": "a", "role": "viewer"}, 1.0)
            second = audit.audit_entry("member_removed", {"login": "u"}, "cli", {"login": "a"}, 2.0)
            self.assertTrue(audit.append_audit(state, first))
            self.assertTrue(audit.append_audit(state, second))
            lines = (state / audit.AUDIT_FILE).read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(ln) for ln in lines], [first, second])
            self.assertEqual(first["by"], {"login": "u", "name": "u"})

    def test_an_untyped_action_is_checked_at_the_cli_edge(self):
        """audit_action() passes a known action through and refuses any other string with ValueError - the check the
        CLI sink (which gets a plain str from limn.access) and audit_entry() share."""
        self.assertEqual(audit.audit_action("token_created"), "token_created")
        with self.assertRaisesRegex(ValueError, "unknown audit action 'dropped'"):
            audit.audit_action("dropped")

    def test_os_actor_names_the_process_account(self):
        """by for the CLI is the uid's account name, used as both login and name."""
        actor = audit.os_actor()
        self.assertEqual(actor["login"], actor["name"])
        self.assertTrue(actor["login"])


# ---------------------------------------------------------------- the append-only audit log through the server and the CLI (v0.3.1, issue #10 L5)


SRC = Path(__file__).resolve().parent.parent / "src"


def audit_rows(state=None):
    """Every line of <state>/audit.jsonl, parsed ([] if the file does not exist)."""
    p = Path(state or ps.APP.C.state) / "audit.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]


def os_login():
    """The OS account running the tests (what the CLI records as the actor)."""
    return pwd.getpwuid(os.getuid()).pw_name


class AuditLogServer(AccessBase):
    """clear and purge (owner actions over HTTP) are written to audit.jsonl, which outlives the events.jsonl rotation."""

    def setUp(self):
        super().setUp()
        self.set_people(
            [{"login": A_LOGIN, "name": "Alice Kim", "role": "owner"}, {"login": B_LOGIN, "name": "Bob Park"}]
        )
        self.add()
        self.add(8, 9)

    def test_clear_stays_in_the_audit_log_after_the_events_rotate(self):
        """Issue #10 L5: after EVENTS_KEEP + 1 other events the `cleared` record is gone from events.jsonl but kept in audit.jsonl."""
        code, d = self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual(code, 200, d)
        self.assertEqual(ps.APP._read_events()[0][-1]["type"], "cleared")  # still written for compatibility
        ps.APP.emit_events(
            [
                {"type": "mention", "pin": 1, "to": [B_LOGIN], "by": {"login": A_LOGIN, "name": "Alice Kim"}}
                for _ in range(EVENTS_KEEP + 1)
            ]
        )
        self.assertNotIn("cleared", {e["type"] for e in ps.APP._read_events()[0]})
        rows = audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"at", "ts", "action", "by", "via", "details"})
        self.assertEqual(
            (rows[0]["action"], rows[0]["by"], rows[0]["via"]),
            ("cleared", {"login": A_LOGIN, "name": "Alice Kim"}, "http"),
        )
        self.assertEqual(rows[0]["details"], {"n": 2, "archive": d["archive"]})
        self.assertIsInstance(rows[0]["ts"], float)

    def test_purge_is_audited(self):
        """The owner's permanent delete from the Trash leaves an audit line naming the pin."""
        ps.APP.pin_trash.drop_pin(1, dict(LOCAL_ACTOR))
        code, d = self.call("POST", "/api/pins/1/purge", None, ALICE)
        self.assertEqual(code, 200, d)
        self.assertEqual(
            [(r["action"], r["by"]["login"], r["details"]) for r in audit_rows()], [("purged", A_LOGIN, {"pin": 1})]
        )

    def test_refused_clear_and_purge_leave_no_audit_line(self):
        """Nothing that did not happen is audited: a clear without the phrase, a non-owner's clear or purge, a missing pin."""
        self.assertEqual(self.call("POST", "/api/clear", {"confirm": "yes"}, ALICE)[0], 400)
        self.assertEqual(self.call("POST", "/api/clear", CLEAR_BODY, BOB)[0], 403)
        ps.APP.pin_trash.drop_pin(1, dict(LOCAL_ACTOR))
        self.assertEqual(self.call("POST", "/api/pins/1/purge", None, BOB)[0], 403)
        self.assertEqual(self.call("POST", "/api/pins/99/purge", None, ALICE)[0], 404)
        self.assertEqual(audit_rows(), [])
        self.assertFalse((ps.APP.C.state / "audit.jsonl").exists())

    def test_audit_file_is_private_even_with_an_open_umask(self):
        """audit.jsonl is created with mode 0600 whatever the umask, and a wider pre-existing file is narrowed."""
        old = os.umask(0)
        try:
            self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        finally:
            os.umask(old)
        p = ps.APP.C.state / "audit.jsonl"
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        os.chmod(p, 0o644)
        self.add()
        self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_lines_are_only_ever_appended(self):
        """Earlier bytes are never rewritten - not even a line the server cannot parse."""
        p = ps.APP.C.state / "audit.jsonl"
        p.write_text("not json, kept as is\n", encoding="utf-8")
        os.chmod(p, 0o600)
        self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        first = p.read_bytes()
        self.add()
        self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        after = p.read_bytes()
        self.assertTrue(after.startswith(first))
        self.assertEqual(after.splitlines()[0], b"not json, kept as is")
        self.assertEqual(len(after.splitlines()), 3)

    def test_a_symlinked_audit_file_is_not_followed(self):
        """An audit.jsonl that is a symlink (to a file elsewhere) is refused: nothing is written through it, only a warning."""
        target = Path(self.tmp.name) / "elsewhere.jsonl"
        target.write_text("", encoding="utf-8")
        (ps.APP.C.state / "audit.jsonl").symlink_to(target)
        code, d = self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual((code, d.get("cleared")), (200, 2), d)
        self.assertEqual(target.read_text(encoding="utf-8"), "")

    def test_a_failing_audit_write_warns_but_the_clear_still_happens(self):
        """The action has already been applied when the audit line is written; a write failure is a warning, not a 500."""
        (ps.APP.C.state / "audit.jsonl").mkdir()  # cannot be opened for writing
        code, d = self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual((code, d.get("cleared")), (200, 2), d)
        self.assertEqual(ps.APP.snapshot_pins(), [])

    def test_concurrent_appends_keep_every_line_whole(self):
        """Writers in several threads (the server) never interleave or lose lines."""
        by = {"login": A_LOGIN, "name": "Alice Kim"}

        def write(k):
            for i in range(25):
                append_audit(ps.APP.C.state, audit_entry("purged", by, "http", {"pin": k * 100 + i}, time.time()))

        ts = [threading.Thread(target=write, args=(k,)) for k in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        pins = sorted(r["details"]["pin"] for r in audit_rows())
        self.assertEqual(pins, sorted(k * 100 + i for k in range(4) for i in range(25)))


class AuditEntryShape(unittest.TestCase):
    """audit_entry() builds one line from values passed in - the caller owns the clock."""

    def test_entry_carries_the_given_time_actor_channel_and_details(self):
        """at is the local wall-clock string of `now`, ts the same instant in epoch seconds; by keeps only login and name."""
        now = 1790000000.25
        e = audit_entry(
            "token_created", {"login": "u", "name": "U", "pic": "https://x"}, "cli", {"id": "ab12cd34"}, now
        )
        self.assertEqual(
            e,
            {
                "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                "ts": now,
                "action": "token_created",
                "by": {"login": "u", "name": "U"},
                "via": "cli",
                "details": {"id": "ab12cd34"},
            },
        )

    def test_unknown_actions_and_channels_are_programming_errors(self):
        """Only the documented actions and channels can be written."""
        with self.assertRaises(ValueError):
            audit_entry("deleted_everything", {"login": "u"}, "cli", {}, 0.0)
        with self.assertRaises(ValueError):
            audit_entry("cleared", {"login": "u"}, "mail", {}, 0.0)


class AuditLogCli(unittest.TestCase):
    """`limn token` and `limn member` (run on the server machine) audit what they change, as the OS account that ran them."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def limn(self, *args):
        env = dict(os.environ, PYTHONPATH=str(SRC))
        r = subprocess.run(
            [sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=60, env=env, check=False
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_token_create_and_revoke_are_audited_without_the_secret(self):
        """The audit line names the token (id, name) but never holds the token or its hash."""
        plain = self.limn("token", "create", "--state-dir", str(self.state), "--name", "ci").stdout.strip()
        self.limn("token", "revoke", "--state-dir", str(self.state), "ci")
        rows = audit_rows(self.state)
        self.assertEqual(
            [(r["action"], r["via"], r["by"]["login"]) for r in rows],
            [("token_created", "cli", os_login()), ("token_revoked", "cli", os_login())],
        )
        self.assertEqual(rows[0]["details"]["name"], "ci")
        self.assertEqual(rows[0]["details"], rows[1]["details"])
        text = (self.state / "audit.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(plain, text)
        self.assertNotIn(access.token_hash(plain), text)
        self.assertNotIn("sha256:", text)
        self.assertEqual(stat.S_IMODE((self.state / "audit.jsonl").stat().st_mode), 0o600)

    def test_member_add_role_change_and_remove_are_audited_with_the_previous_role(self):
        """Each membership change records who and the role before and after."""
        self.limn("member", "add", "--state-dir", str(self.state), "bob@example.com")
        self.limn("member", "role", "--state-dir", str(self.state), "bob@example.com", "owner")
        self.limn("member", "remove", "--state-dir", str(self.state), "bob@example.com")
        self.assertEqual(
            [(r["action"], r["details"]) for r in audit_rows(self.state)],
            [
                ("member_added", {"login": "bob@example.com", "role": "editor"}),
                ("member_role", {"login": "bob@example.com", "role": "owner", "previous_role": "editor"}),
                ("member_removed", {"login": "bob@example.com", "previous_role": "owner"}),
            ],
        )

    def test_changes_that_did_not_happen_are_not_audited(self):
        """Revoking an unknown token or changing an unknown member exits non-zero and writes nothing."""
        env = dict(os.environ, PYTHONPATH=str(SRC))
        for args in (
            ("token", "revoke", "--state-dir", str(self.state), "nope"),
            ("member", "role", "--state-dir", str(self.state), "nobody@example.com", "owner"),
            ("member", "add", "--state-dir", str(self.state), "bad login"),
        ):
            r = subprocess.run(
                [sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=60, env=env, check=False
            )
            self.assertEqual(r.returncode, 1, (args, r.stdout, r.stderr))
        self.assertEqual(audit_rows(self.state), [])

    def test_python_helpers_audit_too(self):
        """The state helpers themselves write the line, so any caller of them is audited."""
        e, _ = token_create(self.state, "bot")
        member_add(self.state, "carol@example.com", "viewer")
        self.assertEqual(
            [(r["action"], r["details"]) for r in audit_rows(self.state)],
            [
                ("token_created", {"id": e["id"], "name": "bot"}),
                ("member_added", {"login": "carol@example.com", "role": "viewer"}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
