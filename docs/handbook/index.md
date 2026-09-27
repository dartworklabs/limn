---
handbook_format: markdown
catalog_schema: 1
---

# Limn System Handbook

이 Handbook은 Limn의 설계 교과서다. 사람은 처음부터 순서대로 읽을 수 있고, 에이전트는 작업에 맞는 topic만 골라 읽는다. Limn의 모든 문서는 여기에 모여 있다. 저장소 밖 사용자를 위한 첫 안내는 [README.ko.md](../../README.ko.md)와 [README.md](../../README.md), 에이전트 작업 절차는 [SKILL.ko.md](../../skill/SKILL.ko.md)다. 결정 기록은 `docs/adr/`에 있다 (§결정 기록).

> **핵심**
>
> 무엇의 현재값이 어디에 있는지 모르겠으면 [purpose.md](purpose.md) §진실 소스부터 본다. 구조를 바꾸기 전에는 [architecture.md](architecture.md) §멈춤 신호를 확인한다. 코드를 쓰기 전에는 [code-style-roadmap.md](code-style-roadmap.md)의 코딩 규칙을 따른다.

## 목록

아래 순서가 처음 읽는 사람을 위한 읽기 순서다. role 열의 `purpose`·`architecture`·`verification`은 반드시 있어야 하는 세 책임이 어느 파일에 있는지 표시한다.

<!-- handbook-catalog:start -->
| role | file | responsibility | read or update when |
| --- | --- | --- | --- |
| purpose | [purpose.md](purpose.md) | Limn이 줄이는 비용, 사용자, 범위, 영역별 진실 소스 | 처음 읽을 때, 현재값의 정본 위치가 헷갈릴 때 / 제품 범위나 정본 위치가 바뀔 때 |
| architecture | [architecture.md](architecture.md) | 현재 구조(모듈의 층), 의존 방향, 채택한 설계 축, 불변식, 멈춤 신호 | 코드를 놓을 자리를 고르거나 의존성·저장·보안 경계를 건드리기 전 / 구조 단위·불변식·채택값이 바뀔 때 |
|  | [domain.md](domain.md) | 핀 용어, 상태와 전이, 역변환·범위 사다리·anchor 재동기화, 저장소 안전성, 작성자 귀속, 여러 문서 서버 규칙, 알려진 제약 | 핀 규칙이나 위치 계산을 고치기 전 / 상태·전이·위치 규칙·한도가 바뀔 때 |
|  | [viewer.md](viewer.md) | 뷰어 조작 요약, 레이아웃, 패널, 상태 표시, 협업 UI, 디자인 토큰·컴포넌트, 벡터 렌더링·확대, 화면 쪽 제약 | 뷰어 HTML·CSS·JS를 고치기 전 / 화면 규칙이나 가드 테스트가 바뀔 때 |
|  | [build-sync.md](build-sync.md) | 동기·비동기 재빌드, git pull, 자동 동기화 폴링, 위치 추정 est, 응답 다이어트, 보기 전용 PDF 감시 | 빌드·동기화·추정 코드를 고치기 전 / 빌드 상태나 폴링 규칙이 바뀔 때 |
|  | [api.md](api.md) | 에이전트 계약: HTTP API 전체, 요청 경계, 핀 레코드 스키마, pins.md 형식 | 에이전트 연동을 만들거나 요청 처리를 고치기 전 / 경로·필드·상태·pins.md 형식이 바뀔 때 |
|  | [operations.md](operations.md) | 서버 하나 실행: 요구 환경, 실행 인자, 포트, 보안 제약, tailscale serve, systemd, 상태 파일 | 서버를 띄우거나 운영 문제를 볼 때 / 실행 인자·상태 파일·보안 제약이 바뀔 때 |
|  | [instances.md](instances.md) | 원고별 인스턴스 관리자: limn 명령, 설정 키, 문서 탭, 업데이트·되돌리기, 포트, 환경 변수 | 인스턴스를 추가·업데이트·제거할 때 / limn 명령·설정 키·유닛 템플릿이 바뀔 때 |
| verification | [verification.md](verification.md) | 게이트별 측정 대상·적용 조건·실행·합격 기준·보장 범위, 없는 게이트 | PR 전과 리뷰할 때 / 테스트·CI 단계·합격 기준이 바뀔 때 |
|  | [workflow.md](workflow.md) | 설계에서 릴리스까지의 변경 흐름, 예외 경로, ADR 규칙, PR·CLA, 릴리스 | 작업을 시작하거나 PR·릴리스를 할 때 / 절차나 기여 조건이 바뀔 때 |
|  | [code-style-roadmap.md](code-style-roadmap.md) | 코딩 규칙 (R1–R10): 규칙 우선순위, 용어, 규칙마다 업계 이름·지금 코드의 예·확인하는 법, 남은 일 | 코드를 쓰거나 리뷰하기 전 / 규칙이 코드에서 지켜지는 모양이 바뀌거나 남은 일을 끝낼 때 |
<!-- handbook-catalog:end -->

