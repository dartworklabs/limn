# 소유자가 뷰어에서 테일넷 사용자를 들이고 뺀다 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 소유자가 뷰어 패널에서 같은 테일넷의 사용자를 보고, 이 인스턴스에 들이고, 역할을 정하고, 빼는 일을 재시작 없이 한다.

**Architecture:** 상태 디렉터리의 새 파일 `access.json`이 플래그 하나(`managed`)를 들고, 켜져 있으면 `people.json`이 입장의 정본이 된다. `admit()`에 그 플래그를 보는 분기를 **맨 앞에** 더하고, 플래그가 꺼져 있거나 파일이 없으면 오늘의 `--allow`·`--members-only` 판정이 글자 그대로 돈다. 멤버 쓰기는 `security/people.py`의 잠금 없는 순수 편집 + 잠금을 한 번 잡는 트랜잭션 둘로 갈라, 화면(HTTP)과 `limn member`(CLI)가 같은 연산을 쓴다. 테일넷 후보 목록은 tailscaled LocalAPI를 표준 라이브러리로 읽고, 실패는 "목록 없음 + 이유"다.

**Tech Stack:** Python 표준 라이브러리만(`http.client`·`socket`·`json`·`base64`·`fcntl`), 뷰어는 TypeScript → Rollup으로 지어 커밋하는 `dist/viewer.js`.

**Spec:** [docs/superpowers/specs/2026-11-22-viewer-access-management-design.md](../specs/2026-11-22-viewer-access-management-design.md) — 소유자 승인 2026-11-22.

## Global Constraints

- 서버 런타임은 **표준 라이브러리만** 쓴다(`dependencies = []`). `tailscaled`는 있으면 쓰고 없으면 없는 것으로 둔다 — 설치·실행 조건에 들어가지 않는다.
- HTTP 경로·JSON 필드·상태 이름·`reason` 코드는 **더하기만** 한다. 기존 `error` 문장은 글자 하나 바꾸지 않는다.
- 신원·입장·역할 **판단과 비교**는 `src/limn/security/access.py` 안에만 있다. 역할 `Literal`과의 비교를 기능 슬라이스·뷰어 라우트에 쓰지 않는다.
- 알 수 없는 경로는 기본 거부(`check_read`·`post_operation`). 디스패처 등록만으로 권한이 생기지 않는다.
- 상태 파일은 `atomic_write` + `store_lock`을 거쳐서만 쓰고 모드는 `0600`이다. `store_lock`은 **중첩되지 않는다**.
- GET은 영속 상태를 바꾸지 않는다.
- `tools/check_fitness.py`의 기준선은 **내려가기만** 한다. `security/people.py`의 `isinstance` 기준선 11이 상한이므로 새 코드에 `isinstance`를 쓰지 않는다. 새 모듈은 basename이 역할 낱말을 담아야 하고(`*_store.py`→`persistence`, `*_service.py`→`service`, `routes.py`·`http.py`→`http`, `values.py`→`model`) 위반 수가 0이어야 한다.
- 코드·주석·docstring·커밋 메시지·CLI help는 **영어**, Handbook은 **한국어**. `README.md`↔`README.ko.md`와 `skill/SKILL.md`↔`skill/SKILL.ko.md`는 쌍이다.
- 실제 이메일·홈 경로·호스트 이름을 코드·문서·시험에 넣지 않는다(`alice@example.com`, `box.tail1234.ts.net` 꼴).
- 커밋은 모두 `git commit -s`로 만들고 메시지 끝에 `I agree to the Limn CLA (CLA.md).` 줄을 둔다. 처음부터 단다.
- 돌고 있는 인스턴스 `mac-18352`를 건드리지 않는다. 시험은 임시 상태 디렉터리로 한다.

## Review Focus

spec이 함축하지만 어느 Task의 시험도 짚지 않을 수 있는 입력 다섯. 각 줄의 시험을 그 코드를 가진 Task에 넣었다.

- **`access.json`이 `{"version": 2, …}`이거나 `managed`가 `"true"`(문자열)·`1`·`null`이다.** 모르는 판·모르는 타입은 `"unusable"`이어야 한다 — `False`로 접히면 관리 중인 인스턴스가 조용히 오늘 동작으로 돌아간다. → Task 1.
- **전환 요청 본문이 같은 로그인을 두 번, 또는 공백·대문자 차이로 담는다.** 마지막 것이 이기든 거부하든 한 가지로 정해져야 하고, 중복 때문에 줄이 둘 생기면 안 된다. → Task 4.
- **전환 중에 `limn member`가 같은 파일을 쓴다.** 잠금이 하나뿐이므로 둘 중 하나가 기다려야 하고, 끝난 뒤 두 변경이 모두 남아 있거나 뒤엣것이 목표 상태를 적어야 한다. → Task 4.
- **LocalAPI가 200에 JSON이 아닌 본문, 또는 아주 큰 본문을 준다.** 맥 서브프로세스 함정과 같은 모양이다 — 예외를 올리지 않고 "목록 없음 + 이유"여야 하고, 본문 상한을 넘으면 읽기를 멈춰야 한다. → Task 6.
- **`people.json`을 쓸 수 없는데 `access.json`은 `managed`다.** 역할 조회가 아무도 멤버로 보지 않으므로(`is_member`가 `PeopleUnreadable`에 `False`) 헤더로 들어온 사람이 전원 막힌다. 이것이 의도한 닫힌 상태임을 못박고, 거절 이유가 어느 파일 때문인지 말해야 한다. → Task 2.

---

### Task 1: `access.json` — 상태와 닫힌 값

