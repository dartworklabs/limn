"""Concrete HTTP application containing only request-boundary ports."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias

from limn.runtime.config import RunConfig
from limn.runtime.documents import Doc, DocNotFound
from limn.security import access
from limn.security.application import RequestGuards
from limn.web.errors import Messages
from limn.web.routes import RouteBundle

Json: TypeAlias = dict[str, Any]
Query: TypeAlias = dict[str, list[str]]
Document: TypeAlias = Doc
Principal: TypeAlias = access.Principal


class PeopleRecorder(Protocol):
    """The visit-recording operation needed by the common transport layer."""

    def record(self, actor: Json, now: float | None = None, role: access.Role | None = None) -> bool:
        """Record a human visit with the verified role; return whether the file changed."""
        ...


@dataclass(frozen=True)
class DocumentSelector:
    """Choose the target document using the run's current document list."""

    select: Callable[[str | None, object], Doc | DocNotFound]


@dataclass(frozen=True)
class RouteRegistry:
    """The complete route bundle in stable dispatch order."""

    bundle: RouteBundle


@dataclass(frozen=True)
class WebApplication:
    """A listener's guards, target selection, dispatch and visit-recording ports."""

    settings: Callable[[], RunConfig]
    guards: RequestGuards
    selector: DocumentSelector
    routes: RouteRegistry
    recorder: PeopleRecorder
    messages: Callable[[], Messages]
    header_text: Callable[[object], str]
