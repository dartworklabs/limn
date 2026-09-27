"""Read the people visible to one run's autocomplete route."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from limn import access, people
from limn.pins.model import Pin


@dataclass(frozen=True)
class PeopleList:
    """The current roles, live pins and known people of one server run."""

    roles: Callable[[], access.PeopleRoles]
    snapshot_pins: Callable[[], list[Pin]]
    known_people: Callable[[Sequence[Pin] | None], dict[str, people.Row]]

    def candidates(self) -> list[people.Row]:
        """Read roles first, then resynchronize pins and order the candidates."""
        roles = self.roles()
        return people.candidates(
            self.known_people(self.snapshot_pins()), lambda login: access.person_role(roles, login)
        )
