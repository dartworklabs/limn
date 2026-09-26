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
import errno
import hashlib
import html
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from collections.abc import Collection
from typing import NamedTuple
from urllib.parse import quote

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
    ASSIGNEE_AGENT, KIND_REQS, NOTE_MAX, AddRequest, Anchoring, EditRefusal, EditRequest,
    LinePlace, Located, PinEdited, RegionPlace, decide_edit, evolve_edit, file_after, new_line_pin, new_region_pin,
)
from limn.pins.model import (  # noqa: E402 - after the path bootstrap above
    Actor, Agent, DonePin, OpenPin, Person, PinNotFound, ReviewPin, TrashedPin, is_region_pin, parse_pin,
)
from limn import build  # noqa: E402 - after the path bootstrap above
from limn.build import BuildConfig  # noqa: E402 - after the path bootstrap above
from limn.files import atomic_write, file_in_tree, store_lock, tex_lines, vendor_file as find_vendor_file  # noqa: E402,F401 - tex_lines is ps.tex_lines to the tests
from limn import events, people  # noqa: E402 - after the path bootstrap above
from limn.audit import AUDIT_FILE, append_audit, audit_entry, os_actor  # noqa: E402 - after the path bootstrap above
from limn.events import EVENTS_KEEP  # noqa: E402 - after the path bootstrap above
from limn.mentions import (  # noqa: E402 - after the path bootstrap above
    NoteTags, addressed_to, fyi_mentions_to, note_mention_targets, pin_mentions_all,
    resolve_mentions, tag_note, thread_round,
)
from limn.people import is_actor as _is_actor, people_text, valid_people as _valid_people  # noqa: E402
from limn.store import PinFiles, PinStore, find_pin  # noqa: E402 - after the path bootstrap above
from limn import revisions  # noqa: E402 - after the path bootstrap above
from limn import documents  # noqa: E402 - after the path bootstrap above
from limn.documents import (  # noqa: E402 - after the path bootstrap above
    DEFAULT_DOC_KEY, DOC_KEY_RE, DOC_NAME_MAX, DOCS_MAX, Doc, DocNotFound, DocumentFacts,
)
from limn import meta as meta_reads  # noqa: E402 - the module; meta() below is the App member that binds it
from limn.meta import MetaSettings, outline_labels  # noqa: E402,F401 - outline_labels is an App member
# The page directory on screen, a build's PDF and the build state are App members the handler calls with the request's
# document (web/app.py); they are limn.build's own functions, bound here without a shell.
from limn.build import build_pdf, cur_pages, pdf_changed, state_snapshot as build_state_snapshot  # noqa: E402,F401
from limn.revisions import git as _git, revision_history  # noqa: E402,F401 - after the path bootstrap; revision_history is an App member
from limn.scope import valid_changes  # noqa: E402 - after the path bootstrap above
from limn.mapping import (  # noqa: E402 - after the path bootstrap above
    anchor_of, truncate_quote,
)
from limn import locate  # noqa: E402 - after the path bootstrap above
from limn.locate import PinLocation, est_context, locate_file  # noqa: E402 - after the path bootstrap above
from limn.pins import position  # noqa: E402 - after the path bootstrap above
from limn.pins.position import epoch as _epoch, pin_est  # noqa: E402 - after the path bootstrap above
from limn.mark import favicon_svg, inline_svg  # noqa: E402
from limn import access  # noqa: E402 - after the path bootstrap above
from limn.access import (  # noqa: E402 - after the path bootstrap above
    AGENT_LOGIN_PREFIX, AUTH_PROVIDERS, DEFAULT_ROLE, HEADER_NAME_RE, LOCAL_ACTOR, LOOPBACK_AGENT_DEPRECATION,
    file_present, home_or_none, is_loopback_bind, load_tokens, local_owner_actor, parse_networks, parse_public_hosts,
    roles_of, valid_login,
)
# hdr_text is an App member (web/app.py): the handler quotes a refused Host/Origin/document key through it.
from limn.access import hdr_text  # noqa: E402,F401 - after the path bootstrap above
from limn.guidance import shell_path  # noqa: E402 - after the path bootstrap above
# pins.md's renderer; server.py builds its input (pins_md_input).
from limn.pins.render import (  # noqa: E402 - after the path bootstrap above
    DocHeading, PinFacts, PinsMdInput, pins_md_text as render_pins_md_text,
)
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
# Their limits live with their rules: PEOPLE_TOUCH_S in limn.people, EVENTS_KEEP and the notice types in limn.events,
# NOTE_MENTION_COOLDOWN_S in limn.mentions.
TRASH_DAYS = 30                    # a dropped pin stays in the Trash (pins.dropped.jsonl) this long, then is purged for good
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
        return self.state / people.PEOPLE_FILE

    @property
    def events_file(self) -> Path:
        return self.state / events.EVENTS_FILE

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
    """One tracked build of D: LaTeX (_build) or, for view-only, the page render (limn.build.render_pdf_doc)
    (limn.build.run_tracked). The step is looked up when the build runs, so a test that replaces _build sees it."""
    step = (lambda: build.render_pdf_doc(D, build_config())) if D.is_pdf else (lambda: _build(D))
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


