"""Bind the current documents, build and pin facts to viewer document reads."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from limn.documents import reads
from limn.pins import Pin, Record
from limn.runtime.documents import Doc

Json = dict[str, Any]


@dataclass(frozen=True)
class DocumentViews:
    """The run's current document summaries and published outline."""

    settings: Callable[[], reads.MetaSettings]
    docs: Sequence[Doc]
    sync_status: Callable[[], Mapping[str, Any]]
    read_pins: Callable[[], tuple[list[Pin], list[int]]]
    snapshot_pins: Callable[[], list[Pin]]
    pin_doc_key: Callable[[Record], str]
    events_since: Callable[[Json, int | None], Json]
    now: Callable[[], float]

    def meta(self, doc: Doc, actor: Json, light: bool = False) -> Json:
        """The document's current viewer state; a full read also resynchronizes pin counts."""
        out = reads.meta(doc, actor, self.settings(), self.docs, self.sync_status(), self.now())
        if not light:
            out.update(reads.pin_counts([pin.state for pin in self.snapshot_pins()]))
        return out

    def docs_payload(self) -> Json:
        """The current document list and open-pin counts from a read without resynchronization."""
        pins, _ = self.read_pins()
        return reads.docs_payload(self.docs, [pin.record for pin in pins], self.pin_doc_key, self.settings().state)

    def outline(self, doc: Doc) -> Json:
        """Labels from the .aux published with the page images on screen."""
        return reads.outline_labels(doc)
