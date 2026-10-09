"""Shared fixtures of the server-level tests: the one loaded copy of server.py (ps), the Base fixture that points it at a
temporary manuscript and state folder, the socketpair request helpers, the node harness for the viewer's scripts, and
the viewer's source text and page images, and the test data more than one module checks (the reply rule's table
RULE_CASES with rec_for, a minimal PDF for the browser's comparison view, a figure's element map).

Every test module that drives server.py imports from here, so the process holds a single server copy with a fresh
application per Base test. The access fixtures (identities, AccessBase) are in
helpers_access.py and the browser ones (the Chromium launcher, BrowserBase) in helpers_browser.py. Test modules import
fixtures only from these helpers, never from one another.
"""

import dataclasses
import errno
import functools
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

import pytest

from limn.pins.editing import input as editing_input
from limn.pins.location import http as location_http
from limn.pins.model import parse_pin
from limn.pins.record import Broken
from limn.pins.store import find_pin
from limn.revisions import core as revisions
from limn.runtime import config
from limn.runtime.config import AccessOptions, RunConfig
from limn.security.access import LOCAL_ACTOR
from limn.viewer import assemble
from limn.web.errors import InputRejected

import helpers_js
from helpers_authority import post_authority

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
PKG = ROOT / "src" / "limn"
SKILL_MD = ROOT / "skill" / "SKILL.md"
SKILL_KO = ROOT / "skill" / "SKILL.ko.md"
DOCS_DIR = ROOT / "docs" / "handbook"
# server.py loaded from its file, the way an instance runs it; each Base test binds its own application to this copy.
spec = importlib.util.spec_from_file_location("limn_server", PKG / "server.py")
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)
# The viewer package, read once for every test: server.py reads it at startup (start), never at import. HTML is the page
# template - the viewer's source as the tests read it, run-time placeholders (__LABEL__, __ACCENT__...) still in it;
# UI_EN its ko -> en message table and SW_JS the service worker GET /sw.js serves.
VIEWER_FILES = ps.read_viewer()
HTML = VIEWER_FILES.template
UI_EN = VIEWER_FILES.messages
SW_JS = VIEWER_FILES.service_worker
# The viewer's closed-set tables (core.js: PIN_STATE, BUILD_STATE, LOCAL_LOGIN, ...), which extract_js_fn brings along.
VIEWER_CLOSED_SETS = helpers_js.closed_sets((PKG / "viewer" / "js" / "core.js").read_text(encoding="utf-8"))


def extract_js_fn(name: str) -> str:
    """The served page's top-level 'function NAME(...){...}' (with its 'async', if any), exactly as written, preceded by
    the closed-set tables it names (PIN_STATE, LOCAL_LOGIN, ... from core.js) as `var` declarations.

    Running the real source pulled this way through node lets a regression test verify the served code, not a copy the
    test pasted. The declaration is found by tokens (helpers_js), so braces, quotes and '//' inside strings, regexes
    and comments never cut it short; a name that no script declares at the top level, or declares twice, raises. The
    tables come along because a pulled function reads them from the page's shared scope, which a node harness lacks.
    """
    fn = helpers_js.function_source(HTML, name)
    return helpers_js.closed_set_prelude(VIEWER_CLOSED_SETS, fn) + fn


def js_markup() -> str:
    """The viewer's markup part (js/markup.js: Html, html``, ic(), setHtml()) exactly as served, for node harnesses that
    run functions building markup. It needs esc() (js_esc()) and, to draw an icon, ICONS (js_icons() brings both)."""
    return (VIEWER / "js" / "markup.js").read_text(encoding="utf-8")


def js_icons() -> str:
    """The viewer's Lucide icon table (ICONS) with the markup part that draws it (ic(), html``) — included together when
    running icon-drawing functions like card()/archiveRow() under node. Brings no esc(); add js_esc() if the harness
    has none."""
    m = re.search(r"const ICONS=\{.*?\};", HTML)
    return m.group(0) + "\n" + js_markup()


