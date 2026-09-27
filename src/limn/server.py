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

import argparse
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import TYPE_CHECKING, Any

if __package__ in (None, ""):
    # Run as a file (python .../limn/server.py, how instances start): make the sibling modules importable as limn.*.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# The limn.* modules this composition root wires together. The pin services (add_edit, claim, trash, transitions) are
# wired by pin_context(); pins.md's renderer gets its input from pins_md_input(); the run settings' type, the startup
# rules and the command line make C, bound once (main() -> start() below). `X as X` marks a name this module exports as an App
# member (web/app.py) - mypy's explicit re-export, so the App check at the Handler sees it: the page directory on screen
# and a build's PDF (limn.build's own functions, bound here without a shell), outline_labels, pin_state,
# revision_history, hdr_text (the handler quotes a refused Host/Origin/document key through it), APP_NAME and
# app_version. The build state is bound by assignment below the imports, because an import under another name is
# never an export. meta_reads is the module; meta() below is the App member that binds it. record is the store's
# record parse; parse_record() and parse_trashed() below bind it.
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
    people_roles_of,
    person_role,
)
from limn.args import serve_parser
from limn.audit import AuditAction, append_audit, audit_entry
from limn.build import (
    BuildBusy,
    BuildConfig,
    BuildSkipped,
    BuildStarted,
    FailedBuild,
    FinishedBuild,
    ViewOnlyNoRebuild,
    build_pdf as build_pdf,
    cur_pages as cur_pages,
)
from limn.config import AccessOptions, RunConfig
from limn.documents import (
    DEFAULT_DOC_KEY,
    DOC_KEY_RE,
    Doc,
    DocNotFound,
    DocumentFacts,
)
from limn.events import EVENTS_KEEP, EventType
from limn.files import tex_lines, vendor_file as find_vendor_file
from limn.guidance import shell_path
from limn.locate import PinLocation, est_context, locate_file
from limn.mark import inline_svg
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
    CloseRequest,
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
    Pin,
    PinNotFound,
    Record,
    Region,
    ReviewPin,
    TrashedPin,
    is_region_pin,
    parse_pin,
    state_of,
)
from limn.pins.position import EstContext
from limn.pins.record import Broken
from limn.pins.render import (
    DocHeading,
    PinFacts,
    PinsMdInput,
    pins_md_text as render_pins_md_text,
    rel_badge,
)
from limn.pins.shapes import is_int
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
from limn.service.context import Event, Json, PinContext, is_agent, who
from limn.startup import APP_NAME as APP_NAME, StartupRefused, app_version as app_version
from limn.store import PinFiles, PinStore, Row, pin_index
from limn.viewer.assemble import (
    LUCIDE,
    PDFJS_VERSION,
    VIEWER_DIR,
    ServedViewer,
    ViewerFiles,
    load_ui_messages,
    serve_viewer,
    service_worker,
    viewer_html,
)
from limn.web.errors import HTTPError as HTTPError, build_failure_log, revision_failure_text
from limn.web.handler import Handler as WebHandler, Server, Server6

build_state_snapshot = build.state_snapshot


DEFAULT_ENVS = "figure,table,algorithm,equation,align,itemize,enumerate,minipage"

# The settings the pin services get from this instance (pin_context), module globals so a test can patch them. The
# rules they bound live with the rules: the request limits in limn/web/parse.py, NOTE_MAX in limn/pins/edit.py,
# KIND_REQS and the thread marks a record may carry in limn/pins/model.py, PEOPLE_TOUCH_S in limn.people,
# EVENTS_KEEP in limn.events, NOTE_MENTION_COOLDOWN_S in limn.mentions (docs/handbook/api.md §스레드, §@태그·사람·이벤트).
THREAD_MAX = 200  # cap on one pin's thread (replies). State-transition records (close/reopen/confirm) are appended regardless of this cap
TRASH_DAYS = 30  # a dropped pin stays in the Trash (pins.dropped.jsonl) this long, then is purged for good

# ---------------------------------------------------------------- Per-process resources
#
# Everything one server process holds between requests - the locks, caches, registries and status objects, the viewer
# it serves and the long-lived threads - is one Runtime value, made by new_runtime() in start() once the run settings
# are known and bound as RT. Nothing of it exists at import. A test makes a fresh one per test (tests/helpers.py). Each
# document's build lock and state belong to the document (limn.documents.Doc), the single one included.


