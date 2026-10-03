# 코딩 규칙의 적용

Limn의 코딩 규칙은 팀 스킬 `code-implement`, `code-testing`, `code-security`가 정하며, 그 최신 스탠스에 정렬된다. 이 topic은 그 규칙이 Limn의 어느 경계에 적용되는지와 현재 검증 범위를 설명한다. 코드 관례가 스킬과 다르면 스킬을 따른다. 제품 불변식과 설계 멈춤 신호는 [architecture.md](architecture.md)가 정한다.

## R1 판단은 순수 함수, 부수효과는 가장자리

순수 판단(Functional Core)과 부수효과 셸(Imperative Shell)을 엄격히 나눈다. 핀 전이와 편집 판단은 [`lifecycle/rules.py`](../../src/limn/pins/lifecycle/rules.py)와 [`editing/rules.py`](../../src/limn/pins/editing/rules.py)에 있다. 각 기능의 [`service.py`](../../src/limn/pins/lifecycle/service.py)가 잠금 아래 레코드를 읽고 판단 결과를 받아들일 때만 쓰며, 같은 기능의 [`http.py`](../../src/limn/pins/lifecycle/http.py)가 HTTP 응답으로 바꾼다. claim·unclaim과 삭제·복원의 순수 판단은 각 기능의 [`claims/rules.py`](../../src/limn/pins/claims/rules.py)·[`trash/rules.py`](../../src/limn/pins/trash/rules.py)가 소유한다. 여러 기능이 공유하는 문맥은 [`pins/context.py`](../../src/limn/pins/context.py)에 있다. 판단은 시계·파일·HTTP 대신 필요한 사실을 인자로 받는다. 빌드 완료 본문은 [`builds/completion.py`](../../src/limn/builds/completion.py)가 계산하고, 같은 기능의 `run.py`가 시계·잠금·이력 저장·상태 발행을 맡는다.

업무상 거절은 `PinStillOpen`처럼 반환 타입에 드러나는 값이다. 셸은 자기가 처리할 결과만 처리하고 나머지는 전달한다. 신원·권한 거절은 누락된 검사로 요청이 통과하지 않도록 예외로 끝낸다(§R10). 순수 판단은 반환값으로, 쓰기와 응답은 해당 경계의 테스트로 확인한다.

## R2 잘못된 상태를 표현하기 어렵게

타입 시스템을 활용해 유효하지 않은 상태의 표현을 원천 차단한다. 핀은 `OpenPin | ReviewPin | DonePin`이고 휴지통 사본은 `TrashedPin`이다([`pins/model.py`](../../src/limn/pins/model.py)). 공통 필드는 `PinCore`, 상태별 필드는 해당 타입이 갖는다. 저장된 레코드를 읽을 때 `state_of()`가 상태를 정한다. 옛 레코드와 모르는 필드는 버리지 않고 원래 순서로 보존한다. 저장 형식과 API 호환은 [architecture.md](architecture.md) §불변식 3·6이 요구한다.

레코드 왕복은 [`test_model.py`](../../src/limn/pins/tests/test_model.py)와 [`pin_records.jsonl`](../../tests/data/pin_records.jsonl)이 확인한다. 직접 생성하는 명령 값의 잘못된 필드는 [`editing/tests/test_rules.py`](../../src/limn/pins/editing/tests/test_rules.py)와 [`lifecycle/tests/test_rules.py`](../../src/limn/pins/lifecycle/tests/test_rules.py)가 확인한다. 상태마다 데이터와 동작이 같은 빌드 상태에는 이 타입 분리를 강제하지 않는다.

## R3 경계에서 파싱하고, 안쪽은 HTTP를 모른다

입력은 언어이며(LangSec), 경계에서 완전한 값으로 단 한 번 파싱한다 (`parse, don't validate`). 요청 본문과 쿼리는 기능별 [`input.py`](../../src/limn/pins/lifecycle/input.py)와 공통 [`web/parse.py`](../../src/limn/web/parse.py)가 요청 값이나 `InputRejected`로 바꾼다. 서비스는 파싱된 값만 받고 HTTP 상태 코드를 고르지 않는다. 기능별 [`http.py`](../../src/limn/pins/lifecycle/http.py)가 거절을 [api.md](api.md) §오류 응답의 `reason`과 상태 코드로 바꾼다. 시작 거절은 `StartupRefused` 값이며 프로세스 종료는 `server.main()`이 맡는다. [`test_web_parse.py`](../../src/limn/web/tests/test_web_parse.py)와 [`test_errors.py`](../../src/limn/web/tests/test_errors.py)가 요청 및 오류 경계를 확인한다.

