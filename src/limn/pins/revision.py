"""Immutable pin facts exposed to the revisions capability."""

import re
from collections.abc import Mapping, Sequence
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


_REF_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.ASCII)
_REF_PR_RE = re.compile(r"#(\d+)", re.ASCII)


def revision_pin(
    record: Record,
    *,
    relative_path: str | None,
    head: str,
    revisions: Sequence[Record],
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
        if record.get("changes_at") == record.get("done_at") and _ref_commit(record.get("close_ref"), revisions) == head
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
    )


def _ref_commit(ref: object, revisions: Sequence[Record]) -> str | None:
    """Return the recent commit named by a close reference."""
    text = ref if isinstance(ref, str) else ""
    for token in _REF_SHA_RE.findall(text):
        for revision in revisions:
            if str(revision["id"]).startswith(token):
                return str(revision["id"])
    for number in _REF_PR_RE.findall(text):
        pattern = re.compile(r"\(#%s\)|pull request #%s\b|#%s\b" % (number, number, number), re.ASCII)
        for revision in revisions:
            if pattern.search(revision.get("subject") or ""):
                return str(revision["id"])
    return None


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
