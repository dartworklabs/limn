"""The anonymous UX preview allows only explicit hosts and isolated demo resources."""

import argparse
import importlib.util
import json
import socket
import subprocess
import sys
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from hypothesis import given, strategies as st

from helpers_browser import ChromiumTestCase, settle, watch_idle

SPEC = importlib.util.spec_from_file_location(
    "ux_poc_serve", Path(__file__).resolve().parents[2] / "tools" / "ux-poc" / "serve.py"
)
assert SPEC and SPEC.loader
demo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = demo
SPEC.loader.exec_module(demo)
PUBLIC_HOST = "preview.example.ts.net:5174"
MALFORMED_PUBLIC_HOSTS = (
    "",
    "ts.net:5174",
    "preview.example.ts.net",
    "https://preview.example.ts.net:5174",
    "preview.example.ts.net:5174/",
    "preview.example.ts.net:5174?variant=current",
    "preview.example.ts.net:5174#fragment",
    "alice@preview.example.ts.net:5174",
    "*.example.ts.net:5174",
    "preview.example.ts.net.evil.test:5174",
    "preview.example.test:5174",
    "127.0.0.1:5174",
    "[::1]:5174",
    "Preview.example.ts.net:5174",
    "preview..ts.net:5174",
    "-preview.example.ts.net:5174",
    "preview-.example.ts.net:5174",
    "preview_example.ts.net:5174",
    "preview.example.ts.net.:5174",
    " preview.example.ts.net:5174",
    "preview.example.ts.net:5174 ",
    "preview.example.ts.net:0",
    "preview.example.ts.net:65536",
    "preview.example.ts.net:05174",
    "preview.example.ts.net:+5174",
    "preview.example.ts.net:5174:5174",
    "a" * 64 + ".ts.net:5174",
    ".".join(["a" * 63] * 4) + ".ts.net:5174",
)


@contextmanager
def running_demo(public_host=PUBLIC_HOST):
    """Run the authored demo with real bundled assets on an isolated ephemeral socket."""
    directory = Path(demo.__file__).parent
    assets = demo.static_assets(directory)
    files = demo.read_viewer()
    pages = {
        name: demo.demo_page(files.template, assets["/reading.json"][0], name == "proposal")
        for name in ("current", "proposal")
    }
    with ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler) as server:
        server.RequestHandlerClass = demo.make_handler(
            directory,
            pages,
            assets,
            server.server_port,
            demo.parse_public_host(public_host) if public_host is not None else None,
        )
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


def request(port, host, path="/", method="GET"):
    """Send an actual HTTP request with an explicit Host and read its entire response."""
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, headers={"Host": host})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def public_server():
    """Share one isolated real demo server with an explicitly granted tailnet authority."""
    with running_demo() as port:
        yield port


def test_explicit_tailnet_host_serves_the_anonymous_preview(public_server):
    """The configured tailnet authority can retrieve the comparison through its proxy."""
    status, headers, body = request(public_server, PUBLIC_HOST)
    assert status == 200
    assert b"native-fixture.js" in body
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_default_configuration_refuses_a_tailnet_host():
    """A tailnet-looking Host grants no access until the optional authority is configured."""
    with running_demo(public_host=None) as port:
        status, _, body = request(port, PUBLIC_HOST)
        local_status, _, _ = request(port, f"127.0.0.1:{port}")
    assert status == 403
    assert body == b"Host refused"
    assert local_status == 200


@pytest.mark.parametrize("hostname", ("127.0.0.1", "localhost"))
@pytest.mark.parametrize("variant", ("current", "proposal"))
def test_loopback_hosts_keep_both_native_comparison_variants(public_server, hostname, variant):
    """Adding a tailnet authority preserves each existing local comparison page and fixture."""
    status, _, body = request(public_server, f"{hostname}:{public_server}", f"/?variant={variant}")
    assert status == 200
    assert b"native-fixture.js" in body
    assert (b'<script src="/native.js"></script>' in body) == (variant == "proposal")
    assert (b'<link rel="stylesheet" href="/native.css">' in body) == (variant == "proposal")


