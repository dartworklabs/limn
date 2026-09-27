"""Resolve a CLI instance or explicit state directory and bind the audit sink."""

import argparse
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeAlias

from limn.audit import append_audit, audit_action, audit_entry, os_actor

INSTANCE_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
OptionSpec: TypeAlias = tuple[tuple[str, ...], dict[str, Any]]


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
        v = line[m.end() :].rstrip()
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


def split_target(
    prog: str, argv: Sequence[str], npos: int, extra: Sequence[OptionSpec] | None = None
) -> tuple[Path, list[str], argparse.Namespace]:
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


def cli_audit(state: Path) -> Callable[[str, Mapping[str, Any]], bool]:
    """The audit sink of `limn token` / `limn member` on state (limn.access.AuditSink): each change becomes one
    audit.jsonl line (limn.audit) as the OS account running the command (os_actor), via "cli", stamped with the clock
    when it is recorded. The action is narrowed by audit_action (ValueError for one limn.audit does not name - a
    defect of the caller). A failed write only warns on stderr and returns False, as append_audit does."""

    def record(action: str, details: Mapping[str, Any]) -> bool:
        """Append one audit line for action with details."""
        return append_audit(state, audit_entry(audit_action(action), os_actor(), "cli", details, time.time()))

    return record
