"""GET build status, PDF and page image answers after common request guards."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple, NoReturn

from limn.builds import answer, artifacts as build, input as build_input
from limn.builds.service import BuildRequests
from limn.runtime.documents import Doc
from limn.security.access import PostAuthority
from limn.web.errors import HTTPError
from limn.web.parse import Query, parse_flag


def status(doc: Doc, query: Query) -> dict[str, Any]:
    """The current build state, with the existing agent log diet unless ?log=1."""
    return answer.diet_log(build.state_snapshot(doc), parse_flag(query, "log"))


def rebuild(requests: BuildRequests, doc: Doc, query: Query, authority: PostAuthority) -> tuple[answer.Body, int]:
    """Build this source document now or in the background, and answer its outcome. ?force=1 builds cold and never
    answers unchanged."""
    switches = build_input.parse_rebuild_query(query)
    if switches.background:
        return answer.rebuild_started_answer(requests.rebuild_async(doc, authority, switches.force))
    return answer.rebuild_answer(requests.rebuild(doc, authority, switches.force), switches.full_log)


def _read(path: Path) -> bytes | None:
    """Read a build artifact, or return None if it has vanished since selection."""
    try:
        return path.read_bytes()
    except OSError:
        return None


# A URL that names a timestamped build always means the same bytes: a page folder is never written again once
# published, and its name is never given to another build (engine.render_pages). The legacy folder `pages` is not one.
IMMUTABLE_BUILD_RE = re.compile(r"pages-\d{14}(-\d+)?")
YEAR_CACHE = "private, max-age=31536000, immutable"
SHORT_CACHE = "private, max-age=600"


class BuildFile(NamedTuple):
    """One page image or PDF answer: its bytes, its Cache-Control and its ETag."""

    data: bytes
    cache: str
    etag: str


def _answer(path: Path, build_name: str, named: bool) -> BuildFile | None:
    """The file at path of page folder build_name, or None when it has vanished. A URL that named a timestamped build
    is cached for a year (immutable); any other - the build on screen, the legacy folder - for ten minutes. The ETag
    is the folder name with the file's mtime_ns and size, so the same bytes in two builds are two tags."""
    try:
        st = path.stat()
        data = path.read_bytes()
    except OSError:
        return None
    cache = YEAR_CACHE if named and IMMUTABLE_BUILD_RE.fullmatch(build_name) else SHORT_CACHE
    return BuildFile(data, cache, '"%s-%x-%x"' % (build_name, st.st_mtime_ns, st.st_size))


def page(doc: Doc, path: str, text: Callable[[object], str]) -> BuildFile | None:
    """A page image: of the build the path names (/pages/<build>/<page>), else of the build on screen. None for a name
    that is not a page image or a page the build does not have, so the handler can fall through to its unknown-path
    answer; a named build whose folder is gone is the pdf_build_gone 404."""
    asked = build_input.page_path(path)
    if asked is None:
        return None
    if asked.build is None:
        cur = build.cur_pages(doc)
        return _answer(cur / asked.name, cur.name, False)
    folder = doc.dir / asked.build
    if not folder.is_dir():
        build_gone(asked.build, build.cur_pages(doc).name, text, "쪽 이미지")
    return _answer(folder / asked.name, asked.build, True)


def pdf(doc: Doc, query: Query, text: Callable[[object], str]) -> BuildFile:
    """The PDF of the requested page build, or its contract 404 when absent or unreadable."""
    name = build_input.parse_build_name(query)
    path = build.build_pdf(doc, name)
    found = None if path is None else _answer(path, path.parent.name, bool(name))
    if found is None:
        pdf_gone(name, build.cur_pages(doc).name, text)
    return found


def build_gone(name: str, pages_build: str, text: Callable[[object], str], what: str) -> NoReturn:
    """404 pdf_build_gone for a page URL naming a build whose folder is gone, with the build on screen."""
    raise HTTPError(
        404,
        "그 빌드의 %s가 없습니다: %s" % (what, text(name)[:60]),
        pdf_build_gone=True,
        pages_build=pages_build,
        reason="pdf_build_gone",
    )


def pdf_gone(name: str, pages_build: str, text: Callable[[object], str]) -> NoReturn:
    """GET /pdf: 404 for a gone named build or for the missing PDF of the on-screen build."""
    raise HTTPError(
        404,
        "그 빌드의 PDF 가 없습니다: %s" % text(name)[:60],
        pdf_build_gone=bool(name),
        pages_build=pages_build,
        reason="pdf_build_gone" if name else "pdf_missing",
    )
