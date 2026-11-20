# 가벼운 폴링이 원고 폴더를 훑지 않게 한다 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 감시 스레드가 LaTeX 문서의 원고 수정 시각을 재 두고, 문서 요약(가벼운 폴링)은 그 값을 읽어 원고 폴더를 훑지 않는다.

**Architecture:** 측정과 기억의 규칙은 `builds/artifacts.py`가 소유한다(요약의 읽기 `shown_src_mtime`, 감시의 한 문서 차례 `watch_src_mtime`, 문서마다의 측정 잠금). 감시의 고리는 `builds/service.py`의 `BuildRequests.watch_sources`이고, 기동(`server.py`의 `prepare`)이 `RuntimeResources.start_thread`로 시작한다. `Doc`은 숫자 둘과 잠금 하나가 놓이는 자리만 준다. 문서 조회와 빌드 사이의 선언은 바뀌지 않는다.

**Tech Stack:** Python 3.10+ 표준 라이브러리만. 시험은 pytest·unittest(기존 개발 의존성).

**Spec:** [docs/superpowers/specs/2026-11-19-poll-manuscript-walk-design.md](../specs/2026-11-19-poll-manuscript-walk-design.md) (승인됨 2026-11-20: A안, 한도는 문서마다 10초, 15초 뒤에 놓는다, ADR-0053은 구현 PR에 `제안`으로).

## Global Constraints

- 서버 런타임은 표준 라이브러리만 쓴다(`pyproject.toml`의 `dependencies = []`).
- 에이전트 계약(`pins.md` 형식, HTTP API의 경로·필드·상태 이름)과 저장 형식을 바꾸지 않는다. 새 파일·새 실행 인자가 없다.
- 상수(이름과 값): `SRC_MEMO_S = 2.0`(지금의 리터럴), `SRC_WATCH_EVERY_S = 1.0`, `SRC_WATCH_ASKED_S = 15.0`, `SRC_WATCH_TRUST_S = 10.0`. 모두 `builds/artifacts.py`에 둔다.
- 한도 10초는 감시의 측정이 **끝난** 시각부터 센다. 물은 시각과 감시가 잰 시각은 뒤로 가지 않는 시계(`artifacts.watch_clock`, `time.monotonic`)로 재고, 처음 값은 `float("-inf")`다(부팅 직후의 작은 시계 값을 "방금"으로 읽지 않는다). 2초 기억은 지금처럼 `time.time`이다.
- `src_mtime(D, state_dir, force=False, build=None)`의 서명과 답은 그대로다. 달라지는 것은 문서 하나의 측정이 한 번에 하나만 돈다는 것뿐이다.
- 빌드의 기준(`run.py`의 `run_tracked`, `engine.py`의 `compile_tex`, `write_built_src_mtime`, `seed_builds`)은 `force=True`로 그 자리에서 잰다. pick(`source_newer(name)`)은 2초 규칙이다. 둘 다 `shown_src_mtime`을 부르지 않는다.
- 잠금의 순서는 측정 잠금(`mcache_measuring`) 다음에 `mcache_lock`이다. 측정 잠금을 쥔 채 다른 문서의 잠금, 빌드 잠금(`Doc.lock`), 이력 잠금(`builds_lock`)을 잡지 않는다. 감시는 측정 잠금을 기다리지 않는다.
- 감시는 `stat`·폴더 읽기·화면 빌드의 `.fls` 읽기만 한다. 요청은 스레드를 시작하지 않는다.
- 기능은 다른 기능을 import하지 않고, `runtime/`은 기능을 import하지 않는다. 선언 모듈(`needs.py`·`contracts.py`)은 건드리지 않는다. `tools/check_fitness.py` 기준선과 `.basedpyright/baseline.json`은 늘지 않는다. `typing.cast`·`# type: ignore`·`# pyright:`를 쓰지 않는다.
- 시험은 벽시계로 성능을 단언하지 않는다. 파일 시스템 호출 수를 센다(`tests/support/helpers.py`의 `fs_calls`). 지나가는 상태를 스레드로 폴링해 보지 않는다. 순서는 잠금을 쥐거나 훑기 안에서 다음 일을 일으켜 고정한다.
- 코드·주석·docstring·시험 이름·커밋 메시지는 영어, Handbook과 ADR은 한국어. 만들거나 본문을 고친 모든 정의에 docstring을 단다. 호스트 이름·홈 경로를 저장소에 넣지 않는다.
- 커밋은 모두 `git commit -s`, 메시지 끝에 `I agree to the Limn CLA (CLA.md).` 스테이징은 파일 이름으로 한다.

