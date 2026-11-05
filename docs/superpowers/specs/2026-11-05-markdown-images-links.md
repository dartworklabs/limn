# Markdown 화면의 그림과 문서 사이 링크 — 원고 트리 안의 그림, 등록된 문서로 가는 상대 링크

> **상태: 제안(소유자 승인 전).** 결정 초안은 [ADR-0030](../../adr/0030-markdown-tree-images-and-document-links.md)(`제안`)이다. [HTML 문서 화면 설계](2026-10-24-html-document-surface.md)의 이후 단계 4다. [ADR-0025](../../adr/0025-html-document-surface.md) D6의 "그림은 불러오지 않는다"와, 상대 경로 링크를 글자로 두는 조항을 부분 대체한다. 보안 경계를 건너므로 [workflow.md](../../handbook/workflow.md) §기본 경로의 HARD-GATE에 따라 승인 뒤에만 `main` 에 넣는다.
>
> - 대조한 코드: `main` 770fa20c(0.4.50). 아래 `file:line` 은 모두 이 커밋 기준이다.
> - PoC: 브랜치 `poc/md-assets`. 추천안을 끝까지 구현했고 보안 시험이 붙어 있다. 승인되면 Handbook·SKILL·CHANGELOG를 더해 그대로 구현으로 쓴다(§PoC와 남은 일).
> - 형제 설계: 일반 텍스트·코드 문서([ADR-0029](../../adr/index.md), 브랜치 `md-text`)와 겹치지 않게 이 변경은 링크·그림 처리와 그림 읽기 경로만 건드린다.

## 문제

Markdown 화면은 그림을 하나도 불러오지 않는다. 그림 자리에는 `그림: <대체 글>` 만 선다. 설계 문서와 노트의 그림은 대개 같은 저장소 안의 PNG·SVG인데, 읽는 사람은 그 그림을 보려고 저장소를 따로 열어야 한다. 그림에 핀을 달 때도 무엇을 가리키는지 화면에서 확인할 수 없다.

문서 사이의 상대 링크(`[안내](docs/guide.md#설치)`)도 글자로 남는다. 같은 인스턴스에 그 문서가 탭으로 등록되어 있어도 링크로는 갈 수 없고, 탭을 찾아 눌러야 한다.

두 기능 모두 남이 쓴 글이 읽는 사람의 신원으로 무언가를 불러오게 만든다. 그래서 무엇을 어디서 불러오고, 어떤 링크를 여는지를 보안 경계로 정한다.

## 현재 코드 대조 (`main` 770fa20c)

