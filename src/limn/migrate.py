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
from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path

OLD = "pin-viewer"
NEW = "limn"
KEY_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)=(.*)$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
OLD_WORD_RE = re.compile(r"pin[-_ ]?viewer|pin_server|manuscript-pin-picker|핀 뷰어", re.I)
HEADER_2 = "# Not sourced by a shell — do not use shell syntax in values."
HISTORY = ("This repository moved here on 2026-09-25 from the manuscript-pin-picker skill of "
           "writing-agent-playbook and bin/pin-viewer.sh of dotfiles (README, History).")


def xdg(var: str, default: str) -> Path:
    v = os.environ.get(var)
    return Path(v) if v else Path.home() / default


def unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def emit(key: str, val: str) -> str:
    if re.search(r"[\s#]", val):
        return '%s="%s"' % (key, val)
    return "%s=%s" % (key, val)


def parse(text: str) -> dict:
    """KEY -> value. A repeated key keeps its last value (same rule as systemd and instances.sh)."""
    vals = {}
    for ln in text.splitlines():
        m = KEY_RE.match(ln.rstrip("\r"))
        if m:
            vals[m.group(1)] = unquote(m.group(2))
    return vals


def render(name: str, text: str, state_dir: str, had_state: bool) -> str:
    out = ["# %s@%s — written by `limn migrate` on %s. Keys: docs/handbook/instances.md." % (
        NEW, name, date.today().isoformat()), HEADER_2]
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
    out, done = [], False
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
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.stdout.strip() in ("active", "activating", "reloading", "deactivating")


def port_busy(port: str) -> bool:
    if not port.isdigit():
        return False
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="limn migrate",
        description="Move instance configs (and optionally state dirs) from the old %s install to Limn. "
                    "Old files are never deleted. %s" % (OLD, HISTORY))
    ap.add_argument("names", nargs="*", help="instances to migrate (default: all)")
    ap.add_argument("--dry-run", "-n", action="store_true", help="write nothing; show what would happen")
    ap.add_argument("--move-state", action="store_true",
                    help="move state dirs under the old data root to the new one (units must be stopped)")
    cfg, data = xdg("XDG_CONFIG_HOME", ".config"), xdg("XDG_DATA_HOME", ".local/share")
    ap.add_argument("--old-config-dir", type=Path, default=cfg / OLD)
    ap.add_argument("--config-dir", type=Path, default=Path(os.environ.get("LIMN_CONFIG_DIR") or cfg / NEW))
    ap.add_argument("--old-data-root", type=Path, default=data / OLD)
    ap.add_argument("--data-root", type=Path, default=Path(os.environ.get("LIMN_DATA_ROOT") or data / NEW))
    a = ap.parse_args(argv)
    dry = a.dry_run
    tag = "(dry-run) " if dry else ""

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
    claimed = set()
    switch = []
    for n in names:
        src = a.old_config_dir / ("%s.env" % n)
        dst = a.config_dir / ("%s.env" % n)
        text = src.read_text(encoding="utf-8")
        vals = parse(text)
        had_state = bool(vals.get("STATE_DIR"))
        state = vals.get("STATE_DIR") or str(a.old_data_root / n)
        claimed.add(Path(state).resolve())
        want = render(n, text, state, had_state)
        print("[%s]" % n)
        link = " (symlink -> %s)" % os.path.realpath(src) if src.is_symlink() else ""
        print("  old config  %s%s" % (src, link))

        # 1. config
        if dst.exists():
            cur, new = parse(dst.read_text(encoding="utf-8")), parse(want)
            strip = lambda d: {k: v for k, v in d.items() if k != "STATE_DIR"}  # noqa: E731
            if cur == new or (strip(cur) == strip(new) and cur.get("STATE_DIR") == str(a.data_root / n)):
                print("  new config  %s — already migrated" % dst)
            else:
                print("  new config  %s — exists with different values; left alone (check by hand)" % dst)
                problems += 1
                continue
        else:
            print("  %snew config  write %s" % (tag, dst))
            if not dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".tmp")
                tmp.write_text(want, encoding="utf-8")
                os.replace(tmp, dst)
        if link:
            print("  note        the old config was a symlink — to keep configs in that repository, "
                  "point LIMN_SOURCE_DIR at its directory")

        # 2. state dir
        cur_state = parse(dst.read_text(encoding="utf-8")).get("STATE_DIR", state) if dst.exists() else state
        sp = Path(cur_state)
        if under(sp, a.old_data_root):
            target = a.data_root / n
            if not a.move_state:
                print("  state dir   %s — under the old data root; fine to keep using it" % sp)
                print("              to move it, stop the units, then: limn migrate --move-state %s  (-> %s)"
                      % (n, target))
            else:
                why = ["%s is running" % u for u in ("%s@%s.service" % (OLD, n), "%s@%s.service" % (NEW, n))
                       if unit_active(u)]
                if port_busy(vals.get("PORT", "")):
                    why.append("local port %s is in use" % vals.get("PORT"))
                if target.exists():
                    why.append("%s already exists" % target)
                if not sp.is_dir():
                    why.append("%s does not exist" % sp)
                if why:
                    print("  state dir   %s — not moved: %s" % (sp, "; ".join(why)))
                    problems += 1
                else:
                    print("  %sstate dir   %s -> %s (STATE_DIR in the new config updated)" % (tag, sp, target))
                    if not dry:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(sp), str(target))
                        dst.write_text(set_state(dst.read_text(encoding="utf-8"), str(target)), encoding="utf-8")
        else:
            print("  state dir   %s — kept as is (pins and build history continue)" % sp)
        switch.append(n)

    if a.old_data_root.is_dir():
        rest = [p for p in sorted(a.old_data_root.iterdir()) if p.is_dir() and p.resolve() not in claimed]
        if rest:
            print("")
            print("Other directories in the old data root %s — Limn does not use them; not deleted:" % a.old_data_root)
            for p in rest:
                print("  %s" % p)

    if switch:
        print("")
        print("systemd switch, per instance (ports and tailscale serve entries carry over unchanged):")
        for n in switch:
            print("  systemctl --user disable --now %s@%s.service" % (OLD, n))
            print("  limn start %s" % n)
            print("  limn status %s" % n)
        print("After switching, the old unit template (~/.config/systemd/user/%s@.service) and the old "
              "configs can be removed." % OLD)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
