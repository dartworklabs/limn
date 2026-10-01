"""Warm LaTeX builds and the no-change skip: which files the build copy keeps between builds, when what latexmk left
there may stand for a build, what a build's recipe is (with the digest of what it read), and whether a rebuild may keep
the pages on screen (docs/handbook/build-sync.md §따뜻한 LaTeX와 변경 없는 재빌드).

The byproducts latexmk leaves next to the main file (.aux, .bbl, .fdb_latexmk, .fls, ...) let the next latexmk run only
the steps whose inputs changed. They are a disposable cache: a forced rebuild and every build that does not end ok
clear them, and the next build is cold. Pure: names and decisions only; limn.builds.engine does the file work.
"""

import hashlib
import os
import re
from collections.abc import Collection, Sequence
from pathlib import PurePosixPath
from typing import Any, NamedTuple

# What latexmk, pdflatex, bibtex/biber and makeindex write next to the main file, named <stem><suffix>.
BYPRODUCT_SUFFIXES = (
    ".aux",
    ".bbl",
    ".bcf",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".idx",
    ".ilg",
    ".ind",
    ".lof",
    ".log",
    ".lot",
    ".nav",
    ".out",
    ".run.xml",
    ".snm",
    ".spl",
    ".toc",
    ".vrb",
)
OUTPUT_SUFFIXES = (".pdf", ".synctex.gz")  # the build's own output; the copy already never touches *.synctex.gz
# The project rc files latexmk reads from the folder it runs in; the build root's are counted too (warm.cold_digest).
LATEXMKRC_NAMES = ("latexmkrc", ".latexmkrc")
# The tools a latexmk run may start, as rc variables whose command's first word names the program: -pdf runs $pdflatex,
# and bibtex, biber and makeindex run when the document needs them. Each defaults to its own name.
TOOL_VARS = ("pdflatex", "bibtex", "biber", "makeindex")
_ILG_STYLE = "Scanning style file "  # makeindex: "Scanning style file ./style.ist.done (...)" - one dot per few lines
_BLG_STYLE = "The style file: "  # bibtex: "The style file: plain.bst"
_WORD_END = frozenset(" \t'\";")
_UP_TO_DATE = ("Latexmk: All targets (", ") are up-to-date")


def byproduct_names(stem: str) -> tuple[str, ...]:
    """The names of the main file's byproducts and outputs (stem + each of BYPRODUCT_SUFFIXES and OUTPUT_SUFFIXES):
    what a forced or failed build clears from the folder latexmk runs in."""
    return tuple(stem + s for s in BYPRODUCT_SUFFIXES + OUTPUT_SUFFIXES)


def kept_paths(out_rel: PurePosixPath, stem: str, source_names: Collection[str]) -> tuple[str, ...]:
    """The paths below the build copy (POSIX, relative) that the copy step neither deletes nor overwrites: the main
    file's byproducts and its PDF in out_rel, the folder latexmk runs in. source_names are the file names the manuscript
    holds in that folder. When one of them is a byproduct name (a manuscript that ships its main.bbl, say), nothing is
    kept: the manuscript's own file is copied and used as it always was, and every build is cold. A committed PDF of
    the same name never counts: the build's PDF is kept, so the committed one never lands where latexmk writes."""
    names = set(source_names)
    if any(stem + s in names for s in BYPRODUCT_SUFFIXES):
        return ()
    return tuple((out_rel / (stem + s)).as_posix() for s in BYPRODUCT_SUFFIXES + (".pdf",))


class Reads(NamedTuple):
    """The files a build read: inside, relative to the build copy ('a/b.csv'), whose bytes are compared; outside, the
    absolute paths of everything else (TeX Live, a TEXINPUTS folder, the user's format file), whose stat is compared."""

    inside: frozenset[str]
    outside: frozenset[str]