| 무엇 | 지금 | 근거 |
| --- | --- | --- |
| 그림 | `image` 토큰은 대체 글 상자(`.md-img`)이고 팁에 주소를 적는다. 요청은 하나도 나가지 않는다 | `viewer/js/md-surface.js:266`, `viewer/css/md-surface.css:43`, [viewer.md](../../handbook/viewer.md) §Markdown 화면 |
| 링크 관문 | `mdHref` 가 허용 목록이다. 다른 출처의 `http(s)`, `mailto`, 문서 안 `#제목` 만 연다. 상대 경로·`//호스트`·같은 출처·루프백은 글자로 둔다 | `viewer/js/md-surface.js:288`·`:330`, [viewer.md](../../handbook/viewer.md) §링크와 관문 |
| 페이지 정책 | 뷰어 `GET /` 의 CSP는 `img-src 'self' https:` 다. 같은 출처 그림은 이미 허용된다. `data:` 그림은 허용하지 않는다 | `web/csp.py:75`, [ADR-0026](../../adr/0026-viewer-csp.md) D1 |
| 원고 트리의 읽기 | `file_in_tree` 가 경로를 풀어 원고 트리(`--manuscript`) 안인지, 점으로 시작하는 부분(`.git`·`.env`)이 없는지, 상태 폴더가 아닌지 본다. 읽을 때는 모든 단계를 no-follow로 열고 정규 파일인지 다시 본다(FIFO는 non-blocking). `read_bounded` 는 크기를 먼저 보고 한도까지만 읽는다 | `platform/files.py:102`·`:127`·`:200-201`·`:238` |
| 원문 경로 | `GET /api/source` 가 이 핸들로 1 MiB까지 읽는다. 모든 입장한 주체(owner·editor·viewer·agent)가 읽는다. 같은 트리의 어느 텍스트 파일이든 `/api/snippet?file=` 로 읽힌다 | `documents/http.py:44`, `documents/routes.py:27`, `security/access.py:670`·`:687` |
| 응답 헤더 | 모든 응답에 `nosniff` 가 붙는다. CSP는 페이지 정책이 없으면 `frame-ancestors 'none'` 하나다. `Reply` 에는 그 밖의 헤더 칸이 없다 | `web/handler.py:125`·`:142`·`:150`, `web/reply.py:10` |
| 문서 목록 | `/api/docs` 의 `path` 가 각 문서 main 파일의 트리 상대 경로다 | `builds/queries.py:155` |
| 문서 전환과 주소 | 전환은 `#doc=<키>` 를 `replaceState` 로 바꾼다. 그래서 탭 전환은 방문 기록을 남기지 않는다. 주소의 해시가 바뀌면(`hashchange`) 그 문서로 간다. 휴대폰의 뒤로 가기 레이어는 기록 항목 하나를 쌓는다 | `viewer/js/doc-tabs.js:9`·`:12`, `viewer/js/doc-switch.js:188`, `viewer/js/gestures.js:202` |
| 읽던 자리 | 다시 그릴 때 단 위끝의 원문 줄과 그 줄이 넘어간 px를 지킨다(`mdAnchor`·`mdRestore`). 그림이 나중에 커지는 경우는 없었다 | `viewer/js/md-surface.js:134`·`:136` |
| 변경 보기 | Markdown 문서의 이력 파일은 그 `.md` 하나다 | `builds/queries.py:273` |

## 제안

브라우저가 그리는 문서(Markdown)에 두 가지를 더한다.

1. **원고 트리 안의 그림을 보인다.** 그림 주소가 상대 경로이고, 문서 자기 경로를 기준으로 풀어 원고 트리 안에 머물고, 그림 접미사(`png`·`jpg`·`jpeg`·`gif`·`webp`·`svg`)를 가지면, 뷰어가 같은 출처의 새 읽기 경로 `GET /api/asset` 에서 받아 `<img>` 로 그린다. 서버는 받은 경로를 다시 검사하고, 원문을 읽을 때와 같은 검사된 핸들로 읽는다. 원격·`data:`·트리 밖 그림은 지금처럼 대체 글이고, 팁에 왜 불러오지 않는지 적는다.
2. **등록된 다른 문서로 간다.** 상대 링크를 같은 규칙으로 풀어, 그 경로가 이 인스턴스의 등록 문서이면 그 문서로 전환하고(Markdown이면 `#제목` 까지), 브라우저의 뒤로 가기로 돌아온다. 트리의 그림 파일을 가리키는 링크는 그 그림을 새 탭에서 연다. 그 밖의 상대 링크는 지금처럼 글자로 남고, 팁이 까닭을 말한다(`등록된 문서가 아니라 열지 않습니다`, `원고 밖을 가리켜 열지 않습니다`).

절대 주소의 허용 목록(`mdHref`)은 한 글자도 바꾸지 않는다. 뷰어가 새로 만드는 주소는 둘뿐이다. 뷰어가 검사한 트리 경로로 지은 `/api/asset?doc=…&path=…`, 그리고 등록 문서의 `#doc=<키>` 다. 문서의 글은 이 두 주소의 어느 글자도 정하지 못한다.

## 결정

