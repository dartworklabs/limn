# 핀 마크가 줄을 따라가고 배지를 끌어 위치를 다시 잡는다 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 열린 LaTeX 줄 핀의 PDF 마크를 저장된 좌표 대신 "지금 화면 빌드에서 그 줄이 찍힌 자리"로 계산해 보이고, 마크의 번호 배지를 끌어 핀의 위치를 다시 잡을 수 있게 한다.

**Architecture:** 정방향 SyncTeX(`synctex view`)로 줄 → 쪽·상자를 얻어 그림 핀과 같은 `mark`·`mark_page` 계산 필드로 싣는다. 조회는 배경 패스가 핀 저장소 잠금 밖에서 하고 결과는 메모리 캐시에만 둔다. `GET /api/pins`는 캐시를 읽기만 한다. 핀 레코드와 `rev`는 건드리지 않는다. 드래그는 이미 있는 위치 다시 잡기 경로(`finishRect` → `pick` → `bannerCompare` → `snapBox`)를 배지에서 시작하도록 연다.

**Tech Stack:** Python 3 표준 라이브러리만(`subprocess`·`dataclasses`), 뷰어는 의존성 없는 JS 조각, 시험은 `unittest` + `tests/support/helpers.py`의 `Base`·`extract_js_fn`·Playwright.

**Spec:** [`docs/superpowers/specs/2026-11-15-pin-marks-follow-lines-design.md`](../specs/2026-11-15-pin-marks-follow-lines-design.md) (승인됨), [ADR-0041](../../adr/0041-pin-marks-derived-from-lines.md) (제안)

## Global Constraints

- 런타임 의존성을 더하지 않는다 — `pyproject.toml`의 `dependencies = []`는 그대로. `synctex`는 이미 쓰는 바이너리다.
- 서버 런타임은 표준 라이브러리만 쓴다.
- GET은 파일을 쓰지 않는다 — 새 코드는 `require_writer()`가 걸린 경로에서만 캐시를 채운다.
- 핀 레코드와 `rev`를 바꾸지 않는다. 옛 릴리스가 레코드를 바이트 그대로 되쓸 수 있어야 한다.
- 에이전트 계약은 더하기만 — `pins.md` 열과 핀 레코드 스키마는 바뀌지 않는다.
- 코드·주석·docstring·커밋 메시지는 영어, Handbook은 한국어.
- 커밋은 모두 `git commit -s`, 메시지 끝에 `I agree to the Limn CLA (CLA.md).` 줄.
- 화면이 바뀌는 단계는 네 기기군 PoC(1440×900 마우스, 390×844·320×720 터치, 768×1024·1024×768 터치, 폴더블 344×882·673×841·841×673) 뒤에 머지한다.
- 상자의 위끝은 `v - H`다. `v`는 기준선이다.
- 쪽 크기는 쪽마다 다를 수 있다 — `pick_pages`가 준 목록에서 **그 쪽의** 크기를 쓴다.

## Review Focus

스펙이 전제하지만 어느 작업의 시험도 건드리지 않는, 사람을 물 가능성이 큰 입력부터.

1. **쪽마다 크기가 다른 문서**(가로 쪽을 섞은 원고). 첫 쪽 크기로 나누면 그 쪽의 마크가 어긋난다. → Task 2가 시험을 갖는다.
2. **`\input`으로 쪼갠 원고.** `synctex view -i`에 넘길 파일 이름이 빌드 사본 기준이라, 핀의 절대 경로를 그대로 넘기면 답이 없다. → Task 1(argv 모양)과 Task 3(핀의 경로 → 상대 이름)이 각각 시험을 갖는다.
3. **쪽 폴더가 사라진 문서**(`pick_pages`가 `None`). 패스가 예외로 죽으면 유지 주기가 멈춘다. → Task 3이 시험을 갖는다.
4. **핀이 예산보다 많은 문서.** 매 패스가 같은 앞쪽 핀만 채우면 뒤쪽 핀은 영원히 마크가 없다(기아). → Task 5가 시험을 갖는다.
5. **판정 핀의 배지.** 끌리면 서버가 `400 verdict_fixed`로 거절하는데, 카드에서는 CSS(`cards.css:300`)가 [위치 다시 잡기]를 숨겨 사람은 그 길이 없다고 안다. → Task 7이 시험을 갖는다.

---

### Task 1: 정방향 조회와 답 고르기

**Files:**
- Modify: `src/limn/pins/location/source.py` (`synctex_edit` 옆에 더한다)
- Modify: `src/limn/pins/location/mapping.py`
- Test: `src/limn/pins/tests/test_mapping.py`, `src/limn/pins/location/tests/test_forward.py` (생성)

