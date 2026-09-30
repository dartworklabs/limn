"""Pin operations load adapters only when a declared export is requested."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .routes import actions as pin_actions, other_posts as other_posts
    from .service import PinTrash as PinTrash

__all__ = ["PinTrash", "other_posts", "pin_actions"]

_EXPORTS = {
    "pin_actions": ("routes", "actions"),
    "other_posts": ("routes", "other_posts"),
    "PinTrash": ("service", "PinTrash"),
}


def __getattr__(name: str) -> object:
    """Resolve one public pin operation without loading unrelated HTTP services."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
