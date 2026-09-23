# Lucide 아이콘 (vendored)

뷰어의 아이콘은 [Lucide](https://github.com/lucide-icons/lucide)에서 가져왔다. 쓰는 아이콘의 SVG 요소만 `scripts/pin_server.py` 의 `LUCIDE` 사전에 인라인 문자열로 넣었다. 서버가 파일을 따로 주지 않고 외부 CDN 도 쓰지 않는다 — 뷰어는 테일넷 안에서만 돈다. 이 디렉토리에는 라이선스와 출처 기록만 둔다.

| 항목 | 값 |
| --- | --- |
| 패키지 | `lucide-static@1.47.0` (npm `latest`, 2026-09-17 배포) |
| 저장소 | <https://github.com/lucide-icons/lucide> |
| 받은 방법 | `npm pack lucide-static@1.47.0` → `package/icons/<이름>.svg` 에서 `<svg>` 안의 요소만 옮겨 적었다. 공백만 한 칸으로 줄였고 좌표는 그대로다 |
| tarball sha256 | `b47744c9f7b385c25fb27d212cf9830947030a57a635f8b11a5473a72ec57cfd` |
| 라이선스 | ISC. Feather 에서 온 아이콘은 MIT — [`LICENSE`](LICENSE) (패키지의 `LICENSE` 원본 그대로, sha256 `b495047b…29c57`) |

그릴 때는 원본 `<svg>` 의 속성을 그대로 쓴다: `viewBox="0 0 24 24"`, `fill="none"`, `stroke="currentColor"`, `stroke-width="2"`, `stroke-linecap="round"`, `stroke-linejoin="round"`. 크기는 CSS 로 14–16px 로 줄여 글자색을 따른다.

## 쓰는 아이콘

| 이름 | 쓰는 곳 |
| --- | --- |
| `check` | 닫힌 핀 행의 머리, 문서 목록에서 지금 문서 |
| `chevron-down` · `chevron-right` | 보관함 구획 머리의 접기·펼치기, 카드 접기(좁은 화면), [문서] 버튼 |
| `chevron-up` · `chevron-left` | [핀 N] 패널·시트 펴기·접기 방향 |
| `circle-question-mark` | 도움말 버튼 |
| `clock` | '처리 중' 배지 |
| `copy` | 위치 복사 버튼 |
| `ellipsis` | 더보기 버튼(좁은 화면) |
| `minus` · `plus` | PDF 축소·확대, 범위 한 줄씩 좁히기·넓히기 |
| `moon` · `sun` · `sun-moon` | 화면 테마(어둡게·밝게·시스템) |
| `move-vertical` | '줄 +N 이동' 배지 |
| `pencil` | '수정됨' 배지 |
| `trash-2` | 삭제한 핀 행의 머리 |
| `triangle-alert` | '위치 잃음' 배지 |
| `x` | 알림·안내 닫기 |

## 갱신

1. `npm pack lucide-static@<새 버전>` 을 받아 위 표의 아이콘 `.svg` 에서 `<svg>` 안의 요소를 `LUCIDE` 에 다시 옮긴다. 이름이 바뀐 아이콘이 있다(예: `alert-triangle` → `triangle-alert`, `help-circle` → `circle-question-mark`). 새 이름을 쓴다.
2. `LICENSE` 를 새 패키지의 것으로 덮어쓰고 위 표의 버전·sha256 을 고친다.
3. 아이콘을 더하거나 빼면 `LUCIDE_VERSION`·위 표·`LUCIDE` 를 함께 고친다. 회귀 테스트(`FrontendIcons`)가 셋이 맞는지 본다.
