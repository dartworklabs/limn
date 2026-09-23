#!/usr/bin/env bash
# bin/pin-viewer.sh 검증 — 가짜 systemctl·tailscale·ss 로 실제 호스트를 건드리지 않는다.
#
# 왜 스텁인가: 이 CLI 가 하는 일은 대부분 부작용이다(유닛을 켜고, 테일넷 문을 열고,
# 포트 장부를 다시 쓴다). tailscale serve 설정은 머신 단위 공유 상태라 진짜로 부르면
# 같은 호스트의 다른 서빙까지 걸린다. 경로는 전부 PIN_VIEWER_* 로 임시 폴더에 돌린다.
#
# 실제 systemd 인스턴스 둘을 동시에 띄워 재빌드·핀 분리를 잰 결과는 이 테스트 범위 밖이다
# (TeX Live·원고가 필요하다). 절차는 machines/example-host/pin-viewer/README.md §검증.
#
# `chk` 가 검사식을 문자열로 받아 eval 하므로 shellcheck 는 결과 변수를 미사용으로 본다.
# shellcheck disable=SC2034
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PV="$ROOT/bin/pin-viewer.sh"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

pass=0 fail=0
ok() {
    printf '  \033[32m✓\033[0m %s\n' "$1"
    pass=$((pass + 1))
}
no() {
    printf '  \033[31m✗\033[0m %s\n' "$1"
    fail=$((fail + 1))
}
chk() { if eval "$2"; then ok "$1"; else no "$1  [$2]"; fi; }

PY=$(command -v python3 || true)
if [[ -z "$PY" ]]; then
    printf '  · python3 없음 — 건너뜁니다 (CI 에서는 돕니다)\n'
    exit 0
fi

# ── 스텁 ─────────────────────────────────────────────────────────────────────
mkdir -p "$T/bin"
# systemctl: 부른 것을 적고, is-active 는 늘 inactive.
cat > "$T/bin/systemctl" << 'STUB'
#!/usr/bin/env bash
echo "systemctl $*" >> "$STUB_LOG"
[[ " $* " == *" is-active "* ]] && { echo inactive; exit 3; }
exit 0
STUB
# ss: STUB_LISTEN 에 있는 포트만 LISTEN 중이라고 답한다.
cat > "$T/bin/ss" << 'STUB'
#!/usr/bin/env bash
a="$*"
p=${a##*:}
for x in $STUB_LISTEN; do [[ "$x" == "$p" ]] && echo "LISTEN 0 5 100.64.0.1:$p 0.0.0.0:*"; done
exit 0
STUB
# tailscale: serve 설정을 STUB_SERVE(JSON)에 들고, 바꾸는 호출은 적어 둔다.
cat > "$T/bin/tailscale" << 'STUB'
#!/usr/bin/env bash
echo "tailscale $*" >> "$STUB_LOG"
case "$*" in
    "status --json") echo '{"Self":{"DNSName":"box.tail0000.ts.net."}}' ;;
    "serve status --json") cat "$STUB_SERVE" ;;
    serve\ --bg\ --https=*)
        a=${3#--https=}; "$PY" -c 'import json,sys
d=json.load(open(sys.argv[1])); d.setdefault("TCP",{})[sys.argv[2]]={"HTTPS":True}
d.setdefault("Web",{})["box.tail0000.ts.net:"+sys.argv[2]]={"Handlers":{"/":{"Proxy":sys.argv[3]}}}
json.dump(d,open(sys.argv[1],"w"))' "$STUB_SERVE" "$a" "$4" ;;
    serve\ --https=*\ off)
        a=${2#--https=}; "$PY" -c 'import json,sys
d=json.load(open(sys.argv[1])); d.get("TCP",{}).pop(sys.argv[2],None)
d.get("Web",{}).pop("box.tail0000.ts.net:"+sys.argv[2],None); json.dump(d,open(sys.argv[1],"w"))' "$STUB_SERVE" "$a" ;;
    *funnel*) echo "funnel 을 불렀다" >&2; exit 99 ;;
esac
STUB
chmod +x "$T/bin/"*

