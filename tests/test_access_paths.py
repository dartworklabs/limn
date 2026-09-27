"""Who may do what through which entry path: every principal (loopback agent, tailnet person, token, trusted proxy)
over loopback, the tailnet and a proxy, for read, pin, reply, close, confirm and clear.

The v0.2.1 QA (finding B) found a headerless request through `tailscale serve` treated as the loopback agent.
PrincipalMatrix pins every principal x entry path; ProxyHardening the security-review follow-ups (more proxy markers
refuse the headerless agent, --auth local refuses proxied requests, people.json stays 0600). The identity providers,
tokens and roles one by one are test_access.py; the access rules without a server are test_access_module.py.

Run: uv run pytest -q tests/test_access_paths.py
"""

import os

from limn import access, startup
from limn.access import LOCAL_ACTOR
from limn.pins.lifecycle import CloseRequest

from helpers import ps, set_config
from helpers_access import ALICE, BOB, CLEAR_BODY, TS_HOST, AccessBase, member_add, token_create


class PrincipalMatrix(AccessBase):
    """Every principal x entry path for read, pin, reply, close, confirm and clear."""

    OPS = ("read", "pin", "reply", "close", "confirm", "clear")

    def run_ops(self, **kw):
        """Status code of each operation for one principal (fresh pins per operation, so earlier ones do not interfere)."""
        out = {}
        out["read"] = self.call("GET", "/pins.md", **kw)[0]
        out["pin"] = self.call(
            "POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "n"}, **kw
        )[0]
        pid = self.add()
        out["reply"] = self.call("POST", "/api/pins/%d/reply" % pid, {"text": "답"}, **kw)[0]
        pid = self.add()
        code, d = self.call("POST", "/api/pins/%d/close" % pid, None, **kw)
        out["close"] = code if code != 200 else d["state"]
        pid = self.add()
        ps.APP.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest())
        out["confirm"] = self.call("POST", "/api/pins/%d/confirm" % pid, None, **kw)[0]
        before = len(ps.APP.snapshot_pins())
        out["clear"] = self.call("POST", "/api/clear", CLEAR_BODY, **kw)[0]
        if out["clear"] != 200:
            self.assertEqual(len(ps.APP.snapshot_pins()), before)
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
        self.assertIn("Bearer", d["error"])  # tells the agent what to do instead
        self.expect(self.run_ops(headers={"Host": TS_HOST + ":18004"}), **self.REFUSED_403)

    def test_spoofed_loopback_host_through_the_proxy_is_refused(self):
        # tailscale serve routes by the TLS name and passes the client's Host through unchanged, so a tagged device can
        # send "Host: localhost". The proxy always sets X-Forwarded-For/-Host/-Proto (overwriting client values) - those,
        # not Host, tell that a request came through it.
        for extra in (
            {"X-Forwarded-For": "100.64.0.9"},
            {"X-Forwarded-Host": TS_HOST},
            {"X-Forwarded-Proto": "https"},
            {"Forwarded": "for=100.64.0.9"},
        ):
            for host in ("localhost", "127.0.0.1:1", "[::1]", "LOCALHOST."):
                h = dict(extra, Host=host)
                self.assertEqual(self.call("GET", "/pins.md", headers=h)[0], 403, h)
                pid = self.add()
                self.assertEqual(self.call("POST", "/api/pins/%d/drop" % pid, None, headers=h)[0], 403, h)
                self.assertIsNotNone(self.pin(pid))
        # the same forwarded headers with a person's identity or a token are fine
        self.assertEqual(
            self.call("GET", "/pins.md", headers=dict(BOB, Host=TS_HOST, **{"X-Forwarded-For": "100.64.0.9"}))[0], 200
        )
        _, tok = token_create(ps.APP.C.state, "ci")
        self.assertEqual(
            self.call("GET", "/pins.md", token=tok, headers={"Host": "localhost", "X-Forwarded-For": "100.64.0.9"})[0],
            200,
        )

    def test_opt_in_with_an_allowlist_refuses_forwarded_requests_too(self):
        set_config(tailnet_agent=True)
        self.assertEqual(
            self.call("GET", "/pins.md", headers={"Host": "localhost", "X-Forwarded-For": "100.64.0.9"})[0], 200
        )
        set_config(allow=frozenset({"alice@example.com"}))
        self.assertEqual(
            self.call("GET", "/pins.md", headers={"Host": "localhost", "X-Forwarded-For": "100.64.0.9"})[0], 403
        )
        self.assertEqual(self.call("GET", "/pins.md")[0], 200)  # a real local agent is still fine

    def test_public_host_headerless_is_refused(self):
        set_config(public_hosts=access.parse_public_hosts(["limn.example.com"]))
        self.expect(self.run_ops(headers={"Host": "limn.example.com"}), **self.REFUSED_403)

    def test_tailnet_headerless_opt_in_is_the_agent_again(self):
        set_config(tailnet_agent=True)
        self.expect(self.run_ops(headers={"Host": TS_HOST}), **self.AGENT)
        set_config(allow=frozenset({"alice@example.com"}))  # an allowlist still refuses it, as in v0.1
        self.assertEqual(self.call("GET", "/pins.md", headers={"Host": TS_HOST})[0], 403)

    def test_bearer_token_over_loopback_and_tailnet(self):
        _, tok = token_create(ps.APP.C.state, "ci")
        self.expect(self.run_ops(token=tok), **self.AGENT)
        self.expect(self.run_ops(token=tok, headers={"Host": TS_HOST}), **self.AGENT)

    def test_trusted_proxy_peer_and_non_peer(self):
        set_config(auth="trusted-proxy", agent_loopback=False)
        set_config(trusted_proxies=access.parse_networks("10.0.0.1"))
        h = {"X-Forwarded-User": "bob@example.com"}
        self.expect(self.run_ops(headers=h, peer="10.0.0.1"), **self.EDITOR)
        self.set_people([{"login": "alice@example.com", "name": "Alice", "role": "owner"}])
        self.expect(self.run_ops(headers={"X-Forwarded-User": "alice@example.com"}, peer="10.0.0.1"), **self.OWNER)
        self.expect(self.run_ops(headers=h, peer="10.0.0.9"), **self.REFUSED_401)
        self.expect(self.run_ops(peer="10.0.0.1"), **self.REFUSED_401)  # the proxy without a user header

    def test_loopback_agent_off_is_401_even_on_loopback(self):
        set_config(agent_loopback=False)
        self.expect(self.run_ops(), **self.REFUSED_401)


