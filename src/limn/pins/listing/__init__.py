"""Pin operations load adapters only when a declared export is requested."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .markdown import PinMarkdown as PinMarkdown
    from .routes import get as get_route
    from .service import PinListing as PinListing

__all__ = ["PinListing", "PinMarkdown", "get_route"]

_EXPORTS = {
    "PinMarkdown": ("markdown", "PinMarkdown"),
    "get_route": ("routes", "get"),
    "PinListing": ("service", "PinListing"),
}


def __getattr__(name: str) -> object:
    """Resolve one public pin operation without loading unrelated HTTP services."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
