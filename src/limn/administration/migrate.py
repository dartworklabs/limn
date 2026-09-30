"""`limn migrate` — move instances from the old install (named "pin-viewer") to Limn. One-shot command.

This module and its tests are the only places that know the old name. What it does:

1. Copies `~/.config/pin-viewer/<name>.env` to `~/.config/limn/<name>.env`. Keys are unchanged
   (LABEL, MANUSCRIPT, DOCS, PORT, TS_PORT, STATE_DIR, GIT_PULL, EXTRA_ARGS, ...); comment lines that
   mention the old name are dropped and a new header is written. If STATE_DIR was empty, the old
   default (`~/.local/share/pin-viewer/<name>`) is written explicitly — Limn's default is a different
   directory, and without it the pins would seem to vanish.
2. Reports state dirs under `~/.local/share/pin-viewer/` and, only with `--move-state`, moves them to
   `~/.local/share/limn/<name>` and updates STATE_DIR in the new config. Before moving it checks that
   both units (pin-viewer@ and limn@) are stopped and that PORT is free.
3. Prints the systemd switch commands (stop/disable pin-viewer@, then start limn@). It does not run them.

Idempotent: running it again gives the same result. Old files and directories are never deleted.
`--dry-run` writes nothing and shows what would happen.
"""

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

OLD = "pin-viewer"
NEW = "limn"
KEY_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)=(.*)$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
OLD_WORD_RE = re.compile(r"pin[-_ ]?viewer|pin_server|manuscript-pin-picker|핀 뷰어", re.I)
HEADER_2 = "# Not sourced by a shell — do not use shell syntax in values."
HISTORY = (
    "This repository moved here on 2026-09-25 from the manuscript-pin-picker skill of "
    "writing-agent-playbook and bin/pin-viewer.sh of dotfiles (README, History)."
)


def xdg(var: str, default: str) -> Path:
    """The XDG base folder in environment variable var, or ~/<default> when it is unset or empty."""
    v = os.environ.get(var)
    return Path(v) if v else Path.home() / default


def unquote(v: str) -> str:
    """A config value as instances.sh reads it: surrounding whitespace dropped, then one layer of matching single or
    double quotes removed. Nothing inside is unescaped."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def emit(key: str, val: str) -> str:
    """One KEY=VALUE config line; the value is wrapped in double quotes when it holds whitespace or '#', so unquote()
    and instances.sh read it back unchanged (a value containing '"' is not escaped)."""
    if re.search(r"[\s#]", val):
        return '%s="%s"' % (key, val)
    return "%s=%s" % (key, val)


def parse(text: str) -> dict[str, str]:
    """KEY -> value. A repeated key keeps its last value (same rule as systemd and instances.sh)."""
    vals: dict[str, str] = {}
    for ln in text.splitlines():
        m = KEY_RE.match(ln.rstrip("\r"))
        if m:
            vals[m.group(1)] = unquote(m.group(2))
    return vals


def render(name: str, text: str, state_dir: str, had_state: bool) -> str:
    """The new config for instance name from the old config text: a fresh two-line header dated today, then the old
    lines in order - comments that mention the old name (and an old copy of HEADER_2) dropped, every STATE_DIR line
    rewritten to state_dir, other lines kept as they were (a trailing CR removed). Without had_state (the old config
    set no non-empty STATE_DIR) a STATE_DIR line is appended, so the pins stay where the old install kept them."""
    out = [
        "# %s@%s — written by `limn migrate` on %s. Keys: docs/handbook/instances.md."
        % (NEW, name, date.today().isoformat()),
        HEADER_2,
    ]
    for ln in text.splitlines():
        s = ln.rstrip("\r")
        if s.lstrip().startswith("#"):
            if not OLD_WORD_RE.search(s) and s.strip() != HEADER_2:
                out.append(s)
            continue
        m = KEY_RE.match(s)
        out.append(emit("STATE_DIR", state_dir) if m and m.group(1) == "STATE_DIR" else s)
    if not had_state:
        out.append(emit("STATE_DIR", state_dir))
    return "\n".join(out) + "\n"


def set_state(text: str, state_dir: str) -> str:
    """text with every STATE_DIR line replaced by STATE_DIR=state_dir, or such a line appended if there was none.
    Other lines are kept; the result ends in one newline."""
    out: list[str] = []
    done = False
    for ln in text.splitlines():
        m = KEY_RE.match(ln)
        if m and m.group(1) == "STATE_DIR":
            out.append(emit("STATE_DIR", state_dir))
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(emit("STATE_DIR", state_dir))
    return "\n".join(out) + "\n"


def unit_active(unit: str) -> bool:
    """Whether the systemd user unit is running or changing state (active, activating, reloading, deactivating).
    False when systemctl is missing, fails or times out (10 s) - a machine without systemd has no running unit."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", unit], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.stdout.strip() in ("active", "activating", "reloading", "deactivating")


