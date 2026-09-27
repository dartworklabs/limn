"""The startup rules of `limn serve`: what a command line is allowed to start, and what it starts with.

The composition root (server.start) runs the steps in order and makes the run settings (limn.config.RunConfig) from
their answers; this module decides and never reads C or imports server.py (tests/test_startup.py checks). A step that cannot go on returns a
StartupRefused instead of ending the process - server.main() is the one place that exits (coding rule R3).

- Access (a security boundary, docs/adr/0002-access-control.md): access_options() turns the access flags into an
  AccessOptions or the refusal. The rule: bind loopback by default; a non-loopback --bind only with --auth
  trusted-proxy or an explicit --i-know-this-is-insecure; the deprecated headerless loopback agent only under tailscale
  on a loopback bind. access_log_lines() is the startup log about the result.
- Documents and files: the --doc specs (parse_doc_arg, parse_docs; a refusal is a DocsRefusal value, worded by
  doc_refusal_message), the main .tex without --doc (detect_main, pick_documents), the documents over the run's paths
  once the state folder is known (docs_of; make_docs is both steps), the state folder (state_dir, state_placement), and
  people.json's permissions (tighten_state_perms).
- The port: a free one (free_port), whether --port can be listened on (probe_port), and the one line for one that
  cannot (listen_refusal).
- The instance label and accent (default_label, clean_label, run_label, run_accent), and the startup summary.
- The package version --version and GET /api/version report (app_version).

Pure decisions and the few startup probes live together because they change together - one command-line option at a
time. The probes (free_port, probe_port, detect_main, parse_doc_arg's file checks, git_remote_url,
tighten_state_perms) touch only what their arguments name.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple, TypeAlias, TypedDict

from limn.access import (
    AUTH_PROVIDERS,
    HEADER_NAME_RE,
    LOOPBACK_AGENT_DEPRECATION,
    is_auth_provider,
    is_loopback_bind,
    local_owner_actor,
    parse_networks,
    parse_public_hosts,
    valid_login,
)
from limn.config import ACCENT_PALETTE, AccessOptions as AccessOptions, RunConfig
from limn.documents import DEFAULT_DOC_KEY, DOC_KEY_RE, DOC_NAME_MAX, DOCS_MAX, Doc, RunPaths
from limn.gitrun import run_git
from limn.mapping import truncate_quote

APP_NAME = "limn"
# Label shown so tabs don't get confused when multiple manuscript viewers are open at once (§Running multiple manuscript instances at once).
# The length cap is a safeguard so the tool bar / tab title doesn't grow unbounded from one long paper name.
LABEL_MAX = 40
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def app_version() -> str:
    """The package version (__version__ in src/limn/__init__.py), or "0+unknown" when that file cannot be read or has
    none. Reads the neighbouring file rather than importing the package, so it gives the same value whether the server
    is imported as a module (python -m limn.server) or run directly by file path (python .../limn/server.py)."""
    try:
        m = re.search(
            r'^__version__\s*=\s*["\']([^"\']+)["\']',
            Path(__file__).with_name("__init__.py").read_text(encoding="utf-8"),
            re.M,
        )
    except OSError:
        m = None
    return m.group(1) if m else "0+unknown"


class StartupRefused(NamedTuple):
    """Why the server does not start: the message main() prints to stderr before exiting with status 1."""

    message: str


# ---------------------------------------------------------------- access (docs/adr/0002-access-control.md)


def access_options(a: argparse.Namespace) -> AccessOptions | StartupRefused:
    """The access options (--auth, tokens/loopback agent, --bind, proxy, members) of a parsed `limn serve` command
    line, or the refusal with a clear message for a refused combination - main() stops before any build, so a
    misconfigured unit fails fast. The checks run in a fixed order, which decides the message of a line with several
    faults: --auth (argparse's choices already hold it to AUTH_PROVIDERS; checked again here, where the text becomes an
    AuthProvider, for a namespace built some other way), --bind, the non-loopback bind, --agent-loopback, --tailnet-agent, --public-host/--trusted-proxies, the
    proxy header names, --local-user.

    Rules: a non-loopback --bind needs --auth trusted-proxy or --i-know-this-is-insecure. The headerless loopback agent
    exists only under tailscale on a loopback bind; asking for it (--agent-loopback) anywhere else refuses to start."""
    auth = a.auth or "tailscale"
    if not is_auth_provider(auth):
        return StartupRefused("--auth takes one of %s: %r" % (", ".join(AUTH_PROVIDERS), auth))
    bind = a.bind or "127.0.0.1"
    try:
        loop_bind = is_loopback_bind(bind)
    except ValueError:
        return StartupRefused("--bind takes an IP address (or localhost): %s" % bind)
    if not loop_bind and auth != "trusted-proxy" and not a.i_know_this_is_insecure:
        return StartupRefused(
            "Refusing to bind %s with --auth %s: a non-loopback address is only safe behind an authenticating "
            "proxy (--auth trusted-proxy). Keep the default 127.0.0.1 and expose it with tailscale serve, or "
            "pass --i-know-this-is-insecure if this network is private." % (bind, auth)
        )
    loopback_agent_possible = auth == "tailscale" and loop_bind
    if a.agent_loopback is True and not loopback_agent_possible:
        return StartupRefused(
            "--agent-loopback (AGENT_LOOPBACK=1) works only with --auth tailscale on a loopback --bind "
            "(here: --auth %s, --bind %s). Give agents a token instead: limn token create <instance>" % (auth, bind)
        )
    agent_loopback = loopback_agent_possible and a.agent_loopback is not False
    if a.tailnet_agent and not agent_loopback:
        return StartupRefused(
            "--tailnet-agent (TAILNET_AGENT=1) extends the headerless loopback agent to requests through tailscale serve, "
            "so it needs it on: --auth tailscale, a loopback --bind and no --no-agent-loopback (here: --auth %s, "
            "--bind %s%s). Give agents a token instead: limn token create <instance>"
            % (auth, bind, ", --no-agent-loopback" if a.agent_loopback is False else "")
        )
    try:
        public_hosts = parse_public_hosts(a.public_host)
        trusted_proxies = parse_networks(a.trusted_proxies)
    except ValueError as e:
        return StartupRefused(str(e))
    for opt, v in (
        ("--proxy-user-header", a.proxy_user_header),
        ("--proxy-name-header", a.proxy_name_header),
        ("--proxy-email-header", a.proxy_email_header),
    ):
        if v is not None and not HEADER_NAME_RE.fullmatch(v):
            return StartupRefused("%s takes an HTTP header name: %r" % (opt, v))
    if a.local_user is not None and not valid_login(a.local_user):
        return StartupRefused("--local-user takes a login (no spaces, not 'local' or 'agent:...'): %r" % a.local_user)
    return AccessOptions(
        auth=auth,
        bind=bind,
        agent_loopback=agent_loopback,
        tailnet_agent=bool(a.tailnet_agent),
        public_hosts=public_hosts,
        trusted_proxies=trusted_proxies,
        proxy_user_header=a.proxy_user_header,
        proxy_name_header=a.proxy_name_header,
        proxy_email_header=a.proxy_email_header,
        members_only=bool(a.members_only),
        local_user=a.local_user,
        insecure=bool(a.i_know_this_is_insecure) and not loop_bind and auth != "trusted-proxy",
        agent_token_file=Path(a.agent_token_file).expanduser() if a.agent_token_file else None,
    )


def access_log_lines(s: AccessOptions, tokens: int, token_file_present: bool) -> list[str]:
    """Startup log lines about access: the provider line, and warnings for a non-loopback bind / the deprecated
    loopback agent. tokens is the number of valid entries in tokens.json; token_file_present whether
    s.agent_token_file exists (only shown when one is configured)."""
    parts: list[str] = [s.auth]
    if s.auth == "local":
        parts.append("owner %s" % local_owner_actor(s.local_user)["login"])
    if s.auth == "trusted-proxy":
        parts.append("proxies %s" % ",".join(str(n) for n in s.trusted_proxies))
        parts.append("user header %s" % s.proxy_user_header)
    parts.append("tokens %d" % tokens)
    if s.agent_token_file is not None:
        parts.append("token file %s (%s)" % (s.agent_token_file, "present" if token_file_present else "absent"))
    parts.append("loopback agent %s" % ("on (deprecated)" if s.agent_loopback else "off"))
    if s.agent_loopback:  # only meaningful where the loopback agent exists
        parts.append("tailnet agent %s" % ("on (deprecated)" if s.tailnet_agent else "off"))
    parts.append("members-only %s" % ("on" if s.members_only else "off"))
    if s.public_hosts:
        parts.append("public hosts %s" % ",".join(n + (":%d" % p if p else "") for n, p in s.public_hosts))
    out = ["auth        " + " · ".join(parts)]
    if not is_loopback_bind(s.bind):
        out.append(
            "warning     bound to %s (not loopback) - identity provider: %s. Anyone who can reach this port "
            "can try it; only %s"
            % (
                s.bind,
                s.auth,
                "the configured --trusted-proxies may vouch for people"
                if s.auth == "trusted-proxy"
                else "tokens and the provider stand in the way",
            )
        )
    if s.insecure:
        out.append(
            "warning     !!! --i-know-this-is-insecure: --auth %s on %s is NOT an authentication boundary - "
            "anyone on this network can read the manuscript and change pins. Use --auth trusted-proxy behind an "
            "authenticating proxy, or bind 127.0.0.1 and use tailscale serve !!!" % (s.auth, s.bind)
        )
    if s.agent_loopback:
        out.append("warning     " + LOOPBACK_AGENT_DEPRECATION)
    if s.tailnet_agent:
        out.append(
            "warning     --tailnet-agent: a headerless request through tailscale serve (a tagged device) is treated "
            "as the agent - anyone who can reach the tailnet address without an identity can change pins. Give "
            "remote agents a token (limn token create <instance>) and drop TAILNET_AGENT"
        )
    return out


# ---------------------------------------------------------------- the port


def free_port(start: int = 18300, end: int = 18400) -> int | StartupRefused:
    """Find a free port. The point is not to steal someone else's port."""
    for p in range(start, end):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return StartupRefused("No free port in the %d-%d range. Specify one with --port." % (start, end))


