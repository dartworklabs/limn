"""Pin-owned actor extraction does not export workflow or location schemas."""

from hypothesis import given, strategies as st

from limn.pins.application import people_facts


@given(note=st.text(), path=st.text())
def test_participants_are_flat_identity_facts(note, path):
    """Location, note and thread metadata must never accompany participant identities."""
    record = {
        "author": {"login": "alice@example.com", "name": "Alice", "extra": path},
        "file": path,
        "note": note,
        "done_by": {"login": "bob@example.com"},
        "thread": [{"id": 0, "text": note, "by": {"login": "alice@example.com", "pic": "portrait"}}],
    }
    assert people_facts(record) == (
        {"login": "alice@example.com", "name": "Alice"},
        {"login": "bob@example.com"},
        {"login": "alice@example.com", "pic": "portrait"},
    )
