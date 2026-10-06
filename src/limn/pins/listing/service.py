"""Run-bound reads behind the pin JSON routes."""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from limn.pins.listing import projection as view
from limn.pins.location.position import EstContext
from limn.pins.model import Pin, PinNotFound, Record
from limn.pins.needs import FollowElement
from limn.pins.retention import expires_ts, unexpired, without_live_shadows
from limn.pins.store import PinStore

Json = dict[str, Any]


class ListingDeps(Protocol):
    """Only the run-specific facts that JSON pin views need."""

    def pin_store(self) -> PinStore:
        """The run's pin store and lock."""
        ...

    def snapshot_pins(self) -> list[Pin]:
        """Live pins after their usual resynchronization."""
        ...

    def public(self, record: Record) -> Json:
        """One record with its current file path exposed to the API."""
        ...

    def overlaps_by_id(self, pins: Sequence[Pin]) -> dict[int, list[Json]]:
        """Overlap relationships computed over all live pins."""
        ...

    def pin_doc_key(self, record: Record) -> str:
        """The document that owns one pin."""
        ...

    def _doc_est_context(self, key: str) -> EstContext | None:
        """Current build facts for one document."""
        ...

    def element_follower(self, key: str) -> FollowElement | None:
        """The loadable map of the build on screen of the figure document key names, or None."""
        ...


@dataclass(frozen=True)
class PinListing:
    """JSON pin and Trash reads bound to one server run."""

    deps: ListingDeps
    trash_days: int

    def pins_payload(self, pins: Sequence[Pin], allp: bool) -> list[Json]:
        """The list with overlap, estimation and figure element positions computed over the full live set."""
        rows = [pin.record for pin in pins]
        return view.pins_payload(
            rows,
            allp,
            self.deps.overlaps_by_id(pins),
            self.deps.public,
            self.deps.pin_doc_key,
            self.deps._doc_est_context,
            time.time(),
            self.deps.element_follower,
        )

    def list_payload(self, allp: bool, doc_key: str | None = None) -> list[Json]:
        """Read live pins, then scope the fully computed list to one document if requested."""
        rows = self.pins_payload(self.deps.snapshot_pins(), allp)
        return [r for r in rows if r["doc"] == doc_key] if doc_key is not None else rows

    def pin_payload(self, pid: int) -> Json | PinNotFound:
        """One pin as the full list renders it, or its named miss."""
        rec = next((r for r in self.pins_payload(self.deps.snapshot_pins(), True) if r["id"] == pid), None)
        return PinNotFound(pid) if rec is None else rec

    def dropped_payload(self, now: float | None = None) -> list[Json]:
        """Visible Trash entries from one locked read of live and dropped files."""
        store = self.deps.pin_store()
        with store.lock:
            pins = store.read_pins()[0]
            entries = store.read_dropped()[0]
        visible = without_live_shadows(entries, pins)
        return view.dropped_payload(
            unexpired(visible, self.trash_days, time.time() if now is None else now),
            self.deps.public,
            lambda entry: expires_ts(entry, self.trash_days),
        )
