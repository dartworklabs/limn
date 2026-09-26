#!/usr/bin/env python3
"""Limn — a local viewer that maps a dragged region of a manuscript PDF back to .tex line numbers.

The goal is to hand an agent a "file:line-range" instead of a screenshot. A single
image runs 1-2 thousand tokens, while a line range is a few dozen, and more
importantly the agent can read and fix the line directly - a screenshot forces a
round trip just to relocate it.

The reverse mapping pits two paths against each other **on equal footing**. A SyncTeX
coordinate lookup is the primary path, and recovering the characters inside the
selected region from the source text is the secondary one. Treating either as a
conditional fallback leaves no way to catch SyncTeX being silently wrong - this
actually happens inside minipage/tabular (e.g. Nomenclature).

The server binds 127.0.0.1 by default and external exposure is handled by tailscale
serve. Who a request is comes from an identity provider (--auth): `tailscale` (the
default - the Tailscale-User-Login/Name/Profile-Pic headers tailscale serve adds,
trusted from a loopback peer only), `local` (a single user on their own machine) or
`trusted-proxy` (headers set by an authenticating reverse proxy). Agents authenticate
with API tokens (`limn token create`), and people.json roles decide what a person may
change. Binding anything but loopback requires `trusted-proxy` or an explicit
--i-know-this-is-insecure (docs/adr/0002-access-control.md, SECURITY.md).

Python 3.10 standard library only.
"""

from __future__ import annotations

import argparse
import dataclasses
import html
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import quote

if __package__ in (None, ""):
    # Run as a file (python .../limn/server.py, how instances start): make the sibling modules importable as limn.*.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# The limn.* modules this composition root wires together. The pin services (add_edit, claim, trash, transitions) are
# wired by pin_context(); pins.md's renderer gets its input from pins_md_input(); the run settings' type, the startup
# rules and the command line fill in C (main() -> start() below). `X as X` marks a name this module exports as an App
# member (web/app.py) - mypy's explicit re-export, so the App check at the Handler sees it: the page directory on screen
# and a build's PDF (limn.build's own functions, bound here without a shell), is_agent, outline_labels, pin_state,
# revision_history, hdr_text (the handler quotes a refused Host/Origin/document key through it), APP_NAME and
# app_version. The build state is bound by assignment below the imports, because an import under another name is
# never an export. meta_reads is the module; meta() below is the App member that binds it. record is the store's
# record check; valid_rec() below binds it.
from limn import (
    access,
    build,
    documents,
    events,
    gitsync,
    locate,
    meta as meta_reads,
    people,
    revisions,
    startup,
)
from limn.access import (
    DEFAULT_ROLE as DEFAULT_ROLE,
    LOCAL_ACTOR,
    LOOPBACK_AGENT_DEPRECATION,
    file_present,
    hdr_text as hdr_text,
    home_or_none,
    load_tokens,
    roles_of,
)
from limn.args import serve_parser
from limn.audit import append_audit, audit_entry, os_actor
from limn.build import (
    BuildConfig,
    BuildResult,
    build_pdf as build_pdf,
    cur_pages as cur_pages,
    pdf_changed,
)
from limn.config import Cfg
from limn.documents import (
    DEFAULT_DOC_KEY,
    DOC_KEY_RE,
    Doc,
    DocNotFound,
    DocumentFacts,
)
from limn.events import EVENTS_KEEP
from limn.files import tex_lines, vendor_file as find_vendor_file
from limn.guidance import shell_path
from limn.locate import PinLocation, est_context, locate_file
from limn.mark import favicon_svg, inline_svg
from limn.mentions import (
    NoteTags,
    addressed_to,
    fyi_mentions_to,
    note_mention_targets,
    tag_note,
    thread_round,
)
from limn.meta import MetaSettings, outline_labels as outline_labels
from limn.people import is_actor as _is_actor
from limn.pins import record, view
from limn.pins.edit import AddRequest, EditRefusal, EditRequest
from limn.pins.lifecycle import (
    AgentCannotConfirm,
    AlreadyClosed,
    AlreadyDone,
    AlreadyLive,
    ClaimClosedPin,
    ClaimedByOther,
    NotClaimed,
    NotInTrash,
    PinStillOpen,
    ThreadFull,
    claim_holds,
    pin_reopened_in_round,
    reopens_on_reply,
)
from limn.pins.model import (
    DonePin,
    OpenPin,
    PinNotFound,
    Record,
    ReviewPin,
    TrashedPin,
    is_region_pin,
    parse_pin,
)
from limn.pins.position import EstContext
from limn.pins.record import is_int
from limn.pins.render import (
    DocHeading,
    PinFacts,
    PinsMdInput,
    pins_md_text as render_pins_md_text,
    rel_badge,
)
from limn.pins.view import pin_state as pin_state
from limn.revisions import (
    DiffRefusal,
    PdfRefusal,
    StartRefusal,
    StatusRefusal,
    git as _git,
    revision_history as revision_history,
)
from limn.service import add_edit, claim, transitions, trash
from limn.service.context import Event, Json, PinContext, is_agent as is_agent, who
from limn.startup import APP_NAME as APP_NAME, StartupRefused, app_version as app_version
from limn.store import PinFiles, PinStore, Row, find_pin
from limn.viewer.assemble import (
    LUCIDE,
    PDFJS_VERSION,
    VIEWER_DIR,
    load_ui_messages,
    service_worker,
    viewer_html,
)
from limn.web.errors import HTTPError, Messages, revision_failure_text
from limn.web.handler import Handler as WebHandler, Server, Server6
from limn.web.parse import CloseChange

build_state_snapshot = build.state_snapshot


# The viewer's ko -> en message table: the viewer page embeds it, and the handler's refusal page reads it (App.UI_EN).
UI_EN: Messages = load_ui_messages(Path(__file__).with_name("ui_en.json"))

DEFAULT_ENVS = "figure,table,algorithm,equation,align,itemize,enumerate,minipage"

# The settings the pin services get from this instance (pin_context), module globals so a test can patch them. The
# rules they bound live with the rules: the request limits in limn/web/parse.py, NOTE_MAX and KIND_REQS in
# limn/pins/edit.py, the thread marks a record may carry in limn/pins/record.py, PEOPLE_TOUCH_S in limn.people,
# EVENTS_KEEP in limn.events, NOTE_MENTION_COOLDOWN_S in limn.mentions (docs/handbook/api.md §스레드, §@태그·사람·이벤트).
THREAD_MAX = 200  # cap on one pin's thread (replies). State-transition records (close/reopen/confirm) are appended regardless of this cap
TRASH_DAYS = 30  # a dropped pin stays in the Trash (pins.dropped.jsonl) this long, then is purged for good

# The pin store's lock (limn.store.PinStore.lock): every path that touches the pin files goes through this single
# re-entrant lock. The store creates no lock, so the process makes its one here and pin_store() passes it on.
PIN_LOCK = threading.RLock()
# If two latexmk runs share the same build/, they trample each other's .aux.
BUILD_LOCK = threading.Lock()
# Guards the BUILD_STATE dict (progress chip / error panel). Separate from BUILD_LOCK (only one build at
# a time) - this lock exists just so that state doesn't race with the GET /api/build request that "reads" it.
BUILD_STATE_LOCK = threading.Lock()
BUILD_STATE: dict[str, Any] = {
    "state": "idle",
    "phase": None,
    "started_at": None,
    "start_ts": None,
    "last_s": None,
    "pages": 0,
    "errors": [],
    "log_tail": "",
    "built_at": None,
    "seq": 0,
    "finished_at": None,
    "last": None,
    "head": None,
    "pull": None,
}
# Bundles the read-modify-write of builds.json (build history).
BUILDS_LOCK = threading.Lock()


