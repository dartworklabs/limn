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
# The project rc files latexmk reads from the folder it runs in; the build root's are counted too (warm.reads_digest).
LATEXMKRC_NAMES = ("latexmkrc", ".latexmkrc")
_UP_TO_DATE = re.compile(r"^Latexmk: All targets \((.*)\) are up-to-date\s*$", re.MULTILINE)


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
RECIPE_FORMAT = 1
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


def reads_digest(
    rc_files: Sequence[tuple[str, bytes | None]],
    inside: Sequence[tuple[str, bytes | None]],
    outside: Sequence[tuple[str, bytes | None]],
) -> str:
    """One digest (32 hex digits) of what a build read: each latexmkrc file latexmk would read and each file inside the
    copy, as (name, SHA-256 of its bytes), and each file outside it, as (path, its mtime_ns and size) - None for a file
    that is missing - in the order given. A file that appears, disappears or changes changes the digest."""
    h = hashlib.sha256()
    for group, files in ((b"rc", rc_files), (b"inside", inside), (b"outside", outside)):
        h.update(group + b"\0")
        for name, token in files:
            h.update(name.encode("utf-8", "surrogateescape") + b"\0" + (b"-" if token is None else b"+" + token))
    return h.hexdigest()[:32]


def recipe(dpi: int, main_rel: PurePosixPath, latexmk_args: Sequence[str], reads: Reads, digest: str) -> dict[str, Any]:
    """How a LaTeX build made its pages, besides its fingerprint, as its page folder's RECIPE_NAME holds it: the page
    image dpi, the main file below the build root, latexmk's switches, the files it read (inside and outside the copy)
    and the reads_digest of those and of its latexmkrc files when it finished."""
    return {
        "format": RECIPE_FORMAT,
        "dpi": dpi,
        "main": main_rel.as_posix(),
        "latexmk": list(latexmk_args),
        "inside": sorted(reads.inside),
        "outside": sorted(reads.outside),
        "digest": digest,
    }


def stored_reads(stored: object) -> Reads | None:
    """The files a recipe (as recipe() makes it, read back from JSON) says its build read, or None for anything that is
    not such a recipe - another format, a missing or mistyped field."""
    if not isinstance(stored, dict) or stored.get("format") != RECIPE_FORMAT:
        return None
    inside, outside = stored.get("inside"), stored.get("outside")
    if not (isinstance(inside, list) and isinstance(outside, list)):
        return None
    if not all(isinstance(x, str) for x in inside + outside):
        return None
    return Reads(frozenset(inside), frozenset(outside))


def recipe_matches(stored: object, dpi: int, main_rel: PurePosixPath, latexmk_args: Sequence[str], digest: str) -> bool:
    """Does the recipe a build stored still hold: the same dpi, main file and switches, and `digest` - the reads_digest
    the caller made now over the files the recipe lists (stored_reads) - equal to the one it recorded?"""
    return (
        stored_reads(stored) is not None
        and isinstance(stored, dict)
        and stored.get("dpi") == dpi
        and stored.get("main") == main_rel.as_posix()
        and stored.get("latexmk") == list(latexmk_args)
        and stored.get("digest") == digest
    )


def up_to_date_target(latexmk_output: str) -> str | None:
    """What the last 'Latexmk: All targets (X) are up-to-date' line of latexmk's output names (X), or None. latexmk
    4.87 prints that line after every run that ends without an error, a run that compiled too, so it says only which
    targets latexmk ended with - never that it compiled nothing."""
    found = _UP_TO_DATE.findall(latexmk_output)
    return found[-1] if found else None


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