def js_esc() -> str:
    """The viewer's own esc() (HTML-escapes &<>"' and turns null into ''), as the page defines it - for node harnesses
    that run functions building markup, so they escape exactly as the viewer does instead of with a pasted copy."""
    return re.search(r"^const esc=.*;$", HTML, re.M).group(0)


def js_thread() -> str:
    """The native thread and card context renderers; callers supply actors, icons, and viewer state."""
    ev = re.search(r"^const EV_LABEL=.*;$", HTML, re.M).group(0)
    st = re.search(r"^const ST_NAME=.*;$", HTML, re.M).group(0)
    mo = re.search(r"^const MSG_OPEN=.*;$", HTML, re.M).group(0)
    return "\n".join(
        [ev, st, mo, "let PEOPLE=[];", extract_js_fn("hasRef")]
        + [
            extract_js_fn(n)
            for n in (
                "relTime",
                "relSpan",
                "msgBody",
                "isAgent",
                "isQuestion",
                "assigneeOf",
                "assigneeWord",
                "assignChip",
                "cardMetadata",
                "isViewer",
                "stDot",
                "reopenedTurn",
                "threadOf",
                "allMentions",
                "replyCount",
                "msgText",
                "msgHtml",
                "threadHtml",
                "pinState",
                "isMe",
                "reviewerLabel",
                "peopleName",
                "mentionToks",
                "mentionAfterWord",
                "reEsc",
                "meLogin",
                "pinRefExists",
                "pinRefGone",
                "fmtText",
                "pinRefs",
                "mentionsMe",
                "addressedTag",
                "fyiTag",
            )
        ]
    )


def js_i18n(lang: str = "ko") -> str:
    """The viewer's message functions tr()/tl()/trMsg()/errText() with the language fixed - pulled functions call
    them for every UI string and API error, so a node harness needs them. Korean (the source) unless lang='en'."""
    return "\n".join(
        [
            "var LANG=%s,I18N_EN=%s;" % (json.dumps(lang), json.dumps(UI_EN, ensure_ascii=False)),
            extract_js_fn("tr"),
            extract_js_fn("tl"),
            extract_js_fn("trMsg"),
            extract_js_fn("errText"),
        ]
    )


# The access options of a command line with no access flags (limn.runtime.startup.access_options' answer): tailscale identities,
# a loopback bind, the deprecated headerless loopback agent on - the v0.1-equivalent behaviour. Stated in full, so a
# change of a default shows up as a failing comparison in test_startup.
DEFAULT_ACCESS = AccessOptions(
    auth="tailscale",
    bind="127.0.0.1",
    agent_loopback=True,
    tailnet_agent=False,
    public_hosts=(),
    trusted_proxies=(ipaddress.ip_network("127.0.0.1/32"), ipaddress.ip_network("::1/128")),
    proxy_user_header="X-Forwarded-User",
    proxy_name_header="X-Forwarded-Preferred-Username",
    proxy_email_header=None,
    members_only=False,
    local_user=None,
    insecure=False,
    agent_token_file=None,
)
ACCESS_FIELDS = frozenset(f.name for f in dataclasses.fields(AccessOptions))


def run_config(src: Path, main: Path, state: Path, **over) -> RunConfig:
    """The run settings Base serves with (manuscript src, main file main, state folder state; port 18999, 150 dpi, a
    60-second build timeout, the default float environments, label 원고 in the first accent, no origin URL, access
    options at their defaults, no --ui-lang), with `over` replacing settings by name - an access option's name (auth, bind, ...)
    replaces that field of .access."""
    base = RunConfig(
        src=src,
        main=main,
        state=state,
        port=18999,
        dpi=150,
        envs=tuple(ps.DEFAULT_ENVS.split(",")),
        timeout=60,
        allow=frozenset(),
        origin_check=True,
        git_pull=False,
        pdfjs_dir=None,
        label="원고",
        accent=config.ACCENT_PALETTE[0],
        repo=None,
        access=DEFAULT_ACCESS,
        ui_lang=None,
    )
    return with_settings(base, **over)


