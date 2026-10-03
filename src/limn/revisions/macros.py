"""The document's own commands whose last argument is text: the commands a comparison asks latexdiff to mark inside.

latexdiff marks changes word by word in running text and inside the last argument of the text commands it knows
(\\textbf, \\section, \\footnote, ...). Any other command with arguments is one opaque token: when its argument changes,
the old call is commented out and the new one is added between markers that draw nothing. A reply letter that keeps
its answers in its own \\reply{...} macros therefore showed changes only in its plain opening paragraphs (issue #162).
text_macros() reads the definitions a document's preamble makes with \\newcommand, \\renewcommand and \\providecommand,
and names those whose last argument is typeset as text, for latexdiff's --append-textcmd.

The judgement is conservative. Markup inside an argument that is not text (a label, a file name, a colour, a length,
math) breaks the comparison's compile, while leaving a text macro out only keeps latexdiff's default. So a definition
counts only when every use of its last parameter is running text or the text argument of a known text command, and its
body does no TeX programming. Pure: it only reads the string it is given.
"""

import re
from typing import TypeAlias

PREAMBLE_MAX = 1024 * 1024  # characters of the main file read for definitions; a preamble is far shorter

# Commands a body may hand arguments to, by name: (mandatory arguments, whether the last one is typeset as text).
# Optional [...] arguments are not counted. A command missing here is unknown: a group right after it is taken as
# its argument, so a parameter there is not text.
_ARGUMENTS: dict[str, tuple[int, bool]] = {
    **dict.fromkeys(
        (
            "textbf",
            "textit",
            "textsl",
            "textsf",
            "texttt",
            "textrm",
            "textsc",
            "textup",
            "textmd",
            "textnormal",
            "emph",
            "underline",
            "mbox",
            "fbox",
            "makebox",
            "framebox",
            "footnote",
        ),
        (1, True),
    ),
    "textcolor": (2, True),
    "colorbox": (2, True),
    "fcolorbox": (3, True),
    "parbox": (2, True),
    **dict.fromkeys(
        ("begin", "end", "color", "vspace", "hspace", "addvspace", "label", "linespread", "thispagestyle"), (1, False)
    ),
    "fontsize": (2, False),
    "rule": (2, False),
}
TEXT_COMMANDS = frozenset(name for name, (_, text) in _ARGUMENTS.items() if text)

# A definition with parameters whose body opens right after the match: \newcommand{\name}[n], \renewcommand*\name[n],
# \providecommand{\name}[n][default]{. A default holding a brace, bracket or command does not match (see _ANY_DEFINITION).
_DEFINITION = re.compile(
    r"\\(?:new|renew|provide)command\*?\s*(?:\{\s*\\([A-Za-z]+)\s*\}|\\([A-Za-z]+))"
    r"\s*\[\s*([1-9])\s*\]\s*(?:\[[^\]{}\\]*\]\s*)?\{"
)
# Every way a preamble gives a name a meaning. A name counts only when each of these is a _DEFINITION judged text.
_ANY_DEFINITION = re.compile(
    r"\\(?:(?:new|renew|provide)command\*?|DeclareRobustCommand\*?|(?:New|Renew|Provide|Declare)DocumentCommand"
    r"|[egx]?def|let)\s*\{?\s*\\([A-Za-z]+)"
)
# Bodies that program TeX instead of typesetting: conditionals, expansion control, definitions, file reads, verbatim,
# internal (@) names and nested parameters. Their parameters may be anything.
_PROGRAMMING = re.compile(
    r"\\(?:if[A-Za-z]*|fi|else|or|csname|endcsname|expandafter|noexpand|string|detokenize|unexpanded|number"
    r"|romannumeral|the|meaning|[egx]?def|let|futurelet|global|long|(?:new|renew|provide)command"
    r"|DeclareRobustCommand|(?:New|Renew|Provide|Declare)DocumentCommand|input|include|catcode|uppercase|lowercase"
    r"|char|verb|ensuremath)(?![A-Za-z])|\\[A-Za-z]*@|##"
)
# Math: the comparison runs latexdiff with --math-markup=off, and its text markup does not compile inside math.
_MATH = re.compile(
    r"\$|(?<!\\)\\[(\[]|\\begin\s*\{\s*(?:equation|align|gather|multline|eqnarray|math|displaymath|flalign|alignat)"
)
_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%.*")  # an unescaped % to the end of its line; \\ before it stays
_BRACE = re.compile(r"\\.|[{}]", re.DOTALL)
_WORD = re.compile(r"[A-Za-z]+\*?")
_BEGIN_DOCUMENT = re.compile(r"\\begin\s*\{\s*document\s*\}")

# Where the scan stands: right after a command and how many of its mandatory arguments it has read, or None.
Context: TypeAlias = tuple[str, int] | None


