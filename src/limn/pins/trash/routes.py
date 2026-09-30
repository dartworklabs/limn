"""Registered pin Trash actions and the clear path."""

from limn.pins.trash import http
from limn.pins.trash.http import TrashApp
from limn.web.routes import OtherPost, PinAction

CLEAR_PATH = "/api/clear"


def actions(app: TrashApp) -> dict[str, PinAction]:
    """Bind Trash actions to this run's service."""
    return {
        "drop": lambda r: http.drop(app, r.pid, r.actor),
        "restore": lambda r: http.restore(app, r.pid, r.actor),
        "purge": lambda r: http.purge(app, r.pid, r.actor),
    }


def other_posts(app: TrashApp) -> dict[str, OtherPost]:
    """Bind the owner-only clear path to this run's service."""
    return {CLEAR_PATH: lambda r: http.clear(app, r.actor, r.body)}
