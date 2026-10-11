"""Pin verified font provision, cache failures, and actual page-scoped preboot glyphs."""

import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import helpers_browser_font as fonts
from helpers_browser import BrowserBase, booted, drawn_faces, settle


def cache_path(directory: Path) -> Path:
    """Locate the public artifact by its content identity in an isolated real cache."""
    return directory / (fonts.FONT_SHA256 + ".otf")


def test_failed_cold_download_reports_source_and_cache_without_publishing(tmp_path, monkeypatch):
    """An offline cold cache is an actionable failure, never a skip or partial font."""
    monkeypatch.setattr(fonts, "_download_font", lambda: fonts.FontProvisionFailure("offline fixture"))
    result = fonts.provision_test_font(tmp_path)
    assert isinstance(result, fonts.FontProvisionFailure)
    assert "offline fixture" in result.message
    assert fonts.FONT_URL in result.message
    assert str(cache_path(tmp_path)) in result.message
    assert not cache_path(tmp_path).exists()
    assert not list(tmp_path.glob(".font-*"))


@pytest.mark.parametrize("payload", [b"", b"OTTO", b"OTTO" + b"x" * fonts.FONT_BYTES])
def test_download_size_mismatch_cannot_be_published(tmp_path, monkeypatch, payload):
    """Empty, truncated, and oversized source bytes cannot become a usable cache entry."""
    monkeypatch.setattr(fonts, "_download_font", lambda: payload)
    result = fonts.provision_test_font(tmp_path)
    assert isinstance(result, fonts.FontProvisionFailure)
    assert "byte count" in result.message
    assert not cache_path(tmp_path).exists()


def test_same_size_wrong_digest_cannot_be_published(tmp_path, monkeypatch):
    """Matching the expected byte count grants no trust without the exact SHA-256."""
    monkeypatch.setattr(fonts, "_download_font", lambda: b"x" * fonts.FONT_BYTES)
    result = fonts.provision_test_font(tmp_path)
    assert isinstance(result, fonts.FontProvisionFailure)
    assert "SHA-256" in result.message
    assert not cache_path(tmp_path).exists()


def test_corrupt_cache_and_offline_source_cannot_supply_fallback_bytes(tmp_path, monkeypatch):
    """A failed repair retains diagnostic corrupt bytes but never returns them to the browser."""
    path = cache_path(tmp_path)
    path.write_bytes(b"corrupt existing cache")
    monkeypatch.setattr(fonts, "_download_font", lambda: fonts.FontProvisionFailure("offline fixture"))
    result = fonts.provision_test_font(tmp_path)
    assert isinstance(result, fonts.FontProvisionFailure)
    assert "offline fixture" in result.message
    assert path.read_bytes() == b"corrupt existing cache"


def test_cache_symlink_cannot_admit_or_modify_another_file(tmp_path, monkeypatch):
    """An untrusted cache symlink is not an artifact and an offline miss leaves its target intact."""
    target = tmp_path / "outside.otf"
    target.write_bytes(b"not an authorized artifact")
    cache_path(tmp_path).symlink_to(target)
    monkeypatch.setattr(fonts, "_download_font", lambda: fonts.FontProvisionFailure("offline fixture"))
    result = fonts.provision_test_font(tmp_path)
    assert isinstance(result, fonts.FontProvisionFailure)
    assert target.read_bytes() == b"not an authorized artifact"


def test_checked_in_provenance_matches_the_fixed_download_contract():
    """The reviewable source/license manifest travels with the exact download identity."""
    directory = Path(__file__).parent / "fixtures" / "browser-font"
    source = json.loads((directory / "SOURCE.json").read_text())
    assert source["url"] == fonts.FONT_URL
    assert source["commit"] == fonts.FONT_COMMIT
    assert source["sha256"] == fonts.FONT_SHA256
    assert source["bytes"] == fonts.FONT_BYTES
    assert source["license"] == "SIL OFL 1.1"
    assert hashlib.sha256((directory / "LICENSE").read_bytes()).hexdigest() == source["license_sha256"]


class FontSourceResponse(io.BytesIO):
    """An unmanaged HTTP response substitute used only inside the download adapter's tests."""

    def __init__(self, data: bytes, url: str = fonts.FONT_URL):
        """Expose source bytes and the final URL without using a managed-cache fake."""
        super().__init__(data)
        self.url = url

    def geturl(self) -> str:
        """Expose the destination the adapter must compare with its fixed source."""
        return self.url


def source_response(monkeypatch, response: FontSourceResponse) -> list[tuple]:
    """Replace HTTP only at its owned adapter boundary and record the requested target/bound."""
    requests = []

    class SourceOpener:
        """Own the fake unmanaged connection, leaving the cache and browser real."""

        def open(self, url, *, timeout):
            """Return the source response and expose the adapter's public network request."""
            requests.append((url, timeout))
            return response

    monkeypatch.setattr(fonts.urllib.request, "build_opener", lambda *_handlers: SourceOpener())
    return requests


