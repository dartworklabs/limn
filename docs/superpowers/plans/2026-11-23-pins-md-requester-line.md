# pins.md 요청자 줄 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /pins.md` 가 그 요청의 신원(이름·로그인·역할·신원 출처) 한 줄을 머리말에 보이고, 디스크 사본은 같은 자리에 요청자 없음 줄을 두며, 토큰 없는 사람 신원 쓰기의 안내가 "내가 일하는 사용자일 때만"으로 바뀐다.

**Architecture:** 신원은 이미 요청마다 `Principal(actor, role, via)` 로 정해진다. `security/access.py` 가 그것과 신원 방식으로 닫힌 값 `RequestIdentity` 를 만들고, 조립 지점(`server.py`)이 그 함수를 pin 경로에 넘긴다. 순수 렌더러(`pins/listing/render.py`)는 `PinsMdInput.requester` 가 `None` 이면 디스크 줄, 값이면 요청자 줄을 `갱신:` 다음에 낸다. 디스크를 쓰는 렌더 경로는 요청자를 받지 않는다.

**Tech Stack:** Python 표준 라이브러리(서버 런타임 `dependencies = []`), unittest/pytest, basedpyright, ruff.

**Spec:** [docs/superpowers/specs/2026-11-23-pins-md-requester-line-design.md](../specs/2026-11-23-pins-md-requester-line-design.md) (승인됨, 커밋 `1d985ba5`)

## Global Constraints

- 코드는 PR #543이 `main` 에 머지된 뒤 그 `main` 위에서만 쓴다(Task 0).
- 서버 런타임은 표준 라이브러리만 쓴다(`dependencies = []`).
- 코드·주석·docstring·커밋 메시지는 영어, Handbook은 한국어. `skill/SKILL.md` 와 `skill/SKILL.ko.md` 는 함께 고친다.
- 커밋은 모두 `git commit -s` 이고 메시지 끝에 `I agree to the Limn CLA (CLA.md).` 를 둔다. 메시지에 `Signed-off-by` 를 손으로 쓰지 않는다.
- 예시 계정은 `alice@example.com` 꼴, 예시 호스트는 `box.tail1234.ts.net` 꼴. 실제 이메일·홈 경로·호스트 이름·org 이름을 넣지 않는다. 문서만 고친 커밋도 `uv run pytest -q tests/architecture/` 를 돌린다.
- `pins.md` 문구는 spec §설계 1–3의 글자 그대로다. 구현에서 문구를 바꿔야 할 사정이 생기면 바꾸지 말고 소유자에게 묻는다.
- 역할·신원 비교는 `security/access.py` 밖에 두지 않는다(architecture.md).
- 핀 파일은 쓰지 않는다. 디스크 `pins.md` 는 지금처럼 쓰기 뒤 렌더에서만 쓴다.
- ADR은 `제안` 으로 쓰고, 머지 직전 마지막 커밋에서만 `승인됨` 으로 올린다.

## Review Focus

1. 같은 keep-alive 연결이나 연달아 온 두 요청의 신원이 다르면, 각 응답이 자기 신원만 보여야 한다(앞 요청의 줄이 남지 않는다) → Task 3 `test_each_request_sees_only_itself`.
2. 사람 신원으로 쓴 직후의 디스크 사본에 그 로그인이 들어가면 안 된다 → Task 3 `test_disk_copy_never_holds_the_requester`.
3. `--tailnet-agent` 로 받은 헤더 없는 테일넷 요청(`Host: box.tail1234.ts.net`, `X-Forwarded-For`)은 헤더 없는 루프백 이름표를 받아야 한다 → Task 3 `test_tailnet_agent_request_is_the_loopback_agent`.
4. 표시 이름에 `|`·줄바꿈, 로그인에 백틱이 있어도 머리말이 한 줄로 남고 코드 스팬이 깨지지 않아야 한다 → Task 2 `test_hostile_name_and_login_stay_on_one_line`.
5. `people.json` 을 읽을 수 없는 동안 헤더로 온 사람은 `역할 viewer` 로 보여야 한다(닫힌 기본값이 줄에도 보인다) → Task 3 `test_unreadable_people_shows_viewer`.

