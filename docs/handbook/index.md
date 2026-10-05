---
handbook_format: markdown
catalog_schema: 1
---

# Limn System Handbook

이 Handbook은 Limn의 설계 교과서다. 사람은 처음부터 순서대로 읽을 수 있고, 에이전트는 작업에 맞는 topic만 골라 읽는다. Limn의 모든 문서는 여기에 모여 있다. 저장소 밖 사용자를 위한 첫 안내는 [README.ko.md](../../README.ko.md)와 [README.md](../../README.md), 에이전트 작업 절차는 [SKILL.ko.md](../../skill/SKILL.ko.md)다.

> **핵심**
>
> 무엇의 현재값이 어디에 있는지 모르겠으면 [purpose.md](purpose.md) §진실 소스부터 본다. 구조를 바꾸기 전에는 [architecture.md](architecture.md) §멈춤 신호를 확인한다. 코드를 쓰기 전에는 팀 코딩 스킬과 [code-style-roadmap.md](code-style-roadmap.md)의 Limn 적용 경계를 확인한다.

## 목록

아래 순서가 처음 읽는 사람을 위한 읽기 순서다. role 열의 `purpose`·`architecture`·`verification`은 반드시 있어야 하는 세 책임이 어느 파일에 있는지 표시한다.

<!-- handbook-catalog:start -->
| role | file | responsibility | read or update when |
| --- | --- | --- | --- |
| purpose | [purpose.md](purpose.md) | Limn이 줄이는 비용, 사용자, 범위, 영역별 진실 소스 | 처음 읽을 때, 현재값의 정본 위치가 헷갈릴 때 / 제품 범위나 정본 위치가 바뀔 때 |
| architecture | [architecture.md](architecture.md) | 현재 구조(기능 소유권과 공통 경계), 의존 방향, 채택한 설계 축, 불변식, 멈춤 신호 | 코드를 놓을 자리를 고르거나 의존성·저장·보안 경계를 건드리기 전 / 구조 단위·불변식·채택값이 바뀔 때 |
|  | [domain.md](domain.md) | 핀 용어, 상태와 전이, 역변환·범위 사다리·그림 문서의 요소 pick·anchor 재동기화·읽을 때 계산하는 요소 위치, 저장소 안전성, 작성자 귀속, 여러 문서 서버 규칙(보기 전용 PDF·그림 문서), 알려진 제약 | 핀 규칙이나 위치 계산을 고치기 전 / 상태·전이·위치 규칙·한도가 바뀔 때 |
|  | [viewer.md](viewer.md) | 뷰어 조작 요약, 레이아웃, 패널, 상태 표시, 협업 UI, 디자인 토큰·컴포넌트, 벡터 렌더링·확대, 화면 쪽 제약 | 뷰어 HTML·CSS·JS를 고치기 전 / 화면 규칙이나 가드 테스트가 바뀔 때 |
|  | [build-sync.md](build-sync.md) | 동기·비동기 재빌드, git pull, 자동 동기화 폴링, 위치 추정 est, 응답 다이어트, 보기 전용 PDF 감시, 그림 문서 가져오기 | 빌드·동기화·추정 코드를 고치기 전 / 빌드 상태나 폴링 규칙이 바뀔 때 |
|  | [api.md](api.md) | 에이전트 계약: HTTP API 전체, 요청 경계, 핀 레코드 스키마, pins.md 형식, 그림 문서의 pick·핀, 그림 요소 지도 형식 | 에이전트 연동을 만들거나 요청 처리를 고치기 전 / 경로·필드·상태·pins.md 형식이 바뀔 때 |
|  | [operations.md](operations.md) | 서버 하나 실행: 요구 환경, 실행 인자, 포트, 보안 제약, tailscale serve, systemd, 상태 파일 | 서버를 띄우거나 운영 문제를 볼 때 / 실행 인자·상태 파일·보안 제약이 바뀔 때 |
|  | [instances.md](instances.md) | 원고별 인스턴스 관리자: limn 명령, 설정 키, 문서 탭, 업데이트·되돌리기, 포트, 환경 변수 | 인스턴스를 추가·업데이트·제거할 때 / limn 명령·설정 키·유닛 템플릿이 바뀔 때 |
| verification | [verification.md](verification.md) | 게이트별 측정 대상·적용 조건·실행·합격 기준·보장 범위, 없는 게이트 | PR 전과 리뷰할 때 / 테스트·CI 단계·합격 기준이 바뀔 때 |
|  | [workflow.md](workflow.md) | 설계에서 릴리스까지의 변경 흐름, 예외 경로, PR·CLA, 릴리스 | 작업을 시작하거나 PR·릴리스를 할 때 / 절차나 기여 조건이 바뀔 때 |
|  | [code-style-roadmap.md](code-style-roadmap.md) | 팀 코딩 스킬의 Limn 적용 경계와 현재 검증 범위 | 코드를 쓰거나 리뷰하기 전 / 적용 경계나 검증 범위가 바뀔 때 |
<!-- handbook-catalog:end -->