C = Cfg()
# A transaction step's result type (transact).
T = TypeVar("T")


# ---------------------------------------------------------------- Documents (§Multiple documents, docs/handbook/domain.md §여러 문서)
#
# A document (limn.documents.Doc) is always an argument: the handler finds the request's (request_doc) and passes it
# on, a build thread gets its own, and startup walks the list. The list itself (DOCS, the first document is the
# default) is this composition root's; a Doc reads the run paths through the C it is given at construction.


def now_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- Instance label (§Running multiple manuscript instances at once)


def favicon_href(accent: str) -> str:
    """The Limn mark (limn.mark) as an SVG data URL: the tile in the instance accent (#rrggbb), the glyph white. The
    accent tells tabs of different instances apart; the tab title carries the label. Quote-encoded for data:."""
    return "data:image/svg+xml," + quote(favicon_svg(accent), safe="")


def build_html(label: str, accent: str) -> str:
    """Fills in the __LABEL__/__ACCENT__/__ACCENT_KEY__/__FAVICON_HREF__ placeholders of the viewer HTML template.

    Depends on run arguments (label/accent), so it's called after argparse (in main()) - unlike
    __PDFJS_VERSION__, which is fixed at module-load time, this one only has a value once C is filled in.
    __ACCENT_KEY__ (the accent's hex digits) keys the PNG favicon URLs, so a new accent is never served from a cache."""
    out = HTML.replace("__LABEL__", html.escape(label, quote=True))
    out = out.replace("__ACCENT_KEY__", accent.lstrip("#").lower())
    out = out.replace("__ACCENT__", accent)
    out = out.replace("__FAVICON_HREF__", favicon_href(accent))
    return out


# ---------------------------------------------------------------- Page-image version directories and the build
#
# The build - page directories, build state, the LaTeX build, history, fingerprint - lives in limn/build.py and
# takes the document and the settings it needs as arguments (docs/handbook/build-sync.md). Callers here pass the
# document they act on and the run settings; only the tracked build (build_all/build_async) is wired here, because
# it binds the instance's BuildConfig, --git-pull and the view-only render. The PDF.js directory the viewer's vector
# renderer is served from is bound here too; the name check of a file in it is limn.files.vendor_file.


def default_pdfjs_dir() -> Path:
    """The PDF.js bundled with the package (limn/vendor/pdfjs)."""
    return Path(__file__).resolve().parent / "vendor" / "pdfjs"


def vendor_file(name: str) -> Path | None:
    """The file GET /vendor/pdfjs/<name> serves from this instance's PDF.js directory (--pdfjs-dir, else the bundled
    one), or None (limn.files.vendor_file: a single .mjs name that stays inside the directory)."""
    return find_vendor_file(C.pdfjs_dir or default_pdfjs_dir(), name)


# ---------------------------------------------------------------- Build
#
# The agent response's log diet (?log=1 for the full log) is the HTTP layer's: limn.web.answers.diet_log.


def build_config() -> BuildConfig:
    """The build settings from the run arguments. Made per build, so a test (or main()) that changes C is seen at once."""
    return BuildConfig(state=C.state, dpi=C.dpi, timeout=C.timeout)


def build_all(D: Doc) -> BuildResult:
    """POST /api/rebuild for document D: build it now (synchronous). If it is already building, returns busy without
    waiting (limn.build.build_now)."""
    return build.build_now(D, lambda: _build_tracked(D))


def build_async(D: Doc) -> Json:
    """POST /api/rebuild?async=1 for document D: start the tracked build on a daemon thread
    (limn.build.build_in_background); the thread builds D itself."""
    return build.build_in_background(D, lambda: _build_tracked(D), now_str())


def _build_tracked(D: Doc) -> BuildResult:
    """One tracked build of D: LaTeX (_build) or, for view-only, the page render (limn.build.render_pdf_doc)
    (limn.build.run_tracked). The step is looked up when the build runs, so a test that replaces _build sees it."""
    step = (lambda: build.render_pdf_doc(D, build_config())) if D.is_pdf else (lambda: _build(D))
    return build.run_tracked(D, C.state, step, now_str())


# ---------------------------------------------------------------- Manuscript history, pin-scoped changes, comparison PDFs
#
# The revision services are limn/revisions.py (the git edge and the comparison builds) and limn/scope.py (the pure
# attribution of a commit's hunks to a pin, ADR-0005). They take the document and a RevisionContext and return
# outcome values; limn.web.answers answers them. What the instance supplies is wired here: the process's one scope
# cache and job registry, the pins as the API shows them, where a recorded path is now, and the texts a failed
# comparison records (limn.web.errors, the same table as the HTTP answers).

SCOPE_CACHE = revisions.ScopeCache()  # the process's pin scopes (commits are immutable, so entries stay right)
REVISION_JOBS = revisions.RevisionJobs()  # the process's running comparison builds and their two slots


def revision_context() -> revisions.RevisionContext:
    """The revision services' view of this instance, made per request like pin_store(), so a test (or main()) that
    changes C is seen at once."""
    root = C.src

    def locate(file: str, D: revisions.RevisionDoc) -> Path | None:
        """Where a recorded change's path of document D is under the manuscript root now (locate_file, issue #24)."""
        loc = locate_file(file, None, root, D)
        return loc.path if loc is not None else None

    return revisions.RevisionContext(
        timeout=C.timeout,
        pins=lambda: [public(r) for r in read_pins()[0]],
        doc_of=pin_doc_key,
        locate=locate,
        cache=SCOPE_CACHE,
        jobs=REVISION_JOBS,
        describe=revision_failure_text,
    )


def revision_diff(D: Doc, commit: str, pin: int | None = None) -> Json | DiffRefusal:
    """GET /api/revision-diff for document D (limn.revisions.revision_diff with this instance's context)."""
    return revisions.revision_diff(D, commit, pin, revision_context())


def revision_status(D: Doc, commit: str, pin: int | None = None) -> Json | StatusRefusal:
    """GET /api/revision-build for document D (limn.revisions.revision_status)."""
    return revisions.revision_status(D, commit, pin, revision_context())


def revision_start(D: Doc, commit: str, pin: int | None = None) -> Json | StartRefusal:
    """POST /api/revision-build for document D (limn.revisions.revision_start)."""
    return revisions.revision_start(D, commit, pin, revision_context())


def revision_pdf(D: Doc, commit: str, pin: int | None = None) -> bytes | PdfRefusal:
    """GET /api/revision-pdf for document D (limn.revisions.revision_pdf)."""
    return revisions.revision_pdf(D, commit, pin, revision_context())


# ---------------------------------------------------------------- --git-pull and the remote-main watch (docs/handbook/build-sync.md §재빌드 전 원격 main 당겨오기)
#
# Fast-forwards the manuscript repo to the remote main before the rebuild's copy step, and watches remote main while
# the server runs. A co-author merging a PR wasn't reflected on the server-side checkout - the viewer kept showing the
# old manuscript. Even on failure (dirty tree, diverged, no upstream), the build itself continues with the current
# checkout - a pull is nice to have, not a build prerequisite.
#
# The pull and the watch are limn/gitsync.py (the git calls, locks and watch loop) over limn/pull.py (what git's
# answers mean and what the watch does next). The process's one pull share and watch status are made here; the
# bindings below hand them the manuscript folder, the documents, --git-pull, the git runner (limn.revisions.git
# imported above as _git: no shell, 30 seconds per call), the clock and the build starter, read per call so a test (or
# main()) that changes C or rebinds build_async is seen at once. prepare() starts the watch thread.

