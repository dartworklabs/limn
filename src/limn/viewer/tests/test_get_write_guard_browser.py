"""Actual external-resource and navigation chains must remain GET-only and preserve persistent state."""

import hashlib
import http.server
import threading
from functools import partial
from pathlib import Path

from helpers import ps, set_config
from helpers_browser import BrowserBase


def snapshot(root):
    """Keep a filesystem oracle independent of the store's own polling signature."""
    return {
        str(p.relative_to(root)): (
            p.stat().st_ino,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).digest() if p.is_file() else None,
        )
        for p in (root, *root.rglob("*"))
        if not p.is_symlink()
    }


BOOT = """() => new Promise((resolve, reject) => {
  const end = performance.now() + 15000;
  function poll() {
    if (typeof LIGHT_TIMER !== 'undefined' && LIGHT_TIMER !== null) return resolve();
    if (performance.now() > end) return reject(new Error('boot incomplete'));
    requestAnimationFrame(poll);
  }
  poll();
})"""


class ExternalReadChains(BrowserBase):
    """A real loopback listener and fresh temporary manuscript/state, with no startup workers to confound reads."""

    def test_resources_navigation_boot_and_poll_never_write(self):
        """Eight browser entry methods, both site relationships, boot/poll/unload: no files or automatic POSTs."""
        set_config(ps, auth="local", local_user="reader")
        server = ps.Server(("127.0.0.1", 0), ps.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_port
        external = Path(self.tmp.name) / "external"
        external.mkdir()
        (external / "index.html").write_text("<!doctype html><title>External entry</title><button id='go'>Go</button>")
        other = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(http.server.SimpleHTTPRequestHandler, directory=str(external))
        )
        other_thread = threading.Thread(target=other.serve_forever, daemon=True)
        other_thread.start()
        try:
            for host in ("localhost", "127.0.0.1"):
                for method in ("img", "script", "link", "fetch", "click", "location", "form", "open"):
                    with self.subTest(host=host, entry=method), self.browser.new_context() as context:
                        page = context.new_page()
                        observed = []
                        context.on(
                            "request", lambda request, observed=observed: observed.append((request.method, request.url))
                        )
                        page.goto("http://%s:%d/" % (host, other.server_port))
                        before = snapshot(ps.APP.C.state), snapshot(ps.APP.C.src)
                        target = base + ("/api/meta" if method in ("img", "script", "link", "fetch") else "/")
                        page.evaluate(
                            """({method, target}) => {
                          document.getElementById('go').onclick = () => {
                            if (method === 'fetch') { fetch(target, {mode: 'no-cors'}); return; }
                            if (method === 'location') { location.href = target; return; }
                            if (method === 'open') { window.open(target); return; }
                            if (method === 'click') { const a = document.createElement('a'); a.href=target; a.click(); return; }
                            if (method === 'form') { const f=document.createElement('form'); f.action=target; f.method='GET'; document.body.append(f); f.submit(); return; }
                            const element=document.createElement(method);
                            if (method === 'link') { element.rel='stylesheet'; element.href=target; }
                            else element.src=target;
                            document.body.append(element);
                          };
                        }""",
                            {"method": method, "target": target},
                        )
                        if method == "open":
                            with page.expect_popup() as popup:
                                page.click("#go")
                            viewer = popup.value
                            viewer.wait_for_load_state()
                        else:
                            with page.expect_response(lambda response, target=target: response.url.startswith(target)):
                                page.click("#go")
                            viewer = page
                        if method in ("click", "location", "form", "open"):
                            viewer.evaluate(BOOT)
                            # Exercise the actual polling function and give unload hooks their normal lifecycle.
                            viewer.evaluate("() => pollLightOnce()")
                            viewer.goto("about:blank")
                        page.wait_for_timeout(100)  # bounded negative observation: detect a delayed automatic write
                        self.assertFalse([m for m, url in observed if url.startswith(base) and m != "GET"])
                        self.assertEqual((snapshot(ps.APP.C.state), snapshot(ps.APP.C.src)), before)
        finally:
            other.shutdown()
            other.server_close()
            other_thread.join(5)
            server.shutdown()
            server.server_close()
            thread.join(5)


class ExternalReadChainsFirefox(ExternalReadChains):
    """Run the same entry-chain contract in Firefox's independent networking engine."""

    BROWSER_ENGINE = "firefox"
