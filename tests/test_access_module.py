"""limn.access and limn.guidance tested directly, without a server: the refusals of the security boundary (R10).

identify, admit and check_role are called with explicit AccessSettings and AccessLookups, the way server.py's
composition root calls them. Each refusal must raise HTTPError with the same status, reason and browser page as it
did in server.py. The file-backed lookups (FileCache) and the CLI state helpers get their own direct tests. The
end-to-end paths through the HTTP handler are tested in test_access.py and test_qa_021.py.

Run: uv run pytest -q tests/test_access_module.py
"""
import ast
import dataclasses
import io
import ipaddress
import json
import stat
import tempfile
import threading
import unittest
from email.message import Message
from pathlib import Path, PurePath
from unittest import mock

from limn import access, files, guidance, people
from limn.access import AccessLookups, AccessSettings, Principal
from limn.web.answers import CONFIRM_BY_HUMAN
from limn.web.errors import HTTPError

ACCESS_PY = Path(access.__file__)
GUIDANCE_PY = Path(guidance.__file__)
PEOPLE_PY = Path(people.__file__)
ALICE = {"Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Alice Kim"}
TOKEN = "limn_" + "t" * 43
TOKEN_ROW = {"id": "0badc0de", "name": "ci", "hash": access.token_hash(TOKEN), "created": "2026-09-26 10:00:00"}
# The options a server started with no access flags runs with (server.Cfg's values), stated here in full because
# AccessSettings has no defaults. Each test overrides only what it is about.
BASE_SETTINGS = dict(auth="tailscale", agent_loopback=True, tailnet_agent=False,
                     trusted_proxies=(ipaddress.ip_network("127.0.0.1/32"), ipaddress.ip_network("::1/128")),
                     proxy_user_header="X-Forwarded-User", proxy_name_header="X-Forwarded-Preferred-Username",
                     proxy_email_header=None, members_only=False, allow=frozenset(), local_user=None,
                     agent_token_file=None)


def settings(**over) -> AccessSettings:
    """AccessSettings of a default-flag server with the given options changed."""
    return AccessSettings(**dict(BASE_SETTINGS, **over))


def headers(values=None) -> Message:
    """A request header block like the one http.server hands the handler (repeated names allowed as pairs)."""
    m = Message()
    for k, v in (values.items() if isinstance(values, dict) else values or []):
        m[k] = v
    return m


class Lookups:
    """Stand-in file-backed facts: fixed token rows and roles, and counters of what identify/admit read."""

    def __init__(self, tokens=(), roles=None):
        """tokens: the tokens.json rows; roles: {login: role} of people.json."""
        self.rows = list(tokens)
        self.role_map = dict(roles or {})
        self.role_reads = 0
        self.warnings = 0

    def tokens(self):
        """The token rows as the server sees them now."""
        return self.rows

    def roles(self):
        """The people.json roles, counting each read."""
        self.role_reads += 1
        return self.role_map

    def warn(self):
        """Count one loopback-agent deprecation warning."""
        self.warnings += 1

    def value(self) -> AccessLookups:
        """The AccessLookups identify() receives."""
        return AccessLookups(tokens=self.tokens, roles=self.roles, warn_loopback_agent=self.warn)


class RefusalCase(unittest.TestCase):
    """Assertions on a raised refusal."""

    def refused(self, fn, *args, code, reason, page=None, **kwargs):
        """fn(*args, **kwargs) raises HTTPError with this status, reason and page; returns the error for more checks."""
        with self.assertRaises(HTTPError) as cm:
            fn(*args, **kwargs)
        e = cm.exception
        self.assertEqual((e.code, e.body["reason"], e.page and e.page[0]), (code, reason, page))
        return e


