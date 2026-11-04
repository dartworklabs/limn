# 뷰어 페이지의 Content-Security-Policy

> **상태: 승인됨 (2026-11-04).** [HTML 문서 화면 설계](2026-10-24-html-document-surface.md) §결정 5의 5번과 [ADR-0025](../../adr/0025-html-document-surface.md) D6이 앞선 조건으로 따로 승인받기로 한 결정이다(계획 Task 0 Step 3). 소유자가 2026-11-04에 §소유자 결정의 물음을 모두 추천안대로 정했다: 엄격한 `style-src`(해시만, `'unsafe-inline'` 없음), 첫 판부터 강제(Report-Only 경로도 끄는 실행 인자도 없음), 사람 사진은 `img-src 'self' https:`, 거절 페이지에도 같은 정책. [ADR-0026](../../adr/0026-viewer-csp.md)이 `승인됨` 이다.

## 문제

지금 모든 응답의 CSP는 `frame-ancestors 'none'` 하나다(`web/handler.py` `end_headers`). 그래서 뷰어 페이지에서는 어떤 스크립트든 돈다. 뷰어는 지금 사람이 쓴 글을 `html``…`` 의 이스케이프와 `setHtml()` 한 곳(`markup.js`)으로만 그리므로 막힌 구멍은 없다. 그러나 HTML 화면이 들어오면 뷰어는 같은 출처에서, 읽는 사람의 신원으로, 남이 쓴 Markdown을 그린다. 렌더러 규율(DOM API만, 원시 HTML 자리표시, 링크 허용 목록) 하나가 무너지면 그 문서가 Limn API를 읽는 사람의 권한으로 부를 수 있다. CSP는 그때 주입된 스크립트가 돌지 않게 하는 두 번째 벽이다.

## 현재 코드 대조

| 사실 | 자리 | CSP에 주는 뜻 |
| --- | --- | --- |
| 뷰어 페이지는 인라인 `<script>` 셋(테마, 언어, 뷰어 본체)과 인라인 `<style>` 하나다. 본체 스크립트와 스타일시트는 `parts.txt` 의 조각을 이어 붙인다 | `viewer/index.html`, `viewer/assemble.py` `load_viewer_html` | 해시 넷이면 인라인 전부를 허용한다 |
| 실행마다 채우는 자리표시가 스크립트와 스타일시트 안에 있다. 언어 스크립트의 `__UI_LANG__`, `tokens.css` 의 `--brand:__ACCENT__` | `assemble.py` `run_page` | 해시는 템플릿이 아니라 실행의 페이지에서 잰다 |
| 인라인 이벤트 처리기(`onclick=` 등)와 `javascript:` 주소가 없다. 클릭은 `data-act` 로 나눈다 | `js/events.js` | `script-src` 에 `'unsafe-inline'` 이 필요 없다 |
| `style` 속성이 넷 있다. `#brand-stripe` 의 `background:__ACCENT__`, `#trash-h` 의 `margin:0`, 위치 다시 잡기 줄의 오류(`repick.js`), 빌드 오류 로그의 `max-height:30vh`(`rebuild.js`) | `index.html`, `js/repick.js`, `js/rebuild.js` | 엄격한 `style-src` 에서 막힌다. CSS 규칙으로 옮긴다(§위반과 고침) |
| JS는 모양을 `el.style.x = …` 와 `style.cssText` 로 바꾼다 | 여러 조각, PDF.js | CSSOM이라 CSP가 다루지 않는다. 그대로 된다 |
| PDF.js는 같은 출처의 모듈을 `import()` 하고 같은 출처의 worker를 띄운다. `isEvalSupported:false`, `useWasm:false` 다 | `js/pdf-open.js`, `js/revisions.js` | `'unsafe-eval'`·`'wasm-unsafe-eval'` 이 필요 없다 |
| 사람 사진은 `Tailscale-User-Profile-Pic` 의 주소다. 서버는 `https://` 로 시작하는 1,000자 이하만 받는다 | `security/access.py` | `img-src` 에 `https:` 가 필요하다 |
| 거절 페이지(브라우저가 `GET /` 에서 거절될 때)에 인라인 `<script>` 와 `<style>` 이 하나씩 있다 | `web/errors.py` `error_page_html` | 같은 방식으로 해시한다 |
| 브라우저 시험의 가로채기 경로는 서버 응답에서 `content-type`·`content-disposition` 만 넘긴다 | `tests/support/helpers_browser.py` `forward` | 지금 브라우저 시험은 `frame-ancestors` 조차 본 적이 없다. CSP 회귀를 잡으려면 헤더를 넘겨야 한다 |

