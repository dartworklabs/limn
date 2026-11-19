# 번호 배지를 끌어 핀의 위치를 다시 잡기 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저장된 열린 핀의 번호 배지를 끌면 그 핀의 [위치 다시 잡기]가 시작하고, 놓은 자리가 저장되면 설 조각들로 스냅한 뒤 기존 배너가 확정을 받는다.

**Architecture:** 서버는 고치지 않는다. 뷰어의 기존 세 기구를 잇는다 — (1) 쪽 위 드래그 처리기(`pdf/input-selection.ts`)에 배지에서 시작하는 분기를 더하고, (2) 작성 중인 선택이 쓰는 조각 스냅(`composer/view-levels.ts` `followRange` + `pdf/input-selection.ts` `snapSelectionBox`)을 '새 위치' 상자에 연결하고, (3) 확정은 기존 위치 다시 잡기 배너(`composer/flow-repick-banner.ts`)가 받는다. `pdf` 는 `composer` 를 import 할 수 없으므로 배지 드래그가 모드를 켜는 호출은 `pdf/state-seams.ts` 의 `PageSelection` 이음매를 지난다.

**Tech Stack:** TypeScript ES 모듈(뷰어), Python 3.10+ 표준 라이브러리(서버·테스트), pytest + Playwright, node(모듈 글을 타입 걷어 읽는 순수 함수 시험).

**Spec:** [`docs/superpowers/specs/2026-11-19-pin-badge-drag-reposition-design.md`](../specs/2026-11-19-pin-badge-drag-reposition-design.md) (2026-11-19 소유자 승인). 결정 기록은 [`docs/adr/0051-pin-badge-drag-reposition.md`](../../adr/0051-pin-badge-drag-reposition.md)(제안).

## Global Constraints

- **에이전트 계약은 더하기만 한다.** 이 변경은 HTTP 경로·JSON 필드·상태 이름·`pins.md` 를 하나도 더하거나 바꾸지 않는다. 서버 코드(`src/limn/` 중 `viewer/js` 밖)를 고치지 않는다.
- **커밋은 모두 `git commit -s`** 이고 메시지 끝 줄은 `I agree to the Limn CLA (CLA.md).` 다.
- **코드·주석·커밋 메시지는 영어, Handbook 은 한국어.** 새 UI 문구를 더하면 템플릿의 한국어가 원본이고 `src/limn/viewer/ui_en.json` 에 영어를 더한다(이 계획은 새 문구를 더하지 않는다).
- **이름은 온전한 낱말.** `limn/plain-names` 가 세 글자 미만과 `tools/viewer-names.json` 의 `deny`(`sel`·`btn`·`rev`·`ctx`·`idx` 등)를 거절한다. 주석에 릴리스·이슈·PR 번호와 `YYYY-MM-DD` 를 쓰지 않는다(`limn/no-history-comment`); Handbook 절과 ADR 번호는 쓴다.
- **모듈 경계.** `js/<기능>/<역할>-<주제>.ts` 자리를 지킨다. `pdf` → `composer` import 는 없다. `rules` 역할은 제 기능의 `rules` 와 `platform` 밖을 import 하지 않는다.
- **페이지 정책.** JS 는 `<script>`·`<style>` 요소를 만들지 않고 `style` 속성·인라인 처리기를 쓰지 않는다. 좌표는 `element.style.left` 류로 쓴다.
- **문턱 8px**(`TAP_SLOP`), **짚개는 쪽 폭 ±7%·쪽 높이 ±0.6%**(`QUICK_HALF_WIDTH`·`QUICK_HALF_HEIGHT`, 기존 값 그대로).
- **머지하지 않는다.** PR 까지다. 네 기기군 여덟 크기 PoC 를 소유자에게 보인 뒤에 소유자가 머지한다.

## Review Focus

spec 이 함의하지만 어느 task 의 시험도 돌리지 않아 사람을 물 수 있는 입력 다섯이다. 줄마다 그 시험을 소유 task 에 붙였다.