def port_busy(port: str) -> bool:
    """Whether something accepts TCP connections on 127.0.0.1:port (0.5 s timeout). False for an empty or
    non-numeric port - there is nothing to check."""
    if not port.isdigit():
        return False
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def under(p: Path, root: Path) -> bool:
    """Whether p is root or inside it, after resolving symlinks on both sides."""
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def without_state(vals: dict[str, str]) -> dict[str, str]:
    """vals without its STATE_DIR key: a new config that differs from the wanted one only in STATE_DIR - because an
    earlier --move-state moved the state dir to the new data root - still counts as migrated."""
    return {k: v for k, v in vals.items() if k != "STATE_DIR"}


def _args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the migration's names, roots, and dry-run or state-move options."""
    ap = argparse.ArgumentParser(
        prog="limn migrate",
        description="Move instance configs (and optionally state dirs) from the old %s install to Limn. "
        "Old files are never deleted. %s" % (OLD, HISTORY),
    )
    ap.add_argument("names", nargs="*", help="instances to migrate (default: all)")
    ap.add_argument("--dry-run", "-n", action="store_true", help="write nothing; show what would happen")
    ap.add_argument(
        "--move-state",
        action="store_true",
        help="move state dirs under the old data root to the new one (units must be stopped)",
    )
    cfg, data = xdg("XDG_CONFIG_HOME", ".config"), xdg("XDG_DATA_HOME", ".local/share")
    ap.add_argument("--old-config-dir", type=Path, default=cfg / OLD)
    ap.add_argument("--config-dir", type=Path, default=Path(os.environ.get("LIMN_CONFIG_DIR") or cfg / NEW))
    ap.add_argument("--old-data-root", type=Path, default=data / OLD)
    ap.add_argument("--data-root", type=Path, default=Path(os.environ.get("LIMN_DATA_ROOT") or data / NEW))
    return ap.parse_args(argv)


def _migrate_config(dst: Path, want: str, data_root: Path, name: str, dry: bool) -> bool:
    """Write or recognize one destination config; refuse a different existing config."""
    if dst.exists():
        cur, new = parse(dst.read_text(encoding="utf-8")), parse(want)
        if cur == new or (without_state(cur) == without_state(new) and cur.get("STATE_DIR") == str(data_root / name)):
            print("  new config  %s — already migrated" % dst)
            return True
        print("  new config  %s — exists with different values; left alone (check by hand)" % dst)
        return False
    print("  %snew config  write %s" % ("(dry-run) " if dry else "", dst))
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        tmp.write_text(want, encoding="utf-8")
        os.replace(tmp, dst)
    return True


