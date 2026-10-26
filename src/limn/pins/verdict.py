"""A pin's `verdict`: the word a person picked for it with one press, and what the pin's place says it is about.

A verdict pin stores the `key` of one of its document's verdict words, exactly as the word file declared it when the
pin was made (docs/superpowers/specs/2026-10-26-verdict-pins.md §핀 레코드). Pins never read a word file: the
composition root hands pin creation the keys a document declares (limn.pins.needs.VerdictKeys). What pins own is the
stored field - how a stored value is read back - and the place's meaning:

- verdict_of: a stored verdict is promoted only when it is a string that is a key (VERDICT_KEY_RE, the word file's
  key rule). Anything else stays in the record as stored and the pin counts as one without a verdict - never as a
  broken line (limn.pins.record does not check the field). A key later dropped from the word file stays the pin's
  verdict.
- whole_figure: a figure pin whose element is its page's figure itself (el.path == [el.id]).
- whole_page_target: whether a pin's verdict is about a whole page's target - the figure of a figure document's page
  (whole_figure), or a view-only PDF's page (a region pin whose frac is the whole page, each value within
  PAGE_EPSILON). A LaTeX pin never is.

Pure.
"""

import re
from collections.abc import Mapping
from typing import Any

from limn.pins.element import element_of
from limn.pins.model import is_region_pin
from limn.platform.values import is_finite_num

# A verdict key: 1-16 Unicode letters, digits, '-' or '_' (Python's [\w-]), as limn.documents.verdicts.KEY_RE reads a
# word file's keys; tests/contracts/test_verdict_keys.py holds the two in agreement. It never holds '|' or a line break,
# so pins.md prints it as it is.
VERDICT_KEY_RE = re.compile(r"[\w-]{1,16}")
# How far a view-only PDF pin's frac may be from [0, 0, 1, 1] and still be the whole page.
PAGE_EPSILON = 1e-6
WHOLE_PAGE = (0.0, 0.0, 1.0, 1.0)


def is_verdict_key(v: object) -> bool:
    """Is v a string a verdict key may be (VERDICT_KEY_RE)?"""
    return isinstance(v, str) and VERDICT_KEY_RE.fullmatch(v) is not None


def verdict_of(record: Mapping[str, Any]) -> str | None:
    """The verdict a stored pin carries, or None when it has none: no field, or a value that is not a key-shaped
    string (is_verdict_key) - such a value stays in the record as stored and is not a verdict. Total."""
    v = record.get("verdict")
    return v if is_verdict_key(v) else None


def whole_figure(record: Mapping[str, Any]) -> str | None:
    """The figure id a pin names when its element is the whole figure of its page (a well-formed el whose path is
    [el.id]), else None. Only a figure document's pins carry an el."""
    el = element_of(record.get("el"))
    return el.id if el is not None and el.path == (el.id,) else None


def is_whole_page_frac(frac: object) -> bool:
    """Is frac a list of four finite JSON numbers, each within PAGE_EPSILON of [0, 0, 1, 1]?"""
    if not (isinstance(frac, list) and len(frac) == 4 and all(is_finite_num(x) for x in frac)):
        return False
    return all(abs(float(x) - want) <= PAGE_EPSILON for x, want in zip(frac, WHOLE_PAGE, strict=True))


def whole_page_target(record: Mapping[str, Any], figure_document: bool, view_only_document: bool) -> bool:
    """Is the pin about a whole page's target, as pins.md's '(쪽 전체)' says: on a figure document (figure_document,
    Doc.has_element_map), a pin whose element is the page's figure (whole_figure); on a view-only PDF
    (view_only_document, Doc.view_only), a region pin over the whole page (is_whole_page_frac) - the page and
    pdf_build it stores say which page. Never for a LaTeX document's pin, nor when the pin's document is unknown
    (both flags False)."""
    if figure_document:
        return whole_figure(record) is not None
    if view_only_document:
        return is_region_pin(record) and is_whole_page_frac(record.get("frac"))
    return False
