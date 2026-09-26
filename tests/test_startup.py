"""limn.startup, limn.args and limn.config - the startup rules of `limn serve`, driven directly with plain values.

The composition (server.start: configure_access, the --port probe, configure_run, prepare, report, listen) runs in
tests/test_access.py (StartupRules, TailnetAgentStartup) and as a real process in tests/test_access.py (serve on a busy
port) and tests/test_token_file.py. This file pins each rule, every access refusal's exact message (a security
boundary, docs/adr/0002-access-control.md) and the module boundary. DocArgs hands make_docs the server copy's run
settings (helpers.ps.C) as the documents' paths, as server.py does.

Run: uv run pytest -q tests/test_startup.py
"""
import argparse
import ast
import dataclasses
import errno
import ipaddress
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from limn import args, config, startup
from limn.access import LOOPBACK_AGENT_DEPRECATION
from limn.documents import DOCS_MAX
from limn.startup import AccessOptions, RunDocuments, StartupRefused

from helpers import MINI_PDF, TEX as FIXTURE_TEX, ps

SRC = Path(__file__).resolve().parent.parent / "src" / "limn"
TEX = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"


def parse(*argv: str) -> argparse.Namespace:
    """A `limn serve` command line with --manuscript x and argv, parsed by the real parser."""
    return args.serve_parser("Limn test", "limn 0", "figure").parse_args(["--manuscript", "x", *argv])


def options(*argv: str) -> AccessOptions:
    """The access options of a command line the rules accept; a refusal fails the test."""
    got = startup.access_options(parse(*argv))
    assert isinstance(got, AccessOptions), got
    return got


def refusal(*argv: str) -> str:
    """The message of a command line the access rules refuse."""
    got = startup.access_options(parse(*argv))
    assert isinstance(got, StartupRefused), got
    return got.message


class ModuleBoundary(unittest.TestCase):
    """The startup modules decide and describe; the composition root (server.py) applies and exits."""

    def test_no_server_import_no_run_settings_global_no_exit(self):
        """Neither imports limn.server, names the global C, or calls sys.exit (R3: only server.main exits)."""
        for name in ("startup.py", "args.py", "config.py"):
            tree = ast.parse((SRC / name).read_text(encoding="utf-8"))
            with self.subTest(name):
                modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
                modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
                self.assertFalse({m for m in modules if m.startswith(("limn.server", "server"))}, modules)
                names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                self.assertNotIn("C", names)
                exits = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                         and c.func.attr == "exit"]
                self.assertEqual(exits, [])

    def test_access_options_are_run_settings_of_the_same_name(self):
        """Every AccessOptions field is a Cfg setting (configure_access copies them by name), and a command line with no
        access flags starts with exactly Cfg's defaults - the v0.1-equivalent behaviour."""
        fields = [f.name for f in dataclasses.fields(AccessOptions)]
        self.assertLessEqual(set(fields), set(config.Cfg.__annotations__))
        defaults = options()
        for name in fields:
            with self.subTest(name):
                self.assertEqual(getattr(defaults, name), getattr(config.Cfg, name))


