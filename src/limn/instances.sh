#!/usr/bin/env bash
# Limn instance manager — brings up and manages one `limn@<name>.service` instance per manuscript (paper).
#
# Each paper has its own repository, and when two papers are being worked on at once, Limn has to run
# separately for each too. So each instance gets its own port, state dir (pins, build, build.log), and
# journal, while sharing a single installed limn package. Structure and procedure: docs/handbook/instances.md.
#
# This script is invoked by the `limn` command (limn.cli). Do not call it directly — the CLI passes the
# server path, Python, and version number in via LIMN_SERVER/LIMN_PYTHON/LIMN_VERSION.
#
# Usage:
#   limn add <name> --manuscript <manuscript dir> [--main <file.tex>] [--port N] [--ts-port N]
#                  [--git-pull] [--label <label>] [--accent <#rrggbb>] [--state-dir <dir>]
#                  [--extra "<server args>"] [--no-serve] [--no-start] [--auth tailscale|local|trusted-proxy]
#                  [--doc <key>=<display name>:<path> ...]   (not used together with --main. §Multiple documents)
#                  [--stage auto|initial|revision]        (only for auto-detection without --doc/--main. §Default tab auto-detection)
#
# Default tab auto-detection: if neither --doc nor --main is given and the manuscript dir has the
# standard paper-repo structure (manuscript/<round>/<main>.tex,
# submission/{highlights,cover_letter,review_response}/*.tex), DOCS is built in the order
# ms=body(latest round) · rr=response letter(revision stage only, and only if the file exists) ·
# hl=highlights · cl=cover letter. Default --stage is auto (revision if <manuscript dir>/reviews/
# exists). If the layout doesn't match, falls back to single-MAIN detection.
#   limn doc suggest --manuscript <manuscript dir> [--stage auto|initial|revision]
#                                          prints only the DOCS string the above auto-detection would pick (read-only)
#   limn start <name> [--no-serve]         turns on an instance whose config already exists (after reboot, new machine, switch)
#   limn stop <name>                       stops only the unit (config, port, serve entry stay as-is)
#   limn update [--ref <tag|branch>] [--from <install source>] [--dry-run] [--force] [--no-restart]
#                                          reinstalls limn (uv tool) and restarts instances that are on
#   limn list                              instance table (label, port, status, open pins, doc count, manuscript)
#   limn status [<name>]                   detailed (includes document list)
#   limn url [<name>]                      tailnet address
#   limn snippet <name>                    prints the blurb to paste into that paper repo's AGENTS.md (print only)
#   limn doc list <name>                            document key/name/path table
#   limn doc add <name> --doc '<key>=<name>:<path>' [--doc …] [--restart]
#                                          adds a document to an existing instance. If it was a single
#                                          document (MAIN), moves the body into the first entry main=body:<MAIN> and switches it to DOCS
#   limn doc remove <name> <key> [--restart]   removes one document from DOCS (refuses to remove the last document)
#   limn remove <name>                     stops and disables the unit, unserves it, deletes the config (= port reservation).
#                                          does not delete the state dir
#   limn run <name>                        (unit-only) reads the config and execs into the server
#   limn token create|path|list|revoke <name> … agent API tokens (create --save writes <config dir>/<name>.token);
#                                          limn member add|list|remove|role <name> … roles
#                                          (Python, see limn help — they edit the instance's state dir)
#
# Access control (v0.2, docs/handbook/instances.md §설정 키): AUTH, AGENT_LOOPBACK, TAILNET_AGENT, BIND, PUBLIC_HOSTS,
# TRUSTED_PROXIES, PROXY_USER_HEADER/PROXY_NAME_HEADER/PROXY_EMAIL_HEADER, MEMBERS_ONLY, LOCAL_USER map to
# the server flags of the same meaning. Unset keys add no flag, so a v0.1 config runs exactly as before.
#
# Multiple documents (--doc, DOCS=): a single instance switches between tabs for the body, response
# letter, a view-only PDF, and so on. Format is <key>=<display name>:<path>. Keys are [a-z0-9-]{1,24},
# no duplicates, up to 12 documents, and paths must be inside --manuscript. `<build root>::<main.tex>`
# is an extended notation (LaTeX only) that widens the copy scope to the build root. In the config file
# this is written as DOCS="<key1>=<name1>:<path1>;<key2>=..." (split on `;`). MAIN and DOCS are not
# used together — see docs/handbook/operations.md §여러 문서 for the full contract.

# Security rules (do not change): the server binds 127.0.0.1 unless BIND says otherwise, and a non-loopback
# BIND is refused unless AUTH=trusted-proxy (or EXTRA_ARGS carries --i-know-this-is-insecure). Tailnet
# exposure only via `tailscale serve`, and only for the tailscale provider (AUTH unset or tailscale — under
# local or trusted-proxy it would hand out identities). funnel is never used, sudo is never invoked.
# tailscale operator must be this user for serve to work without sudo — if it isn't, it errors out and
# stops (permissions are never changed automatically).

set -uo pipefail
unset CDPATH

