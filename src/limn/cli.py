"""The `limn` command: run a server (serve), print the version, migrate old installs, manage agent API tokens
(token) and member roles (member), and manage long-running instances (add, start, ...).

Instance management lives in the bash script instances.sh next to this file. This module hands it
the paths it needs (interpreter, server, unit template, the limn executable) and the version via
environment variables, then execs bash. `limn token` and `limn member` are Python: they edit the
instance's state directory through the state helpers in limn.access, with the audit sink and the people.json format
that server.py wires (cli_audit, PEOPLE_FORMAT). server.py is imported only by the commands that need it, so
`limn version` and the instance commands stay fast.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, TypeAlias

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

INSTANCE_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
TOKEN_LINE_RE = re.compile(r"limn_[A-Za-z0-9_-]+")   # what a token file holds: access.TOKEN_PREFIX + token_urlsafe

# One extra argparse option of split_target(): (flags, add_argument keyword arguments),
# e.g. (("--name",), {"help": "..."}).
OptionSpec: TypeAlias = tuple[tuple[str, ...], dict[str, Any]]


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


# ---------------------------------------------------------------- instance -> state dir (same rules as instances.sh)

class CliError(Exception):
    """A refusal of `limn token` / `limn member` the user can act on; main() prints its message as one
    `limn: ...` line on stderr and exits with status 1."""


def env_get(path: Path, key: str) -> str | None:
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
    """The XDG base folder in environment variable var, or ~/<default> when it is unset or empty."""
    return Path(os.environ.get(var) or (Path.home() / default))


def check_instance_name(name: str) -> None:
    """Raise CliError unless name is a valid instance name - the rule of valid_name in instances.sh."""
    if not INSTANCE_RE.fullmatch(name or "") or name == "serve":
        raise CliError("name must match [a-z0-9-]+ (must start with a letter/digit, 'serve' is reserved): '%s'" % name)


def config_dir() -> Path:
    """The instance config folder, resolved as instances.sh does: $LIMN_CONFIG_DIR, else $XDG_CONFIG_HOME/limn,
    else ~/.config/limn."""
    return Path(os.environ.get("LIMN_CONFIG_DIR") or xdg("XDG_CONFIG_HOME", ".config") / "limn")


def instance_state_dir(name: str) -> Path:
    """STATE_DIR of instance <name>: $LIMN_CONFIG_DIR/<name>.env (default $XDG_CONFIG_HOME/limn; then the
    $LIMN_SOURCE_DIR copy), key STATE_DIR, default $LIMN_DATA_ROOT/<name> (default $XDG_DATA_HOME/limn)."""
    check_instance_name(name)
    cfg = config_dir()
    source_dir = Path(os.environ.get("LIMN_SOURCE_DIR") or cfg)
    f = cfg / ("%s.env" % name)
    if not f.is_file():
        f = source_dir / ("%s.env" % name)
    if not f.is_file():
        raise CliError("no config found: %s (or use --state-dir <dir>)" % (cfg / ("%s.env" % name)))
    state = env_get(f, "STATE_DIR")
    if state:
        return Path(state)
    data_root = Path(os.environ.get("LIMN_DATA_ROOT") or xdg("XDG_DATA_HOME", ".local/share") / "limn")
    return data_root / name


def split_target(prog: str, argv: Sequence[str], npos: int,
                 extra: Sequence[OptionSpec] | None = None) -> tuple[Path, list[str], argparse.Namespace]:
    """Parses '<instance> <positionals...> [options]' or '--state-dir DIR <positionals...> [options]'
    -> (state dir, positionals, options namespace). The namespace's `instance` is the instance name, None for
    --state-dir (a plain `limn serve` has no instance, so no token file). extra adds options (OptionSpec).

    Wrong usage - no instance, or not exactly npos positionals - exits through argparse (usage on stderr, status 2);
    an invalid or unconfigured instance name raises CliError."""
    ap = argparse.ArgumentParser(prog=prog)
    ap.add_argument("--state-dir", help="state directory of a plain `limn serve` instead of an instance name")
    for args, kw in extra or []:
        ap.add_argument(*args, **kw)
    ap.add_argument("args", nargs="*")
    ns = ap.parse_intermixed_args(argv)
    pos = list(ns.args)
    ns.instance = None
    if ns.state_dir:
        state = Path(ns.state_dir).expanduser().resolve()
    else:
        if not pos:
            ap.error("an instance name (or --state-dir <dir>) is required")
        ns.instance = pos.pop(0)
        state = instance_state_dir(ns.instance)
    if len(pos) != npos:
        ap.error("expected %d argument(s) after the instance, got %d: %s" % (npos, len(pos), " ".join(pos) or "(none)"))
    return state, pos, ns


# ---------------------------------------------------------------- the agent token file (docs/adr/0007-agent-token-file.md)

def token_file_path(name: str) -> Path:
    """Where agents on this machine read instance <name>'s token: <config dir>/<name>.token, next to <name>.env.

    Never the LIMN_SOURCE_DIR copy of the config - that folder is often a dotfiles repository, and a token file must
    not land in one. instances.sh's token_file_of gives the same path."""
    check_instance_name(name)
    return config_dir() / ("%s.token" % name)


