# 핀 상자를 줄 범위에 맞추기 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LaTeX 문서의 핀 마크와 '새 핀' 상자가, 드래그한 사각형 대신 그 핀이 가리키는 줄 범위가 PDF에서 차지하는 영역을 덮는다.

**Architecture:** 정방향 SyncTeX(`synctex view`)로 소스 줄의 박스를 받아, 순수 계산이 쪽·단 본문 박스를 거르고 여백을 더해 조각으로 합친다. 결과는 저장하지 않고 `pick`·`snippet`·`pins` 응답에 `boxes`로 더한다. 뷰어는 조각마다 `.mark`를 그리고 첫 조각을 기준으로 삼는다.

**Tech Stack:** Python 3.10+ 표준 라이브러리만(`subprocess`), 외부 실행 파일 `synctex`(이미 쓴다), TypeScript 뷰어 모듈.

**Spec:** [docs/superpowers/specs/2026-11-17-pin-mark-snap-to-range.md](../specs/2026-11-17-pin-mark-snap-to-range.md) (승인됨 2026-11-17), [ADR-0049](../../adr/0049-pin-marks-follow-the-range.md)

## Global Constraints

- 서버 런타임은 표준 라이브러리만 쓴다(`pyproject.toml`의 `dependencies = []`). 새 외부 도구를 요구하지 않는다.
- 에이전트 계약은 **더하기만** 한다. `frac`·`mark`·`mark_page`·`page`의 뜻과 모양을 바꾸지 않고, `POST /api/pin`의 저장 필드 화이트리스트도 바꾸지 않는다.
- 핀 레코드에 새 필드를 저장하지 않는다. `boxes`는 읽을 때 계산한다.
- 기능은 다른 기능을 import하지 않는다. 핀은 빌드의 사실을 `src/limn/pins/needs.py`의 선언으로만 받는다.
- 어떤 GET도 영속 상태를 바꾸지 않는다. 캐시는 메모리에만 둔다.
- 코드·주석·docstring·테스트 이름·커밋 메시지는 영어. Handbook은 한국어.
- 커밋은 모두 `git commit -s`로 만들고 메시지 끝에 `I agree to the Limn CLA (CLA.md).` 줄을 둔다.
- 여백 = (글줄 `v` 차이의 중앙값 − 글줄 높이 평균) ÷ 2. 글줄이 하나면 글줄 높이 × 0.175.
- 박스 좌표는 PDF 포인트(쪽 좌상단 기준)로 받아 쪽 대비 비율 `frac: [x, y, w, h]`로 내보낸다.

## Review Focus

spec이 전제하지만 어느 task의 시험도 건드리지 않는 입력들. 줄마다 그 줄을 맡는 task에 시험을 더했다.

1. **쪽 경계를 넘는 범위** — 문단이 쪽을 넘으면 조각이 서로 다른 `page`를 갖는다. 뷰어가 지금 안 보이는 쪽의 조각을 그리려다 좌표를 잘못 놓으면 안 된다. (Task 1, Task 6)
2. **빈 줄·주석만 있는 줄** — `synctex view`는 아무것도 답하지 않는 것이 아니라 **조상을 찾아 엉뚱한 박스를 답한다**. 실측에서 두 단 10pt A4 문서의 빈 줄 하나가 레코드 17개를 돌려주었고, 그것은 **앞 문단의** 찍힌 글줄들이었다(다른 빈 줄은 44개, 쪽·단 본문 박스까지). 평범한 글줄 상자라 높이 거르기에 걸리지 않고 범위의 진짜 박스와의 틈도 이웃 판정 안이라, 그냥 물으면 마크가 두 문단을 한 조각으로 덮는다. 그래서 주석을 떼면 글이 남지 않는 줄은 **묻기 전에 뺀다**. `boxes`가 없는 응답이지 빈 배열이 아니라는 것은 그대로다. (Task 3)
3. **`.synctex.gz`가 없거나 깨진 빌드** — 보기 전용 PDF로 올린 문서, 오래된 빌드. `synctex`가 실패해도 pick 자체는 지금처럼 답해야 한다. (Task 2, Task 3)
4. **같은 핀이 목록과 pick에서 다른 상자를 받는 경우** — 핀 목록은 "범위가 그대로 설 때만" 상자를 내고 pick은 빌드 줄을 쓴다. 두 경로가 같은 상황에서 어긋나면 상자가 깜빡인다. (Task 5)
5. **조각 한도를 넘는 float** — 표는 칸마다 박스가 흩어진다. 한도를 넘으면 조용히 드래그 사각형으로 떨어져야지, 조각 수백 개를 내려보내면 안 된다. (Task 1, Task 8)

