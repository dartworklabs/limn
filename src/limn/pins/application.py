"""Public pin reads and capability-owned composition values."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

from limn.pins.model import Pin
from limn.pins.revision import RevisionPin, revision_pin as project_revision_pin

if TYPE_CHECKING:
    from limn.builds import BuildView
    from limn.pins.context import MakeEvent
    from limn.pins.editing.http import EditingRequests
    from limn.pins.location.source import TokenCache
    from limn.pins.runtime import PinCommands
    from limn.runtime.config import RunConfig
    from limn.runtime.documents import Doc
    from limn.runtime.resources import RuntimeResources
    from limn.security.access import Role
    from limn.security.audit import AuditAction
    from limn.web.routes import PinAction, RouteBundle

Json: TypeAlias = dict[str, Any]
Record: TypeAlias = Mapping[str, Any]


def _stored_path(value: Record | str, _document: object) -> Path:
    """Default locator for isolated projection tests; production supplies the current locator."""
    file = value.get("file") if isinstance(value, Mapping) else value
    return Path(file) if isinstance(file, str) else Path()


def people_facts(record: Record) -> Json:
    """Project attribution for collaboration, detaching every actor and discarding other fields."""

    def actor(value: object) -> Json:
        """Copy only the identity facts needed to discover and exclude people."""
        if not isinstance(value, Mapping):
            return {}
        return {key: deepcopy(value[key]) for key in ("login", "name", "pic") if key in value}

    facts: Json = {key: actor(value) for key, value in record.items() if key == "author" or key.endswith("_by")}
    facts["thread"] = [{"by": actor(post.get("by"))} for post in record.get("thread") or []]
    return facts


@dataclass(frozen=True)
class PinReadView:
    """Read-only pin projections for other capabilities."""

    _read: Callable[[], tuple[list[Pin], list[int]]]
    _snapshot: Callable[[], list[Pin]]
    _document_key: Callable[[Record], str]
    _locate: Callable[[Record | str, Any], Path | None] = _stored_path

    def counts_by_document(self, known: set[str]) -> tuple[dict[str, int], int]:
        """Return open counts by document and the count outside ``known``."""
        counts: dict[str, int] = {}
        for pin in self._read()[0]:
            if pin.state != "open":
                continue
            key = self._document_key(pin.record)
            counts[key] = counts.get(key, 0) + 1
        return counts, sum(count for key, count in counts.items() if key not in known)

    def state_counts(self) -> dict[str, int]:
        """Return viewer counts after the normal pin resynchronization."""
        states = [pin.state for pin in self._snapshot()]
        return {
            "n_open": states.count("open"),
            "n_done": states.count("done"),
            "n_review": states.count("review"),
        }

    def people_records(self, *, refresh: bool = False) -> tuple[Json, ...]:
        """Return only detached actor facts, never source locations or pin workflow data."""
        pins = self._snapshot() if refresh else self._read()[0]
        return tuple(people_facts(pin.record) for pin in pins)

    def revision_pin(
        self,
        pin_id: int,
        document_key: str,
        document: Any,
        relative: Callable[[Path], str | None],
        head: str,
        revisions: Sequence[Record],
    ) -> RevisionPin | None:
        """Return one document-bound projection with every stored path currently resolved."""
        record = next((pin.record for pin in self._read()[0] if pin.core.id == pin_id), None)
        if record is None or self._document_key(record) != document_key:
            return None

        def resolve(value: Record | str) -> str | None:
            """Locate a stored path now, then let the revision owner place it in its repository."""
            path = self._locate(value, document)
            return relative(path) if path is not None else None

        def resolve_pin() -> str | None:
            """Prefer the current location, retaining a repository-relative historical name after a rename."""
            current = resolve(record)
            stored = record.get("file")
            return current if current is not None else relative(Path(stored)) if isinstance(stored, str) else None

        projection = project_revision_pin(
            record,
            relative_path=resolve_pin(),
            head=head,
            revisions=revisions,
        )
        changes = tuple(
            change._replace(file=resolved)
            for change in projection.changes
            if (resolved := resolve(change.file)) is not None
        )
        return replace(projection, changes=changes)


@dataclass(frozen=True)
class PinStartup:
    """Pin startup operations owned by the capability."""

    initialize_sequence: Callable[[], None]
    render_markdown: Callable[[], None]


@dataclass(frozen=True)
class PinSubsystem:
    """The pin capability values used by composition."""

    view: PinReadView
    commands: PinCommands
    routes: RouteBundle
    startup: PinStartup


def assemble_pins(
    *,
    settings: Callable[[], RunConfig],
    resources: Callable[[], RuntimeResources[object, object, object, object, object, TokenCache]],
    docs: list[Doc],
    builds: BuildView,
    known_people: Callable[[Sequence[Json] | None], dict[str, Json]],
    make_event: MakeEvent,
    emit_events: Callable[[list[Json | None]], None],
    recent_events: Callable[[], Sequence[Json]],
    role_of: Callable[[str], Role],
    audit: Callable[[AuditAction, Json, Json], bool],
    now: Callable[[], str],
    remote_base_for: Callable[[str], str],
) -> PinSubsystem:
    """Assemble pin reads, transactions, routes and startup using explicit deferred ports."""
    from limn.pins.location.lookup import locate_file
    from limn.pins.runtime import PinCommands

    commands = PinCommands(
        settings, resources, docs, builds, known_people, make_event, emit_events, recent_events, role_of, audit, now
    )

    def locate(value: Record | str, document: Any) -> Path | None:
        """Resolve a pin or recorded change using the current manuscript paths."""
        config = settings()
        location = locate_file(
            value.get("file") if isinstance(value, Mapping) else value,
            value.get("file_rel") if isinstance(value, Mapping) else None,
            config.src,
            config.state,
            document,
        )
        return None if location is None else location.path

    def render() -> None:
        """Render current pins after acquiring this run's transaction lock."""
        with resources().pin_lock:
            commands.render_pins_md(commands.read_pins()[0])

    view = PinReadView(commands.read_pins, commands.snapshot_pins, commands.pin_doc_key, locate)
    startup = PinStartup(commands.init_seq, render)
    return PinSubsystem(view, commands, pin_route_bundle(commands, commands.editing_requests, remote_base_for), startup)


