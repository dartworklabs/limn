"""Shared fixtures of the handler-level access tests: the tailnet identities, the access settings reset, the CLI
state helpers (tokens, members), a socketpair request from a chosen TCP peer, and the test bases built on them -
AccessBase, ScopedRepo (a git repository with pin-scoped commits) and MovedManuscriptBase (a checkout renamed between
two server runs).

They lived in test_access.py, test_qa_021.py, test_v03.py and test_v032.py and were imported from there; a test module
is not a fixture library (importing one runs its module code and couples the files), so they are here. None of the
classes holds a test, so importing one never collects a test twice.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from limn import access, config
from limn.access import LOCAL_ACTOR
from limn.cli import cli_audit
from limn.config import Cfg
from limn.store import dump_jsonl

from helpers import Base, add_pin, ps, req, shut_wr, split_resp

# Tailnet identities as the request headers `tailscale serve` adds. Every server-level module uses these three.
ALICE = {"Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Alice Kim"}
BOB = {"Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob Park"}
CAROL = {"Tailscale-User-Login": "carol@example.com", "Tailscale-User-Name": "Carol Lee"}


def actor(h):
    """The {login, name} actor a tailnet identity's headers stand for (what the server stores as a pin's author)."""
    return {"login": h["Tailscale-User-Login"], "name": h["Tailscale-User-Name"]}


# The same identities as stored actors, for tests that call the server copy's functions directly.
ALICE_ACTOR = actor(ALICE)
BOB_ACTOR = actor(BOB)
# The body POST /api/clear requires.
CLEAR_BODY = {"confirm": "clear all pins"}
# Their logins, as events and people.json name people.
A_LOGIN, B_LOGIN, C_LOGIN = (h["Tailscale-User-Login"] for h in (ALICE, BOB, CAROL))
# A fourth person (the agent-role member where a test gives roles) and a tailnet host name as `tailscale serve` sends it.
DAVE = {"Tailscale-User-Login": "dave@example.com", "Tailscale-User-Name": "Dave Choi"}
TS_HOST = "box.tail1234.ts.net"


ACCESS_DEFAULTS = dict(
    auth="tailscale",
    agent_loopback=True,
    tailnet_agent=False,
    bind="127.0.0.1",
    public_hosts=(),
    trusted_proxies=Cfg.trusted_proxies,
    proxy_user_header="X-Forwarded-User",
    proxy_name_header="X-Forwarded-Preferred-Username",
    proxy_email_header=None,
    members_only=False,
    local_user=None,
    insecure=False,
    agent_token_file=None,
)


def reset_access(mod=ps):
    """Access settings back to the v0.1-equivalent defaults (the Cfg object is shared by every test module)."""
    for k, v in ACCESS_DEFAULTS.items():
        setattr(mod.C, k, v)
    mod.C.allow = frozenset()
    mod.LOOPBACK_WARNING = access.WarnOnce(access.LOOPBACK_AGENT_DEPRECATION)  # a fresh process: warns again
    mod.TOKENS_CACHE = access.FileCache()
    mod.ROLES_CACHE = access.FileCache()


def token_create(state, name=None):
    """`limn token create` on state as the CLI runs it: limn.access with limn.cli.cli_audit -> (entry, plaintext)."""
    return access.token_create(state, name, cli_audit(state))


def token_revoke(state, ref):
    """`limn token revoke` on state as the CLI runs it -> the removed entry, or None."""
    return access.token_revoke(state, ref, cli_audit(state))


def member_add(state, login, role=access.DEFAULT_ROLE, name=None):
    """`limn member add` on state as the CLI runs it, with limn.cli.cli_audit -> the new entry."""
    return access.member_add(state, login, role, name, cli_audit(state))


def member_remove(state, login):
    """`limn member remove` on state as the CLI runs it -> the removed entry, or None."""
    return access.member_remove(state, login, cli_audit(state))


def member_set_role(state, login, role):
    """`limn member role` on state as the CLI runs it -> the updated entry, or None."""
    return access.member_set_role(state, login, role, cli_audit(state))


def load_people_file(state, mod=ps):
    """people.json as `limn member list` reads it (strict: ValueError for an unreadable file)."""
    return access.load_people_file(state)


def talk_to(mod, raw: bytes, peer: str = "127.0.0.1") -> bytes:
    """One request over a socketpair to mod.Handler, from the given TCP peer address."""
    a, b = socket.socketpair()

    def serve():
        try:
            mod.Handler(b, (peer, 0), None)
        finally:
            b.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    a.sendall(raw)
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


class AccessBase(Base):
    """Base with the access settings reset to their defaults and the handler driven over a socketpair from a chosen
    TCP peer (call), so a test sees what a tailnet person, a proxy or the loopback agent is answered."""

    def setUp(self):
        """Base's fresh manuscript and state, access settings at their defaults, no people seen yet."""
        super().setUp()
        reset_access()
        ps._PEOPLE_SEEN.clear()

    def tearDown(self):
        """Put the access settings back for the next test module, then remove the temporary folders."""
        reset_access()
        super().tearDown()

    def call(self, method, path, body=None, headers=None, peer="127.0.0.1", token=None):
        """One request through the handler: body as JSON, headers as given, token as a Bearer header, from peer.
        Returns (status, parsed JSON or text body); the response headers are kept in self.last_headers."""
        h = dict(headers or {})
        raw = b""
        if body is not None:
            raw = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if token is not None:
            h["Authorization"] = "Bearer %s" % token
        code, hdrs, out = split_resp(talk_to(ps, req(method, path, raw, h), peer))
        try:
            data = json.loads(out)
        except ValueError:
            data = out.decode("utf-8", "replace")
        self.last_headers = hdrs
        return code, data

    def pin_id(self, headers=None, token=None, lo=4, hi=5, peer="127.0.0.1"):
        """Add a pin on main.tex lines lo-hi over HTTP as the given identity; fails the test unless it is a 200."""
        code, d = self.call(
            "POST",
            "/api/pin",
            {"file": str(self.main), "lo": lo, "hi": hi, "page": 1, "note": "n"},
            headers,
            peer,
            token,
        )
        self.assertEqual(code, 200, d)
        return d["id"]

    def people_file(self):
        """The rows of people.json, or [] when the file does not exist."""
        return json.loads(ps.C.people_file.read_text(encoding="utf-8"))["people"] if ps.C.people_file.exists() else []

    def set_people(self, rows):
        """Write people.json with these rows, as `limn member` would store them."""
        ps.C.people_file.write_text(
            json.dumps({"version": 1, "people": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )


def configure(mod, src: Path, main: Path, state: Path) -> None:
    """The same run configuration Base uses, applied to any server module (v0.1 or current)."""
    C = mod.C
    C.src, C.main, C.state, C.build = src, main, state, state / "build"
    C.port, C.dpi, C.timeout = 18999, 150, 60
    C.envs = tuple(mod.DEFAULT_ENVS.split(","))
    C.allow = frozenset()
    C.origin_check, C.git_pull, C.pdfjs_dir = True, False, None
    C.label, C.accent, C.repo = "원고", config.ACCENT_PALETTE[0], None
    mod.BUILD_STATE.update(
        state="idle",
        phase=None,
        started_at=None,
        start_ts=None,
        seq=0,
        finished_at=None,
        last=None,
        errors=[],
        log_tail="",
        head=None,
        pull=None,
    )
    mod.set_docs(None)
    mod.init_seq()
    if hasattr(mod, "TOKENS_CACHE"):
        reset_access(mod)


def get(mod, path, headers=None):
    """GET path from mod.Handler over a socketpair -> (status, body text)."""
    code, _, body = split_resp(talk_to(mod, req("GET", path, b"", headers)))
    return code, body.decode("utf-8")


TIME_LINE = re.compile(r"^갱신: \d{4}-\d\d-\d\d \d\d:\d\d  ·", re.M)


def mask(md: str) -> str:
    """pins.md with its header timestamp replaced by <갱신>, so two renderings compare byte for byte."""
    return TIME_LINE.sub("갱신: <갱신>  ·", md)


# ---------------------------------------------------------------- a git repository with pin-scoped commits (v0.3)

# The manuscript ScopedRepo commits first (three paragraphs, a pin each), and the version its fix commit writes.
REPO_OLD = """\\documentclass{article}
\\begin{document}
\\section{Intro}
Alpha paragraph talks about apples.

Filler one.
Filler two.
Filler three.
Filler four.

Beta paragraph talks about bananas.

Filler five.
Filler six.
Filler seven.
Filler eight.

Gamma paragraph talks about cherries.
\\end{document}
"""
# One commit touching three pins: alpha grows by a line (shifting everything below by +1), beta is rewritten, gamma is deleted.
REPO_NEW = (
    REPO_OLD.replace(
        "Alpha paragraph talks about apples.\n",
        "Alpha paragraph talks about apples and pears.\nA second alpha sentence.\n",
    )
    .replace("Beta paragraph talks about bananas.", "Beta paragraph talks about blueberries.")
    .replace("Gamma paragraph talks about cherries.\n", "")
)


class ScopedRepo(AccessBase):
    """A git repo whose second commit fixes three pins at once (alpha: recorded `changes`; beta and gamma: inferred),
    and a third commit that belongs entirely to a fourth pin."""

    def setUp(self):
        """Build the repository: first commit, three pins, the fix commit closing them, a fourth pin and its commit."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.main.write_text(REPO_OLD, encoding="utf-8")
        self.git("init", "--quiet")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.commit("first")
        self.p1 = self.add(lo=4, hi=4, note="alpha")
        self.p2 = self.add(lo=11, hi=11, note="beta")
        self.p3 = self.add(lo=18, hi=18, note="gamma")
        self.write(REPO_NEW)
        self.fix = self.commit("fix three pins")
        self.call(
            "POST",
            "/api/pins/%d/close" % self.p1,
            {"ref": self.fix[:8], "changes": [{"file": "main.tex", "lo": 4, "hi": 5}]},
        )
        self.call("POST", "/api/pins/%d/close" % self.p2, {"ref": self.fix[:8]})
        self.call("POST", "/api/pins/%d/close" % self.p3, {"ref": self.fix[:8]})
        self.p4 = self.add(lo=8, hi=8, note="filler")
        self.write(REPO_NEW.replace("Filler two.", "Filler two, reworded."))
        self.solo = self.commit("fix the filler pin")
        self.call("POST", "/api/pins/%d/close" % self.p4, {"ref": self.solo[:8]})

    def git(self, *args):
        """Run git in the repository; returns its stdout (a failure raises)."""
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def write(self, text):
        """Write main.tex with an mtime 5 s ahead, so the server sees the file as changed."""
        self.main.write_text(text, encoding="utf-8")
        t = time.time() + 5
        os.utime(self.main, (t, t))

    def commit(self, msg):
        """Commit the manuscript folder; returns the new commit hash."""
        self.git("add", "ms")
        self.git("commit", "--quiet", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()

    def diff(self, commit, pin=None):
        """GET /api/revision-diff for commit (scoped to pin when given) -> (status, body)."""
        q = "/api/revision-diff?commit=%s" % commit + ("&pin=%s" % pin if pin is not None else "")
        return self.call("GET", q)

    def diff_ok(self, commit, pin=None):
        """The body of a revision-diff request that must succeed. A failure shows the server's answer; a 500 used to
        surface only as KeyError: 'scope'."""
        code, d = self.diff(commit, pin)
        self.assertEqual(code, 200, d)
        return d


# ---------------------------------------------------------------- a manuscript moved between two server runs (v0.3.2)

# The manuscript MovedManuscriptBase moves: main.tex \input's sections/x.tex (20 numbered lines, two of them comments)
# and sections/long.tex (one line over 600 characters).
MOVED_MAIN = (
    "\\documentclass{article}\n\\begin{document}\n\\input{sections/x}\n\\input{sections/long}\n\\end{document}\n"
)
MOVED_X_LINES = [
    "%% line %d" % i if i in (1, 2) else "Sentence number %d about topic%d." % (i, i) for i in range(1, 21)
]
MOVED_X = "\n".join(MOVED_X_LINES) + "\n"
MOVED_LONG = "Long line " + "word " * 150 + "\n"  # one line over 600 characters (the «…» quote rule)


class MovedManuscriptBase(AccessBase):
    """A manuscript with \\input'ed sections at <tmp>/paper-a, pins placed there, then the folder renamed to paper-b."""

    def setUp(self):
        """Write the manuscript at paper-a, add a current pin, a legacy pin and a quoted legacy pin there."""
        super().setUp()
        root = Path(self.tmp.name)
        self.a, self.b = root / "paper-a", root / "paper-b"
        (self.a / "sections").mkdir(parents=True)
        (self.a / "main.tex").write_text(MOVED_MAIN, encoding="utf-8")
        (self.a / "sections" / "x.tex").write_text(MOVED_X, encoding="utf-8")
        (self.a / "sections" / "long.tex").write_text(MOVED_LONG, encoding="utf-8")
        self.use_root(self.a)
        self.p_new = self.pin_at("sections/x.tex", 5, 6)
        self.p_old = self.pin_at("sections/x.tex", 10, 11)
        self.p_quote = add_pin(
            {
                "file": str(self.a / "sections" / "long.tex"),
                "lo": 1,
                "hi": 1,
                "scope": "raw",
                "quote": "Long line word word",
                "note": "q",
            },
            dict(LOCAL_ACTOR),
        ).record["id"]
        self.make_legacy(self.p_old, self.p_quote)  # as 0.3.0 wrote them: no file_rel

    def use_root(self, root: Path):
        """Point the server at a manuscript root, as `limn serve --manuscript <root>` would."""
        ps.C.src, ps.C.main = root, root / "main.tex"

    def pin_at(self, rel, lo, hi, note="n"):
        """Add a line pin on the manuscript file rel (relative to the current root); returns its id."""
        return add_pin({"file": str(ps.C.src / rel), "lo": lo, "hi": hi, "note": note}, dict(LOCAL_ACTOR)).record["id"]

    def stored(self):
        """The stored records of pins.jsonl by id, as read from disk."""
        return {r["id"]: r for r in ps.read_pins()[0]}

    def rewrite(self, fn):
        """Edit pins.jsonl directly (a state written by another version, or by hand)."""
        rows = ps.read_pins()[0]
        fn(rows)
        ps.C.pins_jsonl.write_text(dump_jsonl(rows), encoding="utf-8")

    def make_legacy(self, *ids):
        """Drop file_rel from these pins' stored records, as 0.3.0 wrote them."""
        self.rewrite(lambda rows: [r.pop("file_rel", None) for r in rows if r["id"] in ids])

    def move(self):
        """Stop, rename the checkout, start again on the new path (the handler has no state beyond C and the files)."""
        os.rename(self.a, self.b)
        self.use_root(self.b)

    def api_pins(self):
        """GET /api/pins as a dict by id; fails the test unless it is a 200."""
        code, rows = self.call("GET", "/api/pins")
        self.assertEqual(code, 200, rows)
        return {r["id"]: r for r in rows}

    def pins_md(self):
        """GET /pins.md; fails the test unless it is a 200."""
        code, md = self.call("GET", "/pins.md")
        self.assertEqual(code, 200)
        return md
