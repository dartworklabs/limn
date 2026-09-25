#!/usr/bin/env bash
# Limn 인스턴스 관리 — 원고(논문)마다 `limn@<이름>.service` 인스턴스 하나를 띄우고 관리한다.
#
# 논문마다 저장소가 따로이고, 두 논문을 동시에 작업하면 Limn 도 동시에 따로 돌아야 한다.
# 그래서 인스턴스마다 포트·상태 폴더(핀·빌드·build.log)·journal 이 갈리고, 설치된 limn
# 패키지 하나를 함께 쓴다. 구조와 절차는 docs/instances.md.
#
# 이 스크립트는 `limn` 명령(limn.cli)이 부른다. 직접 부르지 않는다 — cli 가 서버 경로·파이썬·
# 판 번호를 LIMN_SERVER·LIMN_PYTHON·LIMN_VERSION 으로 넘겨 준다.
#
# Usage:
#   limn add <이름> --manuscript <원고 폴더> [--main <파일.tex>] [--port N] [--ts-port N]
#                  [--git-pull] [--label <이름표>] [--accent <#rrggbb>] [--state-dir <폴더>]
#                  [--extra "<서버 인자>"] [--no-serve] [--no-start]
#                  [--doc <키>=<표시 이름>:<경로> ...]   (--main 과 함께 쓰지 않는다. §여러 문서)
#                  [--stage auto|initial|revision]        (--doc/--main 없이 자동 탐지할 때만. §기본 탭 자동 탐지)
#
# 기본 탭 자동 탐지: --doc 도 --main 도 안 주면, 원고 폴더가 표준 paper-repo 구조
# (manuscript/<라운드>/<본문>.tex, submission/{highlights,cover_letter,review_response}/*.tex)면
# ms=본문(최신 라운드) · rr=답변서(revision 단계·파일 있을 때만) · hl=하이라이트 · cl=커버레터
# 순서로 DOCS 를 만든다. --stage 기본은 auto(<원고 폴더>/reviews/ 있으면 revision). 구조가 아니면
# 단일 MAIN 탐지로 물러난다.
#   limn doc suggest --manuscript <원고 폴더> [--stage auto|initial|revision]
#                                          위 자동 탐지가 고를 DOCS 문자열만 찍는다(읽기 전용)
#   limn start <이름> [--no-serve]         설정이 이미 있는 인스턴스를 켠다(재부팅 뒤·새 기기·전환)
#   limn stop <이름>                       유닛만 끈다(설정·포트·serve 항목은 그대로)
#   limn update [--ref <태그|브랜치>] [--from <설치 원본>] [--dry-run] [--force] [--no-restart]
#                                          limn 을 다시 설치(uv tool)하고 켜진 인스턴스를 재시작
#   limn list                              인스턴스 표(이름표·포트·상태·열린 핀·문서 수·원고)
#   limn status [<이름>]                   자세히(문서 목록 포함)
#   limn url [<이름>]                      테일넷 주소
#   limn snippet <이름>                    그 논문 저장소 AGENTS.md 에 붙일 안내 조각(출력만)
#   limn doc list <이름>                            문서 키·이름·경로 표
#   limn doc add <이름> --doc '<키>=<이름>:<경로>' [--doc …] [--restart]
#                                          기존 인스턴스에 문서를 더한다. 단일 문서(MAIN)였다면
#                                          본문을 첫 항목 main=본문:<MAIN> 으로 바꿔 DOCS 로 옮긴다
#   limn doc remove <이름> <키> [--restart]   DOCS 에서 문서 하나를 뺀다(마지막 문서는 거부)
#   limn remove <이름>                     유닛 중지·비활성, serve 해제, 설정(=포트 예약) 삭제.
#                                          상태 폴더는 지우지 않는다
#   limn run <이름>                        (유닛 전용) 설정을 읽어 서버로 exec
#
# 여러 문서(--doc, DOCS=): 인스턴스 하나로 본문·답변서·보기 전용 PDF 등을 탭으로 전환한다. 형식은
# <키>=<표시 이름>:<경로>. 키는 [a-z0-9-]{1,24} 중복 금지, 문서는 12개까지, 경로는 --manuscript
# 안이어야 한다. `<빌드 루트>::<메인.tex>` 는 복사 범위를 빌드 루트로 넓히는 확장 표기(LaTeX 전용).
# 설정 파일에는 DOCS="<키1>=<이름1>:<경로1>;<키2>=..." 로 쓴다(`;` 로 나눔). MAIN 과 DOCS 는
# 함께 쓰지 않는다 — 자세한 계약은 docs/operations.md §여러 문서.
#
# 보안 규칙(바꾸지 말 것): 바인딩은 127.0.0.1 뿐(서버에 박혀 있다), 노출은 `tailscale serve`
# 만, funnel 은 절대 쓰지 않는다, sudo 를 부르지 않는다. tailscale operator 가 이 사용자여야
# serve 가 sudo 없이 걸린다 — 안 걸리면 오류를 보이고 멈춘다(권한을 스스로 바꾸지 않는다).

set -uo pipefail
unset CDPATH

# ── 경로 (LIMN_* 로 덮을 수 있다 — 테스트가 홈을 건드리지 않게) ──
_XDG_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
_XDG_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DATA_ROOT="${LIMN_DATA_ROOT:-$_XDG_DATA/limn}"
CONFIG_DIR="${LIMN_CONFIG_DIR:-$_XDG_CONFIG/limn}"
# 설정 원본 폴더(선택). 설정을 다른 저장소(예: dotfiles)에서 버전 관리하면 거기를 가리킨다 —
# add 가 원본을 거기에 쓰고 CONFIG_DIR 에는 심링크를 건다. 비우면 CONFIG_DIR 에 바로 쓴다.
SOURCE_DIR="${LIMN_SOURCE_DIR:-$CONFIG_DIR}"
USER_UNIT_DIR="${LIMN_USER_UNIT_DIR:-$_XDG_CONFIG/systemd/user}"
# 포트 장부(선택). 이 기기의 다른 서빙 유닛이 광고하는 포트를 적은 파일로, 있으면 읽어서 피한다.
# LIMN_LEDGER_GEN 에 생성기(<유닛 폴더> <설정 폴더...> 를 받아 "<포트> <유닛>" 줄을 찍는 스크립트)를
# 주면 add·remove 뒤에 장부를 다시 만든다. 없으면 장부를 쓰지 않는다(남의 파일을 반쪽으로 덮지 않게).
LEDGER="${LIMN_LEDGER:-$_XDG_CONFIG/served/reserved-ports.txt}"
LEDGER_GEN="${LIMN_LEDGER_GEN:-}"
LEDGER_UNITS_DIR="${LIMN_LEDGER_UNITS_DIR:-$USER_UNIT_DIR}"
# 자동 배정 대역: 테일넷 포트 N 에 로컬 포트 N+100 을 짝짓는다(18004↔18104) — 주소만 보고도 짝을 안다.
TS_MIN="${LIMN_TS_MIN:-18005}"
TS_MAX="${LIMN_TS_MAX:-18099}"
LOCAL_OFFSET="${LIMN_LOCAL_OFFSET:-100}"
# 여러 문서(--doc/DOCS=) 제약. 서버(limn/server.py) 쪽 DOC_KEY_RE·DOCS_MAX·DOC_NAME_MAX 와 맞춘다.
DOCS_MAX=12
DOC_NAME_MAX=40
# cli 가 넘긴다: 설치된 limn 의 파이썬·서버·유닛 템플릿·실행 파일·판 번호.
PYTHON="${LIMN_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
    if [[ -x /usr/bin/python3 ]]; then PYTHON=/usr/bin/python3; else PYTHON=$(command -v python3 || true); fi
