"""Regressions for the defects found by the end-to-end QA of v0.2.0 (fixed in v0.2.1).

A  a person already @-mentioned on a pin got no notification when tagged again.
B  POST /api/clear wiped every pin for editors and agents; a headerless request through tailscale serve (a tagged
   device, Host *.ts.net) was treated as the loopback agent.
Minors: pins.md claim instruction, the question nudge stealing focus, `limn member add` login validation, the
`member list` footnote, `limn serve` on a busy port, a readable 403 page, viewer-only UI, the section strip at the
top of page 1, and the `limn update` source.

Run: uv run pytest -q tests/test_qa_021.py
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse

from test_access import ALICE, BOB, CAROL, AccessBase, reset_access, talk_to
from test_server import add_pin, Base, edit_pin, extract_js_fn, ps, req, run_node, split_resp

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DAVE = {"Tailscale-User-Login": "dave@example.com", "Tailscale-User-Name": "Dave Choi"}
CLEAR_BODY = {"confirm": "clear all pins"}
TS_HOST = "box.tail1234.ts.net"


def actor(h):
    return {"login": h["Tailscale-User-Login"], "name": h["Tailscale-User-Name"]}


# ---------------------------------------------------------------- A. @mentions always notify

class MentionRules(Base):
    """Every explicit @mention in a new reply, reopen reason or note edit is a `mention` event for that person (never
    the author themself), whatever was mentioned before; everyone else involved gets `replied`; nobody gets both."""

    def setUp(self):
        super().setUp()
        ps._PEOPLE_SEEN.clear()
        ps._EVENTS_CACHE.clear()
        for h in (ALICE, BOB, CAROL, DAVE):
            ps.record_person(actor(h))
        self.A, self.B, self.C, self.D = (actor(h) for h in (ALICE, BOB, CAROL, DAVE))

    def events_after(self, n):
        return [(e["type"], sorted(e["to"])) for e in ps._read_events()[0][n:]]

    def n(self):
        return len(ps._read_events()[0])

    def test_first_mention_in_a_reply(self):
        pid = self.add(actor=self.A)
        n = self.n()
        ps.reply_pin(pid, "@Bob Park 봐 주세요", self.A)
        self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"])])

    def test_re_mention_in_a_second_reply_notifies_again(self):
        pid = self.add(actor=self.A)
        ps.reply_pin(pid, "@Bob Park 봐 주세요", self.A)
        n = self.n()
        ps.reply_pin(pid, "@Bob Park 다시 부름", self.A)
        self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"])])
        n = self.n()
        ps.reply_pin(pid, "태그 없는 답글", self.A)                       # no tag: Bob (mentioned before) gets replied
        self.assertEqual(self.events_after(n), [("replied", ["bob@example.com"])])

    def test_note_mention_then_reply_mention(self):
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 이 문단"}, self.A).record["id"]
        n = self.n()
        ps.reply_pin(pid, "@Bob Park 이것도 봐 주세요", self.C)
        self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"]), ("replied", ["alice@example.com"])])

    def test_self_mention_never_notifies_the_author(self):
        pid = self.add(actor=self.A)
        ps.reply_pin(pid, "@Bob Park 확인", self.A)
        n = self.n()
        ps.reply_pin(pid, "@Bob Park 제가 스스로 부름", self.B)             # Bob tags himself: nothing for Bob
        self.assertEqual(self.events_after(n), [("replied", ["alice@example.com"])])
        n = self.n()
        ps.reply_pin(pid, "@Alice Kim 나", self.A)                         # the pin author tags herself
        self.assertEqual(self.events_after(n), [("replied", ["bob@example.com"])])

    def test_mention_plus_other_participants_nobody_gets_both(self):
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Carol Lee 참고"}, self.A).record["id"]
        ps.reply_pin(pid, "@Bob Park 의견?", self.A)
        n = self.n()
        ps.reply_pin(pid, "@Bob Park @Carol Lee 둘 다 봐 주세요", self.D)
        evs = ps._read_events()[0][n:]
        self.assertEqual([(e["type"], sorted(e["to"])) for e in evs],
                         [("mention", ["bob@example.com", "carol@example.com"]), ("replied", ["alice@example.com"])])
        to = [lg for e in evs for lg in e["to"]]
        self.assertEqual(len(to), len(set(to)))                           # one event per person per reply

    def test_reopen_reason_re_mention_notifies(self):
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 부탁"}, self.A).record["id"]
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        n = self.n()
        ps.set_done(pid, False, self.C, reason="@Bob Park 다시 봐 주세요")
        self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"]), ("reopened", ["alice@example.com"])])
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        n = self.n()
        ps.set_done(pid, False, self.C, reason="@Alice Kim 확인 부탁")      # the author tagged: mention only, not also reopened
        self.assertEqual(self.events_after(n), [("mention", ["alice@example.com"])])

    def test_note_edit_that_tags_again_notifies_but_a_typo_fix_does_not(self):
        """A note edit notifies whoever it tags one more time; a typo fix next to an existing tag notifies nobody.

        v0.3.1 (issue #10 L3): tagging the same person again from the same pin's note by the same editor notifies at most
        once per NOTE_MENTION_COOLDOWN_S, so the re-tag below is made after the window (fake clock)."""
        from unittest import mock
        t0 = float(int(time.time()))                                       # whole seconds: ts is stored rounded to ms
        with mock.patch.object(ps.time, "time", return_value=t0):
            pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 이 문단 줄여 주세요"}, self.A).record["id"]
            n = self.n()
            edit_pin(pid, {"note": "@Bob Park 이 문단을 줄여 주세요", "base_rev": 0}, self.A)    # typo fix only
            self.assertEqual(self.events_after(n), [])
        with mock.patch.object(ps.time, "time", return_value=t0 + ps.NOTE_MENTION_COOLDOWN_S):
            edit_pin(pid, {"note_append": "@Bob Park 급합니다"}, self.A)                    # tags Bob again
            self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"])])
            n = self.n()
            edit_pin(pid, {"note": ps.find_pin(ps.snapshot_pins(), pid)["note"] + " @Carol Lee", "base_rev": 2}, self.A)
            self.assertEqual(self.events_after(n), [("mention", ["carol@example.com"])])


# ---------------------------------------------------------------- B. /api/clear and headerless tailnet requests

class ClearEndpoint(AccessBase):
    def setUp(self):
        super().setUp()
        ps._EVENTS_CACHE.clear()
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
                         {"login": "bob@example.com", "name": "Bob Park"},
                         {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"},
                         {"login": "dave@example.com", "name": "Dave Choi", "role": "agent"}])
        self.add()
        self.add(8, 9)

    def backups(self):
        return sorted(p.name for p in ps.C.state.glob("pins_*.jsonl.bak"))

    def assert_untouched(self):
        self.assertEqual(len(ps.snapshot_pins()), 2)
        self.assertEqual(self.backups(), [])

    def test_only_the_owner_may_clear(self):
        _, tok = ps.token_create(ps.C.state, "ci")
        refused = [("editor", dict(headers=BOB)), ("viewer", dict(headers=CAROL)), ("agent-role person", dict(headers=DAVE)),
                   ("token agent", dict(token=tok)), ("loopback agent", {}),
                   ("token over tailnet", dict(token=tok, headers={"Host": TS_HOST}))]
        for label, kw in refused:
            code, d = self.call("POST", "/api/clear", CLEAR_BODY, **kw)
            self.assertEqual(code, 403, (label, d))
        self.assert_untouched()

    def test_owner_needs_the_confirmation_phrase(self):
        for body in (None, {}, {"confirm": True}, {"confirm": "yes"}, {"confirm": "Clear All Pins"}):
            code, d = self.call("POST", "/api/clear", body, ALICE)
            self.assertEqual(code, 400, (body, d))
            self.assertIn("clear all pins", d["error"])
        self.assert_untouched()

    def test_owner_clear_keeps_a_backup_and_records_the_actor(self):
        code, d = self.call("POST", "/api/clear", CLEAR_BODY, ALICE)
        self.assertEqual(code, 200, d)
        self.assertTrue(d["ok"])
        self.assertEqual(d["cleared"], 2)
        self.assertEqual(ps.snapshot_pins(), [])
        self.assertEqual(self.backups(), [d["archive"]])
        rows = [json.loads(ln) for ln in (ps.C.state / d["archive"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["id"] for r in rows], [1, 2])
        ev = ps._read_events()[0][-1]
        self.assertEqual((ev["type"], ev["by"]["login"], ev["n"], ev["archive"]), ("cleared", "alice@example.com", 2, d["archive"]))
        self.assertEqual(ev["to"], [])
        self.assertEqual(self.add(), 3)                                    # ids keep counting

    def test_local_owner_may_clear(self):
        ps.C.auth, ps.C.agent_loopback, ps.C.local_user = "local", False, "alice"
        code, d = self.call("POST", "/api/clear", CLEAR_BODY)
        self.assertEqual((code, d.get("cleared")), (200, 2), d)


class PrincipalMatrix(AccessBase):
    """Every principal x entry path for read, pin, reply, close, confirm and clear."""

    OPS = ("read", "pin", "reply", "close", "confirm", "clear")

    def run_ops(self, **kw):
        """Status code of each operation for one principal (fresh pins per operation, so earlier ones do not interfere)."""
        out = {}
        out["read"] = self.call("GET", "/pins.md", **kw)[0]
        out["pin"] = self.call("POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "n"}, **kw)[0]
        pid = self.add()
        out["reply"] = self.call("POST", "/api/pins/%d/reply" % pid, {"text": "답"}, **kw)[0]
        pid = self.add()
        code, d = self.call("POST", "/api/pins/%d/close" % pid, None, **kw)
        out["close"] = code if code != 200 else d["state"]
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        out["confirm"] = self.call("POST", "/api/pins/%d/confirm" % pid, None, **kw)[0]
        before = len(ps.snapshot_pins())
        out["clear"] = self.call("POST", "/api/clear", CLEAR_BODY, **kw)[0]
        if out["clear"] != 200:
            self.assertEqual(len(ps.snapshot_pins()), before)
        return out

    def expect(self, got, **want):
        self.assertEqual(got, dict(zip(self.OPS, [want[k] for k in self.OPS], strict=True)))

    AGENT = dict(read=200, pin=200, reply=200, close="review", confirm=403, clear=403)
    EDITOR = dict(read=200, pin=200, reply=200, close="done", confirm=200, clear=403)
    OWNER = dict(read=200, pin=200, reply=200, close="done", confirm=200, clear=200)
    REFUSED_403 = dict(read=403, pin=403, reply=403, close=403, confirm=403, clear=403)
    REFUSED_401 = dict(read=401, pin=401, reply=401, close=401, confirm=401, clear=401)

    def test_loopback_headerless_is_the_agent(self):
        self.expect(self.run_ops(), **self.AGENT)

    def test_loopback_with_identity_headers(self):
        self.expect(self.run_ops(headers=BOB), **self.EDITOR)
        self.set_people([{"login": "alice@example.com", "name": "Alice", "role": "owner"}])
        self.expect(self.run_ops(headers=ALICE), **self.OWNER)

    def test_tailnet_with_identity_headers(self):
        self.expect(self.run_ops(headers=dict(BOB, Host=TS_HOST)), **self.EDITOR)
        self.set_people([{"login": "alice@example.com", "name": "Alice", "role": "owner"}])
        self.expect(self.run_ops(headers=dict(ALICE, Host=TS_HOST)), **self.OWNER)

    def test_tailnet_headerless_is_refused(self):
        self.expect(self.run_ops(headers={"Host": TS_HOST}), **self.REFUSED_403)
        code, d = self.call("GET", "/pins.md", headers={"Host": TS_HOST})
        self.assertIn("Bearer", d["error"])                               # tells the agent what to do instead
        self.expect(self.run_ops(headers={"Host": TS_HOST + ":18004"}), **self.REFUSED_403)

    def test_spoofed_loopback_host_through_the_proxy_is_refused(self):
        # tailscale serve routes by the TLS name and passes the client's Host through unchanged, so a tagged device can
        # send "Host: localhost". The proxy always sets X-Forwarded-For/-Host/-Proto (overwriting client values) - those,
        # not Host, tell that a request came through it.
        for extra in ({"X-Forwarded-For": "100.64.0.9"}, {"X-Forwarded-Host": TS_HOST}, {"X-Forwarded-Proto": "https"},
                      {"Forwarded": "for=100.64.0.9"}):
            for host in ("localhost", "127.0.0.1:1", "[::1]", "LOCALHOST."):
                h = dict(extra, Host=host)
                self.assertEqual(self.call("GET", "/pins.md", headers=h)[0], 403, h)
                pid = self.add()
                self.assertEqual(self.call("POST", "/api/pins/%d/drop" % pid, None, headers=h)[0], 403, h)
                self.assertIsNotNone(self.pin(pid))
        # the same forwarded headers with a person's identity or a token are fine
        self.assertEqual(self.call("GET", "/pins.md", headers=dict(BOB, Host=TS_HOST, **{"X-Forwarded-For": "100.64.0.9"}))[0], 200)
        _, tok = ps.token_create(ps.C.state, "ci")
        self.assertEqual(self.call("GET", "/pins.md", token=tok, headers={"Host": "localhost", "X-Forwarded-For": "100.64.0.9"})[0], 200)

    def test_opt_in_with_an_allowlist_refuses_forwarded_requests_too(self):
        ps.C.tailnet_agent = True
        self.assertEqual(self.call("GET", "/pins.md", headers={"Host": "localhost", "X-Forwarded-For": "100.64.0.9"})[0], 200)
        ps.C.allow = frozenset({"alice@example.com"})
        self.assertEqual(self.call("GET", "/pins.md", headers={"Host": "localhost", "X-Forwarded-For": "100.64.0.9"})[0], 403)
        self.assertEqual(self.call("GET", "/pins.md")[0], 200)                  # a real local agent is still fine

    def test_public_host_headerless_is_refused(self):
        ps.C.public_hosts = ps.parse_public_hosts(["limn.example.com"])
        self.expect(self.run_ops(headers={"Host": "limn.example.com"}), **self.REFUSED_403)

    def test_tailnet_headerless_opt_in_is_the_agent_again(self):
        ps.C.tailnet_agent = True
        self.expect(self.run_ops(headers={"Host": TS_HOST}), **self.AGENT)
        ps.C.allow = frozenset({"alice@example.com"})                     # an allowlist still refuses it, as in v0.1
        self.assertEqual(self.call("GET", "/pins.md", headers={"Host": TS_HOST})[0], 403)

    def test_bearer_token_over_loopback_and_tailnet(self):
        _, tok = ps.token_create(ps.C.state, "ci")
        self.expect(self.run_ops(token=tok), **self.AGENT)
        self.expect(self.run_ops(token=tok, headers={"Host": TS_HOST}), **self.AGENT)

    def test_trusted_proxy_peer_and_non_peer(self):
        ps.C.auth, ps.C.agent_loopback = "trusted-proxy", False
        ps.C.trusted_proxies = ps.parse_networks("10.0.0.1")
        h = {"X-Forwarded-User": "bob@example.com"}
        self.expect(self.run_ops(headers=h, peer="10.0.0.1"), **self.EDITOR)
        self.set_people([{"login": "alice@example.com", "name": "Alice", "role": "owner"}])
        self.expect(self.run_ops(headers={"X-Forwarded-User": "alice@example.com"}, peer="10.0.0.1"), **self.OWNER)
        self.expect(self.run_ops(headers=h, peer="10.0.0.9"), **self.REFUSED_401)
        self.expect(self.run_ops(peer="10.0.0.1"), **self.REFUSED_401)   # the proxy without a user header

    def test_loopback_agent_off_is_401_even_on_loopback(self):
        ps.C.agent_loopback = False
        self.expect(self.run_ops(), **self.REFUSED_401)


class ProxyHardening(AccessBase):
    """Security review follow-ups (L1, L2, L4)."""

    def test_more_proxy_markers_refuse_the_headerless_agent(self):
        for extra in ({"X-Real-IP": "100.64.0.9"}, {"Via": "1.1 proxy"}, {"X-Forwarded-Port": "443"},
                      {"X-Forwarded-Proto": "https"}, {"X-Forwarded-Host": TS_HOST}):
            h = dict(extra, Host="localhost")
            self.assertEqual(self.call("GET", "/pins.md", headers=h)[0], 403, h)
            self.assertEqual(self.call("POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 5}, h)[0], 403, h)
        self.assertEqual(self.call("GET", "/pins.md")[0], 200)                      # a real local agent

    def test_local_auth_refuses_proxied_requests(self):
        ps.C.auth, ps.C.agent_loopback, ps.C.local_user = "local", False, "alice"
        self.add()
        for h in ({"Host": TS_HOST, "X-Forwarded-For": "100.64.0.9"}, {"Host": "localhost", "X-Forwarded-For": "100.64.0.9"},
                  {"Host": "localhost", "X-Real-IP": "100.64.0.9"}):
            code, d = self.call("POST", "/api/clear", {"confirm": "clear all pins"}, h)
            self.assertEqual(code, 403, (h, d))
            self.assertEqual(self.call("GET", "/api/meta?light=1", headers=h)[0], 403, h)
        self.assertEqual(len(ps.snapshot_pins()), 1)
        code, d = self.call("GET", "/api/meta?light=1")                               # the owner at the keyboard
        self.assertEqual((code, d["me"]["role"]), (200, "owner"))
        _, tok = ps.token_create(ps.C.state, "ci")                                     # tokens still work through a proxy
        self.assertEqual(self.call("GET", "/pins.md", token=tok, headers={"Host": TS_HOST, "X-Forwarded-For": "1.2.3.4"})[0], 200)

    def test_people_json_is_written_0600(self):
        ps._PEOPLE_SEEN.clear()
        ps.record_person({"login": "bob@example.com", "name": "Bob"})
        self.assertEqual(ps.C.people_file.stat().st_mode & 0o777, 0o600)
        os.chmod(ps.C.people_file, 0o644)
        ps.member_add(ps.C.state, "carol@example.com")
        self.assertEqual(ps.C.people_file.stat().st_mode & 0o777, 0o600)

    def test_startup_tightens_a_group_or_world_writable_people_json(self):
        import io
        from unittest import mock
        ps.C.people_file.write_text('{"version": 1, "people": []}\n', encoding="utf-8")
        os.chmod(ps.C.people_file, 0o666)
        err = io.StringIO()
        with mock.patch.object(ps.sys, "stderr", err):
            ps.tighten_state_perms()
            ps.tighten_state_perms()
        self.assertEqual(ps.C.people_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len([ln for ln in err.getvalue().splitlines() if "tightened" in ln]), 1, err.getvalue())   # logged once
        os.chmod(ps.C.people_file, 0o644)                                              # only writable-by-others is changed
        ps.tighten_state_perms()
        self.assertEqual(ps.C.people_file.stat().st_mode & 0o777, 0o644)


class TailnetAgentStartup(AccessBase):
    def configure(self, *args):
        ps.configure_access(ps.build_arg_parser().parse_args(["--manuscript", "x", *args]))
        return ps.access_log_lines()

    def test_default_off_and_logged(self):
        log = self.configure()
        self.assertFalse(ps.C.tailnet_agent)
        self.assertIn("tailnet agent off", log[0])

    def test_opt_in_needs_the_loopback_agent(self):
        log = self.configure("--tailnet-agent")
        self.assertTrue(ps.C.tailnet_agent)
        self.assertIn("tailnet agent on (deprecated)", log[0])
        for args in (("--tailnet-agent", "--no-agent-loopback"), ("--tailnet-agent", "--auth", "local"),
                     ("--tailnet-agent", "--auth", "trusted-proxy")):
            with self.assertRaises(SystemExit) as cm:
                self.configure(*args)
            self.assertIn("--tailnet-agent", str(cm.exception.code))

    def test_instances_config_key(self):
        root = Path(self.tmp.name)
        cfg = root / "cfg"
        cfg.mkdir()
        (cfg / "paper.env").write_text("MANUSCRIPT=%s\nMAIN=main.tex\nPORT=19130\nSTATE_DIR=%s\nTAILNET_AGENT=1\n"
                                       % (self.src, ps.C.state), encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(SRC), LIMN_CONFIG_DIR=str(cfg), LIMN_PRINT_ARGV="1")
        r = subprocess.run([sys.executable, "-m", "limn", "run", "paper"], capture_output=True, text=True, timeout=60, env=env, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--tailnet-agent", r.stdout.splitlines())
        (cfg / "paper.env").write_text("MANUSCRIPT=%s\nMAIN=main.tex\nPORT=19130\nSTATE_DIR=%s\nTAILNET_AGENT=1\nAGENT_LOOPBACK=0\n"
                                       % (self.src, ps.C.state), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "limn", "run", "paper"], capture_output=True, text=True, timeout=60, env=env, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("TAILNET_AGENT", r.stderr)


# ---------------------------------------------------------------- pins.md: claim and remote-agent token instructions

class PinsMdInstructions(AccessBase):
    def test_claim_instruction_next_to_close(self):
        self.add()
        lines = ps.C.pins_md.read_text(encoding="utf-8").splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("처리한 핀은 닫는다"))
        self.assertIn("/api/pins/N/claim", lines[i + 1])
        self.assertIn('"eta_min"', lines[i + 1])
        self.assertEqual(lines[i + 1], ps.claim_guidance("http://127.0.0.1:18999"))
        self.assertEqual(lines[i + 2], ps.TOKEN_GUIDANCE)

    def test_remote_agents_are_told_to_use_a_token(self):
        self.add()
        _, tok = ps.token_create(ps.C.state, "ci")
        code, md = self.call("GET", "/pins.md", token=tok, headers={"Host": TS_HOST})
        self.assertEqual(code, 200)
        self.assertIn("https://%s/api/pins/N/claim" % TS_HOST, md)
        self.assertIn("테일넷 주소", ps.TOKEN_GUIDANCE)
        self.assertIn("403", ps.TOKEN_GUIDANCE)
        self.assertEqual(md.splitlines().count(ps.TOKEN_GUIDANCE), 1)


# ---------------------------------------------------------------- CLI: member add / list, serve on a busy port

def cli(*args, env=None):
    e = dict(os.environ, PYTHONPATH=str(SRC))
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=120, env=e, check=False)


class MemberCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def test_member_add_rejects_logins_the_server_would_refuse(self):
        for bad in ("bad login", " alice@example.com", "tab\tlogin", "local", "agent:x", ""):
            r = cli("member", "add", "--state-dir", str(self.state), bad)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("invalid login", r.stderr)
            self.assertFalse(ps.valid_login(bad), bad)
        r = cli("member", "add", "--state-dir", str(self.state), "alice@example.com")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_member_list_footnote_says_how_roles_get_recorded(self):
        self.state.mkdir(parents=True)
        (self.state / "people.json").write_text(json.dumps({"version": 1, "people": [
            {"login": "bob@example.com", "name": "Bob", "last_seen": "2026-09-25 10:00:00"}]}), encoding="utf-8")
        r = cli("member", "list", "--state-dir", str(self.state))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("recorded on first visit", r.stdout)
        self.assertIn("limn member role", r.stdout)


class ServeBusyPort(unittest.TestCase):
    def test_busy_port_is_a_one_line_error(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ms = Path(tmp.name) / "ms"
        ms.mkdir()
        (ms / "main.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}\n", encoding="utf-8")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        self.addCleanup(s.close)
        port = s.getsockname()[1]
        r = cli("serve", "--manuscript", str(ms), "--port", str(port), "--state-dir", str(Path(tmp.name) / "state"), "--no-build")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        err = [ln for ln in r.stderr.splitlines() if ln.strip()]
        self.assertEqual(len(err), 1, r.stderr)
        self.assertIn(str(port), err[0])
        self.assertIn("in use", err[0])


# ---------------------------------------------------------------- a readable 403 page

class ErrorPage(AccessBase):
    def test_members_only_refusal_is_a_readable_page(self):
        ps.C.members_only = True
        for lang, want in (("ko-KR,ko;q=0.9", "이 뷰어의 멤버가 아닙니다"), ("en-US,en;q=0.9", "not a member of this viewer")):
            code, hdrs, body = split_resp(talk_to(ps, req("GET", "/", b"", dict(CAROL, **{"Accept": "text/html",
                                                                                      "Accept-Language": lang}))))
            self.assertEqual(code, 403)
            self.assertTrue(hdrs["content-type"].startswith("text/html"), hdrs)
            text = body.decode("utf-8")
            self.assertIn("<html", text)
            self.assertIn(want, text)
            self.assertIn("carol@example.com", text)
            self.assertNotIn('{"error"', text)
        code, hdrs, _ = split_resp(talk_to(ps, req("GET", "/api/pins", b"", CAROL)))
        self.assertEqual((code, hdrs["content-type"].split(";")[0]), (403, "application/json"))   # the API stays JSON

    def test_page_escapes_the_login(self):
        ps.C.members_only = True
        h = {"Tailscale-User-Login": "<b>x</b>@example.com", "Tailscale-User-Name": "X", "Accept": "text/html"}
        _, _, body = split_resp(talk_to(ps, req("GET", "/", b"", h)))
        self.assertNotIn("<b>x</b>", body.decode("utf-8"))


# ---------------------------------------------------------------- the section strip at the top of page 1

class SectionStrip(unittest.TestCase):
    def run_js(self, body):
        out = run_node(extract_js_fn("outlineIndexAt") + "\n" + extract_js_fn("destFrac") + "\n" + body)
        if out is None:
            self.skipTest("node is not installed")
        return json.loads(out)

    def test_first_section_at_the_very_top(self):
        entries = [{"page": 1, "frac": 0.30}, {"page": 1, "frac": 0.55}, {"page": 1, "frac": 0.80},
                   {"page": 2, "frac": 0.10}, {"page": 4, "frac": 0.0}]
        js = "const E=%s;console.log(JSON.stringify([outlineIndexAt(E,1,0),outlineIndexAt(E,1,0.56),outlineIndexAt(E,1,0.95)," \
             "outlineIndexAt(E,2,0.05),outlineIndexAt(E,3,0.5),outlineIndexAt(E,4,0),outlineIndexAt([],1,0)]))" % json.dumps(entries)
        self.assertEqual(self.run_js(js), [0, 1, 2, 2, 3, 4, -1])

    def test_dest_top_to_fraction(self):
        js = "console.log(JSON.stringify([destFrac([{},{name:'XYZ'},72,792,0],792),destFrac([{},{name:'XYZ'},72,396,0],792)," \
             "destFrac([{},{name:'Fit'}],792),destFrac([{},{name:'XYZ'},0,null,0],792),destFrac([{},{name:'XYZ'},0,900,0],792)]))"
        self.assertEqual(self.run_js(js), [0, 0.5, 0, 0, 0])


# ---------------------------------------------------------------- update source

class UpdateSource(unittest.TestCase):
    def test_default_is_https_everywhere(self):
        sh = (SRC / "limn" / "instances.sh").read_text(encoding="utf-8")
        self.assertIn('REPO="${LIMN_REPO:-git+https://github.com/dartworklabs/limn}"', sh)
        text = (ROOT / "docs" / "handbook" / "instances.md").read_text(encoding="utf-8")
        row = next(ln for ln in text.splitlines() if ln.startswith("| `LIMN_REPO`"))
        self.assertIn("git+https://github.com/dartworklabs/limn", row)
        self.assertIn("0.1.0의 기본값은 `git+ssh://", text)                  # the note on the v0.1.0 ssh default


# ---------------------------------------------------------------- browser: viewer-only UI and the question nudge

TEX = "\\documentclass{article}\n\\begin{document}\n" + "".join("Line %d of the demo manuscript.\n" % i for i in range(3, 40)) + "\\end{document}\n"


class BrowserBase(unittest.TestCase):
    """The real viewer against the in-process server (same approach as test_i18n.EnglishChrome). /api/pick is answered
    with a computed pick result, since the test has no PDF or SyncTeX."""

    WHO = ALICE

    @classmethod
    def setUpClass(cls):
        required = os.environ.get("LIMN_TEST_REQUIRE_BROWSER") == "1"
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            if required:
                raise
            raise unittest.SkipTest("Playwright unavailable") from None
        cls.pw = sync_playwright().start()
        exe = os.environ.get("LIMN_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
        try:
            cls.browser = cls.pw.chromium.launch(executable_path=exe or None, args=["--no-sandbox"])
        except Exception as e:  # no bundled or system browser
            cls.pw.stop()
            if required:
                raise
            raise unittest.SkipTest("Chromium unavailable: %s" % e) from e
        cls.saved_html = ps.HTML
        ps.HTML = ps.build_html("Demo", "#2563eb")

    @classmethod
    def tearDownClass(cls):
        ps.HTML = cls.saved_html
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        from test_i18n import _png
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        src = root / "ms"
        src.mkdir()
        (src / "main.tex").write_text(TEX, encoding="utf-8")
        C = ps.C
        C.src, C.main = src, src / "main.tex"
        C.state = root / "state"
        C.state.mkdir()
        C.build = C.state / "build"
        C.port, C.dpi, C.timeout = 18999, 150, 60
        C.envs = tuple(ps.DEFAULT_ENVS.split(","))
        C.allow, C.origin_check, C.git_pull, C.pdfjs_dir = frozenset(), True, False, None
        C.label, C.accent, C.repo = "Demo", ps.ACCENT_PALETTE[0], None
        reset_access()
        ps._PEOPLE_SEEN.clear()
        ps.set_docs(None)
        ps.init_seq()
        pages = C.state / "pages-20260925100000"
        pages.mkdir()
        for i in (1, 2):
            (pages / ("page-%d.png" % i)).write_bytes(_png(1275, 1650))
        (C.state / "pages.cur").write_text(pages.name)
        (C.state / "built_at.txt").write_text("2026-09-25 10:00:00")
        (C.state / "head.txt").write_text("abc1234")
        self.main = C.main

    def tearDown(self):
        reset_access()
        self.tmp.cleanup()

    def talk(self, raw):
        return split_resp(talk_to(ps, raw))

    def route(self, route):
        rq = route.request
        u = urlparse(rq.url)
        if u.netloc != "viewer.test":
            return route.abort()
        if u.path == "/api/pick":
            lines = ps.tex_lines(self.main)
            lad = ps.compute_levels(lines, 5, 5, ps.C.envs)
            d = {"file": str(self.main), "name": "main.tex", "page": 1, "lo": lad["lo"], "hi": lad["hi"], "raw_lo": 5,
                 "raw_hi": 5, "kind": lad["kind"], "via": "synctex", "score": 1.0, "warn": "", "n_lines": len(lines),
                 "snippet": ps.snippet(lines, lad["lo"], lad["hi"]), "frac": [0.1, 0.1, 0.3, 0.05], "quote": "Line 5",
                 "levels": lad["levels"], "default_level": lad["default_level"], "overlaps": [],
                 "pdf_build": ps.cur_pages(ps.DOCS[0]).name}
            return route.fulfill(status=200, headers={"content-type": "application/json"}, body=json.dumps(d))
        body = rq.post_data_buffer or b""
        h = {"Host": "127.0.0.1:18999", "Tailscale-User-Login": self.WHO["Tailscale-User-Login"],
             "Tailscale-User-Name": self.WHO["Tailscale-User-Name"]}
        if rq.headers.get("content-type"):
            h["Content-Type"] = rq.headers["content-type"]
        if body:
            h["Content-Length"] = str(len(body))
        if rq.method == "POST":
            h["Origin"] = "http://127.0.0.1:18999"
        raw = ("%s %s HTTP/1.1\r\n" % (rq.method, u.path + ("?" + u.query if u.query else ""))
               + "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n").encode("latin-1") + body
        code, hdrs, data = self.talk(raw)
        route.fulfill(status=code, headers={"content-type": hdrs.get("content-type", "application/octet-stream")}, body=data)

    def open(self, n_open, lang="ko", init=None, **device):
        """Open the viewer in a new context and return the page once boot() has finished: the pin lists (open, review,
        done) are loaded and polling has started, with at least n_open open pins. init is an optional script run
        before the viewer's own.

        The wait is on LIGHT_TIMER, which boot() sets only after `await loadPins()`. META and the initial
        `OPEN_ALL=[]` are both set before that await, so waiting on them alone let a test act on a review or done
        pin that the viewer did not know yet (showChange() of an unknown pin does nothing, and nothing retries)."""
        context = self.browser.new_context(**(device or {"viewport": {"width": 1400, "height": 850}}))
        self.addCleanup(context.close)
        if init:
            context.add_init_script(init)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=%s" % lang)
        page.wait_for_function("typeof LIGHT_TIMER!=='undefined'&&LIGHT_TIMER!==null&&OPEN_ALL.length>=%d" % n_open,
                               timeout=20000)
        page.wait_for_timeout(300)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def open_composer(self, page):
        page.evaluate("LAST_PTR='mouse'; pick({page:1,x0:10,y0:10,x1:200,y1:60})")
        page.wait_for_selector("#composer:not([hidden])", timeout=8000)
        page.wait_for_function("CUR&&CUR.lo", timeout=8000)


# Makes the viewer's pin list (GET /api/pins?all=1) answer 1.5s late, as on a slow CI runner; other requests are untouched.
SLOW_PIN_LIST = ("(()=>{const f=window.fetch;window.fetch=function(u,o){const p=f.call(this,u,o);"
                 "return String(u).startsWith('/api/pins?all=1')?p.then(r=>new Promise(ok=>setTimeout(()=>ok(r),1500))):p;};})()")


class BrowserOpenWaitsForPins(BrowserBase):
    """BrowserBase.open returns only after the viewer knows every pin. The ScopedViewer flake (CI run 36216447363):
    open(0) returned once META was set, before boot() had loaded the pin lists; showChange() of a done pin then found
    no pin and did nothing, and the test timed out waiting for the diff."""

    WHO = ALICE

    def test_a_done_pin_is_known_when_open_returns_even_if_the_pin_list_is_slow(self):
        """With the pin list 1.5s late, the done pin is already in the viewer's lists when open(0) returns."""
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 4, "page": 1, "note": "done"}, actor(ALICE)).record["id"]
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), reply="fixed")
        page = self.open(0, init=SLOW_PIN_LIST)
        self.assertTrue(page.evaluate("findAnyPin(%d)!==null" % pid))


