"""Which stored pin records the store accepts, parsed: one pins.jsonl or Trash line into its pin, or Broken
(docs/handbook/api.md §핀 레코드).

The store (limn.store.PinStore) trusts and indexes a few fields of every record - id, where the pin is, the thread
the viewer renders as-is - so a line whose fields do not have their stored shape is treated as broken: kept aside
with its original bytes, never served or rewritten. Checking id alone is not enough: a single record with a string
lo or no file turns every GET/POST into a 500, and because the pins.jsonl write commits right before that 500, a
retry creates a duplicate pin (observed).

A record that passes is parsed into its state type (limn.pins.model.parse_pin, or TrashedPin for a Trash entry), so
a reader of the store holds a typed pin whose shared fields the check has already vouched for: an integer id, a
place (a LineSpan or a Region), a thread of well-formed entries, and every optional field either missing, null or
of its stored kind.

Every optional field may be missing (a legacy record), and a field this version does not know passes untouched (an
older server must not drop what a newer one wrote, docs/adr/0005-pin-scoped-changes.md, 0006). The check changes
when a stored field is added or its shape changes - together with the records limn.pins.edit and
limn.pins.lifecycle write.

Pure. Two shapes it checks are owned by modules that are not: a document key (limn.documents.DOC_KEY_RE) and a
recorded actor (limn.people.is_actor). The composition root passes both in (server.parse_record).
"""

from collections.abc import Callable
from dataclasses import dataclass
from posixpath import isabs  # os.path.isabs on POSIX, the only platform Limn runs on - string work only
from typing import TypeGuard

from limn.pins.model import THREAD_EVENTS, Pin, TrashedPin, is_kind_req, is_region_pin, parse_pin
from limn.pins.shapes import is_int, is_num
from limn.scope import valid_changes


@dataclass(frozen=True)
class Broken:
    """A stored line the store does not trust: not JSON, not an object, or a field it checks has the wrong shape. The
    store skips it, reports its line number, and keeps the file's original bytes before its next rewrite."""


def parse_record(r: object, is_doc_key: Callable[[str], object], is_actor: Callable[[object], bool]) -> Pin | Broken:
    """The pin a parsed pins.jsonl line holds (its state type, every field lifted or kept as stored), or Broken when
    the store may not trust it (fits_record). Never raises and never changes r."""
    if not fits_record(r, is_doc_key, is_actor):
        return Broken()
    return parse_pin(r)


def parse_trashed(
    r: object, is_doc_key: Callable[[str], object], is_actor: Callable[[object], bool]
) -> TrashedPin | Broken:
    """The Trash copy a parsed pins.dropped.jsonl line holds (TrashedPin: the drop lifted, the rest the pin it was), or
    Broken by the same check as a live pin (fits_record: dropped_at is an *_at time, dropped_by a *_by actor)."""
    if not fits_record(r, is_doc_key, is_actor):
        return Broken()
    return TrashedPin.from_record(r)


def fits_record(
    r: object, is_doc_key: Callable[[str], object], is_actor: Callable[[object], bool]
) -> TypeGuard[dict[str, object]]:
    """Is r a pin record the store may trust? False if even one field it checks has the wrong shape.

    is_doc_key(s) is truthy when s is a document key (the stored `doc`; a document no longer configured is still a
    valid key, so its pins are not broken); is_actor(v) tells whether v is a recorded actor ({login, name, pic?}
    strings - author and every *_by). A view-only PDF's pin (is_region_pin) is placed by pdf (absolute path), page and
    frac instead of file/lo/hi. Never raises and never changes r."""
    if not isinstance(r, dict) or not is_int(r.get("id")):
        return False
    if r.get("doc") is not None and not (isinstance(r["doc"], str) and is_doc_key(r["doc"])):
        return False
    if is_region_pin(r):
        if not isabs(r["pdf"]) or not (is_int(r.get("page")) and r["page"] >= 1):
            return False
        if r.get("lo") is not None or r.get("hi") is not None:
            return False
        fr = r.get("frac")
        if not (isinstance(fr, list) and len(fr) == 4 and all(is_num(x) for x in fr)):
            return False
    else:
        if not isinstance(r.get("file"), str) or not r["file"]:
            return False
        lo, hi = r.get("lo"), r.get("hi")
        if not (is_int(lo) and is_int(hi) and 1 <= lo <= hi):
            return False
        if not isabs(r["file"]):  # a relative path would point at a different file depending on the server's cwd
            return False
    if "page" in r and not is_int(r["page"]):
        return False
    if "note" in r and r["note"] is not None and not isinstance(r["note"], str):
        return False
    for k in ("close_reply", "close_ref"):
        if r.get(k) is not None and not isinstance(r[k], str):
            return False
    if r.get("changes") is not None and not valid_changes(r["changes"]):
        return False
    # The new fields (kind_req/thread/mentions/review) are all optional. The viewer renders them as-is, so a malformed shape is treated as a broken line.
    if r.get("kind_req") is not None and not is_kind_req(r["kind_req"]):
        return False
    if r.get("mentions") is not None and not _is_str_list(r["mentions"]):
        return False
    if r.get("assignee") is not None and not (isinstance(r["assignee"], str) and r["assignee"]):
        return False
    if r.get("thread") is not None and not _valid_thread(r["thread"], is_actor):
        return False
    if "anchor" in r and not isinstance(r["anchor"], dict):
        return False
    for k in ("raw_lo", "raw_hi", "rev"):
        if r.get(k) is not None and not is_int(r[k]):
            return False
    # epoch seconds - named apart from '*_at' (string timestamps)
    for k in ("synced_at", "score", "claim_until", "claim_ts", "eta_ts"):
        if r.get(k) is not None and not is_num(r[k]):
            return False
    for k in ("done", "stale", "review"):
        if r.get(k) is not None and not isinstance(r[k], bool):
            return False
    for k in ("name", "kind", "via", "scope", "sync", "pdf_build", "frac_build", "file_rel"):
        if r.get(k) is not None and not isinstance(r[k], str):
            return False
    for k, v in r.items():
        if k == "at" or k.endswith("_at") and k != "synced_at":
            if v is not None and not isinstance(v, str):
                return False
        elif (k == "author" or k.endswith("_by")) and v is not None and not is_actor(v):
            return False
    fr = r.get("frac")
    return fr is None or (isinstance(fr, list) and len(fr) == 4 and all(is_num(x) for x in fr))


def _is_str_list(v: object) -> TypeGuard[list[str]]:
    """A list of strings - how mentions (logins) are stored."""
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _valid_thread(th: object, is_actor: Callable[[object], bool]) -> bool:
    """thread = [{id, by, at, text, ev?, ref?, mentions?}] - the viewer renders by.name/text as-is, so every entry
    needs an integer id, text and at strings and a recorded actor (is_actor); ev, when present, is a THREAD_EVENTS
    mark."""
    if not isinstance(th, list):
        return False
    for m in th:
        if not isinstance(m, dict) or not is_int(m.get("id")) or not isinstance(m.get("text"), str):
            return False
        if not isinstance(m.get("at"), str) or not is_actor(m.get("by")):
            return False
        if m.get("ev") is not None and m["ev"] not in THREAD_EVENTS:
            return False
        if m.get("ref") is not None and not isinstance(m["ref"], str):
            return False
        if m.get("mentions") is not None and not _is_str_list(m["mentions"]):
            return False
    return True
