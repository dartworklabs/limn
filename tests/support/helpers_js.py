"""A small JavaScript tokenizer for the tests that read the viewer's scripts as source.

The viewer is ES modules (src/limn/viewer/js/**/*.ts) built into one classic script, and the tests pull its real
functions out to run them under node, and check the source for shapes a parser would accept but a person did not mean
(a statement swallowed by a `//` comment, a function nothing calls). Counting braces or matching regexes over raw text
cannot tell a brace, quote or `//` inside a string, template literal, regular expression or comment from code, so these
tests read the text through tokenize() instead. It knows exactly what the viewer uses: comments, string literals,
template literals (with `${...}` substitutions, nested), regular-expression literals, identifiers, numbers and
punctuators. It is not a parser: it does not check grammar (node --check does that), it only says where each token
starts and ends, so a brace in any literal or comment is never counted.

On top of the tokens: the top-level function declarations of a script (top_level_functions, function_source), the
names it uses (references), and the closed-set tables the table modules declare (closed_sets, closed_set_prelude - see
docs/handbook/viewer.md §닫힌 값 표).

Stdlib only, like the server; node is not needed to tokenize. A module's own text is TypeScript, which the tokenizer does
not read: module_text() gives its code as the build takes it, its types taken out by tools/strip_types.mjs (node and
`npm ci --ignore-scripts`).
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import unittest
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
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


def _scan_quoted(src: str, i: int, fragment: bool = False) -> int:
    """The end offset of the string literal whose opening quote is at src[i] (backslash escapes honoured). In a fragment
    a string that runs to the end of src is a string cut off there."""
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
    if fragment and j >= len(src):
        return len(src)
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


def tokenize(src: str, fragment: bool = False) -> list[Token]:
    """Every token of src in order, spaces and comments included, so the tokens' texts joined are src exactly.

    Raises TokenizeError for an unterminated literal or comment - unless src is a fragment (a piece of a script cut
    where a test stopped copying it): then a string or a comment still open at its end is that string or comment cut
    off."""
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
                if not fragment:
                    raise TokenizeError("unterminated comment at offset %d" % i)
                close = len(src) - 2
            end = close + 2
            kind = "comment"
        elif c in "'\"":
            end = _scan_quoted(src, i, fragment)
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


_STATEMENT_WORDS = ("const", "let", "var", "function", "async", "class")


def _after_blocks(toks: list[Token]) -> list[list[Token]]:
    """toks cut before each statement keyword that follows a top-level closing brace: a declaration that ends in a block
    (`function f() {...}`, `class C {...}`) has no `;`, so _split_top leaves the statement after it in the same piece."""
    parts: list[list[Token]] = [[]]
    depth = 0
    for k, t in enumerate(toks):
        closed = k > 0 and depth == 0 and toks[k - 1].kind == "punct" and toks[k - 1].text == "}"
        if closed and t.kind == "ident" and t.text in _STATEMENT_WORDS:
            parts.append([])
        if t.kind == "punct" and t.text in ("(", "[", "{"):
            depth += 1
        elif t.kind == "punct" and t.text in (")", "]", "}"):
            depth -= 1
        parts[-1].append(t)
    return parts


def closed_sets(src: str) -> dict[str, ClosedSet]:
    """The closed sets script src declares at its top level (docs/handbook/viewer.md §닫힌 값 표), by name in order:
    every `const A=..., B=...;` statement whose declarators are all a plain string or a frozen table of plain strings.
    Any other const statement is skipped whole."""
    out: dict[str, ClosedSet] = {}
    for statement in (piece for chunk in _split_top(code(tokenize(src)), ";") for piece in _after_blocks(chunk)):
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


_WORD = re.compile(r"[\w$]")
_OPENERS = ("(", "[", "{")


def _opens(t: Token) -> bool:
    """Whether t opens a bracket: '(' '[' '{' or a template token that ends in '${'."""
    return t.text in _OPENERS if t.kind == "punct" else t.kind == "template" and t.text.endswith("${")


def squash(src: str, fragment: bool = False) -> str:
    """src's code as one run of tokens, however it is laid out: spaces and comments dropped, one space kept only where
    two neighbouring tokens would otherwise read as one (`return x`, `a + +b`), and a trailing comma before a closing
    bracket dropped. Strings, templates' text and regexes stay exactly as written. The viewer's source is formatted by
    Prettier (line breaks, indentation, trailing commas), so a test that looks for a piece of code in it looks for
    squash(piece) in squash(source) instead of for one layout of it. A piece that is not whole statements may be
    squashed too: a fragment is read as the tokens it would be inside a longer script, and with fragment=True one that
    stops inside a string or a comment is read as that string or comment cut off."""
    toks = code(tokenize(src, fragment))
    # `(x) => ...` and `x => ...` are the one thing: the parentheses round a lone parameter are a layout choice.
    parens = {
        k
        for k in range(len(toks) - 3)
        if toks[k].text == "(" and toks[k + 1].kind == "ident" and toks[k + 2].text == ")" and toks[k + 3].text == "=>"
    }
    parens |= {k + 2 for k in parens}
    out: list[str] = []
    for k, t in enumerate(toks):
        if k in parens:
            continue
        closes = t.text in (")", "]", "}") if t.kind == "punct" else t.kind == "template" and t.text.startswith("}")
        if closes and out and out[-1] == ",":
            out.pop()
        if out and out[-1] != " ":
            last = out[-1][-1]
            if (_WORD.match(last) and _WORD.match(t.text[0])) or (last in "+-" and t.text[0] == last):
                out.append(" ")
        out.append(t.text)
    return "".join(out)


def declared_names(src: str) -> dict[str, list[str]]:
    """The top-level `const`, `let` and `var` statements of script src, each whole (through its `;`): name -> the text of
    every statement that declares it as a plain `NAME = ...` declarator (the first of a statement, or after a top-level
    comma). A destructuring declarator names nothing here."""
    toks = code(tokenize(src))
    out: dict[str, list[str]] = {}
    k = 0
    while k < len(toks):
        t = toks[k]
        if _opens(t):
            k = matching_bracket(toks, k) + 1
            continue
        before = toks[k - 1] if k else None
        starts = before is None or (before.kind == "punct" and before.text in (";", "}", ")", "]"))
        if not (starts and t.kind == "ident" and t.text in ("const", "let", "var")):
            k += 1
            continue
        j = k + 1
        names: list[str] = []
        while j < len(toks) and not (toks[j].kind == "punct" and toks[j].text == ";"):
            if _opens(toks[j]):
                j = matching_bracket(toks, j) + 1
                continue
            lead = toks[j - 1]
            if (
                toks[j].kind == "ident"
                and (lead.text in ("const", "let", "var") if lead.kind == "ident" else lead.text == ",")
                and j + 1 < len(toks)
                and toks[j + 1].text == "="
            ):
                names.append(toks[j].text)
            j += 1
        end = toks[j].end if j < len(toks) else len(src)
        for name in names:
            out.setdefault(name, []).append(src[t.start : end])
        k = j + 1
    return out


@functools.lru_cache(maxsize=4)
def page_declarations(page: str) -> dict[str, tuple[str, ...]]:
    """declared_names of every inline script of page, merged: name -> the statements declaring it, in page order."""
    out: dict[str, tuple[str, ...]] = {}
    for js in inline_scripts(page):
        for name, found in declared_names(js).items():
            out[name] = out.get(name, ()) + tuple(found)
    return out


def one_declaration(found: list[str] | tuple[str, ...], name: str) -> str:
    """The one statement of found that declares name; LookupError for none, ValueError for several."""
    if not found:
        raise LookupError("no top-level declaration of %s" % name)
    if len(found) > 1:
        raise ValueError("%s is declared %d times at the top level" % (name, len(found)))
    return found[0]


def declaration_source(page: str, name: str) -> str:
    """The top-level `const|let|var` statement that declares NAME in the inline scripts of page, exactly as served and
    whole (a statement declaring several names comes whole for each). Raises LookupError when none declares it and
    ValueError when more than one does."""
    return one_declaration(page_declarations(page).get(name, ()), name)


def module_declaration(src: str, name: str) -> str:
    """declaration_source for one script or module's text src: the statement declaring NAME, whole and as written."""
    return one_declaration(declared_names(src).get(name, []), name)