class ModuleBoundary(unittest.TestCase):
    """access.py does not reach into the composition root, and guidance.py stays pure."""

    def imported(self, path: Path) -> set:
        """Top-level module names path imports."""
        names = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] if not a.name.startswith("limn") else a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module)
        return names

    def test_access_never_reads_the_run_settings_or_imports_the_server(self):
        """No `C.`, no server import: the settings and lookups arrive as arguments."""
        source = ACCESS_PY.read_text(encoding="utf-8")
        self.assertNotIn("C.", source)
        self.assertFalse({n for n in self.imported(ACCESS_PY) if n and "server" in n})
        self.assertNotIn("limn.audit", self.imported(ACCESS_PY))    # the CLI's audit sink arrives as an argument

    def test_the_people_format_access_imports_brings_no_server_store_or_notices(self):
        """access.py takes people.json's entry check and text from limn.people; that module imports only the standard
        library and limn.files (which access.py imports itself) - never the server, the pin store, notices or HTTP."""
        self.assertIn("limn.people", self.imported(ACCESS_PY))
        self.assertEqual({n for n in self.imported(PEOPLE_PY) if n.startswith("limn")}, {"limn.files"})
        self.assertIn("limn.files", self.imported(ACCESS_PY))
        self.assertEqual({n for n in self.imported(Path(files.__file__)) if n.startswith("limn")}, set())

    def test_limn_member_writes_people_json_in_the_people_stores_format(self):
        """`limn member` and the running server write one format: what member_add writes is people_text of its rows,
        and an entry people.valid_people drops is dropped by the CLI's read too."""
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "people.json").write_text(json.dumps({"version": 1, "people": [
                {"login": "zed@example.com", "name": "Zed"}, {"login": ""}, {"login": "x@example.com", "name": 3}]}),
                encoding="utf-8")
            self.assertEqual(access.load_people_file(state), [{"login": "zed@example.com", "name": "Zed"}])
            access.member_add(state, "amy@example.com", "viewer", None, lambda action, details: None)
            rows = [{"login": "amy@example.com", "name": "amy", "role": "viewer"},
                    {"login": "zed@example.com", "name": "Zed"}]
            self.assertEqual((state / "people.json").read_text(encoding="utf-8"), people.people_text(rows))

    def test_guidance_imports_nothing_effectful(self):
        """The token-file wording is strings in, strings out: only re, shlex and PurePath."""
        self.assertEqual(self.imported(GUIDANCE_PY), {"__future__", "re", "shlex", "pathlib"})
        self.assertIn("from pathlib import PurePath", GUIDANCE_PY.read_text(encoding="utf-8"))


class Settings(unittest.TestCase):
    """AccessSettings cannot be built from partial options."""

    def test_every_field_must_be_given(self):
        """No field has a default, so leaving one out is an error, never the permissive legacy value."""
        self.assertTrue(all(f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
                            for f in dataclasses.fields(AccessSettings)))
        partial = dict(BASE_SETTINGS)
        del partial["agent_loopback"]
        with self.assertRaises(TypeError):
            AccessSettings(**partial)


class Peers(unittest.TestCase):
    """What counts as a loopback peer and as a trusted proxy."""

    def test_a_peer_that_is_not_an_ip_is_never_a_trusted_proxy(self):
        """A unix-socket path, a host name or an empty peer is refused even when every address is trusted."""
        everything = access.parse_networks("0.0.0.0/0,::/0")
        for peer in ("", "localhost", "/run/limn.sock", "10.0.0.1:80", None):
            self.assertFalse(access.peer_is_trusted_proxy(peer, everything), peer)
            self.assertFalse(access.peer_is_loopback(peer), peer)

    def test_an_ipv4_mapped_loopback_peer_is_loopback(self):
        """::ffff:127.0.0.1 (a dual-stack socket's view of 127.0.0.1) is loopback, as on main; ::ffff:10.0.0.1 is not."""
        self.assertTrue(access.peer_is_loopback("::ffff:127.0.0.1"))
        self.assertTrue(access.peer_is_loopback("::1%lo0"))
        self.assertFalse(access.peer_is_loopback("::ffff:10.0.0.1"))
        self.assertTrue(access.peer_is_trusted_proxy("::ffff:10.0.0.1", access.parse_networks("10.0.0.1")))


