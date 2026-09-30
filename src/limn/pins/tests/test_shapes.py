"""limn.platform.values: the one rule for "a JSON integer" and "a JSON number" that every reader of stored data asks.

Run: uv run pytest -q src/limn/pins/tests/test_shapes.py
"""

import ast
import unittest
from pathlib import Path

from limn.platform import values as shapes
from limn.platform.values import is_finite_num, is_int, is_num


class Shapes(unittest.TestCase):
    """A bool is never a number, although Python's bool is an int."""

    def test_is_int_takes_ints_only(self):
        """0, negative and large ints pass; a bool, a float (even 1.0), a string and None do not."""
        self.assertEqual([is_int(v) for v in (0, -3, 2**60)], [True, True, True])
        self.assertEqual([is_int(v) for v in (True, False, 1.0, "1", None)], [False] * 5)

    def test_is_num_takes_ints_and_floats(self):
        """Ints and floats (also nan and inf, as json.loads can give) pass; a bool, a string and None do not."""
        self.assertEqual([is_num(v) for v in (0, 1.5, float("nan"), float("inf"))], [True] * 4)
        self.assertEqual([is_num(v) for v in (True, "1", None, [1])], [False] * 4)

    def test_finite_number_refuses_an_integer_too_large_for_a_float(self):
        """An untrusted JSON integer may exceed float range without crashing parsers or domain constructors."""
        self.assertTrue(is_finite_num(2.5))
        self.assertEqual([is_finite_num(v) for v in (True, float("inf"), float("nan"), 10**400)], [False] * 4)

    def test_imports_only_pure_standard_library_modules(self):
        """Any layer may use these shape predicates without importing I/O or application modules."""
        tree = ast.parse(Path(shapes.__file__).read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imported, {"math", "typing"})


if __name__ == "__main__":
    unittest.main()
