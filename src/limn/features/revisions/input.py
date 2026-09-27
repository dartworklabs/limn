"""Commit and pin inputs for revision and comparison PDF requests."""

import re
from typing import NamedTuple

from limn.features.revisions.core import REVISION_ID_RE
from limn.pins.shapes import is_int
from limn.web.errors import InputRejected
from limn.web.parse import Json, Query, query_first

REVISION_BUILD_FIELDS = frozenset({"commit", "doc", "pin"})


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
    """A revision request's commit (a full lowercase SHA-1) and optional pin."""

    commit: str
    pin: int | None


def parse_commit(v: object) -> str | InputRejected:
    """A commit id as the revision routes take it: a full lowercase SHA-1 string. Whether it is one of the document's
    recent commits is the service's to decide."""
    if not isinstance(v, str) or not REVISION_ID_RE.fullmatch(v):
        return InputRejected("올바른 커밋 ID가 아닙니다.", "bad_commit")
    return v


def parse_revision_query(q: Query) -> RevisionQuery | InputRejected:
    """GET /api/revision-diff|-build|-pdf: the optional &pin= (parse_pin_param) first, then ?commit= (parse_commit)."""
    pin = parse_pin_param(query_first(q, "pin"))
    if isinstance(pin, InputRejected):
        return pin
    commit = parse_commit(query_first(q, "commit", "") or "")
    if isinstance(commit, InputRejected):
        return commit
    return RevisionQuery(commit, pin)


def parse_revision_build(d: Json) -> RevisionQuery | InputRejected:
    """POST /api/revision-build's body: only commit, doc and pin; pin, when present, a JSON integer in range; then
    the commit (parse_commit)."""
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
    return RevisionQuery(commit, pin)
