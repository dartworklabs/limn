#!/usr/bin/env bash
# 원고 핀 뷰어를 논문마다 따로 띄우고 관리한다 — `pin-viewer@<이름>.service` 인스턴스.
#
# 논문마다 저장소가 따로이고, 두 논문을 동시에 작업하면 뷰어도 동시에 따로 돌아야 한다.
# 그래서 인스턴스마다 포트·상태 폴더(핀·빌드·build.log)·journal 이 갈리고, 앱 사본 하나만
# 함께 쓴다. 구조와 절차는 machines/example-host/pin-viewer/README.md.
#
# Usage:
#   pin-viewer add <이름> --manuscript <원고 폴더> [--main <파일.tex>] [--port N] [--ts-port N]
#                  [--git-pull] [--label <이름표>] [--accent <#rrggbb>] [--state-dir <폴더>]
#                  [--extra "<서버 인자>"] [--no-serve] [--no-start]
#   pin-viewer start <이름> [--no-serve]   설정이 이미 있는 인스턴스를 켠다(재부팅 뒤·새 기기·전환)
#   pin-viewer stop <이름>                 유닛만 끈다(설정·포트·serve 항목은 그대로)
#   pin-viewer update [--from <스킬 폴더>] [--force] [--no-restart]
#                                          플러그인에서 앱 사본을 갱신하고 켜진 인스턴스를 재시작
#   pin-viewer list                        인스턴스 표(이름표·포트·상태·열린 핀·원고)
#   pin-viewer status [<이름>]             자세히
#   pin-viewer url [<이름>]                테일넷 주소
#   pin-viewer snippet <이름>              그 논문 저장소 AGENTS.md 에 붙일 안내 조각(출력만)
#   pin-viewer remove <이름>               유닛 중지·비활성, serve 해제, 설정(=포트 예약) 삭제.
#                                          상태 폴더는 지우지 않는다
#   pin-viewer run <이름>                  (유닛 전용) 설정을 읽어 서버로 exec
#
# 보안 규칙(바꾸지 말 것): 바인딩은 127.0.0.1 뿐(서버에 박혀 있다), 노출은 `tailscale serve`
# 만, funnel 은 절대 쓰지 않는다, sudo 를 부르지 않는다. 이 호스트는 operator 가 이 사용자라
# serve 는 sudo 없이 걸린다 — 안 걸리면 오류를 보이고 멈춘다(권한을 스스로 바꾸지 않는다).

set -uo pipefail
unset CDPATH

