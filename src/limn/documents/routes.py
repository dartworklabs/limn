"""HTTP paths and complete replies for document state, outline and source reads."""

from limn.documents import http
from limn.documents.service import DocumentViews
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest


def get(request: GetRequest, service: DocumentViews) -> Reply | None:
    """Answer viewer meta, document list, outline labels or the source of the selected document; None lets another GET
    route match."""
    path = request.path
    if path == "/api/meta":
        return json_reply(
            http.meta(
                service,
                request.doc,
                request.actor,
                request.principal.role,
                request.query,
            )
        )
    if path == "/api/docs":
        return json_reply(http.docs(service))
    if path == "/api/outline-labels":
        return json_reply(http.outline(service, request.doc))
    if path == "/api/source":
        return json_reply(http.source(request.doc))
    return None