def statement_init(stmt: str, name: str) -> str:
    """The initializer of the declarator NAME in the statement stmt (`const NAME = <init>;`): the text after its `=` up
    to the declarator's end - the `;`, or the `,` that starts the next declarator - exactly as written."""
    toks = code(tokenize(stmt))
    k = next(
        i
        for i, t in enumerate(toks)
        if t.text == name and toks[i + 1].text == "=" and toks[i - 1].text in ("const", "let", "var", ",")
    )
    j = k + 2
    while j < len(toks) and not (toks[j].kind == "punct" and toks[j].text in (";", ",")):
        j = matching_bracket(toks, j) + 1 if _opens(toks[j]) else j + 1
    return stmt[toks[k + 1].end : toks[j - 1].end].strip()


def declaration_init(page: str, name: str) -> str:
    """The initializer of the top-level declarator NAME in the inline scripts of page (statement_init of its
    declaration_source)."""
    return statement_init(declaration_source(page, name), name)


@functools.lru_cache(maxsize=4)
def _page_code(page: str) -> tuple[tuple[str, tuple[Token, ...]], ...]:
    """Each inline script of page with its code tokens (comments and spaces dropped), cached per page."""
    return tuple((js, tuple(code(tokenize(js)))) for js in inline_scripts(page))


