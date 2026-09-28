# 코딩 규칙의 적용

Limn의 코딩 규칙은 팀 스킬 `code-implement`, `code-testing`, `code-security`가 정한다. 이 topic은 그 규칙이 Limn의 어느 경계에 적용되는지와 현재 검증 범위를 설명한다. 코드 관례가 스킬과 다르면 스킬을 따른다. 제품 불변식과 설계 멈춤 신호는 [architecture.md](architecture.md)가 정한다.

## R1 판단은 순수 함수, 부수효과는 가장자리

핀 전이와 편집 판단은 [`pins/lifecycle.py`](../../src/limn/pins/lifecycle.py)와 [`pins/edit.py`](../../src/limn/pins/edit.py)에 있다. 각 기능의 [`service.py`](../../src/limn/features/pins/lifecycle/service.py)가 잠금 아래 레코드를 읽고 판단 결과를 받아들일 때만 쓰며, 같은 기능의 [`http.py`](../../src/limn/features/pins/lifecycle/http.py)가 HTTP 응답으로 바꾼다. 여러 기능이 공유하는 문맥은 [`service/context.py`](../../src/limn/service/context.py)에 있다. 판단은 시계·파일·HTTP 대신 필요한 사실을 인자로 받는다.

업무상 거절은 `PinStillOpen`처럼 반환 타입에 드러나는 값이다. 셸은 자기가 처리할 결과만 처리하고 나머지는 전달한다. 신원·권한 거절은 누락된 검사로 요청이 통과하지 않도록 예외로 끝낸다(§R10). 순수 판단은 반환값으로, 쓰기와 응답은 해당 경계의 테스트로 확인한다.

## R2 잘못된 상태를 표현하기 어렵게

핀은 `OpenPin | ReviewPin | DonePin`이고 휴지통 사본은 `TrashedPin`이다([`pins/model.py`](../../src/limn/pins/model.py)). 공통 필드는 `PinCore`, 상태별 필드는 해당 타입이 갖는다. 저장된 레코드를 읽을 때 `state_of()`가 상태를 정한다. 옛 레코드와 모르는 필드는 버리지 않고 원래 순서로 보존한다. 저장 형식과 API 호환은 [architecture.md](architecture.md) §불변식 3·6이 요구한다.

레코드 왕복은 [`test_pins_model.py`](../../tests/test_pins_model.py)와 [`pin_records.jsonl`](../../tests/data/pin_records.jsonl)이 확인한다. 직접 생성하는 명령 값의 잘못된 필드는 [`test_pins_edit.py`](../../tests/test_pins_edit.py)와 [`test_pins_lifecycle.py`](../../tests/test_pins_lifecycle.py)가 확인한다. 상태마다 데이터와 동작이 같은 빌드 상태에는 이 타입 분리를 강제하지 않는다.

## R3 경계에서 파싱하고, 안쪽은 HTTP를 모른다

요청 본문과 쿼리는 기능별 [`input.py`](../../src/limn/features/pins/lifecycle/input.py)와 공통 [`web/parse.py`](../../src/limn/web/parse.py)가 요청 값이나 `InputRejected`로 바꾼다. 서비스는 파싱된 값만 받고 HTTP 상태 코드를 고르지 않는다. 기능별 [`http.py`](../../src/limn/features/pins/lifecycle/http.py)가 거절을 [api.md](api.md) §오류 응답의 `reason`과 상태 코드로 바꾼다. 시작 거절은 `StartupRefused` 값이며 프로세스 종료는 `server.main()`이 맡는다. [`test_web_parse.py`](../../tests/test_web_parse.py)와 [`test_errors.py`](../../tests/test_errors.py)가 요청 및 오류 경계를 확인한다.

## R4 기계적 규칙은 도구가 집행

설정의 정본은 [`pyproject.toml`](../../pyproject.toml)의 Ruff·mypy 절, 실행과 합격 기준은 [verification.md](verification.md) §8·9다. Ruff는 프로덕션의 공개 docstring 누락과 테스트 모듈·클래스의 누락을 검사한다. private 도우미와 테스트 함수·메서드의 누락 및 docstring 내용은 현재 리뷰에서 확인한다. 뷰어 JavaScript는 린터 없이 문법·소스 가드와 브라우저 테스트로 확인한다.

