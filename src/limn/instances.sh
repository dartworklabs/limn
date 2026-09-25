#!/usr/bin/env bash
# Limn instance manager — brings up and manages one `limn@<name>.service` instance per manuscript (paper).
#
# Each paper has its own repository, and when two papers are being worked on at once, Limn has to run
# separately for each too. So each instance gets its own port, state dir (pins, build, build.log), and
# journal, while sharing a single installed limn package. Structure and procedure: docs/instances.md.
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
#   limn token create|list|revoke <name> … agent API tokens; limn member add|list|remove|role <name> … roles
#                                          (Python, see limn help — they edit the instance's state dir)
#
# Access control (v0.2, docs/instances.md §Config keys): AUTH, AGENT_LOOPBACK, BIND, PUBLIC_HOSTS,
# TRUSTED_PROXIES, PROXY_USER_HEADER/PROXY_NAME_HEADER/PROXY_EMAIL_HEADER, MEMBERS_ONLY, LOCAL_USER map to
# the server flags of the same meaning. Unset keys add no flag, so a v0.1 config runs exactly as before.
#
# Multiple documents (--doc, DOCS=): a single instance switches between tabs for the body, response
# letter, a view-only PDF, and so on. Format is <key>=<display name>:<path>. Keys are [a-z0-9-]{1,24},
# no duplicates, up to 12 documents, and paths must be inside --manuscript. `<build root>::<main.tex>`
# is an extended notation (LaTeX only) that widens the copy scope to the build root. In the config file
# this is written as DOCS="<key1>=<name1>:<path1>;<key2>=..." (split on `;`). MAIN and DOCS are not
# used together — see docs/operations.md §Multiple documents for the full contract.

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
# Multi-document (--doc/DOCS=) limits. Kept in sync with DOC_KEY_RE/DOCS_MAX/DOC_NAME_MAX on the server side (limn/server.py).
DOCS_MAX=12
DOC_NAME_MAX=40
# Passed in by the CLI: the installed limn's Python, server, unit template, executable, and version.
PYTHON="${LIMN_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
    if [[ -x /usr/bin/python3 ]]; then PYTHON=/usr/bin/python3; else PYTHON=$(command -v python3 || true); fi
fi
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