@dataclass(frozen=True)
class Runtime:
    """The resources of one server process. The binding never changes after start(); the objects it holds do (a cache
    fills, a status moves on), each guarded by its own lock where threads share it.

    stop() ends the long-lived threads (the view-only PDF watch and the remote-main watch) that start_thread() began:
    it sets `stopping`, which both loops wait on, and joins them."""

    viewer: ServedViewer  # what GET /, GET /sw.js and a refused browser's page serve (read_viewer, serve_viewer)
    # The pin store's lock (limn.store.PinStore.lock): every path that touches the pin files goes through this single
    # re-entrant lock. The store creates no lock, so the process makes its one here and pin_store() passes it on.
    pin_lock: threading.RLock = field(default_factory=threading.RLock)
    people_lock: threading.Lock = field(default_factory=threading.Lock)  # people.json's read-modify-write
    events_lock: threading.Lock = field(default_factory=threading.Lock)  # events.jsonl's appends and trims
    # (people.json path, login) -> (name, pic, epoch last written): not rewritten if the value is unchanged
    people_seen: people.SeenMemo = field(default_factory=dict)
    # warns once per breakage of an unusable people.json, for every reader
    people_warning: people.UnreadableWarning = field(default_factory=people.UnreadableWarning)
    events_cache: events.ReadCache = field(default_factory=dict)  # events.jsonl as last read, keyed by mtime/size
    trash_checked: list[float] = field(default_factory=lambda: [0.0])  # epoch of the Trash's last lazy check
    # the pin scopes of commits (commits are immutable, so entries stay right) and the running comparison builds
    scope_cache: revisions.ScopeCache = field(default_factory=revisions.ScopeCache)
    revision_jobs: revisions.RevisionJobs = field(default_factory=revisions.RevisionJobs)
    # --git-pull: one pull per repository and its last result; the remote-main watch status (GET /api/meta `sync`)
    pull_share: gitsync.PullShare = field(default_factory=gitsync.PullShare)
    sync_watch: gitsync.SyncWatch = field(default_factory=gitsync.SyncWatch)
    token_cache: locate.TokenCache = field(default_factory=locate.TokenCache)  # word weights of the last file weighed
    # tokens.json's valid entries and people.json's {login: role} (or PeopleUnreadable) as last read - re-read when
    # the file changes on disk, so `limn token` / `limn member` edits take effect on the next request
    tokens_cache: access.FileCache[list[Json]] = field(default_factory=access.FileCache)
    roles_cache: access.FileCache[access.PeopleRoles] = field(default_factory=access.FileCache)
    loopback_warning: access.WarnOnce = field(default_factory=lambda: access.WarnOnce(LOOPBACK_AGENT_DEPRECATION))
    stopping: threading.Event = field(default_factory=threading.Event)  # set by stop(); the watch loops end on it
    threads: list[threading.Thread] = field(default_factory=list)  # the long-lived threads start_thread() began

    def start_thread(self, target: Callable[..., object], *args: object) -> None:
        """Start target(*args) on a daemon thread, registering only a thread stop() can join.

        target must return once `stopping` is set. A failed Thread.start leaves the registry unchanged so partial
        startup cleanup can stop earlier watches without masking the start error.
        """
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
        self.threads.append(t)

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the long-lived threads to end and wait up to timeout seconds for each. Idempotent: a second call, or one
        before any thread started (a refused or partial startup), only sets the event again."""
        self.stopping.set()
        for t in self.threads:
            t.join(timeout)


def new_runtime(viewer: ServedViewer) -> Runtime:
    """A process's resources, all fresh: new locks, empty caches and registries, no threads, serving viewer."""
    return Runtime(viewer)


RT: Runtime  # bound once by start(), before the server listens

# The run settings (limn.config.RunConfig): made by the startup steps from the command line and bound once, by start(),
# before the server listens. Frozen - a test binds another value (tests/helpers.py set_config) rather than changing it.
C: RunConfig


# ---------------------------------------------------------------- Documents (§Multiple documents, docs/handbook/domain.md §여러 문서)
#
# A document (limn.documents.Doc) is always an argument: the handler finds the request's (request_doc) and passes it
# on, a build thread gets its own, and startup walks the list. The list itself (DOCS, the first document is the
# default) is this composition root's, filled by prepare(); a Doc holds the frozen run paths (C.paths) it was made with.


def now_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


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
    """The build settings from the run arguments. Made per build, so a test that binds another C is seen at once."""
    return BuildConfig(state=C.state, dpi=C.dpi, timeout=C.timeout)


def build_all(D: Doc) -> FinishedBuild | BuildBusy:
    """POST /api/rebuild for document D: build it now (synchronous). If it is already building, returns BuildBusy
    without waiting (limn.build.build_now)."""
    return build.build_now(D, lambda: _build_tracked(D))


def build_async(D: Doc) -> BuildStarted | BuildBusy:
    """POST /api/rebuild?async=1 for document D: start the tracked build on a daemon thread
    (limn.build.build_in_background); the thread builds D itself."""
    return build.build_in_background(D, lambda: _build_tracked(D), now_str(), build_failure_log)


def rebuild(D: Doc) -> FinishedBuild | BuildBusy | ViewOnlyNoRebuild:
    """POST /api/rebuild for document D: build_all, or ViewOnlyNoRebuild for a view-only one (limn.build.request_rebuild)."""
    return build.request_rebuild(D, build_all)


def rebuild_async(D: Doc) -> BuildStarted | BuildBusy | ViewOnlyNoRebuild:
    """POST /api/rebuild?async=1 for document D: build_async, or ViewOnlyNoRebuild for a view-only one."""
    return build.request_rebuild(D, build_async)


def _build_tracked(D: Doc) -> FinishedBuild:
    """One tracked build of D: LaTeX (_build) or, for view-only, the page render (limn.build.render_pdf_doc)
    (limn.build.run_tracked); a failure's log text is limn.web.errors.build_failure_log. The step is looked up when
    the build runs, so a test that replaces _build sees it."""
    step: Callable[[], FinishedBuild] = (
        (lambda: build.render_pdf_doc(D, build_config())) if D.is_pdf else (lambda: _build(D))
    )
    return build.run_tracked(D, C.state, step, now_str(), build_failure_log)


# ---------------------------------------------------------------- Manuscript history, pin-scoped changes, comparison PDFs
#
# The revision services are limn/revisions.py (the git edge and the comparison builds) and limn/scope.py (the pure
# attribution of a commit's hunks to a pin, ADR-0005). They take the document and a RevisionContext and return
# outcome values; limn.web.answers answers them. What the instance supplies is wired here: the process's one scope
# cache and job registry, the pins as the API shows them, where a recorded path is now, and the texts a failed
# comparison records (limn.web.errors, the same table as the HTTP answers).