def text_macros(source: str) -> tuple[str, ...]:
    """The names (without the backslash, sorted, each once) of the commands the preamble of source - the text before
    \\begin{document}, at most PREAMBLE_MAX characters, comments removed - defines with parameters and whose every
    definition typesets its last parameter as text (_last_parameter_is_text). A name some definition gives another
    meaning (a \\def, \\let, \\NewDocumentCommand, a default or body that does not parse) is left out. Any string is
    valid input; it never raises."""
    text = _COMMENT.sub(r"\1", source[:PREAMBLE_MAX])
    begin = _BEGIN_DOCUMENT.search(text)
    preamble = text[: begin.start()] if begin else text
    pairs = _brace_pairs(preamble)
    counted: dict[str, int] = {}
    for m in _ANY_DEFINITION.finditer(preamble):
        counted[m.group(1)] = counted.get(m.group(1), 0) + 1
    judged: dict[str, list[bool]] = {}
    for m in _DEFINITION.finditer(preamble):
        name, count, start = m.group(1) or m.group(2), int(m.group(3)), m.end() - 1
        end = pairs.get(start)
        judged.setdefault(name, []).append(end is not None and _last_parameter_is_text(preamble, start + 1, end, count))
    return tuple(sorted(name for name, oks in judged.items() if all(oks) and len(oks) == counted.get(name)))


def _brace_pairs(text: str) -> dict[int, int]:
    """The index of each { in text (an escaped \\{ is not one) mapped to the index of its matching }; a { that never
    closes is absent. One pass, so finding every body costs no more than reading the text once."""
    pairs: dict[int, int] = {}
    open_at: list[int] = []
    for m in _BRACE.finditer(text):
        if m.group(0) == "{":
            open_at.append(m.start())
        elif m.group(0) == "}" and open_at:
            pairs[open_at.pop()] = m.start()
    return pairs


def _last_parameter_is_text(text: str, start: int, end: int, count: int) -> bool:
    """Whether the definition body text[start:end], of count parameters, uses #count, and every use is running text:
    outside any group, or in plain groups and the text arguments of known text commands (_ARGUMENTS); never in an
    optional [...] argument, in an unknown command's argument, in a group glued to a word (a column type such as
    m{...}), in math or in a body that programs TeX (_PROGRAMMING). Reads the body in place: nested definitions share
    text, and a body that programs is turned down at its first such command, so the scans stay linear."""
    parameter = "#%d" % count
    if _PROGRAMMING.search(text, start, end) or text.find(parameter, start, end) < 0 or _MATH.search(text, start, end):
        return False
    groups: list[tuple[str, bool, Context]] = []  # open groups: (closing character, text allowed, context after it)
    context: Context = None
    previous = ""
    i = start
    while i < end:
        c = text[i]
        if c == "\\":
            word = _WORD.match(text, i + 1, end)
            name = word.group(0).rstrip("*") if word else text[i + 1 : min(i + 2, end)]
            i = word.end() if word else i + 2
            context, previous = (name, 0), ""
            continue
        i += 1
        if c.isspace():  # TeX skips spaces before an argument, so the context stays
            previous = " "
        elif c == "#":
            if text.startswith(parameter, i - 1, end) and not (
                all(allowed for _, allowed, _ in groups) and _bare_parameter_is_text(context)
            ):
                return False
            context, previous = None, c
            i += 1 if i < end and text[i].isdigit() else 0
        elif c == "{":
            allowed, after = _group_opens(context, previous.isalnum())
            groups.append(("}", allowed, after))
            context, previous = None, ""
        elif c == "[" and context is not None:  # an optional argument; an unknown command taking one takes arguments
            name, read = context
            groups.append(("]", False, context if name in _ARGUMENTS else (name, max(read, 1))))
            context, previous = None, ""
        elif groups and c == groups[-1][0]:
            context, previous = groups.pop()[2], c
        else:
            context, previous = None, c
    return not groups


def _group_opens(context: Context, glued: bool) -> tuple[bool, Context]:
    """A { opening in context: whether text may sit in the group, and the context once it closes. Right after a
    command it is that command's next argument - text only when it is a known text command's last one. Otherwise it
    is a plain group, which may hold text unless it is glued to a word."""
    if context is None:
        return not glued, None
    name, read = context
    arity, text = _ARGUMENTS.get(name, (0, False))
    return text and read == arity - 1, (name, read + 1)


def _bare_parameter_is_text(context: Context) -> bool:
    """Whether a parameter written without braces in context is text: not right after a command it would be an
    argument of. A known command's arguments are known; after an unknown command the parameter counts only if no
    argument was read yet (a declaration such as \\itshape or \\normalsize takes none)."""
    if context is None:
        return True
    name, read = context
    if name not in _ARGUMENTS:
        return read == 0
    arity, text = _ARGUMENTS[name]
    return read >= arity or (text and read == arity - 1)
