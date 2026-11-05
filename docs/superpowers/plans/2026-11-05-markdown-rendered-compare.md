# Markdown 그린 비교 구현 계획

범위: [승인된 설계](../specs/2026-11-05-markdown-rendered-compare.md), [ADR-0031](../../adr/0031-markdown-rendered-compare.md)의 D1–D8(D6은 C). 출발점은 PoC 브랜치 `poc/md-rendered-compare` 이고, 같은 브랜치를 `origin/main`(15f80d90) 위로 옮겨 구현으로 만든다.

각 시험 묶음은 그 기능 줄을 되돌리면 실패해야 한다. 묶음마다 변이를 적고, 돌려서 실패를 본다.

## Task 1: 브랜치와 승인 기록

- [x] Step 1: PoC 커밋 열한 개를 `origin/main` 위로 옮긴다. #427의 옛 판 두 커밋(등록한 경로, 점 폴더)은 main의 최종판이 대신하므로 뺀다. 두 쪽 읽기는 main의 등록한 경로(`registered_repo`·`registered_file`, `files_pathspec` 의 제외 pathspec, 점 이름 규칙)를 그대로 쓴다. Expected: `test_revision_source.py` 통과.
- [x] Step 2: ADR-0031 `승인됨`(결정일, 결정자, 결정마다의 상태, D6 정함, B는 결과에 열림), ADR 목록의 행, 설계 머리와 §정한 결정. Expected: `git diff --name-status origin/main...HEAD -- ':(glob)docs/adr/[0-9][0-9][0-9][0-9]-*.md'` 가 `A` 한 줄이다.

## Task 2: 렌더러의 문맥

- [x] Step 1: `mdRender` 와 그 아래 함수가 그리기 문맥(`MdRx`)을 받는다. 문서 화면의 문맥은 `MD` 다. Expected: `test_viewer_markdown*.py` 가 고치지 않은 채 통과한다.
- [x] Step 2: 비교는 쪽마다 `mdRx` 로 짓고 일 2,000개마다 차례를 넘긴다. 시험 `BuildPauses`. 변이: `mdcBuild` 가 `MD` 를 문맥으로 쓰기, 차례를 넘기지 않기 → 둘 다 실패.

## Task 3: 승인된 화면

- [x] Step 1: D6 = C. 핀의 [변경 보기]는 소스 diff로 열고 [그린 비교]가 옆 탭, 그 탭은 커밋 전체와 핀의 블록 테두리, 커밋 일부를 가진 핀이면 그렇다고 적는다. 시험 `PinBlocks`(2). 변이: 핀을 그린 비교로 열기, 커밋 전체라는 말 빼기 → 실패.
- [x] Step 2: 한 단만. 두 단 후보와 그 CSS·문구·시험을 뺀다.
- [x] Step 3: 그린 블록 그대로. 숨은 문자 상자가 열쇠와 낱말에, 머리 정보·따로 선 수식이 제 종류의 줄 블록, 줄 안의 수식·인라인 HTML이 코드와 다른 종류, 줄 span은 구조가 아니다. 시험 `HiddenFrontMath`(Chromium·Firefox), `Rewrapped`. 변이: 상자를 열쇠·낱말에서 빼기, `.md-front` 를 단위에서 빼기, 코드를 태그만으로 이름 붙이기, 줄 span을 구조로 세기 → 실패.
- [x] Step 4: 범위의 상태 줄에 커밋·파일 수. 시험 `RangeDisplay`(Chromium·Firefox). 변이: 상태 줄에서 `REV.rangeN` 빼기 → 실패.
- [x] Step 5: 한도와 접근성. 시험 `SidePastLimit`(1 MiB를 넘는 쪽 → `role="status"` 안내와 [소스 diff 보기]), `TabsAndFocus`(탭의 이름·역할·눌림, 바뀐 곳 이동 묶음, 블록의 종류를 읽고 범례는 읽지 않음, Enter 뒤의 초점). 변이: 쪽의 `reason` 무시하기, 형식을 바꿀 때 초점 버리기 → 실패.

## Task 4: 경로 시험

- [x] Step 1: PoC의 경로 시험(두 쪽, 범위, 창, 크기, 쓰기 없음, `git_line_starts`, 등록한 경로)이 main의 코드에서 통과한다.
- [x] Step 2: 정확히 1 MiB인 쪽은 줄을 준다. 그 커밋에서 그 이름이 폴더인 쪽은 `not_a_file` 이고 아래 파일은 읽지 않는다. 변이: 한도에 닿은 쪽 거절, ls-tree가 이름 붙인 무엇이든 파일로 읽기 → 실패.

## Task 5: 문서 동기화

- [x] Step 1: Handbook [viewer.md](../../handbook/viewer.md) §변경 보기(그린 비교)·§그리기(그리기 문맥)·§숨은 문자, [api.md](../../handbook/api.md)(`GET /api/revision-source` 행과 오류, `doc=` 표, §두 커밋 사이), [verification.md](../../handbook/verification.md) §두 판 읽기와 그린 비교, [index.md](../../handbook/index.md) 파일 지도. Expected: Handbook 출판 검사 종료 코드 0.
- [x] Step 2: CHANGELOG `Unreleased` 의 `### Added`, 설계의 §구현에서 바꾼 것·§검증.

## Task 6: 검증과 PoC

- [x] Step 1: ruff check·format, mypy 두 플랫폼, 경계 검사, `npm run typecheck`, strict ratchet, `pytest -n 6 -m "not browser and not tex"`, `-m tex`, 바꾼 브라우저 시험 파일과 `test_viewer_markdown*.py`·변경 보기 브라우저 시험(`-n 4`).
- [x] Step 2: 테일넷 PoC(`limn-poc-mdcmp`)를 이 코드로 다시 띄우고 200과 새 코드를 확인한다. 1440×900·390×844 전후 캡처(핀의 [변경 보기], [그린 비교]).

## 열린 것

- **D6의 B: 핀 단위 합성 판.** 서버가 ADR-0005 §5의 합성을 파일 하나의 글에 쓰고 `GET /api/revision-source` 가 선택 `pin` 을 받는다. 에이전트 계약에 더하는 일이라 그 변경에서 api.md와 ADR-0005의 덧붙임을 고치고, 핀의 [변경 보기] 기본을 그린 비교로 바꾼다.
- **대비 걷기.** 칩·범례·안내 줄·옮긴 자리 줄은 `test_viewer_contrast.py` 의 걷기가 열지 않는다(`NOT_WALKED`). 변경 보기의 그린 비교 장면을 걷기에 더하는 일이 남았다.
