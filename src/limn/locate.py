"""Where a selection and a stored pin are in the manuscript on this machine now - the effectful half of the position
rules (docs/handbook/domain.md).

This module reads what the rules need: the .tex files, where a pin's file is under a moved checkout (ADR-0006), the
build history, SyncTeX and pdftotext for a dragged region. The rules themselves are pure - the range ladder, scores
and anchors in limn.mapping, estimation, overlap and anchor re-sync in limn.pins.position - and are called from here.

Everything the instance decides comes in as an argument: the document (limn.documents.Doc), the manuscript root, the
float environments, the state folder, the token-weight cache and the store's pins (PickContext), and the Locator that
says where each pin's file is now (the overlaps count each pin in that file). Nothing here reads
the server's run settings or imports the server (coding rule R5); the composition root (server.py) binds these.
"""

import contextlib
import re
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Protocol, TypeAlias, cast

from limn import build
from limn.documents import Doc, to_source
from limn.files import file_in_tree, tex_lines, tree_part
from limn.mapping import (
    TokenWeights,
    Traced,
    compute_levels,
    densest,
    norm,
    pin_rel_path,
    snippet,
    trace_range,
    truncate_quote,
)
from limn.pins import position
from limn.pins.edit import PDF_QUOTE_MAX
from limn.pins.model import OpenPin, is_region_pin, state_of
from limn.pins.position import EstContext, epoch, est_basis, resync

# One stored pin as the store reads it: a JSON object (limn.store.Row).
Row: TypeAlias = dict[str, Any]
# A word token worth weighting: a Hangul word of 2+ syllables, a Latin word of 4+ letters, or a decimal number.
TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{4,}|\d+\.\d+")


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


def by_synctex(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float) -> tuple[str, int, int] | None:
    """The SyncTeX candidate for a box: (file, lo, hi), or None when no sample point maps anywhere.

    Samples a grid over the box (2-5 columns, 2-6 rows by its size), keeps the file most samples land in, and the
    densest cluster of their lines (mapping.densest)."""
    w, h = x1 - x0, y1 - y0
    nx = max(2, min(5, int(w / 40) + 2))
    ny = max(2, min(6, int(h / 14) + 2))
    hits = []
    for i in range(nx):
        for j in range(ny):
            r = synctex_edit(pdf, page, x0 + w * (i + 0.5) / nx, y0 + h * (j + 0.5) / ny)
            if r:
                hits.append(r)
    if not hits:
        return None
    best = max({f for f, _ in hits}, key=lambda f: sum(1 for g, _ in hits if g == f))
    ls = densest(sorted(ln for f, ln in hits if f == best))
    return best, ls[0], ls[-1]


# ---------------------------------------------------------------- Reverse mapping 2: rendered text


def region_text(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float) -> str:
    """Pulls out the characters actually printed inside the selection rectangle (1px = 1pt since -r 72); "" when
    pdftotext is missing or times out (15 s)."""
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


def file_key(path: Path) -> tuple[str, int, int]:
    """(path, mtime_ns, size) - identifies one version of a file for TokenCache; (path, 0, 0) when it cannot be stat'ed."""
    try:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(path), 0, 0)


