"""HTTP paths and complete replies for manuscript snippets and pin overlaps."""

from limn.pins.location import http
from limn.pins.location.http import LocationApp
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest, PostDocRequest

POST_PATH = "/api/pick"


def get(request: GetRequest, app: LocationApp) -> Reply | None:
    """Answer one source-range read for the selected document."""
    path = request.path
    if path == "/api/snippet":
        return json_reply(http.snippet(app, request.doc, request.query))
    if path == "/api/overlaps":
        return json_reply(http.overlaps(app, request.doc, request.query))
    return None


def post(request: PostDocRequest, app: LocationApp) -> tuple[dict[str, object], int]:
    """Answer a PDF selection for the already selected document."""
    return http.pick(app, request.doc, request.body), 200
