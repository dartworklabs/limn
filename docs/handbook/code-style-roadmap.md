# 코딩 규칙 (R1–R10)

이 topic은 Limn 코드에 적용하는 코딩 규칙 열 가지를 설명한다. 규칙마다 무엇을 말하는지, 업계에서 어떤 이름으로 부르는지, 지금 코드의 어디가 그 규칙을 보여 주는지, 어떻게 확인하는지를 적는다. 코드를 쓰거나 리뷰하기 전에 해당 규칙 절을 읽는다. 규칙이 코드에서 지켜지는 모양이 바뀌거나 §다음의 일을 끝내면 이 파일을 고친다.

> **한눈에**
>
> - 규칙이 부딪힐 때 무엇이 이기는가: §규칙 우선순위
> - 이 문서에서 쓰는 말: §용어
> - 규칙별 설명과 지금 코드의 예: §R1 ~ §R10
> - 아직 하지 않은 일과 그 순서: §다음

## 규칙 우선순위

> **핵심**
>
> 규칙이 부딪힐 때의 우선순위는 이렇다.
>
> 1. 제품 불변식 — [architecture.md](architecture.md) §불변식 (127.0.0.1, 표준 라이브러리만, 에이전트 계약, 저장 순서 등)
> 2. 팀 코딩 스킬 — `code-implement`, `code-testing`, `code-security`
> 3. 지금 코드의 관례
>
> 지금 코드가 어떤 방식으로 짜여 있다는 사실만으로는 근거가 되지 않는다. 스킬과 다르면 스킬을 따른다. 다만 손대지 않는 코드를 한꺼번에 뜯어고치지 않는다. 새로 쓰거나 고치는 코드에 규칙을 적용한다.

아래 표는 스킬의 규칙을 Limn에서 중요한 순서로 늘어놓은 것이다. 기준은 "틀렸을 때 피해가 큰가, 그리고 다른 규칙의 발판이 되는가"다. 순위는 중요도이고, 새로 쓰는 코드에는 열 가지를 모두 적용한다.

| 순위 | 규칙 | 스킬 출처 | 이 순위인 이유 |
| --- | --- | --- | --- |
| 1 | R1 판단은 순수 함수, 부수효과는 가장자리 | code-implement | 핀 수명 주기가 Limn의 핵심 가치다. 규칙을 파일과 떼어 놓아야 빠르고 확실하게 테스트할 수 있다 |
| 2 | R2 잘못된 상태를 표현하기 어렵게 | code-implement / modeling | 핀 상태가 저장된 필드의 조합이라 모순된 조합이 생길 수 있다 |
| 3 | R3 경계에서 파싱하고, 안쪽은 HTTP를 모른다 | code-implement / modeling | 검증과 오류 표현이 흩어지면 R1·R2를 적용할 수 없다 |
| 4 | R4 기계적 규칙은 도구 하나가 집행 | code-implement / format | 가장 싸고, 모든 변경을 지켜 주는 안전망이다 |
| 5 | R5 보이지 않는 전역 상태를 명시적 인자로 | code-implement / structure, python-backend | 함수 결과가 숨은 값에 달려 있으면 나누기도 테스트하기도 어렵다 |
| 6 | R6 변경 이유가 다른 코드는 다른 모듈로 | code-implement / structure | R1~R5의 결과를 담을 자리가 모듈 경계다 |
| 7 | R7 계약을 말하는 docstring | code-implement | 머릿속 지도를 코드로 옮기는 가장 직접적인 방법이다 |
| 8 | R8 정확한 타입 표기 | code-implement / python | 경계 값의 모양을 도구가 확인하게 한다 |
| 9 | R9 동작을 이름과 docstring으로 말하는 테스트 | code-testing | 테스트가 무엇을 지키는지 읽혀야 안전하게 옮길 수 있다 |
| 10 | R10 신뢰 경계는 보안 규칙으로 | code-security | 이미 잘 지키고 있어 순위는 낮지만, 경계를 건드리는 변경에는 늘 적용한다 |

## 용어

| 용어 | 쉬운 뜻 |
| --- | --- |
| 순수 함수 | 같은 입력이면 늘 같은 결과를 내고, 파일·시계·네트워크·전역 변수를 건드리지 않는 함수. 테스트가 가장 쉽다 |
| 부수효과 | 함수 밖 세상을 바꾸거나 읽는 일. 파일 쓰기, `subprocess` 실행, 현재 시각 읽기, HTTP 응답 보내기가 모두 부수효과다 |
| 가장자리 (shell) | 부수효과를 모아 두는 바깥층. 요청을 받고, 필요한 사실을 읽고, 순수 판단을 부르고, 결과를 저장한다 |
| 판단 (decision) | "이 요청을 받아들이는가, 결과 상태는 무엇인가"를 정하는 규칙. 순수 함수로 둔다 |
| 조립 지점 (composition root) | 프로그램이 시작할 때 설정을 읽고 자원(잠금, 스레드, 서버)을 만들어 서로 이어 주는 한 곳. Limn에서는 `server.py`다 |
| 경계에서 파싱 | 바깥에서 들어온 값(JSON, 파일 줄, 헤더)을 들어오는 곳에서 한 번 검사해 믿을 수 있는 내부 값으로 바꾸는 것. 안쪽 코드는 다시 검사하지 않는다 |
| 거절 값 | 예상된 실패를 예외 대신 반환값으로 돌려주는 타입. `AgentCannotConfirm`, `PinStillOpen`처럼 이유마다 이름이 있다 |