**Interfaces:**
- Consumes: 없음.
- Produces:
  ```python
  # source.py
  def synctex_view(pdf: Path, line: int, src: str) -> list[tuple[int, float, float, float, float]] | None
  # mapping.py
  @dataclass(frozen=True)
  class ViewBox:
      page: int
      box: tuple[float, float, float, float]   # (x0, y0, x1, y1), points, page top-left origin
  def view_box(hits: Sequence[tuple[int, float, float, float, float]], pages: int) -> ViewBox | None
  def span_box(lo: ViewBox | None, hi: ViewBox | None) -> ViewBox | None
  ```

- [ ] **Step 1: `view_box`·`span_box`의 실패 시험을 쓴다**

`test_mapping.py`에, 스펙의 값을 그대로 넣는다.

```python
def test_view_box_takes_the_first_valid_hit_and_drops_the_rest(self):
    # measured: a tabular row's line answers four times - the row, the whole table, the row again, the row
    # above. Only the first is the line's own box; a union spread the mark over the table (spec 결정 3).
    hits = [(1, 133.77, 232.19, 343.71, 8.86), (1, 133.77, 241.05, 100.0, 8.86), (2, 10.0, 20.0, 30.0, 8.0)]
    got = mapping.view_box(hits, 3)
    self.assertEqual(got.page, 1)
    for a, b in zip(got.box, (133.77, 223.33, 477.48, 232.19), strict=True):  # top = v - H
        self.assertAlmostEqual(a, b, places=6)


def test_view_box_refuses_a_page_out_of_range_a_non_finite_number_and_an_empty_box(self):
    self.assertIsNone(mapping.view_box([(4, 1.0, 2.0, 3.0, 4.0)], 3))
    self.assertIsNone(mapping.view_box([(1, 1.0, float("inf"), 3.0, 4.0)], 3))
    self.assertIsNone(mapping.view_box([(1, 1.0, 2.0, 0.0, 4.0)], 3))
    self.assertIsNone(mapping.view_box([], 3))


def test_span_box_unites_one_page_keeps_lo_across_pages_and_is_none_without_lo(self):
    lo, same, other = (
        ViewBox(1, (10.0, 10.0, 20.0, 20.0)),
        ViewBox(1, (15.0, 30.0, 25.0, 40.0)),
        ViewBox(2, (0.0, 0.0, 5.0, 5.0)),
    )
    self.assertEqual(mapping.span_box(lo, same).box, (10.0, 10.0, 25.0, 40.0))
    self.assertEqual(mapping.span_box(lo, other), lo)
    self.assertIsNone(mapping.span_box(None, same))
```

- [ ] **Step 2: 돌려서 실패를 본다**

Run: `uv run pytest src/limn/pins/tests/test_mapping.py -k view_box -q`
Expected: FAIL — `module 'limn.pins.location.mapping' has no attribute 'view_box'`

- [ ] **Step 3: `ViewBox`·`view_box`·`span_box`를 `mapping.py`에 넣는다**

순수 함수다. `view_box`는 첫 유효 적중의 쪽을 고르고 그 쪽 적중만 합집합으로 묶는다. 상자는 `(h, v - H, h + W, v)`.

- [ ] **Step 4: 돌려서 통과를 본다**

Run: `uv run pytest src/limn/pins/tests/test_mapping.py -k "view_box or span_box" -q`
Expected: PASS

- [ ] **Step 5: `synctex_view`의 시험을 쓴다** (Review Focus 2)

`test_forward.py`에. `synctex_edit`의 관례대로 `subprocess.run`을 패치한다.

```python
def test_synctex_view_asks_by_line_and_column_zero_and_reads_every_page_record(self):
    out = "SyncTeX result begin\nOutput:main.pdf\nPage:14\nx:1\ny:2\nh:133.77\nv:349.81\nW:343.71\nH:8.86\nPage:14\nh:1\nv:2\nW:3\nH:4\n"
    with mock.patch.object(pick_source.subprocess, "run", return_value=mock.Mock(stdout=out)) as run:
        got = pick_source.synctex_view(Path("/b/main.pdf"), 500, "sections/intro.tex")
    self.assertEqual(run.call_args[0][0][:4], ["synctex", "view", "-i", "500:0:sections/intro.tex"])
    self.assertEqual(got, [(14, 133.77, 349.81, 343.71, 8.86), (14, 1.0, 2.0, 3.0, 4.0)])


def test_synctex_view_is_none_when_the_tool_is_missing_times_out_or_gives_no_page(self):
    for boom in (FileNotFoundError(), subprocess.TimeoutExpired("synctex", 10)):
        with mock.patch.object(pick_source.subprocess, "run", side_effect=boom):
            self.assertIsNone(pick_source.synctex_view(Path("/b/main.pdf"), 1, "main.tex"))
    with mock.patch.object(pick_source.subprocess, "run", return_value=mock.Mock(stdout="SyncTeX result begin\n")):
        self.assertIsNone(pick_source.synctex_view(Path("/b/main.pdf"), 1, "main.tex"))
```

- [ ] **Step 6: 돌려서 실패를 본다**

Run: `uv run pytest src/limn/pins/location/tests/test_forward.py -q`
Expected: FAIL — `no attribute 'synctex_view'`