def with_settings(c: RunConfig, **over) -> RunConfig:
    """c with `over` replacing settings by name (dataclasses.replace); an access option's name replaces that field of
    c.access."""
    acc = {k: over.pop(k) for k in list(over) if k in ACCESS_FIELDS}
    if acc:
        over["access"] = dataclasses.replace(over.get("access", c.access), **acc)
    return dataclasses.replace(c, **over)


def set_config(mod=None, **over) -> None:
    """Bind the server copy (default ps) to its run settings with `over` replaced (with_settings), as a restart with
    those options would. When a run path (src, main, state) changes and the copy serves the single document, that
    document is made again over the new paths (set_docs), as start() would make it."""
    mod = mod or ps
    old = mod.APP.C
    mod.APP.C = with_settings(old, **over)
    if mod.APP.C.paths != old.paths and len(mod.APP.docs) == 1 and mod.APP.docs[0].legacy:
        mod.APP.set_docs(None)


def page_for(label: str, accent: str, ui_lang: str | None = None) -> str:
    """The page GET / serves on a run labelled `label` in `accent` with --ui-lang ui_lang (None: not given;
    limn.viewer.assemble.run_page over HTML)."""
    return assemble.run_page(HTML, label, accent, ui_lang)


def fresh_runtime(mod=None) -> None:
    """Bind a fresh Runtime (new_runtime) on the server copy (default ps), as a restarted process has: new locks,
    empty caches and registries, no threads, serving the viewer for its run's label, accent and interface language."""
    mod = mod or ps
    c = mod.APP.C
    mod.APP.RT = mod.new_runtime(assemble.serve_viewer(VIEWER_FILES, c.label, c.accent, c.ui_lang))


def serve_viewer(label: str, accent: str, mod=None) -> None:
    """Make the server copy (default ps) serve the viewer of a run labelled `label` in `accent` (with its run's
    interface language), as start() does."""
    mod = mod or ps
    served = assemble.serve_viewer(VIEWER_FILES, label, accent, mod.APP.C.ui_lang)
    mod.APP.RT = dataclasses.replace(mod.APP.RT, viewer=served)


def needs_tex(*tools: str):
    """Decorator for a test method that runs real TeX-side tools (latexmk, pdftoppm, pdftotext, latexdiff, bwrap...).

    Before the test body runs, every name in tools must be on PATH. A missing one skips the test and names what is
    missing, unless LIMN_TEST_REQUIRE_TEX=1 (the CI `tex` job), where it is a failure. The test also gets the pytest
    marker `tex`, so that job selects exactly these tests with `pytest -m tex`."""

    def wrap(fn):
        """Guard fn with the PATH check and mark it `tex`."""

        @functools.wraps(fn)
        def guarded(self, *args, **kwargs):
            """Skip (or fail under LIMN_TEST_REQUIRE_TEX=1) when a tool is missing; otherwise run the test."""
            missing = [t for t in tools if not shutil.which(t)]
            if missing:
                if os.environ.get("LIMN_TEST_REQUIRE_TEX") == "1":
                    self.fail("%s required (LIMN_TEST_REQUIRE_TEX=1) but not installed" % ", ".join(missing))
                self.skipTest("%s not available" % ", ".join(missing))
            return fn(self, *args, **kwargs)

        return pytest.mark.tex(guarded)

    return wrap


def run_node(js: str, tz: str = None):
    """Run js under node and return stdout. Returns None if node is missing (handled on the test side).

    The script goes to node on stdin (`node -`), not as an `-e` argument: Linux caps one argument at 128 KB
    (MAX_ARG_STRLEN), and a harness that inlines a corpus passes that.

    If tz is given, run in that timezone — used to directly verify that isEstimated no
    longer reads the wall clock (the frac_build path). The Korean tr()/tl() are prepended unless the
    script defines its own (see js_i18n)."""
    node = shutil.which("node")
    if not node:
        return None
    if "function tl(" not in js:
        js = js_i18n() + "\n" + js
    env = dict(os.environ)
    if tz is not None:
        env["TZ"] = tz
    r = subprocess.run([node, "-"], input=js, capture_output=True, text=True, timeout=15, env=env, check=False)
    if r.returncode != 0:
        raise AssertionError("node execution failed:\n%s" % r.stderr)
    return r.stdout


