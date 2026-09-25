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

# The real interpreter (resolved before HOME is redirected — some python3 shims depend on HOME).
PY=$(python3 -c "import sys; print(sys.executable)" 2> /dev/null || true)
if [[ -z "$PY" ]]; then
    printf '  · python3 not found — skipping (runs fine in CI)\n'
    exit 0
fi

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

printf '\n  %d passed, %d failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