규칙마다 **업계에서 부르는 이름**을 한 줄씩 달았다. Limn이 새로 만든 규칙이 아니라 널리 쓰는 원칙이라는 뜻이고, 더 읽고 싶을 때 검색할 이름이다.

## R1 판단은 순수 함수, 부수효과는 가장자리

**규칙이 말하는 것.** "이 요청을 받아들일지, 결과 상태가 무엇인지"는 순수 함수로 정한다. 현재 시각, 행위자, 이미 읽어 온 사실을 인자로 받는다. 파일을 읽고 쓰고, 잠금을 잡고, HTTP 상태 코드를 고르는 일은 바깥 층이 한다.

**업계에서 부르는 이름.** Functional Core, Imperative Shell (Gary Bernhardt, "Boundaries" 발표). Mark Seemann은 같은 모양을 "impureim sandwich"라고 부른다.

**지금 코드.** 핀 전이의 규칙은 [`limn/pins/lifecycle.py`](../../src/limn/pins/lifecycle.py)·[`limn/pins/edit.py`](../../src/limn/pins/edit.py)의 순수 함수다. 닫기·다시 열기·확인·답글의 잠금과 쓰기는 [`features/pins/lifecycle/service.py`](../../src/limn/features/pins/lifecycle/service.py), 결과의 HTTP 변환은 같은 기능의 [`http.py`](../../src/limn/features/pins/lifecycle/http.py)에 있다. claim·unclaim은 [`features/pins/claims/service.py`](../../src/limn/features/pins/claims/service.py)에 있고, 나머지 핀 동작은 아직 [`limn/service/`](../../src/limn/service/context.py)와 [`limn/web/answers.py`](../../src/limn/web/answers.py)를 쓴다. 빌드도 같다. 빌드는 결과 값(`BuildOk`·`BuildOkWithErrors`·`FailedBuild` 등)을 돌려주고, `POST /api/rebuild` 의 본문은 [`features/builds/answer.py`](../../src/limn/features/builds/answer.py)가, 실패 로그의 문장은 HTTP 경계가 만든다([build-sync.md](build-sync.md) §빌드 결과).

> **예시**
>
> 확인(confirm) 하나가 세 층을 지난다. 규칙은 파일·시계·HTTP를 모르고, 서명만 보고 결과를 안다.

```python
# limn/pins/lifecycle.py
def confirmer(actor: Actor) -> Person | AgentCannotConfirm:
    """The person who may confirm, or the refusal for an agent - decided before any pin is loaded."""


def confirm(pin: Pin, by: Person, at: str) -> DonePin | AlreadyDone | PinStillOpen:
    match pin:
        case ReviewPin():
            return confirm_review(pin, by, at)
        case DonePin():
            return AlreadyDone(pin)
        case OpenPin():
            return PinStillOpen(pin)


# limn/features/pins/lifecycle/service.py - refuse an agent before the store
def confirm_pin(
    self, pid: int, actor: Mapping[str, Any]
) -> DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound:
    by = confirmer(typed_actor(actor))
    if isinstance(by, AgentCannotConfirm):
        return by
    ctx = self.context()
    ...
    result = confirm(pin, person, ctx.now())  # inside ctx.store.transact(...)
```

같은 기능의 `http.py`에 있는 `confirm_answer()`가 이 다섯 결과를 `match` 하나로 받아 에이전트 계약의 상태 코드와 본문(200, `403 confirm_by_human`, `409 open`)으로 답한다.

**거절을 값으로 돌려주는 이유.** `raise`를 쓰면 서명은 `-> Pin`이라서, 호출하는 쪽은 docstring을 읽어야 거절이 있다는 걸 안다. 잊고 `try`를 빠뜨리면 거절이 처리기 밖까지 새어 500이 된다. 반환 타입에 결과가 모두 드러나면 타입 검사기와 `match`가 처리하지 않은 경우를 드러낸다. 예외는 결함(호출자가 전제를 어김)과 인프라 장애(파일·시간 초과)에만 쓴다. 일반 Result 라이브러리는 들이지 않는다. 보안 경계의 거절은 예외다(R10).

**결과 타입을 고르는 법.** 팀 스킬 `code-implement`의 규칙을 따른다.

- 경우마다 데이터나 응답이 다르면 경우별 타입으로 나눈다(`PinStillOpen(pin)`과 `AgentCannotConfirm()`). 데이터와 응답이 모두 같을 때만 `Literal` 이유 하나로 묶는다. 앱 전체 공용 오류 타입은 만들지 않는다.
- 한 동작의 거절이 여럿이면 이름을 한 번 붙인다(`XRefusal: TypeAlias = A | B`). 서명은 `성공 | 그 이름`으로 읽힌다.
- 셸은 처리할 타입 하나만 보고 나머지는 그대로 돌려준다. 파이썬 `match`는 합 타입 이름을 패턴으로 쓸 수 없으니 구성원을 다시 나열하지 않는다.
- 식별자로 불러온 결과가 없으면 이름 있는 타입(`PinNotFound`)으로 돌려주고, 그 값이 가장자리까지 그대로 간다. 계산의 빈 결과만 `X | None`이다.
- 상태와 이벤트를 한 값에 묶지 않는다. 사실을 기록해야 하는 전이는 `decide → 이벤트 | 거절`, `evolve(상태, 이벤트) → 새 상태`로 나눈다(`decide_close`·`evolve_close`).