# ---------------------------------------------------------------- --git-pull: the pull itself and the remote-main watch

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
# A PDF with no LaTeX source (reviewer comments, etc.) has no rebuild; when that PDF file changes, its page images are
# re-rendered through the same tracked build as a LaTeX rebuild (limn.build.render_pdf_doc, pdf_changed).

def refresh_pdf_doc(D: Doc) -> bool:
    """If the PDF changed, re-render it in the background (does nothing if already rendering). True if it started."""
    if not D.is_pdf or not pdf_changed(D):
        return False
    r = build_async(D)
    return not r.get("busy")


# ---------------------------------------------------------------- Documents and meta
#
# The document list (DOCS, the first is the default) is this composition root's. The lookups over it are
# limn.documents' and the polled reads (GET /api/meta, /api/docs, /api/outline-labels) limn.meta's; each takes the
# list and the run settings as arguments, bound here.

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


def doc_by_key(key) -> Doc | None:
    """The document of this instance whose key is `key`, or None (limn.documents.doc_by_key)."""
    return documents.doc_by_key(DOCS, key)


def pin_doc_key(r: dict) -> str:
    """The document key a pin belongs to; a legacy record without a doc field is the first document's
    (limn.documents.pin_doc_key)."""
    return documents.pin_doc_key(r, DOCS)


def meta_settings() -> MetaSettings:
    """The run settings GET /api/meta reads, made per request like pin_store(), so a test (or main()) that changes C is
    seen at once."""
    return MetaSettings(state=C.state, pins_md=C.pins_md, pins_jsonl=C.pins_jsonl, label=C.label, accent=C.accent,
                        repo=C.repo, dpi=C.dpi)


def docs_payload() -> dict:
    """GET /api/docs — the document list and open-pin counts per document. Pins are only read (no sync write)."""
    rows, _ = read_pins()
    return meta_reads.docs_payload(DOCS, rows, pin_doc_key, C.state)


def meta(D: Doc, actor: dict, light: bool = False) -> dict:
    """GET /api/meta for document D: its pages, builds, staleness and settings for the viewer (limn.meta.meta); with
    light (polling) the pin counts are left out, and with them the sync write of snapshot_pins()."""
    out = meta_reads.meta(D, actor, meta_settings(), DOCS, sync_status(), time.time())
    if light:                             # polling only - skips the sync write in snapshot_pins()
        return out
    out.update(meta_reads.pin_counts([pin_state(r) for r in snapshot_pins()]))
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
    """The document of this instance that key names, else the one holding file_hint, else the first; DocNotFound for a
    key it does not serve (limn.documents.request_doc)."""
    return documents.request_doc(DOCS, C.src, key, file_hint)


