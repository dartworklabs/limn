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

# HTTP 층 (limn/web/answers.py, 6단계에서 처리기 메서드에서 옮김) — 모든 결과에 응답 하나.
# 상태 코드와 본문은 에이전트 계약 그대로. show는 server.py의 public()이다
def confirm_answer(result: DonePin | AlreadyDone | PinStillOpen | AgentCannotConfirm | PinNotFound, show: Show) -> Body:
    match result:
        case DonePin(record=record) | AlreadyDone(pin=DonePin(record=record)):
            return {"ok": True, "pin": show(record), "state": "done"}
        case PinNotFound():
            return {"ok": False, "pin": None, "state": None}
        case AgentCannotConfirm():
            raise HTTPError(403, CONFIRM_BY_HUMAN, reason="confirm_by_human")
        case PinStillOpen(pin=OpenPin(record=record)):
            raise HTTPError(409, "open", pin=show(record), detail=CONFIRM_OPEN_DETAIL, reason="open")
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

**옮기기 전 모습.** 핀 상태는 저장된 필드의 조합에서 계산했다.

```python
def pin_state(r: dict) -> str:
    if not r.get("done"):
        return "open"
    return "review" if r.get("review") is True else "done"
```

`done`, `review`, `confirmed_by`, `close_reply`, `claim_until` 같은 필드는 서로 독립적이다. 예를 들어 `done`이 거짓인데 `review`가 참이거나, 열린 핀에 `confirmed_by`가 남는 조합도 사전에는 담길 수 있다. 이런 조합을 만드는 코드 경로가 없도록 사람이 조심해서 막았고, 핀 코드를 처음 보는 사람은 이 약속을 몰랐다. `pin_state()`는 서버의 다른 읽기(목록, `pins.md`)를 위해 그대로 남아 있다.

**바꾼 모습.** 상태를 필드로 들고 다니는 한 타입이 아니라, **상태마다 타입을 두고 핀을 그 합으로** 둔다 (2026-09-26, [`limn/pins/model.py`](../../src/limn/pins/model.py)). **저장 형식(`pins.jsonl`)과 API 모양은 바꾸지 않는다** ([architecture.md](architecture.md) §불변식 3, 6). 같은 날 **그 상태에만 있는 필드를 상태 타입의 속성으로 올렸다.** 열린 핀만 처리 중 표시(`Claim`)를, 닫힌 핀만 닫은 기록(`Close`)을, 완료 핀만 확인(`Confirmation`)을, 휴지통 사본만 삭제 기록(`Dropped`)을 가진다. 그래서 "열린 핀의 `confirmed_by`"나 "닫힌 핀의 claim"을 담을 속성이 아예 없다.

```python
@dataclass(frozen=True)
class OpenPin:
    """A pin nobody has closed: its stored done is false or missing. Only an open pin carries a claim."""
    claim: Claim | None          # claimed_by, claimed_at, claim_ts, claim_until, eta_ts
    fields: Record               # every other stored field, as stored
    order: tuple[str, ...] = field(default=(), compare=False, repr=False)

@dataclass(frozen=True)
class ReviewPin:
    """Closed by an agent and waiting for a person to confirm it: done and review are both true."""
    close: Close                 # done_at, closed_by, close_reply, close_ref, changes, changes_at
    fields: Record
    order: tuple[str, ...] = ...

@dataclass(frozen=True)
class DonePin:
    """Closed for good: done without review. A legacy done record with no review field is done too."""
    close: Close
    confirmation: Confirmation | None   # confirmed_by + confirmed_at
    fields: Record
    order: tuple[str, ...] = ...

Pin: TypeAlias = OpenPin | ReviewPin | DonePin

def parse_pin(record: Record) -> Pin: ...        # pin_state()와 같은 규칙, 실패하지 않는다
```

`TrashedPin`은 삭제 전의 핀(`pin: Pin`)과 `dropped: Dropped | None`을 가진다. 모든 상태가 함께 쓰는 필드(`note`, `file`, `lo`/`hi`, `thread`, `rev`, `reopened_*` 등)와 이 버전이 모르는 필드는 올리지 않고 `fields`에 저장된 그대로 둔다. `record`는 이제 속성에서 레코드를 다시 쓰는 읽기 전용 속성이고, `order`가 저장 때의 필드 순서를 기억한다. 그래서 셸의 `r.update(result.record)`와 처리기의 `case OpenPin(record=record)`는 그대로 돈다.

옛 레코드와 어긋난 값은 이렇게 담는다.

