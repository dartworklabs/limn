"""HTTP paths and complete replies for document state, outline, source and tree-image reads."""

from limn.documents import http
from limn.documents.assets import AssetTags
from limn.documents.service import DocumentViews
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest


def get(request: GetRequest, service: DocumentViews, tags: AssetTags) -> Reply | None:
    """Answer viewer meta, document list, outline labels, the source of the selected document or an image of its
    manuscript tree (tags: the run's content tags of the images it sent); None lets another GET route match."""
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
    if path == "/api/asset":
        return http.asset(request.doc, request.query, tags, request.if_none_match)
    return None
