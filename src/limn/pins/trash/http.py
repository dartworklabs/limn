"""HTTP entry points and responses for the Trash feature."""

from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypeAlias

from limn.pins.model import DonePin, OpenPin, PinNotFound, Record, ReviewPin, TrashedPin
from limn.pins.trash import input as trash_input
from limn.pins.trash.rules import AlreadyLive, NotInTrash, VerdictByAgent
from limn.pins.trash.service import PinTrash
from limn.security.access import PostAuthority
from limn.web.answers import accepted
from limn.web.errors import HTTPError

Body: TypeAlias = dict[str, object]
Show: TypeAlias = Callable[[Record], object]

# D16: an agent neither deletes nor restores a verdict pin (403 verdict_human, the reason D11's refusal has).
VERDICT_DROP_HUMAN = "판정은 사람이 정합니다 — 에이전트는 판정 핀을 지우지 않습니다."
VERDICT_RESTORE_HUMAN = "판정은 사람이 정합니다 — 에이전트는 판정 핀을 되살리지 않습니다."


class TrashApp(Protocol):
    """Run-specific collaborators used by Trash HTTP actions."""

    pin_trash: PinTrash

    def public(self, record: Record) -> dict[str, Any]:
        """Render one pin record for the API."""
        ...


def drop(app: TrashApp, pid: int, actor: PostAuthority) -> Body:
    """Answer POST /api/pins/{id}/drop after shared guards."""
    return drop_answer(app.pin_trash.drop_pin(pid, actor))


def restore(app: TrashApp, pid: int, actor: PostAuthority) -> Body:
    """Answer POST /api/pins/{id}/restore after shared guards."""
    return restore_answer(app.pin_trash.restore_pin(pid, actor), app.public)


def purge(app: TrashApp, pid: int, actor: PostAuthority) -> Body:
    """Answer owner-only POST /api/pins/{id}/purge after shared role checking."""
    return purge_answer(app.pin_trash.purge_pin(pid, actor), pid)


def clear(app: TrashApp, actor: PostAuthority, body: Mapping[str, Any]) -> Body:
    """Check the confirmation phrase and answer owner-only POST /api/clear."""
    accepted(trash_input.parse_clear(body))
    return clear_answer(app.pin_trash.clear_pins(actor))


def clear_answer(result: Mapping[str, Any]) -> Body:
    """POST /api/clear: the archive and number of cleared pins, with ok true."""
    return dict(result, ok=True)


def restore_answer(
    result: OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive | VerdictByAgent, show: Show
) -> Body:
    """POST /api/pins/{id}/restore: the pin back in the list, or 404/409 with the old messages, or 403 verdict_human
    for an agent's restore of a verdict pin (D16)."""
    match result:
        case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
            return {"ok": True, "pin": show(record)}
        case NotInTrash(pid=pid):
            raise HTTPError(404, "삭제 기록에 핀 #%d 이 없습니다." % pid, reason="not_in_trash")
        case AlreadyLive(pid=pid):
            raise HTTPError(409, "핀 #%d 이 이미 있습니다." % pid, reason="pin_exists")
        case VerdictByAgent():
            raise HTTPError(403, VERDICT_RESTORE_HUMAN, reason="verdict_human")


def drop_answer(result: TrashedPin | PinNotFound | VerdictByAgent) -> Body:
    """POST /api/pins/{id}/drop: ok true when dropped, false when the id was absent, 403 verdict_human for an agent's
    drop of a verdict pin (D16)."""
    match result:
        case TrashedPin():
            return {"ok": True}
        case PinNotFound():
            return {"ok": False}
        case VerdictByAgent():
            raise HTTPError(403, VERDICT_DROP_HUMAN, reason="verdict_human")


def purge_answer(result: TrashedPin | NotInTrash, pid: int) -> Body:
    """POST /api/pins/{id}/purge: permanent deletion or 404 not_in_trash."""
    match result:
        case TrashedPin():
            return {"ok": True, "purged": pid}
        case NotInTrash():
            raise HTTPError(404, "휴지통에 핀 #%d 이 없습니다." % pid, reason="not_in_trash")
