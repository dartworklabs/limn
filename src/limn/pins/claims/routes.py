"""Registered pin claim actions."""

from limn.pins.claims import http
from limn.pins.claims.http import ClaimsApp
from limn.web.routes import PinAction


def actions(app: ClaimsApp) -> dict[str, PinAction]:
    """Bind claim paths to this run's service."""
    return {
        "claim": lambda r: http.claim(app, r.pid, r.actor, r.body),
        "unclaim": lambda r: http.unclaim(app, r.pid, r.actor),
    }