**Files:**
- Create: `src/limn/security/access_store.py`
- Modify: `src/limn/security/values.py`, `src/limn/runtime/paths.py`, `src/limn/runtime/config.py`, `src/limn/runtime/resources.py`
- Test: `src/limn/security/tests/test_access_store.py` (새)

**Interfaces:**
- Produces: `limn.security.values.ManagedAccess: TypeAlias = Literal["managed", "not-managed", "unusable"]`
- Produces: `limn.security.access_store.AccessFile` — frozen dataclass `(managed: ManagedAccess, at: str | None, by: str | None, reason: str | None)`
- Produces: `read_access(path: Path) -> AccessFile` — 없는 파일은 `("not-managed", None, None, None)`; 읽히고 `{"version": 1, "managed": bool}` 모양이면 그 플래그; 그 밖(읽기 실패·UTF-8 JSON 아님·`version`이 1 아님·`managed`가 `bool` 아님)은 `("unusable", None, None, reason)`
- Produces: `access_text(managed: bool, at: str, by: str) -> str` — `{"version":1,"managed":…,"managed_at":…,"managed_by":…}`, 한 칸 들여쓰기, 줄바꿈으로 끝
- Produces: `write_access(path: Path, managed: bool, at: str, by: str) -> None` — `atomic_write(..., mode=0o600)`. **잠금을 잡지 않는다**(부르는 쪽이 `store_lock(state, "people")`을 들고 있다). **첫 인자는 `read_access`와 같이 파일 경로다** — 상태 디렉터리가 아니다. 둘 다 `Path`라서 타입 검사가 뒤바뀜을 못 잡고, 호출자가 손에 든 값은 `RunConfig.access_file`(파일)이다
- Produces: `limn.runtime.paths.ACCESS_FILE = "access.json"`, `RunConfig.access_file` property, `RuntimeResources.access_cache` (`FileCache[AccessFile]`)

- [ ] **Step 1: 실패하는 시험을 쓴다** (`test_access_store.py`, 클래스 `ReadAccess`, `WriteAccess`)

```python
# ReadAccess
def test_absent_file_is_not_managed(self):        # read_access(tmp/"access.json").managed == "not-managed"
def test_managed_true(self):                      # {"version":1,"managed":true} -> "managed", at/by 보존
def test_managed_false(self):                     # {"version":1,"managed":false} -> "not-managed"
def test_unknown_version_is_unusable(self):       # {"version":2,"managed":true} -> "unusable", reason에 파일 이름
def test_managed_not_bool_is_unusable(self):      # "true" / 1 / None 세 값 모두 "unusable"
def test_broken_json_is_unusable(self):           # 잘린 본문, 빈 파일, UTF-8 아님
def test_not_an_object_is_unusable(self):         # [] 와 "x"
def test_unreadable_file_is_unusable(self):       # chmod 0o000 (root 아닐 때만)
# WriteAccess
def test_write_then_read_round_trips(self):       # write_access -> read_access 가 같은 managed/at/by
def test_mode_is_0600(self):                      # stat.S_IMODE == 0o600
def test_text_ends_with_newline(self):            # access_text(...).endswith("\n")
```

- [ ] **Step 2: 실패를 본다**

Run: `uv run pytest -q src/limn/security/tests/test_access_store.py`
Expected: FAIL — `ModuleNotFoundError: limn.security.access_store`

- [ ] **Step 3: 구현한다** — 위 Interfaces 그대로. `read_access`의 갈라치기는 `limn.security.people.load_people`의 "없는 파일 / 있는데 못 쓰는 파일" 판단과 **같은 모양**으로 쓰고, docstring에 그렇게 적는다. **`isinstance`를 한 번도 쓰지 않는다** — 이 모듈은 기준선에 없는 새 파일이라 위반 수가 0이어야 한다. 파싱한 JSON의 타입 확인은 `type(d) is dict` 와 `value is True or value is False` 로 한다(`isinstance`가 아니라 `type(...) is ...`). `RunConfig.access_file`은 `people_file`과 같은 모양의 property. `RuntimeResources`에 `access_cache`를 `roles_cache`·`tokens_cache` 옆에 더한다.

- [ ] **Step 4: 통과를 본다**

Run: `uv run pytest -q src/limn/security/tests/test_access_store.py && uv run python tools/check_fitness.py && uv run python tools/check_boundaries.py`
Expected: PASS — 세 명령 전부

- [ ] **Step 5: 커밋** — `feat(security): read and write the instance access flag`

### Task 2: `admit()`의 관리 분기

**Files:**
- Modify: `src/limn/security/access.py` (`admit`), `src/limn/security/application.py` (`RequestGuards.admit`, `SecurityApplication`), `src/limn/server.py` (조립), `src/limn/runtime/startup.py` (기동 `auth` 로그 줄)
- Test: `src/limn/security/tests/test_access.py`, `src/limn/security/tests/test_access_paths.py`, `tests/support/helpers_access.py`

**Interfaces:**
- Consumes: Task 1의 `ManagedAccess`, `read_access`, `access_cache`
- Produces: `access.admit(p, host, headers, settings, roles, managed: Callable[[], ManagedAccess]) -> None` — **기본값 없는 여섯째 매개변수**
- Produces: `SecurityApplication.managed_access() -> ManagedAccess` (캐시에서 투영), `RequestGuards.managed: Callable[[], ManagedAccess]`
- Produces: **못 쓰는 `access.json`의 stderr 경고 한 번** — spec §A가 요구한다. `people.UnreadableWarning`(`people.py:82`)과 같은 모양으로 프로세스가 하나를 소유하고(`RuntimeResources`에 `access_warning`을 `people_warning` 옆에), 한 번 깨짐에 한 줄만 찍고 정상 읽기가 다시 무장한다. Task 1의 `access_store.py` docstring이 "the server's warning shows it"이라고 약속해 둔 자리가 이것이다

