"""Tests for pin claiming and unclaiming feature slice.

Colocated feature tests verifying:
- Input parsing and validation (parse_claim_body, clamping, reject negative/float)
- State transitions under claim and unclaim via PinClaims service
- HTTP handler responses and error codes via ClaimsApp protocol
"""

import threading
from collections.abc import Callable
from typing import Any

import pytest

from limn.features.pins.claims import http
from limn.features.pins.claims.input import (
    CLAIM_ETA_MAX,
    CLAIM_TTL_DEFAULT,
    CLAIM_TTL_MAX,
    ClaimBody,
    parse_claim_body,
)
from limn.features.pins.claims.service import PinClaims
from limn.mentions import NoteTags
from limn.pins.model import OpenPin, Pin, PinNotFound, Record
from limn.service.context import PinContext
from limn.web.errors import HTTPError, InputRejected

# ---------------------------------------------------------------------------
# Test Fixtures & In-Memory Fake Context
# ---------------------------------------------------------------------------


class FakePinStore:
    """In-memory pin store for slice tests without file system access."""

    def __init__(self, initial_pins: list[Pin]) -> None:
        self.pins: list[Pin] = list(initial_pins)
        self.lock = threading.RLock()

    def transact(self, fn: Callable[[list[Pin]], tuple[Any, bool]]) -> tuple[bool, Any]:
        with self.lock:
            result, changed = fn(self.pins)
            return changed, result


def make_test_context(store: FakePinStore, now_epoch: float = 1790000000.0) -> PinContext:
    """Build a minimal PinContext for unit testing PinClaims."""
    return PinContext(
        store=store,  # type: ignore[arg-type]
        now=lambda: "2026-09-28 12:00:00",
        epoch=lambda: now_epoch,
        hm=lambda: "12:00",
        make_event=lambda *args, **kwargs: None,
        emit_events=lambda events: None,
        who=lambda actor: {"login": actor.get("login", "local"), "name": actor.get("name", "")},
        audit=lambda *args: None,
        known_people=lambda pins: {},
        note_tags=lambda note, old_note, pins, hints, actor, pid: NoteTags((), []),
        role_of=lambda login: "owner",
        person_name=lambda login: login,
        locate=lambda r: None,
        stamp=lambda r: None,
        thread_max=100,
        trash_days=30,
        trash_checked=[0.0],
    )


class FakeClaimsApp:
    """Collaborator implementing ClaimsApp protocol."""

    def __init__(self, pin_claims: PinClaims) -> None:
        self.pin_claims = pin_claims

    def public(self, record: Record) -> dict[str, Any]:
        return dict(record)


# ---------------------------------------------------------------------------
# 1. Input Parsing Tests
# ---------------------------------------------------------------------------


class TestClaimInputParsing:
    """Unit tests for parse_claim_body."""

    def test_default_when_empty(self) -> None:
        result = parse_claim_body({})
        assert isinstance(result, ClaimBody)
        assert result.ttl == CLAIM_TTL_DEFAULT
        assert result.eta is None

    def test_eta_only_calculates_ttl(self) -> None:
        result = parse_claim_body({"eta_min": 10})
        assert isinstance(result, ClaimBody)
        assert result.eta == 10
        # ttl is min(120, max(30, eta * 2)) -> max(30, 20) = 30
        assert result.ttl == 30

        result_large = parse_claim_body({"eta_min": 50})
        assert isinstance(result_large, ClaimBody)
        assert result_large.eta == 50
        # max(30, 50 * 2) = 100
        assert result_large.ttl == 100

    def test_clamping_exceeding_values(self) -> None:
        result = parse_claim_body({"ttl_min": 480, "eta_min": 300})
        assert isinstance(result, ClaimBody)
        assert result.ttl == CLAIM_TTL_MAX
        assert result.eta == CLAIM_ETA_MAX

    def test_rejection_of_non_integers(self) -> None:
        for bad in ({"eta_min": "15"}, {"eta_min": 15.5}, {"eta_min": True}, {"eta_min": None}):
            res = parse_claim_body(bad)
            assert isinstance(res, InputRejected)
            assert res.reason == "not_integer"

        for bad in ({"ttl_min": "60"}, {"ttl_min": 60.5}, {"ttl_min": True}):
            res = parse_claim_body(bad)
            assert isinstance(res, InputRejected)
            assert res.reason == "not_integer"

    def test_rejection_of_too_small_values(self) -> None:
        res = parse_claim_body({"eta_min": 0})
        assert isinstance(res, InputRejected)
        assert res.reason == "too_small"

        res = parse_claim_body({"ttl_min": 0})
        assert isinstance(res, InputRejected)
        assert res.reason == "too_small"


