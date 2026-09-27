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
from typing import TYPE_CHECKING, Any, ClassVar

if __package__ in (None, ""):
    # Run as a file (python .../limn/server.py, how instances start): make the sibling modules importable as limn.*.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# The composition root wires these modules into ServerApplication. Explicit aliases
# retain the names that application exposes to the handler through App.
from limn import (
    access,
    build,
    documents,
    events,
    locate,
    people,
    startup,
)
from limn.access import (
    DEFAULT_ROLE as DEFAULT_ROLE,
    LOOPBACK_AGENT_DEPRECATION,
    file_present,
    hdr_text as hdr_text,
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
)
from limn.config import AccessOptions, RunConfig
from limn.documents import (
    DEFAULT_DOC_KEY,
    DOC_KEY_RE,
    Doc,
    DocNotFound,
    DocumentFacts,
)
from limn.features.builds import engine as build_engine, run as build_run
from limn.features.builds.service import BuildRequests
from limn.features.collaboration.directory import PeopleDirectory
from limn.features.collaboration.notices import Notices
from limn.features.document_views.reads import MetaSettings
from limn.features.document_views.service import DocumentViews
from limn.features.pins.claims.service import PinClaims
from limn.features.pins.editing.service import PinEditing
from limn.features.pins.lifecycle.service import PinLifecycle
from limn.features.pins.listing.markdown import PinMarkdown
from limn.features.pins.listing.service import PinListing
from limn.features.pins.location import resolve as pick_resolve, source as pick_source
from limn.features.pins.location.service import PinLocationService
from limn.features.pins.trash.service import PinTrash
from limn.features.revisions import core as revisions
from limn.features.revisions.core import (
    git as _git,
)
from limn.features.revisions.service import RevisionRequests
from limn.features.sync import run as gitsync
from limn.features.sync.service import SyncContext, SyncService
from limn.files import vendor_file as find_vendor_file
from limn.locate import PinLocation, est_context, locate_file
from limn.mark import inline_svg
from limn.people import is_actor as _is_actor
from limn.pins import record, view
from limn.pins.lifecycle import (
    claim_holds,
    reopens_on_reply,
)
from limn.pins.model import (
    Pin,
    Record,
    Region,
    TrashedPin,
    parse_pin,
)
from limn.pins.position import EstContext
from limn.pins.record import Broken
from limn.pins.view import pin_state as pin_state
from limn.service.context import Json, PinContext, who
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
from limn.web.app import App
from limn.web.errors import HTTPError as HTTPError, build_failure_log, revision_failure_text
from limn.web.handler import Handler as WebHandler, Server, Server6

DEFAULT_ENVS = "figure,table,algorithm,equation,align,itemize,enumerate,minipage"

# The pin services receive instance settings through pin_context(). The rules they bind
# live with the rules: request limits in limn/web/parse.py, NOTE_MAX in limn/pins/edit.py,
# KIND_REQS and the thread marks a record may carry in limn/pins/model.py, PEOPLE_TOUCH_S in limn.people,
# EVENTS_KEEP in limn.events, NOTE_MENTION_COOLDOWN_S in limn.mentions (docs/handbook/api.md §스레드, §@태그·사람·이벤트).
THREAD_MAX = 200  # cap on one pin's thread (replies). State-transition records (close/reopen/confirm) are appended regardless of this cap
TRASH_DAYS = 30  # a dropped pin stays in the Trash (pins.dropped.jsonl) this long, then is purged for good

# ---------------------------------------------------------------- Per-process resources
#
# Everything one server process holds between requests - the locks, caches, registries and status objects, the viewer
# it serves and the long-lived threads - is one Runtime value, made by new_runtime() in start() once the run settings
# are known and owned by ServerApplication. Nothing of it exists at import. A test makes a fresh one per test (tests/helpers.py). Each
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
    token_cache: pick_source.TokenCache = field(
        default_factory=pick_source.TokenCache
    )  # word weights of the last file weighed
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


