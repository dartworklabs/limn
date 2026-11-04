# GET의 유지 쓰기와 외부 이동의 경계

> **상태: 제안 / 승인 대기 (2026-11-05).** [HTML 문서 화면 설계](2026-10-24-html-document-surface.md) §결정 5가 별도 승인으로 미룬 보안 설계다. [ADR-0027](../../adr/0027-get-write-guard.md)은 `제안`이다. 이 문서는 현재 구현을 바꾸거나 구현을 승인하지 않는다. 기준은 `09f66cf8`(Limn 0.4.48)이며 이후 main의 동작은 조사하지 않았다.

## 문제

다른 사이트의 글은 그림·스크립트·스타일·불투명 fetch와 페이지 이동으로 Limn GET을 만들 수 있다. 응답을 읽지 못해도 서버의 쓰기는 이미 끝난다. `/`에서 방문 쓰기만 막아도, 열린 뷰어는 같은 출처에서 전체 `/api/meta`와 `/api/pins`를 부른다(`viewer/js/boot.js:12–15`). 따라서 요청 하나의 Fetch Metadata만 검사하면 이동 뒤의 유지 쓰기가 남는다.

2026-11-04 Codex 3회차가 찾은 것은 정해진 유지 작업과 방문 기록이다. 공격자가 고른 핀 편집, 권한 상승, 응답 유출은 확인되지 않았다. 이 문서는 이를 임의 파일 쓰기나 계정 탈취로 부르지 않는다. Host 끝 점 정규화는 유지한다. 남의 이름을 막는 Host 검사와, 허용된 이름으로 보내는 남의 요청을 막는 문제는 다르다.

## 현재 코드 대조 — 쓰기 목록

경로는 쿼리와 문서 키를 합쳐 하나로 센다. `READ_PATHS`의 고정 경로 24개, 단일 핀 패턴 1개, `/pages/`와 vendor 세 종류의 경로군 4개로 **GET 경로·경로군 29개**다(`security/access.py:645–693`). **디스크를 바꿀 수 있는 경로는 9개**, 기능 고유의 캐시·프로세스까지 세면 12개다. 공통 인증 캐시까지 포함하면 29개 모두 조건부 메모리 쓰기가 있으므로, 아래의 ‘순수 읽기’는 그 공통 경계와 응답 버퍼·잠금·OS 접근 시각을 뺀 기능 동작을 뜻한다. 캐시와 영속 쓰기의 위험을 같은 것으로 세지 않는다. 파일:줄은 모두 `src/limn/` 기준이다.

