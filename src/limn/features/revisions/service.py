"""Per-instance revision requests using the established comparison jobs and cache."""

from collections.abc import Callable
from typing import Any

from limn import revisions
from limn.documents import Doc
from limn.revisions import DiffRefusal, PdfRefusal, StartRefusal, StatusRefusal


class RevisionRequests:
    """Connect revision operations to this server's live request context."""

    def __init__(self, context: Callable[[], revisions.RevisionContext]) -> None:
        """Read the current instance settings and caches for each request."""
        self.context = context

    def history(self, doc: Doc) -> dict[str, Any]:
        """List recent commits of this document."""
        return revisions.revision_history(doc)

    def diff(self, doc: Doc, commit: str, pin: int | None = None) -> dict[str, Any] | DiffRefusal:
        """Read the source changes between a commit and its parent."""
        return revisions.revision_diff(doc, commit, pin, self.context())

    def status(self, doc: Doc, commit: str, pin: int | None = None) -> dict[str, Any] | StatusRefusal:
        """Read a comparison job or cached PDF state."""
        return revisions.revision_status(doc, commit, pin, self.context())

    def start(self, doc: Doc, commit: str, pin: int | None = None) -> dict[str, Any] | StartRefusal:
        """Start a comparison PDF job using this instance's slots and cache."""
        return revisions.revision_start(doc, commit, pin, self.context())

    def pdf(self, doc: Doc, commit: str, pin: int | None = None) -> bytes | PdfRefusal:
        """Read the comparison PDF, or return the existing refusal outcome."""
        return revisions.revision_pdf(doc, commit, pin, self.context())
