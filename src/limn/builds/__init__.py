"""Declared query, command and assembly surface of the builds capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import (
        BuildCommands as BuildCommands,
        BuildInitialization as BuildInitialization,
        BuildSubsystem as BuildSubsystem,
        BuildView as BuildView,
        assemble_builds as assemble_builds,
    )

__all__ = ["BuildView", "BuildCommands", "BuildInitialization", "BuildSubsystem", "assemble_builds"]

_EXPORTS = {
    "BuildView": ("application", "BuildView"),
    "BuildCommands": ("application", "BuildCommands"),
    "BuildInitialization": ("application", "BuildInitialization"),
    "BuildSubsystem": ("application", "BuildSubsystem"),
    "assemble_builds": ("application", "assemble_builds"),
}


def __getattr__(name: str) -> object:
    """Load one declared contract without initializing unrelated routes or runtime resources."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
