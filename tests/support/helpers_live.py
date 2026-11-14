"""The real Limn server on a loopback socket, for the browser tests that need a secure context: the service worker and the
tab that is opened again with no network (docs/handbook/verification.md §실제 소켓의 브라우저 테스트).

BrowserBase serves the viewer through request interception on the fake host viewer.test, which is not a secure context, so
no worker registers there. `http://127.0.0.1:<port>` is a secure context. LiveBase serves the same in-process server copy
(ps.Server and ps.Handler, the way test_viewer_pdf_download does) on an ephemeral port in a daemon thread of the test
process: nothing is spawned, so nothing outlives the test, and the port is released by the cleanup that runs after a
failure or an interrupt as after a pass.

LiveTab is the one place that knows the page's internals. A test asks it for outcomes (what the cache holds, how many pins
wait, what the page drew) and for actions (open, keep, cut off, drag, save); when a page internal is renamed, this file is
the one to change. The internals it reads are named in JS below.
"""

import json
import threading
import time
import urllib.request

from helpers import ps
from helpers_browser import BrowserBase

# Words page 1 of the build's PDF carries, at 72pt from the left and 92pt from the top of a 612x792 page.
PDF_WORDS = "Offline kept words"
# A drag over those words, as fractions of page 1 (x0, y0, x1, y1).
OVER_WORDS = (0.05, 0.07, 0.9, 0.13)
# The service worker's cache (sw.js CACHE).
CACHE_NAME = "limn-offline-v1"
# Wide and tall enough that a drag anywhere on page 1 is on screen without scrolling.
VIEWPORT = {"width": 1440, "height": 1500}

# What the page must have drawn before a test acts: the document read and its first page element.
DRAWN = "typeof META!=='undefined'&&!!META&&!!META.pages&&META.pages.length>0&&!!document.getElementById('p1')"
CONTROLLED = "!!(navigator.serviceWorker&&navigator.serviceWorker.controller)"
PDF_OPEN = "typeof VEC!=='undefined'&&!!VEC&&!!VEC.doc"


def two_page_pdf(words: str) -> bytes:
    """A valid PDF of the two 612x792 pages BrowserBase's build shows (the viewer opens a PDF only when its page count is the
    screen's): page 1 carries words, page 2 the words "second page"."""
    streams = [
        b"BT /F1 24 Tf 72 700 Td (" + words.encode("ascii") + b") Tj ET",
        b"BT /F1 24 Tf 72 700 Td (second page) Tj ET",
    ]
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
    ]
    for i in range(2):
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R" % (5 + i)
            + b" /Resources << /Font << /F1 7 0 R >> >> >>"
        )
    for stream in streams:
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