@dataclass
class TokenCache:
    """The document frequencies of one file's word tokens, kept for the last file weighed (one entry).

    The composition root makes one per process; picks from several request threads share it under its lock."""

    _entry: dict[tuple[str, int, int], dict[str, int]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def weights(self, text: str, lines: Sequence[str], key: tuple[str, int, int]) -> TokenWeights:
        """Weights the region text's word tokens by rarity in lines (the file identified by key, file_key()).

        Without weighting, common words like "target"/"data"/"training" dominate the score, so a selection that
        actually picked the Nomenclature can come out scoring high overlap with a body paragraph too (observed).
        The rarer a token, the more power it has to pin down a location; a word on more than 5% of the lines is
        dropped. The cache key is (path, mtime_ns, size) - id(lines) gets reused once the list is garbage-collected
        and can pick up another file's frequencies."""
        with self._lock:
            df = self._entry.get(key)
        if df is None:
            df = {}
            for ln in lines:
                for t in set(TOKEN_RE.findall(ln)):
                    df[t] = df.get(t, 0) + 1
            with self._lock:
                self._entry.clear()
                self._entry[key] = df
        n = max(1, len(lines))
        out = []
        for t in {t for t in TOKEN_RE.findall(text) if len(t) >= 2}:
            freq = df.get(t, 0)
            if freq > n * 0.05:  # a word scattered across the whole manuscript can't pin down a location
                continue
            out.append((t, 1.0 / (1.0 + freq)))
        return out


# ---------------------------------------------------------------- Where a pin's file is now (ADR-0006)


class PinLocation(NamedTuple):
    """Where a line pin's file is on this machine now (pin_location, docs/adr/0006-relative-pin-paths.md)."""

    rel: str  # POSIX path relative to the manuscript root (--manuscript)
    path: Path  # root / rel - the absolute path the API returns as `file`


# Where a stored pin's file is now, as the composition root binds pin_location to its root and documents. It only
# reads the record, so a read-only record (a Mapping) is enough.
Locator: TypeAlias = Callable[[Mapping[str, Any]], PinLocation | None]


class BuildRoot(Protocol):
    """A document as doc_scope reads it: only its build root. limn.documents.Doc is one, and so is the revision
    services' document (limn.revisions.RevisionDoc), whose recorded paths the composition root locates too."""

    @property
    def src(self) -> Path:
        """The build root - the folder a build copies."""
        ...


def _within(p: Path, root: Path) -> bool:
    """Does p, symlinks resolved, belong to the tree root (limn.files.tree_part: inside root and under no dot-named
    part such as .git)? False when either cannot be resolved."""
    return tree_part(p, root) is not None


def doc_scope(D: BuildRoot | None, root: Path) -> str:
    """Document D's build root relative to the manuscript root, in POSIX form ('' for the root itself): where a moved
    record's tail is searched (issue #24), so a same-named file of another document is never picked. A LaTeX
    document's pins come from its own build, which copies only that folder, so nothing of D lies outside it. '' when
    D is None (a record whose document is no longer configured - the whole root, as in 0.3.2) or D.src is not under
    root."""
    if D is None:
        return ""
    try:
        rel = D.src.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        return ""
    return "" if rel == "." else rel


def locate_file(file: object, file_rel: object, root: Path, doc: BuildRoot | None) -> PinLocation | None:
    """Where a stored absolute path is under the manuscript root on this machine now, by the one rule of ADR-0006
    (pin_rel_path) - a pin's own `file` (with its file_rel) or a path in its `changes` (none), the tail guess searched
    in the folder of doc (doc_scope). None for a missing path or one the rule cannot place inside root.

    Only file metadata is read (resolve, is_file) - under root, apart from resolving the stored path itself as 0.3.0's
    in_tree() did - and never file contents: a line read from outside the tree would leak into the anchor and out
    through GET /api/pins. The result is checked once more after resolving symlinks against the tree rule
    (limn.files.tree_part), so a link inside the tree cannot lead outside, and a path under a dot-named part (.git,
    .env) is never located - a pin recorded there before that rule is outside the tree (a tail through such a link or
    part is skipped for the next one)."""
    if not isinstance(file, str) or not file:
        return None
    try:
        under: str | None = Path(file).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        under = None
    scope = doc_scope(doc, root) if under is None else ""  # only a moved record needs its document folder
    rel = pin_rel_path(file, file_rel, under, lambda t: (root / t).is_file() and _within(root / t, root), scope)
    if rel is None:
        return None
    path = root / rel
    return PinLocation(rel, path) if _within(path, root) else None


def pin_location(r: Mapping[str, Any], root: Path, doc: Doc | None) -> PinLocation | None:
    """Where line pin r's file is under the manuscript root on this machine now (locate_file, the tail guess limited to
    the folder of doc - the pin's own document, None when it is no longer configured), or None: a view-only PDF pin,
    or a file the rule cannot place inside root."""
    return locate_file(r.get("file"), r.get("file_rel"), root, doc)


def stamp_location(r: Row, root: Path, doc: Doc | None) -> PinLocation | None:
    """Records where line pin r's file is now (ADR-0006 §1): `file` becomes the current absolute path and `file_rel` the
    path relative to root. Only for a write to this very pin (create, edit, restore) - other writes keep the stored
    record, so there is no write migration. A pin that cannot be located, or a view-only PDF pin, is left as it is.
    Mutates r and returns its location (or None)."""
    loc = pin_location(r, root, doc)
    if loc is not None:
        r["file"], r["file_rel"] = str(loc.path), loc.rel
    return loc


def located_file(r: Row, locate: Locator) -> str:
    """The file an open line pin is counted in for overlaps: where locate places it now, else its stored `file` - so
    pins made before and after a move of the checkout are one file."""
    loc = locate(r)
    return str(loc.path) if loc else str(r.get("file"))


# ---------------------------------------------------------------- Overlap - a computed field, never stored
#
# The rule is limn.pins.position's (overlaps_by_id, selection_rel, overlaps_for_range); here each pin is counted in
# the file locate finds for it now (located_file), so a moved checkout's old and new pins overlap as one file.


def overlaps_by_id(rows: Sequence[Row], locate: Locator) -> dict[int, list[dict[str, Any]]]:
    """The relationship of every pair of open line pins of rows on the same file, as locate places each pin's file now
    (limn.pins.position.overlaps_by_id): {id: [{"id", "rel"}, ...]} with an entry for every open pin. Never stored."""
    return position.overlaps_by_id(rows, lambda r: located_file(cast(Row, r), locate))  # r is one of rows


def overlaps_for_range(file: str, lo: int, hi: int, rows: Sequence[Row], locate: Locator) -> list[dict[str, Any]]:
    """The overlap relationships between a not-yet-saved range lo..hi of file and the open line pins of rows that
    locate places in that file now (limn.pins.position.overlaps_for_range): [{"id", "lo", "hi", "rel"}] in row order.
    Nothing is saved."""
    return position.overlaps_for_range(file, lo, hi, rows, lambda r: located_file(cast(Row, r), locate))  # one of rows


# ---------------------------------------------------------------- Anchors and re-syncing


def sync_all(rows: list[Row], locate: Locator) -> bool:
    """If the manuscript is newer than a pin, re-match its line numbers via the anchor (limn.pins.position.resync).
    A changed record replaces its row in rows; returns whether any row changed. The pin store calls this under its lock
    before every transaction (limn.store.PinStore.sync).

    Open line pins only (a view-only PDF's pin has no lines). The pin's file is the one locate finds (ADR-0006: a moved
    checkout is followed; outside the tree is never read); a pin whose file cannot be located or is not a file now is
    left alone. Each file is read once per call."""
    changed = False
    cache: dict[Path, tuple[list[str], list[str], float]] = {}
    for i, r in enumerate(rows):
        if state_of(r) is not OpenPin or is_region_pin(r):  # a view-only PDF's pin has no lines - nothing to re-match
            continue
        loc = locate(r)
        if loc is None:
            continue
        f = loc.path
        try:
            if not f.is_file():
                continue
        except OSError:
            continue
        if f not in cache:
            ls = tex_lines(f)
            cache[f] = (ls, [norm(t) for t in ls], f.stat().st_mtime)
        lines, nlines, mtime = cache[f]
        new = resync(r, lines, nlines, mtime, str(f))
        if new is not None:
            rows[i] = new
            changed = True
    return changed


# ---------------------------------------------------------------- Location estimation (.est)


def est_context(D: Doc) -> EstContext:
    """What estimation needs to know about document D's builds (limn.pins.position.est_basis), its history read once."""
    h = build.load_builds(D)
    cur = build.cur_pages(D).name
    return est_basis(cur, h["by"], build.read_built_src_mtime(D), epoch(build.read_built_at(D)))


# ---------------------------------------------------------------- Selection resolution


class Selection(Protocol):
    """A validated drag (limn.web.parse.PickRequest): the page directory it is traced in, the page (1-based), the box
    (x0, y0, x1, y1) in points clamped to the page, the page size (width, height) in points, and the viewer's frac as
    sent (None if absent)."""

    @property
    def pdir(self) -> Path:
        """The page directory on screen at drag time."""
        ...

    @property
    def page(self) -> int:
        """The page, 1-based."""
        ...

    @property
    def box(self) -> tuple[float, float, float, float]:
        """x0, y0, x1, y1 in points."""
        ...

    @property
    def size(self) -> tuple[float, float]:
        """The page's width and height in points."""
        ...

    @property
    def frac(self) -> list[float] | None:
        """The viewer's page-relative box, or None."""
        ...


class SourceLines(Protocol):
    """A validated range of a manuscript file (limn.web.parse.SourceRange): the file, its lines as read, and
    1 <= lo <= hi <= len(lines)."""

    @property
    def file(self) -> Path:
        """The file inside the manuscript tree."""
        ...

    @property
    def lines(self) -> list[str]:
        """Its lines (tex_lines)."""
        ...

    @property
    def lo(self) -> int:
        """First line, 1-based."""
        ...

    @property
    def hi(self) -> int:
        """Last line, inclusive."""
        ...


@dataclass(frozen=True)
class PickContext:
    """What resolving a selection needs from the instance: the manuscript root (a SyncTeX answer outside it is
    refused), the float environments of the range ladder (--float-envs), the state folder (for the "PDF older than the
    manuscript" check), the process's token-weight cache, and the overlaps of a range with the stored open pins
    (file, lo, hi) -> [{"id", "lo", "hi", "rel"}]."""

    root: Path
    envs: Sequence[str]
    state: Path
    tokens: TokenCache
    overlaps: Callable[[str, int, int], list[dict[str, Any]]]


@dataclass(frozen=True)
class Picked:
    """A selection traced to lines of a manuscript file: the file (inside the tree), the page, the range the paths
    agreed on (limn.mapping.Traced), the file's line count and the chosen range's text, the viewer's frac as sent, the
    region's printed text as a short quote, the stored open pins that range overlaps, and the page directory it was
    traced in. stale: the manuscript is newer than that build's PDF (by more than 2 s); building: a LaTeX build is
    running now. The HTTP answer (limn.web.answers.pick_answer) turns this into the pick body."""

    file: Path
    page: int
    traced: Traced
    n_lines: int
    snippet: str
    frac: list[float] | None
    quote: str
    overlaps: list[dict[str, Any]]
    pdf_build: str
    stale: bool
    building: bool


@dataclass(frozen=True)
class PickedRegion:
    """A selection on a view-only PDF document: its key, the page and page-relative box (frac), the PDF's path from
    the manuscript root and file name, the region's printed text as a quote and its length, and the page directory.
    blank: the region has no printed text (a figure or scan); redrawing: the pages are being redrawn now."""

    doc: str
    page: int
    frac: list[float]
    pdf: str
    name: str
    quote: str
    n_chars: int
    blank: bool
    redrawing: bool
    pdf_build: str


@dataclass(frozen=True)
class GeneratedFile:
    """SyncTeX points into a generated file (a .bbl or .bib, by its suffix): the fix belongs in the .bib or the text."""

    suffix: str


@dataclass(frozen=True)
class SynctexOutside:
    """SyncTeX points at a file that is not in the manuscript tree (path as mapped back from the build copy)."""

    path: Path


@dataclass(frozen=True)
class SourceUnreadable:
    """The source file the selection lands in has no readable UTF-8 lines."""

    path: Path


@dataclass(frozen=True)
class NoSourceHere:
    """Neither SyncTeX nor the region's text leads to a line of the file."""


# Why a selection is not traced to manuscript lines; each is answered with its own 200 {"error", "reason"} body
# (limn.web.errors.PICK_REFUSALS).
PickRefusal: TypeAlias = GeneratedFile | SynctexOutside | SourceUnreadable | NoSourceHere


def pick(D: Doc, request: Selection, ctx: PickContext) -> Picked | PickedRegion | PickRefusal:
    """Dragged region -> source line range + range ladder, for document D and a selection parsed by
    limn.web.parse.parse_pick: a view-only document's region (PickedRegion), the traced range (Picked), or why the
    region cannot be traced to a manuscript line (PickRefusal).

    This is the shell: it runs pdftotext and SyncTeX on the build's PDF, maps SyncTeX's file back to the checkout,
    reads the file and weighs the region's tokens, then lets limn.mapping.trace_range choose between the two paths.
    The build facts (a manuscript newer than the PDF, a running LaTeX build) and the overlaps are read after that.

    The page directory is the build on screen at drag time (pdf_build, META.pages_build). A drag made after a rebuild
    finishes but before the viewer switches pages uses coordinates from the old layout, so it's traced back
    against that build's PDF and returned as pdf_build in the response - the viewer carries that value
    through unchanged when saving the pin (/api/pin) to record "which build's coordinates these are" (§Position estimation)."""
    pdir, page, (x0, y0, x1, y1), (pw, ph), frac = request.pdir, request.page, request.box, request.size, request.frac
    pdf = build.cur_pdf(D, pdir)
    rtext = region_text(pdf, page, x0, y0, x1, y1)
    if D.is_pdf:
        return _pick_region(D, pdir, page, (x0, y0, x1, y1), (pw, ph), frac, rtext)
    sy = by_synctex(pdf, page, x0, y0, x1, y1)

    src = to_source(D, sy[0]) if sy else D.main
    if src.suffix in (".bbl", ".bib"):
        return GeneratedFile(src.suffix)
    found = file_in_tree(str(src), ctx.root)
    if not isinstance(found, Path):
        return SynctexOutside(src)
    lines = tex_lines(found)
    if not lines:
        return SourceUnreadable(found)
    tw = ctx.tokens.weights(rtext, lines, file_key(found))
    traced = trace_range(tw, lines, (sy[1], sy[2]) if sy else None, ctx.envs)
    if traced is None:
        return NoSourceHere()

    stale = build.source_newer(D, ctx.state, pdir.name) > 2
    bstate = build.state_snapshot(D)
    return Picked(
        file=found,
        page=page,
        traced=traced,
        n_lines=len(lines),
        snippet=snippet(lines, traced.lo, traced.hi),
        frac=frac,
        quote=truncate_quote(norm(rtext), 60),
        overlaps=ctx.overlaps(str(found), traced.lo, traced.hi),
        pdf_build=pdir.name,
        stale=stale,
        building=bstate["state"] == "running" and bstate["phase"] == "latex",
    )


def _pick_region(
    D: Doc,
    pdir: Path,
    page: int,
    box: tuple[float, float, float, float],
    size: tuple[float, float],
    frac: list[float] | None,
    rtext: str,
) -> PickedRegion:
    """pick for a view-only document - only page/region and the region's text (pdftotext), no SyncTeX.
    If frac wasn't sent (agent curl), it's built from the coordinates - for a view-only pin, the region is the whole location."""
    x0, y0, x1, y1 = box
    pw, ph = size
    if frac is None:
        frac = [x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph]
    text = norm(rtext)
    bstate = build.state_snapshot(D)
    return PickedRegion(
        doc=D.key,
        page=page,
        frac=frac,
        pdf=D.rel_path(),
        name=D.main.name,
        quote=truncate_quote(text, PDF_QUOTE_MAX),
        n_chars=len(text),
        blank=not text,
        redrawing=bstate["state"] == "running",
        pdf_build=pdir.name,
    )


def overlaps_api(rng: SourceLines, ctx: PickContext) -> dict[str, Any]:
    """GET /api/overlaps - asks about a not-yet-saved selection's overlap using only file/range (kept for
    agent/legacy-viewer compatibility): {"overlaps": [...]}, the stored open pins' relationships as ctx.overlaps finds
    them.

    The current viewer instead recomputes the same rule (overlapsFor) locally against its own PINS on every
    range change, with no round trip - because pressing [Save Pin] while a response is still in flight could
    otherwise save a duplicate with no banner shown. rng is the range parsed by limn.web.parse.parse_source_range."""
    return {"overlaps": ctx.overlaps(str(rng.file), rng.lo, rng.hi)}


def snippet_api(rng: SourceLines, levels: bool, envs: Sequence[str]) -> dict[str, Any]:
    """GET /api/snippet: the source lines lo..hi of a manuscript file (a range parsed by limn.web.parse.parse_snippet),
    and with levels the range ladder around them for the float environments envs."""
    f, lines, lo, hi = rng.file, rng.lines, rng.lo, rng.hi
    out: dict[str, Any] = {
        "file": str(f),
        "name": f.name,
        "lo": lo,
        "hi": hi,
        "n": hi - lo + 1,
        "n_lines": len(lines),
        "snippet": snippet(lines, lo, hi),
    }
    if levels:
        lad = compute_levels(lines, lo, hi, envs)
        out["levels"] = lad["levels"]
        out["default_level"] = lad["default_level"]
    return out
