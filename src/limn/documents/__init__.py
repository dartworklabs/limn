"""Public operations and values owned by the documents capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .reads import MetaSettings as MetaSettings
    from .routes import get as get_route
    from .service import DocumentViews as DocumentViews

__all__ = ["DocumentViews", "MetaSettings", "get_route"]

_EXPORTS = {
    "DocumentViews": ("service", "DocumentViews"),
    "MetaSettings": ("reads", "MetaSettings"),
    "get_route": ("routes", "get"),
}


def __getattr__(name: str) -> object:
    """Load only the requested public operation without initializing unrelated adapters."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
