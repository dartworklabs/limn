"""Run-bound reverse mapping for a dragged PDF region."""

from collections.abc import Callable
from dataclasses import dataclass

from limn.documents import Doc
from limn.features.pins.location.input import PickRequest
from limn.features.pins.location.resolve import PickContext, Picked, PickedRegion, PickRefusal, pick


@dataclass(frozen=True)
class PinSelection:
    """Resolve a selection using this server run's source tree, token cache and pin overlaps."""

    context: Callable[[], PickContext]

    def resolve(self, doc: Doc, request: PickRequest) -> Picked | PickedRegion | PickRefusal:
        """Return source lines, a view-only region or a named refusal."""
        return pick(doc, request, self.context())
