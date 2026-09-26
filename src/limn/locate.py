"""Where a selection and a stored pin are in the manuscript on this machine now - the effectful half of the position
rules (docs/handbook/domain.md).

This module reads what the rules need: the .tex files, where a pin's file is under a moved checkout (ADR-0006), the
build history, SyncTeX and pdftotext for a dragged region. The rules themselves are pure - the range ladder, scores
and anchors in limn.mapping, estimation, overlap and anchor re-sync in limn.pins.position - and are called from here.

Everything the instance decides comes in as an argument: the document (limn.documents.Doc), the manuscript root, the
float environments, the state folder, the token-weight cache and the store's pins (PickContext). Nothing here reads
the server's run settings or imports the server (coding rule R5); the composition root (server.py) binds these.
"""
from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Protocol, TypeAlias

from limn import build
from limn.documents import Doc
from limn.files import file_in_tree
from limn.mapping import (
    TokenWeights, by_text, compute_levels, densest, norm, pin_rel_path, score_range, snippet, truncate_quote,
)
from limn.pins.edit import PDF_QUOTE_MAX
from limn.pins.position import EstContext, epoch, est_basis, resync

# One stored pin as the store reads it: a JSON object (limn.store.Row).
Row: TypeAlias = dict[str, Any]
# A word token worth weighting: a Hangul word of 2+ syllables, a Latin word of 4+ letters, or a decimal number.
TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{4,}|\d+\.\d+")


# ---------------------------------------------------------------- Source-text access

def tex_lines(path: Path) -> list[str]:
    """The lines of a manuscript file as pins number them (str.splitlines), or [] when it cannot be read as UTF-8."""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def to_source(D: Doc, path: str) -> Path:
    """Maps a path in document D's build copy (as SyncTeX reports it) back to the original checkout path."""
    p = Path(path)
    for base in (D.build, D.build.resolve()):
        try:
            return D.src / p.relative_to(base)
        except ValueError:
            pass
    try:
        return D.src / p.resolve().relative_to(D.build.resolve())
    except (ValueError, OSError):
        pass
    # If the state directory was moved or cloned, synctex points at the old build path. If the path's tail
    # matches a real file inside the manuscript tree, fall back to that (longest tail wins; never reads outside the tree).
    parts = p.parts
    for k in range(1, len(parts)):
        cand = D.src.joinpath(*parts[k:])
        if cand.is_file():
            return cand
    return p


# ---------------------------------------------------------------- Reverse mapping 1: SyncTeX

def synctex_edit(pdf: Path, page: int, x: float, y: float) -> tuple[str, int] | None:
    """The (input file, line) SyncTeX gives for one point of a page (in points), or None when it gives none, is
    missing or times out (10 s)."""
    try:
        out = subprocess.run(["synctex", "edit", "-o", "%d:%.2f:%.2f:%s" % (page, x, y, pdf)],
                             capture_output=True, text=True, timeout=10, check=False).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    inp = line = None
    for ln in out.splitlines():
        if ln.startswith("Input:"):
            inp = ln[6:].strip()
        elif ln.startswith("Line:"):
            try:
                line = int(ln[5:].strip())
            except ValueError:
                pass
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
            ["pdftotext", "-f", str(page), "-l", str(page), "-r", "72",
             "-x", str(int(x0)), "-y", str(int(y0)),
             "-W", str(max(1, int(x1 - x0))), "-H", str(max(1, int(y1 - y0))), str(pdf), "-"],
            capture_output=True, text=True, timeout=15, check=False).stdout
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
            if freq > n * 0.05:            # a word scattered across the whole manuscript can't pin down a location
                continue
            out.append((t, 1.0 / (1.0 + freq)))
        return out


# ---------------------------------------------------------------- Where a pin's file is now (ADR-0006)

