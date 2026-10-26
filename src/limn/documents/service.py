"""Bind the current documents, build and pin facts to viewer document reads."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from limn.documents import reads
from limn.documents.needs import BuildFacts, PinCounts
from limn.documents.verdicts import VerdictFiles, verdict_fields, verdict_keys
from limn.runtime.documents import Doc

Json = dict[str, Any]


@dataclass(frozen=True)
class DocumentViews:
    """The run's current document summaries and published outline. pins and builds are supplied by the composition
    root (limn.documents.needs); there is no default for either. verdicts is the run's reader of the documents' verdict
    word files (limn.documents.verdicts)."""

    settings: Callable[[], reads.MetaSettings]
    docs: Sequence[Doc]
    sync_status: Callable[[], Mapping[str, Any]]
    pins: PinCounts
    events_since: Callable[[Json, int | None], Json]
    now: Callable[[], float]
    builds: BuildFacts
    verdicts: VerdictFiles

    def meta(self, doc: Doc, actor: Json, light: bool = False) -> Json:
        """The document's current viewer state; a full read also resynchronizes pin counts and ends with the
        document's verdict words (verdict_fields). The light poll carries neither, nor do the `docs` copies of
        either body: a viewer reads the words when it opens or switches a document."""
        out = reads.meta(
            doc,
            actor,
            self.settings(),
            self.docs,
            self.sync_status(),
            self.now(),
            self.builds,
            self.pins.change_token(),
        )
        if not light:
            out.update(self.pins.state_counts())
            out.update(verdict_fields(doc, self.verdicts.read(doc)))
        return out

    def docs_payload(self) -> Json:
        """The current document list and open-pin counts from a read without resynchronization; each entry ends with
        its verdict words (verdict_fields) after n_open."""
        counts, other = self.pins.counts_by_document({doc.key for doc in self.docs})
        out = reads.docs_payload(self.docs, counts, other, self.settings().state, self.builds)
        for entry, doc in zip(out["docs"], self.docs, strict=True):
            entry.update(verdict_fields(doc, self.verdicts.read(doc)))
        return out

    def verdict_keys(self, doc: Doc) -> tuple[str, ...]:
        """The verdict keys document doc declares now, in file order; () when it has no usable word file. What pin
        creation checks a requested verdict against."""
        return verdict_keys(self.verdicts.read(doc))

    def outline(self, doc: Doc) -> Json:
        """Labels from the .aux published with the page images on screen."""
        return reads.outline_labels(doc, self.builds)
