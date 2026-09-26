---
handbook_format: markdown
catalog_schema: 1
---

# Limn System Handbook

이 Handbook은 Limn의 설계 교과서다. 사람은 처음부터 순서대로 읽을 수 있고, 에이전트는 작업에 맞는 topic만 골라 읽는다. Limn의 모든 문서는 여기에 모여 있다. 저장소 밖 사용자를 위한 첫 안내는 [README.ko.md](../../README.ko.md)와 [README.md](../../README.md), 에이전트 작업 절차는 [SKILL.ko.md](../../skill/SKILL.ko.md)다. 결정 기록은 `docs/adr/`에 있다 (§결정 기록).

> **핵심**
>
> 무엇의 현재값이 어디에 있는지 모르겠으면 [purpose.md](purpose.md) §진실 소스부터 본다. 구조를 바꾸기 전에는 [architecture.md](architecture.md) §멈춤 신호를 확인한다. 코드를 쓰기 전에는 [code-style-roadmap.md](code-style-roadmap.md)의 규칙을 따른다.

## 목록

아래 순서가 처음 읽는 사람을 위한 읽기 순서다. role 열의 `purpose`·`architecture`·`verification`은 반드시 있어야 하는 세 책임이 어느 파일에 있는지 표시한다.

<!-- handbook-catalog:start -->
| role | file | responsibility | read or update when |
| --- | --- | --- | --- |
| purpose | [purpose.md](purpose.md) | Limn이 줄이는 비용, 사용자, 범위, 영역별 진실 소스 | 처음 읽을 때, 현재값의 정본 위치가 헷갈릴 때 / 제품 범위나 정본 위치가 바뀔 때 |
| architecture | [architecture.md](architecture.md) | 현재 구조, 채택한 설계 축, 목표 구조, 불변식, 멈춤 신호 | 코드를 놓을 자리를 고르거나 의존성·저장·보안 경계를 건드리기 전 / 구조 단위·불변식·채택값이 바뀔 때 |
|  | [domain.md](domain.md) | 핀 용어, 상태와 전이, 역변환·범위 사다리·anchor 재동기화, 저장소 안전성, 작성자 귀속, 여러 문서 서버 규칙, 알려진 제약 | 핀 규칙이나 위치 계산을 고치기 전 / 상태·전이·위치 규칙·한도가 바뀔 때 |
|  | [viewer.md](viewer.md) | 뷰어 레이아웃, 패널, 상태 표시, 협업 UI, 디자인 토큰·컴포넌트, 벡터 렌더링·확대, 화면 쪽 제약 | 뷰어 HTML·CSS·JS를 고치기 전 / 화면 규칙이나 가드 테스트가 바뀔 때 |
|  | [build-sync.md](build-sync.md) | 동기·비동기 재빌드, git pull, 자동 동기화 폴링, 위치 추정 est, 응답 다이어트, 보기 전용 PDF 감시 | 빌드·동기화·추정 코드를 고치기 전 / 빌드 상태나 폴링 규칙이 바뀔 때 |
|  | [api.md](api.md) | 에이전트 계약: HTTP API 전체, 요청 경계, 핀 레코드 스키마, pins.md 형식 | 에이전트 연동을 만들거나 요청 처리를 고치기 전 / 경로·필드·상태·pins.md 형식이 바뀔 때 |
|  | [operations.md](operations.md) | 서버 하나 실행: 요구 환경, 실행 인자, 포트, 보안 제약, tailscale serve, systemd, 상태 파일, 뷰어 사용법 | 서버를 띄우거나 운영 문제를 볼 때 / 실행 인자·상태 파일·보안 제약이 바뀔 때 |
|  | [instances.md](instances.md) | 원고별 인스턴스 관리자: limn 명령, 설정 키, 문서 탭, 업데이트·되돌리기, 포트, 환경 변수 | 인스턴스를 추가·업데이트·제거할 때 / limn 명령·설정 키·유닛 템플릿이 바뀔 때 |
| verification | [verification.md](verification.md) | 게이트별 측정 대상·적용 조건·실행·합격 기준·보장 범위, 없는 게이트 | PR 전과 리뷰할 때 / 테스트·CI 단계·합격 기준이 바뀔 때 |
|  | [workflow.md](workflow.md) | 설계에서 릴리스까지의 변경 흐름, 예외 경로, ADR 규칙, PR·CLA, 릴리스 | 작업을 시작하거나 PR·릴리스를 할 때 / 절차나 기여 조건이 바뀔 때 |
|  | [code-style-roadmap.md](code-style-roadmap.md) | 팀 코딩 규칙의 우선순위, 규칙별 현재 모습과 바꾼 모습, 단계별 정렬 계획과 진행 상황 | 코드를 쓰거나 리뷰하기 전 / 단계를 끝내거나 순서를 바꿀 때 |
<!-- handbook-catalog:end -->

## 파일 지도

어느 경로를 고치면 어느 topic을 함께 봐야 하는지 적는다. 전체 파일 목록이 아니라 의미 있는 경로만 담는다.