@pytest.mark.parametrize("query", ("?variant=unknown", "?variant=current&variant=proposal"))
def test_unknown_or_ambiguous_variants_are_rejected(public_server, query):
    """An allowed Host cannot select an unknown or repeated comparison variant."""
    status, _, body = request(public_server, PUBLIC_HOST, "/" + query)
    assert status == 400
    assert body == b"Unknown comparison variant"


@pytest.mark.parametrize(
    "host",
    (
        "foreign.example.test:5174",
        "other.example.ts.net:5174",
        "preview.example.ts.net:443",
        "preview.example.ts.net",
        "preview.example.ts.net.:5174",
        "preview.example.ts.net:05174",
        "preview.example.ts.net.evil.test:5174",
        "preview.example.ts.net:5174 ",
        "Preview.example.ts.net:5174",
        "alice@preview.example.ts.net:5174",
        "https://preview.example.ts.net:5174",
        "localhost:5174",
    ),
)
def test_host_must_match_one_exact_configured_authority(public_server, host):
    """Neither a related DNS name, alternate encoding, nor a different port receives an asset."""
    status, _, body = request(public_server, host, "/sample.pdf")
    assert status == 403
    assert body == b"Host refused"


@pytest.mark.parametrize("hosts", ((), (PUBLIC_HOST, PUBLIC_HOST), (PUBLIC_HOST, "foreign.example.test:5174")))
def test_missing_or_duplicate_host_headers_are_denied(public_server, hosts):
    """Host ambiguity is denied even when one or both supplied headers would otherwise be trusted."""
    connection = HTTPConnection("127.0.0.1", public_server, timeout=5)
    try:
        connection.putrequest("GET", "/", skip_host=True)
        for host in hosts:
            connection.putheader("Host", host)
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 403
        assert response.read() == b"Host refused"
    finally:
        connection.close()


@pytest.mark.parametrize("method", ("POST", "PUT", "PATCH", "DELETE"))
@pytest.mark.parametrize("path", ("/", "/api/pin", "/native.js"))
@pytest.mark.parametrize("allowed", (True, False))
def test_http_mutations_are_disabled_for_every_host(public_server, method, path, allowed):
    """Trusted requests cannot mutate resources, and foreign hosts are rejected before method handling."""
    host = PUBLIC_HOST if allowed else "foreign.example.test:5174"
    status, _, body = request(public_server, host, path, method)
    assert status == (405 if allowed else 403)
    assert body == (b"Demo HTTP mutations are disabled" if allowed else b"Host refused")


@pytest.mark.parametrize(
    "path",
    (
        "/api/pins",
        "/api/docs",
        "/api/people",
        "/api/meta",
        "/api/snippet?file=main.tex&lo=1&hi=10",
        "/api/rebuild",
        "/pins.md",
        "/tokens.json",
        "/serve.py",
        "/../README.md",
        "/%2e%2e/README.md",
        "/native.css/../serve.py",
        "/reading.json/../native-reading.json",
        "/vendor/pdfjs/README.md",
    ),
)
def test_api_and_unlisted_files_are_unavailable(public_server, path):
    """The tailnet authority permits only demo resources, never API reads or filesystem traversal."""
    status, _, body = request(public_server, PUBLIC_HOST, path)
    assert status == 404
    assert body == b"Resource not in demo allowlist"


@pytest.mark.parametrize(
    "path,media",
    (
        ("/native-fixture.js", ("text/javascript", "application/javascript")),
        ("/native.js", "text/javascript"),
        ("/native.css", "text/css"),
        ("/reading.json", "application/json"),
        ("/sample.pdf", "application/pdf"),
        ("/pdf", "application/pdf"),
        ("/sample.png", "image/png"),
        ("/pages/demo-build-1/page-1.png", "image/png"),
        ("/pages/demo-build-2/page-1.png", "image/png"),
        ("/pages/demo-build-1/page-2.png", "image/png"),
        ("/pages/demo-build-2/page-3.png", "image/png"),
        ("/native-pdf.mjs", "text/javascript"),
        ("/vendor/pdfjs/pdf.min.mjs", "text/javascript"),
    ),
)
def test_allowlisted_assets_remain_available_through_tailnet(public_server, path, media):
    """Real authored fixtures, proposal leaves, and vendor code are reachable through the exact public Host."""
    status, headers, body = request(public_server, PUBLIC_HOST, path)
    assert status == 200
    assert body
    assert headers["Content-Type"] in (media if isinstance(media, tuple) else (media,))
    assert int(headers["Content-Length"]) == len(body)