class AccessRefusals(unittest.TestCase):
    """Every refused access combination, with the exact message main() prints before exiting with status 1."""

    def test_bind_must_be_an_address(self):
        """A --bind that is not an IP address or localhost."""
        for bad in ("notanip", "example.com"):
            self.assertEqual(refusal("--bind", bad), "--bind takes an IP address (or localhost): %s" % bad)

    def test_non_loopback_bind_needs_trusted_proxy_or_the_insecure_flag(self):
        """Loopback only by default: tailscale and local refuse any non-loopback address, IPv4 or IPv6."""
        for auth, bind in (("tailscale", "0.0.0.0"), ("local", "0.0.0.0"), ("tailscale", "::"), ("local", "10.1.2.3")):
            with self.subTest(auth=auth, bind=bind):
                self.assertEqual(refusal("--auth", auth, "--bind", bind),
                                 "Refusing to bind %s with --auth %s: a non-loopback address is only safe behind an "
                                 "authenticating proxy (--auth trusted-proxy). Keep the default 127.0.0.1 and expose it "
                                 "with tailscale serve, or pass --i-know-this-is-insecure if this network is private."
                                 % (bind, auth))

    def test_explicit_loopback_agent_only_under_tailscale_on_loopback(self):
        """--agent-loopback where the headerless agent cannot exist refuses to start."""
        for argv, auth, bind in ((("--auth", "local"), "local", "127.0.0.1"),
                                 (("--auth", "trusted-proxy"), "trusted-proxy", "127.0.0.1"),
                                 (("--auth", "trusted-proxy", "--bind", "0.0.0.0"), "trusted-proxy", "0.0.0.0"),
                                 (("--bind", "0.0.0.0", "--i-know-this-is-insecure"), "tailscale", "0.0.0.0")):
            with self.subTest(argv):
                self.assertEqual(refusal(*argv, "--agent-loopback"),
                                 "--agent-loopback (AGENT_LOOPBACK=1) works only with --auth tailscale on a loopback "
                                 "--bind (here: --auth %s, --bind %s). Give agents a token instead: limn token create "
                                 "<instance>" % (auth, bind))

    def test_tailnet_agent_needs_the_loopback_agent(self):
        """--tailnet-agent without the loopback agent; --no-agent-loopback is named when it was the cause."""
        for argv, auth, bind, extra in ((("--no-agent-loopback",), "tailscale", "127.0.0.1", ", --no-agent-loopback"),
                                        (("--auth", "local"), "local", "127.0.0.1", ""),
                                        (("--auth", "trusted-proxy"), "trusted-proxy", "127.0.0.1", ""),
                                        (("--bind", "0.0.0.0", "--i-know-this-is-insecure"), "tailscale", "0.0.0.0", "")):
            with self.subTest(argv):
                self.assertEqual(refusal(*argv, "--tailnet-agent"),
                                 "--tailnet-agent (TAILNET_AGENT=1) extends the headerless loopback agent to requests "
                                 "through tailscale serve, so it needs it on: --auth tailscale, a loopback --bind and no "
                                 "--no-agent-loopback (here: --auth %s, --bind %s%s). Give agents a token instead: limn "
                                 "token create <instance>" % (auth, bind, extra))

    def test_bad_hosts_networks_headers_and_local_user(self):
        """The value checks, each with its own message."""
        cases = [
            (("--public-host", "https://x.example.com/"),
             "--public-host takes a DNS name with an optional :port, got 'https://x.example.com/'"),
            (("--public-host", "localhost"), "--public-host takes a DNS name with an optional :port, got 'localhost'"),
            (("--trusted-proxies", "proxy.example.com"),
             "--trusted-proxies takes IP addresses or CIDR ranges, got 'proxy.example.com'"),
            (("--trusted-proxies", " , "), "--trusted-proxies is empty"),
            (("--proxy-user-header", "X User"), "--proxy-user-header takes an HTTP header name: 'X User'"),
            (("--proxy-name-header", "X_Name"), "--proxy-name-header takes an HTTP header name: 'X_Name'"),
            (("--proxy-email-header=X Email",), "--proxy-email-header takes an HTTP header name: 'X Email'"),
        ]
        for login in ("agent:me", "local", "a b", ""):
            cases.append((("--local-user", login),
                          "--local-user takes a login (no spaces, not 'local' or 'agent:...'): %r" % login))
        for argv, message in cases:
            with self.subTest(argv):
                self.assertEqual(refusal(*argv), message)

    def test_the_first_fault_in_rule_order_is_the_one_reported(self):
        """bind, then the loopback agent, then hosts/networks, then headers, then --local-user."""
        self.assertTrue(refusal("--bind", "0.0.0.0", "--local-user", "agent:x").startswith("Refusing to bind"))
        self.assertTrue(refusal("--auth", "local", "--agent-loopback", "--tailnet-agent").startswith("--agent-loopback"))
        self.assertTrue(refusal("--public-host", "x/", "--trusted-proxies", "bad").startswith("--public-host"))
        self.assertTrue(refusal("--proxy-user-header", "a b", "--local-user", "agent:x").startswith("--proxy-user-header"))


