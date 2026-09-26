# 코딩 규칙 정렬 로드맵

이 topic은 Limn 코드를 우리 팀 코딩 규칙에 맞춰 가는 순서를 설명한다. 규칙 하나하나가 무엇을 말하는지, 지금 코드는 어떤 모습인지, 왜 바꾸면 좋은지, 바꾸면 어떻게 생기는지를 실제 코드로 보여 준다. Limn 코드를 고치는 사람은 작업 전에 해당 규칙 절을 읽는다. 단계를 끝내거나 순서를 바꾸면 이 파일의 §진행 상황을 고친다.

> **한눈에**
>
> - 이 문서를 읽는 법과 용어: §먼저 알아 둘 것
> - 지금 적용하는 것과 조건이 차면 하는 것: §두 층 — 지금 적용과 방향
> - 지금 코드가 이미 잘하고 있는 것: §지금 코드의 강점
> - 규칙의 우선순위: §규칙 우선순위
> - 규칙별 설명과 예시: §R1 ~ §R10
> - 실제로 옮기는 순서: §단계별 로드맵, §진행 상황

## 먼저 알아 둘 것

Limn은 짧은 기간에 기능을 빠르게 쌓으며 자랐다. 실제 논문 작업에서 문제가 보이면 바로 고치고, 고친 이유를 주석과 테스트로 꼼꼼히 남겼다. 그 덕분에 지금 기능은 단단하다. 다만 코드가 한 사람의 머릿속 지도에 기대고 있어서, 다른 사람이나 에이전트가 안전하게 손대기에는 길잡이가 부족하다. 이 로드맵은 그 지도를 코드 구조와 도구로 옮기는 계획이다.

> **핵심**
>
> 규칙이 부딪힐 때의 우선순위는 이렇다.
>
> 1. 제품 불변식 — [architecture.md](architecture.md) §불변식 (127.0.0.1, 표준 라이브러리만, 에이전트 계약, 저장 순서 등)
> 2. 팀 코딩 스킬 — `code-implement`, `code-testing`, `code-security`
> 3. 지금 코드의 관례
>
> 지금 코드가 어떤 방식으로 짜여 있다는 사실만으로는 근거가 되지 않는다. 스킬과 다르면 스킬을 따른다. 다만 이미 있는 코드를 한꺼번에 뜯어고치지 않고, 아래 단계대로 옮긴다.

이 문서에서 자주 쓰는 말을 먼저 정리한다.

| 용어 | 쉬운 뜻 |
| --- | --- |
| 순수 함수 | 같은 입력이면 늘 같은 결과를 내고, 파일·시계·네트워크·전역 변수를 건드리지 않는 함수. 테스트가 가장 쉽다 |
| 부수효과 | 함수 밖 세상을 바꾸거나 읽는 일. 파일 쓰기, `subprocess` 실행, 현재 시각 읽기, HTTP 응답 보내기가 모두 부수효과다 |
| 가장자리 (shell) | 부수효과를 모아 두는 바깥층. 요청을 받고, 필요한 사실을 읽고, 순수 판단을 부르고, 결과를 저장한다 |
| 판단 (decision) | "이 요청을 받아들이는가, 결과 상태는 무엇인가"를 정하는 규칙. 순수 함수로 둔다 |
| 조립 지점 (composition root) | 프로그램이 시작할 때 설정을 읽고 자원(잠금, 스레드, 서버)을 만들어 서로 이어 주는 한 곳 |
| 경계에서 파싱 | 바깥에서 들어온 값(JSON, 파일 줄, 헤더)을 들어오는 곳에서 한 번 검사해 믿을 수 있는 내부 값으로 바꾸는 것. 안쪽 코드는 다시 검사하지 않는다 |

규칙마다 **업계에서 부르는 이름**을 한 줄씩 달았다. Limn이 새로 만든 규칙이 아니라 널리 쓰는 원칙이라는 뜻이고, 더 읽고 싶을 때 검색할 이름이다.

## 두 층 — 지금 적용과 방향

제품의 UX·UI와 기술 스택은 아직 움직이는 중이다. 이럴 때 구조까지 미리 굳히면, 방향이 바뀔 때 옮긴 것을 다시 옮겨야 한다. 그래서 이 로드맵은 두 층으로 나눈다.

| 층 | 무엇 | 언제 |
| --- | --- | --- |
| 지금 적용 | 규칙 우선순위, 새로 쓰거나 고치는 코드에 R1·R3·R5·R7~R10 적용, 1단계 안전망 | 바로. 기존 코드를 찾아다니며 고치지 않는다 |
| 방향 | R2 상태별 타입, R6 모듈 분리, 3~7단계의 목표 구조 | §단계별 로드맵의 **착수 조건**이 찼을 때. 2026-09-26 소유자 결정으로 충족 — 아래 참고 |

지금 적용하는 층은 구조를 고정하지 않는다. 오히려 판단을 가장자리에서 떼어 놓으면(R1), 나중에 화면이나 스택이 바뀌어도 핀 규칙은 그대로 살아남는다. 방향 층은 목표 모양을 미리 적어 두되, 그 영역이 더 움직이지 않을 때 시작한다.

> **핵심**
>
> **2026-09-26 소유자 결정.** 2단계는 새 기능 PR마다 잘 적용되고 있지만, 기존 코드의 부채(전역 상태, 흩어진 `HTTPError`, 1만 줄짜리 한 파일)는 손대는 곳만 고치는 방식으로는 줄지 않았다. 그래서 방향 층도 지금 시작하고, `server.py`를 책임별 모듈로 나누는 일을 가장 먼저 한다.
>
> - **구조 이동이 우선이다.** 구조 이동 PR과 열린 기능 PR이 충돌하면 기능 PR이 새 구조를 따라온다.
> - **대신 기능 결함은 만들지 않는다.** 구조 이동 PR은 동작을 바꾸지 않고, 그 사실을 테스트로 증명한다 (전체 테스트 녹색, 뷰어 HTML 바이트 동일, 계약 스냅숏·레코드 왕복 테스트).
> - **예상된 거절은 반환 타입에 드러낸다.** 아래 R1·R3을 따른다.

