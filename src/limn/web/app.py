"""What the HTTP handler needs from the application: the services, settings and texts it calls, as one Protocol.

The handler never imports server.py. server.py is loaded more than once in one process (limn.server, __main__ when
run as a file, and each test module's copy loaded by path); an import could reach a different copy than the one
serving. Each composition root creates a ServerApplication with its own configuration, documents and locks and binds
it to that copy's handler class (server.Handler.app). The handler calls through the bound object at request time.

The members are server.py's services and wirings. The handler finds the request's document (request_doc) and passes
it to every member that acts on one - there is no "current document" - and it parses what a route takes from the
request (limn.web.parse) and passes the parsed values. Some members read the frozen run settings C
(limn.config.RunConfig) held by ServerApplication.

The run settings, a document and a principal are server.py's own types (limn.config.RunConfig, limn.documents.Doc,
limn.access.Principal), not narrower views of them: ServerApplication's members take those types, and mypy checks
ServerApplication against this Protocol in server.py, so a missing or wrongly typed binding is a type error.
tests/test_web.py checks at run time that the bound application provides every member.
"""

from collections.abc import Collection
from email.message import Message
from pathlib import Path
from typing import Any, Protocol, TypeAlias

from limn import access
from limn.config import RunConfig
from limn.documents import Doc, DocNotFound
from limn.features.builds.service import BuildRequests
from limn.features.collaboration.directory import PeopleDirectory
from limn.features.document_views.service import DocumentViews
from limn.features.pins.claims.service import PinClaims
from limn.features.pins.editing.service import PinEditing
from limn.features.pins.lifecycle.service import PinLifecycle
from limn.features.pins.listing.markdown import PinMarkdown
from limn.features.pins.listing.service import PinListing
from limn.features.pins.location.service import PinLocationService
from limn.features.pins.trash.service import PinTrash
from limn.features.revisions.service import RevisionRequests
from limn.pins.model import Pin, Record
from limn.viewer.assemble import ServedViewer
from limn.web.parse import DocumentFacts
from limn.web.routes import GetRoute

Json: TypeAlias = dict[str, Any]  # a JSON object: request body, response payload, actor, stored pin record
Query: TypeAlias = dict[str, list[str]]  # parse_qs() of the request's query string


# The run settings the handler reads (C: origin_check, src, state, accent), a document a request acts on (key, is_pdf) and
# who a request is (actor, role, via) - server.py's own types, so its members type-check against App.
Config: TypeAlias = RunConfig
Document: TypeAlias = Doc
Principal: TypeAlias = access.Principal


class App(Protocol):
    """The server application as the handler sees it, with the services and their typed contracts."""

    C: Config
    pin_lifecycle: PinLifecycle
    pin_claims: PinClaims
    pin_trash: PinTrash
    pin_editing: PinEditing
    pin_listing: PinListing
    pin_markdown: PinMarkdown
    location_service: PinLocationService
    build_requests: BuildRequests
    people_directory: PeopleDirectory
    document_views: DocumentViews
    revision_requests: RevisionRequests
    get_routes: tuple[GetRoute, ...]
    APP_NAME: str
    DEFAULT_ROLE: access.Role  # the role of a person people.json gives none

    def viewer(self) -> ServedViewer:
        """What the viewer routes serve on this run: the page for GET / (label and accent filled in), the service
        worker for GET /sw.js and the ko -> en message table a refused browser's page reads."""
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

    # ---- the request's document

    def request_doc(self, key: str | None, file_hint: object = None) -> Document | DocNotFound:
        """The document key names (parsed by limn.web.parse.parse_doc_key), or - with none - the one holding
        file_hint, else the first; DocNotFound for a key the instance does not serve."""
        ...

    def document_facts(self, D: Document) -> DocumentFacts:
        """What the location parsers read about document D and the manuscript (limn.web.parse.DocumentFacts)."""
        ...

    def edit_scope(self, pid: int) -> tuple[bool, Document]:
        """Whether pin pid is a view-only (region) pin, and the document its edit's loc is checked against: the pin's
        own, else the current one. Read without the lock, before the edit."""
        ...

    def assignee_people(self, d: Json) -> Collection[str]:
        """The logins an assignee in body d is checked against: the known people when d names one, else none."""
        ...

    # ---- reads

    def app_version(self) -> str:
        """The installed Limn version."""
        ...

    def people_roles(self) -> access.PeopleRoles:
        """{login: role} from people.json, or PeopleUnreadable while it cannot be used."""
        ...

    def snapshot_pins(self) -> list[Pin]:
        """The pins, parsed, re-synced and saved under the pin lock."""
        ...

    def remote_base_for(self, host_raw: str) -> str:
        """The base URL for GET /pins.md's guidance."""
        ...

    def vendor_file(self, name: str) -> Path | None:
        """The bundled PDF.js file GET /vendor/pdfjs/<name> serves, or None."""
        ...

    def public(self, r: Record) -> Json:
        """A pin record as the API returns it."""
        ...

    def pin_state(self, r: Record) -> str:
        """'open' | 'review' | 'done'."""
        ...

    # ---- changes