def case_block(page: str, label: str) -> str:
    """The text between the braces of the first `case 'LABEL':{...}` of the inline scripts of page, exactly as served. Raises
    LookupError when no script has such a case with a block."""
    for js, toks in _page_code(page):
        for k in range(len(toks) - 3):
            if (
                toks[k].text == "case"
                and toks[k + 1].kind == "string"
                and toks[k + 1].text[1:-1] == label
                and toks[k + 2].text == ":"
                and toks[k + 3].text == "{"
            ):
                end = matching_bracket(list(toks), k + 3)
                return js[toks[k + 3].end : toks[end].start]
    raise LookupError("no `case '%s':{...}` in the page's scripts" % label)


def call_source(page: str, head: str) -> str:
    """The whole call expression of the inline scripts of page that begins with head - the code up to and with its first
    open parenthesis and the argument that follows, such as `document.addEventListener('keydown'` - from its first
    token to the parenthesis that closes it, exactly as served. The first such call wins. Raises LookupError when no
    script has one."""
    want = [t.text for t in code(tokenize(head))]
    opener = want.index("(")
    for js, toks in _page_code(page):
        texts = [t.text for t in toks]
        for i in range(len(texts) - len(want)):
            if texts[i : i + len(want)] == want:
                end = matching_bracket(list(toks), i + opener)
                return js[toks[i].start : toks[end].end]
    raise LookupError("no call beginning %r in the page's scripts" % head)


def listener_body(page: str, target: str, event: str, mentioning: str = "") -> str:
    """The text between the braces of the first handler `target.addEventListener('EVENT', e => {...})` of the inline
    scripts of page whose body mentions `mentioning` (a name), exactly as served. A handler is an arrow function with
    one parameter and a block body, in either layout of its parameter - `e =>` or `(e) =>`. Raises LookupError when
    there is none."""
    want = [t.text for t in code(tokenize(target + ".addEventListener('%s'," % event))]
    for js, toks in _page_code(page):
        texts = [t.text for t in toks]
        for i in range(len(texts) - len(want) - 4):
            if texts[i : i + len(want)] != want:
                continue
            j = i + len(want)
            j += 3 if texts[j] == "(" and texts[j + 2] == ")" else 1
            if (toks[j - 1].kind == "ident" or texts[j - 1] == ")") and texts[j] == "=>" and texts[j + 1] == "{":
                body = js[toks[j + 1].end : toks[matching_bracket(list(toks), j + 1)].start]
                if mentioning in references(body):
                    return body
    raise LookupError(
        "no %s.addEventListener('%s', e => {...}) mentioning %r in the page's scripts" % (target, event, mentioning)
    )


def function_body(page: str, name: str) -> str:
    """The text between the braces of the top-level function NAME in the inline scripts of page, exactly as served."""
    src = function_source(page, name)
    toks = code(tokenize(src))
    n = next(i for i, t in enumerate(toks) if t.text == "(")
    open_ = matching_bracket(toks, n) + 1
    close = matching_bracket(toks, open_)
    return src[toks[open_].end : toks[close].start]


# The module syntax the viewer's ES modules carry (docs/adr/0042-viewer-es-modules.md): the named imports at the top, a
# side-effect-only import, and the export list at the end - one statement each, possibly over several lines.
_MODULE_SYNTAX = re.compile(r"^(?:import \{[^}]*\} from '[^']+';|import '[^']+';|export \{[^}]*\};)\n", re.M)


def module_code(src: str) -> str:
    """A viewer module's text as the build puts it into the script: its import and export statements taken out, every
    other byte as written - so a node harness can run a module's code as a classic script."""
    return _MODULE_SYNTAX.sub("", src)