---

### Task 1: 박스 계산 (순수)

**Files:**
- Modify: `src/limn/pins/location/mapping.py`
- Test: `src/limn/pins/location/tests/test_mapping.py` (없으면 생성; 기존 테스트 파일 위치는 `rg --files src/limn/pins/location/tests`로 확인)

**Interfaces:**
- Consumes: 기존 `paired_lines(built, now) -> list[int | None]`, `_shared_ends`
- Produces:
  - `Box = tuple[int, float, float, float, float]` — `(page, x, y, w, h)`, PDF 포인트, 쪽 좌상단 기준
  - `line_boxes(rows: Sequence[Box], page_h: float) -> list[Box]`
  - `range_pad(rows: Sequence[Box]) -> float`
  - `merge_boxes(rows: Sequence[Box], pad: float, page_w: float, page_h: float, limit: int) -> list[Box]`
  - `built_range(built: Sequence[str], now: Sequence[str], lo: int, hi: int) -> tuple[int, int] | None`

- [ ] **Step 1: Write the failing tests**

```python
def test_line_boxes_drops_page_body_boxes():
    # a page body box (full text width, most of the page height) and two text lines
    rows = [(1, 72.0, 100.0, 467.0, 548.0), (1, 72.0, 231.0, 228.6, 8.86), (1, 72.0, 243.0, 228.6, 8.86)]
    assert line_boxes(rows, 841.89) == rows[1:]


def test_range_pad_halves_the_blank_between_lines():
    rows = [(1, 72.0, 231.0, 228.6, 8.86), (1, 72.0, 242.96, 228.6, 8.86)]
    assert range_pad(rows) == 1.55


def test_range_pad_falls_back_to_a_share_of_the_line_height():
    assert range_pad([(1, 72.0, 231.0, 228.6, 12.75)]) == 2.23


def test_merge_boxes_joins_one_column_and_keeps_two():
    # first column's last line, then the second column's block
    rows = [(1, 72.0, 665.8, 228.6, 8.86), (1, 310.6, 127.9, 228.6, 8.86), (1, 310.6, 139.8, 228.6, 8.86)]
    out = merge_boxes(rows, 0.0, 595.28, 841.89, 8)
    assert len(out) == 2


def test_merge_boxes_keeps_pages_apart():
    rows = [(1, 72.0, 700.0, 228.6, 8.86), (2, 72.0, 100.0, 228.6, 8.86)]
    assert [b[0] for b in merge_boxes(rows, 0.0, 595.28, 841.89, 8)] == [1, 2]


def test_merge_boxes_clamps_padding_to_the_page():
    out = merge_boxes([(1, 72.0, 2.0, 228.6, 8.86)], 5.0, 595.28, 841.89, 8)
    assert out[0][2] == 0.0


def test_merge_boxes_gives_up_over_the_limit():
    rows = [(1, 72.0 + 30 * i, 100.0 + 30 * i, 20.0, 8.0) for i in range(9)]
    assert merge_boxes(rows, 0.0, 595.28, 841.89, 8) == []


def test_built_range_maps_todays_lines_back():
    built = ["a", "b", "c", "d"]
    now = ["x", "a", "b", "c", "d"]  # one line added at the top
    assert built_range(built, now, 2, 4) == (1, 3)


def test_built_range_is_none_when_the_text_moved_away():
    assert built_range(["a", "b"], ["q", "r"], 1, 2) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest src/limn/pins/location/tests/test_mapping.py -q`