PULL_SHARE = gitsync.PullShare()  # the process's one pull per repository and its last result
SYNC_WATCH = gitsync.SyncWatch()  # the remote-main watch status GET /api/meta shows as `sync`


def repo_pull() -> Json:
    """A build's --git-pull, as its `pull` record (limn.gitsync.repo_pull): one document pulls on every build; several
    share one pull per repository within limn.gitsync.PULL_SHARE_S."""
    return gitsync.repo_pull(PULL_SHARE, multi_doc(), lambda: gitsync.pull(C.src, main_only=False, git=_git), time.time)


def sync_status() -> Json:
    """GET /api/meta's `sync` - the remote-main watch status (limn.gitsync.SyncWatch.status)."""
    return SYNC_WATCH.status(DOCS, C.git_pull)


def sync_main_once() -> Json:
    """One remote-main round (limn.gitsync.SyncWatch.once): pull main, then start the builds of the documents the
    pull left behind. The watch thread runs it, and a --no-build startup through it."""
    return SYNC_WATCH.once(
        DOCS,
        C.git_pull,
        lambda: gitsync.pull(C.src, main_only=True, git=_git),
        PULL_SHARE,
        build_async,
        gitsync.local_stamp,
        time.time,
    )


def _build(D: Doc) -> BuildResult:
    """The LaTeX build of document D with this instance's settings; --git-pull pulls first (limn.build.compile_tex)."""
    return build.compile_tex(D, build_config(), repo_pull if C.git_pull else None)


# ---------------------------------------------------------------- Documents and meta
#
# The document list (DOCS, the first is the default) is this composition root's. The lookups over it are
# limn.documents' and the polled reads (GET /api/meta, /api/docs, /api/outline-labels) limn.meta's; each takes the
# list and the run settings as arguments, bound here.

# [C.src string, value, measured-at time] - a 2-second cache (for a single document)
_SRC_MTIME_CACHE: list[Any] = [None, 0.0, 0.0]
# Single document (no --doc). Holds the module-global lock/state as-is, so the object the legacy code paths
# and regression tests see is exactly this document's.
LEGACY_DOC = Doc(
    DEFAULT_DOC_KEY,
    "본문",
    legacy=True,
    lock=BUILD_LOCK,
    bstate=BUILD_STATE,
    bstate_lock=BUILD_STATE_LOCK,
    builds_lock=BUILDS_LOCK,
    mcache=_SRC_MTIME_CACHE,
    paths=C,
)
DOCS: list[Doc] = [LEGACY_DOC]


def set_docs(docs: Iterable[Doc] | None = None) -> None:
    """Change the document list (main()/tests). Reverts to a single document when empty."""
    DOCS[:] = list(docs) if docs else [LEGACY_DOC]


def multi_doc() -> bool:
    return len(DOCS) > 1


def doc_by_key(key: object) -> Doc | None:
    """The document of this instance whose key is `key`, or None (limn.documents.doc_by_key)."""
    return documents.doc_by_key(DOCS, key)


def pin_doc_key(r: Record) -> str:
    """The document key a pin belongs to; a legacy record without a doc field is the first document's
    (limn.documents.pin_doc_key)."""
    return documents.pin_doc_key(r, DOCS)


def meta_settings() -> MetaSettings:
    """The run settings GET /api/meta reads, made per request like pin_store(), so a test (or main()) that changes C is
    seen at once."""
    return MetaSettings(
        state=C.state,
        pins_md=C.pins_md,
        pins_jsonl=C.pins_jsonl,
        label=C.label,
        accent=C.accent,
        repo=C.repo,
        dpi=C.dpi,
    )


def docs_payload() -> Json:
    """GET /api/docs — the document list and open-pin counts per document. Pins are only read (no sync write)."""
    rows, _ = read_pins()
    return meta_reads.docs_payload(DOCS, rows, pin_doc_key, C.state)


def meta(D: Doc, actor: Json, light: bool = False) -> Json:
    """GET /api/meta for document D: its pages, builds, staleness and settings for the viewer (limn.meta.meta); with
    light (polling) the pin counts are left out, and with them the sync write of snapshot_pins()."""
    out = meta_reads.meta(D, actor, meta_settings(), DOCS, sync_status(), time.time())
    if light:  # polling only - skips the sync write in snapshot_pins()
        return out
    out.update(meta_reads.pin_counts([pin_state(r) for r in snapshot_pins()]))
    return out


# ---------------------------------------------------------------- Pin store
#
# Which stored records the store trusts is limn/pins/record.py's check; valid_rec binds it to the document key format
# (limn.documents) and the recorded actor's shape (limn.people), which it cannot import and stay pure.


def valid_rec(r: object) -> bool:
    """The store's record check (limn.pins.record.valid_rec) with DOC_KEY_RE and limn.people.is_actor: is r a pin
    record the store may trust? A record failing it is a broken line."""
    return record.valid_rec(r, DOC_KEY_RE.fullmatch, _is_actor)


def pin_location(r: Record, root: Path) -> PinLocation | None:
    """Where line pin r's file is under the manuscript root on this machine now (limn.locate.pin_location, the tail
    guess limited to the folder of the pin's own document), or None."""
    return locate.pin_location(r, root, doc_by_key(pin_doc_key(r)))


def stamp_location(r: Row, root: Path) -> PinLocation | None:
    """Records in r where its file is now (limn.locate.stamp_location, the pin's own document). Mutates r."""
    return locate.stamp_location(r, root, doc_by_key(pin_doc_key(r)))


def pin_locator() -> locate.Locator:
    """pin_location() bound to this instance's manuscript root, read now."""
    root = C.src
    return lambda r: pin_location(r, root)


def sync_all(rows: list[Row]) -> bool:
    """The store's re-sync (PinStore.sync): stored pins' lines follow their anchors in the .tex files as this instance
    finds them now (limn.locate.sync_all)."""
    return locate.sync_all(rows, pin_locator())


def pin_store() -> PinStore:
    """The pin store (limn.store) over the current run arguments - where the composition root wires it.

    Made per call, like build_config(), so a test or main() that changes C.state is seen at once; the lock is the one
    process-wide PIN_LOCK. The collaborators are looked up at call time: the record check valid_rec, the anchor re-sync
    sync_all (reads the .tex files under C.src), the renderer pins_md_text, and HTTPError as a step's refusal."""
    return PinStore(PinFiles(C.state), PIN_LOCK, valid_rec, sync_all, pins_md_text, HTTPError)


# The pin store under its old names - the many call sites (transact(fn) everywhere) keep calling these, and each
# delegates to pin_store(). The contracts are the store's methods of the same name.


def read_jsonl(path: Path) -> tuple[list[Row], list[int]]:
    """(records, broken line numbers) of a JSONL file (PinStore.read_jsonl)."""
    return pin_store().read_jsonl(path)


def read_pins() -> tuple[list[Row], list[int]]:
    """The live pins and pins.jsonl's broken line numbers, lock-free and not re-synced (PinStore.read_pins)."""
    return pin_store().read_pins()