## R4 기계적 규칙은 도구가 집행

설정의 정본은 [`pyproject.toml`](../../pyproject.toml)의 Ruff·mypy 절, 실행과 합격 기준은 [verification.md](verification.md) §8·9다. Ruff는 프로덕션의 공개 docstring 누락과 테스트 모듈·클래스의 누락을 검사한다. private 도우미와 테스트 함수·메서드의 누락 및 docstring 내용은 현재 리뷰에서 확인한다. 뷰어 JavaScript는 린터 없이 문법·소스 가드와 브라우저 테스트로 확인한다.

`E501`은 포매터가 코드 줄을 정리하므로 끈다. `UP030`–`UP032`는 계약 메시지의 포매팅 바이트를, `UP042`는 enum 문자열 결과를 보존하려고 끈다. `server.py`의 `E402`는 파일 경로 실행 전에 `sys.path`를 준비해야 해서 예외다. `tools/handbook-publish/`와 번들 vendor 코드는 외부 소유라 검사 대상에서 뺐다. 테스트 함수·메서드의 docstring 누락 규칙은 기존 누락이 많아 테스트 경로에서 제외한다. 새로 쓰거나 고친 테스트는 §R9를 따른다.

## R5 보이지 않는 전역 상태를 명시적 인자로

[`server.py`](../../src/limn/server.py)의 `start()`는 얼린 설정 `RunConfig`, 실행별 자원 `RuntimeResources`, 문서 목록으로 기능별 subsystem을 조립한다. 기능 로직은 각 소유 패키지에 있고 서버는 연결과 실행 순서만 정한다. HTTP 처리기는 `WebApplication`의 요청 경계 포트를 받으며 전체 기능 서비스를 탐색하지 않는다. `StartedServer`는 소켓·HTTP 앱·자원을 함께 반환해 종료 대상을 보존한다. 다른 모듈은 서버의 전역 설정이나 현재 문서를 읽지 않고 필요한 설정·문서·협력자를 인자로 받는다. 실행별 수명과 종료 순서는 [architecture.md](architecture.md) §의존 방향이 소유한다. 서버를 두 벌 띄운 테스트와 모듈별 import 검사가 실행 간 격리를 확인한다.

## R6 변경 이유가 다른 코드는 다른 모듈로 — 동거 기본값과 세로 슬라이스

함께 바뀌는 것을 함께 두는 배치를 기본값으로 삼는다(Common Closure Principle, Locality of Behaviour). 기능별 세로 슬라이스는 규칙·서비스·HTTP·테스트를 함께 소유한다.

- **공개 경계:** 각 슬라이스의 `__init__.py`와 `__all__`가 조립과 다른 기능에 넘기는 계약을 선언한다. 조회는 소비자의 목적에 맞는 완성된 답을 돌려준다. 원본 레코드·이력·상태·지도 그래프·저장소·파서·렌더 구현을 공개하지 않는다. 저장 표현의 해석과 사실 추출은 소유 기능에서 수행한다. 문서용·핀용 빌드 질의, 핀 개수·변경 토큰, 비교용 핀 사실을 구별하며 참여자는 평탄한 신원 사실, 알림은 `Notice`로 전달한다. 조립 지점도 이 표면으로 import한다. 공통 HTTP 계약은 기능의 구체 구현을 import하지 않는다. `tools/check_boundaries.py`의 기능 쌍별·진입점별 허용목록은 공개 이름 중에서도 승인한 import만 통과시킨다. 비공개 접근·공통 코드의 기능 의존·순환도 모든 슬라이스에서 검사한다([verification.md](verification.md) §10).
- **슬라이스 내부의 계층은 폴더가 아니라 의존 방향 규칙이다.** 슬라이스 안에서 순수 판단은 I/O를 import하지 않는다. 기능을 `routes/`, `services/`, `models/`처럼 가로 레이어 폴더로 흩뿌리지 않는다.
- **추상화보다 복제가 싸다 (AHA, Sandi Metz).** 모양이 닮았다는 이유만으로 섣불리 공통 도우미, 유틸리티, 베이스 클래스를 만들지 않는다. 변경 이유가 실제로 같음이 확인될 때만 승격한다.
- **테스트 동거 (Test Colocation).** 새 기능 슬라이스나 이행되는 슬라이스는 해당 슬라이스를 검증하는 테스트를 슬라이스의 `tests/`에 둔다. 기능 독립 장치와 보안·HTTP·실행 자원도 자기 패키지에 테스트를 둔다. 여러 기능을 관통하는 계약·구조 검사는 루트 `tests/`에 둔다. 수집·패키징 규칙은 [verification.md](verification.md) §테스트 파일의 배치가 정한다.
- 경로별 책임과 변경 trigger는 [index.md](index.md) §파일 지도에 있다. 파일 길이만으로 분리하지 않고, 서로 다른 변경 이유, 수명 주기 또는 의존 경계가 확인될 때 나누며, 이동은 [verification.md](verification.md) §구조 이동의 동작 불변 증명(차등 비교)으로 확인한다.

