"""What the common HTTP handler needs from its bound application.

The handler never imports server.py. server.py is loaded more than once in one process (limn.server, __main__ when
run as a file, and each test module's copy loaded by path); an import could reach a different copy than the one
serving. Each composition root creates a ServerApplication with its own configuration, documents and locks and binds
it to that copy's handler class (server.Handler.app). The handler calls through the bound object at request time.

The handler finds a request's document and passes it to registered feature routes. Each feature declares its own
narrow collaborator contract. This Protocol covers only guard, selection, registration, and refusal dependencies
that the common handler itself reads.

The run settings, a document and a principal are server.py's own types (limn.config.RunConfig, limn.documents.Doc,
limn.access.Principal), not narrower views of them: ServerApplication's members take those types, and mypy checks
ServerApplication against this Protocol in server.py, so a missing or wrongly typed binding is a type error.
tests/test_web.py checks at run time that the bound application provides every member.
"""

from email.message import Message
from typing import Any, Protocol, TypeAlias

from limn import access
from limn.config import RunConfig
from limn.documents import Doc, DocNotFound
from limn.features.collaboration.directory import PeopleDirectory
from limn.viewer.assemble import ServedViewer
from limn.web.routes import GetRoute, OtherPost, PinAction, PostDocRoute

Json: TypeAlias = dict[str, Any]  # a JSON object: request body, response payload, actor, stored pin record
Query: TypeAlias = dict[str, list[str]]  # parse_qs() of the request's query string


# The run settings, document, and principal are server.py's own types, so its bindings type-check against App.
Config: TypeAlias = RunConfig
Document: TypeAlias = Doc
Principal: TypeAlias = access.Principal


class App(Protocol):
    """The server application as the handler sees it, with the services and their typed contracts."""

    C: Config
    people_directory: PeopleDirectory
    get_routes: tuple[GetRoute, ...]
    post_doc_routes: tuple[PostDocRoute, ...]
    pin_actions: dict[str, PinAction]
    other_posts: dict[str, OtherPost]

    def viewer(self) -> ServedViewer:
        """Return this run's viewer messages for a refused browser opening the first page."""
        ...

    # ---- request guard: Host/Origin, identity, admission, roles (limn.access, bound to this run by server.py)

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
