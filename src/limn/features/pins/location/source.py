"""SyncTeX and printed-text samples, with token weights cached per file version."""

import contextlib
import re
import subprocess
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from limn.mapping import TokenWeights, synctex_range

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
