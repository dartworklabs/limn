"""limn.builds.figure_map's pick, ladder and follow rules: which element a drag on a figure page points at, the range
ladder above it, and where a pinned element is on a later build's map - pure functions over map values.

The parser half of the module (parse_map) is tested with P1a's tests. Here pages are built from the value types
directly, so each rule is seen without JSON, files or a server. docs/handbook/domain.md §그림 문서의 요소 pick
describes the ladder the rules feed; the Hypothesis properties at the end check them on generated element trees against
an oracle written from that description.

Run: uv run pytest -q src/limn/builds/tests/test_figure_map_pick.py
"""

import json
import unittest

from hypothesis import given, settings, strategies as st

from limn.builds.figure_map import (
    COVER_MIN,
    FILL_MIN,
    FOLLOW_EPS,
    LADDER_MAX,
    ElementFollow,
    FigureMap,
    MapElement,
    MapPage,
    SourceRef,
    element_kind,
    follow_element,
    ladder_scopes,
    parse_map,
    pick_element,
)

SHA = "0" * 64


def el(eid, parent, frac, src=None, part=None, label=None):
    """A map element of f.py; src given as (lo, hi), or None for an element drawn without code (D7)."""
    return MapElement(eid, parent, tuple(frac), None if src is None else SourceRef("f.py", *src), None, part, label)


ROOT = el("F", None, (0, 0, 1, 1), src=(1, 200))
# A calendar strip with two month cells side by side, like the spec's example map.
CAL = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(80, 97), part="CalendarStrip", label="달력")
JUL = el("F/cal/m07", "F/cal", (0.2, 0.2, 0.2, 0.2), src=(88, 95), part="MonthCell", label="7월")
AUG = el("F/cal/m08", "F/cal", (0.4, 0.2, 0.2, 0.2), part="MonthCell", label="8월")


def page(*elements, n=1):
    """Page n of figure F: the root, then elements in map order."""
    return MapPage(n, "F", None, (ROOT, *elements))


CAL_PAGE = page(CAL, JUL, AUG)


def fmap(*pages):
    """A map of the given pages."""
    return FigureMap("figures.pdf", SHA, tuple(pages))


