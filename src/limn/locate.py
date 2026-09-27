"""Shared pin file location, anchor re-sync, overlap and build estimation (docs/handbook/domain.md).

The PDF drag's SyncTeX/text resolution lives in features/pins/location. This module locates stored pin files under
the current manuscript tree, resynchronizes their anchors, and computes overlaps and build estimates for pin views.
The document, tree, state folder and stored pins arrive as arguments; this module does not read server globals.
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol, TypeAlias

from limn import build
from limn.documents import Doc
from limn.files import tex_lines, tree_part
from limn.mapping import (
    norm,
    pin_rel_path,
)
from limn.pins import position
from limn.pins.model import DonePin, LineSpan, OpenPin, Pin, PinCore, ReviewPin
from limn.pins.position import EstContext, epoch, est_basis, resync

# One stored pin as the store reads it: a JSON object (limn.store.Row).
Row: TypeAlias = dict[str, Any]

# ---------------------------------------------------------------- Where a pin's file is now (ADR-0006)


class PinLocation(NamedTuple):
    """Where a line pin's file is on this machine now (pin_location, docs/adr/0006-relative-pin-paths.md)."""

    rel: str  # POSIX path relative to the manuscript root (--manuscript)
    path: Path  # root / rel - the absolute path the API returns as `file`


# Where a stored pin's file is now, as the composition root binds pin_file to its root and the pin's document.
Locator: TypeAlias = Callable[[Pin], PinLocation | None]


class BuildRoot(Protocol):
    """A document as doc_scope reads it: only its build root. limn.documents.Doc is one, and so is the revision
    services' document (limn.revisions.RevisionDoc), whose recorded paths the composition root locates too."""

    @property
    def src(self) -> Path:
        """The build root - the folder a build copies."""
        ...


def _within(p: Path, root: Path, state: Path) -> bool:
    """Does p, symlinks resolved, belong to the tree root (limn.files.tree_part: inside root, under no dot-named part
    such as .git and not in the state folder `state`)? False when a path cannot be resolved."""
    return tree_part(p, root, state) is not None


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


def locate_file(file: object, file_rel: object, root: Path, state: Path, doc: BuildRoot | None) -> PinLocation | None:
    """Where a stored absolute path is under the manuscript root on this machine now, by the one rule of ADR-0006
    (pin_rel_path) - a pin's own `file` (with its file_rel) or a path in its `changes` (none), the tail guess searched
    in the folder of doc (doc_scope). None for a missing path or one the rule cannot place inside root.

    Only file metadata is read (resolve, is_file) - under root, apart from resolving the stored path itself as 0.3.0's
    in_tree() did - and never file contents: a line read from outside the tree would leak into the anchor and out
    through GET /api/pins. The result is checked once more after resolving symlinks against the tree rule
    (limn.files.tree_part), so a link inside the tree cannot lead outside, and a path under a dot-named part (.git,
    .env) or in the state folder `state` is never located - a pin recorded there before that rule is outside the tree
    (a tail through such a link or part is skipped for the next one)."""
    if not isinstance(file, str) or not file:
        return None
    try:
        under: str | None = Path(file).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        under = None
    scope = doc_scope(doc, root) if under is None else ""  # only a moved record needs its document folder
    rel = pin_rel_path(file, file_rel, under, lambda t: (root / t).is_file() and _within(root / t, root, state), scope)
    if rel is None:
        return None
    path = root / rel
    return PinLocation(rel, path) if _within(path, root, state) else None


def pin_location(r: Mapping[str, Any], root: Path, state: Path, doc: Doc | None) -> PinLocation | None:
    """Where the file of r - a record, or the location fields of one (file, file_rel) - is under the manuscript root
    on this machine now (locate_file, the tail guess limited to the folder of doc - the pin's own document, None when
    it is no longer configured), or None: no file (a view-only PDF pin), or a file the rule cannot place inside the
    tree (root minus the state folder `state`). A stored pin is located by pin_file."""
    return locate_file(r.get("file"), r.get("file_rel"), root, state, doc)


