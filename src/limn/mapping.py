"""Where a selection lands in the manuscript - the pure half of Limn's position rules.

Everything here takes lines of text, numbers and path strings and returns values: no files, clock, subprocess, HTTP
or module state (coding rule R1, docs/handbook/code-style-roadmap.md). That includes finding a stored pin's file
under a moved manuscript (pin_rel_path), whose existence checks come in as a callback. The effectful half - running
SyncTeX and pdftotext, reading .tex files, the token-weight cache, re-syncing stored pins, resolving paths - is
limn/locate.py, which calls into this module (and into limn.pins.position for the rules about stored pins). The rules
themselves are described in docs/handbook/domain.md.
"""
# Lazy annotations to match server.py's style, not for an older interpreter: Limn needs Python >= 3.10 (server.py
# uses `match`), and instances.sh refuses an older one before it starts the server.
from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeAlias

FLOAT_KINDS = ("figure", "table", "algorithm")


ENV_TOK_RE = re.compile(r"\\(begin|end)\{([^{}]+)\}")

# A word token of the selected text and its rarity weight (limn.locate.TokenCache.weights()).
TokenWeights: TypeAlias = Sequence[tuple[str, float]]
# One rung of the range ladder: level, lo, hi, label, n, snippet, and env/merged when present (compute_levels()).
Level: TypeAlias = dict[str, Any]


# ---------------------------------------------------------------- Line text

def norm(line: str) -> str:
    """The line with runs of whitespace collapsed to one space and the ends trimmed - the form anchors compare."""
    return " ".join(line.split())


def truncate_quote(s: object, n: int = 60) -> str:
    """Truncates a quote to at most n characters (ellipsis included, matching the «...» convention).

    If a truncated quote looked like a complete sentence, it would be confusing when trying to relocate the
    source - the truncation mark is what tells the user/agent to read this as a "search hint", not the
    "whole thing". When truncating, the ellipsis is appended after n-1 characters of body text, so the
    result is always n characters or fewer (never n+1 from n characters plus the ellipsis)."""
    text = str(s)
    return text[:n - 1] + "…" if len(text) > n else text


def is_comment(line: str) -> bool:
    """True for a whole-line LaTeX comment (first non-blank character is %)."""
    return line.lstrip().startswith("%")


def strip_comment(line: str) -> str:
    """The line without its trailing LaTeX comment; an escaped \\% stays."""
    return re.sub(r"(?<!\\)%.*", "", line)


# ---------------------------------------------------------------- Reverse mapping: picking lines

def densest(values: list[int], gap: int = 30) -> list[int]:
    """Breaks at large gaps and keeps only the densest cluster.

    synctex returns the node *closest* to the query coordinate, so even a point inside the selection
    rectangle can pull in a line from an adjacent float (observed: selecting a single table returned a
    range spanning 740-801)."""
    if not values:
        return values
    groups = [[values[0]]]
    for v in values[1:]:
        if v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return max(groups, key=len)


def score_range(tw: TokenWeights, lines: Sequence[str], lo: int, hi: int) -> float:
    """Scores 0-1 how much of the region's characters a candidate line range contains."""
    if not tw:
        return 0.0
    blob = " ".join(lines[max(0, lo - 2):hi + 1])
    return sum(w for t, w in tw if t in blob) / sum(w for _, w in tw)


def by_text(tw: TokenWeights, lines: Sequence[str], near: int | None = None) -> tuple[int, int, float] | None:
    """Recovers source lines from the rendered text's word tokens.

    This is the path used when SyncTeX stays silent or points somewhere wrong on a table/equation region.
    Korean word tokens survive almost untouched by markup (e.g. `타겟--소스 $i$ 간 코사인 거리`), so they
    remain in the source text as-is."""
    if len(tw) < 2:
        return None
    scores = [sum(w for t, w in tw if t in ln) for ln in lines]
    if max(scores, default=0) <= 0:
        return None
    peak = max(range(len(scores)), key=lambda i: (scores[i], -abs(i + 1 - (near or i + 1))))
    lo = hi = peak
    while lo > 0 and scores[lo - 1] > 0:
        lo -= 1
    while hi < len(scores) - 1 and scores[hi + 1] > 0:
        hi += 1
    return lo + 1, hi + 1, score_range(tw, lines, lo + 1, hi + 1)


# ---------------------------------------------------------------- Block expansion and the range ladder

SECTION_RE = re.compile(r"\s*\\(part|chapter|section|subsection|subsubsection|paragraph)\*?[\[{]")


