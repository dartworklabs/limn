"""The viewer and pins.md name the same characters as hiding or reordering text (ADR-0029 D5, D7).

The viewer marks them wherever it shows a source's or a suggestion's text (src/limn/viewer/js/hidden-chars.js
CC_RANGES), and pins.md flags a suggestion that adds one to its base (limn.pins.suggestion.HIDDEN_RANGES). The two
languages keep their own copy of the table; this test keeps the copies equal, and checks the Python one over every code
point, so a character the person is warned about is the one the agent is told to confirm.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from limn.pins.suggestion import HIDDEN_RANGES, Suggestion, hidden_added

PART = Path(__file__).resolve().parents[2] / "src" / "limn" / "viewer" / "js" / "hidden-chars.js"


class HiddenCharacterTables(unittest.TestCase):
    """CC_RANGES against HIDDEN_RANGES."""

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_viewer_table_is_the_pins_md_table(self):
        """CC_RANGES, evaluated as the page evaluates it, is HIDDEN_RANGES range for range."""
        js = PART.read_text(encoding="utf-8") + "\nconsole.log(JSON.stringify(CC_RANGES));"
        out = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, check=True).stdout
        self.assertEqual([tuple(r) for r in json.loads(out)], list(HIDDEN_RANGES))

    def test_the_table_is_sorted_disjoint_and_names_every_code_point_alike(self):
        """The ranges ascend without overlap, and hidden_added counts a code point exactly when a range holds it - a
        supplementary one as one character."""
        flat = [c for r in HIDDEN_RANGES for c in r]
        self.assertEqual(flat, sorted(flat))
        self.assertTrue(all(a < b for (_, a), (b, _) in zip(HIDDEN_RANGES, HIDDEN_RANGES[1:], strict=False)))
        inside = {c for a, b in HIDDEN_RANGES for c in range(a, b + 1)}
        text = "".join(chr(c) for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF and c != 0x0A)
        got = {int(name[2:], 16) for name, _ in hidden_added(Suggestion("", text.replace("\r", "")))}
        self.assertEqual(got, inside - {0x0D})


if __name__ == "__main__":
    unittest.main()
