"""The `limn` command surface: version, serve pass-through, help, and what `limn token` / `limn member` import."""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def limn(*args, **kw):
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run(
        [sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=60, env=env, **kw, check=False
    )


def package_version():
    text = (SRC / "limn" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


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


def test_pyproject_takes_version_from_package():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'path = "src/limn/__init__.py"' in text
    assert 'limn = "limn.cli:main"' in text


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


# ---------------------------------------------------------------- `limn update`'s default source (v0.2.1 QA)


class UpdateSource(unittest.TestCase):
    def test_default_is_https_everywhere(self):
        sh = (SRC / "limn" / "instances.sh").read_text(encoding="utf-8")
        self.assertIn('REPO="${LIMN_REPO:-git+https://github.com/dartworklabs/limn}"', sh)
        text = (ROOT / "docs" / "handbook" / "instances.md").read_text(encoding="utf-8")
        row = next(ln for ln in text.splitlines() if ln.startswith("| `LIMN_REPO`"))
        self.assertIn("git+https://github.com/dartworklabs/limn", row)
        self.assertIn("0.1.0의 기본값은 `git+ssh://", text)  # the note on the v0.1.0 ssh default
