"""limn.mapping - the pure half of the position rules (range ladder, block expansion, anchors).

These tests call the module directly: no server, state directory, files or subprocess - that it stays pure, and
that the float environments come in as an argument (coding rule R5). The one exception is Ladder at the end: the
ladder on the fixture manuscript with the float environments server.py runs with.

Run: uv run pytest -q tests/test_mapping.py
"""

import ast
import unittest
from pathlib import Path

from limn import mapping
from limn.mapping import find_level

from helpers import TEX, Base, ps

MAPPING_PY = Path(mapping.__file__)
PURE_IMPORTS = {"__future__", "re", "collections.abc", "typing", "dataclasses", "limn.pins.shapes"}

# A table set inside running text (no blank lines around it), so the paragraph and the table differ.
TABLE_DOC = [
    "Intro paragraph line one.",
    "Intro line two.",
    "\\begin{table}",
    "\\begin{tabular}{l}",
    "cell alpha \\\\",
    "\\end{tabular}",
    "\\end{table}",
    "After the table.",
    "More text.",
]


class Purity(unittest.TestCase):
    """The module must not reach files, processes, the network or the server's globals."""

    def test_imports_only_pure_standard_modules(self):
        """A file, subprocess or HTTP import here would put an effect inside the domain (architecture.md stop signal)."""
        tree = ast.parse(MAPPING_PY.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertLessEqual(imported, PURE_IMPORTS)

    def test_does_not_read_server_configuration(self):
        """The old expand_block read C.envs; configuration now arrives as an argument."""
        source = MAPPING_PY.read_text(encoding="utf-8")
        self.assertNotIn("C.", source)
        self.assertNotIn("cur_doc(", source)


class AnchorMatching(unittest.TestCase):
    """find_line and anchor_holds match an anchor line by one rule (partial_key), and read offsets by anchor_offset."""

    def test_partial_key_is_the_first_40_characters_of_12_or_more(self):
        """A line of 12 characters or more may match by its first 40; a shorter one only whole."""
        self.assertIsNone(mapping.partial_key("x" * 11))
        self.assertEqual(mapping.partial_key("x" * 12), "x" * 12)
        self.assertEqual(mapping.partial_key("y" * 50), "y" * 40)

    def test_find_line_and_anchor_holds_accept_the_same_partial_match(self):
        """A long head found inside a longer line by find_line also holds there; a short one does neither."""
        long_head, short_head = "a" * 45, "short"
        nlines = ["intro", "a" * 40 + " and more", "short line"]
        self.assertEqual(mapping.find_line(nlines, long_head, 2), 2)
        self.assertTrue(mapping.anchor_holds({"head": long_head, "head_off": 0}, 2, nlines))
        self.assertIsNone(mapping.find_line(nlines, short_head, 3))
        self.assertFalse(mapping.anchor_holds({"head": short_head, "head_off": 0}, 3, nlines))

    def test_anchor_offset_accepts_only_an_int_in_0_to_9999(self):
        """A bool, a negative, 10000 or a string reads as 0 - as does a missing offset."""
        self.assertEqual(
            [mapping.anchor_offset(v) for v in (3, 9999, 10000, -1, True, "2", None)], [3, 9999, 0, 0, 0, 0, 0]
        )


class FloatEnvironments(unittest.TestCase):
    """expand_block/compute_levels expand a selection only into the environments they are given."""

    def test_selection_expands_to_a_listed_float(self):
        """A cell inside a table expands to the whole table when "table" is a float environment."""
        lo, hi, kind = mapping.expand_block(TABLE_DOC, 5, 5, ("table",))
        self.assertEqual((lo, hi, kind), (3, 7, "float"))

    def test_selection_does_not_expand_to_an_unlisted_environment(self):
        """Without "table" in envs the same cell expands to its paragraph instead."""
        self.assertEqual(mapping.expand_block(TABLE_DOC, 5, 5, ("figure",)), (1, 9, "paragraph"))

    def test_ladder_default_follows_the_given_environments(self):
        """compute_levels passes envs through: the default is the table only when "table" is listed."""
        with_table = mapping.compute_levels(TABLE_DOC, 5, 5, ("table",))
        without = mapping.compute_levels(TABLE_DOC, 5, 5, ("figure",))
        self.assertEqual((with_table["default_level"], with_table["lo"], with_table["hi"]), ("env", 3, 7))
        self.assertEqual((without["default_level"], without["lo"], without["hi"]), ("para", 5, 5))


# ---------------------------------------------------------------- through server.py's wiring
#
# The range ladder on the fixture manuscript with the server's default float environments. These classes load
# server.py (helpers.ps) and drive the module through its bindings; the tests above call the module on its own.


class Ladder(Base):
    def test_para_stays_inside_env(self):
        lines = TEX.splitlines()
        lad = mapping.compute_levels(lines, 14, 14, ps.C.envs)  # a cell inside the table
        para = find_level(lad["levels"], "para")
        self.assertGreaterEqual(para["lo"], 13)
        self.assertLessEqual(para["hi"], 15)

    def test_para_stops_at_subsection(self):
        lines = TEX.splitlines()
        # the line after the table — the next line is \subsection
        lad = mapping.compute_levels(lines, 17, 17, ps.C.envs)
        para = find_level(lad["levels"], "para")
        self.assertEqual(para["hi"], 17)


if __name__ == "__main__":
    unittest.main()
