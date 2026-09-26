#!/usr/bin/env bash
# Tests for the Limn instance manager (`limn add|start|…`, src/limn/instances.sh) — with fake
# systemctl/tailscale/ss/uv so the real host is never touched.
#
# Why stubs: most of what this CLI does is side effects (enabling units, opening tailnet ports,
# installing packages). tailscale serve config is machine-wide shared state, so calling the real one
# would affect other services on the host. All paths are redirected into a temp dir via LIMN_*/HOME/XDG_*.
#
# `chk` evals its check expression from a string, so shellcheck sees result variables as unused.
# shellcheck disable=SC2034
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

# The real interpreter (resolved before HOME is redirected — some python3 shims depend on HOME). limn needs
# Python >= 3.10, and macOS's /usr/bin/python3 is 3.9, so the first python3 is not enough: LIMN_TEST_PYTHON, then
# python3 / python3.1x on PATH, then this checkout's .venv (uv sync).
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' > /dev/null 2>&1; }
PY=""
for c in "${LIMN_TEST_PYTHON:-}" python3 python3.14 python3.13 python3.12 python3.11 python3.10 "$ROOT/.venv/bin/python"; do
    [[ -n "$c" ]] || continue
    c=$(command -v "$c" 2> /dev/null) || continue
    py_ok "$c" || continue
    PY=$("$c" -c "import sys; print(sys.executable)") && break
done
if [[ -z "$PY" ]]; then
    printf '  · no Python >= 3.10 found (set LIMN_TEST_PYTHON, or uv sync) — skipping (runs fine in CI)\n'
    exit 0
fi
# mode_of <file> — octal permission bits on GNU (Linux) and BSD (macOS) stat alike.
mode_of() { stat -c %a "$1" 2> /dev/null || stat -f %Lp "$1"; }

# ── stubs ─────────────────────────────────────────────────────────────────────
mkdir -p "$T/bin"
# systemctl: logs each call, and is-active always reports inactive.
cat > "$T/bin/systemctl" << 'STUB'
#!/usr/bin/env bash
echo "systemctl $*" >> "$STUB_LOG"
[[ " $* " == *" is-active "* ]] && { echo inactive; exit 3; }
exit 0
STUB
# ss: reports LISTEN only for ports listed in STUB_LISTEN.
cat > "$T/bin/ss" << 'STUB'
#!/usr/bin/env bash
a="$*"
p=${a##*:}
for x in $STUB_LISTEN; do [[ "$x" == "$p" ]] && echo "LISTEN 0 5 100.64.0.1:$p 0.0.0.0:*"; done
exit 0
STUB
# tailscale: keeps serve config in STUB_SERVE (JSON), and logs calls that change it.
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
    *funnel*) echo "funnel was called" >&2; exit 99 ;;
esac
STUB
chmod +x "$T/bin/"*

# limn: the real CLI from this checkout (python -m limn), so cli.py's env hand-off is exercised too.
cat > "$T/bin/limn" << STUB
#!/usr/bin/env bash
PYTHONPATH="$ROOT/src\${PYTHONPATH:+:\$PYTHONPATH}" exec "$PY" -m limn "\$@"
STUB
# uv: records the call; a later `limn version` reports the version in STUB_NEW_VERSION.
cat > "$T/bin/uv" << 'STUB'
#!/usr/bin/env bash
echo "uv $*" >> "$STUB_LOG"
exit "${STUB_UV_RC:-0}"
STUB
chmod +x "$T/bin/"*
PV="$T/bin/limn"

export PATH="$T/bin:$PATH" PY STUB_LOG="$T/calls" STUB_SERVE="$T/serve.json" STUB_LISTEN=""
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" XDG_DATA_HOME="$T/home/.local/share"
export LIMN_DATA_ROOT="$T/data" LIMN_CONFIG_DIR="$T/config" LIMN_SOURCE_DIR="$T/src"
export LIMN_USER_UNIT_DIR="$T/user-units" LIMN_LEDGER="$T/served/reserved-ports.txt"
export LIMN_TS_MIN=18005 LIMN_TS_MAX=18012 XDG_RUNTIME_DIR="$T/run"
export LIMN_WAIT=1 # doc add/remove --restart wait for HTTP 200; there is no server, so keep the loop short
export LIMN_UV="$T/bin/uv" LIMN_REPO="git+ssh://git@example.invalid/limn" LIMN_UNIT_PATH="/opt/tex/bin:/usr/bin:/bin"
mkdir -p "$T/run" "$T/served" "$HOME"
# The port ledger already lists a unit advertising local 18105 → the 18005↔18105 pair is unusable.
printf '# generated\n18105 other-serve.service\n' > "$LIMN_LEDGER"
cp "$LIMN_LEDGER" "$T/ledger.orig"
# 18006 is already served by tailscale → the 18006↔18106 pair is unusable too.
echo '{"TCP":{"18006":{"HTTPS":true}},"Web":{"box.tail0000.ts.net:18006":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:9999"}}}}}' > "$STUB_SERVE"
# Someone is LISTENing on 18107 → 18007↔18107 is unusable. The first free pair is 18008↔18108.
export STUB_LISTEN="18107"

ms="$T/ms/paper-x/manuscript"
mkdir -p "$ms"
printf '\\documentclass{article}\n\\begin{document}x\\end{document}\n' > "$ms/main.tex"
printf '%% \\documentclass{article} (comment)\n' > "$ms/notes.tex"

echo "── 1. name validation ──"
for bad in Bad serve -x 'a/b' 'a b' ''; do
    chk "rejects: '$bad'" "! '$PV' add '$bad' --manuscript '$ms' --no-start >/dev/null 2>&1"
done
chk "rejects a manuscript dir that doesn't exist" "! '$PV' add ok1 --manuscript '$T/none' --no-start >/dev/null 2>&1"
chk "rejects a main .tex that doesn't exist" "! '$PV' add ok1 --manuscript '$ms' --main nope.tex --no-start >/dev/null 2>&1"
chk "rejects a label containing \$ (so the config file can't become code)" "! '$PV' add ok1 --manuscript '$ms' --label 'a\$(id)' --no-start >/dev/null 2>&1"
chk "rejects an accent that isn't #rrggbb" "! '$PV' add ok1 --manuscript '$ms' --accent red --no-start >/dev/null 2>&1"
chk "a rejected add leaves no config behind" "[[ ! -e '$T/src/ok1.env' && ! -e '$T/config/ok1.env' ]]"