| # | 결정 | 추천 | 소유자 몫 |
| --- | --- | --- | --- |
| 1 | 그림을 불러오는 범위 | 원고 트리(`--manuscript`) 전체 안, 문서 경로 기준 상대 경로만 | 예 — 보안 경계 |
| 2 | 읽기 경로 | `GET /api/asset?doc=&path=`. 정규화된 트리 상대 경로만 받고, 접미사·내용 허용 목록, 8 MiB, 원문 읽기와 같은 역할 | 예 — 새 경로(에이전트 계약에 더해진다), 한도 |
| 3 | SVG | 받는다. `<img>` 로만 그리고, 직접 열면 샌드박스 정책으로 무력하게 둔다 | 예 — 보안 경계 |
| 4 | 원격·`data:` 그림 | 계속 막는다 | 아니오 — ADR-0025 D6 그대로 |
| 5 | 배치·읽던 자리·핀·다크 모드 | 늦게 불러오기, 자리 맡기, 불러온 뒤 읽던 자리 되돌리기, 그림 테두리로 핀 표시, 다크 모드에서는 그림 뒤에 밝은 판 | 부분 — 다크 모드의 밝은 판 |
| 6 | 상대 링크 | 등록 문서는 전환(`#제목` 까지, 뒤로 가기 항목 하나), 트리의 그림은 새 탭, 나머지는 글자 | 예 — 뒤로 가기, 그림 링크 |
| 7 | 캐시·변경 보기·에이전트 계약 | 내용 ETag와 `no-cache`. 변경 보기는 그대로. `/api/docs`·핀·`pins.md` 그대로 | 아니오 |

### 결정 1. 그림을 불러오는 범위

**추천.** 문서 자기 경로를 기준으로 푼 상대 경로가 원고 트리 안에 머무는 그림만 불러온다. 뿌리는 인스턴스의 원고 트리 전체다. `/` 로 시작하는 경로는 트리의 뿌리 기준이다. 저장소의 Markdown에서 GitHub이 읽는 방식과 같다.

**근거.**

- 원고 트리는 이미 이 인스턴스가 읽는 사람에게 내놓는 범위다. 원문 경로와 `/api/snippet` 이 같은 트리의 어느 텍스트 파일이든 읽고, 모든 입장한 주체가 그것을 읽는다. 그림을 같은 트리로 묶으면 읽는 사람이 새로 닿는 파일 종류는 그림 다섯 형식뿐이다.
- 문서 폴더로 좁히면 흔한 배치가 깨진다. `docs/guide.md` 가 `../figures/plot.png` 를 쓰는 식이다. 그렇게 좁혀도 같은 사람이 같은 트리를 이미 읽으므로 얻는 보안 이득이 없다.

**대안.**

- **문서 폴더 아래만.** 위의 까닭으로 추천하지 않는다.
- **문서가 실제로 가리키는 그림만.** 서버가 Markdown을 파싱해야 한다. "서버는 Markdown을 파싱하지 않는다"([ADR-0025](../../adr/0025-html-document-surface.md) D5)와 부딪히고, 막는 것도 결정 1의 트리 경계와 다르지 않다.

### 결정 2. 읽기 경로 `GET /api/asset`

**추천.** `GET /api/asset?doc=<키>&path=<트리 상대 경로>`. 코드는 `documents/assets.py`(규칙)와 `documents/http.py` 의 `asset`(응답)이다.

- **경로 규칙(`asset_path`).** 뷰어가 이미 정규화해서 보내므로, 고칠 것이 있는 경로는 고치지 않고 거절한다(400 `bad_asset_path`). 비었거나 1,024자를 넘는 것, `/` 로 시작하는 것, 백슬래시·제어 문자가 든 것, 빈 부분·`.`·`..`·점으로 시작하는 부분이 있는 것, 그림 접미사가 아닌 것이 여기 든다. 쿼리는 한 번만 디코드된다. 두 번 인코딩한 `%252e%252e` 는 `%` 가 든 파일 이름일 뿐이다.
- **트리 검사.** 통과한 경로는 원문 경로와 같은 `parse.source_file`(`file_in_tree`)로 검사한다. 트리 밖으로 나가는 링크(파일이든 폴더든), 상태 폴더, 정규 파일이 아닌 것은 다른 파일 경로와 같은 400(`file_outside_manuscript`·`file_not_found`)이다. 트리 안을 가리키는 링크는 그 파일이다. 원문 경로와 같다.
- **형식.** 응답의 `Content-Type` 은 접미사로만 정한다. 내용이나 시스템 표에서 정하지 않는다. 내용은 그 형식의 시그니처로 시작해야 한다(PNG·JPEG·GIF·WebP). SVG는 UTF-8 글이고 첫 요소가 `<svg>` 여야 하며, 내부 DTD(엔티티 정의)를 갖지 않아야 한다. 아니면 415 `asset_not_image` 다. `.png` 라는 이름의 HTML이 그림 응답으로 나가지 않게 하려는 것이다.
- **한도.** 8 MiB. 크기를 먼저 보고, 넘으면 읽지 않고 413 `asset_too_large`(`bytes`·`limit`)다. 스크린숏과 그림은 대개 수백 KB다.
- **역할.** `READ_PATHS` 에 더한다. 원문 경로와 같아서 owner·editor·viewer·agent가 읽고, 헤더 없는 테일넷 요청·모르는 피어·다른 Host·Origin은 원문 경로와 같은 답을 받는다.
- **헤더.** `nosniff`(이미 모든 응답에 붙는다), 그림 자신의 CSP(결정 3), `Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: private, no-cache` 와 내용 해시 ETag(결정 7)다. CORP는 `Reply` 에 선택 칸 `resource_policy` 를 더해 보낸다.
- **쓰지 않는다.** 검사된 디스크립터에서 제한된 읽기를 한 번 할 뿐이다. 어떤 GET도 영속 상태를 바꾸지 않는다는 불변식([architecture.md](../../handbook/architecture.md) §10. 어떤 GET도 영속 상태를 바꾸지 않는다)을 지킨다.