class Pick(unittest.TestCase):
    """pick_element: the deepest covering element, else the common ancestor of the filled ones, else the root."""

    def test_a_point_picks_the_deepest_element_holding_it(self):
        """A click (a drag without area) is its point: every box holding it covers it fully and the deepest wins."""
        got = pick_element(CAL_PAGE, (0.3, 0.3, 0.0, 0.0))
        self.assertEqual((got.chosen.id, got.score), ("F/cal/m07", 1.0))

    def test_a_small_box_inside_a_leaf_picks_the_leaf(self):
        """A box wholly inside the July cell is covered by the cell, the strip and the root; the cell is deepest."""
        got = pick_element(CAL_PAGE, (0.25, 0.25, 0.05, 0.05))
        self.assertEqual(got.chosen.id, "F/cal/m07")
        self.assertAlmostEqual(got.score, 1.0)

    def test_a_box_inside_the_parent_across_siblings_picks_the_parent(self):
        """Each cell covers only half of a box straddling both; the strip holding the whole box covers it."""
        self.assertEqual(pick_element(CAL_PAGE, (0.3, 0.25, 0.2, 0.1)).chosen.id, "F/cal")

    def test_a_box_across_siblings_and_beyond_their_parent_picks_the_common_ancestor(self):
        """The box reaches past the strip (its cover 0.5 < COVER_MIN) but fills both cells: their nearest common
        ancestor is chosen and scored by its own cover."""
        got = pick_element(CAL_PAGE, (0.25, 0.1, 0.3, 0.4))
        self.assertEqual(got.chosen.id, "F/cal")
        self.assertAlmostEqual(got.score, 0.5)

    def test_a_drag_across_branches_of_a_parsed_map_ends_at_the_root_and_never_raises(self):
        """Through parse_map (the only way a served page is made): two elements in separate branches under the root are
        both filled by a wide drag, so their common ancestor is the root itself - the walk up from any element of an
        accepted map reaches the root, so _common_ancestor always has an answer."""

        def box(eid, parent, frac):
            """One map element."""
            return {"id": eid, "parent": parent, "frac": frac}

        raw = {
            "format": "limn-figure-map/1",
            "pdf": "f.pdf",
            "pdf_sha256": SHA,
            "pages": [
                {
                    "page": 1,
                    "figure": "F",
                    "elements": [
                        {"id": "F", "frac": [0, 0, 1, 1]},
                        box("F/a", "F", [0.0, 0.0, 0.3, 0.3]),
                        box("F/a/x", "F/a", [0.0, 0.0, 0.2, 0.2]),
                        box("F/b", "F", [0.7, 0.7, 0.3, 0.3]),
                        box("F/b/y", "F/b", [0.8, 0.8, 0.2, 0.2]),
                    ],
                }
            ],
        }
        parsed = parse_map(json.dumps(raw).encode())
        self.assertIsInstance(parsed, FigureMap)
        got = pick_element(parsed.pages[0], (0.0, 0.0, 1.0, 1.0))
        self.assertEqual((got.chosen.id, [e.id for e in got.ladder]), ("F", ["F"]))

    def test_nothing_qualifying_picks_the_root(self):
        """A box over empty space: no element covers it or is filled by it, so the whole figure is chosen."""
        got = pick_element(CAL_PAGE, (0.8, 0.8, 0.1, 0.1))
        self.assertEqual((got.chosen.id, got.ladder), ("F", (ROOT,)))
        self.assertAlmostEqual(got.score, 1.0)

    def test_equal_boxes_go_to_the_deeper_then_the_earlier_element(self):
        """A child filling its parent exactly wins by depth; two siblings with one box go by map order."""
        parent = el("F/p", "F", (0.1, 0.1, 0.3, 0.3), src=(1, 9))
        child = el("F/p/c", "F/p", (0.1, 0.1, 0.3, 0.3), src=(2, 3))
        self.assertEqual(pick_element(page(parent, child), (0.2, 0.2, 0.05, 0.05)).chosen.id, "F/p/c")
        a = el("F/a", "F", (0.5, 0.5, 0.2, 0.2), src=(4, 5))
        b = el("F/b", "F", (0.5, 0.5, 0.2, 0.2), src=(6, 7))
        self.assertEqual(pick_element(page(a, b), (0.55, 0.55, 0.05, 0.05)).chosen.id, "F/a")
        self.assertEqual(pick_element(page(b, a), (0.55, 0.55, 0.05, 0.05)).chosen.id, "F/b")

    def test_a_smaller_box_wins_among_equally_deep_covering_elements(self):
        """Two overlapping siblings both cover the drag: the smaller one is the more specific answer."""
        big = el("F/big", "F", (0.1, 0.1, 0.6, 0.6))
        small = el("F/small", "F", (0.2, 0.2, 0.2, 0.2))
        self.assertEqual(pick_element(page(big, small), (0.25, 0.25, 0.05, 0.05)).chosen.id, "F/small")

    def test_an_element_without_source_is_picked_by_its_box_alone(self):
        """An element drawn without code (D7) competes like any other; the pick never looks at src."""
        got = pick_element(CAL_PAGE, (0.45, 0.25, 0.05, 0.05))
        self.assertEqual((got.chosen.id, got.chosen.src), ("F/cal/m08", None))

    def test_a_line_drag_counts_as_its_centre_point(self):
        """A drag with width but no height has no area: it is the point at its centre (0.3, 0.3)."""
        self.assertEqual(pick_element(CAL_PAGE, (0.25, 0.3, 0.1, 0.0)).chosen.id, "F/cal/m07")