# ── paths (can be overridden via LIMN_* — so tests don't touch the real home) ──
_XDG_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
_XDG_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DATA_ROOT="${LIMN_DATA_ROOT:-$_XDG_DATA/limn}"
CONFIG_DIR="${LIMN_CONFIG_DIR:-$_XDG_CONFIG/limn}"
# Config source dir (optional). If configs are version-controlled in another repo (e.g. dotfiles),
# point here — add writes the source there and symlinks it into CONFIG_DIR. Empty means write
# straight into CONFIG_DIR.
SOURCE_DIR="${LIMN_SOURCE_DIR:-$CONFIG_DIR}"
USER_UNIT_DIR="${LIMN_USER_UNIT_DIR:-$_XDG_CONFIG/systemd/user}"
# Port ledger (optional). A file listing ports advertised by other serving units on this machine;
# read and avoided if present. If LIMN_LEDGER_GEN points to a generator (a script that takes
# <unit dir> <config dir...> and prints "<port> <unit>" lines), the ledger is regenerated after
# add/remove. If not set, the ledger is never written (so we don't half-overwrite someone else's file).
LEDGER="${LIMN_LEDGER:-$_XDG_CONFIG/served/reserved-ports.txt}"
LEDGER_GEN="${LIMN_LEDGER_GEN:-}"
LEDGER_UNITS_DIR="${LIMN_LEDGER_UNITS_DIR:-$USER_UNIT_DIR}"
# Auto-assign band: pairs tailnet port N with local port N+100 (18004↔18104) — the pairing is obvious from the address alone.
TS_MIN="${LIMN_TS_MIN:-18005}"
TS_MAX="${LIMN_TS_MAX:-18099}"
LOCAL_OFFSET="${LIMN_LOCAL_OFFSET:-100}"
# Passed in by the CLI: the installed limn's Python, server, unit template, executable, and version.
# The server needs Python >= 3.10 (pyproject requires-python; server.py uses `match`, so 3.9 cannot even parse it and
# would die with a bare SyntaxError). The CLI passes the interpreter it runs on, which satisfies that by construction;
# run directly (tests, a checkout), the first python3 / python3.1x on PATH that does is used. macOS ships a
# /usr/bin/python3 3.9, so the first python3 found is not good enough by itself. Every command but help calls the
# interpreter (the helpers below use it), so it is chosen and checked here, once, and main() stops with the reason
# before any command runs.
PY_MIN_MAJOR=3 PY_MIN_MINOR=10
PY_FIX="run it through the installed limn command, or set LIMN_PYTHON to a Python >= $PY_MIN_MAJOR.$PY_MIN_MINOR"
py_version() { # py_version <interpreter> — prints its version (3.9.6); fails when it does not run as Python
    "$1" -c 'import sys; print("%d.%d.%d" % tuple(sys.version_info[:3]))' 2> /dev/null
}
py_new_enough() { # py_new_enough <version> — is <version> (3.9.6) at least PY_MIN_MAJOR.PY_MIN_MINOR?
    local major minor
    IFS=. read -r major minor _ <<< "$1"
    [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1
    ((major > PY_MIN_MAJOR || (major == PY_MIN_MAJOR && minor >= PY_MIN_MINOR)))
}
# find_python — prints the interpreter to use; fails when there is none, with a one-line reason on stderr that names
# the interpreter, its version and the fix. LIMN_PYTHON is an explicit choice, so a too-old one is an error rather
# than silently replaced.
find_python() {
    local c p v first=""
    if [[ -n "${LIMN_PYTHON:-}" ]]; then
        if ! v=$(py_version "$LIMN_PYTHON"); then
            printf 'LIMN_PYTHON=%s does not run as Python — %s\n' "$LIMN_PYTHON" "$PY_FIX" >&2
            return 1
        fi
        py_new_enough "$v" && {
            printf '%s' "$LIMN_PYTHON"
            return 0
        }
        printf 'LIMN_PYTHON=%s is Python %s, limn needs >= %s.%s — %s\n' \
            "$LIMN_PYTHON" "$v" "$PY_MIN_MAJOR" "$PY_MIN_MINOR" "$PY_FIX" >&2
        return 1
    fi
    for c in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
        p=$(command -v "$c" 2> /dev/null) || continue
        if ! v=$(py_version "$p"); then
            [[ -n "$first" ]] || first="$p does not run as Python"
            continue
        fi
        py_new_enough "$v" && {
            printf '%s' "$p"
            return 0
        }
        [[ -n "$first" ]] || first="$p is Python $v"
    done
    printf 'no Python >= %s.%s on PATH (%s) — %s\n' \
        "$PY_MIN_MAJOR" "$PY_MIN_MINOR" "${first:-no python3 or python3.1x there}" "$PY_FIX" >&2
    return 1
}
PYTHON=$(find_python 2> /dev/null) || PYTHON=""
PYTHON_WHY="" # why there is none - main() stops with it, except for help
[[ -n "$PYTHON" ]] || PYTHON_WHY=$(find_python 2>&1 > /dev/null)
_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="${LIMN_SERVER:-$_HERE/server.py}"
UNIT_TEMPLATE="${LIMN_UNIT_TEMPLATE:-$_HERE/systemd/limn@.service}"
LIMN_BIN="${LIMN_BIN:-$(command -v limn || printf '%s' "$HOME/.local/bin/limn")}"
VERSION="${LIMN_VERSION:-?}"
# Source that update reinstalls from (the form uv tool install accepts). If --ref is given, @<ref> is appended.
REPO="${LIMN_REPO:-git+https://github.com/dartworklabs/limn}"
UV="${LIMN_UV:-uv}"
WAIT_S="${LIMN_WAIT:-240}"

die() {
    printf 'limn: %s\n' "$*" >&2
    exit 1
}
say() { printf '%s\n' "$*"; }
warn() { printf 'limn: warning: %s\n' "$*" >&2; }

unit_of() { printf 'limn@%s.service' "$1"; }

# systemctl --user. SSH/non-login shells may not inherit the bus env vars even when the user
# manager is alive — recover the bus address via loginctl's RuntimePath (or /run/user/<uid> if unset).
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
    # `serve` collides with DATA_ROOT/serve, where `limn serve` keeps its state dir (the default state dir is DATA_ROOT/<name>).
    [[ "$1" != serve ]]
}
need_name() {
    [[ -n "${1:-}" ]] || die "a name is required"
    valid_name "$1" || die "name must match [a-z0-9-]+ (must start with a letter/digit, 'serve' is reserved): '$1'"
}
valid_port() { [[ "$1" =~ ^[0-9]+$ ]] && (($1 >= 1024 && $1 <= 65535)); }

# ── config file ──
# The format is a subset of a systemd EnvironmentFile: one `KEY=VALUE` line, values are bare or
# wrapped in one layer of double quotes. Never sourced by the shell — a config-file line must never
# become code. Writing rejects quotes/backslash/$/backtick/newline, so no two parsers can read it differently.
conf_of() { printf '%s/%s.env' "$CONFIG_DIR" "$1"; }
src_of() { printf '%s/%s.env' "$SOURCE_DIR" "$1"; }

