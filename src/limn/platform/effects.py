"""Request-local read capabilities and mutation observations, independent of feature ownership."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_read_only: ContextVar[bool] = ContextVar("read_only", default=False)


@dataclass
class Changes:
    """Whether an operation actually changed persistent state or started changing work."""

    changed: bool = False


_changes: ContextVar[Changes | None] = ContextVar("changes", default=None)


@contextmanager
def reading() -> Iterator[None]:
    """Deny writers and work scheduling throughout this request, including nested collaborators."""
    token = _read_only.set(True)
    try:
        yield
    finally:
        _read_only.reset(token)


def require_writer() -> None:
    """Reject writer acquisition or effects in a read request before any file or thread changes."""
    if _read_only.get():
        raise PermissionError("read requests cannot obtain a writer or schedule writes")


@contextmanager
def observing_changes() -> Iterator[Changes]:
    """Observe real changes on this request only; failures never register a person."""
    changes = Changes()
    token = _changes.set(changes)
    try:
        yield changes
    finally:
        _changes.reset(token)


def changed() -> None:
    """Record a completed mutation or accepted worker; read requests cannot mark a change."""
    require_writer()
    observation = _changes.get()
    if observation is not None:
        observation.changed = True
