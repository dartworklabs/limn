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
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar, TypeAlias

if __package__ in (None, ""):
    # Run as a file (python .../limn/server.py, how instances start): make the sibling modules importable as limn.*.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Capability implementations assemble their own routes; this entrypoint only wires run ports.
from limn.administration import doc_start_line, docs_of, pick_documents
from limn.builds import (
    BuildMapCache,
    BuildSubsystem,
    assemble_builds,
)
from limn.collaboration import CollaborationSubsystem, assemble_collaboration
from limn.documents import DocumentsSubsystem, MetaSettings, assemble_documents
from limn.pins import (
    PinSubsystem,
    TokenCache,
    assemble_pins,
)
from limn.platform.files import vendor_file as find_vendor_file
from limn.platform.git import git as _git
from limn.revisions import (
    RevisionJobs,
    RevisionSubsystem,
    ScopeCache,
    assemble_revisions,
)
from limn.runtime import documents as runtime_documents, startup
from limn.runtime.args import serve_parser
from limn.runtime.config import AccessOptions, RunConfig
from limn.runtime.documents import DEFAULT_DOC_KEY, Doc
from limn.runtime.resources import RuntimeResources
from limn.runtime.startup import APP_NAME as APP_NAME, StartupRefused, app_version as app_version
from limn.security import access
from limn.security.access import (
    DEFAULT_ROLE as DEFAULT_ROLE,
    file_present,
    hdr_text as hdr_text,
)
from limn.security.application import SecurityApplication
from limn.sync import PullShare, SyncContext, SyncSubsystem, SyncWatch, assemble_sync
from limn.viewer import (
    ServedViewer,
    assemble_viewer,
    default_pdfjs_dir as default_pdfjs_dir,
    read_viewer as read_viewer,
    serve_viewer as serve_viewer,
)
from limn.web.app import DocumentSelector, RouteRegistry, WebApplication
from limn.web.errors import HTTPError as HTTPError
from limn.web.handler import Handler as WebHandler, Server, Server6
from limn.web.routes import merge_routes

DEFAULT_ENVS = "figure,table,algorithm,equation,align,itemize,enumerate,minipage"

RunResources: TypeAlias = RuntimeResources[
    ServedViewer, ScopeCache, RevisionJobs, PullShare, SyncWatch, TokenCache, BuildMapCache
]


def new_runtime(viewer: ServedViewer) -> RunResources:
    """A process's resources, all fresh: new locks, empty caches and registries, no threads, serving viewer."""
    return RuntimeResources(
        viewer, ScopeCache(), RevisionJobs(), PullShare(), SyncWatch(), TokenCache(), BuildMapCache()
    )


# ---------------------------------------------------------------- HTTP handler wiring (the handler is limn/web/handler.py)


class Handler(WebHandler):
    """Base handler for a server copy; each listener binds its own subclass to one application."""

    app: ClassVar[WebApplication]


# ---------------------------------------------------------------- Entry point


def build_arg_parser() -> argparse.ArgumentParser:
    """The `limn serve` argument parser (limn.runtime.args) with this server's one-line description, version and --float-envs
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
    rules are limn.runtime.startup's; this applies their answers and makes the --doc documents once the paths are known.
    """
    src = Path(a.manuscript).expanduser().resolve()
    picked = pick_documents(src, a.doc, a.main)
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
        ui_lang=a.ui_lang,
    )
    return RunStart(config, docs_of(picked.docs, config.paths) if picked.docs else None)


@dataclass
class RunEnvironment:
    """Configuration and resources read by one assembled run's deferred bindings."""

    C: RunConfig
    RT: RunResources
    docs: list[Doc] = field(default_factory=list)


@dataclass(frozen=True)
class ServerAssembly:
    """Capability results and the concrete HTTP application owned by one run."""

    environment: RunEnvironment
    pins: PinSubsystem
    builds: BuildSubsystem
    collaboration: CollaborationSubsystem
    documents: DocumentsSubsystem
    revisions: RevisionSubsystem
    sync: SyncSubsystem
    security: SecurityApplication
    web: WebApplication


