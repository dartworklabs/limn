"""Source snippets and overlap reads for validated manuscript ranges."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from limn.pins.location.mapping import compute_levels, snippet


class SourceRange(NamedTuple):
    """A validated range of a manuscript file: the file, its lines as read, and 1 <= lo <= hi <= len(lines)."""

    file: Path
    lines: list[str]
    lo: int
    hi: int


def overlaps_api(rng: SourceRange, overlaps: Callable[[str, int, int], list[dict[str, Any]]]) -> dict[str, Any]:
    """GET /api/overlaps - asks about a not-yet-saved selection's overlap using only file/range (kept for
    agent/legacy-viewer compatibility): {"overlaps": [...]}, the stored open pins' relationships as overlaps finds
    them.

    The current viewer instead recomputes the same rule (overlapsFor) locally against its own PINS on every
    range change, with no round trip - because pressing [Save Pin] while a response is still in flight could
    otherwise save a duplicate with no banner shown. rng is the range parsed by location.input.parse_source_range."""
    return {"overlaps": overlaps(str(rng.file), rng.lo, rng.hi)}


def snippet_api(rng: SourceRange, levels: bool, envs: Sequence[str]) -> dict[str, Any]:
    """GET /api/snippet: the source lines lo..hi of a manuscript file (a range parsed by location.input.parse_snippet),
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