echo "── 2. add: config, link, automatic port assignment ──"
out=$("$PV" add paper-a --manuscript "$ms" --label "Paper A" --accent '#1f77b4' --git-pull --no-start 2>&1)
rc=$?
chk "add --no-start succeeds" "[[ $rc -eq 0 ]]"
env_a="$T/src/paper-a.env"
chk "the source config is created in the source dir" "[[ -f '$env_a' ]]"
chk "the home config is a symlink pointing at the source" "[[ -L '$T/config/paper-a.env' && \$(readlink '$T/config/paper-a.env') == '$env_a' ]]"
chk "auto-detects the main .tex (ignores \\\\documentclass inside a comment)" "grep -qx 'MAIN=main.tex' '$env_a'"
chk "picks the first free pair (18008↔18108), avoiding the ledger/serve/LISTEN" "grep -qx 'TS_PORT=18008' '$env_a' && grep -qx 'PORT=18108' '$env_a'"
chk "wraps values containing whitespace in quotes" "grep -qx 'LABEL=\"Paper A\"' '$env_a'"
chk "wraps values containing # in quotes too" "grep -qx 'ACCENT=\"#1f77b4\"' '$env_a'"
chk "--git-pull → GIT_PULL=1" "grep -qx 'GIT_PULL=1' '$env_a'"
chk "the default state dir is DATA_ROOT/<name>" "grep -qx 'STATE_DIR=$T/data/paper-a' '$env_a'"
chk "without LIMN_LEDGER_GEN the shared ledger file is left untouched" "cmp -s '$LIMN_LEDGER' '$T/ledger.orig'"
chk "prints the AGENTS.md snippet" "grep -q 'curl -s https://box.tail0000.ts.net:18008/pins.md' <<< \"\$out\" && grep -q 'git remote get-url origin' <<< \"\$out\" && grep -q '⏳' <<< \"\$out\""
chk "the snippet tells remote agents to send a token" "grep -qF 'Authorization: Bearer \$LIMN_TOKEN' <<< \"\$out\" && grep -q 'limn token create' <<< \"\$out\""
chk "--no-start doesn't touch the unit or serve" "! grep -qE 'systemctl .*(enable|start)|tailscale serve --' '$STUB_LOG'"

out=$("$PV" add paper-b --manuscript "$ms" --no-start 2>&1)
chk "the second add gets the next free pair (18009↔18109)" "grep -qx 'TS_PORT=18009' '$T/src/paper-b.env' && grep -qx 'PORT=18109' '$T/src/paper-b.env'"
chk "label omitted → falls back to the name when it's not a git repo" "grep -qx 'LABEL=paper-b' '$T/src/paper-b.env'"
chk "warns when it sees the same manuscript" "grep -q 'same manuscript dir' <<< \"\$out\""
chk "the same name cannot be added again" "! '$PV' add paper-a --manuscript '$ms' --no-start >/dev/null 2>&1"
chk "another instance's port is rejected even if given explicitly" "! '$PV' add paper-c --manuscript '$ms' --port 18108 --ts-port 18010 --no-start >/dev/null 2>&1"
chk "a port already used by serve is rejected even if given explicitly" "! '$PV' add paper-c --manuscript '$ms' --port 18110 --ts-port 18006 --no-start >/dev/null 2>&1"
chk "rejects when the state dir collides" "! '$PV' add paper-c --manuscript '$ms' --state-dir '$T/data/paper-a' --no-start >/dev/null 2>&1"

echo "── 3. run: arguments from the config ──"
argv=$(LIMN_PRINT_ARGV=1 "$PV" run paper-a 2> "$T/run.err")
chk "run execs the packaged server with the interpreter that runs limn" "[[ \$(sed -n 1p <<< \"\$argv\") == '$PY' && \$(sed -n 2p <<< \"\$argv\") == '$ROOT/src/limn/server.py' ]]"
chk "run builds the arguments from the config" "grep -qx -- '--port' <<< \"\$argv\" && grep -qx 18108 <<< \"\$argv\" && grep -qx -- '--git-pull' <<< \"\$argv\" && grep -qx -- '--no-build' <<< \"\$argv\""
chk "run passes the state dir" "grep -qx '$T/data/paper-a' <<< \"\$argv\""
chk "run passes the label as one argument" "grep -qx -- '--label' <<< \"\$argv\" && grep -qx 'Paper A' <<< \"\$argv\""
chk "run passes the accent" "grep -qx -- '--accent' <<< \"\$argv\" && grep -qx '#1f77b4' <<< \"\$argv\""
chk "the packaged server accepts every argument run builds" "\"$PY\" '$ROOT/src/limn/server.py' --help | grep -q -- '--label' && \"$PY\" '$ROOT/src/limn/server.py' --help | grep -q -- '--doc'"
argv=$(LIMN_PRINT_ARGV=1 "$PV" run paper-b 2> /dev/null)
chk "GIT_PULL=0 means no --git-pull" "! grep -qx -- '--git-pull' <<< \"\$argv\""
sed -i.bak '/^PORT=/d' "$T/src/paper-b.env" && rm -f "$T/src/paper-b.env.bak"
chk "run fails without PORT (never auto-pick)" "! LIMN_PRINT_ARGV=1 '$PV' run paper-b >/dev/null 2>&1"
printf 'PORT=18109\n' >> "$T/src/paper-b.env"

echo "── 4. list·url ──"
lst=$("$PV" list 2>&1)
chk "list shows both instances and labels" "grep -qE '^paper-a +Paper A +18108 +18008' <<< \"\$lst\" && grep -qE '^paper-b +paper-b +18109 +18009' <<< \"\$lst\""
chk "url prints the tailnet address" "[[ \$('$PV' url paper-a) == 'https://box.tail0000.ts.net:18008/' ]]"

echo "── 5. remove ──"
# fake paper-b's tailnet port as used by someone else → remove must not take it down.
"$PY" -c 'import json,sys
d=json.load(open(sys.argv[1])); d["TCP"]["18009"]={"HTTPS":True}
d["Web"]["box.tail0000.ts.net:18009"]={"Handlers":{"/":{"Proxy":"http://127.0.0.1:7777"}}}
json.dump(d,open(sys.argv[1],"w"))' "$STUB_SERVE"
mkdir -p "$T/data/paper-b" && echo keep > "$T/data/paper-b/pins.jsonl"
: > "$STUB_LOG"
out=$("$PV" remove paper-b 2>&1)
chk "disables the unit with --now" "grep -q 'disable --now limn@paper-b.service' '$STUB_LOG'"
chk "does not take down someone else's serve entry" "! grep -q 'serve --https=18009 off' '$STUB_LOG' && grep -q '7777' '$STUB_SERVE'"
chk "the config source and link both disappear" "[[ ! -e '$T/src/paper-b.env' && ! -L '$T/config/paper-b.env' ]]"
chk "remove frees the ports (a new add may take them)" "! grep -q '^PORT=' '$T/src/paper-b.env' 2>/dev/null"
chk "leaves the state dir behind" "[[ \$(cat '$T/data/paper-b/pins.jsonl') == keep ]] && grep -q 'was not deleted' <<< \"\$out\""
# paper-a has our own pair set → remove must take it down.
"$PY" -c 'import json,sys
d=json.load(open(sys.argv[1])); d["TCP"]["18008"]={"HTTPS":True}
d["Web"]["box.tail0000.ts.net:18008"]={"Handlers":{"/":{"Proxy":"http://127.0.0.1:18108"}}}
json.dump(d,open(sys.argv[1],"w"))' "$STUB_SERVE"
"$PV" remove paper-a > /dev/null 2>&1
chk "takes down our own serve entry" "grep -q 'serve --https=18008 off' '$STUB_LOG' && ! grep -q '18108' '$STUB_SERVE'"
chk "funnel was never called" "! grep -q funnel '$STUB_LOG'"