## Review Focus

1. **읽을 수 없는 빌드 루트.** 원고 폴더가 사라졌거나 권한이 없어도 감시는 멈추지 않고, 요약의 읽기는 지금처럼 0.0을 답한다 → Task 2의 `test_a_document_whose_tree_is_gone_is_measured_as_nothing_and_the_watch_goes_on`.
2. **부팅 직후.** 뒤로 가지 않는 시계가 15보다 작아도, 아무도 묻지 않은 문서를 감시가 재지 않는다 → Task 2의 `test_a_document_nobody_asked_about_is_not_measured_however_small_the_clock`.
3. **쪽 교체와 겹친 감시의 측정.** 저장되지 않고, 감시가 잰 시각도 적히지 않는다 → Task 2의 `test_a_watch_measurement_that_spans_a_page_swap_is_dropped_and_leaves_no_stamp`.
4. **응답하지 않는 측정 뒤의 종료.** 감시가 한 문서에 묶여 있어도 `RuntimeResources.stop`은 5초 뒤 돌아온다(데몬 스레드) → Task 3의 `test_stop_returns_while_the_watch_is_inside_a_measurement`.
5. **한 프로세스의 두 실행.** 한 실행의 감시가 다른 실행의 문서를 재지 않고, 숫자와 잠금을 나눠 쓰지 않는다 → Task 3의 `test_two_runs_share_no_watch_state`.

---

### Task 1: 문서 하나의 측정은 한 번에 하나

**Files:**
- Modify: `src/limn/runtime/documents.py` (`Doc.__init__`: `mcache_asked`, `mcache_watched`, `mcache_measuring`)
- Modify: `src/limn/builds/artifacts.py` (`BuildDoc`, `SRC_MEMO_S`, `src_mtime`, 새 `_memo_hit`·`_measure`)
- Modify: `src/limn/builds/tests/test_build.py`, `src/limn/builds/tests/test_warm.py` (`BuildDoc`을 흉내 내는 대역에 새 셋)
- Test: `src/limn/builds/tests/test_source_watch.py` (새 파일)

**Interfaces:**
- Produces:
  - `Doc.mcache_asked: float`, `Doc.mcache_watched: float` (둘 다 `float("-inf")`로 시작, `mcache_lock` 아래에서만 읽고 쓴다), `Doc.mcache_measuring: threading.Lock`. `BuildDoc`에 같은 셋.
  - `artifacts._memo_hit(D: BuildDoc, key: tuple[str, str | None]) -> float | None`: `mcache_lock` 아래에서 칸의 열쇠가 `key`이고 잰 지 `SRC_MEMO_S` 안이면 값, 아니면 `None`.
  - `artifacts._measure(D: BuildDoc, state_dir: Path, key: tuple[str, str | None], build: str | None, by_watch: bool = False) -> float`: 부른 쪽이 `D.mcache_measuring`을 쥐고 있어야 한다. 세대를 읽고, 훑고, 세대가 그대로면 칸에 저장한다. `by_watch`이고 저장했으면 같은 잠금 구간에서 `D.mcache_watched = watch_clock()`(Task 2에서 쓴다).
  - `artifacts.src_mtime`: `force`가 아니면 `_memo_hit`, 빗나가면 측정 잠금을 잡고 `_memo_hit`을 다시 본 뒤 `_measure`. `force`면 측정 잠금을 잡고 바로 `_measure`.