- 필드가 없으면 속성도 없다. 닫은 기록의 각 부분(`Close.at`, `Close.by` 등)은 모두 선택이고, `claim_ts`가 없는 옛 claim은 `Claim.start`가 `None`이다.
- 값의 종류가 틀리면(숫자가 아닌 `claim_until`, 객체가 아닌 `closed_by` 등) 올리지 않는다. `fields`에 저장된 그대로 남고, 상태는 그 필드가 없는 것처럼 읽는다. 파싱은 실패하지 않는다.
- 묶음은 이루는 필드가 있을 때만 올린다. claim은 `claimed_by`가 객체일 때, 확인은 `confirmed_by`와 `confirmed_at`이 함께 있을 때, 삭제 기록은 `dropped_at`과 `dropped_by`가 함께 있을 때다.
- 다른 상태의 필드는 속성이 되지 않는다. 다시 연 핀에 남는 지난 닫기의 `done_at`·`closed_by`, 손으로 고친 닫힌 핀의 claim 필드는 `fields`에 그대로 있을 뿐이다. 그래서 닫힌 핀에 대한 `unclaim`은 늘 `NotClaimed`이고 아무것도 쓰지 않는다. 어떤 버전도 닫힌 핀에 claim을 남긴 적이 없으므로(닫기는 처음부터 claim을 지웠다) 저장소가 쓴 레코드에서는 동작이 같다.
- `done`·`review`는 상태를 가르는 값이라 `fields`에 저장된 그대로 두고, 생성자가 그 값이 자기 상태를 가리키는지 확인한다. 어긋나면 `ValueError`(결함)다.

전이는 여전히 다음 레코드를 필드 하나씩 만든 뒤 곧바로 다음 상태로 파싱한다(`DonePin.from_record(record)`). 필드 순서가 바이트 계약의 일부라서다. 규칙은 올린 속성을 읽는다. 예를 들어 `claim_open`은 `pin.claim.holds(now)`와 `pin.claim.by`로 판단하고, `unclaim`은 `case OpenPin(claim=Claim())`로 claim이 있는 열린 핀만 쓴다.

한 상태에만 쓰는 전이는 그 상태 타입만 받는다(`confirm_review(pin: ReviewPin, ...)`). 요청처럼 어떤 상태든 올 수 있는 입구는 `match pin:`으로 타입을 나눈다. 상태 문자열을 비교하지 않는다.

**확인하는 법.** 옛 레코드 모양(검토 필드 없는 완료, `doc` 없는 레코드 등)을 읽어서 다시 쓰면 바이트 단위로 같아야 한다. [`tests/test_pins_model.py`](../../tests/test_pins_model.py)가 이것을 지킨다. 말뭉치 [`tests/data/pin_records.jsonl`](../../tests/data/pin_records.jsonl)은 전체 테스트가 `pins.jsonl`·`pins.dropped.jsonl`에서 읽고 쓴 레코드를 모양(필드 이름·순서·값 종류)마다 하나씩 모은 147건이다. 여기에 테스트가 더는 쓰지 않는 옛 모양과 어긋난 값 24건을 더했다. 모두 `parse_pin`과 `TrashedPin.from_record` 둘 다에서 저장소의 `json.dumps` 설정으로 바이트가 같다.

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
        raise HTTPError(400, "note 는 문자열이어야 합니다.", reason="bad_note")
    if len(v) > NOTE_MAX:
        raise HTTPError(400, "메모가 너무 깁니다(%d자 이하)." % NOTE_MAX, reason="note_too_long")
    return v
