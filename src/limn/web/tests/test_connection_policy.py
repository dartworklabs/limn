"""Pure leases reject over-capacity, stale cleanup and entry after irreversible stop."""

from dataclasses import FrozenInstanceError, replace

import pytest
from hypothesis import given, strategies as st

from limn.web.connection_policy import (
    AdmissionState,
    Cancelled,
    Claimed,
    Full,
    LeaseToken,
    Reserved,
    Stopped,
    admitted,
    claim,
    release,
    reserve,
    stop,
)


def test_capacity_claim_and_stop_preserve_cleanup_ownership():
    """Stopping entry keeps both pending and claimed leases until attested cleanup."""
    first = reserve(AdmissionState(2, object()))
    assert isinstance(first, Reserved)
    second = reserve(first.state)
    assert isinstance(second, Reserved)
    assert reserve(second.state) == Full()
    claimed = claim(second.state, first.token)
    assert isinstance(claimed, Claimed)
    stopped = stop(claimed.state)
    assert reserve(stopped) == Stopped()
    assert claim(stopped, second.token) == Cancelled()
    assert stopped.pending == frozenset({second.token})
    assert stopped.claimed == frozenset({first.token})
    assert admitted(stopped) == 2
    cleaned = release(release(stopped, first.token), second.token)
    assert admitted(cleaned) == 0
    assert cleaned.stopped
    assert stop(cleaned) == cleaned


def test_old_cleanup_cannot_release_a_new_lease():
    """A retired generation cannot free a later lease on the same listener."""
    first = reserve(AdmissionState(1, object()))
    assert isinstance(first, Reserved)
    second = reserve(release(first.state, first.token))
    assert isinstance(second, Reserved)
    assert second.token.generation > first.token.generation
    unchanged = release(second.state, first.token)
    assert admitted(unchanged) == 1
    assert unchanged == second.state
    assert claim(unchanged, first.token) == Cancelled()


def test_foreign_generation_and_duplicate_cleanup_are_absorbing():
    """A matching generation from another listener grants no cleanup authority."""
    current = reserve(AdmissionState(1, object()))
    foreign = reserve(AdmissionState(1, object()))
    assert isinstance(current, Reserved) and isinstance(foreign, Reserved)
    assert current.token.generation == foreign.token.generation
    assert release(current.state, foreign.token) == current.state
    assert claim(current.state, foreign.token) == Cancelled()
    cleaned = release(current.state, current.token)
    assert release(cleaned, current.token) == cleaned
    assert admitted(cleaned) == 0


def test_values_are_frozen_and_owner_uses_identity():
    """Caller equality overrides cannot merge two opaque listener identities."""

    class EqualOwner:
        """Distinct instances deliberately compare alike to challenge opaque identity."""

        def __eq__(self, other):
            """Return equality for every owner while remaining distinct objects."""
            return isinstance(other, EqualOwner)

        def __hash__(self):
            """Return the same hash without asserting identity."""
            return 1

    current = reserve(AdmissionState(1, EqualOwner()))
    foreign = LeaseToken(EqualOwner(), 0)
    assert isinstance(current, Reserved)
    assert release(current.state, foreign) == current.state
    assert current.token != foreign
    with pytest.raises(FrozenInstanceError):
        current.state.limit = 2
    with pytest.raises(FrozenInstanceError):
        current.token.generation = 9


@pytest.mark.parametrize("limit", [0, -1, True, False, 1.5, "1"])
def test_invalid_capacity_cannot_construct_state(limit):
    """Invalid or boolean limits cannot represent a listener's capacity."""
    with pytest.raises(ValueError):
        AdmissionState(limit, object())


@pytest.mark.parametrize("generation", [-1, True, 1.5, "0"])
def test_invalid_generation_cannot_construct_values(generation):
    """Only nonnegative integer generations can identify issued leases."""
    with pytest.raises(ValueError):
        LeaseToken(object(), generation)
    with pytest.raises(ValueError):
        AdmissionState(1, object(), next_generation=generation)


