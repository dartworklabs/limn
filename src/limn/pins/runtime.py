"""Pin-owned storage, location and command composition for one run."""

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from limn.pins.application import people_facts
from limn.pins.claims.service import PinClaims
from limn.pins.context import Json, PinContext, who
from limn.pins.editing.http import EditingRequests
from limn.pins.editing.service import EditScope, PinEditing
from limn.pins.lifecycle.service import PinLifecycle
from limn.pins.listing.markdown import PinMarkdown
from limn.pins.listing.projection import pin_state, public_record as view_public_record
from limn.pins.listing.service import PinListing
from limn.pins.location.lookup import (
    Locator as locate_Locator,
    PinLocation,
    est_context,
    overlaps_by_id as locate_overlaps_by_id,
    overlaps_for_range as locate_overlaps_for_range,
    pin_file as locate_pin_file,
    pin_location as locate_pin_location,
    stamp_location as locate_stamp_location,
    sync_all as locate_sync_all,
)
from limn.pins.location.position import EstContext
from limn.pins.location.resolve import PickContext
from limn.pins.location.service import PinLocationService
from limn.pins.location.source import TokenCache
from limn.pins.mentions import note_tags as pin_note_tags
from limn.pins.model import EventType, Pin, Record, TrashedPin
from limn.pins.needs import BuildAnswers, FollowElement
from limn.pins.notice import PinNotice
from limn.pins.record import Broken, parse_record as record_parse_record, parse_trashed as record_parse_trashed
from limn.pins.store import PinFiles, PinStore, Row
from limn.pins.trash.service import PinTrash
from limn.runtime import documents
from limn.runtime.config import RunConfig
from limn.runtime.documents import DOC_KEY_RE, Doc
from limn.runtime.resources import RuntimeResources
from limn.security.access import Role
from limn.security.audit import AuditAction
from limn.security.people import is_actor as _is_actor
from limn.web.parse import DocumentFacts

THREAD_MAX = 200
TRASH_DAYS = 30