def shut_wr(sock: socket.socket) -> None:
    """Half-close the client side of a test socketpair after sending a request.

    The handler may already have answered and closed its end (an early 4xx does), and then macOS
    refuses the half-close with ENOTCONN (Linux may say EPIPE or ECONNRESET). The response is
    still buffered for recv(), so those errors are not failures; anything else still raises.
    """
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError as exc:
        if exc.errno not in (errno.ENOTCONN, errno.EPIPE, errno.ECONNRESET):
            raise


def add_pin(d: dict, actor: dict, mod=None, doc=None):
    """What POST /api/pin does below its HTTP answer (limn.web.handler) for the request's document doc (default the
    first): the body's doc wins over it, the body is parsed against that document (limn.pins.editing.input.parse_add), and the
    service saves it. Returns the new open pin, or the InputRejected of the first refused field. mod is the server copy
    to use (default ps)."""
    mod = (mod or ps).APP
    D = doc or mod.docs[0]
    want = d.get("doc")
    if isinstance(want, str) and want != D.key:
        D = mod.request_doc(want)
    request = editing_input.parse_add(d, mod.editing_requests.assignee_people(d), mod.document_facts(D))
    return (
        request
        if isinstance(request, InputRejected)
        else mod.pin_editing.add_pin(D, request, post_authority(mod.pin_editing.context().store, actor, "add", D))
    )


def edit_pin(pid: int, d: dict, actor: dict, mod=None):
    """What POST /api/pins/{pid}/edit does below its HTTP answer: parse the body, place its loc against the pin's own
    document (edit_scope), then edit. Returns the edit's outcome, or the InputRejected of the first refused field."""
    mod = (mod or ps).APP
    body = editing_input.parse_edit(d, mod.editing_requests.assignee_people(d))
    if isinstance(body, InputRejected):
        return body
    region, pdoc = mod.editing_requests.edit_scope(pid)
    place = editing_input.parse_edit_place(body, region, mod.document_facts(pdoc))
    if isinstance(place, InputRejected):
        return place
    return mod.pin_editing.edit_pin(
        pid,
        dataclasses.replace(body.request, place=place),
        post_authority(mod.pin_editing.context().store, actor, "edit", pid),
        region,
    )


def pick(d: dict, mod=None, doc=None):
    """The POST /api/pick body for one document, through its feature HTTP entry."""
    mod = (mod or ps).APP
    return location_http.pick(mod, doc or mod.docs[0], d)


def revision_spec(commit: str, pin: int | None = None, mod=None, doc=None):
    """What a comparison request of document doc (default the first) compares (limn.revisions.core.revision_spec with the
    server copy's context), or its refusal value."""
    mod = (mod or ps).APP
    return revisions.revision_spec(doc or mod.docs[0], commit, pin, mod.revision_context())


def record_of(outcome) -> dict:
    """The pin as the API returns it, from a close/reopen outcome (a state type, or AlreadyClosed carrying one)."""
    pin = getattr(outcome, "pin", outcome)
    return ps.APP.public(pin.record)


def fits(r, mod=None) -> bool:
    """Does the server copy's record parse (parse_record) let r through - a record the store trusts?"""
    return not isinstance((mod or ps).APP.parse_record(r), Broken)


def records(parsed) -> list:
    """The stored records of parsed pins or Trash entries (what the store hands out), each as it is written."""
    return [p.record for p in parsed]


def find_record(parsed, pid: int) -> dict | None:
    """The stored record of the first parsed pin whose id is pid, or None."""
    return find_pin(records(parsed), pid)


