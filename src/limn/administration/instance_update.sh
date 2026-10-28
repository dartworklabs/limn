#!/usr/bin/env bash
# Sourced by instances.sh after its shared environment and operations are defined.

# update — reinstalls the installed limn via uv tool and restarts instances that are running. Never
# touches state dirs. To roll back, reinstall the previous tag (limn update --ref v<previous version>).
# A running server is already loaded into memory, so it doesn't die during the install — it switches
# to the new version only on restart.
#
# Exit status (also in `limn update --help` and docs/handbook/instances.md §업데이트와 되돌리기):
#   0  nothing failed - including "already vX", --dry-run, --no-restart and no running instance
#   1  an error before any restart: bad arguments, no remote tag, the install failed, the unit file could not be written
#   3  installed, but a restarted instance failed (restart failed, unit failed, not 200). Every instance is tried first.
# A 401 from the readiness check is a warning, not a failure: see update_usage.
UPDATE_PARTIAL_RC=3
update_usage() {
    cat << 'EOF'
usage: limn update [--ref <tag|branch>] [--from <install source>] [--dry-run] [--force] [--no-restart]

Reinstalls limn with `uv tool install --force` and restarts the instances that were running. State dirs are never
touched. To roll back, install the previous tag: limn update --ref v<previous version>.

  --ref <tag|branch>   what to install (default: the highest v* tag on the remote)
  --from <source>      install from this source (a checkout or a git URL) instead; not together with --ref
  --dry-run, -n        show what would be installed and restarted, and do nothing
  --force              reinstall even when <ref> is the version that is installed
  --no-restart         install only; the running servers keep the version they loaded until they restart

What it does and does not do:
  - When <ref> is the installed version and --force is not given, it prints "already vX — not reinstalling" and exits
    0 without installing or restarting anything. A server that is still running an older version stays on it; use
    --force to reinstall and restart. --from has no such check.
  - Only instances that were active before the install are restarted. A stopped instance stays stopped and starts on
    the new version when you start it.
  - Each restarted instance is checked until it answers HTTP 200 (LIMN_WAIT seconds, 240 by default - the first
    boot waits for the build). A 401 means the server is up but refused the check (no usable token file, or a revoked
    one): that is a warning and not a failure, the same as in `limn start`.
  - Every instance is tried even after one failed; the failures are named in one line at the end.

Exit status:
  0  nothing failed. This includes "already vX", --dry-run, --no-restart and no running instance.
  1  an error before any instance was restarted: bad arguments, no remote tag, the install failed (limn stays on the
     current version) or the unit file could not be written.
  3  limn is installed, but at least one instance that was running did not come back: its restart failed, its unit
     failed, or it did not answer 200 in time. Look at `limn status <name>` and journalctl; to go back, limn update
     --ref v<previous version>.
EOF
}
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
            -h | --help) update_usage; return 0 ;;
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
    # Every instance is tried; the ones that did not come back are remembered and decide the exit status.
    local failed=() rc f list=""
    for n in "${active[@]}"; do
        if ! load "$n"; then
            warn "  $n: could not read the config — not restarted"
            failed+=("$n (config unreadable)")
            continue
        fi
        if ! sysu restart "$(unit_of "$n")"; then
            warn "restart failed: $(unit_of "$n")"
            failed+=("$n (restart failed)")
            continue
        fi
        rc=0
        wait_ready "$n" "$C_PORT" || rc=$?
        case $rc in
            0) say "  $n restarted → 200" ;;
            # 401: the server answered, so the restart worked; the check was refused (no usable token file, or a revoked
            # one) and waiting would not change that. Same as `limn start`: a warning, not a failure.
            3) warn "  $n restarted → 401: $(refused_hint "$n" "$READY_HOW")" ;;
            2)
                warn "  $n restarted but its unit failed — journalctl --user -u $(unit_of "$n") -n 50"
                failed+=("$n (unit failed)")
                ;;
            *)
                warn "  $n restarted but not responding — limn status $n"
                failed+=("$n (not responding)")
                ;;
        esac
    done
    [[ ${#failed[@]} -eq 0 ]] && return 0
    for f in "${failed[@]}"; do list+="${list:+, }$f"; done
    printf 'limn: update installed, but %d of %d running instance(s) did not come back: %s\n' \
        "${#failed[@]}" "${#active[@]}" "$list" >&2
    return "$UPDATE_PARTIAL_RC"
}
