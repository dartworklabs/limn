"""Bind events.jsonl and mention rules to one server run."""

import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from limn.collaboration import events
from limn.runtime.documents import Doc
from limn.security import access
from limn.security.access import is_agent_actor

Json = dict[str, Any]


@dataclass(frozen=True)
class Notices:
    """The run's event file, recipient facts and clock."""

    path: Callable[[], Path]
    lock: Callable[[], threading.Lock]
    cache: Callable[[], events.ReadCache]
    clock: Callable[[], float]
    stamp: Callable[[], str]
    pin_doc_key: Callable[[Mapping[str, Any]], str]
    docs: Callable[[], Sequence[Doc]]

    def log(self) -> events.EventLog:
        """Create a log view with this run's shared lock and read cache."""
        return events.EventLog(self.path(), self.lock(), self.cache(), self.clock, self.stamp)

    def read(self) -> tuple[list[events.Row], events.Signature | None]:
        """Read the current event file through the run's cache."""
        return self.log().read()

    def make_event(
        self,
        typ: events.EventType,
        r: Mapping[str, Any],
        actor: Mapping[str, Any],
        to: Iterable[str | None] | None,
        msg: Mapping[str, Any] | None = None,
        text: str | None = None,
    ) -> Json | None:
        """Build one notice, excluding the actor and headerless local agent from recipients."""
        return events.make_event(
            typ, r, actor, to, _actor_record, self.pin_doc_key, access.LOCAL_ACTOR["login"], msg, text
        )

    def emit_events(self, notices: list[Json | None]) -> None:
        """Append committed pin notices and retain the configured recent window."""
        self.log().emit(notices, events.EVENTS_KEEP)

    def since(self, actor: Json, cursor: int | None) -> Json:
        """Select the browser notifications visible to this actor after cursor."""
        rows, _ = self.read()
        me = (actor or {}).get("login")
        return events.events_since(
            rows, None if not me or is_agent_actor(actor) else me, cursor, {doc.key: doc.name for doc in self.docs()}
        )


def _actor_record(actor: Mapping[str, Any]) -> Json:
    """Return the stable actor fields stored in an event."""
    return {"login": actor.get("login", "local"), "name": actor.get("name", "")}