export PATH="$T/bin:$PATH" PY STUB_LOG="$T/calls" STUB_SERVE="$T/serve.json" STUB_LISTEN=""
export PIN_VIEWER_PYTHON="$PY" PIN_VIEWER_MACHINE_ID=example-host
export PIN_VIEWER_DATA_ROOT="$T/data" PIN_VIEWER_CONFIG_DIR="$T/config" PIN_VIEWER_SOURCE_DIR="$T/src"
export PIN_VIEWER_UNITS_DIR="$T/units" PIN_VIEWER_USER_UNIT_DIR="$T/user-units"
export PIN_VIEWER_LEDGER="$T/served/reserved-ports.txt" PIN_VIEWER_PLUGIN_ROOT="$T/plugins"
export PIN_VIEWER_TS_MIN=18005 PIN_VIEWER_TS_MAX=18012 XDG_RUNTIME_DIR="$T/run"
mkdir -p "$T/units" "$T/run"
# 장부에 이미 있는 유닛: 로컬 18105 를 광고한다 → 18005↔18105 짝은 못 쓴다.
printf '[Service]\nExecStart=/usr/bin/python3 x.py --port 18105\n' > "$T/units/other-serve.service"
# serve 에 이미 걸린 18006 → 18006↔18106 짝도 못 쓴다.
echo '{"TCP":{"18006":{"HTTPS":true}},"Web":{"box.tail0000.ts.net:18006":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:9999"}}}}}' > "$STUB_SERVE"
# 18107 은 누군가 LISTEN 중 → 18007↔18107 짝도 못 쓴다. 남는 첫 짝은 18008↔18108.
export STUB_LISTEN="18107"

ms="$T/ms/paper-x/manuscript"
mkdir -p "$ms"
printf '\\documentclass{article}\n\\begin{document}x\\end{document}\n' > "$ms/main.tex"
printf '%% \\documentclass{article} (주석)\n' > "$ms/notes.tex"

echo "── 1. 이름 검증 ──"
for bad in Bad app -x 'a/b' 'a b' ''; do
    chk "거부: '$bad'" "! '$PV' add '$bad' --manuscript '$ms' --no-start >/dev/null 2>&1"
done
chk "없는 원고 폴더는 거부" "! '$PV' add ok1 --manuscript '$T/none' --no-start >/dev/null 2>&1"
chk "없는 메인 .tex 는 거부" "! '$PV' add ok1 --manuscript '$ms' --main nope.tex --no-start >/dev/null 2>&1"
chk "\$ 가 든 이름표는 거부(설정 파일이 코드가 되지 않게)" "! '$PV' add ok1 --manuscript '$ms' --label 'a\$(id)' --no-start >/dev/null 2>&1"
chk "#rrggbb 가 아닌 accent 는 거부" "! '$PV' add ok1 --manuscript '$ms' --accent red --no-start >/dev/null 2>&1"
chk "거부된 add 는 설정을 남기지 않는다" "[[ ! -e '$T/src/ok1.env' && ! -e '$T/config/ok1.env' ]]"

