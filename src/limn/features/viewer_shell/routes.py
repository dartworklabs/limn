"""GET paths and replies for the viewer shell and bundled browser assets."""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from limn.config import RunConfig
from limn.mark import png as mark_png
from limn.viewer.assemble import ServedViewer
from limn.web.errors import HTTPError
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest

# The vendor file validator admits only .mjs.
VENDOR_MIME: Mapping[str, str] = {".mjs": "text/javascript; charset=utf-8"}


class ViewerShellApp(Protocol):
    """Run-specific values needed to serve the viewer shell."""

    C: RunConfig
    APP_NAME: str

    def viewer(self) -> ServedViewer:
        """Return the page and service worker bound to this run."""
        ...

    def app_version(self) -> str:
        """Return the installed application version."""
        ...

    def vendor_file(self, name: str) -> Path | None:
        """Validate and locate one bundled PDF.js file."""
        ...

    def hdr_text(self, value: object) -> str:
        """Render a path safely for an HTTP refusal."""
        ...


def _read(path: Path) -> bytes | None:
    """Read a served file or return None when it is unavailable."""
    try:
        return path.read_bytes()
    except OSError:
        return None


def get(request: GetRequest, app: ViewerShellApp) -> Reply | None:
    """Serve the viewer shell, icon fallbacks, version, worker, or PDF.js file."""
    path = request.path
    if path == "/":
        request.record_person()
        return Reply(200, app.viewer().page.encode(), "text/html; charset=utf-8")
    if path == "/favicon.ico":
        return Reply(204, b"", "image/x-icon")
    if path in ("/favicon-32.png", "/apple-touch-icon.png"):
        size, rounded = (32, True) if path == "/favicon-32.png" else (180, False)
        return Reply(200, mark_png(size, app.C.accent, rounded), "image/png", "public, max-age=86400")
    if path == "/api/version":
        return json_reply({"name": app.APP_NAME, "version": app.app_version()})
    if path == "/sw.js":
        return Reply(200, app.viewer().service_worker.encode(), "text/javascript; charset=utf-8", "no-cache")
    if path.startswith("/vendor/pdfjs/"):
        # The validator rejects subpaths, traversal and encoded characters.
        vf = app.vendor_file(path[len("/vendor/pdfjs/") :])
        data = None if vf is None else _read(vf)
        if vf is not None and data is not None:
            return Reply(200, data, VENDOR_MIME[vf.suffix], "public, max-age=86400")
        raise HTTPError(404, "없는 vendor 파일입니다: %s" % app.hdr_text(path)[:100], reason="not_found")
    return None