def revision_context() -> revisions.RevisionContext:
    """The revision services' view of this instance, made per request like pin_store(), so a test (or main()) that
    changes C is seen at once."""
    root, state = C.src, C.state

    def locate(file: str, D: revisions.RevisionDoc) -> Path | None:
        """Where a recorded change's path of document D is under the manuscript root now (locate_file, issue #24)."""
        loc = locate_file(file, None, root, state, D)
        return loc.path if loc is not None else None

    return revisions.RevisionContext(
        timeout=C.timeout,
        pins=lambda: [public(pin.record) for pin in read_pins()[0]],
        doc_of=pin_doc_key,
        locate=locate,
        cache=RT.scope_cache,
        jobs=RT.revision_jobs,
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
# answers mean and what the watch does next). The process's one pull share and watch status are the Runtime's; the
# bindings below hand them the manuscript folder, the documents, --git-pull, the git runner (limn.revisions.git
# imported above as _git: no shell, 30 seconds per call), the clock and the build starter, read per call so a test
# that binds another C or rebinds build_async is seen at once. prepare() starts the watch thread.


def repo_pull() -> Json:
    """A build's --git-pull, as its `pull` record (limn.gitsync.repo_pull): one document pulls on every build; several
    share one pull per repository within limn.gitsync.PULL_SHARE_S."""
    return gitsync.repo_pull(
        RT.pull_share, multi_doc(), lambda: gitsync.pull(C.src, main_only=False, git=_git), time.time
    )


def sync_status() -> Json:
    """GET /api/meta's `sync` - the remote-main watch status (limn.gitsync.SyncWatch.status)."""
    return RT.sync_watch.status(DOCS, C.git_pull)


def sync_main_once() -> Json:
    """One remote-main round (limn.gitsync.SyncWatch.once): pull main, then start the builds of the documents the
    pull left behind. The watch thread runs it, and a --no-build startup through it."""
    return RT.sync_watch.once(
        DOCS,
        C.git_pull,
        lambda: gitsync.pull(C.src, main_only=True, git=_git),
        RT.pull_share,
        build_async,
        gitsync.local_stamp,
        time.time,
    )


def _build(D: Doc) -> FinishedBuild:
    """The LaTeX build of document D with this instance's settings; --git-pull pulls first (limn.build.compile_tex)."""
    return build.compile_tex(D, build_config(), repo_pull if C.git_pull else None)


# ---------------------------------------------------------------- Documents and meta
#
# The document list (DOCS, the first is the default) is this composition root's. The lookups over it are
# limn.documents' and the polled reads (GET /api/meta, /api/docs, /api/outline-labels) limn.meta's; each takes the
# list and the run settings as arguments, bound here.

DOCS: list[Doc] = []  # the documents this run serves, the first is the default; filled by prepare() (set_docs)


def set_docs(docs: Iterable[Doc] | None = None) -> None:
    """Change the document list (prepare()/tests). With none, the single document of a run without --doc: legacy
    (the manuscript and main file are C's) over C.paths, with its own build lock and state like any document."""
    DOCS[:] = list(docs) if docs else [Doc(DEFAULT_DOC_KEY, "본문", legacy=True, paths=C.paths)]


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
    """The run settings GET /api/meta reads, made per request like pin_store(), so a test that binds another C is
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
    pins, _ = read_pins()
    return meta_reads.docs_payload(DOCS, [pin.record for pin in pins], pin_doc_key, C.state)


def meta(D: Doc, actor: Json, light: bool = False) -> Json:
    """GET /api/meta for document D: its pages, builds, staleness and settings for the viewer (limn.meta.meta); with
    light (polling) the pin counts are left out, and with them the sync write of snapshot_pins()."""
    out = meta_reads.meta(D, actor, meta_settings(), DOCS, sync_status(), time.time())
    if light:  # polling only - skips the sync write in snapshot_pins()
        return out
    out.update(meta_reads.pin_counts([pin.state for pin in snapshot_pins()]))
    return out


# ---------------------------------------------------------------- Pin store
#
# Which stored records the store trusts, and the pins they parse to, is limn/pins/record.py's parse; parse_record and
# parse_trashed bind it to the document key format (limn.documents) and the recorded actor's shape (limn.people),
# which it cannot import and stay pure.


def parse_record(r: object) -> Pin | Broken:
    """The store's parse of a pins.jsonl line (limn.pins.record.parse_record) with DOC_KEY_RE and
    limn.people.is_actor: the pin r holds, or Broken for a record the store may not trust."""
    return record.parse_record(r, DOC_KEY_RE.fullmatch, _is_actor)


def parse_trashed(r: object) -> TrashedPin | Broken:
    """The store's parse of a Trash line (limn.pins.record.parse_trashed), with the same two rules as parse_record."""
    return record.parse_trashed(r, DOC_KEY_RE.fullmatch, _is_actor)


def pin_location(r: Record, root: Path, state: Path) -> PinLocation | None:
    """Where line pin r's file is under the manuscript root on this machine now (limn.locate.pin_location, the tail
    guess limited to the folder of the pin's own document, never in the state folder), or None."""
    return locate.pin_location(r, root, state, doc_by_key(pin_doc_key(r)))


def stamp_location(r: Row, root: Path, state: Path) -> PinLocation | None:
    """Records in r where its file is now (limn.locate.stamp_location, the pin's own document). Mutates r."""
    return locate.stamp_location(r, root, state, doc_by_key(pin_doc_key(r)))


def pin_file(pin: Pin, root: Path, state: Path) -> PinLocation | None:
    """Where stored line pin pin's file is under the manuscript root on this machine now (limn.locate.pin_file, the tail
    guess limited to the folder of the pin's own document, never in the state folder), or None."""
    return locate.pin_file(pin, root, state, doc_by_key(pin_doc_key(pin.record)))


def pin_locator() -> locate.Locator:
    """pin_file() bound to this instance's manuscript root and state folder, read now: where a stored pin's file is."""
    root, state = C.src, C.state
    return lambda pin: pin_file(pin, root, state)


def record_locator() -> Callable[[Record], PinLocation | None]:
    """pin_location() bound to this instance's manuscript root and state folder, read now: where the file a record's
    location fields name is (the services locate a new pin's file, or an edit's, this way)."""
    root, state = C.src, C.state
    return lambda r: pin_location(r, root, state)


def sync_all(pins: list[Pin]) -> bool:
    """The store's re-sync (PinStore.sync): stored pins' lines follow their anchors in the .tex files as this instance
    finds them now (limn.locate.sync_all)."""
    return locate.sync_all(pins, pin_locator())


def pin_store() -> PinStore:
    """The pin store (limn.store) over the current run arguments - where the composition root wires it.

    Made per call, like build_config(), so a test that binds another C is seen at once; the lock is the one
    process-wide RT.pin_lock. The collaborators are looked up at call time: parse_record and parse_trashed read stored
    records into pins, sync_all re-matches their anchors, and pins_md_text renders the result."""
    return PinStore(PinFiles(C.state), RT.pin_lock, parse_record, parse_trashed, sync_all, pins_md_text)


# The pin store under its old names - the many call sites (transact(fn) everywhere) keep calling these, and each
# delegates to pin_store(). The contracts are the store's methods of the same name.


def read_pins() -> tuple[list[Pin], list[int]]:
    """The live pins, parsed, and pins.jsonl's broken line numbers, lock-free and not re-synced (PinStore.read_pins)."""
    return pin_store().read_pins()


def read_dropped() -> tuple[list[TrashedPin], list[int]]:
    """The Trash entries, parsed, and the Trash file's broken line numbers, lock-free (PinStore.read_dropped)."""
    return pin_store().read_dropped()


def write_pins(pins: list[Pin], bad: list[int] | None = None) -> None:
    """Rewrites pins.jsonl then pins.md; nothing if rendering fails (PinStore.write_pins). Callers hold RT.pin_lock."""
    pin_store().write_pins(pins, bad)


def snapshot_pins() -> list[Pin]:
    """The live pins, re-synced and written back if that changed them (PinStore.snapshot)."""
    return pin_store().snapshot()


def public(r: Record) -> Json:
    """A record as the API returns it (limn.pins.view.public_record), placed where pin_location() finds its file under
    the manuscript root now: `file` the absolute path on this machine, `rel_path` relative to the root (ADR-0006).
    Never changes r."""
    loc = pin_location(r, C.src, C.state)
    return view.public_record(r, None if loc is None else (str(loc.path), loc.rel))


# ---------------------------------------------------------------- Computed fields of GET /api/pins, and overlap
#
# What GET /api/pins and GET /api/pins/dropped add to the stored records is limn.pins.view's (pure; pin_state, an App
# member, is imported as it is). Overlap is limn.locate's, counting each pin in the file this instance finds for it
# now. Here both are bound to this instance: how a record is shown (public), a pin's document, each document's build
# history (limn.locate.est_context), the pin locator, the stored pins and the clock.


def pins_payload(pins: Sequence[Pin], allp: bool) -> list[Json]:
    """GET /api/pins response (limn.pins.view.pins_payload): stored records + the computed fields rel (overlap), est
    (location estimated), doc, state, addressed, fyi. None of these are stored."""
    rows = [pin.record for pin in pins]
    return view.pins_payload(rows, allp, overlaps_by_id(pins), public, pin_doc_key, _doc_est_context, time.time())


def pin_payload(pid: int) -> Json | PinNotFound:
    """GET /api/pins/{id}: pin pid as GET /api/pins?all=1 lists it (the pins re-synced and saved first), or
    PinNotFound."""
    rec = next((r for r in pins_payload(snapshot_pins(), True) if r["id"] == pid), None)
    return PinNotFound(pid) if rec is None else rec


def _doc_est_context(key: str) -> EstContext | None:
    """What estimation reads of the builds of the document key names (limn.locate.est_context), or None when this
    instance no longer serves that document."""
    D = doc_by_key(key)
    return None if D is None else est_context(D)


def dropped_payload(now: float | None = None) -> list[Json]:
    """GET /api/pins/dropped response - the Trash (limn.pins.view.dropped_payload): pins.dropped.jsonl ordered by
    dropped_at, each entry with `expires_ts`, without entries older than TRASH_DAYS (hidden here, removed from the file
    by the next purge_trash()).

    Read-only and outside the lock - dropping/restoring already hold RT.pin_lock while writing this file
    (drop_pin/restore_pin). Since only a file that has finished an atomic replace (atomic_write) is ever
    read here, no separate lock is needed to avoid seeing a half-written file."""
    return view.dropped_payload(_unexpired(read_dropped()[0], now), public, trash_expires_ts)


def overlaps_by_id(pins: Sequence[Pin]) -> dict[int, list[Json]]:
    """The relationship of every pair of open line pins on the same file, each counted where pin_location() places it
    now (limn.locate.overlaps_by_id), never stored."""
    return locate.overlaps_by_id(pins, pin_locator())


def overlaps_for_range(file: str, lo: int, hi: int) -> list[Json]:
    """The overlap relationships between a not-yet-saved range of file and that file's open pins, as re-synced now
    (limn.locate.overlaps_for_range). Nothing is saved."""
    return locate.overlaps_for_range(file, lo, hi, snapshot_pins(), pin_locator())


# ---------------------------------------------------------------- Pin ids


def init_seq() -> None:
    """If pins.seq is missing, fill it once from the max id across the current, archived, and dropped records (PinStore.init_seq)."""
    pin_store().init_seq()


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
    """The parsing facts of document D (limn.documents.DocumentFacts) with this instance's manuscript root, state
    folder and dpi - made per request like pin_store(), so a test that binds another C is seen at once."""
    return DocumentFacts(D, C.src, C.state, C.dpi)


# ---------------------------------------------------------------- Pin operations
#
# The pin services - add, edit, reply, close/reopen, confirm, claim, the Trash and clear - are limn/service/: the
# shells that load the pins under the pin lock, ask limn.pins' rules, write only on success and then emit the notices
# and audit lines. What they need from this instance comes in a PinContext that pin_context() makes per call; the
# functions below keep the names, arguments and outcomes the handler (web/app.py) and the tests call.


def pin_context() -> PinContext:
    """The pin services' view of this instance (limn.service.context.PinContext), made per call like pin_store(), so a
    test that binds another C, patches THREAD_MAX or TRASH_DAYS, or freezes now_str or time.time, is seen at once."""
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
        locate=record_locator(),
        stamp=lambda r: stamp_location(r, C.src, C.state),
        thread_max=THREAD_MAX,
        trash_days=TRASH_DAYS,
        trash_checked=RT.trash_checked,
    )


