"""The import build of a figure document: its element map and the PDF the map names become a page directory.

A figure repository renders a PDF and writes an element map (limn.figmap); Limn never runs its code. The watch looks
at the two files and imports them only when the map describes exactly that PDF (pdf_sha256). The pages are then
rendered from the bytes that were checked, through the same tracked build a view-only PDF uses (run_tracked), and the
map is published next to the PDF copy in the new page directory, so a drag on an older build is traced with that
build's map (limn.build.load_build_map). Files that do not agree yet are left alone - no build, no failure - and
looked at again when either changes. The watch and its signature file are the view-only PDF's
(docs/handbook/build-sync.md §보기 전용 PDF 문서).

The decisions (import_due, accept_pdf, figure_src_hash) take values. The readers, the log line and the render at the
edge take the document and the build settings as arguments and read no server global (coding rules R1, R5).
"""

import contextlib
import hashlib
import os
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

from limn import build
from limn.build import BuildAborted, BuildConfig, BuildDoc, BuildFailed, BuildOk, PagesNotRendered
from limn.features.builds import engine
from limn.figmap import MAP_MAX_BYTES, FigureMap, MapRejected, parse_map
from limn.files import atomic_write

SIG_FILE = "pdf_sig.txt"  # the watch's signature file, shared with view-only PDFs (engine.render_pdf_doc)
STAGE_DIR = "figure-import"  # private staging folder in the document's state folder; never a page directory name
NO_FILE = "-"  # the PDF half of a signature when there is no PDF to look at
# The most a figure's PDF is ever read into memory, capped like its map (limn.figmap.MAP_MAX_BYTES): the map names
# the file, so any non-dot file in the folder could otherwise be read whole before its hash is even checked. Read at
# most PDF_MAX_BYTES + 1 bytes (read_figure_import); a PDF over the cap is deferred pdf_too_large, never hashed.
PDF_MAX_BYTES = 64 * 1024 * 1024

DeferReason: TypeAlias = Literal[
    "map_missing", "map_rejected", "pdf_outside", "pdf_missing", "pdf_too_large", "pdf_mismatch"
]


@dataclass(frozen=True)
class FileRead:
    """One read of a file: its bytes and "<mtime_ns>:<size>" taken from the same open descriptor, so both describe the
    same version even while a producer replaces the file."""

    raw: bytes
    signature: str


@dataclass(frozen=True)
class FigureImport:
    """A figure document's map and PDF read together and verified: the map's bytes and parse, the PDF's bytes (their
    SHA-256 is the map's pdf_sha256), and the watch signature of the two files as read."""

    map_raw: bytes
    figure_map: FigureMap
    pdf_raw: bytes
    signature: str


@dataclass(frozen=True)
class ImportDeferred:
    """Why a figure document's files are not imported now, a detail for the log, and the watch signature of what was
    seen - None when the map could not be read. The watch settles that signature, so only a change is looked at."""

    reason: DeferReason
    detail: str
    signature: str | None


@dataclass
class MapLooks:
    """What the watch last learned from each figure document's map, keyed by the map's path: the map's signature and
    its parsed map (None when the map is rejected). Only the map itself is memoised - the PDF it names is resolved
    fresh (build.figure_pdf) on every tick, even when the map is unchanged, because it can name a symlink inside the
    folder: the same map can be made to point at a different target, or start pointing at one that did not exist
    before, without the map's own bytes (and so its signature) ever changing. Caching the once-resolved path would
    miss both. One per run (features.builds.service.BuildRequests): a tick stats the map and reads it again only when
    its signature changed. Startup and the watch thread never look at one document at the same time; a lost update
    would only cost one extra read."""

    seen: dict[str, tuple[str, FigureMap | None]] = field(default_factory=dict)


def stat_signature(st: os.stat_result) -> str:
    """ "<mtime_ns>:<size>" of a stat result, the view-only PDF's signature format (engine.pdf_signature)."""
    return "%d:%d" % (st.st_mtime_ns, st.st_size)


def _file_signature(path: Path | None) -> str:
    """The signature of the regular file at path, not following a symlink in its last part; NO_FILE when there is no
    path or no such regular file."""
    if path is None:
        return NO_FILE
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return NO_FILE
    return stat_signature(st) if stat.S_ISREG(st.st_mode) else NO_FILE


