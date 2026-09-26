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
import selectors
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import tempfile
import time
import traceback
from collections import Counter
from datetime import datetime
from email.header import decode_header, make_header
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Callable, Sequence, Set as AbstractSet
from typing import Literal, NamedTuple, TypedDict
from urllib.parse import parse_qs, quote, urlparse

if __package__ in (None, ""):
    # Run as a file (python .../limn/server.py, how instances start): make the sibling modules importable as limn.*.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from limn.pins.lifecycle import (  # noqa: E402 - after the path bootstrap above
    AgentCannotConfirm, AlreadyClosed, AlreadyDone, AlreadyLive, ClaimClosedPin, ClaimedByOther, ClaimRequest,
    CloseRequest, NotClaimed, NotInTrash, PinReopened, PinStillOpen, Replied, ThreadFull, claim, claim_holds,
    confirm, confirmer, decide_close, decide_reopen, decide_reply, drop, evolve_close, evolve_reopen, evolve_reply,
    find_trashed, next_rev, reopen_request, reopens_on_reply, restore, thread_message, unclaim,
)
from limn.pins.model import (  # noqa: E402 - after the path bootstrap above
    Actor, Agent, DonePin, OpenPin, Person, PinNotFound, ReviewPin, TrashedPin, parse_pin,
)
from limn import build  # noqa: E402 - after the path bootstrap above
from limn.build import BuildConfig, valid_build_name  # noqa: E402 - after the path bootstrap above
from limn.files import atomic_write  # noqa: E402 - after the path bootstrap above
from limn.mapping import (  # noqa: E402 - after the path bootstrap above
    anchor_holds, anchor_of, by_text, compute_levels, densest, find_line, norm, pin_rel_path, score_range, snippet,
    truncate_quote,
)

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
    not translated — they are a language-stable contract for agents."""
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

TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{4,}|\d+\.\d+")
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

MAX_BODY = 1 << 20
NOTE_MAX = 4000
CLOSE_REPLY_MAX = 500              # what-was-fixed note left when closing (§P0b-보완 C)
CLOSE_REF_MAX = 80                 # reference (e.g. PR number) - matching values let the UI group closed pins together
CLOSE_CHANGES_MAX = 50             # v0.3: ranges in one close body's optional changes (the new-side lines the agent changed for the pin)
CHANGE_LINE_MAX = 1_000_000       # a line number past this is not a manuscript line
CLAIM_TTL_DEFAULT = 120            # minutes - lock duration used when neither ttl_min nor eta_min is given for a claim (§P0c-C)
CLAIM_TTL_MIN = 1
CLAIM_TTL_MAX = 120                # the lock auto-expiring is a safety net - at 480 a stuck agent held a pin for half a day (observed 23 times)
CLAIM_ETA_MIN = 1                  # minutes - estimated time to handle (eta_min). Shown in the UI rounded up to 5-minute steps
CLAIM_ETA_MAX = 240
CLAIM_TTL_FLOOR = 30               # if only eta_min is given, the lock is min(ceiling, max(this floor, eta x 2)) - even a short estimate holds for 30 min
# Pin kind and thread (docs/handbook/api.md §스레드). 24% of pins (10 of 42 in A-DEMO) were questions rather than
# something to fix, but the only place to leave an answer was the single close_reply field on closing, so
# there was no way to ask back. kind_req is kept separate from the legacy kind (scope type) to avoid a name clash.
KIND_REQS = ("fix", "question")    # defaults to fix if absent - legacy pins are all fix requests
THREAD_TEXT_MAX = 1000             # one reply - like the note (NOTE_MAX), only string/length are checked; the UI renders it via esc()
THREAD_MAX = 200                   # cap on one pin's thread (replies). State-transition records (close/reopen/confirm) are appended regardless of this cap
THREAD_EVENTS = ("close", "reopen", "confirm", "assign")
# Assignee (docs/handbook/api.md §담당). Who handles this pin - either "agent" or a person's login. If absent, it's a
# legacy pin, so addressed_to()'s inference (the @-tag on a question pin) is used as-is. Guessing this from the
# body text made the skip rule ambiguous (A-DEMO #43: a fix-request pin's "@Seojun please check" was meant for a person).
ASSIGNEE_AGENT = "agent"
# @-tags (docs/handbook/api.md §@태그·사람·이벤트). Only invoked inside the viewer - no external notification is sent, it's just recorded in events.jsonl.
MENTION_MAX = 10                   # cap on mention hints per post
PEOPLE_TOUCH_S = 600               # don't rewrite people.json's last_seen more often than this interval (so every poll doesn't trigger a write)
EVENTS_KEEP = 5000                 # number of recent events kept in events.jsonl. seq only increases (consumers follow along by seq)
NOTE_MENTION_COOLDOWN_S = 600      # a note save re-tagging the same person on the same pin notifies them at most this often per editor (issue #10 L3)
EVENT_TYPES = ("mention", "review_requested", "replied", "reopened", "assigned", "dropped")
TRASH_DAYS = 30                    # a dropped pin stays in the Trash (pins.dropped.jsonl) this long, then is purged for good
GIT_PULL_TIMEOUT = 30              # seconds - one fetch for --git-pull (§P0c-E)
REVISION_DIFF_MAX = 256 * 1024     # response/memory cap. Review large changes in the repo instead.
REVISION_ID_RE = re.compile(r"[0-9a-f]{40}")
SCOPES = ("raw", "para", "env", "env2", "env3", "lines")
ADD_FIELDS = ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score",
              "frac", "note", "scope", "quote", "pdf_build")
LOC_FIELDS = ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score",
              "frac", "scope", "quote")
LOCAL_ACTOR = {"login": "local", "name": "로컬/에이전트"}
AGENT_LOGIN_PREFIX = "agent:"      # API-token principals are {"login": "agent:<token name>", "name": "<token name>"}
CONFIRM_BY_HUMAN = "확인은 사람이 합니다 — 테일넷 신원으로 접속해 뷰어에서 [확인]을 누르세요."
CONFIRM_OPEN_DETAIL = "열린 핀은 확인할 것이 없습니다 — 닫힌 뒤 검토 대기일 때 확인합니다."
# Label shown so tabs don't get confused when multiple manuscript viewers are open at once (§Running multiple manuscript instances at once).
# The length cap is a safeguard so the tool bar / tab title doesn't grow unbounded from one long paper name.
LABEL_MAX = 40
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# A high-saturation "700-level" palette with enough contrast on both the dark and light theme backgrounds
# (--bg #14161a / #e9ebef) and under white text (chip text). One is chosen by hashing the label string -
# the same label always gets the same color.
ACCENT_PALETTE = ("#1d4ed8", "#047857", "#be123c", "#6d28d9",
                   "#0e7490", "#c2410c", "#a21caf", "#4d7c0f")

# Every path that touches the pin file goes through this single lock. Without it, a read-modify-write
# race loses most concurrent writes - of 30 pins saved at once, only 2 survived (observed) - the rest
# were clobbered by each other's writes.
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
        return self.state / "pins.jsonl"

    @property
    def pins_md(self) -> Path:
        return self.state / "pins.md"

    @property
    def dropped(self) -> Path:
        return self.state / "pins.dropped.jsonl"

    @property
    def seq(self) -> Path:
        return self.state / "pins.seq"

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
# A single paper repo has several documents - the body, the review response, the cover letter. One viewer
# (one address) switches between them. The pin store (pins.jsonl/pins.seq) is singular - pin numbers must
# be unique across documents so "handle #12" is unambiguous. Build/page images/PDF copy/build history live
# under a per-document folder (Doc.dir). A single request handles a single document, and it's hung off a
# thread-local value (using_doc) - so request code can look at "the current document" without taking a
# parameter, keeping the existing code paths as-is. The build itself (limn/build.py) takes the document as an
# argument; a Doc carries that document's build lock, build state, history lock and src_mtime memo.

DOC_KEY_RE = re.compile(r"[a-z0-9-]{1,24}")
DOC_NAME_MAX = 40
DOCS_MAX = 12
DEFAULT_DOC_KEY = "main"


class Doc:
    """One document. kind is 'tex' (LaTeX, lines traced back via SyncTeX) or 'pdf' (view-only - page/region only).

    legacy=True means a single document started without --doc. The manuscript path/state folder are read
    from C on demand (C.src/C.main/C.state/C.build) - this keeps the legacy state-folder layout working, and
    the regression tests that swap out C keep working too. root=True puts build artifacts at the state
    folder root (the same place as for a single document). Under --doc, only the LaTeX document keyed
    main gets this - so adding documents to a single-document instance keeps the body's build history
    (the source of location estimation) continuous."""

    def __init__(self, key: str, name: str, kind: str = "tex", src: Path = None, main: Path = None,
                 legacy: bool = False, root: bool = None, lock=None, bstate=None, bstate_lock=None,
                 builds_lock=None, mcache=None):
        self.key, self.name, self.kind = key, name, kind
        self._src, self._main, self.legacy = src, main, legacy
        self.root = legacy if root is None else root
        self.lock = lock or threading.Lock()
        self.bstate = bstate if bstate is not None else _fresh_build_state()
        self.bstate_lock = bstate_lock or threading.Lock()
        self.builds_lock = builds_lock or threading.Lock()
        self.mcache = mcache if mcache is not None else [None, 0.0, 0.0]

    @property
    def src(self) -> Path:
        """Build root - the scope copied into the build copy. For view-only, the folder holding the PDF."""
        return C.src if self.legacy else self._src

    @property
    def main(self) -> Path:
        """The main .tex for LaTeX, or the PDF file for view-only."""
        return C.main if self.legacy else self._main

    @property
    def dir(self) -> Path:
        """Per-document state folder - page images, build history, built_at, etc."""
        return C.state if self.root else C.state / "docs" / self.key

    @property
    def build(self) -> Path:
        return C.build if self.legacy else self.dir / "build"

    @property
    def main_rel(self) -> Path:
        try:
            return self.main.relative_to(self.src)
        except ValueError:
            return Path(self.main.name)

    @property
    def out(self) -> Path:
        """The folder where latexmk runs and the PDF comes out. A --doc document runs in the folder holding
        its main .tex (the same as running latexmk there normally would - the build root before '::' is only
        the copy scope). A single document is the build root, as before."""
        return self.build if self.legacy else self.build / self.main_rel.parent

    @property
    def pdf_name(self) -> str:
        """Name of the PDF copy inside the page directory."""
        return self.main.stem + ".pdf"

    @property
    def is_pdf(self) -> bool:
        return self.kind == "pdf"

    def rel_path(self) -> str:
        """Path relative to --manuscript (for display / the pins.md header). Points at the main file."""
        try:
            return str(self.main.resolve().relative_to(C.src.resolve()))
        except (ValueError, OSError, RuntimeError):
            return str(self.main)


def _fresh_build_state() -> dict:
    return {"state": "idle", "phase": None, "started_at": None, "start_ts": None,
            "last_s": None, "pages": 0, "errors": [], "log_tail": "", "built_at": None,
            "seq": 0, "finished_at": None, "last": None, "head": None, "pull": None}


class HTTPError(Exception):
    """The handler turns this directly into a JSON error response."""

    def __init__(self, code: int, msg: str, page=None, **extra):
        super().__init__(msg)
        self.code = code
        self.body = dict({"error": msg}, **extra)
        self.page = page            # (kind, params) for the readable HTML page a browser gets on GET / (error_page_html)


def now_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- Startup preparation

def detect_main(src: Path) -> Path:
    """Find the top-level .tex. If it's ambiguous, don't guess - show the candidates and stop."""
    cands = [p for p in sorted(src.glob("*.tex"))
             if "\\documentclass" in p.read_text(encoding="utf-8", errors="ignore")[:20000]]
    if len(cands) == 1:
        return cands[0]
    how = "found none" if not cands else "found several"
    listing = "\n".join("  - %s" % p.name for p in cands) or "  (none)"
    sys.exit("%s: %s top-level .tex files under %s. Specify one with --main.\n%s" % (APP_NAME, how, src, listing))


def free_port(start: int = 18300, end: int = 18400) -> int:
    """Find a free port. The point is not to steal someone else's port."""
    for p in range(start, end):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    sys.exit("No free port in the %d-%d range. Specify one with --port." % (start, end))


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


def clean_label(v) -> str:
    """Validate a label. Newlines and excessive length are blocked here since they'd break the tool bar / tab title."""
    v = "" if v is None else str(v).strip()
    v = " ".join(v.split())         # collapse newlines/tabs/repeated whitespace to a single space
    if not v:
        v = "원고"
    if len(v) > LABEL_MAX:
        sys.exit("--label must be %d characters or fewer: %r" % (LABEL_MAX, v))
    return v


def pick_accent(label: str) -> str:
    """Pick one from the palette by hashing the label string - the same label always gets the same color."""
    idx = int(hashlib.sha1(label.encode("utf-8")).hexdigest(), 16) % len(ACCENT_PALETTE)
    return ACCENT_PALETTE[idx]


def valid_accent(v) -> bool:
    return isinstance(v, str) and ACCENT_RE.fullmatch(v) is not None


def favicon_href(label: str, accent: str) -> str:
    """An SVG data URL with the label's first character inside an accent-colored circle. Special characters inside data: are quote-encoded."""
    ch = (label.strip()[:1] or "?").upper()
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
           '<circle cx="16" cy="16" r="16" fill="%s"/>'
           '<text x="16" y="21" text-anchor="middle" font-family="sans-serif" font-size="16" '
           'font-weight="700" fill="#ffffff">%s</text></svg>') % (accent, html.escape(ch, quote=True))
    return "data:image/svg+xml," + quote(svg, safe="")


def build_html(label: str, accent: str) -> str:
    """Fills in the __LABEL__/__ACCENT__/__FAVICON_HREF__ placeholders of the viewer HTML template.

    Depends on run arguments (label/accent), so it's called after argparse (in main()) - unlike
    __PDFJS_VERSION__, which is fixed at module-load time, this one only has a value once C is filled in."""
    out = HTML.replace("__LABEL__", html.escape(label, quote=True))
    out = out.replace("__LABEL_INITIAL__", html.escape((label.strip()[:1] or "?").upper(), quote=True))
    out = out.replace("__ACCENT__", accent)
    out = out.replace("__FAVICON_HREF__", favicon_href(label, accent))
    return out


# ---------------------------------------------------------------- Page-image version directories
#
# The build - page directories, build state, the LaTeX build, history, fingerprint - lives in limn/build.py and
# takes the document and the settings it needs as arguments (docs/handbook/build-sync.md). The functions below
# with the old names are shells: they bind the request's document (cur_doc()) and the run arguments (C) until
# the HTTP layer passes them itself (docs/handbook/code-style-roadmap.md stage 6).

def cur_pages() -> Path:
    """The current document's page-image directory on screen (limn.build.cur_pages)."""
    return build.cur_pages(cur_doc())


def pages_dir_for(name) -> Path:
    """The current document's page directory the browser is looking at, or the current one (limn.build.pages_dir_for)."""
    return build.pages_dir_for(cur_doc(), name)


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


def build_pdf(name) -> Path:
    """The PDF GET /pdf?build=<name> serves for the current document, or None (limn.build.build_pdf)."""
    return build.build_pdf(cur_doc(), name)


def cur_pdf(pdir: Path = None) -> Path:
    """The current document's PDF matched to the page images (limn.build.cur_pdf)."""
    return build.cur_pdf(cur_doc(), pdir)


def source_newer(name: str = None) -> float:
    """Seconds the current document's manuscript is newer than that build (default: the one on screen), else 0.0 (limn.build.source_newer)."""
    return build.source_newer(cur_doc(), C.state, name)


def migrate_pages() -> None:
    """Turn the current document's legacy page layout into a version directory (limn.build.migrate_pages)."""
    build.migrate_pages(cur_doc())


# ---------------------------------------------------------------- Build

def build_state_snapshot() -> dict:
    """The current document's build state as GET /api/build returns it (limn.build.state_snapshot)."""
    return build.state_snapshot(cur_doc())


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


def build_all() -> dict:
    """Rebuild the current document's PDF (synchronous). If it is already building, returns busy without waiting (limn.build.build_now)."""
    return build.build_now(cur_doc(), _build_tracked)


def build_async() -> dict:
    """POST /api/rebuild?async=1 for the current document: start the tracked build on a daemon thread (limn.build.build_in_background)."""
    D = cur_doc()

    def tracked() -> dict:
        """The build thread sees the same document: the steps _build_tracked binds (and tests replace) still read cur_doc()."""
        with using_doc(D):
            return _build_tracked()
    return build.build_in_background(D, tracked, now_str())


def _build_tracked() -> dict:
    """One tracked build of the current document: LaTeX (_build) or, for view-only, the page render (_render_pdf_doc) (limn.build.run_tracked)."""
    D = cur_doc()
    return build.run_tracked(D, C.state, _render_pdf_doc if D.is_pdf else _build, now_str())


def finish_build(res: dict, src_mtime_for_build) -> None:
    """Record a finished build of the current document in its history and build state (limn.build.finish_build)."""
    build.finish_build(cur_doc(), res, src_mtime_for_build)


# ---------------------------------------------------------------- Build history (builds.json) and manuscript fingerprint
#
# What each build records and why location estimation (.est) needs it: limn/build.py §Build history.

def load_builds() -> dict:
    """The current document's build history {seq, builds, last, by} (limn.build.load_builds)."""
    return build.load_builds(cur_doc())


def seed_builds() -> None:
    """Add the current document's existing build to its history and restore its last result (limn.build.seed_builds)."""
    build.seed_builds(cur_doc(), C.state)


def _read_built_at():
    """When the current document's page images were committed, or None (limn.build.read_built_at)."""
    return build.read_built_at(cur_doc())


def _read_head():
    """The short git hash the current document's page images came from, or None (limn.build.read_head)."""
    return build.read_head(cur_doc())


# ---------------------------------------------------------------- --git-pull (§P0c-E)
#
# Fast-forwards the manuscript repo to the remote main before the rebuild's copy step. A co-author merging a
# PR wasn't reflected on the server-side checkout - the viewer kept showing the old manuscript. Even on
# failure (dirty tree, diverged, no upstream), the build itself continues with the current checkout - a
# pull is nice to have, not a build prerequisite.

def _git(args: list, cwd, timeout: int = GIT_PULL_TIMEOUT):
    """Run git without a shell. Never puts user input into the args. Returns (returncode, stdout, stderr).
    Timeout and exec failure are both distinguished by returncode=None."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=str(cwd), timeout=timeout, capture_output=True, text=True, check=False)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.TimeoutExpired, OSError):
        return None, "", ""


def revision_scope(D: Doc):
    """Returns a Git pathspec scoped to just the manuscript text inside the chosen main .tex's folder.

    D.src is the build-copy scope, so multiple documents can share the same root. The change history must
    be filtered to D.main.parent, or commits from the body, highlights, and cover letter get mixed together."""
    if D.is_pdf:
        return None
    root = D.main.resolve().parent
    try:
        root.relative_to(D.src.resolve())
    except ValueError:
        return None
    rc, top, _ = _git(["-C", str(root), "rev-parse", "--show-toplevel"], root)
    if rc != 0 or not top.strip():
        return None
    repo = Path(top.strip()).resolve()
    try:
        prefix = root.relative_to(repo).as_posix()
    except ValueError:
        return None
    prefix = "" if prefix == "." else prefix + "/"
    # Git :(glob) ** only matches subfolders, so root files are included via a separate pattern.
    exts = ("tex", "bib", "sty", "cls", "bst")
    paths = [":(glob)%s*.%s" % (prefix, ext) for ext in exts]
    paths += [":(glob)%s**/*.%s" % (prefix, ext) for ext in exts]
    return repo, paths


def revision_history(D: Doc) -> dict:
    scope = revision_scope(D)
    if scope is None:
        return {"available": False, "revisions": []}
    repo, paths = scope
    rc, out, _ = _git(["-C", str(repo), "log", "-12", "--format=%H%x1f%cs%x1f%s", "--"] + paths, repo)
    if rc != 0:
        return {"available": False, "revisions": []}
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) == 3 and REVISION_ID_RE.fullmatch(parts[0]):
            rows.append({"id": parts[0], "date": parts[1], "subject": parts[2][:180]})
    return {"available": True, "revisions": rows}


def revision_diff(D: Doc, commit: str, pin: int | None = None) -> dict:
    """The selected commit's unified diff. With pin (v0.3), an additive `scope` says which of its hunks belong to that pin
    (scope_payload); the whole-commit `diff` is returned unchanged either way."""
    if not REVISION_ID_RE.fullmatch(commit or ""):
        raise HTTPError(400, "올바른 커밋 ID가 아닙니다.")
    scope = revision_scope(D)
    if scope is None:
        raise HTTPError(404, "이 문서는 원고 변경사항을 볼 수 없습니다.")
    repo, paths = scope
    # Only read commits that appear in the current document's recent list. Never exposes arbitrary Git objects or another document's history.
    revisions = revision_history(D)["revisions"]
    if commit not in {row["id"] for row in revisions}:
        raise HTTPError(404, "현재 문서의 최근 커밋이 아닙니다.")
    cmd = ["git", "-C", str(repo), "show", "--format=", "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=3",
           commit, "--"] + paths
    try:
        with subprocess.Popen(cmd, cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
            chunks, size = [], 0
            deadline = time.monotonic() + GIT_PULL_TIMEOUT
            try:
                with selectors.DefaultSelector() as sel:
                    sel.register(proc.stdout, selectors.EVENT_READ)
                    while size <= REVISION_DIFF_MAX:
                        ready = sel.select(max(0, deadline - time.monotonic()))
                        if not ready:
                            raise subprocess.TimeoutExpired(cmd, GIT_PULL_TIMEOUT)
                        part = os.read(proc.stdout.fileno(), min(65536, REVISION_DIFF_MAX + 1 - size))
                        if not part:
                            break
                        chunks.append(part)
                        size += len(part)
                too_large = size > REVISION_DIFF_MAX
                if too_large:
                    proc.kill()
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
                proc.wait()
                raise
            if proc.returncode != 0 and not too_large:
                raise HTTPError(404, "변경사항을 읽지 못했습니다.")
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPError(503, "변경사항을 읽지 못했습니다.") from None
    out = {"id": commit, "diff": b"".join(chunks)[:REVISION_DIFF_MAX].decode("utf-8", errors="replace"),
           "truncated": too_large}
    if pin is not None:
        base, rows = revision_first_parent(repo, commit), [public(r) for r in read_pins()[0]]   # current paths (ADR-0006)
        sc = (revision_pin_scope(D, rows, repo, paths, base, commit, pin, revisions, SCOPE_CACHE) if base  # may raise ScopeRejected
              else PinScope(scope_pin_record(rows, D, pin)["id"], "commit", "none", 0, 0))
        out["scope"] = scope_payload(sc)
    return out


# ---------------------------------------------------------------- Pin-scoped changes (docs/adr/0005-pin-scoped-changes.md)
#
# [변경 보기] showed the whole commit linked to a pin. When one commit fixes several pins, a reviewer could not tell which
# change belonged to which pin. The commit's -U0 hunks ("blocks") are now attributed to the pin: the agent's recorded
# `changes` (new-side line ranges) pick them, or - for a pin without it - the pin's own range mapped through the commit
# does. The source diff then shows only those blocks, and the comparison PDF compiles old + only those blocks.
# Everything from here to "the git edge" is pure (coding rule R1): bytes and records in, values out - no file, clock, git
# or HTTP. Expected refusals are ScopeRejected with a reason; the HTTP layer maps reasons in one table (SCOPE_REJECTIONS).

SCOPE_CONTEXT = 3                     # context lines around a scoped hunk, git's default
SCOPE_FILES_MAX = 60                  # a commit touching more manuscript files than this stays a whole-commit view
SCOPE_BYTES_MAX = 16 * 1024 * 1024    # both sides of every changed file together
SCOPE_CACHE_KEEP = 32                 # entries: counts, block key and the two patches, each cut at REVISION_DIFF_MAX + 1 bytes
SCOPE_SLOTS = 2                       # scope computations (cache misses) reading git at once; more wait, then show whole
SCOPE_SECONDS_MAX = 60                # reading one commit's files for scoping, all git calls together
_U0_HUNK_RE = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


class ScopeRejected(Exception):
    """An expected refusal while scoping a commit to one pin. reason is one of the keys of SCOPE_REJECTIONS, which the
    HTTP layer (Handler._run) and the build worker turn into the status code, Korean message and API reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Block(NamedTuple):
    """One -U0 hunk of a file, 0-based. old_lo is where the old span starts; for a pure insertion (old_n == 0) it is the
    old index the new lines go before. new_lo is the same on the new side."""
    old_lo: int
    old_n: int
    new_lo: int
    new_n: int


