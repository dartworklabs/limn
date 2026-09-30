"""Common HTTP boundary helpers for parsed refusals and document lookup."""

from collections.abc import Callable
from typing import TypeAlias, TypeVar

from limn.runtime.documents import DocNotFound
from limn.security.values import CONFIRM_BY_HUMAN as CONFIRM_BY_HUMAN
from limn.web.errors import HTTPError, InputRejected

Text: TypeAlias = Callable[[object], str]
T = TypeVar("T")


def accepted(value: T | InputRejected) -> T:
    """A request parser's value (limn.web.parse), or the 400 of its refusal: the parser's message, word for word, and
    its reason."""
    if isinstance(value, InputRejected):
        raise HTTPError(400, value.message, reason=value.reason)
    return value


def found_doc(found: T | DocNotFound, text: Text) -> T:
    """The document a request names, or 404 unknown_doc for a key this instance does not serve: the key (through text,
    cut to 40 characters) and every key it does serve (docs)."""
    if isinstance(found, DocNotFound):
        raise HTTPError(404, "없는 문서입니다: %s" % text(found.key)[:40], docs=list(found.known), reason="unknown_doc")
    return found