NO_READS = Reads(frozenset(), frozenset())
RECIPE_NAME = "recipe.json"  # the sidecar a LaTeX build publishes in its page folder, next to its .fls
RECIPE_FORMAT = 3
# One source line of a .fdb_latexmk rule: "name" mtime size md5 "rule that made it" ("" for a primary source).
_FDB_SOURCE = re.compile(r'^  "((?:[^"\\]|\\.)*)" \S+ \S+ \S+ "([^"]*)"\s*$')


def _split(paths: Collection[str], cwd: str, roots: Sequence[str]) -> Reads:
    """paths, resolved lexically against cwd when relative, split into those strictly below one of roots (named
    relative to it, POSIX) and all others (absolute). A name with a NUL byte is dropped."""
    here = os.path.normpath(cwd)
    bases = [os.path.normpath(r) for r in roots]
    inside: set[str] = set()
    outside: set[str] = set()
    for spelled in paths:
        if not spelled or "\x00" in spelled:
            continue
        full = os.path.normpath(spelled if os.path.isabs(spelled) else os.path.join(here, spelled))
        for base in bases:
            if full.startswith(base + os.sep):
                inside.add(full[len(base) + 1 :].replace(os.sep, "/"))
                break
        else:
            outside.add(full)
    return Reads(frozenset(inside), frozenset(outside))


def fls_reads(text: str, cwd: str, roots: Sequence[str]) -> Reads:
    """Every file a latexmk recorder file (.fls) says pdflatex read and did not write: its `INPUT <path>` lines that no
    `OUTPUT <path>` line names, each resolved lexically against cwd (the folder pdflatex ran in) when relative, split by
    whether it lies strictly below one of roots (the build copy, as a path and resolved), whatever its suffix - data
    files, \\input'd files and figures alike inside; TeX Live's own files outside."""
    read: set[str] = set()
    written: set[str] = set()
    for line in text.split("\n"):
        kind, _, spelled = line.rstrip("\r").partition(" ")
        if kind == "INPUT":
            read.add(spelled)
        elif kind == "OUTPUT":
            written.add(spelled)
    return _split(read - written, cwd, roots)


def fdb_sources(text: str, cwd: str, roots: Sequence[str]) -> Reads:
    """The primary sources of every rule a latexmk database (.fdb_latexmk) records - pdflatex's, and also bibtex's,
    biber's and makeindex's (a .bib, .bst or .ist the .fls never lists): its source lines whose last field, the rule
    that made the file, is empty. Generated files (.aux, .bbl) and the (generated) lists are left out. Split as fls_reads
    does; a line of another shape is skipped."""
    found: set[str] = set()
    for line in text.split("\n"):
        m = _FDB_SOURCE.match(line.rstrip("\r"))
        if m is not None and m.group(2) == "":
            found.add(m.group(1).replace('\\"', '"'))
    return _split(found, cwd, roots)


def union(*reads: Reads) -> Reads:
    """All the files of reads together."""
    return Reads(frozenset().union(*(r.inside for r in reads)), frozenset().union(*(r.outside for r in reads)))


Tokens = Sequence[tuple[str, bytes | None]]


def _digest(groups: Sequence[tuple[bytes, Tokens]]) -> str:
    """32 hex digits of SHA-256 over named groups of (name, token) - a token None for a missing file - in order."""
    h = hashlib.sha256()
    for group, files in groups:
        h.update(group + b"\0")
        for name, token in files:
            h.update(name.encode("utf-8", "surrogateescape") + b"\0" + (b"-" if token is None else b"+" + token))
    return h.hexdigest()[:32]


def reads_digest(inside: Tokens, outside: Tokens) -> str:
    """One digest (32 hex digits) of what a build read: each file inside the copy as (name, SHA-256 of its bytes) and
    each file outside it as (path, its mtime_ns and size), None for a file that is missing, in the order given. A file
    that appears, disappears or changes changes the digest."""
    return _digest(((b"inside", inside), (b"outside", outside)))


def cold_digest(rc_files: Tokens, tools: Tokens, styles: Tokens) -> str:
    """The recipe-level digest (32 hex digits): what latexmk does not track, so a change to it must not meet a warm
    copy. Each latexmkrc latexmk would read, by its bytes; each tool the run may start, as 'var=<real path>' with the
    program's mtime_ns and size (a new TeX Live year on PATH, an in-place update); and each style file named only in a
    side tool's log (makeindex's .ist, bibtex's .bst), by its bytes or stat."""
    return _digest(((b"rc", rc_files), (b"tools", tools), (b"styles", styles)))


