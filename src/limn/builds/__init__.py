"""Public operations and values owned by the builds capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .answer import build_failure_log as build_failure_log
    from .artifacts import (
        BuildMapCache as BuildMapCache,
        BuildSkipped as BuildSkipped,
        FailedBuild as FailedBuild,
        build_figure_pdf as build_figure_pdf,
        cur_pages as cur_pages,
        cur_pdf as cur_pdf,
        last_build_failed as last_build_failed,
        load_builds as load_builds,
        migrate_pages as migrate_pages,
        page_list as page_list,
        read_built_at as read_built_at,
        read_built_src_mtime as read_built_src_mtime,
        read_head as read_head,
        seed_builds as seed_builds,
        source_newer as source_newer,
        src_mtime as src_mtime,
        state_snapshot as state_snapshot,
        valid_build_name as valid_build_name,
    )
    from .document_facts import DocumentFacts as DocumentFacts
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
    from .routes import POST_PATH as REBUILD_PATH, get as get_route, post as post_route
    from .run import needs_build as needs_build
    from .service import BuildRequests as BuildRequests

__all__ = [
    "build_figure_pdf",
    "BuildMapCache",
    "BuildRequests",
    "BuildSkipped",
    "DocumentFacts",
    "ElementPick",
    "FailedBuild",
    "FigureMap",
    "Frac",
    "MAP_MAX_DEPTH",
    "MAP_MAX_LINE",
    "MAP_MAX_PATH",
    "MAP_MAX_TEXT",
    "MapElement",
    "MapPage",
    "MapRejected",
    "REBUILD_PATH",
    "build_failure_log",
    "cur_pages",
    "cur_pdf",
    "element_kind",
    "follow_element",
    "get_route",
    "is_canonical_path",
    "ladder_scopes",
    "last_build_failed",
    "load_builds",
    "migrate_pages",
    "needs_build",
    "page_list",
    "pick_element",
    "post_route",
    "read_built_at",
    "read_built_src_mtime",
    "read_head",
    "seed_builds",
    "source_newer",
    "src_mtime",
    "state_snapshot",
    "valid_build_name",
]

_EXPORTS = {
    "build_figure_pdf": ("artifacts", "build_figure_pdf"),
    "BuildMapCache": ("artifacts", "BuildMapCache"),
    "BuildRequests": ("service", "BuildRequests"),
    "BuildSkipped": ("artifacts", "BuildSkipped"),
    "DocumentFacts": ("document_facts", "DocumentFacts"),
    "ElementPick": ("figure_map", "ElementPick"),
    "FailedBuild": ("artifacts", "FailedBuild"),
    "FigureMap": ("figure_map", "FigureMap"),
    "Frac": ("figure_map", "Frac"),
    "MAP_MAX_DEPTH": ("figure_map", "MAP_MAX_DEPTH"),
    "MAP_MAX_LINE": ("figure_map", "MAP_MAX_LINE"),
    "MAP_MAX_PATH": ("figure_map", "MAP_MAX_PATH"),
    "MAP_MAX_TEXT": ("figure_map", "MAP_MAX_TEXT"),
    "MapElement": ("figure_map", "MapElement"),
    "MapPage": ("figure_map", "MapPage"),
    "MapRejected": ("figure_map", "MapRejected"),
    "REBUILD_PATH": ("routes", "POST_PATH"),
    "build_failure_log": ("answer", "build_failure_log"),
    "cur_pages": ("artifacts", "cur_pages"),
    "cur_pdf": ("artifacts", "cur_pdf"),
    "element_kind": ("figure_map", "element_kind"),
    "follow_element": ("figure_map", "follow_element"),
    "get_route": ("routes", "get"),
    "is_canonical_path": ("figure_map", "is_canonical_path"),
    "ladder_scopes": ("figure_map", "ladder_scopes"),
    "last_build_failed": ("artifacts", "last_build_failed"),
    "load_builds": ("artifacts", "load_builds"),
    "migrate_pages": ("artifacts", "migrate_pages"),
    "needs_build": ("run", "needs_build"),
    "page_list": ("artifacts", "page_list"),
    "pick_element": ("figure_map", "pick_element"),
    "post_route": ("routes", "post"),
    "read_built_at": ("artifacts", "read_built_at"),
    "read_built_src_mtime": ("artifacts", "read_built_src_mtime"),
    "read_head": ("artifacts", "read_head"),
    "seed_builds": ("artifacts", "seed_builds"),
    "source_newer": ("artifacts", "source_newer"),
    "src_mtime": ("artifacts", "src_mtime"),
    "state_snapshot": ("artifacts", "state_snapshot"),
    "valid_build_name": ("artifacts", "valid_build_name"),
}


def __getattr__(name: str) -> object:
    """Load only the requested public operation without initializing unrelated adapters."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
