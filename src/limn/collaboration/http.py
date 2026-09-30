"""The GET /api/people response after the shared request guard."""

from collections.abc import Mapping
from typing import Any, Protocol

from limn.security import access


class PeopleCandidates(Protocol):
    """The single people operation used by the HTTP projection."""

    def candidates(self) -> list[dict[str, Any]]:
        """Return the people visible to autocomplete."""
        ...


def people_list(service: PeopleCandidates, actor: Mapping[str, Any], role: access.Role) -> dict[str, Any]:
    """Autocomplete candidates and the requesting person's role, in the existing key order."""
    return {"people": service.candidates(), "me": dict(actor, role=role)}
