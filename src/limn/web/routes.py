"""The common contracts for registered HTTP routes."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, NamedTuple, TypeAlias, TypeVar

from limn.runtime.documents import Doc
from limn.security import access
from limn.web.parse import Query
from limn.web.reply import Reply


class GetRequest(NamedTuple):
    """A guarded GET with its selected document, request-local identity facts and its If-None-Match header (None
    without one): a route whose answer carries an ETag may tell a 304 before it reads what it would send."""

    path: str
    query: Query
    doc: Doc
    actor: dict[str, Any]
    principal: access.Principal
    host_raw: str
    if_none_match: str | None = None


GetRoute: TypeAlias = Callable[[GetRequest], Reply | None]


class PostDocRequest(NamedTuple):
    """A guarded POST with parsed JSON, its selected document and request-local identity."""

    query: Query
    body: dict[str, Any]
    doc: Doc
    actor: access.PostAuthority
    principal: access.Principal


class PostDocRoute(NamedTuple):
    """One POST path whose action needs the document selected by the common handler."""

    path: str
    action: Callable[[PostDocRequest], tuple[dict[str, object], int]]
    new_pin: bool = False


class PinActionRequest(NamedTuple):
    """A guarded action on one pin after parsing its JSON body."""

    pid: int
    actor: access.PostAuthority
    body: dict[str, Any]
    principal: access.Principal


PinAction: TypeAlias = Callable[[PinActionRequest], dict[str, object]]


class OtherPostRequest(NamedTuple):
    """A guarded POST with no selected document or pin."""

    actor: access.PostAuthority
    body: dict[str, Any]
    principal: access.Principal


OtherPost: TypeAlias = Callable[[OtherPostRequest], dict[str, object]]


class PathPolicy(NamedTuple):
    """The headers every response for one path carries, whatever it answers - a success, a 304, a refusal of the
    route itself or one raised before it ran (401, 403, an unknown document), a 500: its Content-Security-Policy, in
    place of FRAME_ONLY or a page's own, and its Cross-Origin-Resource-Policy."""

    csp: str
    resource_policy: str


@dataclass(frozen=True)
class RouteBundle:
    """One capability's ordered reads, uniquely keyed mutation routes and the paths whose every response carries
    fixed policy headers (policies, keyed by path)."""

    get: tuple[GetRoute, ...] = ()
    post_documents: tuple[PostDocRoute, ...] = ()
    pin_actions: Mapping[str, PinAction] = field(default_factory=dict)
    other_posts: Mapping[str, OtherPost] = field(default_factory=dict)
    policies: Mapping[str, PathPolicy] = field(default_factory=dict)


Route = TypeVar("Route")


def _merge_keyed(kind: str, groups: tuple[Mapping[str, Route], ...]) -> dict[str, Route]:
    """Merge keyed routes, refusing any ambiguous registration."""
    merged: dict[str, Route] = {}
    for group in groups:
        for key, route in group.items():
            if key in merged:
                raise ValueError("duplicate %s route: %s" % (kind, key))
            merged[key] = route
    return merged


def merge_routes(*bundles: RouteBundle) -> RouteBundle:
    """Combine capability bundles without changing ordered fallthrough dispatch."""
    posts: list[PostDocRoute] = []
    paths: set[str] = set()
    for bundle in bundles:
        for route in bundle.post_documents:
            if route.path in paths:
                raise ValueError("duplicate document POST route: %s" % route.path)
            paths.add(route.path)
            posts.append(route)
    return RouteBundle(
        get=tuple(route for bundle in bundles for route in bundle.get),
        post_documents=tuple(posts),
        pin_actions=_merge_keyed("pin action", tuple(bundle.pin_actions for bundle in bundles)),
        other_posts=_merge_keyed("POST", tuple(bundle.other_posts for bundle in bundles)),
        policies=_merge_keyed("path policy", tuple(bundle.policies for bundle in bundles)),
    )
