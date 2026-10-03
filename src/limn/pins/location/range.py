"""Source snippets and overlap reads for validated manuscript ranges."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from limn.pins.location.mapping import compute_levels, snippet
from limn.platform.values import is_int


@dataclass(frozen=True, init=False)
class SourceRange:
    """An immutable manuscript snapshot with integer endpoints satisfying 1 <= lo <= hi <= len(lines)."""

    file: Path
    lines: tuple[str, ...]
    lo: int
    hi: int

    def __init__(self, file: Path, lines: Sequence[str], lo: int, hi: int) -> None:
        """Copy the source lines and freeze the range; invalid integer endpoints or bounds raise ValueError."""
        snapshot = tuple(lines)
        if not is_int(lo) or not is_int(hi) or not 1 <= lo <= hi <= len(snapshot):
            raise ValueError("source range requires integer endpoints within its source lines")
        object.__setattr__(self, "file", file)
        object.__setattr__(self, "lines", snapshot)
        object.__setattr__(self, "lo", lo)
        object.__setattr__(self, "hi", hi)


def overlaps_api(rng: SourceRange, overlaps: Callable[[str, int, int], list[dict[str, Any]]]) -> dict[str, Any]:
    """GET /api/overlaps - asks about a not-yet-saved selection's overlap using only file/range (kept for
    agent/legacy-viewer compatibility): {"overlaps": [...]}, the stored open pins' relationships as overlaps finds
    them.

    The current viewer instead recomputes the same rule (overlapsFor) locally against its own PINS on every
    range change, with no round trip - because pressing [Save Pin] while a response is still in flight could
    otherwise save a duplicate with no banner shown. rng is the range parsed by location.input.parse_source_range."""
    return {"overlaps": overlaps(str(rng.file), rng.lo, rng.hi)}


def snippet_api(rng: SourceRange, levels: bool, envs: Sequence[str], source_ladder: bool = True) -> dict[str, Any]:
    """GET /api/snippet: the source lines lo..hi of a manuscript file (a range parsed by location.input.parse_snippet),
    and with levels the range ladder around them - compute_levels' for the float environments envs when the document's
    ladder comes from its text (source_ladder), else raw_ladder's."""
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
        lad = compute_levels(lines, lo, hi, envs) if source_ladder else raw_ladder(lines, lo, hi)
        out["levels"] = lad["levels"]
        out["default_level"] = lad["default_level"]
    return out


def raw_ladder(lines: Sequence[str], lo: int, hi: int) -> dict[str, Any]:
    """The ladder of a range in a document whose rungs come from its element map rather than its text (a figure's
    drawing script): the raw rung alone - the lines as they are - and it is the default. Paragraph and environment
    rungs are LaTeX rules and mean nothing in code; the element ladder is the pick's (docs/handbook/api.md §그림 문서의
    pick·핀)."""
    rung = {
        "level": "raw",
        "lo": lo,
        "hi": hi,
        "label": "드래그한 줄",
        "n": hi - lo + 1,
        "snippet": snippet(lines, lo, hi),
    }
    return {"levels": [rung], "default_level": "raw"}
