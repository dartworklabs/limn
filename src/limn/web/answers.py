"""Common HTTP boundary helpers for parsed refusals and document lookup."""

from collections.abc import Callable
from typing import TypeAlias, TypeVar

from limn.documents import DocNotFound
from limn.pins.model import Record
from limn.web.errors import HTTPError, InputRejected

Show: TypeAlias = Callable[[Record], object]
StateOf: TypeAlias = Callable[[Record], str]
Text: TypeAlias = Callable[[object], str]
T = TypeVar("T")

CONFIRM_BY_HUMAN = "확인은 사람이 합니다 — 테일넷 신원으로 접속해 뷰어에서 [확인]을 누르세요."


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