**대안: 경로형 주소(`/tree/<경로>`).** `<img src>` 를 상대 경로 그대로 둘 수 있어 보기에는 단순하다. 그러나 페이지 기준으로 풀리는 상대 주소, `%2F` 를 서버와 프록시가 저마다 다르게 다루는 문제, 경로 정규화가 프록시에서 한 번 더 일어나는 문제를 떠안는다. 쿼리 한 칸이면 이 문제가 없다.

### 결정 3. SVG

**추천.** 받는다. 뷰어는 SVG를 `<img>` 로만 그린다. `<img>` 안의 SVG는 스크립트를 돌리지 않고 외부 자원도 받지 않는다. 다만 사용자가 그림 주소를 새 탭으로 열면 SVG는 같은 출처의 문서가 된다. 그래서 모든 그림 응답에 다음 정책을 단다.

`default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox; frame-ancestors 'none'`

`sandbox` 는 그 문서에 불투명한 출처를 주고 스크립트를 막는다. `default-src 'none'` 은 아무것도 받지 않게 한다. SVG 안의 인라인 스타일과 `data:` 그림은 그대로 그려진다. 래스터 그림에도 같은 정책을 단다. 해가 없고, 규칙이 하나로 남는다.

**대안.**

- **SVG를 받지 않는다.** 가장 단순하다. 그러나 흐름도와 다이어그램은 SVG가 흔하다.
- **`Content-Disposition: attachment`.** 새 탭으로 열면 내려받기가 되어 그림을 볼 수 없다. 샌드박스가 같은 위협을 막으면서 볼 수 있게 둔다.

### 결정 4. 원격·`data:` 그림

**추천(바꾸지 않음).** 계속 막는다. 원격 그림은 누가 언제, 어느 IP에서 문서를 열었는지 제3자에게 알린다. `data:` 그림은 페이지 정책의 `img-src` 에 없다. 열려면 CSP를 넓혀야 한다. 둘 다 대체 글로 남고, 팁이 까닭을 말한다(`원격 그림은 불러오지 않습니다`, `이 그림은 불러오지 않습니다`, `원고 밖의 그림은 불러오지 않습니다`, 서버가 거절하면 `그림을 불러오지 못했습니다`).

### 결정 5. 배치·읽던 자리·핀·다크 모드

**추천.**

