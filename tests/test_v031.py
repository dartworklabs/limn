"""v0.3.1 (issue #10): the two low-severity event findings of the v0.2.1 security review.

L3  Toggling an @-tag through repeated note edits sent the tagged person a new `mention` every time. Note mentions now
    have a cooldown per (actor, target, pin); replies and reopen reasons still notify every time.
L5  The `cleared` audit record rotated out of events.jsonl (which keeps the newest EVENTS_KEEP). Destructive and owner
    actions now also go to an append-only audit log, <state_dir>/audit.jsonl, which nothing truncates.

Design notes live in docs/handbook/api.md §이벤트 (`events.jsonl`) and §감사 기록 (`audit.jsonl`).

Run: uv run pytest -q tests/test_v031.py
"""
import json
import os
import pwd
import stat
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn.mentions import NOTE_MENTION_COOLDOWN_S
from test_access import ALICE, BOB, CAROL, AccessBase
from test_qa_021 import CLEAR_BODY, actor
from test_server import add_pin, Base, edit_pin, ps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
A_LOGIN, B_LOGIN, C_LOGIN = (h["Tailscale-User-Login"] for h in (ALICE, BOB, CAROL))


def note_ev(by, to, pin, ts, **extra):
    """An events.jsonl mention record as a note save writes it (no `msg`: it did not come from a thread post)."""
    return dict({"type": "mention", "pin": pin, "doc": "main", "to": list(to), "by": {"login": by, "name": by},
                 "seq": 1, "at": "2026-09-26 10:00:00", "ts": ts}, **extra)


# ---------------------------------------------------------------- L3: the cooldown decision (pure)

class NoteMentionCooldownRule(unittest.TestCase):
    """note_mention_targets() decides which newly tagged people a note save notifies, from the recent events and a clock
    reading passed in - no file, no clock of its own."""

    def targets(self, recent, now, added=(B_LOGIN,), by=A_LOGIN, pin=7):
        return ps.note_mention_targets(list(added), recent, by, pin, now)

    def test_everyone_added_is_notified_when_there_is_no_recent_note_mention(self):
        """With an empty log every newly tagged person gets a mention, in the order given."""
        self.assertEqual(self.targets([], 1000.0, added=(B_LOGIN, C_LOGIN)), [B_LOGIN, C_LOGIN])

    def test_same_actor_target_and_pin_is_suppressed_within_the_window(self):
        """A note mention from the same actor to the same person about the same pin inside ten minutes suppresses the next."""
        recent = [note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0)]
        self.assertEqual(self.targets(recent, 1000.0 + 1), [])
        self.assertEqual(self.targets(recent, 1000.0 + NOTE_MENTION_COOLDOWN_S - 0.001), [])

    def test_a_mention_is_sent_again_once_the_window_has_passed(self):
        """Exactly NOTE_MENTION_COOLDOWN_S (ten minutes) after the last sent note mention, the tag notifies again."""
        self.assertEqual(NOTE_MENTION_COOLDOWN_S, 600)
        recent = [note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0)]
        self.assertEqual(self.targets(recent, 1000.0 + NOTE_MENTION_COOLDOWN_S), [B_LOGIN])

    def test_each_key_part_keeps_its_own_cooldown(self):
        """The key is (actor login, target login, pin id): changing any one of them is not suppressed."""
        recent = [note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0)]
        self.assertEqual(self.targets(recent, 1001.0, by=C_LOGIN), [B_LOGIN])            # another actor
        self.assertEqual(self.targets(recent, 1001.0, pin=8), [B_LOGIN])                 # another pin
        self.assertEqual(self.targets(recent, 1001.0, added=(B_LOGIN, C_LOGIN)), [C_LOGIN])   # another target

    def test_reply_and_reopen_mentions_never_start_a_note_cooldown(self):
        """Mentions from thread posts (they carry `msg`) and other event types do not count - replies notify every time."""
        recent = [note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0, msg=3),
                  dict(note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0), type="assigned"),
                  dict(note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0), type="replied")]
        self.assertEqual(self.targets(recent, 1001.0), [B_LOGIN])

    def test_records_without_a_usable_time_or_far_from_now_are_ignored(self):
        """A record the rule cannot place in time (missing, non-numeric, boolean) or more than the window away from now on
        either side (the clock stepped back) suppresses nothing."""
        recent = [note_ev(A_LOGIN, [B_LOGIN], 7, ts=None), note_ev(A_LOGIN, [B_LOGIN], 7, ts="1000"),
                  note_ev(A_LOGIN, [B_LOGIN], 7, ts=True), note_ev(A_LOGIN, [B_LOGIN], 7, ts=5000.0)]
        self.assertEqual(self.targets(recent, 1001.0), [B_LOGIN])

    def test_a_record_rounded_just_past_now_still_counts(self):
        """events.jsonl stores ts rounded to milliseconds, so the previous mention may read as slightly after `now`."""
        self.assertEqual(self.targets([note_ev(A_LOGIN, [B_LOGIN], 7, ts=1001.0005)], 1001.0), [])