def tool_names(rc_texts: Sequence[str]) -> dict[str, str]:
    """The program each of TOOL_VARS runs, from rc texts in the order latexmk reads them (a later assignment wins): the
    first word of a `$pdflatex = '...'` style assignment ('xelatex' for "$pdflatex = 'xelatex %O %S'"), else the
    variable's own name. Only a simple quoted assignment is read; anything else leaves the default, and the rc's own
    bytes are in the cold digest anyway."""
    names = {var: var for var in TOOL_VARS}
    for text in rc_texts:
        for line in text.splitlines():  # line by line, in linear time, whatever the rc holds
            stripped = line.lstrip()
            if not stripped.startswith("$"):
                continue
            var, eq, value = stripped[1:].partition("=")
            var, value = var.strip(), value.lstrip()
            if not eq or var not in names or value[:1] not in ("'", '"'):
                continue
            word = value[1:].lstrip()
            end = next((i for i, c in enumerate(word) if c in _WORD_END), len(word))
            if end:
                names[var] = word[:end]
    return names


def log_styles(ilg_text: str | None, blg_text: str | None) -> list[str]:
    """The style files a side tool says it read, as it spells them: makeindex's .ilg 'Scanning style file X...' and
    bibtex's .blg 'The style file: X'. latexmk does not track a style given with makeindex -s, so its edit would
    otherwise meet a warm copy that latexmk thinks is up to date."""
    found: list[str] = []
    for line in (ilg_text or "").splitlines():  # line by line, in linear time, whatever the log holds
        if line.startswith(_ILG_STYLE):
            spelled, _, _ = line[len(_ILG_STYLE) :].rpartition("done")
            name = spelled.rstrip(".")
            if spelled.endswith(".") and name:
                found.append(name)
    for line in (blg_text or "").splitlines():
        if line.startswith(_BLG_STYLE):
            name = line[len(_BLG_STYLE) :].strip()
            if name:
                found.append(name)
    return found


def recipe(
    dpi: int,
    main_rel: PurePosixPath,
    latexmk_args: Sequence[str],
    reads: Reads | None,
    digest: str | None,
    styles: Sequence[str],
    cold: str,
) -> dict[str, Any]:
    """How a LaTeX build made its pages, besides its fingerprint, as its page folder's RECIPE_NAME holds it: the page
    image dpi, the main file below the build root, latexmk's switches, the files it read (inside and outside the copy)
    and their reads_digest - both None for a build that published no .fls, which no rebuild may then skip - and the
    side tools' style files (log_styles, resolved) and the cold_digest when it finished, which the next build's go-cold
    decision uses with or without a .fls."""
    return {
        "format": RECIPE_FORMAT,
        "dpi": dpi,
        "main": main_rel.as_posix(),
        "latexmk": list(latexmk_args),
        "inside": sorted(reads.inside) if reads is not None else [],
        "outside": sorted(reads.outside) if reads is not None else [],
        "digest": digest if reads is not None else None,
        "styles": list(styles),
        "cold": cold,
    }


def _strings(v: object) -> list[str] | None:
    """v when it is a list of strings, else None."""
    return v if isinstance(v, list) and all(isinstance(x, str) for x in v) else None


def _cold_part(stored: object) -> tuple[list[str], str] | None:
    """(styles, cold) of a recipe (as recipe() makes it, read back from JSON), or None for anything that is not one -
    another format, a missing or mistyped field."""
    if not isinstance(stored, dict) or stored.get("format") != RECIPE_FORMAT:
        return None
    styles, cold = _strings(stored.get("styles")), stored.get("cold")
    return (styles, cold) if styles is not None and isinstance(cold, str) else None


