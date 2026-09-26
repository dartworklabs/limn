"""Notices: <state>/events.jsonl and what a viewer's poll picks from it (docs/handbook/api.md §이벤트 (`events.jsonl`),
§브라우저 알림 커서).

events.jsonl is an append-only record of notices (mention, review_requested, replied, reopened, assigned, dropped, and
the audit notices cleared and purged) for the viewer's browser notifications and a future external integration to
read. Each record gets the next seq (seq only increases; consumers follow along by seq) and only the newest `keep`
records are kept. The file is written to a temp file under a lock and then os.replace'd (atomic) - readers only ever
see the old file or the new one.

Two parts:

- Pure: make_event() builds one notice and decides who it goes to; events_since() picks what one person's poll
  returns. They read no file and no clock.
- The file: EventLog appends notices (emit) and reads the records back (read, cached by the file's mtime/size).
  The composition root (server.event_log()) passes the path, the process's lock and cache, and the clock.

The module knows no run arguments, no HTTP and no server.
"""
from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from limn.files import atomic_write
from limn.mapping import truncate_quote

# One notice or events.jsonl record, a pin record, an actor or a thread post as read from JSON.
Row: TypeAlias = dict[str, Any]
# The file signature the read cache is keyed by: (path, st_mtime_ns, st_size).
Signature: TypeAlias = tuple[str, int, int]
# The process's read cache: {"v": (signature, records)}.
ReadCache: TypeAlias = dict[str, tuple[Signature, list[Row]]]

EVENTS_FILE = "events.jsonl"
EVENTS_KEEP = 5000                 # number of recent events kept in events.jsonl. seq only increases (consumers follow along by seq)
EVENT_TYPES = ("mention", "review_requested", "replied", "reopened", "assigned", "dropped")
NOTIFY_TYPES = ("mention", "review_requested", "replied", "reopened", "assigned", "dropped")
EVENTS_SINCE_MAX = 20
EXCERPT_CHARS = 140


# ---------------------------------------------------------------- Pure: building and picking notices

def excerpt(s: object, n: int = EXCERPT_CHARS) -> str:
    """s with whitespace/newlines collapsed to single spaces, truncated at n characters (with an ellipsis if cut)."""
    return truncate_quote(" ".join(str(s or "").split()), n)


def make_event(typ: str, r: Mapping[str, Any], actor: Mapping[str, Any], to: Iterable[str | None] | None,
               who: Callable[[Mapping[str, Any]], Row], doc_of: Callable[[Mapping[str, Any]], str], local_login: str,
               msg: Mapping[str, Any] | None = None, text: str | None = None) -> Row | None:
    """One events.jsonl record of type typ about pin record r (seq/at/ts are filled in by EventLog.emit), or None.

    to is deduplicated in order and loses empty logins, the actor themselves and local_login (the headerless agent);
    None (not recorded) if that leaves it empty. who gives the actor as recorded ({login, name}) and doc_of the pin's
    document; both are only asked when a notice is made. The record carries kind_req when the pin has one, msg (the
    thread post's id) when a post is given, and an excerpt of text - or of the post's text - when not empty."""
    me = (actor or {}).get("login")
    rcpt = [lg for lg in dict.fromkeys(to or []) if lg and lg != me and lg != local_login]
    if not rcpt:
        return None
    ev: Row = {"type": typ, "pin": r.get("id"), "doc": doc_of(r), "to": rcpt, "by": who(actor)}
    if r.get("kind_req"):
        ev["kind_req"] = r["kind_req"]
    if msg is not None:
        ev["msg"] = msg.get("id")
    ex = excerpt(text if text is not None else (msg or {}).get("text", ""))
    if ex:
        ev["excerpt"] = ex
    return ev


def last_seq(rows: Iterable[Mapping[str, Any]]) -> int:
    """The highest seq among the records, 0 for none."""
    return max((e.get("seq", 0) for e in rows), default=0)


def events_since(rows: list[Row], me: str | None, cursor: int | None, doc_names: Mapping[str, str]) -> Row:
    """Notification material carried in /api/meta polling (docs/handbook/api.md §브라우저 알림 커서).

    Always includes ev_seq (the latest event number). With a cursor (the parsed ev=<number>) it also includes
    `events`: up to EVENTS_SINCE_MAX records after it of a NOTIFY_TYPES type addressed to `me` and not by `me`, each
    with doc_name (its document's name from doc_names, else the doc key) - empty when me is None (local/agent or no
    login: nobody to notify). Pure: the caller reads the records."""
    out: Row = {"ev_seq": last_seq(rows)}
    if cursor is None:
        return out
    if not me:
        out["events"] = []
        return out
    evs = [_with_doc_name(e, doc_names) for e in rows
           if e.get("seq", 0) > cursor and e.get("type") in NOTIFY_TYPES and me in (e.get("to") or [])
           and (e.get("by") or {}).get("login") != me]
    out["events"] = evs[-EVENTS_SINCE_MAX:]
    return out


def _with_doc_name(e: Row, doc_names: Mapping[str, str]) -> Row:
    """A copy of record e with doc_name: the name doc_names gives its doc key, else the key itself (None if absent)."""
    doc: Any = e.get("doc")
    return dict(e, doc_name=doc_names.get(doc, doc))


# ---------------------------------------------------------------- The file

def _is_int(v: object) -> bool:
    """A JSON integer: an int, but not a bool."""
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class EventLog:
    """events.jsonl of one state directory, with the process's write lock and read cache.

    The composition root makes the lock and the cache once and passes them to every value it makes; the clock
    (epoch seconds and the local wall-clock string the notices carry) comes in the same way, so a frozen clock in a
    test reaches every record."""
    path: Path
    lock: threading.Lock
    cache: ReadCache
    now: Callable[[], float]
    stamp: Callable[[], str]

    def read(self) -> tuple[list[Row], Signature | None]:
        """(event list, file signature); ([], None) when the file cannot be stat'ed. Since polling reads this often,
        the cache is used when mtime/size are unchanged. Lines that are not JSON objects with an integer seq are
        skipped. Returns a new list each time (the records themselves are shared with the cache)."""
        try:
            st = self.path.stat()
        except OSError:
            return [], None
        sig = (str(self.path), st.st_mtime_ns, st.st_size)
        c = self.cache.get("v")
        if c and c[0] == sig:
            return list(c[1]), sig
        rows = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and _is_int(e.get("seq")):
                rows.append(e)
        self.cache["v"] = (sig, rows)
        return list(rows), sig

    def emit(self, events: Iterable[Row | None], keep: int = EVENTS_KEEP) -> None:
        """Appends events (Nones skipped) to the end of events.jsonl (lock + full atomic replace, leaving the earlier
        part untouched - append-only). seq starts from the file's last seq+1; each record gets seq, at (the stamp at
        that moment) and ts (the clock read once, rounded to milliseconds), in place. Only the newest `keep` records
        stay. Called only after the pin write has committed (prevents phantom events). A failure is just a warning -
        the pin change already went through."""
        batch = [e for e in events or [] if e]
        if not batch:
            return
        with self.lock:
            rows, _ = self.read()
            seq = last_seq(rows)
            now = self.now()
            for e in batch:
                seq += 1
                e.update(seq=seq, at=self.stamp(), ts=round(now, 3))
            rows = (rows + batch)[-keep:]
            try:
                atomic_write(self.path, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in rows))
            except OSError as e:
                print("warning: failed to write events.jsonl: %s" % e, file=sys.stderr)
