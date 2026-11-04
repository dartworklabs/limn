"""The viewer under its enforced Content-Security-Policy (docs/adr/0026-viewer-csp.md), in Chromium, Firefox and WebKit.

Every other browser test hands the browser the server's policy as Report-Only and fails on any report
(tests/support/helpers_csp.py): Playwright's wait_for_function() evals its predicate in the page, which an enforced
policy refuses. These tests take the header as the server sends it, from a real HTTP server, and wait only with
Playwright's selector engine and promises the page resolves - nothing that needs eval in the page. They show that the
enforced policy lets the viewer do what it does - boot, the PDF.js module and its worker drawing a LaTeX manuscript, a
figure document and a view-only PDF, the help and Trash sheets - and that it refuses what it should: an inline script
whose text matches none of the page's hashes and an inline event handler, each reported. (It does not refuse a script
element pointing at a file of this origin, or one whose text matches a hash: those run whoever inserts them, and the
viewer's rules - StaticGuards below - keep them out.)

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_csp.py
"""

import ast
import html
import re
import tempfile
import threading
import unittest
from pathlib import Path

import helpers_csp
import helpers_figure
import helpers_js
from helpers import ps
from helpers_browser import BrowserBase


def two_page_pdf(first: tuple[int, int]) -> bytes:
    """A valid two-page PDF, page 1 `first` points and page 2 portrait letter, each with a filled square: the page count
    and shapes of helpers_figure.viewer_build's page images (WIDE_PX or TALL_PX, then TALL_PX, at 150 dpi)."""
    sizes = (first, (612, 792))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>"]
    for w, h in sizes:
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 5 0 R >>" % (w, h))
    objects.append(b"<< /Length 24 >>\nstream\n0 0 1 rg 20 20 80 80 re f\nendstream")
    output, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(output)


# Resolves once the page has drawn every page of the document on screen with PDF.js, or fails after the timeout - a
# promise the page itself resolves, so nothing is evaluated by Playwright's polling (which an enforced policy refuses).
DRAWN = """key => new Promise((resolve, reject) => {
  const done = () => DOC === key && META && VEC.doc && document.querySelectorAll('#doc .pg.drawn').length === META.pages.length;
  const t0 = performance.now();
  (function poll() {
    if (done()) return resolve(document.querySelectorAll('#doc .pg.drawn').length);
    if (performance.now() - t0 > 15000) return reject(new Error('not drawn: ' + key));
    requestAnimationFrame(poll);
  })();
})"""

# Puts in an inline script element with text the page did not carry and a button with an inline click handler, clicks
# it, and resolves with the directives of the two violations they report - in the page's own order of events. The two
# are expected (window.__limnCspExpected while they come in), so the gate (helpers_csp.no_csp_violation) leaves them
# out.
INJECT = """() => new Promise(resolve => {
  const got = []; window.__limnCspExpected = true;
  document.addEventListener('securitypolicyviolation', e => {
    got.push(e.effectiveDirective || e.violatedDirective);
    if (got.length === 2) { window.__limnCspExpected = false; resolve(got); }
  });
  const s = document.createElement('script'); s.textContent = 'window.__cspRan = 1'; document.body.append(s);
  const d = document.createElement('div'); d.innerHTML = '<button id="csp-probe" onclick="window.__cspClicked = 1">x</button>';
  document.body.append(d); document.getElementById('csp-probe').click();
})"""


