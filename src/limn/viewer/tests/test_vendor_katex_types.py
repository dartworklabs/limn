"""The KaTeX declarations (src/limn/viewer/types/katex.d.ts) are what the vendored build is (docs/handbook/viewer.md §타입 검사).

The viewer draws Markdown math with a hand-written subset of KaTeX, so tsc trusts every member it declares. This test
is what makes that true: it loads the vendored module (src/limn/vendor/katex/katex.mjs, the file the page imports) under
node with a stand-in for the DOM calls KaTeX makes, takes the library out of it as the page does (texLibraryOf, pulled
from the served page), draws a formula and a refused one with the options the viewer passes, and compares what it sees
with the declaration:

- every declared interface is checked here, and every declared member of the library exists on the real object with
  its declared kind; render() returns nothing, draws into the element it is given, and with throwOnError throws the
  build's ParseError for TeX it refuses;
- the declared options are exactly the keys drawTexBox passes, each one the build's SETTINGS_SCHEMA knows, with a type
  the schema allows;
- the declaration names the vendored version.

Run: uv run pytest -q src/limn/viewer/tests/test_vendor_katex_types.py   (needs node)
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from limn.viewer import assemble

from helpers import PKG, VIEWER, extract_js_fn
from helpers_js import squash

DECLARATION = VIEWER / "types" / "katex.d.ts"
MODULE = PKG / "vendor" / "katex" / "katex.mjs"

# The script node runs: a stand-in document (KaTeX checks compatMode when it loads, and builds its output with these
# calls), the page's texLibraryOf, and the viewer's calls.
SCRIPT = r"""
import { pathToFileURL } from 'node:url';
class StandIn {
  constructor(tag) { this.tag = tag; this.childNodes = []; this.style = {}; this.className = ''; }
  appendChild(child) { this.childNodes.push(child); return child; }
  setAttribute() {}
  set textContent(text) { this.childNodes = text ? [{ text }] : []; }
}
globalThis.document = {
  compatMode: 'CSS1Compat',
  createElement: (tag) => new StandIn(tag),
  createElementNS: (space, tag) => new StandIn(tag),
  createTextNode: (text) => ({ text }),
  createDocumentFragment: () => new StandIn('#fragment'),
};
const loaded = await import(pathToFileURL(process.argv[2]).href);
%s
const library = texLibraryOf(loaded);
const options = JSON.parse(process.argv[3]);
const kind = (value) => (value === null ? 'null' : typeof value);
const box = new StandIn('code');
box.textContent = 'before';
const drawn = library.render('x^2', box, { ...options, displayMode: false });
let refused = null;
try {
  library.render('\\frac{', new StandIn('code'), { ...options, displayMode: true });
} catch (error) {
  refused = { parseError: error instanceof loaded.ParseError, name: error.name };
}
const schema = Object.fromEntries(
  Object.keys(options).map((key) => [key, loaded.SETTINGS_SCHEMA[key] ? loaded.SETTINGS_SCHEMA[key].type : null]),
);
console.log(JSON.stringify({
  isDefault: library === loaded.default,
  members: { render: kind(library.render) },
  renderLength: library.render.length,
  drawn: kind(drawn),
  childClass: box.childNodes.map((node) => node.className),
  refused,
  schema,
  version: loaded.version,
  others: [texLibraryOf({ render() {} }) !== null, texLibraryOf({ default: { render: 1 } }), texLibraryOf(null),
    texLibraryOf({}), texLibraryOf('katex')],
}));
"""


def declared_members(text: str) -> dict[str, dict[str, str]]:
    """Each `interface Katex...` block of the declaration as name -> members: a property by its name with its type, a
    method as `name()` with its return type."""
    out = {}
    for name, body in re.findall(r"^interface (Katex\w+) \{\n(.*?)^\}", text, re.M | re.S):
        members = {}
        for member, rest in re.findall(r"^  (\w+)(\(.*;|\??: .*;)$", body, re.M):
            if rest.startswith("("):
                members[member + "()"] = rest[rest.rindex("): ") + 3 : -1]
            else:
                members[member] = rest[rest.index(": ") + 2 : -1]
        out[name] = members
    return out


def passed_options() -> dict:
    """The options drawTexBox passes to render(), read off the served page as booleans by name."""
    text = squash(extract_js_fn("drawTexBox"))
    found = re.search(r"library\.render\(tex,box,\{([^}]*)\}\)", text)
    if not found:
        raise AssertionError("drawTexBox's render() call is not found in the served page")
    out = {}
    for pair in found.group(1).split(","):
        key, value = pair.split(":")
        out[key] = value in ("true", "display")
    return out


@unittest.skipUnless(shutil.which("node"), "node not available")
class DeclarationMatchesBuild(unittest.TestCase):
    """The declared KaTeX members, against the vendored build drawing formulas."""

    @classmethod
    def setUpClass(cls):
        cls.text = DECLARATION.read_text(encoding="utf-8")
        cls.options = passed_options()
        with tempfile.TemporaryDirectory() as folder:
            probe = Path(folder) / "probe.mjs"
            probe.write_text(
                SCRIPT
                % "\n".join(
                    [extract_js_fn("isRecord"), extract_js_fn("isKatexLibrary"), extract_js_fn("texLibraryOf")]
                ),
                encoding="utf-8",
            )
            done = subprocess.run(
                [shutil.which("node"), str(probe), str(MODULE), json.dumps(cls.options)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        if done.returncode != 0:
            raise AssertionError("node failed:\n%s" % done.stderr)
        cls.observed = json.loads(done.stdout.strip().splitlines()[-1])

    def test_the_declaration_has_the_library_and_its_options_and_nothing_else(self):
        """Mutation: add an interface to the declaration -> fails."""
        self.assertEqual(set(declared_members(self.text)), {"KatexLibrary", "KatexRenderOptions"})

    def test_the_library_is_the_modules_default_export_with_each_declared_member(self):
        """texLibraryOf takes the module's default export, and each declared member is on it with its kind: render()
        takes the three declared arguments. Mutation: declare a member the build lacks -> fails."""
        library = declared_members(self.text)["KatexLibrary"]
        self.assertTrue(self.observed["isDefault"])
        self.assertEqual({member.rstrip("()") for member in library}, set(self.observed["members"]))
        for member in library:
            self.assertEqual(self.observed["members"][member.rstrip("()")], "function", member)
        self.assertEqual(library["render()"], "void")
        self.assertEqual(self.observed["renderLength"], 3)

    def test_render_draws_into_its_element_returns_nothing_and_throws_a_parse_error_for_refused_tex(self):
        self.assertEqual(self.observed["drawn"], "undefined")
        self.assertEqual(self.observed["childClass"], ["katex"])  # what the element held is replaced
        self.assertEqual(self.observed["refused"], {"parseError": True, "name": "ParseError"})

    def test_the_options_are_the_keys_the_viewer_passes_each_of_a_type_the_build_allows(self):
        """Mutation: pass another option in drawTexBox, or declare one as another type -> fails."""
        declared = declared_members(self.text)["KatexRenderOptions"]
        self.assertEqual(set(declared), set(self.options))
        for key, type_text in declared.items():
            with self.subTest(option=key):
                allowed = self.observed["schema"][key]
                self.assertIsNotNone(allowed, "the build's SETTINGS_SCHEMA has no %s" % key)
                allowed = allowed if isinstance(allowed, list) else [allowed]
                self.assertIn(type_text, allowed)

    def test_nothing_but_an_object_with_render_is_the_library(self):
        self.assertEqual(self.observed["others"], [True, None, None, None, None])

    def test_the_declaration_names_the_vendored_version(self):
        """The declaration is written against one build: updating the vendored KaTeX means reading it again."""
        self.assertEqual(self.observed["version"], assemble.KATEX_VERSION)
        self.assertRegex(self.text, r"katex\s+(?://\s+)?%s\b" % re.escape(assemble.KATEX_VERSION))
