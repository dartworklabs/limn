"""A line pin's current mark in GET /api/pins: the cached answer of the build on screen, in the same `mark` and
`mark_page` fields a figure pin uses, computed on every read and never stored (docs/handbook/api.md).

Run: uv run pytest -q src/limn/pins/listing/tests/test_line_marks.py
"""

import unittest

from limn.pins.listing import projection as view
from limn.pins.location.position import LineMark

from helpers import ps
from helpers_access import ALICE, AccessBase

MARK = LineMark(3, (0.1, 0.2, 0.3, 0.04))


class LineMarksProjection(unittest.TestCase):
    """The pure part."""

    def test_a_line_pins_record_carries_the_marks_the_build_found(self):
        got = view.line_marks({"lo": 10, "hi": 12}, MARK)
        self.assertEqual(got, {"mark": [0.1, 0.2, 0.3, 0.04], "mark_page": 3})

    def test_a_line_pin_without_a_mark_and_a_figure_pin_get_nothing_from_line_marks(self):
        self.assertEqual(view.line_marks({"lo": 10, "hi": 12}, None), {})
        self.assertEqual(view.line_marks({"lo": 10, "hi": 12, "el": {"id": "x"}}, MARK), {})

    def test_any_el_makes_it_a_figure_pin_even_a_malformed_one(self):
        self.assertEqual(view.line_marks({"lo": 10, "hi": 12, "el": "junk"}, MARK), {})
        self.assertEqual(view.line_marks({"lo": 10, "hi": 12, "el": None}, MARK)["mark_page"], 3)

    def test_the_default_lookup_knows_no_mark(self):
        self.assertIsNone(view.no_line_maps("ms")(1))


class LineMarksPayload(unittest.TestCase):
    """pins_payload asks the lookup once per listed line pin, never for a figure pin."""

    def rows(self):
        return [
            {"id": 1, "lo": 10, "hi": 12, "file": "a.tex"},
            {"id": 2, "lo": 4, "hi": 4, "file": "a.tex", "el": {"id": "x", "label": "x"}},
        ]

    def test_the_lookup_is_asked_by_document_and_pin_and_only_for_a_pin_without_an_element(self):
        asked = []

        def line_map(key):
            return lambda pid: asked.append((key, pid)) or MARK

        out = view.pins_payload(self.rows(), True, {}, dict, lambda r: "ms", lambda k: None, 0.0, line_map=line_map)
        self.assertEqual(asked, [("ms", 1)])
        self.assertEqual(out[0]["mark"], [0.1, 0.2, 0.3, 0.04])
        self.assertEqual(out[0]["mark_page"], 3)
        self.assertNotIn("mark", out[1])

    def test_the_lookup_is_bound_once_per_document_however_many_line_pins_it_lists(self):
        bound = []

        def line_map(key):
            bound.append(key)
            return lambda pid: MARK

        rows = [{"id": i, "lo": i, "hi": i, "file": "a.tex"} for i in range(1, 6)]
        rows.append({"id": 9, "lo": 1, "hi": 1, "file": "b.tex"})
        view.pins_payload(
            rows,
            True,
            {},
            dict,
            lambda r: "ms" if r["file"] == "a.tex" else "fig",
            lambda k: None,
            0.0,
            line_map=line_map,
        )
        self.assertEqual(bound, ["ms", "fig"])


class LineMarksOverHttp(AccessBase):
    """Through the server: a cached mark shows up, and a read changes nothing stored."""

    def listed(self):
        code, body = self.call("GET", "/api/pins", headers=ALICE)
        self.assertEqual(code, 200, body)
        return {p["id"]: p for p in body}

    def stored(self, pid):
        with ps.APP.RT.pin_lock:
            return next(p.record for p in ps.APP.read_pins()[0] if p.record["id"] == pid)

    def test_a_cached_mark_is_listed_and_a_pin_without_one_is_not(self):
        a, b = self.add(4, 5), self.add(8, 9)
        doc = ps.APP.docs[0]
        build = ps.APP.build_view.heading(doc).build
        ps.APP.line_marks.put(doc.key, build, a, 4, 5, MARK)
        got = self.listed()
        self.assertEqual((got[a]["mark"], got[a]["mark_page"]), ([0.1, 0.2, 0.3, 0.04], 3))
        self.assertNotIn("mark", got[b])

    def test_a_get_resolves_the_build_on_screen_once_per_document_not_once_per_pin(self):
        ids = [self.add(4 + i, 4 + i) for i in range(4)]
        heading = ps.APP.build_view.heading
        calls = []

        def counting(doc):
            calls.append(doc.key)
            return heading(doc)

        # the build bundle is a frozen dataclass, so its field is swapped past __setattr__ and put back
        object.__setattr__(ps.APP.build_view, "heading", counting)
        self.addCleanup(object.__setattr__, ps.APP.build_view, "heading", heading)
        self.assertEqual(len(self.listed()), len(ids))
        self.assertEqual(calls.count(ps.APP.docs[0].key), 1)

    def test_a_mark_of_another_build_is_not_shown(self):
        a = self.add(4, 5)
        doc = ps.APP.docs[0]
        ps.APP.line_marks.put(doc.key, "some-other-build", a, 4, 5, MARK)
        self.assertNotIn("mark", self.listed()[a])

    def test_the_payload_leaves_the_record_and_rev_untouched(self):
        a = self.add(4, 5)
        doc = ps.APP.docs[0]
        ps.APP.line_marks.put(doc.key, ps.APP.build_view.heading(doc).build, a, 4, 5, MARK)
        before = self.stored(a)
        rev = before["rev"]
        self.assertIn("mark", self.listed()[a])
        after = self.stored(a)
        self.assertEqual(after["rev"], rev)
        self.assertNotIn("mark", after)
        self.assertNotIn("mark_page", after)
        self.assertEqual(after, before)
