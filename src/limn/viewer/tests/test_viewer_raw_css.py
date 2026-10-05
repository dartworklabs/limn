"""Guard against raw design values in the viewer CSS (docs/handbook/viewer.md §컴포넌트 규격, §리터럴 예외).

Every CSS part under src/limn/viewer/css/ except tokens.css is read declaration by declaration. In the guarded properties
- colour (color, background*, border*-color), border radius, font size, spacing (padding*, margin*, gap) and the
height/min-height of a control (a button, input, select, textarea, button variant or segmented control) - a raw value
where a token exists is a finding, unless raw_css_allowlist.json lists it with its reason. Issue 189: controls added
after the tokens (the comparison PDF's zoom buttons) drifted from the component standard because nothing stopped a raw
value.
"""

import json
import re
import unittest
from pathlib import Path
from typing import NamedTuple

CSS_DIR = Path(__file__).resolve().parents[1] / "css"
ALLOWLIST = Path(__file__).with_name("raw_css_allowlist.json")
TOKEN_FILE = "tokens.css"

COLOUR_PROP = re.compile(r"color|background(?:-[a-z]+)*|border(?:-(?:top|right|bottom|left|block|inline))?-color")
RADIUS_PROP = re.compile(r"border(?:-[a-z]+)*-radius")
SPACING_PROP = re.compile(r"(?:padding|margin)(?:-[a-z]+)*|gap|row-gap|column-gap")
HEIGHT_PROP = re.compile(r"height|min-height")
COLOUR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(|"
    r"\b(?:white|black|red|green|blue|gray|grey|yellow|orange|purple|pink|silver)\b",
    re.I,
)
LENGTH = re.compile(r"(?<![\w.-])-?(?:\d+\.?\d*|\.\d+)(?:px|rem|em)\b")
RADIUS_OK = re.compile(r"var\(--radius(?:-sm|-lg)?\)|0|50%")
FONT_SIZE_OK = re.compile(r"var\(--text-(?:xs|sm|base|lg|xl)\)|inherit")
CONTROL = re.compile(r"(?:^|[^\w-])(?:button|input|select|textarea)(?![\w-])|\.btn-[a-z]+|\.seg(?![\w-])")


class Decl(NamedTuple):
    """One declaration of a CSS part: its file name, the rule's selector, the property and its value."""

    file: str
    selector: str
    prop: str
    value: str


