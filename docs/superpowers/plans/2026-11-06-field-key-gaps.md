# 글 칸의 스크롤 키: 남은 빈틈 둘 (#452)

범위: [2026-11-06-field-keys-on-the-host.md](2026-11-06-field-keys-on-the-host.md)(#449, 안 A)의 후속이다. 소유자 결정(2026-11-06)은 #449의 방식, 즉 기본 동작만 막고 캐럿은 옮기지 않는 방식을 기준으로 두고 남은 빈틈 둘만 같은 방식으로 메우는 것이다. 출발점은 `origin/main` `9200e9de`다. #449의 설계와 계획은 승인된 기록이라 고치지 않는다. 캐럿을 옮기던 다른 구현(브랜치 `fix/field-keys-414`)은 쓰지 않는다.

## 규칙

`fieldScrollKey`([`js/layout.js`](../../../src/limn/viewer/js/layout.js))가 두 경우를 더 막는다.

1. **조합 중인 이동 키.** #449가 막는 키(호스트별 집합 그대로: `PageUp`·`PageDown`은 모든 호스트, `Home`·`End`는 macOS)는 조합 중(`isComposing`, keyCode 229)이어도 기본 동작을 막는다. `imeKey` 예외를 뺀다. 이 네 키에서 `imeKey`가 참이 되는 것은 조합 중일 때뿐이다(`imeTail`은 Enter·Esc만 본다). 조합 자체(글자, 확정, 캐럿)는 건드리지 않는다. 입력기가 받아 간 키는 `Process`로 오므로 이 집합에 들지 않는다.
2. **읽기 전용 칸의 이동 키.** 초점이 있는 글 칸이 `readOnly`면 화살표·`Home`·`End`·`PageUp`·`PageDown`·`Space`의 기본 동작을 모든 호스트에서 막는다. `Shift+Space`도 막는다. Shift와 이동 키는 바깥을 움직이지 않으므로 그대로 두고(Firefox는 선택을 넓히고 Chromium은 읽기 전용 칸에서 선택을 그대로 둔다), Ctrl·Alt·⌘는 호스트의 단축키라 그대로 둔다. 읽기 전용이 되는 칸은 둘이다. 저장이 도는 동안의 판정 이유 칸(`pvReasonSave`)과, 범위의 원문을 읽기 전까지의 제안 문안 칸(`suggestRead`)이다.

보이는 것보다 많은 칸과 칸 밖의 키는 #449처럼 그대로 둔다.

## 실측 (main `9200e9de`, Linux Chromium·Firefox, macOS 흉내)

macOS 흉내는 Linux Chromium에 `navigator.platform=MacIntel`을 두고 키를 CDP `Input.dispatchKeyEvent`에 Cocoa 명령(`scrollToBeginningOfDocument` 등, Playwright의 macOS 경로와 같다)과 함께 보낸 것이다.

| 경우 | 키 | Chromium Linux | Chromium macOS 흉내 | Firefox |
|---|---|---|---|---|
| 이유 칸, `나` 조합 중, 3쪽, 1920×1080 | `Home` | +0 | −2208px, 1쪽, 칸 사라짐 | 조합을 몰 수 없음 |
| 같음 | `End` | +0 | +5138px, 칸 사라짐 | |
| 같음 | `PageUp` · `PageDown` | +194 · +873 | +194 · +873 | |
| 저장 중 이유 칸, 맞춤의 1.6배 확대(153%), 1440×900 | 화살표 | ±40px(←·→는 옆으로) | ±40px | +0, 캐럿 이동 |
| 같음 | `Space` · `Shift+Space` | +715 · −715, 칸 사라짐 | 같음 | +0 |
| 같음 | `Home` · `End` | −1671 · +9684, 칸 사라짐 | #449가 막음 | +0 |
| 같음 | Shift+이동 키 | +0(선택 그대로) | +0 | +0, 선택 넓힘 |
| 같음 | `Ctrl+Home`·`Ctrl+End` | 칸 사라짐 | 칸 사라짐 | +0 |
| 같음 | `⌘↑`·`⌘↓` | | 칸 사라짐 | |
| 제안 문안 칸(원문 읽는 중), 673×841 시트 | 화살표 · `Space` · `Home` · `End` | `#right` ±40 · +172 · −193 · +163 | | |

조합 중 키의 기본 동작을 막아도 조합은 열린 채 남았고, 그 뒤 확정한 음절과 다음 음절이 제자리에 들어갔다(`가나다`).

## 작업

- [x] **T1. `fieldScrollKey`.** `imeKey` 예외를 빼고, `readOnly` 분기와 `READ_ONLY_KEYS`를 더한다.
- [x] **T2. 시험.** `test_viewer_verdict_panel.py`의 `ReasonFieldStill`(이 호스트)·`ReasonFieldStillMac`(macOS 흉내)·`ReasonFieldStillFirefox`, `test_viewer_suggest.py`의 `SuggestReadOnlyKeys`. 조합 시험은 키마다 다음 음절을 확정해 마지막 글까지 본다. Firefox에서는 Playwright가 입력기를 몰지 못하므로 조합 중 표시가 붙은 keydown에 대한 뷰어의 답(`defaultPrevented`)을 본다. macOS 흉내의 키는 `helpers_browser.mac_press`다.
- [x] **T3. macOS CI.** `macos-browser` 선택에 위의 Chromium 클래스 셋을 넣는다.
- [x] **T4. Handbook.** `viewer.md` §키와 초점의 **글 칸의 스크롤 키**에 두 경우, §조합을 끝내는 키에 한 문단, §판정 핀 **쓰기**에 한 조각.
- [x] **T5. CHANGELOG.**

## 돌연변이

| 바꾼 것 | 실패한 시험 |
|---|---|
| `imeKey(e)` 예외를 되살림 | 조합 시험 셋(이 호스트·macOS 흉내·Firefox) |
| `readOnly` 분기를 뺌 | 읽기 전용 시험 넷(이유 칸 셋, 제안 칸) |
| 집합에서 `ArrowLeft`를 뺌 | 이유 칸 읽기 전용 셋 |
| 집합에서 `Space`를 뺌 | 이유 칸 읽기 전용(Chromium 둘), 제안 칸 |
| 집합에서 `End`를 뺌 | 이유 칸 읽기 전용(Chromium 둘), macOS 흉내 조합, 제안 칸 |
| 읽기 전용 칸의 Shift 예외를 뺌 | 이유 칸 읽기 전용 셋(`Shift+Home`이 막힘) |
| `Shift+Space`를 Shift 예외에 넣음 | 이유 칸 읽기 전용(Chromium 둘), 제안 칸 |

## 남는 것

- 실제 macOS 한글 입력기에서 막힌 keydown 뒤에도 조합이 바르게 확정되는지는 확인하지 못했다. macOS CI가 Chromium에서 같은 시험을 돌리지만 CDP의 조합은 실제 입력기가 아니다.
- 읽기 전용 칸의 `Ctrl+Home`·`Ctrl+End`·`⌘↑`·`⌘↓`·`Alt+↓`는 아직 바깥을 움직인다. #449처럼 수정 키와 함께 눌린 키는 호스트의 것으로 두었다. 막으려면 호스트별 단축키 표가 필요하다(Linux의 `Alt+←`는 뒤로 가기다).
- WebKit은 이 머신에서 뜨지 않아 CI에 맡긴다.