---

### Task 0: #543 머지 뒤의 main 위로 옮기기

**Files:** 없음(브랜치 작업)

- [ ] **Step 1:** `gh pr view 543 --repo dartworklabs/limn --json state,mergedAt` 가 `MERGED` 인지 확인한다. 아니면 멈춘다.
- [ ] **Step 2:** `git fetch origin` 뒤 `git rebase origin/main`. 이 브랜치의 커밋은 spec·plan 문서뿐이라 충돌이 없어야 한다.
- [ ] **Step 3:** 머지된 `main` 에서 다음을 다시 읽고, 이 계획의 이름·자리와 어긋나면 계획을 먼저 고친다: `security/access.py` 의 `Principal`·`Via`·`identify`, `security/values.py`(있으면 닫힌 값의 자리), api.md §인증·§pins.md 안내 줄·§원격 에이전트 진입점, `skill/SKILL*.md` §인증, `tests/contracts/test_contract_snapshot.py`.
- [ ] **Step 4:** `ls docs/adr/ | sort | tail -3` 으로 가장 큰 ADR 번호를 확인하고 이 ADR의 번호 `NNNN` 을 정한다(예상 0056).
- [ ] **Step 5:** `uv sync --group dev && uv run pytest -q tests/architecture/` 가 통과한다.

### Task 1: 보안 쪽 신원 값 `RequestIdentity`

**Files:**
- Modify: `src/limn/security/access.py` (`Principal` 정의 아래)
- Test: `src/limn/security/tests/test_request_identity.py` (새 파일)

**Interfaces:**
- Produces:
  - `IdentitySource: TypeAlias = Literal["tailnet-header", "proxy-header", "local-owner", "token", "loopback-agent"]`
  - `PERSON_SOURCES: frozenset[IdentitySource] = frozenset({"tailnet-header", "proxy-header", "local-owner"})`
  - `class RequestIdentity(NamedTuple): name: str; login: str; role: Role; source: IdentitySource` 와 메서드 `is_person(self) -> bool`(`source in PERSON_SOURCES`)
  - `def request_identity(p: Principal, auth: AuthProvider) -> RequestIdentity`

- [ ] **Step 1: 실패하는 시험을 쓴다.** `RequestIdentityOf(unittest.TestCase)`:
  - `test_tailnet_header`: `Principal({"login":"alice@example.com","name":"Alice Kim"}, "editor", "header")`, `"tailscale"` → `RequestIdentity("Alice Kim","alice@example.com","editor","tailnet-header")`, `is_person()` 참.
  - `test_proxy_header`: 같은 주체, `"trusted-proxy"` → 출처 `"proxy-header"`, 사람.
  - `test_local_owner`: `Principal({"login":"alice","name":"alice"}, "owner", "local-owner")`, `"local"` → 출처 `"local-owner"`, 사람.
  - `test_token`: `Principal({"login":"agent:reviewer","name":"reviewer"}, "agent", "token")` → `RequestIdentity("reviewer","agent:reviewer","agent","token")`, `is_person()` 거짓.
  - `test_loopback_agent`: `Principal(dict(LOCAL_ACTOR), "agent", "loopback-agent")`, `"tailscale"` → `("로컬/에이전트","local","agent","loopback-agent")`, 사람 아님.
  - `test_agent_role_person_is_a_person`: 헤더 주체에 역할 `"agent"` → 출처 `"tailnet-header"`, `is_person()` 참.
  - `test_empty_name_falls_back_to_login`: `name` 이 `""` 이거나 없으면 `name == login`.