# ---------------------------------------------------------------- L3: through the pin operations

class NoteMentionCooldown(Base):
    """Toggling @Bob through note edits notifies Bob once per ten minutes per editor and pin; replies are unchanged."""

    def setUp(self):
        super().setUp()
        ps._PEOPLE_SEEN.clear()
        ps._EVENTS_CACHE.clear()
        for h in (ALICE, BOB, CAROL):
            ps.record_person(actor(h))
        self.A, self.B, self.C = (actor(h) for h in (ALICE, BOB, CAROL))
        self.t0 = float(int(time.time()))                  # whole seconds: events.jsonl rounds ts to milliseconds

    def mentions_to_bob(self):
        return [e for e in ps._read_events()[0] if e["type"] == "mention" and B_LOGIN in e["to"]]

    def edit_note(self, pid, note, who):
        return edit_pin(pid, {"note": note, "base_rev": ps.find_pin(ps.snapshot_pins(), pid)["rev"]}, who)

    def toggle(self, pid, who, times=3):
        for _ in range(times):
            self.edit_note(pid, "이 문단 줄여 주세요", who)
            self.edit_note(pid, "@Bob Park 이 문단 줄여 주세요", who)

    def test_toggling_a_tag_three_times_within_ten_minutes_sends_one_mention(self):
        """Issue #10 L3: pin with @Bob, then remove and re-add the tag three times - Bob hears of it once, not four times."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 이 문단 줄여 주세요"}, self.A).record["id"]
            self.toggle(pid, self.A)
        self.assertEqual(len(self.mentions_to_bob()), 1)
        self.assertEqual(ps.find_pin(ps.snapshot_pins(), pid)["mentions"], [B_LOGIN])   # the note still tags him

    def test_the_tag_notifies_again_after_the_window(self):
        """Ten minutes after the last sent note mention, re-adding the tag is a new mention (fake clock)."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = self.add(actor=self.A)
            self.edit_note(pid, "@Bob Park 봐 주세요", self.A)
            self.toggle(pid, self.A, times=2)
        self.assertEqual(len(self.mentions_to_bob()), 1)
        with mock.patch.object(ps.time, "time", return_value=self.t0 + NOTE_MENTION_COOLDOWN_S - 1):
            self.toggle(pid, self.A, times=1)
        self.assertEqual(len(self.mentions_to_bob()), 1)
        with mock.patch.object(ps.time, "time", return_value=self.t0 + NOTE_MENTION_COOLDOWN_S):
            self.toggle(pid, self.A, times=2)
        self.assertEqual(len(self.mentions_to_bob()), 2)                                  # one more, then quiet again

    def test_note_append_with_the_tag_is_under_the_same_cooldown(self):
        """note_append that writes @Bob again counts as a note edit: suppressed inside the window, sent after it."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 부탁"}, self.A).record["id"]
            edit_pin(pid, {"note_append": "@Bob Park 급합니다"}, self.A)
        self.assertEqual(len(self.mentions_to_bob()), 1)
        with mock.patch.object(ps.time, "time", return_value=self.t0 + NOTE_MENTION_COOLDOWN_S + 5):
            edit_pin(pid, {"note_append": "@Bob Park 아직입니다"}, self.A)
        self.assertEqual(len(self.mentions_to_bob()), 2)

    def test_another_editor_or_pin_has_its_own_cooldown(self):
        """Carol tagging Bob on the same pin, or Alice tagging him on another pin, still notifies Bob."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            p1 = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 하나"}, self.A).record["id"]
            self.edit_note(p1, "없음", self.C)
            self.edit_note(p1, "@Bob Park 둘", self.C)
            p2 = self.add(lo=8, hi=9, actor=self.A)
            self.edit_note(p2, "@Bob Park 셋", self.A)
        by = [(e["by"]["login"], e["pin"]) for e in self.mentions_to_bob()]
        self.assertEqual(by, [(A_LOGIN, p1), (C_LOGIN, p1), (A_LOGIN, p2)])

    def test_replies_and_reopen_reasons_still_notify_every_time(self):
        """Explicit messages are not rate-limited: every reply or reopen reason that tags Bob is a mention."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 메모"}, self.A).record["id"]
            ps.reply_pin(pid, "@Bob Park 하나", self.A)
            ps.reply_pin(pid, "@Bob Park 둘", self.A)
            ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
            ps.set_done(pid, False, self.A, reason="@Bob Park 다시")
        self.assertEqual(len(self.mentions_to_bob()), 4)

    def test_a_reply_mention_does_not_silence_a_following_note_tag(self):
        """The cooldown counts note mentions only: a reply that tagged Bob does not stop the next note tag."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = self.add(actor=self.A)
            ps.reply_pin(pid, "@Bob Park 답글", self.A)
            self.edit_note(pid, "@Bob Park 메모에서도", self.A)
        self.assertEqual(len(self.mentions_to_bob()), 2)