- [ ] **Step 7: `synctex_view`를 `source.py`에 넣는다**

`synctex_edit`와 같은 모양이다 — `subprocess.run(..., capture_output=True, text=True, timeout=10, check=False)`, `except (subprocess.TimeoutExpired, FileNotFoundError): return None`. argv는 `["synctex", "view", "-i", "%d:0:%s" % (line, src), "-o", str(pdf)]`. `src`는 **빌드 루트 기준 상대 경로**다(절대 경로가 아니다). 출력은 `Page:`가 레코드를 열고 뒤따르는 `h`·`v`·`W`·`H`가 그 레코드에 속한다. 네 값이 다 모인 레코드만 담고, 하나도 없으면 `None`.

- [ ] **Step 8: 돌려서 통과를 본다**

Run: `uv run pytest src/limn/pins/location/tests/test_forward.py src/limn/pins/tests/test_mapping.py -q`
Expected: PASS

- [ ] **Step 9: 실물로 한 번 확인한다**

Run: `uv run pytest src/limn/pins/location/tests/ -m tex -q` (없으면 건너뛴다)
그리고 손으로: 시험 원고를 하나 빌드해 `synctex_view`를 파이썬에서 직접 불러 본문 줄과 `tabular` 안의 줄이 서로 다른 상자를 주는지 본다. 결과를 PR 본문에 적는다.

- [ ] **Step 10: 커밋**

```bash
git add src/limn/pins/location/source.py src/limn/pins/location/mapping.py src/limn/pins/location/tests/test_forward.py src/limn/pins/tests/test_mapping.py
git commit -s -m "feat(pins): read a source line's page and box from SyncTeX forward lookup"
```

---

### Task 2: 핀 하나의 마크 계산

**Files:**
- Modify: `src/limn/pins/location/position.py`
- Test: `src/limn/pins/location/tests/test_forward.py`

**Interfaces:**
- Consumes: Task 1의 `ViewBox`, `span_box`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class LineMark:
      page: int
      frac: tuple[float, float, float, float]
  def line_mark(span: ViewBox | None, size: tuple[float, float], exact_page: int | None) -> LineMark | None
  ```
  `exact_page`는 그 핀이 **읽고 있는 바로 그 빌드에서 찍혔을 때** 저장된 `page`이고, 아니면 `None`이다.
  **쪽 안으로 자르는 검사는 여기서 한다** — Task 1의 `view_box`는 쪽 수만 알아 못 했다. 상자를 `(0, 0, pw, ph)`로 자른 뒤 너비나 높이가 남지 않으면 `None`이다.

- [ ] **Step 1: 실패 시험을 쓴다** (Review Focus 1)

```python
def test_line_mark_converts_points_to_that_pages_fractions(self):
    got = position.line_mark(ViewBox(2, (150.0, 100.0, 450.0, 120.0)), (600.0, 800.0), None)
    self.assertEqual((got.page, got.frac), (2, (0.25, 0.125, 0.5, 0.025)))


def test_line_mark_uses_the_size_of_its_own_page_not_the_first(self):
    # a landscape page 2: the caller passes that page's size, so a wide page's mark is not squeezed
    got = position.line_mark(ViewBox(2, (0.0, 0.0, 400.0, 100.0)), (800.0, 600.0), None)
    self.assertEqual(got.frac, (0.0, 0.0, 0.5, 1.0 / 6.0))


def test_line_mark_distrusts_a_same_build_answer_that_lands_on_another_page(self):
    span = ViewBox(5, (10.0, 10.0, 20.0, 20.0))
    self.assertIsNone(position.line_mark(span, (600.0, 800.0), 4))
    self.assertIsNotNone(position.line_mark(span, (600.0, 800.0), 5))


def test_line_mark_is_none_without_a_span_or_a_positive_page_size(self):
    self.assertIsNone(position.line_mark(None, (600.0, 800.0), None))
    self.assertIsNone(position.line_mark(ViewBox(1, (0.0, 0.0, 1.0, 1.0)), (0.0, 800.0), None))
```

- [ ] **Step 2: 돌려서 실패를 본다** — Run: `uv run pytest src/limn/pins/location/tests/test_forward.py -k line_mark -q` / Expected: FAIL

- [ ] **Step 3: `LineMark`·`line_mark`를 `position.py`에 넣는다**

순수 함수이고 시계를 읽지 않는다. 비율 변환은 같은 기능의 `mapping.drag_frac`을 쓴다 — `position.py`의 import 화이트리스트가 `figure`를 막아서 시공 중에 `figure.py`에서 `mapping.py`로 옮겼다(Ruling 9).

- [ ] **Step 4: 돌려서 통과를 본다** — Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/limn/pins/location/position.py src/limn/pins/location/tests/test_forward.py
git commit -s -m "feat(pins): turn a forward lookup into a line pin's mark"
```

---

