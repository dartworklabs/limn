"""Public operations and values owned by the sync capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import SyncSubsystem as SyncSubsystem, assemble_sync as assemble_sync
    from .run import PullShare as PullShare, SyncWatch as SyncWatch, local_stamp as local_stamp
    from .service import SyncContext as SyncContext, SyncService as SyncService

__all__ = ["PullShare", "SyncContext", "SyncService", "SyncSubsystem", "SyncWatch", "assemble_sync", "local_stamp"]

_EXPORTS = {
    "PullShare": ("run", "PullShare"),
    "SyncContext": ("service", "SyncContext"),
    "SyncService": ("service", "SyncService"),
    "SyncSubsystem": ("application", "SyncSubsystem"),
    "SyncWatch": ("run", "SyncWatch"),
    "assemble_sync": ("application", "assemble_sync"),
    "local_stamp": ("run", "local_stamp"),
}


def __getattr__(name: str) -> object:
    """Load only the requested public operation without initializing unrelated adapters."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