def trash_records(mod=None) -> list:
    """The Trash entries of the server copy's state folder as stored (every readable line, expired ones too)."""
    return records((mod or ps).APP.read_dropped()[0])


def edit_stored(fn, mod=None) -> None:
    """Hand-edit the live pins in one transaction of the server copy's store, as a person editing pins.jsonl would:
    fn(records) changes the stored records in place (it may also append or remove); each is parsed back into its
    state and the file is rewritten."""

    def step(pins):
        """The transact() step: the records edited by fn replace the pins."""
        rows = records(pins)
        fn(rows)
        pins[:] = [parse_pin(r) for r in rows]
        return None, True

    (mod or ps).APP.pin_store().transact(step)


def write_records(rows, bad=None, mod=None) -> None:
    """Rewrite pins.jsonl (and pins.md) of the server copy with these stored records, parsed into their states. The
    caller holds no lock: this is a test's hand edit."""
    (mod or ps).APP.write_pins([parse_pin(r) for r in rows], bad)


# The fixture manuscript Base writes as main.tex: a section, comments, a table float and a subsection, with a rare word
# on most lines so a test can find the line a pick or a quote came from.
TEX = """\\documentclass{article}
\\begin{document}
\\section{Intro}
First paragraph line one about rarewordalpha.
First paragraph line two.

% TODO 주석
Body line seven betaunique.
Body line eight gammaunique.
% 꼬리 주석

\\begin{table}
\\begin{tabular}{l}
cell deltaunique \\\\
\\end{tabular}
\\end{table}
After table epsilonunique.
\\subsection{Next}
Tail paragraph zetaunique.
\\end{document}
"""