1. **끄는 동안 그 핀이 목록에서 사라진다** (다른 쪽이 지웠고 5초 폴링이 목록을 다시 읽었다). 기대: 켤 모드가 없으므로 그 드래그는 평범한 사각형으로 이어지고, 예외가 나지 않는다. → Task 4 Step 3.
2. **끄는 동안 두 손가락이 들어온다**(핀치) 또는 포인터가 취소된다. 기대: 끌던 상자가 사라지고, 그 드래그가 켠 모드도 함께 꺼진다 — 상자 없는 배너가 쪽 위에 남지 않는다. → Task 4 Step 5.
3. **끌 수 없는 핀의 배지를 마우스로 끈다**(판정·닫힌·검토 대기 핀). 기대: 지금과 똑같다 — 상자가 생기지 않고 배지의 클릭이 카드로 데려간다. → Task 4 Step 7.
4. **배지를 쪽 밖으로 끈다.** 기대: 짚개는 그 쪽 안에 머물고(영역 핀은 상자가 쪽 안으로 되밀린다), 다른 쪽으로 넘어가지 않는다. → Task 3 Step 1·3.
5. **확정하는 순간 그 핀의 `rev` 가 달라져 있다**(에이전트가 닫았거나 다른 쪽이 고쳤다). 기대: `409` 로 거절되고 배너가 이유를 말하며 핀은 움직이지 않는다. → Task 4 Step 9.

---

## File Structure

| 파일 | 맡는 것 |
| --- | --- |
`src/limn/viewer/js/app/rules-pins.ts` | 수정 — `markMovable(pin)`: 자리를 옮길 수 있는 핀인지의 순수 판단
`src/limn/viewer/js/pdf/input-selection.ts` | 수정 — 조각 상자의 소유자, 배지 드래그의 상태·순수 계산(`badgeDrop`·`badgeAt`)과 포인터 분기
`src/limn/viewer/js/pdf/state-seams.ts` | 수정 — `PageSelection` 에 `repickFromBadge`
`src/limn/viewer/js/main.ts` | 수정 — 그 이음매 등록
`src/limn/viewer/js/composer/view-levels.ts` | 수정 — 범위의 소유자 역할(`rangeRole`)과 역할별 새로 고침 타이머, 스냅의 소유자
`src/limn/viewer/js/composer/flow-repick-banner.ts` | 수정 — 배너가 '새 위치' 상자를 조각으로 스냅하고 보이게 하며, 끝낼 때 그 조각을 거둔다
`src/limn/viewer/js/composer/flow-repick.ts` | 수정 — `repickFromBadge(id)`, 확정이 쓰는 `base_rev`
`src/limn/viewer/js/composer/flow-pick.ts` | 수정 — 조각을 거둘 때 소유자를 말한다
`src/limn/viewer/types/state.d.ts` | 수정 — `Repick.base_rev`
`src/limn/viewer/tests/test_viewer_badge_drag.py` | 생성 — 순수 판단·계산(node)과 배지 드래그의 실제 흐름(브라우저)
`src/limn/viewer/tests/test_viewer_selection_boxes.py` | 수정 — 두 소유자의 조각이 서로를 거두지 않는다, '새 위치' 상자가 조각으로 선다
`docs/handbook/viewer.md` | 수정 — §조작 한눈에 두 표, §패널 정리, §핀 마크의 조각
`CHANGELOG.md` | 수정 — 사용자에게 보이는 변경

---

### Task 1: 조각 상자를 소유 상자에 묶는다

작성 중인 선택과 위치 다시 잡기는 동시에 열려 있을 수 있다(`startRepick` 은 **미완성** 선택만 버린다). 지금은 `clearSelectionParts()` 가 `document` 전체의 `.sel-part` 를 지우므로, 한쪽이 다른 쪽의 조각을 거둔다. Task 2 가 '새 위치' 상자에 조각을 주기 전에 이것을 고친다.

