# GET 영속 쓰기 방어 구현 계획

범위: [승인된 설계](../specs/2026-11-05-get-write-guard.md), [ADR-0027](../../adr/0027-get-write-guard.md)의 B안. 기준 트리는 `818e3134`이며 아래 줄 번호는 이 트리 기준이다. 화면·번역·원고 형식·기존 역할은 바꾸지 않는다.

## Task 1: HTTP 읽기 경계와 저장 능력 분리

- [x] Step 1: `web/handler.py:300-315`에서 GET 전체(입장·오류 포함)를 읽기 전용 실행 범위로 묶는 회귀 검사를 먼저 쓴다. `web/routes.py:16-25`의 GET 사람 기록 협력자를 제거한다. Expected: GET에서 writer를 구하거나 쓰기 worker를 예약하려는 주입 결함은 디스크 변경 전에 거절된다. 향후 HEAD에도 같은 범위를 적용한다.
- [x] Step 2: `pins/store.py:88-130,197-200`의 읽기·메모리 재동기화를 writer와 분리하고 `pins/runtime.py:225-266`의 읽기 경로에는 읽기 객체만 제공한다. writer 발급과 영속/예약 경계는 읽기 범위를 거절한다. Expected: writer 없는 GET에서도 기존 필드·정렬·현재 위치를 유지한다.

## Task 2: 실제 변경 때만 사람 기록

- [x] Step 1: `/` (`viewer/routes.py:99`)와 전체 meta (`documents/routes.py:21`)에서 기록 연결을 뺀다. `web/handler.py:360-391`은 성공한 실제 변경 뒤에만 사람을 기록한다. POST pick·실패·없는 핀·멱등 재요청은 등록 근거가 아니다. Expected: 새 독자는 열기만으로 등록되지 않고, 편집자의 첫 핀 변경은 등록된다. 기존 사람·역할은 보존한다.

## Task 3: 핀 조회와 독립 유지 실행

- [x] Step 1: `pins/listing/routes.py:13-31`의 정리 호출을 제거한다. `pins/store.py:197-200`의 snapshot은 메모리 계산으로 바꾼다. Expected: 이동 anchor·새 mtime·anchor 없는 옛 핀·손상 레코드·없는 단일 핀에서도 GET은 파일의 bytes/inode/mtime을 유지한다.
- [x] Step 2: `pins/application.py:156-162`, `server.py:397-419`, `runtime/resources.py:48-60`에 시작 및 60초 주기 유지 수명을 연결한다. 유지 실행은 단일 실행 잠금으로 겹침을 막고, 렌더·읽기·쓰기 실패에 원본을 보존하며 다음 주기에 재시도한다. Expected: 핀·pins.md·만료/그림자 휴지통이 수렴하고, 변화 없는 주기는 교체도 하지 않는다. HTTP pins.md는 즉시 계산한다.

## Task 4: 비교 GET과 제한된 읽기

- [x] Step 1: `revisions/jobs.py:49-56,199-214,350-369`에서 기존 루트 조회와 POST 생성 경로를 나눈다. Expected: 루트 없음은 idle/not-ready이며 폴더가 생기지 않는다. 기존 비교도 읽기만 한다.
- [x] Step 2: Git 읽기의 기존 시간·출력·입력·캐시 상한을 유지한다. HTTP 읽기 동시성은 프로세스당 최대 4개로 제한하고 대기는 새 작업을 만들지 않는다. Expected: 쓰기 예약 없이 bounded Git 조회만 실행한다.

## Task 5: 로그와 경로 인자 한도

- [x] Step 1: `pins/listing/routes.py:29-31`, `security/access.py:675-689`, `web/handler.py:377-391`의 정수 변환 전에 경로 인자 길이를 제한한다. Expected: 5,000자리 핀 번호는 4xx이며 traceback을 만들지 않는다.
- [x] Step 2: `web/handler.py:298`, `pins/store.py:122-126`의 반복 오류·손상 경고를 제한된 메모리의 중복 억제로 묶는다. Expected: 같은 결함은 한 번 출력하고 서로 다른 원인도 정해진 총량을 넘지 않는다. 로그에 토큰을 남기지 않는다.

## Task 6: 전수 검사·문서·최종 검증