class PinLocation(NamedTuple):
    """Where a line pin's file is on this machine now (pin_location, docs/adr/0006-relative-pin-paths.md)."""
    rel: str                 # POSIX path relative to the manuscript root (--manuscript)
    path: Path               # root / rel - the absolute path the API returns as `file`


# Where a stored pin's file is now, as the composition root binds pin_location to its root and documents.
Locator: TypeAlias = Callable[[Row], PinLocation | None]


def _within(p: Path, root: Path) -> bool:
    """Does p, symlinks resolved, lie inside root (also resolved)? False when either cannot be resolved."""
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def doc_scope(D: Doc | None, root: Path) -> str:
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


def locate_file(file: object, file_rel: object, root: Path, doc: Doc | None) -> PinLocation | None:
    """Where a stored absolute path is under the manuscript root on this machine now, by the one rule of ADR-0006
    (pin_rel_path) - a pin's own `file` (with its file_rel) or a path in its `changes` (none), the tail guess searched
    in the folder of doc (doc_scope). None for a missing path or one the rule cannot place inside root.

    Only file metadata is read (resolve, is_file) - under root, apart from resolving the stored path itself as 0.3.0's
    in_tree() did - and never file contents: a line read from outside the tree would leak into the anchor and out
    through GET /api/pins. The result is checked once more after resolving symlinks, so a link inside the tree cannot
    lead outside (a tail through such a link is skipped for the next one)."""
    if not isinstance(file, str) or not file:
        return None
    try:
        under: str | None = Path(file).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        under = None
    scope = doc_scope(doc, root) if under is None else ""         # only a moved record needs its document folder
    rel = pin_rel_path(file, file_rel, under, lambda t: (root / t).is_file() and _within(root / t, root), scope)
    if rel is None:
        return None
    path = root / rel
    return PinLocation(rel, path) if _within(path, root) else None


def pin_location(r: Row, root: Path, doc: Doc | None) -> PinLocation | None:
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
        if r.get("done") or not r.get("file"):         # a view-only PDF's pin has no lines - nothing to re-match
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


