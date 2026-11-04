# ADR-0026: Limn의 HTML 페이지에 해시 기반 Content-Security-Policy를 강제한다

| | |
| --- | --- |
| **번호** | ADR-0026 |
| **제목** | Limn의 HTML 페이지에 해시 기반 Content-Security-Policy를 강제한다 |
| **상태** | 제안 |
| **결정일** | — |
| **결정자** | — (Limn 소유자의 결정을 기다린다) |
| **출처** | [설계(제안)](../superpowers/specs/2026-11-04-viewer-csp.md), [ADR-0025](0025-html-document-surface.md) D6, [HTML 문서 화면 설계](../superpowers/specs/2026-10-24-html-document-surface.md) §결정 5의 5번, 버리는 PoC 브랜치 `poc/viewer-csp` |

## 맥락

모든 응답의 CSP는 `frame-ancestors 'none'` 하나다. 클릭재킹은 막지만 뷰어 페이지에서 어떤 스크립트든 돈다. 지금 뷰어는 사람이 쓴 글을 이스케이프하는 `html``…`` 과 `setHtml()` 한 곳으로만 그려서 막힌 구멍은 없다. ADR-0025는 같은 출처에서, 읽는 사람의 신원으로, 남이 쓴 Markdown을 그리기로 했다. 렌더러의 규율이 한 번 무너지면 그 문서가 읽는 사람의 권한으로 Limn API를 부를 수 있다. 그래서 ADR-0025 D6은 뷰어 페이지의 `script-src` CSP를 HTML 화면보다 먼저, 따로 정하기로 했다. 이 ADR이 그 결정이다. 보안 경계 변경이므로 소유자 승인이 필요하다.

뷰어 페이지는 서버가 조립한다. 인라인 `<script>` 셋(테마, 언어, 뷰어 본체)과 인라인 `<style>` 하나이고, 실행마다 언어(스크립트)와 색(스타일시트)을 채운다. 인라인 이벤트 처리기는 없고, PDF.js는 같은 출처의 모듈과 worker를 `eval`·WebAssembly 없이 쓴다. 그래서 해시만으로 인라인을 모두 허용할 수 있다.

## 결정

| # | 결정 | 상태 |
| --- | --- | --- |
| D1 | Limn이 조립하는 HTML 페이지(뷰어 `GET /`, 브라우저에게 보이는 거절 페이지)는 자기 정책을 갖는다. `default-src 'self'; script-src 'self' <인라인 스크립트 해시>; style-src 'self' <인라인 스타일 해시>; img-src 'self' https:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'none'`. `'unsafe-inline'`·`'unsafe-eval'`·nonce·보고 주소는 없다 | 제안 |
| D2 | 그 밖의 응답(JSON, `pins.md`, PDF, 쪽 이미지, vendor 파일, 서비스 워커, 표준 라이브러리 오류 쪽)은 지금처럼 `frame-ancestors 'none'` 하나다. 에이전트 계약은 바뀌지 않는다 | 제안 |
| D3 | 해시는 보낼 문자열에서 잰다. 실행의 자리표시를 채운 뒤이고, HTML 토크나이저처럼 줄바꿈을 LF로 바꾼 뒤다. 브라우저가 다르게 읽을 수 있는 꼴(속성 붙은 `<script>`·`<style>`, 글 안의 다른 닫는 태그, `<!--`)은 해시하지 않고 거부한다. 계산은 `limn/web/csp.py` 한 곳이고, 뷰어는 `GET /` 가 보내는 그 문자열로 한 번 재어 기억한다 | 제안 |
| D4 | 페이지는 `style` 속성, 인라인 이벤트 처리기, `javascript:` 주소를 쓰지 않는다. 모양은 CSS 규칙과 CSSOM(`el.style`)으로 바꾼다. 지금의 `style` 속성 넷은 같은 값의 CSS 규칙으로 옮긴다 | 제안 |
| D5 | 첫 판부터 강제한다. Report-Only로 먼저 내지 않고, 정책을 끄는 실행 인자도 두지 않는다. 되돌림은 이전 태그로의 업데이트다 | 제안 |
| D6 | 시험은 세 겹이다. 헤더의 해시가 보낸 바이트의 해시와 같다는 단위 시험(따로 짠 파서로 읽는다). 모든 브라우저 시험이 서버의 정책을 Report-Only로 받아 보고가 하나라도 있으면 실패하는 가드. 강제 헤더 그대로 Chromium·Firefox·WebKit에서 뷰어를 띄우는 시험. 브라우저 시험이 지나지 않는 흐름은 템플릿과 JS 조각의 정적 검사가 덮는다 | 제안 |

### D1의 값을 고른 근거

`default-src 'self'` 는 연결·글꼴·worker·manifest·media를 같은 출처로 덮는다. `worker-src` 를 따로 두지 않는 까닭은 판마다 찾는 지시어가 달라서다. CSP2 브라우저(Safari 15.4 이하)는 worker를 `child-src` 를 거쳐 `default-src` 로, CSP3 브라우저는 `script-src` 를 거쳐 찾는다. 둘 다 `'self'` 로 끝난다. `'none'` 을 기본으로 두면 옛 Safari에서 PDF.js worker가 막힌다.

`style-src` 를 엄격하게 두는 까닭은 `img-src` 가 `https:` 로 넓기 때문이다. 주입된 CSS는 속성 선택자로 값을 읽어 `https` 그림 주소로 내보낼 수 있다. 고칠 것은 `style` 속성 넷이고, 둘은 모든 페이지 로드에서, 둘은 특정 흐름에서 났다.

`img-src https:` 는 사람 사진 때문이다. 사진 주소는 신원 공급자가 주는 `https` 주소이고(서버가 `https://` 만 받는다) 공급자마다 호스트가 다르다.