> **참고**
>
> 에이전트는 이미 있는 코드의 관례를 그대로 따라 한다. 규칙이 없으면 전역 `C`나 `cur_doc()` 같은 패턴이 새 코드에서도 늘어난다. 지금 적용하는 층은 이 복제를 막는 최소한이다.

## 지금 코드의 강점

바꿀 점을 말하기 전에, 지금 코드가 이미 우리 규칙과 같은 방향으로 잘하고 있는 것을 적는다. 로드맵은 이 강점을 지키면서 진행한다.

- **저장 안전성.** 핀 파일 쓰기는 `transact()` 한 곳을 지나고, 임시 파일 뒤 `os.replace`로 원자적으로 바꾼다. 손상된 줄은 버리지 않고 백업한다. 우리 규칙이 말하는 "효과는 한 소유자가 명시적으로 다룬다"를 이미 지키고 있다.
- **이유를 남기는 주석.** `pin_state()`와 `transact()`의 docstring처럼, 무엇을 하는지보다 왜 그렇게 하는지를 설명하는 글이 많다.
- **회귀 테스트.** 734개의 테스트가 실제로 겪은 결함을 고정한다. 처리기를 소켓 쌍으로 직접 모는 방식은 경계 수준 테스트로 좋은 선택이다.
- **보안 감각.** git 호출에 셸을 쓰지 않고, 비교 PDF 빌드를 bwrap 샌드박스에서 돌리며, 정적 파일은 이름 허용 목록으로만 내준다.
- **호환성 규율.** 옛 레코드를 쓰기 마이그레이션 없이 읽고, 에이전트 계약에는 필드를 더하기만 한다.

## 규칙 우선순위

우리 스킬의 규칙을 Limn에서 중요한 순서로 정렬했다. 순서의 기준은 "틀렸을 때 피해가 큰가, 그리고 다른 규칙을 적용하기 위한 발판이 되는가"다.

| 순위 | 규칙 | 스킬 출처 | 이 순위인 이유 |
| --- | --- | --- | --- |
| 1 | R1 판단은 순수 함수, 부수효과는 가장자리 | code-implement | 핀 수명 주기가 Limn의 핵심 가치다. 규칙을 파일과 떼어 놓아야 빠르고 확실하게 테스트할 수 있다 |
| 2 | R2 잘못된 상태를 표현하기 어렵게 | code-implement / modeling | 핀 상태가 독립 필드의 조합이라 모순된 조합이 생길 수 있다 |
| 3 | R3 경계에서 파싱하고, 안쪽은 HTTP를 모른다 | code-implement / modeling | 검증과 오류 표현이 흩어져 있으면 R1·R2를 적용할 수 없다 |
| 4 | R4 기계적 규칙은 도구 하나가 집행 | code-implement / format | 가장 싸고, 이후의 모든 이동을 지켜 주는 안전망이다 |
| 5 | R5 보이지 않는 전역 상태를 명시적 인자로 | code-implement / structure, python-backend | 함수 결과가 숨은 값에 달려 있으면 나누기도 테스트하기도 어렵다 |
| 6 | R6 변경 이유가 다른 코드는 다른 모듈로 | code-implement / structure | 9,892행 한 파일은 R1~R5의 결과를 담을 자리가 없다 |
| 7 | R7 계약을 말하는 docstring | code-implement | 머릿속 지도를 코드로 옮기는 가장 직접적인 방법이다 |
| 8 | R8 정확한 타입 표기 | code-implement / python | 경계 값의 모양을 도구가 확인하게 한다 |
| 9 | R9 동작을 이름과 docstring으로 말하는 테스트 | code-testing | 테스트가 무엇을 지키는지 읽혀야 안전하게 옮길 수 있다 |
| 10 | R10 신뢰 경계는 보안 규칙으로 | code-security | 이미 잘 지키고 있어 순위는 낮지만, 경계를 건드리는 변경에는 늘 적용한다 |

도구 도입(R4)은 순위는 4위지만 **가장 먼저** 한다. 비용이 가장 작고, 뒤 단계의 이동이 안전한지 알려 주기 때문이다. 순위는 중요도이고, 실행 순서는 §단계별 로드맵이 정한다.

## R1 판단은 순수 함수, 부수효과는 가장자리

**규칙이 말하는 것.** "이 요청을 받아들일지, 결과 상태가 무엇인지"는 순수 함수로 정한다. 현재 시각, 행위자, 이미 읽어 온 사실을 인자로 받는다. 파일을 읽고 쓰고, 잠금을 잡고, HTTP 상태 코드를 고르는 일은 바깥 처리기가 한다.

**업계에서 부르는 이름.** Functional Core, Imperative Shell (Gary Bernhardt, "Boundaries" 발표, 2012). Mark Seemann은 같은 모양을 "impureim sandwich"라고 부른다.

**옮기기 전 모습.** 검토 대기 핀을 확인하던 `confirm_pin()`을 보자.

```python
def confirm_pin(pid: int, actor: dict):
    if is_agent(actor):
        raise HTTPError(403, "확인은 사람이 합니다 — ...")

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return None, False
        st = pin_state(r)
        if st == "open":
            raise HTTPError(409, "open", pin=public(r), detail="...")
        if st == "done":
            return public(r), False
        r.pop("review", None)
        r["confirmed_by"] = who(actor)
        r["confirmed_at"] = now_str()
        _thread_append(r, actor, "", ev="confirm")
        r["rev"] = int(r.get("rev") or 0) + 1
        return public(r), True
    return transact(fn)[1]
```

한 함수 안에 네 종류의 일이 섞여 있었다.

1. 규칙: 에이전트는 확인할 수 없다. 열린 핀은 확인할 것이 없다. 이미 완료면 그대로 돌려준다.
2. 시계 읽기: `now_str()`.
3. HTTP 표현: `403`, `409`와 한국어 메시지.
4. 저장: `transact()` 안에서 사전을 직접 고친다.