def write_pins(rows: list[Row], bad: list[int] | None = None) -> None:
    """Rewrites pins.jsonl then pins.md; nothing if rendering fails (PinStore.write_pins). Callers hold PIN_LOCK."""
    pin_store().write_pins(rows, bad)


def transact(fn: Callable[[list[Row]], tuple[T, bool]]) -> tuple[list[Row], T]:
    """Write-order invariant: with PIN_LOCK -> read -> sync -> apply the request's change -> atomic write -> pins.md.

    fn(rows) returns (result, whether it mutated); returns (rows, result). See PinStore.transact."""
    return pin_store().transact(fn)


def snapshot_pins() -> list[Row]:
    """The live pins, re-synced and written back if that changed them (PinStore.snapshot)."""
    return pin_store().snapshot()


def public(r: Record) -> Json:
    """A record as the API returns it (limn.pins.view.public_record), placed where pin_location() finds its file under
    the manuscript root now: `file` the absolute path on this machine, `rel_path` relative to the root (ADR-0006).
    Never changes r."""
    loc = pin_location(r, C.src)
    return view.public_record(r, None if loc is None else (str(loc.path), loc.rel))


# ---------------------------------------------------------------- Computed fields of GET /api/pins, and overlap
#
# What GET /api/pins and GET /api/pins/dropped add to the stored records is limn.pins.view's (pure; pin_state, an App
# member, is imported as it is). Overlap is limn.locate's, counting each pin in the file this instance finds for it
# now. Here both are bound to this instance: how a record is shown (public), a pin's document, each document's build
# history (limn.locate.est_context), the pin locator, the stored pins and the clock.


def pins_payload(rows: list[Row], allp: bool) -> list[Json]:
    """GET /api/pins response (limn.pins.view.pins_payload): stored records + the computed fields rel (overlap), est
    (location estimated), doc, state, addressed, fyi. None of these are stored."""
    return view.pins_payload(rows, allp, overlaps_by_id(rows), public, pin_doc_key, _doc_est_context, time.time())


def _doc_est_context(key: str) -> EstContext | None:
    """What estimation reads of the builds of the document key names (limn.locate.est_context), or None when this
    instance no longer serves that document."""
    D = doc_by_key(key)
    return None if D is None else est_context(D)


def dropped_payload(now: float | None = None) -> list[Json]:
    """GET /api/pins/dropped response - the Trash (limn.pins.view.dropped_payload): pins.dropped.jsonl ordered by
    dropped_at, each entry with `expires_ts`, without entries older than TRASH_DAYS (hidden here, removed from the file
    by the next purge_trash()).

    Read-only and outside the lock - dropping/restoring already hold PIN_LOCK while writing this file
    (drop_pin/restore_pin). Since only a file that has finished an atomic replace (atomic_write) is ever
    read here, no separate lock is needed to avoid seeing a half-written file."""
    return view.dropped_payload(_unexpired(read_jsonl(C.dropped)[0], now), public, trash_expires_ts)


def overlaps_by_id(rows: Sequence[Row]) -> dict[int, list[Json]]:
    """The relationship of every pair of open line pins on the same file, each counted where pin_location() places it
    now (limn.locate.overlaps_by_id), never stored."""
    return locate.overlaps_by_id(rows, pin_locator())


def overlaps_for_range(file: str, lo: int, hi: int) -> list[Json]:
    """The overlap relationships between a not-yet-saved range of file and that file's open pins, as re-synced now
    (limn.locate.overlaps_for_range). Nothing is saved."""
    return locate.overlaps_for_range(file, lo, hi, snapshot_pins(), pin_locator())


# ---------------------------------------------------------------- Pin ids


def init_seq() -> None:
    """If pins.seq is missing, fill it once from the max id across the current, archived, and dropped records (PinStore.init_seq)."""
    pin_store().init_seq()


def next_id(rows: list[Row]) -> int:
    """An id is never reused - hands out the next one and records it in pins.seq (PinStore.next_id)."""
    return pin_store().next_id(rows)


# ---------------------------------------------------------------- Request documents and parsing facts
#
# The request parsers live in limn/web/parse.py (coding rule R3): each returns the validated value or an InputRejected
# with the exact 400 message of the agent contract, and the handler passes the parsed value to the service here. A
# parser that checks a request against the manuscript reads it through document_facts().


def assignee_people(d: Mapping[str, Any]) -> Collection[str]:
    """The logins limn.web.parse.parse_assignee checks against: known_people() when the body names an assignee, else
    none (no read)."""
    return known_people() if d.get("assignee") is not None else ()


def _person_name(login: str) -> str:
    """A known person's display name, or the login itself for someone the viewer does not know."""
    return (known_people().get(login) or {}).get("name") or login


def request_doc(key: str | None, file_hint: object | None = None) -> Doc | DocNotFound:
    """The document of this instance that key names, else the one holding file_hint, else the first; DocNotFound for a
    key it does not serve (limn.documents.request_doc)."""
    return documents.request_doc(DOCS, C.src, key, file_hint)


def document_facts(D: Doc) -> DocumentFacts:
    """The parsing facts of document D (limn.documents.DocumentFacts) with this instance's manuscript root and dpi -
    made per request like pin_store(), so a test (or main()) that changes C is seen at once."""
    return DocumentFacts(D, C.src, C.dpi)


# ---------------------------------------------------------------- Pin operations
#
# The pin services - add, edit, reply, close/reopen, confirm, claim, the Trash and clear - are limn/service/: the
# shells that load the pins under the pin lock, ask limn.pins' rules, write only on success and then emit the notices
# and audit lines. What they need from this instance comes in a PinContext that pin_context() makes per call; the
# functions below keep the names, arguments and outcomes the handler (web/app.py) and the tests call.


def pin_context() -> PinContext:
    """The pin services' view of this instance (limn.service.context.PinContext), made per call like pin_store(), so a
    test (or main()) that changes C, THREAD_MAX or TRASH_DAYS, or freezes now_str or time.time, is seen at once."""
    return PinContext(
        store=pin_store(),
        now=now_str,
        epoch=time.time,
        hm=lambda: datetime.now().astimezone().strftime("%H:%M"),
        make_event=make_event,
        emit_events=emit_events,
        who=who,
        audit=http_audit,
        known_people=known_people,
        note_tags=note_tags,
        role_of=role_of,
        person_name=_person_name,
        locate=pin_locator(),
        stamp=lambda r: stamp_location(r, C.src),
        thread_max=THREAD_MAX,
        trash_days=TRASH_DAYS,
        trash_checked=_TRASH_CHECKED,
    )


def http_audit(action: str, by: Json, details: Json) -> bool:
    """Appends one audit.jsonl line for a change made over HTTP (limn.audit), stamped by the clock read now."""
    return append_audit(C.state, audit_entry(action, by, "http", details, time.time()))


def add_pin(D: Doc, request: AddRequest, actor: Json) -> OpenPin:
    """POST /api/pin: a new pin in document D (limn.service.add_edit.add_pin)."""
    return add_edit.add_pin(pin_context(), D, request, actor)


def edit_scope(pid: int) -> tuple[bool, Doc]:
    """(region, document) of an edit of pin pid, read without the lock before the edit (as always): whether it is a
    view-only (region) pin, and the document its loc is checked against - the pin's own, else the first one."""
    r0 = find_pin(read_pins()[0], pid)
    region = r0 is not None and is_region_pin(r0)
    return region, (doc_by_key(pin_doc_key(r0)) if r0 is not None else None) or DOCS[0]


