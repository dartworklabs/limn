# 저장된 핀 줄의 파싱 기억 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 읽기 전용 발급으로 핀 파일을 읽을 때, 지난 읽기와 글자가 같은 줄은 다시 파싱하지 않는다.

**Architecture:** `pins/store.py`에 줄 글자를 열쇠로 하는 기억(`KeptLines`)을 두고, `PinReader`의 하위 타입 `KeptPinReader`만 그것을 쓴다. `PinStore`는 그대로다. 기억은 `RuntimeResources`의 실행별 자리 `pin_lines`가 소유하고 `server.py`가 연결한다. 읽은 값으로 `pins.md`를 쓰는 두 곳은 쓰기 발급으로 읽는다.

**Tech Stack:** Python 3.10+ 표준 라이브러리만. 시험은 pytest·unittest·Hypothesis(기존 개발 의존성).

**Spec:** [docs/superpowers/specs/2026-11-19-pin-records-parsed-once-design.md](../specs/2026-11-19-pin-records-parsed-once-design.md) (승인됨 2026-11-19, A안). ADR은 구현·시험 뒤 진단하고 소유자와 정한다(Task 6).

## Global Constraints

- 서버 런타임은 표준 라이브러리만 쓴다(`pyproject.toml`의 `dependencies = []`).
- 에이전트 계약(`pins.md` 형식, HTTP API의 경로·필드·상태 이름)과 저장 형식을 바꾸지 않는다. 응답 바이트가 `main`과 같다.
- `PinStore`의 클래스 본문과 `transact()`의 순서를 바꾸지 않는다. 쓰기 경로의 읽기는 기억을 읽지도 채우지도 않는다. 핀 파일에 쓰이는 값은 기억에서 오지 않는다.
- 어떤 GET도 영속 상태를 바꾸지 않는다. 기억은 메모리에만 있다.
- 파일 위치 판정은 요청 사이에 기억하지 않는다(`Locations`·`PinPlaces`는 건드리지 않는다).
- 기능은 다른 기능을 import하지 않고, `runtime/`은 기능을 import하지 않는다.
- 저장 역할 모듈(`store.py`)에 `isinstance`를 더하지 않는다(`tools/check_fitness.py` 기준선). `typing.cast`·`# type: ignore`·`# pyright:`를 쓰지 않는다.
- 한도: 기억 하나의 줄 글자 수 합 `KEPT_LINE_CHARS = 4 * 1024 * 1024`. 넘게 하는 줄부터는 담지 않는다.
- `json.loads`가 `RecursionError`를 낸 줄의 `Broken`은 기억하지 않는다.
- 시험은 벽시계로 성능을 단언하지 않는다. 호출 수·실행한 줄 수를 센다.
- 코드·주석·docstring·시험 이름·커밋 메시지는 영어, Handbook은 한국어. 만들거나 본문을 고친 모든 정의에 docstring을 단다. 호스트 이름·홈 경로를 저장소에 넣지 않는다.
- 커밋은 모두 `git commit -s`, 메시지 끝에 `I agree to the Limn CLA (CLA.md).`

## Review Focus

spec이 전제하지만 시험이 따로 짚지 않으면 지나치기 쉬운 입력들. 줄마다 맡는 task에 시험을 뒀다.

1. **같은 크기로 제자리에서 고친 파일**(같은 inode, mtime을 되돌림). stat 열쇠였다면 낡은 답이 나오는 입력이다. 줄 하나의 글자만 바꿔 다시 읽으면 새 값이 나와야 한다. (Task 1)
2. **같은 줄이 두 번 있는 파일과 줄 순서가 바뀐 파일.** 값 목록의 순서와 `bad` 줄 번호가 지금 읽기와 같아야 한다. (Task 1)
3. **파일이 사라졌다가 다시 생김**(전체 지우기 뒤 첫 핀). 사라진 동안 `([], [])`, 기억은 비고, 다시 생기면 새로 파싱한다. (Task 1)
4. **한도를 넘는 파일.** 답이 같고 기억의 글자 합이 한도 이하이며, 한도 밖의 줄은 읽을 때마다 파싱된다. (Task 1)
5. **읽기 경로가 공유 값을 고침.** 지금은 없지만 뒤의 변경이 넣기 쉽다. 하네스 정리 단계의 대조가 잡아야 한다. (Task 3)

---

### Task 1: 줄 글자 기억과 읽기 전용 발급 (`pins/store.py`)

