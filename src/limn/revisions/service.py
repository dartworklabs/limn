"""Per-instance revision requests using the established comparison jobs and cache."""

from collections.abc import Callable
from typing import Any

from limn.revisions import core as revisions, jobs
from limn.revisions.core import (
    CommitNotRecent,
    DiffRefusal,
    HistoryPage,
    PdfRefusal,
    RangeRefusal,
    StartRefusal,
    StatusRefusal,
)
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

    def history(self, doc: Doc, page: HistoryPage | None = None) -> dict[str, Any] | CommitNotRecent:
        """List this document's commits: the recent ones, or one page of its history window (page; CommitNotRecent for
        a before outside it). A figure document's list covers the files its current build's map names
        (RevisionBuildQueries.history_files), and its answer adds `overlay`, the two builds the viewer lays one over
        the other - present even when the folder has no Git history. Any other document's unpaged answer keeps its two
        keys."""
        context = self.context()
        out = revisions.revision_history(doc, context.history_files(doc), page)
        if isinstance(out, CommitNotRecent):
            return out
        overlay = context.overlay(doc)
        if overlay is not None:
            out["overlay"] = overlay
        return out

    def diff(
        self, doc: Doc, commit: str, pin: int | None = None, base: str | None = None
    ) -> dict[str, Any] | DiffRefusal | RangeRefusal:
        """Read the source changes between a commit and its parent, or from base to the commit (a range), scoped like
        history()."""
        context = self.context()
        return revisions.revision_diff(doc, commit, pin, context, context.history_files(doc), base)

    def status(
        self, doc: Doc, commit: str, pin: int | None = None, base: str | None = None
    ) -> dict[str, Any] | StatusRefusal | RangeRefusal:
        """Read a comparison job or cached PDF state (of the range from base when given)."""
        return jobs.revision_status(doc, commit, pin, self.context(), base)

    def start(
        self, doc: Doc, commit: str, pin: int | None = None, *, authority: PostAuthority, base: str | None = None
    ) -> dict[str, Any] | StartRefusal | RangeRefusal:
        """Start a comparison PDF job (of the range from base when given) using this instance's slots and cache."""
        context = self.context()
        require_authority(
            authority,
            AuthorityScope(self, "", (context.jobs, context.cache)),
            "revision-build",
            document_authority_target(doc),
        )
        return jobs.revision_start(doc, commit, pin, context, base)

    def pdf(
        self, doc: Doc, commit: str, pin: int | None = None, base: str | None = None
    ) -> bytes | PdfRefusal | RangeRefusal:
        """Read the comparison PDF (of the range from base when given), or return the existing refusal outcome."""
        return jobs.revision_pdf(doc, commit, pin, self.context(), base)