그래서 "에이전트는 확인할 수 없다"라는 규칙 하나를 테스트하려 해도 임시 상태 디렉터리와 파일 저장소를 거쳐야 했다. 규칙이 늘수록 테스트가 느려지고, 규칙이 어디 있는지 찾기도 어려워진다.

**바꾼 모습.** 2026-09-26 확인 전이를 처음으로 옮겼다. 규칙은 [`limn/pins/lifecycle.py`](../../src/limn/pins/lifecycle.py)의 순수 함수, 불러오기·저장은 `server.py`의 `confirm_pin()`, 응답은 HTTP 처리기가 맡는다. 동작과 응답은 그대로다.

```python
# limn/pins/lifecycle.py — 파일·시계·HTTP를 모른다. 서명만 보고 결과를 안다
def confirmer(actor: Actor) -> Person | AgentCannotConfirm:
    """The person who may confirm, or the refusal for an agent - decided before any pin is loaded."""

def confirm(pin: Pin, by: Person, at: str) -> DonePin | AlreadyDone | PinStillOpen:
    match pin:
        case ReviewPin():
            return confirm_review(pin, by, at)      # ReviewPin만 받는 전이: 다른 상태로는 부를 수 없다
        case DonePin():
            return AlreadyDone(pin)                 # 거절이 아니라 "바뀐 것 없음"이라는 결과
        case OpenPin():
            return PinStillOpen(pin)                # 409 본문에 쓸 핀을 함께 돌려준다
```

```python
# server.py — 가장자리: 에이전트면 저장소를 건드리기 전에 끝내고, 불러오고, 판단을 부르고, 새 DonePin만 쓴다
def confirm_pin(pid, actor) -> DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound:
    by = confirmer(typed_actor(actor))
    if isinstance(by, AgentCannotConfirm):
        return by
    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return PinNotFound(pid), False
        result = confirm(parse_pin(r), by, now_str())
        if isinstance(result, DonePin):             # 처리할 타입 하나만 보고, 나머지는 그대로 넘긴다
            r.clear()
            r.update(result.record)
            return result, True
        return result, False
    return transact(fn)[1]

# HTTP 처리기 — 모든 결과에 응답 하나. 상태 코드와 본문은 에이전트 계약 그대로
match result:
    case DonePin(record=record) | AlreadyDone(pin=DonePin(record=record)):
        return self._json({"ok": True, "pin": public(record), "state": "done"})
    case PinNotFound():
        return self._json({"ok": False, "pin": None, "state": None})
    case AgentCannotConfirm():
        raise HTTPError(403, CONFIRM_BY_HUMAN)
    case PinStillOpen(pin=OpenPin(record=record)):
        raise HTTPError(409, "open", pin=public(record), detail=CONFIRM_OPEN_DETAIL)
```

이제 규칙 테스트는 파일 없이 `confirmer(Agent(...)) == AgentCannotConfirm()` 한 줄로 끝난다 (`tests/test_pins_lifecycle.py`). 처리기 테스트는 상태 코드와 저장만 확인한다.

**거절을 값으로 돌려주는 이유.** `raise`를 쓰면 서명은 `-> Pin`이라서, 호출하는 쪽은 docstring을 읽어야 거절이 있다는 걸 안다. 잊고 `try`를 빠뜨리면 거절이 처리기 밖까지 새어 500이 된다. 반환 타입에 결과가 모두 드러나면 타입 검사기와 `match`가 처리하지 않은 경우를 드러낸다. 예외는 결함(호출자가 전제를 어김)과 인프라 장애(파일·시간 초과)에만 쓴다. 일반 Result 라이브러리는 들이지 않는다.

**결과 타입을 고르는 법.** 팀 스킬 `code-implement`의 규칙을 따른다.

- 경우마다 데이터나 응답이 다르면 경우별 타입으로 나눈다(`PinStillOpen(pin)`과 `AgentCannotConfirm()`). 데이터와 응답이 모두 같을 때만 `Literal` 이유 하나로 묶는다. 앱 전체 공용 오류 타입은 만들지 않는다.
- 한 동작의 거절이 여럿이면 이름을 한 번 붙인다(`XRefusal: TypeAlias = A | B`). 서명은 `성공 | 그 이름`으로 읽힌다.
- 처리기는 처리할 타입 하나만 보고 나머지는 그대로 돌려준다. 파이썬 `match`는 합 타입 이름을 패턴으로 쓸 수 없으니 구성원을 다시 나열하지 않는다.
- 식별자로 불러온 결과가 없으면 이름 있는 타입(`PinNotFound`)으로 돌려주고, 그 값이 가장자리까지 그대로 간다. 계산의 빈 결과만 `X | None`이다.
- 상태와 이벤트를 한 값에 묶지 않는다. 사실을 기록해야 하는 전이는 `decide → 이벤트 | 거절`, `evolve(상태, 이벤트) → 새 상태`로 나눈다.

**확인하는 법.** 옮기기 전에 기존 처리기 테스트가 녹색인지 확인하고, 옮긴 뒤 같은 테스트가 그대로 녹색이어야 한다. 새 순수 함수에는 허용 전이와 거부 조합마다 직접 테스트를 둔다.

> **주의**
>
> 모든 함수를 순수로 만들 필요는 없다. 계산·파싱·렌더링은 평범한 함수로 충분하다. 명령(Command)·이벤트 같은 이름 붙은 값은 감사·재시도·여러 입구처럼 실제 필요가 있을 때만 쓴다. 패턴을 채우려고 클래스를 만들지 않는다.

## R2 잘못된 상태를 표현하기 어렵게

**규칙이 말하는 것.** 상태마다 필요한 데이터와 허용되는 동작이 다르면 상태별 타입을 둔다. 그러면 "있을 수 없는 조합"을 애초에 만들 수 없다.

**업계에서 부르는 이름.** Make illegal states unrepresentable (Yaron Minsky, "Effective ML", 2010). Scott Wlaschin의 책 *Domain Modeling Made Functional*(2018)이 같은 방법을 자세히 다룬다.

**언제 시작하나.** 방향 층이다. 2026-09-26 소유자 결정으로 4단계와 함께 시작한다 (§두 층).

