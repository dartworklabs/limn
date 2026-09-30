"""Declared query, command and assembly surface of the pins capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import (
        PinStartup as PinStartup,
        PinSubsystem as PinSubsystem,
        assemble_pins as assemble_pins,
    )
    from .contracts import PinCountQueries as PinCountQueries, RevisionPinQuery as RevisionPinQuery
    from .location import TokenCache as TokenCache
    from .revision import RevisionPin as RevisionPin
    from .runtime import PinCommands as PinCommands

__all__ = [
    "PinCountQueries",
    "RevisionPinQuery",
    "RevisionPin",
    "PinCommands",
    "PinStartup",
    "PinSubsystem",
    "TokenCache",
    "assemble_pins",
]

_EXPORTS = {
    "PinCountQueries": ("contracts", "PinCountQueries"),
    "RevisionPinQuery": ("contracts", "RevisionPinQuery"),
    "RevisionPin": ("revision", "RevisionPin"),
    "PinCommands": ("runtime", "PinCommands"),
    "PinStartup": ("application", "PinStartup"),
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
