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
    from .artifacts import (
        BuildMapCache as BuildMapCache,
        build_figure_pdf as build_figure_pdf,
        valid_build_name as valid_build_name,
    )
    from .figure_map import (
        MAP_MAX_DEPTH as MAP_MAX_DEPTH,
        MAP_MAX_LINE as MAP_MAX_LINE,
        MAP_MAX_PATH as MAP_MAX_PATH,
        MAP_MAX_TEXT as MAP_MAX_TEXT,
        ElementPick as ElementPick,
        FigureMap as FigureMap,
        Frac as Frac,
        MapElement as MapElement,
        MapPage as MapPage,
        MapRejected as MapRejected,
        element_kind as element_kind,
        follow_element as follow_element,
        is_canonical_path as is_canonical_path,
        ladder_scopes as ladder_scopes,
        pick_element as pick_element,
    )

__all__ = [
    "valid_build_name",
    "build_figure_pdf",
    "BuildMapCache",
    "ElementPick",
    "FigureMap",
    "Frac",
    "MAP_MAX_DEPTH",
    "MAP_MAX_LINE",
    "MAP_MAX_PATH",
    "MAP_MAX_TEXT",
    "MapElement",
    "MapPage",
    "MapRejected",
    "element_kind",
    "follow_element",
    "is_canonical_path",
    "ladder_scopes",
    "pick_element",
    "BuildView",
    "BuildCommands",
    "BuildInitialization",
    "BuildSubsystem",
    "assemble_builds",
]

_EXPORTS = {
    "valid_build_name": ("artifacts", "valid_build_name"),
    "build_figure_pdf": ("artifacts", "build_figure_pdf"),
    "BuildMapCache": ("artifacts", "BuildMapCache"),
    "ElementPick": ("figure_map", "ElementPick"),
    "FigureMap": ("figure_map", "FigureMap"),
    "Frac": ("figure_map", "Frac"),
    "MAP_MAX_DEPTH": ("figure_map", "MAP_MAX_DEPTH"),
    "MAP_MAX_LINE": ("figure_map", "MAP_MAX_LINE"),
    "MAP_MAX_PATH": ("figure_map", "MAP_MAX_PATH"),
    "MAP_MAX_TEXT": ("figure_map", "MAP_MAX_TEXT"),
    "MapElement": ("figure_map", "MapElement"),
    "MapPage": ("figure_map", "MapPage"),
    "MapRejected": ("figure_map", "MapRejected"),
    "element_kind": ("figure_map", "element_kind"),
    "follow_element": ("figure_map", "follow_element"),
    "is_canonical_path": ("figure_map", "is_canonical_path"),
    "ladder_scopes": ("figure_map", "ladder_scopes"),
    "pick_element": ("figure_map", "pick_element"),
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
