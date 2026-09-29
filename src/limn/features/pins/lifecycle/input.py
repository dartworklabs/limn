"""Input for closing and reopening a pin, including the close change path boundary."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

from limn.features.pins.lifecycle.rules import CloseRequest
from limn.files import tree_part
from limn.pins.shapes import is_int
from limn.web.errors import InputRejected
from limn.web.parse import parse_mention_hints

Json = Mapping[str, Any]

CLOSE_REPLY_MAX = 500  # what-was-fixed note left when closing (docs/handbook/api.md §닫을 때 사유 남기기)
CLOSE_REF_MAX = 80  # reference (e.g. PR number) - matching values let the UI group closed pins together
# v0.3: ranges in one close body's optional changes (the new-side lines the agent changed for the pin)
CLOSE_CHANGES_MAX = 50
CHANGE_LINE_MAX = 1_000_000  # a line number past this is not a manuscript line
THREAD_TEXT_MAX = 1000  # one reply or reopen reason


def parse_thread_text(v: object, what: str = "text", required: bool = True) -> str | None | InputRejected:
    """One reply or reopen reason. Like a note, only string type and length are checked (the screen renders via esc()).
    Newlines are normalized to \\n and control characters (other than newline/tab) are stripped - so the pins.md table
    and notification bodies don't break. Empty after trimming whitespace is refused when required, else None; so is
    an absent value. `what` names the field in the refusal."""
    if v is None:
        if required:
            return InputRejected("%s 가 필요합니다." % what, "text_required")
        return None
    if not isinstance(v, str):
        return InputRejected("%s 는 문자열이어야 합니다." % what, "bad_text")
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    v = "".join(ch for ch in v if ch in "\n\t" or not (ord(ch) < 32 or 127 <= ord(ch) < 160)).strip()
    if len(v) > THREAD_TEXT_MAX:
        return InputRejected("%s 가 너무 깁니다(%d자 이하)." % (what, THREAD_TEXT_MAX), "text_too_long")
    if not v:
        if required:
            return InputRejected("%s 가 비어 있습니다." % what, "text_empty")
        return None
    return v


def parse_review_flag(d: Json) -> bool | None | InputRejected:
    """The close body's optional review - true means awaiting review, false means done right away. None if absent
    (left to the closer to decide)."""
    v = d.get("review")
    if v is not None and not isinstance(v, bool):
        return InputRejected("review 는 true/false 입니다.", "bad_review")
    return v


class CloseBody(NamedTuple):
    """A close's optional reply and ref, each None when absent or blank."""

    reply: str | None
    ref: str | None


def parse_close_body(d: Json) -> CloseBody | InputRejected:
    """The close body's optional {"reply", "ref"} fields. Absent or an empty (whitespace-only) string both become
    None - preserving the existing "curl POST with no body" behavior (docs/handbook/api.md §닫을 때 사유 남기기)."""
    reply = d.get("reply")
    if reply is not None:
        if not isinstance(reply, str):
            return InputRejected("reply 는 문자열이어야 합니다.", "bad_reply")
        if len(reply) > CLOSE_REPLY_MAX:
            return InputRejected("reply 가 너무 깁니다(%d자 이하)." % CLOSE_REPLY_MAX, "reply_too_long")
        if not reply.strip():
            reply = None
    ref = d.get("ref")
    if ref is not None:
        if not isinstance(ref, str):
            return InputRejected("ref 는 문자열이어야 합니다.", "bad_ref")
        if len(ref) > CLOSE_REF_MAX:
            return InputRejected("ref 가 너무 깁니다(%d자 이하)." % CLOSE_REF_MAX, "ref_too_long")
        if not ref.strip():
            ref = None
    return CloseBody(reply, ref)


class CloseChange(NamedTuple):
    """One validated range of a close body's `changes` (parse_close_changes), immutable: an absolute, resolved path
    inside the manuscript folder, and the new-side lines 1 ≤ lo ≤ hi ≤ CHANGE_LINE_MAX the agent changed for the pin."""

    file: str
    lo: int
    hi: int

    def record(self) -> dict[str, Any]:
        """The JSON shape stored on the pin record (api.md §핀 레코드 스키마): {file, lo, hi}."""
        return {"file": self.file, "lo": self.lo, "hi": self.hi}