### Task 3: 캐시와 배경 패스

**Files:**
- Modify: `src/limn/pins/location/lookup.py`
- Test: `src/limn/pins/location/tests/test_forward.py`

**Interfaces:**
- Consumes: Task 1·2 전부.
- Produces:
  ```python
  @dataclass
  class LineMarks:
      """One run's line-pin marks, per (document, build). Memory only: nothing is written to disk."""
      cap: int = 2000
      def get(self, doc: str, build: str, pid: int) -> LineMark | None
      def put(self, doc: str, build: str, pid: int, lo: int, hi: int, mark: LineMark) -> None
      def known(self, doc: str, build: str, pid: int, lo: int, hi: int) -> bool

  @dataclass(frozen=True)
  class MarkContext:
      """What one document's pass needs: the build on screen, its page sizes, its pdf, the build root the SyncTeX
      names are relative to, and whether the manuscript is newer than that build."""
      build: str
      sizes: Sequence[tuple[float, float]]
      pdf: Path
      build_root: Path
      stale_src: bool

  def fill_marks(doc: str, pins: Sequence[Pin], ctx: MarkContext | None, marks: LineMarks, limit: int, deadline: float) -> int
  ```
  `ctx`가 `None`인 것은 그 문서의 쪽을 물을 수 없다는 뜻이다(`pick_pages`가 `None`을 돌려준 경우). `line_mark`에 넘길 쪽 크기는 **1부터 세는** `ctx.sizes[span.page - 1]`로 고른다 — 첫 쪽 크기를 모든 쪽에 쓰지 않는다. `view_box`의 `pages`는 `len(ctx.sizes)`다. `MarkContext`를 만드는 쪽은 Task 5다.

- [ ] **Step 1: 실패 시험을 쓴다** (Review Focus 3)

```python
def test_fill_marks_does_nothing_while_the_manuscript_is_newer_than_the_build(self):
    # the two line coordinate systems have diverged: the build's lines are not today's lines
    n = lookup.fill_marks("d", [self.open_pin(1, lo=10, hi=12)], self.ctx(stale_src=True), self.marks, 200, self.far)
    self.assertEqual(n, 0)
    self.assertIsNone(self.marks.get("d", "b1", 1))


def test_fill_marks_skips_a_stale_pin_a_closed_pin_and_a_region_pin(self):
    pins = [self.stale_pin(1), self.closed_pin(2), self.region_pin(3)]
    with mock.patch.object(pick_source, "synctex_view", side_effect=AssertionError("no forward lookup")):
        self.assertEqual(lookup.fill_marks("d", pins, self.ctx(), self.marks, 200, self.far), 0)


def test_fill_marks_survives_a_document_whose_pages_are_gone(self):
    # pick_pages answered None: the caller passes no context and the pass neither raises nor caches
    self.assertEqual(lookup.fill_marks("d", [self.open_pin(1)], None, self.marks, 200, self.far), 0)


def test_fill_marks_asks_once_for_a_one_line_pin_and_twice_for_a_span(self):
    with mock.patch.object(pick_source, "synctex_view", return_value=[(1, 10.0, 20.0, 30.0, 8.0)]) as view:
        lookup.fill_marks(
            "d", [self.open_pin(1, lo=7, hi=7), self.open_pin(2, lo=9, hi=11)], self.ctx(), self.marks, 200, self.far
        )
    self.assertEqual([c[0][1] for c in view.call_args_list], [7, 9, 11])


def test_fill_marks_passes_the_build_relative_name_not_the_pins_absolute_path(self):
    with mock.patch.object(pick_source, "synctex_view", return_value=[(1, 10.0, 20.0, 30.0, 8.0)]) as view:
        lookup.fill_marks(
            "d", [self.open_pin(1, file=str(self.root / "sections/intro.tex"))], self.ctx(), self.marks, 200, self.far
        )
    self.assertEqual(view.call_args[0][2], "sections/intro.tex")


def test_fill_marks_does_not_ask_again_for_a_pin_it_already_has_at_the_same_lines(
    self,
): ...  # second call makes no synctex_view call; after the pin's lo moves within the same build it asks again
```

- [ ] **Step 2: 돌려서 실패를 본다** — Run: `uv run pytest src/limn/pins/location/tests/test_forward.py -k fill_marks -q` / Expected: FAIL

- [ ] **Step 3: `LineMarks`·`MarkContext`·`fill_marks`를 `lookup.py`에 넣는다**

`fill_marks`는 `ctx`가 `None`이거나 `ctx.stale_src`면 0을 돌려준다. 대상은 열린 줄 핀 중 `stale`이 아니고 `marks.known(...)`이 아닌 것. 핀당 `lo`(와 `hi`가 다르면 `hi`)를 `synctex_view`로 묻고 `view_box`·`span_box`·`line_mark`로 접는다. `limit`개를 채우거나 `time.monotonic() >= deadline`이면 멈춘다. 캐시는 `cap`을 넘으면 오래된 것부터 버린다. 핀 파일도 핀 저장소도 열지 않는다.