class AccessAccepted(unittest.TestCase):
    """What an accepted command line starts with."""

    def test_loopback_agent_only_under_tailscale_on_loopback(self):
        """On by default under tailscale on any loopback bind; forced off elsewhere, off with --no-agent-loopback."""
        for bind in ("127.0.0.1", "127.0.0.2", "::1", "localhost"):
            self.assertTrue(options("--bind", bind).agent_loopback, bind)
        self.assertFalse(options("--no-agent-loopback").agent_loopback)
        self.assertFalse(options("--auth", "local").agent_loopback)
        self.assertFalse(options("--auth", "trusted-proxy", "--bind", "0.0.0.0").agent_loopback)
        self.assertFalse(options("--bind", "0.0.0.0", "--i-know-this-is-insecure").agent_loopback)
        self.assertTrue(options("--tailnet-agent").tailnet_agent)

    def test_insecure_only_marks_a_non_loopback_bind_without_trusted_proxy(self):
        """The loud warning's flag: set only where the insecure flag actually opened a non-loopback bind."""
        self.assertTrue(options("--bind", "0.0.0.0", "--i-know-this-is-insecure").insecure)
        self.assertFalse(options("--i-know-this-is-insecure").insecure)
        self.assertFalse(options("--auth", "trusted-proxy", "--bind", "0.0.0.0", "--i-know-this-is-insecure").insecure)

    def test_values_are_parsed(self):
        """Hosts, networks, headers, members-only, local user and the token file path (with ~ expanded)."""
        got = options("--auth", "trusted-proxy", "--public-host", "A.example.com:8443,b.example.com",
                      "--trusted-proxies", "10.0.0.0/8", "--proxy-email-header", "X-Email", "--members-only",
                      "--local-user", "alice", "--agent-token-file", "~/t.token")
        self.assertEqual(got.public_hosts, (("a.example.com", 8443), ("b.example.com", None)))
        self.assertEqual(got.trusted_proxies, (ipaddress.ip_network("10.0.0.0/8"),))
        self.assertEqual((got.proxy_email_header, got.members_only, got.local_user), ("X-Email", True, "alice"))
        self.assertEqual(got.agent_token_file, Path("~/t.token").expanduser())


class AccessLog(unittest.TestCase):
    """access_log_lines(): the startup lines about access."""

    def test_default_line_and_deprecation_warning(self):
        """The v0.1-equivalent start: the provider line and the loopback-agent warning."""
        self.assertEqual(startup.access_log_lines(options(), 0, False), [
            "auth        tailscale · tokens 0 · loopback agent on (deprecated) · tailnet agent off · members-only off",
            "warning     " + LOOPBACK_AGENT_DEPRECATION])

    def test_trusted_proxy_on_a_public_address(self):
        """Proxies, header, token count and file, public hosts, and the not-loopback warning."""
        got = options("--auth", "trusted-proxy", "--bind", "0.0.0.0", "--trusted-proxies", "10.0.0.0/8",
                      "--public-host", "a.example.com:8443", "--agent-token-file", "/x/t.token", "--members-only")
        self.assertEqual(startup.access_log_lines(got, 2, True), [
            "auth        trusted-proxy · proxies 10.0.0.0/8 · user header X-Forwarded-User · tokens 2 · token file "
            "/x/t.token (present) · loopback agent off · members-only on · public hosts a.example.com:8443",
            "warning     bound to 0.0.0.0 (not loopback) - identity provider: trusted-proxy. Anyone who can reach this "
            "port can try it; only the configured --trusted-proxies may vouch for people"])

    def test_insecure_and_tailnet_warnings(self):
        """The loud insecure warning, the local owner, and the tailnet-agent warning."""
        lines = startup.access_log_lines(options("--auth", "local", "--local-user", "bob", "--bind", "0.0.0.0",
                                                 "--i-know-this-is-insecure"), 0, False)
        self.assertEqual(lines[0], "auth        local · owner bob · tokens 0 · loopback agent off · members-only off")
        self.assertTrue(lines[2].startswith("warning     !!! --i-know-this-is-insecure: --auth local on 0.0.0.0 is NOT"))
        lines = startup.access_log_lines(options("--tailnet-agent"), 0, False)
        self.assertIn("tailnet agent on (deprecated)", lines[0])
        self.assertTrue(lines[-1].startswith("warning     --tailnet-agent: a headerless request"))


