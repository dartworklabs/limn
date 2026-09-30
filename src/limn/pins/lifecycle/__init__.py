"""Pin operations load adapters only when a declared export is requested."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .routes import actions as pin_actions
    from .service import PinLifecycle as PinLifecycle

__all__ = ["PinLifecycle", "pin_actions"]

_EXPORTS = {"pin_actions": ("routes", "actions"), "PinLifecycle": ("service", "PinLifecycle")}


def __getattr__(name: str) -> object:
    """Resolve one public pin operation without loading unrelated HTTP services."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