Expected: FAIL — `line_boxes` 등이 정의되지 않음

- [ ] **Step 3: Implement the four functions in `src/limn/pins/location/mapping.py`**

`line_boxes`: 높이가 `page_h`의 25% 이상인 박스를 버린다(쪽·단 본문). 폭은 보지 않는다 — 실측에서 `\end{document}` 는 단 본문 박스(`W:228.64`, 쪽 폭의 38%)를 돌려주므로 폭 기준은 그것을 놓치고 단 전체가 덮인다. 글줄은 쪽 높이의 1.05%(`H:8.856` / 841.89)라 높이만으로 두 자릿수 차이가 난다. 그 기준은 범위 안 박스끼리 견주지 않는다 — float은 칸마다 크기가 제각각이라 중앙값 비교가 깨진다. 대신 쪽 높이의 4분의 1보다 큰 float 박스도 버려지므로 그 핀은 드래그 사각형으로 떨어진다(spec 이 float 에 허용한 폴백).

`merge_boxes`: 같은 `page`에서 가로로 겹치고(구간이 만남) 세로로 이어지는(틈이 글줄 높이 이하) 박스를 합친다. 합친 뒤 `pad`를 사방에 더하고 `0..page_w`·`0..page_h`로 자른다. 결과가 `limit`을 넘으면 `[]`.

`built_range`: `paired_lines(built, now)`를 뒤집어 `now` 줄 → `built` 줄 표를 만들고, `lo..hi`(1-based)가 짝지어진 `built` 줄의 처음과 끝을 돌려준다. 짝이 하나도 없으면 `None`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest src/limn/pins/location/tests/test_mapping.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/limn/pins/location/mapping.py src/limn/pins/location/tests/test_mapping.py
git commit -s -m "feat(pins): compute mark boxes from forward-SyncTeX rows

I agree to the Limn CLA (CLA.md)."
```

---

### Task 2: 정방향 SyncTeX 호출

**Files:**
- Modify: `src/limn/pins/location/source.py`
- Test: `src/limn/pins/location/tests/test_source.py`

**Interfaces:**
- Consumes: Task 1의 `Box`
- Produces: `synctex_view(pdf: Path, tex: str, line: int) -> list[Box]`

- [ ] **Step 1: Write the failing test**

`synctex`가 없는 환경에서도 도는 시험이어야 한다. `subprocess.run`을 monkeypatch해 CLI 출력 본문을 주고 파싱만 본다.

```python
SAMPLE = "Output:x.pdf\nPage:2\nx:144.0\ny:218.4\nh:72.0\nv:220.4\nW:228.6\nH:8.86\n"


def test_synctex_view_reads_page_and_box(monkeypatch):
    monkeypatch.setattr(source.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=SAMPLE))
    assert source.synctex_view(Path("x.pdf"), "x.tex", 30) == [(2, 72.0, 211.54, 228.6, 8.86)]


def test_synctex_view_is_empty_when_the_tool_is_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(source.subprocess, "run", boom)
    assert source.synctex_view(Path("x.pdf"), "x.tex", 30) == []
```

`v`는 박스의 **아랫변**이므로 `y = v - H`다(첫 시험의 211.54 = 220.4 − 8.86).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest src/limn/pins/location/tests/test_source.py -q -k synctex_view`
Expected: FAIL — `synctex_view`가 없음

- [ ] **Step 3: Implement `synctex_view(pdf, tex, line)` in `src/limn/pins/location/source.py`**