echo "── 2. add: 설정·링크·포트 자동 배정 ──"
out=$("$PV" add paper-a --manuscript "$ms" --label "Paper A" --accent '#1f77b4' --git-pull --no-start 2>&1)
rc=$?
chk "add --no-start 성공" "[[ $rc -eq 0 ]]"
env_a="$T/src/paper-a.env"
chk "원본 설정이 원본 폴더에 생긴다" "[[ -f '$env_a' ]]"
chk "홈 설정은 원본을 가리키는 심링크" "[[ -L '$T/config/paper-a.env' && \$(readlink '$T/config/paper-a.env') == '$env_a' ]]"
chk "메인 .tex 자동 탐지(주석 속 \\\\documentclass 는 무시)" "grep -qx 'MAIN=main.tex' '$env_a'"
chk "장부·serve·LISTEN 을 피해 첫 빈 짝(18008↔18108)" "grep -qx 'TS_PORT=18008' '$env_a' && grep -qx 'PORT=18108' '$env_a'"
chk "공백 든 값은 따옴표로 싼다" "grep -qx 'LABEL=\"Paper A\"' '$env_a'"
chk "# 든 값도 따옴표로 싼다" "grep -qx 'ACCENT=\"#1f77b4\"' '$env_a'"
chk "--git-pull → GIT_PULL=1" "grep -qx 'GIT_PULL=1' '$env_a'"
chk "기본 상태 폴더는 DATA_ROOT/<이름>" "grep -qx 'STATE_DIR=$T/data/paper-a' '$env_a'"
chk "장부에 두 포트가 예약된다" "grep -qx '18008 pin-viewer@paper-a' '$PIN_VIEWER_LEDGER' && grep -qx '18108 pin-viewer@paper-a' '$PIN_VIEWER_LEDGER'"
chk "AGENTS.md 조각을 출력한다" "grep -q 'curl -s https://box.tail0000.ts.net:18008/pins.md' <<< \"\$out\" && grep -q 'git remote get-url origin' <<< \"\$out\" && grep -q '⏳' <<< \"\$out\""
chk "--no-start 는 유닛·serve 를 건드리지 않는다" "! grep -qE 'systemctl .*(enable|start)|tailscale serve --' '$STUB_LOG'"

out=$("$PV" add paper-b --manuscript "$ms" --no-start 2>&1)
chk "두 번째 add 는 다음 빈 짝(18009↔18109)" "grep -qx 'TS_PORT=18009' '$T/src/paper-b.env' && grep -qx 'PORT=18109' '$T/src/paper-b.env'"
chk "이름표 생략 → git 저장소가 아니면 이름" "grep -qx 'LABEL=paper-b' '$T/src/paper-b.env'"
chk "같은 원고를 보면 경고한다" "grep -q '같은 원고 폴더' <<< \"\$out\""
chk "같은 이름은 다시 add 못 한다" "! '$PV' add paper-a --manuscript '$ms' --no-start >/dev/null 2>&1"
chk "다른 인스턴스의 포트는 명시해도 거부" "! '$PV' add paper-c --manuscript '$ms' --port 18108 --ts-port 18010 --no-start >/dev/null 2>&1"
chk "serve 에 걸린 포트는 명시해도 거부" "! '$PV' add paper-c --manuscript '$ms' --port 18110 --ts-port 18006 --no-start >/dev/null 2>&1"
chk "상태 폴더가 겹치면 거부" "! '$PV' add paper-c --manuscript '$ms' --state-dir '$T/data/paper-a' --no-start >/dev/null 2>&1"

echo "── 3. run: 조건부 인자 ──"
mkdir -p "$T/data/app/vendor/pdfjs"
# 옛 앱: --label·--accent 를 모른다.
printf 'import sys\nprint("usage: pin_server.py --manuscript M --port P --git-pull")\n' > "$T/data/app/pin_server.py"
argv=$(PIN_VIEWER_PRINT_ARGV=1 "$PV" run paper-a 2> "$T/run.err")
chk "run 이 설정대로 인자를 만든다" "grep -qx -- '--port' <<< \"\$argv\" && grep -qx 18108 <<< \"\$argv\" && grep -qx -- '--git-pull' <<< \"\$argv\" && grep -qx -- '--no-build' <<< \"\$argv\""
chk "상태·pdfjs 경로를 넘긴다" "grep -qx '$T/data/paper-a' <<< \"\$argv\" && grep -qx '$T/data/app/vendor/pdfjs' <<< \"\$argv\""
chk "옛 앱에는 --label 을 넘기지 않는다" "! grep -qx -- '--label' <<< \"\$argv\""
chk "대신 경고를 남긴다" "grep -q -- '--label 을 모릅니다' '$T/run.err'"
# 새 앱: 두 인자를 안다.
printf 'print("usage: pin_server.py [--label LABEL] [--accent ACCENT]")\n' > "$T/data/app/pin_server.py"
argv=$(PIN_VIEWER_PRINT_ARGV=1 "$PV" run paper-a 2> /dev/null)
chk "새 앱에는 이름표를 한 인자로 넘긴다" "grep -qx -- '--label' <<< \"\$argv\" && grep -qx 'Paper A' <<< \"\$argv\""
chk "accent 도 넘긴다" "grep -qx -- '--accent' <<< \"\$argv\" && grep -qx '#1f77b4' <<< \"\$argv\""
argv=$(PIN_VIEWER_PRINT_ARGV=1 "$PV" run paper-b 2> /dev/null)
chk "GIT_PULL 이 0 이면 --git-pull 없음" "! grep -qx -- '--git-pull' <<< \"\$argv\""
sed -i.bak '/^PORT=/d' "$T/src/paper-b.env" && rm -f "$T/src/paper-b.env.bak"
chk "PORT 가 없으면 run 은 실패한다(자동 선택 금지)" "! PIN_VIEWER_PRINT_ARGV=1 '$PV' run paper-b >/dev/null 2>&1"
printf 'PORT=18109\n' >> "$T/src/paper-b.env"

