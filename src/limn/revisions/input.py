"""Commit, base, pin and paging inputs for revision and comparison PDF requests."""

import re
from typing import NamedTuple

from limn.platform.values import is_int
from limn.revisions.core import REVISION_ID_RE, REVISION_PAGE_MAX, REVISION_RECENT, HistoryPage
from limn.web.errors import InputRejected
from limn.web.parse import Json, Query, query_first

REVISION_BUILD_FIELDS = frozenset({"commit", "base", "doc", "pin"})
PIN_WITH_BASE = InputRejected("핀 단위 변경 보기는 두 커밋 사이 비교와 함께 쓸 수 없습니다.", "pin_with_base")


def parse_pin_param(v: object) -> int | None | InputRejected:
    """The optional pin of a revision request (query string or JSON int): None if absent or empty, else a pin id
    1..999999999. Whether the pin exists is decided later."""
    if v is None or v == "":
        return None
    if isinstance(v, str) and re.fullmatch(r"[1-9][0-9]{0,8}", v):
        return int(v)
    if isinstance(v, int) and is_int(v) and 1 <= v <= 999999999:
        return v
    return InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin")


class RevisionQuery(NamedTuple):
    """A revision request's commit (a full lowercase SHA-1), optional pin and optional range base (issue #188: the old
    side of a two-commit comparison; never together with pin)."""

    commit: str
    pin: int | None
    base: str | None = None


def parse_commit(v: object) -> str | InputRejected:
    """A commit id as the revision routes take it: a full lowercase SHA-1 string. Whether it is one of the document's
    recent commits is the service's to decide."""
    if not isinstance(v, str) or not REVISION_ID_RE.fullmatch(v):
        return InputRejected("올바른 커밋 ID가 아닙니다.", "bad_commit")
    return v


def parse_base(v: object) -> str | None | InputRejected:
    """A range's optional base: None when absent or empty (the single-commit request, unchanged), else a full lowercase
    SHA-1 (bad_commit otherwise). Whether it lies in the document's history is the service's to decide."""
    if v is None or v == "":
        return None
    if not isinstance(v, str) or not REVISION_ID_RE.fullmatch(v):
        return InputRejected("올바른 기준 커밋 ID가 아닙니다.", "bad_commit")
    return v


def _with_base(commit: str, pin: int | None, base: object) -> RevisionQuery | InputRejected:
    """The query of commit and pin with base parsed (parse_base); a pin and a base together are pin_with_base."""
    parsed = parse_base(base)
    return _combined(commit, pin, parsed)


def _combined(commit: str, pin: int | None, parsed: str | None | InputRejected) -> RevisionQuery | InputRejected:
    """The query of commit, pin and a parsed base (or its refusal); a pin and a base together are pin_with_base."""
    if isinstance(parsed, InputRejected):
        return parsed
    if parsed is not None and pin is not None:
        return PIN_WITH_BASE
    return RevisionQuery(commit, pin, parsed)


def parse_revision_query(q: Query) -> RevisionQuery | InputRejected:
    """GET /api/revision-diff|-build|-pdf: the optional &pin= (parse_pin_param) first, then ?commit= (parse_commit),
    then the optional &base= (parse_base), never together with a pin."""
    pin = parse_pin_param(query_first(q, "pin"))
    if isinstance(pin, InputRejected):
        return pin
    commit = parse_commit(query_first(q, "commit", "") or "")
    if isinstance(commit, InputRejected):
        return commit
    return _with_base(commit, pin, query_first(q, "base"))


def parse_revision_build(d: Json) -> RevisionQuery | InputRejected:
    """POST /api/revision-build's body: only commit, base, doc and pin; pin, when present, a JSON integer in range;
    then the commit (parse_commit), then base when the body names it - a full SHA-1 string (null and "" are refused,
    unlike the query's empty base=), never together with pin."""
    if set(d) - REVISION_BUILD_FIELDS:
        return InputRejected("허용되지 않는 비교 PDF 요청 필드입니다.", "unknown_fields")
    if "pin" in d and not is_int(d["pin"]):
        return InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin")
    pin = parse_pin_param(d.get("pin"))
    if isinstance(pin, InputRejected):
        return pin
    commit = parse_commit(d.get("commit"))
    if isinstance(commit, InputRejected):
        return commit
    if "base" not in d:
        return RevisionQuery(commit, pin)
    base = d["base"]  # in a body, a named base is a range: null and "" are refused, never read as absent
    if not isinstance(base, str) or not REVISION_ID_RE.fullmatch(base):
        return InputRejected("올바른 기준 커밋 ID가 아닙니다.", "bad_commit")
    return _combined(commit, pin, base)


def parse_history_query(q: Query) -> HistoryPage | None | InputRejected:
    """GET /api/revisions: None without before and limit (the REVISION_RECENT newest, as before paging), else the page
    asked: before a full SHA-1 (bad_commit otherwise), limit 1..REVISION_PAGE_MAX in decimal digits (bad_limit
    otherwise; REVISION_RECENT when absent). Empty values are absent."""
    before, limit = query_first(q, "before") or None, query_first(q, "limit") or None
    if before is None and limit is None:
        return None
    if before is not None and not REVISION_ID_RE.fullmatch(before):
        return InputRejected("올바른 커밋 ID가 아닙니다.", "bad_commit")
    if limit is not None and not (re.fullmatch(r"[0-9]{1,3}", limit) and 1 <= int(limit) <= REVISION_PAGE_MAX):
        return InputRejected("limit 은 1–%d 사이의 정수여야 합니다." % REVISION_PAGE_MAX, "bad_limit")
    return HistoryPage(before, int(limit) if limit is not None else REVISION_RECENT)
