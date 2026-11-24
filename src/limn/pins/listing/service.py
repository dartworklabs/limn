"""Run-bound reads behind the pin JSON routes."""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from limn.pins.listing import projection as view
from limn.pins.location.position import EstContext
from limn.pins.model import Pin, PinNotFound, Record
from limn.pins.needs import BoxesFor, FollowElement
from limn.pins.retention import expires_ts, unexpired, without_live_shadows
from limn.pins.store import PinReader

Json = dict[str, Any]


class Places(Protocol):
    """One computation's answers about where the pins' files are (the composition root's PinPlaces): each file is
    judged once for all of them, so one listing takes one value and drops it when it has answered."""

    def public(self, record: Record) -> Json:
        """One record with its current file path exposed to the API, and its suggestion's state when it has one."""
        ...

    def public_trashed(self, record: Record) -> Json:
        """One Trash entry's record with its current file path exposed to the API: no computed pin field."""
        ...

    def current_lines(self, record: Record) -> Sequence[str] | None:
        """The norm()-ed lines of the file a line pin's file is found at now, read once per file; None when it is not
        located or cannot be read."""
        ...

    def overlaps_by_id(self, pins: Sequence[Pin]) -> dict[int, list[Json]]:
        """Overlap relationships computed over all live pins."""
        ...

    def superseded_by_id(self, pins: Sequence[Pin]) -> dict[int, int]:
        """Which verdict pins a newer verdict pin supersedes, computed over all live pins."""
        ...


class ListingDeps(Protocol):
    """Only the run-specific facts that JSON pin views need."""

    def pin_reader(self) -> PinReader:
        """The run's pin store and lock."""
        ...

    def snapshot_pins(self) -> list[Pin]:
        """Live pins at their saved positions and revisions."""
        ...

    def places(self) -> Places:
        """A fresh view of where the pins' files are, for one listing."""
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

    def line_boxes(self, key: str) -> BoxesFor | None:
        """Where a line range of the document key names prints on the build it has on screen, or None."""
        ...


@dataclass(frozen=True)
class PinListing:
    """JSON pin and Trash reads bound to one server run."""

    deps: ListingDeps
    trash_days: int

    def pins_payload(self, pins: Sequence[Pin], allp: bool) -> list[Json]:
        """The list with overlap, estimation, figure element positions, line marks (only where a pin's anchor still
        stands on its lines) and verdict supersession computed over the full live set."""
        return self._views(pins, [pin.record for pin in pins], allp)

    def _views(self, pins: Sequence[Pin], rows: Sequence[Record], allp: bool) -> list[Json]:
        """The records of rows as GET /api/pins lists them (the open ones, every one when allp), in rows' order.

        pins is the full live set: a pin's overlaps and a verdict pin's supersession are relations to every other
        live pin, so both are computed over all of pins whatever rows asks for. rows is the part of that set to
        answer; everything a record carries beyond those two relations - how it is shown, its estimate, its
        element's position, where its lines print - is computed for the records of rows alone, and each of them
        reads only that record and its own document's facts. So a record's answer does not depend on which other
        records are in rows, and answering one pin costs one pin's work on top of the two relations. Where a file
        is is judged once per file for the whole call (one Places value)."""
        places = self.deps.places()
        return view.pins_payload(
            rows,
            allp,
            places.overlaps_by_id(pins),
            places.public,
            self.deps.pin_doc_key,
            self.deps._doc_est_context,
            time.time(),
            self.deps.element_follower,
            places.superseded_by_id(pins),
            self.deps.line_boxes,
            places.current_lines,
        )

    def list_payload(self, allp: bool, doc_key: str | None = None) -> list[Json]:
        """Read live pins and list them, the pins of one document alone when doc_key names it. The overlaps and
        supersessions are still those over every live pin; only the listed document's records are computed."""
        pins = self.deps.snapshot_pins()
        rows = [pin.record for pin in pins]
        if doc_key is not None:
            rows = [r for r in rows if self.deps.pin_doc_key(r) == doc_key]
        return self._views(pins, rows, allp)

    def pin_payload(self, pid: int) -> Json | PinNotFound:
        """One pin as the full list renders it, or its named miss: the first listed record whose shown id is pid.
        Only records stored under that id are computed; a shown id is the stored one or, for a number the wire
        cannot carry, null, so no other record could match."""
        pins = self.deps.snapshot_pins()
        rows = [pin.record for pin in pins if pin.record["id"] == pid]
        rec = next((r for r in self._views(pins, rows, True) if r["id"] == pid), None)
        return PinNotFound(pid) if rec is None else rec

    def dropped_payload(self, now: float | None = None) -> list[Json]:
        """Visible Trash entries from one locked read of live and dropped files."""
        store = self.deps.pin_reader()
        with store.lock:
            pins = store.read_pins()[0]
            entries = store.read_dropped()[0]
        visible = without_live_shadows(entries, pins)
        return view.dropped_payload(
            unexpired(visible, self.trash_days, time.time() if now is None else now),
            self.deps.places().public_trashed,
            lambda entry: expires_ts(entry, self.trash_days),
        )
