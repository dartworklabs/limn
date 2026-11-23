"""The `limn` command surface: version, serve pass-through, help, and isolated token/member commands."""

import json
import os
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"


def limn(*args, **kw):
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run(
        [sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=60, env=env, **kw, check=False
    )


def package_version():
    """The version installed for users of the command, independent of source layout."""
    return distribution("dartwork-limn").version


def test_version_command_prints_package_version():
    r = limn("version")
    assert r.returncode == 0
    assert r.stdout.strip() == "limn %s" % package_version()


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_flags(flag):
    assert limn(flag).stdout.strip() == "limn %s" % package_version()


def test_serve_version_flag_matches():
    r = limn("serve", "--version")
    assert r.returncode == 0
    assert r.stdout.strip() == "limn %s" % package_version()


def test_serve_help_lists_server_options():
    r = limn("serve", "--help")
    assert r.returncode == 0
    for opt in ("--manuscript", "--doc", "--port", "--state-dir", "--label", "--pdfjs-dir", "--version"):
        assert opt in r.stdout
    assert r.stdout.startswith("usage: limn serve")


def test_help_shows_serve_and_instance_commands():
    r = limn("help")
    assert r.returncode == 0
    for word in ("limn serve", "limn version", "limn migrate", "limn add", "limn update", "limn status"):
        assert word in r.stdout


def test_server_reports_the_same_version_when_run_by_path():
    code = (
        "import importlib.util as u; s=u.spec_from_file_location('s', %r); m=u.module_from_spec(s); "
        "s.loader.exec_module(m); print(m.app_version())" % str(SRC / "limn" / "server.py")
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
    assert r.stdout.strip() == package_version()


def test_installed_command_prints_package_version():
    """The installed command starts and reports its package version."""
    command = Path(sys.executable).with_name("limn")
    result = subprocess.run([str(command), "version"], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0
    assert result.stdout.strip() == "limn %s" % package_version()


# Every `limn token` / `limn member` subcommand, run in one fresh interpreter in which importing limn.server fails (the
# None entry in sys.modules makes `import limn.server` raise ImportError, as a broken server or viewer part would). The
# script prints each exit status, then whether the server or the viewer assembly got imported.
NO_SERVER_SCRIPT = """
import json, sys
sys.modules["limn.server"] = None
from limn import cli
state = sys.argv[1]
calls = [
    ["token", "create", "--state-dir", state, "--name", "ci"],
    ["token", "list", "--state-dir", state],
    ["token", "path", "paper"],
    ["token", "revoke", "--state-dir", state, "ci"],
    ["member", "add", "--state-dir", state, "alice@example.com"],
    ["member", "list", "--state-dir", state],
    ["member", "role", "--state-dir", state, "alice@example.com", "viewer"],
    ["member", "remove", "--state-dir", state, "alice@example.com"],
]
codes = [cli.main(c) for c in calls]
print(json.dumps({"codes": codes, "loaded": sorted(m for m in sys.modules if m in ("limn.server", "limn.viewer.assemble") and sys.modules[m] is not None)}))
"""


def test_token_and_member_commands_run_without_the_server(tmp_path):
    """`limn token` and `limn member` never import limn.server: with the server unimportable every subcommand still
    exits 0, neither the server nor the viewer assembly it runs at import is loaded, and each change is audited."""
    env = dict(os.environ, PYTHONPATH=str(SRC), LIMN_CONFIG_DIR=str(tmp_path / "cfg"))
    r = subprocess.run(
        [sys.executable, "-c", NO_SERVER_SCRIPT, str(tmp_path / "state")],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    result = json.loads(r.stdout.strip().splitlines()[-1])
    assert result == {"codes": [0] * 8, "loaded": []}
    actions = [json.loads(line)["action"] for line in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]
    assert actions == ["token_created", "token_revoked", "member_added", "member_role", "member_removed"]


class TestMemberCliLastOwner:
    """`limn member remove|role` refuse to leave an instance without an owner (owner's decision, 2026-11-22)."""

    @staticmethod
    def _members(tmp_path, *pairs):
        state = str(tmp_path / "state")
        for login, role in pairs:
            assert limn("member", "add", "--state-dir", state, login, "--role", role).returncode == 0
        return state

    @staticmethod
    def _roles(state):
        rows = json.loads((Path(state) / "people.json").read_text(encoding="utf-8"))["people"]
        return {x["login"]: x["role"] for x in rows}

    def test_member_remove_refuses_last_owner(self, tmp_path):
        state = self._members(tmp_path, ("a@example.com", "owner"), ("b@example.com", "editor"))
        r = limn("member", "remove", "--state-dir", state, "a@example.com")
        assert r.returncode == 1
        assert r.stderr.startswith("limn: ") and len(r.stderr.strip().splitlines()) == 1 and "a@example.com" in r.stderr
        assert self._roles(state) == {"a@example.com": "owner", "b@example.com": "editor"}

    def test_member_role_refuses_demoting_last_owner(self, tmp_path):
        state = self._members(tmp_path, ("a@example.com", "owner"))
        r = limn("member", "role", "--state-dir", state, "a@example.com", "viewer")
        assert r.returncode == 1
        assert r.stderr.startswith("limn: ") and len(r.stderr.strip().splitlines()) == 1
        assert self._roles(state) == {"a@example.com": "owner"}

    def test_add_new_owner_then_remove_old_works(self, tmp_path):
        state = self._members(tmp_path, ("a@example.com", "owner"))
        assert limn("member", "add", "--state-dir", state, "b@example.com", "--role", "owner").returncode == 0
        assert limn("member", "remove", "--state-dir", state, "a@example.com").returncode == 0
        assert self._roles(state) == {"b@example.com": "owner"}

    def test_two_owners_allow_demoting_one(self, tmp_path):
        state = self._members(tmp_path, ("a@example.com", "owner"), ("b@example.com", "owner"))
        assert limn("member", "role", "--state-dir", state, "a@example.com", "editor").returncode == 0
