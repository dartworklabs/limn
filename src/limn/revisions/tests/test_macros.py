"""limn.revisions.macros: which of a document's own commands a comparison asks latexdiff to mark inside (issue #162).

A command named here gets latexdiff's markup inside its last argument, so a wrong "yes" breaks the comparison's compile
(markup inside a label, a file name, a length or math) and a wrong "no" only keeps latexdiff's opaque-token default.
The positive cases are the shapes reply letters and manuscripts use; the negative ones are the arguments that are not
text. The definitions are synthetic.
"""

import re
import string

import pytest
from hypothesis import given, strategies as st

from limn.revisions.macros import TEXT_COMMANDS, text_macros

PREAMBLE = "\\documentclass{article}\n%s\n\\begin{document}\nBody.\n\\end{document}\n"


@pytest.mark.parametrize(
    ("definition", "names"),
    [
        ("\\newcommand{\\reply}[1]{\\par\\noindent\\textbf{Reply:}\\ \\normalsize #1\\par}", ("reply",)),
        ("\\newcommand\\reply[1]{#1}", ("reply",)),
        ("\\renewcommand*{\\reply}[1]{\\textcolor{blue}{#1}}", ("reply",)),
        ("\\providecommand{\\note}[2][general]{\\emph{#2}}", ("note",)),
        ("\\newcommand{\\revised}[1]{%\n  \\begin{quote}\\itshape\n  \\color{black}#1\n  \\end{quote}}", ("revised",)),
        ("\\newcommand{\\flag}[1]{\\textcolor{red!70!black}{\\textsf{[Flag: #1]}}}", ("flag",)),
        ("\\newcommand{\\pair}[2]{\\label{#1}#2}", ("pair",)),
        ("\\newcommand{\\share}[1]{#1 per cent\\%}", ("share",)),
        ("\\newcommand{\\aside}[1]{\\parbox[t]{0.4\\linewidth}{#1}}", ("aside",)),
        (
            "\\newcommand{\\b}[1]{#1}\n\\newcommand{\\a}[1]{\\emph{#1}}\n\\renewcommand{\\b}[1]{\\textbf{#1}}",
            ("a", "b"),
        ),
    ],
)
def test_a_macro_that_typesets_its_last_argument_as_text_is_named(definition, names):
    """Running text, a known text command's text argument, a literal bracket and the body of an environment all count
    as text; the names come back sorted, each once, without the backslash."""
    assert text_macros(PREAMBLE % definition) == names


@pytest.mark.parametrize(
    "definition",
    [
        "\\newcommand{\\see}[1]{see Section~\\ref{#1}}",
        "\\newcommand{\\pic}[1]{\\includegraphics{#1}}",
        "\\newcommand{\\pic}[2]{\\includegraphics[width=#1]{#2}}",
        "\\newcommand{\\pic}[1]{\\includegraphics[scale=2]#1}",
        "\\newcommand{\\paint}[1]{\\color{#1}}",
        "\\newcommand{\\gap}[1]{text\\vspace{#1}}",
        "\\newcommand{\\pick}[1]{\\textcolor{#1}{text}}",
        "\\newcommand{\\link}[1]{\\href{https://example.com}#1}",
        "\\newcommand{\\break}[1]{line\\\\[#1]}",
        "\\newcommand{\\cols}[1]{\\begin{tabular}{#1}x\\end{tabular}}",
        "\\renewcommand{\\tabularxcolumn}[1]{m{#1}}",
        "\\newcommand{\\vect}[1]{$\\mathbf{#1}$}",
        "\\newcommand{\\square}[1]{\\(#1^2\\)}",
        "\\newcommand{\\maybe}[1]{\\ifx#1\\empty none\\else #1\\fi}",
        "\\newcommand{\\make}[1]{\\expandafter\\def\\csname #1\\endcsname{}}",
        "\\newcommand{\\inner}[1]{\\my@inner{#1}}",
        "\\newcommand{\\outer}[1]{\\newcommand{\\inner}[1]{##1 #1}}",
        "\\newcommand{\\unused}[1]{always the same}",
        "\\newcommand{\\plain}{no parameters}",
        "\\newcommand{\\open}[1]{#1",
        "\\newcommand{\\dflt}[2][\\today]{#2}",
        "% \\newcommand{\\gone}[1]{#1}",
        "\\newcommand{\\twice}[1]{#1}\n\\renewcommand{\\twice}[1]{\\label{#1}}",
        "\\newcommand{\\swap}[1]{#1}\n\\def\\swap#1{\\label{#1}}",
    ],
)
def test_a_macro_whose_last_argument_may_not_be_text_is_not_named(definition):
    """A label, a file name, a colour, a length, an optional argument, a column type or math in the last parameter's
    place, a body that programs TeX, a parameter the body never uses, no parameters, a body or default that does not
    parse, a commented-out definition, and a name some other definition (or a \\def) gives a non-text meaning: none is
    named, because markup there would not compile or the meaning is not certain."""
    assert text_macros(PREAMBLE % definition) == ()


def test_only_the_preamble_is_read():
    """A definition after \\begin{document} is not named: latexdiff takes the new side's preamble, and the scan stays
    bounded by it."""
    assert (
        text_macros("\\documentclass{article}\n\\begin{document}\n\\newcommand{\\late}[1]{#1}\n\\end{document}\n") == ()
    )


@given(st.text(alphabet=string.printable + "가#\\{}[]%$@", max_size=400))
def test_any_text_gives_sorted_letter_names_each_defined_in_it(source):
    """Any string is a valid input (a manuscript is untrusted text): text_macros never raises, and every name it gives
    is ASCII letters only - safe as a latexdiff pattern line - sorted, unique, and defined by a definition command in the
    source."""
    names = text_macros(source)
    assert list(names) == sorted(set(names))
    for name in names:
        assert re.fullmatch("[A-Za-z]+", name)
        assert re.search(r"command\*?\s*\{?\s*\\" + name + "(?![A-Za-z])", source)


@given(st.from_regex(r"[A-Za-z]{1,10}", fullmatch=True).filter(lambda name: name not in TEXT_COMMANDS))
def test_a_parameter_handed_to_any_other_command_is_never_text(command):
    """Whatever the command, unless it is one of the known text commands, a last parameter that is its argument
    (\\command{#1}) may be a label, a key or a length, so the macro is not named."""
    assert text_macros(PREAMBLE % ("\\newcommand{\\wrap}[1]{\\%s{#1}}" % command)) == ()