**Files:**
- Modify: `src/limn/viewer/js/pdf/input-selection.ts`
- Modify: `src/limn/viewer/js/composer/flow-pick.ts`
- Test: `src/limn/viewer/tests/test_viewer_selection_boxes.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `type PendingOwner = 'compose' | 'repick'` (export)
  - `function selectionParts(owner: PendingOwner): HTMLElement[]`
  - `function clearSelectionParts(owner: PendingOwner): void`
  - `function snapSelectionBox(box: HTMLElement | null, pieces: MarkPiece[], dragged: { page: number; frac: number[] } | null, owner: PendingOwner): void`

- [ ] **Step 1: 실패하는 시험을 쓴다** — `test_viewer_selection_boxes.py` 에 `PieceOwners` 클래스로, 서로 다른 소유자의 조각이 서로를 거두지 않는지 node 로 읽는다. 기존 `MARKS_HARNESS` 류 하네스를 따라 `snapSelectionBox` 를 `extract_js_fn` 으로 꺼내 돌린다.

```python
def test_a_pending_box_takes_off_only_its_own_pieces(self):
    """snapSelectionBox('repick') leaves the pieces drawn for 'compose' in place."""
    # 두 소유자로 각각 조각 둘을 그린 뒤 'repick' 으로 다시 스냅하면,
    # 남은 .sel-part 의 data-owner 는 compose 둘 + repick 새것들이다.
```

- [ ] **Step 2: 시험을 돌려 실패를 확인한다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_selection_boxes.py -k PieceOwners`
Expected: FAIL — `snapSelectionBox` 가 인자 넷을 받지 않거나, 다른 소유자의 조각이 사라진다.

- [ ] **Step 3: `pdf/input-selection.ts` 에서 조각에 소유자를 적는다**

`newSelectionPart(pageElement, owner)` 가 `part.dataset.owner = owner` 를 쓴다. `selectionParts(owner)`·`clearSelectionParts(owner)` 는 `'.sel-part[data-owner=' + owner + ']'` 로 찾는다(값은 닫힌 두 글자뿐이라 선택자에 그대로 쓴다). `snapSelectionBox` 가 `owner` 를 받아 `clearSelectionParts(owner)` 와 `newSelectionPart(pageElement, owner)` 에 넘긴다. `finishRect` 와 `pressOutsideSelection` 의 호출은 `'compose'` 다. CSS 는 고치지 않는다 — `.sel-part` 를 고르는 규칙이 없고 조각은 `sel pending` 으로 그려진다.

- [ ] **Step 4: `composer/flow-pick.ts` 의 두 호출에 소유자를 넘긴다** — 둘 다 작성 중인 선택을 거두는 자리이므로 `'compose'` 다.

- [ ] **Step 5: 시험을 돌려 통과를 확인한다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_selection_boxes.py src/limn/viewer/tests/test_viewer_mark_boxes.py`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add -- src/limn/viewer/js/pdf/input-selection.ts src/limn/viewer/js/composer/flow-pick.ts src/limn/viewer/tests/test_viewer_selection_boxes.py
git commit -s -m "refactor(viewer): a pending box takes off only its own piece boxes"
```

---

### Task 2: '새 위치' 상자가 저장될 조각들로 선다 (ADR-0051 D5)

줄 핀의 위치 다시 잡기는 지금 끈 사각형을 보이며 [이 위치로 바꾸기]를 묻는데, 저장되면 마크는 그 범위의 조각으로 선다. 작성 중인 선택이 쓰는 `followRange` 를 '새 위치' 상자에 연결한다. 배지 드래그 없이도 보이는 변경이므로 이 task 만으로 PoC 의 전후 비교 하나가 생긴다.

**Files:**
- Modify: `src/limn/viewer/js/composer/view-levels.ts`
- Modify: `src/limn/viewer/js/composer/flow-repick-banner.ts`
- Test: `src/limn/viewer/tests/test_viewer_selection_boxes.py`