`["synctex", "view", "-i", "%d:0:%s" % (line, tex), "-o", str(pdf)]`를 `synctex_edit`와 같은 꼴로 돌린다 — `capture_output=True`, `text=True`, `timeout=10`, `check=False`. `TimeoutExpired`·`FileNotFoundError`는 빈 목록. 출력에서 `Page:`·`h:`·`v:`·`W:`·`H:` 다섯을 모은 레코드마다 `(page, h, v - H, W, H)`를 낸다.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest src/limn/pins/location/tests/test_source.py -q -k synctex_view`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/limn/pins/location/source.py src/limn/pins/location/tests/test_source.py
git commit -s -m "feat(pins): read forward-SyncTeX boxes for a source line

I agree to the Limn CLA (CLA.md)."
```

---

### Task 3: pick 응답의 기본 단계에 `boxes`

**Files:**
- Modify: `src/limn/pins/location/resolve.py`, `src/limn/pins/location/http.py`
- Test: `src/limn/pins/location/tests/` 의 pick 시험 파일

**Interfaces:**
- Consumes: Task 1의 `line_boxes`·`range_pad`·`merge_boxes`, Task 2의 `synctex_view`
- Produces: `Picked`에 `boxes: list[tuple[int, tuple[float, float, float, float]]]` 필드(쪽과 `frac`). `http.py`가 `[{"page": p, "frac": [...]}, …]`로 직렬화한다. 빈 목록이면 응답에 키를 싣지 않는다.

- [ ] **Step 1: Write the failing test**

`resolve.pick`의 기존 시험 원고(`.tex`·`.pdf` 픽스처)를 그대로 쓴다. `synctex_view`를 monkeypatch해 줄마다 고정 박스를 주고, 응답의 기본 단계에 `boxes`가 실리는지, 빈 답에는 키가 없는지 본다.

```python
def test_pick_carries_boxes_for_the_default_level(...):
    # synctex_view가 줄마다 한 박스를 주면 기본 단계에 조각 하나가 실린다
    assert body["levels"][default_index]["boxes"] == [{"page": 1, "frac": [...]}]

def test_pick_has_no_boxes_when_forward_synctex_is_silent(...):
    # 빈 줄만 고른 범위: synctex_view가 아무것도 답하지 않는다
    assert "boxes" not in body["levels"][default_index]

def test_pick_still_answers_when_synctex_view_fails(...):
    # synctex_view가 FileNotFoundError로 빈 목록을 내도 pick의 나머지 응답은 그대로다
    assert body["lo"] and "boxes" not in body["levels"][default_index]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest src/limn/pins/location/tests -q -k boxes`
Expected: FAIL

- [ ] **Step 3: Compute the boxes in `resolve.pick`**

기본 단계(`traced.levels` 중 `traced.default_level`)의 `lo..hi`를 **빌드 줄로 되돌려** 쓴다. `pick`은 `publication.built_lines(found.path)`를 이미 읽었다 — 그 목록이 있으면 Task 1의 `built_range(built, lines, lo, hi)`로 되돌리고, 없으면 지금 줄을 그대로 쓴다(그 규칙 이전 빌드). `built_range`가 `None`이면 상자를 내지 않는다.

되돌린 줄마다 `synctex_view(pdf, <빌드 사본 안의 tex 경로>, line)`를 부르고, 모은 박스를 `line_boxes` → `range_pad` → `merge_boxes`에 넘긴다. 쪽 크기는 이미 `pick`이 쥔 `(pw, ph)`다. 조각을 쪽 대비 비율로 바꿔 `Picked.boxes`에 담는다.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest src/limn/pins/location/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/limn/pins/location/
git commit -s -m "feat(api): add boxes to the pick answer's default level