## 제안

### 정책

뷰어 페이지(`GET /`)와 거절 페이지에만 아래 정책을 보낸다. 다른 응답(JSON, `pins.md`, PDF, 쪽 이미지, vendor 파일, 서비스 워커, 표준 라이브러리의 오류 쪽)은 지금처럼 `frame-ancestors 'none'` 하나다.

```text
default-src 'self';
script-src 'self' 'sha256-<테마>' 'sha256-<언어>' 'sha256-<뷰어>';
style-src 'self' 'sha256-<스타일시트>';
img-src 'self' https:;
object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'none'
```

| 지시어 | 값 | 까닭 |
| --- | --- | --- |
| `default-src` | `'self'` | `connect`(같은 출처 `fetch`), `font`(Pretendard), `worker`(PDF.js worker, 서비스 워커, 이후의 Markdown 파싱 Worker), `manifest`·`media` 를 같은 출처로 덮는다. `worker-src` 를 따로 두지 않는다. CSP2 브라우저(Safari 15.4 이하)는 worker를 `child-src`, 없으면 `default-src` 로 찾고, CSP3 브라우저는 `child-src`, `script-src` 순으로 찾는다. 어느 쪽이든 `'self'` 가 되어 판마다 다르지 않다 |
| `script-src` | `'self'` + 인라인 셋의 해시 | `'self'` 는 PDF.js(이후 markdown-it)의 `import()` 와 서비스 워커 등록을 덮는다. `'unsafe-inline'`·`'unsafe-eval'`·`'strict-dynamic'`·nonce를 쓰지 않는다. nonce는 응답마다 새 값과 페이지 다시 쓰기가 필요하다. 페이지가 실행마다 고정이므로 해시가 맞다 |
| `style-src` | `'self'` + 스타일시트의 해시 | `'self'` 는 Pretendard 스타일시트다. `style` 속성과 남이 넣은 `<style>` 은 막힌다. 주입된 CSS가 속성 선택자로 값을 읽어 `https:` 그림 주소로 내보내는 길을 닫는다 |
| `img-src` | `'self' https:` | 쪽 PNG와 파비콘은 같은 출처, 사람 사진은 신원 공급자의 `https` 주소다. 호스트를 정하지 않는다. 공급자마다 다르기 때문이다. `data:`·`blob:` 은 뷰어가 쓰지 않는다 |
| `object-src`·`base-uri`·`form-action`·`frame-src` | `'none'` | 뷰어에 플러그인, `<base>`, 양식, 프레임이 없다. 주입된 `<base>` 가 상대 주소를 돌리거나 주입된 양식이 다른 곳으로 보내는 길을 닫는다 |
| `frame-ancestors` | `'none'` | 지금과 같다(`X-Frame-Options: DENY` 와 함께) |
| 보고(`report-to`·`report-uri`) | 없음 | 받을 경로가 없다(§Report-Only를 먼저 내지 않는다) |

### 해시를 맞게 유지하는 법