fi
_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="${LIMN_SERVER:-$_HERE/server.py}"
UNIT_TEMPLATE="${LIMN_UNIT_TEMPLATE:-$_HERE/systemd/limn@.service}"
LIMN_BIN="${LIMN_BIN:-$(command -v limn || printf '%s' "$HOME/.local/bin/limn")}"
VERSION="${LIMN_VERSION:-?}"
# update 가 다시 설치할 원본(uv tool install 이 받는 형식). --ref 가 붙으면 @<ref> 를 더한다.
REPO="${LIMN_REPO:-git+ssh://git@github.com/dartworklabs/limn}"
UV="${LIMN_UV:-uv}"
WAIT_S="${LIMN_WAIT:-240}"

die() {
    printf 'limn: %s\n' "$*" >&2
    exit 1
}
say() { printf '%s\n' "$*"; }
warn() { printf 'limn: 경고: %s\n' "$*" >&2; }

unit_of() { printf 'limn@%s.service' "$1"; }

# systemctl --user. SSH·비로그인 셸은 user manager 가 살아 있어도 bus 환경변수를 물려받지 못할 수
# 있다 — loginctl 의 RuntimePath(없으면 /run/user/<uid>)로 bus 주소를 복원한다.
sysu() {
    local runtime_dir="${XDG_RUNTIME_DIR:-}" user_id
    if [[ -z "$runtime_dir" ]]; then
        user_id=$(id -u)
        if command -v loginctl > /dev/null 2>&1; then
            runtime_dir=$(loginctl show-user "$user_id" -p RuntimePath --value 2> /dev/null) || runtime_dir=""
        fi
        [[ -z "$runtime_dir" && -d "/run/user/$user_id" ]] && runtime_dir="/run/user/$user_id"
    fi
    if [[ -n "$runtime_dir" ]]; then
        XDG_RUNTIME_DIR="$runtime_dir" \
            DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$runtime_dir/bus}" \
            systemctl --user "$@"
        return
    fi
    systemctl --user "$@"
}