def test_invalid_live_sets_cannot_construct_state():
    """Foreign, unissued, overlapping, mutable and over-capacity ownership are rejected."""
    owner = object()
    token = LeaseToken(owner, 0)
    cases = [
        {"pending": frozenset({LeaseToken(object(), 0)}), "next_generation": 1},
        {"pending": frozenset({token})},
        {"pending": frozenset({token}), "claimed": frozenset({token}), "next_generation": 1},
        {"pending": frozenset({token, LeaseToken(owner, 1)}), "next_generation": 2},
        {"pending": {token}, "next_generation": 1},
        {"pending": frozenset({object()}), "next_generation": 1},
        {"stopped": 1},
    ]
    for invalid in cases:
        with pytest.raises(ValueError):
            AdmissionState(1, owner, **invalid)


@given(
    st.lists(
        st.sampled_from(("reserve", "claim", "release", "duplicate_release", "stale_release", "stop")), max_size=80
    )
)
def test_generated_lifecycle_never_exceeds_capacity(events):
    """Generated lifecycles preserve capacity and never reopen after stopping."""
    state = AdmissionState(3, object())
    tokens = []
    retired = []
    ever_stopped = False
    for event in events:
        if event == "reserve":
            result = reserve(state)
            if ever_stopped:
                assert result == Stopped()
            elif admitted(state) == state.limit:
                assert result == Full()
            else:
                assert isinstance(result, Reserved)
                state = result.state
                tokens.append(result.token)
        elif event == "claim" and tokens:
            token = tokens[-1]
            result = claim(state, token)
            if ever_stopped or token not in state.pending:
                assert result == Cancelled()
            else:
                assert isinstance(result, Claimed)
                assert result.state.pending == state.pending - {token}
                assert result.state.claimed == state.claimed | {token}
                state = result.state
        elif event == "release" and tokens:
            token = tokens.pop(0)
            before = admitted(state)
            state = release(state, token)
            assert admitted(state) == before - 1
            retired.append(token)
        elif event in ("duplicate_release", "stale_release") and retired:
            assert release(state, retired[0]) == state
        elif event == "stop":
            before = state
            state = stop(state)
            assert state.pending == before.pending and state.claimed == before.claimed
            ever_stopped = True
        assert 0 <= admitted(state) <= 3
        assert not ever_stopped or state.stopped
        assert state.pending.isdisjoint(state.claimed)
        assert state.pending | state.claimed == frozenset(tokens)


@given(st.lists(st.booleans(), min_size=1, max_size=80))
def test_generated_retirement_rejects_stale_foreign_and_duplicate_tokens(claims):
    """Repeated generations retain only live ownership and never accept foreign cleanup."""
    state = AdmissionState(1, object())
    retired = []
    for should_claim in claims:
        result = reserve(state)
        assert isinstance(result, Reserved)
        state = result.state
        foreign = LeaseToken(object(), result.token.generation)
        assert release(state, foreign) == state
        assert claim(state, foreign) == Cancelled()
        for stale in retired:
            assert release(state, stale) == state
            assert claim(state, stale) == Cancelled()
        if should_claim:
            entered = claim(state, result.token)
            assert isinstance(entered, Claimed)
            state = entered.state
            assert claim(state, result.token) == Cancelled()
        state = release(state, result.token)
        assert admitted(state) == 0
        assert state.pending == state.claimed == frozenset()
        assert release(state, result.token) == state
        retired.append(result.token)
    assert state.next_generation == len(claims)


@given(st.integers(min_value=1, max_value=8), st.integers(min_value=0, max_value=8))
def test_generated_stop_fences_pending_but_keeps_claimed_ownership(limit, claimed_count):
    """Stopping any mix of pending and claimed leases forbids entry until cleanup."""
    state = AdmissionState(limit, object())
    tokens = []
    for _ in range(limit):
        result = reserve(state)
        assert isinstance(result, Reserved)
        state = result.state
        tokens.append(result.token)
    for token in tokens[:claimed_count]:
        result = claim(state, token)
        assert isinstance(result, Claimed)
        state = result.state
    stopped = stop(state)
    assert stopped == replace(state, stopped=True)
    for token in tokens:
        assert claim(stopped, token) == Cancelled()
    assert reserve(stopped) == Stopped()
    assert admitted(stopped) == limit
    for remaining, token in enumerate(tokens):
        stopped = release(stopped, token)
        assert admitted(stopped) == limit - remaining - 1
        assert reserve(stopped) == Stopped()