**확인하는 법.** 새 순수 함수에는 허용 전이와 거절 조합마다 직접 테스트를 둔다(`tests/test_pins_lifecycle.py`). 순수 모듈은 부수효과 모듈을 가져오지 않는다는 것을 import 검사가 지킨다. 셸을 옮기거나 고치면 처리기를 거치는 기존 테스트가 그대로 녹색이어야 한다.

> **주의**
>
> 모든 함수를 순수로 만들 필요는 없다. 계산·파싱·렌더링은 평범한 함수로 충분하다. 명령(Command)·이벤트 같은 이름 붙은 값은 감사·재시도·여러 입구처럼 실제 필요가 있을 때만 쓴다. 패턴을 채우려고 클래스를 만들지 않는다.

## R2 잘못된 상태를 표현하기 어렵게

**규칙이 말하는 것.** 상태마다 필요한 데이터와 허용되는 동작이 다르면 상태별 타입을 둔다. 그러면 "있을 수 없는 조합"을 애초에 만들 수 없다.

**업계에서 부르는 이름.** Make illegal states unrepresentable (Yaron Minsky, "Effective ML"). Scott Wlaschin의 책 *Domain Modeling Made Functional*이 같은 방법을 자세히 다룬다.

**지금 코드.** 핀은 상태 타입의 합 `Pin = OpenPin | ReviewPin | DonePin`이고, 휴지통 사본은 `TrashedPin`이다([`limn/pins/model.py`](../../src/limn/pins/model.py)). 모든 상태가 함께 가진 필드는 `core: PinCore`로 타입이 있고, 전이·편집·위치 규칙은 `pin.core.rev`·`pin.core.thread`·`pin.core.place`처럼 이 속성을 읽는다. 그 상태에만 있는 필드는 타입의 속성이다. 열린 핀만 처리 중 표시(`Claim`)를, 닫힌 핀만 닫은 기록(`Close`)을, 완료 핀만 확인(`Confirmation`)을, 휴지통 사본만 삭제 기록(`Dropped`)을 가진다. 저장소는 레코드를 읽으며 핀으로 파싱해 서비스에 넘긴다. 저장 형식(`pins.jsonl`)과 API 모양은 그대로다([architecture.md](architecture.md) §불변식 3, 6). 비교 PDF 하나의 상태도 같은 방식으로 타입의 합(`IdleComparison | RunningComparison | ReadyComparison | FailedComparison`, [`features/revisions/jobs.py`](../../src/limn/features/revisions/jobs.py))이다. 캐시를 읽는 쪽과 작업 목록이 이 타입을 내고, 캐시에서 답할지(`answered_from_cache`)와 응답 본문(`status_body`)은 타입으로 가른다. 저장된 `status.json`의 필드는 핀처럼 저장된 그대로 싣는다.

새 핀의 위치 값(`LinePlace`·`RegionPlace`)은 직접 생성해도 필수 좌표와 필드 종류를 검사하고, 저장 필드의 불변 스냅숏을 가진다. `AddRequest`·`EditRequest`는 내부 생성에서도 메모 길이와 필드 종류를 검사하고, `CloseRequest`는 변경 범위의 모양을 검사해 불변 사본으로 보관한다. HTTP 파서는 파일 존재·줄 수·문서의 쪽 수·담당자 신원처럼 외부 사실이 필요한 조건을 먼저 확인한다. `ClaimRequest`는 내부 생성에서도 양수 정수 시간을 요구하고, 닫기 이벤트의 적용 함수는 열린 핀만 받는다. HTTP의 시간 상한과 전이 허용 여부는 각각 경계와 판단 함수의 별도 책임이다.

저장소가 받아들인 레코드는 `fits_record()`의 검사 뒤 `parse_pin()`이 정수 ID와 완전한 줄 또는 영역 위치로 올린다. 자유로운 옛 레코드 파서는 미완성 값도 보존하므로 `PinCore.id`·`place`는 선택 타입으로 남는다. 복원 정렬처럼 저장 경계를 지난 호출부는 `PinCore.pid`로 ID 필수 조건을 드러낸다. 별도 `VerifiedPin` 타입은 없앤 위험 분기보다 저장소·동기화·서비스의 변환 지점이 많아 도입하지 않는다.

> **예시**
>
> "열린 핀의 `confirmed_by`"나 "닫힌 핀의 claim"을 담을 속성이 아예 없다.

```python
@dataclass(frozen=True)
class DonePin:
    """Closed for good: done without review. It has a close, a confirmation when a person confirmed it out of review,
    and no claim. A legacy done record with no review field is done too."""

    state: ClassVar[StateName] = "done"
    core: PinCore  # id, doc, place, note, rev, thread ... - what every state shares
    close: Close
    confirmation: Confirmation | None
    fields: Record  # every field the core and the state do not lift, as stored


Pin: TypeAlias = OpenPin | ReviewPin | DonePin


def parse_pin(record: Record) -> Pin: ...  # by the one rule state_of(); never fails
```

옛 레코드와 어긋난 값은 이렇게 담는다.

