#!/usr/bin/env bash
# Sourced by instances.sh to own instance creation, run, start, stop, and removal.

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
    valid_ui_lang "$C_UI_LANG" || die "UI_LANG must be ko or en (or left out — the browser's language decides): '$C_UI_LANG'"
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
    [[ -n "$C_UI_LANG" ]] && args+=(--ui-lang "$C_UI_LANG")
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
    local manuscript="" main="" port="" ts="" gitpull=0 label="" accent="" ui_lang="" state="" extra_args="--no-build" serve=1 start=1
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
            --ui-lang) ui_lang=${2:-}; shift 2 ;;
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
    valid_ui_lang "$ui_lang" || die "--ui-lang must be ko or en: $ui_lang"
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
        emit UI_LANG "$ui_lang"
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
