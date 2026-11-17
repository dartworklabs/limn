"""Where a selection lands in the manuscript - the pure half of Limn's position rules.

Everything here takes lines of text, numbers and path strings and returns values: no files, clock, subprocess, HTTP
or module state (coding rule R1, docs/handbook/code-style-roadmap.md). That includes finding a stored pin's file
under a moved manuscript (pin_rel_path), whose existence checks come in as a callback. The effectful half - running
SyncTeX and pdftotext, reading .tex files, the token-weight cache, re-syncing stored pins, resolving paths - is in
pins/location and limn/pins/location/lookup.py. Both call into this module; stored pin rules also use limn.pins.location.position. The rules
themselves are described in docs/handbook/domain.md.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal, TypeAlias, get_args

from limn.platform.text import flat as flat, truncate_quote as truncate_quote
from limn.platform.values import is_int

FLOAT_KINDS = ("figure", "table", "algorithm")


ENV_TOK_RE = re.compile(r"\\(begin|end)\{([^{}]+)\}")

# A word token of the selected text and its rarity weight (features.pins.location.source.TokenCache.weights()).
TokenWeights: TypeAlias = Sequence[tuple[str, float]]
# One rung of the range ladder: level, lo, hi, label, n, snippet, and env/merged when present (compute_levels()).
Level: TypeAlias = dict[str, Any]
# What block expansion found around a selection (expand_block()): a float environment (FLOAT_KINDS), another listed
# environment, the paragraph - or nothing, for an empty file. compute_levels() answers it as the pick's `kind`.
BlockKind: TypeAlias = Literal["float", "block", "paragraph", "none"]


# ---------------------------------------------------------------- Line text


def norm(line: str) -> str:
    """The line with runs of whitespace collapsed to one space and the ends trimmed - the form anchors compare."""
    return " ".join(line.split())


def is_comment(line: str, marker: str = "%") -> bool:
    """True for a whole-line comment: the first non-blank character is marker (a LaTeX % by default)."""
    return line.lstrip().startswith(marker)


def comment_marker(path: str) -> str:
    """The character a whole-line comment starts with in the source file at path, as anchor_of skips it: "#" for a
    Python script (a figure's drawing code, suffix .py in any case), "%" for every other file - LaTeX, as always."""
    return "#" if path.lower().endswith(".py") else "%"


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


def synctex_range(hits: Sequence[tuple[str, int]]) -> tuple[str, int, int] | None:
    """Choose the file hit by the most sampled PDF points and its densest cluster of source lines.

    None means no point mapped to a source. Callers sample points and run SyncTeX; this function only
    judges its answers. A tie between files has no ranking guarantee, as in the original selection rule.
    """
    if not hits:
        return None
    best = max({file for file, _ in hits}, key=lambda file: sum(1 for hit_file, _ in hits if hit_file == file))
    lines = densest(sorted(line for file, line in hits if file == best))
    return best, lines[0], lines[-1]


@dataclass(frozen=True)
class Carried:
    """Where a range of the lines a build read stands in the file now (carry_range): lo..hi, 1-based and inclusive,
    from the first to the last of its lines still there. whole: every line of the range is there and they are still
    next to one another, so lo..hi holds exactly the text the range held."""

    lo: int
    hi: int
    whole: bool


def carry_range(built: Sequence[str], now: Sequence[str], lo: int, hi: int) -> Carried | None:
    """Carry lines lo..hi (1-based, inclusive) of built - a file as a build read it - over to now, the same file as it
    is today, or None when that text no longer stands there.

    SyncTeX numbers the lines of the source its build read. Used on a file edited since, the numbers name whatever
    moved into their place (observed: five lines added above a paragraph put its pin on the two paragraphs before it).
    The two line lists are compared as a line diff: a line of built survives when the diff pairs it with an equal line of
    now, in order, so a repeated line is followed to its own twin. The answer spans the surviving lines of the range,
    first to last. None when the range names no line of built (lo..hi is cut to 1..len(built) first) or when no line
    with text survives: a blank line left behind is not the text that was dragged.

    The lines the two files share at their start and end are paired directly; only the stretch between is handed to
    difflib, whose shortcut for lines repeated all over a long file can miss a pairing but never invents one - a miss
    reads as a line that did not survive."""
    lo, hi = max(1, lo), min(hi, len(built))
    if lo > hi:
        return None
    head, tail = _shared_ends(built, now)
    mid_end = len(built) - tail  # built[head:mid_end] is the stretch the two files do not plainly share
    shift = len(now) - len(built)
    between = _paired_between(built, now, head, tail) if lo - 1 < mid_end and hi > head else {}
    places: list[int] = []
    text = False
    for i in range(lo - 1, hi):
        j = i if i < head else i + shift if i >= mid_end else between.get(i)
        if j is None:
            continue
        places.append(j)
        text = text or bool(built[i].strip())
    if not text:
        return None
    first, last = places[0] + 1, places[-1] + 1
    return Carried(first, last, len(places) == hi - lo + 1 and last - first == hi - lo)


def _shared_ends(built: Sequence[str], now: Sequence[str]) -> tuple[int, int]:
    """How many lines built and now share at their start and, of what is left, at their end."""
    head = 0
    limit = min(len(built), len(now))
    while head < limit and built[head] == now[head]:
        head += 1
    tail = 0
    while tail < limit - head and built[len(built) - 1 - tail] == now[len(now) - 1 - tail]:
        tail += 1
    return head, tail


def _paired_between(built: Sequence[str], now: Sequence[str], head: int, tail: int) -> dict[int, int]:
    """The line diff of the stretch between the shared ends (_shared_ends): for each line of built there (0-based) that
    the diff pairs with an equal line of now, that line's 0-based index in now."""
    paired: dict[int, int] = {}
    matcher = SequenceMatcher(None, built[head : len(built) - tail], now[head : len(now) - tail])
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            paired[head + a + k] = head + b + k
    return paired


def paired_lines(built: Sequence[str], now: Sequence[str]) -> list[int | None]:
    """For every line of built - a file as a build read it - the 0-based index of the line of now, the same file as it
    is today, that the line diff pairs it with, or None for a line that did not survive. The pairing is carry_range's:
    the lines the two files share at their start and end pair directly, the stretch between through difflib."""
    head, tail = _shared_ends(built, now)
    mid_end = len(built) - tail
    shift = len(now) - len(built)
    between = _paired_between(built, now, head, tail)
    return [i if i < head else i + shift if i >= mid_end else between.get(i) for i in range(len(built))]


def score_range(tw: TokenWeights, lines: Sequence[str], lo: int, hi: int) -> float:
    """Scores 0-1 how much of the region's characters a candidate line range contains."""
    if not tw:
        return 0.0
    blob = " ".join(lines[max(0, lo - 2) : hi + 1])
    return sum(w for t, w in tw if t in blob) / sum(w for _, w in tw)


def one_word_will_do(tw: TokenWeights, lines: Sequence[str], near: int | None) -> bool:
    """Whether one word may place a drag: SyncTeX named a line without text (near; a word of the title it names by
    \\end{frontmatter}) and the word is on exactly one line of the file. A line of text is an answer to weigh, and a word found
    there or not says too little to overrule it, so a drag on the wrong file keeps its warning."""
    return (
        len(tw) == 1
        and near is not None
        and 0 < near <= len(lines)
        and WITHOUT_TEXT_RE.fullmatch(lines[near - 1]) is not None
        and sum(1 for line in lines if tw[0][0] in line) == 1
    )


def by_text(tw: TokenWeights, lines: Sequence[str], near: int | None = None) -> tuple[int, int, float] | None:
    """Recovers source lines from the rendered text's word tokens.

    This is the path used when SyncTeX stays silent or points somewhere wrong on a table/equation region.
    Korean word tokens survive almost untouched by markup (e.g. `타겟--소스 $i$ 간 코사인 거리`), so they
    remain in the source text as-is. One word is enough only where one_word_will_do says so."""
    if len(tw) < 2 and not one_word_will_do(tw, lines, near):
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


# ---------------------------------------------------------------- A pin's mark: boxes on the PDF

# One box on the PDF: (page, x, y, w, h) in PDF points from the page's top left, as SyncTeX's forward search gives it.
Box: TypeAlias = tuple[int, float, float, float, float]

# The most boxes a pin's mark is drawn with. A range that merges into more pieces than this is scattered over the
# document (a float's lines and its text far apart); one mark of many bits says less than none.
BOX_LIMIT = 8

# A box at least this tall, as a share of the page height, is the page or column body, not a line of text.
BODY_HEIGHT_SHARE = 0.25
# With a single line there is no blank between lines to measure; the padding is this share of the line's height.
_LONE_LINE_PAD_SHARE = 0.175


def line_boxes(rows: Sequence[Box], page_h: float) -> list[Box]:
    """The boxes of rows that are lines of text, without the boxes that are the page or a column body.

    SyncTeX answers a line like \\end{document} or \\begin{table} with the boxes of the page body and of each column
    body it sits in (measured on an A4 two-column 10 pt article: 467 pt wide and 548 pt tall for the page body, and
    229 pt wide and 548 pt tall for each column body, on a 595 x 842 pt page). A mark drawn from one would cover a
    column or the page. Height alone tells them from text: a body text line is 8.86 pt high, 1.05% of the page height,
    and a body box is 65%, two orders of magnitude apart, so a box at least 25% of page_h high is dropped. Width cannot
    be the test: a column body is only 38% of the page width, so a width gate lets it through. Nor is the test a
    comparison among the range's own boxes: a table's cells differ wildly in size, so such a comparison drops real
    cells or keeps the body. The trade-off: a float box taller than a quarter of the page is dropped too, and a pin
    on it falls back to the dragged rectangle, which the spec allows for floats. A box as wide as the page but short
    (a rule, a full-width one-line float) is ink of the range and stays, which is why the page width is not asked for."""
    return [row for row in rows if row[4] < BODY_HEIGHT_SHARE * page_h]


def _median(values: Sequence[float]) -> float:
    """The middle of values (the mean of the two middle ones for an even count); values is not empty."""
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _overlaps_across(a: Box, b: Box) -> bool:
    """True when a and b lie on one page and their horizontal spans meet - one column, not two."""
    return a[0] == b[0] and a[1] <= b[1] + b[3] and b[1] <= a[1] + a[3]


def _gap_below(a: Box, b: Box) -> float:
    """The vertical blank between a and b: negative when they overlap."""
    return max(a[2], b[2]) - min(a[2] + a[4], b[2] + b[4])


def range_pad(rows: Sequence[Box]) -> float:
    """How far to grow a mark's boxes on every side: half the blank between the range's lines, to 2 decimals.

    A text line's box is about 8.86 pt high with about 11.96 pt between baselines in 10 pt body text, so the blank
    between two lines is about 3.10 pt. Half of it on each side makes the boxes of neighbouring lines meet exactly, so
    a range reads as one block with no stripes, and a mark never reaches into the line above or below it. The padding
    is measured from the range's own leading, never assumed, because the leading follows the font size and the line
    spacing: at line spacing 1.8 the blank is 12.66 pt and the padding 6.33 pt, in \\Large text 1.0 pt and 0.50 pt. The
    line advance is the middle of the steps down from one box to the next in the same column (so one big skip inside a
    long range does not move it); the blank is that advance less the mean box height. A step that is not downward means
    the boxes restarted at the top of a column or page, which is no leading, and is left out. With no step (a single
    line) the padding is a share of the line's height instead."""
    ordered = sorted(rows, key=lambda r: (r[0], r[2], r[1]))
    steps = [b[2] - a[2] for a, b in zip(ordered, ordered[1:], strict=False) if _overlaps_across(a, b) and b[2] > a[2]]
    if steps:
        mean_h = sum(row[4] for row in ordered) / len(ordered)
        return round(max(0.0, (_median(steps) - mean_h) / 2), 2)
    if not ordered:
        return 0.0
    return round(_median([row[4] for row in ordered]) * _LONE_LINE_PAD_SHARE, 2)


def _touch(a: Box, b: Box, pad: float) -> bool:
    """True when a and b are one block: the same column on one page, and the blank between them no wider than the
    one between two lines of this range - 2 * pad (the leading) plus the taller box."""
    return _overlaps_across(a, b) and _gap_below(a, b) <= 2 * pad + max(a[4], b[4])


def _union(a: Box, b: Box) -> Box:
    """The smallest box that holds both a and b (on one page)."""
    x0, y0 = min(a[1], b[1]), min(a[2], b[2])
    x1, y1 = max(a[1] + a[3], b[1] + b[3]), max(a[2] + a[4], b[2] + b[4])
    return a[0], x0, y0, x1 - x0, y1 - y0


def merge_boxes(rows: Sequence[Box], pad: float, page_w: float, page_h: float, limit: int) -> list[Box]:
    """The mark's pieces: line boxes joined into blocks, grown by pad and cut to the page - or [] over limit boxes.

    Boxes join when they lie on one page, their horizontal spans meet and the blank between them is at most the one
    between two lines of the range (2 * pad plus the taller box). The lines of a paragraph become one block, while a
    range that runs from one column into the next stays two pieces, one per column, and one that crosses a page stays
    one per page. Touching is judged between the boxes as given and joins chain, so a tall block does not widen the
    threshold for what lies below it. Padding is added after joining and clipped to 0..page_w and 0..page_h, so a
    mark at the page's edge does not leave the page. More than limit pieces is a range scattered over the document,
    and there the mark gives up: [] means "draw nothing", not "nothing found". Pieces are rounded to 2
    decimals and sorted by (page, y, x), so the pin's number badge sits on the first one, the top of the range."""
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(rows):
        for j in range(i + 1, len(rows)):
            if _touch(a, rows[j], pad):
                parent[find(j)] = find(i)
    groups: dict[int, Box] = {}
    for i, row in enumerate(rows):
        root = find(i)
        groups[root] = _union(groups[root], row) if root in groups else row
    blocks = list(groups.values())
    grown: list[Box] = []
    for page, x, y, w, h in blocks:
        x0, y0 = max(0.0, x - pad), max(0.0, y - pad)
        x1, y1 = min(page_w, x + w + pad), min(page_h, y + h + pad)
        grown.append((page, round(x0, 2), round(y0, 2), round(x1 - x0, 2), round(y1 - y0, 2)))
    if len(grown) > limit:
        return []
    return sorted(grown, key=lambda b: (b[0], b[2], b[1]))


def built_range(built: Sequence[str], now: Sequence[str], lo: int, hi: int) -> tuple[int, int] | None:
    """The lines of built - a file as a build read it - that hold today's lines lo..hi (1-based, inclusive) of now, or
    None when they are not there whole.

    This is carry_range turned around: SyncTeX numbers the lines of the file the build read, so a range chosen in
    today's file must be read back into that file before its boxes are asked for. "Whole" is carry_range's
    (Carried.whole): every line of lo..hi pairs with a line of built and the paired lines stand next to one another.
    A range that is only partly there - a line edited or added inside it - would get a box for some of its text and
    pass it off as the range's, so it gets none. The same rule on both paths, a fresh pick and a stored pin's listing,
    is what makes them draw the same box instead of flickering between two. A range of blank lines alone is no text
    either, as in carry_range. lo and hi are cut to 1..len(now) first."""
    lo, hi = max(1, lo), min(hi, len(now))
    if lo > hi:
        return None
    built_at = {j: i for i, j in enumerate(paired_lines(built, now)) if j is not None}
    places = [built_at.get(j) for j in range(lo - 1, hi)]
    if None in places:
        return None
    found = [i for i in places if i is not None]
    if found[-1] - found[0] != hi - lo or not any(now[j].strip() for j in range(lo - 1, hi)):
        return None
    return found[0] + 1, found[-1] + 1


# ---------------------------------------------------------------- Block expansion and the range ladder

WITHOUT_TEXT_RE = re.compile(r"\s*(\\end\{[^{}]*\}\W*)?")  # blank, or the end of an environment
PICTURE_LINE_RE = re.compile(r"\\includegraphics(\[[^\]]*\])?\{[^{}]*\}")
SECTION_RE = re.compile(r"\s*\\(part|chapter|section|subsection|subsubsection|paragraph)\*?[\[{]")


def expand_block(lines: Sequence[str], lo: int, hi: int, envs: Sequence[str]) -> tuple[int, int, BlockKind]:
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
    chunk = lines[lo - 1 : hi]
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
        item: Level = {
            "level": level,
            "lo": lo,
            "hi": hi,
            "label": label,
            "n": hi - lo + 1,
            "snippet": snippet(lines, lo, hi),
        }
        if env:
            item["env"] = env
        for i, old in enumerate(levels):  # levels with the same range are merged (keeping the later name)
            if (old["lo"], old["hi"]) == (lo, hi):
                item["merged"] = old.get("merged", []) + [old["level"]]
                levels[i] = item
                return
        levels.append(item)

    add("raw", raw_lo, raw_hi, "드래그한 줄")
    spans = env_spans(lines)
    encl = sorted(
        (s for s in spans if s[0] <= raw_lo <= s[1] and s[2] != "document"), key=lambda s: (s[1] - s[0], -s[0])
    )
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
    encl = [s for i, s in enumerate(encl) if not any(o[0] == s[0] - 1 and o[1] == s[1] + 1 for o in encl[i + 1 :])]
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
    return {"levels": levels, "default_level": default["level"], "lo": default["lo"], "hi": default["hi"], "kind": kind}


# ---------------------------------------------------------------- Choosing a selection's range

# How a selection's range was found: SyncTeX's answer for the box, the rendered text's tokens (by_text), or - on a
# figure document - its build's element map (limn.builds.figure_map, pins/location/figure.py).
Via: TypeAlias = Literal["synctex", "text", "map"]
VIAS: tuple[Via, ...] = get_args(Via)
WEAK_SCORE = 0.3  # below this a weighed selection's best range is flagged as a weak match
SPLIT_MARGIN = 0.12  # two paths scoring closer than this that land apart are flagged as disagreeing


@dataclass(frozen=True)
class Traced:
    """The range a selection traces to (trace_range): the path that won, its raw lines and score (0-1), and the range
    ladder around them (compute_levels: the default rung's lo/hi and kind, every rung, the default's name).

    score is None when there was nothing to weigh, a picture's region or words so common they name no place: no measure,
    not a 0% match. weak is set when the region's text was weighed but the best score is below WEAK_SCORE. split, only when not weak,
    names the winner's and the loser's first lines when both paths scored within SPLIT_MARGIN and the loser's line lies
    outside the chosen range - the two paths point at different places."""

    via: Via
    raw_lo: int
    raw_hi: int
    score: float | None
    lo: int
    hi: int
    kind: str
    levels: list[Level]
    default_level: str
    weak: bool
    split: tuple[int, int] | None


def draws_picture(lines: Sequence[str], synctex: tuple[int, int]) -> bool:
    """Whether SyncTeX's range is one line that holds a picture and nothing else. It names a picture's words by that line
    alone, and the words live in the picture's own file, so the source's words tell nothing about the place. A longer range
    or a line with anything more holds text as well, which the text path may rightly correct."""
    lo, hi = synctex
    return (
        lo == hi
        and 0 < lo <= len(lines)
        and PICTURE_LINE_RE.fullmatch(strip_comment(lines[lo - 1]).strip()) is not None
    )


def trace_range(
    tw: TokenWeights, lines: Sequence[str], synctex: tuple[int, int] | None, envs: Sequence[str]
) -> Traced | None:
    """Pit SyncTeX's range (lo, hi in lines, or None when it gave none) and the text's range (by_text, searched near
    SyncTeX's line) against each other on equal footing and expand the better one into the range ladder. Treating
    either as a conditional fallback would leave no way to catch SyncTeX being silently wrong (inside minipage/tabular).
    On a tie SyncTeX wins - it is the only one that is right in a region with no text (a figure). None when neither
    path gives a range."""
    cands: list[tuple[Via, int, int, float]] = []
    if synctex:
        cands.append(("synctex", synctex[0], synctex[1], score_range(tw, lines, synctex[0], synctex[1])))
    # On a picture SyncTeX is sure, and the picture's words matching some sentence elsewhere would only take the pin away.
    picture = synctex is not None and draws_picture(lines, synctex)
    alt = None if picture else by_text(tw, lines, synctex[0] if synctex else None)
    if alt:
        cands.append(("text", alt[0], alt[1], alt[2]))
    if not cands:
        return None
    cands.sort(key=lambda c: (-c[3], c[0] != "synctex"))
    via, raw_lo, raw_hi, best = cands[0]
    lad = compute_levels(lines, raw_lo, raw_hi, envs)
    lo, hi = lad["lo"], lad["hi"]
    # The paths compete on their raw lines; each rung then says how much of the drag is in its own lines, as the person can
    # choose any, and the answer gives the default's: SyncTeX names a table's cells by its \\end line, whose words are the rows
    # above it, so the raw line alone would say 0% of a table holding every word.
    measured = bool(tw) and not picture
    for level in lad["levels"]:
        level["score"] = round(score_range(tw, lines, level["lo"], level["hi"]), 2) if measured else None
    score = score_range(tw, lines, lo, hi) if measured else None
    weak = score is not None and score < WEAK_SCORE
    # If both expand into the same block, the two paths haven't actually diverged - no disagreement.
    split = (
        (cands[0][1], cands[1][1])
        if not weak
        and len(cands) == 2
        and abs(cands[0][3] - cands[1][3]) < SPLIT_MARGIN
        and not (lo <= cands[1][1] <= hi)
        else None
    )
    return Traced(via, raw_lo, raw_hi, score, lo, hi, lad["kind"], lad["levels"], lad["default_level"], weak, split)


# ---------------------------------------------------------------- Anchors


def anchor_of(lines: Sequence[str], lo: int, hi: int, marker: str = "%") -> dict[str, str | int]:
    """Captures the head/tail text of the block a pin points at (whole-line comments - lines starting with marker,
    comment_marker() of the pin's file - are skipped).

    Storing only line numbers means every pin drifts the moment the manuscript is edited once. The whole
    point of this tool is "an agent edits the manuscript", so a design where editing kills the pins is
    unusable. Comments are skipped because a TODO comment is a line about to be deleted - anchoring to it
    would kill the pin first.

    head_off/tail_off are the distance from lo to the head line, and from the tail line to hi. Without
    these, a pin that deliberately included comment lines at its edges would silently shrink on the first
    line-matching pass (observed: L7-L9 -> L10-L11)."""
    idx = [i for i in range(lo - 1, min(hi, len(lines))) if lines[i].strip()]
    body = [i for i in idx if not is_comment(lines[i], marker)] or idx
    if not body:
        return {}
    return {
        "head": norm(lines[body[0]]),
        "tail": norm(lines[body[-1]]),
        "head_off": body[0] - (lo - 1),
        "tail_off": (hi - 1) - body[-1],
    }


def find_line(nlines: Sequence[str], needle: object, near: int) -> int | None:
    """The 1-based line in nlines (already norm()-ed) that holds needle, nearest to line near.

    An exact match wins; a needle of 12+ characters falls back to its first 40 characters as a substring.
    None when needle is empty, not a string, or found nowhere.
    """
    if not isinstance(needle, str) or not needle:
        return None
    cands = [i for i, t in enumerate(nlines) if t == needle]
    key = partial_key(needle)
    if not cands and key is not None:
        cands = [i for i, t in enumerate(nlines) if key in t]
    if not cands:
        return None
    return min(cands, key=lambda i: abs(i + 1 - near)) + 1


def anchor_holds(anchor: Mapping[str, Any], lo: int, nlines: Sequence[str]) -> bool:
    """Is the anchor's head line still where the pin's lo says (line lo + head_off, 1-based), by find_line()'s matching
    (the whole norm()-ed line, or its first 40 characters for a head of 12 or more)? head_off that is not an integer in
    0..9999 counts as 0, like a legacy anchor. False for a missing head or a line outside nlines."""
    head = anchor.get("head")
    i = lo + anchor_offset(anchor.get("head_off")) - 1
    if not isinstance(head, str) or not head or not 0 <= i < len(nlines):
        return False
    key = partial_key(head)
    return nlines[i] == head or (key is not None and key in nlines[i])


def partial_key(needle: str) -> str | None:
    """The part of an anchor line that may match inside a norm()-ed line of the file: its first 40 characters when
    it has 12 or more, else None - a shorter line only matches a whole line (find_line, anchor_holds)."""
    return needle[:40] if len(needle) >= 12 else None


def anchor_offset(v: object) -> int:
    """A stored anchor's head_off/tail_off - how far its first/last non-comment line sits from lo/hi - when it is an int
    in 0..9999, else 0 (a legacy anchor has none, and a bad value must not move the pin)."""
    return v if is_int(v) and 0 <= v < 10000 else 0


# ---------------------------------------------------------------- Where a pin's file is (docs/adr/0006-relative-pin-paths.md)


def _posix_parts(path: str) -> list[str]:
    """The components of a POSIX path string, without empty and '.' parts ('/a//b/./c' -> ['a', 'b', 'c'])."""
    return [p for p in path.split("/") if p not in ("", ".")]


def file_tails(file: str) -> list[str]:
    """The relative tails of an absolute path, longest first: '/p/s/x.tex' -> ['p/s/x.tex', 's/x.tex', 'x.tex']. A tail
    with a '..' part is left out, so no candidate can climb above the root it is joined to."""
    parts = _posix_parts(file)
    return ["/".join(parts[k:]) for k in range(len(parts)) if ".." not in parts[k:]]


def pin_rel_path(
    file: str, file_rel: object, under_root: str | None, exists: Callable[[str], bool], scope: str = ""
) -> str | None:
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