- [ ] **Step 2:** `uv run pytest -q src/limn/security/tests/test_request_identity.py` → 이름이 없어 FAIL.
- [ ] **Step 3: 구현.** `request_identity` 는 `via` 로 가르고, `"header"` 만 `auth == "trusted-proxy"` 이면 `"proxy-header"`, 그 밖이면 `"tailnet-header"` 다. `match` 를 빠짐없이 써서 basedpyright가 모든 `Via` 를 확인하게 한다. 새 이름을 `__all__` 이 있으면 거기에 더한다.
- [ ] **Step 4:** 같은 명령 → PASS. `uv run python tools/check_types.py` 와 `uv run python tools/check_boundaries.py` 통과.
- [ ] **Step 5: 커밋** `feat(security): name a request's identity source for pins.md` (서명·CLA).

### Task 2: 렌더러의 요청자 줄과 디스크 줄

**Files:**
- Modify: `src/limn/pins/listing/render.py` (`PinsMdInput`, 상수, `requester_line`, `pins_md_text` 의 `갱신:` 다음)
- Test: `src/limn/pins/tests/test_render.py` (새 클래스 `RequesterLine`)

**Interfaces:**
- Consumes: Task 1의 `RequestIdentity`, `IdentitySource`.
- Produces:
  - `PinsMdInput.requester: RequestIdentity | None = None` (마지막 필드, 기본값 `None`. 기존 시험의 생성자를 깨지 않는다)
  - 상수 `REQUESTER_SOURCES: dict[IdentitySource, str]`, `REQUESTER_PERSON_TAIL: str`, `REQUESTER_AGENT_TAIL: str`, `REQUESTER_DISK: str`(`%s` 하나 = 루프백 base)
  - `def requester_line(requester: RequestIdentity | None, loopback_base: str) -> str`

문구는 spec §설계 1·2 그대로다:

```python
REQUESTER_SOURCES = {
    "tailnet-header": "테일넷 헤더(이 기기에 로그인한 테일넷 계정)",
    "proxy-header": "프록시 헤더(인증 프록시가 보낸 사용자)",
    "local-owner": "로컬 소유자(--auth local 의 루프백 요청)",
    "token": "토큰",
    "loopback-agent": "헤더 없는 루프백(폐지 예정)",
}
REQUESTER_PERSON_TAIL = (
    " — 이 요청으로 쓰면 이 사람으로 기록된다 · 내가 일하는 사용자가 아니면 쓰지 말고 "
    "사용자에게 토큰을 요청한다(`limn token create <인스턴스>`)"
)
REQUESTER_AGENT_TAIL = " — 이 요청으로 쓰면 에이전트로 기록된다"
REQUESTER_DISK = (
    "요청자: 없음(디스크 사본) — 쓰는 요청의 신원은 요청마다 정해진다 · "
    "확인하려면 쓸 때와 같은 인증으로 `curl -s %s/pins.md` 를 읽어 이 줄을 본다"
)
```

줄 모양: `"요청자: %s(%s) · 역할 %s · 신원 출처 %s%s" % (md_cell(name), 코드 스팬(login), role, REQUESTER_SOURCES[source], 꼬리)`. 코드 스팬은 로그인 안의 가장 긴 백틱 열보다 하나 긴 백틱으로 감싸고, 로그인이 백틱으로 시작하거나 끝나면 안쪽에 공백 하나를 둔다(CommonMark 코드 스팬 규칙). 이름은 `md_cell(name, newline=" ")`.