def _migrate_state(a: argparse.Namespace, name: str, old: dict[str, str], dst: Path, state: str) -> int:
    """Report or move one state directory; return one problem when a requested move is blocked."""
    cur_state = parse(dst.read_text(encoding="utf-8")).get("STATE_DIR", state) if dst.exists() else state
    sp = Path(cur_state)
    if not under(sp, a.old_data_root):
        print("  state dir   %s — kept as is (pins and build history continue)" % sp)
        return 0
    target = a.data_root / name
    if not a.move_state:
        print("  state dir   %s — under the old data root; fine to keep using it" % sp)
        print("              to move it, stop the units, then: limn migrate --move-state %s  (-> %s)" % (name, target))
        return 0
    why = [
        "%s is running" % unit
        for unit in ("%s@%s.service" % (OLD, name), "%s@%s.service" % (NEW, name))
        if unit_active(unit)
    ]
    if port_busy(old.get("PORT", "")):
        why.append("local port %s is in use" % old.get("PORT"))
    if target.exists():
        why.append("%s already exists" % target)
    if not sp.is_dir():
        why.append("%s does not exist" % sp)
    if why:
        print("  state dir   %s — not moved: %s" % (sp, "; ".join(why)))
        return 1
    print(
        "  %sstate dir   %s -> %s (STATE_DIR in the new config updated)"
        % ("(dry-run) " if a.dry_run else "", sp, target)
    )
    if not a.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(sp), str(target))
        dst.write_text(set_state(dst.read_text(encoding="utf-8"), str(target)), encoding="utf-8")
    return 0


def _migrate_one(a: argparse.Namespace, name: str, claimed: set[Path]) -> tuple[int, bool]:
    """Report and migrate one instance; return its problem count and whether to show its switch commands."""
    src = a.old_config_dir / ("%s.env" % name)
    dst = a.config_dir / ("%s.env" % name)
    text = src.read_text(encoding="utf-8")
    vals = parse(text)
    had_state = bool(vals.get("STATE_DIR"))
    state = vals.get("STATE_DIR") or str(a.old_data_root / name)
    claimed.add(Path(state).resolve())
    want = render(name, text, state, had_state)
    print("[%s]" % name)
    link = " (symlink -> %s)" % os.path.realpath(src) if src.is_symlink() else ""
    print("  old config  %s%s" % (src, link))
    if not _migrate_config(dst, want, a.data_root, name, a.dry_run):
        return 1, False
    if link:
        print(
            "  note        the old config was a symlink — to keep configs in that repository, "
            "point LIMN_SOURCE_DIR at its directory"
        )
    return _migrate_state(a, name, vals, dst, state), True


def _report_remaining(old_data_root: Path, claimed: set[Path]) -> None:
    """List old data directories that no migrated instance claims."""
    if old_data_root.is_dir():
        rest = [p for p in sorted(old_data_root.iterdir()) if p.is_dir() and p.resolve() not in claimed]
        if rest:
            print("")
            print("Other directories in the old data root %s — Limn does not use them; not deleted:" % old_data_root)
            for p in rest:
                print("  %s" % p)


def _report_switch(names: list[str]) -> None:
    """Print the manual systemd switch commands for migrated instances."""
    if not names:
        return
    print("")
    print("systemd switch, per instance (ports and tailscale serve entries carry over unchanged):")
    for name in names:
        print("  systemctl --user disable --now %s@%s.service" % (OLD, name))
        print("  limn start %s" % name)
        print("  limn status %s" % name)
    print(
        "After switching, the old unit template (~/.config/systemd/user/%s@.service) and the old "
        "configs can be removed." % OLD
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Migrate selected instances and report a status of 1 for conflicts or blocked state moves."""
    a = _args(argv)
    if not a.old_config_dir.is_dir():
        print("No old config dir: %s — nothing to migrate" % a.old_config_dir)
        return 0
    found = sorted(p.stem for p in a.old_config_dir.glob("*.env") if NAME_RE.match(p.stem))
    names = a.names or found
    missing = [n for n in names if not (a.old_config_dir / ("%s.env" % n)).is_file()]
    if missing:
        print("limn migrate: no old config for: %s" % ", ".join(missing), file=sys.stderr)
        return 1
    if not names:
        print("No old configs: %s/*.env" % a.old_config_dir)
        return 0

    problems = 0
    claimed: set[Path] = set()
    switch: list[str] = []
    for name in names:
        issue, show_switch = _migrate_one(a, name, claimed)
        problems += issue
        if show_switch:
            switch.append(name)
    _report_remaining(a.old_data_root, claimed)
    _report_switch(switch)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