**지금 코드의 모습.** 핀 상태는 저장된 필드의 조합에서 계산한다.

```python
def pin_state(r: dict) -> str:
    if not r.get("done"):
        return "open"
    return "review" if r.get("review") is True else "done"
```

`done`, `review`, `confirmed_by`, `close_reply`, `claim_until` 같은 필드는 서로 독립적이다. 예를 들어 `done`이 거짓인데 `review`가 참이거나, 열린 핀에 `confirmed_by`가 남는 조합도 사전에는 담길 수 있다. 지금은 이런 조합을 만드는 코드 경로가 없도록 사람이 조심해서 막고 있다. 핀 코드를 처음 보는 사람은 이 약속을 모른다.

**바꾼 모습.** 상태를 필드로 들고 다니는 한 타입이 아니라, **상태마다 타입을 두고 핀을 그 합으로** 둔다 (2026-09-26, [`limn/pins/model.py`](../../src/limn/pins/model.py)). **저장 형식(`pins.jsonl`)과 API 모양은 바꾸지 않는다** ([architecture.md](architecture.md) §불변식 3, 6). 각 상태 타입은 저장된 레코드를 그대로 들고 다녀서, 이 버전이 모르는 필드도 왕복에서 살아남는다.

```python
@dataclass(frozen=True)
class OpenPin:
    """A pin nobody has closed: its stored done is false or missing."""
    record: Record

@dataclass(frozen=True)
class ReviewPin:
    """Closed by an agent and waiting for a person to confirm it: done and review are both true."""
    record: Record

@dataclass(frozen=True)
class DonePin:
    """Closed for good. A legacy done record with no review field is done too."""
    record: Record

Pin: TypeAlias = OpenPin | ReviewPin | DonePin

def parse_pin(record: Record) -> Pin: ...        # pin_state()와 같은 규칙
```

한 상태에만 쓰는 전이는 그 상태 타입만 받는다(`confirm_review(pin: ReviewPin, ...)`). 요청처럼 어떤 상태든 올 수 있는 입구는 `match pin:`으로 타입을 나눈다. 상태 문자열을 비교하지 않는다.

**다음 단계.** 전이를 하나씩 옮길 때, 그 상태에만 있는 필드(검토 대기의 닫은 기록, 완료의 `confirmed_by`, 열림의 claim)를 레코드에서 꺼내 해당 상태 타입의 속성으로 올린다. 그래야 "열린 핀에 `confirmed_by`가 남는" 조합이 타입으로 막힌다. 지금은 상태만 타입이고 필드는 레코드 안에 있다.

**확인하는 법.** 옛 레코드 모양(검토 필드 없는 완료, `doc` 없는 레코드 등)을 읽어서 다시 쓰면 바이트 단위로 같아야 한다. 이 왕복 테스트를 먼저 만들고 옮긴다.

> **참고**
>
> 상태가 이름표일 뿐 데이터와 동작이 같다면 문자열이나 `Enum`으로 충분하다. 빌드 상태(`idle`·`running`·`ok`·`ok_errors`·`fail`)가 그런 예다. 핀 수명 주기처럼 상태마다 데이터가 다를 때만 타입을 나눈다.

## R3 경계에서 파싱하고, 안쪽은 HTTP를 모른다

**규칙이 말하는 것.** 요청 JSON, 파일 줄, 헤더처럼 바깥에서 온 값은 들어오는 곳에서 한 번 검사해 내부 값으로 바꾼다. 안쪽 판단은 HTTP 상태 코드를 모른다. 예상된 거부는 **반환값**으로 표현하고(R1 §거절을 값으로 돌려주는 이유), HTTP 층이 상태 코드와 메시지로 바꾼다. 경계 파서도 같다 — 검증된 값이거나 거절 값을 돌려준다. 예외는 결함과 인프라 오류에만 쓴다.

**업계에서 부르는 이름.** Parse, don't validate (Alexis King, 2019 블로그 글).

**지금 코드의 모습.** `HTTPError`를 던지는 함수가 48개다. `clean_note()` 같은 입력 검사 함수뿐 아니라 `confirm_pin()`, `reply_pin()`, `edit_pin()` 같은 핀 조작 함수도 직접 `HTTPError(409, ...)`를 던진다.

```python
def clean_note(v) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise HTTPError(400, "note 는 문자열이어야 합니다.")
    if len(v) > NOTE_MAX:
        raise HTTPError(400, "메모가 너무 깁니다(%d자 이하)." % NOTE_MAX)
    return v
```

또 `detect_main()`, `free_port()`, `clean_label()`은 문제가 있으면 `sys.exit()`로 프로세스를 끝낸다. 시작할 때만 불린다는 전제가 코드에 드러나지 않는다.

이렇게 되면 같은 규칙을 HTTP가 아닌 입구(예: 앞으로의 CLI 명령이나 백그라운드 작업)에서 쓰기 어렵다. 한국어 오류 문구도 48곳에 흩어진다.

**바꾼 모습.** 요청 파싱은 `http/` 층이 맡는다. `parse_note(v) -> NoteText | InputRejected`처럼 검증된 값이나 이유가 붙은 거절 값을 돌려준다. 도메인은 `ConfirmRejected("open")`처럼 이유를 담은 값을 **돌려준다**. HTTP 층은 `match`로 받아 이유별 상태 코드와 한국어 문구를 **한 표**에서 고른다. `sys.exit()`는 `main()` 한 곳에서만 부르고, 안쪽 함수는 시작 실패 이유를 값으로 돌려준다.

0.3의 핀 단위 변경 코드는 이미 거절을 이유(`ScopeRejected(reason)`)와 표 하나(`SCOPE_REJECTIONS`)로 모았다. 다만 예외로 던지므로, 모듈로 옮길 때 반환값으로 바꾼다. 이유마다 데이터나 응답이 다르면 그때 경우별 타입으로 나눈다 (R1 §결과 타입을 고르는 법).