echo "── 4. list·url ──"
lst=$("$PV" list 2>&1)
chk "list 가 두 인스턴스와 이름표를 보인다" "grep -qE '^paper-a +Paper A +18108 +18008' <<< \"\$lst\" && grep -qE '^paper-b +paper-b +18109 +18009' <<< \"\$lst\""
chk "url 이 테일넷 주소를 낸다" "[[ \$('$PV' url paper-a) == 'https://box.tail0000.ts.net:18008/' ]]"

echo "── 5. remove ──"
# paper-b 의 테일넷 포트를 남이 쓰는 것처럼 꾸민다 → remove 가 내리면 안 된다.
"$PY" -c 'import json,sys
d=json.load(open(sys.argv[1])); d["TCP"]["18009"]={"HTTPS":True}
d["Web"]["box.tail0000.ts.net:18009"]={"Handlers":{"/":{"Proxy":"http://127.0.0.1:7777"}}}
json.dump(d,open(sys.argv[1],"w"))' "$STUB_SERVE"
mkdir -p "$T/data/paper-b" && echo keep > "$T/data/paper-b/pins.jsonl"
: > "$STUB_LOG"
out=$("$PV" remove paper-b 2>&1)
chk "유닛을 disable --now 한다" "grep -q 'disable --now pin-viewer@paper-b.service' '$STUB_LOG'"
chk "남의 serve 항목은 내리지 않는다" "! grep -q 'serve --https=18009 off' '$STUB_LOG' && grep -q '7777' '$STUB_SERVE'"
chk "설정 원본과 링크가 사라진다" "[[ ! -e '$T/src/paper-b.env' && ! -L '$T/config/paper-b.env' ]]"
chk "장부에서 빠진다" "! grep -q 'pin-viewer@paper-b' '$PIN_VIEWER_LEDGER' && grep -q 'pin-viewer@paper-a' '$PIN_VIEWER_LEDGER'"
chk "상태 폴더는 남긴다" "[[ \$(cat '$T/data/paper-b/pins.jsonl') == keep ]] && grep -q '지우지 않았습니다' <<< \"\$out\""
# paper-a 는 우리 짝을 걸어 두고 remove → 내려야 한다.
"$PY" -c 'import json,sys
d=json.load(open(sys.argv[1])); d["TCP"]["18008"]={"HTTPS":True}
d["Web"]["box.tail0000.ts.net:18008"]={"Handlers":{"/":{"Proxy":"http://127.0.0.1:18108"}}}
json.dump(d,open(sys.argv[1],"w"))' "$STUB_SERVE"
"$PV" remove paper-a > /dev/null 2>&1
chk "우리 serve 항목은 내린다" "grep -q 'serve --https=18008 off' '$STUB_LOG' && ! grep -q '18108' '$STUB_SERVE'"
chk "funnel 은 한 번도 부르지 않았다" "! grep -q funnel '$STUB_LOG'"

