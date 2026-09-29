# 검증 — 무엇을 재고 언제 합격인가

이 topic은 Limn의 변경이 합격인지 판단하는 게이트를 모은다. 각 게이트마다 무엇을 재는지, 어떤 변경에서 돌리는지, 어떻게 돌리는지, 무엇이면 통과인지, 그리고 통과가 무엇까지 보장하는지를 적는다. PR을 올리기 전, 리뷰할 때, 새 테스트나 CI 단계를 더할 때 읽는다. 게이트를 더하거나 합격 기준을 바꾸면 이 파일을 같은 변경에서 고친다.

> **한눈에**
>
> - 자동 게이트: §1 파이썬 테스트, §2 인스턴스 관리자 테스트, §3 설치 스모크
> - 불안정한 테스트를 막는 규칙(상태를 기다리고, 시계를 얼린다): §브라우저 테스트의 기다림
> - 사람이 확인하는 게이트: §4 에이전트 계약 호환, §5 화면 실측
> - 아직 없는 게이트: §6 정량 게이트가 없는 영역
> - 문서 출판: §7 Handbook 출판
> - 정적 검사: §8 Ruff(린트·포매팅)·ShellCheck, §9 타입 검사
> - 동작을 바꾸지 않는 구조 변경의 증명: §구조 이동의 동작 불변 증명(차등 비교)
> - 결과 보고 규칙: §결과를 보고하는 법

## 합격의 뜻

