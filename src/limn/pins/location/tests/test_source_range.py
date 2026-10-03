"""Source ranges enforce their bounds independently of the HTTP parser."""

from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from limn.pins.location.range import SourceRange, snippet_api


@given(st.lists(st.text(), max_size=20), st.integers(-5, 25), st.integers(-5, 25))
def test_only_ordered_positive_ranges_inside_the_snapshot_can_be_constructed(lines, lo, hi):
    """A range exists exactly when both endpoints lie in its immutable source snapshot."""
    if 1 <= lo <= hi <= len(lines):
        source = SourceRange(Path("/manuscript/main.tex"), lines, lo, hi)
        assert (source.lo, source.hi, len(source.lines)) == (lo, hi, len(lines))
    else:
        with pytest.raises(ValueError):
            SourceRange(Path("/manuscript/main.tex"), lines, lo, hi)


@pytest.mark.parametrize(("lo", "hi"), [(True, 1), (1, True), (1.0, 1), (1, 1.0)])
def test_range_endpoints_require_integers_other_than_booleans(lo, hi):
    """Typed callers cannot introduce boolean or floating-point line indices."""
    with pytest.raises(ValueError):
        SourceRange(Path("/manuscript/main.tex"), ["first"], lo, hi)


def test_mutating_the_original_lines_does_not_change_the_range_snapshot():
    """A caller cannot invalidate a constructed range by clearing its source list."""
    lines = ["first", "second"]
    source = SourceRange(Path("/manuscript/main.tex"), lines, 1, 2)
    lines.clear()
    assert snippet_api(source, False, ())["snippet"] == "    1  first\n    2  second"