**확인하는 법.** 오류 응답 본문(`{"error": ...}`)과 상태 코드가 옮기기 전후에 같아야 한다. API 오류 문자열은 에이전트 계약의 일부다. 도메인 함수의 반환 타입에 거절 값이 드러나고, 그 함수 안에 업무상 거절을 위한 `raise`가 남지 않는다.

## R4 기계적 규칙은 도구 하나가 집행

**규칙이 말하는 것.** 포매팅·린트처럼 기계가 판단할 수 있는 규칙은 사람이 기억하지 않는다. 도구 하나가 로컬과 CI에서 같은 방식으로 집행한다. 파이썬 생태계의 기본은 Ruff다. 타입 검사는 따로 정한다.

**업계에서 부르는 이름.** 스타일과 기계적 규칙은 사람 대신 도구가 집행한다는 원칙. *Software Engineering at Google*(2020) 8장 "Style Guides and Rules"가 이유를 설명한다.

**1단계 전 모습.** 포매터·린터·타입 검사기 설정이 없었고, CI는 테스트만 돌렸다. `instances.sh`에는 shellcheck 억제 주석이 있었지만 CI가 shellcheck를 돌리지 않았다. 쓰지 않는 import나 가려진 변수 같은 실수는 사람이 찾아야 했다.

2026-09-25에 설정 없이 Ruff 0.16을 돌려 본 결과는 이렇다.

| 규칙 묶음 | 건수 | 성격 |
| --- | --- | --- |
| 전부 켬 (`E`·`F`·`W`·`I`·`B`·`UP`·`SIM`·`D`) | 3,808 | 대부분 줄 길이(1,769)와 docstring 누락. 한 번에 녹색으로 만들 수 없다 |
| 버그 후보만 (`F`·`E4`·`E7`·`E9`·`B`·`PLW1510`) | 84 | 한 PR에서 처리할 수 있다 |

버그 후보 묶음이 잡은 것 중 하나는 실제 결함이었다. 빌드 직전에 원고를 사본 폴더로 옮기는 `rsync` 호출이 종료 코드를 보지 않았다. 권한 오류나 디스크 부족으로 복사가 일부만 되어도 빌드는 낡은 사본을 컴파일했다. `subprocess.run`에 `check`를 적게 하는 규칙(`PLW1510`)이 이 호출을 드러냈고, 실패 테스트(`tests/test_build_copy.py`)와 함께 따로 고쳤다.

**지금 모습 (1단계 완료).** 버그 후보 규칙만 켰다. 스타일 규칙은 전체 포매팅 커밋과 함께 넓힌다.

```toml
# pyproject.toml
[tool.ruff]
target-version = "py310"
line-length = 120
extend-exclude = ["src/limn/vendor", "tools/handbook-publish"]

[tool.ruff.lint]
select = ["F", "E4", "E7", "E9", "B", "PLW1510"]
```

- Ruff와 ShellCheck(`shellcheck-py`)는 개발 의존성이다. [architecture.md](architecture.md) §불변식 2와 부딪히지 않고, 로컬과 CI가 `uv.lock`의 같은 버전을 쓴다. CI `lint` 작업이 `uv run ruff check`와 `uv run shellcheck ...`를 돌린다 ([verification.md](verification.md) §8).
- 84건은 동작을 바꾸지 않고 정리했다. 종료 코드를 따로 확인하던 `subprocess.run`에는 `check=False`를 명시했다. `except` 안에서 HTTP 오류로 바꿔 던지는 곳에는 `from None`을, 원인을 메시지에 담는 곳에는 `from e`를 붙였다. 길이가 같아야 하는 `zip`에는 `strict=True`를 붙였다.
- ShellCheck의 info 4건은 의도한 코드라 이유를 적은 주석과 함께 껐다.
- `tools/handbook-publish/`는 플러그인에서 복사한 사본이라 검사에서 뺀다. 고칠 일이 있으면 원본에서 고친다.

**다음.**

- `ruff format --check`와 스타일 규칙은 기존 코드 전체를 다시 포매팅하는 커밋과 함께 켠다. 이 커밋은 **동작 변경과 섞지 않고 따로** 만들고, `git blame`이 흐려지지 않도록 `.git-blame-ignore-revs`에 적는다. 열린 PR이 모두 머지된 때를 골라야 다른 작업과 충돌하지 않는다.
- docstring 규칙(`D`)은 처음에 새 모듈에만 켜고, 옮겨지는 모듈마다 넓힌다.

**확인하는 법.** 로컬 명령과 CI 단계가 같은 결과를 낸다. 일부러 쓰지 않는 import를 하나 넣었을 때 `uv run ruff check`가 실패하는지 확인한다.

## R5 보이지 않는 전역 상태를 명시적 인자로

**규칙이 말하는 것.** 함수가 무엇에 의존하는지는 인자에 드러나야 한다. 오래 사는 자원(설정, 잠금, 스레드)은 그것을 쓰는 런타임의 조립 지점이 만들고 닫는다. import 시점에 만들어진 전역에 소유권을 숨기지 않는다.

**업계에서 부르는 이름.** 명시적 의존성 주입과 composition root (Mark Seemann, *Dependency Injection Principles, Practices, and Patterns*, 2019).

**지금 코드의 모습.**

```python
C = Cfg()                      # 실행 인자 — 코드 안 217곳에서 C.xxx 로 읽는다

_TL = threading.local()
def cur_doc() -> Doc: ...      # "지금 요청의 문서" — 45곳에서 인자 없이 부른다

BUILD_STATE = {"state": "idle", ...}   # 모듈 전역 상태 사전과 잠금들
```

이 방식은 기능을 빨리 붙이기에 편했다. 여러 문서 지원을 더할 때 수십 개의 빌드 함수에 인자를 추가하지 않아도 됐다. 대신 함수의 결과가 호출자가 보지 못하는 값에 달려 있다. 테스트는 `C`를 통째로 바꿔 끼워야 하고, 스레드를 새로 띄우는 코드는 `using_doc()`를 잊지 않아야 한다. 빌드 스레드가 "현재 문서"를 잃으면 엉뚱한 문서의 빌드 폴더를 건드릴 수 있다.