Limn에서 "테스트가 녹색"은 합격의 필요조건이지 충분조건이 아니다. 내부 구현 세부나 목(mock)을 어설프게 고정한 녹색 테스트는 거짓 경보(false alarm)를 숨길 수 있다. 테스트는 구조가 아니라 관찰 가능한 동작(Kent Beck's Test Desiderata, Khorikov의 리팩토링 내성)을 고정해야 하며, 순수 함수는 출력 기반으로, 도메인 불변식은 성질 기반(PBT; Hypothesis)으로, 그리고 테스트를 의도적으로 실패시켜 보지 않은 테스트(변이 테스트 / red 단계)는 신뢰하지 않는다([code-style-roadmap.md](code-style-roadmap.md) §R9).

[architecture.md](architecture.md) §채택한 설계 축에서 정한 검수 진실원은 세 겹이다.

1. 자동 테스트가 동작과 불변식을 올바르게 검증하며 녹색이다.
2. 에이전트 계약(`pins.md`, HTTP API)이 호환을 지킨다.
3. 화면을 바꿨다면 실제 화면에서 규칙대로 보이는지 실측했다.

게이트는 머지 전에 막는다. CI([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml))가 `main` 푸시, `v*` 태그, 모든 PR에서 돈다.

### 검증 시간과 병렬 실행

- 수정 중에는 바뀐 동작을 직접 보는 테스트와 관련 정적 검사부터 돌린다. 전체 게이트는 완료 전 한 번 돌리고, 같은 입력으로 반복하지 않는다. 실패 원인을 고친 뒤에는 영향을 받는 게이트만 다시 돌린다.
- 병렬 가능한 검사는 백그라운드나 멀티프로세스로 돌린다 (`pytest -n auto`, 독립된 CI 작업).
- 테스트가 끝난 뒤에는 **무엇을 돌려 몇 초 만에 통과했는지** 숫자로 보고한다(§결과를 보고하는 법).

## 1. 파이썬 테스트

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 도메인 순수 함수와 거절 값, 상태 머신 전이, 핀 저장 순서와 원자적 파일 교체, HTTP 처리기와 응답 형식, 에이전트 계약(`pins.md`, JSONL 스키마), 에이전트 토큰 파일, 뷰어 템플릿 조립과 프론트엔드 불변식, SyncTeX 역변환, Git 프로세스 호출, 인스턴스 앱 격리 |
| 적용 조건 | 파이썬 코드, 뷰어 파일, 에이전트 계약, 테스트를 바꿀 때. PR 전과 CI에서 항상 돈다 |
| 실행 | `uv run pytest -q -rs` (빠른 전체). 병렬은 `uv run pytest -q -rs -n auto` (CPU 코어 수만큼 프로세스를 띄운다) |
| 합격 기준 | 실패나 에러가 0건이어야 한다. 건너뛴 테스트(`s`)가 있으면 그 이유가 합당해야 한다(예: TeX Live가 없는 환경에서 TeX 테스트 스킵) |
| 보장 범위 | 단위와 통합 수준의 동작 회귀를 막는다. 실제 브라우저 렌더링(CSS 배치, Lucide 아이콘 표시)과 실제 tailnet 환경은 보장하지 않는다(각각 §5, §6) |

### 브라우저 테스트의 기다림

브라우저가 닿는 테스트(`tests/test_viewer_browser.py`, `tests/test_viewer.py`의 `Frontend*` 가드)는 **임의의 시간(`sleep`, `wait_for_timeout`)을 기다리지 않는다.** 이벤트·DOM 상태·통신 완료를 가리키는 술어(`expect(...)`, `wait_for_selector`, `wait_for_function`)를 기다린다. 시간으로 기다리면 빠른 머신에서는 시간을 낭비하고 느린 CI에서는 무작위로 깨진다.

뷰어 화면의 시간 의존 동작(폴링 간격, 알림 배지 깜빡임, 날짜 포맷)을 테스트할 때는 브라우저의 시계를 얼린다(`clock.set_fixed_time()`).

### 테스트 파일의 배치

테스트 파일은 아래 규칙으로 놓인다. 파일마다의 자세한 범위는 각 테스트 모듈의 docstring에 있다. 새 테스트는 이 규칙에 맞는 파일에 둔다. 기능 테스트만 직접 실행해도 공용 `helpers`를 찾도록 pytest의 `pythonpath`에 `tests`를 둔다. 테스트 클래스·메서드를 옮길 때는 `tools/test_id_map.py`로 수집 목록의 누락·중복을 대조한다.

| 파일 | 맡은 범위 |
| --- | --- |
| `src/limn/features/*/test_*.py` | **기능 슬라이스 동거 테스트.** 세로 슬라이스는 코드와 테스트를 함께 소유한다. 슬라이스 안의 순수 규칙·입력 파싱·상태 전이·서비스 경계를 함께 검증한다. 동기화·원격 pull은 `sync/`, 비교 이력은 `revisions/`, 문서 meta·목차는 `document_views/`, 답글은 `pins/lifecycle/`, 원고 복사와 보기 전용 문서의 감시 라운드(`test_watch.py`)는 `builds/`, 기동 문서 선택과 기동 로그의 문서 줄은 `administration/`에서 검증한다. 관리 의존성(파일·디렉터리)은 임시 디렉터리로 실제 수행하고, 내부 비공개 구현이나 호출 횟수를 모킹하지 않는다 |
| `tests/test_<모듈>.py` | 그 모듈을 지킨다(`test_pins_lifecycle.py`는 `limn/pins/lifecycle.py`, `test_web_parse.py`는 `limn/web/parse.py`). 순수 모듈은 서버 없이 값으로 직접 테스트하고, 순수하지 않은 것을 가져오지 않는지 import 검사로 지킨다. 옮긴 모듈은 서버 전역(`C`, 문서 목록)을 읽지 않는지도 본다. 파일 끝의 클래스가 `server.py`를 거쳐 그 모듈의 연결을 보기도 한다 |
| [`tests/test_access_module.py`](../../tests/test_access_module.py), [`tests/test_access.py`](../../tests/test_access.py), [`tests/test_security.py`](../../tests/test_security.py) | 접근 제어와 보안 강화(보안 경계). 첫째는 `limn/access.py`를 서버 없이, 둘째는 처리기를 거쳐 신원 방식·토큰·역할·바인드 규칙과 옛 상태 디렉터리 호환을 본다. 셋째는 처리기 끝까지(소켓 쌍) 점으로 시작하는 이름 아래 파일과 원고 안에 둔 상태 폴더의 거절(그런 상태 폴더의 기동 경고·거절 포함), 쓸 수 없는 `people.json`이 권한을 주지 않고 다시 쓰이지 않는지, 모든 응답의 프레이밍 금지 헤더를 본다 |
| [`tests/test_server.py`](../../tests/test_server.py) | `server.py` 자신의 함수와, 요청이 처리기와 서버 배선을 끝까지 지나는 동작. 대다수 요청은 처리기를 소켓 쌍으로 직접 몰고, 실행별 앱 격리는 같은 모듈에서 두 서버를 실제 TCP 포트에 띄워 확인한다. 기능의 HTTP 경로(claim·종류와 스레드·검토·겹침)는 여기 두고, 그 규칙·저장 필드·`pins.md` 줄은 지키는 모듈의 파일에 둔다 |
| [`features/pins/lifecycle/test_reply.py`](../../src/limn/features/pins/lifecycle/test_reply.py), [`tests/test_trash.py`](../../tests/test_trash.py), [`tests/test_notifications.py`](../../tests/test_notifications.py), [`tests/test_access_paths.py`](../../tests/test_access_paths.py), [`tests/test_moved_paths.py`](../../tests/test_moved_paths.py), [`tests/test_token_file.py`](../../tests/test_token_file.py), [`features/builds/test_build_copy.py`](../../src/limn/features/builds/test_build_copy.py) | 여러 모듈을 건너는 기능 하나. 답글 규칙의 경로, 휴지통과 전체 비우기, 알림, 주체×진입 경로, 옮긴 원고, 에이전트 토큰 파일, 빌드의 원고 복사. 파일 이름은 기능 이름이다 |
| `features/pins/*/test_service.py`, [`tests/helpers_pin_service.py`](../../tests/helpers_pin_service.py) | 핀 기능별 서비스·HTTP 동작과 공유 실파일 저장소 fixture. `tests/test_service.py`는 공통 문맥·행위자·조회·import 경계만 검증한다. 규칙 테스트의 공통 레코드는 `tests/helpers_pin_rules.py`가 제공한다 |
| [`tests/helpers.py`](../../tests/helpers.py) | 테스트가 아니라 공용 도구. `server.py`를 파일에서 한 번 읽은 사본(`ps`)과 임시 원고·상태 폴더마다 새 `ServerApplication`을 묶는 `Base`, 원고 픽스처, 소켓 쌍 요청 도우미, 뷰어 스크립트를 node로 돌리는 도우미, TeX 도구 검사 `needs_tex`. 서버 사본마다 앱의 설정·문서 목록·잠금이 따로 있으므로, 서버를 부르는 테스트 파일은 모두 여기서 가져온다 |
| [`tests/test_contract_snapshot.py`](../../tests/test_contract_snapshot.py) | 에이전트 계약의 스냅샷. 정해진 핀 흐름을 처리기로 몰아 응답마다의 상태·본문, 쓰기마다의 `pins.md`, 끝의 핀 목록 응답을 [`tests/data/contract_snapshot.json`](../../tests/data/contract_snapshot.json)과 바이트 단위로 비교한다. 계약을 일부러 바꿀 때만(설계 승인 뒤) `LIMN_RECORD_SNAPSHOT=1`로 다시 기록하고, JSON의 차이가 곧 계약의 변경이다 |
| [`tests/test_pins_model.py`](../../tests/test_pins_model.py) | 레코드 왕복. 레코드 모양 말뭉치 [`tests/data/pin_records.jsonl`](../../tests/data/pin_records.jsonl)을 상태 타입으로 파싱해 다시 쓰면 바이트가 같은지 보고, 공통 필드(`PinCore`)와 상태 필드가 어떤 값을 올리고 어떤 값을 저장된 그대로 두는지 본다. 새 레코드 모양을 쓰는 코드를 더하면 말뭉치에도 더한다 |
| [`tests/test_pbt_invariants.py`](../../tests/test_pbt_invariants.py) | 성질 기반 테스트(PBT; Hypothesis). 형상 타입 가드(bool 거절), 인용·줄 정규화, SyncTeX 군집화, 핀 범위 겹침 대수 대칭성, 핀 상태 머신 전이 불변식을 무작위 생성 입력으로 검증한다 |
| [`tests/test_files.py`](../../tests/test_files.py) | 상태 파일의 원자적 교체. 동기화·권한 설정·교체 실패 뒤 원본과 임시 파일·파일 기술자의 상태, 성공 때의 바이트와 비밀 파일 권한을 본다 |
| `tests/test_viewer*.py` | 뷰어. `test_viewer.py`는 배포되는 HTML·CSS 구조와 JS 순수 함수, 실제 Chromium의 레이아웃 회귀(`Frontend*` 가드), `test_viewer_files.py`는 조각과 순서 목록·`node --check`, `test_viewer_source.py`는 토큰으로 읽은 JS(정확한 함수 떼어 내기, 아무도 부르지 않거나 두 번 선언한 함수, `//` 주석 끝에 붙어 돌지 않는 코드 문장, 닫힌 값 표와 서버 값의 대조), `test_viewer_assemble.py`는 조립, `test_viewer_input.py`는 마우스·터치 입력, `test_viewer_browser.py`는 실제 Chromium에서 기능 흐름(답글·휴지통·딥 링크·핀 단위 변경 보기·보기 역할). 뷰어 JS가 서버 규칙을 따라 하는 곳은 같은 말뭉치를 양쪽에 돌려 결과를 대조한다(`test_mentions_parity.py`: 뷰어 `mentionScan()`과 서버 `resolve_mentions()`) |
| [`tests/test_errors.py`](../../tests/test_errors.py), [`tests/test_i18n.py`](../../tests/test_i18n.py), [`tests/test_naming.py`](../../tests/test_naming.py) | 여러 모듈에 걸친 위생. 모든 거절 본문의 안정 코드 `reason`과 영어 문장, UI 영어 대응표와 계약 문자열의 비번역, 앱 이름과 개인정보 |
| [`tests/test_handbook_refs.py`](../../tests/test_handbook_refs.py) | Handbook 참조 정합성. topic 산문의 깨진 `§절 제목` 참조, 코드 안의 `docs/handbook/` 참조, 그리고 topic 본문에 들어간 ISO 날짜(날짜는 git과 CHANGELOG의 몫이다)를 잡는다 |
| [`features/revisions/test_revisions.py`](../../src/limn/features/revisions/test_revisions.py) | 핀 단위 변경 보기와 비교 빌드(0.3). Git 커밋 목록, 커밋별 diff, 핀 범위에 걸치는 hunk 추정, 핀의 hunk만 골라낸 diff와 비교 PDF 격리 빌드를 본다 |
| [`tests/test_instances.sh`](../../tests/test_instances.sh) | 인스턴스 관리자(§2) |

## 2. 인스턴스 관리자 테스트

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 원고별 인스턴스 관리자(`limn` 셸 스크립트와 `cli.py`): 인스턴스 생성(`add`), 실행(`run`), 시작(`start`), 중지(`stop`), 제거(`rm`), 목록(`list`), 상태(`status`), 업데이트(`update`), 되돌리기(`update --ref`), 포트 충돌 감지, 유닛 파일 생성, 환경 변수 파일 읽기/쓰기 |
| 적용 조건 | `src/limn/instances.sh`, `src/limn/cli.py`, `src/limn/systemd/*`, `tests/test_instances.sh`를 바꿀 때 |
| 실행 | `bash tests/test_instances.sh` |
| 합격 기준 | 스크립트가 0으로 끝나고 모든 하위 테스트가 `PASS`를 출력해야 한다 |
| 보장 범위 | 여러 인스턴스를 격리해 관리하는 셸 계층의 동작을 보장한다. 실제 systemd 데몬과의 상호작용은 리눅스 환경에서만 보장된다 |

## 3. 설치 스모크

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 패키지 빌드와 클린 가상환경 설치: `uv build`로 wheel/sdist가 생기는지, 깨끗한 환경에 설치해 `limn --help`와 `limn version`이 정상 실행되는지, 런타임 의존성이 비어 있는지 |
| 적용 조건 | `pyproject.toml`, 패키지 구조, 진입점을 바꿀 때. PR과 CI의 `smoke` 작업에서 돈다 |
| 실행 | `uv build && uv run --isolated python -m limn --help` |
| 합격 기준 | 빌드가 성공하고, 격리 환경에서 도움말과 버전이 오류 없이 출력되어야 한다 |
| 보장 범위 | 패키징과 진입점 연결을 보장한다. 인스턴스를 실제로 띄워 브라우저로 접속하는 것은 보장하지 않는다 |

## 4. 에이전트 계약 호환

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 에이전트가 읽는 파일과 API의 하위 호환: `pins.md` 형식(열 순서, 상태 표시어, 한국어 머리말), HTTP API 응답 스키마, 핀 레코드 필드, 오류 응답 형식 |
| 적용 조건 | `pins.md` 렌더링, API 경로·응답, 핀 레코드 구조를 바꿀 때 |
| 실행 | 자동: `tests/test_contract_snapshot.py`, `tests/test_pins_model.py`. 수동: [api.md](api.md)와 [SKILL.ko.md](../../skill/SKILL.ko.md)의 설명이 일치하는지 대조 |
| 합격 기준 | 스냅샷 테스트 통과, 스키마에 필수 필드가 빠지지 않음, 기존 필드의 의미가 바뀌지 않음 |
| 보장 범위 | 기존 에이전트가 새 버전의 Limn과 통신할 때 깨지지 않음을 보장한다. 에이전트 자체의 버그는 보장하지 않는다 |

## 5. 화면 실측

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 브라우저 뷰어의 시각적 요소: 패널 너비와 접힘 상태, 핀 마커의 위치와 색상, 디자인 토큰(CSS 변수), 반응형 레이아웃, Lucide 아이콘 렌더링 |
| 적용 조건 | `src/limn/viewer/` 아래의 HTML·CSS·JS를 바꿀 때 |
| 실행 | 자동: `tests/test_viewer.py` 안의 `Frontend*` 가드 테스트. 수동: 변경 전후 스크린샷 비교, 또는 브라우저 개발자 도구에서 실측 |
| 합격 기준 | 자동 가드 통과, 변경 전후 레이아웃 깨짐 없음, 디자인 토큰 값이 [viewer.md](viewer.md)와 일치 |
| 보장 범위 | 지정된 뷰포트와 테마에서의 렌더링을 보장한다. 모든 OS·브라우저 조합에서의 픽셀 단위 일치는 보장하지 않는다 |

## 6. 정량 게이트가 없는 영역

아래 영역은 CI에서 숫자로 떨어지는 자동 게이트가 없다. 어떻게 메꾸는지 함께 적는다.

| 영역 | 없는 이유 | 메꾸는 법 |
| --- | --- | --- |
| 실제 테일넷 다중 사용자 접속 | CI 러너가 테일넷에 조인할 수 없다 | `--auth trusted-proxy`와 `tests/test_access.py`의 헤더 시뮬레이션으로 대조 |
| 실제 TeX 엔진의 다양한 원고 | TeX Live 전체 설치는 CI에서 너무 무겁다 | 최소 fixture 원고와 `test_cross_engine.py`로 핵심 경로만 확인 |
| 브라우저 알림(Service Worker) 실기 동작 | 헤드리스 브라우저에서 푸시 알림 환경이 제한된다 | `sw.js` 구문 검사와 `test_notifications.py`의 이벤트 스트림 검사로 분할 |
| 뷰어 JS 단위 테스트 프레임워크 | 브라우저 JS 린터나 Jest 같은 별도 러너를 두지 않는다 | `test_viewer_source.py`의 AST 토큰 검사와 `test_viewer_browser.py`의 Playwright 통합으로 대체 |
| Handbook 같은 파일 안의 §참조 | 정규식만으로 같은 파일의 앵커 존재를 완벽히 가리기 어렵다 | PR 리뷰에서 사람이 링크를 직접 클릭해 확인 |
| private 도우미 함수의 docstring | docstring 검사(`tests/test_handbook_refs.py`)는 공개 API와 테스트 모듈만 본다 | 코드 리뷰에서 복잡한 로직에 설명 주석이 있는지 확인 |
| 스냅샷 흐름 밖의 계약 | 경로별 테스트가 응답의 관련 필드를 확인한다(§4) | 스냅샷에 없는 경로의 응답 전체 바이트는 비교하지 않는다 |

## 7. Handbook 출판

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | Handbook이 작성 표준(목록·role 배정·H1 하나·강조 상자 label·코드 언어·단순 표·내부 링크와 절 대상)을 지키고 한 장짜리 HTML로 묶이는지 |
| 적용 조건 | `docs/handbook/`, `docs/handbook/book.json`, `tools/handbook-publish/`를 바꿀 때 |
| 실행 | 폰트를 `.handbook/fonts/Pretendard-Regular.otf`에 둔 뒤 `uv run python tools/handbook-publish/publish.py check docs/handbook/index.md`, 이어서 `uv run python tools/handbook-publish/publish.py build docs/handbook/index.md --output .handbook/out/index.html` |
| 합격 기준 | 두 명령이 0으로 끝난다. 폰트 SHA-256과 Pandoc 버전은 `book.json`의 값과 정확히 같아야 한다 |
| 보장 범위 | 형식과 링크 대상까지다. 내용이 코드와 맞는지는 보장하지 않는다. PDF 출판은 `book.json`에 고정한 Playwright·Chromium이 따로 필요하다 |

## 8. 정적 검사

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 파이썬: 문법 오류, 쓰지 않는 import, 정의되지 않은 이름, 흔한 버그 패턴(`B`), 종료 코드를 정하지 않은 `subprocess.run`(`PLW1510`), 스타일 규칙(`E`·`W`, import 순서 `I`, 옛 문법 `UP`, 단순화 `SIM`), 프로덕션 공개 항목의 docstring 누락(`D100`–`D107`)과 테스트 모듈·클래스의 누락(`D100`·`D101`), 그리고 코드 모양이 `ruff format`의 출력과 같은지. 셸: `instances.sh`·`instance_*.sh`·`test_instances.sh`의 ShellCheck 경고 |
| 적용 조건 | 모든 변경. CI `lint` 작업이 항상 돈다 |
| 실행 | `uv sync --group dev` 뒤 `uv run ruff check`, `uv run ruff format --check`, `uv run shellcheck src/limn/instances.sh src/limn/features/administration/instance_*.sh tests/test_instances.sh`. 포매팅이 어긋나면 `uv run ruff format`이 고친다. 두 도구 모두 개발 의존성이라 로컬과 CI가 `uv.lock`의 같은 버전을 쓴다 |
| 합격 기준 | 세 명령이 0으로 끝난다. 규칙을 끄려면 그 줄에 이유를 적은 주석과 함께 끈다 (예: `# shellcheck disable=SC2016` 위에 이유 한 줄). 포매터를 `# fmt: off`로 끄는 것은 정말 표 모양인 데이터에만 쓴다 |
| 보장 범위 | 켠 규칙만이다. 규칙 목록과 끈 규칙은 `pyproject.toml`의 `[tool.ruff.lint]`가 정본이고, 끈 이유는 [code-style-roadmap.md](code-style-roadmap.md) §R4에 있다. docstring은 프로덕션 공개 항목과 테스트 모듈·클래스의 누락을 검사하며 private 도우미·테스트 함수·메서드는 제외한다 (§6). 타입은 §9가 본다. 뷰어 JS에는 린터가 없고, §1의 `test_viewer_files`가 node로 문법을, `test_viewer_source`가 토큰으로 죽은 함수·주석에 삼켜진 문장·닫힌 값 표를 본다 |

## 9. 타입 검사

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 파이썬 타입 힌트의 정합성: 함수 인자와 반환값의 타입 일치, `Optional` 처리, `None` 검사 누락, 닫힌 `Literal` 타입과의 비교 |
| 적용 조건 | 파이썬 코드를 바꿀 때. CI `typecheck` 작업에서 돈다 |
| 실행 | `uv run mypy src/limn/` |
| 합격 기준 | `Success: no issues found`로 끝나야 한다. `type: ignore`는 외부 라이브러리 타입 스텁 부재 등 불가피한 경우에만 이유 주석과 함께 허용한다 |
| 보장 범위 | 정적 타입 규칙 위반을 잡는다. 런타임 값의 범위나 비즈니스 불변식은 보장하지 않는다(§1 파이썬 테스트가 맡는다) |

## 구조 이동의 동작 불변 증명(차등 비교)

코드를 옮기거나 리팩토링할 때는 **동작이 바뀌지 않았음**을 차등 비교(differential testing)로 증명한다.

1. **이동 전 측정:** 이동할 대상 모듈의 테스트를 돌려 통과 상태와 실행 시간을 기록한다.
2. **이동 실행:** 파일 이동, import 경로 변경, 조립 지점 연결을 수행한다.
3. **이동 후 대조:** 같은 테스트를 다시 돌려 정확히 같은 결과가 나오는지 확인한다.
4. **스냅샷 대조:** `tests/test_contract_snapshot.py`로 에이전트 계약에 바이트 단위 차이가 없는지 확인한다.
5. **보고:** 이동 전후의 테스트 건수, 소요 시간, diff 행 수를 PR 설명에 숫자로 적는다.

## 결과를 보고하는 법

게이트 실행 결과는 주관적 감상이 아니라 **측정된 수치**로 보고한다.

- "테스트 통과함" 대신: `1826 passed, 11 skipped in 119s (pytest -n 4)`
- "린트 깨끗함" 대신: `ruff check: 0 errors, ruff format: ok, shellcheck: 0 warnings`
- "인스턴스 테스트 통과" 대신: `test_instances.sh: 190 passed, 0 failed`
- 실패가 있으면: 실패한 테스트 이름, 에러 메시지 첫 줄, 재현 명령을 함께 보고한다.

## 요청과 자원 권한 경계

`tests/test_request_boundary.py`와 `tests/test_request_input.py`는 중복 키·헤더·잘못된 인코딩을 거부하고 연결을 닫으며 상태를 쓰지 않는지 확인한다. `tests/test_authority.py`는 역할별 기존 허용 동작, 새 경로 등록의 기본 거부, 작업·대상·인스턴스가 다른 권한의 거부와 신원 스냅샷을 검증한다. `tests/test_manuscript_files.py`는 원고 제외 경로, 검사 뒤 심볼릭 링크 교체, 일반 파일 제한과 디스크립터 정리를 실제 파일로 확인한다. `tests/test_pin_sequences.py`는 생성한 전이 시퀀스의 상태·식별자·revision·레코드 왕복을 확인한다.