- [ ] **Step 1: 실패하는 시험을 쓴다.** `RequesterLine(unittest.TestCase)`, `page(...)` 도우미(이 파일의 기존 `PinsMdInput` 도우미)에 `requester=` 를 넘긴다:
  - `test_tailnet_header_line`: `RequestIdentity("Alice Kim","alice@example.com","editor","tailnet-header")` → 그 줄이 정확히 `"요청자: Alice Kim(`alice@example.com`) · 역할 editor · 신원 출처 테일넷 헤더(이 기기에 로그인한 테일넷 계정) — 이 요청으로 쓰면 이 사람으로 기록된다 · 내가 일하는 사용자가 아니면 쓰지 말고 사용자에게 토큰을 요청한다(`limn token create <인스턴스>`)"`.
  - `test_each_source_label_and_tail`: 다섯 출처 각각 `REQUESTER_SOURCES[src]` 를 담고, 사람 셋은 `REQUESTER_PERSON_TAIL`, 에이전트 둘은 `REQUESTER_AGENT_TAIL` 로 끝난다.
  - `test_token_line_names_the_agent_login`: 토큰 주체 → `"요청자: reviewer(`agent:reviewer`) · 역할 agent · 신원 출처 토큰 — 이 요청으로 쓰면 에이전트로 기록된다"`.
  - `test_no_requester_is_the_disk_line`: `requester=None`, port 18999 → 줄이 `REQUESTER_DISK % "http://127.0.0.1:18999"` 이고, 출력 어디에도 `"역할 "` 이 없다.
  - `test_line_follows_the_updated_line_once`: 단일 문서와 다중 문서(`docs=` 둘) 모두, `요청자:` 로 시작하는 줄이 정확히 하나이고 `갱신:` 줄 바로 다음이며, 그다음 줄은 빈 줄이다.
  - `test_hostile_name_and_login_stay_on_one_line` (Review Focus 4): 이름 `"A|B\nC"`, 로그인 `"a`b"` → 줄에 `"A\\|B C"` 와 ``"``a`b``"`` 가 있고, 출력의 `요청자:` 줄 수가 1, 그 줄에 줄바꿈이 없다.
- [ ] **Step 2:** `uv run pytest -q src/limn/pins/tests/test_render.py -k RequesterLine` → FAIL.
- [ ] **Step 3: 구현.** `pins_md_text` 에서 `갱신:` 줄을 더한 바로 다음에 `out.append(requester_line(page.requester, loopback_base))`. `PinsMdInput` docstring에 `requester` 를 적는다(None = 디스크 사본).
- [ ] **Step 4:** 같은 명령 → PASS.
- [ ] **Step 5: 기존 시험 맞추기.** `uv run pytest -q -x` 로 깨지는 시험을 모은다. 디스크·HTTP 머리말을 바이트로 비교하는 시험은 `REQUESTER_DISK` 줄(이 단계에서는 HTTP도 아직 디스크 줄)을 기대값에 더하거나, `test_access.py::test_pins_md_matches_the_v01_rendering` 처럼 더한 줄을 `lines.remove(...)` 로 지우는 기존 방식으로 맞춘다. 계약 스냅샷은 `LIMN_RECORD_SNAPSHOT=1 uv run pytest -q tests/contracts/test_contract_snapshot.py` 로 다시 쓰고, `git diff --stat tests/data/` 와 `git diff tests/data/ | grep '^[-+]' | grep -v '요청자: ' | grep -v '^[-+][-+]'` 가 요청자 줄 말고는 아무것도 바뀌지 않았음을 보인다.
- [ ] **Step 6:** `uv run pytest -q` 통과.
- [ ] **Step 7: 커밋** `feat(pins): pins.md names its requester, the disk copy says it has none`.

### Task 3: `GET /pins.md` 에 요청의 신원을 넘기기

**Files:**
- Modify: `src/limn/pins/listing/markdown.py` (`PinMarkdown.current_text`)
- Modify: `src/limn/pins/listing/http.py` (`markdown`)
- Modify: `src/limn/pins/listing/routes.py` (`get`)
- Modify: `src/limn/pins/application.py` (`assemble_pins`, `pin_route_bundle`)
- Modify: `src/limn/server.py` (`assemble_pins(...)` 호출)
- Test: `src/limn/pins/tests/test_render.py` (새 클래스 `PinsMdRequester(AccessBase)`, `PinsMdInstructions` 옆)

**Interfaces:**
- Consumes: Task 1 `request_identity`, `RequestIdentity`; Task 2 `PinsMdInput.requester`, 상수들.
- Produces:
  - `PinMarkdown.current_text(self, base: str, requester: RequestIdentity) -> str` — `render_pins_md_text(dataclasses.replace(self.pins_md_input(self.deps.snapshot_pins(), base), requester=requester))`. `pins_md_text(pins, base)` 와 `pins_md_input(pins, base)` 의 시그니처는 그대로 두어, 디스크를 쓰는 경로가 요청자를 받을 수 없게 한다.
  - `http.markdown(app: ListingApp, base: str, requester: RequestIdentity) -> str`
  - `routes.get(request, app, remote_base_for, request_identity: Callable[[Principal], RequestIdentity])` — `/pins.md` 분기가 `request_identity(request.principal)` 를 넘긴다.
  - `assemble_pins(..., request_identity: Callable[[Principal], RequestIdentity], ...)` — 기본값 없이 필수. `pin_route_bundle(app, editing, remote_base_for, request_identity)`.
  - `server.py`: `request_identity=lambda principal: access.request_identity(principal, settings().access.auth)`.

- [ ] **Step 1: 실패하는 시험을 쓴다.** `PinsMdRequester(AccessBase)`, 핀 하나를 더한 뒤(`self.add()` 또는 `pin_id`) `self.call("GET", "/pins.md", ...)` 의 `요청자:` 줄을 읽는 도우미 `requester_of(md) -> str`:
  - `test_tailnet_header_request` (이슈 완료 기준): `headers=ALICE` → Task 2 `test_tailnet_header_line` 의 줄 그대로.
  - `test_token_request` (완료 기준): `token_create(state, "reviewer")` 의 토큰 → `"요청자: reviewer(`agent:reviewer`) · 역할 agent · 신원 출처 토큰 — 이 요청으로 쓰면 에이전트로 기록된다"`.
  - `test_headerless_loopback_request` (완료 기준): 헤더 없음 → `"요청자: 로컬/에이전트(`local`) · 역할 agent · 신원 출처 헤더 없는 루프백(폐지 예정)" + REQUESTER_AGENT_TAIL`.
  - `test_local_owner_request`: `set_config(auth="local", agent_loopback=False, local_user="alice")` → `"요청자: alice(`alice`) · 역할 owner · 신원 출처 로컬 소유자(--auth local 의 루프백 요청)" + REQUESTER_PERSON_TAIL`.
  - `test_proxy_header_request`: `set_config(auth="trusted-proxy", agent_loopback=False)`, `headers={"X-Forwarded-User": "carol@example.com", "X-Forwarded-Preferred-Username": "Carol Lee"}` → `"요청자: Carol Lee(`carol@example.com`) · 역할 editor · 신원 출처 프록시 헤더(인증 프록시가 보낸 사용자)" + REQUESTER_PERSON_TAIL`.
  - `test_viewer_role_is_shown`: `member_add(state, "alice@example.com", "viewer")` 뒤 `headers=ALICE` → 줄에 `"역할 viewer"`.
  - `test_each_request_sees_only_itself` (Review Focus 1): 같은 시험 안에서 `ALICE`, `BOB`, 헤더 없음 순으로 부르면 각 줄이 자기 로그인만 담고 다른 둘의 로그인을 담지 않는다.
  - `test_disk_copy_never_holds_the_requester` (Review Focus 2): `self.pin_id(ALICE)` 로 쓴 뒤 `ps.APP.C.pins_md.read_text()` 의 `요청자:` 줄이 `REQUESTER_DISK % "http://127.0.0.1:18999"` 이고, 파일 전체에 `"alice@example.com"` 이 없다. 같은 순간 `GET /pins.md`(`ALICE`)는 그 로그인을 보인다.
  - `test_tailnet_agent_request_is_the_loopback_agent` (Review Focus 3): `set_config(tailnet_agent=True)`, `headers={"Host": TS_HOST, "X-Forwarded-For": "100.64.0.9"}` → 헤더 없는 루프백 줄.
  - `test_unreadable_people_shows_viewer` (Review Focus 5): `ps.APP.C.people_file.write_text("{", encoding="utf-8")` 뒤 `headers=ALICE` → `"역할 viewer"`.
  - `test_pins_md_is_not_stored`: `GET /pins.md` 응답 헤더 `Cache-Control` 이 `no-store`.
- [ ] **Step 2:** `uv run pytest -q src/limn/pins/tests/test_render.py -k PinsMdRequester` → FAIL(디스크 줄이 나온다).
- [ ] **Step 3: 구현** 위 Interfaces 그대로. `assemble_pins` docstring에 `request_identity` 한 줄을 더한다.
- [ ] **Step 4:** 같은 명령 → PASS. 스냅샷은 `LIMN_RECORD_SNAPSHOT=1` 로 다시 쓰고, 바뀐 것이 `GET /pins.md` 단계의 `요청자:` 줄(디스크 줄 → 헤더 없는 루프백 줄)뿐인지 Task 2 Step 5의 `git diff` 필터로 확인한다.
- [ ] **Step 5:** `uv run pytest -q`, `uv run python tools/check_boundaries.py`, `uv run python tools/check_types.py`, `uv run python tools/check_fitness.py` 통과. 적합도 기준선(`tools/fitness-baseline/`)이 늘면 늘린 까닭을 커밋 메시지에 적는다.
- [ ] **Step 6: 커밋** `feat(pins): GET /pins.md shows the identity its request is recorded as`.

### Task 4: 안내 두 구절을 조건부로 고쳐 쓰기

**Files:**
- Modify: `src/limn/pins/listing/render.py` (`pins_md_text` 의 닫기 안내, `REPLY_GUIDANCE`)
- Modify: `src/limn/security/tests/test_access.py` (`v03_close_line` 의 `replace` 사슬, v0.1 대조)
- Test: `src/limn/pins/tests/test_render.py` (`PinsMdInstructions` 에 시험 둘)

새 구절은 spec §설계 3 그대로다:

- 닫기 안내: `"테일넷 주소로 닫는 에이전트는 요청이 사람 신원을 달고 가므로 본문에 `\"review\":true` 를 넣는다"` → `"머리말 '요청자:' 줄의 신원 출처가 사람 신원(테일넷 헤더·프록시 헤더·로컬 소유자)이면 그 사람이 내가 일하는 사용자일 때만 닫고 본문에 `\"review\":true` 를 넣는다(아니면 닫지 말고 토큰을 요청한다)"`
- `REPLY_GUIDANCE`: `"(테일넷 주소로 닫을 때 `\"review\":true` 를 넣는 경우, `--auth local` 의 헤더 없는 curl)는 답글 본문에 `\"reopen\":false` 를 넣는다"` → `"('요청자:' 줄의 신원 출처가 테일넷 헤더·프록시 헤더·로컬 소유자)는 그 사람이 내가 일하는 사용자일 때만 답글을 달고 본문에 `\"reopen\":false` 를 넣는다"`

- [ ] **Step 1: 실패하는 시험을 쓴다.**
  - `test_close_guidance_writes_as_a_person_only_for_the_user`: 디스크 `pins.md` 의 `처리한 핀은 닫는다` 줄이 새 닫기 구절을 담고, 옛 구절 `"테일넷 주소로 닫는 에이전트는"` 을 담지 않는다. 줄의 시작은 `"처리한 핀은 닫는다 — "` 그대로다.
  - `test_reply_guidance_replies_as_a_person_only_for_the_user`: `REPLY_GUIDANCE` 가 `"답글(0.2.2): "` 로 시작하고 새 구절을 담으며 `"테일넷 주소로 닫을 때"` 를 담지 않는다. 그 줄이 `TOKEN_GUIDANCE` 줄 바로 다음이다.
- [ ] **Step 2:** `-k "person_only_for_the_user"` → FAIL.
- [ ] **Step 3: 구현.** 두 문자열만 바꾼다. 줄의 시작과 다른 구절은 바이트 그대로 둔다.
- [ ] **Step 4:** `test_access.py` 의 v0.1 대조: `v03_close_line` 에 옛 닫기 구절 → 새 구절 `replace` 를 하나 더하고(이전 판 변경과 같은 방식), `lines.remove(md_render.REPLY_GUIDANCE)` 는 그대로 둔다. Task 2에서 더한 요청자 줄 제거도 여기서 확인한다.
- [ ] **Step 5:** 스냅샷을 다시 쓰고 `git diff tests/data/ | grep '^[-+]' | grep -v '^[-+][-+]'` 의 바뀐 줄이 두 구절을 담은 줄뿐인지 본다. `uv run pytest -q` 통과.
- [ ] **Step 6: 커밋** `feat(pins): write as a person only for the user the agent works for`.

### Task 5: 문서·SKILL·ADR

**Files:**
- Modify: `docs/handbook/api.md`, `docs/handbook/domain.md`, `skill/SKILL.md`, `skill/SKILL.ko.md`, `docs/adr/index.md`
- Create: `docs/adr/NNNN-pins-md-requester-line.md` (`NNNN` = 0056, Task 0 Step 4에서 확인)
- Modify (조건부): `CHANGELOG.md`

- [ ] **Step 1: api.md.**
  - §인증 아래(§pins.md 안내 줄 앞)에 `### pins.md 요청자 줄` 을 둔다: 자리(`갱신:` 다음, 한 번), 모양, 출처 표(spec §설계 1의 표), 두 꼬리, 디스크 줄(spec §설계 2), 보안 규칙(spec §설계 6: 요청 주체에게만, `no-store`, 렌더 캐시나 ETag를 붙이면 요청자별로 가른다, 디스크 사본에는 요청자 값이 닿는 경로가 없다). ADR 결정 절을 짧게 인용하되 본문만으로 완결한다.
  - §pins.md 형식 §머리줄에 항목 하나: `갱신:` 다음 줄은 `요청자:` 줄이다(§pins.md 요청자 줄).
  - §원격 에이전트 진입점: "바뀌는 것은 close 예시의 base URL뿐이다"를 "바뀌는 것은 base URL과 요청자 줄이다"로 고치고, 토큰 없는 테일넷 닫기 문장에 "그 신원은 그 기기에 로그인한 테일넷 계정이지 기기 앞의 사람이 아니다. 요청자 줄의 사람이 내가 일하는 사용자일 때만 쓴다"를 넣는다. 디스크 사본 항목에 요청자 없음 줄을 적는다.
  - §답글이 핀을 다시 여는 규칙의 "토큰 없이 사람 신원으로 보내는 에이전트" 항목과 §검토 대기 표의 닫기 행에 같은 조건을 넣는다.
  - §pins.md 안내 줄의 "실행 정본" 줄에 `request_identity`·`RequestIdentity`(`security/access.py`)와 `requester_line`·`REQUESTER_*`(`render.py`)를 더한다.