- [ ] **Step 4: 돌려서 통과를 본다** — Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/limn/pins/location/lookup.py src/limn/pins/location/tests/test_forward.py
git commit -s -m "feat(pins): cache line pins' marks for the build on screen"
```

---

### Task 4: 응답에 붙이기

**Files:**
- Modify: `src/limn/pins/listing/projection.py` (`element_marks` 옆), `src/limn/pins/listing/service.py`, `src/limn/pins/runtime.py`, `src/limn/pins/needs.py`
- Test: `src/limn/pins/listing/tests/test_line_marks.py` (생성), `tests/contracts/test_contract_snapshot.py`

**Interfaces:**
- Consumes: Task 3의 `LineMarks.get`.
- Produces:
  ```python
  # projection.py
  def line_marks(r: Row, mark: LineMark | None) -> Json
  def no_line_marks(key: str, pid: int) -> LineMark | None       # the default, like no_figure_maps
  # pins_payload gains, after figure_map:
  #   line_map: Callable[[str, int], LineMark | None] = no_line_marks
  # runtime.py
  def line_mark_of(self, key: str, pid: int) -> LineMark | None
  ```

- [ ] **Step 1: 실패 시험을 쓴다**

```python
def test_a_line_pins_record_carries_the_marks_the_build_found(self):
    got = view.line_marks({"lo": 10, "hi": 12}, LineMark(3, (0.1, 0.2, 0.3, 0.04)))
    self.assertEqual(got, {"mark": [0.1, 0.2, 0.3, 0.04], "mark_page": 3})


def test_a_line_pin_without_a_mark_and_a_figure_pin_get_nothing_from_line_marks(self):
    self.assertEqual(view.line_marks({"lo": 10, "hi": 12}, None), {})
    self.assertEqual(view.line_marks({"lo": 10, "hi": 12, "el": {"id": "x"}}, LineMark(3, (0.1, 0.2, 0.3, 0.04))), {})


def test_the_payload_leaves_the_record_and_rev_untouched(self):
    before = self.pin(1)["rev"]
    self.api("/api/pins")
    self.assertEqual(self.pin(1)["rev"], before)
    self.assertNotIn("mark", self.raw_record(1))
```

- [ ] **Step 2: 돌려서 실패를 본다** — Run: `uv run pytest src/limn/pins/listing/tests/test_line_marks.py -q` / Expected: FAIL

- [ ] **Step 3: `line_marks`를 넣고 `pins_payload`에 `line_map`을 잇는다**

`element_marks`와 같은 자리에서 `rec.update(...)`한다. **`el`이 있는 핀(그림 핀)에는 붙이지 않는다** — 그 핀은 `element_marks`가 소유한다. `est` 식은 고치지 않는다. `service.py`가 `runtime.line_mark_of`를 넘기고, `needs.py`에 그 콜백 타입을 선언한다.

- [ ] **Step 4: 돌려서 통과를 본다** — Expected: PASS

- [ ] **Step 5: 계약 스냅샷을 갱신한다**

Run: `uv run pytest tests/contracts/ -q`
스냅샷이 달라지면 그 차이가 `mark`·`mark_page`가 붙은 것뿐인지 확인한 뒤 갱신한다. `pins.md` 바이트가 바뀌면 그것은 결함이다 — 되돌린다. 새 되돌리기 시험(`test_*_rollback.py`)은 만들지 않는다 — 레코드에 새 필드를 넣지 않으므로 지킬 바이트가 없고, Step 1의 `assertNotIn("mark", self.raw_record(1))`가 그것을 붙잡는다.

- [ ] **Step 6: 커밋**

```bash
git add src/limn/pins/listing/ src/limn/pins/runtime.py src/limn/pins/needs.py tests/
git commit -s -m "feat(api): carry a line pin's current mark in GET /api/pins"
```

---

### Task 5: 패스를 빌드 완료와 유지 주기에 걸기

**Files:**
- Modify: `src/limn/pins/maintenance.py`, `src/limn/pins/application.py`, `src/limn/pins/runtime.py`
- Test: `src/limn/pins/tests/test_maintenance_marks.py` (생성)

**Interfaces:**
- Consumes: Task 3·4 전부.
- Produces:
  ```python
  # runtime.py — the glue no other task owns: build one document's MarkContext and fill it
  def fill_line_marks(self, limit: int = MARK_LIMIT, seconds: float = MARK_SECONDS) -> int
  # maintenance.py
  #   PinMaintenance gains  marks: Callable[[], int] = lambda: 0
  MARK_LIMIT = 200
  MARK_SECONDS = 10.0
  ```
  `fill_line_marks`는 띄운 문서마다 `document_facts.pick_pages(None)`으로 쪽 폴더와 쪽 크기(pt)를 얻고, 기존 원고 변화 감지로 `stale_src`를 얻어 `MarkContext`를 만든 뒤 `fill_marks`를 부른다. `pick_pages`가 `None`이면 그 문서에는 `None`을 넘긴다.

- [ ] **Step 1: 실패 시험을 쓴다** (Review Focus 4)

```python
def test_the_mark_pass_runs_outside_the_pin_store_lock(self):
    # a pin write on another thread must not wait on the pass, so probe from a thread
    # (a re-entrant lock would hand itself to the calling thread and hide this)
    store, free = self.store(), []

    def probe():
        got = store.lock.acquire(blocking=False)
        if got:
            store.lock.release()
        free.append(got)

    def marks():
        t = threading.Thread(target=probe)
        t.start()
        t.join()
        return 0

    PinMaintenance(store=lambda: store, days=7, marks=marks).run()
    self.assertEqual(free, [True])