- **늦게 불러오기.** `loading="lazy"`, `decoding="async"`. 크기를 모르는 그림은 12rem×8rem 자리를 맡는다. 자리가 없으면 늦게 불러오기가 지켜볼 상자도 없다.
- **크기.** 그림은 제 크기로 서되 단 폭(최대 46rem)을 넘지 않는다. 그림 하나뿐인 문단(`md-fig`)은 그림을 제 줄에 세운다.
- **읽던 자리.** 그림이 불러와져 자리 크기가 바뀌면, 마지막 스크롤이나 그리기 때의 읽던 자리(`mdAnchor`)로 되돌린다. 그래서 읽는 줄 위의 그림이 커져도 읽던 글이 밀리지 않는다. Chromium과 Firefox는 브라우저의 스크롤 고정(`overflow-anchor`)이 이미 같은 일을 한다. 고정이 없는 브라우저에서는 뷰어가 맡는다. 시험은 브라우저 고정을 끄고 잰다. 불러온 크기는 탭 안에서 기억한다(`MD_PIC_SIZE`). 원문이 바뀌어 다시 그리거나 문서로 돌아오면 그림이 처음부터 제 크기로 선다.
- **줄 대응.** 그림은 제 원문 줄의 줄 span 안에 선다. 대체 글이 줄을 넘는 그림은 지금 규칙대로 그 범위 전체로 물러선다([ADR-0025](../../adr/0025-html-document-surface.md) D7). 그림을 누르면 그 줄을 고르고, 사다리의 기본은 그 문단(블록)이다. 그림만의 블록 종류나 핀 `kind` 는 새로 만들지 않는다. 그래서 핀 계약이 그대로다.
- **핀 표시.** 그림 뒤에 깐 상태색은 보이지 않는다. 그래서 핀이 있는 줄의 그림에는 상태색 3px 테두리를, 고른 줄의 그림에는 `--primary` 2px 테두리를 두른다. 번호 배지는 지금처럼 단의 왼쪽 여백에 선다.
- **다크 모드.** 그림 뒤에 밝은 판(`--image-plate`, 다크 `#fafafa`, 라이트 `transparent`)을 둔다. 투명 바탕에 검은 선으로 그린 그림이 어두운 단에서 사라지지 않게 하려는 것이다.

**대안(다크 모드).** 그대로 둔다. GitHub과 같지만 투명 PNG·SVG의 검은 선이 사라진다. 색을 반전한다. 사진의 색이 망가진다.

### 결정 6. 상대 링크

**추천.**

- **등록된 문서.** 문서 자기 경로를 기준으로 푼 경로가 `/api/docs` 의 어느 문서의 `path` 와 같으면 그 문서로 간다. 종류는 가리지 않는다(Markdown, LaTeX main, 보기 전용 PDF, 그림 지도). `#제목` 은 Markdown 문서에서만 그 제목까지 간다. GitHub의 제목 이름 규칙을 쓴다. 다른 문서로 가는 링크는 `data-act="md-doc"`(`role="link"`, Tab으로 닿고 Enter로 간다)이다.
- **뒤로 가기.** 링크로 간 전환만 방문 기록에 항목 하나(`#doc=<키>`)를 더한다. 브라우저의 뒤로 가기는 지금의 `hashchange` 길로 떠난 문서에 돌아가고, 그 문서는 떠날 때의 읽던 자리로 열린다. 탭 전환은 지금처럼 항목을 더하지 않는다. 휴대폰의 뒤로 가기 레이어가 열려 있으면 항목을 더하지 않는다. 그 레이어의 항목이 맨 위에 있어야 하기 때문이다.
- **트리의 그림.** 그림 접미사를 가진 트리 경로는 새 탭(`noopener noreferrer`)에서 `/api/asset` 으로 연다. SVG는 결정 3의 정책 아래 무력하다.
- **그 밖.** 트리 안이지만 등록되지 않은 파일, 트리 밖, 점으로 시작하는 부분은 글자로 남고 팁이 까닭을 말한다. 형제 설계([ADR-0029](../../adr/index.md))가 일반 텍스트 문서를 등록하게 되면, 그 파일로 가는 링크는 이 규칙에 따라 저절로 열린다.

**대안.**

- **뒤로 가기 항목 없음.** 탭 전환처럼 `replaceState` 만 쓴다. 단순하지만 링크를 따라간 사람이 뒤로 가기를 누르면 Limn을 떠난다.
- **그림 링크도 글자로.** 그림은 이미 본문에 보이므로 손실이 작다. 다만 큰 그림을 제 크기로 보고 싶을 때 길이 없다.

### 결정 7. 캐시·변경 보기·에이전트 계약