**바꾼 모습.** 문서와 설정을 인자로 받는다. `server.py`의 `main()`이 조립 지점이 되어 설정을 파싱하고, 문서 목록과 잠금을 만들고, 처리기에 넘긴다.

```python
def build(doc: Doc, cfg: BuildConfig, runner: Runner) -> BuildResult:
    """Build one document's PDF in its own build folder; never touches another document."""
```

**확인하는 법.** 옮긴 함수에 `C.`나 `cur_doc()` 참조가 남지 않는다 (`grep`으로 확인). 여러 문서를 동시에 빌드하는 기존 테스트가 그대로 녹색이다.

> **주의**
>
> 217곳을 한 번에 바꾸지 않는다. 지금 적용하는 층에서는 새 함수가 전역 참조를 새로 늘리지 않는 것까지만 한다. 모듈을 하나 꺼낼 때마다 그 모듈 안의 전역 참조만 걷어 낸다 (§단계별 로드맵 5단계).

## R6 변경 이유가 다른 코드는 다른 모듈로

**규칙이 말하는 것.** 함께, 같은 이유로 바뀌는 코드는 같이 둔다. 서로 다른 이유로 바뀌거나, 판단과 부수효과가 섞이거나, 수명 주기가 다르면 나눈다. 파일이 크다는 사실만으로는 나눌 이유가 되지 않는다. 실제 압력이 있어야 한다.

**업계에서 부르는 이름.** 단일 책임 원칙(Robert C. Martin의 "변경 이유는 하나"). 더 오래된 뿌리는 David Parnas의 논문 "On the Criteria To Be Used in Decomposing Systems into Modules"(1972)다.

**언제 시작하나.** 방향 층이다. 2026-09-26 소유자 결정으로 지금 시작한다. 뷰어는 **빌드 단계 없는 정적 파일**로 꺼낸다 — [architecture.md](architecture.md) §불변식 2를 그대로 지키고, 나중에 빌드 도구를 들이더라도 이 분리가 첫 단계가 된다.

**3단계 전 모습.** `server.py` 한 파일이 1만 행을 넘었고, 그중 약 3,600행은 파이썬 문자열 `HTML` 안에 든 뷰어 HTML·CSS·JS였다. Limn에는 실제로 이런 압력이 보였다.

- 뷰어와 서버는 서로 다른 이유로 바뀐다. 화면 QA 수정은 서버 규칙과 무관하다.
- JS가 파이썬 문자열 안에 있어서 편집기의 JS 도구(문법 강조, 린트)를 쓸 수 없다.
- 테스트는 JS 함수를 문자열에서 중괄호를 세어 잘라 낸다 (`extract_js_fn`). 그 docstring은 "문자열 리터럴에 중괄호가 없는 함수에서만 안전하다"고 스스로 경고한다.
- 핀 규칙, 역변환 계산, 빌드 실행, HTTP 라우팅이 한 이름공간을 공유해서 의존 방향을 도구로 확인할 수 없다.

**바꾼 모습.** [architecture.md](architecture.md) §목표 구조를 따른다. 첫 단계로 뷰어를 패키지 데이터 파일(`viewer/index.html`, `app.css`, `app.js`)로 꺼냈다 (3단계 완료, 2026-09-26). 빌드 단계도 CDN도 없이 서버가 시작할 때 CSS·JS를 `index.html`에 끼워 한 장의 HTML로 내주므로 [architecture.md](architecture.md) §불변식 2를 지킨다. 서버가 채우던 자리 표시자(`__ACCENT__`, `{{ic:이름}}` 등)는 그대로 쓴다. 이제 JS와 CSS를 편집기 도구로 다룰 수 있다. 다음은 `server.py` 안의 책임별 구역을 모듈로 옮기는 일이다 (§단계별 로드맵의 실행 순서).

**확인하는 법.** 서버가 내보내는 HTML이 옮기기 전과 바이트 단위로 같다. 설치 스모크([verification.md](verification.md) §3)가 새 데이터 파일이 패키지에 들어갔는지 확인한다.

## R7 계약을 말하는 docstring

**규칙이 말하는 것.** 새로 쓰거나 고친 모듈·클래스·함수·메서드에는 private 도우미까지 docstring을 단다. 이름을 되풀이하지 말고, 의도와 계약(전제 조건, 결과, 부수효과, 실패)을 적는다. 손대지 않은 파일에 한꺼번에 달지는 않는다.

**업계에서 부르는 이름.** 계약에 의한 설계(Design by Contract, Bertrand Meyer)의 전제·결과를 글로 적는 것. 파이썬 형식은 PEP 257이 정한다.

**지금 코드의 모습.** `server.py` 함수 353개 중 136개, `migrate.py` 10개 중 9개, `cli.py` 11개 중 7개에 docstring이 없다. 있는 것 중에는 `pin_state()`처럼 이유까지 설명하는 훌륭한 글이 많다. 반대로 없는 곳에서는 중요한 계약이 숨는다.

```python
def now_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
```

이 함수는 **시간대 정보를 떼어 낸** 현지 시각 문자열을 돌려준다. 핀의 `at` 필드가 이 값이다. 시간대가 없는 `at`을 브라우저가 현지 시각으로 해석해서 위치 추정 표시가 틀린 적이 있다 ([build-sync.md](build-sync.md) §위치 추정). 계약이 docstring에 있었다면 그 함정이 바로 보였을 것이다.

```python
def now_str() -> str:
    """Local wall-clock time as 'YYYY-MM-DD HH:MM:SS' with the UTC offset dropped.

    Stored in pin records (at, edited_at, ...). The string carries no time zone, so never
    compare it across machines or parse it in the browser; use epoch seconds for that.
    """
```

또 주석 19곳이 `§P0c-C`, `§P0b-보완 C` 같은 옛 작업 계획 번호를 가리킨다. 그 계획 문서는 이 저장소에 없다. 이런 참조는 Handbook의 절 이름으로 바꾼다 (예: `docs/handbook/api.md §처리 중 표시`).

**확인하는 법.** Ruff의 `D` 규칙이 누락을 잡는다 (R4). 리뷰에서 docstring을 구현·테스트와 대조해, 말과 코드가 다르면 둘 중 틀린 쪽을 고친다.