class EnforcedFlows:
    """The flows, run on each engine's class below."""

    def setUp(self):
        """The manuscript, the figure document and the view-only PDF, each with a two-page build whose PDF copy is a real
        two-page PDF, served by a real HTTP server (the enforced header reaches the browser as sent)."""
        super().setUp()
        self.docs = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)
        for D in self.docs:
            build = Path(D.dir / (D.dir / "pages.cur").read_text().strip())
            (build / D.pdf_name).write_bytes(two_page_pdf((1152, 384) if D.has_element_map else (612, 792)))
        self.httpd = ps.Server(("127.0.0.1", 0), ps.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def enforced(self):
        """The viewer from the real server, with its policy enforced, after the first document is drawn."""
        context = self.browser.new_context(viewport={"width": 1400, "height": 850})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        response = page.goto("http://127.0.0.1:%d/?lang=ko" % self.httpd.server_address[1])
        policy = response.headers.get("content-security-policy", "")
        self.assertIn("script-src 'self' 'sha256-", policy)
        page.wait_for_selector("#doc .pg.drawn", timeout=20000)
        return page

    def violations(self, page):
        """The violations the page has reported (helpers_csp.CSP_WATCH keeps them in the page)."""
        return page.evaluate("window.__limnCspViolations")

    def test_every_kind_of_document_is_drawn_by_pdf_js_under_the_enforced_policy(self):
        """The manuscript, the figure document and the view-only PDF are each drawn by the PDF.js module and its worker
        (import() and the worker from 'self'); the help and Trash sheets open; nothing is refused."""
        page = self.enforced()
        for D in self.docs:
            with self.subTest(doc=D.key):
                page.evaluate("async k => await switchDoc(k)", D.key)
                self.assertEqual(page.evaluate(DRAWN, D.key), 2)
        page.evaluate("openHelp()")
        page.wait_for_selector("#help[open]")
        page.keyboard.press("Escape")
        page.wait_for_selector("#help:not([open])", state="attached")
        self.assertEqual(self.violations(page), [])
        stripe = page.evaluate("getComputedStyle(document.getElementById('brand-stripe')).backgroundColor")
        self.assertNotIn(stripe, ("", "rgba(0, 0, 0, 0)"))

    def test_an_inline_script_without_a_hash_and_an_inline_handler_do_not_run(self):
        """An inline script element with other text and an onclick attribute are refused and reported, the two only."""
        page = self.enforced()
        self.assertEqual(self.violations(page), [])
        directives = page.evaluate(INJECT)
        self.assertTrue(all(d.startswith("script-src") for d in directives), directives)
        self.assertEqual(page.evaluate("[window.__cspRan, window.__cspClicked]"), [None, None])
        self.assertEqual([v["expected"] for v in self.violations(page)], [True, True])


VIEWER_DIR = Path(__file__).resolve().parents[1]
# What Limn's pages are written from: the viewer's template and JS parts, the icons put into it (limn.viewer.assemble)
# and the refusal page (limn.web.errors).
PAGE_SOURCES = [
    VIEWER_DIR / "index.html",
    *sorted((VIEWER_DIR / "js").glob("*.js")),
    VIEWER_DIR / "assemble.py",
    VIEWER_DIR.parent / "web" / "errors.py",
]

# What the guard reports, and why the policy refuses it:
# - "style attribute", "inline event handler", "javascript: URL": markup the policy refuses wherever it is written (a
#   style attribute needs 'unsafe-inline' or 'unsafe-hashes', an inline handler and a javascript: URL are inline code
#   with no hash). A property set from JS (el.style.x, el.style.cssText, el.onclick) is CSSOM or a function, not markup,
#   and is allowed.
# - "style through setAttribute", "event handler through setAttribute": the same two attributes put in from JS.
# - "script or style markup", "script or style element" (JS only): a <script> or <style> element a JS part makes, as
#   markup or with createElement(NS). The policy does not stop all of them - a script element that points at a file
#   of this origin runs, and an element whose text matches one of the page's hashes runs or applies, whoever made it -
#   so the rule, not the policy, keeps them out: a module is import()ed from this origin, a look is a CSS rule or
#   CSSOM. The template's and the refusal page's own elements are hashed and are not looked for.
#
# The JS is read as tokens (helpers_js), so code is told from text: every string and template literal (with its JS
# escapes read, a substitution standing as one opaque character) is markup that may reach a page, and calls are found
# with any spacing or comments before their parenthesis, through ?. or ['name'], with a quoted or template-literal
# argument. A value computed at run time (a variable tag name, a string put together with +) is not seen; the browser
# suite's report gate covers the flows it drives.

# An attribute in a piece of markup text: its name after a space, a slash or a quote (as the HTML tokenizer starts a new
# attribute name there), then '='. Case-insensitive like HTML names; the value may be quoted or not.
_TEXT_ATTRIBUTE = re.compile(r"(?:^|(?<=[\s\"'/\x00]))(style|on[a-z]+)\s*=", re.I)
# A start tag's name, then its attributes as the HTML tokenizer reads them: names end at space, '/', '>' or '=', a value
# is double-quoted, single-quoted or runs to space or '>'.
_START_TAG = re.compile(r"<[A-Za-z][^\s/>]*")
_ATTRIBUTE_GAP = re.compile(r"[\s/]*")
_ATTRIBUTE = re.compile(r"(?P<name>[^\s/>][^\s/>=]*)(?:\s*=\s*(?P<value>\"[^\"]*\"?|'[^']*'?|[^\s>]*))?")
# A <script> or <style> element begun in markup text (the tag name ends at space, '/' or '>').
_SCRIPT_OR_STYLE_TAG = re.compile(r"<(?:script|style)(?=[\s/>]|$)", re.I)
# A URL that runs code, once the HTML parser has read character references and the URL parser has dropped tabs and
# newlines (and leading spaces and controls).
_JAVASCRIPT_URL = re.compile(r"(?:^|[^\w+.-])[\x00-\x20]*javascript:", re.I)
# A <script> or <style> element of an HTML document, with its text (which is code or CSS, not markup).
_RAW_TEXT_ELEMENT = re.compile(r"(<(script|style)\b[^>]*>)(.*?)</\2\s*>", re.I | re.S)
# A JS escape in a string or template literal: \xHH, \uHHHH, \u{H...}, a line continuation, or one character.
_JS_ESCAPE = re.compile(
    r"\\(?:x([0-9A-Fa-f]{2})|u\{([0-9A-Fa-f]+)\}|u([0-9A-Fa-f]{4})|(\r\n|[\n\r\u2028\u2029])|(.))", re.S
)
_JS_SIMPLE_ESCAPE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
# The calls that make an element or set an attribute -> the index of the argument naming it.
ELEMENT_CALLS = {"createElement": 0, "createElementNS": 1}
ATTRIBUTE_CALLS = {"setAttribute": 0, "setAttributeNS": 1}
# A template substitution's place in the text of its template literal: one character that is neither markup nor space.
_SUBSTITUTION = "\x00"


def _cooked(raw: str) -> str:
    """The value of a JS literal's raw text: its escapes read (\\x, \\u, \\u{}, the one-letter ones, a line
    continuation dropped, any other escaped character as itself)."""

    def one(m: re.Match[str]) -> str:
        code = m[1] or m[2] or m[3]
        if code:
            return chr(int(code, 16)) if int(code, 16) <= 0x10FFFF else "\ufffd"
        return "" if m[4] else _JS_SIMPLE_ESCAPE.get(m[5], m[5])

    return _JS_ESCAPE.sub(one, raw)


def _js_literals(toks: list[helpers_js.Token]) -> list[tuple[int, str]]:
    """(source offset, value) of every string and template literal among the code tokens toks, in source order of their
    ends; a template literal's value is its text pieces joined by _SUBSTITUTION, one per ${...}."""
    found: list[tuple[int, str]] = []
    open_templates: list[tuple[int, list[str]]] = []
    for t in toks:
        if t.kind == "string":
            found.append((t.start, _cooked(t.text[1:-1])))
        elif t.kind == "template":
            if t.text.startswith("`"):
                open_templates.append((t.start, []))
            start, pieces = open_templates[-1]
            if t.text.endswith("${") and len(t.text) >= 3:
                pieces.append(_cooked(t.text[1:-2]) + _SUBSTITUTION)
            else:
                pieces.append(_cooked(t.text[1:-1]))
                open_templates.pop()
                found.append((start, "".join(pieces)))
    return found


def _literal_value(t: helpers_js.Token) -> str | None:
    """The value of a string literal or a template literal without substitutions, else None."""
    if t.kind == "string" or (t.kind == "template" and t.text.startswith("`") and not t.text.endswith("${")):
        return _cooked(t.text[1:-1])
    return None


def _call_arguments(toks: list[helpers_js.Token], k: int) -> list[list[helpers_js.Token]]:
    """The arguments of the call whose '(' is toks[k], each as its tokens (cut at the commas outside brackets)."""
    end = helpers_js.matching_bracket(toks, k)
    args: list[list[helpers_js.Token]] = [[]]
    depth = 0
    for t in toks[k + 1 : end]:
        opens = t.text in ("(", "[", "{") if t.kind == "punct" else (t.kind == "template" and t.text.endswith("${"))
        closes = t.text in (")", "]", "}") if t.kind == "punct" else (t.kind == "template" and t.text.startswith("}"))
        depth += int(opens) - int(closes)
        if depth == 0 and t.kind == "punct" and t.text == ",":
            args.append([])
        else:
            args[-1].append(t)
    return args


def _js_calls(toks: list[helpers_js.Token]) -> list[tuple[int, str]]:
    """(source offset, what) for each call in toks that makes a script or style element or sets a style or on*
    attribute, with the name given as a literal: el.createElement('x'), el.setAttribute?.(`x`, ...), el['setAttribute']
    ("x", ...) - spaces and comments are not tokens here, so they never hide the parenthesis."""
    found: list[tuple[int, str]] = []
    for k, t in enumerate(toks):
        name = t.text if t.kind == "ident" else None
        after = k + 1
        if t.kind == "string" and k > 0 and toks[k - 1].text == "[" and k + 1 < len(toks) and toks[k + 1].text == "]":
            name, after = _cooked(t.text[1:-1]), k + 2
        if name not in ELEMENT_CALLS and name not in ATTRIBUTE_CALLS:
            continue
        if after < len(toks) and toks[after].text == "?.":
            after += 1
        if after >= len(toks) or toks[after].text != "(":
            continue
        args = _call_arguments(toks, after)
        at = ELEMENT_CALLS.get(name, ATTRIBUTE_CALLS.get(name, 0))
        value = _literal_value(args[at][0]) if at < len(args) and len(args[at]) == 1 else None
        if value is None:
            continue
        value = value.strip().lower()
        if name in ELEMENT_CALLS and value in ("script", "style"):
            found.append((t.start, "script or style element"))
        elif name in ATTRIBUTE_CALLS and value == "style":
            found.append((t.start, "style through setAttribute"))
        elif name in ATTRIBUTE_CALLS and re.fullmatch(r"on[a-z]+", value):
            found.append((t.start, "event handler through setAttribute"))
    return found


def _attributes(markup: str) -> list[tuple[int, str, str | None]]:
    """(offset, lower-case name, value without its quotes or None) of every attribute of every start tag in markup."""
    found: list[tuple[int, str, str | None]] = []
    for tag in _START_TAG.finditer(markup):
        i = tag.end()
        while True:
            i = _ATTRIBUTE_GAP.match(markup, i).end()  # type: ignore[union-attr]
            if i >= len(markup) or markup[i] == ">":
                break
            m = _ATTRIBUTE.match(markup, i)
            assert m is not None  # one character that is not space, '/' or '>' is always a name
            value = m["value"]
            if value is not None and value[:1] in ("'", '"'):
                value = value[1 : -1 if len(value) > 1 and value[-1] == value[0] else None]
            found.append((i, m["name"].lower(), value))
            i = m.end()
    return found


def _runs_code(url: str) -> bool:
    """Whether a URL written in markup is a javascript: URL, read as the browser reads it."""
    return bool(_JAVASCRIPT_URL.search(re.sub(r"[\t\n\r]", "", html.unescape(url))))


def _text_refusals(text: str, js: bool) -> list[tuple[int, str]]:
    """(offset in text, what) for markup text that may be all or part of a page's markup (a JS or Python literal): an
    attribute anywhere a name may start, a javascript: URL, and in a JS literal a <script> or <style> tag."""
    found = [
        (m.start(1), "style attribute" if m[1].lower() == "style" else "inline event handler")
        for m in _TEXT_ATTRIBUTE.finditer(text)
    ]
    if _runs_code(text):
        found.append((0, "javascript: URL"))
    if js:
        found += [(m.start(), "script or style markup") for m in _SCRIPT_OR_STYLE_TAG.finditer(text)]
    return found


def _js_refusals(src: str) -> list[tuple[int, str]]:
    """(offset in src, what) for a script: its literals as markup text, and its calls."""
    toks = helpers_js.code(helpers_js.tokenize(src))
    found = _js_calls(toks)
    for start, value in _js_literals(toks):
        for at, what in _text_refusals(value, js=True):
            found.append((start + (at if value.count("\n", 0, at) == 0 else 0), what))
    return found


def _html_refusals(page: str) -> list[tuple[int, str]]:
    """(offset in page, what) for an HTML document: the attributes of its start tags, and its inline scripts as JS (its
    own <script> and <style> elements are hashed by the policy; a <style>'s text is CSS and is not read)."""
    found: list[tuple[int, str]] = []
    markup = page
    for m in _RAW_TEXT_ELEMENT.finditer(page):
        markup = markup[: m.start(3)] + re.sub(r"[^\n]", " ", m[3]) + markup[m.end(3) :]
        if m[2].lower() == "script":
            found += [(m.start(3) + at, what) for at, what in _js_refusals(m[3])]
    for at, name, value in _attributes(markup):
        if name == "style":
            found.append((at, "style attribute"))
        elif re.fullmatch(r"on[a-z]+", name):
            found.append((at, "inline event handler"))
        if value is not None and _runs_code(value):
            found.append((at, "javascript: URL"))
    return found


def _python_refusals(src: str) -> list[tuple[int, str]]:
    """(line, what) for a Python module that writes a page: each of its string constants as markup text."""
    found = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for at, what in _text_refusals(node.value, js=False):
                found.append((node.lineno + node.value.count("\n", 0, at), what))
    return found


def refusals(text: str, kind: str) -> list[tuple[int, str]]:
    """(line, what) for each refused piece of markup or call in text, a 'js', 'html' or 'py' source, in line order."""
    if kind == "py":
        return sorted(_python_refusals(text))
    found = _js_refusals(text) if kind == "js" else _html_refusals(text)
    return sorted((text.count("\n", 0, at) + 1, what) for at, what in found)


def refused_in(path: Path) -> list[str]:
    """'<file>:<line> <what>' for each refused piece of markup or call in path."""
    kind = {".js": "js", ".html": "html", ".py": "py"}[path.suffix]
    return ["%s:%d %s" % (path.name, line, what) for line, what in refusals(path.read_text(encoding="utf-8"), kind)]


# Each kind of refused markup or call, written as the page's sources could write it -> (kind of source, what the guard
# must report). Every one must be found.
REFUSED_PROBES = [
    ("html", '<span class="errline" style="margin:0">', "style attribute"),
    ("html", '<span STYLE="display:none">', "style attribute"),
    ("html", "<span style=display:none>", "style attribute"),
    ("html", '<a href="x"style="color:red">', "style attribute"),
    ("html", "<span\n  Style\n  =\n  'x'>", "style attribute"),
    ("html", "<button onclick=go()>", "inline event handler"),
    ("html", '<svg/onload="go()">', "inline event handler"),
    ("html", '<img src=x OnError="go()">', "inline event handler"),
    ("html", '<a href="javascript:go()">', "javascript: URL"),
    ("html", '<a href=" JavaScript:go()">', "javascript: URL"),
    ("html", '<a href="java&#x09;script&colon;go()">', "javascript: URL"),
    ("html", "<script>document.createElement('style')</script>", "script or style element"),
    ("js", "el.innerHTML = `<span style=display:none>x</span>`", "style attribute"),
    ("js", 'html`<span class="${c}" style="${s}">`', "style attribute"),
    ("js", "html`<i ${a}style=x>`", "style attribute"),
    ("js", "html`<b>${n}</b><span\nstyle='x'>`", "style attribute"),
    ("js", "const a = '<span st\\x79le=\"x\">'", "style attribute"),
    ("js", "'<span class=\"' + c + '\" style=\"' + s + '\">'", "style attribute"),
    ("js", "el.innerHTML = '<button onclick=go()>x</button>'", "inline event handler"),
    ("js", 'el.insertAdjacentHTML("beforeend", `<img src=x ONERROR="go()">`)', "inline event handler"),
    ("js", "a.href = 'JavaScript:go()'", "javascript: URL"),
    ("js", "el.setAttribute('style', 'x')", "style through setAttribute"),
    ("js", "el.setAttribute(`style`, 'display:none')", "style through setAttribute"),
    ("js", 'el.setAttribute ( "STYLE" , x)', "style through setAttribute"),
    ("js", "el.setAttribute/* why */('style', x)", "style through setAttribute"),
    ("js", "el?.setAttribute?.('style', x)", "style through setAttribute"),
    ("js", "el['setAttribute']('style', x)", "style through setAttribute"),
    ("js", "el.setAttributeNS(null, 'style', x)", "style through setAttribute"),
    ("js", "el.setAttribute('onclick', 'go()')", "event handler through setAttribute"),
    ("js", "document.createElement('script')", "script or style element"),
    ("js", "document.createElement (`style`)", "script or style element"),
    ("js", "document.createElement(\n  // a comment\n  'SCRIPT')", "script or style element"),
    ("js", "document.createElement('scr\\u0069pt')", "script or style element"),
    ("js", "document.createElementNS(SVG, 'script')", "script or style element"),
    ("js", "html`<style>.x{}</style>`", "script or style markup"),
    ("js", "el.insertAdjacentHTML('beforeend', '<style>.x{}</style>')", "script or style markup"),
    ("js", "el.outerHTML = '<script src=/x.js></script>'", "script or style markup"),
    ("js", "document.write('<SCRIPT>go()</SCRIPT>')", "script or style markup"),
    ("js", "new DOMParser().parseFromString(`<style>`, 'text/html')", "script or style markup"),
    ("js", "el.innerHTML = '<svg><script/></svg>'", "script or style markup"),
    ("py", "PAGE = '<p style=\"margin:0\">%s</p>'", "style attribute"),
    ("py", "PAGE = f'<button onclick=go()>{x}</button>'", "inline event handler"),
]
# What the page's sources may write: CSSOM, handlers set as properties, attributes read or removed, other elements,
# and words that only look like the refused ones. None may be found.
ALLOWED_PROBES = [
    ("js", "el.style.display = 'none'"),
    ("js", "el.style.cssText = 'display:none'"),
    ("js", "el.style = 'display:none'"),
    ("js", "el.style.setProperty('--w', w + 'px')"),
    ("js", "const s = new CSSStyleSheet(); s.replaceSync('.x{color:red}'); document.adoptedStyleSheets = [s]"),
    ("js", "el.onclick = go; el.onpointerdown=go"),
    ("js", "el.getAttribute('style'); el.removeAttribute('style'); el.hasAttribute('onclick')"),
    ("js", "el.setAttribute('data-style', x); el.setAttribute('aria-label', label); el.setAttribute(name, v)"),
    ("js", "document.createElement('span'); document.createElement('styles')"),
    ("js", 'html`<span class="x" data-style="y" data-on="z">${n}</span>`'),
    ("js", "fetch('/api/x?doc=' + k + '&on=1&scope=page')"),
    ("js", 'const css = el.styleSheets; // never <script> or style="x" here'),
    ("js", 'html`<a href="${u}" rel="noopener">`'),
    ("js", "x < style && y > on; a = b"),
    ("html", '<p>style = "x" and onclick = go() in words</p>'),
    ("html", '<button data-act="go" data-tip="onclick=go()">x</button>'),
    ("html", "<script>el.style.top = '1px'</script>"),
    ("html", '<a href="/?lang=en">English</a>'),
    ("py", "PAGE = '<style>body{margin:0}</style><script>go()</script>'"),
]


class HarnessReports(unittest.TestCase):
    """The gate leaves out only the harness's own reports: Playwright's eval and WebKit's screenshot sync style."""

    SYNC = {"directive": "style-src-elem", "blocked": "inline", "sample": "body {}", "source": "", "line": 5}

    def test_the_screenshot_sync_style_is_the_harness_own(self):
        """WebKit's `<style>body {}</style>` from Playwright's utility world (no source URL) is left out."""
        self.assertTrue(helpers_csp.playwright_screenshot_sync(self.SYNC))
        self.assertTrue(helpers_csp.harness_own(self.SYNC))

    def test_a_style_the_viewer_inserts_is_still_reported(self):
        """The same text with the page's URL, other text, a style attribute or another directive stays a violation."""
        page = "http://viewer.test/?lang=ko"
        for case in (
            dict(self.SYNC, source=page),
            dict(self.SYNC, sample="body { color: red }"),
            dict(self.SYNC, sample="body {}", directive="style-src-attr"),
            dict(self.SYNC, directive="script-src-elem"),
            dict(self.SYNC, blocked="https://other.example/x.css"),
        ):
            with self.subTest(case=case):
                self.assertFalse(helpers_csp.harness_own(case))

    def test_eval_stays_the_harness_own_only_without_a_url(self):
        """Playwright's eval is left out; an eval in the page's own code is reported."""
        self.assertTrue(helpers_csp.harness_own({"blocked": "eval", "source": ""}))
        self.assertFalse(helpers_csp.harness_own({"blocked": "eval", "source": "http://viewer.test/"}))


class StaticGuards(unittest.TestCase):
    """The template, the JS parts, the icons and the refusal page write no markup the page's policy refuses, and the JS
    parts make no script or style element. The browser suite's gate sees only the flows it drives; a flow it does not
    reach (the re-place banner's error line was one) is caught here."""

    def test_no_markup_the_policy_refuses(self):
        self.assertEqual([found for path in PAGE_SOURCES for found in refused_in(path)], [])

    def test_the_guard_finds_each_refused_way_of_writing_it(self):
        """Every refused probe is found as what it is: quotes, template literals, case, unquoted values, spacing and
        comments before a call, escapes."""
        for kind, src, what in REFUSED_PROBES:
            with self.subTest(src=src):
                self.assertIn(what, [w for _, w in refusals(src, kind)])

    def test_the_guard_lets_cssom_properties_and_look_alikes_through(self):
        """CSSOM (el.style.x, style.cssText, constructed stylesheets), handlers set as properties, attributes read or
        removed, and words that only look like markup are not found."""
        for kind, src in ALLOWED_PROBES:
            with self.subTest(src=src):
                self.assertEqual(refusals(src, kind), [])

    def test_a_js_part_is_held_to_the_js_patterns_and_the_template_is_not(self):
        """The template's own <script> and <style> are allowed (hashed); the same elements in a JS part's strings are
        refused."""
        with tempfile.TemporaryDirectory() as tmp:
            part = "a = '<style>a{}</style>'\nb = `<script>go()</script>`\n"
            (Path(tmp) / "part.js").write_text(part, encoding="utf-8")
            (Path(tmp) / "page.html").write_text("<style>a{}</style>\n<script>go()</script>\n", encoding="utf-8")
            self.assertEqual(
                refused_in(Path(tmp) / "part.js"),
                ["part.js:1 script or style markup", "part.js:2 script or style markup"],
            )
            self.assertEqual(refused_in(Path(tmp) / "page.html"), [])


class EnforcedChromium(EnforcedFlows, BrowserBase):
    """The flows in Chromium."""


class EnforcedFirefox(EnforcedFlows, BrowserBase):
    """The flows in Firefox."""

    BROWSER_ENGINE = "firefox"


class EnforcedWebKit(EnforcedFlows, BrowserBase):
    """The flows in WebKit (Safari's engine, and every browser's on iPadOS)."""

    BROWSER_ENGINE = "webkit"
