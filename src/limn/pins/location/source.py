"""SyncTeX and printed-text samples, where a line range prints, and token weights cached per file version."""

import contextlib
import html
import re
import subprocess
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from limn.pins.location.mapping import (
    FORWARD_LINES_MAX,
    Box,
    MarkPiece,
    TokenWeights,
    built_range,
    line_boxes,
    merge_boxes,
    range_pad,
    strip_comment,
    synctex_range,
)
from limn.platform.files import ManuscriptFile

# A word token worth weighting: a Hangul word of 2+ syllables, a Latin word of 4+ letters, or a decimal number.
TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{4,}|\d+\.\d+")
NUMBER_RE = re.compile(r"\d+\.\d+")
# One word of `pdftotext -bbox`, its box in points from the page's top left.
WORD_BOX_RE = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')


# ---------------------------------------------------------------- Reverse mapping 1: SyncTeX


def synctex_edit(pdf: Path, page: int, x: float, y: float) -> tuple[str, int] | None:
    """The (input file, line) SyncTeX gives for one point of a page (in points), or None when it gives none, is
    missing or times out (10 s)."""
    try:
        out = subprocess.run(
            ["synctex", "edit", "-o", "%d:%.2f:%.2f:%s" % (page, x, y, pdf)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    inp = line = None
    for ln in out.splitlines():
        if ln.startswith("Input:"):
            inp = ln[6:].strip()
        elif ln.startswith("Line:"):
            with contextlib.suppress(ValueError):
                line = int(ln[5:].strip())
        if inp and line:
            return inp, line
    return None


def synctex_view(pdf: Path, tex: str, line: int) -> list[Box]:
    """The PDF boxes SyncTeX prints for one source line, as (page, x, y, w, h) in points from the page's top left,
    exactly as read and in printed order; empty when the line has none, the tool is missing or it times out (10 s).

    `tex` is passed to `-i` untouched: SyncTeX selects the file by that name, so the caller owns choosing it.
    A record is the lines from one `Output:` to the next, and only `Page`, `h`, `v`, `W`, `H` are read (the
    lowercase `x`/`y` are a different pair, and the banner and `before:`/`offset:`/`middle:`/`after:` lines are
    ignored). `v` is the box's bottom reference and `H` its height, so its top edge is `v - H` (measured: `y` in
    the output is not that), rounded to the tool's six printed decimals to drop subtraction noise. A record missing one of the five or holding an unreadable number is skipped.
    Records come back out of document order, so the caller orders them; nothing is sorted or de-duplicated here."""
    try:
        out = subprocess.run(
            ["synctex", "view", "-i", "%d:0:%s" % (line, tex), "-o", str(pdf)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    records: list[dict[str, str]] = []
    for ln in out.splitlines():
        key, _, value = ln.partition(":")
        if key == "Output":
            records.append({})
        elif records and key in ("Page", "h", "v", "W", "H"):
            records[-1][key] = value.strip()
    boxes: list[Box] = []
    for rec in records:
        if len(rec) < 5:
            continue
        try:
            page, h, v, w, ht = int(rec["Page"]), float(rec["h"]), float(rec["v"]), float(rec["W"]), float(rec["H"])
        except ValueError:
            continue
        boxes.append((page, h, round(v - ht, 6), w, ht))
    return boxes


def by_synctex(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float) -> tuple[str, int, int] | None:
    """The SyncTeX candidate for a box: (file, lo, hi), or None when no sample point maps anywhere.

    Samples a grid over the box (2-5 columns, 2-6 rows by its size); mapping.synctex_range chooses
    the file most samples land in and the densest cluster of their lines."""
    w, h = x1 - x0, y1 - y0
    nx = max(2, min(5, int(w / 40) + 2))
    ny = max(2, min(6, int(h / 14) + 2))
    hits = []
    for i in range(nx):
        for j in range(ny):
            r = synctex_edit(pdf, page, x0 + w * (i + 0.5) / nx, y0 + h * (j + 0.5) / ny)
            if r:
                hits.append(r)
    return synctex_range(hits)


# ---------------------------------------------------------------- Forward mapping: where a range prints
#
# SyncTeX the other way round: a pin's mark is the area its line range covers on the page, so an answer that
# carries a mark asks here (docs/adr/0045-pin-marks-follow-the-range.md).


def build_copy_name(build: Path, src: Path, file: Path) -> str:
    """The name `synctex view -i` selects the manuscript file `file` by: that file as it lies inside the build copy
    `build` of the build root `src`, absolute.

    SyncTeX knows the names the build recorded, which are the build copy's, and it really selects by the name: in a
    two-file document (main.tex with \\input{sections/part}) the relative name sections/part.tex and its absolute form
    each answer two boxes for line 1, while the basename part.tex and a name no file has answer nothing. A single-file
    document answers even for a name no file has, so that leniency is an accident of having one input and not
    something to lean on.

    Both sides of the prefix test are resolved, the way limn.builds.built_source.source_key resolves them: a build
    root registered through a symlink (a temporary folder under macOS's /var -> /private/var) otherwise fails the test
    though the file does lie below it, and SyncTeX is then asked for a name no build recorded - the mark vanishes with
    no signal while the source record lookup beside it still succeeds. A file that really does not lie below the build
    root has no name in the copy at all - the copy holds that root's tree - and there the checkout path is the closest
    name there is; losing a mark is the cost of being wrong about it, and failing the pick would be a far larger one."""
    try:
        return str(build / file.resolve().relative_to(src.resolve()))
    except (ValueError, OSError, RuntimeError):
        return str(file)


def boxes_for_range(
    pdf: Path,
    tex: str,
    built: Sequence[str] | None,
    now: Sequence[str],
    lo: int,
    hi: int,
    page_w: float,
    page_h: float,
    limit: int,
) -> tuple[MarkPiece, ...]:
    """Where lines lo..hi (1-based, inclusive) of the file as it is today (now) print on the PDF of the build that
    read `built`: the mark's pieces as (page, frac) pairs, each frac a box in fractions of the page page_w x page_h.
    Empty when there is no answer, and the mark then falls back to the rectangle that was dragged.

    Every answer that carries a mark computes it here - a pick's default range and each rung of a snippet - so the
    same lines of the same file always draw the same box (docs/adr/0045-pin-marks-follow-the-range.md). `tex` is the
    name SyncTeX selects the file by (build_copy_name) and `limit` the most pieces a mark may have, which the caller
    owns.

    The range is one the agent receives - a pick's default level, a rung of the ladder - not SyncTeX's own narrower
    range, and the text path has none at all. So it is read back into the lines that build read
    (mapping.built_range) before SyncTeX is asked, and a range that no longer stands whole in those lines gets no
    mark: half a range's boxes passed off as the range's would place the mark on text the pin does not hold. A build
    that kept no record (made by an older Limn) leaves the numbers as they are, which is what SyncTeX's own answer
    already stands for.

    A line with no text once its comment is stripped is skipped, which is correctness and not thrift: `synctex view`
    answers a blank line through its ancestor search, and measured on a two-column 10 pt A4 document a blank line
    answered 17 boxes which were the printed lines of the paragraph *before* it (another answered 44, the page and
    column bodies among them). They are ordinary text boxes, so the height filter leaves them, and the 3.12 pt between
    them and the real paragraph is inside the adjacency threshold - the mark would have become one piece covering both
    paragraphs. Over FORWARD_LINES_MAX lines of text the range is left unmarked rather than paid for. A page of no
    width or height is a broken page list rather than a mark to draw, and is answered like every other box path that
    has no answer: with none, and without running the tool."""
    if page_w <= 0 or page_h <= 0:
        return ()
    lo, hi = max(1, lo), min(hi, len(now))
    if lo > hi:
        return ()
    in_build = built_range(built, now, lo, hi) if built is not None else (lo, hi)
    if in_build is None:
        return ()
    shift = in_build[0] - lo  # built_range answers a range of the same length, so one shift places every line of it
    asked = [i + shift for i in range(lo, hi + 1) if strip_comment(now[i - 1]).strip()]
    if not asked or len(asked) > FORWARD_LINES_MAX:
        return ()
    rows: list[Box] = []
    for line in asked:
        rows.extend(synctex_view(pdf, tex, line))
    kept = line_boxes(rows, page_h)
    pieces = merge_boxes(kept, range_pad(kept), page_w, page_h, limit)
    return tuple((page, (x / page_w, y / page_h, w / page_w, h / page_h)) for page, x, y, w, h in pieces)


# ---------------------------------------------------------------- Reverse mapping 2: rendered text


def region_text(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float) -> str:
    """The characters printed inside the selection rectangle, "" when pdftotext is missing or times out (15 s).

    pdftotext's crop takes a word only when the word's lower part lies inside the rectangle, so a drag along a line of
    text, a few points high, or one over the top of a line, gets nothing: 8 pt over the top of a 9.3 pt word gave "". Such
    a drag touches the words all the same, so it reads the words it touches (touched_text)."""
    return cropped_text(pdf, page, x0, y0, x1, y1).strip() or touched_text(pdf, page, x0, y0, x1, y1)


def cropped_text(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float) -> str:
    """pdftotext's text of the rectangle (1px = 1pt since -r 72); "" when pdftotext is missing or times out (15 s)."""
    try:
        return subprocess.run(
            [
                "pdftotext",
                "-f",
                str(page),
                "-l",
                str(page),
                "-r",
                "72",
                "-x",
                str(int(x0)),
                "-y",
                str(int(y0)),
                "-W",
                str(max(1, int(x1 - x0))),
                "-H",
                str(max(1, int(y1 - y0))),
                str(pdf),
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def touched_text(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float) -> str:
    """The page's words the rectangle overlaps at all, one space apart in pdftotext's order; "" when there are none or
    pdftotext is missing or times out (15 s)."""
    try:
        words = subprocess.run(
            ["pdftotext", "-bbox", "-f", str(page), "-l", str(page), str(pdf), "-"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return " ".join(
        html.unescape(word)
        for left, top, right, bottom, word in WORD_BOX_RE.findall(words)
        if float(left) < x1 and x0 < float(right) and float(top) < y1 and y0 < float(bottom)
    )


def file_key(path: ManuscriptFile) -> tuple[str, int, int]:
    """Identify a checked source version without following replacement symlinks; zeros on refusal."""
    metadata = path.metadata()
    return (str(path), metadata.st_mtime_ns, metadata.st_size) if metadata is not None else (str(path), 0, 0)


@dataclass
class TokenCache:
    """The document frequencies of one file's word tokens, kept for the last file weighed (one entry).

    The composition root makes one per process; picks from several request threads share it under its lock."""

    _entry: dict[tuple[str, int, int], tuple[dict[str, int], str]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def weights(self, text: str, lines: Sequence[str], key: tuple[str, int, int]) -> TokenWeights:
        """Weights the region text's word tokens by rarity in lines (the file identified by key, file_key()).

        Without weighting, common words like "target"/"data"/"training" dominate the score, so a selection that
        actually picked the Nomenclature can come out scoring high overlap with a body paragraph too (observed).
        The rarer a token, the more power it has to pin down a location; a word on more than 5% of the lines is
        dropped. A number the file does not hold is dropped too: a \\ref printed it, no line can contain it, and weighed as
        the rarest of all "5.5" took a right place to 34%. Those it holds weigh together no more than the lightest word beside
        them: they can tell two rows with the same label apart, but a printed "3.2" matching an unrelated 3.2 outweighed every
        word and took a drag whose line held all of its words to another paragraph. A word the file lacks stays, because it says
        something: the drag may be on another file, which is what the score is there to catch.
        The cache key is (path, mtime_ns, size) - id(lines) gets reused once the list is garbage-collected
        and can pick up another file's frequencies."""
        with self._lock:
            entry = self._entry.get(key)
        if entry is None:
            df: dict[str, int] = {}
            for ln in lines:
                for t in set(TOKEN_RE.findall(ln)):
                    df[t] = df.get(t, 0) + 1
            entry = (df, "\n".join(lines))
            with self._lock:
                self._entry.clear()
                self._entry[key] = entry
        df, whole = entry
        n = max(1, len(lines))
        kept = [(t, df.get(t, 0)) for t in {t for t in TOKEN_RE.findall(text) if len(t) >= 2}]
        # a word scattered across the whole manuscript names no place
        kept = [(t, freq) for t, freq in kept if freq <= n * 0.05]
        kept = [(t, freq) for t, freq in kept if freq or not NUMBER_RE.fullmatch(t) or t in whole]
        numbers = sum(1 for t, _ in kept if NUMBER_RE.fullmatch(t))
        lightest = min((1.0 / (1.0 + freq) for t, freq in kept if not NUMBER_RE.fullmatch(t)), default=numbers)
        share = lightest / max(1, numbers)
        return [
            (t, min(1.0 / (1.0 + freq), share) if NUMBER_RE.fullmatch(t) else 1.0 / (1.0 + freq)) for t, freq in kept
        ]
