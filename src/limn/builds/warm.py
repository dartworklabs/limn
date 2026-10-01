"""Warm LaTeX builds and the no-change skip: which files the build copy keeps between builds, what a build's recipe
is (with the digest of what it read), and whether a rebuild may keep the pages on screen (docs/handbook/build-sync.md §따뜻한 LaTeX와 변경 없는 재빌드).

The byproducts latexmk leaves next to the main file (.aux, .bbl, .fdb_latexmk, .fls, ...) let the next latexmk run only
the steps whose inputs changed. They are a disposable cache: a forced rebuild and every build that does not end ok
clear them, and the next build is cold. Pure: names and decisions only; limn.builds.engine does the file work.
"""

import hashlib
import os
import re
from collections.abc import Collection, Sequence
from pathlib import PurePosixPath
from typing import Any

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
_UP_TO_DATE = re.compile(r"^Latexmk: All targets \(.*\) are up-to-date\s*$", re.MULTILINE)


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


def fls_reads(text: str, cwd: str, roots: Sequence[str]) -> frozenset[str]:
    """Every file a latexmk recorder file (.fls) says pdflatex read and did not write: its `INPUT <path>` lines that no
    `OUTPUT <path>` line names, each resolved lexically against cwd (the folder pdflatex ran in) when relative, kept
    when it lies strictly below one of roots (the build copy, as a path and resolved) and named relative to that root
    ('a/b.csv'), whatever its suffix - data files, \\input'd files and figures alike. TeX Live's own files, a name with
    a NUL byte and anything outside the copy are dropped."""
    here = os.path.normpath(cwd)
    bases = [os.path.normpath(r) for r in roots]

    def full(spelled: str) -> str:
        """The lexical absolute path of a recorder line's name."""
        return os.path.normpath(spelled if os.path.isabs(spelled) else os.path.join(here, spelled))

    read: set[str] = set()
    written: set[str] = set()
    for line in text.split("\n"):
        kind, _, spelled = line.rstrip("\r").partition(" ")
        if kind not in ("INPUT", "OUTPUT") or not spelled or "\x00" in spelled:
            continue
        (read if kind == "INPUT" else written).add(full(spelled))
    found: set[str] = set()
    for path in read - written:
        for base in bases:
            if path.startswith(base + os.sep):
                found.add(path[len(base) + 1 :].replace(os.sep, "/"))
                break
    return frozenset(found)


def reads_digest(rc_files: Sequence[tuple[str, bytes | None]], read_files: Sequence[tuple[str, bytes | None]]) -> str:
    """One digest (32 hex digits) of what a build read beyond its fingerprint: each latexmkrc file latexmk would read and
    each file the build's .fls lists as read, as (name, SHA-256 of its bytes, or None when it is missing), in the order
    given. A file that appears, disappears or changes changes the digest."""
    h = hashlib.sha256()
    for group, files in ((b"rc", rc_files), (b"read", read_files)):
        h.update(group + b"\0")
        for name, digest in files:
            h.update(name.encode("utf-8", "surrogateescape") + b"\0" + (b"-" if digest is None else b"+" + digest))
    return h.hexdigest()[:32]


def recipe(dpi: int, main_rel: PurePosixPath, latexmk_args: Sequence[str], reads: str | None) -> str:
    """How a LaTeX build makes its pages, besides its fingerprint: the page image dpi, the main file below the build
    root, latexmk's switches, and reads - the reads_digest of its latexmkrc files and of every file its .fls says it read
    ("-" when it kept no .fls). Two builds with the same fingerprint and recipe have the same pages."""
    return "dpi=%d main=%s latexmk=%s reads=%s" % (dpi, main_rel.as_posix(), " ".join(latexmk_args), reads or "-")


def up_to_date(latexmk_output: str) -> bool:
    """Did latexmk say every target was already up to date (its own 'Latexmk: All targets (...) are up-to-date'
    line), so it wrote no new PDF, SyncTeX, .aux or .fls? Only a warm copy can get this answer."""
    return _UP_TO_DATE.search(latexmk_output) is not None


def keeps_pages(history: dict[str, Any], current: str, fingerprint: str | None, build_recipe: str) -> bool:
    """May a rebuild keep page directory `current` (the one on screen) instead of building? Only when the last finished
    build (history["last"], limn.builds.artifacts.load_builds) was ok and made `current`, and `current`'s history entry
    has this fingerprint (not None) and this recipe - which the caller computes over the copy with `current`'s own .fls,
    so the files that build read are compared too. A build of an older Limn has no recipe and never matches; a last
    build that failed or had LaTeX errors never matches either, so such a manuscript is always rebuilt."""
    last = history.get("last")
    ent = history.get("by", {}).get(current)
    return (
        fingerprint is not None
        and isinstance(last, dict)
        and last.get("state") == "ok"
        and last.get("build") == current
        and isinstance(ent, dict)
        and ent.get("src_hash") == fingerprint
        and ent.get("recipe") == build_recipe
    )
