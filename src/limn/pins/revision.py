"""Immutable pin facts exposed to the revisions capability."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple, TypeAlias, TypedDict, TypeGuard

from limn.pins.location.mapping import anchor_offset
from limn.platform.values import is_int

Record: TypeAlias = Mapping[str, Any]


class ChangeRecord(TypedDict):
    """One stored changed range attached to a closed pin."""

    file: str
    lo: int
    hi: int


class RevisionAnchor(NamedTuple):
    """The normalized anchor facts revision attribution needs."""

    head: str
    tail: str
    head_off: int
    tail_off: int


class RevisionChange(NamedTuple):
    """One recorded changed range before the current locator resolves its path."""

    file: str
    lo: int
    hi: int


@dataclass(frozen=True)
class RevisionPin:
    """The pin-owned facts revision attribution may consume."""

    id: int
    relative_path: str | None
    lo: int | None
    hi: int | None
    stale: bool
    anchor: RevisionAnchor | None
    changes: tuple[RevisionChange, ...]
    close_ref: str | None = None


def revision_pin(
    record: Record,
    *,
    relative_path: str | None,
) -> RevisionPin:
    """Project one accepted pin record for attribution against ``head``."""
    stored = record.get("anchor")
    raw_anchor: Record = stored if isinstance(stored, dict) else {}
    anchor_head = raw_anchor.get("head")
    anchor_tail = raw_anchor.get("tail")
    anchor = (
        RevisionAnchor(
            anchor_head,
            anchor_tail if isinstance(anchor_tail, str) else "",
            anchor_offset(raw_anchor.get("head_off")),
            anchor_offset(raw_anchor.get("tail_off")),
        )
        if isinstance(anchor_head, str) and anchor_head
        else None
    )
    lo, hi = record.get("lo"), record.get("hi")
    changes = (
        tuple(
            RevisionChange(change["file"], change["lo"], change["hi"])
            for change in record.get("changes") or []
            if _valid_change(change)
        )
        if record.get("changes_at") == record.get("done_at")
        else ()
    )
    return RevisionPin(
        id=int(record["id"]),
        relative_path=relative_path,
        lo=lo if is_int(lo) else None,
        hi=hi if is_int(hi) else None,
        stale=bool(record.get("stale")),
        anchor=anchor,
        changes=changes,
        close_ref=record.get("close_ref") if isinstance(record.get("close_ref"), str) else None,
    )


def _valid_change(value: object) -> TypeGuard[ChangeRecord]:
    """Recognize the stored fields required by revision attribution."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("file"), str)
        and is_int(value.get("lo"))
        and is_int(value.get("hi"))
    )


def valid_changes(value: object) -> bool:
    """Return whether a stored changes value is a list of valid ranges."""
    return isinstance(value, list) and all(_valid_change(change) for change in value)