# 심링크(~/.local/bin/pin-viewer)를 끝까지 따라가 레포 안의 자기 위치를 찾는다.
# bin/dotfiles-machine.sh 와 같은 이유 — 그래야 lib/ 와 machines/ 를 찾는다.
_resolve_symlink() {
    local path=$1 link depth=0
    while [[ -L "$path" ]]; do
        if ((++depth > 40)); then
            printf '심링크가 너무 깊거나 순환합니다: %s\n' "$1" >&2
            return 1
        fi
        link="$(readlink "$path")"
        if [[ "$link" == /* ]]; then
            path="$link"
        else
            path="$(cd "$(dirname "$path")" && pwd)/$link"
        fi
    done
    printf '%s\n' "$path"
}
_SELF="$(_resolve_symlink "${BASH_SOURCE[0]}")" || exit 1
DOTFILES_DIR="$(cd "$(dirname "$_SELF")/.." && pwd)"
# shellcheck source=../lib/dotfiles.sh
source "$DOTFILES_DIR/lib/dotfiles.sh"

# ── 경로 (PIN_VIEWER_* 로 덮을 수 있다 — 테스트가 홈을 건드리지 않게) ──
MACHINE_ID="${PIN_VIEWER_MACHINE_ID:-$(dotfiles_machine_id)}"
DATA_ROOT="${PIN_VIEWER_DATA_ROOT:-$HOME/.local/share/pin-viewer}"
APP_DIR="${PIN_VIEWER_APP_DIR:-$DATA_ROOT/app}"
CONFIG_DIR="${PIN_VIEWER_CONFIG_DIR:-$HOME/.config/pin-viewer}"
SOURCE_DIR="${PIN_VIEWER_SOURCE_DIR:-$DOTFILES_DIR/machines/$MACHINE_ID/pin-viewer}"
UNITS_SRC_DIR="${PIN_VIEWER_UNITS_DIR:-$DOTFILES_DIR/machines/$MACHINE_ID/systemd}"
USER_UNIT_DIR="${PIN_VIEWER_USER_UNIT_DIR:-$HOME/.config/systemd/user}"
LEDGER="${PIN_VIEWER_LEDGER:-$HOME/.config/served/reserved-ports.txt}"
PLUGIN_ROOT="${PIN_VIEWER_PLUGIN_ROOT:-$HOME/.claude/plugins}"
SKILL_REL="skills/manuscript-pin-picker"
# 자동 배정 대역. 기존 관례(18003↔18103 대시보드, 18004↔18104 핀 뷰어)를 따라
# 테일넷 포트 N 에 로컬 포트 N+100 을 짝짓는다 — 주소만 보고도 짝을 안다.
TS_MIN="${PIN_VIEWER_TS_MIN:-18005}"
TS_MAX="${PIN_VIEWER_TS_MAX:-18099}"
LOCAL_OFFSET="${PIN_VIEWER_LOCAL_OFFSET:-100}"
PYTHON="${PIN_VIEWER_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
    if [[ -x /usr/bin/python3 ]]; then PYTHON=/usr/bin/python3; else PYTHON=$(command -v python3 || true); fi
fi
WAIT_S="${PIN_VIEWER_WAIT:-240}"

die() {
    printf 'pin-viewer: %s\n' "$*" >&2
    exit 1
}
say() { printf '%s\n' "$*"; }
warn() { printf 'pin-viewer: 경고: %s\n' "$*" >&2; }

unit_of() { printf 'pin-viewer@%s.service' "$1"; }
sysu() { dotfiles_systemctl_user "$@"; }

valid_name() {
    [[ "$1" =~ ^[a-z0-9][a-z0-9-]*$ ]] || return 1
    # `app` 은 공유 앱 사본 폴더 이름과 겹친다(기본 상태 폴더가 DATA_ROOT/<이름> 이다).
    [[ "$1" != app ]]
}
need_name() {
    [[ -n "${1:-}" ]] || die "이름이 필요합니다"
    valid_name "$1" || die "이름은 [a-z0-9-]+ (첫 글자는 영숫자, 'app' 은 예약) 만 받습니다: '$1'"
}
valid_port() { [[ "$1" =~ ^[0-9]+$ ]] && (($1 >= 1024 && $1 <= 65535)); }

# ── 설정 파일 ──
# 형식은 systemd EnvironmentFile 의 부분집합이다: `KEY=VALUE` 한 줄, 값은 맨값이거나
# 큰따옴표 한 겹. 셸로 source 하지 않는다 — 설정 파일 한 줄이 코드가 되면 안 된다.
# 쓸 때는 따옴표·역슬래시·$·백틱·줄바꿈을 거부하므로 두 파서가 달리 읽을 여지가 없다.
conf_of() { printf '%s/%s.env' "$CONFIG_DIR" "$1"; }
src_of() { printf '%s/%s.env' "$SOURCE_DIR" "$1"; }

env_get() { # env_get <파일> <KEY>
    awk -v k="$2" -v q="'" '
        { sub(/\r$/, "") }
        $0 ~ "^[[:space:]]*" k "=" {
            v = $0; sub("^[[:space:]]*" k "=", "", v); sub(/[[:space:]]+$/, "", v)
            a = substr(v, 1, 1); b = substr(v, length(v), 1)
            if (length(v) >= 2 && a == b && (a == "\"" || a == q)) v = substr(v, 2, length(v) - 2)
            val = v; found = 1
        }
        END { if (found) print val }' "$1"
}

# 인스턴스 설정을 C_* 전역으로 읽는다.
load() { # load <이름>
    local f
    f=$(conf_of "$1")
    [[ -f "$f" ]] || f=$(src_of "$1")
    [[ -f "$f" ]] || return 1
    C_FILE=$f
    C_LABEL=$(env_get "$f" LABEL)
    C_ACCENT=$(env_get "$f" ACCENT)
    C_MANUSCRIPT=$(env_get "$f" MANUSCRIPT)
    C_MAIN=$(env_get "$f" MAIN)
    C_PORT=$(env_get "$f" PORT)
    C_TS_PORT=$(env_get "$f" TS_PORT)
    C_STATE_DIR=$(env_get "$f" STATE_DIR)
    [[ -n "$C_STATE_DIR" ]] || C_STATE_DIR="$DATA_ROOT/$1"
    C_GIT_PULL=$(env_get "$f" GIT_PULL)
    C_EXTRA_ARGS=$(env_get "$f" EXTRA_ARGS)
}

safe_value() { # 설정 파일에 쓸 수 있는 값인가
    case "$1" in
        *'"'* | *"'"* | *'\'* | *'$'* | *'`'* | *$'\n'* | *$'\r'*) return 1 ;;
    esac
    return 0
}
emit() { # emit <KEY> <값> — 비면 줄을 만들지 않는다
    [[ -n "$2" ]] || return 0
    # 공백·`#` 이 든 값은 따옴표로 싼다(`#` 을 주석으로 읽는 파서가 있다).
    if [[ "$2" == *[[:space:]]* || "$2" == *'#'* ]]; then printf '%s="%s"\n' "$1" "$2"; else printf '%s=%s\n' "$1" "$2"; fi
}

instances() { # 설정이 있는 이름들(홈 설정 + 레포 원본)
    {
        local f
        for f in "$CONFIG_DIR"/*.env "$SOURCE_DIR"/*.env; do
            [[ -e "$f" ]] && basename "$f" .env
        done
    } | sort -u | while IFS= read -r n; do valid_name "$n" && printf '%s\n' "$n"; done
}

# ── 포트 장부 ──
# 장부는 손으로 쓰지 않는다: bin/served-reserved-ports.sh 가 유닛과 인스턴스 설정에서
# 만든다. 그래서 "예약" 은 설정 파일을 쓰고 장부를 다시 만드는 것이다.
ledger_lines() {
    local units=$UNITS_SRC_DIR tmp=""
    if [[ ! -d "$units" ]]; then
        tmp=$(mktemp -d) && units=$tmp
    fi
    # 원본 폴더를 따로 준다 — 유닛 폴더 옆이면 생성기가 이미 보지만, 겹친 줄은 생성기가 없앤다.
    local extra=("$CONFIG_DIR")
    [[ -d "$SOURCE_DIR" ]] && extra+=("$SOURCE_DIR")
    "$DOTFILES_DIR/bin/served-reserved-ports.sh" "$units" "${extra[@]}"
    [[ -n "$tmp" ]] && rmdir "$tmp"
    return 0
}
ledger_refresh() {
    mkdir -p "$(dirname "$LEDGER")" || return 1
    local t
    t=$(mktemp "$(dirname "$LEDGER")/.pin-viewer-ledger.XXXXXX") || return 1
    if ledger_lines > "$t"; then
        mv -f "$t" "$LEDGER"
    else
        rm -f "$t"
        warn "포트 장부를 다시 만들지 못했습니다: $LEDGER"
        return 1
    fi
}

# 테일넷 serve 항목: "<테일넷 포트> <프록시 대상 또는 -> <funnel 0|1>" 한 줄씩.
ts_map() {
    command -v tailscale > /dev/null 2>&1 || return 0
    tailscale serve status --json 2> /dev/null | "$PYTHON" -c '
import json, sys
try:
    d = json.load(sys.stdin) or {}
except Exception:
    sys.exit(0)
web = d.get("Web") or {}
fun = d.get("AllowFunnel") or {}
funnel_ports = {k.rsplit(":", 1)[-1] for k, v in fun.items() if v}
seen = set()
for hp, cfg in web.items():
    port = hp.rsplit(":", 1)[-1] if ":" in hp else "443"
    h = (cfg or {}).get("Handlers") or {}
    root = h.get("/") or {}
    proxy = root.get("Proxy") or (next(iter(h.values()), {}) or {}).get("Proxy") or "-"
    seen.add(port)
    print(port, proxy, 1 if port in funnel_ports else 0)
for port in (d.get("TCP") or {}):
    if port not in seen:
        print(port, "-", 1 if port in funnel_ports else 0)
'
}
ts_proxy_of() { ts_map | awk -v p="$1" '$1 == p { print $2; exit }'; }

listening() { # 어느 주소에서든 LISTEN 중인가 (테일넷 IP 에만 붙은 것도 본다)
    if command -v ss > /dev/null 2>&1; then
        [[ -n "$(ss -ltnH "sport = :$1" 2> /dev/null)" ]]
        return
    fi
    # ss 가 없으면(macOS) 모든 주소에 bind 해 본다. 점유돼 있으면 실패한다.
    ! "$PYTHON" -c 'import socket,sys
s=socket.socket(); s.bind(("0.0.0.0", int(sys.argv[1]))); s.close()' "$1" 2> /dev/null
}

# 포트를 고르는 동안 장부와 serve 목록을 한 번만 읽는다(후보마다 다시 읽으면 대역 하나에
# 생성기·tailscale 호출이 수백 번 돈다). LISTEN 여부만 후보마다 잰다.
snapshot_ports() {
    _SNAP_LEDGER=$(ledger_lines)
    _SNAP_TS=$(ts_map)
}
# port_taken <포트> [<자기 이름>] — 장부·LISTEN·serve 중 하나라도 걸리면 그 이유를 출력하고 0.
port_taken() {
    local p=$1 me=${2:-} who
    who=$(awk -v p="$p" -v me="pin-viewer@$me" '$1 == p && $2 != me { print $2; exit }' <<< "${_SNAP_LEDGER:-}")
    if [[ -n "$who" ]]; then printf '장부에 예약됨(%s)' "$who"; return 0; fi
    if listening "$p"; then printf '이미 LISTEN 중'; return 0; fi
    who=$(awk -v p="$p" '$1 == p { print $2; exit }' <<< "${_SNAP_TS:-}")
    if [[ -n "$who" ]]; then printf 'tailscale serve 가 이미 쓰는 중(%s)' "$who"; return 0; fi
    return 1
}

pick_pair() { # 빈 (테일넷, 로컬) 짝 하나
    local ts lp
    for ((ts = TS_MIN; ts <= TS_MAX; ts++)); do
        lp=$((ts + LOCAL_OFFSET))
        port_taken "$ts" > /dev/null && continue
        port_taken "$lp" > /dev/null && continue
        printf '%s %s\n' "$ts" "$lp"
        return 0
    done
    return 1
}

tailnet_host() {
    command -v tailscale > /dev/null 2>&1 || return 0
    tailscale status --json 2> /dev/null | "$PYTHON" -c '
import json, sys
try:
    print((json.load(sys.stdin).get("Self") or {}).get("DNSName", "").rstrip("."))
except Exception:
    pass'
}
url_of() { # url_of <테일넷 포트>
    local h
    h=$(tailnet_host)
    if [[ -n "$h" ]]; then printf 'https://%s:%s/' "$h" "$1"; else printf 'https://<기기>.<tailnet>.ts.net:%s/' "$1"; fi
}

# ── 앱 사본 ──
plugin_skill_dir() {
    # 설치된 버전이 정본이다. 캐시 폴더는 옛 버전이 쌓여 있고 이름이 해시라,
    # `ls | tail -1` 은 사전순으로 아무 옛 버전이나 고른다(실측 2026-09-23: 설치본
    # a8e83e9b60af 대신 e0023cdef0c9 를 골랐다).
    # (명령치환 안에 heredoc 을 두지 않는다 — macOS bash 3.2 가 잘못 파싱한다. tests/lib 주석 참고)
    local p
    p=$("$PYTHON" -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for key, ents in (d.get("plugins") or {}).items():
    if key.startswith("writing-agent-playbook@"):
        for e in ents or []:
            if e.get("installPath"):
                print(e["installPath"])
                sys.exit(0)
' "$PLUGIN_ROOT/installed_plugins.json" 2> /dev/null)
    if [[ -n "$p" && -f "$p/$SKILL_REL/scripts/pin_server.py" ]]; then
        printf '%s\n' "$p/$SKILL_REL"
        return 0
    fi
    # 기록이 없으면 가장 최근에 바뀐 캐시 폴더.
    p=$(find "$PLUGIN_ROOT"/cache/*/writing-agent-playbook -mindepth 1 -maxdepth 1 -type d 2> /dev/null \
        | while IFS= read -r d; do
            [[ -f "$d/$SKILL_REL/scripts/pin_server.py" ]] && printf '%s %s\n' "$(stat -c %Y "$d" 2> /dev/null || stat -f %m "$d")" "$d"
        done | sort -n | tail -1 | cut -d' ' -f2-)
    [[ -n "$p" ]] && printf '%s\n' "$p/$SKILL_REL"
}

app_sha() { [[ -f "$1/pin_server.py" ]] && "$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()[:12])' "$1/pin_server.py"; }

# install_app <스킬 폴더> — 같은 파일시스템에 먼저 만들고 이름만 바꿔 끼운다. 상태 폴더는
# 여기 없으므로 건드릴 일이 없다. 직전 사본은 app.prev 로 한 벌 남긴다(되돌리기용).
install_app() {
    local src=$1 stage
    [[ -f "$src/scripts/pin_server.py" ]] || die "pin_server.py 가 없습니다: $src/scripts"
    [[ -f "$src/vendor/pdfjs/pdf.min.mjs" && -f "$src/vendor/pdfjs/pdf.worker.min.mjs" ]] \
        || die "vendor/pdfjs 가 없습니다: $src/vendor/pdfjs (없으면 뷰어가 흐린 PNG 로 돈다)"
    "$PYTHON" "$src/scripts/pin_server.py" --help > /dev/null 2>&1 \
        || die "새 pin_server.py 가 --help 조차 못 돕니다 — 갈아 끼우지 않습니다: $src"
    mkdir -p "$(dirname "$APP_DIR")" || die "폴더를 만들지 못했습니다: $(dirname "$APP_DIR")"
    stage=$(mktemp -d "$(dirname "$APP_DIR")/.app-stage.XXXXXX") || die "임시 폴더 실패"
    if ! { mkdir -p "$stage/vendor" \
        && cp -p "$src/scripts/pin_server.py" "$stage/pin_server.py" \
        && cp -Rp "$src/vendor/pdfjs" "$stage/vendor/pdfjs"; }; then
        rm -rf "$stage"
        die "앱 사본 복사 실패"
    fi
    {
        printf 'source=%s\n' "$src"
        printf 'sha=%s\n' "$(app_sha "$stage")"
        printf 'installed_at=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
    } > "$stage/SOURCE"
    rm -rf "$APP_DIR.prev"
    if [[ -e "$APP_DIR" ]]; then mv "$APP_DIR" "$APP_DIR.prev" || die "옛 사본을 옮기지 못했습니다"; fi
    mv "$stage" "$APP_DIR" || die "새 사본을 끼우지 못했습니다(옛 사본: $APP_DIR.prev)"
}
ensure_app() {
    [[ -f "$APP_DIR/pin_server.py" ]] && return 0
    local s
    s=$(plugin_skill_dir)
    [[ -n "$s" ]] || die "앱 사본이 없고 플러그인 캐시에서도 찾지 못했습니다 — pin-viewer update --from <스킬 폴더>"
    install_app "$s"
    say "앱 사본 설치: $APP_DIR ($(app_sha "$APP_DIR"), $s)"
}

ensure_unit_link() {
    local src
    src=$(dotfiles_machine_files "$DOTFILES_DIR" "$MACHINE_ID" "systemd/pin-viewer@.service" | tail -1)
    [[ -n "$src" ]] || die "이 기기용 템플릿 유닛이 없습니다: machines/$MACHINE_ID/systemd/pin-viewer@.service"
    mkdir -p "$USER_UNIT_DIR"
    if [[ "$(readlink "$USER_UNIT_DIR/pin-viewer@.service" 2> /dev/null)" != "$src" ]]; then
        [[ -e "$USER_UNIT_DIR/pin-viewer@.service" && ! -L "$USER_UNIT_DIR/pin-viewer@.service" ]] \
            && die "$USER_UNIT_DIR/pin-viewer@.service 가 심링크가 아닌 파일입니다 — 손으로 확인하세요"
        ln -sfn "$src" "$USER_UNIT_DIR/pin-viewer@.service"
    fi
    sysu daemon-reload
}

ensure_conf_link() { # 레포 원본만 있으면 홈에 링크를 건다
    local n=$1
    [[ -e "$(conf_of "$n")" ]] && return 0
    [[ -f "$(src_of "$n")" ]] || die "설정이 없습니다: $(src_of "$n")"
    mkdir -p "$CONFIG_DIR" && ln -s "$(src_of "$n")" "$(conf_of "$n")"
}

http_code() { # http_code <로컬 포트> — 쓰기 없는 경로만 찌른다
    curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$1/api/meta?light=1" 2> /dev/null || true
}
wait_ready() { # wait_ready <이름> <포트>
    local i code
    for ((i = 0; i < WAIT_S; i++)); do
        code=$(http_code "$2")
        [[ "$code" == 200 ]] && return 0
        if [[ "$(sysu is-active "$(unit_of "$1")" 2> /dev/null)" == failed ]]; then
            return 2
        fi
        sleep 1
    done
    return 1
}

# serve_on <테일넷 포트> <로컬 포트> — 같은 짝이 이미 있으면 그대로 둔다. 남의 항목이면 멈춘다.
serve_on() {
    local ts=$1 lp=$2 cur want="http://127.0.0.1:$2"
    command -v tailscale > /dev/null 2>&1 || die "tailscale 이 없습니다 — --no-serve 로 로컬만 띄울 수 있습니다"
    cur=$(ts_proxy_of "$ts")
    if [[ "$cur" == "$want" ]]; then
        say "tailscale serve :$ts → $want (이미 있음)"
    elif [[ -n "$cur" ]]; then
        die "테일넷 :$ts 는 이미 $cur 로 쓰이고 있습니다 — 덮어쓰지 않습니다"
    else
        tailscale serve --bg --https="$ts" "$want" > /dev/null \
            || die "tailscale serve 실패 — 이 사용자가 operator 인지 확인하세요(권한은 바꾸지 않습니다)"
        say "tailscale serve :$ts → $want"
    fi
    # 걸렸는지, 그리고 funnel 이 아닌지 되읽어 확인한다(스킬 operations.md §보안 제약).
    local line
    line=$(ts_map | awk -v p="$ts" '$1 == p')
    [[ "$(awk '{print $2}' <<< "$line")" == "$want" ]] || die "serve 항목을 되읽지 못했습니다(:$ts)"
    [[ "$(awk '{print $3}' <<< "$line")" == 0 ]] || die ":$ts 가 funnel 로 열려 있습니다 — 즉시 확인하세요"
}
# serve_off <테일넷 포트> <로컬 포트> — 우리 짝일 때만 내린다.
serve_off() {
    local ts=$1 lp=$2 cur
    command -v tailscale > /dev/null 2>&1 || return 0
    cur=$(ts_proxy_of "$ts")
    if [[ -z "$cur" ]]; then
        say "tailscale serve :$ts 없음"
    elif [[ "$cur" != "http://127.0.0.1:$lp" ]]; then
        warn "테일넷 :$ts 는 $cur 를 가리킵니다 — 이 인스턴스 것이 아니라 내리지 않습니다"
    else
        tailscale serve --https="$ts" off > /dev/null || warn "serve 해제 실패(:$ts)"
        [[ -z "$(ts_proxy_of "$ts")" ]] && say "tailscale serve :$ts 해제"
    fi
}

open_pins() { # <상태 폴더> → 열린 핀 수 (pins.md 머리줄. 서버를 찌르지 않는다)
    [[ -f "$1/pins.md" ]] || {
        printf '?'
        return
    }
    local n
    n=$(sed -nE 's/.*열린 핀 ([0-9]+)건.*/\1/p' "$1/pins.md" | head -1)
    printf '%s' "${n:-?}"
}

default_label() { # 원고 git 저장소 이름 — origin URL 의 끝, 없으면 저장소 폴더 이름
    local m=$1 u top
    u=$(git -C "$m" remote get-url origin 2> /dev/null || true)
    if [[ -n "$u" ]]; then
        u=${u%/}
        u=${u##*/}
        u=${u##*:}
        printf '%s' "${u%.git}"
        return
    fi
    top=$(git -C "$m" rev-parse --show-toplevel 2> /dev/null || true)
    [[ -n "$top" ]] && printf '%s' "$(basename "$top")"
}

detect_main() { # 원고 폴더 맨 위에서 \documentclass 가 있는 .tex 가 정확히 하나면 그것
    local m=$1 cands=() f
    for f in "$m"/*.tex; do
        [[ -f "$f" ]] && grep -qE '^[^%]*\\documentclass' "$f" && cands+=("$(basename "$f")")
    done
    if [[ ${#cands[@]} -eq 1 ]]; then
        printf '%s' "${cands[0]}"
        return 0
    fi
    printf '최상위 .tex 를 %s — --main 으로 지정하세요: %s\n' \
        "$([[ ${#cands[@]} -eq 0 ]] && echo '찾지 못했습니다' || echo '여러 개 찾았습니다')" "${cands[*]:-(없음)}" >&2
    return 1
}

with_lock() { # 포트 고르기~설정 쓰기를 동시 add 끼리 겹치지 않게
    mkdir -p "$CONFIG_DIR"
    if command -v flock > /dev/null 2>&1; then
        exec 9> "$CONFIG_DIR/.lock"
        flock -w 30 9 || die "다른 pin-viewer 가 잠금을 쥐고 있습니다: $CONFIG_DIR/.lock"
    fi
}

# ─────────────────────────────── 명령 ───────────────────────────────

cmd_run() {
    local n=${1:-}
    need_name "$n"
    load "$n" || die "설정이 없습니다: $(conf_of "$n")"
    [[ -f "$APP_DIR/pin_server.py" ]] || die "앱 사본이 없습니다: $APP_DIR — pin-viewer update"
    [[ -n "$C_MANUSCRIPT" && -d "$C_MANUSCRIPT" ]] || die "MANUSCRIPT 폴더가 없습니다: '$C_MANUSCRIPT'"
    [[ -z "$C_MAIN" || -f "$C_MANUSCRIPT/$C_MAIN" ]] || die "MAIN 파일이 없습니다: $C_MANUSCRIPT/$C_MAIN"
    valid_port "${C_PORT:-x}" || die "PORT 가 없거나 잘못됐습니다: '$C_PORT' (자동 선택에 맡기지 않는다 — 광고한 주소가 깨진다)"
    local args=(--manuscript "$C_MANUSCRIPT" --port "$C_PORT" --state-dir "$C_STATE_DIR"
        --pdfjs-dir "$APP_DIR/vendor/pdfjs")
    [[ -n "$C_MAIN" ]] && args+=(--main "$C_MAIN")
    [[ "$C_GIT_PULL" == 1 ]] && args+=(--git-pull)
    # LABEL·ACCENT 는 앱 사본이 그 인자를 알 때만 넘긴다. 모르는 인자를 넘기면 argparse 가
    # 죽고 Restart 루프만 돈다 — 이름표 하나 때문에 뷰어가 통째로 안 뜨는 것보다 낫다.
    if [[ -n "$C_LABEL" || -n "$C_ACCENT" ]]; then
        local help
        help=$("$PYTHON" "$APP_DIR/pin_server.py" --help 2>&1 || true)
        if [[ -n "$C_LABEL" ]]; then
            if grep -q -- '--label' <<< "$help"; then args+=(--label "$C_LABEL"); else warn "앱 사본이 --label 을 모릅니다 — 이름표 없이 띄웁니다(pin-viewer update)"; fi
        fi
        if [[ -n "$C_ACCENT" ]]; then
            if grep -q -- '--accent' <<< "$help"; then args+=(--accent "$C_ACCENT"); else warn "앱 사본이 --accent 를 모릅니다 — 기본 색으로 띄웁니다(pin-viewer update)"; fi
        fi
    fi
    if [[ -n "$C_EXTRA_ARGS" ]]; then
        local extra
        read -r -a extra <<< "$C_EXTRA_ARGS"
        args+=("${extra[@]}")
    fi
    mkdir -p "$C_STATE_DIR" || die "상태 폴더를 만들지 못했습니다: $C_STATE_DIR"
    if [[ "${PIN_VIEWER_PRINT_ARGV:-0}" == 1 ]]; then
        printf '%s\n' "$PYTHON" "$APP_DIR/pin_server.py" "${args[@]}"
        return 0
    fi
    exec "$PYTHON" "$APP_DIR/pin_server.py" "${args[@]}"
}

start_instance() { # start_instance <이름> <serve 0|1>
    local n=$1 serve=$2 rc=0
    ensure_conf_link "$n"
    load "$n" || die "설정을 읽지 못했습니다: $n"
    ensure_app
    ensure_unit_link
    sysu enable "$(unit_of "$n")" > /dev/null 2>&1 || die "enable 실패: $(unit_of "$n")"
    sysu start "$(unit_of "$n")" || die "start 실패: journalctl --user -u $(unit_of "$n")"
    say "$(unit_of "$n") 기동 — 127.0.0.1:$C_PORT 응답 대기(첫 기동은 빌드까지 기다린다, 최대 ${WAIT_S}s)"
    wait_ready "$n" "$C_PORT" || rc=$?
    case $rc in
        0) say "127.0.0.1:$C_PORT 200" ;;
        2) die "유닛이 실패했습니다: journalctl --user -u $(unit_of "$n") -n 50" ;;
        *) warn "아직 200 이 아닙니다(빌드 중일 수 있음) — pin-viewer status $n" ;;
    esac
    if [[ "$serve" == 1 ]]; then
        valid_port "${C_TS_PORT:-x}" || die "TS_PORT 가 없습니다 — --no-serve 로 띄우거나 설정에 적으세요"
        serve_on "$C_TS_PORT" "$C_PORT"
    fi
}

cmd_add() {
    local n=${1:-}
    need_name "$n"
    shift
    local manuscript="" main="" port="" ts="" gitpull=0 label="" accent="" state="" extra_args="--no-build" serve=1 start=1
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --manuscript) manuscript=${2:-}; shift 2 ;;
            --main) main=${2:-}; shift 2 ;;
            --port) port=${2:-}; shift 2 ;;
            --ts-port) ts=${2:-}; shift 2 ;;
            --git-pull) gitpull=1; shift ;;
            --label) label=${2:-}; shift 2 ;;
            --accent) accent=${2:-}; shift 2 ;;
            --state-dir) state=${2:-}; shift 2 ;;
            --extra) extra_args=${2:-}; shift 2 ;;
            --no-serve) serve=0; shift ;;
            --no-start) start=0; serve=0; shift ;;
            *) die "모르는 인자: $1" ;;
        esac
    done
    [[ -n "$manuscript" ]] || die "--manuscript <원고 폴더> 가 필요합니다"
    [[ -d "$manuscript" ]] || die "원고 폴더가 없습니다: $manuscript"
    manuscript=$(cd "$manuscript" && pwd -P)
    if [[ -n "$main" ]]; then
        [[ "$main" != */* && -f "$manuscript/$main" ]] || die "메인 .tex 가 원고 폴더 맨 위에 없습니다: $manuscript/$main"
    else
        main=$(detect_main "$manuscript") || die "메인 .tex 자동 탐지 실패"
    fi
    [[ -z "$accent" || "$accent" =~ ^#[0-9a-fA-F]{6}$ ]] || die "--accent 는 #rrggbb 형식입니다: $accent"
    [[ -n "$label" ]] || label=$(default_label "$manuscript")
    [[ -n "$label" ]] || label=$n
    ((${#label} <= 40)) || die "--label 은 40자 이하: $label"
    [[ -n "$state" ]] || state="$DATA_ROOT/$n"
    local v
    for v in "$manuscript" "$main" "$label" "$state" "$extra_args"; do
        safe_value "$v" || die "설정 파일에 쓸 수 없는 문자(따옴표·역슬래시·\$·백틱·줄바꿈)가 있습니다: $v"
    done
    [[ "$state" == /* ]] || die "--state-dir 는 절대경로여야 합니다: $state"
    [[ "$state" != "$APP_DIR" && "$state" != "$APP_DIR"/* ]] || die "상태 폴더를 앱 사본 안에 둘 수 없습니다: $state"

    with_lock
    snapshot_ports
    [[ -e "$(conf_of "$n")" || -e "$(src_of "$n")" ]] \
        && die "'$n' 설정이 이미 있습니다 — 다시 켜려면 pin-viewer start $n, 새로 만들려면 먼저 remove"
    local o
    for o in $(instances); do
        load "$o" || continue
        [[ "$C_STATE_DIR" != "$state" ]] || die "상태 폴더가 '$o' 와 겹칩니다: $state"
        [[ "$C_MANUSCRIPT" != "$manuscript" ]] || warn "'$o' 도 같은 원고 폴더를 봅니다 — 빌드는 각자의 상태 폴더에서 하지만 --git-pull 이 겹칠 수 있습니다"
    done

    local why
    if [[ -z "$port" && -z "$ts" ]]; then
        read -r ts port <<< "$(pick_pair)"
        [[ -n "$port" ]] || die "$TS_MIN-$TS_MAX 대역에 빈 짝이 없습니다 — --port/--ts-port 로 지정하세요"
    else
        [[ -n "$port" ]] || port=$((ts + LOCAL_OFFSET))
        [[ -n "$ts" ]] || ts=$((port - LOCAL_OFFSET))
    fi
    valid_port "$port" || die "로컬 포트가 잘못됐습니다: $port"
    valid_port "$ts" || die "테일넷 포트가 잘못됐습니다: $ts"
    [[ "$port" != "$ts" ]] || die "로컬 포트와 테일넷 포트가 같습니다: $port"
    why=$(port_taken "$port" "$n") && die "로컬 포트 $port: $why"
    why=$(port_taken "$ts" "$n") && die "테일넷 포트 $ts: $why"

    mkdir -p "$SOURCE_DIR" || die "원본 폴더를 만들지 못했습니다: $SOURCE_DIR"
    {
        printf '# pin-viewer@%s — `pin-viewer add` 가 %s 에 만들었다. 형식·키는 README 참고.\n' "$n" "$(date +%F)"
        printf '# 셸로 source 하지 않는다 — 값에 셸 문법을 쓰지 말 것.\n'
        emit LABEL "$label"
        emit ACCENT "$accent"
        emit MANUSCRIPT "$manuscript"
        emit MAIN "$main"
        emit PORT "$port"
        emit TS_PORT "$ts"
        emit STATE_DIR "$state"
        emit GIT_PULL "$gitpull"
        emit EXTRA_ARGS "$extra_args"
    } > "$(src_of "$n")" || die "설정을 쓰지 못했습니다: $(src_of "$n")"
    mkdir -p "$CONFIG_DIR" && ln -sfn "$(src_of "$n")" "$(conf_of "$n")"
    ledger_refresh
    say "설정  $(src_of "$n")"
    say "링크  $(conf_of "$n") → 원본"
    say "포트  로컬 127.0.0.1:$port · 테일넷 :$ts (장부 $LEDGER 에 반영)"
    exec 9>&- # 잠금 해제 — 기동 대기(최대 수 분) 동안 다른 add 를 막지 않는다

    if [[ "$start" == 1 ]]; then
        start_instance "$n" "$serve"
    else
        say "켜지 않았습니다 — pin-viewer start $n"
    fi
    case "$(src_of "$n")" in
        "$DOTFILES_DIR"/*)
            say ""
            say "설정 원본은 dotfiles 에 있습니다. 브랜치에서 커밋하세요:"
            say "  git -C $DOTFILES_DIR add ${SOURCE_DIR#"$DOTFILES_DIR"/}/$n.env"
            ;;
    esac
    say ""
    cmd_snippet "$n"
}

cmd_start() {
    local n=${1:-} serve=1
    need_name "$n"
    [[ "${2:-}" == --no-serve ]] && serve=0
    load "$n" || die "설정이 없습니다 — pin-viewer add $n ..."
    if [[ "$(sysu is-active "$(unit_of "$n")" 2> /dev/null)" != active ]] && listening "$C_PORT"; then
        die "로컬 포트 $C_PORT 이 이미 쓰이고 있습니다 — 옛 유닛이 아직 도는가? (ss -ltnp 'sport = :$C_PORT')"
    fi
    start_instance "$n" "$serve"
    say "$(url_of "$C_TS_PORT")"
}

cmd_stop() {
    local n=${1:-}
    need_name "$n"
    sysu disable --now "$(unit_of "$n")" > /dev/null 2>&1 || warn "disable 실패: $(unit_of "$n")"
    say "$(unit_of "$n") 중지·비활성 (설정·포트 예약·serve 항목은 그대로 — 다시 켜기: pin-viewer start $n)"
}

cmd_update() {
    local from="" force=0 restart=1
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --from) from=${2:-}; shift 2 ;;
            --force) force=1; shift ;;
            --no-restart) restart=0; shift ;;
            *) die "모르는 인자: $1" ;;
        esac
    done
    [[ -n "$from" ]] || from=$(plugin_skill_dir)
    [[ -n "$from" ]] || die "플러그인 캐시에서 manuscript-pin-picker 를 찾지 못했습니다 — --from <스킬 폴더>"
    local old new
    old=$(app_sha "$APP_DIR" || true)
    new=$("$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()[:12])' "$from/scripts/pin_server.py" 2> /dev/null) \
        || die "pin_server.py 가 없습니다: $from/scripts"
    if [[ "$old" == "$new" && "$force" == 0 ]] \
        && diff -rq "$from/vendor/pdfjs" "$APP_DIR/vendor/pdfjs" > /dev/null 2>&1; then
        say "앱 사본이 이미 최신입니다 ($new, $from) — 재시작하지 않습니다(--force 로 강제)"
        return 0
    fi
    install_app "$from"
    say "앱 사본 ${old:-없음} → $new ($from)"
    [[ "$restart" == 1 ]] || return 0
    local n any=0
    for n in $(instances); do
        [[ "$(sysu is-active "$(unit_of "$n")" 2> /dev/null)" == active ]] || continue
        any=1
        load "$n" || continue
        sysu restart "$(unit_of "$n")" || {
            warn "재시작 실패: $(unit_of "$n")"
            continue
        }
        if wait_ready "$n" "$C_PORT"; then say "  $n 재시작 → 200"; else warn "  $n 재시작 뒤 응답 없음 — pin-viewer status $n"; fi
    done
    [[ "$any" == 1 ]] || say "켜진 인스턴스 없음"
}

cmd_list() {
    local n state code
    printf '%-14s %-16s %-6s %-6s %-9s %-5s %s\n' 이름 이름표 로컬 테일넷 상태 열린핀 원고
    for n in $(instances); do
        load "$n" || continue
        state=$(sysu is-active "$(unit_of "$n")" 2> /dev/null)
        [[ -n "$state" ]] || state="?"
        code=""
        [[ "$state" == active ]] && code=$(http_code "$C_PORT")
        [[ -n "$code" && "$code" != 200 ]] && state="$state/$code"
        printf '%-14s %-16s %-6s %-6s %-9s %-5s %s\n' "$n" "${C_LABEL:--}" "$C_PORT" "$C_TS_PORT" \
            "$state" "$(open_pins "$C_STATE_DIR")" "$C_MANUSCRIPT"
    done
}

cmd_status() {
    local names n
    if [[ -n "${1:-}" ]]; then
        need_name "$1"
        names=$1
    else
        names=$(instances)
    fi
    [[ -n "$names" ]] || {
        say "인스턴스 없음 — pin-viewer add <이름> --manuscript <원고 폴더>"
        return 0
    }
    say "앱 사본  $APP_DIR ($(app_sha "$APP_DIR" || echo 없음))"
    for n in $names; do
        load "$n" || die "설정이 없습니다: $n"
        local unit
        unit=$(unit_of "$n")
        say ""
        say "[$n] ${C_LABEL:-}"
        say "  유닛     $unit  $(sysu is-active "$unit" 2> /dev/null) / $(sysu is-enabled "$unit" 2> /dev/null)  pid=$(sysu show -p MainPID --value "$unit" 2> /dev/null)"
        say "  로컬     http://127.0.0.1:$C_PORT/  → $(http_code "$C_PORT")"
        say "  테일넷   $(url_of "$C_TS_PORT")  (serve: $(ts_proxy_of "$C_TS_PORT" | grep . || echo 없음))"
        say "  원고     $C_MANUSCRIPT/${C_MAIN:-(자동)}"
        say "  상태     $C_STATE_DIR  (열린 핀 $(open_pins "$C_STATE_DIR"))"
        say "  설정     $C_FILE"
        say "  로그     journalctl --user -u $unit · $C_STATE_DIR/build.log"
    done
}

cmd_url() {
    local n
    if [[ -n "${1:-}" ]]; then
        need_name "$1"
        load "$1" || die "설정이 없습니다: $1"
        url_of "$C_TS_PORT"
        printf '\n'
        return
    fi
    for n in $(instances); do
        load "$n" || continue
        printf '%-14s %s\n' "$n" "$(url_of "$C_TS_PORT")"
    done
}

cmd_snippet() {
    local n=${1:-}
    need_name "$n"
    load "$n" || die "설정이 없습니다: $n"
    local url origin
    url=$(url_of "$C_TS_PORT")
    url=${url%/}
    origin=$(git -C "$C_MANUSCRIPT" remote get-url origin 2> /dev/null || echo '(원고 폴더가 git 저장소가 아님)')
    cat << EOF
--- 이 논문 저장소의 AGENTS.md 에 붙일 조각 (pin-viewer snippet $n) ---
## 원고 핀 뷰어 (${C_LABEL:-$n})

- 뷰어: $url/ — 공저자가 PDF 에서 드래그해 수정할 자리를 핀으로 남긴다.
- 핀 목록: \`curl -s $url/pins.md\` (같은 기기에서는 \`curl -s http://127.0.0.1:$C_PORT/pins.md\`)
- **먼저 확인한다**: pins.md 머리의 저장소(원고 경로)가 이 체크아웃의 \`git remote get-url origin\` 과 같은지 본다.
  다르면 다른 논문의 뷰어다 — 처리하지 않는다. 이 뷰어의 원고 저장소: \`$origin\`
- 처리 분담: 부탁받은 쪽이 열린 핀을 **전부** 처리한다. 다른 쪽이 claim 한 핀(⏳)은 건너뛴다.
- 처리한 핀은 pins.md 머리의 안내대로 닫는다(무엇을 고쳤는지 reply, 커밋·PR 을 ref 로).
---
EOF
}

cmd_remove() {
    local n=${1:-}
    need_name "$n"
    load "$n" || die "설정이 없습니다: $n"
    local state=$C_STATE_DIR port=$C_PORT ts=$C_TS_PORT
    sysu disable --now "$(unit_of "$n")" > /dev/null 2>&1 || true
    say "$(unit_of "$n") 중지·비활성"
    [[ -n "$ts" && -n "$port" ]] && serve_off "$ts" "$port"
    # 설정 = 포트 예약이다. 홈 링크와 그 원본(링크가 가리키는 파일 — 다른 체크아웃일 수도
    # 있다)을 함께 지워야 장부에서 빠진다.
    local f targets=()
    if [[ -L "$(conf_of "$n")" ]]; then
        f=$(readlink "$(conf_of "$n")")
        [[ "$(basename "$f")" == "$n.env" && -f "$f" ]] && targets+=("$f")
    fi
    [[ -e "$(conf_of "$n")" || -L "$(conf_of "$n")" ]] && targets+=("$(conf_of "$n")")
    [[ -f "$(src_of "$n")" ]] && targets+=("$(src_of "$n")")
    for f in "${targets[@]+"${targets[@]}"}"; do
        [[ -e "$f" || -L "$f" ]] || continue
        rm -f "$f" && say "설정 삭제: $f"
        case "$f" in
            */machines/*/pin-viewer/"$n".env)
                say "  dotfiles 에서 이 삭제를 커밋하세요: git -C ${f%/machines/*} add -u machines/${f#*/machines/}"
                ;;
        esac
    done
    ledger_refresh && say "포트 예약 해제: $port/$ts (장부 $LEDGER)"
    sysu reset-failed "$(unit_of "$n")" > /dev/null 2>&1 || true
    say "상태 폴더는 지우지 않았습니다: $state"
}

usage() { sed -n '/^# Usage:/,/^# 보안 규칙/p' "$_SELF" | sed -e '$d' -e 's/^# \{0,1\}//'; }

main() {
    local c=${1:-}
    [[ $# -gt 0 ]] && shift
    case "$c" in
        add) cmd_add "$@" ;;
        start) cmd_start "$@" ;;
        stop) cmd_stop "$@" ;;
        update) cmd_update "$@" ;;
        list | ls) cmd_list ;;
        status) cmd_status "$@" ;;
        url) cmd_url "$@" ;;
        snippet) cmd_snippet "$@" ;;
        remove | rm) cmd_remove "$@" ;;
        run) cmd_run "$@" ;;
        -h | --help | help | "") usage ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
}
main "$@"