| GET 경로 | 쓰는 것 | 조건 | 근거 파일:줄 |
| --- | --- | --- | --- |
| `/` | `people.json`, `.people.lock`, 방문 메모, CSP 해시 캐시 | 사람 신원이고 새 방문·이름/사진 변경·600초 경과. 해시는 처음 보는 페이지 | `viewer/routes.py:62,98–101`, `web/handler.py:256`, `security/people.py:135–175` |
| `/api/meta` | 방문 파일·메모, `pins.jsonl`·`pins.md`와 손상 원본 백업. 원고 mtime·입력 집합·그림 지도·판정 낱말·이벤트 읽기 캐시 | 전체 조회는 방문·핀 재동기화; `light=1`은 앞의 영속 쓰기 없음. 캐시는 해당 문서·파일의 첫 조회/변경 때 | `documents/http.py:20–40`, `documents/service.py:36–55`, `pins/application.py:85`, `builds/queries.py:143`, `builds/artifacts.py:964`, `documents/verdicts.py:262`, `collaboration/events.py:130–151` |
| `/api/pins` | 재동기화한 핀·파생 Markdown·손상 백업, 휴지통 파일·그 손상 백업, 정리 시각 메모, 그림 지도 캐시 | 원고 mtime이 핀의 `synced_at`보다 새로우면 위치가 그대로여도 `synced_at`을 고친 핀을 저장(`pins/location/position.py:267–284`, `pins/store.py:189–194`). anchor가 옮겨졌을 때와 옛 레코드에 anchor를 보충할 때도 저장. 정리 주기 1시간이 지나 만료/원본 그림자가 있을 때 휴지통 저장 | `pins/listing/routes.py:25`, `pins/listing/service.py:81`, `pins/store.py:144,165–207`, `pins/trash/service.py:136–174` |
| `/pins.md` | 위와 같은 핀·휴지통 쓰기·메모·지도 캐시 | 같은 조건. HTTP 응답용 Markdown 조립 자체는 저장하지 않음 | `pins/listing/routes.py:21`, `pins/listing/markdown.py:79`, `pins/store.py:165–207` |
| `/api/pins/{id}` | 재동기화한 핀·Markdown·손상 백업, 지도 캐시 | 모든 핀 snapshot을 먼저 읽으므로 다른 핀 재동기화도 저장. 없는 id의 404도 그 뒤에 결정 | `pins/listing/service.py:86–89`, `pins/runtime.py:241`, `pins/store.py:201` |
| `/api/people` | 재동기화한 핀·Markdown·손상 백업 | 후보 목록은 `participants(True)`로 snapshot. 이 경로 자체가 방문을 기록하지는 않음 | `collaboration/directory.py:50–53`, `pins/application.py:94–97` |
| `/api/overlaps` | 재동기화한 핀·Markdown·손상 백업 | 유효한 원고 범위를 파싱한 뒤 snapshot | `pins/location/http.py:53`, `pins/runtime.py:303–307` |
| `/api/revision-build` | 문서별 `revisions/` 폴더, Git 자식 프로세스, 이력 창·핀 범위 캐시·그림 지도 캐시 | 유효한 commit/base/pin으로 비교 spec을 만든 뒤 루트가 없으면 mkdir. GET은 컴파일 worker를 만들지 않음 | `revisions/routes.py:19–20`, `revisions/jobs.py:45–51,200–213`, `revisions/core.py:313,947,998` |
| `/api/revision-pdf` | 위와 같은 폴더·프로세스·캐시 | 비교 spec이 유효하면 아직 PDF가 없어 오류로 끝나도 루트 생성 가능 | `revisions/routes.py:21–22`, `revisions/jobs.py:322–343` |
| `/api/revisions` | Git 조회 프로세스, 이력 창 캐시, 그림 지도 캐시 | 이력 조회; 지도는 그림 문서일 때 | `revisions/service.py:33–46`, `revisions/core.py:313–335,524`, `builds/queries.py:273` |
| `/api/revision-diff` | Git 조회 프로세스(한도 있는 diff/blob 포함), 이력 창·핀 범위 캐시, 그림 지도 캐시 | 유효한 비교 인자. 디스크에 diff/비교 PDF를 저장하지 않음 | `revisions/service.py:48–54`, `revisions/core.py:656,694,947–983` |
| `/api/docs` | 원고 mtime·입력 집합·판정 낱말 캐시. summary가 읽는 지도 캐시도 가능 | 문서 요약의 캐시 미스. 핀 수는 동기화 없이 읽음 | `documents/service.py:57–64`, `documents/reads.py:40–64`, `builds/queries.py:143`, `documents/verdicts.py:262–282` |

공통 경계는 위 표와 아래 표의 모든 GET에 적용된다. Bearer가 있으면 `tokens_cache`, 프록시 사람 신원이면 `roles_cache`를 읽으며 캐시 미스 때 메모리를 바꾼다(`security/access.py:143–153,512–541`, `security/application.py:81–90`). 잘못된 사람 파일이나 옛 루프백 에이전트 설정은 경고 한 번 메모와 stderr도 바꿀 수 있다(`security/people.py:93`, `security/access.py:185–195`). 이것은 인증을 생략할 이유가 아니다.

| 나머지 GET 경로·경로군(17개) | 기능 동작과 근거 |
| --- | --- |
| `/api/build` | 빌드 상태 복사만. 컴파일·상태 저장 없음(`builds/http.py:18`) |
| `/pdf`, `/pages/{이름…}` | 이미 있는 PDF·PNG 바이트·ETag만. 쪽 렌더·캐시 폴더 생성 없음. 304도 읽기 뒤 결정(`builds/http.py:68–93`, `web/handler.py:119`) |
| `/api/outline-labels` | 공개된 aux 읽기·파싱만(`builds/queries.py:237–248`) |
| `/api/source`, `/api/snippet` | 검사된 원고 파일 읽기와 범위/사다리 계산. SyncTeX·컴파일 실행 없음(`documents/http.py:54`, `pins/location/http.py:44–51`) |
| `/api/pins/dropped` | 만료·그림자 사본을 응답에서 숨길 뿐 파일 정리 없음(`pins/listing/service.py:91–101`) |
| `/api/version`, `/sw.js`, `/md-parse.mjs` | 고정 값·꾸러미 글 응답(`viewer/routes.py:107–115`) |
| `/favicon.ico`, `/favicon-16.png`, `/favicon-32.png`, `/apple-touch-icon.png` | 꾸러미 아이콘 응답(`viewer/routes.py:102–106`) |
| `/vendor/pdfjs/{파일}`, `/vendor/markdown-it/{파일}`, `/vendor/pretendard/{파일}` | 허용된 꾸러미 파일 읽기(`viewer/routes.py:77–86,116–121`) |