- **보내는 문자열에서 잰다.** `limn/web/csp.py` 의 `page_policy(page)` 가 보낼 문자열에서 인라인 `<script>`·`<style>` 의 글을 찾아 SHA-256을 잰다. `GET /` 는 보내는 바로 그 `page` 로 정책을 구한다(`viewer/routes.py`). 정책을 따로 저장하지 않으므로 정책과 페이지가 어긋날 수 없다. 1.6 MB 페이지에 약 20 ms이고, 실행은 같은 페이지 객체를 보내므로 두 번째 요청부터는 기억한 값이다(`lru_cache`, Python이 문자열의 해시를 객체에 기억한다). 조립(`assemble.py`)은 지금처럼 `limn.web` 을 모른다. 거절 페이지는 보낼 때 잰다.
- **브라우저와 같게 읽는다.** HTML 토크나이저는 글을 만들기 전에 CR LF와 홀로 선 CR을 LF로 바꾼다. 해시도 그 뒤에 잰다. 속성이 붙은 `<script>`, 글 안의 다른 닫는 태그(`</SCRIPT `), `<!--` 처럼 토크나이저가 다르게 읽을 수 있는 꼴은 해시하지 않고 거부한다(`ValueError`, 요청은 500). 페이지가 실행마다 달라지는 것은 이름(이스케이프됨)·색(`#rrggbb`)·언어(`ko`·`en`)뿐이므로, 꾸러미의 페이지가 어떤 실행 값으로도 읽힌다는 것을 시험이 미리 확인한다. 조립 결함은 운영이 아니라 시험에서 드러난다.
- **헤더 하나로 보낸다.** 처리기는 `_send(…, csp=)` 로 받은 페이지 정책을 그 응답의 `end_headers` 에서 한 번 쓰고 지운다. 그 밖의 응답과 표준 라이브러리 오류 쪽은 `FRAME_ONLY` 다. CSP 헤더가 둘이면 브라우저는 둘 다 지키므로 페이지에는 하나만 보낸다.
- **시험이 바이트로 확인한다.** §시험.

### 위반과 고침

| 위반 | 어디서 | 고침 |
| --- | --- | --- |
| `style-src-attr` — `#brand-stripe` 의 `style="background:__ACCENT__"` | 모든 페이지 로드 | `#brand-stripe{…;background:var(--brand)}`. `--brand` 는 이미 `tokens.css` 의 `:root{--brand:__ACCENT__}` 이므로 같은 색이다 |
| `style-src-attr` — `#trash-h` 의 `style="margin:0"` | 모든 페이지 로드 | 지운다. `.ns-head h2{margin:0}` 가 이미 같은 값을 준다 |
| `style-src-attr` — 위치 다시 잡기 줄의 `<span class="errline" style="margin:0">` | 다시 잡기 실패 | `class="errline flush"` 와 `.errline.flush{margin:0}`. `.errline` 의 다른 규칙보다 구체적이다 |
| `style-src-attr` — 빌드 오류의 `<pre class="nowrap" style="max-height:30vh">` | 빌드 실패 패널 | `#build-err pre{max-height:30vh}`. `pre{max-height:44vh}` 보다 구체적이다 |

뷰어 자신의 위반은 이 넷뿐이다. 스크립트·worker·글꼴·연결·그림 위반은 없었다. 앞의 둘은 모든 페이지 로드에서 났고(첫 실측에서 페이지 로드마다 2건), 뒤의 둘은 그 흐름을 지날 때만 난다. 위치 다시 잡기의 오류 줄은 브라우저 시험이 지나지 않는 흐름이라 정적 검사로 찾았다. 그래서 정적 가드를 더한다(§시험).

### 브라우저 시험과 Report-Only

브라우저 시험은 정책을 강제로 걸 수 없다. Playwright의 `wait_for_function()` 은 조건 글을 페이지 안에서 `eval` 로 돌린다. Chromium과 Firefox 모두 그랬다. `'unsafe-eval'` 없는 정책을 강제하면 모든 시험이 첫 기다림에서 멈춘다. `bypass_csp` 는 정책을 통째로 끄므로 잴 수 없다.

그래서 시험의 가로채기 경로는 서버의 정책을 **`Content-Security-Policy-Report-Only` 로 바꿔** 브라우저에 준다. 바꾸는 것은 헤더 이름과 보고에 글 앞부분을 싣는 `'report-sample'` 뿐이다. Report-Only도 강제와 같은 지시어로 같은 대상을 보고하고, 막는 것은 모두 보고된다. 그래서 "보고 0건"은 "강제해도 막히는 것 0건"과 같다. 페이지마다 `securitypolicyviolation` 을 듣는 스크립트를 먼저 넣고, 보고가 하나라도 있으면 그 시험을 실패로 한다(`tests/support/helpers_csp.py`). 시험 자신의 `eval`(주소 없는 코드나 Firefox의 `debugger eval code` 에서 막힌 `eval`)만 뺀다. 뷰어의 코드는 늘 주소가 있으므로(인라인은 페이지 주소, 모듈은 `/vendor/…`) 뷰어의 `eval` 은 빠지지 않는다.

