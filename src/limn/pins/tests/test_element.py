"""limn.pins.element - a figure pin's `el`: its stored shape (is_element_record), the value readers lift from it
(element_of) and the shape it is written in (PinElement.to_record), on values alone.

Run: uv run pytest -q src/limn/pins/tests/test_element.py
"""

import unittest

from hypothesis import given, strategies as st

from limn.pins.element import ElementImpl, PinElement, element_of, is_element_record

FULL = PinElement(
    "B2/m07", ("B2", "B2/m07"), "7월", "MonthCell", ElementImpl("lib/c.py", 410, 470), (0.47, 0.18, 0.07, 0.12)
)


class Shape(unittest.TestCase):
    """The record an element is written as, and what reads back from a record."""

    def test_the_record_is_id_and_path_then_only_the_set_fields_in_order(self):
        """id and path always; label, part, impl and frac only when set, in that order."""
        self.assertEqual(list(FULL.to_record()), ["id", "path", "label", "part", "impl", "frac"])
        self.assertEqual(FULL.to_record()["impl"], {"file": "lib/c.py", "lo": 410, "hi": 470})
        self.assertEqual(FULL.to_record()["frac"], [0.47, 0.18, 0.07, 0.12])
        self.assertEqual(PinElement("B2", ("B2",)).to_record(), {"id": "B2", "path": ["B2"]})

    def test_a_record_reads_back_as_the_same_element(self):
        """element_of undoes to_record; a null label reads as no label."""
        self.assertEqual(element_of(FULL.to_record()), FULL)
        self.assertEqual(element_of({"id": "B2", "path": ["B2"], "label": None}), PinElement("B2", ("B2",)))

    def test_what_is_not_an_element_reads_as_none(self):
        """Missing, not an object, an empty id, a non-string path entry or a three-number frac is no element."""
        for v in (
            None,
            "B2",
            {"id": "", "path": []},
            {"id": "B2", "path": ["B2", 1]},
            {"id": "B2", "path": ["B2"], "frac": [0, 0, 1]},
        ):
            with self.subTest(v=v):
                self.assertFalse(is_element_record(v))
                self.assertIsNone(element_of(v))

    @given(
        st.builds(
            PinElement,
            id=st.text(min_size=1, max_size=20),
            path=st.lists(st.text(max_size=20), max_size=5).map(tuple),
            label=st.none() | st.text(max_size=20),
            part=st.none() | st.text(max_size=20),
            impl=st.none() | st.builds(ElementImpl, st.text(max_size=20), st.integers(), st.integers()),
            frac=st.none() | st.tuples(st.floats(0, 1), st.floats(0, 1), st.floats(0, 1), st.floats(0, 1)),
        )
    )
    def test_every_element_round_trips_through_its_record(self, el):
        """Writing an element and reading it back gives the same value, and the record passes the store's check."""
        rec = el.to_record()
        self.assertTrue(is_element_record(rec))
        self.assertEqual(element_of(rec), el)


class NonFiniteFrac(unittest.TestCase):
    """A stored frac the shape check accepts (is_num asks only int-or-float, not finite or in range) but that is
    not a usable box: element_of must lift the rest of the element and drop frac, never raise. Task 8's
    pins_payload and Task 9's render.py call element_of on every open row before any write, so a raise here would
    break GET /api/pins and every pin write for an unrelated line."""

    def test_a_frac_with_nan_is_dropped_without_raising(self):
        """A NaN coordinate: is_element_record still trusts the shape; element_of lifts the element without frac."""
        rec = {"id": "B2", "path": ["B2"], "frac": [float("nan"), 0.1, 0.1, 0.1]}
        self.assertTrue(is_element_record(rec))
        self.assertEqual(element_of(rec), PinElement("B2", ("B2",)))

    def test_a_frac_with_infinity_is_dropped_without_raising(self):
        """An Infinity coordinate: is_element_record still trusts the shape; element_of lifts without frac."""
        rec = {"id": "B2", "path": ["B2"], "frac": [0.1, float("inf"), 0.1, 0.1]}
        self.assertTrue(is_element_record(rec))
        self.assertEqual(element_of(rec), PinElement("B2", ("B2",)))

    def test_a_frac_with_an_oversized_integer_is_dropped_without_raising(self):
        """A 400-digit int coordinate (is_num accepts any int, not just ones float() can hold): is_element_record
        still trusts the shape; element_of lifts without frac instead of raising OverflowError."""
        rec = {"id": "B2", "path": ["B2"], "frac": [0.1, 0.1, 10**400, 0.1]}
        self.assertTrue(is_element_record(rec))
        self.assertEqual(element_of(rec), PinElement("B2", ("B2",)))


if __name__ == "__main__":
    unittest.main()
