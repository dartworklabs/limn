"""Registered pin lifecycle actions."""

from limn.features.pins.lifecycle import http
from limn.features.pins.lifecycle.http import LifecycleApp
from limn.web.routes import PinAction


def actions(app: LifecycleApp) -> dict[str, PinAction]:
    """Bind lifecycle paths to this run's service."""
    return {
        "reply": lambda r: http.reply(app, r.pid, r.actor, r.body),
        "confirm": lambda r: http.confirm(app, r.pid, r.actor),
        "close": lambda r: http.close(app, r.pid, r.actor, r.body, r.principal.review_on_close),
        "reopen": lambda r: http.reopen(app, r.pid, r.actor, r.body),
    }
