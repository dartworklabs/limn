# 검증 — 무엇을 재고 언제 합격인가

이 topic은 Limn의 변경이 합격인지 판단하는 게이트를 모은다. 각 게이트마다 무엇을 재는지, 어떤 변경에서 돌리는지, 어떻게 돌리는지, 무엇이면 통과인지, 그리고 통과가 무엇까지 보장하는지를 적는다. PR을 올리기 전, 리뷰할 때, 새 테스트나 CI 단계를 더할 때 읽는다. 게이트를 더하거나 합격 기준을 바꾸면 이 파일을 같은 변경에서 고친다.

> **한눈에**
>
> - 머지를 막는 게이트와 정보만 주는 검사의 구분: §게이트와 정보 검사
> - 자동 게이트: §1 파이썬 테스트, §2 인스턴스 관리자 테스트, §3 설치 스모크, §8 정적 검사, §9 타입 검사, §10 기능 경계 검사
> - 불안정한 테스트를 막는 규칙(상태를 기다리고, 시계를 얼린다): §브라우저 테스트의 기다림, 생긴 뒤의 처리: §불안정한 테스트
> - 사람이 확인하는 게이트: §4 에이전트 계약 호환, §5 화면 실측
> - 아직 없는 게이트: §6 정량 게이트가 없는 영역
> - 문서 출판: §7 Handbook 출판
> - 동작을 바꾸지 않는 구조 변경의 증명: §구조 이동의 동작 불변 증명(차등 비교)
> - 결과 보고 규칙: §결과를 보고하는 법

## 합격의 뜻

