"""limn.mapping - the pure half of the position rules (range ladder, block expansion, anchors).

These tests call the module directly: no server, state directory, files or subprocess. The ladder's behavior
on real manuscripts is also pinned through the handler in test_server.py; here the module's own contract is
checked - that it stays pure, and that the float environments come in as an argument (coding rule R5).

Run: uv run pytest -q tests/test_mapping.py
"""
import ast
import unittest
from pathlib import Path

from limn import mapping

MAPPING_PY = Path(mapping.__file__)
PURE_IMPORTS = {"__future__", "re", "collections.abc", "typing", "dataclasses"}

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


if __name__ == "__main__":
    unittest.main()