**HEAD는 29개 경로 모두 미지원이다.** `Handler`는 `do_GET`·`do_POST`만 정의한다(`web/handler.py:305–311`). 표준 처리기의 501로 끝나 인증·GET dispatch·방문·유지 쓰기에 들어가지 않는다. HEAD를 나중에 GET과 묶으면 이 목록과 검증도 함께 바꾼다. 시작 때의 빌드·휴지통 정리·`pins.seq` 초기화, 감시 스레드의 발행은 요청 쓰기로 세지 않는다.

## 인증 방식별 위협 모델

공격자는 다른 웹 출처의 글과 URL·쿼리·반복 횟수를 고른다. Limn 응답·토큰·같은 출처 스크립트 실행권은 갖지 않는다. Host·Origin·입장 검사는 유지된다. GET에는 Origin이 없는 경우가 많고 Referer는 지워질 수 있다. SOP/CORS는 읽기를 막아도 이미 보낸 GET의 쓰기를 취소하지 않는다.

| 신원 방식 | 소유자의 브라우저로 가능한 요청과 신원 | 현실적인 최악의 결과·경계 |
| --- | --- | --- |
| `--auth local` | 루프백에 도달하는 헤더 없는 GET은 local owner. 하위 자원·이동·기동 요청 모두 가능. 프록시 흔적이 있거나 루프백 아닌 peer는 거절 | 소유자가 열지 않은 방문 기록, anchor 재동기화·Markdown 교체 I/O, 이미 만료된 휴지통/그림자 정리. 유효한 비교 인자를 알면 문서별 고정 루트 생성·Git CPU. 방문 파일은 사람별 행이며 매 요청 무한 append가 아님 |
| `--auth tailscale` | 브라우저가 테일넷 주소에 닿고 Serve가 사용자를 인증해 신원 헤더를 붙이면 그 사람의 신원. 악성 사이트가 헤더를 위조할 필요 없음. 직접 루프백은 기본 설정의 옛 agent 경로가 켜져 있을 때 agent이며, 토큰 파일 설정으로 꺼졌으면 401 | 허용된 사람은 위 9개 경로의 고정 유지 쓰기 가능. agent 경로에서는 방문은 남기지 않음. 비멤버/허용 목록 밖은 입장 거절. 태그 장치의 헤더 없는 프록시 요청은 기본 거절이며 선택 인자 예외를 소유자 신원으로 혼동하지 않음 |
| `--auth trusted-proxy` | 신뢰한 peer의 프록시가 브라우저 세션을 신원 헤더로 바꾸고 Host가 허용되면 그 사람. 쿠키·프록시의 SameSite/입장 정책에 따라 하위 자원은 막혀도 최상위 이동은 통과할 수 있음 | 프록시 정책에 종속되지만 앱은 통과한 사람의 같은 유지 쓰기를 허용. 신뢰하지 않은 peer/헤더 없는 직접 요청은 401. 임의 웹 글이 신원 헤더를 붙이는 공격과 구별 |
| Bearer agent token | 웹 글은 비밀을 알거나 응답을 읽지 않고 Authorization을 만들 수 없음. 토큰은 브라우저에 자동 부착되는 쿠키가 아님. 이미 토큰을 가진 에이전트의 직접 GET은 별개 | 토큰 보유자는 원래 허용된 유지·조회 수행, 방문 기록 제외. 토큰 탈취를 이 문제의 결과로 주장하지 않음. legacy 헤더 없는 agent와 구분 |