**Files:**

- Modify: `src/limn/pins/store.py` (`PinReader.read_jsonl`, 새 정의 다섯)
- Test: `src/limn/pins/tests/test_kept_lines.py` (새 파일)

**Interfaces:**

- Produces (모두 `limn.pins.store`):
  - `KEPT_LINE_CHARS: int = 4 * 1024 * 1024`
  - `line_value(text: str, parse: Callable[[object], Parsed | Broken]) -> tuple[Parsed | Broken, bool]` — 빈 줄이 아닌 줄 하나의 값과, 그 값이 줄 글자만의 함수인지. `RecursionError`면 `(parse(None), False)`, 그 밖의 `ValueError`면 `(parse(None), True)`, 풀리면 `(parse(r), True)`.
  - `class KeptLines(Generic[Value])`: `__init__(self, limit: int = KEPT_LINE_CHARS)`, `values(self, lines: Sequence[str], fresh: Callable[[str], tuple[Value, bool]]) -> list[Value]`, `held(self) -> Mapping[str, Value]`.
  - `@dataclass(frozen=True) class PinLines`: `live: KeptLines[Pin | Broken]`, `dropped: KeptLines[TrashedPin | Broken]`, 둘 다 `default_factory=KeptLines`.
  - `PinReader.read_jsonl(self, path, parse, kept: KeptLines[Parsed | Broken] | None = None)` — 반환과 진단은 지금과 같다.
  - `@dataclass(frozen=True) class KeptPinReader(PinReader)`: 필드 `lines: PinLines`. `read_pins()`는 `self.lines.live`를, `read_dropped()`는 `self.lines.dropped`를 `read_jsonl`에 넘긴다.

`KeptLines.values`의 규칙(서명과 시험이 정하지 않는 부분):

```text
old = 지금 세대(잠금 아래 참조만 집는다)
new = {}, chars = 0, full = False
줄마다: old에 있으면 그 값, 없으면 new에 있으면 그 값, 없으면 fresh(줄) -> (값, settled)
        settled이고 full이 아니고 new에 없으면: chars + len(줄) <= limit 이면 담고, 아니면 full = True
지금 세대 = new (잠금 아래 참조만 바꾼다). 세대는 올린 뒤 고치지 않는다.
```

`read_jsonl`은 파일이 없을 때도 `kept`가 있으면 빈 세대를 올린다(`kept.values((), …)`).

- [ ] **Step 1: 실패하는 시험을 쓴다** — `test_kept_lines.py`. 저장소 없이 임시 폴더와 `PinReader`/`KeptPinReader`/`PinStore`를 직접 만든다(`test_store.py`의 방식). 파싱은 호출을 세는 주입 함수로 준다.

  - `KeptReadsAnswerAsPlainReads` (Hypothesis): 줄 풀(유효 레코드, 한 글자 고친 레코드, 비ASCII 메모, 빈 줄, `not json`, `{"id": "x"}`, 중복)에서 뽑은 파일 내용의 열을 차례로 쓰고 읽을 때마다 `kept_reader.read_pins() == plain_reader.read_pins()`이고 휴지통도 같다.
  - `test_an_unchanged_file_is_not_parsed_again`: 두 번째 `read_pins()`의 파싱 호출 0.
  - `test_one_changed_line_is_one_parse`: 80줄 중 한 줄을 고치면 다음 읽기의 호출 1.
  - `test_rereading_costs_no_parse_whatever_the_number_of_lines`: 40줄과 80줄에서 다시 읽기의 호출이 같다(0).
  - `test_a_file_rewritten_in_place_at_the_same_size_is_read_as_it_is_now`: 같은 inode·같은 크기로 한 글자를 바꾸고 `os.utime`으로 시각을 되돌린 뒤 읽으면 새 값.
  - `test_duplicate_and_reordered_lines_keep_their_places`: 값 순서와 `bad` 번호가 `PinReader`와 같다.
  - `test_a_broken_line_is_kept_and_numbered_at_each_read`: 손상 줄의 재파싱 0, 앞에 줄을 넣으면 `bad` 번호가 옮겨 간다.
  - `test_a_line_at_the_nesting_limit_is_judged_at_each_read`: `"[" * 200_000`인 줄은 `Broken`이고 읽을 때마다 파싱 호출이 는다(`held()`에 없다).
  - `test_a_missing_file_empties_what_was_kept`: 파일을 지우면 `([], [])`이고 `held()`가 비며, 다시 쓰면 새로 파싱한다.
  - `test_what_is_kept_stays_within_the_limit`: `KeptLines(limit=200)`에서 `sum(len(k) for k in held())<= 200`, 답은 같고, 한도 밖 줄은 읽을 때마다 파싱된다.
  - `test_lines_that_left_the_file_leave_what_is_kept`: 줄을 빼고 읽으면 `held()`에 그 줄이 없다.
  - `test_live_and_trash_lines_are_kept_apart`: 같은 글자의 줄이 두 파일에 있어도 `read_pins()`는 `Pin`, `read_dropped()`는 `TrashedPin`.
  - `test_each_read_hands_out_its_own_list`: 받은 목록을 비워도 다음 읽기가 같다.
  - `test_a_store_parses_every_time_and_keeps_nothing`: 같은 `PinLines`를 쓰는 `KeptPinReader` 옆의 `PinStore.read_pins()`·`transact()`는 호출마다 전부 파싱하고 `held()`를 바꾸지 않는다. `transact`의 `fn`이 받은 목록과 값을 고쳐도 `held()`의 값이 새 파싱과 같다.
  - `test_readers_racing_a_writer_each_answer_the_text_they_read`: 스레드 넷이 읽는 동안 두 판을 번갈아 원자적으로 교체한다. 각 읽기의 답이 두 판 중 하나의 새 파싱과 같다. 판을 바꾸는 쪽은 장벽(`threading.Barrier`)으로 순서를 고정하고, 폴링이나 `sleep`을 쓰지 않는다.

