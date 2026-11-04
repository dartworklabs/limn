"""The viewer under its enforced Content-Security-Policy (docs/adr/0026-viewer-csp.md), in Chromium, Firefox and WebKit.

Every other browser test hands the browser the server's policy as Report-Only and fails on any report
(tests/support/helpers_csp.py): Playwright's wait_for_function() evals its predicate in the page, which an enforced
policy refuses. These tests take the header as the server sends it, from a real HTTP server, and wait only with
Playwright's selector engine and promises the page resolves - nothing that needs eval in the page. They show that the
enforced policy lets the viewer do what it does - boot, the PDF.js module and its worker drawing a LaTeX manuscript, a
figure document and a view-only PDF, the help and Trash sheets - and that it refuses what it should: a script element
the page did not carry and an inline event handler, each reported.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_csp.py
"""

import re
import threading
import unittest
from pathlib import Path

import helpers_figure
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

# Puts in a script element the page did not carry and a button with an inline click handler, clicks it, and resolves with
# the directives of the two violations they report - in the page's own order of events. The two are expected
# (window.__limnCspExpected while they come in), so the gate (helpers_csp.no_csp_violation) leaves them out.
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

    def test_a_script_the_page_did_not_carry_and_an_inline_handler_do_not_run(self):
        """A script element with other text and an onclick attribute are refused and reported, the two only."""
        page = self.enforced()
        self.assertEqual(self.violations(page), [])
        directives = page.evaluate(INJECT)
        self.assertTrue(all(d.startswith("script-src") for d in directives), directives)
        self.assertEqual(page.evaluate("[window.__cspRan, window.__cspClicked]"), [None, None])
        self.assertEqual([v["expected"] for v in self.violations(page)], [True, True])


VIEWER_DIR = Path(__file__).resolve().parents[1]
# Markup the policy refuses, written into the page template or a JS part: a style attribute (also through setAttribute),
# an inline event handler attribute, a javascript: URL. A property set from JS (el.style.x, el.onclick) is not markup and
# is allowed. The lookbehind keeps `.style=` and `.onclick=` out.
REFUSED_MARKUP = {
    "style attribute": re.compile(r"(?<![\w.$-])style\s*=\s*[\"'$]"),
    "style through setAttribute": re.compile(r"setAttribute\(\s*['\"]style['\"]"),
    "inline event handler": re.compile(r"(?<![\w.$-])on[a-z]+\s*=\s*[\"'$]"),
    "javascript: URL": re.compile(r"javascript:", re.I),
}


class StaticGuards(unittest.TestCase):
    """The template and the JS parts write no markup the page's policy refuses. The browser suite's gate sees only the
    flows it drives; a flow it does not reach (the re-place banner's error line was one) is caught here."""

    def test_no_markup_the_policy_refuses(self):
        found = []
        for path in [VIEWER_DIR / "index.html", *sorted((VIEWER_DIR / "js").glob("*.js"))]:
            text = path.read_text(encoding="utf-8")
            for what, pattern in REFUSED_MARKUP.items():
                found += [
                    "%s:%d %s" % (path.name, text.count("\n", 0, m.start()) + 1, what) for m in pattern.finditer(text)
                ]
        self.assertEqual(found, [])

    def test_the_patterns_catch_what_they_name(self):
        """Each pattern finds the markup it names and not the JS property of the same name."""
        for what, markup, prop in (
            ("style attribute", '<span class="errline" style="margin:0">', "el.style=x"),
            ("style through setAttribute", "el.setAttribute('style','x')", "el.getAttribute('style')"),
            ("inline event handler", '<button onclick="go()">', "el.onclick=go"),
            ("javascript: URL", '<a href="javascript:go()">', "a.href=url"),
        ):
            with self.subTest(what=what):
                self.assertTrue(REFUSED_MARKUP[what].search(markup))
                self.assertFalse(REFUSED_MARKUP[what].search(prop))


class EnforcedChromium(EnforcedFlows, BrowserBase):
    """The flows in Chromium."""


class EnforcedFirefox(EnforcedFlows, BrowserBase):
    """The flows in Firefox."""

    BROWSER_ENGINE = "firefox"


class EnforcedWebKit(EnforcedFlows, BrowserBase):
    """The flows in WebKit (Safari's engine, and every browser's on iPadOS)."""

    BROWSER_ENGINE = "webkit"
