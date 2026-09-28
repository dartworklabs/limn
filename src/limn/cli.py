"""Select the `limn` command and hand it to its feature owner.

Version and instance commands avoid loading the server or token and member stores.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from limn import __version__

HERE = Path(__file__).resolve().parent

HELP = """\
limn {version} — pin a spot in a manuscript PDF and get back the source lines

  limn serve --manuscript <dir> [server options]  run one server now (limn serve --help)
  limn version                                    print the installed version
  limn migrate [--dry-run] [--move-state] ...     move instances from the old install (limn migrate --help)

Access (per instance, or --state-dir <dir> for a plain `limn serve`):
  limn token create <instance> [--name NAME]      create an agent API token (shown once)
      [--save [--force] [--print]]                ...and write it to the instance's token file instead of printing it
  limn token path <instance>                      the token file agents on this machine read (~/.config/limn/<instance>.token)
  limn token list <instance>                      list tokens (id, name, created; never the token)
  limn token revoke <instance> <id|name>          revoke a token (the running server stops accepting it at once;
                                                  the token file goes too if it held that token)
  limn member add <instance> <login> [--role editor] [--name NAME]
  limn member list <instance>                     people.json: login, role, name, last seen
  limn member remove <instance> <login>
  limn member role <instance> <login> <owner|editor|viewer|agent>

Instances (one systemd user unit limn@<name> per manuscript):
"""


def limn_bin() -> str:
    """The limn executable to put into the systemd unit's ExecStart — prefer the one running now."""
    argv0 = Path(sys.argv[0])
    if argv0.name == "limn" and argv0.exists():
        # Do not resolve symlinks: uv's bin dir (~/.local/bin/limn) is the path that survives upgrades.
        return os.path.abspath(argv0)
    return shutil.which("limn") or str(Path.home() / ".local" / "bin" / "limn")


def instances_env() -> dict[str, str]:
    """The environment instances.sh runs in: the caller's, plus where this install keeps its interpreter, server,
    unit template and limn executable (LIMN_PYTHON, LIMN_SERVER, LIMN_UNIT_TEMPLATE, LIMN_BIN; a value the caller
    already set wins), and LIMN_VERSION, which is always this package's version."""
    env = dict(os.environ)
    env.setdefault("LIMN_PYTHON", sys.executable)
    env.setdefault("LIMN_SERVER", str(HERE / "server.py"))
    env.setdefault("LIMN_UNIT_TEMPLATE", str(HERE / "systemd" / "limn@.service"))
    env.setdefault("LIMN_BIN", limn_bin())
    env["LIMN_VERSION"] = __version__
    return env


def run_instances(args: Sequence[str]) -> int:
    """Replace this process with `bash instances.sh <args...>` in instances_env(). Returns 1 only when bash is not
    installed (after saying so on stderr); otherwise it never returns - the script's exit status is the process's.
    os.execve raises OSError if bash cannot be executed."""
    bash = shutil.which("bash")
    if not bash:
        print("limn: bash is required", file=sys.stderr)
        return 1
    os.execve(bash, [bash, str(HERE / "instances.sh"), *args], instances_env())
    return 1  # not reached


def main(argv: Sequence[str] | None = None) -> int:
    """The `limn` entry point -> exit status. serve, version, migrate, token and member run here in Python; every
    other command execs instances.sh (so this returns only for those). A CliError, bad value, OS or subprocess error
    of `token` / `member` is one `limn: ...` line on stderr and status 1."""
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
        from limn.features.administration import migrate

        return migrate.main(args[1:])
    if cmd in ("token", "member"):
        from limn.features.administration import members, tokens
        from limn.features.administration.targets import CliError

        try:
            return (tokens.cmd_token if cmd == "token" else members.cmd_member)(args[1:])
        except (CliError, ValueError, OSError, subprocess.SubprocessError) as e:
            print("limn: %s" % e, file=sys.stderr)
            return 1
    if cmd in ("", "-h", "--help", "help"):
        sys.stdout.write(HELP.format(version=__version__))
        sys.stdout.flush()
    return run_instances(args)


if __name__ == "__main__":
    raise SystemExit(main())
