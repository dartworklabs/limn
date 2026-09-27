"""HTTP paths and complete replies for document state and outline reads."""

from limn.features.document_views import http
from limn.features.document_views.service import DocumentViews
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest


def get(request: GetRequest, service: DocumentViews) -> Reply | None:
    """Answer viewer meta, document list or outline labels for the selected document."""
    path = request.path
    if path == "/api/meta":
        return json_reply(
            http.meta(
                service,
                request.doc,
                request.actor,
                request.principal.role,
                request.query,
                request.record_person,
            )
        )
    if path == "/api/docs":
        return json_reply(http.docs(service))
    if path == "/api/outline-labels":
        return json_reply(http.outline(service, request.doc))
    return None