def port_in_use_message(bind: str, port: int) -> str:
    """The one line for a --port another process already listens on."""
    return "limn serve: port %d on %s is already in use - stop the other server, or pick another --port" % (port, bind)


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
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # the same option the server sets (allow_reuse_address)
        s.bind((bind, port))
    except OSError as e:
        return listen_refusal(bind, port, e)
    finally:
        s.close()
    return None


# ---------------------------------------------------------------- documents and the state folder (§Multiple documents)


class DocSpec(TypedDict):
    """One parsed --doc: key, display name, kind ('tex' or 'pdf'), build root (src) and main file, both resolved."""

    key: str
    name: str
    kind: str
    src: Path
    main: Path


@dataclass(frozen=True)
class DocNotKeyed:
    """The --doc value is not a string of the form <key>=<name>:<path> (it has no '=')."""

    spec: object


@dataclass(frozen=True)
class DocKeyInvalid:
    """The key before '=' is not [a-z0-9-]{1,24} (DOC_KEY_RE)."""

    key: str


@dataclass(frozen=True)
class DocNameUnseparated:
    """No ':' separates the display name from the path; spec is the whole --doc value."""

    key: str
    spec: str


@dataclass(frozen=True)
class DocNameEmpty:
    """The display name is empty once its whitespace is collapsed."""

    key: str