- **캐시.** `Cache-Control: private, no-cache` 와 내용 해시(BLAKE2b 96비트) ETag. 다시 볼 때마다 묻고, 바뀌지 않았으면 304다. 한 문서 안에서 다시 그릴 때는 브라우저의 그림 캐시가 같은 주소를 다시 받지 않는다. 그 자리에서 고친 그림은 다음에 열 때 보인다. 탭을 연 채로 그림만 바뀐 경우를 바로 따라가지는 않는다(§남은 일).
- **변경 보기.** 그대로다. Markdown 문서의 이력은 그 `.md` 파일 하나다. 그림만 바꾼 커밋은 그 문서의 변경 보기에 나오지 않는다. 그림의 전후 비교는 이번 범위 밖이다.
- **에이전트 계약.** `/api/docs`·`/api/meta`·핀 레코드·`pins.md` 는 그대로다. 새 경로 `GET /api/asset` 하나와 이유 코드 넷(`bad_asset_path`·`asset_not_image`·`asset_too_large`·`asset_unreadable`)이 더해진다. [api.md](../../handbook/api.md) §화면·PDF·정적 파일에 적는다. 에이전트는 이 경로를 쓸 일이 없다. 그림 줄의 핀은 평범한 줄 핀이다.

## 보안

렌더한 문서는 뷰어와 같은 출처에서 읽는 사람의 신원으로 돈다. 이 변경으로 문서가 정할 수 있게 된 것은 두 가지다. 같은 출처에서 그림을 불러오게 하는 것과, 다른 등록 문서로 전환하게 하는 것이다.

| 위협 | 막는 것 | 지키는 시험 |
| --- | --- | --- |
| 경로 탈출: `..`, 절대 경로, 백슬래시, 한 번·두 번 인코딩한 `..` | 서버는 정규화된 경로만 받고(`asset_path`), 그다음 트리 검사(`file_in_tree`) | `AssetPathRule`, `AssetRoute.test_no_path_leaves_the_tree`, 뷰어 쪽 `test_a_relative_reference_resolves_in_the_tree_or_says_why_not` |
| 링크로 탈출: 트리 밖을 가리키는 파일·폴더 링크, 검사 뒤 바꿔치기 | 경로를 풀어 트리 안인지 보고, 읽을 때 모든 단계를 no-follow로 연다 | `test_no_path_leaves_the_tree`(`leak.png`, `out/`) |
| 비밀 파일: `.git`, `.env`, 상태 폴더(사람·토큰 기록) | 점으로 시작하는 부분과 상태 폴더 거절 | `test_no_path_leaves_the_tree`, `test_the_state_folder_inside_the_tree_is_refused` |
| 특수 파일: FIFO, 폴더 | 정규 파일만, non-blocking open | `test_what_is_not_an_image_file_is_refused` |
| 위장 내용: `.png` 라는 이름의 HTML, `.svg` 라는 이름의 글 | 시그니처 검사(415), 접미사로 정한 `Content-Type`, `nosniff` | `AssetKind`, `test_what_is_not_an_image_file_is_refused`, `test_an_image_is_sent_as_its_suffix_says…` |
| 직접 연 SVG의 스크립트(같은 출처 문서가 되어 API를 부름) | 그림 응답의 `sandbox; default-src 'none'` | 브라우저 `SvgOnItsOwn`: 정책 아래에서 제목이 그대로이고 출처는 `null` 이며 요청이 0건이다. 정책을 뺀 대조에서는 스크립트가 돈다 |
| `<img>` 안 SVG의 스크립트·외부 그림 | 브라우저 규칙(그림 문맥) | `TreeImages`: SVG의 `fetch`·`onload` 요청 0건, 다른 호스트 요청 0건 |
| 원격 추적 그림 | 렌더러는 원격 `src` 로 `<img>` 를 만들지 않는다. 렌더러가 짓는 그림 주소는 `mdAssetUrl` 하나다 | `TreeImages`(다른 호스트 0건), `test_an_image_loads_only_from_the_tree…`, `test_the_image_address_is_built_from_the_checked_path…` |
| 다른 사이트의 탐침: `<img src="https://<limn>/api/asset?…">` 로 파일이 있는지, 크기가 얼마인지 알아냄(테일넷은 신원이 저절로 붙는다) | `Cross-Origin-Resource-Policy: same-origin` | 헤더 시험(`test_an_image_is_sent…`). 브라우저가 실제로 막는지는 아직 시험하지 않는다(§남은 일) |
| 문서가 Limn API를 부르는 링크 | 절대 주소 관문은 그대로다. 뷰어가 짓는 주소는 `/api/asset` 과 `#doc=` 뿐이다. `/api/pins` 같은 상대 경로는 등록 문서도 그림도 아니므로 글자다 | `test_a_link_opens_a_registered_document_an_image_or_nothing`(`/api/pins`, `/api/asset?…`, 자기 출처, 루프백) |
| 큰 파일·메모리 | 크기를 먼저 보고 8 MiB까지만 읽음 | `test_the_size_limit_holds_at_its_edge` |
| GET 쓰기 | 제한된 읽기 한 번 | `test_no_answer_writes_anything`(트리·상태 폴더·트리 밖의 바이트와 mtime) |
| 권한 | 원문 경로와 같은 역할 규칙 | `test_every_admitted_principal_reads_it…` |
| 그림 수 폭주 | 늦게 불러오기, 기존 요소 한도 60,000 | 기존 한도 시험 |
| 픽셀 폭탄(작은 파일, 거대한 화면) | 브라우저의 디코드 한도에 맡긴다. 바이트 한도만 둔다 | 없음(§남은 일) |

