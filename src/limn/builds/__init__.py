"""Public operations and values owned by the builds capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .answer import build_failure_log as build_failure_log
    from .application import (
        BuildCommands as BuildCommands,
        BuildSubsystem as BuildSubsystem,
        BuildView as BuildView,
        assemble_builds as assemble_builds,
    )
    from .artifacts import (
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
    from .routes import POST_PATH as REBUILD_PATH, get as get_route, post as post_route
    from .run import needs_build as needs_build
    from .service import BuildRequests as BuildRequests

__all__ = [
    "assemble_builds",
    "build_figure_pdf",
    "BuildRequests",
    "BuildCommands",
    "BuildSkipped",
    "BuildSubsystem",
    "BuildView",
    "DocumentFacts",
    "FailedBuild",
    "REBUILD_PATH",
    "build_failure_log",
    "cur_pages",
    "cur_pdf",
    "get_route",
    "last_build_failed",
    "load_builds",
    "migrate_pages",
    "needs_build",
    "page_list",
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
    "assemble_builds": ("application", "assemble_builds"),
    "build_figure_pdf": ("artifacts", "build_figure_pdf"),
    "BuildRequests": ("service", "BuildRequests"),
    "BuildCommands": ("application", "BuildCommands"),
    "BuildSkipped": ("artifacts", "BuildSkipped"),
    "BuildSubsystem": ("application", "BuildSubsystem"),
    "BuildView": ("application", "BuildView"),
    "DocumentFacts": ("document_facts", "DocumentFacts"),
    "FailedBuild": ("artifacts", "FailedBuild"),
    "REBUILD_PATH": ("routes", "POST_PATH"),
    "build_failure_log": ("answer", "build_failure_log"),
    "cur_pages": ("artifacts", "cur_pages"),
    "cur_pdf": ("artifacts", "cur_pdf"),
    "get_route": ("routes", "get"),
    "last_build_failed": ("artifacts", "last_build_failed"),
    "load_builds": ("artifacts", "load_builds"),
    "migrate_pages": ("artifacts", "migrate_pages"),
    "needs_build": ("run", "needs_build"),
    "page_list": ("artifacts", "page_list"),
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