def test_download_stops_after_the_maximum_artifact_bytes(monkeypatch):
    """An oversized HTTP stream yields at most the pinned size plus one rejection byte."""
    requests = source_response(monkeypatch, FontSourceResponse(b"x" * (fonts.FONT_BYTES + 17)))
    result = fonts._download_font()
    assert isinstance(result, bytes)
    assert len(result) == fonts.FONT_BYTES + 1
    assert requests == [(fonts.FONT_URL, fonts.SOCKET_SECONDS)]


def test_download_rejects_a_changed_final_source_url(monkeypatch):
    """Even a supplied successful response cannot move the fixed target through a redirect."""
    source_response(monkeypatch, FontSourceResponse(b"", "https://example.com/font.otf"))
    result = fonts._download_font()
    assert isinstance(result, fonts.FontProvisionFailure)
    assert "redirected" in result.message


def test_download_deadline_fails_without_reading_an_unbounded_stream(monkeypatch):
    """The body deadline rejects a slow stream independently of socket progress."""
    source_response(monkeypatch, FontSourceResponse(b"unbounded source fixture"))
    times = iter((0, fonts.DOWNLOAD_SECONDS + 1))
    monkeypatch.setattr(fonts.time, "monotonic", lambda: next(times))
    result = fonts._download_font()
    assert isinstance(result, fonts.FontProvisionFailure)
    assert "exceeded" in result.message


def test_http_redirect_cannot_contact_a_second_destination(monkeypatch):
    """The real HTTP adapter rejects redirects before any follow-up request is sent."""
    requests = []

    class RedirectSource(BaseHTTPRequestHandler):
        """Supply an unmanaged upstream redirect through a real loopback HTTP server."""

        def do_GET(self):
            """Record the request and ask the client to leave the fixed source path."""
            requests.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/unapproved-font.otf")
            self.end_headers()

        def log_message(self, *args):
            """Keep the source fixture's access payload out of the test's diagnostic output."""

    server = HTTPServer(("127.0.0.1", 0), RedirectSource)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    try:
        monkeypatch.setattr(fonts, "FONT_URL", "http://127.0.0.1:%d/font.otf" % server.server_port)
        result = fonts._download_font()
        assert isinstance(result, fonts.FontProvisionFailure)
        assert "302" in result.message
        assert requests == ["/font.otf"]
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
    assert not worker.is_alive()


@pytest.fixture(scope="module")
def canonical_font():
    """Acquire the real pinned font only for browser-marked integration tests."""
    result = fonts.provision_test_font()
    assert isinstance(result, fonts.VerifiedTestFont), result
    return result


@pytest.mark.browser
def test_cold_cache_publishes_verified_source_bytes(tmp_path, monkeypatch, canonical_font):
    """A cold cache publishes verified official bytes without requiring a new warm/offline fetch."""
    monkeypatch.setattr(fonts, "_download_font", lambda: canonical_font.data)
    result = fonts.provision_test_font(tmp_path)
    assert isinstance(result, fonts.VerifiedTestFont), result
    assert len(result.data) == fonts.FONT_BYTES
    assert hashlib.sha256(result.data).hexdigest() == fonts.FONT_SHA256
    assert cache_path(tmp_path).is_file()
    assert cache_path(tmp_path).read_bytes() == result.data
    assert not list(tmp_path.glob(".font-*"))


@pytest.mark.browser
def test_verified_warm_cache_works_offline(tmp_path, monkeypatch, canonical_font):
    """A verified existing artifact remains usable when the upstream is unavailable."""
    cache_path(tmp_path).write_bytes(canonical_font.data)
    monkeypatch.setattr(fonts, "_download_font", lambda: fonts.FontProvisionFailure("offline fixture"))
    result = fonts.provision_test_font(tmp_path)
    assert isinstance(result, fonts.VerifiedTestFont), result
    assert result.data == canonical_font.data


@pytest.mark.browser
def test_corrupt_cache_is_replaced_by_verified_source_bytes(tmp_path, monkeypatch, canonical_font):
    """A same-size corrupt artifact is atomically repaired rather than reused."""
    corrupted = bytearray(canonical_font.data)
    corrupted[-1] ^= 1
    cache_path(tmp_path).write_bytes(corrupted)
    monkeypatch.setattr(fonts, "_download_font", lambda: canonical_font.data)
    result = fonts.provision_test_font(tmp_path)
    assert isinstance(result, fonts.VerifiedTestFont), result
    assert result.data == canonical_font.data
    assert cache_path(tmp_path).read_bytes() == canonical_font.data
    assert not list(tmp_path.glob(".font-*"))