class FileChange(NamedTuple):
    """One file of a commit. Paths are repo-relative POSIX; old_path is None for an added file, new_path for a deleted one.
    old/new are the file's lines as bytes, each keeping its newline (git_lines). A pure rename, a mode change, a
    symlink or submodule entry and a binary file have no blocks - they are shown as a header and never attributed to
    a pin. modes are git's (old, new) file modes ("" for a side that does not exist)."""
    old_path: str | None
    new_path: str | None
    old: tuple[bytes, ...]
    new: tuple[bytes, ...]
    blocks: tuple[Block, ...]
    binary: bool
    modes: tuple[str, str] = ("100644", "100644")


class RawEntry(NamedTuple):
    """One entry of `git diff --raw -z`: paths as in FileChange, both blob ids (all zeros for a missing side), the two
    modes, and text - False for a symlink (120000) or submodule (160000) side, which is never read as lines."""
    old_path: str | None
    new_path: str | None
    old_oid: str
    new_oid: str
    modes: tuple[str, str]
    text: bool


ScopeMode = Literal["pin", "commit"]
ScopeSource = Literal["changes", "inferred", "none"]


class Anchor(NamedTuple):
    """A pin's anchor (anchor_of): the normalised first and last non-comment lines and their distance from lo/hi."""
    head: str
    tail: str
    head_off: int
    tail_off: int


class PinFacts(NamedTuple):
    """What scope attribution reads from a pin record (pin_facts): its id, its file relative to the repository (None
    for a view-only PDF pin or a file outside the repository), its range (None when the record has no int lo/hi),
    whether sync lost it, and its anchor if it has a usable one."""
    id: int
    rel: str | None
    lo: int | None
    hi: int | None
    stale: bool
    anchor: Anchor | None


BlockId = tuple[int, int]                         # (index into the files, index into that file's blocks)
ScopeItem = tuple[str, str, int, int, int, int]   # (old path or "", new path or "", *Block) - see scope_key()


class Placement(NamedTuple):
    """Where a pin's range may sit on one side of a commit: side "new" or "old", 1-based lines in git's numbering."""
    side: str
    lo: int
    hi: int


class RepoRange(NamedTuple):
    """A recorded change as attribution sees it: the repo-relative POSIX path and its new-side lines, 1 ≤ lo ≤ hi."""
    path: str
    lo: int
    hi: int


class ChangeRecord(TypedDict):
    """One item of a pin record's stored `changes` (api.md §핀 레코드 스키마): an absolute path and 1 ≤ lo ≤ hi."""
    file: str
    lo: int
    hi: int


class CloseChange(NamedTuple):
    """One validated range of a close body's `changes` (clean_close_changes), immutable: an absolute, resolved path
    inside the manuscript folder, and the new-side lines 1 ≤ lo ≤ hi ≤ CHANGE_LINE_MAX the agent changed for the pin.
    (A NamedTuple rather than a dataclass: the tests load server.py outside sys.modules, where dataclasses cannot
    resolve postponed annotations.)"""
    file: str
    lo: int
    hi: int

    def record(self) -> ChangeRecord:
        """The JSON shape stored on the pin record."""
        return {"file": self.file, "lo": self.lo, "hi": self.hi}


Changes = tuple[CloseChange, ...]


class ScopeMeta(TypedDict):
    """The additive fields of a revision-build status for a pin request (api.md §핀 단위 변경 보기). Never stored in
    status.json: several pins and pin-less requests share the whole-commit comparison."""
    scope: ScopeMode
    pin: int
    source: ScopeSource
    hunks: int
    other: int


class _ScopeCounts(TypedDict):
    """The fields of ScopePayload that are always present (a TypedDict base, since 3.10 has no NotRequired)."""
    pin: int
    mode: ScopeMode
    source: ScopeSource
    hunks: int
    other: int


class ScopePayload(_ScopeCounts, total=False):
    """The additive `scope` object of GET /api/revision-diff?pin=; the patches and their truncation flags only in mode
    "pin"."""
    diff: str
    other_diff: str
    truncated: bool
    other_truncated: bool


class ScopeWrite(NamedTuple):
    """One file of the synthetic "old + this pin's blocks" tree: path relative to the build root, and the bytes to write
    there, or None to remove the file (the pin's block deletes it)."""
    rel: str
    data: bytes | None


class PinScope(NamedTuple):
    """How one pin sees one commit. mode "pin" means the pin owns some but not all of the commit; "commit" means the
    whole commit is shown (it is all the pin's, none of it is, or scoping was not possible). source says what picked
    the blocks: "changes" (recorded at close), "inferred" (the pin's range) or "none"."""
    pin: int
    mode: ScopeMode
    source: ScopeSource
    hunks: int
    other: int
    blocks: tuple[ScopeItem, ...] = ()   # scope_key() of the pin's blocks, in mode "pin" only
    diff: bytes = b""                    # the two patches (UTF-8, cut at REVISION_DIFF_MAX + 1 bytes), in mode "pin" only
    other_diff: bytes = b""


