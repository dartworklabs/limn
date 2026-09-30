"""Generated multi-operation histories preserve pin identity, state and legacy fields."""

import copy
import json

from hypothesis import given, strategies as st

from limn.pins.claims.rules import ClaimRequest, claim, unclaim
from limn.pins.lifecycle.rules import (
    AlreadyClosed,
    AlreadyDone,
    CloseRequest,
    PinStillOpen,
    Replied,
    ThreadFull,
    confirm,
    decide_close,
    decide_reopen,
    decide_reply,
    evolve_close,
    evolve_reply,
    reopen_request,
)
from limn.pins.model import Agent, DonePin, OpenPin, Person, ReviewPin, parse_pin
from limn.pins.thread import CLAIM_FIELDS

OPERATIONS = st.lists(
    st.tuples(
        st.sampled_from(("close", "reopen", "confirm", "reply", "claim", "unclaim")),
        st.booleans(),
        st.one_of(st.none(), st.booleans()),
    ),
    min_size=1,
    max_size=60,
)


@given(OPERATIONS, st.integers(min_value=1, max_value=999999), st.text(max_size=80))
def test_operation_sequences_preserve_identity_and_serializable_state(operations, pid, note):
    """Interleaved accepted and refused operations retain identity/data, never mutate prior snapshots,
    and serialize into the state predicted by the public lifecycle rules after every step.
    """
    original = {"id": pid, "file": "/ms/main.tex", "lo": 2, "hi": 4, "note": note, "legacy_extra": {"v": [1]}}
    pin = parse_pin(original)
    state = "open"
    person = Person("alice@example.com", "Alice")
    agent = Agent("agent:worker", "Worker")
    for step, (operation, as_agent, review) in enumerate(operations):
        before = copy.deepcopy(pin.record)
        previous = pin
        by = agent if as_agent else person
        at = "2026-09-29 12:00:00"
        if operation == "close":
            event = decide_close(pin, by, at, CloseRequest(reply="done", review=review))
            if state == "open":
                assert isinstance(pin, OpenPin)
                pin = evolve_close(pin, event)
                state = "review" if (as_agent if review is None else review) else "done"
            else:
                assert isinstance(event, AlreadyClosed)
        elif operation == "reopen":
            pin = reopen_request(pin, decide_reopen(pin, by, at, "again", ()))
            state = "open"
        elif operation == "confirm":
            outcome = confirm(pin, person, at)
            if state == "review":
                assert isinstance(outcome, DonePin)
                pin = outcome
                state = "done"
            else:
                assert isinstance(outcome, PinStillOpen if state == "open" else AlreadyDone)
        elif operation == "reply":
            event = decide_reply(pin, by, at, "response", (), False, 5)
            if isinstance(event, Replied):
                pin = evolve_reply(pin, event)
            else:
                assert isinstance(event, ThreadFull)
        elif operation == "claim":
            outcome = claim(pin, by, float(step), at, ClaimRequest(5), None)
            if isinstance(outcome, OpenPin):
                pin = outcome
        else:
            outcome = unclaim(pin)
            if isinstance(outcome, OpenPin):
                pin = outcome

        assert previous.record == before
        assert type(pin) is {"open": OpenPin, "review": ReviewPin, "done": DonePin}[state]
        for key, value in original.items():
            assert pin.record[key] == value
        old_rev = before.get("rev", 0)
        new_rev = pin.record.get("rev", 0)
        assert new_rev >= old_rev
        if pin.record != before:
            assert new_rev == old_rev + 1
        if state != "open":
            assert not set(CLAIM_FIELDS).intersection(pin.record)
        encoded = json.dumps(pin.record, ensure_ascii=False)
        restored = parse_pin(json.loads(encoded))
        assert type(restored) is type(pin)
        assert json.dumps(restored.record, ensure_ascii=False) == encoded