def stored_reads(stored: object) -> Reads | None:
    """The files a recipe says its build read, or None when it records none (a build without a .fls) or is not such a
    recipe."""
    if _cold_part(stored) is None or not isinstance(stored, dict) or not isinstance(stored.get("digest"), str):
        return None
    inside, outside = _strings(stored.get("inside")), _strings(stored.get("outside"))
    if inside is None or outside is None:
        return None
    return Reads(frozenset(inside), frozenset(outside))


def stored_styles(stored: object) -> list[str]:
    """The style files a valid recipe lists (none for anything that is not one)."""
    part = _cold_part(stored)
    return [] if part is None else list(part[0])


def goes_cold(stored: object, cold_now: str) -> bool:
    """Must this build clear the copy's byproducts before latexmk? Yes unless the build on screen recorded a valid
    recipe - with or without a .fls - whose cold_digest equals cold_now; an unknown recipe (no recipe.json, an older
    format) goes cold too."""
    part = _cold_part(stored)
    return part is None or part[1] != cold_now


def recipe_matches(
    stored: object, dpi: int, main_rel: PurePosixPath, latexmk_args: Sequence[str], digest: str, cold: str
) -> bool:
    """Does the recipe a build stored still hold: the same dpi, main file and switches, `digest` - the reads_digest the
    caller made now over the files the recipe lists (stored_reads) - and `cold` - the cold_digest made now - equal to
    the ones it recorded?"""
    return (
        stored_reads(stored) is not None
        and isinstance(stored, dict)
        and stored.get("dpi") == dpi
        and stored.get("main") == main_rel.as_posix()
        and stored.get("latexmk") == list(latexmk_args)
        and stored.get("digest") == digest
        and stored.get("cold") == cold
    )


def up_to_date_target(latexmk_output: str) -> str | None:
    """What the last 'Latexmk: All targets (X) are up-to-date' line of latexmk's output names (X), or None. latexmk
    4.87 prints that line after every run that ends without an error, a run that compiled too, so it says only which
    targets latexmk ended with - never that it compiled nothing."""
    head, tail = _UP_TO_DATE
    found = None
    for line in latexmk_output.splitlines():  # line by line, in linear time
        line = line.rstrip()
        if line.startswith(head) and line.endswith(tail) and len(line) >= len(head) + len(tail):
            found = line[len(head) : len(line) - len(tail)]
    return found


def vouched(
    latexmk_output: str,
    stem: str,
    warm_copy: bool,
    rc: int | None,
    timed_out: bool,
    pdf_before: tuple[int, int, int] | None,
    pdf_after: tuple[int, int, int] | None,
) -> bool:
    """May a build publish what latexmk left in a warm copy (the PDF, SyncTeX, .aux) as its own, although this run wrote
    none of it? Only when all hold: the copy is warm, latexmk exited 0 and did not time out, the PDF was there before
    the run and this run did not write it (pdf_before == pdf_after, each its (mtime_ns, size, inode)), and the last
    up-to-date line names exactly <stem>.pdf - an $out_dir, $aux_dir or -jobname of a latexmkrc names another target,
    and then the PDF in the copy is not the one latexmk built."""
    return (
        warm_copy
        and rc == 0
        and not timed_out
        and pdf_before is not None
        and pdf_after == pdf_before
        and up_to_date_target(latexmk_output) == stem + ".pdf"
    )


def keeps_pages(history: dict[str, Any], current: str, fingerprint: str | None) -> bool:
    """May a rebuild keep page directory `current` (the one on screen) as far as the history says? Only when the last
    finished build (history["last"], limn.builds.artifacts.load_builds) was ok and made `current`, and `current`'s
    history entry has this fingerprint (not None). A last build that failed or had LaTeX errors never matches, so such a
    manuscript is always rebuilt. The caller also needs the build's recipe to match (recipe_matches)."""
    last = history.get("last")
    ent = history.get("by", {}).get(current)
    return (
        fingerprint is not None
        and isinstance(last, dict)
        and last.get("state") == "ok"
        and last.get("build") == current
        and isinstance(ent, dict)
        and ent.get("src_hash") == fingerprint
    )