def git_lines(data: bytes) -> tuple[bytes, ...]:
    """Split the way git counts lines - on "\\n" only, keeping it; a last line without one stays as it is."""
    parts = data.split(b"\n")
    return tuple([p + b"\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else []))


def parse_u0_blocks(patch: bytes) -> list[Block]:
    """The blocks of one file's `git diff -U0` output. Only the @@ headers are read: the lines themselves come from
    the two blobs, so a missing final newline or odd bytes never have to be reconstructed from the patch."""
    out = []
    for m in _U0_HUNK_RE.finditer(patch):
        a, c = int(m[1]), int(m[3])
        b = 1 if m[2] is None else int(m[2])
        d = 1 if m[4] is None else int(m[4])
        out.append(Block(a if b == 0 else a - 1, b, c if d == 0 else c - 1, d))
    return out


def touch_range(lo0: int, n: int) -> tuple[int, int]:
    """The 1-based lines a block touches on one side. An empty side (pure insertion or deletion) touches the lines on
    both sides of the point, so a range naming the line before or after a deletion still names the deletion."""
    return (lo0 + 1, lo0 + n) if n > 0 else (max(1, lo0), lo0 + 1)


def _hits(rng: tuple[int, int], lo: int, hi: int) -> bool:
    """Whether the inclusive line ranges rng and lo..hi share at least one line (overlap only - no nearby lines,
    ADR-0005 §3: attributing a neighbour's change is worse than showing the whole commit)."""
    return rng[0] <= hi and rng[1] >= lo


def pin_range_candidates(f: FileChange, pin: PinFacts) -> list[Placement]:
    """Where the pin's range may sit in this commit, best first; the pin must have a range (lo/hi not None).

    A closed pin keeps the lines of its last sync, and nothing records which version that was: the commit's new side
    when the anchor survived the fix, the old side when the fix rewrote the anchored text (sync lost it and kept the
    pre-edit lines) or when the pin was closed before the server's checkout reached the commit. So the anchor is
    looked up on both sides near the recorded range, with the same rule as sync_all(), and the side where it sits
    closer to the recorded line comes first (the recorded number is in that side's coordinates; ties prefer the new
    side). A generic anchor such as \\begin{equation} is found on both sides - the distance is what tells them apart.
    The raw range comes last: old side if the pin went stale, else new."""
    lo, hi, anc, found = pin.lo, pin.hi, pin.anchor, []
    sides = {"new": _pin_lines(f.new), "old": _pin_lines(f.old)}
    if anc is not None:
        ho, to = anc.head_off, anc.tail_off
        for rank, side in enumerate(("new", "old")):
            texts, to_git = sides[side]
            if not texts:
                continue
            nl = [norm(t) for t in texts]
            head = find_line(nl, anc.head, lo + ho)
            if head is None:
                continue
            a = max(1, head - ho)
            tail = find_line(nl, anc.tail, hi - to + (a - lo))
            b = max(a, min(len(texts), tail + to if tail is not None and tail >= head else a + (hi - lo)))
            found.append((abs(a - lo), rank, Placement(side, to_git(a), to_git(b))))
    raw = "old" if pin.stale else "new"
    return [c for _, _, c in sorted(found)] + [Placement(raw, sides[raw][1](lo), sides[raw][1](hi))]


def _pin_lines(lines: tuple[bytes, ...]) -> tuple[list[str], Callable[[int], int]]:
    """(texts, to_git) for one side. A pin's lines are numbered by str.splitlines() (tex_lines), git's by "\\n" only; they
    differ after a form feed, a lone CR, U+2028 and the like. texts are the splitlines lines (what anchors match) and
    to_git maps a 1-based splitlines line number to git's line number (identity when the two agree)."""
    text = b"".join(lines).decode("utf-8", "replace")
    texts = text.splitlines()
    if len(texts) == len(lines):
        return texts, lambda n: n
    starts, line = [], 1
    for piece in text.splitlines(keepends=True):
        starts.append(line)
        line += piece.count("\n")
    return texts, lambda n: starts[min(max(n, 1), len(starts)) - 1] if starts else n


def attribute_blocks(files: Sequence[FileChange], pin: PinFacts,
                     changes: Sequence[RepoRange]) -> tuple[ScopeSource, set[BlockId]]:
    """(source, block ids) - the blocks of this commit that belong to the pin.

    changes are the pin's recorded new-side ranges for this commit (recorded_changes). If none of them hits a block
    (a wrong path, lines the commit did not touch) the pin's own range decides (pin_range_candidates; pin.rel is its
    repo-relative file), and if that hits nothing either the answer is ("none", set()) and the caller shows the whole
    commit as before."""
    chosen = set()
    for fi, f in enumerate(files):
        if f.new_path is None:
            continue
        for rel, lo, hi in changes:
            if rel == f.new_path:
                chosen |= {(fi, bi) for bi, b in enumerate(f.blocks) if _hits(touch_range(b.new_lo, b.new_n), lo, hi)}
    if chosen:
        return "changes", chosen
    if pin.rel and pin.lo is not None and pin.hi is not None:
        for fi, f in enumerate(files):
            if pin.rel not in (f.old_path, f.new_path):
                continue
            for side, lo, hi in pin_range_candidates(f, pin):     # the first placement that meets a change wins
                hit = {(fi, bi) for bi, b in enumerate(f.blocks)
                       if _hits(touch_range(b.new_lo, b.new_n) if side == "new" else touch_range(b.old_lo, b.old_n), lo, hi)}
                if hit:
                    chosen |= hit
                    break
    return ("inferred" if chosen else "none"), chosen


def _patch_line(prefix: str, line: bytes) -> list[str]:
    """One diff body line for a file line (prefix " ", "-" or "+"), without its newline or a trailing CR; a line that
    has no newline (the file's last) is followed by git's "\\ No newline at end of file" marker. Undecodable bytes
    become U+FFFD - the patch is for display."""
    text = line.decode("utf-8", "replace")
    if text.endswith("\n"):
        return [prefix + text[:-1].rstrip("\r")]
    return [prefix + text.rstrip("\r"), "\\ No newline at end of file"]


def _file_header(f: FileChange) -> list[str]:
    """git-style header lines for one file of a scoped patch: diff --git, new/deleted/rename lines, and either the
    ---/+++ pair (when hunks follow) or the "Binary files ... differ" line. The viewer's revisionFiles() splits files
    on "diff --git" and names them after " b/"."""
    a, b = f.old_path or f.new_path, f.new_path or f.old_path
    out = ["diff --git a/%s b/%s" % (a, b)]
    if f.old_path is None:
        out.append("new file mode " + (f.modes[1] or "100644"))
    elif f.new_path is None:
        out.append("deleted file mode " + (f.modes[0] or "100644"))
    else:
        if f.modes[0] != f.modes[1]:
            out += ["old mode " + f.modes[0], "new mode " + f.modes[1]]
        if a != b:
            out += ["rename from " + a, "rename to " + b]
    old_name = "/dev/null" if f.old_path is None else "a/" + a
    new_name = "/dev/null" if f.new_path is None else "b/" + b
    if f.binary:
        out.append("Binary files %s and %s differ" % (old_name, new_name))
    elif f.blocks:
        out += ["--- " + old_name, "+++ " + new_name]
    return out


def _hunk(f: FileChange, i: int, j: int) -> list[str]:
    """One unified hunk for blocks i..j of f (adjacent in f.blocks). Context stops at any neighbouring block, so a
    change that is not in this hunk never shows up as context; the new-side numbers count every block before i -
    they are the commit's real line numbers, the same ones the whole-commit diff and the pin's range use."""
    bl = f.blocks
    start = max(bl[i - 1].old_lo + bl[i - 1].old_n if i else 0, bl[i].old_lo - SCOPE_CONTEXT)
    end = min(bl[j + 1].old_lo if j + 1 < len(bl) else len(f.old), bl[j].old_lo + bl[j].old_n + SCOPE_CONTEXT, len(f.old))
    shift = sum(b.new_n - b.old_n for b in bl[:i])
    body, oc, nc, pos = [], 0, 0, start
    for b in bl[i:j + 1]:
        for ln in f.old[pos:b.old_lo]:
            body += _patch_line(" ", ln)
        oc += b.old_lo - pos
        nc += b.old_lo - pos
        for ln in f.old[b.old_lo:b.old_lo + b.old_n]:
            body += _patch_line("-", ln)
        for ln in f.new[b.new_lo:b.new_lo + b.new_n]:
            body += _patch_line("+", ln)
        oc += b.old_n
        nc += b.new_n
        pos = b.old_lo + b.old_n
    for ln in f.old[pos:end]:
        body += _patch_line(" ", ln)
    oc += max(0, end - pos)
    nc += max(0, end - pos)
    return ["@@ -%d,%d +%d,%d @@" % (start + 1 if oc else start, oc, start + shift + 1 if nc else start + shift, nc)] + body


def scoped_patch(files: Sequence[FileChange], chosen: AbstractSet[BlockId], want: bool) -> tuple[str, int]:
    """(unified patch text, number of places) for the blocks whose membership in chosen equals want. A place is one
    changed spot (a block); blocks of the same side within 2 x context of each other with nothing between them share
    one hunk, like git. Files without blocks (pure rename, mode change, binary) are one place on the "other" side."""
    out, places = [], 0
    for fi, f in enumerate(files):
        if not f.blocks:
            if not want:
                out += _file_header(f)
                places += 1
            continue
        pick = [bi for bi in range(len(f.blocks)) if ((fi, bi) in chosen) == want]
        if not pick:
            continue
        out += _file_header(f)
        groups = []
        for bi in pick:
            prev = f.blocks[bi - 1] if bi else None
            if groups and groups[-1][-1] == bi - 1 and f.blocks[bi].old_lo - (prev.old_lo + prev.old_n) <= 2 * SCOPE_CONTEXT:
                groups[-1].append(bi)
            else:
                groups.append([bi])
        for g in groups:
            out += _hunk(f, g[0], g[-1])
        places += len(pick)
    return "".join(line + "\n" for line in out), places


def apply_blocks(f: FileChange, chosen: AbstractSet[int]) -> bytes:
    """The file's old bytes with only the chosen blocks (indices into f.blocks) replaced by their new lines - the
    synthetic "old + this pin's changes" version the pin-scoped comparison PDF compiles."""
    out, pos = [], 0
    for bi, b in enumerate(f.blocks):
        if bi in chosen:
            out += f.old[pos:b.old_lo]
            out += f.new[b.new_lo:b.new_lo + b.new_n]
            pos = b.old_lo + b.old_n
    out += f.old[pos:]
    return b"".join(out)


def scope_key(files: Sequence[FileChange], chosen: AbstractSet[BlockId]) -> tuple[ScopeItem, ...]:
    """The chosen blocks as plain values (path pair + block), sorted - the part of a comparison's identity that says
    which hunks it applies. It does not depend on file order or indices, so it is stable across requests."""
    return tuple(sorted((files[fi].old_path or "", files[fi].new_path or "") + tuple(files[fi].blocks[bi])
                        for fi, bi in chosen))


def pin_scope(files: Sequence[FileChange] | None, pin: PinFacts, changes: Sequence[RepoRange]) -> PinScope:
    """The decision for one pin and one commit's files (None = the commit could not be read for scoping, which
    shows the whole commit). Mode "pin" only when the pin owns some but not all places of the commit. The patches
    are kept cut at REVISION_DIFF_MAX + 1 bytes - one byte more than a response sends, so truncation still shows."""
    if files is None:
        return PinScope(pin.id, "commit", "none", 0, 0)
    source, chosen = attribute_blocks(files, pin, changes)
    mine_text, mine = scoped_patch(files, chosen, True)
    other_text, other = scoped_patch(files, chosen, False)
    if not (chosen and other):
        return PinScope(pin.id, "commit", source, mine, other)
    cut = REVISION_DIFF_MAX + 1
    return PinScope(pin.id, "pin", source, mine, other, scope_key(files, chosen),
                    mine_text.encode("utf-8", "replace")[:cut], other_text.encode("utf-8", "replace")[:cut])


def pin_facts(r: dict, rel: str | None) -> PinFacts:
    """Parses a pin record (already accepted by valid_rec) into what attribution reads. rel is its file relative to
    the repository, resolved by the caller; an anchor without a non-empty head counts as none."""
    anc = r.get("anchor") if isinstance(r.get("anchor"), dict) else {}
    head = anc.get("head")
    anchor = (Anchor(head, anc.get("tail") if isinstance(anc.get("tail"), str) else "", _off(anc.get("head_off")),
                     _off(anc.get("tail_off"))) if isinstance(head, str) and head else None)
    lo, hi = r.get("lo"), r.get("hi")
    return PinFacts(r["id"], rel, lo if _is_int(lo) else None, hi if _is_int(hi) else None, bool(r.get("stale")), anchor)


_REF_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.ASCII)
_REF_PR_RE = re.compile(r"#(\d+)", re.ASCII)


def ref_commit(ref: object, revisions: Sequence[dict]) -> str | None:
    """The commit a close reference names among revisions ([{id, subject}], newest first) - the viewer's
    matchRevision() rule, kept identical (a test runs both): the first 7-40 hex token that prefixes a commit id,
    else the first #N found in a subject as "(#N)", "pull request #N" or "#N" (the squash or merge commit)."""
    ref = ref if isinstance(ref, str) else ""
    for tok in _REF_SHA_RE.findall(ref):
        for r in revisions:
            if r["id"].startswith(tok):
                return r["id"]
    for n in _REF_PR_RE.findall(ref):
        rx = re.compile(r"\(#%s\)|pull request #%s\b|#%s\b" % (n, n, n), re.ASCII)
        for r in revisions:
            if rx.search(r.get("subject") or ""):
                return r["id"]
    return None


def recorded_changes(pin: dict, head: str, revisions: Sequence[dict]) -> tuple[ChangeRecord, ...]:
    """The pin's stored `changes` that apply to commit head: none unless changes_at equals done_at (a 0.2.2 server,
    after a rollback, neither clears nor writes them, so an older close's set may still be on the record) and head is
    the commit its close_ref names (ref_commit) - the lines were recorded for that commit, and on any other commit
    they would select another pin's fix (review M1). Items of the wrong shape are skipped."""
    if pin.get("changes_at") != pin.get("done_at") or ref_commit(pin.get("close_ref"), revisions) != head:
        return ()
    return tuple(c for c in (pin.get("changes") or []) if _valid_changes([c]))


def scope_meta(sc: PinScope) -> ScopeMeta:
    """The per-request status fields of a pin's comparison PDF (added to every build status answer, never stored)."""
    return {"scope": sc.mode, "pin": sc.pin, "source": sc.source, "hunks": sc.hunks, "other": sc.other}


def scope_payload(sc: PinScope) -> ScopePayload:
    """The additive `scope` object of GET /api/revision-diff?pin=. The two patches are only sent in mode "pin", each cut
    at REVISION_DIFF_MAX bytes like the whole-commit diff, with truncated / other_truncated saying so."""
    out: ScopePayload = {"pin": sc.pin, "mode": sc.mode, "source": sc.source, "hunks": sc.hunks, "other": sc.other}
    if sc.mode == "pin":
        out["diff"] = sc.diff[:REVISION_DIFF_MAX].decode("utf-8", "ignore")
        out["other_diff"] = sc.other_diff[:REVISION_DIFF_MAX].decode("utf-8", "ignore")
        out["truncated"] = len(sc.diff) > REVISION_DIFF_MAX
        out["other_truncated"] = len(sc.other_diff) > REVISION_DIFF_MAX
    return out


def plan_scope_writes(files: Sequence[FileChange] | None, scope: Sequence[ScopeItem], source: str) -> list[ScopeWrite]:
    """The files to write into an old-side snapshot so it becomes old + only the scope's blocks.

    source is the build root relative to the repo ("." for the root); files outside it are not part of the compiled
    document and are skipped. Files keep their old names - a rename that belongs to the pin is applied as an edit in
    place, so the old main still finds what it \\inputs; an added file is written, a deleted one removed.
    Raises ScopeRejected: "scope_unreadable" (files is None), "unsafe_path" (a path that could leave the snapshot),
    "scope_mismatch" (a block of the scope is not in the commit any more)."""
    if files is None:
        raise ScopeRejected("scope_unreadable")
    want, found, out = set(scope), set(), []
    prefix = "" if source == "." else source + "/"
    for f in files:
        idx = {bi for bi, b in enumerate(f.blocks) if ((f.old_path or "", f.new_path or "") + tuple(b)) in want}
        if not idx:
            continue
        found |= {(f.old_path or "", f.new_path or "") + tuple(f.blocks[bi]) for bi in idx}
        name = f.old_path if f.old_path is not None else f.new_path
        if not name.startswith(prefix):
            continue
        rel = name[len(prefix):]
        if (not rel or rel.startswith("/") or "\\" in rel or any(ord(c) < 32 for c in rel)
                or any(part in ("", ".", "..", ".git") for part in rel.split("/"))):
            raise ScopeRejected("unsafe_path")
        out.append(ScopeWrite(rel, None if f.new_path is None else apply_blocks(f, idx)))
    if found != want:
        raise ScopeRejected("scope_mismatch")
    return out


_TEXT_MODES = ("100644", "100755")


def parse_raw_entries(raw: bytes) -> list[RawEntry]:
    """The entries of `git diff --raw -z --abbrev=40` output. A side whose mode is not a regular file (symlink
    120000, submodule 160000) makes the entry non-text. Raises ValueError or UnicodeError on output it cannot read
    (a non-UTF-8 path included); revision_changes() then shows the whole commit."""
    tokens, out, i = raw.split(b"\0"), [], 0
    while i < len(tokens):
        meta = tokens[i]
        if not meta.startswith(b":"):
            i += 1
            continue
        old_mode, new_mode, old_oid, new_oid, status = meta[1:].decode("ascii").split()
        n = 2 if status[:1] in ("R", "C") else 1
        names = [t.decode("utf-8") for t in tokens[i + 1:i + 1 + n]]
        if len(names) != n:
            raise ValueError("truncated raw entry")
        i += 1 + n
        old_path = None if status[:1] == "A" else names[0]
        new_path = None if status[:1] == "D" else names[-1]
        modes = ("" if old_path is None else old_mode, "" if new_path is None else new_mode)
        text = all(m in _TEXT_MODES for m in modes if m)
        out.append(RawEntry(old_path, new_path, old_oid, new_oid, modes, text))
    return out


def _valid_changes(v: object) -> bool:
    """Whether v has the stored shape of `changes` - a list of {file: str, lo: int, hi: int}. valid_rec() treats a
    record failing this as a broken line; recorded_changes() skips such items."""
    return isinstance(v, list) and all(isinstance(c, dict) and isinstance(c.get("file"), str) and _is_int(c.get("lo"))
                                       and _is_int(c.get("hi")) for c in v)


# -------- the git edge of pin scoping (reads git and pins.jsonl; decisions above)

class ScopeCache:
    """Pin scopes already decided, keyed by (repo, base, head, pin facts) - commits are immutable, so an entry stays
    right until evicted (oldest first beyond keep). Holds only complete answers: a commit that could not be read
    (timeout, size) is not stored, so the next request tries again. slot() bounds how many cache misses read git at
    once; waiting longer than SCOPE_SECONDS_MAX gives up (the caller shows the whole commit, uncached)."""

    def __init__(self, keep: int = SCOPE_CACHE_KEEP, slots: int = SCOPE_SLOTS):
        self._rows: dict = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(slots)
        self.keep = keep

    def get(self, key: tuple) -> PinScope | None:
        """The stored scope for key, or None."""
        with self._lock:
            return self._rows.get(key)

    def put(self, key: tuple, value: PinScope) -> None:
        """Stores value, evicting the oldest entry when full."""
        with self._lock:
            if key not in self._rows and len(self._rows) >= self.keep:
                self._rows.pop(next(iter(self._rows)))
            self._rows[key] = value

    @contextlib.contextmanager
    def slot(self):
        """Yields True while holding one of the git-reading slots, or False after waiting SCOPE_SECONDS_MAX."""
        got = self._slots.acquire(timeout=SCOPE_SECONDS_MAX)
        try:
            yield got
        finally:
            if got:
                self._slots.release()

    def values(self) -> list[PinScope]:
        """The stored scopes (tests and diagnostics)."""
        with self._lock:
            return list(self._rows.values())

    def clear(self) -> None:
        """Forgets every stored scope."""
        with self._lock:
            self._rows.clear()


SCOPE_CACHE = ScopeCache()           # the server's one instance; revision_diff/revision_spec pass it explicitly


def _blob(repo: Path, oid: str, budget: list[int]) -> bytes:
    """The bytes of one git blob, charged against budget[0] (bytes left for the whole commit, updated in place).
    Raises ValueError when git fails or the budget runs out; revision_exec's HTTPError on timeout/size passes up -
    revision_changes() turns both into "not scoped"."""
    rc, data, _ = revision_exec(["git", "cat-file", "blob", oid], repo, 15, budget[0] + 4096)
    if rc != 0:
        raise ValueError("unreadable blob")
    budget[0] -= len(data)
    if budget[0] < 0:
        raise ValueError("too large")
    return data


def revision_changes(repo: Path, base: str, head: str, paths: Sequence[str]) -> list[FileChange] | None:
    """The commit's manuscript files as FileChange values (renames detected), or None when they cannot be read or are
    over the scoping limits - the caller then shows the whole commit, exactly as before 0.3. git runs without a
    shell; only full SHA-1s from revision_history() and git's own object ids reach its arguments."""
    try:
        rc, raw, _ = revision_exec(["git", "diff", "--raw", "-z", "-M", "--abbrev=40", "--no-ext-diff", base, head, "--"]
                                   + list(paths), repo, 30, 2 * 1024 * 1024)
        if rc != 0:
            return None
        entries = parse_raw_entries(raw)
        if len(entries) > SCOPE_FILES_MAX:
            return None
        budget, zero, files = [SCOPE_BYTES_MAX], "0" * 40, []
        deadline = time.monotonic() + SCOPE_SECONDS_MAX
        for old_path, new_path, old_oid, new_oid, modes, text in entries:
            if time.monotonic() > deadline:
                return None
            if not text:                          # symlink or submodule: never lines (the whole-commit snapshot refuses it)
                files.append(FileChange(old_path, new_path, (), (), (), False, modes))
                continue
            old = _blob(repo, old_oid, budget) if old_path is not None and old_oid != zero else b""
            new = _blob(repo, new_oid, budget) if new_path is not None and new_oid != zero else b""
            if b"\0" in old[:8000] or b"\0" in new[:8000]:
                files.append(FileChange(old_path, new_path, (), (), (), True, modes))
                continue
            if old == new:
                blocks = []
            elif old_path is None or new_path is None:
                blocks = [Block(0, len(git_lines(old)), 0, len(git_lines(new)))]
            else:
                # --inter-hunk-context=0: a diff.interHunkContext setting must not merge two pins' blocks into one
                rc, patch, _ = revision_exec(["git", "diff", "-U0", "--inter-hunk-context=0", "--no-color", "--no-ext-diff",
                                              "--no-textconv", old_oid, new_oid], repo, 30,
                                             4 * REVISION_DIFF_MAX + len(old) + len(new))
                if rc != 0:
                    return None
                blocks = parse_u0_blocks(patch)
            files.append(FileChange(old_path, new_path, git_lines(old), git_lines(new), tuple(blocks), False, modes))
        return files
    except (HTTPError, ValueError, UnicodeError):
        return None


def _repo_rel(repo: Path, path: str) -> str | None:
    """path (absolute, as stored on pins) relative to the repository root in POSIX form, symlinks resolved; None when
    it lies outside the repository or cannot be resolved."""
    try:
        return Path(path).resolve().relative_to(repo.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError, TypeError):
        return None


def scope_pin_record(rows: list, D: Doc, pid: int) -> dict:
    """The pin a scoped request names, from rows (pins.jsonl as read by the caller, without the sync write). Raises
    ScopeRejected("pin_not_in_doc") when there is no such pin or it belongs to another document than D."""
    r = find_pin(rows, pid)
    if r is None or pin_doc_key(r) != D.key:
        raise ScopeRejected("pin_not_in_doc")
    return r


def revision_pin_scope(D: Doc, rows: list, repo: Path, paths: Sequence[str], base: str, head: str, pid: int,
                       revisions: Sequence[dict], cache: ScopeCache) -> PinScope:
    """How pin pid of document D sees commit head (compared with its first parent base). rows are the pin records,
    revisions the document's recent commits (revision_history); the recorded changes count only on the commit the
    pin's close_ref names. Unless the same pin facts were decided for this commit before (cache), reads the commit's
    files within one of the cache's slots and decides with pin_scope(); an unreadable commit is mode "commit" and not
    stored. Raises ScopeRejected("pin_not_in_doc")."""
    r = scope_pin_record(rows, D, pid)
    changes = [RepoRange(_repo_rel(repo, c["file"]), c["lo"], c["hi"]) for c in recorded_changes(r, head, revisions)]
    pin = pin_facts(r, _repo_rel(repo, r["file"]) if not is_region_pin(r) else None)
    key = (str(repo), base, head, json.dumps([pin, changes], default=str))
    hit = cache.get(key)
    if hit is not None:
        return hit
    with cache.slot() as got:
        files = revision_changes(repo, base, head, paths) if got else None
    out = pin_scope(files, pin, [c for c in changes if c.path])
    if files is not None:
        cache.put(key, out)
    return out


def revision_first_parent(repo: Path, commit: str) -> str | None:
    """The full SHA-1 of commit's first parent, or None for a root commit or when git cannot tell (the source diff
    then shows the whole commit for a pin)."""
    rc, out, _ = _git(["rev-list", "--parents", "-n", "1", commit], repo)
    parents = out.strip().split()
    return parents[1] if rc == 0 and len(parents) >= 2 and REVISION_ID_RE.fullmatch(parents[1]) else None


# ---------------------------------------------------------------- Git revision PDFs — independent from the current manuscript build

REVISION_CACHE_VERSION = "latex-pdf-v1"
REVISION_FILES_MAX = 4000
REVISION_TREE_MAX = 256 * 1024 * 1024
REVISION_FILE_MAX = 64 * 1024 * 1024
REVISION_PDF_MAX = 32 * 1024 * 1024
REVISION_CACHE_KEEP = 6
REVISION_SCOPED_KEEP = 6              # pin-scoped comparisons, counted apart so they never evict whole-commit ones
SCOPED_MARK = "scoped"                # empty file in a pin-scoped comparison's cache folder
REVISION_CACHE_TTL = 24 * 3600
REVISION_JOBS_LOCK = threading.RLock()
REVISION_JOBS = {}                    # active jobs only; completed state lives in the bounded cache
REVISION_SLOTS = threading.BoundedSemaphore(2)


class RevisionSpec(NamedTuple):
    """One comparison to build: repo, build root (source, relative to repo) and main (relative to it), the first parent
    base and the commit head, and key - the cache identity (revision_spec). For a pin that owns part of the commit,
    scope names the blocks the new side applies; meta carries the per-request status fields for a pin request."""
    repo: Path
    source: str
    main: Path
    base: str
    head: str
    key: str
    paths: tuple[str, ...] = ()       # the manuscript pathspec (revision_scope) - a scoped build re-reads the commit with it
    scope: tuple[ScopeItem, ...] = ()  # v0.3: the pin's blocks (scope_key); () = the whole commit
    pin: int | None = None            # the pin that asked, when the request named one
    meta: ScopeMeta | None = None     # additive status fields for a pin request: scope, pin, source, hunks, other


def revision_spec(D: Doc, commit: str, pin: int | None = None) -> RevisionSpec:
    """What to compare. With pin (v0.3) the new side is old + only that pin's blocks - unless the pin owns the whole
    commit or none of it, in which case the spec (and its cache entry) is the whole-commit one. The cache identity of a
    scoped comparison is (commit, block set) - two pins with the same blocks share one PDF. Raises HTTPError for a
    bad or foreign commit (as before 0.3) and ScopeRejected("pin_not_in_doc") for a pin D does not have."""
    if not isinstance(commit, str) or not REVISION_ID_RE.fullmatch(commit):
        raise HTTPError(400, "올바른 커밋 ID가 아닙니다.")
    scope = revision_scope(D)
    revisions = revision_history(D)["revisions"] if scope is not None else []
    if scope is None or commit not in {r["id"] for r in revisions}:
        raise HTTPError(404, "현재 문서의 최근 커밋이 아닙니다.")
    repo, paths = scope[0], tuple(scope[1])
    try:
        source = D.src.resolve().relative_to(repo).as_posix()
        main = D.main.resolve().relative_to(D.src.resolve())
    except ValueError:
        raise HTTPError(400, "Git 저장소 안의 문서 빌드 루트가 필요합니다.") from None
    rc, out, _ = _git(["rev-list", "--parents", "-n", "1", commit], repo)
    parents = out.strip().split()
    if rc != 0 or len(parents) < 2 or not REVISION_ID_RE.fullmatch(parents[1]):
        raise HTTPError(422, "첫 커밋은 이전 원고가 없어 비교 PDF를 만들 수 없습니다.", reason="no_parent")
    base = parents[1]
    identity = [REVISION_CACHE_VERSION, str(repo), source, main.as_posix(), base, commit, "pdflatex"]
    blocks, meta = (), None
    if pin is not None:
        sc = revision_pin_scope(D, [public(r) for r in read_pins()[0]], repo, paths, base, commit, pin, revisions,
                                SCOPE_CACHE)
        meta = scope_meta(sc)
        if sc.mode == "pin":
            blocks = sc.blocks                    # keyed by the block set, not the pin: pins on the same fix share it
            identity += ["blocks", [list(b) for b in blocks]]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return RevisionSpec(repo, source, main, base, commit, key, paths, blocks, pin, meta)


def revision_exec(cmd: list, cwd: Path, timeout: float, limit: int = 8 * 1024 * 1024):
    """Bound both pipes and lifetime; kill the entire process group on every early exit."""
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        raise HTTPError(503, "비교 PDF 실행 도구를 시작하지 못했습니다.", reason="tool_unavailable") from None
    buffers = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    size, deadline = 0, time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as sel:
            for pipe in buffers:
                sel.register(pipe, selectors.EVENT_READ)
            while sel.get_map():
                left = deadline - time.monotonic()
                if left <= 0:
                    raise HTTPError(503, "비교 PDF 실행 시간이 초과됐습니다.", reason="timeout")
                for key, _ in sel.select(min(left, 1)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        sel.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    if size > limit:
                        raise HTTPError(422, "비교 입력 또는 실행 로그가 크기 제한을 넘었습니다.", reason="size_limit")
                    buffers[key.fileobj].extend(chunk)
            try:
                rc = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise HTTPError(503, "비교 PDF 실행 시간이 초과됐습니다.", reason="timeout") from None
        return rc, bytes(buffers[proc.stdout]), bytes(buffers[proc.stderr])
    finally:
        # Also remove descendants left behind by a command that has already exited.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        for pipe in buffers:
            pipe.close()


def revision_snapshot(spec: RevisionSpec, commit: str, dest: Path) -> None:
    prefix = "" if spec.source == "." else spec.source + "/"
    cmd = ["git", "ls-tree", "-r", "-l", "-z", commit]
    if prefix:
        cmd += ["--", ":(literal)" + spec.source]
    rc, tree, _ = revision_exec(cmd, spec.repo, 30, 2 * 1024 * 1024)
    if rc != 0:
        raise HTTPError(422, "Git 원고 사본을 읽지 못했습니다.", reason="snapshot_failed")
    entries, total = [], 0
    for row in tree.split(b"\0"):
        if not row:
            continue
        try:
            meta, rawname = row.split(b"\t", 1)
            mode, kind, oid, size = meta.split()
            name = rawname.decode("utf-8")
            if not name.startswith(prefix):
                raise ValueError()
            name = name[len(prefix):]
            path = Path(name)
            if (mode not in (b"100644", b"100755") or kind != b"blob" or path.is_absolute()
                    or not name or any(p in (".", "..", ".git") for p in name.split("/"))
                    or "\\" in name or any(ord(c) < 32 for c in name)):
                raise ValueError()
            n = int(size)
        except (ValueError, UnicodeError):
            raise HTTPError(422, "사본에 허용되지 않는 경로·심링크·하위 저장소가 있습니다.", reason="unsafe_snapshot") from None
        total += n
        entries.append((path, oid.decode("ascii"), n))
        if n > REVISION_FILE_MAX or total > REVISION_TREE_MAX or len(entries) > REVISION_FILES_MAX:
            raise HTTPError(422, "원고 사본이 파일 수·크기 제한을 넘었습니다.", reason="size_limit")
    dest.mkdir(parents=True)
    deadline = time.monotonic() + 60
    for path, oid, n in entries:
        if time.monotonic() >= deadline:
            raise HTTPError(503, "Git 사본 생성 시간이 초과됐습니다.", reason="timeout")
        rc, data, _ = revision_exec(["git", "cat-file", "blob", oid], spec.repo,
                                    min(15, max(.01, deadline - time.monotonic())), n + 4096)
        if rc != 0 or len(data) != n:
            raise HTTPError(422, "Git 원고 파일을 읽지 못했습니다.", reason="snapshot_failed")
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if not (dest / spec.main).is_file():
        raise HTTPError(422, "해당 커밋에 현재 메인 원고 경로가 없습니다. 소스 변경사항을 확인하세요.", reason="missing_main")


def revision_apply_scope(spec: RevisionSpec, dest: Path) -> None:
    """Turns dest (a fresh snapshot of the old side) into old + only spec.scope's blocks: re-reads the commit from git
    (deterministic for two SHA-1s), lets plan_scope_writes() decide, and writes or removes those files under dest.
    Raises ScopeRejected ("scope_unreadable", "scope_mismatch", "unsafe_path" - also for a symlink or a parent outside
    dest - and "scope_unwritable" for an OSError while writing); the build worker reports it in the status like any
    other build failure, and a pin's scope_failed is answered from the cache next time."""
    for w in plan_scope_writes(revision_changes(spec.repo, spec.base, spec.head, spec.paths), spec.scope, spec.source):
        target = dest / w.rel
        if target.is_symlink() or not target.parent.resolve().is_relative_to(dest.resolve()):
            raise ScopeRejected("unsafe_path")
        try:
            if w.data is None:
                if target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(w.data)
        except OSError:
            raise ScopeRejected("scope_unwritable") from None


def revision_sandbox(work: Path, main_parent: Path, tool: str, args: list) -> list:
    """Only the TeX installation and throwaway snapshots are visible; no host home or network."""
    if tool not in ("latexdiff", "latexmk"):
        raise ValueError("unsupported revision tool")
    bwrap, exe = shutil.which("bwrap"), shutil.which(tool)
    if not bwrap or not exe:
        raise HTTPError(503, "비교 PDF에는 bwrap, latexdiff, latexmk가 필요합니다.", reason="tool_unavailable")
    exe = Path(exe).resolve()
    if not exe.is_relative_to(Path("/usr")):
        raise HTTPError(503, "비교 PDF 도구는 /usr 아래의 시스템 설치를 사용해야 합니다.", reason="tool_unavailable")
    cmd = [bwrap, "--unshare-all", "--die-with-parent", "--clearenv"]
    for path in ("/usr", "/bin", "/lib", "/lib64", "/etc/fonts", "/etc/texmf", "/var/lib/texmf", "/var/cache/fontconfig"):
        if Path(path).exists():
            cmd += ["--ro-bind", path, path]
    cmd += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--bind", str(work), "/work", "--chdir", "/work/new/" + main_parent.as_posix()]
    # latexmk invokes the engine by name; use the installation's public binary directory,
    # not a symlink-resolved Perl script directory.
    texbin = str(Path(shutil.which("latexmk") or "/usr/bin/latexmk").parent)
    for key, value in {"PATH": texbin + ":/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8",
                       "TEXMFVAR": "/tmp/texmf-var", "TEXMFCONFIG": "/tmp/texmf-config",
                       "openin_any": "p", "openout_any": "p"}.items():
        cmd += ["--setenv", key, value]
    return cmd + ["--", str(exe)] + args


def revision_compile(spec: RevisionSpec, jobdir: Path, timeout: int) -> dict:
    """Builds the comparison PDF of spec into jobdir/revision.pdf (and jobdir/build.log) inside the bwrap sandbox:
    snapshots of both sides - for a pin scope, old + only its blocks (revision_apply_scope) - then latexdiff, then
    latexmk with timeout seconds. Returns the "ready" status fields with warnings. Raises HTTPError with a reason
    for a failed step (as before 0.3) or ScopeRejected from the scope step; the worker records either."""
    warnings = ["수식 내부와 같은 파일명의 그림 내용 변경은 강조되지 않을 수 있습니다. 그림·서지·스타일 변경은 소스 변경사항도 확인하세요."]
    with tempfile.TemporaryDirectory(prefix="work-", dir=jobdir) as tmp:
        work = Path(tmp)
        revision_snapshot(spec, spec.base, work / "old")
        if spec.scope:                            # v0.3: the new side is old + only the pin's blocks
            revision_snapshot(spec, spec.base, work / "new")
            revision_apply_scope(spec, work / "new")
        else:
            revision_snapshot(spec, spec.head, work / "new")
        main = spec.main.as_posix()
        head_label = spec.head[:8] + ("+scoped" if spec.scope else "")
        args = ["--encoding=utf8", "--flatten", "--math-markup=off", "--add-to-config",
                "ARRENV=tabularx;tabular;tabular[*]", "--label", spec.base[:8], "--label", head_label,
                "/work/old/" + main, "/work/new/" + main]
        rc, diff, err = revision_exec(revision_sandbox(work, spec.main.parent, "latexdiff", args), work, 60)
        log = err.decode("utf-8", errors="replace")
        if rc != 0 or b"\\begin{document}" not in diff or "Could not find" in log:
            atomic_write(jobdir / "build.log", log[-8000:])
            raise HTTPError(422, "latexdiff가 원고를 비교하지 못했습니다. 누락된 포함 파일 또는 실행 격리 설정을 확인하세요.", reason="diff_failed")
        if not re.search(rb"\\DIF(?:add|del)(?:begin|\{)", diff.split(b"\\begin{document}", 1)[1]):
            warnings.append("본문에 강조할 문장 차이가 없습니다. 서지·스타일 또는 주석만 바뀌었을 수 있습니다.")
        out = work / "new" / spec.main.parent
        # Tracked artifacts must never satisfy the fresh-PDF check or influence latexmk.
        for stale in out.glob("pin_revision.*"):
            if stale.is_file():
                stale.unlink()
        (out / "pin_revision.tex").write_bytes(diff)
        args = ["-norc", "-pdf", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "pin_revision.tex"]
        rc, stdout, stderr = revision_exec(revision_sandbox(work, spec.main.parent, "latexmk", args), work, timeout)
        log += (stdout + stderr).decode("utf-8", errors="replace")
        atomic_write(jobdir / "build.log", log[-8000:])
        pdf = out / "pin_revision.pdf"
        if rc != 0 or not pdf.is_file() or pdf.stat().st_size > REVISION_PDF_MAX:
            raise HTTPError(422, "비교 PDF 컴파일에 실패했습니다. 이 뷰어는 pdfLaTeX를 사용합니다. 소스 변경사항을 확인하세요.", reason="compile_failed")
        if not pdf.read_bytes().startswith(b"%PDF-"):
            raise HTTPError(422, "비교 PDF 결과가 올바르지 않습니다.", reason="invalid_pdf")
        # Earlier latexmk passes normally contain unresolved citations. Report the final
        # engine log only, otherwise a successful BibTeX pass looks like a broken PDF.
        final_log = out / "pin_revision.log"
        final_text = (final_log.read_text(encoding="utf-8", errors="replace")
                      if final_log.is_file() and final_log.stat().st_size <= 8 * 1024 * 1024 else log)
        warning_lines = [line.strip() for line in final_text.splitlines()
                         if "Warning:" in line or "undefined" in line or "Missing character:" in line]
        warnings += list(dict.fromkeys(warning_lines))[:12]
        os.replace(pdf, jobdir / "revision.pdf")
    return {"state": "ready", "warnings": warnings, "error": None, "reason": None}


def _revision_cache_root(D: Doc) -> Path:
    root = D.dir / "revisions"
    if root.is_symlink():
        raise HTTPError(503, "비교 캐시 경로가 올바르지 않습니다.", reason="unsafe_cache")
    root.mkdir(parents=True, exist_ok=True)
    return root


SCOPE_META = ("scope", "pin", "source", "hunks", "other")   # per-request fields; never stored in a (shared) status


def _without_meta(d: dict) -> dict:
    """d without the per-request pin fields (SCOPE_META), so a stored or shared status never carries another
    request's pin."""
    return {k: v for k, v in d.items() if k not in SCOPE_META}


def _revision_cached(spec: RevisionSpec, root: Path) -> dict:
    """The finished status of spec from its cache folder under root ("ready" only with a PDF of sane size), else an
    "idle" status; always with spec's identity and, for a pin request, its per-request fields. Reads files only;
    a corrupt, oversized, symlinked or expired entry is a miss."""
    path = root / spec.key
    identity = dict({"job_id": spec.key, "base": spec.base, "head": spec.head, "engine": "pdflatex"}, **(spec.meta or {}))
    try:
        status = path / "status.json"
        if path.is_symlink() or status.is_symlink() or status.stat().st_size > 32768:
            raise ValueError()
        data = json.loads(status.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("state") not in ("ready", "error") or time.time() - status.stat().st_mtime > REVISION_CACHE_TTL:
            raise ValueError()
        if data["state"] == "ready":
            pdf = path / "revision.pdf"
            if pdf.is_symlink() or not 0 < pdf.stat().st_size <= REVISION_PDF_MAX:
                raise ValueError()
        return dict(_without_meta(data), **identity)
    except (OSError, ValueError, TypeError):
        return dict(identity, state="idle", warnings=[], error=None, reason=None)


def _revision_prune(root: Path, keep_key: str) -> None:
    """Removes expired comparisons and, newest first, those beyond the limits - REVISION_CACHE_KEEP whole-commit and
    REVISION_SCOPED_KEEP pin-scoped ones (SCOPED_MARK), counted apart so pins never push out whole-commit PDFs. The
    entry about to be built (keep_key, counted as one whole-commit slot as before) and running jobs are kept."""
    entries = [p for p in root.iterdir() if re.fullmatch(r"[0-9a-f]{64}", p.name) and p.is_dir() and not p.is_symlink()]
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    kept = {False: 1, True: 0}
    for path in entries:
        if path.name == keep_key or str(path) in REVISION_JOBS:
            continue
        scoped = (path / SCOPED_MARK).is_file()
        limit = REVISION_SCOPED_KEEP if scoped else REVISION_CACHE_KEEP
        if kept[scoped] >= limit or time.time() - path.stat().st_mtime > REVISION_CACHE_TTL:
            shutil.rmtree(path)
        else:
            kept[scoped] += 1


def revision_status(D: Doc, commit: str, pin: int | None = None) -> dict:
    """GET /api/revision-build: the running job's status or the cached one, re-authorising the commit (and pin) on
    every poll. Raises what revision_spec raises."""
    spec = revision_spec(D, commit, pin)         # Reauthorize cache hits and poll requests too.
    with REVISION_JOBS_LOCK:
        root = _revision_cache_root(D)
        active = REVISION_JOBS.get(str(root / spec.key))
        return dict(_without_meta(active), **(spec.meta or {})) if active else _revision_cached(spec, root)


def revision_start(D: Doc, commit: str, pin: int | None = None) -> dict:
    """POST /api/revision-build: returns the running or cached status, or starts a worker thread and returns
    "running". A pin subset that failed deterministically is answered from the cache. Raises HTTPError 409 when both
    build slots or this document's lock are taken, and what revision_spec raises."""
    spec = revision_spec(D, commit, pin)
    with REVISION_JOBS_LOCK:
        root = _revision_cache_root(D)
        jobdir, jobkey = root / spec.key, str(root / spec.key)
        if jobkey in REVISION_JOBS:
            return dict(_without_meta(REVISION_JOBS[jobkey]), **(spec.meta or {}))
        cached = _revision_cached(spec, root)
        if cached["state"] == "ready":
            return cached
        # A pin's subset that did not compile will not compile next time either (two SHA-1s, a fixed pipeline): answer
        # from the cache so the viewer falls back at once instead of spending a build slot again. Whole commits retry.
        if spec.scope and cached["state"] == "error" and cached.get("reason") in ("compile_failed", "diff_failed", "scope_failed"):
            return cached
        if not REVISION_SLOTS.acquire(blocking=False):
            raise HTTPError(409, "다른 비교 PDF를 만드는 중입니다. 잠시 뒤 다시 시도하세요.", reason="busy")
        try:
            # A second server sharing a state directory must not prune or replace this job.
            lock = (root / "build.lock").open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                raise HTTPError(409, "이 문서의 비교 PDF를 만드는 중입니다.", reason="busy") from None
            _revision_prune(root, spec.key)
            if jobdir.is_symlink():
                raise HTTPError(503, "비교 캐시 경로가 올바르지 않습니다.", reason="unsafe_cache")
            if jobdir.exists():
                shutil.rmtree(jobdir)
            jobdir.mkdir()
            if spec.scope:
                (jobdir / SCOPED_MARK).write_text("")
            running = dict(_without_meta(cached), state="running", error=None, reason=None, warnings=[])
            REVISION_JOBS[jobkey] = running
            timeout = min(180, max(1, C.timeout))
        except BaseException:
            if "lock" in locals() and not lock.closed:
                lock.close()
            REVISION_SLOTS.release()
            raise

        def worker():
            """Runs the build, stores its final status in jobdir/status.json, and frees the slot and lock. An expected
            failure (HTTPError, or ScopeRejected mapped by the one SCOPE_REJECTIONS table) becomes an "error" status."""
            try:
                result = revision_compile(spec, jobdir, timeout)
            except (HTTPError, ScopeRejected) as exc:
                err = exc if isinstance(exc, HTTPError) else scope_http_error(exc)
                result = {"state": "error", "error": err.body["error"], "reason": err.body.get("reason", "build_failed"), "warnings": []}
            except Exception:
                traceback.print_exc()
                result = {"state": "error", "error": "비교 PDF를 만들지 못했습니다.", "reason": "build_failed", "warnings": []}
            try:
                result = dict(running, **result)          # running carries no per-request pin fields (SCOPE_META)
                atomic_write(jobdir / "status.json", json.dumps(result, ensure_ascii=False))
            except OSError:
                pass
            finally:
                with REVISION_JOBS_LOCK:
                    REVISION_JOBS.pop(jobkey, None)
                    lock.close()
                    REVISION_SLOTS.release()

        try:
            threading.Thread(target=worker, daemon=True).start()
        except BaseException:
            REVISION_JOBS.pop(jobkey, None)
            lock.close()
            REVISION_SLOTS.release()
            raise
        return dict(running, **(spec.meta or {}))


def revision_pdf(D: Doc, commit: str, pin: int | None = None) -> bytes:
    """GET /api/revision-pdf: the finished comparison PDF of the commit (or of the pin's part of it). Raises HTTPError
    404 when it is not ready or has expired, and what revision_spec raises."""
    spec = revision_spec(D, commit, pin)
    with REVISION_JOBS_LOCK:
        root = _revision_cache_root(D)
        if _revision_cached(spec, root)["state"] != "ready":
            raise HTTPError(404, "해당 비교 PDF가 아직 없거나 만료됐습니다.")
        try:
            return (root / spec.key / "revision.pdf").read_bytes()
        except OSError:
            raise HTTPError(404, "해당 비교 PDF가 없습니다.") from None


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
    with using_doc(D):
        pages = cur_pages()
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
                with using_doc(D):
                    build_async()
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


def _build() -> dict:
    """The LaTeX build of the current document with this instance's settings; --git-pull pulls first (limn.build.compile_tex)."""
    return build.compile_tex(cur_doc(), build_config(), repo_pull if C.git_pull else None)


def _render_pages(pdf: Path, extra: list):
    """Render pdf into a new page directory of the current document: (directory, None) or (None, error) (limn.build.render_pages)."""
    return build.render_pages(cur_doc(), pdf, extra, C.dpi)


def _commit_pages(newdir: Path) -> str:
    """Make newdir the current document's page directory and return the short head (limn.build.commit_pages)."""
    return build.commit_pages(cur_doc(), newdir)


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


def _render_pdf_doc() -> dict:
    """The 'build' for a view-only document - renders the original PDF into page images. No LaTeX, SyncTeX, or git pull."""
    t0 = time.time()
    D = cur_doc()
    res = {"ok": False, "state": "fail", "errors": [], "log": "", "elapsed_s": 0.0}
    sig = pdf_signature(D)
    if sig is None:
        res["log"] = "PDF 가 없습니다: %s" % D.main
        return res
    try:
        res["src_hash"] = doc_fingerprint(D)
    except OSError:
        res["src_hash"] = None
    newdir, err = _render_pages(D.main, [])
    if newdir is None:
        res["log"] = err
        res["elapsed_s"] = round(time.time() - t0, 1)
        try:                                         # never retries the same file every 3 seconds - re-renders only when the file changes
            atomic_write(D.dir / "pdf_sig.txt", sig)
        except OSError:
            pass
        return res
    res["head"] = _commit_pages(newdir)
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
    with using_doc(D):
        r = build_async()
    return not r.get("busy")


# ---------------------------------------------------------------- Meta

def png_size(path: Path) -> tuple:
    with path.open("rb") as fh:
        return struct.unpack(">II", fh.read(24)[16:24])


def page_list(pdir: Path = None) -> list:
    pages = []
    for p in sorted((pdir or cur_pages()).glob("page-*.png")):
        try:
            w, h = png_size(p)
        except (OSError, struct.error):
            continue
        pages.append({"name": p.name, "pt_w": w * 72.0 / C.dpi, "pt_h": h * 72.0 / C.dpi})
    return pages


_SRC_MTIME_CACHE: list = [None, 0.0, 0.0]     # [C.src string, value, measured-at time] - a 2-second cache (for a single document)
# Single document (no --doc). Holds the module-global lock/state as-is, so the object the legacy code paths
# and regression tests see is exactly this document's.
LEGACY_DOC = Doc(DEFAULT_DOC_KEY, "본문", legacy=True, lock=BUILD_LOCK, bstate=BUILD_STATE,
                 bstate_lock=BUILD_STATE_LOCK, builds_lock=BUILDS_LOCK, mcache=_SRC_MTIME_CACHE)
DOCS: list = [LEGACY_DOC]
_TL = threading.local()


def set_docs(docs=None) -> None:
    """Change the document list (main()/tests). Reverts to a single document when empty."""
    DOCS[:] = list(docs) if docs else [LEGACY_DOC]


def cur_doc() -> Doc:
    """The document this thread is handling. Request handlers / build threads hang it off via using_doc. Falls back to the first document."""
    d = getattr(_TL, "doc", None)
    return d if d is not None else DOCS[0]


@contextlib.contextmanager
def using_doc(d):
    prev = getattr(_TL, "doc", None)
    _TL.doc = d
    try:
        yield d
    finally:
        _TL.doc = prev


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


def doc_fingerprint(D: Doc) -> str:
    """The document's manuscript fingerprint (limn.build.doc_fingerprint)."""
    return build.doc_fingerprint(D, C.state)


def source_fingerprint(root: Path) -> str:
    """The current document's manuscript fingerprint over the files under root (limn.build.source_fingerprint)."""
    return build.source_fingerprint(cur_doc(), root, C.state)


def src_mtime(force: bool = False) -> float:
    """Newest manuscript mtime of the current document, memoized 2 seconds unless force (limn.build.src_mtime)."""
    return build.src_mtime(cur_doc(), C.state, force)


def read_built_src_mtime():
    """The src_mtime the current document's page images were built from, or None (limn.build.read_built_src_mtime)."""
    return build.read_built_src_mtime(cur_doc())


def write_built_src_mtime(value: float = None) -> None:
    """Commit the current document's built src_mtime; measured now if value is omitted (limn.build.write_built_src_mtime)."""
    build.write_built_src_mtime(cur_doc(), C.state, value)


def pins_rev() -> str:
    try:
        st = C.pins_jsonl.stat()
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return "0"


def doc_brief(D: Doc) -> dict:
    """A summary of one document - used by /api/docs and (with multiple documents) /api/meta's docs. Never writes (called from polling)."""
    with using_doc(D):
        b = build_state_snapshot()
        stale = (not D.is_pdf) and source_newer() > 2
        pdir = cur_pages()
        n_pages = sum(1 for _ in pdir.glob("page-*.png")) if pdir.is_dir() else 0
        return {"key": D.key, "name": D.name, "kind": D.kind, "view_only": D.is_pdf, "path": D.rel_path(),
                "main": D.main.name, "stale_build": stale, "src_mtime": src_mtime(),
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


def meta(actor: dict, light: bool = False) -> dict:
    D = cur_doc()

    def read(f):
        try:
            return (D.dir / f).read_text().strip()
        except OSError:
            return "?"
    bstate = build_state_snapshot()
    sm = src_mtime()
    newer = 0.0 if D.is_pdf else source_newer()     # view-only: the server re-renders on its own when the PDF changes
    out = {"pages": page_list(), "built_at": read("built_at.txt"), "head": read("head.txt"),
           "main": D.main.name, "pins_md": str(C.pins_md), "state_dir": str(C.state), "me": actor,
           "label": C.label, "accent": C.accent, "repo": C.repo,
           "building": D.lock.locked(), "sync": sync_status(),
           "doc": D.key, "doc_name": D.name, "kind": D.kind, "view_only": D.is_pdf, "multi": multi_doc(),
           # Is the manuscript newer than the PDF on screen - the server judges this numerically (independent of browser clock/timezone).
           "stale_build": newer > 2, "src_age_s": round(max(0.0, time.time() - sm), 1) if sm else None,
           "src_mtime": sm, "build_src_mtime": read_built_src_mtime(),
           "pages_build": cur_pages().name,
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


# ---------------------------------------------------------------- Source-text access

def tex_lines(path: Path) -> list:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def to_source(path: str) -> Path:
    """Maps a build-copy path back to the original checkout path."""
    D = cur_doc()
    p = Path(path)
    for base in (D.build, D.build.resolve()):
        try:
            return D.src / p.relative_to(base)
        except ValueError:
            pass
    try:
        return D.src / p.resolve().relative_to(D.build.resolve())
    except (ValueError, OSError):
        pass
    # If the state directory was moved or cloned, synctex points at the old build path. If the path's tail
    # matches a real file inside the manuscript tree, fall back to that (longest tail wins; never reads outside the tree).
    parts = p.parts
    for k in range(1, len(parts)):
        cand = D.src.joinpath(*parts[k:])
        if cand.is_file():
            return cand
    return p


def safe_src(p) -> Path:
    """Only passes real files inside the manuscript tree. Otherwise 400 - the first line leaks into pins.md."""
    if not isinstance(p, str) or not p or "\x00" in p or len(p) > 4096:
        raise HTTPError(400, "file 이 올바르지 않습니다.")
    q = Path(p)
    if not q.is_absolute():
        q = C.src / q
    try:
        rel = q.resolve().relative_to(C.src.resolve())
    except (ValueError, OSError, RuntimeError):
        raise HTTPError(400, "원고 디렉토리 밖의 파일입니다: %s" % p) from None
    out = C.src / rel
    if not out.is_file():
        raise HTTPError(400, "원고 안에 그런 파일이 없습니다: %s" % p)
    return out


# ---------------------------------------------------------------- Reverse mapping 1: SyncTeX

def synctex_edit(pdf: Path, page: int, x: float, y: float):
    try:
        out = subprocess.run(["synctex", "edit", "-o", "%d:%.2f:%.2f:%s" % (page, x, y, pdf)],
                             capture_output=True, text=True, timeout=10, check=False).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    inp = line = None
    for ln in out.splitlines():
        if ln.startswith("Input:"):
            inp = ln[6:].strip()
        elif ln.startswith("Line:"):
            try:
                line = int(ln[5:].strip())
            except ValueError:
                pass
        if inp and line:
            return inp, line
    return None


def by_synctex(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float):
    w, h = x1 - x0, y1 - y0
    nx = max(2, min(5, int(w / 40) + 2))
    ny = max(2, min(6, int(h / 14) + 2))
    hits = []
    for i in range(nx):
        for j in range(ny):
            r = synctex_edit(pdf, page, x0 + w * (i + 0.5) / nx, y0 + h * (j + 0.5) / ny)
            if r:
                hits.append(r)
    if not hits:
        return None
    best = max({f for f, _ in hits}, key=lambda f: sum(1 for g, _ in hits if g == f))
    ls = densest(sorted(ln for f, ln in hits if f == best))
    return best, ls[0], ls[-1]


# ---------------------------------------------------------------- Reverse mapping 2: rendered text

def region_text(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float) -> str:
    """Pulls out the characters actually printed inside the selection rectangle (1px = 1pt since -r 72)."""
    try:
        return subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-r", "72",
             "-x", str(int(x0)), "-y", str(int(y0)),
             "-W", str(max(1, int(x1 - x0))), "-H", str(max(1, int(y1 - y0))), str(pdf), "-"],
            capture_output=True, text=True, timeout=15, check=False).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


_DF_CACHE: dict = {}
_DF_LOCK = threading.Lock()


def file_key(path: Path) -> tuple:
    try:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(path), 0, 0)


def token_weights(text: str, lines: list, key: tuple) -> list:
    """Weights the region text's word tokens by rarity.

    Without weighting, common words like "target"/"data"/"training" dominate the score, so a selection that
    actually picked the Nomenclature can come out scoring high overlap with a body paragraph too (observed).
    The rarer a token, the more power it has to pin down a location. The cache key is (path, mtime_ns,
    size) - id(lines) gets reused once the list is garbage-collected and can pick up another file's frequencies."""
    with _DF_LOCK:
        df = _DF_CACHE.get(key)
    if df is None:
        df = {}
        for ln in lines:
            for t in set(TOKEN_RE.findall(ln)):
                df[t] = df.get(t, 0) + 1
        with _DF_LOCK:
            _DF_CACHE.clear()
            _DF_CACHE[key] = df
    n = max(1, len(lines))
    out = []
    for t in {t for t in TOKEN_RE.findall(text) if len(t) >= 2}:
        freq = df.get(t, 0)
        if freq > n * 0.05:            # a word scattered across the whole manuscript can't pin down a location
            continue
        out.append((t, 1.0 / (1.0 + freq)))
    return out


# ---------------------------------------------------------------- Block expansion and the range ladder

# ---------------------------------------------------------------- Anchors and re-syncing

def _off(v) -> int:
    return v if _is_int(v) and 0 <= v < 10000 else 0


def sync_all(rows: list) -> bool:
    """If the manuscript is newer than a pin, re-match its line numbers via the anchor. Records whose lines or stale flag changed get rev+1.

    The pin's file is the one pin_location() finds (ADR-0006). When that is not the stored `file` (a moved checkout),
    synced_at was measured on another file, so the mtime shortcut is taken only if the anchor still holds at lo
    (anchor_holds); a re-match then writes the located path into `file`, so lines, synced_at and file describe one file
    again. `file_rel` is never added here, and an anchor is never backfilled from a file the record does not name."""
    changed = False
    cache: dict = {}
    for r in rows:
        if r.get("done") or not r.get("file"):         # a view-only PDF's pin has no lines - nothing to re-match
            continue
        loc = pin_location(r, C.src)                 # ADR-0006: a moved checkout is followed; outside the tree is never read
        if loc is None:
            continue
        f = loc.path
        try:
            if not f.is_file():
                continue
        except OSError:
            continue
        if f not in cache:
            ls = tex_lines(f)
            cache[f] = (ls, [norm(t) for t in ls], f.stat().st_mtime)
        lines, nlines, mtime = cache[f]
        moved = str(f) != r["file"]                  # measured on another file than the stored one (ADR-0006)
        if "anchor" not in r:                        # backfill a legacy pin saved without an anchor, once
            if moved:
                continue                             # never from a file the record does not name (it may be a guess)
            r["anchor"] = anchor_of(lines, r["lo"], r["hi"])
            r["synced_at"] = mtime
            changed = True
            continue
        if not r["anchor"]:                          # a pin that selected only blank lines has no anchor to follow
            continue
        if r.get("synced_at", 0) >= mtime and (not moved or anchor_holds(r["anchor"], r["lo"], nlines)):
            continue
        before = (r["lo"], r["hi"], bool(r.get("stale")))
        anc = r["anchor"]
        ho, to = _off(anc.get("head_off")), _off(anc.get("tail_off"))   # 0 for a legacy anchor
        span = r["hi"] - r["lo"]
        head = find_line(nlines, anc.get("head", ""), r["lo"] + ho)
        if head is None:
            r["stale"], r["sync"] = True, "lost"
        else:
            n = max(1, len(lines))
            lo = max(1, head - ho)
            tail = find_line(nlines, anc.get("tail", ""), r["hi"] - to + (lo - r["lo"]))
            hi = tail + to if tail is not None and tail >= head else lo + span
            hi = max(lo, min(n, hi))
            r["sync"] = "ok" if (lo, hi) == (r["lo"], r["hi"]) else "moved %+d" % (lo - r["lo"])
            r["lo"], r["hi"] = lo, hi
            r.pop("stale", None)
        if (r["lo"], r["hi"], bool(r.get("stale"))) != before:
            r["rev"] = next_rev(r)
        if moved:
            r["file"] = str(f)                       # the new numbers describe this file
        r["synced_at"] = mtime
        changed = True
    return changed


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
    if r.get("changes") is not None and not _valid_changes(r["changes"]):
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


def is_region_pin(r: dict) -> bool:
    """Is this a pin on a view-only PDF document - no file, but a pdf path present (distinguished purely by record shape: even if the
    current config no longer includes that document, the record is not treated as broken - treating it as broken would delete the pin on the next write)."""
    return isinstance(r, dict) and r.get("file") is None and isinstance(r.get("pdf"), str) and bool(r["pdf"])


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


class PinLocation(NamedTuple):
    """Where a line pin's file is on this machine now (pin_location, docs/adr/0006-relative-pin-paths.md)."""
    rel: str                 # POSIX path relative to the manuscript root (--manuscript)
    path: Path               # root / rel - the absolute path the API returns as `file`


def _within(p: Path, root: Path) -> bool:
    """Does p, symlinks resolved, lie inside root (also resolved)? False when either cannot be resolved."""
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def pin_location(r: dict, root: Path) -> PinLocation | None:
    """Where line pin r's file is under the manuscript root on this machine now (pin_rel_path), or None: a view-only
    PDF pin, or a file the rule cannot place inside root. Only file metadata is read (resolve, is_file) - under root,
    apart from resolving the stored path itself as 0.3.0's in_tree() did - and never file contents: a line read from
    outside the tree would leak into the anchor and out through GET /api/pins. The result is checked once more after
    resolving symlinks, so a link inside the tree cannot lead outside (a tail through such a link is skipped for the
    next one)."""
    file = r.get("file")
    if not isinstance(file, str) or not file:
        return None
    try:
        under = Path(file).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        under = None
    rel = pin_rel_path(file, r.get("file_rel"), under, lambda t: (root / t).is_file() and _within(root / t, root))
    if rel is None:
        return None
    path = root / rel
    return PinLocation(rel, path) if _within(path, root) else None


def stamp_location(r: dict, root: Path) -> PinLocation | None:
    """Records where line pin r's file is now (ADR-0006 §1): `file` becomes the current absolute path and `file_rel` the
    path relative to root. Only for a write to this very pin (create, edit, restore) - other writes keep the stored
    record, so there is no write migration. A pin that cannot be located, or a view-only PDF pin, is left as it is.
    Mutates r and returns its location (or None)."""
    loc = pin_location(r, root)
    if loc is not None:
        r["file"], r["file_rel"] = str(loc.path), loc.rel
    return loc


def read_jsonl(path: Path) -> tuple:
    """(records, broken line numbers). Broken lines are skipped with a warning - so the whole GET doesn't become a 500.

    Even a line that parses as JSON is treated as broken if the required fields (file/lo/hi/id) have the wrong type (valid_rec)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return [], []
    rows, bad = [], []
    for i, t in enumerate(text.splitlines(), 1):
        if not t.strip():
            continue
        try:
            r = json.loads(t)
        except (ValueError, RecursionError):
            r = None
        if not valid_rec(r):
            bad.append(i)
            continue
        rows.append(r)
    if bad:
        print("warning: failed to read %d line(s) of %s (line %s)." % (len(bad), path.name, bad[:10]),
              file=sys.stderr)
    return rows, bad


def read_pins() -> tuple:
    return read_jsonl(C.pins_jsonl)


def dump_jsonl(rows: list) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def unique_path(stem: str, suffix: str) -> Path:
    """If <state>/<stem><suffix> already exists, appends -1, -2, ... - so archiving twice in the same second never overwrites."""
    p = C.state / (stem + suffix)
    k = 1
    while p.exists():
        p = C.state / ("%s-%d%s" % (stem, k, suffix))
        k += 1
    return p


def write_pins(rows: list, bad=None) -> None:
    """Builds pins.md in memory first. If rendering fails, nothing is written -
    committing pins.jsonl and then returning a 500 would make the client retry and create a duplicate pin."""
    md = pins_md_text(rows)
    data = dump_jsonl(rows)
    if bad and C.pins_jsonl.exists():                # avoid silent data loss: keep the original bytes
        shutil.copy2(C.pins_jsonl, unique_path("pins.jsonl.corrupt-%s" % time.strftime("%Y%m%d-%H%M%S"), ".bak"))
    atomic_write(C.pins_jsonl, data)
    atomic_write(C.pins_md, md)


def transact(fn):
    """Write-order invariant: with PIN_LOCK -> read -> sync -> apply the request's change -> atomic write -> pins.md.

    The change is applied after sync, so a caller-supplied lo/hi never gets reverted by a stale anchor.
    fn(rows) returns (result, whether it mutated). fn only modifies rows after validation is done."""
    with PIN_LOCK:
        rows, bad = read_pins()
        synced = sync_all(rows)
        try:
            result, mutated = fn(rows)
        except HTTPError:
            if synced:
                write_pins(rows, bad)
            raise
        if synced or mutated:
            write_pins(rows, bad)
        return rows, result


def snapshot_pins() -> list:
    rows, _ = transact(lambda rows: (None, False))
    return rows


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


# ---------------------------------------------------------------- Location estimation (.est) — a computed field the server judges
#
# A mark is fixed to frac (the ratio relative to the page) at the moment the pin was placed. If those
# coordinates might no longer match the PDF currently on screen, it's "estimated" (dashed). The judgment
# is made by build identity: estimated if the build the pin was placed on screen with (pdf_build) differs
# from the current build and the two builds' manuscript fingerprints differ. Also estimated if anchor line
# matching moved or lost the pin. The wall clock is never used - browser timezone, a note-only edited_at,
# and a pin placed on a stale PDF were all wrong across the board.

def pin_build(r: dict):
    """The name of the build a pin's coordinates belong to. frac_build is the legacy field name with the same meaning (83b91a5)."""
    for k in ("pdf_build", "frac_build"):
        v = r.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _epoch(s):
    """'YYYY-MM-DD HH:MM:SS' (server local time, the shape now_str writes) or ISO+offset -> epoch seconds. Resolved server-side only."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace(" ", "T", 1))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()          # this value was written in server local time - read back on the same machine
    return dt.timestamp()


def est_context() -> dict:
    """Judgment material for one request (history read once)."""
    h = load_builds()
    cur = cur_pages().name
    by = dict(h["by"])
    if cur not in by:                                 # before seed_builds() (tests / a rare race) - judge with what's known
        by[cur] = {"build": cur, "src_mtime": read_built_src_mtime(), "src_hash": None}
    bsm = read_built_src_mtime()
    if bsm is None and _is_num(by[cur].get("src_mtime")):
        bsm = float(by[cur]["src_mtime"])
    return {"cur": cur, "by": by, "built_at": _epoch(_read_built_at()), "bsm": bsm}


def same_source(a, b) -> bool:
    """Were two builds made from the same manuscript? By hash if both have one, otherwise by src_mtime at start.
    False (treated as different) if neither is known - rendering it as "exact location" while actually unsure would be worse."""
    if not a or not b:
        return False
    if a.get("src_hash") and b.get("src_hash"):
        return a["src_hash"] == b["src_hash"]
    ma, mb = a.get("src_mtime"), b.get("src_mtime")
    return _is_num(ma) and _is_num(mb) and abs(float(ma) - float(mb)) < 0.01


def legacy_est(r: dict, ctx: dict) -> bool:
    """Fallback heuristic for a legacy pin without pdf_build (the old viewer's rule, redone server-side with epoch numbers): estimated if
    the pin was placed before the current PDF, and the manuscript that produced the current PDF (src_mtime at start) changed after the pin.

    The only reference time is when it was placed (at) - using edited_at would turn off estimation just from
    editing the note (confirmed by independent verification). An edit that re-places frac (loc) now records
    pdf_build, so it no longer falls through to this heuristic."""
    ba, pa = ctx["built_at"], _epoch(r.get("at"))
    if ba is None or pa is None or pa >= ba:
        return False
    return ctx["bsm"] is not None and ctx["bsm"] > pa


def pin_est(r: dict, ctx: dict) -> bool:
    sync = r.get("sync")
    if r.get("stale") or (isinstance(sync, str) and sync != "ok"):
        return True                                   # moved +-N / lost - the anchor shifted or was lost
    b = pin_build(r)
    if b is None:
        return legacy_est(r, ctx)
    if b == ctx["cur"]:
        return False
    return not same_source(ctx["by"].get(b), ctx["by"].get(ctx["cur"]))


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
                with using_doc(D):
                    ctxs[k] = est_context()
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

def _range_rel(a_lo: int, a_hi: int, b_lo: int, b_hi: int):
    """a's relationship to b. None if they don't overlap."""
    if a_hi < b_lo or b_hi < a_lo:
        return None
    if b_lo <= a_lo and a_hi <= b_hi:
        return "contains" if (a_lo, a_hi) == (b_lo, b_hi) else "inside"
    if a_lo <= b_lo and b_hi <= a_hi:
        return "contains"
    return "partial"


def overlaps_by_id(rows: list) -> dict:
    """Computes the relationship for every pair of open pins on the same file (never stored). {id: [{"id","rel"}, ...]}.

    When two ranges are exactly equal, the one with the smaller id is treated as the outer one (contains) -
    since neither is truly nested inside the other, a single deterministic rule is needed."""
    out: dict = {}
    by_file: dict = {}
    for r in rows:
        if r.get("done"):
            continue
        out.setdefault(r["id"], [])
        if not r.get("file"):                          # a view-only PDF's pin - no line-range overlap
            continue
        loc = pin_location(r, C.src)                   # pins made before and after a move of the checkout are one file
        by_file.setdefault(str(loc.path) if loc else r.get("file"), []).append(r)
    for group in by_file.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if (a["lo"], a["hi"]) == (b["lo"], b["hi"]):
                    outer, inner = (a, b) if a["id"] < b["id"] else (b, a)
                    out[inner["id"]].append({"id": outer["id"], "rel": "inside"})
                    out[outer["id"]].append({"id": inner["id"], "rel": "contains"})
                    continue
                rel_a = _range_rel(a["lo"], a["hi"], b["lo"], b["hi"])   # does a fall inside b?
                if rel_a == "inside":
                    out[a["id"]].append({"id": b["id"], "rel": "inside"})
                    out[b["id"]].append({"id": a["id"], "rel": "contains"})
                elif rel_a == "contains":
                    out[a["id"]].append({"id": b["id"], "rel": "contains"})
                    out[b["id"]].append({"id": a["id"], "rel": "inside"})
                elif rel_a == "partial":
                    out[a["id"]].append({"id": b["id"], "rel": "partial"})
                    out[b["id"]].append({"id": a["id"], "rel": "partial"})
    return out


def selection_rel(lo: int, hi: int, b_lo: int, b_hi: int):
    """The relationship between a not-yet-saved selection (lo..hi) and a saved pin (b_lo..b_hi) - from the selection's point of view.

    equal (same range - the most common duplicate: placing a pin on the same paragraph/environment twice) -
    inside (selection is inside the pin) - contains (selection wraps the pin) - partial (overlapping) -
    None (no overlap). Same rule as the viewer's overlapsFor() (the browser recomputes this on every range
    change without a server round trip - a regression test compares the two implementations)."""
    if (lo, hi) == (b_lo, b_hi):
        return "equal"
    return _range_rel(lo, hi, b_lo, b_hi)


def overlaps_for_range(file: str, lo: int, hi: int) -> list:
    """The overlap relationships between the (not-yet-saved) range pick chose and that file's open pins. Nothing is saved.

    Between saved pins (overlaps_by_id), equal ranges are split into inner/outer by id, but a new selection
    has no id yet, so an identical range is reported separately as 'equal' - the viewer surfaces all four
    relationships via a banner with wording that spells out the relationship."""
    out = []
    for r in snapshot_pins():
        if r.get("done") or not r.get("file"):
            continue
        loc = pin_location(r, C.src)
        if (str(loc.path) if loc else r.get("file")) != file:
            continue
        rel = selection_rel(lo, hi, r["lo"], r["hi"])
        if rel:
            out.append({"id": r["id"], "lo": r["lo"], "hi": r["hi"], "rel": rel})
    return out


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


def max_id_in(path: Path) -> int:
    rows, _ = read_jsonl(path)
    return max((r["id"] for r in rows), default=0)


def init_seq() -> None:
    """If pins.seq is missing, fill it once from the max id across the current, archived, and dropped records (a one-time migration)."""
    with PIN_LOCK:
        if C.seq.exists():
            return
        m = max_id_in(C.pins_jsonl)
        for p in list(C.state.glob("pins_*.jsonl.bak")) + [C.dropped]:
            m = max(m, max_id_in(p))
        atomic_write(C.seq, str(m))


def next_id(rows: list) -> int:
    """An id is never reused - "#2" in a chat message must never end up pointing at a different pin."""
    try:
        last = int(C.seq.read_text().strip() or 0)
    except (OSError, ValueError):
        last = 0
    nid = max(last, max((r["id"] for r in rows), default=0)) + 1
    atomic_write(C.seq, str(nid))
    return nid


def find_pin(rows: list, pid: int):
    return next((r for r in rows if r.get("id") == pid), None)


def who(actor: dict) -> dict:
    return {"login": actor.get("login", "local"), "name": actor.get("name", "")}


# ---------------------------------------------------------------- Input validation

def _int(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or int(v) != v:
        raise HTTPError(400, "%s 는 정수여야 합니다." % what)
    return int(v)


def _num(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise HTTPError(400, "%s 는 유한한 숫자여야 합니다." % what)
    return float(v)


def clean_note(v) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise HTTPError(400, "note 는 문자열이어야 합니다.")
    if len(v) > NOTE_MAX:
        raise HTTPError(400, "메모가 너무 깁니다(%d자 이하)." % NOTE_MAX)
    return v


def clean_close_body(d: dict) -> tuple:
    """Validates the close body's optional {"reply", "ref"} fields. Absent or an empty (whitespace-only)
    string both become (None, None) - preserving the existing "curl POST with no body" behavior (§P0b-보완 C)."""
    reply = d.get("reply")
    if reply is not None:
        if not isinstance(reply, str):
            raise HTTPError(400, "reply 는 문자열이어야 합니다.")
        if len(reply) > CLOSE_REPLY_MAX:
            raise HTTPError(400, "reply 가 너무 깁니다(%d자 이하)." % CLOSE_REPLY_MAX)
        if not reply.strip():
            reply = None
    ref = d.get("ref")
    if ref is not None:
        if not isinstance(ref, str):
            raise HTTPError(400, "ref 는 문자열이어야 합니다.")
        if len(ref) > CLOSE_REF_MAX:
            raise HTTPError(400, "ref 가 너무 깁니다(%d자 이하)." % CLOSE_REF_MAX)
        if not ref.strip():
            ref = None
    return reply, ref


def clean_close_changes(v: object, root: Path) -> Changes | None:
    """HTTP-boundary parser for the close body's optional `changes`: [{file, lo, hi}] - the new-side lines the agent
    changed for this pin. file is a path inside root (the manuscript folder), absolute or relative to it (the pins.md
    location column); the result carries it resolved and absolute, like a pin's file. Absent or [] -> None (the
    pre-0.3 close). Raises HTTPError(400) naming the offending item - the messages are part of the agent contract."""
    if v is None:
        return None
    if not isinstance(v, list):
        raise HTTPError(400, "changes 는 [{\"file\", \"lo\", \"hi\"}] 목록이어야 합니다.")
    if len(v) > CLOSE_CHANGES_MAX:
        raise HTTPError(400, "changes 는 %d개 이하여야 합니다." % CLOSE_CHANGES_MAX)
    out, base = [], root.resolve()
    for i, c in enumerate(v):
        what = "changes[%d]" % i
        if not isinstance(c, dict) or set(c) != {"file", "lo", "hi"}:
            raise HTTPError(400, "%s 는 file·lo·hi 세 필드만 가진 객체여야 합니다." % what)
        f, lo, hi = c["file"], c["lo"], c["hi"]
        if not isinstance(f, str) or not f.strip() or len(f) > 1024 or "\x00" in f:
            raise HTTPError(400, "%s.file 은 비어 있지 않은 경로 문자열이어야 합니다." % what)
        if not (_is_int(lo) and _is_int(hi) and 1 <= lo <= hi <= CHANGE_LINE_MAX):
            raise HTTPError(400, "%s 의 lo·hi 는 1 ≤ lo ≤ hi ≤ %d 인 정수여야 합니다." % (what, CHANGE_LINE_MAX))
        try:
            path = (Path(f) if os.path.isabs(f) else base / f).resolve()
            path.relative_to(base)
        except (ValueError, OSError, RuntimeError):
            raise HTTPError(400, "%s.file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다." % what) from None
        out.append(CloseChange(str(path), lo, hi))
    return tuple(out) or None


def clean_pin_param(v: object) -> int | None:
    """HTTP-boundary parser for the optional pin of a revision request (query string or JSON int): None if absent or
    empty, else a pin id 1..999999999. Raises HTTPError(400) otherwise; whether the pin exists is decided later."""
    if v is None or v == "":
        return None
    if isinstance(v, str) and re.fullmatch(r"[1-9][0-9]{0,8}", v):
        return int(v)
    if _is_int(v) and 1 <= v <= 999999999:
        return v
    raise HTTPError(400, "pin 은 핀 번호(양의 정수)여야 합니다.")


def clean_assignee(v, rows: list = None):
    """Assignee - "agent" or the login of a person this viewer knows (known_people). None if absent (not sent = unchanged)."""
    if v is None:
        return None
    if v == ASSIGNEE_AGENT:
        return v
    if not isinstance(v, str) or not v or v == LOCAL_ACTOR["login"]:
        raise HTTPError(400, "assignee 는 'agent' 또는 사람의 로그인(문자열)입니다.")
    if v not in known_people(rows):
        raise HTTPError(400, "담당(assignee) '%s' 은(는) 이 뷰어가 아는 사람이 아닙니다 — 'agent' 또는 뷰어를 연 적 있는 테일넷 사람의 로그인을 쓰세요." % v)
    return v


def _set_assignee(r: dict, value, actor: dict, evs: list, record: bool) -> None:
    """Changes the assignee. If it changes (and record=True), leaves an ev=assign line in the thread, and if a person newly becomes the assignee, queues an assigned event."""
    if value is None or r.get("assignee") == value:
        return
    before = r.get("assignee")
    r["assignee"] = value
    if record:
        _thread_append(r, actor, "담당: " + ("에이전트" if value == ASSIGNEE_AGENT else "@" + _person_name(value)), ev="assign")
    if value != ASSIGNEE_AGENT and value != before:
        evs.append(make_event("assigned", r, actor, [value], text=r.get("note")))


def _person_name(login: str) -> str:
    return (known_people().get(login) or {}).get("name") or login


def clean_kind_req(v):
    """Pin kind - 'fix' (fix request) | 'question'. None if absent (= fix, same as a legacy pin)."""
    if v is None:
        return None
    if v not in KIND_REQS:
        raise HTTPError(400, "kind_req 는 %s 중 하나입니다." % "|".join(KIND_REQS))
    return v


def clean_thread_text(v, what: str = "text", required: bool = True):
    """One reply or reopen reason. Like a note, only string type and length are checked (the screen renders via esc()). Newlines are
    normalized to \\n and control characters (other than newline/tab) are stripped - so the pins.md table and notification bodies
    don't break. After trimming whitespace, an empty result is 400 (when required)."""
    if v is None:
        if required:
            raise HTTPError(400, "%s 가 필요합니다." % what)
        return None
    if not isinstance(v, str):
        raise HTTPError(400, "%s 는 문자열이어야 합니다." % what)
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    v = "".join(ch for ch in v if ch in "\n\t" or not (ord(ch) < 32 or 127 <= ord(ch) < 160)).strip()
    if len(v) > THREAD_TEXT_MAX:
        raise HTTPError(400, "%s 가 너무 깁니다(%d자 이하)." % (what, THREAD_TEXT_MAX))
    if not v:
        if required:
            raise HTTPError(400, "%s 가 비어 있습니다." % what)
        return None
    return v


def clean_loc(d: dict) -> dict:
    """Validates location fields into the shape to store. file must be inside the manuscript tree, and 1 <= lo <= hi <= line count."""
    out: dict = {}
    f = safe_src(d.get("file"))
    n = len(tex_lines(f))
    lo, hi = _int(d.get("lo"), "lo"), _int(d.get("hi"), "hi")
    if not 1 <= lo <= hi <= max(n, 1):
        raise HTTPError(400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (n, lo, hi))
    out.update(file=str(f), name=f.name, lo=lo, hi=hi)
    page = _int(d.get("page", 1), "page")
    if page < 1:
        raise HTTPError(400, "page 는 1 이상이어야 합니다.")
    out["page"] = page
    for k in ("raw_lo", "raw_hi"):
        if d.get(k) is not None:
            out[k] = _int(d[k], k)
    if d.get("kind") is not None:
        if not isinstance(d["kind"], str) or len(d["kind"]) > 80:
            raise HTTPError(400, "kind 가 올바르지 않습니다.")
        out["kind"] = d["kind"]
    if d.get("via") is not None:
        if d["via"] not in ("synctex", "text"):
            raise HTTPError(400, "via 는 synctex|text 입니다.")
        out["via"] = d["via"]
    if d.get("score") is not None:
        out["score"] = _num(d["score"], "score")
    if d.get("frac") is not None:
        fr = d["frac"]
        if not isinstance(fr, list) or len(fr) != 4:
            raise HTTPError(400, "frac 은 숫자 4개 목록입니다.")
        out["frac"] = [_num(x, "frac") for x in fr]
    if d.get("scope") is not None:
        if d["scope"] not in SCOPES:
            raise HTTPError(400, "scope 는 %s 중 하나입니다." % "|".join(SCOPES))
        out["scope"] = d["scope"]
    if d.get("quote") is not None:
        if not isinstance(d["quote"], str):
            raise HTTPError(400, "quote 는 문자열입니다.")
        out["quote"] = truncate_quote(d["quote"], 60)
    if d.get("pdf_build") is not None:                # the build on screen at drag time (pdf_build from the pick response)
        if not valid_build_name(d["pdf_build"]):
            raise HTTPError(400, "pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다.")
        out["pdf_build"] = d["pdf_build"]
    return out


PDF_QUOTE_MAX = 160               # region text for a view-only pin - more generous than 60 chars since there's no line number (material for the agent's judgment)
REGION_FIELDS = ("page", "frac", "note", "quote", "pdf_build")


def clean_frac(fr) -> list:
    """A view-only pin's location is region-only, so it's checked more strictly than a LaTeX pin: 4 numbers, within the page (0..1), positive area."""
    if not isinstance(fr, list) or len(fr) != 4:
        raise HTTPError(400, "frac 은 숫자 4개 목록 [x, y, w, h](쪽 대비 비율)입니다.")
    x, y, w, h = [_num(v, "frac") for v in fr]
    eps = 1e-6
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 + eps and 0 < h <= 1 + eps
            and x + w <= 1 + eps and y + h <= 1 + eps):
        raise HTTPError(400, "frac 이 쪽 밖입니다(0..1, 넓이 > 0).")
    return [x, y, w, h]