def http_audit(action: AuditAction, by: Json, details: Json) -> bool:
    """Appends one audit.jsonl line for a change made over HTTP (limn.audit), stamped by the clock read now."""
    return append_audit(C.state, audit_entry(action, by, "http", details, time.time()))


def add_pin(D: Doc, request: AddRequest, actor: Json) -> OpenPin:
    """POST /api/pin: a new pin in document D (limn.service.add_edit.add_pin)."""
    return add_edit.add_pin(pin_context(), D, request, actor)


def edit_scope(pid: int) -> tuple[bool, Doc]:
    """(region, document) of an edit of pin pid, read without the lock before the edit (as always): whether it is a
    view-only (region) pin, and the document its loc is checked against - the pin's own, else the first one."""
    pins, _ = read_pins()
    i = pin_index(pins, pid)
    if i is None:
        return False, DOCS[0]
    pin = pins[i]
    return isinstance(pin.core.place, Region), doc_by_key(pin_doc_key(pin.record)) or DOCS[0]


def edit_pin(
    pid: int, request: EditRequest, actor: Json, region: bool = False
) -> OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound:
    """POST /api/pins/{id}/edit: pin pid edited in place (limn.service.add_edit.edit_pin); region and the placed loc
    come from edit_scope()."""
    return add_edit.edit_pin(pin_context(), pid, request, actor, region)


