#!/usr/bin/env bash
# Sourced by instances.sh after its shared environment and operations are defined.

# update — reinstalls the installed limn via uv tool and restarts instances that are running. Never
# touches state dirs. To roll back, reinstall the previous tag (limn update --ref v<previous version>).
# A running server is already loaded into memory, so it doesn't die during the install — it switches
# to the new version only on restart.
latest_tag() { # the highest v* tag on the remote. Prints nothing on failure.
    local url=${REPO#git+}
    command -v git > /dev/null 2>&1 || return 0
    GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes}" \
        with_timeout 30 git ls-remote --tags --refs "$url" 'v*' 2> /dev/null \
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
        local rc=0
        wait_ready "$n" "$C_PORT" || rc=$?
        case $rc in
            0) say "  $n restarted → 200" ;;
            3) warn "  $n restarted → 401: $(refused_hint "$n" "$READY_HOW")" ;;
            *) warn "  $n restarted but not responding — limn status $n" ;;
        esac
    done
}