def test_the_pass_stops_at_its_budget_and_takes_the_next_pins_on_the_following_run(self):
    pins = [self.open_pin(i) for i in range(1, 6)]
    first = maintenance_pass(pins, limit=2)
    second = maintenance_pass(pins, limit=2)
    self.assertEqual((first, second), (2, 2))
    self.assertEqual(self.marked_ids(), [1, 2, 3, 4])  # no starvation: it moves on, it does not redo 1 and 2


def test_a_new_build_on_screen_fills_the_marks_without_waiting_for_the_periodic_run(
    self,
): ...  # the build callback path calls the pass once for that document


def test_a_failing_pass_does_not_stop_upkeep(self):
    with mock.patch.object(..., side_effect=OSError("boom")):
        PinMaintenance(...).run()  # no raise; the pins file is still maintained
```

- [ ] **Step 2: 돌려서 실패를 본다** — Expected: FAIL

- [ ] **Step 3: `run()`에 패스를 더한다**

`with store.lock:` **블록이 끝난 뒤** 부른다. 예외는 기존 `except Exception` 안에서 삼키되 `diagnostics.emit`에 따로 적는다. 빌드가 새 쪽을 화면에 올리는 경로에서도 같은 함수를 한 번 부른다. 다음 패스가 이어 가도록, 채우지 못한 핀의 자리는 캐시가 기억하지 않는다(다음 패스가 앞에서부터 훑어도 이미 채운 핀은 `known`으로 건너뛴다).

- [ ] **Step 4: 돌려서 통과를 본다** — Expected: PASS

- [ ] **Step 4b: 화면이 따라오는지 브라우저 시험으로 고정한다** (목표 2)

뷰어 코드를 고치지 않아도 화면이 바뀌므로, 그 결과를 시험이 붙잡아야 한다. `test_viewer_browser.py`에:

```python
def test_a_line_pins_mark_moves_to_the_new_build_and_stops_being_dotted(self):
    # pin on page 1, add lines above it, rebuild: the mark stands on its new page, solid
    ...
    self.assertEqual(page.locator(".mark[data-pin='1']").count(), 1)
    self.assertFalse("est" in (page.locator(".mark[data-pin='1']").get_attribute("class") or ""))

def test_a_pin_the_pass_could_not_follow_keeps_its_saved_box_and_stays_dotted(self):
```

Run: `uv run pytest src/limn/viewer/tests/test_viewer_browser.py -k mark -q` / Expected: PASS

- [ ] **Step 5: 실물로 확인한다 — 기다리지 않는다**

일회용 인스턴스를 띄워: 핀 세 개를 찍고 → 원고 위쪽에 20줄을 넣고 → 재빌드하고 → `GET /api/pins`에 `mark`·`mark_page`가 새 쪽·상자로 붙는지, `pins.jsonl`의 `rev`가 그대로인지 본다. 예약 회차를 기다리지 않고 빌드를 손으로 돌린다. 결과(전후 `mark`, `rev`, 패스 시간)를 PR 본문에 적는다.

- [ ] **Step 6: 커밋**

```bash
git add src/limn/pins/maintenance.py src/limn/pins/application.py src/limn/pins/runtime.py src/limn/pins/tests/
git commit -s -m "feat(pins): fill line marks after a build and in the upkeep cycle"
```

- [ ] **Step 7: 1단계 PoC를 소유자에게 보인다**

네 기기군에서 전후를 나란히: ① 마크가 제자리로 가고 점선이 사라진 쪽, ② 목록 순서가 바뀐 패널, ③ 카드의 쪽 라벨. 바뀐 자리는 따뜻한 색 하나의 옅은 반투명 면(밝은 화면 약 5%)으로 칠하고 번호를 단다 — **테두리는 긋지 않는다**. 차이 목록(잰 값)과 PoC 주소를 함께 낸다. `code-ui-poc` 스킬의 `ui_poc.py compare`를 쓴다. **소유자가 본 뒤에 다음 Task로 간다.**

---

### Task 6: pick 답의 정방향 상자

**Files:**
- Modify: `src/limn/pins/location/resolve.py`, `src/limn/pins/location/http.py`
- Test: `src/limn/pins/location/tests/test_forward.py`, `tests/contracts/test_contract_snapshot.py`

**Interfaces:**
- Consumes: Task 1·2.
- Produces: pick 응답의 `levels[]`에 붙는 `mark`(`[x, y, w, h]`)와 `mark_page`. 단계마다 그 범위의 정방향 상자이고, 못 구하면 그 단계에 없다.

- [ ] **Step 1: 실패 시험을 쓴다**

```python
def test_every_pick_level_carries_the_box_its_range_will_actually_stand_on(self):
    answer = self.pick(lo=10, hi=12)
    self.assertEqual(answer["levels"][0]["mark_page"], 1)
    self.assertEqual(len(answer["levels"][0]["mark"]), 4)