class Port(unittest.TestCase):
    """The --port probe and the one line for a port that cannot be listened on."""

    def test_listen_refusal_names_a_taken_port_or_the_os_reason(self):
        """EADDRINUSE is the 'already in use' line; any other error quotes the OS's reason."""
        self.assertEqual(startup.listen_refusal("127.0.0.1", 18999, OSError(errno.EADDRINUSE, "in use")),
                         StartupRefused("limn serve: port 18999 on 127.0.0.1 is already in use - stop the other server, "
                                        "or pick another --port"))
        self.assertEqual(startup.listen_refusal("10.0.0.9", 80, OSError(errno.EADDRNOTAVAIL, "Cannot assign")),
                         StartupRefused("limn serve: cannot listen on 10.0.0.9 port 80: Cannot assign"))

    def test_probe_refuses_a_taken_port_and_passes_a_free_one(self):
        """A port another socket listens on refuses; the same port once closed passes."""
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            self.assertEqual(startup.probe_port("127.0.0.1", port),
                             StartupRefused(startup.port_in_use_message("127.0.0.1", port)))
        self.assertIsNone(startup.probe_port("127.0.0.1", port))

    def test_no_free_port_is_a_refusal(self):
        """Every port of the range answers: the refusal names the range."""
        with mock.patch.object(startup.socket, "socket") as sock:
            sock.return_value.__enter__.return_value.connect_ex.return_value = 0
            self.assertEqual(startup.free_port(18300, 18302),
                             StartupRefused("No free port in the 18300-18302 range. Specify one with --port."))