- 상태를 가르는 규칙은 `state_of()` 하나다. `done`이 아니면 열림, `done`이고 `review`가 참이면 검토 대기, 나머지 `done`(옛 `review` 없는 레코드 포함)은 완료다. API의 `state` 이름도 이 타입의 이름이다.
- 필드가 없거나 값의 종류가 틀리면 속성으로 올리지 않는다. `fields`에 저장된 그대로 남고, 핀은 그 필드가 없는 것처럼 읽는다. 위치(`LineSpan`·`Region`)는 필드가 모두 맞을 때만 올린다. 파싱은 실패하지 않는다.
- 다른 상태의 필드는 속성이 되지 않는다. 다시 연 핀에 남는 지난 닫기의 `done_at`·`closed_by`는 `fields`에 있을 뿐이다.
- 드물게 쓰는 필드와 이 버전이 모르는 필드는 `fields`에 두고, `order`가 저장 때의 필드 순서를 기억한다. 필드 순서는 바이트 계약의 일부다.

한 상태에만 쓰는 전이는 그 상태 타입만 받는다(`confirm_review(pin: ReviewPin, ...)`). 어떤 상태든 올 수 있는 입구는 `match pin:`으로 타입을 나눈다. 상태 문자열을 비교하지 않는다.

**확인하는 법.** 옛 레코드 모양을 읽어서 다시 쓰면 바이트 단위로 같아야 한다. [`tests/test_pins_model.py`](../../tests/test_pins_model.py)가 레코드 모양 말뭉치 [`tests/data/pin_records.jsonl`](../../tests/data/pin_records.jsonl)(테스트가 읽고 쓴 모양마다 하나, 그리고 옛 모양과 어긋난 값)으로 이것을 지킨다. 새 레코드 모양을 쓰는 코드를 더하면 말뭉치에도 그 모양을 더한다. 새 명령 값은 HTTP를 거치지 않은 직접 생성에서도 잘못된 상태를 거절하는지 [`tests/test_pins_edit.py`](../../tests/test_pins_edit.py)와 [`tests/test_pins_lifecycle.py`](../../tests/test_pins_lifecycle.py)가 확인한다.

> **참고**
>
> 상태가 이름표일 뿐 데이터와 동작이 같다면 문자열이나 `Enum`으로 충분하다. 빌드 상태(`idle`·`running`·`ok`·`ok_errors`·`fail`)가 그런 예다. 핀 수명 주기처럼 상태마다 데이터가 다를 때만 타입을 나눈다.

## R3 경계에서 파싱하고, 안쪽은 HTTP를 모른다

**규칙이 말하는 것.** 요청 JSON, 파일 줄, 헤더처럼 바깥에서 온 값은 들어오는 곳에서 한 번 검사해 내부 값으로 바꾼다. 안쪽 판단은 HTTP 상태 코드를 모른다. 예상된 거절은 반환값으로 표현하고(R1), HTTP 층이 상태 코드와 메시지로 바꾼다. 경계 파서도 같다. 검증된 값이거나 거절 값을 돌려준다.

**업계에서 부르는 이름.** Parse, don't validate (Alexis King).

**지금 코드.** 공통 문서 선택과 여러 기능이 함께 쓰는 요청 파서는 [`limn/web/parse.py`](../../src/limn/web/parse.py)에 있고, 닫기·다시 열기·답글 입력은 [`features/pins/lifecycle/input.py`](../../src/limn/features/pins/lifecycle/input.py), claim 입력은 [`features/pins/claims/input.py`](../../src/limn/features/pins/claims/input.py), 전체 비우기 확인 입력은 [`features/pins/trash/input.py`](../../src/limn/features/pins/trash/input.py), 핀 만들기·편집의 필드 검사·본문 입력·위치 검사는 [`features/pins/editing/fields.py`](../../src/limn/features/pins/editing/fields.py)·[`input.py`](../../src/limn/features/pins/editing/input.py)·[`location.py`](../../src/limn/features/pins/editing/location.py)에 있다. PDF 선택과 원문 구간·겹침 조회의 입력과 응답은 [`features/pins/location/`](../../src/limn/features/pins/location/input.py)이 소유한다. 빌드 조회와 재빌드의 이름·스위치 검사와 응답은 [`features/builds/`](../../src/limn/features/builds/input.py)이, Git 이력·비교 PDF의 입력·응답은 [`features/revisions/`](../../src/limn/features/revisions/input.py)이 소유한다. 기능 경로는 본문과 쿼리를 파서에 넘기고 필드를 직접 읽지 않는다. 경로마다 요청 타입(`ReplyRequest`, `DocChoice`, `RebuildQuery` 등)이 있고, 쿼리 스위치는 `parse_flag` 하나가 읽는다. 핀 위치도 사전이 아니라 타입(`LineLoc`, `RegionLoc`)이고, 저장할 때 `to_record()`가 늘 쓰던 키 순서로 바꾼다. 기능별 HTTP 입구는 파서가 돌려준 거절을 `accepted()`로 400 문장 그대로 답하고, 서비스에는 파싱된 값(`AddRequest`, `EditRequest` 등)만 넘긴다. 모든 거절 본문에는 안정 코드 `reason`이 붙는다([api.md](api.md) §오류 응답). `HTTPError`를 만드는 곳은 HTTP 경계(`web/`과 기능별 `http.py`) 및 신원·입장·역할 판단([`limn/access.py`](../../src/limn/access.py), R10)뿐이다. 시작 단계의 거절은 `StartupRefused` 값이고 `sys.exit`은 `server.main()` 한 곳에만 있다([`limn/startup.py`](../../src/limn/startup.py)).

