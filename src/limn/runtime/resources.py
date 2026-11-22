"""Process-owned locks, caches and long-lived thread registry."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from limn.platform.effects import require_writer
from limn.security import access, people_store as people
from limn.security.access_store import AccessFile, UnusableWarning

Viewer = TypeVar("Viewer", covariant=True)
Scope = TypeVar("Scope", covariant=True)
Jobs = TypeVar("Jobs", covariant=True)
Share = TypeVar("Share", covariant=True)
Watch = TypeVar("Watch", covariant=True)
Tokens = TypeVar("Tokens", covariant=True)
Maps = TypeVar("Maps", covariant=True)
Lines = TypeVar("Lines", covariant=True)
Pages = TypeVar("Pages", covariant=True)


@dataclass(frozen=True)
class RuntimeResources(Generic[Viewer, Scope, Jobs, Share, Watch, Tokens, Maps, Lines, Pages]):
    """Mutable resources owned by one server process, grouped by lifecycle. The feature resources (viewer ...
    page_folders) are typed by the composition root, which makes them; this module imports no feature. pin_lines is
    what the run's read-only pin readers keep of the pin files' lines (limn.pins.store.PinLines), and page_folders
    what its build queries keep of the page folders on screen (limn.builds.artifacts.PageFolderCache): each is memory
    only, bounded where it is defined, gone with the run and never shared between two runs."""

    viewer: Viewer
    scope_cache: Scope
    revision_jobs: Jobs
    pull_share: Share
    sync_watch: Watch
    token_cache: Tokens
    figure_maps: Maps
    pin_lines: Lines
    page_folders: Pages
    pin_lock: threading.RLock = field(default_factory=threading.RLock)
    people_lock: threading.Lock = field(default_factory=threading.Lock)
    events_lock: threading.Lock = field(default_factory=threading.Lock)
    people_seen: people.SeenMemo = field(default_factory=dict)
    people_warning: people.UnreadableWarning = field(default_factory=people.UnreadableWarning)
    events_cache: dict[Any, Any] = field(default_factory=dict)
    trash_checked: list[float] = field(default_factory=lambda: [0.0])
    tokens_cache: access.FileCache[list[dict[str, Any]]] = field(default_factory=access.FileCache)
    roles_cache: access.FileCache[access.PeopleRoles] = field(default_factory=access.FileCache)
    access_cache: access.FileCache[AccessFile] = field(default_factory=access.FileCache)
    access_warning: UnusableWarning = field(default_factory=UnusableWarning)
    loopback_warning: access.WarnOnce = field(
        default_factory=lambda: access.WarnOnce(access.LOOPBACK_AGENT_DEPRECATION)
    )
    stopping: threading.Event = field(default_factory=threading.Event)
    threads: list[threading.Thread] = field(default_factory=list)

    def start_thread(self, target: Callable[..., object], *args: object) -> None:
        """Start and register one daemon that exits after ``stopping`` is set."""
        require_writer()
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        self.threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop registered background work and join each thread once."""
        self.stopping.set()
        for thread in self.threads:
            thread.join(timeout)