class Documents(unittest.TestCase):
    """pick_documents() and state_dir(): what a command line serves and where its state lives."""

    def setUp(self):
        """A manuscript with main.tex, sub/r.tex and a view-only PDF."""
        self.tmp = tempfile.TemporaryDirectory()
        self.ms = Path(self.tmp.name).resolve() / "ms"
        (self.ms / "sub").mkdir(parents=True)
        (self.ms / "main.tex").write_text(TEX, encoding="utf-8")
        (self.ms / "sub" / "r.tex").write_text(TEX, encoding="utf-8")
        (self.ms / "view.pdf").write_bytes(b"%PDF-1.4\n")
        self.paths = config.Cfg()

    def tearDown(self):
        """Remove the manuscript."""
        self.tmp.cleanup()

    def test_refusals_in_order(self):
        """A missing folder first, then --doc with --main, a bad --doc, a missing --main."""
        missing = self.ms / "nope"
        self.assertEqual(startup.pick_documents(missing, ["x=y:main.tex"], "main.tex", self.paths),
                         StartupRefused("Manuscript directory does not exist: %s" % missing))
        self.assertEqual(startup.pick_documents(self.ms, ["x=y:bad.tex"], "main.tex", self.paths),
                         StartupRefused("--doc and --main are not used together - the main file is set via the --doc path."))
        self.assertEqual(startup.pick_documents(self.ms, ["x=y:none.tex"], None, self.paths),
                         StartupRefused("--doc x: 파일이 없습니다: %s" % (self.ms / "none.tex")))
        self.assertEqual(startup.pick_documents(self.ms, [], "none.tex", self.paths),
                         StartupRefused("Top-level .tex does not exist: %s" % (self.ms / "none.tex")))

    def test_main_is_the_first_latex_document_or_the_detected_one(self):
        """Under --doc the run's main is the first LaTeX document's (a PDF listed first is skipped); without --doc it
        is --main or the single top-level .tex, and there are no --doc documents."""
        got = startup.pick_documents(self.ms, ["rv=View:view.pdf", "rr=R:sub/r.tex"], None, self.paths)
        assert isinstance(got, RunDocuments)
        self.assertEqual(([d.key for d in got.docs or []], got.main), (["rv", "rr"], self.ms / "sub" / "r.tex"))
        self.assertIs(got.docs[0].paths, self.paths)
        only_pdf = startup.pick_documents(self.ms, ["rv=View:view.pdf"], None, self.paths)
        assert isinstance(only_pdf, RunDocuments)
        self.assertEqual(only_pdf.main, self.ms / "view.pdf")
        self.assertEqual(startup.pick_documents(self.ms, [], None, self.paths), RunDocuments(None, self.ms / "main.tex"))
        self.assertEqual(startup.pick_documents(self.ms, [], "sub/r.tex", self.paths),
                         RunDocuments(None, self.ms / "sub" / "r.tex"))

    def test_state_dir(self):
        """--state-dir resolved, else the per-manuscript slug under the data home."""
        self.assertEqual(startup.state_dir(str(self.ms / "st" / ".." / "st2"), self.ms, Path("/d")), self.ms / "st2")
        self.assertEqual(startup.state_dir(None, self.ms, Path("/d")),
                         Path("/d") / "limn" / "serve" / startup.state_slug(self.ms))
        self.assertTrue(startup.state_slug(self.ms).startswith("ms-"))

    def test_tighten_only_group_or_world_writable_people_json(self):
        """0666 becomes 0600; 0644 and a missing file are left alone."""
        p = self.ms / "people.json"
        startup.tighten_state_perms(p)                      # missing: nothing happens
        p.write_text("{}", encoding="utf-8")
        os.chmod(p, 0o644)
        startup.tighten_state_perms(p)
        self.assertEqual(p.stat().st_mode & 0o777, 0o644)
        os.chmod(p, 0o666)
        with mock.patch.object(startup.sys, "stderr"):
            startup.tighten_state_perms(p)
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)


class LabelAndAccent(unittest.TestCase):
    """run_label() and run_accent(): the instance's label and accent."""

    def test_explicit_label_is_refused_when_long_the_default_is_truncated(self):
        """A typo in --label is never silently truncated; a long repo name never halts startup."""
        self.assertIsInstance(startup.run_label("x" * (startup.LABEL_MAX + 1), Path("/m"), None), StartupRefused)
        long_repo = "git@example.com:org/" + "r" * 60 + ".git"
        label = startup.run_label(None, Path("/m"), long_repo)
        self.assertIsInstance(label, str)
        self.assertLessEqual(len(label), startup.LABEL_MAX)
        self.assertEqual(startup.run_label(None, Path("/m/paper"), None), "paper")
        self.assertEqual(startup.run_label(" A\nB ", Path("/m"), None), "A B")

    def test_accent_given_lowercased_or_picked(self):
        """--accent is lowercased when #rrggbb, refused otherwise; absent, the label picks one from the palette."""
        self.assertEqual(startup.run_accent("#ABCDEF", "x"), "#abcdef")
        self.assertEqual(startup.run_accent("red", "x"), StartupRefused("--accent must be in #rrggbb form: red"))
        self.assertEqual(startup.run_accent(None, "A-DEMO"), startup.pick_accent("A-DEMO"))
        self.assertIn(startup.run_accent(None, "A-DEMO"), config.ACCENT_PALETTE)