class SaveTarget(NamedTuple):
    """What is at a token file path before `limn token create --save` writes it (gathered by inspect_save_target)."""
    occupied: bool         # something is already at the path - a dangling symlink too
    repo: str | None       # the git work tree that would hold the file without ignoring it; None if there is none
    unknown: str | None = None   # why git could not tell whether a work tree holds it; None when it could


def save_refusal(target: SaveTarget, path: Path, force: bool) -> str | None:
    """Why --save must not write the token file at path, or None when it may. A work tree that would hold the file
    refuses even with --force (a token never goes into a repository), and so does not being able to tell; an existing
    file needs --force."""
    if target.unknown:
        return ("could not tell whether %s is inside a git work tree (%s) - a token file never goes into a repository. "
                "Fix git, or set LIMN_CONFIG_DIR to a folder outside any repository" % (path.parent, target.unknown))
    if target.repo:
        return ("%s would be inside the git work tree %s, which does not ignore it - a token file never goes into a "
                "repository. Ignore it there (e.g. '*.token' in its .gitignore) or set LIMN_CONFIG_DIR to a folder "
                "outside any repository" % (path, target.repo))
    if target.occupied and not force:
        return ("%s already exists - pass --force to replace it (the token in it stays valid until you revoke it: "
                "limn token list, limn token revoke)" % path)
    return None


def git_tree_holding(path: Path) -> tuple[str | None, str | None]:
    """(work tree, None) when a git work tree holds path's folder and does not ignore path; (None, None) when none
    does, git is not installed, or it is macOS's stub without developer tools; (None, why) when git fails otherwise
    (dubious ownership, a broken repository), so the caller can refuse rather than guess.

    Symlinks are resolved first, so a config folder linked into a repository is judged by that repository. The folder
    may not exist yet: its nearest existing parent is asked. GIT_* variables of the caller (GIT_DIR, GIT_WORK_TREE)
    are dropped - they would point git at another repository - and messages are read in the C locale."""
    git = shutil.which("git")
    if not git:
        return None, None
    folder = path.parent
    while not folder.is_dir() and folder != folder.parent:
        folder = folder.parent
    real = folder.resolve() / path.parent.relative_to(folder) / path.name
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"

    def git_in(*args: str) -> subprocess.CompletedProcess[str]:
        """One git command in the resolved folder, with the cleaned environment; never raises on git's status."""
        return subprocess.run([git, "-C", str(folder.resolve()), *args], capture_output=True, text=True, env=env,
                              timeout=30, check=False)
    top = git_in("rev-parse", "--show-toplevel")
    if top.returncode != 0:
        err = top.stderr.strip()
        if "not a git repository" in err or "xcode-select" in err or "developer tools" in err.lower():
            return None, None
        return None, (err.splitlines() or ["git rev-parse failed"])[-1]
    ignored = git_in("check-ignore", "-q", str(real))
    if ignored.returncode == 0:
        return None, None
    if ignored.returncode == 1:
        return top.stdout.strip(), None
    return None, (ignored.stderr.strip().splitlines() or ["git check-ignore failed"])[-1]


def inspect_save_target(path: Path) -> SaveTarget:
    """The facts save_refusal() decides on, read from the file system and git."""
    repo, unknown = git_tree_holding(path)
    return SaveTarget(occupied=os.path.lexists(path), repo=repo, unknown=unknown)


def write_token_file(path: Path, token: str, replace: bool) -> None:
    """Write token as the only line of path, mode 0600; a missing folder is created with mode 0700.

    Without replace the file must not exist: O_EXCL never follows a symlink and fails if another writer got there
    first (FileExistsError). With replace the new file is swapped in atomically (a 0600 temp file in the same folder,
    then os.replace, which replaces a symlink itself and never writes through it). A half-written new file or temp
    file - both hold the token - is removed. Raises OSError."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = token + "\n"
    if replace:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".%s." % path.name)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as fh:
                os.fchmod(fh.fileno(), 0o600)
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, data.encode("ascii"))
        os.fsync(fd)
    except OSError:
        os.close(fd)
        path.unlink()
        raise
    os.close(fd)


def read_token_file(path: Path) -> str | None:
    """The token a token file holds, or None: no regular file there (a symlink is not followed), unreadable, or not
    one token line."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text if TOKEN_LINE_RE.fullmatch(text) else None


