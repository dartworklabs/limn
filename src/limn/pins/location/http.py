"""HTTP response contract for POST /api/pick."""

from collections.abc import Mapping
from typing import Any, Protocol, TypeAlias

from limn.pins.location import input as pick_input
from limn.pins.location.figure import PickedElement, Rung
from limn.pins.location.mapping import WEAK_SCORE
from limn.pins.location.resolve import (
    GeneratedFile,
    NoSourceHere,
    Picked,
    PickedRegion,
    PickRefusal,
    SourceUnreadable,
    SynctexOutside,
)
from limn.pins.location.service import PinLocationService
from limn.runtime.documents import Doc
from limn.web.answers import accepted
from limn.web.parse import DocumentFacts, Query, parse_flag

Body: TypeAlias = dict[str, object]


class LocationApp(Protocol):
    """The document facts and location service bound to one server run."""

    location_service: PinLocationService

    def document_facts(self, doc: Doc) -> DocumentFacts:
        """Read the selected document's build and page facts."""
        ...


def pick(app: LocationApp, doc: Doc, body: Mapping[str, Any]) -> Body:
    """Parse one selection and return its contract body after common request guards."""
    selection = pick_input.parse_pick(body, app.document_facts(doc))
    if isinstance(selection, pick_input.PickBuildGone):
        return pick_build_gone()
    return pick_answer(app.location_service.resolve(doc, accepted(selection)))


def snippet(app: LocationApp, doc: Doc, query: Query) -> Body:
    """GET /api/snippet after the common request guards; a document with an element map gets the raw rung as its
    ladder."""
    rng = accepted(pick_input.parse_snippet(query, app.document_facts(doc)))
    return app.location_service.snippet(rng, parse_flag(query, "levels"), not doc.has_element_map)


def overlaps(app: LocationApp, doc: Doc, query: Query) -> Body:
    """GET /api/overlaps after the common request guards."""
    rng = accepted(pick_input.parse_source_range(query, app.document_facts(doc)))
    return app.location_service.overlaps(rng)


# The sentences a pick's `warn` is made of (a UI hint in a 200 body, not an error). The viewer translates each by its
# template in PICK_WARNS (docs/handbook/viewer.md); src/limn/viewer/tests/test_i18n.py checks that every sentence here has one.
# figure_map_unavailable and element_without_source lead a figure's region answer (location.figure.FigureFallback).
PICK_WARNINGS = {
    "weak": "이 영역은 원문 대조가 약합니다(%.0f%%). 줄 범위를 눈으로 확인하세요.",
    "split": "두 경로가 다른 곳을 가리킵니다(L%d / L%d). 확인이 필요합니다.",
    "stale": "화면의 PDF 가 지금 원고보다 낡았습니다 — [PDF 재빌드] 뒤에 다시 고르세요.",
    "building": "빌드 중이라 결과가 흔들릴 수 있습니다.",
    "blank": "이 영역에는 글자가 없습니다(그림·스캔본). 메모에 무엇을 가리키는지 적어 주세요.",
    "redrawing": "PDF 가 바뀌어 쪽을 다시 그리는 중입니다 — 끝나면 다시 고르세요.",
    "figure_map_unavailable": "이 그림의 요소 지도를 읽지 못해 영역으로 찍습니다 — 그림 저장소가 지도를 다시 쓰면 다시 고르세요.",
    "element_without_source": "이 요소를 그린 코드 줄을 찾지 못해 영역으로 찍습니다 — 스크립트를 고친 뒤라면 그림을 다시 렌더하고 다시 고르세요.",
}
# Why a selection is not traced to manuscript lines (location.resolve.PickRefusal, one type each) -> (message, API reason).
# POST /api/pick answers each with a 200 {"error", "reason"} body (pick_answer), the message filled with the
# refusal's detail: the generated file's suffix, the path SyncTeX named, the unreadable file. The messages and reasons
# are part of the agent contract (api.md §오류 응답); tests pin every body and check that every refusal type has its row.
PICK_REFUSALS: dict[type[PickRefusal], tuple[str, str]] = {
    GeneratedFile: ("여기는 생성 파일(%s)입니다. 참고문헌은 .bib 나 본문 \\cite 를 고쳐야 합니다.", "generated_file"),
    SynctexOutside: ("SyncTeX 가 원고 밖 파일을 가리킵니다(%s). PDF 재빌드 뒤 다시 골라 보세요.", "synctex_outside"),
    SourceUnreadable: ("원문 파일을 읽지 못했습니다: %s", "source_unreadable"),
    NoSourceHere: ("그 자리에서 원문을 되짚지 못했습니다. 글자가 있는 쪽으로 조금 넓게 잡아 보세요.", "no_source_here"),
}


def pick_build_gone() -> Body:
    """POST /api/pick naming a page directory that is gone (location.input.PickBuildGone): a 200 whose error tells the
    viewer to pick again on the new PDF, with pdf_build_gone set."""
    return {
        "error": "화면의 PDF 가 이미 지워진 옛 빌드입니다 — 화면을 새 PDF 로 바꿨으니 다시 고르세요.",
        "reason": "pdf_build_gone",
        "pdf_build_gone": True,
    }