```

0.3.4부터 모든 거절에 안정 코드 `reason`이 붙는다([api.md](api.md) §오류 응답). `HTTPError`는 `reason` 없이 만들 수 없다. 흩어진 문구는 그대로지만 거절마다 이름이 생겼으므로, 옮길 때 그 코드가 거절 값의 이름과 한 표의 열쇠가 된다.

또 `detect_main()`, `free_port()`, `clean_label()`은 문제가 있으면 `sys.exit()`로 프로세스를 끝낸다. 시작할 때만 불린다는 전제가 코드에 드러나지 않는다. (2026-09-26 바꿨다: 이 함수들과 `configure_access()`·`probe_port()`는 `StartupRefused(message)`를 돌려주고, `sys.exit`은 `main()` 한 곳에만 있다. `tests/test_server.py`의 `StartupRefusals`가 검사한다.)

이렇게 되면 같은 규칙을 HTTP가 아닌 입구(예: 앞으로의 CLI 명령이나 백그라운드 작업)에서 쓰기 어렵다. 한국어 오류 문구도 48곳에 흩어진다.

**바꾼 모습.** 요청 파싱은 HTTP 층(`web/`)이 맡는다. `parse_note(v) -> NoteText | InputRejected`처럼 검증된 값이나 이유가 붙은 거절 값을 돌려준다. 도메인은 `ConfirmRejected("open")`처럼 이유를 담은 값을 **돌려준다**. HTTP 층은 `match`로 받아 이유별 상태 코드와 한국어 문구를 **한 표**에서 고른다. `sys.exit()`는 `main()` 한 곳에서만 부르고, 안쪽 함수는 시작 실패 이유를 값으로 돌려준다.

0.3의 핀 단위 변경 코드는 이미 거절을 이유(`ScopeRejected(reason)`)와 표 하나(`SCOPE_REJECTIONS`)로 모았다. 다만 예외로 던지므로, 모듈로 옮길 때 반환값으로 바꾼다. 이유마다 데이터나 응답이 다르면 그때 경우별 타입으로 나눈다 (R1 §결과 타입을 고르는 법). 2026-09-26 그렇게 옮겼다: `limn/scope.py`가 경우마다 한 값(`PinNotInDoc`·`ScopeUnreadable`·`ScopeMismatch`·`UnsafePath`·`ScopeUnwritable`, 묶음 이름 `ScopeRefusal`)을 돌려주고, 표 `SCOPE_REJECTIONS`는 그 타입을 열쇠로 여전히 하나다.

**확인하는 법.** 오류 응답 본문(`{"error": ..., "reason": ...}`)과 상태 코드가 옮기기 전후에 같아야 한다. API 오류 문자열은 에이전트 계약의 일부다. 도메인 함수의 반환 타입에 거절 값이 드러나고, 그 함수 안에 업무상 거절을 위한 `raise`가 남지 않는다.

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

**빌드에 적용한 모습 (2026-09-26).** [`limn/build.py`](../../src/limn/build.py)의 함수는 모두 문서를 첫 인자로 받는다. 설정은 조립 지점이 실행 인자에서 만든 작은 값 `BuildConfig(state, dpi, timeout)`로 넘긴다. 문서마다 따로인 오래 사는 자원(빌드 잠금, 빌드 상태와 그 잠금, 이력 잠금, `src_mtime` 캐시)은 원래대로 문서 객체가 갖고, 빌드 모듈은 import 때 아무 자원도 만들지 않는다. 캐시 세 칸을 읽고 채우는 짧은 잠금 하나만 모듈에 있다. 여러 문서를 묶는 `--git-pull`은 조립 지점 쪽에 두고 단계로 넘긴다.

```python
def compile_tex(D: BuildDoc, cfg: BuildConfig, pull: Callable[[], dict] | None) -> dict:
    """Builds D with -synctex=1 from a copy, ... then renders pages into a new directory and only swaps the pointer."""

# server.py — 조립 지점의 연결: 처리기가 넘긴 문서에 이 인스턴스의 설정을 묶는다 (6단계에서 셸을 없앴다)
def _build(D: Doc) -> dict:
    return build.compile_tex(D, build_config(), repo_pull if C.git_pull else None)