# ---------------------------------------------------------------- L5: the append-only audit log

def audit_rows(state=None):
    """Every line of <state>/audit.jsonl, parsed ([] if the file does not exist)."""
    p = Path(state or ps.C.state) / "audit.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]


def os_login():
    return pwd.getpwuid(os.getuid()).pw_name


class AuditLogServer(AccessBase):
    """clear and purge (owner actions over HTTP) are written to audit.jsonl, which outlives the events.jsonl rotation."""

    def setUp(self):
        super().setUp()
        ps._EVENTS_CACHE.clear()
        self.set_people([{"login": A_LOGIN, "name": "Alice Kim", "role": "owner"}, {"login": B_LOGIN, "name": "Bob Park"}])
        self.add()
        self.add(8, 9)

    def test_clear_stays_in_the_audit_log_after_the_events_rotate(self):
        """Issue #10 L5: after EVENTS_KEEP + 1 other events the `cleared` record is gone from events.jsonl but kept in audit.jsonl."""
        code, d = self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual(code, 200, d)
        self.assertEqual(ps._read_events()[0][-1]["type"], "cleared")                     # still written for compatibility
        ps.emit_events([{"type": "mention", "pin": 1, "to": [B_LOGIN], "by": {"login": A_LOGIN, "name": "Alice Kim"}}
                        for _ in range(ps.EVENTS_KEEP + 1)])
        self.assertNotIn("cleared", {e["type"] for e in ps._read_events()[0]})
        rows = audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"at", "ts", "action", "by", "via", "details"})
        self.assertEqual((rows[0]["action"], rows[0]["by"], rows[0]["via"]),
                         ("cleared", {"login": A_LOGIN, "name": "Alice Kim"}, "http"))
        self.assertEqual(rows[0]["details"], {"n": 2, "archive": d["archive"]})
        self.assertIsInstance(rows[0]["ts"], float)

    def test_purge_is_audited(self):
        """The owner's permanent delete from the Trash leaves an audit line naming the pin."""
        ps.drop_pin(1, dict(ps.LOCAL_ACTOR))
        code, d = self.call("POST", "/api/pins/1/purge", None, ALICE)
        self.assertEqual(code, 200, d)
        self.assertEqual([(r["action"], r["by"]["login"], r["details"]) for r in audit_rows()],
                         [("purged", A_LOGIN, {"pin": 1})])

    def test_refused_clear_and_purge_leave_no_audit_line(self):
        """Nothing that did not happen is audited: a clear without the phrase, a non-owner's clear or purge, a missing pin."""
        self.assertEqual(self.call("POST", "/api/clear", {"confirm": "yes"}, ALICE)[0], 400)
        self.assertEqual(self.call("POST", "/api/clear", CLEAR_BODY, BOB)[0], 403)
        ps.drop_pin(1, dict(ps.LOCAL_ACTOR))
        self.assertEqual(self.call("POST", "/api/pins/1/purge", None, BOB)[0], 403)
        self.assertEqual(self.call("POST", "/api/pins/99/purge", None, ALICE)[0], 404)
        self.assertEqual(audit_rows(), [])
        self.assertFalse((ps.C.state / "audit.jsonl").exists())

    def test_audit_file_is_private_even_with_an_open_umask(self):
        """audit.jsonl is created with mode 0600 whatever the umask, and a wider pre-existing file is narrowed."""
        old = os.umask(0)
        try:
            self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        finally:
            os.umask(old)
        p = ps.C.state / "audit.jsonl"
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        os.chmod(p, 0o644)
        self.add()
        self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_lines_are_only_ever_appended(self):
        """Earlier bytes are never rewritten - not even a line the server cannot parse."""
        p = ps.C.state / "audit.jsonl"
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
        (ps.C.state / "audit.jsonl").symlink_to(target)
        code, d = self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual((code, d.get("cleared")), (200, 2), d)
        self.assertEqual(target.read_text(encoding="utf-8"), "")

    def test_a_failing_audit_write_warns_but_the_clear_still_happens(self):
        """The action has already been applied when the audit line is written; a write failure is a warning, not a 500."""
        (ps.C.state / "audit.jsonl").mkdir()                                            # cannot be opened for writing
        code, d = self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual((code, d.get("cleared")), (200, 2), d)
        self.assertEqual(ps.snapshot_pins(), [])

    def test_concurrent_appends_keep_every_line_whole(self):
        """Writers in several threads (the server) never interleave or lose lines."""
        by = {"login": A_LOGIN, "name": "Alice Kim"}

        def write(k):
            for i in range(25):
                ps.append_audit(ps.C.state, ps.audit_entry("purged", by, "http", {"pin": k * 100 + i}, time.time()))
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
        e = ps.audit_entry("token_created", {"login": "u", "name": "U", "pic": "https://x"}, "cli", {"id": "ab12cd34"}, now)
        self.assertEqual(e, {"at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "ts": now,
                             "action": "token_created", "by": {"login": "u", "name": "U"}, "via": "cli",
                             "details": {"id": "ab12cd34"}})

    def test_unknown_actions_and_channels_are_programming_errors(self):
        """Only the documented actions and channels can be written."""
        with self.assertRaises(ValueError):
            ps.audit_entry("deleted_everything", {"login": "u"}, "cli", {}, 0.0)
        with self.assertRaises(ValueError):
            ps.audit_entry("cleared", {"login": "u"}, "mail", {}, 0.0)


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
        r = subprocess.run([sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=60, env=env,
                           check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_token_create_and_revoke_are_audited_without_the_secret(self):
        """The audit line names the token (id, name) but never holds the token or its hash."""
        plain = self.limn("token", "create", "--state-dir", str(self.state), "--name", "ci").stdout.strip()
        self.limn("token", "revoke", "--state-dir", str(self.state), "ci")
        rows = audit_rows(self.state)
        self.assertEqual([(r["action"], r["via"], r["by"]["login"]) for r in rows],
                         [("token_created", "cli", os_login()), ("token_revoked", "cli", os_login())])
        self.assertEqual(rows[0]["details"]["name"], "ci")
        self.assertEqual(rows[0]["details"], rows[1]["details"])
        text = (self.state / "audit.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(plain, text)
        self.assertNotIn(ps.token_hash(plain), text)
        self.assertNotIn("sha256:", text)
        self.assertEqual(stat.S_IMODE((self.state / "audit.jsonl").stat().st_mode), 0o600)

    def test_member_add_role_change_and_remove_are_audited_with_the_previous_role(self):
        """Each membership change records who and the role before and after."""
        self.limn("member", "add", "--state-dir", str(self.state), "bob@example.com")
        self.limn("member", "role", "--state-dir", str(self.state), "bob@example.com", "owner")
        self.limn("member", "remove", "--state-dir", str(self.state), "bob@example.com")
        self.assertEqual([(r["action"], r["details"]) for r in audit_rows(self.state)], [
            ("member_added", {"login": "bob@example.com", "role": "editor"}),
            ("member_role", {"login": "bob@example.com", "role": "owner", "previous_role": "editor"}),
            ("member_removed", {"login": "bob@example.com", "previous_role": "owner"})])

    def test_changes_that_did_not_happen_are_not_audited(self):
        """Revoking an unknown token or changing an unknown member exits non-zero and writes nothing."""
        env = dict(os.environ, PYTHONPATH=str(SRC))
        for args in (("token", "revoke", "--state-dir", str(self.state), "nope"),
                     ("member", "role", "--state-dir", str(self.state), "nobody@example.com", "owner"),
                     ("member", "add", "--state-dir", str(self.state), "bad login")):
            r = subprocess.run([sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=60, env=env,
                               check=False)
            self.assertEqual(r.returncode, 1, (args, r.stdout, r.stderr))
        self.assertEqual(audit_rows(self.state), [])

    def test_python_helpers_audit_too(self):
        """The state helpers themselves write the line, so any caller of them is audited."""
        e, _ = ps.token_create(self.state, "bot")
        ps.member_add(self.state, "carol@example.com", "viewer")
        self.assertEqual([(r["action"], r["details"]) for r in audit_rows(self.state)],
                         [("token_created", {"id": e["id"], "name": "bot"}),
                          ("member_added", {"login": "carol@example.com", "role": "viewer"})])


if __name__ == "__main__":
    unittest.main()
