"""Pure lifecycle commands, decisions and stored-record transitions.

All external facts arrive as values; records preserve their field insertion order.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from posixpath import isabs
from types import MappingProxyType

from limn.pins.lifecycle import (
    CLAIM_FIELDS,
    PinT,
    author,
    rev_after,
    signature,
    thread_message,
    with_entry,
)
from limn.pins.model import (
    Actor,
    Agent,
    DonePin,
    OpenPin,
    Person,
    Pin,
    Record,
    ReviewPin,
    ThreadEntry,
)
from limn.pins.shapes import is_int

# What a reopen forgets: the last close and any review or confirmation of it.
CLOSE_FIELDS = ("close_reply", "close_ref", "changes", "changes_at", "review", "confirmed_by", "confirmed_at")


@dataclass(frozen=True)
class AgentCannotConfirm:
    """Only a person may confirm: review exists to record that a person looked at an agent's closed pin."""


@dataclass(frozen=True)
class PinStillOpen:
    """An open pin has nothing to confirm; the pin travels along for the 409 body."""

    pin: OpenPin


@dataclass(frozen=True)
class AlreadyDone:
    """The pin is already done; confirming it again changes nothing and is not an error."""

    pin: DonePin


def confirmer(actor: Actor) -> Person | AgentCannotConfirm:
    """The person who may confirm, or the refusal for an agent - decided before any pin is loaded."""
    match actor:
        case Person():
            return actor
        case Agent():
            return AgentCannotConfirm()


def confirm(pin: Pin, by: Person, at: str) -> DonePin | AlreadyDone | PinStillOpen:
    """Confirm a pin awaiting review; a done pin comes back as AlreadyDone and an open one as PinStillOpen."""
    match pin:
        case ReviewPin():
            return confirm_review(pin, by, at)
        case DonePin():
            return AlreadyDone(pin)
        case OpenPin():
            return PinStillOpen(pin)


def confirm_review(pin: ReviewPin, by: Person, at: str) -> DonePin:
    """Close the review: drop the review flag, record who confirmed and when, add an ev=confirm thread entry, bump rev.

    Fields keep their order in the record (new ones go to the end), so the stored line changes only where the
    old in-place update changed it.
    """
    record = {key: value for key, value in pin.record.items() if key != "review"}
    record["confirmed_by"] = signature(by)
    record["confirmed_at"] = at
    record["thread"] = with_entry(pin.core.thread, thread_message(pin.core.thread, author(by), at, ev="confirm"))
    record["rev"] = rev_after(pin.core.rev)
    return DonePin.from_record(record)


@dataclass(frozen=True)
class CloseRequest:
    """A close's reply, ref, changed ranges and review choice, with local shapes guarded on construction.

    The boundary checks text limits and paths against the manuscript; changes are copied into immutable mappings so a
    caller cannot change a range after validation. review None leaves the choice to the closer: an agent's close
    awaits review, a person's is done at once.
    """

    reply: str | None = None
    ref: str | None = None
    changes: tuple[Record, ...] = ()
    review: bool | None = None

    def __post_init__(self) -> None:
        """Reject malformed local fields before a direct caller can save a broken close record."""
        if self.reply is not None and not isinstance(self.reply, str):
            raise ValueError("reply must be a string")
        if self.ref is not None and not isinstance(self.ref, str):
            raise ValueError("ref must be a string")
        if self.review is not None and not isinstance(self.review, bool):
            raise ValueError("review must be a boolean")
        if not isinstance(self.changes, tuple):
            raise ValueError("changes must be a tuple of ranges")
        for change in self.changes:
            if (
                not isinstance(change, Mapping)
                or set(change) != {"file", "lo", "hi"}
                or not isinstance(change["file"], str)
                or not isabs(change["file"])
                or not is_int(change["lo"])
                or not is_int(change["hi"])
                or not 1 <= change["lo"] <= change["hi"]
            ):
                raise ValueError("changes must contain absolute files and ordered positive lines")
        object.__setattr__(self, "changes", tuple(MappingProxyType(dict(change)) for change in self.changes))


@dataclass(frozen=True)
class PinClosed:
    """The fact that an open pin was closed: by whom, when, with which reply, ref and changes, and whether it awaits review."""

    by: Actor
    at: str
    reply: str | None
    ref: str | None
    changes: tuple[Record, ...]
    review: bool


@dataclass(frozen=True)
class AlreadyClosed:
    """The pin was closed before; closing again changes nothing, so the first closer and reply stay on record."""

    pin: ReviewPin | DonePin


def decide_close(pin: Pin, by: Actor, at: str, request: CloseRequest) -> PinClosed | AlreadyClosed:
    """What closing does: an open pin is closed (into review when an agent closes it, unless the request says),
    a closed one is left alone."""
    match pin:
        case OpenPin():
            review = request.review if request.review is not None else isinstance(by, Agent)
            return PinClosed(by, at, request.reply, request.ref, request.changes, review)
        case ReviewPin() | DonePin():
            return AlreadyClosed(pin)


