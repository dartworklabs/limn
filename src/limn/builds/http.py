"""GET build status, PDF and page image answers after common request guards."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

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
    """Build this source document now or in the background, and answer its outcome."""
    switches = build_input.parse_rebuild_query(query)
    if switches.background:
        return answer.rebuild_started_answer(requests.rebuild_async(doc, authority))
    return answer.rebuild_answer(requests.rebuild(doc, authority), switches.full_log)


def _read(path: Path) -> bytes | None:
    """Read a build artifact, or return None if it has vanished since selection."""
    try:
        return path.read_bytes()
    except OSError:
        return None


def page(doc: Doc, path: str) -> bytes | None:
    """A page image on screen, or None so the handler can fall through to its unknown-path answer."""
    name = build_input.page_name(path)
    return _read(build.cur_pages(doc) / name) if name is not None else None


def pdf(doc: Doc, query: Query, text: Callable[[object], str]) -> bytes:
    """The PDF of the requested page build, or its contract 404 when absent or unreadable."""
    name = build_input.parse_build_name(query)
    path = build.build_pdf(doc, name)
    data = None if path is None else _read(path)
    if data is None:
        pdf_gone(name, build.cur_pages(doc).name, text)
    return data


def pdf_gone(name: str, pages_build: str, text: Callable[[object], str]) -> NoReturn:
    """GET /pdf: 404 for a gone named build or for the missing PDF of the on-screen build."""
    raise HTTPError(
        404,
        "그 빌드의 PDF 가 없습니다: %s" % text(name)[:60],
        pdf_build_gone=bool(name),
        pages_build=pages_build,
        reason="pdf_build_gone" if name else "pdf_missing",
    )
