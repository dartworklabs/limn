"""The notice value pins emit when a pin changes in a way somebody should be told about.

Pins own this value and import no other feature for it. The receiver, wired in by the composition root, declares in
its own slice the fields it reads; the value passes through the root unchanged and the type checker compares the two
declarations there.
"""

from dataclasses import dataclass

from limn.pins.model import EventType


@dataclass(frozen=True)
class PinNotice:
    """One completed notice about a pin, as handed to the injected notice sink.

    Pins extract every fact from the pin record and its thread, so the sink interprets neither. recipients is
    unfiltered: it may hold the actor, repeats and missing logins, and the sink decides who is told. message_id means
    something only when has_message is true (0 is a valid id). text is the unshortened source of the excerpt.
    """

    type: EventType
    pin: int | None
    document: str
    actor_login: str
    actor_name: str
    recipients: tuple[str | None, ...]
    kind: str | None = None
    has_message: bool = False
    message_id: int | None = None
    text: str = ""
