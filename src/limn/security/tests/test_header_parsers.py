"""The request-header parsers of the trust boundary answer every input with a value or their named refusal.

Each parser reads text a client chose: Authorization (bearer_of), Host (split_host), Origin against Host (origin_ok),
the Tailscale-User-* identity headers (actor_of), and the --trusted-proxies list (parse_networks). Generated inputs check
that none of them crashes on another exception, and that the properties the access rules rely on hold: a Bearer token
round-trips, Host names come back lowercase with an in-range port, a loopback Host accepts only a loopback Origin, the
identity fields stay within their bounds, and every listed address is in the parsed networks.

Header values are drawn from printable Latin-1 without CR/LF, which is what http.server hands the handler.
"""

import ipaddress
from email.message import Message

import pytest
from hypothesis import given, strategies as st

from limn.security import access
from limn.web.errors import HTTPError

LATIN1 = st.characters(min_codepoint=0x20, max_codepoint=0xFF, blacklist_characters="\x7f")
HEADER_TEXT = st.text(alphabet=LATIN1)
# Values past the identity bounds (login 200, name 100, picture 1000), which plain text rarely reaches.
LONG_TEXT = HEADER_TEXT | st.text(alphabet=LATIN1, min_size=90, max_size=1200)
TOKEN = st.text(alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E), min_size=1, max_size=80)
LABEL = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,20}[a-z0-9])?", fullmatch=True)
HOST_NAME = st.lists(LABEL, min_size=1, max_size=4).map(".".join)
PORT = st.integers(min_value=0, max_value=65535)


def headers(**values):
    """A Message holding each name's value or list of values, as the handler receives request headers."""
    msg = Message()
    for name, value in values.items():
        for v in value if isinstance(value, list) else [value]:
            msg[name.replace("_", "-")] = v
    return msg


@given(st.lists(HEADER_TEXT, max_size=3))
def test_bearer_of_answers_none_a_token_or_bad_bearer(values):
    """Any Authorization headers yield no token, a non-blank token, or a 401 bad_bearer - never another exception."""
    try:
        token = access.bearer_of(headers(Authorization=values))
    except HTTPError as e:
        assert (e.code, e.body["reason"]) == (401, "bad_bearer")
        return
    assert token is None or (token.strip() == token and token)


@given(st.sampled_from(["Bearer", "bearer", "BEARER"]), TOKEN, st.sampled_from(["", " ", "  "]))
def test_bearer_of_returns_the_token_it_was_given(scheme, token, pad):
    """`Bearer <token>` with any scheme case and surrounding blanks gives back exactly the token."""
    assert access.bearer_of(headers(Authorization="%s%s %s%s" % (pad, scheme, token, pad))) == token


@given(HEADER_TEXT)
def test_split_host_answers_a_normalized_name_and_port(raw):
    """Any Host text gives a lowercase name without a trailing dot and a port of at most five digits, or ('', None)."""
    name, port = access.split_host(raw)
    assert name == name.lower() and not name.endswith(".")
    assert port is None or 0 <= port <= 99999


@given(HOST_NAME, st.none() | PORT, st.booleans())
def test_split_host_round_trips_a_name_and_port(name, port, upper):
    """`name[:port]`, in any letter case, comes back as the lowercase name and the port."""
    raw = (name.upper() if upper else name) + ("" if port is None else ":%d" % port)
    assert access.split_host(raw) == (name, port)


@given(HEADER_TEXT, HEADER_TEXT)
def test_origin_ok_answers_a_bool_for_any_origin_and_host(origin, host):
    """origin_ok never raises on what a client sends; it only says yes or no."""
    assert access.origin_ok(origin, host, ()) in (True, False)


@given(
    st.sampled_from(["http", "https"]),
    HOST_NAME | st.sampled_from(["box.tail1234.ts.net", "limn.example.com"]),
    st.none() | PORT.filter(bool),
    st.sampled_from(["localhost", "127.0.0.1", "[::1]", "localhost:18004", ""]),
)
def test_a_loopback_host_accepts_only_a_loopback_origin(scheme, name, port, host):
    """With a loopback Host (or none), an Origin is accepted exactly when its own host is loopback - so a tailnet or
    public page cannot drive the local user's browser against this server."""
    origin = "%s://%s%s" % (scheme, name, "" if port is None else ":%d" % port)
    assert access.origin_ok(origin, host, ()) == (name in access.LOOPBACK)


@given(LONG_TEXT, LONG_TEXT, LONG_TEXT | st.text(alphabet=LATIN1, max_size=1100).map("https://".__add__))
def test_actor_of_keeps_identity_fields_within_their_bounds(login, name, pic):
    """Any Tailscale-User-* values give a login of at most 200 and a name of at most 100 characters, and a picture
    only when it is an https URL of at most 1000 characters; without a login the request is the local actor."""
    actor, from_header = access.actor_of(
        headers(Tailscale_User_Login=login, Tailscale_User_Name=name, Tailscale_User_Profile_Pic=pic)
    )
    if not from_header:
        assert actor == access.LOCAL_ACTOR
        return
    assert 0 < len(actor["login"]) <= 200 and len(actor["name"]) <= 100
    assert "pic" not in actor or (actor["pic"].startswith("https://") and len(actor["pic"]) <= 1000)


@given(HEADER_TEXT)
def test_parse_networks_answers_networks_or_value_error(spec):
    """Any --trusted-proxies text gives at least one network or a ValueError - never another exception."""
    try:
        nets = access.parse_networks(spec)
    except ValueError:
        return
    assert nets and all(isinstance(n, (ipaddress.IPv4Network, ipaddress.IPv6Network)) for n in nets)


@given(st.lists(st.ip_addresses(), min_size=1, max_size=5), st.sampled_from([",", ", ", " ,"]))
def test_parse_networks_contains_every_listed_address(addresses, sep):
    """A comma-separated list of addresses parses to networks that contain each address."""
    nets = access.parse_networks(sep.join(str(a) for a in addresses))
    assert all(any(a in n for n in nets) for a in addresses)


@pytest.mark.parametrize("spec", ["", " , ", "10.0.0.1,not-an-ip"])
def test_parse_networks_refuses_an_empty_or_bad_list(spec):
    """An empty list and a list with a non-address entry are refused rather than trusting nothing or something else."""
    with pytest.raises(ValueError):
        access.parse_networks(spec)