def _read_file(path: Path, limit: int | None) -> FileRead | None:
    """One read of the regular file at path, not following a symlink in its last part: all its bytes, or at most
    limit + 1 when limit is given (the caller refuses an oversized file without holding it), and the signature from the
    same descriptor. None when it is missing, a symlink, not a regular file, or unreadable. Opened non-blocking, so a
    FIFO in its place cannot stall the watch."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as fh:
            raw = fh.read() if limit is None else fh.read(limit + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    return FileRead(raw, stat_signature(st))


def _parsed_map(D: BuildDoc, raw: bytes) -> FigureMap | None:
    """D's map bytes raw, parsed with D's own source check (limn.figmap.parse_map): the map when it is one, else None
    when it is rejected. Does not resolve the PDF the map names - watch_signature does that itself, every time, since
    the target can change (a repointed symlink) without these bytes changing."""
    parsed = parse_map(raw, source_inside=build.figure_source_check(D.src))
    return parsed if isinstance(parsed, FigureMap) else None


def watch_signature(D: BuildDoc, looks: MapLooks) -> str | None:
    """ "<map mtime_ns>:<map size>|<pdf mtime_ns>:<pdf size>" of figure document D now, or None when its map is missing
    (or not a regular file). The PDF half is NO_FILE when the map is rejected, names a PDF outside D's folder, or that
    PDF is missing. The map is read again only when its own signature differs from the one looks remembers for it, but
    the PDF path is resolved from the (possibly memoised) parsed map on every call (build.figure_pdf) rather than
    memoised itself - the map may name a symlink inside the folder, and it can be repointed, or start existing, without
    the map's own signature moving; only a fresh resolve sees that."""
    key = str(D.main)
    map_sig = _file_signature(D.main)
    if map_sig == NO_FILE:
        return None
    known = looks.seen.get(key)
    if known is not None and known[0] == map_sig:
        fm = known[1]
    else:
        got = _read_file(D.main, MAP_MAX_BYTES)
        if got is None:
            return None
        map_sig, fm = got.signature, _parsed_map(D, got.raw)
        looks.seen[key] = (map_sig, fm)
    pdf = build.figure_pdf(D, fm) if fm is not None else None
    return map_sig + "|" + _file_signature(pdf)


def import_due(now: str | None, settled: str | None, missing_pages: bool) -> bool:
    """Whether figure files must be read and checked: never without a map (now is None); when their signature differs
    from the one last settled; and when nothing changed but the document has no page images at startup
    (missing_pages)."""
    return now is not None and (now != settled or missing_pages)


def accept_pdf(map_read: FileRead, figure_map: FigureMap, pdf_read: FileRead) -> FigureImport | ImportDeferred:
    """The pair as read: a FigureImport when the SHA-256 of the PDF bytes is figure_map.pdf_sha256, else pdf_mismatch -
    the producer has written one file and not yet the other. Either way the signature is the map's and the PDF's."""
    signature = map_read.signature + "|" + pdf_read.signature
    if hashlib.sha256(pdf_read.raw).hexdigest() != figure_map.pdf_sha256:
        return ImportDeferred("pdf_mismatch", figure_map.pdf, signature)
    return FigureImport(map_read.raw, figure_map, pdf_read.raw, signature)


def read_figure_import(D: BuildDoc) -> FigureImport | ImportDeferred:
    """Read figure document D's map and the PDF it names once each, and check them in this order: the map is a
    readable regular file (map_missing); it parses with D's source check (map_rejected: the parser's reason and
    detail); it names a PDF inside D.src (pdf_outside); that PDF is a readable regular file (pdf_missing); it is at
    most PDF_MAX_BYTES (pdf_too_large - the map chooses the file, so it is never read whole before this check: at most
    PDF_MAX_BYTES + 1 bytes are read); its SHA-256 is the map's pdf_sha256 (pdf_mismatch, accept_pdf). Every deferral
    but map_missing carries the signature of what was read: NO_FILE for a PDF that was not read, else the PDF's own -
    including pdf_too_large, whose signature is real (from the same read) so an unchanged oversized file is not
    re-read on the next tick."""
    got = _read_file(D.main, MAP_MAX_BYTES)
    if got is None:
        return ImportDeferred("map_missing", str(D.main), None)
    no_pdf = got.signature + "|" + NO_FILE
    parsed = parse_map(got.raw, source_inside=build.figure_source_check(D.src))
    if isinstance(parsed, MapRejected):
        return ImportDeferred("map_rejected", "%s: %s" % (parsed.reason, parsed.detail), no_pdf)
    pdf = build.figure_pdf(D, parsed)
    if pdf is None:
        return ImportDeferred("pdf_outside", parsed.pdf, no_pdf)
    pdf_read = _read_file(pdf, PDF_MAX_BYTES)
    if pdf_read is None:
        return ImportDeferred("pdf_missing", str(pdf), no_pdf)
    if len(pdf_read.raw) > PDF_MAX_BYTES:
        return ImportDeferred(
            "pdf_too_large",
            "%d bytes > %d" % (len(pdf_read.raw), PDF_MAX_BYTES),
            got.signature + "|" + pdf_read.signature,
        )
    return accept_pdf(got, parsed, pdf_read)


