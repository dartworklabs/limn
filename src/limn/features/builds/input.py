"""Names and switches accepted by build read routes."""

import os
import re

from limn.web.parse import Query, query_first

# The page image names a completed build writes. A path can contain extra components, as the existing route did.
PAGE_FILE_RE = re.compile(r"page-\d+\.png")


def page_name(path: str) -> str | None:
    """A servable page image basename, or None for a path that falls through the route."""
    name = os.path.basename(path)
    return name if PAGE_FILE_RE.fullmatch(name) else None


def parse_build_name(q: Query) -> str:
    """GET /pdf's ?build= as sent, or "" for the build on screen. An unknown name is answered as a missing PDF."""
    return query_first(q, "build", "") or ""
