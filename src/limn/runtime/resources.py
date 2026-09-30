"""Process-owned locks, caches and long-lived thread registry."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from limn.security import access, people

Viewer = TypeVar("Viewer", covariant=True)
Scope = TypeVar("Scope", covariant=True)
Jobs = TypeVar("Jobs", covariant=True)
Share = TypeVar("Share", covariant=True)
Watch = TypeVar("Watch", covariant=True)
Tokens = TypeVar("Tokens", covariant=True)


@dataclass(frozen=True)
class RuntimeResources(Generic[Viewer, Scope, Jobs, Share, Watch, Tokens]):
    """Mutable resources owned by one server process, grouped by lifecycle."""

    viewer: Viewer
    scope_cache: Scope
    revision_jobs: Jobs
    pull_share: Share
    sync_watch: Watch
    token_cache: Tokens
    pin_lock: threading.RLock = field(default_factory=threading.RLock)
    people_lock: threading.Lock = field(default_factory=threading.Lock)
    events_lock: threading.Lock = field(default_factory=threading.Lock)
    people_seen: people.SeenMemo = field(default_factory=dict)
    people_warning: people.UnreadableWarning = field(default_factory=people.UnreadableWarning)
    events_cache: dict[Any, Any] = field(default_factory=dict)
    trash_checked: list[float] = field(default_factory=lambda: [0.0])
    tokens_cache: access.FileCache[list[dict[str, Any]]] = field(default_factory=access.FileCache)
    roles_cache: access.FileCache[access.PeopleRoles] = field(default_factory=access.FileCache)
    loopback_warning: access.WarnOnce = field(
        default_factory=lambda: access.WarnOnce(access.LOOPBACK_AGENT_DEPRECATION)
    )
    stopping: threading.Event = field(default_factory=threading.Event)
    threads: list[threading.Thread] = field(default_factory=list)

    def start_thread(self, target: Callable[..., object], *args: object) -> None:
        """Start and register one daemon that exits after ``stopping`` is set."""
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        self.threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop registered background work and join each thread once."""
        self.stopping.set()
        for thread in self.threads:
            thread.join(timeout)
