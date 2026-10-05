"""GET paths and replies for the viewer shell and bundled browser assets."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from limn.viewer.assemble import ServedViewer, VendorLibrary
from limn.viewer.mark import ICON_ROUTES
from limn.web.errors import HTTPError
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest


@dataclass(frozen=True)
class VendorServing:
    """How GET /vendor/<library>/<file> answers one bundled library: the media type of each file suffix it serves - the
    leaf-name validator (app.vendor_file) admits no other suffix - and the Cache-Control of a 200."""

    media: Mapping[str, str]
    cache: str


# PDF.js caches for a day: --pdfjs-dir can put other files under the same ?v=. Pretendard comes only from the package,
# and every URL the page and its stylesheet name carries the font's version (?v=), so a copy never needs revalidating
# (docs/handbook/api.md §화면·PDF·정적 파일).
VENDOR: Mapping[VendorLibrary, VendorServing] = {
    "pdfjs": VendorServing({".mjs": "text/javascript; charset=utf-8"}, "public, max-age=86400"),
    "pretendard": VendorServing(
        {".woff2": "font/woff2", ".css": "text/css; charset=utf-8"}, "public, max-age=31536000, immutable"
    ),
}


class ViewerShellApp(Protocol):
    """Run-specific values needed to serve the viewer shell."""

    APP_NAME: str

    def viewer(self) -> ServedViewer:
        """Return the page, service worker and icons (by GET path) bound to this run."""
        ...

    def app_version(self) -> str:
        """Return the installed application version."""
        ...

    def vendor_file(self, library: VendorLibrary, name: str, suffixes: Collection[str]) -> Path | None:
        """Validate and locate one file of a bundled library: one leaf name ending in one of suffixes, or None."""
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


def _vendor(app: ViewerShellApp, library: VendorLibrary, path: str, name: str) -> Reply:
    """The bundled file `name` of library as its bytes, media type and cache (VENDOR); a 404 not_found for any name the
    validator refuses - a subpath, traversal, an encoded character, a suffix the library does not serve - or a file
    that cannot be read."""
    served = VENDOR[library]
    vf = app.vendor_file(library, name, served.media.keys())
    data = None if vf is None else _read(vf)
    if vf is not None and data is not None:
        return Reply(200, data, served.media[vf.suffix], served.cache)
    raise HTTPError(404, "없는 vendor 파일입니다: %s" % app.hdr_text(path)[:100], reason="not_found")


def get(request: GetRequest, app: ViewerShellApp) -> Reply | None:
    """Serve the viewer shell, its icons, version, worker, or a bundled PDF.js or Pretendard file (_vendor); None for a
    path that is not one of them.

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
        return _vendor(app, "pdfjs", path, path[len("/vendor/pdfjs/") :])
    if path.startswith("/vendor/pretendard/"):
        return _vendor(app, "pretendard", path, path[len("/vendor/pretendard/") :])
    return None
