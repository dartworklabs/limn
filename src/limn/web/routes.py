"""The common contracts for registered document-scoped HTTP routes."""

from collections.abc import Callable
from typing import NamedTuple, TypeAlias

from limn.documents import Doc
from limn.web.parse import Json, Query
from limn.web.reply import Reply

GetRoute: TypeAlias = Callable[[str, Query, Doc], Reply | None]


class PostDocRoute(NamedTuple):
    """One POST path whose action needs the document selected by the common handler."""

    path: str
    action: Callable[[Query, Json, Doc], tuple[dict[str, object], int]]
