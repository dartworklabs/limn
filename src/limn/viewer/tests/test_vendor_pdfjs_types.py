"""The PDF.js declarations (src/limn/viewer/types/pdfjs.d.ts) are what the vendored build is (docs/handbook/viewer.md §타입 검사).

The viewer is type-checked against a hand-written subset of PDF.js, so tsc trusts every member it declares. This test
is what makes that true: it loads the vendored module (src/limn/vendor/pdfjs/pdf.min.mjs, the same file the page imports)
under node, opens small PDFs with it, makes every call the viewer makes, and compares what comes back with the
declaration:

- every declared interface and member is observed, and every member observed is declared (a member added to the
  declaration without a call here, or one called here that the declaration lost, fails);
- every declared member exists on the real object with the declared kind, read off its declared type: a property of its JS
  type, a method that returns what it is declared to return (a promise that resolves to an object, an array, a number,
  null);
- the two interfaces the viewer only passes in (PdfDocumentSource, PdfRenderOptions) hold exactly the keys the calls
  below pass, and the calls succeed with them;
- what the declaration says where the build's own types are looser: getOutline() answers null for a PDF without
  bookmarks, an outline item always has a title and a dest (null without one), a destination's first element is a
  page reference or a page index, render() throws on a null context, and a cancelled render rejects with a
  RenderingCancelledException (the name pdf/view-draw.ts tests).

Run: uv run pytest -q src/limn/viewer/tests/test_vendor_pdfjs_types.py   (needs node)
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from limn.viewer import assemble

from helpers import MINI_PDF, PKG, VIEWER

DECLARATION = VIEWER / "types" / "pdfjs.d.ts"
VENDOR = PKG / "vendor" / "pdfjs"
# The tuple the declaration gives an outline destination, checked below against every destination the build gives.
DESTINATION = "type PdfDestination = [PdfPageReference | number | null, { name: string } | null, ...(number | null)[]];"

# The one interface a declared property names that is a class in the build, not an object: GlobalWorkerOptions.
CLASS_LIKE = {"PdfWorkerOptions"}
# The interfaces the viewer only passes in, with the keys it passes.
INPUTS = {
    "PdfDocumentSource": {"data", "isEvalSupported", "useWasm", "enableXfa"},
    "PdfRenderOptions": {"canvasContext", "viewport", "transform"},
}

# The script node runs: it makes the viewer's calls and records, per declared member, the kinds it found.
SCRIPT = r"""
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [, , libraryPath, outlinePath, plainPath] = process.argv;
const lib = await import(pathToFileURL(libraryPath).href);
const seen = {};
const kind = (value) =>
  value === null ? 'null' : Array.isArray(value) ? 'array' : value instanceof Promise ? 'promise' : typeof value;
const note = (interfaceName, member, found) => ((seen[interfaceName + '.' + member] ??= new Set()).add(found));
// Records the kinds of the members of value that the declaration names.
const props = (interfaceName, value, names) => names.forEach((name) => note(interfaceName, name, kind(value[name])));
// Records what a method call returns, and what its promise resolves to.
const returns = async (interfaceName, member, call) => {
  const result = call();
  const resolved = result instanceof Promise ? await result : undefined;
  note(interfaceName, member + '()', result instanceof Promise ? 'promise<' + kind(resolved) + '>' : kind(result));
  return resolved === undefined ? result : resolved;
};
const inputs = {};

if (typeof lib.getDocument !== 'function') throw new Error('the module has no getDocument');
props('PdfLibrary', lib, ['GlobalWorkerOptions']);
lib.GlobalWorkerOptions.workerSrc = pathToFileURL(libraryPath.replace('pdf.min.mjs', 'pdf.worker.min.mjs')).href;
props('PdfWorkerOptions', lib.GlobalWorkerOptions, ['workerSrc']);

const source = (path) => ({
  data: new Uint8Array(readFileSync(path)),
  isEvalSupported: false,
  useWasm: false,
  enableXfa: false,
});
inputs.PdfDocumentSource = Object.keys(source(plainPath));

