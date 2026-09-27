"""The common callable contract for registered document-scoped GET routes."""

from collections.abc import Callable
from typing import TypeAlias

from limn.documents import Doc
from limn.web.parse import Query
from limn.web.reply import Reply

GetRoute: TypeAlias = Callable[[str, Query, Doc], Reply | None]
