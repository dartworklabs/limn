"""Declared query, command and assembly surface of the documents capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import DocumentsSubsystem as DocumentsSubsystem, assemble_documents as assemble_documents
    from .reads import MetaSettings as MetaSettings

__all__ = ["DocumentsSubsystem", "MetaSettings", "assemble_documents"]

_EXPORTS = {
    "DocumentsSubsystem": ("application", "DocumentsSubsystem"),
    "MetaSettings": ("reads", "MetaSettings"),
    "assemble_documents": ("application", "assemble_documents"),
}


def __getattr__(name: str) -> object:
    """Load one declared contract without initializing unrelated routes or runtime resources."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