const outlineTask = lib.getDocument(source(outlinePath));
note('PdfLibrary', 'getDocument()', kind(outlineTask));
props('PdfLoadingTask', outlineTask, ['promise']);
const doc = await outlineTask.promise;
props('PdfDocument', doc, ['numPages', 'loadingTask']);
if (doc.loadingTask !== outlineTask) throw new Error('loadingTask is not the task that opened the document');

const plainTask = lib.getDocument(source(plainPath));
const plain = await plainTask.promise;
await returns('PdfDocument', 'getOutline', () => plain.getOutline());

// The outline: every item, with the destinations it names (a string names one by its name).
const items = [];
const walk = (list) => list.forEach((item) => (items.push(item), walk(item.items)));
walk(await returns('PdfDocument', 'getOutline', () => doc.getOutline()));
for (const item of items) props('PdfOutlineItem', item, ['title', 'dest', 'items']);
const destinations = [];
for (const item of items) {
  if (typeof item.dest === 'string') {
    destinations.push(await returns('PdfDocument', 'getDestination', () => doc.getDestination(item.dest)));
  } else if (Array.isArray(item.dest)) destinations.push(item.dest);
}
await returns('PdfDocument', 'getDestination', () => doc.getDestination('no such destination'));
const shapes = [];
for (const destination of destinations) {
  shapes.push(destination.length);
  destination.forEach((element, index) => {
    if (index === 0) note('PdfDestination', '0', kind(element));
    else if (index === 1) note('PdfDestination', '1', kind(element) + (element && typeof element.name === 'string' ? ':name' : ''));
    else note('PdfDestination', 'rest', kind(element));
  });
  if (destination[0] && typeof destination[0] === 'object') {
    props('PdfPageReference', destination[0], ['num', 'gen']);
    await returns('PdfDocument', 'getPageIndex', () => doc.getPageIndex(destination[0]));
  }
}

const page = await returns('PdfDocument', 'getPage', () => doc.getPage(1));
const viewport = await returns('PdfPage', 'getViewport', () => page.getViewport({ scale: 1 }));
props('PdfViewport', viewport, ['width', 'height', 'transform']);
const transformLength = viewport.transform.length;
const content = await returns('PdfPage', 'getTextContent', () => page.getTextContent());
props('PdfTextContent', content, ['items', 'styles']);
for (const item of content.items) {
  props('PdfTextItem', item, ['str', 'transform', 'width', 'height', 'fontName', 'hasEOL']);
  props('PdfTextStyle', content.styles[item.fontName], ['fontFamily', 'ascent', 'descent']);
}

// A render onto a canvas that takes every drawing call and does nothing.
const canvas = { width: 200, height: 400, getContext: () => context };
const context = new Proxy(
  { canvas, getTransform: () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }) },
  { get: (target, name) => (name in target ? target[name] : () => {}), set: () => true },
);
const renderOptions = { canvasContext: context, viewport, transform: [1, 0, 0, 1, 0, 0] };
inputs.PdfRenderOptions = Object.keys(renderOptions);
const drawn = await returns('PdfPage', 'render', () => page.render(renderOptions));
props('PdfRenderTask', drawn, ['promise']);
await drawn.promise;
const cancelled = page.render(renderOptions);
await returns('PdfRenderTask', 'cancel', () => cancelled.cancel());
let cancelName = null;
try {
  await cancelled.promise;
} catch (error) {
  cancelName = (error instanceof Error ? 'Error ' : '') + error.name;
}
let nullContext = null;
try {
  page.render({ ...renderOptions, canvasContext: null });
} catch (error) {
  nullContext = error.name;
}

