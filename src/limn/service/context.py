"""What a pin service needs from the instance (PinContext), and the typed actor of a request.

The composition root (server.pin_context()) makes a PinContext per call. Every collaborator is a value or a callable
looked up at that moment - the pin store with the process's lock, the clock, the notice and audit sinks, the @-tag
lookups, where a pin's file is under the manuscript root, and the settings values - so the services never read the
run settings and a frozen clock or a patched setting in a test reaches them.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias

from limn.access import AGENT_LOGIN_PREFIX, LOCAL_ACTOR
from limn.locate import PinLocation
from limn.mentions import NoteTags
from limn.pins.model import Actor, Agent, Person
from limn.store import PinStore

Json: TypeAlias = dict[str, Any]          # a request's actor, a stored pin record, a notice
Row: TypeAlias = dict[str, Any]           # one stored pin as the store reads and writes it (limn.store.Row)
Event: TypeAlias = dict[str, Any]         # one events.jsonl record before emit fills in seq/at/ts


class MakeEvent(Protocol):
    """One notice about pin r by actor for the logins in to, or None when nobody is left to tell (server.make_event)."""

    def __call__(self, typ: str, r: Mapping[str, Any], actor: Mapping[str, Any], to: Iterable[str | None] | None,
                 msg: Mapping[str, Any] | None = None, text: str | None = None) -> Event | None:
        """Build the notice; recording it is emit_events' job."""
        ...


class NoteTagger(Protocol):
    """The saved note's @-tags and whom this save notifies (server.note_tags: people plus the recent notices)."""

    def __call__(self, note: str, old_note: str, rows: list[Row], hints: Iterable[str] | None,
                 actor: Mapping[str, Any], pid: object) -> NoteTags:
        """Resolve note against the people on rows; old_note is the note before this save ('' for a new pin)."""
        ...


@dataclass(frozen=True)
class PinContext:
    """What a pin service needs from the instance, made per call by the composition root (server.pin_context()).

    store is the pin store with the process-wide re-entrant lock: every service writes the pin files only through
    store.transact() or while holding store.lock. The clock is three readings of the same wall clock: now (the local
    'YYYY-MM-DD HH:MM:SS' every *_at string records), epoch (seconds: claim deadlines, Trash expiry, the audit line)
    and hm ('HH:MM', stamped on an appended note). Notices are built by make_event and recorded by emit_events, only
    after the pin write committed; audit appends one audit.jsonl line (action, by, details) and flocks and fsyncs, so
    it is called outside the lock. trash_checked is the process's memo of the last Trash expiry check (one element).
    """
    store: PinStore
    now: Callable[[], str]
    epoch: Callable[[], float]
    hm: Callable[[], str]
    make_event: MakeEvent
    emit_events: Callable[[list[Event | None]], None]
    who: Callable[[Mapping[str, Any]], Json]                    # an actor as notices and audit.jsonl record it
    audit: Callable[[str, Json, Json], object]
    known_people: Callable[[list[Row]], Mapping[str, Json]]     # @-tag candidates: people.json plus the people on rows
    note_tags: NoteTagger
    role_of: Callable[[str], str]                               # a login's people.json role
    person_name: Callable[[str], str]                           # a known person's display name, else the login
    locate: Callable[[Mapping[str, Any]], PinLocation | None]   # where a record's file is under the manuscript root now
    stamp: Callable[[Row], PinLocation | None]                  # records that location in the row (file, file_rel)
    thread_max: int                                             # cap on one pin's replies
    trash_days: int                                             # how long a dropped pin stays restorable
    trash_checked: list[float]


def is_agent(actor: Mapping[str, Any] | None) -> bool:
    """An agent actor: a headerless loopback request (LOCAL_ACTOR, login "local") or an API-token principal (login
    "agent:<name>"). Picks defaults (a close goes to review, never recorded in people.json) and refuses confirm; the
    role check in the handler (check_role) additionally covers people whose people.json role is agent."""
    login = (actor or {}).get("login", "local")
    return bool(login == LOCAL_ACTOR["login"] or str(login).startswith(AGENT_LOGIN_PREFIX))


def typed_actor(actor: Mapping[str, Any]) -> Actor:
    """The typed actor of a request's actor dict: an Agent when is_agent() says so, otherwise a Person (with its
    picture only when it is a non-empty string)."""
    login, name = actor.get("login", "local"), actor.get("name", "")
    if is_agent(actor):
        return Agent(login, name)
    pic = actor.get("pic")
    return Person(login, name, pic if isinstance(pic, str) and pic else None)