# ---------------------------------------------------------------- People, @-tags, events (docs/handbook/api.md §@태그·사람·이벤트)
#
# people.json (limn/people.py), the @-tag rules (limn/mentions.py) and events.jsonl (limn/events.py) take their paths,
# locks, caches and clock as arguments. The process's ones are the Runtime's (RT), bound per call by people_book()
# and event_log(); the functions below keep the names the pin services, the handler (web/app.py) and the tests call.


def people_book() -> people.PeopleBook:
    """people.json of the current run (limn.people.PeopleBook): C.state with the Runtime's lock, last-written memo and
    unreadable-file warning. Made per call, like pin_store(), so a test that binds another C is seen at once."""
    return people.PeopleBook(C.state, RT.people_lock, RT.people_seen, RT.people_warning)


def load_people() -> list[Row] | people.PeopleUnreadable:
    """The valid entries of this run's people.json (limn.people.load_people); [] when it is missing, PeopleUnreadable
    (warned about once, RT.people_warning) when it exists but cannot be used."""
    rows = people.load_people(C.people_file)
    RT.people_warning.note(C.people_file, rows)
    return rows


def record_person(actor: Json, now: float | None = None, role: access.Role | None = None) -> bool:
    """Records a tailnet person into people.json (limn.people.record_person: a new person, a name/picture change, or
    last_seen stale past PEOPLE_TOUCH_S). Local/agent and an actor without a login are never recorded. The request
    continues even if the write fails (only a warning). Returns True if it wrote. A person seen for the first time gets
    no role field (= DEFAULT_ROLE) unless `role` is given (the local owner is recorded as owner)."""
    login = (actor or {}).get("login")
    if not login or is_agent(actor):
        return False
    return people.record_person(people_book(), actor, time.time() if now is None else now, role, DEFAULT_ROLE)


def people_payload() -> list[Json]:
    """GET /api/people's candidates (limn.people.candidates): people.json's roles read first, then the known people
    over the pins re-synced and saved (snapshot_pins), each with its role (limn.access.person_role)."""
    roles = people_roles()
    return people.candidates(known_people(snapshot_pins()), lambda login: person_role(roles, login))


def known_people(pins: Sequence[Pin] | None = None) -> dict[str, Row]:
    """@-tag candidates {login: {login,name,pic?,last_seen?}} - people.json plus the people on the pins (pins, or the
    stored pins when None), agents excluded (limn.people.known_people, which scans each pin's stored actor fields in
    stored order - the first one seen names a login). An unusable people.json adds no one: the candidates are then
    the people on the pins."""
    ppl = load_people()
    listed = [] if isinstance(ppl, people.PeopleUnreadable) else ppl
    on = pins if pins is not None else read_pins()[0]
    return people.known_people(listed, (pin.record for pin in on), is_agent)


def event_log() -> events.EventLog:
    """events.jsonl of the current run (limn.events.EventLog) with the Runtime's lock and read cache, stamped by
    time.time() and now_str() - looked up when the value is made, so a test that freezes either reaches the records."""
    return events.EventLog(C.events_file, RT.events_lock, RT.events_cache, time.time, now_str)