@dataclass(frozen=True)
class DocNameTooLong:
    """The display name (whitespace collapsed) is longer than DOC_NAME_MAX characters."""

    key: str
    name: str


@dataclass(frozen=True)
class DocPathEmpty:
    """Nothing but whitespace follows the ':' after the display name."""

    key: str


@dataclass(frozen=True)
class DocOutsideManuscript:
    """A path resolves outside --manuscript (a security constraint: pins only point at files inside it). part says
    which one - the build root of the '::' form or the plain path; manuscript and path are both resolved."""

    key: str
    part: Literal["root", "path"]
    manuscript: Path
    path: Path


@dataclass(frozen=True)
class DocExtendedMalformed:
    """The '::' form is not exactly one <build root>::<main.tex> with both sides non-empty; path is the path part."""

    key: str
    path: str


@dataclass(frozen=True)
class DocRootMissing:
    """The build root of the '::' form is not an existing folder."""

    key: str
    root: Path


@dataclass(frozen=True)
class DocMainAbsolute:
    """The main file after '::' is absolute; it must be relative to the build root."""

    key: str
    main: Path


@dataclass(frozen=True)
class DocMainOutsideRoot:
    """The main file after '::' resolves outside its build root."""

    key: str
    main: Path


@dataclass(frozen=True)
class DocExtendedNotTex:
    """The '::' form names a main file that is not .tex - the form is for LaTeX documents only."""

    key: str
    main: Path