def edit_pin(
    pid: int, request: EditRequest, actor: Json, region: bool = False
) -> OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound:
    """POST /api/pins/{id}/edit: pin pid edited in place (limn.service.add_edit.edit_pin); region and the placed loc
    come from edit_scope()."""
    return add_edit.edit_pin(pin_context(), pid, request, actor, region)


# ---------------------------------------------------------------- People, @-tags, events (docs/handbook/api.md §@태그·사람·이벤트)
#
# people.json (limn/people.py), the @-tag rules (limn/mentions.py) and events.jsonl (limn/events.py) take their paths,
# locks, caches and clock as arguments. The process's ones are made here, once, and bound per call by people_book()
# and event_log(); the functions below keep the names the pin services, the handler (web/app.py) and the tests call.

PEOPLE_LOCK = threading.Lock()
EVENTS_LOCK = threading.Lock()
_PEOPLE_SEEN: people.SeenMemo = {}  # (people.json path, login) -> (name, pic, epoch last written) - not rewritten if the value is unchanged
_EVENTS_CACHE: events.ReadCache = {}  # events.jsonl as last read, keyed by its mtime/size


def people_book() -> people.PeopleBook:
    """people.json of the current run (limn.people.PeopleBook): C.state with the process's lock and last-written memo.
    Made per call, like pin_store(), so a test or main() that changes C.state is seen at once."""
    return people.PeopleBook(C.state, PEOPLE_LOCK, _PEOPLE_SEEN)


def load_people() -> list[Row]:
    """The valid entries of this run's people.json (limn.people.load_people); [] when it is missing or unreadable."""
    return people.load_people(C.people_file)


def record_person(actor: Json, now: float | None = None, role: str | None = None) -> bool:
    """Records a tailnet person into people.json (limn.people.record_person: a new person, a name/picture change, or
    last_seen stale past PEOPLE_TOUCH_S). Local/agent and an actor without a login are never recorded. The request
    continues even if the write fails (only a warning). Returns True if it wrote. A person seen for the first time gets
    no role field (= DEFAULT_ROLE) unless `role` is given (the local owner is recorded as owner)."""
    login = (actor or {}).get("login")
    if not login or is_agent(actor):
        return False
    return people.record_person(people_book(), actor, time.time() if now is None else now, role, DEFAULT_ROLE)


def known_people(rows: list[Row] | None = None) -> dict[str, Row]:
    """@-tag candidates {login: {login,name,pic?,last_seen?}} - people.json plus the people on the pins (rows, or the
    stored pins when None), agents excluded (limn.people.known_people)."""
    ppl = load_people()
    return people.known_people(ppl, rows if rows is not None else read_pins()[0], is_agent)


def event_log() -> events.EventLog:
    """events.jsonl of the current run (limn.events.EventLog) with the process's lock and read cache, stamped by
    time.time() and now_str() - looked up when the value is made, so a test that freezes either reaches the records."""
    return events.EventLog(C.events_file, EVENTS_LOCK, _EVENTS_CACHE, time.time, now_str)


def make_event(
    typ: str,
    r: Mapping[str, Any],
    actor: Mapping[str, Any],
    to: Iterable[str | None] | None,
    msg: Mapping[str, Any] | None = None,
    text: str | None = None,
) -> Event | None:
    """One events.jsonl line about pin r by actor (limn.events.make_event; seq/at are filled in by emit_events). The
    actor themselves and local are removed from to - None (not recorded) if that leaves it empty."""
    return events.make_event(typ, r, actor, to, who, pin_doc_key, LOCAL_ACTOR["login"], msg, text)


def emit_events(evs: list[Event | None]) -> None:
    """Appends notices to events.jsonl, keeping the newest EVENTS_KEEP (limn.events.EventLog.emit). Only called after
    the pin write has committed (prevents phantom events); a failure is just a warning."""
    event_log().emit(evs, EVENTS_KEEP)


def _read_events() -> tuple[list[Row], events.Signature | None]:
    """(event list, file signature) of events.jsonl, cached by mtime/size (limn.events.EventLog.read)."""
    return event_log().read()


def note_tags(
    note: str, old_note: str, rows: list[Row], hints: Sequence[str] | None, actor: Mapping[str, Any], pid: object
) -> NoteTags:
    """Resolve the saved note's @-tags and decide who gets a mention event for pin pid.

    Everyone this save newly @-tags (limn.mentions.tag_note against old_note, the note before this edit; empty for a
    new pin) is notified - unless this actor's note already notified them about this pin within
    NOTE_MENTION_COOLDOWN_S (note_mention_targets over events.jsonl, read only when someone is newly tagged). Runs
    inside transact(): the caller emits the event under the same PIN_LOCK, so the next save sees it."""
    me = (actor or {}).get("login")
    tags = tag_note(note, old_note, known_people(rows), hints, me)
    if not tags.notify:
        return tags
    return tags._replace(notify=note_mention_targets(tags.notify, _read_events()[0], me, pid, time.time()))


def events_since(actor: Json, cursor: int | None) -> Json:
    """Notification material carried in /api/meta polling (limn.events.events_since): ev_seq always, and with a cursor
    the events after it addressed to the requester's tailnet login - nothing for local/agent. Read-only."""
    rows, _ = _read_events()
    me = (actor or {}).get("login")
    return events.events_since(rows, None if not me or is_agent(actor) else me, cursor, {d.key: d.name for d in DOCS})


def reply_reopens(r: Record, human: bool, mentioned: Sequence[str], reopen: bool | None = None) -> bool:
    """Does a reply reopen stored pin r? limn.pins.lifecycle.reopens_on_reply() on the record's state; the viewer's
    preview (replyReopens) mirrors that rule."""
    return reopens_on_reply(parse_pin(r), human, mentioned, reopen)


def reply_pin(
    pid: int,
    text: str,
    actor: Json,
    hints: list[str] | None = None,
    reopen: bool | None = None,
    human: bool | None = None,
) -> OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound:
    """POST /api/pins/{id}/reply (limn.service.transitions.reply_pin)."""
    return transitions.reply_pin(pin_context(), pid, text, actor, hints, reopen, human)


def set_done(
    pid: int,
    done: bool,
    actor: Json,
    reply: str | None = None,
    ref: str | None = None,
    review: bool | None = None,
    reason: str | None = None,
    hints: list[str] | None = None,
    changes: Sequence[CloseChange] | None = None,
) -> OpenPin | ReviewPin | DonePin | AlreadyClosed | PinNotFound:
    """POST /api/pins/{id}/close (done=True) and /reopen (done=False) (limn.service.transitions.set_done)."""
    return transitions.set_done(pin_context(), pid, done, actor, reply, ref, review, reason, hints, changes)


def confirm_pin(pid: int, actor: Json) -> DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound:
    """POST /api/pins/{id}/confirm (limn.service.transitions.confirm_pin)."""
    return transitions.confirm_pin(pin_context(), pid, actor)


def drop_pin(pid: int, actor: Json) -> TrashedPin | PinNotFound:
    """POST /api/pins/{id}/drop: the pin moves to the Trash (limn.service.trash.drop_pin)."""
    return trash.drop_pin(pin_context(), pid, actor)