def make_event(
    typ: EventType,
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
    note: str, old_note: str, pins: Sequence[Pin], hints: Sequence[str] | None, actor: Mapping[str, Any], pid: object
) -> NoteTags:
    """Resolve the saved note's @-tags and decide who gets a mention event for pin pid.

    Everyone this save newly @-tags (limn.mentions.tag_note against old_note, the note before this edit; empty for a
    new pin) is notified - unless this actor's note already notified them about this pin within
    NOTE_MENTION_COOLDOWN_S (note_mention_targets over events.jsonl, read only when someone is newly tagged). Runs
    inside transact(): the caller emits the event under the same RT.pin_lock, so the next save sees it."""
    me = (actor or {}).get("login")
    tags = tag_note(note, old_note, known_people(pins), hints, me)
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


def close_pin(pid: int, actor: Json, request: CloseRequest) -> ReviewPin | DonePin | AlreadyClosed | PinNotFound:
    """POST /api/pins/{id}/close with its parsed body (limn.web.parse.parse_close; CloseRequest() is a close with
    no body) (limn.service.transitions.close_pin)."""
    return transitions.close_pin(pin_context(), pid, actor, request)


def reopen_pin(
    pid: int, actor: Json, reason: str | None = None, hints: list[str] | None = None
) -> OpenPin | PinNotFound:
    """POST /api/pins/{id}/reopen with its reason and @-tag hints (limn.web.parse.parse_reopen)
    (limn.service.transitions.reopen_pin)."""
    return transitions.reopen_pin(pin_context(), pid, actor, reason, hints)


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
# the reads that already write, and by the owner's permanent delete. The process's memo of the last lazy check is
# the Runtime's (RT.trash_checked).


def trash_expires_ts(entry: TrashedPin) -> float | None:
    """Epoch seconds at which a Trash entry expires (dropped_at + TRASH_DAYS), or None if dropped_at is unreadable."""
    return trash.expires_ts(entry, TRASH_DAYS)


def trash_expired(entry: TrashedPin, now: float | None = None) -> bool:
    """Is a Trash entry past TRASH_DAYS at now (default: the clock)? An entry of unknown age never is."""
    return trash.expired(entry, TRASH_DAYS, time.time() if now is None else now)


def _unexpired(entries: Sequence[TrashedPin], now: float | None = None) -> list[TrashedPin]:
    """The Trash entries still restorable at now (default: the clock)."""
    return trash.unexpired(entries, TRASH_DAYS, time.time() if now is None else now)


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


def render_pins_md(pins: Sequence[Pin]) -> None:
    """Rewrites pins.md from pins alone (PinStore.render_md). Callers hold RT.pin_lock."""
    pin_store().render_md(pins)


def pins_md_text(pins: Sequence[Pin], base: str | None = None) -> str:
    """pins.md's text for pins: limn.pins.render.pins_md_text over pins_md_input(pins, base). The store renders with
    this after every write (base None: the file on disk) and GET /pins.md with the request's base."""
    return render_pins_md_text(pins_md_input(pins, base))


def pins_md_input(pins: Sequence[Pin], base: str | None = None) -> PinsMdInput:
    """Everything one rendering of pins.md reads, gathered at the edge: the run settings in C, the documents and their
    build stamps, the clock, this machine's token file, people.json, and per pin what the overlap, @-tag, thread and
    file-location rules decide. base is GET /pins.md's request base, None for the file written to disk.

    Reads files (people.json, the build stamps, whether the token file exists, and the source file of each open
    one-line pin that carries a quote - each file read at most once per call) but writes nothing."""
    rows = [pin.record for pin in pins]
    rel = overlaps_by_id(pins)
    by_id = {r["id"]: r for r in rows}
    sources: dict[Path, list[str]] = {}
    facts: dict[int, PinFacts] = {}
    for pin in pins:
        r = pin.record
        if state_of(r) is DonePin:
            continue
        location, line_len = "", None
        if not is_region_pin(r):
            loc = pin_location(r, C.src, C.state)  # ADR-0006: still relative after the checkout moved
            location = loc.rel if loc is not None else (Path(str(r.get("file", ""))).name or str(r.get("name") or ""))
            lo, hi = r.get("lo"), r.get("hi")
            if loc is not None and state_of(r) is OpenPin and r.get("quote") and is_int(lo) and is_int(hi) and lo == hi:
                if loc.path not in sources:  # outside the tree (loc None) is never read
                    sources[loc.path] = tex_lines(loc.path)
                lines = sources[loc.path]
                line_len = len(lines[lo - 1]) if 1 <= lo <= len(lines) else None
        facts[r["id"]] = PinFacts(
            doc_key=pin_doc_key(r),
            location=location,
            line_len=line_len,
            badge=rel_badge(rel.get(r["id"], []), by_id, r),
            reopened=pin_reopened_in_round(pin.core.thread),
            addressed=tuple(addressed_to(pin)),
            fyi=tuple(fyi_mentions_to(pin)),
            round=tuple(thread_round(pin.core.thread)),
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
        people=known_people(pins),
        now=time.time(),
        updated=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        token_file=existing_token_file_shown(C.access.agent_token_file),
    )


def existing_token_file_shown(f: Path | None) -> str | None:
    """The shell path of token file f when it exists, else None - the edge half of
    limn.pins.render.token_guidance_line(): one stat per render, never a read of the file."""
    return shell_path(f, home_or_none()) if file_present(f) else None


# ---------------------------------------------------------------- Selection resolution
#
# Resolving a drag to source lines, the snippet and the overlaps of a range are limn/locate.py's; they take the
# document and a PickContext as arguments. These are the App members the handler calls (web/app.py), bound to this
# instance's run settings, the Runtime's token-weight cache and the pins (overlaps_for_range above).


