"""`limn migrate`: moving instances from the old pin-viewer install to Limn, in a sandbox.

This file and src/limn/migrate.py are the only places allowed to use the old name.
"""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

A_ENV = """# pin-viewer@paper-a — A-DEMO manuscript
# Not sourced by a shell. See the pin-viewer README.
LABEL=A-DEMO
MANUSCRIPT={ms}
DOCS="ms=본문:main.tex;hl=하이라이트:hl.tex"
PORT={port_a}
TS_PORT=18004
STATE_DIR={legacy_state}
GIT_PULL=1
EXTRA_ARGS=--no-build
"""
B_ENV = """# pin-viewer@paper-b — `pin-viewer add` wrote this on 2026-09-23.
LABEL=Long-DemoPaper1
MANUSCRIPT={ms}
MAIN=main.tex
PORT={port_b}
TS_PORT=18005
STATE_DIR={old_root}/paper-b
GIT_PULL=1
EXTRA_ARGS=--no-build
"""
C_ENV = """LABEL=paper-c
MANUSCRIPT={ms}
MAIN=main.tex
PORT=19107
TS_PORT=19007
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def box(tmp_path):
    home = tmp_path / "home"
    cfg, data = home / ".config", home / ".local" / "share"
    ms = tmp_path / "paper"
    ms.mkdir(parents=True)
    (ms / "main.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}\n")
    (ms / "hl.tex").write_text("\\documentclass{article}\\begin{document}h\\end{document}\n")
    old_cfg, old_root = cfg / "pin-viewer", data / "pin-viewer"
    old_cfg.mkdir(parents=True)
    legacy_state = data / "paper-a-pin"  # a state dir outside the old data root
    for d in (legacy_state, old_root / "paper-b", old_root / "paper-c", old_root / "app", old_root / "app.prev"):
        d.mkdir(parents=True)
    (legacy_state / "pins.jsonl").write_text('{"id": 1}\n')
    (old_root / "paper-b" / "pins.jsonl").write_text('{"id": 2}\n')
    # paper-a's config is a symlink into a separately versioned directory (as on the live host).
    repo = tmp_path / "configs-repo"
    repo.mkdir()
    fmt = dict(ms=ms, legacy_state=legacy_state, old_root=old_root, port_a=free_port(), port_b=free_port())
    (repo / "paper-a.env").write_text(A_ENV.format(**fmt))
    os.symlink(repo / "paper-a.env", old_cfg / "paper-a.env")
    (old_cfg / "paper-b.env").write_text(B_ENV.format(**fmt))
    (old_cfg / "paper-c.env").write_text(C_ENV.format(**fmt))
    # systemctl stub: every unit is inactive unless listed in STUB_ACTIVE.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "systemctl").write_text(
        '#!/usr/bin/env bash\nfor u in $STUB_ACTIVE; do [[ " $* " == *" $u "* ]] && '
        "{ echo active; exit 0; }; done\necho inactive; exit 3\n"
    )
    (bindir / "systemctl").chmod(0o755)
    env = dict(
        os.environ,
        HOME=str(home),
        XDG_CONFIG_HOME=str(cfg),
        XDG_DATA_HOME=str(data),
        PATH="%s:%s" % (bindir, os.environ.get("PATH", "")),
        PYTHONPATH=str(SRC),
        STUB_ACTIVE="",
    )
    env.pop("LIMN_CONFIG_DIR", None)
    env.pop("LIMN_DATA_ROOT", None)

    def run(*args, **extra):
        e = dict(env, **extra)
        return subprocess.run(
            [sys.executable, "-m", "limn", *args], capture_output=True, text=True, timeout=60, env=e, check=False
        )

    def snapshot():
        return {
            p: (p.read_bytes() if p.is_file() else None) for p in sorted(tmp_path.rglob("*")) if "bin" not in p.parts
        }

    return dict(
        run=run,
        cfg=cfg,
        data=data,
        old_cfg=old_cfg,
        old_root=old_root,
        legacy_state=legacy_state,
        repo=repo,
        env=env,
        snapshot=snapshot,
        tmp=tmp_path,
        fmt=fmt,
    )


def read_env(p):
    out = {}
    for ln in p.read_text().splitlines():
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.split("=", 1)
            out[k] = v.strip('"')
    return out


def test_dry_run_writes_nothing_and_shows_the_plan(box):
    before = box["snapshot"]()
    r = box["run"]("migrate", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert box["snapshot"]() == before
    assert not (box["cfg"] / "limn").exists()
    for n in ("paper-a", "paper-b", "paper-c"):
        assert "[%s]" % n in r.stdout
        assert "systemctl --user disable --now pin-viewer@%s.service" % n in r.stdout
        assert "limn start %s" % n in r.stdout
    assert "(dry-run)" in r.stdout


def test_migrate_copies_configs_and_keeps_every_value(box):
    r = box["run"]("migrate")
    assert r.returncode == 0, r.stdout + r.stderr
    new = box["cfg"] / "limn"
    for n in ("paper-a", "paper-b", "paper-c"):
        old_vals = read_env(box["old_cfg"] / ("%s.env" % n))
        new_vals = read_env(new / ("%s.env" % n))
        for k, v in old_vals.items():
            assert new_vals[k] == v, (n, k)
        text = (new / ("%s.env" % n)).read_text()
        # old-name comments dropped
        assert not [ln for ln in text.splitlines() if ln.startswith("#") and "pin-viewer" in ln]
        assert text.startswith("# limn@%s" % n)
        assert not (new / ("%s.env" % n)).is_symlink()
    # A missing STATE_DIR is pinned to the old default so pins do not vanish.
    assert read_env(new / "paper-c.env")["STATE_DIR"] == str(box["old_root"] / "paper-c")
    # Old files stay.
    assert (box["old_cfg"] / "paper-a.env").is_symlink()
    assert (box["repo"] / "paper-a.env").read_text().startswith("# pin-viewer@paper-a")
    assert "symlink" in r.stdout
    # The leftover old app copies are reported, not touched.
    assert str(box["old_root"] / "app") in r.stdout and (box["old_root"] / "app").is_dir()


def test_migrate_is_idempotent(box):
    assert box["run"]("migrate").returncode == 0
    before = box["snapshot"]()
    r = box["run"]("migrate")
    assert r.returncode == 0
    assert r.stdout.count("already migrated") == 3
    assert box["snapshot"]() == before


def test_conflicting_new_config_is_left_alone(box):
    new = box["cfg"] / "limn"
    new.mkdir(parents=True)
    (new / "paper-b.env").write_text("PORT=1\n")
    r = box["run"]("migrate", "paper-b")
    assert r.returncode == 1
    assert (new / "paper-b.env").read_text() == "PORT=1\n"
    assert "different values" in r.stdout


def test_unknown_name_fails(box):
    r = box["run"]("migrate", "nope")
    assert r.returncode == 1 and "nope" in r.stderr


def test_state_dirs_move_only_on_request_and_only_when_stopped(box):
    assert box["run"]("migrate").returncode == 0
    new_b = box["cfg"] / "limn" / "paper-b.env"
    target = box["data"] / "limn" / "paper-b"
    assert read_env(new_b)["STATE_DIR"] == str(box["old_root"] / "paper-b")
    # A running unit blocks the move.
    r = box["run"]("migrate", "--move-state", "paper-b", STUB_ACTIVE="pin-viewer@paper-b.service")
    assert r.returncode == 1 and "is running" in r.stdout
    assert not target.exists()
    # A busy local port blocks it too.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        cfg = box["old_cfg"] / "paper-b.env"
        text = cfg.read_text()
        cfg.write_text(text.replace("PORT=%d\n" % box["fmt"]["port_b"], "PORT=%d\n" % s.getsockname()[1]))
        (box["cfg"] / "limn" / "paper-b.env").unlink()
        assert box["run"]("migrate", "paper-b").returncode == 0
        r = box["run"]("migrate", "--move-state", "paper-b")
        assert r.returncode == 1 and "in use" in r.stdout
        cfg.write_text(text)
    (box["cfg"] / "limn" / "paper-b.env").unlink()
    assert box["run"]("migrate", "paper-b").returncode == 0
    # Dry run shows the move but does nothing.
    r = box["run"]("migrate", "--move-state", "--dry-run", "paper-b")
    assert r.returncode == 0 and "(dry-run) state dir" in r.stdout and not target.exists()
    r = box["run"]("migrate", "--move-state", "paper-b")
    assert r.returncode == 0, r.stdout
    assert (target / "pins.jsonl").read_text() == '{"id": 2}\n'
    assert read_env(new_b)["STATE_DIR"] == str(target)
    # Running again is a no-op.
    r = box["run"]("migrate", "--move-state", "paper-b")
    assert r.returncode == 0 and "already migrated" in r.stdout


def test_state_outside_the_old_root_is_never_moved(box):
    r = box["run"]("migrate", "--move-state", "paper-a")
    assert r.returncode == 0
    assert (box["legacy_state"] / "pins.jsonl").exists()
    assert read_env(box["cfg"] / "limn" / "paper-a.env")["STATE_DIR"] == str(box["legacy_state"])
    assert "kept as is" in r.stdout


def test_limn_run_uses_the_migrated_config(box):
    assert box["run"]("migrate").returncode == 0
    r = box["run"]("run", "paper-a", LIMN_PRINT_ARGV="1")
    assert r.returncode == 0, r.stderr
    argv = r.stdout.splitlines()
    assert argv[argv.index("--port") + 1] == str(box["fmt"]["port_a"])
    assert argv[argv.index("--state-dir") + 1] == str(box["legacy_state"])
    assert "ms=본문:main.tex" in argv and "--git-pull" in argv and "--no-build" in argv
