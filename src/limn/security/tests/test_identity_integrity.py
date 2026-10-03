"""Provider identity decoding must never turn a malformed login into another principal."""

from email.header import Header
from email.message import Message
from ipaddress import ip_network

import pytest
from hypothesis import given, strategies as st

from limn.security.access import AccessLookups, AccessSettings, actor_of, identify
from limn.web.errors import HTTPError


def identity_settings(provider: str, email: bool = False) -> AccessSettings:
    """Use a loopback proxy and member filtering without any anonymous-agent fallback."""
    return AccessSettings(
        auth=provider,
        agent_loopback=False,
        tailnet_agent=False,
        trusted_proxies=(ip_network("127.0.0.1/32"),),
        proxy_user_header="X-User",
        proxy_name_header="X-Name",
        proxy_email_header="X-Email" if email else None,
        members_only=True,
        allow=frozenset(),
        local_user=None,
        agent_token_file=None,
    )


@pytest.mark.parametrize("provider", ["tailscale", "trusted-proxy", "proxy-email"])
@pytest.mark.parametrize("encoding", ["plain", "rfc2047", "padded-rfc2047"])
@pytest.mark.parametrize(
    ("login", "owner"),
    [
        ("a" * 200 + "different-account", "a" * 200),
        ("al\tice@example.com", "alice@example.com"),
        ("alice@example.com\x7f", "alice@example.com"),
        ("alice@example.com ", "alice@example.com"),
    ],
)
def test_malformed_identity_cannot_inherit_an_owner_role(provider, encoding, login, owner):
    """Truncation and control removal must not grant a known owner's identity or membership."""
    headers = Message()
    if encoding != "plain":
        login = Header(login, "utf-8").encode()
        if encoding == "padded-rfc2047":
            login = " " + login
    if provider == "tailscale":
        headers["Tailscale-User-Login"] = login
    else:
        headers["X-User"] = "other@example.com" if provider == "proxy-email" else login
        if provider == "proxy-email":
            headers["X-Email"] = login
    lookups = AccessLookups(lambda: [], lambda: {owner: "owner"}, lambda: None)
    with pytest.raises(HTTPError) as refused:
        identify(
            headers,
            "127.0.0.1",
            identity_settings("trusted-proxy" if provider == "proxy-email" else provider, provider == "proxy-email"),
            lookups,
        )
    assert (refused.value.code, refused.value.body["reason"]) == (401, "unauthenticated")


@pytest.mark.parametrize("provider", ["tailscale", "trusted-proxy"])
@pytest.mark.parametrize(
    ("raw_login", "owner"),
    [
        (" =?utf-8?q?alice=40example=2Ecom?=", "alice@example.com"),
        ("\t=?utf-8?q?alice=40example=2Ecom?=", "alice@example.com"),
        ("=?utf-8?q?alice=40?=\n\t=?utf-8?q?example=2Ecom?=", "alice@example.com"),
        ("=?unknown-8bit?q?alice=FF=40example=2Ecom?=", "alice\ufffd@example.com"),
    ],
)
def test_lossy_header_decoding_cannot_select_an_owner(provider, raw_login, owner):
    """Encoded headers cannot drop whitespace or raw controls or replace undecodable bytes to inherit a role."""
    headers = Message()
    headers["Tailscale-User-Login" if provider == "tailscale" else "X-User"] = raw_login
    with pytest.raises(HTTPError) as refused:
        identify(
            headers,
            "127.0.0.1",
            identity_settings(provider),
            AccessLookups(lambda: [], lambda: {owner: "owner"}, lambda: None),
        )
    assert (refused.value.code, refused.value.body["reason"]) == (401, "unauthenticated")


@pytest.mark.parametrize("provider", ["tailscale", "trusted-proxy"])
def test_encoded_unicode_identity_preserves_the_verified_login(provider):
    """RFC 2047 transport decoding preserves a complete Unicode login and its role."""
    login = "가@example.com"
    headers = Message()
    headers["Tailscale-User-Login" if provider == "tailscale" else "X-User"] = Header(login, "utf-8").encode()
    principal = identify(
        headers,
        "127.0.0.1",
        identity_settings(provider),
        AccessLookups(lambda: [], lambda: {login: "viewer"}, lambda: None),
    )
    assert (principal.actor["login"], principal.role) == (login, "viewer")


@given(st.text(alphabet="abcXYZ012@._-\t\x7f", min_size=1, max_size=240))
def test_plain_identity_is_preserved_or_refused(login):
    """Any nonempty plaintext identity is accepted unchanged or refused, never repaired."""
    headers = Message()
    headers["Tailscale-User-Login"] = login
    try:
        actor, from_header = actor_of(headers)
    except HTTPError as refused:
        assert (refused.code, refused.body["reason"]) == (401, "unauthenticated")
        return
    assert from_header
    assert actor["login"] == login
    assert len(login) <= 200 and login.isprintable()
