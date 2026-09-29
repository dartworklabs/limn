"""The common contracts for registered HTTP routes."""

from collections.abc import Callable
from typing import Any, NamedTuple, TypeAlias

from limn import access
from limn.documents import Doc
from limn.web.parse import Query
from limn.web.reply import Reply


class GetRequest(NamedTuple):
    """A guarded GET with its selected document and request-local identity facts."""

    path: str
    query: Query
    doc: Doc
    actor: dict[str, Any]
    principal: access.Principal
    host_raw: str
    record_person: Callable[[], None]


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