def pick_context() -> locate.PickContext:
    """What resolving a selection needs from this instance: the manuscript root, --float-envs, the state folder, the
    process's token-weight cache and the overlaps of a range with the stored pins."""
    return locate.PickContext(C.src, C.envs, C.state, RT.token_cache, overlaps_for_range)


def pick(D: Doc, request: locate.Selection) -> locate.Picked | locate.PickedRegion | locate.PickRefusal:
    """POST /api/pick: a selection of document D (parsed by limn.web.parse.parse_pick) -> source lines, a view-only
    region, or why it cannot be traced (limn.locate.pick); limn.web.answers.pick_answer gives the body."""
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
# the settings value C makes once (C.access_settings; a test that binds another C is seen at once),
# the file-backed lookups, and the resources the Runtime owns for them - one cache per file (tokens.json and
# people.json are re-read when they change on disk, so `limn token` / `limn member` edits take effect on the next
# request without a restart) and the one-time loopback-agent warning. The refusals raise HTTPError (fail closed).


def access_settings() -> access.AccessSettings:
    """The access options of this run as the value identify() and admit() read (C.access_settings, made once per C)."""
    return C.access_settings


def current_tokens() -> list[Json]:
    """tokens.json as the server sees it now - re-read whenever its inode/mtime/size changes (revocation needs no restart)."""
    return RT.tokens_cache.get(C.tokens_file, lambda: load_tokens(C.state), [])


def people_roles() -> access.PeopleRoles:
    """{login: role} for everyone in people.json, or PeopleUnreadable while it cannot be used, re-read whenever the
    file changes - so `limn member role` and `limn member remove`, and a repaired file, take effect on the running
    server's next request."""
    return RT.roles_cache.get(C.people_file, lambda: people_roles_of(load_people()), {})


def role_of(login: str) -> access.Role:
    """The people.json role of login (limn.access.person_role): editor for someone people.json does not list, viewer
    for everyone while it cannot be used."""
    return person_role(people_roles(), login)


def access_lookups() -> access.AccessLookups:
    """The file-backed facts identify() reads at request time, over the Runtime's caches and warning."""
    return access.AccessLookups(tokens=current_tokens, roles=people_roles, warn_loopback_agent=RT.loopback_warning)


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
    return access.host_ok(host, C.access.public_hosts)


def origin_ok(origin: str, host: str | None) -> bool:
    """Is Origin on the same side as the Host the request arrived on (limn.access.origin_ok)?"""
    return access.origin_ok(origin, host, C.access.public_hosts)


def remote_base_for(host_raw: str) -> str:
    """The base URL of GET /pins.md's guidance for this Host (limn.access.remote_base_for, loopback on C.port)."""
    return access.remote_base_for(host_raw, C.access.public_hosts, C.port)


# ---------------------------------------------------------------- Viewer
#
# The viewer package (limn/viewer/assemble.py) is read once, by start(), never at import: importing this module reads
# no file. The template (ViewerFiles) and the page this run serves (ServedViewer: the template with the run's label and
# accent) are separate values; the Runtime holds the served one.


def read_viewer() -> ViewerFiles:
    """The viewer package from disk: the page template (index.html, its parts, the icons, the mark, the PDF.js version
    and ui_en.json's message table filled in), the service worker and the message table. Raises OSError / ValueError
    for a missing or malformed file (a packaging defect)."""
    messages = load_ui_messages(Path(__file__).with_name("ui_en.json"))
    template = viewer_html(VIEWER_DIR, messages, pdfjs_version=PDFJS_VERSION, mark=inline_svg(), icons=LUCIDE)
    return ViewerFiles(template, service_worker(VIEWER_DIR), messages)


def viewer() -> ServedViewer:
    """What the viewer routes serve on this run (GET /, GET /sw.js, a refused browser's page): the Runtime's, read at
    call time so a test that binds its own is seen at once."""
    return RT.viewer


# ---------------------------------------------------------------- HTTP handler wiring (the handler is limn/web/handler.py)


