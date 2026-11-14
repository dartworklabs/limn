"""HTTP paths and complete replies for reading a document's build artifacts."""

from collections.abc import Callable

from limn.builds import http, input as build_input
from limn.builds.service import BuildRequests
from limn.runtime.documents import Doc
from limn.security.access import PostAuthority
from limn.web.parse import Json, Query
from limn.web.reply import Reply, attachment_disposition, json_reply

POST_PATH = "/api/rebuild"
HOLD_PATH = "/api/hold"


def get(path: str, query: Query, doc: Doc, text: Callable[[object], str]) -> Reply | None:
    """Answer build status, one page image or the matching PDF; None lets another GET route match. A page or PDF
    answer carries its Cache-Control and ETag (http.BuildFile); /pdf?download=1 adds a Content-Disposition naming the
    document's label."""
    if path == "/api/build":
        return json_reply(http.status(doc, query))
    if path.startswith("/pages/"):
        found = http.page(doc, path, text)
        if found is not None:
            return Reply(200, found.data, "image/png", found.cache, found.etag)
    if path == "/pdf":
        pdf = http.pdf(doc, query, text)
        disposition = attachment_disposition(doc.name) if build_input.parse_download(query) else None
        return Reply(200, pdf.data, "application/pdf", pdf.cache, pdf.etag, disposition)
    return None


def post(
    query: Query, _body: Json, doc: Doc, requests: BuildRequests, authority: PostAuthority
) -> tuple[dict[str, object], int]:
    """Answer the registered rebuild POST route for this document."""
    return http.rebuild(requests, doc, query, authority)


def post_hold(
    query: Query, body: Json, doc: Doc, requests: BuildRequests, authority: PostAuthority, text: Callable[[object], str]
) -> tuple[dict[str, object], int]:
    """Answer the registered build hold POST route for this document."""
    del query  # ?doc= is read by the common handler; the hold has no switch of its own
    return http.hold(requests, doc, body, authority, text)
