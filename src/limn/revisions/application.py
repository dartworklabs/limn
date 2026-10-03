"""Revision capability assembly."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from limn.pins import RevisionPinQuery
from limn.revisions.answer import revision_failure_text
from limn.revisions.core import RevisionContext, RevisionJobs, ScopeCache
from limn.revisions.service import RevisionRequests
from limn.runtime.documents import Doc
from limn.web.routes import PostDocRoute, RouteBundle


@dataclass(frozen=True)
class RevisionSubsystem:
    """Revision requests and their bound HTTP routes."""

    requests: RevisionRequests
    routes: RouteBundle


def assemble_revisions(
    *,
    timeout: Callable[[], int],
    pins: RevisionPinQuery,
    cache: Callable[[], ScopeCache],
    jobs: Callable[[], RevisionJobs],
    history_files: Callable[[Doc], tuple[Path, ...] | None],
    overlay: Callable[[Doc], dict[str, Any] | None],
) -> RevisionSubsystem:
    """Bind revision resources and adapters while keeping failure rendering at its owner. history_files and overlay
    are the build owner's answers for a figure document - the files whose history its changes are, and the two builds
    the viewer lays one over the other - that the composition root injects (None for any other document)."""
    from limn.revisions.routes import POST_PATH, get, post

    requests = RevisionRequests(
        lambda: RevisionContext(timeout(), pins, cache(), jobs(), revision_failure_text, history_files, overlay)
    )
    routes = RouteBundle(
        get=(lambda request: get(request.path, request.query, request.doc, requests),),
        post_documents=(
            PostDocRoute(
                POST_PATH,
                lambda request: post(request.query, request.body, request.doc, requests, request.actor),
            ),
        ),
    )
    return RevisionSubsystem(requests, routes)