- [ ] **Step 2: 실패를 본다**

  Run: `uv run pytest -q src/limn/pins/tests/test_kept_lines.py`
  Expected: 수집 오류(`KeptPinReader`를 import할 수 없다).

- [ ] **Step 3: `store.py`에 구현한다.** 모듈 docstring에 기억과 그 소유(조립 지점이 넘긴다)를 한 문단 더한다. `PinReader.read_jsonl`의 줄 처리 순서와 `bad`·진단은 그대로 둔다.

- [ ] **Step 4: 통과를 본다**

  Run: `uv run pytest -q src/limn/pins/tests/test_kept_lines.py src/limn/pins/tests/test_store.py src/limn/pins/tests/test_trash.py`
  Expected: 모두 통과. `test_store.py`의 소스 검사(표준 라이브러리만 import, 서버 전역 없음)도 통과.

- [ ] **Step 5: 커밋** — `perf(pins): keep what a stored line parses to by the line's own text`

### Task 2: 실행 자원과 조립

**Files:**

- Modify: `src/limn/runtime/resources.py` (타입 변수 `Lines`, 필드 `pin_lines: Lines`를 `figure_maps` 다음에)
- Modify: `src/limn/server.py` (`RunResources` 별칭, `new_runtime`이 `PinLines()`를 넘긴다)
- Modify: `src/limn/pins/__init__.py` (`PinLines`를 `__all__`·`_EXPORTS`·`TYPE_CHECKING` import에), `tools/check_boundaries.py` (`ENTRYPOINT_IMPORTS`)
- Modify: `src/limn/pins/runtime.py` (`pin_reader()`가 `KeptPinReader(…, self.RT.pin_lines)`를 준다. `refresh_pins_md`는 `self.pin_store().read_pins()[0]`로 읽는다. `resources`·`RT`의 타입에 `PinLines`)
- Modify: `src/limn/pins/application.py` (기동 때 `render()`가 `commands.pin_store().read_pins()[0]`로 읽는다. `resources`의 타입)
- Modify: `src/limn/security/application.py` (`RuntimeResources[…]`에 `object` 하나)
- Test: `src/limn/pins/tests/test_kept_lines.py` (조립을 거치는 시험 추가)

**Interfaces:**

- Consumes: Task 1의 `PinLines`, `KeptPinReader`.
- Produces: `RuntimeResources.pin_lines`, `limn.pins.PinLines`(진입점용 export).

