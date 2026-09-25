"""The `limn` command: run a server (serve), print the version, migrate old installs, manage agent API tokens
(token) and member roles (member), and manage long-running instances (add, start, ...).

Instance management lives in the bash script instances.sh next to this file. This module hands it
the paths it needs (interpreter, server, unit template, the limn executable) and the version via
environment variables, then execs bash. `limn token` and `limn member` are Python: they edit the
instance's state directory through the store helpers in server.py (the server stays one module).
"""
from __future__ import annotations

import argparse
import os
import re
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

Access (per instance, or --state-dir <dir> for a plain `limn serve`):
  limn token create <instance> [--name NAME]      create an agent API token (shown once)
  limn token list <instance>                      list tokens (id, name, created; never the token)
  limn token revoke <instance> <id|name>          revoke a token (the running server stops accepting it at once)
  limn member add <instance> <login> [--role editor] [--name NAME]
  limn member list <instance>                     people.json: login, role, name, last seen
  limn member remove <instance> <login>
  limn member role <instance> <login> <owner|editor|viewer|agent>

Instances (one systemd user unit limn@<name> per manuscript):
"""

INSTANCE_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


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


# ---------------------------------------------------------------- instance -> state dir (same rules as instances.sh)

class CliError(Exception):
    pass


def env_get(path: Path, key: str):
    """One KEY=VALUE from an instance config, read without a shell — the same rules as env_get in instances.sh:
    the last matching line wins, leading whitespace before KEY and trailing whitespace are dropped, and one layer
    of matching single or double quotes is removed. None if the key is absent."""
    val = None
    pat = re.compile(r"^[ \t\f\v]*" + re.escape(key) + "=")
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line[:-1] if line.endswith("\r") else line
        m = pat.match(line)
        if not m:
            continue
        v = line[m.end():].rstrip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        val = v
    return val


def xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or (Path.home() / default))


def instance_state_dir(name: str) -> Path:
    """STATE_DIR of instance <name>: $LIMN_CONFIG_DIR/<name>.env (default $XDG_CONFIG_HOME/limn; then the
    $LIMN_SOURCE_DIR copy), key STATE_DIR, default $LIMN_DATA_ROOT/<name> (default $XDG_DATA_HOME/limn)."""
    if not INSTANCE_RE.fullmatch(name or "") or name == "serve":
        raise CliError("name must match [a-z0-9-]+ (must start with a letter/digit, 'serve' is reserved): '%s'" % name)
    config_dir = Path(os.environ.get("LIMN_CONFIG_DIR") or xdg("XDG_CONFIG_HOME", ".config") / "limn")
    source_dir = Path(os.environ.get("LIMN_SOURCE_DIR") or config_dir)
    f = config_dir / ("%s.env" % name)
    if not f.is_file():
        f = source_dir / ("%s.env" % name)
    if not f.is_file():
        raise CliError("no config found: %s (or use --state-dir <dir>)" % (config_dir / ("%s.env" % name)))
    state = env_get(f, "STATE_DIR")
    if state:
        return Path(state)
    data_root = Path(os.environ.get("LIMN_DATA_ROOT") or xdg("XDG_DATA_HOME", ".local/share") / "limn")
    return data_root / name


def split_target(prog: str, argv: list, npos: int, extra=None) -> tuple:
    """Parses '<instance> <positionals...> [options]' or '--state-dir DIR <positionals...> [options]'
    -> (state dir, positionals, options namespace)."""
    ap = argparse.ArgumentParser(prog=prog)
    ap.add_argument("--state-dir", help="state directory of a plain `limn serve` instead of an instance name")
    for args, kw in extra or []:
        ap.add_argument(*args, **kw)
    ap.add_argument("args", nargs="*")
    ns = ap.parse_intermixed_args(argv)
    pos = list(ns.args)
    if ns.state_dir:
        state = Path(ns.state_dir).expanduser().resolve()
    else:
        if not pos:
            ap.error("an instance name (or --state-dir <dir>) is required")
        state = instance_state_dir(pos.pop(0))
    if len(pos) != npos:
        ap.error("expected %d argument(s) after the instance, got %d: %s" % (npos, len(pos), " ".join(pos) or "(none)"))
    return state, pos, ns


def server_module():
    from limn import server
    return server


def cmd_token(argv: list) -> int:
    sub = argv[0] if argv else ""
    rest = argv[1:]
    ps = server_module()
    if sub == "create":
        state, _, ns = split_target("limn token create", rest, 0, [(("--name",), {"help": "token name (default agent, agent-2, ...)"})])
        entry, plain = ps.token_create(state, ns.name)
        print(plain)
        sys.stdout.flush()
        print("limn: created token %s (name %s) in %s" % (entry["id"], entry["name"], state / "tokens.json"), file=sys.stderr)
        print("limn: this is the only time the token is shown; only its hash is stored. Give it to the agent, e.g.\n"
              "        export LIMN_TOKEN=<the token above>\n"
              "        curl -s -H \"Authorization: Bearer $LIMN_TOKEN\" <base>/pins.md\n"
              "      A running server accepts it on the next request.", file=sys.stderr)
        return 0
    if sub == "list":
        state, _, _ = split_target("limn token list", rest, 0)
        rows = ps.load_tokens(state, strict=True)
        if not rows:
            print("no tokens in %s" % state)
            return 0
        print("%-10s %-24s %s" % ("ID", "NAME", "CREATED"))
        for t in rows:
            print("%-10s %-24s %s" % (t["id"], t["name"], t.get("created", "")))
        return 0
    if sub in ("revoke", "rm"):
        state, pos, _ = split_target("limn token revoke", rest, 1)
        t = ps.token_revoke(state, pos[0])
        if t is None:
            raise CliError("no token with id or name %r in %s" % (pos[0], state))
        print("revoked token %s (name %s) — the running server refuses it from the next request" % (t["id"], t["name"]))
        return 0
    raise CliError("limn token create|list|revoke <instance> ... (unknown subcommand: '%s')" % sub)


def cmd_member(argv: list) -> int:
    sub = argv[0] if argv else ""
    rest = argv[1:]
    ps = server_module()
    note = "the running server applies it from the next request"
    if sub == "add":
        state, pos, ns = split_target("limn member add", rest, 1, [
            (("--role",), {"default": ps.DEFAULT_ROLE, "choices": ps.ROLES, "help": "role (default editor)"}),
            (("--name",), {"help": "display name (default: the part of the login before @)"})])
        e = ps.member_add(state, pos[0], ns.role, ns.name)
        print("added %s as %s (%s) — %s" % (e["login"], e["role"], e["name"], note))
        return 0
    if sub in ("list", "ls"):
        state, _, _ = split_target("limn member list", rest, 0)
        rows = ps.load_people_file(state)
        if not rows:
            print("no members in %s" % state)
            return 0
        print("%-32s %-7s %-24s %s" % ("LOGIN", "ROLE", "NAME", "LAST SEEN"))
        for x in rows:
            role = ps.role_value(x.get("role"))
            print("%-32s %-7s %-24s %s" % (x["login"], role + ("" if "role" in x else "*"), x.get("name") or "",
                                           x.get("last_seen") or "-"))
        if any("role" not in x for x in rows):
            print("* no role recorded — editor by default (set one with `limn member role <instance> <login> <role>`)")
        return 0
    if sub in ("remove", "rm"):
        state, pos, _ = split_target("limn member remove", rest, 1)
        if ps.member_remove(state, pos[0]) is None:
            raise CliError("%s is not in %s" % (pos[0], state / "people.json"))
        print("removed %s — %s" % (pos[0], note))
        return 0
    if sub == "role":
        state, pos, _ = split_target("limn member role", rest, 2)
        e = ps.member_set_role(state, pos[0], pos[1])
        if e is None:
            raise CliError("%s is not in %s (add it with `limn member add`)" % (pos[0], state / "people.json"))
        print("%s is now %s — %s" % (e["login"], e["role"], note))
        return 0
    raise CliError("limn member add|list|remove|role <instance> ... (unknown subcommand: '%s')" % sub)


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
    if cmd in ("token", "member"):
        try:
            return (cmd_token if cmd == "token" else cmd_member)(args[1:])
        except (CliError, ValueError, OSError) as e:
            print("limn: %s" % e, file=sys.stderr)
            return 1
    if cmd in ("", "-h", "--help", "help"):
        sys.stdout.write(HELP.format(version=__version__))
        sys.stdout.flush()
    return run_instances(args)


if __name__ == "__main__":
    raise SystemExit(main())
