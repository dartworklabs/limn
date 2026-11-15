"""SyncTeX's forward lookup: where a source line is printed (source.synctex_view).

Run: uv run pytest -q src/limn/pins/location/tests/test_forward.py
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from limn.pins.location import mapping, source as pick_source

from helpers import needs_tex


class SynctexView(unittest.TestCase):
    """The command asked and how its output is read."""

    def test_synctex_view_asks_by_line_and_column_zero_and_reads_every_page_record(self):
        """The input is relative to the build root; every Page: record with its four numbers counts."""
        out = (
            "SyncTeX result begin\nOutput:main.pdf\nPage:14\nx:1\ny:2\nh:133.77\nv:349.81\nW:343.71\nH:8.86\n"
            "Page:14\nh:1\nv:2\nW:3\nH:4\n"
        )
        with mock.patch.object(pick_source.subprocess, "run", return_value=mock.Mock(stdout=out)) as run:
            got = pick_source.synctex_view(Path("/b/main.pdf"), 500, "sections/intro.tex")
        self.assertEqual(run.call_args[0][0][:4], ["synctex", "view", "-i", "500:0:sections/intro.tex"])
        self.assertEqual(got, [(14, 133.77, 349.81, 343.71, 8.86), (14, 1.0, 2.0, 3.0, 4.0)])

    def test_synctex_view_is_none_when_the_tool_is_missing_times_out_or_gives_no_page(self):
        """No answer is None, never an empty list."""
        for boom in (FileNotFoundError(), subprocess.TimeoutExpired("synctex", 10)):
            with mock.patch.object(pick_source.subprocess, "run", side_effect=boom):
                self.assertIsNone(pick_source.synctex_view(Path("/b/main.pdf"), 1, "main.tex"))
        with mock.patch.object(pick_source.subprocess, "run", return_value=mock.Mock(stdout="SyncTeX result begin\n")):
            self.assertIsNone(pick_source.synctex_view(Path("/b/main.pdf"), 1, "main.tex"))

    def test_synctex_view_drops_a_record_missing_one_of_its_four_numbers(self):
        """A Page: record without W: is not a box."""
        out = "Page:1\nh:1\nv:2\nH:4\nPage:2\nh:1\nv:2\nW:3\nH:4\n"
        with mock.patch.object(pick_source.subprocess, "run", return_value=mock.Mock(stdout=out)):
            self.assertEqual(pick_source.synctex_view(Path("/b/main.pdf"), 1, "main.tex"), [(2, 1.0, 2.0, 3.0, 4.0)])


TEX = r"""\documentclass{article}
\begin{document}
First paragraph line one of the body text,
which runs on and on for a while,
and ends here.

\begin{table}[t]
\centering
\begin{tabular}{ll}
alpha & one \\
beta & two \\
\end{tabular}
\end{table}

Last paragraph after the table.
\end{document}
"""


class RealSynctex(unittest.TestCase):
    """The real binary on a built page."""

    @needs_tex("pdflatex", "synctex")
    def test_a_body_line_and_a_table_row_get_different_boxes_on_page_one(self):
        """The body line is a full-width strip; a tabular row is inside the (narrower) table box."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(TEX, encoding="utf-8")
            subprocess.run(
                ["pdflatex", "-synctex=1", "-interaction=nonstopmode", "main.tex"],
                cwd=root,
                capture_output=True,
                timeout=120,
                check=True,
            )
            body = mapping.view_box(pick_source.synctex_view(root / "main.pdf", 3, "main.tex") or [], 1)
            row = mapping.view_box(pick_source.synctex_view(root / "main.pdf", 9, "main.tex") or [], 1)
        self.assertIsNotNone(body)
        self.assertIsNotNone(row)
        self.assertEqual((body.page, row.page), (1, 1))
        self.assertNotEqual(body.box, row.box)