# ---------------------------------------------------------------- Trash (pins.dropped.jsonl, docs/handbook/domain.md §전이와 할 수 있는 쪽)
#
# The Trash's rules and writes are limn/service/trash.py: a dropped pin stays restorable for TRASH_DAYS from dropped_at,
# reading never writes, and the file is rewritten without expired entries at startup, on every drop/restore, hourly on
# the reads that already write, and by the owner's permanent delete. The process's memo of the last lazy check is here.

_TRASH_CHECKED: list[float] = [0.0]  # epoch of the last lazy check (per process)


def trash_expires_ts(r: Record) -> float | None:
    """Epoch seconds at which a Trash entry expires (dropped_at + TRASH_DAYS), or None if dropped_at is unreadable."""
    return trash.expires_ts(r, TRASH_DAYS)


def trash_expired(r: Record, now: float | None = None) -> bool:
    """Is Trash entry r past TRASH_DAYS at now (default: the clock)? An entry of unknown age never is."""
    return trash.expired(r, TRASH_DAYS, time.time() if now is None else now)


def _unexpired(rows: Sequence[Row], now: float | None = None) -> list[Row]:
    """The Trash entries of rows still restorable at now (default: the clock)."""
    return trash.unexpired(rows, TRASH_DAYS, time.time() if now is None else now)


def purge_trash(now: float | None = None) -> int:
    """Rewrites the Trash without entries older than TRASH_DAYS -> how many went (limn.service.trash.purge_trash)."""
    return trash.purge_trash(pin_context(), now)


def maybe_purge_trash() -> int:
    """The hourly lazy expiry on the reads that already write (limn.service.trash.maybe_purge_trash)."""
    return trash.maybe_purge_trash(pin_context())


def purge_pin(pid: int, actor: Json) -> TrashedPin | NotInTrash:
    """POST /api/pins/{id}/purge: the owner's permanent delete (limn.service.trash.purge_pin)."""
    return trash.purge_pin(pin_context(), pid, actor)


# ---------------------------------------------------------------- In-progress marker (docs/handbook/api.md §처리 중 표시 (claim))
#
# A co-author and their agent can work on the same pin at the same time. A TTL'd optimistic marker reduces
# conflicts - it's a signal, not a lock: nothing stops closing or force-claiming a pin another identity holds a valid claim on.
# Claiming and unclaiming are limn/service/claim.py; claim_active is the read the pin list computes claim_ts from.


def claim_active(r: Record) -> bool:
    """Does this pin have an unexpired claim now? limn.pins.lifecycle.claim_holds() at the current epoch."""
    return claim_holds(r, time.time())


def claim_pin(
    pid: int, actor: Json, ttl_min: int, eta_min: int | None = None
) -> OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound:
    """POST /api/pins/{id}/claim: place or extend the in-progress marker (limn.service.claim.claim_pin)."""
    return claim.claim_pin(pin_context(), pid, actor, ttl_min, eta_min)


def unclaim_pin(pid: int, actor: Json) -> OpenPin | ReviewPin | DonePin | NotClaimed | PinNotFound:
    """POST /api/pins/{id}/unclaim (limn.service.claim.unclaim_pin)."""
    return claim.unclaim_pin(pin_context(), pid, actor)


def restore_pin(pid: int, actor: Json) -> OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive:
    """POST /api/pins/{id}/restore: the pin comes back from the Trash (limn.service.trash.restore_pin)."""
    return trash.restore_pin(pin_context(), pid, actor)


def clear_pins(actor: Json | None = None) -> Json:
    """POST /api/clear: archive and clear every pin, with its notice and audit line (limn.service.trash.clear_pins)."""
    return trash.clear_pins(pin_context(), actor)


def render_pins_md(rows: list[Row]) -> None:
    """Rewrites pins.md from rows alone (PinStore.render_md). Callers hold PIN_LOCK."""
    pin_store().render_md(rows)


def pins_md_text(rows: list[Row], base: str | None = None) -> str:
    """pins.md's text for rows: limn.pins.render.pins_md_text over pins_md_input(rows, base). The store renders with
    this after every write (base None: the file on disk) and GET /pins.md with the request's base."""
    return render_pins_md_text(pins_md_input(rows, base))


def pins_md_input(rows: list[Row], base: str | None = None) -> PinsMdInput:
    """Everything one rendering of pins.md reads, gathered at the edge: the run settings in C, the documents and their
    build stamps, the clock, this machine's token file, people.json, and per pin what the overlap, @-tag, thread and
    file-location rules decide. base is GET /pins.md's request base, None for the file written to disk.

    Reads files (people.json, the build stamps, whether the token file exists, and the source file of each open
    one-line pin that carries a quote - each file read at most once per call) but writes nothing."""
    rel = overlaps_by_id(rows)
    by_id = {r["id"]: r for r in rows}
    sources: dict[Path, list[str]] = {}
    facts: dict[int, PinFacts] = {}
    for r in rows:
        if pin_state(r) == "done":
            continue
        location, line_len = "", None
        if not is_region_pin(r):
            loc = pin_location(r, C.src)  # ADR-0006: still relative after the checkout moved
            location = loc.rel if loc is not None else (Path(str(r.get("file", ""))).name or str(r.get("name") or ""))
            lo, hi = r.get("lo"), r.get("hi")
            if loc is not None and not r.get("done") and r.get("quote") and is_int(lo) and is_int(hi) and lo == hi:
                if loc.path not in sources:  # outside the tree (loc None) is never read
                    sources[loc.path] = tex_lines(loc.path)
                lines = sources[loc.path]
                line_len = len(lines[lo - 1]) if 1 <= lo <= len(lines) else None
        facts[r["id"]] = PinFacts(
            doc_key=pin_doc_key(r),
            location=location,
            line_len=line_len,
            badge=rel_badge(rel.get(r["id"], []), by_id, r),
            reopened=pin_reopened_in_round(r),
            addressed=tuple(addressed_to(r)),
            fyi=tuple(fyi_mentions_to(r)),
            round=tuple(thread_round(r)),
        )
    docs = tuple(
        DocHeading(d.key, d.name, d.rel_path(), d.is_pdf, build.read_head(d), build.read_built_at(d)) for d in DOCS
    )
    return PinsMdInput(
        rows=rows,
        facts=facts,
        base=base,
        port=C.port,
        manuscript=str(C.src),
        label=C.label,
        repo=C.repo,
        docs=docs,
        people=known_people(rows),
        now=time.time(),
        updated=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        token_file=existing_token_file_shown(C.agent_token_file),
    )


def existing_token_file_shown(f: Path | None) -> str | None:
    """The shell path of token file f when it exists, else None - the edge half of
    limn.pins.render.token_guidance_line(): one stat per render, never a read of the file."""
    return shell_path(f, home_or_none()) if file_present(f) else None


# ---------------------------------------------------------------- Selection resolution
#
# Resolving a drag to source lines, the snippet and the overlaps of a range are limn/locate.py's; they take the
# document and a PickContext as arguments. These are the App members the handler calls (web/app.py), bound to this
# instance's run settings, token-weight cache and pins (overlaps_for_range above).

TOKEN_CACHE = locate.TokenCache()  # the process's word-frequency cache for the last file weighed


def pick_context() -> locate.PickContext:
    """What resolving a selection needs from this instance: the manuscript root, --float-envs, the state folder, the
    process's token-weight cache and the overlaps of a range with the stored pins."""
    return locate.PickContext(C.src, C.envs, C.state, TOKEN_CACHE, overlaps_for_range)


