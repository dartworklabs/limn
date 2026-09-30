"""Revision capability assembly."""

from collections.abc import Callable
from dataclasses import dataclass

from limn.revisions.core import RevisionContext
from limn.revisions.service import RevisionRequests
from limn.web.routes import PostDocRoute, RouteBundle


@dataclass(frozen=True)
class RevisionSubsystem:
    """Revision requests and their bound HTTP routes."""

    requests: RevisionRequests
    routes: RouteBundle


def assemble_revisions(context: Callable[[], RevisionContext]) -> RevisionSubsystem:
    """Bind revision requests and adapters to one run."""
    from limn.revisions.routes import POST_PATH, get, post

    requests = RevisionRequests(context)
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
