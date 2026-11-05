"""Shared pin file location, anchor re-sync, overlap and build estimation (docs/handbook/domain.md).

The PDF drag's SyncTeX/text resolution lives in pins/location. This module locates stored pin files under
the current manuscript tree, resynchronizes their anchors, and computes overlaps and build estimates for pin views.
The document, tree, state folder and stored pins arrive as arguments; this module does not read server globals.
"""

import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, NamedTuple, Protocol, TypeAlias

from limn.pins.location import position
from limn.pins.location.mapping import norm, pin_rel_path
from limn.pins.location.position import EstContext, resync
from limn.pins.model import DonePin, LineSpan, OpenPin, Pin, PinCore, Record, ReviewPin
from limn.pins.needs import BuildAnswers
from limn.pins.pages import keep_pages
from limn.platform.files import PATH_MAX_CHARS, ManuscriptFile, file_in_tree, tree_part
from limn.runtime.documents import Doc

# One stored pin as the store reads it: a JSON object (limn.pins.store.Row).
Row: TypeAlias = dict[str, Any]

# Folders through which stored pin records were written, each with the folder it is in the coordinates the run
# registered (recorded_folders): learned once at startup, read-only for the run.
RecordedFolders: TypeAlias = Mapping[Path, Path]
NO_RECORDED_FOLDERS: RecordedFolders = MappingProxyType({})

# The most distinct folders recorded_folders resolves at startup. A manuscript's records name a few folders; the
# bound keeps a pins file with thousands of made-up folders from holding startup on the file system.
RECORDED_FOLDERS_MAX = 512

# ---------------------------------------------------------------- Where a pin's file is now (ADR-0006)


class PinLocation(NamedTuple):
    """Where a line pin's file is on this machine now (pin_location, docs/adr/0006-relative-pin-paths.md)."""

    rel: str  # POSIX path relative to the manuscript root (--manuscript)
    source: ManuscriptFile

    @property
    def path(self) -> Path:
        """Expose the checked name for API projection; content reads use source."""
        return self.source.path


# Where a stored pin's file is now, as the composition root binds pin_file to its root and the pin's document.
Locator: TypeAlias = Callable[[Pin], PinLocation | None]


class BuildRoot(Protocol):
    """A document as doc_scope reads it: only its build root. limn.runtime.documents.Doc is one, and so is the revision
    services' document (limn.revisions.core.RevisionDoc), whose recorded paths the composition root locates too."""

    @property
    def src(self) -> Path:
        """The build root - the folder a build copies."""
        ...


