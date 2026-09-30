"""The `el` field of a figure pin: which element of a figure's map the pin points at (docs/handbook/api.md §그림 문서의
pick·핀).

A figure pin records its element as {id, path, label?, part?, impl?: {file, lo, hi}, frac?}: id is the element's
map id, path the ids from the page root down to it, label and part its display names, impl the lines of its shared
implementation (file relative to the document's folder), frac its box [x, y, w, h] on the build the pin was placed
on. The record check (limn.pins.record) accepts a stored value by its shape alone (is_element_record); readers lift
it with element_of; the pick and the request parsers write PinElement.to_record(). Pure.
"""

from dataclasses import dataclass
from typing import Any, TypeAlias, TypeGuard

from limn.platform.values import is_finite_num, is_int, is_num

# An element's box on its page: x, y, w, h in page fractions, origin top left (limn.builds.figure_map.Frac).
ElementFrac: TypeAlias = tuple[float, float, float, float]
EL_TEXT_MAX = 200
EL_PATH_MAX = 64
EL_FILE_MAX = 1024
EL_LINE_MAX = 1_000_000


def canonical_impl_path(path: str) -> bool:
    """Accept only canonical relative display paths; this grants no permission to read them."""
    return "\\" not in path and "\x00" not in path and all(part not in ("", ".", "..") for part in path.split("/"))


@dataclass(frozen=True)
class ElementImpl:
    """Where an element's shared implementation is: a file relative to the document's folder, lines lo..hi."""

    file: str
    lo: int
    hi: int


@dataclass(frozen=True)
class PinElement:
    """A figure pin's element: its map id, the ids from the page root down to it, its label and part when the map
    names them, its shared implementation when the map records one, and its box on the build it was pinned on."""

    id: str
    path: tuple[str, ...]
    label: str | None = None
    part: str | None = None
    impl: ElementImpl | None = None
    frac: ElementFrac | None = None

    def to_record(self) -> dict[str, Any]:
        """The shape stored in a record and answered by the API: id and path, then label, part, impl and frac only
        when set, in that order (lists for path and frac)."""
        out: dict[str, Any] = {"id": self.id, "path": list(self.path)}
        if self.label is not None:
            out["label"] = self.label
        if self.part is not None:
            out["part"] = self.part
        if self.impl is not None:
            out["impl"] = {"file": self.impl.file, "lo": self.impl.lo, "hi": self.impl.hi}
        if self.frac is not None:
            out["frac"] = list(self.frac)
        return out


def is_element_record(v: object) -> TypeGuard[dict[str, Any]]:
    """Is v a stored `el` the store may trust? An object whose id is a non-empty string and whose path is a list of
    strings; label and part strings when present (null counts as absent); impl, when present, {file: string,
    lo: integer, hi: integer}; frac, when present, a list of four numbers. Keys it does not know pass."""
    if not isinstance(v, dict):
        return False
    eid, path = v.get("id"), v.get("path")
    if not (isinstance(eid, str) and eid and isinstance(path, list) and all(isinstance(p, str) for p in path)):
        return False
    if any(v.get(k) is not None and not isinstance(v[k], str) for k in ("label", "part")):
        return False
    impl = v.get("impl")
    if impl is not None and not (
        isinstance(impl, dict)
        and isinstance(impl.get("file"), str)
        and is_int(impl.get("lo"))
        and is_int(impl.get("hi"))
    ):
        return False
    frac = v.get("frac")
    return frac is None or (isinstance(frac, list) and len(frac) == 4 and all(is_num(x) for x in frac))


def element_of(v: object) -> PinElement | None:
    """The element a stored `el` names, or None when v is missing, null or not a shape is_element_record accepts.

    Total: is_element_record's frac check is shape-only (is_num, any int or float), so a stored frac may hold a
    NaN, an Infinity or an integer too large for float() to hold - each a line the store still keeps. Such a frac
    is dropped here (the rest of the element is still lifted) instead of raising, so a reader that calls this on
    every open row (listing.projection.pins_payload, listing.markdown's pins.md facts, before any write) never turns one
    bad line into a failed GET/POST for every pin."""
    if not is_element_record(v):
        return None
    impl, frac = v.get("impl"), v.get("frac")
    safe_frac = None
    if frac is not None and all(is_finite_num(x) for x in frac):
        safe_frac = (float(frac[0]), float(frac[1]), float(frac[2]), float(frac[3]))
    return PinElement(
        v["id"],
        tuple(v["path"]),
        v.get("label"),
        v.get("part"),
        None if impl is None else ElementImpl(impl["file"], impl["lo"], impl["hi"]),
        safe_frac,
    )
