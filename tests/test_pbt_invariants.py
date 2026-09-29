"""Property-based testing (PBT) for domain invariants and algebraic properties using Hypothesis.

Covers:
1. Shape type-guards (is_int, is_num, is_finite_num) against arbitrary Python and JSON types.
2. Text normalization and truncation invariants (truncate_quote, flat, norm).
3. Cluster mapping invariant for SyncTeX source line picking (densest).
4. Line range overlap geometry and algebraic symmetry (range_rel, _reverse_rel).
5. State machine transition invariants for pin lifecycles (reopens_on_reply, confirm, evolve_close).
6. Lossless round-trip invariants for parse_pin across generated valid record structures.
"""

import json
import math
from collections.abc import Sequence

from hypothesis import given, strategies as st

from limn.features.pins.lifecycle.rules import (
    AlreadyDone,
    PinClosed,
    PinStillOpen,
    confirm,
    evolve_close,
    reopens_on_reply,
)
from limn.mapping import densest, flat, norm, truncate_quote
from limn.pins.lifecycle import CLAIM_FIELDS, rev_after
from limn.pins.model import (
    Actor,
    Agent,
    DonePin,
    OpenPin,
    Person,
    Pin,
    ReviewPin,
    parse_pin,
)
from limn.pins.position import _reverse_rel, range_rel
from limn.pins.shapes import is_finite_num, is_int, is_num

# -----------------------------------------------------------------------------
# Strategies
# -----------------------------------------------------------------------------

person_strategy = st.builds(
    Person,
    login=st.text(min_size=1, max_size=30).filter(lambda s: "\x00" not in s),
    name=st.text(min_size=1, max_size=30).filter(lambda s: "\x00" not in s),
    pic=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
)

agent_strategy = st.builds(
    Agent,
    login=st.text(min_size=1, max_size=30).filter(lambda s: "\x00" not in s),
    name=st.text(min_size=1, max_size=30).filter(lambda s: "\x00" not in s),
)

actor_strategy = st.one_of(person_strategy, agent_strategy)


def base_open_record_strategy() -> st.SearchStrategy[dict[str, object]]:
    """Generate arbitrary valid open pin records."""
    return st.fixed_dictionaries(
        {
            "id": st.integers(min_value=1, max_value=100_000),
            "file": st.text(min_size=1, max_size=50).map(lambda s: f"/ms/{s.replace('/', '_')}.tex"),
            "lo": st.integers(min_value=1, max_value=5000),
            "hi": st.integers(min_value=1, max_value=5000),
            "note": st.text(max_size=100),
            "done": st.just(False),
        }
    ).map(lambda d: {**d, "hi": max(d["lo"], d["hi"])})  # ensure lo <= hi


@st.composite
def open_pin_strategy(draw: st.DrawFn) -> OpenPin:
    """Generate parsed OpenPin domain models."""
    record = draw(base_open_record_strategy())
    rev = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=100)))
    kind_req = draw(st.one_of(st.none(), st.sampled_from(["task", "question", "typo"])))
    if rev is not None:
        record["rev"] = rev
    if kind_req is not None:
        record["kind_req"] = kind_req
    pin = parse_pin(record)
    assert isinstance(pin, OpenPin)
    return pin


@st.composite
def review_pin_strategy(draw: st.DrawFn) -> ReviewPin:
    """Generate parsed ReviewPin domain models."""
    record = draw(base_open_record_strategy())
    record["done"] = True
    record["review"] = True
    record["done_at"] = "2026-09-28 10:00:00"
    record["closed_by"] = {"login": "local", "name": "agent"}
    rev = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=100)))
    kind_req = draw(st.one_of(st.none(), st.sampled_from(["task", "question", "typo"])))
    if rev is not None:
        record["rev"] = rev
    if kind_req is not None:
        record["kind_req"] = kind_req
    pin = parse_pin(record)
    assert isinstance(pin, ReviewPin)
    return pin