def pin_file(pin: Pin, root: Path, state: Path, doc: Doc | None) -> PinLocation | None:
    """Where a stored line pin's file is under the manuscript root on this machine now: its LineSpan's file and its
    file_rel by locate_file, as pin_location reads them off the record. None for a pin placed on a region (it has no
    file) or a file the rule cannot place inside the tree."""
    span = pin.core.place
    return locate_file(span.file if isinstance(span, LineSpan) else None, pin.core.file_rel, root, state, doc)


def stamp_location(r: Row, root: Path, state: Path, doc: Doc | None) -> PinLocation | None:
    """Records where line pin r's file is now (ADR-0006 §1): `file` becomes the current absolute path and `file_rel` the
    path relative to root. Only for a write to this very pin (create, edit, restore) - other writes keep the stored
    record, so there is no write migration. A pin that cannot be located, or a view-only PDF pin, is left as it is.
    Mutates r and returns its location (or None)."""
    loc = pin_location(r, root, state, doc)
    if loc is not None:
        r["file"], r["file_rel"] = str(loc.path), loc.rel
    return loc


def located_file(pin: Pin, locate: Locator) -> str:
    """The file an open line pin is counted in for overlaps: where locate places it now, else its stored `file` - so
    pins made before and after a move of the checkout are one file."""
    loc = locate(pin)
    if loc is not None:
        return str(loc.path)
    span = pin.core.place
    return str(span.file if isinstance(span, LineSpan) else None)


# ---------------------------------------------------------------- Overlap - a computed field, never stored
#
# The rule is limn.pins.position's (overlaps_by_id, selection_rel, overlaps_for_range); here each pin is counted in
# the file locate finds for it now (located_file), so a moved checkout's old and new pins overlap as one file.


def overlaps_by_id(pins: Sequence[Pin], locate: Locator) -> dict[int, list[dict[str, Any]]]:
    """The relationship of every pair of open line pins on the same file, as locate places each pin's file now
    (limn.pins.position.overlaps_by_id): {id: [{"id", "rel"}, ...]} with an entry for every open pin. Never stored."""
    return position.overlaps_by_id(pins, lambda pin: located_file(pin, locate))


def overlaps_for_range(file: str, lo: int, hi: int, pins: Sequence[Pin], locate: Locator) -> list[dict[str, Any]]:
    """The overlap relationships between a not-yet-saved range lo..hi of file and the open line pins that locate
    places in that file now (limn.pins.position.overlaps_for_range): [{"id", "lo", "hi", "rel"}] in the pins' order.
    Nothing is saved."""
    return position.overlaps_for_range(file, lo, hi, pins, lambda pin: located_file(pin, locate))


# ---------------------------------------------------------------- Anchors and re-syncing


def sync_all(pins: list[Pin], locate: Locator) -> bool:
    """If the manuscript is newer than a pin, re-match its line numbers via the anchor (limn.pins.position.resync).
    A re-matched pin replaces its old state in pins; returns whether any pin changed. The pin store calls this under
    its lock before every transaction (limn.store.PinStore.sync).

    Open line pins only (a view-only PDF's pin has no lines). The pin's file is the one locate finds (ADR-0006: a moved
    checkout is followed; outside the tree is never read); a pin whose file cannot be located or is not a file now is
    left alone. Each file is read once per call."""
    changed = False
    cache: dict[Path, tuple[list[str], list[str], float]] = {}
    for i, pin in enumerate(pins):
        match pin:
            case OpenPin(core=PinCore(place=LineSpan() as span)):
                pass
            case OpenPin() | ReviewPin() | DonePin():  # closed, or a view-only PDF's pin: no lines to re-match
                continue
        loc = locate(pin)
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
        new = resync(pin, span, lines, nlines, mtime, str(f))
        if new is not None:
            pins[i] = new
            changed = True
    return changed


# ---------------------------------------------------------------- Location estimation (.est)


def est_context(D: Doc) -> EstContext:
    """What estimation needs to know about document D's builds (limn.pins.position.est_basis), its history read once."""
    h = build.load_builds(D)
    cur = build.cur_pages(D).name
    return est_basis(cur, h["by"], build.read_built_src_mtime(D), epoch(build.read_built_at(D)))
