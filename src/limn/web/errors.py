"""What the HTTP layer refuses with, and how a refusal reads: the error type, the refusal tables and the browser page.

HTTPError is the one exception the handler turns into an error response ({"error": <Korean message>, "reason":
<code>, ...extra}); the messages and reason codes are part of the agent contract (docs/handbook/api.md §오류 응답) and
the messages are never reworded - the viewer shows English by the reason (ui_en.json `reason:<code>`). InputRejected is the value a
boundary parser returns instead of raising. The two tables below give the pin-scoping refusals (limn.scope) and the
failed steps of a comparison build (limn.revisions.StepFailed) their texts: the HTTP answers read them, and the
composition root hands revision_failure_text() to the comparison worker, which records the same texts in its status.

A browser that opens the viewer (GET / asking for HTML) and is refused gets a short readable page instead of raw
JSON (v0.2.1), in the viewer's language (ko/en) from the same message table the viewer uses (ui_en.json).
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from email.message import Message
from typing import NamedTuple, TypeAlias

from limn.revisions import BuildFailure, FailureKind, StepFailed
from limn.scope import PinNotInDoc, ScopeMismatch, ScopeRefusal, ScopeUnreadable, ScopeUnwritable, UnsafePath

# A page-kind error's (kind, params): kind is a key of ERROR_PAGE_TEXT, params fill its {placeholders}.
PageRef: TypeAlias = tuple[str, dict[str, object]]
# The viewer's ko -> en message table (ui_en.json): a string, or plural forms of which the page uses "other".
Messages: TypeAlias = Mapping[str, str | dict[str, str]]


class HTTPError(Exception):
    """The handler turns this directly into a JSON error response: status `code`, body
    {"error": msg, "reason": reason, **extra}.

    msg is the Korean text agents already read (api.md §오류 응답 - never reworded); reason is the stable snake_case
    code for the same refusal, required so that no refusal goes out without one. The viewer shows English by the
    reason (ui_en.json `reason:<code>`), agents may branch on it. page names the readable HTML page a browser gets
    instead when it opens the viewer (error_page_html); without it the browser gets the generic page with msg as its
    detail line.
    """

    def __init__(self, code: int, msg: str, *, reason: str, page: PageRef | None = None, **extra: object) -> None:
        """Keep the status, the JSON body (error, reason, then extra in order) and the optional page reference."""
        super().__init__(msg)
        self.code = code
        self.body: dict[str, object] = dict({"error": msg, "reason": reason}, **extra)
        self.page = page


class InputRejected(NamedTuple):
    """A request field the server refuses with 400; message is the response's error text, word for word, and reason
    its stable code (api.md §오류 응답), which the HTTP answer puts next to it.

    Boundary parsers (server.py's parse_* functions) return it instead of raising; the handler answers it with
    HTTPError(400, message, reason=reason). A NamedTuple, as it was when it lived in server.py, so values compare
    exactly as before."""

    message: str
    reason: str


# Expected refusals of pin scoping (limn.scope.ScopeRefusal, one type each) -> (status, message, API reason). The one
# place they become responses - the revision answers for requests (answers.revision_answer), and through
# revision_failure_text() the status a failed comparison build stores. The messages and reasons are part of the agent
# contract (api.md §핀 단위 변경 보기); tests pin every body and check that every refusal type has its row.
SCOPE_REJECTIONS: dict[type[ScopeRefusal], tuple[int, str, str]] = {
    PinNotInDoc: (404, "이 문서의 핀이 아닙니다.", "pin_not_in_doc"),
    ScopeUnreadable: (422, "이 핀의 변경만 골라 적용하지 못했습니다.", "scope_failed"),
    ScopeMismatch: (422, "이 핀의 변경을 커밋에서 다시 찾지 못했습니다.", "scope_failed"),
    UnsafePath: (422, "사본에 허용되지 않는 경로가 있습니다.", "unsafe_snapshot"),
    ScopeUnwritable: (422, "이 핀의 변경만 넣은 사본을 쓰지 못했습니다.", "scope_failed"),
}


def scope_http_error(e: ScopeRefusal) -> HTTPError:
    """The HTTP form of a pin-scoping refusal, from SCOPE_REJECTIONS."""
    code, msg, reason = SCOPE_REJECTIONS[type(e)]
    return HTTPError(code, msg, reason=reason)


# A failed step of a comparison build (limn.revisions.StepFailed.kind) -> (message, API reason) its "error" status
# carries (api.md §변경 보기와 비교 PDF). These never become an HTTP status of their own: the build runs in the
# background and GET /api/revision-build reports the stored status. tests check that every kind has its row.
REVISION_FAILURES: dict[FailureKind, tuple[str, str]] = {
    "tool_start": ("비교 PDF 실행 도구를 시작하지 못했습니다.", "tool_unavailable"),
    "timeout": ("비교 PDF 실행 시간이 초과됐습니다.", "timeout"),
    "size": ("비교 입력 또는 실행 로그가 크기 제한을 넘었습니다.", "size_limit"),
    "snapshot_read": ("Git 원고 사본을 읽지 못했습니다.", "snapshot_failed"),
    "unsafe_snapshot": ("사본에 허용되지 않는 경로·심링크·하위 저장소가 있습니다.", "unsafe_snapshot"),
    "snapshot_size": ("원고 사본이 파일 수·크기 제한을 넘었습니다.", "size_limit"),
    "snapshot_timeout": ("Git 사본 생성 시간이 초과됐습니다.", "timeout"),
    "snapshot_blob": ("Git 원고 파일을 읽지 못했습니다.", "snapshot_failed"),
    "missing_main": ("해당 커밋에 현재 메인 원고 경로가 없습니다. 소스 변경사항을 확인하세요.", "missing_main"),
    "sandbox_tools": ("비교 PDF에는 bwrap, latexdiff, latexmk가 필요합니다.", "tool_unavailable"),
    "sandbox_system": ("비교 PDF 도구는 /usr 아래의 시스템 설치를 사용해야 합니다.", "tool_unavailable"),
    "diff_failed": (
        "latexdiff가 원고를 비교하지 못했습니다. 누락된 포함 파일 또는 실행 격리 설정을 확인하세요.",
        "diff_failed",
    ),
    "compile_failed": (
        "비교 PDF 컴파일에 실패했습니다. 이 뷰어는 pdfLaTeX를 사용합니다. 소스 변경사항을 확인하세요.",
        "compile_failed",
    ),
    "invalid_pdf": ("비교 PDF 결과가 올바르지 않습니다.", "invalid_pdf"),
}


def revision_failure_text(failure: BuildFailure) -> tuple[str, str]:
    """(message, API reason) a failed comparison build records: a step's from REVISION_FAILURES, a pin-scoping
    refusal's from SCOPE_REJECTIONS (the same text its HTTP answer has)."""
    if isinstance(failure, StepFailed):
        return REVISION_FAILURES[failure.kind]
    _, msg, reason = SCOPE_REJECTIONS[type(failure)]
    return msg, reason


# The page kinds identity refusals name (HTTPError page=(kind, params)) -> (heading, hint). The Korean text is the key
# into the viewer's message table (ui_en.json), so the page follows the same ko/en table as the viewer.
ERROR_PAGE_TEXT = {
    "not-member": (
        "이 뷰어의 멤버가 아닙니다: {login}",
        "이 뷰어의 소유자에게 멤버로 추가해 달라고 요청하세요: limn member add <인스턴스> {login}",
    ),
    "not-allowed": (
        "이 뷰어에 허용되지 않은 계정입니다: {login}",
        "이 뷰어의 소유자에게 --allow 목록에 넣어 달라고 요청하세요",
    ),
    "no-identity": (
        "신원을 확인할 수 없는 요청입니다",
        "사람 계정으로 로그인한 장치에서 여세요. 에이전트는 토큰(Authorization: Bearer)을 씁니다: limn token create <인스턴스>",
    ),
}


def page_lang(headers: Message, query: Mapping[str, list[str]]) -> str:
    """ko or en for a server-rendered page: ?lang=, else the first Accept-Language tag (ko* -> ko), else en - the viewer's rule."""
    v = (query.get("lang") or [""])[0]
    if v in ("ko", "en"):
        return v
    first = (headers.get("Accept-Language") or "").split(",")[0].strip().lower()
    return "ko" if first.startswith("ko") else "en"


def ui_text(key: str, lang: str, messages: Messages, **params: object) -> str:
    """One message from the viewer's table, filled in (the server-side twin of the viewer's tl()).

    In ko the Korean key is the text; in en it is the table's entry (its "other" form when plural), or the key
    itself when the table has none. Each {name} placeholder is replaced by str(params[name]).
    """
    v = messages.get(key, key) if lang == "en" else key
    if isinstance(v, dict):
        v = v.get("other", key)
    for k, x in params.items():
        v = v.replace("{%s}" % k, str(x))
    return v


def error_page_html(e: HTTPError, lang: str, messages: Messages) -> str:
    """The readable page for a browser whose GET / was refused: e's page kind (heading and hint) when it names one,
    else a generic heading with the error text as a detail line; every value is HTML-escaped. The page links to
    itself in the other language (/?lang=)."""
    kind, params = e.page or ("", {})
    if kind in ERROR_PAGE_TEXT:
        head, hint = (ui_text(k, lang, messages, **params) for k in ERROR_PAGE_TEXT[kind])
        detail = ""
    else:
        head, hint = ui_text("이 뷰어를 열 수 없습니다 ({code})", lang, messages, code=e.code), ""
        detail = str(e.body.get("error") or "")
    other = "en" if lang == "ko" else "ko"
    esc = html.escape
    return (
        '<!doctype html><html lang="%s"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Limn · %s</title>'
        '<style>body{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Pretendard","Noto Sans KR",sans-serif;max-width:36rem;'
        "margin:15vh auto;padding:0 1.25rem;color:#18181b;background:#fafafa}h1{font-size:1.15rem;margin:0 0 .6rem}"
        "p{margin:.4rem 0;color:#3f3f46}code,.d{font:13px ui-monospace,monospace;word-break:break-all}"
        "a{color:#1860cf}@media(prefers-color-scheme:dark){body{color:#fafafa;background:#09090b}p{color:#a1a1aa}a{color:#6ea8fe}}"
        '</style></head><body><h1>%s</h1>%s%s<p><a href="/?lang=%s">%s</a></p></body></html>'
        % (
            lang,
            esc(str(e.code)),
            esc(head),
            "<p>%s</p>" % esc(hint) if hint else "",
            '<p class="d">%s</p>' % esc(detail) if detail else "",
            other,
            "English" if other == "en" else "한국어",
        )
    )