def test_a_level_whose_forward_lookup_fails_carries_no_box_and_the_pick_still_answers(self):
    with mock.patch.object(pick_source, "synctex_view", return_value=None):
        answer = self.pick(lo=10, hi=12)
    self.assertNotIn("mark", answer["levels"][0])


def test_the_forward_lookups_are_capped_at_two_per_level(self):
    with mock.patch.object(pick_source, "synctex_view", return_value=[(1, 1.0, 2.0, 3.0, 4.0)]) as view:
        self.pick(lo=10, hi=12)
    self.assertLessEqual(len(view.call_args_list), 2 * len(self.levels_of(answer)))
```

- [ ] **Step 2: 돌려서 실패를 본다** — Expected: FAIL

- [ ] **Step 3: pick 답에 단계별 상자를 넣는다**

`resolve.pick`이 값으로 돌려주고 `http.py`가 본문에 싣는다. 영역 핀을 받는 문서와 그림 문서에는 붙이지 않는다(그 문서는 이미 `el`로 스냅한다). 실패는 조용히 빠진다 — pick 자체를 거절하지 않는다.

- [ ] **Step 4: 돌려서 통과를 본다** — Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/limn/pins/location/ tests/
git commit -s -m "feat(api): tell a pick answer where each level's range stands on the page"
```

---

### Task 7: 배지 드래그

**Files:**
- Modify: `src/limn/viewer/js/selection.js` (`:41`의 배지 반환, `finishRect`), `src/limn/viewer/js/list.js` (`:452`의 `mousedown` 캡처), `src/limn/viewer/js/figure.js` (`snapBox`), `src/limn/viewer/js/repick.js`
- Test: `src/limn/viewer/tests/test_viewer_input.py` (순수 로직), `src/limn/viewer/tests/test_viewer_browser.py` (드래그)

**Interfaces:**
- Consumes: Task 6의 단계별 `mark`.
- Produces: 순수 함수 `badgeDrop(frac, dx, dy)` — 핀의 상자를 끌린 만큼 옮긴 새 상자. `dx`·`dy`는 쪽 대비 비율이고, 끝이 쪽을 넘으면 크기를 지킨 채 안으로 자른다. 최상위 `function`으로 선언하고 전역을 읽지 않는다(`extract_js_fn`으로 시험하기 위해).

- [ ] **Step 1: 순수 로직 시험을 쓴다** (`helpers_js` 하네스)

```python
def test_a_badge_drop_moves_the_pins_box_by_the_drag_and_stays_on_the_page(self):
    got = self.run_js(["badgeDrop"], "[badgeDrop([0.1,0.1,0.2,0.05],0.3,0.2),badgeDrop([0.9,0.95,0.2,0.1],0.3,0.3)]")
    self.assertEqual(got[0], [0.4, 0.3, 0.2, 0.05])
    self.assertEqual(got[1], [0.8, 0.9, 0.2, 0.1])  # clamped: the box keeps its size and stays inside
```

- [ ] **Step 2: 돌려서 실패를 본다** — Run: `uv run pytest src/limn/viewer/tests/test_viewer_input.py -k badgeDrop -q` / Expected: FAIL

- [ ] **Step 3: `badgeDrop`을 `selection.js`에 넣고 배지에서 드래그를 연다**

- 마우스: `selection.js:41`의 `if(badge&&(mouse||!SELMODE||!e.isPrimary))return;`에서 마우스 배제를 걷고, `list.js:452`의 `mousedown` 캡처가 `preventDefault`하는 대상에서 드래그 시작을 뺀다. 문턱은 기존 `TAP_SLOP`(8px)을 쓴다 — 새 값을 만들지 않는다.
- 터치: `SELMODE`에서 이미 도는 `DRAG.badge` 경로를 쓰되, **`REPICK`이 그 핀의 것일 때만** 받는다.
- 두 경로 모두 새 사각형을 그리는 대신 `badgeDrop`으로 **핀의 상자를 옮겨** `finishRect`와 같은 모양으로 `pick`한다.
- **판정 핀의 배지는 받지 않는다** (Review Focus 5). 카드에서 CSS(`cards.css:300`)가 [위치 다시 잡기]를 숨기는 것과 같은 판정을 JS에서 한다.
- 배지에서 시작한 드래그는 기존 `SWALLOW_CLICK=BADGE_HOLD` 규칙으로 뒤따르는 클릭을 삼킨다(카드로 뛰지 않게).

