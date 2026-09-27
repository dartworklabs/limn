"""Shared fixtures of the real-browser tests: one Chromium launcher for every browser test class, and BrowserBase -
the real viewer against the in-process server.

Every browser test class uses them (test_brand, test_i18n, test_viewer, test_viewer_input, test_viewer_browser).
Chromium is $LIMN_CHROMIUM, a system Chrome/Chromium, or Playwright's bundled one (`playwright install chromium`), in
that order. Without Playwright or a browser the class is skipped, unless
LIMN_TEST_REQUIRE_BROWSER=1 (CI), where that is a failure. Every class that launches Chromium carries the pytest marker
`browser`, so `pytest -m "not browser"` runs the rest.

The browser tests never wait a fixed time for the page to get somewhere: they wait on the state the next step reads (a
variable the viewer sets, an element, the page having settled - settle()). The one fixed wait left is nothing_follows(),
for an event only the browser would send (a click it synthesizes from a tap, a back navigation from a swipe), which no
page state announces (docs/handbook/verification.md §브라우저 테스트의 기다림).
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

import pytest

from limn import mapping
from limn.build import cur_pages
from limn.files import tex_lines

from helpers import blank_png, ps, run_config, serve_viewer, split_resp
from helpers_access import ALICE, reset_access, talk_to

# The timers settle() waits for: the viewer's debounces, slides and long-press timers run 0-1000ms. Longer ones are
# lifetimes no test waits out - a toast's 6s, the coach mark's 8s, a tooltip's 4s.
IDLE_TIMER_MS = 1000

# Counts the page's pending work for settle(): every short timer not yet run and every fetch whose body has not been read
# to its end (released one task later, so the caller's own continuation has run as well). Installed as an init script
# after any other (watch_idle), so it wraps whatever a test put in front of fetch and counts what the viewer waits for.
IDLE_WATCH = (
    """(() => {
  const w = window, idle = w.__limnIdle = {timers: new Set(), fetches: 0, quiet: 0};
  const setT = w.setTimeout, clearT = w.clearTimeout, fetch0 = w.fetch;
  w.setTimeout = function (fn, ms, ...args) {
    const d = ms === undefined ? 0 : Number(ms);
    if (typeof fn !== 'function' || !(d <= %d)) return setT.call(w, fn, ms, ...args);
    const id = setT.call(w, function () { idle.timers.delete(id); return fn.apply(this, args); }, ms);
    idle.timers.add(id);
    return id;
  };
  w.clearTimeout = function (id) { idle.timers.delete(id); return clearT.call(w, id); };
  w.fetch = function (...a) {
    idle.fetches++;
    const done = () => { setT.call(w, () => { idle.fetches--; }, 0); };
    let p;
    try { p = fetch0.apply(w, a); } catch (e) { done(); throw e; }
    p.then(r => r.clone().arrayBuffer()).then(done, done);
    return p;
  };
})()"""
    % IDLE_TIMER_MS
)

# settle()'s check, run on every animation frame: nothing pending (IDLE_WATCH) and no finite CSS animation or transition
# running (an infinite one - a spinner - never ends), on two frames in a row, so that a requestAnimationFrame callback
# queued behind the first check has run too.
QUIET = """() => {
  const idle = window.__limnIdle;
  if (!idle) throw new Error('settle(): this page has no idle watch - add it to the context with watch_idle()');
  const moving = document.getAnimations().some(a => a.playState === 'running' && a.effect
    && a.effect.getComputedTiming().iterations !== Infinity);
  idle.quiet = idle.timers.size === 0 && idle.fetches === 0 && !moving ? idle.quiet + 1 : 0;
  return idle.quiet >= 2;
}"""


def watch_idle(context):
    """Install IDLE_WATCH in every page of context, after the init scripts added so far; settle() needs it."""
    context.add_init_script(IDLE_WATCH)


def settle(page, timeout=15000):
    """Wait until the page has settled: no short timer pending, no fetch in flight, no CSS animation or transition
    running, on two animation frames in a row. After it, whatever the last action set in motion - a debounced save, a
    slide, a server round trip and its redraw - has finished, so the next step reads the state it produced, and a check
    that something did not happen reads the page after everything that could have made it happen."""
    page.evaluate("window.__limnIdle && (window.__limnIdle.quiet = 0)")
    page.wait_for_function(QUIET, timeout=timeout, polling="raf")


def nothing_follows(page, ms=500):
    """The one bounded negative wait: settle, then let ms pass, so that an event only the browser would still send - a
    click it synthesizes after a tap, a back navigation from an overscroll swipe - has had the time to arrive before the
    test checks that it did not. No page state announces that such an event will not come, so this wait cannot be on
    state; it bounds a check that nothing happened and never stands in for the next step's precondition."""
    settle(page)
    page.wait_for_timeout(ms)