class ProxyHardening(AccessBase):
    """Security review follow-ups (L1, L2, L4)."""

    def test_more_proxy_markers_refuse_the_headerless_agent(self):
        for extra in (
            {"X-Real-IP": "100.64.0.9"},
            {"Via": "1.1 proxy"},
            {"X-Forwarded-Port": "443"},
            {"X-Forwarded-Proto": "https"},
            {"X-Forwarded-Host": TS_HOST},
        ):
            h = dict(extra, Host="localhost")
            self.assertEqual(self.call("GET", "/pins.md", headers=h)[0], 403, h)
            self.assertEqual(self.call("POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 5}, h)[0], 403, h)
        self.assertEqual(self.call("GET", "/pins.md")[0], 200)  # a real local agent

    def test_local_auth_refuses_proxied_requests(self):
        set_config(auth="local", agent_loopback=False, local_user="alice")
        self.add()
        for h in (
            {"Host": TS_HOST, "X-Forwarded-For": "100.64.0.9"},
            {"Host": "localhost", "X-Forwarded-For": "100.64.0.9"},
            {"Host": "localhost", "X-Real-IP": "100.64.0.9"},
        ):
            code, d = self.call("POST", "/api/clear", {"confirm": "clear all pins"}, h)
            self.assertEqual(code, 403, (h, d))
            self.assertEqual(self.call("GET", "/api/meta?light=1", headers=h)[0], 403, h)
        self.assertEqual(len(ps.APP.snapshot_pins()), 1)
        code, d = self.call("GET", "/api/meta?light=1")  # the owner at the keyboard
        self.assertEqual((code, d["me"]["role"]), (200, "owner"))
        _, tok = token_create(ps.APP.C.state, "ci")  # tokens still work through a proxy
        self.assertEqual(
            self.call("GET", "/pins.md", token=tok, headers={"Host": TS_HOST, "X-Forwarded-For": "1.2.3.4"})[0], 200
        )

    def test_people_json_is_written_0600(self):
        ps.APP.RT.people_seen.clear()
        ps.APP.record_person({"login": "bob@example.com", "name": "Bob"})
        self.assertEqual(ps.APP.C.people_file.stat().st_mode & 0o777, 0o600)
        os.chmod(ps.APP.C.people_file, 0o644)
        member_add(ps.APP.C.state, "carol@example.com")
        self.assertEqual(ps.APP.C.people_file.stat().st_mode & 0o777, 0o600)

    def test_startup_tightens_a_group_or_world_writable_people_json(self):
        import io
        from unittest import mock

        ps.APP.C.people_file.write_text('{"version": 1, "people": []}\n', encoding="utf-8")
        os.chmod(ps.APP.C.people_file, 0o666)
        err = io.StringIO()
        with mock.patch.object(ps.sys, "stderr", err):
            startup.tighten_state_perms(ps.APP.C.people_file)
            startup.tighten_state_perms(ps.APP.C.people_file)
        self.assertEqual(ps.APP.C.people_file.stat().st_mode & 0o777, 0o600)
        # logged once
        self.assertEqual(len([ln for ln in err.getvalue().splitlines() if "tightened" in ln]), 1, err.getvalue())
        os.chmod(ps.APP.C.people_file, 0o644)  # only writable-by-others is changed
        startup.tighten_state_perms(ps.APP.C.people_file)
        self.assertEqual(ps.APP.C.people_file.stat().st_mode & 0o777, 0o644)