강제 자체는 따로 시험한다(`viewer/tests/test_viewer_csp.py`). 실제 HTTP 서버가 보낸 헤더 그대로 띄우고, `eval` 이 필요 없는 기다림(선택자 엔진, 페이지가 푸는 Promise)만 쓴다. Chromium·Firefox·WebKit 클래스가 있다.

### 시험

| 시험 | 보는 것 | 자리 |
| --- | --- | --- |
| 헤더 = 바이트 | `GET /` 와 거절 페이지의 헤더 해시가 받은 몸의 인라인 글 해시와 같다. 오라클은 `limn.web.csp` 와 따로 `html.parser`·`hashlib` 으로 몸을 읽는다 | `web/tests/test_csp.py` |
| 실행마다 | 언어와 색이 다른 두 실행의 정책이 다르고, 각자 자기 바이트와 맞다(템플릿에서 재면 실패한다) | 같은 곳 |
| 지시어 | 위 표의 값, `unsafe` 가 없다, 다른 응답은 `frame-ancestors 'none'` 하나다 | 같은 곳, `security/tests/test_security.py` `FramingHeaders` |
| 읽을 수 없는 꼴 | 속성 붙은 태그, 다른 닫는 태그, `<!--` 는 `ValueError`. 꾸러미의 페이지는 `</script><!--` 같은 이름을 줘도 브라우저와 같게 읽힌다 | `test_csp.py` |
| 강제 | 원고·그림 문서·보기 전용 PDF를 PDF.js 모듈과 worker로 그리고, 도움말이 열리며, 보고가 0건이다. 페이지에 없던 스크립트 요소와 `onclick` 속성은 돌지 않고 각각 보고된다 | `viewer/tests/test_viewer_csp.py` |
| 보고 0건 | 모든 브라우저 시험의 페이지가 보고를 내지 않는다 | `tests/support/helpers_csp.py`(pytest 플러그인), 가로채기 경로 |
| 정적 가드 | 템플릿과 JS 조각에 `style` 속성(`setAttribute('style', …)` 포함), `on…=` 처리기 속성, `javascript:` 주소가 없다. JS 속성(`el.style`, `el.onclick`)은 걸리지 않는다. 브라우저 시험이 지나지 않는 흐름(다시 잡기 오류 줄)을 덮는다 | `test_viewer_csp.py` `StaticGuards` |

시험 코드가 일으키던 위반도 고쳤다. 고치지 않으면 보고 0건 가드가 실패하기 때문이다.

| 시험 코드의 위반 | 고침 |
| --- | --- |
| Playwright `add_style_tag` 가 넣는 인라인 `<style>`(6곳) | `add_test_style()`: `CSSStyleSheet.replaceSync` 와 `adoptedStyleSheets`(CSSOM, CSP 밖) |
| 대체 글꼴·깨진 색을 시험하려고 init 스크립트가 넣는 `<style>`(5곳), 늦게 오는 글꼴을 시험하는 `@font-face` `<style>`(1곳), 대비 검사의 고정 장치가 마크업과 함께 넣는 `<style>`(2곳) | 같은 생성 스타일시트. `@font-face` 는 `FontFace` API(`document.fonts.add`)로. 대비 검사의 규칙 수집이 생성 스타일시트도 읽게 했다(`document.adoptedStyleSheets`) |
| 스크린숏을 `data:image/png` 그림으로 해독해 화소를 읽는 도우미(7곳, `img-src`) | `createImageBitmap(new Blob([…]))` 로 해독(fetch가 아니라 CSP 밖) |
| 시험 글꼴 고정 장치가 뷰어 스크립트를 미루려고 바꿔 넣은 로더 스크립트 | 그 페이지의 정책에 로더의 해시를 더한다(`allow_page_scripts`). 로더가 다시 넣는 뷰어 스크립트는 원래 해시로 허용된다 |
| 실제 서버로 띄우는 시험(PDF 내려받기)이 받는 강제 헤더 | 문서 요청(`/`)만 가로채 Report-Only로 바꾼다(`report_only_documents`). 내려받기는 그대로 서버로 간다 |