echo "── 6. update: reinstall through uv tool, restart running instances ──"
: > "$STUB_LOG"
out=$("$PV" update --ref v9.9.9 --dry-run 2>&1)
chk "update --dry-run shows the uv command" "grep -qF 'uv tool install --force git+ssh://git@example.invalid/limn@v9.9.9' <<< \"\$out\""
chk "update --dry-run shows the rollback command" "grep -qE 'limn update --ref v[0-9]' <<< \"\$out\""
out=$(env -u LIMN_REPO "$PV" update --ref v9.9.9 --dry-run 2>&1)
chk "update defaults to the public https source" "grep -qF 'uv tool install --force git+https://github.com/dartworklabs/limn@v9.9.9' <<< \"\$out\""
chk "update --dry-run installs nothing" "! grep -q '^uv ' '$STUB_LOG'"
ver=$("$PV" version)
out=$("$PV" update --ref "v${ver#limn }" 2>&1)
chk "update to the installed tag is a no-op" "grep -q '$(printf '%s' "${ver#limn }")' <<< \"\$out\" && ! grep -q '^uv ' '$STUB_LOG'"
out=$("$PV" update --ref v9.9.9 --no-restart 2>&1)
chk "update runs uv tool install --force <repo>@<ref>" "grep -qx 'uv tool install --force git+ssh://git@example.invalid/limn@v9.9.9' '$STUB_LOG'"
chk "update --from <spec> installs that source" "'$PV' update --from '$ROOT' --no-restart >/dev/null 2>&1 && grep -qx 'uv tool install --force $ROOT' '$STUB_LOG'"
chk "update refuses --ref with --from" "! '$PV' update --ref v1 --from x >/dev/null 2>&1"
STUB_UV_RC=1 "$PV" update --ref v9.9.8 --no-restart > /dev/null 2> "$T/upd.err"
chk "a failed install stops with an error" "[[ \$? -ne 0 ]] || grep -q . '$T/upd.err'"
chk "update never touches state dirs" "[[ \$(cat '$T/data/paper-a/pins.jsonl' 2>/dev/null || echo keep) == keep ]]"

echo "── 7. unit template ──"
U="$ROOT/src/limn/systemd/limn@.service"
chk "the template reads no EnvironmentFile (limn run reads the config)" "! grep -q '^EnvironmentFile' '$U'"
chk "ExecStart is '<limn> run %i'" "grep -qx 'ExecStart=@LIMN_BIN@ run %i' '$U'"
chk "git runs non-interactively inside the unit" "grep -qx 'Environment=GIT_TERMINAL_PROMPT=0' '$U' && grep -q 'BatchMode=yes' '$U'"
chk "Restart=on-failure" "grep -qx 'Restart=on-failure' '$U'"
chk "no 0.0.0.0 and no funnel" "! grep -vE '^#' '$U' | grep -qE '0\\.0\\.0\\.0|funnel'"
"$PV" add unit-t --manuscript "$ms" --port 19110 --ts-port 19010 --no-start > /dev/null 2>&1
: > "$STUB_LOG"
"$PV" start unit-t --no-serve > "$T/start.out" 2>&1
R="$T/user-units/limn@.service"
chk "start writes the rendered unit" "[[ -f '$R' ]] && grep -q '^# limn:generated' '$R'"
chk "rendered ExecStart points at this limn" "grep -qx 'ExecStart=$T/bin/limn run %i' '$R'"
chk "rendered config dir and PATH" "grep -qx 'ConditionPathExists=$T/config/%i.env' '$R' && grep -qx 'Environment=LIMN_CONFIG_DIR=$T/config' '$R' && grep -qx 'Environment=PATH=/opt/tex/bin:/usr/bin:/bin' '$R'"
chk "start enables and starts limn@unit-t" "grep -q 'enable limn@unit-t.service' '$STUB_LOG' && grep -q 'start limn@unit-t.service' '$STUB_LOG'"
printf 'x\n' > "$T/user-units/limn@.service.foreign"
cp "$T/user-units/limn@.service.foreign" "$R"
chk "a unit file limn did not write is not overwritten" "! '$PV' start unit-t --no-serve >/dev/null 2>&1 && [[ \$(cat '$R') == x ]]"
rm -f "$R" "$T/user-units/limn@.service.foreign"

echo "── 7b. ledger generator (optional) ──"
cat > "$T/gen.sh" << 'GEN'
#!/usr/bin/env bash
printf '18105 other-serve.service\n'
for d in "${@:2}"; do for f in "$d"/*.env; do [[ -e "$f" ]] && sed -nE "s/^(TS_)?PORT=([0-9]+)$/\\2 limn@$(basename "$f" .env)/p" "$f"; done; done
GEN
chmod +x "$T/gen.sh"
LIMN_LEDGER_GEN="$T/gen.sh" "$PV" add paper-g --manuscript "$ms" --port 19120 --ts-port 19020 --no-start > /dev/null 2>&1
chk "with LIMN_LEDGER_GEN, add regenerates the ledger" "grep -qx '19120 limn@paper-g' '$LIMN_LEDGER' && grep -qx '18105 other-serve.service' '$LIMN_LEDGER'"
LIMN_LEDGER_GEN="$T/gen.sh" "$PV" remove paper-g > "$T/rm.out" 2>&1 || cat "$T/rm.out"
chk "remove regenerates it without the instance" "! grep -q 'limn@paper-g' '$LIMN_LEDGER'"

echo "── 8. multiple documents (DOCS=): add --doc validation ──"
mkdir -p "$ms/submission/review_response" "$ms/submission/submission_ready" "$ms/wide/deep"
printf '\\documentclass{article}\n\\begin{document}rr\\end{document}\n' > "$ms/submission/review_response/review_response.tex"
: > "$ms/submission/submission_ready/manuscript.pdf"
printf '\\documentclass{article}\n\\begin{document}wide\\end{document}\n' > "$ms/wide/deep/main2.tex"
: > "$ms/readme.md"

chk "--main and --doc together are rejected" \
    "! '$PV' add docs-x --manuscript '$ms' --main main.tex --doc 'rr=답변서:submission/review_response/review_response.tex' --no-start >/dev/null 2>&1"
chk "rejects a format error (no '=')" "! '$PV' add docs-x --manuscript '$ms' --doc 'badspec' --no-start >/dev/null 2>&1"
chk "rejects a format error (no ':')" "! '$PV' add docs-x --manuscript '$ms' --doc 'rr=답변서 없는콜론' --no-start >/dev/null 2>&1"
chk "rejects a key rule violation (uppercase)" "! '$PV' add docs-x --manuscript '$ms' --doc 'RR=답변서:submission/review_response/review_response.tex' --no-start >/dev/null 2>&1"
chk "rejects a duplicate key" \
    "! '$PV' add docs-x --manuscript '$ms' --doc 'rr=답변서:submission/review_response/review_response.tex' --doc 'rr=중복:main.tex' --no-start >/dev/null 2>&1"
chk "rejects a path outside the manuscript (../ is compared after normalization)" "! '$PV' add docs-x --manuscript '$ms' --doc 'out=밖:../outside.tex' --no-start >/dev/null 2>&1"
chk "rejects an unsupported extension" "! '$PV' add docs-x --manuscript '$ms' --doc 'x=문서:readme.md' --no-start >/dev/null 2>&1"
chk "rejects a nonexistent file" "! '$PV' add docs-x --manuscript '$ms' --doc 'x=문서:no-such.tex' --no-start >/dev/null 2>&1"
chk "a rejected --doc add leaves no config behind" "[[ ! -e '$T/src/docs-x.env' ]]"

docs13=()
for i in $(seq 1 13); do docs13+=(--doc "d$i=문서$i:main.tex"); done
"$PV" add docs-13 --manuscript "$ms" "${docs13[@]}" --no-start > /dev/null 2>&1
rc13=$?
chk "13 is rejected (max is 12)" "[[ $rc13 -ne 0 ]]"
chk "leaves no config behind after rejecting 13" "[[ ! -e '$T/src/docs-13.env' ]]"

out=$("$PV" add docs-1 --manuscript "$ms" --label DEMO-B-test --no-serve \
    --doc 'ms=본문:main.tex' \
    --doc 'rr=답변서:submission/review_response/review_response.tex' \
    --doc 'sub=제출본 PDF:submission/submission_ready/manuscript.pdf' \
    --doc 'wd=넓게:wide::deep/main2.tex' \
    --no-start 2>&1)
rc=$?
chk "multiple --doc add succeeds (spec examples: name with spaces · :: extended notation · .pdf mixed)" "[[ $rc -eq 0 ]]"
env_docs="$T/src/docs-1.env"
chk "DOCS is stored joined by ';'" \
    "grep -qx 'DOCS=\"ms=본문:main.tex;rr=답변서:submission/review_response/review_response.tex;sub=제출본 PDF:submission/submission_ready/manuscript.pdf;wd=넓게:wide::deep/main2.tex\"' '$env_docs'"
chk "no MAIN line when DOCS is used" "! grep -q '^MAIN=' '$env_docs'"
chk "add output (snippet) shows the doc key list and the #doc= link" "grep -q 'Docs: ms,rr,sub,wd' <<< \"\$out\" && grep -q '#doc=<key>' <<< \"\$out\""

echo "── 9. doc list/add/remove: single document ↔ multi-document switch ──"
"$PV" add single-1 --manuscript "$ms" --main main.tex --no-serve --no-start > /dev/null 2>&1
chk "doc list on a single-document instance reports MAIN" "'$PV' doc list single-1 | grep -q 'single document (MAIN=main.tex)'"
chk "doc add on a nonexistent instance is rejected" "! '$PV' doc add nope --doc 'x=문서:main.tex' >/dev/null 2>&1"
chk "doc remove on a nonexistent instance is rejected" "! '$PV' doc remove nope x >/dev/null 2>&1"
chk "an unknown doc subcommand is rejected" "! '$PV' doc frobnicate single-1 >/dev/null 2>&1"

out=$("$PV" doc add single-1 --doc 'rr=답변서:submission/review_response/review_response.tex' 2>&1)
rc=$?
env_single="$T/src/single-1.env"
chk "doc add succeeds" "[[ $rc -eq 0 ]]"
chk "MAIN becomes main=본문:<MAIN>, the first entry in DOCS (where build history carries over)" \
    "grep -qx 'DOCS=main=본문:main.tex;rr=답변서:submission/review_response/review_response.tex' '$env_single'"
chk "the MAIN line disappears" "! grep -q '^MAIN=' '$env_single'"
chk "without a restart, only a hint is printed" "grep -q 'a restart is required' <<< \"\$out\" && ! grep -q 'restart limn@single-1' '$STUB_LOG'"
dl=$("$PV" doc list single-1 2>&1)
chk "doc list shows both documents" "grep -qE '^main[[:space:]]' <<< \"\$dl\" && grep -qE '^rr[[:space:]]' <<< \"\$dl\" && grep -q 'submission/review_response/review_response.tex' <<< \"\$dl\""
chk "doc add is rejected when it collides with an existing key" "! '$PV' doc add single-1 --doc 'rr=중복:main.tex' >/dev/null 2>&1"

: > "$STUB_LOG"
"$PV" doc add single-1 --doc 'sub=제출본 PDF:submission/submission_ready/manuscript.pdf' --restart > /dev/null 2>&1
chk "--restart restarts the unit" "grep -q 'restart limn@single-1.service' '$STUB_LOG'"
chk "the third document is reflected after restart (quoted because the name has a space)" \
    "grep -qx 'DOCS=\"main=본문:main.tex;rr=답변서:submission/review_response/review_response.tex;sub=제출본 PDF:submission/submission_ready/manuscript.pdf\"' '$env_single'"

out=$("$PV" doc remove single-1 main 2>&1)
chk "doc remove succeeds (main removed, rr/sub remain)" \
    "grep -qx 'DOCS=\"rr=답변서:submission/review_response/review_response.tex;sub=제출본 PDF:submission/submission_ready/manuscript.pdf\"' '$env_single'"
chk "without a restart, doc remove also only prints a hint" "grep -q 'a restart is required' <<< \"\$out\""
chk "removing a nonexistent key is rejected" "! '$PV' doc remove single-1 nope >/dev/null 2>&1"
"$PV" doc remove single-1 sub > /dev/null 2>&1
chk "removing the last document is refused" "! '$PV' doc remove single-1 rr >/dev/null 2>&1"
chk "refusing to remove the last document leaves DOCS unchanged" "grep -qx 'DOCS=rr=답변서:submission/review_response/review_response.tex' '$env_single'"

echo "── 10. run with DOCS; MAIN/DOCS conflict; documents in list/status/snippet ──"
argv=$(LIMN_PRINT_ARGV=1 "$PV" run docs-1 2> "$T/docs-run.err")
rc=$?
chk "run builds four --doc arguments and no --main" \
    "[[ $rc -eq 0 ]] && grep -qx -- '--doc' <<< \"\$argv\" \
     && grep -qx 'ms=본문:main.tex' <<< \"\$argv\" \
     && grep -qx 'rr=답변서:submission/review_response/review_response.tex' <<< \"\$argv\" \
     && grep -qx 'sub=제출본 PDF:submission/submission_ready/manuscript.pdf' <<< \"\$argv\" \
     && grep -qx 'wd=넓게:wide::deep/main2.tex' <<< \"\$argv\" \
     && ! grep -qx -- '--main' <<< \"\$argv\""

printf 'MAIN=main.tex\n' >> "$T/src/docs-1.env"
chk "run refuses a config with both MAIN and DOCS" \
    "! LIMN_PRINT_ARGV=1 '$PV' run docs-1 > /dev/null 2> '$T/docs-conflict.err' && grep -q 'MAIN' '$T/docs-conflict.err'"
sed -i.bak '/^MAIN=/d' "$T/src/docs-1.env" && rm -f "$T/src/docs-1.env.bak"

lst2=$("$PV" list 2>&1)
chk "list's docs column shows 4 for docs-1" "awk '\$1==\"docs-1\"{print \$7}' <<< \"\$lst2\" | grep -qx 4"
st=$("$PV" status docs-1 2>&1)
chk "status shows the document count and key list" "grep -q 'docs         4: ms,rr,sub,wd' <<< \"\$st\""
snip=$("$PV" snippet docs-1 2>&1)
chk "snippet shows the doc key list, the #doc= link, and the pins.md subsection hint" \
    "grep -q 'Docs: ms,rr,sub,wd' <<< \"\$snip\" && grep -q '#doc=<key>' <<< \"\$snip\" && grep -q 'pins.md' <<< \"\$snip\""

echo "── 11. default document tab auto-detection (manuscript/<round> + submission/{...}) ──"
std="$T/std-paper"
mkdir -p "$std/manuscript/1st" "$std/manuscript/2nd" "$std/manuscript/changes" \
    "$std/submission/highlights" "$std/submission/cover_letter" "$std/submission/review_response"
printf '\\documentclass{article}\n\\begin{document}v1\\end{document}\n' > "$std/manuscript/1st/main_v1.tex"
printf '\\documentclass{article}\n\\begin{document}v2\\end{document}\n' > "$std/manuscript/2nd/main_v2.tex"
: > "$std/manuscript/changes/notes.tex" # a folder that doesn't start with a number → excluded from round candidates
printf '\\documentclass{article}\n\\begin{document}hl\\end{document}\n' > "$std/submission/highlights/highlights.tex"
printf '\\documentclass{article}\n\\begin{document}cl\\end{document}\n' > "$std/submission/cover_letter/cover_letter.tex"
printf '\\documentclass{article}\n\\begin{document}rr\\end{document}\n' > "$std/submission/review_response/review_response.tex"

sug=$("$PV" doc suggest --manuscript "$std" 2>&1)
chk "doc suggest (initial stage, no reviews/): latest round (2nd) · rr excluded · hl, cl order" \
    "[[ \"\$sug\" == 'ms=본문:manuscript::2nd/main_v2.tex;hl=하이라이트:submission/highlights/highlights.tex;cl=커버레터:submission/cover_letter/cover_letter.tex' ]]"
chk "doc suggest writes nothing" "[[ ! -e '$T/src/std-paper.env' && ! -e '$std/limn.env' ]]"

mkdir -p "$std/reviews"
sug=$("$PV" doc suggest --manuscript "$std" 2>&1)
chk "doc suggest (revision stage, reviews/ present): ms, rr, hl, cl order" \
    "[[ \"\$sug\" == 'ms=본문:manuscript::2nd/main_v2.tex;rr=답변서:submission/review_response/review_response.tex;hl=하이라이트:submission/highlights/highlights.tex;cl=커버레터:submission/cover_letter/cover_letter.tex' ]]"
sug=$("$PV" doc suggest --manuscript "$std" --stage initial 2>&1)
chk "--stage initial drops rr even if reviews/ exists" \
    "[[ \"\$sug\" == 'ms=본문:manuscript::2nd/main_v2.tex;hl=하이라이트:submission/highlights/highlights.tex;cl=커버레터:submission/cover_letter/cover_letter.tex' ]]"
sug=$("$PV" doc suggest --manuscript "$std" --stage revision 2>&1)
chk "explicit --stage revision gives the same result" \
    "[[ \"\$sug\" == 'ms=본문:manuscript::2nd/main_v2.tex;rr=답변서:submission/review_response/review_response.tex;hl=하이라이트:submission/highlights/highlights.tex;cl=커버레터:submission/cover_letter/cover_letter.tex' ]]"

std2="$T/std-paper-no-optional"
mkdir -p "$std2/manuscript/1st" "$std2/submission/review_response" "$std2/reviews"
printf '\\documentclass{article}\n\\begin{document}v1\\end{document}\n' > "$std2/manuscript/1st/main.tex"
printf '\\documentclass{article}\n\\begin{document}rr\\end{document}\n' > "$std2/submission/review_response/review_response.tex"
sug=$("$PV" doc suggest --manuscript "$std2" 2>&1)
chk "missing hl/cl files just drop those tabs (only ms, rr remain)" \
    "[[ \"\$sug\" == 'ms=본문:manuscript::1st/main.tex;rr=답변서:submission/review_response/review_response.tex' ]]"

chk "doc suggest is rejected for a non-standard layout (non-standard → provide --doc by hand)" \
    "! '$PV' doc suggest --manuscript '$ms' >/dev/null 2>&1"
# The adds below give explicit --port/--ts-port because §2/§8/§9 have already used up most of the
# TS_MIN-TS_MAX (18005-18012) auto-assign pool — this avoids unrelated failures from pool exhaustion
# (this section's focus is DOCS content, not ports).
"$PV" add nonstd --manuscript "$ms" --port 19101 --ts-port 19001 --no-serve --no-start > /dev/null 2>&1
chk "add also falls back to single MAIN without --main/--doc on the same manuscript (no manuscript/<round> structure) — same as the old behavior" \
    "grep -qx 'MAIN=main.tex' '$T/src/nonstd.env' && ! grep -q '^DOCS=' '$T/src/nonstd.env'"

out=$("$PV" add std-auto --manuscript "$std" --port 19102 --ts-port 19002 --no-serve --no-start 2>&1)
rc=$?
env_std="$T/src/std-auto.env"
chk "add auto-detects the standard layout without --doc/--main" "[[ $rc -eq 0 ]]"
chk "prints the auto-detected result line by line" \
    "grep -q 'auto-detected documents:' <<< \"\$out\" && grep -qF '  ms=본문:manuscript::2nd/main_v2.tex' <<< \"\$out\" && grep -qF '  rr=답변서:submission/review_response/review_response.tex' <<< \"\$out\""
chk "DOCS is stored in ms, rr, hl, cl order" \
    "grep -qx 'DOCS=ms=본문:manuscript::2nd/main_v2.tex;rr=답변서:submission/review_response/review_response.tex;hl=하이라이트:submission/highlights/highlights.tex;cl=커버레터:submission/cover_letter/cover_letter.tex' '$env_std'"
chk "the auto-detect path also leaves no MAIN line" "! grep -q '^MAIN=' '$env_std'"

out=$("$PV" add std-explicit --manuscript "$std" --port 19103 --ts-port 19003 --no-serve --no-start \
    --doc 'x=문서:submission/highlights/highlights.tex' 2>&1)
chk "an explicit --doc skips auto-detection" "grep -qx 'DOCS=x=문서:submission/highlights/highlights.tex' '$T/src/std-explicit.env'"
chk "the explicit --doc path doesn't print 'auto-detected documents:'" "! grep -q 'auto-detected documents:' <<< \"\$out\""

chk "--stage is only allowed for auto-detection without --doc/--main (rejected together with explicit --main)" \
    "! '$PV' add std-bad --manuscript '$std' --main manuscript/2nd/main_v2.tex --stage initial --no-start >/dev/null 2>&1"

echo "── 12. when there are multiple body candidates inside a round folder: git commit time → mtime → fail on tie ──"
GITBIN=$(command -v git || true)
if [[ -z "$GITBIN" ]]; then
    printf '  · git not found — skipping section 12\n'
else
    # 12a. outside a git repo (untracked): picked by mtime.
    mt="$T/mtime-tie"
    mkdir -p "$mt/manuscript/1st"
    printf '\\documentclass{article}\n\\begin{document}old\\end{document}\n' > "$mt/manuscript/1st/old.tex"
    printf '\\documentclass{article}\n\\begin{document}new\\end{document}\n' > "$mt/manuscript/1st/new.tex"
    touch -d '2020-01-01 00:00:00' "$mt/manuscript/1st/old.tex" 2> /dev/null || touch -t 202001010000 "$mt/manuscript/1st/old.tex"
    touch -d '2024-01-01 00:00:00' "$mt/manuscript/1st/new.tex" 2> /dev/null || touch -t 202401010000 "$mt/manuscript/1st/new.tex"
    sug=$("$PV" doc suggest --manuscript "$mt" 2>&1)
    chk "outside a git repo (untracked), picks the candidate with the more recent mtime" \
        "[[ \"\$sug\" == 'ms=본문:manuscript::1st/new.tex' ]]"

    # 12b. inside a git repo: even with mtime faked the other way, git commit time wins.
    gt="$T/git-tie"
    mkdir -p "$gt/manuscript/1st"
    printf '\\documentclass{article}\n\\begin{document}a\\end{document}\n' > "$gt/manuscript/1st/a.tex"
    printf '\\documentclass{article}\n\\begin{document}b\\end{document}\n' > "$gt/manuscript/1st/b.tex"
    (
        cd "$gt" && "$GITBIN" init -q && "$GITBIN" config user.email t@t && "$GITBIN" config user.name t \
            && "$GITBIN" add manuscript/1st/a.tex \
            && GIT_AUTHOR_DATE='2020-01-01T00:00:00' GIT_COMMITTER_DATE='2020-01-01T00:00:00' "$GITBIN" commit -q -m a \
            && "$GITBIN" add manuscript/1st/b.tex \
            && GIT_AUTHOR_DATE='2024-01-01T00:00:00' GIT_COMMITTER_DATE='2024-01-01T00:00:00' "$GITBIN" commit -q -m b
    ) > /dev/null 2>&1
    # mtime is reversed: a.tex is faked to look more recent — git commit time (b is more recent) must win.
    touch -d '2030-01-01 00:00:00' "$gt/manuscript/1st/a.tex" 2> /dev/null || touch -t 203001010000 "$gt/manuscript/1st/a.tex"
    sug=$("$PV" doc suggest --manuscript "$gt" 2>&1)
    chk "git commit time takes priority over mtime (picks b.tex, the more recently committed, even though mtime says a.tex is newer)" \
        "[[ \"\$sug\" == 'ms=본문:manuscript::1st/b.tex' ]]"

    # 12c. added together in the same commit, so even the commit times tie — fails instead of guessing.
    tie="$T/git-equal"
    mkdir -p "$tie/manuscript/1st"
    printf '\\documentclass{article}\n\\begin{document}x\\end{document}\n' > "$tie/manuscript/1st/x.tex"
    printf '\\documentclass{article}\n\\begin{document}y\\end{document}\n' > "$tie/manuscript/1st/y.tex"
    (
        cd "$tie" && "$GITBIN" init -q && "$GITBIN" config user.email t@t && "$GITBIN" config user.name t \
            && "$GITBIN" add manuscript/1st/x.tex manuscript/1st/y.tex \
            && GIT_AUTHOR_DATE='2022-01-01T00:00:00' GIT_COMMITTER_DATE='2022-01-01T00:00:00' "$GITBIN" commit -q -m both
    ) > /dev/null 2>&1
    err=$("$PV" doc suggest --manuscript "$tie" 2>&1)
    rc=$?
    chk "exits non-zero instead of guessing when even the commit times tie (doc suggest)" "[[ $rc -ne 0 ]]"
    chk "the failure message shows both candidate filenames" "grep -q 'x.tex' <<< \"\$err\" && grep -q 'y.tex' <<< \"\$err\""
    chk "the failure message points to --doc" "grep -q -- '--doc' <<< \"\$err\""

    out=$("$PV" add git-equal --manuscript "$tie" --port 19104 --ts-port 19004 --no-serve --no-start 2>&1)
    rc=$?
    chk "add also fails on a tie and leaves no config behind" "[[ $rc -ne 0 ]] && [[ ! -e '$T/src/git-equal.env' ]]"
    chk "add's failure message also shows the candidates and points to --doc" "grep -q 'x.tex' <<< \"\$out\" && grep -q 'y.tex' <<< \"\$out\" && grep -q -- '--doc' <<< \"\$out\""
fi

echo "── 13. access control keys (v0.2): AUTH, AGENT_LOOPBACK, BIND, … → server flags ──"
# A v0.1-style config written by hand (no access keys) must give exactly the v0.1 argv.
mkdir -p "$T/data/v01"
cat > "$T/config/v01.env" << EOF
# limn@v01 — a config as v0.1 wrote it
LABEL="Paper V"
MANUSCRIPT=$ms
MAIN=main.tex
PORT=19130
TS_PORT=19030
STATE_DIR=$T/data/v01
GIT_PULL=1
EXTRA_ARGS=--no-build
EOF
argv=$(LIMN_PRINT_ARGV=1 "$PV" run v01 2> "$T/v01.err")
want=$(printf '%s\n' "$PY" "$ROOT/src/limn/server.py" --manuscript "$ms" --port 19130 --state-dir "$T/data/v01" \
    --main main.tex --git-pull --label "Paper V" --no-build)
chk "a v0.1 config (no access keys) yields exactly the v0.1 argv" "[[ \"\$argv\" == \"\$want\" ]]"

acc="$T/config/acc.env"
cp "$T/config/v01.env" "$acc"
sed -i.bak 's#^STATE_DIR=.*#STATE_DIR='"$T"'/data/acc#' "$acc" && rm -f "$acc.bak"
cat >> "$acc" << 'EOF'
AUTH=trusted-proxy
AGENT_LOOPBACK=0
BIND=0.0.0.0
PUBLIC_HOSTS=limn.example.com,alt.example.com:8443
TRUSTED_PROXIES=10.0.0.5,::1
PROXY_USER_HEADER=X-Auth-User
PROXY_NAME_HEADER=X-Auth-Name
PROXY_EMAIL_HEADER=X-Auth-Email
MEMBERS_ONLY=1
LOCAL_USER=alice
EOF
argv=$(LIMN_PRINT_ARGV=1 "$PV" run acc 2> "$T/acc.err")
rc=$?
pair() { grep -A1 -x -- "$1" <<< "$argv" | sed -n 2p; }
chk "run with access keys succeeds" "[[ $rc -eq 0 ]]"
chk "AUTH → --auth" "[[ \$(pair --auth) == trusted-proxy ]]"
chk "AGENT_LOOPBACK=0 → --no-agent-loopback" "grep -qx -- '--no-agent-loopback' <<< \"\$argv\" && ! grep -qx -- '--agent-loopback' <<< \"\$argv\""
chk "BIND → --bind" "[[ \$(pair --bind) == 0.0.0.0 ]]"
chk "PUBLIC_HOSTS → --public-host" "[[ \$(pair --public-host) == 'limn.example.com,alt.example.com:8443' ]]"
chk "TRUSTED_PROXIES → --trusted-proxies" "[[ \$(pair --trusted-proxies) == '10.0.0.5,::1' ]]"
chk "PROXY_*_HEADER → the header flags" "[[ \$(pair --proxy-user-header) == X-Auth-User && \$(pair --proxy-name-header) == X-Auth-Name && \$(pair --proxy-email-header) == X-Auth-Email ]]"
chk "MEMBERS_ONLY=1 → --members-only" "grep -qx -- '--members-only' <<< \"\$argv\""
chk "LOCAL_USER → --local-user" "[[ \$(pair --local-user) == alice ]]"
chk "the packaged server accepts every access flag run builds" \
    "\"$PY\" '$ROOT/src/limn/server.py' --help > '$T/help.txt' && for f in --auth --no-agent-loopback --agent-loopback --tailnet-agent --bind --public-host --trusted-proxies --proxy-user-header --proxy-name-header --proxy-email-header --members-only --local-user --i-know-this-is-insecure; do grep -q -- \"\$f\" '$T/help.txt' || exit 1; done"

badrun() { # badrun <label> <KEY=VALUE lines...> — the v0.1 config plus these lines must be refused with a message
    local label=$1
    shift
    cp "$T/config/v01.env" "$T/config/bad.env"
    printf '%s\n' "$@" >> "$T/config/bad.env"
    chk "$label" "! LIMN_PRINT_ARGV=1 '$PV' run bad > /dev/null 2> '$T/bad.err' && grep -q . '$T/bad.err'"
}
badrun "rejects an unknown AUTH" "AUTH=oidc"
badrun "rejects AGENT_LOOPBACK other than 0/1" "AGENT_LOOPBACK=yes"
badrun "rejects MEMBERS_ONLY other than 0/1" "MEMBERS_ONLY=true"
badrun "rejects a BIND that is not an IP address" "BIND=example.com"
badrun "refuses a non-loopback BIND without AUTH=trusted-proxy (no restart loop)" "BIND=0.0.0.0"
badrun "refuses AGENT_LOOPBACK=1 under AUTH=local" "AUTH=local" "AGENT_LOOPBACK=1"
badrun "refuses AGENT_LOOPBACK=1 with a non-loopback BIND" "AUTH=trusted-proxy" "BIND=0.0.0.0" "AGENT_LOOPBACK=1"
badrun "rejects TAILNET_AGENT other than 0/1" "TAILNET_AGENT=on"
badrun "refuses TAILNET_AGENT=1 with AGENT_LOOPBACK=0" "TAILNET_AGENT=1" "AGENT_LOOPBACK=0"
badrun "refuses TAILNET_AGENT=1 under AUTH=local" "AUTH=local" "TAILNET_AGENT=1"
badrun "rejects a malformed PUBLIC_HOSTS" "PUBLIC_HOSTS=https://x.example.com/"
badrun "rejects a malformed TRUSTED_PROXIES" "TRUSTED_PROXIES=proxy.example.com"
badrun "rejects a malformed proxy header name" "PROXY_USER_HEADER=X User"
cp "$T/config/v01.env" "$T/config/insec.env"
printf 'BIND=0.0.0.0\nEXTRA_ARGS="--no-build --i-know-this-is-insecure"\n' >> "$T/config/insec.env"
argv=$(LIMN_PRINT_ARGV=1 "$PV" run insec 2> /dev/null)
chk "a non-loopback BIND is accepted with --i-know-this-is-insecure in EXTRA_ARGS" "grep -qx -- '--i-know-this-is-insecure' <<< \"\$argv\" && [[ \$(grep -A1 -x -- --bind <<< \"\$argv\" | sed -n 2p) == 0.0.0.0 ]]"
cp "$T/config/v01.env" "$T/config/lb1.env"
printf 'AGENT_LOOPBACK=1\n' >> "$T/config/lb1.env"
chk "AGENT_LOOPBACK=1 → --agent-loopback (tailscale, loopback)" "LIMN_PRINT_ARGV=1 '$PV' run lb1 2>/dev/null | grep -qx -- '--agent-loopback'"
cp "$T/config/v01.env" "$T/config/tn1.env"
printf 'TAILNET_AGENT=1\n' >> "$T/config/tn1.env"
chk "TAILNET_AGENT=1 → --tailnet-agent (v0.2.1 opt-in)" "LIMN_PRINT_ARGV=1 '$PV' run tn1 2>/dev/null | grep -qx -- '--tailnet-agent'"
chk "a v0.1 config adds no --tailnet-agent" "! LIMN_PRINT_ARGV=1 '$PV' run v01 2>/dev/null | grep -q -- '--tailnet-agent'"

"$PV" add acc-add --manuscript "$ms" --port 19131 --ts-port 19031 --auth local --no-serve --no-start > /dev/null 2>&1
chk "add --auth local writes AUTH=local" "grep -qx 'AUTH=local' '$T/src/acc-add.env'"
chk "add without --auth writes no AUTH line (server default = tailscale)" "! grep -q '^AUTH=' '$T/src/nonstd.env'"
chk "add rejects an unknown --auth" "! '$PV' add acc-bad --manuscript '$ms' --port 19132 --ts-port 19032 --auth oidc --no-start >/dev/null 2>&1 && [[ ! -e '$T/src/acc-bad.env' ]]"
chk "add --auth local refuses tailscale serve (every tailnet member would be the owner)" \
    "! '$PV' add acc-ser --manuscript '$ms' --port 19133 --ts-port 19033 --auth local >/dev/null 2>&1 && [[ ! -e '$T/src/acc-ser.env' ]]"
chk "start refuses to serve an AUTH=local instance" "! '$PV' start acc-add > /dev/null 2> '$T/acc-start.err' && grep -q 'owner' '$T/acc-start.err' && ! grep -q 'serve --bg' '$STUB_LOG'"
"$PV" doc add acc-add --doc 'rr=답변서:submission/review_response/review_response.tex' > /dev/null 2>&1
chk "doc add keeps the access keys when it rewrites the config" "grep -qx 'AUTH=local' '$T/src/acc-add.env' && grep -q '^DOCS=' '$T/src/acc-add.env'"

echo "── 14. limn token / limn member resolve the instance's state dir ──"
tok=$("$PV" token create v01 --name ci 2> "$T/tok.err")
chk "token create prints the token on stdout only" "[[ \"\$tok\" == limn_* && \$(wc -l <<< \"\$tok\") -eq 1 ]]"
chk "the token lands in STATE_DIR from the config, hashed and 0600" \
    "[[ -f '$T/data/v01/tokens.json' && \$(mode_of '$T/data/v01/tokens.json') == 600 ]] && ! grep -qF \"\$tok\" '$T/data/v01/tokens.json' && grep -q '\"name\": \"ci\"' '$T/data/v01/tokens.json'"
chk "token list shows the name, never the token" "'$PV' token list v01 | grep -q ' ci ' && ! '$PV' token list v01 | grep -qF \"\$tok\""
chk "token revoke by name" "'$PV' token revoke v01 ci >/dev/null && ! grep -q '\"name\": \"ci\"' '$T/data/v01/tokens.json'"
chk "token on an unknown instance fails" "! '$PV' token list nope >/dev/null 2>&1"
chk "member add/role/list via the instance name" \
    "'$PV' member add v01 alice@example.com --role viewer >/dev/null && '$PV' member role v01 alice@example.com editor >/dev/null && '$PV' member list v01 | grep -qE '^alice@example.com +editor'"
chk "member remove" "'$PV' member remove v01 alice@example.com >/dev/null && ! grep -q alice '$T/data/v01/people.json'"
chk "--state-dir instead of an instance" "'$PV' member add --state-dir '$T/data/plain' bob@example.com >/dev/null && grep -q bob@example.com '$T/data/plain/people.json'"
"$PV" help > "$T/help.out" 2>&1
chk "limn help lists token and member" "grep -q 'limn token create' '$T/help.out' && grep -q 'limn member add' '$T/help.out' && grep -q -- '--auth' '$T/help.out'"

echo "── 16. portability: Python >= 3.10, timeout without GNU coreutils ──"
mkdir -p "$T/py39" "$T/pynew"
printf '#!/bin/sh\n# a Python 3.9: too old for limn\nexit 1\n' > "$T/py39/python3"
chmod +x "$T/py39/python3"
ln -s "$(command -v dirname)" "$T/py39/dirname"
ln -s "$(command -v sed)" "$T/py39/sed" # for `help`
ln -s "$PY" "$T/pynew/python3.12"
IM="$ROOT/src/limn/instances.sh"
out=$(env -u LIMN_PYTHON LIMN_PRINT_ARGV=1 PATH="$T/py39:$T/pynew:$PATH" bash "$IM" run v01 2>&1)
chosen=$(sed -n 1p <<< "$out")
chk "run directly: skips a python3 older than 3.10 for a newer python3.1x on PATH" "[[ '$chosen' != '$T/py39/python3' && -x '$chosen' ]] && py_ok '$chosen'"
out=$(env -u LIMN_PYTHON PATH="$T/py39" "$BASH" "$IM" list 2>&1)
chk "run directly with only an old python3: stops with a clear message" "grep -q 'no Python >= 3.10 found' <<< \"\$out\""
out=$(LIMN_PYTHON="$T/py39/python3" PATH="$T/pynew:$PATH" bash "$IM" list 2>&1)
chk "an explicit LIMN_PYTHON that is too old is an error, not silently replaced" "grep -qF 'LIMN_PYTHON=$T/py39/python3 is not Python >= 3.10' <<< \"\$out\""
chk "help still works without a Python" "env -u LIMN_PYTHON PATH='$T/py39' '$BASH' '$IM' help | grep -q 'limn add'"
# with_timeout: no timeout(1)/gtimeout (stock macOS) -> perl's alarm still bounds the command.
if command -v perl > /dev/null 2>&1; then
    mkdir -p "$T/notimeout"
    ln -s "$(command -v perl)" "$T/notimeout/perl"
    ln -s "$(command -v sleep)" "$T/notimeout/sleep"
    sed -n '/^with_timeout()/,/^}/p' "$IM" > "$T/with_timeout.sh"
    chk "with_timeout without timeout(1) still stops a hung command (perl alarm)" \
        "PATH='$T/notimeout' '$BASH' -c '. \"\$1\"; type with_timeout > /dev/null && s=\$SECONDS && { with_timeout 1 sleep 5 2> /dev/null; rc=\$?; (( rc != 0 && SECONDS - s < 4 )); }' x '$T/with_timeout.sh' 2> /dev/null"
    chk "with_timeout without timeout(1) passes a quick command's status through" \
        "PATH='$T/notimeout' '$BASH' -c '. \"\$1\"; with_timeout 5 sleep 0' x '$T/with_timeout.sh'"
fi

printf '\n  %d passed, %d failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