- [x] Step 1: READ_PATHS와 route family 등록 목록에서 빠짐을 잡는 계약 검사를 둔다. 사람(owner/editor)·viewer·token agent·입장 거절, Fetch Metadata 다섯 상태, GET/HEAD, 정상·오류·304·없는 핀, 비교 루트 유무와 모든 쓰기 유발 상태를 교차한다. Expected: 상태와 원고 트리 bytes/inode/mtime 및 폴더가 동일하고 컴파일·유지 예약이 없다.
- [x] Step 2: 각 계약마다 옛 쓰기를 잠시 복구해 새 검사가 실패하는 mutation proof를 남기고 커밋 파일로 복구한다. 기존 GET 저장 검사는 승인된 의미 변경에 맞춰 수정 이유를 커밋에 적는다. Expected: 보안 검사가 실제 회귀를 검출한다.
- [x] Step 3: `docs/handbook/{api,domain,build-sync,operations,architecture,verification,index}.md`, `SECURITY.md`, `skill/SKILL{,.ko}.md`, `CHANGELOG.md`를 현재 계약으로 맞춘다. Expected: 새 독자의 미등록·멘션 제한과 viewer의 명시 등록, 디스크 pins.md의 약 60초 지연(지연/실패 시 더 길어짐)이 명확하다. 틀린 화면 문구는 고치지 않고 보고한다.
- [x] Step 4: 요청된 ruff 두 검사, mypy 두 플랫폼, boundaries, typecheck, strict ratchet, core pytest 4 workers, architecture, instances shell, viewer/markdown/CSP browser, Handbook check를 모두 실행한다. Expected: 실패 0, 통과·건너뜀 수와 환경 한계를 보고한다. push/PR은 하지 않으며 마지막 커밋의 별도 Codex 리뷰는 소유 세션이 수행한다.

## 실행 증거와 검토 메모

구현은 별도 writer를 얻지 않는 PinReader 조회와 HTTP 읽기 범위로 연결했다. 캐시·Git 읽기는 유지하고 HTTP GET 실행은 4개로 제한했다. 유지 실패 원복은 준비 파일과 원본 hard link를 사용한다. 손상 원본의 backup도 같은 준비 묶음에 포함한다. 변경 없는 Markdown은 생성 시각만 달라져도 다시 쓰지 않는다.

각 계약의 mutation proof는 구현 커밋 뒤 옛 쓰기 또는 결함을 임시로 넣고 검사가 실패한 뒤 `git checkout -- <file>`로 복구했다: 읽기 writer 제한 제거, HTTP 읽기 범위 제거, GET 사람 기록 복구, snapshot의 저장 트랜잭션 복구, 유지 실행 생략, 비교 루트 무조건 생성, Fetch Metadata 없는 요청 거절, 경로 길이 제한 제거, 진단 중복·상한 제거. 각 mutation은 별도 pytest 실행에서 실패했다. 읽기 범위가 사람 기록의 PermissionError를 기존 OSError 경고로 삼킬 수 있어, 사람 기록 진입점에도 writer 검사를 올렸다. 화면은 고치지 않았다.

브라우저는 임시 원고·상태와 127.0.0.1의 두 서버에서 Chromium·Firefox 각각 8개 진입 방식과 두 출처 관계(총 32개)를 검사했다. script/img/link의 JSON 응답은 브라우저의 opaque-response 차단으로 response 이벤트 없이 끝날 수 있어 onload/onerror 완료와 서버 수신 기록을 함께 확인한다. boot·실제 light poll·unload에서 자동 POST가 없고 상태·원고 파일의 bytes/inode/mtime이 같다.

검증: ruff check·format(594개 파일), mypy 두 플랫폼(173개 파일), boundaries, typecheck, strict ratchet(오류 0), core(3,754 통과·1 건너뜀·6,516 subtests), architecture(111 통과), instance 셸(222 통과), 지정 browser 및 새 외부 진입 검사(75 통과·WebKit 3 건너뜀·132 subtests), Handbook check와 git diff --check 통과. 새 계약 파일만 실행하면 13개·3,800 subtests가 통과한다. 요청에서 요구한 최종 커밋의 독립 Codex 리뷰는 소유 세션으로 돌려준다. 원격 push·PR·상시 인스턴스 조작은 하지 않았다. 검토 서버는 만들지 않았으며 수정 정본 Markdown을 직접 검토한다.

GET inventory와 실제 코드의 불일치는 찾지 못했다. 구현 중 새 읽기 범위의 PermissionError를 사람 기록의 옛 OSError 복구가 삼키는 점은 기록 진입점의 writer 검사로 고쳤다. 화면/문구는 그대로다. mentions.js의 "이 뷰어를 연 테일넷 사람만" 안내와 대응 영어 번역, unknown_assignee 오류의 같은 안내, CLI 멤버 목록의 LAST SEEN은 이제 실제 변경 기록의 의미와 맞지 않아 소유자 PoC 대상이다. 실제 Tailscale Serve·trusted-proxy 브라우저 세션과 WebKit 실행은 이 환경에서 검증하지 않았다. 새 기능 간 import는 없고 공통 platform의 읽기 효과 범위만 각 소유 기능에 연결했다.

최종 POST 점검에서 동기 재빌드의 새 발행이 사람 등록 관찰값을 세우지 않던 누락을 고쳤다. 실제 임시 파일을 발행하는 컴파일 adapter fixture로 `people.json`이 없다는 실패를 먼저 확인하고, 성공한 새 발행이 관찰값을 세운 뒤 통과함을 확인했다. busy·변경 없음·실패는 등록하지 않는다. 마지막 제품 커밋 뒤 core(3,754 통과·1 건너뜀·6,516 subtests), 지정 browser+외부 진입(75 통과·3 건너뜀·132 subtests), architecture(111 통과)와 정적·타입 게이트를 재확인했다.
