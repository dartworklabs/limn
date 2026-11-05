"""Document capability assembly."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from limn.documents import reads
from limn.documents.assets import ASSET_POLICY, ASSET_RESOURCE_POLICY, AssetTags
from limn.documents.needs import BuildFacts, PinCounts
from limn.documents.service import DocumentViews
from limn.documents.verdicts import VerdictFiles
from limn.runtime.documents import Doc
from limn.web.routes import PathPolicy, RouteBundle

Json = dict[str, Any]


@dataclass(frozen=True)
class DocumentsSubsystem:
    """The document read service, its route bindings and the run's content tags of the tree images it sent
    (asset_tags). verdict_keys answers the verdict keys a document declares now (DocumentViews.verdict_keys), for the
    composition root to hand to pin creation."""

    views: DocumentViews
    routes: RouteBundle
    asset_tags: AssetTags

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
    warn (the server log, stderr, when None), and its own content tags of the tree images it sends (AssetTags). The HTTP adapters are imported only here, when a run is assembled."""
    from limn.documents.routes import get

    verdicts = VerdictFiles() if warn is None else VerdictFiles(warn)
    views = DocumentViews(settings, docs, sync_status, pins, events_since, now, builds, verdicts)
    tags = AssetTags()  # the run's content tags of the tree images it sent: an unchanged one revalidates as a stat
    # Every answer of GET /api/asset - an image, a 304, each refusal - is sandboxed and same-origin (ADR-0030 D3): a
    # refusal's JSON body, opened on its own, is a document of that path too.
    policies = {"/api/asset": PathPolicy(ASSET_POLICY, ASSET_RESOURCE_POLICY)}
    routes = RouteBundle(get=(lambda request: get(request, views, tags),), policies=policies)
    return DocumentsSubsystem(views, routes, tags)