> **예시**
>
> 메모 필드의 파서다. 검증된 문자열이나 이유가 붙은 거절을 돌려준다.

```python
def parse_note(v: object) -> str | InputRejected:
    """A pin's note: a string of at most NOTE_MAX characters; absent or null is the empty note."""
    if v is None:
        return ""
    if not isinstance(v, str):
        return InputRejected("note 는 문자열이어야 합니다.", "bad_note")
    if len(v) > NOTE_MAX:
        return InputRejected("메모가 너무 깁니다(%d자 이하)." % NOTE_MAX, "note_too_long")
    return v
```

**확인하는 법.** 오류 응답 본문(`{"error": ..., "reason": ...}`)과 상태 코드는 에이전트 계약이라 바뀌지 않아야 한다. [`tests/test_errors.py`](../../tests/test_errors.py)가 모든 거절에 `reason`이 있는지 보고, [`tests/test_web_parse.py`](../../tests/test_web_parse.py)가 파서마다의 값과 거절, 필드를 보는 순서를 본다. 도메인 함수의 반환 타입에 거절 값이 드러나고, 그 함수 안에 업무상 거절을 위한 `raise`가 없다.

## R4 기계적 규칙은 도구 하나가 집행

**규칙이 말하는 것.** 포매팅·린트처럼 기계가 판단할 수 있는 규칙은 사람이 기억하지 않는다. 도구 하나가 로컬과 CI에서 같은 방식으로 집행한다. 파이썬 생태계의 기본은 Ruff다. 타입 검사는 R8이다.

**업계에서 부르는 이름.** 스타일과 기계적 규칙은 사람 대신 도구가 집행한다는 원칙. *Software Engineering at Google* 8장 "Style Guides and Rules"가 이유를 설명한다.

**지금 코드.** 켠 규칙, 끈 규칙, 제외 경로, 포매터 설정의 정본은 [`pyproject.toml`](../../pyproject.toml)의 `[tool.ruff]`·`[tool.ruff.lint]`다. 코드 모양은 `ruff format`의 기본값이 정한다. Ruff·ShellCheck·mypy는 개발 의존성이라 로컬과 CI가 `uv.lock`의 같은 버전을 쓴다. 명령과 합격 기준은 [verification.md](verification.md) §8에 있다.

끈 규칙과 뺀 경로는 소유자 결정이다. 이유를 함께 적는다.

| 끈 것 | 이유 |
| --- | --- |
| `E501` 줄 길이 | 코드 줄은 포매터가 접는다. 긴 주석·docstring 줄은 검사하지 않는다 |
| `UP030`·`UP031`·`UP032` 문자열 포매팅 바꾸기 | printf 형식과 `str.format` 문자열을 그대로 둔다. 메시지가 에이전트 계약 바이트라서다 |
| `UP042` `class X(str, Enum)` → `StrEnum` | 바꾸면 멤버의 `str()`·`format()` 결과가 달라진다 |
| `server.py`의 `E402` | `limn.*` import가 파일로 실행될 때를 위한 `sys.path` 준비 뒤에 와야 한다([architecture.md](architecture.md) §현재 구조) |
| `tools/handbook-publish/` 제외 | 플러그인에서 복사한 사본이다. 고칠 일이 있으면 원본에서 고친다. 번들한 `src/limn/vendor/`도 뺀다 |
| 테스트 함수·메서드의 docstring 누락 `D102`–`D107` | 테스트 모듈·클래스는 `D100`·`D101`로 검사한다. 기존 함수·메서드의 누락은 많아 `tests/*.py`에서 나머지만 제외하고, 새로 쓰거나 고친 테스트는 R9에 따라 리뷰한다. §다음 |

통째 포매팅처럼 줄만 바꾼 커밋은 [`.git-blame-ignore-revs`](../../.git-blame-ignore-revs)에 적는다. 로컬에서 `git config blame.ignoreRevsFile .git-blame-ignore-revs`를 한 번 하면 `git blame`이 그 커밋을 건너뛴다.

**확인하는 법.** 로컬 명령과 CI 단계가 같은 결과를 낸다. 쓰지 않는 import를 하나 넣었을 때 `uv run ruff check`가 실패한다. 규칙을 한 줄에서만 끄려면 그 줄에 이유를 단다.

## R5 보이지 않는 전역 상태를 명시적 인자로

**규칙이 말하는 것.** 함수가 무엇에 의존하는지는 인자에 드러나야 한다. 오래 사는 자원(설정, 잠금, 스레드)은 그것을 쓰는 런타임의 조립 지점이 만들고 닫는다. import 시점에 만들어진 전역에 소유권을 숨기지 않는다.

**업계에서 부르는 이름.** 명시적 의존성 주입과 composition root (Mark Seemann, *Dependency Injection Principles, Practices, and Patterns*).