def expand_block(lines: Sequence[str], lo: int, hi: int, envs: Sequence[str]) -> tuple[int, int, str]:
    """Expands the selected lines to the enclosing environment named in envs (--float-envs) or paragraph boundary. Used to determine the default level.

    An environment must be closed by a \\end of the same name - without matching the name, the selection
    leaks into an adjacent float (observed: selecting one table pulled in 109 lines)."""
    n = len(lines)
    if not n:
        return lo, hi, "none"
    lo, hi = max(1, min(lo, n)), max(lo, min(hi, n))
    alt = "|".join(re.escape(e) for e in envs)
    b_re = re.compile(r"\\begin\{(" + alt + r")(\*?)\}")
    e_re = re.compile(r"\\end\{(" + alt + r")(\*?)\}")

    for i in range(lo - 1, -1, -1):
        if e_re.search(lines[i]) and i < lo - 1:
            break
        m = b_re.search(lines[i])
        if not m:
            continue
        env = m.group(1) + m.group(2)
        close = re.compile(r"\\end\{" + re.escape(env) + r"\}")
        opens = re.compile(r"\\begin\{" + re.escape(env) + r"\}")
        depth = 0
        for j in range(i + 1, n):
            if opens.search(lines[j]):
                depth += 1
            if close.search(lines[j]):
                if depth:
                    depth -= 1
                    continue
                return i + 1, j + 1, "float" if m.group(1) in FLOAT_KINDS else "block"
        break

    a, b = para_bounds(lines, lo, hi)
    return a, b, "paragraph"


def para_bounds(lines: Sequence[str], lo: int, hi: int) -> tuple[int, int]:
    """Expands to the nearest blank line. A section-heading line (\\section/\\subsection/...) is never crossed in either direction."""
    n = len(lines)
    a, b = lo, hi
    while a > 1 and lines[a - 2].strip() and not SECTION_RE.match(lines[a - 2]):
        a -= 1
    while b < n and lines[b].strip() and not SECTION_RE.match(lines[b]):
        b += 1
    return a, b


def trim_comments(lines: Sequence[str], a: int, b: int) -> tuple[int, int]:
    """Trims leading/trailing pure-comment lines (starting with %). Does nothing if every line is a comment.

    In a manuscript where one paragraph is one line, this stops a trailing TODO comment from becoming the tail of the pin range and its anchor."""
    x, y = a, b
    while x <= y and is_comment(lines[x - 1]):
        x += 1
    while y >= x and is_comment(lines[y - 1]):
        y -= 1
    return (a, b) if x > y else (x, y)


def env_spans(lines: Sequence[str]) -> list[tuple[int, int, str]]:
    """(start line, end line, name) - every environment paired up by matching name and depth. A \\begin inside a comment is ignored."""
    stack: list[tuple[str, int]] = []
    spans: list[tuple[int, int, str]] = []
    for i, ln in enumerate(lines):
        for m in ENV_TOK_RE.finditer(strip_comment(ln)):
            name = m.group(2).strip()
            if m.group(1) == "begin":
                stack.append((name, i + 1))
                continue
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == name:
                    spans.append((stack[k][1], i + 1, name))
                    del stack[k:]
                    break
    return spans


def snippet(lines: Sequence[str], lo: int, hi: int, cap: int = 80) -> str:
    """Lines lo..hi (1-based, inclusive) numbered in a 5-wide column; beyond cap lines, a Korean "(N줄 더)" tail."""
    chunk = lines[lo - 1:hi]
    extra = len(chunk) - cap
    if extra > 0:
        chunk = chunk[:cap]
    out = "\n".join("%5d  %s" % (lo + k, t) for k, t in enumerate(chunk))
    return out + ("\n      ... (%d줄 더)" % extra if extra > 0 else "")


def find_level(levels: Sequence[Level], key: str) -> Level | None:
    """The ladder level named key, or the level that absorbed it (its "merged" list); None when neither exists."""
    for lv in levels:
        if lv["level"] == key or key in lv.get("merged", ()):
            return lv
    return None


