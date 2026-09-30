"""Git history and comparison PDF routes after common request guards."""

from typing import Any

from limn.revisions import answer, input as revision_input
from limn.revisions.service import RevisionRequests
from limn.runtime.documents import Doc
from limn.security.access import PostAuthority
from limn.web.answers import accepted
from limn.web.parse import Json, Query


def history(requests: RevisionRequests, doc: Doc) -> dict[str, Any]:
    """GET /api/revisions for one document."""
    return requests.history(doc)


def diff(requests: RevisionRequests, doc: Doc, query: Query) -> dict[str, Any]:
    """GET /api/revision-diff with pin before commit validation."""
    commit, pin = accepted(revision_input.parse_revision_query(query))
    return answer.revision_answer(requests.diff(doc, commit, pin))


def status(requests: RevisionRequests, doc: Doc, query: Query) -> dict[str, Any]:
    """GET /api/revision-build with the existing comparison state answer."""
    commit, pin = accepted(revision_input.parse_revision_query(query))
    return answer.revision_answer(requests.status(doc, commit, pin))


def pdf(requests: RevisionRequests, doc: Doc, query: Query) -> bytes:
    """GET /api/revision-pdf bytes or its contract refusal."""
    commit, pin = accepted(revision_input.parse_revision_query(query))
    return answer.revision_pdf_answer(requests.pdf(doc, commit, pin))


def start(requests: RevisionRequests, doc: Doc, body: Json, authority: PostAuthority) -> tuple[dict[str, Any], int]:
    """POST /api/revision-build after its body has passed the common JSON check."""
    commit, pin = accepted(revision_input.parse_revision_build(body))
    return answer.revision_start_answer(requests.start(doc, commit, pin, authority=authority))