def create_saved_token(state: Path, ns: argparse.Namespace) -> int:
    """`limn token create <instance> --save`: check the target, create the token, write it to the token file.

    Every check runs before the token exists, and a failed write revokes the new token again, so a failure never
    leaves a valid token nobody holds. The token is printed only with --print."""
    from limn import access, server as ps
    if ns.instance is None:
        raise CliError("--save needs an instance name: the token file is <config dir>/<instance>.token "
                       "(see limn token path <instance>)")
    path = token_file_path(ns.instance)
    previous = read_token_file(path) if ns.force else None
    refusal = save_refusal(inspect_save_target(path), path, ns.force)
    if refusal:
        raise CliError(refusal)
    entry, plain = access.token_create(state, ns.name, ps.cli_audit(state))
    try:
        write_token_file(path, plain, replace=ns.force)
    except OSError as e:
        try:
            access.token_revoke(state, entry["id"], ps.cli_audit(state))
        except (OSError, ValueError) as undo:
            raise CliError("could not write %s: %s - and could not revoke the new token (%s), so it is still valid; "
                           "revoke it: limn token revoke %s %s" % (path, e, undo, ns.instance, entry["id"])) from e
        raise CliError("could not write %s: %s - the new token %s was revoked again" % (path, e, entry["id"])) from e
    if ns.print:
        print(plain)
        sys.stdout.flush()
    print("limn: created token %s (name %s) in %s" % (entry["id"], entry["name"], state / "tokens.json"), file=sys.stderr)
    print("limn: saved it to %s (mode 0600)%s. Agents on this machine send it with\n"
          "        curl -H \"Authorization: Bearer $(cat %s)\" <base>/pins.md\n"
          "      A running server accepts it on the next request." % (path, "" if ns.print else ", not printed", path),
          file=sys.stderr)
    if previous:
        old = [t for t in access.load_tokens(state) if t["hash"] == access.token_hash(previous)]
        if old:
            print("limn: the token that was in the file (id %s, name %s) is still valid - revoke it if nothing else "
                  "uses it: limn token revoke %s %s" % (old[0]["id"], old[0]["name"], ns.instance, old[0]["id"]),
                  file=sys.stderr)
    return 0


def forget_saved_token(path: Path, revoked: Mapping[str, Any], token_hash: Callable[[str], str]) -> str | None:
    """After a revoke: remove the token file if it held the revoked token (an agent would only get 401 from it) and
    say so; say that a file holding another token, or one it cannot read, was kept; None when there is no token file."""
    if not os.path.lexists(path):
        return None
    saved = read_token_file(path)
    if saved is None:
        return "kept %s - could not read one token from it (unreadable, a symlink, or not one token line)" % path
    if token_hash(saved) == revoked["hash"]:
        path.unlink()
        return "removed %s (it held this token)" % path
    return "kept %s - it holds another token" % path


def cmd_token(argv: Sequence[str]) -> int:
    """`limn token create|path|list|revoke ...` -> exit status. Edits <state>/tokens.json through the state helpers in
    limn.access (audited through server.cli_audit) and, for an instance, its token file (ADR-0007). Refusals raise
    CliError; main() prints them."""
    sub = argv[0] if argv else ""
    rest = argv[1:]
    from limn import access, server as ps
    if sub == "create":
        state, _, ns = split_target("limn token create", rest, 0, [
            (("--name",), {"help": "token name (default agent, agent-2, ...)"}),
            (("--save",), {"action": "store_true",
                           "help": "write the token to the instance's token file (limn token path) instead of printing it"}),
            (("--force",), {"action": "store_true", "help": "with --save: replace an existing token file"}),
            (("--print",), {"action": "store_true", "help": "with --save: print the token as well"})])
        if ns.save:
            return create_saved_token(state, ns)
        if ns.force or ns.print:
            raise CliError("--force and --print only go with --save")
        entry, plain = access.token_create(state, ns.name, ps.cli_audit(state))
        print(plain)
        sys.stdout.flush()
        print("limn: created token %s (name %s) in %s" % (entry["id"], entry["name"], state / "tokens.json"), file=sys.stderr)
        print("limn: this is the only time the token is shown; only its hash is stored. Give it to the agent, e.g.\n"
              "        export LIMN_TOKEN=<the token above>\n"
              "        curl -s -H \"Authorization: Bearer $LIMN_TOKEN\" <base>/pins.md\n"
              "      A running server accepts it on the next request.", file=sys.stderr)
        return 0
    if sub == "path":
        ap = argparse.ArgumentParser(prog="limn token path",
                                     description="Print the token file agents on this machine read (it is not read here)")
        ap.add_argument("instance")
        print(token_file_path(ap.parse_args(rest).instance))
        return 0
    if sub == "list":
        state, _, ns = split_target("limn token list", rest, 0)
        rows = access.load_tokens(state, strict=True)
        if not rows:
            print("no tokens in %s" % state)
            return 0
        print("%-10s %-24s %s" % ("ID", "NAME", "CREATED"))
        for t in rows:
            print("%-10s %-24s %s" % (t["id"], t["name"], t.get("created", "")))
        saved = read_token_file(token_file_path(ns.instance)) if ns.instance else None
        held = [t for t in rows if saved is not None and t["hash"] == access.token_hash(saved)]
        if held:
            print("token file %s holds %s (name %s)" % (token_file_path(ns.instance), held[0]["id"], held[0]["name"]))
        return 0
    if sub in ("revoke", "rm"):
        state, pos, ns = split_target("limn token revoke", rest, 1)
        revoked = access.token_revoke(state, pos[0], ps.cli_audit(state))
        if revoked is None:
            raise CliError("no token with id or name %r in %s" % (pos[0], state))
        print("revoked token %s (name %s) — the running server refuses it from the next request"
              % (revoked["id"], revoked["name"]))
        note = forget_saved_token(token_file_path(ns.instance), revoked, access.token_hash) if ns.instance else None
        if note:
            print(note)
        return 0
    raise CliError("limn token create|path|list|revoke <instance> ... (unknown subcommand: '%s')" % sub)