echo "── 6. update: 설치된 플러그인 버전을 고른다 ──"
mk_skill() { # mk_skill <폴더> <표식>
    mkdir -p "$1/skills/manuscript-pin-picker/scripts" "$1/skills/manuscript-pin-picker/vendor/pdfjs"
    printf 'print("usage: %s")\n' "$2" > "$1/skills/manuscript-pin-picker/scripts/pin_server.py"
    : > "$1/skills/manuscript-pin-picker/vendor/pdfjs/pdf.min.mjs"
    : > "$1/skills/manuscript-pin-picker/vendor/pdfjs/pdf.worker.min.mjs"
}
cache="$T/plugins/cache/mkt/writing-agent-playbook"
mk_skill "$cache/aaa111" installed
mk_skill "$cache/zzz999" stale # 사전순으로 마지막 — `ls | tail -1` 이 고르던 옛 버전
printf '{"plugins":{"writing-agent-playbook@mkt":[{"installPath":"%s"}]}}' "$cache/aaa111" > "$T/plugins/installed_plugins.json"
rm -rf "$T/data/app"
echo keep > "$T/data/paper-a/pins.jsonl" 2> /dev/null || { mkdir -p "$T/data/paper-a" && echo keep > "$T/data/paper-a/pins.jsonl"; }
out=$("$PV" update 2>&1)
chk "installed_plugins.json 의 installPath 를 쓴다" "grep -q 'installed' '$T/data/app/pin_server.py' && grep -q 'aaa111' '$T/data/app/SOURCE'"
chk "vendor/pdfjs 도 함께 복사한다" "[[ -f '$T/data/app/vendor/pdfjs/pdf.worker.min.mjs' ]]"
out=$("$PV" update 2>&1)
chk "같으면 갈아 끼우지 않는다" "grep -q '이미 최신' <<< \"\$out\""
out=$("$PV" update --from "$cache/zzz999/skills/manuscript-pin-picker" 2>&1)
chk "--from 으로 다른 판을 끼우고 직전 판을 app.prev 로 남긴다" "grep -q stale '$T/data/app/pin_server.py' && grep -q installed '$T/data/app.prev/pin_server.py'"
chk "상태 폴더는 건드리지 않는다" "[[ \$(cat '$T/data/paper-a/pins.jsonl') == keep ]]"
rm "$cache/zzz999/skills/manuscript-pin-picker/vendor/pdfjs/pdf.min.mjs"
chk "pdfjs 가 빠진 판은 거부한다" "! '$PV' update --from '$cache/zzz999/skills/manuscript-pin-picker' --force >/dev/null 2>&1 && grep -q stale '$T/data/app/pin_server.py'"

echo "── 7. 템플릿 유닛·paper-a 설정 ──"
U="$ROOT/machines/example-host/systemd/pin-viewer@.service"
C="$ROOT/machines/example-host/pin-viewer/paper-a.env"
chk "EnvironmentFile 로 인스턴스 설정을 읽는다" "grep -qx 'EnvironmentFile=%h/.config/pin-viewer/%i.env' '$U'"
chk "ExecStart 는 pin-viewer run %i" "grep -qx 'ExecStart=%h/.local/bin/pin-viewer run %i' '$U'"
chk "TeX Live PATH·git 비대화 환경을 옮겼다" "grep -q 'texlive/2025/bin' '$U' && grep -qx 'Environment=GIT_TERMINAL_PROMPT=0' '$U' && grep -q 'BatchMode=yes' '$U'"
chk "Restart=on-failure" "grep -qx 'Restart=on-failure' '$U'"
chk "0.0.0.0·funnel 을 쓰지 않는다" "! grep -vE '^#' '$U' | grep -qE '0\\.0\\.0\\.0|funnel'"
chk "paper-a 은 옛 포트·상태 폴더 그대로" "grep -qx 'PORT=18104' '$C' && grep -qx 'TS_PORT=18004' '$C' && grep -qx 'STATE_DIR=/home/user/.local/share/paper-a-pin' '$C'"
chk "paper-a 은 --no-build·git-pull·이름표 A-DEMO" "grep -qx 'EXTRA_ARGS=--no-build' '$C' && grep -qx 'GIT_PULL=1' '$C' && grep -qx 'LABEL=A-DEMO' '$C'"

printf '\n  %d passed, %d failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