class Identify(RefusalCase):
    """Who a request is under each provider, and every way it is refused."""

    def identify(self, hdrs=None, peer="127.0.0.1", lookups=None, **options):
        """identify() with these headers and peer, under a default-flag server's settings with options changed."""
        return access.identify(headers(hdrs), peer, settings(**options), (lookups or Lookups()).value())

    def test_a_valid_token_is_the_agent_under_every_provider(self):
        """A known token wins over identity headers and the provider, from any peer."""
        for auth in access.AUTH_PROVIDERS:
            p = self.identify({"Authorization": "Bearer " + TOKEN, **ALICE}, peer="10.0.0.9",
                              lookups=Lookups([TOKEN_ROW]), auth=auth)
            self.assertEqual(p, Principal({"login": "agent:ci", "name": "ci"}, "agent", "token"), auth)

    def test_an_unknown_or_revoked_token_is_401_and_never_falls_back_to_the_headers(self):
        """A token that matches no row is refused even though the Tailscale headers alone would pass."""
        self.refused(self.identify, {"Authorization": "Bearer limn_wrong", **ALICE}, "127.0.0.1", Lookups([TOKEN_ROW]),
                     code=401, reason="bad_token")
        self.refused(self.identify, {"Authorization": "Bearer " + TOKEN, **ALICE}, "127.0.0.1", Lookups([]),
                     code=401, reason="bad_token")                       # revoked: its row is gone

    def test_an_empty_or_repeated_bearer_header_is_401_not_no_token(self):
        """`Bearer` without a value, or two Bearer headers, are malformed - never read as an anonymous request."""
        for hdrs in ({"Authorization": "Bearer "}, [("Authorization", "Bearer a"), ("Authorization", "Bearer b")]):
            self.refused(self.identify, hdrs, code=401, reason="bad_bearer")

    def test_tailscale_headers_from_a_remote_peer_are_ignored(self):
        """Only tailscale serve (a loopback peer) may vouch for a person; the same headers from elsewhere are 401."""
        self.refused(self.identify, ALICE, "100.64.0.7", code=401, reason="unauthenticated")

    def test_a_header_login_that_is_not_a_person_is_401(self):
        """'local', 'agent:...' and a login with a space cannot be claimed through a header."""
        for login in ("local", "agent:ci", "bad login"):
            self.refused(self.identify, {"Tailscale-User-Login": login}, code=401, reason="unauthenticated")

    def test_a_person_gets_the_people_json_role_and_editor_by_default(self):
        """The role comes from the roles lookup; someone people.json does not list is an editor."""
        lk = Lookups(roles={"alice@example.com": "viewer"})
        self.assertEqual(self.identify(ALICE, lookups=lk).role, "viewer")
        self.assertEqual(self.identify({"Tailscale-User-Login": "bob@example.com"}).role, "editor")

    def test_a_headerless_request_through_the_proxy_is_403_not_the_agent(self):
        """A forwarding header or a tailnet Host marks tailscale serve: without --tailnet-agent it is refused."""
        for hdrs in ({"X-Forwarded-For": "100.64.0.7"}, {"Host": "box.tail1.ts.net"}, {"Via": "1.1 proxy"}):
            e = self.refused(self.identify, hdrs, code=403, reason="headerless", page="no-identity")
            self.assertEqual(e.body["error"], access.TAILNET_HEADERLESS)
        self.assertEqual(self.identify({"Host": "box.tail1.ts.net"}, tailnet_agent=True).via, "loopback-agent")

    def test_the_loopback_agent_asks_for_the_warning_and_can_be_turned_off(self):
        """A plain local request is the agent while agent_loopback is on (and asks for the warning)."""
        lk = Lookups()
        self.assertEqual(self.identify({"Host": "127.0.0.1:18300"}, lookups=lk).via, "loopback-agent")
        self.assertEqual(lk.warnings, 1)
        e = self.refused(self.identify, {"Host": "localhost"}, "::1", lk, agent_loopback=False,
                         agent_token_file=Path("/srv/limn/paper.token"), code=401, reason="loopback_agent_off")
        self.assertTrue(e.body["error"].startswith(guidance.UNAUTHENTICATED))
        self.assertIn("limn token create paper --save", e.body["error"])      # the file does not exist here
        self.assertEqual(lk.warnings, 1)

    def test_a_remote_request_with_the_loopback_agent_off_is_plain_401(self):
        """Through the proxy with the loopback agent off: the generic 401, not the local token-file hint."""
        e = self.refused(self.identify, {"X-Forwarded-For": "1.2.3.4"}, agent_loopback=False,
                         code=401, reason="unauthenticated")
        self.assertEqual(e.body["error"], guidance.UNAUTHENTICATED)

    def test_local_provider_owner_only_from_this_machine(self):
        """--auth local: a loopback request is the owner; a remote one is 401; one through a proxy is 403."""
        with mock.patch.dict("os.environ", {"USER": "dana"}):
            self.assertEqual(self.identify(auth="local").actor, {"login": "dana", "name": "dana"})
        self.assertEqual(self.identify(auth="local", local_user="alice").role, "owner")
        self.refused(self.identify, None, "10.0.0.5", auth="local", code=401, reason="unauthenticated")
        self.refused(self.identify, {"X-Forwarded-Host": "x"}, auth="local", code=403, reason="headerless",
                     page="no-identity")

    def test_trusted_proxy_headers_count_only_from_a_trusted_peer(self):
        """--auth trusted-proxy: the user header from an untrusted peer, or no header, is 401."""
        nets = access.parse_networks("10.0.0.1")
        hdrs = {"X-Forwarded-User": "alice@example.com"}
        self.refused(self.identify, hdrs, "10.0.0.2", auth="trusted-proxy", trusted_proxies=nets,
                     code=401, reason="unauthenticated")
        self.refused(self.identify, {}, "10.0.0.1", auth="trusted-proxy", trusted_proxies=nets,
                     code=401, reason="unauthenticated")
        self.refused(self.identify, {"X-Forwarded-User": "local"}, "10.0.0.1", auth="trusted-proxy",
                     trusted_proxies=nets, code=401, reason="unauthenticated")
        p = self.identify({**hdrs, "X-Email": "a@example.com"}, "::ffff:10.0.0.1", Lookups(roles={"a@example.com": "owner"}),
                          auth="trusted-proxy", trusted_proxies=nets, proxy_email_header="X-Email")
        self.assertEqual((p.actor["login"], p.role, p.via), ("a@example.com", "owner", "header"))


