"""Every class a viewer CSS rule selects is one the viewer can put on an element (issue #418).

A rule whose class nothing writes styles nothing and only misleads the next reader: `.nav-sp`, `.arc-n`, the tool bar's label
`.chip` and `.rv-close` outlived their markup by weeks, and two tests pinned the dead `.chip` text. A class counts as
written when its name stands as a whole word (not inside a longer name) in the page template (index.html), a viewer script,
or the Python under src/limn that serves HTML. The viewer builds some names at run time from a fixed prefix
(`'nk-'+kind`, `ev-${m.ev}`); BUILT lists each such family with the script that builds it and the values it joins, and
only those exact names pass unnamed - a static class that shares a family's prefix (`.mdc-note`, `.rd-no`) must still
appear by name. KEPT names the classes kept with no writer on purpose.

This is a lower bound: a name that also occurs as a plain word in a script (`chip`, `open`) passes whether or not an element
carries it. It catches what the issue's audit found by hand - a class whose name is nowhere outside the CSS.
"""

import re
import unittest
from pathlib import Path

VIEWER = Path(__file__).resolve().parents[1]
CSS_DIR = VIEWER / "css"
JS_DIR = VIEWER / "js"
SRC = VIEWER.parent

# Class families the viewer names at run time: prefix -> (the script that builds the name from it, the values it joins).
# Only prefix+value passes unnamed; a value is a quoted string in a script (a number for a depth).
BUILT = {
    "band-": ("layout.js (the screen band on <body>)", {"short", "tablet-sheet"}),
    "lay-": ("layout.js (the layout on <body>)", {"mid", "narrow"}),
    "dot-": ("notices.js (the red dot on the control a message leads to)", {"rv", "side"}),
    "nk-": ("notices.js, status.js (a message's kind)", {"err", "info", "ok", "warn"}),
    "ev-": ("card-parts.js (a thread's state record)", {"assign", "close", "confirm", "reopen"}),
    "rd-": ("revisions.js, suggest.js (a diff line's kind)", {"del", "file", "hunk", "meta"}),
    "md-al-": ("md-surface.js (a Markdown table cell's alignment)", {"center", "left", "right"}),
    "mdc-chip-": ("md-compare.js (a change chip's kind)", {"pin"}),
    "mdc-": ("md-compare.js (a compared block's change)", {"del", "ins", "mod", "move"}),
    "ol-depth-": ("outline.js (an outline entry's depth)", {"0", "1", "2", "3", "4"}),
    "ic-": ("markup.js (an icon's name)", {"check", "minus", "pencil"}),
}
BUILT_NAMES = {p + v for p, (_, values) in BUILT.items() for v in values}
# Classes kept with no writer, and why.
KEPT = {
    "badge-default": "a badge variant of the component set (docs/handbook/viewer.md §디자인 토큰과 컴포넌트, 배지)",
    "badge-destructive": "a badge variant of the component set (docs/handbook/viewer.md §디자인 토큰과 컴포넌트, 배지)",
}

CLASS = re.compile(r"\.(-?[A-Za-z_][\w-]*)")


def selector_classes(css: str) -> set[str]:
    """The class names the selectors of one CSS text select: comments, at-rule preludes, attribute selectors and quoted
    strings are not read (a `[href$=".pdf"]` names no class)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: set[str] = set()
    for m in re.finditer(r"([^;{}]*)\{", css):
        sel = m.group(1).strip()
        if sel.startswith("@"):
            continue
        out.update(CLASS.findall(re.sub(r"\[[^\]]*\]|\"[^\"]*\"|'[^']*'", "", sel)))
    return out


def viewer_classes() -> dict[str, list[str]]:
    """Class name -> the viewer CSS parts that select it."""
    out: dict[str, list[str]] = {}
    for path in sorted(CSS_DIR.glob("*.css")):
        for c in selector_classes(path.read_text(encoding="utf-8")):
            out.setdefault(c, []).append(path.name)
    return out


def writers() -> str:
    """The texts that can put a class on an element: the page template, the viewer scripts, and the Python under
    src/limn (server-made HTML), tests excepted."""
    parts = [(VIEWER / "index.html").read_text(encoding="utf-8")]
    parts += [p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js"))]
    parts += [p.read_text(encoding="utf-8") for p in sorted(VIEWER.glob("*.mjs"))]
    parts += [p.read_text(encoding="utf-8") for p in sorted(SRC.rglob("*.py")) if "tests" not in p.parts]
    return "\n".join(parts)


def named(name: str, text: str) -> bool:
    """Does name stand in text as a whole class name (not part of a longer one)?"""
    return re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", text) is not None


def unwritten(classes, text: str) -> list[str]:
    """The classes neither named in text, nor a name a BUILT family joins, nor KEPT."""
    return sorted(c for c in classes if c not in KEPT and c not in BUILT_NAMES and not named(c, text))


class ViewerCssClasses(unittest.TestCase):
    """No viewer CSS rule selects a class the viewer never writes."""

    @classmethod
    def setUpClass(cls):
        cls.classes = viewer_classes()
        cls.text = writers()

    def test_every_selected_class_is_written(self):
        """Every class a rule selects is named by the template, a script or the server, or is a name a BUILT family joins."""
        dead = unwritten(self.classes, self.text)
        self.assertEqual(
            [(c, self.classes[c]) for c in dead], [], "remove these rules, or list the class with a reason"
        )

    def test_every_built_family_is_still_built_and_selected(self):
        """Each BUILT prefix is still joined to a value in a script ('nk-'+…, `ev-${…}`); each name it lists is selected by
        a rule, is not also written whole (then it needs no listing), and its value stands quoted in a script (a depth
        is a number) - so the list never outlives the family or names a value no script has."""
        scripts = "\n".join(p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js")))
        for prefix, (_, values) in BUILT.items():
            with self.subTest(prefix=prefix):
                self.assertRegex(scripts, r"[\s'\"`]" + re.escape(prefix) + r"(?:['\"]\s*\+|\$\{)")
            for value in sorted(values):
                with self.subTest(name=prefix + value):
                    self.assertIn(prefix + value, self.classes)
                    self.assertFalse(named(prefix + value, self.text))
                    if not value.isdigit():
                        self.assertRegex(scripts, "['\"`]" + re.escape(value) + "['\"`]")

    def test_every_kept_class_is_selected_and_unwritten(self):
        """A KEPT class is still selected by a rule and still has no writer; once something writes it, it leaves KEPT."""
        for name, why in KEPT.items():
            with self.subTest(name=name):
                self.assertTrue(why.strip())
                self.assertIn(name, self.classes)
                self.assertFalse(named(name, self.text))

    def test_a_planted_dead_class_is_reported(self):
        """A rule for a class nothing writes is reported; a built or written one, a comment, an attribute value and an
        at-rule prelude are not."""
        css = (
            "/* .in-comment{} */ @media (max-width:359.98px){.planted-x{flex:1}} .nk-new,#bar1 .btn-icon{gap:0}"
            ' a[href$=".pdf"]{color:red}'
        )
        classes = selector_classes(css)
        self.assertEqual(classes, {"planted-x", "nk-new", "btn-icon"})
        self.assertEqual(unwritten(classes, '<b class="btn-icon">'), ["nk-new", "planted-x"])
        self.assertEqual(
            unwritten({"nk-err", "mdc-note", "rd-no"}, ""), ["mdc-note", "rd-no"]
        )  # a family's static class is not built