@dataclass
class PinCommands:
    """Bind pin transactions, source placement and HTTP adapters to explicit run ports."""

    settings: Callable[[], RunConfig]
    resources: Callable[[], RuntimeResources[object, object, object, object, object, TokenCache, object]]
    docs: list[Doc]
    build_view: BuildAnswers
    known_people: Callable[[Sequence[Json] | None], dict[str, Json]]
    notice_sink: Callable[[PinNotice], Json | None]
    emit_events: Callable[[list[Json | None]], None]
    recent_events: Callable[[], Sequence[Json]]
    role_of: Callable[[str], Role]
    http_audit: Callable[[AuditAction, Json, Json], bool]
    now_str: Callable[[], str]
    # The composition root's effect that brings a watched document's files up to date (pull, then import) by its key,
    # run before a close awaiting review is written; by default nothing.
    refresh_watched: Callable[[str], object] = lambda key: None
    pin_lifecycle: PinLifecycle = field(init=False)
    pin_claims: PinClaims = field(init=False)
    pin_trash: PinTrash = field(init=False)
    pin_editing: PinEditing = field(init=False)
    editing_requests: EditingRequests = field(init=False)
    pin_listing: PinListing = field(init=False)
    pin_markdown: PinMarkdown = field(init=False)
    location_service: PinLocationService = field(init=False)

    @property
    def C(self) -> RunConfig:
        """Read current settings when an operation begins."""
        return self.settings()

    @property
    def retention_days(self) -> int:
        """Return the pin-owned Trash retention used in permission refusal messages."""
        return TRASH_DAYS

    @property
    def RT(self) -> RuntimeResources[object, object, object, object, object, TokenCache, object]:
        """Read the run's shared transaction and cache resources."""
        return self.resources()

    def __post_init__(self) -> None:
        """Bind pin services after all deferred collaboration ports are supplied."""
        self.pin_lifecycle = PinLifecycle(self.pin_context)
        self.pin_claims = PinClaims(self.pin_context)
        self.pin_trash = PinTrash(self.pin_context)
        self.pin_editing = PinEditing(self.pin_context)
        self.editing_requests = EditingRequests(
            self.pin_editing,
            lambda: self.known_people(None),
            self.document_facts,
            EditScope(self.read_pins, lambda: self.docs, self.pin_doc_key),
            self.public,
        )
        self.pin_listing = PinListing(self, TRASH_DAYS)
        self.pin_markdown = PinMarkdown(self, self.known_pin_people, self.build_view)
        self.location_service = PinLocationService(
            lambda: PickContext(
                self.C.src,
                self.C.envs,
                self.C.state,
                self.RT.token_cache,
                self.overlaps_for_range,
                self.build_view,
            )
        )

    pin_state = staticmethod(pin_state)

    def element_follower(self, key: str) -> FollowElement | None:
        """Query current element positions without exposing a map to pin services."""
        doc = self.doc_by_key(key)
        return None if doc is None else self.build_view.elements(doc)

    def refresh_pins_md(self) -> None:
        """Refresh derived markdown after publication without resynchronizing pins."""
        with self.RT.pin_lock:
            self.render_pins_md(self.read_pins()[0])

    def watches_files(self, r: Record) -> bool:
        """Whether the document pin record r belongs to (pin_doc_key) has its files watched (Doc.watches_files: a figure
        document or a view-only PDF); False for a document this run does not serve."""
        doc = self.doc_by_key(self.pin_doc_key(r))
        return doc is not None and doc.watches_files

    def refresh_files(self, r: Record) -> None:
        """Bring the files of the document pin record r belongs to up to date (the refresh_watched port, by key)."""
        self.refresh_watched(self.pin_doc_key(r))

    def doc_by_key(self, key: object) -> Doc | None:
        """The document of this instance whose key is `key`, or None (limn.runtime.documents.doc_by_key)."""
        return documents.doc_by_key(self.docs, key)

    def pin_doc_key(self, r: Record) -> str:
        """The document key a pin belongs to; a legacy record without a doc field is the first document's
        (limn.runtime.documents.pin_doc_key)."""
        return documents.pin_doc_key(r, self.docs)

    def parse_record(self, r: object) -> Pin | Broken:
        """The store's parse of a pins.jsonl line (limn.pins.record.parse_record) with DOC_KEY_RE and
        limn.security.people.is_actor: the pin r holds, or Broken for a record the store may not trust."""
        return record_parse_record(r, DOC_KEY_RE.fullmatch, _is_actor)

    def parse_trashed(self, r: object) -> TrashedPin | Broken:
        """The store's parse of a Trash line (limn.pins.record.parse_trashed), with the same two rules as parse_record."""
        return record_parse_trashed(r, DOC_KEY_RE.fullmatch, _is_actor)

    def pin_location(self, r: Record, root: Path, state: Path) -> PinLocation | None:
        """Where line pin r's file is under the manuscript root on this machine now (limn.pins.location.lookup.pin_location, the tail
        guess limited to the folder of the pin's own document, never in the state folder), or None."""
        return locate_pin_location(r, root, state, self.doc_by_key(self.pin_doc_key(r)))

    def stamp_location(self, r: Row, root: Path, state: Path) -> PinLocation | None:
        """Records in r where its file is now (limn.pins.location.lookup.stamp_location, the pin's own document). Mutates r."""
        return locate_stamp_location(r, root, state, self.doc_by_key(self.pin_doc_key(r)))

    def pin_file(self, pin: Pin, root: Path, state: Path) -> PinLocation | None:
        """Where stored line pin pin's file is under the manuscript root on this machine now (limn.pins.location.lookup.pin_file, the tail
        guess limited to the folder of the pin's own document, never in the state folder), or None."""
        return locate_pin_file(pin, root, state, self.doc_by_key(self.pin_doc_key(pin.record)))

    def pin_locator(self) -> locate_Locator:
        """pin_file() bound to this instance's manuscript root and state folder, read now: where a stored pin's file is."""
        root, state = self.C.src, self.C.state
        return lambda pin: self.pin_file(pin, root, state)

    def record_locator(self) -> Callable[[Record], PinLocation | None]:
        """pin_location() bound to this instance's manuscript root and state folder, read now: where the file a record's
        location fields name is (the services locate a new pin's file, or an edit's, this way)."""
        root, state = self.C.src, self.C.state
        return lambda r: self.pin_location(r, root, state)

    def sync_all(self, pins: list[Pin]) -> bool:
        """The store's re-sync (PinStore.sync): stored pins' lines follow their anchors in the .tex files as this instance
        finds them now (limn.pins.location.lookup.sync_all)."""
        return locate_sync_all(pins, self.pin_locator())

    def pin_store(self) -> PinStore:
        """The pin store (limn.pins.store) over the current run arguments - where the composition root wires it.

        Made per call, like the build service's config(), so a test that replaces this application's C is seen at once; the lock is the one
        application-wide RT.pin_lock. The collaborators are looked up at call time: parse_record and parse_trashed read stored
        records into pins, sync_all re-matches their anchors, and pins_md_text renders the result."""
        return PinStore(
            PinFiles(self.C.state),
            self.RT.pin_lock,
            self.parse_record,
            self.parse_trashed,
            self.sync_all,
            self.pin_markdown.pins_md_text,
        )

    def read_pins(self) -> tuple[list[Pin], list[int]]:
        """The live pins, parsed, and pins.jsonl's broken line numbers, lock-free and not re-synced (PinStore.read_pins)."""
        return self.pin_store().read_pins()

    def read_dropped(self) -> tuple[list[TrashedPin], list[int]]:
        """The Trash entries, parsed, and the Trash file's broken line numbers, lock-free (PinStore.read_dropped)."""
        return self.pin_store().read_dropped()

    def write_pins(self, pins: list[Pin], bad: list[int] | None = None) -> None:
        """Rewrites pins.jsonl then pins.md; nothing if rendering fails (PinStore.write_pins). Callers hold RT.pin_lock."""
        self.pin_store().write_pins(pins, bad)

    def snapshot_pins(self) -> list[Pin]:
        """The live pins, re-synced and written back if that changed them (PinStore.snapshot)."""
        return self.pin_store().snapshot()

    def public(self, r: Record) -> Json:
        """A record as the API returns it (limn.pins.listing.projection.public_record), placed where pin_location() finds its file under
        the manuscript root now: `file` the absolute path on this machine, `rel_path` relative to the root (ADR-0006).
        Never changes r."""
        loc = self.pin_location(r, self.C.src, self.C.state)
        return view_public_record(r, None if loc is None else (str(loc.path), loc.rel))

    def _doc_est_context(self, key: str) -> EstContext | None:
        """What estimation reads of the builds of the document key names (limn.pins.location.lookup.est_context), or None when this
        instance no longer serves that document."""
        D = self.doc_by_key(key)
        return None if D is None else est_context(D, self.build_view)

    def overlaps_by_id(self, pins: Sequence[Pin]) -> dict[int, list[Json]]:
        """The relationship of every pair of open line pins on the same file, each counted where pin_location() places it
        now (limn.pins.location.lookup.overlaps_by_id), never stored."""
        return locate_overlaps_by_id(pins, self.pin_locator())

    def overlaps_for_range(self, file: str, lo: int, hi: int) -> list[Json]:
        """The overlap relationships between a not-yet-saved range of file and that file's open pins, as re-synced now
        (limn.pins.location.lookup.overlaps_for_range). Nothing is saved."""
        return locate_overlaps_for_range(file, lo, hi, self.snapshot_pins(), self.pin_locator())

    def init_seq(self) -> None:
        """If pins.seq is missing, fill it once from the max id across the current, archived, and dropped records (PinStore.init_seq)."""
        self.pin_store().init_seq()

    def _person_name(self, login: str) -> str:
        """A known person's display name, or the login itself for someone the viewer does not know."""
        return (self.known_people(None).get(login) or {}).get("name") or login

    def known_pin_people(self, pins: Sequence[Pin] | None = None) -> dict[str, Json]:
        """Return known people, optionally including actor facts from the supplied pins."""
        return self.known_people(
            None if pins is None else [actor for pin in pins for actor in people_facts(pin.record)]
        )

    def known_record_people(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Json]:
        """Return known people with detached record facts for pin-owned policies."""
        return self.known_people([actor for record in records for actor in people_facts(record)])

    def document_facts(self, D: Doc) -> DocumentFacts:
        """The parsing facts of document D (limn.runtime.documents.DocumentFacts) with this instance's manuscript root, state
        folder and dpi - made per request like pin_store(), so a test that replaces this application's C is seen at once."""
        return self.build_view.document_facts(D, self.C.src, self.C.state, self.C.dpi)

    def make_event(
        self,
        typ: EventType,
        r: Mapping[str, Any],
        actor: Mapping[str, Any],
        to: Iterable[str | None] | None,
        msg: Mapping[str, Any] | None = None,
        text: str | None = None,
    ) -> Json | None:
        """Extract pin/thread context here; the injected sink receives only completed notice facts."""
        return self.notice_sink(
            PinNotice(
                typ,
                r.get("id"),
                self.pin_doc_key(r),
                actor.get("login", "local"),
                actor.get("name", ""),
                tuple(to or ()),
                r.get("kind_req"),
                msg is not None,
                None if msg is None else msg.get("id"),
                text if text is not None else (msg or {}).get("text", ""),
            )
        )

    def pin_context(self) -> PinContext:
        """The pin services' view of this instance (limn.pins.context.PinContext), made per call like pin_store(), so a
        test that replaces this application's C, patches THREAD_MAX or TRASH_DAYS, or freezes now_str or time.time, is seen at once."""
        return PinContext(
            store=self.pin_store(),
            now=self.now_str,
            epoch=time.time,
            hm=lambda: datetime.now().astimezone().strftime("%H:%M"),
            make_event=self.make_event,
            emit_events=self.emit_events,
            who=who,
            audit=self.http_audit,
            known_people=self.known_pin_people,
            note_tags=lambda note, old, pins, hints, actor, pid: pin_note_tags(
                note,
                old,
                pins,
                hints,
                actor,
                pid,
                self.known_record_people,
                self.recent_events,
                time.time,
            ),
            role_of=self.role_of,
            person_name=self._person_name,
            locate=self.record_locator(),
            stamp=lambda r: self.stamp_location(r, self.C.src, self.C.state),
            thread_max=THREAD_MAX,
            trash_days=TRASH_DAYS,
            trash_checked=self.RT.trash_checked,
            builds=self.build_view,
            watches_files=self.watches_files,
            refresh_files=self.refresh_files,
        )

    def render_pins_md(self, pins: Sequence[Pin]) -> None:
        """Rewrites pins.md from pins alone (PinStore.render_md). Callers hold RT.pin_lock."""
        self.pin_store().render_md(pins)
