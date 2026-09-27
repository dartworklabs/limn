"""Input accepted by the bulk clear operation."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from limn.web.errors import InputRejected

CLEAR_CONFIRM = "clear all pins"


@dataclass(frozen=True)
class ClearConfirmed:
    """A POST /api/clear body that carries the confirmation phrase (CLEAR_CONFIRM)."""


def parse_clear(d: Mapping[str, Any]) -> ClearConfirmed | InputRejected:
    """A POST /api/clear body: its confirm must be exactly CLEAR_CONFIRM, else 400 confirm_required naming the phrase
    and the archive left behind. Any other field is ignored."""
    if d.get("confirm") != CLEAR_CONFIRM:
        return InputRejected(
            '모든 핀을 지우려면 본문에 {"confirm": "%s"} 를 보내세요(보관본 pins_<시각>.jsonl.bak 이 남습니다).'
            % CLEAR_CONFIRM,
            "confirm_required",
        )
    return ClearConfirmed()
