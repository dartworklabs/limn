"""Declared, purpose-specific query and assembly surface of the builds capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import (
        BuildCommands as BuildCommands,
        BuildInitialization as BuildInitialization,
        BuildSubsystem as BuildSubsystem,
        assemble_builds as assemble_builds,
    )
    from .artifacts import BuildMapCache as BuildMapCache
    from .contracts import (
        BuildHeading as BuildHeading,
        DocumentBuild as DocumentBuild,
        DocumentBuildQueries as DocumentBuildQueries,
        ElementFact as ElementFact,
        ElementFollower as ElementFollower,
        ElementPosition as ElementPosition,
        ElementSelection as ElementSelection,
        OutlineInput as OutlineInput,
        PinBuildQueries as PinBuildQueries,
        PositionHistory as PositionHistory,
        Publication as Publication,
        RevisionBuildQueries as RevisionBuildQueries,
        SelectionUnavailable as SelectionUnavailable,
    )
    from .queries import document_build_queries as document_build_queries, pin_build_queries as pin_build_queries

__all__ = [
    "BuildHeading",
    "DocumentBuild",
    "DocumentBuildQueries",
    "ElementFact",
    "ElementFollower",
    "ElementPosition",
    "ElementSelection",
    "OutlineInput",
    "PinBuildQueries",
    "PositionHistory",
    "Publication",
    "RevisionBuildQueries",
    "SelectionUnavailable",
    "BuildMapCache",
    "BuildCommands",
    "BuildInitialization",
    "BuildSubsystem",
    "assemble_builds",
    "document_build_queries",
    "pin_build_queries",
]

_EXPORTS = {
    "BuildHeading": ("contracts", "BuildHeading"),
    "DocumentBuild": ("contracts", "DocumentBuild"),
    "DocumentBuildQueries": ("contracts", "DocumentBuildQueries"),
    "ElementFact": ("contracts", "ElementFact"),
    "ElementFollower": ("contracts", "ElementFollower"),
    "ElementPosition": ("contracts", "ElementPosition"),
    "ElementSelection": ("contracts", "ElementSelection"),
    "OutlineInput": ("contracts", "OutlineInput"),
    "PinBuildQueries": ("contracts", "PinBuildQueries"),
    "PositionHistory": ("contracts", "PositionHistory"),
    "Publication": ("contracts", "Publication"),
    "RevisionBuildQueries": ("contracts", "RevisionBuildQueries"),
    "SelectionUnavailable": ("contracts", "SelectionUnavailable"),
    "BuildMapCache": ("artifacts", "BuildMapCache"),
    "BuildCommands": ("application", "BuildCommands"),
    "BuildInitialization": ("application", "BuildInitialization"),
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
