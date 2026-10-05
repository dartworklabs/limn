"""A concrete completed notice for the collaboration tests that drive events.make_event with no server.

Collaboration only declares the shape it accepts (limn.collaboration.contracts.Notice, a Protocol) and builds no
notice itself; these tests stand in for the emitting feature without importing it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NoticeFacts:
    """Every field make_event reads, in the positional order the emitting feature fills them."""

    type: str
    pin: int | None
    document: str
    actor_login: str
    actor_name: str
    recipients: tuple[str | None, ...]
    kind: str | None = None
    has_message: bool = False
    message_id: int | None = None
    text: str = ""