@dataclass(frozen=True)
class DocFileMissing:
    """The resolved main file is not an existing regular file."""

    key: str
    main: Path


@dataclass(frozen=True)
class DocKindUnknown:
    """The main file is neither .tex (LaTeX) nor .pdf (view-only)."""

    key: str
    main: Path


@dataclass(frozen=True)
class TooManyDocs:
    """More --doc values than DOCS_MAX; count is how many were given."""

    count: int


@dataclass(frozen=True)
class DocKeyRepeated:
    """Two --doc values share a key."""

    key: str


# Why one --doc value cannot be served (parse_doc_arg), and why the --doc list cannot (make_docs adds its own two). All
# are answered the same way: pick_documents() refuses to start with doc_refusal_message()'s text.
DocSpecRefusal: TypeAlias = (
    DocNotKeyed
    | DocKeyInvalid
    | DocNameUnseparated
    | DocNameEmpty
    | DocNameTooLong
    | DocPathEmpty
    | DocOutsideManuscript
    | DocExtendedMalformed
    | DocRootMissing
    | DocMainAbsolute
    | DocMainOutsideRoot
    | DocExtendedNotTex
    | DocFileMissing
    | DocKindUnknown
)
DocsRefusal: TypeAlias = DocSpecRefusal | TooManyDocs | DocKeyRepeated