- [ ] **Step 4: `snapBox`가 줄 답에도 스냅하게 한다**

지금은 `el`이 없으면 바로 반환한다. 기본 단계의 `mark`가 있으면 그 상자로 스냅한다. 호출처(`bannerCompare`)는 그대로다.

- [ ] **Step 5: 브라우저 시험을 쓴다**

`test_viewer_browser.py`의 `drag`·`drag_touch` 관례를 따른다.

```python
def test_a_mouse_drag_on_a_badge_repoints_the_pin_and_snaps_the_box_to_the_new_range(self):
    ...   # drag from the badge; the banner shows 지금/새 위치; [이 위치로 바꾸기] saves; the mark lands on the snapped box
def test_a_badge_drag_does_not_jump_to_the_card(self):
def test_a_finger_drag_on_a_badge_moves_the_pin_only_inside_repick_mode(self):
def test_a_verdict_pins_badge_cannot_be_dragged(self):
```

- [ ] **Step 6: 돌려서 통과를 본다**

Run: `uv run pytest src/limn/viewer/tests/test_viewer_input.py src/limn/viewer/tests/test_viewer_browser.py -q`
그리고 회귀: `uv run pytest src/limn/viewer/tests/test_viewer_repick_race.py src/limn/viewer/tests/test_viewer_csp.py -q`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add src/limn/viewer/js/ src/limn/viewer/tests/
git commit -s -m "feat(viewer): drag a pin's number badge to repoint it"
```

- [ ] **Step 8: 2단계 PoC를 소유자에게 보인다**

네 기기군 전후 + 확인 모양 두 후보(ⓐ 배너에서 확인하고 저장, ⓑ 놓는 순간 저장 + 되돌리기 칩). 추천안을 첫째에 둔다. Task 5 Step 7의 표시 규칙을 그대로 따른다. **소유자가 고른 뒤에 다음 Task로 간다.**

---

### Task 8: Handbook·ADR 동기화와 전체 게이트

**Files:**
- Modify: `docs/handbook/domain.md`, `build-sync.md`, `api.md`, `viewer.md`, `architecture.md`, `index.md`, `verification.md`, `skill/SKILL.md`, `skill/SKILL.ko.md`, `docs/adr/0041-pin-marks-derived-from-lines.md`

- [ ] **Step 1: 현재 상태를 고친다**

- `domain.md` — §줄 번호 재동기화 아래에 "줄 핀의 마크도 읽을 때 계산한다"를 §그림 핀의 요소 위치와 나란히. §줄 맞춤의 한계에 `stale` 핀은 조회하지 않는 이유와 빈 줄이 위 문단 상자를 받는 한계.
- `build-sync.md` — §위치 추정 (`est`)의 첫 문장("핀 마크는 드래그 당시의 `frac`에 고정된다")을 고친다. 패스가 도는 자리·예산·늦음. **그리고 정본 drift를 바로잡는다** — 지금 377행은 `same_source`·`est_basis`가 `position.py`에 있다고 적지만, `_same_source`는 `builds/queries.py:79`에 있고 `est_basis`는 없다(가장 가까운 것이 같은 파일의 `position_basis`).
- `api.md` — `mark`·`mark_page`의 적용 범위가 그림 핀에서 줄 핀으로 넓어진 것, pick 답의 단계별 상자.
- `viewer.md` — §조작 한눈에·§패널 정리에 배지 드래그(마우스는 바로, 터치는 모드 안에서), §상태 표현의 점선 설명.
- `architecture.md`·`index.md` §파일 지도 — `pins/location/**`의 책임에 정방향 조회와 캐시.
- `verification.md` — 새 시험이 드는 게이트.
- `skill/SKILL.md`·`skill/SKILL.ko.md` — 에이전트가 보는 `mark`의 뜻. **두 언어를 함께.**
- ADR-0041의 상태를 `승인됨`으로 올린다.

- [ ] **Step 2: 전체 게이트를 돌린다**

```bash
uv run pytest -q -rs
bash src/limn/administration/tests/test_instances.sh
uv run ruff check && uv run ruff format --check
uv run shellcheck src/limn/administration/instances.sh src/limn/administration/instance_*.sh src/limn/administration/tests/test_instances.sh
uv run python tools/check_boundaries.py
uv run mypy && uv run mypy --platform darwin
npm ci --ignore-scripts && npm run typecheck
uv run python tools/strict_ratchet.py
```
Expected: 전부 통과. 하나라도 빨가면 고친다 — 시험을 줄이거나 건너뛰지 않는다.

- [ ] **Step 3: 커밋**

```bash
git add docs/ skill/
git commit -s -m "docs: line pins' marks follow their lines"
```