class Summary(unittest.TestCase):
    """summary_lines(): the startup summary on stdout."""

    def test_single_document_on_loopback(self):
        """The main file for a single document, the loopback address note, access lines as given, pdf.js found."""
        c = config.Cfg()
        c.src, c.main, c.state, c.port, c.allow = Path("/m"), Path("/m/main.tex"), Path("/s"), 18300, frozenset()
        c.pdfjs_dir = Path("/p")
        self.assertEqual(startup.summary_lines(c, False, ["auth        x"], True), [
            "manuscript  /m/main.tex",
            "label       원고 (#1d4ed8) - no git origin, using the folder name as default",
            "state       /s",
            "address     http://127.0.0.1:18300/   (external exposure only via tailscale serve)",
            "auth        x",
            "pdf.js      /p (vector rendering)"])

    def test_documents_ipv6_and_optional_features(self):
        """The folder under --doc, a bracketed IPv6 address, allow, --no-origin-check, --git-pull, missing pdf.js."""
        c = config.Cfg()
        c.src, c.main, c.state, c.port = Path("/m"), Path("/m/main.tex"), Path("/s"), 18301
        c.bind, c.repo, c.allow, c.origin_check, c.git_pull = "::", "git@x:y.git", frozenset({"b", "a"}), False, True
        c.agent_loopback = False
        self.assertEqual(startup.summary_lines(c, True, [], False), [
            "manuscript  /m",
            "label       원고 (#1d4ed8)",
            "state       /s",
            "address     http://[::]:18301/",
            "allow       a, b",
            "warning     --no-origin-check: Host/Origin checking is off (no DNS rebinding defense)",
            "git-pull    checks main right after startup and every 60 seconds, rebuilding the PDF on a new commit",
            "warning     pdf.js is missing (None) - the viewer falls back to PNG"])


class Parser(unittest.TestCase):
    """serve_parser(): the command line takes the server's description, version and --float-envs default."""

    def test_given_values_reach_help_version_and_defaults(self):
        """What the composition root passes is what `limn serve --help` / --version show and --float-envs defaults to."""
        ap = args.serve_parser("Limn test line", "limn 9.9", "figure,table")
        self.assertEqual(ap.description, "Limn test line")
        self.assertEqual(ap.parse_args(["--manuscript", "m"]).float_envs, "figure,table")
        self.assertIn("(%d characters or fewer)" % startup.LABEL_MAX, " ".join(ap.format_help().split()))
        with mock.patch.dict(os.environ, {"LIMN_AGENT_TOKEN_FILE": "/x/t.token"}):
            self.assertEqual(args.serve_parser("d", "v", "e").parse_args(["--manuscript", "m"]).agent_token_file,
                             "/x/t.token")


# ---------------------------------------------------------------- instance label (§Running multiple manuscript instances at once)

class RepoNameFromUrl(unittest.TestCase):
    def test_https_url(self):
        self.assertEqual(startup.repo_name_from_url("https://github.com/example-lab/paper-a.git"),
                         "paper-a")

    def test_ssh_url_with_path(self):
        self.assertEqual(startup.repo_name_from_url("git@github.com:example-lab/paper-a.git"),
                         "paper-a")

    def test_scp_style_without_slash(self):
        self.assertEqual(startup.repo_name_from_url("git@host:reponame.git"), "reponame")

    def test_no_git_suffix(self):
        self.assertEqual(startup.repo_name_from_url("https://github.com/org/name"), "name")

    def test_trailing_slash(self):
        self.assertEqual(startup.repo_name_from_url("https://github.com/org/name/"), "name")