I agree to the Limn CLA (CLA.md)."
```

---

### Task 4: `GET /api/snippet`의 단계마다 `boxes`

**Files:**
- Modify: `src/limn/pins/location/range.py`, `src/limn/pins/location/http.py`
- Test: 같은 폴더의 snippet 시험

**Interfaces:**
- Consumes: Task 3이 쓴 계산 묶음. 한 자리에 모아 `boxes_for_range(...) -> list[...]`로 빼고 pick과 snippet이 함께 쓴다.
- Produces: snippet 응답의 각 단계에 pick과 같은 모양의 `boxes`

- [ ] **Step 1: Write the failing test**

```python
def test_snippet_levels_carry_boxes(...):
    assert all("boxes" in lv for lv in body["levels"] if lv["level"] != "lines" or ...)

def test_snippet_boxes_match_pick_for_the_same_range(...):
    # 같은 파일·같은 lo..hi 면 pick과 snippet의 boxes 가 같다 (Review Focus 4)
    assert snippet_boxes == pick_boxes
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest src/limn/pins/location/tests -q -k snippet`
Expected: FAIL

- [ ] **Step 3: Extract the shared computation and call it from `range.py`**

Task 3에서 `resolve.py`에 쓴 계산을 `boxes_for_range(pdf, tex, built, now, lo, hi, pages, limit)`로 빼어 두 호출자가 쓴다. `pages` 는 쪽마다의 `(폭, 높이)` 다 — 조각은 자기가 놓인 쪽의 크기로 재고 그 쪽 안으로 자른다. 쪽 하나의 크기만 쓰면 가로 쪽이 섞인 문서에서 상자가 어긋나 잘리고, pick 과 snippet 이 같은 범위에 다른 값을 답한다(Review Focus 4). 쪽별 크기는 `pick_pages` 가 이미 한 번에 준다. snippet은 단계마다 부른다.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest src/limn/pins/location/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/limn/pins/location/
git commit -s -m "feat(api): answer snippet levels with their boxes

I agree to the Limn CLA (CLA.md)."
```

---

### Task 5: 핀 목록의 계산 필드 `boxes`와 캐시

**Files:**
- Modify: `src/limn/pins/needs.py`, `src/limn/pins/listing/projection.py`, `src/limn/builds/` (캐시와 콜러블), 조립 지점(`src/limn/pins/application.py` 또는 `runtime.py`, `src/limn/server.py`)
- Test: `src/limn/pins/listing/tests/`, `src/limn/builds/tests/`

**Interfaces:**
- Consumes: Task 4의 `boxes_for_range`
- Produces: `needs.py`에 `BoxesFor = Callable[[str, int, int], list[...]]` 선언. 빌드 소유자가 문서별로 바인딩해 조립 지점에서 주입한다. `pins_payload`는 그것을 받아 LaTeX 줄 핀에 `boxes`를 붙인다.

- [ ] **Step 1: Write the failing tests**

```python
def test_pins_payload_adds_boxes_for_line_pins(...):
    assert payload[0]["boxes"] == [{"page": 1, "frac": [...]}]

def test_pins_payload_leaves_figure_pins_alone(...):
    assert "boxes" not in figure_pin and figure_pin["mark"] == ...

def test_boxes_are_not_written_to_the_record(...):
    assert "boxes" not in json.loads(pins_jsonl_first_line)

def test_no_boxes_when_the_range_no_longer_stands(...):
    # 원고를 고치고 재빌드하지 않은 상태 (Review Focus 4, spec D7)
    assert "boxes" not in payload[0]

def test_the_cache_answers_the_second_call_without_running_synctex(...):
    # 같은 빌드·같은 범위를 두 번 물으면 synctex_view 호출 수가 늘지 않는다
    assert calls == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest src/limn/pins/listing/tests src/limn/builds/tests -q -k boxes`
Expected: FAIL

- [ ] **Step 3: Declare the need, add the cache, wire the assembly**