`E501`은 포매터가 코드 줄을 정리하므로 끈다. `UP030`–`UP032`는 계약 메시지의 포매팅 바이트를, `UP042`는 enum 문자열 결과를 보존하려고 끈다. `server.py`의 `E402`는 파일 경로 실행 전에 `sys.path`를 준비해야 해서 예외다. `tools/handbook-publish/`와 번들 vendor 코드는 외부 소유라 검사 대상에서 뺀다. 테스트 함수·메서드의 docstring 누락 규칙은 기존 누락이 많아 테스트 경로에서 제외한다. 새로 쓰거나 고친 테스트는 §R9를 따른다.

## R5 보이지 않는 전역 상태를 명시적 인자로

[`server.py`](../../src/limn/server.py)의 `start()`가 얼린 설정 `RunConfig`, 실행별 자원 `Runtime`, 문서 목록을 `ServerApplication`에 묶는다. `StartedServer`는 소켓과 앱을 함께 반환해 종료 대상을 보존한다. 다른 모듈은 서버의 전역 설정이나 현재 문서를 읽지 않고 필요한 설정·문서·협력자를 인자로 받는다. 실행별 수명과 종료 순서는 [architecture.md](architecture.md) §상태를 주고받는 방식이 소유한다. 서버를 두 벌 띄운 테스트와 모듈별 import 검사가 실행 간 격리를 확인한다.

## R6 변경 이유가 다른 코드는 다른 모듈로

기능별 세로 슬라이스는 규칙·서비스·HTTP를 함께 소유한다([ADR-0009](../adr/0009-backend-vertical-slices.md)). 순수 규칙, 파일·프로세스 셸, HTTP, 조립 지점의 의존 방향은 [architecture.md](architecture.md) §현재 구조·§의존 방향이 정한다. 경로별 책임과 변경 trigger는 [index.md](index.md) §파일 지도에 있다. 파일 길이만으로 분리하지 않는다. 서로 다른 변경 이유, 수명 주기 또는 의존 경계가 확인될 때 나누고, 이동은 [verification.md](verification.md) §구조 이동의 동작 불변 증명(차등 비교)으로 확인한다.

## R7 계약을 말하는 docstring

새로 쓰거나 고친 Python 모듈·타입·함수·메서드는 private 도우미까지 의도와 계약을 docstring으로 설명한다. 전제 조건, 결과, 부수효과, 실패 중 해당하는 것을 코드와 테스트에 대조한다. Ruff의 누락 검사가 모든 내용을 보증하지 않으므로 리뷰가 정확성을 확인한다. Handbook 절을 인용한 주석은 [`test_handbook_refs.py`](../../tests/test_handbook_refs.py)가 대상 존재를 확인한다.

## R8 정확한 타입 표기

지원 범위는 Python 3.10 이상이다([`pyproject.toml`](../../pyproject.toml)). `mypy --strict`가 `src/limn/` 전체와 합 타입의 `match` 누락을 검사한다. 공개 경계와 추론이 어려운 값에 타입을 적고, 외부 값은 경계에서 내부 표현으로 바꾼다. 테스트 파일은 현재 mypy 대상이 아니다. 검사 명령과 보장 범위는 [verification.md](verification.md) §9에 있다.

## R9 동작을 이름과 docstring으로 말하는 테스트

테스트는 관찰 가능한 결과를 위험을 잃지 않는 가장 좁은 경계에서 확인한다. 순수 판단은 반환값으로, 저장·직렬화·HTTP는 해당 경계에서 확인한다. 새 테스트 모듈·클래스·함수·도우미에는 보호하는 동작이나 위험을 docstring으로 적는다. 결함 회귀 테스트는 수정 전 실패와 수정 후 통과를 확인한다. 테스트 배치와 전체 게이트는 [verification.md](verification.md) §1이 소유한다.

## R10 신뢰 경계는 보안 규칙으로

신원·입장·역할·Host/Origin 판단은 [`access.py`](../../src/limn/access.py)가 맡는다. 권한 거절은 호출자가 무시해도 통과하지 않도록 `HTTPError`를 던진다. 파일 경로, 명령 실행, 외부 URL을 포함한 신뢰 경계를 고칠 때는 `code-security`를 적용하고 부정 경우를 검증한다. 서버 바인드와 인증의 멈춤 신호는 [architecture.md](architecture.md) §멈춤 신호, 실제 HTTP 계약은 [api.md](api.md) §인증이 정한다.
