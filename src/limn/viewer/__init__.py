"""Declared query, command and assembly surface of the viewer capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import assemble_viewer as assemble_viewer
    from .assemble import (
        ServedViewer as ServedViewer,
        default_pdfjs_dir as default_pdfjs_dir,
        read_viewer as read_viewer,
        serve_viewer as serve_viewer,
    )

__all__ = ["ServedViewer", "assemble_viewer", "default_pdfjs_dir", "read_viewer", "serve_viewer"]

_EXPORTS = {
    "ServedViewer": ("assemble", "ServedViewer"),
    "assemble_viewer": ("application", "assemble_viewer"),
    "default_pdfjs_dir": ("assemble", "default_pdfjs_dir"),
    "read_viewer": ("assemble", "read_viewer"),
    "serve_viewer": ("assemble", "serve_viewer"),
}


def __getattr__(name: str) -> object:
    """Load one declared contract without initializing unrelated routes or runtime resources."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
