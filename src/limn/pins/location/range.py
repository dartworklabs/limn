"""Source snippets and overlap reads for validated manuscript ranges."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from limn.pins.editing.values import SUGGEST_LINES_MAX
from limn.pins.location.mapping import Level, MarkPiece, mark_wire, rung_ladder, snippet
from limn.pins.suggestion import lines_text
from limn.platform.values import is_int

# Asks where the lines lo..hi of the range's file print: (lo, hi) -> the mark's pieces, empty when there is none. The
# run binds one of these to the build it is reading (limn.pins.location.resolve.range_boxes); a caller that holds no
# build facts passes no_boxes, and this module never learns what a build is.
RangeBoxes: TypeAlias = Callable[[int, int], tuple[MarkPiece, ...]]


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


def no_boxes(_lo: int, _hi: int) -> tuple[MarkPiece, ...]:
    """A RangeBoxes that answers no pieces - snippet_api's default, so a caller holding no build facts (and every
    document with no pages to measure a mark against) answers exactly the ladder it answered before marks followed the
    range."""
    return ()


def snippet_api(
    rng: SourceRange,
    levels: bool,
    envs: Sequence[str],
    source_ladder: bool = True,
    text: bool = False,
    boxes: RangeBoxes = no_boxes,
) -> dict[str, Any]:
    """GET /api/snippet: the source lines lo..hi of a manuscript file (a range parsed by location.input.parse_snippet),
    and with levels the range ladder around them - mapping.rung_ladder's for the float environments envs when the
    document's ladder comes from its text (source_ladder), else the raw rung alone. Every rung carries where its own
    lines print (`boxes`, the run's asker) when the caller asked for marks (?boxes=1, limn.pins.location.http.snippet):
    the composing box reads this route for every range it settles on, so the mark follows the range with no further
    round trip, while a caller that wants the lines alone runs no process. With text (?text=1), and only for a
    range of at most SUGGEST_LINES_MAX lines, `text` comes last: the exact lines unnumbered, joined with "\n",
    carriage returns removed - what a suggested edit's base must be (limn.pins.suggestion.lines_text). Every other
    field is the same."""
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
        if source_ladder:
            rungs, default, _kind = rung_ladder(lines, lo, hi, envs)
        else:
            rungs = [raw_rung(lines, lo, hi)]
            default = rungs[0]
        out["levels"] = [_rung_with_boxes(rung, boxes) for rung in rungs]
        out["default_level"] = default["level"]
    exact = lines_text(lines, lo, hi) if text and hi - lo + 1 <= SUGGEST_LINES_MAX else None
    if exact is not None:
        out["text"] = exact
    return out


def _rung_with_boxes(rung: Mapping[str, object], boxes: RangeBoxes) -> Mapping[str, object]:
    """One rung of the answered ladder: the rung as the ladder built it, carrying where its own lines print when there
    is an answer for them.

    A rung with no pieces is left as it was rather than given an empty list, so a client reads "no mark for this
    range" and not "a mark of no pieces" - the same rule as a pick's default rung
    (limn.pins.location.http._levels_with_boxes). Each rung is asked by its own range, and the asker owns the cost of
    answering: a rung longer than mapping.FORWARD_LINES_MAX answers nothing without a single call. A rung is read as
    the mapping it is (mapping.Level puts no type on its values), so its line numbers are checked and not assumed; a
    rung that holds no integer range is answered without a mark rather than asked about."""
    lo, hi = rung["lo"], rung["hi"]
    pieces = boxes(lo, hi) if is_int(lo) and is_int(hi) else ()
    return {**rung, "boxes": mark_wire(pieces)} if pieces else rung


def raw_rung(lines: Sequence[str], lo: int, hi: int) -> Level:
    """The one rung of a document whose ladder comes from its element map rather than its text (a figure's drawing
    script): the lines as they are. Paragraph and environment rungs are LaTeX rules and mean nothing in code; the
    element ladder is the pick's (docs/handbook/api.md §그림 문서의 pick·핀)."""
    return {
        "level": "raw",
        "lo": lo,
        "hi": hi,
        "label": "드래그한 줄",
        "n": hi - lo + 1,
        "snippet": snippet(lines, lo, hi),
    }


def raw_ladder(lines: Sequence[str], lo: int, hi: int) -> dict[str, Any]:
    """The ladder of such a document as an answer's fields: raw_rung alone, and it is the default."""
    return {"levels": [raw_rung(lines, lo, hi)], "default_level": "raw"}