- [ ] **Step 1: 실패하는 시험을 쓴다** (`test_access.py`, 클래스 `ManagedAdmission`, `UnmanagedUnchanged`)

```python
# UnmanagedUnchanged — access.json 이 없을 때 오늘의 판정이 글자 그대로다
def test_no_list_admits_everyone(self):           # allow 없음·members_only 꺼짐 -> ALICE 200
def test_allow_only_refuses_outsider(self):       # allow={A} -> BOB 403 reason "not_allowed"
def test_members_only_admits_member_or_allow(self)# members_only + member(B) + allow={A} -> 둘 다 200, CAROL 403 "not_member"
# ManagedAdmission — access.json 이 managed 일 때
def test_member_is_admitted(self):                # people.json 에 B -> BOB 200
def test_non_member_is_refused(self):             # CAROL 403 reason "not_member" (기존 코드·기존 안내 화면)
def test_allow_is_ignored(self):                  # allow={A}, people.json={B} -> ALICE 403, BOB 200
def test_members_only_is_ignored(self):           # members_only 켜짐이어도 같은 결과
def test_empty_people_admits_nobody(self):        # people.json 없음 -> ALICE 403, CAROL 403
def test_token_and_local_owner_still_admitted(self)
def test_unusable_access_refuses_header_people(self)  # 403 reason "access_unreadable"; 토큰은 200
def test_unusable_people_with_managed_refuses(self)   # Review Focus 5: 403, 이유가 people 파일을 가리킨다
def test_change_applies_without_restart(self):    # 같은 서버에 두 요청 사이에 people.json 을 고치면 두 번째가 달라진다
```

- [ ] **Step 2: 실패를 본다**

Run: `uv run pytest -q src/limn/security/tests/test_access.py -k "Managed or Unmanaged"`
Expected: FAIL — `admit() missing 1 required positional argument: 'managed'`

- [ ] **Step 3: 구현한다** — spec §B 그대로. `managed()`가 `"managed"`면 `is_member(roles(), login)`만 보고, `"unusable"`이면 새 코드 `access_unreadable`로 거절하고, `"not-managed"`면 기존 두 분기로 떨어진다. **기존 두 분기의 글자를 바꾸지 않는다.** `helpers_access.py`의 `configure`/`reset_access`에 `managed` 기본값(`"not-managed"`)을 더해 기존 호출 자리가 오늘 동작을 유지하게 한다. `startup.py`의 `auth` 로그 줄에 `managed` 상태를 더하고, `managed`인데 `--allow`나 `--members-only`가 주어졌으면 "그 인자는 무시되고 access.json이 정본"이라고 적는다.

- [ ] **Step 4: 통과를 본다**

Run: `uv run pytest -q src/limn/security/ && uv run python tools/check_types.py`
Expected: PASS

- [ ] **Step 5: 커밋** — `feat(security): admit members from the people file when the instance is managed`

### Task 3: 멤버 쓰기 기본 연산과 마지막 owner

**Files:**
- Modify: `src/limn/security/people.py` (순수 편집 + 트랜잭션), `src/limn/administration/member_state.py` (얇은 포장)
- Test: `src/limn/security/tests/test_people_store.py` (새), `src/limn/administration/tests/test_cli.py`

**Interfaces:**
- Produces (in `security/people.py`, 모두 잠금을 잡지 않는다):
  - `MemberChange` — frozen dataclass `(action: str, details: Json)`, 감사 줄 하나
  - `add_member(rows: list[Row], login: str, role: str, name: str | None) -> tuple[Row, MemberChange]`
  - `set_member_role(rows: list[Row], login: str, role: str) -> tuple[Row | None, MemberChange | None]`
  - `remove_member(rows: list[Row], login: str) -> tuple[Row | None, MemberChange | None]`
  - `LastOwner` — frozen dataclass, 마지막 owner를 빼거나 내리려 할 때 위 두 함수가 **올리는** 예외(값으로 돌려주지 않는다 — 부르는 쪽이 떨어뜨리면 보호가 사라진다)
  - `people_transaction(state: Path, step: Callable[[list[Row]], T], audit: AuditSink) -> T` — 잠금을 **한 번** 잡고 읽고 `step`을 돌리고 `atomic_write`하고 같은 잠금 안에서 감사 줄을 적는다
- Produces (unchanged public surface in `administration/member_state.py`): `member_add`, `member_set_role`, `member_remove`, `load_people_file` — 이름·반환값·`ValueError`/`None` 규약 그대로

- [ ] **Step 1: 실패하는 시험을 쓴다** (`test_people_store.py` 클래스 `PureMemberEdits`, `LastOwnerRule`, `Transaction`; `test_cli.py` 클래스 `MemberCliLastOwner`)

