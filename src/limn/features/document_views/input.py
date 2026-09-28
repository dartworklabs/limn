"""The event cursor of GET /api/meta."""

from collections.abc import Mapping

from limn.web.errors import InputRejected
from limn.web.parse import query_first


def parse_event_cursor(v: str | None) -> int | None | InputRejected:
    """The last event sequence the viewer saw, or None when absent."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return InputRejected("ev 는 정수(마지막으로 본 이벤트 seq)입니다.", "bad_event_cursor")


def parse_events_query(q: Mapping[str, list[str]]) -> int | None | InputRejected:
    """Parse the first ?ev= value after the document summary has been read."""
    return parse_event_cursor(query_first(q, "ev"))
