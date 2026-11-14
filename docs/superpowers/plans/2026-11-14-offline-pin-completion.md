# 계획: 오프라인 핀 — 남은 일과 작업 단위의 계약

설계는 [`../specs/2026-11-14-offline-pin-capture-design.md`](../specs/2026-11-14-offline-pin-capture-design.md), 현재 규칙은 [`../../handbook/viewer.md`](../../handbook/viewer.md) §끊긴 채 보기와 핀 쌓기다. 이 문서는 남은 일을 네 단위로 나누고, 단위들이 함께 따르는 계약을 한곳에 둔다. 브리프는 이 파일을 가리킨다.

베이스는 브랜치 `t3/offline-pin-sync`다. 각 단위는 자기 워크트리에서 **자기 파일만** 고치고 커밋까지 한다. push·PR·머지·배포는 통합 담당이 검증한 뒤에 한다.

## 단위와 파일 소유

| 단위 | 하는 일 | 고쳐도 되는 파일 |
| --- | --- | --- |
| **S 서버** | `POST /api/pin` 멱등 키(§계약 1) | `src/limn/pins/**`, `src/limn/documents/**`(meta의 능력 표시), `src/limn/security/**`·`src/limn/web/**`(필요할 때만), 그 `tests/`, `docs/handbook/api.md`·`domain.md` |
| **U 화면** | 쌓인 핀을 보이기·버리기·다시 찍기, 데스크톱 상태 줄(§계약 2), 네 기기군 PoC | `src/limn/viewer/js/offline-ui.js`(뼈대 있음), `src/limn/viewer/css/**`(새 파일 가능), `src/limn/viewer/index.html`, `src/limn/viewer/js/status.js`, `src/limn/viewer/parts.txt`(CSS 줄만), `src/limn/viewer/ui_en.json`(끝에 덧붙임), 새 테스트 파일, `docs/handbook/viewer.md`(§계약 2의 한 문단만) |
| **T 검증** | 실제 소켓에서 서비스 워커까지 도는 브라우저 테스트(§계약 3) | `tests/support/`의 새 파일, `src/limn/viewer/tests/`의 새 테스트 파일, `docs/handbook/verification.md` |
| **통합** | Markdown·텍스트 문서의 오프라인 핀, 모든 문서 받아 두기, 멱등 키의 뷰어 쪽, ADR-0040, 통합·검증·배포 | `src/limn/viewer/js/offline.js`·`save.js`·`api.js`·`composer.js`·`polling.js`·`boot.js`·`md-surface.js`·`text-surface.js`, `src/limn/viewer/sw.js`, `docs/adr/**`, 설계·계획 문서 |

**남의 파일은 고치지 않는다.** 꼭 필요하면 고치지 말고 보고에 "이 파일의 이 줄이 이렇게 바뀌어야 한다"고 적는다.

## 계약 1 — 멱등 키 (S가 만들고, 통합이 뷰어에서 쓴다)

지금 큐는 답을 잃은 전송을 목록에서 "같은 자리·같은 메모"로 찾는다. 두 레코드가 모두 답을 잃고 둘 다 저장된 경우를 가리지 못해 같은 핀이 둘이 된다. 쓰기에 신원을 실어 보내면 닫힌다.