def document_facts(D: Doc) -> DocumentFacts:
    """The parsing facts of document D (limn.documents.DocumentFacts) with this instance's manuscript root and dpi -
    made per request like pin_store(), so a test (or main()) that changes C is seen at once."""
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
# people.json (limn/people.py), the @-tag rules (limn/mentions.py) and events.jsonl (limn/events.py) take their paths,
# locks, caches and clock as arguments. The process's ones are made here, once, and bound per call by people_book()
# and event_log(); the functions below keep the names the pin services, the handler (web/app.py) and the tests call.

PEOPLE_LOCK = threading.Lock()
EVENTS_LOCK = threading.Lock()
_PEOPLE_SEEN: people.SeenMemo = {}    # (people.json path, login) -> (name, pic, epoch last written) - not rewritten if the value is unchanged
_EVENTS_CACHE: events.ReadCache = {}  # events.jsonl as last read, keyed by its mtime/size


def people_book() -> people.PeopleBook:
    """people.json of the current run (limn.people.PeopleBook): C.state with the process's lock and last-written memo.
    Made per call, like pin_store(), so a test or main() that changes C.state is seen at once."""
    return people.PeopleBook(C.state, PEOPLE_LOCK, _PEOPLE_SEEN)


def load_people() -> list:
    """The valid entries of this run's people.json (limn.people.load_people); [] when it is missing or unreadable."""
    return people.load_people(C.people_file)


def record_person(actor: dict, now: float = None, role: str = None) -> bool:
    """Records a tailnet person into people.json (limn.people.record_person: a new person, a name/picture change, or
    last_seen stale past PEOPLE_TOUCH_S). Local/agent and an actor without a login are never recorded. The request
    continues even if the write fails (only a warning). Returns True if it wrote. A person seen for the first time gets
    no role field (= DEFAULT_ROLE) unless `role` is given (the local owner is recorded as owner)."""
    login = (actor or {}).get("login")
    if not login or is_agent(actor):
        return False
    return people.record_person(people_book(), actor, time.time() if now is None else now, role, DEFAULT_ROLE)


def known_people(rows: list = None) -> dict:
    """@-tag candidates {login: {login,name,pic?,last_seen?}} - people.json plus the people on the pins (rows, or the
    stored pins when None), agents excluded (limn.people.known_people)."""
    ppl = load_people()
    return people.known_people(ppl, rows if rows is not None else read_pins()[0], is_agent)


def event_log() -> events.EventLog:
    """events.jsonl of the current run (limn.events.EventLog) with the process's lock and read cache, stamped by
    time.time() and now_str() - looked up when the value is made, so a test that freezes either reaches the records."""
    return events.EventLog(C.events_file, EVENTS_LOCK, _EVENTS_CACHE, time.time, now_str)


def make_event(typ: str, r: dict, actor: dict, to, msg: dict = None, text: str = None) -> dict:
    """One events.jsonl line about pin r by actor (limn.events.make_event; seq/at are filled in by emit_events). The
    actor themselves and local are removed from to - None (not recorded) if that leaves it empty."""
    return events.make_event(typ, r, actor, to, who, pin_doc_key, LOCAL_ACTOR["login"], msg, text)


def emit_events(evs: list) -> None:
    """Appends notices to events.jsonl, keeping the newest EVENTS_KEEP (limn.events.EventLog.emit). Only called after
    the pin write has committed (prevents phantom events); a failure is just a warning."""
    event_log().emit(evs, EVENTS_KEEP)


def _read_events() -> tuple:
    """(event list, file signature) of events.jsonl, cached by mtime/size (limn.events.EventLog.read)."""
    return event_log().read()


def note_tags(note: str, old_note: str, rows: list, hints, actor: dict, pid: object) -> NoteTags:
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


