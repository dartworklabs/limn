"""Public operations and values owned by the viewer capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .assemble import (
        LUCIDE as LUCIDE,
        PDFJS_VERSION as PDFJS_VERSION,
        VIEWER_DIR as VIEWER_DIR,
        ServedViewer as ServedViewer,
        ViewerFiles as ViewerFiles,
        load_ui_messages as load_ui_messages,
        serve_viewer as serve_viewer,
        service_worker as service_worker,
        viewer_html as viewer_html,
    )
    from .mark import FILES as BRAND_FILES, Brand as Brand, brand as brand
    from .routes import get as get_route

__all__ = [
    "brand",
    "Brand",
    "BRAND_FILES",
    "LUCIDE",
    "PDFJS_VERSION",
    "ServedViewer",
    "VIEWER_DIR",
    "ViewerFiles",
    "get_route",
    "load_ui_messages",
    "serve_viewer",
    "service_worker",
    "viewer_html",
]

_EXPORTS = {
    "brand": ("mark", "brand"),
    "Brand": ("mark", "Brand"),
    "BRAND_FILES": ("mark", "FILES"),
    "LUCIDE": ("assemble", "LUCIDE"),
    "PDFJS_VERSION": ("assemble", "PDFJS_VERSION"),
    "ServedViewer": ("assemble", "ServedViewer"),
    "VIEWER_DIR": ("assemble", "VIEWER_DIR"),
    "ViewerFiles": ("assemble", "ViewerFiles"),
    "get_route": ("routes", "get"),
    "load_ui_messages": ("assemble", "load_ui_messages"),
    "serve_viewer": ("assemble", "serve_viewer"),
    "service_worker": ("assemble", "service_worker"),
    "viewer_html": ("assemble", "viewer_html"),
}


def __getattr__(name: str) -> object:
    """Load only the requested public operation without initializing unrelated adapters."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