- `POST /api/pin` 본문에 선택 필드 **`idem`**: 16~64자, `[A-Za-z0-9_-]` 만. 그 밖이면 `400 {error, reason:"bad_idem"}`.
- 이 인스턴스의 핀(열림·검토 대기·완료·휴지통 어디에 있든) 가운데 같은 `idem`을 가진 것이 있으면 **아무것도 쓰지 않고** `200 {id:<그 핀의 번호>, replay:true}` 로 답한다. 판 번호·이벤트·`pins.md`·알림이 바뀌지 않는다. 다시 보낸 본문이 처음과 달라도 처음 것이 이긴다.
- 없으면 지금과 같이 만들고 `idem`을 핀 레코드에 저장한다. 답은 지금과 같은 `{id}` 다(`replay` 키 없음).
- 확인과 만들기는 한 `transact()` 안이다. 같은 키의 두 요청이 동시에 와도 핀은 하나다.
- `idem`은 `pins.md`에 나오지 않고 `GET /api/pins`의 행에도 싣지 않는다(읽기 계약은 그대로다).
- 휴지통에서 영구 삭제된 핀의 키는 사라진다. 그 뒤 같은 키는 새 핀을 만든다.
- **능력 표시:** `GET /api/meta`(라이트 포함) 응답에 `"pin_idem": true` 를 싣는다. 뷰어는 이것이 참일 때만 멱등 키에 기대고, 없으면(옛 서버) 지금의 찾기 규칙을 쓴다.
- `idem` 없는 요청(에이전트의 `curl`, 옛 뷰어)은 지금과 한 글자도 다르지 않게 동작한다.
- **키만으로 묻기(통합 담당이 더한다).** 본문이 `{idem, replay_only: true}` 이면 서버는 아무것도 만들지 않는다. 그 키의 핀이 있으면 `200 {id, replay:true}`, 없으면 `409 {error, reason:"idem_unknown"}` 다. 본문의 다른 필드는 보지 않는다(자리를 다시 찾지 못한 레코드도 물을 수 있어야 한다). 뷰어는 **이미 시도한 레코드**를 자리를 찾기 전에 이것으로 묻는다 — 첫 시도가 핀을 만들고 답만 잃었는데 그사이 자리가 사라졌으면(붙잡은 빌드의 만료, 그 줄의 수정), 자리부터 찾는 순서로는 보류로 빠지고 키를 써 보지 못한다.

험한 표본: `idem` 이 `""`, 15자, 65자, `"한글키-0123456789abcd"`, 숫자 `12345678901234567`(문자열 아님), `null`. 앞의 넷과 숫자는 `400 bad_idem`, `null`·필드 없음은 키 없는 요청이다.

## 계약 2 — 쌓인 핀의 화면 (U가 만든다)

지금은 끊긴 채 핀을 열 개 찍어도 쪽 위에 아무 표시가 없고, 보류된 핀을 보거나 버릴 길이 없다. 상태 줄의 개수뿐이다.

큐 레코드(IndexedDB `limnOffline`의 `pins`, 읽기 `offAll()`):

```
{id, v:1, label, doc, build, page, frac:[x,y,w,h], pt:{w,h}|null, rect|null, quote, note,
 kind_req, assignee, mentions:[], at:<ISO>, held:bool, why:<사유>, sent:bool, top:number|undefined,
 place:{file,name,lo,hi}|null, lines:{file,lo,hi}|null, idem:string}
```

`page` 가 `null` 이고 `lines` 가 있으면 Markdown·텍스트 문서의 줄 핀이다(쪽이 없다). 험한 표본: `quote` 가 빈 글, `note` 가 3,000자, `page` 가 지금 문서의 쪽 수보다 큼, `build` 가 지금 화면의 빌드와 다름, `held:true` 에 `why` 가 빈 글, `doc` 이 지금 문서가 아님.

- **연결점은 하나다.** `offline.js` 의 `offlineSync()` 가 큐를 읽을 때마다 `offlineUiSync(all)` 을 부른다(뼈대가 `js/offline-ui.js` 에 있다). U는 `offline.js` 를 고치지 않는다. 쓰는 것은 `offAll()`·`offDel(id)`·`offPut(rec)`·`offlineSync()`·`offlineFlush()`·`offlineNow()`·`OFF` 다.
- **쪽 위의 표시.** 지금 문서의, **지금 화면의 빌드에 그려진**(`rec.build===META.pages_build`) 레코드만 그 `frac` 자리에 그린다. 빌드가 다르면 그리지 않는다(좌표가 다른 지면의 것이다). 저장된 핀의 마크와 한눈에 구별되어야 하고(아직 서버에 없다), 보류는 대기와 구별되어야 한다. 색·선·배지는 기존 토큰과 `viewer.md` §뜻과 모양을 따른다. **둥근 모서리와 한쪽 강조선을 한 요소에 두지 않는다.**
- **목록.** 핀 패널에 쌓인 핀의 구획을 둔다(큐가 비면 없다). 행마다 쪽(또는 줄), 인용, 메모, 상태(대기 / 보류와 그 사유)를 보이고, 동작은 [버리기](되돌릴 수 있다)와 [다시 찍기]다. [다시 찍기]는 그 레코드를 큐에서 빼고 메모를 작성 칸에 둔다 — 다음 드래그가 그 메모로 새 핀을 만든다(메모가 다음 선택을 기다리는 기존 초안 동작, `draft.js`). 다른 문서의 레코드는 문서 이름과 함께 보이고, 누르면 그 문서로 간다.
- **데스크톱(펼친 화면)의 상태 줄.** `statusShown()` 이 넓은 화면에서 쌓인 핀 항목을 거른다. 넓은 화면에서도 보이게 한다.
- **PoC.** [`workflow.md`](../../handbook/workflow.md) §화면 변경은 PoC를 먼저 보인다 — 네 기기군의 전후 캡처, 바뀐 자리를 표시한 것, 차이 목록. 통합 담당이 소유자에게 보인다.
- `viewer.md` 에는 §끊긴 채 보기와 핀 쌓기의 `**쌓기.**` 문단 바로 뒤에 `**쌓인 핀을 보고 버리기.**` 로 시작하는 문단 하나만 더한다.