**지금 코드.** `server.py`의 `ServerApplication`이 얼린 실행 설정 `C`(`RunConfig`), 실행별 자원 `RT`(`Runtime`), 문서 목록을 함께 갖는다. `start()`가 앱 하나와 그 앱에만 묶인 처리기 하위 클래스를 만들고 `StartedServer`로 소켓과 앱을 함께 돌려준다. import만으로는 앱이나 자원이 생기지 않는다. 같은 모듈에서 다음 실행을 시작해도 앞선 처리기의 앱과 런타임은 바뀌지 않는다. 다른 모듈은 서버를 가져오지 않고, HTTP 처리기가 `app.C`로 읽는 설정 몇 개를 빼면 `C`를 읽지 않는다. 앱은 현재 설정을 기능 서비스에 전달하고, 기능은 `BuildConfig`·`MetaSettings`·`PickContext` 같은 작은 값이나 `PinContext` 같은 협력자로 내부 실행 함수에 넘긴다. 문서는 언제나 인자다. 처리기가 요청의 문서를 찾아 서비스마다 넘기고, 빌드 스레드는 자기 문서로 시작한다.

> **예시**
>
> 빌드 모듈은 문서와 설정을 인자로 받는다. 조립 지점은 이 인스턴스의 설정을 묶는 한 줄만 둔다.

```python
# features/builds/engine.py
def compile_tex(D: BuildDoc, cfg: BuildConfig, pull: Callable[[], Json] | None) -> FinishedBuild:
    """Builds D with -synctex=1 from a copy, leaving the original untouched, then renders pages into a new directory and only swaps the pointer."""


# features/builds/service.py - the service reads current settings at call time
def compile(self, doc: Doc) -> FinishedBuild:
    """Compile one LaTeX document, pulling its repository first when configured."""
    return engine.compile_tex(doc, self.config(), self.pull if self.settings().git_pull else None)
```

뷰어의 현재 문서 방문은 페이지 전체가 공유하는 `DOC`·`SWITCHSEQ`로 확인하고, 초안 저장·빌드 폴링·편집 카드·변경 보기·새 핀 작성의 화면 상태는 각각 `DRAFT`·`BUILD`·`EDITOR`·`REV`·`COMPOSE`가 소유한다([viewer.md](viewer.md) §여러 문서). 문서 방문을 넘는 비동기 응답은 `captureVisit()`·`currentVisit()`으로 그 방문이 여전히 현재인지 확인한다. 작성 패널과 위치 다시 잡기는 PDF 드래그 요청을 한 번에 하나만 받을 수 있어 `PICKSEQ`를 함께 쓴다.

**확인하는 법.** 모듈마다 import·이름 검사가 서버 전역을 읽지 않는지 본다(예: `tests/test_build.py`의 `NoServerState`, `tests/test_locate.py`, `tests/test_service.py`). 두 문서를 동시에 빌드하는 테스트가 결과·이력·빌드 폴더가 섞이지 않음을 본다. 뷰어는 조립된 스크립트와 브라우저에서 문서 A→B→A의 늦은 응답·초안·빌드 기준값을 본다.

## R6 변경 이유가 다른 코드는 다른 모듈로

**규칙이 말하는 것.** 함께, 같은 이유로 바뀌는 코드는 같이 둔다. 서로 다른 이유로 바뀌거나, 판단과 부수효과가 섞이거나, 수명 주기가 다르면 나눈다. 파일이 크다는 사실만으로는 나눌 이유가 되지 않는다. 실제 압력이 있어야 한다.

**업계에서 부르는 이름.** 단일 책임 원칙(Robert C. Martin의 "변경 이유는 하나"). 더 오래된 뿌리는 David Parnas의 논문 "On the Criteria To Be Used in Decomposing Systems into Modules"다.

**지금 코드.** 핀·빌드·동기화·원고 이력·협업·문서 조회·뷰어 셸의 HTTP 경로와 토큰·멤버·이전 명령은 기능 슬라이스가 맡는다. 공통 `web/`은 요청 가드·문서 선택·등록 경로 호출을 맡고, `server.py`는 실행별 협력자를 조립한다. 저장·신원·문서 등 여러 기능이 함께 쓰는 규칙과 아직 옮기지 않은 운영 명령은 기본 모듈에 있다([architecture.md](architecture.md) §현재 구조, §의존 방향). 경로마다의 책임은 [index.md](index.md) §파일 지도가 정본이다. 뷰어는 빌드 단계 없는 정적 파일이고, 스크립트와 스타일은 변경 이유가 다른 조각 파일로 나뉜다. 조각의 순서는 `viewer/parts.txt` 하나가 정하고, 서버는 그 순서대로 이어 붙이기만 한다([viewer.md](viewer.md) §뷰어 규칙을 바꿀 때).

> **예시**
>
> 핀 레코드 모양 검사(`valid_rec`)는 저장 레코드에 필드를 더할 때 전이·편집과 함께 바뀐다. 그래서 저장소 옆이 아니라 순수 모듈 [`limn/pins/record.py`](../../src/limn/pins/record.py)에 있다. 순수하지 않은 모듈의 규칙(문서 키 규칙, 행위자 모양)은 인자로 받고, `server.valid_rec`이 둘을 묶는 한 줄이 되어 저장소에 넘어간다.

**확인하는 법.** 모듈을 나누거나 옮기는 변경은 동작을 바꾸지 않았다는 것을 증명한다. 전체 테스트가 녹색이고, 필요하면 [verification.md](verification.md) §구조 이동의 동작 불변 증명(차등 비교)을 돌린다. 뷰어 조각은 `tests/test_viewer_files.py`가 목록·조각·조립 결과를 맞춰 보고, 내보내는 스크립트마다 `node --check`를 돌린다.

## R7 계약을 말하는 docstring