## R8 정확한 타입 표기

**규칙이 말하는 것.** 공개 경계와 추론이 어려운 곳에 타입을 적는다. 지원하는 가장 오래된 파이썬(3.10)의 문법을 쓴다. `from __future__ import annotations`는 실제로 필요할 때만 쓴다.

**업계에서 부르는 이름.** 점진적 타입 지정(gradual typing, PEP 484). `X | None` 표기는 PEP 604다.

**지금 코드의 모습.**

- `pdfjs_dir: Path = None`처럼 기본값이 `None`인데 타입에 `None`이 빠진 곳이 35곳이다.
- 반환 타입이 그냥 `dict`인 함수가 53개다. 어떤 키가 들어 있는지는 본문을 읽어야 안다.
- 모든 파일이 `from __future__ import annotations`로 시작하지만, 이것이 필요한 순환 참조는 없다.

**바꾼 모습.** `Path | None = None`처럼 적는다. 경계를 넘는 구조화된 값(빌드 결과, 메타 응답 등)은 `TypedDict`나 `dataclass`로 모양을 드러낸다. 타입 검사기(pyright 또는 mypy)는 새 모듈부터 켜고 옮기는 대로 넓힌다.

**확인하는 법.** 타입 검사기가 새 모듈에서 오류 0으로 끝난다. 일부러 `match`의 상태 하나를 빼 보았을 때 검사기가 알려 주는지 한 번 확인한다.

## R9 동작을 이름과 docstring으로 말하는 테스트

**규칙이 말하는 것.** 테스트는 관찰 가능한 동작을, 위험을 잃지 않는 가장 좁은 수준에서 확인한다. 이름에는 조건과 기대 결과를 담는다 (`test_<결과>_when_<조건>`은 예시다). 테스트 모듈·클래스·함수에도 무엇을 지키는지 docstring을 단다. 결함을 고칠 때는 고치기 전에 실패하고 고친 뒤 통과하는 테스트를 먼저 만든다.

**업계에서 부르는 이름.** 실패하는 테스트부터 쓰는 것은 TDD의 red-green(Kent Beck, *Test-Driven Development: By Example*, 2002). 조건과 기대를 이름에 담는 방식은 Roy Osherove의 *The Art of Unit Testing*이 정리했다.

**지금 코드의 모습.** 테스트 함수 733개 중 docstring이 있는 것은 4개다. 대부분은 클래스 이름(`Claim`, `Estimate`)과 주석이 맥락을 주지만, 개별 테스트가 어떤 사고를 막는지는 본문을 읽어야 안다. `test_server.py` 한 파일이 6,663행이라, 서버를 나눌 때 어느 테스트가 어느 모듈을 지키는지 가려내기 어렵다.

**바꾼 모습.**

- R1에서 꺼낸 순수 판단은 서버 없이 직접 테스트한다. 모의 객체(mock)는 거의 필요 없다.
- 처리기 테스트는 지금처럼 소켓 쌍으로 경계를 확인한다. 이 방식은 유지한다.
- 모듈을 꺼낼 때 그 모듈을 지키는 테스트도 같은 이름의 파일로 옮긴다 (예: `tests/test_pins_lifecycle.py`).
- 새로 쓰거나 고치는 테스트에는 docstring을 단다.

**확인하는 법.** 옮긴 테스트 수와 결과가 옮기기 전과 같다. 새 회귀 테스트는 고치기 전 실패 출력을 PR에 남긴다.

## R10 신뢰 경계는 보안 규칙으로

**규칙이 말하는 것.** 신원, 권한, 외부 입력이 실행되는 곳(셸, SQL, 템플릿), 파일 경로, 외부 URL을 건드리는 변경에는 `code-security` 규칙을 함께 적용한다. 거부되어야 할 경우(권한 없음, 경로 탈출, 위조 헤더)를 테스트로 확인한다.

**업계에서 부르는 이름.** OWASP Top 10과 OWASP ASVS(Application Security Verification Standard)가 대표적인 점검 목록이다.

**지금 코드의 모습.** Limn은 이미 이 부분을 조심스럽게 다룬다. 요청 본문을 끝까지 읽어 요청 밀수(smuggling)를 막고, Host·Origin을 검사하고, 신원 헤더 없는 테일넷 요청을 거절한다. 0.2.0부터는 신원 방식·토큰·역할이 더해져 신뢰 경계가 넓어졌다. 토큰은 해시로만 저장하고, 역할은 처리기 한 곳에서 집행하며, `tests/test_access.py`가 거부 경우를 확인한다 ([ADR-0002](../adr/0002-access-control.md)).

**바꾼 모습.** 새로 바꿀 것은 없다. 경계를 건드리는 PR은 PR 설명에 "보안 경계 변경"을 적고, 부정 경우 테스트를 함께 올린다. ADR-0002의 v0.3 이후 단계는 spec을 먼저 승인받고 시작한다. R1을 적용할 때 역할 판단("이 역할이 이 동작을 해도 되는가")도 순수 판단으로 꺼내면 권한 규칙을 파일 없이 테스트할 수 있다.

## 단계별 로드맵

각 단계는 독립적으로 머지할 수 있고, 단계마다 동작은 바뀌지 않는다. 앞 단계가 끝나야 뒤 단계를 안전하게 할 수 있다.

**착수 조건**은 앞 단계가 끝났다는 것에 더해, 그 단계가 굳히는 영역이 더 움직이지 않는다는 신호다. 1·2단계는 구조를 고정하지 않으므로 조건 없이 0단계와 나란히 한다 ([ADR-0001](../adr/0001-blueprint.md) §결과). 3~6단계의 조건은 2026-09-26 소유자 결정으로 충족됐다 (§두 층).

실행 순서는 표의 번호와 조금 다르다. `server.py`를 빨리 가볍게 하려고 기계적으로 옮길 수 있는 것부터 한다: 3단계(뷰어) → 5단계 앞부분(`mapping.py`, 거의 순수) → 4단계(`store`·핀 모델·전이) → 5단계 나머지(`build/`) → 6단계(`http/`, 조립 지점). 포매팅 커밋은 옮기기가 끝난 뒤에 한 번에 한다.