def compute_levels(lines: Sequence[str], raw_lo: int, raw_hi: int, envs: Sequence[str]) -> dict[str, Any]:
    """The range ladder: dragged line / paragraph (trailing comments excluded) / enclosing environments, innermost to outermost, up to 3 levels. envs are the float
    environments (--float-envs) a selection expands to.

    Snippets are included up front so the client can switch levels without a server round trip. There is no
    section level - that would easily produce hundred-line ranges, against the "hand over only a line range" principle."""
    n = len(lines)
    raw_lo = max(1, min(raw_lo, n))
    raw_hi = max(raw_lo, min(raw_hi, n))
    levels: list[Level] = []

    def add(level: str, lo: int, hi: int, label: str, env: str | None = None) -> None:
        """Append a rung, or replace the rung with the same range and list the replaced name under merged."""
        item: Level = {"level": level, "lo": lo, "hi": hi, "label": label, "n": hi - lo + 1,
                "snippet": snippet(lines, lo, hi)}
        if env:
            item["env"] = env
        for i, old in enumerate(levels):              # levels with the same range are merged (keeping the later name)
            if (old["lo"], old["hi"]) == (lo, hi):
                item["merged"] = old.get("merged", []) + [old["level"]]
                levels[i] = item
                return
        levels.append(item)

    add("raw", raw_lo, raw_hi, "드래그한 줄")
    spans = env_spans(lines)
    encl = sorted((s for s in spans if s[0] <= raw_lo <= s[1] and s[2] != "document"),
                  key=lambda s: (s[1] - s[0], -s[0]))
    pa, pb = para_bounds(lines, raw_lo, raw_hi)
    if encl:
        # A paragraph never crosses the innermost enclosing environment. If the drag is strictly inside that
        # environment, the \begin/\end lines are also excluded - otherwise a "paragraph" inside a table would
        # swallow \end{table*} and the line after it, drifting out of sync with the environment (observed: L187-L270).
        ea, eb = encl[0][0], encl[0][1]
        if ea < raw_lo and raw_hi < eb:
            ea, eb = ea + 1, eb - 1
        pa, pb = max(pa, ea), min(pb, eb)
        if pa > pb:
            pa, pb = raw_lo, raw_hi
    # Also never half-overlaps an environment outside the drag (a paragraph right after \end{table*} was
    # swallowing the table's tail). An environment fully contained in the paragraph (an equation with no
    # blank-line break) is left as-is.
    for a, b, name in spans:
        if name == "document" or a <= raw_lo <= b:
            continue
        if b < raw_lo and a < pa <= b:
            pa = b + 1
        elif a > raw_hi and a <= pb < b:
            pb = a - 1
    pa, pb = min(pa, raw_lo), max(pb, raw_hi)
    pa, pb = trim_comments(lines, pa, pb)
    add("para", pa, pb, "문단")
    # If the outer environment wraps the inner one by exactly one line on each side (a single tabular inside
    # a minipage), treat them as the same block - listing the inner one separately would waste a ladder
    # rung on an almost-identical range. The outer name is kept.
    encl = [s for i, s in enumerate(encl)
            if not any(o[0] == s[0] - 1 and o[1] == s[1] + 1 for o in encl[i + 1:])]
    for k, (a, b, name) in enumerate(encl[:3]):
        key = "env" if k == 0 else "env%d" % (k + 1)
        suffix = "" if k == 0 else (" (바깥)" if k == 1 else " (바깥 2)")
        add(key, a, b, "환경 %s%s" % (name, suffix), env=name)

    ea, eb, kind = expand_block(lines, raw_lo, raw_hi, envs)
    default: Level | None = None
    if kind in ("float", "block"):
        for lv in levels:
            if lv["level"].startswith("env") and (lv["lo"], lv["hi"]) == (ea, eb):
                default = lv
                break
        if default is None:
            default = next((lv for lv in levels if lv["level"].startswith("env")), None)
    if default is None:
        default = find_level(levels, "para")
        kind = "paragraph"
    # "para" was added above; a later rung with the same range keeps it in its merged list, so find_level() finds it.
    assert default is not None
    if not default["level"].startswith("env") and kind != "paragraph":
        kind = "paragraph"
    return {"levels": levels, "default_level": default["level"], "lo": default["lo"],
            "hi": default["hi"], "kind": kind}


# ---------------------------------------------------------------- Anchors

def anchor_of(lines: Sequence[str], lo: int, hi: int) -> dict[str, str | int]:
    """Captures the head/tail text of the block a pin points at (pure-comment lines are skipped).

    Storing only line numbers means every pin drifts the moment the manuscript is edited once. The whole
    point of this tool is "an agent edits the manuscript", so a design where editing kills the pins is
    unusable. Comments are skipped because a TODO comment is a line about to be deleted - anchoring to it
    would kill the pin first.

    head_off/tail_off are the distance from lo to the head line, and from the tail line to hi. Without
    these, a pin that deliberately included comment lines at its edges would silently shrink on the first
    line-matching pass (observed: L7-L9 -> L10-L11)."""
    idx = [i for i in range(lo - 1, min(hi, len(lines))) if lines[i].strip()]
    body = [i for i in idx if not is_comment(lines[i])] or idx
    if not body:
        return {}
    return {"head": norm(lines[body[0]]), "tail": norm(lines[body[-1]]),
            "head_off": body[0] - (lo - 1), "tail_off": (hi - 1) - body[-1]}