valid_name() {
    [[ "$1" =~ ^[a-z0-9][a-z0-9-]*$ ]] || return 1
    # `serve` 는 `limn serve` 가 상태 폴더를 두는 DATA_ROOT/serve 와 겹친다(기본 상태 폴더가 DATA_ROOT/<이름> 이다).
    [[ "$1" != serve ]]
}
need_name() {
    [[ -n "${1:-}" ]] || die "이름이 필요합니다"
    valid_name "$1" || die "이름은 [a-z0-9-]+ (첫 글자는 영숫자, 'serve' 는 예약) 만 받습니다: '$1'"
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
    C_DOCS=$(env_get "$f" DOCS)
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

# ── 여러 문서 (--doc / DOCS=) ──
# 형식은 <키>=<표시 이름>:<경로>. 파싱·검증 규칙은 서버(limn/server.py 의 parse_doc_arg·make_docs)
# 와 맞춘다 — 기동 시 서버가 다시 검증하지만, 여기서 먼저 걸러야 systemd Restart 루프 대신
# `limn add`/`limn doc add` 시점에 분명한 오류로 멈춘다.
join_semi() { local IFS=';'; printf '%s' "$*"; } # join_semi <항목...> -> ';' 로 이은 문자열
valid_doc_key() { # [a-z0-9-]{1,24}
    [[ "$1" =~ ^[a-z0-9-]+$ ]] || return 1
    local len=${#1}
    ((len >= 1 && len <= 24))
}

# doc_parse_kv <spec> — 성공하면 전역 DOC_KEY/DOC_NAME/DOC_PATH 를 채운다. 실패하면 die.
doc_parse_kv() {
    local spec=$1 rest
    [[ "$spec" == *=* ]] || die "--doc 는 <키>=<표시 이름>:<경로> 형식입니다: $spec"
    DOC_KEY=${spec%%=*}
    rest=${spec#*=}
    valid_doc_key "$DOC_KEY" || die "--doc 키는 [a-z0-9-]{1,24} 여야 합니다: $DOC_KEY"
    [[ "$rest" == *:* ]] || die "--doc $DOC_KEY: 표시 이름과 경로 사이에 ':' 가 없습니다: $spec"
    DOC_NAME=${rest%%:*}
    DOC_PATH=${rest#*:}
    [[ -n "$DOC_NAME" ]] || die "--doc $DOC_KEY: 표시 이름이 비었습니다"
    ((${#DOC_NAME} <= DOC_NAME_MAX)) || die "--doc $DOC_KEY: 표시 이름은 ${DOC_NAME_MAX}자 이하여야 합니다: $DOC_NAME"
    [[ -n "$DOC_PATH" ]] || die "--doc $DOC_KEY: 경로가 비었습니다"
}

# doc_check_path <원고 절대경로> — doc_parse_kv 가 채운 DOC_KEY/DOC_PATH 를 읽어 경로를 검증한다.
# `::` 표기(<빌드 루트>::<메인.tex>)는 빌드 루트·메인 둘 다 원고 폴더 안에 있는지 본다. `../` 로
# 원고 밖을 가리키는 문자열은 단순 접두어 비교로는 못 잡으므로(`$ms/../x` 도 문자열로는 `$ms/`
# 로 시작한다) `cd .. && pwd -P` 로 정규화한 뒤 비교한다 — manuscript 인자 자체를 정규화하는
# cmd_add 의 `pwd -P` 관례와 같다.
doc_check_path() {
    local ms=$1 path=$DOC_PATH key=$DOC_KEY root="" root_c="" main="" main_c=""
    if [[ "$path" == *::* ]]; then
        local root_s=${path%%::*} main_s=${path#*::}
        [[ "$main_s" != *::* ]] || die "--doc $key: 확장 표기는 <빌드 루트>::<메인.tex> 하나입니다: $path"
        [[ -n "$root_s" && -n "$main_s" ]] || die "--doc $key: 확장 표기 형식 오류(빌드 루트나 메인이 비었습니다): $path"
        if [[ "$root_s" == /* ]]; then root="$root_s"; else root="$ms/$root_s"; fi
        [[ -d "$root" ]] || die "--doc $key: 빌드 루트 폴더가 없습니다: $root"
        root_c=$(cd "$root" && pwd -P) || die "--doc $key: 빌드 루트 경로를 확인하지 못했습니다: $root"
        case "$root_c" in
            "$ms"/* | "$ms") ;;
            *) die "--doc $key: 빌드 루트가 --manuscript($ms) 밖입니다: $root_c" ;;
        esac
        [[ "$main_s" != /* ]] || die "--doc $key: '::' 뒤 메인은 빌드 루트 기준 상대경로여야 합니다: $main_s"
        main="$root_c/$main_s"
        case "${main##*.}" in
            tex) ;;
            *) die "--doc $key: '::' 표기는 LaTeX 문서(.tex)에만 씁니다: $main" ;;
        esac
    else
        if [[ "$path" == /* ]]; then main="$path"; else main="$ms/$path"; fi
        case "${main##*.}" in
            tex | pdf) ;;
            *) die "--doc $key: .tex(LaTeX) 또는 .pdf(보기 전용)만 받습니다: $main" ;;
        esac
    fi
    [[ -f "$main" ]] || die "--doc $key: 파일이 없습니다: $main"
    main_c="$(cd "$(dirname "$main")" && pwd -P)/$(basename "$main")" || die "--doc $key: 경로를 확인하지 못했습니다: $main"
    case "$main_c" in
        "$ms"/*) ;;
        *) die "--doc $key: 경로가 --manuscript($ms) 밖입니다: $main_c" ;;
    esac
    if [[ -n "$root_c" ]]; then
        case "$main_c" in
            "$root_c"/*) ;;
            *) die "--doc $key: 메인이 빌드 루트($root_c) 밖입니다: $main_c" ;;
        esac
    fi
}

# validate_doc_specs <원고 절대경로> <spec...> — 개수·키 중복·형식·경로를 전부 검증한다. 문제가
# 있으면 die 로 즉시 멈춘다(설정을 쓰기 전에 걸러야 한다).
validate_doc_specs() {
    local ms=$1
    shift
    local n=$#
    ((n > 0)) || die "--doc 가 최소 1개 필요합니다"
    ((n <= DOCS_MAX)) || die "--doc 는 ${DOCS_MAX}개까지입니다(지금 ${n}개)"
    local seen=" " spec
    for spec in "$@"; do
        doc_parse_kv "$spec"
        case "$seen" in
            *" $DOC_KEY "*) die "--doc 키가 겹칩니다: $DOC_KEY" ;;
        esac
        seen="$seen$DOC_KEY "
        doc_check_path "$ms"
    done
}

doc_count() { # doc_count <DOCS 문자열> -> 문서 개수(비어 있으면 단일 문서라 1)
    local d=$1
    [[ -n "$d" ]] || {
        printf 1
        return
    }
    local specs=()
    IFS=';' read -ra specs <<< "$d"
    printf '%d' "${#specs[@]}"
}
doc_keys() { # doc_keys <DOCS 문자열> -> 콤마로 이은 키 목록("main" = 단일 문서)
    local d=$1
    [[ -n "$d" ]] || {
        printf main
        return
    }
    local specs=() spec out=""
    IFS=';' read -ra specs <<< "$d"
    for spec in "${specs[@]}"; do
        doc_parse_kv "$spec"
        [[ -z "$out" ]] || out+=","
        out+="$DOC_KEY"
    done
    printf '%s' "$out"
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
# 포트 예약의 원본은 인스턴스 설정 파일(PORT=·TS_PORT=)이다. 장부 파일(LEDGER)은 이 기기의 다른
# 서빙 유닛이 광고하는 포트를 알려 주는 보조 자료다 — 있으면 읽고, 생성기(LEDGER_GEN)가 있을 때만
# 다시 만든다. 장부를 손으로 쓰지 않는다.
own_port_lines() { # 인스턴스 설정의 포트 → "<포트> limn@<이름>"
    local n
    for n in $(instances); do
        load "$n" || continue
        [[ -n "$C_PORT" ]] && printf '%s limn@%s\n' "$C_PORT" "$n"
        [[ -n "$C_TS_PORT" ]] && printf '%s limn@%s\n' "$C_TS_PORT" "$n"
    done
    return 0
}
ledger_lines() {
    {
        if [[ -n "$LEDGER_GEN" ]]; then
            local extra=("$CONFIG_DIR")
            [[ "$SOURCE_DIR" != "$CONFIG_DIR" && -d "$SOURCE_DIR" ]] && extra+=("$SOURCE_DIR")
            local units=$LEDGER_UNITS_DIR tmp=""
            if [[ ! -d "$units" ]]; then tmp=$(mktemp -d) && units=$tmp; fi
            "$LEDGER_GEN" "$units" "${extra[@]}"
            [[ -n "$tmp" ]] && rmdir "$tmp"
        elif [[ -f "$LEDGER" ]]; then
            grep -vE '^[[:space:]]*(#|$)' "$LEDGER"
        fi
        own_port_lines
    } | sort -k1,1n -k2,2 | uniq
    return 0
}
ledger_refresh() { # 생성기가 있을 때만 장부를 다시 만든다. 없으면 할 일이 없다(설정 파일이 곧 예약).
    [[ -n "$LEDGER_GEN" ]] || return 0
    mkdir -p "$(dirname "$LEDGER")" || return 1
    local t
    t=$(mktemp "$(dirname "$LEDGER")/.limn-ledger.XXXXXX") || return 1
    if "$LEDGER_GEN" "$LEDGER_UNITS_DIR" "$CONFIG_DIR" > "$t"; then
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
    who=$(awk -v p="$p" -v me="limn@$me" '$1 == p && $2 != me { print $2; exit }' <<< "${_SNAP_LEDGER:-}")
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

# ── 유닛 템플릿 ──
# 패키지에 든 limn@.service 를 이 기기에 맞게 채워 USER_UNIT_DIR 에 쓴다(심링크가 아니라 사본 — uv 가
# 도구를 다시 설치하면 패키지 경로가 바뀔 수 있다). 채우는 자리: 실행 파일(@LIMN_BIN@), 설정 폴더
# (@LIMN_CONFIG_DIR@), 유닛의 PATH(@LIMN_PATH@ — systemd 는 셸 rc 를 거치지 않아 TeX 경로를 못 물려받는다).
unit_path() {
    if [[ -n "${LIMN_UNIT_PATH:-}" ]]; then
        printf '%s' "$LIMN_UNIT_PATH"
        return
    fi
    local out="" d tex
    tex=$(command -v pdflatex 2> /dev/null || true)
    for d in ${tex:+"$(dirname "$tex")"} /usr/local/bin /usr/bin /bin; do
        case ":$out:" in *":$d:"*) continue ;; esac
        out="${out:+$out:}$d"
    done
    printf '%s' "$out"
}
render_unit() {
    [[ -f "$UNIT_TEMPLATE" ]] || die "유닛 템플릿이 없습니다: $UNIT_TEMPLATE"
    local bin=$LIMN_BIN cfg=$CONFIG_DIR path
    path=$(unit_path)
    awk -v bin="$bin" -v cfg="$cfg" -v path="$path" '
        { gsub(/@LIMN_BIN@/, bin); gsub(/@LIMN_CONFIG_DIR@/, cfg); gsub(/@LIMN_PATH@/, path); print }' "$UNIT_TEMPLATE"
}
ensure_unit() {
    local dst="$USER_UNIT_DIR/limn@.service" want
    want=$(render_unit) || exit 1
    mkdir -p "$USER_UNIT_DIR" || die "폴더를 만들지 못했습니다: $USER_UNIT_DIR"
    if [[ -e "$dst" || -L "$dst" ]]; then
        [[ ! -L "$dst" ]] && grep -q '^# limn:generated' "$dst" \
            || die "$dst 는 limn 이 만든 파일이 아닙니다 — 손으로 확인하세요"
        [[ "$(cat "$dst")" == "$want" ]] && return 0
    fi
    printf '%s\n' "$want" > "$dst" || die "유닛을 쓰지 못했습니다: $dst"
    say "유닛 템플릿 설치: $dst"
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

# detect_round <manuscript/ 폴더> — 맨 앞 숫자가 가장 큰 하위 폴더 이름(1st, 2nd, 3rd, ...)을
# 고른다. 숫자로 시작하지 않는 폴더(`changes` 등)는 무시한다. 없으면 실패.
detect_round() {
    local mdir=$1 d base n best="" bestn=-1
    for d in "$mdir"/*/; do
        [[ -d "$d" ]] || continue
        base=$(basename "$d")
        [[ "$base" =~ ^([0-9]+) ]] || continue
        n=${BASH_REMATCH[1]}
        if ((10#$n > bestn)); then
            bestn=$((10#$n))
            best=$base
        fi
    done
    [[ -n "$best" ]] || return 1
    printf '%s' "$best"
}

# git_commit_time <파일> — 그 파일이 속한 git 저장소에서 가장 최근 커밋의 커밋 시각(unix epoch)을
# 찍는다. git 이 없거나, 저장소 밖이거나, 추적되지 않은 파일이면 아무 것도 찍지 않고 실패한다
# (mtime 은 fresh clone·checkout 에서 리셋되거나 동시에 찍혀 신뢰할 수 없다 — git log 가 우선).
git_commit_time() {
    local f=$1 dir t
    command -v git > /dev/null 2>&1 || return 1
    dir=$(dirname "$f")
    git -C "$dir" rev-parse --is-inside-work-tree > /dev/null 2>&1 || return 1
    t=$(git -C "$dir" log -1 --format=%ct -- "$(basename "$f")" 2> /dev/null) || return 1
    [[ -n "$t" ]] || return 1
    printf '%s' "$t"
}
# file_mtime <파일> — 수정 시각(unix epoch). GNU(stat -c)·BSD/macOS(stat -f) 둘 다 시도한다.
file_mtime() { stat -c %Y "$1" 2> /dev/null || stat -f %m "$1" 2> /dev/null; }

# detect_main_for_round <라운드 폴더> — detect_main 을 그대로 쓰되, 후보가 여럿이면(같은 라운드
# 폴더에 독립된 \documentclass 를 가진 선행 논문 원문이 남아 있는 경우 등) git 커밋 시각이 가장
# 최근인 파일을 고른다(파일이 git 밖이거나 추적되지 않으면 mtime 으로 물러난다). 시각까지 같으면
# 추측하지 않고 die 로 멈춘다 — 후보 목록을 보여주고 --doc 를 안내한다. 후보가 0개면 그대로
# 실패(비표준 레이아웃으로 취급해 상위에서 옛 탐지로 물러난다).
detect_main_for_round() {
    local d=$1 out cands=() f
    out=$(detect_main "$d" 2> /dev/null) && {
        printf '%s' "$out"
        return 0
    }
    for f in "$d"/*.tex; do
        [[ -f "$f" ]] && grep -qE '^[^%]*\\documentclass' "$f" && cands+=("$f")
    done
    ((${#cands[@]} > 0)) || return 1
    if ((${#cands[@]} == 1)); then
        printf '%s' "$(basename "${cands[0]}")"
        return 0
    fi
    local times=() t i best_t=-1 best_i=-1 tie=0
    for f in "${cands[@]}"; do
        t=$(git_commit_time "$f")
        [[ -n "$t" ]] || t=$(file_mtime "$f")
        [[ -n "$t" ]] || t=-1
        times+=("$t")
    done
    for ((i = 0; i < ${#cands[@]}; i++)); do
        t=${times[$i]}
        if ((t > best_t)); then
            best_t=$t
            best_i=$i
            tie=0
        elif ((t == best_t)); then
            tie=1
        fi
    done
    if ((tie == 1)); then
        local names=() nf
        for nf in "${cands[@]}"; do names+=("$(basename "$nf")"); done
        die "$(basename "$d")/ 안에 \\documentclass 후보가 여럿이고(git 커밋·수정 시각까지 같아) 자동으로 고르지 못했습니다 — --doc 로 지정하세요: $(IFS=,; printf '%s' "${names[*]}")"
    fi
    printf '%s' "$(basename "${cands[$best_i]}")"
}

# detect_docs_layout <원고 절대경로> <stage: auto|initial|revision> — 표준 paper-repo 레이아웃
# (`manuscript/<라운드>/<본문>.tex` + `submission/{highlights,cover_letter,review_response}/*.tex`)
# 이면 전역 배열 DETECTED_DOCS(--doc 스펙과 같은 형식)를 고정 순서(ms·rr·hl·cl)로 채우고 0을
# 돌려준다. `rr`(답변서)은 revision 단계에서만, 그리고 파일이 실제로 있을 때만 넣는다. 라운드
# 폴더나 본문을 못 찾으면(비표준 레이아웃) 아무 것도 채우지 않고 1을 돌려준다 — 호출부가 옛
# 단일 MAIN 탐지로 대체한다.
detect_docs_layout() {
    local ms=$1 stage=${2:-auto} mdir round main
    DETECTED_DOCS=()
    mdir="$ms/manuscript"
    [[ -d "$mdir" ]] || return 1
    round=$(detect_round "$mdir") || return 1
    main=$(detect_main_for_round "$mdir/$round") || return 1
    DETECTED_DOCS+=("ms=본문:manuscript::$round/$main")
    case "$stage" in
        auto)
            if [[ -d "$ms/reviews" ]]; then stage=revision; else stage=initial; fi
            ;;
        initial | revision) ;;
        *) die "--stage 는 auto|initial|revision 입니다: $stage" ;;
    esac
    if [[ "$stage" == revision && -f "$ms/submission/review_response/review_response.tex" ]]; then
        DETECTED_DOCS+=("rr=답변서:submission/review_response/review_response.tex")
    fi
    [[ -f "$ms/submission/highlights/highlights.tex" ]] && DETECTED_DOCS+=("hl=하이라이트:submission/highlights/highlights.tex")
    [[ -f "$ms/submission/cover_letter/cover_letter.tex" ]] && DETECTED_DOCS+=("cl=커버레터:submission/cover_letter/cover_letter.tex")
    return 0
}

with_lock() { # 포트 고르기~설정 쓰기를 동시 add 끼리 겹치지 않게
    mkdir -p "$CONFIG_DIR"
    if command -v flock > /dev/null 2>&1; then
        exec 9> "$CONFIG_DIR/.lock"
        flock -w 30 9 || die "다른 limn 가 잠금을 쥐고 있습니다: $CONFIG_DIR/.lock"
    fi
}

# ─────────────────────────────── 명령 ───────────────────────────────

cmd_run() {
    local n=${1:-}
    need_name "$n"
    load "$n" || die "설정이 없습니다: $(conf_of "$n")"
    [[ -f "$SERVER" ]] || die "limn 서버를 찾지 못했습니다: $SERVER — limn 을 다시 설치하세요"
    [[ -n "$C_MANUSCRIPT" && -d "$C_MANUSCRIPT" ]] || die "MANUSCRIPT 폴더가 없습니다: '$C_MANUSCRIPT'"
    [[ -z "$C_DOCS" || -z "$C_MAIN" ]] || die "설정 오류: MAIN 과 DOCS 를 함께 쓸 수 없습니다: $C_FILE"
    [[ -z "$C_MAIN" || -f "$C_MANUSCRIPT/$C_MAIN" ]] || die "MAIN 파일이 없습니다: $C_MANUSCRIPT/$C_MAIN"
    valid_port "${C_PORT:-x}" || die "PORT 가 없거나 잘못됐습니다: '$C_PORT' (자동 선택에 맡기지 않는다 — 광고한 주소가 깨진다)"
    [[ -z "$C_ACCENT" || "$C_ACCENT" =~ ^#[0-9a-fA-F]{6}$ ]] || die "ACCENT 는 #rrggbb 형식입니다: '$C_ACCENT'"
    local args=(--manuscript "$C_MANUSCRIPT" --port "$C_PORT" --state-dir "$C_STATE_DIR")
    if [[ -n "$C_DOCS" ]]; then
        local doc_specs=() d
        IFS=';' read -ra doc_specs <<< "$C_DOCS"
        validate_doc_specs "$C_MANUSCRIPT" "${doc_specs[@]}"
        for d in "${doc_specs[@]}"; do args+=(--doc "$d"); done
    else
        [[ -n "$C_MAIN" ]] && args+=(--main "$C_MAIN")
    fi
    [[ "$C_GIT_PULL" == 1 ]] && args+=(--git-pull)
    [[ -n "$C_LABEL" ]] && args+=(--label "$C_LABEL")
    [[ -n "$C_ACCENT" ]] && args+=(--accent "$C_ACCENT")
    if [[ -n "$C_EXTRA_ARGS" ]]; then
        local extra
        read -r -a extra <<< "$C_EXTRA_ARGS"
        args+=("${extra[@]}")
    fi
    mkdir -p "$C_STATE_DIR" || die "상태 폴더를 만들지 못했습니다: $C_STATE_DIR"
    if [[ "${LIMN_PRINT_ARGV:-0}" == 1 ]]; then
        printf '%s\n' "$PYTHON" "$SERVER" "${args[@]}"
        return 0
    fi
    exec "$PYTHON" "$SERVER" "${args[@]}"
}

start_instance() { # start_instance <이름> <serve 0|1>
    local n=$1 serve=$2 rc=0
    ensure_conf_link "$n"
    load "$n" || die "설정을 읽지 못했습니다: $n"
    ensure_unit
    sysu enable "$(unit_of "$n")" > /dev/null 2>&1 || die "enable 실패: $(unit_of "$n")"
    sysu start "$(unit_of "$n")" || die "start 실패: journalctl --user -u $(unit_of "$n")"
    say "$(unit_of "$n") 기동 — 127.0.0.1:$C_PORT 응답 대기(첫 기동은 빌드까지 기다린다, 최대 ${WAIT_S}s)"
    wait_ready "$n" "$C_PORT" || rc=$?
    case $rc in
        0) say "127.0.0.1:$C_PORT 200" ;;
        2) die "유닛이 실패했습니다: journalctl --user -u $(unit_of "$n") -n 50" ;;
        *) warn "아직 200 이 아닙니다(빌드 중일 수 있음) — limn status $n" ;;
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
    local docs=() stage=auto
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --manuscript) manuscript=${2:-}; shift 2 ;;
            --main) main=${2:-}; shift 2 ;;
            --doc) docs+=("${2:-}"); shift 2 ;;
            --stage) stage=${2:-}; shift 2 ;;
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
    [[ -z "$main" || ${#docs[@]} -eq 0 ]] || die "--main 과 --doc 는 함께 쓸 수 없습니다"
    if [[ ${#docs[@]} -gt 0 ]]; then
        [[ "$stage" == auto ]] || die "--stage 는 --doc/--main 없이 자동 탐지할 때만 씁니다"
        validate_doc_specs "$manuscript" "${docs[@]}"
    elif [[ -n "$main" ]]; then
        [[ "$stage" == auto ]] || die "--stage 는 --doc/--main 없이 자동 탐지할 때만 씁니다"
        [[ "$main" != */* && -f "$manuscript/$main" ]] || die "메인 .tex 가 원고 폴더 맨 위에 없습니다: $manuscript/$main"
    elif detect_docs_layout "$manuscript" "$stage"; then
        docs=("${DETECTED_DOCS[@]}")
        validate_doc_specs "$manuscript" "${docs[@]}"
        say "자동 탐지 문서:"
        local d
        for d in "${docs[@]}"; do say "  $d"; done
    else
        main=$(detect_main "$manuscript") || die "메인 .tex 자동 탐지 실패"
    fi
    [[ -z "$accent" || "$accent" =~ ^#[0-9a-fA-F]{6}$ ]] || die "--accent 는 #rrggbb 형식입니다: $accent"
    [[ -n "$label" ]] || label=$(default_label "$manuscript")
    [[ -n "$label" ]] || label=$n
    ((${#label} <= 40)) || die "--label 은 40자 이하: $label"
    [[ -n "$state" ]] || state="$DATA_ROOT/$n"
    local docs_str=""
    ((${#docs[@]} == 0)) || docs_str=$(join_semi "${docs[@]}")
    local v
    for v in "$manuscript" "$main" "$label" "$state" "$extra_args" "$docs_str"; do
        safe_value "$v" || die "설정 파일에 쓸 수 없는 문자(따옴표·역슬래시·\$·백틱·줄바꿈)가 있습니다: $v"
    done
    [[ "$state" == /* ]] || die "--state-dir 는 절대경로여야 합니다: $state"

    with_lock
    snapshot_ports
    [[ -e "$(conf_of "$n")" || -e "$(src_of "$n")" ]] \
        && die "'$n' 설정이 이미 있습니다 — 다시 켜려면 limn start $n, 새로 만들려면 먼저 remove"
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
        printf '# limn@%s — `limn add` 가 %s 에 만들었다. 형식·키는 README 참고.\n' "$n" "$(date +%F)"
        printf '# 셸로 source 하지 않는다 — 값에 셸 문법을 쓰지 말 것.\n'
        emit LABEL "$label"
        emit ACCENT "$accent"
        emit MANUSCRIPT "$manuscript"
        emit MAIN "$main"
        emit DOCS "$docs_str"
        emit PORT "$port"
        emit TS_PORT "$ts"
        emit STATE_DIR "$state"
        emit GIT_PULL "$gitpull"
        emit EXTRA_ARGS "$extra_args"
    } > "$(src_of "$n")" || die "설정을 쓰지 못했습니다: $(src_of "$n")"
    if [[ "$SOURCE_DIR" != "$CONFIG_DIR" ]]; then
        mkdir -p "$CONFIG_DIR" && ln -sfn "$(src_of "$n")" "$(conf_of "$n")"
    fi
    ledger_refresh
    say "설정  $(src_of "$n")"
    [[ "$SOURCE_DIR" == "$CONFIG_DIR" ]] || say "링크  $(conf_of "$n") → 원본"
    say "포트  로컬 127.0.0.1:$port · 테일넷 :$ts (설정 파일이 곧 예약)"
    exec 9>&- # 잠금 해제 — 기동 대기(최대 수 분) 동안 다른 add 를 막지 않는다

    if [[ "$start" == 1 ]]; then
        start_instance "$n" "$serve"
    else
        say "켜지 않았습니다 — limn start $n"
    fi
    if [[ "$SOURCE_DIR" != "$CONFIG_DIR" ]]; then
        say ""
        say "설정 원본은 $SOURCE_DIR 에 있습니다 — 그 저장소에서 커밋하세요: $(src_of "$n")"
    fi
    say ""
    cmd_snippet "$n"
}

cmd_start() {
    local n=${1:-} serve=1
    need_name "$n"
    [[ "${2:-}" == --no-serve ]] && serve=0
    load "$n" || die "설정이 없습니다 — limn add $n ..."
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
    say "$(unit_of "$n") 중지·비활성 (설정·포트 예약·serve 항목은 그대로 — 다시 켜기: limn start $n)"
}

# update — 설치된 limn 을 uv tool 로 다시 설치하고 켜진 인스턴스를 재시작한다. 상태 폴더는 건드리지 않는다.
# 되돌리기는 이전 태그로 다시 설치하는 것이다(limn update --ref v<이전 판>). 도는 서버는 이미 메모리에
# 올라 있으므로 설치 중에 죽지 않고, 재시작할 때 새 판으로 바뀐다.
latest_tag() { # 원격의 v* 태그 중 가장 높은 판. 실패하면 아무 것도 찍지 않는다.
    local url=${REPO#git+}
    command -v git > /dev/null 2>&1 || return 0
    GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes}" \
        timeout 30 git ls-remote --tags --refs "$url" 'v*' 2> /dev/null \
        | awk '{ sub("refs/tags/", "", $2); print $2 }' | sort -V | tail -1
}
cmd_update() {
    local ref="" from="" force=0 restart=1 dry=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --ref) ref=${2:-}; shift 2 ;;
            --from) from=${2:-}; shift 2 ;;
            --force) force=1; shift ;;
            --no-restart) restart=0; shift ;;
            --dry-run | -n) dry=1; shift ;;
            *) die "모르는 인자: $1" ;;
        esac
    done
    [[ -z "$ref" || -z "$from" ]] || die "--ref 와 --from 은 함께 쓰지 않습니다"
    local spec
    if [[ -n "$from" ]]; then
        spec=$from
    else
        if [[ -z "$ref" ]]; then
            ref=$(latest_tag)
            [[ -n "$ref" ]] || die "원격 태그를 읽지 못했습니다($REPO) — --ref <태그> 로 지정하세요"
        fi
        if [[ "$ref" == "v$VERSION" && "$force" == 0 ]]; then
            say "이미 $ref 입니다 — 다시 설치하지 않습니다(--force 로 강제)"
            return 0
        fi
        spec="$REPO@$ref"
    fi
    local cmd=("$UV" tool install --force "$spec")
    local active=() n
    if [[ "$restart" == 1 ]]; then
        for n in $(instances); do
            [[ "$(sysu is-active "$(unit_of "$n")" 2> /dev/null)" == active ]] && active+=("$n")
        done
    fi
    if [[ "$dry" == 1 ]]; then
        say "(dry-run) 지금 판: $VERSION"
        say "(dry-run) 설치: ${cmd[*]}"
        if [[ ${#active[@]} -gt 0 ]]; then
            for n in "${active[@]}"; do say "(dry-run) 재시작: $(unit_of "$n")"; done
        else
            say "(dry-run) 재시작할 인스턴스 없음"
        fi
        say "(dry-run) 되돌리기: limn update --ref v$VERSION"
        return 0
    fi
    say "설치: ${cmd[*]}"
    "${cmd[@]}" || die "설치 실패 — 지금 판($VERSION)은 그대로입니다"
    local now
    now=$("$LIMN_BIN" version 2> /dev/null || true)
    say "limn $VERSION → ${now#limn } (되돌리기: limn update --ref v$VERSION)"
    [[ -f "$UNIT_TEMPLATE" ]] && ensure_unit
    [[ ${#active[@]} -gt 0 ]] || {
        say "켜진 인스턴스 없음"
        return 0
    }
    for n in "${active[@]}"; do
        load "$n" || continue
        sysu restart "$(unit_of "$n")" || {
            warn "재시작 실패: $(unit_of "$n")"
            continue
        }
        if wait_ready "$n" "$C_PORT"; then say "  $n 재시작 → 200"; else warn "  $n 재시작 뒤 응답 없음 — limn status $n"; fi
    done
}

cmd_list() {
    local n state code
    printf '%-14s %-16s %-6s %-6s %-9s %-5s %-4s %s\n' 이름 이름표 로컬 테일넷 상태 열린핀 문서 원고
    for n in $(instances); do
        load "$n" || continue
        state=$(sysu is-active "$(unit_of "$n")" 2> /dev/null)
        [[ -n "$state" ]] || state="?"
        code=""
        [[ "$state" == active ]] && code=$(http_code "$C_PORT")
        [[ -n "$code" && "$code" != 200 ]] && state="$state/$code"
        printf '%-14s %-16s %-6s %-6s %-9s %-5s %-4s %s\n' "$n" "${C_LABEL:--}" "$C_PORT" "$C_TS_PORT" \
            "$state" "$(open_pins "$C_STATE_DIR")" "$(doc_count "$C_DOCS")" "$C_MANUSCRIPT"
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
        say "인스턴스 없음 — limn add <이름> --manuscript <원고 폴더>"
        return 0
    }
    say "limn     $VERSION ($SERVER)"
    for n in $names; do
        load "$n" || die "설정이 없습니다: $n"
        local unit
        unit=$(unit_of "$n")
        say ""
        say "[$n] ${C_LABEL:-}"
        say "  유닛     $unit  $(sysu is-active "$unit" 2> /dev/null) / $(sysu is-enabled "$unit" 2> /dev/null)  pid=$(sysu show -p MainPID --value "$unit" 2> /dev/null)"
        say "  로컬     http://127.0.0.1:$C_PORT/  → $(http_code "$C_PORT")"
        say "  테일넷   $(url_of "$C_TS_PORT")  (serve: $(ts_proxy_of "$C_TS_PORT" | grep . || echo 없음))"
        if [[ -n "$C_DOCS" ]]; then
            say "  원고     $C_MANUSCRIPT"
            say "  문서     $(doc_count "$C_DOCS")개: $(doc_keys "$C_DOCS")"
        else
            say "  원고     $C_MANUSCRIPT/${C_MAIN:-(자동)}"
        fi
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
    local doclist=""
    if [[ -n "$C_DOCS" ]]; then
        doclist=$'\n'"- 문서: $(doc_keys "$C_DOCS") — \`pins.md\` 는 문서별 소절로 나뉜다. 특정 문서로 바로 열려면 \`$url/#doc=<키>\`"
    fi
    cat << EOF
--- 이 논문 저장소의 AGENTS.md 에 붙일 조각 (limn snippet $n) ---
## Limn 원고 인스턴스 (${C_LABEL:-$n})

- 뷰어: $url/ — 공저자가 PDF 에서 드래그해 수정할 자리를 핀으로 남긴다.$doclist
- 핀 목록: \`curl -s $url/pins.md\` (같은 기기에서는 \`curl -s http://127.0.0.1:$C_PORT/pins.md\`)
- **먼저 확인한다**: pins.md 머리의 저장소(원고 경로)가 이 체크아웃의 \`git remote get-url origin\` 과 같은지 본다.
  다르면 다른 논문의 뷰어다 — 처리하지 않는다. 이 뷰어의 원고 저장소: \`$origin\`
- 처리 분담: 부탁받은 쪽이 열린 핀을 **전부** 처리한다. 다른 쪽이 claim 한 핀(⏳)은 건너뛴다.
- 처리한 핀은 pins.md 머리의 안내대로 닫는다(무엇을 고쳤는지 reply, 커밋·PR 을 ref 로).
---
EOF
}

# write_conf_docs <이름> <DOCS 문자열> — 로드된 C_* (load 가 채운 것)를 그대로 두고 MAIN 자리에
# DOCS 를 넣어 설정 파일(C_FILE — 보통 홈의 심링크, 따라가서 원본을 고친다)을 다시 쓴다.
write_conf_docs() {
    local n=$1 docs_str=$2 f=$C_FILE
    {
        printf '# limn@%s — `limn doc` 가 %s 에 고쳤다. 형식·키는 README 참고.\n' "$n" "$(date +%F)"
        printf '# 셸로 source 하지 않는다 — 값에 셸 문법을 쓰지 말 것.\n'
        emit LABEL "$C_LABEL"
        emit ACCENT "$C_ACCENT"
        emit MANUSCRIPT "$C_MANUSCRIPT"
        emit DOCS "$docs_str"
        emit PORT "$C_PORT"
        emit TS_PORT "$C_TS_PORT"
        emit STATE_DIR "$C_STATE_DIR"
        emit GIT_PULL "$C_GIT_PULL"
        emit EXTRA_ARGS "$C_EXTRA_ARGS"
    } > "$f" || die "설정을 쓰지 못했습니다: $f"
}

# 재시작 안내 또는 --restart 처리 — doc add/remove 공통.
doc_restart_or_hint() {
    local n=$1 restart=$2
    if [[ "$restart" == 1 ]]; then
        sysu restart "$(unit_of "$n")" || die "재시작 실패: journalctl --user -u $(unit_of "$n")"
        load "$n" || die "설정을 다시 읽지 못했습니다: $n"
        if wait_ready "$n" "$C_PORT"; then say "재시작 → 127.0.0.1:$C_PORT 200"; else warn "재시작 뒤 응답 없음 — limn status $n"; fi
    else
        say "재시작이 필요합니다: limn stop $n && limn start $n (또는 --restart)"
    fi
}

cmd_doc_list() {
    local n=${1:-}
    need_name "$n"
    load "$n" || die "설정이 없습니다: $n"
    if [[ -z "$C_DOCS" ]]; then
        say "단일 문서 (MAIN=${C_MAIN:-자동 탐지})"
        return 0
    fi
    local specs=() spec
    IFS=';' read -ra specs <<< "$C_DOCS"
    printf '%-10s %-24s %s\n' 키 이름 경로
    for spec in "${specs[@]}"; do
        doc_parse_kv "$spec"
        printf '%-10s %-24s %s\n' "$DOC_KEY" "$DOC_NAME" "$DOC_PATH"
    done
}

cmd_doc_suggest() { # 읽기 전용 — 설정을 쓰지 않고 자동 탐지될 DOCS 문자열만 찍는다
    local manuscript="" stage=auto
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --manuscript) manuscript=${2:-}; shift 2 ;;
            --stage) stage=${2:-}; shift 2 ;;
            *) die "모르는 인자: $1" ;;
        esac
    done
    [[ -n "$manuscript" ]] || die "--manuscript <원고 폴더> 가 필요합니다"
    [[ -d "$manuscript" ]] || die "원고 폴더가 없습니다: $manuscript"
    manuscript=$(cd "$manuscript" && pwd -P)
    detect_docs_layout "$manuscript" "$stage" \
        || die "표준 레이아웃(manuscript/<라운드>/<본문>.tex)을 찾지 못했습니다 — --doc 를 손으로 주세요"
    validate_doc_specs "$manuscript" "${DETECTED_DOCS[@]}"
    join_semi "${DETECTED_DOCS[@]}"
    printf '\n'
}

cmd_doc_add() {
    local n=${1:-}
    need_name "$n"
    shift
    local newdocs=() restart=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --doc) newdocs+=("${2:-}"); shift 2 ;;
            --restart) restart=1; shift ;;
            *) die "모르는 인자: $1" ;;
        esac
    done
    ((${#newdocs[@]} > 0)) || die "--doc <키>=<표시 이름>:<경로> 가 최소 1개 필요합니다"
    load "$n" || die "설정이 없습니다: $n"
    [[ -n "$C_MANUSCRIPT" && -d "$C_MANUSCRIPT" ]] || die "MANUSCRIPT 폴더가 없습니다: '$C_MANUSCRIPT'"
    local specs=()
    if [[ -n "$C_DOCS" ]]; then
        IFS=';' read -ra specs <<< "$C_DOCS"
    elif [[ -n "$C_MAIN" ]]; then
        # 단일 문서(MAIN) → 다중 문서 전환: 본문을 첫 항목 main=본문:<MAIN> 으로 옮긴다. 키가
        # main 인 LaTeX 문서는 서버가 상태 폴더 루트(옛 자리)를 그대로 쓰므로 빌드 이력·쪽
        # 이미지가 이어지고, doc 필드가 없는 옛 핀도 이 문서로 읽힌다(operations.md §여러 문서).
        specs=("main=본문:$C_MAIN")
    else
        die "MAIN 도 DOCS 도 없는 설정입니다 — 손으로 확인하세요: $C_FILE"
    fi
    specs+=("${newdocs[@]}")
    validate_doc_specs "$C_MANUSCRIPT" "${specs[@]}"
    local docs_str
    docs_str=$(join_semi "${specs[@]}")
    safe_value "$docs_str" || die "설정 파일에 쓸 수 없는 문자(따옴표·역슬래시·\$·백틱·줄바꿈)가 DOCS 에 있습니다"
    write_conf_docs "$n" "$docs_str"
    say "DOCS 갱신: $C_FILE"
    say "  더함: $(join_semi "${newdocs[@]}")"
    doc_restart_or_hint "$n" "$restart"
}

cmd_doc_remove() {
    local n=${1:-}
    need_name "$n"
    local key=${2:-}
    [[ -n "$key" ]] || die "제거할 키가 필요합니다: limn doc remove <이름> <키>"
    shift 2
    local restart=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --restart) restart=1; shift ;;
            *) die "모르는 인자: $1" ;;
        esac
    done
    load "$n" || die "설정이 없습니다: $n"
    [[ -n "$C_DOCS" ]] || die "'$n' 은 여러 문서 설정(DOCS)이 없습니다 — 단일 문서 인스턴스는 지울 문서가 없습니다"
    local specs=() spec kept=() found=0
    IFS=';' read -ra specs <<< "$C_DOCS"
    for spec in "${specs[@]}"; do
        doc_parse_kv "$spec"
        if [[ "$DOC_KEY" == "$key" ]]; then found=1; else kept+=("$spec"); fi
    done
    ((found == 1)) || die "키를 찾지 못했습니다: $key ($(doc_keys "$C_DOCS"))"
    ((${#kept[@]} > 0)) || die "마지막 문서는 지울 수 없습니다 — 인스턴스를 통째로 지우려면 limn remove $n"
    validate_doc_specs "$C_MANUSCRIPT" "${kept[@]}"
    local docs_str
    docs_str=$(join_semi "${kept[@]}")
    write_conf_docs "$n" "$docs_str"
    say "DOCS 에서 제거: $key"
    doc_restart_or_hint "$n" "$restart"
}

cmd_doc() {
    local sub=${1:-}
    [[ $# -gt 0 ]] && shift
    case "$sub" in
        list) cmd_doc_list "$@" ;;
        add) cmd_doc_add "$@" ;;
        remove | rm) cmd_doc_remove "$@" ;;
        suggest) cmd_doc_suggest "$@" ;;
        *) die "limn doc list|add|remove <이름> ... | suggest --manuscript <원고 폴더> (모르는 하위 명령: '$sub')" ;;
    esac
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
            "$SOURCE_DIR"/"$n".env)
                [[ "$SOURCE_DIR" == "$CONFIG_DIR" ]] || say "  설정 원본 저장소에서 이 삭제를 커밋하세요: $f"
                ;;
        esac
    done
    ledger_refresh
    say "포트 예약 해제: $port/$ts (설정 삭제)"
    sysu reset-failed "$(unit_of "$n")" > /dev/null 2>&1 || true
    say "상태 폴더는 지우지 않았습니다: $state"
}

usage() { sed -n '/^# Usage:/,/^# 보안 규칙/p' "${BASH_SOURCE[0]}" | sed -e '$d' -e 's/^# \{0,1\}//'; }

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
        doc) cmd_doc "$@" ;;
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