class Ladder(unittest.TestCase):
    """The ladder: the chosen element, its ancestors nearest first up to LADDER_MAX rungs, then the root."""

    def test_the_ladder_climbs_from_the_element_to_the_root(self):
        """A click on the July cell gives the cell, the strip and the figure, named el, el2 and fig."""
        got = pick_element(CAL_PAGE, (0.3, 0.3, 0.0, 0.0))
        self.assertEqual([e.id for e in got.ladder], ["F/cal/m07", "F/cal", "F"])
        self.assertEqual(ladder_scopes(got.ladder), ("el", "el2", "fig"))

    def test_a_deep_chain_keeps_the_nearest_rungs_up_to_the_cap_then_the_root(self):
        """Twelve nested elements: the ladder keeps the chosen one and its seven nearest ancestors, then the root."""
        chain, parent = [], "F"
        for i in range(12):
            side = 0.8 - 0.05 * i
            e = el("F/%d" % i, parent, (0.1, 0.1, side, side))
            chain.append(e)
            parent = e.id
        got = pick_element(page(*chain), (0.12, 0.12, 0.0, 0.0))
        self.assertEqual(got.chosen.id, "F/11")
        self.assertEqual([e.id for e in got.ladder], ["F/%d" % i for i in range(11, 3, -1)] + ["F"])
        self.assertEqual(len(got.ladder), LADDER_MAX + 1)
        self.assertEqual(ladder_scopes(got.ladder), ("el", "el2", "el3", "el4", "el5", "el6", "el7", "el8", "fig"))

    def test_scopes_refuse_a_ladder_no_pick_makes(self):
        """An empty ladder, or one with more than LADDER_MAX element rungs, is a defect (ValueError)."""
        with self.assertRaises(ValueError):
            ladder_scopes(())
        with self.assertRaises(ValueError):
            ladder_scopes((ROOT,) * (LADDER_MAX + 2))


class Kind(unittest.TestCase):
    """element_kind: the pin kind of a rung."""

    def test_the_root_is_figure_and_an_element_is_its_part(self):
        """figure for the root; el:<part>, or el:? without a part, for any other element."""
        self.assertEqual(element_kind(ROOT, True), "figure")
        self.assertEqual(element_kind(JUL, False), "el:MonthCell")
        self.assertEqual(element_kind(el("F/x", "F", (0, 0, 1, 1)), False), "el:?")

    def test_an_empty_part_is_treated_like_no_part(self):
        """parse_map keeps an empty part as "" rather than None (P1a carry); element_kind must answer el:? for
        part == "" exactly as it does for part is None, not "el:"."""
        self.assertEqual(element_kind(el("F/x", "F", (0, 0, 1, 1), part=""), False), "el:?")

    def test_a_long_part_is_cut_so_the_kind_fits_a_pin(self):
        """A pin's kind is at most 80 characters, so a longer part is cut to 77."""
        self.assertEqual(element_kind(el("F/x", "F", (0, 0, 1, 1), part="P" * 200), False), "el:" + "P" * 77)


class Follow(unittest.TestCase):
    """follow_element: where a pinned element is on another build's map."""

    def test_the_same_place_within_eps_is_ok(self):
        """Same page, every component within FOLLOW_EPS: ok, with the element's box on this map."""
        got = follow_element(fmap(CAL_PAGE), "F/cal/m07", 1, (0.2, 0.2 + FOLLOW_EPS / 2, 0.2, 0.2))
        self.assertEqual(got, ElementFollow(1, JUL.frac, "ok"))

    def test_a_new_box_or_a_new_page_is_moved(self):
        """A box that changed, or the same box on another page, is moved to where the map puts it now."""
        moved = el("F/cal/m07", "F/cal", (0.25, 0.2, 0.2, 0.2), src=(88, 95))
        self.assertEqual(
            follow_element(fmap(page(CAL, moved, AUG)), "F/cal/m07", 1, JUL.frac),
            ElementFollow(1, moved.frac, "moved"),
        )
        self.assertEqual(
            follow_element(fmap(page(CAL, JUL, AUG, n=2)), "F/cal/m07", 1, JUL.frac),
            ElementFollow(2, JUL.frac, "moved"),
        )

    def test_an_id_gone_from_the_map_is_lost(self):
        """No element with that id on any page: lost, with no page or box."""
        self.assertEqual(
            follow_element(fmap(page(CAL, AUG)), "F/cal/m07", 1, JUL.frac), ElementFollow(None, None, "lost")
        )


# ---------------------------------------------------------------- properties on generated element trees