## 파일 지도

어느 경로를 고치면 어느 topic을 함께 봐야 하는지 적는다. 전체 파일 목록이 아니라 의미 있는 경로만 담는다.

<!-- handbook-filemap:start -->
| 경로 패턴 | 책임 | 수정 trigger | 갱신 주체 |
| --- | --- | --- | --- |
| `src/limn/server.py` | 조립 지점: 실행 설정 `RunConfig`, 실행별 자원 소유자 `Runtime`(핀 잠금, 신원·사람 캐시, pull 나눠 쓰기, 감시 상태, 작업 목록, 뷰어, 감시 스레드와 `stop()`), 문서 목록을 `ServerApplication` 하나에 묶는다. 앱 메서드가 옮긴 모듈에 이 실행의 설정과 협력자를 넘기고, 핀 변경 협력자에 실행별 문맥 생성 함수를, `PinListing`·`PinMarkdown`에 조회 사실을, `PinLocationService`에 원고·캐시·겹침 조회 문맥을 묶으며 `web/app.py`의 `App` 프로토콜을 구현한다. `start()`는 실행 전용 처리기에 앱을 묶고 `StartedServer`로 소켓과 앱을 함께 돌려준다 | 시작·종료 순서, 앱이 넘기는 설정·협력자, `App`에 든 서비스의 이름·인자 변경 | architecture.md, operations.md, 연결된 모듈의 topic |
| `src/limn/service/context.py` | 여러 핀 기능이 쓰는 `PinContext`: 저장소·시계·알림·감사·파일 위치 협력자 | 기능이 받는 협력자와 저장·알림 경계 변경 | domain.md, api.md, architecture.md 불변식 4 |
| `src/limn/features/pins/lifecycle/*` | 닫기·다시 열기·확인·답글의 입력(`input.py`), HTTP 응답(`http.py`), 실행별 문맥을 받는 잠금·전이·알림(`service.py`). 다른 핀 동작과 함께 쓰는 순수 규칙은 현재 `pins/lifecycle.py`가 소유한다 | 네 경로의 파싱·응답·쓰기·알림·권한 흐름 변경 | api.md, domain.md, architecture.md, code-style-roadmap.md |
| `src/limn/features/pins/claims/*` | claim·unclaim의 시간 입력과 상한(`input.py`), 성공·409 응답(`http.py`), 실행별 문맥으로 저장하는 `PinClaims`(`service.py`). 순수 claim 규칙은 공통 `pins/lifecycle.py`에 있다 | 시간 검사·응답·저장 순서 변경 | api.md, domain.md, architecture.md |
| `src/limn/features/pins/trash/*` | 전체 비우기 확인 입력(`input.py`), 삭제·복원·영구 삭제·전체 비우기의 HTTP 응답(`http.py`), 실행별 문맥의 휴지통 변경·만료 정리(`service.py`). 순수 핀 전이는 공통 `pins/lifecycle.py`에 있다 | 휴지통의 쓰기·알림·감사 순서, 보존 기한, 응답 변경 | api.md, domain.md, architecture.md |
| `src/limn/features/pins/editing/*` | 만들기·편집의 줄·PDF 영역 위치 검사(`location.py`), 본문 입력(`input.py`), 응답(`http.py`), 저장·알림(`service.py`). 순수 편집 규칙은 `pins/edit.py`에 있다 | 위치·필드 검사 순서, 저장·알림·응답 변경 | api.md, domain.md, architecture.md |
| `src/limn/features/pins/listing/*` | 핀 목록·한 핀·휴지통의 쿼리 입력(`input.py`), HTTP 응답(`http.py`), 실행별 JSON 읽기(`service.py`), 요청·저장용 `pins.md` 입력 조립(`markdown.py`). 순수 응답·렌더 규칙은 `pins/view.py`·`pins/render.py`에 있다 | 조회 순서, 필터, 계산 필드, 휴지통 가시성, `pins.md` 바이트 변경 | api.md, domain.md, architecture.md |
| `src/limn/features/pins/location/*` | PDF 선택·원문 구간·겹침 조회의 입력(`input.py`), HTTP 응답·경고·거절 문장(`http.py`), 실행별 협력자(`service.py`), 역변환 결과와 판단(`resolve.py`), SyncTeX·pdftotext 및 토큰 캐시(`source.py`), 구간 렌더·겹침 조회(`range.py`) | 선택·구간 입력 순서, 위치 해석, 응답 변경 | api.md, domain.md, architecture.md |
| `src/limn/features/builds/*` | 빌드 상태·PDF·쪽 이미지 읽기와 재빌드 요청: 이름·스위치 검사(`input.py`), 응답 키 순서·로그 다이어트(`answer.py`), HTTP 입구·파일 읽기(`http.py`), 실행별 동기·비동기 선택(`service.py`), 잠금·상태·이력 기록(`run.py`), 원고 복사·LaTeX·PDF 렌더(`engine.py`). 공통 산출물·원본 지문·이력 사실은 `build.py`에 있다 | 빌드 조회·재빌드 응답, 파일 선택, 실행 연결 변경 | api.md, build-sync.md, architecture.md |
| `src/limn/features/sync/*` | `--git-pull`·원격 main 감시: 결과·감시 상태와 순수 판정(`rules.py`), Git 순서·여러 문서의 pull 공유·감시 실행(`run.py`), 실행별 문맥과 빌드·meta·감시 연결(`service.py`) | pull 거절·fast-forward, 감시 상태·재빌드 선택·실행별 연결 변경 | build-sync.md, api.md, architecture.md |
| `src/limn/features/collaboration/*` | 사람 목록 조회: 현재 역할·핀 스냅숏·알려진 사람 조합(`service.py`), `GET /api/people` 본문(`http.py`). 공통 `people.json`·역할 규칙은 `people.py`·`access.py`에 있다 | 사람 후보 조회 순서·응답 변경 | api.md §@태그·사람·이벤트, architecture.md |
| `src/limn/features/revisions/*` | Git 이력·비교 PDF의 입력 검사(`input.py`), 성공·거절 응답(`answer.py`), HTTP 입구(`http.py`), 실행별 비교 문맥·요청 실행(`service.py`). Git 이력·diff와 공통 타입(`core.py`), 스냅숏·격리 PDF 실행(`execution.py`), 비교 캐시·작업 상태(`jobs.py`)가 같은 기능에 있다 | 커밋·핀 검사 순서, 비교 응답·문맥 연결과 실행·캐시 규칙 변경 | api.md, architecture.md |
| `src/limn/store.py` | 핀 저장소: 잠금 아래 쓰기 순서(`transact`), `pins.jsonl`·`pins.md`·휴지통 쓰기, 손상 줄 보존, 핀 번호(`pins.seq`), 보관(clear). 서버를 모르고 협력자를 인자로 받는다 | 저장 순서·파일 이름·보존 규칙 변경 | domain.md §저장소 안전성, architecture.md 불변식 4 |
| `src/limn/pins/*` | 핀 도메인의 순수 코드: 상태 타입, 행위자 타입, 저장소가 믿는 레코드 모양 검사(`record.py`), 옮겨진 전이와 `pins.md`의 다시 열림 판단(`lifecycle.py`), 편집 판단과 새 핀 레코드, 핀 위치 규칙(`position.py`: 위치 추정·겹침·anchor 재동기화), JSON 정수·숫자 판정(`shapes.py`), `pins.md` 렌더(`render.py`: 입력 값 → 문자열, 겹침 배지), API가 레코드를 보이는 모양과 계산 필드(`view.py`: `public_record`·`state`·`GET /api/pins`·휴지통 본문) | 저장 레코드 필드 추가(`record.py`의 검사도 함께), 상태·전이·거절 규칙, 추정·겹침·줄 맞춤 규칙 변경, `pins.md` 열·표시·머리말 변경(계약) | domain.md, build-sync.md §위치 추정 (`est`), api.md §pins.md 형식, code-style-roadmap.md |
| `src/limn/guidance.py` | 에이전트가 읽는 토큰 파일 문구(`UNAUTHENTICATED`, `shell_path`, `token_file_curl`, `loopback_refused_text`) — 순수. `pins.md` 인증 줄과 헤더 없는 로컬 요청의 401이 같이 쓴다 | 인증 안내·401 문구 변경(계약) | api.md §인증, ADR-0007 |
| `src/limn/mapping.py` | 위치 계산의 순수한 절반: SyncTeX 표본에서 파일·줄 범위 선택(`synctex_range`), 범위 사다리, 블록 확장, 점수, anchor 찾기, 한 줄 줄이기(`flat`: `pins.md`와 알림 `excerpt`), 핀 파일 찾기(`pin_rel_path`) | 점수·단계·anchor·핀 파일 위치 규칙 변경 | domain.md, api.md §핀 파일의 위치 |
| `src/limn/locate.py` | 여러 핀 경로의 공통 위치: 핀 파일 찾기(`pin_location`), 저장된 핀 재동기화(`sync_all`), 겹침(`overlaps_by_id`·`overlaps_for_range`), 빌드 이력 읽기(`est_context`). 문서와 설정을 인자로 받는다 | 재동기화·핀 파일 위치·겹침 변경 | domain.md, build-sync.md, api.md §핀 파일의 위치 |
| `src/limn/build.py` | 빌드의 공통 사실: 쪽 디렉토리와 쪽 목록, 빌드 결과 값(`BuildOk`·`FailedBuild` 등)과 빌드 상태 이름(`BuildState`), 빌드 상태, 빌드 이력, 원고 지문과 `src_mtime`. 문서를 인자로 받으며 빌드 기능과 핀·문서 조회가 함께 읽는다 | 공통 빌드 상태·이력·지문·산출물 규칙 변경 | build-sync.md, architecture.md |
| `src/limn/gitrun.py` | git 프로세스를 띄우는 방식: 인자 목록, stdin·터미널 없음, `GIT_TERMINAL_PROMPT=0`, 서버의 `GIT_*` 변수 빼기, 시간 제한 | git 호출 방식이나 넘기는 환경 변경 | build-sync.md §git 프로세스, verification.md |
| `src/limn/meta.py` | 뷰어가 폴링하는 읽기: `/api/meta` 본문, `/api/docs`, `pins_rev`, 화면 빌드의 `.aux`에서 읽는 목차 라벨. 문서·목록·설정을 인자로 받고 쓰지 않는다 | meta·docs 응답 필드, 폴링 규칙 변경 | api.md, build-sync.md §자동 동기화 (가벼운 meta 폴링) |
| `src/limn/outline.py` | `.aux` 목차 줄의 순수 파서(번호·제목·인쇄 쪽 번호·계층) | 목차 라벨 변환 규칙 변경 | api.md, viewer.md |
| `src/limn/files.py` | 원자적 파일 교체(`atomic_write`): 상태 폴더의 모든 쓰기가 공유. 상태 파일의 프로세스 간 잠금(`store_lock`). 무엇이 원고 트리인지(`tree_part`: 점으로 시작하는 이름 아래와 원고 안에 둔 상태 폴더 아래는 트리가 아니다)와 경로가 그 안의 파일인지 보는 규칙(`file_in_tree`), 원고 줄 세기(`tex_lines`), PDF.js 파일 이름 검사(`vendor_file`) | 쓰기 방식·트리 경로 규칙 변경 | domain.md, architecture.md |
| `src/limn/people.py` | `people.json`: 항목 검사, 저장 형식, 읽기(쓸 수 없는 파일은 `PeopleUnreadable`)와 그 경고, 실행 중 서버의 기록(`record_person`, 쓸 수 없는 파일은 다시 쓰지 않음), @태그 후보(`known_people`) | 사람 목록 필드·기록 간격·후보 규칙 변경 | api.md §@태그·사람·이벤트, §인증 |
| `src/limn/mentions.py` | @태그의 순수 규칙: `@이름` 풀기, 지금 차례, `addressed`·`fyi`, 메모 태그와 재알림 간격 | 태그 해석·addressed·재알림 규칙 변경 | api.md §@태그·사람·이벤트, viewer.md §스레드와 검토 |
| `src/limn/events.py` | 알림 한 건과 받는 사람, 폴링이 고르는 이벤트(순수), `events.jsonl` 쓰기·읽기(`EventLog`) | 이벤트 종류·필드·받는 사람·보관 건수 변경 | api.md §이벤트 (`events.jsonl`), §브라우저 알림 커서 |
| `src/limn/audit.py` | `audit.jsonl` 한 줄과 추가 전용 쓰기, CLI 행위자 | 감사 항목·쓰기 방식 변경 | api.md §감사 기록 (`audit.jsonl`), SECURITY.md |
| `src/limn/scope.py` | 핀 단위 변경(0.3)의 순수 판단: hunk 블록 귀속, 핀 hunk diff, 합성 판, 거절 값 | 귀속 순서·`scope` 필드·`changes` 검사 변경 | api.md §핀 단위 변경 보기, ADR-0005 |
| `src/limn/documents.py` | 문서(`Doc`: 빌드 루트·메인·문서별 상태 폴더와 빌드 잠금·상태), 문서 키 규칙, 문서 목록을 인자로 받는 조회(`request_doc`·`doc_for_file`·`pin_doc_key`)와 조회 결과 값(`DocNotFound`), 파서가 읽는 원고 사실(`DocumentFacts`), `to_source` | 문서 경로·키 규칙 변경 | domain.md §여러 문서, build-sync.md |
| `src/limn/mark.py` | Limn 마크: 기하 하나, 뷰어 인라인 SVG·파비콘 SVG·PNG | 마크 모양·크기·색 규칙 변경 | viewer.md §마크와 파비콘 |
| `src/limn/viewer/*` | 뷰어 화면: `index.html`, 스타일 조각 `css/*.css`, 스크립트 조각 `js/*.js`, 조각 순서 `parts.txt`, 브라우저 알림의 서비스 워커 `sw.js`(`GET /sw.js`, `service_worker()`가 읽는다). 조립은 `assemble.py`(`viewer_html`: 조각을 순서대로 이어 한 장의 HTML로 만들고 PDF.js 버전·마크·Lucide 아이콘 표·영어 메시지 표를 채운다) | 레이아웃·토큰·컴포넌트·상호작용 변경, 조각 추가(`parts.txt`에 줄을 더한다), 아이콘 추가(`assemble.py`의 `LUCIDE`), PDF.js 버전 변경(`PDFJS_VERSION`) | viewer.md, verification.md |
| `src/limn/web/*` | HTTP 층: 처리기와 서버 클래스·본문 읽기와 한도·경로 분기와 경로만 쓰는 상수(`handler.py`), 아직 옮기지 않은 경로의 요청 본문·쿼리 파서와 요청 타입(`parse.py`), 아직 옮기지 않은 결과의 응답과 빌드 응답의 로그 다이어트(`answers.py`), 오류 형식·거절 표·빌드 실패 문장 표·거부된 첫 화면(`errors.py`), 처리기가 부르는 서비스 목록(`app.py`) | 경로·응답·오류 문구 추가나 변경, 처리기가 부르는 서비스 변경 | api.md, architecture.md, verification.md |
| `src/limn/access.py` | 접근 제어: 신원·입장·역할·Host/Origin 판단, `tokens.json`·`people.json` 캐시, `limn token`·`limn member`의 상태 도우미(`people.json` 형식은 `people.py`의 것). 토큰 파일 안내 문구는 위의 `guidance.py` | 신원 방식·토큰·역할·Host/Origin 규칙 변경(보안 경계, architecture.md §멈춤 신호) | api.md §인증, architecture.md 불변식 1, operations.md, verification.md |
| `src/limn/startup.py` | `limn serve` 시작 규칙: 접근 설정 판단(`access_options`, 보안 경계)과 시작 로그, `--port` 확인, `--doc` 해석·메인 파일·상태 폴더, `people.json` 권한 조이기, 라벨·색, 시작 요약 줄, 패키지 버전(`app_version`). 거절은 `StartupRefused` 값(`--doc`의 거절은 먼저 `DocsRefusal` 값) | 시작 거절·바인드 규칙·요약 줄 변경(바인드 규칙은 architecture.md §멈춤 신호) | architecture.md 불변식 1, operations.md, verification.md |
| `src/limn/args.py` | `limn serve` 명령줄 파서(`serve_parser`): 옵션·기본값·도움말 | 인자 추가나 변경 | operations.md, instances.md |
| `src/limn/config.py` | 실행 설정의 얼린 타입 `RunConfig`(필드와 상태 파일 경로)와 그 안의 접근 옵션 `AccessOptions`, 강조색 표 | 실행 설정 추가나 변경 | architecture.md |
| `src/limn/ui_en.json` | 뷰어 영어 문자열 | UI 문자열 추가·변경 | viewer.md |
| `src/limn/instances.sh`, `src/limn/cli.py`, `src/limn/systemd/*` | 인스턴스 관리자와 limn 명령 | 명령·설정 키·유닛 템플릿 변경 | instances.md, operations.md |
| `src/limn/migrate.py` | 옛 설치에서 옮기기 | 이전 절차 변경 | instances.md |
| `src/limn/vendor/**` | 번들한 PDF.js와 Lucide | 버전 교체나 파일 추가 | viewer.md, 해당 vendor README |
| `pyproject.toml`, `uv.lock` | 의존성과 지원 파이썬 | 의존성·파이썬 범위 변경 | architecture.md 불변식 2, verification.md |
| `tests/**` | 자동 게이트 | 테스트 추가·이동·합격 기준 변경 | verification.md |
| `.github/workflows/*` | CI | 작업·행렬·단계 변경 | verification.md, workflow.md |
| `skill/*` | 에이전트 절차 | 에이전트 행동 규칙 변경 | api.md와 함께, 영어·한국어 두 벌 |
| `docs/adr/*` | 결정 기록 | 새 결정 | index.md §결정 기록, workflow.md §ADR을 쓰는 때 |
| `docs/handbook/book.json`, `tools/handbook-publish/*` | Handbook 출판 설정과 출판기 | 폰트·도구 버전·출판기 교체 | verification.md |
<!-- handbook-filemap:end -->