env_get() { # env_get <file> <KEY>
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

# Reads an instance's config into C_* globals.
load() { # load <name>
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
    # Access control (v0.2). All optional — a v0.1 config sets none of them and runs exactly as before.
    C_AUTH=$(env_get "$f" AUTH)
    C_AGENT_LOOPBACK=$(env_get "$f" AGENT_LOOPBACK)
    C_TAILNET_AGENT=$(env_get "$f" TAILNET_AGENT)
    C_BIND=$(env_get "$f" BIND)
    C_PUBLIC_HOSTS=$(env_get "$f" PUBLIC_HOSTS)
    C_TRUSTED_PROXIES=$(env_get "$f" TRUSTED_PROXIES)
    C_PROXY_USER_HEADER=$(env_get "$f" PROXY_USER_HEADER)
    C_PROXY_NAME_HEADER=$(env_get "$f" PROXY_NAME_HEADER)
    C_PROXY_EMAIL_HEADER=$(env_get "$f" PROXY_EMAIL_HEADER)
    C_MEMBERS_ONLY=$(env_get "$f" MEMBERS_ONLY)
    C_LOCAL_USER=$(env_get "$f" LOCAL_USER)
}

# emit_access — the access-control keys of the loaded config (C_*), for rewriting a config without losing them.
emit_access() {
    emit AUTH "$C_AUTH"
    emit AGENT_LOOPBACK "$C_AGENT_LOOPBACK"
    emit TAILNET_AGENT "$C_TAILNET_AGENT"
    emit BIND "$C_BIND"
    emit PUBLIC_HOSTS "$C_PUBLIC_HOSTS"
    emit TRUSTED_PROXIES "$C_TRUSTED_PROXIES"
    emit PROXY_USER_HEADER "$C_PROXY_USER_HEADER"
    emit PROXY_NAME_HEADER "$C_PROXY_NAME_HEADER"
    emit PROXY_EMAIL_HEADER "$C_PROXY_EMAIL_HEADER"
    emit MEMBERS_ONLY "$C_MEMBERS_ONLY"
    emit LOCAL_USER "$C_LOCAL_USER"
}

valid_auth() { [[ "$1" == tailscale || "$1" == local || "$1" == trusted-proxy ]]; }

# is_loopback_addr <addr> — the same rule as the server's is_loopback_bind (127.0.0.0/8, ::1, localhost).
is_loopback_addr() {
    [[ "$1" == localhost || "$1" == 127.0.0.1 || "$1" == ::1 ]] && return 0
    "$PYTHON" -c 'import ipaddress, sys
sys.exit(0 if ipaddress.ip_address(sys.argv[1]).is_loopback else 1)' "$1" 2> /dev/null
}
valid_ip() {
    [[ "$1" == localhost ]] && return 0
    "$PYTHON" -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$1" 2> /dev/null
}

# access_args — validates the access keys of the loaded config and fills ACCESS_ARGS with server flags. Dies with
# a clear message on a value the server would refuse (instead of the unit restarting into the same error). Unset
# keys add no flag, so a v0.1 config yields exactly the v0.1 argv.
access_args() {
    ACCESS_ARGS=()
    local auth=${C_AUTH:-tailscale} bind=${C_BIND:-127.0.0.1} loop=1 h
    [[ -z "$C_AUTH" ]] || valid_auth "$C_AUTH" || die "AUTH must be tailscale, local or trusted-proxy: '$C_AUTH'"
    [[ -z "$C_AGENT_LOOPBACK" || "$C_AGENT_LOOPBACK" == 0 || "$C_AGENT_LOOPBACK" == 1 ]] || die "AGENT_LOOPBACK must be 0 or 1: '$C_AGENT_LOOPBACK'"
    [[ -z "$C_TAILNET_AGENT" || "$C_TAILNET_AGENT" == 0 || "$C_TAILNET_AGENT" == 1 ]] || die "TAILNET_AGENT must be 0 or 1: '$C_TAILNET_AGENT'"
    [[ -z "$C_MEMBERS_ONLY" || "$C_MEMBERS_ONLY" == 0 || "$C_MEMBERS_ONLY" == 1 ]] || die "MEMBERS_ONLY must be 0 or 1: '$C_MEMBERS_ONLY'"
    if [[ -n "$C_BIND" ]]; then
        valid_ip "$C_BIND" || die "BIND must be an IP address (or localhost): '$C_BIND'"
    fi
    is_loopback_addr "$bind" || loop=0
    if [[ "$loop" == 0 && "$auth" != trusted-proxy && " $C_EXTRA_ARGS " != *" --i-know-this-is-insecure "* ]]; then
        die "BIND=$bind is not loopback: set AUTH=trusted-proxy (behind an authenticating proxy), or keep 127.0.0.1 and use tailscale serve"
    fi
    if [[ "$C_AGENT_LOOPBACK" == 1 && ("$auth" != tailscale || "$loop" == 0) ]]; then
        die "AGENT_LOOPBACK=1 works only with AUTH=tailscale on a loopback BIND — give agents a token: limn token create <name>"
    fi
    if [[ "$C_TAILNET_AGENT" == 1 && ("$auth" != tailscale || "$loop" == 0 || "$C_AGENT_LOOPBACK" == 0) ]]; then
        die "TAILNET_AGENT=1 needs the loopback agent (AUTH=tailscale, a loopback BIND, AGENT_LOOPBACK not 0) — give remote agents a token instead: limn token create <name>"
    fi
    if [[ -n "$C_PUBLIC_HOSTS" ]]; then
        local hosts=() one
        IFS=',' read -ra hosts <<< "$C_PUBLIC_HOSTS"
        for one in "${hosts[@]}"; do
            [[ "$one" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$ ]] || die "PUBLIC_HOSTS takes host names with an optional :port, comma-separated: '$one'"
        done
    fi
    [[ -z "$C_TRUSTED_PROXIES" || "$C_TRUSTED_PROXIES" =~ ^[0-9A-Fa-f:.,/]+$ ]] || die "TRUSTED_PROXIES takes IP addresses/CIDR ranges, comma-separated: '$C_TRUSTED_PROXIES'"
    for h in "$C_PROXY_USER_HEADER" "$C_PROXY_NAME_HEADER" "$C_PROXY_EMAIL_HEADER"; do
        [[ -z "$h" || "$h" =~ ^[A-Za-z0-9][A-Za-z0-9-]*$ ]] || die "PROXY_*_HEADER takes an HTTP header name: '$h'"
    done
    [[ -z "$C_LOCAL_USER" || "$C_LOCAL_USER" =~ ^[A-Za-z0-9._@+-]+$ ]] || die "LOCAL_USER takes a login without spaces: '$C_LOCAL_USER'"
    [[ -n "$C_AUTH" ]] && ACCESS_ARGS+=(--auth "$C_AUTH")
    [[ "$C_AGENT_LOOPBACK" == 0 ]] && ACCESS_ARGS+=(--no-agent-loopback)
    [[ "$C_AGENT_LOOPBACK" == 1 ]] && ACCESS_ARGS+=(--agent-loopback)
    [[ "$C_TAILNET_AGENT" == 1 ]] && ACCESS_ARGS+=(--tailnet-agent)
    [[ -n "$C_BIND" ]] && ACCESS_ARGS+=(--bind "$C_BIND")
    [[ -n "$C_PUBLIC_HOSTS" ]] && ACCESS_ARGS+=(--public-host "$C_PUBLIC_HOSTS")
    [[ -n "$C_TRUSTED_PROXIES" ]] && ACCESS_ARGS+=(--trusted-proxies "$C_TRUSTED_PROXIES")
    [[ -n "$C_PROXY_USER_HEADER" ]] && ACCESS_ARGS+=(--proxy-user-header "$C_PROXY_USER_HEADER")
    [[ -n "$C_PROXY_NAME_HEADER" ]] && ACCESS_ARGS+=(--proxy-name-header "$C_PROXY_NAME_HEADER")
    [[ -n "$C_PROXY_EMAIL_HEADER" ]] && ACCESS_ARGS+=(--proxy-email-header "$C_PROXY_EMAIL_HEADER")
    [[ "$C_MEMBERS_ONLY" == 1 ]] && ACCESS_ARGS+=(--members-only)
    [[ -n "$C_LOCAL_USER" ]] && ACCESS_ARGS+=(--local-user "$C_LOCAL_USER")
    return 0
}

safe_value() { # is this value safe to write to a config file?
    # '\' below is a pattern for one literal backslash, not an attempt to escape a quote.
    # shellcheck disable=SC1003
    case "$1" in
        *'"'* | *"'"* | *'\'* | *'$'* | *'`'* | *$'\n'* | *$'\r'*) return 1 ;;
    esac
    return 0
}
emit() { # emit <KEY> <value> — emits no line at all if empty
    [[ -n "$2" ]] || return 0
    # Values containing whitespace or `#` get quoted (some parsers read `#` as a comment).
    if [[ "$2" == *[[:space:]]* || "$2" == *'#'* ]]; then printf '%s="%s"\n' "$1" "$2"; else printf '%s=%s\n' "$1" "$2"; fi
}

instances() { # names that have a config (home config + repo source)
    {
        local f
        for f in "$CONFIG_DIR"/*.env "$SOURCE_DIR"/*.env; do
            [[ -e "$f" ]] && basename "$f" .env
        done
    } | sort -u | while IFS= read -r n; do valid_name "$n" && printf '%s\n' "$n"; done
}

# ── port ledger ──
# The source of truth for port reservations is the instance config file (PORT=/TS_PORT=). The ledger
# file (LEDGER) is supplementary data listing ports advertised by other serving units on this
# machine — read if present, and only regenerated when a generator (LEDGER_GEN) is configured. Never
# hand-write the ledger.
own_port_lines() { # ports from instance configs → "<port> limn@<name>"
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
ledger_refresh() { # regenerates the ledger only when a generator is set. Otherwise nothing to do (the config file is already the reservation).
    [[ -n "$LEDGER_GEN" ]] || return 0
    mkdir -p "$(dirname "$LEDGER")" || return 1
    local t
    t=$(mktemp "$(dirname "$LEDGER")/.limn-ledger.XXXXXX") || return 1
    if "$LEDGER_GEN" "$LEDGER_UNITS_DIR" "$CONFIG_DIR" > "$t"; then
        mv -f "$t" "$LEDGER"
    else
        rm -f "$t"
        warn "could not regenerate the port ledger: $LEDGER"
        return 1
    fi
}

# tailnet serve entries: one line per "<tailnet port> <proxy target or -> <funnel 0|1>".
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

listening() { # is anything LISTENing on any address (also catches binds to only the tailnet IP)
    if command -v ss > /dev/null 2>&1; then
        [[ -n "$(ss -ltnH "sport = :$1" 2> /dev/null)" ]]
        return
    fi
    # If ss is unavailable (macOS), try binding to all addresses — fails if the port is taken.
    ! "$PYTHON" -c 'import socket,sys
s=socket.socket(); s.bind(("0.0.0.0", int(sys.argv[1]))); s.close()' "$1" 2> /dev/null
}

# Read the ledger and serve list only once while picking a port (re-reading per candidate would mean
# hundreds of generator/tailscale calls for one band scan). Only the LISTEN check runs per candidate.
snapshot_ports() {
    _SNAP_LEDGER=$(ledger_lines)
    _SNAP_TS=$(ts_map)
}
# port_taken <port> [<own name>] — if the ledger, LISTEN, or serve catches it, prints the reason and returns 0.
port_taken() {
    local p=$1 me=${2:-} who
    who=$(awk -v p="$p" -v me="limn@$me" '$1 == p && $2 != me { print $2; exit }' <<< "${_SNAP_LEDGER:-}")
    if [[ -n "$who" ]]; then printf 'reserved in the ledger(%s)' "$who"; return 0; fi
    if listening "$p"; then printf 'already LISTENing'; return 0; fi
    who=$(awk -v p="$p" '$1 == p { print $2; exit }' <<< "${_SNAP_TS:-}")
    if [[ -n "$who" ]]; then printf 'already used by tailscale serve(%s)' "$who"; return 0; fi
    return 1
}

pick_pair() { # one free (tailnet, local) pair
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
url_of() { # url_of <tailnet port>
    local h
    h=$(tailnet_host)
    if [[ -n "$h" ]]; then printf 'https://%s:%s/' "$h" "$1"; else printf 'https://<device>.<tailnet>.ts.net:%s/' "$1"; fi
}

# ── unit template ──
# Fills in the packaged limn@.service for this machine and writes it to USER_UNIT_DIR (a copy, not a
# symlink — the package path can change when uv reinstalls the tool). Fields filled in: the executable
# (@LIMN_BIN@), the config dir (@LIMN_CONFIG_DIR@), and the unit's PATH (@LIMN_PATH@ — systemd doesn't
# go through shell rc files, so it can't inherit the TeX path).
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
    [[ -f "$UNIT_TEMPLATE" ]] || die "unit template not found: $UNIT_TEMPLATE"
    local bin=$LIMN_BIN cfg=$CONFIG_DIR path
    path=$(unit_path)
    awk -v bin="$bin" -v cfg="$cfg" -v path="$path" '
        { gsub(/@LIMN_BIN@/, bin); gsub(/@LIMN_CONFIG_DIR@/, cfg); gsub(/@LIMN_PATH@/, path); print }' "$UNIT_TEMPLATE"
}
ensure_unit() {
    local dst="$USER_UNIT_DIR/limn@.service" want
    want=$(render_unit) || exit 1
    mkdir -p "$USER_UNIT_DIR" || die "could not create dir: $USER_UNIT_DIR"
    if [[ -e "$dst" || -L "$dst" ]]; then
        # Both must hold (a regular file carrying the marker); either failing dies - not an if/else.
        # shellcheck disable=SC2015
        [[ ! -L "$dst" ]] && grep -q '^# limn:generated' "$dst" \
            || die "$dst was not generated by limn — check it by hand"
        [[ "$(cat "$dst")" == "$want" ]] && return 0
    fi
    printf '%s\n' "$want" > "$dst" || die "could not write the unit: $dst"
    say "installed unit template: $dst"
    sysu daemon-reload
}

ensure_conf_link() { # if only the repo source exists, link it into home
    local n=$1
    [[ -e "$(conf_of "$n")" ]] && return 0
    [[ -f "$(src_of "$n")" ]] || die "no config found: $(src_of "$n")"
    mkdir -p "$CONFIG_DIR" && ln -s "$(src_of "$n")" "$(conf_of "$n")"
}

# ── the agent token file (docs/adr/0007-agent-token-file.md) ──
# Agents on this machine read an instance's token from <config dir>/<name>.token (mode 0600, written by
# `limn token create <name> --save`). This script sends it too when it asks a running instance over HTTP, so
# status checks keep working once the instance refuses headerless requests (AGENT_LOOPBACK=0). Never in SOURCE_DIR.
token_file_of() { printf '%s/%s.token' "$CONFIG_DIR" "$1"; }

# token_of <name> — prints the instance's token from its token file, if that file is safe to use. No file: nothing,
# status 1. A file that is a symlink or not a regular file, belongs to another account, is open to group/others, or
# is not a single `limn_…` line is not used either: a warning says why and how to fix it.
token_of() {
    local f perm mode owner tok re='^limn_[A-Za-z0-9_-]+$'
    f=$(token_file_of "$1")
    [[ -e "$f" || -L "$f" ]] || return 1
    if [[ -L "$f" || ! -f "$f" ]]; then
        warn "$f is not a regular file — not using it (recreate it: limn token create $1 --save --force)"
        return 1
    fi
    perm=$(stat_fmt '%a %u' '%Lp %u' "$f") || perm=""
    read -r mode owner <<< "$perm"
    if [[ ! "$mode" =~ ^[0-7]+$ || "$owner" != "$(id -u)" ]]; then
        warn "$f does not belong to this account — not using it"
        return 1
    fi
    if ((8#$mode & 8#077)); then
        warn "$f is open to group or others (mode $mode) — not using it; fix it: chmod 600 $f"
        return 1
    fi
    tok=$(< "$f") || tok=""
    if [[ ! "$tok" =~ $re ]]; then
        warn "$f does not hold one limn_… token line — not using it (recreate it: limn token create $1 --save --force)"
        return 1
    fi
    printf '%s' "$tok"
}

# shell_path <path> — the path as an agent's shell should see it: ~/… under $HOME (the tilde still expands inside
# $(cat …)), else as is. For text people paste, never for this script's own file access.
# The server's shell_path() follows the same rule: ~/ only for a plain rest under a non-empty $HOME, else quoted.
shell_path() {
    local rest re='^[A-Za-z0-9._/-]+$'
    if [[ -n "${HOME:-}" && "$1" == "$HOME"/* ]]; then
        rest=${1#"$HOME"/}
        if [[ "$rest" =~ $re ]]; then
            # The tilde is literal text for the reader's shell, not an expansion here.
            # shellcheck disable=SC2088
            printf '~/%s' "$rest"
            return
        fi
    fi
    printf '%q' "$1"
}

# own_listener <port> — is every socket listening on <port> this account's (and is there one)? The token goes only to
# our own server: while an instance is down another account could listen on its port (ports are predictable, they
# are in the ledger) and read the Authorization header. Linux: the uid column of /proc/net/tcp and tcp6
# (LIMN_PROC_NET points elsewhere in tests). Elsewhere (macOS): lsof, split into this account's listeners and
# anyone else's. Neither available: no.
own_listener() {
    local port=$1 uid net=${LIMN_PROC_NET:-/proc/net}
    uid=$(id -u)
    if [[ -r "$net/tcp" ]]; then
        "$PYTHON" -c 'import sys
port, uid, owners = int(sys.argv[1]), sys.argv[2], set()
for name in sys.argv[3:]:
    try:
        rows = open(name).read().splitlines()[1:]
    except OSError:
        continue
    for row in rows:
        c = row.split()
        if len(c) > 7 and c[3] == "0A" and int(c[1].rsplit(":", 1)[1], 16) == port:
            owners.add(c[7])
sys.exit(0 if owners == {uid} else 1)' "$port" "$uid" "$net/tcp" "$net/tcp6" 2> /dev/null
        return
    fi
    command -v lsof > /dev/null 2>&1 || return 1
    [[ -n "$(lsof -nP -a -u "$uid" -iTCP:"$port" -sTCP:LISTEN -t 2> /dev/null)" ]] \
        && [[ -z "$(lsof -nP -a -u "^$uid" -iTCP:"$port" -sTCP:LISTEN -t 2> /dev/null)" ]]
}

# probe_auth <name> <port> — how a check of <port> authenticates, as "<how> [token]": sent (the token file's token
# goes with it), withheld (a usable token, but the port is not held by this account - see own_listener), unusable
# (a token file token_of refused, with its warning), or none (no token file).
probe_auth() {
    local tok f
    f=$(token_file_of "$1")
    if tok=$(token_of "$1"); then
        if own_listener "$2"; then printf 'sent %s' "$tok"; else printf 'withheld'; fi
    elif [[ -e "$f" || -L "$f" ]]; then
        printf 'unusable'
    else
        printf 'none'
    fi
}

# probe_code <local port> [token] — HTTP code of a read-only route. The token goes to curl on stdin (-H @-), never
# on its command line, where other accounts could read it (ps).
probe_code() {
    local url="http://127.0.0.1:$1/api/meta?light=1"
    if [[ -n "${2:-}" ]]; then
        curl -s -o /dev/null -m 5 -w '%{http_code}' -H @- "$url" 2> /dev/null <<< "Authorization: Bearer $2" || true
    else
        curl -s -o /dev/null -m 5 -w '%{http_code}' "$url" 2> /dev/null || true
    fi
}
http_code() { # http_code <name> <local port> — probe_code, with the token file's token when probe_auth sends it
    local how tok=""
    read -r how tok <<< "$(probe_auth "$1" "$2")"
    probe_code "$2" "$tok"
}
# refused_hint <name> <how: sent|withheld|unusable|none> — what a 401 from the instance's port means, and the fix.
refused_hint() {
    local f
    f=$(token_file_of "$1")
    case "$2" in
        sent) printf 'the token in %s was refused (revoked?) — make a new one: limn token create %s --save --force' "$f" "$1" ;;
        withheld) printf 'no process of this account listens on the port, so the token was not sent — is the instance down, or another account on its port?' ;;
        unusable) printf 'the token file %s is not usable (see the warning) — chmod 600 it, or replace it: limn token create %s --save --force' "$f" "$1" ;;
        *) printf 'it refuses requests without a token (AGENT_LOOPBACK=0, or AUTH other than tailscale) and there is no token file — limn token create %s --save' "$1" ;;
    esac
}
# wait_ready <name> <port> — 0 once it answers 200; 2 if the unit failed; 3 on a 401 (it is up but refuses this
# check: no usable token file, or a revoked one - waiting would not change that); 1 when LIMN_WAIT runs out.
# READY_HOW tells the caller how the last check authenticated (for refused_hint). The token file is read once; the
# token goes with a check only while this account holds the port (own_listener), which a starting unit may not yet.
wait_ready() {
    local i code tok="" t f
    f=$(token_file_of "$1")
    if tok=$(token_of "$1"); then
        READY_HOW=withheld
    else
        tok=""
        READY_HOW=none
        [[ -e "$f" || -L "$f" ]] && READY_HOW=unusable
    fi
    for ((i = 0; i < WAIT_S; i++)); do
        t=""
        if [[ -n "$tok" ]] && own_listener "$2"; then
            t=$tok
            READY_HOW=sent
        fi
        code=$(probe_code "$2" "$t")
        [[ "$code" == 200 ]] && return 0
        [[ "$code" == 401 ]] && return 3
        if [[ "$(sysu is-active "$(unit_of "$1")" 2> /dev/null)" == failed ]]; then
            return 2
        fi
        sleep 1
    done
    return 1
}

# serve_on <tailnet port> <local port> — leaves an identical existing entry as-is. Stops if it belongs to someone else.
serve_on() {
    local ts=$1 lp=$2 cur want="http://127.0.0.1:$2"
    command -v tailscale > /dev/null 2>&1 || die "tailscale is not installed — use --no-serve to run local-only"
    cur=$(ts_proxy_of "$ts")
    if [[ "$cur" == "$want" ]]; then
        say "tailscale serve :$ts → $want (already set)"
    elif [[ -n "$cur" ]]; then
        die "tailnet :$ts is already used by $cur — not overwriting"
    else
        tailscale serve --bg --https="$ts" "$want" > /dev/null \
            || die "tailscale serve failed — check whether this user is the operator (permissions are never changed automatically)"
        say "tailscale serve :$ts → $want"
    fi
    # Read it back to confirm it's set and not exposed via funnel (see docs/handbook/operations.md §보안 제약).
    local line
    line=$(ts_map | awk -v p="$ts" '$1 == p')
    [[ "$(awk '{print $2}' <<< "$line")" == "$want" ]] || die "could not read back the serve entry(:$ts)"
    [[ "$(awk '{print $3}' <<< "$line")" == 0 ]] || die ":$ts is exposed via funnel — check this immediately"
}
# serve_off <tailnet port> <local port> — only unserves if it's our own pair.
serve_off() {
    local ts=$1 lp=$2 cur
    command -v tailscale > /dev/null 2>&1 || return 0
    cur=$(ts_proxy_of "$ts")
    if [[ -z "$cur" ]]; then
        say "tailscale serve :$ts not set"
    elif [[ "$cur" != "http://127.0.0.1:$lp" ]]; then
        warn "tailnet :$ts points at $cur — not this instance's, leaving it alone"
    else
        tailscale serve --https="$ts" off > /dev/null || warn "failed to unserve(:$ts)"
        [[ -z "$(ts_proxy_of "$ts")" ]] && say "tailscale serve :$ts unset"
    fi
}

open_pins() { # <state dir> → open pin count (pins.md header line. Doesn't hit the server)
    [[ -f "$1/pins.md" ]] || {
        printf '?'
        return
    }
    local n
    n=$(sed -nE 's/.*열린 핀 ([0-9]+)건.*/\1/p' "$1/pins.md" | head -1)
    printf '%s' "${n:-?}"
}

default_label() { # manuscript git repo name — the tail of the origin URL, or the repo dir name if none
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

detect_main() { # if exactly one top-level .tex in the manuscript dir has \documentclass, that one
    local m=$1 cands=() f
    for f in "$m"/*.tex; do
        [[ -f "$f" ]] && grep -qE '^[^%]*\\documentclass' "$f" && cands+=("$(basename "$f")")
    done
    if [[ ${#cands[@]} -eq 1 ]]; then
        printf '%s' "${cands[0]}"
        return 0
    fi
    printf 'top-level .tex %s — specify one with --main: %s\n' \
        "$([[ ${#cands[@]} -eq 0 ]] && echo 'not found' || echo 'found multiple')" "${cands[*]:-(none)}" >&2
    return 1
}

# stat_fmt <GNU format> <BSD format> <file> — one stat(1) field on GNU (Linux: stat -c) or BSD/macOS (stat -f). BSD
# stat rejects -c, so the GNU form fails there and the BSD form runs; on GNU the -c form succeeds for any existing file.
stat_fmt() { stat -c "$1" "$3" 2> /dev/null || stat -f "$2" "$3" 2> /dev/null; }

with_lock() { # keeps concurrent adds from overlapping between port-picking and config-writing
    mkdir -p "$CONFIG_DIR"
    if command -v flock > /dev/null 2>&1; then
        exec 9> "$CONFIG_DIR/.lock"
        flock -w 30 9 || die "another limn holds the lock: $CONFIG_DIR/.lock"
    fi
}

# ─────────────────────────────── commands ───────────────────────────────

cmd_run() {
    local n=${1:-}
    need_name "$n"
    load "$n" || die "no config found: $(conf_of "$n")"
    [[ -f "$SERVER" ]] || die "limn server not found: $SERVER — reinstall limn"
    [[ -n "$C_MANUSCRIPT" && -d "$C_MANUSCRIPT" ]] || die "MANUSCRIPT dir does not exist: '$C_MANUSCRIPT'"
    [[ -z "$C_DOCS" || -z "$C_MAIN" ]] || die "config error: MAIN and DOCS cannot be used together: $C_FILE"
    [[ -z "$C_MAIN" || -f "$C_MANUSCRIPT/$C_MAIN" ]] || die "MAIN file does not exist: $C_MANUSCRIPT/$C_MAIN"
    valid_port "${C_PORT:-x}" || die "PORT is missing or invalid: '$C_PORT' (never left to auto-pick — the advertised address would break)"
    [[ -z "$C_ACCENT" || "$C_ACCENT" =~ ^#[0-9a-fA-F]{6}$ ]] || die "ACCENT must be in #rrggbb format: '$C_ACCENT'"
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
    access_args
    args+=("${ACCESS_ARGS[@]+"${ACCESS_ARGS[@]}"}")
    if [[ -n "$C_EXTRA_ARGS" ]]; then
        local extra
        read -r -a extra <<< "$C_EXTRA_ARGS"
        args+=("${extra[@]}")
    fi
    mkdir -p "$C_STATE_DIR" || die "could not create the state dir: $C_STATE_DIR"
    if [[ "${LIMN_PRINT_ARGV:-0}" == 1 ]]; then
        printf '%s\n' "$PYTHON" "$SERVER" "${args[@]}"
        return 0
    fi
    # Where agents on this machine keep the token (ADR-0007). An environment variable, not a flag, so a config
    # without access keys still yields exactly the v0.1 argv. The server only checks whether the file exists.
    LIMN_AGENT_TOKEN_FILE=$(token_file_of "$n")
    export LIMN_AGENT_TOKEN_FILE
    exec "$PYTHON" "$SERVER" "${args[@]}"
}

start_instance() { # start_instance <name> <serve 0|1>
    local n=$1 serve=$2 rc=0
    ensure_conf_link "$n"
    load "$n" || die "could not read the config: $n"
    ensure_unit
    sysu enable "$(unit_of "$n")" > /dev/null 2>&1 || die "enable failed: $(unit_of "$n")"
    sysu start "$(unit_of "$n")" || die "start failed: journalctl --user -u $(unit_of "$n")"
    say "$(unit_of "$n") starting — waiting for 127.0.0.1:$C_PORT to respond (the first boot waits for the build, up to ${WAIT_S}s)"
    wait_ready "$n" "$C_PORT" || rc=$?
    case $rc in
        0) say "127.0.0.1:$C_PORT 200" ;;
        2) die "the unit failed: journalctl --user -u $(unit_of "$n") -n 50" ;;
        3) warn "127.0.0.1:$C_PORT is up but answers 401: $(refused_hint "$n" "$READY_HOW")" ;;
        *) warn "not 200 yet (may still be building) — limn status $n" ;;
    esac
    if [[ "$serve" == 1 ]]; then
        serve_allowed_for "$C_AUTH" || die "$(serve_refusal "$C_AUTH") — start it with --no-serve"
        valid_port "${C_TS_PORT:-x}" || die "TS_PORT is not set — start with --no-serve or add it to the config"
        serve_on "$C_TS_PORT" "$C_PORT"
    fi
}

# tailscale serve connects from loopback. Under AUTH=local every loopback request is the owner, and under
# AUTH=trusted-proxy a tailnet user could send the proxy identity headers themselves — so only the tailscale
# provider (or no AUTH, which is tailscale) may be exposed with tailscale serve.
serve_allowed_for() { [[ -z "${1:-}" || "$1" == tailscale ]]; }
serve_refusal() {
    case "$1" in
        local) printf 'AUTH=local makes every loopback request the owner, and tailscale serve connects from loopback — exposing it would make every tailnet member the owner' ;;
        *) printf 'AUTH=%s trusts identity headers from loopback, and tailscale serve would pass headers a tailnet user sets — put it behind its own proxy instead' "$1" ;;
    esac
}

cmd_add() {
    local n=${1:-}
    need_name "$n"
    shift
    local manuscript="" main="" port="" ts="" gitpull=0 label="" accent="" state="" extra_args="--no-build" serve=1 start=1
    local docs=() stage=auto auth=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --manuscript) manuscript=${2:-}; shift 2 ;;
            --auth) auth=${2:-}; shift 2 ;;
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
            *) die "unknown argument: $1" ;;
        esac
    done
    [[ -n "$manuscript" ]] || die "--manuscript <manuscript dir> is required"
    [[ -d "$manuscript" ]] || die "manuscript dir does not exist: $manuscript"
    manuscript=$(cd "$manuscript" && pwd -P)
    [[ -z "$auth" ]] || valid_auth "$auth" || die "--auth must be tailscale, local or trusted-proxy: $auth"
    serve_allowed_for "$auth" || [[ "$serve" == 0 ]] || die "$(serve_refusal "$auth") — add it with --no-serve"
    [[ -z "$main" || ${#docs[@]} -eq 0 ]] || die "--main and --doc cannot be used together"
    if [[ ${#docs[@]} -gt 0 ]]; then
        [[ "$stage" == auto ]] || die "--stage is only used for auto-detection without --doc/--main"
        validate_doc_specs "$manuscript" "${docs[@]}"
    elif [[ -n "$main" ]]; then
        [[ "$stage" == auto ]] || die "--stage is only used for auto-detection without --doc/--main"
        [[ "$main" != */* && -f "$manuscript/$main" ]] || die "main .tex is not at the top of the manuscript dir: $manuscript/$main"
    elif detect_docs_layout "$manuscript" "$stage"; then
        docs=("${DETECTED_DOCS[@]}")
        validate_doc_specs "$manuscript" "${docs[@]}"
        say "auto-detected documents:"
        local d
        for d in "${docs[@]}"; do say "  $d"; done
    else
        main=$(detect_main "$manuscript") || die "automatic main .tex detection failed"
    fi
    [[ -z "$accent" || "$accent" =~ ^#[0-9a-fA-F]{6}$ ]] || die "--accent must be in #rrggbb format: $accent"
    [[ -n "$label" ]] || label=$(default_label "$manuscript")
    [[ -n "$label" ]] || label=$n
    ((${#label} <= 40)) || die "--label must be 40 characters or fewer: $label"
    [[ -n "$state" ]] || state="$DATA_ROOT/$n"
    local docs_str=""
    ((${#docs[@]} == 0)) || docs_str=$(join_semi "${docs[@]}")
    local v
    for v in "$manuscript" "$main" "$label" "$state" "$extra_args" "$docs_str"; do
        safe_value "$v" || die "contains characters not allowed in a config file (quote/backslash/\$/backtick/newline): $v"
    done
    [[ "$state" == /* ]] || die "--state-dir must be an absolute path: $state"

    with_lock
    snapshot_ports
    [[ -e "$(conf_of "$n")" || -e "$(src_of "$n")" ]] \
        && die "'$n' config already exists — to turn it back on use limn start $n, to recreate it, remove first"
    local o
    for o in $(instances); do
        load "$o" || continue
        [[ "$C_STATE_DIR" != "$state" ]] || die "state dir collides with '$o': $state"
        [[ "$C_MANUSCRIPT" != "$manuscript" ]] || warn "'$o' also points at the same manuscript dir — builds happen in separate state dirs, but --git-pull may collide"
    done

    local why
    if [[ -z "$port" && -z "$ts" ]]; then
        read -r ts port <<< "$(pick_pair)"
        [[ -n "$port" ]] || die "no free pair in the $TS_MIN-$TS_MAX band — specify with --port/--ts-port"
    else
        [[ -n "$port" ]] || port=$((ts + LOCAL_OFFSET))
        [[ -n "$ts" ]] || ts=$((port - LOCAL_OFFSET))
    fi
    valid_port "$port" || die "local port is invalid: $port"
    valid_port "$ts" || die "tailnet port is invalid: $ts"
    [[ "$port" != "$ts" ]] || die "local port and tailnet port are the same: $port"
    why=$(port_taken "$port" "$n") && die "local port $port: $why"
    why=$(port_taken "$ts" "$n") && die "tailnet port $ts: $why"

    mkdir -p "$SOURCE_DIR" || die "could not create the source dir: $SOURCE_DIR"
    {
        # The backticks are literal text in the config header, not a command substitution.
        # shellcheck disable=SC2016
        printf '# limn@%s — created by `limn add` on %s. See README for the format and keys.\n' "$n" "$(date +%F)"
        printf '# Not sourced by the shell — do not put shell syntax in values.\n' 
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
        emit AUTH "$auth"
    } > "$(src_of "$n")" || die "could not write the config: $(src_of "$n")"
    if [[ "$SOURCE_DIR" != "$CONFIG_DIR" ]]; then
        mkdir -p "$CONFIG_DIR" && ln -sfn "$(src_of "$n")" "$(conf_of "$n")"
    fi
    ledger_refresh
    say "config  $(src_of "$n")"
    [[ "$SOURCE_DIR" == "$CONFIG_DIR" ]] || say "link  $(conf_of "$n") → source"
    say "ports  local 127.0.0.1:$port · tailnet :$ts (the config file is the reservation)"
    exec 9>&- # release the lock — don't block other adds during the boot wait (up to a few minutes)

    if [[ "$start" == 1 ]]; then
        start_instance "$n" "$serve"
    else
        say "not started — limn start $n"
    fi
    if [[ "$SOURCE_DIR" != "$CONFIG_DIR" ]]; then
        say ""
        say "the config source lives in $SOURCE_DIR — commit it in that repo: $(src_of "$n")"
    fi
    say ""
    cmd_snippet "$n"
}

cmd_start() {
    local n=${1:-} serve=1
    need_name "$n"
    [[ "${2:-}" == --no-serve ]] && serve=0
    load "$n" || die "no config found — limn add $n ..."
    if [[ "$(sysu is-active "$(unit_of "$n")" 2> /dev/null)" != active ]] && listening "$C_PORT"; then
        die "local port $C_PORT is already in use — is an old unit still running? (ss -ltnp 'sport = :$C_PORT')"
    fi
    start_instance "$n" "$serve"
    say "$(url_of "$C_TS_PORT")"
}

cmd_stop() {
    local n=${1:-}
    need_name "$n"
    sysu disable --now "$(unit_of "$n")" > /dev/null 2>&1 || warn "disable failed: $(unit_of "$n")"
    say "$(unit_of "$n") stopped and disabled (config, port reservation, and serve entry stay as-is — turn back on: limn start $n)"
}

# with_timeout <seconds> <command...> — runs the command, killed after the given seconds: GNU timeout (Linux),
# gtimeout (Homebrew coreutils), or perl's alarm (every macOS has perl) — macOS has no timeout(1). Without any of
# them the command runs unbounded.
with_timeout() {
    local s=$1
    shift
    if command -v timeout > /dev/null 2>&1; then
        timeout "$s" "$@"
    elif command -v gtimeout > /dev/null 2>&1; then
        gtimeout "$s" "$@"
    elif command -v perl > /dev/null 2>&1; then
        perl -e 'alarm shift; exec @ARGV or exit 127' "$s" "$@"
    else
        "$@"
    fi
}

cmd_list() {
    local n state code
    printf '%-14s %-16s %-6s %-6s %-9s %-5s %-4s %s\n' NAME LABEL LOCAL TAILNET STATUS PINS DOCS MANUSCRIPT
    for n in $(instances); do
        load "$n" || continue
        state=$(sysu is-active "$(unit_of "$n")" 2> /dev/null)
        [[ -n "$state" ]] || state="?"
        code=""
        [[ "$state" == active ]] && code=$(http_code "$n" "$C_PORT")
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
        say "no instances — limn add <name> --manuscript <manuscript dir>"
        return 0
    }
    say "limn     $VERSION ($SERVER)"
    for n in $names; do
        load "$n" || die "no config found: $n"
        local unit
        unit=$(unit_of "$n")
        say ""
        say "[$n] ${C_LABEL:-}"
        say "  unit         $unit  $(sysu is-active "$unit" 2> /dev/null) / $(sysu is-enabled "$unit" 2> /dev/null)  pid=$(sysu show -p MainPID --value "$unit" 2> /dev/null)"
        local how tok="" code f
        f=$(token_file_of "$n")
        read -r how tok <<< "$(probe_auth "$n" "$C_PORT")"
        code=$(probe_code "$C_PORT" "$tok")
        if [[ "$code" == 401 ]]; then
            say "  local        http://127.0.0.1:$C_PORT/  → 401 ($(refused_hint "$n" "$how"))"
        else
            say "  local        http://127.0.0.1:$C_PORT/  → $code"
        fi
        case "$how" in
            sent) say "  token file   $f (sent with the check above)" ;;
            withheld) say "  token file   $f (not sent: no process of this account listens on 127.0.0.1:$C_PORT)" ;;
            unusable) say "  token file   $f (not usable, see the warning)" ;;
            *) say "  token file   none — agents here use a token file once the owner runs: limn token create $n --save" ;;
        esac
        say "  tailnet      $(url_of "$C_TS_PORT")  (serve: $(ts_proxy_of "$C_TS_PORT" | grep . || echo none))"
        if [[ -n "$C_DOCS" ]]; then
            say "  manuscript   $C_MANUSCRIPT"
            say "  docs         $(doc_count "$C_DOCS"): $(doc_keys "$C_DOCS")"
        else
            say "  manuscript   $C_MANUSCRIPT/${C_MAIN:-(auto)}"
        fi
        say "  state        $C_STATE_DIR  (open pins $(open_pins "$C_STATE_DIR"))"
        say "  config       $C_FILE"
        say "  log          journalctl --user -u $unit · $C_STATE_DIR/build.log"
    done
}

cmd_url() {
    local n
    if [[ -n "${1:-}" ]]; then
        need_name "$1"
        load "$1" || die "no config found: $1"
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
    load "$n" || die "no config found: $n"
    local url origin tokfile
    url=$(url_of "$C_TS_PORT")
    url=${url%/}
    tokfile=$(shell_path "$(token_file_of "$n")")
    origin=$(git -C "$C_MANUSCRIPT" remote get-url origin 2> /dev/null || echo '(manuscript dir is not a git repo)')
    local doclist=""
    if [[ -n "$C_DOCS" ]]; then
        doclist=$'\n'"- Docs: $(doc_keys "$C_DOCS") — \`pins.md\` is split into per-document subsections. To open a specific document directly, use \`$url/#doc=<key>\`"
    fi
    cat << EOF
--- Snippet to paste into this paper repo's AGENTS.md (limn snippet $n) ---
## Limn manuscript instance (${C_LABEL:-$n})

- Viewer: $url/ — co-authors drag on the PDF to leave pins marking where to fix things.$doclist
- Every request carries this instance's agent token:
  - on the machine that serves it: \`-H "Authorization: Bearer \$(cat $tokfile)"\` — the file the owner writes once with
    \`limn token create $n --save\`. Never print that file or copy it into a repository.
  - from another machine: \`-H "Authorization: Bearer \$LIMN_TOKEN"\` with a token the owner creates (\`limn token create $n\`)
    and hands over. Through the tailnet address it is required unless the machine is signed in as a person: a request with neither gets 403.
- Pin list: \`curl -s -H "Authorization: Bearer \$(cat $tokfile)" http://127.0.0.1:$C_PORT/pins.md\` on the serving machine,
  \`curl -s -H "Authorization: Bearer \$LIMN_TOKEN" $url/pins.md\` from elsewhere.
- **Check this first**: does the repo (manuscript path) at the top of pins.md match \`git remote get-url origin\` for this checkout?
  If not, this is the viewer for a different paper — don't act on it. This viewer's manuscript repo: \`$origin\`
- Division of labor: whoever was asked handles **all** open pins. Skip pins claimed (⏳) by the other side.
- Close pins you've handled per the instructions at the top of pins.md (reply with what you fixed, referencing the commit/PR).
---
EOF
}

cmd_remove() {
    local n=${1:-}
    need_name "$n"
    load "$n" || die "no config found: $n"
    local state=$C_STATE_DIR port=$C_PORT ts=$C_TS_PORT
    sysu disable --now "$(unit_of "$n")" > /dev/null 2>&1 || true
    say "$(unit_of "$n") stopped and disabled"
    [[ -n "$ts" && -n "$port" ]] && serve_off "$ts" "$port"
    # config = port reservation. Both the home link and its target (the file the link points to —
    # possibly a different checkout) must be deleted together for it to drop out of the ledger.
    local f targets=()
    if [[ -L "$(conf_of "$n")" ]]; then
        f=$(readlink "$(conf_of "$n")")
        [[ "$(basename "$f")" == "$n.env" && -f "$f" ]] && targets+=("$f")
    fi
    [[ -e "$(conf_of "$n")" || -L "$(conf_of "$n")" ]] && targets+=("$(conf_of "$n")")
    [[ -f "$(src_of "$n")" ]] && targets+=("$(src_of "$n")")
    for f in "${targets[@]+"${targets[@]}"}"; do
        [[ -e "$f" || -L "$f" ]] || continue
        rm -f "$f" && say "deleted config: $f"
        case "$f" in
            "$SOURCE_DIR"/"$n".env)
                [[ "$SOURCE_DIR" == "$CONFIG_DIR" ]] || say "  commit this deletion in the config source repo: $f"
                ;;
        esac
    done
    ledger_refresh
    say "freed the port reservation: $port/$ts (config deleted)"
    sysu reset-failed "$(unit_of "$n")" > /dev/null 2>&1 || true
    say "state dir was not deleted: $state"
}

# shellcheck source=src/limn/features/administration/instance_documents.sh
. "$_HERE/features/administration/instance_documents.sh"

# shellcheck source=src/limn/features/administration/instance_update.sh
. "$_HERE/features/administration/instance_update.sh"

usage() { sed -n '/^# Usage:/,/^# Security rules/p' "${BASH_SOURCE[0]}" | sed -e '$d' -e 's/^# \{0,1\}//'; }

main() {
    local c=${1:-}
    [[ $# -gt 0 ]] && shift
    case "$c" in
        -h | --help | help | "") ;;
        *) [[ -n "$PYTHON" ]] || die "$PYTHON_WHY" ;;
    esac
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