- [ ] **Step 1: 실패하는 시험을 쓴다** (`test_source_watch.py`, 클래스 `OneMeasurementAtATime`)

  픽스처: 임시 원고(`main.tex`, `sec/a.tex`)와 상태 폴더, `Doc("ms", "Body", "tex", src, src / "main.tex", paths=RunPaths(src, src / "main.tex", state))`. 도우미 `walks(call)`은 `fs_calls(call)[0]["scandir"]`를 돌려준다.

  - `test_a_miss_behind_a_running_measurement_takes_its_value_without_walking`: 시험이 `doc.mcache_measuring`을 쥔 채 스레드 하나가 `src_mtime(doc, state)`를 부른다. 시험이 칸을 `[(str(src), None), 123.0, time.time()]`으로 채우고 잠금을 놓는다. 스레드의 답은 `123.0`이고 그 스레드의 `scandir`는 0이다(`fs_calls`를 스레드 안에서 건다).
  - `test_a_forced_measurement_waits_and_then_measures_itself`: 같은 준비에서 스레드가 `src_mtime(doc, state, force=True)`를 부른다. 잠금을 놓은 뒤의 답은 `123.0`이 아니라 `main.tex`의 mtime이고 `scandir`가 1 이상이다.
  - `test_a_measurement_that_started_first_cannot_overwrite_a_later_one`: `build_inputs`를 감싸 첫 호출을 붙잡는다(`test_apart_sources.py`의 `slow` 방식). 붙잡힌 동안 `main.tex`를 고치고(`os.utime`으로 +50초) 다른 스레드에서 `src_mtime(doc, state, force=True)`를 시작한다. 붙잡은 것을 놓고 둘을 기다린다. 끝난 뒤 `doc.mcache[1]`은 고친 뒤의 mtime이다.
  - `test_a_hit_takes_no_measurement_lock`: 칸이 방금 채워진 상태에서 시험이 `mcache_measuring`을 쥔 채 `src_mtime(doc, state)`를 같은 스레드에서 부른다. 멈추지 않고 칸의 값을 답한다.

- [ ] **Step 2: 실패를 본다**

  Run: `uv run pytest -q src/limn/builds/tests/test_source_watch.py`
  Expected: FAIL (`Doc`에 `mcache_measuring`이 없다).

- [ ] **Step 3: 구현한다** — 위 Interfaces 그대로. `src_mtime`의 docstring에 "한 번에 하나"와 그 이유(늦게 끝난 옛 측정이 새 값을 덮지 못한다)를 적는다. `test_build.py`·`test_warm.py`의 대역 dataclass에 `mcache_asked`·`mcache_watched`(기본 `float("-inf")`)·`mcache_measuring`(기본 `threading.Lock`)을 더한다.

- [ ] **Step 4: 통과를 본다**

  Run: `uv run pytest -q src/limn/builds/tests/test_source_watch.py src/limn/builds/tests/test_apart_sources.py src/limn/builds/tests/test_build.py src/limn/builds/tests/test_warm.py src/limn/documents/tests/test_light_poll_reads.py`
  Expected: PASS.

- [ ] **Step 5: 커밋** — `perf(builds): one measurement of a document's manuscript mtime at a time`

### Task 2: 요약의 읽기와 감시의 한 문서 차례

**Files:**
- Modify: `src/limn/builds/artifacts.py` (상수 셋, `watch_clock`, `shown_src_mtime`, `watch_src_mtime`, `expire_src_mtime`, `shown_source_newer`)
- Modify: `src/limn/builds/queries.py` (`_shown`이 `artifacts.shown_src_mtime(doc, state)`를 부른다)
- Test: `src/limn/builds/tests/test_source_watch.py`