@st.composite
def pages(draw):
    """A page with a random element tree: each element's parent is an earlier element, boxes anywhere on the page."""
    count = draw(st.integers(min_value=0, max_value=12))
    elements = [ROOT]
    for i in range(count):
        parent = draw(st.sampled_from([e.id for e in elements]))
        x = draw(st.floats(0.0, 0.95))
        y = draw(st.floats(0.0, 0.95))
        w = draw(st.floats(0.01, 1.0 - x))
        h = draw(st.floats(0.01, 1.0 - y))
        elements.append(el("F/%d" % i, parent, (x, y, w, h), src=(1, 2)))
    return MapPage(1, "F", None, tuple(elements))


@st.composite
def drags(draw):
    """A drag inside the page, possibly without width or height (a click or a line)."""
    x = draw(st.floats(0.0, 1.0))
    y = draw(st.floats(0.0, 1.0))
    return (x, y, draw(st.floats(0.0, 1.0 - x)), draw(st.floats(0.0, 1.0 - y)))


def overlap(a, b):
    """The oracle's shared area of two boxes."""
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def cover(box, d):
    """The oracle's cover: the share of the drag inside box; a drag without area is its centre point."""
    if d[2] * d[3] <= 0:
        x, y = d[0] + d[2] / 2, d[1] + d[3] / 2
        return 1.0 if box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3] else 0.0
    return min(1.0, overlap(box, d) / (d[2] * d[3]))


def fill(box, d):
    """The oracle's fill: the share of box the drag covers."""
    return min(1.0, overlap(box, d) / (box[2] * box[3]))


def common_ancestor(pg, els):
    """The oracle's nearest common ancestor (an element counts as its own ancestor)."""
    chains = [[e.id, *(a.id for a in pg.ancestors(e))] for e in els]
    return pg.by_id(next(i for i in chains[0] if all(i in c for c in chains)))


class Properties(unittest.TestCase):
    """The rules hold for every generated page and drag."""

    @settings(deadline=None, max_examples=200)
    @given(pages(), drags())
    def test_the_choice_is_the_deepest_cover_else_the_common_ancestor_else_the_root(self, pg, d):
        """Total, and never another element: step 1 by depth, step 2 by the filled elements, step 3 the root;
        score is the chosen element's cover."""
        got = pick_element(pg, d)
        others = pg.elements[1:]
        covering = [e for e in others if cover(e.frac, d) >= COVER_MIN]
        if covering:
            self.assertGreaterEqual(cover(got.chosen.frac, d), COVER_MIN)
            self.assertEqual(len(pg.ancestors(got.chosen)), max(len(pg.ancestors(e)) for e in covering))
        else:
            filled = [e for e in others if fill(e.frac, d) >= FILL_MIN]
            want = common_ancestor(pg, filled) if filled else pg.root()
            self.assertEqual(got.chosen.id, want.id)
        self.assertEqual(got.score, cover(got.chosen.frac, d))

    @settings(deadline=None, max_examples=200)
    @given(pages(), drags())
    def test_the_ladder_climbs_parents_ends_with_the_root_and_names_match_its_length(self, pg, d):
        """First the choice, then parents one by one, at most LADDER_MAX of them, the root last; scopes el..fig."""
        got = pick_element(pg, d)
        root = pg.root()
        self.assertEqual(got.ladder[0].id, got.chosen.id)
        self.assertEqual(got.ladder[-1].id, root.id)
        self.assertLessEqual(len(got.ladder), LADDER_MAX + 1)
        rungs = got.ladder[:-1]
        for child, parent in zip(rungs, rungs[1:], strict=False):
            self.assertEqual(child.parent, parent.id)
        scopes = ladder_scopes(got.ladder)
        self.assertEqual(len(scopes), len(got.ladder))
        self.assertEqual(scopes, tuple("el" if i == 0 else "el%d" % (i + 1) for i in range(len(scopes) - 1)) + ("fig",))

    @settings(deadline=None, max_examples=100)
    @given(pages())
    def test_following_any_element_on_its_own_map_is_ok(self, pg):
        """Nothing moved: every element found at its own page and box."""
        m = FigureMap("figures.pdf", SHA, (pg,))
        for e in pg.elements:
            self.assertEqual(follow_element(m, e.id, 1, e.frac), ElementFollow(1, e.frac, "ok"))


if __name__ == "__main__":
    unittest.main()