def clean_region(d: dict) -> dict:
    """A view-only document's (the current document's) pin location - page/region. lo/hi/file are not accepted."""
    D = cur_doc()
    for k in ("file", "lo", "hi", "scope"):
        if d.get(k) is not None:
            raise HTTPError(400, "보기 전용 문서(%s)의 핀에는 %s 가 없습니다 — 쪽(page)과 영역(frac)만 받습니다." % (D.key, k))
    out: dict = {"pdf": str(D.main), "name": D.main.name, "kind": "region"}
    page = _int(d.get("page"), "page")
    want = d.get("pdf_build")
    if want is not None and not valid_build_name(want):
        raise HTTPError(400, "pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다.")
    n = len(page_list(pages_dir_for(want)))
    if page < 1 or (n and page > n):
        raise HTTPError(400, "page 는 1..%d 이어야 합니다." % max(n, 1))
    out["page"] = page
    out["frac"] = clean_frac(d.get("frac"))
    if d.get("quote") is not None:
        if not isinstance(d["quote"], str):
            raise HTTPError(400, "quote 는 문자열입니다.")
        out["quote"] = truncate_quote(norm(d["quote"]), PDF_QUOTE_MAX)
    if want is not None:
        out["pdf_build"] = want
    return out


def request_doc(q: dict, body: dict = None, file_hint=None) -> Doc:
    """The document a request refers to: ?doc= or body doc. If neither is present, guessed from file (agent curl); if that's absent too, the first document.
    An unknown key is 404 - silently falling back to the first document would attach the pin to the wrong document."""
    key = (q.get("doc") or [None])[0] if q else None
    bkey = body.get("doc") if isinstance(body, dict) else None
    if bkey is not None and not isinstance(bkey, str):
        raise HTTPError(400, "doc 은 문자열이어야 합니다.")
    if key and bkey and key != bkey:
        raise HTTPError(400, "doc 이 주소(%s)와 본문(%s)에서 다릅니다." % (key, bkey))
    key = key or bkey
    if not key:
        if file_hint and multi_doc():
            return doc_for_file(file_hint)
        return DOCS[0]
    D = doc_by_key(key)
    if D is None:
        raise HTTPError(404, "없는 문서입니다: %s" % hdr_text(key)[:40], docs=[d.key for d in DOCS])
    return D


