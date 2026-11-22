"""The instance access flag: <state>/access.json.

While the flag is on, people.json is the source of truth for who is admitted and the owner manages members from the
viewer. This module holds only the file: its read (read_access), its stored text (access_text) and its write
(write_access). It knows no run arguments, no HTTP and no admission rule; the caller decides what the flag means.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from limn.platform.files import atomic_write
from limn.security.values import ManagedAccess


@dataclass(frozen=True)
class AccessFile:
    """What access.json says. `managed` is "managed" or "not-managed" for a usable file (or none), and "unusable" for
    a file that exists but cannot be used; `reason` then names the file and why, as the server's warning shows it.
    `at` and `by` are the stamp and actor of the last change, when the file records them."""

    managed: ManagedAccess
    at: str | None
    by: str | None
    reason: str | None


def _unusable(reason: str) -> AccessFile:
    """An AccessFile for a file that exists but cannot be used."""
    return AccessFile("unusable", None, None, reason)


def _text_or_none(value: object) -> str | None:
    """value when it is a string, else None (a stamp or actor that is not text is left out, not an error)."""
    return value if type(value) is str else None


class _Object(dict[str, object]):
    """A JSON object as _parse makes it. The subclass lets `type(d) is _Object` tell one from a list or a string and
    leaves a fully typed dict behind, with no cast and no isinstance."""


def _pairs(items: list[tuple[str, object]]) -> _Object:
    """json.loads hook: every JSON object becomes an _Object."""
    return _Object(items)


_loads: Callable[..., object] = json.loads


def _parse(text: str) -> object:
    """text as parsed JSON, its objects as _Object; ValueError when it is not JSON."""
    return _loads(text, object_pairs_hook=_pairs)


def read_access(path: Path) -> AccessFile:
    """The access flag at path. Same split as limn.security.people.load_people: a file that does not exist is the
    ordinary "not managed" (nothing was ever switched on); a file that exists but cannot be used - it cannot be read,
    is not UTF-8 JSON, is not an object, has a `version` other than 1, or a `managed` that is not a boolean - is
    "unusable" with a reason naming the file. Never raises for a bad file."""
    try:
        d = _parse(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AccessFile("not-managed", None, None, None)
    except (OSError, ValueError) as e:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        return _unusable("cannot read %s: %s" % (path, e))
    if type(d) is not _Object:
        return _unusable("%s is not a Limn access file" % path)
    doc: dict[str, object] = d
    version, managed = doc.get("version"), doc.get("managed")
    if type(version) is not int or version != 1 or not (managed is True or managed is False):
        return _unusable("%s is not a Limn access file" % path)
    return AccessFile(
        "managed" if managed else "not-managed",
        _text_or_none(doc.get("managed_at")),
        _text_or_none(doc.get("managed_by")),
        None,
    )


class UnusableWarning:
    """The stderr warning about an unusable access.json, printed once per breakage: the first read that finds the file
    unusable warns, later ones stay quiet, and a good read re-arms it so a new breakage warns again. The running
    server owns one for the process (RuntimeResources.access_warning), like people.UnreadableWarning. Thread-safe."""

    def __init__(self) -> None:
        """The file is not known to be broken yet."""
        self._lock: threading.Lock = threading.Lock()
        self._broken: bool = False

    def note(self, read: AccessFile) -> None:
        """Record what a read gave: warn for an unusable file unless this breakage was warned about already; forget
        the breakage after a good read."""
        with self._lock:
            if read.managed != "unusable":
                self._broken = False
                return
            if self._broken:
                return
            self._broken = True
        print(
            "warning: %s - every person a header identifies is refused (access_unreadable) until it is fixed or "
            "removed" % read.reason,
            file=sys.stderr,
        )


def access_text(managed: bool, at: str, by: str) -> str:
    """The stored text of access.json: {"version": 1, "managed", "managed_at", "managed_by"}, one-space indent,
    non-ASCII kept, ending in a newline."""
    doc = {"version": 1, "managed": managed, "managed_at": at, "managed_by": by}
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def write_access(path: Path, managed: bool, at: str, by: str) -> None:
    """Writes the access file at path (RunConfig.access_file) atomically with mode 0600. Takes no lock: the caller
    holds store_lock(state, "people"), the cross-process lock that serialises the flag against people.json.
    Raises OSError when the write fails."""
    atomic_write(path, access_text(managed, at, by), mode=0o600)
