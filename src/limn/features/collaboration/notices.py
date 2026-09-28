"""Bind events.jsonl and mention rules to one server run."""

import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from limn import access, events
from limn.documents import Doc
from limn.mentions import NoteTags, note_mention_targets, tag_note
from limn.pins.model import Pin, Record
from limn.service.context import is_agent, who

Json = dict[str, Any]


@dataclass(frozen=True)
class Notices:
    """The run's event file, recipient facts and clock."""

    path: Callable[[], Path]
    lock: Callable[[], threading.Lock]
    cache: Callable[[], events.ReadCache]
    clock: Callable[[], float]
    stamp: Callable[[], str]
    pin_doc_key: Callable[[Record], str]
    docs: Callable[[], Sequence[Doc]]
    known_people: Callable[[Sequence[Pin] | None], dict[str, Json]]

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
        return events.make_event(typ, r, actor, to, who, self.pin_doc_key, access.LOCAL_ACTOR["login"], msg, text)

    def emit_events(self, notices: list[Json | None]) -> None:
        """Append committed pin notices and retain the configured recent window."""
        self.log().emit(notices, events.EVENTS_KEEP)

    def note_tags(
        self,
        note: str,
        old_note: str,
        pins: Sequence[Pin],
        hints: Sequence[str] | None,
        actor: Mapping[str, Any],
        pid: object,
    ) -> NoteTags:
        """Resolve newly tagged people and suppress repeated note notices within the cooldown."""
        me = (actor or {}).get("login")
        tags = tag_note(note, old_note, self.known_people(pins), hints, me)
        if not tags.notify:
            return tags
        return tags._replace(notify=note_mention_targets(tags.notify, self.read()[0], me, pid, self.clock()))

    def since(self, actor: Json, cursor: int | None) -> Json:
        """Select the browser notifications visible to this actor after cursor."""
        rows, _ = self.read()
        me = (actor or {}).get("login")
        return events.events_since(
            rows, None if not me or is_agent(actor) else me, cursor, {doc.key: doc.name for doc in self.docs()}
        )
