"""Query switches for the pin list."""

from typing import NamedTuple

from limn.web.parse import Query, parse_flag


class PinsQuery(NamedTuple):
    """GET /api/pins: include closed pins and filter to the selected document."""

    all: bool
    doc_scoped: bool


def parse_pins_query(q: Query) -> PinsQuery:
    """GET /api/pins switches; document selection was already checked by the shared guard."""
    return PinsQuery(parse_flag(q, "all"), bool(q.get("doc")))
