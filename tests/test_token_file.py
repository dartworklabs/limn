"""Agent token files (docs/adr/0007-agent-token-file.md): agents on the serving machine send the token the owner saved
in ~/.config/limn/<instance>.token, so an instance can turn off the headerless loopback agent (AGENT_LOOPBACK=0).

Pinned here:
- the CLI: `limn token create <instance> --save` (0600 file, 0700 folder, token not printed), `--force`, `--print`,
  `limn token path`, `limn token revoke` removing the file that held the revoked token, and the refusals (an existing
  file, a git work tree, no instance name, a failed write that must not leave a live token behind);
- the server: the pins.md clause that names the file once it exists (never for a remote reader, never the token), the
  401 a headerless local request gets with the loopback agent off, and --agent-token-file / LIMN_AGENT_TOKEN_FILE;
- the instance manager against a real server with the loopback agent on and off: `limn status` and `limn start`
  send the token file (on curl's stdin, never its command line), explain a 401, and refuse unsafe token files.

Run: uv run pytest -q tests/test_token_file.py
"""
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_access import AccessBase, get
from test_server import ps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TS_HOST = "box.tail1234.ts.net"


def run_limn(*args: str, env: dict, timeout: int = 60) -> subprocess.CompletedProcess:
    """`limn <args>` from this checkout with the given environment (a sandboxed config and data root)."""
    e = dict(env, PYTHONPATH=str(SRC))
    return subprocess.run([sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=timeout,
                          env=e, check=False)


class Sandbox:
    """A throwaway config folder, data root and home for one test: instance `paper` with its state dir."""

    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.cfg = self.home / ".config" / "limn"
        self.data = root / "data"
        self.state = self.data / "paper"
        self.ms = root / "ms"
        for d in (self.cfg, self.state, self.ms):
            d.mkdir(parents=True)
        (self.cfg / "paper.env").write_text("MANUSCRIPT=%s\nSTATE_DIR=%s\n" % (self.ms, self.state), encoding="utf-8")
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
                        LIMN_CONFIG_DIR=str(self.cfg), LIMN_DATA_ROOT=str(self.data))
        self.env.pop("LIMN_SOURCE_DIR", None)
        self.token_file = self.cfg / "paper.token"

    def tokens(self) -> list:
        """The instance's tokens.json entries."""
        f = self.state / "tokens.json"
        return json.loads(f.read_text(encoding="utf-8"))["tokens"] if f.exists() else []