- [ ] **Step 1: 실패하는 시험을 쓴다** — `test_kept_lines.py`에 `Base`(`tests/support/helpers.py`)를 쓰는 클래스 둘. 줄 수는 `test_locations.py`의 `lines_run`과 같은 방식으로 `limn.pins.record` 모듈에서 센다(도우미는 이 파일에 둔다).

  - `ARunParsesAStoredLineOnce`:
    - `test_a_second_read_runs_no_line_of_the_record_check`: 핀 40개에서 `pin_listing.list_payload(True)`, `pin_listing.pin_payload(7)`, `pin_markdown.current_text(...)`, `pins.counts.state_counts()`(meta), `counts_by_document`(docs), 휴지통 목록 각각을 한 번 부른 뒤 다시 부르면 `limn.pins.record`에서 실행한 줄이 0이다. 첫 호출은 0보다 크다(새 실행 자원에서).
    - `test_a_write_costs_the_next_read_one_line`: 답글 하나 뒤의 목록이 레코드 검사를 한 줄 몫만 돈다(40핀과 80핀에서 같은 줄 수).
    - `test_two_runs_share_nothing`: `fresh_runtime()` 뒤 첫 읽기는 다시 전부 파싱한다.
  - `WritersDoNotReadWhatIsKept`:
    - `test_pins_md_written_after_publication_comes_from_the_file`: `RT.pin_lines.live`의 세대에 줄 하나의 값을 다른 핀으로 바꿔 심은 뒤(`KeptLines.values`로 올린다) `refresh_pins_md()`를 부르면 디스크의 `pins.md`가 `pin_markdown.pins_md_text(새로 파싱한 핀)`과 같다.
    - `test_pins_md_rendered_at_startup_comes_from_the_file`: 같은 것을 `pins.startup.render()`로.
    - `test_a_transaction_reads_the_file`: 같은 식으로 틀린 값을 심고 답글을 달면 `pins.jsonl`의 다른 줄들이 바이트 그대로다.

- [ ] **Step 2: 실패를 본다**

  Run: `uv run pytest -q src/limn/pins/tests/test_kept_lines.py`
  Expected: `ARunParsesAStoredLineOnce`가 0이 아닌 줄 수로 실패하고, `WritersDoNotReadWhatIsKept`는 `pin_lines`가 없어 실패한다.

- [ ] **Step 3: 조립을 구현한다.** `PinCommands.pin_reader()`의 반환 타입은 `PinReader` 그대로다.

- [ ] **Step 4: 통과와 경계 검사를 본다**

  Run: `uv run pytest -q src/limn/pins/tests src/limn/documents/tests tests/contracts tests/architecture -n 8` 그리고 `uv run python tools/check_boundaries.py && uv run python tools/check_fitness.py && uv run python tools/check_types.py`
  Expected: 모두 통과. 기준선은 오르지 않는다.

- [ ] **Step 5: 커밋** — `perf(pins): the run keeps parsed pin lines for its read-only readers`

### Task 3: 공유 규칙의 감사

**Files:**

- Modify: `tests/support/helpers.py` (`kept_lines_changed(mod=None) -> list[str]`, `Base.tearDown`)
- Modify: `tests/support/helpers_browser.py` (브라우저 하네스가 같은 프로세스의 실행 자원을 정리하는 자리가 있으면 같은 대조)
- Modify: `tests/contracts/test_get_write_guard.py` (읽기 경로 전수 walk 뒤 대조)
- Test: `tests/test_kept_lines_audit.py` (새 파일)

**Interfaces:**

- Consumes: `RuntimeResources.pin_lines`, `store.line_value`, `PinCommands.parse_record`·`parse_trashed`.
- Produces: `kept_lines_changed(mod=None) -> list[str]` — 지금 실행의 두 기억에서, 기억한 값이 그 줄의 새 파싱과 다른 줄들(앞 80자). 비교는 타입이 같고 `json.dumps(value.record, ensure_ascii=False)`가 같은지로 한다(`Broken`끼리는 같다). `==`는 NaN이 든 레코드를 다르다고 하므로 쓰지 않는다.

- [ ] **Step 1: 실패하는 시험을 쓴다** — `tests/test_kept_lines_audit.py`:
  - `test_a_reader_that_changes_a_kept_pin_is_reported`: 핀을 하나 만들고 읽은 뒤 `ps.APP.read_pins()[0][0].record["author"]["name"] = "x"`를 하면 `kept_lines_changed()`가 그 줄을 낸다.
  - `test_reading_every_way_changes_nothing`: 목록·한 건·`pins.md`·수 세기·사람·휴지통·편집 대상 판정·겹침 계산을 돈 뒤 `kept_lines_changed() == []`.