**Interfaces:**
- Consumes: Task 1 의 `snapSelectionBox(..., owner)`·`clearSelectionParts(owner)`
- Produces:
  - `type RangeRole = 'compose' | 'edit' | 'repick'` (`view-levels.ts` 안에서만 쓴다)
  - `function rangeRole(owner: LineOwner): RangeRole`
  - `followRange(selection, box, after)` 와 `refetchSnip(owner, after)` 의 서명은 **바뀌지 않는다** — 역할을 안에서 가린다

- [ ] **Step 1: 실패하는 브라우저 시험을 쓴다** — `test_viewer_selection_boxes.py` 의 위치 다시 잡기 흐름에, 핀 목록이 조각을 답하는 문서에서 [위치 다시 잡기] → 드래그 뒤 `#banner` 가 서면 `REPICK.box` 가 끈 사각형이 아니라 후보 범위의 조각에 서는지 읽는다. 조각이 둘인 범위에서는 `.sel-part[data-owner=repick]` 가 하나 더 그려진다.

- [ ] **Step 2: 시험을 돌려 실패를 확인한다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_selection_boxes.py -k Repick`
Expected: FAIL — 상자가 끈 사각형에 그대로 있다.

- [ ] **Step 3: `view-levels.ts` 에 `rangeRole(owner)` 을 더하고 역할로 가른다**

`rangeRole` 은 `owner === COMPOSE.current` 면 `'compose'`, `REPICK && REPICK.cand === owner` 면 `'repick'`, 아니면 `'edit'` 이다. `refetchSnip` 의 `const composing = owner === COMPOSE.current` 를 `const role = rangeRole(owner)` 로 바꾸고, 상자를 달라고 하는 조건(`&levels=1&boxes=1` 과 `takeRangeBoxes`)과 `followRange` 의 스냅 소유자를 `role !== 'edit'`·`role === 'repick' ? 'repick' : 'compose'` 로 읽는다. 새로 고침 타이머는 역할마다 하나다(`Map<RangeRole, ReturnType<typeof setTimeout>>`) — 함께 열린 두 패널의 요청이 서로를 취소하지 않게 하려는 기존 이유(그 파일의 주석)를 역할 셋으로 넓히는 것이다. 답이 아직 그 소유자의 것인지 보는 조건도 역할마다다: `'compose'` 는 지금처럼 `owner === COMPOSE.current && currentVisit(visit)`, `'edit'` 은 `owner === EDITOR.current`, `'repick'` 은 `REPICK !== null && REPICK.cand === owner && currentVisit(visit)` 다. `REPICK` 를 `app/state.ts` 에서 import 한다.

- [ ] **Step 4: `flow-repick-banner.ts` 의 `bannerCompare` 가 조각으로 스냅하고 보이게 한다**

`snapBox(repick.box, repickElement(candidate))` 다음에 `followRange(candidate, repick.box, bannerCompare)` 와 `revealBox(repick.box, true)` 를 둔다. `followRange` 는 그림 문서와 영역 답에서 바로 돌아오므로(`isFigureKind`·`onLines`) 그 두 경우의 상자는 지금과 같다. `revealBox` 는 상자가 이미 보이면 아무것도 하지 않으므로, 쪽을 넘는 범위에서만 스크롤한다. `cancelRepick` 은 `REPICK.box.remove()` 앞에 `clearSelectionParts('repick')` 를 부른다. `flow-pick.ts` 가 `pdf_build_gone` 으로 `repick.box` 를 거두는 자리에도 같은 호출을 둔다.

- [ ] **Step 5: 시험을 돌려 통과를 확인한다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_selection_boxes.py src/limn/viewer/tests/test_viewer_repick_race.py src/limn/viewer/tests/test_viewer_markdown.py -k "Repick or repick"`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add -- src/limn/viewer/js/composer/view-levels.ts src/limn/viewer/js/composer/flow-repick-banner.ts src/limn/viewer/js/composer/flow-pick.ts src/limn/viewer/tests/test_viewer_selection_boxes.py
git commit -s -m "feat(viewer): a re-place's box stands on the pieces its range prints as"
```

---

### Task 3: 끌 수 있는 핀과 끄는 사각형의 순수 판단 (ADR-0051 D2·D3·D4·D7)

**Files:**
- Modify: `src/limn/viewer/js/app/rules-pins.ts`
- Modify: `src/limn/viewer/js/pdf/input-selection.ts`
- Test: `src/limn/viewer/tests/test_viewer_badge_drag.py` (생성)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `function markMovable(pin: Pin | null | undefined): boolean` — `app/rules-pins.ts` 에서 export
  - `function badgeDrop(place: number[], dx: number, dy: number): number[]` — `pdf/input-selection.ts`, export(시험이 꺼낸다)
  - `function badgeAt(drag: BadgeDrag, x: number, y: number): number[]` — 두 꼭짓점 `[x0, y0, x1, y1]`

- [ ] **Step 1: 실패하는 시험을 쓴다** — `test_viewer_badge_drag.py` 에 `MovablePins`·`DroppedBox` 두 클래스를 두고 `extract_js_fn` + `run_node` 로 읽는다.

```python
def test_only_an_open_pin_without_a_verdict_may_be_moved(self):
    """markMovable: open -> True; a verdict, review and done -> False."""