```python
# PureMemberEdits — rows 를 제자리에서 고친다
def test_add_appends_with_role_and_name(self)     # name 없으면 login 의 @ 앞
def test_add_rejects_existing_login(self)         # ValueError
def test_add_rejects_invalid_login_and_role(self) # valid_login / is_role
def test_set_role_returns_none_when_absent(self)
def test_set_role_same_role_makes_no_change(self) # MemberChange is None
def test_remove_returns_none_when_absent(self)
# LastOwnerRule — 두 문을 함께 묶는다
def test_remove_last_owner_raises(self)           # LastOwner
def test_demote_last_owner_raises(self)           # set_member_role(owner -> editor)
def test_remove_one_of_two_owners_is_allowed(self)
def test_remove_non_owner_is_allowed(self)
# Transaction
def test_transaction_writes_and_audits_in_order(self)
def test_transaction_refuses_unusable_people_file(self)   # ValueError, 파일은 그대로
def test_transaction_holds_the_lock_while_the_step_runs(self)
    # step 안에서 .people.lock 에 flock(LOCK_EX|LOCK_NB) 를 걸어 보면 BlockingIOError 가 난다.
    # 중첩이 안 되는 잠금이므로(platform/files.py), 이 시험이 "step 이 또 잡으면 멎는다"를 못박는다.
# test_cli.py — 소유자 결정으로 바뀐 동작
def test_member_remove_refuses_last_owner(self)   # exit 1, stderr 한 줄
def test_member_role_refuses_demoting_last_owner(self)
def test_add_new_owner_then_remove_old_works(self)
```

- [ ] **Step 2: 실패를 본다**

Run: `uv run pytest -q src/limn/security/tests/test_people_store.py src/limn/administration/tests/test_cli.py -k "Member or LastOwner or Transaction"`
Expected: FAIL — `ImportError: cannot import name 'add_member'`

- [ ] **Step 3: 구현한다** — spec §G 그대로. 지금 `member_state._people_update`가 하는 일을 `people_transaction`으로 옮기고, 세 `member_*` 함수의 몸통에서 편집 부분만 순수 함수로 꺼낸다. `member_state.py`의 공개 함수는 `people_transaction`을 부르는 포장으로 줄이고, CLI 문구(`"%s is already a member - change the role with \`limn member role\`"` 등)는 **그대로** 둔다. `LastOwner`는 `members.py`에서 `limn: ...` 한 줄로, HTTP에서는 Task 5가 `409 last_owner`로 바꾼다. 새 코드에 `isinstance`를 쓰지 않는다.

- [ ] **Step 4: 통과를 본다**

Run: `uv run pytest -q src/limn/security/ src/limn/administration/ && uv run python tools/check_fitness.py && uv run python tools/check_boundaries.py`
Expected: PASS

- [ ] **Step 5: 커밋** — `refactor(security): the people store owns member edits, and the last owner cannot be removed`

### Task 4: 전환 — 목표 상태를 한 잠금 안에서 적는다

**Files:**
- Create: `src/limn/security/access_service.py`
- Test: `src/limn/security/tests/test_access_managed.py` (새)

**Interfaces:**
- Consumes: Task 1의 `write_access`, Task 3의 순수 편집·`people_transaction`
- Produces: `TargetMember` — frozen dataclass `(login: str, role: str)`
- Produces: `apply_managed(state, targets: Sequence[TargetMember], by: Json, managed: bool, now: float, audit) -> ManagedResult` — 한 잠금 안에서 `people.json`을 목표 상태로 맞추고 **그 뒤** `access.json`을 쓴다
- Produces: `ManagedResult` — frozen dataclass `(added, removed, changed: tuple[str, ...], managed: bool)`
- Produces: `LocksOutOwner`, `RoleNotSettable`, `DuplicateTarget` — 거절을 올리는 값
- Produces: `current_admitted(allow: frozenset[str], members_only: bool, rows) -> tuple[str, ...]` (순수) — 전환 화면의 "지금 들어오는 사람"
- Produces: 단건 변경의 서비스 세 개 — `add_one(state, login, role, name, by, audit)`, `set_one_role(state, login, role, by, audit)`, `remove_one(state, login, by, audit)`. 각각 `people_transaction`을 한 번 쓰고 `LastOwner`를 그대로 올린다. **Task 5의 HTTP 싱크는 이 셋과 `apply_managed`만 부른다** — `administration/member_state.py`를 부르지 않는다(경계 검사가 `security/` → 기능 모듈 import 를 거부한다)

- [ ] **Step 1: 실패하는 시험을 쓴다** (`test_access_managed.py`, 클래스 `Transition`, `TransitionRefusals`, `TransitionRaces`)

```python
# Transition
def test_default_target_is_a_no_op(self)          # current_admitted 로 만든 targets -> added/removed/changed 전부 빈
def test_allow_login_without_row_gets_an_editor_row(self)
def test_unchecked_row_is_removed(self)           # member_removed 감사 줄
def test_owner_and_agent_rows_are_preserved_when_absent_from_targets(self)
def test_people_is_written_before_access(self)    # write_access 가 올리면 people 변경은 남고 managed 는 꺼진 채다
def test_applying_twice_is_idempotent(self)
def test_turning_management_off_writes_managed_false(self)
# TransitionRefusals
def test_target_without_the_requesting_owner_refuses(self)   # LocksOutOwner, 파일 둘 다 안 바뀐다
def test_owner_or_agent_role_in_targets_refuses(self)        # RoleNotSettable
def test_duplicate_login_in_targets_refuses(self)            # DuplicateTarget (Review Focus 2)
# TransitionRaces
def test_cli_member_add_during_transition_serializes(self)   # 다른 프로세스의 limn member 와 번갈아, 뒤엣것이 목표 상태 (Review Focus 3)
```

- [ ] **Step 2: 실패를 본다**

Run: `uv run pytest -q src/limn/security/tests/test_access_managed.py`
Expected: FAIL — `ModuleNotFoundError: limn.security.access_service`