# The run settings and process resources are owned by ServerApplication, bound before serving.


# The application passes an explicit Doc and its RunConfig into build and revision services.
# The default document is the first entry in ServerApplication.docs.


def default_pdfjs_dir() -> Path:
    """The PDF.js bundled with the package (limn/vendor/pdfjs)."""
    return Path(__file__).resolve().parent / "vendor" / "pdfjs"


# The viewer package is read at startup. Importing this module does not read it from disk.


def read_viewer() -> ViewerFiles:
    """The viewer package from disk: the page template (index.html, its parts, the icons, the mark, the PDF.js version
    and ui_en.json's message table filled in), the service worker and the message table. Raises OSError / ValueError
    for a missing or malformed file (a packaging defect)."""
    messages = load_ui_messages(Path(__file__).with_name("ui_en.json"))
    template = viewer_html(VIEWER_DIR, messages, pdfjs_version=PDFJS_VERSION, mark=inline_svg(), icons=LUCIDE)
    return ViewerFiles(template, service_worker(VIEWER_DIR), messages)


# ---------------------------------------------------------------- HTTP handler wiring (the handler is limn/web/handler.py)


class Handler(WebHandler):
    """Base handler for a server copy; each listener binds its own subclass to one application."""

    app: ClassVar[App]


# ---------------------------------------------------------------- Entry point


def build_arg_parser() -> argparse.ArgumentParser:
    """The `limn serve` argument parser (limn.args) with this server's one-line description, version and --float-envs
    default. The environment default of --agent-token-file is read here, i.e. at startup in main()."""
    return serve_parser(__doc__.splitlines()[0], "%s %s" % (APP_NAME, app_version()), DEFAULT_ENVS)


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


