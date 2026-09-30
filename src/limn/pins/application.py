"""Public pin reads and capability-owned composition values."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TypeAlias

from limn.pins.model import Pin
from limn.pins.revision import RevisionPin, revision_pin as project_revision_pin

Json: TypeAlias = dict[str, Any]
Record: TypeAlias = Mapping[str, Any]


def _stored_path(value: Record | str, _document: object) -> Path:
    """Default locator for isolated projection tests; production supplies the current locator."""
    file = value.get("file") if isinstance(value, Mapping) else value
    return Path(file) if isinstance(file, str) else Path()


@dataclass(frozen=True)
class PinReadView:
    """Read-only pin projections for other capabilities."""

    read: Callable[[], tuple[list[Pin], list[int]]]
    snapshot: Callable[[], list[Pin]]
    document_key: Callable[[Record], str]
    locate: Callable[[Record | str, Any], Path | None] = _stored_path

    def _records(self, refresh: bool) -> tuple[Json, ...]:
        """Return detached records, optionally after the normal resynchronization."""
        pins = self.snapshot() if refresh else self.read()[0]
        return tuple(dict(pin.record) for pin in pins)

    def counts_by_document(self, known: set[str]) -> tuple[dict[str, int], int]:
        """Return open counts by document and the count outside ``known``."""
        counts: dict[str, int] = {}
        for pin in self.read()[0]:
            if pin.state != "open":
                continue
            key = self.document_key(pin.record)
            counts[key] = counts.get(key, 0) + 1
        return counts, sum(count for key, count in counts.items() if key not in known)

    def state_counts(self) -> dict[str, int]:
        """Return viewer counts after the normal pin resynchronization."""
        states = [pin.state for pin in self.snapshot()]
        return {
            "n_open": states.count("open"),
            "n_done": states.count("done"),
            "n_review": states.count("review"),
        }

    def people_records(self, *, refresh: bool = False) -> tuple[Json, ...]:
        """Return detached records from which collaboration derives people facts."""
        return self._records(refresh)

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
        record = next((pin.record for pin in self.read()[0] if pin.core.id == pin_id), None)
        if record is None or self.document_key(record) != document_key:
            return None

        def resolve(value: Record | str) -> str | None:
            """Locate a stored path now, then let the revision owner place it in its repository."""
            path = self.locate(value, document)
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
class PinCommands:
    """Pin mutation services kept behind one composition value."""

    lifecycle: object
    claims: object
    trash: object
    editing: object


@dataclass(frozen=True)
class PinRoutes:
    """Pin HTTP bindings completed by the route assembly step."""

    get: tuple[Callable[..., object], ...] = ()
    document_posts: tuple[object, ...] = ()
    actions: Mapping[str, Callable[..., object]] | None = None
    other_posts: Mapping[str, Callable[..., object]] | None = None


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
    routes: PinRoutes
    startup: PinStartup


def assemble_pins(
    view: PinReadView,
    commands: PinCommands,
    startup: PinStartup,
    routes: PinRoutes | None = None,
) -> PinSubsystem:
    """Assemble the pin capability from its explicit read, command, and startup ports."""
    return PinSubsystem(view, commands, routes or PinRoutes(), startup)
