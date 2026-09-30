"""Representative pin records and actors shared by pure mutation tests."""

from limn.pins.model import Agent, Person

ALICE_PERSON = Person("alice@example.com", "Alice Kim", "https://example.com/a.png")


AT = "2026-09-26 10:00:00"


def review_record(**extra):
    """A pin an agent closed: done and review are true, with one earlier thread entry."""
    record = {
        "id": 7,
        "file": "main.tex",
        "lo": 3,
        "hi": 4,
        "note": "fix",
        "done": True,
        "review": True,
        "thread": [{"id": 1, "by": {"login": "local", "name": "agent"}, "at": "t0", "text": "done", "ev": "close"}],
        "rev": 2,
    }
    record.update(extra)
    return record


AGENT = Agent("local", "agent")


def open_record(**extra):
    """An open pin with a claim in progress and one earlier reply."""
    record = {
        "id": 9,
        "file": "main.tex",
        "lo": 1,
        "hi": 2,
        "note": "n",
        "done": False,
        "claimed_by": {"login": "local"},
        "claim_until": 1.0,
        "thread": [{"id": 4, "by": {"login": "x", "name": "X"}, "at": "t0", "text": "hi"}],
        "rev": 5,
    }
    record.update(extra)
    return record


NOW = 1_790_000_000.0
