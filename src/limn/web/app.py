"""What the common HTTP handler needs from its bound application.

The handler never imports server.py. server.py is loaded more than once in one process (limn.server, __main__ when
run as a file, and each test module's copy loaded by path); an import could reach a different copy than the one
serving. Each composition root creates a ServerApplication with its own configuration, documents and locks and binds
it to that copy's handler class (server.Handler.app). The handler calls through the bound object at request time.

The handler finds a request's document and passes it to registered feature routes. Each feature declares its own
narrow collaborator contract. This Protocol covers only guard, selection, registration, and refusal dependencies
that the common handler itself reads.

The run settings, a document and a principal are server.py's own types (limn.runtime.config.RunConfig, limn.runtime.documents.Doc,
limn.security.access.Principal), not narrower views of them: ServerApplication's members take those types, and mypy checks
ServerApplication against this Protocol in server.py, so a missing or wrongly typed binding is a type error.
src/limn/web/tests/test_web.py checks at run time that the bound application provides every member.
"""

from email.message import Message
from typing import Any, Protocol, TypeAlias

from limn.runtime.config import RunConfig
from limn.runtime.documents import Doc, DocNotFound
from limn.security import access
from limn.web.errors import Messages
from limn.web.routes import GetRoute, OtherPost, PinAction, PostDocRoute

Json: TypeAlias = dict[str, Any]  # a JSON object: request body, response payload, actor, stored pin record
Query: TypeAlias = dict[str, list[str]]  # parse_qs() of the request's query string


# The run settings, document, and principal are server.py's own types, so its bindings type-check against App.
Config: TypeAlias = RunConfig
Document: TypeAlias = Doc
Principal: TypeAlias = access.Principal


class PeopleRecorder(Protocol):
    """The visit-recording operation needed by the common transport layer."""

    def record(self, actor: Json, now: float | None = None, role: access.Role | None = None) -> bool:
        """Record a human visit with the verified role; return whether the file changed."""
        ...


class ViewerMessages(Protocol):
    """Messages needed to render an admission refusal without a viewer dependency."""

    @property
    def messages(self) -> Messages:
        """Return the immutable view of this run's UI translation table."""
        ...


class App(Protocol):
    """The server application as the handler sees it, with the services and their typed contracts."""

    C: Config
    get_routes: tuple[GetRoute, ...]
    post_doc_routes: tuple[PostDocRoute, ...]
    pin_actions: dict[str, PinAction]
    other_posts: dict[str, OtherPost]

    @property
    def people_directory(self) -> PeopleRecorder:
        """Expose visit recording without depending on a feature implementation."""
        ...

    def viewer(self) -> ViewerMessages:
        """Return this run's viewer messages for a refused browser opening the first page."""
        ...

    # ---- request guard: Host/Origin, identity, admission, roles (limn.security.access, bound to this run by server.py)

    def host_ok(self, host: str) -> bool:
        """Is Host a loopback name, *.ts.net or a --public-host?"""
        ...

    def origin_ok(self, origin: str, host: str | None) -> bool:
        """Is Origin on the same side as the Host the request arrived on?"""
        ...

    def hdr_text(self, v: object) -> str:
        """A header value as text (RFC 2047 decoded), for messages."""
        ...

    def identify(self, headers: Message, peer: str) -> Principal:
        """Who the request is (token, identity headers, loopback agent); raises HTTPError 401/403."""
        ...

    def admit(self, p: Principal, host: str | None, headers: Message | None = None) -> None:
        """May this principal use the instance at all; raises HTTPError 403."""
        ...

    def check_role(self, p: Principal, path: str) -> None:
        """The role rule for a POST to path; raises HTTPError 403."""
        ...

    def authorize_post(self, p: Principal, path: str, doc: Document | None = None) -> access.PostAuthority:
        """Issue immutable authority for the selected target after admission and role checks."""
        ...

    def check_read(self, path: str) -> None:
        """Refuse undeclared read routes before dispatch."""
        ...

    # ---- the request's document

    def request_doc(self, key: str | None, file_hint: object = None) -> Document | DocNotFound:
        """The document key names (parsed by limn.web.parse.parse_doc_key), or - with none - the one holding
        file_hint, else the first; DocNotFound for a key the instance does not serve."""
        ...
