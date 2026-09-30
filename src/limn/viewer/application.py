"""Viewer route assembly."""

from dataclasses import dataclass

from limn.viewer.routes import ViewerShellApp
from limn.web.routes import RouteBundle


@dataclass(frozen=True)
class ViewerSubsystem:
    """The viewer's bound HTTP routes."""

    routes: RouteBundle


def assemble_viewer(app: ViewerShellApp) -> ViewerSubsystem:
    """Bind viewer shell and asset reads to one run."""
    from limn.viewer.routes import get

    return ViewerSubsystem(RouteBundle(get=(lambda request: get(request, app),)))
