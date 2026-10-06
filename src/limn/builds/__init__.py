"""Declared, purpose-specific query and assembly surface of the builds capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import BuildSubsystem as BuildSubsystem, assemble_builds as assemble_builds
    from .artifacts import BuildMapCache as BuildMapCache
    from .contracts import (
        ElementFact as ElementFact,
        ElementSelection as ElementSelection,
        SelectionUnavailable as SelectionUnavailable,
    )
    from .queries import document_build_queries as document_build_queries, pin_build_queries as pin_build_queries

__all__ = [
    "ElementFact",
    "ElementSelection",
    "SelectionUnavailable",
    "BuildMapCache",
    "BuildSubsystem",
    "assemble_builds",
    "document_build_queries",
    "pin_build_queries",
]

_EXPORTS = {
    "ElementFact": ("contracts", "ElementFact"),
    "ElementSelection": ("contracts", "ElementSelection"),
    "SelectionUnavailable": ("contracts", "SelectionUnavailable"),
    "BuildMapCache": ("artifacts", "BuildMapCache"),
    "BuildSubsystem": ("application", "BuildSubsystem"),
    "assemble_builds": ("application", "assemble_builds"),
    "document_build_queries": ("queries", "document_build_queries"),
    "pin_build_queries": ("queries", "pin_build_queries"),
}


def __getattr__(name: str) -> object:
    """Load only the requested contract, leaving storage and map models private."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
