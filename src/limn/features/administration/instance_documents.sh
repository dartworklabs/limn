#!/usr/bin/env bash
# Sourced by instances.sh; doc parsing also serves add and status commands.

# Multi-document (--doc/DOCS=) limits. Kept in sync with DOC_KEY_RE/DOCS_MAX/DOC_NAME_MAX on the server side (limn/documents.py).
DOCS_MAX=12
DOC_NAME_MAX=40
# ── multiple documents (--doc / DOCS=) ──
# Format is <key>=<display name>:<path>. Parsing/validation rules are kept in sync with the server
# (parse_doc_arg/make_docs in limn/startup.py) — the server re-validates on startup, but filtering
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
# file_mtime <file> — modification time (unix epoch).
file_mtime() { stat_fmt %Y %m "$1"; }

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

# write_conf_docs <name> <DOCS string> — leaves the loaded C_* (filled in by load) as-is and rewrites
# the config file (C_FILE — usually the symlink in home, followed to the source) with DOCS in MAIN's place.
write_conf_docs() {
    local n=$1 docs_str=$2 f=$C_FILE
    {
        # The backticks are literal text in the config header, not a command substitution.
        # shellcheck disable=SC2016
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
        local rc=0
        wait_ready "$n" "$C_PORT" || rc=$?
        case $rc in
            0) say "restarted → 127.0.0.1:$C_PORT 200" ;;
            3) warn "restarted → 127.0.0.1:$C_PORT answers 401: $(refused_hint "$n" "$READY_HOW")" ;;
            *) warn "not responding after restart — limn status $n" ;;
        esac
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
        # without a doc field are also read as this document (docs/handbook/operations.md §여러 문서).
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
