"""Per-instance revision requests using the established comparison jobs and cache."""

from collections.abc import Callable
from typing import Any

from limn.revisions import core as revisions, jobs
from limn.revisions.core import DiffRefusal, PdfRefusal, StartRefusal, StatusRefusal
from limn.runtime.documents import Doc, document_authority_target
from limn.security.access import AuthorityScope, PostAuthority, require_authority


class RevisionRequests:
    """Connect revision operations to this server's live request context."""

    def __init__(self, context: Callable[[], revisions.RevisionContext]) -> None:
        """Read the current instance settings and caches for each request."""
        self.context = context

    @property
    def authority_scope(self) -> AuthorityScope:
        """Bind comparison requests to this service's current job and cache resources."""
        context = self.context()
        return AuthorityScope(self, "", (context.jobs, context.cache))

    def history(self, doc: Doc) -> dict[str, Any]:
        """List recent commits of this document."""
        return revisions.revision_history(doc)

    def diff(self, doc: Doc, commit: str, pin: int | None = None) -> dict[str, Any] | DiffRefusal:
        """Read the source changes between a commit and its parent."""
        return revisions.revision_diff(doc, commit, pin, self.context())

    def status(self, doc: Doc, commit: str, pin: int | None = None) -> dict[str, Any] | StatusRefusal:
        """Read a comparison job or cached PDF state."""
        return jobs.revision_status(doc, commit, pin, self.context())

    def start(
        self, doc: Doc, commit: str, pin: int | None = None, *, authority: PostAuthority
    ) -> dict[str, Any] | StartRefusal:
        """Start a comparison PDF job using this instance's slots and cache."""
        context = self.context()
        require_authority(
            authority,
            AuthorityScope(self, "", (context.jobs, context.cache)),
            "revision-build",
            document_authority_target(doc),
        )
        return jobs.revision_start(doc, commit, pin, context)

    def pdf(self, doc: Doc, commit: str, pin: int | None = None) -> bytes | PdfRefusal:
        """Read the comparison PDF, or return the existing refusal outcome."""
        return jobs.revision_pdf(doc, commit, pin, self.context())