- [ ] **Step 3: 구현한다** — spec §C 그대로. 거절은 파일을 열기 **전에** 모두 판정해서 "거절했으면 아무것도 안 바뀐다"를 보장한다. 중복은 거부한다(마지막 것이 이기게 하면 화면이 보인 것과 적히는 것이 갈린다 — WYSIWYS). `TransitionRaces`의 시험은 `subprocess`로 `limn member add`를 돌려 같은 상태 디렉터리를 쓴다.

- [ ] **Step 4: 통과를 본다**

Run: `uv run pytest -q src/limn/security/ && uv run python tools/check_fitness.py`
Expected: PASS

- [ ] **Step 5: 커밋** — `feat(security): one transition writes the member list and the access flag`

### Task 5: 소유자 전용 읽기와 멤버 POST

**Files:**
- Modify: `src/limn/security/access.py` (`check_read`, `OWNER_READS`, `MEMBER_OPERATIONS`, `OWNER_POSTS`, `post_operation`, `READ_PATHS`), `src/limn/security/application.py`, `src/limn/server.py` (`authority_scope` 분기, `merge_routes`), `src/limn/web/handler.py` (`check_read` 호출), `src/limn/viewer/ui_en.json`
- Create: `src/limn/security/routes.py`, `src/limn/security/http.py`
- Test: `src/limn/security/tests/test_access_paths.py`, `test_authority.py`, `src/limn/web/tests/test_errors.py`, `src/limn/security/tests/test_access_http.py` (새)

**Interfaces:**
- Consumes: Task 4의 `apply_managed`·`current_admitted`·`add_one`·`set_one_role`·`remove_one`, Task 1의 `read_access`. **`administration/member_state.py`는 부르지 않는다** — `administration`은 기능 capability이고 그 `__all__`에 멤버 쓰기 함수가 없어, `security/`가 그 모듈에 닿으면 `tools/check_boundaries.py`가 거부한다
- Produces: `access.check_read(path: str, p: Principal) -> None` — **매개변수가 하나 늘었다**; `OWNER_READS = frozenset({"/api/access"})`
- Produces: `access.MEMBER_OPERATIONS: dict[str, str]` — `/api/access/managed`→`access-managed`, `/api/members/add`→`member-add`, `/api/members/role`→`member-role`, `/api/members/remove`→`member-remove`. 네 경로 모두 `OWNER_POSTS`에 든다
- Produces: `security/http.py`의 `access_view(...) -> dict[str, Any]`와 네 POST 동작; `security/routes.py`의 `RouteBundle`
- Produces: `access_view`는 후보 목록을 **주입된 콜러블**로 받는다 — `directory: Callable[[frozenset[str]], TailnetDirectoryView]`, `TailnetDirectoryView`는 `(users: tuple[Json, ...], partial: bool, reason: str | None)`. 이 Task에서 조립은 **"목록 없음 + `reason='directory not wired yet'`"을 돌려주는 대역**을 꽂는다. Task 6이 그 자리에 실제 읽기를 넣는다 — 그래서 Task 5의 시험은 `tailnet.users == []`와 `partial is True`를 기대한다
- Produces: 새 `reason` 코드 — `access_unreadable`(Task 2), `locks_out_owner`, `role_not_settable`, `last_owner`, `not_managed`

- [ ] **Step 1: 실패하는 시험을 쓴다**

```python
# test_access_paths.py — RoleMatrix 에 더한다
def test_access_read_is_owner_only(self)          # owner 200; editor/viewer/agent/token/local-owner 403 "owner_only"
def test_member_posts_are_owner_only(self)        # 네 경로 × 여섯 주체
def test_unregistered_member_path_is_404(self)    # /api/members/promote -> 404 "not_found"
# test_authority.py
def test_member_operation_gets_the_people_scope(self)
def test_pin_authority_cannot_change_members(self)        # invalid_authority
# test_access_http.py
def test_get_access_lists_members_and_args(self)          # 키 순서와 필드 이름
def test_tailnet_block_is_empty_until_wired(self)         # users == [], partial is True, reason 이 있다
def test_member_add_applies_without_restart(self)         # POST 뒤 다음 요청의 admit 이 달라진다
def test_member_post_on_unmanaged_instance_is_409(self)   # "not_managed"
def test_role_owner_or_agent_is_400(self)                 # "role_not_settable"
def test_remove_last_owner_is_409(self)                   # "last_owner"
def test_transition_without_confirm_is_400(self)
def test_transition_locking_out_requester_is_409(self)    # "locks_out_owner"
def test_audit_lines_say_via_http(self)
# test_errors.py
def test_every_served_reason_has_an_english_sentence(self)
```

- [ ] **Step 2: 실패를 본다**

Run: `uv run pytest -q src/limn/security/tests/ src/limn/web/tests/test_errors.py`
Expected: FAIL — `check_read() takes 1 positional argument but 2 were given`

- [ ] **Step 3: 구현한다** — spec §D 그대로. `handler.py`의 `check_read` 호출 자리는 이미 `self.principal`을 들고 있다. `authority_scope()`에 `MEMBER_OPERATIONS.values()` 분기를 더해 people 저장소 범위를 주고(안 더하면 핀 저장소로 조용히 떨어진다), 네 동작의 싱크에서 `require_authority(authority, scope, operation, login)`를 부른다. 확인 문구는 `/api/clear`의 방식 그대로 `{"confirm": "manage access from the viewer"}`. `ui_en.json`에 새 `reason:` 문장 다섯과 새 한국어 UI 문자열을 더한다.

- [ ] **Step 4: 통과를 본다**