- [ ] **Step 2: 실패를 본다** — Run: `uv run pytest -q tests/test_kept_lines_audit.py`. Expected: `kept_lines_changed` import 실패.
- [ ] **Step 3: 도우미를 쓰고 `Base.tearDown`이 임시 폴더를 지우기 전에 `self.assertEqual(kept_lines_changed(), [])`를 하게 한다.** 일부러 고친 첫 시험은 대조 전에 `fresh_runtime()`으로 그 실행을 버린다.
- [ ] **Step 4: 전체 파이썬 시험으로 감사를 돌린다**

  Run: `uv run pytest -q -rs`
  Expected: 통과. 정리 단계의 대조가 실패하는 시험이 있으면 그 읽기 경로가 공유 값을 고친 것이다. 그 경로를 고치고(값을 복사해 고치게), spec의 "위반 0건"을 정정한다.

- [ ] **Step 5: 커밋** — `test(pins): every test's teardown checks that no reader changed a kept pin`

### Task 4: Handbook과 CHANGELOG

**Files:**

- Modify: `docs/handbook/architecture.md` (§HTTP 읽기 능력과 유지 실행, §현재 구조의 핀·실행 자원 행), `docs/handbook/domain.md` (§저장소 안전성), `docs/handbook/api.md` (§GET의 영속 무효과), `docs/handbook/verification.md` (§불안정한 테스트), `docs/handbook/index.md` (파일 지도에 해당 행이 있으면), `CHANGELOG.md`

- [ ] **Step 1: 현재형으로 고친다.** 내용은 spec §문서 동기화의 목록 그대로다. 날짜·전후 수치·호스트 이름은 넣지 않는다. CHANGELOG는 다음 판 머리(없으면 `## Unreleased`가 아니라 기존 관례를 따른다 — 최근 릴리스 PR의 머리 형식을 확인)에 `### Changed`와 "에이전트 계약 불변"을 적는다. 판 번호는 올리지 않는다(릴리스는 소유자가 정한다).
- [ ] **Step 2: 문서 시험** — Run: `uv run pytest -q tests/architecture -n 4 && npm run format:check`. Expected: 통과.
- [ ] **Step 3: 커밋** — `docs(handbook): parsed pin lines are kept per run for read-only readers`

### Task 5: 증명과 측정 (저장소 밖 작업 폴더)

- [ ] **Step 1: 고장 넣기.** spec §검증 7의 변이 아홉을 하나씩 넣고 해당 시험이 그 단언에서 실패하는지 본다. 결과 표를 작업 폴더에 남긴다. 살아남는 변이가 있으면 시험을 더한다.
- [ ] **Step 2: 차등 비교.** `main`(합친 `origin/main`)과 이 가지를 같은 상태 폴더 사본(1,002핀 + 변종 17건)으로 띄워, 핀 읽기 전부를 두 번씩 받고 사이에 답글·편집·삭제·되살리기와 파일을 밖에서 고치는 일을 같은 순서로 끼워 바이트를 대조한다. Expected: 차이 0.
- [ ] **Step 3: 측정.** `main`과 이 가지를 번갈아 두 번씩 `fx_scale.py`·`fx_slots.py`로 재고 `uptime`을 함께 남긴다. 요청 한 번의 프로파일에서 레코드 파싱 호출 수 전후를 적는다. Expected: 두 번째 요청의 `parse_record` 호출 0. 시간은 보고 값이다.
- [ ] **Step 4: 메모리.** 실제 서버 프로세스에서 1,002핀을 읽은 뒤의 기억 크기를 재서 spec의 배수(7.2배)와 견준다.
- [ ] **Step 5: 게이트.** `CLAUDE.md` §검증의 전부를 차례로 돌리고 결과를 표로 남긴다.

### Task 6: 독립 리뷰, 진단, PR

- [ ] **Step 1:** `origin/main`을 다시 가져와 움직였으면 합치고 영향받는 검사를 다시 돌린다.
- [ ] **Step 2:** 새 맥락의 리뷰어에게 가지 전체 diff와 spec을 주고 검토받는다(결론을 주지 않는다). 지적은 코드로 확인한 뒤 고친다.
- [ ] **Step 3:** 측정·시험 결과로 "기술적으로 충분한가"를 진단해 소유자에게 보이고, ADR 여부와 릴리스 여부를 묻는다.
- [ ] **Step 4:** PR을 연다. 본문에 전후 수치(부하와 함께), 파싱 호출 수, 차등 비교 건수, 변이 표, 게이트 결과, 폴링 지연이 회복되지 않는 사실과 그 원인을 적는다. 머지는 `workflow.md` 절차를 따른다.
