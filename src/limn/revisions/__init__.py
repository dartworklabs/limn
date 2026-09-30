"""Declared query, command and assembly surface of the revisions capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import RevisionSubsystem as RevisionSubsystem, assemble_revisions as assemble_revisions
    from .core import RevisionJobs as RevisionJobs, ScopeCache as ScopeCache

__all__ = ["RevisionJobs", "ScopeCache", "RevisionSubsystem", "assemble_revisions"]

_EXPORTS = {
    "RevisionJobs": ("core", "RevisionJobs"),
    "ScopeCache": ("core", "ScopeCache"),
    "RevisionSubsystem": ("application", "RevisionSubsystem"),
    "assemble_revisions": ("application", "assemble_revisions"),
}


def __getattr__(name: str) -> object:
    """Load one declared contract without initializing unrelated routes or runtime resources."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