def pick_answer(result: Picked | PickedElement | PickedRegion | PickRefusal) -> Body:
    """POST /api/pick for every outcome, always a 200 body: the traced range with its ladder, a figure element's lines,
    a view-only region, or {"error", "reason"} for a selection that cannot be traced (PICK_REFUSALS, the message filled
    with the refusal's detail)."""
    match result:
        case Picked():
            return _picked_body(result)
        case PickedElement():
            return _element_body(result)
        case PickedRegion():
            return _region_body(result)
        case GeneratedFile(suffix=suffix):
            return _pick_refusal(result, suffix)
        case SynctexOutside(path=path) | SourceUnreadable(path=path):
            return _pick_refusal(result, path)
        case NoSourceHere():
            return _pick_refusal(result)


def _pick_refusal(refusal: PickRefusal, *detail: object) -> Body:
    """The 200 body of a pick refusal: its message from PICK_REFUSALS filled with detail, and its reason."""
    message, reason = PICK_REFUSALS[type(refusal)]
    return {"error": message % detail, "reason": reason}


def _picked_body(p: Picked) -> Body:
    """The body of a traced selection, keys in the order the agent contract has always had them."""
    t = p.traced
    return {
        "file": str(p.file),
        "name": p.file.name,
        "page": p.page,
        "lo": t.lo,
        "hi": t.hi,
        "raw_lo": t.raw_lo,
        "raw_hi": t.raw_hi,
        "kind": t.kind,
        "via": t.via,
        "score": round(t.score, 2),
        "warn": pick_warning(p),
        "n_lines": p.n_lines,
        "snippet": p.snippet,
        "frac": p.frac,
        "quote": p.quote,
        "levels": t.levels,
        "default_level": t.default_level,
        "overlaps": p.overlaps,
        "pdf_build": p.pdf_build,
    }


def pick_warning(p: Picked) -> str:
    """A traced selection's `warn`: the stale-PDF sentence first, then a weak match or the two paths disagreeing, then
    a running LaTeX build - the sentences that apply, joined by one space; "" when none does."""
    t = p.traced
    warn = ""
    if t.weak:
        warn = PICK_WARNINGS["weak"] % (t.score * 100)
    elif t.split is not None:
        warn = PICK_WARNINGS["split"] % t.split
    if p.stale:
        warn = PICK_WARNINGS["stale"] + (" " + warn if warn else "")
    if p.building:
        warn = (warn + " " if warn else "") + PICK_WARNINGS["building"]
    return warn


def _element_body(p: PickedElement) -> Body:
    """The body of a drag traced through a figure's map: the traced-selection body's keys in their contract order -
    the default rung's lines, via "map", the element's kind and name - then el and path_names, the name the map gives
    each id of el.path (label, else part, else "") (docs/handbook/api.md §그림 문서의 pick·핀). The score is rounded
    to two decimals like a traced selection's: full containment computes a cover a hair under 1.0. Only the body is
    rounded - element_warning still tests the unrounded score against WEAK_SCORE."""
    first = p.rungs[0]
    return {
        "file": str(p.file),
        "name": p.file.name,
        "page": p.page,
        "lo": first.lo,
        "hi": first.hi,
        "raw_lo": first.lo,
        "raw_hi": first.hi,
        "kind": p.kind,
        "via": "map",
        "score": round(p.score, 2),
        "warn": element_warning(p),
        "n_lines": p.n_lines,
        "snippet": first.snippet,
        "frac": p.frac,
        "quote": p.quote,
        "levels": [_rung_level(r) for r in p.rungs],
        "default_level": first.level,
        "overlaps": p.overlaps,
        "pdf_build": p.pdf_build,
        "el": p.el.to_record(),
        "path_names": list(p.path_names),
    }


def _rung_level(r: Rung) -> dict[str, object]:
    """One levels entry of a map pick, keys in the contract's order (docs/handbook/api.md §그림 문서의 pick·핀): level, lo,
    hi, n, label, snippet, then its el, then merged when outer rungs had the same lines."""
    out: dict[str, object] = {
        "level": r.level,
        "lo": r.lo,
        "hi": r.hi,
        "n": r.hi - r.lo + 1,
        "label": r.label,
        "snippet": r.snippet,
        "el": r.el.to_record(),
    }
    if r.merged:
        out["merged"] = list(r.merged)
    return out


def element_warning(p: PickedElement) -> str:
    """A map pick's warn: the weak-match sentence when the chosen element holds less than WEAK_SCORE of the drag, then
    the redraw sentence while the pages are being redrawn; "" when neither applies."""
    warn = PICK_WARNINGS["weak"] % (p.score * 100) if p.score < WEAK_SCORE else ""
    if p.redrawing:
        warn = (warn + " " if warn else "") + PICK_WARNINGS["redrawing"]
    return warn


def _region_body(r: PickedRegion) -> Body:
    """The body of a selection answered as a region - a view-only document's, or a figure's that fell back - keys in
    the order the agent contract has always had them. A figure's fallback leads the warn with its reason's sentence
    and adds el, the element it chose, and path_names, the names of its path, after the contract keys."""
    warn = PICK_WARNINGS[r.fallback] if r.fallback is not None else ""
    if r.blank:
        warn = (warn + " " if warn else "") + PICK_WARNINGS["blank"]
    if r.redrawing:
        warn = (warn + " " if warn else "") + PICK_WARNINGS["redrawing"]
    body: Body = {
        "doc": r.doc,
        "kind": "region",
        "view_only": True,
        "page": r.page,
        "frac": r.frac,
        "pdf": r.pdf,
        "name": r.name,
        "quote": r.quote,
        "n_chars": r.n_chars,
        "warn": warn,
        "overlaps": [],
        "pdf_build": r.pdf_build,
    }
    if r.el is not None:
        body["el"] = r.el.to_record()
        body["path_names"] = list(r.path_names)
    return body
