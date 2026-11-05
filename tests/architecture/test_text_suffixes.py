"""The instance shell and the server register the same text suffixes (ADR-0029 D2), and take the same --main.

`limn add`/`limn doc add` check a --doc path before the config is written (instance_documents.sh), and the server
checks it again at startup (limn.administration.serve_documents.parse_doc_arg). The shell keeps its own copy of the
list, as it does of the other suffixes; this test keeps the two copies equal, so a suffix the server takes is never
refused by the shell or the other way round.
"""

import re
import unittest
from pathlib import Path

from limn.administration.serve_documents import LATEX_OWN_SUFFIXES
from limn.runtime.documents import TEXT_SUFFIXES

SHELL = Path(__file__).resolve().parents[2] / "src" / "limn" / "administration" / "instance_documents.sh"


class TextSuffixes(unittest.TestCase):
    """The shell's copy of the text suffixes against the server's."""

    def test_the_shell_list_is_the_server_list(self):
        """DOC_TEXT_SUFFIXES in the shell, split on spaces, is TEXT_SUFFIXES: lowercase, each once."""
        m = re.search(r'^DOC_TEXT_SUFFIXES="([^"]*)"$', SHELL.read_text(encoding="utf-8"), re.M)
        assert m is not None, "instance_documents.sh has no DOC_TEXT_SUFFIXES line"
        listed = m.group(1).split()
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(set(listed), TEXT_SUFFIXES)
        self.assertTrue(all(s == s.lower() and s.startswith(".") for s in TEXT_SUFFIXES))

    def test_the_shells_latex_own_suffixes_are_the_servers(self):
        """MAIN_LATEX_OWN_SUFFIXES in the shell (what `limn add --main` still takes among the text suffixes) is
        serve_documents.LATEX_OWN_SUFFIXES, and every one of them is a text suffix."""
        m = re.search(r'^MAIN_LATEX_OWN_SUFFIXES="([^"]*)"$', SHELL.read_text(encoding="utf-8"), re.M)
        assert m is not None, "instance_documents.sh has no MAIN_LATEX_OWN_SUFFIXES line"
        listed = m.group(1).split()
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(set(listed), LATEX_OWN_SUFFIXES)
        self.assertLessEqual(LATEX_OWN_SUFFIXES, TEXT_SUFFIXES)


if __name__ == "__main__":
    unittest.main()