## 결정 기록

| ADR | 내용 | 상태 |
| --- | --- | --- |
| [ADR-0001](../adr/0001-blueprint.md) | 청사진: 설계 축 채택값과 이유 | 확정 (2026-09-26) |
| [ADR-0002](../adr/0002-access-control.md) | 접근 제어·협업 경계·동기화 | v0.2 확정·구현, 이후 제안 |
| [ADR-0003](../adr/0003-tailnet-headerless-and-owner-clear.md) | 테일넷의 헤더 없는 요청 거부와 소유자 전용 전체 지우기 | 확정·구현 (0.2.1) |
| [ADR-0004](../adr/0004-one-reply-trash-sections.md) | 답글 하나와 서버 규칙, 휴지통, 접는 목록 구획 | 확정·구현 (0.2.2) |
| [ADR-0005](../adr/0005-pin-scoped-changes.md) | 핀 단위 [변경 보기]: 닫을 때의 `changes`와 `PR #번호 (커밋 해시)`, 서버 추정(겹침만), 핀의 hunk만 담은 소스 diff·비교 PDF | 확정·구현 (0.3.0) |
| [ADR-0006](../adr/0006-relative-pin-paths.md) | 핀의 파일을 원고 폴더 기준 상대 경로(`file_rel`)로도 적고, 옛 레코드는 읽을 때 해석한다(쓰기 마이그레이션 없음) — 옮긴 원고에서도 핀이 따라온다 | 확정·구현 (0.3.2), 후속 읽기 규칙 (0.3.4, 이슈 #24) |
| [ADR-0007](../adr/0007-agent-token-file.md) | 서버 머신의 에이전트는 인스턴스별 토큰 파일(`~/.config/limn/<인스턴스>.token`, `0600`)로 인증하고, 그 뒤 인스턴스마다 `AGENT_LOOPBACK=0` | 확정 (2026-09-26) |
| [ADR-0008](../adr/0008-trash-live-reconciliation.md) | 휴지통과 살아 있는 핀의 두 파일 쓰기가 중단되면 살아 있는 핀을 우선하고 그림자 사본을 정리한다 | 확정·구현 (2026-09-27) |
| [ADR-0009](../adr/0009-backend-vertical-slices.md) | 백엔드를 기능별 세로 슬라이스로 점진 이행. 핀 수명 주기·처리 중 표시·휴지통·만들기·편집·JSON 조회를 옮겼다 | 확정·점진 구현 중 (2026-09-28) |

## 알려진 공백

- HTML 출판은 로컬 폰트(`.handbook/fonts/`, git 밖)에 기대고, CI에서 출판을 검사하지 않는다. 방법은 [verification.md](verification.md) §7 Handbook 출판에 있다.
- Handbook 안의 `[파일](파일) §절 제목` 참조와 코드 주석의 `docs/handbook/파일 §절 제목` 참조는 [`tests/test_handbook_refs.py`](../../tests/test_handbook_refs.py)가 검사한다. 같은 파일 안의 `§절 제목`만 쓴 참조는 검사하지 않는다 ([verification.md](verification.md) §6).
