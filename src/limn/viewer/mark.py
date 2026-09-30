"""The Limn logo in the viewer: the confirmed app icon (the letter i - a stem and a vermilion pin - on a squircle tile),
the browser favicon (the same i on a 먹 rounded square that fills the square) and the wordmark "limn", as the brand
source draws them.

Nothing is drawn here. dartworklabs/limn-sans draws every picture (site/limn-brand.js, `make icons`), and
src/limn/viewer/brand/ holds the files the app uses, byte for byte, with their SHA256SUMS and provenance (its README.md).
This module turns those bytes into what the viewer serves. It is pure - no files, no clock, no state: the composition
root reads the folder (server.read_brand) and passes the bytes to brand().

- ICON_ROUTES: the tab and home-screen icon routes and the file each serves unchanged - the favicon's 16 and 32 px
  pixel drawings on 먹 (one for light and dark tabs) and their .ico, and the 180 px full-bleed apple-touch-icon;
  RETIRED_ICON_ROUTES are the 0.3.6-0.3.7 dark paths, served for one release as the same favicon.
- MARK_SLOTS: the viewer page's placeholders for the inline logo and the SVG made for that size - the icon with the
  optical correction of 16 px (top bar) and 14 px ([더보기] label chip), the wordmark 20 px tall (help header).
- parse_svg(): one vendored SVG as a Drawing. The vocabulary is closed (svg, g, path and circle with their geometry
  attributes), and each brand colour becomes the part it paints: 뼈종이 the tile, 먹 a stroke, 주 the pin. Anything
  else is refused, so no markup or colour of the file reaches the page by accident.
- inline_svg(): a Drawing as the viewer's markup, with classes (limn-mark*) and never colours - the stylesheet's
  tokens paint the parts for the theme (docs/handbook/viewer.md §마크와 파비콘). Never plain .mark: that is the pin
  box on the PDF, which marks() removes and redraws.
"""

import hashlib
import html
import re
import xml.etree.ElementTree as ET  # stdlib only (docs/handbook/architecture.md §불변식 2); DOCTYPEs are refused first
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypeAlias

Role: TypeAlias = Literal["tile", "stroke", "pin"]
# The brand colours (limn-brand.js COLOR) in the light drawings the app vendors, and the part each paints. The dark
# theme's colours are the stylesheet's; the light files only say which shape is which.
ROLE_OF_FILL: Mapping[str, Role] = {"#fbf1e6": "tile", "#15161a": "stroke", "#e8452c": "pin"}
ROLE_CLASS: Mapping[Role, str] = {"tile": "limn-mark-tile", "stroke": "limn-mark-stroke", "pin": "limn-mark-pin"}

