"""The instance shell and the server register the same text suffixes (ADR-0029 D2), and take the same --main.

`limn add`/`limn doc add` check a --doc path before the config is written (instance_documents.sh), and the server
checks it again at startup (limn.administration.serve_documents.parse_doc_arg). The shell keeps its own copy of the
list, as it does of the other suffixes; this test keeps the two copies equal, so a suffix the server takes is never
refused by the shell or the other way round.
"""

import re
import subprocess
import unittest
from pathlib import Path

from limn.administration.serve_documents import LATEX_OWN_SUFFIXES
from limn.runtime.documents import TEXT_SUFFIXES, name_suffix

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


# File names whose suffix Python's Path.suffix reads differently across versions, or that sit at a rule's edge.
NAMES = (
    ".py",
    "..py",
    "...py",
    ".hidden.py",
    "a.",
    "a.py",
    "plot.PY",
    "name.tar.gz",
    "Figures.LIMNMAP.JSON",
    "refs.Bib",
    "paper.sty",
    ".",
    "..",
    "noext",
    "dir/.py",
    "dir/notes.TXT",
    "a..py",
)


class SuffixReading(unittest.TestCase):
    """The shell and the server read a file name's suffix, and so a --doc's kind and a --main's refusal, the same way."""

    def shell(self, script: str) -> list[str]:
        """Run script after sourcing instance_documents.sh (with a stub die) and return its output lines."""
        out = subprocess.run(
            ["bash", "-c", 'die() { echo "die $*"; exit 1; }; source "$1"; ' + script, "bash", str(SHELL)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return out.stdout.splitlines()

    def test_name_suffix_reads_dotfiles_and_trailing_dots_alike_on_every_python(self):
        """A dotfile has no suffix however many dots lead it; a trailing dot gives none; otherwise the last dot's."""
        want = {
            ".py": "",
            "..py": "",
            "...py": "",
            ".hidden.py": ".py",
            "a.": "",
            "a.py": ".py",
            "plot.PY": ".py",
            "name.tar.gz": ".gz",
            "Figures.LIMNMAP.JSON": ".json",
            ".": "",
            "..": "",
            "noext": "",
            "a..py": ".py",
        }
        for name, suf in want.items():
            with self.subTest(name=name):
                self.assertEqual(name_suffix(name), suf)

    def test_the_shell_reads_every_name_as_the_server_does(self):
        """For every name: the shell's name_suffix is the server's, doc_is_text is the server's --doc text kind, and
        main_is_text_doc / main_is_figure_map are pick_documents' refusals."""
        script = (
            "for n in " + " ".join("'%s'" % n for n in NAMES) + '; do printf "%s|%s|%s|%s|%s\\n" "$n" '
            '"$(name_suffix "$n")" "$(doc_is_text "$n" && echo 1)" "$(main_is_text_doc "$n" && echo 1)" '
            '"$(main_is_figure_map "$n" && echo 1)"; done'
        )
        from limn.administration.serve_documents import LATEX_OWN_SUFFIXES
        from limn.runtime.documents import MAP_SUFFIX

        for line in self.shell(script):
            name, suf, text, main_text, main_map = line.split("|")
            is_map = name.lower().endswith(MAP_SUFFIX)
            with self.subTest(name=name):
                self.assertEqual(suf, name_suffix(name))
                self.assertEqual(text == "1", not is_map and name_suffix(name) in TEXT_SUFFIXES)
                self.assertEqual(main_text == "1", name_suffix(name) in TEXT_SUFFIXES - LATEX_OWN_SUFFIXES)
                self.assertEqual(main_map == "1", is_map)


if __name__ == "__main__":
    unittest.main()
