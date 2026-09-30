"""Public operations and values owned by the revisions capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .answer import revision_failure_text as revision_failure_text
    from .core import (
        RevisionContext as RevisionContext,
        RevisionDoc as RevisionDoc,
        RevisionJobs as RevisionJobs,
        ScopeCache as ScopeCache,
    )
    from .routes import POST_PATH as REVISION_PATH, get as get_route, post as post_route
    from .service import RevisionRequests as RevisionRequests

__all__ = [
    "REVISION_PATH",
    "RevisionContext",
    "RevisionDoc",
    "RevisionJobs",
    "RevisionRequests",
    "ScopeCache",
    "get_route",
    "post_route",
    "revision_failure_text",
]

_EXPORTS = {
    "REVISION_PATH": ("routes", "POST_PATH"),
    "RevisionContext": ("core", "RevisionContext"),
    "RevisionDoc": ("core", "RevisionDoc"),
    "RevisionJobs": ("core", "RevisionJobs"),
    "RevisionRequests": ("service", "RevisionRequests"),
    "ScopeCache": ("core", "ScopeCache"),
    "get_route": ("routes", "get"),
    "post_route": ("routes", "post"),
    "revision_failure_text": ("answer", "revision_failure_text"),
}


def __getattr__(name: str) -> object:
    """Load only the requested public operation without initializing unrelated adapters."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