def test_a_dropped_box_keeps_its_size_and_stays_on_the_page(self):
    """badgeDrop([0.8, 0.9, 0.3, 0.2], 0.5, 0.5) -> [0.7, 0.8, 0.3, 0.2] (slid back inside)."""


def test_a_box_put_back_where_it_was_reads_as_the_fractions_it_came_with(self):
    """badgeDrop(place, 0, 0) == place for six-place fractions."""
```

- [ ] **Step 2: 시험을 돌려 실패를 확인한다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_badge_drag.py`
Expected: FAIL — `markMovable`·`badgeDrop` 를 꺼낼 수 없다.

- [ ] **Step 3: `app/rules-pins.ts` 에 `markMovable` 을, `pdf/input-selection.ts` 에 `badgeDrop`·`fracMove`·`badgeAt` 을 쓴다**

`markMovable(pin)` = `!!pin && !verdictOf(pin) && pinState(pin) === PIN_STATE.OPEN`. `badgeDrop(place, dx, dy)` 는 `place` 의 폭·높이를 지키고 양 끝을 `[0, 1 - 폭]`·`[0, 1 - 높이]` 로 자른 뒤 소수 여섯째 자리로 반올림한다(어느 쪽에서도 천분의 일 픽셀 미만). `fracMove(pageElement, startClientX, startClientY, x, y)` 는 `getBoundingClientRect` 로 비율 이동량을 낸다(`fracAt` 과 같은 기준이라 핀치 확대 중에도 맞는다). `badgeAt(drag, x, y)` 는 영역 핀이면 `badgeDrop` 의 `[x, y, w, h]` 를 두 꼭짓점으로 펴고, 줄 핀이면 포인터 자리의 `quickBox(...)` 를 그대로 돌려준다 — 짚개는 탭·길게 누르기가 문단을 집을 때 보내는 그 사각형이고 `clampUnit` 이 쪽 안으로 자른다.

- [ ] **Step 4: 시험을 돌려 통과를 확인한다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_badge_drag.py`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add -- src/limn/viewer/js/app/rules-pins.ts src/limn/viewer/js/pdf/input-selection.ts src/limn/viewer/tests/test_viewer_badge_drag.py
git commit -s -m "feat(viewer): the pure rules of a badge drag - which pin moves, and where its box lands"
```

---

### Task 4: 배지 드래그가 위치 다시 잡기를 시작한다 (ADR-0051 D1·D6)

**Files:**
- Modify: `src/limn/viewer/types/state.d.ts`
- Modify: `src/limn/viewer/js/composer/flow-repick.ts`
- Modify: `src/limn/viewer/js/pdf/state-seams.ts`
- Modify: `src/limn/viewer/js/main.ts`
- Modify: `src/limn/viewer/js/pdf/input-selection.ts`
- Test: `src/limn/viewer/tests/test_viewer_badge_drag.py`