## 계약 3 — 실제 소켓의 브라우저 테스트 (T가 만든다)

기존 브라우저 하네스(`helpers_browser.BrowserBase`)는 요청을 가로채 가짜 호스트로 서빙한다. 보안 컨텍스트가 아니라 서비스 워커가 등록되지 않는다. 그래서 워커의 사본 응답과 "끊긴 채 다시 연 탭"은 자동 검사에 없다.

- 실제 서버를 루프백 소켓에 띄우는 하네스를 만든다(`http://127.0.0.1:<빈 포트>` 는 보안 컨텍스트다). 실제 LaTeX 빌드가 필요한 검사는 `latexmk`·`synctex`·`pdftotext` 가 없으면 건너뛴다(기존 LaTeX 검사의 관례를 따른다).
- 옮길 시나리오의 참조 구현이 `~/scratch/limn-offline-20261114/` 에 있다: `offline_smoke.py`(워커의 사본, `/api/*` 는 사본으로 답하지 않음, 큐가 새로고침을 넘김), `stored_read.py`(저장해 둔 읽기와 그 조건), `e2e_live.py`(받아 두기 → 끊김 → 새로고침 → 드래그 → 큐), `e2e_landing.py`(**받아 두기 → 끊김 → 핀 → 서버 재빌드 두 번 → 재연결 → 붙잡힌 빌드로 되짚어 온라인 pick과 같은 줄에 한 개**). 넷 다 지금 통과한다.
- 페이지에는 CSP가 걸려 있다. Playwright의 문자열 평가는 `bypass_csp=True` 가 필요하다. 알림 문구는 브라우저 언어를 따른다(`locale="ko-KR"`).
- 완료 기준: 위 시나리오가 저장소의 테스트로 돌고, `pytest -m browser` 에 들며, 워커가 등록되지 않으면 조용히 통과하지 않고 실패한다.

## 통합 담당의 일

1. **Markdown·텍스트 문서.** 그 문서의 핀은 쪽이 없고 줄이 곧 자리다. 지금은 큐에 넣으면 상자가 없어 전부 보류가 된다. 줄과 그 줄의 글을 담아 두고, 보낼 때 그 줄이 여전히 같은 글이면 쓰고 아니면 보류한다.
2. **모든 문서 받아 두기.** 받아 두기가 지금 문서 하나만 받는다.
3. **멱등 키의 뷰어 쪽.** 레코드마다 키를 두고, 서버가 `pin_idem` 을 말하면 찾기 규칙 대신 그것에 기댄다.
4. **ADR-0040**(제안) — 워커의 사본, `holds.json`·`slim.json`, `POST /api/hold`, 멱등 키, 저장해 둔 읽기.
5. 통합, 전체 검사, 변이 쓸기, 실물 확인, PR, 세 기기 재배포.

## 모든 단위의 검증

```bash
uv sync --group dev
uv run pytest -q -rs -m "not browser"          # 2분
uv run ruff check && uv run ruff format --check
uv run python tools/check_boundaries.py
uv run mypy && uv run mypy --platform darwin
npm ci --ignore-scripts && npm run typecheck
uv run python tools/strict_ratchet.py
```

브라우저 전체(`-m browser`)는 17분이다. 자기 변경이 닿는 파일만 돌리고, 전체는 통합 담당이 돈다. 뷰어의 node 하네스가 `api()`·`savePin()`·`pick()`·`boot()` 를 꺼내 돌린다 — 그 함수가 부르는 새 이름에는 `tests/support/helpers.py` 의 `JS_OFFLINE_STUBS` 에 대역을 더한다.
