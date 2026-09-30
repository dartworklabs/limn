"""Revision capability assembly."""

from collections.abc import Callable
from dataclasses import dataclass

from limn.pins import PinReadView
from limn.revisions.answer import revision_failure_text
from limn.revisions.core import RevisionContext, RevisionJobs, ScopeCache
from limn.revisions.service import RevisionRequests
from limn.web.routes import PostDocRoute, RouteBundle


@dataclass(frozen=True)
class RevisionSubsystem:
    """Revision requests and their bound HTTP routes."""

    requests: RevisionRequests
    routes: RouteBundle


def assemble_revisions(
    *,
    timeout: Callable[[], int],
    pins: PinReadView,
    cache: Callable[[], ScopeCache],
    jobs: Callable[[], RevisionJobs],
) -> RevisionSubsystem:
    """Bind revision resources and adapters while keeping failure rendering at its owner."""
    from limn.revisions.routes import POST_PATH, get, post

    requests = RevisionRequests(lambda: RevisionContext(timeout(), pins, cache(), jobs(), revision_failure_text))
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