### 그림 문서, 보기 전용 PDF, 비교 PDF, 도움말·시트

모두 같은 페이지 안이다. 강제 시험이 세 종류 문서를 PDF.js로 그렸다. 비교 PDF(`/api/revision-pdf` 를 바이트로 받아 같은 PDF.js로 그린다)와 도움말·휴지통·더보기 시트, 문서 시트는 전체 시험에서 보고 0건이다. 내려받기(`/pdf?download=1`)와 새 탭의 PDF는 문서 이동이라 이 정책이 다루지 않고, PDF 응답은 지금처럼 `frame-ancestors 'none'` 이다. 브라우저 내장 PDF 보기를 막지 않기 위해서다.

### 에이전트와 API

바뀌지 않는다. CSP는 브라우저가 문서에 적용하는 응답 헤더이고, 에이전트가 읽는 JSON·`pins.md`·PDF 응답의 헤더는 그대로다(시험이 정확한 값을 본다). 바뀌는 것은 HTML 응답 둘의 CSP 값이다. [api.md](../../handbook/api.md)의 "CSP에는 이 지시어 하나뿐" 문장은 고친다. 계약을 깨지 않고 더하는 변경이다.

### 브라우저 지원

| 기능 | Chromium | Firefox | Safari·iPadOS | 쓰임 |
| --- | --- | --- | --- | --- |
| `script-src`·`style-src` 해시(CSP2) | 40+ | 31+ | 10+ | 인라인 넷 |
| `base-uri`·`form-action`·`frame-ancestors`(CSP2) | 40+ | 35+ | 10+ | |
| `worker-src` | 59+ | 58+ | 15.5+ | 쓰지 않는다. `default-src 'self'` 로 덮어 이전 판도 같다 |
| `style-src-attr`·`-elem`(CSP3) | 75+ | 108+ | 15.4+ | 쓰지 않는다. 보고에는 이 이름이 실린다 |

iPadOS의 모든 브라우저는 WebKit이다. 이 기계에서는 WebKit이 시스템 라이브러리(libevent, gstreamer-plugins-bad, flite, avif, gst-libav) 부족으로 뜨지 않았다. `playwright install` 은 쓰지 않았다. WebKit 강제 시험은 CI의 엔진 작업(`firefox and webkit`, 그 작업만 의존성을 설치한다)에서 돈다. PR을 열어야 CI가 돌므로 그때 확인한다. 소유자의 iPad에서 테일넷 PoC를 열어 보는 것이 실기기 확인이다.

### Report-Only를 먼저 내지 않는다

추천은 첫 판부터 강제다.

- Report-Only는 보고를 받을 곳이 있어야 쓸모가 있다. 받을 곳이 없으면 위반은 사용자의 개발자 도구 콘솔에만 남고 아무도 읽지 않는다. 받을 경로(`report-to`)를 두면 남이 쓸 수 있는 새 쓰기 경로와 API가 생긴다. Limn의 작은 API와 맞지 않는다.
- 이 PoC의 근거가 그보다 강하다. 전체 브라우저 시험이 같은 정책 아래 두 엔진에서 보고 0건이고, 강제 시험이 Chromium·Firefox에서 통과했다(WebKit은 CI에서).
- 망가지면 되돌리는 길이 이미 있다. 이전 태그로 `limn update --ref <이전 태그>`([workflow.md](../../handbook/workflow.md) 긴급 경로). 상태·저장·API 변경이 없어 되돌려도 남는 것이 없다.

정책을 끄거나 Report-Only로 바꾸는 실행 인자도 두지 않는다. 끄는 길은 설정 표면을 늘리고, 켜 두는 것을 잊는 운영자를 만든다.

## 위험

