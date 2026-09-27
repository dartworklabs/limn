"""HTTP path and complete reply for creating a pin."""

from limn.features.pins.editing import http
from limn.features.pins.editing.http import EditingApp
from limn.web.routes import PostDocRequest

POST_PATH = "/api/pin"
POST_NEW_PIN = True


def post(request: PostDocRequest, app: EditingApp) -> tuple[dict[str, object], int]:
    """Answer one pin creation after the common document choice and guards."""
    return http.add(app, request.doc, request.actor, request.body), 200
