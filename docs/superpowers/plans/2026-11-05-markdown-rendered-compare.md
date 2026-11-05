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

## Task 7: 리뷰 지적(2026-11-06)

- [x] Step 1: 두 쪽 읽기의 `ls-tree` 에 `:(literal)` pathspec. 시험 `test_a_file_whose_name_reads_as_pathspec_magic_has_its_sides`(`:plan.md`·`:(glob)*.md`). 변이: 맨 경로 → `null`·`source_unreadable`, 실패.
- [x] Step 2: 뺀 블록과 옮긴 자리 줄은 새 판에서 옛 상자를 대신하는 상자에 선다(`mdcPair`·`mdcPlace`). 시험 `DeletedNestedList`(하위 목록, 느슨한 목록의 항목, 통째로 지운 표). 변이: 부모 태그로만 가르기 → 실패.
- [x] Step 3: 지운 목록 항목의 제 글은 옮긴다(`mdcOwn`). 시험 `DeletedListImage`. 변이: `cloneNode(true)` → 그림이 크기도 대체 글도 얻지 못해 실패.
- [x] Step 4: 강조·링크의 사본과 줄 안 수식의 조각은 열쇠에서 한 덩이, 링크 사본은 대상을 다시 세지 않는다, 대체 글은 공백을 접는다. 시험 `RewrappedInsideInline`, `AltRewrapped`. 변이: 합치지 않기, 링크 사본 세기, 수식 조각을 맞닿을 때만 합치기, 대체 글을 그대로 견주기 → 실패.
- [x] Step 5: 표 칸의 정렬이 열쇠에 들고 `표 칸 정렬이 바뀜` 이라고 적는다. 시험 `TableAlignment`, 순수 시험의 정렬 두 경우. 변이: 정렬을 열쇠에서 빼기, 그 말을 빼기 → 실패.

## Task 8: 리뷰 지적 2차(2026-11-06)

- [x] Step 1: 목록 항목의 그림·링크·대체 글과 바뀐 링크 표시는 항목 제 글의 경계(`mdcOwnPart`)까지다. 시험 `ChildBlockRefs`. 변이: `mdcRefs` 의 `closest('li')`, 대체 글의 `closest('li')`, `mdcLinkMarks` 의 경계 빼기 → 각각 실패.
- [x] Step 2: 같은 종류 인용·목록의 갈라짐과 합쳐짐(`mdcRegroup`, 이웃한 두 블록의 고침과 그 말, 한국어·영어). 시험 `BoxesSplit`(Chromium, 영어 화면), 순수 시험의 아홉 경우. 변이: `mdcRegroup` 빼기 → 브라우저·순수 시험 실패, 사이에 더한 블록을 보지 않기 → 순수 시험 실패.
- [x] Step 3: 문서가 바뀐 메시지의 [변경 보기]가 Markdown 문서에서 여는 탭을 Handbook §새 소식과 §변경 보기가 같게 말한다. 시험 `UpdateMessageRange`(문서에서, 그린 비교에서, 소스 diff에서). 변이: 메시지 범위를 소스 diff로 열기 → 앞의 둘 실패, Markdown 범위를 탭과 상관없이 그린 비교로 열기 → 셋째 실패.
- [x] Step 4: `HeadingJumpFirefox` 의 한 번 실패(2,987px)는 스크롤의 프레임보다 먼저 온 그림 불러오기가 스크롤 전의 읽던 자리를 되돌린 것이다. 프레임을 늦추면 두 엔진에서 재현된다. 읽던 자리에 읽은 때의 스크롤 위치(`top`)를 적고, 그림이 자리를 되돌릴 때 단의 위치가 그와 다르면 되돌리지 않고 지금 자리를 읽는다(`mdSpotBack`). 자리 크기가 바뀌기 앞에 자리를 읽는 첫 시도는 틀렸다. 불러오기 이벤트 때는 그림이 이미 새 크기로 놓일 수 있어(기억한 크기로 그린 바뀐 그림) 밀린 자리를 읽었고, `ChangedOnDisk`(두 엔진)와 `ReadingSpotChangedImage` 가 실패했다. 시험 `HeadingJump` 의 프레임을 잡아 둔 Home 둘(불러옴·실패, Chromium·Firefox). 변이: `mdSpotBack` 의 위치 비교 빼기 → 넷 모두 실패.

## 열린 것

- **D6의 B: 핀 단위 합성 판.** 서버가 ADR-0005 §5의 합성을 파일 하나의 글에 쓰고 `GET /api/revision-source` 가 선택 `pin` 을 받는다. 에이전트 계약에 더하는 일이라 그 변경에서 api.md와 ADR-0005의 덧붙임을 고치고, 핀의 [변경 보기] 기본을 그린 비교로 바꾼다.
- **대비 걷기.** 칩·범례·안내 줄·옮긴 자리 줄은 `test_viewer_contrast.py` 의 걷기가 열지 않는다(`NOT_WALKED`). 변경 보기의 그린 비교 장면을 걷기에 더하는 일이 남았다.