**읽는 범위가 넓어지는 것.** viewer 역할도 문서가 가리키지 않은 트리의 그림을 경로로 받을 수 있다. 이것은 같은 사람이 `/api/snippet` 으로 트리의 텍스트 파일을 이미 읽을 수 있는 것과 같은 경계다. 트리 안에 두지 말아야 할 그림이 있다면 그것은 지금도 원고 트리 설정의 문제다.

## 바꿀 곳

| 영역 | 파일 | PoC |
| --- | --- | --- |
| 그림 읽기 규칙 | `src/limn/documents/assets.py`(새로): `asset_path`, `asset_kind`, `read_asset`, `ASSET_POLICY` | 됨 |
| 응답과 경로 | `documents/http.py`(`asset`), `documents/routes.py`, `security/access.py`(`READ_PATHS`) | 됨 |
| CORP 헤더 | `web/reply.py`(`resource_policy`), `web/handler.py`(`_send`) | 됨 |
| 뷰어: 그림 | `viewer/js/md-surface.js`(`mdRelPath`, `mdImgPath`, `mdImage`, `mdPicLoad`, `mdPicError`, `MD_PIC_SIZE`, `MD.spot`), `viewer/css/md-surface.css`, `viewer/css/tokens.css`(`--image-plate`) | 됨 |
| 뷰어: 링크 | `md-surface.js`(`mdTarget`, `mdLink`, `mdGoDoc`, `mdGoSlug`, `MD.headTo`), `viewer/js/events.js`(`md-doc`) | 됨 |
| 문구 | `viewer/ui_en.json`(팁 여덟, 이유 코드 넷) | 됨 |
| 시험 | `documents/tests/test_assets.py`, `viewer/tests/test_md_tree_refs.py`, `viewer/tests/test_viewer_markdown_assets.py`, 기존 시험 두 곳(원격 그림 팁 문구, 경로 목록) | 됨 |
| Handbook | [viewer.md](../../handbook/viewer.md) §Markdown 화면(그리기의 그림 항목, §링크와 관문 표), [api.md](../../handbook/api.md) §화면·PDF·정적 파일(새 경로·이유 코드), [architecture.md](../../handbook/architecture.md)(읽기 경로 목록), [verification.md](../../handbook/verification.md)(새 시험), index.md 파일 지도 | 승인 뒤 |
| SKILL·README·CHANGELOG | 두 SKILL에 "그림은 트리 안의 것만 보인다" 한 줄(에이전트 행동은 그대로), CHANGELOG | 승인 뒤 |

## PoC와 남은 일

**PoC가 하는 것.** 위 결정의 추천안 전부. 서버 경로, 뷰어의 그림·링크·뒤로 가기·읽던 자리·핀 표시·다크 모드, 보안 시험. 테일넷 시안은 `/tmp/limn-poc-assets/repo` 의 데모 문서 넷(README, 사용 안내, 계획 노트, LaTeX 본문)이다. 데모에는 트리 안의 PNG·JPEG·WebP·GIF·SVG, 원격 그림, 트리 밖을 가리키는 그림과 링크 파일, `.git` 안 그림, 가짜 PNG, 등록되지 않은 파일로 가는 링크가 들어 있다.