Run: `uv run pytest -q src/limn/ && uv run python tools/check_boundaries.py && uv run python tools/check_fitness.py && uv run python tools/check_types.py`
Expected: PASS

- [ ] **Step 5: 커밋** — `feat(security): owner-only access reads and member changes over HTTP`

### Task 6: 테일넷 후보 목록

**Files:**
- Create: `src/limn/platform/tailnet.py`
- Modify: `src/limn/security/http.py` (목록을 응답에 넣는다), `src/limn/server.py` (조립)
- Test: `src/limn/platform/tests/test_tailnet.py` (새)

**Interfaces:**
- Consumes: Task 5의 `directory` 주입 자리 — 이 Task가 대역을 실제 읽기로 바꾸고, `test_tailnet_block_is_empty_until_wired`를 "목록이 오면 그 사용자들이 보인다"로 고친다
- Produces: `TailnetUser` — frozen dataclass `(login: str, name: str, pic: str | None)`
- Produces: `TailnetDirectory` — frozen dataclass `(users: tuple[TailnetUser, ...], partial: bool, reason: str | None)`; `partial`은 **늘 `True`**
- Produces: `read_directory(now: float, timeout: float = 1.0) -> TailnetDirectory` — 실패·시간 초과·`BackendState != "Running"`·비-JSON은 `users=()` 와 `reason`. **예외를 올리지 않는다**
- Produces: `project_users(status: Json, exclude: frozenset[str]) -> tuple[TailnetUser, ...]` (순수) — `User` 맵에서 `LoginName`·`DisplayName`·`ProfilePicURL`만, `valid_login`을 통과하고 `exclude`에 없는 것만, 이름 기준 정렬

- [ ] **Step 1: 실패하는 시험을 쓴다** (`test_tailnet.py`, 클래스 `Projection`, `UnixTransport`, `Failures`)

```python
# Projection (순수)
def test_takes_login_name_and_pic(self)
def test_drops_invalid_logins(self)              # 공백·빈 값·'local'·'agent:x'
def test_drops_excluded_members(self)
def test_sorts_by_name_ignoring_case(self)
def test_partial_is_always_true(self)
# UnixTransport — 가짜 유닉스 소켓 서버
def test_reads_status_over_a_unix_socket(self)
def test_sends_the_local_tailscaled_host_header(self)    # 'Host: local-tailscaled.sock'
def test_sends_no_origin_or_referer(self)                # 하나라도 있으면 tailscaled 는 403
def test_tries_socket_paths_in_order(self)               # /run/tailscale/... -> /var/run/tailscale/... -> /var/run/tailscaled.socket
# Failures — 전부 reason 을 돌려주고 예외를 올리지 않는다
def test_no_socket_anywhere(self)
def test_server_never_answers_times_out(self)            # timeout=0.05
def test_two_hundred_with_non_json_body(self)            # Review Focus 4
def test_body_over_the_limit_stops_reading(self)         # Review Focus 4
def test_backend_state_not_running(self)
def test_http_401_and_403(self)
```

- [ ] **Step 2: 실패를 본다**

Run: `uv run pytest -q src/limn/platform/tests/test_tailnet.py`
Expected: FAIL — `ModuleNotFoundError: limn.platform.tailnet`

- [ ] **Step 3: 구현한다** — spec §E 그대로. 리눅스는 `socket.AF_UNIX` + `http.client.HTTPConnection` 서브클래스, 맥은 `readlink("/Library/Tailscale/ipnport")`로 포트와 `sameuserproof-<포트>`로 토큰을 읽어 `127.0.0.1:<포트>` + HTTP Basic(사용자 빈칸). 맥의 파일은 stale일 수 있으므로 연결 실패를 정상 실패로 다룬다. **서브프로세스를 쓰지 않는다**(맥에서 종료코드 0에 비-JSON이 나온다). 본문 상한과 타임아웃의 값에 이유를 주석 한 줄로 적는다. 값을 몇 초 기억해 연타를 막되 **스레드를 만들지 않는다**.

- [ ] **Step 4: 통과를 본다**

Run: `uv run pytest -q src/limn/platform/ src/limn/security/ && uv run python tools/check_fitness.py`
Expected: PASS

- [ ] **Step 5: 커밋** — `feat(platform): read the tailnet user directory from the local tailscaled`

### Task 7: 화면 후보와 PoC — 소유자가 고른다

**Files:**
- Create: `src/limn/viewer/css/access.css`, `src/limn/viewer/js/access/{state,view-panel,flow}.ts`
- Modify: `src/limn/viewer/index.html`, `assemble.py` (`STYLESHEETS`, 필요한 `LUCIDE` 아이콘), `js/main.ts`, `js/layout/flow.ts`, `js/layout/flow-back.ts`, `js/documents/view-meta.ts`, `types/api.d.ts`, `types/page.d.ts`(생성), `tools/check_viewer_boundaries.mjs`, `ui_en.json`

**Interfaces:**
- Consumes: Task 5의 `GET /api/access`와 네 POST, Task 6의 `tailnet` 필드
- Produces: `body.role-owner` (`/api/meta`의 `me.role`을 따른다 — `/api/people`가 아니다), `<dialog id="access">`

후보 코드는 탐색이다. **곁가지 `poc/access-panel`에서 짓고 이 가지에 머지하지 않는다**([workflow.md](../../handbook/workflow.md) §경로가 달라지는 경우). Task 8은 고른 후보를 이 가지에서 **다시 쓴다** — 후보 커밋을 그대로 옮기지 않는다. 그래서 Task 7과 8이 같은 파일을 적어도 충돌하지 않는다.