class ApplicationFixture:
    """Adapt legacy test helpers to an assembly without widening the production HTTP collaborators."""

    def __init__(self, settings, runtime, module=ps):
        """Create an isolated assembly; callbacks read its current test settings and resources."""
        self.assembly = module.assemble_application(settings, runtime)

    def __getattr__(self, name):
        """Resolve test operations at their actual capability owner."""
        app = self.assembly
        fixed = {
            "C": app.environment.C,
            "RT": app.environment.RT,
            "docs": app.environment.docs,
            "web": app.web,
            "build_requests": app.builds.commands._requests,
            "people_directory": app.collaboration.people,
            "notices": app.collaboration.notices,
            "document_views": app.documents.views,
            "sync_service": app.sync.service,
            "revision_requests": app.revisions.requests,
            "pin_actions": app.web.routes.bundle.pin_actions,
            "other_posts": app.web.routes.bundle.other_posts,
        }
        if name in fixed:
            return fixed[name]
        for owner in (app.pins.commands, app.security, app.web.guards):
            if hasattr(owner, name):
                return getattr(owner, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        """Keep replacements in tests at the resource or service the callbacks actually use."""
        if name == "assembly":
            object.__setattr__(self, name, value)
        elif name in ("C", "RT"):
            setattr(self.assembly.environment, name, value)
        elif name == "docs":
            self.assembly.environment.docs[:] = value
        elif hasattr(self.assembly.pins.commands, name):
            setattr(self.assembly.pins.commands, name, value)
        else:
            object.__setattr__(self, name, value)

    def __delattr__(self, name):
        """Allow mock.patch to restore a temporarily replaced pin collaborator."""
        if name in self.__dict__:
            object.__delattr__(self, name)
        elif name not in ("C", "RT", "docs"):
            delattr(self.assembly.pins.commands, name)

    def set_docs(self, documents):
        """Replace served documents in place so every bound capability sees the new list."""
        self.docs[:] = documents or [ps.Doc(ps.DEFAULT_DOC_KEY, "본문", legacy=True, paths=self.C.paths)]

    def viewer(self):
        """Read the current served viewer for viewer-specific test helpers."""
        return self.RT.viewer

    def request_doc(self, key, hint=None):
        """Choose a test target through the same document selector as HTTP."""
        return self.web.selector.select(key, hint)

    def access_settings(self):
        """Read the security settings for tests exercising identity directly."""
        return self.C.access_settings

    def revision_context(self):
        """Read the revision owner's current context for its focused tests."""
        return self.assembly.revisions.requests.context()

    def prepare(self, documents, no_build):
        """Exercise the real startup orchestration for state-recovery tests."""
        return ps.prepare(self.assembly, documents, no_build)

    def access_log_lines(self):
        """Render the actual startup security summary for configuration tests."""
        return ps.startup.access_log_lines(
            self.C.access, len(self.current_tokens()), ps.file_present(self.C.access.agent_token_file)
        )

    def remote_base_for(self, host):
        """Read the request link base using the production security policy."""
        return ps.access.remote_base_for(host, self.C.access.public_hosts, self.C.port)


class Base(unittest.TestCase):
    """server.py pointed at a fresh temporary manuscript (main.tex = TEX) and state folder: one document, no pins, an
    idle build, default run settings. Tests drive it through ps's functions or the handler (talk)."""

    def setUp(self):
        """Bind the server copy's run settings and a fresh Runtime (as a restarted process has) for this test, and the
        single document with its idle build."""
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / "ms"
        self.src.mkdir()
        self.main = self.src / "main.tex"
        self.main.write_text(TEX, encoding="utf-8")
        (root / "state").mkdir()
        config = run_config(self.src, self.main, root / "state")
        ps.APP = ApplicationFixture(
            config, ps.new_runtime(assemble.serve_viewer(VIEWER_FILES, config.label, config.accent, config.ui_lang))
        )
        ps.Handler.app = ps.APP.web
        ps.APP.set_docs(None)  # start as a single document (no --doc) — clears the list left over from multi-doc tests
        ps.APP.init_seq()

    def tearDown(self):
        """Remove the temporary manuscript and state folder."""
        self.tmp.cleanup()

    def add(self, lo=4, hi=5, note="n", actor=None):
        """Add a pin on main.tex lines lo-hi (page 1) as actor (default the local agent); returns its id."""
        return add_pin(
            {"file": str(self.main), "lo": lo, "hi": hi, "page": 1, "note": note}, actor or dict(LOCAL_ACTOR)
        ).record["id"]

    def pin(self, pid):
        """The stored record of pin pid after a synced read, or None."""
        return find_record(ps.APP.snapshot_pins(), pid)

    def talk(self, raw: bytes, shut=True) -> bytes:
        """Send raw over one connection and collect response bytes until the server closes it."""
        a, b = socket.socketpair()

        def serve():
            try:
                ps.Handler(b, ("127.0.0.1", 0), None)
            finally:
                b.close()  # this is socketserver's shutdown_request duty

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        a.sendall(raw)
        if shut:
            shut_wr(a)
        a.settimeout(10)
        out = b""
        try:
            while True:
                chunk = a.recv(65536)
                if not chunk:
                    break
                out += chunk
        finally:
            a.close()
        t.join(10)
        return out


def split_resp(out: bytes):
    """Split one response's bytes into (status code, lowercase header dict, body)."""
    head, _, body = out.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    code = int(lines[0].split()[1])
    hdrs = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        hdrs[k.strip().lower()] = v.strip()
    return code, hdrs, body


def req(method, path, body=b"", headers=None):
    """The raw bytes of one HTTP/1.1 request to the test server's loopback Host, with Content-Length for a body."""
    h = {"Host": "127.0.0.1:18999"}
    h.update(headers or {})
    if body:
        h["Content-Length"] = str(len(body))
    head = "%s %s HTTP/1.1\r\n" % (method, path) + "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n"
    return head.encode() + body


def blank_png(w: int, h: int) -> bytes:
    """A white 8-bit grayscale PNG of w x h pixels (the viewer only needs real page images and their size)."""

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\xff" * w for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# Stand-in TeX-side tools held at gates (GatedBuild). Each one leaves a file named for its step in $LIMN_TEST_GATES when it
# starts - `latex`, or the page number - and waits until the test creates `go-<step>` there (20 s at most, then it fails),
# so a test reads the build's state between its steps. latexmk copies main.tex to the PDF and writes SyncTeX and an empty
# log; pdfinfo says $LIMN_TEST_PAGES pages; pdftoppm (-r DPI -f N -l N -singlefile PDF) writes page N as a 2x1 PPM.
GATED_LATEXMK = """#!/bin/sh
for a; do main=$a; done
stem=${main%.tex}
touch "$LIMN_TEST_GATES/latex"
i=0
until [ -e "$LIMN_TEST_GATES/go-latex" ]; do i=$((i + 1)); [ "$i" -gt 800 ] && exit 9; sleep 0.025; done
cp "$main" "$stem.pdf"
printf 'synctex' > "$stem.synctex.gz"
: > "$stem.log"
"""
GATED_PDFINFO = """#!/bin/sh
echo "Pages:          $LIMN_TEST_PAGES"
"""
GATED_PDFTOPPM = """#!/bin/sh
page=$4
touch "$LIMN_TEST_GATES/$page"
i=0
until [ -e "$LIMN_TEST_GATES/go-$page" ]; do i=$((i + 1)); [ "$i" -gt 800 ] && exit 9; sleep 0.025; done
printf 'P6\\n2 1\\n255\\n\\377\\377\\377\\0\\0\\0'
"""


class GatedBuild:
    """A real build whose latexmk and per-page pdftoppm wait at gates the test opens, so the test can read the build
    state (GET /api/build, the viewer's status line) between the TeX pass and each page. The stand-ins (GATED_LATEXMK,
    GATED_PDFINFO, GATED_PDFTOPPM) go first on PATH for the test's duration - an environment patch the in-process
    server's subprocesses inherit - and every gate is opened when the test ends, so a failed test never leaves a build
    waiting. A step is 'latex' or a page number."""

    def __init__(self, test: unittest.TestCase, root: Path, pages: int) -> None:
        """Write the stand-ins under root and patch PATH for test; the PDF they make has `pages` pages."""
        self.gates = root / "gates"
        self.gates.mkdir()
        bin_dir = root / "gated-bin"
        bin_dir.mkdir()
        for name, text in (("latexmk", GATED_LATEXMK), ("pdfinfo", GATED_PDFINFO), ("pdftoppm", GATED_PDFTOPPM)):
            (bin_dir / name).write_text(text, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        env = mock.patch.dict(
            os.environ,
            {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "LIMN_TEST_GATES": str(self.gates),
                "LIMN_TEST_PAGES": str(pages),
            },
        )
        env.start()
        test.addCleanup(env.stop)
        test.addCleanup(self.release_all)
        self.pages = pages

    def started(self, step: str | int) -> bool:
        """Whether the stand-in of step has started (and so waits at its gate, or has passed it)."""
        return (self.gates / str(step)).exists()

    def wait_started(self, step: str | int, timeout: float = 10.0) -> None:
        """Wait until step's stand-in has started; fail after timeout seconds."""
        end = time.monotonic() + timeout
        while not self.started(step):
            if time.monotonic() > end:
                raise AssertionError("the %s stand-in never started" % step)
            time.sleep(0.02)

    def release(self, step: str | int) -> None:
        """Open step's gate: its stand-in finishes its work."""
        (self.gates / ("go-%s" % step)).touch()

    def release_all(self) -> None:
        """Open every gate (the TeX pass and each page). Nothing to open once the test's folder is gone (a fixture's
        tearDown removes it before the cleanups run): the stand-ins then give up after their 20 s."""
        if not self.gates.is_dir():
            return
        for step in ["latex", *range(1, self.pages + 1)]:
            self.release(step)


# The viewer's build-free source folder (index.html, parts.txt, css/, js/).
VIEWER = PKG / "viewer"


def viewer_text(marker: str, directory: Path = VIEWER) -> str:
    """The text the server puts at marker: the manifest's parts for it, joined in order."""
    return "".join((directory / n).read_text(encoding="utf-8") for n in assemble.viewer_manifest(directory)[marker])


# the smallest PDF that pdftoppm/pdftotext can read (one page, one line of text). poppler rebuilds the xref itself.
MINI_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 150 Td (Reviewer one) Tj ET\nendstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)


def jreq(method, path, obj=None, headers=None):
    """req() with obj sent as a JSON body (Content-Type application/json); no body when obj is None."""
    body = json.dumps(obj).encode() if obj is not None else b""
    h = {"Content-Type": "application/json"} if obj is not None else {}
    h.update(headers or {})
    return req(method, path, body, h)


# The reply rule as a table (docs/handbook/domain.md §전이와 할 수 있는 쪽): every (state, kind_req, human, mentioned,
# override) with whether a reply reopens the pin. The server's rule (limn.pins.lifecycle.test_rules.ReplyRule) and the viewer's
# preview of it (test_viewer.FrontendReplyRule) are both checked against every row.
# (state, kind_req, human, mentioned, override) -> reopens?
RULE_CASES = []
for _st in ("open", "review", "done"):
    for _kind in ("fix", "question"):
        for _human in (True, False):
            for _ment in ([], ["bob@example.com"]):
                for _ov in (None, True, False):
                    if _st == "open":
                        _want = False
                    elif _ov is not None:
                        _want = _ov
                    else:
                        _want = _kind == "fix" and _human and not _ment
                    RULE_CASES.append((_st, _kind, _human, _ment, _ov, _want))


def rec_for(state, kind):
    """A minimal stored record of a pin in `state` ("open", "review" or "done") whose kind_req is `kind`."""
    r = {"id": 1, "file": "/m.tex", "lo": 1, "hi": 2, "kind_req": kind}
    if state != "open":
        r["done"] = True
    if state == "review":
        r["review"] = True
    return r


def minimal_pdf(label: str = "") -> bytes:
    """A valid one-page PDF (pdf.js renders it) - browser tests stand in for latexdiff/latexmk, which CI does not have."""
    stream = b"BT /F1 24 Tf 72 700 Td (" + label.encode("ascii") + b") Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


def figure_map(pdf: bytes, pdf_name: str = "figures.pdf") -> dict:
    """The element map (limn-figure-map/1) of the design's example - one page, figure B2 with a calendar strip and its
    July cell, whose code lines are in src/B2_calendar.py and whose shared component is in lib/components.py - that
    describes the PDF bytes pdf and names that PDF pdf_name, relative to the map's folder."""
    return {
        "format": "limn-figure-map/1",
        "pdf": pdf_name,
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "pages": [
            {
                "page": 1,
                "figure": "B2",
                "title": "Deployment calendar",
                "elements": [
                    {"id": "B2", "frac": [0, 0, 1, 1], "src": {"file": "src/B2_calendar.py", "lo": 12, "hi": 140}},
                    {
                        "id": "B2/calendar",
                        "parent": "B2",
                        "part": "CalendarStrip",
                        "label": "달력",
                        "frac": [0.06, 0.18, 0.88, 0.12],
                        "src": {"file": "src/B2_calendar.py", "lo": 80, "hi": 97},
                    },
                    {
                        "id": "B2/calendar/m07",
                        "parent": "B2/calendar",
                        "part": "MonthCell",
                        "label": "7월",
                        "frac": [0.47, 0.18, 0.07, 0.12],
                        "src": {"file": "src/B2_calendar.py", "lo": 88, "hi": 95},
                        "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
                    },
                ],
            }
        ],
    }


def map_bytes(m: dict) -> bytes:
    """The bytes a producer writes for map m: its JSON text with non-ASCII escaped, so a lone surrogate stays
    expressible for the tests that need one."""
    return json.dumps(m).encode("ascii")
