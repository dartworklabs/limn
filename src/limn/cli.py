"""The `limn` command: run a server (serve), print the version, migrate old installs, and manage
long-running instances (add, start, ...).

Instance management lives in the bash script instances.sh next to this file. This module hands it
the paths it needs (interpreter, server, unit template, the limn executable) and the version via
environment variables, then execs bash.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from limn import __version__

HERE = Path(__file__).resolve().parent

HELP = """\
limn {version} — pin a spot in a manuscript PDF and get back the source lines

  limn serve --manuscript <dir> [server options]  run one server now (limn serve --help)
  limn version                                    print the installed version
  limn migrate [--dry-run] [--move-state] ...     move instances from the old install (limn migrate --help)

Instances (one systemd user unit limn@<name> per manuscript):
"""


def limn_bin() -> str:
    """The limn executable to put into the systemd unit's ExecStart — prefer the one running now."""
    argv0 = Path(sys.argv[0])
    if argv0.name == "limn" and argv0.exists():
        # Do not resolve symlinks: uv's bin dir (~/.local/bin/limn) is the path that survives upgrades.
        return os.path.abspath(argv0)
    return shutil.which("limn") or str(Path.home() / ".local" / "bin" / "limn")


def instances_env() -> dict:
    env = dict(os.environ)
    env.setdefault("LIMN_PYTHON", sys.executable)
    env.setdefault("LIMN_SERVER", str(HERE / "server.py"))
    env.setdefault("LIMN_UNIT_TEMPLATE", str(HERE / "systemd" / "limn@.service"))
    env.setdefault("LIMN_BIN", limn_bin())
    env["LIMN_VERSION"] = __version__
    return env


def run_instances(args: list) -> int:
    bash = shutil.which("bash")
    if not bash:
        print("limn: bash is required", file=sys.stderr)
        return 1
    os.execve(bash, [bash, str(HERE / "instances.sh"), *args], instances_env())
    return 1  # not reached


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else ""
    if cmd in ("version", "--version", "-V"):
        print("limn %s" % __version__)
        return 0
    if cmd == "serve":
        from limn import server
        sys.argv = ["limn serve", *args[1:]]
        server.main()
        return 0
    if cmd == "migrate":
        from limn import migrate
        return migrate.main(args[1:])
    if cmd in ("", "-h", "--help", "help"):
        sys.stdout.write(HELP.format(version=__version__))
        sys.stdout.flush()
    return run_instances(args)


if __name__ == "__main__":
    raise SystemExit(main())