def cmd_member(argv: Sequence[str]) -> int:
    """`limn member add|list|remove|role ...` -> exit status. Edits <state>/people.json through the state helpers in
    limn.access, in server.py's people.json format and audit sink; a running server applies the change from its next
    request. A missing member or an unknown subcommand
    raises CliError; an invalid login or role, an existing member, or an unreadable people.json raises ValueError
    from the store helpers; main() prints both."""
    sub = argv[0] if argv else ""
    rest = argv[1:]
    from limn import access, server as ps
    note = "the running server applies it from the next request"
    if sub == "add":
        state, pos, ns = split_target("limn member add", rest, 1, [
            (("--role",), {"default": access.DEFAULT_ROLE, "choices": access.ROLES, "help": "role (default editor)"}),
            (("--name",), {"help": "display name (default: the part of the login before @)"})])
        e = access.member_add(state, pos[0], ns.role, ns.name, ps.PEOPLE_FORMAT, ps.cli_audit(state))
        print("added %s as %s (%s) — %s" % (e["login"], e["role"], e["name"], note))
        return 0
    if sub in ("list", "ls"):
        state, _, _ = split_target("limn member list", rest, 0)
        rows = access.load_people_file(state, ps.PEOPLE_FORMAT)
        if not rows:
            print("no members in %s" % state)
            return 0
        print("%-32s %-7s %-24s %s" % ("LOGIN", "ROLE", "NAME", "LAST SEEN"))
        for x in rows:
            role = access.role_value(x.get("role"))
            print("%-32s %-7s %-24s %s" % (x["login"], role + ("" if "role" in x else "*"), x.get("name") or "",
                                           x.get("last_seen") or "-"))
        if any("role" not in x for x in rows):
            print("* no role recorded — editor by default (set one with `limn member role <instance> <login> <role>`)")
        return 0
    if sub in ("remove", "rm"):
        state, pos, _ = split_target("limn member remove", rest, 1)
        if access.member_remove(state, pos[0], ps.PEOPLE_FORMAT, ps.cli_audit(state)) is None:
            raise CliError("%s is not in %s" % (pos[0], state / "people.json"))
        print("removed %s — %s" % (pos[0], note))
        return 0
    if sub == "role":
        state, pos, _ = split_target("limn member role", rest, 2)
        changed = access.member_set_role(state, pos[0], pos[1], ps.PEOPLE_FORMAT, ps.cli_audit(state))
        if changed is None:
            raise CliError("%s is not in %s (add it with `limn member add`)" % (pos[0], state / "people.json"))
        print("%s is now %s — %s" % (changed["login"], changed["role"], note))
        return 0
    raise CliError("limn member add|list|remove|role <instance> ... (unknown subcommand: '%s')" % sub)


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
        from limn import migrate
        return migrate.main(args[1:])
    if cmd in ("token", "member"):
        try:
            return (cmd_token if cmd == "token" else cmd_member)(args[1:])
        except (CliError, ValueError, OSError, subprocess.SubprocessError) as e:
            print("limn: %s" % e, file=sys.stderr)
            return 1
    if cmd in ("", "-h", "--help", "help"):
        sys.stdout.write(HELP.format(version=__version__))
        sys.stdout.flush()
    return run_instances(args)


if __name__ == "__main__":
    raise SystemExit(main())