# ---------------------------------------------------------------- Pin operations

def add_pin(d: dict, actor: dict) -> int:
    """Saves a new pin from a POST /api/pin body for the current document (or the body's `doc`) -> its id. A LaTeX pin
    stores its location, anchor, the author and - since 0.3.2 (ADR-0006) - file_rel next to the absolute file; a view-only
    document gets a region pin. Queues mention/assigned events and emits them after the write. Validation errors are
    HTTPError(400) from the clean_* parsers (404 for an unknown doc), raised before anything is written."""
    D = cur_doc()
    want = d.get("doc")
    if isinstance(want, str) and want != D.key:        # if the body's doc differs from the current document, switch to that one (404 on an unknown key)
        other = request_doc({}, {"doc": want})
        with using_doc(other):
            return add_pin(dict(d, doc=other.key), actor)
    if D.is_pdf:
        return _add_region_pin(d, actor)
    body = {k: d[k] for k in ADD_FIELDS if k in d}
    rec = clean_loc(body)
    note = clean_note(body.get("note"))
    kind_req = clean_kind_req(d.get("kind_req"))
    hints = clean_mention_hints(d.get("mentions"))
    assignee = clean_assignee(d.get("assignee"))
    if "kind" not in rec:
        rec["kind"] = "lines"
    f = Path(rec["file"])
    lines = tex_lines(f)
    evs = []

    def fn(rows):
        """The transact() step: completes rec (id, author, mentions, anchor, build, rel_path) and appends it -> (id, True)."""
        rec["note"] = note
        rec["at"] = now_str()
        rec["id"] = next_id(rows)
        rec["author"] = dict(actor)
        if kind_req:
            rec["kind_req"] = kind_req
        _set_note_mentions(rec, rows, hints, actor, evs)
        _set_assignee(rec, assignee, actor, evs, record=False)
        rec["anchor"] = anchor_of(lines, rec["lo"], rec["hi"])
        rec["synced_at"] = f.stat().st_mtime if f.exists() else 0
        # Pins down which build's layout coordinates frac belongs to, by build identity (§Position estimation).
        # The viewer just echoes back pdf_build from the pick response (the build on screen at drag time) -
        # so a drag made right after a rebuild but before the screen switches still stays tagged to the old build.
        # A call that doesn't send it (agent curl) is treated as the current build.
        rec.setdefault("pdf_build", cur_pages().name)
        rec["doc"] = D.key
        rec["rev"] = 0
        stamp_location(rec, C.src)                   # ADR-0006: rel_path next to the absolute file
        rows.append(rec)
        return rec["id"], True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def _add_region_pin(d: dict, actor: dict) -> int:
    """A pin on a view-only document: {doc, pdf, name, page, frac, kind:'region', quote?, note, pdf_build}. No line or anchor."""
    D = cur_doc()
    rec = clean_region({k: d[k] for k in REGION_FIELDS + ("file", "lo", "hi", "scope") if k in d})
    note = clean_note(d.get("note"))
    kind_req = clean_kind_req(d.get("kind_req"))
    hints = clean_mention_hints(d.get("mentions"))
    assignee = clean_assignee(d.get("assignee"))
    evs = []

    def fn(rows):
        rec["note"] = note
        rec["at"] = now_str()
        rec["id"] = next_id(rows)
        rec["author"] = dict(actor)
        if kind_req:
            rec["kind_req"] = kind_req
        rec.setdefault("pdf_build", cur_pages().name)
        rec["doc"] = D.key
        rec["rev"] = 0
        _set_note_mentions(rec, rows, hints, actor, evs)
        _set_assignee(rec, assignee, actor, evs, record=False)
        rows.append(rec)
        return rec["id"], True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def edit_pin(pid: int, d: dict, actor: dict) -> dict:
    """Edits the note/range/location in place. id/at/done are never changed.

    If base_rev differs from the current rev, 409 - so a pin the agent closed, or one auto-line-matching
    already moved, is never silently overwritten with stale lo/hi."""
    has_note = "note" in d
    note = clean_note(d.get("note")) if has_note else None
    note_append = d.get("note_append")
    if note_append is not None:
        if not isinstance(note_append, str):
            raise HTTPError(400, "note_append 는 문자열이어야 합니다.")
        if not note_append.strip():
            raise HTTPError(400, "덧붙일 메모가 비어 있습니다.")
        if len(note_append) > 2000:
            raise HTTPError(400, "덧붙일 메모가 너무 깁니다(2000자 이하).")
    loc = d.get("loc")
    if loc is not None and not isinstance(loc, dict):
        raise HTTPError(400, "loc 는 객체여야 합니다.")
    lo = _int(d["lo"], "lo") if d.get("lo") is not None else None
    hi = _int(d["hi"], "hi") if d.get("hi") is not None else None
    scope = d.get("scope")
    if scope is not None and scope not in SCOPES:
        raise HTTPError(400, "scope 는 %s 중 하나입니다." % "|".join(SCOPES))
    kind = d.get("kind")
    if kind is not None and (not isinstance(kind, str) or len(kind) > 80):
        raise HTTPError(400, "kind 가 올바르지 않습니다.")
    kind_req = clean_kind_req(d.get("kind_req"))   # pin kind (fix request/question) - a note-level value that can be changed even on a closed pin
    hints = clean_mention_hints(d.get("mentions"))
    assignee = clean_assignee(d.get("assignee"))   # assignee - like kind_req, can be changed even on a closed pin. Changing it leaves an ev=assign in the thread
    evs = []
    base_given = "base_rev" in d
    if not base_given and note_append is None:
        raise HTTPError(400, "base_rev 가 필요합니다(카드를 열 때 받은 rev).")
    base = _int(d["base_rev"], "base_rev") if base_given else None
    moves = loc is not None or lo is not None or hi is not None
    if not (has_note or moves or scope is not None or kind is not None or note_append is not None or kind_req is not None
            or assignee is not None):
        raise HTTPError(400, "바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append, kind_req, assignee).")
    # Location validation and the default build are scoped to that pin's document (even if the request omits ?doc=). A pin's kind (LaTeX/view-only) never changes.
    r0 = find_pin(read_pins()[0], pid)
    region = r0 is not None and is_region_pin(r0)
    pdoc = (doc_by_key(pin_doc_key(r0)) if r0 is not None else None) or cur_doc()
    if region and (lo is not None or hi is not None or scope is not None or kind is not None):
        raise HTTPError(400, "보기 전용 문서의 핀에는 줄 범위가 없습니다 — 메모(note)와 영역(loc: page, frac)만 고칩니다.")
    with using_doc(pdoc):
        if region:
            newloc = clean_region(loc) if loc is not None else None
        else:
            newloc = clean_loc(loc) if loc is not None else None
        if newloc is not None:
            # pdf_build records which build frac's coordinates belong to - a loc that doesn't re-place frac cannot change this value.
            if "frac" in loc:
                newloc.setdefault("pdf_build", cur_pages().name)
            else:
                newloc.pop("pdf_build", None)

    def fn(rows):
        """The transact() step: applies the validated edit to pin pid, records where its file is now (stamp_location) and
        bumps rev -> (public pin, True). Raises HTTPError 404 (no pin), 409 (closed pin moved, stale base_rev) or 400
        (a range outside the file, or a pin outside the manuscript tree) before changing anything."""
        r = find_pin(rows, pid)
        if r is None:
            raise HTTPError(404, "핀 #%d 이 없습니다." % pid)
        if r.get("done") and (moves or scope is not None or kind is not None):
            raise HTTPError(409, "done", pin=public(r), detail="닫힌 핀은 메모만 고칠 수 있습니다.")
        if base_given and int(r.get("rev") or 0) != base:
            raise HTTPError(409, "conflict", pin=public(r))
        old_note = str(r.get("note") or "")         # to tell a new @-tag from one the note already had (_set_note_mentions)
        merged = None
        if note_append is not None:                  # checked before anything changes: transact() may still write rows on a 400
            base_note = note if has_note else old_note
            stamp = "(추가 %s) " % datetime.now().astimezone().strftime("%H:%M")
            merged = base_note + ("\n" if base_note else "") + stamp + note_append
            if len(merged) > NOTE_MAX:
                raise HTTPError(400, "덧붙이면 메모가 너무 깁니다(%d자, %d자 이하)." % (len(merged), NOTE_MAX))
        range_changed = False
        if region:
            if newloc is not None:                   # re-placing the region - only page/region/region text/build change
                for k in ("page", "frac", "quote", "pdf_build"):
                    if k in newloc:
                        r[k] = newloc[k]
                    elif k == "quote":
                        r.pop("quote", None)
        elif newloc is not None:
            # page/frac not present in loc are left as-is - so page doesn't snap back to 1 just because the agent sent only file/lo/hi.
            keep = {k: r[k] for k in ("page", "frac") if k not in loc and k in r}
            for k in LOC_FIELDS:
                r.pop(k, None)
            r.update(newloc)
            r.update(keep)
            if "kind" not in newloc:                 # same default as add
                r["kind"] = kind if kind is not None else "lines"
            if scope is not None and "scope" not in newloc:
                r["scope"] = scope
            if "frac" in loc:                        # build identity only changes when frac was actually re-placed
                r.pop("frac_build", None)            # legacy field name (83b91a5) - superseded by pdf_build
            range_changed = True
        elif lo is not None or hi is not None:
            a = lo if lo is not None else r["lo"]
            b = hi if hi is not None else r["hi"]
            here = pin_location(r, C.src)
            if here is None:
                raise HTTPError(400, "원고 디렉토리 밖을 가리키는 핀입니다 — 위치 다시 잡기(loc)로 고치세요.")
            n = len(tex_lines(here.path))
            if not 1 <= a <= b <= max(n, 1):
                raise HTTPError(400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (n, a, b))
            range_changed = (a, b) != (r["lo"], r["hi"]) or bool(r.get("stale"))
            r["lo"], r["hi"] = a, b
            if range_changed:                        # a manually moved range is no longer the result of coordinate/text matching
                r.pop("via", None)
                r.pop("score", None)
        if newloc is None:
            if scope is not None:
                r["scope"] = scope
            if kind is not None:
                r["kind"] = kind
        where = None if region else stamp_location(r, C.src)   # ADR-0006: an edit records where the file is now
        if range_changed and where is not None:
            f = where.path
            r["anchor"] = anchor_of(tex_lines(f), r["lo"], r["hi"])
            r["synced_at"] = f.stat().st_mtime if f.exists() else 0
            r.pop("stale", None)
            r.pop("sync", None)
        if has_note:
            r["note"] = note
        if merged is not None:
            r["note"] = merged
        if kind_req is not None:
            r["kind_req"] = kind_req
        if has_note or note_append is not None:
            _set_note_mentions(r, rows, hints, actor, evs, old_note)
        _set_assignee(r, assignee, actor, evs, record=True)
        r["edited_at"] = now_str()
        r["edited_by"] = who(actor)
        r["rev"] = next_rev(r)
        return public(r), True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def _msg_by(actor: dict) -> dict:
    """The thread author - adds an avatar (pic) to who() (the card renders a 22px circle)."""
    out = who(actor)
    if isinstance(actor.get("pic"), str) and actor["pic"]:
        out["pic"] = actor["pic"]
    return out


