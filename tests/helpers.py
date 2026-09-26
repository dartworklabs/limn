"""Shared fixtures of the server-level tests: the one loaded copy of server.py (ps), the Base fixture that points it at a
temporary manuscript and state folder, the socketpair request helpers, and the node harness for the viewer's scripts.

Every test module that drives server.py imports from here, so the process holds a single server copy (loading it twice
would give two sets of module globals: two C, two DOCS, two locks).
"""
import dataclasses
import errno
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from limn import config, gitsync, revisions
from limn.access import LOCAL_ACTOR
from limn.store import find_pin
from limn.web import answers, parse
from limn.web.errors import InputRejected

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PKG = ROOT / "src" / "limn"
SKILL_MD = ROOT / "skill" / "SKILL.md"
SKILL_KO = ROOT / "skill" / "SKILL.ko.md"
DOCS_DIR = ROOT / "docs" / "handbook"
# server.py loaded from its file, the way an instance runs it; every server-level test shares this one copy.
spec = importlib.util.spec_from_file_location("limn_server", PKG / "server.py")
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)


def extract_js_fn(name: str) -> str:
    """Pull one 'function NAME(...){ ... }' definition out of ps.HTML, balancing braces as-is.

    This is only safe for functions whose string literals contain no braces (i.e. this
    file's pure-logic functions — no DOM/CSS text inside them). Running the actual server
    source pulled this way through node lets the regression test verify the real source,
    not a copy the test happened to paste as a string.

    Also matches 'async function NAME(' — matching only 'function NAME(' would drop the
    leading 'async ', and node would then reject a function containing await with
    'await is only valid in async functions'."""
    src = ps.HTML
    key = "function %s(" % name
    i = src.index(key)
    if i >= 6 and src[i - 6:i] == "async ":
        i -= 6
    j = src.index("{", i)
    depth = 0
    k = j
    while True:
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return src[i:k + 1]


def js_icons() -> str:
    """The viewer's Lucide icon table (ICONS) and ic() — included together when running icon-drawing functions like card()/archiveRow() under node."""
    m = re.search(r"const ICONS=\{.*?\};", ps.HTML)
    return m.group(0) + "\n" + extract_js_fn("ic")


def js_thread() -> str:
    """The functions that render a thread (called by card()/doneCard()). Callers must set up who·avatar·esc·arcTime·ic·THREAD_OPEN·REPLY."""
    ev = re.search(r"^const EV_LABEL=.*;$", ps.HTML, re.M).group(0)
    st = re.search(r"^const ST_NAME=.*;$", ps.HTML, re.M).group(0)
    mo = re.search(r"^const MSG_OPEN=.*;$", ps.HTML, re.M).group(0)
    return "\n".join([ev, st, mo, "let PEOPLE=[];", extract_js_fn("hasRef")] + [extract_js_fn(n) for n in (
        "relTime", "relSpan", "msgBody", "isAgent", "isQuestion", "assigneeOf", "assignChip", "stDot", "reopenedTurn", "threadOf", "allMentions", "replyCount", "msgText", "msgHtml", "threadHtml", "pinState", "isMe", "reviewerLabel",
        "peopleName", "mentionToks", "reEsc", "meLogin", "pinRefExists", "pinRefGone", "fmtText", "mentionsMe", "addressedTag", "fyiTag")])


def js_i18n(lang: str = "ko") -> str:
    """The viewer's message functions tr()/tl()/trMsg()/errText() with the language fixed - pulled functions call
    them for every UI string and API error, so a node harness needs them. Korean (the source) unless lang='en'."""
    return "\n".join(["var LANG=%s,I18N_EN=%s;" % (json.dumps(lang), json.dumps(ps.UI_EN, ensure_ascii=False)),
                      extract_js_fn("tr"), extract_js_fn("tl"), extract_js_fn("trMsg"), extract_js_fn("errText")])


def run_node(js: str, tz: str = None):
    """Run js under node and return stdout. Returns None if node is missing (handled on the test side).

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
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=15, env=env, check=False)
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
    first): the body's doc wins over it, the body is parsed against that document (limn.web.parse.parse_add), and the
    service saves it. Returns the new open pin, or the InputRejected of the first refused field. mod is the server copy
    to use (default ps)."""
    mod = mod or ps
    D = doc or mod.DOCS[0]
    want = d.get("doc")
    if isinstance(want, str) and want != D.key:
        D = mod.request_doc(want)
    request = parse.parse_add(d, mod.assignee_people(d), mod.document_facts(D))
    return request if isinstance(request, InputRejected) else mod.add_pin(D, request, actor)


