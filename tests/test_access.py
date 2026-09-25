"""Access control (v0.2): identity providers, agent API tokens, member roles, the bind rule, and the v0.1 migration.

Handler tests drive the real request handler over a socketpair (no port is opened), setting the TCP peer
explicitly to tell loopback from non-loopback clients. docs/adr/0002-access-control.md is the design.

Run: uv run pytest -q tests/test_access.py
Opt-in check against a copy of real state (never the live directory — the server writes):
    LIMN_TEST_STATE_COPY=<copy of a state dir> uv run pytest -q tests/test_access.py -k Migration
"""
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from test_server import TEX, Base, extract_js_fn, ps, req, run_node, split_resp

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

ALICE = {"Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Alice Kim"}
BOB = {"Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob Park"}
CAROL = {"Tailscale-User-Login": "carol@example.com", "Tailscale-User-Name": "Carol Lee"}

ACCESS_DEFAULTS = dict(auth="tailscale", agent_loopback=True, tailnet_agent=False, bind="127.0.0.1", public_hosts=(),
                       trusted_proxies=ps.Cfg.trusted_proxies, proxy_user_header="X-Forwarded-User",
                       proxy_name_header="X-Forwarded-Preferred-Username", proxy_email_header=None,
                       members_only=False, local_user=None, insecure=False)


def reset_access(mod=ps):
    """Access settings back to the v0.1-equivalent defaults (the Cfg object is shared by every test module)."""
    for k, v in ACCESS_DEFAULTS.items():
        setattr(mod.C, k, v)
    mod.C.allow = frozenset()
    mod._LOOPBACK_WARNED[0] = False
    mod._TOKENS_CACHE.update(key=None, rows=[])
    mod._ROLES_CACHE.update(key=None, roles={})


def talk_to(mod, raw: bytes, peer: str = "127.0.0.1") -> bytes:
    """One request over a socketpair to mod.Handler, from the given TCP peer address."""
    a, b = socket.socketpair()

    def serve():
        try:
            mod.Handler(b, (peer, 0), None)
        finally:
            b.close()
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    a.sendall(raw)
    a.shutdown(socket.SHUT_WR)
    a.settimeout(10)
    out = b""
    try:
        while True:
            chunk = a.recv(65536)
            if not chunk:
                break
            out += chunk
    finally:
        a.close()
    t.join(10)
    return out


