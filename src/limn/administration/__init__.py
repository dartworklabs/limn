"""Public operations and values owned by the administration capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .members import cmd_member as cmd_member
    from .migrate import main as migrate_main
    from .serve_documents import doc_start_line as doc_start_line, docs_of as docs_of, pick_documents as pick_documents
    from .targets import CliError as CliError
    from .tokens import cmd_token as cmd_token

__all__ = ["doc_start_line", "CliError", "cmd_member", "cmd_token", "docs_of", "migrate_main", "pick_documents"]

_EXPORTS = {
    "doc_start_line": ("serve_documents", "doc_start_line"),
    "CliError": ("targets", "CliError"),
    "cmd_member": ("members", "cmd_member"),
    "cmd_token": ("tokens", "cmd_token"),
    "docs_of": ("serve_documents", "docs_of"),
    "migrate_main": ("migrate", "main"),
    "pick_documents": ("serve_documents", "pick_documents"),
}


def __getattr__(name: str) -> object:
    """Load only the requested public operation without initializing unrelated adapters."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
