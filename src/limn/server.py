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
import re
import secrets
import selectors
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
from typing import NamedTuple, TypedDict
from urllib.parse import parse_qs, quote, urlparse

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
FLOAT_KINDS = ("figure", "table", "algorithm")
DEFAULT_ENVS = "figure,table,algorithm,equation,align,itemize,enumerate,minipage"
PAGES_DIR_RE = re.compile(r"pages(-\d{14}(-\d+)?)?")
PAGE_FILE_RE = re.compile(r"page-\d+\.png")
ENV_TOK_RE = re.compile(r"\\(begin|end)\{([^{}]+)\}")

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
# Directories excluded from the build copy (rsync). The manuscript fingerprint and src_mtime use the same
# list - a latexdiff artifact changing must not turn on "manuscript modified" / location re-estimation
# when it isn't part of the build (observed: 17 PDFs under diff/).
BUILD_EXCLUDE_DIRS = ("diff", "diff_temporary")
BUILDS_KEEP = 200                  # number of successful builds kept in builds.json (roughly 200 bytes each)

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


C = Cfg()


# ---------------------------------------------------------------- Documents (§Multiple documents, docs/handbook/domain.md §여러 문서)
#
# A single paper repo has several documents - the body, the review response, the cover letter. One viewer
# (one address) switches between them. The pin store (pins.jsonl/pins.seq) is singular - pin numbers must
# be unique across documents so "handle #12" is unambiguous. Build/page images/PDF copy/build history live
# under a per-document folder (Doc.dir). A single request handles a single document, and it's hung off a
# thread-local value (using_doc) - so build/page functions can look at "the current document" without
# taking a parameter, keeping the existing code paths as-is.

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


def atomic_write(path: Path, text: str, mode: int = None) -> None:
    """Write to a temp file in the same directory, then os.replace - readers only ever see the old file or the new one.
    With mode (e.g. 0o600 for tokens.json) the temp file is created with that mode, so the content is never readable by others, even briefly."""
    tmp = path.with_name(".%s.tmp%d.%d" % (path.name, os.getpid(), threading.get_ident()))
    if mode is None:
        fh = open(tmp, "w", encoding="utf-8")
    else:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        os.fchmod(fd, mode)                               # the umask may have narrowed or (never) widened it
        fh = open(fd, "w", encoding="utf-8")
    with fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


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
                           capture_output=True, text=True, timeout=5)
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

def cur_pages() -> Path:
    """The page-image directory to show right now. Pointed to by the pages.cur pointer.

    If the pointer is absent, the legacy layout (<state>/pages/) is used as-is - migrated without a rebuild.
    Per-document (cur_doc().dir - the state folder root for a single document)."""
    base = cur_doc().dir
    try:
        name = (base / "pages.cur").read_text(encoding="utf-8").strip()
    except OSError:
        name = ""
    if name and PAGES_DIR_RE.fullmatch(name) and (base / name).is_dir():
        return base / name
    return base / "pages"


def valid_build_name(v) -> bool:
    return isinstance(v, str) and PAGES_DIR_RE.fullmatch(v) is not None


def pages_dir_for(name) -> Path:
    """The page directory of the build the browser is currently looking at. Falls back to the current one if the name is wrong or already deleted.

    A drag made in the gap between a rebuild finishing and the viewer switching to the new view (a polling
    gap) uses coordinates from the old layout - mapping those onto the new PDF would point at a different
    line. Because the previous build directory is kept one generation back (_build keeps current + previous),
    it can usually still be traced back using the same PDF the screen was showing."""
    base = cur_doc().dir
    if valid_build_name(name) and (base / name).is_dir():
        return base / name
    return cur_pages()


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
    """The PDF GET /pdf?build=<name> serves - only the copy that matches that build's page images (pages-<build>/<main>.pdf).

    Unlike cur_pdf, this never falls back to build/. The one in build/ can be overwritten in place by a
    rebuild and drift out of sync with the on-screen page images - measuring coordinates against it would
    point at a different spot than the PNG. Returns None if there is none."""
    D = cur_doc()
    if name in (None, ""):
        pdir = cur_pages()
    elif valid_build_name(name) and (D.dir / name).is_dir():
        pdir = D.dir / name
    else:
        return None
    f = pdir / D.pdf_name
    return f if f.is_file() else None


def cur_pdf(pdir: Path = None) -> Path:
    """The PDF matched to the page images. Uses the copy in the version directory if present, otherwise (legacy layout) the one in build/.

    Why matching matters: even if a build fails, the screen still shows the old PDF - if pick read the
    newly broken PDF instead, it would point at a different spot than what's visible."""
    D = cur_doc()
    f = (pdir or cur_pages()) / D.pdf_name
    if f.exists():
        return f
    if D.is_pdf:                                          # view-only: the original PDF if pages haven't been rendered yet
        return D.main
    return D.out / D.pdf_name


def build_ref_mtime(name: str):
    """The manuscript src_mtime at the time that build started (looked up via build history -> built_src_mtime.txt -> PDF timestamp, in that order)."""
    ent = load_builds()["by"].get(name)
    if ent and _is_num(ent.get("src_mtime")):
        return float(ent["src_mtime"])
    if name == cur_pages().name:
        v = read_built_src_mtime()
        if v is not None:
            return v
    try:
        return cur_pdf(pages_dir_for(name)).stat().st_mtime
    except OSError:
        return None


def source_newer(name: str = None) -> float:
    """If the manuscript is newer than that build (default: the build currently on screen), returns the difference in seconds; otherwise 0.0.

    If the screen shows a stale PDF, the dragged spot and the source text drift apart. Yet the text path
    can still find a similar-looking paragraph and just barely clear the warning threshold (0.3) - in one
    observed case, selecting the Nomenclature returned the introduction's contribution list at 0.32 with no
    warning. A score alone can't filter that out, so the fact itself is surfaced instead. The comparison
    baseline is "src_mtime at the moment the build started" - this also catches files edited mid-build, and
    src_mtime already excludes diff/, which isn't part of the build (the old implementation looked at every
    *.tex plus the PDF timestamp)."""
    ref = build_ref_mtime(name or cur_pages().name)
    if ref is None:
        return 0.0
    return max(0.0, src_mtime() - ref)


def migrate_pages() -> None:
    """Turns the legacy layout (<state>/pages/ + build/<main>.pdf) into a version directory.

    The PDF/synctex copies must sit in pages/ so pick reads the same PDF as the on-screen pages - the one
    in build/ gets overwritten in place by a rebuild (and drifts if a build is in progress or fails partway)."""
    D = cur_doc()
    if D.is_pdf:
        return
    legacy = D.dir / "pages"
    if not legacy.is_dir():
        return
    ptr = D.dir / "pages.cur"
    if not ptr.exists():
        atomic_write(ptr, "pages")
    if cur_pages() != legacy:
        return
    for suf in (".pdf", ".synctex.gz"):
        src, dst = D.out / (D.main.stem + suf), legacy / (D.main.stem + suf)
        if src.is_file() and not dst.exists():
            tmp = dst.with_name(dst.name + ".tmp")
            try:
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
            except OSError as e:
                print("warning: failed to copy %s into the page directory: %s" % (src.name, e), file=sys.stderr)


# ---------------------------------------------------------------- Build

def latex_errors(text: str) -> list:
    """Pulls out up to 5 '! ' lines and the first following 'l.<n>' line each (no file guessing)."""
    out = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if not ln.startswith("! "):
            continue
        line_no = None
        for nxt in lines[i + 1:i + 40]:
            m = re.match(r"l\.(\d+)", nxt)
            if m:
                line_no = int(m.group(1))
                break
            if nxt.startswith("! "):
                break
        out.append({"line": line_no, "msg": ln[2:].strip()[:200]})
        if len(out) >= 5:
            break
    return out


def run_logged(cmd: list, cwd: Path, timeout: int):
    """Runs the whole process group, and kills the whole group on timeout (including pdflatex spawned by latexmk)."""
    try:
        p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             encoding="utf-8", errors="replace", start_new_session=True)
    except FileNotFoundError:
        return None, "%s 를 찾지 못했습니다." % cmd[0], False
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or "", False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        out, _ = p.communicate()
        return None, (out or "") + "\n[시간 초과 %d초 — 빌드를 중단했습니다]" % timeout, True


def build_state_update(**kw) -> None:
    D = cur_doc()
    with D.bstate_lock:
        D.bstate.update(kw)


def build_state_snapshot() -> dict:
    """The shape GET /api/build returns. If a build is running, elapsed_s is re-measured against the current time."""
    D = cur_doc()
    with D.bstate_lock:
        d = dict(D.bstate)
    t0 = d.pop("start_ts", None)
    d["elapsed_s"] = round(time.time() - t0, 1) if d.get("state") == "running" and t0 else d.get("elapsed_s") or 0.0
    if d.get("built_at") is None:
        try:
            d["built_at"] = (D.dir / "built_at.txt").read_text().strip()
        except OSError:
            d["built_at"] = None
    return d


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


def build_all() -> dict:
    """Rebuild the PDF (synchronous). If a build is already running, returns busy without waiting.
    One lock per document - different documents build concurrently (each has its own build folder)."""
    lock = cur_doc().lock
    if not lock.acquire(blocking=False):
        return {"ok": False, "busy": True}
    try:
        return _build_tracked()
    finally:
        lock.release()


def build_async() -> dict:
    """POST /api/rebuild?async=1: if the lock is acquired, runs the same build function on a daemon thread and returns immediately."""
    D = cur_doc()
    if not D.lock.acquire(blocking=False):
        return {"state": "running", "busy": True}
    build_state_update(state="running", phase="copy", started_at=now_str(), start_ts=time.time())

    def worker():
        with using_doc(D):                             # the build thread sees the same document
            try:
                _build_tracked()
            except Exception as e:                     # noqa: BLE001 — must not stay stuck at running even if _build_tracked itself dies
                finish_build({"ok": False, "state": "fail", "errors": [],
                              "log": "빌드 스레드에서 예상 밖 예외가 났습니다: %r" % e, "elapsed_s": 0.0}, None)
            finally:
                D.lock.release()
    threading.Thread(target=worker, daemon=True).start()
    return {"state": "running"}


def _build_tracked() -> dict:
    """Wraps _build() to fill in BUILD_STATE (progress chip / error panel) and the build history. Sync and async both use this path.

    Even if _build() raises an unexpected exception (e.g. an OSError near an rsync/latexmk call), BUILD_STATE
    is never left stuck at running - if this function died inside an async worker, the next poll would show
    "building" forever. built_src_mtime is fixed to the mtime of "the manuscript this build actually
    compiled" - with --git-pull that's after the pull (fast-forward can bump the .tex mtime); otherwise
    _build() measures it right before the copy and returns it as res["src_mtime"] (force=True, skipping the
    2-second cache). Only when _build() can't return that value (a PDF document, or a failure before
    res["src_mtime"] gets filled in) does the build start time (src_mtime_at_start) stand in instead. It's
    only committed to file on ok|ok_errors - on failure the screen still shows the old PDF, so the
    "manuscript modified" badge must not turn off."""
    D = cur_doc()
    with D.bstate_lock:
        last_s = D.bstate.get("last_s")
    build_state_update(state="running", phase="copy", started_at=now_str(), start_ts=time.time(),
                        last_s=last_s, errors=[], log_tail="")
    src_mtime_at_start = src_mtime(force=True)
    try:
        res = _render_pdf_doc() if D.is_pdf else _build()
    except Exception as e:                            # noqa: BLE001 — must not stay stuck at running even if the build dies
        res = {"ok": False, "state": "fail", "errors": [],
               "log": "빌드 중 예상 밖 예외가 났습니다: %r" % e, "elapsed_s": 0.0}
    src_mtime_for_build = res.get("src_mtime")
    if not _is_num(src_mtime_for_build):
        src_mtime_for_build = src_mtime_at_start          # fallback for cases res couldn't fill in - a PDF document, or a failure before the copy
    if res.get("state") in ("ok", "ok_errors"):
        write_built_src_mtime(src_mtime_for_build)
    finish_build(res, src_mtime_for_build)
    return res


def finish_build(res: dict, src_mtime_for_build) -> None:
    """A build finished (success or failure either way) - record it in history, bump build_seq, then update BUILD_STATE.

    src_mtime_for_build is the mtime of "the manuscript this build actually compiled" (after the pull with
    --git-pull, otherwise measured right before the copy - see the caller _build_tracked()). Because
    build_ref_mtime() looks at this history entry before built_src_mtime.txt, the value recorded here is the
    effective baseline for the "manuscript modified" badge.

    build_seq is "number of finished builds". The viewer notices a build it never saw by checking whether
    this value changed - even a build that starts and finishes inside a single 5-second polling gap (never
    observed as running) still bumps seq. seq and the final state are changed together (so there's never a
    visible moment where the state is final but seq is still the old value)."""
    state = res.get("state", "fail")
    last = {"state": state, "errors": list(res.get("errors") or [])[:5],
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "elapsed_s": res.get("elapsed_s", 0.0), "log_tail": str(res.get("log") or "")[-4000:],
            "head": res.get("head"), "pull": res.get("pull")}
    D = cur_doc()
    with D.bstate_lock:
        last["started_at"] = D.bstate.get("started_at")
    ent = None
    if state in ("ok", "ok_errors") and res.get("build"):
        ent = {"build": res["build"], "src_mtime": src_mtime_for_build, "src_hash": res.get("src_hash"),
               "finished_at": last["finished_at"]}
    seq = record_build(last, ent)
    build_state_update(state=state, phase=None, start_ts=None, seq=seq, finished_at=last["finished_at"],
                        elapsed_s=last["elapsed_s"], last_s=last["elapsed_s"],
                        pages=res.get("pages", 0), errors=last["errors"], head=last["head"], pull=last["pull"],
                        log_tail=res.get("log", ""), built_at=_read_built_at(),
                        last={"state": state, "errors": last["errors"], "finished_at": last["finished_at"],
                              "seq": seq, "head": last["head"], "pull": last["pull"]})


# ---------------------------------------------------------------- Build history (builds.json) and manuscript fingerprint
#
# For the server to judge location estimation (.est), it needs to know whether "the build on screen when
# the pin was placed" and "the current build" came from the same manuscript. So every build records its
# page-directory name (build id) and a fingerprint of the manuscript it compiled (content hash + src_mtime
# at start). Wall-clock comparison (the old approach) was wrong across the board with browser time zones,
# note edits, and pins placed on a stale PDF (confirmed by independent verification).

def _empty_builds() -> dict:
    return {"seq": 0, "builds": [], "last": None}


def _valid_build_entry(b) -> bool:
    return (isinstance(b, dict) and valid_build_name(b.get("build"))
            and (b.get("src_mtime") is None or _is_num(b.get("src_mtime")))
            and (b.get("src_hash") is None or isinstance(b.get("src_hash"), str)))


def load_builds() -> dict:
    """{seq, builds, last, by}. Empty history if the file is missing or broken - the server still runs without history (estimation just stays conservative)."""
    try:
        d = json.loads((cur_doc().dir / "builds.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        d = None
    out = _empty_builds()
    if isinstance(d, dict):
        if _is_int(d.get("seq")) and d["seq"] >= 0:
            out["seq"] = d["seq"]
        if isinstance(d.get("builds"), list):
            out["builds"] = [b for b in d["builds"] if _valid_build_entry(b)]
        if isinstance(d.get("last"), dict):
            out["last"] = d["last"]
    out["by"] = {b["build"]: b for b in out["builds"]}
    return out


def _write_builds(h: dict) -> None:
    body = {"seq": h["seq"], "last": h["last"], "builds": h["builds"][-BUILDS_KEEP:]}
    try:
        atomic_write(cur_doc().dir / "builds.json", json.dumps(body, ensure_ascii=False, indent=1) + "\n")
    except OSError as e:
        print("warning: failed to write build history: %s" % e, file=sys.stderr)


def record_build(last: dict, ent) -> int:
    """Add one finished build to the history and return the new seq. seq still advances (in memory) even if the write fails."""
    D = cur_doc()
    with D.builds_lock:
        h = load_builds()
        with D.bstate_lock:
            seq = max(h["seq"], int(D.bstate.get("seq") or 0)) + 1
        h["seq"] = seq
        h["last"] = dict(last, seq=seq, build=ent["build"] if ent else None)
        if ent:
            ent = dict(ent, seq=seq)
            h["builds"] = [b for b in h["builds"] if b["build"] != ent["build"]] + [ent]
        _write_builds(h)
        return seq


def seed_builds() -> None:
    """Add the current build (made by an earlier instance) to history once if it isn't already there, and restore the last build result into BUILD_STATE.

    Which manuscript that build was made from is unknown. But if the current manuscript's src_mtime is at or
    before that build's reference time (built_src_mtime.txt, or the PDF timestamp if absent), no file has
    been edited since, so the current manuscript's fingerprint is adopted as that build's fingerprint - this
    keeps the first pin placed after startup from being misjudged as estimated on a "rebuild that didn't
    change the manuscript". If it can't be determined, the fingerprint is left empty (that build's pins fall
    back to conservative estimation after the next build)."""
    D = cur_doc()
    with D.builds_lock:
        h = load_builds()
        cur = cur_pages()
        if cur.is_dir() and cur.name not in h["by"] and any(cur.glob("page-*.png")):
            bsm = read_built_src_mtime()
            ref = bsm
            if ref is None:
                try:
                    ref = cur_pdf(cur).stat().st_mtime
                except OSError:
                    ref = None
            ent = {"build": cur.name, "seq": h["seq"], "src_mtime": bsm, "src_hash": None,
                   "finished_at": _read_built_at(), "seeded": True}
            now_m = src_mtime(force=True)
            if ref is not None and now_m <= ref + 1e-6:
                ent["src_hash"] = doc_fingerprint(D)
                if ent["src_mtime"] is None:
                    ent["src_mtime"] = now_m
            h["builds"].append(ent)
            _write_builds(h)
    last = h.get("last") or {}
    kw = {"seq": h["seq"]}
    if last.get("state") in ("ok", "ok_errors", "fail"):
        errs = [e for e in (last.get("errors") or []) if isinstance(e, dict)][:5]
        kw.update(state=last["state"], errors=errs, log_tail=str(last.get("log_tail") or ""),
                  started_at=last.get("started_at"), finished_at=last.get("finished_at"),
                  last_s=last.get("elapsed_s"), elapsed_s=last.get("elapsed_s"),
                  head=last.get("head"), pull=last.get("pull"),
                  last={"state": last["state"], "errors": errs, "finished_at": last.get("finished_at"),
                        "seq": h["seq"], "head": last.get("head"), "pull": last.get("pull")})
    build_state_update(**kw)


def _read_built_at():
    try:
        return (cur_doc().dir / "built_at.txt").read_text().strip()
    except OSError:
        return None


def _read_head():
    try:
        return (cur_doc().dir / "head.txt").read_text().strip()
    except OSError:
        return None


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
        r = subprocess.run(["git"] + list(args), cwd=str(cwd), timeout=timeout, capture_output=True, text=True)
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
    if commit not in {row["id"] for row in revision_history(D)["revisions"]}:
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
        raise HTTPError(503, "변경사항을 읽지 못했습니다.")
    out = {"id": commit, "diff": b"".join(chunks)[:REVISION_DIFF_MAX].decode("utf-8", errors="replace"),
           "truncated": too_large}
    if pin is not None:
        base = revision_first_parent(repo, commit)
        sc = (revision_pin_scope(D, repo, paths, base, commit, pin) if base          # may raise ScopeRejected
              else PinScope(scope_pin_record(D, pin)["id"], "commit", "none", 0, 0))
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
SCOPE_CACHE_KEEP = 32                 # entries hold counts and the two patches only (at most 2 x 256 KiB each)
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
    old/new are the file's lines as bytes, each keeping its newline (git_lines). A pure rename, a mode change and a
    binary file have no blocks - they are shown as a header and never attributed to a pin."""
    old_path: str | None
    new_path: str | None
    old: tuple[bytes, ...]
    new: tuple[bytes, ...]
    blocks: tuple[Block, ...]
    binary: bool


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
    scope: str
    pin: int
    source: str
    hunks: int
    other: int


class _ScopeCounts(TypedDict):
    pin: int
    mode: str
    source: str
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
    mode: str
    source: str
    hunks: int
    other: int
    blocks: tuple[ScopeItem, ...] = ()   # scope_key() of the pin's blocks, in mode "pin" only
    diff: bytes = b""                    # the two patches (UTF-8), in mode "pin" only
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


def pin_range_candidates(f: FileChange, pin: dict) -> list[Placement]:
    """Where the pin's range may sit in this commit, best first; the pin must have int lo/hi.

    A closed pin keeps the lines of its last sync, and nothing records which version that was: the commit's new side
    when the anchor survived the fix, the old side when the fix rewrote the anchored text (sync lost it and kept the
    pre-edit lines) or when the pin was closed before the server's checkout reached the commit. So the anchor is
    looked up on both sides near the recorded range, with the same rule as sync_all(), and the side where it sits
    closer to the recorded line comes first (the recorded number is in that side's coordinates; ties prefer the new
    side). A generic anchor such as \\begin{equation} is found on both sides - the distance is what tells them apart.
    The raw range comes last: old side if the pin went stale, else new."""
    lo, hi = pin["lo"], pin["hi"]
    anc = pin.get("anchor") if isinstance(pin.get("anchor"), dict) else {}
    head_text, found = anc.get("head"), []
    sides = {"new": _pin_lines(f.new), "old": _pin_lines(f.old)}
    if isinstance(head_text, str) and head_text:
        ho, to = _off(anc.get("head_off")), _off(anc.get("tail_off"))
        for rank, side in enumerate(("new", "old")):
            texts, to_git = sides[side]
            if not texts:
                continue
            nl = [norm(t) for t in texts]
            head = find_line(nl, head_text, lo + ho)
            if head is None:
                continue
            a = max(1, head - ho)
            tail = find_line(nl, anc.get("tail", ""), hi - to + (a - lo))
            b = max(a, min(len(texts), tail + to if tail is not None and tail >= head else a + (hi - lo)))
            found.append((abs(a - lo), rank, Placement(side, to_git(a), to_git(b))))
    raw = "old" if pin.get("stale") else "new"
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


def attribute_blocks(files: Sequence[FileChange], pin: dict, pin_rel: str | None,
                     changes: Sequence[RepoRange]) -> tuple[str, set[BlockId]]:
    """(source, block ids) - the blocks of this commit that belong to the pin.

    changes are the pin's recorded new-side ranges. If none of them hits a block (another commit's numbers, a wrong
    path) the pin's own range decides (pin_range_candidates; pin_rel is its repo-relative file, None for a region pin),
    and if that hits nothing either the answer is ("none", set()) and the caller shows the whole commit as before."""
    chosen = set()
    for fi, f in enumerate(files):
        if f.new_path is None:
            continue
        for rel, lo, hi in changes:
            if rel == f.new_path:
                chosen |= {(fi, bi) for bi, b in enumerate(f.blocks) if _hits(touch_range(b.new_lo, b.new_n), lo, hi)}
    if chosen:
        return "changes", chosen
    if pin_rel and _is_int(pin.get("lo")) and _is_int(pin.get("hi")):
        for fi, f in enumerate(files):
            if pin_rel not in (f.old_path, f.new_path):
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
        out.append("new file mode 100644")
    elif f.new_path is None:
        out.append("deleted file mode 100644")
    elif a != b:
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


def pin_scope(pid: int, files: Sequence[FileChange] | None, pin: dict, pin_rel: str | None,
              changes: Sequence[RepoRange]) -> PinScope:
    """The decision for one pin and one commit's files (None = the commit could not be read for scoping, which
    shows the whole commit). Mode "pin" only when the pin owns some but not all places of the commit."""
    if files is None:
        return PinScope(pid, "commit", "none", 0, 0)
    source, chosen = attribute_blocks(files, pin, pin_rel, changes)
    mine_text, mine = scoped_patch(files, chosen, True)
    other_text, other = scoped_patch(files, chosen, False)
    if not (chosen and other):
        return PinScope(pid, "commit", source, mine, other)
    return PinScope(pid, "pin", source, mine, other, scope_key(files, chosen),
                    mine_text.encode("utf-8", "replace"), other_text.encode("utf-8", "replace"))


def recorded_changes(pin: dict) -> tuple[ChangeRecord, ...]:
    """The pin's stored `changes` that belong to its current close: none unless changes_at equals done_at. A 0.2.2
    server (after a rollback) neither clears nor writes them, so an older close's set may still be on the record;
    items of the wrong shape are skipped."""
    if pin.get("changes_at") != pin.get("done_at"):
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


def _valid_changes(v: object) -> bool:
    """Whether v has the stored shape of `changes` - a list of {file: str, lo: int, hi: int}. valid_rec() treats a
    record failing this as a broken line; recorded_changes() skips such items."""
    return isinstance(v, list) and all(isinstance(c, dict) and isinstance(c.get("file"), str) and _is_int(c.get("lo"))
                                       and _is_int(c.get("hi")) for c in v)


# -------- the git edge of pin scoping (reads git and pins.jsonl; decisions above)

SCOPE_CACHE_LOCK = threading.Lock()
SCOPE_CACHE = {}                      # (repo, base, head, pin facts) -> PinScope; bounded, commits are immutable


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
        tokens, entries, i = raw.split(b"\0"), [], 0
        while i < len(tokens):
            meta = tokens[i]
            if not meta.startswith(b":"):
                i += 1
                continue
            _, _, old_oid, new_oid, status = meta[1:].split()
            n = 2 if status[:1] in (b"R", b"C") else 1
            names = [t.decode("utf-8") for t in tokens[i + 1:i + 1 + n]]   # a non-UTF-8 name: UnicodeError -> whole commit
            i += 1 + n
            kind = status[:1].decode()
            old_path = None if kind == "A" else names[0]
            new_path = None if kind == "D" else names[-1]
            entries.append((old_path, new_path, old_oid.decode(), new_oid.decode()))
        if len(entries) > SCOPE_FILES_MAX:
            return None
        budget, zero, files = [SCOPE_BYTES_MAX], "0" * 40, []
        deadline = time.monotonic() + SCOPE_SECONDS_MAX
        for old_path, new_path, old_oid, new_oid in entries:
            if time.monotonic() > deadline:
                return None
            old = _blob(repo, old_oid, budget) if old_path is not None and old_oid != zero else b""
            new = _blob(repo, new_oid, budget) if new_path is not None and new_oid != zero else b""
            if b"\0" in old[:8000] or b"\0" in new[:8000]:
                files.append(FileChange(old_path, new_path, (), (), (), True))
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
            files.append(FileChange(old_path, new_path, git_lines(old), git_lines(new), tuple(blocks), False))
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


def scope_pin_record(D: Doc, pid: int) -> dict:
    """The pin a scoped request names, read from pins.jsonl without the sync write. Raises
    ScopeRejected("pin_not_in_doc") when there is no such pin or it belongs to another document than D."""
    rows, _ = read_pins()
    r = find_pin(rows, pid)
    if r is None or pin_doc_key(r) != D.key:
        raise ScopeRejected("pin_not_in_doc")
    return r


def revision_pin_scope(D: Doc, repo: Path, paths: Sequence[str], base: str, head: str, pid: int) -> PinScope:
    """How pin pid of document D sees commit head (compared with its first parent base): reads the pin and, unless
    the same pin facts were seen for this commit before (SCOPE_CACHE), the commit's files; then decides with
    pin_scope(). Raises ScopeRejected("pin_not_in_doc"); an unreadable commit is mode "commit", not an error."""
    r = scope_pin_record(D, pid)
    changes = [RepoRange(_repo_rel(repo, c["file"]), c["lo"], c["hi"]) for c in recorded_changes(r)]
    facts = json.dumps([r.get(k) for k in ("file", "lo", "hi", "stale", "anchor")] + [changes], sort_keys=True, default=str)
    key = (str(repo), base, head, pid, facts)
    with SCOPE_CACHE_LOCK:
        hit = SCOPE_CACHE.get(key)
    if hit is not None:
        return hit
    files = revision_changes(repo, base, head, paths)
    pin_rel = _repo_rel(repo, r["file"]) if not is_region_pin(r) else None
    out = pin_scope(pid, files, r, pin_rel, [c for c in changes if c.path])
    with SCOPE_CACHE_LOCK:
        if len(SCOPE_CACHE) >= SCOPE_CACHE_KEEP:
            SCOPE_CACHE.pop(next(iter(SCOPE_CACHE)))
        SCOPE_CACHE[key] = out
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
    commit or none of it, in which case the spec (and its cache entry) is the whole-commit one. Raises HTTPError for a
    bad or foreign commit (as before 0.3) and ScopeRejected("pin_not_in_doc") for a pin D does not have."""
    if not isinstance(commit, str) or not REVISION_ID_RE.fullmatch(commit):
        raise HTTPError(400, "올바른 커밋 ID가 아닙니다.")
    scope = revision_scope(D)
    if scope is None or commit not in {r["id"] for r in revision_history(D)["revisions"]}:
        raise HTTPError(404, "현재 문서의 최근 커밋이 아닙니다.")
    repo, paths = scope[0], tuple(scope[1])
    try:
        source = D.src.resolve().relative_to(repo).as_posix()
        main = D.main.resolve().relative_to(D.src.resolve())
    except ValueError:
        raise HTTPError(400, "Git 저장소 안의 문서 빌드 루트가 필요합니다.")
    rc, out, _ = _git(["rev-list", "--parents", "-n", "1", commit], repo)
    parents = out.strip().split()
    if rc != 0 or len(parents) < 2 or not REVISION_ID_RE.fullmatch(parents[1]):
        raise HTTPError(422, "첫 커밋은 이전 원고가 없어 비교 PDF를 만들 수 없습니다.", reason="no_parent")
    base = parents[1]
    identity = [REVISION_CACHE_VERSION, str(repo), source, main.as_posix(), base, commit, "pdflatex"]
    blocks, meta = (), None
    if pin is not None:
        sc = revision_pin_scope(D, repo, paths, base, commit, pin)
        meta = scope_meta(sc)
        if sc.mode == "pin":
            blocks = sc.blocks
            identity += ["pin", pin, [list(b) for b in blocks]]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return RevisionSpec(repo, source, main, base, commit, key, paths, blocks, pin, meta)


def revision_exec(cmd: list, cwd: Path, timeout: float, limit: int = 8 * 1024 * 1024):
    """Bound both pipes and lifetime; kill the entire process group on every early exit."""
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        raise HTTPError(503, "비교 PDF 실행 도구를 시작하지 못했습니다.", reason="tool_unavailable")
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
                raise HTTPError(503, "비교 PDF 실행 시간이 초과됐습니다.", reason="timeout")
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
            raise HTTPError(422, "사본에 허용되지 않는 경로·심링크·하위 저장소가 있습니다.", reason="unsafe_snapshot")
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
    dest); the build worker reports it in the status like any other build failure."""
    for w in plan_scope_writes(revision_changes(spec.repo, spec.base, spec.head, spec.paths), spec.scope, spec.source):
        target = dest / w.rel
        if target.is_symlink() or not target.parent.resolve().is_relative_to(dest.resolve()):
            raise ScopeRejected("unsafe_path")
        if w.data is None:
            if target.is_file():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(w.data)


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
        head_label = spec.head[:8] + ("+pin%d" % spec.pin if spec.scope else "")
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
    entries = [p for p in root.iterdir() if re.fullmatch(r"[0-9a-f]{64}", p.name) and p.is_dir() and not p.is_symlink()]
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    kept = 1
    for path in entries:
        if path.name == keep_key or str(path) in REVISION_JOBS:
            continue
        if kept >= REVISION_CACHE_KEEP or time.time() - path.stat().st_mtime > REVISION_CACHE_TTL:
            shutil.rmtree(path)
        else:
            kept += 1


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
                raise HTTPError(409, "이 문서의 비교 PDF를 만드는 중입니다.", reason="busy")
            _revision_prune(root, spec.key)
            if jobdir.is_symlink():
                raise HTTPError(503, "비교 캐시 경로가 올바르지 않습니다.", reason="unsafe_cache")
            if jobdir.exists():
                shutil.rmtree(jobdir)
            jobdir.mkdir()
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
            raise HTTPError(404, "해당 비교 PDF가 없습니다.")


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
    """Builds with -synctex=1 from a copy, leaving the original untouched, then renders pages into a new directory and only swaps the pointer.

    Three outcomes: fail = no new PDF or timeout (screen keeps the old PDF), ok_errors = a new PDF came
    out but there are LaTeX errors ('! ' lines), ok = no errors."""
    t0 = time.time()
    D = cur_doc()
    D.build.mkdir(parents=True, exist_ok=True)
    res = {"ok": False, "state": "fail", "errors": [], "log": "", "elapsed_s": 0.0}

    if C.git_pull:                                        # fast-forward to remote main before the copy step (§P0c-E)
        build_state_update(phase="pull")
        res["pull"] = repo_pull()
        build_state_update(phase="copy")
    # mtime of the manuscript this build will actually compile - after the pull if there was one (a
    # fast-forward can bump the .tex mtime), otherwise measured now (right before the copy). _build_tracked()
    # commits this value to built_src_mtime/history - using the build start time (before the pull) instead
    # caused the new mtime from the pull to be misread as "not built yet", leaving the "manuscript modified"
    # badge on even right after a success.
    res["src_mtime"] = src_mtime(force=True)

    rs = shutil.which("rsync")
    try:
        if rs:
            excl = []
            for d in BUILD_EXCLUDE_DIRS:
                excl += ["--exclude", d + "/"]
            subprocess.run([rs, "-a", "--delete"] + excl + ["--exclude", "*.synctex.gz",
                            str(D.src) + "/", str(D.build) + "/"], capture_output=True, timeout=300)
        else:                                            # must still work without rsync
            shutil.rmtree(D.build, ignore_errors=True)
            shutil.copytree(D.src, D.build, ignore=shutil.ignore_patterns(*BUILD_EXCLUDE_DIRS, "*.synctex.gz"))
    except (subprocess.TimeoutExpired, OSError) as e:
        res["log"] = "원고 사본을 만들지 못했습니다: %s" % e
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res
    # The fingerprint is taken from the copy - these are exactly the files this build actually compiles (the original can still change meanwhile).
    try:
        res["src_hash"] = source_fingerprint(D.build)
    except OSError:
        res["src_hash"] = None

    build_state_update(phase="latex")
    # A single document runs in the build root as before; a --doc document runs in the folder holding its main .tex (Doc.out).
    _rc, out, timed_out = run_logged(
        ["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode", D.main.name], D.out, C.timeout)
    try:
        atomic_write(D.dir / "build.log", out)
    except OSError:
        pass
    tail = "\n".join(out.splitlines()[-40:])[-4000:]
    res["log"] = tail

    pdf = D.out / (D.main.stem + ".pdf")
    syn = D.out / (D.main.stem + ".synctex.gz")
    texlog = D.out / (D.main.stem + ".log")
    try:
        logtxt = texlog.read_text(encoding="utf-8", errors="replace") \
            if texlog.exists() and texlog.stat().st_mtime >= t0 - 1 else out
    except OSError:
        logtxt = out
    res["errors"] = latex_errors(logtxt)

    fresh = (not timed_out) and pdf.exists() and pdf.stat().st_mtime >= t0 - 1
    if not fresh:
        res["log"] = ("시간 초과로 멈췄습니다.\n" if timed_out else "새 PDF 가 나오지 않았습니다.\n") + tail
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res
    if not syn.exists() or syn.stat().st_mtime < t0 - 1:
        res["log"] = "synctex.gz 가 없습니다 — latexmk 가 -synctex=1 을 받았는지 확인하세요.\n" + tail
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res

    extra = [syn]
    aux = D.out / (D.main.stem + ".aux")
    if aux.is_file() and aux.stat().st_mtime >= t0 - 1:
        extra.append(aux)
    newdir, err = _render_pages(pdf, extra)
    if newdir is None:
        res["log"] = err + "\n" + tail
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res
    head_short = _commit_pages(newdir)
    res["head"] = head_short

    res["state"] = "ok_errors" if res["errors"] else "ok"
    res["ok"] = True
    res["build"] = newdir.name
    res["pages"] = len(list(newdir.glob("page-*.png")))
    res["elapsed_s"] = round(time.time() - t0, 1)
    return res


def _render_pages(pdf: Path, extra: list):
    """Renders pages into a new directory and drops in a copy of the PDF (and extra - synctex). The screen keeps showing the old directory until this finishes.
    Returns (directory, None) or (None, error message)."""
    D = cur_doc()
    D.dir.mkdir(parents=True, exist_ok=True)
    bid = time.strftime("%Y%m%d%H%M%S")
    name = "pages-" + bid
    k = 1
    while (D.dir / name).exists():
        name = "pages-%s-%d" % (bid, k)
        k += 1
    newdir = D.dir / name
    newdir.mkdir(parents=True)
    build_state_update(phase="render")
    try:
        r = subprocess.run(["pdftoppm", "-r", str(C.dpi), "-png", str(pdf), str(newdir / "page")],
                           capture_output=True, timeout=600)
        ok_render = r.returncode == 0 and any(newdir.glob("page-*.png"))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        ok_render = False
    if not ok_render:
        shutil.rmtree(newdir, ignore_errors=True)
        return None, "쪽 이미지를 그리지 못했습니다(pdftoppm)."
    try:
        shutil.copy2(pdf, newdir / D.pdf_name)
        for f in extra:
            shutil.copy2(f, newdir / f.name)
    except OSError as e:
        shutil.rmtree(newdir, ignore_errors=True)
        return None, "PDF 사본을 쪽 디렉토리에 두지 못했습니다: %s" % e
    return newdir, None


def _commit_pages(newdir: Path) -> str:
    """Swaps the pointer to the new page directory in one shot (atomically), keeps only current+previous, and writes built_at/head. head is the short hash."""
    D = cur_doc()
    prev = cur_pages().name
    atomic_write(D.dir / "pages.cur", newdir.name)       # a single atomic swap
    for d in D.dir.iterdir():                            # keep only current and previous
        if d.is_dir() and PAGES_DIR_RE.fullmatch(d.name) and d.name not in (newdir.name, prev):
            shutil.rmtree(d, ignore_errors=True)
    atomic_write(D.dir / "built_at.txt", datetime.now().astimezone().isoformat(timespec="seconds"))
    try:
        head = subprocess.run(["git", "-C", str(D.src), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        head_short = head.stdout.strip() or "-"
    except (OSError, subprocess.SubprocessError):
        head_short = "-"
    atomic_write(D.dir / "head.txt", head_short)
    return head_short


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


SRC_TEX_EXTS = (".tex", ".bib", ".sty", ".cls", ".bst")
SRC_FIG_EXTS = (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg")
SRC_MTIME_EXTS = SRC_TEX_EXTS + SRC_FIG_EXTS
# Build artifact directories (in case the state directory is placed inside the manuscript) + directories the build rsync excludes.
BUILD_OUTDIRS = ("build", "out") + BUILD_EXCLUDE_DIRS

_SRC_MTIME_CACHE: list = [None, 0.0, 0.0]     # [C.src string, value, measured-at time] - a 2-second cache (for a single document)
_SRC_MTIME_LOCK = threading.Lock()

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


def _excluded_dir(name: str) -> bool:
    return name.startswith(".") or name in BUILD_OUTDIRS


def iter_sources(root: Path):
    """Yields manuscript/figure-extension files under root as (relative path 'a/b.tex', os.DirEntry).

    src_mtime (badge / stale-PDF warning) and source_fingerprint (build fingerprint) look at the same list -
    if they saw different files, mismatches like "badge is off but estimation is on" would appear. Dot (.)
    directories, build artifacts / directories the build rsync excludes (BUILD_OUTDIRS), a state directory
    placed inside the manuscript, and the root's main PDF are all excluded."""
    D = cur_doc()
    main_pdf = D.pdf_name
    main_at = tuple(D.main_rel.parent.parts)            # the PDF next to the main .tex (a build artifact / committed copy) is not part of the manuscript
    state_in_root = None
    try:
        state_in_root = tuple(C.state.resolve().relative_to(root.resolve()).parts)
    except (ValueError, OSError, RuntimeError):
        pass

    def walk(d: Path, rel_parts: tuple):
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                if _excluded_dir(e.name):
                    continue
                parts = rel_parts + (e.name,)
                if state_in_root is not None and parts == state_in_root:
                    continue
                yield from walk(Path(e.path), parts)
            elif e.is_file(follow_symlinks=False):
                if e.name == main_pdf and rel_parts == main_at:
                    continue
                if os.path.splitext(e.name)[1].lower() in SRC_MTIME_EXTS:
                    yield "/".join(rel_parts + (e.name,)), e
    yield from walk(root, ())


def doc_fingerprint(D: Doc) -> str:
    """The document's manuscript fingerprint. For view-only, this is the hash of the PDF file's contents."""
    if D.is_pdf:
        h = hashlib.sha256()
        with open(D.main, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:32]
    with using_doc(D):
        return source_fingerprint(D.src)


def source_fingerprint(root: Path) -> str:
    """Manuscript fingerprint - a hash of (relative path, content) over the files iter_sources yields. mtime is not included:
    a file whose content is unchanged but timestamp changed (e.g. via git checkout) should not change the layout."""
    h = hashlib.sha256()
    for rel, e in iter_sources(root):
        try:
            with open(e.path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).digest()
        except OSError:
            continue
        h.update(rel.encode("utf-8", "surrogateescape") + b"\0" + digest)
    return h.hexdigest()[:32]


def src_mtime(force: bool = False) -> float:
    """Max mtime over manuscript/figure extensions under C.src (2-second cache). Build artifacts and the main PDF are excluded (iter_sources).

    C.build, which build_all() populates via rsync, is normally under C.state (i.e. outside C.src), but it
    is also excluded by name so that even the rare layout with the state directory inside the manuscript
    tree doesn't false-positive "manuscript changed" from build artifacts. C.src is included in the cache
    key so that if the manuscript path changes within the same process (tests, or a rare reconfiguration),
    the old path's value is never mistakenly returned for the new path.

    force=True skips the cache and measures now - if write_built_src_mtime() used the 2-second cache value
    as-is when recording the build-start mtime, then editing the manuscript within 2 seconds of the cache
    being filled and immediately rebuilding would wrongly record the pre-edit mtime as "the build start time"."""
    D = cur_doc()
    cache = D.mcache
    key = str(D.src)
    if not force:
        with _SRC_MTIME_LOCK:
            ckey, val, at = cache
            if ckey == key and time.time() - at < 2.0:
                return val
    newest = 0.0
    if D.is_pdf:                                          # view-only: that one PDF file is the manuscript
        try:
            newest = D.main.stat().st_mtime
        except OSError:
            pass
    else:
        for _rel, e in iter_sources(D.src):
            try:
                newest = max(newest, e.stat().st_mtime)
            except OSError:
                pass
    with _SRC_MTIME_LOCK:
        cache[0], cache[1], cache[2] = key, newest, time.time()
    return newest


def read_built_src_mtime():
    try:
        return float((cur_doc().dir / "built_src_mtime.txt").read_text().strip())
    except (OSError, ValueError):
        return None


def write_built_src_mtime(value: float = None) -> None:
    """If value is omitted, measures the current src_mtime(force=True) and records it (skipping the 2-second cache).

    The caller (_build_tracked) passes the mtime of "the manuscript this build actually compiled" - after
    the pull with --git-pull (a fast-forward can bump the .tex mtime), otherwise the value measured right
    before the copy. This function is only called to commit that value when the build finished ok|ok_errors -
    a failed build still shows the old PDF on screen, so the "manuscript modified" badge must not turn off."""
    try:
        v = src_mtime(force=True) if value is None else value
        atomic_write(cur_doc().dir / "built_src_mtime.txt", "%f" % v)
    except OSError:
        pass


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

def norm(line: str) -> str:
    return " ".join(line.split())


def truncate_quote(s, n: int = 60) -> str:
    """Truncates a quote to at most n characters (ellipsis included, matching the «...» convention).

    If a truncated quote looked like a complete sentence, it would be confusing when trying to relocate the
    source - the truncation mark is what tells the user/agent to read this as a "search hint", not the
    "whole thing". When truncating, the ellipsis is appended after n-1 characters of body text, so the
    result is always n characters or fewer (never n+1 from n characters plus the ellipsis)."""
    s = str(s)
    return s[:n - 1] + "…" if len(s) > n else s


def is_comment(line: str) -> bool:
    return line.lstrip().startswith("%")


def strip_comment(line: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", line)


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
        raise HTTPError(400, "원고 디렉토리 밖의 파일입니다: %s" % p)
    out = C.src / rel
    if not out.is_file():
        raise HTTPError(400, "원고 안에 그런 파일이 없습니다: %s" % p)
    return out


# ---------------------------------------------------------------- Reverse mapping 1: SyncTeX

def synctex_edit(pdf: Path, page: int, x: float, y: float):
    try:
        out = subprocess.run(["synctex", "edit", "-o", "%d:%.2f:%.2f:%s" % (page, x, y, pdf)],
                             capture_output=True, text=True, timeout=10).stdout
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


def densest(values: list, gap: int = 30) -> list:
    """Breaks at large gaps and keeps only the densest cluster.

    synctex returns the node *closest* to the query coordinate, so even a point inside the selection
    rectangle can pull in a line from an adjacent float (observed: selecting a single table returned a
    range spanning 740-801)."""
    if not values:
        return values
    groups = [[values[0]]]
    for v in values[1:]:
        if v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return max(groups, key=len)


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
    ls = densest(sorted(l for f, l in hits if f == best))
    return best, ls[0], ls[-1]


# ---------------------------------------------------------------- Reverse mapping 2: rendered text

def region_text(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float) -> str:
    """Pulls out the characters actually printed inside the selection rectangle (1px = 1pt since -r 72)."""
    try:
        return subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-r", "72",
             "-x", str(int(x0)), "-y", str(int(y0)),
             "-W", str(max(1, int(x1 - x0))), "-H", str(max(1, int(y1 - y0))), str(pdf), "-"],
            capture_output=True, text=True, timeout=15).stdout
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


def score_range(tw: list, lines: list, lo: int, hi: int) -> float:
    """Scores 0-1 how much of the region's characters a candidate line range contains."""
    if not tw:
        return 0.0
    blob = " ".join(lines[max(0, lo - 2):hi + 1])
    return sum(w for t, w in tw if t in blob) / sum(w for _, w in tw)


def by_text(tw: list, lines: list, near=None):
    """Recovers source lines from the rendered text's word tokens.

    This is the path used when SyncTeX stays silent or points somewhere wrong on a table/equation region.
    Korean word tokens survive almost untouched by markup (e.g. `타겟--소스 $i$ 간 코사인 거리`), so they
    remain in the source text as-is."""
    if len(tw) < 2:
        return None
    scores = [sum(w for t, w in tw if t in ln) for ln in lines]
    if max(scores, default=0) <= 0:
        return None
    peak = max(range(len(scores)), key=lambda i: (scores[i], -abs(i + 1 - (near or i + 1))))
    lo = hi = peak
    while lo > 0 and scores[lo - 1] > 0:
        lo -= 1
    while hi < len(scores) - 1 and scores[hi + 1] > 0:
        hi += 1
    return lo + 1, hi + 1, score_range(tw, lines, lo + 1, hi + 1)


# ---------------------------------------------------------------- Block expansion and the range ladder

def expand_block(lines: list, lo: int, hi: int):
    """Expands the selected lines to the enclosing environment (--float-envs) or paragraph boundary. Used to determine the default level.

    An environment must be closed by a \\end of the same name - without matching the name, the selection
    leaks into an adjacent float (observed: selecting one table pulled in 109 lines)."""
    n = len(lines)
    if not n:
        return lo, hi, "none"
    lo, hi = max(1, min(lo, n)), max(lo, min(hi, n))
    alt = "|".join(re.escape(e) for e in C.envs)
    b_re = re.compile(r"\\begin\{(" + alt + r")(\*?)\}")
    e_re = re.compile(r"\\end\{(" + alt + r")(\*?)\}")

    for i in range(lo - 1, -1, -1):
        if e_re.search(lines[i]) and i < lo - 1:
            break
        m = b_re.search(lines[i])
        if not m:
            continue
        env = m.group(1) + m.group(2)
        close = re.compile(r"\\end\{" + re.escape(env) + r"\}")
        opens = re.compile(r"\\begin\{" + re.escape(env) + r"\}")
        depth = 0
        for j in range(i + 1, n):
            if opens.search(lines[j]):
                depth += 1
            if close.search(lines[j]):
                if depth:
                    depth -= 1
                    continue
                return i + 1, j + 1, "float" if m.group(1) in FLOAT_KINDS else "block"
        break

    a, b = para_bounds(lines, lo, hi)
    return a, b, "paragraph"


SECTION_RE = re.compile(r"\s*\\(part|chapter|section|subsection|subsubsection|paragraph)\*?[\[{]")


def para_bounds(lines: list, lo: int, hi: int) -> tuple:
    """Expands to the nearest blank line. A section-heading line (\\section/\\subsection/...) is never crossed in either direction."""
    n = len(lines)
    a, b = lo, hi
    while a > 1 and lines[a - 2].strip() and not SECTION_RE.match(lines[a - 2]):
        a -= 1
    while b < n and lines[b].strip() and not SECTION_RE.match(lines[b]):
        b += 1
    return a, b


def trim_comments(lines: list, a: int, b: int) -> tuple:
    """Trims leading/trailing pure-comment lines (starting with %). Does nothing if every line is a comment.

    In a manuscript where one paragraph is one line, this stops a trailing TODO comment from becoming the tail of the pin range and its anchor."""
    x, y = a, b
    while x <= y and is_comment(lines[x - 1]):
        x += 1
    while y >= x and is_comment(lines[y - 1]):
        y -= 1
    return (a, b) if x > y else (x, y)


def env_spans(lines: list) -> list:
    """(start line, end line, name) - every environment paired up by matching name and depth. A \\begin inside a comment is ignored."""
    stack, spans = [], []
    for i, ln in enumerate(lines):
        for m in ENV_TOK_RE.finditer(strip_comment(ln)):
            name = m.group(2).strip()
            if m.group(1) == "begin":
                stack.append((name, i + 1))
                continue
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == name:
                    spans.append((stack[k][1], i + 1, name))
                    del stack[k:]
                    break
    return spans


def snippet(lines: list, lo: int, hi: int, cap: int = 80) -> str:
    chunk = lines[lo - 1:hi]
    extra = len(chunk) - cap
    if extra > 0:
        chunk = chunk[:cap]
    out = "\n".join("%5d  %s" % (lo + k, t) for k, t in enumerate(chunk))
    return out + ("\n      ... (%d줄 더)" % extra if extra > 0 else "")


def find_level(levels: list, key: str):
    for lv in levels:
        if lv["level"] == key or key in lv.get("merged", ()):
            return lv
    return None


def compute_levels(lines: list, raw_lo: int, raw_hi: int) -> dict:
    """The range ladder: dragged line / paragraph (trailing comments excluded) / enclosing environments, innermost to outermost, up to 3 levels.

    Snippets are included up front so the client can switch levels without a server round trip. There is no
    section level - that would easily produce hundred-line ranges, against the "hand over only a line range" principle."""
    n = len(lines)
    raw_lo = max(1, min(raw_lo, n))
    raw_hi = max(raw_lo, min(raw_hi, n))
    levels: list = []

    def add(level, lo, hi, label, env=None):
        item = {"level": level, "lo": lo, "hi": hi, "label": label, "n": hi - lo + 1,
                "snippet": snippet(lines, lo, hi)}
        if env:
            item["env"] = env
        for i, old in enumerate(levels):              # levels with the same range are merged (keeping the later name)
            if (old["lo"], old["hi"]) == (lo, hi):
                item["merged"] = old.get("merged", []) + [old["level"]]
                levels[i] = item
                return
        levels.append(item)

    add("raw", raw_lo, raw_hi, "드래그한 줄")
    spans = env_spans(lines)
    encl = sorted((s for s in spans if s[0] <= raw_lo <= s[1] and s[2] != "document"),
                  key=lambda s: (s[1] - s[0], -s[0]))
    pa, pb = para_bounds(lines, raw_lo, raw_hi)
    if encl:
        # A paragraph never crosses the innermost enclosing environment. If the drag is strictly inside that
        # environment, the \begin/\end lines are also excluded - otherwise a "paragraph" inside a table would
        # swallow \end{table*} and the line after it, drifting out of sync with the environment (observed: L187-L270).
        ea, eb = encl[0][0], encl[0][1]
        if ea < raw_lo and raw_hi < eb:
            ea, eb = ea + 1, eb - 1
        pa, pb = max(pa, ea), min(pb, eb)
        if pa > pb:
            pa, pb = raw_lo, raw_hi
    # Also never half-overlaps an environment outside the drag (a paragraph right after \end{table*} was
    # swallowing the table's tail). An environment fully contained in the paragraph (an equation with no
    # blank-line break) is left as-is.
    for a, b, name in spans:
        if name == "document" or a <= raw_lo <= b:
            continue
        if b < raw_lo and a < pa <= b:
            pa = b + 1
        elif a > raw_hi and a <= pb < b:
            pb = a - 1
    pa, pb = min(pa, raw_lo), max(pb, raw_hi)
    pa, pb = trim_comments(lines, pa, pb)
    add("para", pa, pb, "문단")
    # If the outer environment wraps the inner one by exactly one line on each side (a single tabular inside
    # a minipage), treat them as the same block - listing the inner one separately would waste a ladder
    # rung on an almost-identical range. The outer name is kept.
    encl = [s for i, s in enumerate(encl)
            if not any(o[0] == s[0] - 1 and o[1] == s[1] + 1 for o in encl[i + 1:])]
    for k, (a, b, name) in enumerate(encl[:3]):
        key = "env" if k == 0 else "env%d" % (k + 1)
        suffix = "" if k == 0 else (" (바깥)" if k == 1 else " (바깥 2)")
        add(key, a, b, "환경 %s%s" % (name, suffix), env=name)

    ea, eb, kind = expand_block(lines, raw_lo, raw_hi)
    default = None
    if kind in ("float", "block"):
        for lv in levels:
            if lv["level"].startswith("env") and (lv["lo"], lv["hi"]) == (ea, eb):
                default = lv
                break
        if default is None:
            default = next((lv for lv in levels if lv["level"].startswith("env")), None)
    if default is None:
        default = find_level(levels, "para")
        kind = "paragraph"
    if not default["level"].startswith("env") and kind != "paragraph":
        kind = "paragraph"
    return {"levels": levels, "default_level": default["level"], "lo": default["lo"],
            "hi": default["hi"], "kind": kind}


# ---------------------------------------------------------------- Anchors and re-syncing

def anchor_of(lines: list, lo: int, hi: int) -> dict:
    """Captures the head/tail text of the block a pin points at (pure-comment lines are skipped).

    Storing only line numbers means every pin drifts the moment the manuscript is edited once. The whole
    point of this tool is "an agent edits the manuscript", so a design where editing kills the pins is
    unusable. Comments are skipped because a TODO comment is a line about to be deleted - anchoring to it
    would kill the pin first.

    head_off/tail_off are the distance from lo to the head line, and from the tail line to hi. Without
    these, a pin that deliberately included comment lines at its edges would silently shrink on the first
    line-matching pass (observed: L7-L9 -> L10-L11)."""
    idx = [i for i in range(lo - 1, min(hi, len(lines))) if lines[i].strip()]
    body = [i for i in idx if not is_comment(lines[i])] or idx
    if not body:
        return {}
    return {"head": norm(lines[body[0]]), "tail": norm(lines[body[-1]]),
            "head_off": body[0] - (lo - 1), "tail_off": (hi - 1) - body[-1]}


def _off(v) -> int:
    return v if _is_int(v) and 0 <= v < 10000 else 0


def find_line(nlines: list, needle: str, near: int):
    if not isinstance(needle, str) or not needle:
        return None
    cands = [i for i, t in enumerate(nlines) if t == needle]
    if not cands and len(needle) >= 12:
        key = needle[:40]
        cands = [i for i, t in enumerate(nlines) if key in t]
    if not cands:
        return None
    return min(cands, key=lambda i: abs(i + 1 - near)) + 1


def sync_all(rows: list) -> bool:
    """If the manuscript is newer than a pin, re-match its line numbers via the anchor. Records whose lines or stale flag changed get rev+1."""
    changed = False
    cache: dict = {}
    for r in rows:
        if r.get("done") or not r.get("file"):         # a view-only PDF's pin has no lines - nothing to re-match
            continue
        f = Path(r.get("file", ""))
        if not in_tree(str(f)):
            continue
        try:
            if not f.is_file():
                continue
        except OSError:
            continue
        if f not in cache:
            ls = tex_lines(f)
            cache[f] = (ls, [norm(t) for t in ls], f.stat().st_mtime)
        lines, nlines, mtime = cache[f]
        if "anchor" not in r:                        # backfill a legacy pin saved without an anchor, once
            r["anchor"] = anchor_of(lines, r["lo"], r["hi"])
            r["synced_at"] = mtime
            changed = True
            continue
        if not r["anchor"] or r.get("synced_at", 0) >= mtime:   # a pin that selected only blank lines has no anchor to follow
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
            r["rev"] = int(r.get("rev") or 0) + 1
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
    for k in ("name", "kind", "via", "scope", "sync", "pdf_build", "frac_build"):
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


def in_tree(p: str) -> bool:
    """Is the record's file inside the manuscript tree? If outside, line-matching/editing never reads that
    file (reading it would let a line from outside the tree leak into the anchor and out via GET /api/pins)."""
    try:
        Path(p).resolve().relative_to(C.src.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


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
    out = dict(r)
    out["rev"] = out["rev"] if _is_int(out.get("rev")) else 0
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
        by_file.setdefault(r.get("file"), []).append(r)
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
        if r.get("done") or r.get("file") != file:
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
            raise HTTPError(400, "%s.file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다." % what)
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
        r = find_pin(rows, pid)
        if r is None:
            raise HTTPError(404, "핀 #%d 이 없습니다." % pid)
        if r.get("done") and (moves or scope is not None or kind is not None):
            raise HTTPError(409, "done", pin=public(r), detail="닫힌 핀은 메모만 고칠 수 있습니다.")
        if base_given and int(r.get("rev") or 0) != base:
            raise HTTPError(409, "conflict", pin=public(r))
        old_note = str(r.get("note") or "")         # to tell a new @-tag from one the note already had (_set_note_mentions)
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
            if not in_tree(r["file"]):
                raise HTTPError(400, "원고 디렉토리 밖을 가리키는 핀입니다 — 위치 다시 잡기(loc)로 고치세요.")
            f = Path(r["file"])
            n = len(tex_lines(f))
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
        if range_changed and not region and in_tree(r["file"]):
            f = Path(r["file"])
            r["anchor"] = anchor_of(tex_lines(f), r["lo"], r["hi"])
            r["synced_at"] = f.stat().st_mtime if f.exists() else 0
            r.pop("stale", None)
            r.pop("sync", None)
        if has_note:
            r["note"] = note
        if note_append is not None:
            stamp = "(추가 %s) " % datetime.now().astimezone().strftime("%H:%M")
            merged = str(r.get("note") or "") + ("\n" if r.get("note") else "") + stamp + note_append
            if len(merged) > NOTE_MAX:
                raise HTTPError(400, "덧붙이면 메모가 너무 깁니다(%d자, %d자 이하)." % (len(merged), NOTE_MAX))
            r["note"] = merged
        if kind_req is not None:
            r["kind_req"] = kind_req
        if has_note or note_append is not None:
            _set_note_mentions(r, rows, hints, actor, evs, old_note)
        _set_assignee(r, assignee, actor, evs, record=True)
        r["edited_at"] = now_str()
        r["edited_by"] = who(actor)
        r["rev"] = int(r.get("rev") or 0) + 1
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
    mid = max((m.get("id", 0) for m in th if isinstance(m, dict) and _is_int(m.get("id"))), default=0) + 1
    msg = {"id": mid, "by": _msg_by(actor), "at": now_str(), "text": text or ""}
    if ev:
        msg["ev"] = ev
    if ref:
        msg["ref"] = ref
    if mentions:
        msg["mentions"] = list(mentions)
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


def _set_note_mentions(r: dict, rows: list, hints, actor: dict, evs: list, old_note: str = "") -> None:
    """Resolves the note's @-tags into r['mentions'] (drops the field if none). Queues a mention event for everyone
    this save or edit explicitly @-tags: a person whose '@name' occurs more often in the new note than in old_note
    (the note before this edit; empty for a new pin). A typo fix next to an existing '@Bob' notifies nobody, while
    an edit or note_append that writes '@Bob' again notifies Bob even though the note already tagged him."""
    ppl = known_people(rows)
    me = (actor or {}).get("login")
    hits = mention_hits(r.get("note") or "", ppl, hints, exclude=me)
    before = Counter(mention_hits(old_note or "", ppl, hints, exclude=me))
    new = list(dict.fromkeys(hits))
    if new:
        r["mentions"] = new
    else:
        r.pop("mentions", None)
    now = Counter(hits)
    evs.append(make_event("mention", r, actor, [lg for lg in new if now[lg] > before[lg]], text=r.get("note")))


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
        raise HTTPError(400, "ev 는 정수(마지막으로 본 이벤트 seq)입니다.")
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
    """Does a reply reopen this pin? The one rule behind the viewer's single [Reply] (docs/handbook/api.md §스레드 (답글)).

    An open pin never changes. Otherwise an explicit `reopen` (true/false, from the request) decides; without one, a
    human's reply on a pin awaiting review or done reopens it - the reply becomes the rework instruction - unless it
    tags a person (then it is a conversation with that person) or the pin is a question (then the reply is an answer).
    An agent's reply never reopens by the rule. `mentioned` is the post's resolved @-tags without the poster.
    The viewer's preview (replyReopens) mirrors this function."""
    if pin_state(r) == "open":
        return False
    if reopen is not None:
        return bool(reopen)
    if r.get("kind_req") == "question" or not human:
        return False
    return not mentioned


def clean_reopen_flag(d: dict):
    """The reply body's optional reopen - true/false overrides the rule, absent (None) lets the server decide."""
    v = d.get("reopen")
    if v is not None and not isinstance(v, bool):
        raise HTTPError(400, "reopen 은 true/false 입니다(없으면 서버 규칙을 따릅니다).")
    return v


def reply_pin(pid: int, text: str, actor: dict, hints=None, reopen=None, human=None):
    """One reply (from a person or an agent). Returns (pin, msg); an unknown id returns (None, None).

    Whether it also reopens the pin is decided here by reply_reopens() - the viewer only previews it. `human` is
    whether the poster is a person (the handler also counts a person with the agent role as an agent); None means
    "not an agent actor". A reopening reply is recorded exactly like POST /reopen with the reply as its reason
    (ev=reopen, the same events), so the pin returns to the open table of pins.md with that reason. Otherwise it is
    a plain reply: 409 if the thread is full; every @-tag in it is a mention event (whether or not tagged before),
    and the author plus everyone previously tagged on this pin who is not tagged here gets a replied event. The
    poster themself gets neither."""
    evs = []
    human = (not is_agent(actor)) if human is None else human

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return (None, None), False
        ment = resolve_mentions(text, known_people(rows), hints, exclude=(actor or {}).get("login"))
        persons = [lg for lg in ment if role_of(lg) != "agent"]     # tagging an agent-role account is not asking a person
        if reply_reopens(r, human, persons, reopen):
            before = pin_mentions_all(r)
            msg = _reopen(r, rows, actor, text, hints, evs)
            # _reopen told the author (reopened) and everyone this reply tags (mention). Everyone else tagged on the pin
            # earlier would have heard of a plain reply (replied) - reopening must not silence them.
            author = (r.get("author") or {}).get("login")
            evs.append(make_event("replied", r, actor, [lg for lg in sorted(before) if lg != author and lg not in (msg.get("mentions") or [])],
                                  msg=msg))
            r["rev"] = int(r.get("rev") or 0) + 1
            return (public(r), msg), True
        if len(thread_replies(r)) >= THREAD_MAX:
            raise HTTPError(409, "full", detail="스레드가 가득 찼습니다(답글 %d건). 새 핀으로 이어 가세요." % THREAD_MAX)
        before = pin_mentions_all(r)
        msg = _thread_append(r, actor, text, mentions=ment)
        r["rev"] = int(r.get("rev") or 0) + 1
        # Every @-tag in this reply is a mention, even for someone tagged earlier on the pin (observed in the
        # v0.2.0 QA: a second "@Bob ..." reached nobody). Everyone else involved gets replied - never both.
        evs.append(make_event("mention", r, actor, ment, msg=msg))
        evs.append(make_event("replied", r, actor, [lg for lg in [(r.get("author") or {}).get("login")] + sorted(before)
                                                    if lg not in ment], msg=msg))
        return (public(r), msg), True
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
    """Open/close. `reply`/`ref` (already validated by clean_close_body) are only used when closing, and only recorded on the first close.

    Re-closing an already-closed pin changes nothing (§P0b-보완 D) - this prevents a second close from
    overwriting done_at/closed_by and erasing who closed it first (observed defect). rev also stays
    unchanged. To leave a new reply, the pin must be reopened and closed again - so a reopen clears the old
    close_reply/close_ref (the next close fills them in fresh).

    Awaiting review (§Pending review): if an agent (no identity header) closes it, review=true is left on, so it
    isn't done until a person [confirms] it - out of 42 observed cases, an author reopened an agent-closed
    pin twice (#28, #42) with no record that a person had ever looked at the result. If a tailnet person
    closes it, that person is the reviewer, so it's done right away. If the body supplies review, that's
    followed instead - a remote agent closing via a tailnet address arrives with a person's identity, so it
    sends review=true. Reopening clears the review/confirm record, and if the pin had been closed, the
    reopen reason (reason) is recorded in the thread.

    changes (v0.3, validated by clean_close_changes) are stored on the first close with changes_at = done_at, which
    ties them to that close (docs/adr/0005-pin-scoped-changes.md); a reopen clears both."""
    evs = []

    def fn(rows):
        """The transact() step: applies the close or reopen to pin pid in rows. Returns (public pin or None, whether
        rows changed); an already closed pin is returned unchanged."""
        r = find_pin(rows, pid)
        if r is None:
            return None, False
        if done:
            if r.get("done"):
                return public(r), False           # already closed - changes nothing (rev unchanged too)
            r["done"] = True
            r["done_at"] = now_str()
            r["closed_by"] = who(actor)
            if reply:
                r["close_reply"] = reply
            if ref:
                r["close_ref"] = ref
            if changes:
                r["changes"] = [c.record() for c in changes]   # v0.3 (docs/adr/0005)
                r["changes_at"] = r["done_at"]    # ties the set to this close (a 0.2.2 re-close after a rollback would not)
            if review if review is not None else is_agent(actor):
                r["review"] = True
            msg = _thread_append(r, actor, reply or "", ev="close", ref=ref)   # the close reason also goes in the thread - one unified line of history
            if r.get("review"):
                evs.append(make_event("review_requested", r, actor, [(r.get("author") or {}).get("login")], msg=msg))
            _clear_claim(r)                       # closing also clears the in-progress claim (§P0c-C)
        else:
            _reopen(r, rows, actor, reason, hints, evs)
        r["rev"] = int(r.get("rev") or 0) + 1
        return public(r), True
    with PIN_LOCK:
        out = transact(fn)[1]
        emit_events(evs)
    return out


def _reopen(r: dict, rows: list, actor: dict, reason, hints, evs: list):
    """Reopens r in place (inside transact): clears the review/confirm record and the old close reason so the next
    close fills them in fresh, and - if the pin was closed - records the reason in the thread (ev=reopen) and queues a
    mention for everyone it @-tags and reopened for the author. Shared by POST /reopen and a reopening reply.
    Returns the thread message, or None for an already open pin (nothing is recorded then)."""
    was_done = bool(r.get("done"))
    r["done"] = False
    r["reopened_at"] = now_str()
    r["reopened_by"] = who(actor)
    r.pop("close_reply", None)
    r.pop("close_ref", None)
    r.pop("changes", None)                        # v0.3: the recorded lines belong to that close
    r.pop("changes_at", None)
    for k in ("review", "confirmed_by", "confirmed_at"):
        r.pop(k, None)
    if not was_done:
        return None
    ment = resolve_mentions(reason or "", known_people(rows), hints, exclude=(actor or {}).get("login"))
    msg = _thread_append(r, actor, reason or "", ev="reopen", mentions=ment)
    evs.append(make_event("mention", r, actor, ment, msg=msg))    # same rule as a reply: every @-tag here
    evs.append(make_event("reopened", r, actor, [lg for lg in [(r.get("author") or {}).get("login")]
                                                 if lg not in ment], msg=msg))
    return msg


def confirm_pin(pid: int, actor: dict):
    """Awaiting review -> done. **Only a person** can press this (the viewer merely suggests the author as reviewer - it's a trust model.
    A request with no identity header (agent/local curl) gets 403 - awaiting review exists specifically as a
    record that a person looked at a pin the agent closed, so an agent confirming its own work would defeat
    the point). Records confirmed_by/confirmed_at and appends ev=confirm to the thread. Already done changes
    nothing and just returns as-is (idempotent, like close). 409 open for an open pin. An unknown id returns None."""
    if is_agent(actor):
        raise HTTPError(403, CONFIRM_BY_HUMAN)

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return None, False
        st = pin_state(r)
        if st == "open":
            raise HTTPError(409, "open", pin=public(r), detail="열린 핀은 확인할 것이 없습니다 — 닫힌 뒤 검토 대기일 때 확인합니다.")
        if st == "done":
            return public(r), False
        r.pop("review", None)
        r["confirmed_by"] = who(actor)
        r["confirmed_at"] = now_str()
        _thread_append(r, actor, "", ev="confirm")
        r["rev"] = int(r.get("rev") or 0) + 1
        return public(r), True
    return transact(fn)[1]


def drop_pin(pid: int, actor: dict) -> bool:
    """Removes a pin from pins.jsonl and moves it to the Trash (pins.dropped.jsonl). restore brings the same id back.

    The author is told when someone else deletes their pin (a `dropped` event, with [Restore] in the viewer). Expired
    Trash entries are purged in the same write (purge_trash)."""
    evs = []

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return False, False
        rows.remove(r)
        _clear_claim(r)                           # a claim is never left behind on delete either (§P0c-C)
        gone = dict(r, dropped_at=now_str(), dropped_by=who(actor))
        old, bad = read_jsonl(C.dropped)
        write_dropped(_unexpired(old) + [gone], bad)
        evs.append(make_event("dropped", r, actor, [(r.get("author") or {}).get("login")], text=r.get("note")))
        return True, True
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


def purge_pin(pid: int, actor: dict) -> int:
    """The owner's permanent delete from the Trash (POST /api/pins/{id}/purge; check_role refuses everyone else).
    404 if the pin is not in the Trash - an open or closed pin must be dropped first. Leaves a `purged` audit event
    (to: [], like `cleared`) and a log line, since it cannot be undone."""
    with PIN_LOCK:
        rows, bad = read_jsonl(C.dropped)
        if not any(r.get("id") == pid for r in _unexpired(rows)):
            raise HTTPError(404, "휴지통에 핀 #%d 이 없습니다." % pid)
        write_dropped(_unexpired([r for r in rows if r.get("id") != pid]), bad)
        emit_events([{"type": "purged", "to": [], "pin": pid, "by": who(actor)}])
    print("trash: pin #%d deleted permanently by %s" % (pid, (actor or {}).get("login")), file=sys.stderr)
    sys.stderr.flush()
    return pid


# ---------------------------------------------------------------- In-progress marker (claim, §P0c-C)
#
# A co-author and their agent can work on the same pin at the same time. A TTL'd optimistic marker reduces
# conflicts - it's a signal, not a lock: nothing stops closing or force-claiming a pin another identity holds a valid claim on.

def claim_active(r: dict) -> bool:
    """Does this pin have an unexpired claim? claim_until is epoch seconds (compared independent of timezone)."""
    cu = r.get("claim_until")
    return _is_num(cu) and float(cu) > time.time()


CLAIM_FIELDS = ("claimed_by", "claimed_at", "claim_ts", "claim_until", "eta_ts")


def _clear_claim(r: dict) -> None:
    for k in CLAIM_FIELDS:
        r.pop(k, None)


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


def claim_pin(pid: int, actor: dict, ttl_min: int, eta_min: int = None):
    """Places the in-progress marker (or extends it, for the same identity). An unknown id returns (None, False) -
    the caller then reports {"ok": false}. 409 for a closed pin, or one where another identity holds a valid claim.

    An extension (a valid claim from the same identity) leaves the start time (claimed_at/claim_ts) as-is
    and re-measures the lock (claim_until) from now. If eta_min is given, the estimate (eta_ts) is also
    reset from now; if not, the earlier estimate is kept - if it's been exceeded, the screen shows "running
    behind estimate". On a fresh claim with no eta_min, there is no eta_ts either (shown as start time plus elapsed minutes)."""
    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return None, False
        if r.get("done"):
            raise HTTPError(409, "done", pin=public(r))
        me = who(actor)
        mine = claim_active(r) and (r.get("claimed_by") or {}).get("login") == me["login"]
        if claim_active(r) and not mine:
            raise HTTPError(409, "claimed", claimed_by=r["claimed_by"], claim_until=r["claim_until"],
                            eta_ts=r.get("eta_ts"))
        now = time.time()
        if not mine:
            _clear_claim(r)
            r["claimed_at"] = now_str()
            r["claim_ts"] = now
        elif not _is_num(r.get("claim_ts")):          # extending a legacy claim - backfills the start time as an epoch
            r["claim_ts"] = _epoch(r.get("claimed_at")) or now
        r["claimed_by"] = me
        r["claim_until"] = now + ttl_min * 60
        if eta_min is not None:
            r["eta_ts"] = now + eta_min * 60
        r["rev"] = int(r.get("rev") or 0) + 1
        return public(r), True
    return transact(fn)[1]


def unclaim_pin(pid: int, actor: dict):
    """Clears the in-progress marker - independent of the requester's identity (the trust model imposes no permission restriction here).
    An unknown id returns (None, False)."""
    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return None, False
        had = "claimed_by" in r
        _clear_claim(r)
        if had:
            r["rev"] = int(r.get("rev") or 0) + 1
        return public(r), had
    return transact(fn)[1]


def restore_pin(pid: int, actor: dict) -> dict:
    """Writes to pins.jsonl first, and only removes it from the dropped record once that succeeds.

    Reversing the order means a crash between the two writes makes the pin vanish from both files (observed).
    With this order, the worst case is "present in both", which is recoverable."""
    with PIN_LOCK:                                   # RLock - bundles transact and cleaning up the dropped record together
        rec = transact(lambda rows: _restore(rows, pid, actor))[1]
        old, bad = read_jsonl(C.dropped)
        write_dropped(_unexpired([r for r in old if r.get("id") != pid]), bad)
        return rec


def _restore(rows: list, pid: int, actor: dict):
    old, _ = read_jsonl(C.dropped)
    hits = [r for r in _unexpired(old) if r.get("id") == pid]
    if not hits:
        raise HTTPError(404, "삭제 기록에 핀 #%d 이 없습니다." % pid)
    if find_pin(rows, pid) is not None:
        raise HTTPError(409, "핀 #%d 이 이미 있습니다." % pid)
    rec = dict(hits[-1])
    rec.pop("dropped_at", None)
    rec.pop("dropped_by", None)
    rec["restored_at"] = now_str()
    rec["restored_by"] = who(actor)
    rec["rev"] = int(rec.get("rev") or 0) + 1
    sync_all([rec])
    rows.append(rec)
    rows.sort(key=lambda r: r["id"])
    return public(rec), True


CLEAR_CONFIRM = "clear all pins"


def clear_pins(actor: dict = None) -> dict:
    """Archives everything to pins_<ts>.jsonl.bak and clears it. pins.seq is untouched, so ids keep incrementing.
    Records a `cleared` event (who, how many, which archive) and a log line - the only bulk-destructive operation,
    so it always leaves a trace. Returns {"cleared": n, "archive": <file name or None>}."""
    with PIN_LOCK:
        n, archive = len(read_pins()[0]), None
        if C.pins_jsonl.exists():                    # clearing twice in the same second never overwrites the earlier archive
            dest = unique_path("pins_%s" % time.strftime("%y%m%d_%H%M%S"), ".jsonl.bak")
            C.pins_jsonl.rename(dest)
            archive = dest.name
        render_pins_md([])
        emit_events([{"type": "cleared", "to": [], "by": who(actor or LOCAL_ACTOR), "n": n, "archive": archive}])
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
    f = Path(str(r.get("file", "")))
    try:
        rel = f.resolve().relative_to(C.src.resolve())
        name = str(rel)
    except (ValueError, OSError, RuntimeError):
        name = f.name or str(r.get("name") or "")
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
    f = Path(str(r.get("file", "")))
    if not in_tree(str(f)):
        return ""
    lines = tex_lines(f)
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
    out.append(TOKEN_GUIDANCE)
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

    lad = compute_levels(lines, raw_lo, raw_hi)
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
        raise HTTPError(400, "lo·hi 는 정수여야 합니다.")
    if not 1 <= lo <= hi <= len(lines):
        raise HTTPError(400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (len(lines), lo, hi))
    out = {"file": str(f), "name": f.name, "lo": lo, "hi": hi, "n": hi - lo + 1,
           "n_lines": len(lines), "snippet": snippet(lines, lo, hi)}
    if (q.get("levels") or ["0"])[0] == "1":
        lad = compute_levels(lines, lo, hi)
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
        raise HTTPError(400, "lo·hi 는 정수여야 합니다.")
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
            raise ValueError("cannot read %s: %s" % (p, e))
        print("warning: cannot read %s (%s) - no agent token is accepted until it is fixed" % (p, e), file=sys.stderr)
        return []
    if strict and not (isinstance(d, dict) and isinstance(d.get("tokens"), list)):
        raise ValueError("%s is not a Limn token file" % p)
    return _valid_tokens(d)


def _write_tokens(state: Path, rows: list) -> None:
    atomic_write(Path(state) / "tokens.json",
                 json.dumps({"version": 1, "tokens": rows}, ensure_ascii=False, indent=1) + "\n", mode=0o600)


def token_create(state: Path, name: str = None) -> tuple:
    """Creates a token -> (entry, plaintext). Only the hash is stored; the plaintext is returned once and never again."""
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
    return entry, plain


def token_revoke(state: Path, ref: str):
    """Removes the token whose id or name is ref -> the removed entry, or None if there is none."""
    state = Path(state)
    if not (state / "tokens.json").exists():
        return None
    with store_lock(state, "tokens"):
        rows = load_tokens(state, strict=True)
        hit = [t for t in rows if t["id"] == ref] or [t for t in rows if t["name"] == ref]
        if not hit:
            return None
        _write_tokens(state, [t for t in rows if t is not hit[0]])
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
        raise ValueError("cannot read %s: %s" % (p, e))
    if not isinstance(d, dict) or not isinstance(d.get("people"), list):
        raise ValueError("%s is not a Limn people file" % p)
    return _valid_people(d)


def _people_update(state: Path, fn):
    """Read-modify-write of <state>/people.json under the same cross-process lock the server uses."""
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    with store_lock(state, "people"):
        rows = load_people_file(state)
        out = fn(rows)
        atomic_write(state / "people.json", people_text(rows), mode=0o600)
    return out


def member_add(state: Path, login: str, role: str = DEFAULT_ROLE, name: str = None) -> dict:
    if not valid_login(login):
        raise ValueError("invalid login %r (non-empty, no spaces, at most %d characters, not 'local' or 'agent:...')"
                         % (login, LOGIN_MAX))
    if role not in ROLES:
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
    name = " ".join((name or login.split("@")[0]).split())[:NAME_MAX] or login

    def fn(rows):
        if any(x["login"] == login for x in rows):
            raise ValueError("%s is already a member - change the role with `limn member role`" % login)
        entry = {"login": login, "name": name, "role": role}
        rows.append(entry)
        return entry
    return _people_update(state, fn)


def member_remove(state: Path, login: str):
    if not (Path(state) / "people.json").exists():
        return None

    def fn(rows):
        hit = next((x for x in rows if x["login"] == login), None)
        if hit is not None:
            rows.remove(hit)
        return hit
    return _people_update(state, fn)


def member_set_role(state: Path, login: str, role: str):
    if role not in ROLES:
        raise ValueError("role must be one of %s: %r" % (", ".join(ROLES), role))
    if not (Path(state) / "people.json").exists():
        return None

    def fn(rows):
        hit = next((x for x in rows if x["login"] == login), None)
        if hit is not None:
            hit["role"] = role
        return hit
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
                raise ValueError("--trusted-proxies takes IP addresses or CIDR ranges, got %r" % item)
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

HTML = r"""<!doctype html><html lang="ko" data-theme="light"><head><meta charset="utf-8">
<script>
(function(){var p=null;try{p=JSON.parse(localStorage.getItem('pinPrefs')||'null');}catch(e){}
 if(!p||typeof p!=='object'){p={theme:'light'};}else if(!p.theme){p.theme='light';}
 try{localStorage.setItem('pinPrefs',JSON.stringify(p));}catch(e){}
 var t=p.theme,eff=t;if(t==='system'){eff=(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark';}
 document.documentElement.setAttribute('data-theme',eff==='light'?'light':'dark');})();
</script>
<script>
// Interface language: ?lang=ko|en (remembered), then the saved choice, then the browser language.
window.LIMN_LANG=(function(){var v=null;try{v=new URLSearchParams(location.search).get('lang');}catch(e){}
 if(v==='ko'||v==='en'){try{localStorage.setItem('limnLang',v);}catch(e){}return v;}
 try{v=localStorage.getItem('limnLang');}catch(e){v=null;}
 if(v==='ko'||v==='en')return v;
 return String(navigator.language||'').toLowerCase().indexOf('ko')===0?'ko':'en';})();
document.documentElement.setAttribute('lang',window.LIMN_LANG);
</script>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=resizes-content">
<title>Limn · __LABEL__</title>
<link rel="icon" href="__FAVICON_HREF__">
<style>
/* ---------------- Design tokens (docs/handbook/viewer.md §디자인 토큰과 컴포넌트). Borrows only shadcn/ui's system (names/roles) - no code.
   Color literals live only in these two blocks (dark :root, light :root[data-theme=light]). Every rule uses var(--...).
   A regression test (FrontendDesignTokens) blocks color/radius/font-size literals outside these blocks. Neutral colors are the zinc family. */
:root{color-scheme:dark;
  --background:#09090b;--foreground:#fafafa;
  --sidebar:#18181b;--card:#131316;--card-foreground:#fafafa;--popover:#18181b;--popover-foreground:#fafafa;
  --muted:#27272a;--muted-foreground:#a1a1aa;--subtle-foreground:#8b8b94;
  --secondary:#27272a;--secondary-foreground:#fafafa;--accent:#2e2e33;--accent-foreground:#fafafa;
  --border:#27272a;--border-strong:#52525b;--input:#3f3f46;--field:#0c0c0e;--code:#0c0c0e;--outline-bg:#3f3f4633;
  --primary:#6ea8fe;--primary-foreground:#0b1220;--ring:var(--primary);
  --destructive:#f0787a;--destructive-foreground:#1f0708;
  --success:#4ec9a0;--success-foreground:#06231b;--warning:#e0a458;--warning-foreground:#2a1a04;
  --status-open:var(--success);--status-open-foreground:var(--success-foreground);--status-claimed:#f0b43c;
  --status-closed:var(--success);--status-dropped:#71717a;--status-warning:var(--warning);
  --status-review:#b197fc;--status-review-foreground:#1e1033;
  --tooltip:#09090b;--tooltip-foreground:#fafafa;
  --shadow-color:#00000088;--shadow-page:0 2px 18px var(--shadow-color)}
:root[data-theme=light]{color-scheme:light;
  --background:#e4e4e7;--foreground:#09090b;
  --sidebar:#ffffff;--card:#fafafa;--card-foreground:#09090b;--popover:#ffffff;--popover-foreground:#09090b;
  --muted:#f4f4f5;--muted-foreground:#52525b;--subtle-foreground:#71717a;
  --secondary:#f4f4f5;--secondary-foreground:#18181b;--accent:#e4e4e7;--accent-foreground:#09090b;
  --border:#e4e4e7;--border-strong:#a1a1aa;--input:#d4d4d8;--field:#ffffff;--code:#f4f4f5;--outline-bg:#ffffff;
  --primary:#1860cf;--primary-foreground:#ffffff;
  --destructive:#cf222e;--destructive-foreground:#ffffff;
  --success:#1a7f5a;--success-foreground:#ffffff;--warning:#8a5c00;--warning-foreground:#ffffff;
  --status-claimed:#b86e00;--status-dropped:#71717a;
  --status-review:#6d28d9;--status-review-foreground:#ffffff;
  --tooltip:#18181b;--tooltip-foreground:#fafafa;
  --shadow-color:#00000022;--shadow-page:0 1px 6px var(--shadow-color)}
/* Theme-independent scales: radius in 3 steps (only circular dots/avatars use 50%), text in 5 steps, spacing in
   6 steps, control heights. The label color (--brand) is filled in per instance by the server (--accent argument) and stays fixed across theme changes. */
:root{--brand:__ACCENT__;--brand-foreground:#ffffff;
  --outline-width:240px;--doc-nav-h:44px;
  --radius-sm:4px;--radius:6px;--radius-lg:10px;
  --text-xs:11px;--text-sm:12px;--text-base:13px;--text-lg:14px;--text-xl:16px;
  --space-1:4px;--space-2:8px;--space-3:12px;--space-4:16px;--space-5:20px;--space-6:24px;
  --control-h-sm:24px;--control-h:28px;--control-h-lg:36px;--control-h-touch:44px;
  --shadow-sm:0 1px 4px var(--shadow-color);--shadow:0 4px 16px var(--shadow-color);--shadow-lg:0 6px 24px var(--shadow-color);
  --font-sans:-apple-system,BlinkMacSystemFont,"Pretendard","Noto Sans KR",sans-serif;
  --font-mono:"JetBrains Mono",ui-monospace,monospace}
*{box-sizing:border-box}
[hidden]{display:none!important}
/* Viewer role (people.json role viewer, v0.2.1): the server refuses every change anyway; the screen stops offering it.
   Reading stays - view/jump, threads, the archive, the composer's location and source lines. */
body.role-viewer :is([data-act=edit],[data-act=drop],[data-act=close],[data-act=confirm],
  [data-act=reply-open],[data-act=reply-flip],[data-act=restore],[data-act=purge],[data-act=unclaim],[data-act=rebuild],[data-act=overlap-append],[data-act=overlap-separate],
  [data-act=kind],[data-act=e-kind],[data-act=assign-new],[data-act=assign-edit],[data-act=esave]),
body.role-viewer :is(#btn-save,#note,#c-kind,#c-assign,#c-qhint,#note-mentions){display:none!important}
body:not(.role-viewer) #c-viewer{display:none}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
body{margin:0;background:var(--background);color:var(--foreground);font:var(--text-lg)/1.55 var(--font-sans);
  display:flex;height:100vh;height:calc(100dvh - var(--kb,0px));overflow:hidden}
/* PDF area: blocks the browser's pinch zoom and passes through only scrolling - a two-finger gesture is handled by the app's own zoom (docs/handbook/viewer.md §PDF 영역 전용 확대). */
/* #main = document navigation + PDF area. #right's edit/pin screen is kept independent. */
#main{flex:1;display:flex;flex-direction:column;min-width:240px;min-height:0;position:relative}
#left{flex:1;overflow:auto;padding:var(--space-4) var(--space-4) 60vh 44px;min-width:240px;min-height:0;touch-action:pan-x pan-y}
#pdf-body{flex:1;display:flex;min-height:0;min-width:0}
#pdf-center{flex:1;display:flex;flex-direction:column;min-width:0;min-height:0}
#doc-nav{display:none;flex:none;align-items:center;gap:var(--space-3);height:var(--doc-nav-h);padding:0 var(--space-4);
  background:var(--sidebar);border-bottom:1px solid var(--border);font-size:var(--text-base)}
body:not(.lay-narrow) #doc-nav{display:flex}
#doc-nav .nav-sp{flex:1}
#paper-identity{display:inline-flex;align-items:center;gap:var(--space-2);flex:0 1 auto;min-width:0;max-width:180px;margin-right:var(--space-3);padding-right:var(--space-3);
  border-right:1px solid var(--border);color:var(--muted-foreground);font-size:var(--text-xs);font-weight:600;white-space:nowrap}
#paper-identity-mark{display:grid;place-items:center;width:15px;height:15px;border-radius:var(--radius-sm);background:var(--brand);
  color:var(--brand-foreground);font-size:var(--text-xs);line-height:1;font-weight:700}
#paper-identity>span:last-child{overflow:hidden;text-overflow:ellipsis}
body.lay-narrow #paper-identity{display:none}
#doc-select-wrap{display:none;align-items:center;gap:var(--space-2);min-width:0}
#doc-links{display:none;align-items:stretch;min-width:0;height:100%;gap:var(--space-5);margin-right:var(--space-3);overflow-x:auto}
#doc-links button{flex:none}
body.docs-multi:not(.lay-narrow) #doc-links{display:flex}
#doc-links button{position:relative;border:0;border-radius:0;background:transparent;color:var(--muted-foreground);padding:0 2px;font-size:var(--text-sm);white-space:nowrap}
#doc-links button[aria-current=page]{color:var(--foreground);font-weight:600}
#doc-links button[aria-current=page]::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:var(--brand)}
#doc-links button:hover,#doc-links button:focus-visible{color:var(--foreground)}
#doc-links .doc-link-count{font-size:var(--text-xs);color:var(--subtle-foreground);margin-left:var(--space-1)}
#doc-links button[aria-current=page] .doc-link-count{color:var(--muted-foreground)}   /* label-colored text measured 2.8 contrast in dark (QA) - the current document's underline bar already carries the label color */
#doc-select-wrap label{color:var(--muted-foreground);font-size:var(--text-sm)}
#doc-select{max-width:230px;min-width:120px;background:var(--sidebar);border:0;font-weight:600;padding:4px 20px 4px 2px}
#view-switch{padding-left:0}
body.docs-multi #view-switch{border-left:1px solid var(--border);padding-left:var(--space-3)}
#view-switch{display:inline-flex;align-items:stretch;gap:var(--space-4);height:100%;flex:none}
#view-switch button{position:relative;border:0;border-radius:0;background:transparent;color:var(--muted-foreground);padding:0 2px;font-size:var(--text-sm)}
#view-switch button[aria-pressed=true]{color:var(--foreground);font-weight:600}
#view-switch button[aria-pressed=true]::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:var(--brand)}
#outline{display:block;flex:none;width:var(--outline-width);min-width:var(--outline-width);overflow:auto;padding:var(--space-3) var(--space-2);
  background:var(--sidebar);font-size:var(--text-sm)}
body.outline-collapsed #outline{display:none}
body.outline-collapsed #outline-items,body.outline-collapsed #outline-search,body.outline-collapsed .outline-title{display:none}
.outline-head{display:flex;align-items:center;min-height:32px;gap:var(--space-2);padding:0 var(--space-2) var(--space-2)}
#outline .outline-title{font-weight:600}
#nav-toc-toggle{display:inline-flex;flex:none;align-self:center;width:32px;height:32px;padding:0;color:var(--muted-foreground)}
#nav-toc-toggle[aria-expanded=true]{background:var(--accent);color:var(--foreground)}
#outline-search{width:100%;margin-bottom:var(--space-2);background:var(--field);font-size:var(--text-sm)}
#outline .outline-empty{color:var(--muted-foreground);padding:var(--space-2)}
#outline-items button{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:var(--space-1);width:100%;text-align:left;
  background:transparent;border:0;color:var(--muted-foreground);padding:var(--space-2) var(--space-1);font-size:var(--text-sm)}
#outline-items button .ol-name{overflow-wrap:anywhere}
#outline-items button.ol-depth-0 .ol-name,#outline-items button.ol-depth-0 .ol-no{font-weight:600;color:var(--foreground)}
#outline-items button .ol-page{color:var(--subtle-foreground);white-space:nowrap;font-size:var(--text-xs)}
#outline-items button.ol-depth-1{padding-left:var(--space-4)}
#outline-items button.ol-depth-2{padding-left:var(--space-5)}
#outline-items button.ol-depth-3,#outline-items button.ol-depth-4{padding-left:var(--space-6)}
#outline-items button.ol-active{background:var(--accent);color:var(--foreground)}
#outline-items button:hover,#outline-items button:focus-visible{background:var(--accent);color:var(--foreground)}
#outline-items button:is(.ol-active,:hover,:focus-visible) .ol-page{color:var(--muted-foreground)}   /* the faint page number measured 3.8 contrast on --accent here (QA) */
#outline-grip{position:relative;z-index:6;width:6px;flex:none;cursor:col-resize;touch-action:none;background:var(--border)}
#outline-grip::after{content:'';position:absolute;inset:0 -9px}
#outline-grip:hover,#outline-grip.on,#outline-grip:focus-visible{background:var(--border-strong)}
body.outline-collapsed #outline-grip,body.lay-narrow #outline,body.lay-narrow #outline-grip{display:none}
#section-strip{display:flex;align-items:center;gap:var(--space-2);height:38px;flex:none;padding:0 var(--space-4);background:var(--muted);
  border-bottom:1px solid var(--border);font-size:var(--text-sm);color:var(--muted-foreground)}
#section-current{color:var(--foreground);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#section-page{margin-left:auto;white-space:nowrap}
body.revision-open #section-strip{display:none}
body.lay-narrow #section-strip{display:none}
#revision-view{display:none;flex:1;min-width:0;min-height:0;overflow:hidden;background:var(--background)}
body.revision-open #revision-view{display:block}
body.revision-open #left{display:none}
/* The pin [변경 보기] points at (docs/handbook/viewer.md §변경 보기): a one-line notice below the header plus highlighting of the pin's range lines. The narrow (folded)
   layout has no nav bar, so this notice's [원고로] is the way back. */
#revision-pin{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-1) var(--space-2);padding:var(--space-2) var(--space-4);background:var(--card);
  border-bottom:1px solid var(--border);font-size:var(--text-sm)}
#revision-pin .rp-msg{color:var(--muted-foreground);min-width:0;flex:1 1 12em;overflow-wrap:anywhere}
#revision-pin>span:first-child{min-width:0;overflow-wrap:anywhere}
#revision-pin button{flex:none;margin-left:auto}   /* if the text is long it wraps - the button is never clipped (QA: at 842px, [원고로] was going off-screen) */
#revision-diff .rd-pin{background:color-mix(in srgb,var(--status-review) 12%,var(--sidebar))}
body.lay-narrow #revision-head{padding:var(--space-2) var(--space-3)}
body.lay-narrow #revision-head h2{display:none}
body.lay-narrow #revision-view{height:100%}
body.lay-narrow #revision-source,body.lay-narrow #revision-pdf{padding-bottom:84px}   /* the folded sheet's tool bar covers the bottom */
#revision-inner{height:100%;display:flex;flex-direction:column;min-height:0}
#revision-head{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-2) var(--space-4);background:var(--sidebar);border-bottom:1px solid var(--border)}
#revision-head h2{font-size:var(--text-sm);margin:0;white-space:nowrap}
#revision-list{min-width:0;flex:1}
#revision-list select{width:100%;max-width:470px;min-width:0;background:var(--sidebar);font-size:var(--text-sm)}
#revision-note{color:var(--muted-foreground);font-size:var(--text-xs);padding:4px var(--space-4);background:var(--sidebar)}
#revision-file-row{display:flex;align-items:center;gap:var(--space-2);margin-bottom:var(--space-2);font-size:var(--text-sm)}
#revision-file-row select{max-width:min(100%,500px);background:var(--sidebar)}
#revision-other,#revision-diff{white-space:pre;max-height:none;overflow:auto;margin:0;padding:0;background:var(--sidebar);font-size:var(--text-sm);line-height:1.7}
#revision-other .rd-line,#revision-diff .rd-line{display:block;width:max-content;min-width:100%;min-height:1.7em}
#revision-other .rd-no,#revision-diff .rd-no{display:inline-block;width:54px;padding:0 var(--space-2);margin-right:var(--space-2);
  text-align:right;color:var(--subtle-foreground);border-right:1px solid var(--border);user-select:none}
#revision-other .rd-code,#revision-diff .rd-code{white-space:pre;padding-right:var(--space-3)}
#revision-other.wrap .rd-line,#revision-diff.wrap .rd-line{display:flex;width:auto}
#revision-other.wrap .rd-no,#revision-diff.wrap .rd-no{flex:none}
#revision-other.wrap .rd-code,#revision-diff.wrap .rd-code{flex:1;min-width:0;white-space:pre-wrap;overflow-wrap:anywhere}
#revision-other .rd-file,#revision-diff .rd-file{background:var(--muted);font-weight:600}
#revision-other .rd-meta,#revision-diff .rd-meta{color:var(--muted-foreground)}
#revision-other .rd-hunk,#revision-diff .rd-hunk{background:color-mix(in srgb,var(--primary) 8%,var(--sidebar));color:var(--primary)}
#revision-other .rd-add,#revision-diff .rd-add{background:color-mix(in srgb,var(--success) 9%,var(--sidebar));
  color:color-mix(in srgb,var(--success) 75%,var(--foreground))}
#revision-other .rd-del,#revision-diff .rd-del{background:color-mix(in srgb,var(--destructive) 8%,var(--sidebar));
  color:color-mix(in srgb,var(--destructive) 75%,var(--foreground))}
#revision-controls{display:flex;align-items:center;gap:var(--space-2);flex-wrap:wrap;padding:var(--space-1) var(--space-4);background:var(--sidebar);border-bottom:1px solid var(--border)}
#revision-controls button[aria-pressed=true]{background:var(--accent);color:var(--foreground)}
#revision-status{font-size:var(--text-xs);color:var(--muted-foreground);padding:4px var(--space-4);background:var(--sidebar)}
#revision-warning{font-size:var(--text-xs);color:var(--warning);padding:0 var(--space-4);background:var(--sidebar)}
#revision-warning summary{cursor:pointer}
#revision-warning pre{white-space:pre-wrap;max-height:8em;overflow:auto;margin:4px 0}
#revision-pdf{flex:1;min-height:0;overflow:auto;background:var(--background);padding:var(--space-3);text-align:center}
#revision-source{flex:1;min-height:0;overflow:auto}
/* v0.3: the pin's own hunks come first; the rest of the commit folds under one control and expands inline below them */
#revision-other-toggle{display:flex;align-items:center;gap:var(--space-1);width:100%;justify-content:flex-start;border-radius:0;
  border-top:1px solid var(--border);color:var(--muted-foreground);font-size:var(--text-sm)}
#revision-other-toggle[aria-expanded=true] .ic{transform:rotate(90deg)}
#revision-other{border-top:1px solid var(--border)}
.revision-page{width:min(100%,780px);min-height:500px;margin:0 auto var(--space-4);background:var(--sidebar);box-shadow:var(--shadow-page)}
.revision-page canvas{display:block;max-width:100%;margin:auto}
/* Panel width grip (shared by wide/mid, Pointer Events): the visible bar is 6px; the grab area is widened via
   ::after (24px for touch). For mouse, only 3px on each side is added, so it doesn't cover the body scrollbar on the left. */
#grip{position:relative;z-index:6;width:6px;cursor:col-resize;background:var(--border);flex:none;touch-action:none}
#grip::after{content:'';position:absolute;top:0;bottom:0;left:-3px;right:-3px}
#grip:hover,#grip.on,#grip:focus-visible{background:var(--border-strong)}
body.resizing{-webkit-user-select:none;user-select:none;cursor:col-resize}
body.resizing #left{pointer-events:none}
#sheet-grip{display:none}
#right{width:348px;min-width:280px;max-width:80vw;border-left:1px solid var(--border);background:var(--sidebar);
  display:flex;flex-direction:column;flex:none;min-height:0}
.bar{padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border);display:flex;gap:var(--space-1);align-items:center;flex-wrap:wrap}
#bar1{flex-wrap:wrap;gap:var(--space-1);padding:var(--space-2);--tb-h:var(--control-h)}   /* wraps to two lines in a narrowed panel - so it never overflows horizontally */
/* The tool bar is a single height (--tb-h: 28px desktop, 44px touch). The page field is also the same height/text size as the buttons - taking the
   generic input field rule (14px, 6px padding) as-is made it 8px taller than the buttons with larger text, breaking the row's harmony (author feedback 2026-09-23). Icon buttons are square. */
#bar1>button,#bar1>input{height:var(--tb-h)}
#bar1 button{padding:0 var(--space-2);white-space:nowrap}
#bar1 button.btn-icon{padding:0;width:var(--tb-h);min-width:var(--tb-h)}
#bar1 input.n{width:54px;flex:100 1 40px;min-width:40px;max-width:54px;padding:0 var(--space-1);font-size:var(--text-base);line-height:normal;border-radius:var(--radius);text-align:left}   /* the single-character '쪽' field read like a button (QA) - left-aligned like a proper input field for '쪽 이동'. Its basis is 40px and it takes the free space first (grow 100, up to 54px) so the longer English labels still fit the 348px panel on one row - a wrapping flex line breaks on the basis, not the shrunk size */
/* Tool bar hierarchy (QA 2026-09-24): page/zoom-in/zoom-out/fit-width are bordered navigation controls, notification/theme/help
   are borderless utility icons, and [PDF 재빌드] is a rarely used action so it's a faint ghost - if the manuscript is newer than the PDF, updateStaleBadge promotes it to .btn-default. */
#bar1 :is(#btn-notify,#btn-theme,#btn-help){background:transparent;border-color:transparent;color:var(--muted-foreground)}
#bar1 :is(#btn-notify,#btn-theme,#btn-help):hover{background:var(--accent);color:var(--foreground)}
#btn-rebuild:not(.btn-default){background:transparent;border-color:transparent;color:var(--muted-foreground)}
body.lay-wide #btn-rebuild .ic{display:none}   /* text only on a wide screen - so the 348px panel's tool bar fits on one line */
body.lay-wide #bar1 #btn-rebuild{padding:0 var(--space-1)}   /* at 8px, [?] dropped to a second line in the default 348px panel (grid-cleanup QA) */
#btn-rebuild:not(.btn-default):hover{background:var(--accent);color:var(--foreground)}
#bar1 .chip{height:var(--control-h-sm);display:block;line-height:var(--control-h-sm);padding:0 var(--space-2);flex:0 1 auto;min-width:40px}
/* ---------------- Components (docs/handbook/viewer.md §컴포넌트). Classes borrowing shadcn/ui's variant names - every button/badge uses this one set.
   Button variants: (no class) = outline - .btn-default (primary action, one per panel) - .btn-secondary - .btn-soft ([완료]) - .btn-ghost - .btn-destructive
   Button sizes: (no class) = default (28px) - .btn-sm (around 24px) - .btn-icon (square, a smaller square when combined with .btn-sm)
   Badges: .badge (= outline) - .badge-default - .badge-secondary - .badge-destructive - status .badge-claimed - .badge-warning */
button{display:inline-flex;align-items:center;justify-content:center;gap:var(--space-1);
  background:var(--outline-bg);color:var(--foreground);border:1px solid var(--input);border-radius:var(--radius);
  padding:var(--space-1) var(--space-3);cursor:pointer;font:inherit;font-size:var(--text-base);line-height:1.4;
  transition:background-color .12s,border-color .12s,color .12s}
/* Icons (Lucide, vendor/lucide/README.md): outline icons that follow the text color. Inside a button they sit next to the text with a 4px gap. */
.ic{width:16px;height:16px;flex:none;display:inline-block;vertical-align:-3px;pointer-events:none}
.kh{font-weight:400;opacity:.8;font-size:var(--text-sm)}
button:hover{background:var(--accent);color:var(--accent-foreground)}
button:disabled{opacity:.65;cursor:not-allowed}
button[data-pending]{cursor:progress;background:color-mix(in srgb,var(--primary) 70%,var(--background));border-color:transparent}   /* [핀 저장]'s "saving" - looks pressed-and-waiting */
button.btn-default{background:var(--primary);color:var(--primary-foreground);border-color:var(--primary);font-weight:600}
button.btn-default:hover{background:color-mix(in srgb,var(--primary) 88%,var(--background));color:var(--primary-foreground)}
button.btn-secondary{background:var(--secondary);color:var(--secondary-foreground);border-color:transparent}
button.btn-secondary:hover{background:color-mix(in srgb,var(--secondary) 88%,var(--foreground))}
button.btn-ghost{background:transparent;border-color:transparent}
button.btn-ghost:hover{background:var(--accent)}
/* soft: a light accent (a tint of the primary color). Only for the card's [완료] - set by the author 2026-09-23 (light blue). The secondary token is used by count badges, so it's left untouched */
button.btn-soft{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--primary);border-color:transparent}
button.btn-soft:hover{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--primary);border-color:color-mix(in srgb,var(--primary) 45%,transparent)}   /* darkening the background further drops light-mode text contrast below 4.5 - shown via a border instead */
button.btn-destructive{background:color-mix(in srgb,var(--destructive) 10%,transparent);color:var(--destructive);border-color:transparent}
button.btn-destructive:hover{background:color-mix(in srgb,var(--destructive) 18%,transparent);color:var(--destructive)}
button.btn-sm{padding:2px var(--space-2);font-size:var(--text-sm)}
button.btn-icon{flex:none;padding:0;width:var(--control-h);min-width:var(--control-h);height:var(--control-h)}
button.btn-icon.btn-sm{width:var(--control-h-sm);min-width:var(--control-h-sm);height:var(--control-h-sm)}
:focus-visible{outline:2px solid var(--ring);outline-offset:1px}
.badge{display:inline-flex;align-items:center;gap:var(--space-1);padding:1px var(--space-2);border:1px solid transparent;border-radius:var(--radius-sm);
  background:var(--muted);color:var(--muted-foreground);font-size:var(--text-xs);font-weight:500;line-height:1.45;white-space:nowrap}
/* A badge is a borderless light fill (the shadcn secondary badge) - a bordered badge is never drawn inside a bordered card
   (author feedback 2026-09-24: an outline inside an outline). A meaningful badge is that color's light tint background + text in that color. */
.badge .ic{width:12px;height:12px}
.badge-default{background:var(--primary);color:var(--primary-foreground)}
.badge-secondary{background:var(--secondary);border-color:transparent;color:var(--secondary-foreground)}
.badge-destructive{background:color-mix(in srgb,var(--destructive) 14%,transparent);color:var(--destructive)}
.badge-warning{background:color-mix(in srgb,var(--status-warning) 14%,transparent);color:var(--status-warning)}
.badge-claimed{background:color-mix(in srgb,var(--status-claimed) 16%,transparent);color:var(--foreground)}
.badge-claimed .ic{color:var(--status-claimed)}
.badge-claimed.late{background:color-mix(in srgb,var(--status-warning) 14%,transparent);color:var(--status-warning)}
.badge-claimed.late .ic{color:var(--status-warning)}
button.badge{cursor:pointer;padding:1px var(--space-2);border-radius:var(--radius-sm);font-size:var(--text-xs);line-height:1.45}
button.badge:hover{background:var(--accent);border-color:var(--border-strong)}
.card{background:var(--card);color:var(--card-foreground);border:1px solid var(--border);border-radius:var(--radius-lg)}
input,textarea{background:var(--field);color:var(--foreground);border:1px solid var(--input);border-radius:var(--radius);padding:var(--space-2);
  font:inherit;width:100%}
input::placeholder,textarea::placeholder{color:var(--muted-foreground)}
textarea{resize:vertical;min-height:4.8em}
input.n{width:58px;text-align:center}
.sp{flex:1}
.pg{position:relative;margin:0 auto var(--space-4);box-shadow:var(--shadow-page);user-select:none}
:root[data-theme=light] .pg{border:1px solid var(--border)}
.pg img{width:100%;height:100%;display:block}
/* Vector rendering (docs/handbook/viewer.md §벡터 렌더링): the page canvas (.vb) fills the page box completely, and when zoom
   exceeds the pixel ceiling, a detail canvas (.dt) rendered at native resolution for just the visible portion is overlaid at % coordinates within the page. The underlying PNG is hidden whenever a canvas is present. */
.pg>canvas{position:absolute;display:block;pointer-events:none}
.pg>canvas.vb{left:0;top:0;width:100%;height:100%}
.pg.drawn>img{visibility:hidden}
.pg .no{position:absolute;top:var(--space-2);left:var(--space-2);color:var(--muted-foreground);font-size:var(--text-xs);background:var(--card);
  padding:1px var(--space-2);border-radius:var(--radius-sm);box-shadow:var(--shadow-sm);line-height:1.5}
.sel{position:absolute;border:2px solid var(--primary);background:color-mix(in srgb,var(--primary) 13%,transparent);pointer-events:none}
.sel.pending{border-style:dashed}
.sel i{position:absolute;top:-21px;left:-2px;background:var(--primary);color:var(--primary-foreground);font-size:var(--text-xs);font-style:normal;
  padding:1px var(--space-2);border-radius:var(--radius-sm);white-space:nowrap}
.mark{position:absolute;border:2px solid var(--status-open);background:color-mix(in srgb,var(--status-open) 8%,transparent);pointer-events:none}
.mark.st{border-color:var(--warning);background:color-mix(in srgb,var(--status-warning) 8%,transparent)}
.mark.est{border-style:dashed}
.mark.hi{border-width:3px}
.mark b{position:absolute;top:-2px;left:-24px;background:var(--status-open);color:var(--status-open-foreground);border-radius:50%;
  width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:var(--text-sm);pointer-events:auto;cursor:pointer}
.mark.st b{background:var(--warning);color:var(--warning-foreground)}
.mark.rv{border-color:var(--status-review);background:color-mix(in srgb,var(--status-review) 8%,transparent)}
.mark.rv b{background:var(--status-review);color:var(--status-review-foreground)}
.mark.flash{animation:flash .6s ease-in-out 3}
@keyframes flash{50%{box-shadow:0 0 0 5px var(--primary)}}
#banner{padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border);background:var(--card);display:flex;gap:var(--space-2);flex-wrap:wrap;
  align-items:center;font-size:var(--text-base)}
#build-err{padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border);background:var(--card);font-size:var(--text-base)}
#composer{flex:none;max-height:62vh;overflow:auto;padding:var(--space-3);border-bottom:1px solid var(--border);background:var(--card)}
#list{flex:1;overflow:auto;padding:0 var(--space-3) 32px;min-height:0}   /* the top padding belongs to the section header (.sec-head) - so a sticky element doesn't sit that far down */
.busy{opacity:.45}
pre{background:var(--code);border:0;border-radius:var(--radius);padding:var(--space-2);overflow:auto;font-size:var(--text-sm);
  line-height:1.5;max-height:44vh;font-family:var(--font-mono);tab-size:2;margin:var(--space-2) 0}
pre.wrap{white-space:pre-wrap;word-break:break-word}
pre.nowrap{white-space:pre}
/* ---------------- Composer panel (docs/handbook/viewer.md §패널 정리): an 8px grid, uniform heights, only [핀 저장] gets the accent color (--acc).
   The location line (file/line + page + match badge + copy) -> range-segment control -> line-by-line stepper -> 4 lines of source -> note -> a fixed action row at the bottom. */
.c-loc-row{display:flex;align-items:center;gap:var(--space-2)}
.c-loc-main{flex:1;min-width:0;display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-1) var(--space-2)}
.c-loc-main .loc{font-weight:600}
#c-page{color:var(--muted-foreground);font-size:var(--text-sm)}
.c-tools{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2);margin:0 0 8px}
.step{display:inline-flex;flex:none;border:0;border-radius:var(--radius-lg);overflow:hidden;background:var(--muted);padding:2px;gap:2px}
.step{align-items:stretch}
.step button{border:0;border-radius:var(--radius);min-width:30px;padding:var(--space-1);background:transparent}
.step button:hover{background:var(--popover)}
.step .sl{display:inline-flex;align-items:center;padding:0 var(--space-2);font-size:var(--text-sm);color:var(--muted-foreground)}
button.tg[aria-pressed=false]{color:var(--muted-foreground)}
button.tg[aria-pressed=true]{border-color:var(--border-strong)}
#c-snip,.e-snip{margin:0}
#c-snip:not(.open){max-height:calc(6em + 16px);overflow:hidden}   /* the collapsed source is 4 lines - overflow fades out with a [펼치기] */
#c-snip.clip:not(.open){-webkit-mask-image:linear-gradient(var(--foreground) 60%,transparent);mask-image:linear-gradient(var(--foreground) 60%,transparent)}
#c-snip.open{max-height:44vh}
.e-snip{max-height:calc(9em + 16px)}
/* One line right below the source: [줄바꿈] on the left, [원문 펼치기] on the right. [줄바꿈] used to sit at the end of the
   stepper row and dropped alone to the next line in the folded (330px panel) layout (QA 2026-09-25) - since both change how the source is displayed, they're grouped below the source instead. */
.snip-foot{display:flex;align-items:center;justify-content:space-between;gap:var(--space-2)}
.snip-foot button{color:var(--muted-foreground);white-space:nowrap}
.snip-foot button.tg[aria-pressed=true]{color:var(--foreground);background:var(--accent);border-color:transparent}   /* on = the same filled state as the diff's [줄바꿈] */
#note{margin-top:8px}
#c-overlap{display:flex;flex-wrap:wrap;gap:var(--space-2);margin:8px 0;font-size:var(--text-base)}   /* no box, just text + two buttons */
#c-overlap>span{flex-basis:100%}
#c-overlap button{flex:1 1 0;min-width:0}
/* The action row is fixed to the bottom of the panel (visible while scrolling the list, or with the virtual keyboard up). It hides along with the composer panel closing. */
#c-actions{flex:none;display:grid;grid-template-columns:1fr 2fr;gap:var(--space-2);padding:var(--space-2) var(--space-3);border-top:1px solid var(--border);background:var(--sidebar);z-index:3}
#composer[hidden]~#c-actions{display:none}
#c-actions button{min-height:var(--control-h-lg);font-size:var(--text-base)}
#composer:not([hidden])~#list #empty{display:none}   /* the first-screen guidance paragraph is hidden while selecting */
.loc{font-family:var(--font-mono);color:var(--primary);font-size:var(--text-base);cursor:copy;overflow-wrap:anywhere}
.dim{color:var(--muted-foreground);font-size:var(--text-sm)}
.row{display:flex;align-items:center;gap:var(--space-2);flex-wrap:wrap}
/* Segment control (range ladder / panel width): a single row, horizontal scroll on overflow. The selected segment shows not as the accent color but as a step-brighter surface. */
.seg{position:relative;display:flex;flex-wrap:nowrap;overflow-x:auto;gap:2px;margin:8px 0;padding:var(--space-1);border:0;
  border-radius:var(--radius-lg);background:var(--muted);scrollbar-width:none;overscroll-behavior-x:contain}   /* shadcn Tabs: one filled frame, the selected segment is a raised surface */
.seg::-webkit-scrollbar{display:none}
.seg.fade-r{mask-image:linear-gradient(to right,var(--foreground) calc(100% - 32px),transparent)}
.seg.fade-l{mask-image:linear-gradient(to left,var(--foreground) calc(100% - 32px),transparent)}
.seg.fade-l.fade-r{mask-image:linear-gradient(to right,transparent,var(--foreground) 32px,var(--foreground) calc(100% - 32px),transparent)}
.seg button{flex:1 0 auto;background:transparent;border-color:transparent;border-radius:var(--radius);font-size:var(--text-sm);padding:var(--space-1) var(--space-3);
  white-space:nowrap;color:var(--muted-foreground)}
.seg button.on{background:var(--popover);border-color:transparent;color:var(--foreground);font-weight:600;box-shadow:var(--shadow-sm)}
.seg button .k{font-weight:400;color:var(--muted-foreground)}
.seg button .k.wn{color:var(--warning)}
.wn{color:var(--warning)}
.warnline{color:var(--warning);font-size:var(--text-sm);margin-top:var(--space-2)}
.errline{color:var(--destructive);font-size:var(--text-base);margin-top:var(--space-2)}
.pin{position:relative;padding:var(--space-2) var(--space-3);margin-bottom:8px}   /* shape follows .card */
/* Status (docs/handbook/viewer.md §상태 표현): the left-edge color stripe was removed (author feedback 2026-09-24 - looked dated). Distinguished by the small
   dot color at the front of the card header plus a matching badge (text/icon) - never by color alone. Open is green, in-progress is amber, awaiting review is purple, location lost is the warning color.
   Closed/dropped aren't a card at all but a faded archive row, where a leading icon (check/trash-2) is the status. */
.st-dot{flex:none;width:8px;height:8px;border-radius:50%;background:var(--status-open)}
.st-dot.claimed{background:var(--status-claimed)}
.st-dot.review{background:var(--status-review)}
.st-dot.lost{background:var(--status-warning)}
.st-dot.done{background:var(--status-closed)}
.st-dot.dropped{background:var(--status-dropped)}
.badge-reopen{background:color-mix(in srgb,var(--status-warning) 14%,transparent);color:var(--status-warning)}
.badge-review{background:color-mix(in srgb,var(--status-review) 14%,transparent);color:var(--status-review)}
button.badge-review{font-weight:600}
.rv-n{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;padding:0 var(--space-1);margin-left:2px;border-radius:var(--radius-lg);
  background:var(--status-review);color:var(--status-review-foreground);font-size:var(--text-xs);font-weight:700;line-height:1}
.rv-close{margin-top:4px;color:var(--muted-foreground);font-size:var(--text-sm)}
.rv-close b{color:var(--card-foreground);font-weight:600}
.pin.st{border-color:var(--warning)}
.pin.editing{border-color:var(--primary)}
.pin.cur{box-shadow:0 0 0 2px var(--primary)}
.pin.flash{animation:pinflash 1.2s ease-in-out 1}
@keyframes pinflash{0%,100%{box-shadow:0 0 0 2px var(--primary)}50%{box-shadow:0 0 0 5px var(--primary)}}
.pin .n{color:var(--card-foreground);font-weight:700}
.pin .n.go{cursor:pointer;color:var(--primary);border-radius:var(--radius);padding:0 var(--space-1);margin:0 -4px}
/* One unified link style (QA 2026-09-24): the card header's #number/line-range/N페이지 and a #12 inside a post are all "a reference
   that navigates or copies on click" - there used to be three distinct looks: bold dotted underline, blue, gray dotted underline. Now one:
   primary-color text, no underline at rest, solid underline on hover/focus. Gray text is non-clickable information (author/timestamp).
   Same inside a faded archive row - the row's text is faded and only the clickable words are in the primary color. */
:is(.loc,.pg-link,.pin .n.go,.pin-ref){text-decoration:none;text-underline-offset:3px}
:is(.loc,.pg-link,.pin .n.go,.pin-ref):is(:hover,:focus-visible){text-decoration:underline}
.pin .note{margin-top:4px;white-space:pre-wrap;word-break:break-word;cursor:text}
/* Card header: number/range/page on the left, author/collapse on the right. Badges are a single row below the header. Actions form an equal-width grid; only [완료] is emphasized and [삭제] is in the destructive color. */
.pin .head{flex-wrap:wrap;gap:var(--space-1) var(--space-2);min-height:28px}
.pin .head .loc{white-space:nowrap}
.pin .head .pg-link{white-space:nowrap;flex:none}
/* Header right-side group (.h-meta = assignee chip - reply count - author): when space runs out, the whole
   group drops to the next line, right-aligned. It used to be crammed onto one line, so an assignee chip could truncate the author's name down to a single
   letter 'W' (QA 2026-09-24). Within the group, the assignee chip's name truncates first, then the author's name. compact (a collapsed card) keeps a single
   line (author shown as just an avatar) and shrinks in the same order. */
.pin .head .h-meta{display:inline-flex;align-items:center;gap:var(--space-2);margin-left:auto;min-width:0;max-width:100%}
.h-meta .au{flex:0 1 auto;min-width:0;max-width:14em}
.h-meta .badge-assign{flex:0 100 auto;min-width:4.5em}
.pin .tags{display:flex;flex-wrap:wrap;gap:var(--space-1);margin-top:4px}
.pin .tags:empty{display:none}
.pin .acts{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:var(--space-2);margin-top:8px}
.pin .acts button{min-width:0;padding-left:var(--space-1);padding-right:var(--space-1)}
button.b-close{font-weight:600}
/* Buttons inside a card are borderless and filled (secondary) - so six bordered buttons never line up inside an already-bordered card.
   Only [완료] gets the soft emphasis; [삭제] is plain destructive-colored text with no fill, so it never becomes the most eye-catching button. [취소] next to an input field uses the same fill. */
.pin :is(.acts,.e-acts,.r-acts) button:not(.btn-soft):not(.btn-destructive):not(.btn-default){background:var(--secondary);color:var(--secondary-foreground);border-color:transparent}
.pin :is(.acts,.e-acts,.r-acts) button:not(.btn-soft):not(.btn-destructive):not(.btn-default):hover{background:var(--accent)}
.pin .acts button.btn-destructive{background:transparent}
.pin .acts button.btn-destructive:hover{background:color-mix(in srgb,var(--destructive) 12%,transparent)}   /* [완료] = soft, [삭제] = destructive - the variant is set by the class in the markup */
.e-acts{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:var(--space-2);margin-top:8px}
/* Pin kind (fix request / question) and thread (docs/handbook/viewer.md §스레드와 검토). The question badge has a primary-color border; the thread is set apart by a dotted line below the note. */
.kind-seg{margin:8px 0 0}
.kind-seg button{flex:1 1 0}
.edit .kind-seg{margin:0 0 var(--space-2)}
.badge-question{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--primary)}
.badge-mention{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--foreground)}
.badge-mention .ic{color:var(--primary)}
.mention{color:var(--primary);font-weight:600;background:color-mix(in srgb,var(--primary) 12%,transparent);border-radius:var(--radius-sm);padding:0 var(--space-1);
  white-space:nowrap}   /* so a name never splits across a line break into two pills, '@Bob' / 'Lee' */
/* A resolved @-tag = primary-color text + a light-tint pill (like Slack/GitHub). A tag that mentions me is one shade darker. An unresolved '@word' is plain text. */
.mention.me{background:color-mix(in srgb,var(--primary) 28%,transparent);color:var(--foreground)}
.badge-assign{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--foreground);font-weight:600;flex:0 0 auto;max-width:12em;overflow:hidden;justify-content:flex-start}
.badge-assign .as-n{min-width:0;overflow:hidden;text-overflow:ellipsis}
.badge-assign.me{background:color-mix(in srgb,var(--primary) 28%,transparent)}
.assign-row{display:flex;align-items:center;gap:var(--space-2);margin-top:var(--space-2)}
.assign-row .as-lab{flex:none;color:var(--muted-foreground);font-size:var(--text-sm)}
.assign-row .as-seg{flex:1;min-width:0;margin:0}
body.lay-narrow #c-assign{order:1;margin:0 0 8px}
.mention-bad{color:var(--muted-foreground);text-decoration:underline dotted;text-underline-offset:3px}
.m-preview{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-1) var(--space-2);margin-top:var(--space-2);font-size:var(--text-sm)}
.m-preview .m-lab{display:inline-flex;align-items:center;gap:2px;color:var(--muted-foreground)}
.m-preview .m-lab .ic{width:12px;height:12px}
.m-preview .m-note{color:var(--muted-foreground)}
body.lay-narrow #note-mentions{order:1;margin:-4px 0 8px}
/* Question-suggestion line (.q-hint): faded text + a link-style button. No box (single nesting level). Sits below the note field, so the field never shifts while typing. */
.q-hint{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-1);margin-top:var(--space-1);font-size:var(--text-sm);color:var(--muted-foreground)}
.q-hint svg{width:14px;height:14px;flex:none}
.q-hint button{background:transparent;border-color:transparent;color:var(--primary);padding:0 var(--space-1);font-size:var(--text-sm);text-underline-offset:3px}
.q-hint button:is(:hover,:focus-visible){background:transparent;color:var(--primary);text-decoration:underline}
body.lay-narrow #c-qhint{order:1;margin:-4px 0 8px}
/* A '#12' inside text = a link to that pin (a navigable string is dotted-underline, solid on hover - the same convention as .pg-link/#number) */
.pin-ref{color:var(--primary);font-weight:600;cursor:pointer}
/* '#12' pointing at a deleted pin (in the Trash): faded, struck number + 'deleted pin' - clicking opens the Trash at that row */
.pin-ref.gone{color:var(--muted-foreground);font-weight:400}
.pin-ref.gone small{font-size:var(--text-xs)}
/* Trash (docs/handbook/viewer.md §휴지통): a dialog from [⋯] (compact) or the link under the list (desktop). Rows are the flat archive rows. */
#trash{width:min(560px,calc(100vw - 16px))}
#trash .trash-note{margin:var(--space-2) 0 0;font-size:var(--text-sm)}
#trash .arc-list{max-height:min(60vh,520px);overflow:auto}
.trash-left{color:var(--subtle-foreground)}
#trash .arc-l1{flex-wrap:wrap;white-space:normal;row-gap:var(--space-1)}   /* [되살리기] [영구 삭제] drop to their own line on a phone instead of being cut off */
#trash .arc-l1 .sp{flex:1 0 0}
.arc-acts{flex:none;display:inline-flex;gap:var(--space-1);margin-left:auto}
#trash-link{display:flex;margin:12px auto 0;color:var(--muted-foreground);background:transparent;border-color:transparent}
#trash-link:hover{background:var(--accent);color:var(--foreground)}
body.compact #trash-link{display:none}   /* compact: the Trash is in [⋯], like the other secondary lists */
.arc-row.flash{animation:pinflash 1.2s ease-in-out 1;border-radius:var(--radius)}
/* @-tag autocomplete: a list that appears right below the input field (above it if there's no room). Never steals the input field's focus (blocks pointerdown). */
#mention-pop{position:fixed;z-index:90;min-width:200px;max-width:min(360px,calc(100vw - 16px));padding:var(--space-1) 0;overflow:hidden;background:var(--popover);
  color:var(--popover-foreground);border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:var(--shadow-lg)}
#mention-pop button{display:flex;width:100%;justify-content:flex-start;gap:var(--space-2);border:0;border-radius:0;background:transparent;text-align:left;padding:var(--space-2) var(--space-3)}   /* a selected row = a full-width flat band (shadcn Command) - never a rounded box within a box (single nesting level) */
#mention-pop button[aria-selected=true]{background:var(--accent)}
#mention-pop .ml{color:var(--muted-foreground);font-size:var(--text-sm);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#mention-pop .dim{padding:var(--space-2) var(--space-3)}
.thread{display:flex;flex-direction:column;gap:var(--space-2);margin-top:var(--space-2);padding-top:var(--space-2);border-top:1px solid var(--border)}   /* a single divider - not a box */
.thread:empty{display:none}
.msg{display:flex;align-items:flex-start;gap:var(--space-2);font-size:var(--text-base);line-height:1.5}
.msg .av{width:20px;height:20px;margin-top:1px}
.msg-b{flex:1;min-width:0}
.msg-h{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 var(--space-2);color:var(--muted-foreground);font-size:var(--text-sm)}
.msg-h b{color:var(--foreground);font-weight:600}
.msg-t{white-space:pre-wrap;word-break:break-word}
.msg-t.clamp{display:-webkit-box;-webkit-line-clamp:6;-webkit-box-orient:vertical;overflow:hidden}   /* a single 1,000-character reply stretched a card to 1,390px (QA) */
button.msg-more{align-self:flex-start;margin-top:2px;color:var(--muted-foreground)}
.thread :is(button.msg-more,button.th-more){justify-content:flex-start;padding-left:var(--space-1);padding-right:var(--space-1);margin-left:calc(-1 * var(--space-1))}   /* the text aligns with the thread posts' left edge */
.msg.ev{display:block;padding-left:28px;color:var(--muted-foreground);font-size:var(--text-sm)}
.msg.ev .msg-t{color:var(--card-foreground);font-size:var(--text-base)}
button.th-more{align-self:flex-start;color:var(--muted-foreground)}
.th-n{display:inline-flex;align-items:center;gap:2px;flex:none;color:var(--muted-foreground);font-size:var(--text-xs);cursor:pointer;border-radius:var(--radius);padding:0 2px;position:relative}
.th-n:hover{background:var(--accent);color:var(--foreground)}
.th-n .ic{width:12px;height:12px}
.reply-box{display:flex;flex-direction:column;gap:var(--space-2);margin-top:8px}
.reply-box textarea{min-height:3.2em}
.r-acts{display:grid;grid-template-columns:1fr 2fr;gap:var(--space-2)}
.pin:has(.reply-box)>.acts{display:none}   /* while the input field is open, its own [취소]/[보내기] act as this card's action row - otherwise the two rows overlapped */
/* The reply outcome line (docs/handbook/viewer.md §스레드와 검토): on a closed pin, one line under the box says what sending will do -
   reopen for the agent, notify the tagged person, or keep the state - with the rarely used [상태 유지] toggle beside it. */
.r-outcome{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-1) var(--space-2);font-size:var(--text-sm);color:var(--muted-foreground)}
.r-outcome .ic{width:14px;height:14px;flex:none}
.r-outcome.reopen{color:var(--status-review)}
.r-outcome .r-out-t{flex:1 1 12em;min-width:0}
/* The override is a switch (role=switch): a small track + knob before its label, the label naming the non-default outcome.
   On = filled track with the knob on the right. The whole button is the touch target (44px on touch, like the other controls). */
.r-outcome button.r-keep{flex:none;gap:var(--space-2);background:transparent;border-color:transparent;color:var(--muted-foreground);padding:0 var(--space-1)}
.r-outcome button.r-keep::before{content:"";flex:none;width:28px;height:16px;border-radius:var(--radius-lg);box-sizing:border-box;border:1px solid var(--border-strong);
  background:radial-gradient(circle 6px at 7px 50%,var(--muted-foreground) 96%,transparent) var(--muted)}
.r-outcome button.r-keep[aria-checked=true]{color:var(--foreground)}
.r-outcome button.r-keep[aria-checked=true]::before{border-color:var(--primary);background:radial-gradient(circle 6px at 19px 50%,var(--primary-foreground) 96%,transparent) var(--primary)}
.reply-box .r-err{margin:0}
#trash .arc-l2 .arc-reply:not(.open){white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.arc-sep{flex:none;color:var(--subtle-foreground)}
.arc-thread{margin:4px 0 0 var(--space-5)}   /* indentation only - no box */
.arc-thread .thread{margin:0;padding:0;border:0}
.edit .c-tools{margin-top:0;flex-wrap:wrap}
.edit .c-tools .e-range{white-space:nowrap}   /* the line range never wraps character by character - the whole thing drops to the next line if there's no room */
.pg-link{color:var(--primary);font-size:var(--text-sm);cursor:pointer}
.au{display:inline-flex;align-items:center;gap:var(--space-1);font-size:var(--text-sm);color:var(--muted-foreground);max-width:150px}
.au .au-n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.au.old{font-style:italic}
.av{width:22px;height:22px;border-radius:50%;flex:none;object-fit:cover}
.av.i{display:inline-flex;align-items:center;justify-content:center;background:var(--primary);color:var(--primary-foreground);
  font-size:var(--text-xs);font-weight:700;font-style:normal}
.av.agent{background:var(--accent);color:var(--muted-foreground)}
.av.agent .ic{width:13px;height:13px}
.me-tag{color:var(--muted-foreground);font-weight:400}
.edit{margin-top:var(--space-2)}
/* ---------------- List sections (docs/handbook/viewer.md §목록 구획): open pins - awaiting review - done, one header component. The header spans
   the full width and stays stuck to the top while scrolling (sticky) - so it's always clear which section is in view. Each section is wrapped in
   <section>, so the previous header gets pushed out once the next section arrives. --stick-top is the height of the tool bar (#bar1) stuck at the
   top in compact mode (measured by JS). The toggle button carries chevron - name - count - (collapsed only) 'new N'; tools follow it. A closed pin is a flat row, not a card. */
.lsec{position:relative}
.lsec+.lsec{margin-top:12px}
.sec-head{position:sticky;top:var(--stick-top,0px);z-index:2;display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-1) var(--space-2);
  background:var(--sidebar);margin:0 -12px 4px;padding:var(--space-1) var(--space-3);border-top:1px solid var(--border);scroll-margin-top:var(--stick-top,0px)}
#sec-open>.sec-head{border-top:0}
/* scroll-margin-top pairs with revealList()'s scrollIntoView({block:'start'}) - without it, the browser aligns this header's
   "static in-flow position" to the top of the viewport (0), but the sticky calculation then renders it pushed back down by stick-top.
   The next row's in-flow position lands in that empty gap (0 to stick-top) and got completely hidden under #bar1 (a touch regression). */
button.sec-tg{display:inline-flex;align-items:center;gap:var(--space-1);min-width:0;margin-left:calc(-1 * var(--space-1));padding:0 var(--space-1);
  background:transparent;border-color:transparent;color:var(--foreground);font-weight:700;white-space:nowrap;scroll-margin-top:var(--stick-top,0px)}
button.sec-tg:hover{background:var(--accent)}
.sec-tg>.ic{width:14px;height:14px;color:var(--muted-foreground)}
.sec-tg .sec-name{white-space:nowrap}
.sec-n{justify-content:center;min-width:20px;padding:0 var(--space-1);border-radius:var(--radius-lg);line-height:18px;font-weight:600;vertical-align:1px}
.sec-new{flex:none;padding:0 var(--space-1);border-radius:var(--radius-lg);line-height:18px;font-size:var(--text-xs);font-weight:600;
  background:color-mix(in srgb,var(--primary) 16%,transparent);color:var(--foreground)}
/* A section header's tools (re-read/pins that call me/all documents) are borderless ghosts - an active filter shows as a filled surface */
.sec-head button:not(.sec-tg){background:transparent;border-color:transparent;color:var(--muted-foreground);white-space:nowrap}
.sec-head button:not(.sec-tg):hover{background:var(--accent);color:var(--foreground)}
.sec-head button:not(.sec-tg)[aria-pressed=true]{background:var(--accent);border-color:transparent;color:var(--foreground)}
.arc-n,.dcnt{flex:none;justify-content:center;min-width:20px;padding:0 var(--space-1);border-radius:var(--radius-lg);line-height:18px}
.arc-list{padding:var(--space-2) 0 var(--space-1)}
.arc-list>.dim{padding:var(--space-1) 0}
.arc-row{position:relative;padding:var(--space-2) 0;color:var(--muted-foreground);font-size:var(--text-base);line-height:1.5}
.arc-row+.arc-row{border-top:1px solid var(--border)}   /* a flat row - a single divider, no stripe or box */
.arc-row.dropped{color:var(--subtle-foreground)}
.arc-row.dropped .arc-l1>.ic{color:var(--status-dropped)}
.arc-row .ic{width:14px;height:14px}
.arc-row.done .arc-l1>.ic{color:var(--status-closed)}
.arc-l1{display:flex;align-items:center;gap:var(--space-1);min-height:26px;white-space:nowrap}
.arc-l1 .n{font-weight:700}
.arc-l1 .loc{font-size:var(--text-sm)}
.arc-ref{flex:0 1 auto;min-width:0;line-height:16px;padding:0 var(--space-1);max-width:120px;overflow:hidden;text-overflow:ellipsis}
.arc-t{flex:none;font-size:var(--text-xs);white-space:nowrap}   /* the timestamp is never truncated - it's a short relative time so it's always readable (it used to become '09-24 1...') */
.arc-l1 .dchip,.arc-l1 .loc{min-width:0;overflow:hidden;text-overflow:ellipsis}
.arc-l1 .loc{flex:none}   /* the line range is never truncated - in a narrow panel, 'L890-L897' next to a long reference used to get clipped to 'L89' (folded-layout QA 2026-09-25). The reference shrinks first instead */
button.arc-b{flex:none;color:var(--muted-foreground)}
button.arc-b:hover{color:var(--foreground)}
.arc-l2{display:flex;align-items:baseline;gap:var(--space-2)}
.arc-reply{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
.arc-reply.open{white-space:pre-wrap;overflow:visible;word-break:break-word}
.arc-reply.none{font-style:italic;cursor:default}
button.arc-orig-t{flex:none;background:transparent;border-color:transparent;color:var(--primary);padding:0 var(--space-1);font-size:var(--text-sm);text-underline-offset:3px}
button.arc-orig-t:hover,button.arc-orig-t:focus-visible{background:transparent;color:var(--primary);text-decoration:underline}   /* a text action inside a row also uses the unified link style (primary color, underline on hover) */
.arc-orig{margin:4px 0 0 var(--space-5);white-space:pre-wrap;word-break:break-word;color:var(--card-foreground)}
.arc-orig b{display:block;font-size:var(--text-xs);font-weight:600;margin-bottom:2px}
h3{margin:0 0 var(--space-2);font-size:var(--text-sm);color:var(--muted-foreground);text-transform:uppercase;letter-spacing:.06em}
.hint{padding:var(--space-4) var(--space-3);color:var(--muted-foreground);font-size:var(--text-base);text-align:center;line-height:1.85}
kbd{background:var(--muted);border:1px solid var(--border);border-radius:var(--radius-sm);padding:1px var(--space-1);font:inherit;font-size:var(--text-xs);white-space:nowrap}   /* the browser's default monospace font rendered a Korean button name ('길게 누르기') with awkward spacing */
.spin{width:12px;height:12px;border:2px solid var(--border);border-top-color:var(--primary);border-radius:50%;
  animation:rot .8s linear infinite;display:inline-block}
@keyframes rot{to{transform:rotate(360deg)}}
/* Notifications (toast, docs/handbook/viewer.md §알림(토스트)): appear near where you just clicked - they used to show at the bottom-left (desktop) or
   top-left of the body (mid), ending up more than 1,100px from where the eye was after clicking [핀 저장] in the right panel (observed 2026-09-24).
   The horizontal position (--toast-r/--toast-w) and bottom height (--toast-b) are measured by placeToasts(): for wide/mid, bottom-right
   inside the panel column, just above the action row/save button; for narrow, above the sheet.
   The look is a single floating surface like sonner (thin border + shadow - only floating surfaces get a shadow). Status is a leading icon instead of a color stripe.
   New notifications stack at the top, and once there are more than 3, the rest collapse (expand on hover). */
#toasts{position:fixed;z-index:50;right:var(--toast-r,var(--space-3));bottom:var(--toast-b,var(--space-3));width:var(--toast-w,360px);
  max-width:calc(100vw - 2 * var(--space-2));display:flex;flex-direction:column;gap:var(--space-2);pointer-events:none}
.toast{pointer-events:auto;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;column-gap:var(--space-2);
  padding:var(--space-3);background:var(--popover);color:var(--popover-foreground);border:1px solid var(--border);border-radius:var(--radius-lg);
  box-shadow:var(--shadow);font-size:var(--text-base);line-height:1.45;animation:toast-in .16s ease-out}
.toast>.ic{margin-top:1px;color:var(--success)}
.toast.warn>.ic{color:var(--warning)}
.toast.err>.ic{color:var(--destructive)}
.toast .t-body{min-width:0;overflow-wrap:anywhere}
.toast .t-title{font-weight:600}
.toast .t-desc{color:var(--muted-foreground);font-size:var(--text-sm)}
.toast .t-acts{display:flex;align-items:center;gap:var(--space-1);margin:-3px -5px -3px 0}
#toasts:not(:hover):not(:focus-within) .toast:nth-child(n+4){display:none}
/* Touch: the toast body passes taps through (only its buttons receive them) - so a toast floating right above a phone's sheet never intercepts a PDF long-press or the tool bar. */
@media (pointer:coarse){.toast{pointer-events:none}.toast button{pointer-events:auto}}
@keyframes toast-in{from{opacity:0;transform:translateY(6px)}}
#tip{position:fixed;z-index:100;max-width:300px;background:var(--tooltip);color:var(--tooltip-foreground);font-size:var(--text-sm);line-height:1.5;
  padding:var(--space-1) var(--space-2);border-radius:var(--radius);pointer-events:none;box-shadow:var(--shadow);left:0;top:0}
dialog{background:var(--popover);color:var(--popover-foreground);border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:var(--shadow-lg);max-width:680px;
  width:92vw;padding:var(--space-4) var(--space-6);max-height:88vh}
dialog::backdrop{background:var(--shadow-color)}
dialog h2{font-size:var(--text-xl);margin:0 0 8px}
dialog .help-steps{margin:0;padding-left:var(--space-5);font-size:var(--text-base)}
dialog .help-legend{font-size:var(--text-base)}
dialog .help-legend+.help-legend{margin-top:var(--space-1)}
dialog h4{margin:var(--space-4) 0 var(--space-1);font-size:var(--text-base)}
dialog table{border-collapse:collapse;font-size:var(--text-base);width:100%}
dialog td{border-top:1px solid var(--border);padding:var(--space-1) var(--space-2);vertical-align:top}
dialog code{font-size:var(--text-sm);word-break:break-all}
.sw{display:inline-block;width:14px;height:10px;border:2px solid var(--status-open);vertical-align:middle;margin-right:4px}
.sw.w{border-color:var(--warning)}
.sw.a{border-color:var(--primary);border-style:dashed}
dialog .help-legend .st-dot{display:inline-block;vertical-align:middle;margin:0 4px 0 2px}
/* ---------------- Mobile/touch (docs/handbook/viewer.md §모바일 레이아웃)
   The layout is set by JS on body: lay-wide (1100px and up) - lay-mid (over 700px, under 1100px: a narrow side panel) -
   lay-narrow (700px and below: a bottom sheet). compact = mid|narrow. side-open = the panel/sheet is expanded.
   In the collapsed state, only the tool bar (#bar1), status chips (#bar2), and the re-place-location banner remain. */
.cmp,.tch{display:none}
.pin .sum{display:none}
.hint .t-touch{display:none}
.pg{-webkit-touch-callout:none}
#btn-select[aria-pressed=true]{background:var(--primary);color:var(--primary-foreground);border-color:var(--primary);font-weight:600}   /* on = looks like btn-default */
body.selmode .pg{touch-action:none;outline:2px dashed var(--primary);outline-offset:3px}
#coach{position:fixed;left:50%;transform:translateX(-50%);top:calc(var(--space-3) + env(safe-area-inset-top));z-index:60;background:var(--primary);
  color:var(--primary-foreground);border-radius:var(--radius-lg);padding:var(--space-1) var(--space-1) var(--space-1) var(--space-3);display:flex;gap:var(--space-2);align-items:center;
  width:max-content;max-width:calc(100vw - 16px);font-size:var(--text-lg);box-shadow:var(--shadow-lg)}
#coach button{background:transparent;color:inherit;border-color:transparent}
body:not(.lay-narrow) #coach{top:94px;pointer-events:none}
body:not(.lay-narrow) #coach button{pointer-events:auto}
#more{max-width:440px}
#more .more-head{flex-wrap:nowrap;gap:var(--space-2);margin-bottom:var(--space-2)}
#more .more-head .chip{background:var(--brand);max-width:min(60%,240px)}
#more .more-info{font-size:var(--text-base);color:var(--muted-foreground);overflow-wrap:anywhere;margin:0 0 var(--space-2)}
#more .more-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-2)}
#more .more-grid .wide{grid-column:1/-1}
#more .jump-row{display:flex;gap:var(--space-2)}
#more .jump-row input{flex:1;min-width:0}
#more .size-row{display:flex;align-items:center;gap:var(--space-2)}
#more .size-row .seg{flex:1;margin:0}
@media (pointer:coarse){
  :root{--doc-nav-h:48px}
  button.tch{display:inline-flex}
  .hint .t-touch{display:inline}
  .hint .t-mouse{display:none}
  button{min-height:44px;min-width:44px;padding:var(--space-2) var(--space-3);font-size:var(--text-lg);-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}
  button.btn-sm,.seg button{min-height:44px;padding:var(--space-2) var(--space-3);font-size:var(--text-base)}
  /* A tappable badge (assignee chip/awaiting review/build error) keeps its visual size and only widens its hit area to 44px - growing it via
     min-height:44px turned the card header's assignee chip into a 44px blue slab (folded-layout QA). */
  button.badge{min-height:0;min-width:0;padding:1px var(--space-2);position:relative}
  button.badge::after{content:'';position:absolute;left:-4px;right:-4px;top:50%;height:var(--control-h-touch);transform:translateY(-50%)}
  #bar1{flex-wrap:wrap;--tb-h:var(--control-h-touch)}
  #bar1 button{padding:0 var(--space-2)}
  input,textarea,select{font-size:var(--text-xl)}
  #bar1 input.n{width:84px;flex:0 0 84px;max-width:none;font-size:var(--text-xl)}   /* iOS zooms the screen when focusing an input field smaller than 16px */
  .loc,.pg-link,.pin .n.go{display:inline-flex;align-items:center;min-height:44px}
  /* #N is drawn narrow, only as wide as its text (26-35px) - the visual size is kept and a fixed 44x44 hit area is centered on top of it
     (a fixed size rather than an inset proportional to the parent's width is needed to guarantee 44 even for a short number). position:relative
     is given only to .n.go - giving it to .loc/.pg-link too let .loc, which comes later in DOM order, rise above .n.go's ::before
     in the positioned stacking order and intercept hit-testing for the right half (observed: cx+21 returned '.loc' instead of '#N').  */
  .pin .n.go{position:relative}
  .pin .n.go::before{content:'';position:absolute;left:50%;top:50%;width:var(--control-h-touch);height:var(--control-h-touch);transform:translate(-50%,-50%)}
  .mark b{width:26px;height:26px;left:-28px;font-size:var(--text-base)}
  .mark b::after{content:'';position:absolute;inset:-9px}
  #tip{max-width:min(300px,calc(100vw - 16px))}
  button.btn-icon,.step button{width:var(--control-h-touch);min-width:var(--control-h-touch)}
  /* button.btn-icon.btn-sm{width:var(--control-h-sm)} (the base rule, 0-0-2-1) is more specific than the
     button.btn-icon above (0-0-1-1), so it stayed at 24px even for touch (observed on the card-collapse .b-fold/toast-close buttons) - re-pinned here at the same specificity. */
  button.btn-icon.btn-sm{width:var(--control-h-touch);min-width:var(--control-h-touch);height:var(--control-h-touch)}
  #c-actions button{min-height:48px;font-size:var(--text-lg)}
  .pin .acts button{min-height:44px}
  /* To keep an archive row flat, [원래 요청] is drawn at 28px and only its hit area is widened to 44px via ::after */
  button.arc-orig-t{min-height:44px;min-width:44px;padding:0 var(--space-1);font-size:var(--text-base)}   /* the box itself is 44px (QA: used to be 58x28) */
  .arc-reply{min-height:44px;display:flex;align-items:center}
  .q-hint,.q-hint button{font-size:var(--text-base)}   /* the suggestion button is also 44px (the global button rule); the text is bumped up a step */
  /* [변경 보기] phone/folded-layout QA (2026-09-25): commit selection was 18px, [빌드 경고 보기] was 16px tall */
  #revision-list select,#revision-file-row select{min-height:var(--control-h-touch)}
  #revision-warning summary{line-height:var(--control-h-touch)}
  .arc-reply.open{display:block;padding:var(--space-2) 0}
  .th-n{min-height:44px;min-width:44px;justify-content:center}
  .thread :is(button.msg-more,button.th-more){padding-left:var(--space-1);padding-right:var(--space-1)}
  #grip::after{left:-9px;right:-9px}
}
body.lay-narrow #grip,body.lay-mid:not(.side-open) #grip{display:none}
/* mid: shows a grab bar in the middle of the handle (easier to find by touch) */
body.lay-mid #grip{width:8px;background:var(--sidebar);border-left:1px solid var(--border)}
body.lay-mid #grip::before{content:'';position:absolute;left:50%;top:50%;width:4px;height:44px;border-radius:var(--radius-sm);
  background:var(--border-strong);transform:translate(-50%,-50%)}
body.lay-mid #grip.on::before{background:var(--primary)}
body.compact button.cmp{display:inline-flex}
body.compact .sec{display:none}
body.compact #left{padding:var(--space-3) max(var(--space-2),env(safe-area-inset-right)) 60vh max(32px,env(safe-area-inset-left));min-width:0}
body.compact #main{min-width:0}
body.compact #right{overflow-y:auto;overscroll-behavior:contain;min-width:0;max-width:none}
body.compact #right>*{flex:none}
/* Compact tool bar: a single row of same-height items. Packed edge to edge with no gaps, and [⋯] sits in that same flow (text shrinks first if there's no room). */
body.compact #bar1{flex-wrap:nowrap;gap:var(--space-1);padding:var(--space-2) var(--space-3);position:sticky;top:0;z-index:3;background:var(--sidebar)}
body.compact #bar1 .sp{display:none}
body.compact #bar1 button{flex:1 1 auto;min-width:0;padding:0 var(--space-2);overflow:hidden;text-overflow:ellipsis;font-size:var(--text-base)}
/* If there's no room, the label chip shrinks first (the full name is in the description) - this prevents a button's text from getting clipped to something like 'DF 재빌드' */
body.compact #bar1 .chip{flex:0 50 auto;min-width:28px}
/* min-width:0 above (body.compact #bar1 button) is more specific (includes an id) than @media(pointer:coarse)'s
   button{min-width:44px} (line 3647), so it won for narrow screens (lay-mid), and that's why [선택] used to shrink all the way to 40px (observed).
   The same selector is re-pinned here, touch-only - since it comes later in source order than the rule above, it wins the specificity tie. */
@media (pointer:coarse){body.compact #bar1 button{min-width:44px}}
/* Folded (narrow): the label text is pulled out of the tool bar and placed on [더보기]'s first line - shrinking it to 28px left only 'C...', unreadable (2026-09-23).
   The label-color stripe at the very top (#brand-stripe) distinguishes the instance instead. The [문서] button always shows the short document name in full
   (body/response/cover letter) without shrinking. The spread-out folded layout (mid, 884px) is under the same flex-wrap:nowrap pressure and its label
   also shrank to 'CE-iTra...' (71px) (observed) - the same fix is applied there too. #more-label ([더보기]'s first line) already exists in both layouts
   (shared markup with no layout condition), so the full name is visible without a separate sheet. */
body.lay-narrow #bar1 .chip,body.lay-mid #bar1 .chip{display:none}
body.lay-narrow #bar1 #btn-doc{flex:none;overflow:visible}
/* Folded/phone-sheet tool bar (QA 2026-09-24): frequency order - [핀 N] [선택] [문서] ... [재빌드] [⋯]. The awaiting-review count is a pill
   inside [핀 N] (it used to float half-overlapping the button's corner border). [PDF 재빌드] is rarely used, so only its icon remains to free up
   thumb space (the name lives in aria-label/long-press description). Freeing that space also removed the width problem that used to clip it to '핀 02'. */
body.lay-narrow #btn-side{order:1}
body.lay-narrow #btn-select{order:2}
body.lay-narrow #btn-doc{order:3}
body.lay-narrow #btn-rebuild{order:4}
body.lay-narrow #btn-more{order:5}
body.lay-narrow #bar1 #btn-rebuild{flex:0 0 var(--tb-h);padding:0}
body.lay-narrow #btn-rebuild .lbl{display:none}
@media (max-width:360px){body.lay-narrow #btn-select .lbl{display:none}}   /* very narrow phone: [선택] is just the dashed-box icon (filled color when on) */
body.lay-narrow #btn-doc .nm{overflow:visible;text-overflow:clip;max-width:6em}
body.compact #bar1 #btn-more{flex:0 0 44px;padding:0;background:transparent;border-color:transparent}   /* utility = ghost (the same convention as notification/theme/help on desktop) */
body.compact #composer{max-height:none;overflow:visible}
/* Narrow sheet: the note field is moved above the source text - within the sheet height, the note field used to hide below the bottom action row (observed during the mobile improvements). */
body.lay-narrow #composer{display:flex;flex-direction:column}
body.lay-narrow #c-body{display:contents}
body.lay-narrow #c-snip,body.lay-narrow .snip-foot{order:2}
body.lay-narrow #note{order:1;margin:0 0 8px}
body.compact #list{overflow:visible;padding-bottom:calc(20px + env(safe-area-inset-bottom))}
/* In compact, #right is the scroll box - the action row is stuck to its bottom. */
body.compact #c-actions{position:sticky;bottom:0;padding:8px 12px calc(8px + env(safe-area-inset-bottom))}
body.compact #meta-txt,body.compact #me{display:none}
body.compact #bar2:not(:has(.badge:not([hidden]))){display:none}
body.compact:not(.side-open) #right>:not(#bar1):not(#bar2):not(#banner):not(#sheet-grip){display:none}
body.compact:not(.side-open) #bar1{order:3;border-bottom:0}
/* Toast placement (placeToasts): narrow is the full screen width right above the sheet; mid is the panel side just above the action row (inside its column if the panel is open). */
body.lay-narrow #toasts{left:var(--space-2);right:var(--space-2);width:auto;max-width:none}
body.lay-mid #toasts{max-width:calc(100vw - 2 * var(--space-3))}
/* Collapsed card (compact): one header line (number/location/page ... assignee/reply count/collapse) + two lines of note preview below it. The preview
   used to be squeezed into the header line's leftover width, showing just a fragment like '[C...', with most of the card's height wasted as empty space (QA 2026-09-24). The header's 44px hit area overlaps the card's padding. */
body.compact .pin .sum{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;
  margin:0 0 var(--space-1);color:var(--muted-foreground);font-size:var(--text-base);line-height:1.5;cursor:pointer}
body.compact .pin .head{flex-wrap:nowrap;margin:-6px 0}
body.compact .pin.open .sum,body.compact .pin.editing .sum{display:none}
body.compact .pin:not(.open):not(.editing) :is(.tags,.au,.note,.acts,.head>.sp,.thread){display:none}
body.compact .pin .au .au-n{display:none}
body.lay-narrow{display:block}
body.lay-narrow #main{height:100%}
body.lay-narrow #left{height:100%}
body.lay-narrow #right{position:fixed;left:0;right:0;bottom:var(--kb,0px);width:auto!important;height:auto;
  max-height:calc(var(--vvh,100dvh) - 48px);border-left:0;border-top:1px solid var(--border-strong);border-radius:var(--radius-lg) var(--radius-lg) 0 0;
  box-shadow:0 -6px 24px var(--shadow-color);z-index:20;padding:0 env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}
/* Sheet height: --sheet-f (fraction of screen height, default 0.64) is changed by dragging or pressing the top-edge handle (#sheet-grip). It shrinks to fit within the visible height when the keyboard is up. */
body.lay-narrow.side-open #right{height:min(calc(var(--sheet-f,.64) * 100dvh),calc(var(--vvh,100dvh) - 48px))}
body.lay-narrow #sheet-grip{display:flex;align-items:center;justify-content:center;height:24px;flex:none;position:sticky;top:0;z-index:4;
  background:var(--sidebar);border-radius:var(--radius-lg) var(--radius-lg) 0 0;touch-action:none;cursor:row-resize}
body.lay-narrow #sheet-grip::before{content:'';width:40px;height:4px;border-radius:var(--radius-sm);background:var(--border-strong)}
body.lay-narrow #sheet-grip::after{content:'';position:absolute;left:0;right:0;top:0;bottom:-8px}
body.lay-narrow #sheet-grip.on::before{background:var(--primary)}
body.lay-narrow #bar1{top:24px;padding-top:0}
/* ---- Spread-out folded layout / tablet (mid): the document nav bar on top, the action row on the bottom - both fixed to the full screen
   width, with the panel spread between them (docs/handbook/viewer.md §펼친 화면 레이아웃). It used to have the tool bar follow the panel, so [핀]
   jumped to the top-right when expanded and the bottom-right when collapsed (observed 842x758, y 56->693), and the document-side panel
   (901-1099px) clipped the nav bar by the panel's width (968px down to 630px). On a two-handed grip, the thumbs reach the two bottom
   corners - the frequently used [선택] sits bottom-left, and the panel toggle [핀 N] sits bottom-right where the panel appears, staying in
   the same spot regardless of whether the panel is open or closed. Save/cancel (#c-actions) is at the panel's bottom, right above the action
   row, so it's within right-thumb reach. The tool bar (#bar1) stays in the DOM inside #right and is pulled out visually via position:fixed -
   this is because the narrow sheet reuses the same markup as a sticky element below its handle. That's also why #right is never given a
   transform/filter/opacity (that would change a fixed child's containing block, and the action row would move together with the panel). */
body.lay-mid{--mbar-tb:var(--control-h);--mbar-h:calc(var(--mbar-tb) + 2 * var(--space-2) + 1px + env(safe-area-inset-bottom));
  --mid-top:calc(var(--doc-nav-h) + env(safe-area-inset-top));padding-top:var(--mid-top);padding-bottom:var(--mbar-h)}
@media (pointer:coarse){body.lay-mid{--mbar-tb:var(--control-h-touch)}}
body.lay-mid #bar1{position:fixed;left:0;right:0;top:auto;bottom:var(--kb,0px);z-index:30;height:var(--mbar-h);--tb-h:var(--mbar-tb);
  gap:var(--space-2);padding:var(--space-2) max(var(--space-3),env(safe-area-inset-right)) calc(var(--space-2) + env(safe-area-inset-bottom)) max(var(--space-3),env(safe-area-inset-left));
  background:var(--sidebar);border-top:1px solid var(--border);border-bottom:0;pointer-events:auto;visibility:visible}
/* Buttons keep their natural text width (never shrink or grow). Order follows thumb reach: [선택] .... [PDF 재빌드] [⋯] [핀 N].
   DOM order is shared with the narrow sheet, so only CSS order changes it. */
body.lay-mid #bar1 button{flex:none;min-width:var(--tb-h);padding:0 var(--space-3);overflow:visible}
body.lay-mid #bar1 #btn-more{flex:0 0 var(--tb-h);width:var(--tb-h);padding:0}
body.lay-mid #bar1 .sp{display:block;flex:1 1 0;order:2;align-self:stretch}
body.lay-mid #btn-select{order:1}
body.lay-mid #btn-rebuild{order:3}
body.lay-mid #btn-more{order:4}
body.lay-mid #bar1 #btn-side{order:5;min-width:calc(2 * var(--control-h-touch));justify-content:center;gap:var(--space-1)}
body.lay-mid #bar1 #btn-side[aria-expanded=true]{background:var(--accent);border-color:var(--border-strong)}
body.lay-mid.side-open #right{width:var(--side-w,clamp(300px,38vw,360px))!important}
/* Collapsed panel: #right remains an invisible frame, floating only the status chips (#bar2) and the re-place-location banner (#banner) at the bottom-right just above the action row.
   The frame itself never receives input, so it never blocks the PDF behind it. */
body.lay-mid:not(.side-open) #right{position:fixed;left:auto;top:auto;right:max(var(--space-3),env(safe-area-inset-right));
  bottom:calc(var(--mbar-h) + var(--kb,0px) + var(--space-2));width:auto!important;height:auto;max-width:calc(100vw - 2 * var(--space-3));
  display:flex;flex-direction:column;align-items:flex-end;gap:var(--space-2);
  background:transparent;border:0;box-shadow:none;z-index:20;overflow:visible;pointer-events:none}
body.lay-mid:not(.side-open) #right>#bar2,body.lay-mid:not(.side-open) #right>#banner{pointer-events:auto;background:var(--sidebar);
  border:1px solid var(--border-strong);border-radius:var(--radius-lg);box-shadow:var(--shadow-lg)}
/* Nav bar: fixed to the full screen width (the panel never clips it). Overflowing document links scroll horizontally within that row, with
   the overflowing edge faded (fade-l/fade-r, docLinksFade). The current document's link is always scrolled into view. */
body.lay-mid #paper-identity{display:none}
body.lay-mid #doc-nav{position:fixed;top:0;left:0;right:0;z-index:22;height:var(--mid-top);gap:var(--space-2);
  padding:env(safe-area-inset-top) max(var(--space-3),env(safe-area-inset-right)) 0 max(var(--space-3),env(safe-area-inset-left))}
body.lay-mid #doc-links{gap:var(--space-3);margin-right:0;flex:0 1 auto;scrollbar-width:none}
body.lay-mid #doc-links::-webkit-scrollbar{display:none}
body.lay-mid #doc-links.fade-r{mask-image:linear-gradient(to right,var(--foreground) calc(100% - 32px),transparent)}
body.lay-mid #doc-links.fade-l{mask-image:linear-gradient(to left,var(--foreground) calc(100% - 32px),transparent)}
body.lay-mid #doc-links.fade-l.fade-r{mask-image:linear-gradient(to right,transparent,var(--foreground) 32px,var(--foreground) calc(100% - 32px),transparent)}
body.lay-mid #view-switch{gap:var(--space-2);padding-left:var(--space-2)}
body.lay-mid #doc-nav button{white-space:nowrap}
/* At mid width, the outline overlays on top of the document (#main already starts below the nav bar). On a narrow tablet, pins overlay too, preserving the body's width. */
body.lay-mid #outline{position:absolute;left:0;top:0;bottom:0;z-index:18;border-right:1px solid var(--border);box-shadow:var(--shadow)}
body.lay-mid #outline-grip{display:none}
/* First-time onboarding: shown as a small chip just above the action row, on the left, right above the [선택] it points at - it never covers the nav bar or panel. */
body.lay-mid #coach{top:auto;bottom:calc(var(--mbar-h) + var(--kb,0px) + var(--space-2));left:max(var(--space-3),env(safe-area-inset-left));transform:none;
  max-width:calc(100vw - 2 * var(--space-3));padding:var(--space-1) var(--space-1) var(--space-1) var(--space-3);font-size:var(--text-base)}
body.lay-mid.side-open #coach{max-width:calc(100vw - var(--side-w,330px) - 3 * var(--space-3))}
@keyframes mid-panel-in{from{right:calc(-1 * var(--side-w,330px))}}
@keyframes mid-grip-in{from{opacity:0}}
@media (min-width:701px) and (max-width:900px){
  body.lay-mid.side-open #right{position:fixed;right:0;top:var(--mid-top);bottom:calc(var(--mbar-h) + var(--kb,0px));z-index:20;box-shadow:var(--shadow);
    animation:mid-panel-in .18s ease-out}
  /* At the width where the pin panel floats overlaid (folded), the change view gets offset by the panel width - unlike the body PDF, the diff
     can't be pushed aside to view, so the right half under the panel (the end of a wrapped line, the guidance line's [원고로]) was hidden (QA 2026-09-25, 842px). */
  body.lay-mid.side-open #revision-view{padding-right:var(--side-w,330px)}
  body.lay-mid.side-open #grip{position:fixed;right:var(--side-w,330px);top:var(--mid-top);bottom:calc(var(--mbar-h) + var(--kb,0px));z-index:21;
    animation:mid-grip-in .18s ease-out}
}
/* The folded layout (narrow) reuses the existing tool bar's [문서 ▾] button and sheet list as-is. */
.dm-item .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dcnt{font-weight:600}
.dcnt.z{color:var(--muted-foreground);font-weight:400;background:transparent}
.dm-item.on .dcnt:not(.z){background:var(--brand);color:var(--brand-foreground)}
.dvo{flex:none;line-height:14px;padding:0 var(--space-1);letter-spacing:.02em}
.ddot{flex:none;width:7px;height:7px;border-radius:50%;background:var(--warning)}
.dm-item .spin,#btn-doc .spin{width:10px;height:10px}
#btn-doc{display:none;align-items:center;gap:var(--space-1)}
#btn-doc .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body.lay-narrow.docs-multi #btn-doc{display:inline-flex}
body.view-only #btn-rebuild{display:none}
.dchip{flex:none;line-height:16px;max-width:110px;overflow:hidden;text-overflow:ellipsis}
.dchip.other{background:transparent;border-color:var(--border-strong);border-style:dashed}   /* another document = a dashed border (a meaningful border) */
#docs-menu{margin:auto auto 0;width:100%;max-width:560px;border-radius:var(--radius-lg) var(--radius-lg) 0 0;padding:var(--space-3) var(--space-3) calc(var(--space-3) + env(safe-area-inset-bottom))}
#docs-menu .dm-list{display:flex;flex-direction:column;gap:var(--space-2);margin-top:var(--space-2)}
.dm-item{display:flex;align-items:center;gap:var(--space-3);width:100%;text-align:left;padding:var(--space-3)}
.dm-item .tx{flex:1;min-width:0;display:flex;flex-direction:column}
.dm-item .ph{font-size:var(--text-sm);color:var(--muted-foreground);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dm-item{border-color:transparent;background:transparent}
.dm-item.on{background:var(--accent)}
/* Selection on a view-only PDF document: no range ladder, stepper, or source expansion (there is no line). The region's text is shown in the source field instead. */
#composer.region #c-levels,#composer.region .c-tools,#composer.region .snip-foot,#composer.region #c-copy{display:none}
.edit.region .e-levels,.edit.region .c-tools .step{display:none}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
/* Label chip/stripe (§Running multiple manuscript instances at once): since its purpose is distinguishing tabs when multiple manuscript viewers are
   open at once, the accent color is pinned as a fixed background (inline style) - the label color must stay the same across theme changes. */
#brand-stripe{position:fixed;top:0;left:0;right:0;height:4px;z-index:50;pointer-events:none}
.chip{flex:none;color:var(--brand-foreground);font-weight:700;font-size:var(--text-sm);line-height:1.4;padding:var(--space-1) var(--space-2);border-radius:var(--radius);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}
@media (max-width:480px){.chip{max-width:64px;font-size:var(--text-xs);padding:2px var(--space-1)}}
</style></head><body>
<div id="brand-stripe" style="background:__ACCENT__"></div>
<div id="main"><div id="doc-nav"><button id="nav-toc-toggle" data-act="outline" aria-controls="outline" aria-expanded="false" aria-label="목차 펼치기" class="btn-ghost btn-icon">{{ic:panel-left}}</button><span id="paper-identity"><span id="paper-identity-mark" aria-hidden="true">__LABEL_INITIAL__</span><span>__LABEL__</span></span><div id="doc-select-wrap"><label for="doc-select">문서</label><select id="doc-select" aria-label="문서 선택"></select></div><div id="doc-links" role="group" aria-label="문서 선택"></div><div id="view-switch" role="group" aria-label="보기"><button id="view-manuscript" data-act="view-mode" data-mode="manuscript" aria-pressed="true">원고</button><button id="view-revisions" data-act="view-mode" data-mode="revisions" aria-pressed="false">변경사항</button></div></div><div id="pdf-body"><nav id="outline" aria-label="원고 목차"><div class="outline-head"><span class="outline-title">목차</span></div><input id="outline-search" type="search" placeholder="장·절 찾기" aria-label="목차에서 장·절 찾기"><div id="outline-items" class="outline-empty">PDF 목차를 읽는 중입니다.</div></nav><div id="outline-grip" role="separator" aria-orientation="vertical" aria-controls="outline" aria-label="목차 폭" tabindex="0" aria-valuemin="220" aria-valuemax="320" aria-valuenow="240" data-tip="끌어서 목차 폭을 바꿉니다. ←/→ 키로 16px씩 바꿀 수 있습니다"></div><div id="pdf-center"><div id="section-strip"><span id="section-current">원고</span><span id="section-page"></span></div><div id="left"><div id="doc"></div></div><section id="revision-view" aria-label="원고 변경사항"><div id="revision-inner"><div id="revision-head"><h2>원고 변경사항</h2><div id="revision-list"></div></div><div id="revision-pin" role="status" hidden></div><div id="revision-note">선택 커밋의 첫 부모와 비교 · 이 문서의 Git 이력 · 미커밋 수정 제외</div><div id="revision-controls"><button id="revision-pdf-tab" data-act="revision-format" data-format="pdf" aria-pressed="true">변경 PDF</button><button id="revision-source-tab" data-act="revision-format" data-format="source" aria-pressed="false">소스 diff</button><button id="revision-whole" class="tg btn-sm" data-act="revision-whole" aria-pressed="false" hidden data-tip="이 핀의 변경만 넣은 비교 대신 커밋 전체의 비교 PDF를 봅니다. 다시 누르면 이 핀의 변경만 봅니다">커밋 전체 비교</button><button id="revision-wrap" class="tg btn-sm" data-act="diff-wrap" aria-pressed="false" data-tip="긴 줄을 화면 폭에 맞춰 접어 봅니다. 문단 하나가 한 줄인 원고는 켜 두세요">{{ic:text-wrap}}줄바꿈</button></div><div id="revision-status" role="status" aria-live="polite"></div><details id="revision-warning" hidden><summary>빌드 경고 보기</summary><pre></pre></details><div id="revision-pdf"></div><div id="revision-source" hidden><div id="revision-file-row" hidden><label for="revision-file">파일</label><select id="revision-file"></select></div><pre id="revision-diff" class="nowrap"></pre><button id="revision-other-toggle" class="btn-ghost btn-sm" data-act="revision-other" aria-expanded="false" aria-controls="revision-other" hidden>{{ic:chevron-right}}<span></span></button><pre id="revision-other" class="nowrap" hidden></pre></div></div></section></div></div></div>
<div id="toasts" role="status" aria-live="polite"></div>
<div id="grip" role="separator" aria-orientation="vertical" aria-controls="right" aria-label="패널 폭" tabindex="0" data-tip="끌어서 패널 폭을 바꿉니다. 탭(마우스는 두 번 클릭)하면 좁게 → 보통 → 넓게 순으로 바뀝니다. ←/→ 키로도 바뀝니다"></div>
<div id="right">
  <div id="sheet-grip" role="separator" aria-orientation="horizontal" aria-controls="right" aria-label="시트 높이" tabindex="0" data-tip="끌어서 시트 높이를 바꿉니다. 탭하면 낮게 → 보통 → 높게 순으로 바뀌고, 끝까지 내리면 접힙니다"></div>
  <div class="bar" id="bar1" role="toolbar" aria-label="도구">
    <button id="btn-doc" data-act="doc-menu" aria-haspopup="dialog" aria-label="문서 바꾸기" data-tip="이 논문의 다른 문서(답변서·커버레터 등)로 바꿉니다"><span class="nm" id="btn-doc-n">문서</span><span id="btn-doc-dot" class="ddot" hidden></span>{{ic:chevron-down}}</button>
    <button id="btn-side" class="cmp" data-act="side" aria-controls="right" aria-expanded="false" data-tip="핀 목록과 선택한 자리 패널을 펴고 접습니다. 보라색 숫자는 검토 대기(에이전트가 닫고 사람의 확인을 기다리는 핀) 수입니다">핀 <b id="side-n">0</b><span id="side-rv" class="rv-n" hidden></span><span id="side-arrow" aria-hidden="true">{{ic:chevron-up}}</span></button>
    <button id="btn-select" class="tch" data-act="selmode" aria-pressed="false" data-tip="켜면 PDF 위를 끌어서 영역을 고르고, 탭하면 그 자리 문단을 고릅니다. 끄면 보통처럼 스크롤·확대됩니다">{{ic:square-dashed}}<span class="lbl">선택</span></button>
    <button id="btn-rebuild" data-act="rebuild" aria-label="PDF 재빌드" data-tip="지금 원고(.tex)로 PDF를 새로 컴파일해 화면을 바꿉니다. 에이전트가 원고를 고친 뒤 결과를 볼 때 누르세요. 30초~1분쯤 걸리며, 끝나면 보던 자리 그대로 화면만 바뀝니다. 원본 폴더는 건드리지 않고 사본에서 빌드합니다.">{{ic:refresh-cw}}<span class="lbl">PDF 재빌드</span></button>
    <span class="sp"></span>
    <input class="n sec" id="jump" placeholder="쪽 이동" inputmode="numeric" aria-label="쪽 번호로 이동" data-tip="쪽 번호를 넣고 Enter">
    <button id="btn-zoom-out" class="sec btn-icon" data-act="zoom-out" aria-label="축소" data-tip="PDF 쪽만 축소합니다 (Ctrl/⌘ −, PDF 위에서 Ctrl/⌘+휠). 패널은 그대로입니다">{{ic:minus}}</button>
    <button id="btn-zoom-in" class="sec btn-icon" data-act="zoom-in" aria-label="확대" data-tip="PDF 쪽만 확대합니다 (Ctrl/⌘ +, PDF 위에서 Ctrl/⌘+휠·트랙패드 핀치). 패널은 그대로입니다">{{ic:plus}}</button>
    <button id="btn-fit" class="sec btn-icon" data-act="fit" aria-label="폭 맞춤" data-tip="폭 맞춤: PDF 쪽 폭을 왼쪽 화면 폭에 맞춥니다 (Ctrl/⌘ 0)">{{ic:move-horizontal}}</button>
    <button id="btn-notify" class="sec btn-icon" data-act="notify-toggle" aria-label="브라우저 알림: 꺼짐" data-tip="브라우저 알림(이 기기만): 나를 부르거나, 내 핀이 검토 대기로 오거나, 내 핀에 답글이 달리면 알립니다">{{ic:bell-off}}</button>
    <button id="btn-theme" class="sec btn-icon" data-act="theme" aria-label="화면 테마: 시스템" data-tip="화면 테마: 시스템 따름 → 밝게 → 어둡게 순으로 바뀝니다. PDF 종이 색은 그대로입니다">{{ic:sun-moon}}</button>
    <button id="btn-help" class="sec btn-icon" data-act="help" aria-label="도움말" data-tip="사용법·단축키·용어 설명, pins.md 위치 (?)">{{ic:circle-question-mark}}</button>
    <button id="btn-more" class="cmp btn-icon" data-act="more" aria-label="더보기" aria-haspopup="dialog" data-tip="핀 다시 읽기·쪽 이동·확대·테마·닫힌 핀·휴지통·도움말">{{ic:ellipsis}}</button>
  </div>
  <div class="bar" id="bar2"><span id="meta" class="dim"><span id="meta-txt"><span id="meta-main" data-tip="PDF를 만든 최상위 원고 파일"></span> · <span id="meta-pages" data-tip="지금 화면에 있는 PDF의 쪽 수"></span> · <span id="meta-head" data-tip="PDF를 만들 때의 원고 Git 커밋. 그 뒤의 커밋이나 저장된 수정은 이 PDF에 없습니다"></span> · <span id="meta-built" data-tip="PDF를 마지막으로 만든 시각"></span></span> <span id="meta-stale" class="badge badge-warning" hidden data-tip="이 PDF를 만든 뒤에 원고(.tex)가 바뀌었습니다. 지금 화면에서 고른 자리는 원문과 어긋날 수 있으니 [PDF 재빌드]를 누르세요">원고가 더 새롭습니다</span> <span id="meta-sync" class="badge" hidden></span> <span id="build-chip" class="badge" hidden data-tip="지금 다른 사람(또는 나)이 PDF를 재빌드하는 중입니다"></span></span><span class="sp"></span>
    <span id="vec-chip" class="badge badge-warning" hidden data-tip="PDF를 벡터로 그리지 못해 이미지(PNG)로 보입니다. 확대하면 흐릴 수 있습니다">PNG 보기</span>
    <span id="conn-lost" class="badge badge-warning" hidden data-tip="자동 동기화가 서버에 두 번 연속 닿지 못했습니다. 연결이 끊겼을 수 있습니다">연결 끊김</span>
    <button id="build-err-chip" class="badge badge-warning" hidden data-act="build-err-reopen" data-tip="마지막 빌드에 오류가 있었습니다 — 눌러서 다시 봅니다">빌드 오류 · 다시 보기</button>
    <button id="rv-chip" class="badge badge-review" hidden data-act="goto-review" data-tip="에이전트가 닫고 사람의 확인을 기다리는 핀입니다. 누르면 목록의 '검토 대기'로 갑니다"></button>
    <span id="me" class="au" data-tip="지금 이 화면을 쓰는 사람. 핀을 저장·수정·완료하면 이 이름으로 기록됩니다"></span></div>
  <div id="build-err" hidden></div>
  <div id="banner" hidden></div>
  <div id="composer" hidden role="region" aria-label="선택한 자리">
    <div id="c-err" class="errline" hidden></div>
    <div id="c-body">
      <div class="c-loc-row">
        <div class="c-loc-main"><span id="c-loc" class="loc" tabindex="0" data-tip="핀에 저장될 원문 위치입니다. 에이전트는 이 줄을 직접 열어 고칩니다. 누르면 복사"></span>
          <span id="c-page"></span><span id="c-tag" class="badge" hidden data-tip="원문 줄을 찾은 방법과 일치율"></span><span id="c-spin" class="spin" hidden aria-label="찾는 중"></span></div>
        <button class="btn-icon" id="c-copy" data-act="copy-cur" aria-label="위치 복사" data-tip="'파일 L시작-L끝'을 복사합니다. 채팅창에 붙이면 에이전트가 바로 그 줄을 엽니다">{{ic:copy}}</button>
      </div>
      <div id="c-warn" class="warnline" hidden></div>
      <div id="c-overlap" hidden></div>
      <div id="c-levels" class="seg" role="group" aria-label="범위 단계"></div>
      <div class="c-tools">
        <div class="step" role="group" aria-label="한 줄씩 넓히고 좁히기">
          <span class="sl" aria-hidden="true">위</span><button id="c-up-grow" data-act="nudge" data-dir="up-grow" aria-label="위로 한 줄 넓히기" data-tip="위로 한 줄 넓힙니다">{{ic:plus}}</button><button id="c-up-shrink" data-act="nudge" data-dir="up-shrink" aria-label="위에서 한 줄 좁히기" data-tip="위에서 한 줄 좁힙니다">{{ic:minus}}</button><span class="sl" aria-hidden="true">아래</span><button id="c-down-grow" data-act="nudge" data-dir="down-grow" aria-label="아래로 한 줄 넓히기" data-tip="아래로 한 줄 넓힙니다">{{ic:plus}}</button><button id="c-down-shrink" data-act="nudge" data-dir="down-shrink" aria-label="아래에서 한 줄 좁히기" data-tip="아래에서 한 줄 좁힙니다">{{ic:minus}}</button>
        </div>
      </div>
      <pre id="c-snip" class="wrap"></pre>
      <div class="snip-foot"><button class="tg btn-sm btn-ghost" id="c-wrap" data-act="wrap" aria-pressed="true" data-tip="긴 줄을 패널 폭에 맞춰 접어 봅니다. 문단 하나가 한 줄인 원고라면 켜 두세요">{{ic:text-wrap}}줄바꿈</button><button class="btn-sm btn-ghost" id="c-expand" data-act="expand" data-tip="접어 둔 원문 줄을 모두 보여 줍니다" hidden>원문 펼치기</button></div>
    </div>
    <div id="c-kind" class="seg kind-seg" role="radiogroup" aria-label="핀 종류"><button class="on" data-act="kind" data-kind="fix" role="radio" aria-checked="true" data-tip="이 자리를 고쳐 달라는 요청입니다. 에이전트가 원고를 고친 뒤 닫습니다">수정 요청</button><button data-act="kind" data-kind="question" role="radio" aria-checked="false" data-tip="고칠 곳이 아니라 묻는 핀입니다. 답이 이 핀의 스레드에 달리고, 원고는 질문이 수정을 뜻할 때만 고칩니다">질문</button></div>
    <textarea id="note" rows="3" placeholder="메모: 여기를 어떻게 고칠지 (비워도 됩니다) · @이름으로 사람을 부릅니다" aria-label="메모" data-tip="여기를 어떻게 고칠지 적습니다. 다른 곳을 다시 드래그해도 지워지지 않습니다"></textarea><div id="note-mentions" class="m-preview" aria-live="polite" hidden></div><div id="c-viewer" class="q-hint" role="status">{{ic:eye}}<span>보기 권한만 있습니다 — 위치와 원문만 볼 수 있고 핀은 남길 수 없습니다. 소유자에게 편집 권한을 요청하세요</span></div><div id="c-qhint" class="q-hint" role="status" hidden>{{ic:circle-question-mark}}<span>질문처럼 보입니다 —</span><button data-act="kind" data-kind="question" data-tip="이 핀을 질문으로 바꿉니다. 답이 이 핀의 스레드에 달립니다">질문으로 보내기</button></div><div id="c-assign" class="assign-row" role="radiogroup" aria-label="담당" hidden></div>
  </div>
  <div id="list">
    <div id="empty" class="hint" hidden><span class="t-mouse">PDF 위에서 <b>드래그</b>해 영역을 고르면</span><span class="t-touch">PDF를 <b>길게 누르면</b> 그 문단을, <b>[선택]</b>을 켜고 끌면 그 영역을 고르고</span> 그 자리의 <b>.tex 줄 번호</b>를 찾아 줍니다.<br>
      범위를 고르고 메모를 달아 핀으로 저장하면, 에이전트가 pins.md 한 장만 읽고 작업합니다.<br><span class="t-mouse"><kbd>?</kbd> 를 누르면 도움말.</span><span class="t-touch">도움말은 [더보기]에 있습니다.</span></div>
    <section class="lsec" id="sec-open" aria-labelledby="list-h">
      <div class="sec-head"><button class="sec-tg" id="open-toggle" data-act="sec-toggle" data-sec="open" aria-expanded="true" aria-controls="open-body" data-tip="열린 핀을 접고 폅니다. 접어 둔 동안 새로 온 핀 수가 머리에 붙습니다">{{ic:chevron-down}}<span class="sec-name" id="list-h">열린 핀 <span class="badge badge-secondary sec-n">0</span></span></button><span class="sp"></span><button id="btn-reload" class="sec btn-sm" data-act="reload" aria-label="핀 다시 읽기" data-tip="핀 파일을 다시 읽어 목록을 맞춥니다. 에이전트가 완료한 핀이 빠지고, 원고 수정으로 밀린 줄 번호가 다시 맞춰집니다. PDF는 바뀌지 않습니다.">다시 읽기</button><button class="btn-sm tg" id="mention-filter" data-act="mention-filter" aria-pressed="false" hidden data-tip="나를 @태그한 열린·검토 대기 핀만 봅니다(모든 문서). 다시 누르면 전부 봅니다"></button><button class="btn-sm tg" id="all-docs" data-act="all-docs" aria-pressed="false" hidden data-tip="다른 문서의 열린 핀도 함께 봅니다. 카드에 문서 이름이 붙고, #번호·[보기]를 누르면 그 문서로 바꿔 그 자리로 갑니다">모든 문서</button></div>
      <div id="open-body"><div id="pins"></div></div>
    </section>
    <section class="lsec" id="sec-review" aria-labelledby="review-h" hidden>
      <div class="sec-head"><button class="sec-tg" id="review-toggle" data-act="sec-toggle" data-sec="review" aria-expanded="true" aria-controls="review-pins" data-tip="에이전트가 닫고 사람의 확인을 기다리는 핀을 접고 폅니다">{{ic:chevron-down}}<span class="sec-name" id="review-h">검토 대기 <span class="badge badge-secondary sec-n">0</span></span></button></div>
      <div id="review-pins"></div>
    </section>
    <section class="lsec arc" id="sec-done" aria-labelledby="done-h" hidden>
      <div class="sec-head"><button class="sec-tg" id="done-toggle" data-act="sec-toggle" data-sec="done" aria-expanded="false" aria-controls="done-list" data-tip="완료한 핀을 펼치고 접습니다. 에이전트가 닫고 확인까지 끝난 핀도 여기에 있습니다">{{ic:chevron-right}}<span class="sec-name" id="done-h">완료 <span class="badge badge-secondary sec-n">0</span></span></button></div>
      <div id="done-list" class="arc-list" hidden></div>
    </section>
    <button id="trash-link" class="btn-sm" data-act="trash-open" hidden data-tip="삭제한 핀은 30일 동안 휴지통에 있습니다. 누르면 열어 되살릴 수 있습니다">휴지통 0</button>
  </div>
  <div id="c-actions">
    <button id="btn-cancel" data-act="cancel" data-tip="이 선택을 버립니다 (Esc)">취소</button>
    <button class="btn-default" id="btn-save" data-act="save" data-tip="메모와 위치를 핀으로 저장해 pins.md에 올립니다. 에이전트는 이 파일을 읽고 작업합니다 (⌘ Enter / Ctrl+Enter)">핀 저장</button>
  </div>
</div>
<div id="tip" role="tooltip" hidden></div>
<div id="mention-pop" role="listbox" aria-label="부를 사람" hidden></div>
<div id="coach" role="status" hidden><span id="coach-t"></span><button class="btn-icon btn-ghost" data-act="coach-close" aria-label="안내 닫기">{{ic:x}}</button></div>
<dialog id="more" aria-label="더보기 · __LABEL__">
  <div class="row more-head"><span id="more-label" class="chip" data-tip="__LABEL__ — 이 창이 다루는 논문. 여러 뷰어를 동시에 열었을 때 구분용">__LABEL__</span><h2 style="margin:0">더보기</h2><span class="sp"></span><button class="btn-sm btn-ghost" data-act="more-close">닫기</button></div>
  <p class="more-info" id="more-info"></p>
  <div class="more-grid">
    <button class="btn-secondary" data-act="reload" data-close="1">핀 다시 읽기</button>
    <button id="m-theme" class="btn-secondary" data-act="theme">테마: 시스템</button>
    <button id="m-lang" class="btn-secondary" data-act="lang" data-tip="화면 언어를 바꿉니다 (한국어 / English)">English</button>
    <button id="m-notify" class="btn-secondary wide" data-act="notify-toggle">알림 켜기</button>
    <button class="btn-secondary" data-act="zoom-out">축소</button>
    <button class="btn-secondary" data-act="zoom-in">확대</button>
    <button class="btn-secondary wide" data-act="fit" data-close="1">폭 맞춤</button>
    <div class="size-row wide"><span class="dim" id="m-size-l">패널 폭</span><div class="seg" id="m-size" role="group" aria-label="패널 폭"></div></div>
    <div class="jump-row wide"><input id="m-jump" inputmode="numeric" placeholder="쪽" aria-label="쪽 번호로 이동"><button class="btn-secondary" data-act="m-jump">이동</button></div>
    <button id="m-done" class="btn-secondary" data-act="done-toggle" data-close="1">닫힌 핀 0</button>
    <button id="m-trash" class="btn-secondary" data-act="trash-open" data-close="1" data-tip="삭제한 핀은 30일 동안 휴지통에 있습니다. 같은 번호로 되살릴 수 있습니다">휴지통 0</button>
    <button class="btn-secondary wide" data-act="help">도움말</button>
  </div>
</dialog>
<dialog id="docs-menu" aria-labelledby="docs-menu-h">
  <div class="row"><h2 id="docs-menu-h" style="margin:0">문서</h2><span class="sp"></span><button class="btn-sm" data-act="docs-menu-close">닫기</button></div>
  <div class="dm-list" id="docs-menu-list" role="listbox" aria-labelledby="docs-menu-h"></div>
</dialog>
<dialog id="trash" aria-labelledby="trash-h">
  <div class="row"><h2 id="trash-h" style="margin:0">휴지통</h2><span class="sp"></span><button class="btn-sm" data-act="trash-close" data-tip="휴지통 닫기 (Esc)">닫기</button></div>
  <p class="dim trash-note" id="trash-note"></p>
  <div id="trash-list" class="arc-list"></div>
</dialog>
<dialog id="help" aria-labelledby="help-h">
  <div class="row"><h2 id="help-h">Limn — 사용법</h2><span class="sp"></span><button class="btn-sm" data-act="help-close" data-tip="도움말 닫기 (Esc)">닫기</button></div>
  <h4>한 바퀴</h4>
  <ol class="help-steps">
    <li>PDF 위에서 고칠 곳을 <b>드래그</b>합니다. 점선 상자('새 핀')가 남습니다.</li>
    <li>사이드바의 <b>범위 단계</b>(드래그한 줄 / 문단 / 환경)와 한 줄 버튼(위·아래 +/−)으로 줄 범위를 맞춥니다.</li>
    <li>메모를 쓰고 <b>핀 저장</b>(⌘ Enter / Ctrl+Enter). 알림의 [되돌리기]로 바로 취소할 수 있습니다.</li>
    <li>에이전트에게 "핀 처리해줘"라고 말합니다. 에이전트는 pins.md 한 장을 읽고 원고를 고친 뒤 핀을 닫습니다.</li>
    <li><b>PDF 재빌드</b>로 결과를 봅니다. 보던 쪽과 쓰던 메모는 그대로 남습니다.</li>
    <li>결과가 맞으면 [확인], 틀렸으면 [답글]에 무엇이 틀렸는지 적습니다. 보내면 핀이 다시 열려 에이전트에게 갑니다.</li>
  </ol>
  <h4>휴대폰·태블릿(터치)</h4>
  <table><tr><td><kbd>길게 누르기</kbd></td><td>PDF 위를 길게 누르면 그 자리 문단을 고릅니다. 스크롤·확대는 평소처럼 됩니다</td></tr>
    <tr><td><kbd>선택</kbd></td><td>켜면 한 손가락으로 끌어 영역을 고르고, 탭하면 그 자리 문단을 고릅니다. 두 손가락으로 벌리면 PDF 만 커집니다. 핀을 저장하거나 취소하면 저절로 꺼집니다</td></tr>
    <tr><td><kbd>핀 N</kbd></td><td>핀 목록 패널(좁은 화면에서는 아래 시트)을 펴고 접습니다. 카드를 누르면 펼쳐집니다</td></tr>
    <tr><td><kbd>더보기</kbd></td><td>핀 다시 읽기·쪽 이동·확대·테마·닫힌 핀·휴지통·이 도움말</td></tr>
    <tr><td>패널 폭·시트 높이</td><td>패널 왼쪽 가장자리(아래 시트는 윗가장자리) 손잡이를 끌면 바뀌고, 탭하면 단계가 돌아갑니다. [더보기] → 패널 폭 / 시트 높이에서도 고릅니다. 시트는 끝까지 내리면 접힙니다</td></tr>
    <tr><td>설명 보기</td><td>버튼을 길게 누르면 설명이 뜹니다</td></tr></table>
  <h4>단축키</h4>
  <table><tr><td><kbd>드래그</kbd></td><td>영역을 골라 원문 위치를 찾습니다</td></tr>
    <tr><td><kbd>⌘ Enter</kbd> / <kbd>Ctrl+Enter</kbd></td><td>메모 칸에서 핀 저장, 편집 칸에서 수정 저장 (한글 조합 중에는 무시)</td></tr>
    <tr><td><kbd>Esc</kbd></td><td>열린 것부터 닫습니다: 도움말 → 툴팁 → 위치 다시 잡기 → 편집 취소 → 선택 취소</td></tr>
    <tr><td><kbd>Ctrl/⌘ + 휠</kbd> · <kbd>Ctrl/⌘ + = − 0</kbd></td><td>PDF 위에서 확대·축소(포인터 자리 기준), 0 은 폭 맞춤. 트랙패드 핀치도 같습니다. PDF 만 커지고 패널은 그대로입니다 (입력 칸 밖에서)</td></tr>
    <tr><td><kbd>?</kbd></td><td>이 도움말 (입력 칸 밖에서)</td></tr>
    <tr><td><kbd>Ctrl+PgUp</kbd>/<kbd>PgDn</kbd> · <kbd>Alt+1…9</kbd></td><td>문서 전환(문서가 여럿일 때, 입력 칸 밖에서). 브라우저가 이 키를 먼저 가져가면 PDF 위 문서 탭을 누르세요. 문서마다 보던 자리·확대를 기억합니다</td></tr>
    <tr><td>폭 손잡이</td><td>본문과 패널 사이 막대를 끌면 패널 폭이 바뀝니다. 두 번 클릭하면 좁게 → 보통 → 넓게, 포커스한 뒤 ←/→ 로도 바뀝니다. 폭은 브라우저에 기억됩니다</td></tr></table>
  <h4>용어</h4>
  <table>
    <tr><td>핀</td><td>출력물의 한 자리 + 요청이나 질문 + 그 대화. 번호(#N)는 다시 쓰이지 않습니다</td></tr>
    <tr><td>수정 요청 · 질문</td><td>핀을 저장할 때 고릅니다. 질문 핀은 에이전트가 원고를 고치지 않고 스레드에 답을 단 뒤 닫습니다</td></tr>
    <tr><td>스레드 · 답글</td><td>카드 아래의 대화. 사람과 에이전트가 [답글]로 주고받고, 닫기·다시 열기·확인도 한 줄씩 남습니다</td></tr>
    <tr><td>검토 대기</td><td>에이전트가 닫은 핀은 바로 완료가 되지 않고 여기서 사람의 [확인]을 기다립니다. 작성자에게 권하지만 누구나 누를 수 있습니다. 테일넷 사람이 [완료]를 누르면 그 사람이 검토자라 바로 완료입니다</td></tr>
    <tr><td>답글이 하는 일</td><td>검토 대기·완료 핀에 사람이 단 답글은 핀을 다시 열어 에이전트에게 보냅니다(답글이 곧 고칠 점). 사람을 @태그한 답글은 그 사람과의 대화로 남고 상태는 그대로입니다. 질문 핀의 답글은 답으로 남습니다. 답글 칸 아래 한 줄이 보내면 무엇이 되는지 미리 알려 주고, 드물게 [상태 유지]로 바꿉니다. 보낸 뒤 알림의 [되돌리기]로 취소합니다</td></tr>
    <tr><td>휴지통</td><td>[삭제]한 핀이 30일 동안 머무는 곳입니다. [더보기] → 휴지통(데스크톱은 목록 아래)에서 같은 번호로 되살립니다. 30일이 지나면 저절로 지워지고, 소유자는 바로 영구 삭제할 수 있습니다</td></tr>
    <tr><td>앵커</td><td>핀을 찍을 때 떠 둔 첫·끝 문장. 원고가 고쳐지면 이것으로 새 줄 번호를 찾습니다</td></tr>
    <tr><td>줄 이동</td><td>원고 수정으로 핀 위치가 밀려 다시 맞췄다는 표시('줄 +3 이동')</td></tr>
    <tr><td>위치 잃음</td><td>첫 문장이 바뀌거나 지워져 위치를 되찾지 못함. [수정] → 위치 다시 잡기로 고칩니다</td></tr>
    <tr><td>위치 불확실</td><td>드래그한 글자가 찾은 줄 범위에 90%보다 적게 들어 있을 때 붙는 배지입니다(90% 이상이면 배지가 없습니다). 30% 미만이면 노란색. 설명에 찾은 방법(좌표·글자)과 일치율이 있습니다 — 원문 칸에서 고칠 곳이 그 줄들에 있는지 확인하세요</td></tr>
    <tr><td>#N 범위 안 · #N과 같은 범위 · #N과 일부 겹침</td><td>다른 열린 핀과 줄 범위가 겹친다는 배지. 앞의 둘은 한 번에 고치고 함께 닫는 편이 낫고, 일부 겹침은 참고만 합니다</td></tr>
    <tr><td>작성자</td><td>tailscale 로 들어온 사람은 계정 이름으로, 로컬·에이전트 요청은 '로컬/에이전트'로 기록됩니다. 기록이 생기기 전 핀은 '기록 전'</td></tr>
    <tr><td>PDF 재빌드 vs 핀 다시 읽기</td><td>앞의 것은 원고를 컴파일해 화면을 바꾸고(수십 초), 뒤의 것(구 '새로고침')은 핀 목록만 다시 읽습니다(즉시)</td></tr>
  </table>
  <h4>색</h4>
  <div class="help-legend"><span class="sw"></span>열린 핀 · <span class="sw w"></span>위치 잃음 · <span class="sw a"></span>저장 전 선택</div>
  <div class="help-legend">카드 머리의 점: <span class="st-dot"></span>열림 · <span class="st-dot claimed"></span>처리 중 · <span class="st-dot review"></span>검토 대기 · <span class="st-dot lost"></span>위치 잃음 — 같은 뜻의 배지가 함께 붙는다. 완료는 목록 아래 흐린 행({{ic:check}} 완료), 삭제한 핀은 휴지통({{ic:trash-2}})</div>
  <h4>pins.md 위치</h4>
  <code id="help-pins-md"></code>
</dialog>
<script>
'use strict';
const $=s=>document.querySelector(s);
const $$=s=>Array.from(document.querySelectorAll(s));
// Lucide icons (vendor/lucide/README.md). Same shape as the server's icon_svg() - size is set by CSS (.ic).
const ICONS=__LUCIDE_JSON__;
function ic(n){const b=ICONS[n]; return b?'<svg class="ic ic-'+n+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'+b+'</svg>':'';}
const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const IS_MAC=/Mac|iPhone|iPad/i.test(navigator.platform||navigator.userAgent||'');
const SMOOTH=matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth';
const MQ=matchMedia('(prefers-color-scheme: light)');
let META=null,PINS=[],DONE=[],DROPPED=[],CUR=null,SAVING=false,ESAVING=false,EDIT=null,REPICK=null,PICKSEQ=0,PENDING=null,PICKING=false,PEND_SAVE=false;
let SNIP_OPEN=false,W=900,WRAP=true;
// Mobile: LAYOUT is 'wide'|'mid'|'narrow', SIDE_OPEN is whether the panel/sheet is expanded, SELMODE is touch selection mode,
// ZOOMED is whether the user changed the width via -/+ in compact (while true, it's never auto-fit to the screen width).
const MQ_COARSE=matchMedia('(pointer:coarse)');
// A device with no hover (phone/tablet): hover/focus tooltips are never shown at all - a tap sent a simulated mouseover and left the description stuck over the list (phone QA). Only long-press is used.
const MQ_NOHOVER=matchMedia('(hover:none)');
let OUTLINE_MID_OPEN=false,MID_OVERLAY=false;
let LAYOUT=null,SIDE_OPEN=true,SELMODE=false,ZOOMED=false,LAST_PTR='mouse',LAST_TOUCH_T=0;
const OPEN_CARDS=new Set();   // ids of pin cards expanded in compact
// Pin kind/thread (docs/handbook/viewer.md §스레드와 검토): KIND_NEW = the composer panel's kind (fix|question), REPLY = the open reply/reopen
// input field {id,mode,el} (holds onto the DOM like EDIT does, and re-inserts it in place when the list redraws), THREAD_OPEN = cards with the thread fully expanded,
// REPLY_DRAFT = a closed input field's draft text ('reply:12').
let KIND_NEW='fix',REPLY=null;
// @-tags (docs/handbook/viewer.md §@태그): PEOPLE = /api/people (tailnet people who opened this viewer + pin authors/actors), MENTION_ONLY = viewing only "pins that called me".
let PEOPLE=[],MENTION_ONLY=false;
const THREAD_OPEN=new Set(),REPLY_DRAFT=new Map();
// Multiple documents (§Multiple documents, docs/handbook/domain.md §여러 문서): DOCS = the /api/docs list, DOC = the current document key, DEFAULT_DOC = the first
// document that a legacy pin with no doc field belongs to. OPEN_ALL = open pins across all documents (PINS is the subset for the current document - marks/overlap/editing only look at PINS).
// META_BY = per-document meta cache (instant tab switching), VIEW_BY = per-document viewed position/zoom, BUILD_ERR_BY = per-document last build error,
// DOC_SEQ = another document's finished-build count (used to notice a build that finished in the background).
let DOCS=[],DOC=null,DEFAULT_DOC='main',OPEN_ALL=[],DONE_ALL=[],SHOW_ALL=false,SWITCHSEQ=0;
// Awaiting review (a pin closed by an agent, waiting for a person's [확인], state==='review'). Never put into DONE_ALL - drawn separately from the done archive.
let REVIEW_ALL=[];
const META_BY=new Map(),VIEW_BY=new Map(),BUILD_ERR_BY=new Map(),DOC_SEQ=new Map();
window.__pinViewerBoot=Date.now();   // a marker for checking reload status from outside

const T={
  stale:'핀을 찍은 첫 문장이 바뀌거나 지워져 위치를 되찾지 못했습니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
  n:"누르면 PDF에서 이 핀 자리로 갑니다. 에이전트에게는 '#2 처리해줘'처럼 번호로 부르세요. 번호는 다시 쓰이지 않습니다",
  loc:'핀이 가리키는 원문 줄. 클릭하면 복사',
  view:'PDF에서 이 핀 자리로 가서 깜빡입니다', edit:'메모와 범위를 고칩니다. 번호는 그대로입니다',
  close:"처리됨으로 표시해 목록과 pins.md에서 뺍니다. 아래 '닫힌 핀'에서 되돌릴 수 있습니다",
  drop:'핀을 휴지통으로 보냅니다. 알림의 [되돌리기]나 휴지통에서 같은 번호 그대로 되살릴 수 있습니다(30일 보관)',
  repick:'번호와 메모는 그대로 두고 PDF에서 새 위치를 드래그해 바꿉니다 (Esc 취소)',
  esave:'수정한 내용을 저장합니다 (⌘ Enter / Ctrl+Enter)', ecancel:'수정을 버립니다 (Esc)',
  restore:'삭제한 핀을 같은 번호로 되살려 열린 핀에 올립니다',
  purge:'휴지통에서 영구 삭제합니다(소유자만). 알림이 떠 있는 동안 [되돌리기]로 취소할 수 있고, 알림이 사라지면 지웁니다',
  synctex:'PDF 좌표(SyncTeX)로 줄을 찾았지만 드래그한 글자가 이 줄 범위에 다 있지는 않습니다(드문 낱말에 가중한 비율). 원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.',
  text:'드래그한 글자를 원문에서 직접 찾아 위치를 정했습니다(표·기호표처럼 좌표 조회가 약한 곳). 원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.',
  raw:'넓히기 전에 드래그 영역이 직접 가리킨 줄만 잡습니다',
  para:'드래그한 자리를 감싸는 문단 전체입니다(앞뒤 % 주석 줄은 뺍니다)',
  env:'감싸는 \\begin{…}…\\end{…} 블록 전체입니다. (바깥)은 한 단계 더 바깥 블록입니다',
  cur:'지금 핀이 가리키는 범위 그대로입니다',
  undo:'방금 한 저장·완료·삭제를 되돌립니다',
  question:'고칠 곳이 아니라 묻는 핀입니다. 답은 아래 스레드에 달리고, 원고는 질문이 수정을 뜻할 때만 고칩니다',
  review:'에이전트가 닫은 핀입니다. 사람이 결과를 보고 [확인]하면 완료로 가고, [답글]에 틀린 점을 쓰면 다시 열려 에이전트가 고칩니다',
  confirm:'결과를 확인했다고 기록하고 완료로 옮깁니다. 작성자에게 권하지만 누구나 누를 수 있고, 누른 사람이 기록됩니다',
  change:'변경사항 탭을 열어 이 핀을 고친 커밋(닫을 때 남긴 참조, 없으면 이 줄을 바꾼 최근 커밋)의 diff 에서 핀 자리를 강조합니다',
  reply:'이 핀에 답글을 답니다. 닫힌 핀이면 보내기 전에 칸 아래 한 줄이 결과(다시 열림·알림·그대로)를 알려 줍니다 (⌘ Enter / Ctrl+Enter 보내기)'
};

// ------------------------------------------------ Preferences (merged save)
// UI language (window.LIMN_LANG from the head script). Korean strings in this file are the source; in English
// mode tr()/trMsg() look them up in I18N_EN (src/limn/ui_en.json) and a MutationObserver translates text
// nodes and UI attributes as they are rendered. Strings missing from the table stay Korean.
const LANG=window.LIMN_LANG==='en'?'en':'ko', I18N_EN=__UI_EN_JSON__, I18N_ATTRS=['data-tip','aria-label','title','placeholder'];
function tr(s){if(LANG!=='en'||typeof s!=='string')return s; const t=s.trim();
  if(!t||!Object.prototype.hasOwnProperty.call(I18N_EN,t)||typeof I18N_EN[t]!=='string')return s; return s.replace(t,I18N_EN[t]);}
// Composed UI strings: tl('{n}쪽',{n:3}). The Korean key is the template and the Korean output; in English the
// table value is the template - a string, or plural forms {"one":...,"other":...} picked by p.n. {x} placeholders
// are filled from p (values are inserted as given - escape them first if the result goes into HTML).
function tl(k,p){let s=k; if(LANG==='en'&&Object.prototype.hasOwnProperty.call(I18N_EN,k)){const v=I18N_EN[k];
    s=typeof v==='string'?v:(v&&(Number(p&&p.n)===1&&v.one?v.one:v.other))||k;}
  return s.replace(/\{(\w+)\}/g,(m,x)=>p&&p[x]!=null?String(p[x]):m);}
function trMsg(s){if(LANG!=='en'||typeof s!=='string')return s; const e=tr(s); if(e!==s)return e;
  for(const sep of [' — ',' · ']){if(s.indexOf(sep)>0)return s.split(sep).map(tr).join(sep);} return s;}
function i18nEl(el){for(const a of I18N_ATTRS){const v=el.getAttribute(a); if(v){const e=trMsg(v); if(e!==v)el.setAttribute(a,e);}}}
function i18nText(n){const p=n.parentNode; if(!p||/^(TEXTAREA|SCRIPT|STYLE)$/.test(p.nodeName))return;
  const e=trMsg(n.nodeValue); if(e!==n.nodeValue)n.nodeValue=e;}
function i18nTree(root){if(LANG!=='en'||!root)return;
  if(root.nodeType===3)return i18nText(root);
  if(root.nodeType!==1)return; i18nEl(root);
  const w=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT); let n;
  while((n=w.nextNode())){if(n.nodeType===3)i18nText(n); else i18nEl(n);}}
function i18nStart(){const b=document.getElementById('m-lang'); if(b)b.textContent=LANG==='en'?'한국어':'English';
  if(LANG!=='en')return; i18nTree(document.body);
  new MutationObserver(ms=>{for(const m of ms){
    if(m.type==='childList')m.addedNodes.forEach(i18nTree);
    else if(m.type==='characterData')i18nText(m.target);
    else if(m.type==='attributes'&&m.target.nodeType===1){const v=m.target.getAttribute(m.attributeName);
      if(v){const e=trMsg(v); if(e!==v)m.target.setAttribute(m.attributeName,e);}}}})
    .observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:I18N_ATTRS});}
function switchLang(){try{localStorage.setItem('limnLang',LANG==='en'?'ko':'en');}catch(e){}
  const u=new URL(location.href); u.searchParams.delete('lang'); location.replace(u.toString());}
function prefs(){try{const p=JSON.parse(localStorage.getItem('pinPrefs')||'{}');return p&&typeof p==='object'?p:{};}catch(e){return {};}}
function savePrefs(patch){try{localStorage.setItem('pinPrefs',JSON.stringify(Object.assign(prefs(),patch)));}catch(e){}}
(function(){const p=prefs(); if(p.side)$('#right').style.width=p.side+'px'; if(p.w)W=p.w; if(p.wrap!==undefined)WRAP=!!p.wrap;})();
// List sections (docs/handbook/viewer.md §목록 구획): expanded/collapsed per section, remembered in pinPrefs.sec. Defaults: open pins and
// awaiting review expanded, done collapsed. SEC_SEEN holds, per section, the ids known at the first load plus everything the section
// held while expanded - while collapsed, a listed id not in it is counted as 'new N' on the header.
const SEC_DEFAULT={open:true,review:true,done:false};
function secState(saved){const o=Object.assign({},SEC_DEFAULT); if(saved&&typeof saved==='object')for(const k in SEC_DEFAULT)if(typeof saved[k]==='boolean')o[k]=saved[k]; return o;}
function secNewCount(seen,ids){if(!seen)return 0; return ids.filter(id=>!seen.has(id)).length;}
let SEC=secState(prefs().sec);
const SEC_SEEN={open:null,review:null,done:null};

const THEMES=['system','light','dark'],THEME_ICON={system:'sun-moon',light:'sun',dark:'moon'},THEME_NAME={system:'시스템',light:'밝게',dark:'어둡게'};
function applyTheme(){let t=prefs().theme||'light'; if(!THEME_ICON[t])t='light';
  const eff=t==='system'?(MQ.matches?'light':'dark'):(t==='light'?'light':'dark');
  document.documentElement.setAttribute('data-theme',eff); const b=$('#btn-theme'); b.innerHTML=ic(THEME_ICON[t]);
  const nm=tr(THEME_NAME[t]); b.setAttribute('aria-label',tl('화면 테마: {name}',{name:nm}));
  b.dataset.tip=tl('화면 테마: 지금 {name}. 누르면 시스템 따름 → 밝게 → 어둡게 순으로 바뀝니다. PDF 종이 색은 그대로입니다',{name:nm});
  const m=$('#m-theme'); if(m)m.textContent=tl('테마: {name}',{name:nm});}
MQ.addEventListener('change',applyTheme);
function cycleTheme(){const t=prefs().theme||'light';savePrefs({theme:THEMES[(THEMES.indexOf(t)+1)%3]});applyTheme();}

// ------------------------------------------------ Server calls and notifications
async function api(url,o){o=o||{};
  const init={method:o.method||'GET',headers:{}}; if(o.keepalive)init.keepalive=true;
  if(o.body!==undefined){init.body=JSON.stringify(o.body);init.headers['Content-Type']='application/json';}
  let r;
  const failed=()=>tl('{what} 실패',{what:tr(o.what||'요청').replace(/…$/,'')});
  try{r=await fetch(url,init);}catch(e){if(!o.silent)toast(failed()+' — '+tr('서버에 닿지 않습니다'),'err');throw e;}
  let d=null; try{d=await r.json();}catch(e){}
  if(r.status>=400&&!(o.expect||[]).includes(r.status)){
    if(!o.silent)toast(failed()+' — '+((d&&d.error)||('HTTP '+r.status)),'err');
    const err=new Error('HTTP '+r.status); err.status=r.status; err.data=d; throw err;}
  return {status:r.status,data:d};
}
// Toasts (docs/handbook/viewer.md §알림(토스트)): one title line + one faded description line. Text is split into title/description at the first ' — ' (or the first ' · ' if none).
const TOAST_IC={ok:()=>ic('circle-check'),warn:()=>ic('triangle-alert'),err:()=>ic('circle-x')};
// If ' — ' is present, everything before it is the title (the title of '핀 #10 · 본문 — 서준님이 불렀습니다: …' is '핀 #10 · 본문'), otherwise everything before the first ' · '.
function toastSplit(msg){msg=String(msg==null?'':msg); const m=/^(.+?) — (.+)$/.exec(msg)||/^(.+?) · (.+)$/.exec(msg); return m?[m[1],m[2]]:[msg,''];}
// Never announces the same transition on the same pin twice (QA: a focused tab showed both '핀 #37 · 본문 — 검토 대기: …' and '#37 이 검토 대기로 넘어왔습니다'
// at once). dd={keys:['review_requested:37'],rank}: if a toast with the same key is already showing within 8 seconds, a higher-rank new one replaces the old,
// while a lower-rank one is suppressed. The same rank (the same path) is treated as a different event and both are shown (e.g. a second awaiting-review after a reopen). The browser-notification path (notifyShow, rank 2) beats the list-comparison toast (rank 1).
const TOAST_KEYS=[];
function toastDup(dd){if(!dd||!dd.keys||!dd.keys.length)return false; const now=Date.now(),rank=dd.rank||1;
  for(let i=TOAST_KEYS.length-1;i>=0;i--){const x=TOAST_KEYS[i]; if(now-x.t>8000||!x.el.isConnected){TOAST_KEYS.splice(i,1);continue;}
    if(!dd.keys.some(k=>x.keys.includes(k)))continue;
    if(x.rank>rank&&dd.keys.every(k=>x.keys.includes(k)))return true;   // a new toast on the same path (same rank) is a different event - never suppressed
    if(rank>x.rank){x.el.remove(); TOAST_KEYS.splice(i,1);}}
  return false;}
function toast(msg,kind,action,dd){msg=trMsg(msg);
  if(toastDup(dd))return null;
  kind=TOAST_IC[kind]?kind:'ok';
  const box=toastHost(),t=document.createElement('div'); t.className='toast '+kind;
  const [title,desc]=toastSplit(msg);
  t.innerHTML=TOAST_IC[kind]()+'<div class="t-body"><div class="t-title"></div>'+(desc?'<div class="t-desc"></div>':'')+'</div><div class="t-acts"></div>';
  t.querySelector('.t-title').textContent=title; if(desc)t.querySelector('.t-desc').textContent=desc;
  const acts=t.querySelector('.t-acts');
  let timer=null; const kill=()=>{clearTimeout(timer);t.remove();hideTip();toastGone(t);};
  const arm=()=>{clearTimeout(timer);timer=setTimeout(kill,6000);};
  if(action){const b=document.createElement('button');b.className='btn-sm';b.textContent=action.label;b.dataset.tip=action.tip||T.undo;
    b.addEventListener('click',()=>{t._gone=null;kill();action.fn();});acts.appendChild(b);}
  const c=document.createElement('button');c.className='btn-icon btn-sm btn-ghost';c.innerHTML=ic('x');
  c.setAttribute('aria-label','알림 닫기');c.addEventListener('click',kill);acts.appendChild(c);
  t.addEventListener('mouseenter',()=>clearTimeout(timer)); t.addEventListener('mouseleave',arm);
  placeToasts(); box.insertBefore(t,box.firstChild); arm(); while(box.children.length>6){const l=box.lastChild; l.remove(); toastGone(l);}
  if(dd&&dd.keys&&dd.keys.length)TOAST_KEYS.push({keys:dd.keys.slice(),rank:dd.rank||1,el:t,t:Date.now()});
  watchToasts();
  return t;
}
// A toast's _gone hook runs once when it leaves the screen for any reason but its own action button - timeout, [x], or being
// pushed out by newer toasts. deferred() uses it: the action commits only once [되돌리기] is no longer on screen.
function toastGone(t){const g=t&&t._gone; if(g){t._gone=null; g();}}
// While a modal dialog is open (the Trash), the rest of the page is inert - a toast outside it could not be clicked. The toast box
// moves into the open modal dialog and back to <body> when it closes.
function toastHost(){const box=$('#toasts'),d=document.querySelector('dialog[open]:modal'),host=d||document.body;
  if(box.parentNode!==host)host.appendChild(box); return box;}
document.addEventListener('close',e=>{if(e.target&&e.target.tagName==='DIALOG'){const box=$('#toasts'); if(box.parentNode===e.target)document.body.appendChild(box);}},true);
// Deferred commit with an undo toast (docs/handbook/viewer.md §알림(토스트)): the change is sent when the toast goes away - after its 6 seconds
// (paused while hovered), on [x], or when the page is hidden - and [되돌리기] cancels it before anything reaches the server. So an
// agent never sees a reply or permanent delete that was taken back. The page being hidden or closed sends what is pending (fetch keepalive).
const DEFERRED=new Set();
function deferred(msg,commit,undo){let done=false,t=null;
  // Committing early (page hidden) also takes the toast away - an [되돌리기] that can no longer cancel anything must not stay on screen.
  const d={run:()=>{if(done)return; done=true; DEFERRED.delete(d); if(t&&t.isConnected){t._gone=null; t.remove();} commit();}};
  DEFERRED.add(d);
  t=toast(msg,'ok',{label:'되돌리기',tip:'보내기 전에 취소합니다',fn:()=>{if(done)return; done=true; DEFERRED.delete(d); undo();}});
  d.toast=t; if(t)t._gone=d.run; else d.run();
  return d;}
function flushDeferred(){Array.from(DEFERRED).forEach(d=>d.run());}
window.addEventListener('pagehide',flushDeferred);
document.addEventListener('visibilitychange',()=>{if(document.hidden)flushDeferred();});
// Toast placement: near where you just clicked. wide/mid is bottom-right of the panel column - just above the top edge of whichever action row is
// visible (#c-actions: save/cancel, mid's bottom tool bar, or the status chips floating in collapsed mid). narrow is just above the sheet's top edge
// (or above the screen if the sheet nearly fills it). While showing, the position is re-measured (watchToasts) whenever the panel opens/closes or the
// composer panel appears - so the save/cancel buttons and the bottom tool bar are never covered.
function placeToasts(){const box=$('#toasts'),right=$('#right'); if(!box||!right)return;
  const R=document.documentElement.style,gap=8,vh=innerHeight;
  const shown=el=>{if(!el||el.hidden)return false; const cs=getComputedStyle(el); if(cs.display==='none'||cs.visibility==='hidden')return false;
    const r=el.getBoundingClientRect(); return r.height>0&&r.width>0&&r.top<vh;};
  let top=vh,r=12,w=360;
  if(LAYOUT==='narrow'){r=8; w=innerWidth-16; if(shown(right))top=Math.min(top,right.getBoundingClientRect().top);
    // If the sheet covers most of the screen (starts within the top 30%), there's no room above it - raising it above the screen
    // instead covered the sheet's own tool bar ([더보기] etc.), making it unpressable (a touch regression). In that case, it's placed inside the
    // sheet near the bottom, above the save/cancel row if that's visible.
    if(top<vh*0.3){top=vh; const ca=$('#c-actions'); if(shown(ca))top=ca.getBoundingClientRect().top;}}
  else{const open=LAYOUT==='wide'||SIDE_OPEN,rr=right.getBoundingClientRect();
    if(open&&rr.width>0){r=Math.max(gap,innerWidth-rr.right+12); w=Math.min(380,rr.width-24);} else w=Math.min(360,innerWidth-24);
    ['#c-actions'].concat(LAYOUT==='mid'?['#bar1']:[],LAYOUT==='mid'&&!open?['#bar2','#banner']:[]).forEach(s=>{const e=$(s);
      if(shown(e))top=Math.min(top,e.getBoundingClientRect().top);});}
  R.setProperty('--toast-b',Math.max(gap,Math.round(vh-top+gap))+'px'); R.setProperty('--toast-r',Math.round(r)+'px'); R.setProperty('--toast-w',Math.round(Math.max(200,w))+'px');}
let TOAST_WATCH=0;
function watchToasts(){if(TOAST_WATCH)return; TOAST_WATCH=setInterval(()=>{if(!$('#toasts').children.length){clearInterval(TOAST_WATCH);TOAST_WATCH=0;return;} placeToasts();},250);}
async function copyText(s){
  try{await navigator.clipboard.writeText(s);}catch(e){
    const ta=document.createElement('textarea');ta.value=s;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');}catch(e2){} ta.remove();}
  toast(tl('복사함: {text}',{text:s}),'ok');
}

// ------------------------------------------------ Tooltip
const TIP=$('#tip'); let tipT=null,tipEl=null,TIPXY=null;
document.addEventListener('mousemove',e=>{TIPXY=[e.clientX,e.clientY];},{passive:true});
function hideTip(){clearTimeout(tipT);tipT=null;tipEl=null;TIP.hidden=true;}
function showTip(el){const txt=el.dataset.tip; if(!txt||!document.contains(el))return;
  TIP.textContent=txt; TIP.hidden=false;
  const r=el.getBoundingClientRect(),tw=TIP.offsetWidth,th=TIP.offsetHeight;
  let top=r.top-th-8, cx=r.left+r.width/2;
  if(top<4) top=r.bottom+8;
  if(top>innerHeight-th-4 && TIPXY){top=TIPXY[1]+18; cx=TIPXY[0];}   // an element taller than the window (#grip/a long card) anchors to the pointer instead
  top=Math.max(4,Math.min(top,innerHeight-th-4));
  const left=Math.min(Math.max(4,cx-tw/2),innerWidth-tw-4);
  TIP.style.left=left+'px'; TIP.style.top=top+'px';}
function armTip(el){if(el===tipEl)return; hideTip(); if(!el)return; tipEl=el; tipT=setTimeout(()=>showTip(el),300);}
// Hover/focus tooltips are never shown right after a touch - mobile Chrome simulates mouseover/focusin on every tap, so a
// description used to pop up every time a button was pressed. Touch relies on long-press instead (below).
const touchRecent=()=>Date.now()-LAST_TOUCH_T<1500;
document.addEventListener('pointerdown',e=>{LAST_PTR=e.pointerType||'mouse'; if(LAST_PTR!=='mouse')LAST_TOUCH_T=Date.now();},true);
document.addEventListener('mouseover',e=>{if(touchRecent()||MQ_NOHOVER.matches)return; armTip(e.target.closest?e.target.closest('[data-tip]'):null);});
// A focus tooltip is never shown on an input field (textarea) - it covered the snippet while typing, and the tooltip
// swallowed the first Esc, so "Esc to cancel -> Ctrl+Enter" ended up saving a pin that was meant to be discarded (observed).
document.addEventListener('focusin',e=>{const t=e.target;
  if((t&&t.tagName==='TEXTAREA')||touchRecent()||MQ_NOHOVER.matches){if(Date.now()>=SWALLOW_CLICK)hideTip();return;}
  armTip(t.closest?t.closest('[data-tip]'):null);});
// Long-press tooltip (touch/pen): holding for 500ms shows the description, and the one click after release is swallowed (so the button doesn't fire).
// Over a page image, quick selection (long-press = that paragraph) takes priority, so only badges (.mark b) apply. Input fields keep their paste menu.
let PRESS=null,SWALLOW_CLICK=0;
function pressTarget(t){const el=t&&t.closest?t.closest('[data-tip]'):null; if(!el)return null;
  if(el.tagName==='TEXTAREA'||el.tagName==='INPUT')return null;
  if(el.closest('.pg')&&!el.closest('.mark b'))return null; return el;}
document.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse')return; if(!TIP.hidden)hideTip();
  const el=pressTarget(e.target); if(!el)return;
  PRESS={el,x:e.clientX,y:e.clientY,t:setTimeout(()=>{showTip(el); PRESS.shown=true; SWALLOW_CLICK=Date.now()+900;
    setTimeout(()=>{if(!TIP.hidden&&TIP.textContent===el.dataset.tip)hideTip();},4000);},500)};},true);
function endPress(){if(PRESS){clearTimeout(PRESS.t); PRESS=null;}}
document.addEventListener('pointermove',e=>{if(PRESS&&Math.hypot(e.clientX-PRESS.x,e.clientY-PRESS.y)>10)endPress();},true);
document.addEventListener('pointerup',endPress,true);
document.addEventListener('pointercancel',endPress,true);
document.addEventListener('click',e=>{if(Date.now()<SWALLOW_CLICK){SWALLOW_CLICK=0;e.preventDefault();e.stopImmediatePropagation();}},true);
document.addEventListener('contextmenu',e=>{if(LAST_PTR==='mouse')return; const t=e.target;
  if(t&&t.closest&&(t.closest('.pg')||pressTarget(t)))e.preventDefault();});
document.addEventListener('input',hideTip,true);
document.addEventListener('focusout',hideTip);
document.addEventListener('scroll',hideTip,true);
// Releasing right after a long-press opens it, Chrome sends a simulated mousedown - that alone must never close it.
document.addEventListener('mousedown',()=>{if(Date.now()>=SWALLOW_CLICK)hideTip();},true);

// ------------------------------------------------ Multiple documents - list/tabs/switching (docs/handbook/domain.md §여러 문서)
function multiDoc(){return DOCS.length>1;}
function docInfo(k){return DOCS.find(d=>d.key===k)||null;}
function pdoc(p){return (p&&p.doc)||DEFAULT_DOC;}
function isRegion(p){return !!p&&(p.kind==='region'||(!p.file&&!!p.pdf));}
// Appends ?doc=<key> to a document-scoped path (the server treats it as the first document if absent).
function dq(u,k){k=k||DOC; if(!k)return u; return u+(u.indexOf('?')<0?'?':'&')+'doc='+encodeURIComponent(k);}
function hashDoc(){const m=/(?:^#|[#&])doc=([a-z0-9-]{1,24})(?:&|$)/.exec(location.hash||''); return m?m[1]:null;}
function setHash(k){if(!multiDoc())return; const h='#doc='+k; if(location.hash!==h)history.replaceState(null,'',location.pathname+location.search+h);}
// The document shown first: URL hash (link sharing/reload) > the last document viewed on this device > the first document.
function initialDoc(){const h=hashDoc(); if(h&&docInfo(h))return h; const l=prefs().lastDoc; if(l&&docInfo(l))return l;
  return DOCS.length?DOCS[0].key:null;}
async function loadDocs(){try{const r=(await api('/api/docs',{what:'문서 목록',silent:true})).data;
    DOCS=Array.isArray(r.docs)?r.docs:[]; DEFAULT_DOC=r.default||(DOCS[0]&&DOCS[0].key)||'main';}catch(e){DOCS=[];}
  document.body.classList.toggle('docs-multi',multiDoc()); $('#all-docs').hidden=!multiDoc();}
function docCount(k){return OPEN_ALL.filter(p=>pdoc(p)===k).length;}
function docBadge(d){const n=docCount(d.key);
  return (d.building?'<span class="spin" aria-label="빌드 중"></span>':(d.stale_build?'<span class="ddot" aria-label="원고 수정됨"></span>':''))+
    (d.view_only?'<span class="badge dvo" aria-label="보기 전용">PDF</span>':'')+'<span class="badge badge-secondary dcnt'+(n?'':' z')+'" aria-label="'+esc(tl('열린 핀 {n}',{n}))+'">'+n+'</span>';}
function docTip(d){return d.name+' · '+d.path+(d.view_only?' · 보기 전용 PDF(줄 번호 없이 쪽·영역으로 핀을 남깁니다)':'')+
  (d.building?' · 빌드 중':(d.stale_build?' · 원고가 이 PDF보다 새롭습니다(그 탭에서 [PDF 재빌드])':''));}
function drawDocTabs(){
  const box=$('#doc-select');
  box.innerHTML=DOCS.map(d=>'<option value="'+esc(d.key)+'">'+esc(d.name)+(d.building?' · 빌드 중':d.stale_build?' · 원고 수정됨':'')+'</option>').join('');
  if(DOC)box.value=DOC;
  $('#doc-links').innerHTML=DOCS.map(d=>'<button data-act="doc" data-doc="'+esc(d.key)+'" aria-current="'+(d.key===DOC?'page':'false')+'" title="'+esc(docTip(d))+'">'+esc(d.name)+(d.n_pages?'<span class="doc-link-count">'+tl('{n}쪽',{n:d.n_pages})+'</span>':'')+'</button>').join('');
  const cur=docInfo(DOC); $('#btn-doc-n').textContent=cur?cur.name:tr('문서');
  $('#btn-doc-dot').hidden=!DOCS.some(d=>d.key!==DOC&&(d.stale_build||d.building));
  if(DOC!==DOC_LINK_SHOWN){DOC_LINK_SHOWN=DOC; docLinksReveal();} else docLinksFade();
  if($('#docs-menu').open)drawDocsMenu();}
// When the document-links row overflows (e.g. 5 documents in mid): the overflowing edge is faded (fade-l/fade-r) to show there's more,
// and when the document changes, the current document's link is scrolled into view. A polling redraw never touches wherever the user has scrolled to (only a document change does).
let DOC_LINK_SHOWN=null;
function docLinksFade(){const d=$('#doc-links'); if(!d)return; const over=d.scrollWidth-d.clientWidth;
  d.classList.toggle('fade-l',over>1&&d.scrollLeft>1); d.classList.toggle('fade-r',over>1&&over-d.scrollLeft>1);}
function docLinksReveal(){const d=$('#doc-links'),a=d&&d.querySelector('[aria-current=page]');
  if(a&&d.scrollWidth>d.clientWidth){const dr=d.getBoundingClientRect(),ar=a.getBoundingClientRect(),pad=40;
    if(ar.left<dr.left+pad)d.scrollLeft-=dr.left+pad-ar.left; else if(ar.right>dr.right-pad)d.scrollLeft+=ar.right-(dr.right-pad);}
  docLinksFade();}
$('#doc-links').addEventListener('scroll',docLinksFade,{passive:true});
if(window.ResizeObserver)new ResizeObserver(()=>docLinksReveal()).observe($('#doc-links'));
let REVISION_SEQ=0,REVISION_FILES=[],REVISION_WHOLE='',REVISION_COMMIT='',REVISION_SOURCE_COMMIT='',REVISION_FORMAT='pdf';
// v0.3 (docs/handbook/viewer.md §변경 보기): a pin's view of a commit. REVISION_SCOPE is the source diff's scope object
// ({mode:'pin'|'commit', source, hunks, other, ...}); REV_PDF holds the comparison PDF's toggle - whole commit or only this pin.
let REVISION_SCOPE=null,REVISION_OTHER='';
const REV_SCOPE={whole:false,partial:false,fallback:false};
const REV_PDF={doc:null,loading:null,observer:null,tasks:new Set()};
function revisionFiles(patch){
  const starts=[];const re=/^diff --git .+$/gm;let m;
  while((m=re.exec(patch))!==null)starts.push({at:m.index,head:m[0]});
  return starts.map((s,i)=>{const n=s.head.lastIndexOf(' b/');return {
    name:n>=0?s.head.slice(n+3):tl('파일 {n}',{n:i+1}),text:patch.slice(s.at,i+1<starts.length?starts[i+1].at:undefined)};});
}
// Source diff wrapping: on by default for touch devices (a manuscript where a paragraph is one line was 6,273px wide on a phone, QA). The on/off value is stored in pinPrefs.diffWrap.
let DIFF_WRAP=null;
function setDiffWrap(on){DIFF_WRAP=!!on; savePrefs({diffWrap:DIFF_WRAP}); for(const d of [$('#revision-diff'),$('#revision-other')])if(d)d.className=DIFF_WRAP?'wrap':'nowrap';
  const b=$('#revision-wrap'); if(b)b.setAttribute('aria-pressed',String(DIFF_WRAP));}
function initDiffWrap(){const v=prefs().diffWrap; setDiffWrap(typeof v==='boolean'?v:MQ_COARSE.matches);}
function renderRevisionDiff(patch){
  const lines=String(patch||'').split('\n'); if(lines[lines.length-1]==='')lines.pop();
  let oldLine=null,newLine=null,inHunk=false;
  return lines.map(line=>{
    let kind='meta',number='';
    if(line.startsWith('diff --git ')){kind='file';inHunk=false;oldLine=newLine=null;}
    else if(line.startsWith('@@ ')){
      kind='hunk';inHunk=true;
      const at=/^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);
      oldLine=at?Number(at[1]):null;newLine=at?Number(at[2]):null;
    }
    else if(!inHunk&&(line.startsWith('--- ')||line.startsWith('+++ '))){kind='meta';}
    else if(line.startsWith('+')){kind='add';if(newLine!==null)number=newLine++;}
    else if(line.startsWith('-')){kind='del';if(oldLine!==null)number=oldLine++;}
    else if(line.startsWith(' ')){kind='context';if(newLine!==null){number=newLine++;oldLine++;}}
    return '<span class="rd-line rd-'+kind+'"><span class="rd-no" aria-hidden="true">'+number+'</span><span class="rd-code">'+esc(line)+'</span></span>';
  }).join('');
}
function renderRevisionFile(){const v=$('#revision-file').value,i=Number(v);
  $('#revision-diff').innerHTML=renderRevisionDiff(v==='all'?REVISION_WHOLE:(REVISION_FILES[i]&&REVISION_FILES[i].text)||REVISION_WHOLE);}
// The rest of the commit, folded under one control (v0.3). Hidden when the pin owns the whole commit or the view is not a pin's.
function drawRevisionOther(sc){const b=$('#revision-other-toggle'),o=$('#revision-other');
  o.hidden=true;o.innerHTML='';b.setAttribute('aria-expanded','false');
  REVISION_OTHER=sc&&sc.mode==='pin'?String(sc.other_diff||'')+(sc.other_truncated?'\n\n'+tr('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.'):''):'';
  b.hidden=!REVISION_OTHER;if(REVISION_OTHER)b.querySelector('span').textContent=tl('이 커밋의 다른 변경 {n}곳',{n:sc.other});}
function toggleRevisionOther(){const b=$('#revision-other-toggle'),o=$('#revision-other'),open=b.getAttribute('aria-expanded')!=='true';
  b.setAttribute('aria-expanded',String(open));o.hidden=!open;
  if(open&&!o.innerHTML)o.innerHTML=renderRevisionDiff(REVISION_OTHER);}
// [커밋 전체 비교]: shown only for the PDF of a pin that owns part of the commit, and not after a fallback (there is nothing to switch to).
function syncRevisionWhole(){const b=$('#revision-whole');
  b.hidden=!(REVISION_FORMAT==='pdf'&&REV_TARGET&&REV_SCOPE.partial&&!REV_SCOPE.fallback);
  b.setAttribute('aria-pressed',String(REV_SCOPE.whole));}
function setRevisionWhole(on){REV_SCOPE.whole=!!on;++REVISION_SEQ;REVISION_PDF_COMMIT='';
  clearRevisionPdf();$('#revision-warning').hidden=true;setRevisionFormat('pdf');}
function revisionCurrent(seq,k,id){return seq===REVISION_SEQ&&k===DOC&&id===REVISION_COMMIT&&document.body.classList.contains('revision-open');}
function clearRevisionPdf(){
  if(REV_PDF.observer){REV_PDF.observer.disconnect();REV_PDF.observer=null;}
  REV_PDF.tasks.forEach(t=>{try{t.cancel();}catch(e){}});REV_PDF.tasks.clear();
  if(REV_PDF.loading){try{REV_PDF.loading.destroy();}catch(e){}REV_PDF.loading=null;}
  REV_PDF.doc=null;$('#revision-pdf').replaceChildren();
}
function setRevisionFormat(format){REVISION_FORMAT=format==='source'?'source':'pdf';
  $('#revision-pdf-tab').setAttribute('aria-pressed',String(REVISION_FORMAT==='pdf'));
  $('#revision-source-tab').setAttribute('aria-pressed',String(REVISION_FORMAT==='source'));
  $('#revision-pdf').hidden=REVISION_FORMAT!=='pdf';$('#revision-source').hidden=REVISION_FORMAT!=='source';
  if(REVISION_FORMAT==='source'&&REVISION_COMMIT&&REVISION_SOURCE_COMMIT!==REVISION_COMMIT)
    loadRevisionSource(REVISION_COMMIT,REVISION_SEQ,DOC);
  // The comparison PDF is only built when that format is actually viewed - [변경 보기] goes straight to the source diff, so it never wastes a latexdiff build.
  if(REVISION_FORMAT==='pdf'&&REVISION_COMMIT&&REVISION_PDF_COMMIT!==REVISION_COMMIT){REVISION_PDF_COMMIT=REVISION_COMMIT;
    $('#revision-status').textContent='비교 PDF 상태를 확인하는 중입니다.'; loadRevisionPdf(REVISION_COMMIT,REVISION_SEQ,DOC);}
  syncRevisionWhole();
  if(REV_TARGET)revTargetNote();
}
function setViewMode(mode){
  const revisions=mode==='revisions'; document.body.classList.toggle('revision-open',revisions);
  $('#view-manuscript').setAttribute('aria-pressed',String(!revisions));
  $('#view-revisions').setAttribute('aria-pressed',String(revisions));
  if(!revisions)REV_TARGET=null;
  if(revisions)loadRevisions(); else{++REVISION_SEQ;clearRevisionPdf();$('#revision-pin').hidden=true;if(VEC.doc)vecSchedule(0);updateSectionStrip();}
}
async function loadRevisions(){
  const seq=++REVISION_SEQ,k=DOC,list=$('#revision-list'),out=$('#revision-diff'),tg=REV_TARGET;
  clearRevisionPdf();list.textContent='최근 변경사항을 읽는 중입니다.';out.textContent='';$('#revision-pin').hidden=!tg;
  if(tg)revTargetNote('변경사항을 읽는 중입니다.');
  let data; try{data=(await api(dq('/api/revisions',k),{what:'변경사항 읽기',silent:true})).data;}
  catch(e){if(seq===REVISION_SEQ)list.textContent='변경사항을 읽지 못했습니다.';return;}
  if(seq!==REVISION_SEQ||k!==DOC)return;
  if(!data.available){list.textContent='이 문서의 Git 변경사항을 볼 수 없습니다.';
    if(tg)revTargetNote(tg.region?'보기 전용 PDF 문서의 핀이라 Git 변경사항이 없습니다 — 고친 곳은 LaTeX 문서(본문 등)의 변경사항에서 찾으세요.':
      '이 문서는 Git 이력을 읽을 수 없어(Git 저장소가 아니거나 경로가 밖) 핀 자리를 변경과 맞출 수 없습니다.'); return;}
  if(!data.revisions.length){list.textContent='이 문서의 최근 변경사항이 없습니다.'; if(tg)revTargetNote('이 문서의 최근 12개 커밋에 변경이 없습니다.'); return;}
  list.innerHTML='<label class="sr-only" for="revision-select">비교할 커밋</label><select id="revision-select" aria-label="비교할 커밋">'+data.revisions.map(r=>'<option value="'+esc(r.id)+'">'+esc(r.subject)+' · '+esc(r.date)+' · '+esc(r.id.slice(0,8))+'</option>').join('')+'</select>';
  if(tg){const pick=await pickRevisionFor(tg,data.revisions,seq,k); if(seq!==REVISION_SEQ||k!==DOC||REV_TARGET!==tg)return;
    tg.commit=pick.id; tg.via=pick.via; tg.hit=pick.hit; showRevision(pick.id,'source'); return;}
  showRevision(data.revisions.some(r=>r.id===REVISION_COMMIT)?REVISION_COMMIT:data.revisions[0].id);
}
async function showRevision(id,format){
  const seq=++REVISION_SEQ,k=DOC;REVISION_COMMIT=id;REVISION_SOURCE_COMMIT='';REVISION_PDF_COMMIT='';clearRevisionPdf();
  const select=$('#revision-select');if(select)select.value=id;
  REVISION_SCOPE=null;REV_SCOPE.whole=REV_SCOPE.partial=REV_SCOPE.fallback=false;drawRevisionOther(null);
  $('#revision-diff').textContent='';$('#revision-file-row').hidden=true;$('#revision-warning').hidden=true;
  $('#revision-status').textContent='';
  setRevisionFormat(format||'pdf');
}
async function loadRevisionSource(id,seq,k){
  const out=$('#revision-diff');out.textContent='소스 변경 내용을 읽는 중입니다.';$('#revision-file-row').hidden=true;
  const tg0=REV_TARGET,pq=tg0&&!tg0.region?'&pin='+tg0.id:'';
  try{const r=(await api(dq('/api/revision-diff?commit='+encodeURIComponent(id)+pq,k),{what:'변경 내용 읽기',silent:true})).data;
    if(!revisionCurrent(seq,k,id))return;
    // v0.3: a pin's own hunks when it owns part of the commit; otherwise the whole commit exactly as before
    const sc=r.scope&&r.scope.mode==='pin'?r.scope:null;REVISION_SCOPE=r.scope||null;
    if(sc){REV_SCOPE.partial=true;syncRevisionWhole();}
    const cut='\n\n'+tr('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.');
    REVISION_WHOLE=sc?sc.diff+(sc.truncated?cut:''):(r.diff||tr('이 커밋에서 표시할 원고 텍스트 변경이 없습니다.'))+(r.truncated?cut:'');
    REVISION_FILES=revisionFiles(sc?sc.diff:(r.diff||''));drawRevisionOther(sc);
    const select=$('#revision-file');select.innerHTML='<option value="all">전체 파일</option>'+REVISION_FILES.map((f,i)=>'<option value="'+i+'">'+esc(f.name)+'</option>').join('');
    select.value='all';$('#revision-file-row').hidden=REVISION_FILES.length<2;REVISION_SOURCE_COMMIT=id;
    const tg=REV_TARGET,fi=tg?pinFileIndex(REVISION_FILES,tg.file):-1;
    if(fi>=0&&REVISION_FILES.length>1)select.value=String(fi);
    renderRevisionFile(); if(tg)revHighlight(tg);
  }catch(e){if(revisionCurrent(seq,k,id))out.textContent='소스 변경 내용을 읽지 못했습니다.';}
}
// ------------------------------------------------ [변경 보기] (docs/handbook/viewer.md §변경 보기): opens the changes tab from an awaiting-review/done pin.
// Commit selection: the commit hash (7+ characters) in the close-time reference (ref) > a commit whose subject contains the reference's PR number
// ('(#236)'/'pull request #236') > among the last 12 commits, the most recent one that touched the pin's file/lines (+-5 lines) > the most recent commit.
// Line matching exists only for the source diff - a line whose new-side line number falls within the pin's range is highlighted and scrolled to.
// The comparison PDF (latexdiff) has no SyncTeX mapping, so it only moves to roughly the pin's page.
let REV_TARGET=null,REVISION_PDF_COMMIT='';
function matchRevision(ref,revs){ref=String(ref||'');
  for(const m of ref.matchAll(/\b[0-9a-f]{7,40}\b/g)){const r=revs.find(x=>x.id.startsWith(m[0])); if(r)return {id:r.id,via:'sha',tok:m[0]};}
  for(const m of ref.matchAll(/#(\d+)/g)){const n=m[1],re=new RegExp('\\(#'+n+'\\)|pull request #'+n+'\\b|#'+n+'\\b');
    const r=revs.find(x=>re.test(x.subject||'')); if(r)return {id:r.id,via:'pr',tok:'#'+n};}
  return null;}
function pinFileIndex(files,file){file=String(file||''); let best=-1,len=0;
  files.forEach((f,i)=>{const n=f.name; if(n&&(file===n||file.endsWith('/'+n))&&n.length>len){best=i;len=n.length;}}); return best;}
function hunkRanges(text){const out=[]; for(const m of String(text||'').matchAll(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm)){
  const a=+m[1],n=m[2]===undefined?1:+m[2]; out.push([a,a+Math.max(n,1)-1]);} return out;}
function touchesPin(files,tg,slack){const i=pinFileIndex(files,tg.file); if(i<0)return false; slack=slack==null?5:slack;
  return hunkRanges(files[i].text).some(([a,b])=>b>=tg.lo-slack&&a<=tg.hi+slack);}
async function pickRevisionFor(tg,revs,seq,k){
  const m=matchRevision(tg.ref,revs); if(m)return m;
  if(!tg.region&&tg.file){for(const r of revs){if(seq!==REVISION_SEQ||k!==DOC)break;
    try{const d=(await api(dq('/api/revision-diff?commit='+encodeURIComponent(r.id),k),{what:'변경 내용 읽기',silent:true})).data;
      if(touchesPin(revisionFiles(d.diff||''),tg))return {id:r.id,via:'lines'};}catch(e){}}}
  return {id:revs[0].id,via:'latest'};}
function revTargetNote(msg){const tg=REV_TARGET,box=$('#revision-pin'); if(!tg){box.hidden=true;return;}
  const via={sha:tl('참조의 커밋 {tok}',{tok:tg.tokOf||''}),pr:tr('참조의 PR'),lines:tr('이 줄을 바꾼 가장 최근 커밋'),latest:tr('참조로 커밋을 찾지 못해 가장 최근 커밋')}[tg.via]||'';
  const where=tg.region?tl('쪽 {page} 영역',{page:tg.page}):tg.name+' '+rng(tg.lo,tg.hi);
  const sc=REVISION_FORMAT==='source'&&REVISION_SCOPE&&REVISION_SCOPE.mode==='pin'?REVISION_SCOPE:null;
  const scopeMsg=sc?tl('이 핀의 변경 {n}곳만 보입니다',{n:sc.hunks})+' ('+tr(sc.source==='changes'?'에이전트가 기록한 줄':'핀 자리로 추정')+') · ':'';
  let t=msg?tr(msg):scopeMsg+(REVISION_FORMAT==='pdf'?tl('비교 PDF에는 줄 대응이 없어 원고 {page}쪽 근처로만 옮겼습니다(삭제 문장이 끼어 쪽이 밀릴 수 있음). 정확한 줄은 [소스 diff]',{page:tg.page}):
    tr(tg.hit===false?'이 커밋의 diff에서 핀 범위를 찾지 못했습니다 — 가장 가까운 줄을 보입니다':
     tg.near?'핀 범위 줄 자체는 바뀌지 않았고 바로 곁(±5줄)이 바뀌었습니다 — 가장 가까운 줄을 보입니다':'강조한 줄이 핀 범위입니다'));
  const back=REV_BACK&&REV_BACK!==DOC&&docInfo(REV_BACK)?docInfo(REV_BACK).name:null;
  box.innerHTML='<span><b>'+esc(tl('핀 #{id}',{id:tg.id}))+'</b> · '+esc(where)+(tg.ref?' · '+esc(tl('참조 {ref}',{ref:tg.ref})):'')+(via?' · '+esc(via):'')+'</span><span class="rp-msg">'+esc(t)+'</span>'+
    '<button class="btn-sm" data-act="rev-back" data-tip="'+esc(back?tl('{name} 원고 보기로 돌아갑니다',{name:back}):tr('원고 보기로 돌아갑니다'))+'">'+esc(back?tl('{name}(으)로',{name:back}):tr('원고로'))+'</button>';
  box.hidden=false;}
function revHighlight(tg){const rows=$$('#revision-diff .rd-line'); let first=null;
  rows.forEach(el=>{if(!(el.classList.contains('rd-add')||el.classList.contains('rd-context')))return; const n=+el.querySelector('.rd-no').textContent;
    if(n>=tg.lo&&n<=tg.hi){el.classList.add('rd-pin'); if(!first)first=el;}});
  tg.hit=!!first||touchesPin(REVISION_FILES,tg,5); tg.near=!first&&tg.hit;   // when only a neighboring line changed, it's never described as "the highlighted line" (there is none)
  if(!first){const f=pinFileIndex(REVISION_FILES,tg.file); if(f<0)tg.hit=false;
    else{let best=null,dist=Infinity; rows.forEach(el=>{const n=+el.querySelector('.rd-no').textContent; if(!n)return; const d=Math.min(Math.abs(n-tg.lo),Math.abs(n-tg.hi)); if(d<dist){dist=d;best=el;}}); first=best;}}
  revTargetNote(); if(first)requestAnimationFrame(()=>first.scrollIntoView({block:'center'}));}
function findAnyPin(id){return OPEN_ALL.find(p=>p.id===id)||REVIEW_ALL.find(p=>p.id===id)||DONE_ALL.find(p=>p.id===id)||null;}
let REV_BACK=null;   // the document being viewed when [변경 보기] was pressed - [원고로] returns to that document (QA: opening it from a cover-letter pin used to leave you stuck on the cover letter)
async function showChange(id){const p=findAnyPin(id); if(!p)return; const k=pdoc(p); if(!document.body.classList.contains('revision-open'))REV_BACK=DOC;
  if(k!==DOC&&docInfo(k)){await switchDoc(k); if(DOC!==k)return;}
  REV_TARGET={id:p.id,file:p.file||p.pdf||'',name:p.name||String(p.file||p.pdf||'').split('/').pop(),lo:p.lo,hi:p.hi,page:p.page,ref:p.close_ref||'',region:isRegion(p)};
  const m=/\b[0-9a-f]{7,40}\b/.exec(REV_TARGET.ref); REV_TARGET.tokOf=m?m[0]:'';
  if(LAYOUT==='narrow')setSide(false);
  if(document.body.classList.contains('revision-open'))loadRevisions(); else setViewMode('revisions');}
async function loadRevisionPdf(id,seq,k){
  const statusBox=$('#revision-status'),warningBox=$('#revision-warning'),tg=REV_TARGET;
  // v0.3: for a pin, the comparison is old + only that pin's hunks unless [커밋 전체 비교] is on or that build already failed
  const pin=tg&&!tg.region&&!REV_SCOPE.whole&&!REV_SCOPE.fallback?tg.id:null,pq=pin?'&pin='+pin:'';
  try{
    let status=(await api('/api/revision-build',{method:'POST',body:pin?{commit:id,doc:k,pin}:{commit:id,doc:k},what:'비교 PDF 만들기',silent:true})).data;
    if(!revisionCurrent(seq,k,id))return;
    if(pin&&status.scope){REV_SCOPE.partial=status.scope==='pin';syncRevisionWhole();}
    for(let tries=0;status.state==='running'&&tries<180;tries++){
      if(!revisionCurrent(seq,k,id))return;
      statusBox.textContent='선택 커밋의 비교 PDF를 만드는 중입니다. 원고와 핀은 그대로 사용할 수 있습니다.';
      await new Promise(resolve=>setTimeout(resolve,1000));
      if(!revisionCurrent(seq,k,id))return;
      status=(await api(dq('/api/revision-build?commit='+encodeURIComponent(id)+pq,k),{what:'비교 PDF 상태',silent:true})).data;
    }
    if(!revisionCurrent(seq,k,id))return;
    if(pin&&status.scope==='pin'&&status.state==='error'){   // the pin's hunks alone did not compile: show the whole commit, say so in one line
      REV_SCOPE.fallback=true;syncRevisionWhole();return loadRevisionPdf(id,seq,k);}
    if(status.state!=='ready')throw new Error(status.error||tr(status.state==='running'?'비교 PDF 대기 시간이 지났습니다. 다시 열어 재시도하세요.':'비교 PDF를 만들지 못했습니다.'));
    if(status.head&&status.head!==id)throw new Error(tr('요청한 커밋과 비교 PDF의 커밋이 다릅니다.'));
    const warnings=Array.isArray(status.warnings)?status.warnings:[];
    warningBox.hidden=!warnings.length;warningBox.querySelector('summary').textContent=tl('빌드 경고 {n}건 보기',{n:warnings.length});
    warningBox.querySelector('pre').textContent=warnings.join('\n');warningBox.open=false;
    statusBox.textContent='비교 PDF를 읽는 중입니다.';
    const response=await fetch(dq('/api/revision-pdf?commit='+encodeURIComponent(id)+pq,k));
    if(!response.ok)throw new Error(tl('비교 PDF를 열지 못했습니다 (HTTP {status}).',{status:response.status}));
    const bytes=new Uint8Array(await response.arrayBuffer());
    if(!revisionCurrent(seq,k,id))return;
    const lib=VEC.lib||await import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V);
    lib.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V;
    const loading=lib.getDocument({data:bytes,isEvalSupported:false,useWasm:false,enableXfa:false});REV_PDF.loading=loading;
    const pdf=await loading.promise;
    if(!revisionCurrent(seq,k,id)){try{loading.destroy();}catch(e){}return;}
    REV_PDF.doc=pdf;
    const lead=pin&&status.scope==='pin'?tl('핀 #{id}의 변경만',{id:pin})+' · ':REV_SCOPE.fallback&&tg?tr('이 핀의 변경만으로는 비교 PDF를 만들지 못해 커밋 전체를 비교합니다')+' · ':'';
    statusBox.textContent=lead+tl('첫 부모 {base} → {head} · {n}쪽 · 읽기 전용 · 빨강 삭제 / 파랑 추가',{base:String(status.base||'').slice(0,8),head:id.slice(0,8),n:pdf.numPages});
    const box=$('#revision-pdf');box.innerHTML=Array.from({length:pdf.numPages},(_,i)=>'<div class="revision-page" data-page="'+(i+1)+'" aria-label="'+esc(tl('비교 PDF {page}쪽',{page:i+1}))+'"></div>').join('');
    if(window.IntersectionObserver){REV_PDF.observer=new IntersectionObserver(rows=>{for(const row of rows)if(row.isIntersecting){
      REV_PDF.observer.unobserve(row.target);renderRevisionPage(row.target,pdf,seq,k,id);
    }},{root:box,rootMargin:'600px 0px'});box.querySelectorAll('.revision-page').forEach(el=>REV_PDF.observer.observe(el));}
    else for(const el of box.querySelectorAll('.revision-page'))renderRevisionPage(el,pdf,seq,k,id);
    if(REV_TARGET&&REV_TARGET.page){const el=box.querySelector('.revision-page[data-page="'+Math.min(REV_TARGET.page,pdf.numPages)+'"]'); if(el)el.scrollIntoView({block:'start'}); revTargetNote();}
  }catch(e){if(revisionCurrent(seq,k,id)){
    statusBox.textContent=tl('비교 PDF: {error} 소스 diff에서 변경 내용을 확인할 수 있습니다.',{error:e&&e.message?e.message:tr('표시하지 못했습니다.')});
  }}
}
async function renderRevisionPage(el,pdf,seq,k,id){
  if(el.dataset.state||!revisionCurrent(seq,k,id))return;el.dataset.state='loading';
  try{const page=await pdf.getPage(Number(el.dataset.page));if(!revisionCurrent(seq,k,id))return;
    const base=page.getViewport({scale:1}),cssWidth=Math.min(780,$('#revision-pdf').clientWidth-24),scale=Math.max(0.25,cssWidth/base.width);
    const viewport=page.getViewport({scale}),dpr=Math.min(2,window.devicePixelRatio||1),canvas=document.createElement('canvas');
    canvas.width=Math.ceil(viewport.width*dpr);canvas.height=Math.ceil(viewport.height*dpr);
    canvas.style.width=viewport.width+'px';canvas.style.height=viewport.height+'px';el.style.minHeight=viewport.height+'px';el.append(canvas);
    const task=page.render({canvasContext:canvas.getContext('2d'),viewport,transform:[dpr,0,0,dpr,0,0]});REV_PDF.tasks.add(task);
    try{await task.promise;el.dataset.state='ready';}finally{REV_PDF.tasks.delete(task);}
  }catch(e){if(revisionCurrent(seq,k,id)){$('#revision-status').textContent='일부 비교 PDF 쪽을 그리지 못했습니다. 소스 diff를 확인할 수 있습니다.';el.dataset.state='error';}}
}
function drawDocsMenu(){
  $('#docs-menu-list').innerHTML=DOCS.map(d=>{const on=d.key===DOC;
    return '<button class="dm-item'+(on?' on':'')+'" role="option" aria-selected="'+on+'" data-act="doc" data-doc="'+esc(d.key)+'" data-close="1">'+
      '<span class="tx"><span class="nm">'+esc(d.name)+(on?ic('check'):'')+'</span><span class="ph">'+esc(d.path)+'</span></span>'+docBadge(d)+'</button>';}).join('');}
function openDocsMenu(){const d=$('#docs-menu'); if(d.open)return; hideTip(); drawDocsMenu(); d.showModal();
  const on=d.querySelector('.dm-item.on'); if(on)on.focus();}
// Viewed position: page/fraction anchored at the top, page width, whether zoomed manually in compact, horizontal scroll. Kept in sessionStorage so it survives a reload.
function saveView(){if(!DOC||!META||!$('#doc .pg'))return; const a=topAnchor();
  VIEW_BY.set(DOC,{page:a?a.page:1,frac:a?a.frac:0,w:W,zoomed:ZOOMED,sl:$('#left').scrollLeft,lay:LAYOUT});
  if(multiDoc()){try{sessionStorage.setItem('pinDocView',JSON.stringify(Array.from(VIEW_BY.entries())));}catch(e){}}}
function loadViews(){if(!multiDoc())return; try{const a=JSON.parse(sessionStorage.getItem('pinDocView')||'[]');
  if(Array.isArray(a))a.forEach(x=>{if(Array.isArray(x)&&docInfo(x[0])&&x[1]&&typeof x[1]==='object')VIEW_BY.set(x[0],x[1]);});}catch(e){}}
// The page width is decided first (buildDoc builds pages using W). Only a width viewed in the same layout is restored - so a width fit for a folded screen is never applied on desktop.
function applyViewWidth(v){if(v&&typeof v.w==='number'&&v.lay===LAYOUT&&(LAYOUT==='wide'||v.zoomed)){W=v.w; ZOOMED=LAYOUT!=='wide'&&!!v.zoomed; return true;}
  ZOOMED=false; return false;}
function restoreView(v){if(!v)return; restoreAnchor({page:v.page,frac:v.frac}); if(typeof v.sl==='number')$('#left').scrollLeft=v.sl;}
addEventListener('pagehide',saveView);
// Switches documents. Remembers the current document's viewed position, and cancels any in-progress selection/re-place-location (a note's draft text is kept).
// If a meta cache exists, that document is drawn immediately without waiting, then the latest meta is fetched in the background, and pages are swapped only if the build changed.
async function switchDoc(k){
  if(!k||k===DOC||!docInfo(k))return; const seq=++SWITCHSEQ;
  if(document.body.classList.contains('revision-open'))setViewMode('manuscript');
  saveView(); cancelRepick(); if(CUR||!$('#composer').hidden)cancelSelection(false);
  if(EDIT&&!editDirty())cancelEdit();
  let m=META_BY.get(k),cached=!!m;
  if(!m){try{m=(await api(dq('/api/meta',k),{what:'문서 열기'})).data;}catch(e){return;} if(seq!==SWITCHSEQ)return;}
  DOC=k; META=m; META_BY.set(k,m); savePrefs({lastDoc:k}); setHash(k);
  hideTip(); showDoc(VIEW_BY.get(k));
  if(cached){try{const f=(await api(dq('/api/meta',k),{what:'문서 열기',silent:true})).data;
    if(seq===SWITCHSEQ&&DOC===k){const changed=f.pages_build!==META.pages_build||f.pages.length!==META.pages.length;
      META_BY.set(k,f); if(changed)await refreshDoc(); else{META=f; drawMeta();}}}catch(e){}}
}
// Redraws the screen from the current META (tab switching). The build chip, error panel, and auto-polling baseline are all switched to that document's values too.
function showDoc(v){
  drawMeta(); const hadW=applyViewWidth(v); buildDoc(); if(!hadW)autoW(); restoreView(v);
  if(!v&&$('#left'))$('#left').scrollTop=0;
  PINS=OPEN_ALL.filter(p=>pdoc(p)===DOC); drawPins(); marks(); drawDocTabs();
  $('#outline-items').textContent=tr('PDF 목차를 읽는 중입니다.');
  if(document.body.classList.contains('revision-open'))loadRevisions();
  vecOpen();
  if(BUILD_TIMER){clearInterval(BUILD_TIMER);BUILD_TIMER=null;} $('#build-chip').hidden=true; $('#btn-rebuild').disabled=false;
  LAST_BUILD_SEQ=(typeof META.build_seq==='number')?META.build_seq:0; LAST_BUILD_ERR=BUILD_ERR_BY.get(DOC)||null;
  if(LAST_BUILD_ERR)hideBuildErr(); else{$('#build-err').hidden=true; $('#build-err-chip').hidden=true;}
  BUILD_BOOTED=true; if(BUILD_INFLIGHT)BUILD_INFLIGHT.then(()=>pollBuild()); else pollBuild();   // if a previous document's request is still in flight, queue after it
  docTitle(false);
}
// The tab title: 'Limn · <label> · <document> · 열린 N' (+ ' · 검토 N' once the pin list knows the review count).
function docTitle(review){if(!META)return;
  document.title='Limn · '+(META.label?META.label+' · ':'')+(multiDoc()?META.doc_name||META.main:META.main)+' · '+tl('열린 {n}',{n:PINS.length})+
    (review&&REVIEW_ALL.length?' · '+tl('검토 {n}',{n:REVIEW_ALL.length}):'');}
function cycleDoc(step){if(!multiDoc())return; const i=DOCS.findIndex(d=>d.key===DOC);
  switchDoc(DOCS[(i+step+DOCS.length)%DOCS.length].key);}
window.addEventListener('hashchange',()=>{const k=hashDoc(); if(k&&k!==DOC&&docInfo(k))switchDoc(k);});
// A #number/[보기]/[수정] on another document's pin: switches to that document, then calls then again (used by jumpPin/openEdit at the very top). Returns true if it switched.
function viaDoc(id,then){const p=OPEN_ALL.find(x=>x.id===id);
  if(!p||pdoc(p)===DOC||!docInfo(pdoc(p)))return false;
  const k=pdoc(p); switchDoc(k).then(()=>{if(DOC===k)then(id);}); return true;}

// ------------------------------------------------ Document
async function boot(){i18nStart();
  // A link /#doc=<key>&pin=<n>[&act=restore] (a notification clicked with no tab open) is read first: the boot below rewrites the
  // hash to #doc=<key> on an instance with several documents, which used to lose pin= (0.2.1 and earlier).
  const link=takeLinkHash();
  applyTheme(); applyLayout(); initDiffWrap();
  // There's no keyboard shortcut on a touch device - "핀 저장 Ctrl+Enter" would just get clipped at phone width.
  $('#btn-save').innerHTML=saveBtnLabel();
  await loadDocs(); DOC=initialDoc();
  try{META=(await api(dq('/api/meta'),{what:'화면 정보 읽기'})).data;}catch(e){return;}
  if(META.doc)DOC=META.doc; META_BY.set(DOC,META); loadViews(); const v=VIEW_BY.get(DOC);
  if(multiDoc()){setHash(DOC); savePrefs({lastDoc:DOC});}
  drawMeta(); applySideWidth(); applyOutlineState(); const hadW=applyViewWidth(v); buildDoc(); if(!hadW)autoW(); vecBoot(); await loadPins();
  restoreView(v); drawDocTabs();
  if(MQ_COARSE.matches)coach('touch','PDF를 길게 누르면 그 문단을 고릅니다 · [선택]을 켜면 끌어서 고릅니다');
  LAST_PINS_REV=META.pins_rev; LAST_SRC_MTIME=META.src_sig||META.src_mtime;
  LAST_BUILD_SEQ=(typeof META.build_seq==='number')?META.build_seq:0;   // the build count this tab has already "seen"
  (META.docs||[]).forEach(d=>DOC_SEQ.set(d.key,d.build_seq));
  startLightPolling(); startBuildPolling();
  drawNotify(); if(prefs().notify&&notifySupported()&&notifyPerm()==='granted')notifyRegister();
  if(link.pin)openPinFromLink(link.doc||DOC,link.pin,link.restore);
}
function builtAtEpoch(s){const t=Date.parse(String(s||'').replace(' ','T')); return isNaN(t)?null:t/1000;}
// The "manuscript modified" badge - judged only from numbers the server provides (stale_build, src_age_s), independent of the browser's clock/timezone.
// Only a legacy response with no stale_build falls back to comparing src_mtime/build_src_mtime (both server epochs).
function updateStaleBadge(m){
  const badge=$('#meta-stale'), btn=$('#btn-rebuild');
  let stale;
  if(typeof m.stale_build==='boolean')stale=m.stale_build;
  else{const ref=(typeof m.build_src_mtime==='number')?m.build_src_mtime:builtAtEpoch(META&&META.built_at);
    stale=ref!=null&&typeof m.src_mtime==='number'&&m.src_mtime>ref+2;}
  if(!stale){badge.hidden=true; btn.classList.remove('btn-default'); return;}
  const age=(typeof m.src_age_s==='number')?m.src_age_s:(Date.now()/1000-m.src_mtime);
  const mins=Math.max(0,Math.round(age/60));
  badge.hidden=false; badge.textContent=tl('원고 수정됨 · {n}분 전',{n:mins});
  btn.classList.add('btn-default');
}
const SYNC_REASON={not_git:'Git 저장소가 아닙니다',no_upstream:'main 업스트림이 없습니다',not_main:'현재 체크아웃이 main이 아닙니다',
  dirty:'로컬에 커밋되지 않은 수정이 있습니다',diverged:'로컬 main과 원격 main이 갈라졌습니다',
  fetch_failed:'원격을 확인하지 못했습니다',fetch_timeout:'원격 확인 시간이 초과됐습니다',
  status_failed:'로컬 수정 상태를 읽지 못했습니다',unexpected:'동기화 중 오류가 났습니다',
  building:'다른 PDF 빌드가 진행 중입니다',build_failed:'새 원고의 PDF 빌드가 실패했습니다'};
function updateSyncBadge(s){const b=$('#meta-sync'); if(!b)return;
  if(!s||s.state==='disabled'||s.state==='current'){b.hidden=true; return;}
  b.hidden=false; b.classList.toggle('badge-warning',s.state==='blocked'||s.state==='error');
  const reason=tr(SYNC_REASON[s.reason]||s.reason||'');
  b.textContent=tr(s.state==='updating'?'최신 main PDF 반영 중':s.state==='updated'?'최신 main 반영됨':
    s.state==='deferred'?'빌드 뒤 main 확인':s.state==='checking'?'main 확인 중':'main 동기화 확인 필요');
  b.dataset.tip=reason?(b.textContent+' · '+reason+' · '+tr('기존 PDF가 보일 수 있습니다')):b.textContent;
}
function isViewer(){return !!(typeof META!=='undefined'&&META&&META.me&&META.me.role==='viewer');}
// A state change the viewer role cannot make (the server answers 403 anyway): say so once instead of sending it.
function viewerBlocked(){if(!isViewer())return false; toast('보기 권한(viewer)만 있는 계정이라 바꿀 수 없습니다','warn'); return true;}
function drawMeta(){
  document.body.classList.toggle('view-only',!!META.view_only);
  document.body.classList.toggle('role-viewer',isViewer());
  $('#meta-main').textContent=META.main; $('#meta-pages').textContent=tl('{n}쪽',{n:META.pages.length});
  $('#meta-head').textContent=META.head; $('#meta-built').textContent=String(META.built_at||'').slice(0,16).replace('T',' ');
  const me=META.me||{};
  $('#me').innerHTML=avatar(me)+'<span class="au-n">'+esc(who(me))+'</span>';
  $('#me').dataset.tip=tl('지금 이 화면을 쓰는 사람: {name}. 핀을 저장·수정·완료하면 이 이름으로 기록됩니다',{name:(isAgent(me)?who(me):me.name||'')+(me.login&&me.login!=='local'?' ('+me.login+')':'')});
  updateStaleBadge(META);
  updateSyncBadge(META.sync);
  $('#help-pins-md').textContent=META.pins_md||'';
  // In compact, #bar2's file/commit/time/author line is hidden and shown as a single line inside [⋯] instead (so a long filename never overflows).
  $('#more-info').textContent=[META.main,tl('{n}쪽',{n:META.pages.length}),META.head,String(META.built_at||'').slice(0,16).replace('T',' '),
    tl('나: {name}',{name:who(me)})].filter(Boolean).join(' · ');
}

// ------------------------------------------------ Auto sync (P0b-02) - lightweight meta polling
let LAST_PINS_REV=null,LAST_SRC_MTIME=null,POLL_FAILS=0,LIGHT_TIMER=null,LIGHT_INFLIGHT=null;
// Single-flight: same pattern as pollBuild - even if visibilitychange/focus/the 5-second timer overlap and
// call this together (e.g. focus returning at the same moment as a tab switch), /api/meta and loadPins only go out once (observed defect: overlapping calls fired loadPins 3 times).
function pollLight(){
  if(document.hidden)return Promise.resolve();   // a heavy refresh (including redrawing the list) is never sent while the tab is hidden
  if(LIGHT_INFLIGHT)return LIGHT_INFLIGHT;
  LIGHT_INFLIGHT=pollLightOnce().finally(()=>{LIGHT_INFLIGHT=null;});
  return LIGHT_INFLIGHT;
}
// While the tab is hidden, the list is never redrawn (observed defect: a hidden tab received no notifications at all), but if notifications
// are on (notifyOn), a light (slow - the browser throttles it anyway) /api/meta?light=1 call is still made just to surface events as notifications.
// This is a notification-only branch splitting off at the same point as pollLight's document.hidden bailout - it never touches the screen.
let NOTIFY_HIDDEN_TIMER=null,NOTIFY_HIDDEN_INFLIGHT=null;
const NOTIFY_HIDDEN_INTERVAL_MS=20000;
function pollHiddenNotify(){
  if(!document.hidden||!notifyOn())return Promise.resolve();
  if(NOTIFY_HIDDEN_INFLIGHT)return NOTIFY_HIDDEN_INFLIGHT;
  NOTIFY_HIDDEN_INFLIGHT=pollHiddenNotifyOnce().finally(()=>{NOTIFY_HIDDEN_INFLIGHT=null;});
  return NOTIFY_HIDDEN_INFLIGHT;
}
async function pollHiddenNotifyOnce(){
  let d;
  try{d=(await api(dq('/api/meta?light=1')+notifyQuery(),{what:'알림 확인',silent:true})).data;}catch(e){return;}
  if(document.hidden)notifyHandle(d);   // if the tab came back while waiting, normal polling has already handled it
}
// If the tab hides while notifications are on, the slow timer is started; it's stopped when the tab returns or notifications are turned off (avoids duplicate polling).
function syncHiddenNotifyTimer(){
  clearInterval(NOTIFY_HIDDEN_TIMER); NOTIFY_HIDDEN_TIMER=null;
  if(document.hidden&&notifyOn()){pollHiddenNotify(); NOTIFY_HIDDEN_TIMER=setInterval(pollHiddenNotify,NOTIFY_HIDDEN_INTERVAL_MS);}
}
async function pollLightOnce(){
  let d; const k=DOC;
  try{d=(await api(dq('/api/meta?light=1')+notifyQuery(),{what:'상태 확인',silent:true})).data; POLL_FAILS=0;}
  catch(e){POLL_FAILS++; if(POLL_FAILS>=2)$('#conn-lost').hidden=false; return;}
  $('#conn-lost').hidden=true;
  notifyHandle(d);                      // browser notifications - independent of the document (handled first even mid document-switch)
  if(k!==DOC)return;                    // the document changed while waiting - the screen is never painted with a stale document's state
  updateStaleBadge(d); updateSyncBadge(d.sync); noteOtherDocs(d.docs);
  // With multiple documents, re-read even if src_sig (per-document src_mtime) changed - another document's manuscript changing shifts that document's pins' lines too.
  const sig=d.src_sig||d.src_mtime;
  if(LAST_PINS_REV!==null&&(d.pins_rev!==LAST_PINS_REV||sig!==LAST_SRC_MTIME)) await loadPins();
  LAST_PINS_REV=d.pins_rev; LAST_SRC_MTIME=sig;
  // A build started via curl by another session/agent is also caught through light meta's build.state - the 1-second poll only
  // runs during that (or when this tab itself pressed rebuild()).
  if(d.build&&d.build.state==='running'&&!BUILD_TIMER)pollBuild();
  // If build_seq (number of finished builds) differs from what this tab has seen, it means a build started and finished entirely
  // within a 5-second polling gap, never observed as "running" - the details are fetched to sync up the screen/banner/chip.
  else if(typeof d.build_seq==='number'&&d.build_seq!==LAST_BUILD_SEQ)pollBuild();
}
// Reflects another document's staleness/in-progress build on its tab, and if that document's build finished in the background, notifies and then drops the meta cache (a fresh page when you switch back).
function noteOtherDocs(list){if(!Array.isArray(list)||!list.length)return; let redraw=false;
  list.forEach(n=>{const d=docInfo(n.key); if(!d)return;
    if(d.stale_build!==n.stale_build||d.building!==n.building){d.stale_build=n.stale_build; d.building=n.building; redraw=true;}
    const was=DOC_SEQ.get(n.key); DOC_SEQ.set(n.key,n.build_seq);
    if(n.key===DOC||was===undefined||was===n.build_seq)return;
    META_BY.delete(n.key); redraw=true;
    if(n.last_state==='ok')toast(tl(d.view_only?'{name} PDF 쪽을 새로 그렸습니다':'{name} PDF 재빌드 완료',{name:d.name}),'ok',{label:'열기',tip:'그 문서로 바꿉니다',fn:()=>switchDoc(n.key)});
    else if(n.last_state==='ok_errors'||n.last_state==='fail')toast(tl(n.last_state==='fail'?'{name} 빌드 실패':'{name} 빌드에 LaTeX 오류',{name:d.name}),n.last_state==='fail'?'err':'warn',{label:'열기',tip:'그 문서로 바꿔 오류를 봅니다',fn:()=>switchDoc(n.key)});});
  if(redraw)drawDocTabs();}
function startLightPolling(){
  clearInterval(LIGHT_TIMER); LIGHT_TIMER=setInterval(pollLight,5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollLight(); syncHiddenNotifyTimer();});
  window.addEventListener('focus',()=>pollLight());
  syncHiddenNotifyTimer();   // catches it right away if already hidden at boot (a rare case) and notifications are on
}
// This tab's own close/drop/reopen/restore already showed a local toast, so the next loadPins()'s
// diffToast never announces the same transition again - only the first diffToast judgment right after markMine(id) is swallowed
// (consumeMine removes it as soon as it's confirmed), and if that judgment hasn't arrived after 10 seconds (e.g. a lost response), it's
// given up on and subsequent values are announced normally. An action from another tab isn't in this map, so it's shown as usual.
const MY_ACTIONS=new Map();
function markMine(id){MY_ACTIONS.set(id,Date.now()+10000);}
function consumeMine(id){const until=MY_ACTIONS.get(id); if(until===undefined)return false;
  MY_ACTIONS.delete(id); return Date.now()<=until;}
function diffToast(prev,d,dropped){
  // prev is only the "open pins" this tab saw last time (PINS never holds done ones). d is every open+closed
  // pin (all=1) from this GET - if an id that was in prev is also in d with done=true, it was completed; if it's
  // not in d at all (neither open nor closed), it was dropped. The old implementation never distinguished the
  // two and announced everything as "completed" - if a co-author deleted a pin, the author's screen showed "#N 이 완료되었습니다" (observed).
  if(!prev||!prev.length)return;
  const byId=new Map(prev.map(p=>[p.id,p]));
  const known=new Map((d||[]).map(p=>[p.id,p]));
  const dropById=new Map((dropped||[]).map(p=>[p.id,p]));
  const closed=[],droppedIds=[],reviewed=[];
  byId.forEach((_,id)=>{const n=known.get(id);
    if(n&&n.done){if(!consumeMine(id))(n.review?reviewed:closed).push(id);}
    else if(!n){if(!consumeMine(id))droppedIds.push(id);}});
  if(closed.length)toast(tl('#{ids} 이 완료되었습니다',{ids:closed.join(', #'),n:closed.length}),'ok');
  if(reviewed.length)toast(tl('#{ids} 이 검토 대기로 넘어왔습니다 — 결과를 보고 [확인]하세요',{ids:reviewed.join(', #'),n:reviewed.length}),'ok',null,{keys:reviewed.map(i=>'review_requested:'+i)});
  droppedIds.forEach(id=>{const rec=dropById.get(id),nm=rec?who(rec.dropped_by):'';
    toast(tl('#{id} 을 {name} 가 삭제함',{id,name:nm||tr('다른 세션')}),'warn',{label:'되살리기',fn:()=>restorePin(id)},{keys:['dropped:'+id]});});
  (d||[]).filter(p=>!p.done).forEach(p=>{const was=byId.get(p.id); if(!was)return;
    if(!was.stale&&p.stale){toast(tl('#{id} 위치를 잃었습니다',{id:p.id}),'warn');return;}
    const m=/^moved ([+-]\d+)$/.exec(p.sync||''),wm=/^moved ([+-]\d+)$/.exec(was.sync||'');
    if(m&&(!wm||wm[1]!==m[1]))toast(tl('#{id} 줄 {delta} 이동',{id:p.id,delta:m[1]}),'ok');});
}

// Announces when a pin that was awaiting review gets confirmed (done) or reopened elsewhere. An action this tab performed (markMine) is swallowed.
function pinState(p){return (p&&p.state)||(p&&p.done?(p.review?'review':'done'):'open');}
function reviewToast(prev,d){if(!prev||!prev.length)return; const known=new Map((d||[]).map(p=>[p.id,p]));
  prev.forEach(p=>{const n=known.get(p.id); if(!n)return; const st=pinState(n); if(st==='review')return; if(consumeMine(p.id))return;
    if(st==='done')toast(tl('#{id} 확인됨',{id:p.id})+(n.confirmed_by?' · '+who(n.confirmed_by):''),'ok');
    else toast(tl('#{id} 다시 열림',{id:p.id})+(n.reopened_by?' · '+who(n.reopened_by):''),'warn',null,{keys:['reopened:'+p.id]});});}

// ------------------------------------------------ Browser notifications (docs/handbook/viewer.md §브라우저 알림) - only while the tab is alive
// Turned on per device (pinPrefs.notify). Notification.requestPermission() is only ever called from the [알림 켜기] click. The server
// carries "events addressed to the current identity" in the 5-second poll (/api/meta?light=1&ev=<cursor>), and this tab shows them as
// notifications. The cursor (pinNotifyCursor) is kept in this browser's localStorage, so a reload or two tabs never announce the same
// event twice. Display always goes through the service worker's showNotification() (Chrome on Android blocks new Notification()); tag is
// the pin number, so the same pin collapses into one slot. If the tab is visible and focused, a toast is shown instead of a notification.
// This only works in a secure context (an https tailnet address, or http://127.0.0.1/localhost) - the browser blocks plain http on other hosts.
const NOTIFY_RANK={dropped:6,assigned:5,mention:4,reopened:3,review_requested:2,replied:1};
let SW_REG=null;
function notifySupported(){return !!(window.isSecureContext&&'serviceWorker' in navigator&&'Notification' in window);}
function notifyPerm(){return 'Notification' in window?Notification.permission:'unsupported';}
function notifyOn(){return !!prefs().notify&&notifySupported()&&notifyPerm()==='granted';}
function notifyCursor(){const v=parseInt(localStorage.getItem('pinNotifyCursor')||'',10); return isNaN(v)?null:v;}
function setNotifyCursor(v){const c=notifyCursor(); if(c==null||v>c)try{localStorage.setItem('pinNotifyCursor',String(v));}catch(e){}}
function notifyQuery(){if(!notifyOn())return ''; const c=notifyCursor(); return c==null?'':'&ev='+c;}
// Picks what to notify about (a pure function): after the cursor, addressed to me (to), not my own doing. One per pin - mention > reopen > awaiting review > reply, ties go to the later one.
function pickNotifications(evs,me,cursor){const login=me&&me.login; if(!login||login==='local')return [];
  const by=new Map();
  (evs||[]).forEach(e=>{if(!(e.seq>(cursor==null?-1:cursor)))return; if(!NOTIFY_RANK[e.type])return;
    if(!(e.to||[]).includes(login)||(e.by&&e.by.login===login))return;
    const o=by.get(e.pin); if(!o||NOTIFY_RANK[e.type]>NOTIFY_RANK[o.type]||(NOTIFY_RANK[e.type]===NOTIFY_RANK[o.type]&&e.seq>o.seq))by.set(e.pin,e);});
  return Array.from(by.values()).sort((a,b)=>a.seq-b.seq);}
function notifyText(e){const nm=who(e.by)||tr('누군가'),ex=String(e.excerpt||'').split('\n')[0].slice(0,80),q={name:nm,text:ex};
  const body={mention:tl('{name}님이 불렀습니다: {text}',q),review_requested:tl('검토 대기: {text}',{text:ex||tr('설명 없이 닫힘')}),
    replied:tl('{name}님 답글: {text}',q),reopened:ex?tl('{name}님이 다시 열었습니다: {text}',q):tl('{name}님이 다시 열었습니다',q),
    assigned:tl('{name}님이 담당으로 지정했습니다: {text}',q),dropped:tl('{name}님이 삭제했습니다: {text}',q)}[e.type]||ex;
  return {title:tl('핀 #{id}',{id:e.pin})+' · '+(e.doc_name||e.doc||(META&&META.label)||''),body};}
async function notifyShow(e){const t=notifyText(e);
  if(document.visibilityState==='visible'&&document.hasFocus()){
    const act=e.type==='dropped'?(isViewer()?{label:'열기',tip:'휴지통에서 봅니다',fn:()=>openPinFromLink(e.doc,e.pin)}:{label:'되살리기',tip:'휴지통에서 같은 번호로 되살립니다',fn:()=>restorePin(e.pin)})
      :{label:'열기',tip:'그 핀으로 갑니다',fn:()=>openPinFromLink(e.doc,e.pin)};
    toast(t.title+' — '+t.body,e.type==='dropped'?'warn':'ok',act,{keys:[e.type+':'+e.pin],rank:2});return;}
  try{const reg=SW_REG||await navigator.serviceWorker.ready;
    await reg.showNotification(t.title,{body:t.body,tag:'pin-'+e.pin,icon:(document.querySelector('link[rel=icon]')||{}).href,
      actions:e.type==='dropped'&&!isViewer()?[{action:'restore',title:tr('되살리기')}]:[],   // [되살리기] on "X deleted your pin" (the service worker hands it to this tab)
      data:{pin:e.pin,doc:e.doc,url:'/#doc='+encodeURIComponent(e.doc||'')+'&pin='+e.pin}});}catch(err){}}
function notifyHandle(d){if(!d||typeof d.ev_seq!=='number')return;
  if(!notifyOn())return;
  const c=notifyCursor(); if(c==null){setNotifyCursor(d.ev_seq); return;}   // first time enabled in this browser - never floods with a backlog of past events
  if(!Array.isArray(d.events)){if(d.ev_seq<c)try{localStorage.setItem('pinNotifyCursor',String(d.ev_seq));}catch(e){}return;}
  const list=pickNotifications(d.events,META&&META.me,notifyCursor());   // only what's after it, if another tab just advanced the cursor
  const top=d.events.reduce((m,e)=>Math.max(m,e.seq||0),c); setNotifyCursor(top);
  list.forEach(notifyShow);}
async function notifyRegister(){if(!notifySupported())return null;
  try{SW_REG=await navigator.serviceWorker.register('/sw.js',{scope:'/'}); return SW_REG;}catch(e){return null;}}
// A local identity (no tailnet login) never gets events from the server's events_since() at all (§@태그·사람·이벤트), so
// notifications would never arrive - since getting browser permission wouldn't help, turning it on is blocked outright and the reason is shown.
function isLocalIdentity(){const me=META&&META.me; return !me||!me.login||me.login==='local';}
function notifyState(){if(isLocalIdentity())return 'local'; if(!notifySupported())return 'unsupported'; const pm=notifyPerm();
  if(pm==='denied')return 'blocked'; return prefs().notify&&pm==='granted'?'on':'off';}
function drawNotify(){const st=notifyState(),b=$('#btn-notify'),m=$('#m-notify');
  const lab={on:'알림: 켜짐',off:'알림: 꺼짐',blocked:'알림: 브라우저에서 차단됨',unsupported:'알림: 이 주소에서는 안 됨',local:'알림: 테일넷 주소에서만'}[st];
  const tip={on:'이 기기에서 켜져 있습니다. 누르면 끕니다',off:'누르면 이 기기에서 켭니다(브라우저가 허용을 묻습니다)',
    blocked:'브라우저가 이 사이트의 알림을 막았습니다. 주소창 왼쪽 자물쇠(사이트 설정) → 알림 → 허용으로 바꾼 뒤 다시 누르세요',
    unsupported:'브라우저 알림은 https(테일넷 주소)나 http://127.0.0.1·localhost 에서만 됩니다',
    local:'테일넷 주소로 열면 켤 수 있습니다'}[st];
  b.innerHTML=st==='on'?ic('bell'):ic('bell-off'); b.setAttribute('aria-label',tr('브라우저 '+lab)); b.setAttribute('aria-pressed',String(st==='on')); b.dataset.tip=lab+' — '+tip;
  b.disabled=st==='local'; m.disabled=st==='local';
  m.textContent=st==='on'?'알림 끄기 (켜짐)':st==='off'?'알림 켜기':lab; m.dataset.tip=tip;}
async function notifyToggle(){const st=notifyState();
  if(st==='local'){toast('테일넷 주소로 열면 켤 수 있습니다','warn'); return;}
  if(st==='on'){savePrefs({notify:false}); drawNotify(); syncHiddenNotifyTimer(); toast('이 기기의 브라우저 알림을 껐습니다','ok'); return;}
  if(st==='unsupported'){toast('브라우저 알림은 https 테일넷 주소나 http://127.0.0.1 에서만 됩니다','warn'); return;}
  if(st==='blocked'){toast('브라우저가 알림을 막았습니다 — 주소창 자물쇠 → 알림 → 허용으로 바꾼 뒤 다시 누르세요','warn'); return;}
  let pm=notifyPerm(); if(pm!=='granted'){try{pm=await Notification.requestPermission();}catch(e){pm='denied';}}   // only ever asked from within this click
  if(pm!=='granted'){drawNotify(); toast(pm==='denied'?'알림을 허용하지 않아 켜지 않았습니다':'알림 허용을 고르지 않았습니다','warn'); return;}
  await notifyRegister(); savePrefs({notify:true});
  try{const d=(await api(dq('/api/meta?light=1'),{silent:true})).data; if(notifyCursor()==null)setNotifyCursor(d.ev_seq);}catch(e){}
  drawNotify(); syncHiddenNotifyTimer(); toast('이 기기에서 브라우저 알림을 켰습니다 — 나를 부르거나 내 핀에 일이 생기면 알립니다','ok');}
// Clicking a notification (service worker -> postMessage, or a new tab's #doc=<key>&pin=<number>) switches to that document and opens that pin.
function hashPin(){const m=/(?:^#|[#&])pin=(\d{1,9})(?:&|$)/.exec(location.hash||''); return m?+m[1]:null;}
// Reads a one-shot pin link (#doc=<key>&pin=<n>[&act=restore]) and removes pin=/act= from the address right away, so a
// reload never repeats it (a reload of an &act=restore link restored a pin someone had deleted again - PR #11 review).
function takeLinkHash(){const link={pin:hashPin(),doc:hashDoc(),restore:/(?:^#|[#&])act=restore(?:&|$)/.test(location.hash||'')};
  if(link.pin)history.replaceState(null,'',location.pathname+location.search+(link.doc?'#doc='+link.doc:''));
  return link;}
// restore = the [되살리기] action of a 'dropped' notification: bring the pin back from the Trash first (never for a viewer).
async function openPinFromLink(doc,pin,restore){if(!pin)return; if(doc&&doc!==DOC&&docInfo(doc)){await switchDoc(doc); if(DOC!==doc)return;}
  await loadPins(); if(restore&&!isViewer()&&!findAnyPin(pin)&&DROPPED.some(x=>x.id===pin))await restorePin(pin);
  const p=findAnyPin(pin); if(!p){if(DROPPED.some(x=>x.id===pin))openTrash(pin); return;} if(pinState(p)==='done'){SEC.done=true;}
  OPEN_CARDS.add(pin); setSide(true); drawPins(); if(pinState(p)!=='done')jumpPin(pin);
  requestAnimationFrame(()=>jumpToCard(pin));}
if('serviceWorker' in navigator)navigator.serviceWorker.addEventListener('message',e=>{const d=e.data||{};
  if(d.type==='open-pin')openPinFromLink(d.doc,+d.pin); else if(d.type==='restore-pin'&&!isViewer())restorePin(+d.pin);});
window.addEventListener('hashchange',()=>{const l=takeLinkHash(); if(l.pin)openPinFromLink(l.doc,l.pin,l.restore);});

// ------------------------------------------------ Async build-progress chip (P0b-01)
// BUILD_TIMER only exists while a build is actually running - /api/build is never hit every second once there's
// nothing to do (already settled into idle/ok/fail). There are only three places it starts: this tab pressing rebuild(),
// pollLight (the 5-second poll) seeing build.state==='running', and catching an already-running build at boot.
// A finished build is counted via build_seq (the server bumps it by 1 per build). LAST_BUILD_SEQ is the value this tab
// has already processed - processing (swapping the screen, toasting) happens exactly once per seq. Counting via the
// started_at string or "was running ever observed" instead missed a build that finished within a 5-second gap, or
// double-processed the same completion when a hidden tab came back via two paths at once (observed: toast x2).
let BUILD_TIMER=null,LAST_BUILD_ERR=null,LAST_BUILD_SEQ=null,BUILD_BOOTED=false,BUILD_INFLIGHT=null;
function buildChipText(b){
  const label={pull:'원격 main 당겨오는 중',copy:'원고 복사 중',latex:'LaTeX 컴파일 중',render:'쪽 그리는 중'}[b.phase]||'재빌드 중';
  const el=Math.round(b.elapsed_s||0), last=b.last_s?' '+tl('(지난번 {s}초)',{s:Math.round(b.last_s)}):'';
  return tr(label)+' · '+tl('{s}초',{s:el})+last;
}
// §P0c-E: appends one line about the pull result to the build-complete toast. ok gets the applied commit range,
// skipped/error just the reason - up_to_date has nothing worth reporting, so nothing is appended.
function pullSuffix(b){
  const p=b&&b.pull; if(!p||!p.state)return '';
  if(p.state==='ok')return ' · '+tl('원격 반영 {range}',{range:String(p.head_before||'?').slice(0,7)+'..'+String(p.head_after||'?').slice(0,7)});
  if(p.state==='skipped'||p.state==='error')return ' · '+tl(p.state==='error'?'git pull 실패({reason})':'git pull 건너뜀({reason})',{reason:p.reason||'?'});
  return '';
}
// Single-flight: if a request is already in flight, that same promise is returned instead of sending a new one (even if the
// 1-second timer, visibilitychange, focus, and pollLight all call it together, /api/build only goes out once and completion is only processed once).
function pollBuild(){
  if(document.hidden)return Promise.resolve();   // the request is never even sent while the tab is hidden
  if(BUILD_INFLIGHT)return BUILD_INFLIGHT;
  BUILD_INFLIGHT=pollBuildOnce().finally(()=>{BUILD_INFLIGHT=null;});
  return BUILD_INFLIGHT;
}
async function pollBuildOnce(){
  let b; const k=DOC;
  try{b=(await api(dq('/api/build?log=1'),{what:'빌드 상태',silent:true})).data;}catch(e){return;}
  if(k!==DOC)return;                    // the document changed - showDoc will query the new one again
  const chip=$('#build-chip');
  if(b.state==='running'){
    chip.hidden=false; chip.textContent=buildChipText(b); $('#btn-rebuild').disabled=true;
    if(!BUILD_TIMER)BUILD_TIMER=setInterval(pollBuild,1000);
    BUILD_BOOTED=true; return;
  }
  chip.hidden=true; $('#btn-rebuild').disabled=false;
  if(BUILD_TIMER){clearInterval(BUILD_TIMER);BUILD_TIMER=null;}    // polling stops once there's nothing left to watch
  const seq=(typeof b.seq==='number')?b.seq:0;
  const booted=BUILD_BOOTED; BUILD_BOOTED=true;
  if(LAST_BUILD_SEQ===null)LAST_BUILD_SEQ=seq;
  if(seq!==LAST_BUILD_SEQ){
    LAST_BUILD_SEQ=seq;                 // claimed before the await - so the same completion is never processed twice
    DOC_SEQ.set(k,seq);
    try{await refreshDoc();}catch(e){}
    if(k!==DOC)return;
    const secs=Math.round(b.elapsed_s||0);
    if(b.state==='ok'){toast(tr(META.view_only?'PDF가 바뀌어 쪽을 새로 그렸습니다':'PDF 재빌드 완료')+' · '+tl('{n}쪽',{n:META.pages.length})+' · '+tl('{s}초',{s:secs})+pullSuffix(b),'ok'); LAST_BUILD_ERR=null; BUILD_ERR_BY.delete(k); hideBuildErr();}
    else if(b.state==='ok_errors'){toast(tr('PDF를 재빌드했지만 LaTeX 오류가 있습니다')+pullSuffix(b),'warn'); showBuildErr(b);}
    else if(b.state==='fail'){toast(tr('빌드 실패 — 화면은 이전 PDF입니다')+pullSuffix(b),'err'); showBuildErr(b);}
  }else if(!booted&&(b.state==='fail'||b.state==='ok_errors')){
    showBuildErr(b);   // a freshly opened tab - a build that already failed just opens the panel/chip with no toast (leaves a way to look at it again)
  }
}
function startBuildPolling(){
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollBuild();});
  window.addEventListener('focus',()=>pollBuild());
  pollBuild();   // once at boot - if a build is already running (started by another session), this turns on the 1-second poll
}

// ------------------------------------------------ Panel width (P0b-06 + docs/handbook/viewer.md §패널 정리)
// wide/mid adjusts the right panel's width; narrow adjusts the bottom sheet's height. Width is remembered separately
// per screen kind (pinPrefs.side = wide, pinPrefs.sideMid = mid) - so a width fit for a spread-out screen never covers the desktop width.
// If the saved value exceeds the current screen's limit (collapsing/expanding, shrinking the window), the saved value is kept
// and only the visible width is clamped within the limit. The limit: the minimum is the width where the panel's tool bar fits
// on one line, the maximum is the width that leaves the body (PDF) side its minimum width.
function outlineBounds(){if(LAYOUT==='mid')return {min:220,max:320};const max=Math.max(180,Math.min(320,innerWidth-curSideW()-290));return {min:Math.min(220,max),max};}
function showOutlineWidth(w){const b=outlineBounds();w=Math.round(Math.max(b.min,Math.min(b.max,w)));
  document.documentElement.style.setProperty('--outline-width',w+'px');
  const g=$('#outline-grip');g.setAttribute('aria-valuemin',b.min);g.setAttribute('aria-valuemax',b.max);g.setAttribute('aria-valuenow',w);return w;}
function applyOutlineState(){
  const p=prefs(),closed=LAYOUT==='mid'?!OUTLINE_MID_OPEN:p.outlineClosed===true;
  document.body.classList.toggle('outline-collapsed',closed);
  const t=$('#nav-toc-toggle');t.setAttribute('aria-expanded',String(!closed));t.setAttribute('aria-label',closed?'목차 펼치기':'목차 접기');
  if(LAYOUT!=='narrow')showOutlineWidth(typeof p.outlineWidth==='number'?p.outlineWidth:240);
}
function setOutlineWidth(w){if(LAYOUT==='narrow')return;w=showOutlineWidth(w);savePrefs({outlineWidth:w});relayout();}
function toggleOutline(){const a=topAnchor(),closed=!document.body.classList.contains('outline-collapsed');
  if(LAYOUT==='mid'){OUTLINE_MID_OPEN=!closed;if(!closed)setSide(false);}
  else savePrefs({outlineClosed:closed});
  applyOutlineState();relayout();restoreAnchor(a);$('#nav-toc-toggle').focus({preventScroll:true});}
function sideBounds(layout,iw){const cl=(w,a,b)=>Math.round(Math.min(b,Math.max(a,w)));
  if(layout==='mid'){const min=300,max=iw<=900?Math.min(440,iw-240):Math.max(min,iw-488);
    const def=cl(330,min,max); return {min,max,def,presets:[min,def,cl(iw*0.5,min,max)]};}
  const min=280,max=Math.max(min,Math.min(Math.round(iw*0.8),iw-486)),def=cl(348,min,max);
  return {min,max,def,presets:[cl(300,min,max),def,cl(iw*0.42,min,max)]};}
function clampSide(w,b){return Math.round(Math.min(b.max,Math.max(b.min,w)));}
// Cycles through preset steps: the next step wider than the current width, wrapping to the narrowest if already at the widest. presetIndex is the step within +-4px (or -1 if none matches).
function nextPreset(presets,w){const n=presets.find(p=>p>w+4); return n===undefined?presets[0]:n;}
function presetIndex(presets,w){return presets.findIndex(p=>Math.abs(p-w)<=4);}
function sideKey(){return LAYOUT==='mid'?'sideMid':'side';}
function curSideW(){return Math.round($('#right').getBoundingClientRect().width);}
function showSideW(w,b){$('#right').style.width=w+'px'; document.documentElement.style.setProperty('--side-w',w+'px');
  const g=$('#grip'); g.setAttribute('aria-valuenow',w); g.setAttribute('aria-valuemin',b.min); g.setAttribute('aria-valuemax',b.max);}
function applySideWidth(){
  if(LAYOUT==='narrow'){$('#right').style.width=''; applySheet(); return;}
  const b=sideBounds(LAYOUT,innerWidth),p=prefs()[sideKey()];
  showSideW(clampSide(typeof p==='number'?p:b.def,b),b);
}
// Sets and remembers the width, then re-fits page width/marks (position is preserved - relayout uses topAnchor/restoreAnchor).
function setSideWidth(w){if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth); w=clampSide(w,b);
  showSideW(w,b); savePrefs({[sideKey()]:w}); relayout(); renderSizeSeg();}
function cycleSideWidth(){if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth); setSideWidth(nextPreset(b.presets,curSideW()));}
// Sheet height is stored as a fraction of screen height (--sheet-f) - CSS shrinks it to fit within the visible height when the keyboard is up.
const SHEET_F=[0.45,0.64,1],SHEET_MIN_F=0.3,SHEET_CLOSE_F=0.25;
function sheetF(){const f=prefs().sheetF; return typeof f==='number'?Math.min(1,Math.max(SHEET_MIN_F,f)):0.64;}
function applySheet(){document.documentElement.style.setProperty('--sheet-f',String(sheetF()));}
function setSheetF(f){f=Math.min(1,Math.max(SHEET_MIN_F,f)); savePrefs({sheetF:Math.round(f*1000)/1000}); applySheet(); if(!SIDE_OPEN)setSide(true); renderSizeSeg();}
function cycleSheet(){const f=sheetF(),i=SHEET_F.findIndex(x=>x>f+0.02); setSheetF(SHEET_F[i<0?0:i]);}
// The '패널 폭' (wide/mid) / '시트 높이' (narrow) segment control inside [⋯].
function renderSizeSeg(){const box=$('#m-size'); if(!box)return; const narrow=LAYOUT==='narrow';
  $('#m-size-l').textContent=narrow?'시트 높이':'패널 폭'; box.setAttribute('aria-label',narrow?'시트 높이':'패널 폭');
  let names,cur;
  if(narrow){names=['낮게','보통','높게']; const f=sheetF(); cur=SHEET_F.findIndex(x=>Math.abs(x-f)<=0.02);}
  else{names=['좁게','보통','넓게']; cur=presetIndex(sideBounds(LAYOUT,innerWidth).presets,curSideW());}
  box.innerHTML=names.map((n,i)=>'<button class="'+(i===cur?'on':'')+'" aria-pressed="'+(i===cur)+'" data-act="size-preset" data-i="'+i+'">'+n+'</button>').join('');}
function sizePreset(i){if(LAYOUT==='narrow'){setSheetF(SHEET_F[i]);return;} setSideWidth(sideBounds(LAYOUT,innerWidth).presets[i]);}
function pageSrc(p){return dq('/pages/'+encodeURIComponent(p.name)+'?v='+encodeURIComponent(META.built_at));}
function buildDoc(){
  const doc=$('#doc'); doc.innerHTML=''; PENDING=null;
  META.pages.forEach((p,i)=>{const d=document.createElement('div'); d.className='pg'; d.id='p'+(i+1); d.dataset.page=i+1;
    d.style.width=W+'px'; d.style.aspectRatio=p.pt_w+' / '+p.pt_h;
    d.innerHTML='<span class="no">'+(i+1)+'</span><img loading="lazy" draggable="false" alt="'+esc(tl('{page}쪽',{page:i+1}))+'" src="'+esc(pageSrc(p))+'">';
    doc.appendChild(d);});
  marks(); vecObserve();
}
// save=false is auto-fit - never saved. If a width fit for a narrow first window persisted into a wider window, the pages would look too small.
// Width is never saved in compact (mid/narrow) - so a width fit for a folded screen never overrides the spread/desktop setting.
// The page width limit is ZOOM_MIN-ZOOM_MAX times the fit-width (minimum 160px). Overflow scrolls horizontally only within the PDF area (#left).
const ZOOM_MIN=0.5,ZOOM_MAX=5,ZOOM_STEP=1.2;
function wBounds(fit){const f=Math.max(160,fit),lo=Math.max(160,Math.round(f*ZOOM_MIN)); return [lo,Math.max(lo,Math.round(f*ZOOM_MAX))];}
function setW(w,save){const b=wBounds(fitWidth()); W=Math.round(Math.min(b[1],Math.max(b[0],w))); $$('.pg').forEach(e=>e.style.width=W+'px');
  if(save!==false&&LAYOUT==='wide')savePrefs({w:W}); vecInvalidate();}
function innerW(){const L=$('#left'),cs=getComputedStyle(L); return L.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);}
// Fit-width: in compact, the body's inner width; in wide, #left.clientWidth minus 48px (left/right margins).
function fitWidth(){return LAYOUT!=='wide'?innerW():$('#left').clientWidth-48;}
// compact always fits the screen width (unless the user pressed -/+, in which case it stays fixed for that layout). wide behaves as before.
function autoW(){if(LAYOUT!=='wide'){if(!ZOOMED)setW(innerW(),false);return;}
  if(prefs().w!==undefined)return; const f=$('#left').clientWidth-44-16; setW(f<900?f:900,false);}
// Zoom anchor: the page under screen coordinates (cx,cy) and its fraction within that page. If the point falls in the gap between pages, the vertically nearest page is used.
// Without coordinates, the center of the PDF area is used (keyboard/button).
function zoomAnchor(cx,cy){const L=$('#left'),lr=L.getBoundingClientRect();
  if(cx==null){cx=lr.left+L.clientWidth/2; cy=lr.top+L.clientHeight/2;}
  let best=null,bd=Infinity;
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(),d=cy<r.top?r.top-cy:(cy>r.bottom?cy-r.bottom:0);
    if(d<bd){bd=d; best={pg,r};} if(d===0)break;}
  return best?{pg:best.pg,cx,cy,fx:(cx-best.r.left)/best.r.width,fy:(cy-best.r.top)/best.r.height}:null;}
// Restores the anchor's in-page fractional position back to screen coordinates (cx,cy) - so the text under the pointer stays put even after zooming.
function zoomRestore(a,cx,cy){if(!a)return; const L=$('#left'),r=a.pg.getBoundingClientRect();
  L.scrollLeft+=r.left+a.fx*r.width-(cx==null?a.cx:cx); L.scrollTop+=r.top+a.fy*r.height-(cy==null?a.cy:cy);}
function zoomTo(w,cx,cy){const a=zoomAnchor(cx,cy); setW(w); if(LAYOUT!=='wide')ZOOMED=true; zoomRestore(a);}
function zoom(k){zoomTo(W*Math.pow(ZOOM_STEP,k));}
// Fit width: keeps the viewed page/position (anchored at the top) and resets horizontal scroll to the start.
function fitW(){const a=topAnchor(),L=$('#left');
  if(LAYOUT!=='wide'){ZOOMED=false; setW(innerW(),false);} else setW(L.clientWidth-48);
  restoreAnchor(a); L.scrollLeft=0;}
function goPage(v){const el=document.getElementById('p'+parseInt(v===undefined?$('#jump').value:v,10)); if(el) el.scrollIntoView({behavior:SMOOTH});}
$('#jump').addEventListener('keydown',e=>{if(e.key==='Enter')goPage();});
$('#m-jump').addEventListener('keydown',e=>{if(e.key==='Enter'){$('#more').close(); goPage($('#m-jump').value);}});

// ------------------------------------------------ Vector rendering (PDF.js) - docs/handbook/viewer.md §벡터 렌더링
// Each page draws the PDF directly onto a canvas. Backing size = page CSS size x devicePixelRatio (x the browser's pinch
// scale), and app zoom is already baked into the page CSS width (W). The page box, aspect ratio, and % coordinates stay
// exactly as they were for PNG, so drag frac/marks/pdf_build never change.
// - Only pages near the visible area (VEC_KEEP) are drawn; canvases for pages that scroll away are released (IntersectionObserver).
// - A single canvas never exceeds VEC_PIX_CAP pixels. At zoom beyond that, the page canvas is capped and a detail canvas (.dt)
//   rendered at native resolution for just the visible portion is overlaid on top.
// - When zoom changes, the existing canvas is stretched via CSS to stay visible while a debounced redraw happens (no flicker).
// - If pdf.js/the PDF fails to load or render, the canvas is torn down, falling back to the PNG <img>, and the status chip (#vec-chip) reports it.
// No text-selection layer is added - since dragging means selecting a region, it would conflict with text selection.
const PDFJS_V='__PDFJS_VERSION__';
const VEC_PIX_CAP=16777216, VEC_KEEP='150% 0px', VEC_DT_MARGIN=0.25;
const VEC={lib:null,doc:null,build:null,gen:0,failed:null,io:null,near:new Set(),st:new Map(),cur:null,
  pumping:false,timer:0,stats:[],tFirst:null,tDoc:null,cache:new Map()};
// Multiple documents: holds up to VEC_CACHE_MAX recently opened PDF document objects keyed by 'document|build' - switching tabs back
// draws immediately without re-fetching. Beyond that, the least recently used is closed first (worker memory). An old build of the same document is closed when a new build opens.
const VEC_CACHE_MAX=3;
function vecCacheKey(k,b){return (k||'')+'|'+(b||'');}
function vecCachePut(key,doc){const c=VEC.cache; c.delete(key); c.set(key,doc);
  const pre=key.split('|')[0]+'|';
  Array.from(c.keys()).forEach(x=>{if(x!==key&&x.startsWith(pre)){const d=c.get(x); c.delete(x); if(d!==VEC.doc)vecClose(d);}});
  while(c.size>VEC_CACHE_MAX){const x=c.keys().next().value,d=c.get(x); c.delete(x); if(d!==VEC.doc&&d!==doc)vecClose(d);}}
function vecCached(doc){for(const d of VEC.cache.values())if(d===doc)return true; return false;}
function vecForget(doc){VEC.cache.forEach((d,x)=>{if(d===doc)VEC.cache.delete(x);});}
window.__pinVec=VEC;   // for measurement (Playwright) - canvas count, render time
async function vecBoot(){
  if(!window.IntersectionObserver){vecFail('이 브라우저는 IntersectionObserver 가 없습니다');return;}
  try{VEC.lib=await import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V);
    VEC.lib.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V;}
  catch(e){VEC.lib=null; vecFail('pdf.js 를 불러오지 못했습니다',e); return;}
  await vecOpen();
}
// Opens the PDF for the currently displayed build (META.pages_build). Never used if the page count differs from what's on screen (coordinates would be off).
async function vecOpen(){
  if(!VEC.lib||!META)return;
  const gen=++VEC.gen, build=META.pages_build||'', n=META.pages.length, key=vecCacheKey(DOC,build); let doc=VEC.cache.get(key);
  vecCancel();
  if(!doc){
    // The old document (a different document/old build) is never used for the new page DOM - PNG is shown while fetching.
    const prev=VEC.doc; VEC.doc=null; VEC.build=null; if(prev&&!vecCached(prev))vecClose(prev);
    try{const r=await fetch(dq('/pdf?build='+encodeURIComponent(build)+'&v='+encodeURIComponent(META.built_at||'')));
      if(!r.ok)throw new Error('PDF HTTP '+r.status);
      const data=new Uint8Array(await r.arrayBuffer()); if(gen!==VEC.gen)return;
      doc=await VEC.lib.getDocument({data,isEvalSupported:false,useWasm:false,enableXfa:false}).promise;}
    catch(e){if(gen===VEC.gen)vecFail('PDF 를 벡터로 열지 못했습니다',e); return;}
    if(gen!==VEC.gen){vecClose(doc); return;}
    if(doc.numPages!==n){vecClose(doc); vecFail(tl('PDF 쪽 수({pdf})가 화면({view})과 다릅니다',{pdf:doc.numPages,view:n})); return;}
    vecCachePut(key,doc);
  }else vecCachePut(key,doc);           // promoted as most recently used
  if(gen!==VEC.gen)return;
  const old=VEC.doc; VEC.doc=doc; VEC.build=build; VEC.failed=null; VEC.tDoc=performance.now(); $('#vec-chip').hidden=true;
  loadOutline(doc,gen);
  VEC.st.forEach(s=>{s.stale=true;});
  if(old&&old!==doc&&!vecCached(old))vecClose(old);
  vecSchedule(0);
}
async function loadOutline(doc,gen){
  const box=$('#outline-items'); let entries=[];
  try{const items=await doc.getOutline();
    async function walk(rows,depth){for(const item of rows||[]){if(entries.length>=180)return;
      let dest=item.dest;
      if(typeof dest==='string')dest=await doc.getDestination(dest);
      if(Array.isArray(dest)&&dest[0]!=null){
        const page=typeof dest[0]==='number'?dest[0]+1:(await doc.getPageIndex(dest[0]))+1;
        const ptH=META&&META.pages&&META.pages[page-1]?+META.pages[page-1].pt_h:0;
        if(Number.isInteger(page)&&page>=1&&page<=doc.numPages)entries.push({title:item.title||tr('제목 없음'),page,depth,frac:destFrac(dest,ptH)});
      }
      if(depth<4)await walk(item.items,depth+1);
    }}
    await walk(items,0);
  }catch(e){entries=[];}
  if(gen!==VEC.gen||doc!==VEC.doc)return;
  if(entries.length){
    const k=DOC,build=META&&META.pages_build;
    try{const r=(await api(dq('/api/outline-labels',k),{what:'목차 번호 읽기',silent:true})).data;
      if(gen===VEC.gen&&doc===VEC.doc&&k===DOC&&build===META.pages_build&&r.build===build)
        entries=mergeOutlineLabels(entries,r.labels||[]);
    }catch(e){} // the PDF's own outline is still usable even if the numbering service can't be reached.
  }
  if(gen!==VEC.gen||doc!==VEC.doc)return;
  OUTLINE_ENTRIES=entries;OUTLINE_SELECTED=-1;OUTLINE_ACTIVE_PAGE=0;OUTLINE_PINNED=null;
  renderOutline();updateSectionStrip();
}
function mergeOutlineLabels(entries,labels){
  const norm=s=>String(s||'').normalize('NFKC').replace(/\s+/g,' ').trim().toLowerCase();
  const levels=['section','subsection','subsubsection','paragraph','subparagraph'];
  const depthGuard=labels.some(l=>l.level==='section'&&entries.some(e=>e.depth===0&&norm(e.title)===norm(l.title)));
  let cursor=0;
  return entries.map(entry=>{
    const title=norm(entry.title);let matched=null;
    if(title)for(let i=cursor;i<labels.length;i++){
      const label=labels[i];if(norm(label.title)!==title)continue;
      if(/^\d+$/.test(String(label.page||''))&&Number(label.page)!==entry.page)continue;
      if(depthGuard&&levels.includes(label.level)&&levels.indexOf(label.level)!==entry.depth)continue;
      matched=label;cursor=i+1;break;
    }
    return Object.assign({},entry,{number:matched?String(matched.number||''):'',
      pageLabel:matched?String(matched.page||''):''});
  });
}
let OUTLINE_ENTRIES=[],OUTLINE_SELECTED=-1,OUTLINE_ACTIVE_PAGE=0;
function renderOutline(){
  const box=$('#outline-items'),query=$('#outline-search').value.trim().toLowerCase();
  if(!OUTLINE_ENTRIES.length){box.className='outline-empty';box.textContent='이 PDF에는 이동할 수 있는 목차가 없습니다.';return;}
  const rows=OUTLINE_ENTRIES.map((x,i)=>Object.assign({index:i},x)).filter(x=>!query||(x.number+' '+x.title).toLowerCase().includes(query));
  if(!rows.length){box.className='outline-empty';box.textContent='찾은 장·절이 없습니다.';return;}
  box.className='';box.innerHTML=rows.map(x=>'<button class="ol-depth-'+Math.min(x.depth,4)+(x.index===OUTLINE_SELECTED?' ol-active':'')+'" data-act="outline-page" data-index="'+x.index+'" data-page="'+x.page+'" aria-current="'+(x.index===OUTLINE_SELECTED?'location':'false')+'" title="'+esc(x.title)+'"><span class="ol-no">'+esc(x.number||'·')+'</span><span class="ol-name">'+esc(x.title)+'</span><span class="ol-page">'+esc(tl('{page}쪽',{page:x.pageLabel||String(x.page)}))+'</span></button>').join('');
}
// Where a PDF outline destination sits on its page, as a fraction from the top (0 = top). An XYZ destination carries
// the top edge in PDF points from the bottom; anything else (Fit, no top) counts as the top of the page.
function destFrac(dest,ptH){const top=Array.isArray(dest)&&dest[1]&&dest[1].name==='XYZ'?dest[3]:null;
  if(typeof top!=='number'||!(ptH>0))return 0; return Math.min(1,Math.max(0,1-top/ptH));}
// The outline entry the reader is in at (page, frac): the last heading that starts at or above that point. Before the
// first heading (a title page, the top of page 1) it is the first entry - never a later heading on the same page
// (v0.2.0 showed "1.2" at the very top of page 1, because 1, 1.1 and 1.2 all start on page 1). -1 without entries.
function outlineIndexAt(entries,page,frac){let sel=-1;
  for(let i=0;i<entries.length;i++){const e=entries[i]; if(e.page<page||(e.page===page&&(e.frac||0)<=frac+1e-6))sel=i;}
  return sel<0&&entries.length?0:sel;}
let OUTLINE_PINNED=null;   // an entry picked in the outline wins until the reader leaves its page
function updateSectionStrip(){
  const L=$('#left'),probe=L?Math.min(160,L.clientHeight/4):0,anchor=topAnchor(probe),page=anchor?anchor.page:1,frac=anchor?anchor.frac:0;
  let sel;
  if(OUTLINE_PINNED&&OUTLINE_PINNED.page===page)sel=OUTLINE_PINNED.index;
  else{OUTLINE_PINNED=null; sel=outlineIndexAt(OUTLINE_ENTRIES,page,frac);}
  if(sel!==OUTLINE_SELECTED||page!==OUTLINE_ACTIVE_PAGE){OUTLINE_ACTIVE_PAGE=page;OUTLINE_SELECTED=sel;renderOutline();}
  const x=OUTLINE_ENTRIES[OUTLINE_SELECTED];$('#section-current').textContent=x?(x.number?x.number+'  ':'')+x.title:tr('원고');
  $('#section-page').textContent=tl('{page} / {n}쪽',{page,n:META&&META.pages?META.pages.length:0});
}
$('#outline-search').addEventListener('input',renderOutline);
$('#left').addEventListener('scroll',()=>{if(!document.body.classList.contains('revision-open'))requestAnimationFrame(updateSectionStrip);},{passive:true});
// Closes one document - PDFDocumentProxy has no destroy of its own; loadingTask frees the worker-side resources too.
function vecClose(doc){if(!doc)return; try{doc.loadingTask.destroy();}catch(e){}}
function vecFail(msg,err){
  VEC.failed=msg; VEC.gen++; vecCancel(); vecReleaseAll();
  vecForget(VEC.doc); vecClose(VEC.doc); VEC.doc=null;
  const c=$('#vec-chip'); c.hidden=false;
  c.dataset.tip=tl('PDF를 벡터로 그리지 못해 이미지(PNG)로 보입니다 — {reason}. 확대하면 흐릴 수 있습니다',{reason:tr(msg)+(err&&err.message?' ('+String(err.message).slice(0,100)+')':'')});
}
function vecState(n){let s=VEC.st.get(n); if(!s){s={base:null,bw:0,bh:0,dt:null,reg:null,dtCw:0,dtK:0,stale:false}; VEC.st.set(n,s);} return s;}
function vecDrop(cv){if(!cv)return; cv.width=0; cv.height=0; cv.remove();}   // must shrink to 0 for Safari to release memory right away too
function vecRelease(n){if(VEC.cur&&VEC.cur.n===n)vecCancel(); const s=VEC.st.get(n); if(!s)return;
  vecDrop(s.base); vecDrop(s.dt); VEC.st.delete(n);
  const pg=document.getElementById('p'+n); if(pg)pg.classList.remove('drawn');}
function vecReleaseAll(){vecCancel(); Array.from(VEC.st.keys()).forEach(vecRelease);}
function vecCancel(){const c=VEC.cur; VEC.cur=null; if(c&&c.task){try{c.task.cancel();}catch(e){}}}
function vecObserve(){if(VEC.io)VEC.io.disconnect(); vecReleaseAll(); VEC.near.clear(); if(!window.IntersectionObserver)return;
  VEC.io=new IntersectionObserver(es=>{es.forEach(en=>{const n=+en.target.dataset.page;
      if(en.isIntersecting)VEC.near.add(n); else {VEC.near.delete(n); vecRelease(n);}}); vecSchedule(0);},
    {root:$('#left'),rootMargin:VEC_KEEP});
  $$('.pg').forEach(pg=>VEC.io.observe(pg));}
function vecSchedule(ms){clearTimeout(VEC.timer); VEC.timer=setTimeout(vecPump,ms||0);}
// Zoom, window size, or DPR changed - whatever was being drawn (the old size) is discarded and redrawn shortly after. Meanwhile, the old canvas is shown stretched.
function vecInvalidate(){if(!VEC.doc)return; vecCancel(); vecSchedule(150);}
function vecK(){const vv=window.visualViewport; return (window.devicePixelRatio||1)*Math.max(1,(vv&&vv.scale)||1);}
// The page canvas's backing size. If it exceeds the cap, it's scaled down proportionally and marked capped (the detail canvas fills in the visible portion).
function vecTarget(cw,ch,k,cap){let bw=Math.round(cw*k),bh=Math.round(ch*k),capped=false;
  if(bw*bh>cap){const f=Math.sqrt(cap/(bw*bh)); bw=Math.max(1,Math.floor(bw*f)); bh=Math.max(1,Math.floor(bh*f)); capped=true;}
  return {cw,ch,k,bw,bh,capped};}
function vecTargetOf(pg){const cw=pg.clientWidth,ch=pg.clientHeight; return cw&&ch?vecTarget(cw,ch,vecK(),VEC_PIX_CAP):null;}
// The portion of a page visible on screen (page CSS px). margin is extra room relative to the viewport size (the detail canvas is drawn a bit larger).
function vecVisible(pg,margin){const L=$('#left'),lr=L.getBoundingClientRect(),r=pg.getBoundingClientRect();
  const ox=r.left+pg.clientLeft,oy=r.top+pg.clientTop,cw=pg.clientWidth,ch=pg.clientHeight;
  const vx0=lr.left+L.clientLeft,vy0=lr.top+L.clientTop,vw=L.clientWidth,vh=L.clientHeight,mx=vw*margin,my=vh*margin;
  const x0=Math.max(0,vx0-mx-ox),y0=Math.max(0,vy0-my-oy),x1=Math.min(cw,vx0+vw+mx-ox),y1=Math.min(ch,vy0+vh+my-oy);
  return x1>x0&&y1>y0?{x:x0,y:y0,w:x1-x0,h:y1-y0,cw,ch}:null;}
function vecCovers(reg,v){return !!reg&&reg.x<=v.x/v.cw+1e-6&&reg.y<=v.y/v.ch+1e-6&&
  reg.x+reg.w>=(v.x+v.w)/v.cw-1e-6&&reg.y+reg.h>=(v.y+v.h)/v.ch-1e-6;}
// The one thing to draw next: pages within the viewport first (nearest to center), page canvas before detail canvas.
function vecNextJob(){
  if(!VEC.doc)return null;
  const L=$('#left'),lr=L.getBoundingClientRect(),top=lr.top,bot=lr.top+L.clientHeight,cy=(top+bot)/2;
  const list=[];
  VEC.near.forEach(n=>{const pg=document.getElementById('p'+n); if(!pg)return; const r=pg.getBoundingClientRect();
    list.push({n,pg,vis:r.bottom>top&&r.top<bot,d:Math.abs((r.top+r.bottom)/2-cy)});});
  list.sort((a,b)=>(b.vis-a.vis)||(a.d-b.d));
  for(const it of list){const s=vecState(it.n),t=vecTargetOf(it.pg); if(!t)continue;
    if(!s.base||s.stale||s.bw!==t.bw||s.bh!==t.bh)return {n:it.n,kind:'base'};
    if(t.capped&&it.vis){const v=vecVisible(it.pg,0);
      if(v&&(!s.dt||s.dtCw!==t.cw||s.dtK!==t.k||!vecCovers(s.reg,v)))return {n:it.n,kind:'dt'};}
    else if(s.dt){vecDrop(s.dt); s.dt=null; s.reg=null;}}
  return null;
}
async function vecPump(){
  if(VEC.pumping||!VEC.doc)return; VEC.pumping=true;
  try{for(let i=0;i<400;i++){const job=vecNextJob(); if(!job)break; await vecRun(job);}}
  finally{VEC.pumping=false;}
}
async function vecRun(job){
  const n=job.n,pg=document.getElementById('p'+n),doc=VEC.doc,gen=VEC.gen; if(!pg||!doc)return;
  if(n>doc.numPages)return;   // a defensive check - just skips a case where another document/build's doc ends up running on a new n (the vecOpen bailout above is the real fix)
  let page; try{page=await doc.getPage(n);}catch(e){if(gen===VEC.gen)vecFail('쪽을 읽지 못했습니다',e); return;}
  if(gen!==VEC.gen||!VEC.near.has(n)||!document.contains(pg))return;
  const t=vecTargetOf(pg); if(!t)return;
  const vp1=page.getViewport({scale:1}),cv=document.createElement('canvas'); let scale,tf,reg=null;
  // Width and height are fit independently (the transform's vertical scale) - the page box's aspect ratio comes from
  // the PNG pixel dimensions and differs from the PDF page's aspect ratio by less than 0.1%. Since PNG was also drawn
  // filling that same box, this is needed for the canvas's text to land at the same % position it did for PNG.
  if(job.kind==='base'){cv.width=t.bw; cv.height=t.bh; scale=t.bw/vp1.width; tf=[1,0,0,t.bh/(vp1.height*scale),0,0];}
  else{const v=vecVisible(pg,VEC_DT_MARGIN); if(!v)return; let k=t.k;
    if(v.w*v.h*k*k>VEC_PIX_CAP)k=Math.sqrt(VEC_PIX_CAP/(v.w*v.h));
    scale=t.cw*k/vp1.width; cv.width=Math.max(1,Math.round(v.w*k)); cv.height=Math.max(1,Math.round(v.h*k));
    tf=[1,0,0,t.ch*k/(vp1.height*scale),-v.x*k,-v.y*k];
    reg={x:v.x/t.cw,y:v.y/t.ch,w:v.w/t.cw,h:v.h/t.ch};}
  const ctx=cv.getContext('2d',{alpha:false}),t0=performance.now();
  const task=page.render({canvasContext:ctx,viewport:page.getViewport({scale}),transform:tf});
  VEC.cur={n,task};
  try{await task.promise;}
  catch(e){if(VEC.cur&&VEC.cur.task===task)VEC.cur=null; vecDrop(cv);
    if(e&&e.name==='RenderingCancelledException')return;
    if(gen===VEC.gen)vecFail('쪽을 그리지 못했습니다',e); return;}
  if(VEC.cur&&VEC.cur.task===task)VEC.cur=null;
  const t2=gen===VEC.gen&&VEC.near.has(n)&&document.contains(pg)?vecTargetOf(pg):null;
  if(!t2||t2.cw!==t.cw||t2.ch!==t.ch||t2.k!==t.k){vecDrop(cv); return;}   // zoom or window size changed while drawing
  VEC.stats.push({n,kind:job.kind,ms:Math.round(performance.now()-t0),w:cv.width,h:cv.height});
  if(VEC.stats.length>200)VEC.stats.splice(0,VEC.stats.length-200);
  const s=vecState(n);
  if(job.kind==='base'){vecDrop(s.base); s.base=cv; s.bw=t.bw; s.bh=t.bh; s.stale=false; cv.className='vb';
    pg.prepend(cv); pg.classList.add('drawn'); if(VEC.tFirst===null)VEC.tFirst=performance.now();}
  else{vecDrop(s.dt); s.dt=cv; s.reg=reg; s.dtCw=t.cw; s.dtK=t.k; cv.className='dt';
    Object.assign(cv.style,{left:reg.x*100+'%',top:reg.y*100+'%',width:reg.w*100+'%',height:reg.h*100+'%'});
    if(s.base)s.base.after(cv); else pg.prepend(cv);}
}
$('#left').addEventListener('scroll',()=>{if(VEC.doc)vecSchedule(120);},{passive:true});
// devicePixelRatio changes with browser zoom (Ctrl+wheel outside the PDF, etc.) or moving the window to a different screen - redraws at that scale.
(function watchDpr(){if(!window.matchMedia)return;
  matchMedia('(resolution: '+(window.devicePixelRatio||1)+'dppx)').addEventListener('change',()=>{vecInvalidate(); watchDpr();},{once:true});})();
if(window.visualViewport)visualViewport.addEventListener('resize',()=>{if(VEC.doc)vecSchedule(300);});

// ------------------------------------------------ PDF-area-only zoom - docs/handbook/viewer.md §PDF 영역 전용 확대
// Browser zoom would also enlarge the sidebar and tool bar. Zoom input over the PDF area is intercepted to change only the page width (W).
// - Desktop: Ctrl(Cmd)+wheel over #left. Trackpad pinch also arrives as a wheel event with ctrlKey set, in Chrome/Firefox. Anchored to the pointer.
// - Safari trackpad pinch: gesturestart/gesturechange (e.scale).
// - Keyboard Ctrl(Cmd) + = / + / - / 0 -> zoom in/out/fit width (never intercepted while an input field has focus - see the key handler).
// - Touch: #left has touch-action:pan-x pan-y, so there's no browser pinch. W changes with the ratio of the two-finger distance, and the
//   point under the midpoint of the two fingers follows the fingers (drag while zooming). A page in selection mode has touch-action:none, so it goes through the same path.
function zoomKey(e){const k=e.key,c=e.code;
  if(k==='='||k==='+'||c==='Equal'||c==='NumpadAdd')return 'in';
  if(k==='-'||k==='_'||c==='Minus'||c==='NumpadSubtract')return 'out';
  if(k==='0'||c==='Digit0'||c==='Numpad0')return 'fit';
  return null;}
// The factor for one wheel tick. One mouse-wheel notch (|dy|>=50 pixels or a line unit) gets the same ZOOM_STEP as one button
// press; a trackpad pinch's finely divided dy is composed via exp(-dy/100) - the inverse of the formula Chrome uses to turn
// pinch scale into wheel events, so it grows in proportion to how far the fingers spread. dy is clamped to +-18 so a single
// event never exceeds one button press's worth (ZOOM_STEP ~ exp(0.18)).
function wheelFactor(dy,mode){if(!dy)return 1;
  if(mode===1||mode===2||Math.abs(dy)>=50)return dy<0?ZOOM_STEP:1/ZOOM_STEP;
  return Math.exp(-Math.max(-18,Math.min(18,dy))/100);}
(function(){const L=$('#left'); let acc=1,pt=null,raf=0,G=null,TP=null;
  const flush=()=>{raf=0; if(acc===1)return; const f=acc; acc=1; zoomTo(W*f,pt[0],pt[1]);};
  L.addEventListener('wheel',e=>{if(!(e.ctrlKey||e.metaKey))return; e.preventDefault();
    acc*=wheelFactor(e.deltaY,e.deltaMode); pt=[e.clientX,e.clientY]; if(!raf)raf=requestAnimationFrame(flush);},{passive:false});
  L.addEventListener('gesturestart',e=>{e.preventDefault(); if(!TP)G={w:W};},{passive:false});
  L.addEventListener('gesturechange',e=>{e.preventDefault(); if(G&&!TP&&e.scale>0)zoomTo(G.w*e.scale,e.clientX,e.clientY);},{passive:false});
  L.addEventListener('gestureend',e=>{e.preventDefault(); G=null;},{passive:false});
  const mid=(a,b)=>[(a.clientX+b.clientX)/2,(a.clientY+b.clientY)/2];
  const dist=(a,b)=>Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY)||1;
  let tr=0,last=null;
  const apply=()=>{tr=0; if(!TP||!last)return; const w=TP.w*last.d/TP.d;
    setW(w); if(LAYOUT!=='wide')ZOOMED=true; zoomRestore(TP.a,last.m[0],last.m[1]);};
  L.addEventListener('touchstart',e=>{if(e.touches.length!==2){if(e.touches.length>2)TP=null; return;}
    if(e.cancelable)e.preventDefault();
    const a=e.touches[0],b=e.touches[1],m=mid(a,b); cancelDrag(); cancelLP();
    TP={d:dist(a,b),w:W,a:zoomAnchor(m[0],m[1])}; last={d:TP.d,m};},{passive:false});
  L.addEventListener('touchmove',e=>{if(!TP||e.touches.length!==2)return; if(e.cancelable)e.preventDefault();
    const a=e.touches[0],b=e.touches[1]; last={d:dist(a,b),m:mid(a,b)}; if(!tr)tr=requestAnimationFrame(apply);},{passive:false});
  const end=e=>{if(TP&&e.touches.length<2){if(tr){cancelAnimationFrame(tr); apply();} TP=null; last=null;}};
  L.addEventListener('touchend',end); L.addEventListener('touchcancel',end);
})();

// ------------------------------------------------ Layout by screen width (mobile)
// wide: 1100px and up, a right sidebar (width-adjustable). mid: over 700px, under 1100px - a narrow side
// panel; when collapsed, only the bottom-right tool bar remains. narrow: 700px and below (a folded foldable/phone) -
// a bottom sheet, collapsed by default. If the width changes partway through a collapse/expand, the layout is re-chosen
// and the page width is re-fit while preserving the viewed position (topAnchor). Marks and the selection box are % coordinates within the page, so they fall back into place automatically once the page width is fit.
function layoutFor(){const w=innerWidth; if(w<=700)return 'narrow'; if(w<1100)return 'mid'; return 'wide';}
function applyLayout(){const L=layoutFor(),overlay=L==='mid'&&innerWidth<=900; if(L===LAYOUT&&overlay===MID_OVERLAY)return false;
  LAYOUT=L; MID_OVERLAY=overlay; OUTLINE_MID_OPEN=false; const b=document.body,p=prefs(); ZOOMED=false;
  ['wide','mid','narrow'].forEach(k=>b.classList.toggle('lay-'+k,k===L)); b.classList.toggle('compact',L!=='wide');
  SIDE_OPEN=L==='wide'?true:(L==='mid'?(typeof p.midClosed==='boolean'?!p.midClosed:!overlay):false);
  if(L!=='wide'&&!REPICK&&(CUR||EDIT||!$('#composer').hidden))SIDE_OPEN=true;   // an in-progress note/edit is never left hidden collapsed
  applySide(); stickTop(); return true;}
function applySide(){const open=LAYOUT==='wide'||SIDE_OPEN;
  document.body.classList.toggle('side-open',open);
  const btn=$('#btn-side'); btn.setAttribute('aria-expanded',String(open));
  $('#side-arrow').innerHTML=ic(LAYOUT==='narrow'?(open?'chevron-down':'chevron-up'):(open?'chevron-right':'chevron-left'));
  btn.setAttribute('aria-label',tr(open?'패널 접기':'패널 펴기')+' · '+tl('열린 핀 {n}',{n:PINS.length}));}
// remember: only remembers a manual collapse/expand by the user in mid (narrow always starts collapsed).
function setSide(open,remember){if(LAYOUT==='wide')return; open=!!open;
  if(open&&LAYOUT==='mid'){OUTLINE_MID_OPEN=false;applyOutlineState();}
  if(remember&&LAYOUT==='mid')savePrefs({midClosed:!open});
  if(SIDE_OPEN===open)return; SIDE_OPEN=open; applySide(); hideTip();}
function relayout(){const a=topAnchor(); applyLayout(); applySideWidth(); applyOutlineState();autoW(); restoreAnchor(a); hideTip(); if(CUR)renderComposer(); stickTop();updateSectionStrip();}
// The height a list section header (sticky) sticks below. In compact, #right is the scroll box and the tool bar (#bar1, below the
// sheet handle in narrow) is already stuck above it, so the header sticks below that. In wide, #list itself is the scroll box, so this is 0.
function stickTop(){let t=0; const b=$('#bar1');
  if(LAYOUT!=='wide'&&b){const cs=getComputedStyle(b); if(cs.position==='sticky')t=Math.round((parseFloat(cs.top)||0)+b.offsetHeight);}
  document.documentElement.style.setProperty('--stick-top',t+'px');}
if(window.ResizeObserver)new ResizeObserver(()=>stickTop()).observe($('#bar1'));
let RELAY=0;
function scheduleRelayout(){if(RELAY)return; RELAY=requestAnimationFrame(()=>{RELAY=0; if(META)relayout(); else applyLayout();});}
window.addEventListener('resize',scheduleRelayout);
MQ_COARSE.addEventListener('change',scheduleRelayout);
// Even a mere #left width change from expanding/collapsing the panel (compact) re-fits the page width. The layout is never
// changed directly in the callback - it's deferred to the next frame (avoids a ResizeObserver loop warning). wide still only reacts to window-size changes, as before.
// Never re-fit while the handle is being dragged (body.resizing) - setSideWidth fits it once on release.
if(window.ResizeObserver)new ResizeObserver(()=>{if(LAYOUT&&LAYOUT!=='wide'&&!document.body.classList.contains('resizing'))scheduleRelayout();}).observe($('#left'));

// Virtual keyboard: on Chrome Android, the layout itself shrinks via the viewport meta's interactive-widget=resizes-content.
// A browser that doesn't understand that value instead measures the keyboard height (--kb) via visualViewport and raises the
// whole screen by that amount. A visualViewport shrunk by pinch zoom is not the keyboard (undone by multiplying by scale).
// If an input field has focus, it's scrolled into view.
function onViewport(){const vv=window.visualViewport; if(!vv)return;
  const lh=document.documentElement.clientHeight;
  let kb=Math.round(lh-vv.height*vv.scale); if(!(kb>=80)||!MQ_COARSE.matches)kb=0;
  const R=document.documentElement.style, prev=R.getPropertyValue('--kb');
  R.setProperty('--kb',kb+'px'); R.setProperty('--vvh',(lh-kb)+'px');
  const a=document.activeElement;
  if(prev!==kb+'px'&&a&&(a.tagName==='TEXTAREA'||a.tagName==='INPUT')&&$('#right').contains(a))
    requestAnimationFrame(()=>a.scrollIntoView({block:'center'}));}
if(window.visualViewport){visualViewport.addEventListener('resize',onViewport); visualViewport.addEventListener('scroll',onViewport);}
document.addEventListener('focusin',e=>{const t=e.target;
  if(LAYOUT!=='wide'&&t&&t.tagName==='TEXTAREA'&&$('#right').contains(t))setTimeout(()=>t.scrollIntoView({block:'center'}),350);});

// Onboarding shown only the first time (remembers that it's been seen in localStorage pinPrefs.coach).
let COACH_T=null;
function coach(key,text){const seen=Object.assign({},prefs().coach||{}); if(seen[key])return; seen[key]=1; savePrefs({coach:seen});
  $('#coach-t').textContent=text; $('#coach').hidden=false; clearTimeout(COACH_T); COACH_T=setTimeout(()=>{$('#coach').hidden=true;},8000);}
function setSelMode(on){SELMODE=!!on; document.body.classList.toggle('selmode',SELMODE);
  const b=$('#btn-select'); b.setAttribute('aria-pressed',String(SELMODE)); b.querySelector('.lbl').textContent=SELMODE?'선택 중':'선택';
  if(SELMODE)coach('sel','끌어서 고칠 곳을 고르세요 · 탭하면 그 문단 · 두 손가락으로 확대');}
function openMore(){const d=$('#more'); if(d.open)return; hideTip(); renderSizeSeg(); d.showModal(); toastHost();}
// Expanding done/dropped pins from [⋯] opens the panel and scrolls to that list.
function revealList(sel,shown){if(!shown)return; setSide(true); requestAnimationFrame(()=>{const t=$(sel); if(t)t.scrollIntoView({block:'start'});});}
// Clicking outside a dialog (the backdrop) closes it - only for a click whose target is the dialog itself and that falls outside its box rectangle.
$('#more').addEventListener('click',e=>{const d=$('#more'); if(e.target!==d)return; const r=d.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});

// Panel width handle - mouse/touch/pen all share one Pointer Events path (replacing the old desktop-only mousedown
// implementation). The handle has touch-action:none, so dragging it never fights browser scrolling, and
// setPointerCapture keeps tracking it even outside the handle. While dragging, only the width changes (the body's
// page width stays put); relayout runs once on release. A tap (double-click for mouse) cycles presets, Left/Right moves
// 16px, Home/End go to the limits, and Enter/Space cycles presets.
(function(){const g=$('#grip'); let D=null;
  g.addEventListener('pointerdown',e=>{if(LAYOUT==='narrow'||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault(); D={id:e.pointerId,x:e.clientX,w:curSideW(),moved:false,mouse:e.pointerType==='mouse'};
    try{g.setPointerCapture(e.pointerId);}catch(_){}
    g.classList.add('on'); document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(!D||e.pointerId!==D.id)return; const dx=D.x-e.clientX;
    if(!D.moved&&Math.abs(dx)<4)return; D.moved=true; const b=sideBounds(LAYOUT,innerWidth); showSideW(clampSide(D.w+dx,b),b);});
  const end=e=>{if(!D||e.pointerId!==D.id)return; const d=D; D=null; g.classList.remove('on'); document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){applySideWidth(); relayout(); return;}
    if(d.moved)setSideWidth(curSideW()); else if(!d.mouse&&Date.now()>=SWALLOW_CLICK)cycleSideWidth();};
  g.addEventListener('pointerup',end); g.addEventListener('pointercancel',end);
  g.addEventListener('dblclick',()=>cycleSideWidth());
  g.addEventListener('keydown',e=>{if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth),w=curSideW();
    const k={ArrowLeft:w+16,ArrowRight:w-16,Home:b.max,End:b.min}[e.key];
    if(k!==undefined){e.preventDefault(); setSideWidth(k);} else if(e.key==='Enter'||e.key===' '){e.preventDefault(); cycleSideWidth();}});
})();
// Outline width is independent of the right work panel's handle. While dragging, only the width changes; the PDF position is restored when it ends.
(function(){const g=$('#outline-grip');let D=null;
  g.addEventListener('pointerdown',e=>{if(LAYOUT==='narrow'||document.body.classList.contains('outline-collapsed')||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault();D={id:e.pointerId,x:e.clientX,w:Math.round($('#outline').getBoundingClientRect().width)};
    try{g.setPointerCapture(e.pointerId);}catch(_){}g.classList.add('on');document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(D&&e.pointerId===D.id)showOutlineWidth(D.w+e.clientX-D.x);});
  const end=e=>{if(!D||e.pointerId!==D.id)return;D=null;g.classList.remove('on');document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){applyOutlineState();relayout();}else setOutlineWidth($('#outline').getBoundingClientRect().width);};
  g.addEventListener('pointerup',end);g.addEventListener('pointercancel',end);
  g.addEventListener('keydown',e=>{if(LAYOUT==='narrow')return;const b=outlineBounds(),w=Math.round($('#outline').getBoundingClientRect().width);
    const next={ArrowLeft:w-16,ArrowRight:w+16,Home:b.min,End:b.max}[e.key];
    if(next!==undefined){e.preventDefault();setOutlineWidth(next);}});
})();
// Sheet height handle (narrow) - dragging up raises it (a collapsed sheet expands); dropping it below 25% of the screen collapses it. A tap cycles presets.
(function(){const g=$('#sheet-grip'); let D=null;
  g.addEventListener('pointerdown',e=>{if(LAYOUT!=='narrow'||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault(); D={id:e.pointerId,y:e.clientY,h:$('#right').getBoundingClientRect().height,moved:false};
    try{g.setPointerCapture(e.pointerId);}catch(_){}
    g.classList.add('on'); document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(!D||e.pointerId!==D.id)return; const dy=D.y-e.clientY;
    if(!D.moved&&Math.abs(dy)<6)return; D.moved=true;
    if(!SIDE_OPEN&&dy>0)setSide(true);
    if(SIDE_OPEN)document.documentElement.style.setProperty('--sheet-f',String(Math.max(0.12,(D.h+dy)/innerHeight)));});
  const end=e=>{if(!D||e.pointerId!==D.id)return; const d=D; D=null; g.classList.remove('on'); document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){applySheet(); return;}
    if(!d.moved){if(Date.now()<SWALLOW_CLICK)return; if(!SIDE_OPEN)setSide(true,true); else cycleSheet(); return;}
    if(!SIDE_OPEN){applySheet(); return;}
    const f=$('#right').getBoundingClientRect().height/innerHeight;
    if(f<SHEET_CLOSE_F){applySheet(); setSide(false,true); return;}
    setSheetF(f);};
  g.addEventListener('pointerup',end); g.addEventListener('pointercancel',end);
  g.addEventListener('keydown',e=>{if(LAYOUT!=='narrow')return; const f=sheetF();
    if(e.key==='ArrowUp'){e.preventDefault(); setSheetF(f+0.05);} else if(e.key==='ArrowDown'){e.preventDefault(); setSheetF(f-0.05);}
    else if(e.key==='Enter'||e.key===' '){e.preventDefault(); cycleSheet();}});
})();

// ------------------------------------------------ Drag selection (mouse/touch/pen - one Pointer Events path)
// Mouse: press and drag draws a rectangle, as before. Touch/pen: a drag draws a rectangle only in selection mode
// (SELMODE), and a tap does quick selection; outside selection mode, scroll/pinch zoom work as usual and a
// long-press does quick selection. Only pages get touch-action:none in selection mode (a one-finger drag is
// handled by this code, two fingers by the app zoom - §PDF 영역 전용 확대).
// Coordinates are computed as fractions within the page from clientX/Y and getBoundingClientRect on the same
// basis (the layout viewport), so they stay correct even during a pinch zoom.
let DRAG=null,LP=null;
const c01=v=>Math.min(1,Math.max(0,v));
const LONGPRESS_MS=450,TAP_SLOP=8,QUICK_W=0.07,QUICK_H=0.006;
function fracAt(pg,cx,cy){const r=pg.getBoundingClientRect(); return [c01((cx-r.left)/r.width),c01((cy-r.top)/r.height)];}
function newBox(pg){const b=document.createElement('div'); b.className='sel'; pg.appendChild(b); return b;}
function drawBox(box,sx,sy,x,y){Object.assign(box.style,{left:Math.min(sx,x)*100+'%',top:Math.min(sy,y)*100+'%',
  width:Math.abs(x-sx)*100+'%',height:Math.abs(y-sy)*100+'%'});}
function cancelDrag(){if(DRAG&&DRAG.box)DRAG.box.remove(); DRAG=null;}
function cancelLP(){if(LP){clearTimeout(LP.t); LP=null;}}
// Prevents the default behavior of a mouse press on a page (focus shift, image dragging), as the old mousedown did - the note field's focus is preserved.
$('#doc').addEventListener('mousedown',e=>{if(e.button===0&&e.target.closest('.pg'))e.preventDefault();});
$('#doc').addEventListener('pointerdown',e=>{
  if(e.target.closest('.mark b'))return;
  if(!e.isPrimary){cancelDrag(); cancelLP(); return;}   // a second finger = a pinch - the box being drawn is discarded
  const pg=e.target.closest('.pg'); if(!pg)return;
  const mouse=e.pointerType==='mouse';
  if(mouse&&e.button!==0)return;
  if(mouse||SELMODE){const [sx,sy]=fracAt(pg,e.clientX,e.clientY);
    DRAG={pg,sx,sy,id:e.pointerId,mouse,cx:e.clientX,cy:e.clientY,box:mouse?newBox(pg):null};
    if(!mouse){try{pg.setPointerCapture(e.pointerId);}catch(_){}}
    return;}
  cancelLP();
  LP={id:e.pointerId,pg,cx:e.clientX,cy:e.clientY,t:setTimeout(()=>{const L=LP; LP=null; if(L)quickPick(L.pg,L.cx,L.cy);},LONGPRESS_MS)};
});
window.addEventListener('pointermove',e=>{
  if(LP&&e.pointerId===LP.id&&Math.hypot(e.clientX-LP.cx,e.clientY-LP.cy)>10)cancelLP();
  if(!DRAG||e.pointerId!==DRAG.id)return;
  if(!DRAG.box){if(Math.hypot(e.clientX-DRAG.cx,e.clientY-DRAG.cy)<TAP_SLOP)return; DRAG.box=newBox(DRAG.pg);}
  const [x,y]=fracAt(DRAG.pg,e.clientX,e.clientY); drawBox(DRAG.box,DRAG.sx,DRAG.sy,x,y);});
window.addEventListener('pointerup',e=>{
  if(LP&&e.pointerId===LP.id)cancelLP();
  if(!DRAG||e.pointerId!==DRAG.id)return;
  const D=DRAG; DRAG=null;
  if(!D.box){quickPick(D.pg,e.clientX,e.clientY);return;}   // a tap in selection mode = quick selection
  const [x,y]=fracAt(D.pg,e.clientX,e.clientY); finishRect(D.pg,D.box,D.sx,D.sy,x,y);});
window.addEventListener('pointercancel',e=>{if(LP&&e.pointerId===LP.id)cancelLP(); if(DRAG&&e.pointerId===DRAG.id)cancelDrag();});
// Quick selection: calls the existing /api/pick with a small box around the pressed point (page width +-7%, height
// +-0.6% ~ one line). The server's default level is used as-is - 'paragraph' in body text, 'environment' inside a
// figure/table - and then widened or narrowed via the range ladder.
function quickPick(pg,cx,cy){const [x,y]=fracAt(pg,cx,cy);
  finishRect(pg,newBox(pg),c01(x-QUICK_W),c01(y-QUICK_H),c01(x+QUICK_W),c01(y+QUICK_H));}
function finishRect(pg,box,sx,sy,x,y){
  const w=Math.abs(x-sx),h=Math.abs(y-sy);
  if(w<0.004&&h<0.004){box.remove();return;}
  drawBox(box,sx,sy,x,y);
  box.classList.add('pending');
  if(REPICK){ if(REPICK.box)REPICK.box.remove(); REPICK.box=box; box.innerHTML='<i>새 위치</i>'; }
  else { if(PENDING)PENDING.remove(); PENDING=box; box.innerHTML='<i>새 핀</i>'; }
  const page=+pg.dataset.page,p=META.pages[page-1];
  pick({page,x0:Math.min(sx,x)*p.pt_w,y0:Math.min(sy,y)*p.pt_h,x1:Math.max(sx,x)*p.pt_w,y1:Math.max(sy,y)*p.pt_h,
    frac:[Math.min(sx,x),Math.min(sy,y),w,h],pdf_build:META.pages_build||undefined,doc:DOC||undefined});}
// If the sheet/panel covers the selection box, the body scrolls up until the box is visible (compact only).
function revealBox(box){if(!box||LAYOUT==='wide'||!document.contains(box))return;
  const L=$('#left'),lr=L.getBoundingClientRect(),br=box.getBoundingClientRect();
  let bottom=lr.bottom; if(LAYOUT==='narrow'&&SIDE_OPEN)bottom=Math.min(bottom,$('#right').getBoundingClientRect().top);
  const top=lr.top+28; if(br.top>=top&&br.bottom<=bottom-8)return;
  L.scrollTop+=br.top-top-Math.max(0,(bottom-top-br.height)/3);}

// ------------------------------------------------ Range levels
function lvOf(obj,key){return (obj.levels||[]).find(l=>l.level===key||(l.merged||[]).includes(key));}
function kindFor(scope,env){if(!scope)return null; if(scope.startsWith('env'))return 'env:'+(env||'?');
  return scope==='para'?'paragraph':'lines';}
function scopeLabel(o){const lv=o.scope&&lvOf(o,o.scope); if(lv)return levelLabel(lv.label); if(o.scope==='lines')return tr('줄 직접 지정');
  return tr(({float:'그림/표',block:'환경 블록',paragraph:'문단',none:'생성 파일',lines:'줄'})[o.kind]||o.kind||'');}
// Range-level labels come from the server in Korean ('드래그한 줄', '문단', '환경 table', '환경 table (바깥)').
function levelLabel(s){s=String(s||''); if(LANG!=='en')return s; const m=/^환경 (.+?)( \(바깥( 2)?\))?$/.exec(s);
  return m?tl(m[3]?'환경 {env} (바깥 2)':m[2]?'환경 {env} (바깥)':'환경 {env}',{env:m[1]}):tr(s);}
// Shows the level matching the current range as pressed. If scope is set, that level (when the range also matches); otherwise the first level whose lo/hi match
// (shown as '지금 범위' on an edit card).
function curLevel(o){const ls=o.levels||[];
  const s=o.scope&&lvOf(o,o.scope); if(s&&s.lo===o.lo&&s.hi===o.hi)return s;
  return ls.find(l=>l.lo===o.lo&&l.hi===o.hi)||null;}
// Line-range notation: 'L159' for a single line, 'L155-L173' for multiple (the copy/pins.md format 'L159-L159' is left as-is).
function rng(lo,hi){return 'L'+lo+(hi!==lo?'-L'+hi:'');}
// Segment-control labels are kept short - '환경 abstract' -> 'abstract'. When the same environment name appears more than
// once, '(바깥)' is kept to distinguish them. The line range is left out of the label, going instead into the description (data-tip)/aria-label and the location line.
function levelName(lv,all){if(!lv.env)return levelLabel(lv.label);
  const dup=(all||[]).filter(o=>o.env===lv.env).length>1; return dup?levelLabel(lv.label).replace(/^(환경|Environment) /,''):lv.env;}
function levelBtns(o,isEdit){const cur=curLevel(o),ls=o.levels||[]; return ls.map(lv=>{const on=lv===cur;
  const tip=isEdit&&lv.level==='raw'?T.cur:(lv.level.startsWith('env')?T.env:T[lv.level]);
  const label=isEdit&&lv.level==='raw'?tr('지금 범위'):levelName(lv,ls),nl=tl('{n}줄',{n:lv.n});
  return '<button class="'+(on?'on':'')+'" data-act="level" data-level="'+esc(lv.level)+'" aria-pressed="'+on+'" aria-label="'+
    esc(label+' '+rng(lv.lo,lv.hi)+' · '+nl)+'" data-tip="'+esc(rng(lv.lo,lv.hi)+' · '+tr(tip))+'">'+
    esc(label)+' <span class="k'+(lv.n>50?' wn':'')+'">· '+esc(nl)+'</span></button>';}).join('');}
// Scrolls a horizontally overflowing segment control so the selected segment is visible (vertical scroll is left untouched).
function segReveal(seg){const on=seg&&seg.querySelector('.on'); if(!on){segFade(seg);return;}
  const l=on.offsetLeft,r=l+on.offsetWidth;
  if(l<seg.scrollLeft)seg.scrollLeft=Math.max(0,l-4); else if(r>seg.scrollLeft+seg.clientWidth)seg.scrollLeft=r-seg.clientWidth+4;
  segFade(seg);}
// If the range ladder is longer than the panel, the overflowing edge is faded - since the scrollbar is hidden, the right-side
// segment (after 'minipage - 43 lines') used to just get clipped with no indication there was more (QA 2026-09-24). The same idea as the document-links row (docLinksFade).
function segFade(seg){if(!seg)return; const over=seg.scrollWidth-seg.clientWidth;
  seg.classList.toggle('fade-l',over>1&&seg.scrollLeft>1); seg.classList.toggle('fade-r',over>1&&over-seg.scrollLeft>1);}
document.addEventListener('scroll',e=>{const t=e.target; if(t&&t.classList&&t.classList.contains('seg'))segFade(t);},true);
function useLevel(o,key){const lv=lvOf(o,key); if(!lv)return; o.lo=lv.lo;o.hi=lv.hi;o.scope=lv.level;o.env=lv.env||null;o.snippet=lv.snippet;}
function nudge(o,dir){let lo=o.lo,hi=o.hi; const max=o.n_lines||hi+1;
  if(dir==='up-grow')lo=Math.max(1,lo-1); else if(dir==='up-shrink')lo=Math.min(hi,lo+1);
  else if(dir==='down-grow')hi=Math.min(max,hi+1); else if(dir==='down-shrink')hi=Math.max(lo,hi-1);
  if(lo===o.lo&&hi===o.hi)return false; o.lo=lo;o.hi=hi;o.scope='lines';o.env=null;return true;}
let snipT=null;
function refetchSnip(o,after){clearTimeout(snipT); snipT=setTimeout(async()=>{
  try{const {data}=await api(dq('/api/snippet?file='+encodeURIComponent(o.file)+'&lo='+o.lo+'&hi='+o.hi,o.doc),{what:'원문 읽기'});
    if(data.lo===o.lo&&data.hi===o.hi){o.snippet=data.snippet;after();}}catch(e){}},250);}
function snipText(text,open){const ls=String(text||'').split('\n');
  return (open||ls.length<=8)?ls.join('\n'):ls.slice(0,8).join('\n')+'\n      … '+tl('{n}줄 접힘',{n:ls.length-8});}
// Location match-rate badge: hidden at 90% or above (a number on a location you can trust is just noise). Below that, '위치 불확실';
// below 30%, the warning color. The method used, match rate, and what to check go in the description instead ('match 100%' alone was meaningless). Shared by the composer panel and cards.
const VIA_HIDE=90,VIA_WARN=30;
function viaTag(p){if(!p.via)return null; const pct=Math.round((+p.score||0)*100);
  if(pct>=VIA_HIDE)return null; const low=pct<VIA_WARN;
  const how=p.via==='synctex'?tr('좌표로 찾음'):(p.via==='text'?tr('글자로 찾음'):tl('찾은 방법: {via}',{via:p.via}));
  const why=tr(p.via==='text'?T.text:T.synctex);
  return {t:tr('위치 불확실'),tip:tl('{how} · 일치 {pct}% — {why}',{how,pct,why})+(low?' '+tr('많이 어긋났을 수 있습니다.'):''),low};}

// ------------------------------------------------ composer
function setBusy(on){$('#c-spin').hidden=!on; $('#c-body').classList.toggle('busy',on);}
async function pick(r){
  const seq=++PICKSEQ,rp=REPICK;
  // When a new selection (not a re-place) starts, the previous CUR is cleared right away - so that a [핀 저장] within
  // this window (~1.1s) never silently saves the stale CUR, and instead goes through the PEND_SAVE queue (§P0c) to
  // save the just-chosen new location (regression: the old location used to get saved on a re-select).
  if(rp){banner('<span>되짚는 중…</span>');} else {CUR=null; $('#composer').hidden=false; setBusy(true); PICKING=true; $('#c-err').hidden=true; $('#c-body').hidden=false;
    if(LAYOUT!=='wide'){setSide(true); $('#right').scrollTop=0; revealBox(PENDING);}}
  let d;
  try{d=(await api('/api/pick',{method:'POST',body:r,what:'위치 찾기'})).data;}
  catch(e){if(seq!==PICKSEQ)return; setBusy(false); if(!rp){PICKING=false; clearPendingSave();}
    if(rp){bannerRepick();} else {if(PENDING){PENDING.remove();PENDING=null;} if(!CUR)$('#composer').hidden=true;} return;}
  if(seq!==PICKSEQ)return;
  setBusy(false); if(!rp)PICKING=false;
  if(d.error){
    if(d.pdf_build_gone){try{await refreshDoc();}catch(e){} if(rp&&rp.box){rp.box.remove();rp.box=null;} else if(!rp&&PENDING){PENDING.remove();PENDING=null;}}
    if(rp){bannerRepick(d.error);return;}
    // Even a pending save is never carried out if pick fails - only the existing error panel is shown (regression: prevents a silent save failure).
    CUR=null; clearPendingSave(); $('#c-err').textContent=d.error; $('#c-err').hidden=false; $('#c-body').hidden=true; return;}
  if(rp){rp.cand=d; bannerCompare(); return;}
  CUR=d; CUR.scope=null; if(!isRegion(d)){useLevel(CUR,d.default_level); if(!CUR.scope){CUR.lo=d.lo;CUR.hi=d.hi;}}
  OVERLAP_DISMISSED=null;   // a freshly chosen selection - re-notified even if [별도 핀으로 저장] was pressed for a previous selection
  CUR.overlaps=overlapsFor(CUR,PINS);
  // If a pin the server saw as overlapping isn't in this tab's PINS (someone else just saved it), the list is re-fetched - loadPins recomputes overlap too.
  if((d.overlaps||[]).some(o=>!PINS.some(p=>p.id===o.id)))loadPins();
  SNIP_OPEN=false; $('#c-err').hidden=true; $('#c-body').hidden=false; renderComposer();
  $('#composer').scrollTop=0;   // so a second drag's new location/ladder never hides above the scroll (the note stays as-is)
  if(LAYOUT!=='wide')$('#right').scrollTop=0;
  // Drag -> straight into the note field. Never focused on touch - the virtual keyboard would pop up immediately and cover the range ladder and page.
  if(LAST_PTR==='mouse')$('#note').focus({preventScroll:true});
  // If [핀 저장] was pressed while pick was still slow (~1.1s), the queued save runs here (CUR has just been filled in).
  if(PEND_SAVE){clearPendingSave(); savePin();}
}
// P0b-03: if the pre-save selection (CUR) overlaps an open pin, one representative is chosen and a "append" banner
// is drawn. Never auto-merged - the user picks between [메모에 덧붙이기]/[별도 핀으로 저장].
// Overlap is recomputed against this tab's PINS every time the range changes (drag/level switch/up-down). Computing
// it only once at pick time meant switching levels to produce the exact same range as an existing pin never showed
// the banner, and a duplicate pin got saved (observed). The rule matches the server's selection_rel (a regression
// test compares them): equal (same range) - inside (selection is inside the pin) - contains (selection wraps the pin) - partial.
function selRel(lo,hi,blo,bhi){
  if(hi<blo||bhi<lo)return null;
  if(lo===blo&&hi===bhi)return 'equal';
  if(blo<=lo&&hi<=bhi)return 'inside';
  if(lo<=blo&&bhi<=hi)return 'contains';
  return 'partial';
}
function overlapsFor(o,pins){const out=[]; if(!o||!o.file)return out;   // a selection on a view-only PDF has no line
  (pins||[]).forEach(p=>{if(p.done||p.file!==o.file)return; const rel=selRel(o.lo,o.hi,p.lo,p.hi);
    if(rel)out.push({id:p.id,lo:p.lo,hi:p.hi,rel:rel});});
  return out;}
// One representative: same range > inside (the narrowest enclosing pin) > contains (the widest inner pin) > overlap (the smallest id).
function pickOverlap(ovs){
  if(!ovs||!ovs.length)return null;
  const eq=ovs.filter(o=>o.rel==='equal');
  if(eq.length)return eq.reduce((a,b)=>b.id<a.id?b:a);
  const insides=ovs.filter(o=>o.rel==='inside');
  if(insides.length)return insides.reduce((a,b)=>(b.hi-b.lo)<(a.hi-a.lo)?b:a);
  const contains=ovs.filter(o=>o.rel==='contains');
  if(contains.length)return contains.reduce((a,b)=>(b.hi-b.lo)>(a.hi-a.lo)?b:a);
  const partials=ovs.filter(o=>o.rel==='partial');
  if(partials.length)return partials.reduce((a,b)=>b.id<a.id?b:a);
  return null;
}
// Overlap-banner wording: what relationship the selection has to that pin - '#4와 같은 범위' - '#4 범위 안' - '#4를 감쌈' - '#4와 일부 겹침'.
// The whole banner sentence in the UI language: '열린 핀 #4와 같은 범위입니다' / 'Same range as open pin #4'.
function overlapText(rel,id){const k={equal:'열린 핀 #{id}{p} 같은 범위입니다',inside:'열린 핀 #{id} 범위 안입니다',contains:'열린 핀 #{id}{p} 감쌉니다',
    partial:'열린 핀 #{id}{p} 일부 겹칩니다'}[rel]||'열린 핀 #{id}{p} 겹칩니다';
  return tl(k,{id,p:rel==='contains'?josa(id,'을','를'):josa(id,'과','와')});}
// [별도 핀으로 저장] turns off "that relationship with that pin" (id:rel). Re-announced if changing the range changes the
// relationship, and reset on a fresh drag (pick) - prevents a regression where one press permanently silenced it for every later selection.
let OVERLAP_DISMISSED=null;
function recomputeOverlap(){if(CUR)CUR.overlaps=overlapsFor(CUR,PINS);}
function renderOverlapBanner(){
  const box=$('#c-overlap'); const d=CUR;
  const ov=d?pickOverlap(d.overlaps):null;
  if(!ov||OVERLAP_DISMISSED===ov.id+':'+ov.rel){box.hidden=true;return;}
  box.hidden=false; box.dataset.rel=ov.rel;
  box.innerHTML='<span>'+overlapText(ov.rel,ov.id)+' <span class="dim">(L'+ov.lo+'-L'+ov.hi+')</span></span>'+
    '<button class="btn-sm" data-act="overlap-append" data-oid="'+ov.id+'" data-tip="'+tl('이 선택의 메모를 #{id} 에 덧붙이고, 지금 선택은 새 핀으로 만들지 않습니다',{id:ov.id})+'">'+
    tl('#{id} 메모에 덧붙이기',{id:ov.id})+'</button>'+
    '<button class="btn-sm" data-act="overlap-separate" data-key="'+ov.id+':'+ov.rel+'" data-tip="겹쳐도 별도 핀으로 저장합니다">별도 핀으로 저장</button>';
}
// Location is one line: 'file L159' + page + match badge + [copy]. Range kind/line count are never repeated, since the
// segment control's selected segment already shows them (if adjusted directly via up/down and it doesn't match any
// segment, '줄 직접 지정' is appended next to the page). The dragged line goes into the description.
// Selection on a view-only PDF: the location is '쪽 N - 영역', and the region's text (pdftotext) is shown in the source field. The range ladder/stepper are hidden.
function renderRegionComposer(d){
  $('#composer').classList.add('region');
  $('#c-loc').textContent=d.name+' · '+tl('쪽 {page} 영역',{page:d.page}); $('#c-loc').dataset.copy=d.name+' 쪽 '+d.page;
  const pg=$('#c-page'); pg.textContent=tr('보기 전용'); pg.dataset.tip='LaTeX 소스가 없는 PDF입니다 — 줄 번호 없이 쪽·영역과 영역 글자로 핀을 남깁니다';
  $('#c-tag').hidden=true; $('#c-warn').hidden=!d.warn; $('#c-warn').textContent=d.warn||''; $('#c-overlap').hidden=true;
  $('#c-levels').innerHTML='';
  const pre=$('#c-snip'); pre.className='wrap open'; pre.textContent=d.quote?tl('영역 글자: {text}',{text:d.quote}):tr('(이 영역에는 글자가 없습니다)');
  $('#c-expand').hidden=true;}
function renderComposer(){const d=CUR; if(!d)return;
  if(isRegion(d)){renderRegionComposer(d); return;}
  $('#composer').classList.remove('region');
  const copy=d.name+' L'+d.lo+'-L'+d.hi;
  $('#c-loc').textContent=d.name+' '+rng(d.lo,d.hi); $('#c-loc').dataset.copy=copy;
  const pg=$('#c-page'),pgn=tl('{page}쪽',{page:d.page}); pg.textContent=pgn+(curLevel(d)?'':' · '+tr('줄 직접 지정'));
  pg.dataset.tip=pgn+' · '+scopeLabel(d)+' · '+tl('{n}줄',{n:d.hi-d.lo+1})+' · '+tl('드래그한 줄 {range}',{range:rng(d.raw_lo,d.raw_hi)});
  const v=viaTag(d),tg=$('#c-tag'); tg.hidden=!v; if(v){tg.textContent=v.t;tg.dataset.tip=v.tip;tg.classList.toggle('badge-warning',!!v.low);}
  $('#c-warn').hidden=!d.warn; $('#c-warn').textContent=d.warn||'';
  renderOverlapBanner();
  $('#c-levels').innerHTML=levelBtns(d,false);
  segReveal($('#c-levels'));
  const pre=$('#c-snip'); pre.className=(WRAP?'wrap':'nowrap')+(SNIP_OPEN?' open':''); pre.textContent=snipText(d.snippet,SNIP_OPEN);
  // A collapsed source is cut to 4 lines by CSS. Whether it was cut is measured after rendering (a manuscript where one long line wraps into several is common).
  const over=SNIP_OPEN||pre.scrollHeight>pre.clientHeight+2, nl=String(d.snippet||'').split('\n').length;
  pre.classList.toggle('clip',!SNIP_OPEN&&over);
  $('#c-expand').hidden=!over; $('#c-expand').textContent=SNIP_OPEN?tr('원문 접기'):tr('원문 펼치기')+(nl>1?' · '+tl('{n}줄',{n:nl}):'');
  $('#c-wrap').setAttribute('aria-pressed',String(WRAP));
}
// When a selection ends via save/cancel/append, selection mode is turned off (scrolling resumes) and the narrow sheet collapses (the body comes forward again).
// The composer panel's pin kind (fix request / question). Reverts to fix request on save or discard (the default for the next pin).
function setKind(k){KIND_NEW=k==='question'?'question':'fix';
  $$('#c-kind button').forEach(b=>{const on=b.dataset.kind===KIND_NEW; b.classList.toggle('on',on); b.setAttribute('aria-checked',String(on));});
  $('#note').placeholder=KIND_NEW==='question'?'무엇이 궁금한지 적어 주세요':'메모: 여기를 어떻게 고칠지 (비워도 됩니다)'; renderAssignNew(); qHint($('#c-qhint'),$('#note').value,KIND_NEW);}
// A note that reads like a question (docs/handbook/viewer.md §스레드와 검토 - suggesting the kind). True if it ends in ?/? or a
// Korean interrogative ending (는가/나요/까요/인가/건가/니/냐/까). A trailing period/ellipsis/closing bracket/quote and a
// trailing @-tag (e.g. '맞나요? @Bob Park') are ignored. Only judges - never changes the kind itself.
function looksQuestion(text){let t=String(text||'').trim();
  for(let i=0;i<3;i++)t=t.replace(/[\s.…~!。)\]"'”’]+$/,'').replace(/(?:\s*@[^\s@?？]+(?:\s+[A-Za-z][A-Za-z.'-]*)?)+$/,'');
  return /[?？]$/.test(t)||/(는가|나요|까요|인가|건가|니|냐|까)$/.test(t);}
// If it's a fix request but the note reads like a question, a one-line suggestion appears next to the kind control. Never
// auto-changes it - only changes on click (author feedback 2026-09-25: "...표현한 의도가 있는건가?" got saved as a fix
// request). Disappears once it becomes a question or the text no longer reads like one.
function qHint(box,text,kind){if(box)box.hidden=kind==='question'||!looksQuestion(text);}
function cancelSelection(clearNote){CUR=null; PICKSEQ++; PICKING=false; clearPendingSave(); if(PENDING){PENDING.remove();PENDING=null;}
  OVERLAP_DISMISSED=null; setBusy(false); $('#composer').hidden=true; if(clearNote){$('#note').value=''; $('#note')._mentions=null; ASSIGN_NEW.touched=false; mentionPreview($('#note')); setKind('fix');}
  if(!REPICK)setSelMode(false); if(LAYOUT==='narrow'&&!EDIT)setSide(false);}
async function appendToPin(id,text){
  const prior=PINS.find(p=>p.id===id); const priorNote=prior?(prior.note||''):'';
  try{const {data}=await api('/api/pins/'+id+'/edit',{method:'POST',body:{note_append:text},what:'메모 덧붙이기'});
    const box=PENDING; PENDING=null; cancelSelection(true); if(box)box.remove();
    toast(tl('#{id} 에 덧붙였습니다',{id}),'ok',{label:'되돌리기',fn:()=>undoAppend(id,priorNote,data.pin.rev)});
    await loadPins();
  }catch(e){}}
async function undoAppend(id,note,rev){
  try{await api('/api/pins/'+id+'/edit',{method:'POST',body:{note:note,base_rev:rev},what:'되돌리기'});
    toast(tl('#{id} 메모를 되돌렸습니다',{id}),'ok');}catch(e){} await loadPins();}
// The normal label for the save-pin button (shared by boot and clearing the pending state).
function saveBtnLabel(){return MQ_COARSE.matches?tr('핀 저장'):tr('핀 저장')+' <span class="kh">'+(IS_MAC?'⌘ Enter':'Ctrl+Enter')+'</span>';}
// P0c: pressing [핀 저장] right after a drag but before SyncTeX pick finishes (~1.1s) used to just silently vanish, since
// CUR didn't exist yet (observed). Now that save request is queued and auto-saved once pick succeeds - the note re-reads
// #note at the moment of saving (when pick resolves), picking up even characters the user edited in the meantime. If pick
// fails or the selection is canceled, the queue is cleared too. Pressing the button again cancels the pending save (a toggle) - so it can be undone without a separate cancel button.
function togglePendingSave(){if(PEND_SAVE){clearPendingSave();return;}
  PEND_SAVE=true; const btn=$('#btn-save'); btn.dataset.pending='1';
  btn.innerHTML=tr('위치 찾는 중… 저장 대기')+' <span class="spin" aria-hidden="true"></span>';}
function clearPendingSave(){if(!PEND_SAVE)return; PEND_SAVE=false;
  const btn=$('#btn-save'); delete btn.dataset.pending; btn.innerHTML=saveBtnLabel();}
async function savePin(){
  if(SAVING)return;
  if(!CUR){if(PICKING)togglePendingSave(); return;}   // pick hasn't finished yet - queue it (toggle) or cancel the pending save
  SAVING=true; const btn=$('#btn-save'); btn.disabled=true;
  const d=CUR,note=$('#note').value.trim();
  let body={file:d.file,name:d.name,page:d.page,lo:d.lo,hi:d.hi,raw_lo:d.raw_lo,raw_hi:d.raw_hi,via:d.via,score:d.score,
    frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};
  if(d.scope){body.scope=d.scope; body.kind=kindFor(d.scope,d.env);} else body.kind=d.kind;
  if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};   // view-only: page/region only
  body.doc=d.doc||DOC||undefined;
  body.kind_req=KIND_NEW;
  const mh=mentionHints($('#note')); if(mh.length)body.mentions=mh;
  renderAssignNew(); body.assignee=ASSIGN_NEW.v||'agent';   // a pin created by the viewer always records an assignee (otherwise a legacy pin's inference rule applies)
  try{const {data}=await api('/api/pin',{method:'POST',body,what:'핀 저장'});
    const id=data.id,q=KIND_NEW==='question'; const box=PENDING; PENDING=null; cancelSelection(true); if(box)box.remove();
    if(SEC_SEEN.open)SEC_SEEN.open.add(id);   // my own new pin is never 'new' on a collapsed header
    toast(tl(q?'질문 #{id} 저장됨 · pins.md 갱신':'핀 #{id} 저장됨 · pins.md 갱신',{id}),'ok',{label:'되돌리기',fn:()=>dropPin(id,true)});
    await loadPins();
  }catch(e){} finally{SAVING=false; btn.disabled=false;}
}

// ------------------------------------------------ Pin list
function who(a){if(a&&a.login==='local')return tr(a.name||'로컬/에이전트'); return (a&&(a.name||a.login))||'';}   // the stored local name is Korean ('로컬/에이전트'); shown in the UI language
const BADPIC=new Set();   // an avatar URL that has already failed is never requested again (otherwise console errors would pile up on every re-render)
// A person = a photo or an initial circle (primary color); local/agent = a faded circle with a robot icon - distinguishes people from agents at a glance.
function isAgent(a){return !!a&&(a.login==='local'||String(a.login).startsWith('agent:'));}
function avatar(a){if(!a||!(a.name||a.login))return ''; if(isAgent(a))return '<span class="av i agent" aria-hidden="true">'+ic('bot')+'</span>';
  const ini=esc((who(a).trim()[0]||'?').toUpperCase());
  return a.pic&&!BADPIC.has(a.pic)?'<img class="av" src="'+esc(a.pic)+'" alt="" referrerpolicy="no-referrer" data-ini="'+ini+'">'
    :'<span class="av i" aria-hidden="true">'+ini+'</span>';}
document.addEventListener('error',e=>{const t=e.target;
  if(t&&t.tagName==='IMG'&&t.classList.contains('av')){BADPIC.add(t.getAttribute('src')); const s=document.createElement('span');s.className='av i';
    s.textContent=t.dataset.ini||'?';t.replaceWith(s);}},true);
function authorTip(p){let s=tl('작성: {name} · {at}',{name:p.author?who(p.author):tr('기록 전'),at:p.at||'?'});
  if(p.edited_at)s+=' / '+tl('수정: {name} · {at}',{name:who(p.edited_by)||tr('기록 전'),at:p.edited_at}); return s;}
// P0b-03: one representative among the rel entries - if there's an inside (the outer pin with the smallest range),
// otherwise the smallest-id partial. Must follow the same rule as the server's rel_badge() (pins.md) so card tags and
// pins.md rows never disagree - since a rel entry is only {id,rel}, the range is looked up by id from PINS (all currently loaded open pins).
// The badge wording is phrased to be self-explanatory: '#20과 같은 범위' > '#20 범위 안' > '#20과 일부 겹침'. Same-range is distinguished using p's (this pin's) lo/hi.
function josa(n,c,v){const d=String(n).slice(-1); return d==='0'||'13678'.includes(d)?c:v;}
function relBadge(rel,p){
  if(!rel||!rel.length)return null;
  const byId=new Map(PINS.map(p=>[p.id,p]));
  if(p){const same=rel.filter(x=>{const o=byId.get(x.id); return o&&o.lo===p.lo&&o.hi===p.hi;});
    if(same.length){const n=Math.min.apply(null,same.map(x=>x.id)); return {id:n,rel:'equal',label:tl('#{id}{p} 같은 범위',{id:n,p:josa(n,'과','와')})};}}
  const insides=rel.filter(x=>x.rel==='inside');
  if(insides.length){
    const span=x=>{const o=byId.get(x.id); return o?(o.hi-o.lo):Number.MAX_SAFE_INTEGER;};
    const best=insides.reduce((a,b)=>{const sa=span(a),sb=span(b);
      return (sb<sa||(sb===sa&&b.id<a.id))?b:a;});
    return {id:best.id,rel:'inside',label:tl('#{id} 범위 안',{id:best.id})};
  }
  const partials=rel.filter(x=>x.rel==='partial').sort((a,b)=>a.id-b.id);
  if(partials.length){const n=partials[0].id; return {id:n,rel:'partial',label:tl('#{id}{p} 일부 겹침',{id:n,p:josa(n,'과','와')})};}
  return null;
}
// §P0c-C: the in-progress marker. claim_until is epoch seconds, compared independent of the browser's timezone (numbers
// instead of a wall-clock string, for the same reason as §Position estimation). The viewer never places a claim (agent-only) - it only offers [풀기].
function claimActive(p){return typeof p.claim_until==='number'&&p.claim_until>Date.now()/1000;}
// Estimated time to handle (docs/handbook/api.md §처리 중 표시): if an agent gives eta_min on a claim, the server sets eta_ts
// (epoch). The badge shows '처리 중 · 약 15분 · 20:40쯤' - both the remaining minutes and the time are rounded up to
// 5-minute steps (an estimate is approximate). Past it, '예상보다 늦어짐 (+5분)'. A legacy claim with no eta shows
// '처리 중 · 20:02부터 (23분째)'. The lock's auto-expiry (claim_until) was misread as the estimated completion (observed:
// '~04:02'), so it's never shown on screen - only in the description. The time is the viewing device's local time. now is injected by tests.
function ceil5(m){return Math.max(5,Math.ceil(m/5-1e-9)*5);}
function hhmm(ms){const d=new Date(ms); return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');}
function claimInfo(p,now){now=now==null?Date.now():now; const w=who(p.claimed_by)||'?',st=typeof p.claim_ts==='number'?p.claim_ts*1000:null;
  const tail=' · '+tl('잠금 자동 해제 {time}(그 뒤에는 다른 쪽이 잡을 수 있습니다). 에이전트가 멈췄으면 [풀기]',{time:hhmm(p.claim_until*1000)});
  const head=tl('처리하는 쪽: {name}',{name:w})+(st?' · '+tl('시작 {time}',{time:hhmm(st)}):'');
  if(typeof p.eta_ts==='number'){const eta=p.eta_ts*1000;
    if(now<=eta)return {t:tl('처리 중 · 약 {n}분 · {time}쯤',{n:ceil5((eta-now)/60000),time:hhmm(Math.ceil(eta/300000)*300000)}),late:false,
      tip:head+' · '+tl('예상 완료 {time}',{time:hhmm(eta)})+tail};
    return {t:tl('예상보다 늦어짐 (+{n}분)',{n:ceil5((now-eta)/60000)}),late:true,tip:head+' · '+tl('예상 완료 {time}였음',{time:hhmm(eta)})+tail};}
  if(st)return {t:tl('처리 중 · {time}부터 ({n}분째)',{time:hhmm(st),n:Math.max(1,Math.ceil((now-st)/60000))}),late:false,tip:head+' · '+tr('예상 시간 없음')+tail};
  return {t:tr('처리 중'),late:false,tip:head+tail};}
function claimLabel(p,now){return claimInfo(p,now).t;}
function claimTag(p){const c=claimInfo(p);
  return '<span class="badge badge-claimed'+(c.late?' late':'')+'" data-claim="'+p.id+'" data-tip="'+esc(c.tip)+'">'+ic('clock')+'<span class="ct">'+esc(c.t)+'</span></span>';}
// The remaining/elapsed minutes change with time - only the badge text is updated every 30 seconds (the card isn't redrawn). The list is redrawn if any pin's lock has expired.
function tickClaims(){if(document.hidden)return; let gone=false;
  $$('.badge-claimed[data-claim]').forEach(el=>{const p=OPEN_ALL.find(x=>x.id===+el.dataset.claim);
    if(!p||!claimActive(p)){gone=true; return;} const c=claimInfo(p); el.querySelector('.ct').textContent=c.t; el.dataset.tip=c.tip; el.classList.toggle('late',c.late);});
  if(gone)drawPins();}
setInterval(tickClaims,30000);
// A card's location text: 'L12-L18' for a LaTeX pin, '영역' for a view-only PDF's pin (the page is a separate field). The copy format is 'file L12-L18' / 'x.pdf 쪽 3'.
function locText(p){return isRegion(p)?tr('영역'):rng(p.lo,p.hi);}
function locCopy(p){const name=p.name||String(p.file||p.pdf||'').split('/').pop(); return isRegion(p)?name+' 쪽 '+p.page:name+' L'+p.lo+'-L'+p.hi;}
// The document chip attached to a card header when viewing all documents. Another document's is dashed-bordered - clicking it switches to that document.
function docChip(p){if(!(SHOW_ALL&&multiDoc()))return ''; const d=docInfo(pdoc(p)),other=pdoc(p)!==DOC;
  return '<span class="badge badge-secondary dchip'+(other?' other':'')+'" data-tip="'+esc((d?d.name+' · '+d.path:tl('{doc} (설정에 없는 문서)',{doc:pdoc(p)}))+(other?' — '+tr('#번호·[보기]를 누르면 이 문서로 바꿉니다'):''))+'">'+esc(d?d.name:pdoc(p))+'</span>';}
// Thread (docs/handbook/viewer.md §스레드와 검토): replies and state-transition records (close/reopen/confirm) form a single line of history. Text goes through esc().
// wide shows the last 3, compact shows only the last 1, expanded via [이전 N건] (THREAD_OPEN). The input field (REPLY) is inserted in place like EDIT.
function isQuestion(p){return !!p&&p.kind_req==='question';}
// The current assignee - the recorded value (p.assignee); for a legacy pin without one, the person the server inferred (the first of p.addressed); if neither, the agent.
function assigneeOf(p){if(!p)return 'agent'; if(p.assignee)return p.assignee; const a=p.addressed||[]; return a.length?a[0]:'agent';}
// The card header's assignee chip: shown only when the assignee is a person (the agent is the default, so it's not shown). The author (or an identity-less local screen) changes it by clicking into [수정].
function assignChip(p){if(!p.assignee||p.assignee==='agent')return ''; const me=meLogin(),mine=p.assignee===me,nm=mine?tr('나'):'@'+(String(peopleName(p.assignee)).split(/\s+/)[0]||p.assignee);   // the chip shows the first word of the name; the full name goes in the description
  const canEdit=pinState(p)==='open'&&(isMe(p.author)||!me),tip=tl('담당: {name} — 에이전트는 이 핀을 건너뜁니다',{name:mine?tr('나'):peopleName(p.assignee)})+(canEdit?tr('. 누르면 [수정]에서 담당을 바꿉니다'):'');
  return canEdit?'<button class="badge badge-assign as-chip'+(mine?' me':'')+'" data-act="edit" data-tip="'+esc(tip)+'">'+esc(tr('담당'))+' <span class="as-n">'+esc(nm)+'</span></button>'
    :'<span class="badge badge-assign as-chip'+(mine?' me':'')+'" data-tip="'+esc(tip)+'">'+esc(tr('담당'))+' <span class="as-n">'+esc(nm)+'</span></span>';}
// Status dot (docs/handbook/viewer.md §상태 표현): color + a readable name (aria-label/description). A badge states the same meaning in text once more.
const ST_NAME={open:'열림',claimed:'처리 중',review:'검토 대기',lost:'위치 잃음'};
function stDot(st){const t=esc(tl('상태: {name}',{name:tr(ST_NAME[st])})); return '<span class="st-dot'+(st==='open'?'':' '+st)+'" role="img" aria-label="'+t+'" data-tip="'+t+'"></span>';}
// Did the current round start with a reopen (a pin that returned from review)? True if the thread's last close/reopen record is a reopen.
function reopenedTurn(p){const th=threadOf(p); for(let i=th.length-1;i>=0;i--){const e=th[i].ev; if(e==='close'||e==='reopen')return e==='reopen'?th[i]:null;} return null;}
function threadOf(p){return Array.isArray(p&&p.thread)?p.thread:[];}
function replyCount(p){return threadOf(p).filter(m=>!m.ev).length;}
function msgText(m){return fmtText(m.text,m.mentions);}
// Turns '@name' (only resolved mentions) and '#number' (an existing pin) in text into tokens (docs/handbook/viewer.md §@태그).
// Text goes through esc() first, and names/numbers are found and wrapped within that already-escaped text - so text a
// person wrote never leaks as HTML. Names are matched with the same candidates as the server's resolve_mentions() (full
// name/login/the part of the login before @/the first word of the name), longest first, case-insensitive. Skipped if the
// character before '@' is alphanumeric (an email address); a name ending in an ASCII letter followed by an ASCII letter
// (@Alicex) is a different word. An unresolved '@word' stays plain text - it must never look like it called someone.
function peopleName(login){const x=PEOPLE.find(p=>p.login===login); return x?x.name:login;}
function mentionToks(logins){const out=[]; (logins||[]).forEach(lg=>{const x=PEOPLE.find(p=>p.login===lg),nm=String((x&&x.name)||'');
    const w=nm.split(/\s+/).filter(Boolean); [nm,lg,String(lg).split('@')[0]].concat(w.length>1?[w[0]]:[]).forEach((t,k)=>{if(t&&t.length>=2)out.push({t:esc(t),lg,k});});});
  return out.sort((a,b)=>b.t.length-a.t.length||a.k-b.k);}   // for a tie in text length, full name > login > first word
function reEsc(t){return t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
function meLogin(){const me=typeof META!=='undefined'&&META&&META.me; return me&&me.login&&me.login!=='local'?me.login:null;}
function fmtText(text,logins){let h=esc(text); const toks=mentionToks(logins),hit=[],me=meLogin();
  if(toks.length){const re=new RegExp('@('+toks.map(x=>reEsc(x.t)).join('|')+')','gi');
    // First swapped for placeholders (\u0001number\u0002) - so that after a long name is wrapped, a short name never re-wraps inside it.
    h=h.replace(re,(m,t,off,all)=>{const prev=off>0?all[off-1]:''; if(prev&&/[0-9A-Za-z가-힣._-]/.test(prev))return m;
      const nx=all.charAt(off+m.length); if(/[A-Za-z0-9]$/.test(t)&&/[A-Za-z0-9_]/.test(nx))return m;
      const tk=toks.find(x=>x.t.toLowerCase()===t.toLowerCase()); if(!tk)return m; hit.push({m,lg:tk.lg}); return '\u0001'+(hit.length-1)+'\u0002';});}
  // '#12' - a link to that pin if it exists. An escape like '&#39;' (preceded by &) and '#12;' are left untouched.
  // A '#12' whose pin is in the Trash renders as '#12 deleted pin' (faded) and opens the Trash at that row.
  h=h.replace(/(^|[^&0-9A-Za-z#])#(\d{1,6})(?![\d;])/g,(m,pre,n)=>{const id=+n;
    if(pinRefExists(id))return pre+'<span class="pin-ref" role="link" tabindex="0" data-act="pin-ref" data-ref="'+id+'" data-tip="'+esc(tl('핀 #{id} 로 갑니다',{id}))+'">#'+id+'</span>';
    if(pinRefGone(id))return pre+'<span class="pin-ref gone" role="link" tabindex="0" data-act="pin-ref" data-ref="'+id+'" data-tip="'+esc(tl('핀 #{id} 은 삭제되었습니다 — 누르면 휴지통에서 봅니다',{id}))+'">#'+id+' <small>'+esc(tr('삭제된 핀'))+'</small></span>';
    return m;});
  return h.replace(/\u0001(\d+)\u0002/g,(_,k)=>{const x=hit[+k],mine=!!me&&x.lg===me;
    return '<span class="mention'+(mine?' me':'')+'" data-tip="'+esc(mine?tr('나를 부름 — 이 핀 알림이 나에게 옵니다'):tl('@태그 — {name}에게 알림이 갑니다',{name:peopleName(x.lg)}))+'">'+x.m+'</span>';});}
function pinRefExists(id){return typeof findAnyPin==='function'&&!!findAnyPin(id);}
function pinRefGone(id){return typeof DROPPED!=='undefined'&&Array.isArray(DROPPED)&&DROPPED.some(p=>p.id===id);}
// The [나를 부른 핀] filter (docs/handbook/viewer.md §@태그): uses the same material as the badge/pins.md's '→ @name'
// (p.addressed, which the server counts only for the current round via thread_round) - the old version scanned the
// entire thread (threadOf(p).some(...)) and had a defect where an @-tag from an old round kept a pin marked "called me"
// even after reopening (observed). addressed_to() only has a value on question pins.
function mentionsMe(p){const me=META&&META.me; if(!me||!me.login||me.login==='local')return false;
  return (p.addressed||[]).includes(me.login);}
function addressedTag(p){const to=(p.addressed||[]); if(!to.length)return '';
  const me=META&&META.me&&META.me.login,mine=to.includes(me),others=to.filter(x=>x!==me);
  return (mine?'<span class="badge badge-mention" data-tip="이 핀이 나를 @태그했습니다 — 에이전트는 이 핀을 건너뜁니다(사용자가 시키면 예외)">'+ic('at-sign')+'나를 부름</span>':'')+
    (others.length?'<span class="badge badge-mention" data-tip="사람을 부른 핀입니다 — 에이전트는 사용자가 따로 시키지 않으면 건너뜁니다">'+ic('at-sign')+esc(others.map(peopleName).join(', '))+'</span>':'');}
// A fix pin's FYI @-tags (never skipped) - kept separate from p.addressed (question-pin only) and sent in p.fyi instead.
function fyiTag(p){const to=(p.fyi||[]); if(!to.length)return '';
  return '<span class="badge badge-mention" data-tip="참고로 부른 사람입니다 — 질문이 아니라 수정 요청이라 건너뛰지 않습니다">'+ic('at-sign')+esc(tl('참고 {names}',{names:to.map(peopleName).join(', ')}))+'</span>';}
// Is the reference (ref) a meaningful value? '-' is a placeholder QA scripts/legacy callers use for "no reference" - shown as-is
// it would produce meaningless text like '닫음 · -' (observed defect). An empty or whitespace-only value is filtered out the same way.
function hasRef(v){return !!v&&String(v).trim()!==''&&String(v).trim()!=='-';}
const EV_LABEL={close:'닫음',reopen:'다시 엶',confirm:'확인',assign:'담당 바꿈'};
// A long post collapses at 6 lines with [더 보기] (keyed 'id:index' in MSG_OPEN). If the author is me, '(나)'.
const MSG_OPEN=new Set();
function msgBody(m,key){const long=String(m.text||'').length>280||String(m.text||'').split('\n').length>6,open=!key||MSG_OPEN.has(key);
  return '<div class="msg-t'+(long&&!open?' clamp':'')+'">'+msgText(m)+'</div>'+
    (long&&key?'<button class="btn-sm btn-ghost msg-more" data-act="msg-more" data-key="'+esc(key)+'" aria-expanded="'+open+'">'+(open?'접기':'더 보기')+'</button>':'');}
function msgHtml(m,key){const by=m.by||{},nm=who(by)||'?',mine=isMe(by)?'<span class="me-tag"> (나)</span>':'';
  if(m.ev)return '<div class="msg ev ev-'+esc(m.ev)+'"><div class="msg-h"><b>'+esc(nm)+mine+'</b><span>'+esc(tr(EV_LABEL[m.ev]||m.ev))+(hasRef(m.ref)?' · '+esc(m.ref):'')+'</span>'+relSpan(m.at)+'</div>'+
    (m.text?msgBody(m,key):'')+'</div>';
  return '<div class="msg">'+avatar(by)+'<div class="msg-b"><div class="msg-h"><b>'+esc(nm)+mine+'</b>'+relSpan(m.at)+'</div>'+msgBody(m,key)+'</div></div>';}
function threadHtml(p,wide){const th=threadOf(p),keep=wide?3:1,all=THREAD_OPEN.has(p.id),hide=all?0:Math.max(0,th.length-keep);
  let h='';
  if(hide)h+='<button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="false">'+esc(tl('이전 {n}건 보기',{n:hide}))+'</button>';
  else if(all&&th.length>keep)h+='<button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="true">스레드 접기</button>';
  h+=th.slice(hide).map((m,i)=>msgHtml(m,p.id+':'+(i+hide))).join('');
  if(REPLY&&REPLY.id===p.id)h+='<div class="reply-slot"></div>';
  return h?'<div class="thread">'+h+'</div>':'';}
function card(p){
  const loc='L'+p.lo+'-L'+p.hi,name=p.name||String(p.file||'').split('/').pop(),tags=[];   // loc stays in the copy format
  if(p.stale)tags.push('<span class="badge badge-warning" data-tip="'+esc(T.stale)+'">'+ic('triangle-alert')+'위치 잃음</span>');
  else{const m=/^moved ([+-]\d+)$/.exec(p.sync||''); if(m)tags.push('<span class="badge" data-tip="'+
    esc(tl('원고가 고쳐져 {n}줄 밀렸고, 핀을 찍을 때 떠 둔 첫·끝 문장으로 새 위치를 다시 찾았습니다',{n:m[1].replace('+','')}))+'">'+ic('move-vertical')+esc(tl('줄 {delta} 이동',{delta:m[1]}))+'</span>');}
  const claimed=claimActive(p);
  if(claimed)tags.push(claimTag(p));
  if(p.edited_at)tags.push('<span class="badge" data-tip="'+esc(tl('저장한 뒤 메모나 범위를 고쳤습니다({when})',{when:p.edited_at.slice(11,16)+
    (p.edited_by?' · '+who(p.edited_by):'')}))+'">'+ic('pencil')+esc(tr('수정됨'))+'</span>');
  const closedCard=pinState(p)!=='open';   // overlap/location-confidence badges are meaningless on an awaiting-review/done card (line matching doesn't run, QA)
  const rb=closedCard?null:relBadge(p.rel,p);
  if(rb)tags.push('<span class="badge" data-tip="'+esc(tl(rb.rel==='partial'?'핀 #{id}{p} 줄 범위가 일부 겹칩니다. 참고만 하고 따로 고쳐도 됩니다':
    '핀 #{id}{p} 같은 곳을 가리킵니다. 한 번에 고치고 함께 닫는 편이 낫습니다',{id:rb.id,p:josa(rb.id,'과','와')}))+'">'+esc(rb.label)+'</span>');
  const v=closedCard?null:viaTag(p); if(v)tags.push('<span class="badge'+(v.low?' badge-warning':'')+'" data-tip="'+esc(v.tip)+'">'+esc(v.t)+'</span>');
  const tip=esc(authorTip(p));
  const au=p.author?'<span class="au" data-tip="'+tip+'">'+avatar(p.author)+'<span class="au-n">'+esc(who(p.author))+(isMe(p.author)?'<span class="me-tag"> (나)</span>':'')+'</span></span>'
    :'<span class="au old" data-tip="'+tip+'">기록 전</span>';
  const editing=!!(EDIT&&EDIT.id===p.id),open=OPEN_CARDS.has(p.id);
  // Header line: number/line-range/page on the left, author/collapse on the right. Badges (.tags) drop to one line below the header.
  // compact accordion: a collapsed card shows only number/location/page/the note's first line (.sum); clicking expands badges/note/buttons (CSS).
  // In wide, .sum and the collapse button are hidden and the card is always expanded. Actions form an equal-width grid; only [완료] is emphasized, [삭제] is the destructive color.
  const first=String(p.note||'').split('\n')[0].trim();
  // Collapsed card's (compact) note preview: up to two lines on its own line below the header. It used to only get the
  // leftover width after the number/location inside the header's single line, clipping to '[C...', and an awaiting-review
  // card's prefixed '내 확인 차례 · ' ate even more of that width (QA 2026-09-24). Review status is conveyed by the dot color.
  const sum='<div class="sum" data-act="card-toggle">'+(first?fmtText(first,p.mentions):'<span class="dim">(메모 없음)</span>')+'</div>';
  if(isRegion(p))tags.unshift('<span class="badge" data-tip="보기 전용 PDF의 핀 — 줄 번호 없이 쪽·영역과 영역 글자로 가리킵니다">보기 전용</span>');
  if(isQuestion(p))tags.unshift('<span class="badge badge-question" data-tip="'+esc(T.question)+'">'+ic('circle-question-mark')+'질문</span>');
  const adr=p.assignee?'':addressedTag(p); if(adr)tags.push(adr);   // a pin with a recorded assignee already says the same thing via the header's assignee chip
  const fyi=fyiTag(p); if(fyi)tags.push(fyi);   // a fix pin's FYI @-tags - this line once sat after the comment above and never executed (QA 2026-09-24)
  const rv=pinState(p)==='review';
  if(rv)tags.unshift('<span class="badge badge-review" data-tip="'+esc(tr(T.review)+' · '+tl('닫은 쪽: {name}',{name:who(p.closed_by)||'?'})+' · '+(p.done_at||''))+'">'+ic('eye')+esc(reviewerLabel(p))+'</span>');
  const ro=!rv&&reopenedTurn(p);
  if(ro)tags.unshift('<span class="badge badge-reopen" data-tip="'+esc(tl('검토에서 되돌아온 핀 — {name} · {time}',{name:who(ro.by)||'?',time:arcTime(ro.at)})+(ro.text?' · '+tl('이유: {text}',{text:ro.text}):''))+'">'+ic('rotate-ccw')+'다시 열림</span>');
  const nr=replyCount(p);
  const thn=nr?'<span class="th-n" role="button" tabindex="0" data-act="reply-open" aria-label="'+esc(tl('답글 {n}건 — 답글 쓰기',{n:nr}))+'" data-tip="'+esc(tl('이 핀의 답글 {n}건 — 누르면 카드를 펴고 답글 칸을 엽니다',{n:nr}))+'">'+ic('message-square')+nr+'</span>':'';
  if(rv)return '<div class="pin card review'+(open?' open':'')+'" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'">'+
    '<div class="row head">'+stDot(rv?'review':p.stale?'lost':claimed?'claimed':'open')+'<span class="n go" role="button" tabindex="0" data-act="view" data-tip="'+esc(T.n)+'">#'+p.id+'</span>'+docChip(p)+
    '<span class="loc" tabindex="0" data-copy="'+esc(isRegion(p)?locCopy(p):name+' '+loc)+'" data-tip="'+esc(isRegion(p)?'영역이 있는 PDF 쪽. 클릭하면 복사':T.loc)+'">'+locText(p)+'</span>'+
    '<span class="pg-link" tabindex="0" data-act="view" data-tip="클릭하면 그 쪽으로 이동">'+esc(tl('{page}쪽',{page:p.page}))+'</span>'+
    '<span class="sp"></span><span class="h-meta">'+assignChip(p)+thn+au+'</span>'+
    '<button class="btn-icon btn-sm btn-ghost cmp b-fold" data-act="card-toggle" aria-expanded="'+open+'" aria-label="'+(open?'카드 접기':'카드 펼치기')+'">'+ic(open?'chevron-down':'chevron-right')+'</button></div>'+
    sum+
    '<div class="tags">'+tags.join('')+'</div>'+
    '<div class="note">'+(p.note?fmtText(p.note,p.mentions):'<span class="dim">(메모 없음)</span>')+'</div>'+
    threadHtml(p,LAYOUT==='wide')+
    '<div class="acts">'+
    '<button class="btn-sm b-change" data-act="change" data-tip="'+esc(T.change)+'">변경 보기</button>'+
    '<button class="btn-sm b-reply" data-act="reply-open" data-tip="'+esc(T.reply)+'">답글</button>'+
    '<button class="btn-sm b-confirm'+(isMe(p.author)?' btn-soft':'')+'" data-act="confirm" data-tip="'+esc(T.confirm)+'">확인</button>'+
    '</div></div>';
  return '<div class="pin card'+(p.stale?' st':'')+(claimed?' claimed':'')+(editing?' editing':'')+(open?' open':'')+'" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'">'+
    '<div class="row head">'+stDot(rv?'review':p.stale?'lost':claimed?'claimed':'open')+'<span class="n go" role="button" tabindex="0" data-act="view" data-tip="'+esc(T.n)+'">#'+p.id+'</span>'+docChip(p)+
    '<span class="loc" tabindex="0" data-copy="'+esc(isRegion(p)?locCopy(p):name+' '+loc)+'" data-tip="'+esc(isRegion(p)?'영역이 있는 PDF 쪽. 클릭하면 복사':T.loc)+'">'+locText(p)+'</span>'+
    '<span class="pg-link" tabindex="0" data-act="view" data-tip="클릭하면 그 쪽으로 이동">'+esc(tl('{page}쪽',{page:p.page}))+'</span>'+
    '<span class="sp"></span><span class="h-meta">'+assignChip(p)+thn+au+'</span>'+
    '<button class="btn-icon btn-sm btn-ghost cmp b-fold" data-act="card-toggle" aria-expanded="'+(open||editing)+'" aria-label="'+(open?'카드 접기':'카드 펼치기')+'">'+ic(open||editing?'chevron-down':'chevron-right')+'</button></div>'+
    sum+
    '<div class="tags">'+tags.join('')+'</div>'+
    (editing?'<div class="edit-slot"></div>':
    '<div class="note" data-act="edit" data-tip="클릭하면 메모와 범위를 고칩니다">'+(p.note?fmtText(p.note,p.mentions):'<span class="dim">(메모 없음)</span>')+'</div>'+
    threadHtml(p,LAYOUT==='wide')+
    '<div class="acts"><button class="btn-sm b-view" data-act="view" data-tip="'+esc(T.view)+'">보기</button>'+
    '<button class="btn-sm b-edit" data-act="edit" data-tip="'+esc(T.edit)+'">수정</button>'+
    '<button class="btn-sm b-reply" data-act="reply-open" data-tip="'+esc(T.reply)+'">답글</button>'+
    (claimed?'<button class="btn-sm b-unclaim" data-act="unclaim" data-tip="'+esc('처리 중 표시를 풉니다(에이전트가 멈췄거나 잘못 잡은 경우)')+'">풀기</button>':'')+
    '<button class="btn-sm btn-destructive b-drop" data-act="drop" data-tip="'+esc(T.drop)+'">삭제</button>'+
    '<button class="btn-sm btn-soft b-close" data-act="close" data-tip="'+esc(T.close)+'">완료</button>'+
    '</div>')+'</div>';
}
// Archive row (docs/handbook/viewer.md §보관함): a closed/dropped pin is a flat, borderless, backgroundless row with faded text, not a card.
// The first line is icon/#number/location/reference/time/[다시 열기|되살리기]; the second line is one line of the agent's
// answer (close_reply) - truncated on overflow, expandable on click. The original request note is only shown by pressing
// [원래 요청]. The expanded state is kept in ARC_OPEN ('r:'|'o:'|'d:' + id) so it survives a redraw.
const ARC_OPEN=new Set();
// Relative time (docs/handbook/viewer.md §뜻과 모양): '방금'/'N분 전'/'N시간 전'/'N일 전', 'M-D' past a week. Absolute time is in the description (hover).
// The original string is kept in data-at and re-computed every 60 seconds (tickRel).
function relTime(s,now){s=String(s||''); const m=/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(s); if(!m)return s;
  const t=new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5]).getTime(),d=Math.max(0,((now==null?Date.now():now)-t)/60000);
  if(d<1)return tr('방금'); if(d<60)return tl('{n}분 전',{n:Math.floor(d)}); if(d<24*60)return tl('{n}시간 전',{n:Math.floor(d/60)}); if(d<7*24*60)return tl('{n}일 전',{n:Math.floor(d/1440)});
  return (+m[2])+'-'+(+m[3]);}
function relSpan(s,cls,tip){return '<span class="rt'+(cls?' '+cls:'')+'" data-at="'+esc(s||'')+'" data-tip="'+esc((tip?tip+' ':'')+(s||'?'))+'">'+esc(relTime(s))+'</span>';}
function tickRel(){if(document.hidden)return; $$('.rt[data-at]').forEach(e=>{const v=relTime(e.dataset.at); if(e.textContent!==v)e.textContent=v;});}
setInterval(tickRel,60000);
function arcTime(s){s=String(s||''); return /^\d{4}-\d\d-\d\d \d\d:\d\d/.test(s)?s.slice(5,16):s;}
function arcLoc(p){const name=p.name||String(p.file||p.pdf||'').split('/').pop();
  return '<span class="loc" tabindex="0" data-copy="'+esc(isRegion(p)?locCopy(p):name+' L'+p.lo+'-L'+p.hi)+'" data-tip="'+esc(T.loc)+'">'+esc(isRegion(p)?tl('쪽 {page} 영역',{page:p.page}):rng(p.lo,p.hi))+'</span>';}
function arcLine(key,text,tip,logins){const open=ARC_OPEN.has(key);
  return '<span class="arc-reply'+(open?' open':'')+'" role="button" tabindex="0" data-act="arc-toggle" data-key="'+esc(key)+'" aria-expanded="'+open+'" data-tip="'+esc(tip)+'">'+fmtText(text,logins)+'</span>';}
function allMentions(p){const out=(p.mentions||[]).slice(); threadOf(p).forEach(m=>(m.mentions||[]).forEach(l=>{if(!out.includes(l))out.push(l);})); return out;}
function doneCard(p){
  const ref=hasRef(p.close_ref)?'<span class="badge arc-ref" data-tip="닫을 때 남긴 참조 — 같은 값이면 같은 처리에 딸린 핀입니다">'+esc(p.close_ref)+'</span>':'';
  const reply=p.close_reply?arcLine('r:'+p.id,p.close_reply,'닫으며 남긴 설명 — 누르면 펼치고 접습니다',allMentions(p)):'<span class="arc-reply none">설명 없이 닫힘</span>';
  const oo=ARC_OPEN.has('o:'+p.id);
  // If the thread is longer than a single close record (there was a reply/reopen), it expands via [스레드 N] - with only
  // one record, it's the same as the single answer line above. [답글] opens the same reply box as a card (openReply): a person's
  // reply on a done pin reopens it by the server rule, and the line under the box says so before sending. The thread is kept
  // expanded while replying so the box is visible.
  const replying=REPLY&&REPLY.id===p.id;
  const th=threadOf(p),tn=th.length>1||(th.length>0&&!th[0].ev),to=(tn&&ARC_OPEN.has('t:'+p.id))||replying;
  return '<div class="arc-row done" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'" data-tip="'+esc(authorTip(p))+'">'+
    '<div class="arc-l1">'+ic('check')+'<span class="n" data-tip="완료한 핀 번호">#'+p.id+'</span>'+docChip(p)+arcLoc(p)+ref+
    relSpan(p.done_at,'arc-t',tl('닫은 사람 {name} · 닫은 시각',{name:who(p.closed_by)||tr('기록 전')}))+'<span class="sp"></span>'+
    '<button class="btn-sm btn-secondary arc-b b-reply" data-act="reply-open" data-tip="'+esc(T.reply)+'">답글</button></div>'+
    '<div class="arc-l2">'+reply+(p.note?'<button class="arc-orig-t" data-act="arc-toggle" data-key="o:'+p.id+'" aria-expanded="'+oo+'" data-tip="핀을 남길 때 쓴 메모를 펼치고 접습니다">원래 요청</button>':'')+
    '<button class="arc-orig-t b-change" data-act="change" data-tip="'+esc(T.change)+'">변경 보기</button>'+
    (tn?'<button class="arc-orig-t" data-act="arc-toggle" data-key="t:'+p.id+'" aria-expanded="'+to+'" data-tip="답글과 닫기·다시 열기 이력을 펼치고 접습니다">'+esc(tl('스레드 {n}',{n:th.length}))+'</button>':'')+'</div>'+
    (p.note&&oo?'<div class="arc-orig"><b>원래 요청</b>'+fmtText(p.note,p.mentions)+'</div>':'')+
    (to?'<div class="arc-thread"><div class="thread">'+th.map((m,i)=>msgHtml(m,p.id+':'+i)).join('')+(replying?'<div class="reply-slot"></div>':'')+'</div></div>':'')+'</div>';}
// A Trash row (docs/handbook/viewer.md §휴지통): who deleted it and when, how many days are left before it is purged, [되살리기], and -
// for the owner only - [영구 삭제] (sent after its undo toast goes away, like a reply).
const TRASH_DAYS=30;
function trashDaysLeft(at,now,exp){if(typeof exp==='number')return Math.max(0,Math.ceil((exp*1000-(now==null?Date.now():now))/86400000));
  const m=/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(String(at||'')); if(!m)return null;
  const t=new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5]).getTime(); return Math.max(0,Math.ceil(TRASH_DAYS-((now==null?Date.now():now)-t)/86400000));}
function isOwner(){return !!(typeof META!=='undefined'&&META&&META.me&&META.me.role==='owner');}
function droppedCard(p){
  const line=p.note?arcLine('d:'+p.id,p.note,'삭제한 핀의 메모 — 누르면 펼치고 접습니다',p.mentions):'<span class="arc-reply none">(메모 없음)</span>';
  const left=trashDaysLeft(p.dropped_at,null,p.expires_ts);
  return '<div class="arc-row dropped" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'" data-tip="'+esc(authorTip(p))+'">'+
    '<div class="arc-l1">'+ic('trash-2')+'<span class="n" data-tip="삭제한 핀 번호">#'+p.id+'</span>'+docChip(p)+arcLoc(p)+
    relSpan(p.dropped_at,'arc-t',tl('삭제한 사람 {name} · 삭제한 시각',{name:who(p.dropped_by)||tr('기록 전')}))+
    '<span class="arc-sep" aria-hidden="true">·</span><span class="arc-t trash-by">'+esc(tl('{name} 삭제',{name:who(p.dropped_by)||tr('기록 전')}))+'</span>'+
    (left!=null?'<span class="arc-sep" aria-hidden="true">·</span><span class="arc-t trash-left" data-tip="'+esc(tl('{n}일이 지나면 저절로 지워집니다',{n:TRASH_DAYS}))+'">'+esc(tl('{n}일 뒤 지워짐',{n:left}))+'</span>':'')+'<span class="sp"></span>'+
    // a viewer reads the Trash but is offered no state change (the server answers 403 anyway) - not rendered, not only hidden
    '<span class="arc-acts">'+(isViewer()?'':'<button class="btn-sm btn-secondary arc-b b-restore" data-act="restore" data-tip="'+esc(T.restore)+'">되살리기</button>')+
    (isOwner()?'<button class="btn-sm arc-b btn-destructive b-purge" data-act="purge" data-tip="'+esc(T.purge)+'">영구 삭제</button>':'')+'</span></div>'+
    '<div class="arc-l2">'+line+'</div></div>';}
let TRASH_ALL=false;   // the Trash shows every document while open for another document's pin - the list's own filter (SHOW_ALL) is untouched
function drawTrash(){const L=TRASH_ALL?DROPPED:listDropped(),box=$('#trash-list'); if(!box)return;
  $('#trash-note').textContent=tl('삭제한 핀은 {n}일 동안 여기 있다가 저절로 지워집니다. 되살리면 같은 번호로 돌아옵니다',{n:TRASH_DAYS});
  box.innerHTML=L.length?L.slice().reverse().filter(p=>!PURGING.has(p.id)).map(droppedCard).join(''):'<div class="dim">'+esc(tr('휴지통이 비어 있습니다'))+'</div>';}
function openTrash(flashId){const d=$('#trash');
  if(flashId!=null&&!listDropped().some(p=>p.id===flashId)&&DROPPED.some(p=>p.id===flashId))TRASH_ALL=true;   // another document's pin
  drawTrash(); if(!d.open){hideTip(); d.showModal(); toastHost();}
  if(flashId!=null)requestAnimationFrame(()=>{const el=document.querySelector('#trash .arc-row[data-id="'+flashId+'"]'); if(!el)return;
    el.scrollIntoView({block:'nearest'}); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');});}
$('#trash').addEventListener('close',()=>{TRASH_ALL=false;});
$('#trash').addEventListener('click',e=>{const d=$('#trash'); if(e.target!==d)return; const r=d.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});
// If the people list changes (a new person/name), the list is redrawn - the very first render can show a login instead of a name.
async function loadPeople(){try{const r=(await api('/api/people',{what:'사람 목록',silent:true})).data;
  if(Array.isArray(r.people)){const was=JSON.stringify(PEOPLE); PEOPLE=r.people; if(JSON.stringify(PEOPLE)!==was)drawPins();}}catch(e){}}
async function loadPins(){let d;
  try{d=(await api('/api/pins?all=1',{what:'핀 읽기'})).data;}catch(e){return;}
  loadPeople();
  let dropped=[];
  try{dropped=(await api('/api/pins/dropped',{what:'삭제한 핀',silent:true})).data.dropped||[];}catch(e){}
  // Multiple documents: the fetched list is for every document (diffToast also sees all of it too). PINS/DONE are only the current document's; if SHOW_ALL, only the rendered list shows everything.
  const prevOpen=OPEN_ALL,prevReview=REVIEW_ALL;
  const nextOpen=d.filter(p=>!p.done); REVIEW_ALL=d.filter(p=>pinState(p)==='review'); DONE_ALL=d.filter(p=>pinState(p)==='done'); DROPPED=dropped;
  diffToast(prevOpen,d,dropped); reviewToast(prevReview,d);
  OPEN_ALL=nextOpen; PINS=nextOpen.filter(p=>pdoc(p)===DOC||!DOC); DONE=DONE_ALL.filter(p=>pdoc(p)===DOC||!DOC);
  if(EDIT&&!OPEN_ALL.some(p=>p.id===EDIT.id)){toast(tl('편집 중이던 핀 #{id} 이 목록에서 빠졌습니다(다른 쪽에서 닫았거나 지움)',{id:EDIT.id}),'warn'); EDIT=null;}
  if(REPLY&&!d.some(p=>p.id===REPLY.id)){closeReply(false); toast('답글을 쓰던 핀이 목록에서 빠졌습니다(지워짐) — 쓰던 글은 남겨 둡니다','warn');}
  if(!SEC_SEEN.open){SEC_SEEN.open=new Set(OPEN_ALL.map(p=>p.id)); SEC_SEEN.review=new Set(REVIEW_ALL.map(p=>p.id)); SEC_SEEN.done=new Set(DONE_ALL.map(p=>p.id));}
  drawPins(); marks(); drawDocTabs();
  if(CUR){recomputeOverlap(); renderOverlapBanner();}   // if the list changes (someone else's save/completion), overlap is recomputed too
  docTitle(true);
}
// The list drawn in the sidebar: the current document by default, everything if 'all documents'. A pin being edited is kept even from another document (so the draft text doesn't disappear).
function listOpen(){return SHOW_ALL&&multiDoc()?OPEN_ALL:OPEN_ALL.filter(p=>pdoc(p)===DOC||!DOC||(EDIT&&EDIT.id===p.id));}
function listDone(){return SHOW_ALL&&multiDoc()?DONE_ALL:DONE;}
function listReview(){return SHOW_ALL&&multiDoc()?REVIEW_ALL:REVIEW_ALL.filter(p=>pdoc(p)===DOC||!DOC);}
// Awaiting-review count: counted across documents (the inbox of work for a person to confirm). The purple number next to [핀 N] (compact) / the tool bar chip (wide).
function updateReviewCount(){const n=REVIEW_ALL.length,pill=$('#side-rv'),chip=$('#rv-chip');
  pill.hidden=!n; pill.textContent=n; pill.setAttribute('aria-label',tl('검토 대기 {n}',{n}));
  const here=listReview().length; chip.hidden=!n||LAYOUT!=='wide'; chip.textContent=tl('검토 대기 {n}',{n})+(multiDoc()&&here!==n?' '+tl('(이 문서 {n})',{n:here}):'');}
function gotoReview(){if(!listReview().length&&REVIEW_ALL.length&&multiDoc())SHOW_ALL=true;
  if(!SEC.review){SEC.review=true; savePrefs({sec:SEC});} drawPins();
  setSide(true); requestAnimationFrame(()=>{const t=$('#sec-review'); if(t&&!t.hidden)t.scrollIntoView({block:'start',behavior:SMOOTH});});}
// The reviewer shown on an awaiting-review card: the author is suggested (anyone can confirm - a trust model). If I'm the author, '내 확인 차례'.
function isMe(a){const me=META&&META.me; return !!(a&&me&&me.login&&me.login!=='local'&&a.login===me.login);}
function reviewerLabel(p){if(!p.author||!(p.author.name||p.author.login))return tr('확인 필요'); return isMe(p.author)?tr('내 확인 차례'):tl('{name}님 확인 필요',{name:who(p.author)});}
function listDropped(){return SHOW_ALL&&multiDoc()?DROPPED:DROPPED.filter(p=>pdoc(p)===DOC||!DOC);}
// One section header (docs/handbook/viewer.md §목록 구획): chevron, name, count and - while collapsed - 'new N' (ids the section did not show
// when it was last expanded). The body it controls (aria-controls) is hidden while collapsed.
const SEC_NAME_ID={open:'list-h',review:'review-h',done:'done-h'};
// ids = the pins this section lists now; all = the section's pins across every document. While expanded, everything is marked seen
// (all, so switching documents never reads as arrivals); SEC_SEEN starts from the first load, so nothing is 'new' at boot.
function secHead(key,name,ids,all){const b=document.getElementById(key+'-toggle'); if(!b)return; const open=!!SEC[key],seen=SEC_SEEN[key];
  if(open&&seen)(all||ids).forEach(id=>seen.add(id));
  const nn=open?0:secNewCount(seen,ids);
  b.innerHTML=ic(open?'chevron-down':'chevron-right')+'<span class="sec-name" id="'+SEC_NAME_ID[key]+'">'+esc(name)+' <span class="badge badge-secondary sec-n">'+ids.length+'</span></span>'+
    (nn?'<span class="sec-new">'+esc(tl('새 {n}',{n:nn}))+'</span>':'');
  b.setAttribute('aria-expanded',String(open));
  const body=document.getElementById(b.getAttribute('aria-controls')); if(body)body.hidden=!open;}
function toggleSec(key,force){if(!(key in SEC_DEFAULT))return; SEC[key]=force===undefined?!SEC[key]:!!force; savePrefs({sec:SEC}); drawPins();}
function drawPins(){
  const LIST=listOpen(),LDONE=listDone(),LDROP=listDropped();
  // The '나를 부른 핀' filter: only the open/awaiting-review pins across every document that @-tagged me (a cross-document inbox).
  const MINE=OPEN_ALL.concat(REVIEW_ALL).filter(mentionsMe),mf=$('#mention-filter');
  if(MENTION_ONLY&&!MINE.length)MENTION_ONLY=false;
  mf.hidden=!MINE.length; mf.setAttribute('aria-pressed',String(MENTION_ONLY)); mf.innerHTML=ic('at-sign')+MINE.length; mf.setAttribute('aria-label',tl('나를 부른 핀 {n}',{n:MINE.length}));
  const SHOWN=MENTION_ONLY?OPEN_ALL.filter(mentionsMe):LIST;
  // If the cursor was in the reply input field, it's restored to that position after redrawing (so auto-sync redrawing the list never interrupts typing).
  const rta=REPLY&&REPLY.el.querySelector('textarea'),rfocus=rta&&document.activeElement===rta?[rta.selectionStart,rta.selectionEnd]:null;
  secHead('open',tr(MENTION_ONLY?'나를 부른 열린 핀':SHOW_ALL&&multiDoc()?'모든 문서의 열린 핀':'열린 핀'),SHOWN.map(p=>p.id),OPEN_ALL.map(p=>p.id));
  const ab=$('#all-docs'); ab.setAttribute('aria-pressed',String(SHOW_ALL)); ab.innerHTML=(SHOW_ALL?ic('check'):'')+esc(tr('모든 문서'));
  $('#side-n').textContent=PINS.length; applySide();
  // In compact, the done toggle and the Trash are also in [⋯]. On desktop the Trash is the link under the list.
  $('#m-done').textContent=tl(SEC.done?'닫힌 핀 {n} 숨기기':'닫힌 핀 {n} 보기',{n:LDONE.length});
  const nTrash=LDROP.filter(p=>!PURGING.has(p.id)).length;
  $('#m-trash').textContent=tl('휴지통 {n}',{n:nTrash}); $('#trash-link').textContent=tl('휴지통 {n}',{n:nTrash}); $('#trash-link').hidden=!nTrash;
  $('#empty').hidden=SHOWN.length>0||OPEN_ALL.length>0||REVIEW_ALL.length>0;
  // Empty list: the header's count already says it - a separate '아직 없습니다.' line is never added too (QA). Only a note that another document has pins is left.
  $('#pins').innerHTML=SHOWN.length?SHOWN.map(card).join(''):(multiDoc()&&!SHOW_ALL&&OPEN_ALL.length?'<div class="dim list-empty">'+esc(tl('이 문서에는 없습니다 · 다른 문서에 {n}건',{n:OPEN_ALL.length}))+'</div>':'');
  if(EDIT){const slot=$('#pins .edit-slot'); if(slot)slot.replaceWith(EDIT.el);}
  // Awaiting-review section: between open pins and done. Hidden when empty. The card looks the same as an open pin (thread/replies); only the actions are [확인]/[답글].
  const LREV=MENTION_ONLY?REVIEW_ALL.filter(mentionsMe):listReview();
  $('#sec-review').hidden=!LREV.length; secHead('review',tr('검토 대기'),LREV.map(p=>p.id),REVIEW_ALL.map(p=>p.id));
  $('#review-pins').innerHTML=LREV.map(card).join('');
  updateReviewCount();
  // Done section: hidden header and all if empty. The header stays stuck to the top while scrolling.
  $('#sec-done').hidden=!LDONE.length; secHead('done',tr('완료'),LDONE.map(p=>p.id),DONE_ALL.map(p=>p.id));
  if(SEC.done)$('#done-list').innerHTML=LDONE.length?LDONE.slice().reverse().map(doneCard).join(''):'<div class="dim">없습니다.</div>';
  if($('#trash').open)drawTrash();
  if(REPLY){const slot=document.querySelector('#list .reply-slot'); if(slot)slot.replaceWith(REPLY.el); renderReplyOutcome();   // the pin may have changed state meanwhile
    if(rfocus&&document.contains(rta)){rta.focus(); try{rta.setSelectionRange(rfocus[0],rfocus[1]);}catch(e){}}}
}
// Location estimation (.est, dashed) is judged by the server and carried as est in /api/pins (pin_est - comparing the
// manuscript fingerprint of the build the pin was placed on with the current build). Back when the viewer judged this by
// wall clock, it was wrong across the board with browser timezone, a note-only edited_at, and a pin placed on a stale
// PDF (confirmed by independent verification). The viewer just renders the value it's given.
function isEstimated(p){return p.est===true;}
function marks(){
  $$('.mark').forEach(m=>m.remove());
  // Awaiting-review pins are also drawn as purple marks - so the reviewer can see right there what was fixed (unrelated to an open pin's overlap/editing).
  PINS.concat(REVIEW_ALL.filter(p=>pdoc(p)===DOC)).forEach(p=>{const el=document.getElementById('p'+p.page); if(!el||!Array.isArray(p.frac))return;
    const est=isEstimated(p);
    const m=document.createElement('div'); m.className='mark'+(p.stale?' st':'')+(est?' est':'')+(p.done?' rv':''); m.dataset.pin=p.id;
    Object.assign(m.style,{left:p.frac[0]*100+'%',top:p.frac[1]*100+'%',width:p.frac[2]*100+'%',height:p.frac[3]*100+'%'});
    const n=String(p.note||'').replace(/\s+/g,' ').trim();
    const tip='#'+p.id+' · '+(n?(n.length>60?n.slice(0,60)+'…':n):tr('(메모 없음)'))+(est?' '+tr('(PDF가 새로 만들어져 위치는 추정입니다)'):'');
    m.innerHTML='<b data-act="mark-jump" data-id="'+p.id+'" data-tip="'+esc(tip)+'">'+p.id+'</b>'; el.appendChild(m);});
}
// Clicking a badge scrolls to and flashes the card (never calls pick). The mark box itself has pointer-events:none, so
// a drag over it still becomes a new selection - only the badge (<b>) needs to block mousedown.
$('#doc').addEventListener('mousedown',e=>{
  if(e.target.closest('.mark b')){e.stopPropagation();e.preventDefault();}
},true);
// Clicking a badge -> scroll to the card + .cur highlight (spec) + a 1.2-second flash. The highlight is never left on -
// it releases; when it was a static box-shadow, it stayed on the card until the next click.
// compact: clicking a badge expands the panel/sheet and that card, then scrolls via jumpToCard.
// Expands the section that holds pin id if it is collapsed (a mark click, a notification, [검토 대기 N]). Returns true if it changed.
function secOpenFor(id){const p=findAnyPin(id); if(!p)return false; const st=pinState(p),key=st==='review'?'review':st==='done'?'done':'open';
  if(SEC[key])return false; SEC[key]=true; savePrefs({sec:SEC}); return true;}
function revealCard(id){if(secOpenFor(id))drawPins(); if(LAYOUT==='wide')return; setSide(true);
  if(!OPEN_CARDS.has(id)&&(PINS.some(p=>p.id===id)||REVIEW_ALL.some(p=>p.id===id))){OPEN_CARDS.add(id); drawPins();}}
function jumpToCard(id){if(secOpenFor(id))drawPins();
  const el=document.querySelector('.pin[data-id="'+id+'"]'); if(!el)return;
  el.scrollIntoView({behavior:SMOOTH,block:'nearest'});
  $$('.pin.cur').forEach(x=>{if(x!==el)x.classList.remove('cur');});
  clearTimeout(el._curT);
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('cur','flash');
  el._curT=setTimeout(()=>el.classList.remove('cur','flash'),1200);
}
// A '#12' link in text: expands and scrolls to that pin's card/archive row, then flashes it. If it's on another document, '모든 문서' is turned on.
function gotoPinRef(id){const p=findAnyPin(id); if(!p){if(DROPPED.some(x=>x.id===id))openTrash(id); return;}
  const st=pinState(p);
  if(multiDoc()&&DOC&&pdoc(p)!==DOC)SHOW_ALL=true;
  if(st==='done')SEC.done=true; else{OPEN_CARDS.add(id); SEC[st==='review'?'review':'open']=true;} savePrefs({sec:SEC});
  if(LAYOUT!=='wide')setSide(true); drawPins();
  requestAnimationFrame(()=>{const el=document.querySelector('.pin[data-id="'+id+'"],.arc-row[data-id="'+id+'"]'); if(!el)return;
    el.scrollIntoView({behavior:SMOOTH,block:'nearest'}); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    clearTimeout(el._flT); el._flT=setTimeout(()=>el.classList.remove('flash'),1200);});}
function jumpPin(id){if(viaDoc(id,jumpPin))return; const p=PINS.find(x=>x.id===id)||REVIEW_ALL.find(x=>x.id===id&&pdoc(x)===DOC);
  if(!p){const q=REVIEW_ALL.find(x=>x.id===id); if(q&&docInfo(pdoc(q)))switchDoc(pdoc(q)).then(()=>{if(DOC===pdoc(q))jumpPin(id);}); return;}
  if(document.body.classList.contains('revision-open'))setViewMode('manuscript');
  if(LAYOUT==='narrow')setSide(false);   // collapsed first so the sheet doesn't cover the page, then measured
  const m=document.querySelector('.mark[data-pin="'+id+'"]');
  if(m){
    const L=$('#left'),lr=L.getBoundingClientRect(),mr=m.getBoundingClientRect();
    L.scrollTop+=(mr.top-(lr.top+lr.height*0.30));
    m.classList.remove('flash');void m.offsetWidth;m.classList.add('flash');
  } else {
    const el=document.getElementById('p'+p.page); if(el)el.scrollIntoView({behavior:SMOOTH});
  }
}
// Hovering a card highlights its mark, along with any overlapping counterpart marks.
function markIdsFor(p){return [p.id].concat((p.rel||[]).map(x=>x.id));}
$('#pins').addEventListener('mouseover',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.add('hi');});});
$('#pins').addEventListener('mouseout',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.remove('hi');});});
async function closePin(id){try{const {data}=await api('/api/pins/'+id+'/close',{method:'POST',what:'완료'});
  if(!data.ok){toast(tl('완료 실패 — 핀 #{id} 이 없습니다',{id}),'err');}
  else {markMine(id); toast(tl(data.state==='review'?'핀 #{id} 검토 대기로 보냄 — 이 화면에 신원이 없어(로컬) 에이전트가 닫은 것으로 칩니다':'핀 #{id} 완료',{id}),
    'ok',{label:'되돌리기',fn:()=>reopenPin(id)});}}catch(e){} await loadPins();}
// Awaiting review -> done. The person who confirmed (confirmed_by) is recorded.
async function confirmPin(id){try{const {data}=await api('/api/pins/'+id+'/confirm',{method:'POST',what:'확인',expect:[409]});
  if(data&&data.error==='open')toast(tl('핀 #{id} 은 이미 다시 열렸습니다',{id}),'warn');
  else if(!data.ok)toast(tl('확인 실패 — 핀 #{id} 이 없습니다',{id}),'err');
  else{markMine(id); toast(tl('핀 #{id} 확인 · 완료로 옮겼습니다',{id}),'ok');}}catch(e){} await loadPins();}
// Undo of [완료] (the toast's [되돌리기]) - the viewer has no [다시 열기] button any more; a reply reopens by the server rule.
async function reopenPin(id){try{await api('/api/pins/'+id+'/reopen',{method:'POST',what:'다시 열기'});
  markMine(id); toast(tl('핀 #{id} 완료를 되돌렸습니다',{id}),'ok');}catch(e){} await loadPins();}
// [삭제] takes the pin off the list at once (no confirmation) and says so next to the action with [되돌리기]; it waits in the Trash.
async function dropPin(id,undoSave){const was={o:OPEN_ALL,p:PINS};
  OPEN_ALL=OPEN_ALL.filter(p=>p.id!==id); PINS=PINS.filter(p=>p.id!==id); if(EDIT&&EDIT.id===id)EDIT=null; drawPins(); marks();
  try{await api('/api/pins/'+id+'/drop',{method:'POST',what:'삭제'});
    markMine(id); toast(tl(undoSave?'핀 #{id} 저장을 되돌렸습니다':'핀 #{id} 삭제됨 · 휴지통에 30일 보관',{id}),'ok',{label:'되돌리기',fn:()=>restorePin(id)});}
  catch(e){OPEN_ALL=was.o; PINS=was.p; drawPins(); marks();} await loadPins();}
// [영구 삭제] (owner): the row leaves the Trash at once; the request goes out when the undo toast does (deferred).
const PURGING=new Set();
function purgePin(id){PURGING.add(id); drawTrash(); drawPins();
  deferred(tl('핀 #{id} 영구 삭제',{id}),async()=>{try{await api('/api/pins/'+id+'/purge',{method:'POST',what:'영구 삭제',keepalive:true});}catch(e){}
      PURGING.delete(id); await loadPins();},
    ()=>{PURGING.delete(id); drawTrash(); drawPins();});}
async function restorePin(id){try{await api('/api/pins/'+id+'/restore',{method:'POST',what:'되살리기'});
  markMine(id); toast(tl('핀 #{id} 되살림',{id}),'ok');}catch(e){} await loadPins();}
async function unclaimPin(id){try{await api('/api/pins/'+id+'/unclaim',{method:'POST',what:'처리 중 풀기'});
  markMine(id); toast(tl('핀 #{id} 처리 중 표시를 풀었습니다',{id}),'ok');}catch(e){} await loadPins();}

// ------------------------------------------------ @-tag autocomplete (docs/handbook/viewer.md §@태그)
// Typing '@' in the note/edit/reply field shows known people (PEOPLE, excluding me). Picking one inserts '@name ' and
// remembers that login on the field (ta._mentions), carried as a hint (mentions) when sending - the server re-resolves
// it from the text (dropped if the name was deleted from the text). There is no external notification.
const MENTION={ta:null,start:0,items:[],sel:0};
function mentionQuery(ta){const pos=ta.selectionStart; if(pos==null||pos!==ta.selectionEnd)return null;
  const m=/(^|[^0-9A-Za-z가-힣._@-])@([^\s@]{0,30})$/.exec(ta.value.slice(0,pos)); return m?{start:pos-m[2].length-1,q:m[2]}:null;}
function mentionMatches(q,people,meLogin){q=String(q||'').toLowerCase();
  const rows=people.filter(p=>p.login!==meLogin).map(p=>{const n=String(p.name||'').toLowerCase(),l=p.login.toLowerCase();
    const at=Math.min(...[n.indexOf(q),l.indexOf(q)].filter(i=>i>=0).concat([99]));
    const word=n.split(/\s+/).some(w=>w.startsWith(q)); return {p,rank:!q?0:at===0?0:word?1:at<99?2:9};});
  return rows.filter(r=>r.rank<9).sort((a,b)=>a.rank-b.rank||String(a.p.name).localeCompare(String(b.p.name))).slice(0,6).map(r=>r.p);}
function mentionHints(ta){if(!ta||!ta._mentions)return []; const v=ta.value;
  return Array.from(ta._mentions).filter(l=>v.includes('@'+peopleName(l)));}
// An '@word' still being typed (the cursor sits at its end) is never flagged as '등록된 사람이 아님' yet - the warning
// used to appear while still picking (QA 2026-09-25). It's flagged once the cursor leaves it or the field. If the same word appears earlier too (an already-finished '@word'), it's still flagged as usual.
function mentionBadSettled(bad,text,q){if(!q)return bad; const w=q.q, before=String(text||'').slice(0,q.start);
  return bad.filter(x=>x!==w||before.includes('@'+w));}
function mentionClose(){MENTION.ta=null; $('#mention-pop').hidden=true;}
// The line below the input field: who will be notified on save (resolved @names) and any '@word' that won't resolve
// ('not a registered person'). Since text can't be colored inside a textarea, this is previewed here instead - so it's
// known before saving whether a tag will actually become a notification. The rule matches the server's resolve_mentions() (see the fmtText comment).
function mentionScan(text,hints){text=String(text||''); const toks=mentionToks(PEOPLE.map(p=>p.login)).map(x=>({t:x.t.toLowerCase(),lg:x.lg}));
  const hit=[],bad=[],low=text.toLowerCase(),hs=hints||new Set(); let first=null;
  for(let i=0;i<text.length;i++){if(text[i]!=='@'||(i>0&&/[0-9A-Za-z가-힣._-]/.test(text[i-1])))continue;
    const rest=low.slice(i+1); let got=null;
    for(const x of toks){const t=x.t.replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'");
      if(!rest.startsWith(t))continue; const nx=rest.charAt(t.length); if(/[a-z0-9]$/.test(t)&&/[a-z0-9_]/.test(nx))continue;
      const all=toks.filter(y=>y.t===x.t).map(y=>y.lg),pick=all.length===1?all:all.filter(l=>hs.has(l)); if(pick.length){got=pick;break;}}
    if(got){got.forEach(l=>{if(!hit.includes(l))hit.push(l);}); if(first===null&&!text.slice(0,i).trim())first=got[0];}
    else{const w=/^[^\s@]{1,30}/.exec(text.slice(i+1)); if(w&&!bad.includes(w[0]))bad.push(w[0]);}}
  return {hit,bad,first};}
// Assignee (docs/handbook/viewer.md §담당): who handles this pin. Default - if the note starts with a resolved @-tag, that
// person; otherwise a question pin's first @-tag; otherwise the agent. I can never be picked (just as the server
// excludes a tag mentioning me). With no @-tags, there's nothing to pick (the agent).
function defaultAssignee(text,kind,hints){const r=mentionScan(text,hints),me=meLogin(),hit=r.hit.filter(l=>l!==me);
  if(r.first&&r.first!==me)return r.first; if(kind==='question'&&hit.length)return hit[0]; return 'agent';}
function assignPeople(text,hints,keep){const me=meLogin(),out=mentionScan(text,hints).hit.filter(l=>l!==me);
  if(keep&&keep!=='agent'&&!out.includes(keep))out.push(keep); return out;}
function assignSeg(people,value,act){if(!people.length)return '';
  const opt=(v,label,tip)=>'<button type="button" role="radio" data-act="'+act+'" data-v="'+esc(v)+'" aria-checked="'+(v===value)+'"'+(v===value?' class="on"':'')+
    ' data-tip="'+esc(tip)+'">'+label+'</button>';
  return '<span class="as-lab">'+esc(tr('담당'))+'</span><div class="seg as-seg">'+opt('agent',esc(tr('에이전트')),tr('에이전트가 이 핀을 처리합니다 — @태그한 사람에게는 알림만 갑니다'))+
    people.map(l=>opt(l,'@'+esc(peopleName(l)),tl('{name}에게 맡깁니다 — 에이전트는 이 핀을 건너뜁니다',{name:peopleName(l)}))).join('')+'</div>';}
// The composer panel's assignee: before the user picks one (touched=false), the default is re-chosen every time the note changes. If the picked person disappears from the note, it falls back to the default.
const ASSIGN_NEW={v:'agent',touched:false};
function renderAssignNew(){const ta=$('#note'),box=$('#c-assign'); if(!ta||!box)return;
  const ppl=assignPeople(ta.value,ta._mentions);
  if(!ASSIGN_NEW.touched||(ASSIGN_NEW.v!=='agent'&&!ppl.includes(ASSIGN_NEW.v))){ASSIGN_NEW.v=defaultAssignee(ta.value,KIND_NEW,ta._mentions); ASSIGN_NEW.touched=false;}
  if(!ppl.length){ASSIGN_NEW.v='agent'; box.hidden=true; box.innerHTML=''; return;}
  box.innerHTML=assignSeg(ppl,ASSIGN_NEW.v,'assign-new'); box.hidden=false;}
function renderAssignEdit(){const E=EDIT; if(!E)return; const ta=E.el.querySelector('.e-note'),box=E.el.querySelector('.e-assign'); if(!ta||!box)return;
  const ppl=assignPeople(ta.value,ta._mentions,E.assignee);
  if(!ppl.length){box.hidden=true; box.innerHTML=''; return;}
  box.innerHTML=assignSeg(ppl,E.assignee,'assign-edit'); box.hidden=false;}
function mentionPreview(ta){if(!ta)return; const box=ta.nextElementSibling; if(!box||!box.classList.contains('m-preview'))return;
  const r=mentionScan(ta.value,new Set(mentionHints(ta))),me=meLogin();   // the same hints the save/send carries r.bad=mentionBadSettled(r.bad,ta.value,document.activeElement===ta?mentionQuery(ta):null);
  if(!r.hit.length&&!r.bad.length){box.hidden=true; box.innerHTML=''; return;}
  box.innerHTML=(r.hit.length?'<span class="m-lab">'+ic('at-sign')+'알림</span>'+r.hit.map(l=>'<span class="mention'+(l===me?' me':'')+'">'+esc(peopleName(l))+(l===me?' '+esc(tr('(나 — 알림 없음)')):'')+'</span>').join(''):'')+
    r.bad.map(w=>'<span class="mention-bad" data-tip="등록된 사람이 아님 — 이 이름으로는 알림이 가지 않습니다. 이 뷰어를 연 테일넷 사람만 부를 수 있습니다">@'+esc(w)+'</span>').join('')+
    (r.bad.length?'<span class="m-note">등록된 사람이 아님</span>':'');
  box.hidden=false;}
function mentionUpdate(ta){const q=mentionQuery(ta); if(!q){if(MENTION.ta===ta)mentionClose(); return;}
  const me=META&&META.me&&META.me.login; MENTION.ta=ta; MENTION.start=q.start; MENTION.items=mentionMatches(q.q,PEOPLE,me);
  MENTION.sel=Math.min(MENTION.sel,Math.max(0,MENTION.items.length-1));
  const pop=$('#mention-pop');
  pop.innerHTML=MENTION.items.length?MENTION.items.map((p,i)=>'<button type="button" role="option" aria-selected="'+(i===MENTION.sel)+'" data-act="mention-pick" data-i="'+i+'">'+
    avatar(p)+'<span>'+esc(p.name)+'</span><span class="ml">'+esc(p.login)+'</span></button>').join(''):
    '<div class="dim">'+esc((q.q?tl("'{q}' 와 맞는 사람이 없습니다",{q:q.q}):tr('부를 수 있는 사람이 없습니다'))+' — '+tr('이 뷰어를 연 테일넷 사람만 부를 수 있습니다'))+'</div>';
  pop.hidden=false; const r=ta.getBoundingClientRect(),h=pop.offsetHeight,w=pop.offsetWidth,vv=window.visualViewport;
  const g=mentionGuard(ta); pop.style.top=mentionTop(r,g?g.getBoundingClientRect():null,h,vv?vv.offsetTop:0,vv?vv.offsetTop+vv.height:innerHeight)+'px';
  pop.style.left=Math.max(4,Math.min(r.left,innerWidth-w-4))+'px';}
// The action row of that input field that the @-list must never cover: reply/reopen [취소][보내기], edit [저장], composer panel [취소][핀 저장].
function mentionGuard(ta){const box=ta.closest('.reply-box,.edit'); return box?box.querySelector('.r-acts,.e-acts'):ta.id==='note'?$('#c-actions'):null;}
// The @-list's top (docs/handbook/viewer.md §@태그). A spot that never covers the action row (guard) is chosen in this order -
// (1) right below the input field (if it fits above the action row) (2) above the input field (3) below the action row
// (4) if nothing fits, below the input field (the old spot). A reply field has [취소][보내기] right below it, so (1)
// never fits and (2) is used instead (the list used to cover both buttons, QA 2026-09-25).
function mentionTop(r,g,h,top,bot){const gap=4,lim=g&&g.top>=r.bottom?Math.min(bot,g.top):bot;
  if(r.bottom+gap+h<=lim)return r.bottom+gap;
  if(r.top-gap-h>=top+gap)return r.top-gap-h;
  if(g&&g.bottom+gap+h<=bot)return g.bottom+gap;
  return Math.max(top+gap,Math.min(r.bottom+gap,bot-h-gap));}
function mentionApply(i){const ta=MENTION.ta,p=MENTION.items[i]; if(!ta||!p)return; const pos=ta.selectionStart,ins='@'+p.name+' ';
  ta.value=ta.value.slice(0,MENTION.start)+ins+ta.value.slice(pos); const c=MENTION.start+ins.length; ta.setSelectionRange(c,c);
  (ta._mentions=ta._mentions||new Set()).add(p.login); mentionClose(); ta.focus(); autoGrow(ta); mentionPreview(ta);
  if(ta.id==='note')renderAssignNew(); else if(ta.classList.contains('e-note'))renderAssignEdit(); else if(ta.classList.contains('r-text'))renderReplyOutcome();}
const isMentionField=t=>!!t&&t.tagName==='TEXTAREA'&&(t.id==='note'||t.classList.contains('e-note')||t.classList.contains('r-text'));
document.addEventListener('input',e=>{if(isMentionField(e.target)){mentionUpdate(e.target); mentionPreview(e.target);
  if(e.target.id==='note'){renderAssignNew(); qHint($('#c-qhint'),e.target.value,KIND_NEW);}
  else if(e.target.classList.contains('e-note')){renderAssignEdit(); if(EDIT)qHint(EDIT.el.querySelector('.e-qhint'),e.target.value,EDIT.kind_req);}
  else if(e.target.classList.contains('r-text'))renderReplyOutcome();}});
window.addEventListener('keydown',e=>{if(!MENTION.ta||e.target!==MENTION.ta||$('#mention-pop').hidden||e.isComposing)return;
  const n=MENTION.items.length;
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){if(!n)return; e.preventDefault(); e.stopImmediatePropagation();
    MENTION.sel=(MENTION.sel+(e.key==='ArrowDown'?1:n-1))%n; mentionUpdate(MENTION.ta);}
  else if((e.key==='Enter'&&!e.metaKey&&!e.ctrlKey)||e.key==='Tab'){if(!n)return; e.preventDefault(); e.stopImmediatePropagation(); mentionApply(MENTION.sel);}
  else if(e.key==='Escape'){e.preventDefault(); e.stopImmediatePropagation(); mentionClose();}},true);
// When the cursor leaves the '@word' being typed (arrow key/click/leaving the field), the preview redraws and warns at that point.
['keyup','click','focusout'].forEach(t=>document.addEventListener(t,e=>{if(isMentionField(e.target))setTimeout(()=>mentionPreview(e.target),0);}));
document.addEventListener('focusout',e=>{if(e.target===MENTION.ta)setTimeout(()=>{if(document.activeElement!==MENTION.ta)mentionClose();},150);});
$('#mention-pop').addEventListener('pointerdown',e=>e.preventDefault());

// ------------------------------------------------ Reply input field (docs/handbook/viewer.md §스레드와 검토)
// Only one input field is ever open. Its DOM is held on REPLY.el, and when drawPins() redraws cards, it's re-inserted
// into .reply-slot - so the 5-second auto-sync redrawing the list never loses the draft text or cursor (focus is
// restored too). There is one [답글] for every state: on a closed pin (awaiting review or done) the server decides whether the
// reply reopens it (reply_reopens), and the line under the box (.r-outcome) previews that decision with the same rule
// (replyReopens) - [상태 유지] (REPLY.keep) overrides it with reopen:false. Sending is deferred behind an undo toast.
function isHuman(){const me=typeof META!=='undefined'&&META&&META.me; return !!(me&&me.login&&me.login!=='local'&&!String(me.login).startsWith('agent:')&&me.role!=='agent');}
// Mirrors the server's reply_reopens(): an open pin never changes; an explicit override (true/false) wins; otherwise a person's reply
// on a closed pin reopens it unless it tags a person or the pin is a question. mentioned = the post's resolved @-tags without me.
function replyReopens(p,human,mentioned,override){if(pinState(p)==='open')return false;
  if(override!==undefined&&override!==null)return !!override;
  if(p.kind_req==='question'||!human)return false; return !(mentioned&&mentioned.length);}
// The outcome line: {text, toggle}, or null for an open pin (a reply never changes it). toggle names the one rare override the box
// offers: 'keep' ([상태 유지], reopen:false) where the rule would reopen, 'reopen' ([다시 열기], reopen:true) where it keeps a closed pin
// as it is. flip = that toggle is pressed.
function replyPreview(p,human,mentioned,flip){if(!p||pinState(p)==='open')return null; const m=mentioned||[];
  const reopens=replyReopens(p,human,m),toggle=reopens?'keep':'reopen',names=m.map(peopleName).join(', ');
  if(flip&&!reopens)return {text:m.length?tl('보내면 이 핀이 다시 열려 에이전트에게 가고, {names}에게 알림이 갑니다',{names}):tr('보내면 이 핀이 다시 열려 에이전트에게 갑니다'),toggle};
  if(flip)return {text:tr('보내도 상태는 그대로입니다'),toggle};
  if(reopens)return {text:tr('보내면 이 핀이 다시 열려 에이전트에게 갑니다'),toggle};
  if(p.kind_req==='question')return {text:tr('답으로 남고 상태는 그대로입니다'),toggle};
  if(!human)return {text:tr('이 화면은 에이전트로 보내므로 상태는 그대로입니다'),toggle};
  return {text:tl('보내면 {names}에게 알림이 가고 상태는 그대로입니다',{names}),toggle};}
// The empty box's placeholder says the same outcome as the line under it would for a reply without @-tags.
function replyPlaceholder(p,human,flip){const closed=!!p&&pinState(p)!=='open',def=closed&&replyReopens(p,human,[]);
  return tr(closed&&(flip?!def:def)?'무엇이 틀렸는지 적으면 다시 열려 에이전트에게 갑니다 (⌘/Ctrl+Enter 보내기)':'답글 (⌘/Ctrl+Enter 보내기)');}
// After the deferred send: a note only when the server's decision differs from the preview (the pin changed state while the
// undo toast was up, e.g. someone else's reply reopened it first). Worded from the response, not from the guess.
function replyServerNote(id,predicted,data){if(!data||!data.ok||!!data.reopened===!!predicted)return null;
  if(data.reopened)return tl('#{id} 은 그사이 닫혀서 이 답글이 다시 열었습니다',{id});
  return data.state==='open'?tl('#{id} 은 그사이 이미 열려 있어 답글로만 남았습니다',{id}):tl('#{id} 은 다시 열리지 않고 답글로만 남았습니다',{id});}
// The post's @-tags that count as asking a person: without me and without agent-role accounts (as the server's rule).
// Resolved with exactly the hints the request will carry (mentionHints) - the server resolves the same text with the same hints,
// so an autocompleted '@Robin Lee' later edited down to an ambiguous '@Robin' previews what the server will do (PR #11 review).
function replyMentioned(ta){const me=meLogin(); return mentionScan(ta.value,new Set(mentionHints(ta))).hit.filter(l=>l!==me&&(PEOPLE.find(x=>x.login===l)||{}).role!=='agent');}
function replyEl(p){const el=document.createElement('div'); el.className='reply-box';
  el.innerHTML='<textarea class="r-text" rows="2" maxlength="1000" aria-label="답글" placeholder="'+esc(replyPlaceholder(p,isHuman(),false))+'"></textarea><div class="m-preview" aria-live="polite" hidden></div>'+
    '<div class="r-outcome" aria-live="polite" hidden><span class="r-out-t"></span><button type="button" class="btn-sm r-keep" role="switch" data-act="reply-flip" aria-checked="false"></button></div>'+
    '<div class="r-err errline" role="alert" hidden></div>'+
    '<div class="r-acts"><button class="btn-sm" data-act="reply-cancel" data-tip="입력 칸을 닫습니다 (Esc). 쓰던 글은 남겨 둡니다">취소</button>'+
    '<button class="btn-sm btn-default" data-act="reply-send" data-tip="답글을 보냅니다. 알림의 [되돌리기]를 누르면 보내기 전에 취소됩니다">보내기</button></div>';
  return el;}
function renderReplyOutcome(){const R=REPLY; if(!R)return; const box=R.el.querySelector('.r-outcome'),ta=R.el.querySelector('textarea'); if(!box||!ta)return;
  const p=findAnyPin(R.id),ment=replyMentioned(ta);
  let pv=p&&replyPreview(p,isHuman(),ment,!!R.flip);
  ta.placeholder=replyPlaceholder(p,isHuman(),!!R.flip);
  if(!pv){box.hidden=true; R.flip=false; R.toggle=null; return;}
  if(R.toggle&&R.toggle!==pv.toggle&&R.flip){R.flip=false; pv=replyPreview(p,isHuman(),ment,false);}   // the rule changed direction (a tag added/removed): the override resets
  R.toggle=pv.toggle; box.hidden=false; box.querySelector('.r-out-t').textContent=pv.text;
  box.classList.toggle('reopen',replyReopens(p,isHuman(),ment,R.flip?pv.toggle==='reopen':undefined));
  const k=box.querySelector('[data-act=reply-flip]'),keep=pv.toggle==='keep';
  k.textContent=tr(keep?'상태 유지':'다시 열기'); k.dataset.tip=tr(keep?'보내도 핀을 다시 열지 않고 답글만 남깁니다(드물게 씁니다)':'보내면서 핀을 다시 열어 에이전트에게 보냅니다(드물게 씁니다)');
  k.setAttribute('aria-checked',String(!!R.flip));}
function openReply(id){
  if(REPLY&&REPLY.id===id){const t=REPLY.el.querySelector('textarea'); if(t)t.focus(); return;}
  if(REPLY)closeReply(false);
  const p=findAnyPin(id);
  REPLY={id,flip:false,toggle:null,el:replyEl(p)}; OPEN_CARDS.add(id); if(LAYOUT!=='wide')setSide(true); drawPins();
  const ta=REPLY.el.querySelector('textarea'); ta.value=REPLY_DRAFT.get('reply:'+id)||''; autoGrow(ta); mentionPreview(ta); renderReplyOutcome(); ta.focus();
  REPLY.el.scrollIntoView({block:'nearest'});}
function closeReply(redraw){if(!REPLY)return; const ta=REPLY.el.querySelector('textarea');
  if(ta&&ta.value.trim())REPLY_DRAFT.set('reply:'+REPLY.id,ta.value); else REPLY_DRAFT.delete('reply:'+REPLY.id);
  REPLY=null; if(redraw!==false)drawPins();}
function sendReply(){const R=REPLY; if(!R||viewerBlocked())return; const ta=R.el.querySelector('textarea'),text=ta.value.trim();
  if(!text){toast('답글이 비어 있습니다','warn'); ta.focus(); return;}
  const id=R.id,p=findAnyPin(id),body={text},mh=mentionHints(ta),hints=ta._mentions,flip=!!R.flip; if(mh.length)body.mentions=mh;
  if(flip&&p&&pinState(p)!=='open'&&R.toggle)body.reopen=R.toggle==='reopen';
  const reopens=!!p&&replyReopens(p,isHuman(),replyMentioned(ta),body.reopen);
  // Back into the box - after [되돌리기], or with an inline error when sending failed (offline), so the draft is visibly kept.
  const back=err=>{REPLY_DRAFT.set('reply:'+id,text); openReply(id);
    if(REPLY&&REPLY.id===id){const t=REPLY.el.querySelector('textarea'); if(hints)t._mentions=hints; REPLY.flip=flip; mentionPreview(t); renderReplyOutcome();
      const e=REPLY.el.querySelector('.r-err'); if(e){e.textContent=err||''; e.hidden=!err;}}};
  REPLY_DRAFT.delete('reply:'+id); REPLY=null; drawPins();          // the box closes at once; the post waits for the undo toast
  const d=deferred(tl(reopens?'핀 #{id} 다시 열어 에이전트에게 보냄':'#{id} 에 답글을 남겼습니다',{id}),
    async()=>{markMine(id);
      try{const {data}=await api('/api/pins/'+id+'/reply',{method:'POST',body,what:'답글',keepalive:true});
        if(!data.ok)toast(tl('핀 #{id} 이 없습니다',{id}),'err');
        else{const note=replyServerNote(id,reopens,data); if(note)toast(note,'warn');}}
      catch(e){back(tr('보내지 못했습니다 — 글은 그대로 두었습니다. 연결을 확인하고 다시 보내세요'));}
      await loadPins();},
    ()=>back(null));
  // Keyboard users (Ctrl+Enter) land on [되돌리기], so Enter undoes; the toast still commits when it goes away.
  const b=d.toast&&d.toast.querySelector('.t-acts button'); if(b)b.focus({preventScroll:true});}

// ------------------------------------------------ Edit
function openEdit(id){if(viaDoc(id,openEdit))return; const p=PINS.find(x=>x.id===id); if(!p)return;
  if(document.body.classList.contains('revision-open'))jumpPin(id);
  if(EDIT&&EDIT.id===id)return;
  const el=document.createElement('div'); el.className='edit';
  el.innerHTML='<div class="e-kind seg kind-seg" role="radiogroup" aria-label="핀 종류"><button data-act="e-kind" data-kind="fix" role="radio" data-tip="고쳐 달라는 요청">수정 요청</button>'+
    '<button data-act="e-kind" data-kind="question" role="radio" data-tip="'+esc(T.question)+'">질문</button></div>'+
    '<textarea class="e-note" rows="3" aria-label="메모 고치기" data-tip="메모를 고칩니다. ⌘ Enter / Ctrl+Enter 저장, Esc 취소"></textarea><div class="m-preview" aria-live="polite" hidden></div>'+
    '<div class="e-qhint q-hint" role="status" hidden>'+ic('circle-question-mark')+'<span>질문처럼 보입니다 —</span><button data-act="e-kind" data-kind="question" data-tip="이 핀을 질문으로 바꿉니다">질문으로 보내기</button></div>'+
    '<div class="e-assign assign-row" role="radiogroup" aria-label="담당" hidden></div>'+
    '<div class="e-levels seg" role="group" aria-label="범위 단계"></div>'+
    '<div class="c-tools"><div class="step" role="group" aria-label="한 줄씩 넓히고 좁히기">'+
    '<span class="sl" aria-hidden="true">위</span><button data-act="nudge" data-dir="up-grow" aria-label="위로 한 줄 넓히기" data-tip="위로 한 줄 넓힙니다">'+ic('plus')+'</button>'+
    '<button data-act="nudge" data-dir="up-shrink" aria-label="위에서 한 줄 좁히기" data-tip="위에서 한 줄 좁힙니다">'+ic('minus')+'</button>'+
    '<span class="sl" aria-hidden="true">아래</span><button data-act="nudge" data-dir="down-grow" aria-label="아래로 한 줄 넓히기" data-tip="아래로 한 줄 넓힙니다">'+ic('plus')+'</button>'+
    '<button data-act="nudge" data-dir="down-shrink" aria-label="아래에서 한 줄 좁히기" data-tip="아래에서 한 줄 좁힙니다">'+ic('minus')+'</button></div>'+
    '<span class="e-range loc" tabindex="0" data-tip="저장하면 핀이 가리킬 원문 줄. 누르면 복사"></span></div>'+
    '<pre class="e-snip wrap">원문 읽는 중…</pre>'+
    '<div class="e-acts"><button class="btn-sm b-repick" data-act="repick" data-tip="'+esc(T.repick)+'">위치 다시 잡기</button>'+
    '<button class="btn-sm b-ecancel" data-act="ecancel" data-tip="'+esc(T.ecancel)+'">취소</button>'+
    '<button class="btn-sm btn-default b-esave" data-act="esave" data-tip="'+esc(T.esave)+'">저장</button></div>';
  const ta=el.querySelector('.e-note'); ta.value=p.note||''; ta._mentions=new Set(p.mentions||[]); autoGrow(ta); mentionPreview(ta);
  EDIT={id,el,base_rev:p.rev||0,file:p.file,name:p.name||String(p.file||p.pdf||'').split('/').pop(),lo:p.lo,hi:p.hi,scope:p.scope||null,
    kind:p.kind,env:null,levels:[],n_lines:null,snippet:'',orig:{lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',kind_req:isQuestion(p)?'question':'fix',assignee:assigneeOf(p)},
    assignee:assigneeOf(p),
    doc:pdoc(p),region:isRegion(p),page:p.page,quote:p.quote||'',kind_req:isQuestion(p)?'question':'fix'};
  if(EDIT.region)el.classList.add('region');
  drawPins(); renderEdit(); ta.focus(); editSnip(true);
}
// Does the edit field have unsaved changes (whether it's safe to close the edit when switching documents)?
function editDirty(){const E=EDIT; if(!E)return false; const ta=E.el.querySelector('.e-note');
  return (ta&&ta.value!==E.orig.note)||E.lo!==E.orig.lo||E.hi!==E.orig.hi||E.kind_req!==E.orig.kind_req||E.assignee!==E.orig.assignee;}
function autoGrow(ta){ta.style.height='auto'; const lh=20; ta.style.height=Math.min(12*lh,Math.max(3*lh,ta.scrollHeight+2))+'px';}
document.addEventListener('input',e=>{if(e.target.classList&&(e.target.classList.contains('e-note')||e.target.classList.contains('r-text')||e.target.id==='note'))autoGrow(e.target);});
async function editSnip(withLevels){const E=EDIT; if(!E)return;
  if(E.region){E.snippet=E.quote?tl('영역 글자: {text}',{text:E.quote}):tr('(영역 글자 없음)'); renderEdit(); return;}   // view-only: there is no source line
  try{const {status,data}=await api(dq('/api/snippet?file='+encodeURIComponent(E.file)+'&lo='+E.lo+'&hi='+E.hi+(withLevels?'&levels=1':''),E.doc),
      {what:'원문 읽기',expect:[400]});
    if(EDIT!==E)return;
    if(status===400){E.snippet=tr('원문을 읽지 못했습니다')+' — '+(data&&data.error||'')+'\n'+tr('위치 다시 잡기로 고치세요.'); renderEdit(); return;}
    E.snippet=data.snippet; E.n_lines=data.n_lines;
    if(withLevels&&data.levels){E.levels=data.levels; if(!E.scope||!lvOf(E,E.scope)){const cur=E.levels.find(l=>l.lo===E.lo&&l.hi===E.hi);
      if(cur&&!E.scope)E.scope=null;}}
    renderEdit();}catch(e){}}
function renderEdit(){const E=EDIT; if(!E)return; const el=E.el;
  el.querySelectorAll('.e-kind button').forEach(b=>{const on=b.dataset.kind===(E.kind_req||'fix'); b.classList.toggle('on',on); b.setAttribute('aria-checked',String(on));});
  el.querySelector('.e-range').textContent=E.region?tl('쪽 {page} · 영역',{page:E.page}):rng(E.lo,E.hi);
  el.querySelector('.e-range').dataset.copy=E.region?E.name+' 쪽 '+E.page:E.name+' L'+E.lo+'-L'+E.hi;
  el.querySelector('.e-levels').innerHTML=levelBtns(E,true); segReveal(el.querySelector('.e-levels'));
  const pre=el.querySelector('.e-snip'); pre.className='e-snip '+(WRAP?'wrap':'nowrap'); pre.textContent=snipText(E.snippet,false); renderAssignEdit();
  qHint(el.querySelector('.e-qhint'),el.querySelector('.e-note').value,E.kind_req);}
function cancelEdit(){EDIT=null; drawPins();}
async function saveEdit(){const E=EDIT; if(!E||ESAVING||viewerBlocked())return;
  const note=E.el.querySelector('.e-note').value, body={base_rev:E.base_rev};
  if(note!==E.orig.note)body.note=note;
  if(E.kind_req&&E.kind_req!==E.orig.kind_req)body.kind_req=E.kind_req;
  if(E.assignee&&E.assignee!==E.orig.assignee)body.assignee=E.assignee;
  if(body.note!==undefined){const mh=mentionHints(E.el.querySelector('.e-note')); if(mh.length)body.mentions=mh;}
  if(E.lo!==E.orig.lo||E.hi!==E.orig.hi||(E.scope||null)!==(E.orig.scope||null)){body.lo=E.lo;body.hi=E.hi;
    if(E.scope){body.scope=E.scope; body.kind=kindFor(E.scope,E.env);}}
  if(Object.keys(body).length===1){cancelEdit();return;}
  ESAVING=true;
  try{const {status,data}=await api('/api/pins/'+E.id+'/edit',{method:'POST',body,what:'핀 수정',expect:[409]});
    if(status===409){
      if(data&&data.error==='done'){toast(tl('핀 #{id} 은 이미 닫혀 범위를 바꿀 수 없습니다 — 메모만 고칠 수 있습니다',{id:E.id}),'warn'); EDIT=null; await loadPins(); return;}
      const p=data.pin; toast('다른 쪽(에이전트나 자동 줄 맞춤)이 이 핀을 먼저 바꿨습니다 — 최신 위치를 불러왔습니다','warn');
      E.base_rev=p.rev; E.lo=p.lo; E.hi=p.hi; E.scope=p.scope||null; E.file=p.file;
      E.orig={lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',kind_req:E.orig.kind_req,assignee:assigneeOf(p)}; editSnip(true); await loadPins(); return;}
    EDIT=null; toast(tl('핀 #{id} 수정됨',{id:E.id}),'ok'); await loadPins();
  }catch(e){} finally{ESAVING=false;}
}

// ------------------------------------------------ Re-place location
function banner(html){const b=$('#banner'); b.innerHTML=html; b.hidden=false;}
function bannerRepick(err){banner('<span>'+esc(tl('핀 #{id} 의 새 위치를 PDF에서 드래그하세요 · Esc 취소',{id:REPICK.id}))+'</span>'+
  (err?'<span class="errline" style="margin:0">'+esc(err)+'</span>':'')+'<span class="sp"></span>'+
  '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');}
function bannerCompare(){const c=REPICK.cand,lv=lvOf(c,c.default_level)||c,rg=isRegion(c);
  banner('<span class="loc" data-tip="지금 위치 → 새 위치" tabindex="0">'+esc(rg?tl('지금 쪽 {from} · 새 쪽 {to} 영역',{from:REPICK.from.page,to:c.page}):tl('지금 {from} · 새 {to}',{from:'L'+REPICK.from.lo+'-L'+REPICK.from.hi,to:'L'+lv.lo+'-L'+lv.hi}))+'</span>'+
    '<span class="dim">('+esc(rg?(c.quote?String(c.quote).slice(0,40):tr('글자 없는 영역')):(lv.label?levelLabel(lv.label):scopeLabel(c)))+')</span><span class="sp"></span>'+
    '<button class="btn-sm btn-default" data-act="rp-apply" data-tip="번호와 메모는 그대로 두고 위치만 바꿉니다">이 위치로 바꾸기</button>'+
    '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');}
// On touch, selection mode is turned on during a re-place, and narrow collapses the sheet to reveal the page (the banner stays visible even on the collapsed sheet).
async function startRepick(){if(!EDIT)return;
  if(EDIT.doc&&EDIT.doc!==DOC){const E=EDIT; await switchDoc(E.doc); if(DOC!==E.doc||EDIT!==E)return;}   // selection happens on that pin's document
  REPICK={id:EDIT.id,from:{lo:EDIT.lo,hi:EDIT.hi,page:EDIT.page},box:null,cand:null}; bannerRepick();
  if(MQ_COARSE.matches)setSelMode(true); if(LAYOUT==='narrow')setSide(false);}
function cancelRepick(){const was=!!REPICK; if(REPICK&&REPICK.box)REPICK.box.remove(); REPICK=null; $('#banner').hidden=true;
  if(was){if(!CUR)setSelMode(false); if(EDIT&&LAYOUT!=='wide')setSide(true);}}
async function applyRepick(){const R=REPICK; if(!R||!R.cand)return; const c=R.cand,lv=lvOf(c,c.default_level)||c;
  let loc={file:c.file,page:c.page,lo:lv.lo,hi:lv.hi,raw_lo:c.raw_lo,raw_hi:c.raw_hi,via:c.via,score:c.score,frac:c.frac,pdf_build:c.pdf_build||undefined,
    scope:lv.level||null,kind:lv.level?kindFor(lv.level,lv.env):c.kind};
  if(!loc.scope)delete loc.scope;
  if(isRegion(c))loc={page:c.page,frac:c.frac,quote:c.quote,pdf_build:c.pdf_build||undefined};   // view-only: only the region is re-placed
  const base=EDIT&&EDIT.id===R.id?EDIT.base_rev:0;
  try{const {status,data}=await api('/api/pins/'+R.id+'/edit',{method:'POST',body:{loc,base_rev:base},what:'위치 바꾸기',expect:[409]});
    if(status===409){toast(data&&data.error==='done'?'닫힌 핀은 위치를 바꿀 수 없습니다':'다른 쪽이 이 핀을 먼저 바꿨습니다 — 최신 값을 불러왔습니다','warn');
      if(EDIT&&data.pin){EDIT.base_rev=data.pin.rev;} cancelRepick(); await loadPins(); return;}
    const p=data.pin; cancelRepick();
    if(EDIT&&EDIT.id===p.id){Object.assign(EDIT,{base_rev:p.rev,lo:p.lo,hi:p.hi,file:p.file,name:p.name,scope:p.scope||null,page:p.page,quote:p.quote||''});
      EDIT.orig.lo=p.lo;EDIT.orig.hi=p.hi;EDIT.orig.scope=p.scope||null; editSnip(true);}
    toast(tl('핀 #{id} 위치를 {where} 로 바꿨습니다',{id:p.id,where:isRegion(p)?tl('쪽 {page} 영역',{page:p.page}):'L'+p.lo+'-L'+p.hi}),'ok'); await loadPins();
  }catch(e){}}

// ------------------------------------------------ PDF rebuild
function topAnchor(off){const L=$('#left'),top=L.getBoundingClientRect().top+(off||0);
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(); if(r.bottom>top+1)return {page:+pg.dataset.page,frac:Math.max(0,(top-r.top)/r.height)};}
  return null;}
function restoreAnchor(a){if(!a)return; const pg=document.getElementById('p'+a.page); if(!pg)return; const L=$('#left');
  L.scrollTop+=pg.getBoundingClientRect().top-L.getBoundingClientRect().top+a.frac*pg.getBoundingClientRect().height;}
async function refreshDoc(){const a=topAnchor(),k=DOC;
  const m=(await api(dq('/api/meta'),{what:'화면 정보 읽기'})).data; META_BY.set(k,m);
  if(k!==DOC)return;                    // switched to another document while waiting - only the cache is refreshed
  const same=META&&m.pages.length===META.pages.length; META=m; drawMeta();
  // The canvas was drawn from the old PDF - it's torn down to show the new PNG first, then redrawn once the new build's PDF is opened.
  if(same){vecReleaseAll(); $$('.pg').forEach((pg,i)=>{const p=META.pages[i]; pg.style.aspectRatio=p.pt_w+' / '+p.pt_h; pg.querySelector('img').src=pageSrc(p);});}
  else buildDoc();
  restoreAnchor(a); vecOpen(); if(document.body.classList.contains('revision-open'))loadRevisions(); await loadPins();}
// On ok_errors|fail, the panel itself is opened right away, not just a toast - once the toast disappeared after 6
// seconds there used to be no way to see it again. Even after closing it, #build-err-chip remains to reopen it (as long as LAST_BUILD_ERR exists).
function showBuildErr(r){LAST_BUILD_ERR=r; if(DOC)BUILD_ERR_BY.set(DOC,r); const b=$('#build-err');
  const title=tr(r.state==='fail'?'빌드 실패 — 화면은 이전 PDF입니다':'PDF를 재빌드했지만 LaTeX 오류가 있습니다');
  b.innerHTML='<div class="row"><b>'+esc(title)+'</b><span class="sp"></span>'+
    '<button class="btn-sm" data-act="err-close" data-tip="이 알림을 닫습니다(다시 보기는 위 배지로)">닫기</button></div>'+
    (r.errors||[]).map(e=>'<div class="dim">'+(e.line?'L'+e.line+' · ':'')+esc(e.msg)+'</div>').join('')+
    '<pre class="nowrap" style="max-height:30vh">'+esc(String(r.log_tail||r.log||'').split('\n').slice(-20).join('\n'))+'</pre>';
  b.hidden=false; $('#build-err-chip').hidden=true;}
function hideBuildErr(){$('#build-err').hidden=true; $('#build-err-chip').hidden=!LAST_BUILD_ERR;}
// P0b-01: rebuild is async - the POST returns immediately, and the #build-chip poller (startBuildPolling) shows
// progress, then does the in-place swap and notification once it finishes. A build started by someone else is caught by the same poller.
async function rebuild(){
  try{const {status}=await api(dq('/api/rebuild?async=1'),{method:'POST',what:'PDF 재빌드',expect:[409]});
    if(status===409){toast('이미 다른 곳에서 PDF를 재빌드하는 중입니다 — 끝난 뒤 다시 누르세요','warn');return;}
    $('#build-err').hidden=true;
    // If a request already went out before this POST, its completion is awaited before asking again - that request
    // carries a stale state (ok) and would never turn on 1-second polling. Completion is distinguished by build_seq, so this tab has nothing separate to remember.
    if(BUILD_INFLIGHT){try{await BUILD_INFLIGHT;}catch(e){}}
    await pollBuild();
  }catch(e){}}

// ------------------------------------------------ Help
let HELP_BACK=null;
function openHelp(){const d=$('#help'); if(d.open)return; HELP_BACK=document.activeElement; hideTip(); d.showModal(); toastHost();}
$('#help').addEventListener('close',()=>{if(HELP_BACK&&HELP_BACK.focus)HELP_BACK.focus(); HELP_BACK=null;});

// ------------------------------------------------ Event delegation (no inline handlers)
document.addEventListener('click',e=>{
  const cp=e.target.closest('[data-copy]'); if(cp){copyText(cp.dataset.copy);return;}
  const a=e.target.closest('[data-act]'); if(!a)return;
  const host=a.closest('[data-id]'),id=host?+host.dataset.id:null,inEdit=!!a.closest('.edit');
  const fromMore=!!a.closest('#more');
  if(fromMore&&(a.dataset.close||a.dataset.act==='help'))$('#more').close();
  switch(a.dataset.act){
    case 'side':setSide(!SIDE_OPEN,true);break;
    case 'selmode':setSelMode(!SELMODE);if(SELMODE&&LAYOUT==='narrow'&&!CUR&&!EDIT)setSide(false);break;
    case 'more':openMore();break; case 'more-close':$('#more').close();break;
    case 'size-preset':sizePreset(+a.dataset.i);break;
    case 'm-jump':$('#more').close();goPage($('#m-jump').value);break;
    case 'coach-close':$('#coach').hidden=true;break;
    case 'card-toggle':if(id==null)break; if(OPEN_CARDS.has(id))OPEN_CARDS.delete(id); else OPEN_CARDS.add(id); drawPins();break;
    case 'rebuild':rebuild();break; case 'reload':loadPins();break;
    case 'zoom-in':zoom(1);break; case 'zoom-out':zoom(-1);break; case 'fit':fitW();break;
    case 'theme':cycleTheme();break; case 'lang':switchLang();break; case 'notify-toggle':notifyToggle();break; case 'help':openHelp();break; case 'help-close':$('#help').close();break;
    case 'save':if(!viewerBlocked())savePin();break; case 'cancel':cancelSelection(true);break;
    case 'overlap-append':{const text=$('#note').value.trim();
      if(!text){toast('메모를 먼저 써야 덧붙일 수 있습니다','warn');break;}
      appendToPin(+a.dataset.oid,text);break;}
    case 'overlap-separate':OVERLAP_DISMISSED=a.dataset.key||null;renderOverlapBanner();break;
    case 'wrap':WRAP=!WRAP;savePrefs({wrap:WRAP});renderComposer();renderEdit();break;
    case 'copy-cur':if(CUR)copyText(CUR.name+' L'+CUR.lo+'-L'+CUR.hi);break;
    case 'expand':SNIP_OPEN=!SNIP_OPEN;renderComposer();break;
    case 'level':{const o=inEdit?EDIT:CUR; if(!o)break; useLevel(o,a.dataset.level); if(!inEdit)recomputeOverlap(); inEdit?renderEdit():renderComposer(); break;}
    case 'nudge':{const o=inEdit?EDIT:CUR; if(!o||!nudge(o,a.dataset.dir))break; if(!inEdit)recomputeOverlap(); const r=inEdit?renderEdit:renderComposer; r(); refetchSnip(o,r); break;}
    case 'view':jumpPin(id);break; case 'edit':openEdit(id);break;
    case 'doc':{const inMenu=!!a.closest('#docs-menu'); switchDoc(a.dataset.doc); if(inMenu)$('#docs-menu').close(); break;}
    // ^ inMenu is determined before calling switchDoc() - for a cached document, switchDoc finishes synchronously
    //   through drawDocTabs, and inside that it redraws the open #docs-menu (drawDocsMenu), detaching a from the DOM.
    //   Calling a.closest() after switchDoc would return null, leaving the menu open and blocking the next tab
    //   interaction (a touch regression).
    case 'doc-menu':openDocsMenu();break; case 'docs-menu-close':$('#docs-menu').close();break;
    case 'view-mode':setViewMode(a.dataset.mode);break;
    case 'rev-back':{const b=REV_BACK; REV_BACK=null; setViewMode('manuscript'); if(b&&b!==DOC&&docInfo(b))switchDoc(b); break;}
    case 'outline':toggleOutline();break;
    case 'outline-page':if(LAYOUT==='mid'&&OUTLINE_MID_OPEN)toggleOutline();OUTLINE_SELECTED=Number(a.dataset.index);OUTLINE_ACTIVE_PAGE=Number(a.dataset.page);OUTLINE_PINNED={index:OUTLINE_SELECTED,page:OUTLINE_ACTIVE_PAGE};renderOutline();updateSectionStrip();setViewMode('manuscript');goPage(a.dataset.page);break;
    case 'revision':showRevision(a.dataset.commit);break;
    case 'revision-format':setRevisionFormat(a.dataset.format);break;
    case 'all-docs':SHOW_ALL=!SHOW_ALL;drawPins();break;
    case 'mention-filter':MENTION_ONLY=!MENTION_ONLY;drawPins();break;
    case 'mention-pick':mentionApply(+a.dataset.i);break;
    case 'pin-ref':gotoPinRef(+a.dataset.ref);break;
    case 'assign-new':ASSIGN_NEW.v=a.dataset.v||'agent'; ASSIGN_NEW.touched=true; renderAssignNew(); break;
    case 'assign-edit':if(EDIT){EDIT.assignee=a.dataset.v||'agent'; renderAssignEdit();} break;
    case 'msg-more':{const k=a.dataset.key; if(!k)break; if(MSG_OPEN.has(k))MSG_OPEN.delete(k); else MSG_OPEN.add(k); drawPins(); break;}
    case 'diff-wrap':setDiffWrap(!DIFF_WRAP);break;
    case 'revision-other':toggleRevisionOther();break;
    case 'revision-whole':setRevisionWhole(!REV_SCOPE.whole);break;
    case 'mark-jump':revealCard(id);jumpToCard(id);break;
    case 'close':closePin(id);break; case 'drop':dropPin(id,false);break;
    case 'restore':restorePin(id);break; case 'purge':if(id!=null)purgePin(id);break; case 'unclaim':unclaimPin(id);break;
    case 'kind':{const fromHint=!!a.closest('#c-qhint'); setKind(a.dataset.kind);
      // [질문으로 보내기] hides itself (qHint), which would drop focus to <body> and make Ctrl+Enter do nothing - back to the memo.
      if(fromHint){const n=$('#note'); n.focus({preventScroll:true}); n.setSelectionRange(n.value.length,n.value.length);}
      break;}
    case 'e-kind':if(EDIT){EDIT.kind_req=a.dataset.kind==='question'?'question':'fix'; renderEdit();}break;
    case 'reply-open':if(id!=null)openReply(id);break;
    case 'reply-flip':if(REPLY){REPLY.flip=!REPLY.flip; renderReplyOutcome();}break;
    case 'confirm':if(id!=null)confirmPin(id);break;
    case 'change':if(id!=null)showChange(id);break;
    case 'goto-review':gotoReview();break;
    case 'reply-cancel':closeReply();break; case 'reply-send':sendReply();break;
    case 'thread-more':if(id==null)break; if(THREAD_OPEN.has(id))THREAD_OPEN.delete(id); else THREAD_OPEN.add(id); drawPins();break;
    case 'arc-toggle':{const k=a.dataset.key; if(!k)break; if(ARC_OPEN.has(k))ARC_OPEN.delete(k); else ARC_OPEN.add(k); drawPins(); break;}
    case 'esave':saveEdit();break; case 'ecancel':cancelEdit();break;
    case 'repick':startRepick();break; case 'rp-cancel':cancelRepick();break; case 'rp-apply':applyRepick();break;
    case 'sec-toggle':toggleSec(a.dataset.sec);break;
    case 'done-toggle':toggleSec('done');if(fromMore)revealList('#done-toggle',SEC.done);break;
    case 'trash-open':openTrash();break; case 'trash-close':$('#trash').close();break;
    case 'err-close':hideBuildErr();break;
    case 'build-err-reopen':if(LAST_BUILD_ERR)showBuildErr(LAST_BUILD_ERR);break;
  }
});
$('#doc-select').addEventListener('change',e=>switchDoc(e.target.value));
$('#revision-list').addEventListener('change',e=>{if(e.target.id==='revision-select')showRevision(e.target.value);});
$('#revision-file').addEventListener('change',renderRevisionFile);
document.addEventListener('keydown',e=>{
  if(e.isComposing||e.keyCode===229)return;
  const t=e.target,inField=t&&(t.tagName==='TEXTAREA'||t.tagName==='INPUT'||t.tagName==='SELECT'||t.isContentEditable);
  // Ctrl(Cmd) + = / - / 0 zooms/fits just the PDF page instead of the browser zoom. Left to the browser inside an input field.
  if((e.ctrlKey||e.metaKey)&&!e.altKey&&!inField){const z=zoomKey(e);
    if(z){e.preventDefault(); if(z==='fit')fitW(); else zoom(z==='in'?1:-1); return;}}
  // Document switching (multiple documents): Ctrl+PgUp/PgDn is previous/next, Alt+1...9 is that index (e.code - Option+digit on Mac produces a different character).
  // The selector uses default keyboard handling. Global shortcuts are never used inside an input field.
  if(multiDoc()&&!inField){
    if(e.ctrlKey&&!e.altKey&&!e.metaKey&&(e.key==='PageUp'||e.key==='PageDown')){e.preventDefault(); cycleDoc(e.key==='PageDown'?1:-1); return;}
    if(e.altKey&&!e.ctrlKey&&!e.metaKey&&/^Digit[1-9]$/.test(e.code||'')){const d=DOCS[+e.code.slice(5)-1]; if(d){e.preventDefault(); switchDoc(d.key);} return;}
  }
  if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){
    if(t&&(t.id==='note'||(t.closest&&t.closest('#composer')&&!$('#composer').hidden&&!inField))){e.preventDefault(); if(!viewerBlocked())savePin();}
    else if(t&&t.classList&&t.classList.contains('e-note')){e.preventDefault();saveEdit();}
    else if(t&&t.classList&&t.classList.contains('r-text')){e.preventDefault();sendReply();}
    return;}
  if(e.key==='Enter'&&t&&t.dataset&&t.dataset.copy!==undefined&&!inField){copyText(t.dataset.copy);return;}
  // A span with role=button (a card's #number) is also activated by Enter/Space - sent through the same data-act path as a click.
  if((e.key==='Enter'||e.key===' ')&&t&&t.getAttribute&&/^(button|link)$/.test(t.getAttribute('role')||'')&&t.dataset&&t.dataset.act&&!inField){e.preventDefault();t.click();return;}
  if(e.key==='Escape'){
    if($('#help').open||$('#more').open||$('#docs-menu').open||$('#trash').open)return;
    if(!TIP.hidden){hideTip(); if(!inField)return;}
    if(LAYOUT==='mid'&&OUTLINE_MID_OPEN){e.preventDefault();toggleOutline();return;}
    if(REPICK){cancelRepick();return;}
    if(REPLY){closeReply();return;}
    if(EDIT){cancelEdit();return;}
    if(CUR||!$('#composer').hidden){cancelSelection(true);return;}
    return;}
  if(e.key==='?'&&!inField&&!e.metaKey&&!e.ctrlKey&&!e.altKey){e.preventDefault();openHelp();}
});
boot();
</script></body></html>"""
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
            raise HTTPError(400, "본문이 올바른 JSON 이 아닙니다.")
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
                pin, msg = reply_pin(pid, text, actor, hints, reopen=reopen, human=human)
                return self._json({"ok": pin is not None, "pin": pin, "msg": msg, "state": pin_state(pin) if pin else None,
                                   "reopened": bool(msg and msg.get("ev") == "reopen")})
            if act == "confirm":
                pin = confirm_pin(pid, actor)
                return self._json({"ok": pin is not None, "pin": pin, "state": pin_state(pin) if pin else None})
            if act == "drop":
                return self._json({"ok": drop_pin(pid, actor)})
            if act == "restore":
                return self._json({"ok": True, "pin": restore_pin(pid, actor)})
            if act == "purge":                    # owner only (check_role)
                return self._json({"ok": True, "purged": purge_pin(pid, actor)})
            if act == "edit":
                return self._json({"ok": True, "pin": edit_pin(pid, d, actor)})
            if act == "claim":
                ttl, eta = clean_claim_body(d)
                pin = claim_pin(pid, actor, ttl, eta)
                out = {"ok": pin is not None, "pin": pin, "ttl_min_applied": ttl}
                if eta is not None:
                    out["eta_min_applied"] = eta          # the clamped value, if sent above the ceiling (240)
                return self._json(out)
            if act == "unclaim":
                pin = unclaim_pin(pid, actor)
                return self._json({"ok": pin is not None, "pin": pin})
            reply = ref = review = reason = changes = None
            if act == "close":
                reply, ref = clean_close_body(d)
                changes = clean_close_changes(d.get("changes"), C.src)
                review = clean_review_flag(d)
                if review is None and self.principal.role == "agent":
                    review = True                 # a person with the agent role closes into review like any agent
            else:                                 # reopen - optional body {"reason"}: the reopen reason (recorded in the thread)
                reason = clean_thread_text(d.get("reason"), "reason", required=False)
            pin = set_done(pid, act == "close", actor, reply, ref, review=review, reason=reason,
                           hints=clean_mention_hints(d.get("mentions")), changes=changes)
            return self._json({"ok": pin is not None, "pin": pin, "state": pin_state(pin) if pin else None})
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
            raise ValueError("--doc %s: %s 가 --manuscript(%s) 밖입니다: %s" % (key, what, ms, p))
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
            raise ValueError("--doc %s: 메인 .tex 가 빌드 루트 밖입니다: %s" % (key, main))
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