class AccessBase(Base):
    def setUp(self):
        super().setUp()
        reset_access()
        ps._PEOPLE_SEEN.clear()

    def tearDown(self):
        reset_access()
        super().tearDown()

    def call(self, method, path, body=None, headers=None, peer="127.0.0.1", token=None):
        h = dict(headers or {})
        raw = b""
        if body is not None:
            raw = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if token is not None:
            h["Authorization"] = "Bearer %s" % token
        code, hdrs, out = split_resp(talk_to(ps, req(method, path, raw, h), peer))
        try:
            data = json.loads(out)
        except ValueError:
            data = out.decode("utf-8", "replace")
        self.last_headers = hdrs
        return code, data

    def pin_id(self, headers=None, token=None, lo=4, hi=5, peer="127.0.0.1"):
        code, d = self.call("POST", "/api/pin", {"file": str(self.main), "lo": lo, "hi": hi, "page": 1, "note": "n"},
                            headers, peer, token)
        self.assertEqual(code, 200, d)
        return d["id"]

    def people_file(self):
        return json.loads(ps.C.people_file.read_text(encoding="utf-8"))["people"] if ps.C.people_file.exists() else []

    def set_people(self, rows):
        ps.C.people_file.write_text(json.dumps({"version": 1, "people": rows}, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")


# ---------------------------------------------------------------- identity providers

class TailscaleProvider(AccessBase):
    def test_headers_trusted_from_loopback(self):
        code, d = self.call("GET", "/api/meta?light=1", headers=ALICE)
        self.assertEqual(code, 200)
        self.assertEqual((d["me"]["login"], d["me"]["name"], d["me"]["role"]), ("alice@example.com", "Alice Kim", "editor"))

    def test_headers_ignored_from_non_loopback_peer(self):
        code, d = self.call("GET", "/api/meta?light=1", headers=ALICE, peer="10.0.0.5")
        self.assertEqual(code, 401)
        self.assertIn("error", d)
        self.assertEqual(self.last_headers.get("www-authenticate"), 'Bearer realm="limn"')
        pid = self.add()
        code, _ = self.call("POST", "/api/pins/%d/close" % pid, headers=ALICE, peer="10.0.0.5")
        self.assertEqual(code, 401)
        self.assertFalse(self.pin(pid).get("done"))

    def test_ipv6_and_mapped_loopback_peers_are_loopback(self):
        for peer in ("::1", "::ffff:127.0.0.1"):
            code, d = self.call("GET", "/api/meta?light=1", headers=ALICE, peer=peer)
            self.assertEqual((code, d["me"]["login"]), (200, "alice@example.com"), peer)

    def test_loopback_agent_default_on_and_warned_once(self):
        err = io.StringIO()
        with mock.patch.object(ps.sys, "stderr", err):
            code, d = self.call("GET", "/api/meta?light=1")
            self.call("GET", "/api/pins")
            self.call("GET", "/pins.md")
        self.assertEqual(code, 200)
        self.assertEqual({k: d["me"][k] for k in ("login", "name")}, ps.LOCAL_ACTOR)
        self.assertEqual(d["me"]["role"], "agent")
        self.assertEqual(err.getvalue().count("deprecated"), 1, err.getvalue())
        self.assertIn("limn token create", err.getvalue())

    def test_agent_loopback_off_is_401(self):
        ps.C.agent_loopback = False
        code, d = self.call("GET", "/api/pins")
        self.assertEqual(code, 401)
        self.assertIn("Bearer", d["error"])
        code, _ = self.call("GET", "/api/pins", headers=ALICE)     # people keep working
        self.assertEqual(code, 200)

    def test_agent_logins_from_headers_are_refused(self):
        code, _ = self.call("GET", "/api/meta?light=1", headers={"Tailscale-User-Login": "agent:x"})
        self.assertEqual(code, 401)


class LocalProvider(AccessBase):
    def setUp(self):
        super().setUp()
        ps.C.auth, ps.C.agent_loopback, ps.C.local_user = "local", False, "alice"

    def test_loopback_is_the_owner_and_tailscale_headers_are_ignored(self):
        code, d = self.call("GET", "/api/meta?light=1", headers=BOB)
        self.assertEqual(code, 200)
        self.assertEqual((d["me"]["login"], d["me"]["name"], d["me"]["role"]), ("alice", "alice", "owner"))

    def test_owner_closes_as_done_and_can_confirm(self):
        pid = self.pin_id()
        code, d = self.call("POST", "/api/pins/%d/close" % pid)
        self.assertEqual((code, d["state"]), (200, "done"))
        rid = self.add(8, 9)
        ps.set_done(rid, True, dict(ps.LOCAL_ACTOR))                   # an agent's close -> review
        code, d = self.call("POST", "/api/pins/%d/confirm" % rid)
        self.assertEqual((code, d["state"]), (200, "done"))
        self.assertEqual(self.pin(rid)["confirmed_by"]["login"], "alice")

    def test_owner_recorded_as_owner(self):
        self.call("GET", "/")
        self.assertEqual([(p["login"], p.get("role")) for p in self.people_file()], [("alice", "owner")])

    def test_non_loopback_is_401_and_agents_use_tokens(self):
        self.assertEqual(self.call("GET", "/api/pins", peer="10.0.0.5")[0], 401)
        _, tok = ps.token_create(ps.C.state, "bot")
        code, d = self.call("GET", "/api/meta?light=1", token=tok)
        self.assertEqual((code, d["me"]["login"], d["me"]["role"]), (200, "agent:bot", "agent"))

    def test_default_owner_login_from_user(self):
        ps.C.local_user = None
        with mock.patch.dict(os.environ, {"USER": "dana"}):
            self.assertEqual(ps.local_owner_actor()["login"], "dana")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ps.local_owner_actor()["login"], "owner")


class TrustedProxyProvider(AccessBase):
    def setUp(self):
        super().setUp()
        ps.C.auth, ps.C.agent_loopback = "trusted-proxy", False
        ps.C.trusted_proxies = ps.parse_networks("10.0.0.1,192.168.5.0/24")

    def test_header_trusted_from_configured_proxy(self):
        h = {"X-Forwarded-User": "alice", "X-Forwarded-Preferred-Username": "Alice K"}
        for peer in ("10.0.0.1", "192.168.5.77"):
            code, d = self.call("GET", "/api/meta?light=1", headers=h, peer=peer)
            self.assertEqual((code, d["me"]["login"], d["me"]["name"], d["me"]["role"]), (200, "alice", "Alice K", "editor"))

    def test_other_peers_and_missing_header_are_401(self):
        h = {"X-Forwarded-User": "alice"}
        self.assertEqual(self.call("GET", "/api/pins", headers=h, peer="10.0.0.9")[0], 401)
        self.assertEqual(self.call("GET", "/api/pins", headers=h, peer="127.0.0.1")[0], 401)   # loopback is not in the list here
        self.assertEqual(self.call("GET", "/api/pins", peer="10.0.0.1")[0], 401)               # the proxy, but no user
        self.assertEqual(self.call("GET", "/api/pins", headers=ALICE, peer="127.0.0.1")[0], 401)  # tailscale headers mean nothing

    def test_custom_header_names_and_email_as_login(self):
        ps.C.proxy_user_header, ps.C.proxy_name_header, ps.C.proxy_email_header = "X-Auth-User", "X-Auth-Name", "X-Auth-Email"
        h = {"X-Auth-User": "u123", "X-Auth-Name": "Alice", "X-Auth-Email": "alice@example.com", "X-Forwarded-User": "mallory"}
        code, d = self.call("GET", "/api/meta?light=1", headers=h, peer="10.0.0.1")
        self.assertEqual((code, d["me"]["login"], d["me"]["name"]), (200, "alice@example.com", "Alice"))
        code, d = self.call("GET", "/api/meta?light=1", headers={"X-Auth-User": "u123"}, peer="10.0.0.1")
        self.assertEqual((code, d["me"]["login"]), (200, "u123"))                    # no e-mail -> the user header
        self.assertEqual(self.call("GET", "/api/pins", headers={"X-Forwarded-User": "mallory"}, peer="10.0.0.1")[0], 401)

    def test_proxy_person_pins_and_is_recorded(self):
        h = {"X-Forwarded-User": "alice@example.com"}
        pid = self.pin_id(h, peer="10.0.0.1")
        self.assertEqual(self.pin(pid)["author"]["login"], "alice@example.com")
        self.assertEqual([p["login"] for p in self.people_file()], ["alice@example.com"])

    def test_members_only_applies_to_proxy_users(self):
        ps.C.members_only = True
        self.set_people([{"login": "alice@example.com", "name": "Alice"}])
        self.assertEqual(self.call("GET", "/api/pins", headers={"X-Forwarded-User": "alice@example.com"}, peer="10.0.0.1")[0], 200)
        self.assertEqual(self.call("GET", "/api/pins", headers={"X-Forwarded-User": "eve@example.com"}, peer="10.0.0.1")[0], 403)

    def test_tokens_work_from_anywhere(self):
        _, tok = ps.token_create(ps.C.state, "ci")
        code, d = self.call("GET", "/api/meta?light=1", token=tok, peer="203.0.113.9")
        self.assertEqual((code, d["me"]["login"]), (200, "agent:ci"))


# ---------------------------------------------------------------- startup rules: bind, loopback agent

class StartupRules(AccessBase):
    def configure(self, *args):
        a = ps.build_arg_parser().parse_args(["--manuscript", "x", *args])
        ps.configure_access(a)
        return ps.access_log_lines()

    def refused(self, *args):
        with self.assertRaises(SystemExit) as cm:
            self.configure(*args)
        self.assertIsInstance(cm.exception.code, str)                 # a message, not a bare exit code
        return cm.exception.code

    def test_defaults_are_v01(self):
        log = self.configure()
        self.assertEqual((ps.C.auth, ps.C.agent_loopback, ps.C.bind, ps.C.members_only), ("tailscale", True, "127.0.0.1", False))
        self.assertEqual(log[0], "auth        tailscale · tokens 0 · loopback agent on (deprecated) · tailnet agent off · "
                                 "members-only off")
        self.assertTrue(any(l.startswith("warning     ") and "deprecated" in l for l in log))

    def test_no_agent_loopback(self):
        self.configure("--no-agent-loopback")
        self.assertFalse(ps.C.agent_loopback)
        self.assertIn("loopback agent off", self.configure("--no-agent-loopback")[0])

    def test_loopback_agent_forced_off_and_explicit_request_refused(self):
        self.configure("--auth", "trusted-proxy")
        self.assertFalse(ps.C.agent_loopback)
        self.configure("--auth", "local")
        self.assertFalse(ps.C.agent_loopback)
        self.assertIn("--agent-loopback", self.refused("--auth", "trusted-proxy", "--agent-loopback"))
        self.assertIn("--agent-loopback", self.refused("--auth", "local", "--agent-loopback"))
        self.assertIn("--agent-loopback", self.refused("--bind", "0.0.0.0", "--i-know-this-is-insecure", "--agent-loopback"))
        self.configure("--agent-loopback")
        self.assertTrue(ps.C.agent_loopback)

    def test_non_loopback_bind_refused_unless_trusted_proxy_or_insecure(self):
        for auth in ("tailscale", "local"):
            msg = self.refused("--auth", auth, "--bind", "0.0.0.0")
            self.assertIn("--i-know-this-is-insecure", msg)
        log = self.configure("--auth", "trusted-proxy", "--bind", "0.0.0.0")
        self.assertTrue(any(l.startswith("warning     bound to 0.0.0.0") and "trusted-proxy" in l for l in log), log)
        self.assertFalse(any("!!!" in l for l in log))
        log = self.configure("--bind", "0.0.0.0", "--i-know-this-is-insecure")
        self.assertFalse(ps.C.agent_loopback)                          # forced off on a non-loopback bind
        self.assertTrue(any("!!!" in l and "--i-know-this-is-insecure" in l for l in log), log)
        self.assertTrue(any(l.startswith("warning     bound to 0.0.0.0") and "tailscale" in l for l in log))

    def test_loopback_binds_are_fine(self):
        for b in ("127.0.0.1", "127.0.0.2", "::1", "localhost"):
            self.configure("--bind", b)
            self.assertTrue(ps.C.agent_loopback, b)
        self.refused("--bind", "example.com")

    def test_invalid_values_refused(self):
        self.refused("--trusted-proxies", "proxy.example.com")
        self.refused("--public-host", "https://x.example.com/")
        self.refused("--proxy-user-header", "X User")
        self.refused("--local-user", "agent:me")

    def test_auth_line_counts_tokens_and_members_only(self):
        ps.C.state = Path(self.tmp.name) / "state"
        ps.token_create(ps.C.state, "a")
        ps.token_create(ps.C.state, "b")
        log = self.configure("--auth", "local", "--local-user", "alice", "--members-only")
        self.assertEqual(log[0], "auth        local · owner alice · tokens 2 · loopback agent off · members-only on")


# ---------------------------------------------------------------- agent API tokens

class Tokens(AccessBase):
    def test_store_hashes_at_rest_0600_and_lists(self):
        e1, t1 = ps.token_create(ps.C.state)
        e2, t2 = ps.token_create(ps.C.state)
        self.assertEqual((e1["name"], e2["name"]), ("agent", "agent-2"))
        self.assertTrue(t1.startswith("limn_") and len(t1) > 40)
        raw = ps.C.tokens_file.read_text(encoding="utf-8")
        self.assertNotIn(t1, raw)
        self.assertNotIn(t1[len("limn_"):], raw)
        self.assertEqual(stat.S_IMODE(ps.C.tokens_file.stat().st_mode), 0o600)
        d = json.loads(raw)
        self.assertEqual(d["version"], 1)
        self.assertEqual([t["hash"] for t in d["tokens"]], [ps.token_hash(t1), ps.token_hash(t2)])
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{8}", t["id"]) and re.fullmatch(r"sha256:[0-9a-f]{64}", t["hash"])
                            and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", t["created"]) for t in d["tokens"]))
        self.assertEqual([t["name"] for t in ps.load_tokens(ps.C.state)], ["agent", "agent-2"])
        with self.assertRaises(ValueError):
            ps.token_create(ps.C.state, "agent")                      # names are unique
        with self.assertRaises(ValueError):
            ps.token_create(ps.C.state, "bad name")
        self.assertEqual(ps.token_revoke(ps.C.state, e1["id"])["name"], "agent")   # by id
        self.assertEqual(ps.token_revoke(ps.C.state, "agent-2")["id"], e2["id"])   # by name
        self.assertIsNone(ps.token_revoke(ps.C.state, "agent-2"))
        self.assertEqual(ps.load_tokens(ps.C.state), [])
        self.assertEqual(stat.S_IMODE(ps.C.tokens_file.stat().st_mode), 0o600)

    def test_token_principal_is_an_agent(self):
        _, tok = ps.token_create(ps.C.state, "ci")
        code, d = self.call("GET", "/api/meta?light=1", token=tok, headers=ALICE)   # a valid token wins over headers
        self.assertEqual(d["me"], {"login": "agent:ci", "name": "ci", "role": "agent"})
        pid = self.pin_id(token=tok)
        self.assertEqual(self.pin(pid)["author"], {"login": "agent:ci", "name": "ci"})
        code, d = self.call("POST", "/api/pins/%d/close" % pid, {"reply": "고침"}, token=tok)
        self.assertEqual((code, d["state"]), (200, "review"))
        code, d = self.call("POST", "/api/pins/%d/confirm" % pid, token=tok)
        self.assertEqual(code, 403)
        self.assertEqual(ps.pin_state(self.pin(pid)), "review")
        self.call("GET", "/", token=tok)
        self.assertEqual(self.people_file(), [])                        # never recorded in people.json
        code, d = self.call("GET", "/api/people", token=tok)
        self.assertNotIn("agent:ci", [p["login"] for p in d["people"]])
        self.assertTrue(ps.is_agent({"login": "agent:ci"}) and ps.is_agent(dict(ps.LOCAL_ACTOR)))
        self.assertFalse(ps.is_agent({"login": "alice@example.com"}))

    def test_revoked_token_is_401_without_restart(self):
        e, tok = ps.token_create(ps.C.state, "ci")
        self.assertEqual(self.call("GET", "/api/pins", token=tok)[0], 200)
        ps.token_revoke(ps.C.state, e["id"])
        code, d = self.call("GET", "/api/pins", token=tok)
        self.assertEqual(code, 401)
        self.assertIn("error", d)
        _, tok2 = ps.token_create(ps.C.state, "ci")                     # a new token is accepted without restart too
        self.assertEqual(self.call("GET", "/api/pins", token=tok2)[0], 200)

    def test_invalid_token_never_falls_back(self):
        pid = self.add()
        for bad in ("limn_nope", "x"):
            self.assertEqual(self.call("GET", "/api/pins", token=bad)[0], 401)
            self.assertEqual(self.call("POST", "/api/pins/%d/close" % pid, token=bad, headers=ALICE)[0], 401)
        self.assertFalse(self.pin(pid).get("done"))
        self.assertEqual(self.call("GET", "/api/pins", headers={"Authorization": "Bearer "})[0], 401)
        self.assertEqual(self.call("GET", "/api/pins", headers={"Authorization": "Basic YTpi"})[0], 200)   # not ours: ignored

    def test_token_file_is_reread_when_it_changes(self):
        self.assertEqual(ps.current_tokens(), [])
        _, tok = ps.token_create(ps.C.state, "ci")
        self.assertEqual(ps.token_lookup(tok)["name"], "ci")
        ps.C.tokens_file.write_text("{broken", encoding="utf-8")        # unreadable -> no token accepted (fail closed)
        with mock.patch.object(ps.sys, "stderr", io.StringIO()):
            self.assertIsNone(ps.token_lookup(tok))
        with self.assertRaises(ValueError):                            # and the CLI refuses to overwrite it
            ps.token_create(ps.C.state, "x")

    def cli(self, *args, env=None):
        e = dict(os.environ, PYTHONPATH=str(SRC))
        e.update(env or {})
        return subprocess.run([sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=60, env=e)

    def test_cli_create_list_revoke(self):
        root = Path(self.tmp.name)
        cfg, data = root / "cfg", root / "data"
        cfg.mkdir()
        (cfg / "paper.env").write_text("MANUSCRIPT=%s\nSTATE_DIR=\"%s\"\n" % (self.src, root / "st"), encoding="utf-8")
        (cfg / "other.env").write_text("MANUSCRIPT=%s\n" % self.src, encoding="utf-8")   # no STATE_DIR -> data root
        env = {"LIMN_CONFIG_DIR": str(cfg), "LIMN_DATA_ROOT": str(data)}
        r = self.cli("token", "create", "paper", "--name", "ci", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        tok = r.stdout.strip()
        self.assertTrue(tok.startswith("limn_") and "\n" not in tok)
        self.assertIn("only time", r.stderr)
        tf = root / "st" / "tokens.json"
        self.assertNotIn(tok, tf.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(tf.stat().st_mode), 0o600)
        r = self.cli("token", "list", "paper", env=env)
        self.assertIn(" ci ", r.stdout)
        self.assertNotIn(tok, r.stdout)
        self.assertEqual(self.cli("token", "revoke", "paper", "ci", env=env).returncode, 0)
        self.assertEqual(json.loads(tf.read_text(encoding="utf-8"))["tokens"], [])
        self.assertNotEqual(self.cli("token", "revoke", "paper", "ci", env=env).returncode, 0)
        r = self.cli("token", "create", "other", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((data / "other" / "tokens.json").exists())
        r = self.cli("token", "create", "--state-dir", str(root / "plain"), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((root / "plain" / "tokens.json").exists())
        r = self.cli("token", "list", "missing", env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no config found", r.stderr)

    def test_cli_env_parsing_matches_instances_sh(self):
        from importlib import import_module
        sys.path.insert(0, str(SRC))
        try:
            cli = import_module("limn.cli")
        finally:
            sys.path.remove(str(SRC))
        f = Path(self.tmp.name) / "x.env"
        f.write_text("# STATE_DIR=/no\n  STATE_DIR='/a b'  \r\nOTHER=1\nSTATE_DIR=\"/c\"\n", encoding="utf-8")
        self.assertEqual(cli.env_get(f, "STATE_DIR"), "/c")          # the last line wins
        f.write_text("STATE_DIR='/a b'  \r\n", encoding="utf-8")
        self.assertEqual(cli.env_get(f, "STATE_DIR"), "/a b")
        self.assertIsNone(cli.env_get(f, "NOPE"))
        bash = shutil.which("bash")
        if bash:                                                       # the same answer as instances.sh's env_get
            script = 'source <(sed -n "/^env_get()/,/^}/p" "$1"); env_get "$2" STATE_DIR'
            out = subprocess.run([bash, "-c", script, "x", str(SRC / "limn" / "instances.sh"), str(f)],
                                 capture_output=True, text=True, timeout=30).stdout.strip()
            self.assertEqual(out, "/a b")


# ---------------------------------------------------------------- roles and admission

class Roles(AccessBase):
    VIEWER_REFUSED = [("/api/pin", {"file": None, "lo": 4, "hi": 5}), ("/api/pins/{id}/reply", {"text": "x"}),
                      ("/api/pins/{id}/close", None), ("/api/pins/{id}/reopen", None),
                      ("/api/pins/{id}/edit", {"note": "x", "base_rev": 0}), ("/api/pins/{id}/claim", None),
                      ("/api/pins/{id}/unclaim", None), ("/api/pins/{id}/drop", None),
                      ("/api/pins/{id}/restore", None), ("/api/pins/{id}/confirm", None),
                      ("/api/rebuild?async=1", None), ("/api/clear", None)]

    def test_viewer_is_refused_every_state_change(self):
        self.set_people([{"login": "bob@example.com", "name": "Bob", "role": "viewer"}])
        pid = self.add()
        before = ps.C.pins_jsonl.read_bytes()
        for path, body in self.VIEWER_REFUSED:
            if body is not None and "file" in body:
                body = dict(body, file=str(self.main))
            code, d = self.call("POST", path.format(id=pid), body, BOB)
            self.assertEqual(code, 403, (path, d))
        self.assertEqual(ps.C.pins_jsonl.read_bytes(), before)
        self.assertEqual(self.call("GET", "/api/pins", headers=BOB)[0], 200)
        self.assertEqual(self.call("GET", "/pins.md", headers=BOB)[0], 200)
        code, d = self.call("GET", "/api/meta", headers=BOB)
        self.assertEqual((code, d["me"]["role"]), (200, "viewer"))
        code, d = self.call("POST", "/api/pick", {"page": 1, "x0": 0, "y0": 0, "x1": 1, "y1": 1}, BOB)
        self.assertNotEqual(code, 403, d)                              # a computation, not a change
        code, d = self.call("POST", "/api/revision-build", {"commit": "0" * 40}, BOB)
        self.assertNotEqual(code, 403, d)

    def test_editor_and_missing_role_can_do_everything(self):
        self.set_people([{"login": "alice@example.com", "name": "Alice"},
                         {"login": "bob@example.com", "name": "Bob", "role": "editor"}])
        for h in (ALICE, BOB):
            pid = self.pin_id(h)
            self.assertEqual(self.call("POST", "/api/pins/%d/reply" % pid, {"text": "x"}, h)[0], 200)
            self.assertEqual(self.call("POST", "/api/pins/%d/close" % pid, None, h)[1]["state"], "done")
            rid = self.add(8, 9)
            ps.set_done(rid, True, dict(ps.LOCAL_ACTOR))
            self.assertEqual(self.call("POST", "/api/pins/%d/confirm" % rid, None, h)[1]["state"], "done")

    def test_owner_person_can_confirm(self):
        self.set_people([{"login": "alice@example.com", "name": "Alice", "role": "owner"}])
        rid = self.add()
        ps.set_done(rid, True, dict(ps.LOCAL_ACTOR))
        self.assertEqual(self.call("POST", "/api/pins/%d/confirm" % rid, None, ALICE)[1]["state"], "done")

    def test_agent_role_person_closes_into_review_and_cannot_confirm(self):
        self.set_people([{"login": "bob@example.com", "name": "Bob", "role": "agent"}])
        pid = self.pin_id(BOB)
        code, d = self.call("POST", "/api/pins/%d/close" % pid, None, BOB)
        self.assertEqual((code, d["state"]), (200, "review"))
        code, _ = self.call("POST", "/api/pins/%d/confirm" % pid, None, BOB)
        self.assertEqual(code, 403)
        code, d = self.call("POST", "/api/pins/%d/reopen" % pid, None, BOB)
        self.assertEqual(code, 200)
        code, d = self.call("POST", "/api/pins/%d/close" % pid, {"review": False}, BOB)   # an explicit body still wins
        self.assertEqual(d["state"], "done")

    def test_loopback_agent_confirm_is_403(self):
        rid = self.add()
        ps.set_done(rid, True, dict(ps.LOCAL_ACTOR))
        code, d = self.call("POST", "/api/pins/%d/confirm" % rid)
        self.assertEqual(code, 403)
        self.assertEqual(d["error"], ps.CONFIRM_BY_HUMAN)

    def test_role_changes_apply_without_restart(self):
        self.call("GET", "/", headers=BOB)                              # auto-added, no role
        pid = self.add()
        self.assertEqual(self.call("POST", "/api/pins/%d/reply" % pid, {"text": "a"}, BOB)[0], 200)
        ps.member_set_role(ps.C.state, "bob@example.com", "viewer")
        self.assertEqual(self.call("POST", "/api/pins/%d/reply" % pid, {"text": "b"}, BOB)[0], 403)
        ps.member_set_role(ps.C.state, "bob@example.com", "editor")
        self.assertEqual(self.call("POST", "/api/pins/%d/reply" % pid, {"text": "c"}, BOB)[0], 200)

    def test_unknown_role_value_is_viewer(self):
        self.set_people([{"login": "bob@example.com", "name": "Bob", "role": "admin"}])
        self.assertEqual(ps.role_of("bob@example.com"), "viewer")
        self.assertEqual(self.call("POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 4}, BOB)[0], 403)

    def test_record_person_preserves_role(self):
        self.set_people([{"login": "bob@example.com", "name": "Bob", "role": "viewer", "first_seen": "2026-09-01 10:00:00",
                          "last_seen": "2026-09-01 10:00:00"}])
        self.assertTrue(ps.record_person({"login": "bob@example.com", "name": "Bob P."}, now=10 ** 9 * 2))
        p = self.people_file()[0]
        self.assertEqual((p["role"], p["name"], p["first_seen"]), ("viewer", "Bob P.", "2026-09-01 10:00:00"))

    def test_people_api_and_meta_carry_roles(self):
        self.set_people([{"login": "alice@example.com", "name": "Alice", "role": "owner"},
                         {"login": "bob@example.com", "name": "Bob"}])
        code, d = self.call("GET", "/api/people", headers=ALICE)
        self.assertEqual({p["login"]: p["role"] for p in d["people"]}, {"alice@example.com": "owner", "bob@example.com": "editor"})
        self.assertEqual(d["me"]["role"], "owner")
        code, d = self.call("GET", "/api/meta", headers=BOB)
        self.assertEqual(d["me"]["role"], "editor")

    def test_member_store_add_list_remove_role(self):
        e = ps.member_add(ps.C.state, "alice@example.com", "viewer")
        self.assertEqual(e, {"login": "alice@example.com", "name": "alice", "role": "viewer"})
        ps.member_add(ps.C.state, "bob@example.com", name="Bob Park")
        with self.assertRaises(ValueError):
            ps.member_add(ps.C.state, "bob@example.com")
        for bad in ("", "local", "agent:x", " a"):
            with self.assertRaises(ValueError):
                ps.member_add(ps.C.state, bad)
        with self.assertRaises(ValueError):
            ps.member_add(ps.C.state, "carol@example.com", "admin")
        self.assertEqual([(p["login"], p["role"]) for p in ps.load_people_file(ps.C.state)],
                         [("alice@example.com", "viewer"), ("bob@example.com", "editor")])
        self.assertEqual(ps.member_set_role(ps.C.state, "alice@example.com", "owner")["role"], "owner")
        self.assertIsNone(ps.member_set_role(ps.C.state, "nobody@example.com", "owner"))
        self.assertEqual(ps.member_remove(ps.C.state, "bob@example.com")["login"], "bob@example.com")
        self.assertIsNone(ps.member_remove(ps.C.state, "bob@example.com"))
        d = json.loads(ps.C.people_file.read_text(encoding="utf-8"))
        self.assertEqual(d, {"version": 1, "people": [{"login": "alice@example.com", "name": "alice", "role": "owner"}]})
        ps.C.people_file.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):                            # never overwrite a file we could not read
            ps.member_add(ps.C.state, "dan@example.com")
        self.assertEqual(ps.C.people_file.read_text(encoding="utf-8"), "{broken")

    def test_member_cli(self):
        e = dict(os.environ, PYTHONPATH=str(SRC))
        st = str(ps.C.state)

        def cli(*a):
            return subprocess.run([sys.executable, "-m", "limn", "member", *a], capture_output=True, text=True, timeout=60, env=e)
        self.assertEqual(cli("add", "--state-dir", st, "alice@example.com", "--role", "viewer").returncode, 0)
        self.assertEqual(cli("add", "--state-dir", st, "bob@example.com", "--name", "Bob Park").returncode, 0)
        self.assertNotEqual(cli("add", "--state-dir", st, "bob@example.com").returncode, 0)
        self.assertNotEqual(cli("add", "--state-dir", st, "x@example.com", "--role", "admin").returncode, 0)
        self.assertEqual(cli("role", "--state-dir", st, "alice@example.com", "editor").returncode, 0)
        self.assertNotEqual(cli("role", "--state-dir", st, "nobody@example.com", "editor").returncode, 0)
        self.assertEqual(cli("remove", "--state-dir", st, "bob@example.com").returncode, 0)
        r = cli("list", "--state-dir", st)
        self.assertRegex(r.stdout, r"alice@example\.com +editor ")
        self.assertNotIn("bob@example.com", r.stdout)
        self.assertEqual(ps.role_of("alice@example.com"), "editor")   # the server sees it at once


class Admission(AccessBase):
    def test_tailscale_default_policy_is_open_with_attribution(self):
        """Owner policy: with no AUTH and no allowlist, anyone on the tailnet may do everything that works in v0.1,
        attributed to their login; a never-seen person is recorded as an editor with no role field written."""
        self.assertEqual(self.call("GET", "/", headers=CAROL)[0], 200)
        pid = self.pin_id(CAROL)
        self.assertEqual(self.pin(pid)["author"], {"login": "carol@example.com", "name": "Carol Lee"})
        self.assertEqual(self.call("POST", "/api/pins/%d/reply" % pid, {"text": "보충"}, CAROL)[0], 200)
        code, d = self.call("POST", "/api/pins/%d/close" % pid, {"reply": "고침"}, CAROL)
        self.assertEqual((code, d["state"]), (200, "done"))              # a person closing is the reviewer
        rid = self.add(8, 9)
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % rid)[1]["state"], "review")   # the agent's close
        code, d = self.call("POST", "/api/pins/%d/confirm" % rid, None, CAROL)
        self.assertEqual((code, d["state"]), (200, "done"))
        self.assertEqual(self.pin(rid)["confirmed_by"]["login"], "carol@example.com")
        people = self.people_file()
        self.assertEqual([p["login"] for p in people], ["carol@example.com"])
        self.assertNotIn("role", people[0])
        self.assertEqual(ps.role_of("carol@example.com"), "editor")

    def test_members_only_admits_listed_people(self):
        ps.C.members_only = True
        self.set_people([{"login": "alice@example.com", "name": "Alice"}])
        self.assertEqual(self.call("GET", "/", headers=ALICE)[0], 200)
        code, d = self.call("GET", "/", headers=CAROL)
        self.assertEqual(code, 403)
        self.assertIn("limn member add", d["error"])
        self.assertEqual(self.call("POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 4}, CAROL)[0], 403)
        self.assertEqual([p["login"] for p in self.people_file()], ["alice@example.com"])   # not recorded
        ps.C.allow = frozenset({"carol@example.com"})                  # --allow logins are admitted too
        self.assertEqual(self.call("GET", "/", headers=CAROL)[0], 200)
        ps.member_add(ps.C.state, "bob@example.com")                   # a new member is admitted on the next request
        self.assertEqual(self.call("GET", "/api/pins", headers=BOB)[0], 200)
        ps.member_remove(ps.C.state, "bob@example.com")
        self.assertEqual(self.call("GET", "/api/pins", headers=BOB)[0], 403)

    def test_members_only_keeps_agents(self):
        ps.C.members_only = True
        self.assertEqual(self.call("GET", "/api/pins")[0], 200)          # loopback agent
        _, tok = ps.token_create(ps.C.state, "ci")
        self.assertEqual(self.call("GET", "/api/pins", token=tok)[0], 200)
        code, _ = self.call("GET", "/api/pins", headers={"Host": "box.tail1234.ts.net"})   # tagged device
        self.assertEqual(code, 403)

    def test_allow_keeps_v01_semantics(self):
        ps.C.allow = frozenset({"alice@example.com"})
        self.set_people([{"login": "bob@example.com", "name": "Bob"}])
        self.assertEqual(self.call("GET", "/api/pins", headers=ALICE)[0], 200)
        code, d = self.call("GET", "/api/pins", headers=BOB)             # in people.json but not in --allow
        self.assertEqual(code, 403)
        self.assertIn("허용되지 않은 계정", d["error"])
        self.assertEqual(self.call("GET", "/api/pins")[0], 200)
        self.assertEqual(self.call("GET", "/api/pins", headers={"Host": "box.tail1234.ts.net"})[0], 403)


# ---------------------------------------------------------------- Host/Origin with --public-host

class PublicHost(AccessBase):
    def setUp(self):
        super().setUp()
        ps.C.public_hosts = ps.parse_public_hosts(["limn.example.com", "alt.example.com:8443"])

    def test_parse(self):
        self.assertEqual(ps.C.public_hosts, (("limn.example.com", None), ("alt.example.com", 8443)))
        self.assertEqual(ps.parse_public_hosts(["a.example.com,B.example.com:9000", "a.example.com"]),
                         (("a.example.com", None), ("b.example.com", 9000)))
        for bad in ("https://x.example.com", "x.example.com/p", "localhost", "a b", "x.example.com:99999"):
            with self.assertRaises(ValueError):
                ps.parse_public_hosts([bad])

    def test_host_and_origin_rules(self):
        self.assertTrue(ps.host_ok("limn.example.com"))
        self.assertTrue(ps.host_ok("limn.example.com:443"))
        self.assertTrue(ps.host_ok("alt.example.com:8443"))
        self.assertFalse(ps.host_ok("other.example.com"))
        self.assertTrue(ps.origin_ok("https://limn.example.com", "limn.example.com"))
        self.assertTrue(ps.origin_ok("https://limn.example.com:443", "limn.example.com"))
        self.assertFalse(ps.origin_ok("http://limn.example.com", "limn.example.com"))      # https only
        self.assertFalse(ps.origin_ok("https://limn.example.com:8443", "limn.example.com"))
        self.assertFalse(ps.origin_ok("https://evil.example.com", "limn.example.com"))
        self.assertTrue(ps.origin_ok("https://alt.example.com:8443", "alt.example.com:8443"))
        self.assertFalse(ps.origin_ok("https://alt.example.com", "alt.example.com:8443"))
        self.assertFalse(ps.origin_ok("https://limn.example.com", "127.0.0.1:18999"))        # never on a loopback Host
        self.assertFalse(ps.origin_ok("https://limn.example.com", "box.tail1234.ts.net"))
        reset_access()
        self.assertFalse(ps.host_ok("limn.example.com"))                                     # nothing without the option

    def test_requests_and_pins_md_base(self):
        # A headerless request under a public host is not the loopback agent (v0.2.1) - a person or a token is needed.
        code, _ = self.call("POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 4},
                            dict(ALICE, Host="limn.example.com", Origin="https://limn.example.com"))
        self.assertEqual(code, 200)
        code, _ = self.call("POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 4},
                            dict(ALICE, Host="limn.example.com", Origin="https://evil.example.com"))
        self.assertEqual(code, 403)
        _, tok = ps.token_create(ps.C.state, "ci")
        self.assertEqual(ps.remote_base_for("limn.example.com"), "https://limn.example.com")
        self.assertEqual(ps.remote_base_for("alt.example.com:8443"), "https://alt.example.com:8443")
        code, md = self.call("GET", "/pins.md", headers={"Host": "limn.example.com"}, token=tok)
        self.assertEqual(code, 200)
        self.assertIn("https://limn.example.com/api/pins/N/close", md)
        self.assertIn("원격: `curl -s https://limn.example.com/pins.md`", md)


# ---------------------------------------------------------------- the agent contract additions

class ContractAdditions(AccessBase):
    def test_pins_md_has_exactly_one_token_guidance_line(self):
        self.add()
        md = ps.C.pins_md.read_text(encoding="utf-8")
        lines = md.splitlines()
        self.assertEqual(lines.count(ps.TOKEN_GUIDANCE), 1)
        i = lines.index(ps.TOKEN_GUIDANCE)
        self.assertTrue(lines[i - 2].startswith("처리한 핀은 닫는다"))  # after the existing guidance paragraph
        self.assertEqual(lines[i - 1], ps.claim_guidance("http://127.0.0.1:18999"))   # and the v0.2.1 claim line
        self.assertIn("Authorization: Bearer", ps.TOKEN_GUIDANCE)
        self.assertIn("limn token create <인스턴스>", ps.TOKEN_GUIDANCE)
        self.assertIn("폐지 예정", ps.TOKEN_GUIDANCE)
        for s in ("| # | 쪽 | 위치 | 범위 | 메모 |", "# 수정 요청 핀"):
            self.assertIn(s, md)

    def test_js_is_agent(self):
        js = extract_js_fn("isAgent") + ";console.log(JSON.stringify([isAgent({login:'local'}),isAgent({login:'agent:ci'}),"
        js += "isAgent({login:'alice@example.com'}),isAgent(null)]))"
        out = run_node(js)
        if out is None:
            self.skipTest("node is not installed")
        self.assertEqual(json.loads(out), [True, True, False, False])


# ---------------------------------------------------------------- migration from v0.1

V01_PINS = [
    {"id": 1, "file": "{main}", "name": "main.tex", "page": 1, "lo": 4, "hi": 5, "note": "로컬에서 남긴 메모",
     "at": "2026-09-20 10:00:00", "author": {"login": "local", "name": "로컬/에이전트"}, "rev": 0},
    {"id": 2, "file": "{main}", "name": "main.tex", "page": 1, "lo": 8, "hi": 9, "note": "alice 메모",
     "at": "2026-09-20 10:05:00", "author": {"login": "alice@example.com", "name": "Alice Kim"}, "rev": 0},
    {"id": 3, "file": "{main}", "name": "main.tex", "page": 1, "lo": 17, "hi": 17, "note": "끝난 핀",
     "at": "2026-09-20 10:10:00", "author": {"login": "alice@example.com", "name": "Alice Kim"}, "done": True,
     "done_at": "2026-09-21 09:00:00", "closed_by": {"login": "alice@example.com", "name": "Alice Kim"}, "rev": 1},
    {"id": 4, "file": "{main}", "name": "main.tex", "page": 1, "lo": 19, "hi": 19, "note": "검토할 핀",
     "at": "2026-09-20 10:15:00", "author": {"login": "alice@example.com", "name": "Alice Kim"}, "done": True,
     "review": True, "done_at": "2026-09-21 09:30:00", "closed_by": {"login": "local", "name": "로컬/에이전트"},
     "close_reply": "고쳤음", "close_ref": "PR #1", "rev": 1},
    {"id": 5, "file": "{main}", "name": "main.tex", "page": 1, "lo": 12, "hi": 14, "note": "이 표는 왜 필요한가요?",
     "kind_req": "question", "at": "2026-09-20 10:20:00", "author": {"login": "bob@example.com", "name": "Bob Park"}, "rev": 0},
]
V01_PEOPLE = [
    {"login": "alice@example.com", "first_seen": "2026-09-20 09:59:00", "name": "Alice Kim", "last_seen": "2026-09-21 09:00:00"},
    {"login": "bob@example.com", "first_seen": "2026-09-20 10:19:00", "name": "Bob Park", "last_seen": "2026-09-20 10:20:00"},
]
# pins.md as v0.1.0 renders the fixture above (header timestamp masked as <갱신>, the manuscript path as {src}).
V01_PINS_MD = """\
# 수정 요청 핀

원고: `{src}`
논문: 원고 · 저장소: (없음)
갱신: <갱신>  ·  열린 핀 3건  ·  검토 대기 1건(맨 아래, 처리하지 않는다)  ·  닫힌 핀 1건(뷰어의 '닫힌 핀'에서 확인)

처리한 핀은 닫는다 — `curl -X POST -H 'Content-Type: application/json' -d '{"reply":"무엇을 고쳤는지(≤500자)","ref":"커밋/PR(≤80자)"}' http://127.0.0.1:18999/api/pins/N/close`(본문 생략 가능, 그러면 옛 방식처럼 사유 없이 닫힘) · 줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다 · '질문' 핀은 원고를 고치지 말고(질문이 수정을 뜻할 때만 고친다) `curl -X POST -H 'Content-Type: application/json' -d '{"text":"답(≤1000자)"}' http://127.0.0.1:18999/api/pins/N/reply` 로 답한 뒤 닫는다 · 에이전트가 닫은 핀은 완료가 아니라 검토 대기로 간다(사람이 뷰어에서 [확인]) — 테일넷 주소로 닫는 에이전트는 요청이 사람 신원을 달고 가므로 본문에 `"review":true` 를 넣는다 · 검토 대기 핀은 다시 처리하지 않는다 · 에이전트는 확인(confirm)하지 않는다 — `/api/pins/N/confirm` 은 사람 신원(테일넷 헤더)이 없으면 403
표시: '#N 범위 안'·'#N과 같은 범위' = N과 한 번에 고치고 둘 다 닫는다 · '#N과 일부 겹침' = 참고만, 각자 처리해도 된다 · '처리 중(이름, 약 N분)' = 다른 에이전트가 잡음, 건너뛴다 · '수정됨' = 저장 뒤 메모·범위가 바뀜 · '위치 잃음' = 위치를 되찾지 못함(네가 방금 고친 곳이면 확인 후 닫아도 된다) · '질문' = 고칠 곳이 아니라 물음이다, 답글(reply)로 답하고 닫는다 · '다시 열림' = 검토에서 되돌아온 핀, 메모 칸의 '다시 연 이유'대로 다시 고친다 · '→ @이름' = 담당이 사람인 핀(담당 없는 옛 핀은 사람에게 물은 질문 핀), 사용자가 따로 시키지 않으면 건너뛴다 · '참고 @이름' = 알림만 간 참고용 태그다, 담당이 아니므로 건너뛰지 않는다 · «…» = 줄 안에서 가리킨 부분의 렌더 글자(검색 힌트, 원문과 다를 수 있음)

| # | 쪽 | 위치 | 범위 | 메모 |
|---|---|---|---|---|
| 1 | 1 | `main.tex L4-L5` |  | [로컬/에이전트] 로컬에서 남긴 메모 |
| 2 | 1 | `main.tex L8-L9` |  | [Alice Kim] alice 메모 |
| 5 · 질문 | 1 | `main.tex L12-L14` |  | [Bob Park] 이 표는 왜 필요한가요? |

## 검토 대기 1건 — 사람이 확인할 차례. 에이전트는 다시 처리하지 않는다(다시 열리면 위 열린 표로 돌아온다)

| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |
|---|---|---|---|
| 4 | `main.tex L19-L19` | Alice Kim | 고쳤음 (PR #1) |
"""
TIME_LINE = re.compile(r"^갱신: \d{4}-\d\d-\d\d \d\d:\d\d  ·", re.M)


def mask(md: str) -> str:
    return TIME_LINE.sub("갱신: <갱신>  ·", md)


def load_v01():
    """The server module exactly as released in v0.1.0 (from git), or None when the history is not available (shallow CI clone)."""
    for ref in ("v0.1.0", "946a92d"):
        r = subprocess.run(["git", "show", "%s:src/limn/server.py" % ref], cwd=ROOT, capture_output=True, timeout=30)
        if r.returncode == 0 and b"def pins_md_text" in r.stdout:
            break
    else:
        return None
    d = Path(tempfile.mkdtemp(prefix="limn-v01-"))
    (d / "server_v01.py").write_bytes(r.stdout)
    spec = importlib.util.spec_from_file_location("limn_server_v01", d / "server_v01.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    shutil.rmtree(d, ignore_errors=True)
    return mod


def configure(mod, src: Path, main: Path, state: Path) -> None:
    """The same run configuration Base uses, applied to any server module (v0.1 or current)."""
    C = mod.C
    C.src, C.main, C.state, C.build = src, main, state, state / "build"
    C.port, C.dpi, C.timeout = 18999, 150, 60
    C.envs = tuple(mod.DEFAULT_ENVS.split(","))
    C.allow = frozenset()
    C.origin_check, C.git_pull, C.pdfjs_dir = True, False, None
    C.label, C.accent, C.repo = "원고", mod.ACCENT_PALETTE[0], None
    mod.BUILD_STATE.update(state="idle", phase=None, started_at=None, start_ts=None, seq=0,
                           finished_at=None, last=None, errors=[], log_tail="", head=None, pull=None)
    mod.set_docs(None)
    mod.init_seq()
    if hasattr(mod, "_TOKENS_CACHE"):
        reset_access(mod)


def get(mod, path, headers=None):
    code, _, body = split_resp(talk_to(mod, req("GET", path, b"", headers)))
    return code, body.decode("utf-8")


class Migration(AccessBase):
    """A v0.1 instance (no AUTH, no tokens.json, people.json without roles) behaves exactly as before."""

    def write_fixture(self, state: Path) -> None:
        state.mkdir(parents=True, exist_ok=True)
        rows = [json.loads(json.dumps(r).replace("{main}", str(self.main))) for r in V01_PINS]
        (state / "pins.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        (state / "pins.seq").write_text("5", encoding="utf-8")
        (state / "people.json").write_text(json.dumps({"version": 1, "people": V01_PEOPLE}, ensure_ascii=False, indent=1) + "\n",
                                           encoding="utf-8")

    def setUp(self):
        super().setUp()
        self.write_fixture(ps.C.state)
        configure(ps, self.src, self.main, ps.C.state)

    def test_run_argv_is_unchanged(self):
        root = Path(self.tmp.name)
        cfg = root / "cfg"
        cfg.mkdir()
        (cfg / "paper.env").write_text(
            "# a v0.1 config\nLABEL=\"Paper V\"\nMANUSCRIPT=%s\nMAIN=main.tex\nPORT=19130\nTS_PORT=19030\n"
            "STATE_DIR=%s\nGIT_PULL=1\nEXTRA_ARGS=--no-build\n" % (self.src, ps.C.state), encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(SRC), LIMN_CONFIG_DIR=str(cfg), LIMN_PRINT_ARGV="1")
        r = subprocess.run([sys.executable, "-m", "limn", "run", "paper"], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            sys.executable, str(SRC / "limn" / "server.py"), "--manuscript", str(self.src), "--port", "19130",
            "--state-dir", str(ps.C.state), "--main", "main.tex", "--git-pull", "--label", "Paper V", "--no-build"])

    def test_handler_semantics_unchanged(self):
        code, d = self.call("GET", "/api/meta?light=1")                  # headerless loopback = the agent
        self.assertEqual({k: d["me"][k] for k in ("login", "name")}, ps.LOCAL_ACTOR)
        code, d = self.call("POST", "/api/pins/1/close", {"reply": "고침"})
        self.assertEqual((code, d["state"]), (200, "review"))
        self.assertEqual(self.pin(1)["closed_by"], ps.LOCAL_ACTOR)
        self.assertEqual(self.call("POST", "/api/pins/4/confirm")[0], 403)
        pid = self.pin_id(ALICE)                                          # a tailnet person pins, closes, confirms
        self.assertEqual(self.pin(pid)["author"], {"login": "alice@example.com", "name": "Alice Kim"})
        self.assertEqual(self.call("POST", "/api/pins/2/close", None, ALICE)[1]["state"], "done")
        code, d = self.call("POST", "/api/pins/4/confirm", None, ALICE)
        self.assertEqual((code, d["state"]), (200, "done"))
        self.assertEqual(self.call("GET", "/", headers=CAROL)[0], 200)   # an unknown tailnet person is auto-added
        people = {p["login"]: p for p in self.people_file()}
        self.assertEqual(sorted(people), ["alice@example.com", "bob@example.com", "carol@example.com"])
        self.assertTrue(all("role" not in p for p in people.values()))
        self.assertEqual(people["bob@example.com"], V01_PEOPLE[1])      # untouched
        self.assertFalse(ps.C.tokens_file.exists())

    def test_pins_md_matches_the_v01_rendering(self):
        code, md = get(ps, "/pins.md")
        self.assertEqual(code, 200)
        lines = md.split("\n")
        self.assertEqual(lines.count(ps.TOKEN_GUIDANCE), 1)
        lines.remove(ps.TOKEN_GUIDANCE)
        lines.remove(ps.claim_guidance("http://127.0.0.1:18999"))       # v0.2.1: one more additive line
        lines.remove(ps.REPLY_GUIDANCE)                                  # v0.2.2: one more additive line
        self.assertEqual(mask("\n".join(lines)), V01_PINS_MD.replace("{src}", str(self.src)))

    def test_api_and_pins_md_equal_the_v01_server(self):
        v01 = load_v01()
        if v01 is None:
            self.skipTest("v0.1.0 is not in this clone's history (shallow checkout)")
        old_state = Path(self.tmp.name) / "state-v01"
        self.write_fixture(old_state)
        configure(v01, self.src, self.main, old_state)
        self.compare_with(v01)

    def compare_with(self, v01, headers=None):
        for path in ("/api/pins", "/api/pins?all=1", "/api/pins/dropped", "/api/pins/4"):
            c_old, b_old = get(v01, path, headers)
            c_new, b_new = get(ps, path, headers)
            self.assertEqual(c_new, c_old, path)
            new, old = json.loads(b_new), json.loads(b_old)
            if path == "/api/pins/dropped":                              # v0.2.2: the Trash adds a computed expires_ts
                for r in new["dropped"]:                                 # and hides entries older than TRASH_DAYS
                    self.assertIsInstance(r.pop("expires_ts", 0), (int, float))
                old["dropped"] = [r for r in old["dropped"] if not ps.trash_expired(r)]
            self.assertEqual(new, old, path)
        c_old, md_old = get(v01, "/pins.md", headers)
        c_new, md_new = get(ps, "/pins.md", headers)
        self.assertEqual(c_new, c_old)
        lines = md_new.split("\n")
        self.assertEqual(lines.count(ps.TOKEN_GUIDANCE), 1)
        lines.remove(ps.TOKEN_GUIDANCE)
        claim = [l for l in lines if l.startswith("처리를 시작하는 핀은 먼저 잡는다")]
        self.assertEqual(len(claim), 1)                                  # v0.2.1: one more additive line
        lines.remove(claim[0])
        lines.remove(ps.REPLY_GUIDANCE)                                  # v0.2.2: one more additive line
        self.assertEqual(mask("\n".join(lines)), mask(md_old))
        _, p_old = get(v01, "/api/people", headers)
        _, p_new = get(ps, "/api/people", headers)
        p_old, p_new = json.loads(p_old), json.loads(p_new)
        self.assertTrue(all(p.pop("role") == "editor" for p in p_new["people"]))   # the only change: an additive role
        p_new["me"].pop("role")
        self.assertEqual(p_new, p_old)

    def test_real_state_copy(self):
        """Opt-in: LIMN_TEST_STATE_COPY=<copy of a real state dir>. The copy is copied again (twice) so neither server
        writes to it; the v0.1.0 server and this one must serve the same pins, pins.md (+ one line) and people."""
        src_state = os.environ.get("LIMN_TEST_STATE_COPY")
        if not src_state:
            self.skipTest("set LIMN_TEST_STATE_COPY to a copy of a real state dir to run this")
        v01 = load_v01()
        if v01 is None:
            self.skipTest("v0.1.0 is not in this clone's history")
        src_state = Path(src_state)
        keep = ("pins.jsonl", "pins.seq", "pins.dropped.jsonl", "people.json", "events.jsonl", "builds.json",
                "built_at.txt", "built_src_mtime.txt", "head.txt", "pages.cur", "pins.md")
        states = []
        for tag in ("old", "new"):
            d = Path(self.tmp.name) / ("copy-" + tag)
            d.mkdir()
            for name in keep:
                if (src_state / name).is_file():
                    shutil.copy2(src_state / name, d / name)
            states.append(d)
        m = re.search(r"^원고: `([^`]+)`", (src_state / "pins.md").read_text(encoding="utf-8"), re.M) \
            if (src_state / "pins.md").exists() else None
        ms = Path(m.group(1)) if m else self.src
        main = next(iter(sorted(ms.glob("*.tex"))), self.main) if ms.is_dir() else self.main
        configure(v01, ms, main, states[0])
        configure(ps, ms, main, states[1])
        self.assertFalse((states[1] / "tokens.json").exists())
        self.compare_with(v01)
        people = json.loads((states[1] / "people.json").read_text(encoding="utf-8"))["people"] \
            if (states[1] / "people.json").exists() else []
        for p in people:                                                 # a real person keeps today's rights
            code, _ = get(ps, "/api/pins", {"Tailscale-User-Login": p["login"]})
            self.assertEqual(code, 200, p["login"])
            self.assertEqual(ps.role_of(p["login"]), ps.role_value(p.get("role")))


if __name__ == "__main__":
    unittest.main()