# A setter the ES modules declare for a binding another module changes (ADR-0042 D1): `function setX(v){X=v; return v;}`,
# in whatever layout (squash() reads it as the one line it would be).
# A setter: it assigns its argument to the binding (and answers it), to a field of a module object
# (`setComposeBox(value){COMPOSE.box=value;}`), or to a field of the object it is given (`setEditAssignee(card,a)`).
_SETTER = re.compile(
    r"function (set\w+)\((\w+)\)\{(\w+)=\2;return \2;\}"
    r"|function set\w+\((\w+)\)\{\w+\.\w+=\4;\}"
    r"|function set\w+\((\w+),(\w+)\)\{\5\.\w+=\6;\}"
)


# A state reader the ES modules declare for a binding that is null until it is first set (app/state.ts knownMeta): it
# answers the binding, and throws an Error whose message starts with the binding's name while it is still null.
_KNOWN_READER = re.compile(r"function \w+\(\)\{if\(!(\w+)\)throw new Error\('\1 [^']*'\);return \1;\}")


def setter_prelude(page: str, js: str) -> str:
    """The setters and known-state readers js calls, as the page declares them: a pulled function that changes another
    module's binding calls that module's setter, and one that reads a binding only once it is set calls its reader
    (knownMeta), which a node harness that declares the binding itself does not have. The reader runs against the
    harness's binding, so a harness that leaves it null sees the throw the page would. Function declarations, so pulling
    several functions that bring the same setter or reader is still a valid script. '' when js calls none."""
    used = references(js)
    out = ""
    for name, sources in page_functions(page).items():
        if name in used:
            out += "".join(
                src + "\n" for src in sources if _SETTER.fullmatch(squash(src)) or _KNOWN_READER.fullmatch(squash(src))
            )
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


ROOT = Path(__file__).resolve().parents[2]
STRIP_TYPES = ROOT / "tools" / "strip_types.mjs"  # what the build takes a module's types out with


@functools.lru_cache(maxsize=8)
def strip_results(files: tuple[tuple[str, str], ...]) -> tuple[tuple[bool, str], ...]:
    """tools/strip_types.mjs over (name, text) pairs, in one node run: for each, (True, its code with its types taken
    out), or (False, the error stripping it threw - a SyntaxError for a module that does not parse)."""
    node = shutil.which("node")
    if not node or not (ROOT / "node_modules" / "typescript").is_dir():
        missing = "node" if not node else "the viewer's dev tools (npm ci --ignore-scripts)"
        if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
            raise AssertionError("%s required (LIMN_TEST_REQUIRE_NODE=1) but not installed" % missing)
        raise unittest.SkipTest("%s is not installed: a viewer module's code is its TypeScript without types" % missing)
    # The texts go on stdin, as one JSON list: a module is past what one argument may hold (MAX_ARG_STRLEN).
    script = (
        "import { readFileSync } from 'node:fs';\n"
        "import { stripTypes } from %s;\n"
        "const files = JSON.parse(readFileSync(0, 'utf8'));\n"
        "const one = ([name, text]) => { try { return [true, stripTypes(text, name)]; } catch (e) { return [false, String(e)]; } };\n"
        "process.stdout.write(JSON.stringify(files.map(one)));\n"
    ) % json.dumps(STRIP_TYPES.as_uri())
    r = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps([list(f) for f in files]),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=ROOT,
    )
    if r.returncode != 0:
        raise AssertionError("tools/strip_types.mjs failed:\n%s" % r.stderr)
    return tuple((ok, text) for ok, text in json.loads(r.stdout))


def module_texts(paths: list[Path]) -> list[str]:
    """The code of each viewer module in paths as the build takes it (tools/build_viewer.mjs): its TypeScript types taken
    out by tools/strip_types.mjs, every other byte as written - imports, exports and comments included. Skips the test
    without node and the viewer's dev tools, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
    results = strip_results(tuple((p.name, p.read_text(encoding="utf-8")) for p in paths))
    failed = ["%s: %s" % (p.name, text) for p, (ok, text) in zip(paths, results, strict=True) if not ok]
    if failed:
        raise AssertionError("tools/strip_types.mjs refused:\n" + "\n".join(failed))
    return [text for _, text in results]


def module_text(path: Path) -> str:
    """module_texts() of one module. Every module of its folder goes through the one node run (cached), so the tests
    that read modules one at a time start node once."""
    folder = sorted(p for p in path.parent.iterdir() if p.suffix in (".ts", ".js") and p.is_file())
    return module_texts(folder)[folder.index(path)]