`needs.py`에 콜러블 모양을 선언한다(핀은 빌드를 import하지 않는다). 빌드 쪽에 `BuildMapCache`와 같은 자리·같은 수명의 캐시를 두고(빌드 id·파일·`lo`·`hi`가 열쇠, 실행마다 하나), 그 뒤에서 `boxes_for_range`를 부른다. 범위가 빌드가 읽은 줄에 그대로 서지 않으면(`built_range`가 `None`) 빈 목록을 돌려준다.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest src/limn/pins src/limn/builds -q`
Expected: PASS

- [ ] **Step 5: Run the boundary gate**

Run: `uv run python tools/check_boundaries.py`
Expected: 통과 — 핀이 빌드를 import하지 않는다

- [ ] **Step 6: Commit**

```bash
git add src/limn/pins/ src/limn/builds/ src/limn/server.py
git commit -s -m "feat(api): add computed boxes to the pin listing

I agree to the Limn CLA (CLA.md)."
```

---

### Task 6: 뷰어 — 마크를 조각 여럿으로

**Files:**
- Modify: `src/limn/viewer/js/pdf/view-figure.ts` (`pinPlace`), 마크를 그리는 모듈, `src/limn/viewer/js/pins/flow-list.ts`
- Test: `src/limn/viewer/tests/`

**Interfaces:**
- Consumes: Task 5의 `boxes`
- Produces: 핀 하나가 `.mark[data-pin=N]` 여러 개로 그려진다. 첫 조각에만 배지가 붙는다.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_pin_with_two_boxes_draws_two_marks(...):
    assert page.locator('.mark[data-pin="1"]').count() == 2

def test_only_the_first_box_carries_the_badge(...):
    assert page.locator('.mark[data-pin="1"] button.mark-jump').count() == 1

def test_a_pin_without_boxes_still_draws_its_frac(...):
    assert page.locator('.mark[data-pin="2"]').count() == 1

def test_boxes_on_another_page_draw_on_that_page(...):
    # Review Focus 1
    assert page.locator('#page-2 .mark[data-pin="1"]').count() == 1

def test_hiding_marks_hides_every_box(...):
    # H 키
    assert page.locator('.mark[data-pin="1"]:visible').count() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest src/limn/viewer/tests -q -k boxes`
Expected: FAIL

- [ ] **Step 3: Draw one mark per box**

`pinPlace`가 LaTeX 핀이면 `boxes`를 먼저 본다. 그리는 쪽은 조각마다 요소를 만들고 첫 조각에만 배지를 단다. 되돌리기 칩·[보기]의 스크롤과 반짝임·팝오버 앵커는 첫 조각을 쓴다.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest src/limn/viewer/tests -q`
Expected: PASS

- [ ] **Step 5: Rebuild the viewer bundle and run the JS gates**

Run: `npm run build:check && npm run typecheck && npm test`
Expected: PASS — 지어진 `dist/viewer.js`가 커밋된 바이트와 같다

- [ ] **Step 6: Commit**

```bash
git add src/limn/viewer/
git commit -s -m "feat(viewer): draw a pin mark per box

I agree to the Limn CLA (CLA.md)."
```

---

### Task 7: 뷰어 — 작성 중인 상자와 범위 전환

**Files:**
- Modify: `src/limn/viewer/js/pdf/input-selection.ts`, `src/limn/viewer/js/composer/view-levels.ts`, `view-excerpt.ts`
- Test: `src/limn/viewer/tests/`

**Interfaces:**
- Consumes: Task 3의 pick `boxes`, Task 4의 snippet `boxes`
- Produces: '새 핀' 상자가 조각으로 그려지고, 사다리·범위 발췌를 따라 바뀐다.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_new_pin_box_snaps_to_the_default_level(...):
    assert selection_box_height > dragged_height

def test_changing_the_ladder_rung_moves_the_box(...):
    assert box_after_env > box_after_para

def test_adjusting_lines_in_the_excerpt_moves_the_box(...):
    assert box_changed_after_widening

def test_the_box_falls_back_when_the_answer_has_no_boxes(...):
    assert selection_box == dragged_rect
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest src/limn/viewer/tests -q -k selection`
Expected: FAIL