def events_since(actor: dict, cursor: int | None) -> dict:
    """Notification material carried in /api/meta polling (limn.events.events_since): ev_seq always, and with a cursor
    the events after it addressed to the requester's tailnet login - nothing for local/agent. Read-only."""
    rows, _ = _read_events()
    me = (actor or {}).get("login")
    return events.events_since(rows, None if not me or is_agent(actor) else me, cursor, {d.key: d.name for d in DOCS})


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


def render_pins_md(rows: list) -> None:
    """Rewrites pins.md from rows alone (PinStore.render_md). Callers hold PIN_LOCK."""
    pin_store().render_md(rows)


def pins_md_text(rows: list, base: str | None = None) -> str:
    """pins.md's text for rows: limn.pins.render.pins_md_text over pins_md_input(rows, base). The store renders with
    this after every write (base None: the file on disk) and GET /pins.md with the request's base."""
    return render_pins_md_text(pins_md_input(rows, base))


def pins_md_input(rows: list, base: str | None = None) -> PinsMdInput:
    """Everything one rendering of pins.md reads, gathered at the edge: the run settings in C, the documents and their
    build stamps, the clock, this machine's token file, people.json, and per pin what the overlap, @-tag, thread and
    file-location rules decide. base is GET /pins.md's request base, None for the file written to disk.

    Reads files (people.json, the build stamps, whether the token file exists, and the source file of each open
    one-line pin that carries a quote - each file read at most once per call) but writes nothing."""
    rel = overlaps_by_id(rows)
    by_id = {r["id"]: r for r in rows}
    sources: dict = {}
    facts = {}
    for r in rows:
        if pin_state(r) == "done":
            continue
        location, line_len = "", None
        if not is_region_pin(r):
            loc = pin_location(r, C.src)             # ADR-0006: still relative after the checkout moved
            location = loc.rel if loc is not None else (Path(str(r.get("file", ""))).name or str(r.get("name") or ""))
            lo, hi = r.get("lo"), r.get("hi")
            if loc is not None and not r.get("done") and r.get("quote") and _is_int(lo) and _is_int(hi) and lo == hi:
                if loc.path not in sources:          # outside the tree (loc None) is never read
                    sources[loc.path] = tex_lines(loc.path)
                lines = sources[loc.path]
                line_len = len(lines[lo - 1]) if 1 <= lo <= len(lines) else None
        facts[r["id"]] = PinFacts(
            doc_key=pin_doc_key(r), location=location, line_len=line_len,
            badge=rel_badge(rel.get(r["id"], []), by_id, r), reopened=pin_reopened_in_round(r),
            addressed=tuple(addressed_to(r)), fyi=tuple(fyi_mentions_to(r)), round=tuple(thread_round(r)))
    docs = tuple(DocHeading(d.key, d.name, d.rel_path(), d.is_pdf, build.read_head(d), build.read_built_at(d))
                 for d in DOCS)
    return PinsMdInput(
        rows=rows, facts=facts, base=base, port=C.port, manuscript=str(C.src), label=C.label, repo=C.repo, docs=docs,
        people=known_people(rows), now=time.time(), updated=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        token_file=existing_token_file_shown(C.agent_token_file))


def existing_token_file_shown(f: Path | None) -> str | None:
    """The shell path of token file f when it exists, else None - the edge half of
    limn.pins.render.token_guidance_line(): one stat per render, never a read of the file."""
    return shell_path(f, home_or_none()) if file_present(f) else None




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


# ---------------------------------------------------------------- Access control wiring (limn/access.py, docs/adr/0002-access-control.md)
#
# Who a request is (identify), whether it may use this instance (admit), what it may change (check_role) and the
# Host/Origin rules live in limn/access.py, which never reads C. Here the composition root binds them to this instance:
# the settings value from C (made per call like build_config(), so a test or main() that changes C is seen at once),
# the file-backed lookups, and the resources this process owns for them - one cache per file (tokens.json and
# people.json are re-read when they change on disk, so `limn token` / `limn member` edits take effect on the next
# request without a restart) and the one-time loopback-agent warning. The refusals raise HTTPError (fail closed).