# ---------------------------------------------------------------------------
# 2. Slice Service & State Transition Tests
# ---------------------------------------------------------------------------


class TestPinClaimsService:
    """State transition tests on PinClaims service."""

    def test_claim_open_pin_succeeds(self) -> None:
        initial_pin = OpenPin.from_record({"id": 1, "file": "main.tex", "lo": 1, "hi": 2, "note": "test"})
        store = FakePinStore([initial_pin])
        ctx = make_test_context(store, now_epoch=1000.0)
        claims = PinClaims(lambda: ctx)

        actor = {"login": "alice@example.com", "name": "Alice"}
        result = claims.claim_pin(1, actor, ttl_min=30, eta_min=15)

        assert isinstance(result, OpenPin)
        assert result.record["claimed_by"]["login"] == "alice@example.com"
        assert result.record["claim_ts"] == 1000.0
        assert result.record["claim_until"] == 1000.0 + 30 * 60
        assert result.record["eta_ts"] == 1000.0 + 15 * 60

    def test_claim_pin_not_found(self) -> None:
        store = FakePinStore([])
        ctx = make_test_context(store)
        claims = PinClaims(lambda: ctx)

        result = claims.claim_pin(999, {"login": "alice"}, ttl_min=30)
        assert isinstance(result, PinNotFound)

    def test_unclaim_clears_claim_marker(self) -> None:
        initial_pin = OpenPin.from_record(
            {
                "id": 1,
                "file": "main.tex",
                "lo": 1,
                "hi": 2,
                "claimed_by": {"login": "alice@example.com"},
                "claim_until": 2000.0,
                "rev": 1,
            }
        )
        store = FakePinStore([initial_pin])
        ctx = make_test_context(store)
        claims = PinClaims(lambda: ctx)

        result = claims.unclaim_pin(1, {"login": "bob"})
        assert isinstance(result, OpenPin)
        assert "claimed_by" not in result.record
        assert "claim_until" not in result.record
        assert result.record["rev"] == 2


# ---------------------------------------------------------------------------
# 3. HTTP Layer Tests (Routing, Answer and Protocol Adapter)
# ---------------------------------------------------------------------------


class TestClaimHttpAdapter:
    """HTTP endpoint logic tests using ClaimsApp protocol."""

    def test_http_claim_and_unclaim_flow(self) -> None:
        initial_pin = OpenPin.from_record({"id": 1, "file": "main.tex", "lo": 1, "hi": 2})
        store = FakePinStore([initial_pin])
        ctx = make_test_context(store, now_epoch=1000.0)
        claims = PinClaims(lambda: ctx)
        app = FakeClaimsApp(claims)

        actor = {"login": "alice@example.com", "name": "Alice"}
        resp = http.claim(app, 1, actor, {"eta_min": 15})

        assert resp["ok"] is True
        assert resp["ttl_min_applied"] == 30
        assert resp["eta_min_applied"] == 15
        assert isinstance(resp["pin"], dict)
        assert resp["pin"]["claimed_by"]["login"] == "alice@example.com"

        # Now unclaim
        unclaim_resp = http.unclaim(app, 1, actor)
        assert unclaim_resp["ok"] is True
        pin_unclaimed = unclaim_resp["pin"]
        assert isinstance(pin_unclaimed, dict)
        assert "claimed_by" not in pin_unclaimed

    def test_http_claim_conflict_raises_409(self) -> None:
        initial_pin = OpenPin.from_record(
            {
                "id": 1,
                "file": "main.tex",
                "lo": 1,
                "hi": 2,
                "claimed_by": {"login": "alice@example.com"},
                "claim_until": 2000.0,
            }
        )
        store = FakePinStore([initial_pin])
        ctx = make_test_context(store, now_epoch=1000.0)
        claims = PinClaims(lambda: ctx)
        app = FakeClaimsApp(claims)

        # Bob attempts claim while Alice holds it
        with pytest.raises(HTTPError) as exc_info:
            http.claim(app, 1, {"login": "bob@example.com"}, {"ttl_min": 30})

        err = exc_info.value
        assert err.code == 409
        assert err.body["reason"] == "claimed"
        assert err.body["claimed_by"] == {"login": "alice@example.com"}
