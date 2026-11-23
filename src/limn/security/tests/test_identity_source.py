"""limn.security.access.identity_source tested directly: where a request's identity came from, named for pins.md.

GET /pins.md tells its reader who the request is recorded as (docs/handbook/api.md §pins.md 요청자 줄). The source comes
from how identify() knew the principal (Via) and the instance's identity provider; this file pins that mapping for every
Via and which sources are a person's identity. The line itself is tested in src/limn/pins/tests/test_render.py
(RequesterLine, PinsMdRequester).

Run: uv run pytest -q src/limn/security/tests/test_identity_source.py
"""

import unittest
from typing import get_args

from limn.security.access import LOCAL_ACTOR, PERSON_SOURCES, IdentitySource, Principal, identity_source

ALICE = {"login": "alice@example.com", "name": "Alice Kim"}


class IdentitySourceOf(unittest.TestCase):
    """identity_source(principal, provider) names where the principal's identity came from."""

    def test_header_under_tailscale_is_the_tailnet_header(self):
        """A person vouched for by Tailscale headers came through the tailnet header."""
        self.assertEqual(identity_source(Principal(dict(ALICE), "editor", "header"), "tailscale"), "tailnet-header")

    def test_header_under_trusted_proxy_is_the_proxy_header(self):
        """The same header principal under --auth trusted-proxy came from the proxy's user header."""
        self.assertEqual(identity_source(Principal(dict(ALICE), "editor", "header"), "trusted-proxy"), "proxy-header")

    def test_local_owner(self):
        """The loopback owner under --auth local is the local owner."""
        p = Principal({"login": "alice", "name": "alice"}, "owner", "local-owner")
        self.assertEqual(identity_source(p, "local"), "local-owner")

    def test_token(self):
        """A token principal came through its token, under any provider."""
        p = Principal({"login": "agent:reviewer", "name": "reviewer"}, "agent", "token")
        for auth in ("tailscale", "local", "trusted-proxy"):
            self.assertEqual(identity_source(p, auth), "token")

    def test_loopback_agent(self):
        """The headerless loopback agent is the loopback agent."""
        p = Principal(dict(LOCAL_ACTOR), "agent", "loopback-agent")
        self.assertEqual(identity_source(p, "tailscale"), "loopback-agent")

    def test_agent_role_person_is_still_a_header_person(self):
        """A person whose people.json role is agent keeps the header source: the record carries their login."""
        source = identity_source(Principal(dict(ALICE), "agent", "header"), "tailscale")
        self.assertIn(source, PERSON_SOURCES)

    def test_person_sources_are_the_two_headers_and_the_local_owner(self):
        """Exactly the tailnet header, the proxy header and the local owner are a person's identity."""
        self.assertEqual(PERSON_SOURCES, frozenset({"tailnet-header", "proxy-header", "local-owner"}))
        self.assertEqual(set(get_args(IdentitySource)) - PERSON_SOURCES, {"token", "loopback-agent"})


if __name__ == "__main__":
    unittest.main()