**Interfaces:**
- Consumes: Task 3 의 `markMovable`·`badgeAt`; Task 2 의 조각 스냅
- Produces:
  - `Repick.base_rev: number` (`types/state.d.ts`)
  - `PageSelection.repickFromBadge(id: number): void` (`pdf/state-seams.ts`)
  - `function repickFromBadge(id: number): void` (`composer/flow-repick.ts`, export)

- [ ] **Step 1: 실패하는 브라우저 시험을 쓴다** — `test_viewer_badge_drag.py` 에 `BadgeDragOnScreen(BrowserBase)` 를 두고, `test_viewer_mark_boxes.py` 의 `MarkBoxesOnScreen` 처럼 핀 목록 응답에 조각을 끼워 넣는 라우트로 띄운다. 마우스로 핀 하나의 배지를 8px 넘게 끌어 놓으면 `#banner` 에 `[이 위치로 바꾸기]` 가 서고, `REPICK.box` 가 짚은 자리의 범위 조각에 서며, 누르면 그 핀의 `lo`·`hi` 가 바뀌는지 읽는다.

- [ ] **Step 2: 시험을 돌려 실패를 확인한다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_badge_drag.py -k BadgeDragOnScreen`
Expected: FAIL — 배지를 끌어도 배너가 서지 않는다.

- [ ] **Step 3: `composer/flow-repick.ts` 에 `repickFromBadge(id)` 를 쓰고 확정이 `base_rev` 를 읽게 한다**

`repickFromBadge(id)` 는 `findAnyPin(id)` 가 없으면 아무것도 하지 않는다(Review Focus 1). 있으면 `startRepick` 처럼 미완성 선택과 앞선 위치 다시 잡기를 거둔 뒤 `setRepick({ id, from: { lo, hi, page: pinPlace(pin).page, region: isRegion(pin) }, box: null, cand: null, base_rev: pin.rev || 0 })` 와 `bannerRepick()` 를 부른다. 선택 모드와 시트는 그대로 둔다 — 사람은 배지를 쥐고 있고 새로 끌 참이 아니다. `startRepick` 의 `setRepick` 에도 `base_rev: EDITOR.current.base_rev` 를 더한다. `applyRepick` 의 `base` 는 `EDITOR.current && EDITOR.current.id === repick.id ? EDITOR.current.base_rev : repick.base_rev` 다 — 카드가 열려 있으면 지금처럼 카드의 값이고, 배지에서 시작했으면 핀 자신의 값이다.

- [ ] **Step 4: 이음매를 더하고 입구에서 등록한다** — `pdf/state-seams.ts` 의 `PageSelection` 에 `repickFromBadge(id: number): void` 를 더하고(doc 주석 한 줄), `main.ts` 의 `setPageSelection({...})` 에 `repickFromBadge` 를 넣는다.

- [ ] **Step 5: `pdf/input-selection.ts` 의 포인터 분기를 더한다**

`DRAG` 에 `move: { id: number; frac: number[]; region: boolean } | null` 과 `began?: boolean` 을 더한다. `badgeMove(badge, mouse)` 는 그림 문서(`isFigureKind`)·`markMovable` 이 아닌 핀·`isFrac` 이 아닌 자리·크기가 0인 영역 상자·그 핀의 모드 밖 손가락에서 `null` 이다. `pointerdown` 은 `const move = badge && (mouse || (SELMODE && event.isPrimary)) ? badgeMove(badge, mouse) : null` 로 읽고, 지금의 이른 반환을 `if (badge && !move && (mouse || !SELMODE || !event.isPrimary)) return` 으로 바꾸고, 상자는 `mouse && !badge ? newBox(pageElement) : null` 로 미룬다(배지의 누름은 문턱을 넘어야 상자가 된다). `pointermove` 는 문턱을 넘는 순간 `badgeDragBegin(DRAG)` 로 모드를 켜고(이미 그 핀의 모드면 아무것도 하지 않으며, 켜지지 않으면 `move` 를 버려 평범한 사각형이 된다), `badgeDragGone(DRAG)` 이면 상자만 거두고 끝낸다. 그 뒤 `DRAG.move` 가 있으면 `badgeAt` 의 두 꼭짓점으로 `drawBox` 한다. `pointerup` 은 `badgeDragGone` 이면 상자를 거두고 아무것도 하지 않으며(떨어뜨린 자리가 '새 핀' 패널을 열지 않는다), `DRAG.move` 가 있으면 `finishRect(drag.pg, drag.box, ...badgeAt(drag, x, y))` 로 기존 pick·배너·확정 경로에 넣는다. `pointercancel` 은 그 드래그가 켠 모드(`began`)도 함께 끝낸다(Review Focus 2).

- [ ] **Step 6: 시험을 돌려 통과를 확인한다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_badge_drag.py`
Expected: PASS