class Admit(RefusalCase):
    """--allow and --members-only filter people vouched for by a header; tokens and the local owner pass."""

    PERSON = Principal({"login": "bob@example.com", "name": "Bob"}, "editor", "header")

    def admit(self, p, host=None, hdrs=None, lookups=None, **options):
        """admit() with these settings; hdrs None passes no header block."""
        return access.admit(p, host, None if hdrs is None else headers(hdrs), settings(**options),
                            (lookups or Lookups()).roles)

    def test_members_only_refuses_a_non_member_and_reads_roles_only_then(self):
        """A person not in people.json or --allow is 403 not_member; without --members-only roles are never read."""
        lk = Lookups()
        self.admit(self.PERSON, lookups=lk)
        self.assertEqual(lk.role_reads, 0)
        e = self.refused(self.admit, self.PERSON, None, None, lk, members_only=True, code=403, reason="not_member",
                         page="not-member")
        self.assertEqual(e.page[1], {"login": "bob@example.com"})
        self.admit(self.PERSON, lookups=Lookups(roles={"bob@example.com": "viewer"}), members_only=True)
        self.admit(self.PERSON, members_only=True, allow=frozenset({"bob@example.com"}))

    def test_allow_refuses_a_login_it_does_not_list(self):
        """With --allow set, anyone else is 403 not_allowed with the not-allowed page."""
        self.refused(self.admit, self.PERSON, None, None, None, allow=frozenset({"alice@example.com"}),
                     code=403, reason="not_allowed", page="not-allowed")

    def test_the_headerless_agent_through_the_tailnet_is_refused_when_a_list_is_set(self):
        """A loopback-agent principal arriving on a *.ts.net Host or with a forwarding header is 403 under --allow."""
        agent = Principal(dict(access.LOCAL_ACTOR), "agent", "loopback-agent")
        allow = frozenset({"alice@example.com"})
        self.refused(self.admit, agent, "box.tail1.ts.net", None, None, allow=allow, code=403, reason="headerless",
                     page="no-identity")
        self.refused(self.admit, agent, "localhost", {"X-Forwarded-For": "1.2.3.4"}, None, members_only=True,
                     code=403, reason="headerless", page="no-identity")
        self.admit(agent, "localhost", {}, allow=allow)                   # a plain local request passes

    def test_tokens_and_the_local_owner_are_always_admitted(self):
        """The lists only filter header-vouched people."""
        for p in (Principal({"login": "agent:ci", "name": "ci"}, "agent", "token"),
                  Principal({"login": "dana", "name": "dana"}, "owner", "local-owner")):
            self.admit(p, members_only=True, allow=frozenset({"x@example.com"}))


