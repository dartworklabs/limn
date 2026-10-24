"""GET /api/snippet?file=&lo=&hi=&text=1: the range's exact lines, which a suggested edit's base must be
(docs/adr/0020-suggested-edit-pins.md D1) - added only when asked and only for a range of at most 80 lines, every
other field as without it. Through the handler, on a real manuscript.

Run: uv run pytest -q src/limn/pins/location/tests/test_snippet_text.py
"""

import json

from limn.pins.editing.values import SUGGEST_LINES_MAX

from helpers import Base, req, split_resp


class SnippetText(Base):
    """The fixture manuscript, plus long.tex (100 numbered lines, the 7th with a CRLF ending)."""

    def setUp(self):
        """Write long.tex beside main.tex."""
        super().setUp()
        self.long = self.src / "long.tex"
        self.long.write_bytes(
            "".join("line %d%s" % (n, "\r\n" if n == 7 else "\n") for n in range(1, 101)).encode("utf-8")
        )

    def snippet(self, query):
        """GET /api/snippet?<query> as the local agent: the parsed body of a 200."""
        code, _, out = split_resp(self.talk(req("GET", "/api/snippet?" + query)))
        self.assertEqual(code, 200, out)
        return json.loads(out)

    def test_text_is_the_exact_lines_unnumbered(self):
        """Lines 4-5 of main.tex joined with a newline, no trailing one; snippet stays the numbered view."""
        got = self.snippet("file=main.tex&lo=4&hi=5&text=1")
        self.assertEqual(got["text"], "First paragraph line one about rarewordalpha.\nFirst paragraph line two.")
        self.assertIn("    4  First paragraph", got["snippet"])

    def test_text_has_no_carriage_return(self):
        """A CRLF line reads without its CR, as a suggestion's base is compared."""
        self.assertEqual(self.snippet("file=long.tex&lo=6&hi=8&text=1")["text"], "line 6\nline 7\nline 8")

    def test_every_other_field_is_as_without_text(self):
        """With and without text=1 (and with levels=1) the answers differ only by the trailing text field."""
        for extra in ("", "&levels=1"):
            with self.subTest(extra=extra):
                plain = self.snippet("file=main.tex&lo=4&hi=5" + extra)
                with_text = self.snippet("file=main.tex&lo=4&hi=5&text=1" + extra)
                self.assertEqual(list(with_text)[-1], "text")
                self.assertEqual({k: v for k, v in with_text.items() if k != "text"}, plain)
                self.assertNotIn("text", plain)

    def test_text_is_given_up_to_eighty_lines_only(self):
        """80 lines carry text; 81 do not, and the rest of the answer is unchanged; text=0 never does."""
        self.assertEqual(self.snippet("file=long.tex&lo=1&hi=%d&text=1" % SUGGEST_LINES_MAX)["text"].count("\n"), 79)
        over = self.snippet("file=long.tex&lo=1&hi=%d&text=1" % (SUGGEST_LINES_MAX + 1))
        self.assertNotIn("text", over)
        self.assertEqual(over, self.snippet("file=long.tex&lo=1&hi=%d" % (SUGGEST_LINES_MAX + 1)))
        self.assertNotIn("text", self.snippet("file=main.tex&lo=4&hi=5&text=0"))
