"""Document capability assembly."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from limn.documents import reads
from limn.documents.needs import BuildFacts, PinCounts
from limn.documents.service import DocumentViews
from limn.documents.verdicts import VerdictFiles
from limn.runtime.documents import Doc
from limn.web.routes import RouteBundle

Json = dict[str, Any]


@dataclass(frozen=True)
class DocumentsSubsystem:
    """The document read service and its route bindings. verdict_keys answers the verdict keys a document declares
    now (DocumentViews.verdict_keys), for the composition root to hand to pin creation."""

    views: DocumentViews
    routes: RouteBundle

    def verdict_keys(self, doc: Doc) -> tuple[str, ...]:
        """The verdict keys document doc declares now, in file order; () without a usable word file."""
        return self.views.verdict_keys(doc)


def assemble_documents(
    *,
    settings: Callable[[], reads.MetaSettings],
    docs: Sequence[Doc],
    sync_status: Callable[[], Mapping[str, Any]],
    pins: PinCounts,
    events_since: Callable[[Json, int | None], Json],
    now: Callable[[], float],
    builds: BuildFacts,
    warn: Callable[[str], None] | None = None,
) -> DocumentsSubsystem:
    """Assemble the document reads and their routes from what the composition root supplies: pins and builds are
    the pin and build suppliers' objects, matched structurally against limn.documents.needs, so this slice imports
    neither capability. The run gets its own reader of the verdict word files, which reports an unusable file through
    warn (the server log, stderr, when None). The HTTP adapters are imported only here, when a run is assembled."""
    from limn.documents.routes import get

    verdicts = VerdictFiles() if warn is None else VerdictFiles(warn)
    views = DocumentViews(settings, docs, sync_status, pins, events_since, now, builds, verdicts)
    return DocumentsSubsystem(views, RouteBundle(get=(lambda request: get(request, views),)))