def pick(D: Doc, request: Selection, ctx: PickContext) -> dict[str, Any]:
    """Dragged region -> source line range + range ladder, for document D and a selection parsed by
    limn.web.parse.parse_pick. The answer is always a 200 body: the resolved range, or {"error", "reason"} when the
    region cannot be traced to a manuscript line.

    Pits the SyncTeX candidate and the text candidate against each other on equal footing. Treating either
    as a conditional fallback leaves no way to catch SyncTeX being silently wrong (inside minipage/tabular).

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
        return {"error": "여기는 생성 파일(%s)입니다. 참고문헌은 .bib 나 본문 \\cite 를 고쳐야 합니다."
                         % src.suffix, "reason": "generated_file"}
    found = file_in_tree(str(src), ctx.root)
    if not isinstance(found, Path):
        return {"error": "SyncTeX 가 원고 밖 파일을 가리킵니다(%s). PDF 재빌드 뒤 다시 골라 보세요." % src,
                "reason": "synctex_outside"}
    src = found

    lines = tex_lines(src)
    if not lines:
        return {"error": "원문 파일을 읽지 못했습니다: %s" % src, "reason": "source_unreadable"}
    tw = ctx.tokens.weights(rtext, lines, file_key(src))

    cands = []
    if sy:
        cands.append(("synctex", sy[1], sy[2], score_range(tw, lines, sy[1], sy[2])))
    alt = by_text(tw, lines, sy[1] if sy else None)
    if alt:
        cands.append(("text", alt[0], alt[1], alt[2]))
    if not cands:
        return {"error": "그 자리에서 원문을 되짚지 못했습니다. 글자가 있는 쪽으로 조금 넓게 잡아 보세요.",
                "reason": "no_source_here"}

    # On a tie, SyncTeX wins - it's the only one that's right in a region with no text (a figure).
    cands.sort(key=lambda c: (-c[3], c[0] != "synctex"))
    via, raw_lo, raw_hi, best = cands[0]
    warn = ""
    if tw and best < 0.3:
        warn = "이 영역은 원문 대조가 약합니다(%.0f%%). 줄 범위를 눈으로 확인하세요." % (best * 100)

    lad = compute_levels(lines, raw_lo, raw_hi, ctx.envs)
    lo, hi = lad["lo"], lad["hi"]
    if not warn and len(cands) == 2 and abs(cands[0][3] - cands[1][3]) < 0.12:
        # If both expand into the same block, the two paths haven't actually diverged - don't warn.
        if not (lo <= cands[1][1] <= hi):
            warn = "두 경로가 다른 곳을 가리킵니다(L%d / L%d). 확인이 필요합니다." % (cands[0][1], cands[1][1])

    if build.source_newer(D, ctx.state, pdir.name) > 2:
        stale_note = "화면의 PDF 가 지금 원고보다 낡았습니다 — [PDF 재빌드] 뒤에 다시 고르세요."
        warn = stale_note + (" " + warn if warn else "")
    bstate = build.state_snapshot(D)
    if bstate["state"] == "running" and bstate["phase"] == "latex":
        warn = (warn + " " if warn else "") + "빌드 중이라 결과가 흔들릴 수 있습니다."

    quote = truncate_quote(norm(rtext), 60)
    return {"file": str(src), "name": src.name, "page": page, "lo": lo, "hi": hi,
            "raw_lo": raw_lo, "raw_hi": raw_hi, "kind": lad["kind"], "via": via,
            "score": round(best, 2), "warn": warn, "n_lines": len(lines),
            "snippet": snippet(lines, lo, hi), "frac": frac, "quote": quote,
            "levels": lad["levels"], "default_level": lad["default_level"],
            "overlaps": ctx.overlaps(str(src), lo, hi), "pdf_build": pdir.name}


def _pick_region(D: Doc, pdir: Path, page: int, box: tuple[float, float, float, float], size: tuple[float, float],
                 frac: list[float] | None, rtext: str) -> dict[str, Any]:
    """pick for a view-only document - returns only page/region and the region's text (pdftotext), no SyncTeX.
    If frac wasn't sent (agent curl), it's built from the coordinates - for a view-only pin, the region is the whole location."""
    x0, y0, x1, y1 = box
    pw, ph = size
    if frac is None:
        frac = [x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph]
    text = norm(rtext)
    warn = ""
    if not text:
        warn = "이 영역에는 글자가 없습니다(그림·스캔본). 메모에 무엇을 가리키는지 적어 주세요."
    bstate = build.state_snapshot(D)
    if bstate["state"] == "running":
        warn = (warn + " " if warn else "") + "PDF 가 바뀌어 쪽을 다시 그리는 중입니다 — 끝나면 다시 고르세요."
    return {"doc": D.key, "kind": "region", "view_only": True, "page": page, "frac": frac,
            "pdf": D.rel_path(), "name": D.main.name, "quote": truncate_quote(text, PDF_QUOTE_MAX),
            "n_chars": len(text), "warn": warn, "overlaps": [], "pdf_build": pdir.name}


def snippet_api(rng: SourceLines, levels: bool, envs: Sequence[str]) -> dict[str, Any]:
    """GET /api/snippet: the source lines lo..hi of a manuscript file (a range parsed by limn.web.parse.parse_snippet),
    and with levels the range ladder around them for the float environments envs."""
    f, lines, lo, hi = rng.file, rng.lines, rng.lo, rng.hi
    out: dict[str, Any] = {"file": str(f), "name": f.name, "lo": lo, "hi": hi, "n": hi - lo + 1,
                           "n_lines": len(lines), "snippet": snippet(lines, lo, hi)}
    if levels:
        lad = compute_levels(lines, lo, hi, envs)
        out["levels"] = lad["levels"]
        out["default_level"] = lad["default_level"]
    return out
