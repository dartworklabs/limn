"""HTTP paths and complete replies for reading Git history and comparison artifacts."""

from limn.documents import Doc
from limn.features.revisions import http
from limn.features.revisions.service import RevisionRequests
from limn.web.parse import Json, Query
from limn.web.reply import Reply, json_reply

POST_PATH = "/api/revision-build"


def get(path: str, query: Query, doc: Doc, requests: RevisionRequests) -> Reply | None:
    """Answer one revision GET route, or let the next registered route match."""
    if path == "/api/revisions":
        return json_reply(http.history(requests, doc))
    if path == "/api/revision-diff":
        return json_reply(http.diff(requests, doc, query))
    if path == "/api/revision-build":
        return json_reply(http.status(requests, doc, query))
    if path == "/api/revision-pdf":
        return Reply(200, http.pdf(requests, doc, query), "application/pdf", "private, max-age=600")
    return None


def post(_query: Query, body: Json, doc: Doc, requests: RevisionRequests) -> tuple[dict[str, object], int]:
    """Answer the registered comparison-build POST route for this document."""
    return http.start(requests, doc, body)
