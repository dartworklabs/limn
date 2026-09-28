#!/usr/bin/env bash
# Sourced by instances.sh to own instance list, status, URL, and agent guidance.

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
