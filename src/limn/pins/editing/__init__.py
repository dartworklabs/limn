"""Pin operations load adapters only when a declared export is requested."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .http import EditingRequests as EditingRequests
    from .routes import POST_NEW_PIN as POST_NEW_PIN, POST_PATH as PIN_PATH, actions as pin_actions, post as post_route
    from .service import EditScope as EditScope, PinEditing as PinEditing

__all__ = ["EditScope", "EditingRequests", "PIN_PATH", "POST_NEW_PIN", "PinEditing", "pin_actions", "post_route"]

_EXPORTS = {
    "EditingRequests": ("http", "EditingRequests"),
    "POST_NEW_PIN": ("routes", "POST_NEW_PIN"),
    "PIN_PATH": ("routes", "POST_PATH"),
    "pin_actions": ("routes", "actions"),
    "post_route": ("routes", "post"),
    "EditScope": ("service", "EditScope"),
    "PinEditing": ("service", "PinEditing"),
}


def __getattr__(name: str) -> object:
    """Resolve one public pin operation without loading unrelated HTTP services."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