def parse_doc_arg(spec: str, ms: Path) -> DocSpec | DocSpecRefusal:
    """Parses one --doc <key>=<display name>:<path>. The path is relative to --manuscript (recommended) or absolute.

    - `<key>=<name>:a/b/main.tex` - LaTeX. The build root is the folder holding that .tex (a/b).
    - `<key>=<name>:a::b/main.tex` - LaTeX. The build root is a (the scope copied into the build copy), and
      main is a/b/main.tex. The build runs in the folder holding main (a/b) - used when main reads another
      folder inside the build root via ../.
    - `<key>=<name>:x/review.pdf` - a view-only PDF (no rebuild, page/region pins).
    key must be [a-z0-9-]{1,24}; name must be 40 characters or fewer with no ':'. The path must be inside
    --manuscript (a security constraint: a pin can only ever point at a file inside the manuscript tree).
    Returns the DocSpec, or the first rule the value breaks (DocSpecRefusal), checked in this order: form, key, name,
    path, then the files. Reads the file system only to resolve the paths and check that they exist."""
    if not isinstance(spec, str) or "=" not in spec:
        return DocNotKeyed(spec)
    key, rest = spec.split("=", 1)
    key = key.strip()
    if not DOC_KEY_RE.fullmatch(key):
        return DocKeyInvalid(key)
    if ":" not in rest:
        return DocNameUnseparated(key, spec)
    name, path = rest.split(":", 1)
    name = " ".join(name.split())
    if not name:
        return DocNameEmpty(key)
    if len(name) > DOC_NAME_MAX:
        return DocNameTooLong(key, name)
    path = path.strip()
    if not path:
        return DocPathEmpty(key)
    ms = ms.resolve()

    def inside(p: Path, part: Literal["root", "path"]) -> Path | DocOutsideManuscript:
        """p resolved against --manuscript, or the refusal when it lands outside the manuscript tree."""
        p = (p if p.is_absolute() else ms / p).resolve()
        try:
            p.relative_to(ms)
        except ValueError:
            return DocOutsideManuscript(key, part, ms, p)
        return p

    if "::" in path:
        root_s, main_s = path.split("::", 1)
        if "::" in main_s or not root_s.strip() or not main_s.strip():
            return DocExtendedMalformed(key, path)
        root = inside(Path(root_s.strip()), "root")
        if isinstance(root, DocOutsideManuscript):
            return root
        if not root.is_dir():
            return DocRootMissing(key, root)
        mp = Path(main_s.strip())
        if mp.is_absolute():
            return DocMainAbsolute(key, mp)
        main = (root / mp).resolve()
        try:
            main.relative_to(root)
        except ValueError:
            return DocMainOutsideRoot(key, main)
        if main.suffix.lower() != ".tex":
            return DocExtendedNotTex(key, main)
    else:
        found = inside(Path(path), "path")
        if isinstance(found, DocOutsideManuscript):
            return found
        main, root = found, found.parent
    if not main.is_file():
        return DocFileMissing(key, main)
    suf = main.suffix.lower()
    if suf == ".tex":
        kind = "tex"
    elif suf == ".pdf":
        kind = "pdf"
    else:
        return DocKindUnknown(key, main)
    return DocSpec(key=key, name=name, kind=kind, src=root, main=main)


def doc_refusal_message(r: DocsRefusal) -> str:
    """The text the server refuses to start with for each --doc refusal (Korean, worded as it always was)."""
    match r:
        case DocNotKeyed(spec=spec):
            return "--doc 는 <키>=<표시 이름>:<경로> 형식입니다: %r" % (spec,)
        case DocKeyInvalid(key=key):
            return "--doc 키는 영문 소문자·숫자·'-' 1–24자여야 합니다: %r" % key
        case DocNameUnseparated(key=key, spec=spec):
            return "--doc %s: 표시 이름과 경로 사이에 ':' 가 없습니다: %r" % (key, spec)
        case DocNameEmpty(key=key):
            return "--doc %s: 표시 이름이 비었습니다" % key
        case DocNameTooLong(key=key, name=name):
            return "--doc %s: 표시 이름은 %d자 이하여야 합니다: %r" % (key, DOC_NAME_MAX, name)
        case DocPathEmpty(key=key):
            return "--doc %s: 경로가 비었습니다" % key
        case DocOutsideManuscript(key=key, part=part, manuscript=ms, path=path):
            what = "빌드 루트" if part == "root" else "경로"
            return "--doc %s: %s 가 --manuscript(%s) 밖입니다: %s" % (key, what, ms, path)
        case DocExtendedMalformed(key=key, path=text):
            return "--doc %s: 확장 표기는 <빌드 루트>::<메인.tex> 하나입니다: %r" % (key, text)
        case DocRootMissing(key=key, root=root):
            return "--doc %s: 빌드 루트 폴더가 없습니다: %s" % (key, root)
        case DocMainAbsolute(key=key, main=main):
            return "--doc %s: '::' 뒤 메인은 빌드 루트 기준 상대경로입니다: %s" % (key, main)
        case DocMainOutsideRoot(key=key, main=main):
            return "--doc %s: 메인 .tex 가 빌드 루트 밖입니다: %s" % (key, main)
        case DocExtendedNotTex(key=key, main=main):
            return "--doc %s: '::' 표기는 LaTeX 문서(.tex)에만 씁니다: %s" % (key, main)
        case DocFileMissing(key=key, main=main):
            return "--doc %s: 파일이 없습니다: %s" % (key, main)
        case DocKindUnknown(key=key, main=main):
            return "--doc %s: .tex(LaTeX) 또는 .pdf(보기 전용)만 받습니다: %s" % (key, main)
        case TooManyDocs(count=count):
            return "--doc 는 %d개까지입니다(지금 %d개)" % (DOCS_MAX, count)
        case DocKeyRepeated(key=key):
            return "--doc 키가 겹칩니다: %s" % key