**Interfaces:**
- Consumes: Task 1의 `_measure(..., by_watch=True)`, `Doc`의 새 셋.
- Produces:
  - `artifacts.watch_clock() -> float`: `time.monotonic()`. 시험이 `mock.patch.object(artifacts, "watch_clock", ...)`로 세운다.
  - `artifacts.shown_src_mtime(D: BuildDoc, state_dir: Path) -> float`: 원본에서 빌드하지 않는 문서는 `src_mtime(D, state_dir)` 그대로. 그 밖에는 `mcache_lock` 아래에서 `D.mcache_asked = now`를 적고, 칸의 열쇠가 `(str(D.src), None)`이고 `now - D.mcache_watched < SRC_WATCH_TRUST_S`이면 칸의 값을 답한다. 아니면 `src_mtime(D, state_dir)`.
  - `artifacts.watch_src_mtime(D: BuildDoc, state_dir: Path) -> bool`: 쟀으면 `True`. 원본에서 빌드하지 않으면 `False`. `now - D.mcache_asked >= SRC_WATCH_ASKED_S`이면 `D.mcache_watched = float("-inf")`로 지우고 `False`. `D.mcache_measuring.acquire(blocking=False)`가 실패하면 `False`. 잡았으면 `_measure(D, state_dir, (str(D.src), None), None, by_watch=True)`.
  - `expire_src_mtime`: 지금 하는 일에 더해 `D.mcache_watched = float("-inf")`.
  - `shown_source_newer`: 안의 `src_mtime(D, state_dir)`를 `shown_src_mtime(D, state_dir)`로.

