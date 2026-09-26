"""What the HTTP handler needs from the application: the services, settings and texts it calls, as one Protocol.

The handler never imports server.py. server.py is loaded more than once in one process (limn.server, __main__ when
run as a file, and each test module's copy loaded by path), and every copy has its own configuration C, documents and
locks; an import would reach a different copy than the one serving. Instead the composition root binds its handler
subclass to itself (server.Handler.app), and the handler calls through that at request time - so a name the tests
rebind on their server copy (mock.patch.object(ps, "build_async")) is the one the handler calls.

The members are server.py's services and wirings. The handler finds the request's document (request_doc) and passes
it to every member that acts on one - there is no "current document" - and it parses what a route takes from the
request (limn.web.parse) and passes the parsed values. Some members still read the run settings C themselves;
stage 6's second half (docs/handbook/code-style-roadmap.md) narrows them to explicit arguments.

The run settings, a document and a principal are server.py's own types (limn.config.Cfg, limn.documents.Doc,
limn.access.Principal), not narrower views of them: server.py's members take those types, and mypy checks server.py's
module against this Protocol (the `if TYPE_CHECKING:` assignment after server.Handler), so a missing or wrongly typed
binding is a type error. tests/test_web.py checks at run time that server.py provides every member.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from email.message import Message
from pathlib import Path
from typing import Any, Protocol, TypeAlias

from limn import access
from limn.config import Cfg
from limn.documents import Doc, DocNotFound
from limn.pins.edit import AddRequest, EditRefusal, EditRequest
from limn.pins.lifecycle import (
    AgentCannotConfirm,
    AlreadyClosed,
    AlreadyDone,
    AlreadyLive,
    ClaimClosedPin,
    ClaimedByOther,
    NotClaimed,
    NotInTrash,
    PinStillOpen,
    ThreadFull,
)
from limn.pins.model import DonePin, OpenPin, PinNotFound, Record, ReviewPin, TrashedPin
from limn.revisions import DiffRefusal, PdfRefusal, StartRefusal, StatusRefusal
from limn.web.errors import Messages
from limn.web.parse import CloseChange, DocumentFacts, PickRequest, SourceRange

Json: TypeAlias = dict[str, Any]  # a JSON object: request body, response payload, actor, stored pin record
Query: TypeAlias = dict[str, list[str]]  # parse_qs() of the request's query string


# The run settings the handler reads (C: origin_check, src, accent), a document a request acts on (key, is_pdf) and
# who a request is (actor, role, via) - server.py's own types, so its members type-check against App.
Config: TypeAlias = Cfg
Document: TypeAlias = Doc
Principal: TypeAlias = access.Principal


class App(Protocol):
    """server.py as the handler sees it. Each member keeps the name, arguments and contract it has there."""

    C: Config
    HTML: str  # the viewer page (rebuilt by main() with the label and accent)
    SW_JS: str  # the service worker served as /sw.js
    UI_EN: Messages  # the viewer's ko -> en message table, for the refusal page
    APP_NAME: str
    DEFAULT_ROLE: str  # the role of a person people.json gives none

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

    def record_person(self, actor: Json, now: float | None = None, role: str | None = None) -> bool:
        """Record a person in people.json (never an agent)."""
        ...

    def is_agent(self, actor: Json) -> bool:
        """An agent actor: headerless loopback or an API token."""
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

    def people_roles(self) -> dict[str, str]:
        """{login: role} from people.json."""
        ...

    def known_people(self, rows: list[Json] | None = None) -> dict[str, Json]:
        """@-tag candidates {login: {login, name, pic?, last_seen?}}."""
        ...

    def snapshot_pins(self) -> list[Json]:
        """The pins, re-synced and saved under the pin lock."""
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

    def maybe_purge_trash(self) -> int:
        """The hourly lazy expiry of the Trash."""
        ...

    def remote_base_for(self, host_raw: str) -> str:
        """The base URL for GET /pins.md's guidance."""
        ...

    def pins_md_text(self, rows: list[Json], base: str | None = None) -> str:
        """The pins.md text."""
        ...

    def pins_payload(self, rows: list[Json], allp: bool) -> list[Json]:
        """GET /api/pins: records plus computed fields."""
        ...

    def docs_payload(self) -> Json:
        """GET /api/docs."""
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

    def reply_pin(
        self,
        pid: int,
        text: str,
        actor: Json,
        hints: list[str] | None = None,
        reopen: bool | None = None,
        human: bool | None = None,
    ) -> OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound:
        """POST /api/pins/{id}/reply."""
        ...

    def confirm_pin(
        self, pid: int, actor: Json
    ) -> DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound:
        """POST /api/pins/{id}/confirm."""
        ...

    def drop_pin(self, pid: int, actor: Json) -> TrashedPin | PinNotFound:
        """POST /api/pins/{id}/drop."""
        ...

    def restore_pin(self, pid: int, actor: Json) -> OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive:
        """POST /api/pins/{id}/restore."""
        ...

    def purge_pin(self, pid: int, actor: Json) -> TrashedPin | NotInTrash:
        """POST /api/pins/{id}/purge."""
        ...

    def edit_pin(
        self, pid: int, request: EditRequest, actor: Json, region: bool = False
    ) -> OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound:
        """POST /api/pins/{id}/edit."""
        ...

    def claim_pin(
        self, pid: int, actor: Json, ttl_min: int, eta_min: int | None = None
    ) -> OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound:
        """POST /api/pins/{id}/claim."""
        ...

    def unclaim_pin(self, pid: int, actor: Json) -> OpenPin | ReviewPin | DonePin | NotClaimed | PinNotFound:
        """POST /api/pins/{id}/unclaim."""
        ...

    def set_done(
        self,
        pid: int,
        done: bool,
        actor: Json,
        reply: str | None = None,
        ref: str | None = None,
        review: bool | None = None,
        reason: str | None = None,
        hints: list[str] | None = None,
        changes: Sequence[CloseChange] | None = None,
    ) -> OpenPin | ReviewPin | DonePin | AlreadyClosed | PinNotFound:
        """POST /api/pins/{id}/close (done) and /reopen."""
        ...

    def add_pin(self, D: Document, request: AddRequest, actor: Json) -> OpenPin:
        """POST /api/pin."""
        ...

    def clear_pins(self, actor: Json | None = None) -> Json:
        """POST /api/clear."""
        ...

    def pick(self, D: Document, request: PickRequest) -> Json:
        """POST /api/pick: a dragged region -> source lines."""
        ...

    def revision_start(self, D: Document, commit: str, pin: int | None = None) -> Json | StartRefusal:
        """POST /api/revision-build."""
        ...

    def build_all(self, D: Document) -> Json:
        """POST /api/rebuild: build document D now."""
        ...

    def build_async(self, D: Document) -> Json:
        """POST /api/rebuild?async=1: start document D's build in the background."""
        ...