| 단계 | 목표 | 착수 조건 | 하는 일 | 끝났다는 증거 | 하지 않는 일 |
| --- | --- | --- | --- | --- | --- |
| 0 | 합의 | 없음 | 이 문서와 [ADR-0001](../adr/0001-blueprint.md)을 검토하고 확정한다. 3~6단계 착수 조건을 정한다 | ADR-0001 상태가 `확정`. 착수 조건 충족 | 코드 변경 |
| 1 | 안전망 | 없음. 0단계와 나란히 | Ruff 버그 후보 규칙과 shellcheck를 CI에 더한다 (R4). 스타일 규칙과 전체 포매팅은 별도 커밋으로 뒤에 한다 | CI에 새 단계가 녹색. [verification.md](verification.md) §6 표 갱신 | 동작 변경, docstring 일괄 추가 |
| 2 | 새 코드부터 규칙 | 없음. 0단계와 나란히 | 이후 모든 PR은 손대는 함수에 R7·R8을 적용하고, 새 판단은 R1로 쓴다. `§P0…` 주석은 만나는 대로 Handbook 절로 바꾼다 | 리뷰 체크 항목에 반영 | 손대지 않는 코드 일괄 수정 |
| 3 | 뷰어 분리 | 충족: 빌드 없는 정적 파일로 정함 (2026-09-26) | `HTML` 문자열을 `viewer/` 패키지 데이터 파일로 옮긴다. 서버가 조립한 `HTML`은 그대로라 테스트는 계속 `ps.HTML`을 읽는다 | 내보내는 HTML이 바이트 단위로 같다. 설치 스모크 녹색 | 뷰어 동작·디자인 변경 |
| 4 | 핀 수명 주기 | 충족: 소유자 결정 (2026-09-26) | 계약 스냅숏 테스트(`pins.md`, 주요 API 응답)와 레코드 왕복 테스트를 먼저 만든다. 그다음 `pins/model.py`·`lifecycle.py`로 R1~R3을 적용한다. 전이 함수는 거절을 반환값으로 돌려준다 | 스냅숏·왕복 테스트 녹색. 전이마다 순수 테스트 | 저장 형식·API 변경 |
| 5 | 역변환과 빌드 | 충족: 소유자 결정 (2026-09-26) | `mapping/`(순수 계산)과 `build/`(부수효과)를 꺼내며 그 안의 전역 참조를 걷어 낸다 (R5) | 옮긴 모듈에 `C.`·`cur_doc()` 참조 없음. 여러 문서 동시 빌드 테스트 녹색 | 빌드 동작 변경 |
| 6 | HTTP와 조립 지점 | 4·5단계가 끝났다 | 라우팅 표, 요청 파싱, 오류 매핑을 `http/`로 모으고, `main()`을 조립 지점으로 정리한다 | `server.py`에는 조립 코드만 남는다 | 새 엔드포인트 |
| 7 | 타입 검사 확대 | 옮긴 모듈이 있다 | 타입 검사기를 옮긴 모든 모듈로 넓히고 CI 게이트로 만든다 | 타입 검사 CI 단계 녹색 | — |

> **예시**
>
> 3단계 PR의 실제 모습: "`HTML` 문자열을 `src/limn/viewer/`의 세 파일로 옮김. 서버는 시작할 때 CSS·JS를 `index.html`에 끼우고 같은 자리 표시자를 채운다. 옮기기 전후 `HTML`과 `build_html()` 결과의 sha256이 같음. 동작 변경 없음."

## 진행 상황

| 단계 | 상태 | 비고 |
| --- | --- | --- |
| 0 합의 | 완료 | 2026-09-25 이 문서와 ADR-0001 초안 작성. 같은 날 리뷰 의견("UX·UI와 스택이 확정되기 전에 구조를 굳히는 게 맞나")으로 두 층과 착수 조건을 더함. 2026-09-26 소유자 결정으로 ADR-0001 확정, 3~6단계 착수 |
| 1 안전망 | 완료 (포매팅·스타일 규칙은 남음) | 2026-09-25 Ruff 버그 후보 규칙·ShellCheck CI 게이트. `rsync` 결함을 따로 고침 |
| 2 새 코드부터 규칙 | 진행 중 | 2026-09-25부터 손대는 코드에 적용. 0.3.0~0.3.2 PR이 새 함수·테스트에 R1·R3·R7~R9를 적용함 |
| 3 뷰어 분리 | 완료 | 2026-09-26. `server.py` 10,973 → 7,378행. 출력 바이트 동일 |
| 4 핀 수명 주기 | 진행 중 | 2026-09-26 `limn/pins/`(상태 타입 `OpenPin`·`ReviewPin`·`DonePin`)와 확인(confirm) 전이. 같은 날 닫기·다시 열기(`decide`/`evolve`로 사실과 새 상태를 나누고, 알림은 셸이 사실에서 만든다). 이어서 답글(다시 여는 답글은 다시 열기 사실을 그대로 쓰고, 스레드 가득 참은 `ThreadFull` 값). 옛 코드와 응답·상태 디렉터리 전체 바이트가 같음을 차등 비교로 확인. 이어서 claim·unclaim(시계는 셸이 한 번 읽어 넘긴다). 이어서 휴지통(`TrashedPin`, 되살리기 거절은 값이라 휴지통 파일을 건드리지 않음). 편집·추가가 남음 |
| 5 역변환과 빌드 | 진행 중 | 2026-09-26 `mapping.py` 분리 (순수, `C.envs` → 인자). `build/`는 남음 |
| 6 HTTP와 조립 지점 | 시작 전 | 4·5단계 뒤 |
| 7 타입 검사 확대 | 시작 전 | — |

이 문서의 수치(줄 수, 함수 수, docstring 수, Ruff 건수)는 2026-09-25 Limn 0.2.2 기준 실측이다. 단계를 끝낼 때 새로 재서 고친다.
