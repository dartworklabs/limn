"""What the HTTP handler needs from the application: the services, settings and texts it calls, as one Protocol.

The handler never imports server.py. server.py is loaded more than once in one process (limn.server, __main__ when
run as a file, and each test module's copy loaded by path), and every copy has its own configuration C, documents and
locks; an import would reach a different copy than the one serving. Instead the composition root binds its handler
subclass to itself (server.Handler.app), and the handler calls through that at request time - so a name the tests
rebind on their server copy (mock.patch.object(ps, "build_async")) is the one the handler calls.

The members are server.py's current shells, most still reading the global C and the thread's current document;
stage 6's second half (docs/handbook/code-style-roadmap.md) narrows them to explicit arguments. The handler parses what
a route takes from the request (limn.web.parse) and passes the parsed values. Values the handler only passes back (a
document) are typed by what the handler reads of them. tests/test_web.py checks that server.py provides every member.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from email.message import Message
from pathlib import Path
from typing import Any, Protocol, TypeAlias

from limn.pins.edit import AddRequest, EditRefusal, EditRequest
from limn.pins.lifecycle import (
    AgentCannotConfirm, AlreadyClosed, AlreadyDone, AlreadyLive, ClaimClosedPin, ClaimedByOther, NotClaimed,
    NotInTrash, PinStillOpen, ThreadFull,
)
from limn.pins.model import DonePin, OpenPin, PinNotFound, Record, ReviewPin, TrashedPin
from limn.web.errors import Messages
from limn.web.parse import CloseChange, DocumentFacts, PickRequest, SourceRange

Json: TypeAlias = dict[str, Any]          # a JSON object: request body, response payload, actor, stored pin record
Query: TypeAlias = dict[str, list[str]]   # parse_qs() of the request's query string


class Config(Protocol):
    """The run settings the handler reads (server.py's C)."""

    @property
    def origin_check(self) -> bool:
        """False under --no-origin-check: Host/Origin are not checked."""
        ...

    @property
    def src(self) -> Path:
        """The manuscript folder (--manuscript), the root close `changes` must stay under."""
        ...

    @property
    def accent(self) -> str:
        """The instance accent (#rrggbb) the PNG favicons are drawn in."""
        ...


class Document(Protocol):
    """A document a request acts on (server.py's Doc), as far as the handler reads it."""

    @property
    def key(self) -> str:
        """The document key (?doc=)."""
        ...

    @property
    def is_pdf(self) -> bool:
        """True for a view-only PDF document, which is never rebuilt."""
        ...


class Principal(Protocol):
    """Who a request is (server.py's Principal from identify())."""

    @property
    def actor(self) -> Json:
        """{login, name, pic?} - what pins record."""
        ...

    @property
    def role(self) -> str:
        """owner | editor | viewer | agent."""
        ...

    @property
    def via(self) -> str:
        """header | token | loopback-agent | local-owner."""
        ...


class App(Protocol):
    """server.py as the handler sees it. Each member keeps the name, arguments and contract it has there."""

    C: Config
    HTML: str                         # the viewer page (rebuilt by main() with the label and accent)
    SW_JS: str                        # the service worker served as /sw.js
    UI_EN: Messages                   # the viewer's ko -> en message table, for the refusal page
    APP_NAME: str
    DEFAULT_ROLE: str                 # the role of a person people.json gives none
    CLEAR_CONFIRM: str                # the phrase POST /api/clear must carry
    PAGE_FILE_RE: re.Pattern[str]     # a page image name GET /pages/<name> serves
    VENDOR_MIME: Mapping[str, str]    # suffix -> Content-Type of a file vendor_file() returns
    ScopeRejected: type[Exception]    # the pin-scoping refusal; instances carry .reason (limn.web.errors.ScopeRefusal)

    # ---- request guard: Host/Origin, identity, admission, roles (the security boundary stays in server.py)

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

    def request_doc(self, key: str | None, file_hint: object = None) -> Document:
        """The document key names (parsed by limn.web.parse.parse_doc_key), or - with none - the one holding
        file_hint, else the first; raises HTTPError 404 for an unknown key."""
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

    def using_doc(self, d: Document) -> AbstractContextManager[object]:
        """Make d the thread's current document for the block."""
        ...

    def cur_doc(self) -> Document:
        """The thread's current document."""
        ...

    def cur_pages(self) -> Path:
        """The current document's page-image directory."""
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

    def meta(self, actor: Json, light: bool = False) -> Json:
        """GET /api/meta for the current document."""
        ...

    def events_since(self, actor: Json, cursor: int | None) -> Json:
        """Browser notification material after cursor."""
        ...

    def revision_history(self, D: Document) -> Json:
        """GET /api/revisions."""
        ...

    def revision_diff(self, D: Document, commit: str, pin: int | None = None) -> Json:
        """GET /api/revision-diff; raises HTTPError or ScopeRejected."""
        ...

    def revision_status(self, D: Document, commit: str, pin: int | None = None) -> Json:
        """GET /api/revision-build."""
        ...

    def revision_pdf(self, D: Document, commit: str, pin: int | None = None) -> bytes:
        """GET /api/revision-pdf; raises HTTPError when there is none."""
        ...

    def outline_labels(self, D: Document) -> Json:
        """GET /api/outline-labels."""
        ...

    def build_state_snapshot(self) -> Json:
        """GET /api/build for the current document."""
        ...

    def diet_log(self, payload: Json, full: bool) -> Json:
        """A build payload with its log trimmed unless full."""
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

    def build_pdf(self, name: str) -> Path | None:
        """The PDF of build `name` of the current document, or None."""
        ...

    def public(self, r: Record) -> Json:
        """A pin record as the API returns it."""
        ...

    def pin_state(self, r: Record) -> str:
        """'open' | 'review' | 'done'."""
        ...

    # ---- changes

    def reply_pin(self, pid: int, text: str, actor: Json, hints: list[str] | None = None, reopen: bool | None = None,
                  human: bool | None = None) -> OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound:
        """POST /api/pins/{id}/reply."""
        ...

    def confirm_pin(self, pid: int, actor: Json) -> DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound:
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

    def edit_pin(self, pid: int, request: EditRequest, actor: Json,
                 region: bool = False) -> OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound:
        """POST /api/pins/{id}/edit."""
        ...

    def claim_pin(self, pid: int, actor: Json, ttl_min: int,
                  eta_min: int | None = None) -> OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound:
        """POST /api/pins/{id}/claim."""
        ...

    def unclaim_pin(self, pid: int, actor: Json) -> OpenPin | ReviewPin | DonePin | NotClaimed | PinNotFound:
        """POST /api/pins/{id}/unclaim."""
        ...

    def set_done(self, pid: int, done: bool, actor: Json, reply: str | None = None, ref: str | None = None,
                 review: bool | None = None, reason: str | None = None, hints: list[str] | None = None,
                 changes: Sequence[CloseChange] | None = None) -> OpenPin | ReviewPin | DonePin | AlreadyClosed | PinNotFound:
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

    def revision_start(self, D: Document, commit: object, pin: int | None = None) -> Json:
        """POST /api/revision-build."""
        ...

    def build_all(self) -> Json:
        """POST /api/rebuild: build the current document now."""
        ...

    def build_async(self) -> Json:
        """POST /api/rebuild?async=1: start the build in the background."""
        ...
