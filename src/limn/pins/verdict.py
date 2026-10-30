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
- superseded_by: which verdict pins a newer explicit verdict pin (one with a `verdict`) about the same target has
  overtaken, and which pin that is (ADR-0023). The order is ADR-0021 D4's - the newest live verdict pin about a target
  wins - read off the stored place with the rule the viewer's verdict order uses (order_target), so the page line, a
  card's '이전 판정' marker, GET /api/pins and pins.md name the same pin. A memo whose first word is a verdict word is
  not read (ADR-0021 D1): a repository that counts those too may find a newer current verdict than the one named.

Pure.
"""

import math
import re
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from limn.pins.element import element_of
from limn.pins.model import LineSpan, OpenPin, Pin, is_region_pin
from limn.platform.values import is_finite_num, is_int

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


# A document's kind as the verdict order reads it (limn.runtime.documents.DocKind: pins do not import the runtime).
TargetKind: TypeAlias = Literal["tex", "pdf", "figure"]


@dataclass(frozen=True)
class Placement:
    """What the edge reads of a verdict pin's document before the order is computed: doc, the key of the document the
    pin belongs to, and its kind. file is, for a LaTeX document, where the pin's file is on this machine now (the
    path overlaps count it in, so a moved checkout is one file). estimated, for a view-only PDF, is the API's `est` of
    the pin - its mark is only an estimate on the PDF on screen (limn.pins.location.position.pin_est)."""

    doc: str
    kind: TargetKind
    file: str | None = None
    estimated: bool = False


@dataclass(frozen=True)
class OrderTarget:
    """What one verdict pin is about, as its stored place says it: key, the pins about the same thing share it (the
    document's key and a name for the figure, the page or the lines). A pin about lines also holds whether it is open
    and its anchor, which decide whether two pins on the same lines are about the same text (same_lines); a pin
    about a whole figure or page holds neither (on_lines False)."""

    key: tuple[str, str]
    on_lines: bool = False
    open: bool = False
    anchor: tuple[Hashable, ...] | None = None

    @property
    def same_text(self) -> tuple[Hashable, ...]:
        """The classes of text this target belongs to, which same_lines compares: for a pin about lines, "open" when it
        is open (open pins' lines are matched to the text now) and its anchor when it has one; empty for any other
        target, which has no classes to share and is about the same thing as any other pin of its key."""
        if not self.on_lines:
            return ()
        return (("open",) if self.open else ()) + (() if self.anchor is None else (("anchor", self.anchor),))


def figure_root(record: Mapping[str, Any]) -> str | None:
    """The figure a figure document's pin is about: the first id of its element's path (el.path[0]), whatever element
    of the figure the pin names (ADR-0022 D1); None without a well-formed el, or with an empty path or root id."""
    el = element_of(record.get("el"))
    return el.path[0] if el is not None and el.path and el.path[0] else None


def _json_number(v: float) -> float | None:
    """A JSON number as the viewer holds it once parsed and written back: the nearest IEEE double (2**53 + 1 is 2**53,
    10**21 is 1e21, -0.0 is 0), or None - JSON.stringify's null - for one no double holds (a literal past 1.8e308) or
    a value that is not finite."""
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


def _json_key(v: object) -> Hashable:
    """v as a value that is equal to another's, and hashes alike, exactly when the two are the same JSON value as the
    viewer reads it: its JSON type beside what it holds. A number by the double it is (_json_number; JSON has one kind
    of number: 1 and 1.0 are one), and one no double holds is null as the viewer writes it; true and false never a
    number; a list item by item; an object by its keys and values whatever order they were written in. A hand-edited
    offset can be a list or an object, and must never make the anchor unhashable nor meet a value of another type: the
    list [0] is not the string "[0]", true is not 1 (#303). The viewer's anchorKey writes the anchor as JSON with sorted
    keys, which tells the same values apart."""
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        v = _json_number(v)
        if v is not None:
            return ("number", v)
    if v is None:
        return ("null",)
    if isinstance(v, str):
        return ("string", v)
    if isinstance(v, (list, tuple)):
        return ("array", tuple(_json_key(x) for x in v))
    if isinstance(v, Mapping):
        return ("object", frozenset((k, _json_key(x)) for k, x in v.items()))
    return ("other", type(v).__name__, repr(v))  # nothing a JSON record holds


def anchor_key(record: Mapping[str, Any]) -> tuple[Hashable, ...] | None:
    """A line pin's anchor - the text of its first and last lines when it was saved or last re-matched, with their
    distances from lo and hi - as one comparable, hashable value, or None when it has no anchor with a head and a tail
    text. Two anchors are one when their texts are and their offsets are the same JSON value (_json_key); a missing
    offset is null, as in the viewer's."""
    a = record.get("anchor")
    if not (isinstance(a, Mapping) and isinstance(a.get("head"), str) and isinstance(a.get("tail"), str)):
        return None
    return (a["head"], a["tail"], _json_key(a.get("head_off")), _json_key(a.get("tail_off")))


def order_target(pin: Pin, placed: Placement) -> OrderTarget | None:
    """The target a verdict pin is about, as far as its stored place says it without a project's rules (the viewer's
    verdictTargetOf, so the two never disagree), or None when it cannot be resolved:

    - figure document: its figure, el.path[0] (figure_root) - the pin on the figure itself and the one on a panel of
      it are about the same thing; None without an element path.
    - view-only PDF: its page, for a region pin over the whole page (whole_page_target) whose mark is not an estimate
      on the PDF on screen; any other region is None.
    - LaTeX document: its exact lines - the file as placed now, lo and hi - unless the pin lost its anchor (stale);
      a region pin has none.

    A lines target is only a candidate: the server re-matches an open pin's lines to the text now, never a closed
    one's, so same_lines says when two pins on the same lines are about the same text. Which lines are one item of
    the repository is the repository's rule, so None and 'not superseded' never say a pin is current."""
    r = pin.record
    if placed.kind == "figure":
        root = figure_root(r)
        return None if root is None else OrderTarget((placed.doc, "figure " + root))
    if placed.kind == "pdf":
        page = r.get("page")
        if placed.estimated or not whole_page_target(r, figure_document=False, view_only_document=True):
            return None
        return OrderTarget((placed.doc, "page %d" % page)) if is_int(page) else None
    span = pin.core.place
    if not isinstance(span, LineSpan) or r.get("stale") or placed.file is None:
        return None
    return OrderTarget(
        (placed.doc, "lines %s:%d-%d" % (placed.file, span.lo, span.hi)),
        on_lines=True,
        open=isinstance(pin, OpenPin),
        anchor=anchor_key(r),
    )


def same_lines(a: OrderTarget, b: OrderTarget) -> bool:
    """Are two pins on the same file and line numbers about the same text? Always for any other target. For lines:
    when both are open (their lines are matched to the text now), or both were saved on the same text (one anchor). A
    closed pin's numbers may be from an older text; without a shared anchor it is only its own target - never
    superseded, never another pin's current verdict. The same rule as sharing a class of OrderTarget.same_text, which
    superseded_by indexes."""
    if not (a.on_lines and b.on_lines):
        return True
    return bool(set(a.same_text) & set(b.same_text))


def superseded_by(pins: Sequence[Pin], placement_of: Callable[[Pin], Placement | None]) -> dict[int, int]:
    """For every verdict pin that is no longer its target's current verdict, the number of the newest verdict pin
    about the same thing: {pin id: that pin's id} (ADR-0023).

    pins are the live pins - open, awaiting review and done; a pin in the Trash is not among them, so a deleted
    verdict supersedes nothing, and one restored supersedes again. Only pins with a `verdict` field are read: a memo
    whose first word is a verdict word is an older verdict pin by the repository's convention and the server does not
    read memos (ADR-0021 D1), so it neither supersedes nor is superseded here. Verdict pins are grouped by order_target
    and a pin's current verdict is the newest pin of its group that is itself or about the same text (same_lines); a
    pin that is its own current verdict has no entry. Only verdict pins are asked for their placement (placement_of:
    None for a pin whose document the instance does not serve), so an instance without verdicts reads nothing. A pin
    whose target cannot be resolved has no entry.

    One pass to index each group's newest pin and, per class of text (OrderTarget.same_text), the newest pin of that
    class, and one pass to read each pin's answer off those indexes: linear in the verdict pins, whatever their
    number of anchors."""
    groups: dict[tuple[str, str], list[tuple[int, OrderTarget]]] = {}
    for pin in pins:
        if verdict_of(pin.record) is None:
            continue
        placed = placement_of(pin)
        target = None if placed is None else order_target(pin, placed)
        if target is not None:
            groups.setdefault(target.key, []).append((pin.core.pid, target))
    out: dict[int, int] = {}
    for group in groups.values():
        newest = max(pid for pid, _ in group)
        newest_of_class: dict[Hashable, int] = {}
        for pid, target in group:
            for c in target.same_text:
                if newest_of_class.get(c, 0) < pid:
                    newest_of_class[c] = pid
        for pid, target in group:
            current = max((newest_of_class[c] for c in target.same_text), default=pid) if target.on_lines else newest
            if current > pid:
                out[pid] = current
    return out
