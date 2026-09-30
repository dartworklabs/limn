"""Bind the current documents, build and pin facts to viewer document reads."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from limn.builds import BuildView
from limn.documents import reads
from limn.pins import PinReadView
from limn.runtime.documents import Doc

Json = dict[str, Any]


@dataclass(frozen=True)
class DocumentViews:
    """The run's current document summaries and published outline."""

    settings: Callable[[], reads.MetaSettings]
    docs: Sequence[Doc]
    sync_status: Callable[[], Mapping[str, Any]]
    pins: PinReadView
    events_since: Callable[[Json, int | None], Json]
    now: Callable[[], float]
    builds: BuildView = BuildView()

    def meta(self, doc: Doc, actor: Json, light: bool = False) -> Json:
        """The document's current viewer state; a full read also resynchronizes pin counts."""
        out = reads.meta(doc, actor, self.settings(), self.docs, self.sync_status(), self.now(), self.builds)
        if not light:
            out.update(self.pins.state_counts())
        return out

    def docs_payload(self) -> Json:
        """The current document list and open-pin counts from a read without resynchronization."""
        counts, other = self.pins.counts_by_document({doc.key for doc in self.docs})
        return reads.docs_payload(self.docs, counts, other, self.settings().state, self.builds)

    def outline(self, doc: Doc) -> Json:
        """Labels from the .aux published with the page images on screen."""
        return reads.outline_labels(doc, self.builds)
