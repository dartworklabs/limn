# ADR-0041: 백엔드의 구조 적합성을 파일 이름과 더 엄격한 타입 검사로 자동 집행한다

| | |
| --- | --- |
| **번호** | ADR-0041 |
| **제목** | 백엔드의 구조 적합성을 파일 이름과 더 엄격한 타입 검사로 자동 집행한다 |
| **상태** | 승인됨 |
| **결정일** | 2026-11-16 |
| **결정자** | Limn 소유자(CTO)가 2026-11-16 대화에서 지시 |
| **출처** | 1단계 구현(`tools/check_types.py`, `tools/check_fitness.py`, `tests/architecture/test_type_gate.py`, `tests/architecture/test_fitness.py`)과 그 구현에서 일부러 넣어 본 위반의 검출 결과 |
| **부분 대체** | 없음. mypy를 타입 게이트로 둔 것은 번호 기록이 아니라 Handbook의 현재 규칙이었다([code-style-roadmap.md](../handbook/code-style-roadmap.md) §R8, [verification.md](../handbook/verification.md) §9). [ADR-0009](0009-backend-vertical-slices.md)의 세로 슬라이스와 기능 경계 검사(`tools/check_boundaries.py`)는 그대로이고, 이 기록은 그 안쪽에 층을 하나 더한다 |

## 맥락

백엔드(`src/limn`, 테스트를 뺀 약 3만 5천 줄)는 기능 사이의 import를 막는 경계 검사와 `mypy --strict`를 이미 게이트로 둔다. 그래도 세 가지는 사람의 리뷰에만 기대고 있었다.

- **슬라이스 안의 계층.** "순수 판단은 I/O를 import하지 않는다", "HTTP는 서비스만 부른다"는 규칙은 문장으로만 있다. 어느 모듈이 순수 판단인지 코드에서 알 길이 없어 검사기가 그 규칙을 걸 수 없다.
- **타입의 비상구.** `isinstance`로 합 타입을 가르는 분기(프로덕션 코드의 호출 566개, 그중 핀 슬라이스에 290개), `case _`로 끝나는 `match`, `# type: ignore`는 타입 검사가 보는 범위를 줄인다. mypy는 `Any`가 흘러드는 자리(`dict[str, Any]`가 148개)를 대부분 통과시킨다.
- **원시 타입의 도메인 개념.** 핀 번호·문서 키·로그인·줄 번호·상태 이름이 판단 함수의 서명에서 `str`·`int`다. 서로 바꿔 넘겨도 타입 검사가 잡지 못한다.

소유자는 이 셋을 "이름과 경로에서 기계적으로 읽히는 적합성"으로 집행하라고 지시했다. 결정은 아래 다섯이고, 이 기록은 그 결정과 1단계 구현에서 정한 세부를 적는다.

## 결정

| | | |
| --- | --- | --- |
| D1 | **basedpyright가 mypy를 대신해 프로덕션 코드의 타입 게이트가 된다.** `typeCheckingMode = "all"` 이고, 끄는 규칙은 `pyproject.toml` 에 한 줄씩 이유를 단다. Linux와 macOS 두 플랫폼으로 검사한다. 게이트가 들어올 때 있던 오류는 basedpyright의 기준선(`.basedpyright/baseline.json`)에 두고, 기준선은 줄기만 한다. 새 오류는 실패이고, 기준선보다 오류가 적어도 기준선을 내려 커밋할 때까지 실패다. mypy는 그것이 집행하던 것을 basedpyright가 모두 잡는다는 것을 넣어 본 위반으로 보인 뒤에 뺀다 | 승인됨 |
| D2 | **닫힌 타입 위의 `match`는 빠짐없이 다룬다.** 와일드카드 `case _`(그리고 무엇이든 받는 이름 하나의 `case x`)는 몸이 `assert_never(...)` 하나일 때만 쓴다 | 승인됨 |
| D3 | **`isinstance`와 `cast`로 분기를 빠져나가지 않는다.** `typing.cast`, `# type: ignore`, `# pyright:` 주석은 프로덕션 코드에서 쓰지 않는다. `isinstance`는 밖의 데이터나 저장된 데이터를 타입 있는 값으로 바꾸는 경계 파싱 역할에서만 쓰고, 그 밖에서는 닫힌 타입 위의 `match`로 좁힌다 | 승인됨 |
| D4 | **순수 판단·모델 역할의 공개 서명과 필드는 도메인 개념을 원시 타입으로 적지 않는다.** `str`·`int`·`dict[...]` 대신 NewType·값 타입·`Literal`을 쓴다. 사람이 쓴 자유 글처럼 정말로 `str`인 값은 검토를 거친 별칭 하나(`limn.platform.text.FreeText`)로 적는다. `Any`는 basedpyright의 `reportExplicitAny`가 모든 모듈에서 맡는다 | 승인됨 |
| D5 | **파일 이름과 경로가 모듈의 역할을 말하고, 적합성 검사가 그것을 집행한다.** 모든 프로덕션 모듈의 역할은 경로와 파일 이름에서 정해지고, 역할마다 import·I/O·`isinstance`·`limn.web`·원시 타입의 규칙이 있다. 이름이 어느 역할도 말하지 않는 모듈은 위반이다. 계층은 의존 규칙이지 폴더가 아니다. `routes/`·`services/`·`models/` 폴더를 만들지 않는다 | 승인됨 |