def booted(n_open):
    """The JS condition that boot() has finished with at least n_open open pins: LIGHT_TIMER is set by the last
    synchronous steps after `await loadPins()` (see BrowserBase.open)."""
    return "typeof LIGHT_TIMER!=='undefined'&&LIGHT_TIMER!==null&&OPEN_ALL.length>=%d" % n_open


class ChromiumTestCase(unittest.TestCase):
    """A test class sharing one Chromium (cls.browser, driven through cls.pw) across its tests. A subclass that needs
    more class setup calls super().setUpClass() first and super().tearDownClass() last. Every subclass carries the
    pytest marker `browser` (pytest reads pytestmark through the class hierarchy)."""

    pytestmark = pytest.mark.browser

    @classmethod
    def setUpClass(cls):
        """Start Playwright and launch Chromium; skip the class when either is unavailable, unless
        LIMN_TEST_REQUIRE_BROWSER=1, where the error propagates."""
        super().setUpClass()
        required = os.environ.get("LIMN_TEST_REQUIRE_BROWSER") == "1"
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            if required:
                raise
            raise unittest.SkipTest("Playwright unavailable") from None
        exe = os.environ.get("LIMN_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(executable_path=exe or None, args=["--no-sandbox"])
        except Exception as e:  # no bundled or system browser
            cls.pw.stop()
            if required:
                raise
            raise unittest.SkipTest("Chromium unavailable: %s" % e) from e

    @classmethod
    def tearDownClass(cls):
        """Close Chromium and stop Playwright."""
        cls.browser.close()
        cls.pw.stop()
        super().tearDownClass()


# The manuscript BrowserBase serves: 37 numbered lines between the preamble and \end{document}.
DEMO_TEX = (
    "\\documentclass{article}\n\\begin{document}\n"
    + "".join("Line %d of the demo manuscript.\n" % i for i in range(3, 40))
    + "\\end{document}\n"
)


class BrowserBase(ChromiumTestCase):
    """The real viewer against the in-process server (same approach as test_i18n.EnglishChrome), as the tailnet
    person WHO. /api/pick is answered with a computed pick result, since the test has no PDF or SyncTeX."""

    WHO = ALICE

    def setUp(self):
        """A fresh 37-line manuscript with a finished two-page build (blank page images), default access settings, and
        a fresh Runtime serving the viewer page built for the "Demo" paper."""
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        src = root / "ms"
        src.mkdir()
        (src / "main.tex").write_text(DEMO_TEX, encoding="utf-8")
        (root / "state").mkdir()
        ps.C = run_config(src, src / "main.tex", root / "state", label="Demo")
        C = ps.C
        reset_access()  # the access defaults and a fresh Runtime
        serve_viewer("Demo", "#2563eb", ps)
        ps.set_docs(None)
        ps.init_seq()
        pages = C.state / "pages-20260925100000"
        pages.mkdir()
        for i in (1, 2):
            (pages / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
        (C.state / "pages.cur").write_text(pages.name)
        (C.state / "built_at.txt").write_text("2026-09-25 10:00:00")
        (C.state / "head.txt").write_text("abc1234")
        self.main = C.main

    def tearDown(self):
        """Put the access settings back and remove the temporary folders."""
        reset_access()
        self.tmp.cleanup()

    def talk(self, raw):
        """Send one raw request to the handler (from loopback) -> (status, headers, body)."""
        return split_resp(talk_to(ps, raw))

    def route(self, route):
        """Playwright route handler: /api/pick gets a computed answer, every other viewer.test request goes to the
        handler with WHO's tailnet headers (and a same-origin Origin on POST); anything else is aborted."""
        rq = route.request
        u = urlparse(rq.url)
        if u.netloc != "viewer.test":
            return route.abort()
        if u.path == "/api/pick":
            lines = tex_lines(self.main)
            lad = mapping.compute_levels(lines, 5, 5, ps.C.envs)
            d = {
                "file": str(self.main),
                "name": "main.tex",
                "page": 1,
                "lo": lad["lo"],
                "hi": lad["hi"],
                "raw_lo": 5,
                "raw_hi": 5,
                "kind": lad["kind"],
                "via": "synctex",
                "score": 1.0,
                "warn": "",
                "n_lines": len(lines),
                "snippet": mapping.snippet(lines, lad["lo"], lad["hi"]),
                "frac": [0.1, 0.1, 0.3, 0.05],
                "quote": "Line 5",
                "levels": lad["levels"],
                "default_level": lad["default_level"],
                "overlaps": [],
                "pdf_build": cur_pages(ps.DOCS[0]).name,
            }
            return route.fulfill(status=200, headers={"content-type": "application/json"}, body=json.dumps(d))
        body = rq.post_data_buffer or b""
        h = {
            "Host": "127.0.0.1:18999",
            "Tailscale-User-Login": self.WHO["Tailscale-User-Login"],
            "Tailscale-User-Name": self.WHO["Tailscale-User-Name"],
        }
        if rq.headers.get("content-type"):
            h["Content-Type"] = rq.headers["content-type"]
        if body:
            h["Content-Length"] = str(len(body))
        if rq.method == "POST":
            h["Origin"] = "http://127.0.0.1:18999"
        raw = (
            "%s %s HTTP/1.1\r\n" % (rq.method, u.path + ("?" + u.query if u.query else ""))
            + "".join("%s: %s\r\n" % kv for kv in h.items())
            + "\r\n"
        ).encode("latin-1") + body
        code, hdrs, data = self.talk(raw)
        route.fulfill(
            status=code, headers={"content-type": hdrs.get("content-type", "application/octet-stream")}, body=data
        )

    def open(self, n_open, lang="ko", init=None, **device):
        """Open the viewer in a new context and return the page once boot() has finished and the page has settled: the
        pin lists (open, review, done) are loaded and polling has started, with at least n_open open pins. init is an
        optional script run before the viewer's own.

        The wait is on LIGHT_TIMER, which boot() sets only after `await loadPins()`. META and the initial
        `OPEN_ALL=[]` are both set before that await, so waiting on them alone let a test act on a review or done
        pin that the viewer did not know yet (showChange() of an unknown pin does nothing, and nothing retries)."""
        context = self.browser.new_context(**(device or {"viewport": {"width": 1400, "height": 850}}))
        self.addCleanup(context.close)
        if init:
            context.add_init_script(init)
        watch_idle(context)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=%s" % lang)
        page.wait_for_function(booted(n_open), timeout=20000)
        settle(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def open_composer(self, page):
        """Drag a region on page 1 with the mouse and wait until the composer shows its resolved lines."""
        page.evaluate("LAST_PTR='mouse'; pick({page:1,x0:10,y0:10,x1:200,y1:60})")
        page.wait_for_selector("#composer:not([hidden])", timeout=8000)
        page.wait_for_function("CUR&&CUR.lo", timeout=8000)
