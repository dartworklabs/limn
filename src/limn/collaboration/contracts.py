"""Completed effect inputs accepted by collaboration, independent of pin storage."""

from typing import Literal, Protocol, TypeAlias

EventType: TypeAlias = Literal["mention", "review_requested", "replied", "reopened", "assigned", "dropped"]


class Notice(Protocol):
    """One completed notice before recipient filtering, excerpt formatting and durable emission.

    Collaboration declares here exactly the fields it reads and constructs no notice itself: the emitting feature
    owns the concrete value, and the composition root hands it over unchanged. Any value with these read-only
    members is accepted, so a notice type the emitter adds without adding it to EventType fails type checking at
    the wiring rather than reaching events.jsonl.
    """

    @property
    def type(self) -> EventType:
        """Which notice this is; written as the record's `type`."""
        ...

    @property
    def pin(self) -> int | None:
        """The pin's id, None when the emitter's record has none."""
        ...

    @property
    def document(self) -> str:
        """The key of the document the pin belongs to."""
        ...

    @property
    def actor_login(self) -> str:
        """The login of whoever caused the notice; never one of its recipients."""
        ...

    @property
    def actor_name(self) -> str:
        """The actor's display name, empty when unknown."""
        ...

    @property
    def recipients(self) -> tuple[str | None, ...]:
        """Candidate logins in order, unfiltered: repeats, missing logins and the actor may be present."""
        ...

    @property
    def kind(self) -> str | None:
        """The pin's request kind; recorded only when truthy."""
        ...

    @property
    def has_message(self) -> bool:
        """Whether the notice is about one thread message; only then is message_id recorded."""
        ...

    @property
    def message_id(self) -> int | None:
        """That message's id (0 is a valid id); meaningful only when has_message is true."""
        ...

    @property
    def text(self) -> str:
        """The unshortened source of the one-line excerpt; an empty excerpt is not recorded."""
        ...