def parse_close_changes(v: object, root: Path, state: Path) -> tuple[CloseChange, ...] | None | InputRejected:
    """The close body's optional `changes`: [{file, lo, hi}] - the new-side lines the agent changed for this pin. file is
    a path in the tree root (the manuscript folder; limn.files.tree_part, so never under a dot-named part such as .env
    nor in the state folder `state`),
    absolute or relative to it (the pins.md location column), and need not exist; the result carries it resolved and
    absolute, like a pin's file. Absent or [] -> None (the pre-0.3 close). A refusal names the
    offending item - the messages are part of the agent contract."""
    if v is None:
        return None
    if not isinstance(v, list):
        return InputRejected('changes 는 [{"file", "lo", "hi"}] 목록이어야 합니다.', "bad_changes")
    if len(v) > CLOSE_CHANGES_MAX:
        return InputRejected("changes 는 %d개 이하여야 합니다." % CLOSE_CHANGES_MAX, "too_many_changes")
    out, base = [], root.resolve()
    for i, c in enumerate(v):
        what = "changes[%d]" % i
        if not isinstance(c, dict) or set(c) != {"file", "lo", "hi"}:
            return InputRejected("%s 는 file·lo·hi 세 필드만 가진 객체여야 합니다." % what, "bad_changes")
        f, lo, hi = c["file"], c["lo"], c["hi"]
        if not isinstance(f, str) or not f.strip() or len(f) > 1024 or "\x00" in f:
            return InputRejected("%s.file 은 비어 있지 않은 경로 문자열이어야 합니다." % what, "bad_changes")
        if not (is_int(lo) and is_int(hi) and 1 <= lo <= hi <= CHANGE_LINE_MAX):
            return InputRejected(
                "%s 의 lo·hi 는 1 ≤ lo ≤ hi ≤ %d 인 정수여야 합니다." % (what, CHANGE_LINE_MAX), "bad_changes"
            )
        rel = tree_part(Path(f) if os.path.isabs(f) else base / f, base, state)
        if rel is None:
            return InputRejected(
                "%s.file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다." % what, "change_outside_manuscript"
            )
        out.append(CloseChange(str(base / rel), lo, hi))
    return tuple(out) or None


def parse_close(d: Json, root: Path, state: Path) -> CloseRequest | InputRejected:
    """A POST /api/pins/{id}/close body, in the order the server has always checked it: reply and ref
    (parse_close_body), changes against the manuscript tree root and outside the state folder (parse_close_changes),
    review (parse_review_flag),
    then mentions. A close tags nobody, so its `mentions` is dropped - but a malformed one has always been refused with
    400 bad_mentions, and still is. Any other field is ignored. The result carries each change in its stored form."""
    body = parse_close_body(d)
    if isinstance(body, InputRejected):
        return body
    changes = parse_close_changes(d.get("changes"), root, state)
    if isinstance(changes, InputRejected):
        return changes
    review = parse_review_flag(d)
    if isinstance(review, InputRejected):
        return review
    hints = parse_mention_hints(d.get("mentions"))
    if isinstance(hints, InputRejected):
        return hints
    return CloseRequest(body.reply, body.ref, tuple(c.record() for c in changes or ()), review)


class ReopenBody(NamedTuple):
    """A reopen's optional reason (None when absent or blank) and the viewer's @-tag hints for it."""

    reason: str | None
    hints: list[str]


def parse_reopen(d: Json) -> ReopenBody | InputRejected:
    """A POST /api/pins/{id}/reopen body, in the order the server has always checked it: the optional reason
    (parse_thread_text, recorded in the thread when the pin was closed), then mentions. Any other field - a close's
    reply or review sent to reopen, say - is ignored."""
    reason = parse_thread_text(d.get("reason"), "reason", required=False)
    if isinstance(reason, InputRejected):
        return reason
    hints = parse_mention_hints(d.get("mentions"))
    if isinstance(hints, InputRejected):
        return hints
    return ReopenBody(reason, hints)


def parse_reply_text(v: object) -> str | InputRejected:
    """A reply's required text (parse_thread_text with required=True, which never gives None)."""
    text = parse_thread_text(v)
    return "" if text is None else text


def parse_reopen_flag(d: Json) -> bool | None | InputRejected:
    """The reply body's optional reopen - true/false overrides the rule, absent (None) lets the server decide."""
    v = d.get("reopen")
    if v is not None and not isinstance(v, bool):
        return InputRejected("reopen 은 true/false 입니다(없으면 서버 규칙을 따릅니다).", "bad_reopen")
    return v


class ReplyRequest(NamedTuple):
    """A POST /api/pins/{id}/reply body: the cleaned text, the viewer's @-tag hints and the optional reopen override
    (None lets the server decide)."""

    text: str
    hints: list[str]
    reopen: bool | None


def parse_reply(d: Json) -> ReplyRequest | InputRejected:
    """A POST /api/pins/{id}/reply body, in the order the server has always checked it: text (parse_reply_text),
    mentions (parse_mention_hints), then reopen (parse_reopen_flag). Any other field is ignored."""
    text = parse_reply_text(d.get("text"))
    if isinstance(text, InputRejected):
        return text
    hints = parse_mention_hints(d.get("mentions"))
    if isinstance(hints, InputRejected):
        return hints
    reopen = parse_reopen_flag(d)
    if isinstance(reopen, InputRejected):
        return reopen
    return ReplyRequest(text, hints, reopen)
