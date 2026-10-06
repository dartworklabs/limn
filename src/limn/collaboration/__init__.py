"""Declared query, command and assembly surface of the collaboration capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import (
        CollaborationSubsystem as CollaborationSubsystem,
        assemble_collaboration as assemble_collaboration,
    )

__all__ = ["CollaborationSubsystem", "assemble_collaboration"]

_EXPORTS = {
    "CollaborationSubsystem": ("application", "CollaborationSubsystem"),
    "assemble_collaboration": ("application", "assemble_collaboration"),
}


def __getattr__(name: str) -> object:
    """Load one declared contract without initializing unrelated routes or runtime resources."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