- [ ] **Step 1: 실패하는 시험을 쓴다** (클래스 `SummaryReadsTheWatch`, `WatchTurn`)

  도우미 `at(seconds)`는 `mock.patch.object(artifacts, "watch_clock", return_value=seconds)`. 2초 기억을 빗나가게 할 때는 `doc.mcache[2] = 0.0`으로 잰 시각을 지운다(시계를 건드리지 않는다).

  - `test_a_summary_read_after_a_watch_turn_walks_nothing_whatever_the_age_of_the_memo`: `at(100)`에서 `shown_src_mtime`(직접 잰다), `watch_src_mtime` → `True`. `doc.mcache[2] = 0.0`. `at(105)`에서 `shown_src_mtime`의 `scandir + entry_stat`가 0이고 답이 원고의 mtime이다.
  - `test_the_calls_of_a_watched_read_do_not_grow_with_the_manuscript`: 파일 3개인 원고와 300개인 원고에서 위 읽기의 `fs_calls` 합이 같다(0).
  - `test_past_the_limit_the_summary_measures_itself`: 감시가 `at(100)`에 쟀고 `at(110)`(정확히 10초)에서의 읽기는 `scandir`가 1 이상이다. `at(109.9)`에서는 0이다.
  - `test_a_request_measurement_is_trusted_for_two_seconds_only`: 감시가 한 번도 재지 않은 문서에서 `shown_src_mtime` 뒤 `doc.mcache[2] = 0.0`이면 다음 읽기가 훑는다.
  - `test_a_document_nobody_asked_about_is_not_measured_however_small_the_clock`: 새 `Doc`에 대해 `at(0.5)`에서 `watch_src_mtime` → `False`, `fs_calls` 합 0.
  - `test_a_document_is_let_go_fifteen_seconds_after_it_was_last_asked_about`: `at(100)` 읽기, `at(114.9)` 감시 → `True`, `at(115)` 감시 → `False`이고 `fs_calls` 합 0, `doc.mcache_watched == float("-inf")`.
  - `test_two_reads_after_the_watch_let_go_do_not_answer_what_it_last_measured`: `at(100)` 읽기, `at(114)` 감시, `at(115.5)` 감시(놓는다), 원고를 고친다(`os.utime` +50초), `doc.mcache[2] = 0.0`. `at(120)`에서 읽기 둘의 답이 모두 고친 뒤의 mtime이고, 둘째는 훑지 않는다(첫째가 잰 2초 기억).
  - `test_a_page_swap_forgets_what_the_watch_measured`: 감시가 잰 뒤 `expire_src_mtime`. 같은 시각의 읽기가 훑는다(`scandir` 1 이상).
  - `test_a_watch_measurement_that_spans_a_page_swap_is_dropped_and_leaves_no_stamp`: `build_inputs`를 감싸 그 안에서 `expire_src_mtime(doc)`을 부른다. `watch_src_mtime` 뒤 `doc.mcache_watched == float("-inf")`이고 `doc.mcache[2] == 0.0`이다.
  - `test_the_swap_of_a_document_that_sets_files_apart_is_answered_against_the_new_build`: `test_apart_sources.py`의 준비(다른 문서의 그림 폴더, 빌드 둘, 둘째의 `.fls`만 그림을 읽는다)로, 감시가 첫 빌드 기준으로 잰 뒤 포인터를 바꾸고 `expire_src_mtime`. 읽기의 답이 그림의 mtime이다.
  - `test_a_forced_measurement_ignores_what_the_watch_keeps`: 감시가 잰 뒤 원고를 고치고 `src_mtime(doc, state, force=True)` → 고친 뒤의 mtime. 이어서 같은 시각의 `shown_src_mtime`도 그 값이다(칸에 가장 늦게 저장된 측정).
  - `test_a_pick_does_not_use_the_ten_second_limit`: 감시가 `at(100)`에 쟀고 `doc.mcache[2] = 0.0`. `at(105)`에서 `source_newer(doc, state, B1)`은 훑는다(`scandir` 1 이상). 같은 준비에서 `shown_src_mtime`이 훑지 않는다는 것은 첫 시험이 본다(한 시험에서 이어 부르면 앞의 호출이 칸을 채운다).
  - `test_a_named_measurement_in_the_cell_is_not_answered_as_the_build_on_screen`: 다른 문서의 파일을 빼 두는 문서에서 감시가 잰 뒤 `src_mtime(doc, state, force=True, build=B1)`. 같은 시각의 `shown_src_mtime`은 칸의 값을 답하지 않고 화면 빌드 기준으로 잰다.
  - `test_the_watch_skips_a_document_someone_else_is_measuring`: 시험이 `mcache_measuring`을 쥔 채 `watch_src_mtime` → `False`, `fs_calls` 합 0. 멈추지 않는다.
  - `test_a_document_not_built_from_source_is_neither_watched_nor_marked_asked`: 보기 전용 PDF 문서에서 `shown_src_mtime`은 주 파일 `stat` 하나이고 `mcache_asked`는 `float("-inf")` 그대로다. `watch_src_mtime` → `False`.
  - `test_a_document_whose_tree_is_gone_is_measured_as_nothing_and_the_watch_goes_on`: 원고 폴더를 지운 뒤 읽기는 `0.0`, `watch_src_mtime`은 예외 없이 `True`.

- [ ] **Step 2: 실패를 본다**

  Run: `uv run pytest -q src/limn/builds/tests/test_source_watch.py`
  Expected: FAIL (`shown_src_mtime`이 없다).

- [ ] **Step 3: 구현한다** — Interfaces 그대로. 상수마다 값의 이유를 주석 한 줄로 적는다(간격: 평소 늦어지는 최대, 15초: 폴링 세 번, 10초: 폴링 두 번).

- [ ] **Step 4: 통과를 본다**

  Run: `uv run pytest -q src/limn/builds src/limn/documents/tests/test_light_poll_reads.py`
  Expected: PASS.

- [ ] **Step 5: 커밋** — `perf(builds): a document summary answers the manuscript mtime the watch keeps`

### Task 3: 감시의 고리와 조립

**Files:**
- Modify: `src/limn/builds/service.py` (`BuildRequests.watch_sources`, `watch_sources_round`)
- Modify: `src/limn/builds/application.py` (`BuildCommands.watch_sources`)
- Modify: `src/limn/server.py` (`prepare`)
- Test: `src/limn/builds/tests/test_source_watch.py`, `src/limn/runtime/tests/test_server.py`, `src/limn/documents/tests/test_light_poll_reads.py`