def pin_route_bundle(
    app: PinCommands,
    editing: EditingRequests,
    remote_base_for: Callable[[str], str],
) -> RouteBundle:
    """Bind all pin-owned reads and mutations without exposing their adapter modules."""
    from limn.pins.claims.routes import actions as claims_actions
    from limn.pins.editing.routes import POST_NEW_PIN, POST_PATH, actions as editing_actions, post as editing_post
    from limn.pins.lifecycle.routes import actions as lifecycle_actions
    from limn.pins.listing.routes import get as listing_get
    from limn.pins.location.routes import POST_PATH as PICK_PATH, get as location_get, post as location_post
    from limn.pins.trash.routes import actions as trash_actions, other_posts as trash_posts
    from limn.web.routes import PostDocRoute, RouteBundle

    actions: dict[str, PinAction] = {}
    for group in (lifecycle_actions(app), claims_actions(app), editing_actions(editing), trash_actions(app)):
        for name, action in group.items():
            if name in actions:
                raise ValueError("duplicate pin action route: %s" % name)
            actions[name] = action
    return RouteBundle(
        get=(
            lambda request: listing_get(request, app, app.pin_trash.maybe_purge_trash, remote_base_for),
            lambda request: location_get(request, app),
        ),
        post_documents=(
            PostDocRoute(PICK_PATH, lambda request: location_post(request, app)),
            PostDocRoute(POST_PATH, lambda request: editing_post(request, editing), new_pin=POST_NEW_PIN),
        ),
        pin_actions=actions,
        other_posts=trash_posts(app),
    )