# GET path -> (file in src/limn/viewer/brand/, content type). /favicon.ico and /apple-touch-icon.png are also the paths
# browsers and iOS ask for on their own. The tab favicon is one drawing for light and dark tabs (the i on a 먹 rounded
# square); the touch icon is the app icon.
CURRENT_ICON_ROUTES: Mapping[str, tuple[str, str]] = {
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/favicon-16.png": ("favicon-16.png", "image/png"),
    "/favicon-32.png": ("favicon-32.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}
# Retired path -> the path whose file it serves, for 0.3.8 only (docs/handbook/api.md): 0.3.6-0.3.7 pages link a dark
# set and their head script points a dark-scheme tab at it, and the HTTP API removes a path only after a release that
# announces it. Remove these in the next release.
RETIRED_ICON_ROUTES: Mapping[str, str] = {
    "/favicon-dark.ico": "/favicon.ico",
    "/favicon-dark-16.png": "/favicon-16.png",
    "/favicon-dark-32.png": "/favicon-32.png",
}
ICON_ROUTES: Mapping[str, tuple[str, str]] = {
    **CURRENT_ICON_ROUTES,
    **{retired: CURRENT_ICON_ROUTES[current] for retired, current in RETIRED_ICON_ROUTES.items()},
}


@dataclass(frozen=True)
class Slot:
    """Where one inline logo goes: the SVG file drawn for that size, the class of the <svg> (limn-mark for the icon,
    limn-mark-word for the wordmark) and its accessible name - None for a decorative mark (aria-hidden), whose
    neighbouring text names the thing."""

    file: str
    css_class: Literal["limn-mark", "limn-mark-word"]
    label: str | None


MARK_SLOTS: Mapping[str, Slot] = {
    "__LIMN_MARK_16__": Slot("limn-icon-light-16.svg", "limn-mark", None),  # the top bar, before the label
    "__LIMN_MARK_14__": Slot("limn-icon-light-14.svg", "limn-mark", None),  # the [더보기] label chip
    "__LIMN_WORDMARK__": Slot("limn-wordmark-light-20.svg", "limn-mark-word", "Limn"),  # the help header's name
}
# Every file brand() reads.
FILES: frozenset[str] = frozenset([name for name, _ in ICON_ROUTES.values()] + [s.file for s in MARK_SLOTS.values()])

SVG_NS = "{http://www.w3.org/2000/svg}"
NUMBER = r"-?(?:\d+(?:\.\d*)?|\.\d+)"
NUMBER_RE = re.compile(NUMBER)
VIEW_BOX_RE = re.compile(r"%s(?: %s){3}" % (NUMBER, NUMBER))
PATH_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz0-9., -]+")
TRANSFORM_RE = re.compile(r"(?:(?:translate|scale)\(%s(?:[ ,]%s)?\) ?)+" % (NUMBER, NUMBER))
# The shape vocabulary: tag -> its geometry attributes, in the order they are written back.
SHAPES: Mapping[str, tuple[str, ...]] = {
    "path": ("d",),
    "circle": ("cx", "cy", "r"),
}
ROOT_ATTRS = frozenset({"viewBox", "width", "height", "role", "aria-label"})  # role and aria-label are replaced


@dataclass(frozen=True)
class Shape:
    """One filled shape: tag with its geometry attributes (name, value) in SHAPES order, painted as role - None when it
    takes the role of the group around it."""

    tag: Literal["path", "circle"]
    attrs: tuple[tuple[str, str], ...]
    role: Role | None


@dataclass(frozen=True)
class Group:
    """A <g>: an optional transform, the role its shapes inherit (None: each paints itself) and its children."""

    transform: str | None
    role: Role | None
    children: "tuple[Shape | Group, ...]"


@dataclass(frozen=True)
class Drawing:
    """One vendored SVG, parsed: its viewBox and size as written, and its parts. Every shape in it has a role."""

    view_box: str
    width: str
    height: str
    parts: tuple[Shape | Group, ...]


@dataclass(frozen=True)
class Icon:
    """One icon file as a route serves it: the bytes unchanged and their content type."""

    body: bytes
    content_type: str


@dataclass(frozen=True)
class Brand:
    """What the viewer takes from the brand folder: the icon each ICON_ROUTES path serves, the inline markup for each
    MARK_SLOTS placeholder, and key - 12 hex digits of sha256 over the served icons, the ?v= of their URLs, so a new
    drawing is never taken from a cache."""

    icons: Mapping[str, Icon]
    marks: Mapping[str, str]
    key: str


def _number(value: str | None, what: str) -> str:
    """value if it is a plain decimal number (what names it in the error); ValueError otherwise."""
    if value is None or not NUMBER_RE.fullmatch(value):
        raise ValueError("%s is not a number: %r" % (what, value))
    return value


def _role(element: ET.Element, inherited: Role | None) -> Role | None:
    """The role element paints: its fill's (ValueError for a fill that is not a vendored brand colour), else the one it
    inherits."""
    fill = element.get("fill")
    if fill is None:
        return inherited
    if fill not in ROLE_OF_FILL:
        raise ValueError("fill %r is not a brand colour" % fill)
    return ROLE_OF_FILL[fill]


def _blank(element: ET.Element) -> None:
    """ValueError if element carries text (inside it or after it): the vocabulary has shapes only."""
    if (element.text or "").strip() or (element.tail or "").strip():
        raise ValueError("text in the drawing: %r" % ((element.text or "") + (element.tail or "")).strip())


def _part(element: ET.Element, inherited: Role | None) -> Shape | Group:
    """One child of the drawing as a Shape or Group, painted as its own fill or the inherited role. ValueError for an
    element or attribute outside the vocabulary, a malformed value, or a shape that nothing paints."""
    _blank(element)
    tag = element.tag.removeprefix(SVG_NS) if element.tag.startswith(SVG_NS) else "(no namespace) " + element.tag
    role = _role(element, inherited)
    own = role if "fill" in element.attrib else None  # written on this element; otherwise it comes from the group
    if tag == "g":
        if set(element.attrib) - {"transform", "fill"}:
            raise ValueError("g attributes %s" % sorted(set(element.attrib) - {"transform", "fill"}))
        transform = element.get("transform")
        if transform is not None and not TRANSFORM_RE.fullmatch(transform):
            raise ValueError("transform %r" % transform)
        return Group(transform, own, tuple(_part(child, role) for child in element))
    if tag not in SHAPES:
        raise ValueError("element %r is not in the logo's vocabulary" % tag)
    names = SHAPES[tag]
    if set(element.attrib) - {"fill"} != set(names) or len(element):
        raise ValueError("%s attributes %s" % (tag, sorted(element.attrib)))
    if role is None:
        raise ValueError("a %s that nothing paints" % tag)
    if tag == "path":
        d = element.get("d", "")
        if not PATH_RE.fullmatch(d):
            raise ValueError("path data %r" % d[:40])
        return Shape("path", (("d", d),), own)
    attrs = tuple((name, _number(element.get(name), "%s %s" % (tag, name))) for name in names)
    return Shape("circle", attrs, own)


def parse_svg(text: str) -> Drawing:
    """One vendored SVG file (limn-sans `make icons` output) as a Drawing.

    The root must be an SVG <svg> with a numeric viewBox, width and height (role and aria-label are dropped; the viewer
    sets its own); below it only g, path and circle with their geometry attributes, a transform on a g, and a
    fill that is one of the brand colours in ROLE_OF_FILL. A DOCTYPE (and so any entity) is refused before parsing.
    ValueError for anything else - the file is a packaging defect then, and start() fails rather than inline it."""
    if "<!" in text:
        raise ValueError("a DOCTYPE, entity or comment in the drawing")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError("not XML: %s" % e) from e
    if root.tag != SVG_NS + "svg":
        raise ValueError("root is %r, not an SVG <svg>" % root.tag)
    if set(root.attrib) - ROOT_ATTRS:
        raise ValueError("svg attributes %s" % sorted(set(root.attrib) - ROOT_ATTRS))
    _blank(root)
    view_box = root.get("viewBox") or ""
    if not VIEW_BOX_RE.fullmatch(view_box):
        raise ValueError("viewBox %r" % view_box)
    parts = tuple(_part(child, None) for child in root)
    if not parts:
        raise ValueError("an empty drawing")
    return Drawing(view_box, _number(root.get("width"), "svg width"), _number(root.get("height"), "svg height"), parts)


def _markup(part: Shape | Group) -> str:
    """One part as markup: its geometry attributes (HTML-escaped) and the class of its role, never a colour."""
    cls = "" if part.role is None else ' class="%s"' % ROLE_CLASS[part.role]
    if isinstance(part, Group):
        transform = "" if part.transform is None else ' transform="%s"' % html.escape(part.transform, quote=True)
        return "<g%s%s>%s</g>" % (transform, cls, "".join(_markup(child) for child in part.children))
    attrs = "".join(' %s="%s"' % (name, html.escape(value, quote=True)) for name, value in part.attrs)
    return "<%s%s%s/>" % (part.tag, cls, attrs)


def inline_svg(drawing: Drawing, css_class: Literal["limn-mark", "limn-mark-word"], label: str | None = None) -> str:
    """The viewer's markup for drawing: an <svg> of class css_class with the drawing's viewBox and size and each part
    classed by its role (limn-mark-tile, limn-mark-stroke, limn-mark-pin) - no colour anywhere, the stylesheet paints
    them. Decorative (aria-hidden) without a label, otherwise an image named label. Deterministic."""
    a11y = 'role="img" aria-label="%s"' % html.escape(label, quote=True) if label else 'aria-hidden="true"'
    return '<svg class="%s" viewBox="%s" width="%s" height="%s" %s focusable="false">%s</svg>' % (
        css_class,
        drawing.view_box,
        drawing.width,
        drawing.height,
        a11y,
        "".join(_markup(part) for part in drawing.parts),
    )


def content_key(icons: Mapping[str, Icon]) -> str:
    """12 hex digits of sha256 over every (path, bytes) of icons in path order - the same icons give the same key, a
    changed drawing a new one."""
    digest = hashlib.sha256()
    for path in sorted(icons):
        body = icons[path].body
        digest.update(b"%d %s\n" % (len(body), path.encode("utf-8")))
        digest.update(body)
    return digest.hexdigest()[:12]


def _slot_markup(slot: Slot, data: bytes) -> str:
    """The inline markup for slot from its SVG file's bytes (UTF-8, parse_svg, inline_svg). ValueError for bytes that
    are not UTF-8 or not a drawing in the vocabulary, its message starting with the file's name ("<file>: <reason>")."""
    try:
        return inline_svg(parse_svg(data.decode("utf-8")), slot.css_class, slot.label)
    except ValueError as e:  # UnicodeDecodeError is a ValueError
        raise ValueError("%s: %s" % (slot.file, e)) from e


def brand(files: Mapping[str, bytes]) -> Brand:
    """The viewer's logo from the brand folder's bytes (files: name -> bytes, at least FILES): the icon for every
    ICON_ROUTES path, the markup for every MARK_SLOTS placeholder (_slot_markup) and their content key. KeyError for a
    missing file, ValueError naming the file for a malformed SVG."""
    icons = {path: Icon(files[name], content_type) for path, (name, content_type) in ICON_ROUTES.items()}
    marks = {placeholder: _slot_markup(slot, files[slot.file]) for placeholder, slot in MARK_SLOTS.items()}
    return Brand(icons, marks, content_key(icons))
