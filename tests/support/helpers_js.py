"""A small JavaScript tokenizer for the tests that read the viewer's scripts as source.

The viewer is plain classic scripts (src/limn/viewer/js/*.js joined into one <script>), and the tests pull its real
functions out to run them under node, and check the source for shapes a parser would accept but a person did not mean
(a statement swallowed by a `//` comment, a function nothing calls). Counting braces or matching regexes over raw text
cannot tell a brace, quote or `//` inside a string, template literal, regular expression or comment from code, so these
tests read the text through tokenize() instead. It knows exactly what the viewer uses: comments, string literals,
template literals (with `${...}` substitutions, nested), regular-expression literals, identifiers, numbers and
punctuators. It is not a parser: it does not check grammar (node --check does that), it only says where each token
starts and ends, so a brace in any literal or comment is never counted.

On top of the tokens: the top-level function declarations of a script (top_level_functions, function_source), the
names it uses (references), and the closed-set tables core.js declares (closed_sets, closed_set_prelude - see
docs/handbook/viewer.md §닫힌 값 표).

Stdlib only, like the server; node is not needed to tokenize.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

Kind = Literal["space", "comment", "line-comment", "string", "template", "regex", "ident", "number", "punct"]

# After one of these words an expression starts, so a '/' there begins a regular expression, never a division.
_EXPR_KEYWORDS = frozenset(
    [
        "return",
        "typeof",
        "instanceof",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "case",
        "do",
        "else",
        "yield",
        "await",
    ]
)
# Punctuators, longest first so '===' is never read as '==' then '='.
_PUNCTS = sorted(
    [
        "{",
        "}",
        "(",
        ")",
        "[",
        "]",
        ";",
        ",",
        "<",
        ">",
        "+",
        "-",
        "*",
        "%",
        "&",
        "|",
        "^",
        "!",
        "~",
        "?",
        ":",
        "=",
        ".",
        "@",
        "#",
        "...",
        "<=",
        ">=",
        "==",
        "!=",
        "===",
        "!==",
        "**",
        "++",
        "--",
        "<<",
        ">>",
        ">>>",
        "&&",
        "||",
        "??",
        "?.",
        "=>",
        "+=",
        "-=",
        "*=",
        "%=",
        "**=",
        "<<=",
        ">>=",
        ">>>=",
        "&=",
        "|=",
        "^=",
        "&&=",
        "||=",
        "??=",
    ],
    key=len,
    reverse=True,
)
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUMBER = re.compile(r"0[xXoObB][\da-fA-F_]+n?|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?n?")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Token:
    """One token of a script: its kind, its exact source text, and where it sits (text == source[start:end]).

    A template literal is split where its substitutions are: '`a${' , '}b${' and '}c`' are each one "template" token,
    and the substitution's code between them is ordinary tokens - so identifiers used inside `${...}` are seen, and a
    template's '${' / '}' never count as braces. A "line-comment" is a `//` comment (without its newline); "comment" is
    a `/* */` one."""

    kind: Kind
    text: str
    start: int
    end: int


class TokenizeError(ValueError):
    """The text is not a script this tokenizer can read: an unterminated string, template, regex or comment. The viewer's
    parts all parse (node --check), so this means a broken part or a tokenizer gap."""


def _regex_allowed(prev: Token | None) -> bool:
    """Whether a '/' after prev (the last token that is not space or comment) starts a regular expression.

    An expression can start at the beginning, after an operator or opening bracket, or after a keyword such as
    `return`; after a value (an identifier, a number, a literal, ')' ']' '}') a '/' divides. `}` is read as the end of
    an object or a template substitution, which the viewer never follows with a regex statement."""
    if prev is None:
        return True
    if prev.kind == "ident":
        return prev.text in _EXPR_KEYWORDS
    if prev.kind in ("number", "string", "regex"):
        return False
    if prev.kind == "template":
        return prev.text.endswith("${")
    return prev.text not in (")", "]", "}", "++", "--")


def _scan_quoted(src: str, i: int) -> int:
    """The end offset of the string literal whose opening quote is at src[i] (backslash escapes honoured)."""
    q = src[i]
    j = i + 1
    while j < len(src):
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == q:
            return j + 1
        if c == "\n":
            break
        j += 1
    raise TokenizeError("unterminated string at offset %d" % i)


def _scan_template(src: str, i: int) -> tuple[int, bool]:
    """Scan template text from src[i] (just after '`' or a substitution's closing '}') to the next '${' or closing '`'.
    Returns the end offset and whether a substitution opened there."""
    j = i
    while j < len(src):
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == "`":
            return j + 1, False
        if c == "$" and src.startswith("${", j):
            return j + 2, True
        j += 1
    raise TokenizeError("unterminated template literal at offset %d" % i)


def _scan_regex(src: str, i: int) -> int:
    """The end offset of the regular-expression literal starting with '/' at src[i]: up to the '/' that is neither
    escaped nor inside a [...] class, then its flags."""
    j = i + 1
    in_class = False
    while j < len(src):
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == "\n":
            break
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "/":
            j += 1
            while j < len(src) and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            return j
        j += 1
    raise TokenizeError("unterminated regular expression at offset %d" % i)


def tokenize(src: str) -> list[Token]:
    """Every token of src in order, spaces and comments included, so the tokens' texts joined are src exactly.

    Raises TokenizeError for an unterminated literal or comment."""
    out: list[Token] = []
    prev: Token | None = None  # the last token that is not space or comment: decides '/' and closing '}'
    braces: list[bool] = []  # one entry per open '{' or '${': True for a template substitution
    i = 0
    while i < len(src):
        c = src[i]
        kind: Kind
        if c.isspace():
            end = _SPACE.match(src, i).end()  # type: ignore[union-attr]
            kind = "space"
        elif src.startswith("//", i):
            nl = src.find("\n", i)
            end = len(src) if nl < 0 else nl
            kind = "line-comment"
        elif src.startswith("/*", i):
            close = src.find("*/", i + 2)
            if close < 0:
                raise TokenizeError("unterminated comment at offset %d" % i)
            end = close + 2
            kind = "comment"
        elif c in "'\"":
            end = _scan_quoted(src, i)
            kind = "string"
        elif c == "`":
            end, opened = _scan_template(src, i + 1)
            if opened:
                braces.append(True)
            kind = "template"
        elif c == "}" and braces and braces[-1]:
            braces.pop()
            end, opened = _scan_template(src, i + 1)
            if opened:
                braces.append(True)
            kind = "template"
        elif c == "/" and _regex_allowed(prev):
            end = _scan_regex(src, i)
            kind = "regex"
        elif _IDENT.match(src, i):
            end = _IDENT.match(src, i).end()  # type: ignore[union-attr]
            kind = "ident"
        elif c.isdigit() or (c == "." and i + 1 < len(src) and src[i + 1].isdigit()):
            end = _NUMBER.match(src, i).end()  # type: ignore[union-attr]
            kind = "number"
        else:
            p = next((p for p in _PUNCTS if src.startswith(p, i)), c)
            end = i + len(p)
            kind = "punct"
            if p == "{":
                braces.append(False)
            elif p == "}" and braces:
                braces.pop()
        tok = Token(kind, src[i:end], i, end)
        out.append(tok)
        if kind not in ("space", "comment", "line-comment"):
            prev = tok
        i = end
    return out


def code(tokens: list[Token]) -> list[Token]:
    """The tokens that are code: spaces and comments dropped."""
    return [t for t in tokens if t.kind not in ("space", "comment", "line-comment")]


@dataclass(frozen=True)
class FunctionDecl:
    """A top-level `function NAME(...){...}` declaration (optionally `async`) and where it sits in its script:
    source[start:end] is the whole declaration, from `async`/`function` to its closing brace."""

    name: str
    start: int
    end: int


def matching_bracket(toks: list[Token], k: int) -> int:
    """The index of the token closing the bracket opened at toks[k] ('(' '[' '{'), across nested brackets and template
    substitutions (a template token that ends in '${' opens, one that starts with '}' closes)."""
    depth = 0
    for j in range(k, len(toks)):
        t = toks[j]
        opens = t.text in ("(", "[", "{") if t.kind == "punct" else (t.kind == "template" and t.text.endswith("${"))
        closes = t.text in (")", "]", "}") if t.kind == "punct" else (t.kind == "template" and t.text.startswith("}"))
        if closes:
            depth -= 1
            if depth == 0:
                return j
        if opens:
            depth += 1
    raise TokenizeError("unbalanced bracket at offset %d" % toks[k].start)


def top_level_functions(src: str) -> list[FunctionDecl]:
    """The function declarations at the top level of script src, in order. A function inside another function, a
    block or an expression (`const f=function g(){}`) is not one: only a `function` that starts a statement at depth 0.
    """
    toks = code(tokenize(src))
    out: list[FunctionDecl] = []
    k = 0
    while k < len(toks):
        t = toks[k]
        if t.kind == "punct" and t.text in ("(", "[", "{") or t.kind == "template" and t.text.endswith("${"):
            k = matching_bracket(toks, k) + 1
            continue
        before = toks[k - 1] if k else None
        starts_statement = before is None or (
            before.text in (";", "}", ")", "]") if before.kind == "punct" else before.text not in _EXPR_KEYWORDS
        )
        head = k + 1 if t.text == "async" and k + 1 < len(toks) and toks[k + 1].text == "function" else k
        if starts_statement and t.kind == "ident" and toks[head].text == "function":
            n = head + 1 + (toks[head + 1].text == "*")
            name = toks[n].text
            body = matching_bracket(toks, n + 1) + 1  # the '{' after the parameter list
            end = matching_bracket(toks, body)
            out.append(FunctionDecl(name, t.start, toks[end].end))
            k = end + 1
            continue
        k += 1
    return out


def name_uses(src: str) -> list[Token]:
    """The identifier tokens script src uses as names, in order. A property after '.' or '?.' (`x.name`) is not a use
    of `name`; words inside strings, templates' text, regexes and comments are not identifiers at all."""
    toks = code(tokenize(src))
    return [
        t
        for j, t in enumerate(toks)
        if t.kind == "ident" and not (j and toks[j - 1].kind == "punct" and toks[j - 1].text in (".", "?."))
    ]


def references(src: str, exclude: tuple[int, int] | None = None) -> set[str]:
    """The names script src uses (name_uses), outside the span exclude (start, end) if given."""
    return {t.text for t in name_uses(src) if not (exclude and exclude[0] <= t.start < exclude[1])}


class _InlineScripts(HTMLParser):
    """Collects the text of every inline <script> (one without src) in document order."""

    def __init__(self) -> None:
        """Start with no scripts; convert_charrefs=False keeps script text exactly as served."""
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open a script to collect unless it loads its code from src."""
        if tag == "script" and not dict(attrs).get("src"):
            self._inside = True
            self.scripts.append("")

    def handle_endtag(self, tag: str) -> None:
        """Close the script being collected."""
        if tag == "script":
            self._inside = False

    def handle_data(self, data: str) -> None:
        """Script text arrives as data (HTMLParser treats <script> content as CDATA)."""
        if self._inside:
            self.scripts[-1] += data


def inline_scripts(page: str) -> list[str]:
    """The inline scripts of an HTML page, in order."""
    p = _InlineScripts()
    p.feed(page)
    p.close()
    return p.scripts


@functools.lru_cache(maxsize=4)
def page_functions(page: str) -> dict[str, tuple[str, ...]]:
    """Every top-level function declared in the inline scripts of page: name -> the source of each declaration, in
    page order. Cached per page text, since the tests pull hundreds of functions out of the same page."""
    out: dict[str, tuple[str, ...]] = {}
    for js in inline_scripts(page):
        for f in top_level_functions(js):
            out[f.name] = out.get(f.name, ()) + (js[f.start : f.end],)
    return out


def function_source(page: str, name: str) -> str:
    """The source text of the top-level declaration `function NAME(...){...}` (with its `async`, if any) in the inline
    scripts of page, exactly as served. Raises LookupError when no script declares it at the top level, and ValueError
    when more than one does (the later one would silently win in the browser)."""
    found = page_functions(page).get(name, ())
    if not found:
        raise LookupError("no top-level function %s in the page's scripts" % name)
    if len(found) > 1:
        raise ValueError("function %s is declared %d times at the top level" % (name, len(found)))
    return found[0]


ClosedSet = str | dict[str, str]  # a scalar constant ('local') or a frozen table ({"OPEN": "open", ...})


def _string_value(t: Token) -> str | None:
    """The value of a plain string literal token (quoted, no escapes), else None - the tables hold only plain words."""
    if t.kind != "string" or "\\" in t.text:
        return None
    return t.text[1:-1]


def _closed_set(init: list[Token]) -> ClosedSet | None:
    """The value of one declarator's initializer when it is a closed set: a plain string, or
    `Object.freeze({KEY:'value',...})` with plain string values and nothing else. None for any other initializer."""
    if len(init) == 1:
        return _string_value(init[0])
    if [t.text for t in init[:5]] != ["Object", ".", "freeze", "(", "{"] or [t.text for t in init[-2:]] != ["}", ")"]:
        return None
    body = init[5:-2]
    table: dict[str, str] = {}
    for k in range(0, len(body), 4):
        entry = body[k : k + 4]
        value = _string_value(entry[2]) if len(entry) >= 3 else None
        if (
            value is None
            or entry[0].kind != "ident"
            or entry[1].text != ":"
            or (len(entry) == 4 and entry[3].text != ",")
        ):
            return None
        table[entry[0].text] = value
    return table


def _split_top(toks: list[Token], sep: str) -> list[list[Token]]:
    """toks cut at every `sep` punctuator outside brackets (the separators dropped)."""
    parts: list[list[Token]] = [[]]
    depth = 0
    for t in toks:
        if t.kind == "punct" and t.text in ("(", "[", "{"):
            depth += 1
        elif t.kind == "punct" and t.text in (")", "]", "}"):
            depth -= 1
        if depth == 0 and t.kind == "punct" and t.text == sep:
            parts.append([])
        else:
            parts[-1].append(t)
    return parts


def closed_sets(src: str) -> dict[str, ClosedSet]:
    """The closed sets script src declares at its top level (core.js §closed sets), by name in order: every
    `const A=..., B=...;` statement whose declarators are all a plain string or a frozen table of plain strings. Any
    other const statement is skipped whole."""
    out: dict[str, ClosedSet] = {}
    for statement in _split_top(code(tokenize(src)), ";"):
        if not statement or statement[0].text != "const":
            continue
        found: dict[str, ClosedSet] = {}
        for decl in _split_top(statement[1:], ","):
            value = _closed_set(decl[2:]) if len(decl) > 2 and decl[0].kind == "ident" and decl[1].text == "=" else None
            if value is None:
                break
            found[decl[0].text] = value
        else:
            out.update(found)
    return out


def closed_set_prelude(sets: dict[str, ClosedSet], js: str) -> str:
    """`var` declarations of the closed sets js names, for a node harness that runs pulled functions on their own: a
    function reads PIN_STATE or LOCAL_LOGIN from the page's shared scope, which the harness does not have. `var` (not
    const) so that pulling several functions that each bring the same table is still a valid script. '' when js names
    none."""
    used = references(js)
    out = ""
    for name, value in sets.items():
        if name in used:
            init = json.dumps(value) if isinstance(value, str) else "Object.freeze(%s)" % json.dumps(value)
            out += "var %s=%s;\n" % (name, init)
    return out