@st.composite
def done_pin_strategy(draw: st.DrawFn) -> DonePin:
    """Generate parsed DonePin domain models."""
    record = draw(base_open_record_strategy())
    record["done"] = True
    record["done_at"] = "2026-09-28 10:00:00"
    record["closed_by"] = {"login": "alice@example.com", "name": "Alice"}
    rev = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=100)))
    kind_req = draw(st.one_of(st.none(), st.sampled_from(["task", "question", "typo"])))
    if rev is not None:
        record["rev"] = rev
    if kind_req is not None:
        record["kind_req"] = kind_req
    pin = parse_pin(record)
    assert isinstance(pin, DonePin)
    return pin


# -----------------------------------------------------------------------------
# 1. Shapes and Type-Guard Invariants
# -----------------------------------------------------------------------------


class TestShapeInvariants:
    """Test JSON shape validation invariants across primitive and numeric types."""

    @given(st.booleans())
    def test_booleans_are_never_int_nor_num(self, b: bool) -> None:
        """In Python, bool is an int subclass. Limn shapes must strictly reject bools."""
        assert is_int(b) is False
        assert is_num(b) is False
        assert is_finite_num(b) is False

    @given(st.integers())
    def test_integers_are_always_int_and_num(self, i: int) -> None:
        """True integers are recognized by is_int, is_num, and is_finite_num (within float range)."""
        assert is_int(i) is True
        assert is_num(i) is True
        try:
            float(i)
            assert is_finite_num(i) is True
        except OverflowError:
            assert is_finite_num(i) is False

    @given(st.floats())
    def test_floats_properties(self, f: float) -> None:
        """Floats are recognized by is_num, never is_int, and is_finite_num tracks isfinite."""
        assert is_int(f) is False
        assert is_num(f) is True
        assert is_finite_num(f) is math.isfinite(f)


# -----------------------------------------------------------------------------
# 2. Text and Truncation Invariants
# -----------------------------------------------------------------------------


class TestTextInvariants:
    """Test string normalization and quote truncation properties."""

    @given(st.text(), st.integers(min_value=1, max_value=500))
    def test_truncate_quote_length_bound(self, s: str, n: int) -> None:
        """Truncated quotes never exceed the requested limit n."""
        result = truncate_quote(s, n)
        assert len(result) <= n
        if len(s) <= n:
            assert result == s
        else:
            assert result.endswith("…")
            assert len(result) == n

    @given(st.text(), st.integers(min_value=1, max_value=500))
    def test_flat_invariants(self, s: str, n: int) -> None:
        """flat collapses newlines/whitespace and respects character length limit."""
        result = flat(s, n)
        assert len(result) <= n
        assert "\n" not in result
        assert "\r" not in result
        assert "  " not in result

    @given(st.text())
    def test_norm_idempotence(self, s: str) -> None:
        """Line normalization is idempotent: norm(norm(s)) == norm(s)."""
        once = norm(s)
        twice = norm(once)
        assert once == twice


# -----------------------------------------------------------------------------
# 3. Densest Cluster Selection (SyncTeX Invariant)
# -----------------------------------------------------------------------------


class TestDensestClusterInvariants:
    """Test SyncTeX hit clustering invariants."""

    @given(st.lists(st.integers(min_value=1, max_value=10_000)), st.integers(min_value=1, max_value=100))
    def test_densest_cluster_properties(self, raw_values: list[int], gap: int) -> None:
        """densest returns a contiguous sub-cluster where every adjacent element diff <= gap."""
        if not raw_values:
            assert densest([], gap) == []
            return

        values = sorted(raw_values)
        cluster = densest(values, gap)
        assert len(cluster) >= 1
        assert set(cluster).issubset(set(values))

        # Invariant: Every step in the selected cluster has difference <= gap
        for i in range(len(cluster) - 1):
            assert cluster[i + 1] - cluster[i] <= gap


# -----------------------------------------------------------------------------
# 4. Range Overlap Invariants (Geometry & Symmetry)
# -----------------------------------------------------------------------------