### D5를 고른 근거

Report-Only는 보고를 받을 곳이 있어야 신호가 된다. 받을 곳이 없으면 보고는 사용자의 콘솔에만 남는다. 받을 경로를 두면 남이 쓸 수 있는 쓰기 경로와 API가 하나 생긴다. 반면 이 결정의 근거는 실측이다. 전체 브라우저 시험(Chromium·Firefox)을 같은 정책 아래 돌려 뷰어 쪽 보고가 0건이었고, 강제 시험이 두 엔진에서 통과했다. 문제가 생기면 `limn update --ref <이전 태그>` 로 되돌린다. 상태·저장·API가 바뀌지 않아 되돌려도 남는 것이 없다.

### D6을 고른 근거

Playwright의 `wait_for_function()` 은 조건을 페이지 안에서 `eval` 로 돌린다(Chromium·Firefox 모두). 정책을 강제하면 시험이 첫 기다림에서 멈춘다. Report-Only는 강제와 같은 지시어로 같은 대상을 보고하므로 보고 0건은 강제해도 막히는 것이 0건이라는 뜻이다. 시험 자신의 `eval`(주소 없는 코드에서 막힌 `eval`)만 뺀다. 강제 자체는 `eval` 없이 기다리는 별도 시험이 본다. 그때까지 브라우저 시험의 가로채기 경로는 서버 헤더를 넘기지 않아, 지금의 `frame-ancestors` 조차 시험된 적이 없었다.

## Trade-off

- 인라인 `<script>`·`<style>` 을 더하거나 바꾸는 사람은 해시를 신경 쓰지 않아도 되지만, 속성 붙은 꼴이나 `style` 속성을 쓰면 꾸러미 페이지 시험·정적 검사·브라우저 가드가 실패한다. 뷰어 작성 규칙이 하나 는다.
- 페이지에 `<style>`·`<script>` 를 넣는 브라우저 확장(다크 모드, 문법 검사)은 이 페이지에서 일부 막힌다. 뷰어 동작에는 영향이 없다.
- `img-src https:` 는 넓다. 주입된 마크업이 있으면 아무 `https` 그림으로 열었다는 신호를 낼 수 있다. Markdown 화면은 그림을 불러오지 않는다(ADR-0025 D6).
- 시험 하네스가 커진다. 헤더를 넘기고, 보고를 모으고, 시험 코드가 인라인 `<style>`·`data:` 그림을 쓰지 않게 고쳤다.
- WebKit은 PoC 기계에서 띄울 수 없었다(시스템 라이브러리 부족). WebKit 강제 시험은 CI의 엔진 작업에서 처음 돈다.

## 대안

- **인라인 스크립트를 파일로 옮긴다**(`script-src 'self'` 만). 해시 계산이 없다. 그러나 조각을 이어 인라인 하나씩으로 내보내 `GET /` 를 응답 하나로 두는 조립 방식([architecture.md](../handbook/architecture.md) §2. 서버 런타임은 표준 라이브러리만 쓴다)을 바꾸고, 첫 그리기 전에 돌아야 하는 테마 스크립트가 요청 하나를 기다리며, 실행마다 다른 언어 값을 다른 길로 넘겨야 한다. 기각.
- **nonce.** 응답마다 새 값을 만들고 페이지를 다시 써야 한다. 페이지가 실행마다 고정이라 해시가 맞다. 기각.
- **`style-src 'unsafe-inline'`.** 고칠 것이 없지만 주입된 CSS의 유출 길이 남는다. 소유자가 고를 수 있는 대안으로 설계에 남긴다.
- **Report-Only 먼저.** D5. 받을 경로 없이는 신호가 없다.
- **`img-src` 호스트 목록이나 사진 대리 받기.** 공급자마다 호스트가 달라 목록은 깨지기 쉽고, 대리 받기는 새 경로와 캐시가 필요하다. 이후 단계.
- **Trusted Types.** 뷰어의 HTML sink가 하나라 잘 맞지만 지원 브라우저가 고르지 않다. 이후 단계.

## 결과

- 뷰어에 주입된 스크립트와 인라인 처리기는 돌지 않는다. 강제 시험이 페이지에 없던 스크립트 요소와 `onclick` 속성이 막히고 보고되는 것을 본다.
- ADR-0025의 HTML 화면(계획 Task 5)은 이 정책 아래에서 짓는다. markdown-it은 같은 출처에서 `import()` 하고, 파싱 Worker는 같은 출처의 파일로 띄운다(`blob:` Worker는 쓰지 않는다). 그린 문서는 `style` 속성을 마크업으로 쓰지 않는다.
- 승인되면 같은 변경에서 [architecture.md](../handbook/architecture.md)(보안 경계와 불변식), [api.md](../handbook/api.md)·[operations.md](../handbook/operations.md)(응답 헤더 문장), [viewer.md](../handbook/viewer.md)(인라인과 `style` 속성 규칙), [verification.md](../handbook/verification.md)(보고 0건 가드와 강제 시험), `SECURITY.md`(클릭재킹 항목), [index.md](index.md)를 고친다.
