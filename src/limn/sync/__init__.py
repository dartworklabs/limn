"""Declared query, command and assembly surface of the sync capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import SyncSubsystem as SyncSubsystem, assemble_sync as assemble_sync
    from .run import PullShare as PullShare, SyncWatch as SyncWatch
    from .service import SyncContext as SyncContext

__all__ = ["PullShare", "SyncContext", "SyncSubsystem", "SyncWatch", "assemble_sync"]

_EXPORTS = {
    "PullShare": ("run", "PullShare"),
    "SyncContext": ("service", "SyncContext"),
    "SyncSubsystem": ("application", "SyncSubsystem"),
    "SyncWatch": ("run", "SyncWatch"),
    "assemble_sync": ("application", "assemble_sync"),
}


def __getattr__(name: str) -> object:
    """Load one declared contract without initializing unrelated routes or runtime resources."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
