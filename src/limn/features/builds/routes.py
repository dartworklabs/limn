"""HTTP paths and complete replies for reading a document's build artifacts."""

from collections.abc import Callable

from limn.documents import Doc
from limn.features.builds import http
from limn.features.builds.service import BuildRequests
from limn.web.parse import Json, Query
from limn.web.reply import Reply, json_reply

POST_PATH = "/api/rebuild"


def get(path: str, query: Query, doc: Doc, text: Callable[[object], str]) -> Reply | None:
    """Answer build status, one page image or the matching PDF; None lets another GET route match."""
    if path == "/api/build":
        return json_reply(http.status(doc, query))
    if path.startswith("/pages/"):
        data = http.page(doc, path)
        if data is not None:
            return Reply(200, data, "image/png")
    if path == "/pdf":
        return Reply(200, http.pdf(doc, query, text), "application/pdf", "private, max-age=600")
    return None


def post(query: Query, _body: Json, doc: Doc, requests: BuildRequests) -> tuple[dict[str, object], int]:
    """Answer the registered rebuild POST route for this document."""
    return http.rebuild(requests, doc, query)