```

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

**바꾼 모습.** [architecture.md](architecture.md) §목표 구조를 따른다. 첫 단계로 뷰어를 패키지 데이터 파일(`viewer/index.html`, `app.css`, `app.js`)로 꺼냈다 (3단계 완료, 2026-09-26). 빌드 단계도 CDN도 없이 서버가 시작할 때 CSS·JS를 `index.html`에 끼워 한 장의 HTML로 내주므로 [architecture.md](architecture.md) §불변식 2를 지킨다. 서버가 채우던 자리 표시자(`__ACCENT__`, `{{ic:이름}}` 등)는 그대로 쓴다. 이제 JS와 CSS를 편집기 도구로 다룰 수 있다. 같은 날 한 파일이던 `app.js`(2,985줄)와 `app.css`(902줄)를 변경 이유가 다른 조각 45개(`viewer/js/` 35개, `viewer/css/` 10개)로 나눴다. 예: PDF.js 열기·그리기, 목차, 작성 패널, 카드, 목록, 답글, 편집, @태그, 제스처, 화면 언어, 폴링. 조각의 순서는 `viewer/parts.txt` 하나가 정한다. 서버는 그 순서대로 조각을 이어 붙이기만 하므로 빌드 단계도 모듈 로더도 없다. 조각은 한 스크립트 범위를 나눠 쓰는 파일이지 모듈이 아니다. 그래서 조각 사이의 의존 방향은 아직 도구로 확인하지 않는다 ([viewer.md](viewer.md) §뷰어 규칙을 바꿀 때). 다음은 `server.py` 안의 책임별 구역을 모듈로 옮기는 일이다 (§단계별 로드맵의 실행 순서).

**확인하는 법.** 서버가 내보내는 HTML이 옮기기 전과 바이트 단위로 같다. 조각으로 나눌 때도 나누기 전후 `HTML`과 `build_html()` 결과의 sha256이 같았다. 설치 스모크([verification.md](verification.md) §3)가 새 데이터 파일이 패키지에 들어갔는지 확인한다. `tests/test_viewer_files.py`가 목록과 조각, 조립 결과가 맞는지 보고, 내보내는 페이지의 스크립트마다 `node --check`를 돌린다.

## R7 계약을 말하는 docstring

**규칙이 말하는 것.** 새로 쓰거나 고친 모듈·클래스·함수·메서드에는 private 도우미까지 docstring을 단다. 이름을 되풀이하지 말고, 의도와 계약(전제 조건, 결과, 부수효과, 실패)을 적는다. 손대지 않은 파일에 한꺼번에 달지는 않는다.

**업계에서 부르는 이름.** 계약에 의한 설계(Design by Contract, Bertrand Meyer)의 전제·결과를 글로 적는 것. 파이썬 형식은 PEP 257이 정한다.

**지금 코드의 모습.** `server.py` 함수 353개 중 136개에 docstring이 없다. `migrate.py`(10개 중 9개)와 `cli.py`(22개 중 5개, 클래스 `CliError`도)에도 없었는데, 2026-09-26 두 파일을 타입 검사에 넣으면서 모두 달았다 (R8). 있는 것 중에는 `pin_state()`처럼 이유까지 설명하는 훌륭한 글이 많다. 반대로 없는 곳에서는 중요한 계약이 숨는다.

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

**지금 모습 (7단계 착수, 2026-09-26).** 타입 검사기는 mypy다. 옮긴 모듈(`limn/pins/`, `mapping.py`)을 strict 모드와 `exhaustive-match`로 검사하고, CI `lint` 작업이 `uv run mypy`를 돌린다 ([verification.md](verification.md) §9에 고른 이유와 게이트). 검사를 켜면서 두 모듈의 오류 35건을 동작을 바꾸지 않고 정리했다.

- `mapping.py` (33건): 표기 없는 인자·반환, 타입 인자 없는 `list`·`dict`·`tuple`, `Any` 반환에 타입을 적었다. 읽기만 하는 줄 목록은 `Sequence[str]`, 토큰 가중치는 `TokenWeights`, 범위 사다리의 한 단은 `Level`로 이름을 붙였다. `find_line()`은 문자열이 아닌 needle도 받는 계약이라 `needle: object`로 적었다. `compute_levels()`에서 `None`일 수 있다던 기본 단 3건은, `para` 단이 늘 있으므로 `assert`로 좁혔다.
- `pins/lifecycle.py` (2건): `_is_num()`을 `TypeGuard[int | float]`로 적어 `claim_holds()`의 `float(until)`을 좁혔다. `restore()`의 `AlreadyLive`에는 저장된 id를 그대로 넘기며 `cast(int, ...)`로 검사기에만 알렸다 (휴지통 사본의 id는 `find_trashed()`가 맞춰 본 값이다).
- `cli.py`·`migrate.py` (2026-09-26, 20건): 타입 인자 없는 `dict`·`list`·`tuple`·`CompletedProcess` 12건, 표기 없는 인자·반환 3건, 표기 없는 함수 호출 4건, 그것을 고친 뒤 드러난 지역 변수 타입 충돌 1건이었다. 인자는 읽기만 하므로 `Sequence[str]`, `split_target()`의 추가 옵션 한 개는 `OptionSpec`으로 이름을 붙였다. `server_module()`은 반환 타입을 적으면 모듈이 `ModuleType`(속성이 모두 `Any`)이 되어 저장 도우미 호출을 검사하지 못하므로, 부르던 세 함수 안에서 `from limn import server as ps`로 바로 들여오고 지웠다 (들여오는 때는 그대로라 `limn version`은 여전히 `server.py`를 읽지 않는다). `cmd_member()`에서 두 가지 타입으로 쓰이던 지역 변수 `e`는 `role` 가지에서 `changed`로, `migrate.main()`의 `strip` 람다는 모듈 함수 `without_state()`로 바꿨다. 새 `TypedDict`·`dataclass`는 만들지 않았다. 경계를 넘는 구조화된 값은 이미 `SaveTarget`이 있고, 토큰·구성원 레코드의 모양은 `server.py`의 저장 도우미가 정본이라 그쪽을 옮길 때 적는다. `limn` 명령 65번(version·help·serve --help·migrate·token·member, 거절 포함)을 main과 이 변경에서 한 번씩 따로 프로세스로 돌려 비교했을 때 출력·종료 코드·파일이 같았다.

**확인하는 법.** 타입 검사기가 옮긴 모듈에서 오류 0으로 끝난다. 일부러 `match`의 상태 하나를 빼 보았을 때 검사기가 알려 주는지 한 번 확인한다 (2026-09-26 `confirm()`에서 `case DonePin():`을 지워 확인, [verification.md](verification.md) §9).

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

실행 순서는 표의 번호와 조금 다르다. `server.py`를 빨리 가볍게 하려고 기계적으로 옮길 수 있는 것부터 한다: 3단계(뷰어) → 5단계 앞부분(`mapping.py`, 거의 순수) → 4단계(`store`·핀 모델·전이) → 5단계 나머지(`build/`) → 6단계(`web/`, 조립 지점). 포매팅 커밋은 옮기기가 끝난 뒤에 한 번에 한다.

| 단계 | 목표 | 착수 조건 | 하는 일 | 끝났다는 증거 | 하지 않는 일 |
| --- | --- | --- | --- | --- | --- |
| 0 | 합의 | 없음 | 이 문서와 [ADR-0001](../adr/0001-blueprint.md)을 검토하고 확정한다. 3~6단계 착수 조건을 정한다 | ADR-0001 상태가 `확정`. 착수 조건 충족 | 코드 변경 |
| 1 | 안전망 | 없음. 0단계와 나란히 | Ruff 버그 후보 규칙과 shellcheck를 CI에 더한다 (R4). 스타일 규칙과 전체 포매팅은 별도 커밋으로 뒤에 한다 | CI에 새 단계가 녹색. [verification.md](verification.md) §6 표 갱신 | 동작 변경, docstring 일괄 추가 |
| 2 | 새 코드부터 규칙 | 없음. 0단계와 나란히 | 이후 모든 PR은 손대는 함수에 R7·R8을 적용하고, 새 판단은 R1로 쓴다. `§P0…` 주석은 만나는 대로 Handbook 절로 바꾼다 | 리뷰 체크 항목에 반영 | 손대지 않는 코드 일괄 수정 |
| 3 | 뷰어 분리 | 충족: 빌드 없는 정적 파일로 정함 (2026-09-26) | `HTML` 문자열을 `viewer/` 패키지 데이터 파일로 옮긴다. 서버가 조립한 `HTML`은 그대로라 테스트는 계속 `ps.HTML`을 읽는다 | 내보내는 HTML이 바이트 단위로 같다. 설치 스모크 녹색 | 뷰어 동작·디자인 변경 |
| 4 | 핀 수명 주기 | 충족: 소유자 결정 (2026-09-26) | 계약 스냅숏 테스트(`pins.md`, 주요 API 응답)와 레코드 왕복 테스트를 먼저 만든다. 그다음 `pins/model.py`·`lifecycle.py`로 R1~R3을 적용한다. 전이 함수는 거절을 반환값으로 돌려준다 | 스냅숏·왕복 테스트 녹색. 전이마다 순수 테스트 | 저장 형식·API 변경 |
| 5 | 역변환과 빌드 | 충족: 소유자 결정 (2026-09-26) | `mapping/`(순수 계산)과 `build/`(부수효과)를 꺼내며 그 안의 전역 참조를 걷어 낸다 (R5) | 옮긴 모듈에 `C.`·`cur_doc()` 참조 없음. 여러 문서 동시 빌드 테스트 녹색 | 빌드 동작 변경 |
| 6 | HTTP와 조립 지점 | 4·5단계가 끝났다 | 라우팅 표, 요청 파싱, 오류 매핑을 `web/`(표준 모듈 `http`를 가리지 않는 이름, [architecture.md](architecture.md) §현재 구조)으로 모으고, `main()`을 조립 지점으로 정리한다 | `server.py`에는 조립 코드만 남는다 | 새 엔드포인트 |
| 7 | 타입 검사 확대 | 옮긴 모듈이 있다 | 타입 검사기를 옮긴 모든 모듈로 넓히고 CI 게이트로 만든다 | 타입 검사 CI 단계 녹색 | — |

> **예시**
>
> 3단계 PR의 실제 모습: "`HTML` 문자열을 `src/limn/viewer/`의 세 파일로 옮김. 서버는 시작할 때 CSS·JS를 `index.html`에 끼우고 같은 자리 표시자를 채운다. 옮기기 전후 `HTML`과 `build_html()` 결과의 sha256이 같음. 동작 변경 없음."

## 진행 상황

| 단계 | 상태 | 비고 |
| --- | --- | --- |
| 0 합의 | 완료 | 2026-09-25 이 문서와 ADR-0001 초안 작성. 같은 날 리뷰 의견("UX·UI와 스택이 확정되기 전에 구조를 굳히는 게 맞나")으로 두 층과 착수 조건을 더함. 2026-09-26 소유자 결정으로 ADR-0001 확정, 3~6단계 착수 |
| 1 안전망 | 완료 (포매팅·스타일 규칙은 남음) | 2026-09-25 Ruff 버그 후보 규칙·ShellCheck CI 게이트. `rsync` 결함을 따로 고침 |
| 2 새 코드부터 규칙 | 진행 중 | 2026-09-25부터 손대는 코드에 적용. 0.3.0~0.3.3 PR이 새 함수·테스트에 R1·R3·R7~R9를 적용함(0.3.3은 보안 경계라 R10 부정 경우 테스트도) |
| 3 뷰어 분리 | 완료 | 2026-09-26. `server.py` 10,973 → 7,378행. 출력 바이트 동일. 같은 날 `app.js`·`app.css`를 책임별 조각 45개로 나눴다(R6, 순서는 `viewer/parts.txt`). 나누기 전후 `HTML`·`build_html()`의 sha256이 같고, 내보내는 스크립트는 `node --check`를 통과한다(CI에서 필수) |
| 4 핀 수명 주기 | 진행 중 | 2026-09-26 `limn/pins/`(상태 타입 `OpenPin`·`ReviewPin`·`DonePin`)와 확인(confirm) 전이. 같은 날 닫기·다시 열기(`decide`/`evolve`로 사실과 새 상태를 나누고, 알림은 셸이 사실에서 만든다). 이어서 답글(다시 여는 답글은 다시 열기 사실을 그대로 쓰고, 스레드 가득 참은 `ThreadFull` 값). 옛 코드와 응답·상태 디렉터리 전체 바이트가 같음을 차등 비교로 확인. 이어서 claim·unclaim(시계는 셸이 한 번 읽어 넘긴다). 이어서 휴지통(`TrashedPin`, 되살리기 거절은 값이라 휴지통 파일을 건드리지 않음). 이어서 편집·추가(`limn/pins/edit.py`: `decide_edit`가 닫힌 핀의 위치 변경·낡은 `base_rev`·덧붙인 메모 길이·파일 밖 줄 범위를 값으로 돌려주고, `evolve_edit`·`new_line_pin`·`new_region_pin`이 레코드를 옛 필드 순서 그대로 만든다. 본문 파서 `parse_edit`·`parse_add`는 `InputRejected` 값을 돌려주고 처리기가 옛 문구로 답한다). 이로써 핀 조작의 전이는 모두 옮겼다. 이어서 핀 저장소를 `limn/store.py`로 꺼냈다: `PinStore`가 잠금 아래 쓰기 순서(`transact`), `pins.jsonl`·`pins.md`·휴지통 쓰기와 손상 원본 보존, `pins.seq`, clear 보관을 맡고, 파일 위치·잠금·레코드 검사·줄 맞춤·`pins.md` 렌더·거절 예외는 조립 지점 `server.pin_store()`가 호출마다 인자로 넘긴다(서버를 가져오지 않음, `tests/test_store.py`가 검사). 옛 이름 `transact`·`read_pins`·`write_pins` 등은 `server.py`에 남아 저장소에 넘긴다. 옛 코드와 응답·상태 디렉터리 전체 바이트(손상 백업·clear 보관 이름 포함)가 같음을 차등 비교로 확인. 이어서 상태에만 있는 필드를 상태 타입의 속성으로 올렸다(열림의 `Claim`, 닫힘의 `Close`, 완료의 `Confirmation`, 휴지통의 `Dropped`; `record`는 저장 순서대로 다시 쓰는 속성). 테스트가 읽고 쓴 모든 레코드 모양 147건과 옛 모양 24건의 왕복이 바이트 단위로 같고(`tests/test_pins_model.py`), 옛 코드와 응답·상태 디렉터리 바이트가 같음을 핀 흐름 80단계 차등 비교로 확인. 이로써 R2 §다음 단계로 적어 둔 일도 끝났다 |
| 5 역변환과 빌드 | 완료 | 2026-09-26 `mapping.py` 분리 (순수, `C.envs` → 인자). 같은 날 `build.py` 분리: 문서(`BuildDoc`)와 설정(`BuildConfig`)을 인자로 받고, `--git-pull`과 보기 전용 그리기는 단계로 넘겨받는다. `C.`·`cur_doc()` 없음(`tests/test_build.py`), 두 문서 동시 빌드 테스트 녹색. 옛 코드와 응답·빌드 상태·상태 디렉터리 전체 바이트가 같음을 차등 비교로 확인(성공, LaTeX 오류, PDF 없음, SyncTeX 없음, pdftoppm 실패, 복사 실패, 시간 초과, 빌드 예외, 두 LaTeX 문서와 보기 전용 PDF). `--git-pull`·원격 main 감시는 문서 여럿을 묶는 일이라 `server.py`에 남고, `server.py`의 옛 이름 셸은 6단계에서 없앤다 |
| 6 HTTP와 조립 지점 | 진행 중 | 2026-09-26 소유자 결정으로 4단계의 `store.py`와 나란히 시작. 앞부분: HTTP 처리기(`Handler`·`Server`·`Server6`, 본문 읽기와 1 MiB 한도, Host/Origin 검사 호출, GET/POST 경로 분기), 결과별 응답(옛 `_*_answer`·`_*_reply` 메서드 → `limn/web/answers.py`의 함수), `HTTPError`·`InputRejected`·`SCOPE_REJECTIONS`·거부된 첫 화면을 `limn/web/`로 옮겼다. 처리기는 `server.py`를 가져오지 않는다. `server.py`가 자기 전역을 요청 때 그대로 읽는 보기(`_ModuleApp`)로 하위 클래스 `Handler`를 묶고, 처리기가 부르는 서비스 목록은 `web/app.py`의 `App` 프로토콜이다. 신원·역할·Host/Origin 판단(`identify`·`admit`·`check_role`·`host_ok`·`origin_ok`)은 보안 경계라 `server.py`에 그대로 두었다. 경로 표는 만들지 않았다 — 분기 순서가 응답을 정하므로(`/pages/`가 404로 떨어지는 길, `/api/pins/dropped`가 `/api/pins/N`보다 먼저) 이번에는 옮기기만 했다. 옛 코드와 응답(상태, Date·Server를 뺀 헤더, 본문)과 상태 디렉터리 전체 바이트가 같음을 160개 경우의 차등 비교로 확인(모든 핀 조작과 거절, 잘못된 JSON·본문 한도·`Transfer-Encoding`, 잘못된 Host·Origin, 테일넷의 헤더 없는 요청, 토큰 에이전트, 역할별 403, 거부된 첫 화면 ko·en, 500, 핀 단위 변경 거절 표). 뒷부분 첫째(요청 파서): 본문·쿼리의 파서를 모두 `limn/web/parse.py`로 옮겼다. 파서마다 값이나 `InputRejected`를 돌려주고(옛 `clean_*`는 `HTTPError`를 던졌다), 처리기가 `accepted()`로 옛 400 문장 그대로 답한 뒤 서비스에 파싱된 값을 넘긴다(`add_pin(D, AddRequest, …)`, `edit_pin(pid, EditRequest, …)`, `pick(D, PickRequest)` 등). 필드를 보는 순서와 부수효과와의 순서(예: 잘못된 `?ev=`는 meta를 만든 뒤에 거절)는 옛 코드 그대로다. 원고와 맞춰 보는 파서(새 핀·편집 위치·선택·snippet)는 파일의 줄과 빌드의 쪽을 `DocumentFacts`로 받고, 조립 지점이 `document_facts(D)`로 문서마다 만든다. 원고 트리 경로 규칙은 `limn/files.py`의 `file_in_tree` 하나로 모아 파서와 선택 해석이 같이 쓴다. `server.py`는 더 이상 `InputRejected`를 만들거나 가져오지 않는다(`raise HTTPError` 82 → 47곳, `cur_doc()` 35 → 28곳). 옛 코드와 응답·상태 디렉터리 전체 바이트가 같음을 314개 요청(파서의 모든 거절, 여러 문서의 보기 전용 PDF 핀 포함)의 차등 비교로 확인. 뒷부분 둘째(결과 값): 원고 이력·핀 단위 변경·비교 PDF를 `limn/revisions.py`(git 쪽)와 `limn/scope.py`(순수 판단)로 옮기며 거절을 값으로 바꿨다. 경로의 거절은 경우마다 한 타입(`NoHistory`·`CommitNotRecent`·`DiffFailed`·`DiffUnavailable`·`NotInRepo`·`NoParent`·`UnsafeCache`·`AllSlotsBusy`·`DocumentBusy`·`RevisionNotReady`·`RevisionPdfMissing`, 경로마다 `DiffRefusal` 등으로 묶음)이고 `answers.revision_answer`가 옛 상태·문구로 답한다. `ScopeRejected` 예외는 경우별 값 `ScopeRefusal`이 됐고 `SCOPE_REJECTIONS`는 그 타입을 열쇠로 하나로 남았다. 비교 빌드의 단계 실패는 `StepFailed(kind)` 하나(모든 경우가 같은 데이터·같은 처리: 상태 파일에 기록)이고 문구 표 `REVISION_FAILURES`는 `web/errors.py`에 있다. 워커는 조립 지점이 넘긴 `revision_failure_text`로 옛 문구를 그대로 기록한다. 커밋 형식 검사(`bad_commit`)는 요청 파서로 옮겼다. 문서 조회는 `DocNotFound`를 돌려준다. `raise HTTPError`는 `server.py`에서 47 → 16곳(남은 것은 신원·입장·역할 판단). 옛 코드와 응답·상태 디렉터리 전체 바이트가 같음을 git 저장소를 둔 346개 요청의 차등 비교로 확인(핀 단위 diff, 비교 빌드 실패 기록, 슬롯·문서 잠금 409, 캐시 심링크 503, 첫 커밋 422 포함). 뒷부분 셋째(문서는 인자, R5): 스레드 지역 "현재 문서"(`cur_doc()`·`using_doc()`)를 없앴다. 처리기가 요청의 문서를 찾아 모든 서비스에 넘기고(`meta(D, …)`·`build_all(D)`·`build_state_snapshot(D)` 등), 빌드 스레드는 자기 문서로 시작한다. 빌드의 옛 이름 셸 22개(`cur_pages()`·`src_mtime()`·`seed_builds()`·`_read_head()` 등)를 지우고 부르는 쪽이 `limn.build`에 문서와 설정을 넘긴다. 남은 빌드 연결은 `build_all(D)`·`build_async(D)`·`_build(D)`·`_render_pdf_doc(D)`로, `BuildConfig`·`--git-pull`·보기 전용 그리기를 묶는 조립 지점의 일이다. `Doc`은 `limn/documents.py`로 옮겨 실행 경로를 만들 때 받은 `RunPaths`(조립 지점의 `C`)에서 읽는다. `cur_doc()`은 `server.py`에서 28 → 0곳, 처리기의 `app.cur_doc()`도 0곳. `C.`는 219 → 210곳. 옛 코드와 응답·상태 디렉터리 전체 바이트가 같음을 355개 요청(여러 문서의 실제 비동기 빌드 포함)의 차등 비교로 확인. 뒷부분 넷째(조립 지점): `main()`은 인자를 파싱해 `start()`에 넘기고, 거절이면 그 문구로 끝내고 아니면 서버를 돌린다. `start()`는 단계를 차례로 부른다: 접근 설정(`configure_access`), `--port` 확인(`probe_port`), 실행 설정과 문서(`configure_run`), 저장소와 빌드와 감시 스레드(`prepare`), 시작 요약(`report`), 듣는 서버(`listen`). 시작을 막는 단계는 모두 `StartupRefused`를 돌려주고 `sys.exit`은 `main()`에만 있다(R3). 순서와 문구, 상태 폴더를 만드는 시점은 그대로다. 옛 코드와 거절 20가지·정상 시작 3가지의 종료 코드·stdout·stderr·상태 폴더가 같음을 따로 돌린 시작 차등 비교로 확인. 신원·입장·역할 판단(`identify`·`admit`·`check_role`·`bearer_of`)은 옮기지 않았다. 옮기는 것이 기계적이지 않다: 이 함수들은 실행 설정 13개와 파일에 기댄 조회 4가지(`tokens.json`·`people.json`과 그 캐시, 에이전트 토큰 파일 안내)를 읽는데, 그 조회를 CLI와 `pins.md`도 쓴다. `web/`으로 옮기려면 이것들을 모두 인자로 넘겨야 해서 경계를 옮기는 게 아니라 다시 쓰는 일이 된다. 또 이 경계의 거절은 일부러 예외(`HTTPError`)다. 던진 거절은 부르는 쪽이 놓칠 수 없지만, 값으로 돌려준 거절은 새로 짠 호출자가 무시하면 요청이 통과한다. 그래서 `server.py`가 `limn.web`에서 가져오는 것은 이 네 함수의 `HTTPError`·`CONFIRM_BY_HUMAN`(과 저장소에 넘기는 거절 타입)으로 좁혀졌다. `C.`는 `server.py`에서 210 → 208곳이고, 그중 124곳이 조립 지점에 있다: 시작 단계(`configure_access`·`access_log_lines`·`configure_run`·`prepare`·`report`·`listen`·`start`와 `init_doc`·`tighten_state_perms`) 114곳, 요청마다 서비스에 넘기는 연결(`build_config`·`pin_store`·`document_facts`·`revision_context`) 10곳. 나머지 84곳은 서비스 안에 있다. 남은 일: 서비스(meta, `pins.md`, 사람·이벤트, 휴지통, 핀 위치, 신원)가 `C`를 읽지 않고 설정을 인자로 받게 하기. 그러면 `server.py`에는 조립 코드만 남는다 |
| 7 타입 검사 확대 | 진행 중 | 2026-09-26 옮긴 모듈(`limn/pins/`, `mapping.py`)부터 mypy strict를 CI 게이트로 켰다 (R8). 모듈을 옮기는 대로 `[tool.mypy]`의 `files`에 더한다. 같은 날 `build.py`·`files.py`를 더했다(표기만 고침, 동작 그대로). 이어서 `store.py`를 더했다. 0.3.4의 새 순수 모듈 `mark.py`도 처음부터 넣었다. 이어서 `web/`을 더했다(처리기가 부르는 서비스는 `App` 프로토콜로 적고, `cast` 한 곳에 이유를 단다). 이어서 `limn` 명령(`cli.py`·`migrate.py`·`__init__.py`·`__main__.py`)을 더하고 두 파일의 docstring을 모두 달았다(R7, 동작 그대로). `server.py`는 남음 |

이 문서의 수치(줄 수, 함수 수, docstring 수, Ruff 건수)는 2026-09-25 Limn 0.2.2 기준 실측이다. 단계를 끝낼 때 새로 재서 고친다.