def parse_docs(specs: Sequence[str], ms: Path) -> list[DocSpec] | DocsRefusal:
    """--doc list -> the parsed documents in order, or the first refusal: more than DOCS_MAX values (checked before any
    is parsed), a value parse_doc_arg refuses, or a key used twice."""
    if len(specs) > DOCS_MAX:
        return TooManyDocs(len(specs))
    out: list[DocSpec] = []
    seen: set[str] = set()
    for spec in specs:
        p = parse_doc_arg(spec, ms)
        if not isinstance(p, dict):
            return p
        if p["key"] in seen:
            return DocKeyRepeated(p["key"])
        seen.add(p["key"])
        out.append(p)
    return out


def docs_of(specs: Sequence[DocSpec], paths: RunPaths) -> list[Doc]:
    """The documents of parsed --doc specs over the run's paths (the frozen value the composition root made once the
    state folder was known). A LaTeX document keyed main uses the state-folder-root layout (root)."""
    return [
        Doc(
            p["key"],
            p["name"],
            p["kind"],
            src=p["src"],
            main=p["main"],
            root=(p["key"] == DEFAULT_DOC_KEY and p["kind"] == "tex"),
            paths=paths,
        )
        for p in specs
    ]


def make_docs(specs: Sequence[str], ms: Path, paths: RunPaths) -> list[Doc] | DocsRefusal:
    """--doc list -> Doc list over the run paths it is given (parse_docs, then docs_of), or parse_docs' refusal."""
    parsed = parse_docs(specs, ms)
    return docs_of(parsed, paths) if isinstance(parsed, list) else parsed


def detect_main(src: Path) -> Path | StartupRefused:
    """Find the top-level .tex. If it's ambiguous, don't guess - refuse with the candidates."""
    cands = [
        p
        for p in sorted(src.glob("*.tex"))
        if "\\documentclass" in p.read_text(encoding="utf-8", errors="ignore")[:20000]
    ]
    if len(cands) == 1:
        return cands[0]
    how = "found none" if not cands else "found several"
    listing = "\n".join("  - %s" % p.name for p in cands) or "  (none)"
    return StartupRefused(
        "%s: %s top-level .tex files under %s. Specify one with --main.\n%s" % (APP_NAME, how, src, listing)
    )


@dataclass(frozen=True)
class RunDocuments:
    """What the command line serves: the parsed --doc documents (None without --doc: the single document of --main) and
    the main .tex of the run (the first LaTeX --doc document's, else the first document's; else --main's or the
    detected one). The documents are made over the run's paths (docs_of) once the state folder is known."""

    docs: list[DocSpec] | None
    main: Path


def pick_documents(src: Path, specs: Sequence[str], main: str | None) -> RunDocuments | StartupRefused:
    """The documents of a command line with manuscript folder src (already resolved), or the refusal, in this order: a
    missing manuscript folder, --doc together with --main, a bad --doc, no or several top-level .tex files, a --main
    that does not exist."""
    if not src.is_dir():
        return StartupRefused("Manuscript directory does not exist: %s" % src)
    if specs:
        if main:
            return StartupRefused("--doc and --main are not used together - the main file is set via the --doc path.")
        docs = parse_docs(specs, src)
        if not isinstance(docs, list):
            return StartupRefused(doc_refusal_message(docs))
        first_tex = next((d for d in docs if d["kind"] != "pdf"), docs[0])
        return RunDocuments(docs, first_tex["main"])
    main_file = (src / main) if main else detect_main(src)
    if isinstance(main_file, StartupRefused):
        return main_file
    if not main_file.exists():
        return StartupRefused("Top-level .tex does not exist: %s" % main_file)
    return RunDocuments(None, main_file)