class DefaultLabel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_uses_repo_name_when_remote_given(self):
        src = self.root / "some-checkout-dir"
        src.mkdir()
        self.assertEqual(startup.default_label(src, "git@github.com:example-lab/paper-a.git"),
                         "paper-a")

    def test_falls_back_to_folder_name_without_remote(self):
        src = self.root / "my-manuscript"
        src.mkdir()
        self.assertEqual(startup.default_label(src, None), "my-manuscript")

    def test_git_remote_url_none_when_not_a_repo(self):
        if not shutil.which("git"):
            self.skipTest("git not available")
        src = self.root / "plain-dir"
        src.mkdir()
        self.assertIsNone(startup.git_remote_url(src))

    def test_git_remote_url_reads_origin(self):
        if not shutil.which("git"):
            self.skipTest("git not available")
        src = self.root / "repo"
        src.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=src, check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@example.com:org/paper-x.git"],
                       cwd=src, check=True)
        self.assertEqual(startup.git_remote_url(src), "git@example.com:org/paper-x.git")
        self.assertEqual(startup.default_label(src, startup.git_remote_url(src)), "paper-x")


class LabelValidation(unittest.TestCase):
    def test_strips_and_collapses_whitespace(self):
        self.assertEqual(startup.clean_label("  A-DEMO  "), "A-DEMO")
        self.assertEqual(startup.clean_label("A\nDEMO"), "A DEMO")

    def test_empty_becomes_default_placeholder(self):
        self.assertEqual(startup.clean_label(""), "원고")
        self.assertEqual(startup.clean_label(None), "원고")

    def test_over_length_is_refused(self):
        """An explicit --label over LABEL_MAX refuses to start (main() prints the message and exits)."""
        refused = startup.clean_label("x" * (startup.LABEL_MAX + 1))
        self.assertIsInstance(refused, StartupRefused)
        self.assertTrue(refused.message.startswith("--label must be %d characters or fewer" % startup.LABEL_MAX))

    def test_exactly_max_length_ok(self):
        v = "x" * startup.LABEL_MAX
        self.assertEqual(startup.clean_label(v), v)


class AccentValidation(unittest.TestCase):
    def test_valid_format(self):
        self.assertTrue(startup.valid_accent("#1d4ed8"))
        self.assertTrue(startup.valid_accent("#AABBCC"))

    def test_invalid_formats_rejected(self):
        for bad in ("1d4ed8", "#1d4ed", "#1d4ed8ff", "#gggggg", "red", "", None):
            self.assertFalse(startup.valid_accent(bad))

    def test_pick_accent_is_deterministic_for_same_label(self):
        a = startup.pick_accent("A-DEMO")
        b = startup.pick_accent("A-DEMO")
        self.assertEqual(a, b)
        self.assertIn(a, config.ACCENT_PALETTE)

    def test_pick_accent_differs_for_different_labels_usually(self):
        # the palette has 8 colors so a 100% guarantee isn't possible, but if a handful of different
        # labels all cluster onto the same color, the hash distribution is broken.
        colors = {startup.pick_accent(lbl) for lbl in ("A-DEMO", "paper-b", "grant-2026", "thesis")}
        self.assertGreater(len(colors), 1)


