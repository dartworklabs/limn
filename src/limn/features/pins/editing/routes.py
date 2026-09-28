"""HTTP paths and complete replies for creating and editing pins."""

from limn.features.pins.editing import http
from limn.features.pins.editing.http import EditingRequests
from limn.web.routes import PinAction, PostDocRequest

POST_PATH = "/api/pin"
POST_NEW_PIN = True


def post(request: PostDocRequest, app: EditingRequests) -> tuple[dict[str, object], int]:
    """Answer one pin creation after the common document choice and guards."""
    return http.add(app, request.doc, request.actor, request.body), 200


def actions(app: EditingRequests) -> dict[str, PinAction]:
    """Bind the edit path to this run's service."""
    return {"edit": lambda r: http.edit(app, r.pid, r.actor, r.body)}
