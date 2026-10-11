"""Provide one verified, page-scoped font for the wide-Hangul browser regressions.

Only explicit font-sensitive fixtures call this module. The public upstream font
is cached outside the checkout; no font is installed or registered with the OS.
"""

import fcntl
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route

FONT_FAMILY = "Noto Sans CJK KR"
FONT_COMMIT = "f8d157532fbfaeda587e826d4cd5b21a49186f7c"
FONT_URL = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/" + FONT_COMMIT + "/Sans/OTF/Korean/NotoSansCJKkr-Regular.otf"
)
FONT_SHA256 = "6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a"
FONT_BYTES = 16_433_112
FONT_ROUTE = "/__limn-test-font.otf"
DOWNLOAD_SECONDS = 60
SOCKET_SECONDS = 15


@dataclass(frozen=True)
class VerifiedTestFont:
    """Carry immutable verified bytes so the browser never reopens a cache path."""

    data: bytes

    def __post_init__(self) -> None:
        """Reject construction from bytes other than the pinned official artifact."""
        if error := font_integrity_error(self.data):
            raise ValueError(error)


@dataclass(frozen=True)
class FontProvisionFailure:
    """Explain an actionable prerequisite failure without admitting invalid bytes."""

    message: str


def font_integrity_error(data: bytes) -> str | None:
    """Return the violated size/digest constraint, or accept exactly the pinned bytes."""
    if len(data) != FONT_BYTES:
        return "font byte count %d differs from pinned %d" % (len(data), FONT_BYTES)
    digest = hashlib.sha256(data).hexdigest()
    if digest != FONT_SHA256:
        return "font SHA-256 %s differs from pinned %s" % (digest, FONT_SHA256)
    return None


def font_cache_dir() -> Path:
    """Choose an external test cache, allowing isolated CI/diagnostic cache roots."""
    if override := os.environ.get("LIMN_TEST_FONT_CACHE"):
        return Path(override)
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return root / "limn" / "browser-test-font"


class _NoFontRedirect(urllib.request.HTTPRedirectHandler):
    """Keep the only network destination at the approved fixed HTTPS URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Reject redirects rather than forwarding the download to another target."""
        return None


