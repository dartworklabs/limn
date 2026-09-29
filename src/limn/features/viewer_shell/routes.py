"""GET paths and replies for the viewer shell and bundled browser assets."""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from limn.mark import ICON_ROUTES
from limn.viewer.assemble import ServedViewer
from limn.web.errors import HTTPError
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest

# The vendor file validator admits only .mjs.
VENDOR_MIME: Mapping[str, str] = {".mjs": "text/javascript; charset=utf-8"}


class ViewerShellApp(Protocol):
    """Run-specific values needed to serve the viewer shell."""

    APP_NAME: str

    def viewer(self) -> ServedViewer:
        """Return the page, service worker and icons (by GET path) bound to this run."""
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
    """Serve the viewer shell, its icons, version, worker, or PDF.js file; None for a path that is not one of them.

    An ICON_ROUTES path answers the run's vendored icon file unchanged, publicly cacheable for a day. The page's links
    carry a content key (?v=), so a new drawing gets a new URL there; only those linked URLs are busted - the bare
    /favicon.ico and /apple-touch-icon.png a browser or iOS asks for on its own can stay cached for up to a day. A run
    whose viewer holds no icon for the path answers 404."""
    path = request.path
    if path == "/":
        request.record_person()
        return Reply(200, app.viewer().page.encode(), "text/html; charset=utf-8")
    if path in ICON_ROUTES:
        icon = app.viewer().icons.get(path)
        if icon is None:
            raise HTTPError(404, "없는 아이콘입니다: %s" % app.hdr_text(path)[:100], reason="not_found")
        return Reply(200, icon.body, icon.content_type, "public, max-age=86400")
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