def _within(p: Path, root: Path, state: Path) -> bool:
    """Does p, symlinks resolved, belong to the tree root (limn.platform.files.tree_part: inside root, under no dot-named part
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
    (limn.platform.files.tree_part), so a link inside the tree cannot lead outside, and a path under a dot-named part (.git,
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
    source = file_in_tree(str(path), root, state)
    return PinLocation(rel, source) if isinstance(source, ManuscriptFile) else None


def recorded_root(file: object, file_rel: object) -> Path | None:
    """The manuscript root a pin record was written under, as the record itself says: its absolute `file` with its
    file_rel taken off the end - when file_rel is a non-empty relative path without '..' parts that `file` ends with
    and is shorter than, the check of rule 2 of ADR-0006 (limn.pins.location.mapping.pin_rel_path) - else None (a
    record written before 0.3.2 has no file_rel, and 0.3.1 relocating a pin left a stale one). Lexical ('..' parts of
    `file` folded): asks the filesystem nothing. Pure."""
    if not isinstance(file, str) or not isinstance(file_rel, str) or "\x00" in file or not os.path.isabs(file):
        return None
    if file_rel.startswith("/"):
        return None
    parts, rel = Path(os.path.normpath(file)).parts, Path(file_rel).parts
    n = len(rel)
    if not n or ".." in rel or len(parts) <= n + 1 or parts[-n:] != rel:
        return None
    return Path(*parts[:-n])


def recorded_place(
    file: object, record: Mapping[str, Any], root: Path, state: Path, folders: RecordedFolders = NO_RECORDED_FOLDERS
) -> Path | None:
    """Where a path pin record `record` stores - its own `file`, or a path in its `changes` - is in the coordinates the
    run registered, for the changes view: root is the manuscript root as startup resolved it (limn.server). The first
    rule that places the path wins.

    - A path lexically below root ('..' parts folded) is root / that part (rule 1 of ADR-0006).
    - Any other path - a record from a moved or cloned checkout - is placed by the record's own file_rel: its part
      below the root the record was written under (recorded_root) is that part below root. So the pin's file is
      root / file_rel, and a recorded change goes with it.
    - A path whose folder is in folders - one the record was written through, under another path to this manuscript,
      that startup translated once (recorded_folders) - is that folder's registered counterpart / its file name.
    - None for a path no rule places (a record without a usable file_rel whose folder startup did not translate, a
      change outside its record's root), for one with a dot-named part below root and for one in the state folder
      `state` (the tree rule, limn.platform.files.tree_part, judged on the path's own parts).

    Nothing here asks the manuscript tree anything (only `state` is resolved): the changes view's pin scope reads its
    files from Git (limn.revisions.core.revision_pin_scope), never from this path, so a folder replaced by a symlink
    after startup moves neither the pin nor its recorded ranges to another file, and a path is placed even when its
    file is gone, as the commit the pin was closed on still names it. folders is the startup's answer, never asked
    again. The tail guesses of locate_file, which read the tree as it is now, place a pin everywhere else (its
    listing, pins.md)."""
    stored = _stored(file)
    if stored is None:
        return None
    rel = _recorded_rel(stored, record, root)
    if rel is None and stored.name:
        known = folders.get(stored.parent)
        rel = None if known is None else _below(known / stored.name, root)
    if rel is None or not rel.parts or any(part.startswith(".") for part in rel.parts):
        return None
    placed = root / rel
    return None if _in_state(placed, root, state) else placed


def recorded_folders(records: Iterable[Mapping[str, Any]], root: Path, state: Path) -> RecordedFolders:
    """The folders the stored records were written through that lead into the manuscript under another path, each
    with its folder in the coordinates the run registered - the third rule of recorded_place, learned once at startup
    (limn.pins.application binds it) and immutable for the run.

    A record can name this manuscript by another path: its `file` or its `changes` written through a link to the
    folder, or by the old place of a checkout moved away with a link left there. Rules 1 and 2 of recorded_place cannot
    place such a path when the record has no file_rel (before 0.3.2) or its `changes` went through another path than
    its `file`. For each stored path they cannot place (a record's `file`, each `changes[].file`; absolute, at most
    PATH_MAX_CHARS characters), its folder is resolved once (os.path.realpath; an error skips it), at most
    RECORDED_FOLDERS_MAX distinct folders in all. A folder is kept only when it resolves lexically below root (resolved
    at startup), under no dot-named part below root and not in the state folder `state` - the checks recorded_place
    applies to a placed path, which it applies again to the path the folder places. The file name itself is not
    resolved: the commit the pin was closed on names the file, which may be gone.

    Resolving happens here and only here: a link swapped, made or removed after startup changes no placement until the
    next start, which learns its folders afresh from the records stored then. A record the server writes after
    startup is in the registered coordinates already (a pin's file by stamp_location, a close's changes by
    limn.pins.lifecycle.input.parse_close_changes) and needs no folder."""
    known: dict[Path, Path] = {}
    seen: set[Path] = set()
    for record in records:
        for stored in map(_stored, _stored_files(record)):
            if stored is None or not stored.name or _recorded_rel(stored, record, root) is not None:
                continue
            folder = stored.parent
            if folder in seen:
                continue
            if len(seen) >= RECORDED_FOLDERS_MAX:
                return MappingProxyType(known)
            seen.add(folder)
            try:
                real = Path(os.path.realpath(folder))
            except (OSError, ValueError, RuntimeError):
                continue
            rel = _below(real, root)
            if rel is None or any(part.startswith(".") for part in rel.parts) or _in_state(real, root, state):
                continue
            known[folder] = real
    return MappingProxyType(known)


def _stored_files(record: Mapping[str, Any]) -> list[object]:
    """The paths record stores: its `file` and each `changes[].file`, unchecked. Pure."""
    changes = record.get("changes")
    listed = changes if isinstance(changes, list) else []
    return [record.get("file"), *(change.get("file") for change in listed if isinstance(change, Mapping))]


def _stored(file: object) -> Path | None:
    """A stored path as recorded_place reads it: absolute, '..' parts folded, without NUL and at most PATH_MAX_CHARS
    characters, else None. Pure."""
    if not isinstance(file, str) or not file or len(file) > PATH_MAX_CHARS or "\x00" in file:
        return None
    return Path(os.path.normpath(file)) if os.path.isabs(file) else None


def _recorded_rel(stored: Path, record: Mapping[str, Any], root: Path) -> Path | None:
    """stored's part below root by rules 1 and 2 of recorded_place - lexically below root, else below the root the
    record says it was written under (recorded_root) - or None. Pure."""
    rel = _below(stored, root)
    if rel is not None:
        return rel
    base = recorded_root(record.get("file"), record.get("file_rel"))
    return None if base is None else _below(stored, base)


def _in_state(path: Path, root: Path, state: Path) -> bool:
    """Does path lie in the state folder `state` held inside root (the tree rule's state part, state resolved)? True
    when state cannot be resolved, so that nothing is placed then."""
    try:
        held = state.resolve()
    except (OSError, RuntimeError):
        return True
    return held.is_relative_to(root) and path.is_relative_to(held)


def _below(path: Path, folder: Path) -> Path | None:
    """path relative to folder when it lies lexically below it, else None. Pure."""
    try:
        return path.relative_to(folder)
    except ValueError:
        return None


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
# The rule is limn.pins.location.position's (overlaps_by_id, selection_rel, overlaps_for_range); here each pin is counted in
# the file locate finds for it now (located_file), so a moved checkout's old and new pins overlap as one file.


def overlaps_by_id(pins: Sequence[Pin], locate: Locator) -> dict[int, list[dict[str, Any]]]:
    """The relationship of every pair of open line pins on the same file, as locate places each pin's file now
    (limn.pins.location.position.overlaps_by_id): {id: [{"id", "rel"}, ...]} with an entry for every open pin. Never stored."""
    return position.overlaps_by_id(pins, lambda pin: located_file(pin, locate))


def overlaps_for_range(file: str, lo: int, hi: int, pins: Sequence[Pin], locate: Locator) -> list[dict[str, Any]]:
    """The overlap relationships between a not-yet-saved range lo..hi of file and the open line pins that locate
    places in that file now (limn.pins.location.position.overlaps_for_range): [{"id", "lo", "hi", "rel"}] in the pins' order.
    Nothing is saved."""
    return position.overlaps_for_range(file, lo, hi, pins, lambda pin: located_file(pin, locate))


# ---------------------------------------------------------------- Anchors and re-syncing


def sync_all(pins: list[Pin], locate: Locator, has_pages: Callable[[Record], bool] = lambda record: True) -> bool:
    """If the manuscript is newer than a pin, re-match its line numbers via the anchor (limn.pins.location.position.resync).
    A re-matched pin replaces its old state in pins - written like any pin, so without the page fields of a line pin
    whose document has none (has_pages, limn.pins.pages.keep_pages); returns whether any pin changed. The pin store
    calls this under its lock before every transaction (limn.pins.store.PinStore.sync).

    Open line pins only (a view-only PDF's pin has no lines). The pin's file is the one locate finds (ADR-0006: a moved
    checkout is followed; outside the tree is never read); a pin whose file cannot be located or is not a file now is
    left alone. Each file is read once per call. A located file read failure raises ManuscriptReadError;
    the store must discard this batch rather than persist anchors inferred from empty text."""
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
        if f not in cache:
            ls, mtime = loc.source.snapshot_checked()
            cache[f] = (ls, [norm(t) for t in ls], mtime)
        lines, nlines, mtime = cache[f]
        new = resync(pin, span, lines, nlines, mtime, str(f))
        if new is not None:
            pins[i] = keep_pages(new, has_pages(new.record))
            changed = True
    return changed


# ---------------------------------------------------------------- Location estimation (.est)


def est_context(D: Doc, builds: BuildAnswers) -> EstContext:
    """Estimation facts answered by the build owner once for document D. builds is the run's injected query bundle;
    the caller passes it, since this module makes none."""
    facts = builds.position(D)
    return EstContext(facts.cur, facts.exact_builds, facts.built_at, facts.built_src_mtime)