def edit_pin(pid: int, d: dict, actor: dict, mod=None):
    """What POST /api/pins/{pid}/edit does below its HTTP answer: parse the body, place its loc against the pin's own
    document (edit_scope), then edit. Returns the edit's outcome, or the InputRejected of the first refused field."""
    mod = mod or ps
    body = parse.parse_edit(d, mod.assignee_people(d))
    if isinstance(body, InputRejected):
        return body
    region, pdoc = mod.edit_scope(pid)
    place = parse.parse_edit_place(body, region, mod.document_facts(pdoc))
    if isinstance(place, InputRejected):
        return place
    return mod.edit_pin(pid, dataclasses.replace(body.request, place=place), actor, region)


def pick(d: dict, mod=None, doc=None):
    """What POST /api/pick does below its HTTP answer for document doc (default the first): the selection parsed
    (limn.web.parse.parse_pick), then resolved. A gone build gives the 200 body the handler sends; a refused field
    raises the HTTPError the handler would answer with."""
    mod = mod or ps
    D = doc or mod.DOCS[0]
    selection = parse.parse_pick(d, mod.document_facts(D))
    if isinstance(selection, parse.PickBuildGone):
        return answers.pick_build_gone()
    return mod.pick(D, answers.accepted(selection))


def revision_spec(commit: str, pin: int | None = None, mod=None, doc=None):
    """What a comparison request of document doc (default the first) compares (limn.revisions.revision_spec with the
    server copy's context), or its refusal value."""
    mod = mod or ps
    return revisions.revision_spec(doc or mod.DOCS[0], commit, pin, mod.revision_context())


def record_of(outcome) -> dict:
    """The pin as the API returns it, from a close/reopen outcome (a state type, or AlreadyClosed carrying one)."""
    pin = getattr(outcome, "pin", outcome)
    return ps.public(pin.record)


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


class Base(unittest.TestCase):
    """server.py pointed at a fresh temporary manuscript (main.tex = TEX) and state folder: one document, no pins, an
    idle build, default run settings. Tests drive it through ps's functions or the handler (talk)."""

    def setUp(self):
        """Reset the server copy's run settings, build state, remote-main watch and document list for this test."""
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / "ms"
        self.src.mkdir()
        self.main = self.src / "main.tex"
        self.main.write_text(TEX, encoding="utf-8")
        C = ps.C
        C.src, C.main = self.src, self.main
        C.state = root / "state"
        C.state.mkdir()
        C.build = C.state / "build"
        C.port, C.dpi, C.timeout = 18999, 150, 60
        C.envs = tuple(ps.DEFAULT_ENVS.split(","))
        C.allow = frozenset()
        C.origin_check = True
        C.git_pull = False
        ps.SYNC_WATCH = gitsync.SyncWatch()        # a fresh remote-main watch status ("checking")
        C.pdfjs_dir = None
        C.label, C.accent, C.repo = "원고", config.ACCENT_PALETTE[0], None
        ps.BUILD_STATE.update(state="idle", phase=None, started_at=None, start_ts=None, seq=0,
                              finished_at=None, last=None, errors=[], log_tail="", head=None, pull=None)
        ps.set_docs(None)                          # start as a single document (no --doc) — clears the list left over from multi-doc tests
        ps.init_seq()

    def tearDown(self):
        """Remove the temporary manuscript and state folder."""
        self.tmp.cleanup()

    def add(self, lo=4, hi=5, note="n", actor=None):
        """Add a pin on main.tex lines lo-hi (page 1) as actor (default the local agent); returns its id."""
        return add_pin({"file": str(self.main), "lo": lo, "hi": hi, "page": 1, "note": note},
                          actor or dict(LOCAL_ACTOR)).record["id"]

    def pin(self, pid):
        """The stored record of pin pid after a synced read, or None."""
        return find_pin(ps.snapshot_pins(), pid)

    def talk(self, raw: bytes, shut=True) -> bytes:
        """Send raw over one connection and collect response bytes until the server closes it."""
        a, b = socket.socketpair()
        def serve():
            try:
                ps.Handler(b, ("127.0.0.1", 0), None)
            finally:
                b.close()                         # this is socketserver's shutdown_request duty
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


# the smallest PDF that pdftoppm/pdftotext can read (one page, one line of text). poppler rebuilds the xref itself.
MINI_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
            b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
            b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 150 Td (Reviewer one) Tj ET\nendstream endobj\n"
            b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def jreq(method, path, obj=None, headers=None):
    """req() with obj sent as a JSON body (Content-Type application/json); no body when obj is None."""
    body = json.dumps(obj).encode() if obj is not None else b""
    h = {"Content-Type": "application/json"} if obj is not None else {}
    h.update(headers or {})
    return req(method, path, body, h)
