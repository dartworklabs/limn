"""limn.security.access.request_identity tested directly: the identity a request is recorded as, named for pins.md.

GET /pins.md tells its reader who the request is (docs/handbook/api.md §pins.md 요청자 줄). The value comes from the
principal identify() decided and the instance's identity provider; this file pins how each principal and provider map
to a name, login, role and identity source, and which sources are a person's identity. The HTTP path is tested in
src/limn/pins/tests/test_render.py (PinsMdRequester).

Run: uv run pytest -q src/limn/security/tests/test_request_identity.py
"""

import unittest

from limn.security.access import LOCAL_ACTOR, PERSON_SOURCES, Principal, RequestIdentity, request_identity

ALICE = {"login": "alice@example.com", "name": "Alice Kim"}


class RequestIdentityOf(unittest.TestCase):
    """request_identity(principal, provider) names who the request is and where that identity came from."""

    def test_tailnet_header(self):
        """A person vouched for by Tailscale headers is a tailnet-header person."""
        got = request_identity(Principal(dict(ALICE), "editor", "header"), "tailscale")
        self.assertEqual(got, RequestIdentity("Alice Kim", "alice@example.com", "editor", "tailnet-header"))
        self.assertTrue(got.is_person())

    def test_proxy_header(self):
        """The same header principal under --auth trusted-proxy came from the proxy's user header."""
        got = request_identity(Principal(dict(ALICE), "editor", "header"), "trusted-proxy")
        self.assertEqual(got.source, "proxy-header")
        self.assertTrue(got.is_person())

    def test_local_owner(self):
        """The loopback owner under --auth local is a person."""
        got = request_identity(Principal({"login": "alice", "name": "alice"}, "owner", "local-owner"), "local")
        self.assertEqual(got, RequestIdentity("alice", "alice", "owner", "local-owner"))
        self.assertTrue(got.is_person())

    def test_token(self):
        """A token principal is the agent agent:<name>, not a person."""
        got = request_identity(
            Principal({"login": "agent:reviewer", "name": "reviewer"}, "agent", "token"), "tailscale"
        )
        self.assertEqual(got, RequestIdentity("reviewer", "agent:reviewer", "agent", "token"))
        self.assertFalse(got.is_person())

    def test_loopback_agent(self):
        """The headerless loopback agent is the local agent, not a person."""
        got = request_identity(Principal(dict(LOCAL_ACTOR), "agent", "loopback-agent"), "tailscale")
        self.assertEqual(got, RequestIdentity("로컬/에이전트", "local", "agent", "loopback-agent"))
        self.assertFalse(got.is_person())

    def test_agent_role_person_is_a_person(self):
        """A person whose people.json role is agent is still recorded under their own login: a person's identity."""
        got = request_identity(Principal(dict(ALICE), "agent", "header"), "tailscale")
        self.assertEqual((got.source, got.role), ("tailnet-header", "agent"))
        self.assertTrue(got.is_person())

    def test_empty_name_falls_back_to_login(self):
        """A principal without a display name is named by its login, missing or empty alike."""
        for actor in ({"login": "alice@example.com", "name": ""}, {"login": "alice@example.com"}):
            got = request_identity(Principal(actor, "editor", "header"), "tailscale")
            self.assertEqual(got.name, "alice@example.com")

    def test_person_sources_are_the_three_header_and_owner_sources(self):
        """Exactly the tailnet header, the proxy header and the local owner are a person's identity."""
        self.assertEqual(PERSON_SOURCES, frozenset({"tailnet-header", "proxy-header", "local-owner"}))


if __name__ == "__main__":
    unittest.main()