class CheckRole(RefusalCase):
    """The role rule for a POST, before dispatch."""

    def who(self, role):
        """A header-vouched principal with this role."""
        return Principal({"login": "bob@example.com", "name": "Bob"}, role, "header")

    def test_a_viewer_may_only_compute(self):
        """/api/pick and /api/revision-build pass; any change is 403 viewer_only."""
        for path in access.VIEWER_POSTS:
            access.check_role(self.who("viewer"), path, 30)
        self.refused(access.check_role, self.who("viewer"), "/api/pin", 30, code=403, reason="viewer_only")

    def test_an_agent_cannot_confirm(self):
        """Confirm is a person's decision: 403 with the confirm-by-human text."""
        e = self.refused(access.check_role, self.who("agent"), "/api/pins/7/confirm", 30, code=403,
                         reason="confirm_by_human")
        self.assertEqual(e.body["error"], CONFIRM_BY_HUMAN)
        access.check_role(self.who("agent"), "/api/pins/7/close", 30)

    def test_clear_and_purge_are_the_owners_only(self):
        """Editors and agents get 403 owner_only; the purge refusal quotes how long the Trash keeps a pin."""
        for role in ("editor", "agent"):
            self.refused(access.check_role, self.who(role), "/api/clear", 30, code=403, reason="owner_only")
            e = self.refused(access.check_role, self.who(role), "/api/pins/3/purge", 12, code=403, reason="owner_only")
            self.assertIn("12일", e.body["error"])
        access.check_role(self.who("owner"), "/api/clear", 30)
        access.check_role(self.who("owner"), "/api/pins/3/purge", 30)

    def test_an_unknown_role_in_people_json_is_a_viewer(self):
        """Fail closed: a role value Limn does not know grants the least."""
        self.assertEqual([access.role_value(v) for v in (None, "owner", "admin", 3, [])],
                         ["editor", "owner", "viewer", "viewer", "viewer"])


class Hosts(unittest.TestCase):
    """Host and Origin (DNS rebinding and CSRF defense)."""

    PUBLIC = (("limn.example.com", None), ("alt.example.com", 8443))

    def test_a_foreign_host_is_refused(self):
        """Only loopback names, *.ts.net and --public-host names are accepted as Host."""
        for host in ("evil.example.com", "127.0.0.1.evil.example.com", "limn.example.com.evil.net", ""):
            self.assertFalse(access.host_ok(host, self.PUBLIC), host)
        for host in ("localhost:9000", "[::1]:1", "box.tail1.ts.net", "limn.example.com"):
            self.assertTrue(access.host_ok(host, self.PUBLIC), host)

    def test_an_origin_from_the_other_side_is_refused(self):
        """A tailnet Origin with a loopback Host, a null Origin, a plain-http public Origin and a wrong port fail."""
        cases = [("https://box.tail1.ts.net", "localhost"), ("null", "localhost"),
                 ("http://limn.example.com", "limn.example.com"), ("https://alt.example.com", "alt.example.com"),
                 ("https://box.tail1.ts.net:8443", "box.tail1.ts.net"), ("https://other.tail1.ts.net", "box.tail1.ts.net"),
                 ("http://localhost:x", "localhost")]
        for origin, host in cases:
            self.assertFalse(access.origin_ok(origin, host, self.PUBLIC), (origin, host))
        self.assertTrue(access.origin_ok("https://alt.example.com:8443", "alt.example.com", self.PUBLIC))
        self.assertTrue(access.origin_ok("http://127.0.0.1:18110", None, self.PUBLIC))

    def test_the_pins_md_base_follows_the_host_kind(self):
        """*.ts.net as sent, a public host with its configured port, else the loopback URL on the server port."""
        self.assertEqual(access.remote_base_for("box.tail1.ts.net:8443", self.PUBLIC, 18300), "https://box.tail1.ts.net:8443")
        self.assertEqual(access.remote_base_for("alt.example.com", self.PUBLIC, 18300), "https://alt.example.com:8443")
        self.assertEqual(access.remote_base_for("evil.example.com", self.PUBLIC, 18300), "http://127.0.0.1:18300")