class SandboxTest(unittest.TestCase):
    """Base for the CLI tests: a fresh Sandbox per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.box = Sandbox(Path(self.tmp.name))

    def limn(self, *args: str) -> subprocess.CompletedProcess:
        return run_limn(*args, env=self.box.env)


# ---------------------------------------------------------------- the CLI

class SaveTokenFile(SandboxTest):
    """`limn token create <instance> --save` writes the token where agents on this machine read it."""

    def test_save_writes_a_0600_file_in_a_new_0700_folder_and_prints_no_token(self):
        """The folder is created 0700, the file 0600 with one token line; stdout stays empty (no token on screen)."""
        shutil.rmtree(self.box.cfg)
        self.box.cfg.mkdir(parents=True, mode=0o755)
        (self.box.cfg / "paper.env").write_text("MANUSCRIPT=%s\nSTATE_DIR=%s\n" % (self.box.ms, self.box.state), encoding="utf-8")
        nested = self.box.root / "fresh" / "limn"
        env = dict(self.box.env, LIMN_CONFIG_DIR=str(nested), LIMN_SOURCE_DIR=str(self.box.cfg))
        r = run_limn("token", "create", "paper", "--name", "local", "--save", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")
        f = nested / "paper.token"
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(nested.stat().st_mode), 0o700)
        token = f.read_text(encoding="utf-8")
        self.assertRegex(token, r"^limn_[A-Za-z0-9_-]+\n$")
        self.assertNotIn(token.strip(), r.stderr)
        self.assertIn(str(f), r.stderr)
        self.assertEqual([t["hash"] for t in self.box.tokens()], [ps.token_hash(token.strip())])
        self.assertFalse((self.box.cfg / "paper.token").exists())         # never next to the source copy

    def test_print_also_prints_the_saved_token(self):
        """--print is the only way --save shows the token, and it is the same one the file holds."""
        r = self.limn("token", "create", "paper", "--save", "--print")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), self.box.token_file.read_text(encoding="utf-8").strip())

    def test_existing_file_is_refused_and_no_token_is_created(self):
        """Without --force an existing file stays untouched, and the refusal comes before any token exists."""
        self.box.token_file.write_text("keep me\n", encoding="utf-8")
        r = self.limn("token", "create", "paper", "--save")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already exists", r.stderr)
        self.assertIn("--force", r.stderr)
        self.assertEqual(self.box.token_file.read_text(encoding="utf-8"), "keep me\n")
        self.assertEqual(self.box.tokens(), [])

    def test_force_replaces_the_file_and_names_the_old_token_still_valid(self):
        """--force swaps the file atomically (still 0600) and says the replaced token is still valid until revoked."""
        first = self.limn("token", "create", "paper", "--name", "one", "--save")
        self.assertEqual(first.returncode, 0, first.stderr)
        old = self.box.token_file.read_text(encoding="utf-8")
        r = self.limn("token", "create", "paper", "--name", "two", "--save", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        new = self.box.token_file.read_text(encoding="utf-8")
        self.assertNotEqual(new, old)
        self.assertEqual(stat.S_IMODE(self.box.token_file.stat().st_mode), 0o600)
        self.assertIn("still valid", r.stderr)
        self.assertIn("name one", r.stderr)
        self.assertEqual(sorted(t["name"] for t in self.box.tokens()), ["one", "two"])

    def test_save_is_refused_inside_a_git_work_tree_that_does_not_ignore_it(self):
        """A token file never lands in a repository: refused (even with --force) until the repository ignores it."""
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        subprocess.run(["git", "init", "-q", str(self.box.home)], check=True, capture_output=True)
        for force in ((), ("--force",)):
            r = self.limn("token", "create", "paper", "--save", *force)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("git work tree", r.stderr)
            self.assertFalse(self.box.token_file.exists())
        self.assertEqual(self.box.tokens(), [])
        (self.box.home / ".gitignore").write_text("*.token\n", encoding="utf-8")
        r = self.limn("token", "create", "paper", "--save")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.box.token_file.exists())

    def test_save_needs_an_instance_name(self):
        """A plain `limn serve` state dir has no instance, so no token file: --save with --state-dir is refused."""
        r = self.limn("token", "create", "--state-dir", str(self.box.root / "plain"), "--save")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--save needs an instance name", r.stderr)
        self.assertFalse((self.box.root / "plain" / "tokens.json").exists())

    def test_force_and_print_without_save_are_refused(self):
        """--force and --print only mean something with --save; alone they are an error, not silently ignored."""
        for flag in ("--force", "--print"):
            r = self.limn("token", "create", "paper", flag)
            self.assertNotEqual(r.returncode, 0, flag)
            self.assertIn("only go with --save", r.stderr)
        self.assertEqual(self.box.tokens(), [])

    def test_failed_write_revokes_the_new_token(self):
        """When the file cannot be written the token just created is revoked again - no live token nobody holds."""
        if os.geteuid() == 0:
            self.skipTest("root ignores the folder permission this test relies on")
        self.box.cfg.chmod(0o500)
        self.addCleanup(self.box.cfg.chmod, 0o700)
        r = self.limn("token", "create", "paper", "--save")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("revoked again", r.stderr)
        self.assertEqual(self.box.tokens(), [])
        self.assertFalse(self.box.token_file.exists())

    def test_path_prints_the_convention_and_reads_nothing(self):
        """`limn token path` prints <config dir>/<instance>.token, whether or not the file or the instance exists."""
        r = self.limn("token", "path", "paper")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, str(self.box.token_file)))
        r = self.limn("token", "path", "no-such-instance")
        self.assertEqual(r.stdout.strip(), str(self.box.cfg / "no-such-instance.token"))
        r = self.limn("token", "path", "Bad Name")
        self.assertNotEqual(r.returncode, 0)

    def test_list_names_the_token_the_file_holds(self):
        """`limn token list` says which token the token file holds, by id and name only."""
        self.limn("token", "create", "paper", "--name", "ci")
        self.limn("token", "create", "paper", "--name", "local", "--save")
        r = self.limn("token", "list", "paper")
        self.assertIn("holds", r.stdout)
        self.assertIn("(name local)", r.stdout)
        self.assertNotIn(self.box.token_file.read_text(encoding="utf-8").strip(), r.stdout)


class RevokeTokenFile(SandboxTest):
    """`limn token revoke` removes the token file that held the revoked token, and only that one."""

    def test_revoking_the_saved_token_removes_its_file(self):
        """An agent would only get 401 from a revoked token, so the file goes with it."""
        self.limn("token", "create", "paper", "--name", "local", "--save")
        r = self.limn("token", "revoke", "paper", "local")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("removed %s" % self.box.token_file, r.stdout)
        self.assertFalse(self.box.token_file.exists())
        self.assertEqual(self.box.tokens(), [])

    def test_revoking_another_token_keeps_the_file(self):
        """A file holding a different (still valid) token is kept, and the output says so."""
        self.limn("token", "create", "paper", "--name", "ci")
        self.limn("token", "create", "paper", "--name", "local", "--save")
        r = self.limn("token", "revoke", "paper", "ci")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kept %s" % self.box.token_file, r.stdout)
        self.assertTrue(self.box.token_file.exists())


# ---------------------------------------------------------------- the server

class ServerTokenFile(AccessBase):
    """The server names the token file (never its content) once it exists, and only to a reader on this machine."""

    def setUp(self):
        super().setUp()
        self.cfg = Path(self.tmp.name) / "cfg"
        self.cfg.mkdir()
        ps.C.agent_token_file = self.cfg / "paper.token"

    def token_line(self, md: str) -> str:
        return next(ln for ln in md.splitlines() if ln.startswith(ps.TOKEN_GUIDANCE))

    def test_pins_md_is_unchanged_until_the_token_file_exists(self):
        """No file (or no file configured): the agent-auth line is exactly the v0.2 TOKEN_GUIDANCE."""
        self.add()
        self.assertEqual(self.token_line(ps.C.pins_md.read_text(encoding="utf-8")), ps.TOKEN_GUIDANCE)
        ps.C.agent_token_file = None
        self.add()
        self.assertEqual(self.token_line(ps.C.pins_md.read_text(encoding="utf-8")), ps.TOKEN_GUIDANCE)

    def test_pins_md_adds_the_token_file_clause_once_the_file_exists(self):
        """The clause is appended to the old line: the curl form reading the file, and no token anywhere in pins.md."""
        secret = "limn_" + "s" * 43
        ps.C.agent_token_file.write_text(secret + "\n", encoding="utf-8")
        self.add()
        md = ps.C.pins_md.read_text(encoding="utf-8")
        line = self.token_line(md)
        self.assertTrue(line.startswith(ps.TOKEN_GUIDANCE + " · "))
        self.assertIn('Authorization: Bearer $(cat %s)' % ps.C.agent_token_file, line)
        self.assertNotIn(secret, md)
        self.assertEqual(len([ln for ln in md.splitlines() if ln.startswith(ps.TOKEN_GUIDANCE)]), 1)

    def test_the_server_never_reads_the_token_file(self):
        """An unreadable (mode 000) token file still counts as present: the server only stats it."""
        if os.geteuid() == 0:
            self.skipTest("root reads mode-000 files, so this cannot show that nothing was read")
        ps.C.agent_token_file.write_text("limn_x\n", encoding="utf-8")
        ps.C.agent_token_file.chmod(0o000)                                # removing it later needs no read either
        self.add()
        self.assertIn("$(cat ", self.token_line(ps.C.pins_md.read_text(encoding="utf-8")))

    def test_remote_pins_md_never_names_the_token_file(self):
        """GET /pins.md through the tailnet renders for a reader who cannot reach this machine's files."""
        ps.C.agent_token_file.write_text("limn_x\n", encoding="utf-8")
        self.add()
        code, md = get(ps, "/pins.md", {"Host": TS_HOST + ":18004", "X-Forwarded-For": "100.64.0.9",
                                        "Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Alice Kim"})
        self.assertEqual(code, 200)
        self.assertEqual(self.token_line(md), ps.TOKEN_GUIDANCE)
        code, md = get(ps, "/pins.md")                                    # the local reader does get it
        self.assertIn("$(cat ", self.token_line(md))

    def test_headerless_local_request_gets_401_naming_the_token_file_when_the_loopback_agent_is_off(self):
        """AGENT_LOOPBACK=0: 401 whose text starts with the v0.2 message, then the file and how to create it."""
        ps.C.agent_loopback = False
        code, d = self.call("GET", "/api/pins")
        self.assertEqual(code, 401)
        self.assertEqual(self.last_headers.get("www-authenticate"), 'Bearer realm="limn"')
        self.assertTrue(d["error"].startswith(ps.UNAUTHENTICATED))
        self.assertIn("$(cat %s)" % ps.C.agent_token_file, d["error"])
        self.assertIn("limn token create paper --save", d["error"])
        ps.C.agent_token_file.write_text("limn_x\n", encoding="utf-8")
        code, d = self.call("GET", "/api/pins")
        self.assertEqual(code, 401)
        self.assertNotIn("--save", d["error"])                           # the file exists: no need to create it

    def test_proxied_headerless_request_gets_no_local_file_hint(self):
        """Through a proxy the request is not from this machine: the plain 401 text, no local path."""
        ps.C.agent_loopback = False
        code, d = self.call("GET", "/api/pins", headers={"Host": "127.0.0.1:18999", "X-Forwarded-For": "100.64.0.9"})
        self.assertEqual((code, d["error"]), (401, ps.UNAUTHENTICATED))

    def test_revoked_token_from_the_file_is_401(self):
        """A token read from a token file is an ordinary token: revoked means 401, never a fallback to another identity."""
        ps.C.agent_loopback = False
        entry, tok = ps.token_create(ps.C.state, "local")
        self.assertEqual(self.call("GET", "/api/pins", token=tok)[0], 200)
        ps.token_revoke(ps.C.state, entry["id"])
        code, d = self.call("GET", "/api/pins", token=tok)
        self.assertEqual(code, 401)
        self.assertIn("폐기", d["error"])

    def test_agent_token_file_flag_defaults_to_the_environment(self):
        """limn run passes the path in LIMN_AGENT_TOKEN_FILE (argv stays as in v0.1); --agent-token-file overrides it."""
        env = dict(os.environ, LIMN_AGENT_TOKEN_FILE="/x/paper.token")
        code = ("import sys; sys.path.insert(0, %r); from limn import server as s; "
                "a = s.build_arg_parser().parse_args(['--manuscript', 'm'] + sys.argv[1:]); print(a.agent_token_file)"
                % str(SRC))

        def parsed(*args: str) -> str:
            return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, env=env,
                                  timeout=60, check=False).stdout.strip()
        self.assertEqual(parsed(), "/x/paper.token")
        self.assertEqual(parsed("--agent-token-file", "/y/other.token"), "/y/other.token")

    def test_shell_path_uses_a_tilde_only_for_a_plain_path_under_home(self):
        """The shown path must work pasted into a shell: ~/rest when safe to leave unquoted, else quoted absolute."""
        home = Path("/home/u")
        self.assertEqual(ps.shell_path(Path("/home/u/.config/limn/p.token"), home), "~/.config/limn/p.token")
        self.assertEqual(ps.shell_path(Path("/srv/limn/p.token"), home), "/srv/limn/p.token")
        self.assertEqual(ps.shell_path(Path("/home/u/my dir/p.token"), home), "'/home/u/my dir/p.token'")
        self.assertEqual(ps.shell_path(Path("/home/u/p.token"), None), "/home/u/p.token")


