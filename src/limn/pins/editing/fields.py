"""Validate note, kind, scope, assignee, suggested-edit and verdict fields of pin creation and editing.

These pure parsers return the validated value or the exact request rejection. Both
the editing body and editing location parser use them without importing each other.
"""

from collections.abc import Collection

from limn.pins.editing.rules import AskedVerdict, NonStringVerdict
from limn.pins.editing.values import ASSIGNEE_AGENT, LOCAL_LOGIN, NOTE_MAX, SCOPES, Scope, is_scope
from limn.pins.model import KIND_REQS, KindReq, is_kind_req
from limn.pins.suggestion import Suggestion, without_cr
from limn.web.errors import InputRejected

# The one refusal of a suggestion's shape (400 bad_suggest). The limits, the pin and the file are decided after it, by
# the editing rules (limn.pins.editing.rules.decide_new_suggestion, decide_edit).
SUGGEST_REFUSAL = (
    "suggest 는 문자열 base·text 두 칸만 가진 객체여야 합니다"
    "(base = 지금 그 줄 범위의 글, text = 그 줄들을 바꿀 글, 줄은 \\n 으로 잇는다)."
)


def parse_note(v: object) -> str | InputRejected:
    """A pin's note: a string of at most NOTE_MAX characters; absent or null is the empty note."""
    if v is None:
        return ""
    if not isinstance(v, str):
        return InputRejected("note 는 문자열이어야 합니다.", "bad_note")
    if len(v) > NOTE_MAX:
        return InputRejected("메모가 너무 깁니다(%d자 이하)." % NOTE_MAX, "note_too_long")
    return v


def parse_kind_req(v: object) -> KindReq | None | InputRejected:
    """Pin kind - 'fix' (fix request) | 'question'. None if absent (= fix, same as a legacy pin)."""
    if v is None:
        return None
    if not isinstance(v, str) or not is_kind_req(v):
        return InputRejected("kind_req 는 %s 중 하나입니다." % "|".join(KIND_REQS), "bad_kind_req")
    return v


def parse_scope(v: object) -> Scope | None | InputRejected:
    """A line pin's range-ladder rung (SCOPES), or None when absent."""
    if v is None:
        return None
    if not is_scope(v):
        return InputRejected("scope 는 %s 중 하나입니다." % "|".join(SCOPES), "bad_scope")
    return v


def parse_assignee(v: object, known: Collection[str]) -> str | None | InputRejected:
    """Assignee - "agent" or the login of a person this viewer knows. None if absent (not sent = unchanged).

    known is the logins of known_people(), which the caller reads only when the body names an assignee
    (the editing request collaborators)."""
    if v is None:
        return None
    if v == ASSIGNEE_AGENT:
        return ASSIGNEE_AGENT
    if not isinstance(v, str) or not v or v == LOCAL_LOGIN:
        return InputRejected("assignee 는 'agent' 또는 사람의 로그인(문자열)입니다.", "bad_assignee")
    if v not in known:
        return InputRejected(
            "담당(assignee) '%s' 은(는) 이 뷰어가 아는 사람이 아닙니다 — 'agent' 또는 뷰어를 연 적 있는 테일넷 사람의 로그인을 쓰세요."
            % v,
            "unknown_assignee",
        )
    return v


def parse_suggest(v: object) -> Suggestion | InputRejected:
    """A suggested edit as a request sends it: an object with exactly the string fields base and text -> a Suggestion
    with every carriage return removed from both (line terminators are compared without it); anything else - not an
    object, a missing or extra key, a value that is not a string - is 400 bad_suggest. The caller decides what an
    absent or null value means. Duplicate keys never get here: the request parser refuses them (400 bad_json)."""
    if not isinstance(v, dict) or set(v) != {"base", "text"}:
        return InputRejected(SUGGEST_REFUSAL, "bad_suggest")
    base, text = v["base"], v["text"]
    if not (isinstance(base, str) and isinstance(text, str)):
        return InputRejected(SUGGEST_REFUSAL, "bad_suggest")
    return Suggestion(without_cr(base), without_cr(text))


def parse_verdict(v: object) -> AskedVerdict | None:
    """A new pin's verdict as its body sent it: None when absent or null (no verdict pin), the string as sent, or
    NonStringVerdict for any other value. Nothing is refused here: whether the principal may make a verdict pin and
    whether the document declares that word are decided inside the store transaction, in the contract's order
    (limn.pins.editing.rules.decide_new_verdict), where a non-string is verdict_unknown."""
    if v is None:
        return None
    return v if isinstance(v, str) else NonStringVerdict()
