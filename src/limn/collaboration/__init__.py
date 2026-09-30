"""Public operations and values owned by the collaboration capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .directory import PeopleDirectory as PeopleDirectory
    from .events import ReadCache as ReadCache
    from .notices import Notices as Notices
    from .routes import get as get_route

__all__ = ["Notices", "PeopleDirectory", "ReadCache", "get_route"]

_EXPORTS = {
    "Notices": ("notices", "Notices"),
    "PeopleDirectory": ("directory", "PeopleDirectory"),
    "ReadCache": ("events", "ReadCache"),
    "get_route": ("routes", "get"),
}


def __getattr__(name: str) -> object:
    """Load only the requested public operation without initializing unrelated adapters."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