- **새 인라인이 막힌다.** 누군가 `style=` 속성이나 속성 붙은 `<script>` 를 더하면 운영에서 조용히 막힌다. 꾸러미 페이지 시험(해시할 수 없는 꼴), 정적 가드, 브라우저 보고 0건 가드가 세 겹으로 잡는다. 규칙은 [viewer.md](../../handbook/viewer.md)에 적는다. 모양은 CSS 규칙이나 `el.style`(CSSOM)로 바꾼다.
- **브라우저 확장.** 페이지에 `<style>`·`<script>` 를 넣는 확장(다크 모드, 문법 검사)은 이 페이지에서 일부 막히고 콘솔에 보고가 남는다. 확장 자신의 격리 스크립트는 막히지 않는다. 뷰어의 동작에는 영향이 없다.
- **`img-src https:` 는 넓다.** 주입된 마크업이 있으면 아무 `https` 그림으로 "열었다"는 신호를 낼 수 있다. Markdown 렌더러는 그림을 불러오지 않는다(ADR-0025 D6). 좁히려면 사진을 Limn이 대신 받아 주거나 공급자 호스트 목록을 둬야 하는데, 공급자마다 달라 지금은 하지 않는다.
- **WebKit 미측정.** 위 §브라우저 지원.
- **HTML 화면이 지킬 것.** md-surface는 DOM API로 짓고 `style` 속성을 마크업으로 쓰지 않는다. markdown-it은 같은 출처에서 `import()` 한다. 파싱 Worker는 같은 출처의 파일로 띄운다. `blob:` Worker는 `worker-src blob:` 이 필요하므로 쓰지 않는다.

## 되돌리기

코드 되돌리기는 `limn/web/csp.py` 를 빼고 처리기·`Reply`·`viewer/routes.py` 의 정책 싣기를 지우는 것이다. CSS로 옮긴 네 곳은 그대로 두어도 화면이 같다. 운영에서는 이전 태그로 업데이트한다. 상태 파일, 핀, API, 설정 키는 바뀌지 않는다.

## 바꿀 곳

| 자리 | 바뀌는 것 |
| --- | --- |
| `src/limn/web/csp.py`(새) | `FRAME_ONLY`, `inline_hashes`, `page_policy` |
| `src/limn/web/reply.py` | `Reply.csp` |
| `src/limn/web/handler.py` | `_send(csp=)`, `end_headers` 가 페이지 정책 또는 `FRAME_ONLY`, 거절 페이지의 정책 |
| `src/limn/viewer/routes.py` | `GET /` 가 보내는 페이지로 정책을 구해 싣기(기억) |
| `viewer/index.html`, `js/repick.js`, `js/rebuild.js`, `css/responsive.css`, `css/composer.css`, `css/components.css` | `style` 속성 넷을 CSS로 |
| `tests/support/helpers_csp.py`(새), `helpers_browser.py`, `helpers_browser_font.py`, `conftest.py` | 헤더 넘기기(Report-Only), 보고 수집과 0건 가드, 시험 글꼴 로더 해시 |
| 시험 코드 | `add_style_tag` 6곳, `<style>` 주입 8곳, `data:` 해독 7곳, 대비 검사의 규칙 수집, 실제 서버 시험의 문서 가로채기, `brand-stripe` 를 보던 조립 시험 |
| `web/tests/test_csp.py`, `viewer/tests/test_viewer_csp.py`(새), `security/tests/test_security.py` | §시험 |
| Handbook | [architecture.md](../../handbook/architecture.md) §보안(페이지 CSP와 그 불변식), [api.md](../../handbook/api.md)·[operations.md](../../handbook/operations.md)의 응답 헤더 문장, [viewer.md](../../handbook/viewer.md)(인라인을 더하는 규칙, `style` 속성 금지), [verification.md](../../handbook/verification.md)(Report-Only 가로채기와 보고 0건 가드, 강제 시험), `SECURITY.md` 클릭재킹 항목 |
| `docs/adr/index.md` | ADR-0026 행 |

PoC 브랜치에는 Handbook·`SECURITY.md`·`docs/adr/index.md` 수정이 없다. 정식 구현(`feat/viewer-csp`)은 승인 뒤 최신 `main` 에서 새 브랜치를 내고, PoC의 코드와 시험 커밋을 다시 적용한 뒤 Handbook·`SECURITY.md`·CHANGELOG·ADR 색인과 이 표의 나머지를 더했다. PoC 브랜치 자체는 머지하지 않는다([workflow.md](../../handbook/workflow.md) 탐색 규칙).

## 실측

PoC `poc/viewer-csp` 에서 잰 값이다.