## R7 계약을 말하는 docstring

새로 쓰거나 고친 Python 모듈·타입·함수·메서드는 private 도우미까지 의도와 계약을 docstring으로 설명한다. 전제 조건, 결과, 부수효과, 실패 중 해당하는 것을 코드와 테스트에 대조한다. Ruff의 누락 검사가 모든 내용을 보증하지 않으므로 리뷰가 정확성을 확인한다. Handbook 절을 인용한 주석은 [`test_handbook_refs.py`](../../tests/architecture/test_handbook_refs.py)가 대상 존재를 확인한다.

## R8 정확한 타입 표기

지원 범위는 Python 3.10 이상이다([`pyproject.toml`](../../pyproject.toml)). `mypy --strict`가 `src/limn/` 전체와 합 타입의 `match` 누락을 검사한다. 공개 경계와 추론이 어려운 값에 타입을 적고, 외부 값은 경계에서 내부 표현으로 바꾼다. 테스트는 루트 수집 트리와 기능 안의 `tests/` 모두 mypy 탐색 대상에서 제외한다. 프로덕션 코드의 엄격 검사는 유지한다. 검사 명령과 보장 범위는 [verification.md](verification.md) §9에 있다.

## R9 구조가 아닌 동작을 고정하는 테스트

테스트는 내부 구조가 아니라 관찰 가능한 동작을 고정한다(Kent Beck의 Test Desiderata, Khorikov의 리팩토링 내성; 팀 스킬 `code-testing`). 동작이 바뀌지 않았는데 실패하는 테스트는 거짓 경보(false alarm)다. 이 규칙은 새로 쓰거나 고친 테스트에 적용하며, 손대지 않은 테스트를 이 규칙에 맞추려고 다시 쓰거나 옮기지 않는다.

- **출력 기반 검증 우선 (Output-based first):** 순수 함수가 반환하는 값으로 판단을 검증한다. 비즈니스 규칙 검증에 목(mock)이 필요하다면 순수 함수를 추출하라는 설계 신호다.
- **소유한 것만 모킹 (Mock only what you own):** 파일시스템, 상태 디렉터리, Git·TeX 같은 로컬 프로세스 등 Limn이 단독 소유하는 관리 의존성은 실제로 실행한다. 비관리 외부 의존성만 Limn이 소유한 어댑터 경계에서 대체한다. 내부 비공개 도우미나 협력자의 호출 여부·순서를 단언하지 않는다.
- **대역은 주입 지점으로:** 대역은 인자·fixture 같은 주입 지점으로 넣는다. 호출자 테스트에서 `time`·`os`·`threading`·`socket` 같은 라이브러리나 전역을 `patch`하지 않는다. 그런 patch가 필요하면 시계·프로세스 같은 협력자를 인자로 받으라는 설계 신호다. 기존 patch는 그 테스트를 고칠 때 정리한다.
- **거절은 값으로 단언:** 예상된 업무상 거절은 반환 값으로 단언한다(`assert result == PinStillOpen(...)`). `pytest.raises`는 결함, 생성자 불변식, §R10의 신원·권한 거절에 쓴다.
- **성질 기반 불변식 검증 (Property-Based Testing; Hypothesis):** Hypothesis는 개발 의존성이다. 입력 파싱은 값 아니면 거절이라는 성질, 핀 레코드 왕복, 전이 시퀀스 불변식, 범위 관계처럼 성질이 있는 순수 함수는 생성 입력으로 검증하고, 경계는 예제 테스트로 확인한다. 성질은 HTTP나 상태 디렉터리를 거치지 않으며 대상 코드를 다시 구현하지 않는다. 변경 요청이 불변식을 말하면 성질 테스트는 필수이고, 그런 성질이 없는 코드에는 쓰지 않는다.
- **실패를 보지 않은 테스트 불신 (Mutation testing; Red phase):** 테스트 작성 후 고의로 대상 코드를 깨뜨려 테스트 실패를 확인하거나, TDD red 단계를 거친다.
- **회귀 테스트는 수정 전에 실패한다:** 버그 수정의 회귀 테스트는 고치기 전 실패와 고친 뒤 통과를 모두 실행해 기록한다. 기대값을 출력에 맞춰 바꾸려면 명세상의 이유가 있어야 한다.
- **동작을 설명하는 이름과 docstring:** 새로 쓰거나 고친 테스트 모듈·클래스·함수·fixture·도우미에는 보호하는 동작이나 위험을 docstring으로 적고, 리뷰는 그 설명과 단언이 맞는지 대조한다. 테스트 배치와 전체 게이트는 [verification.md](verification.md) §1과 §게이트와 정보 검사가 소유한다.