def state_slug(src: Path) -> str:
    """Separates state per manuscript - so opening manuscripts A and B at once doesn't mix their pins."""
    return "%s-%s" % (src.name, hashlib.sha1(str(src).encode()).hexdigest()[:8])


def state_dir(state_dir_arg: str | None, src: Path, data_home: Path) -> Path:
    """The state folder: --state-dir (resolved), else <data_home>/limn/serve/<state_slug(src)>, where data_home is
    $XDG_DATA_HOME or ~/.local/share. Only decides; the caller creates it."""
    return (
        Path(state_dir_arg).expanduser().resolve() if state_dir_arg else data_home / "limn" / "serve" / state_slug(src)
    )


@dataclass(frozen=True)
class StateInManuscript:
    """The state folder lies inside the manuscript folder and holds none of the served documents: the run starts, the
    manuscript tree (limn.files.tree_part) and the build copy leave the folder out, and main() prints warning() on
    stderr - the folder holds people.json, tokens.json (hashes), audit.jsonl and events.jsonl, which git or a file
    sync of the manuscript would otherwise carry along."""

    state: Path
    manuscript: Path

    def warning(self) -> str:
        """The one stderr line about it."""
        return (
            "warning: the state folder %s is inside the manuscript %s - Limn leaves it out of the manuscript tree "
            "(snippets, pins, the build copy), but it holds people.json, tokens.json (hashes), audit.jsonl and "
            "events.jsonl: keep it out of git (.gitignore) and file sync, or give a --state-dir outside the manuscript"
            % (self.state, self.manuscript)
        )


def state_placement(state: Path, src: Path, served: Sequence[Path]) -> StateInManuscript | StartupRefused | None:
    """Where the state folder lies against the manuscript folder src, both with symlinks resolved: None outside it
    (the default place, or a folder that holds the manuscript), StateInManuscript inside it, and a refusal when it
    also holds a file of `served` (the documents' main files) - the tree rule never reads a file of the state
    folder, so such a document could take no pin (a state folder that is the manuscript folder itself is one)."""
    try:
        held, base = state.resolve(), src.resolve()
    except (OSError, RuntimeError):
        return None
    if not held.is_relative_to(base):
        return None
    for f in served:
        with contextlib.suppress(OSError, RuntimeError):
            if f.resolve().is_relative_to(held):
                return StartupRefused(
                    "The state folder %s holds %s, a document this run serves: Limn never reads a file of its state "
                    "folder as manuscript, so that document could take no pin. Give a --state-dir outside the "
                    "manuscript (the default) or a folder of its own." % (held, f)
                )
    return StateInManuscript(held, base)


def tighten_state_perms(people_file: Path) -> None:
    """people.json holds logins and roles (roles are permissions). It is written 0600 since v0.2.1; an older file that
    others may write is tightened to 0600 on startup, logged once on stderr. Other state files keep their mode -
    pins.md and pins.jsonl are what agents (possibly another account on the machine) read. A missing file is left
    alone; a chmod that fails is a warning, never a refused start."""
    p = people_file
    try:
        mode = p.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o022:
        try:
            os.chmod(p, 0o600)
        except OSError as e:
            print(
                "warning: %s is writable by others (%o) and could not be tightened: %s" % (p, mode, e), file=sys.stderr
            )
            return
        print("people.json: tightened %s from %o to 600 (it was writable by others)" % (p, mode), file=sys.stderr)


# ---------------------------------------------------------------- instance label (§Running multiple manuscript instances at once)


