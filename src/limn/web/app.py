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

from collections.abc import Collection, Sequence
from email.message import Message
from pathlib import Path
from typing import Any, Protocol, TypeAlias

from limn import access
from limn.build import BuildBusy, BuildStarted, FinishedBuild, ViewOnlyNoRebuild
from limn.config import RunConfig
from limn.documents import Doc, DocNotFound
from limn.features.pins.claims.service import PinClaims
from limn.features.pins.editing.service import PinEditing
from limn.features.pins.lifecycle.service import PinLifecycle
from limn.features.pins.trash.service import PinTrash
from limn.locate import Picked, PickedRegion, PickRefusal
from limn.pins.model import Pin, PinNotFound, Record
from limn.revisions import DiffRefusal, PdfRefusal, StartRefusal, StatusRefusal
from limn.viewer.assemble import ServedViewer
from limn.web.parse import DocumentFacts, PickRequest, SourceRange

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

    def record_person(self, actor: Json, now: float | None = None, role: access.Role | None = None) -> bool:
        """Record a person in people.json (never an agent)."""
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

    def cur_pages(self, D: Document) -> Path:
        """Document D's page-image directory on screen (limn.build.cur_pages)."""
        ...

    # ---- reads

    def app_version(self) -> str:
        """The installed Limn version."""
        ...

    def people_roles(self) -> access.PeopleRoles:
        """{login: role} from people.json, or PeopleUnreadable while it cannot be used."""
        ...

    def known_people(self, pins: Sequence[Pin] | None = None) -> dict[str, Json]:
        """@-tag candidates {login: {login, name, pic?, last_seen?}}."""
        ...

    def people_payload(self) -> list[Json]:
        """GET /api/people: the @-tag candidates in their order, each with its people.json role."""
        ...

    def snapshot_pins(self) -> list[Pin]:
        """The pins, parsed, re-synced and saved under the pin lock."""
        ...

    def meta(self, D: Document, actor: Json, light: bool = False) -> Json:
        """GET /api/meta for document D."""
        ...

    def events_since(self, actor: Json, cursor: int | None) -> Json:
        """Browser notification material after cursor."""
        ...

    def revision_history(self, D: Document) -> Json:
        """GET /api/revisions."""
        ...

    def revision_diff(self, D: Document, commit: str, pin: int | None = None) -> Json | DiffRefusal:
        """GET /api/revision-diff for a commit id the parser checked."""
        ...

    def revision_status(self, D: Document, commit: str, pin: int | None = None) -> Json | StatusRefusal:
        """GET /api/revision-build."""
        ...

    def revision_pdf(self, D: Document, commit: str, pin: int | None = None) -> bytes | PdfRefusal:
        """GET /api/revision-pdf."""
        ...

    def outline_labels(self, D: Document) -> Json:
        """GET /api/outline-labels."""
        ...

    def build_state_snapshot(self, D: Document) -> Json:
        """GET /api/build for document D (limn.build.state_snapshot)."""
        ...

    def remote_base_for(self, host_raw: str) -> str:
        """The base URL for GET /pins.md's guidance."""
        ...

    def pins_md_text(self, pins: Sequence[Pin], base: str | None = None) -> str:
        """The pins.md text."""
        ...

    def pins_payload(self, pins: Sequence[Pin], allp: bool) -> list[Json]:
        """GET /api/pins: records plus computed fields."""
        ...

    def docs_payload(self) -> Json:
        """GET /api/docs."""
        ...

    def pin_payload(self, pid: int) -> Json | PinNotFound:
        """GET /api/pins/{id}: one pin as GET /api/pins?all=1 lists it, or PinNotFound."""
        ...

    def dropped_payload(self, now: float | None = None) -> list[Json]:
        """GET /api/pins/dropped: the Trash."""
        ...

    def snippet_api(self, rng: SourceRange, levels: bool) -> Json:
        """GET /api/snippet for a parsed range (with the range ladder when levels)."""
        ...

    def overlaps_api(self, rng: SourceRange) -> Json:
        """GET /api/overlaps for a parsed range."""
        ...

    def vendor_file(self, name: str) -> Path | None:
        """The bundled PDF.js file GET /vendor/pdfjs/<name> serves, or None."""
        ...

    def build_pdf(self, D: Document, name: str) -> Path | None:
        """The PDF of build `name` of document D, or None (limn.build.build_pdf)."""
        ...

    def public(self, r: Record) -> Json:
        """A pin record as the API returns it."""
        ...

    def pin_state(self, r: Record) -> str:
        """'open' | 'review' | 'done'."""
        ...

    # ---- changes

    def pick(self, D: Document, request: PickRequest) -> Picked | PickedRegion | PickRefusal:
        """POST /api/pick: a dragged region -> source lines."""
        ...

    def revision_start(self, D: Document, commit: str, pin: int | None = None) -> Json | StartRefusal:
        """POST /api/revision-build."""
        ...

    def rebuild(self, D: Document) -> FinishedBuild | BuildBusy | ViewOnlyNoRebuild:
        """POST /api/rebuild: build document D now, BuildBusy when it is already building, or ViewOnlyNoRebuild for a
        view-only document."""
        ...

    def rebuild_async(self, D: Document) -> BuildStarted | BuildBusy | ViewOnlyNoRebuild:
        """POST /api/rebuild?async=1: start document D's build in the background, BuildBusy when it is already
        building, or ViewOnlyNoRebuild for a view-only document."""
        ...