def _thread_append(r: dict, actor: dict, text: str = "", ev: str = None, ref: str = None, mentions=None) -> dict:
    """Appends one entry to the thread (only after the caller has finished validating, and only inside transact). id increments from 1 within a pin and is never reused.

    ev (close/reopen/confirm) is a state-transition record - the close reason (reply) and reopen reason are recorded in the same single-line history as replies."""
    th = r.get("thread") if isinstance(r.get("thread"), list) else []
    msg = thread_message(th, _msg_by(actor), now_str(), text, ev=ev, ref=ref, mentions=mentions)
    r["thread"] = th + [msg]
    return msg


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
    fixes a typo next to an existing '@Bob' (_set_note_mentions)."""
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


def clean_mention_hints(v) -> list:
    if v is None:
        return []
    if not _is_str_list(v) or len(v) > MENTION_MAX:
        raise HTTPError(400, "mentions 는 로그인 문자열 목록(%d개 이하)입니다." % MENTION_MAX)
    return v


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


def _set_note_mentions(r: dict, rows: list, hints, actor: dict, evs: list, old_note: str = "") -> None:
    """Resolves the note's @-tags into r['mentions'] (drops the field if none). Queues a mention event for everyone
    this save or edit explicitly @-tags: a person whose '@name' occurs more often in the new note than in old_note
    (the note before this edit; empty for a new pin). A typo fix next to an existing '@Bob' notifies nobody, while
    an edit or note_append that writes '@Bob' again notifies Bob even though the note already tagged him - unless
    this actor's note already notified him about this pin within NOTE_MENTION_COOLDOWN_S (note_mention_targets).
    Runs inside transact(): the caller emits the queued events under the same PIN_LOCK, so the next save sees them."""
    ppl = known_people(rows)
    me = (actor or {}).get("login")
    hits = mention_hits(r.get("note") or "", ppl, hints, exclude=me)
    before = Counter(mention_hits(old_note or "", ppl, hints, exclude=me))
    new = list(dict.fromkeys(hits))
    if new:
        r["mentions"] = new
    else:
        r.pop("mentions", None)
    counts = Counter(hits)
    added = [lg for lg in new if counts[lg] > before[lg]]
    if added:
        added = note_mention_targets(added, _read_events()[0], me, r.get("id"), time.time())
    evs.append(make_event("mention", r, actor, added, text=r.get("note")))


NOTIFY_TYPES = ("mention", "review_requested", "replied", "reopened", "assigned", "dropped")
EVENTS_SINCE_MAX = 20


def events_since(actor: dict, cursor) -> dict:
    """Notification material carried in /api/meta polling (docs/handbook/api.md §브라우저 알림 커서). Always includes ev_seq (the latest event number), and if
    ev=<number> is given, includes up to 20 events after it addressed to the current requester's tailnet login - nothing for local/agent. Read-only."""
    rows, _ = _read_events()
    out = {"ev_seq": max((e.get("seq", 0) for e in rows), default=0)}
    if cursor is None:
        return out
    try:
        cur = int(cursor)
    except (TypeError, ValueError):
        raise HTTPError(400, "ev 는 정수(마지막으로 본 이벤트 seq)입니다.") from None
    me = (actor or {}).get("login")
    if not me or is_agent(actor):
        out["events"] = []
        return out
    names = {d.key: d.name for d in DOCS}
    evs = [dict(e, doc_name=names.get(e.get("doc"), e.get("doc"))) for e in rows
           if e.get("seq", 0) > cur and e.get("type") in NOTIFY_TYPES and me in (e.get("to") or [])
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


def clean_reopen_flag(d: dict):
    """The reply body's optional reopen - true/false overrides the rule, absent (None) lets the server decide."""
    v = d.get("reopen")
    if v is not None and not isinstance(v, bool):
        raise HTTPError(400, "reopen 은 true/false 입니다(없으면 서버 규칙을 따릅니다).")
    return v


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


def clean_review_flag(d: dict):
    """The close body's optional review - true means awaiting review, false means done right away. None if absent (left to the closer to decide)."""
    v = d.get("review")
    if v is not None and not isinstance(v, bool):
        raise HTTPError(400, "review 는 true/false 입니다.")
    return v


def set_done(pid: int, done: bool, actor: dict, reply: str | None = None, ref: str | None = None,
             review: bool | None = None, reason: str | None = None, hints=None, changes: Changes | None = None):
    """Close (done=True) or reopen (done=False) - the single entry POST /close and /reopen and older callers use.

    `reply`/`ref`/`changes` (already validated by clean_close_body/clean_close_changes) and `review` belong to a
    close; `reason` and `hints` to a reopen. The rules are in limn.pins.lifecycle; see close_pin and reopen_pin.
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
    """Rewrites pins.dropped.jsonl. Unreadable lines are never dropped silently: the original bytes are kept in a
    .corrupt-*.bak first, as write_pins does for pins.jsonl."""
    if bad and C.dropped.exists():
        shutil.copy2(C.dropped, unique_path("pins.dropped.jsonl.corrupt-%s" % time.strftime("%Y%m%d-%H%M%S"), ".bak"))
    atomic_write(C.dropped, dump_jsonl(rows))


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




def _claim_int(d: dict, key: str, lo: int, hi: int):
    """One optional integer from the body. None if absent. 400 if not an integer or below lo; clamped to hi if it exceeds the ceiling.

    Clamping is for backward compatibility - so an agent that still sends the old ttl_min=480 doesn't break
    when trying to extend with the same value after the ceiling was lowered to 120, instead of getting a 400.
    The value actually applied is returned as *_applied in the response."""
    if key not in d:
        return None
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or int(v) != v:
        raise HTTPError(400, "%s 은 정수여야 합니다." % key)
    v = int(v)
    if v < lo:
        raise HTTPError(400, "%s 은 %d 이상이어야 합니다(상한 %d 를 넘으면 %d 로 깎아 받습니다)." % (key, lo, hi, hi))
    return min(v, hi)


def clean_claim_body(d: dict) -> tuple:
    """The claim body -> (ttl_min, eta_min or None). Both are optional.

    eta_min (1..240) is the estimated time to handle - shown in the viewer as "in progress - about 15 min -
    around 20:40". ttl_min (1..120) is the time until the lock auto-expires (a safety net). Values past the
    ceiling are clamped to it (compatible with the legacy ttl_min 480). If ttl_min is omitted, it's
    min(120, max(30, eta x 2)) when eta_min is given, otherwise 120."""
    eta = _claim_int(d, "eta_min", CLAIM_ETA_MIN, CLAIM_ETA_MAX)
    ttl = _claim_int(d, "ttl_min", CLAIM_TTL_MIN, CLAIM_TTL_MAX)
    if ttl is None:
        ttl = min(CLAIM_TTL_MAX, max(CLAIM_TTL_FLOOR, eta * 2)) if eta is not None else CLAIM_TTL_DEFAULT
    return ttl, eta


def clean_claim_ttl(d: dict) -> int:
    """Compatibility for legacy callers - just the ttl from clean_claim_body."""
    return clean_claim_body(d)[0]


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
        n, archive = len(read_pins()[0]), None
        if C.pins_jsonl.exists():                    # clearing twice in the same second never overwrites the earlier archive
            dest = unique_path("pins_%s" % time.strftime("%y%m%d_%H%M%S"), ".jsonl.bak")
            C.pins_jsonl.rename(dest)
            archive = dest.name
        render_pins_md([])
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
    atomic_write(C.pins_md, pins_md_text(rows))


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
        head_short, built_at = _read_head(), _read_built_at()
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
        with using_doc(d):
            head_short, built_at = _read_head(), _read_built_at()
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

def pick(d: dict) -> dict:
    """Dragged region -> source line range + range ladder.

    Pits the SyncTeX candidate and the text candidate against each other on equal footing. Treating either
    as a conditional fallback leaves no way to catch SyncTeX being silently wrong (inside minipage/tabular).

    pdf_build (optional) is the build on screen at drag time (META.pages_build). A drag made after a rebuild
    finishes but before the viewer switches pages uses coordinates from the old layout, so it's traced back
    against that build's PDF and returned as pdf_build in the response - the viewer carries that value
    through unchanged when saving the pin (/api/pin) to record "which build's coordinates these are" (§Position estimation)."""
    want = d.get("pdf_build")
    if want is not None:
        if not valid_build_name(want):
            raise HTTPError(400, "pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다.")
        if not (cur_doc().dir / want).is_dir():
            return {"error": "화면의 PDF 가 이미 지워진 옛 빌드입니다 — 화면을 새 PDF 로 바꿨으니 다시 고르세요.",
                    "pdf_build_gone": True}
    pdir = pages_dir_for(want) if want is not None else cur_pages()
    pages = page_list(pdir)
    page = _int(d.get("page"), "page")
    if not 1 <= page <= len(pages):
        raise HTTPError(400, "page 는 1..%d 이어야 합니다." % len(pages))
    pw, ph = pages[page - 1]["pt_w"], pages[page - 1]["pt_h"]
    xs = sorted(min(max(_num(d.get(k), k), 0.0), pw) for k in ("x0", "x1"))
    ys = sorted(min(max(_num(d.get(k), k), 0.0), ph) for k in ("y0", "y1"))
    x0, x1 = xs
    y0, y1 = ys
    frac = d.get("frac")
    if frac is not None and not (isinstance(frac, list) and len(frac) == 4 and
                                 all(not isinstance(v, bool) and isinstance(v, (int, float))
                                     and math.isfinite(v) for v in frac)):
        raise HTTPError(400, "frac 은 숫자 4개 목록입니다.")

    pdf = cur_pdf(pdir)
    rtext = region_text(pdf, page, x0, y0, x1, y1)
    D = cur_doc()
    if D.is_pdf:
        return _pick_region(D, pdir, page, (x0, y0, x1, y1), (pw, ph), frac, rtext)
    sy = by_synctex(pdf, page, x0, y0, x1, y1)

    src = to_source(sy[0]) if sy else D.main
    if src.suffix in (".bbl", ".bib"):
        return {"error": "여기는 생성 파일(%s)입니다. 참고문헌은 .bib 나 본문 \\cite 를 고쳐야 합니다."
                         % src.suffix}
    try:
        src = safe_src(str(src))
    except HTTPError:
        return {"error": "SyncTeX 가 원고 밖 파일을 가리킵니다(%s). PDF 재빌드 뒤 다시 골라 보세요." % src}

    lines = tex_lines(src)
    if not lines:
        return {"error": "원문 파일을 읽지 못했습니다: %s" % src}
    tw = token_weights(rtext, lines, file_key(src))

    cands = []
    if sy:
        cands.append(("synctex", sy[1], sy[2], score_range(tw, lines, sy[1], sy[2])))
    alt = by_text(tw, lines, sy[1] if sy else None)
    if alt:
        cands.append(("text", alt[0], alt[1], alt[2]))
    if not cands:
        return {"error": "그 자리에서 원문을 되짚지 못했습니다. 글자가 있는 쪽으로 조금 넓게 잡아 보세요."}

    # On a tie, SyncTeX wins - it's the only one that's right in a region with no text (a figure).
    cands.sort(key=lambda c: (-c[3], c[0] != "synctex"))
    via, raw_lo, raw_hi, best = cands[0]
    warn = ""
    if tw and best < 0.3:
        warn = "이 영역은 원문 대조가 약합니다(%.0f%%). 줄 범위를 눈으로 확인하세요." % (best * 100)

    lad = compute_levels(lines, raw_lo, raw_hi, C.envs)
    lo, hi = lad["lo"], lad["hi"]
    if not warn and len(cands) == 2 and abs(cands[0][3] - cands[1][3]) < 0.12:
        # If both expand into the same block, the two paths haven't actually diverged - don't warn.
        if not (lo <= cands[1][1] <= hi):
            warn = "두 경로가 다른 곳을 가리킵니다(L%d / L%d). 확인이 필요합니다." % (cands[0][1], cands[1][1])

    if source_newer(pdir.name) > 2:
        stale_note = "화면의 PDF 가 지금 원고보다 낡았습니다 — [PDF 재빌드] 뒤에 다시 고르세요."
        warn = stale_note + (" " + warn if warn else "")
    bstate = build_state_snapshot()
    if bstate["state"] == "running" and bstate["phase"] == "latex":
        warn = (warn + " " if warn else "") + "빌드 중이라 결과가 흔들릴 수 있습니다."

    quote = truncate_quote(norm(rtext), 60)
    return {"file": str(src), "name": src.name, "page": page, "lo": lo, "hi": hi,
            "raw_lo": raw_lo, "raw_hi": raw_hi, "kind": lad["kind"], "via": via,
            "score": round(best, 2), "warn": warn, "n_lines": len(lines),
            "snippet": snippet(lines, lo, hi), "frac": frac, "quote": quote,
            "levels": lad["levels"], "default_level": lad["default_level"],
            "overlaps": overlaps_for_range(str(src), lo, hi), "pdf_build": pdir.name}


def _pick_region(D: Doc, pdir: Path, page: int, box: tuple, size: tuple, frac, rtext: str) -> dict:
    """pick for a view-only document - returns only page/region and the region's text (pdftotext), no SyncTeX.
    If frac wasn't sent (agent curl), it's built from the coordinates - for a view-only pin, the region is the whole location."""
    x0, y0, x1, y1 = box
    pw, ph = size
    if frac is None:
        frac = [x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph]
    text = norm(rtext)
    warn = ""
    if not text:
        warn = "이 영역에는 글자가 없습니다(그림·스캔본). 메모에 무엇을 가리키는지 적어 주세요."
    bstate = build_state_snapshot()
    if bstate["state"] == "running":
        warn = (warn + " " if warn else "") + "PDF 가 바뀌어 쪽을 다시 그리는 중입니다 — 끝나면 다시 고르세요."
    return {"doc": D.key, "kind": "region", "view_only": True, "page": page, "frac": frac,
            "pdf": D.rel_path(), "name": D.main.name, "quote": truncate_quote(text, PDF_QUOTE_MAX),
            "n_chars": len(text), "warn": warn, "overlaps": [], "pdf_build": pdir.name}


def snippet_api(q: dict) -> dict:
    if cur_doc().is_pdf:
        raise HTTPError(400, "보기 전용 문서(%s)에는 원문 줄이 없습니다." % cur_doc().key)
    f = safe_src((q.get("file") or [""])[0])
    lines = tex_lines(f)
    try:
        lo = int((q.get("lo") or [""])[0])
        hi = int((q.get("hi") or [""])[0])
    except ValueError:
        raise HTTPError(400, "lo·hi 는 정수여야 합니다.") from None
    if not 1 <= lo <= hi <= len(lines):
        raise HTTPError(400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (len(lines), lo, hi))
    out = {"file": str(f), "name": f.name, "lo": lo, "hi": hi, "n": hi - lo + 1,
           "n_lines": len(lines), "snippet": snippet(lines, lo, hi)}
    if (q.get("levels") or ["0"])[0] == "1":
        lad = compute_levels(lines, lo, hi, C.envs)
        out["levels"] = lad["levels"]
        out["default_level"] = lad["default_level"]
    return out


def overlaps_api(q: dict) -> dict:
    """GET /api/overlaps — asks about a not-yet-saved selection's overlap using only file/range (kept for agent/legacy-viewer compatibility).

    The current viewer instead recomputes the same rule (overlapsFor) locally against its own PINS on every
    range change, with no round trip - because pressing [Save Pin] while a response is still in flight could
    otherwise save a duplicate with no banner shown. This path was called by the 83b91a5 viewer."""
    f = safe_src((q.get("file") or [""])[0])
    lines = tex_lines(f)
    try:
        lo = int((q.get("lo") or [""])[0])
        hi = int((q.get("hi") or [""])[0])
    except ValueError:
        raise HTTPError(400, "lo·hi 는 정수여야 합니다.") from None
    if not 1 <= lo <= hi <= len(lines):
        raise HTTPError(400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (len(lines), lo, hi))
    return {"overlaps": overlaps_for_range(str(f), lo, hi)}


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
        raise HTTPError(401, "Authorization: Bearer 헤더가 올바르지 않습니다.")
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
            raise HTTPError(401, "토큰이 올바르지 않거나 폐기되었습니다.")
        return Principal({"login": AGENT_LOGIN_PREFIX + t["name"], "name": t["name"]}, "agent", "token")
    loop = peer_is_loopback(peer)
    if C.auth == "local":
        if loop and came_through_proxy(headers):
            # every local request is the owner - one that came through a proxy is someone else (v0.2.1 hardening)
            raise HTTPError(403, TAILNET_HEADERLESS, page=("no-identity", {}))
        if loop:
            return Principal(local_owner_actor(), "owner", "local-owner")
        raise HTTPError(401, UNAUTHENTICATED)
    if C.auth == "trusted-proxy":
        a = proxy_actor(headers) if peer_is_trusted_proxy(peer) else None
        if a is None or not valid_login(a["login"]):
            raise HTTPError(401, UNAUTHENTICATED)
        return Principal(a, role_of(a["login"]), "header")
    if loop:
        a, via = actor_of(headers)
        if via:
            if not valid_login(a["login"]):
                raise HTTPError(401, UNAUTHENTICATED)
            return Principal(a, role_of(a["login"]), "header")
        if C.agent_loopback:
            if came_through_proxy(headers) and not C.tailnet_agent:
                # tailscale serve connects from loopback too. Without identity headers such a request is a tagged
                # device (or anything else behind the proxy) - never the local agent (v0.2.1).
                raise HTTPError(403, TAILNET_HEADERLESS, page=("no-identity", {}))
            warn_loopback_agent_once()
            return Principal(dict(LOCAL_ACTOR), "agent", "loopback-agent")
        if not came_through_proxy(headers):
            # An agent on this machine with the loopback agent off (ADR-0007): say where its token file is.
            f = C.agent_token_file
            raise HTTPError(401, loopback_refused_text(f, file_present(f), home_or_none()))
    raise HTTPError(401, UNAUTHENTICATED)


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
                                page=("not-member", {"login": login}))
        elif C.allow and login not in C.allow:
            raise HTTPError(403, "이 뷰어에 허용되지 않은 계정입니다: %s" % login, page=("not-allowed", {"login": login}))
    elif p.via == "loopback-agent" and (C.allow or C.members_only):
        hname, _ = split_host(host or "")
        if hname.endswith(".ts.net") or (headers is not None and came_through_proxy(headers)):
            raise HTTPError(403, "신원 헤더 없는 테일넷 요청입니다(태그 장치 등). --allow 목록의 계정으로 접속하세요.",
                            page=("no-identity", {}))


def check_role(p: Principal, path: str) -> None:
    """Role rule for state-changing (POST) requests, applied once in the handler before dispatch. A viewer may only
    run computations (/api/pick, /api/revision-build); an agent may do everything but confirm; editor and owner may
    do everything a person could in v0.1, except the bulk-destructive OWNER_POSTS (/api/clear, v0.2.1) and the permanent
    delete from the Trash (OWNER_POST_RE, v0.2.2), which only the owner may call. Other owner-only operations - members, tokens, settings - are CLI/file level."""
    if p.role == "viewer" and path not in VIEWER_POSTS:
        raise HTTPError(403, "보기 권한(viewer)만 있는 계정입니다 — 핀·답글·닫기 같은 변경은 할 수 없습니다.")
    if p.role == "agent" and re.fullmatch(r"/api/pins/\d+/confirm", path):
        raise HTTPError(403, CONFIRM_BY_HUMAN)
    if path in OWNER_POSTS and p.role != "owner":
        raise HTTPError(403, "모든 핀을 지우는 일은 소유자(owner)만 합니다 — 에이전트·편집자는 핀을 하나씩 닫으세요.")
    if OWNER_POST_RE.fullmatch(path) and p.role != "owner":
        raise HTTPError(403, "휴지통에서 영구 삭제는 소유자(owner)만 합니다 — 삭제한 핀은 %d일 뒤 저절로 지워집니다." % TRASH_DAYS)


# ---------------------------------------------------------------- Viewer

VIEWER_DIR = Path(__file__).resolve().parent / "viewer"
VIEWER_MARKERS = ("__APP_CSS__", "__APP_JS__")


def load_viewer_html(directory: Path) -> str:
    """The viewer page with its stylesheet and main script inlined, as one HTML string.

    index.html carries one __APP_CSS__ and one __APP_JS__ marker; app.css and app.js hold the text that
    goes there, byte for byte. Inlining keeps GET / a single response with no extra routes. A missing or
    malformed file is a packaging defect and raises at import (OSError / ValueError).
    """
    page = (directory / "index.html").read_text(encoding="utf-8")
    parts = {"__APP_CSS__": (directory / "app.css").read_text(encoding="utf-8"),
             "__APP_JS__": (directory / "app.js").read_text(encoding="utf-8")}
    for marker, text in parts.items():
        if page.count(marker) != 1 or any(m in text for m in VIEWER_MARKERS):
            raise ValueError("viewer template marker %s must appear exactly once in index.html" % marker)
        page = page.replace(marker, text)
    return page


HTML = load_viewer_html(VIEWER_DIR)
HTML = HTML.replace("__PDFJS_VERSION__", PDFJS_VERSION)
HTML = HTML.replace("__LUCIDE_JSON__", json.dumps(LUCIDE, sort_keys=True))
HTML = HTML.replace("__UI_EN_JSON__", json.dumps(UI_EN, ensure_ascii=False, sort_keys=True).replace("</", "<\\/"))
HTML = ICON_TOKEN_RE.sub(lambda m: icon_svg(m.group(1)), HTML)


# A browser that opens the viewer (GET / asking for HTML) and is refused gets a short page instead of raw JSON (v0.2.1).
# The Korean text is the key into the viewer's message table (ui_en.json), so the page follows the same ko/en table.
ERROR_PAGE_TEXT = {
    "not-member": ("이 뷰어의 멤버가 아닙니다: {login}", "이 뷰어의 소유자에게 멤버로 추가해 달라고 요청하세요: limn member add <인스턴스> {login}"),
    "not-allowed": ("이 뷰어에 허용되지 않은 계정입니다: {login}", "이 뷰어의 소유자에게 --allow 목록에 넣어 달라고 요청하세요"),
    "no-identity": ("신원을 확인할 수 없는 요청입니다",
                    "사람 계정으로 로그인한 장치에서 여세요. 에이전트는 토큰(Authorization: Bearer)을 씁니다: limn token create <인스턴스>"),
}


# Expected refusals of pin scoping (ScopeRejected.reason) -> (status, message, API reason or None). The one place they
# become responses - Handler._run for requests, the revision worker for the build status it stores. The messages and
# reasons are part of the agent contract (api.md §핀 단위 변경 보기); tests pin every body.
SCOPE_REJECTIONS = {
    "pin_not_in_doc": (404, "이 문서의 핀이 아닙니다.", None),
    "scope_unreadable": (422, "이 핀의 변경만 골라 적용하지 못했습니다.", "scope_failed"),
    "scope_mismatch": (422, "이 핀의 변경을 커밋에서 다시 찾지 못했습니다.", "scope_failed"),
    "unsafe_path": (422, "사본에 허용되지 않는 경로가 있습니다.", "unsafe_snapshot"),
    "scope_unwritable": (422, "이 핀의 변경만 넣은 사본을 쓰지 못했습니다.", "scope_failed"),
}


def scope_http_error(e: ScopeRejected) -> HTTPError:
    """The HTTP form of a pin-scoping refusal, from SCOPE_REJECTIONS. An unknown reason is a bug: KeyError, a 500."""
    code, msg, reason = SCOPE_REJECTIONS[e.reason]
    return HTTPError(code, msg, reason=reason) if reason else HTTPError(code, msg)


def page_lang(headers, query: dict) -> str:
    """ko or en for a server-rendered page: ?lang=, else the first Accept-Language tag (ko* -> ko), else en - the viewer's rule."""
    v = (query.get("lang") or [""])[0]
    if v in ("ko", "en"):
        return v
    first = (headers.get("Accept-Language") or "").split(",")[0].strip().lower()
    return "ko" if first.startswith("ko") else "en"


def ui_text(key: str, lang: str, **params) -> str:
    """One message from the viewer's table, filled in (the server-side twin of the viewer's tl())."""
    v = UI_EN.get(key, key) if lang == "en" else key
    if isinstance(v, dict):
        v = v.get("other", key)
    for k, x in params.items():
        v = v.replace("{%s}" % k, str(x))
    return v


def error_page_html(e: HTTPError, lang: str) -> str:
    kind, params = e.page or ("", {})
    if kind in ERROR_PAGE_TEXT:
        head, hint = (ui_text(k, lang, **params) for k in ERROR_PAGE_TEXT[kind])
        detail = ""
    else:
        head, hint = ui_text("이 뷰어를 열 수 없습니다 ({code})", lang, code=e.code), ""
        detail = str(e.body.get("error") or "")
    other = "en" if lang == "ko" else "ko"
    esc = html.escape
    return ("<!doctype html><html lang=\"%s\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Limn · %s</title>"
            "<style>body{font:15px/1.6 -apple-system,BlinkMacSystemFont,\"Pretendard\",\"Noto Sans KR\",sans-serif;max-width:36rem;"
            "margin:15vh auto;padding:0 1.25rem;color:#18181b;background:#fafafa}h1{font-size:1.15rem;margin:0 0 .6rem}"
            "p{margin:.4rem 0;color:#3f3f46}code,.d{font:13px ui-monospace,monospace;word-break:break-all}"
            "a{color:#1860cf}@media(prefers-color-scheme:dark){body{color:#fafafa;background:#09090b}p{color:#a1a1aa}a{color:#6ea8fe}}"
            "</style></head><body><h1>%s</h1>%s%s<p><a href=\"/?lang=%s\">%s</a></p></body></html>"
            % (lang, esc(str(e.code)), esc(head), "<p>%s</p>" % esc(hint) if hint else "",
               "<p class=\"d\">%s</p>" % esc(detail) if detail else "", other, "English" if other == "en" else "한국어"))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128          # so dozens of concurrent requests don't stall a second at a time on SYN retransmits


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # If the body arrives shorter than Content-Length and the connection never closes, the read would hang forever. Idle keep-alive connections are also closed after this time.
    timeout = 30

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype: str, cache: str = None):
        if code >= 400:
            # The connection is closed after an error. The request may not have been read to completion, and
            # if the leftover bytes get read as the next request, they'd bypass --allow and author attribution (request smuggling).
            self.close_connection = True
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache is None or code >= 400:
            cache = "public, max-age=600" if ctype == "image/png" and code < 400 else "no-store"
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        if code == 401:
            self.send_header("WWW-Authenticate", 'Bearer realm="limn"')
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _restore_answer(self, result: OpenPin | ReviewPin | DonePin | NotInTrash | AlreadyLive) -> None:
        """Answer POST /api/pins/{id}/restore: the pin back in the list, or 404/409 with the old messages."""
        match result:
            case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
                return self._json({"ok": True, "pin": public(record)})
            case NotInTrash(pid=pid):
                raise HTTPError(404, "삭제 기록에 핀 #%d 이 없습니다." % pid)
            case AlreadyLive(pid=pid):
                raise HTTPError(409, "핀 #%d 이 이미 있습니다." % pid)

    def _claim_answer(self, result: OpenPin | ClaimClosedPin | ClaimedByOther | PinNotFound, ttl: int,
                      eta: int | None) -> None:
        """Answer POST /api/pins/{id}/claim: the pin and the ttl/eta actually applied (clamped values), or a 409."""
        match result:
            case OpenPin(record=record):
                out = {"ok": True, "pin": public(record), "ttl_min_applied": ttl}
            case PinNotFound():
                out = {"ok": False, "pin": None, "ttl_min_applied": ttl}
            case ClaimClosedPin(pin=ReviewPin(record=record) | DonePin(record=record)):
                raise HTTPError(409, "done", pin=public(record))
            case ClaimedByOther(claimed_by=holder, claim_until=until, eta_ts=eta_ts):
                raise HTTPError(409, "claimed", claimed_by=holder, claim_until=until, eta_ts=eta_ts)
        if eta is not None:
            out["eta_min_applied"] = eta              # the clamped value, if sent above the ceiling (240)
        return self._json(out)

    def _unclaim_answer(self, result: OpenPin | ReviewPin | DonePin | NotClaimed | PinNotFound) -> None:
        """Answer POST /api/pins/{id}/unclaim: the pin as it stands (no claim), or ok:false for an unknown id."""
        match result:
            case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
                return self._json({"ok": True, "pin": public(record)})
            case NotClaimed(pin=OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record)):
                return self._json({"ok": True, "pin": public(record)})
            case PinNotFound():
                return self._json({"ok": False, "pin": None})

    def _reply_answer(self, result: OpenPin | ReviewPin | DonePin | ThreadFull | PinNotFound) -> None:
        """Answer POST /api/pins/{id}/reply: the pin, its new thread entry, its state and whether the reply reopened it."""
        match result:
            case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
                msg = record["thread"][-1]
                return self._json({"ok": True, "pin": public(record), "msg": msg, "state": pin_state(record),
                                   "reopened": msg.get("ev") == "reopen"})
            case ThreadFull(limit=limit):
                raise HTTPError(409, "full", detail="스레드가 가득 찼습니다(답글 %d건). 새 핀으로 이어 가세요." % limit)
            case PinNotFound():
                return self._json({"ok": False, "pin": None, "msg": None, "state": None, "reopened": False})

    def _state_reply(self, result: OpenPin | ReviewPin | DonePin | AlreadyClosed | PinNotFound) -> None:
        """Answer POST /api/pins/{id}/close and /reopen: the pin as it stands now and its state, or ok:false."""
        match result:
            case OpenPin(record=record) | ReviewPin(record=record) | DonePin(record=record):
                return self._json({"ok": True, "pin": public(record), "state": pin_state(record)})
            case AlreadyClosed(pin=ReviewPin(record=record) | DonePin(record=record)):
                return self._json({"ok": True, "pin": public(record), "state": pin_state(record)})
            case PinNotFound():
                return self._json({"ok": False, "pin": None, "state": None})

    def _confirm_reply(self, result: DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound) -> None:
        """Answer POST /api/pins/{id}/confirm for every outcome, with the statuses and bodies of the agent contract."""
        match result:
            case DonePin(record=record) | AlreadyDone(pin=DonePin(record=record)):
                return self._json({"ok": True, "pin": public(record), "state": "done"})
            case PinNotFound():
                return self._json({"ok": False, "pin": None, "state": None})
            case AgentCannotConfirm():
                raise HTTPError(403, CONFIRM_BY_HUMAN)
            case PinStillOpen(pin=OpenPin(record=record)):
                raise HTTPError(409, "open", pin=public(record), detail=CONFIRM_OPEN_DETAIL)

    def _read_raw(self) -> bytes:
        """Reads the request body to completion before any response, on every path (including GET/403/404).

        Responding without reading it first would let the same connection's leftover bytes be interpreted
        as a "local request with no headers" - since tailscale serve reuses the backend connection, a tailnet user could slip through that gap."""
        self._raw = b""
        if self.headers.get("Transfer-Encoding") is not None:
            self.close_connection = True
            raise HTTPError(400, "Transfer-Encoding 은 받지 않습니다. Content-Length 로 보내세요.")
        cls = self.headers.get_all("Content-Length") or []
        if len(set(v.strip() for v in cls)) > 1:
            self.close_connection = True
            raise HTTPError(400, "Content-Length 가 여러 개입니다.")
        cl = cls[0].strip() if cls else ""
        if cl == "":
            return b""
        if not re.fullmatch(r"[0-9]+", cl):          # isdigit() would also accept latin-1 digits like '²'
            self.close_connection = True
            raise HTTPError(400, "Content-Length 가 음이 아닌 정수가 아닙니다.")
        n = int(cl)
        if n > MAX_BODY:
            self.close_connection = True
            raise HTTPError(413, "요청 본문이 너무 큽니다(1 MiB 이하).")
        raw = self.rfile.read(n) if n else b""
        if len(raw) != n:                                 # a truncated request - never acted on (including /api/clear)
            self.close_connection = True
            raise HTTPError(400, "요청 본문이 Content-Length 보다 짧습니다(연결이 끊겼습니다).")
        self._raw = raw
        return raw

    def _check_origin(self) -> None:
        """Blocks cross-origin requests (CSRF) and DNS rebinding.

        - Host: every request must have a loopback name (':' then a port) or *.ts.net.
          DNS rebinding is a browser reaching 127.0.0.1 via evil.example, which shows up in Host.
        - Origin: if present, must be loopback when Host is loopback (port irrelevant - SSH -L), or the same
          origin as that host when Host is *.ts.net (origin_ok).
          A browser always attaches Origin to a cross-origin POST. curl/agents send no Origin, so this has no effect on them."""
        if not C.origin_check:                        # --no-origin-check: an escape hatch for when the observed path differs from expectations
            return
        host = self.headers.get("Host")
        # Checked independent of whether the Tailscale-User-* header is present. That header can also be
        # carried on a same-origin GET from a rebinding page with no preflight, so exempting it via that header would bypass the defense entirely (observed).
        if host is not None and not host_ok(host):
            raise HTTPError(403, "허용되지 않은 Host 입니다: %s" % hdr_text(host)[:100])
        origin = self.headers.get("Origin")
        if origin is not None and not origin_ok(origin, host):
            raise HTTPError(403, "다른 출처의 요청은 받지 않습니다: %s" % hdr_text(origin)[:100])

    def _guard(self) -> dict:
        """Every request: read the body, check Host/Origin, identify (401), admit (403). Leaves the principal on
        self.principal and returns its actor (what pins record)."""
        self._read_raw()
        self._check_origin()
        peer = self.client_address[0] if isinstance(self.client_address, tuple) and self.client_address else ""
        p = identify(self.headers, peer)
        admit(p, self.headers.get("Host"), self.headers)
        self.principal = p
        return p.actor

    def _record(self, actor) -> None:
        """people.json for a person who opened the viewer or wrote something (agents never). The local owner is recorded as owner."""
        record_person(actor, role="owner" if self.principal.via == "local-owner" else None)

    def _me(self, actor) -> dict:
        return dict(actor, role=self.principal.role)

    def _wants_page(self) -> bool:
        """A browser opening the viewer itself (GET / for HTML) - it gets a readable page on a refusal, not JSON."""
        return (self.command == "GET" and urlparse(self.path).path == "/"
                and "text/html" in (self.headers.get("Accept") or ""))

    def _run(self, fn):
        """Runs one request handler and turns its refusal into the response: HTTPError as is, ScopeRejected through
        the SCOPE_REJECTIONS table (one table for every pin-scoping refusal), a dropped connection silently, anything
        else as a 500 with the traceback on stderr. A browser opening / gets an HTML page instead of JSON."""
        try:
            fn()
        except (HTTPError, ScopeRejected) as err:
            e = err if isinstance(err, HTTPError) else scope_http_error(err)
            if self._wants_page():
                lang = page_lang(self.headers, parse_qs(urlparse(self.path).query))
                return self._send(e.code, error_page_html(e, lang).encode("utf-8"), "text/html; charset=utf-8")
            self._json(e.body, e.code)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception as e:                            # noqa: BLE001 — reports as JSON instead of dropping the connection
            traceback.print_exc(file=sys.stderr)
            try:
                self._json({"error": "서버 내부 오류: %s" % e}, 500)
            except OSError:
                self.close_connection = True

    def do_GET(self):
        self._run(self._get)

    def do_POST(self):
        self._run(self._post)

    def _get(self):
        actor = self._guard()
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        # A document-scoped path takes ?doc=<key> (the first document if absent) and is handled for that document (§Multiple documents).
        with using_doc(request_doc(q)):
            return self._get_doc(actor, path, q)

    def _get_revision(self, path: str, D: Doc, q: dict) -> None:
        """Serves the three read routes of a commit's changes for document D (api.md §변경 보기와 비교 PDF). An
        optional &pin= scopes them to one pin (§핀 단위 변경 보기); the pin is parsed before the commit is checked,
        and refusals (HTTPError, ScopeRejected) propagate to _run."""
        commit, pin = (q.get("commit") or [""])[0], clean_pin_param((q.get("pin") or [None])[0])
        if path == "/api/revision-diff":
            return self._json(revision_diff(D, commit, pin))
        if path == "/api/revision-build":
            return self._json(revision_status(D, commit, pin))
        return self._send(200, revision_pdf(D, commit, pin), "application/pdf", cache="private, max-age=600")

    def _get_doc(self, actor, path, q):
        """GET routes that act on the request's document (?doc=, bound by using_doc in _get): the viewer page, people,
        pins and pins.md, meta, snippets, builds and the revision routes. Returns after sending one response; refusals
        propagate to _run as HTTPError (or ScopeRejected from the revision routes)."""
        if path == "/":
            self._record(actor)                   # the tailnet person who opened this viewer (@-tag candidate) - local/agent is never recorded
            return self._send(200, HTML.encode(), "text/html; charset=utf-8")
        if path == "/api/people":                 # @-tag autocomplete candidates (no write). role: people.json role, editor if absent
            roles = people_roles()
            ppl = sorted(known_people(snapshot_pins()).values(), key=lambda x: (x.get("last_seen") is None, x["name"].lower()))
            ppl = [dict(x, role=roles.get(x["login"], DEFAULT_ROLE)) for x in ppl]
            return self._json({"people": ppl, "me": self._me(actor)})
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if path == "/api/version":                # the installed Limn version - no write
            return self._json({"name": APP_NAME, "version": app_version()})
        if path == "/api/meta":
            light = (q.get("light") or ["0"])[0] == "1"
            if not light:
                self._record(actor)
            out = meta(actor, light=light)
            out["me"] = self._me(actor)           # + role (additive)
            out.update(events_since(actor, (q.get("ev") or [None])[0]))   # browser notifications - no write
            return self._json(out)
        if path == "/sw.js":                      # the service worker for browser notifications (app data is never cached)
            return self._send(200, SW_JS.encode(), "text/javascript; charset=utf-8", cache="no-cache")
        if path == "/api/revisions":
            return self._json(revision_history(cur_doc()))
        if path in ("/api/revision-diff", "/api/revision-build", "/api/revision-pdf"):
            return self._get_revision(path, cur_doc(), q)
        if path == "/api/outline-labels":
            return self._json(outline_labels(cur_doc()))
        if path == "/api/build":
            full = (q.get("log") or ["0"])[0] == "1"
            return self._json(diet_log(build_state_snapshot(), full))
        if path == "/pins.md":                    # §P0c-B: entry point for a remote agent - the same sync path as GET /api/pins
            maybe_purge_trash()
            base = remote_base_for(self.headers.get("Host") or "")
            text = pins_md_text(snapshot_pins(), base=base)
            return self._send(200, text.encode("utf-8"), "text/markdown; charset=utf-8")
        if path == "/api/pins":
            maybe_purge_trash()                   # hourly Trash expiry on a long-running server (this path already writes)
            allp = (q.get("all") or ["0"])[0] == "1"
            rows = pins_payload(snapshot_pins(), allp)
            if q.get("doc"):                          # with ?doc=<key>, only that document's pins (overlap/estimation stay computed globally)
                rows = [r for r in rows if r["doc"] == cur_doc().key]
            return self._json(rows)
        if path == "/api/docs":
            return self._json(docs_payload())
        if path == "/api/pins/dropped":
            return self._json({"dropped": dropped_payload()})
        m = re.fullmatch(r"/api/pins/(\d+)", path)
        if m:                                     # one pin (including its thread) - for when an agent needs to read a long thread in full
            pid = int(m.group(1))
            rec = next((r for r in pins_payload(snapshot_pins(), True) if r["id"] == pid), None)
            if rec is None:
                raise HTTPError(404, "핀 #%d 이 없습니다." % pid)
            return self._json({"pin": rec})
        if path == "/api/snippet":
            return self._json(snippet_api(q))
        if path == "/api/overlaps":
            return self._json(overlaps_api(q))
        if path.startswith("/pages/"):
            name = os.path.basename(path)
            if PAGE_FILE_RE.fullmatch(name):
                f = cur_pages() / name
                try:
                    data = f.read_bytes()
                except OSError:
                    data = None
                if data is not None:
                    return self._send(200, data, "image/png")
        if path.startswith("/vendor/pdfjs/"):
            # The viewer's vector renderer (PDF.js). Accepts only a single name component - a subpath, '..', or an encoded character gets a 404.
            f = vendor_file(path[len("/vendor/pdfjs/"):])
            if f is not None:
                try:
                    data = f.read_bytes()
                except OSError:
                    data = None
                if data is not None:
                    # Since the filename carries no version, the viewer appends ?v=<PDFJS_VERSION> to bust the cache.
                    return self._send(200, data, VENDOR_MIME[f.suffix], cache="public, max-age=86400")
            raise HTTPError(404, "없는 vendor 파일입니다: %s" % hdr_text(path)[:100])
        if path == "/pdf":
            # The PDF matching the page images' build (for vector rendering). 404 if the build name is wrong
            # or already deleted - it never falls back to a different build (the viewer falls back to PNG and re-reads /api/meta instead).
            name = (q.get("build") or [""])[0]
            f = build_pdf(name)
            data = None
            if f is not None:
                try:
                    data = f.read_bytes()
                except OSError:
                    data = None
            if data is None:
                raise HTTPError(404, "그 빌드의 PDF 가 없습니다: %s" % hdr_text(name)[:60],
                                pdf_build_gone=bool(name), pages_build=cur_pages().name)
            return self._send(200, data, "application/pdf", cache="private, max-age=600")
        raise HTTPError(404, "없는 경로입니다: %s" % path)

    def _body(self) -> dict:
        raw = self._raw
        if not raw.strip():
            return {}
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            # A cross-origin "simple request" (text/plain form) arrives with no preflight - accepting only JSON closes off that path.
            raise HTTPError(415, "본문은 Content-Type: application/json 으로 보내세요.")
        try:
            d = json.loads(raw)
        except (ValueError, RecursionError):
            raise HTTPError(400, "본문이 올바른 JSON 이 아닙니다.") from None
        if not isinstance(d, dict):
            raise HTTPError(400, "본문은 JSON 객체여야 합니다.")
        return d

    def _post(self):
        actor = self._guard()
        u = urlparse(self.path)
        path = u.path
        check_role(self.principal, path)          # the one place roles are enforced, before any state change
        self._record(actor)
        d = self._body()
        if path in ("/api/pick", "/api/pin", "/api/rebuild", "/api/revision-build"):
            q = parse_qs(u.query)
            D = request_doc(q, d, file_hint=d.get("file") if path == "/api/pin" else None)
            with using_doc(D):
                return self._post_doc(actor, path, u, d)
        return self._post_doc(actor, path, u, d)

    def _post_doc(self, actor, path, u, d):
        """POST routes that act on the request's document: pin changes (close takes the optional v0.3 `changes`,
        parsed against the manuscript folder), pick, new pins, clear, the revision build and rebuilds. d is the parsed
        JSON body; refusals propagate to _run."""
        m = re.fullmatch(r"/api/pins/(\d+)/(close|reopen|drop|restore|purge|edit|claim|unclaim|reply|confirm)", path)
        if m:
            pid, act = int(m.group(1)), m.group(2)
            if act == "reply":
                text, hints, reopen = clean_thread_text(d.get("text")), clean_mention_hints(d.get("mentions")), clean_reopen_flag(d)
                human = not is_agent(actor) and self.principal.role != "agent"
                return self._reply_answer(reply_pin(pid, text, actor, hints, reopen=reopen, human=human))
            if act == "confirm":
                return self._confirm_reply(confirm_pin(pid, actor))
            if act == "drop":
                return self._json({"ok": isinstance(drop_pin(pid, actor), TrashedPin)})
            if act == "restore":
                return self._restore_answer(restore_pin(pid, actor))
            if act == "purge":                    # owner only (check_role)
                if isinstance(purge_pin(pid, actor), NotInTrash):
                    raise HTTPError(404, "휴지통에 핀 #%d 이 없습니다." % pid)
                return self._json({"ok": True, "purged": pid})
            if act == "edit":
                return self._json({"ok": True, "pin": edit_pin(pid, d, actor)})
            if act == "claim":
                ttl, eta = clean_claim_body(d)
                return self._claim_answer(claim_pin(pid, actor, ttl, eta), ttl, eta)
            if act == "unclaim":
                return self._unclaim_answer(unclaim_pin(pid, actor))
            reply = ref = review = reason = changes = None
            if act == "close":
                reply, ref = clean_close_body(d)
                changes = clean_close_changes(d.get("changes"), C.src)
                review = clean_review_flag(d)
                if review is None and self.principal.role == "agent":
                    review = True                 # a person with the agent role closes into review like any agent
            else:                                 # reopen - optional body {"reason"}: the reopen reason (recorded in the thread)
                reason = clean_thread_text(d.get("reason"), "reason", required=False)
            return self._state_reply(set_done(pid, act == "close", actor, reply, ref, review=review, reason=reason,
                                              hints=clean_mention_hints(d.get("mentions")), changes=changes))
        if path == "/api/pick":
            return self._json(pick(d))
        if path == "/api/pin":
            return self._json({"id": add_pin(d, actor)})
        if path == "/api/clear":                  # owner only (check_role), and only with the confirmation phrase
            if d.get("confirm") != CLEAR_CONFIRM:
                raise HTTPError(400, "모든 핀을 지우려면 본문에 {\"confirm\": \"%s\"} 를 보내세요(보관본 pins_<시각>.jsonl.bak 이 남습니다)."
                                % CLEAR_CONFIRM)
            return self._json(dict(clear_pins(actor), ok=True))
        if path == "/api/revision-build":
            if set(d) - {"commit", "doc", "pin"}:
                raise HTTPError(400, "허용되지 않는 비교 PDF 요청 필드입니다.")
            if "pin" in d and not _is_int(d["pin"]):
                raise HTTPError(400, "pin 은 핀 번호(양의 정수)여야 합니다.")
            result = revision_start(cur_doc(), d.get("commit"), clean_pin_param(d.get("pin")))
            return self._json(result, 202 if result["state"] == "running" else 200)
        if path == "/api/rebuild":
            if cur_doc().is_pdf:
                raise HTTPError(400, "보기 전용 문서(%s)는 재빌드하지 않습니다 — PDF 파일이 바뀌면 쪽을 저절로 다시 그립니다."
                                % cur_doc().key)
            full = (parse_qs(u.query).get("log") or ["0"])[0] == "1"
            if (parse_qs(u.query).get("async") or ["0"])[0] == "1":
                r = build_async()
                return self._json(r, 409 if r.get("busy") else 202)
            r = build_all()
            return self._json(diet_log(r, full), 409 if r.get("busy") else 200)
        raise HTTPError(404, "없는 경로입니다: %s" % path)


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
                       root=(p["key"] == DEFAULT_DOC_KEY and p["kind"] == "tex")))
    return out


