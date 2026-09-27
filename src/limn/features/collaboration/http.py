"""The GET /api/people response after the shared request guard."""

from collections.abc import Mapping
from typing import Any

from limn import access
from limn.features.collaboration.directory import PeopleDirectory


def people_list(service: PeopleDirectory, actor: Mapping[str, Any], role: access.Role) -> dict[str, Any]:
    """Autocomplete candidates and the requesting person's role, in the existing key order."""
    return {"people": service.candidates(), "me": dict(actor, role=role)}