GET `/api/revision-build`라는 이름을 컴파일 시작으로 읽으면 안 된다. worker·latexmk·큰 비교 PDF는 **POST**만 시작한다(`revisions/jobs.py:216–319`). GET은 반복 Git 조회와 범위 추정 CPU를 쓸 수 있지만 비교 산출물 무한 증식은 확인되지 않았다. 루트는 문서별 하나이고 이력 창은 8개다. 재동기화는 원고 mtime이 핀의 `synced_at`보다 새로울 때만 다시 저장한다. 그때는 위치가 그대로여도 `synced_at`을 고쳐 `pins.jsonl`과 `pins.md`를 모두 교체하고, 옛 레코드의 anchor를 보충할 때도 저장한다. 원고를 고칠 때마다 다음 GET 한 번이 두 파일을 다시 쓴다는 뜻이며, 원고가 그대로면 GET을 반복해도 다시 쓰지 않는다. 휴지통 검사는 성공 뒤 1시간, 방문 갱신은 600초 간격이다. 반복 요청의 연결·스레드·읽기 CPU 비용은 남는다.

**로그도 남는 효과다.** 공격자가 고른 GET은 고정 유지 쓰기 밖에서 서버 로그를 늘릴 수 있다. `/api/pins/` 뒤에 숫자 5,000자리를 붙이면 `pins/listing/routes.py:31`의 `int()`가 실패해 500이 되고, `web/handler.py:298`이 요청마다 traceback을 stderr에 쓴다(리뷰에서 처리기 직접 호출 두 번에 누적 581→1,162바이트). 손상 레코드도 읽을 때마다 경고한다(`pins/store.py:123`). systemd 사용자 유닛이면 이 출력이 journal에 쌓이므로 저장량은 배포의 journal 한도를 따른다. B의 '영속 쓰기 없음'은 상태 폴더와 원고 트리의 파일·폴더를 뜻하고 로그는 포함하지 않는다. 로그는 아래 계약 1과 검증 계획의 상한·중복 억제로 따로 다룬다.

## 측정

질문은 두 가지다. 브라우저가 어떤 출처 신호를 보내는가, 그리고 외부 이동 뒤의 기동 요청이 그 신호를 보존하는가. 제품 파일은 고치지 않았다. 임시 실험은 이 질문을 재고 종료하며 방어 PoC로 쓰지 않는다.

### 방법과 한계

이 worktree에서 `uv sync` 후 `uv run limn serve --manuscript <임시 원고> --state-dir <임시 상태> --port <183xx> --auth local --bind 127.0.0.1 --no-build`로 실행했다. 짧은 일반 LaTeX 원고와 빈 상태를 사례마다 새로 만들었다. `--no-build`는 브라우저 유발 쓰기와 시작 컴파일을 섞지 않기 위한 것이다. 두 번째 서버는 `python3 -m http.server <포트> --bind 127.0.0.1 --directory <임시 페이지>`다. `localhost` 출처에서 `127.0.0.1` Limn으로 보내 cross-site를, 같은 `127.0.0.1`의 다른 포트로 same-site를 비교했다. 전자는 공개 인터넷에서 사설망으로 들어오는 브라우저 정책 시험이 아니다.

Playwright 1.63.0의 기본 headless Chromium 153.0.8010.12·Firefox 155.0를 썼고 설치는 하지 않았다. 공유 preview는 AppArmor sandbox 오류로 열리지 않아 직접 Playwright를 사용했다. 임시 `sitecustomize`로 표준 HTTP 처리기의 파싱 직후 **다섯 헤더와 method/path만** 기록했다. 헤더를 주입하거나 요청을 대리 전달하지 않았고 Authorization·쿠키·신원 헤더는 수집하지 않았다. 서버 시작이 끝난 뒤 상태의 경로·크기·mtime_ns·SHA-256을 비교하고, 요청 후 2초를 관찰했다. 하위 자원은 전체 `/api/meta`, 이동은 실제 `/`를 대상으로 삼았다. 링크·`location=`·GET form·`window.open`은 버튼/링크 클릭으로 시작했다. 자동 팝업·사용자 동작 없는 팝업 차단은 별도 미측정이다.

빈 핀 상태이므로 anchor 이동·만료 휴지통·손상 백업·비교 폴더는 이 브라우저 측정의 관찰 대상이 아니다. 그 조건부 효과는 위 코드 추적으로만 확인했다. 빈 상태에서 파일 차이가 없다는 것은 그런 효과가 없다는 증거가 아니다. WebKit, 실제 Tailscale Serve와 trusted-proxy 세션, 모바일·외부 공개 출처의 사설망 정책, 구형 브라우저, 헤더를 지우는 프록시는 미측정이다.

### 받은 헤더와 상태 차이

