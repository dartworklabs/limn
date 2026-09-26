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
import contextlib
import errno
import fcntl
import hashlib
import hmac
import html
import ipaddress
import json
import math
import os
import pwd
import re
import secrets
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter
from datetime import datetime
from email.header import decode_header, make_header
from pathlib import Path
from collections.abc import Callable, Collection, Sequence
from typing import NamedTuple
from urllib.parse import quote, urlparse

if __package__ in (None, ""):
    # Run as a file (python .../limn/server.py, how instances start): make the sibling modules importable as limn.*.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from limn.pins.lifecycle import (  # noqa: E402 - after the path bootstrap above
    AgentCannotConfirm, AlreadyClosed, AlreadyDone, AlreadyLive, ClaimClosedPin, ClaimedByOther, ClaimRequest,
    CloseRequest, NotClaimed, NotInTrash, PinReopened, PinStillOpen, Replied, ThreadFull, claim, claim_holds,
    confirm, confirmer, decide_close, decide_reopen, decide_reply, drop, evolve_close, evolve_reopen, evolve_reply,
    find_trashed, reopen_request, reopens_on_reply, restore, unclaim,
)
from limn.pins.edit import (  # noqa: E402 - after the path bootstrap above
    ASSIGNEE_AGENT, KIND_REQS, LOCAL_LOGIN, NOTE_MAX, AddRequest, Anchoring, EditRefusal, EditRequest,
    LinePlace, Located, PinEdited, RegionPlace, decide_edit, evolve_edit, file_after, new_line_pin, new_region_pin,
)
from limn.pins.model import (  # noqa: E402 - after the path bootstrap above
    Actor, Agent, DonePin, OpenPin, Person, PinNotFound, ReviewPin, TrashedPin, is_region_pin, parse_pin,
)
from limn import build  # noqa: E402 - after the path bootstrap above
from limn.build import BuildConfig  # noqa: E402 - after the path bootstrap above
from limn.files import atomic_write  # noqa: E402 - after the path bootstrap above
from limn.store import PinFiles, PinStore, find_pin  # noqa: E402 - after the path bootstrap above
from limn import revisions  # noqa: E402 - after the path bootstrap above
from limn.documents import (  # noqa: E402 - after the path bootstrap above
    DEFAULT_DOC_KEY, DOC_KEY_RE, DOC_NAME_MAX, DOCS_MAX, Doc, DocNotFound,
)
# The page directory on screen, a build's PDF and the build state are App members the handler calls with the request's
# document (web/app.py); they are limn.build's own functions, bound here without a shell.
from limn.build import build_pdf, cur_pages, state_snapshot as build_state_snapshot  # noqa: E402,F401
from limn.revisions import git as _git, revision_history  # noqa: E402,F401 - after the path bootstrap; revision_history is an App member
from limn.scope import valid_changes  # noqa: E402 - after the path bootstrap above
from limn.mapping import (  # noqa: E402 - after the path bootstrap above
    anchor_of, truncate_quote,
)
from limn import locate  # noqa: E402 - after the path bootstrap above
from limn.locate import PinLocation, est_context, locate_file, tex_lines  # noqa: E402 - after the path bootstrap above
from limn.pins import position  # noqa: E402 - after the path bootstrap above
from limn.pins.position import epoch as _epoch, pin_est  # noqa: E402 - after the path bootstrap above
from limn.mark import favicon_svg, inline_svg  # noqa: E402
from limn.web.answers import CONFIRM_BY_HUMAN  # noqa: E402 - after the path bootstrap above
from limn.web.errors import HTTPError, revision_failure_text  # noqa: E402 - after the path bootstrap above
from limn.web.handler import Handler as WebHandler, Server, Server6  # noqa: E402 - after the path bootstrap above

APP_NAME = "limn"


def app_version() -> str:
    """Package version (__version__ in src/limn/__init__.py). Reads the neighboring file so it
    returns the same value whether imported as a module (python -m limn.server) or run
    directly by file path (python .../limn/server.py)."""
    try:
        m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']',
                      Path(__file__).with_name("__init__.py").read_text(encoding="utf-8"), re.M)
    except OSError:
        m = None
    return m.group(1) if m else "0+unknown"



