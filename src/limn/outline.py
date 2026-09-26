"""Outline labels: the section numbers and titles LaTeX wrote to a build's .aux, as the viewer's outline shows them.

The viewer's outline comes from the PDF's own bookmarks; LaTeX's numbering and page labels (``2.1``, ``iv``) are not in
there, so the server reads them from the ``\\@writefile{toc}{\\contentsline ...}`` lines of the .aux that the same page
build published (GET /api/outline-labels, docs/handbook/viewer.md). This module is the pure parser of that text:
no files, no clock. Reading the .aux of the build on screen is limn.meta.outline_labels.

The title conversion is deliberately conservative - a display conversion of a few text macros, never a TeX
evaluator. A title it cannot convert keeps a placeholder row with empty number and title, so the viewer can never
shift every later number onto the wrong entry by index.
"""

from __future__ import annotations

import re
from typing import Any

TOC_LEVELS = ("part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph")
LABELS_MAX = 200  # rows kept from one .aux
ANCHOR_MAX = 200  # characters kept of a hyperref anchor
PAGE_MAX = 40  # characters kept of a raw page label when the title cannot be converted
_WRAPPERS = {
    "textbf",
    "textit",
    "texttt",
    "textrm",
    "textsf",
    "textsc",
    "emph",
    "mbox",
    "ensuremath",
    "mathrm",
    "mathbf",
}


def tex_group(text: str, pos: int) -> tuple[str, int] | None:
    """The balanced ``{...}`` group starting at pos (after optional whitespace): (its content, the index just past its
    closing brace), or None when no group starts there or it never closes. A backslash escapes the next character, so
    ``\\{`` and ``\\}`` do not count as braces."""
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text) or text[pos] != "{":
        return None
    start, depth = pos + 1, 1
    pos += 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
            continue
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return text[start:pos], pos + 1
        pos += 1
    return None


def tex_plain(text: str, depth: int = 0) -> str:
    """The display text of a TeX title fragment: text macros unwrapped (\\textbf, \\emph, ... and \\texorpdfstring's PDF
    side), escaped specials kept, spacing macros as spaces, ``~`` as a space, ``---``/``--`` as dashes, whitespace
    collapsed. Conservative display conversion, never a TeX evaluator: raises ValueError for anything else (math, an
    unsupported macro, unbalanced braces, nesting past 12 or text over 4000 characters), and the caller omits the
    label."""
    if depth > 12 or len(text) > 4000:
        raise ValueError("complex title")
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "{":
            group = tex_group(text, i)
            if not group:
                raise ValueError("unbalanced title")
            value, i = group
            out.append(tex_plain(value, depth + 1))
        elif c == "\\":
            match = re.match(r"\\([A-Za-z@]+|.)", text[i:])
            if not match:
                raise ValueError("bad macro")
            macro = match[1]
            i += len(match[0])
            if macro in ("protect", "relax", "ignorespaces"):
                continue
            if macro in ("&", "%", "#", "_", "$", "{", "}"):
                out.append(macro)
            elif macro in (" ", ",", ";", "quad", "qquad", "enspace"):
                out.append(" ")
            elif macro in _WRAPPERS or macro == "texorpdfstring":
                first = tex_group(text, i)
                if not first:
                    raise ValueError("missing macro group")
                value, i = first
                if macro == "texorpdfstring":
                    second = tex_group(text, i)
                    if not second:
                        raise ValueError("missing PDF title")
                    value, i = second
                out.append(tex_plain(value, depth + 1))
            else:
                raise ValueError("unsupported title macro")
        elif c in "$^_}":
            raise ValueError("unsupported math title")
        else:
            out.append(" " if c == "~" else c)
            i += 1
    return " ".join("".join(out).replace("---", "—").replace("--", "–").split())


def toc_labels(source: str) -> list[dict[str, Any]]:
    """The outline rows of an .aux text, in file order, at most LABELS_MAX: each ``\\@writefile{toc}{\\contentsline
    {level}{[\\numberline {number}]title}{page}{anchor}}`` of a sectioning level (TOC_LEVELS) becomes
    {number, title, page, level, anchor}. Other levels (figures, custom lists) and malformed lines are skipped; a row
    whose number, title or page tex_plain cannot convert becomes a placeholder with empty number and title and the raw
    page (cut to PAGE_MAX), so later rows keep their positions."""
    labels: list[dict[str, Any]] = []
    for match in re.finditer(r"\\@writefile\s*\{toc\}", source):
        outer = tex_group(source, match.end())
        if not outer:
            continue
        line = outer[0]
        marker = re.match(r"\s*\\contentsline\s*", line)
        if not marker:
            continue
        groups, pos = [], marker.end()
        for _ in range(4):
            group = tex_group(line, pos)
            if not group:
                break
            value, pos = group
            groups.append(value)
        if len(groups) < 3 or groups[0] not in TOC_LEVELS:
            continue
        level, title, page = groups[:3]
        number, anchor = "", groups[3] if len(groups) > 3 else ""
        numberline = re.match(r"\s*(?:\\protect\s*)?\\numberline\s*", title)
        if numberline:
            group = tex_group(title, numberline.end())
            if not group:
                continue
            number, pos = group
            title = title[pos:]
        try:
            row = {
                "number": tex_plain(number),
                "title": tex_plain(title),
                "page": tex_plain(page),
                "level": level,
                "anchor": anchor[:ANCHOR_MAX],
            }
        except ValueError:
            # Keep a placeholder so consumers cannot shift all subsequent numbers by index.
            row = {"number": "", "title": "", "page": page[:PAGE_MAX], "level": level, "anchor": anchor[:ANCHOR_MAX]}
        labels.append(row)
        if len(labels) >= LABELS_MAX:
            break
    return labels
