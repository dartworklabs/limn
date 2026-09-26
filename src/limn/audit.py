"""The audit log: <state>/audit.jsonl, one JSON object per destructive or owner action (docs/handbook/api.md §감사 기록).

events.jsonl keeps only the newest EVENTS_KEEP records, so ordinary notification traffic pushed out the record of who
cleared every pin (issue #10 L5). Destructive and owner actions are therefore also written here, one JSON object per
line, appended under a cross-process lock and never rewritten or truncated by Limn. The HTTP handler records clear and
purge (via "http"); the state helpers behind `limn token` / `limn member` record theirs as the OS account (via "cli").
The existing events (`cleared`, `purged`) are still written for compatibility. Old servers never open this file.

audit_entry() builds a line from values the caller passes (the clock included); append_audit() is the only writer of
the file. The module knows no run arguments, no HTTP and no server: the state directory comes in as an argument.
"""

from __future__ import annotations

import json
import os
import pwd
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from limn.files import store_lock

AUDIT_FILE = "audit.jsonl"
AUDIT_ACTIONS = ("cleared", "purged", "token_created", "token_revoked", "member_added", "member_removed", "member_role")
AUDIT_VIA = ("http", "cli")


def audit_entry(
    action: str, by: Mapping[str, Any] | None, via: str, details: Mapping[str, Any], now: float
) -> dict[str, Any]:
    """One audit.jsonl line: {at, ts, action, by, via, details}.

    at is the local wall-clock string of `now` (the shape now_str() writes), ts the same instant in epoch seconds; by
    keeps only {login, name} of the principal (name falls back to login). Raises ValueError for an action or via
    outside AUDIT_ACTIONS / AUDIT_VIA - a programming error, never a request error. Pure: the caller passes the clock."""
    if action not in AUDIT_ACTIONS:
        raise ValueError("unknown audit action %r" % action)
    if via not in AUDIT_VIA:
        raise ValueError("unknown audit channel %r" % via)
    login = (by or {}).get("login")
    return {
        "at": datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "ts": round(now, 3),
        "action": action,
        "by": {"login": login, "name": (by or {}).get("name") or login},
        "via": via,
        "details": dict(details),
    }


def append_audit(state: Path, entry: Mapping[str, Any]) -> bool:
    """Appends entry as one line to <state>/audit.jsonl under the cross-process lock (.audit.lock), then fsyncs.

    The file is opened O_APPEND, so earlier bytes are never rewritten - not even a line that does not parse - and it
    is created, or narrowed if it already exists, with mode 0600. It is never opened through a symlink. The action it
    records has already happened when this runs, so a failure only warns on stderr and returns False; callers do not
    undo or fail the action. Returns True once the line is on disk."""
    line = memoryview((json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
    path = Path(state) / AUDIT_FILE
    try:
        with store_lock(state, "audit"):
            fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                os.fchmod(fd, 0o600)
                while line:
                    line = line[os.write(fd, line) :]
                os.fsync(fd)
            finally:
                os.close(fd)
    except OSError as e:
        print("warning: failed to write %s: %s" % (path, e), file=sys.stderr)
        return False
    return True


def os_actor() -> dict[str, str]:
    """The local account running this process as an audit `by` {login, name}: who ran `limn token` / `limn member` on
    the server machine. Read from the password database by uid, not from $USER; "uid:<n>" if the uid has no entry."""
    uid = os.getuid()
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = "uid:%d" % uid
    return {"login": name, "name": name}