def load_ui_messages() -> dict:
    """The viewer's English message table (ui_en.json next to this file): Korean UI string -> English.

    The Korean strings in the HTML template stay the source; in English mode the viewer swaps every
    UI string it finds in this table (text, tooltips, aria labels, toasts). pins.md and the API are
    not translated — they are a language-stable contract for agents. The one other kind of key is
    `reason:<code>`: the English the viewer shows for an API error body with that reason (errText)."""
    try:
        d = json.loads(Path(__file__).with_name("ui_en.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    def ok(v):   # a string, or plural forms {"one": ..., "other": ...} for a template key with {n}
        if isinstance(v, str):
            return bool(v)
        return (isinstance(v, dict) and set(v) <= {"one", "other"} and isinstance(v.get("other"), str)
                and all(isinstance(x, str) and x for x in v.values()))
    return {k: v for k, v in d.items() if isinstance(k, str) and k and ok(v)}


UI_EN = load_ui_messages()

DEFAULT_ENVS = "figure,table,algorithm,equation,align,itemize,enumerate,minipage"
PAGE_FILE_RE = re.compile(r"page-\d+\.png")
# PDF.js renders the PDF as vectors in the viewer (vendor/pdfjs/README.md). The version is also the ?v= value that busts the browser cache.
PDFJS_VERSION = "6.3.289"
VENDOR_FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*\.mjs")
VENDOR_MIME = {".mjs": "text/javascript; charset=utf-8"}

# Viewer icons - Lucide (ISC, vendor/lucide/README.md). Only the <svg> inner elements of the icons in use are
# copied verbatim from the npm lucide-static source (only whitespace trimmed). Emoji/default character icons
# (e.g. hourglass, chevron, moon, pencil) are avoided since they render differently across devices and fonts.
LUCIDE_VERSION = "1.47.0"
LUCIDE = {
    "bell": '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 '
            '13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',
    "bell-off": '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M17 17H4a1 1 0 0 1-.74-1.673C4.59 13.956 6 12.499 6 8a6 6 0 0 1 '
                '.258-1.742"/><path d="m2 2 20 20"/><path d="M8.668 3.01A6 6 0 0 1 18 8c0 2.687.77 4.653 1.707 6.05"/>',
    "bot": '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "circle-check": '<circle cx="12" cy="12" r="10"/><path d="m16 9-5.5 5.5L8 12"/>',
    "circle-question-mark": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
                            '<path d="M12 17h.01"/>',
    "circle-x": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "copy": '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>'
            '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "at-sign": '<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/>',
    "ellipsis": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    "eye": '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/>'
           '<circle cx="12" cy="12" r="3"/>',
    "message-square": '<path d="M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 '
                      '2-2h16a2 2 0 0 1 2 2z"/>',
    "minus": '<path d="M5 12h14"/>',
    "moon": '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268'
            'c.344-.215.825-.004.803.401"/>',
    "move-vertical": '<path d="M12 2v20"/><path d="m8 18 4 4 4-4"/><path d="m8 6 4-4 4 4"/>',
    "move-horizontal": '<path d="m18 8 4 4-4 4"/><path d="M2 12h20"/><path d="m6 8-4 4 4 4"/>',
    "panel-left": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    "pencil": '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 '
              '.623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "refresh-cw": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
                  '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "rotate-ccw": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "square-dashed": '<path d="M5 3a2 2 0 0 0-2 2"/><path d="M19 3a2 2 0 0 1 2 2"/><path d="M21 19a2 2 0 0 1-2 2"/>'
                     '<path d="M5 21a2 2 0 0 1-2-2"/><path d="M9 3h1"/><path d="M9 21h1"/><path d="M14 3h1"/><path d="M14 21h1"/>'
                     '<path d="M3 9v1"/><path d="M21 9v1"/><path d="M3 14v1"/><path d="M21 14v1"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/>'
           '<path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/>'
           '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "sun-moon": '<path d="M12 2v2"/><path d="M14.837 16.385a6 6 0 1 1-7.223-7.222c.624-.147.97.66.715 1.248a4 4 0 0 0 '
                '5.26 5.259c.589-.255 1.396.09 1.248.715"/><path d="M16 12a4 4 0 0 0-4-4"/>'
                '<path d="m19 5-1.256 1.256"/><path d="M20 12h2"/>',
    "text-wrap": '<path d="m16 16-3 3 3 3"/><path d="M3 12h14.5a1 1 0 0 1 0 7H13"/><path d="M3 19h6"/><path d="M3 5h18"/>',
    "trash-2": '<path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
               '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
                      '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
}
ICON_TOKEN_RE = re.compile(r"\{\{ic:([a-z0-9-]+)\}\}")


def icon_svg(name: str) -> str:
    """One Lucide icon as an inline <svg>. Attributes are kept as-is; size is set by CSS (.ic).
    Produces the same shape as the viewer's JS ic() (the regression tests compare them)."""
    return ('<svg class="ic ic-%s" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">%s</svg>'
            % (name, LUCIDE[name]))

# The limits a request's fields are checked against (the note, close reply/ref/changes, claim minutes, reply text,
# @-tag hints) are with the request parsers in limn/web/parse.py; the pin note's NOTE_MAX and the kind_req values
# KIND_REQS, which the record check here also needs, are in limn/pins/edit.py.
# Pin kind and thread (docs/handbook/api.md §스레드). 24% of pins (10 of 42 in A-DEMO) were questions rather than
# something to fix, but the only place to leave an answer was the single close_reply field on closing, so
# there was no way to ask back. kind_req is kept separate from the legacy kind (scope type) to avoid a name clash.
THREAD_MAX = 200                   # cap on one pin's thread (replies). State-transition records (close/reopen/confirm) are appended regardless of this cap
THREAD_EVENTS = ("close", "reopen", "confirm", "assign")
# Assignee (docs/handbook/api.md §담당). Who handles this pin - either "agent" or a person's login. If absent, it's a
# legacy pin, so addressed_to()'s inference (the @-tag on a question pin) is used as-is. Guessing this from the
# body text made the skip rule ambiguous (A-DEMO #43: a fix-request pin's "@Seojun please check" was meant for a person).
# The value that hands a pin to the agent, ASSIGNEE_AGENT = "agent", lives with the edit rules in limn.pins.edit.
# @-tags (docs/handbook/api.md §@태그·사람·이벤트). Only invoked inside the viewer - no external notification is sent, it's just recorded in events.jsonl.
PEOPLE_TOUCH_S = 600               # don't rewrite people.json's last_seen more often than this interval (so every poll doesn't trigger a write)
EVENTS_KEEP = 5000                 # number of recent events kept in events.jsonl. seq only increases (consumers follow along by seq)
NOTE_MENTION_COOLDOWN_S = 600      # a note save re-tagging the same person on the same pin notifies them at most this often per editor (issue #10 L3)
EVENT_TYPES = ("mention", "review_requested", "replied", "reopened", "assigned", "dropped")
TRASH_DAYS = 30                    # a dropped pin stays in the Trash (pins.dropped.jsonl) this long, then is purged for good
LOCAL_ACTOR = {"login": LOCAL_LOGIN, "name": "로컬/에이전트"}
AGENT_LOGIN_PREFIX = "agent:"      # API-token principals are {"login": "agent:<token name>", "name": "<token name>"}
# Label shown so tabs don't get confused when multiple manuscript viewers are open at once (§Running multiple manuscript instances at once).
# The length cap is a safeguard so the tool bar / tab title doesn't grow unbounded from one long paper name.
LABEL_MAX = 40
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# A high-saturation "700-level" palette with enough contrast on both the dark and light theme backgrounds
# (--bg #14161a / #e9ebef) and under white text (chip text). One is chosen by hashing the label string -
# the same label always gets the same color.
ACCENT_PALETTE = ("#1d4ed8", "#047857", "#be123c", "#6d28d9",
                   "#0e7490", "#c2410c", "#a21caf", "#4d7c0f")

# The pin store's lock (limn.store.PinStore.lock): every path that touches the pin files goes through this single
# re-entrant lock. The store creates no lock, so the process makes its one here and pin_store() passes it on.
PIN_LOCK = threading.RLock()
# If two latexmk runs share the same build/, they trample each other's .aux.
BUILD_LOCK = threading.Lock()
# Guards the BUILD_STATE dict (progress chip / error panel). Separate from BUILD_LOCK (only one build at
# a time) - this lock exists just so that state doesn't race with the GET /api/build request that "reads" it.
BUILD_STATE_LOCK = threading.Lock()
BUILD_STATE = {"state": "idle", "phase": None, "started_at": None, "start_ts": None,
               "last_s": None, "pages": 0, "errors": [], "log_tail": "", "built_at": None,
               "seq": 0, "finished_at": None, "last": None, "head": None, "pull": None}
# Bundles the read-modify-write of builds.json (build history).
BUILDS_LOCK = threading.Lock()


class Cfg:
    """Holds the run arguments. Every project-specific value passes through here."""
    src: Path
    main: Path
    state: Path
    build: Path
    port: int
    dpi: int
    envs: tuple
    timeout: int
    allow: frozenset
    origin_check: bool = True
    git_pull: bool = False
    pdfjs_dir: Path = None          # None = default_pdfjs_dir()
    label: str = "원고"             # label distinguishing multiple instances (§Running multiple manuscript instances at once). Filled in by main()
    accent: str = ACCENT_PALETTE[0]  # the label's accent color (#rrggbb)
    repo: str = None                # git origin URL of --manuscript. None if absent
    # Access control (v0.2). The defaults are exactly the v0.1 behaviour: tailscale headers, headerless loopback = agent.
    auth: str = "tailscale"         # identity provider: tailscale | local | trusted-proxy
    agent_loopback: bool = True     # headerless loopback request = the agent (deprecated; tailscale + loopback bind only)
    tailnet_agent: bool = False     # ...also when it came through tailscale serve (Host not loopback) - opt-in, deprecated
    bind: str = "127.0.0.1"
    public_hosts: tuple = ()        # ((name, port or None), ...) accepted as Host/Origin besides loopback and *.ts.net
    trusted_proxies: tuple = (ipaddress.ip_network("127.0.0.1/32"), ipaddress.ip_network("::1/128"))
    proxy_user_header: str = "X-Forwarded-User"
    proxy_name_header: str = "X-Forwarded-Preferred-Username"
    proxy_email_header: str = None
    members_only: bool = False      # admit only logins in people.json (or --allow)
    local_user: str = None          # the owner's login under --auth local (None = $USER, then "owner")
    insecure: bool = False          # a non-loopback bind allowed by --i-know-this-is-insecure
    agent_token_file: Path | None = None   # where agents on this machine keep this instance's token (ADR-0007); never read

    @property
    def pins_jsonl(self) -> Path:
        """The live pins (the file names are the pin store's, limn.store.PinFiles)."""
        return PinFiles(self.state).pins_jsonl

    @property
    def pins_md(self) -> Path:
        """The agents' work list."""
        return PinFiles(self.state).pins_md

    @property
    def dropped(self) -> Path:
        """The Trash."""
        return PinFiles(self.state).dropped

    @property
    def seq(self) -> Path:
        """The last pin id handed out."""
        return PinFiles(self.state).seq

    @property
    def pages_ptr(self) -> Path:
        return self.state / "pages.cur"

    @property
    def built_src_mtime_file(self) -> Path:
        return self.state / "built_src_mtime.txt"

    @property
    def builds_file(self) -> Path:
        return self.state / "builds.json"

    @property
    def people_file(self) -> Path:
        return self.state / "people.json"

    @property
    def events_file(self) -> Path:
        return self.state / "events.jsonl"

    @property
    def tokens_file(self) -> Path:
        return self.state / "tokens.json"

    @property
    def audit_file(self) -> Path:
        """The append-only audit log of destructive and owner actions (see append_audit)."""
        return self.state / AUDIT_FILE


C = Cfg()


# ---------------------------------------------------------------- Documents (§Multiple documents, docs/handbook/domain.md §여러 문서)
#
# A document (limn.documents.Doc) is always an argument: the handler finds the request's (request_doc) and passes it
# on, a build thread gets its own, and startup walks the list. The list itself (DOCS, the first document is the
# default) is this composition root's; a Doc reads the run paths through the C it is given at construction.


def now_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- Startup preparation
#
# A startup step that cannot go on returns a StartupRefused instead of ending the process; main() is the one place
# that exits (coding rule R3: sys.exit only in main).

class StartupRefused(NamedTuple):
    """Why the server does not start: the message main() prints to stderr before exiting with status 1."""
    message: str


def detect_main(src: Path) -> Path | StartupRefused:
    """Find the top-level .tex. If it's ambiguous, don't guess - refuse with the candidates."""
    cands = [p for p in sorted(src.glob("*.tex"))
             if "\\documentclass" in p.read_text(encoding="utf-8", errors="ignore")[:20000]]
    if len(cands) == 1:
        return cands[0]
    how = "found none" if not cands else "found several"
    listing = "\n".join("  - %s" % p.name for p in cands) or "  (none)"
    return StartupRefused("%s: %s top-level .tex files under %s. Specify one with --main.\n%s" % (APP_NAME, how, src, listing))


def free_port(start: int = 18300, end: int = 18400) -> int | StartupRefused:
    """Find a free port. The point is not to steal someone else's port."""
    for p in range(start, end):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return StartupRefused("No free port in the %d-%d range. Specify one with --port." % (start, end))


def state_slug(src: Path) -> str:
    """Separates state per manuscript - so opening manuscripts A and B at once doesn't mix their pins."""
    return "%s-%s" % (src.name, hashlib.sha1(str(src).encode()).hexdigest()[:8])


# ---------------------------------------------------------------- Instance label (§Running multiple manuscript instances at once)

def git_remote_url(src: Path):
    """git origin URL of --manuscript. None if it isn't a git repo or has no origin - a failure never blocks startup."""
    if not shutil.which("git"):
        return None
    try:
        r = subprocess.run(["git", "-C", str(src), "remote", "get-url", "origin"],
                           capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    url = r.stdout.strip()
    return url if r.returncode == 0 and url else None


def repo_name_from_url(url: str) -> str:
    """Pulls just the repo name out of the last segment of a git remote URL (strips the .git suffix / trailing slash).

    Also accepts scp-style URLs (user@host:name, path separated by ':' only, no '/') - if a '/' is present,
    split on that; only fall back to ':' when it isn't (so a ':' in the hostname isn't mistaken for the name)."""
    tail = url.rstrip("/")
    tail = tail.rsplit("/", 1)[-1] if "/" in tail else tail.rsplit(":", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail


def default_label(src: Path, repo_url) -> str:
    """Default label used when --label is absent: the git repo name, or the manuscript folder name if none."""
    if repo_url:
        name = repo_name_from_url(repo_url)
        if name:
            return name
    return src.name


def clean_label(v) -> str | StartupRefused:
    """Validate a label. Newlines and excessive length are blocked here since they'd break the tool bar / tab title."""
    v = "" if v is None else str(v).strip()
    v = " ".join(v.split())         # collapse newlines/tabs/repeated whitespace to a single space
    if not v:
        v = "원고"
    if len(v) > LABEL_MAX:
        return StartupRefused("--label must be %d characters or fewer: %r" % (LABEL_MAX, v))
    return v


def pick_accent(label: str) -> str:
    """Pick one from the palette by hashing the label string - the same label always gets the same color."""
    idx = int(hashlib.sha1(label.encode("utf-8")).hexdigest(), 16) % len(ACCENT_PALETTE)
    return ACCENT_PALETTE[idx]


def valid_accent(v) -> bool:
    return isinstance(v, str) and ACCENT_RE.fullmatch(v) is not None


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
# it binds the instance's BuildConfig, --git-pull and the view-only render.

def default_pdfjs_dir() -> Path:
    """The PDF.js bundled with the package (limn/vendor/pdfjs)."""
    return Path(__file__).resolve().parent / "vendor" / "pdfjs"


def vendor_file(name: str):
    """The file GET /vendor/pdfjs/<name> serves. Accepts only a single (.mjs) name component and never points outside the directory.

    The name pattern already filters out '/', '..', and '%', but resolve() adds a second check against
    escaping via symlinks and the like."""
    if not isinstance(name, str) or not VENDOR_FILE_RE.fullmatch(name) or ".." in name:
        return None
    base = C.pdfjs_dir or default_pdfjs_dir()
    try:
        base = base.resolve()
        f = (base / name).resolve()
    except (OSError, RuntimeError):
        return None
    if f.parent != base or not f.is_file():
        return None
    return f


# ---------------------------------------------------------------- Build

LOG_TAIL_LINES = 40                # lines kept in the diet response for a non-successful build (§P0c-F)


def diet_log(payload: dict, full: bool) -> dict:
    """Diets the agent response: drops log/log_tail when state=='ok' (even a success ran a few KB via font paths).
    ok_errors|fail are trimmed to the last LOG_TAIL_LINES lines. Left untouched when full (?log=1).
    Internal state (BUILD_STATE/builds.json) is left alone; this only applies right before the HTTP response."""
    if full:
        return payload
    out = dict(payload)
    state = out.get("state")
    for key in ("log", "log_tail"):
        if key not in out:
            continue
        if state == "ok":
            out.pop(key, None)
        else:
            out[key] = "\n".join(str(out[key] or "").splitlines()[-LOG_TAIL_LINES:])
    return out


def build_config() -> BuildConfig:
    """The build settings from the run arguments. Made per build, so a test (or main()) that changes C is seen at once."""
    return BuildConfig(state=C.state, dpi=C.dpi, timeout=C.timeout)


def build_all(D: Doc) -> dict:
    """POST /api/rebuild for document D: build it now (synchronous). If it is already building, returns busy without
    waiting (limn.build.build_now)."""
    return build.build_now(D, lambda: _build_tracked(D))


def build_async(D: Doc) -> dict:
    """POST /api/rebuild?async=1 for document D: start the tracked build on a daemon thread
    (limn.build.build_in_background); the thread builds D itself."""
    return build.build_in_background(D, lambda: _build_tracked(D), now_str())


def _build_tracked(D: Doc) -> dict:
    """One tracked build of D: LaTeX (_build) or, for view-only, the page render (_render_pdf_doc)
    (limn.build.run_tracked). The step is looked up when the build runs, so a test that replaces _build sees it."""
    step = (lambda: _render_pdf_doc(D)) if D.is_pdf else (lambda: _build(D))
    return build.run_tracked(D, C.state, step, now_str())


# ---------------------------------------------------------------- --git-pull (§P0c-E)
#
# Fast-forwards the manuscript repo to the remote main before the rebuild's copy step. A co-author merging a
# PR wasn't reflected on the server-side checkout - the viewer kept showing the old manuscript. Even on
# failure (dirty tree, diverged, no upstream), the build itself continues with the current checkout - a
# pull is nice to have, not a build prerequisite.

# git runs through limn.revisions.git (no shell; imported above as _git), with its 30-second timeout per call.


# ---------------------------------------------------------------- Manuscript history, pin-scoped changes, comparison PDFs
#
# The revision services are limn/revisions.py (the git edge and the comparison builds) and limn/scope.py (the pure
# attribution of a commit's hunks to a pin, ADR-0005). They take the document and a RevisionContext and return
# outcome values; limn.web.answers answers them. What the instance supplies is wired here: the process's one scope
# cache and job registry, the pins as the API shows them, where a recorded path is now, and the texts a failed
# comparison records (limn.web.errors, the same table as the HTTP answers).

SCOPE_CACHE = revisions.ScopeCache()          # the process's pin scopes (commits are immutable, so entries stay right)
REVISION_JOBS = revisions.RevisionJobs()      # the process's running comparison builds and their two slots


def revision_context() -> revisions.RevisionContext:
    """The revision services' view of this instance, made per request like pin_store(), so a test (or main()) that
    changes C is seen at once."""
    root = C.src

    def locate(file: str, D) -> Path | None:
        """Where a recorded change's path of document D is under the manuscript root now (locate_file, issue #24)."""
        loc = locate_file(file, None, root, D)
        return loc.path if loc is not None else None
    return revisions.RevisionContext(timeout=C.timeout, pins=lambda: [public(r) for r in read_pins()[0]],
                                     doc_of=pin_doc_key, locate=locate, cache=SCOPE_CACHE, jobs=REVISION_JOBS,
                                     describe=revision_failure_text)


def revision_diff(D: Doc, commit: str, pin: int | None = None):
    """GET /api/revision-diff for document D (limn.revisions.revision_diff with this instance's context)."""
    return revisions.revision_diff(D, commit, pin, revision_context())


def revision_status(D: Doc, commit: str, pin: int | None = None):
    """GET /api/revision-build for document D (limn.revisions.revision_status)."""
    return revisions.revision_status(D, commit, pin, revision_context())


def revision_start(D: Doc, commit: str, pin: int | None = None):
    """POST /api/revision-build for document D (limn.revisions.revision_start)."""
    return revisions.revision_start(D, commit, pin, revision_context())


def revision_pdf(D: Doc, commit: str, pin: int | None = None):
    """GET /api/revision-pdf for document D (limn.revisions.revision_pdf)."""
    return revisions.revision_pdf(D, commit, pin, revision_context())


# ---------------------------------------------------------------- Outline labels from the same immutable page build as the PDF

def _tex_group(text: str, pos: int):
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text) or text[pos] != "{":
        return None
    start, depth = pos + 1, 1
    pos += 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
            continue
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return text[start:pos], pos + 1
        pos += 1
    return None


def _tex_plain(text: str, depth: int = 0) -> str:
    """Conservative display conversion, never a TeX evaluator; unsupported macros omit a label."""
    if depth > 12 or len(text) > 4000:
        raise ValueError("complex title")
    out, i = [], 0
    wrappers = {"textbf", "textit", "texttt", "textrm", "textsf", "textsc", "emph", "mbox", "ensuremath", "mathrm", "mathbf"}
    while i < len(text):
        c = text[i]
        if c == "{":
            group = _tex_group(text, i)
            if not group:
                raise ValueError("unbalanced title")
            value, i = group
            out.append(_tex_plain(value, depth + 1))
        elif c == "\\":
            match = re.match(r"\\([A-Za-z@]+|.)", text[i:])
            if not match:
                raise ValueError("bad macro")
            macro = match[1]
            i += len(match[0])
            if macro in ("protect", "relax", "ignorespaces"):
                continue
            if macro in ("&", "%", "#", "_", "$", "{", "}"):
                out.append(macro)
            elif macro in (" ", ",", ";", "quad", "qquad", "enspace"):
                out.append(" ")
            elif macro in wrappers or macro == "texorpdfstring":
                first = _tex_group(text, i)
                if not first:
                    raise ValueError("missing macro group")
                value, i = first
                if macro == "texorpdfstring":
                    second = _tex_group(text, i)
                    if not second:
                        raise ValueError("missing PDF title")
                    value, i = second
                out.append(_tex_plain(value, depth + 1))
            else:
                raise ValueError("unsupported title macro")
        elif c in "$^_}":
            raise ValueError("unsupported math title")
        else:
            out.append(" " if c == "~" else c)
            i += 1
    return " ".join("".join(out).replace("---", "—").replace("--", "–").split())


def outline_labels(D: Doc) -> dict:
    pages = build.cur_pages(D)
    result = {"build": pages.name, "labels": []}
    if D.is_pdf:
        return result
    aux = pages / (D.main.stem + ".aux")
    try:
        if aux.is_symlink() or aux.stat().st_size > 4 * 1024 * 1024:
            return result
        source = aux.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    for match in re.finditer(r"\\@writefile\s*\{toc\}", source):
        outer = _tex_group(source, match.end())
        if not outer:
            continue
        line = outer[0]
        marker = re.match(r"\s*\\contentsline\s*", line)
        if not marker:
            continue
        groups, pos = [], marker.end()
        for _ in range(4):
            group = _tex_group(line, pos)
            if not group:
                break
            value, pos = group
            groups.append(value)
        if len(groups) < 3 or groups[0] not in ("part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph"):
            continue
        level, title, page = groups[:3]
        number, anchor = "", groups[3] if len(groups) > 3 else ""
        numberline = re.match(r"\s*(?:\\protect\s*)?\\numberline\s*", title)
        if numberline:
            group = _tex_group(title, numberline.end())
            if not group:
                continue
            number, pos = group
            title = title[pos:]
        try:
            row = {"number": _tex_plain(number), "title": _tex_plain(title), "page": _tex_plain(page),
                   "level": level, "anchor": anchor[:200]}
        except ValueError:
            # Keep a placeholder so consumers cannot shift all subsequent numbers by index.
            row = {"number": "", "title": "", "page": page[:40], "level": level, "anchor": anchor[:200]}
        result["labels"].append(row)
        if len(result["labels"]) >= 200:
            break
    return result


def git_pull_phase(manuscript: Path, main_only: bool = False) -> dict:
    """{"state": "ok"|"up_to_date"|"skipped"|"error", "reason", "head_before", "head_after"}.

    Order: locate the repo root (skipped:not_git if not found) -> fetch (error on failure) -> check
    upstream (skipped:no_upstream if none) -> check for a dirty tree (skipped:dirty if dirty) -> --ff-only
    merge (skipped:diverged if diverged). At any step, a timeout or exec failure on the git call itself is error."""
    rc, top, _ = _git(["-C", str(manuscript), "rev-parse", "--show-toplevel"], manuscript)
    if rc != 0 or not top.strip():
        return {"state": "skipped", "reason": "not_git", "head_before": None, "head_after": None}
    root = top.strip()

    rc, before, _ = _git(["-C", root, "rev-parse", "HEAD"], root)
    head_before = before.strip() if rc == 0 else None

    rc, _out, _err = _git(["-C", root, "fetch", "--quiet"], root)
    if rc != 0:
        reason = "fetch_timeout" if rc is None else "fetch_failed"
        return {"state": "error", "reason": reason, "head_before": head_before, "head_after": head_before}

    rc, upstream, _err = _git(["-C", root, "rev-parse", "--abbrev-ref", "@{u}"], root)
    if rc != 0:
        return {"state": "skipped", "reason": "no_upstream", "head_before": head_before, "head_after": head_before}
    if main_only:
        rc, branch, _err = _git(["-C", root, "symbolic-ref", "--quiet", "--short", "HEAD"], root)
        if rc != 0 or branch.strip() != "main" or not upstream.strip().endswith("/main"):
            return {"state": "skipped", "reason": "not_main", "head_before": head_before, "head_after": head_before}

    rc, dirty, _err = _git(["-C", root, "status", "--porcelain", "--untracked-files=no"], root)
    if rc != 0:
        return {"state": "error", "reason": "status_failed", "head_before": head_before, "head_after": head_before}
    if dirty.strip():
        return {"state": "skipped", "reason": "dirty", "head_before": head_before, "head_after": head_before}

    rc, _out, _err = _git(["-C", root, "merge", "--ff-only", "@{u}"], root)
    if rc != 0:
        return {"state": "skipped", "reason": "diverged", "head_before": head_before, "head_after": head_before}

    rc, after, _err = _git(["-C", root, "rev-parse", "HEAD"], root)
    head_after = after.strip() if rc == 0 else head_before
    state = "up_to_date" if head_after == head_before else "ok"
    return {"state": state, "reason": None, "head_before": head_before, "head_after": head_after}


_PULL_LOCK = threading.Lock()
_PULL_LAST = {"at": 0.0, "res": None}
PULL_SHARE_S = 20                  # seconds - if another document already pulled within this window, reuse its result
SYNC_EVERY_S = 60                  # interval for checking remote main. Checked even when no browser is open.
_SYNC_LOCK = threading.Lock()
_SYNC_STATE = {"state": "checking", "reason": None, "checked_at": None,
               "head_before": None, "head_after": None}


def sync_status() -> dict:
    if not C.git_pull:
        return {"state": "disabled"}
    with _SYNC_LOCK:
        state = dict(_SYNC_STATE)
    if state.get("state") != "updating" or not state.get("head_after"):
        return state
    head = state["head_after"]
    pending = False
    failed = False
    for D in list(DOCS):
        if D.is_pdf:
            continue
        if D.lock.locked():
            pending = True
            continue
        try:
            built = (D.dir / "head.txt").read_text(encoding="utf-8").strip()
        except OSError:
            built = ""
        if not built or built == "-" or not head.startswith(built):
            pending = True
            with D.bstate_lock:
                failed |= D.bstate.get("state") == "fail"
    if not pending or failed:
        with _SYNC_LOCK:
            if _SYNC_STATE.get("state") == "updating" and _SYNC_STATE.get("head_after") == head:
                _SYNC_STATE.update(state="error" if failed else "current",
                                   reason="build_failed" if failed else None)
            return dict(_SYNC_STATE)
    return state


def sync_main_once() -> dict:
    """Check remote main and rebuild the PDF only for documents that changed. Also called on --no-build startup.

    If any document is currently building, this round is deferred. While updating the Git checkout, every
    document lock is held, so a fast-forward never happens while another build is mid-copy of the source.
    """
    if not C.git_pull:
        return {"state": "disabled"}
    held = []
    for D in list(DOCS):
        if D.is_pdf:
            continue
        if not D.lock.acquire(blocking=False):
            for lock in reversed(held):
                lock.release()
            out = {"state": "deferred", "reason": "building",
                   "checked_at": datetime.now().astimezone().isoformat(timespec="seconds")}
            with _SYNC_LOCK:
                _SYNC_STATE.update(out)
            return out
        held.append(D.lock)
    try:
        with _PULL_LOCK:
            pull = git_pull_phase(C.src, main_only=True)
            _PULL_LAST.update(at=time.time(), res=pull)
    finally:
        for lock in reversed(held):
            lock.release()

    state = {"ok": "updated", "up_to_date": "current",
             "skipped": "blocked", "error": "error"}.get(pull["state"], "error")
    out = dict(pull, state=state, checked_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    with _SYNC_LOCK:
        _SYNC_STATE.clear()
        _SYNC_STATE.update(out)
    if state in ("updated", "current"):
        head = pull.get("head_after") or ""
        for D in list(DOCS):
            if D.is_pdf:
                continue
            try:
                built = (D.dir / "head.txt").read_text(encoding="utf-8").strip()
            except OSError:
                built = ""
            if state == "updated" or not built or built == "-" or not head.startswith(built):
                build_async(D)
                out["state"] = "updating"
        if out["state"] == "updating":
            with _SYNC_LOCK:
                _SYNC_STATE["state"] = "updating"
    return out


def watch_main(stop: threading.Event, every: float = SYNC_EVERY_S) -> None:
    """Syncs right after startup and then periodically. The watch thread survives even if an error occurs."""
    while not stop.is_set():
        try:
            result = sync_main_once()
        except Exception:                         # noqa: BLE001 — the next round will retry
            traceback.print_exc(file=sys.stderr)
            with _SYNC_LOCK:
                _SYNC_STATE.update(state="error", reason="unexpected",
                                   checked_at=datetime.now().astimezone().isoformat(timespec="seconds"))
            result = {"state": "error"}
        if stop.wait(min(3.0, every) if result.get("state") == "deferred" else every):
            break


def repo_pull() -> dict:
    """--git-pull operates per repo. A single document pulls once per build (as before). With multiple
    documents, a single lock serializes them, and if another document's build already pulled within
    PULL_SHARE_S, that result is reused (shared=True) instead of pulling again - so rebuilding two
    documents at once never collides on git fetch/merge (.git/index.lock conflicts), and the tree
    never changes mid-copy for one of them."""
    if not multi_doc():
        return git_pull_phase(C.src)
    with _PULL_LOCK:
        last = _PULL_LAST["res"]
        if last is not None and time.time() - _PULL_LAST["at"] < PULL_SHARE_S:
            return dict(last, shared=True)
        res = git_pull_phase(C.src)
        _PULL_LAST.update(at=time.time(), res=res)
        return res


def _build(D: Doc) -> dict:
    """The LaTeX build of document D with this instance's settings; --git-pull pulls first (limn.build.compile_tex)."""
    return build.compile_tex(D, build_config(), repo_pull if C.git_pull else None)


# ---------------------------------------------------------------- View-only PDF documents
#
# A PDF with no LaTeX source (reviewer comments, etc.) has no rebuild. Instead, when that PDF file changes
# (mtime/size), the page images are re-rendered - since it goes through the same build path
# (_build_tracked -> history/build_seq), the viewer updates the screen exactly as it would for a LaTeX rebuild.

def pdf_signature(D: Doc):
    try:
        st = D.main.stat()
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _render_pdf_doc(D: Doc) -> dict:
    """The 'build' for view-only document D - renders the original PDF into page images. No LaTeX, SyncTeX, or git pull."""
    t0 = time.time()
    res = {"ok": False, "state": "fail", "errors": [], "log": "", "elapsed_s": 0.0}
    sig = pdf_signature(D)
    if sig is None:
        res["log"] = "PDF 가 없습니다: %s" % D.main
        return res
    try:
        res["src_hash"] = build.doc_fingerprint(D, C.state)
    except OSError:
        res["src_hash"] = None
    newdir, err = build.render_pages(D, D.main, [], C.dpi)
    if newdir is None:
        res["log"] = err
        res["elapsed_s"] = round(time.time() - t0, 1)
        try:                                         # never retries the same file every 3 seconds - re-renders only when the file changes
            atomic_write(D.dir / "pdf_sig.txt", sig)
        except OSError:
            pass
        return res
    res["head"] = build.commit_pages(D, newdir)
    try:
        atomic_write(D.dir / "pdf_sig.txt", sig)
    except OSError:
        pass
    res.update(state="ok", ok=True, build=newdir.name, pages=len(list(newdir.glob("page-*.png"))),
               elapsed_s=round(time.time() - t0, 1))
    return res


def pdf_changed(D: Doc) -> bool:
    """Has the view-only PDF changed since the page images were last rendered (or have they never been rendered)?"""
    sig = pdf_signature(D)
    if sig is None:
        return False
    try:
        done = (D.dir / "pdf_sig.txt").read_text().strip()
    except OSError:
        done = ""
    return sig != done


def refresh_pdf_doc(D: Doc) -> bool:
    """If the PDF changed, re-render it in the background (does nothing if already rendering). True if it started."""
    if not D.is_pdf or not pdf_changed(D):
        return False
    r = build_async(D)
    return not r.get("busy")


# ---------------------------------------------------------------- Meta

def png_size(path: Path) -> tuple:
    with path.open("rb") as fh:
        return struct.unpack(">II", fh.read(24)[16:24])


def page_list(pdir: Path, dpi: int | None = None) -> list:
    """The page images of page directory pdir as {name, pt_w, pt_h}: sizes in points at the dpi they were rendered at
    (default: this instance's). An unreadable image is left out."""
    dpi = C.dpi if dpi is None else dpi
    pages = []
    for p in sorted(pdir.glob("page-*.png")):
        try:
            w, h = png_size(p)
        except (OSError, struct.error):
            continue
        pages.append({"name": p.name, "pt_w": w * 72.0 / dpi, "pt_h": h * 72.0 / dpi})
    return pages


_SRC_MTIME_CACHE: list = [None, 0.0, 0.0]     # [C.src string, value, measured-at time] - a 2-second cache (for a single document)
# Single document (no --doc). Holds the module-global lock/state as-is, so the object the legacy code paths
# and regression tests see is exactly this document's.
LEGACY_DOC = Doc(DEFAULT_DOC_KEY, "본문", legacy=True, lock=BUILD_LOCK, bstate=BUILD_STATE,
                 bstate_lock=BUILD_STATE_LOCK, builds_lock=BUILDS_LOCK, mcache=_SRC_MTIME_CACHE, paths=C)
DOCS: list = [LEGACY_DOC]


def set_docs(docs=None) -> None:
    """Change the document list (main()/tests). Reverts to a single document when empty."""
    DOCS[:] = list(docs) if docs else [LEGACY_DOC]


def multi_doc() -> bool:
    return len(DOCS) > 1


def doc_by_key(key):
    return next((d for d in DOCS if d.key == key), None)


def pin_doc_key(r: dict) -> str:
    """The document key a pin belongs to. Legacy records without a doc field are read as the first document (no migration write)."""
    k = r.get("doc")
    return k if isinstance(k, str) and k else DOCS[0].key


def doc_for_file(path) -> Doc:
    """Which LaTeX document a request that only gave file (agent curl) belongs to. The document whose build root most deeply contains it, or the first document if none."""
    try:
        p = Path(path) if os.path.isabs(str(path)) else C.src / str(path)
        p = p.resolve()
    except (OSError, RuntimeError, ValueError):
        return DOCS[0]
    best, depth = None, -1
    for d in DOCS:
        if d.is_pdf:
            continue
        try:
            p.relative_to(d.src.resolve())
        except (ValueError, OSError, RuntimeError):
            continue
        n = len(d.src.resolve().parts)
        if n > depth:
            best, depth = d, n
    return best or DOCS[0]


def pins_rev() -> str:
    try:
        st = C.pins_jsonl.stat()
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return "0"


def doc_brief(D: Doc) -> dict:
    """A summary of one document - used by /api/docs and (with multiple documents) /api/meta's docs. Never writes (called from polling)."""
    b = build.state_snapshot(D)
    stale = (not D.is_pdf) and build.source_newer(D, C.state) > 2
    pdir = build.cur_pages(D)
    n_pages = sum(1 for _ in pdir.glob("page-*.png")) if pdir.is_dir() else 0
    return {"key": D.key, "name": D.name, "kind": D.kind, "view_only": D.is_pdf, "path": D.rel_path(),
            "main": D.main.name, "stale_build": stale, "src_mtime": build.src_mtime(D, C.state),
            "building": D.lock.locked(), "build": {"state": b["state"], "phase": b["phase"]},
            "build_seq": b.get("seq", 0), "last_state": (b.get("last") or {}).get("state"),
            "pages_build": pdir.name, "n_pages": n_pages}


def docs_payload() -> dict:
    """GET /api/docs — the document list and open-pin counts per document. Pins are only read (no sync write)."""
    rows, _ = read_pins()
    counts: dict = {}
    for r in rows:
        if not r.get("done"):
            k = pin_doc_key(r)
            counts[k] = counts.get(k, 0) + 1
    known = {d.key for d in DOCS}
    return {"docs": [dict(doc_brief(d), n_open=counts.get(d.key, 0)) for d in DOCS],
            "default": DOCS[0].key, "multi": multi_doc(),
            "other_open": sum(v for k, v in counts.items() if k not in known)}


def meta(D: Doc, actor: dict, light: bool = False) -> dict:
    """GET /api/meta for document D: its pages, builds, staleness and settings for the viewer; with light (polling)
    the pin counts are left out, and with them the sync write of snapshot_pins()."""

    def read(f):
        try:
            return (D.dir / f).read_text().strip()
        except OSError:
            return "?"
    bstate = build.state_snapshot(D)
    sm = build.src_mtime(D, C.state)
    newer = 0.0 if D.is_pdf else build.source_newer(D, C.state)     # view-only: the server re-renders on its own when the PDF changes
    out = {"pages": page_list(build.cur_pages(D)), "built_at": read("built_at.txt"), "head": read("head.txt"),
           "main": D.main.name, "pins_md": str(C.pins_md), "state_dir": str(C.state), "me": actor,
           "label": C.label, "accent": C.accent, "repo": C.repo,
           "building": D.lock.locked(), "sync": sync_status(),
           "doc": D.key, "doc_name": D.name, "kind": D.kind, "view_only": D.is_pdf, "multi": multi_doc(),
           # Is the manuscript newer than the PDF on screen - the server judges this numerically (independent of browser clock/timezone).
           "stale_build": newer > 2, "src_age_s": round(max(0.0, time.time() - sm), 1) if sm else None,
           "src_mtime": sm, "build_src_mtime": build.read_built_src_mtime(D),
           "pages_build": build.cur_pages(D).name,
           "pins_rev": pins_rev(),
           # build_seq = number of finished builds, last_build = the most recently finished build (kept regardless of any build in progress).
           "build_seq": bstate.get("seq", 0),
           "last_build": bstate.get("last") or {"state": None, "errors": [], "finished_at": None, "seq": 0},
           "build": {"state": bstate["state"], "phase": bstate["phase"], "started_at": bstate.get("started_at")}}
    if multi_doc():                       # staleness/build of other documents - the viewer shows a dot/progress marker on their tabs
        out["docs"] = [doc_brief(d) for d in DOCS]
        out["src_sig"] = ",".join("%s=%.3f" % (d["key"], d["src_mtime"]) for d in out["docs"])
    if light:                             # polling only - skips the sync write in snapshot_pins()
        return out
    rows = snapshot_pins()
    states = [pin_state(r) for r in rows]
    out["n_open"] = states.count("open")
    out["n_done"] = states.count("done")          # done only - awaiting review (done=true, review=true) is n_review
    out["n_review"] = states.count("review")
    return out


# ---------------------------------------------------------------- Pin store

def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def valid_rec(r) -> bool:
    """Checks only the fields the store trusts and indexes on. If even one is wrong, the line is treated as broken.

    Back when only id was checked, a single record with a string lo or no file turned every GET/POST into a
    500 - and because the pins.jsonl write had already committed right before that 500, a retry created a
    duplicate pin (observed)."""
    if not isinstance(r, dict) or not _is_int(r.get("id")):
        return False
    if r.get("doc") is not None and not (isinstance(r["doc"], str) and DOC_KEY_RE.fullmatch(r["doc"])):
        return False
    if is_region_pin(r):
        # A view-only PDF's pin: instead of file/lo/hi, its location is pdf (absolute path)/page/region (frac) (see "View-only PDF documents" above).
        if not os.path.isabs(r["pdf"]) or not (_is_int(r.get("page")) and r["page"] >= 1):
            return False
        if r.get("lo") is not None or r.get("hi") is not None:
            return False
        fr = r.get("frac")
        if not (isinstance(fr, list) and len(fr) == 4 and all(_is_num(x) for x in fr)):
            return False
    else:
        if not isinstance(r.get("file"), str) or not r["file"]:
            return False
        lo, hi = r.get("lo"), r.get("hi")
        if not (_is_int(lo) and _is_int(hi) and 1 <= lo <= hi):
            return False
        if not os.path.isabs(r["file"]):              # a relative path would point at a different file depending on the server's cwd
            return False
    if "page" in r and not _is_int(r["page"]):
        return False
    if "note" in r and r["note"] is not None and not isinstance(r["note"], str):
        return False
    for k in ("close_reply", "close_ref"):
        if r.get(k) is not None and not isinstance(r[k], str):
            return False
    if r.get("changes") is not None and not valid_changes(r["changes"]):
        return False
    # The new fields (kind_req/thread/mentions/review) are all optional. The viewer renders them as-is, so a malformed shape is treated as a broken line.
    if r.get("kind_req") is not None and r["kind_req"] not in KIND_REQS:
        return False
    if r.get("mentions") is not None and not _is_str_list(r["mentions"]):
        return False
    if r.get("assignee") is not None and not (isinstance(r["assignee"], str) and r["assignee"]):
        return False
    if r.get("thread") is not None and not _valid_thread(r["thread"]):
        return False
    if "anchor" in r and not isinstance(r["anchor"], dict):
        return False
    for k in ("raw_lo", "raw_hi", "rev"):
        if r.get(k) is not None and not _is_int(r[k]):
            return False
    for k in ("synced_at", "score", "claim_until", "claim_ts", "eta_ts"):   # epoch seconds - named apart from '*_at' (string timestamps)
        if r.get(k) is not None and not _is_num(r[k]):
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
        elif k == "author" or k.endswith("_by"):
            if v is not None and not _is_actor(v):
                return False
    fr = r.get("frac")
    if fr is not None and not (isinstance(fr, list) and len(fr) == 4 and all(_is_num(x) for x in fr)):
        return False
    return True


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_actor(v) -> bool:
    """author/*_by must be a {login,name,pic?} string dict - the UI calls name.trim()."""
    return isinstance(v, dict) and all(v.get(k) is None or isinstance(v[k], str) for k in ("login", "name", "pic"))


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _valid_thread(th) -> bool:
    """thread = [{id, by, at, text, ev?, ref?, mentions?}] - the viewer renders by.name/text as-is."""
    if not isinstance(th, list):
        return False
    for m in th:
        if not isinstance(m, dict) or not _is_int(m.get("id")) or not isinstance(m.get("text"), str):
            return False
        if not isinstance(m.get("at"), str) or not _is_actor(m.get("by")):
            return False
        if m.get("ev") is not None and m["ev"] not in THREAD_EVENTS:
            return False
        if m.get("ref") is not None and not isinstance(m["ref"], str):
            return False
        if m.get("mentions") is not None and not _is_str_list(m["mentions"]):
            return False
    return True


def pin_location(r: dict, root: Path) -> PinLocation | None:
    """Where line pin r's file is under the manuscript root on this machine now (limn.locate.pin_location, the tail
    guess limited to the folder of the pin's own document), or None."""
    return locate.pin_location(r, root, doc_by_key(pin_doc_key(r)))


def stamp_location(r: dict, root: Path) -> PinLocation | None:
    """Records in r where its file is now (limn.locate.stamp_location, the pin's own document). Mutates r."""
    return locate.stamp_location(r, root, doc_by_key(pin_doc_key(r)))


def pin_locator() -> locate.Locator:
    """pin_location() bound to this instance's manuscript root, read now."""
    root = C.src
    return lambda r: pin_location(r, root)


def sync_all(rows: list) -> bool:
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

def read_jsonl(path: Path) -> tuple:
    """(records, broken line numbers) of a JSONL file (PinStore.read_jsonl)."""
    return pin_store().read_jsonl(path)


def read_pins() -> tuple:
    """The live pins and pins.jsonl's broken line numbers, lock-free and not re-synced (PinStore.read_pins)."""
    return pin_store().read_pins()


def write_pins(rows: list, bad=None) -> None:
    """Rewrites pins.jsonl then pins.md; nothing if rendering fails (PinStore.write_pins). Callers hold PIN_LOCK."""
    pin_store().write_pins(rows, bad)


def transact(fn):
    """Write-order invariant: with PIN_LOCK -> read -> sync -> apply the request's change -> atomic write -> pins.md.

    fn(rows) returns (result, whether it mutated); returns (rows, result). See PinStore.transact."""
    return pin_store().transact(fn)


def snapshot_pins() -> list:
    """The live pins, re-synced and written back if that changed them (PinStore.snapshot)."""
    return pin_store().snapshot()


def public(r: dict) -> dict:
    """A record as the API returns it: a copy with rev defaulted to 0 and - for a line pin that pin_location() places
    under the manuscript root - `file` set to its absolute path on this machine now and the computed `rel_path` to its
    path relative to the root (ADR-0006, for old records too). The stored `file_rel` is not returned: rel_path is always
    this server's answer, never a value an older version left behind. A pin that cannot be located keeps its stored
    file and has no rel_path. Never changes r."""
    out = dict(r)
    out["rev"] = out["rev"] if _is_int(out.get("rev")) else 0
    out.pop("file_rel", None)
    out.pop("rel_path", None)
    loc = pin_location(r, C.src)
    if loc is not None:
        out["file"], out["rel_path"] = str(loc.path), loc.rel
    return out


# ---------------------------------------------------------------- Computed fields of GET /api/pins
#
# Location estimation (est) is limn.pins.position.pin_est over the document's builds as limn.locate.est_context reads
# them; overlap (rel) is overlaps_by_id below. Neither is stored.


def pin_state(r: dict) -> str:
    """'open' | 'review' | 'done' - a computed field, never stored (docs/handbook/api.md §검토 대기).

    Awaiting review is the shape done=true plus review=true. Because done is still true, the legacy contract
    keeps working as-is - GET /api/pins (open pins only), the pins.md open table, claim (409 on done), line
    matching, and overlap computation all treat an awaiting-review pin as "the agent's part is finished".
    An old server or old viewer just sees it as done, and nothing breaks. A legacy done:true record with no
    review field stays plain done - reading it never triggers a migration write."""
    if not r.get("done"):
        return "open"
    return "review" if r.get("review") is True else "done"


def pins_payload(rows: list, allp: bool) -> list:
    """GET /api/pins response: stored records + the computed fields rel (overlap), est (location estimated), state. None of these are stored."""
    rel = overlaps_by_id(rows)
    ctxs: dict = {}
    out = []
    for r in rows:
        if not (allp or not r.get("done")):
            continue
        k = pin_doc_key(r)
        if k not in ctxs:                              # judgment material is per document (build history is separate per document)
            D = doc_by_key(k)
            if D is None:
                ctxs[k] = None
            else:
                ctxs[k] = est_context(D)
        ctx = ctxs[k]
        rec = dict(public(r), rel=rel.get(r["id"], []), est=pin_est(r, ctx) if ctx else True, doc=k, state=pin_state(r),
                   addressed=addressed_to(r), fyi=fyi_mentions_to(r))
        if claim_active(r) and not _is_num(r.get("claim_ts")):
            ts = _epoch(r.get("claimed_at"))          # a pre-eta claim - the start epoch (computed field) the viewer's "since 20:02 (23 min in)" uses
            if ts is not None:
                rec["claim_ts"] = ts
        out.append(rec)
    return out


def dropped_payload(now: float = None) -> list:
    """GET /api/pins/dropped response - the Trash: pins.dropped.jsonl emitted as-is, ordered by dropped_at (no computed
    fields but `expires_ts`), without entries older than TRASH_DAYS (hidden here, removed from the file by the next purge_trash()).

    Read-only and outside the lock - dropping/restoring already hold PIN_LOCK while writing this file
    (drop_pin/restore_pin). Since only a file that has finished an atomic replace (atomic_write) is ever
    read here, no separate lock is needed to avoid seeing a half-written file."""
    rows = _unexpired(read_jsonl(C.dropped)[0], now)
    rows.sort(key=lambda r: str(r.get("dropped_at") or ""))
    out = []
    for r in rows:
        rec, exp = public(r), trash_expires_ts(r)
        if exp is not None:
            rec["expires_ts"] = round(exp, 3)       # computed (v0.2.2): the viewer's "gone in N days", free of the browser's time zone
        out.append(rec)
    return out


# ---------------------------------------------------------------- Overlap - a computed field, never stored
#
# The rule is limn.pins.position (overlaps_by_id, selection_rel, overlaps_for_range); here it is bound to where this
# instance finds each pin's file now.

def pin_file(r: dict) -> str:
    """The file an open line pin's overlaps are counted in: where pin_location() places it now, else its stored file
    (pins made before and after a move of the checkout are one file)."""
    return locate.located_file(r, pin_locator())


def overlaps_by_id(rows: list) -> dict:
    """The relationship of every pair of open line pins on the same file (position.overlaps_by_id), never stored."""
    return position.overlaps_by_id(rows, pin_file)


def overlaps_for_range(file: str, lo: int, hi: int) -> list:
    """The overlap relationships between a not-yet-saved range of file and that file's open pins, as re-synced now
    (position.overlaps_for_range). Nothing is saved."""
    return position.overlaps_for_range(file, lo, hi, snapshot_pins(), pin_file)


def josa(n, cons: str, vowel: str) -> str:
    """Korean particle after a number - '#20과'/'#2와', '#20을'/'#2를'. Decided by the final sound of the Sino-Korean reading:
    ending in 0 (ship/baek/cheon/man/yeong) takes the consonant-final particle, and so do the digits 1/3/6/7/8
    (il/sam/yuk/chil/pal). Same rule as the viewer's josa()."""
    d = str(n)[-1:]
    return cons if d == "0" or d in "13678" else vowel


def rel_badge(rel: list, by_id: dict, me: dict = None) -> str:
    """Picks one representative relationship for pins.md / card tags - phrased as a short, meaningful label (the old ⊂#N/∩#N marks were unreadable).

    1. If there's a pin with the exact same range (the same spot marked twice), the one with the smallest id: '#N과 같은 범위'
    2. If there's an inside relationship, the smallest enclosing outer pin: '#N 범위 안'
    3. The smallest-id partial: '#N과 일부 겹침'
    contains (wraps) is never shown. Since the rel entries from GET /api/pins are only {id,rel} (the
    contract), ranges are looked up from by_id (the full rows). Without me (this pin), same-range pins
    can't be singled out, so it falls back to only inside/overlap, as before."""
    if me is not None:
        same = [x for x in rel if (by_id.get(x["id"]) or {}).get("lo") == me.get("lo")
                and (by_id.get(x["id"]) or {}).get("hi") == me.get("hi")]
        if same:
            n = min(x["id"] for x in same)
            return "#%d%s 같은 범위" % (n, josa(n, "과", "와"))
    insides = [x for x in rel if x["rel"] == "inside"]
    if insides:
        def span(x):
            o = by_id.get(x["id"])
            return ((o["hi"] - o["lo"]) if o else 1 << 30, x["id"])
        best = min(insides, key=span)
        return "#%d 범위 안" % best["id"]
    partials = [x for x in rel if x["rel"] == "partial"]
    if partials:
        n = min(partials, key=lambda x: x["id"])["id"]
        return "#%d%s 일부 겹침" % (n, josa(n, "과", "와"))
    return ""


def init_seq() -> None:
    """If pins.seq is missing, fill it once from the max id across the current, archived, and dropped records (PinStore.init_seq)."""
    pin_store().init_seq()


def next_id(rows: list) -> int:
    """An id is never reused - hands out the next one and records it in pins.seq (PinStore.next_id)."""
    return pin_store().next_id(rows)


def who(actor: dict) -> dict:
    return {"login": actor.get("login", "local"), "name": actor.get("name", "")}


# ---------------------------------------------------------------- Request documents and parsing facts
#
# The request parsers live in limn/web/parse.py (coding rule R3): each returns the validated value or an InputRejected
# with the exact 400 message of the agent contract, and the handler passes the parsed value to the service here. A
# parser that checks a request against the manuscript reads it through document_facts().

def assignee_people(d: dict) -> Collection[str]:
    """The logins limn.web.parse.parse_assignee checks against: known_people() when the body names an assignee, else
    none (no read)."""
    return known_people() if d.get("assignee") is not None else ()


def _person_name(login: str) -> str:
    """A known person's display name, or the login itself for someone the viewer does not know."""
    return (known_people().get(login) or {}).get("name") or login


def request_doc(key: str | None, file_hint: object | None = None) -> Doc | DocNotFound:
    """The document key names (limn.web.parse.parse_doc_key checked it). With no key, the document holding file_hint
    (agent curl names only a file), else the first document. An unknown key is DocNotFound with the keys this instance
    serves (answered 404) - silently falling back to the first document would attach the pin to the wrong document."""
    if not key:
        if file_hint and multi_doc():
            return doc_for_file(file_hint)
        return DOCS[0]
    D = doc_by_key(key)
    if D is None:
        return DocNotFound(key, tuple(d.key for d in DOCS))
    return D


class DocumentFacts:
    """limn.web.parse.DocumentFacts for document D: what the location parsers read from this machine's disk - the
    manuscript tree root, a file's lines, the pages of a build of D (sized at dpi). Made per request by
    document_facts(); every method reads at call time."""

    def __init__(self, D: Doc, root: Path, dpi: int) -> None:
        """Bind the document, the manuscript root and the dpi the page images were rendered at."""
        self._doc, self._root, self._dpi = D, root, dpi

    @property
    def key(self) -> str:
        """The document key."""
        return self._doc.key

    @property
    def is_pdf(self) -> bool:
        """True for a view-only PDF document."""
        return self._doc.is_pdf

    @property
    def pdf(self) -> Path:
        """The document's main file (a view-only document's PDF)."""
        return self._doc.main

    @property
    def root(self) -> Path:
        """The manuscript tree."""
        return self._root

    def lines(self, path: Path) -> list:
        """The file's lines (tex_lines: [] when unreadable)."""
        return tex_lines(path)

    def page_count(self, name: str | None) -> int:
        """Pages of build `name` of D, or of the build on screen when name is None or gone (limn.build.pages_dir_for)."""
        return len(page_list(build.pages_dir_for(self._doc, name), self._dpi))

    def current_build(self) -> str:
        """The name of D's page directory on screen."""
        return build.cur_pages(self._doc).name

    def pick_pages(self, name: str | None) -> tuple | None:
        """(page directory, [(width, height) in points]) of build `name` of D - or the one on screen for None - or None
        when name is a page directory of D that is gone."""
        if name is not None and not (self._doc.dir / name).is_dir():
            return None
        pdir = build.pages_dir_for(self._doc, name) if name is not None else build.cur_pages(self._doc)
        return pdir, [(p["pt_w"], p["pt_h"]) for p in page_list(pdir, self._dpi)]


def document_facts(D: Doc) -> DocumentFacts:
    """The parsing facts of document D with this instance's manuscript root and dpi - made per request like
    pin_store(), so a test (or main()) that changes C is seen at once."""
    return DocumentFacts(D, C.src, C.dpi)


# ---------------------------------------------------------------- Pin operations
#
# Adding and editing a pin (docs/handbook/api.md §핀 만들기, §핀 고치기). The handler parses the body
# (limn.web.parse.parse_add, parse_edit and parse_edit_place); the shell reads what only the disk and the clock know
# under the pin lock, and leaves the rules and the record to limn.pins.edit. Each returns an outcome value that the
# HTTP layer answers (limn.web.answers.add_answer, edit_answer).

def located(loc: PinLocation | None) -> Located | None:
    """A pin location found on disk (pin_location) as the value limn.pins.edit records: absolute path and rel."""
    return None if loc is None else Located(str(loc.path), loc.rel)


def add_pin(D: Doc, request: AddRequest, actor: dict) -> OpenPin:
    """Saves a new pin in document D from a parsed POST /api/pin body (limn.web.parse.parse_add) -> the new open pin. A
    LaTeX document gets a line pin with its anchor, the author and - since 0.3.2 (ADR-0006) - file_rel next to the
    absolute file; a view-only document gets a region pin. Queues mention/assigned notices and emits them after the
    write."""
    match request.place:
        case LinePlace() as place:
            return _add_line_pin(place, request, actor, D)
        case RegionPlace() as place:
            return _add_region_pin(place, request, actor, D)


def _add_line_pin(place: LinePlace, request: AddRequest, actor: dict, D: Doc) -> OpenPin:
    """Append a new line pin to document D under the pin lock and emit its notices.

    The file's lines are read before the lock (as always); under it the shell takes the time, the next id (pins.seq),
    the note's @-tags, the anchor over those lines with the file's mtime, the current build and where the file is now,
    and limn.pins.edit.new_line_pin() builds the record. The notices are made from the finished record, so they name
    the pin's own document D.
    """
    f = Path(place.fields["file"])
    lines = tex_lines(f)
    evs = []

    def fn(rows):
        """The transact() step: builds the pin, appends it and queues its notices -> (pin, True)."""
        at = now_str()
        pid = next_id(rows)
        tags = note_tags(request.note, "", rows, request.hints, actor, pid)
        anchoring = Anchoring(anchor_of(lines, place.fields["lo"], place.fields["hi"]),
                              f.stat().st_mtime if f.exists() else 0)
        # Pins down which build's layout coordinates frac belongs to, by build identity (§Position estimation): the
        # viewer echoes pdf_build from the pick response; a call without it (agent curl) takes the current build.
        pin = new_line_pin(place, request, pid, at, actor, tags.mentions, anchoring, build.cur_pages(D).name, D.key,
                           located(pin_location({"file": place.fields["file"]}, C.src)))
        rows.append(dict(pin.record))
        evs.append(make_event("mention", pin.record, actor, tags.notify, text=request.note))
        if request.assignee is not None and request.assignee != ASSIGNEE_AGENT:
            evs.append(make_event("assigned", pin.record, actor, [request.assignee], text=request.note))
        return pin, True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def _add_region_pin(place: RegionPlace, request: AddRequest, actor: dict, D: Doc) -> OpenPin:
    """Append a new pin on view-only document D under the pin lock and emit its notices: {doc, pdf, name, page, frac,
    kind: 'region', quote?, note, pdf_build}, built by limn.pins.edit.new_region_pin(). No lines, no anchor."""
    evs = []

    def fn(rows):
        """The transact() step: builds the pin, appends it and queues its notices -> (pin, True)."""
        at = now_str()
        pid = next_id(rows)
        tags = note_tags(request.note, "", rows, request.hints, actor, pid)
        pin = new_region_pin(place, request, pid, at, actor, tags.mentions, build.cur_pages(D).name, D.key)
        rows.append(dict(pin.record))
        evs.append(make_event("mention", pin.record, actor, tags.notify, text=request.note))
        if request.assignee is not None and request.assignee != ASSIGNEE_AGENT:
            evs.append(make_event("assigned", pin.record, actor, [request.assignee], text=request.note))
        return pin, True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def edit_scope(pid: int) -> tuple:
    """(region, document) of an edit of pin pid, read without the lock before the edit (as always): whether it is a
    view-only (region) pin, and the document its loc is checked against - the pin's own, else the first one."""
    r0 = find_pin(read_pins()[0], pid)
    region = r0 is not None and is_region_pin(r0)
    return region, (doc_by_key(pin_doc_key(r0)) if r0 is not None else None) or DOCS[0]


def edit_pin(pid: int, request: EditRequest, actor: dict,
             region: bool = False) -> OpenPin | ReviewPin | DonePin | EditRefusal | PinNotFound:
    """Edits pin pid's note, range, location and note-level fields in place; id/at/done never change.

    request is the parsed body with its loc already placed against the pin's own document (limn.web.parse.parse_edit
    and parse_edit_place, with region and the document from edit_scope()); region says the pin is a view-only one,
    whose file is never located. Under the pin lock the shell reads where the pin's file will be and - for a lo/hi
    edit - its line count, and limn.pins.edit.decide_edit() refuses or accepts: a closed pin cannot be reshaped, a
    stale base_rev is a conflict (so a pin the agent closed, or one line matching moved, is never silently overwritten
    with stale lo/hi), a merged note_append must fit NOTE_MAX, lo/hi must fit the file. Refusals write nothing of their
    own. An accepted edit gets a new anchor when its range changed, the note's @-tags, edited_at/by and rev
    (evolve_edit); mention/assigned notices are emitted after the write.
    """
    clock = datetime.now().astimezone().strftime("%H:%M") if request.note_append is not None else ""
    evs = []

    def fn(rows):
        """The transact() step: decide the edit on pin pid and, if accepted, write it in place and queue its notices."""
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        pin = parse_pin(r)
        where = None if region else pin_location(file_after(r, request), C.src)   # ADR-0006: an edit records where the file is now
        count = len(tex_lines(where.path)) if where is not None and request.sets_lines() else None
        event = decide_edit(pin, request, typed_actor(actor), now_str(), clock, count, NOTE_MAX)
        if not isinstance(event, PinEdited):
            return event, False
        span = event.span()
        anchoring = None
        if span is not None and where is not None:
            f = where.path
            anchoring = Anchoring(anchor_of(tex_lines(f), *span), f.stat().st_mtime if f.exists() else 0)
        tags = None if event.note is None else note_tags(event.note, str(r.get("note") or ""), rows, request.hints,
                                                         actor, pid)
        assigns = request.assignee not in (None, ASSIGNEE_AGENT) and r.get("assignee") != request.assignee
        edited = evolve_edit(pin, event, located(where), anchoring, None if tags is None else tags.mentions,
                             _person_name(request.assignee) if assigns else None)
        r.clear()
        r.update(edited.record)
        if tags is not None:
            evs.append(make_event("mention", r, actor, tags.notify, text=r.get("note")))
        if assigns:
            evs.append(make_event("assigned", r, actor, [request.assignee], text=r.get("note")))
        return edited, True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def thread_replies(r: dict) -> list:
    """Replies only, excluding state-transition records (ev)."""
    th = r.get("thread") if isinstance(r.get("thread"), list) else []
    return [m for m in th if isinstance(m, dict) and not m.get("ev")]


def thread_round(r: dict) -> list:
    """The thread of the currently open round - posts after the last close (ev=close). Everything, if never closed.
    For a reopened pin, starts from (and includes) the reopen reason (ev=reopen) - this is the part an agent
    needs to read when fixing it again. That only applies if the last reopen is after the last close -
    otherwise (still under review, not yet reopened), it's simply everything after the last close. Without
    this distinction, a reply posted during review (between close and reopen) leaked into the new round after
    reopening as a defect (e.g. that reply's @-tags incorrectly ended up in the new round's addressed_to)."""
    th = r.get("thread") if isinstance(r.get("thread"), list) else []
    last_close = max((i for i, m in enumerate(th) if isinstance(m, dict) and m.get("ev") == "close"), default=-1)
    last_reopen = max((i for i, m in enumerate(th) if isinstance(m, dict) and m.get("ev") == "reopen"), default=-1)
    start = last_reopen if last_reopen > last_close else last_close + 1
    return [m for m in th[start:] if isinstance(m, dict)]


def pin_reopened_in_round(r: dict) -> bool:
    """Has it been reopened since it was last completed (last close) - drives pins.md's "reopened" marker (§Pending review).
    This is effectively the same condition as thread_round() starting the current round from the reopen,
    but it's kept separate in case their definitions diverge in the future (the old version only checked
    "is the round's first post a reopen", which missed a round where a confirm (ev=confirm) followed the
    reopen - after a confirm-then-reopen, the round must start at [reopen, ...], not [confirm, reopen, ...])."""
    th = r.get("thread") if isinstance(r.get("thread"), list) else []
    last_close = max((i for i, m in enumerate(th) if isinstance(m, dict) and m.get("ev") == "close"), default=-1)
    last_reopen = max((i for i, m in enumerate(th) if isinstance(m, dict) and m.get("ev") == "reopen"), default=-1)
    return last_reopen > last_close


# ---------------------------------------------------------------- People, @-tags, events (docs/handbook/api.md §@태그·사람·이벤트)
#
# people.json = tailnet people who have opened (or done something in) this viewer {login,name,pic,first_seen,last_seen}.
# Local/agent is never recorded. @-tag candidates are people.json union the authors/actors left on pins. Post text
# keeps '@name' as-is; only the resolved login is recorded in mentions. events.jsonl = an append-only record for a
# future external notification integration (GitHub/Telegram/email) to read. For now it's write-only - nothing is sent.
# Both files are written to a temp file under a lock and then os.replace'd (atomic) - readers only ever see the old file or the new one.

PEOPLE_LOCK = threading.Lock()
EVENTS_LOCK = threading.Lock()
_PEOPLE_SEEN: dict = {}            # (people.json path, login) -> (name, pic, epoch last written) - not rewritten if the value is unchanged


def _valid_people(d) -> list:
    rows = d.get("people") if isinstance(d, dict) else None
    return [x for x in (rows or []) if isinstance(x, dict) and isinstance(x.get("login"), str) and x["login"]
            and _is_actor(x)]


def load_people() -> list:
    try:
        d = json.loads(C.people_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return _valid_people(d)


def people_text(rows: list) -> str:
    rows.sort(key=lambda x: x["login"])
    return json.dumps({"version": 1, "people": rows}, ensure_ascii=False, indent=1) + "\n"


@contextlib.contextmanager
def store_lock(state: Path, name: str):
    """Cross-process lock around one read-modify-write of a state file. The running server (record_person) and
    `limn member` / `limn token` may write the same file at once; a thread lock alone would let one of them
    overwrite the other's change with stale data. The lock file (.<name>.lock) stays in the state dir."""
    fd = os.open(str(Path(state) / (".%s.lock" % name)), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)                                     # closing the descriptor releases the lock


def record_person(actor: dict, now: float = None, role: str = None) -> bool:
    """Records a tailnet person into people.json (only written for a new person, a name/picture change, or when last_seen is stale past PEOPLE_TOUCH_S).
    Local/agent is never recorded. The request continues even if the write fails (only a warning). Returns True if it wrote.

    A person's `role` (set with `limn member`) is kept as-is. A person seen for the first time gets no role field (= editor)
    unless `role` is given (the local owner is recorded as owner)."""
    login = (actor or {}).get("login")
    if not login or is_agent(actor):
        return False
    now = time.time() if now is None else now
    name, pic = actor.get("name") or login, actor.get("pic")
    key = (str(C.people_file), login)
    seen = _PEOPLE_SEEN.get(key)
    if seen and seen[0] == name and seen[1] == pic and now - seen[2] < PEOPLE_TOUCH_S:
        return False
    with PEOPLE_LOCK:
        try:
            with store_lock(C.state, "people"):
                rows = load_people()                  # re-read under the lock - `limn member` may have just changed it
                stamp = datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                cur = next((x for x in rows if x["login"] == login), None)
                if cur is None:
                    cur = {"login": login, "first_seen": stamp}
                    if role and role != DEFAULT_ROLE:
                        cur["role"] = role
                    rows.append(cur)
                cur["name"] = name
                if pic:
                    cur["pic"] = pic
                cur["last_seen"] = stamp
                atomic_write(C.people_file, people_text(rows), mode=0o600)
        except OSError as e:
            print("warning: failed to write people.json: %s" % e, file=sys.stderr)
            return False
        _PEOPLE_SEEN[key] = (name, pic, now)
    return True


def known_people(rows: list = None) -> dict:
    """@-tag candidates {login: {login,name,pic?,last_seen?}} - from people.json plus authors/actors/thread posters on pins. Local is excluded."""
    out: dict = {}
    def add(a, seen=None):
        if not isinstance(a, dict) or not isinstance(a.get("login"), str) or not a["login"] or is_agent(a):
            return
        cur = out.setdefault(a["login"], {"login": a["login"], "name": a.get("name") or a["login"]})
        if a.get("pic") and not cur.get("pic"):
            cur["pic"] = a["pic"]
        if seen:
            cur["last_seen"] = seen
    for x in load_people():
        add(x, x.get("last_seen"))
    for r in rows if rows is not None else read_pins()[0]:
        for k, v in r.items():
            if k == "author" or k.endswith("_by"):
                add(v)
        for m in r.get("thread") or []:
            add(m.get("by"))
    return out


def _mention_tokens(people: dict) -> list:
    """(text, {login...}) - longest first. Full name, login, the part of the login before @, and the first word of the name (multiple logins if they collide)."""
    toks: dict = {}
    for login, p in people.items():
        name = str(p.get("name") or "")
        for t in {name, login, login.split("@")[0]} | ({name.split()[0]} if len(name.split()) > 1 else set()):
            if len(t) >= 2:
                toks.setdefault(t.lower(), set()).add(login)
    return sorted(toks.items(), key=lambda kv: -len(kv[0]))


def resolve_mentions(text: str, people: dict, hints=None, exclude: str = None) -> list:
    """Resolves '@name' to a login (post text is left unchanged). Skipped if the character before '@' is
    alphanumeric (an email address); treated as a different word if an ASCII letter immediately follows a
    name ending in an ASCII letter (@Alicex). A Korean particle attached right after ('@서준님') is fine.
    When a token matches multiple people (same first word of the name), only those in the viewer-selected
    hints are included. Returned in first-seen order, no duplicates. `exclude` (usually the author's own
    login) is removed from the result - so self-@-tagging never turns into "a pin that called someone" /
    "I was called" (observed: a self-mention was picked up as addressed)."""
    return list(dict.fromkeys(mention_hits(text, people, hints, exclude)))


def mention_hits(text: str, people: dict, hints=None, exclude: str = None) -> list:
    """Every resolved '@name' occurrence in text, in order and with repeats (resolve_mentions() is its de-duplicated
    form). Counting occurrences is what tells a note edit that *adds* another '@Bob' apart from one that only
    fixes a typo next to an existing '@Bob' (note_tags)."""
    text = str(text or "")
    if "@" not in text or not people:
        return []
    low, toks, hints = text.lower(), _mention_tokens(people), set(hints or ())
    found = []
    for i, ch in enumerate(text):
        if ch != "@" or (i > 0 and (text[i - 1].isalnum() or text[i - 1] in "._-")):
            continue
        rest = low[i + 1:]
        for tok, logins in toks:
            if not rest.startswith(tok):
                continue
            nxt = rest[len(tok):len(tok) + 1]
            if nxt and tok[-1].isascii() and tok[-1].isalnum() and nxt.isascii() and (nxt.isalnum() or nxt == "_"):
                continue
            pick = logins if len(logins) == 1 else logins & hints
            for lg in sorted(pick):
                if lg != exclude:
                    found.append(lg)
            if pick:
                break
    return found


def pin_mentions_all(r: dict) -> list:
    """Every person called out on this pin (note + the entire thread)."""
    out = list(r.get("mentions") or [])
    for m in r.get("thread") or []:
        for lg in m.get("mentions") or []:
            if lg not in out:
                out.append(lg)
    return out


def _round_mentions(r: dict) -> list:
    """The note's @-tags plus @-tags in the current round's (thread_round) thread posts - shared material for addressed_to/fyi_mentions_to."""
    out = list(r.get("mentions") or [])
    for m in thread_round(r):
        for lg in m.get("mentions") or []:
            if lg not in out:
                out.append(lg)
    return out


def addressed_to(r: dict) -> list:
    """Is this a pin that **asked** a person something - only meaningful for a question pin (kind_req=question). pins.md marks it
    '→ @name', and an agent skips it (unless the requesting user says otherwise). A fix pin's @-tags are just
    for reference, not something a person must answer to close it, so they don't go here - fyi_mentions_to()
    handles those instead (observed: a fix pin that FYI-tagged someone was picked up as '→ @name' and an agent
    skipped it forever). A closed-then-reopened pin doesn't count posts from the old round (thread_round)."""
    a = r.get("assignee")
    if a:                                   # a pin with an assignee: if it's a person, it was handed to them; if it's the agent, no one was called
        return [] if a == ASSIGNEE_AGENT else [a]
    if r.get("kind_req") != "question":
        return []
    return _round_mentions(r)


def fyi_mentions_to(r: dict) -> list:
    """People called for reference on a fix pin (kind_req != question) - never skipped, only shown in pins.md as '참고 @name'.
    The opposite of addressed_to() (non-question pins). On a pin with an assignee, every @-tag other than the assignee is FYI."""
    if r.get("assignee"):
        to = addressed_to(r)
        return [lg for lg in _round_mentions(r) if lg not in to]
    if r.get("kind_req") == "question":
        return []
    return _round_mentions(r)


def _excerpt(s, n: int = 140) -> str:
    return _flat(s, n)


def make_event(typ: str, r: dict, actor: dict, to, msg: dict = None, text: str = None) -> dict:
    """One events.jsonl line (seq/at are filled in by emit_events). The actor themselves and local are removed from to - None (not recorded) if that leaves it empty."""
    me = (actor or {}).get("login")
    to = [lg for lg in dict.fromkeys(to or []) if lg and lg != me and lg != LOCAL_ACTOR["login"]]
    if not to:
        return None
    ev = {"type": typ, "pin": r.get("id"), "doc": pin_doc_key(r), "to": to, "by": who(actor)}
    if r.get("kind_req"):
        ev["kind_req"] = r["kind_req"]
    if msg is not None:
        ev["msg"] = msg.get("id")
    ex = _excerpt(text if text is not None else (msg or {}).get("text", ""))
    if ex:
        ev["excerpt"] = ex
    return ev


def emit_events(events: list) -> None:
    """Appends events to the end of events.jsonl (lock + full atomic replace, leaving the earlier part untouched - append-only). seq starts from the file's last seq+1.
    Only called after the pin write has committed (prevents phantom events). A failure is just a warning - the pin change already went through."""
    events = [e for e in events or [] if e]
    if not events:
        return
    with EVENTS_LOCK:
        rows, _ = _read_events()
        seq = max((e.get("seq", 0) for e in rows), default=0)
        now = time.time()
        for e in events:
            seq += 1
            e.update(seq=seq, at=now_str(), ts=round(now, 3))
        rows = (rows + events)[-EVENTS_KEEP:]
        try:
            atomic_write(C.events_file, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in rows))
        except OSError as e:
            print("warning: failed to write events.jsonl: %s" % e, file=sys.stderr)


_EVENTS_CACHE: dict = {}


def _read_events() -> tuple:
    """(event list, file signature). Since polling reads this often, the cache is used when mtime/size are unchanged."""
    try:
        st = C.events_file.stat()
    except OSError:
        return [], None
    sig = (str(C.events_file), st.st_mtime_ns, st.st_size)
    c = _EVENTS_CACHE.get("v")
    if c and c[0] == sig:
        return list(c[1]), sig
    rows = []
    for line in C.events_file.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and _is_int(e.get("seq")):
            rows.append(e)
    _EVENTS_CACHE["v"] = (sig, rows)
    return list(rows), sig


def note_mention_targets(added: Sequence[str], recent: Sequence[dict], by: str | None, pin: object, now: float,
                         window: float = NOTE_MENTION_COOLDOWN_S) -> list[str]:
    """Which of `added` (people a note save newly tags, in order) get a mention event - the cooldown of issue #10 L3.

    A person is left out when `by` already sent them a note mention about the same pin in the last `window` seconds
    before `now`: toggling '@Bob' off and on through note edits would otherwise notify Bob on every edit. The key is
    (actor login, target login, pin id). Only note mentions count - `mention` records without `msg`; replies and reopen
    reasons carry their thread message id and keep notifying every time, since they leave a visible entry. A suppressed
    mention is never written, so the window runs from the last one sent. A record counts when its `ts` lies less than
    `window` from `now` on either side - events.jsonl rounds ts to milliseconds, so the last mention can read as a
    moment ahead of the next save, and after the clock steps back a far-future record must not silence anyone for
    longer than the window. Records without a numeric ts are ignored. Pure: `recent` (events.jsonl records) and `now`
    (epoch seconds) come from the caller."""
    cooled: set = set()
    for e in recent:
        if e.get("type") != "mention" or "msg" in e or e.get("pin") != pin:
            continue
        if (e.get("by") or {}).get("login") != by:
            continue
        ts = e.get("ts")
        if _is_num(ts) and abs(now - ts) < window:
            cooled.update(e.get("to") or [])
    return [lg for lg in added if lg not in cooled]


class NoteTags(NamedTuple):
    """What a note save means for @-tags: the note's resolved tags (the pin's mentions) and whom to notify now."""
    mentions: tuple[str, ...]
    notify: list[str]


def note_tags(note: str, old_note: str, rows: list, hints, actor: dict, pid: object) -> NoteTags:
    """Resolve the saved note's @-tags and decide who gets a mention event for pin pid.

    Everyone this save or edit explicitly @-tags is notified: a person whose '@name' occurs more often in the new note
    than in old_note (the note before this edit; empty for a new pin). A typo fix next to an existing '@Bob' notifies
    nobody, while an edit or note_append that writes '@Bob' again notifies Bob even though the note already tagged
    him - unless this actor's note already notified him about this pin within NOTE_MENTION_COOLDOWN_S
    (note_mention_targets, which reads events.jsonl). Runs inside transact(): the caller emits the event under the
    same PIN_LOCK, so the next save sees it."""
    ppl = known_people(rows)
    me = (actor or {}).get("login")
    hits = mention_hits(note or "", ppl, hints, exclude=me)
    before = Counter(mention_hits(old_note or "", ppl, hints, exclude=me))
    new = list(dict.fromkeys(hits))
    counts = Counter(hits)
    added = [lg for lg in new if counts[lg] > before[lg]]
    if added:
        added = note_mention_targets(added, _read_events()[0], me, pid, time.time())
    return NoteTags(tuple(new), added)


NOTIFY_TYPES = ("mention", "review_requested", "replied", "reopened", "assigned", "dropped")
EVENTS_SINCE_MAX = 20


def events_since(actor: dict, cursor: int | None) -> dict:
    """Notification material carried in /api/meta polling (docs/handbook/api.md §브라우저 알림 커서). Always includes ev_seq (the latest event number), and if
    the parsed ev=<number> is given, includes up to 20 events after it addressed to the current requester's tailnet login - nothing for local/agent. Read-only."""
    rows, _ = _read_events()
    out = {"ev_seq": max((e.get("seq", 0) for e in rows), default=0)}
    if cursor is None:
        return out
    me = (actor or {}).get("login")
    if not me or is_agent(actor):
        out["events"] = []
        return out
    names = {d.key: d.name for d in DOCS}
    evs = [dict(e, doc_name=names.get(e.get("doc"), e.get("doc"))) for e in rows
           if e.get("seq", 0) > cursor and e.get("type") in NOTIFY_TYPES and me in (e.get("to") or [])
           and (e.get("by") or {}).get("login") != me]
    out["events"] = evs[-EVENTS_SINCE_MAX:]
    return out


# ---------------------------------------------------------------- Audit log (<state>/audit.jsonl, docs/handbook/api.md §감사 기록 (`audit.jsonl`))
#
# events.jsonl keeps only the newest EVENTS_KEEP records, so ordinary notification traffic pushed out the record of who
# cleared every pin (issue #10 L5). Destructive and owner actions are therefore also written here, one JSON object per
# line, appended under a cross-process lock and never rewritten or truncated by Limn. The HTTP handler records clear and
# purge (via "http"); the state helpers behind `limn token` / `limn member` record theirs as the OS account (via "cli").
# The existing events (`cleared`, `purged`) are still written for compatibility. Old servers never open this file.

AUDIT_FILE = "audit.jsonl"
AUDIT_ACTIONS = ("cleared", "purged", "token_created", "token_revoked", "member_added", "member_removed", "member_role")
AUDIT_VIA = ("http", "cli")


def audit_entry(action: str, by: dict, via: str, details: dict, now: float) -> dict:
    """One audit.jsonl line: {at, ts, action, by, via, details}.

    at is the local wall-clock string of `now` (the shape now_str() writes), ts the same instant in epoch seconds; by
    keeps only {login, name} of the principal (name falls back to login). Raises ValueError for an action or via
    outside AUDIT_ACTIONS / AUDIT_VIA - a programming error, never a request error. Pure: the caller passes the clock."""
    if action not in AUDIT_ACTIONS:
        raise ValueError("unknown audit action %r" % action)
    if via not in AUDIT_VIA:
        raise ValueError("unknown audit channel %r" % via)
    login = (by or {}).get("login")
    return {"at": datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d %H:%M:%S"), "ts": round(now, 3),
            "action": action, "by": {"login": login, "name": (by or {}).get("name") or login}, "via": via,
            "details": dict(details)}


def append_audit(state: Path, entry: dict) -> bool:
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
                    line = line[os.write(fd, line):]
                os.fsync(fd)
            finally:
                os.close(fd)
    except OSError as e:
        print("warning: failed to write %s: %s" % (path, e), file=sys.stderr)
        return False
    return True


def os_actor() -> dict:
    """The local account running this process as an audit `by` {login, name}: who ran `limn token` / `limn member` on
    the server machine. Read from the password database by uid, not from $USER; "uid:<n>" if the uid has no entry."""
    uid = os.getuid()
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = "uid:%d" % uid
    return {"login": name, "name": name}


# Service worker: shows notifications (showNotification - Chrome on Android blocks the page's own new
# Notification()) and, on click, brings the viewer tab forward and opens that pin (or, for the [되살리기] action on a
# 'dropped' notification, asks the tab to restore it; with no tab open, the new window's link carries &act=restore). There is no fetch handler -
# app data and page images are never cached.
SW_JS = r"""'use strict';
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('notificationclick',e=>{e.notification.close();const d=e.notification.data||{};
  const url=new URL(d.url||'/',self.location.origin).href;
  e.waitUntil((async()=>{const cs=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    for(const c of cs){if(new URL(c.url).origin!==self.location.origin)continue;
      try{await c.focus();}catch(_){}
      c.postMessage({type:e.action==='restore'?'restore-pin':'open-pin',pin:d.pin,doc:d.doc});return;}
    if(self.clients.openWindow)await self.clients.openWindow(url+(e.action==='restore'?'&act=restore':''));})());});
"""


def reply_reopens(r: dict, human: bool, mentioned, reopen=None) -> bool:
    """Does a reply reopen stored pin r? limn.pins.lifecycle.reopens_on_reply() on the record's state; the viewer's
    preview (replyReopens) mirrors that rule."""
    return reopens_on_reply(parse_pin(r), human, mentioned, reopen)


def reply_pin(pid: int, text: str, actor: dict, hints=None, reopen=None,
              human=None) -> OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound:
    """One reply (from a person or an agent); the pin as it stands after it is returned, its new entry last in the thread.

    Whether it also reopens the pin is decided by limn.pins.lifecycle.reopens_on_reply() - the viewer only previews it.
    `human` is whether the poster is a person (the handler also counts a person with the agent role as an agent); None
    means "not an agent actor". A reopening reply is recorded exactly like POST /reopen with the reply as its reason
    (ev=reopen, the same notices), so the pin returns to the open table of pins.md with that reason. Otherwise it is a
    plain reply, refused as ThreadFull when the thread is full; every @-tag in it is a mention (whether or not tagged
    before), and the author plus everyone previously tagged on this pin who is not tagged here gets a replied notice.
    The poster themself gets neither.
    """
    evs = []
    human = (not is_agent(actor)) if human is None else human

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        ment = resolve_mentions(text, known_people(rows), hints, exclude=(actor or {}).get("login"))
        persons = [lg for lg in ment if role_of(lg) != "agent"]     # tagging an agent-role account is not asking a person
        pin = parse_pin(r)
        event = decide_reply(pin, typed_actor(actor), now_str(), text, tuple(ment),
                             reopens_on_reply(pin, human, persons, reopen), THREAD_MAX)
        author = (r.get("author") or {}).get("login")
        before = pin_mentions_all(r)
        match event:
            case ThreadFull():
                return event, False
            case PinReopened():
                replied = reopen_request(pin, event)
                r.clear()
                r.update(replied.record)
                msg = r["thread"][-1]
                _reopen_notices(r, actor, ment, msg, evs)
                # Everyone else tagged on the pin earlier would have heard of a plain reply (replied) - reopening must
                # not silence them.
                evs.append(make_event("replied", r, actor, [lg for lg in sorted(before) if lg != author and lg not in ment],
                                      msg=msg))
            case Replied():
                replied = evolve_reply(pin, event)
                r.clear()
                r.update(replied.record)
                msg = r["thread"][-1]
                # Every @-tag in this reply is a mention, even for someone tagged earlier on the pin (observed in the
                # v0.2.0 QA: a second "@Bob ..." reached nobody). Everyone else involved gets replied - never both.
                evs.append(make_event("mention", r, actor, ment, msg=msg))
                evs.append(make_event("replied", r, actor, [lg for lg in [author] + sorted(before) if lg not in ment],
                                      msg=msg))
        return replied, True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def is_agent(actor: dict) -> bool:
    """An agent actor: a headerless loopback request (LOCAL_ACTOR, login "local") or an API-token principal (login "agent:<name>").
    Picks defaults (a close goes to review, never recorded in people.json) and refuses confirm; the role check in the
    handler (check_role) additionally covers people whose people.json role is agent."""
    login = (actor or {}).get("login", "local")
    return login == LOCAL_ACTOR["login"] or str(login).startswith(AGENT_LOGIN_PREFIX)


def set_done(pid: int, done: bool, actor: dict, reply: str | None = None, ref: str | None = None,
             review: bool | None = None, reason: str | None = None, hints=None, changes=None):
    """Close (done=True) or reopen (done=False) - the single entry POST /close and /reopen and older callers use.

    `reply`/`ref`/`changes` (already parsed by limn.web.parse.parse_close_body/parse_close_changes: changes is a
    sequence of CloseChange, each giving its stored form by .record()) and `review` belong to a close; `reason` and
    `hints` to a reopen. The rules are in limn.pins.lifecycle; see close_pin and reopen_pin.
    """
    if done:
        return close_pin(pid, actor, CloseRequest(reply, ref, tuple(c.record() for c in changes or ()), review))
    return reopen_pin(pid, actor, reason, hints)


def close_pin(pid: int, actor: dict, request: CloseRequest) -> ReviewPin | DonePin | AlreadyClosed | PinNotFound:
    """Close pin pid under the pin lock, then tell the author when it now awaits review (docs/handbook/api.md §닫기).

    Re-closing a closed pin changes nothing (AlreadyClosed) - a second close must not overwrite done_at/closed_by
    and erase who closed it first (observed defect). An agent's close awaits review unless the request says:
    out of 42 observed cases an author reopened an agent-closed pin twice with no record that a person had looked.
    A person with the agent role closes into review because the handler sets request.review for them.
    """
    evs = []

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        pin = parse_pin(r)
        event = decide_close(pin, typed_actor(actor), now_str(), request)
        if isinstance(event, AlreadyClosed):
            return event, False
        closed = evolve_close(pin, event)
        r.clear()
        r.update(closed.record)
        if isinstance(closed, ReviewPin):
            evs.append(make_event("review_requested", r, actor, [(r.get("author") or {}).get("login")],
                                  msg=r["thread"][-1]))
        return closed, True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def reopen_pin(pid: int, actor: dict, reason: str | None, hints) -> OpenPin | PinNotFound:
    """Reopen pin pid under the pin lock; a closed pin records the reason and notifies (see _reopen). rev goes up
    even for a pin that was already open, as before."""
    evs = []

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        opened = _reopen(r, rows, actor, reason, hints, evs, request=True)
        return opened, True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def _reopen(r: dict, rows: list, actor: dict, reason, hints, evs: list, request: bool = False) -> OpenPin:
    """Reopens r in place (inside transact) by limn.pins.lifecycle's rule, and - if the pin was closed - queues a
    mention for everyone the reason @-tags and reopened for the author. Shared by POST /reopen (request=True, which
    also bumps rev) and a reopening reply (which bumps rev once for the reply itself). Returns the reopened pin."""
    pin = parse_pin(r)
    ment = resolve_mentions(reason or "", known_people(rows), hints, exclude=(actor or {}).get("login")) \
        if not isinstance(pin, OpenPin) else []
    event = decide_reopen(pin, typed_actor(actor), now_str(), reason, tuple(ment))
    opened = reopen_request(pin, event) if request else evolve_reopen(pin, event)
    r.clear()
    r.update(opened.record)
    if event.was_closed:
        _reopen_notices(r, actor, ment, r["thread"][-1], evs)
    return opened


def _reopen_notices(r: dict, actor: dict, ment: list, msg: dict, evs: list) -> None:
    """Queue the notices of a reopen: a mention for everyone the reason @-tags, reopened for the author otherwise."""
    evs.append(make_event("mention", r, actor, ment, msg=msg))    # same rule as a reply: every @-tag here
    evs.append(make_event("reopened", r, actor, [lg for lg in [(r.get("author") or {}).get("login")]
                                                 if lg not in ment], msg=msg))


def typed_actor(actor: dict) -> Actor:
    """The typed actor of a request's actor dict: an Agent when is_agent() says so, otherwise a Person."""
    login, name = actor.get("login", "local"), actor.get("name", "")
    if is_agent(actor):
        return Agent(login, name)
    pic = actor.get("pic")
    return Person(login, name, pic if isinstance(pic, str) and pic else None)


def confirm_pin(pid: int, actor: dict) -> DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound:
    """Awaiting review -> done, by a person only (docs/handbook/api.md §검토 대기).

    An agent is refused before the store is touched, as before. Otherwise the pin is loaded under the pin lock
    (transact) and lifecycle.confirm() decides; only a new DonePin is written, in place, so the saved line
    keeps its field order. Every other outcome is returned unchanged for the HTTP layer to answer.
    """
    by = confirmer(typed_actor(actor))
    if isinstance(by, AgentCannotConfirm):
        return by

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        result = confirm(parse_pin(r), by, now_str())
        if isinstance(result, DonePin):
            r.clear()
            r.update(result.record)
            return result, True
        return result, False
    return transact(fn)[1]


def drop_pin(pid: int, actor: dict) -> TrashedPin | PinNotFound:
    """Removes a pin from pins.jsonl and moves it to the Trash (pins.dropped.jsonl). restore brings the same id back.

    The author is told when someone else deletes their pin (a `dropped` event, with [Restore] in the viewer). Expired
    Trash entries are purged in the same write (purge_trash)."""
    evs = []

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        rows.remove(r)
        trashed = drop(parse_pin(r), typed_actor(actor), now_str())
        old, bad = read_jsonl(C.dropped)
        write_dropped(_unexpired(old) + [dict(trashed.record)], bad)
        evs.append(make_event("dropped", r, actor, [(r.get("author") or {}).get("login")], text=r.get("note")))
        return trashed, True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


# ---------------------------------------------------------------- Trash (pins.dropped.jsonl, docs/handbook/domain.md §전이와 할 수 있는 쪽)
#
# A dropped pin stays restorable for TRASH_DAYS, counted from dropped_at (local time, like every *_at string). Reading
# never writes: GET /api/pins/dropped only hides expired entries; the file is rewritten without them at startup, on
# every drop/restore, and by the owner's permanent delete. An entry without a readable dropped_at is kept - its age
# cannot be known, and guessing would delete data. ids stay reserved in pins.seq, so a purged number is never reused.

def trash_expires_ts(r: dict):
    """Epoch seconds at which a Trash entry expires (dropped_at + TRASH_DAYS), or None if dropped_at is unreadable."""
    t = _epoch(r.get("dropped_at"))
    return None if t is None else t + TRASH_DAYS * 86400


def trash_expired(r: dict, now: float = None) -> bool:
    t = trash_expires_ts(r)
    return t is not None and (time.time() if now is None else now) > t


def write_dropped(rows: list, bad=None) -> None:
    """Rewrites pins.dropped.jsonl, keeping a .corrupt-*.bak of unreadable lines first (PinStore.write_dropped)."""
    pin_store().write_dropped(rows, bad)


def _unexpired(rows: list, now: float = None) -> list:
    return [r for r in rows if not trash_expired(r, now)]


def purge_trash(now: float = None) -> int:
    """Rewrites pins.dropped.jsonl without the entries older than TRASH_DAYS. Returns how many went (0 = no write, or the
    write failed - reads hide expired entries anyway, so a failure is only a warning)."""
    _TRASH_CHECKED[0] = time.time() if now is None else now      # any check (startup, drop, restore) restarts the hourly clock
    with PIN_LOCK:
        rows, bad = read_jsonl(C.dropped)
        keep = _unexpired(rows, now)
        n = len(rows) - len(keep)
        if n:
            try:
                write_dropped(keep, bad)
            except OSError as e:                      # e.g. a read-only state dir: expired entries stay hidden, the server still starts
                print("warning: could not purge the Trash: %s" % e, file=sys.stderr)
                return 0
    if n:
        print("trash: purged %d pin(s) deleted more than %d days ago" % (n, TRASH_DAYS), file=sys.stderr)
        sys.stderr.flush()
    return n


TRASH_CHECK_EVERY_S = 3600          # a long-running server also drops expired Trash entries during normal reads, at most this often
_TRASH_CHECKED = [0.0]              # epoch of the last lazy check (per process)


def maybe_purge_trash() -> int:
    """The lazy expiry: called from the reads that already write (GET /api/pins, /pins.md - they re-sync line numbers),
    never from the write-free light poll. One cheap clock comparison; at most once per TRASH_CHECK_EVERY_S it reads the
    Trash and rewrites it only if something expired."""
    now = time.time()
    if now - _TRASH_CHECKED[0] < TRASH_CHECK_EVERY_S:
        return 0
    _TRASH_CHECKED[0] = now
    return purge_trash(now)


def purge_pin(pid: int, actor: dict) -> TrashedPin | NotInTrash:
    """The owner's permanent delete from the Trash (POST /api/pins/{id}/purge; check_role refuses everyone else).
    Returns the purged entry, or NotInTrash (nothing written) if the pin is not in the Trash - an open or closed pin
    must be dropped first; the handler answers that with 404. Leaves a `purged` audit event (to: [], like `cleared`), a `purged` line
    in audit.jsonl (v0.3.1, never rotated out) and a log line, since it cannot be undone."""
    with PIN_LOCK:
        rows, bad = read_jsonl(C.dropped)
        found = find_trashed(_unexpired(rows), pid)
        if isinstance(found, NotInTrash):
            return found
        write_dropped(_unexpired([r for r in rows if r.get("id") != pid]), bad)
        emit_events([{"type": "purged", "to": [], "pin": pid, "by": who(actor)}])
    append_audit(C.state, audit_entry("purged", who(actor), "http", {"pin": pid}, time.time()))   # outside PIN_LOCK: it flocks and fsyncs
    print("trash: pin #%d deleted permanently by %s" % (pid, (actor or {}).get("login")), file=sys.stderr)
    sys.stderr.flush()
    return found


# ---------------------------------------------------------------- In-progress marker (claim, §P0c-C)
#
# A co-author and their agent can work on the same pin at the same time. A TTL'd optimistic marker reduces
# conflicts - it's a signal, not a lock: nothing stops closing or force-claiming a pin another identity holds a valid claim on.

def claim_active(r: dict) -> bool:
    """Does this pin have an unexpired claim now? limn.pins.lifecycle.claim_holds() at the current epoch."""
    return claim_holds(r, time.time())




def claim_pin(pid: int, actor: dict, ttl_min: int,
              eta_min: int = None) -> OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound:
    """Place or extend the in-progress marker (docs/handbook/api.md §처리 중 표시) under the pin lock.

    The rule is limn.pins.lifecycle.claim(): a closed pin or another identity's live claim is refused (409 over HTTP),
    the same identity extends. The clock is read once here - epoch and store string of the same moment.
    """
    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        result = claim(parse_pin(r), typed_actor(actor), time.time(), now_str(), ClaimRequest(ttl_min, eta_min),
                       _epoch(r.get("claimed_at")))
        if isinstance(result, OpenPin):
            r.clear()
            r.update(result.record)
            return result, True
        return result, False
    return transact(fn)[1]


def unclaim_pin(pid: int, actor: dict) -> OpenPin | ReviewPin | DonePin | NotClaimed | PinNotFound:
    """Clear the in-progress marker, whoever asks; written only when there was a claim."""
    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        result = unclaim(parse_pin(r))
        if isinstance(result, NotClaimed):
            return result, False
        r.clear()
        r.update(result.record)
        return result, True
    return transact(fn)[1]


def restore_pin(pid: int, actor: dict) -> OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive:
    """Writes to pins.jsonl first, and only removes it from the dropped record once that succeeds.

    Reversing the order means a crash between the two writes makes the pin vanish from both files (observed).
    With this order, the worst case is "present in both", which is recoverable."""
    with PIN_LOCK:                                   # RLock - bundles transact and cleaning up the dropped record together
        result = transact(lambda rows: _restore(rows, pid, actor))[1]
        if isinstance(result, (NotInTrash, AlreadyLive)):
            return result                            # refused: the Trash file is left as it was
        old, bad = read_jsonl(C.dropped)
        write_dropped(_unexpired([r for r in old if r.get("id") != pid]), bad)
        return result


def _restore(rows: list, pid: int, actor: dict):
    """The transact() step of restore_pin: puts the newest unexpired Trash copy of pin pid back into rows, re-synced and
    with rel_path and the current file recorded (ADR-0006). The rule is limn.pins.lifecycle.restore(); NotInTrash
    (404) and AlreadyLive (409) leave rows unchanged."""
    old, _ = read_jsonl(C.dropped)
    trashed = find_trashed(_unexpired(old), pid)
    if isinstance(trashed, NotInTrash):
        return trashed, False
    result = restore(trashed, find_pin(rows, pid) is not None, typed_actor(actor), now_str())
    if isinstance(result, AlreadyLive):
        return result, False
    rec = dict(result.record)
    sync_all([rec])
    stamp_location(rec, C.src)                       # ADR-0006: a restored pin records where its file is now
    rows.append(rec)
    rows.sort(key=lambda r: r["id"])
    return parse_pin(rec), True


CLEAR_CONFIRM = "clear all pins"


def clear_pins(actor: dict | None = None) -> dict:
    """Archives everything to pins_<ts>.jsonl.bak and clears it. pins.seq is untouched, so ids keep incrementing.
    Records a `cleared` event (who, how many, which archive), a `cleared` line in audit.jsonl (v0.3.1 - the event can
    rotate out of events.jsonl, the audit line does not) and a log line - the only bulk-destructive operation, so it
    always leaves a trace. Returns {"cleared": n, "archive": <file name or None>}."""
    by = who(actor or LOCAL_ACTOR)
    with PIN_LOCK:
        n, archive = pin_store().clear()             # never over an earlier archive of the same second
        emit_events([{"type": "cleared", "to": [], "by": by, "n": n, "archive": archive}])
    append_audit(C.state, audit_entry("cleared", by, "http", {"n": n, "archive": archive}, time.time()))   # outside PIN_LOCK: it flocks and fsyncs
    print("clear: %d pin(s) archived to %s by %s" % (n, archive or "-", (actor or LOCAL_ACTOR).get("login")), file=sys.stderr)
    sys.stderr.flush()
    return {"cleared": n, "archive": archive}


def ceil5(minutes: float) -> int:
    """Rounds minutes up to 5-minute steps (minimum 5). Same rule as the viewer's ceil5() - an estimate is approximate, so showing it to the minute would be false precision."""
    return max(5, int(math.ceil(minutes / 5.0 - 1e-9)) * 5)


def claim_md(r: dict, now: float = None) -> str:
    """The in-progress marker for pins.md's number column - "처리 중(이름, 약 15분)". The remaining estimate is rounded up to 5-minute
    steps, or "예상 초과" if exceeded; a legacy claim made without an estimate shows just the name. The lock auto-expiry time is never
    used (it was misread as the estimated completion time)."""
    now = time.time() if now is None else now
    name = md_cell((r.get("claimed_by") or {}).get("name") or "?")
    eta = r.get("eta_ts")
    if not _is_num(eta):
        return "처리 중(%s)" % name
    left = (float(eta) - now) / 60.0
    return "처리 중(%s, %s)" % (name, "약 %d분" % ceil5(left) if left > 0 else "예상 초과")


def render_pins_md(rows: list) -> None:
    """Rewrites pins.md from rows alone (PinStore.render_md). Callers hold PIN_LOCK."""
    pin_store().render_md(rows)


def md_cell(v, newline: str = " ") -> str:
    """One pins.md table cell. '|' would add a column and a newline would break the row - if a record value
    went in as-is, the table would break (observed: kind 'env:x|y' produced an 8-column row). Every cell goes through this function."""
    s = str("" if v is None else v).replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("|", "\\|").replace("\n", newline)


def region_text_of(r: dict) -> str:
    """A view-only pin's location text: "쪽 3, 영역 가로 12-55% 세로 30-48%"."""
    fr = r.get("frac") if isinstance(r.get("frac"), list) and len(r["frac"]) == 4 else [0, 0, 0, 0]
    try:
        x, y, w, h = [float(v) * 100 for v in fr]
    except (TypeError, ValueError):
        x = y = w = h = 0.0
    return "쪽 %s, 영역 가로 %d–%d%% 세로 %d–%d%%" % (r.get("page", "?"), round(x), round(x + w), round(y), round(y + h))


def location_col(r: dict) -> str:
    """Path relative to C.src - for a root file this equals the basename, so existing rows are unchanged.
    A view-only PDF's pin has no line, so it's "쪽 N, 영역 ..." instead (the PDF path is in the document section header)."""
    if is_region_pin(r):
        return md_cell(region_text_of(r))
    loc = pin_location(r, C.src)                     # ADR-0006: still relative after the checkout moved
    name = loc.rel if loc is not None else (Path(str(r.get("file", ""))).name or str(r.get("name") or ""))
    return "`%s L%s-L%s`" % (md_cell(name),md_cell(r.get("lo")), md_cell(r.get("hi")))


def range_label(r: dict) -> str:
    """Range column: if scope is set, env* -> env:<name>, para -> paragraph, raw/lines -> lines; otherwise the legacy kind.
    Every branch escapes via md_cell (missing that on just the env branch used to be a bug)."""
    if is_region_pin(r):
        return "영역"
    scope = r.get("scope")
    if scope and str(scope).startswith("env"):
        k = str(r.get("kind") or "")
        return md_cell(k if k.startswith("env:") else "env:%s" % (k or "?"))
    if scope == "para":
        return "paragraph"
    if scope in ("raw", "lines"):
        return "lines"
    return md_cell(r.get("kind") or "")


def render_quote(r: dict) -> str:
    """The «quote...» exception: only when the pin range is a single line, that line exceeds 600 characters, and scope is raw/para/absent.
    Always attached for a view-only PDF's pin - with no line number, the region text is the agent's only clue to the source."""
    if is_region_pin(r):
        q = r.get("quote")
        return "«%s» " % md_cell(q) if q else ""
    scope = r.get("scope")
    if scope not in (None, "raw", "para"):
        return ""
    lo, hi = r.get("lo"), r.get("hi")
    if not (_is_int(lo) and _is_int(hi)) or lo != hi:
        return ""
    q = r.get("quote")
    if not q:
        return ""
    loc = pin_location(r, C.src)
    if loc is None:                                   # outside the tree: never read (the line would leak into pins.md)
        return ""
    lines = tex_lines(loc.path)
    if not (1 <= lo <= len(lines)) or len(lines[lo - 1]) <= 600:
        return ""
    # q was already truncated by truncate_quote() when it was saved (an ellipsis is already attached if it
    # was cut) - truncating again to 60 characters here would cut into that ellipsis and look
    # double-truncated. Only the pipe character is escaped.
    return "«%s» " % md_cell(q)


LEGEND = ("표시: '#N 범위 안'·'#N과 같은 범위' = N과 한 번에 고치고 둘 다 닫는다 · '#N과 일부 겹침' = 참고만, 각자 처리해도 된다 · "
          "'처리 중(이름, 약 N분)' = 다른 에이전트가 잡음, 건너뛴다 · '수정됨' = 저장 뒤 메모·범위가 바뀜 · "
          "'위치 잃음' = 위치를 되찾지 못함(네가 방금 고친 곳이면 확인 후 닫아도 된다) · "
          "'질문' = 고칠 곳이 아니라 물음이다, 답글(reply)로 답하고 닫는다 · "
          "'다시 열림' = 검토에서 되돌아온 핀, 메모 칸의 '다시 연 이유'대로 다시 고친다 · "
          "'→ @이름' = 담당이 사람인 핀(담당 없는 옛 핀은 사람에게 물은 질문 핀), 사용자가 따로 시키지 않으면 건너뛴다 · "
          "'참고 @이름' = 알림만 간 참고용 태그다, 담당이 아니므로 건너뛰지 않는다 · "
          "«…» = 줄 안에서 가리킨 부분의 렌더 글자(검색 힌트, 원문과 다를 수 있음)")
# v0.2: the one header line added to pins.md - how an agent authenticates (docs/handbook/api.md §인증).
TOKEN_GUIDANCE = ("에이전트 인증: 모든 요청에 `Authorization: Bearer <토큰>` 헤더를 붙인다(`curl -H \"Authorization: Bearer $LIMN_TOKEN\" …`, "
                  "토큰은 사용자가 `limn token create <인스턴스>` 로 발급해 준다) · "
                  "헤더 없는 로컬 요청을 에이전트로 받는 방식은 폐지 예정이다 · "
                  "테일넷 주소(원격)로 오는 신원 헤더 없는 요청(태그 장치 등)은 403 이다 — 원격 에이전트는 반드시 토큰을 붙인다")


TOKEN_FILE_EXAMPLE = "~/.config/limn/<인스턴스>.token"   # the convention, shown when this server does not know its own file


def shell_path(path: Path, home: Path | None) -> str:
    """path as one word an agent's shell on this machine reads back: `~/<rest>` when it is under home and the rest has
    only plain characters (the tilde still expands inside `$(cat ...)`), else the absolute path, shell-quoted."""
    if home is not None:
        try:
            rest = path.relative_to(home)
        except ValueError:
            rest = None
        if rest is not None and re.fullmatch(r"[A-Za-z0-9._/-]+", str(rest)):
            return "~/%s" % rest
    return shlex.quote(str(path))


def token_file_curl(shown: str) -> str:
    """The curl form an agent on this machine uses with the instance's token file (ADR-0007): the shell reads the
    file at call time, so the text names the file and never carries the token."""
    return "`curl -H \"Authorization: Bearer $(cat %s)\" …`" % shown


def token_guidance_line(shown_file: str | None) -> str:
    """The agent-auth line of pins.md: TOKEN_GUIDANCE as before, plus one clause when this machine's agents have a token
    file to send (shown_file, its shell path; None = no file yet, or a remote reader who cannot reach it). The clause
    is appended after the old text, never woven in, so the line still starts with what agents already match."""
    if not shown_file:
        return TOKEN_GUIDANCE
    return (TOKEN_GUIDANCE + " · 이 기기의 에이전트는 토큰 파일을 붙인다: " + token_file_curl(shown_file)
            + "(파일 내용은 출력하지도 저장소에 옮기지도 않는다)")


def loopback_refused_text(token_file: Path | None, exists: bool, home: Path | None) -> str:
    """The 401 text for a headerless request from this machine when the loopback agent is off (--no-agent-loopback,
    AGENT_LOOPBACK=0). The v0.2 text comes first, unchanged; then where this machine's agents get their token: the
    instance's token file when the server knows it (token_file, and whether it exists), else the convention.
    Pure: the caller stats the file and passes the home folder."""
    shown = shell_path(token_file, home) if token_file is not None else TOKEN_FILE_EXAMPLE
    text = ("%s 이 인스턴스는 헤더 없는 로컬 요청을 받지 않습니다(AGENT_LOOPBACK=0). 이 기기의 에이전트는 토큰 파일을 "
            "붙이세요: %s" % (UNAUTHENTICATED, token_file_curl(shown)))
    if not exists:
        name = token_file.stem if token_file is not None and token_file.suffix == ".token" else "<인스턴스>"
        text += " 파일이 없으면 소유자가 `limn token create %s --save` 로 만듭니다." % name
    return text


def existing_token_file_shown(f: Path | None) -> str | None:
    """The shell path of token file f when it exists, else None - the edge half of token_guidance_line(): one stat
    per render, never a read of the file."""
    return shell_path(f, home_or_none()) if file_present(f) else None


def file_present(p: Path | None) -> bool:
    """Whether p exists - False too when that cannot be told: Path.exists() raises PermissionError in a folder this
    process may not search, and a token-file hint must never fail a pin write or turn a 401 into a 500."""
    if p is None:
        return False
    try:
        return p.exists()
    except OSError:
        return False


def home_or_none() -> Path | None:
    """This account's home folder, or None when neither $HOME nor the password database names one."""
    try:
        return Path.home()
    except (RuntimeError, KeyError):
        return None


REPLY_GUIDANCE = ("답글(0.2.2): 사람 신원으로 단 답글은 검토 대기·완료 핀을 다시 연다(답글이 다시 연 이유가 된다) — "
                  "토큰 없이 사람 신원을 달고 가는 에이전트(테일넷 주소로 닫을 때 `\"review\":true` 를 넣는 경우, `--auth local` 의 "
                  "헤더 없는 curl)는 답글 본문에 `\"reopen\":false` 를 넣는다 · 토큰을 쓰는 에이전트의 답글은 상태를 바꾸지 않는다")


def claim_guidance(base: str) -> str:
    """v0.2.1: the line after the close instruction - how to claim a pin (the legend only explained the marker)."""
    return ("처리를 시작하는 핀은 먼저 잡는다 — `curl -X POST -H 'Content-Type: application/json' -d '{\"eta_min\":15}' "
            "%s/api/pins/N/claim`(eta_min = 예상 분, 번호 칸에 '처리 중(이름, 약 N분)' 으로 보인다) · 고치기 직전에 그 핀 하나만 "
            "잡는다 · 409 면 다른 쪽이 잡은 핀이니 건너뛴다 · 포기하면 `%s/api/pins/N/unclaim`" % (base, base))
THREAD_MD_SHOW = 3                 # number of current-round thread posts shown in pins.md's note column (from the end)
THREAD_MD_CHARS = 200              # character count for one of those posts - the full text is via GET /api/pins/N


def _flat(s, n: int) -> str:
    """Collapses whitespace/newlines to a single space and truncates at n characters (with an ellipsis if cut)."""
    return truncate_quote(" ".join(str(s or "").split()), n)


def thread_md(r: dict) -> str:
    """The current round's thread (after the last close), appended after pins.md's note column: "[스레드 2건] 서준: ... ⏎ 다시 연 이유(서준): ...".
    Included so an agent never misses a follow-up question or reopen reason. If long, only the last THREAD_MD_SHOW entries are shown; the rest via GET /api/pins/N."""
    msgs = [m for m in thread_round(r) if m.get("ev") != "close" and (m.get("text") or not m.get("ev"))]
    if not msgs:
        return ""
    shown = msgs[-THREAD_MD_SHOW:]
    parts = []
    for m in shown:
        name = (m.get("by") or {}).get("name") or (m.get("by") or {}).get("login") or "?"
        label = "다시 연 이유(%s)" % name if m.get("ev") == "reopen" else "담당 바꿈(%s)" % name if m.get("ev") == "assign" else name
        parts.append("%s: %s" % (label, _flat(m.get("text"), THREAD_MD_CHARS)))
    more = len(msgs) - len(shown)
    head = "[스레드 %d건%s]" % (len(msgs), ", 앞 %d건은 GET /api/pins/%s" % (more, r.get("id")) if more else "")
    return head + " " + " ⏎ ".join(parts)


def review_md(rows: list, sectioned: bool) -> list:
    """The "awaiting review" subsection at the bottom of pins.md - pins closed by an agent that a person hasn't confirmed yet. A
    different 4-column table from the open table, so it's never misread as open pins. The expected confirmer is the author (anyone
    can confirm, but the viewer suggests the author). No subsection at all if empty."""
    if not rows:
        return []
    out = ["", "## 검토 대기 %d건 — 사람이 확인할 차례. 에이전트는 다시 처리하지 않는다(다시 열리면 위 열린 표로 돌아온다)" % len(rows),
           "", "| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |", "|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x["id"]):
        syms = ["%s" % r.get("id")] + (["질문"] if r.get("kind_req") == "question" else [])
        loc = location_col(r)
        if sectioned:
            loc = "`%s` · %s" % (md_cell(pin_doc_key(r)), loc)
        who_ = (r.get("author") or {}).get("name") or (r.get("author") or {}).get("login") or "작성자 기록 없음"
        ans = _flat(r.get("close_reply"), THREAD_MD_CHARS) or "(설명 없이 닫힘)"
        if r.get("close_ref"):
            ans += " (%s)" % _flat(r["close_ref"], 80)
        out.append("| %s | %s | %s | %s |" % (md_cell(" · ".join(syms)), loc, md_cell(who_), md_cell(ans)))
    return out


def pins_md_text(rows: list, base: str | None = None) -> str:
    """The summary an agent reads in one pass. Snippets are deliberately omitted -
    given just a line range, an agent reading the source directly is always cheaper and more accurate.
    Only %s is used as a format specifier - so a single malformed record never kills the whole summary.
    Closed pins are never listed (only counted in the header line) - so pins.md's size doesn't grow as they pile up.

    base (§P0c-B): the base URL the guidance line's close example uses. If omitted (the default path written
    to disk), it's loopback, as now. GET /pins.md passes the value rewritten to the request Host - only when
    it's a remote base does a "원격: curl ..." line get appended to the guidance paragraph (omitted for
    loopback, since that means the file is already being read locally).

    Multiple documents (§Multiple documents): kept as a single sheet, grouped into per-document subsections
    (## name - key - path). With a single document and no open pins under any other document key, it keeps the old shape with no subsections."""
    loopback_base = "http://127.0.0.1:%d" % C.port
    is_remote = base is not None and base != loopback_base
    base = base or loopback_base
    openn = [r for r in rows if not r.get("done")]
    reviewn = [r for r in rows if pin_state(r) == "review"]
    n_done = len(rows) - len(openn) - len(reviewn)
    rel = overlaps_by_id(rows)
    by_id = {r["id"]: r for r in rows}

    # §P0c-G: @name is prefixed to the note only when there are 2+ authors (by login; legacy pins with no author count as one group).
    author_groups = set()
    for r in openn:
        a = r.get("author")
        author_groups.add(a.get("login") if a and a.get("login") else None)
    multi_author = len(author_groups) > 1

    rows_by_doc: dict = {}
    any_symbol = False
    people = known_people(rows)
    n_human = 0
    for r in openn:
        syms = []
        # Number-column priority (reopened > -> @ > question): the most urgent signal to re-check goes leftmost.
        if pin_reopened_in_round(r):
            syms.append("다시 열림")
        to = addressed_to(r)
        if to:                                    # a pin handed to a person (assignee = a person, or a legacy pin's question @-tag) - an agent skips it
            n_human += 1
            syms.append("→ " + ", ".join("@%s" % ((people.get(lg) or {}).get("name") or lg) for lg in to))
        fyi = fyi_mentions_to(r)
        if fyi:                                    # FYI @-tags - notification only, never skipped
            syms.append("참고 " + ", ".join("@%s" % ((people.get(lg) or {}).get("name") or lg) for lg in fyi))
        if r.get("kind_req") == "question":
            syms.append("질문")
        badge = rel_badge(rel.get(r["id"], []), by_id, r)
        if badge:
            syms.append(badge)
        if claim_active(r):
            syms.append(claim_md(r))
        if r.get("edited_at"):
            syms.append("수정됨")
        if r.get("stale"):
            syms.append("위치 잃음")
        if syms:
            any_symbol = True
        idcol = md_cell(" · ".join(["%s" % r.get("id")] + syms))
        note = md_cell(r.get("note") or "", newline=" ⏎ ")
        th = thread_md(r)
        if th:
            note = (note + " ⏎ " if note else "") + md_cell(th)
        if multi_author:
            an = (r.get("author") or {}).get("name")
            if an:                                 # '[name]' rather than '@name' - so it's never misread as an @-tag (observed)
                note = "[%s] " % md_cell(an) + note
        q = render_quote(r)
        if q:
            any_symbol = True
            note = q + note
        rows_by_doc.setdefault(pin_doc_key(r), []).append(
            "| %s | %s | %s | %s | %s |" % (idcol, md_cell(r.get("page", 0)), location_col(r), range_label(r), note))

    known = [d.key for d in DOCS]
    sectioned = multi_doc() or any(k not in known[:1] for k in rows_by_doc)
    n_region = sum(1 for r in openn if is_region_pin(r))

    out = ["# 수정 요청 핀", "", "원고: `%s`" % C.src,
           "논문: %s · 저장소: %s" % (C.label, C.repo or "(없음)")]
    if not sectioned:
        head_short, built_at = build.read_head(DOCS[0]), build.read_built_at(DOCS[0])   # the one document
        if head_short and head_short != "-" and built_at:           # §P0c-D: omitted entirely if absent
            out.append("기준: %s · 빌드 %s" % (head_short, built_at))
            out.append("다른 체크아웃에서 처리하면 먼저 `git rev-parse --short HEAD` 가 같은지 확인")
    else:
        parts = []
        for d in DOCS:
            parts.append("%s(`%s`%s) %d건" % (md_cell(d.name), d.key, ", 보기 전용" if d.is_pdf else "",
                                              len(rows_by_doc.get(d.key, []))))
        for k in rows_by_doc:
            if k not in known:
                parts.append("설정에 없는 문서(`%s`) %d건" % (md_cell(k), len(rows_by_doc[k])))
        out.append("문서: " + " · ".join(parts))
        out.append("핀은 아래 문서별 소절(`## 이름 · 키 · 경로`)로 묶였다 — 위치 칸의 경로는 `--manuscript` 기준. "
                   "소절의 `기준:` 커밋이 다른 체크아웃에서 처리하면 먼저 `git rev-parse --short HEAD` 가 같은지 확인")
    out.append("갱신: %s  ·  열린 핀 %d건  ·  %s닫힌 핀 %d건(뷰어의 '닫힌 핀'에서 확인)" %
               (datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"), len(openn),
                "검토 대기 %d건(맨 아래, 처리하지 않는다)  ·  " % len(reviewn) if reviewn else "", n_done))
    out.append("")
    guidance = ("처리한 핀은 닫는다 — 닫을 때 `changes` 에 이 핀 때문에 바꾼 줄 범위를, `ref` 에 `PR #번호 (커밋 해시)` 를 적는다: "
                "`curl -X POST -H 'Content-Type: application/json' "
                "-d '{\"reply\":\"무엇을 고쳤는지(≤500자)\",\"ref\":\"PR #12 (커밋 해시)\","
                "\"changes\":[{\"file\":\"main.tex\",\"lo\":12,\"hi\":14}]}' "
                "%s/api/pins/N/close`(본문 생략 가능, 그러면 옛 방식처럼 사유 없이 닫힘. `changes` 의 줄 번호는 `ref` 의 "
                "커밋이 만든 판 기준 — 스쿼시 머지 뒤 닫으면 머지된 main 기준, 경로는 위치 칸 기준. "
                "핀마다 커밋을 나누면 더 좋지만 필수는 아니다) · "
                "줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다 · "
                "'질문' 핀은 원고를 고치지 말고(질문이 수정을 뜻할 때만 고친다) `curl -X POST -H 'Content-Type: application/json' "
                "-d '{\"text\":\"답(≤1000자)\"}' %s/api/pins/N/reply` 로 답한 뒤 닫는다 · "
                "에이전트가 닫은 핀은 완료가 아니라 검토 대기로 간다(사람이 뷰어에서 [확인]) — 테일넷 주소로 닫는 에이전트는 "
                "요청이 사람 신원을 달고 가므로 본문에 `\"review\":true` 를 넣는다 · 검토 대기 핀은 다시 처리하지 않는다 · "
                "에이전트는 확인(confirm)하지 않는다 — `/api/pins/N/confirm` 은 사람 신원(테일넷 헤더)이 없으면 403" % (base, base))
    if n_human:
        guidance += (" · 번호 칸에 `→ @이름` 이 붙은 핀 %d건은 담당이 사람인 핀이다 — 요청한 사용자가 그 핀을 "
                     "명시적으로 시키지 않으면 건너뛴다(`참고 @이름`은 알림만 간 참고용 태그라 건너뛰지 않는다)" % n_human)
    if is_remote:
        guidance += " · 원격: `curl -s %s/pins.md`" % base
    if C.repo:
        guidance += (" · 처리 전 자기 체크아웃의 `git remote get-url origin` 이 위 저장소와 같은지 확인. "
                      "다르면 다른 논문의 핀이니 멈춘다")
    if n_region:
        guidance += (" · 보기 전용 PDF 의 핀은 줄 번호가 없다 — 쪽·영역 글자(«…»)·메모로 무엇을 가리키는지 판단하고, "
                     "고칠 곳은 LaTeX 문서에서 찾는다(못 찾으면 닫지 말고 보고)")
    out.append(guidance)
    out.append(claim_guidance(base))
    out.append(token_guidance_line(None if is_remote else existing_token_file_shown(C.agent_token_file)))
    out.append(REPLY_GUIDANCE)                    # v0.2.2: one more additive line
    if any_symbol:
        out.append(LEGEND)
    header = ["| # | 쪽 | 위치 | 범위 | 메모 |", "|---|---|---|---|---|"]
    if not sectioned:
        rows_render = rows_by_doc.get(known[0], [])
        out += [""] + header
        out += rows_render if rows_render else ["| — | — | 열린 핀 없음 | | |"]
        return "\n".join(out + review_md(reviewn, sectioned)) + "\n"
    shown = 0
    for d in DOCS:
        rs = rows_by_doc.get(d.key)
        if not rs:
            continue
        shown += 1
        title = "## %s · `%s` · `%s`" % (md_cell(d.name), d.key, md_cell(d.rel_path()))
        if d.is_pdf:
            title += " — 보기 전용 PDF(줄 번호 없음)"
        out += ["", title]
        head_short, built_at = build.read_head(d), build.read_built_at(d)
        if head_short and head_short != "-" and built_at:
            out.append("기준: %s · %s %s" % (head_short, "그림" if d.is_pdf else "빌드", built_at))
        out += [""] + header + rs
    for k, rs in rows_by_doc.items():
        if k in known:
            continue
        shown += 1
        out += ["", "## 설정에 없는 문서 · `%s` — 이 뷰어의 --doc 목록에 없다. 처리 전에 사용자에게 확인" % md_cell(k),
                ""] + header + rs
    if not shown:
        out += ["", "열린 핀 없음"]
    return "\n".join(out + review_md(reviewn, sectioned)) + "\n"


# ---------------------------------------------------------------- Selection resolution
#
# Resolving a drag to source lines, the snippet and the overlaps of a range are limn/locate.py's; they take the
# document and the instance's settings as arguments. These are the App members the handler calls (web/app.py),
# bound to this instance's run settings, token-weight cache and pins.

TOKEN_CACHE = locate.TokenCache()             # the process's word-frequency cache for the last file weighed


def pick_context() -> locate.PickContext:
    """What resolving a selection needs from this instance: the manuscript root, --float-envs, the state folder, the
    process's token-weight cache and the overlaps of a range with the stored pins."""
    return locate.PickContext(C.src, C.envs, C.state, TOKEN_CACHE, overlaps_for_range)


def pick(D: Doc, request: locate.Selection) -> dict:
    """POST /api/pick: a selection of document D (parsed by limn.web.parse.parse_pick) -> source lines (limn.locate.pick)."""
    return locate.pick(D, request, pick_context())


def snippet_api(rng: locate.SourceLines, levels: bool) -> dict:
    """GET /api/snippet: a parsed range's lines, with levels the range ladder under --float-envs (limn.locate.snippet_api)."""
    return locate.snippet_api(rng, levels, C.envs)


def overlaps_api(rng: locate.SourceLines) -> dict:
    """GET /api/overlaps — asks about a not-yet-saved selection's overlap using only file/range (kept for agent/legacy-viewer compatibility).

    The current viewer instead recomputes the same rule (overlapsFor) locally against its own PINS on every
    range change, with no round trip - because pressing [Save Pin] while a response is still in flight could
    otherwise save a duplicate with no banner shown. This path was called by the 83b91a5 viewer. rng is the range
    parsed by limn.web.parse.parse_source_range."""
    return {"overlaps": overlaps_for_range(str(rng.file), rng.lo, rng.hi)}


# ---------------------------------------------------------------- Identity (tailscale serve headers)

def hdr_text(v) -> str:
    """tailscale carries non-ASCII values as RFC 2047 (=?utf-8?q?...?=). If raw UTF-8 arrives instead, undoes a latin-1 mis-decode."""
    if not v:
        return ""
    v = str(v).strip()
    if "=?" in v:
        try:
            v = str(make_header(decode_header(v)))
        except Exception:                                # noqa: BLE001 — a single bad header must never drop the request
            pass
    else:
        try:
            v = v.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return "".join(ch for ch in v if ch.isprintable())[:300]


def actor_of(headers) -> tuple:
    """(actor, whether it came from a header) from the Tailscale-User-* headers. identify() only calls this for a
    loopback peer under --auth tailscale - tailscale serve connects from loopback; any other peer's headers are ignored."""
    login = hdr_text(headers.get("Tailscale-User-Login"))
    if not login:
        return dict(LOCAL_ACTOR), False
    a = {"login": login[:200], "name": (hdr_text(headers.get("Tailscale-User-Name")) or login.split("@")[0])[:100]}
    pic = hdr_text(headers.get("Tailscale-User-Profile-Pic"))
    if pic.startswith("https://") and len(pic) <= 1000:
        a["pic"] = pic
    return a, True


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def split_host(v: str) -> tuple:
    """'name:port' / '[::1]:port' -> (lowercase name, port or None). ('', None) if malformed."""
    v = (v or "").strip().lower()
    if v.startswith("["):
        name, _, rest = v[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    else:
        name, _, port = v.partition(":")
    if port and not re.fullmatch(r"[0-9]{1,5}", port):
        return "", None
    return name.rstrip("."), (int(port) if port else None)


def host_ok(host: str) -> bool:
    """For a loopback name, the port is never checked - forwarding via SSH -L to a different local port can
    make Host something like 'localhost:9000', different from the actual server port. A DNS-rebinding
    attack's Host is never a loopback name (an external domain resolving to 127.0.0.1 doesn't turn the Host
    header itself into 'localhost'), so leaving the port out here doesn't weaken that defense. Cross-origin
    (CSRF) defense is origin_ok's job."""
    name, _ = split_host(host)
    if name in LOOPBACK:
        return True
    return name.endswith(".ts.net") or public_host(name) is not None


def public_host(name: str):
    """The (name, port) entry of --public-host matching this Host/Origin name, or None."""
    return next((h for h in C.public_hosts if h[0] == name), None) if name else None


def parse_public_hosts(values) -> tuple:
    """--public-host values (repeatable, each a comma list of NAME or NAME:PORT) -> ((name, port or None), ...). Raises ValueError."""
    out = []
    for v in values or []:
        for item in str(v).split(","):
            item = item.strip()
            if not item:
                continue
            name, port = split_host(item)
            if not name or not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*", name) \
                    or name in LOOPBACK or (port is not None and not 1 <= port <= 65535):
                raise ValueError("--public-host takes a DNS name with an optional :port, got %r" % item)
            if all(h[0] != name for h in out):
                out.append((name, port))
    return tuple(out)


DEFAULT_PORT = {"http": 80, "https": 443}


def origin_ok(origin: str, host) -> bool:
    """Is Origin on the same side as the Host this request arrived on? The rule branches on the kind of Host.

    - Host is loopback: Origin must also be loopback. The port is never checked - forwarding via SSH -L
      makes the browser's Origin/Host port differ from the server's bind port (observed: an 18110->18106
      POST got a 403). There is no legitimate path for a *.ts.net Origin to arrive with a loopback Host
      (tailscale serve preserves Host, confirmed in SKILL.md) - accepting one would let another tailnet's
      public Funnel page CSRF the local user's browser (observed: 200).
    - Host is *.ts.net: Origin must match that host's name and port (a missing port falls back to the scheme default).
    - Host is a --public-host name: Origin must be https://<that name> on the configured port (443 if none was given).
    A request with no Origin (curl/agent/same-origin GET) never reaches this function."""
    u = urlparse(origin.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return False                                   # includes a 'null' origin (sandboxed iframe/file://)
    try:
        oport = u.port
    except ValueError:
        return False
    name = u.hostname.lower().rstrip(".")
    hname, hport = split_host(host or "")
    if not hname or hname in LOOPBACK:                 # no Host at all (HTTP/1.0) is treated as loopback - the stricter side
        return name in LOOPBACK
    if hname.endswith(".ts.net"):
        dflt = DEFAULT_PORT[u.scheme]
        return name == hname and (oport or dflt) == (hport or dflt)
    ph = public_host(hname)
    if ph is not None:
        return u.scheme == "https" and name == ph[0] and (oport or 443) == (ph[1] or 443)
    return False


def remote_base_for(host_raw: str) -> str:
    """The base URL used in GET /pins.md's guidance line (§P0c-B). If Host is *.ts.net, 'https://<Host as-is,
    including port>'; if it's a --public-host name, 'https://<name>[:<configured port>]'; otherwise (loopback/no
    Host) the loopback URL as before. Since _check_origin() has already validated Host by this point, only the
    kind needs to be distinguished here."""
    name, _ = split_host(host_raw or "")
    if name.endswith(".ts.net"):
        return "https://%s" % host_raw.strip()
    ph = public_host(name)
    if ph is not None:
        return "https://%s%s" % (ph[0], ":%d" % ph[1] if ph[1] and ph[1] != 443 else "")
    return "http://127.0.0.1:%d" % C.port


# ---------------------------------------------------------------- Access control (docs/adr/0002-access-control.md, v0.2)
#
# Who is this request (identify: one identity provider per instance, plus agent API tokens that every provider
# accepts), may it use this instance at all (admit: --allow / --members-only), and may it change things
# (check_role: viewer / agent / editor / owner from people.json). The handler runs all three before dispatching.
# tokens.json and people.json are re-read when they change on disk (stat key), so `limn token` / `limn member`
# edits take effect on the next request, without a restart.

AUTH_PROVIDERS = ("tailscale", "local", "trusted-proxy")
ROLES = ("owner", "editor", "viewer", "agent")
DEFAULT_ROLE = "editor"                      # a person without a role field - every v0.1 person
VIEWER_POSTS = ("/api/pick", "/api/revision-build")   # computations a viewer may still run (no state change)
TOKEN_PREFIX = "limn_"
TOKEN_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
HEADER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
LOGIN_MAX = 200
NAME_MAX = 100
LOOPBACK_AGENT_DEPRECATION = ("a request from loopback without an identity header or token is treated as the agent - "
                              "this is deprecated and will be removed; give agents a token (limn token create <instance>) "
                              "and turn it off with --no-agent-loopback (AGENT_LOOPBACK=0)")
TAILNET_HEADERLESS = ("신원 헤더 없는 원격 요청입니다(테일넷의 태그 장치 등) — 에이전트는 `Authorization: Bearer <토큰>` 을 "
                      "보내세요(`limn token create <인스턴스>`).")
OWNER_POSTS = ("/api/clear",)               # bulk-destructive: only the owner (a person), and only with a confirmation
OWNER_POST_RE = re.compile(r"/api/pins/\d+/purge")   # permanent delete from the Trash (v0.2.2): only the owner
UNAUTHENTICATED = "신원을 확인할 수 없습니다 — 에이전트는 `Authorization: Bearer <토큰>` 을 보내세요(`limn token create <인스턴스>`)."


class Principal(NamedTuple):
    actor: dict              # {login, name, pic?} - what pins record
    role: str                # owner | editor | viewer | agent
    via: str                 # header | token | loopback-agent | local-owner


def _stat_key(p: Path):
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return "unreadable"
    return (st.st_ino, st.st_mtime_ns, st.st_size)


# -------- agent API tokens (<state>/tokens.json, hashed at rest)

def token_hash(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _valid_tokens(d) -> list:
    rows = d.get("tokens") if isinstance(d, dict) else None
    return [t for t in rows or [] if isinstance(t, dict)
            and all(isinstance(t.get(k), str) and t[k] for k in ("id", "name", "hash"))]


def load_tokens(state: Path, strict: bool = False) -> list:
    """The token entries of <state>/tokens.json ([] if absent). strict=True (the CLI, before rewriting the file)
    raises ValueError on an unreadable or malformed file instead of treating it as empty."""
    p = Path(state) / "tokens.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        if strict:
            raise ValueError("cannot read %s: %s" % (p, e)) from e
        print("warning: cannot read %s (%s) - no agent token is accepted until it is fixed" % (p, e), file=sys.stderr)
        return []
    if strict and not (isinstance(d, dict) and isinstance(d.get("tokens"), list)):
        raise ValueError("%s is not a Limn token file" % p)
    return _valid_tokens(d)


def _write_tokens(state: Path, rows: list) -> None:
    atomic_write(Path(state) / "tokens.json",
                 json.dumps({"version": 1, "tokens": rows}, ensure_ascii=False, indent=1) + "\n", mode=0o600)


def token_create(state: Path, name: str | None = None) -> tuple:
    """Creates a token -> (entry, plaintext). Only the hash is stored; the plaintext is returned once and never again.
    Appends a `token_created` audit line {id, name} as the OS account (os_actor, via "cli") - never the token or its
    hash. Raises ValueError for a bad or taken name, or an unreadable tokens.json (nothing is written then)."""
    state = Path(state)
    if name is not None and not TOKEN_NAME_RE.fullmatch(name):
        raise ValueError("token name must match [A-Za-z0-9][A-Za-z0-9._-]{0,39}: %r" % name)
    state.mkdir(parents=True, exist_ok=True)
    with store_lock(state, "tokens"):
        rows = load_tokens(state, strict=True)
        names = {t["name"] for t in rows}
        if name is None:
            name, n = "agent", 1
            while name in names:
                n += 1
                name = "agent-%d" % n
        elif name in names:
            raise ValueError("a token named %r already exists (revoke it first, or pick another --name)" % name)
        ids = {t["id"] for t in rows}
        tid = secrets.token_hex(4)
        while tid in ids:
            tid = secrets.token_hex(4)
        plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
        entry = {"id": tid, "name": name, "hash": token_hash(plain), "created": now_str()}
        _write_tokens(state, rows + [entry])
        append_audit(state, audit_entry("token_created", os_actor(), "cli", {"id": tid, "name": name}, time.time()))
    return entry, plain


def token_revoke(state: Path, ref: str) -> dict | None:
    """Removes the token whose id or name is ref -> the removed entry, or None if there is none. A removal appends a
    `token_revoked` audit line {id, name} as the OS account (via "cli"); None writes nothing."""
    state = Path(state)
    if not (state / "tokens.json").exists():
        return None
    with store_lock(state, "tokens"):
        rows = load_tokens(state, strict=True)
        hit = [t for t in rows if t["id"] == ref] or [t for t in rows if t["name"] == ref]
        if not hit:
            return None
        _write_tokens(state, [t for t in rows if t is not hit[0]])
        append_audit(state, audit_entry("token_revoked", os_actor(), "cli", {"id": hit[0]["id"], "name": hit[0]["name"]},
                                        time.time()))
    return hit[0]


_TOKENS_CACHE = {"key": None, "rows": []}
_TOKENS_CACHE_LOCK = threading.Lock()


def current_tokens() -> list:
    """tokens.json as the server sees it now - re-read whenever its inode/mtime/size changes (revocation needs no restart)."""
    p = C.tokens_file
    key = (str(p), _stat_key(p))
    with _TOKENS_CACHE_LOCK:
        if _TOKENS_CACHE["key"] != key:
            _TOKENS_CACHE["rows"] = load_tokens(C.state) if key[1] is not None else []
            _TOKENS_CACHE["key"] = key
        return _TOKENS_CACHE["rows"]


def token_lookup(token: str):
    """The token entry whose hash matches, or None. Compares every entry in constant time (hmac.compare_digest)."""
    h = token_hash(token)
    hit = None
    for t in current_tokens():
        if hmac.compare_digest(t["hash"].encode("utf-8"), h.encode("utf-8")):
            hit = t
    return hit


def bearer_of(headers):
    """The token of an `Authorization: Bearer <token>` header, None when there is no Bearer header. Other schemes
    are not Limn's and are ignored. An empty or repeated Bearer header is a 401 - it is never read as "no token"."""
    vals = headers.get_all("Authorization") or []
    bearer = [v for v in vals if v.strip().split(" ", 1)[0].lower() == "bearer"]
    if not bearer:
        return None
    parts = bearer[0].strip().split(None, 1)
    if len(bearer) > 1 or len(parts) != 2 or not parts[1].strip():
        raise HTTPError(401, "Authorization: Bearer 헤더가 올바르지 않습니다.", reason="bad_bearer")
    return parts[1].strip()


# -------- people.json roles and members

_ROLES_CACHE = {"key": None, "roles": {}}
_ROLES_CACHE_LOCK = threading.Lock()


def role_value(v) -> str:
    """A people.json role field -> the role. Missing = editor (every v0.1 person); an unknown value = viewer (fail closed)."""
    if v is None:
        return DEFAULT_ROLE
    return v if v in ROLES else "viewer"


def people_roles() -> dict:
    """{login: role} for everyone in people.json, re-read whenever the file changes - so `limn member role` and
    `limn member remove` take effect on the running server's next request."""
    key = (str(C.people_file), _stat_key(C.people_file))
    with _ROLES_CACHE_LOCK:
        if _ROLES_CACHE["key"] != key:
            _ROLES_CACHE["roles"] = {x["login"]: role_value(x.get("role")) for x in load_people()} if key[1] else {}
            _ROLES_CACHE["key"] = key
        return _ROLES_CACHE["roles"]


def role_of(login: str) -> str:
    return people_roles().get(login, DEFAULT_ROLE)


def valid_login(login) -> bool:
    """A person's login: non-empty, printable, no whitespace anywhere (a tailnet login is an e-mail address or
    user@github; --local-user and LOCAL_USER already required this), not the agent's 'local' or 'agent:...'. The same rule
    for identity headers, --local-user and `limn member add` (v0.2.1: 'bad login' used to be accepted by the CLI)."""
    return (isinstance(login, str) and 0 < len(login) <= LOGIN_MAX and login.isprintable()
            and not any(c.isspace() for c in login)
            and login != LOCAL_ACTOR["login"] and not login.startswith(AGENT_LOGIN_PREFIX))


def load_people_file(state: Path) -> list:
    """people.json for the CLI: [] if absent, ValueError if it exists but cannot be read (never overwrite what we could not read)."""
    p = Path(state) / "people.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise ValueError("cannot read %s: %s" % (p, e)) from e
    if not isinstance(d, dict) or not isinstance(d.get("people"), list):
        raise ValueError("%s is not a Limn people file" % p)
    return _valid_people(d)


def _people_update(state: Path, fn: Callable[[list], tuple]):
    """Read-modify-write of <state>/people.json under the same cross-process lock the server uses.

    fn(rows) edits rows in place and returns (result, audit) where audit is (action, details) for a membership change
    or None. After people.json is written, the change is appended to audit.jsonl as the OS account (via "cli") while
    the lock is still held, so audit lines follow the order of the changes. Returns result; ValueError from fn
    propagates before anything is written."""
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    with store_lock(state, "people"):
        rows = load_people_file(state)
        out, audit = fn(rows)
        atomic_write(state / "people.json", people_text(rows), mode=0o600)
        if audit is not None:
            append_audit(state, audit_entry(audit[0], os_actor(), "cli", audit[1], time.time()))
    return out


def member_add(state: Path, login: str, role: str = DEFAULT_ROLE, name: str | None = None) -> dict:
    """Adds login to people.json with role (name defaults to the part of the login before @) -> the new entry, and
    audits `member_added` {login, role}. Raises ValueError for an invalid login or role, or an existing member."""
    if not valid_login(login):
        raise ValueError("invalid login %r (non-empty, no spaces, at most %d characters, not 'local' or 'agent:...')"
                         % (login, LOGIN_MAX))
    if role not in ROLES:
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
    name = " ".join((name or login.split("@")[0]).split())[:NAME_MAX] or login

    def fn(rows):
        """The _people_update step: appends the entry -> (entry, member_added audit); ValueError if already a member."""
        if any(x["login"] == login for x in rows):
            raise ValueError("%s is already a member - change the role with `limn member role`" % login)
        entry = {"login": login, "name": name, "role": role}
        rows.append(entry)
        return entry, ("member_added", {"login": login, "role": role})
    return _people_update(state, fn)


def member_remove(state: Path, login: str) -> dict | None:
    """Removes login from people.json -> the removed entry, or None if it was not a member (or there is no file).
    A removal audits `member_removed` {login, previous_role}."""
    if not (Path(state) / "people.json").exists():
        return None

    def fn(rows):
        """The _people_update step: drops the entry -> (entry, member_removed audit), or (None, None) if absent."""
        hit = next((x for x in rows if x["login"] == login), None)
        if hit is None:
            return None, None
        rows.remove(hit)
        return hit, ("member_removed", {"login": login, "previous_role": role_value(hit.get("role"))})
    return _people_update(state, fn)


def member_set_role(state: Path, login: str, role: str) -> dict | None:
    """Sets login's role in people.json -> the updated entry, or None if it is not a member (or there is no file).
    A change of the effective role audits `member_role` {login, role, previous_role}; setting the role it already has
    writes the field but no audit line. Raises ValueError for an unknown role."""
    if role not in ROLES:
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
    if not (Path(state) / "people.json").exists():
        return None

    def fn(rows):
        """The _people_update step: sets the role -> (entry, member_role audit or None when the role is unchanged),
        or (None, None) if absent."""
        hit = next((x for x in rows if x["login"] == login), None)
        if hit is None:
            return None, None
        before = role_value(hit.get("role"))
        hit["role"] = role
        if before == role:
            return hit, None
        return hit, ("member_role", {"login": login, "role": role, "previous_role": before})
    return _people_update(state, fn)


# -------- identity providers

def _peer_ip(addr):
    try:
        ip = ipaddress.ip_address(str(addr).split("%", 1)[0])
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip


def peer_is_loopback(addr) -> bool:
    ip = _peer_ip(addr)
    return bool(ip is not None and ip.is_loopback)


def peer_is_trusted_proxy(addr) -> bool:
    ip = _peer_ip(addr)
    return ip is not None and any(ip in n for n in C.trusted_proxies)


def parse_networks(spec: str) -> tuple:
    """'127.0.0.1,::1,10.0.0.0/8' -> ip_network tuple. Raises ValueError."""
    out = []
    for item in (spec or "").split(","):
        item = item.strip()
        if item:
            try:
                out.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                raise ValueError("--trusted-proxies takes IP addresses or CIDR ranges, got %r" % item) from None
    if not out:
        raise ValueError("--trusted-proxies is empty")
    return tuple(out)


def is_loopback_bind(addr: str) -> bool:
    """Is a --bind address loopback? Raises ValueError for anything but an IP address or 'localhost'."""
    if addr == "localhost":
        return True
    return ipaddress.ip_address(addr).is_loopback


def local_owner_actor() -> dict:
    login = C.local_user or os.environ.get("USER") or "owner"
    return {"login": login, "name": login}


def proxy_actor(headers):
    """The person an authenticating proxy vouches for, or None without the user header. With --proxy-email-header
    the e-mail (when present) is the login, so people.json / --allow can list e-mail addresses."""
    user = hdr_text(headers.get(C.proxy_user_header))
    if not user:
        return None
    email = hdr_text(headers.get(C.proxy_email_header)) if C.proxy_email_header else ""
    login = (email or user)[:LOGIN_MAX]
    name = (hdr_text(headers.get(C.proxy_name_header)) or user.split("@")[0])[:NAME_MAX]
    return {"login": login, "name": name}


_LOOPBACK_WARN_LOCK = threading.Lock()
_LOOPBACK_WARNED = [False]


def warn_loopback_agent_once() -> None:
    """The deprecation warning on the first headerless loopback agent request (and never again - no per-request log)."""
    with _LOOPBACK_WARN_LOCK:
        if _LOOPBACK_WARNED[0]:
            return
        _LOOPBACK_WARNED[0] = True
    print("warning: " + LOOPBACK_AGENT_DEPRECATION, file=sys.stderr)
    sys.stderr.flush()


def identify(headers, peer) -> Principal:
    """Who is this request? A valid `Authorization: Bearer` token wins under every provider; an invalid or revoked
    one is a 401 and never falls back to another identity. Otherwise the provider decides (C.auth):

    - tailscale: Tailscale-User-* headers, trusted only from a loopback peer (tailscale serve). A loopback request
      without them is the agent (LOCAL_ACTOR) while C.agent_loopback is on - the v0.1 behaviour, deprecated.
    - local: a loopback request is the owner (a person). Tailscale headers are ignored.
    - trusted-proxy: the configured user header, trusted only from a --trusted-proxies peer.
    Anything else is a 401."""
    tok = bearer_of(headers)
    if tok is not None:
        t = token_lookup(tok)
        if t is None:
            raise HTTPError(401, "토큰이 올바르지 않거나 폐기되었습니다.", reason="bad_token")
        return Principal({"login": AGENT_LOGIN_PREFIX + t["name"], "name": t["name"]}, "agent", "token")
    loop = peer_is_loopback(peer)
    if C.auth == "local":
        if loop and came_through_proxy(headers):
            # every local request is the owner - one that came through a proxy is someone else (v0.2.1 hardening)
            raise HTTPError(403, TAILNET_HEADERLESS, page=("no-identity", {}), reason="headerless")
        if loop:
            return Principal(local_owner_actor(), "owner", "local-owner")
        raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")
    if C.auth == "trusted-proxy":
        a = proxy_actor(headers) if peer_is_trusted_proxy(peer) else None
        if a is None or not valid_login(a["login"]):
            raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")
        return Principal(a, role_of(a["login"]), "header")
    if loop:
        a, via = actor_of(headers)
        if via:
            if not valid_login(a["login"]):
                raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")
            return Principal(a, role_of(a["login"]), "header")
        if C.agent_loopback:
            if came_through_proxy(headers) and not C.tailnet_agent:
                # tailscale serve connects from loopback too. Without identity headers such a request is a tagged
                # device (or anything else behind the proxy) - never the local agent (v0.2.1).
                raise HTTPError(403, TAILNET_HEADERLESS, page=("no-identity", {}), reason="headerless")
            warn_loopback_agent_once()
            return Principal(dict(LOCAL_ACTOR), "agent", "loopback-agent")
        if not came_through_proxy(headers):
            # An agent on this machine with the loopback agent off (ADR-0007): say where its token file is.
            f = C.agent_token_file
            raise HTTPError(401, loopback_refused_text(f, file_present(f), home_or_none()), reason="loopback_agent_off")
    raise HTTPError(401, UNAUTHENTICATED, reason="unauthenticated")


# Headers a reverse proxy adds (tailscale serve sets X-Forwarded-For/-Host/-Proto). A local curl sends none of them.
FORWARDED_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Forwarded-Port", "X-Real-IP",
                     "Forwarded", "Via")


def host_is_loopback(host) -> bool:
    """Did the request name this machine (a loopback Host, or none at all as in HTTP/1.0)?"""
    name, _ = split_host(host or "")
    return not host or not str(host).strip() or name in LOOPBACK


def came_through_proxy(headers) -> bool:
    """Did this loopback request come through a reverse proxy such as tailscale serve? Host alone cannot tell:
    tailscale serve picks the route from the TLS server name and passes the client's Host through unchanged, so a
    tagged device can send 'Host: localhost'. It does set X-Forwarded-For/-Host/-Proto itself (overwriting what the
    client sent), so any forwarding header - or a non-loopback Host - marks a proxied request. A local agent's curl
    sends neither. Limit: a raw TCP forwarder that adds no header (tailscale serve --tcp/--tls-terminated-tcp,
    ssh -L/-R, a plain port forward) is indistinguishable from a local request - use tokens and --no-agent-loopback there."""
    if not host_is_loopback(headers.get("Host")):
        return True
    return any(headers.get(h) is not None for h in FORWARDED_HEADERS)


def admit(p: Principal, host, headers=None) -> None:
    """May this principal use the instance at all? Only people vouched for by a header are filtered: --members-only
    admits logins in people.json or --allow; otherwise --allow (if set) admits only its logins. Without either,
    everyone the provider identifies is admitted (and recorded in people.json as an editor on first visit).
    Tokens and the local owner are always admitted. A headerless request through the proxy (a tagged device) never
    gets here unless --tailnet-agent is on (identify refuses it), and even then it is refused when a list is
    configured, as in v0.1."""
    login = p.actor.get("login")
    if p.via == "header":
        if C.members_only:
            if login not in C.allow and login not in people_roles():
                raise HTTPError(403, "이 뷰어의 멤버가 아닙니다: %s — 소유자가 `limn member add` 로 추가해야 합니다." % login,
                                page=("not-member", {"login": login}), reason="not_member")
        elif C.allow and login not in C.allow:
            raise HTTPError(403, "이 뷰어에 허용되지 않은 계정입니다: %s" % login, page=("not-allowed", {"login": login}), reason="not_allowed")
    elif p.via == "loopback-agent" and (C.allow or C.members_only):
        hname, _ = split_host(host or "")
        if hname.endswith(".ts.net") or (headers is not None and came_through_proxy(headers)):
            raise HTTPError(403, "신원 헤더 없는 테일넷 요청입니다(태그 장치 등). --allow 목록의 계정으로 접속하세요.",
                            page=("no-identity", {}), reason="headerless")


def check_role(p: Principal, path: str) -> None:
    """Role rule for state-changing (POST) requests, applied once in the handler before dispatch. A viewer may only
    run computations (/api/pick, /api/revision-build); an agent may do everything but confirm; editor and owner may
    do everything a person could in v0.1, except the bulk-destructive OWNER_POSTS (/api/clear, v0.2.1) and the permanent
    delete from the Trash (OWNER_POST_RE, v0.2.2), which only the owner may call. Other owner-only operations - members, tokens, settings - are CLI/file level."""
    if p.role == "viewer" and path not in VIEWER_POSTS:
        raise HTTPError(403, "보기 권한(viewer)만 있는 계정입니다 — 핀·답글·닫기 같은 변경은 할 수 없습니다.", reason="viewer_only")
    if p.role == "agent" and re.fullmatch(r"/api/pins/\d+/confirm", path):
        raise HTTPError(403, CONFIRM_BY_HUMAN, reason="confirm_by_human")
    if path in OWNER_POSTS and p.role != "owner":
        raise HTTPError(403, "모든 핀을 지우는 일은 소유자(owner)만 합니다 — 에이전트·편집자는 핀을 하나씩 닫으세요.", reason="owner_only")
    if OWNER_POST_RE.fullmatch(path) and p.role != "owner":
        raise HTTPError(403, "휴지통에서 영구 삭제는 소유자(owner)만 합니다 — 삭제한 핀은 %d일 뒤 저절로 지워집니다." % TRASH_DAYS, reason="owner_only")


# ---------------------------------------------------------------- Viewer

VIEWER_DIR = Path(__file__).resolve().parent / "viewer"
VIEWER_MARKERS = ("__APP_CSS__", "__APP_JS__")
VIEWER_MANIFEST = "parts.txt"                                    # the ordered list of parts, beside index.html
VIEWER_PART_RE = re.compile(r"[a-z0-9-]+/[a-z0-9-]+\.[a-z]+")    # folder/name.ext: never leaves the viewer folder


def viewer_manifest(directory: Path) -> dict[str, tuple[str, ...]]:
    """The viewer's part files per marker, in page order, as listed in directory/parts.txt.

    The manifest is a marker line (__APP_CSS__, __APP_JS__) followed by the paths of its parts, relative to the
    folder; "#" starts a comment and blank lines are skipped. Every marker has a non-empty list, and a path appears
    once. Anything else is a packaging defect and raises ValueError (a missing manifest raises OSError).
    """
    parts: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in (directory / VIEWER_MANIFEST).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line in VIEWER_MARKERS and line not in parts:
            current = parts[line] = []
        elif current is not None and VIEWER_PART_RE.fullmatch(line):
            current.append(line)
        else:
            raise ValueError("viewer manifest %s: unexpected line %r" % (VIEWER_MANIFEST, raw))
    names = [n for ns in parts.values() for n in ns]
    if set(parts) != set(VIEWER_MARKERS) or not all(parts.values()) or len(names) != len(set(names)):
        raise ValueError("viewer manifest %s must list each of %s once, with parts, and no part twice"
                         % (VIEWER_MANIFEST, ", ".join(VIEWER_MARKERS)))
    return {m: tuple(parts[m]) for m in VIEWER_MARKERS}


def load_viewer_html(directory: Path) -> str:
    """The viewer page with its stylesheet and main script inlined, as one HTML string.

    index.html carries one __APP_CSS__ and one __APP_JS__ marker. The parts listed under each marker in parts.txt
    (viewer_manifest) are joined in that order, byte for byte, and put where the marker was - the CSS parts into the
    one <style>, the JS parts into the one <script>, so no build step or module loader is involved. Inlining keeps
    GET / a single response with no extra routes. A missing or malformed file is a packaging defect and raises at
    import (OSError / ValueError).
    """
    page = (directory / "index.html").read_text(encoding="utf-8")
    for marker, names in viewer_manifest(directory).items():
        text = "".join((directory / name).read_text(encoding="utf-8") for name in names)
        if page.count(marker) != 1 or any(m in text for m in VIEWER_MARKERS):
            raise ValueError("viewer template marker %s must appear exactly once in index.html" % marker)
        page = page.replace(marker, text)
    return page


HTML = load_viewer_html(VIEWER_DIR)
HTML = HTML.replace("__PDFJS_VERSION__", PDFJS_VERSION)
HTML = HTML.replace("__LIMN_MARK__", inline_svg())          # the mark by the label and in the help header (limn.mark)
HTML = HTML.replace("__LUCIDE_JSON__", json.dumps(LUCIDE, sort_keys=True))
HTML = HTML.replace("__UI_EN_JSON__", json.dumps(UI_EN, ensure_ascii=False, sort_keys=True).replace("</", "<\\/"))
HTML = ICON_TOKEN_RE.sub(lambda m: icon_svg(m.group(1)), HTML)


# ---------------------------------------------------------------- HTTP handler wiring (the handler is limn/web/handler.py)

class _ModuleApp:
    """This module's live globals as attributes: the limn.web.app.App the HTTP handler calls.

    Read at call time and never copied, so main() rebinding HTML and a test rebinding a service on its copy of this
    module (mock.patch.object(ps, "build_async")) both reach the handler. A view over globals() rather than the module
    object: server.py also runs where it is not in sys.modules (loaded by path, as the tests and tools do)."""
    __slots__ = ("_ns",)

    def __init__(self, ns: dict) -> None:
        """Wrap the namespace dict itself (this module's globals()), not a snapshot of it."""
        self._ns = ns

    def __getattr__(self, name: str):
        """The current value of global `name`; AttributeError when this module has none."""
        try:
            return self._ns[name]
        except KeyError:
            raise AttributeError(name) from None


class Handler(WebHandler):
    """The HTTP handler of this server: limn.web.handler.Handler bound to this module's services (_ModuleApp)."""
    app = _ModuleApp(globals())


# ---------------------------------------------------------------- Entry point

def parse_doc_arg(spec: str, ms: Path) -> dict:
    """Parses one --doc <key>=<display name>:<path>. The path is relative to --manuscript (recommended) or absolute.

    - `<key>=<name>:a/b/main.tex` - LaTeX. The build root is the folder holding that .tex (a/b).
    - `<key>=<name>:a::b/main.tex` - LaTeX. The build root is a (the scope copied into the build copy), and
      main is a/b/main.tex. The build runs in the folder holding main (a/b) - used when main reads another
      folder inside the build root via ../.
    - `<key>=<name>:x/review.pdf` - a view-only PDF (no rebuild, page/region pins).
    key must be [a-z0-9-]{1,24}; name must be 40 characters or fewer with no ':'. The path must be inside
    --manuscript (a security constraint: a pin can only ever point at a file inside the manuscript tree).
    Raises ValueError (with a Korean-language reason) if malformed."""
    if not isinstance(spec, str) or "=" not in spec:
        raise ValueError("--doc 는 <키>=<표시 이름>:<경로> 형식입니다: %r" % spec)
    key, rest = spec.split("=", 1)
    key = key.strip()
    if not DOC_KEY_RE.fullmatch(key):
        raise ValueError("--doc 키는 영문 소문자·숫자·'-' 1–24자여야 합니다: %r" % key)
    if ":" not in rest:
        raise ValueError("--doc %s: 표시 이름과 경로 사이에 ':' 가 없습니다: %r" % (key, spec))
    name, path = rest.split(":", 1)
    name = " ".join(name.split())
    if not name:
        raise ValueError("--doc %s: 표시 이름이 비었습니다" % key)
    if len(name) > DOC_NAME_MAX:
        raise ValueError("--doc %s: 표시 이름은 %d자 이하여야 합니다: %r" % (key, DOC_NAME_MAX, name))
    path = path.strip()
    if not path:
        raise ValueError("--doc %s: 경로가 비었습니다" % key)
    ms = ms.resolve()

    def inside(p: Path, what: str) -> Path:
        p = (p if p.is_absolute() else ms / p).resolve()
        try:
            p.relative_to(ms)
        except ValueError:
            raise ValueError("--doc %s: %s 가 --manuscript(%s) 밖입니다: %s" % (key, what, ms, p)) from None
        return p

    if "::" in path:
        root_s, main_s = path.split("::", 1)
        if "::" in main_s or not root_s.strip() or not main_s.strip():
            raise ValueError("--doc %s: 확장 표기는 <빌드 루트>::<메인.tex> 하나입니다: %r" % (key, path))
        root = inside(Path(root_s.strip()), "빌드 루트")
        if not root.is_dir():
            raise ValueError("--doc %s: 빌드 루트 폴더가 없습니다: %s" % (key, root))
        mp = Path(main_s.strip())
        if mp.is_absolute():
            raise ValueError("--doc %s: '::' 뒤 메인은 빌드 루트 기준 상대경로입니다: %s" % (key, mp))
        main = (root / mp).resolve()
        try:
            main.relative_to(root)
        except ValueError:
            raise ValueError("--doc %s: 메인 .tex 가 빌드 루트 밖입니다: %s" % (key, main)) from None
        if main.suffix.lower() != ".tex":
            raise ValueError("--doc %s: '::' 표기는 LaTeX 문서(.tex)에만 씁니다: %s" % (key, main))
    else:
        main = inside(Path(path), "경로")
        root = main.parent
    if not main.is_file():
        raise ValueError("--doc %s: 파일이 없습니다: %s" % (key, main))
    suf = main.suffix.lower()
    if suf == ".tex":
        kind = "tex"
    elif suf == ".pdf":
        kind = "pdf"
    else:
        raise ValueError("--doc %s: .tex(LaTeX) 또는 .pdf(보기 전용)만 받습니다: %s" % (key, main))
    return {"key": key, "name": name, "kind": kind, "src": root, "main": main}


def make_docs(specs: list, ms: Path) -> list:
    """--doc list -> Doc list. Checks for duplicate keys and the count ceiling. A LaTeX document keyed main uses the state-folder-root layout (root)."""
    if len(specs) > DOCS_MAX:
        raise ValueError("--doc 는 %d개까지입니다(지금 %d개)" % (DOCS_MAX, len(specs)))
    out, seen = [], set()
    for spec in specs:
        p = parse_doc_arg(spec, ms)
        if p["key"] in seen:
            raise ValueError("--doc 키가 겹칩니다: %s" % p["key"])
        seen.add(p["key"])
        out.append(Doc(p["key"], p["name"], p["kind"], src=p["src"], main=p["main"],
                       root=(p["key"] == DEFAULT_DOC_KEY and p["kind"] == "tex"), paths=C))
    return out


def init_doc(D: Doc, no_build: bool, wait: bool) -> dict:
    """Prepares one document at startup: legacy-layout migration, restoring build history, and building if needed. Builds in the background if wait=False."""
    D.dir.mkdir(parents=True, exist_ok=True)
    if D.root:
        build.migrate_pages(D)
    build.seed_builds(D, C.state)
    need = D.is_pdf and (pdf_changed(D) or not page_list(build.cur_pages(D)))
    if not D.is_pdf:
        need = not no_build or not build.cur_pdf(D).exists() or not page_list(build.cur_pages(D))
    if not need:
        return {"state": "skip"}
    return build_all(D) if wait else build_async(D)


def watch_pdf_docs(stop: threading.Event, every: float = 3.0) -> None:
    """Re-renders pages when a view-only PDF changes (mtime/size). Stands in for a rebuild button."""
    while not stop.wait(every):
        for D in list(DOCS):
            if D.is_pdf:
                try:
                    refresh_pdf_doc(D)
                except Exception:                     # noqa: BLE001 — the watch thread must never die
                    traceback.print_exc(file=sys.stderr)


def configure_access(a) -> StartupRefused | None:
    """Validates and applies the access options (--auth, tokens/loopback agent, --bind, proxy, members) to C, or
    returns the refusal with a clear message for a refused combination - main() stops before any build, so a
    misconfigured unit fails fast. Settings applied before the refused option stay applied (the process ends).

    Rules: a non-loopback --bind needs --auth trusted-proxy or --i-know-this-is-insecure. The headerless loopback agent
    exists only under tailscale on a loopback bind; asking for it (--agent-loopback) anywhere else refuses to start."""
    C.auth = a.auth or "tailscale"
    C.bind = a.bind or "127.0.0.1"
    try:
        loop_bind = is_loopback_bind(C.bind)
    except ValueError:
        return StartupRefused("--bind takes an IP address (or localhost): %s" % C.bind)
    if not loop_bind and C.auth != "trusted-proxy" and not a.i_know_this_is_insecure:
        return StartupRefused("Refusing to bind %s with --auth %s: a non-loopback address is only safe behind an authenticating "
                 "proxy (--auth trusted-proxy). Keep the default 127.0.0.1 and expose it with tailscale serve, or "
                 "pass --i-know-this-is-insecure if this network is private." % (C.bind, C.auth))
    loopback_agent_possible = C.auth == "tailscale" and loop_bind
    if a.agent_loopback is True and not loopback_agent_possible:
        return StartupRefused("--agent-loopback (AGENT_LOOPBACK=1) works only with --auth tailscale on a loopback --bind "
                 "(here: --auth %s, --bind %s). Give agents a token instead: limn token create <instance>"
                 % (C.auth, C.bind))
    C.agent_loopback = loopback_agent_possible and a.agent_loopback is not False
    if a.tailnet_agent and not C.agent_loopback:
        return StartupRefused("--tailnet-agent (TAILNET_AGENT=1) extends the headerless loopback agent to requests through tailscale serve, "
                 "so it needs it on: --auth tailscale, a loopback --bind and no --no-agent-loopback (here: --auth %s, "
                 "--bind %s%s). Give agents a token instead: limn token create <instance>"
                 % (C.auth, C.bind, ", --no-agent-loopback" if a.agent_loopback is False else ""))
    C.tailnet_agent = bool(a.tailnet_agent)
    try:
        C.public_hosts = parse_public_hosts(a.public_host)
        C.trusted_proxies = parse_networks(a.trusted_proxies)
    except ValueError as e:
        return StartupRefused(str(e))
    for opt, v in (("--proxy-user-header", a.proxy_user_header), ("--proxy-name-header", a.proxy_name_header),
                   ("--proxy-email-header", a.proxy_email_header)):
        if v is not None and not HEADER_NAME_RE.fullmatch(v):
            return StartupRefused("%s takes an HTTP header name: %r" % (opt, v))
    C.proxy_user_header, C.proxy_name_header, C.proxy_email_header = a.proxy_user_header, a.proxy_name_header, a.proxy_email_header
    C.members_only = bool(a.members_only)
    if a.local_user is not None and not valid_login(a.local_user):
        return StartupRefused("--local-user takes a login (no spaces, not 'local' or 'agent:...'): %r" % a.local_user)
    C.local_user = a.local_user
    C.insecure = bool(a.i_know_this_is_insecure) and not loop_bind and C.auth != "trusted-proxy"
    C.agent_token_file = Path(a.agent_token_file).expanduser() if a.agent_token_file else None
    return None


def tighten_state_perms() -> None:
    """people.json holds logins and roles (roles are permissions). It is written 0600 since v0.2.1; an older file that
    others may write is tightened to 0600 on startup, logged once. Other state files keep their mode - pins.md and
    pins.jsonl are what agents (possibly another account on the machine) read."""
    p = C.people_file
    try:
        mode = p.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o022:
        try:
            os.chmod(p, 0o600)
        except OSError as e:
            print("warning: %s is writable by others (%o) and could not be tightened: %s" % (p, mode, e), file=sys.stderr)
            return
        print("people.json: tightened %s from %o to 600 (it was writable by others)" % (p, mode), file=sys.stderr)


def access_log_lines() -> list:
    """Startup log lines about access: the provider line, and warnings for a non-loopback bind / the deprecated loopback agent."""
    parts = [C.auth]
    if C.auth == "local":
        parts.append("owner %s" % local_owner_actor()["login"])
    if C.auth == "trusted-proxy":
        parts.append("proxies %s" % ",".join(str(n) for n in C.trusted_proxies))
        parts.append("user header %s" % C.proxy_user_header)
    parts.append("tokens %d" % len(load_tokens(C.state)))
    if C.agent_token_file is not None:
        parts.append("token file %s (%s)" % (C.agent_token_file, "present" if file_present(C.agent_token_file) else "absent"))
    parts.append("loopback agent %s" % ("on (deprecated)" if C.agent_loopback else "off"))
    if C.agent_loopback:                          # only meaningful where the loopback agent exists
        parts.append("tailnet agent %s" % ("on (deprecated)" if C.tailnet_agent else "off"))
    parts.append("members-only %s" % ("on" if C.members_only else "off"))
    if C.public_hosts:
        parts.append("public hosts %s" % ",".join(n + (":%d" % p if p else "") for n, p in C.public_hosts))
    out = ["auth        " + " · ".join(parts)]
    if not is_loopback_bind(C.bind):
        out.append("warning     bound to %s (not loopback) - identity provider: %s. Anyone who can reach this port "
                   "can try it; only %s" % (C.bind, C.auth,
                                           "the configured --trusted-proxies may vouch for people"
                                           if C.auth == "trusted-proxy" else "tokens and the provider stand in the way"))
    if C.insecure:
        out.append("warning     !!! --i-know-this-is-insecure: --auth %s on %s is NOT an authentication boundary - "
                   "anyone on this network can read the manuscript and change pins. Use --auth trusted-proxy behind an "
                   "authenticating proxy, or bind 127.0.0.1 and use tailscale serve !!!" % (C.auth, C.bind))
    if C.agent_loopback:
        out.append("warning     " + LOOPBACK_AGENT_DEPRECATION)
    if C.tailnet_agent:
        out.append("warning     --tailnet-agent: a headerless request through tailscale serve (a tagged device) is treated "
                   "as the agent - anyone who can reach the tailnet address without an identity can change pins. Give "
                   "remote agents a token (limn token create <instance>) and drop TAILNET_AGENT")
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    """The `limn serve` argument parser. Defaults that come from the environment (LIMN_AGENT_TOKEN_FILE) are read
    when the parser is built, i.e. at startup in main()."""
    ap = argparse.ArgumentParser(prog="limn serve", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version="%s %s" % (APP_NAME, app_version()))
    ap.add_argument("--manuscript", required=True, help="LaTeX source root directory")
    ap.add_argument("--main", help="Top-level .tex filename (auto-detected if omitted). Not used together with --doc")
    ap.add_argument("--doc", action="append", default=[], metavar="KEY=NAME:PATH",
                    help="A document the viewer can switch to (repeatable). PATH is relative to --manuscript. "
                         ".tex = LaTeX (build root is that folder), "
                         "<build root>::<main.tex> = build root given separately, .pdf = view-only. The first document is the default. "
                         "If omitted, a single document (key main) built from --manuscript/--main")
    ap.add_argument("--port", type=int, help="Picks a free port in 18300-18400 if omitted")
    ap.add_argument("--state-dir", help="Location of pins and build artifacts")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--float-envs", default=DEFAULT_ENVS)
    ap.add_argument("--build-timeout", type=int, default=900)
    ap.add_argument("--no-build", action="store_true", help="Don't rebuild on startup")
    ap.add_argument("--allow", default="",
                    help="Allowed logins (comma-separated). Everyone is allowed if empty. A loopback "
                         "request with no identity header (curl/agent) is always allowed; a request to *.ts.net with no "
                         "identity header (a tag device) is denied (with or without this option, unless --tailnet-agent)")
    ap.add_argument("--no-origin-check", action="store_true",
                    help="Turns off Host/Origin checking (DNS rebinding/CSRF defense). Use only when tailscale "
                         "serve passes an unexpected Host/Origin and the UI gets a 403")
    ap.add_argument("--git-pull", action="store_true",
                    help="Checks remote main right after startup and every 60 seconds, rebuilding the PDF on a "
                         "new commit. A manual rebuild also does an --ff-only pull of upstream before the copy. Skipped with a screen notice if there are local changes or a divergence")
    ap.add_argument("--pdfjs-dir",
                    help="The PDF.js directory the viewer uses for vector rendering (pdf.min.mjs/pdf.worker.min.mjs). "
                         "Defaults to the limn/vendor/pdfjs bundled with the package. Falls back to PNG in the viewer if absent")
    ap.add_argument("--label",
                    help="A label distinguishing tabs/the tool bar when multiple manuscript viewers are open at once "
                         "(%d characters or fewer). Defaults to --manuscript's git origin repo name, or the folder name if not a git repo" % LABEL_MAX)
    ap.add_argument("--accent",
                    help="The label's accent color (#rrggbb). If omitted, one is picked from a fixed palette by "
                         "hashing the label string (the same label always gets the same color)")
    acc = ap.add_argument_group("access control (docs/adr/0002-access-control.md)")
    acc.add_argument("--auth", choices=AUTH_PROVIDERS,
                     help="Identity provider. tailscale (default): Tailscale-User-* headers from a loopback peer "
                          "(tailscale serve). local: a single user on this machine - every loopback request is the "
                          "owner; agents use a token. trusted-proxy: identity headers set by an authenticating reverse "
                          "proxy, trusted only from --trusted-proxies. Every provider accepts 'Authorization: Bearer "
                          "<token>' (limn token create)")
    lb = acc.add_mutually_exclusive_group()
    lb.add_argument("--no-agent-loopback", dest="agent_loopback", action="store_const", const=False, default=None,
                    help="Refuse (401) loopback requests with no identity header or token instead of treating them "
                         "as the agent (the deprecated v0.1 behaviour, on by default under --auth tailscale)")
    lb.add_argument("--agent-loopback", dest="agent_loopback", action="store_const", const=True,
                    help="Explicitly keep the deprecated headerless loopback agent. Refuses to start where it cannot "
                         "apply (--auth local or trusted-proxy, or a non-loopback --bind)")
    acc.add_argument("--tailnet-agent", action="store_true",
                     help="Also treat a headerless request that arrives through tailscale serve (Host *.ts.net or a "
                          "--public-host, e.g. from a tagged device) as the agent, as v0.2.0 did. Off by default: such "
                          "requests get 403 and remote agents use a token. Needs the loopback agent (deprecated)")
    acc.add_argument("--bind", default="127.0.0.1",
                     help="Listen address (default 127.0.0.1). A non-loopback address needs --auth trusted-proxy or "
                          "--i-know-this-is-insecure")
    acc.add_argument("--i-know-this-is-insecure", action="store_true",
                     help="Allow a non-loopback --bind without --auth trusted-proxy (prints a loud warning)")
    acc.add_argument("--public-host", action="append", default=[], metavar="NAME[:PORT]",
                     help="A public host name the server is reached under (repeatable or comma-separated): accepted as "
                          "Host and as https Origin (port 443 unless given), and used as the pins.md base URL")
    acc.add_argument("--trusted-proxies", default="127.0.0.1,::1", metavar="IP/CIDR,...",
                     help="Peers whose identity headers --auth trusted-proxy trusts (default 127.0.0.1,::1)")
    acc.add_argument("--proxy-user-header", default="X-Forwarded-User",
                     help="Header carrying the user under --auth trusted-proxy (default X-Forwarded-User)")
    acc.add_argument("--proxy-name-header", default="X-Forwarded-Preferred-Username",
                     help="Header carrying the display name (default X-Forwarded-Preferred-Username)")
    acc.add_argument("--proxy-email-header",
                     help="Optional header carrying the e-mail; when present it is used as the login")
    acc.add_argument("--members-only", action="store_true",
                     help="Admit only people listed in people.json (limn member add) or --allow; others get 403 and are not recorded")
    acc.add_argument("--local-user",
                     help="The owner's login under --auth local (default $USER, then 'owner')")
    acc.add_argument("--agent-token-file", default=os.environ.get("LIMN_AGENT_TOKEN_FILE") or None, metavar="PATH",
                     help="Where agents on this machine keep this instance's token (limn token create <instance> "
                          "--save; default $LIMN_AGENT_TOKEN_FILE, which limn run sets). Never read: once the file "
                          "exists, pins.md and the 401 for a headerless local request tell agents to send it")
    return ap


def port_in_use_message(bind: str, port: int) -> str:
    return ("limn serve: port %d on %s is already in use - stop the other server, or pick another --port"
            % (port, bind))


def listen_refusal(bind: str, port: int, e: OSError) -> StartupRefused:
    """The one line for a port that cannot be listened on: taken (EADDRINUSE), or the OS's reason."""
    if e.errno == errno.EADDRINUSE:
        return StartupRefused(port_in_use_message(bind, port))
    return StartupRefused("limn serve: cannot listen on %s port %d: %s" % (bind, port, e.strerror or e))


def probe_port(bind: str, port: int) -> StartupRefused | None:
    """Refuses (one line, exit 1) when --port is taken - before a build that can take minutes, and instead of the
    Errno 98 traceback the server constructor would print (observed in the v0.2.0 QA)."""
    fam = socket.AF_INET6 if ":" in bind else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # the same option the server sets (allow_reuse_address)
        s.bind((bind, port))
    except OSError as e:
        return listen_refusal(bind, port, e)
    finally:
        s.close()
    return None


def configure_run(a) -> list | None | StartupRefused:
    """The run settings from the arguments into C, in the order that decides which refusal a bad command line gets:
    the manuscript, the documents (--doc, returned; None without it) or the main file, the state folder (created
    here, before the label and accent are checked), build settings, the port, access lists, the label and accent -
    and the viewer page they fill in (HTML)."""
    global HTML
    C.src = Path(a.manuscript).expanduser().resolve()
    if not C.src.is_dir():
        return StartupRefused("Manuscript directory does not exist: %s" % C.src)
    if a.doc:
        if a.main:
            return StartupRefused("--doc and --main are not used together - the main file is set via the --doc path.")
        try:
            docs = make_docs(a.doc, C.src)
        except ValueError as e:
            return StartupRefused(str(e))
        first_tex = next((d for d in docs if not d.is_pdf), docs[0])
        C.main = first_tex.main
    else:
        docs = None
        main_file = (C.src / a.main) if a.main else detect_main(C.src)
        if isinstance(main_file, StartupRefused):
            return main_file
        C.main = main_file
        if not C.main.exists():
            return StartupRefused("Top-level .tex does not exist: %s" % C.main)

    default_state = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    C.state = Path(a.state_dir).expanduser().resolve() if a.state_dir \
        else default_state / "limn" / "serve" / state_slug(C.src)
    C.state.mkdir(parents=True, exist_ok=True)
    C.build = C.state / "build"
    C.dpi = a.dpi
    C.envs = tuple(e.strip() for e in a.float_envs.split(",") if e.strip())
    C.timeout = a.build_timeout
    port = a.port or free_port()
    if isinstance(port, StartupRefused):
        return port
    C.port = port
    C.allow = frozenset(x.strip() for x in a.allow.split(",") if x.strip())
    C.origin_check = not a.no_origin_check
    C.git_pull = a.git_pull
    C.pdfjs_dir = Path(a.pdfjs_dir).expanduser().resolve() if a.pdfjs_dir else default_pdfjs_dir()
    C.repo = git_remote_url(C.src)
    # The default label (repo name) is truncated if too long - startup must not halt just because of a long
    # repo name (observed: a 62-character repo). Only an explicitly given --label halts on excess length (so a typo is never silently truncated).
    label = clean_label(a.label) if a.label else clean_label(truncate_quote(default_label(C.src, C.repo), LABEL_MAX))
    if isinstance(label, StartupRefused):
        return label
    C.label = label
    if a.accent:
        if not valid_accent(a.accent):
            return StartupRefused("--accent must be in #rrggbb form: %s" % a.accent)
        C.accent = a.accent.lower()
    else:
        C.accent = pick_accent(C.label)
    HTML = build_html(C.label, C.accent)
    return docs


def prepare(docs: list | None, no_build: bool) -> StartupRefused | None:
    """The documents, pin store and builds before serving: the document list, pins.seq, the Trash's expired entries,
    then either the single document's build (synchronous; a failed build refuses to start) or every --doc
    document's build in the background (a failure only opens that tab's error panel), and the watch threads."""
    set_docs(docs)
    init_seq()
    purge_trash()                    # Trash entries older than TRASH_DAYS go at startup, on every drop/restore, and hourly on reads
    if not docs:
        D = DOCS[0]
        build.migrate_pages(D)
        build.seed_builds(D, C.state)    # adds the current build (made by an earlier instance) to history if missing, and restores the last build result
        if not no_build or not build.cur_pdf(D).exists() or not page_list(build.cur_pages(D)):
            r = build_all(D)
            if r.get("state") == "fail":
                return StartupRefused("Build failed:\n" + r.get("log", ""))
    else:
        # Multiple documents: each document's build runs in the background, and the server comes up right
        # away (never waits N documents x tens of seconds). A failure never blocks startup - that document's tab opens an error panel instead.
        for D in DOCS:
            r = init_doc(D, no_build, wait=False)
            print("doc    %-10s %s %s%s" % (D.key, "view-only" if D.is_pdf else "LaTeX   ", D.rel_path(),
                                           "" if r.get("state") == "skip" else "  (build started)"))
        threading.Thread(target=watch_pdf_docs, args=(threading.Event(),), daemon=True).start()
    if C.git_pull:
        threading.Thread(target=watch_main, args=(threading.Event(),), daemon=True).start()
    with PIN_LOCK:
        render_pins_md(read_pins()[0])
    tighten_state_perms()
    return None


def report(docs: list | None) -> None:
    """The startup summary on stdout: manuscript, label, state folder, address, access, and the optional features."""
    print("manuscript  %s" % (C.src if docs else C.main))
    print("label       %s (%s)%s" % (C.label, C.accent, "" if C.repo else " - no git origin, using the folder name as default"))
    print("state       %s" % C.state)
    if is_loopback_bind(C.bind):
        print("address     http://%s:%d/   (external exposure only via tailscale serve)"
              % ("[%s]" % C.bind if ":" in C.bind else C.bind, C.port))
    else:
        print("address     http://%s:%d/" % ("[%s]" % C.bind if ":" in C.bind else C.bind, C.port))
    for line in access_log_lines():
        print(line)
    if C.allow:
        print("allow       %s%s" % (", ".join(sorted(C.allow)),
                                    " (a loopback request with no header is still allowed)" if C.agent_loopback else ""))
    if not C.origin_check:
        print("warning     --no-origin-check: Host/Origin checking is off (no DNS rebinding defense)")
    if C.git_pull:
        print("git-pull    checks main right after startup and every 60 seconds, rebuilding the PDF on a new commit")
    if vendor_file("pdf.min.mjs") and vendor_file("pdf.worker.min.mjs"):
        print("pdf.js      %s (vector rendering)" % C.pdfjs_dir)
    else:
        print("warning     pdf.js is missing (%s) - the viewer falls back to PNG" % C.pdfjs_dir)
    sys.stdout.flush()


def listen() -> Server | StartupRefused:
    """The HTTP server on --bind/--port with this module's Handler (Server6 for an IPv6 address), or the refusal when
    the port was taken during the build (the probe before it passed) or cannot be listened on."""
    try:
        return (Server6 if ":" in C.bind else Server)((C.bind, C.port), Handler)
    except OSError as e:
        return listen_refusal(C.bind, C.port, e)


def start(a) -> Server | StartupRefused:
    """Every startup step, in order, until one refuses: access settings, the --port probe, the run settings and
    documents, the store and builds, the summary, then the listening server."""
    refused = configure_access(a)
    if refused is None and a.port:
        refused = probe_port(C.bind, a.port)
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