아래는 사례마다 포트를 분리한 cross-site 재측정의 결과다. `—`는 헤더 없음, `H`는 악성 페이지의 `http://localhost:<포트>/`, `L`은 뷰어의 `http://127.0.0.1:<포트>/`다. 두 엔진의 첫 요청 헤더가 모두 같았다. Origin은 모든 표본에서 없었다.

| 방식 | Sec-Fetch-Site | Sec-Fetch-Mode | Sec-Fetch-Dest | Origin | Referer | Limn 수신 수 Chromium / Firefox |
| --- | --- | --- | --- | --- | --- | --- |
| `<img>` → 전체 meta | cross-site | no-cors | image | — | H | 1 / 1 |
| 고전 `<script>` → 전체 meta | cross-site | no-cors | script | — | H | 1 / 1 |
| `<link rel=stylesheet>` → 전체 meta | cross-site | no-cors | style | — | H | 1 / 2 |
| `fetch(mode:no-cors)` → 전체 meta | cross-site | no-cors | empty | — | H | 1 / 1 |
| 링크 클릭 → `/` | cross-site | navigate | document | — | H | 19 / 21 |
| `location=` → `/` | cross-site | navigate | document | — | H | 19 / 21 |
| form GET → `/?` | cross-site | navigate | document | — | H | 19 / 19 |
| `window.open` → `/` | cross-site | navigate | document | — | H | 19 / 19 |
| 위 이동 뒤 전체 meta·pins | same-origin | cors | empty | — | L(폼은 `/?`) | 각 이동에서 meta 1회·pins 1회 |

수신 수는 2초 동안 Limn이 받은 전체 요청(정적 자원·favicon·기동 요청 포함)이다. Firefox의 link 사례 두 번째 요청은 favicon이다. 각 엔진 8개, 총 **16개 사례 모두 `.people.lock` 0바이트와 `people.json` 194바이트를 새로 만들었다**. 기존 파일 변경은 0개, 두 파일 합계는 사례당 194바이트다. 이 크기는 측정용 local 신원의 길이를 포함한 표본 크기이며 저장 한도가 아니다. 기동의 두 번째 방문 기록은 600초 메모에 걸려 별도 파일 증가가 없었다. `pins.jsonl`·휴지통은 비어 있어 추가 쓰기가 없었다. 전체 meta의 읽기 자체가 화면에 쓰이지 않거나 MIME 검사로 스크립트가 실행되지 않아도 서버 쓰기는 끝났다.

첫 탐색은 동일 포트를 즉시 재사용했다. 일부 사례에서 수신 0건이 나와 원인을 확정하지 않고 폐기했으며, 이를 차단 증거로 세지 않았다. 표는 사례별 다른 포트로 재현한 값이다. 원자료·버리는 하네스는 이 머신의 `/tmp/limn-get-write-probe-1105/unique.py`, `/tmp/limn-get-write-joshms1z/results.json`에 있다. 비밀은 수집하지 않았다. 이 경로는 배포 산출물이나 장기 보관 위치가 아니다.

같은 호스트 다른 포트의 재측정은 위 표에서 최초 요청의 Site만 `same-site`, Referer만 `http://127.0.0.1:<악성 포트>/`로 바뀌었다. Mode·Dest·Origin과 기동의 `same-origin/cors/empty`는 같았다. 이 16개 사례도 각각 같은 두 파일·194바이트를 새로 만들었고 기존 파일 변경은 0개였다. 요청 수는 Chromium의 img/script/link/fetch가 각각 1회, click/location/form이 각각 19회, open이 17회였다. Firefox는 앞 네 가지가 1/1/2/1회, 뒤 네 가지가 19/19/19/21회였다. 두 출처 관계를 합쳐 **32개 사례에서 32회 방문 파일 생성**을 관찰했다. 원자료는 `/tmp/limn-get-write-urzvj8sj/results.json`, 하네스는 `/tmp/limn-get-write-probe-1105/unique_same.py`다.

HEAD는 29개 경로·경로군의 대표 주소에 한 번씩 직접 보내 모두 501을 받았고 상태 디렉터리의 경로·크기·mtime이 동일했다. 브라우저 HEAD 측정은 아니며, 하네스는 `/tmp/limn-get-write-probe-1105/head.py`다.

## 결정과 추천

### 대안 비교