# ── multiple documents (--doc / DOCS=) ──
# Format is <key>=<display name>:<path>. Parsing/validation rules are kept in sync with the server
# (parse_doc_arg/make_docs in limn/server.py) — the server re-validates on startup, but filtering
# here first means a clear error at `limn add`/`limn doc add` time instead of a systemd Restart loop.
join_semi() { local IFS=';'; printf '%s' "$*"; } # join_semi <items...> -> string joined by ';'
valid_doc_key() { # [a-z0-9-]{1,24}
    [[ "$1" =~ ^[a-z0-9-]+$ ]] || return 1
    local len=${#1}
    ((len >= 1 && len <= 24))
}

# doc_parse_kv <spec> — on success fills the DOC_KEY/DOC_NAME/DOC_PATH globals. On failure, die.
doc_parse_kv() {
    local spec=$1 rest
    [[ "$spec" == *=* ]] || die "--doc must be in the form <key>=<display name>:<path>: $spec"
    DOC_KEY=${spec%%=*}
    rest=${spec#*=}
    valid_doc_key "$DOC_KEY" || die "--doc key must match [a-z0-9-]{1,24}: $DOC_KEY"
    [[ "$rest" == *:* ]] || die "--doc $DOC_KEY: no ':' between the display name and the path: $spec"
    DOC_NAME=${rest%%:*}
    DOC_PATH=${rest#*:}
    [[ -n "$DOC_NAME" ]] || die "--doc $DOC_KEY: display name is empty"
    ((${#DOC_NAME} <= DOC_NAME_MAX)) || die "--doc $DOC_KEY: display name must be ${DOC_NAME_MAX} characters or fewer: $DOC_NAME"
    [[ -n "$DOC_PATH" ]] || die "--doc $DOC_KEY: path is empty"
}

# doc_check_path <absolute manuscript path> — reads DOC_KEY/DOC_PATH filled by doc_parse_kv and
# validates the path. The `::` notation (<build root>::<main.tex>) checks that both the build root
# and the main file are inside the manuscript dir. A string pointing outside the manuscript via `../`
# can't be caught by a plain prefix comparison (`$ms/../x` still starts with `$ms/` as a string), so
# it's normalized with `cd .. && pwd -P` before comparing — the same `pwd -P` convention cmd_add uses
# to normalize the manuscript argument itself.
doc_check_path() {
    local ms=$1 path=$DOC_PATH key=$DOC_KEY root="" root_c="" main="" main_c=""
    if [[ "$path" == *::* ]]; then
        local root_s=${path%%::*} main_s=${path#*::}
        [[ "$main_s" != *::* ]] || die "--doc $key: extended notation takes exactly one <build root>::<main.tex>: $path"
        [[ -n "$root_s" && -n "$main_s" ]] || die "--doc $key: malformed extended notation (build root or main is empty): $path"
        if [[ "$root_s" == /* ]]; then root="$root_s"; else root="$ms/$root_s"; fi
        [[ -d "$root" ]] || die "--doc $key: build root dir does not exist: $root"
        root_c=$(cd "$root" && pwd -P) || die "--doc $key: could not resolve the build root path: $root"
        case "$root_c" in
            "$ms"/* | "$ms") ;;
            *) die "--doc $key: build root is outside --manuscript($ms): $root_c" ;;
        esac
        [[ "$main_s" != /* ]] || die "--doc $key: the main after '::' must be relative to the build root: $main_s"
        main="$root_c/$main_s"
        case "${main##*.}" in
            tex) ;;
            *) die "--doc $key: '::' notation is only for LaTeX documents (.tex): $main" ;;
        esac
    else
        if [[ "$path" == /* ]]; then main="$path"; else main="$ms/$path"; fi
        case "${main##*.}" in
            tex | pdf) ;;
            *) die "--doc $key: only .tex (LaTeX) or .pdf (view-only) are accepted: $main" ;;
        esac
    fi
    [[ -f "$main" ]] || die "--doc $key: file does not exist: $main"
    main_c="$(cd "$(dirname "$main")" && pwd -P)/$(basename "$main")" || die "--doc $key: could not resolve the path: $main"
    case "$main_c" in
        "$ms"/*) ;;
        *) die "--doc $key: path is outside --manuscript($ms): $main_c" ;;
    esac
    if [[ -n "$root_c" ]]; then
        case "$main_c" in
            "$root_c"/*) ;;
            *) die "--doc $key: main is outside the build root($root_c): $main_c" ;;
        esac
    fi
}

# validate_doc_specs <absolute manuscript path> <spec...> — validates count, duplicate keys, format,
# and paths, all of it. Dies immediately on any problem (must be filtered before writing the config).
validate_doc_specs() {
    local ms=$1
    shift
    local n=$#
    ((n > 0)) || die "at least one --doc is required"
    ((n <= DOCS_MAX)) || die "--doc allows at most ${DOCS_MAX} (got ${n})"
    local seen=" " spec
    for spec in "$@"; do
        doc_parse_kv "$spec"
        case "$seen" in
            *" $DOC_KEY "*) die "--doc key is duplicated: $DOC_KEY" ;;
        esac
        seen="$seen$DOC_KEY "
        doc_check_path "$ms"
    done
}

doc_count() { # doc_count <DOCS string> -> document count (1 if empty, since that's a single document)
    local d=$1
    [[ -n "$d" ]] || {
        printf 1
        return
    }
    local specs=()
    IFS=';' read -ra specs <<< "$d"
    printf '%d' "${#specs[@]}"
}
doc_keys() { # doc_keys <DOCS string> -> comma-joined key list ("main" = single document)
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

http_code() { # http_code <local port> — only pokes a read-only route
    curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$1/api/meta?light=1" 2> /dev/null || true
}
wait_ready() { # wait_ready <name> <port>
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
    # Read it back to confirm it's set and not exposed via funnel (see operations.md §security constraints).
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

# detect_round <manuscript/ dir> — picks the subfolder name with the largest leading number
# (1st, 2nd, 3rd, ...). Folders that don't start with a number (e.g. `changes`) are ignored. Fails if none.
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

# git_commit_time <file> — prints the commit time (unix epoch) of the most recent commit touching
# that file, in the git repo it belongs to. Prints nothing and fails if git is unavailable, the file
# is outside a repo, or it's untracked (mtime is unreliable — it can be reset or stamped identically
# on a fresh clone/checkout, so git log takes priority).
git_commit_time() {
    local f=$1 dir t
    command -v git > /dev/null 2>&1 || return 1
    dir=$(dirname "$f")
    git -C "$dir" rev-parse --is-inside-work-tree > /dev/null 2>&1 || return 1
    t=$(git -C "$dir" log -1 --format=%ct -- "$(basename "$f")" 2> /dev/null) || return 1
    [[ -n "$t" ]] || return 1
    printf '%s' "$t"
}
# file_mtime <file> — modification time (unix epoch). Tries both GNU (stat -c) and BSD/macOS (stat -f).
file_mtime() { stat -c %Y "$1" 2> /dev/null || stat -f %m "$1" 2> /dev/null; }

# detect_main_for_round <round dir> — uses detect_main as-is, but if there are multiple candidates
# (e.g. a leftover prior manuscript with its own \documentclass still sitting in the same round
# folder), picks the file with the most recent git commit time (falls back to mtime if the file is
# outside git or untracked). If even the times tie, doesn't guess — dies, showing the candidate list
# and pointing to --doc. If there are zero candidates, fails as-is (treated as a non-standard layout,
# and the caller falls back to the old detection).
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
        die "multiple \\documentclass candidates in $(basename "$d")/ (even git commit/modification times tie) — could not choose automatically. Specify with --doc: $(IFS=,; printf '%s' "${names[*]}")"
    fi
    printf '%s' "$(basename "${cands[$best_i]}")"
}

# detect_docs_layout <absolute manuscript path> <stage: auto|initial|revision> — if the standard
# paper-repo layout (`manuscript/<round>/<main>.tex` + `submission/{highlights,cover_letter,review_response}/*.tex`)
# is present, fills the global array DETECTED_DOCS (same format as --doc specs) in a fixed order
# (ms/rr/hl/cl) and returns 0. `rr` (response letter) is only added at the revision stage, and only if
# the file actually exists. If the round folder or the main file can't be found (non-standard layout),
# fills nothing and returns 1 — the caller falls back to the old single-MAIN detection.
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
        *) die "--stage must be auto|initial|revision: $stage" ;;
    esac
    if [[ "$stage" == revision && -f "$ms/submission/review_response/review_response.tex" ]]; then
        DETECTED_DOCS+=("rr=답변서:submission/review_response/review_response.tex")
    fi
    [[ -f "$ms/submission/highlights/highlights.tex" ]] && DETECTED_DOCS+=("hl=하이라이트:submission/highlights/highlights.tex")
    [[ -f "$ms/submission/cover_letter/cover_letter.tex" ]] && DETECTED_DOCS+=("cl=커버레터:submission/cover_letter/cover_letter.tex")
    return 0
}

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

# update — reinstalls the installed limn via uv tool and restarts instances that are running. Never
# touches state dirs. To roll back, reinstall the previous tag (limn update --ref v<previous version>).
# A running server is already loaded into memory, so it doesn't die during the install — it switches
# to the new version only on restart.
latest_tag() { # the highest v* tag on the remote. Prints nothing on failure.
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
            *) die "unknown argument: $1" ;;
        esac
    done
    [[ -z "$ref" || -z "$from" ]] || die "--ref and --from cannot be used together"
    local spec
    if [[ -n "$from" ]]; then
        spec=$from
    else
        if [[ -z "$ref" ]]; then
            ref=$(latest_tag)
            [[ -n "$ref" ]] || die "could not read the remote tag($REPO) — specify with --ref <tag>"
        fi
        if [[ "$ref" == "v$VERSION" && "$force" == 0 ]]; then
            say "already $ref — not reinstalling (use --force to override)"
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
        say "(dry-run) current version: $VERSION"
        say "(dry-run) install: ${cmd[*]}"
        if [[ ${#active[@]} -gt 0 ]]; then
            for n in "${active[@]}"; do say "(dry-run) restart: $(unit_of "$n")"; done
        else
            say "(dry-run) no instances to restart"
        fi
        say "(dry-run) rollback: limn update --ref v$VERSION"
        return 0
    fi
    say "installing: ${cmd[*]}"
    "${cmd[@]}" || die "install failed — staying on the current version($VERSION)"
    local now
    now=$("$LIMN_BIN" version 2> /dev/null || true)
    say "limn $VERSION → ${now#limn } (rollback: limn update --ref v$VERSION)"
    [[ -f "$UNIT_TEMPLATE" ]] && ensure_unit
    [[ ${#active[@]} -gt 0 ]] || {
        say "no running instances"
        return 0
    }
    for n in "${active[@]}"; do
        load "$n" || continue
        sysu restart "$(unit_of "$n")" || {
            warn "restart failed: $(unit_of "$n")"
            continue
        }
        if wait_ready "$n" "$C_PORT"; then say "  $n restarted → 200"; else warn "  $n restarted but not responding — limn status $n"; fi
    done
}

cmd_list() {
    local n state code
    printf '%-14s %-16s %-6s %-6s %-9s %-5s %-4s %s\n' NAME LABEL LOCAL TAILNET STATUS PINS DOCS MANUSCRIPT
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
        say "  local        http://127.0.0.1:$C_PORT/  → $(http_code "$C_PORT")"
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
    local url origin
    url=$(url_of "$C_TS_PORT")
    url=${url%/}
    origin=$(git -C "$C_MANUSCRIPT" remote get-url origin 2> /dev/null || echo '(manuscript dir is not a git repo)')
    local doclist=""
    if [[ -n "$C_DOCS" ]]; then
        doclist=$'\n'"- Docs: $(doc_keys "$C_DOCS") — \`pins.md\` is split into per-document subsections. To open a specific document directly, use \`$url/#doc=<key>\`"
    fi
    cat << EOF
--- Snippet to paste into this paper repo's AGENTS.md (limn snippet $n) ---
## Limn manuscript instance (${C_LABEL:-$n})

- Viewer: $url/ — co-authors drag on the PDF to leave pins marking where to fix things.$doclist
- Pin list: \`curl -s $url/pins.md\` (on the same machine: \`curl -s http://127.0.0.1:$C_PORT/pins.md\`)
- **Check this first**: does the repo (manuscript path) at the top of pins.md match \`git remote get-url origin\` for this checkout?
  If not, this is the viewer for a different paper — don't act on it. This viewer's manuscript repo: \`$origin\`
- Division of labor: whoever was asked handles **all** open pins. Skip pins claimed (⏳) by the other side.
- Close pins you've handled per the instructions at the top of pins.md (reply with what you fixed, referencing the commit/PR).
---
EOF
}

# write_conf_docs <name> <DOCS string> — leaves the loaded C_* (filled in by load) as-is and rewrites
# the config file (C_FILE — usually the symlink in home, followed to the source) with DOCS in MAIN's place.
write_conf_docs() {
    local n=$1 docs_str=$2 f=$C_FILE
    {
        printf '# limn@%s — updated by `limn doc` on %s. See README for the format and keys.\n' "$n" "$(date +%F)"
        printf '# Not sourced by the shell — do not put shell syntax in values.\n'
        emit LABEL "$C_LABEL"
        emit ACCENT "$C_ACCENT"
        emit MANUSCRIPT "$C_MANUSCRIPT"
        emit DOCS "$docs_str"
        emit PORT "$C_PORT"
        emit TS_PORT "$C_TS_PORT"
        emit STATE_DIR "$C_STATE_DIR"
        emit GIT_PULL "$C_GIT_PULL"
        emit EXTRA_ARGS "$C_EXTRA_ARGS"
        emit_access
    } > "$f" || die "could not write the config: $f"
}

# Restart hint or --restart handling — shared by doc add/remove.
doc_restart_or_hint() {
    local n=$1 restart=$2
    if [[ "$restart" == 1 ]]; then
        sysu restart "$(unit_of "$n")" || die "restart failed: journalctl --user -u $(unit_of "$n")"
        load "$n" || die "could not re-read the config: $n"
        if wait_ready "$n" "$C_PORT"; then say "restarted → 127.0.0.1:$C_PORT 200"; else warn "not responding after restart — limn status $n"; fi
    else
        say "a restart is required: limn stop $n && limn start $n (or --restart)"
    fi
}

cmd_doc_list() {
    local n=${1:-}
    need_name "$n"
    load "$n" || die "no config found: $n"
    if [[ -z "$C_DOCS" ]]; then
        say "single document (MAIN=${C_MAIN:-auto-detected})"
        return 0
    fi
    local specs=() spec
    IFS=';' read -ra specs <<< "$C_DOCS"
    printf '%-10s %-24s %s\n' KEY NAME PATH
    for spec in "${specs[@]}"; do
        doc_parse_kv "$spec"
        printf '%-10s %-24s %s\n' "$DOC_KEY" "$DOC_NAME" "$DOC_PATH"
    done
}

cmd_doc_suggest() { # read-only — prints only the DOCS string that would be auto-detected, without writing any config
    local manuscript="" stage=auto
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --manuscript) manuscript=${2:-}; shift 2 ;;
            --stage) stage=${2:-}; shift 2 ;;
            *) die "unknown argument: $1" ;;
        esac
    done
    [[ -n "$manuscript" ]] || die "--manuscript <manuscript dir> is required"
    [[ -d "$manuscript" ]] || die "manuscript dir does not exist: $manuscript"
    manuscript=$(cd "$manuscript" && pwd -P)
    detect_docs_layout "$manuscript" "$stage" \
        || die "standard layout (manuscript/<round>/<main>.tex) not found — provide --doc by hand"
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
            *) die "unknown argument: $1" ;;
        esac
    done
    ((${#newdocs[@]} > 0)) || die "at least one --doc <key>=<display name>:<path> is required"
    load "$n" || die "no config found: $n"
    [[ -n "$C_MANUSCRIPT" && -d "$C_MANUSCRIPT" ]] || die "MANUSCRIPT dir does not exist: '$C_MANUSCRIPT'"
    local specs=()
    if [[ -n "$C_DOCS" ]]; then
        IFS=';' read -ra specs <<< "$C_DOCS"
    elif [[ -n "$C_MAIN" ]]; then
        # Single document (MAIN) -> multi-document switch: moves the body into the first entry
        # main=body:<MAIN>. A LaTeX document keyed main uses the state dir root as-is (the old
        # location) on the server side, so build history and page images carry over, and old pins
        # without a doc field are also read as this document (operations.md §Multiple documents).
        specs=("main=본문:$C_MAIN")
    else
        die "config has neither MAIN nor DOCS -- check it by hand: $C_FILE"
    fi
    specs+=("${newdocs[@]}")
    validate_doc_specs "$C_MANUSCRIPT" "${specs[@]}"
    local docs_str
    docs_str=$(join_semi "${specs[@]}")
    safe_value "$docs_str" || die "DOCS contains characters not allowed in a config file (quote/backslash/\$/backtick/newline)"
    write_conf_docs "$n" "$docs_str"
    say "DOCS updated: $C_FILE"
    say "  added: $(join_semi "${newdocs[@]}")"
    doc_restart_or_hint "$n" "$restart"
}

cmd_doc_remove() {
    local n=${1:-}
    need_name "$n"
    local key=${2:-}
    [[ -n "$key" ]] || die "a key to remove is required: limn doc remove <name> <key>"
    shift 2
    local restart=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --restart) restart=1; shift ;;
            *) die "unknown argument: $1" ;;
        esac
    done
    load "$n" || die "no config found: $n"
    [[ -n "$C_DOCS" ]] || die "'$n' has no multi-document config (DOCS) — a single-document instance has no document to remove"
    local specs=() spec kept=() found=0
    IFS=';' read -ra specs <<< "$C_DOCS"
    for spec in "${specs[@]}"; do
        doc_parse_kv "$spec"
        if [[ "$DOC_KEY" == "$key" ]]; then found=1; else kept+=("$spec"); fi
    done
    ((found == 1)) || die "key not found: $key ($(doc_keys "$C_DOCS"))"
    ((${#kept[@]} > 0)) || die "cannot remove the last document — to remove the whole instance, use limn remove $n"
    validate_doc_specs "$C_MANUSCRIPT" "${kept[@]}"
    local docs_str
    docs_str=$(join_semi "${kept[@]}")
    write_conf_docs "$n" "$docs_str"
    say "removed from DOCS: $key"
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
        *) die "limn doc list|add|remove <name> ... | suggest --manuscript <manuscript dir> (unknown subcommand: '$sub')" ;;
    esac
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

usage() { sed -n '/^# Usage:/,/^# Security rules/p' "${BASH_SOURCE[0]}" | sed -e '$d' -e 's/^# \{0,1\}//'; }

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
