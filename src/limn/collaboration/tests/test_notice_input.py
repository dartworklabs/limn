"""Completed notice inputs preserve recipient and optional-field wire contracts."""

from limn.collaboration import events

from helpers_events import NoticeFacts


def test_completed_notice_keeps_message_zero_and_filters_recipients():
    """Message id zero is present; recipients keep order, without actor or local duplicates."""
    assert hasattr(events, "Notice"), "collaboration still consumes pin and thread records"
    notice = NoticeFacts(
        "replied",
        7,
        "fig",
        "alice@example.com",
        "Alice",
        ("bob@example.com", "alice@example.com", "local", "bob@example.com"),
        "question",
        True,
        0,
        "two\n  lines",
    )
    assert events.make_event(notice, "local") == {
        "type": "replied",
        "pin": 7,
        "doc": "fig",
        "to": ["bob@example.com"],
        "by": {"login": "alice@example.com", "name": "Alice"},
        "kind_req": "question",
        "msg": 0,
        "excerpt": "two lines",
    }
