"""`limn migrate` — 이전 이름(pin-viewer)으로 돌던 인스턴스를 Limn 으로 옮긴다. 한 번 쓰는 명령이다.

이 파일과 그 테스트만 이전 이름을 안다. 하는 일:

1. `~/.config/pin-viewer/<이름>.env` 를 `~/.config/limn/<이름>.env` 로 복사한다. 키는 그대로이고
   (LABEL·MANUSCRIPT·DOCS·PORT·TS_PORT·STATE_DIR·GIT_PULL·EXTRA_ARGS …), 이전 이름이 든 주석 줄만 빼고
   머리 주석을 새로 단다. STATE_DIR 가 비어 있었으면 이전 기본값(~/.local/share/pin-viewer/<이름>)을
   적어 둔다 — Limn 의 기본값은 다른 폴더라, 적지 않으면 핀이 사라진 것처럼 보인다.
2. 상태 폴더가 `~/.local/share/pin-viewer/` 아래면 알리고, `--move-state` 일 때만
   `~/.local/share/limn/<이름>` 으로 옮기며 새 설정의 STATE_DIR 을 고친다. 옮기기 전에 두 유닛
   (pin-viewer@·limn@)이 꺼져 있고 PORT 가 비어 있는지 확인한다.
3. systemd 전환 명령(pin-viewer@ 중지·비활성 → limn@ 기동)을 찍는다. 직접 실행하지는 않는다.

같은 명령을 여러 번 불러도 결과가 같다. 이전 파일·폴더는 지우지 않는다. `--dry-run` 은 아무 것도 쓰지
않고 할 일만 보인다.
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


def parse(text: str) -> tuple[dict, list]:
    """(키→값, 줄 목록). 같은 키가 여러 번이면 마지막 값(systemd·instances.sh 와 같은 규칙)."""
    vals, lines = {}, text.splitlines()
    for ln in lines:
        m = KEY_RE.match(ln.rstrip("\r"))
        if m:
            vals[m.group(1)] = unquote(m.group(2))
    return vals, lines


def render(name: str, src: Path, lines: list, state_dir: str, had_state: bool) -> str:
    out = ["# %s@%s — `limn migrate` 가 %s 에 %s 에서 옮겼다. 형식·키는 docs/instances.md." % (
        NEW, name, date.today().isoformat(), src),
        "# 셸로 source 하지 않는다 — 값에 셸 문법을 쓰지 말 것."]
    for ln in lines:
        s = ln.rstrip("\r")
        if s.lstrip().startswith("#"):
            if OLD_WORD_RE.search(s) or s.strip() in ("# 셸로 source 하지 않는다 — 값에 셸 문법을 쓰지 말 것.",):
                continue
            out.append(s)
            continue
        m = KEY_RE.match(s)
        if m and m.group(1) == "STATE_DIR":
            out.append(emit("STATE_DIR", state_dir))
            continue
        out.append(s)
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
        r = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True, timeout=10)
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
        description="이전 이름(pin-viewer)의 인스턴스 설정·상태를 Limn 으로 옮긴다. 이전 파일은 지우지 않는다. "
                    "이 저장소는 writing-agent-playbook 의 manuscript-pin-picker 스킬과 dotfiles 의 "
                    "bin/pin-viewer.sh 에서 2026-09-25 에 옮겨 왔다(README §출처와 이전).")
    ap.add_argument("names", nargs="*", help="옮길 인스턴스 이름(생략하면 전부)")
    ap.add_argument("--dry-run", "-n", action="store_true", help="아무 것도 쓰지 않고 할 일만 보인다")
    ap.add_argument("--move-state", action="store_true",
                    help="이전 데이터 폴더 아래의 상태 폴더를 새 데이터 폴더로 옮긴다(유닛이 꺼져 있어야 한다)")
    cfg, data = xdg("XDG_CONFIG_HOME", ".config"), xdg("XDG_DATA_HOME", ".local/share")
    ap.add_argument("--old-config-dir", type=Path, default=cfg / OLD)
    ap.add_argument("--config-dir", type=Path, default=Path(os.environ.get("LIMN_CONFIG_DIR") or cfg / NEW))
    ap.add_argument("--old-data-root", type=Path, default=data / OLD)
    ap.add_argument("--data-root", type=Path, default=Path(os.environ.get("LIMN_DATA_ROOT") or data / NEW))
    a = ap.parse_args(argv)
    dry = a.dry_run
    tag = "(dry-run) " if dry else ""

    if not a.old_config_dir.is_dir():
        print("이전 설정 폴더가 없습니다: %s — 옮길 것이 없습니다" % a.old_config_dir)
        return 0
    found = sorted(p for p in a.old_config_dir.glob("*.env") if NAME_RE.match(p.stem))
    names = a.names or [p.stem for p in found]
    missing = [n for n in names if not (a.old_config_dir / ("%s.env" % n)).exists()]
    if missing:
        print("limn migrate: 이전 설정이 없습니다: %s" % ", ".join(missing), file=sys.stderr)
        return 1
    if not names:
        print("이전 설정이 없습니다: %s/*.env" % a.old_config_dir)
        return 0

    problems = 0
    claimed = set()
    switch = []
    for n in names:
        src = a.old_config_dir / ("%s.env" % n)
        dst = a.config_dir / ("%s.env" % n)
        text = src.read_text(encoding="utf-8")
        vals, lines = parse(text)
        had_state = bool(vals.get("STATE_DIR"))
        state = vals.get("STATE_DIR") or str(a.old_data_root / n)
        claimed.add(Path(state).resolve())
        want = render(n, src, lines, state, had_state)
        print("[%s]" % n)
        link = " (심링크 → %s)" % os.path.realpath(src) if src.is_symlink() else ""
        print("  이전 설정  %s%s" % (src, link))

        # 1. 설정
        if dst.exists():
            cur_vals, _ = parse(dst.read_text(encoding="utf-8"))
            new_vals, _ = parse(want)
            moved = str(a.data_root / n)
            same = cur_vals == new_vals or (
                {k: v for k, v in cur_vals.items() if k != "STATE_DIR"} ==
                {k: v for k, v in new_vals.items() if k != "STATE_DIR"} and cur_vals.get("STATE_DIR") == moved)
            if same:
                print("  새 설정    %s — 이미 옮겼다" % dst)
            else:
                print("  새 설정    %s — 이미 있고 내용이 다르다. 건드리지 않는다(손으로 확인)" % dst)
                problems += 1
                continue
        else:
            print("  %s새 설정    %s 에 쓴다" % (tag, dst))
            if not dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(".env.tmp")
                tmp.write_text(want, encoding="utf-8")
                os.replace(tmp, dst)
        if link:
            print("  참고       이전 설정은 심링크였다 — 원본 저장소에서 관리하려면 LIMN_SOURCE_DIR 로 그 폴더를 가리킨다")

        # 2. 상태 폴더
        cur_state = parse(dst.read_text(encoding="utf-8"))[0].get("STATE_DIR", state) if dst.exists() else state
        sp = Path(cur_state)
        if under(sp, a.old_data_root):
            target = a.data_root / n
            if not a.move_state:
                print("  상태 폴더  %s — 이전 데이터 폴더 아래다. 그대로 써도 된다" % sp)
                print("             옮기려면 유닛을 끈 뒤: limn migrate --move-state %s  (→ %s)" % (n, target))
            else:
                why = []
                for u in ("%s@%s.service" % (OLD, n), "%s@%s.service" % (NEW, n)):
                    if unit_active(u):
                        why.append("%s 가 켜져 있다" % u)
                port = vals.get("PORT", "")
                if port_busy(port):
                    why.append("로컬 포트 %s 이 쓰이고 있다" % port)
                if target.exists():
                    why.append("%s 가 이미 있다" % target)
                if not sp.is_dir():
                    why.append("%s 가 없다" % sp)
                if why:
                    print("  상태 폴더  %s — 옮기지 않는다: %s" % (sp, "; ".join(why)))
                    problems += 1
                else:
                    print("  %s상태 폴더  %s → %s (새 설정의 STATE_DIR 도 고친다)" % (tag, sp, target))
                    if not dry:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(sp), str(target))
                        dst.write_text(set_state(dst.read_text(encoding="utf-8"), str(target)), encoding="utf-8")
        else:
            print("  상태 폴더  %s — 그대로 쓴다(핀·빌드 이력이 이어진다)" % sp)
        switch.append(n)

    # 이전 데이터 폴더의 나머지(이전 앱 사본 등)
    if a.old_data_root.is_dir():
        rest = [p for p in sorted(a.old_data_root.iterdir())
                if p.is_dir() and p.resolve() not in claimed]
        if rest:
            print("")
            print("이전 데이터 폴더 %s 의 나머지 — Limn 은 쓰지 않는다. 지우지 않았다:" % a.old_data_root)
            for p in rest:
                print("  %s" % p)

    if switch:
        print("")
        print("systemd 전환(인스턴스마다 — 포트·tailscale serve 항목은 그대로 이어진다):")
        for n in switch:
            print("  systemctl --user disable --now %s@%s.service" % (OLD, n))
            print("  limn start %s" % n)
            print("  limn status %s" % n)
        print("전환이 끝나면 이전 유닛 템플릿(~/.config/systemd/user/%s@.service)과 이전 설정은 지워도 된다." % OLD)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
