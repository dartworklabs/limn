"""The `limn` command surface: version, serve pass-through and help."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def limn(*args, **kw):
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run([sys.executable, "-m", "limn", *args], capture_output=True, text=True,
                          timeout=60, env=env, **kw, check=False)


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
    code = ("import importlib.util as u; s=u.spec_from_file_location('s', %r); m=u.module_from_spec(s); "
            "s.loader.exec_module(m); print(m.app_version())" % str(SRC / "limn" / "server.py"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
    assert r.stdout.strip() == package_version()


def test_pyproject_takes_version_from_package():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'path = "src/limn/__init__.py"' in text
    assert 'limn = "limn.cli:main"' in text
