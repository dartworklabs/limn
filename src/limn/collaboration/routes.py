"""HTTP path and complete reply for the people autocomplete list."""

from limn.collaboration import http
from limn.collaboration.http import PeopleCandidates
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest


def get(request: GetRequest, directory: PeopleCandidates) -> Reply | None:
    """Answer the people's list with the requesting person's role."""
    path = request.path
    if path == "/api/people":
        return json_reply(http.people_list(directory, request.actor, request.principal.role))
    return None