@pytest.mark.parametrize("path,allowed,status", (("/", True, 200), ("/api/pins", True, 404), ("/", False, 403)))
def test_head_preserves_get_status_and_length_without_a_body(public_server, path, allowed, status):
    """HEAD uses the same Host and resource boundary as GET and transmits no success or refusal body."""
    host = PUBLIC_HOST if allowed else "foreign.example.test:5174"
    get_status, get_headers, get_body = request(public_server, host, path)
    head_status, head_headers, head_body = request(public_server, host, path, "HEAD")
    assert get_status == head_status == status
    assert head_headers["Content-Length"] == get_headers["Content-Length"] == str(len(get_body))
    assert head_body == b""
    # HTTPConnection discards HEAD bodies; observe the socket as well to detect an accidental write.
    with socket.create_connection(("127.0.0.1", public_server), timeout=5) as connection:
        connection.sendall(f"HEAD {path} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode("ascii"))
        with connection.makefile("rb") as response:
            raw = response.read()
    _, separator, raw_body = raw.partition(b"\r\n\r\n")
    assert separator
    assert raw_body == b""


@pytest.mark.parametrize("value", MALFORMED_PUBLIC_HOSTS)
def test_cli_rejects_malformed_public_hosts_before_starting(value):
    """Invalid authorities exit through argparse before the CLI loads assets or binds a server."""
    result = subprocess.run(
        [sys.executable, demo.__file__, "--public-host", value], capture_output=True, text=True, timeout=5, check=False
    )
    assert result.returncode == 2
    assert "argument --public-host:" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("value", MALFORMED_PUBLIC_HOSTS)
def test_public_host_value_cannot_contain_a_malformed_authority(value):
    """Programmatic callers cannot bypass CLI validation by constructing an invalid grant."""
    with pytest.raises(ValueError, match="public host must be"):
        demo.PublicHost(value)


@given(st.text(max_size=400))
def test_public_host_parser_returns_an_exact_grant_or_argparse_rejection(value):
    """Arbitrary Unicode and oversized authority strings cannot crash or silently normalize the parser."""
    try:
        parsed = demo.parse_public_host(value)
    except argparse.ArgumentTypeError:
        return
    assert isinstance(parsed, demo.PublicHost)
    assert parsed.authority == value


@given(st.from_regex(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", fullmatch=True), st.integers(1, 65535))
def test_canonical_generated_tailnet_authorities_are_accepted(label, port):
    """Canonical DNS labels and every valid HTTPS port preserve the exact supplied authority."""
    authority = f"{label}.example.ts.net:{port}"
    assert demo.parse_public_host(authority).authority == authority


class NativePreviewBrowser(ChromiumTestCase):
    """Exercise actual native fixture/PDF.js behavior with fine and coarse browser contexts.

    These browser emulations inform the PoC review; they establish no physical
    keyboard, hinge, safe-area, stylus, iOS, or screen-reader result.
    """

    @classmethod
    def setUpClass(cls):
        """Start the shared Chromium harness and one isolated, loopback-only fixture server."""
        super().setUpClass()
        cls.server = running_demo(public_host=None)
        cls.port = cls.server.__enter__()

    @classmethod
    def tearDownClass(cls):
        """Release the fixture socket and browser even after an assertion failure."""
        cls.server.__exit__(None, None, None)
        super().tearDownClass()

    def open_preview(self, width, height, touch=False, variant="proposal"):
        """Load one actual variant in a fresh native pointer context and wait for boot/fonts."""
        context = self.browser.new_context(
            viewport={"width": width, "height": height}, has_touch=touch, is_mobile=touch
        )
        self.addCleanup(context.close)
        watch_idle(context)
        page = context.new_page()
        page.goto(f"http://127.0.0.1:{self.port}/?variant={variant}")
        page.wait_for_function("META&&META.pages.length===3&&LIGHT_TIMER!==null")
        settle(page)
        return page

    def geometry(self, page):
        """Measure stable native bands, viewport cost, and actual coarse media without changing classes."""
        return page.evaluate("""() => {
          const r=e=>{const b=e.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height,right:b.right,bottom:b.bottom};};
          return {width:innerWidth,height:innerHeight,coarse:matchMedia('(pointer:coarse)').matches,
            classes:document.body.className,overflow:document.documentElement.scrollWidth-innerWidth,
            pdf:r(document.querySelector('#left')),top:r(document.querySelector('#doc-nav')),
            tools:Array.from(document.querySelectorAll('#ux-doc-tools button')).map(r)};
        }""")

    def test_coarse_phone_tablet_foldable_find_read_and_native_geometry(self):
        """Real coarse media preserves native bands and maps repeated PDF hits to true page 2."""
        matrix = (
            ("phone-small", 320, 720, "phone"),
            ("phone", 390, 844, "phone"),
            ("fold-outside", 344, 882, "phone"),
            ("tablet-portrait", 768, 1024, "tablet-sheet"),
            ("tablet-landscape", 1024, 768, "mid-side"),
            ("fold-inside-673", 673, 960, "tablet-sheet"),
            ("fold-inside-717", 717, 960, "tablet-sheet"),
            ("fold-landscape", 960, 717, "mid-side"),
        )
        for name, width, height, band in matrix:
            with self.subTest(name=name):
                current = self.open_preview(width, height, touch=True, variant="current")
                baseline = self.geometry(current)
                page = self.open_preview(width, height, touch=True)
                observed = self.geometry(page)
                self.assertTrue(observed["coarse"])
                self.assertIn("band-" + band, observed["classes"])
                self.assertEqual(observed["overflow"], 0)
                self.assertEqual(observed["pdf"]["h"], baseline["pdf"]["h"])
                for target in observed["tools"]:
                    self.assertGreaterEqual(target["w"], 44)
                    self.assertGreaterEqual(target["h"], 44)
                    self.assertLessEqual(target["right"], width)
                page.locator("#ux-find").tap()
                page.locator("#ux-body-query").fill("thermal")
                page.wait_for_function("document.querySelector('#ux-body-count').textContent==='1/2 · 2쪽'")
                self.assertEqual(page.locator("#p2 .ux-body-hit").count(), 1)
                self.assertEqual(page.locator("#p1 .ux-body-hit").count(), 0)
                page.locator("[data-ux=find-next]").tap()
                self.assertEqual(page.locator("#ux-body-count").inner_text(), "2/2 · 2쪽")
                page.locator("#ux-read").tap()
                page.wait_for_function("document.querySelectorAll('#ux-reading section').length===3")
                self.assertIn("thermal", page.locator("#ux-reading-page-2").inner_text())
                self.assertIn("추출 가능한 텍스트가 없습니다", page.locator("#ux-reading-page-3").inner_text())
                self.assertEqual(page.locator("#ux-reading .ux-reading-hit").count(), 1)
                self.assertEqual(page.locator("#ux-reading").evaluate("e=>getComputedStyle(e).userSelect"), "text")
                page.locator("[data-ux=find-close]").tap()
                page.locator("#ux-read").tap()
                settle(page)
                self.assertFalse(page.locator("#doc").is_hidden())
                print("NATIVE_POC_COARSE " + json.dumps({"scenario": name, "current": baseline, "proposal": observed}))
                current.context.close()
                page.context.close()

    def select_note(self, page, touch=False):
        """Use actual native PDF selection gestures to open its shared note composer."""
        page.evaluate("goPage('1')")
        settle(page)
        box = page.locator("#p1").bounding_box()
        assert box is not None
        if touch:
            page.locator("#btn-select").tap()
            page.locator("#p1").tap(position={"x": box["width"] * 0.23, "y": box["height"] * 0.29})
        else:
            page.mouse.move(box["x"] + box["width"] * 0.09, box["y"] + box["height"] * 0.27)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] * 0.42, box["y"] + box["height"] * 0.32, steps=4)
            page.mouse.up()
        page.wait_for_function("COMPOSE.current&&!document.querySelector('#composer').hidden")
        settle(page)

    def test_desktop_inline_autocomplete_handoff_ambiguity_and_saved_card(self):
        """Popover/panel share exact selected login hints, and native cards expose candidate assignee/FYI."""
        page = self.open_preview(1440, 900)
        self.select_note(page)
        note = page.locator("#sel-pop textarea")
        self.assertTrue(note.is_visible())
        note.fill("Please check @Ro")
        page.locator('#mention-pop button:has-text("robin.two@example.com")').click()
        self.assertEqual(page.locator("#note").input_value(), "Please check @Robin Lee ")
        self.assertEqual(page.locator("#note").evaluate("e=>Array.from(e._mentions)"), ["robin.two@example.com"])
        self.assertIn("담당 Robin Lee", page.locator("#sel-pop .m-preview").inner_text())
        page.locator("[data-act=pop-more]").click()
        page.locator("#note").fill("Please check @Robin Lee and @동료 ")
        self.assertIn("참고 동료", page.locator("#note-mentions").inner_text())
        page.locator("#btn-save").click()
        page.wait_for_function("PINS.some(p=>p.id===21)")
        saved = page.evaluate("window.LimnDemo.snapshotPins().find(p=>p.id===21)")
        self.assertEqual(saved["assignee"], "robin.two@example.com")
        self.assertEqual(saved["mentions"], ["robin.two@example.com", "demo-colleague@example.com"])
        self.assertIn("Robin Lee", page.locator('.pin[data-id="21"] .card-meta').inner_text())
        page.reload()
        page.wait_for_function("META&&LIGHT_TIMER!==null")
        self.select_note(page)
        page.locator("#sel-pop textarea").fill("Please check @Robin Lee ")
        page.locator("#sel-pop textarea").press("Tab")
        self.assertEqual(page.evaluate("ASSIGN_NEW.v"), "agent")
        page.locator("#note").fill("Please check @동료 ")
        self.assertEqual(page.evaluate("ASSIGN_NEW.v"), "demo-colleague@example.com")
        page.locator("#note").fill("Please check")
        self.assertEqual(page.evaluate("ASSIGN_NEW.v"), "agent")
        page.locator("#note").fill("@Alice Please check")
        self.assertEqual(page.evaluate("ASSIGN_NEW.v"), "agent")

    def test_coarse_assignment_draft_survives_reading_and_document_return(self):
        """A touch tablet keeps the selected colleague and note through reading and native document drafts."""
        page = self.open_preview(717, 960, touch=True)
        self.select_note(page, touch=True)
        page.locator("#note").fill("Please check @Ro")
        page.locator('#mention-pop button:has-text("robin.one@example.com")').tap()
        page.locator("#ux-read").tap()
        page.wait_for_function("document.querySelectorAll('#ux-reading section').length===3")
        page.locator("#ux-read").tap()
        self.assertEqual(page.locator("#note").input_value(), "Please check @Robin Lee ")
        self.assertEqual(page.locator("#note").evaluate("e=>Array.from(e._mentions)"), ["robin.one@example.com"])
        self.assertEqual(page.evaluate("ASSIGN_NEW.v"), "robin.one@example.com")
        page.evaluate("switchDoc('supplement')")
        page.wait_for_function("DOC==='supplement'&&META.doc==='supplement'")
        page.evaluate("switchDoc('main')")
        page.wait_for_function("DOC==='main'&&META.doc==='main'&&COMPOSE.current")
        self.assertEqual(page.locator("#note").input_value(), "Please check @Robin Lee ")
        self.assertEqual(page.locator("#note").evaluate("e=>Array.from(e._mentions)"), ["robin.one@example.com"])
