"""Document capability assembly."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from limn.builds import BuildView
from limn.documents import reads
from limn.documents.service import DocumentViews
from limn.pins import PinReadView
from limn.runtime.documents import Doc
from limn.web.routes import RouteBundle

Json = dict[str, Any]


@dataclass(frozen=True)
class DocumentsSubsystem:
    """The document read service and its route bindings."""

    views: DocumentViews
    routes: RouteBundle


def assemble_documents(
    *,
    settings: Callable[[], reads.MetaSettings],
    docs: Sequence[Doc],
    sync_status: Callable[[], Mapping[str, Any]],
    pins: PinReadView,
    events_since: Callable[[Json, int | None], Json],
    now: Callable[[], float],
    builds: BuildView,
) -> DocumentsSubsystem:
    """Assemble document views without importing HTTP adapters."""
    from limn.documents.routes import get

    views = DocumentViews(settings, docs, sync_status, pins, events_since, now, builds)
    return DocumentsSubsystem(views, RouteBundle(get=(lambda request: get(request, views),)))