class _ModuleApp:
    """This module's live globals as attributes: the limn.web.app.App the HTTP handler calls.

    Read at call time and never copied, so start() binding the run's values and a test rebinding a service on its copy
    of this module (mock.patch.object(ps, "build_async")) both reach the handler. A view over globals() rather than the module
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


def init_doc(D: Doc, no_build: bool, wait: bool) -> FinishedBuild | BuildStarted | BuildBusy | BuildSkipped:
    """Prepares one document at startup: legacy-layout migration, restoring build history, and building if needed. Builds in the background if wait=False."""
    D.dir.mkdir(parents=True, exist_ok=True)
    if D.root:
        build.migrate_pages(D)
    build.seed_builds(D, C.state)
    if not build.needs_build(D, no_build, C.dpi):
        return BuildSkipped()
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


def access_log_lines() -> list[str]:
    """The startup log lines about access (limn.startup.access_log_lines) for C.access, its tokens.json and token file."""
    return startup.access_log_lines(C.access, len(load_tokens(C.state)), file_present(C.access.agent_token_file))


@dataclass(frozen=True)
class RunStart:
    """A command line configure_run lets start: its run settings and the --doc documents over their paths (None
    without --doc: prepare() makes the single document)."""

    config: RunConfig
    docs: list[Doc] | None


def configure_run(a: argparse.Namespace, access_opts: AccessOptions) -> RunStart | StartupRefused:
    """The run settings of the arguments, with the access options the access step decided, in the order that decides
    which refusal a bad command line gets: the manuscript, the documents (--doc) or the main file, the state folder
    (refused when it holds a served document, warned about on stderr when it lies inside the manuscript, and created
    here, before the label and accent are checked), build settings, the port, access lists, the label and accent. The
    rules are limn.startup's; this applies their answers and makes the --doc documents once the paths are known.
    """
    src = Path(a.manuscript).expanduser().resolve()
    picked = startup.pick_documents(src, a.doc, a.main)
    if isinstance(picked, StartupRefused):
        return picked
    state = startup.state_dir(a.state_dir, src, Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")))
    served = [d["main"] for d in picked.docs] if picked.docs else [picked.main]
    placed = startup.state_placement(state, src, served)
    if isinstance(placed, StartupRefused):
        return placed
    if isinstance(placed, startup.StateInManuscript):
        print(placed.warning(), file=sys.stderr)
    state.mkdir(parents=True, exist_ok=True)
    port = a.port or startup.free_port()
    if isinstance(port, StartupRefused):
        return port
    repo = startup.git_remote_url(src)
    label = startup.run_label(a.label, src, repo)
    if isinstance(label, StartupRefused):
        return label
    accent = startup.run_accent(a.accent, label)
    if isinstance(accent, StartupRefused):
        return accent
    config = RunConfig(
        src=src,
        main=picked.main,
        state=state,
        port=port,
        dpi=a.dpi,
        envs=tuple(e.strip() for e in a.float_envs.split(",") if e.strip()),
        timeout=a.build_timeout,
        allow=frozenset(x.strip() for x in a.allow.split(",") if x.strip()),
        origin_check=not a.no_origin_check,
        git_pull=a.git_pull,
        pdfjs_dir=Path(a.pdfjs_dir).expanduser().resolve() if a.pdfjs_dir else default_pdfjs_dir(),
        label=label,
        accent=accent,
        repo=repo,
        access=access_opts,
    )
    return RunStart(config, startup.docs_of(picked.docs, config.paths) if picked.docs else None)


def prepare(docs: list[Doc] | None, no_build: bool) -> StartupRefused | None:
    """The documents, pin store and builds before serving: the document list, pins.seq, the Trash's expired entries,
    then either the single document's build (synchronous; a failed build refuses to start) or every --doc
    document's build in the background (a failure only opens that tab's error panel), and the watch threads (the
    Runtime's, so RT.stop() ends them)."""
    set_docs(docs)
    init_seq()
    purge_trash()  # Trash entries older than TRASH_DAYS go at startup, on every drop/restore, and hourly on reads
    if not docs:
        D = DOCS[0]
        build.migrate_pages(D)
        # adds the current build (made by an earlier instance) to history if missing, and restores the last build result
        build.seed_builds(D, C.state)
        if build.needs_build(D, no_build, C.dpi):
            built = build_all(D)
            if isinstance(built, FailedBuild):
                return StartupRefused("Build failed:\n" + build_failure_log(built))
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
                    "" if isinstance(r, BuildSkipped) else "  (build started)",
                )
            )
        RT.start_thread(watch_pdf_docs, RT.stopping)
    if C.git_pull:
        RT.start_thread(RT.sync_watch.watch, RT.stopping, gitsync.SYNC_EVERY_S, sync_main_once, gitsync.local_stamp)
    with RT.pin_lock:
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
        return (Server6 if ":" in C.access.bind else Server)((C.access.bind, C.port), Handler)
    except OSError as e:
        return startup.listen_refusal(C.access.bind, C.port, e)


def start(a: argparse.Namespace) -> Server | StartupRefused:
    """Every startup step, in order, until one refuses: the access options (limn.startup.access_options: main() stops
    before any build, so a misconfigured unit fails fast), the --port probe, the run settings and documents - bound
    once, here, as C - the process's resources (new_runtime, bound as RT, with the viewer page for the run's label
    and accent: the viewer package is read here, not at import), the store and builds, the summary, then the
    listening server. A refusal or failure after binding the Runtime stops any watch threads it began."""
    global C, RT
    access_opts = startup.access_options(a)
    if isinstance(access_opts, StartupRefused):
        return access_opts
    if a.port:
        refused = startup.probe_port(access_opts.bind, a.port)
        if refused is not None:
            return refused
    run = configure_run(a, access_opts)
    if isinstance(run, StartupRefused):
        return run
    C = run.config
    RT = new_runtime(serve_viewer(read_viewer(), C.label, C.accent))
    try:
        prepared = prepare(run.docs, a.no_build)
        if prepared is not None:
            RT.stop()
            return prepared
        report(run.docs)
        result = listen()
        if isinstance(result, StartupRefused):
            RT.stop()
        return result
    except BaseException:
        RT.stop()
        raise


def main() -> None:
    """The composition root: parse the arguments, then start() makes and binds the run settings (C) and the process's
    resources (RT), the documents, prepares the pin store and the builds, starts the watch threads and opens the
    server; serve until stopped, then close the listening socket and stop the watch threads (RT.stop), even if
    socket closure fails. A serving error retains priority over cleanup errors, which are warned on stderr. The
    one place the process exits on a refused start: the refusal's message on stderr, status 1."""
    started = start(build_arg_parser().parse_args())
    if isinstance(started, StartupRefused):
        sys.exit(started.message)
    try:
        started.serve_forever()
    finally:
        serving_error = sys.exc_info()[1]
        cleanup_errors: list[BaseException] = []
        try:
            started.server_close()
        except BaseException as e:
            cleanup_errors.append(e)
        try:
            RT.stop()
        except BaseException as e:
            cleanup_errors.append(e)
        if cleanup_errors:
            if serving_error is None:
                raise cleanup_errors[0]
            for error in cleanup_errors:
                print(f"warning: server cleanup failed: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
