"""Bind people.json, current pins and roles for people visible to one run."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from limn.pins import PinReadView
from limn.security import access, people
from limn.security.access import is_agent_actor


@dataclass(frozen=True)
class PeopleDirectory:
    """The run's people file, write memo, candidate sources and role lookup."""

    state: Callable[[], Path]
    people_file: Callable[[], Path]
    lock: Callable[[], threading.Lock]
    seen: Callable[[], people.SeenMemo]
    warning: Callable[[], people.UnreadableWarning]
    pins: PinReadView
    roles: Callable[[], access.PeopleRoles]
    clock: Callable[[], float]

    def book(self) -> people.PeopleBook:
        """The current file path and this run's shared lock, memo and warning."""
        return people.PeopleBook(self.state(), self.lock(), self.seen(), self.warning())

    def load(self) -> list[people.Row] | people.PeopleUnreadable:
        """Read the current people file and warn once per breakage."""
        path = self.people_file()
        rows = people.load_people(path)
        self.warning().note(path, rows)
        return rows

    def record(self, actor: people.Row, now: float | None = None, role: access.Role | None = None) -> bool:
        """Record a human visit or change; local and token agents are never recorded."""
        login = (actor or {}).get("login")
        if not login or is_agent_actor(actor):
            return False
        return people.record_person(self.book(), actor, self.clock() if now is None else now, role, access.DEFAULT_ROLE)

    def known(self, records: Sequence[people.Row] | None = None) -> dict[str, people.Row]:
        """People from people.json and pin actors, excluding agents."""
        listed = self.load()
        rows = [] if isinstance(listed, people.PeopleUnreadable) else listed
        on = records if records is not None else self.pins.people_records()
        return people.known_people(rows, on, is_agent_actor)

    def candidates(self) -> list[people.Row]:
        """Read roles first, then resynchronize pins and order the candidates."""
        roles = self.roles()
        return people.candidates(
            self.known(self.pins.people_records(refresh=True)), lambda login: access.person_role(roles, login)
        )