<!-- handbook-filemap:start -->
| 경로 패턴 | 책임 | 수정 trigger | 갱신 주체 |
| --- | --- | --- | --- |
| `src/limn/server.py` | 핀 조작·상태 계산 구역과 핀 저장소 조립(`pin_store`, `PIN_LOCK`, 레코드 검사 `valid_rec`) | 상태·전이·레코드 필드 변경 | domain.md, api.md, architecture.md |
| `src/limn/store.py` | 핀 저장소: 잠금 아래 쓰기 순서(`transact`), `pins.jsonl`·`pins.md`·휴지통 쓰기, 손상 줄 보존, 핀 번호(`pins.seq`), 보관(clear). 서버를 모르고 협력자를 인자로 받는다 | 저장 순서·파일 이름·보존 규칙 변경 | domain.md §저장소 안전성, architecture.md 불변식 4 |
| `src/limn/pins/*` | 핀 도메인의 순수 코드: 상태 타입, 행위자 타입, 옮겨진 전이, 편집 판단과 새 핀 레코드 | 상태·전이·거절 규칙 변경 | domain.md, code-style-roadmap.md |
| `src/limn/mapping.py` | 위치 계산의 순수한 절반: 범위 사다리, 블록 확장, 점수, anchor 찾기, 핀 파일 찾기(`pin_rel_path`) | 점수·단계·anchor·핀 파일 위치 규칙 변경 | domain.md, api.md §핀 파일의 위치 |
| `src/limn/server.py` | 역변환 실행 구역: SyncTeX·pdftotext 호출, `.tex` 읽기, 토큰 가중치 캐시, 저장된 핀 재동기화(`sync_all`) | 역변환 경로·재동기화 변경 | domain.md, build-sync.md |
| `src/limn/build.py` | 빌드: 원고 복사, latexmk, pdftoppm, 쪽 디렉토리, 빌드 상태, 빌드 이력, 원고 지문과 `src_mtime`. 문서와 설정을 인자로 받는다 | 빌드 단계·상태·이력·지문 규칙 변경 | build-sync.md, architecture.md |
| `src/limn/server.py` | 빌드 셸·git pull·원격 main 감시·보기 전용 PDF·meta 구역: 요청의 문서로 빌드를 부르고 동기화 | 폴링·추정·동기화 규칙 변경 | build-sync.md |
| `src/limn/files.py` | 원자적 파일 교체(`atomic_write`): 상태 폴더의 모든 쓰기가 공유. 경로가 원고 트리 안의 파일인지 보는 규칙(`file_in_tree`) | 쓰기 방식·트리 경로 규칙 변경 | domain.md, architecture.md |
| `src/limn/server.py` | 핀 단위 변경 구역(0.3): hunk 블록 귀속, 핀 hunk diff, 합성 판 | 귀속 순서·`scope` 필드·`changes` 검사 변경 | api.md §핀 단위 변경 보기, ADR-0005 |
| `src/limn/mark.py` | Limn 마크: 기하 하나, 뷰어 인라인 SVG·파비콘 SVG·PNG | 마크 모양·크기·색 규칙 변경 | viewer.md §마크와 파비콘 |
| `src/limn/viewer/*` | 뷰어 화면: `index.html`, 스타일 조각 `css/*.css`, 스크립트 조각 `js/*.js`, 조각 순서 `parts.txt` (서버가 순서대로 이어 한 장의 HTML로 조립) | 레이아웃·토큰·컴포넌트·상호작용 변경, 조각 추가(`parts.txt`에 줄을 더한다) | viewer.md, verification.md |
| `src/limn/web/*` | HTTP 층: 처리기와 서버 클래스·본문 읽기와 한도·경로 분기(`handler.py`), 요청 본문·쿼리 파서(`parse.py`), 핀 조작 결과마다의 응답(`answers.py`), 오류 형식·거절 표·거부된 첫 화면(`errors.py`), 처리기가 부르는 서비스 목록(`app.py`) | 경로·응답·오류 문구 추가나 변경, 처리기가 부르는 서비스 변경 | api.md, architecture.md, verification.md |
| `src/limn/server.py` | main과 처리기 연결: 실행 인자, `Handler`를 이 모듈의 서비스에 묶음(`web/app.py`의 `App`이 그 목록) | 인자 추가나 변경, `App`에 든 서비스의 이름·인자 변경 | operations.md, architecture.md |
| `src/limn/ui_en.json` | 뷰어 영어 문자열 | UI 문자열 추가·변경 | viewer.md |
| `src/limn/instances.sh`, `src/limn/cli.py`, `src/limn/systemd/*` | 인스턴스 관리자와 limn 명령 | 명령·설정 키·유닛 템플릿 변경 | instances.md, operations.md |
| `src/limn/migrate.py` | 옛 설치에서 옮기기 | 이전 절차 변경 | instances.md |
| `src/limn/vendor/**` | 번들한 PDF.js와 Lucide | 버전 교체나 파일 추가 | viewer.md, 해당 vendor README |
| `pyproject.toml`, `uv.lock` | 의존성과 지원 파이썬 | 의존성·파이썬 범위 변경 | architecture.md 불변식 2, verification.md |
| `tests/**` | 자동 게이트 | 테스트 추가·이동·합격 기준 변경 | verification.md |
| `.github/workflows/*` | CI | 작업·행렬·단계 변경 | verification.md, workflow.md |
| `skill/*` | 에이전트 절차 | 에이전트 행동 규칙 변경 | api.md와 함께, 영어·한국어 두 벌 |
| `docs/adr/*` | 결정 기록 | 새 결정, 상태 변경 | workflow.md ADR 목록 |
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

## 알려진 공백

- HTML 출판은 로컬 폰트(`.handbook/fonts/`, git 밖)에 기대고, CI에서 출판을 검사하지 않는다. 방법은 [verification.md](verification.md) §7 Handbook 출판에 있다.
- Handbook 안 링크와 `§절 제목` 참조를 자동으로 검사하는 게이트가 없다 ([verification.md](verification.md) §6).