def timestamp() -> str:
    """Return the local wall-clock timestamp stored on build and pin actions."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def assemble_application(config: RunConfig, runtime: RunResources) -> ServerAssembly:
    """Wire capability ports without reading or writing application files."""
    environment = RunEnvironment(config, runtime)

    def settings() -> RunConfig:
        """Read the settings bound to this run."""
        return environment.C

    def resources() -> RunResources:
        """Read the resources owned by this run."""
        return environment.RT

    docs = environment.docs
    sync: SyncSubsystem
    collaboration: CollaborationSubsystem
    security: SecurityApplication
    builds = assemble_builds(
        settings,
        lambda: sync.service.repo_pull(),
        lambda: docs,
        timestamp,
        maps=lambda: resources().figure_maps,
        figure_shown=lambda: pins.commands.refresh_pins_md(),
    )
    pins = assemble_pins(
        settings=settings,
        resources=resources,
        docs=docs,
        builds=builds.pins,
        known_people=lambda records: collaboration.people.known(records),
        notice_sink=lambda notice: collaboration.notices.make_event(notice),
        emit_events=lambda events: collaboration.notices.emit_events(events),
        recent_events=lambda: collaboration.notices.read()[0],
        role_of=lambda login: security.role_of(login),
        audit=lambda action, by, details: security.http_audit(action, by, details),
        now=timestamp,
        remote_base_for=lambda host: access.remote_base_for(host, settings().access.public_hosts, settings().port),
        refresh_watched=lambda key: sync.service.refresh_watched(key),
    )
    collaboration = assemble_collaboration(
        state=lambda: settings().state,
        people_file=lambda: settings().people_file,
        people_lock=lambda: resources().people_lock,
        seen=lambda: resources().people_seen,
        warning=lambda: resources().people_warning,
        participants=pins.participants,
        roles=lambda: security.people_roles(),
        events_path=lambda: settings().events_file,
        events_lock=lambda: resources().events_lock,
        cache=lambda: resources().events_cache,
        clock=lambda: time.time(),
        stamp=lambda: pins.commands.now_str(),
        docs=lambda: docs,
    )
    security = SecurityApplication(settings, resources, collaboration.people.load)
    sync = assemble_sync(
        lambda: SyncContext(
            manuscript=settings().src,
            enabled=settings().git_pull,
            docs=docs,
            share=resources().pull_share,
            watch=resources().sync_watch,
            start_build=builds.commands.build_async,
            last_failed=builds.last_failed,
            built_head=builds.published_head,
            refresh_now=builds.commands.refresh_now,
            git=_git,
            clock=time.time,
        )
    )
    documents_subsystem = assemble_documents(
        settings=lambda: MetaSettings(
            state=settings().state,
            pins_md=settings().pins_md,
            label=settings().label,
            accent=settings().accent,
            repo=settings().repo,
            dpi=settings().dpi,
        ),
        docs=docs,
        sync_status=sync.service.status,
        pins=pins.counts,
        events_since=collaboration.notices.since,
        now=lambda: time.time(),
        builds=builds.documents,
    )
    revisions = assemble_revisions(
        timeout=lambda: settings().timeout,
        pins=pins.revision,
        cache=lambda: resources().scope_cache,
        jobs=lambda: resources().revision_jobs,
        history_files=builds.revisions.history_files,
        overlay=builds.revisions.overlay,
    )
    viewer = assemble_viewer(settings, lambda: resources().viewer)
    routes = merge_routes(
        viewer.routes, builds.routes, revisions.routes, documents_subsystem.routes, collaboration.routes, pins.routes
    )

    def authority_scope(operation: str) -> access.AuthorityScope:
        """Select the effect owner whose resources authorize this operation."""
        if operation == "rebuild":
            return builds.commands.authority_scope
        if operation == "revision-build":
            return revisions.requests.authority_scope
        return pins.commands.pin_context().authority_scope

    web = WebApplication(
        settings,
        security.guards(lambda: docs, authority_scope, pins.commands.retention_days),
        DocumentSelector(lambda key, hint: runtime_documents.request_doc(docs, settings().src, key, hint)),
        RouteRegistry(routes),
        collaboration.people,
        lambda: resources().viewer.messages,
        hdr_text,
    )
    return ServerAssembly(environment, pins, builds, collaboration, documents_subsystem, revisions, sync, security, web)


def prepare(app: ServerAssembly, documents: list[Doc] | None, no_build: bool) -> StartupRefused | None:
    """Initialize pin files, builds and watches before rendering markdown and tightening state permissions."""
    environment = app.environment
    environment.docs[:] = documents or [Doc(DEFAULT_DOC_KEY, "본문", legacy=True, paths=environment.C.paths)]
    app.pins.startup.initialize_sequence()
    app.pins.commands.pin_trash.purge_trash()
    for doc in environment.docs:
        result = app.builds.commands.initialize(doc, no_build, wait=not documents)
        if not documents and result.refusal is not None:
            return result.refusal
        if documents:
            print(doc_start_line(doc.key, doc.kind, doc.rel_path(), result.started))
    if documents:
        environment.RT.start_thread(app.builds.commands.watch, environment.RT.stopping)
    if environment.C.git_pull:
        environment.RT.start_thread(app.sync.service.watch, environment.RT.stopping)
    app.pins.startup.render_markdown()
    startup.tighten_state_perms(environment.C.people_file)
    return None


def report(app: ServerAssembly, documents: list[Doc] | None) -> None:
    """Print the configured run summary after startup preparation succeeds."""
    config = app.environment.C
    pdfjs = config.pdfjs_dir or default_pdfjs_dir()
    pdfjs_found = all(find_vendor_file(pdfjs, name, (".mjs",)) for name in ("pdf.min.mjs", "pdf.worker.min.mjs"))
    access_lines = startup.access_log_lines(
        config.access, len(app.security.current_tokens()), file_present(config.access.agent_token_file)
    )
    for line in startup.summary_lines(config, bool(documents), access_lines, pdfjs_found):
        print(line)
    sys.stdout.flush()


def listen(app: WebApplication) -> Server | StartupRefused:
    """Bind one listener to its concrete HTTP application or return the existing port refusal."""
    config = app.settings()
    handler = type("RunHandler", (Handler,), {"app": app})
    try:
        return (Server6 if ":" in config.access.bind else Server)((config.access.bind, config.port), handler)
    except OSError as error:
        return startup.listen_refusal(config.access.bind, config.port, error)


@dataclass(frozen=True)
class StartedServer:
    """One listening socket and the application whose runtime must stop when that socket closes."""

    server: Server
    app: WebApplication
    runtime: RunResources


def start(a: argparse.Namespace) -> StartedServer | StartupRefused:
    """Every startup step, in order, until one refuses: the access options (limn.runtime.startup.access_options: main() stops
    before any build, so a misconfigured unit fails fast), the --port probe, the run settings and documents,
    the capability assembly with its resources and served viewer, the store and builds, the summary, then the
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
    app = assemble_application(
        run.config, new_runtime(serve_viewer(read_viewer(), run.config.label, run.config.accent, run.config.ui_lang))
    )
    try:
        prepared = prepare(app, run.docs, a.no_build)
        if prepared is not None:
            app.environment.RT.stop()
            return prepared
        report(app, run.docs)
        result = listen(app.web)
        if isinstance(result, StartupRefused):
            app.environment.RT.stop()
            return result
        return StartedServer(result, app.web, app.environment.RT)
    except BaseException:
        app.environment.RT.stop()
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
            started.runtime.stop()
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