TOKENS_CACHE: access.FileCache[list] = access.FileCache()   # tokens.json's valid entries as this process last read them
ROLES_CACHE: access.FileCache[dict] = access.FileCache()    # {login: role} of people.json as this process last read it
LOOPBACK_WARNING = access.WarnOnce(LOOPBACK_AGENT_DEPRECATION)
# How `limn member` reads and writes people.json: the people store's own format (load_people, record_person).
PEOPLE_FORMAT = access.PeopleFormat(valid_rows=_valid_people, text=people_text)


def access_settings() -> access.AccessSettings:
    """The access options of this run (C) as the value identify() and admit() read."""
    return access.AccessSettings(
        auth=C.auth, agent_loopback=C.agent_loopback, tailnet_agent=C.tailnet_agent, trusted_proxies=C.trusted_proxies,
        proxy_user_header=C.proxy_user_header, proxy_name_header=C.proxy_name_header,
        proxy_email_header=C.proxy_email_header, members_only=C.members_only, allow=C.allow, local_user=C.local_user,
        agent_token_file=C.agent_token_file)


def current_tokens() -> list:
    """tokens.json as the server sees it now - re-read whenever its inode/mtime/size changes (revocation needs no restart)."""
    return TOKENS_CACHE.get(C.tokens_file, lambda: load_tokens(C.state), [])


def people_roles() -> dict:
    """{login: role} for everyone in people.json, re-read whenever the file changes - so `limn member role` and
    `limn member remove` take effect on the running server's next request."""
    return ROLES_CACHE.get(C.people_file, lambda: roles_of(load_people()), {})


def role_of(login: str) -> str:
    """The people.json role of login; editor for someone people.json does not list."""
    return people_roles().get(login, DEFAULT_ROLE)


def access_lookups() -> access.AccessLookups:
    """The file-backed facts identify() reads at request time, over this process's caches and warning."""
    return access.AccessLookups(tokens=current_tokens, roles=people_roles, warn_loopback_agent=LOOPBACK_WARNING)


def identify(headers, peer) -> access.Principal:
    """Who this request is (limn.access.identify under this run's settings); raises HTTPError 401/403."""
    return access.identify(headers, peer, access_settings(), access_lookups())


def admit(p: access.Principal, host, headers=None) -> None:
    """May this principal use the instance at all (limn.access.admit); raises HTTPError 403."""
    access.admit(p, host, headers, access_settings(), people_roles)


def check_role(p: access.Principal, path: str) -> None:
    """The role rule for a POST to path (limn.access.check_role; the owner-only purge refusal quotes TRASH_DAYS);
    raises HTTPError 403."""
    access.check_role(p, path, TRASH_DAYS)


def host_ok(host: str) -> bool:
    """Is Host a loopback name, *.ts.net or one of this run's --public-host names (limn.access.host_ok)?"""
    return access.host_ok(host, C.public_hosts)


def origin_ok(origin: str, host) -> bool:
    """Is Origin on the same side as the Host the request arrived on (limn.access.origin_ok)?"""
    return access.origin_ok(origin, host, C.public_hosts)


def remote_base_for(host_raw: str) -> str:
    """The base URL of GET /pins.md's guidance for this Host (limn.access.remote_base_for, loopback on C.port)."""
    return access.remote_base_for(host_raw, C.public_hosts, C.port)


def cli_audit(state: Path) -> access.AuditSink:
    """The audit sink of `limn token` / `limn member` on state: each change becomes an audit.jsonl line as the OS
    account running the command (os_actor), via "cli", stamped when it is recorded."""
    def record(action: str, details: dict) -> bool:
        """Append one audit line for action with details (append_audit: a failed write only warns)."""
        return append_audit(state, audit_entry(action, os_actor(), "cli", details, time.time()))
    return record


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
        parts.append("owner %s" % local_owner_actor(C.local_user)["login"])
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
        if not no_build or not build.cur_pdf(D).exists() or not build.page_list(build.cur_pages(D), C.dpi):
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
