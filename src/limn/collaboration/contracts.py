"""Completed effect inputs accepted by collaboration, independent of pin storage."""

from dataclasses import dataclass
from typing import Literal, TypeAlias

EventType: TypeAlias = Literal["mention", "review_requested", "replied", "reopened", "assigned", "dropped"]


@dataclass(frozen=True)
class Notice:
    """One completed notice before recipient filtering, excerpt formatting and durable emission."""

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