def init_doc(D: Doc, no_build: bool, wait: bool) -> dict:
    """Prepares one document at startup: legacy-layout migration, restoring build history, and building if needed. Builds in the background if wait=False."""
    with using_doc(D):
        D.dir.mkdir(parents=True, exist_ok=True)
        if D.root:
            migrate_pages()
        seed_builds()
        need = D.is_pdf and (pdf_changed(D) or not page_list())
        if not D.is_pdf:
            need = not no_build or not cur_pdf().exists() or not page_list()
        if not need:
            return {"state": "skip"}
        return build_all() if wait else build_async()


def watch_pdf_docs(stop: threading.Event, every: float = 3.0) -> None:
    """Re-renders pages when a view-only PDF changes (mtime/size). Stands in for a rebuild button."""
    while not stop.wait(every):
        for D in list(DOCS):
            if D.is_pdf:
                try:
                    refresh_pdf_doc(D)
                except Exception:                     # noqa: BLE001 — the watch thread must never die
                    traceback.print_exc(file=sys.stderr)


def configure_access(a) -> None:
    """Validates and applies the access options (--auth, tokens/loopback agent, --bind, proxy, members). Exits with a
    clear message on a refused combination - before any build, so a misconfigured unit fails fast.

    Rules: a non-loopback --bind needs --auth trusted-proxy or --i-know-this-is-insecure. The headerless loopback agent
    exists only under tailscale on a loopback bind; asking for it (--agent-loopback) anywhere else refuses to start."""
    C.auth = a.auth or "tailscale"
    C.bind = a.bind or "127.0.0.1"
    try:
        loop_bind = is_loopback_bind(C.bind)
    except ValueError:
        sys.exit("--bind takes an IP address (or localhost): %s" % C.bind)
    if not loop_bind and C.auth != "trusted-proxy" and not a.i_know_this_is_insecure:
        sys.exit("Refusing to bind %s with --auth %s: a non-loopback address is only safe behind an authenticating "
                 "proxy (--auth trusted-proxy). Keep the default 127.0.0.1 and expose it with tailscale serve, or "
                 "pass --i-know-this-is-insecure if this network is private." % (C.bind, C.auth))
    loopback_agent_possible = C.auth == "tailscale" and loop_bind
    if a.agent_loopback is True and not loopback_agent_possible:
        sys.exit("--agent-loopback (AGENT_LOOPBACK=1) works only with --auth tailscale on a loopback --bind "
                 "(here: --auth %s, --bind %s). Give agents a token instead: limn token create <instance>"
                 % (C.auth, C.bind))
    C.agent_loopback = loopback_agent_possible and a.agent_loopback is not False
    if a.tailnet_agent and not C.agent_loopback:
        sys.exit("--tailnet-agent (TAILNET_AGENT=1) extends the headerless loopback agent to requests through tailscale serve, "
                 "so it needs it on: --auth tailscale, a loopback --bind and no --no-agent-loopback (here: --auth %s, "
                 "--bind %s%s). Give agents a token instead: limn token create <instance>"
                 % (C.auth, C.bind, ", --no-agent-loopback" if a.agent_loopback is False else ""))
    C.tailnet_agent = bool(a.tailnet_agent)
    try:
        C.public_hosts = parse_public_hosts(a.public_host)
        C.trusted_proxies = parse_networks(a.trusted_proxies)
    except ValueError as e:
        sys.exit(str(e))
    for opt, v in (("--proxy-user-header", a.proxy_user_header), ("--proxy-name-header", a.proxy_name_header),
                   ("--proxy-email-header", a.proxy_email_header)):
        if v is not None and not HEADER_NAME_RE.fullmatch(v):
            sys.exit("%s takes an HTTP header name: %r" % (opt, v))
    C.proxy_user_header, C.proxy_name_header, C.proxy_email_header = a.proxy_user_header, a.proxy_name_header, a.proxy_email_header
    C.members_only = bool(a.members_only)
    if a.local_user is not None and not valid_login(a.local_user):
        sys.exit("--local-user takes a login (no spaces, not 'local' or 'agent:...'): %r" % a.local_user)
    C.local_user = a.local_user
    C.insecure = bool(a.i_know_this_is_insecure) and not loop_bind and C.auth != "trusted-proxy"
    C.agent_token_file = Path(a.agent_token_file).expanduser() if a.agent_token_file else None


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