class QuestionNudgeFocus(BrowserBase):
    def test_ctrl_enter_saves_after_send_as_question(self):
        page = self.open(0)
        self.open_composer(page)
        page.click("#note")
        page.keyboard.type("이 값은 어디서 왔나요?")
        page.wait_for_selector("#c-qhint:not([hidden])")
        page.click('#c-qhint [data-act="kind"]')
        self.assertEqual(page.evaluate("document.activeElement.id"), "note")
        self.assertEqual(page.evaluate("KIND_NEW"), "question")
        page.keyboard.press("Control+Enter")
        page.wait_for_function("OPEN_ALL.length===1", timeout=8000)
        rows = ps.snapshot_pins()
        self.assertEqual([(r["note"], r.get("kind_req")) for r in rows], [("이 값은 어디서 왔나요?", "question")])

    def test_ctrl_enter_from_the_kind_buttons_still_saves(self):
        page = self.open(0)
        self.open_composer(page)
        page.click("#note")
        page.keyboard.type("표현 다듬기")
        page.click('#c-kind [data-kind="question"]')
        page.keyboard.press("Control+Enter")
        page.wait_for_function("OPEN_ALL.length===1", timeout=8000)


class ViewerRoleUi(BrowserBase):
    WHO = CAROL
    STATE_CHANGING = ("edit", "drop", "close", "reply-open", "rv-reopen", "confirm", "reopen", "restore", "unclaim")

    def setUp(self):
        super().setUp()
        ps.record_person(actor(ALICE))
        ps.C.people_file.write_text(json.dumps({"version": 1, "people": [
            {"login": "alice@example.com", "name": "Alice Kim"},
            {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"}]}), encoding="utf-8")
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "문단 줄이기"}, actor(ALICE)).record["id"]
        ps.reply_pin(pid, "답글", actor(ALICE))
        rid = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "검토할 핀"}, actor(ALICE)).record["id"]
        ps.set_done(rid, True, dict(ps.LOCAL_ACTOR), reply="고침")

    def visible_acts(self, page):
        return page.evaluate("[...document.querySelectorAll('[data-act]')].filter(e=>e.getClientRects().length&&!e.disabled)"
                             ".map(e=>e.dataset.act)")

    def test_viewer_sees_no_state_changing_controls(self):
        for name, device in (("desktop", {"viewport": {"width": 1400, "height": 850}}),
                             ("phone", {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True})):
            with self.subTest(device=name):
                page = self.open(1, **device)
                page.evaluate("setSide(true); OPEN_CARDS.add(1); drawPins()")
                page.wait_for_timeout(200)
                acts = self.visible_acts(page)
                self.assertIn("view", acts)                                 # reading still works
                self.assertEqual(sorted(set(acts) & set(self.STATE_CHANGING + ("rebuild",))), [], acts)
                self.open_composer(page)
                self.assertFalse(page.is_visible("#btn-save"))
                self.assertFalse(page.is_visible("#note"))
                self.assertTrue(page.is_visible("#c-viewer"))
                self.assertTrue(page.is_visible("#c-loc"))                  # the location is still shown (read)
                n = len(ps.snapshot_pins())
                page.keyboard.press("Control+Enter")
                page.evaluate("savePin()")
                page.wait_for_timeout(300)
                self.assertEqual(len(ps.snapshot_pins()), n)

    def test_viewer_notice_is_translated(self):
        page = self.open(1, lang="en")
        self.open_composer(page)
        text = page.inner_text("#c-viewer")
        self.assertFalse(re.search(r"[가-힣]", text), text)

    def test_editor_still_sees_them(self):
        type(self).WHO = ALICE
        try:
            page = self.open(1)
            page.evaluate("OPEN_CARDS.add(1); drawPins()")
            acts = self.visible_acts(page)
            for a in ("edit", "close", "reply-open", "rebuild"):
                self.assertIn(a, acts)
        finally:
            type(self).WHO = CAROL


if __name__ == "__main__":
    unittest.main()