@dataclass
class ServerApplication:
    """One running server's settings, resources, documents and HTTP services.

    The handler receives this typed object; its methods use the instance state.
    A test may replace an individual method on this object without rebinding module globals.
    """

    C: RunConfig
    RT: Runtime
    docs: list[Doc] = field(default_factory=list)
    pin_lifecycle: PinLifecycle = field(init=False)
    pin_claims: PinClaims = field(init=False)
    pin_trash: PinTrash = field(init=False)
    pin_editing: PinEditing = field(init=False)
    pin_listing: PinListing = field(init=False)
    pin_markdown: PinMarkdown = field(init=False)
    location_service: PinLocationService = field(init=False)
    build_requests: BuildRequests = field(init=False)
    people_directory: PeopleDirectory = field(init=False)
    notices: Notices = field(init=False)
    document_views: DocumentViews = field(init=False)
    sync_service: SyncService = field(init=False)
    revision_requests: RevisionRequests = field(init=False)

    def __post_init__(self) -> None:
        """Bind pin features to this application's context factory."""
        self.people_directory = PeopleDirectory(
            state=lambda: self.C.state,
            people_file=lambda: self.C.people_file,
            lock=lambda: self.RT.people_lock,
            seen=lambda: self.RT.people_seen,
            warning=lambda: self.RT.people_warning,
            read_pins=self.read_pins,
            snapshot_pins=self.snapshot_pins,
            roles=self.people_roles,
            clock=lambda: time.time(),
        )
        self.notices = Notices(
            path=lambda: self.C.events_file,
            lock=lambda: self.RT.events_lock,
            cache=lambda: self.RT.events_cache,
            clock=lambda: time.time(),
            stamp=lambda: self.now_str(),
            pin_doc_key=self.pin_doc_key,
            docs=lambda: self.docs,
            known_people=self.people_directory.known,
        )
        self.pin_lifecycle = PinLifecycle(self.pin_context)
        self.pin_claims = PinClaims(self.pin_context)
        self.pin_trash = PinTrash(self.pin_context)
        self.pin_editing = PinEditing(self.pin_context)
        self.pin_listing = PinListing(self, TRASH_DAYS)
        self.pin_markdown = PinMarkdown(self, self.people_directory.known)
        self.location_service = PinLocationService(
            lambda: pick_resolve.PickContext(
                self.C.src, self.C.envs, self.C.state, self.RT.token_cache, self.overlaps_for_range
            )
        )
        self.build_requests = BuildRequests(
            lambda doc: self._build_tracked(doc), lambda: self.now_str(), build_failure_log
        )
        self.sync_service = SyncService(
            lambda: SyncContext(
                manuscript=self.C.src,
                enabled=self.C.git_pull,
                docs=self.docs,
                share=self.RT.pull_share,
                watch=self.RT.sync_watch,
                start_build=self.build_requests.build_async,
                git=_git,
                clock=time.time,
                stamp=gitsync.local_stamp,
            )
        )
        self.document_views = DocumentViews(
            settings=lambda: MetaSettings(
                state=self.C.state,
                pins_md=self.C.pins_md,
                pins_jsonl=self.C.pins_jsonl,
                label=self.C.label,
                accent=self.C.accent,
                repo=self.C.repo,
                dpi=self.C.dpi,
            ),
            docs=self.docs,
            sync_status=self.sync_service.status,
            read_pins=self.read_pins,
            snapshot_pins=self.snapshot_pins,
            pin_doc_key=self.pin_doc_key,
            events_since=self.notices.since,
            now=lambda: time.time(),
        )
        self.revision_requests = RevisionRequests(self.revision_context)

    APP_NAME = APP_NAME
    DEFAULT_ROLE = DEFAULT_ROLE
    hdr_text = staticmethod(hdr_text)
    app_version = staticmethod(app_version)
    pin_state = staticmethod(pin_state)

    def now_str(self) -> str:
        """Return the local timestamp used for a build's start time."""
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

    def vendor_file(self, name: str) -> Path | None:
        """The file GET /vendor/pdfjs/<name> serves from this instance's PDF.js directory (--pdfjs-dir, else the bundled
        one), or None (limn.files.vendor_file: a single .mjs name that stays inside the directory)."""
        return find_vendor_file(self.C.pdfjs_dir or default_pdfjs_dir(), name)

    def build_config(self) -> BuildConfig:
        """The build settings from the run arguments. Made per build, so a test that replaces this application's C is seen at once."""
        return BuildConfig(state=self.C.state, dpi=self.C.dpi, timeout=self.C.timeout)

    def _build_tracked(self, D: Doc) -> FinishedBuild:
        """One tracked build of D: LaTeX (_build) or, for view-only, the page render (limn.features.builds.engine.render_pdf_doc)
        (limn.features.builds.run.run_tracked); a failure's log text is limn.web.errors.build_failure_log. The step is looked up when
        the build runs, so a test that replaces _build sees it."""
        step: Callable[[], FinishedBuild] = (
            (lambda: build_engine.render_pdf_doc(D, self.build_config())) if D.is_pdf else (lambda: self._build(D))
        )
        return build_run.run_tracked(D, self.C.state, step, self.now_str(), build_failure_log)

    def revision_context(self) -> revisions.RevisionContext:
        """The revision services' view of this instance, made per request like pin_store(), so a test (or main()) that
        changes C is seen at once."""
        root, state = self.C.src, self.C.state

        def locate(file: str, D: revisions.RevisionDoc) -> Path | None:
            """Where a recorded change's path of document D is under the manuscript root now (locate_file, issue #24)."""
            loc = locate_file(file, None, root, state, D)
            return loc.path if loc is not None else None

        return revisions.RevisionContext(
            timeout=self.C.timeout,
            pins=lambda: [self.public(pin.record) for pin in self.read_pins()[0]],
            doc_of=self.pin_doc_key,
            locate=locate,
            cache=self.RT.scope_cache,
            jobs=self.RT.revision_jobs,
            describe=revision_failure_text,
        )

    def _build(self, D: Doc) -> FinishedBuild:
        """The LaTeX build of document D with this instance's settings; --git-pull pulls first (limn.features.builds.engine.compile_tex)."""
        return build_engine.compile_tex(
            D, self.build_config(), self.sync_service.repo_pull if self.C.git_pull else None
        )

    def set_docs(self, docs: Iterable[Doc] | None = None) -> None:
        """Change the document list (prepare()/tests). With none, the single document of a run without --doc: legacy
        (the manuscript and main file are C's) over C.paths, with its own build lock and state like any document."""
        self.docs[:] = list(docs) if docs else [Doc(DEFAULT_DOC_KEY, "본문", legacy=True, paths=self.C.paths)]

    def doc_by_key(self, key: object) -> Doc | None:
        """The document of this instance whose key is `key`, or None (limn.documents.doc_by_key)."""
        return documents.doc_by_key(self.docs, key)

    def pin_doc_key(self, r: Record) -> str:
        """The document key a pin belongs to; a legacy record without a doc field is the first document's
        (limn.documents.pin_doc_key)."""
        return documents.pin_doc_key(r, self.docs)

    def parse_record(self, r: object) -> Pin | Broken:
        """The store's parse of a pins.jsonl line (limn.pins.record.parse_record) with DOC_KEY_RE and
        limn.people.is_actor: the pin r holds, or Broken for a record the store may not trust."""
        return record.parse_record(r, DOC_KEY_RE.fullmatch, _is_actor)

    def parse_trashed(self, r: object) -> TrashedPin | Broken:
        """The store's parse of a Trash line (limn.pins.record.parse_trashed), with the same two rules as parse_record."""
        return record.parse_trashed(r, DOC_KEY_RE.fullmatch, _is_actor)

    def pin_location(self, r: Record, root: Path, state: Path) -> PinLocation | None:
        """Where line pin r's file is under the manuscript root on this machine now (limn.locate.pin_location, the tail
        guess limited to the folder of the pin's own document, never in the state folder), or None."""
        return locate.pin_location(r, root, state, self.doc_by_key(self.pin_doc_key(r)))

    def stamp_location(self, r: Row, root: Path, state: Path) -> PinLocation | None:
        """Records in r where its file is now (limn.locate.stamp_location, the pin's own document). Mutates r."""
        return locate.stamp_location(r, root, state, self.doc_by_key(self.pin_doc_key(r)))

    def pin_file(self, pin: Pin, root: Path, state: Path) -> PinLocation | None:
        """Where stored line pin pin's file is under the manuscript root on this machine now (limn.locate.pin_file, the tail
        guess limited to the folder of the pin's own document, never in the state folder), or None."""
        return locate.pin_file(pin, root, state, self.doc_by_key(self.pin_doc_key(pin.record)))

    def pin_locator(self) -> locate.Locator:
        """pin_file() bound to this instance's manuscript root and state folder, read now: where a stored pin's file is."""
        root, state = self.C.src, self.C.state
        return lambda pin: self.pin_file(pin, root, state)

    def record_locator(self) -> Callable[[Record], PinLocation | None]:
        """pin_location() bound to this instance's manuscript root and state folder, read now: where the file a record's
        location fields name is (the services locate a new pin's file, or an edit's, this way)."""
        root, state = self.C.src, self.C.state
        return lambda r: self.pin_location(r, root, state)

    def sync_all(self, pins: list[Pin]) -> bool:
        """The store's re-sync (PinStore.sync): stored pins' lines follow their anchors in the .tex files as this instance
        finds them now (limn.locate.sync_all)."""
        return locate.sync_all(pins, self.pin_locator())

    def pin_store(self) -> PinStore:
        """The pin store (limn.store) over the current run arguments - where the composition root wires it.

        Made per call, like build_config(), so a test that replaces this application's C is seen at once; the lock is the one
        application-wide RT.pin_lock. The collaborators are looked up at call time: parse_record and parse_trashed read stored
        records into pins, sync_all re-matches their anchors, and pins_md_text renders the result."""
        return PinStore(
            PinFiles(self.C.state),
            self.RT.pin_lock,
            self.parse_record,
            self.parse_trashed,
            self.sync_all,
            self.pin_markdown.pins_md_text,
        )

    def read_pins(self) -> tuple[list[Pin], list[int]]:
        """The live pins, parsed, and pins.jsonl's broken line numbers, lock-free and not re-synced (PinStore.read_pins)."""
        return self.pin_store().read_pins()

    def read_dropped(self) -> tuple[list[TrashedPin], list[int]]:
        """The Trash entries, parsed, and the Trash file's broken line numbers, lock-free (PinStore.read_dropped)."""
        return self.pin_store().read_dropped()

    def write_pins(self, pins: list[Pin], bad: list[int] | None = None) -> None:
        """Rewrites pins.jsonl then pins.md; nothing if rendering fails (PinStore.write_pins). Callers hold RT.pin_lock."""
        self.pin_store().write_pins(pins, bad)

    def snapshot_pins(self) -> list[Pin]:
        """The live pins, re-synced and written back if that changed them (PinStore.snapshot)."""
        return self.pin_store().snapshot()

    def public(self, r: Record) -> Json:
        """A record as the API returns it (limn.pins.view.public_record), placed where pin_location() finds its file under
        the manuscript root now: `file` the absolute path on this machine, `rel_path` relative to the root (ADR-0006).
        Never changes r."""
        loc = self.pin_location(r, self.C.src, self.C.state)
        return view.public_record(r, None if loc is None else (str(loc.path), loc.rel))

    def _doc_est_context(self, key: str) -> EstContext | None:
        """What estimation reads of the builds of the document key names (limn.locate.est_context), or None when this
        instance no longer serves that document."""
        D = self.doc_by_key(key)
        return None if D is None else est_context(D)

    def overlaps_by_id(self, pins: Sequence[Pin]) -> dict[int, list[Json]]:
        """The relationship of every pair of open line pins on the same file, each counted where pin_location() places it
        now (limn.locate.overlaps_by_id), never stored."""
        return locate.overlaps_by_id(pins, self.pin_locator())

    def overlaps_for_range(self, file: str, lo: int, hi: int) -> list[Json]:
        """The overlap relationships between a not-yet-saved range of file and that file's open pins, as re-synced now
        (limn.locate.overlaps_for_range). Nothing is saved."""
        return locate.overlaps_for_range(file, lo, hi, self.snapshot_pins(), self.pin_locator())

    def init_seq(self) -> None:
        """If pins.seq is missing, fill it once from the max id across the current, archived, and dropped records (PinStore.init_seq)."""
        self.pin_store().init_seq()

    def assignee_people(self, d: Mapping[str, Any]) -> Collection[str]:
        """The logins limn.web.parse.parse_assignee checks against: known_people() when the body names an assignee, else
        none (no read)."""
        return self.people_directory.known() if d.get("assignee") is not None else ()

    def _person_name(self, login: str) -> str:
        """A known person's display name, or the login itself for someone the viewer does not know."""
        return (self.people_directory.known().get(login) or {}).get("name") or login

    def request_doc(self, key: str | None, file_hint: object | None = None) -> Doc | DocNotFound:
        """The document of this instance that key names, else the one holding file_hint, else the first; DocNotFound for a
        key it does not serve (limn.documents.request_doc)."""
        return documents.request_doc(self.docs, self.C.src, key, file_hint)

    def document_facts(self, D: Doc) -> DocumentFacts:
        """The parsing facts of document D (limn.documents.DocumentFacts) with this instance's manuscript root, state
        folder and dpi - made per request like pin_store(), so a test that replaces this application's C is seen at once."""
        return DocumentFacts(D, self.C.src, self.C.state, self.C.dpi)

    def pin_context(self) -> PinContext:
        """The pin services' view of this instance (limn.service.context.PinContext), made per call like pin_store(), so a
        test that replaces this application's C, patches THREAD_MAX or TRASH_DAYS, or freezes now_str or time.time, is seen at once."""
        return PinContext(
            store=self.pin_store(),
            now=self.now_str,
            epoch=time.time,
            hm=lambda: datetime.now().astimezone().strftime("%H:%M"),
            make_event=self.notices.make_event,
            emit_events=self.notices.emit_events,
            who=who,
            audit=self.http_audit,
            known_people=self.people_directory.known,
            note_tags=self.notices.note_tags,
            role_of=self.role_of,
            person_name=self._person_name,
            locate=self.record_locator(),
            stamp=lambda r: self.stamp_location(r, self.C.src, self.C.state),
            thread_max=THREAD_MAX,
            trash_days=TRASH_DAYS,
            trash_checked=self.RT.trash_checked,
        )

    def http_audit(self, action: AuditAction, by: Json, details: Json) -> bool:
        """Appends one audit.jsonl line for a change made over HTTP (limn.audit), stamped by the clock read now."""
        return append_audit(self.C.state, audit_entry(action, by, "http", details, time.time()))

    def edit_scope(self, pid: int) -> tuple[bool, Doc]:
        """(region, document) of an edit of pin pid, read without the lock before the edit (as always): whether it is a
        view-only (region) pin, and the document its loc is checked against - the pin's own, else the first one."""
        pins, _ = self.read_pins()
        i = pin_index(pins, pid)
        if i is None:
            return False, self.docs[0]
        pin = pins[i]
        return isinstance(pin.core.place, Region), self.doc_by_key(self.pin_doc_key(pin.record)) or self.docs[0]

    def reply_reopens(self, r: Record, human: bool, mentioned: Sequence[str], reopen: bool | None = None) -> bool:
        """Does a reply reopen stored pin r? limn.pins.lifecycle.reopens_on_reply() on the record's state; the viewer's
        preview (replyReopens) mirrors that rule."""
        return reopens_on_reply(parse_pin(r), human, mentioned, reopen)

    def claim_active(self, r: Record) -> bool:
        """Does this pin have an unexpired claim now? limn.pins.lifecycle.claim_holds() at the current epoch."""
        return claim_holds(r, time.time())

    def render_pins_md(self, pins: Sequence[Pin]) -> None:
        """Rewrites pins.md from pins alone (PinStore.render_md). Callers hold RT.pin_lock."""
        self.pin_store().render_md(pins)

    def access_settings(self) -> access.AccessSettings:
        """The access options of this run as the value identify() and admit() read (C.access_settings, made once per C)."""
        return self.C.access_settings

    def current_tokens(self) -> list[Json]:
        """tokens.json as the server sees it now - re-read whenever its inode/mtime/size changes (revocation needs no restart)."""
        return self.RT.tokens_cache.get(self.C.tokens_file, lambda: load_tokens(self.C.state), [])

    def people_roles(self) -> access.PeopleRoles:
        """{login: role} for everyone in people.json, or PeopleUnreadable while it cannot be used, re-read whenever the
        file changes - so `limn member role` and `limn member remove`, and a repaired file, take effect on the running
        server's next request."""
        return self.RT.roles_cache.get(self.C.people_file, lambda: people_roles_of(self.people_directory.load()), {})

    def role_of(self, login: str) -> access.Role:
        """The people.json role of login (limn.access.person_role): editor for someone people.json does not list, viewer
        for everyone while it cannot be used."""
        return person_role(self.people_roles(), login)

    def access_lookups(self) -> access.AccessLookups:
        """The file-backed facts identify() reads at request time, over the Runtime's caches and warning."""
        return access.AccessLookups(
            tokens=self.current_tokens, roles=self.people_roles, warn_loopback_agent=self.RT.loopback_warning
        )

    def identify(self, headers: Message, peer: str) -> access.Principal:
        """Who this request is (limn.access.identify under this run's settings); raises HTTPError 401/403."""
        return access.identify(headers, peer, self.access_settings(), self.access_lookups())

    def admit(self, p: access.Principal, host: str | None, headers: Message | None = None) -> None:
        """May this principal use the instance at all (limn.access.admit); raises HTTPError 403."""
        access.admit(p, host, headers, self.access_settings(), self.people_roles)

    def check_role(self, p: access.Principal, path: str) -> None:
        """The role rule for a POST to path (limn.access.check_role; the owner-only purge refusal quotes TRASH_DAYS);
        raises HTTPError 403."""
        access.check_role(p, path, TRASH_DAYS)

    def host_ok(self, host: str) -> bool:
        """Is Host a loopback name, *.ts.net or one of this run's --public-host names (limn.access.host_ok)?"""
        return access.host_ok(host, self.C.access.public_hosts)

    def origin_ok(self, origin: str, host: str | None) -> bool:
        """Is Origin on the same side as the Host the request arrived on (limn.access.origin_ok)?"""
        return access.origin_ok(origin, host, self.C.access.public_hosts)

    def remote_base_for(self, host_raw: str) -> str:
        """The base URL of GET /pins.md's guidance for this Host (limn.access.remote_base_for, loopback on C.port)."""
        return access.remote_base_for(host_raw, self.C.access.public_hosts, self.C.port)

    def viewer(self) -> ServedViewer:
        """What the viewer routes serve on this run (GET /, GET /sw.js, a refused browser's page): the Runtime's, read at
        call time so a test that binds its own is seen at once."""
        return self.RT.viewer

    def init_doc(self, D: Doc, no_build: bool, wait: bool) -> FinishedBuild | BuildStarted | BuildBusy | BuildSkipped:
        """Prepares one document at startup: legacy-layout migration, restoring build history, and building if needed. Builds in the background if wait=False."""
        D.dir.mkdir(parents=True, exist_ok=True)
        if D.root:
            build.migrate_pages(D)
        build.seed_builds(D, self.C.state)
        if not build_run.needs_build(D, no_build, self.C.dpi):
            return BuildSkipped()
        return self.build_requests.build_all(D) if wait else self.build_requests.build_async(D)

    def watch_pdf_docs(self, stop: threading.Event, every: float = 3.0) -> None:
        """Re-renders pages when a view-only PDF changes (mtime/size). Stands in for a rebuild button."""
        while not stop.wait(every):
            for D in list(self.docs):
                if D.is_pdf:
                    try:
                        build_engine.refresh_pdf_doc(D, self.build_requests.build_async)
                    except Exception:  # noqa: BLE001 — the watch thread must never die
                        traceback.print_exc(file=sys.stderr)

    def access_log_lines(self) -> list[str]:
        """The startup log lines about access (limn.startup.access_log_lines) for C.access, its tokens.json and token file."""
        return startup.access_log_lines(
            self.C.access, len(load_tokens(self.C.state)), file_present(self.C.access.agent_token_file)
        )

    def prepare(self, docs: list[Doc] | None, no_build: bool) -> StartupRefused | None:
        """The documents, pin store and builds before serving: the document list, pins.seq, the Trash's expired entries,
        then either the single document's build (synchronous; a failed build refuses to start) or every --doc
        document's build in the background (a failure only opens that tab's error panel), and the watch threads (the
        Runtime's, so RT.stop() ends them)."""
        self.set_docs(docs)
        self.init_seq()
        self.pin_trash.purge_trash()  # Expired Trash and live shadows go at startup, and hourly on reads that already write
        if not docs:
            D = self.docs[0]
            build.migrate_pages(D)
            # adds the current build (made by an earlier instance) to history if missing, and restores the last build result
            build.seed_builds(D, self.C.state)
            if build_run.needs_build(D, no_build, self.C.dpi):
                built = self.build_requests.build_all(D)
                if isinstance(built, FailedBuild):
                    return StartupRefused("Build failed:\n" + build_failure_log(built))
        else:
            # Multiple documents: each document's build runs in the background, and the server comes up right
            # away (never waits N documents x tens of seconds). A failure never blocks startup - that document's tab opens an error panel instead.
            for D in self.docs:
                r = self.init_doc(D, no_build, wait=False)
                print(
                    "doc    %-10s %s %s%s"
                    % (
                        D.key,
                        "view-only" if D.is_pdf else "LaTeX   ",
                        D.rel_path(),
                        "" if isinstance(r, BuildSkipped) else "  (build started)",
                    )
                )
            self.RT.start_thread(self.watch_pdf_docs, self.RT.stopping)
        if self.C.git_pull:
            self.RT.start_thread(self.sync_service.watch, self.RT.stopping)
        with self.RT.pin_lock:
            self.render_pins_md(self.read_pins()[0])
        startup.tighten_state_perms(self.C.people_file)
        return None

    def report(self, docs: list[Doc] | None) -> None:
        """The startup summary on stdout (limn.startup.summary_lines): manuscript, label, state folder, address, access,
        and the optional features."""
        pdfjs_found = bool(self.vendor_file("pdf.min.mjs") and self.vendor_file("pdf.worker.min.mjs"))
        for line in startup.summary_lines(self.C, bool(docs), self.access_log_lines(), pdfjs_found):
            print(line)
        sys.stdout.flush()

    def listen(self) -> Server | StartupRefused:
        """Listen with a handler class bound only to this app, or return a port refusal."""
        handler = type("RunHandler", (Handler,), {"app": self})
        try:
            return (Server6 if ":" in self.C.access.bind else Server)((self.C.access.bind, self.C.port), handler)
        except OSError as e:
            return startup.listen_refusal(self.C.access.bind, self.C.port, e)


