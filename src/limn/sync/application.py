"""Synchronization capability assembly."""

from collections.abc import Callable
from dataclasses import dataclass

from limn.sync.service import SyncContext, SyncService


@dataclass(frozen=True)
class SyncSubsystem:
    """The synchronization service exposed to composition."""

    service: SyncService


def assemble_sync(context: Callable[[], SyncContext]) -> SyncSubsystem:
    """Bind one run's deferred synchronization facts."""
    return SyncSubsystem(SyncService(context))