Limn에서 "테스트가 녹색"은 합격의 필요조건이지 충분조건이 아니다. 내부 구현 세부나 목(mock)을 어설프게 고정한 녹색 테스트는 거짓 경보(false alarm)를 숨길 수 있다. 테스트는 구조가 아니라 관찰 가능한 동작(Kent Beck's Test Desiderata, Khorikov의 리팩토링 내성)을 고정해야 하며, 순수 함수는 출력 기반으로, 도메인 불변식은 성질 기반(PBT; Hypothesis)으로, 그리고 테스트를 의도적으로 실패시켜 보지 않은 테스트(변이 테스트 / red 단계)는 신뢰하지 않는다([code-style-roadmap.md](code-style-roadmap.md) §R9).

[architecture.md](architecture.md) §채택한 설계 축에서 정한 검수 진실원은 세 겹이다.

1. 자동 테스트가 동작과 불변식을 올바르게 검증하며 녹색이다.
2. 에이전트 계약(`pins.md`, HTTP API)이 호환을 지킨다.
3. 화면을 바꿨다면 실제 화면에서 규칙대로 보이는지 실측했다.

게이트는 머지 전에 막는다. CI([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml))가 `main` 푸시, `v*` 태그, 모든 PR에서 돈다.
같은 PR에 새 커밋이 올라오면 이전 커밋의 진행 중인 CI를 취소하고 새 트리의 전체 게이트를 실행한다. `main`과 태그 실행은 실행별 그룹을 써서 서로 취소하거나 대기열에서 밀어내지 않는다.

### 게이트와 정보 검사

게이트는 모든 PR의 CI에서 돌고 실패하면 머지를 막는 검사다. 나머지 검사는 판단에 정보를 줄 뿐이다. 게이트를 더하거나 빼면 이 표를 같은 변경에서 고친다.

| 검사 | 게이트 여부 | 명령 | 설정 위치 |
| --- | --- | --- | --- |
| §1 파이썬 테스트(§4·§5의 자동 부분 포함) | 게이트 | `uv run pytest -q -rs` | `ci.yml`의 `test`·`macos`·`tex` 작업, `pyproject.toml`의 `[tool.pytest.ini_options]` |
| §2 인스턴스 관리자 테스트 | 게이트 | `bash src/limn/administration/tests/test_instances.sh` | `ci.yml`의 `instances` 작업 |
| §3 설치 스모크 | 게이트 | `uv tool install .` 뒤 설치된 명령과 패키지 내용 확인 | `ci.yml`의 `install` 작업 |
| §8 정적 검사, §9 타입 검사, §10 기능 경계 검사 | 게이트 | §8–§10의 실행 행 | `ci.yml`의 `lint` 작업, `pyproject.toml`의 `[tool.ruff]`·`[tool.mypy]` |
| §4·§5의 수동 대조, §7 Handbook 출판 | 정보 | 각 절의 실행 행 | CI 밖. 리뷰와 작성자가 돌린다 |
| 커버리지 | 정보 | 필요할 때만 측정 | 설정 없음. 커버리지 수치는 실행 여부를 잴 뿐 검증을 재지 않으므로 게이트로 쓰지 않는다 |

### 검증 시간과 병렬 실행

- 수정 중에는 바뀐 동작을 직접 보는 테스트와 관련 정적 검사부터 돌린다. 전체 게이트는 완료 전 한 번 돌리고, 같은 입력으로 반복하지 않는다. 실패 원인을 고친 뒤에는 영향을 받는 게이트만 다시 돌린다.
- pytest는 기본 4개 worker와 `loadscope`로 실행한다. 같은 클래스의 브라우저·서버 자원을 한 worker 안에 유지하고 Chromium 과다 실행을 피하기 위해 CPU 개수 대신 고정 상한을 쓴다. `-n 0`은 직렬 디버깅, `-n 2`는 메모리가 작은 환경에서 쓴다.
- CI는 일반 테스트(core), 브라우저(browser), 실제 TeX(tex), 인스턴스 관리자(instances), 정적 검사(lint), 설치(install)를 독립 작업으로 실행한다. Linux의 일반·브라우저 검사는 Python 3.10·3.12에서 돈다. 일반 검사는 `-m "not browser and not tex"`, 브라우저는 `-m browser`, TeX는 `-m tex`로 분리한다. macOS 일반 검사는 2개 worker, 브라우저·TeX 검사도 각각 2개 worker로 실행한다. 인스턴스 셸 검사는 Linux·macOS에서 독립적으로 돈다.
- 테스트가 끝난 뒤에는 **무엇을 돌려 몇 초 만에 통과했는지** 숫자로 보고한다(§결과를 보고하는 법).

## 1. 파이썬 테스트

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 도메인 순수 함수와 거절 값, 상태 머신 전이, 핀 저장 순서와 원자적 파일 교체, HTTP 처리기와 응답 형식, 에이전트 계약(`pins.md`, JSONL 스키마), 에이전트 토큰 파일, 뷰어 템플릿 조립·브랜드 파일 무결성과 프론트엔드 불변식, SyncTeX 역변환, Git 프로세스 호출, 인스턴스 앱 격리 |
| 적용 조건 | 파이썬 코드, 뷰어 파일, 에이전트 계약, 테스트를 바꿀 때. PR 전과 CI에서 항상 돈다 |
| 실행 | `uv run pytest -q -rs` (기본 4개 worker). 빠른 일반 검사: `uv run pytest -q -rs -m "not browser and not tex"`. 병렬 옵션의 정본은 `pyproject.toml`의 `addopts` |
| 합격 기준 | 실패나 에러가 0건이어야 한다. 수집된 테스트가 0건인 실행(pytest 종료 코드 5)은 통과가 아니라 실패다. 건너뛴 테스트(`s`)가 있으면 그 이유가 합당해야 한다(예: TeX Live가 없는 로컬 환경에서 TeX 테스트 스킵). CI는 도구 부재를 건너뜀이 아니라 실패로 바꾼다. 브라우저·TeX 작업은 `LIMN_TEST_REQUIRE_BROWSER=1`·`LIMN_TEST_REQUIRE_TEX=1`, 모든 테스트 작업은 `LIMN_TEST_REQUIRE_NODE=1`을 둔다 |
| 보장 범위 | 단위와 통합 수준의 동작 회귀를 막는다. 브라우저 표식의 테스트는 지정된 Chromium 동작·레이아웃과 Firefox·WebKit의 핵심 핀 생성·편집·덧붙임·되돌리기 흐름을 확인한다. 실제 iOS 기기, 모든 엔진의 전체 화면과 실제 tailnet 환경은 보장하지 않는다(§5, §6) |

### 브라우저 테스트의 기다림

브라우저가 닿는 테스트(`src/limn/viewer/tests/test_viewer_browser.py`, `src/limn/viewer/tests/test_viewer.py`의 `Frontend*` 가드)는 **임의의 시간(`sleep`, `wait_for_timeout`)을 기다리지 않는다.** 이벤트·DOM 상태·통신 완료를 가리키는 술어(`expect(...)`, `wait_for_selector`, `wait_for_function`)를 기다린다. 공용 대기 `settle()`(`tests/support/helpers_browser.py`)은 짧은 타이머·`fetch`·CSS 애니메이션과 함께 웹 글꼴 로딩(`document.fonts.status`)이 끝나기를 기다린다. 담은 글꼴의 조각은 그 글자가 처음 화면에 나올 때 받아서, 그 전에 잰 글은 폴백 글꼴의 값이기 때문이다([viewer.md](viewer.md) §글꼴). 시간으로 기다리면 빠른 머신에서는 시간을 낭비하고 느린 CI에서는 무작위로 깨진다.

뷰어 화면의 시간 의존 동작(폴링 간격, 알림 배지 깜빡임, 날짜 포맷)을 테스트할 때는 브라우저의 시계를 얼린다(`clock.set_fixed_time()`).

### 불안정한 테스트

같은 코드에서 통과와 실패를 오가는 테스트는 원인을 찾아 고친다. 원인은 공유 상태, 시간, 실행 순서, 동시성, 자원 수명, 환경, 실제와 다른 대역 가운데 하나다. 시계를 주입하고, 상태를 격리하고, 실제 조건을 기다리는 식으로 그 원인을 없앤다. 재시도, 더 긴 타임아웃, `sleep`, 격리 실행은 영향을 줄일 뿐 고치지 않는다. 녹색이 나올 때까지 다시 돌리지 않는다. 바로 고칠 수 없으면 추적 이슈를 남기고 그 이유와 함께 게이트에서 뺀다. 재실행 플러그인을 두지 않는 것도 같은 이유다.

[`test_token_file.py`](../../src/limn/administration/tests/test_token_file.py)의 실제 서버 기동 검사는 자식 프로세스의 stdout·stderr를 테스트별 파일에 보존한다. 기동 실패는 종료 상태·인터프리터·실제 거절 문장을 함께 보고하고, 자식이 살아서 멈춘 경우에는 30초 기동 한도 전에 `faulthandler`가 25초 시점의 스택을 남긴다. 대기 시간을 늘리거나 재시도하지 않고 실패 원인을 확인하기 위한 증거다. 정상 기동은 그 자식의 리스너 준비 표식과 실제 소켓 응답을 함께 확인한다. 다른 프로세스가 같은 포트를 듣는 것만으로 통과하지 않는다. 종료 정리는 먼저 정상 종료를 요청하고 제한 시간에 끝나지 않으면 강제 종료한 뒤 자식을 회수한다. 로그는 자식 정리 뒤에 닫는다.

[`test_server_listener.py`](../../src/limn/web/tests/test_server_listener.py)는 역방향 이름 확인이 응답하지 않는 조건에서 IPv4·IPv6의 실제 리스너가 활성화되고 TCP 연결을 받는지 확인한다. 사용 중인 포트의 기동 거절은 [`test_token_file.py`](../../src/limn/administration/tests/test_token_file.py)의 실제 점유 포트 회귀 검사가 확인한다. 이 검사는 이름 확인이 멈추는 조건에서의 소켓 기동을 검증하며, 과거 CI 실패가 같은 원인이었다는 증거를 대신하지 않는다.

### 테스트 파일의 배치

기능·보안·HTTP·실행 자원·플랫폼 테스트는 소유 패키지의 `tests/`에 둔다. 새 테스트는 그것이 검증하는 슬라이스 안에 두고, 둘 수 없으면 루트 `tests/`에 슬라이스 경로를 따라 두고 이유를 PR에 적는다. 기존 테스트는 승인 없이 옮기지 않는다. 핀의 각 동작 테스트는 `pins/<동작>/tests/`, 모델·레코드·저장·위치 계산을 함께 검증하는 테스트는 `pins/tests/`에 있다. 뷰어의 자산·JavaScript·Chromium 검사도 `viewer/tests/`가 소유한다. 각 파일의 구체적인 관찰 범위는 모듈 docstring에 있다.

| 경로 | 맡은 범위 |
| --- | --- |
| `src/limn/*/tests/`, `src/limn/pins/*/tests/` | 소유 기능과 경계의 값·규칙·입력·저장·HTTP·실행·뷰어 동작. `viewer/tests/test_viewer_role_keyboard.py`는 실제 서버와 저장소에서 사람·에이전트·viewer의 검토 조작 및 거절, PDF 마크 버튼의 Tab·Enter·Space 이동을 본다 |
| `src/limn/administration/tests/test_instances.sh` | 인스턴스 셸 명령·실행 인자·유닛 생성·업데이트 |
| `tests/contracts/` | 여러 기능의 HTTP·`pins.md` 스냅샷과 성질 검증. 그림 문서 흐름(지도 pick, 요소 핀, 다시 렌더 뒤의 계산 필드)은 `test_contract_snapshot.py`가 [`tests/data/contract_snapshot_figure.json`](../../tests/data/contract_snapshot_figure.json)과 따로 비교한다. `test_figure_rollback.py`는 이전 릴리스가 그림 핀 레코드를 읽고 바이트 그대로 되쓰는지 본다 |
| `tests/architecture/` | 공개 표면·import 경계, Handbook 참조, 이름·개인정보 규칙, CI 액션의 커밋 고정·체크아웃 자격 증명·uv와 빌드 백엔드 버전 고정 |
| `tests/tools/` | 테스트 식별자 이동 대조·그림 선택 비교 도구, 익명 PoC 서버의 정확한 Host 허용·자원 allowlist·API 읽기와 쓰기 거부 경계 |
| `tests/support/`, `tests/data/` | 수집하지 않는 공용 테스트 도우미와 고정 입력·스냅샷. 그림 문서 fixture(그림 스크립트·공통 부품·요소 지도·빌드 폴더와, pick 답을 뷰어처럼 저장하는 도우미, 뷰어 테스트가 쓰는 세 문서(원고·그림·보기 전용 PDF)의 등록과 다시 렌더)는 [`tests/support/helpers_figure.py`](../../tests/support/helpers_figure.py)에 있다 |

pytest는 `tests`와 `src/limn`을 수집하고 `tests/support`에서 공용 도우미를 찾는다. `--import-mode=importlib`는 패키지마다 같은 테스트 파일 이름을 허용한다. 테스트용 `__init__.py`는 필요하지 않다. wheel은 모든 `tests/`를 제외하고 sdist는 검증 소스를 포함한다. mypy는 동거 테스트를 제외한 모든 프로덕션 모듈을 엄격히 검사한다.

파일이나 클래스를 옮길 때는 `pytest --collect-only -q -n 0`과 `tools/test_id_map.py`로 식별자 이동을 대조한다. 이전 테스트의 누락·중복이 없고 새 테스트만 더해져야 한다.

## 2. 인스턴스 관리자 테스트

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 원고별 인스턴스 관리자(`limn` 셸 스크립트와 `cli.py`): 인스턴스 생성(`add`), 실행(`run`), 시작(`start`), 중지(`stop`), 제거(`rm`), 목록(`list`), 상태(`status`), 업데이트(`update`), 되돌리기(`update --ref`), 포트 충돌 감지, 유닛 파일 생성, 환경 변수 파일 읽기/쓰기 |
| 적용 조건 | `src/limn/administration/instances.sh`, `src/limn/cli.py`, `src/limn/administration/systemd/*`, `src/limn/administration/tests/test_instances.sh`를 바꿀 때 |
| 실행 | `bash src/limn/administration/tests/test_instances.sh` |
| 합격 기준 | 스크립트가 0으로 끝나고 실패 건수가 0이어야 한다 |
| 보장 범위 | 여러 인스턴스를 격리해 관리하는 셸 계층의 동작을 보장한다. 실제 systemd 데몬·tailscale과의 상호작용은 대역으로 바꾸므로 보장하지 않는다 |

## 3. 설치 스모크

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 패키지 빌드와 클린 가상환경 설치: `uv build`로 wheel/sdist가 생기는지, 깨끗한 환경에 설치해 `limn --help`와 `limn version`이 정상 실행되는지, 런타임 의존성이 비어 있는지 |
| 적용 조건 | `pyproject.toml`, 패키지 구조, 진입점을 바꿀 때. PR과 CI의 `install` 작업에서 돈다 |
| 실행 | `uv tool install .` 뒤 `limn version`, `limn serve --help`, `limn help`를 실행하고, 설치된 패키지에 뷰어·브랜드·번들 라이브러리(PDF.js, Pretendard)·인스턴스 셸·systemd 템플릿 파일이 있고, Pretendard 조각이 `SHA256SUMS`와 바이트까지 같으며, 테스트 파일이 없는지 확인한다. 정확한 단계는 `ci.yml`의 `install` 작업이 정본이다. 로컬에서 빌드만 볼 때는 `uv build && uv run --isolated python -m limn --help` |
| 합격 기준 | 설치가 성공하고, 설치된 명령이 오류 없이 출력하며, 빠진 패키지 파일과 새어 든 테스트 파일이 없어야 한다 |
| 보장 범위 | 패키징과 진입점 연결을 보장한다. 인스턴스를 실제로 띄워 브라우저로 접속하는 것은 보장하지 않는다 |

CI는 uv `0.12.23`을 쓰고, 패키지 빌드는 Hatchling `1.32.4`를 요구한다. 개발 의존성의 잠금 파일과 별개로 설치 도구·격리 빌드 백엔드도 검토한 버전을 쓰기 위해서다. 실행 정본은 `ci.yml`의 `setup-uv` 설정과 `pyproject.toml`의 `[build-system]`이고, [`test_ci_pins.py`](../../tests/architecture/test_ci_pins.py)가 누락되거나 정확히 고정되지 않은 버전을 거부한다.

## 4. 에이전트 계약 호환

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 에이전트가 읽는 파일과 API의 하위 호환: `pins.md` 형식(열 순서, 상태 표시어, 한국어 머리말), HTTP API 응답 스키마, 핀 레코드 필드, 오류 응답 형식 |
| 적용 조건 | `pins.md` 렌더링, API 경로·응답, 핀 레코드 구조를 바꿀 때 |
| 실행 | 자동: `tests/contracts/test_contract_snapshot.py`(원고 흐름과 그림 문서 흐름), `src/limn/pins/tests/test_model.py`, `tests/contracts/test_figure_rollback.py`(이전 릴리스 v0.3.5·v0.3.7·v0.3.8이 그림 핀 레코드를 읽고 바이트 그대로 되쓰는지. 그 태그가 없는 얕은 클론은 그 릴리스만 건너뛰고, CI는 전체 이력을 받아 모두 돈다). 수동: [api.md](api.md)와 [SKILL.ko.md](../../skill/SKILL.ko.md)의 설명이 일치하는지 대조 |
| 합격 기준 | 스냅샷 테스트 통과, 스키마에 필수 필드가 빠지지 않음, 기존 필드의 의미가 바뀌지 않음 |
| 보장 범위 | 기존 에이전트가 새 버전의 Limn과 통신할 때 깨지지 않음을 보장한다. 에이전트 자체의 버그는 보장하지 않는다 |

## 5. 화면 실측

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 브라우저 뷰어의 시각적 요소: 패널 너비와 접힘 상태, 핀 마커의 위치와 색상, 디자인 토큰(CSS 변수), 반응형 레이아웃, Lucide 아이콘 렌더링 |
| 적용 조건 | `src/limn/viewer/` 아래의 HTML·CSS·JS를 바꿀 때 |
| 실행 | 자동: `src/limn/viewer/tests/test_viewer.py` 안의 `Frontend*` 가드 테스트. 수동: 변경 전후 스크린샷 비교, 또는 브라우저 개발자 도구에서 실측 |
| 합격 기준 | 자동 가드 통과, 변경 전후 레이아웃 깨짐 없음, 디자인 토큰 값이 [viewer.md](viewer.md)와 일치 |
| 보장 범위 | 지정된 뷰포트와 테마에서의 렌더링을 보장한다. 모든 OS·브라우저 조합에서의 픽셀 단위 일치는 보장하지 않는다 |

## 6. 정량 게이트가 없는 영역

아래 영역은 CI에서 숫자로 떨어지는 자동 게이트가 없다. 어떻게 메꾸는지 함께 적는다.

| 영역 | 없는 이유 | 메꾸는 법 |
| --- | --- | --- |
| 실제 테일넷 다중 사용자 접속 | CI 러너가 테일넷에 조인할 수 없다 | `--auth trusted-proxy`와 `src/limn/security/tests/test_access.py`의 헤더 시뮬레이션으로 대조 |
| 실제 TeX 엔진의 다양한 원고 | TeX Live 전체 설치는 CI에서 너무 무겁다 | 최소 fixture 원고와 `test_cross_engine.py`로 핵심 경로만 확인 |
| 브라우저 알림(Service Worker) 실기 동작 | 헤드리스 브라우저에서 푸시 알림 환경이 제한된다 | `sw.js` 구문 검사와 `test_notifications.py`의 이벤트 스트림 검사로 분할 |
| 뷰어 JS 단위 테스트 프레임워크 | 브라우저 JS 린터나 Jest 같은 별도 러너를 두지 않는다(타입 검사 `tsc`만 둔다, §9) | `test_viewer_source.py`의 AST 토큰 검사와 `test_viewer_browser.py`의 Playwright 통합으로 대체 |
| Handbook 같은 파일 안의 §참조 | 정규식만으로 같은 파일의 앵커 존재를 완벽히 가리기 어렵다 | PR 리뷰에서 사람이 링크를 직접 클릭해 확인 |
| private 도우미와 테스트 함수·메서드·fixture의 docstring | docstring 검사(Ruff)는 프로덕션 공개 항목과 테스트 모듈·클래스의 존재만 본다. 기존 테스트 함수의 누락이 많아 테스트 경로에서 `D102`–`D107`을 끈다 | 새로 쓰거나 고친 항목은 리뷰가 docstring의 존재와, 그 설명이 단언과 맞는지 확인한다([code-style-roadmap.md](code-style-roadmap.md) §R9) |
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
| 측정 대상 | 파이썬: 문법 오류, 쓰지 않는 import, 정의되지 않은 이름, 흔한 버그 패턴(`B`), 종료 코드를 정하지 않은 `subprocess.run`(`PLW1510`), 스타일 규칙(`E`·`W`, import 순서 `I`, 옛 문법 `UP`, 단순화 `SIM`), 프로덕션 공개 항목의 docstring 누락(`D100`–`D107`)과 테스트 모듈·클래스의 누락(`D100`·`D101`), 그리고 코드 모양이 `ruff format`의 출력과 같은지. 셸: `administration/instances.sh`·`instance_*.sh`·`test_instances.sh`의 ShellCheck 경고 |
| 적용 조건 | 모든 변경. CI `lint` 작업이 항상 돈다 |
| 실행 | `uv sync --group dev` 뒤 `uv run ruff check`, `uv run ruff format --check`, `uv run shellcheck src/limn/administration/instances.sh src/limn/administration/instance_*.sh src/limn/administration/tests/test_instances.sh`. 포매팅이 어긋나면 `uv run ruff format`이 고친다. 두 도구 모두 개발 의존성이라 로컬과 CI가 `uv.lock`의 같은 버전을 쓴다 |
| 합격 기준 | 세 명령이 0으로 끝난다. 규칙을 끄려면 그 줄에 이유를 적은 주석과 함께 끈다 (예: `# shellcheck disable=SC2016` 위에 이유 한 줄). 포매터를 `# fmt: off`로 끄는 것은 정말 표 모양인 데이터에만 쓴다 |
| 보장 범위 | 켠 규칙만이다. 규칙 목록과 끈 규칙은 `pyproject.toml`의 `[tool.ruff.lint]`가 정본이고, 끈 이유는 [code-style-roadmap.md](code-style-roadmap.md) §R4에 있다. docstring은 프로덕션 공개 항목과 테스트 모듈·클래스의 누락을 검사하며 private 도우미·테스트 함수·메서드는 제외한다 (§6). 타입은 §9가 본다. 뷰어 JS에는 린터가 없다. 타입은 §9의 `tsc`가 보고, §1의 `test_viewer_files`가 node로 문법을, `test_viewer_source`가 토큰으로 죽은 함수·주석에 삼켜진 문장·닫힌 값 표를, `test_viewer_markup`이 HTML 싱크와 `html` 태그 규칙([viewer.md](viewer.md) §마크업 만들기)을 본다 |

## 9. 타입 검사

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 파이썬 타입 힌트의 정합성: 함수 인자와 반환값의 타입 일치, `Optional` 처리, `None` 검사 누락, 닫힌 `Literal` 타입과의 비교 |
| 적용 조건 | 파이썬 코드를 바꿀 때. CI `lint` 작업에서 돈다 |
| 실행 | `uv run mypy`, 이어서 `uv run mypy --platform darwin`. 표준 라이브러리 타입 정의는 플랫폼마다 선언하는 이름이 달라(`os.sched_getaffinity`는 macOS에 없다) CI의 Linux와 기여자의 macOS 양쪽 기준으로 검사한다. 플랫폼에 따라 없는 함수는 정적으로 부르지 않고 실행 시점에 찾는다 |
| 합격 기준 | `Success: no issues found`로 끝나야 한다. `type: ignore`는 외부 라이브러리 타입 스텁 부재 등 불가피한 경우에만 이유 주석과 함께 허용한다 |
| 보장 범위 | Linux와 macOS 기준의 정적 타입 규칙 위반을 잡는다. Windows는 지원 대상이 아니라 검사하지 않는다. 런타임 값의 범위나 비즈니스 불변식은 보장하지 않는다(§1 파이썬 테스트가 맡는다) |

뷰어 JS도 같은 절의 게이트다.

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | `src/limn/viewer/js/` 조각: 정의되지 않은 이름, 닫힌 값 표에 없는 멤버, 없는 속성 접근, 잘못된 인자 타입([viewer.md](viewer.md) §타입 검사) |
| 적용 조건 | 뷰어 JS나 `src/limn/viewer/types/`를 바꿀 때. CI `lint` 작업에서 돈다 |
| 실행 | `npm ci --ignore-scripts` 뒤 `npm run typecheck`(`tsc -p .`)와 `uv run python tools/strict_ratchet.py`(`tsconfig.strict.json`의 조각별 오류 수가 `tools/strict-baseline.json`과 같은지). TypeScript 버전은 `package-lock.json`이 정한다 |
| 합격 기준 | `typecheck`는 출력 없이 0으로 끝나고, 래칫은 기준과 같은 수를 알린다. 타입을 좁히는 JSDoc 캐스트(`/** @type {HTMLElement} */(e.target)`)는 쓰되, `@ts-ignore`·`@ts-expect-error`는 쓰지 않는다 |
| 보장 범위 | `strict`의 하위 옵션 중 `tsconfig.json`에 켠 것만 본다. `strictNullChecks`는 켜져 있고, 암묵적 `any`(`noImplicitAny`)는 아직 보지 않는다. API 응답의 모양(`types/api.d.ts`)은 그 타입을 단 전역 상태와 함수에서만 보고, 그 선언이 실제 응답과 맞는지는 §1의 `test_viewer_types`가 계약 스냅샷·실제 처리기·동기화 생성 함수로 확인한다. 런타임 동작은 §1이 맡는다 |

## 10. 기능 경계 검사

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 기능 패키지의 명시적 `__all__`, 기능 모듈이 다른 기능에서 가져오는 모든 import(공개한 이름 포함), 진입점의 `ENTRYPOINT_IMPORTS` 밖 조립 import와 쓰이지 않는 승인, 승인된 importer가 없는 `__all__` 이름, `TEST_EXPORTS`의 이름을 기능 밖 테스트가 실제로 import하는지, 진입점이 아닌 모듈의 진입점 import, 경계 코드에서 기능으로 이어지는 경로, 소비 기능의 빌드 marker·이력 파일명 참조, 소유권 없는 루트 모듈·미등록 패키지 |
| 적용 조건 | Python 파일·기능 경계를 바꿀 때. CI `lint`와 파이썬 테스트가 항상 실행한다 |
| 실행 | `uv run python tools/check_boundaries.py`; 검사기 자체의 탐지 능력은 `uv run pytest -q tests/architecture/test_boundaries.py` |
| 합격 기준 | 위반 0건, 검사 대상 소스가 존재한다. 다른 기능의 비공개 import, 다른 기능이 공개한 이름의 import, 공용 모듈을 거쳐 기능에 닿는 경계 코드, 서로 import하는 두 기능(직접, 그리고 공용 모듈 경유), 기능 모듈의 진입점 import, 승인된 importer가 없는 `__all__` 이름, 쓰이지 않는 진입점 승인, 미승인 진입점 import, 기능 밖 테스트가 import하지 않는 테스트용 export, 소유권 없는 모듈을 넣으면 실패하고 같은 기능의 내부 import는 통과한다. 루트 Python 파일은 버전 선언과 세 실행 진입점만 허용한다 |
| 보장 범위 | Python AST에 드러나는 절대·상대 import와 전이 경로, 명시적인 빌드 marker·이력 파일명 문자열. 파일명을 동적으로 조립하는 코드는 이 검사만으로 차단하지 못하므로 리뷰가 확인한다. `ENTRYPOINT_IMPORTS`·`TEST_EXPORTS`의 변경은 설계 리뷰 대상이다. 테스트는 기능의 내부 모듈을 직접 import할 수 있고 검사기는 테스트의 import를 `TEST_EXPORTS`의 근거로만 읽는다. 공급자의 값이 소비자가 선언한 Protocol을 충족하는지는 이 검사가 아니라 `server.py`를 보는 mypy가 확인한다. 공급자 질의 테스트는 과거 발행본의 독립성·누락 marker의 기본값·원고 동등성 투영을, 참여자 성질 테스트는 신원 외 필드 배제를, 알림 테스트는 수신자·선택 필드·발췌를 확인한다. 동적 import 문자열·런타임 속성 접근·투영에 담는 정보의 적절성도 리뷰가 확인하며 API 동작 보존은 §4가 확인한다 |

## 구조 이동의 동작 불변 증명(차등 비교)

코드를 옮기거나 리팩토링할 때는 **동작이 바뀌지 않았음**을 차등 비교(differential testing)로 증명한다.

1. **이동 전 측정:** 이동할 대상 모듈의 테스트를 돌려 통과 상태와 실행 시간을 기록한다.
2. **이동 실행:** 파일 이동, import 경로 변경, 조립 지점 연결을 수행한다.
3. **이동 후 대조:** 같은 테스트를 다시 돌려 정확히 같은 결과가 나오는지 확인한다.
4. **스냅샷 대조:** `tests/contracts/test_contract_snapshot.py`로 에이전트 계약에 바이트 단위 차이가 없는지 확인한다.
5. **보고:** 이동 전후의 테스트 건수, 소요 시간, diff 행 수를 PR 설명에 숫자로 적는다.

## 결과를 보고하는 법

게이트 실행 결과는 주관적 감상이 아니라 **측정된 수치**로 보고한다.

- "테스트 통과함" 대신: `1826 passed, 11 skipped in 119s (pytest -n 4)`
- "린트 깨끗함" 대신: `ruff check: 0 errors, ruff format: ok, shellcheck: 0 warnings`
- "인스턴스 테스트 통과" 대신: `test_instances.sh: 190 passed, 0 failed`
- 실패가 있으면: 실패한 테스트 이름, 에러 메시지 첫 줄, 재현 명령을 함께 보고한다.

테스트를 더하거나 고친 변경은 수치와 함께 다음을 적는다.

- 새 테스트마다 실제로 본 실패 실행과, 그 실패를 낸 변이(일부러 깨뜨린 줄) 또는 TDD red 단계
- 버그 수정의 회귀 테스트는 수정 전 실패와 수정 후 통과, 두 실행
- 성질 테스트가 맞을 법한 코드에 쓰지 않았다면 그 이유
- 대역으로 바꾸었거나 이 환경에서 돌리지 못한 관리 의존성(TeX, Chromium, node 등)
- 남은 한계

## 요청과 자원 권한 경계

`src/limn/web/tests/test_request_boundary.py`와 `src/limn/web/tests/test_request_input.py`는 중복 키·헤더·잘못된 인코딩을 거부하고 연결을 닫으며 상태를 쓰지 않는지 확인한다. `src/limn/security/tests/test_authority.py`는 역할별 기존 허용 동작, 새 경로 등록의 기본 거부, 등록된 모든 POST의 작업 선언, 작업·대상·인스턴스가 다른 권한의 거부와 신원 스냅샷을 검증한다. `src/limn/security/tests/test_access_paths.py`는 주체 × 진입 경로와 역할 × 핀 동작·읽기 경로를 실제 처리기로 확인한다. `src/limn/security/tests/test_header_parsers.py`는 Bearer·Host·Origin·신원 헤더·신뢰 프록시 목록 파서가 생성한 어떤 입력에도 값이나 정해진 거절만 내고, 루프백 Host가 루프백 Origin만 받는지 확인한다. `src/limn/platform/tests/test_manuscript_files.py`는 원고 제외 경로, 검사 뒤 심볼릭 링크 교체, 일반 파일 제한과 디스크립터 정리를 실제 파일로 확인한다. `src/limn/pins/tests/test_pin_sequences.py`는 생성한 전이 시퀀스의 상태·식별자·revision·레코드 왕복을 확인한다.

[`test_build_access.py`](../../src/limn/security/tests/test_build_access.py)는 owner·editor·viewer·agent의 재빌드·비교 빌드 HTTP 권한을 실제 Git 이력·파일·문서 잠금·작업 스레드로 확인한다. viewer의 동기·비동기 재빌드, 신원 없는 요청, 잘못되거나 폐기된 토큰과 허용 목록 밖 신원은 거절되며 원고·상태 파일과 빌드 상태가 그대로다. 허용된 비교는 실제 작업을 만들고 현재 원고·발행 빌드를 바꾸지 않는다. TeX 표식의 검사는 허용된 재빌드의 실제 PDF와 viewer 비교의 샌드박스 PDF를 확인한다. 도구가 없는 일반 검사의 작업 생성 확인은 PDF 완성 검증을 대신하지 않는다. 주체별 작업 한도나 HTTP 연결 상한을 새로 집행하는 검사는 아니며, 그 정책의 공백은 [code-style-roadmap.md](code-style-roadmap.md) §경계 집행과 검증의 한계에 남는다.