def _download_font() -> bytes | FontProvisionFailure:
    """Fetch bounded bytes with no redirects, socket inactivity and body-read deadlines.

    The 60s body deadline starts after opening the response; the socket timeout
    also applies while connecting/reading headers. This is not a hard total wall
    clock deadline because socket progress can extend the connection/header step.
    """
    opener = urllib.request.build_opener(_NoFontRedirect())
    try:
        with opener.open(FONT_URL, timeout=SOCKET_SECONDS) as response:
            if response.geturl() != FONT_URL:
                return FontProvisionFailure("font source redirected away from the pinned URL")
            deadline = time.monotonic() + DOWNLOAD_SECONDS
            data = bytearray()
            while len(data) <= FONT_BYTES:
                if time.monotonic() > deadline:
                    return FontProvisionFailure("font body download exceeded %ds" % DOWNLOAD_SECONDS)
                # read1 performs at most one buffered/socket read, so the total
                # deadline is checked even when the peer sends a slow stream.
                chunk = response.read1(min(64 * 1024, FONT_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            return bytes(data)
    except (OSError, urllib.error.URLError) as error:
        return FontProvisionFailure("font download failed: %s" % error)


def _read_cached_font(path: Path) -> bytes | None:
    """Read a bounded regular file without following symlinks; absent/invalid is a miss."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return None
            data = stream.read(FONT_BYTES + 1)
    except OSError:
        return None
    return data if font_integrity_error(data) is None else None


def provision_test_font(cache_dir: Path | None = None) -> VerifiedTestFont | FontProvisionFailure:
    """Reuse verified cache bytes or download/publish atomically under a per-font lock.

    Parallel pytest workers share the lock and recheck after acquiring it. Failed
    downloads leave the prior entry untouched and never provide fallback bytes.
    A verified cache hit needs no network. Returned failures name both source and
    cache so normal pytest failures explain how to repair a cold/offline machine.
    """
    directory = cache_dir if cache_dir is not None else font_cache_dir()
    path = directory / (FONT_SHA256 + ".otf")
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(directory / (FONT_SHA256 + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a+b") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                return FontProvisionFailure("font cache lock is not a regular file: %s" % directory)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (data := _read_cached_font(path)) is not None:
                return VerifiedTestFont(data)
            downloaded = _download_font()
            if isinstance(downloaded, FontProvisionFailure):
                return FontProvisionFailure("%s; source=%s; cache=%s" % (downloaded.message, FONT_URL, path))
            if error := font_integrity_error(downloaded):
                return FontProvisionFailure("%s; source=%s; cache=%s" % (error, FONT_URL, path))
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, prefix=".font-", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(downloaded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return VerifiedTestFont(downloaded)
    except OSError as error:
        return FontProvisionFailure("font cache failed: %s; source=%s; cache=%s" % (error, FONT_URL, path))


def prepare_font_document(html: str) -> str:
    """Defer the final classic viewer script intact until the page's FontFace loads.

    Appending a classic script retains its original global bindings. The document
    and original init scripts still establish styles/preferences before boot;
    only an explicitly provisioned test document takes this preparation path.
    """
    opening = html.rfind("<script>")
    closing = html.rfind("</script>")
    if opening < 0 or closing < opening:
        raise ValueError("font fixture requires a final inline classic viewer script")
    source = html[opening + len("<script>") : closing]
    literal = json.dumps(source).replace("</", "<\\/")
    loader = """<script>
window.__limnTestFontReady = (async () => {
  try {
    const face = new FontFace(%s, %s);
    await face.load(); document.fonts.add(face);
    if (document.readyState === 'loading')
      await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve, {once: true}));
    window.__limnTestFontBeforeViewer = face.status === 'loaded' && document.fonts.has(face);
    const script = document.createElement('script'); script.textContent = %s;
    document.body.appendChild(script);
    return null;
  } catch (error) { return String(error); }
})();
</script>""" % (json.dumps(FONT_FAMILY), json.dumps('url("%s")' % FONT_ROUTE), literal)
    return html[:opening] + loader + html[closing + len("</script>") :]


class _FontDocumentRoute:
    """Prepare the existing handler's HTML response without changing other routes."""

    def __init__(self, route: "Route") -> None:
        """Keep the real route/request for the existing in-process viewer handler."""
        self.route = route
        self.request = route.request

    def fulfill(self, *, status: int, headers: dict[str, str], body: bytes) -> None:
        """Transform only successful HTML, preserving all other response bytes."""
        if status == 200 and headers.get("content-type", "").startswith("text/html"):
            body = prepare_font_document(body.decode("utf-8")).encode("utf-8")
        self.route.fulfill(status=status, headers=headers, body=body)

    def abort(self) -> None:
        """Preserve the fixture's refusal of requests outside its allowed origin."""
        self.route.abort()


def install_test_font(page: "Page", font: VerifiedTestFont, viewer_route: Callable[..., object]) -> None:
    """Serve verified bytes only to this page and prepare its root viewer response."""

    def route_request(route: "Route") -> None:
        """Deliver the fixed font or delegate to the fixture's unchanged handler."""
        url = urlparse(route.request.url)
        if url.netloc == "viewer.test" and url.path == FONT_ROUTE:
            route.fulfill(status=200, content_type="font/otf", body=font.data)
        elif url.netloc == "viewer.test" and url.path == "/" and route.request.resource_type == "document":
            viewer_route(_FontDocumentRoute(route))
        else:
            viewer_route(route)

    page.route("**/*", route_request)


def use_test_font(page: "Page", viewer_route: Callable[..., object]) -> None:
    """Provision the requested face or fail the test with the actionable failure."""
    font = provision_test_font()
    if isinstance(font, FontProvisionFailure):
        raise AssertionError(font.message)
    install_test_font(page, font, viewer_route)


def wait_test_font(page: "Page") -> None:
    """Require successful page loading before the fixture waits for viewer boot."""
    error = page.evaluate("window.__limnTestFontReady")
    if error is not None:
        raise AssertionError("page-scoped test font failed to load: %s" % error)
    if not page.evaluate("window.__limnTestFontBeforeViewer === true"):
        raise AssertionError("page-scoped test font was not loaded before the viewer script")