@pytest.mark.browser
def test_simultaneous_cold_readers_receive_one_complete_artifact(tmp_path, monkeypatch, canonical_font):
    """Four concurrent misses coalesce one source fetch and each receives complete verified bytes."""
    calls = []
    start = threading.Barrier(5)

    def download():
        """Substitute the owned upstream adapter while keeping cache files and locks real."""
        calls.append("source download")
        return canonical_font.data

    def read():
        """Enter the cold cache concurrently with the other three readers."""
        start.wait(timeout=10)
        return fonts.provision_test_font(tmp_path)

    monkeypatch.setattr(fonts, "_download_font", download)
    with ThreadPoolExecutor(max_workers=4) as workers:
        pending = [workers.submit(read) for _ in range(4)]
        start.wait(timeout=10)
        results = [future.result(timeout=30) for future in pending]
    assert all(isinstance(result, fonts.VerifiedTestFont) for result in results), results
    assert all(result.data == canonical_font.data for result in results)
    assert calls == ["source download"]
    assert cache_path(tmp_path).read_bytes() == canonical_font.data
    assert not list(tmp_path.glob(".font-*"))


class BrowserFontProvision(BrowserBase):
    """Observe actual loaded webfont glyphs, intact globals, and fresh-context isolation."""

    def test_the_font_is_available_before_viewer_boot_and_does_not_leak_to_a_fresh_context(self):
        """The first boot request sees loaded Noto; native pages cannot inherit the custom face."""
        init = """(() => {const fetch0 = window.fetch;
          window.fetch = (...args) => {
            if (String(args[0]).startsWith('/api/meta') && window.__fontAtFirstBoot === undefined)
              window.__fontAtFirstBoot = [...document.fonts].some(f => f.family.replaceAll('"', '') === 'Noto Sans CJK KR' && f.status === 'loaded');
            return fetch0(...args);
          };})();"""
        page = self.open(0, init=init, test_font=True)
        assert page.evaluate("window.__fontAtFirstBoot === true")
        assert page.evaluate("window.__limnTestFontBeforeViewer === true")
        assert page.evaluate("typeof boot === 'function' && typeof OPEN_ALL !== 'undefined'")
        page.evaluate("document.body.style.fontFamily = '\"Noto Sans CJK KR\"'")
        assert drawn_faces(page, "body", "본문핀검토선택") == {fonts.FONT_FAMILY}
        custom = self.custom_faces(page)
        assert custom and all(font["isCustomFont"] and font["glyphCount"] > 0 for font in custom), custom
        sibling = page.context.new_page()
        sibling_errors = []
        sibling.on("pageerror", lambda error: sibling_errors.append(str(error)))
        sibling.route("**/*", self.route)
        sibling.goto("http://viewer.test/?lang=ko")
        sibling.wait_for_function(booted(0), timeout=20000)
        settle(sibling)
        for native in (sibling, self.open(0)):
            assert native.evaluate(
                "![...document.fonts].some(f => f.family.replaceAll('\"', '') === 'Noto Sans CJK KR')"
            )
            glyphs = self.custom_faces(native)
            assert glyphs and all(font["glyphCount"] > 0 for font in glyphs), glyphs
            assert all(not font["isCustomFont"] for font in glyphs), glyphs
        assert sibling_errors == []

    def custom_faces(self, page) -> list[dict]:
        """Paint the Hangul probe, then read Chromium's actual shaping/custom-font record."""
        page.evaluate("""() => {const span = document.createElement('span'); span.id = 'font-custom-probe';
          span.textContent = '본문핀검토선택'; span.style.cssText = 'position:fixed;left:0;top:0;font-family:"Noto Sans CJK KR"'; document.body.append(span);
          return span.getBoundingClientRect().width;}""")
        page.locator("#font-custom-probe").screenshot()
        session = page.context.new_cdp_session(page)
        session.send("DOM.enable")
        session.send("CSS.enable")
        root = session.send("DOM.getDocument")["root"]["nodeId"]
        node = session.send("DOM.querySelector", {"nodeId": root, "selector": "#font-custom-probe"})["nodeId"]
        result = session.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
        page.evaluate("document.querySelector('#font-custom-probe').remove()")
        return result

    def test_the_deferred_classic_script_keeps_globals_and_executes_once_after_loading(self):
        """Script preparation keeps original global bindings and runs exactly once with the loaded face."""
        font = fonts.provision_test_font()
        assert isinstance(font, fonts.VerifiedTestFont), font
        context = self.browser.new_context()
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        source = """let retainedGlobal = 23; function boot() {
          window.bootCount = (window.bootCount || 0) + 1;
          window.fontAtBoot = [...document.fonts].some(f => f.family.replaceAll('"', '') === 'Noto Sans CJK KR' && f.status === 'loaded');
        } boot();"""
        html = "<html><body><script>" + source + "</script></body></html>"

        def viewer(route):
            """Serve a real classic-script document through the same preparation adapter."""
            route.fulfill(status=200, headers={"content-type": "text/html"}, body=html.encode())

        fonts.install_test_font(page, font, viewer)
        page.goto("http://viewer.test/")
        fonts.wait_test_font(page)
        assert page.evaluate("retainedGlobal") == 23
        assert page.evaluate("window.bootCount") == 1
        assert page.evaluate("window.fontAtBoot") is True
        assert page.evaluate("[...document.scripts].filter(s => s.textContent === %s).length" % json.dumps(source)) == 1
        assert errors == []