def find_line(nlines: Sequence[str], needle: object, near: int) -> int | None:
    """The 1-based line in nlines (already norm()-ed) that holds needle, nearest to line near.

    An exact match wins; a needle of 12+ characters falls back to its first 40 characters as a substring.
    None when needle is empty, not a string, or found nowhere.
    """
    if not isinstance(needle, str) or not needle:
        return None
    cands = [i for i, t in enumerate(nlines) if t == needle]
    if not cands and len(needle) >= 12:
        key = needle[:40]
        cands = [i for i, t in enumerate(nlines) if key in t]
    if not cands:
        return None
    return min(cands, key=lambda i: abs(i + 1 - near)) + 1


def anchor_holds(anchor: Mapping[str, Any], lo: int, nlines: Sequence[str]) -> bool:
    """Is the anchor's head line still where the pin's lo says (line lo + head_off, 1-based), by find_line()'s matching
    (the whole norm()-ed line, or its first 40 characters for a head of 12 or more)? head_off that is not an integer in
    0..9999 counts as 0, like a legacy anchor. False for a missing head or a line outside nlines."""
    head, off = anchor.get("head"), anchor.get("head_off")
    off = off if isinstance(off, int) and not isinstance(off, bool) and 0 <= off < 10000 else 0
    i = lo + off - 1
    if not isinstance(head, str) or not head or not 0 <= i < len(nlines):
        return False
    return nlines[i] == head or (len(head) >= 12 and head[:40] in nlines[i])


# ---------------------------------------------------------------- Where a pin's file is (docs/adr/0006-relative-pin-paths.md)

def anchor_offset(v: object) -> int:
    """A stored anchor's head_off/tail_off - how far its first/last non-comment line sits from lo/hi - when it is an int
    in 0..9999, else 0 (a legacy anchor has none, and a bad value must not move the pin)."""
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10000 else 0


def _posix_parts(path: str) -> list[str]:
    """The components of a POSIX path string, without empty and '.' parts ('/a//b/./c' -> ['a', 'b', 'c'])."""
    return [p for p in path.split("/") if p not in ("", ".")]


def file_tails(file: str) -> list[str]:
    """The relative tails of an absolute path, longest first: '/p/s/x.tex' -> ['p/s/x.tex', 's/x.tex', 'x.tex']. A tail
    with a '..' part is left out, so no candidate can climb above the root it is joined to."""
    parts = _posix_parts(file)
    return ["/".join(parts[k:]) for k in range(len(parts)) if ".." not in parts[k:]]


def pin_rel_path(file: str, file_rel: object, under_root: str | None, exists: Callable[[str], bool],
                 scope: str = "") -> str | None:
    """Where a stored line pin's file lives now, relative to the manuscript root - the one rule of ADR-0006 §2.

    1. under_root: the stored absolute `file` relative to the current root when it lies under it (the caller resolves
       symlinks, as 0.3.0's in_tree() did). It wins even if the file is gone - a known location is never re-guessed.
    2. file_rel (stored since 0.3.2), when it is a non-empty relative path without '..' parts and the stored `file`
       ends with it. The server writes the two together; 0.3.1 or 0.3.0 relocating a pin changes only `file`, and the
       mismatch drops the stale value. A longer tail of `file` that exists wins (the root was widened, e.g. paper/ ->
       the repository); otherwise file_rel itself, even if that file is gone - no shorter guess.
    3. For older records, the longest tail of `file` (file_tails) that exists under scope - the pin's document folder
       relative to the root ('' = the whole root, the only case before issue #24). Each tail is joined to scope, so a
       same-named file of another document is never picked and a document folder renamed with its --doc spec is still
       found. A scope with a '..' part finds nothing. Rules 1 and 2 are recorded facts and are not scoped.
    None when nothing matches: the pin is outside the tree. `exists` answers for paths relative to the root and is
    expected to accept only files that resolve inside it; the caller supplies it (this module reads no files). The
    same rule places the paths recorded in a closed pin's `changes` (ADR-0005), which have no file_rel."""
    if under_root is not None:
        return under_root
    tails = file_tails(file)
    if isinstance(file_rel, str) and file_rel and not file_rel.startswith("/"):
        rel, parts = _posix_parts(file_rel), _posix_parts(file)
        n = len(rel)
        if n and ".." not in rel and len(parts) > n and parts[-n:] == rel:
            longer = [t for t in tails if len(_posix_parts(t)) > n]
            return next((t for t in longer if exists(t)), "/".join(rel))
    base = _posix_parts(scope)
    if ".." in base:
        return None
    return next((c for c in ("/".join(base + [t]) for t in tails) if exists(c)), None)