class TestRangeOverlapInvariants:
    """Test line range relationship algebra."""

    @given(
        st.integers(min_value=1, max_value=1000),
        st.integers(min_value=1, max_value=1000),
        st.integers(min_value=1, max_value=1000),
        st.integers(min_value=1, max_value=1000),
    )
    def test_range_rel_algebraic_symmetry(self, a1: int, a2: int, b1: int, b2: int) -> None:
        """range_rel exhibits duality: reversing roles reverses 'inside' and 'contains'."""
        a_lo, a_hi = min(a1, a2), max(a1, a2)
        b_lo, b_hi = min(b1, b2), max(b1, b2)

        rel_ab = range_rel(a_lo, a_hi, b_lo, b_hi)
        rel_ba = range_rel(b_lo, b_hi, a_lo, a_hi)

        if a_hi < b_lo or b_hi < a_lo:
            assert rel_ab is None
            assert rel_ba is None
        elif (a_lo, a_hi) == (b_lo, b_hi):
            assert rel_ab == "contains"
            assert rel_ba == "contains"
        else:
            assert rel_ab is not None
            assert rel_ba is not None
            assert rel_ba == _reverse_rel(rel_ab)

    @given(
        st.integers(min_value=1, max_value=500),
        st.integers(min_value=1, max_value=500),
        st.integers(min_value=1, max_value=500),
        st.integers(min_value=1, max_value=500),
        st.integers(min_value=1, max_value=500),
        st.integers(min_value=1, max_value=500),
    )
    def test_range_rel_transitivity_of_inside(self, a1: int, a2: int, b1: int, b2: int, c1: int, c2: int) -> None:
        """If range A is strictly inside range B, and B is inside C, then A is inside C."""
        a_lo, a_hi = min(a1, a2), max(a1, a2)
        b_lo, b_hi = min(b1, b2), max(b1, b2)
        c_lo, c_hi = min(c1, c2), max(c1, c2)

        rel_ab = range_rel(a_lo, a_hi, b_lo, b_hi)
        rel_bc = range_rel(b_lo, b_hi, c_lo, c_hi)

        if rel_ab == "inside" and rel_bc == "inside":
            assert range_rel(a_lo, a_hi, c_lo, c_hi) == "inside"


# -----------------------------------------------------------------------------
# 5. Pin Lifecycle State Machine Invariants
# -----------------------------------------------------------------------------