class LiveBase(BrowserBase):
    """BrowserBase's fresh manuscript and two-page build with a real PDF in the build folder, served by the real server on
    a loopback socket. Contexts open on it are secure contexts (see open_live)."""

    LOCALE = "ko-KR"  # notice text follows the browser language

    def setUp(self):
        """The build folder gets a PDF whose text is PDF_WORDS, and the server starts listening."""
        super().setUp()
        self.doc = ps.APP.docs[0]
        self.write_pdf()
        # Every request passes this gate once it has been read and before it is handled (stop_answering) - a request on
        # a connection kept alive as much as one on a new connection. When the test is over the gate is opened for good
        # and what was left waiting is dropped unhandled (leave): the request threads are daemons the listener does
        # not wait for, and a write handled then would land in a state folder that is being removed.
        self.answering = answering = threading.Event()
        answering.set()
        self.finishing = finishing = threading.Event()
        finishing.set()
        over = threading.Event()

        class Gated(ps.Handler):
            def parse_request(self):
                parsed = super().parse_request()
                answering.wait()
                return parsed and not over.is_set()

            def end_headers(self):
                # The answer's head goes out and its body waits at this gate (stop_finishing): a connection lost
                # while an answer is on its way.
                super().end_headers()
                self.wfile.flush()
                finishing.wait()

        def leave():
            over.set()
            answering.set()
            finishing.set()

        self.httpd = ps.Server(("127.0.0.1", 0), Gated)
        self.serving = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.serving.start()
        # Cleanups run last in, first out: the contexts opened later are closed before the listener stops.
        self.addCleanup(self.stop_serving)
        self.addCleanup(leave)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def stop_serving(self):
        """Stop accepting, release the port, and wait for the thread."""
        self.httpd.shutdown()
        self.httpd.server_close()
        self.serving.join(10)
        self.assertFalse(self.serving.is_alive(), "the server thread did not stop")

    def stop_answering(self):
        """The server takes every connection and answers none: a request is neither refused nor answered, and waits.

        This is what a tailnet with no internet behind it does - the name resolves, the request goes into the tunnel
        and nothing comes back - and it is not what set_offline does, where every request fails at once."""
        self.answering.clear()

    def stop_finishing(self):
        """The server starts every answer and finishes none: the head arrives and the body never does - a connection
        lost while an answer is on its way."""
        self.finishing.clear()

    def answer_again(self):
        """The server answers again, the requests left waiting first: one the browser gave up on is still handled."""
        self.answering.set()
        self.finishing.set()

    def write_pdf(self, words=PDF_WORDS):
        """The PDF of the build on screen: one 612x792 page carrying words."""
        build = self.doc.dir / (self.doc.dir / "pages.cur").read_text().strip()
        (build / self.doc.pdf_name).write_bytes(two_page_pdf(words))

    def server(self, method, path, body=None):
        """A request as an agent on the server's own machine makes one - the network the browser lost is still here ->
        the JSON answer. The call is made by the test's process, so cutting the browser off does not touch it."""
        request = urllib.request.Request(
            self.base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=300) as answer:
            return json.loads(answer.read() or b"null")

    def pins(self):
        """Every pin the server holds (open, review and done)."""
        rows = self.server("GET", "/api/pins?all=1")
        return rows if isinstance(rows, list) else rows.get("pins", [])

    def holds(self):
        """The builds the server holds, from holds.json of the document's folder."""
        path = self.doc.dir / "holds.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def open_live(self, url="/", init=None, **options):
        """A new browser context on the server and its page, drawn and under the worker's control; a LiveTab. init is a
        script that runs in the page before the viewer's own.

        The context bypasses the page's CSP, as Playwright's string evaluation needs (the policy itself is
        test_viewer_csp's). It fails, and does not carry on without a worker, if none controls the page."""
        context = self.browser.new_context(
            **{"viewport": VIEWPORT, "bypass_csp": True, "locale": self.LOCALE, **options}
        )
        self.addCleanup(context.close)
        if init:
            context.add_init_script(init)
        tab = LiveTab(self, context, context.new_page())
        tab.page.set_default_timeout(30000)
        tab.errors = []
        tab.page.on("pageerror", lambda e: tab.errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(tab.errors, []))
        tab.page.goto(self.base + url, wait_until="domcontentloaded")
        tab.wait_drawn()
        tab.wait_controlled()
        return tab