def settled_signature(D: BuildDoc) -> str | None:
    """The signature the watch last settled for D (SIG_FILE in D's state folder), or None before any."""
    try:
        return (D.dir / SIG_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def settle(D: BuildDoc, signature: str) -> None:
    """Record signature as settled for D - after a render, a failed render or a deferral - so the watch looks again
    only when a file changes. A failed write is ignored: the next tick then looks again."""
    with contextlib.suppress(OSError):
        D.dir.mkdir(parents=True, exist_ok=True)
        atomic_write(D.dir / SIG_FILE, signature)


def pending_import(D: BuildDoc, looks: MapLooks, dpi: int, *, first: bool) -> FigureImport | None:
    """The verified pair figure document D should import now, or None. first is startup: D is then also imported when
    its files did not change but it has no page images at dpi. None when the map is missing, when nothing changed since
    the settled signature, or when the files do not agree - then the deferral's signature is settled and one line
    naming the reason goes to stderr, so no build and no failure is recorded and the next change is looked at."""
    now = watch_signature(D, looks)
    missing_pages = first and not build.page_list(build.cur_pages(D), dpi)
    if not import_due(now, settled_signature(D), missing_pages):
        return None
    found = read_figure_import(D)
    if isinstance(found, FigureImport):
        return found
    if found.signature is not None:
        settle(D, found.signature)
        print(
            "figure %s: not imported (%s: %s) - waiting for the next change" % (D.main, found.reason, found.detail),
            file=sys.stderr,
        )
    return None


def figure_src_hash(pdf_raw: bytes, map_raw: bytes) -> str:
    """The build fingerprint of an imported pair: SHA-256 over the SHA-256 digest of the PDF bytes followed by that of
    the map bytes, cut to 32 hex digits like every build fingerprint (limn.build.doc_fingerprint). A change to either
    file changes it, so pins made on the previous build are drawn as estimates (est)."""
    pair = hashlib.sha256(pdf_raw).digest() + hashlib.sha256(map_raw).digest()
    return hashlib.sha256(pair).hexdigest()[:32]


def render_figure_doc(D: BuildDoc, cfg: BuildConfig, ready: FigureImport) -> BuildOk | BuildFailed:
    """The 'build' of figure document D from a verified pair, the figure counterpart of engine.render_pdf_doc. The PDF
    and map bytes are staged in D's state folder (STAGE_DIR), the pages are rendered from the staged PDF at cfg.dpi
    (engine.render_pages), and the new page directory holds the PDF copy (D.pdf_name) and the map copy
    (limn.build.FIGMAP_NAME); then pages.cur moves to it (engine.commit_pages). The signature is settled after the
    commit, or after a failed render, so a pair that cannot be rendered is retried only when a file changes. src_hash
    is figure_src_hash of the pair. A staging failure is BuildFailed pdf_copy; the staging folder never survives."""
    t0 = time.time()
    src_hash = figure_src_hash(ready.pdf_raw, ready.map_raw)
    stage = D.dir / STAGE_DIR
    shutil.rmtree(stage, ignore_errors=True)
    newdir: Path | PagesNotRendered
    try:
        stage.mkdir(parents=True)
        (stage / D.pdf_name).write_bytes(ready.pdf_raw)
        (stage / build.FIGMAP_NAME).write_bytes(ready.map_raw)
        newdir = engine.render_pages(D, stage / D.pdf_name, [stage / build.FIGMAP_NAME], cfg.dpi)
    except OSError as e:
        newdir = PagesNotRendered("pdf_copy", str(e))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    if isinstance(newdir, PagesNotRendered):
        settle(D, ready.signature)
        return BuildFailed(newdir.kind, newdir.detail, None, [], round(time.time() - t0, 1), None, None, src_hash)
    head = engine.commit_pages(D, newdir)
    settle(D, ready.signature)
    pages = len(list(newdir.glob("page-*.png")))
    return BuildOk("", round(time.time() - t0, 1), None, None, src_hash, head, newdir.name, pages)


def import_now(D: BuildDoc, cfg: BuildConfig, ready: FigureImport | None) -> BuildOk | BuildFailed | BuildAborted:
    """The tracked build step of figure document D (features.builds.service.BuildRequests.build_step): render ready,
    the pair the watch or startup verified, or - when none was given - read and check D's files now and render them.
    Files that do not agree end as BuildAborted figure_unready naming the reason; nothing is settled, so the watch
    still looks at them."""
    found = ready if ready is not None else read_figure_import(D)
    if isinstance(found, ImportDeferred):
        return BuildAborted("figure_unready", "%s: %s" % (found.reason, found.detail))
    return render_figure_doc(D, cfg, found)