def evolve_close(pin: OpenPin, event: PinClosed) -> ReviewPin | DonePin:
    """Apply a close only to an open pin; a second application is a caller defect.

    Records done_at, closed_by, reply/ref/changes when given, review when chosen, an ev=close thread entry, clears
    the claim, and bumps rev. changes_at equals done_at, tying the changes to this close.
    """
    if not isinstance(pin, OpenPin):
        raise ValueError("a close event can only be applied to an open pin")
    record = dict(pin.record)
    record["done"] = True
    record["done_at"] = event.at
    record["closed_by"] = signature(event.by)
    if event.reply:
        record["close_reply"] = event.reply
    if event.ref:
        record["close_ref"] = event.ref
    if event.changes:
        record["changes"] = [dict(change) for change in event.changes]
        record["changes_at"] = event.at
    if event.review:
        record["review"] = True
    record["thread"] = with_entry(
        pin.core.thread,
        thread_message(pin.core.thread, author(event.by), event.at, event.reply or "", ev="close", ref=event.ref),
    )
    for key in CLAIM_FIELDS:
        record.pop(key, None)
    record["rev"] = rev_after(pin.core.rev)
    if record.get("review") is True:  # parse_pin()'s rule, done now true
        return ReviewPin.from_record(record)
    return DonePin.from_record(record)


@dataclass(frozen=True)
class PinReopened:
    """The fact that a pin was reopened: by whom, when, why, whom the reason tags, and whether it had been closed."""

    by: Actor
    at: str
    reason: str | None
    mentions: tuple[str, ...]
    was_closed: bool


def decide_reopen(pin: Pin, by: Actor, at: str, reason: str | None, mentions: tuple[str, ...]) -> PinReopened:
    """What reopening does. Reopening is always allowed; only a pin that was closed gets a thread entry and notices."""
    return PinReopened(by, at, reason, mentions, was_closed=not isinstance(pin, OpenPin))


def evolve_reopen(pin: Pin, event: PinReopened) -> OpenPin:
    """Apply a reopen: done false, who and when, the last close and its review/confirmation forgotten, and - if the pin
    had been closed - an ev=reopen thread entry carrying the reason and its mentions. rev is the caller's: a reopen
    request bumps it here via reopen_request(), a reopening reply bumps it once for the reply."""
    record = dict(pin.record)
    record["done"] = False
    record["reopened_at"] = event.at
    record["reopened_by"] = signature(event.by)
    for key in CLOSE_FIELDS:
        record.pop(key, None)
    if event.was_closed:
        record["thread"] = with_entry(
            pin.core.thread,
            thread_message(
                pin.core.thread, author(event.by), event.at, event.reason or "", ev="reopen", mentions=event.mentions
            ),
        )
    return OpenPin.from_record(record)


def reopen_request(pin: Pin, event: PinReopened) -> OpenPin:
    """POST /reopen: apply the reopen and bump rev - also for a pin that was already open, which a reopen request
    rewrites all the same."""
    opened = evolve_reopen(pin, event)
    return OpenPin.from_record({**opened.record, "rev": rev_after(pin.core.rev)})


@dataclass(frozen=True)
class Replied:
    """The fact of a plain reply: by whom, when, the text, and whom it @-tags."""

    by: Actor
    at: str
    text: str
    mentions: tuple[str, ...]


@dataclass(frozen=True)
class ThreadFull:
    """The thread already holds as many replies as a pin may have; the conversation continues on a new pin."""

    limit: int


def reopens_on_reply(pin: Pin, human: bool, mentioned: Sequence[str], reopen: bool | None) -> bool:
    """Does a reply reopen this pin? The one rule behind the viewer's single [Reply] (docs/handbook/api.md §스레드 (답글)).

    An open pin never changes. Otherwise an explicit `reopen` (true/false, from the request) decides; without one, a
    human's reply on a pin awaiting review or done reopens it - the reply becomes the rework instruction - unless it
    tags a person (then it is a conversation with that person) or the pin is a question (then the reply is an answer).
    An agent's reply never reopens by the rule. `mentioned` is the post's resolved @-tags of people, without the poster.
    The viewer's preview (replyReopens) mirrors this function.
    """
    match pin:
        case OpenPin():
            return False
        case ReviewPin() | DonePin():
            if reopen is not None:
                return bool(reopen)
            if pin.core.kind_req == "question" or not human:
                return False
            return not mentioned


def decide_reply(
    pin: Pin, by: Actor, at: str, text: str, mentions: tuple[str, ...], reopens: bool, limit: int
) -> PinReopened | Replied | ThreadFull:
    """What a reply does: reopen the pin with the reply as the reason, refuse when the thread is full, or add a reply.

    A reopening reply is not counted against the limit - it is recorded as a state-transition entry, like a close.
    """
    if reopens:
        return decide_reopen(pin, by, at, text, mentions)
    if len(replies(pin.core.thread)) >= limit:
        return ThreadFull(limit)
    return Replied(by, at, text, mentions)


def evolve_reply(pin: PinT, event: Replied) -> PinT:
    """Apply a plain reply: one thread entry with its mentions, and rev bumped. The pin keeps its state."""
    record = dict(pin.record)
    record["thread"] = with_entry(
        pin.core.thread,
        thread_message(pin.core.thread, author(event.by), event.at, event.text, mentions=event.mentions),
    )
    record["rev"] = rev_after(pin.core.rev)
    return type(pin).from_record(record)


def replies(thread: Sequence[ThreadEntry] | None) -> list[ThreadEntry]:
    """The thread's replies, without state-transition entries (ev close/reopen/confirm/assign); none for no thread."""
    return [entry for entry in thread or () if entry.ev is None]


def last_entry(pin: Pin) -> ThreadEntry:
    """The newest entry of pin's thread: the one the reply, close or reopen that just made pin wrote. Asking it of a
    pin without a thread entry is a defect (ValueError)."""
    if not pin.core.thread:
        raise ValueError("pin %r has no thread entry" % pin.core.id)
    return pin.core.thread[-1]