- [ ] **Step 1: 후보 셋을 만든다** — 같은 서버에 인자로 고르게 한다(`?access=a|b|c`).
  - **A (추천)**: `[더보기]`에서 열리는 독립 다이얼로그, 멤버와 테일넷 후보를 **두 구획**으로, 전환은 "지금 / 전환 뒤" **두 칸 대조**. 근거: `#trash`와 같은 모양이라 배우는 것이 없고, 두 칸 대조가 안티목표 1을 눈으로 확인시킨다.
  - **B**: 독립 다이얼로그, 멤버와 후보를 **한 목록**에 "멤버" 배지로 합치고, 전환은 **체크박스 한 목록 + 요약 한 줄**.
  - **C**: `[더보기]` 안의 **한 구획**(휴지통처럼 따로 열지 않는다).
- [ ] **Step 2: 네 기기군으로 묶음을 만든다** — `code-ui-poc` 스킬의 `ui_poc.py compare`로 후보마다 ① 바뀐 자리를 **테두리 없이 옅은 반투명 면 + 번호**로 표시한 전후 캡처(데스크톱 1440×900, 휴대폰 390×844·320×720, 태블릿 768×1024·1024×768, 폴더블 344×882·673×841·841×673), ② 번호마다 잰 값이 붙은 차이 목록, ③ 열어 볼 주소. `#more` 진입점의 전후도 같은 묶음에 넣는다. 캡처에 이름을 준다(`7-A` 꼴).
- [ ] **Step 3: 내가 먼저 이미지를 열어 본다** — 번호마다 목록 줄이 있고, 바뀐 것이 표시 없이 남지 않았고, 표시가 잡음 위에 앉지 않았는지. PoC 서버는 `127.0.0.1`에 묶고 `tailscale serve`로 소유자에게 연다.
- [ ] **Step 4: 소유자에게 보이고 고르게 한다** — 선택 창의 선택지가 캡처 이름과 번호를 가리킨다. 고른 뒤 PoC 서버와 프록시를 내리고 그렇게 말한다.
- [ ] **Step 5: 커밋** — 후보 코드는 탐색이므로 **그대로 머지하지 않는다**. 고른 것만 Task 8로 간다.

### Task 8: 고른 화면을 시공한다

**Files:** Task 7의 목록. `src/limn/viewer/dist/viewer.js`(지어서 커밋)
**Test:** `src/limn/viewer/tests/test_viewer_access.py` (새)

- [ ] **Step 1: 실패하는 시험을 쓴다**

```python
def test_entry_point_absent_for_non_owner(self)   # 숨김이 아니라 문서에 없음 (viewer.md §역할에 따른 화면)
def test_panel_controls_absent_for_non_owner(self)
def test_self_row_has_no_remove_control(self)
def test_last_owner_row_has_no_role_or_remove_control(self)
def test_tailnet_section_says_the_list_is_partial(self)
def test_login_input_is_shown_when_the_list_is_empty(self)
def test_escape_and_backdrop_close_the_panel(self)
def test_tab_stays_inside_the_panel(self)
def test_layout_at_four_device_classes(self)      # 넘침·잘림 없음, 줄 높이 마우스 32px·터치 44px
```

- [ ] **Step 2: 실패를 본다**

Run: `uv run pytest -q src/limn/viewer/tests/test_viewer_access.py`
Expected: FAIL

- [ ] **Step 3: 구현한다** — 고른 후보만. `check_viewer_boundaries.mjs`의 `FEATURES`·`ALLOWED`에 `access`를 등록하고, `flow.ts`의 배경 클릭 목록과 `flow-back.ts`의 셀렉터 **두 곳**에 `#access`를 더한다. 진입점은 소유자에게만 JS로 그린다(`LIVE_ELEMENTS` 등재). `css/access.css`는 `tokens.css`의 토큰만 쓰고 **둥근 모서리 + 한쪽 강조선 조합을 쓰지 않는다**.

- [ ] **Step 4: 통과를 본다**

Run: `uv run python tools/page_elements.py && npm run build && uv run pytest -q src/limn/viewer/ && npm run typecheck && npm run lint && npm run boundaries && npm run build:check && npm run format:check && uv run python tools/page_elements.py --check`
Expected: PASS

- [ ] **Step 5: 커밋** — `feat(viewer): an owner manages instance access from the viewer`

### Task 9: ADR-0054, Handbook, README·SKILL, CHANGELOG

**Files:** `docs/adr/0054-access-managed-from-the-viewer.md`(새), `docs/adr/index.md`, `docs/handbook/{api,architecture,operations,viewer,instances,verification,index}.md`, `SECURITY.md`, `README.md`, `README.ko.md`, `skill/SKILL.md`, `skill/SKILL.ko.md`, `CHANGELOG.md`