class LiveTab:
    """One page of a LiveBase context, with the page's internals behind named methods."""

    def __init__(self, test, context, page):
        self.test, self.context, self.page = test, context, page
        self.errors: list[str] = []

    # ------------------------------------------------------------------------------------------------ waiting
    def wait_drawn(self, pdf=True):
        """The document is drawn (its page list and first page element) and, with pdf, PDF.js has opened its PDF."""
        self.page.wait_for_function(DRAWN)
        if pdf:
            self.page.wait_for_function(PDF_OPEN)

    def wait_controlled(self):
        """A service worker controls this page. This is the failure a worker that never registers shows, not a skip."""
        try:
            self.page.wait_for_function(CONTROLLED, timeout=20000)
        except Exception as error:
            raise AssertionError("no service worker controls the page: it did not register") from error

    def wait_for(self, js, timeout=30000):
        """The page expression js is truthy."""
        self.page.wait_for_function(js, timeout=timeout)

    def until(self, check, timeout=15.0, what="the condition"):
        """check(), a Python callable, is truthy; polled without a fixed wait, for what only the test's process can see."""
        end = time.monotonic() + timeout
        while not check():
            if time.monotonic() > end:
                raise AssertionError("%s did not come true in %ss" % (what, timeout))
            time.sleep(0.05)

    # ------------------------------------------------------------------------------------------------ the network
    def cut_off(self):
        """The browser loses the network (navigator.onLine is false, every request fails)."""
        self.context.set_offline(True)

    def reconnect(self):
        """The network is back, and the page is told so as a browser does."""
        self.context.set_offline(False)
        self.page.evaluate("window.dispatchEvent(new Event('online'))")

    def reopen(self):
        """The tab is opened again (a reload), and waits until it has drawn the document it was given."""
        self.page.reload(wait_until="domcontentloaded")
        self.wait_drawn()

    # ------------------------------------------------------------------------------------------------ keeping
    def keep(self):
        """[더보기] -> [오프라인으로 받기], and wait for it to be done: the server holds the build and the page has let go.

        The server's hold (holds.json) is the last effect the page waits for, and OFF.prep is the page's own flag for
        the whole run; neither is a notice, so the wait does not depend on the language."""
        self.page.click("#btn-more")
        self.page.click("#m-offline")
        build = self.build()
        self.until(lambda: build in self.test.holds(), what="the server's hold of the build")
        self.wait_for("OFF.prep===false")
        return build

    def build(self):
        """The build the screen is drawn from."""
        return self.page.evaluate("META.pages_build")

    def kept(self):
        """The kept record (offline.js OFF_KEPT): what each document keeps ({docs: {key: {build, ...}}}) and the old builds
        not dropped yet ({old: [{doc, build, ...}]}); None for an instance never kept."""
        return self.page.evaluate("async () => await offKept()")

    def kept_build(self, doc):
        """The build the kept record says document doc keeps, or None."""
        record = self.kept() or {}
        return ((record.get("docs") or {}).get(doc) or {}).get("build")

    def cache_urls(self):
        """The addresses (path and query) the worker has kept copies of, sorted."""
        return self.page.evaluate(
            """async name => {const c = await caches.open(name);
              return (await c.keys()).map(r => {const u = new URL(r.url); return u.pathname + u.search;}).sort();}""",
            CACHE_NAME,
        )

    # ------------------------------------------------------------------------------------------------ reads
    def fetch(self, path):
        """A plain fetch from the page -> {ok, status, size} (the body's bytes) or {ok: False, error}."""
        return self.page.evaluate(
            """async path => {try {const r = await fetch(path); return {ok: r.ok, status: r.status, size: (await r.arrayBuffer()).byteLength};}
              catch (e) {return {ok: false, error: String(e)};}}""",
            path,
        )

    def api(self, url, **options):
        """The viewer's own api(url, options) -> {ok, status, data} when it answered, {ok: False, error} when it threw.
        The page's api() is the one that stores document reads and answers from the store."""
        return self.page.evaluate(
            """async ([url, options]) => {try {const r = await api(url, options); return {ok: true, status: r.status, data: r.data};}
              catch (e) {return {ok: false, error: String(e), status: e && e.status || 0};}}""",
            [url, options],
        )

    def read_url(self, path):
        """The address the viewer asks for path with, for the document on screen (dq: /api/meta -> /api/meta?doc=main)."""
        return self.page.evaluate("path => dq(path)", path)

    def stored(self, url):
        """The answer stored for a document read of url, as the page asks it with or without the document's name, or None."""
        return self.page.evaluate(
            "async url => (await offStashed(url, null)) || (await offStashed(dq(url), null))", url
        )

    def stored_stash(self, url, data, status=200):
        """Store an answer for url the way a read does, and wait until it can be read back."""
        self.page.evaluate("([u, d, s]) => offStash(u, d, s, null)", [url, data, status])
        self.until(lambda: self.stored(url) is not None, what="the stored answer")

    def stale_said(self):
        """The screen has said it was drawn from stored reads."""
        return self.page.evaluate("OFF.saidStale")

    def notices(self):
        """How many messages the page has shown so far (the status line's and banners')."""
        return self.page.evaluate("NOTICES.size")

    def save_failure(self):
        """Whether the composer shows a failed save (its banner)."""
        return self.page.evaluate("(() => { const b = BANNERS.get(NOTICE_HOST.COMPOSER); return !!b && !!b.save; })()")

    def fail_api_reads(self, on=True):
        """Make the page's fetch refuse every /api/ call as a failed connection does (a TypeError), while the browser itself
        stays online: a read that fails with the viewer connected, which no network switch can make."""
        self.page.evaluate(
            """on => {
              if (!window.__realFetch) window.__realFetch = window.fetch;
              window.fetch = on
                ? (u, o) => (String(u).startsWith('/api/') ? Promise.reject(new TypeError('Failed to fetch')) : window.__realFetch(u, o))
                : window.__realFetch;
            }""",
            on,
        )

    def answer_reads_with(self, status, body=None):
        """Make the page's fetch get this status and JSON body for every /api/ GET, as a server that refuses; None for the
        status puts the real server back."""
        self.page.evaluate(
            """([status, body]) => {
              if (!window.__realFetch) window.__realFetch = window.fetch;
              window.fetch = status === null ? window.__realFetch
                : (u, o) => (String(u).startsWith('/api/') && !(o && o.method && o.method !== 'GET')
                  ? Promise.resolve(new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}}))
                  : window.__realFetch(u, o));
            }""",
            [status, body],
        )

    def fail_api_reads_from_the_next_visit(self):
        """Every visit this tab makes from now on starts with its /api/ calls refused as a failed connection does (the
        browser stays online), until the page is told otherwise: the first reads of a visit that the network refuses."""
        self.page.add_init_script(
            """(() => {
              const real = window.fetch;
              window.fetch = (u, o) => String(u).startsWith('/api/')
                ? Promise.reject(new TypeError('Failed to fetch')) : real.call(window, u, o);
            })()"""
        )

    def waits(self, **ms):
        """How long this page's requests wait for an answer (api.js API_WAIT: POLL, READ, PICK, SAVE, SEND), in ms."""
        self.page.evaluate("w => { Object.assign(API_WAIT, w); }", ms)

    def lost(self):
        """Whether the page says the connection is gone (the light poll's count, which is what queues a save)."""
        return self.page.evaluate("offlineNow()")

    def asked(self, path):
        """A list that fills with the bodies of this page's requests to path from now on."""
        seen: list[str] = []
        self.page.on(
            "request", lambda r: seen.append(r.post_data or "") if r.url.split("?")[0].endswith(path) else None
        )
        return seen

    def refuse_cache_writes(self):
        """The worker's cache refuses every write from now on, as a browser out of room does."""
        self.context.service_workers[0].evaluate(
            """() => { const open = caches.open.bind(caches);
              caches.open = async name => { const c = await open(name);
                return new Proxy(c, {get: (t, k) => k === 'put' ? () => Promise.reject(new Error('QuotaExceededError'))
                  : typeof t[k] === 'function' ? t[k].bind(t) : t[k]}); }; }"""
        )

    def ask_worker(self, message, wait=20000):
        """One question to the worker, as the page asks it (offlineAsk) -> its reply."""
        return self.page.evaluate("async ([m, ms]) => await offlineAsk(m, ms)", [message, wait])

    def stop_polling(self):
        """The light poll stops, so no poll's answer or failure changes what a test is reading."""
        self.page.evaluate("clearInterval(LIGHT_TIMER)")

    # ------------------------------------------------------------------------------------------------ the page's state
    def state(self):
        """What the tab shows: the build, the number of pages, the open pins' notes, whether it says it is a stored screen."""
        return self.page.evaluate(
            """({build: META.pages_build, pages: META.pages.length, notes: OPEN_ALL.map(p => p.note),
                 stale: OFF.saidStale})"""
        )

    # ------------------------------------------------------------------------------------------------ pinning
    def drag(self, box=OVER_WORDS, page_no=1):
        """Drag a region on a page with the mouse, as page fractions (x0, y0, x1, y1), and wait for the composer."""
        rect = self.page.locator("#p%d" % page_no).bounding_box()
        x0, y0, x1, y1 = box
        mouse = self.page.mouse
        mouse.move(rect["x"] + rect["width"] * x0, rect["y"] + rect["height"] * y0)
        mouse.down()
        mouse.move(rect["x"] + rect["width"] * (x0 + x1) / 2, rect["y"] + rect["height"] * (y0 + y1) / 2, steps=4)
        mouse.move(rect["x"] + rect["width"] * x1, rect["y"] + rect["height"] * y1, steps=4)
        mouse.up()
        self.page.wait_for_selector("#composer:not([hidden])")

    def drag_over_words(self):
        """Drag over the words of page 1 -> the selection (see composer)."""
        self.drag(OVER_WORDS)
        return self.composer()

    def composer(self):
        """The open selection: whether it was made with no network, its page, its words, and whether a box is drawn."""
        self.wait_for("!!COMPOSE.current")
        return self.page.evaluate(
            """({offline: COMPOSE.current.offline === true, page: COMPOSE.current.page,
                 quote: COMPOSE.current.quote, box: !!COMPOSE.box})"""
        )

    def write_note(self, text):
        """Type text in the composer's note and save the pin ([핀 저장]); returns when the composer has closed."""
        self.page.fill("#note", text)
        self.page.evaluate("savePin()")
        self.wait_for("document.querySelector('#composer').hidden")

    def pin_offline(self, note, box=OVER_WORDS):
        """Drag, write the note and save while cut off; waits until the pin is in the queue. -> the selection the drag made."""
        before = self.queued()
        self.drag(box)
        selection = self.composer()
        self.write_note(note)
        self.wait_for("OFF.n===%d" % (before + 1))
        return selection

    # ------------------------------------------------------------------------------------------------ the queue
    def queued(self):
        """How many pins wait in this browser's queue."""
        return self.page.evaluate("async () => (await offAll()).length")

    def queue(self):
        """The queued records, oldest first. Their shape is the page's own; tests read the note, page and build."""
        return self.page.evaluate("async () => await offAll()")

    def unsent(self):
        """The status line's count of waiting pins and of those held back."""
        return self.page.evaluate("({n: OFF.n, held: OFF.held})")

    def queued_drag(self, build):
        """The pick request that the first queued pin's drag makes, in the points of the page on that build: what an
        online pick of the same drag is asked (POST /api/pick), for a test to compare the offline pin's lines with."""
        record = self.queue()[0]
        frac, size = record["frac"], record["pt"]
        return {
            "page": record["page"],
            "x0": frac[0] * size["w"],
            "y0": frac[1] * size["h"],
            "x1": (frac[0] + frac[2]) * size["w"],
            "y1": (frac[1] + frac[3]) * size["h"],
            "frac": frac,
            "pdf_build": build,
        }

    def lose_the_next_pin_answer(self):
        """The next POST /api/pin that creates a pin reaches the server, and its answer never comes back - what a
        connection that drops mid-request does. The question a viewer asks by key alone (replay_only) passes."""
        lost = {"n": 0}

        def handler(route):
            body = route.request.post_data or ""
            if route.request.method != "POST" or '"replay_only"' in body or lost["n"]:
                route.continue_()
                return
            lost["n"] += 1
            route.fetch()  # the server handles it and writes the pin
            route.abort()  # and the browser never hears

        self.page.route("**/api/pin", handler)
        return lost

    def until_routed(self, check, timeout=30.0, what="the condition"):
        """until(), for a condition a route handler brings about: each round lets the page run a moment, which is
        when Playwright's sync API calls the handler. A wait that only sleeps in Python never lets it run, and the
        request it should answer stays held."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.page.wait_for_timeout(100)
            if check():
                return
        raise AssertionError("%s did not come true in %ss" % (what, timeout))

    def send_queue(self):
        """Send the queue now, as the status line's [지금 반영] does, and wait until that send is over."""
        self.page.evaluate("async () => { await offlineFlush(); }")

    def record_sent(self):
        """Whether the first queued record is marked as attempted (the page's own mark; None with an empty queue)."""
        return self.page.evaluate("async () => { const a = await offAll(); return a.length ? !!a[0].sent : null; }")

    def drop_queue(self):
        """Empty the queue without sending it."""
        self.page.evaluate("async () => {for (const r of await offAll()) await offDel(r.id); await offlineSync();}")