**Interfaces:**
- Consumes: `artifacts.watch_src_mtime`, `artifacts.SRC_WATCH_EVERY_S`.
- Produces:
  - `BuildRequests.watch_sources_round(self, stop: threading.Event) -> None`: 실행의 문서(`list(self.docs())`)마다 `stop.is_set()`이면 돌아오고, 아니면 `build.watch_src_mtime(doc, self.settings().state)`. 예외는 표준 오류에 적고 다음 문서로 간다.
  - `BuildRequests.watch_sources(self, stop: threading.Event, every: float = build.SRC_WATCH_EVERY_S) -> None`: `stop.wait(남은 시간)`이 참이 될 때까지 바퀴를 돈다. 남은 시간은 바퀴의 시작부터 `every`를 채우는 만큼이고 0보다 작지 않다. 첫 기다림은 `every`다.
  - `BuildCommands.watch_sources(self, stop: threading.Event) -> None`.
  - `prepare`: 문서 초기화 뒤 `environment.RT.start_thread(app.builds.commands.watch_sources, environment.RT.stopping)`을 늘 부른다(`--doc`가 없어도).

- [ ] **Step 1: 실패하는 시험을 쓴다**

  `test_source_watch.py`, 클래스 `WatchLoop`. 대역 `Rounds(n)`은 `wait(timeout)`이 n번째까지 `False`를 주고 받은 `timeout`을 기록하며, `is_set()`은 `wait`가 `True`를 준 뒤에만 참이다(`test_watch.py`의 `OneRound`를 넓힌 것).

  - `test_one_round_measures_the_documents_asked_about_and_no_other`: 문서 셋(물은 LaTeX, 묻지 않은 LaTeX, 보기 전용 PDF)에서 한 바퀴 뒤 물은 문서만 `mcache_watched`가 유한하다.
  - `test_a_document_that_raises_does_not_stop_the_round`: `watch_src_mtime`을 첫 문서에서 예외를 내게 감싼다. 둘째 문서는 재진다. 표준 오류에 traceback이 있다.
  - `test_the_round_ends_between_documents_when_the_run_stops`: 첫 문서의 측정 안에서 종료 이벤트를 세운다. 둘째 문서는 재지지 않는다.
  - `test_rounds_start_a_second_apart_and_back_to_back_when_one_takes_longer`: `time.monotonic`을 `service`에서만 바꿔(주입한 시계: `mock.patch.object(service.time, "monotonic", side_effect=...)`) 바퀴가 0.2초 걸리면 다음 기다림이 0.8, 1.5초 걸리면 0.0이다(`Rounds`가 기록한 `timeout`).
  - `test_two_runs_share_no_watch_state`: `Doc` 둘을 같은 원고로 만들고 한쪽만 묻고 한쪽 실행의 바퀴만 돈다. 다른 쪽의 `mcache_asked`·`mcache_watched`는 `float("-inf")`, `mcache_measuring`은 다른 객체다.

  `test_server.py`:
  - `test_prepare_starts_the_manuscript_watch_with_or_without_documents`: 그 파일의 기존 `prepare` 시험이 쓰는 준비로 `--doc`가 있을 때와 없을 때 `prepare` 뒤 `RT.threads` 가운데 `watch_sources`를 도는 스레드가 하나 있고, `RT.stop()` 뒤 살아 있지 않다. 기존 시험의 스레드 수 단언은 하나씩 는다.
  - `test_stop_returns_while_the_watch_is_inside_a_measurement`: `watch_src_mtime`을 이벤트를 기다리게 감싸고 감시를 `start_thread`로 시작한다. `rt.stop(timeout=0.2)`가 돌아온다. 그 뒤 이벤트를 놓아 스레드가 끝나는 것을 기다린다(`join`).
  - `test_a_read_request_cannot_start_the_watch`: `effects.reading()` 안에서 `rt.start_thread(...)`는 `PermissionError`다(기존 시험이 있으면 그것으로 충분하다. 없을 때만 더한다).

  `test_light_poll_reads.py`, 클래스 `WatchedPoll`(그 파일의 `Fixture`):
  - `test_a_poll_of_watched_documents_walks_no_manuscript`: LaTeX 문서 둘(`ms`, `rr`)과 PDF를 발행하고 `at(100)`에서 폴링 한 번, 두 문서에 `watch_src_mtime`, 칸마다 잰 시각을 지운 뒤 `at(104)`에서 `fs_calls(lambda: self.meta(self.ms, docs))`의 `scandir + listdir + entry_stat`가 0이다.
  - `test_the_calls_of_a_watched_poll_equal_those_of_a_memo_hit_and_ignore_the_manuscript_size`: `ms`에 원고 파일 3개일 때와 300개일 때 위 폴링의 호출 수 합이 같고, 시계를 세운(`frozen()`) 연이은 폴링의 합과 같다.
  - `test_the_first_poll_after_the_watch_let_go_walks_as_before`: `at(100)` 폴링, 감시, `at(116)` 감시(놓는다), 칸의 잰 시각을 지우고 `at(120)` 폴링은 `scandir`가 1 이상이고, 감시 없이 같은 준비로 잰 폴링과 호출 수가 같다.
  - `test_a_watched_poll_answers_what_an_unwatched_one_does`: 같은 상태에서 감시가 재 둔 폴링의 본문과, 새 `Doc`들로 직접 잰 폴링의 본문이 `src_age_s`를 빼고 같다.