| 실행 | 결과 |
| --- | --- |
| 표본(PDF 내려받기, 뷰어 브라우저, 비교 PDF 확대) 정책 강제, 고치기 전 | 166 실패·115 오류. Playwright 기다림이 `eval` 위반으로 멈춤(166건). `style-src-attr` 332건(페이지 로드마다 2건, `#brand-stripe`·`#trash-h`) |
| 같은 표본, Report-Only 가로채기, 고친 뒤 | 117 통과. 뷰어 보고 0건, 시험 자신의 `eval` 보고만 |
| 전체 브라우저 시험 1회차(`-m browser -n 8`, Chromium·Firefox, WebKit 건너뜀), 뷰어 넷을 고친 뒤 | 1,383 통과, 20 건너뜀(WebKit 19, 원래 있던 Firefox 1), 오류 36. 오류는 모두 보고 0건 가드였고 원인은 시험 코드였다(`data:` 해독 236건, `<style>` 주입 27건). 뷰어 쪽 보고 0건. 시험 자신의 `eval` 보고는 약 2만 건 |
| 전체 브라우저 시험 2회차, 시험 코드를 고친 뒤 | 1,387 통과, 22 건너뜀(WebKit 21, Firefox 1), 실패 1, 오류 2. 오류 2는 대비 시험이 `<style>` 을 넣던 남은 두 곳이었다. 고친 뒤 그 파일과 목록 스크롤 파일이 8 통과, 보고 0건. 실패 1은 `test_viewer_list_scroll` 의 `loadPins()` 가 `false` 를 낸 것(겹친 읽기가 앞섬)으로 보고가 없었고, 단독으로 세 번 통과했다. CSP와 무관한 경쟁으로 보지만 기준 커밋에서 재현해 보지는 않았다. 뷰어 쪽 보고 0건, 시험 자신의 `eval` 보고 34,116건 |
| 강제 시험 `test_viewer_csp.py` | Chromium·Firefox 4 통과, 정적 가드 2 통과, WebKit 2 건너뜀(이 기계) |
| 변이 확인(따로 만든 임시 worktree) | `#brand-stripe` 의 `style` 속성을 되살리면 정적 가드, 강제 시험 4, 보고 0건 가드(PDF 내려받기 시험 4)가 실패한다. 테마 스크립트의 해시를 정책에서 빼면 헤더=바이트 시험 3, 강제 시험 4, 보고 0건 가드가 실패한다 |
| 테일넷 PoC(강제) | Chromium·Firefox 자동화로 원고와 보기 전용 PDF를 PDF.js로 그리고 도움말을 열었다. 위반 0건, 페이지 오류 0건, 색 띠는 실행의 색(`#a21caf`) 그대로 |
| 정책 계산 | 1.6 MB 페이지에 약 20 ms(실행마다 첫 `GET /` 에 한 번), 헤더 392바이트 |

## 이후 단계

- **Trusted Types**(`require-trusted-types-for 'script'`). 뷰어의 HTML sink는 `setHtml()` 하나라 잘 맞는다. 지원 브라우저가 고르지 않아 이번에는 넣지 않는다.
- **사진 대리 받기.** `img-src` 를 `'self'` 로 좁히는 길이다. 위험 §`img-src https:`.

## 소유자 결정

소유자가 2026-11-04에 아래 넷과 순서(5)를 모두 추천안대로 정했다. 물음은 결정 전의 모양 그대로 둔다.

1. **정책.** 위 §정책 그대로(해시, 엄격한 `style-src`, `img-src 'self' https:`). 대안: `style-src 'self' 'unsafe-inline'` 은 고칠 것이 줄지만 주입된 CSS의 유출 길이 남는다. 추천은 엄격.
2. **적용 방식.** 첫 판부터 강제(추천), 또는 한 판 동안 Report-Only. Report-Only는 받을 경로가 없으면 신호가 없다(§Report-Only를 먼저 내지 않는다).
3. **사람 사진.** `https:` 전체(추천), 공급자 호스트 목록, Limn이 대신 받기.
4. **거절 페이지.** 같은 방식의 정책을 단다(추천).
5. **순서.** ADR-0026 승인 → 정식 구현(위 §바꿀 곳, Handbook 포함) → WebKit을 포함한 CI → 릴리스. HTML 화면(계획 Task 5)은 이 릴리스 뒤에 넣는다.
