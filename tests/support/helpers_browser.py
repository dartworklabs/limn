"""Shared fixtures of the real-browser tests: one browser launcher for every test class, and BrowserBase -
the real viewer against the in-process server.

Every browser test class uses them (test_brand, test_i18n, test_viewer, test_viewer_input, test_viewer_browser).
Chromium is $LIMN_CHROMIUM, a system Chrome/Chromium, or Playwright's bundled one (`playwright install chromium`), in
that order. Without Playwright or a browser the class is skipped, unless
LIMN_TEST_REQUIRE_BROWSER=1 (CI), where that is a failure. Classes selecting Firefox or WebKit use Playwright's
bundled engine (`playwright install firefox webkit`). Every class that launches a browser carries the pytest marker
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
from typing import Literal
from urllib.parse import urlparse

import pytest

from limn.builds.artifacts import cur_pages
from limn.pins.location import mapping
from limn.platform.files import file_in_tree, tex_lines

from helpers import ApplicationFixture, blank_png, ps, run_config, serve_viewer, split_resp
from helpers_access import ALICE, reset_access, talk_to

# The timers settle() waits for: the viewer's debounces, slides and long-press timers run 0-1000ms. Longer ones are
# lifetimes no test waits out - an undo's 6s window, a tooltip's 4s.
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

# settle()'s check, run on every animation frame: nothing pending (IDLE_WATCH), no web font loading (the bundled
# Pretendard's slices load as their characters first show, and the text swaps from a fallback when they arrive -
# docs/handbook/viewer.md §글꼴) and no finite CSS animation or transition running (an infinite one - a spinner - never
# ends), on two frames in a row, so that a requestAnimationFrame callback queued behind the first check has run too.
QUIET = """() => {
  const idle = window.__limnIdle;
  if (!idle) throw new Error('settle(): this page has no idle watch - add it to the context with watch_idle()');
  const moving = document.getAnimations().some(a => a.playState === 'running' && a.effect
    && a.effect.getComputedTiming().iterations !== Infinity);
  const fonts = document.fonts.status === 'loaded';
  idle.quiet = idle.timers.size === 0 && idle.fetches === 0 && fonts && !moving ? idle.quiet + 1 : 0;
  return idle.quiet >= 2;
}"""


# ---------------------------------------------------------------- layout probes shared by the browser test files
# Every visible element matching the selector whose tap area is under 44px wide or high, as "name WxH(hit wxh)": from its
# centre, the px that still answer it going left/right/up/down (each side counted to 60px), as the diagnosis measured them - the
# touch twin of DesktopMisc's 24px probe. A hit area may sit off-centre (the sheet's tool bar reaches only downwards).
MISSES_44 = """sel => {
  const out = [];
  const own = (e, x, y) => { if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return false;
    const h = document.elementFromPoint(x, y); return !!h && (h === e || e.contains(h)); };
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect(); if (!r.width || !r.height || getComputedStyle(e).visibility === 'hidden') continue;
    if (r.top < 0 || r.bottom > innerHeight || r.left < 0 || r.right > innerWidth) continue;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2; let l = 0, ri = 0, u = 0, d = 0;
    if (own(e, cx, cy)) { while (l < 60 && own(e, cx - l - 1, cy)) l++; while (ri < 60 && own(e, cx + ri + 1, cy)) ri++;
      while (u < 60 && own(e, cx, cy - u - 1)) u++; while (d < 60 && own(e, cx, cy + d + 1)) d++; }
    const w = l + ri + 1, h = u + d + 1;
    if (w < 44 || h < 44) out.push((e.id ? '#' + e.id : e.className) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + '(hit ' + w + 'x' + h + ')');
  }
  return out; }"""
# The mouse twin of MISSES_44 (WCAG 2.5.8): every visible element matching the selector that does not answer a click 11.5px
# left, right, over and under its centre, as "class text".
MISSES_24 = """sel => [...document.querySelectorAll(sel)].filter(e => {const r = e.getBoundingClientRect();
  if (!r.width || !r.height) return false; const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  return ![[-11.5, 0], [11.5, 0], [0, -11.5], [0, 11.5]].every(([dx, dy]) => {const h = document.elementFromPoint(cx + dx, cy + dy);
    return !!h && (h === e || e.contains(h));});}).map(e => e.className + ' ' + e.textContent.trim())"""
# Every visible segmented control under root, as drawn: its drawn track (a ladder's .lad-t, else the .seg itself), the track's
# height and radius, the selected thumb's insets from the track (top, bottom) and the end segments' (left, right), the thumb's
# radius, and its shadow's reach below it (y offset + blur, px).
SEGMENTS = """root => [...document.querySelectorAll(root + ' .seg')].filter(s => s.getClientRects().length).map(s => {
  const t = s.querySelector(':scope>.lad-t') || s, T = t.getBoundingClientRect(), bs = [...t.querySelectorAll(':scope>button')];
  const on = t.querySelector(':scope>button.on') || bs[0], O = on.getBoundingClientRect(), cs = getComputedStyle(on);
  const sh = cs.boxShadow === 'none' ? [0, 0] : cs.boxShadow.replace(/rgba?\\([^)]*\\)/, '').trim().split(/\\s+/).map(parseFloat).slice(1, 3);
  const r1 = v => Math.round(v * 10) / 10;
  return {id: s.id || s.className, h: r1(T.height), top: r1(O.top - T.top), bottom: r1(T.bottom - O.bottom),
    left: r1(bs[0].getBoundingClientRect().left - T.left), right: r1(T.right - bs[bs.length - 1].getBoundingClientRect().right),
    rTrack: parseFloat(getComputedStyle(t).borderTopLeftRadius), rThumb: parseFloat(cs.borderTopLeftRadius), reach: sh[0] + sh[1]};})"""
# The ink of each box in a screenshot (base64 PNG at the device pixel ratio, boxes in the shot's CSS px): the pixels that differ
# from the box's own background - read at its left edge, at mid height in a fill, at the top corner of a ghost - each pixel row's
# and column's coverage the strongest difference over the box's strongest; the ink's vertical centre and its left and right
# edges, the partial rows and columns counted by their coverage. A fill is read 6px in from every edge (its rounded corners,
# the halves' seam), a ghost 3px in from its sides, an icon's box (ix: 0) from its own edges.
ROW_INK = """async ([b64, dpr, items]) => {const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.drawImage(img, 0, 0);
  const D = x.getImageData(0, 0, c.width, c.height).data, W = c.width, out = {};
  const lum = (X, Y) => {const i = (Y * W + X) * 4; return 0.2126 * D[i] + 0.7152 * D[i + 1] + 0.0722 * D[i + 2];};
  const edges = (cov, base) => {let f = -1, la = -1; cov.forEach((v, i) => {if (v > 0.12) {if (f < 0) f = i; la = i;}});
    return f < 0 ? null : [(base + f + 1 - cov[f]) / dpr, (base + la + cov[la]) / dpr];};
  for (const it of items) {const [l, t, r, b] = it.box, iy = it.fill ? 6 : 0, ix = it.ix ?? (it.fill ? 6 : 3);
    const X0 = Math.round((l + ix) * dpr), X1 = Math.round((r - ix) * dpr), Y0 = Math.round((t + iy) * dpr), Y1 = Math.round((b - iy) * dpr);
    const bg = lum(X0, it.fill ? Math.round((Y0 + Y1) / 2) : Y0);
    let mx = 0; for (let y = Y0; y < Y1; y++) for (let xx = X0; xx < X1; xx++) mx = Math.max(mx, Math.abs(lum(xx, y) - bg));
    const rows = [], cols = new Array(X1 - X0).fill(0);
    for (let y = Y0; y < Y1; y++) {let m = 0; for (let xx = X0; xx < X1; xx++) {const v = Math.abs(lum(xx, y) - bg) / mx; m = Math.max(m, v);
      cols[xx - X0] = Math.max(cols[xx - X0], v);} rows.push(m);}
    const vy = mx < 8 ? null : edges(rows, Y0), vx = mx < 8 ? null : edges(cols, X0);
    out[it.k] = vy && vx ? {mid: (vy[0] + vy[1]) / 2, left: vx[0], right: vx[1]} : null;}
  return out;}"""


# The fixed viewport list of the 2026-10-09 UX pass, at device scale factor 2: a mouse desktop (the wide layout) and touch
# screens reaching the phone, tablet-sheet, mid-overlay and mid-side bands (docs/handbook/viewer.md §모바일 레이아웃).
_TOUCH = {"is_mobile": True, "has_touch": True, "device_scale_factor": 2}
VIEWPORTS: dict[str, dict] = {
    "desktop 1440x900": {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 2},
    "phone 390x844": dict(_TOUCH, viewport={"width": 390, "height": 844}),
    "phone 320x720": dict(_TOUCH, viewport={"width": 320, "height": 720}),
    "tablet 768x1024": dict(_TOUCH, viewport={"width": 768, "height": 1024}),
    "tablet 1024x768": dict(_TOUCH, viewport={"width": 1024, "height": 768}),
    "fold outer 344x882": dict(_TOUCH, viewport={"width": 344, "height": 882}),
    "fold inner 673x841": dict(_TOUCH, viewport={"width": 673, "height": 841}),
    "fold inner 841x673": dict(_TOUCH, viewport={"width": 841, "height": 673}),
}


def watch_idle(context):
    """Install IDLE_WATCH in every page of context, after the init scripts added so far; settle() needs it."""
    context.add_init_script(IDLE_WATCH)


def settle(page, timeout=15000):
    """Wait until the page has settled: no short timer pending, no fetch in flight, no web font loading, no CSS
    animation or transition running, on two animation frames in a row. After it, whatever the last action set in
    motion - a debounced save, a slide, a server round trip and its redraw, a font slice for new text and the swap -
    has finished, so the next step reads the state it produced, and a check that something did not happen reads the
    page after everything that could have made it happen."""
    page.evaluate("window.__limnIdle && (window.__limnIdle.quiet = 0)")
    page.wait_for_function(QUIET, timeout=timeout, polling="raf")


def fonts_ready(page):
    """Wait for document.fonts.ready - every web font load the page has started has finished, so its text is drawn in
    the bundled Pretendard Variable and not a fallback it shows meanwhile (docs/handbook/viewer.md §글꼴) - and return
    document.fonts.status. A test that reads text ink from a screenshot calls it right before the shot: settle() waits for
    font loads as well, and this says where the ink depends on it."""
    return page.evaluate("document.fonts.ready.then(() => document.fonts.status)")


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
    """A test class sharing one browser (cls.browser, driven through cls.pw) across its tests, defaulting to Chromium.
    BROWSER_ENGINE may select bundled Firefox or WebKit. A subclass that needs
    more class setup calls super().setUpClass() first and super().tearDownClass() last. Every subclass carries the
    pytest marker `browser` (pytest reads pytestmark through the class hierarchy)."""

    pytestmark = pytest.mark.browser
    BROWSER_ENGINE: Literal["chromium", "firefox", "webkit"] = "chromium"

    @classmethod
    def setUpClass(cls):
        """Start Playwright and launch the selected engine; skip the class when either is unavailable, unless
        LIMN_TEST_REQUIRE_BROWSER=1, where the error propagates."""
        super().setUpClass()
        required = os.environ.get("LIMN_TEST_REQUIRE_BROWSER") == "1"
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            if required:
                raise
            raise unittest.SkipTest("Playwright unavailable") from None
        cls.pw = sync_playwright().start()
        try:
            if cls.BROWSER_ENGINE == "chromium":
                exe = os.environ.get("LIMN_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
                cls.browser = cls.pw.chromium.launch(executable_path=exe or None, args=["--no-sandbox"])
            else:
                cls.browser = getattr(cls.pw, cls.BROWSER_ENGINE).launch()
        except Exception as e:  # no bundled or system browser
            cls.pw.stop()
            if required:
                raise
            raise unittest.SkipTest("%s unavailable: %s" % (cls.BROWSER_ENGINE.capitalize(), e)) from e

    @classmethod
    def tearDownClass(cls):
        """Close the selected browser and stop Playwright."""
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
    person WHO. /api/pick is answered with a computed pick result, since the test has no PDF or SyncTeX; a test sets
    PICK to replace fields of that answer (its quote, or a region's shape)."""

    WHO = ALICE
    PICK: dict = {}

    def setUp(self):
        """A fresh 37-line manuscript with a finished two-page build (blank page images), default access settings, and
        a fresh Runtime serving the viewer page built for the "Demo" paper."""
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        src = root / "ms"
        src.mkdir()
        (src / "main.tex").write_text(DEMO_TEX, encoding="utf-8")
        (root / "state").mkdir()
        config = run_config(src, src / "main.tex", root / "state", label="Demo")
        ps.APP = ApplicationFixture(
            config, ps.new_runtime(ps.serve_viewer(ps.read_viewer(), config.label, config.accent, config.ui_lang))
        )
        ps.Handler.app = ps.APP.web
        C = ps.APP.C
        reset_access()  # the access defaults and a fresh Runtime
        serve_viewer("Demo", "#2563eb", ps)
        ps.APP.set_docs(None)
        ps.APP.init_seq()
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
        handler (forward); anything else is aborted."""
        rq = route.request
        u = urlparse(rq.url)
        if u.netloc != "viewer.test":
            return route.abort()
        if u.path == "/api/pick":
            lines = tex_lines(file_in_tree(str(self.main), self.main.parent, self.main.parent / "state"))
            lad = mapping.compute_levels(lines, 5, 5, ps.APP.C.envs)
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
                "pdf_build": cur_pages(ps.APP.docs[0]).name,
            }
            d.update(self.PICK)
            return route.fulfill(status=200, headers={"content-type": "application/json"}, body=json.dumps(d))
        return self.forward(route)

    def forward(self, route):
        """Send one viewer.test request to the in-process handler as WHO (tailnet headers, and a same-origin Origin on a
        POST) and fulfil the route with the handler's answer."""
        rq = route.request
        u = urlparse(rq.url)
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
        out = {"content-type": hdrs.get("content-type", "application/octet-stream")}
        if "content-disposition" in hdrs:  # a download's name, which the browser reads from the answer
            out["content-disposition"] = hdrs["content-disposition"]
        route.fulfill(status=code, headers=out, body=data)

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
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo", timeout=8000)
