"""HTTP responses for viewer meta, document list, published outline labels and a browser-drawn document's source."""

from collections.abc import Mapping
from typing import Any

from limn.documents import input as document_input
from limn.documents.assets import (
    ASSET_CACHE,
    AssetBytes,
    AssetNotImage,
    AssetPathRefused,
    AssetTooLarge,
    AssetTooManyPixels,
    AssetUnreadable,
    asset_path,
    read_asset,
)
from limn.documents.service import DocumentViews
from limn.documents.source import SourceLines, SourceNotUtf8, SourceTooLarge, SourceUnreadable, read_source
from limn.runtime.documents import Doc
from limn.security import access
from limn.web import parse
from limn.web.answers import accepted
from limn.web.errors import HTTPError
from limn.web.reply import Reply

Json = dict[str, Any]


def meta(
    service: DocumentViews,
    doc: Doc,
    actor: Json,
    role: access.Role,
    query: Mapping[str, list[str]],
) -> Json:
    """GET /api/meta: read viewer facts, then append role and event notifications."""
    light = parse.parse_flag(query, "light")
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
    """GET /api/source: the source of document doc, which the browser draws, as {doc, file, src_mtime, lines, line_ends}.

    file is the source's path as a pin on it stores it (the checked manuscript file); lines are its lines as the server
    numbers them (limn.documents.source.source_lines); line_ends the line ends among them that are not LF or CRLF, by
    name with their counts (other_line_ends, {} for none); src_mtime the stamp read before them. The refusals, each its own
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
        case SourceLines(lines=lines, src_mtime=src_mtime, line_ends=line_ends):
            return {
                "doc": doc.key,
                "file": str(checked),
                "src_mtime": src_mtime,
                "lines": list(lines),
                "line_ends": dict(line_ends),
            }
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


def asset(doc: Doc, query: Mapping[str, list[str]]) -> Reply:
    """GET /api/asset?path=<tree-relative path>: an image of document doc's manuscript tree, as its bytes
    (limn.documents.assets). doc selects the tree (every document of an instance shares --manuscript).

    200 with the media type its suffix names, an ETag of its content (a matching If-None-Match is a 304), Cache-Control
    private, no-cache. The asset's own Content-Security-Policy and Cross-Origin-Resource-Policy: same-origin go out on
    every response of the path, this answer and each refusal alike (the path's policy, limn.documents.application). The
    refusals, each its own reason: 400 bad_asset_path for a path the viewer would not send (asset_path); the 400 every
    file route answers for a path outside the tree - outside --manuscript, under a dot-named folder, behind a link that
    leads out, in the state folder (file_outside_manuscript) - or for no regular file there (file_not_found); 413
    asset_too_large with `bytes` and `limit` (ASSET_MAX_BYTES); 413 asset_too_many_pixels with `width`, `height` and
    `limit` (ASSET_MAX_PIXELS) for a raster image whose header gives it more pixels; 415 asset_not_image when the bytes are
    not the format the suffix names; 422 asset_unreadable when the checked handle refuses the file after the tree check.
    Writes nothing."""
    wanted = asset_path(parse.query_first(query, "path"))
    if isinstance(wanted, AssetPathRefused):
        raise HTTPError(400, "그림 경로가 올바르지 않습니다.", reason="bad_asset_path")
    rel = wanted.rel
    checked = accepted(parse.source_file(rel, doc.paths.src, doc.paths.state))
    match read_asset(checked, wanted.suffix):
        case AssetBytes(data=data, media=media, etag=etag):
            return Reply(200, data, media, ASSET_CACHE, etag)
        case AssetTooLarge(size=size, limit=limit):
            raise HTTPError(
                413,
                "그림이 너무 커서 보내지 않습니다(%d바이트, 한도 %d바이트)." % (size, limit),
                reason="asset_too_large",
                bytes=size,
                limit=limit,
            )
        case AssetTooManyPixels(width=width, height=height, limit=limit):
            raise HTTPError(
                413,
                "그림의 화소가 너무 많아 보내지 않습니다(%d×%d, 한도 %d화소)." % (width, height, limit),
                reason="asset_too_many_pixels",
                width=width,
                height=height,
                limit=limit,
            )
        case AssetNotImage():
            raise HTTPError(415, "그림 파일의 내용이 확장자와 맞지 않습니다: %s" % rel, reason="asset_not_image")
        case AssetUnreadable():
            raise HTTPError(422, "그림 파일을 읽지 못했습니다: %s" % rel, reason="asset_unreadable")
