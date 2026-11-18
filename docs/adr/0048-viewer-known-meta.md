# ADR-0048: 열린 문서의 meta는 첫 답이 온 뒤에만 있다고 타입에 적고, 그 전에 도는 리스너는 문서가 필요한 자리에서 멈춘다

| | |
| --- | --- |
| **번호** | ADR-0048 |
| **제목** | 열린 문서의 meta는 첫 답이 온 뒤에만 있다고 타입에 적고, 그 전에 도는 리스너는 문서가 필요한 자리에서 멈춘다 |
| **상태** | 승인됨 |
| **결정일** | 2026-11-17 |
| **결정자** | Limn 소유자의 위임자가 작업 지시로 정함(측정한 뒤 고름, 빈 `Meta` 자리 표시 값은 쓰지 않음, 일찍 도는 읽기가 오류를 던지던 자리의 안전한 대신은 아무것도 하지 않는 것, 사람이 보는 결과가 바뀌는 행은 멈춤). 세 모양 중의 선택, 접근자의 이름과 가드의 자리는 지시가 이 변경에 맡겼다 |
| **출처** | `origin/main`(PR #507 합본, 측정 뒤 PR #509를 병합)의 뷰어 모듈을 TypeScript 파서로 센 값, `META`를 `Meta \| null`로 둔 사본에서 `tsc`가 낸 오류 자리, 첫 `/api/meta`를 붙잡은 브라우저에서 키·휠·클릭을 넣어 잰 페이지 오류와 화면 상태 |
| **부분 대체** | 없음. [ADR-0042](0042-viewer-es-modules.md) D1의 설정 함수 방식과 [ADR-0046](0046-viewer-endpoint-answers.md)의 응답 타입을 그대로 쓰며, 그 결정의 어느 조항도 바꾸지 않는다 |

## 맥락

`app/state.ts`는 열린 문서의 meta(`GET /api/meta`의 답)를 `let META = null as unknown as Meta`로 선언했다. 값은 첫 답이 오기 전 `null`인데 타입은 늘 `Meta`라고 말한다. 그래서 첫 답 전에 도는 코드가 `META.kind`를 읽어도 `tsc`는 잡지 못하고, 실행하면 `TypeError`가 된다. 뷰어의 타입에 남은 마지막 구조적 거짓이다.

## 측정

**쓰는 곳.** `META`를 바꾸는 것은 `setMeta` 하나이고, 부르는 자리는 다섯이다: `boot()`의 첫 읽기, 문서 전환(`switchDoc`)의 읽기와 그 뒤 새로 읽은 답, 새 빌드의 새로 고침(`refreshDoc`)의 두 갈래. 다섯 모두 `api('GET /api/meta')`의 답(`Meta`)이나 그 답을 둔 `META_BY`의 값을 넣는다. `null`을 넣는 자리는 없다. 가벼운 폴링(`?light=1`)의 답은 `META`에도 `META_BY`에도 들어가지 않는다. 끊긴 채의 답(`offStashed`)은 성공한 전체 meta 읽기를 둔 사본이거나 받아 둔 빌드를 읽을 때의 meta(`offKeptMeta`)라, 어느 쪽도 일부만 있는 meta가 아니다.

**읽는 곳.** 식별자 `META`의 읽기는 33개 모듈에 266개다(가져오기·내보내기·선언 제외). 많은 순으로 `verdict/flow-line.ts` 45, `documents/view-meta.ts` 18, `documents/flow-switch.ts`·`pdf/view-pages.ts`·`verdict/view-pins.ts` 15, `documents/state.ts` 13, `pdf/view-outline.ts` 12, 나머지 26개 모듈이 1–9개다. 선언을 `Meta | null`로 바꾼 사본에서 `tsc`는 43곳만 실패했다: 좁히지 않은 속성 읽기 34곳과, 값을 `Meta`나 `string`을 받는 매개변수에 넘긴 9곳이다. 나머지 읽기는 이미 좁혀 읽는다(`META && META.pages`, `!!META &&`, `if (!META) return`). 실패한 43곳은 19개 함수에 있다. 6개 함수(`restoreDraft`·`renderRegionComposer`·`mentionUpdate`·`updateStaleBadge`·`quickPick`·`addressedTag`)는 좁혀 읽지만 그 `null`을 `string`을 받는 매개변수에 넘겨 실패했고, 13개 함수가 좁히지 않고 읽는다.

**첫 답 전의 시간.** 스크립트가 적재되며 모듈의 맨 위 코드가 리스너(키, 휠, 터치, 클릭, 크기 변화)를 등록한다. 그 뒤 `boot()`가 언어·테마·배치를 정하고, 끊긴 채의 저장소를 묻고(`offlineAskDown`), 문서 목록을 읽고(`loadDocs`), 그다음에 첫 meta를 기다린다. 그동안 막대와 목차·패널 토글, 변경 보기, [더보기], 도움말, 확대 키와 휠이 살아 있다. 답이 늦으면 이 시간이 길어지고, 답이 실패하면(`boot()`는 상태 줄에 실패를 말하고 끝난다) 이 시간이 페이지가 닫힐 때까지 이어진다. 끊긴 채 다시 연 탭은 저장한 읽기로 곧 답을 받는다.

**좁히지 않는 13개 함수 중 첫 답 전에 도는 것.** 붙잡은 첫 meta 아래에서 넓은 화면·중간 폭·휴대폰·터치·여러 문서·답 실패를 재고, 각 함수를 부르는 자리를 따라갔다.

| 읽는 함수 | 첫 답 전에 닿는 길 | 오늘 그때 일어나는 일 |
| --- | --- | --- |
| `saveScale` (`pdf/view-pages.ts`) | 넓은 화면의 확대: Ctrl+= / − / 0, Ctrl+휠, 막대의 확대·축소·100%·폭 맞춤, [더보기]의 확대, Safari의 핀치, 넓은 터치 화면의 두 손가락 → `zoomTo`·`fitToWidth` → `setScale` | 배율(`PAGE_SCALE`)과 쪽 상자 크기가 바뀐 뒤 `TypeError`. 배율은 저장되지 않고, 배율 숫자는 그리지 않으며, 그 확대의 나머지(벡터 다시 그리기, 자리 되돌리기)는 건너뛴다. 쪽이 없어 그 나머지는 할 일도 없다 |
| `defaultScale` ← `markZoomed` | 좁은·중간 화면에서 위의 같은 확대 | 배율과 배율 숫자가 바뀐 뒤 `TypeError`. `ZOOMED`는 그대로이고 자리 되돌리기를 건너뛴다(쪽이 없어 할 일이 없다) |
| `savedScale`·`defaultScale` ← `autoFitWidth` | 다시 배치(`relayout`): 목차 토글, 중간 폭의 패널 토글, 패널 폭 끌기 | PDF 영역이 그려져 있으면 배치·패널 폭·목차를 적용한 뒤 폭 맞춤에서 `TypeError`, 그 뒤 단계(읽던 자리, 고정 머리, 절 표시줄, 막대의 글자)를 건너뛴다. 그려져 있지 않으면(변경 보기) 폭 맞춤이 먼저 돌아가 오류 없이 뒤 단계가 돈다 |
| `pollBuildOnce` (`documents/view-build-chip.ts`) | 첫 답 전에 누른 [PDF 재빌드]가 성공으로 끝났고, 그 새로 고침의 meta 읽기도 실패했을 때 | 성공 줄을 짓다가 `TypeError`. 오류 패널 닫기, 빌드 오류 지우기, 갱신 확인을 건너뛴다 |

나머지 9개 함수는 첫 답 전에 닿지 않는다. `drawMeta`·`resetBuildForDoc`는 `setMeta` 바로 뒤에서만 불린다. `refreshDoc`·`switchDoc`·`boot()`의 읽기는 같은 함수가 `setMeta`를 부른 뒤에 있다. `buildDoc`·`pageSrc`는 그 문서의 쪽을 그릴 때, `finishRect`는 그린 쪽 위의 선택에서, `loadOutline`은 첫 답이 있어야 여는 PDF(`openVectorDocument`)에서만 돈다. 첫 답 전의 문서 전환(여러 문서에서 Ctrl+PgUp/PgDn, Alt+숫자)은 제 답으로 `META`를 먼저 채우고 그 뒤에 읽는다.

## 결정

| | | |
| --- | --- | --- |
| D1 | **선언이 참을 말한다.** `META`는 `Meta \| null`이다. `setMeta`는 `Meta`만 받아, 한 번 채운 `META`는 다시 `null`이 되지 않는다. 자리 표시 값(빈 `Meta`)은 두지 않는다 | 승인됨 |
| D2 | **문서가 열린 뒤에만 도는 코드는 `knownMeta()`로 읽는다.** `knownMeta()`(`app/state.ts`)는 `Meta`를 돌려주고, 첫 답 전에 불리면 `META`라는 이름으로 시작하는 `Error`를 던진다. 그런 읽기는 시작 순서의 잘못이라, 이음매의 접근자처럼 조용히 넘어가지 않는다. 위 9개 함수와, 일찍 도는 함수 중 첫 답 뒤에만 닿는 부분(`saveScale`·`savedScale`·`defaultScale`)이 쓴다 | 승인됨 |
| D3 | **첫 답 전에 돌 수 있는 코드는 `META`를 읽어 좁히고, 문서가 필요한 일은 오늘 오류가 나던 바로 그 자리에서 멈춘다.** 넓은 화면의 확대는 배율을 저장하기 전에 멈춘다(`setScale`: 배율 숫자는 쪽을 처음 그릴 때 `buildDoc`이 쓴다). 좁은 화면의 확대는 `ZOOMED`를 그대로 둔다(`markZoomed`). 다시 배치는 PDF 영역이 그려져 있으면 틀만 적용하고 폭 맞춤과 그 뒤 단계를 `boot()`에 맡긴다(`relayout`). 첫 답이 오지 않은 채 끝난 이 탭의 재빌드는 아무 말 없이 끝난다(`pollBuildOnce`). 멈추기 전에 일어난 일과 멈춘 뒤 건너뛰는 일은 오늘 그대로라, 사람이 보는 것은 바뀌지 않는다 | 승인됨 |
| D4 | **좁혀 읽던 코드는 그대로 좁혀 읽고, 넘기는 값의 타입을 참으로 적는다.** `META && META.kind`처럼 `null`을 넘기던 자리는 그 값을 받는 매개변수가 `null`을 받거나(`draftRestore`의 빌드, `mentionMatches`의 내 로그인), 같은 결과의 값을 넘긴다(`isFigureKind(META ? META.kind : undefined)`, `builtAtEpoch(META ? META.built_at : '')`, `addressedTag`의 `me !== null &&`) | 승인됨 |

## 대안

| | (a) 모든 읽기가 `Meta \| null`을 좁힘 | (b) 던지는 접근자와 좁히는 읽기(채택) | (c) 첫 답 뒤에 리스너를 등록 |
| --- | --- | --- | --- |
| 모양 | 좁히지 않는 13개 함수마다 `if (!META) return` | 위 D2·D3 | 확대·배치·막대의 리스너를 `boot()`가 첫 답 뒤에 건다 |
| 참인가 | 참이지만, 첫 답 뒤에만 도는 9개 함수에 닿을 수 없는 갈래가 생긴다. 그 갈래는 시작 순서의 잘못을 조용히 삼킨다 | 참이다. 읽는 쪽이 어느 쪽인지 말한다 | 참이 되지만 화면이 바뀐다 |
| 기각 이유 | 266개 읽기의 대부분은 이미 좁혀 읽고, 좁히지 않는 13개 함수 중 9개는 첫 답 뒤에만 돈다. 드문 일찍 도는 읽기를 위해 모든 읽기에 거짓 갈래를 단다 | — | 오늘 첫 답 전에 되는 목차·패널 토글(설정에 남는다), 변경 보기, [더보기], 도움말이 그동안 죽고, 답이 실패한 페이지에서는 끝내 죽는다. 첫 답 전의 문서 전환도 막힌다 |

**자리 표시 값(빈 `Meta`)도 기각했다.** 빈 값이 "문서 없음"으로 읽히지 않는 필드가 있다. `restoreDraft`는 `!META`를 보고 초안을 되살리지 않는데, 빈 `Meta`면 `label: ''`의 키로 초안을 읽고 쓴다. `refreshDoc`는 `META && …`로 처음 그리는지 가르는데, 빈 `pages`와 같은 쪽 수로 비교한다. `me: {}`는 역할 검사에는 "역할 없음"이지만 첫 답이 왔는지는 말하지 못한다.

## 부르는 자리 다섯 (전 → 후)

| 함수 | 전 | 후 |
| --- | --- | --- |
| `drawMeta` (첫 답 뒤) | `document.body.classList.toggle('no-rebuild', !buildsFromSource(META.kind));` | `const meta = knownMeta();` … `!buildsFromSource(meta.kind)` |
| `boot()` (첫 답 바로 뒤) | `if (META.doc) setDoc(META.doc); META_BY.set(DOC, META);` | `const first = knownMeta(); if (first.doc) setDoc(first.doc); META_BY.set(DOC, first);` |
| `finishRect` (그린 쪽 위) | `pageInfo = META.pages[page - 1]` | `meta = knownMeta(), pageInfo = meta.pages[page - 1]` |
| `setScale` (첫 답 전에도) | `if (save !== false && LAYOUT === LAYOUT_MODE.WIDE) saveScale();` | `if (save !== false && LAYOUT === LAYOUT_MODE.WIDE) { if (!META) return; saveScale(); }` |
| `quickPick` (좁혀 읽던 곳) | `isFigureKind(META && META.kind)` | `isFigureKind(META ? META.kind : undefined)` |

## 결과 (이 변경이 센 값)

- `as unknown as` 상태 선언은 뷰어에 `META` 하나였고(`null as unknown as T`, `undefined as unknown as T`를 모듈 전체에서 찾았다), 이제 없다. 그 단언은 [ADR-0046](0046-viewer-endpoint-answers.md) D8이 기준선에 신뢰 지점 말고 남긴 유일한 메시지였다. 이 변경으로 `consistent-type-assertions`는 기준선에서 빠지고(`app/state.ts`의 2개), ESLint 기준선은 그 D8의 세 신뢰 지점(5개 메시지)만 센다. 늘어난 (규칙, 파일)은 없다.
- 첫 meta를 붙잡은 브라우저에서 위 표의 길(키, 휠, 막대, 토글, 변경 보기, [더보기])을 지나며 기록한 화면 상태(배율, `ZOOMED`, 배율 숫자, 틀의 클래스, 패널·목차, 설정, 절 표시줄, 상태 줄)는 단계마다 이 변경 전과 같았고, 페이지 오류는 장치마다 6–7개에서 0개가 되었다. 바뀐 실행 동작과 그 입력은 이 변경의 PR이 적는다.
- `test_viewer_meta_known.py`가 `knownMeta`의 이름 있는 실패, D3의 네 자리, D4의 값, 첫 meta가 늦는 브라우저의 세 장치를 지킨다.
- 현재 규칙은 [viewer.md](../handbook/viewer.md) §타입 검사에 있다.

## Trade-off

- **얻는 것.** 첫 답 전에 `META`를 좁히지 않고 읽는 새 코드는 `tsc`가 거절한다. 문서가 열린 뒤에만 도는 코드는 그렇다고 이름으로 말하고, 순서가 틀리면 이름 있는 오류가 난다.
- **감수하는 것.**
  - D3의 `relayout`은 "PDF 영역이 그려져 있으면"이라는 조건을 그대로 옮겨 적는다. 오늘 폭 맞춤이 그 조건에서만 오류를 냈기 때문이다. 그래서 변경 보기를 연 채 첫 답 전에 다시 배치하면 지금처럼 뒤 단계(절 표시줄 등)가 빈 문서로 돈다.
  - 넓은 화면에서 첫 답 전의 확대는 배율만 바꾸고 배율 숫자는 쪽을 처음 그릴 때까지 그대로다. 오늘의 모양을 지키느라 고치지 않았다.

## 되돌릴 조건

첫 답 전에 돌 수 있는 코드가 늘어 D3의 멈추는 자리가 읽는 쪽보다 많아지면, (c)처럼 그 리스너를 첫 답 뒤로 옮기는 화면 변경을 PoC와 함께 따로 제안한다. 되돌리는 것은 타입과 가드이며, 저장 형식·HTTP API·화면은 이 결정으로 바뀌지 않았다.