await returns('PdfLoadingTask', 'destroy', () => outlineTask.destroy());
await plainTask.destroy();
const out = {
  seen: Object.fromEntries(Object.entries(seen).map(([key, value]) => [key, [...value].sort()])),
  inputs,
  destinationLengths: shapes.sort(),
  transformLength,
  cancelName,
  nullContext,
};
console.log(JSON.stringify(out));
"""


def fixture_pdf() -> bytes:
    """A two-page PDF with text on its first page, named destinations, and an outline with a nested item, an item
    without a destination, a Fit view, an XYZ view and a page named by its index: what the viewer's calls meet."""
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R /Outlines 7 0 R /Dests << /named [4 0 R /XYZ 20 360 null] >> >>",
        2: b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 400] /Contents 5 0 R"
        b" /Resources << /Font << /F1 6 0 R >> >> >>",
        4: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 400] >>",
        5: b"<< /Length 44 >>\nstream\nBT /F1 12 Tf 20 350 Td (Reviewer one) Tj ET\nendstream",
        6: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        7: b"<< /Type /Outlines /First 8 0 R /Last 10 0 R /Count 4 >>",
        8: b"<< /Title (Alpha) /Parent 7 0 R /Dest (named) /First 11 0 R /Last 11 0 R /Count 1 /Next 9 0 R >>",
        9: b"<< /Title (Beta) /Parent 7 0 R /Dest [4 0 R /Fit] /Prev 8 0 R /Next 10 0 R >>",
        10: b"<< /Title (Gamma) /Parent 7 0 R /Dest [1 /XYZ 10 10 null] /Prev 9 0 R >>",
        11: b"<< /Title (Child) /Parent 8 0 R >>",
    }
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for number, body in objects.items():
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    size = len(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    out += b"".join(b"%010d 00000 n \n" % offsets[number] for number in sorted(objects))
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref)
    return bytes(out)


def declared_members(text: str) -> dict[str, dict[str, str]]:
    """Each `interface Pdf...` block of the declaration as name -> members: a property by its name with its declared type,
    a method as `name()` with its declared return type."""
    out = {}
    for name, body in re.findall(r"^interface (Pdf\w+) \{\n(.*?)^\}", text, re.M | re.S):
        members = {}
        for member, rest in re.findall(r"^  (\w+)(\(.*;|\??: .*;)$", body, re.M):
            if rest.startswith("("):
                members[member + "()"] = rest[rest.rindex("): ") + 3 : -1]
            else:
                members[member] = rest[rest.index(": ") + 2 : -1] + (" | undefined" if rest.startswith("?") else "")
        out[name] = members
    return out


def kinds_of(type_text: str, member: str) -> set[str]:
    """The kinds a value of a declared type has at run time, in the vocabulary of SCRIPT: typeof, plus array, null and
    promise. A property that is a Promise is `promise`; a method's Promise result is `promise<kind of what it resolves
    to>`. A type this does not know fails, so a new kind of member gets a rule here."""
    promised = re.fullmatch(r"Promise<(.*)>", type_text)
    if promised:
        inner = kinds_of(promised.group(1), member)
        return {"promise<%s>" % kind for kind in inner} if member.endswith("()") else {"promise"}
    out = set()
    for part in (p.strip() for p in type_text.split("|")):
        if part in ("number", "string", "boolean", "null"):
            out.add(part)
        elif part in ("void", "undefined"):
            out.add("undefined")
        elif part.endswith("[]") or part == "PdfDestination":
            out.add("array")
        elif part in CLASS_LIKE:
            out.add("function")
        elif part.startswith("Record<") or part.startswith("Pdf"):
            out.add("object")
        else:
            raise AssertionError("no rule for the declared type %r of %s" % (part, member))
    return out