- [ ] **Step 2: domain.md** §핀의 상태와 전이 닫기 표의 `"review": true` 권고에 같은 조건을 넣는다.
- [ ] **Step 3: SKILL 두 벌.** §Authentication/§인증의 "From another machine"/"다른 머신에서는" 항목에: 쓰기 전에, 쓸 때와 같은 인증으로 `GET <base>/pins.md` 의 `요청자:` 줄을 읽는다. 그 줄은 내 요청이 누구로 기록되는지(이름·로그인·역할·신원 출처)를 말한다. 출처가 사람 신원(`테일넷 헤더`·`프록시 헤더`·`로컬 소유자`)인데 그 사람이 내가 일하는 사용자가 아니면(예: 다른 사람 계정으로 테일넷에 로그인한 공용 기기) 쓰지 말고 토큰을 요청한다. 디스크 사본은 `요청자: 없음(디스크 사본)` 이다. §What you may do/§해도 되는 것의 닫기 항목, 6단계의 닫기·답글 항목에 "요청자 줄이 내가 일하는 사용자일 때만"을 넣는다. 영어판은 한국어 줄 문구를 원문 그대로 인용한다.
- [ ] **Step 4: ADR.** `docs/adr/NNNN-pins-md-requester-line.md` 를 `제안` 으로 쓴다: D1 요청자 줄, D2 디스크 줄과 닿는 경로가 없는 구조, D3 사람 신원 쓰기의 조건(두 구절의 제자리 고쳐 쓰기, SKILL·api·domain), 버린 대안(인증 줄 끝 구절, 디스크 줄 없음, 조건만 덧붙이기, 안 C). 형식은 `docs/adr/` 의 최근 ADR과 `arch-design` 스킬 `references/adr.md` 를 따른다. `docs/adr/index.md` 에 한 행을 더한다.
- [ ] **Step 5: CHANGELOG.** 머지된 `main` 의 `CHANGELOG.md` 맨 위가 아직 릴리스되지 않은 절이면 거기에 "Added: `GET /pins.md` 의 `요청자:` 줄 · Changed: 사람 신원 쓰기의 두 안내 구절"을 더한다. 맨 위가 릴리스된 판이면 고치지 않고 PR 설명에 같은 요약을 적는다(CHANGELOG는 workflow.md §릴리스의 릴리스 커밋이 쓴다).
- [ ] **Step 6:** `uv run pytest -q tests/architecture/` 와 SKILL을 읽는 시험(`uv run pytest -q src/limn/pins/tests/test_render.py`) 통과. 네 문서와 `render.py` 의 문구가 같은 조건(사람 신원 출처 셋, "내가 일하는 사용자일 때만", "토큰을 요청한다")을 말하는지 `grep -n "요청자" docs/handbook/api.md docs/handbook/domain.md skill/SKILL.md skill/SKILL.ko.md` 로 대조한다.
- [ ] **Step 7: 커밋** `docs: the requester line in api.md, domain.md, SKILL and ADR-NNNN`.