- [ ] **Step 2: 실패를 본다**

  Run: `uv run pytest -q src/limn/builds/tests/test_source_watch.py src/limn/runtime/tests/test_server.py src/limn/documents/tests/test_light_poll_reads.py`
  Expected: 새 시험이 FAIL (`watch_sources_round`가 없다, 스레드 수).

- [ ] **Step 3: 구현한다** — Interfaces 그대로.

- [ ] **Step 4: 통과를 본다**

  Run: `uv run pytest -q src/limn/builds src/limn/runtime src/limn/documents tests/contracts/test_get_write_guard.py tests/architecture`
  Expected: PASS.

- [ ] **Step 5: 커밋** — `perf(builds): a watch thread measures the manuscripts a summary asked about`

### Task 4: Handbook과 ADR-0053

**Files:**
- Create: `docs/adr/0053-manuscript-watch.md` (상태 `제안`)
- Modify: `docs/adr/index.md`, `docs/handbook/build-sync.md`, `docs/handbook/architecture.md`, `docs/handbook/api.md`, `docs/handbook/verification.md`, `docs/handbook/index.md`

- [ ] **Step 1: ADR-0053을 쓴다.** `docs/adr/0052-page-folder-memory-and-display-path.md`의 틀(머리표, 맥락, 결정 표, Trade-off, 대안, 결과). 결정: D1 감시가 재고 요약은 그 값을 읽는다, D2 감시는 답의 근거가 아니다(한도 10초, 넘으면 요청이 직접 잰다), D3 묻지 않은 지 15초가 지난 문서는 놓고 표식을 지운다, D4 빌드의 기준과 pick은 감시의 값을 쓰지 않는다, D5 문서 하나의 측정은 한 번에 하나, D6 GET은 물은 시각만 적고 감시는 읽기만 한다(불변식 10의 해석), D7 새 스레드 하나로 두고 기존 감시에 얹지 않는다. 대안: 기억을 길게, 2초 규칙 그대로, 감시가 살아 있으면 믿는다, 늘 잰다, 기억 없이 싸게, 루트가 같은 문서 합치기, OS 알림. 수치는 spec과 PR에서 옮긴다.
- [ ] **Step 2: Handbook을 고친다**(현재형, 날짜와 전후 수치 없이). spec §문서 동기화의 목록 그대로: `build-sync.md` §원고 변화 감지(기억 문단을 감시·세 상수와 이유·측정 잠금·빌드의 기준과 pick으로 다시 쓴다)와 §폴링 한 번이 읽는 것의 마지막 문단과 §자동 동기화의 `src_mtime`, `architecture.md` §현재 구조·§의존 방향·§HTTP 읽기 능력과 유지 실행, `api.md`의 네 필드 설명과 §GET의 영속 무효과, `verification.md` §불안정한 테스트, `index.md` §파일 지도. 규칙 문단마다 ADR-0053의 조항을 인용한다.
- [ ] **Step 3: 문서 검사를 돌린다**

  Run: `uv run pytest -q tests/architecture src/limn/administration && npm run format:check`
  Expected: PASS.

