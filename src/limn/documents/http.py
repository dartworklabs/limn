"""HTTP responses for viewer meta, document list, published outline labels and a browser-drawn document's source."""

from collections.abc import Callable, Mapping
from typing import Any

from limn.documents import input as document_input
from limn.documents.service import DocumentViews
from limn.documents.source import SourceLines, SourceNotUtf8, SourceTooLarge, SourceUnreadable, read_source
from limn.runtime.documents import Doc
from limn.security import access
from limn.web import parse
from limn.web.answers import accepted
from limn.web.errors import HTTPError

Json = dict[str, Any]


def meta(
    service: DocumentViews,
    doc: Doc,
    actor: Json,
    role: access.Role,
    query: Mapping[str, list[str]],
    record_person: Callable[[], None],
) -> Json:
    """GET /api/meta: record a full viewer read, then append role and event notifications."""
    light = parse.parse_flag(query, "light")
    if not light:
        record_person()
    out = service.meta(doc, actor, light)
    out["me"] = dict(actor, role=role)
    # Preserve the existing order: an invalid event cursor is refused only after meta is built.
    out.update(service.events_since(actor, accepted(document_input.parse_events_query(query))))
    return out


def docs(service: DocumentViews) -> Json:
    """GET /api/docs."""
    return service.docs_payload()


def outline(service: DocumentViews, doc: Doc) -> Json:
    """GET /api/outline-labels."""
    return service.outline(doc)


def source(doc: Doc) -> Json:
    """GET /api/source: the source of document doc, which the browser draws, as {doc, file, src_mtime, lines}.

    file is the source's path as a pin on it stores it (the checked manuscript file); lines are its lines as the server
    numbers them (limn.documents.source.source_lines); src_mtime the stamp read before them. The refusals, each its own
    reason: 400 not_rendered_in_browser for a document the viewer shows as pages (its lines are read with /api/snippet);
    the 400 every file route answers for a path outside the manuscript tree - outside --manuscript, under a dot-named
    folder, in the state folder (file_outside_manuscript) - or for no regular file there (file_not_found); 413
    source_too_large with `bytes` and `limit` and no lines; 422 source_not_utf8; 422 source_unreadable when the checked
    handle refuses the file after the tree check. Reads the file only through the checked handle and writes nothing."""
    if not doc.renders_in_browser:
        raise HTTPError(
            400,
            "브라우저가 원문을 그리는 문서가 아닙니다(%s) — 줄은 /api/snippet 으로 읽습니다." % doc.key,
            reason="not_rendered_in_browser",
        )
    checked = accepted(parse.source_file(str(doc.main), doc.paths.src, doc.paths.state))
    match read_source(checked):
        case SourceLines(lines=lines, src_mtime=src_mtime):
            return {"doc": doc.key, "file": str(checked), "src_mtime": src_mtime, "lines": list(lines)}
        case SourceTooLarge(size=size, limit=limit):
            raise HTTPError(
                413,
                "원문이 너무 커서 보내지 않습니다(%d바이트, 한도 %d바이트)." % (size, limit),
                reason="source_too_large",
                bytes=size,
                limit=limit,
            )
        case SourceNotUtf8():
            raise HTTPError(422, "원문이 UTF-8 이 아닙니다: %s" % checked, reason="source_not_utf8")
        case SourceUnreadable():
            raise HTTPError(422, "원문 파일을 읽지 못했습니다: %s" % checked, reason="source_unreadable")
