"""The text surface's pure rules: the ladder over a text document's lines, the hang of a wrapped line, the characters
marked by name (docs/adr/0029-text-documents.md D3, D5; docs/superpowers/specs/2026-11-05-text-documents.md §결정).

The served txCols, txHang, txParagraph, txIndentBlock, txChars and txPlain run under node. The browser behaviour - the
DOM, picks, marks - is a browser test of the real implementation.

Run: uv run pytest -q src/limn/viewer/tests/test_text_surface.py
"""

import json
import shutil
import unittest

from helpers import extract_js_fn, run_node

FNS = ["txCols", "txHang", "txParagraph", "txIndentBlock", "txCharName", "txChars", "txPlain"]
CONSTS = (
    "const TX_TAB=4;const TX_HANG_MAX=16;const TX_CLOSER=/^([\\]\\)}]|end\\b|fi\\b|done\\b|esac\\b)/;"
    "const TX_HIDDEN=/[\\u0000-\\u0008\\u000e-\\u001f\\u007f-\\u009f\\u061c\\u200b\\u200e\\u200f\\u202a-\\u202e"
    "\\u2060-\\u2064\\u2066-\\u2069\\ufeff]/g;"
)

PY = [
    "import os",  # 1
    "",  # 2
    "class Panel:",  # 3
    '    """Doc."""',  # 4
    "",  # 5
    "    def label(self):",  # 6
    "        x = 1",  # 7
    "        return x",  # 8
    "",  # 9
    "def draw(ax):",  # 10
    "    ax.plot(",  # 11
    "        1,",  # 12
    "    )",  # 13
    "    ax.grid()",  # 14
    "",  # 15
    "main()",  # 16
]
BIB = ["@article{a,", "  title = {T},", "}", "", "@book{b,", "  title = {U},", "}"]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TextSurfacePure(unittest.TestCase):
    """The ladder, hang and marked characters of a text document, under node."""

    def run_js(self, body: str):
        """Evaluate body (an expression) with the served functions and the constants they read; its JSON value."""
        src = CONSTS + "\n".join(extract_js_fn(f) for f in FNS) + "\nconsole.log(JSON.stringify(%s));" % body
        return json.loads(run_node(src))

    def test_columns_and_hang(self):
        """Tabs advance to the next multiple of four; a blank line has no indentation. The hang is the indentation,
        rounded down to a tab stop only on a line holding a tab, and at most sixteen."""
        got = self.run_js(
            "['abc','  a','\\ta',' \\ta','   ','\\t\\t\\t\\t\\tx','      x'].map(l=>[txCols(l),txHang(l)])"
        )
        self.assertEqual(got, [[0, 0], [2, 2], [4, 4], [4, 4], [-1, 0], [20, 16], [6, 6]])

    def test_paragraph_widens_to_blank_lines_and_counts_runs(self):
        """A line's paragraph is its run of non-blank lines; a range over a blank line meets two."""
        lines = json.dumps(PY)
        got = self.run_js("[[7,7],[2,2],[8,10],[16,16]].map(([a,b])=>txParagraph(%s,a,b))" % lines)
        self.assertEqual(
            got, [{"lo": 6, "hi": 8, "n": 1}, None, {"lo": 6, "hi": 14, "n": 2}, {"lo": 16, "hi": 16, "n": 1}]
        )

    def test_indent_block_heads_or_encloses(self):
        """A header line takes the body it heads; a body line takes the block it stands in, closing bracket included;
        a top-level line that heads nothing has no block."""
        lines = json.dumps(PY)
        got = self.run_js(
            "[[6,6],[7,7],[12,12],[11,11],[3,3],[1,1],[16,16]].map(([a,b])=>txIndentBlock(%s,a,b))" % lines
        )
        self.assertEqual(
            got,
            [
                {"lo": 6, "hi": 8, "title": "def label(self):"},
                {"lo": 6, "hi": 8, "title": "def label(self):"},
                {"lo": 11, "hi": 13, "title": "ax.plot("},
                {"lo": 11, "hi": 13, "title": "ax.plot("},
                {"lo": 3, "hi": 8, "title": "class Panel:"},
                None,
                None,
            ],
        )

    def test_a_bib_entry_is_one_block(self):
        """An entry's first line heads its fields, and its closing brace at the header's depth belongs to it."""
        got = self.run_js("[1,2].map(n=>txIndentBlock(%s,n,n))" % json.dumps(BIB))
        self.assertEqual(got, [{"lo": 1, "hi": 3, "title": "@article{a,"}] * 2)

    def test_hidden_characters_are_found_and_named(self):
        """Bidirectional controls, a zero-width space and a control character are marked, a leading byte-order mark of
        line 1 is not, and the zero-width joiner never is; the snippet names each in angle brackets."""
        got = self.run_js(
            "[txChars('a\\u202eb\\u2066c'),txChars('\\ufeffx',true),txChars('\\ufeffx',false),"
            "txChars('x\\u200dy\\u200bz\\u001bw'),txPlain('if a\\u202e b')]"
        )
        self.assertEqual(
            got,
            [
                [{"at": 1, "ch": "\u202e"}, {"at": 3, "ch": "\u2066"}],
                [],
                [{"at": 0, "ch": "\ufeff"}],
                [{"at": 3, "ch": "\u200b"}, {"at": 5, "ch": "\u001b"}],
                "if a\u27e8U+202E\u27e9 b",
            ],
        )


if __name__ == "__main__":
    unittest.main()