# ---------------------------------------------------------------- the instance manager against a real server

def free_port() -> int:
    """A loopback port nothing listens on right now."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


MINIMAL_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
               b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


@unittest.skipUnless(shutil.which("bash") and shutil.which("curl"), "needs bash and curl")
class InstanceManagerProbes(SandboxTest):
    """`limn status` / `limn start` ask a real server (view-only PDF document, no TeX needed) the way agents must once
    AGENT_LOOPBACK=0: with the token file, on curl's stdin. systemctl and tailscale are stubs; nothing on the host
    changes."""

    def setUp(self):
        super().setUp()
        (self.box.ms / "paper.pdf").write_bytes(MINIMAL_PDF)
        self.port = free_port()
        stubs = self.box.root / "bin"
        stubs.mkdir()
        self.curl_log = self.box.root / "curl.log"
        real_curl = shutil.which("curl")
        (stubs / "systemctl").write_text('#!/usr/bin/env bash\ncase " $* " in *" is-active "*) echo active;; '
                                         '*" is-enabled "*) echo enabled;; *" show "*) echo 1;; esac\nexit 0\n')
        (stubs / "tailscale").write_text("#!/usr/bin/env bash\nexit 1\n")
        (stubs / "curl").write_text('#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> %s\nexec %s "$@"\n'
                                    % (self.curl_log, real_curl))
        for f in stubs.iterdir():
            f.chmod(0o755)
        self.box.env.update(PATH="%s:%s" % (stubs, os.environ.get("PATH", "")), XDG_RUNTIME_DIR=str(self.box.root),
                            LIMN_USER_UNIT_DIR=str(self.box.root / "units"), LIMN_WAIT="20",
                            LIMN_LEDGER=str(self.box.root / "ledger.txt"))
        (self.box.cfg / "paper.env").write_text(
            "MANUSCRIPT=%s\nDOCS=main=Paper:paper.pdf\nPORT=%d\nTS_PORT=%d\nSTATE_DIR=%s\nEXTRA_ARGS=--no-build\n"
            % (self.box.ms, self.port, self.port - 100, self.box.state), encoding="utf-8")

    def serve(self, loopback_agent: bool) -> None:
        """Start the real server for this test's instance; stopped at cleanup."""
        args = [sys.executable, str(SRC / "limn" / "server.py"), "--manuscript", str(self.box.ms), "--doc",
                "main=Paper:paper.pdf", "--port", str(self.port), "--state-dir", str(self.box.state), "--no-build"]
        if not loopback_agent:
            args.append("--no-agent-loopback")
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.box.env)
        self.addCleanup(lambda: (proc.terminate(), proc.wait(10)))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            if proc.poll() is not None:
                self.fail("the server exited with %s" % proc.returncode)
            time.sleep(0.1)
        self.fail("the server did not listen within 30 s")

    def status_local_line(self) -> tuple:
        r = self.limn("status", "paper")
        self.assertEqual(r.returncode, 0, r.stderr)
        return next(ln for ln in r.stdout.splitlines() if ln.strip().startswith("local")), r

    def test_status_is_200_with_the_loopback_agent_on_and_no_token_file(self):
        """The v0.1 path still works: a headerless probe answers 200."""
        self.serve(loopback_agent=True)
        line, r = self.status_local_line()
        self.assertTrue(line.endswith("→ 200"), line)
        self.assertIn("token file   none", r.stdout)

    def test_status_sends_the_token_file_when_the_loopback_agent_is_off(self):
        """AGENT_LOOPBACK=0 plus a saved token: 200, and the token never appears on curl's command line."""
        self.serve(loopback_agent=False)
        self.assertEqual(self.limn("token", "create", "paper", "--save").returncode, 0)
        line, r = self.status_local_line()
        self.assertTrue(line.endswith("→ 200"), (line, r.stderr))
        token = self.box.token_file.read_text(encoding="utf-8").strip()
        log = self.curl_log.read_text(encoding="utf-8")
        self.assertIn("-H @-", log)
        self.assertNotIn(token, log)

    def test_status_explains_a_401_without_a_token_file(self):
        """AGENT_LOOPBACK=0 and no token file: the 401 is reported with the command that fixes it."""
        self.serve(loopback_agent=False)
        line, _ = self.status_local_line()
        self.assertIn("→ 401", line)
        self.assertIn("limn token create paper --save", line)

    def test_status_reports_a_revoked_token_in_the_file(self):
        """A file whose token was revoked behind the CLI's back: 401, pointing at --force to replace it."""
        self.serve(loopback_agent=False)
        self.limn("token", "create", "paper", "--name", "local", "--save")
        ps.token_revoke(self.box.state, "local")                           # the file stays: not revoked through the CLI
        line, _ = self.status_local_line()
        self.assertIn("→ 401", line)
        self.assertIn("refused", line)
        self.assertIn("--force", line)

    def test_a_token_file_open_to_others_is_not_used(self):
        """Mode 0644 is refused with a warning naming chmod 600, and the probe goes without it (401)."""
        self.serve(loopback_agent=False)
        self.limn("token", "create", "paper", "--save")
        self.box.token_file.chmod(0o644)
        line, r = self.status_local_line()
        self.assertIn("→ 401", line)
        self.assertIn("chmod 600", r.stderr)
        self.assertNotIn(self.box.token_file.read_text(encoding="utf-8").strip(), self.curl_log.read_text(encoding="utf-8"))

    def test_a_symlinked_or_malformed_token_file_is_not_used(self):
        """A symlink (it could point into a repository) or a file that is not one token line is refused."""
        self.serve(loopback_agent=False)
        self.limn("token", "create", "paper", "--save")
        real = self.box.root / "elsewhere.token"
        self.box.token_file.rename(real)
        self.box.token_file.symlink_to(real)
        _, r = self.status_local_line()
        self.assertIn("not a regular file", r.stderr)
        self.box.token_file.unlink()
        self.box.token_file.write_text("limn_x\nX-Injected: 1\n", encoding="utf-8")
        self.box.token_file.chmod(0o600)
        _, r = self.status_local_line()
        self.assertIn("does not hold one", r.stderr)

    def test_start_stops_waiting_at_a_401(self):
        """`limn start` with AGENT_LOOPBACK=0 and no token: warns at once instead of waiting out LIMN_WAIT."""
        self.serve(loopback_agent=False)
        t0 = time.monotonic()
        r = self.limn("start", "paper", "--no-serve")
        self.assertLess(time.monotonic() - t0, 15)
        self.assertIn("answers 401", r.stderr)
        self.assertIn("limn token create paper --save", r.stderr)
        self.assertEqual(self.limn("token", "create", "paper", "--save").returncode, 0)
        r = self.limn("start", "paper", "--no-serve")
        self.assertIn("127.0.0.1:%d 200" % self.port, r.stdout)


if __name__ == "__main__":
    unittest.main()
