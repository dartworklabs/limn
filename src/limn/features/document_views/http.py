"""HTTP responses for viewer meta, document list and published outline labels."""

from collections.abc import Callable, Mapping
from typing import Any

from limn import access
from limn.documents import Doc
from limn.features.document_views import input as document_input
from limn.features.document_views.service import DocumentViews
from limn.web import parse
from limn.web.answers import accepted

Json = dict[str, Any]


def meta(
    service: DocumentViews,
    doc: Doc,
    actor: Json,
    role: access.Role,
    query: Mapping[str, list[str]],
    record_person: Callable[[], None],
) -> Json:
    """GET /api/meta: record a full viewer read, then append role and event notifications."""
    light = parse.parse_flag(query, "light")
    if not light:
        record_person()
    out = service.meta(doc, actor, light)
    out["me"] = dict(actor, role=role)
    # Preserve the existing order: an invalid event cursor is refused only after meta is built.
    out.update(service.events_since(actor, accepted(document_input.parse_events_query(query))))
    return out


def docs(service: DocumentViews) -> Json:
    """GET /api/docs."""
    return service.docs_payload()


def outline(service: DocumentViews, doc: Doc) -> Json:
    """GET /api/outline-labels."""
    return service.outline(doc)
