"""Names and switches accepted by build read routes."""

import os
import re
from typing import NamedTuple

from limn.builds.artifacts import valid_build_name
from limn.web.parse import Query, parse_flag, query_first

# The page image names a completed build writes. A path can contain extra components, as the existing route did.
PAGE_FILE_RE = re.compile(r"page-\d+\.png")


class PagePath(NamedTuple):
    """The page image a /pages/ path asks for: the build that holds it (None: the build on screen) and its name."""

    build: str | None
    name: str


def page_name(path: str) -> str | None:
    """A servable page image basename, or None for a path that falls through the route."""
    name = os.path.basename(path)
    return name if PAGE_FILE_RE.fullmatch(name) else None


def page_path(path: str) -> PagePath | None:
    """/pages/<build>/<page> names the build (a page directory name, valid_build_name); /pages/<page> and every other
    shape - the old route's - is the build on screen with the path's basename. None when the basename is not a page
    image name, so the path falls through the route."""
    name = page_name(path)
    if name is None:
        return None
    parts = path.split("/")
    if len(parts) == 4 and parts[1] == "pages" and valid_build_name(parts[2]):
        return PagePath(parts[2], name)
    return PagePath(None, name)


def parse_build_name(q: Query) -> str:
    """GET /pdf's ?build= as sent, or "" for the build on screen. An unknown name is answered as a missing PDF."""
    return query_first(q, "build", "") or ""


class RebuildQuery(NamedTuple):
    """POST /api/rebuild switches: full response log, background execution, and a forced cold build (no skip)."""

    full_log: bool
    background: bool
    force: bool = False


def parse_rebuild_query(q: Query) -> RebuildQuery:
    """Parse ?log=1, ?async=1 and ?force=1 with the shared exact-value switch rule."""
    return RebuildQuery(parse_flag(q, "log"), parse_flag(q, "async"), parse_flag(q, "force"))