def git_remote_url(src: Path) -> str | None:
    """git origin URL of --manuscript. None if it isn't a git repo or has no origin - a failure never blocks startup."""
    if not shutil.which("git"):
        return None
    try:
        r = run_git(["-C", str(src), "remote", "get-url", "origin"], src, 5)
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


def default_label(src: Path, repo_url: str | None) -> str:
    """Default label used when --label is absent: the git repo name, or the manuscript folder name if none."""
    if repo_url:
        name = repo_name_from_url(repo_url)
        if name:
            return name
    return src.name


def clean_label(v: object) -> str | StartupRefused:
    """Validate a label. Newlines and excessive length are blocked here since they'd break the tool bar / tab title."""
    v = "" if v is None else str(v).strip()
    v = " ".join(v.split())  # collapse newlines/tabs/repeated whitespace to a single space
    if not v:
        v = "원고"
    if len(v) > LABEL_MAX:
        return StartupRefused("--label must be %d characters or fewer: %r" % (LABEL_MAX, v))
    return v


def run_label(label_arg: str | None, src: Path, repo_url: str | None) -> str | StartupRefused:
    """The label of the run: --label when given (refused when too long, so a typo is never silently truncated), else
    the default label truncated to LABEL_MAX - startup must not halt just because of a long repo name (observed: a
    62-character repo)."""
    return clean_label(label_arg) if label_arg else clean_label(truncate_quote(default_label(src, repo_url), LABEL_MAX))


def pick_accent(label: str) -> str:
    """Pick one from the palette by hashing the label string - the same label always gets the same color."""
    idx = int(hashlib.sha1(label.encode("utf-8")).hexdigest(), 16) % len(ACCENT_PALETTE)
    return ACCENT_PALETTE[idx]


def valid_accent(v: object) -> bool:
    """Whether v is a #rrggbb color."""
    return isinstance(v, str) and ACCENT_RE.fullmatch(v) is not None


def run_accent(accent_arg: str | None, label: str) -> str | StartupRefused:
    """The accent of the run: --accent lowercased (refused unless #rrggbb), else the palette pick for the label."""
    if accent_arg:
        if not valid_accent(accent_arg):
            return StartupRefused("--accent must be in #rrggbb form: %s" % accent_arg)
        return accent_arg.lower()
    return pick_accent(label)


# ---------------------------------------------------------------- the startup summary


def summary_lines(c: RunConfig, multi_doc: bool, access_lines: Sequence[str], pdfjs_found: bool) -> list[str]:
    """The startup summary: manuscript (the folder with --doc, else the main .tex), label, state folder, address,
    access (access_lines), the allow list, and the optional features. pdfjs_found says whether both PDF.js files are
    in c.pdfjs_dir."""
    bind = c.access.bind
    host = "[%s]" % bind if ":" in bind else bind
    out = [
        "manuscript  %s" % (c.src if multi_doc else c.main),
        "label       %s (%s)%s"
        % (c.label, c.accent, "" if c.repo else " - no git origin, using the folder name as default"),
        "state       %s" % c.state,
    ]
    if is_loopback_bind(bind):
        out.append("address     http://%s:%d/   (external exposure only via tailscale serve)" % (host, c.port))
    else:
        out.append("address     http://%s:%d/" % (host, c.port))
    out.extend(access_lines)
    if c.allow:
        out.append(
            "allow       %s%s"
            % (
                ", ".join(sorted(c.allow)),
                " (a loopback request with no header is still allowed)" if c.access.agent_loopback else "",
            )
        )
    if not c.origin_check:
        out.append("warning     --no-origin-check: Host/Origin checking is off (no DNS rebinding defense)")
    if c.git_pull:
        out.append(
            "git-pull    checks main right after startup and every 60 seconds, rebuilding the PDF on a new commit"
        )
    if pdfjs_found:
        out.append("pdf.js      %s (vector rendering)" % c.pdfjs_dir)
    else:
        out.append("warning     pdf.js is missing (%s) - the viewer falls back to PNG" % c.pdfjs_dir)
    return out