## R10 신뢰 경계는 보안 규칙으로

신뢰 경계를 건드릴 때는 `code-security` 원칙을 철저히 집행한다.

- **권한은 값으로 전달 (Object Capabilities):** 권한은 검증된 신원에서 파생된 핸들 값(Object Capability)으로 하위 함수에 전달한다. 전역 객체나 요청의 임의 파라미터에 의존하지 않는다. 변경 진입점은 `PostAuthority`를 받는다. 읽기 권한은 인스턴스 전체 단위라서 GET 처리기는 경로 허용(`check_read`) 뒤 요청의 문서 키·핀 번호를 그대로 쓴다. 새로 만들거나 고치는 읽기 경로가 문서·핀 단위 권한을 갖게 되면 핸들로 받는다. 에이전트/LLM 도구는 대리인(deputy)이므로 읽은 내용은 데이터일 뿐 권한이 아니며, 부수효과는 승인된 주체만 실행한다.
- **단일 지점 완전 중재 및 기본 거부 (Saltzer & Schroeder):** 모든 접근 판단은 한곳에서 닫힌 상태(closed by default)로 중재한다. 알 수 없는 경로는 기본 거부하고, 오류 시 닫힌 상태를 유지한다. 신원·입장·역할·Host/Origin 판단은 [`security/access.py`](../../src/limn/security/access.py)가 총괄한다.
- **보여준 것을 승인한다 (WYSIWYS):** 사람의 승인은 보여준 대상과 판에 묶여야 한다. 지금의 `POST /api/pins/{id}/confirm`은 판을 받지 않고 그 순간의 핀을 완료로 바꾼다. 사람이 본 뒤 에이전트가 다시 열고 다른 `changes`로 닫으면 본 적 없는 결과가 승인된다. 이 공백은 알려진 부채이며, 판을 받는 필드를 더하는 것은 에이전트 계약 변경이라 설계 승인 뒤에 한다.
- **허용은 기록된 결정만:** 공개 자원과 실패 시 열리는 읽기는 없다. 모든 경로가 신원 판단을 거친다. 허용 목록이 없는 인스턴스에서 닿는 사람을 `editor`로 들이는 것과, 에이전트 역할이 사람 확인 없이 할 수 있는 일의 범위는 [ADR-0002](../adr/0002-access-control.md)의 신원·권한 층 결정이며, 현재 규칙은 [api.md](api.md) §인증이 정한다. 이 밖의 허용을 넓히려면 같은 수준의 결정 기록이 필요하다.
- **입력은 언어이며 완전히 인식 (LangSec):** 경계에서 단 한 번 완전한 값으로 파싱하며 애매한 입력은 거부한다(§R3).
- **위험한 싱크는 안전하게 구성 가능한 타입만 수용 (Secure by Construction):** 원고 파일을 읽는 싱크는 검사 생성자가 만든 `ManuscriptFile`만 받는다. Git·latexdiff·latexmk 실행은 검토된 인자 조립, 리비전 형식 검사, 시간 제한에 기대며 타입으로 강제되지 않는다(§경계 집행과 검증의 한계).
- **비밀은 키에만 두고 필요한 데이터만 유지 (Kerckhoffs):** 표준 암호 프리미티브와 상수 시간 비교를 사용하며, 토큰 원문이나 불필요한 민감 정보를 로그나 응답에 남기지 않는다. 서버 바인드와 인증의 멈춤 신호는 [architecture.md](architecture.md) §멈춤 신호, 실제 HTTP 계약은 [api.md](api.md) §인증이 정한다.


## 경계 집행과 검증의 한계

요청의 중복 JSON 키·반복 쿼리·단일값 보안 헤더와 잘못된 인코딩은 `web/request_input.py`와 처리기가 거부한다. 정상 클라이언트 형식과 거절 순서는 [api.md](api.md)가 정한다. `security/access.py`의 명시적 경로 목록은 새 등록을 기본 거부하고, 변경 진입점은 `PostAuthority`의 작업·대상·실행 범위를 검사한다. 일반 actor mapping은 저장용 데이터이며 변경 권한으로 받지 않는다.