### Task 6: 전체 검증과 실서버 확인

**Files:** 없음(검증)

- [ ] **Step 1:** CLAUDE.md §검증 목록을 위에서부터 모두 돌린다(`uv run pytest -q -rs` … `uv run python tools/strict_ratchet.py`). 하나라도 실패하면 고치고 처음부터 다시 돌린다.
- [ ] **Step 2: 실서버.** 체크아웃의 서버를 시험용 원고로 루프백 임의 포트에 띄우고(`uv run python -m limn serve …`, 상태 폴더는 `~/scratch/limn-540-<날짜>/`), `curl -s` 로 세 경우의 `GET /pins.md` 머리말 일곱 줄을 읽는다: 헤더 없음, `-H 'Tailscale-User-Login: alice@example.com' -H 'Tailscale-User-Name: Alice Kim'`, `-H "Authorization: Bearer <limn token create --state-dir 로 만든 토큰>"`. 디스크의 `pins.md` 도 읽는다. 네 출력을 PR 설명에 붙인다. 서버는 끝나면 내린다.
- [ ] **Step 3:** `git diff --name-status origin/main...HEAD -- ':(glob)docs/adr/[0-9][0-9][0-9][0-9]-*.md'` 에 `A` 가 아닌 줄이 없다(동결 ADR을 건드리지 않았다).
- [ ] **Step 4:** 마지막 커밋을 독립 Codex 세션에서 리뷰한다(`codex exec … < /dev/null`, 전역 지침의 GitHub MCP 끄기 두 줄 포함). 지적을 반영하고 다시 1단계.
- [ ] **Step 5:** PR을 열고(머지하지 않는다) 소유자 확인을 받는다. 승인되면 ADR을 `승인됨` 으로 올리는 커밋을 마지막에 두고 머지한다.
