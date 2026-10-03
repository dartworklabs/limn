"""GET paths and replies for the viewer shell and bundled browser assets."""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from limn.viewer.assemble import ServedViewer
from limn.viewer.mark import ICON_ROUTES
from limn.web.errors import HTTPError
from limn.web.reply import Reply, json_reply
from limn.web.routes import GetRequest

# PoC only (issues #167, #168; branch poc/toast-and-select): GET /poc lists the ?poc= variants of js/poc.js, one Korean
# line each. Static text with no request data in it.
_POC_ROWS = (
    (
        "q1a",
        "#167 A · 맥락에만",
        "일어난 자리에 — 새 핀 마크에 '저장됨 [되돌리기]', 저장 실패는 [다시 저장] 바로 위, 핀 일은 그 카드 안·카드 자리, 안내는 PDF 위",
    ),
    (
        "q1b",
        "#167 B · 상태 줄",
        "모든 알림이 시트 위 상태 줄(데스크톱은 칩 줄 아래 한 줄)에 — 다음 알림이 올 때까지 남고 [되돌리기]도 거기에",
    ),
    (
        "q1c",
        "#167 C · 섞음",
        "성공은 조용히(되돌릴 수 있으면 카드 안), 오류·충돌은 패널 위 배너, 배경 사건은 상태 줄 + 배지 점",
    ),
    ("q2a", "#168 a · 아이콘 + 글자", "대칭 점선 상자 아이콘에 '선택' 글자를 늘 붙이고, 켜면 강조색 채움과 '선택 중'"),
    (
        "q2b",
        "#168 b · 분절 스위치",
        "[보기 | 선택] 분절 컨트롤로 지금 모드와 바꿀 모드를 함께 보인다. 휴대폰 세로는 막대에 자리가 없어 PDF 왼쪽 아래에",
    ),
    (
        "q2c",
        "#168 c · PDF 안 모드 막대",
        "막대에는 아이콘만, 켜면 PDF 위에 '선택 중 · 끌면 영역 · 탭하면 문단 [끝내기]' 막대와 강조 테두리",
    ),
)
POC_INDEX = (
    '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Limn PoC · #167 #168</title>'
    "<style>body{font:15px/1.6 -apple-system,Pretendard,sans-serif;margin:24px;max-width:720px}"
    "li{margin:6px 0}code{font-size:13px}</style></head><body>"
    "<h1>Limn PoC — 토스트 대체(#167)·선택 컨트롤(#168)</h1>"
    "<p>최종 설계가 아니라 고르기 위한 시안이다. 플래그는 함께 쓸 수 있다(예: <code>/?poc=q1b,q2a</code>). "
    "플래그가 없으면 지금 화면 그대로다.</p><ul>"
    + "".join(
        '<li><a href="/?poc=%s"><code>?poc=%s</code></a> <b>%s</b> — %s</li>' % (key, key, name, line)
        for key, name, line in _POC_ROWS
    )
    + "</ul></body></html>"
)

# The vendor file validator admits only .mjs.
VENDOR_MIME: Mapping[str, str] = {".mjs": "text/javascript; charset=utf-8"}


class ViewerShellApp(Protocol):
    """Run-specific values needed to serve the viewer shell."""

    APP_NAME: str

    def viewer(self) -> ServedViewer:
        """Return the page, service worker and icons (by GET path) bound to this run."""
        ...

    def app_version(self) -> str:
        """Return the installed application version."""
        ...

    def vendor_file(self, name: str) -> Path | None:
        """Validate and locate one bundled PDF.js file."""
        ...

    def hdr_text(self, value: object) -> str:
        """Render a path safely for an HTTP refusal."""
        ...


def _read(path: Path) -> bytes | None:
    """Read a served file or return None when it is unavailable."""
    try:
        return path.read_bytes()
    except OSError:
        return None


def get(request: GetRequest, app: ViewerShellApp) -> Reply | None:
    """Serve the viewer shell, its icons, version, worker, or PDF.js file; None for a path that is not one of them.

    An ICON_ROUTES path answers the run's vendored icon file unchanged, publicly cacheable for a day. The page's links
    carry a content key (?v=), so a new drawing gets a new URL there; only those linked URLs are busted - the bare
    /favicon.ico and /apple-touch-icon.png a browser or iOS asks for on its own can stay cached for up to a day. A run
    whose viewer holds no icon for the path answers 404."""
    path = request.path
    if path == "/":
        request.record_person()
        return Reply(200, app.viewer().page.encode(), "text/html; charset=utf-8")
    if path == "/poc":
        return Reply(200, POC_INDEX.encode(), "text/html; charset=utf-8", "no-cache")
    if path in ICON_ROUTES:
        icon = app.viewer().icons.get(path)
        if icon is None:
            raise HTTPError(404, "없는 아이콘입니다: %s" % app.hdr_text(path)[:100], reason="not_found")
        return Reply(200, icon.body, icon.content_type, "public, max-age=86400")
    if path == "/api/version":
        return json_reply({"name": app.APP_NAME, "version": app.app_version()})
    if path == "/sw.js":
        return Reply(200, app.viewer().service_worker.encode(), "text/javascript; charset=utf-8", "no-cache")
    if path.startswith("/vendor/pdfjs/"):
        # The validator rejects subpaths, traversal and encoded characters.
        vf = app.vendor_file(path[len("/vendor/pdfjs/") :])
        data = None if vf is None else _read(vf)
        if vf is not None and data is not None:
            return Reply(200, data, VENDOR_MIME[vf.suffix], "public, max-age=86400")
        raise HTTPError(404, "없는 vendor 파일입니다: %s" % app.hdr_text(path)[:100], reason="not_found")
    return None