@dataclass(frozen=True)
class StartedServer:
    """One listening socket and the application whose runtime must stop when that socket closes."""

    server: Server
    app: ServerApplication


if TYPE_CHECKING:

    def _app_contract(app: ServerApplication) -> App:
        return app


def start(a: argparse.Namespace) -> StartedServer | StartupRefused:
    """Every startup step, in order, until one refuses: the access options (limn.startup.access_options: main() stops
    before any build, so a misconfigured unit fails fast), the --port probe, the run settings and documents,
    the ServerApplication with its Runtime and served viewer, the store and builds, the summary, then the
    listening server. A refusal or failure after creating the application stops any watch threads it began."""
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
    app = ServerApplication(run.config, new_runtime(serve_viewer(read_viewer(), run.config.label, run.config.accent)))
    try:
        prepared = app.prepare(run.docs, a.no_build)
        if prepared is not None:
            app.RT.stop()
            return prepared
        app.report(run.docs)
        result = app.listen()
        if isinstance(result, StartupRefused):
            app.RT.stop()
            return result
        return StartedServer(result, app)
    except BaseException:
        app.RT.stop()
        raise


def main() -> None:
    """The composition root: parse the arguments, then start() creates the application, prepares its documents,
    pin store and builds, starts the watch threads and opens the server; serve until stopped, then close the
    listening socket and stop the application's watch threads, even if
    socket closure fails. A serving error retains priority over cleanup errors; secondary cleanup errors are
    warned on stderr. The one place the process exits on a refused start: its message on stderr, status 1."""
    started = start(build_arg_parser().parse_args())
    if isinstance(started, StartupRefused):
        sys.exit(started.message)
    serving_error: BaseException | None = None
    try:
        started.server.serve_forever()
    except BaseException as e:
        serving_error = e
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        try:
            started.server.server_close()
        except BaseException as e:
            cleanup_errors.append(e)
        try:
            started.app.RT.stop()
        except BaseException as e:
            cleanup_errors.append(e)
        if cleanup_errors:
            if serving_error is None:
                for error in cleanup_errors[1:]:
                    print(f"warning: server cleanup failed: {error}", file=sys.stderr)
                raise cleanup_errors[0]
            for error in cleanup_errors:
                print(f"warning: server cleanup failed: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
