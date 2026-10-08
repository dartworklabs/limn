"""Modelled drags remain valid when a figure producer rounds its boxes slightly past the page edge."""

import importlib.util
import json
import random
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from limn.builds.figure_map import FRAC_EPS, FigureMap, parse_map

SPEC = importlib.util.spec_from_file_location(
    "measure_figure_pick", Path(__file__).resolve().parents[2] / "tools" / "measure_figure_pick.py"
)
assert SPEC and SPEC.loader
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)
KINDS = ("tight", "ratio", "padding", "partial", "point")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("box", ((1.0000005, 0.4, 0.0000001, 0.001), (0.4, 1.0000005, 0.001, 0.0000001)))
def test_rounded_map_edges_produce_nonnegative_page_drags(kind, box):
    """Every drag model accepts the parser's page-edge tolerance and clips its result into the real page."""
    parsed = parse_map(
        json.dumps(
            {
                "format": "limn-figure-map/1",
                "pdf": "figures.pdf",
                "pdf_sha256": "0" * 64,
                "pages": [
                    {
                        "page": 1,
                        "figure": "F",
                        "elements": [{"id": "F", "frac": [0, 0, 1, 1]}, {"id": "F/e", "parent": "F", "frac": box}],
                    }
                ],
            }
        ).encode()
    )
    assert isinstance(parsed, FigureMap)
    x, y, w, h = measure.modelled_drag(parsed.pages[0].elements[1].frac, kind, random.Random(0))
    assert 0 <= x <= 1 and 0 <= y <= 1
    assert w >= 0 and h >= 0
    assert x + w <= 1 + 1e-12 and y + h <= 1 + 1e-12


@st.composite
def boxes(draw):
    """Positive boxes satisfying the map's tolerated far edge, including slightly overshooting origins."""
    x = draw(st.floats(0, 1 + FRAC_EPS / 2))
    y = draw(st.floats(0, 1 + FRAC_EPS / 2))
    w = draw(st.floats(1e-8, 1 + FRAC_EPS - x))
    h = draw(st.floats(1e-8, 1 + FRAC_EPS - y))
    return x, y, w, h


@given(boxes(), st.sampled_from(KINDS), st.integers(0, 65535))
def test_any_modelled_drag_from_a_valid_map_box_stays_on_the_page(box, kind, seed):
    """Across sizes, model kinds, and random padding, generated drags never invert or cross the page bounds."""
    x, y, w, h = measure.modelled_drag(box, kind, random.Random(seed))
    assert 0 <= x <= 1 and 0 <= y <= 1
    assert w >= 0 and h >= 0
    assert x + w <= 1 + 1e-12 and y + h <= 1 + 1e-12
