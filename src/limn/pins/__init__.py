"""Declared query, command and assembly surface of the pins capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import PinSubsystem as PinSubsystem, assemble_pins as assemble_pins
    from .location import TokenCache as TokenCache

__all__ = ["PinSubsystem", "TokenCache", "assemble_pins"]

_EXPORTS = {
    "PinSubsystem": ("application", "PinSubsystem"),
    "TokenCache": ("location", "TokenCache"),
    "assemble_pins": ("application", "assemble_pins"),
}


def __getattr__(name: str) -> object:
    """Load one declared contract without initializing unrelated routes or runtime resources."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
