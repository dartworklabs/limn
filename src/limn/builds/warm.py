"""Warm LaTeX builds and the no-change skip: which files the build copy keeps between builds, what a build's recipe
is, and whether a rebuild may keep the pages on screen (docs/handbook/build-sync.md §따뜻한 LaTeX와 변경 없는 재빌드).

The byproducts latexmk leaves next to the main file (.aux, .bbl, .fdb_latexmk, .fls, ...) let the next latexmk run only
the steps whose inputs changed. They are a disposable cache: a forced rebuild and every build that does not end ok
clear them, and the next build is cold. Pure: names and decisions only; limn.builds.engine does the file work.
"""

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


def recipe(dpi: int, main_rel: PurePosixPath, latexmk_args: Sequence[str]) -> str:
    """How a LaTeX build makes its pages, besides the manuscript: the page image dpi, the main file below the build
    root and latexmk's switches. Two builds with the same fingerprint and recipe have the same pages."""
    return "dpi=%d main=%s latexmk=%s" % (dpi, main_rel.as_posix(), " ".join(latexmk_args))


def up_to_date(latexmk_output: str) -> bool:
    """Did latexmk say every target was already up to date (its own 'Latexmk: All targets (...) are up-to-date'
    line), so it wrote no new PDF, SyncTeX, .aux or .fls? Only a warm copy can get this answer."""
    return _UP_TO_DATE.search(latexmk_output) is not None


def keeps_pages(history: dict[str, Any], current: str, fingerprint: str | None, build_recipe: str) -> bool:
    """May a rebuild keep page directory `current` (the one on screen) instead of building? Only when the last finished
    build (history["last"], limn.builds.artifacts.load_builds) was ok and made `current`, and `current`'s history entry
    has this fingerprint (not None) and this recipe. A build of an older Limn has no recipe and never matches; a last
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
