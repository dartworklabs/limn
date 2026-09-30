"""Pin operations load adapters only when a declared export is requested."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .resolve import PickContext as PickContext
    from .routes import POST_PATH as PICK_PATH, get as get_route, post as post_route
    from .service import PinLocationService as PinLocationService
    from .source import TokenCache as TokenCache

__all__ = ["PICK_PATH", "PickContext", "PinLocationService", "TokenCache", "get_route", "post_route"]

_EXPORTS = {
    "PickContext": ("resolve", "PickContext"),
    "PICK_PATH": ("routes", "POST_PATH"),
    "get_route": ("routes", "get"),
    "post_route": ("routes", "post"),
    "PinLocationService": ("service", "PinLocationService"),
    "TokenCache": ("source", "TokenCache"),
}


def __getattr__(name: str) -> object:
    """Resolve one public pin operation without loading unrelated HTTP services."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