def declarations(file: str, css: str) -> list[Decl]:
    """The declarations of one CSS part, comments removed and @media/@keyframes blocks flattened: each innermost
    `selector{...}` block gives one Decl per `property:value` pair."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", css):
        selector = " ".join(m.group(1).split())
        for part in m.group(2).split(";"):
            if ":" in part:
                prop, value = part.split(":", 1)
                out.append(Decl(file, selector, prop.strip(), value.strip()))
    return out


def top_level_split(text: str, seps: str) -> list[str]:
    """Split text on any character of seps that is outside parentheses and brackets (a selector list's commas, a
    selector's combinators), dropping empty pieces."""
    pieces, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if depth == 0 and ch in seps:
            pieces.append(cur)
            cur = ""
        else:
            cur += ch
    pieces.append(cur)
    return [p.strip() for p in pieces if p.strip()]


def is_control(selector: str) -> bool:
    """Whether some selector of the list has a control as its subject: its last compound (after the last top-level
    combinator) names a button, input, select or textarea, a button variant (.btn-*) or a segmented control (.seg). A
    pseudo-element subject (::after, a touch hit box) is not the control itself."""
    for one in top_level_split(selector, ","):
        subject = top_level_split(one, " >+~")[-1]
        if "::" not in subject and CONTROL.search(subject):
            return True
    return False


def raw_values(d: Decl) -> list[str]:
    """The raw values of one declaration where a token exists, by property: colour literals in a colour property; a
    radius other than the three radius tokens, 0 or 50%; a font size other than the text tokens; a non-zero length in
    spacing; a non-zero length in a control's height. Custom properties (token definitions) are not guarded."""
    prop, value = d.prop, d.value
    if prop.startswith("--"):
        return []
    if COLOUR_PROP.fullmatch(prop):
        return [m.group(0) for m in COLOUR.finditer(value)]
    if RADIUS_PROP.fullmatch(prop):
        return [t for t in value.split() if not RADIUS_OK.fullmatch(t)]
    if prop == "font-size":
        return [] if FONT_SIZE_OK.fullmatch(value) else [value]
    if SPACING_PROP.fullmatch(prop) or (HEIGHT_PROP.fullmatch(prop) and is_control(d.selector)):
        return [m.group(0) for m in LENGTH.finditer(value) if float(re.sub(r"[a-z]+$", "", m.group(0))) != 0]
    return []


def load_allowlist(path: Path = ALLOWLIST) -> dict:
    """The allowlist file: hairline values allowed in spacing, and entries (file, selector, property, value, reason)."""
    data: dict = json.loads(path.read_text(encoding="utf-8"))
    return data


def entry_key(file: str, selector: str, prop: str, value: str) -> tuple[str, str, str, str]:
    """An allowlist entry's identity: the CSS part, its selector, the property and the one raw value."""
    return (file, selector, prop, value)


def findings(decls: list[Decl], allow: dict) -> list[str]:
    """Every raw value of decls not allowed, as 'file: selector { property:value } <- raw': the allowlist's hairline
    values are allowed in spacing properties only, its entries for exactly their declaration and value."""
    hairline = set(allow["hairline"]["values"])
    listed = {entry_key(e["file"], e["selector"], e["property"], e["value"]) for e in allow["entries"]}
    bad = []
    for d in decls:
        for raw in raw_values(d):
            if SPACING_PROP.fullmatch(d.prop) and raw in hairline:
                continue
            if entry_key(d.file, d.selector, d.prop, raw) in listed:
                continue
            bad.append("%s: %s { %s:%s } <- %s" % (d.file, d.selector, d.prop, d.value, raw))
    return bad


def stale_entries(decls: list[Decl], allow: dict) -> list[tuple[str, str, str, str]]:
    """Allowlist entries no declaration's raw value matches any more (the rule changed or went): they must go."""
    present = {entry_key(d.file, d.selector, d.prop, raw) for d in decls for raw in raw_values(d)}
    keys = [entry_key(e["file"], e["selector"], e["property"], e["value"]) for e in allow["entries"]]
    return [k for k in keys if k not in present]


def viewer_declarations() -> list[Decl]:
    """The declarations of every viewer CSS part except tokens.css, the one place token values are defined."""
    out = []
    for path in sorted(CSS_DIR.glob("*.css")):
        if path.name != TOKEN_FILE:
            out.extend(declarations(path.name, path.read_text(encoding="utf-8")))
    return out


class RawCssValues(unittest.TestCase):
    """The viewer CSS uses tokens wherever one exists; the exceptions are listed with reasons."""

    def test_viewer_css_has_no_raw_values_outside_the_allowlist(self):
        """No CSS part outside tokens.css has a raw colour, radius, font size, spacing or control height that the
        allowlist does not name."""
        self.assertEqual(findings(viewer_declarations(), load_allowlist()), [])

    def test_every_allowlist_entry_still_matches_a_declaration(self):
        """An allowlist entry whose declaration changed or went is reported, so the list never outlives its reason."""
        self.assertEqual(stale_entries(viewer_declarations(), load_allowlist()), [])

    def test_every_allowlist_entry_gives_a_reason(self):
        """Each exception says why no token fits."""
        allow = load_allowlist()
        self.assertTrue(allow["hairline"]["reason"].strip())
        for e in allow["entries"]:
            with self.subTest(entry=e["selector"]):
                self.assertTrue(e["reason"].strip())

    def test_a_planted_raw_value_is_reported_in_each_guarded_property(self):
        """A raw value planted in each guarded property is reported, and the same rule written with tokens is not:
        the issue's zoom button height, a colour, a radius, a font size, a spacing step and a negative margin."""
        allow = {"hairline": {"values": ["1px", "2px"], "reason": "r"}, "entries": []}
        planted = (
            "#revision-zoom button{min-height:44px}",
            ".a{color:#fff}",
            ".a{background:rgb(0 0 0)}",
            ".a{border-color:white}",
            ".a{border-radius:7px}",
            ".a{font-size:13px}",
            ".a{margin-top:8px}",
            ".a{padding:0 var(--space-2) 12px}",
            ".a{gap:4px}",
            ".a{margin:0 -4px}",
            ".seg button{height:30px}",
            "input.n{min-height:2.5em}",
            "@media (pointer:coarse){button.btn-sm{min-height:44px}}",
        )
        for css in planted:
            with self.subTest(css=css):
                self.assertEqual(len(findings(declarations("x.css", css), allow)), 1)
        clean = (
            "#revision-zoom button{min-height:var(--hit)}"
            ".a{color:var(--foreground);background:color-mix(in srgb,var(--primary) 14%,transparent)}"
            ".a{border-radius:var(--radius-lg) var(--radius-lg) 0 0;font-size:var(--text-sm)}"
            ".a{margin:0 calc(-1 * var(--space-1));padding:1px var(--space-2);gap:2px}"
            ".row{min-height:40px;height:20px}"  # a row or a glyph is not a control
            "button::after{height:44px}"  # a touch hit box is not the control's drawn height
            ".a{--chip:28px}"  # a local token's definition
        )
        self.assertEqual(findings(declarations("x.css", clean), allow), [])

    def test_an_allowlisted_value_is_allowed_only_for_its_declaration(self):
        """An entry allows its one raw value in its own declaration; the same value elsewhere is still reported."""
        allow = {
            "hairline": {"values": [], "reason": "r"},
            "entries": [{"file": "x.css", "selector": ".msg.ev", "property": "padding-left", "value": "28px"}],
        }
        css = ".msg.ev{padding-left:28px}.msg{padding-left:28px}"
        self.assertEqual(findings(declarations("x.css", css), allow), ["x.css: .msg { padding-left:28px } <- 28px"])
        self.assertEqual(
            stale_entries(declarations("x.css", ".msg{padding-left:28px}"), allow),
            [("x.css", ".msg.ev", "padding-left", "28px")],
        )


if __name__ == "__main__":
    unittest.main()