**규칙이 말하는 것.** 새로 쓰거나 고친 모듈·클래스·함수·메서드에는 private 도우미까지 docstring을 단다. 이름을 되풀이하지 말고, 의도와 계약(전제 조건, 결과, 부수효과, 실패)을 적는다. 손대지 않은 파일에 한꺼번에 달지는 않는다.

**업계에서 부르는 이름.** 계약에 의한 설계(Design by Contract, Bertrand Meyer)의 전제·결과를 글로 적는 것. 파이썬 형식은 PEP 257이 정한다.

**지금 코드.** 프로덕션 파이썬의 공개 모듈·클래스·함수·메서드는 Ruff `D100`–`D107`이 docstring 누락을 검사한다. 테스트 모듈·클래스도 `D100`·`D101`로 검사한다. private 도우미와 테스트 함수·메서드의 누락, 내용이 계약을 설명하는지는 리뷰에서 본다. 주석과 docstring이 설계를 가리킬 때는 Handbook의 절을 `docs/handbook/<topic>.md §<절 제목>` 형태로 적고, [`tests/test_handbook_refs.py`](../../tests/test_handbook_refs.py)가 그 절이 실제로 있는지 본다.

> **예시**
>
> 핀 상태를 정하는 규칙 하나의 계약이다. 무엇을 하는지뿐 아니라 무엇을 읽지 않는지, 누가 기대는지를 말한다.

```python
def state_of(record: Record) -> type[OpenPin] | type[ReviewPin] | type[DonePin]:
    """The state type a stored record is in - the one rule of a pin's state, never stored: not done is open; done
    with review true is awaiting review; any other done (a legacy done:true without review too) is done. Reads only
    done and review, so it is cheap enough for every pin of every read (limn.pins.view.pin_state)."""
```

**확인하는 법.** `uv run ruff check`가 프로덕션 코드의 공개 항목과 테스트 모듈·클래스의 docstring 누락을 잡는다. private 도우미·테스트 함수·메서드의 누락과 docstring 내용은 리뷰에서 구현·테스트와 대조해, 말과 코드가 다르면 둘 중 틀린 쪽을 고친다(§다음).

## R8 정확한 타입 표기

**규칙이 말하는 것.** 공개 경계와 추론이 어려운 곳에 타입을 적는다. 지원하는 가장 오래된 파이썬(3.10)의 문법을 쓴다. 기본값이 `None`이면 타입에 `None`을 넣는다(`Path | None = None`). 경계를 넘는 구조화된 값은 `dataclass`나 `TypedDict`로 모양을 드러낸다.

**업계에서 부르는 이름.** 점진적 타입 지정(gradual typing, PEP 484). `X | None` 표기는 PEP 604다.

**지금 코드.** 타입 검사기는 mypy strict이고, `src/limn/` 아래의 모든 파이썬 파일을 검사한다(`[tool.mypy]`의 `files = ["src/limn"]`). 합 타입에 대한 `match`가 경우 하나를 빠뜨리면 `exhaustive-match`로 실패한다. 설정의 정본은 `pyproject.toml`이고, 고른 이유와 게이트는 [verification.md](verification.md) §9에 있다. `from __future__ import annotations`는 실제로 필요한 곳(자기 타입을 가리키는 표기 등)에만 쓴다.

> **예시**
>
> 처리기는 `ServerApplication`을 `web/app.py`의 `App` 프로토콜로 받는다. `server.py`의 타입 검사 전용 함수가 앱 객체 자체의 멤버와 서명을 확인한다.

```python
if TYPE_CHECKING:

    def _app_contract(app: ServerApplication) -> App:
        return app
```

**확인하는 법.** `uv run mypy`가 0으로 끝난다. `match`의 상태 하나를 일부러 지우면 검사기가 실패하는지 한 번 확인한다(`confirm()`에서 `case DonePin():`을 지우면 `Missing return statement`와 `exhaustive-match` 두 오류).

## R9 동작을 이름과 docstring으로 말하는 테스트

**규칙이 말하는 것.** 테스트는 관찰 가능한 동작을, 위험을 잃지 않는 가장 좁은 수준에서 확인한다. 이름에는 조건과 기대 결과를 담는다(`test_<결과>_when_<조건>`은 예시다). 테스트 모듈·클래스·함수에도 무엇을 지키는지 docstring을 단다. 결함을 고칠 때는 고치기 전에 실패하고 고친 뒤 통과하는 테스트를 먼저 만든다.

**업계에서 부르는 이름.** 실패하는 테스트부터 쓰는 것은 TDD의 red-green(Kent Beck, *Test-Driven Development: By Example*). 조건과 기대를 이름에 담는 방식은 Roy Osherove의 *The Art of Unit Testing*이 정리했다.

**지금 코드.** 순수 판단은 서버 없이 값으로 직접 테스트하고, 처리기 테스트는 소켓 쌍으로 경계를 확인한다. 한 모듈을 지키는 테스트는 그 모듈 이름의 파일(`tests/test_<모듈>.py`)에, 여러 모듈을 건너는 기능은 기능 이름의 파일(`tests/test_reply.py` 등)에 있다. 릴리스·이슈 이름의 테스트 파일은 없다. 테스트 파일의 배치 규칙은 [verification.md](verification.md) §1에 있다.

> **예시**
>
> 모의 객체 없이 값만으로 규칙 하나를 고정한다.