| 안 | 지키는 범위 | 깨지는 것·비용 |
| --- | --- | --- |
| **B. 모든 GET의 영속 쓰기를 없앤다(추천)** | 하위 자원과 이동 뒤 기동 모두 같은 읽기 계약. 헤더 없는 브라우저·curl·agent도 동일. HTTP에서 읽는 핀은 메모리에서 위치만 계산 | 재동기화와 휴지통 정리의 실행 주체 분리, 파생 파일의 갱신 지연 계약, 방문 의미 변경 필요. 구현 범위는 가장 크지만 별도 입장 상태는 없음 |
| A. Fetch Metadata로 유지 효과를 막고 외부 이동에는 이어 가기 화면 | cross-site/same-site 하위 요청 거절 또는 효과 없는 조회, 이동은 기동 전 차단. 이어 가기는 같은 출처 페이지에서 사람이 누른 POST 이후만 | 채팅·메일 링크마다 추가 클릭. 새 입장 흐름·만료·재전송·CSP 검토 필요. `Sec-Fetch-User`만 신뢰해 처음 이동을 통과시키면 악성 링크 클릭도 통과하므로 불충분. 헤더가 없는 사람 요청은 같은 화면이 필요 |
| C. 외부 이동에 쓰기 없는 뷰어를 준다 | 화면을 즉시 읽고, 해당 탭의 모든 기동·폴링을 효과 없는 조회로 보낼 수 있다면 양쪽 방어 | 쿼리 플래그만 붙이면 누락한 요청이 다시 씀. 서버가 탭/조회 능력에 경계를 묶고 직접 API도 보호해야 함. 같은 출처의 정상 탭과 외부 탭이 공유 쿠키의 ‘허용’ 하나로 섞이면 우회됨. 화면 상태·행동 전환 설계와 시험이 큼 |
| D. cross-site/same-site GET만 거절하거나 no-op | 직접 하위 요청만 방어. 순수 읽기까지 거절하면 자원 소비도 줄어듦 | 이동→same-origin 기동이 남으므로 단독 채택 불가. 정상 API 링크·pins.md 읽기가 403이 될 수 있음 |
| E. 지금의 조건부 쓰기를 멱등·상한만 강화 | 디스크 증가·반복 작업 비용을 더 좁힘 | 이미 방문 600초·정리 1시간·비교 루트 고정이라는 제한이 있음. 한 번의 의도 없는 쓰기와 이동 사슬은 그대로라 단독 해결 아님 |

### B의 제안 계약

1. **모든 GET·향후 HEAD는 영속 파일·폴더·작업을 만들거나 지우지 않는다.** 조회에 필요한 수명 한정 메모리 캐시와 한도 있는 Git 읽기 프로세스는 명시적 예외로 둔다. GET이 컴파일 worker·정리 worker를 예약해서 나중에 쓰게 하는 것도 금지다. 공통 HTTP 경계의 읽기/효과 구분을 각 기능 협력자까지 전달하고, GET 연결에서 저장 기능을 얻지 못하게 한다. 임의 쿼리의 `read_only=1`은 보안 경계가 아니다. 서버 로그는 이 보장에 들지 않는다. 대신 경로 인자(핀 번호 등)의 길이를 파싱 전에 제한해 예외로 가지 않게 하고, 같은 원인의 반복 오류·경고는 횟수 상한과 중복 억제를 둔다.
2. **뷰어 기동은 계속 GET만 한다.** `/`와 전체 meta에서 사람 방문 기록을 빼고, 이미 권한을 검사한 사람이 실제 변경 POST를 했을 때만 사람 파일을 갱신한다. 열기만 한 사람의 first_seen/last_seen은 더 이상 방문 사실을 뜻하지 않게 되므로, 이름과 API·멤버 안내의 의미를 승인 뒤 함께 정리한다. 자동 POST를 boot·폴링·언로드에 넣으면 문제를 옮길 뿐이므로 금지한다. 읽기 전용 참가자는 목록에 자동 등록되지 않는다. 기존 멤버 행·역할은 지우지 않는다.

   잃는 것은 구체적으로 이렇다. 멘션 후보와 사람 목록은 저장된 사람과 핀 참여자에서만 나온다(`collaboration/directory.py:43–53`, `security/people.py:179–217`). 그래서 **저장된 기록도 핀 참여 이력도 없는 새 독자**는 뷰어를 열어도 `/api/people`과 `limn member list`에 나타나지 않는다. 그 사람의 이름이나 전체 login을 `@`로 적어도 멘션·알림 대상으로 풀리지 않는다(`pins/mentions.py:39–99`). 되찾는 길은 둘이다. 편집할 수 있는 사람은 첫 실제 변경(핀 저장·답글 등) 뒤에 등록된다. `viewer` 역할은 변경 POST가 막혀 스스로 등록될 기회가 없으므로, 소유자가 `limn member add`로 명시 등록한다. 이미 있는 사람의 이름·사진도 읽기만으로는 갱신되지 않고 다음 실제 변경 때 바뀐다.