원고 파일을 읽는 싱크는 `ManuscriptFile`만 받는다. 검사 생성자가 루트·점 이름·상태 폴더 제외 규칙을 적용하고, 실제 읽기는 no-follow 파일 디스크립터 순회로 심볼릭 링크 교체를 거부한다. Python은 생성자를 완전히 봉인하지 못하므로 발급 경로의 소스 가드와 타입 검사를 함께 쓴다. 소스 가드는 `test_authority.py`의 `test_production_authority_issuance_stays_at_the_boundary`와 `test_manuscript_files.py`의 `test_only_checked_factory_constructs_capabilities`이며, 생성자 호출 모양을 찾는 AST 검사라서 `_replace`·`copy`·`object.__setattr__` 같은 우회는 잡지 못한다. 봉인이 아니라 실수를 막는 장치다. 이미 신뢰된 상태·빌드 산출물의 경로와 원고 입력 경로는 소유 경계가 다르다. Git 실행은 검토된 명령 조립과 `platform/git.py`의 인자·환경·시간 제한을 유지하며, 일반 인자 배열에 이름만 붙인 타입으로 안전을 주장하지 않는다.

성질 테스트는 입력 파싱, 핀 전이 시퀀스, 값·범위·왕복·빌드 결과를 검증한다. 생성한 입력 밖의 모든 상태와 동시 실행 순서를 완전 탐색한다는 뜻은 아니다. private docstring의 내용과 테스트 대역의 적절성도 도구 통과만으로 증명되지 않는다. 문서화 규칙은 새로 쓰거나 고친 코드에 적용하며, 내용이 그대로인 이동이나 미수정 테스트 전체에 기계적인 설명을 덧붙이지 않는다.

보안 검증에는 다음 공백이 있다. 고치는 변경은 해당 검사를 함께 더한다.

- **진입점 목록 검사:** POST 작업 표와 새 경로의 기본 거부는 `test_authority.py`가 확인하지만, 등록된 모든 POST가 작업과 역할 판단을 선언하는지 훑는 검사는 없다. GET 처리기는 경로를 선언하지 않는 클로저라 목록으로 뽑을 수 없고, `/pages/`·`/vendor/pdfjs/` 접두사는 통째로 허용된다.
- **권한 행렬:** 역할 × 작업은 단위 수준, 주체 × 진입 경로는 `test_access_paths.py`가 일부 변경 작업만 HTTP로 확인한다. 읽기 경로와 나머지 변경 작업(`edit`·`drop`·`restore`·`purge`·`claim`·재빌드·비교 빌드)은 주체별 HTTP 행렬에 없다.
- **주체별 작업 한도:** `viewer`도 부를 수 있는 `/api/pick`(SyncTeX 실행)과 비교 빌드는 주체별 한도가 없다. 비교 빌드 슬롯은 프로세스 전체가 나눠 쓰고, HTTP 서버에는 스레드·연결 상한이 없다.
- **헤더 파서의 생성 입력:** 요청 본문은 Hypothesis로 검사하지만 Bearer·Host·Origin·네트워크 목록·행위자 헤더 파서는 예제 테스트뿐이다.
- **오류 응답:** 처리되지 않은 예외의 `500` 응답 본문에 예외 문장이 실린다. 들어온 모든 주체가 내부 경로나 구현 세부를 볼 수 있다.
- **CI 공급망:** 액션과 체크아웃은 아래 규칙으로 닫혀 있지만, `uv tool install .`이 쓰는 빌드 백엔드(`hatchling`)와 `setup-uv`가 설치하는 uv 버전은 고정되어 있지 않다.

CI는 남이 바꿀 수 있는 코드를 실행하지 않는다. 워크플로 토큰은 `contents: read`이고 비밀을 쓰지 않는다. 외부 액션은 태그가 아니라 커밋 SHA로 고정한다. 태그는 검토 뒤에도 다른 코드로 옮겨질 수 있기 때문이다. 체크아웃은 `persist-credentials: false`로 토큰을 `.git/config`에 남기지 않는다. 고정값은 Dependabot([`.github/dependabot.yml`](../../.github/dependabot.yml))이 매주 올리고, [`test_ci_pins.py`](../../tests/architecture/test_ci_pins.py)가 두 규칙을 검사한다.

입력·권한 정책을 강화하는 변경은 동작 보존 리팩토링과 구분하고 [architecture.md](architecture.md) §멈춤 신호에 따라 설계한다.