@unittest.skipUnless(shutil.which("node"), "node not available")
class DeclarationMatchesBuild(unittest.TestCase):
    """The declared PDF.js members, against the vendored build opening real PDFs."""

    @classmethod
    def setUpClass(cls):
        """Runs SCRIPT once under node with the vendored module and two PDFs: the outline fixture, and MINI_PDF (no
        outline). The same observation serves every test."""
        cls.text = DECLARATION.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "outline.pdf").write_bytes(fixture_pdf())
            (Path(folder) / "plain.pdf").write_bytes(MINI_PDF)
            (Path(folder) / "probe.mjs").write_text(SCRIPT, encoding="utf-8")
            done = subprocess.run(
                [
                    shutil.which("node"),
                    str(Path(folder) / "probe.mjs"),
                    str(VENDOR / "pdf.min.mjs"),
                    str(Path(folder) / "outline.pdf"),
                    str(Path(folder) / "plain.pdf"),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        if done.returncode != 0:
            raise AssertionError("node failed:\n%s" % done.stderr)
        cls.observed = json.loads(done.stdout.strip().splitlines()[-1])

    def test_every_declared_interface_is_one_this_test_observes_or_passes_in(self):
        """No declared interface goes unchecked: each is observed on real objects or is an input the calls pass (the
        destination tuple is a type alias, checked on its own below).
        Mutation: add an interface to the declaration -> fails."""
        observed = {key.split(".")[0] for key in self.observed["seen"]}
        self.assertEqual(set(declared_members(self.text)), (observed - {"PdfDestination"}) | set(INPUTS))

    def test_every_declared_member_is_on_the_real_object_with_the_declared_kind(self):
        """The kinds the build's objects have, member by member, are the ones the declaration's types say, and a member
        the declaration lacks is not observed. Mutation: declare a property as another type, rename a member, or add
        one the build lacks -> fails."""
        for name, members in declared_members(self.text).items():
            if name in INPUTS:
                continue
            seen = {key.split(".", 1)[1] for key in self.observed["seen"] if key.split(".")[0] == name}
            self.assertEqual(seen, set(members), name)
            for member, type_text in members.items():
                with self.subTest(member="%s.%s" % (name, member)):
                    self.assertEqual(set(self.observed["seen"]["%s.%s" % (name, member)]), kinds_of(type_text, member))

    def test_the_input_interfaces_hold_the_keys_the_calls_pass_and_the_calls_succeed(self):
        """getDocument and render are given exactly the declared keys, and open and draw a page with them."""
        declared = declared_members(self.text)
        for name, keys in INPUTS.items():
            with self.subTest(interface=name):
                self.assertEqual(set(declared[name]), keys)
                self.assertEqual(set(self.observed["inputs"][name]), keys)
        self.assertIn("PdfRenderTask.promise", self.observed["seen"])  # the page was drawn to its end

    def test_a_destination_is_what_the_declared_tuple_says(self):
        """A destination's first element is a page reference or a page index, its second the view's name, the rest
        numbers or null; a Fit view has no more than the two.
        Mutation: change the declared tuple -> fails on its text."""
        self.assertIn(DESTINATION, self.text)
        seen = self.observed["seen"]
        self.assertEqual(set(seen["PdfDestination.0"]), {"object", "number"})
        self.assertEqual(set(seen["PdfDestination.1"]), {"object:name"})
        self.assertEqual(set(seen["PdfDestination.rest"]), {"null", "number"})
        self.assertEqual(self.observed["destinationLengths"], [2, 5, 5])

    def test_the_declaration_says_where_the_build_is_stricter_or_looser_than_its_own_types(self):
        """A viewport's matrix has six numbers, a null context makes render() throw, and a cancelled render rejects with
        an Error of the name the viewer tests for (pdf/view-draw.ts reads the name of an Error only)."""
        self.assertEqual(self.observed["transformLength"], 6)
        self.assertEqual(self.observed["nullContext"], "TypeError")
        self.assertEqual(self.observed["cancelName"], "Error RenderingCancelledException")

    def test_the_declaration_names_the_vendored_version(self):
        """The declaration is written against one build: updating the vendored PDF.js means reading the declaration again."""
        self.assertRegex(self.text, r"pdfjs-dist\s+(?://\s+)?%s\b" % re.escape(assemble.PDFJS_VERSION))