class DocArgs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ms = Path(self.tmp.name) / "repo"
        (self.ms / "manuscript" / "2nd").mkdir(parents=True)
        (self.ms / "manuscript" / "2nd" / "m.tex").write_text(FIXTURE_TEX, encoding="utf-8")
        (self.ms / "sub" / "rr").mkdir(parents=True)
        (self.ms / "sub" / "rr" / "rr.tex").write_text(FIXTURE_TEX, encoding="utf-8")
        (self.ms / "sub" / "review.pdf").write_bytes(MINI_PDF)
        (self.ms / "notes.txt").write_text("x")
        (Path(self.tmp.name) / "outside.tex").write_text(FIXTURE_TEX)

    def tearDown(self):
        self.tmp.cleanup()

    def test_simple_tex_uses_its_folder_as_build_root(self):
        d = startup.parse_doc_arg("rr=답변서:sub/rr/rr.tex", self.ms)
        self.assertEqual((d["key"], d["name"], d["kind"]), ("rr", "답변서", "tex"))
        self.assertEqual(d["src"], (self.ms / "sub" / "rr").resolve())
        self.assertEqual(d["main"], (self.ms / "sub" / "rr" / "rr.tex").resolve())

    def test_extended_form_sets_build_root_separately(self):
        d = startup.parse_doc_arg("ms=본문:manuscript::2nd/m.tex", self.ms)
        self.assertEqual(d["src"], (self.ms / "manuscript").resolve())
        self.assertEqual(d["main"], (self.ms / "manuscript" / "2nd" / "m.tex").resolve())
        doc = startup.make_docs(["ms=본문:manuscript::2nd/m.tex"], self.ms, ps.C)[0]
        self.assertEqual(doc.main_rel, Path("2nd/m.tex"))
        ps.C.state = Path(self.tmp.name) / "st"
        # latexmk runs from the folder that holds the main file
        self.assertEqual(doc.out, ps.C.state / "docs" / "ms" / "build" / "2nd")

    def test_pdf_is_view_only(self):
        d = startup.parse_doc_arg("rv=리뷰어 코멘트:sub/review.pdf", self.ms)
        self.assertEqual(d["kind"], "pdf")
        self.assertEqual(d["name"], "리뷰어 코멘트")                  # a space inside the name is kept as-is

    def test_absolute_path_inside_manuscript_is_accepted(self):
        d = startup.parse_doc_arg("rr=답변서:%s" % (self.ms / "sub" / "rr" / "rr.tex"), self.ms)
        self.assertEqual(d["kind"], "tex")

    def test_rejects_bad_specs(self):
        bad = ["rr답변서:sub/rr/rr.tex",               # no '='
               "RR=답변서:sub/rr/rr.tex",              # uppercase key
               "a" * 25 + "=x:sub/rr/rr.tex",          # 25-char key
               "rr=답변서",                            # no ':'
               "rr=:sub/rr/rr.tex",                    # empty name
               "rr=" + "가" * 41 + ":sub/rr/rr.tex",   # 41-char name
               "rr=답변서:",                           # empty path
               "rr=답변서:../outside.tex",             # outside --manuscript
               "rr=답변서:sub/rr/none.tex",            # nonexistent file
               "rr=답변서:notes.txt",                  # extension
               "rv=코멘트:sub::review.pdf",            # '::' is LaTeX-only
               "ms=본문:manuscript::../outside.tex",   # main is outside the build root
               "ms=본문:manuscript::2nd/m.tex::x",     # '::' twice
               "ms=본문:nope::2nd/m.tex"]              # no build root
        for spec in bad:
            with self.assertRaises(ValueError, msg=spec):
                startup.parse_doc_arg(spec, self.ms)

    def test_make_docs_rejects_duplicate_keys_and_marks_main_root(self):
        with self.assertRaises(ValueError):
            startup.make_docs(["rr=a:sub/rr/rr.tex", "rr=b:sub/rr/rr.tex"], self.ms, ps.C)
        docs = startup.make_docs(["main=본문:manuscript/2nd/m.tex", "rr=답변서:sub/rr/rr.tex", "rv=코멘트:sub/review.pdf"], self.ms, ps.C)
        # only the LaTeX document keyed main is placed at the state-folder root
        self.assertEqual([d.root for d in docs], [True, False, False])
        self.assertEqual([d.kind for d in docs], ["tex", "tex", "pdf"])
        with self.assertRaises(ValueError):
            startup.make_docs(["d%d=x:sub/rr/rr.tex" % i for i in range(DOCS_MAX + 1)], self.ms, ps.C)




class Version(unittest.TestCase):
    """app_version: the package version read from limn/__init__.py beside this module."""

    def test_matches_the_package_version(self):
        """The same string the package declares, never the unknown placeholder in a normal install."""
        import limn
        self.assertEqual(startup.app_version(), limn.__version__)


if __name__ == "__main__":
    unittest.main()