**남은 일(구현 단계).**

- Handbook·SKILL·CHANGELOG(§바꿀 곳).
- Firefox에서 그림·링크 시험 한 벌(기존 `CoreFirefox` 처럼). WebKit은 이 기계에서 뜨지 않아 CI의 엔진 작업에서 처음 돈다. 브라우저 스크롤 고정이 없는 WebKit에서 읽던 자리 되돌리기를 실기기로 확인한다.
- CORP가 다른 출처의 `<img>` 를 실제로 막는지 브라우저 시험(두 출처를 띄우는 하네스가 필요하다).
- 픽셀 폭탄: PNG·GIF 머리의 가로·세로를 읽어 거절할지(예: 1억 화소)를 잰 뒤 정한다.
- 탭을 연 채 그림 파일만 바뀌면 다음에 열 때 보인다. 바로 따라가려면 원문의 `src_mtime` 처럼 그림의 지문을 폴링해야 한다. 지금은 하지 않는다.
- 304를 내기 전에도 파일을 끝까지 읽는다. 그림이 커지면 `If-None-Match` 를 먼저 보고 디스크립터의 지문(mtime·크기·inode)으로 답하게 바꾼다.

## 검증

- **경로 시험** `src/limn/documents/tests/test_assets.py`: 경로 규칙, 형식 시그니처, 응답과 헤더, 304, 탈출 경로 전부, 상태 폴더, 특수 파일, 위장 내용, 8 MiB 경계, 역할, 쓰기 없음.
- **순수 시험** `src/limn/viewer/tests/test_md_tree_refs.py`: 상대 경로 풀기(인코딩·`..`·점 부분·뿌리), 그림 소스 분류, 링크 관문(등록 문서·그림·글자, 절대 주소는 그대로), 뷰어와 서버의 접미사 목록 일치, 뷰어가 짓는 주소를 서버가 그대로 받는지.
- **브라우저 시험** `src/limn/viewer/tests/test_viewer_markdown_assets.py`: 트리 그림을 그리고 나머지는 까닭을 말하는지, 다른 호스트 요청 0건, 직접 연 SVG가 무력한지(정책을 뺀 대조 포함), 그림이 불러와져도 읽던 줄이 2px 안에 있는지(되돌리기를 빼면 772px 어긋난다), 그림 줄 핀의 테두리와 그림 누르기, 문서 링크·`#제목`·뒤로 가기.
- **기존 게이트.** `uv run pytest -q -n 4 -m "not browser and not tex"`, Markdown 브라우저 시험(`src/limn/viewer/tests/test_viewer_markdown*.py`), ruff, mypy, `npm run typecheck`, strict ratchet.
- **화면.** 네 기기군 전후 캡처(데스크톱과 폴더블은 라이트·다크)를 소유자에게 보인다([workflow.md](../../handbook/workflow.md) §화면 변경은 PoC를 먼저 보인다).

## 열린 결정

| 결정 | 추천 | 한 줄 까닭 |
| --- | --- | --- |
| 그림의 뿌리 | 원고 트리 전체(문서 폴더로 좁히지 않음) | 같은 사람이 같은 트리를 이미 읽고, 좁히면 `../figures/` 배치가 깨진다 |
| SVG | 받고, 직접 열면 샌드박스 | 다이어그램은 SVG가 흔하고, 정책 하나로 직접 열기의 스크립트를 막는다 |
| 그림 한도 | 8 MiB | 스크린숏·그림은 대개 수백 KB이고, 넘으면 읽지 않고 거절한다 |
| 다크 모드 | 그림 뒤 밝은 판 | 투명 바탕의 검은 선 그림이 어두운 단에서 사라지지 않는다 |
| 문서 링크와 뒤로 가기 | 링크로 간 전환만 기록 항목 하나 | 링크를 따라간 사람이 뒤로 가기로 돌아오고, 탭 전환은 지금 그대로다 |
| 그림 파일 링크 | 새 탭에서 그림 | 큰 그림을 제 크기로 볼 길이 생기고, SVG는 정책 아래 무력하다 |