- [ ] **Step 4: 커밋** — `docs: the manuscript watch in the Handbook and ADR-0053 (proposed)`

### Task 5: 고장 넣기, 차등 비교, 측정

저장소 밖 작업 폴더의 도구를 쓴다(위치는 PR 본문에 적는다). 결과는 PR 본문에 적고 저장소에 넣지 않는다.

- [ ] **Step 1: 변이.** spec §검증 11의 변이를 변이 실행기로 하나씩 넣어 Task 1~3의 시험이 실패하는지 본다. 살아남은 변이가 있으면 시험을 더하고 Task의 커밋에 이어 커밋한다.
  Expected: 살아남은 변이 0.
- [ ] **Step 2: 차등 비교.** `main`(sparse 워크트리, `src`만)과 이 가지를 같은 상태 폴더 사본과 원고 사본으로 띄워 PR #527의 24단계에 원고 편집 단계(파일 내용 고치기, 파일 더하기, 지우기, 다른 문서가 가진 그림 고치기, 편집 뒤 재빌드)를 더해 대조한다. 원고를 고친 단계는 3초 기다린 뒤 받는다.
  Expected: 손으로 쪽 그림을 지운 단계(ADR-0052의 예외)만 다르다.
- [ ] **Step 3: 호출 수와 지연.** 폴링 한 번의 호출 수(원고 파일 3개, 300개, 문서 12개. 감시가 재 둔 폴링과 쉬다 온 첫 폴링), `main`과 번갈아 잰 지연(무거운 읽기 2개 뒤, 계산 스레드 1개 뒤, 세 원고).
  Expected: 호출 수가 spec §후보별 폴링 지연의 값(24, 24, 87)과 같거나 작다. 지연은 "감시, 10초" 줄에 가깝다. 어긋나면 원인을 찾는다.
- [ ] **Step 4: Linux.** 인스턴스를 운영하는 기기에서 `main`과 이 가지를 같은 방식으로 번갈아 재고, 감시 한 바퀴의 시간을 함께 적는다. 한 바퀴가 10초에 가까우면 소유자에게 보고한다. 잴 수 없으면 이유를 PR에 적는다.

### Task 6: 게이트, 독립 리뷰, PR

- [ ] **Step 1: `origin/main`을 가져와 합친다**(움직였으면). 판 시험이 실패하면 `uv sync --group dev --reinstall-package dartwork-limn`.
- [ ] **Step 2: 게이트.** `CLAUDE.md` §검증의 명령 전부(브라우저 시험 포함).
  Expected: 모두 통과. 타입 기준선과 fitness 기준선이 늘지 않는다.
- [ ] **Step 3: 독립 리뷰.** 새 맥락의 리뷰어(가장 강한 등급)가 spec과 가지의 diff를 대조한다. Critical·Important는 고치고, 남기는 것은 이유와 함께 PR에 적는다.
- [ ] **Step 4: PR.** 본문에 무엇과 왜, 응답이 달라지는 곳, 차등 비교 건수, 호출 수와 지연의 표, 시험과 변이, 독립 리뷰, 게이트, 남는 것(문서 수를 따르는 읽기)을 적는다. 머지는 [workflow.md](../../handbook/workflow.md) 절차를 따르고, ADR-0053을 `승인됨`으로 올리는 것과 릴리스 여부는 소유자에게 묻는다.
