"""Viewer route assembly."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from limn.platform.files import vendor_file as find_vendor_file
from limn.runtime.config import RunConfig
from limn.runtime.startup import APP_NAME, app_version
from limn.security.access import hdr_text
from limn.viewer.assemble import ServedViewer
from limn.web.routes import RouteBundle


@dataclass(frozen=True)
class ViewerSubsystem:
    """The viewer's bound HTTP routes."""

    routes: RouteBundle


@dataclass(frozen=True)
class ViewerShell:
    """Run-specific viewer assets and package metadata used by shell routes."""

    settings: Callable[[], RunConfig]
    viewer: Callable[[], ServedViewer]
    APP_NAME = APP_NAME
    app_version = staticmethod(app_version)
    hdr_text = staticmethod(hdr_text)

    def vendor_file(self, name: str) -> Path | None:
        """Validate one PDF.js module name within the configured vendor directory."""
        directory = self.settings().pdfjs_dir or Path(__file__).resolve().parent.parent / "vendor" / "pdfjs"
        return find_vendor_file(directory, name)


def assemble_viewer(settings: Callable[[], RunConfig], viewer: Callable[[], ServedViewer]) -> ViewerSubsystem:
    """Bind viewer shell and asset reads to one run."""
    from limn.viewer.routes import get

    shell = ViewerShell(settings, viewer)
    return ViewerSubsystem(RouteBundle(get=(lambda request: get(request, shell),)))