```python
class Confirmer(unittest.TestCase):
    """Who may confirm is decided before any pin is loaded."""

    def test_agent_is_refused(self):
        """An agent gets the refusal value, not an exception."""
        self.assertEqual(confirmer(Agent("local", "agent")), AgentCannotConfirm())
```

**확인하는 법.** 새로 쓰거나 고친 테스트에 docstring이 있다. 새 회귀 테스트는 고치기 전의 실패 출력을 PR에 남긴다. 테스트를 옮기면 옮기기 전후의 테스트 id와 결과가 하나씩 대응한다.

## R10 신뢰 경계는 보안 규칙으로

**규칙이 말하는 것.** 신원, 권한, 외부 입력이 실행되는 곳(셸, 템플릿), 파일 경로, 외부 URL을 건드리는 변경에는 `code-security` 규칙을 함께 적용한다. 거부되어야 할 경우(권한 없음, 경로 탈출, 위조 헤더)를 테스트로 확인한다.

**업계에서 부르는 이름.** OWASP Top 10과 OWASP ASVS(Application Security Verification Standard)가 대표적인 점검 목록이다.

**지금 코드.** 신원·입장·역할·Host/Origin 판단은 [`limn/access.py`](../../src/limn/access.py) 한 모듈에 있다([ADR-0002](../adr/0002-access-control.md)). 이 모듈은 실행 설정 `C`를 읽지 않고 서버를 가져오지 않는다. 설정은 `AccessSettings`, 요청 때 읽는 파일 사실(토큰 목록·역할)은 `AccessLookups`로 받으므로 권한 규칙을 서버 없이 테스트할 수 있다. 이 경계의 거절은 코딩 규칙의 예외로 값이 아니라 `HTTPError`를 던진다(fail closed). 던진 거절은 부르는 쪽이 놓칠 수 없지만, 값으로 돌려준 거절은 새 호출자가 무시하면 요청이 통과하기 때문이다.

> **예시**
>
> `identify()`의 서명은 신원 하나만 돌려주고, 거절은 모두 예외로 끝난다. 잘못되거나 폐기된 토큰은 다른 신원으로 떨어지지 않고 401이다.

```python
def identify(headers: Message, peer: str, settings: AccessSettings, lookups: AccessLookups) -> Principal:
    """Who is this request? A valid `Authorization: Bearer` token wins under every provider; an invalid or revoked
    one is a 401 and never falls back to another identity. Otherwise the provider decides (settings.auth): ...
    Anything else is a 401. A refusal raises HTTPError (401 bad_bearer / bad_token / unauthenticated /
    loopback_agent_off, 403 headerless with the no-identity page)."""
```

**확인하는 법.** 경계를 건드리는 PR은 PR 설명에 "보안 경계 변경"을 적고, 부정 경우 테스트를 함께 올린다. [`tests/test_access_module.py`](../../tests/test_access_module.py)가 모듈 수준에서, [`tests/test_access.py`](../../tests/test_access.py)가 처리기를 거쳐 거부 경우를 확인한다. ADR-0002의 v0.3 이후 단계는 spec을 먼저 승인받고 시작한다.

## 다음

아래는 코드에서 확인한 위험을 낮추는 순서다. 코딩 스킬이 기준이고, 지금 코드의 모양은 예외 사유가 아니다. 각 단계는 동작을 바꾸지 않는 범위에서 작게 나누며, 해당 경계의 거절·저장 바이트·응답을 변경 전후에 비교한다([verification.md](verification.md) §구조 이동의 동작 불변 증명(차등 비교)). 저장 형식이나 보안 경계를 바꾸게 되면 [architecture.md](architecture.md) §멈춤 신호에 따라 설계 판단을 먼저 받는다. 끝낸 단계는 이 절에서 지우고 해당 규칙 절의 **지금 코드**를 고친다.

1. **새 경계를 기계적으로 지킨다(R4, R7–R9).** 프로덕션 파이썬의 Ruff `D100`–`D107`과 테스트 모듈·클래스의 `D100`·`D101`은 누락만 잡는다. 기존 테스트 함수·메서드의 누락을 정리하며 검사 범위를 넓히고, 고친 모듈의 계약 docstring을 코드·테스트와 대조한다. 테스트는 문자열 존재보다 요청·저장·화면에서 관찰한 결과를 우선한다. 정적 검사나 새 라이브러리는 실제 결함을 잡거나 코드를 줄이는 경우에만 더하고 대표 위반을 주입해 게이트가 실패하는지 확인한다. JavaScript 이름 오류 검사도 대표 결함을 실제로 잡는 도구가 개발 의존성으로 들어올 때 채택한다. 런타임 의존성을 더하려면 표준 라이브러리 전용 불변식 때문에 먼저 설계 판단과 ADR이 필요하다([architecture.md](architecture.md) §멈춤 신호). **합격:** 로컬과 CI의 같은 명령이 같은 위반을 잡고, 영향을 받은 기능의 테스트와 타입 검사, 필요하면 전체 차등 비교가 통과한다.

함수 추출은 길이보다 독립적인 규칙과 변화 이유를 기준으로 한다. `compile_tex()`·`revision_compile()`은 입출력을 순서대로 지휘할 수 있다. PDF·SyncTeX의 한 줄짜리 mtime 비교만 각각 감싸면 파일 관찰과 실패 우선순위의 책임은 그대로 남으므로, 그런 추출보다 오래된 산출물을 사용했을 때의 결과를 테스트로 지킨다.
