"""Validate note, kind, scope, and assignee fields of pin creation and editing.

These pure parsers return the validated value or the exact request rejection. Both
the editing body and editing location parser use them without importing each other.
"""

from collections.abc import Collection

from limn.pins.edit import ASSIGNEE_AGENT, LOCAL_LOGIN, NOTE_MAX, SCOPES, Scope, is_scope
from limn.pins.model import KIND_REQS, KindReq, is_kind_req
from limn.web.errors import InputRejected


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