3. **핀의 현재 위치는 조회에서 계산하되 저장하지 않는다.** GET에는 기존의 필드·순서를 유지한다. 실제 변경 트랜잭션은 원래처럼 재동기화 후 원자적으로 저장한다. 파생 `pins.md`와 유지용 재동기화·휴지통 정리는 서버 시작과 요청과 무관한 주기에서 수행한다. 추천 주기는 60초이며, 겹치는 실행은 하나만 허용한다. 변경이 없으면 파일을 다시 쓰지 않고, 실패하면 원본을 보존해 다음 주기에 다시 시도한다. 휴지통 조회는 지금처럼 만료·그림자를 숨기므로 물리 삭제가 늦어져도 응답은 일관된다. HTTP `pins.md`는 즉시 계산하지만 디스크를 직접 읽는 에이전트는 정상 가동 중 최대 한 주기만큼 늦을 수 있다. 실행 시간이 주기를 넘거나 오류면 그보다 늦는다는 제약을 문서화한다. 과거 요청의 실행 수·신원을 이 주기에 넘기지 않는다.
4. **비교 GET은 기존 루트만 읽는다.** 루트가 없으면 상태는 idle, PDF는 기존의 not-ready 오류로 답한다. 폴더 생성·정리·컴파일은 권한을 받은 POST에만 둔다. 이력·diff의 Git 프로세스와 메모리 캐시는 입력·시간·출력·항목 수 한도를 유지하고, 동시 조회의 제한도 구현 계획에서 고정한다. 이 제안이 읽기 DoS까지 없앤다고 주장하지 않는다.
5. **Fetch Metadata는 보조 경계다.** 새 쓰기 경로를 GET에 두는 예외는 허용하지 않는다. `cross-site`·`same-site`라는 이유만으로 순수 읽기 GET을 막지는 않는다. 헤더가 없는 curl·구형 브라우저·agent도 같은 순수 조회를 받으며, 유효한 agent token은 기존 신원·권한 검사 뒤 POST를 쓴다. Referer·Origin 부재를 사람 승인으로 해석하지 않는다. B에는 새 POST 경로가 없다. 향후 별도 방문 POST를 원하면 정확한 Origin(포트 포함)과 Fetch Metadata, 헤더 없는 token 요청을 따로 정해야 한다. 지금 루프백 Origin 허용은 포트를 가르지 않으므로 새 민감 POST에 그대로 재사용하면 안 된다.

B는 북마크·주소 입력·메일·채팅 링크에서 같은 뷰어를 즉시 띄우고 agent·HTTP pins.md 독자의 헤더 요구를 늘리지 않는다. Tailscale Serve가 Fetch Metadata를 보존하지 않아도 GET의 영속 무효과는 유지된다. 기존 로컬 경로로 `pins.md`를 읽는 에이전트만 갱신 지연을 감수한다. 원고 작성·핀 편집 의미는 바꾸지 않는다.

A 또는 C처럼 사람이 보는 화면이나 조작이 달라지는 안을 고르면 [workflow.md](../../handbook/workflow.md) §화면 변경은 PoC를 먼저 보인다에 따라 **네 기기군 PoC를 머지 전에** 소유자에게 보인다. 이번 문서 작업에서는 만들지 않는다. B도 방문·참가자 안내 문구를 화면에서 바꾸게 되면 같은 게이트를 적용한다.

## 소유자 결정

아직 어느 항목도 승인되지 않았다. 각 물음의 첫 답이 추천이다.

