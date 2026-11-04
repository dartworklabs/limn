# GET 영속 쓰기 방어 구현 계획

범위: [승인된 설계](../specs/2026-11-05-get-write-guard.md), [ADR-0027](../../adr/0027-get-write-guard.md)의 B안. 기준 트리는 `818e3134`이며 아래 줄 번호는 이 트리 기준이다. 화면·번역·원고 형식·기존 역할은 바꾸지 않는다.

## Task 1: HTTP 읽기 경계와 저장 능력 분리

- Step 1: `web/handler.py:300-315`에서 GET 전체(입장·오류 포함)를 읽기 전용 실행 범위로 묶는 회귀 검사를 먼저 쓴다. `web/routes.py:16-25`의 GET 사람 기록 협력자를 제거한다. Expected: GET에서 writer를 구하거나 쓰기 worker를 예약하려는 주입 결함은 디스크 변경 전에 거절된다. 향후 HEAD에도 같은 범위를 적용한다.
- Step 2: `pins/store.py:88-130,197-200`의 읽기·메모리 재동기화를 writer와 분리하고 `pins/runtime.py:225-266`의 읽기 경로에는 읽기 객체만 제공한다. writer 발급과 영속/예약 경계는 읽기 범위를 거절한다. Expected: writer 없는 GET에서도 기존 필드·정렬·현재 위치를 유지한다.

## Task 2: 실제 변경 때만 사람 기록

- Step 1: `/` (`viewer/routes.py:99`)와 전체 meta (`documents/routes.py:21`)에서 기록 연결을 뺀다. `web/handler.py:360-391`은 성공한 실제 변경 뒤에만 사람을 기록한다. POST pick·실패·없는 핀·멱등 재요청은 등록 근거가 아니다. Expected: 새 독자는 열기만으로 등록되지 않고, 편집자의 첫 핀 변경은 등록된다. 기존 사람·역할은 보존한다.

## Task 3: 핀 조회와 독립 유지 실행

- Step 1: `pins/listing/routes.py:13-31`의 정리 호출을 제거한다. `pins/store.py:197-200`의 snapshot은 메모리 계산으로 바꾼다. Expected: 이동 anchor·새 mtime·anchor 없는 옛 핀·손상 레코드·없는 단일 핀에서도 GET은 파일의 bytes/inode/mtime을 유지한다.
- Step 2: `pins/application.py:156-162`, `server.py:397-419`, `runtime/resources.py:48-60`에 시작 및 60초 주기 유지 수명을 연결한다. 유지 실행은 단일 실행 잠금으로 겹침을 막고, 렌더·읽기·쓰기 실패에 원본을 보존하며 다음 주기에 재시도한다. Expected: 핀·pins.md·만료/그림자 휴지통이 수렴하고, 변화 없는 주기는 교체도 하지 않는다. HTTP pins.md는 즉시 계산한다.

## Task 4: 비교 GET과 제한된 읽기

- Step 1: `revisions/jobs.py:49-56,199-214,350-369`에서 기존 루트 조회와 POST 생성 경로를 나눈다. Expected: 루트 없음은 idle/not-ready이며 폴더가 생기지 않는다. 기존 비교도 읽기만 한다.
- Step 2: Git 읽기의 기존 시간·출력·입력·캐시 상한을 유지한다. HTTP 읽기 동시성은 프로세스당 최대 4개로 제한하고 대기는 새 작업을 만들지 않는다. Expected: 쓰기 예약 없이 bounded Git 조회만 실행한다.

## Task 5: 로그와 경로 인자 한도

- Step 1: `pins/listing/routes.py:29-31`, `security/access.py:675-689`, `web/handler.py:377-391`의 정수 변환 전에 경로 인자 길이를 제한한다. Expected: 5,000자리 핀 번호는 4xx이며 traceback을 만들지 않는다.
- Step 2: `web/handler.py:298`, `pins/store.py:122-126`의 반복 오류·손상 경고를 제한된 메모리의 중복 억제로 묶는다. Expected: 같은 결함은 한 번 출력하고 서로 다른 원인도 정해진 총량을 넘지 않는다. 로그에 토큰을 남기지 않는다.

## Task 6: 전수 검사·문서·최종 검증

- Step 1: READ_PATHS와 route family 등록 목록에서 빠짐을 잡는 계약 검사를 둔다. 사람(owner/editor)·viewer·token agent·입장 거절, Fetch Metadata 다섯 상태, GET/HEAD, 정상·오류·304·없는 핀, 비교 루트 유무와 모든 쓰기 유발 상태를 교차한다. Expected: 상태와 원고 트리 bytes/inode/mtime 및 폴더가 동일하고 컴파일·유지 예약이 없다.
- Step 2: 각 계약마다 옛 쓰기를 잠시 복구해 새 검사가 실패하는 mutation proof를 남기고 커밋 파일로 복구한다. 기존 GET 저장 검사는 승인된 의미 변경에 맞춰 수정 이유를 커밋에 적는다. Expected: 보안 검사가 실제 회귀를 검출한다.
- Step 3: `docs/handbook/{api,domain,build-sync,operations,architecture,verification,index}.md`, `SECURITY.md`, `skill/SKILL{,.ko}.md`, `CHANGELOG.md`를 현재 계약으로 맞춘다. Expected: 새 독자의 미등록·멘션 제한과 viewer의 명시 등록, 디스크 pins.md의 약 60초 지연(지연/실패 시 더 길어짐)이 명확하다. 틀린 화면 문구는 고치지 않고 보고한다.
- Step 4: 요청된 ruff 두 검사, mypy 두 플랫폼, boundaries, typecheck, strict ratchet, core pytest 4 workers, architecture, instances shell, viewer/markdown/CSP browser, Handbook check를 모두 실행한다. Expected: 실패 0, 통과·건너뜀 수와 환경 한계를 보고한다. push/PR은 하지 않으며 마지막 커밋의 별도 Codex 리뷰는 소유 세션이 수행한다.
