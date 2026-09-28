"""HTTP bodies for the pin JSON routes after common GET guards."""

from collections.abc import Mapping
from typing import Any, Protocol

from limn.features.pins.listing import input as listing_input
from limn.features.pins.listing.markdown import PinMarkdown
from limn.features.pins.listing.service import PinListing
from limn.pins.model import PinNotFound
from limn.web.errors import HTTPError


class ListingApp(Protocol):
    """The run-bound listing collaborator."""

    pin_listing: PinListing
    pin_markdown: PinMarkdown


def pins(app: ListingApp, q: Mapping[str, list[str]], doc_key: str) -> list[dict[str, Any]]:
    """List pins and apply the selected-document filter after global overlap calculation."""
    parsed = listing_input.parse_pins_query(q)
    return app.pin_listing.list_payload(parsed.all, doc_key if parsed.doc_scoped else None)


def one(app: ListingApp, pid: int) -> dict[str, object]:
    """One pin with its full thread, or the contract's 404."""
    return pin_answer(app.pin_listing.pin_payload(pid))


def dropped(app: ListingApp) -> dict[str, object]:
    """The visible Trash entries."""
    return {"dropped": app.pin_listing.dropped_payload()}


def markdown(app: ListingApp, base: str) -> str:
    """Render the current pins.md with the request's remote base."""
    return app.pin_markdown.current_text(base)


def pin_answer(result: dict[str, Any] | PinNotFound) -> dict[str, object]:
    """GET /api/pins/{id}: the pin as the full list renders it, or 404 pin_not_found."""
    match result:
        case dict():
            return {"pin": result}
        case PinNotFound(pid=pid):
            raise HTTPError(404, "핀 #%d 이 없습니다." % pid, reason="pin_not_found")