1. **기본 방어:** B(모든 GET의 영속 쓰기 제거) / A(외부 이동 이어 가기) / C(탭별 쓰기 없는 뷰어). D·E는 단독 해법으로 추천하지 않는다.
2. **읽기만 한 사람:** 실제 변경 때만 사람 파일 기록 / 열기 방문 기능을 유지하되 별도 사람 동작과 화면을 설계. 전자를 고르면 기록도 핀 참여도 없는 새 독자는 사람 목록·멘션 후보에 없고 `@`로 적어도 알림이 가지 않는다. 편집자는 첫 변경 뒤, `viewer`는 소유자의 `limn member add` 뒤에 나타난다. 방문 시각(`last_seen`)은 '마지막으로 무언가를 바꾼 때'가 된다(§B의 제안 계약 2).
3. **유지 실행:** 시작과 60초 주기, 변경 없으면 무쓰기 / 별도 명시 POST만. 전자는 디스크 pins.md의 지연과 기존 정리의 무인 실행을 승인하는 선택이다.
4. **헤더 없는 클라이언트:** 순수 GET 허용, 기존 POST 신원·권한 유지 / 토큰 없는 모든 헤더 부재 요청 거절. 전자는 curl·구형 브라우저 호환을 지킨다.
5. **허용하는 읽기 효과:** 한도 있는 메모리 캐시·Git 조회만 예외 / 외부 출처 조회 자체도 차단. 전자는 영속 쓰기 방어와 읽기 자원 남용 방어의 범위를 분리한다.

## 비범위

제품 구현·테스트 변경·PoC 화면, Host 끝 점 거절, 인증 제공자 교체, 토큰·멤버 저장 형식 이관, 모든 POST CSRF 재설계, 임의 읽기 DoS 방어, CSP 변경, Markdown 화면의 승인 조건 변경은 하지 않는다. 논의 중인 안을 Handbook의 현재 채택값으로 옮기지 않는다. 승인 뒤 계획에서 현재 실재와 채택 목표를 나누어 관련 topic을 갱신한다.

## 검증 계획

문서 작업은 `uv run pytest tests/architecture -q`와 `git diff --check`를 돌린다. 제품 코드·테스트가 바뀌지 않았는지 경로로 확인한다. 새 ADR만 추가하고 승인된 번호 ADR은 수정하지 않는다. 문서 자체의 검증 결과는 아래에 적는다.

문서 검증: `uv run pytest tests/architecture -q` — 111개 통과(최종 10.09초), 건너뜀 없음. `git diff --check` 통과. Handbook topic·출판기를 고치지 않아 Handbook HTML 출판 게이트는 적용하지 않았다. 제품 코드·테스트 변경 없음. 검토 화면 서버는 만들지 않았으며 정본 Markdown 파일을 검토한다.

승인 뒤 구현에서는 위 29개 경로군의 등록 전수 목록을 검사한다. 사람·viewer·agent·입장 거절 × cross-site/same-site/same-origin/none/헤더 없음 × GET/HEAD를 교차하고, 디스크 내용뿐 아니라 inode·mtime·폴더 생성·프로세스 시작도 관찰한다. 정상·이동한 anchor·만료/그림자 휴지통·손상 레코드·빈/기존 비교 루트의 fixture를 둔다. 오류 응답과 304, 없는 단일 핀도 무쓰기여야 한다. 아주 긴 핀 번호·손상 레코드를 반복 요청해 로그가 상한 안에 머무는지도 본다. 허용한 Git 조회와 금지한 컴파일/유지 예약을 구별한다.

두 엔진에서 위 여덟 방식과 외부 이동 뒤 전체 기동·폴링을 다시 재고, GET 체인이 파일을 바꾸거나 쓰는 POST를 자동 발행하지 않음을 확인한다. 정상 핀 POST 뒤 저장·people 기록, 60초 유지의 겹침·변경 없음·실패 보존, 읽기 pins.md와 파생 파일 수렴도 확인한다. 권한·입장·경로 검사는 무쓰기보다 앞서 유지한다. 실제 Serve·신뢰 프록시·헤더 없는 클라이언트·WebKit은 별도 환경 게이트다. 화면을 바꾸면 네 기기군 PoC, 구현 마지막 커밋은 별도 Codex 리뷰를 거친다.

## 되돌리기

지금은 제안 문서만 추가하므로 실행 동작·상태 이관이 없다. 구현도 새 영속 승인 상태를 만들지 않는 B를 추천한다. 구현 뒤 이전 판으로 되돌리면 기존 상태를 읽되 GET 유지 쓰기와 방문 기록이 다시 생긴다. 이를 보안 개선이 유지되는 되돌리기로 안내해서는 안 된다. 유지 주기 장애는 원본을 보존하고 진단하며, GET 쓰기를 몰래 다시 켜는 인자는 두지 않는다.