## 1단계에서 정한 세부

- **역할 어휘.** 진입점 셋(`server.py`·`cli.py`·`__main__.py`)은 경로로, 모든 `__init__.py`는 패키지 표면으로 정한다. 그다음 파일 이름의 낱말(`rules.py` 또는 `<무엇>_rules.py`)이 정한다. 낱말은 기존 이름에서 골랐다: `rules`(판단), `values`·`model`(모델), `needs`·`contracts`(받는 것의 선언), `input`·`parse`(경계 파싱), `http`·`routes`·`answer`(HTTP 어댑터), `service`·`run`(셸), `store`·`queries`(저장), `application`(조립). 이름이 정하지 않으면 경계 패키지가 정한다: `platform/`·`web/`·`runtime/`. 기존 모듈 178개 가운데 115개가 이 규칙으로 역할을 받고 63개는 받지 못한다. 63개는 이름을 바꾸지 않고 기준선에 둔다.
- **역할의 규칙.** 판단·모델·선언·파싱은 어떤 런타임 import 경로로도 I/O에 닿지 않는다(`TYPE_CHECKING` 아래 import는 돌지 않으니 I/O로 세지 않지만 역할 사이의 의존으로는 센다). HTTP 어댑터와 표면은 스스로 I/O 모듈을 import하지 않되 셸을 부를 수 있다. 셸·저장·조립·진입점·경계 패키지는 I/O를 한다. 역할마다 import해도 되는 역할이 정해져 있고, 역할이 없는 모듈을 import하는 것도 위반이다. `limn.web`은 진입점·표면·조립·HTTP 어댑터·파싱·`web/`만 import한다.
- **원시 타입 규칙의 범위.** 판단·모델·선언 모듈의 공개 함수와 공개 클래스의 공개 메서드(`__init__`·`__call__`·`__new__` 포함)의 매개변수·반환, 공개 클래스의 필드를 본다. 별칭은 어느 모듈에 정의됐든 펼쳐 본다. `FreeText`만 펼치지 않는다. 검토한 별칭 목록은 `tools/check_fitness.py`의 `PRIMITIVE_ALIASES`이고, 항목 하나가 설계 결정이다.
- **`assert_never`.** `typing.assert_never`는 Python 3.11부터 있고 런타임 의존성은 없으므로, 같은 서명의 함수를 `limn.platform.never`에 둔다.
- **기준선.** basedpyright의 기준선은 basedpyright가 오류가 줄면 스스로 다시 쓰고 0으로 끝나므로, `tools/check_types.py`가 두 플랫폼을 돌린 뒤 파일이 바뀌었으면 실패시킨다. 적합성 검사의 기준선은 최상위 패키지마다 파일 하나(`tools/fitness-baseline/<슬라이스>.json`, 루트 파일은 `root.json`)에 모듈별·규칙별 수를 둔다. 슬라이스마다 다른 작업자가 같은 파일을 고치지 않고 동시에 줄여 갈 수 있게 하기 위해서다. `--update`는 수를 내리기만 하고 올리지 않는다. 모듈을 옮기면 `--rename OLD=NEW`로 수를 따라 옮기고, 새 이름의 역할이 더 보는 규칙의 위반은 옮겨 오지 않으므로 먼저 고친다.
- **끈 basedpyright 규칙.** `reportImplicitOverride`(`@override`는 3.12의 `typing`이나 `typing_extensions`에만 있다), `reportImplicitStringConcatenation`(배치는 Ruff format의 일이고 긴 계약 문장을 그렇게 감싼다), `reportUnusedCallResult`(버린 반환값은 타입 결함이 아니다), `reportImportCycles`(슬라이스 사이의 순환은 경계 검사의 일이고, pyright는 `TYPE_CHECKING` 아래 import까지 세어 모든 지연 표면을 돌지 않는 순환으로 본다).
- **mypy를 뺀 근거.** mypy가 이 저장소에서 집행하던 것마다 basedpyright에 위반을 넣어 보았다. 닫힌 `Literal`과 합 타입 위의 빠진 `match`(`reportMatchNotExhaustive`), 닫힌 `Literal` 밖 값과의 `==`·`in`(`reportUnnecessaryComparison`·`reportUnnecessaryContains`, mypy의 `strict_equality`), 틀린 인자 타입, 확인하지 않은 `None`, Protocol을 충족하지 않는 공급자, 함수의 반환 누락, 타입을 적지 않은 함수, 암묵적 재내보내기(`reportPrivateLocalImportUsage`, mypy의 `no_implicit_reexport`), macOS에 없는 표준 라이브러리 이름(`--pythonplatform Darwin`)이 모두 보고되었다. `# type: ignore`는 아무것도 막지 않는다(`enableTypeIgnoreComments = false`). 이 검출은 `tests/architecture/test_type_gate.py`가 저장소의 설정 그대로 매번 다시 확인한다. mypy로만 잡던 것이 남지 않아 mypy는 개발 의존성과 CI에서 뺀다.