- [ ] **Step 3: Point the selection box at the answer's boxes**

pick 응답으로 상자를 그리고, 사다리 전환과 범위 발췌의 조정은 이미 부르는 `snippet` 응답의 `boxes`로 다시 그린다.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest src/limn/viewer/tests -q`
Expected: PASS

- [ ] **Step 5: Rebuild and gate**

Run: `npm run build:check && npm run typecheck && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/limn/viewer/
git commit -s -m "feat(viewer): snap the composing selection to its range

I agree to the Limn CLA (CLA.md)."
```

---

### Task 8: float 핀의 조각 규칙을 실제 원고에서 정한다

**Files:**
- Modify: `src/limn/pins/location/mapping.py` (규칙과 한도), 그 시험

이 task는 spec의 열린 질문 2·4를 닫는다. 코드를 고치기 전에 **실제 원고에서 재고 소유자에게 보인다.**

- [ ] **Step 1: 실제 원고의 float 핀으로 조각을 잰다**

그림·표가 있는 원고를 띄우고 `figure`·`table` 환경 안의 핀 여러 개에 대해 Task 1~5의 계산이 내는 조각 수와 모양을 기록한다.

- [ ] **Step 2: 후보 규칙 2~3개의 PoC를 만든다**

[workflow.md](../../handbook/workflow.md) §화면 변경은 PoC를 먼저 보인다를 따른다. 후보마다 캡처·차이 목록·주소를 낸다. 추천안을 첫째에 둔다.

- [ ] **Step 3: 소유자가 고른다**

- [ ] **Step 4: 고른 규칙과 조각 한도를 구현하고 시험을 더한다**

한도를 넘으면 빈 목록(드래그 사각형으로 폴백)이라는 Task 1의 성질은 그대로다(Review Focus 5).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest src/limn/pins -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/limn/pins/location/
git commit -s -m "feat(pins): settle the box rule for float environments

I agree to the Limn CLA (CLA.md)."
```

---

### Task 9: Handbook 동기화와 네 기기군 PoC

**Files:**
- Modify: `docs/handbook/domain.md`, `docs/handbook/api.md`, `docs/handbook/viewer.md`, `CHANGELOG.md`
- Modify: `docs/adr/0049-pin-marks-follow-the-range.md` (상태 `제안` → `승인됨`), `docs/adr/index.md`

- [ ] **Step 1: 네 기기군 PoC를 만들어 소유자에게 보인다**

데스크톱 1440×900(마우스), 휴대폰 390×844·320×720(터치), 태블릿 768×1024·1024×768(터치), 폴더블 344×882·673×841·841×673(터치). 전후를 같은 배율로 나란히, 달라진 곳에 확대 컷. PoC 이미지는 저장소에 넣지 않는다.

- [ ] **Step 2: 소유자 확인을 받는다**

- [ ] **Step 3: Handbook을 현재 상태에 맞춘다**

[domain.md](../../handbook/domain.md)에 상자가 범위를 그린다는 규칙과 여백·낡은 빌드·폴백의 이유를 현재형으로 쓰고 ADR-0049를 짧게 인용한다. [api.md](../../handbook/api.md)에 `boxes`의 모양과 세 경로를 적는다. [viewer.md](../../handbook/viewer.md)에 조각 여럿과 첫 조각 기준을 적는다. 날짜·전후 수치·진행 기록은 넣지 않는다(PR과 CHANGELOG가 맡는다).

- [ ] **Step 4: Run the full gate**

Run: CLAUDE.md §검증의 전체 목록
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add docs/ CHANGELOG.md
git commit -s -m "docs: record that pin marks follow the range

I agree to the Limn CLA (CLA.md)."
```