- [ ] **Step 7: Review Focus 의 나머지 시험을 더한다** — 같은 클래스에 넷을 더한다. ① 끌 수 없는 핀(판정·검토 대기)의 배지를 마우스로 끌면 상자가 생기지 않고 클릭이 카드로 데려간다(Review Focus 3). ② 문턱 안의 누름(6px)은 지금처럼 클릭이다. ③ 터치는 모드 밖에서 끌리지 않고, `[선택]` 모드의 다른 핀 배지는 **새 상자**를 시작한다. ④ 모드 안 그 핀의 배지는 손가락으로도 끌린다.

- [ ] **Step 8: 쪽 밖으로 끄는 경우를 더한다** — 배지를 쪽 바깥까지 끌어 놓아도 보낸 사각형이 그 쪽 안이고 다른 쪽의 핀이 되지 않는다(Review Focus 4).

- [ ] **Step 9: `409` 를 더한다** — 끌어 배너를 세운 뒤 그 핀의 `rev` 를 서버에서 올리고 [이 위치로 바꾸기]를 누르면, 경고가 서고 핀의 `lo`·`hi` 가 그대로다(Review Focus 5).

- [ ] **Step 10: 시험을 돌려 통과를 확인한다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_badge_drag.py src/limn/viewer/tests/test_viewer_role_keyboard.py src/limn/viewer/tests/test_viewer_mark_boxes.py src/limn/viewer/tests/test_viewer_covered_marks.py`
Expected: PASS

- [ ] **Step 11: 커밋**

```bash
git add -- src/limn/viewer/types/state.d.ts src/limn/viewer/js/composer/flow-repick.ts src/limn/viewer/js/pdf/state-seams.ts src/limn/viewer/js/main.ts src/limn/viewer/js/pdf/input-selection.ts src/limn/viewer/tests/test_viewer_badge_drag.py
git commit -s -m "feat(viewer): drag a pin's number badge to place it again"
```

---

### Task 5: Handbook 과 CHANGELOG 를 지금 상태에 맞춘다

**Files:**
- Modify: `docs/handbook/viewer.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 1–4 의 실제 동작
- Produces: 없음

- [ ] **Step 1: §조작 한눈에의 두 표를 고친다** — 데스크톱 표의 **마크 배지** 행에 "끌면 그 핀의 위치를 다시 잡는다(8px 넘게 움직일 때. 판정·닫힌·검토 대기 핀은 끌리지 않는다)"를, **수정** 행에 배지 지름길을, 휴대폰·태블릿 표의 **위치 다시 잡기** 행에 "모드 안에서는 그 핀의 배지를 끌어도 된다"를 더한다. "배지 밖의 마크 상자를 끌면 평소처럼 새 위치를 고른다"는 문장은 그대로 둔다.

- [ ] **Step 2: §패널 정리에 '새 위치' 상자의 절을 더한다** — **'새 핀' 상자가 범위를 그린다** 바로 뒤에, '새 위치' 상자도 같은 기구로 조각에 서고 확정할 자리가 영역 밖이면 데려온다는 것, 배지에서 시작한 위치 다시 잡기는 핀 자신의 `rev` 를 기준으로 저장한다는 것, 영역 핀은 핀의 상자를 그대로 옮긴다는 것을 현재형으로 쓴다. 각 문단에 [ADR-0051](../adr/0051-pin-badge-drag-reposition.md)의 해당 결정을 짧게 인용하되 본문만으로 규칙이 완결되게 쓴다.