class TestPinLifecycleInvariants:
    """Test pure domain state transitions and invariants in pins/lifecycle."""

    @given(
        open_pin_strategy(),
        st.booleans(),
        st.lists(st.text(min_size=1, max_size=20), max_size=5),
        st.one_of(st.none(), st.booleans()),
    )
    def test_open_pin_never_reopens_on_reply(
        self, pin: OpenPin, human: bool, mentioned: Sequence[str], reopen: bool | None
    ) -> None:
        """Core Invariant: An OpenPin NEVER changes to reopen on a reply, under any parameters."""
        assert reopens_on_reply(pin, human=human, mentioned=mentioned, reopen=reopen) is False

    @given(
        st.one_of(review_pin_strategy(), done_pin_strategy()),
        st.booleans(),
        st.lists(st.text(min_size=1, max_size=20), max_size=5),
        st.booleans(),
    )
    def test_explicit_reopen_flag_always_controls_closed_pin(
        self, pin: Pin, human: bool, mentioned: Sequence[str], explicit_reopen: bool
    ) -> None:
        """When an explicit reopen flag is present, it directly dictates whether a closed pin reopens."""
        assert reopens_on_reply(pin, human=human, mentioned=mentioned, reopen=explicit_reopen) is explicit_reopen

    @given(
        st.one_of(review_pin_strategy(), done_pin_strategy()),
        st.booleans(),
        st.lists(st.text(min_size=1, max_size=20), max_size=5),
    )
    def test_closed_question_never_reopens_without_explicit_flag(
        self, pin: Pin, human: bool, mentioned: Sequence[str]
    ) -> None:
        """A question pin never auto-reopens on reply (the reply is deemed an answer)."""
        object.__setattr__(pin.core, "kind_req", "question")
        assert reopens_on_reply(pin, human=human, mentioned=mentioned, reopen=None) is False

    @given(
        open_pin_strategy(),
        person_strategy,
        st.text(min_size=1, max_size=25),
    )
    def test_confirm_on_open_pin_is_still_open(self, pin: OpenPin, by: Person, at: str) -> None:
        """Confirming an open pin is refused: returns PinStillOpen carrying the identical pin."""
        result = confirm(pin, by=by, at=at)
        assert isinstance(result, PinStillOpen)
        assert result.pin is pin

    @given(
        done_pin_strategy(),
        person_strategy,
        st.text(min_size=1, max_size=25),
    )
    def test_confirm_on_done_pin_is_already_done(self, pin: DonePin, by: Person, at: str) -> None:
        """Confirming an already-done pin is a no-op: returns AlreadyDone carrying the identical pin."""
        result = confirm(pin, by=by, at=at)
        assert isinstance(result, AlreadyDone)
        assert result.pin is pin

    @given(
        review_pin_strategy(),
        person_strategy,
        st.text(min_size=1, max_size=25),
    )
    def test_confirm_on_review_pin_transitions_to_done(self, pin: ReviewPin, by: Person, at: str) -> None:
        """Confirming a review pin transitions to DonePin, adds signatures and bumps rev."""
        initial_rev = pin.core.rev
        result = confirm(pin, by=by, at=at)
        assert isinstance(result, DonePin)
        assert "review" not in result.record
        assert result.record["confirmed_at"] == at
        assert result.record["confirmed_by"]["login"] == by.login
        assert result.core.rev == rev_after(initial_rev)

    @given(
        open_pin_strategy(),
        actor_strategy,
        st.text(min_size=1, max_size=25),
        st.booleans(),
    )
    def test_evolve_close_strips_claim_fields_and_sets_done(
        self, pin: OpenPin, by: Actor, at: str, review: bool
    ) -> None:
        """Closing an open pin cleans all claim fields and sets done=True."""
        # Attach dummy claim fields to simulate open claimed pin
        enriched_record = dict(pin.record)
        for cf in CLAIM_FIELDS:
            enriched_record[cf] = "dummy"
        enriched_pin = parse_pin(enriched_record)
        assert isinstance(enriched_pin, OpenPin)

        event = PinClosed(by=by, at=at, reply="done", ref=None, changes=(), review=review)
        closed_pin = evolve_close(enriched_pin, event)

        assert closed_pin.record["done"] is True
        for cf in CLAIM_FIELDS:
            assert cf not in closed_pin.record
        if review:
            assert isinstance(closed_pin, ReviewPin)
        else:
            assert isinstance(closed_pin, DonePin)

    @given(st.one_of(st.none(), st.integers(min_value=0, max_value=100_000)))
    def test_rev_after_monotonicity(self, rev: int | None) -> None:
        """rev_after always produces an integer >= 1, strictly greater than existing rev >= 0."""
        nxt = rev_after(rev)
        assert isinstance(nxt, int)
        assert nxt >= 1
        if rev is not None:
            assert nxt > rev


# -----------------------------------------------------------------------------
# 6. Parse-Pin Lossless Roundtrip Invariant
# -----------------------------------------------------------------------------


class TestParsePinLosslessRoundtrip:
    """Verify that parsing valid arbitrary pin shapes is strictly lossless."""

    @given(base_open_record_strategy())
    def test_open_pin_lossless_roundtrip(self, record: dict[str, object]) -> None:
        """Parsing an open record into an OpenPin and serializing back produces identical JSON bytes."""
        pin = parse_pin(record)
        assert isinstance(pin, OpenPin)
        assert pin.record == record
        assert json.dumps(pin.record, ensure_ascii=False) == json.dumps(record, ensure_ascii=False)