class Server6(Server):
    address_family = socket.AF_INET6


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


def probe_port(bind: str, port: int) -> None:
    """Fails fast (one line, exit 1) when --port is taken - before a build that can take minutes, and instead of the
    Errno 98 traceback the server constructor would print (observed in the v0.2.0 QA)."""
    fam = socket.AF_INET6 if ":" in bind else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # the same option the server sets (allow_reuse_address)
        s.bind((bind, port))
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print(port_in_use_message(bind, port), file=sys.stderr)
            sys.exit(1)
        print("limn serve: cannot listen on %s port %d: %s" % (bind, port, e.strerror or e), file=sys.stderr)
        sys.exit(1)
    finally:
        s.close()


def main() -> None:
    a = build_arg_parser().parse_args()
    configure_access(a)
    if a.port:
        probe_port(C.bind, a.port)

    C.src = Path(a.manuscript).expanduser().resolve()
    if not C.src.is_dir():
        sys.exit("Manuscript directory does not exist: %s" % C.src)
    if a.doc:
        if a.main:
            sys.exit("--doc and --main are not used together - the main file is set via the --doc path.")
        try:
            docs = make_docs(a.doc, C.src)
        except ValueError as e:
            sys.exit(str(e))
        first_tex = next((d for d in docs if not d.is_pdf), docs[0])
        C.main = first_tex.main
    else:
        docs = None
        C.main = (C.src / a.main) if a.main else detect_main(C.src)
        if not C.main.exists():
            sys.exit("Top-level .tex does not exist: %s" % C.main)

    default_state = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    C.state = Path(a.state_dir).expanduser().resolve() if a.state_dir \
        else default_state / "limn" / "serve" / state_slug(C.src)
    C.state.mkdir(parents=True, exist_ok=True)
    C.build = C.state / "build"
    C.dpi = a.dpi
    C.envs = tuple(e.strip() for e in a.float_envs.split(",") if e.strip())
    C.timeout = a.build_timeout
    C.port = a.port or free_port()
    C.allow = frozenset(x.strip() for x in a.allow.split(",") if x.strip())
    C.origin_check = not a.no_origin_check
    C.git_pull = a.git_pull
    C.pdfjs_dir = Path(a.pdfjs_dir).expanduser().resolve() if a.pdfjs_dir else default_pdfjs_dir()
    C.repo = git_remote_url(C.src)
    # The default label (repo name) is truncated if too long - startup must not halt just because of a long
    # repo name (observed: a 62-character repo). Only an explicitly given --label halts on excess length (so a typo is never silently truncated).
    C.label = clean_label(a.label) if a.label else clean_label(truncate_quote(default_label(C.src, C.repo), LABEL_MAX))
    if a.accent:
        if not valid_accent(a.accent):
            sys.exit("--accent must be in #rrggbb form: %s" % a.accent)
        C.accent = a.accent.lower()
    else:
        C.accent = pick_accent(C.label)
    global HTML
    HTML = build_html(C.label, C.accent)

    set_docs(docs)
    init_seq()
    purge_trash()                    # Trash entries older than TRASH_DAYS go at startup, on every drop/restore, and hourly on reads
    if not docs:
        migrate_pages()
        seed_builds()                # adds the current build (made by an earlier instance) to history if missing, and restores the last build result
        if not a.no_build or not cur_pdf().exists() or not page_list():
            r = build_all()
            if r.get("state") == "fail":
                sys.exit("Build failed:\n" + r.get("log", ""))
    else:
        # Multiple documents: each document's build runs in the background, and the server comes up right
        # away (never waits N documents x tens of seconds). A failure never blocks startup - that document's tab opens an error panel instead.
        for D in DOCS:
            r = init_doc(D, a.no_build, wait=False)
            print("doc    %-10s %s %s%s" % (D.key, "view-only" if D.is_pdf else "LaTeX   ", D.rel_path(),
                                           "" if r.get("state") == "skip" else "  (build started)"))
        threading.Thread(target=watch_pdf_docs, args=(threading.Event(),), daemon=True).start()
    if C.git_pull:
        threading.Thread(target=watch_main, args=(threading.Event(),), daemon=True).start()

    with PIN_LOCK:
        render_pins_md(read_pins()[0])
    tighten_state_perms()
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
    try:
        httpd = (Server6 if ":" in C.bind else Server)((C.bind, C.port), Handler)
    except OSError as e:                              # taken during the build (the probe above passed)
        if e.errno == errno.EADDRINUSE:
            print(port_in_use_message(C.bind, C.port), file=sys.stderr)
        else:
            print("limn serve: cannot listen on %s port %d: %s" % (C.bind, C.port, e.strerror or e), file=sys.stderr)
        sys.exit(1)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