- [ ] **Step 3: §핀 마크의 조각에 손잡이를 적는다** — 배지가 첫 조각에만 있다는 기존 문단에, 그래서 그 배지가 위치를 다시 잡는 손잡이이기도 하다는 한 문장을 더한다.

- [ ] **Step 4: CHANGELOG 에 적는다** — 다음 판 절에 사용자에게 보이는 두 줄(배지 드래그, '새 위치' 상자가 저장될 자리를 보인다)을 적고 에이전트 계약이 바뀌지 않았음을 적는다.

- [ ] **Step 5: 문서 게이트를 돌린다**

Run: `uv run pytest -q tests/architecture/test_handbook_refs.py src/limn/viewer/tests/test_i18n.py src/limn/viewer/tests/test_viewer_tips.py`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add -- docs/handbook/viewer.md CHANGELOG.md
git commit -s -m "docs: the number badge is the handle for placing a pin again"
```

---

## 게이트 전체와 PoC

- [ ] **Step 1: `CLAUDE.md` §검증의 12개 게이트를 전부 돌린다.** 명령은 `&&` 로 잇는다. 하나라도 실패하면 커밋하지 않고 고친다. 뷰어 번들(`src/limn/viewer/dist/viewer.js`)은 `npm run build:check` 가 다시 지어 바이트를 견주므로, 모듈을 고쳤으면 지어서 함께 커밋한다.
- [ ] **Step 2: 네 기기군 여덟 크기 PoC 를 만든다** — 1440×900(마우스), 390×844·320×720, 768×1024·1024×768, 344×882·673×841·841×673(전부 터치). `code-ui-poc` 스킬의 `ui_poc.py compare` 를 쓴다. 후보는 spec §PoC 후보의 셋이다. 캡처는 `~/scratch/limn-badge-drag-2026-11-19/` 에 두고 응답에 절대 경로로 넣는다. PoC 서버는 `127.0.0.1` 에만 묶고 확인이 끝나면 내린다.
- [ ] **Step 3: PR 을 만든다** — 소유자가 머지한다. PR 본문에 어느 기기군에서 무엇을 보였는지, 로컬 게이트 결과, 에이전트 계약이 바뀌지 않았음을 적는다. `link_pull_request` 로 스레드에 건다.

---

## 시공에서 달라진 것

계획이 정한 범위와 결정은 그대로이고, 아래 넷은 시공이 정한 자리와 이름이다.

- **`badgeDrop` 의 인자 이름은 `moveX`·`moveY` 다.** `dx`·`dy` 는 `limn/plain-names` 가 거절한다(세 글자 미만, 허용 목록 밖).
- **끌 수 있는 핀의 판정은 `composer` 가 한다.** `pdf` 는 `composer` 를 import 할 수 없는데(§모듈 경계) 그 판정은 핀 레코드와 위치 다시 잡기 상태를 읽어야 하므로, `composer/flow-repick.ts` 의 `badgeMovePin(id, mouse)` 이 답하고 `pdf` 는 `PageSelection` 이음매로 묻는다. 이음매는 셋이 되었다 — `badgeMove`·`repickFromBadge`·`cancelRepick`.
- **`followRange`·`refetchSnip` 의 서명은 바뀌지 않았다.** 역할을 인자로 받는 대신 `rangeRole(owner)` 이 소유자 동일성으로 가린다. `view-excerpt.ts` 가 두 종류의 소유자로 부르는 자리가 그대로 남는다.
- **줄 핀은 제 상자가 없어도 끌린다.** PoC 를 실제 서버에서 돌리다가 찾았다 — 에이전트가 `frac` 없이 저장한 핀은 마크가 `boxes` 로 멀쩡히 그려지는데 배지만 끌리지 않았다. 보낼 사각형이 짚개이므로 줄 핀에는 저장된 상자가 필요 없다. 상자의 크기를 요구하는 것은 영역 핀뿐이다.
