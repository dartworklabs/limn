"""The browser tests' Content-Security-Policy gate (docs/adr/0026-viewer-csp.md): every page a browser test opens reports
each violation of the policy the server sent with it, and a browser test with one fails.

The viewer's policy is meant to block nothing the viewer does, so a violation is a regression - an inline script or
style the policy does not hash, a style attribute, a request to another origin - even when the test's own assertions
pass.

The fixture route (helpers_browser.BrowserBase.forward) hands the browser the handler's policy as
Content-Security-Policy-Report-Only (report_only), not as the enforced header. Playwright's wait_for_function() runs
its predicate with eval() inside the page in Chromium and Firefox alike, so an enforced policy without 'unsafe-eval'
stops every test at its first wait; a report-only one lets the wait run and still reports, with the same directive and
the same refused thing, everything the enforced policy would block - nothing is blocked that is not reported. The one
report that is the harness's own is that eval (playwright_eval), which the gate leaves out. What enforcement itself
does to the viewer is tested apart, with the enforced header and waits that need no eval (viewer/tests/test_viewer_csp.py).

watch_csp() puts a listener for `securitypolicyviolation` in every page of a context before the page's own scripts
run, and exposes a function the listener calls with the event's fields. The pytest plugin part
(no_csp_violation) clears this worker's list before each browser test and fails the test when the list is not empty
after it. With LIMN_CSP_LOG=<file>, each violation (the harness's own eval included) is also appended to that file as
one JSON line, with the test's id, so one run of the whole suite lists every violation at once.
"""

import json
import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest

from limn.web.csp import inline_hashes

# Runs before the page's scripts in every document of a context (watch_csp). Records the fields a fix needs: the directive
# that refused, what was refused (a URL, 'inline', 'eval'), the first characters of an inline one, and where.
CSP_WATCH = """(() => {
  const seen = window.__limnCspViolations = [];
  document.addEventListener('securitypolicyviolation', e => {
    const v = {directive: e.effectiveDirective || e.violatedDirective, blocked: e.blockedURI, sample: e.sample,
      source: e.sourceFile, line: e.lineNumber, column: e.columnNumber, disposition: e.disposition, page: location.href,
      expected: !!window.__limnCspExpected};
    seen.push(v);
    try { if (window.__limnCspReport) window.__limnCspReport(v); } catch (err) { /* the context is closing */ }
  }, true);
})();"""

# The violations this worker process has seen since the current browser test began.
VIOLATIONS: list[dict] = []


def playwright_eval(violation: dict) -> bool:
    """Whether a violation is Playwright's own eval() of a wait_for_function() predicate: an eval refused in code with no
    URL (Chromium, WebKit) or in Firefox's "debugger eval code". The viewer's code always has a URL - the page's for
    its inline script, /vendor/... for a module - so an eval of its own is still reported."""
    source = str(violation.get("source") or "")
    return violation.get("blocked") == "eval" and (source == "" or source.startswith("debugger eval code"))


def report_only(policy: str) -> dict[str, str]:
    """The response header a fixture route gives the browser for the server's policy: the same policy as
    Content-Security-Policy-Report-Only, with 'report-sample' in script-src and style-src so a report names the first
    characters of the inline script, style or style attribute it refused (it changes what is reported, not what is
    allowed)."""
    parts = [p + " 'report-sample'" if p.startswith(("script-src ", "style-src ")) else p for p in policy.split("; ")]
    return {"content-security-policy-report-only": "; ".join(parts)}


def _report(violation: dict) -> None:
    """Keep one violation for the gate - not the harness's own eval (playwright_eval), nor one a test provoked on purpose
    (window.__limnCspExpected while it did) - and append it to $LIMN_CSP_LOG when set."""
    record = dict(violation, test=os.environ.get("PYTEST_CURRENT_TEST", ""))
    if not playwright_eval(record) and not record.get("expected"):
        VIOLATIONS.append(record)
    log = os.environ.get("LIMN_CSP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as out:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")


def watch_csp(context) -> None:
    """Report every Content-Security-Policy violation of every page of context (CSP_WATCH)."""
    context.expose_function("__limnCspReport", _report)
    context.add_init_script(CSP_WATCH)


def watching(browser):
    """browser, with every context it makes - new_context(), and new_page()'s own - watched (watch_csp)."""
    new_context, new_page = browser.new_context, browser.new_page

    def watched_context(*args, **options):
        """A new context, watched."""
        context = new_context(*args, **options)
        watch_csp(context)
        return context

    def watched_page(*args, **options):
        """A new page in its own new context, watched from its first navigation on."""
        page = new_page(*args, **options)
        watch_csp(page.context)
        return page

    browser.new_context, browser.new_page = watched_context, watched_page
    return browser


def allow_page_scripts(headers: dict[str, str], page: str) -> dict[str, str]:
    """headers with every inline script of page added to the script-src of their Content-Security-Policy, for a
    fixture that rewrites the page it serves (helpers_browser_font.prepare_font_document puts in its own loader, which
    then inserts the viewer's script - already allowed by the original policy); headers without a policy are returned
    as they are."""
    name = next((n for n in ("content-security-policy", "content-security-policy-report-only") if n in headers), None)
    if name is None:
        return headers
    scripts, _ = inline_hashes(page)
    parts = [" ".join((p, *scripts)) if p.startswith("script-src ") else p for p in headers[name].split("; ")]
    return dict(headers, **{name: "; ".join(parts)})


def report_only_documents(page) -> None:
    """For a test that reaches a real server instead of the fixture route: the page's HTML documents (path /) are
    fetched as they are and handed to the browser with their policy as report_only, so the harness's eval waits run; any
    other request (a download, an API call) goes straight to the server."""

    def convert(route) -> None:
        """Fetch the document and fulfil it with its policy reported on, not enforced."""
        response = route.fetch()
        headers = dict(response.headers)
        policy = headers.pop("content-security-policy", None)
        if policy is not None:
            headers.update(report_only(policy))
        route.fulfill(response=response, headers=headers)

    page.route(lambda url: urlparse(url).path == "/", convert)


def add_test_style(page, css: str) -> None:
    """Add css to the page after its own stylesheet, as a test's override, without an inline <style> the page's policy
    would refuse (Playwright's add_style_tag writes one): a constructed stylesheet is applied through the CSSOM, which
    the policy does not govern, like an element's style property."""
    page.evaluate(
        "css => { const s = new CSSStyleSheet(); s.replaceSync(css);"
        " document.adoptedStyleSheets = [...document.adoptedStyleSheets, s]; }",
        css,
    )


@pytest.fixture(autouse=True)
def no_csp_violation(request: pytest.FixtureRequest) -> Iterator[None]:
    """Fail a browser test whose pages reported a Content-Security-Policy violation."""
    if request.node.get_closest_marker("browser") is None:
        yield
        return
    VIOLATIONS.clear()
    yield
    found = list(VIOLATIONS)
    VIOLATIONS.clear()
    assert not found, "Content-Security-Policy violations: %s" % json.dumps(found, ensure_ascii=False)[:2000]