class Caches(unittest.TestCase):
    """FileCache follows the file on disk; WarnOnce prints once."""

    def setUp(self):
        """A temp folder for the cached files."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_a_missing_file_is_empty_without_loading_and_a_change_reloads(self):
        """Missing -> empty (load not called); written -> loaded once; rewritten -> loaded again."""
        cache, p, loads = access.FileCache(), self.dir / "tokens.json", []

        def load():
            """Read the file, counting reads."""
            loads.append(1)
            return p.read_text(encoding="utf-8")
        self.assertEqual(cache.get(p, load, "empty"), "empty")
        p.write_text("one", encoding="utf-8")
        self.assertEqual((cache.get(p, load, "empty"), cache.get(p, load, "empty")), ("one", "one"))
        p.write_text("second", encoding="utf-8")
        self.assertEqual(cache.get(p, load, "empty"), "second")
        self.assertEqual(len(loads), 2)
        p.unlink()
        self.assertEqual(cache.get(p, load, "empty"), "empty")      # a revoked-by-deletion file accepts nothing

    def test_the_key_includes_the_path_so_two_state_folders_never_share(self):
        """The same cache over another state folder's file loads that file, and switching back loads A's again -
        a value is never served for a folder other than the one it was read from (authorization scope is the folder)."""
        cache = access.FileCache()
        a, b = self.dir / "a.json", self.dir / "b.json"
        a.write_text("A", encoding="utf-8")
        b.write_text("B", encoding="utf-8")

        def read(p):
            """A loader that reads p's current text."""
            return lambda: p.read_text(encoding="utf-8")
        self.assertEqual(cache.get(a, read(a), ""), "A")
        self.assertEqual(cache.get(b, read(b), ""), "B")
        self.assertEqual(cache.get(a, read(a), ""), "A")
        b.unlink()
        self.assertEqual(cache.get(b, read(b), "none"), "none")
        self.assertEqual(cache.get(a, read(a), "none"), "A")

    def test_a_file_that_cannot_be_statted_still_loads_and_fails_closed(self):
        """A stat error other than a missing file ("unreadable") never serves the old value or the empty default: it
        calls load, and the token loader then accepts no token (and the role lookup would see no one)."""
        state = self.dir / "state"
        state.mkdir()
        (state / "tokens.json").write_text(json.dumps({"tokens": [{"id": "1", "name": "ci", "hash": "sha256:x"}]}),
                                           encoding="utf-8")
        cache = access.FileCache()
        path = state / "tokens.json"
        self.assertEqual(len(cache.get(path, lambda: access.load_tokens(state), [])), 1)
        loads = []

        def load():
            """The server's token loader, counting calls; the file itself is unreadable now."""
            loads.append(1)
            return access.load_tokens(state)
        with mock.patch.object(Path, "stat", side_effect=PermissionError(13, "Permission denied")), \
                mock.patch.object(Path, "read_text", side_effect=PermissionError(13, "Permission denied")), \
                mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(cache.get(path, load, [{"stale": True}]), [])
        self.assertEqual(loads, [1])
        self.assertIn("no agent token is accepted", err.getvalue())

    def test_an_unreadable_token_file_accepts_no_token(self):
        """A broken tokens.json warns and yields no rows (fail closed); the CLI's strict read refuses it."""
        (self.dir / "tokens.json").write_text("{broken", encoding="utf-8")
        with mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(access.load_tokens(self.dir), [])
        self.assertIn("no agent token is accepted", err.getvalue())
        with self.assertRaises(ValueError):
            access.load_tokens(self.dir, strict=True)

    def test_the_warning_prints_once_across_threads(self):
        """Many concurrent first calls print one line."""
        warn = access.WarnOnce("the loopback agent is deprecated")
        with mock.patch("sys.stderr", io.StringIO()) as err:
            threads = [threading.Thread(target=warn) for _ in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(err.getvalue(), "warning: the loopback agent is deprecated\n")


class StateHelpers(unittest.TestCase):
    """The helpers behind `limn token` / `limn member`, with a recording audit sink."""

    def setUp(self):
        """A temp state folder and a list the audit sink records into."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        self.audits = []

    def audit(self, action, details):
        """The recording audit sink."""
        self.audits.append((action, details))

    def test_a_token_is_stored_hashed_0600_and_audited_without_the_secret(self):
        """The plaintext is returned once; the file and the audit line never carry it or its hash."""
        entry, plain = access.token_create(self.state, None, self.audit)
        raw = (self.state / "tokens.json").read_text(encoding="utf-8")
        self.assertNotIn(plain, raw)
        self.assertEqual(stat.S_IMODE((self.state / "tokens.json").stat().st_mode), 0o600)
        self.assertEqual(self.audits, [("token_created", {"id": entry["id"], "name": "agent"})])
        self.assertIsNone(access.token_lookup("limn_other", access.load_tokens(self.state)))
        self.assertEqual(access.token_lookup(plain, access.load_tokens(self.state))["id"], entry["id"])

    def test_a_refused_token_or_member_change_writes_and_audits_nothing(self):
        """A bad name, a taken name, an unknown ref, a bad login or role: no file change, no audit line."""
        access.token_create(self.state, "ci", self.audit)
        before = (self.state / "tokens.json").read_bytes()
        self.audits.clear()
        for name in ("ci", "bad name", "-x"):
            with self.assertRaises(ValueError):
                access.token_create(self.state, name, self.audit)
        self.assertIsNone(access.token_revoke(self.state, "nope", self.audit))
        for login, role in (("local", "editor"), ("agent:ci", "editor"), ("a b", "editor"), ("c@example.com", "admin")):
            with self.assertRaises(ValueError):
                access.member_add(self.state, login, role, None, self.audit)
        self.assertEqual((self.state / "tokens.json").read_bytes(), before)
        self.assertFalse((self.state / "people.json").exists())
        self.assertEqual(self.audits, [])

    def test_member_changes_are_audited_in_order(self):
        """add, a role change, a no-op role set (no audit) and a removal, each after its write."""
        access.member_add(self.state, "bob@example.com", "editor", None, self.audit)
        access.member_set_role(self.state, "bob@example.com", "viewer", self.audit)
        access.member_set_role(self.state, "bob@example.com", "viewer", self.audit)
        self.assertEqual(access.roles_of(access.load_people_file(self.state)), {"bob@example.com": "viewer"})
        access.member_remove(self.state, "bob@example.com", self.audit)
        self.assertEqual([a for a, _ in self.audits], ["member_added", "member_role", "member_removed"])
        self.assertEqual(stat.S_IMODE((self.state / "people.json").stat().st_mode), 0o600)

    def test_an_unreadable_people_file_is_never_overwritten(self):
        """The CLI refuses to rewrite a people.json it could not read."""
        (self.state / "people.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            access.member_add(self.state, "bob@example.com", "editor", None, self.audit)
        self.assertEqual((self.state / "people.json").read_text(encoding="utf-8"), "{broken")


class Guidance(unittest.TestCase):
    """The token-file wording shared by the 401 and pins.md."""

    def test_the_401_names_the_file_and_how_to_make_it(self):
        """The known file in ~ form; the create hint only while the file does not exist; the convention otherwise."""
        home = PurePath("/home/u")
        text = guidance.loopback_refused_text(PurePath("/home/u/.config/limn/paper.token"), False, home)
        self.assertTrue(text.startswith(guidance.UNAUTHENTICATED))
        self.assertIn("$(cat ~/.config/limn/paper.token)", text)
        self.assertIn("limn token create paper --save", text)
        self.assertNotIn("--save", guidance.loopback_refused_text(PurePath("/home/u/p.token"), True, home))
        self.assertIn(guidance.TOKEN_FILE_EXAMPLE, guidance.loopback_refused_text(None, False, home))


if __name__ == "__main__":
    unittest.main()
