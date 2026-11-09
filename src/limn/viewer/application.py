"""Viewer route assembly."""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path

from limn.platform.files import vendor_file as find_vendor_file
from limn.runtime.config import RunConfig
from limn.runtime.startup import APP_NAME, app_version
from limn.security.access import hdr_text
from limn.viewer.assemble import (
    ServedViewer,
    VendorLibrary,
    default_katex_dir,
    default_markdown_it_dir,
    default_pdfjs_dir,
    default_pretendard_dir,
)
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

    def vendor_file(self, library: VendorLibrary, name: str, suffixes: Collection[str]) -> Path | None:
        """The file `name` of a bundled library's directory, or None: one leaf name ending in one of suffixes, inside
        the directory (limn.platform.files.vendor_file). PDF.js is read from the run's --pdfjs-dir when given, else the
        package's; markdown-it, KaTeX and Pretendard always from the package (the parser the Markdown surface is tested
        with, the renderer its math is drawn by, the build the viewer is measured in)."""
        match library:
            case "pdfjs":
                directory = self.settings().pdfjs_dir or default_pdfjs_dir()
            case "markdown-it":
                directory = default_markdown_it_dir()
            case "katex":
                directory = default_katex_dir()
            case "pretendard":
                directory = default_pretendard_dir()
        return find_vendor_file(directory, name, suffixes)


def assemble_viewer(settings: Callable[[], RunConfig], viewer: Callable[[], ServedViewer]) -> ViewerSubsystem:
    """Bind viewer shell and asset reads to one run."""
    from limn.viewer.routes import get

    shell = ViewerShell(settings, viewer)
    return ViewerSubsystem(RouteBundle(get=(lambda request: get(request, shell),)))