def pick(D: Doc, request: locate.Selection) -> Json:
    """POST /api/pick: a selection of document D (parsed by limn.web.parse.parse_pick) -> source lines (limn.locate.pick)."""
    return locate.pick(D, request, pick_context())


def snippet_api(rng: locate.SourceLines, levels: bool) -> Json:
    """GET /api/snippet: a parsed range's lines, with levels the range ladder under --float-envs (limn.locate.snippet_api)."""
    return locate.snippet_api(rng, levels, C.envs)


def overlaps_api(rng: locate.SourceLines) -> Json:
    """GET /api/overlaps: a parsed range's overlaps with the stored open pins (limn.locate.overlaps_api)."""
    return locate.overlaps_api(rng, pick_context())


# ---------------------------------------------------------------- Access control wiring (limn/access.py, docs/adr/0002-access-control.md)
#
# Who a request is (identify), whether it may use this instance (admit), what it may change (check_role) and the
# Host/Origin rules live in limn/access.py, which never reads C. Here the composition root binds them to this instance:
# the settings value from C (made per call like build_config(), so a test or main() that changes C is seen at once),
# the file-backed lookups, and the resources this process owns for them - one cache per file (tokens.json and
# people.json are re-read when they change on disk, so `limn token` / `limn member` edits take effect on the next
# request without a restart) and the one-time loopback-agent warning. The refusals raise HTTPError (fail closed).

# tokens.json's valid entries as this process last read them
TOKENS_CACHE: access.FileCache[list[Json]] = access.FileCache()
# {login: role} of people.json as this process last read it
ROLES_CACHE: access.FileCache[dict[str, str]] = access.FileCache()
LOOPBACK_WARNING = access.WarnOnce(LOOPBACK_AGENT_DEPRECATION)


def access_settings() -> access.AccessSettings:
    """The access options of this run (C) as the value identify() and admit() read."""
    return access.AccessSettings(
        auth=C.auth,
        agent_loopback=C.agent_loopback,
        tailnet_agent=C.tailnet_agent,
        trusted_proxies=C.trusted_proxies,
        proxy_user_header=C.proxy_user_header,
        proxy_name_header=C.proxy_name_header,
        proxy_email_header=C.proxy_email_header,
        members_only=C.members_only,
        allow=C.allow,
        local_user=C.local_user,
        agent_token_file=C.agent_token_file,
    )


def current_tokens() -> list[Json]:
    """tokens.json as the server sees it now - re-read whenever its inode/mtime/size changes (revocation needs no restart)."""
    return TOKENS_CACHE.get(C.tokens_file, lambda: load_tokens(C.state), [])


def people_roles() -> dict[str, str]:
    """{login: role} for everyone in people.json, re-read whenever the file changes - so `limn member role` and
    `limn member remove` take effect on the running server's next request."""
    return ROLES_CACHE.get(C.people_file, lambda: roles_of(load_people()), {})


def role_of(login: str) -> str:
    """The people.json role of login; editor for someone people.json does not list."""
    return people_roles().get(login, DEFAULT_ROLE)


def access_lookups() -> access.AccessLookups:
    """The file-backed facts identify() reads at request time, over this process's caches and warning."""
    return access.AccessLookups(tokens=current_tokens, roles=people_roles, warn_loopback_agent=LOOPBACK_WARNING)


def identify(headers: Message, peer: str) -> access.Principal:
    """Who this request is (limn.access.identify under this run's settings); raises HTTPError 401/403."""
    return access.identify(headers, peer, access_settings(), access_lookups())


def admit(p: access.Principal, host: str | None, headers: Message | None = None) -> None:
    """May this principal use the instance at all (limn.access.admit); raises HTTPError 403."""
    access.admit(p, host, headers, access_settings(), people_roles)


def check_role(p: access.Principal, path: str) -> None:
    """The role rule for a POST to path (limn.access.check_role; the owner-only purge refusal quotes TRASH_DAYS);
    raises HTTPError 403."""
    access.check_role(p, path, TRASH_DAYS)


def host_ok(host: str) -> bool:
    """Is Host a loopback name, *.ts.net or one of this run's --public-host names (limn.access.host_ok)?"""
    return access.host_ok(host, C.public_hosts)


def origin_ok(origin: str, host: str | None) -> bool:
    """Is Origin on the same side as the Host the request arrived on (limn.access.origin_ok)?"""
    return access.origin_ok(origin, host, C.public_hosts)


def remote_base_for(host_raw: str) -> str:
    """The base URL of GET /pins.md's guidance for this Host (limn.access.remote_base_for, loopback on C.port)."""
    return access.remote_base_for(host_raw, C.public_hosts, C.port)


def cli_audit(state: Path) -> access.AuditSink:
    """The audit sink of `limn token` / `limn member` on state: each change becomes an audit.jsonl line as the OS
    account running the command (os_actor), via "cli", stamped when it is recorded."""

    def record(action: str, details: Json) -> bool:
        """Append one audit line for action with details (append_audit: a failed write only warns)."""
        return append_audit(state, audit_entry(action, os_actor(), "cli", details, time.time()))

    return record


# ---------------------------------------------------------------- Viewer

# The page GET / serves, before build_html() fills in the run's label and accent, and the service worker GET /sw.js
# serves - both read from the viewer package once, at import (limn/viewer/assemble.py).
HTML = viewer_html(VIEWER_DIR, UI_EN, pdfjs_version=PDFJS_VERSION, mark=inline_svg(), icons=LUCIDE)
SW_JS = service_worker(VIEWER_DIR)


# ---------------------------------------------------------------- HTTP handler wiring (the handler is limn/web/handler.py)


class _ModuleApp:
    """This module's live globals as attributes: the limn.web.app.App the HTTP handler calls.

    Read at call time and never copied, so main() rebinding HTML and a test rebinding a service on its copy of this
    module (mock.patch.object(ps, "build_async")) both reach the handler. A view over globals() rather than the module
    object: server.py also runs where it is not in sys.modules (loaded by path, as the tests and tools do)."""

    __slots__ = ("_ns",)

    def __init__(self, ns: dict[str, Any]) -> None:
        """Wrap the namespace dict itself (this module's globals()), not a snapshot of it."""
        self._ns = ns

    def __getattr__(self, name: str) -> Any:
        """The current value of global `name`; AttributeError when this module has none."""
        try:
            return self._ns[name]
        except KeyError:
            raise AttributeError(name) from None


class Handler(WebHandler):
    """The HTTP handler of this server: limn.web.handler.Handler bound to this module's services (_ModuleApp)."""

    app = _ModuleApp(globals())


if TYPE_CHECKING:
    # _ModuleApp answers every attribute with Any, so mypy cannot see through it. This assignment makes mypy check the
    # module itself against the handler's Protocol (limn.web.app.App): a missing or wrongly typed binding is a type
    # error here. Never runs.
    import limn.server as _this_module
    from limn.web.app import App

    _APP_CHECK: App = _this_module


# ---------------------------------------------------------------- Entry point


def init_doc(D: Doc, no_build: bool, wait: bool) -> Json:
    """Prepares one document at startup: legacy-layout migration, restoring build history, and building if needed. Builds in the background if wait=False."""
    D.dir.mkdir(parents=True, exist_ok=True)
    if D.root:
        build.migrate_pages(D)
    build.seed_builds(D, C.state)
    need = D.is_pdf and (pdf_changed(D) or not build.page_list(build.cur_pages(D), C.dpi))
    if not D.is_pdf:
        need = not no_build or not build.cur_pdf(D).exists() or not build.page_list(build.cur_pages(D), C.dpi)
    if not need:
        return {"state": "skip"}
    return build_all(D) if wait else build_async(D)