- [ ] **Step 1: ADR-0054를 쓴다** (`제안`). 머리표에 **ADR-0002 §2 권한 층의 "소유자 전용 작업은 당분간 CLI 수준" 조항을 `부분 대체`**. 결정: D1 `access.json`의 플래그가 입장의 정본을 가른다, D2 전환은 소유자가 보고 누르며 기본값은 무동작, D3 멤버십 = 입장(두 축을 만들지 않는다), D4 관리 중인 인스턴스에서 빈 명단은 "아무도"다, D5 못 쓰는 `access.json`은 fail closed, D6 읽기도 역할로 가른다(`OWNER_READS`), D7 권한 값은 HTTP 문에서만 발급되고 CLI 문은 OS 파일 권한으로 지킨다(비대칭과 그 이유), D8 마지막 owner 보호는 두 문을 묶는다, D9 최초 owner는 CLI만 만든다, D10 테일넷 목록은 LocalAPI의 부분 목록이고 실패는 정상이다. 대안: 자동 흡수, `--allow` 목록만 파일로, 줄에 `admit` 필드, Admin API 자격증명, 서브프로세스. 수치는 spec §실측에서 옮긴다. **ADR-0002·0003·0007 본문은 건드리지 않는다.**
- [ ] **Step 2: Handbook을 고친다**(현재형, 날짜·전후 수치 없이). `api.md` §인증의 입장 표에 관리 모드 행, 새 경로 다섯과 응답 필드, 새 `reason` 코드, `access.json` 형식, 소유자 전용 읽기와 검사 순서. `architecture.md` §불변식 1에 관리 모드와 fail closed, §멈춤 신호에 걸려 설계 판단을 받았다는 사실. `operations.md` §실행 인자에 "관리 모드에서 `--allow`·`--members-only`는 무시된다", 기동 `auth` 로그 줄, **소유자 교체 순서**(새 소유자를 먼저 더한다). §상태 파일 배치는 **두 자리를 모두** 고친다 — 상태 폴더 나무 그림(`people.json`·`tokens.json` 줄 옆에 `access.json`을 권한 0600과 함께)과 그 아래 "접근 제어의 상태" 문단(`people.json`·`tokens.json`만 말하고 있다). 복구 절차는 "쓸 수 없는 `people.json`" 절과 같은 자리에 둔다. `viewer.md` §역할에 따른 화면에 소유자 전용 패널, 새 절로 패널 규칙. `instances.md`에 전환 안내와 `limn member add --role owner` 부트스트랩. `verification.md`에 새 검사. `index.md` §파일 지도에 새 모듈 행. 규칙 문단마다 ADR-0054의 조항을 인용하고, **인용을 지워도 본문만으로 규칙이 완결되게** 쓴다.
- [ ] **Step 3: `SECURITY.md`를 고친다** — 관리 모드가 무엇을 막고 무엇을 안 막는지, 못 쓰는 `access.json`의 fail closed, 테일넷 목록 읽기가 **읽기 전용이고 소유자에게만 보인다**는 것, 목록이 부분적이라는 것.
- [ ] **Step 4: README 쌍과 SKILL 쌍을 고친다** — `README.md:92`·`README.ko.md:89`의 보안 문단과 `skill/SKILL.md:239`·`skill/SKILL.ko.md:239`의 인증 행. 네 파일을 같은 내용으로 맞춘다.
- [ ] **Step 5: `CHANGELOG.md`에 적는다** — **Added**(관리 모드, 패널, 새 경로)와 **Changed**(`limn member remove`·`role`이 마지막 owner를 거부한다). "에이전트 계약은 더하기만 했다"는 문장과, 되돌릴 때 전환 뒤 더한 사람이 못 들어온다는 것을 적는다.
- [ ] **Step 6: 문서 검사를 돌린다**

Run: `uv run pytest -q tests/architecture/ && uv run python tools/check_boundaries.py`
Expected: PASS

- [ ] **Step 7: 커밋** — `docs: viewer-managed instance access in the Handbook and ADR-0054 (proposed)`

### Task 10: 작동 확인, 게이트, 독립 리뷰, PR 초안

- [ ] **Step 1: `origin/main`을 가져와 합친다**(움직였으면). 판 시험이 실패하면 `uv sync --group dev --reinstall-package dartwork-limn`.
- [ ] **Step 2: 실제 경로에서 돌린다** — 임시 상태 디렉터리로 `limn serve --auth tailscale`을 띄우고, ① `--allow`만 준 상태에서 오늘처럼 403이 나는 것, ② `limn member add --role owner`로 소유자를 만든 뒤 패널에서 전환하는 것, ③ 전환 뒤 공저자를 들이면 **재시작 없이** 들어오는 것, ④ `tailscaled`를 못 부르게 만든 상태에서 목록이 "없음 + 이유"로 떨어지고 직접 입력이 되는 것을 **직접 확인한다**. 기다리지 않고 조건을 만들어 일으킨다. `mac-18352`는 건드리지 않는다.
- [ ] **Step 3: 게이트** — `AGENTS.md` §검증의 명령 전부(브라우저 시험 포함) + `uv run python tools/strict_ratchet.py`.
- [ ] **Step 4: 독립 리뷰** — 마지막 커밋을 독립된 Codex 세션이 리뷰한다. GitHub MCP 표가 있을 때만 끈다:

```sh
off=$(grep -qs '^\[mcp_servers\.github\]' ~/.codex/config.toml && echo --config=mcp_servers.github.enabled=false)
codex exec ${off:+"$off"} "…" < /dev/null
```

Critical·Important는 고치고, 남기는 것은 이유와 함께 PR에 적는다. 저장소에 없는 SHA를 근거로 든 지적은 SHA 실재부터 확인한다.
- [ ] **Step 5: PR 초안** — 본문에 무엇과 왜, 전환 전 판정이 바뀌지 않음을 보인 시험, 새 경로·필드·`reason` 코드 목록, 어느 기기군에서 어떤 PoC를 보이고 소유자가 무엇을 골랐는지, 작동 확인 ①~④, 게이트, 독립 리뷰, 남는 것(부분 목록·맥 샌드박스판 미지원). PR 템플릿 체크 셋. **초안으로 두고 머지는 소유자 승인을 받는다.** ADR-0054를 `승인됨`으로 올리는 것과 릴리스 여부도 소유자에게 묻는다.