## Trade-off

- **얻는 것.** 계층 규칙이 이름에서 기계적으로 읽혀 새 코드가 처음부터 지킨다. 판단 모듈이 셸이나 `limn.web`을 끌어오면 그 줄에서 실패한다. `Any`·`cast`·무시 주석으로 타입 검사를 피하는 길이 기준선 밖에서는 닫힌다. 기준선은 슬라이스별이라 줄이는 일을 나눠 맡을 수 있다.
- **감수하는 것.**
  - 기준선이 크다. basedpyright 오류 1,532개, 적합성 위반 1,036개(파싱 역할 밖의 `isinstance` 497, 원시 타입 343, 역할 사이 import 108, 역할이 없는 이름 63, I/O 17, `limn.web` 8)가 기록된 채 남는다. 기준선 안의 위반은 게이트가 막지 않는다.
  - 역할이 없는 63개 모듈은 이름을 바꾸거나 나누기 전까지 역할의 규칙(I/O, 원시 타입, import)을 받지 않는다. 이름을 바꿀 때 새 역할의 위반을 먼저 고쳐야 한다.
  - 이름이 역할을 정하므로 이름을 잘못 붙이면 규칙도 잘못 걸린다. 검사는 이름이 말하는 역할을 코드가 지키는지를 볼 뿐, 그 이름이 맞는지는 리뷰가 본다.
  - 검사는 AST만 본다. `Path` 값의 I/O 메서드 호출, 동적 import, 런타임 속성 접근은 보지 못한다. 원시 타입 규칙은 `str`·`int`·`dict`만 보고 `float`·`bytes`·`object`는 보지 않는다.
  - 기준선을 손으로 올리는 커밋은 검사가 막지 못한다. 기준선 파일의 수가 늘어난 변경은 `ENTRYPOINT_IMPORTS`의 변경처럼 설계 리뷰 대상이다.
  - basedpyright는 Node 실행 파일을 휠로 받는다(개발 의존성만이다. 런타임 `dependencies = []`는 그대로다).
  - 한 플랫폼에서만 나는 오류는 기준선에 둘 수 없다. 다른 플랫폼의 실행이 그것을 기준선에서 지운다.

## 대안

- **mypy를 두고 적합성 검사만 더한다.** 두 타입 검사기를 함께 돌리면 같은 규칙의 주인이 둘이 된다. mypy의 엄격 모드는 `Any`가 흘러드는 자리와 Protocol 속성의 가변성(공급자의 가변 속성이 소비자의 읽기 전용 Protocol과 맞는지)을 basedpyright만큼 보지 않는다. 채택하지 않는다(D1).
- **역할을 모듈 목록으로 적는다.** 정확하지만 새 모듈마다 목록을 고쳐야 하고, 파일 이름은 여전히 아무것도 말하지 않는다. 소유자의 지시(이름과 경로가 의미를 가진다)에 맞지 않는다. 채택하지 않는다(D5).
- **역할별 폴더(`routes/`·`services/`·`models/`).** 이름 대신 폴더가 역할을 말하게 할 수 있지만, 한 기능을 가로 레이어로 흩뜨려 세로 슬라이스와 `code-implement`의 기본값을 깬다. 채택하지 않는다.
- **1단계에서 이름을 바꾸고 `isinstance`를 고쳐 쓴다.** 기준선이 작아지지만 동작을 바꾸지 않는 대량 이동과 재작성이 게이트 도입과 한 변경에 섞여, 무엇이 동작을 바꿨는지 리뷰가 가를 수 없다. 1단계는 게이트만 녹색으로 들이고, 이동과 재작성은 슬라이스별 후속 변경으로 나눈다.
- **basedpyright의 기준선만 쓰고 감싸지 않는다.** basedpyright는 오류가 줄면 기준선을 스스로 다시 쓰고 0으로 끝나므로 CI에서 낡은 기준선이 실패하지 않는다. 실행 전후의 파일을 비교하는 감싸기를 둔다.

## 결과

- 현재 규칙은 Handbook에 있다: [code-style-roadmap.md](../handbook/code-style-roadmap.md) §R4·§R8·§R11, [verification.md](../handbook/verification.md) §9·§11, [architecture.md](../handbook/architecture.md) §의존 방향.
- 2단계(기준선 줄이기)는 슬라이스별로 나눠 맡는다. 역할이 없는 모듈의 이름 바꾸기와 나누기, `isinstance` 분기를 닫힌 타입의 `match`로 바꾸기, 판단·모델의 원시 타입을 NewType·`Literal`로 바꾸기, `Any`가 흘러드는 경계의 파싱이다.
- 되돌릴 조건: basedpyright가 지원 Python(3.10)을 더 검사하지 못하게 되거나, 역할 어휘가 새 기능의 모양을 담지 못해 이름 바꾸기보다 예외가 더 늘면 어휘를 다시 정한다. 그때도 예외는 모듈 목록이 아니라 새 낱말로 더한다.