def watch_pdf_docs(stop: threading.Event, every: float = 3.0) -> None:
    """Re-renders pages when a view-only PDF changes (mtime/size). Stands in for a rebuild button."""
    while not stop.wait(every):
        for D in list(DOCS):
            if D.is_pdf:
                try:
                    build.refresh_pdf_doc(D, build_async)
                except Exception:  # noqa: BLE001 — the watch thread must never die
                    traceback.print_exc(file=sys.stderr)


def build_arg_parser() -> argparse.ArgumentParser:
    """The `limn serve` argument parser (limn.args) with this server's one-line description, version and --float-envs
    default. The environment default of --agent-token-file is read here, i.e. at startup in main()."""
    return serve_parser(__doc__.splitlines()[0], "%s %s" % (APP_NAME, app_version()), DEFAULT_ENVS)


def access_options() -> startup.AccessOptions:
    """The access settings of this run as the startup rules' value: C's fields of the same names."""
    return startup.AccessOptions(**{f.name: getattr(C, f.name) for f in dataclasses.fields(startup.AccessOptions)})


def configure_access(a: argparse.Namespace) -> StartupRefused | None:
    """Applies the access options of the command line (limn.startup.access_options) to C, or returns the refusal with
    nothing applied - main() stops before any build, so a misconfigured unit fails fast."""
    opts = startup.access_options(a)
    if isinstance(opts, StartupRefused):
        return opts
    for f in dataclasses.fields(opts):
        setattr(C, f.name, getattr(opts, f.name))
    return None


def access_log_lines() -> list[str]:
    """The startup log lines about access (limn.startup.access_log_lines) for C, its tokens.json and token file."""
    return startup.access_log_lines(access_options(), len(load_tokens(C.state)), file_present(C.agent_token_file))


def configure_run(a: argparse.Namespace) -> list[Doc] | None | StartupRefused:
    """The run settings from the arguments into C, in the order that decides which refusal a bad command line gets:
    the manuscript, the documents (--doc, returned; None without it) or the main file, the state folder (created
    here, before the label and accent are checked), build settings, the port, access lists, the label and accent -
    and the viewer page they fill in (HTML). The rules are limn.startup's; this applies their answers."""
    global HTML
    C.src = Path(a.manuscript).expanduser().resolve()
    picked = startup.pick_documents(C.src, a.doc, a.main, C)
    if isinstance(picked, StartupRefused):
        return picked
    C.main = picked.main
    C.state = startup.state_dir(a.state_dir, C.src, Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")))
    C.state.mkdir(parents=True, exist_ok=True)
    C.build = C.state / "build"
    C.dpi = a.dpi
    C.envs = tuple(e.strip() for e in a.float_envs.split(",") if e.strip())
    C.timeout = a.build_timeout
    port = a.port or startup.free_port()
    if isinstance(port, StartupRefused):
        return port
    C.port = port
    C.allow = frozenset(x.strip() for x in a.allow.split(",") if x.strip())
    C.origin_check = not a.no_origin_check
    C.git_pull = a.git_pull
    C.pdfjs_dir = Path(a.pdfjs_dir).expanduser().resolve() if a.pdfjs_dir else default_pdfjs_dir()
    C.repo = startup.git_remote_url(C.src)
    label = startup.run_label(a.label, C.src, C.repo)
    if isinstance(label, StartupRefused):
        return label
    C.label = label
    accent = startup.run_accent(a.accent, C.label)
    if isinstance(accent, StartupRefused):
        return accent
    C.accent = accent
    HTML = build_html(C.label, C.accent)
    return picked.docs


def prepare(docs: list[Doc] | None, no_build: bool) -> StartupRefused | None:
    """The documents, pin store and builds before serving: the document list, pins.seq, the Trash's expired entries,
    then either the single document's build (synchronous; a failed build refuses to start) or every --doc
    document's build in the background (a failure only opens that tab's error panel), and the watch threads."""
    set_docs(docs)
    init_seq()
    purge_trash()  # Trash entries older than TRASH_DAYS go at startup, on every drop/restore, and hourly on reads
    if not docs:
        D = DOCS[0]
        build.migrate_pages(D)
        # adds the current build (made by an earlier instance) to history if missing, and restores the last build result
        build.seed_builds(D, C.state)
        if not no_build or not build.cur_pdf(D).exists() or not build.page_list(build.cur_pages(D), C.dpi):
            r = build_all(D)
            if r.get("state") == "fail":
                return StartupRefused("Build failed:\n" + r.get("log", ""))
    else:
        # Multiple documents: each document's build runs in the background, and the server comes up right
        # away (never waits N documents x tens of seconds). A failure never blocks startup - that document's tab opens an error panel instead.
        for D in DOCS:
            r = init_doc(D, no_build, wait=False)
            print(
                "doc    %-10s %s %s%s"
                % (
                    D.key,
                    "view-only" if D.is_pdf else "LaTeX   ",
                    D.rel_path(),
                    "" if r.get("state") == "skip" else "  (build started)",
                )
            )
        threading.Thread(target=watch_pdf_docs, args=(threading.Event(),), daemon=True).start()
    if C.git_pull:
        threading.Thread(
            target=SYNC_WATCH.watch,
            daemon=True,
            args=(threading.Event(), gitsync.SYNC_EVERY_S, sync_main_once, gitsync.local_stamp),
        ).start()
    with PIN_LOCK:
        render_pins_md(read_pins()[0])
    startup.tighten_state_perms(C.people_file)
    return None


def report(docs: list[Doc] | None) -> None:
    """The startup summary on stdout (limn.startup.summary_lines): manuscript, label, state folder, address, access,
    and the optional features."""
    pdfjs_found = bool(vendor_file("pdf.min.mjs") and vendor_file("pdf.worker.min.mjs"))
    for line in startup.summary_lines(C, bool(docs), access_log_lines(), pdfjs_found):
        print(line)
    sys.stdout.flush()


def listen() -> Server | StartupRefused:
    """The HTTP server on --bind/--port with this module's Handler (Server6 for an IPv6 address), or the refusal when
    the port was taken during the build (the probe before it passed) or cannot be listened on."""
    try:
        return (Server6 if ":" in C.bind else Server)((C.bind, C.port), Handler)
    except OSError as e:
        return startup.listen_refusal(C.bind, C.port, e)


def start(a: argparse.Namespace) -> Server | StartupRefused:
    """Every startup step, in order, until one refuses: access settings, the --port probe, the run settings and
    documents, the store and builds, the summary, then the listening server."""
    refused = configure_access(a)
    if refused is None and a.port:
        refused = startup.probe_port(C.bind, a.port)
    if refused is not None:
        return refused
    docs = configure_run(a)
    if isinstance(docs, StartupRefused):
        return docs
    refused = prepare(docs, a.no_build)
    if refused is not None:
        return refused
    report(docs)
    return listen()


def main() -> None:
    """The composition root: parse the arguments, then start() settles the run settings (C), makes the documents,
    prepares the pin store and the builds, starts the watch threads and opens the server; serve until stopped. The
    one place the process exits on a refused start: the refusal's message on stderr, status 1."""
    started = start(build_arg_parser().parse_args())
    if isinstance(started, StartupRefused):
        sys.exit(started.message)
    started.serve_forever()


if __name__ == "__main__":
    main()
