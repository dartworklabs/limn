"""Public collaboration reads, sinks, and capability assembly."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from limn.collaboration import events
from limn.collaboration.contracts import Notice
from limn.collaboration.directory import PeopleDirectory
from limn.collaboration.notices import Notices
from limn.runtime.documents import Doc
from limn.security import access, people
from limn.web.routes import RouteBundle

Json = dict[str, Any]


@dataclass(frozen=True)
class PeopleView:
    """People reads and recording without pin models or storage."""

    _directory: PeopleDirectory

    @classmethod
    def create(
        cls,
        *,
        state: Callable[[], Path],
        people_file: Callable[[], Path],
        lock: Callable[[], threading.Lock],
        seen: Callable[[], people.SeenMemo],
        warning: Callable[[], people.UnreadableWarning],
        participants: Callable[[bool], Sequence[people.Row]],
        roles: Callable[[], access.PeopleRoles],
        clock: Callable[[], float],
    ) -> "PeopleView":
        """Create a view from the run's people resources and pin facts."""
        return cls(PeopleDirectory(state, people_file, lock, seen, warning, participants, roles, clock))

    def load(self) -> list[people.Row] | people.PeopleUnreadable:
        """Load the current people file fail-closed."""
        return self._directory.load()

    def record(self, actor: people.Row, now: float | None = None, role: access.Role | None = None) -> bool:
        """Record one human visit or role-changing action."""
        return self._directory.record(actor, now, role)

    def known(self, records: Sequence[people.Row] | None = None) -> dict[str, people.Row]:
        """Return known non-agent people from the file and detached pin facts."""
        return self._directory.known(records)

    def candidates(self) -> list[people.Row]:
        """Return current people candidates with roles."""
        return self._directory.candidates()


@dataclass(frozen=True)
class NoticeSink:
    """Create, persist, and read collaboration events."""

    _notices: Notices

    def read(self) -> tuple[list[events.Row], events.Signature | None]:
        """Read recent event rows and their signature."""
        return self._notices.read()

    def make_event(self, notice: Notice) -> Json | None:
        """Create one event from completed input after applying recipient exclusions."""
        return self._notices.make_event(notice)

    def emit_events(self, notices: list[Json | None]) -> None:
        """Persist events after their pin transaction committed."""
        self._notices.emit_events(notices)

    def since(self, actor: Json, cursor: int | None) -> Json:
        """Return events visible to an actor after a cursor."""
        return self._notices.since(actor, cursor)


@dataclass(frozen=True)
class CollaborationSubsystem:
    """The collaboration capability values used by composition."""

    people: PeopleView
    notices: NoticeSink
    routes: RouteBundle


def assemble_collaboration(
    *,
    state: Callable[[], Path],
    people_file: Callable[[], Path],
    people_lock: Callable[[], threading.Lock],
    seen: Callable[[], people.SeenMemo],
    warning: Callable[[], people.UnreadableWarning],
    participants: Callable[[bool], Sequence[people.Row]],
    roles: Callable[[], access.PeopleRoles],
    events_path: Callable[[], Path],
    events_lock: Callable[[], threading.Lock],
    cache: Callable[[], events.ReadCache],
    clock: Callable[[], float],
    stamp: Callable[[], str],
    docs: Callable[[], Sequence[Doc]],
) -> CollaborationSubsystem:
    """Assemble the people view and notice delivery without importing HTTP adapters."""
    people_view = PeopleView.create(
        state=state,
        people_file=people_file,
        lock=people_lock,
        seen=seen,
        warning=warning,
        participants=participants,
        roles=roles,
        clock=clock,
    )
    notices = Notices(events_path, events_lock, cache, clock, stamp, docs)
    from limn.collaboration.routes import get

    return CollaborationSubsystem(
        people_view,
        NoticeSink(notices),
        RouteBundle(get=(lambda request: get(request, people_view),)),
    )