## 파일 지도

어느 경로를 고치면 어느 topic을 함께 봐야 하는지 적는다. 전체 파일 목록이 아니라 의미 있는 경로만 담는다.

<!-- handbook-filemap:start -->
| 경로 패턴 | 책임 | 수정 trigger | 갱신 주체 |
| --- | --- | --- | --- |
| `src/limn/pins/**` | 핀 값·전이·레코드·저장·문맥·멘션·변경 범위와 여섯 동작. 순수 판단과 I/O는 같은 기능 안에서 의존 방향으로 구별한다. 빌드가 선택한 요소 사실의 pick 응답과 원고 사다리 단계(`location/figure.py`), 그림 핀의 요소 필드 모양(`element.py`), 읽을 때 계산하는 `mark`·`el_sync`(`listing/projection.py`), pins.md의 그림 핀 행(`listing/render.py`), 파일 종류별 주석 줄(`location/mapping.py`의 `comment_marker`)을 포함한다 | 상태·전이·위치·쓰기·알림·pins.md 변경 | domain.md, api.md, build-sync.md, architecture.md |
| `src/limn/builds/**` | 빌드 결과·산출물·원고 지문·이력·DocumentFacts·컴파일·PDF 감시·그림 지도 파싱/가져오기와 요청 응답. 소비자별 완성 질의(`queries.py`·`contracts.py`), 지도 사본의 실행별 파싱 캐시(`artifacts.py`의 `BuildMapCache`)와 요소 고르기·사다리·따라가기 규칙(`figure_map.py`)을 포함한다 | 빌드 상태·파일 선택·실행·실패 문구 변경 | build-sync.md, api.md, architecture.md |
| `src/limn/collaboration/**` | 평탄한 참여자 사실의 병합·후보 조회·방문 연결, `Notice`의 수신자 필터·직렬화·이벤트 파일·멘션 알림·폴링 | 사람 조회·이벤트 순서·기록·알림 변경 | api.md, viewer.md, architecture.md |
| `src/limn/documents/**` | 문서 탭·meta·목차 조회와 순수 목차 파서 | 문서 응답·폴링·목차 변경 | api.md, viewer.md, build-sync.md |
| `src/limn/revisions/**` | Git 이력(그림 문서는 빌드가 답한 파일 목록의 범위)·핀 닫힘 참조 해석·변경 후보 선택·diff 파싱·핀 범위 귀속·격리 비교 PDF·캐시·실패 응답 | 비교 실행·범위·응답·캐시 변경 | api.md, architecture.md |
| `src/limn/sync/**` | 원격 main 감시·pull 순서·빌드 소유자가 답한 발행 커밋에 따른 재빌드 선택·정착 판단 | 동기화 거절·감시·재빌드 변경 | build-sync.md, api.md |
| `src/limn/administration/**` | 토큰·멤버·문서 인자·이관·인스턴스 셸·systemd 템플릿 | 명령·설정 키·유닛·업데이트 흐름 변경 | instances.md, operations.md, api.md |
| `src/limn/viewer/**` | HTML·CSS·JS·번역·마크·브랜드 파일·조립·화면 제공 경로 | 화면 동작·조각 순서·번역·캐시 정책 변경 | viewer.md, api.md, verification.md |
| `src/limn/runtime/**` | 시작·설정·실행별 문서·잠금·캐시·감시 수명·고정 상태 경로 | 실행 수명·설정·문서 경로 변경 | architecture.md, operations.md, domain.md |
| `src/limn/security/**` | 신원·Host/Origin·역할·권한 발급·사람 사실·감사·인증 안내 | 신뢰·권한·사람 기록·감사 변경 | architecture.md, api.md, operations.md, SECURITY.md |
| `src/limn/platform/**` | 원고 핸들·원자적 쓰기·파일 잠금·Git 프로세스·숫자와 텍스트 장치 | 파일 접근·프로세스 인자/환경·JSON 값 판정 변경 | domain.md, build-sync.md, architecture.md |
| `src/limn/web/**` | 공통 HTTP 처리기·요청 경계 포트·요청 파서·응답·경로 계약 | 요청 한도·디스패치·공통 오류 형식 변경 | api.md, architecture.md |
| `src/limn/server.py`, `src/limn/cli.py`, `src/limn/__main__.py` | 실행 자원 생성·기능 조립·명령 전달 | 시작/종료 연결·기능별 조립 계약 변경 | architecture.md, operations.md, 연결된 기능 topic |
| `src/limn/*/__init__.py` | 기능 공개 표면과 요청한 값만 불러오는 지연 export | 공개 동작·값·기능 소유권 변경 | architecture.md, code-style-roadmap.md, verification.md |
| `tools/check_boundaries.py`, `tests/architecture/test_boundaries.py` | 기능 비공개 접근·기능 쌍/진입점별 import 허용목록·경계 코드의 기능 의존·순환 검사 | import 해석·소유권·검증 규칙 변경 | verification.md, architecture.md |
| `src/limn/vendor/**` | 번들한 PDF.js, Pretendard 글꼴 조각과 스타일시트, Lucide 출처 | 버전 교체·파일 추가 | viewer.md, api.md, 해당 vendor README |
| `src/limn/**/tests/**`, `tests/**` | 소유 패키지의 동작과 교차 기능 계약·구조 게이트 | 검사 추가·이동·합격 기준 변경 | verification.md |
| `package.json`, `package-lock.json`, `tsconfig.json`, `tsconfig.strict.json`, `tools/strict_ratchet.py`, `tools/strict-baseline.json`, `src/limn/viewer/types/*` | 뷰어 JS 타입 검사 도구와 그 설정·선언(서버와 휠에 들어가지 않는다) | 검사 범위·도구 버전·전역 선언 변경 | viewer.md, verification.md |
| `pyproject.toml`, `uv.lock`, `.github/workflows/*`, `.github/dependabot.yml` | 지원 Python·의존성·수집/패키징·병렬 실행·정적 게이트·CI 액션 고정과 갱신 | 실행 환경·검증 구성 변경 | architecture.md, verification.md, workflow.md |
| `skill/*` | 에이전트 절차의 영어·한국어 계약 | 에이전트 행동 규칙 변경 | api.md와 함께 두 언어 |
| `docs/handbook/book.json`, `tools/handbook-publish/*` | Handbook 출판 설정과 출판기 | 폰트·도구 버전·출판기 교체 | verification.md |
<!-- handbook-filemap:end -->

## 알려진 공백

- HTML 출판은 로컬 폰트(`.handbook/fonts/`, git 밖)에 기대고, CI에서 출판을 검사하지 않는다. 방법은 [verification.md](verification.md) §7 Handbook 출판에 있다.
- Handbook 안의 `[파일](파일) §절 제목` 참조와 코드 주석의 `docs/handbook/파일 §절 제목` 참조는 [`tests/architecture/test_handbook_refs.py`](../../tests/architecture/test_handbook_refs.py)가 검사한다. 같은 파일 안의 `§절 제목`만 쓴 참조는 검사하지 않는다 ([verification.md](verification.md) §6).
