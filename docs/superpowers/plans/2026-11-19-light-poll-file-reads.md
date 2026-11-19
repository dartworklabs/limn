# 가벼운 폴링의 파일 읽기 줄이기 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 가벼운 폴링 한 번이 하는 파일 시스템 호출을 줄인다. 요청 하나가 문서의 같은 사실을 한 번만 읽고, 발행된 쪽 폴더의 쪽 이름·픽셀 크기는 실행 동안 한 번만 읽는다.

**Architecture:** 빌드가 쪽 기억(`PageFolderCache`, `builds/artifacts.py`)을 소유하고 `BuildQueries`가 지도 캐시처럼 받는다. 문서 조회가 받는 빌드 사실에 요약만의 조회 `brief`를 더하고, `reads.meta`는 고른 문서의 `summary`를 한 번만 받는다. 기억은 `RuntimeResources`의 실행별 자리 `page_folders`가 소유하고 `server.py`가 연결한다. `Doc.rel_path`는 기동 때 푼 경로로 답한다.

**Tech Stack:** Python 3.10+ 표준 라이브러리만. 시험은 pytest·unittest·Hypothesis(기존 개발 의존성).

**Spec:** [docs/superpowers/specs/2026-11-19-light-poll-file-reads-design.md](../specs/2026-11-19-light-poll-file-reads-design.md) (승인됨 2026-11-19: B안, 열쇠 B1, 표시 경로는 기동 경로). ADR은 구현·검증 뒤 소유자와 정한다(Task 6).

## Global Constraints

- 서버 런타임은 표준 라이브러리만 쓴다(`pyproject.toml`의 `dependencies = []`).
- 에이전트 계약(`pins.md` 형식, HTTP API의 경로·필드·상태 이름)과 저장 형식을 바꾸지 않는다. `/api/meta`·`/api/docs`의 응답 바이트가 `main`과 같다. 예외는 spec §경우별 응답의 굵은 두 행뿐이다.
- 기억하는 것은 시각 이름(`pages-<14자리>[-<n>]`) 쪽 폴더의 `page-*.png` 이름 수와 (이름, 가로 픽셀, 세로 픽셀)뿐이다. `pages.cur`, `built_at.txt`, `head.txt`, `built_src_mtime.txt`, `builds.json`, 빌드 상태, 원고 수정 시각은 기억하지 않는다. 옛 배치 이름 `pages`는 담지 않는다.
- 열쇠는 `(str(Doc.dir), 빌드 이름)`이다. stat·dpi·시계를 열쇠나 조건에 넣지 않는다. 포인트 크기는 요청마다 `픽셀 * 72.0 / dpi`로 계산한다.
- 담는 조건 셋: 시각 이름이다, 이름이 하나 이상이고 모든 그림의 크기를 읽었다, 읽은 뒤에도 `pages.cur`가 그 이름을 가리킨다.
- 한도: 기억의 행(쪽) 수 합 `PAGE_ROWS_MAX = 4096`. 넘으면 먼저 담은 폴더부터 버리고, 쪽이 그보다 많은 폴더는 담지 않는다.
- `artifacts.page_list`·`page_sizes`·`cur_pages`·`source_newer`·`build_ref_mtime`·`state_snapshot`·`src_mtime`의 서명과 동작, 그 호출자(pick, 핀의 쪽 검사, 줄 핀 상자, 겹쳐 보기, `GET /api/build`, 빌드 엔진, 기동)는 바꾸지 않는다.
- `src_mtime`은 요약에서 지금처럼 `build` 인자 없이 부른다(2초 기억의 열쇠가 문서마다 하나).
- 어떤 GET도 영속 상태를 바꾸지 않는다. 기억은 메모리에만 있고 실행 둘이 공유하지 않는다.
- 기능은 다른 기능을 import하지 않고, `runtime/`은 기능을 import하지 않는다. `tools/check_boundaries.py`의 `ENTRYPOINT_IMPORTS`와 `__all__`은 실제 import와 같아야 한다.
- 저장 역할 모듈(`queries.py`)과 셸에 `isinstance`를 더하지 않는다(`tools/check_fitness.py` 기준선은 오르지 않는다). `typing.cast`·`# type: ignore`·`# pyright:`를 쓰지 않는다. `.basedpyright/baseline.json`은 문장이 옮겨 간 경우의 열 번호만 바뀔 수 있다.
- 시험은 벽시계로 성능을 단언하지 않는다. 파일 시스템 호출 수를 센다.
- 코드·주석·docstring·시험 이름·커밋 메시지는 영어, Handbook은 한국어. 만들거나 본문을 고친 모든 정의에 docstring을 단다. 호스트 이름·홈 경로를 저장소에 넣지 않는다.
- 커밋은 모두 `git commit -s`, 메시지 끝에 `I agree to the Limn CLA (CLA.md).` 스테이징은 파일 이름으로 한다.

## Review Focus

spec이 전제하지만 시험이 따로 짚지 않으면 지나치기 쉬운 입력들. 줄마다 맡는 task에 시험을 뒀다.

1. **쪽 교체와 겹친 첫 읽기.** 폴더를 읽는 동안 `pages.cur`가 다른 빌드로 옮겨 가면(옛 폴더가 지워지는 중일 수 있다) 그 읽기는 답하되 담지 않는다. (Task 1)
2. **같은 초에 발행된 두 문서의 같은 빌드 이름.** 문서 둘이 `pages-20260101000000`을 각자 갖고 쪽이 다르다. 서로의 쪽을 답하면 안 된다. (Task 1)
3. **그림 문서의 쪽 목록 덧쓰기.** `page_facts`는 받은 쪽 목록의 dict에 `figure`·`title`을 써넣는다. 기억이 내준 목록이 호출마다 새 dict가 아니면 다음 요청과 다른 dpi의 답이 오염된다. (Task 2)
4. **쪽 교체 직후, 이력이 쓰이기 전.** `commit_pages`가 포인터를 바꾼 뒤 `record_build`가 `builds.json`을 쓰기까지 요약만의 조회의 `stale_build`가 `summary`의 것과 같아야 한다(`built_src_mtime.txt`로 떨어진다). (Task 2)
5. **읽지 못하는 그림이 든 발행 폴더.** 한 번의 I/O 오류일 수 있으므로 담지 않고, 다음 요청이 다시 읽어 고쳐진 폴더를 답한다. (Task 1)

---

### Task 1: 쪽 기억 (`builds/artifacts.py`)

**Files:**
- Modify: `src/limn/builds/artifacts.py` (`RangeBoxCache` 아래, `png_size`·`page_list` 옆)
- Test: `src/limn/builds/tests/test_page_folders.py` (새 파일)

**Interfaces:**
- Consumes: `artifacts.png_size`, `artifacts.cur_pages`, `artifacts.valid_build_name`, `BuildDoc`.
- Produces:
  - `PAGE_ROWS_MAX: int = 4096`
  - `@dataclass(frozen=True) class FolderPages` — `count: int`(폴더의 `page-*.png` 이름 수), `sized: tuple[tuple[str, int, int], ...]`(크기를 읽은 쪽의 이름·가로·세로 픽셀, 이름 순서). 메서드 `rows(self, dpi: int) -> list[dict[str, Any]]`는 호출마다 새 `{name, pt_w, pt_h}` dict의 새 목록을 준다(`w * 72.0 / dpi`).
  - `read_folder_pages(pdir: Path) -> FolderPages` — 폴더를 한 번 훑고 그림마다 `png_size`. 없는 폴더는 `FolderPages(0, ())`. 읽지 못한 그림(`OSError`, `struct.error`)은 `sized`에서 빠지고 `count`에는 든다.
  - `count_folder_pages(pdir: Path) -> int` — 이름만 센다(그림을 열지 않는다).
  - `@dataclass class PageFolderCache` — 필드 `max_rows: int = PAGE_ROWS_MAX`, `read: Callable[[Path], FolderPages] = read_folder_pages`. 메서드:
    - `pages(self, doc: BuildDoc, pdir: Path) -> FolderPages` — `pdir`은 `doc`의 화면 빌드 폴더(`cur_pages(doc)`가 준 것). 시각 이름이고 기억에 있으면 그 값. 없으면 `self.read(pdir)`로 읽고, 담는 조건 셋이 맞으면 담는다.
    - `count(self, doc: BuildDoc, pdir: Path) -> int` — 시각 이름이면 `pages(doc, pdir).count`, 아니면 `count_folder_pages(pdir)`.
    - `held(self) -> int` — 담긴 행 수의 합.
  - `page_list(pdir, dpi)`는 `read_folder_pages(pdir).rows(dpi)`와 같은 답을 준다(서명·동작 불변, 본문만 공유해도 된다).

시각 이름의 판정은 `valid_build_name(name) and name != "pages"`. 열쇠는 `(str(doc.dir), pdir.name)`. 잠금은 사전을 읽고 쓰는 순간만 쥐고 `read`와 `cur_pages` 호출 동안에는 쥐지 않는다.

- [ ] **Step 1: 시험 도우미와 실패하는 시험을 쓴다**

`src/limn/builds/tests/test_page_folders.py`에 둔다. 도우미:

```python
def fs_calls(call):
    """(Counter of file-system builtins called while call() runs, call's result): open, stat, lstat, scandir,
    listdir, readlink, entry_stat. Counted with sys.setprofile on this thread - a count of work a busy machine does
    not change (docs/handbook/verification.md §불안정한 테스트)."""
```

`c_call` 사건의 `arg`가 `io.open`·`os.open`(→ `"open"`), `os.stat`, `os.lstat`, `os.scandir`, `os.listdir`, `os.readlink`이면 그 이름으로, `getattr(arg, "__qualname__", "") == "DirEntry.stat"`이면 `"entry_stat"`으로 센다. Task 2·3의 시험도 이 도우미를 `from limn.builds.tests...`가 아니라 **자기 파일에 같은 정의로** 두지 않도록, `tests/support/helpers.py`에 두고 세 시험 파일이 `from helpers import fs_calls`로 쓴다.

픽스처: 임시 폴더에 `RunPaths`와 `Doc("ms", "본문", "tex", ...)`, `Doc("rr", ...)`. `publish(doc, name, sizes)`는 `.name.part`에 `helpers_figure.png_header(w, h)`로 쪽을 쓰고 rename한 뒤 `pages.cur`를 쓴다.

시험(이름과 단언):

```python
def test_a_stamped_folder_is_read_once(self):
    publish(self.ms, B1, [(300, 150)] * 3)
    cache = PageFolderCache()
    first = cache.pages(self.ms, self.ms.dir / B1)
    calls, again = fs_calls(lambda: cache.pages(self.ms, self.ms.dir / B1))
    self.assertEqual(again, first)
    self.assertEqual((first.count, len(first.sized)), (3, 3))
    self.assertEqual(calls["open"] + calls["scandir"] + calls["listdir"], 0)

def test_the_second_read_costs_the_same_for_three_pages_as_for_thirty(self): ...   # both 0 opens
def test_rows_are_sized_at_the_dpi_asked_and_fresh_each_call(self):
    # rows(150) == [{"name": "page-1.png", "pt_w": 144.0, "pt_h": 72.0}], rows(300) halves them;
    # mutating a returned row or list leaves the next rows(150) unchanged
def test_rows_equal_page_list(self): ...            # for a folder with one truncated image too
def test_the_legacy_folder_is_never_kept(self):      # doc.dir/"pages": add a page after a read -> seen; held() == 0
def test_an_empty_folder_is_not_kept(self): ...      # then a page written -> count 1
def test_a_folder_with_an_unreadable_image_is_not_kept(self):
    # one image cut to 10 bytes: count 3, len(sized) 2, held() == 0; after the image is whole again -> len(sized) 3
def test_a_read_the_pointer_moved_away_from_is_answered_and_not_kept(self):
    # PageFolderCache(read=reads_then_swaps): read() publishes B2 and moves pages.cur before returning B1's pages
    # -> the answer is B1's, held() == 0
def test_two_documents_with_one_build_name_keep_their_own_pages(self): ...
def test_two_builds_of_one_document_keep_their_own_pages(self): ...
def test_the_rows_kept_stay_within_the_limit_oldest_first(self):
    # PageFolderCache(max_rows=5): B1 (3 pages) then B2 (3 pages) -> held() == 3 and B1 is read again
def test_a_folder_larger_than_the_limit_is_not_kept(self): ...
def test_count_of_the_legacy_folder_opens_no_image(self):       # calls["open"] == 0, result == number of names
def test_count_of_a_stamped_folder_fills_what_is_kept(self):    # then pages() makes no file-system call
def test_two_caches_share_nothing(self): ...
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest -q -n 0 src/limn/builds/tests/test_page_folders.py`
Expected: FAIL (`ImportError: cannot import name 'PageFolderCache'`)

- [ ] **Step 3: `FolderPages`, `read_folder_pages`, `count_folder_pages`, `PageFolderCache`를 구현하고 `fs_calls`를 `tests/support/helpers.py`에 둔다**

`PageFolderCache`의 docstring은 `RangeBoxCache`처럼 전제(시각 이름의 폴더는 한 번 쓰여 발행되고 이름은 다시 쓰이지 않는다), 열쇠, 담는 조건 셋과 그 까닭, 한도와 행 하나의 메모리, 동시성, 발행된 폴더를 손으로 고친 경우 그 실행은 처음 읽은 값을 계속 답한다는 것을 적는다.

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest -q -n 0 src/limn/builds/tests/test_page_folders.py src/limn/builds/tests/test_page_urls.py src/limn/builds/tests/test_hold.py`
Expected: PASS

- [ ] **Step 5: 변이로 실패를 본다**

하나씩 넣고 시험이 단언에서 실패하는지 본 뒤 되돌린다: 열쇠에서 빌드 이름을 뺀다, 열쇠에서 `str(doc.dir)`를 뺀다, `pages`를 담는다, 불완전한 읽기를 담는다, 포인터 재확인을 뺀다, 한도 검사를 뺀다, `rows`가 기억한 dict를 그대로 준다, 포인트 크기를 기억한다. 살아남는 변이가 있으면 시험을 더한다.

- [ ] **Step 6: 커밋**

```bash
git add src/limn/builds/artifacts.py src/limn/builds/tests/test_page_folders.py tests/support/helpers.py
git commit -s -m "perf(builds): keep a published page folder's page names and sizes for the run" -m "I agree to the Limn CLA (CLA.md)."
```

---

### Task 2: 요약만의 조회와 한 번 읽는 요약 (`builds/queries.py`, `documents/`)

**Files:**
- Modify: `src/limn/builds/artifacts.py` (화면 빌드의 낡음 판정, 빌드 상태 복사)
- Modify: `src/limn/builds/queries.py` (`BuildQueries`)
- Modify: `src/limn/builds/contracts.py` (`DocumentBuildQueries`)
- Modify: `src/limn/documents/needs.py` (`BuildFacts`), `src/limn/documents/reads.py` (`doc_brief`, `meta`)
- Test: `src/limn/documents/tests/test_light_poll_reads.py` (새 파일), 기존 `src/limn/documents/tests/test_meta.py`·`src/limn/builds/tests/test_queries.py`는 고치지 않고 통과해야 한다(대역이 `BuildFacts`를 손으로 만든 곳만 `brief`를 더한다)

**Interfaces:**
- Consumes: Task 1의 `PageFolderCache.pages`·`count`, `FolderPages.rows`.
- Produces:
  - `artifacts.shown_source_newer(D: BuildDoc, state_dir: Path, pages: Path) -> float` — `source_newer(D, state_dir)`와 같은 값을, 호출자가 이미 읽은 화면 빌드 폴더 `pages`로 구한다. 기준 mtime은 이력의 `pages.name` 항목 → `read_built_src_mtime(D)` → `cur_pdf(D, pages)`의 mtime 순서(없으면 0.0). 원고 쪽은 `src_mtime(D, state_dir)`(`build` 인자 없음). `pages.cur`를 읽지 않는다.
  - `artifacts.build_state(D: BuildStateHolder) -> dict[str, Any]` — 잠금 아래 `dict(D.bstate)`. 파일을 읽지 않는다.
  - `BuildQueries.pages: Callable[[], artifacts.PageFolderCache]` (기본값은 `own_marks`처럼 그 바인딩만의 캐시를 만드는 `own_pages`).
  - `BuildQueries.brief(self, doc: Doc, state: Path) -> dict[str, Any]` — 지금 `summary(...).brief`와 같은 dict(키 순서 포함).
  - `BuildQueries.summary(self, doc, state, dpi) -> DocumentBuild` — 서명 불변. `brief`와 `meta`를 한 번의 읽기에서 만든다.
  - `DocumentBuildQueries(summary, outline, brief)` — `brief: Callable[[Doc, Path], dict[str, Any]]`. `BuildQueries.documents()`가 채운다.
  - `documents.needs.BuildFacts.brief` — `Callable[[Doc, Path], dict[str, Any]]` 속성(읽기 전용 Protocol 멤버, docstring: 요약의 키에 드는 사실만 읽는다).
  - `reads.doc_brief(D, state_dir, builds)`는 `builds.brief(D, state_dir)`를 돌려준다. `reads.meta`는 `builds.summary(D, ...)`를 한 번 받고, `multi`일 때 `docs`의 `D` 자리에 그 답의 `brief`를, 나머지에 `doc_brief`를 넣는다(`d is D`).

`summary`와 `brief`가 함께 쓰는 한 번의 읽기(이름은 구현자가 정하는 비공개 메서드): `build_state(doc)`, `cur_pages(doc)` 한 번, `src_mtime(doc, state)`, `shown_source_newer(doc, state, pages)`, `doc.rel_path()`, `doc.lock.locked()`. 쪽 수는 `brief`에서 `self.pages().count(doc, pages)`, `summary`에서 `self.pages().pages(doc, pages)` 한 번으로 `count`와 `rows(dpi)`를 얻는다. `summary`의 `built_at`·`head`는 `artifacts.read_built_at`·`read_head`를 직접 부른다(`self.heading`은 포인터를 한 번 더 읽는다). `n_pages`의 지금 식은 `sum(1 for _ in pages.glob("page-*.png")) if pages.is_dir() else 0`이고 `count`가 같은 값이어야 한다.

- [ ] **Step 1: 실패하는 시험을 쓴다**

`src/limn/documents/tests/test_light_poll_reads.py`. 픽스처는 `test_meta.py`의 `Fixture`와 같은 모양(본문 `ms`, 둘째 LaTeX `rr`, 보기 전용 PDF `rv`, `MetaSettings`)에 `publish(doc, name, n)`(쪽 n장, PDF 사본 포함)과 `queries()`(`BuildQueries(lambda: BuildMapCache(), pages=lambda: cache)`의 `documents()`)를 더한다. 어떤 파일을 열었는지는 `sys.addaudithook`의 `open` 사건으로 모은다: 모듈에 hook을 한 번만 달고 `opened(call) -> (list[str], result)`가 켜고 끄는 목록에 경로를 쌓는다(이 도우미도 `tests/support/helpers.py`에 둔다).

```python
def test_brief_equals_the_summarys_brief(self):
    # for ms (pages, history entry present), rr (pages, no history entry, built_src_mtime.txt old -> stale True),
    # rv (view-only, pages), a document with no pages at all, the legacy layout, a folder on screen that is gone
    self.assertEqual(q.brief(doc, self.state), q.summary(doc, self.state, 150).brief)
    self.assertEqual(list(q.brief(doc, self.state)), BRIEF_KEYS)   # the contract order, written out in the test

def test_brief_stale_matches_between_the_swap_and_the_history(self):
    # pages.cur names B2, builds.json has no B2, built_src_mtime.txt = 1.0, main.tex touched now
    self.assertIs(q.brief(self.ms, self.state)["stale_build"], True)
    self.assertEqual(q.brief(self.ms, self.state), q.summary(self.ms, self.state, 150).brief)

def test_brief_reads_no_stamp_and_with_a_history_entry_no_baseline_file(self):
    names = [Path(p).name for p in opened(lambda: q.brief(self.ms, self.state))[0]]
    self.assertNotIn("built_at.txt", names); self.assertNotIn("head.txt", names)
    self.assertNotIn("built_src_mtime.txt", names)      # the history names the build on screen

def test_a_summary_reads_each_fact_once(self):
    q.summary(self.ms, self.state, 150)                  # fills the page memory and the src_mtime memo
    names = Counter(Path(p).name for p in opened(lambda: q.summary(self.ms, self.state, 150))[0])
    self.assertEqual((names["pages.cur"], names["built_at.txt"], names["head.txt"]), (1, 1, 1))
    self.assertEqual(sum(n for name, n in names.items() if name.endswith(".png")), 0)

def test_meta_reads_each_documents_pointer_once(self):
    # reads.meta(self.ms, {}, self.settings, [self.ms, self.rr, self.rv], {}, time.time(), q) twice;
    # in the second: every document's pages.cur opened exactly once, no .png opened, scandir + entry_stat == 0
def test_the_second_meta_costs_the_same_for_three_pages_as_for_thirty(self): ...   # fs_calls totals equal
def test_metas_docs_carry_the_selected_documents_brief_from_the_same_read(self):
    # out["docs"][0] == the brief of the summary; with pages.cur swapped by a `summary` wrapper between the
    # selected document's summary and the rest, out["pages_build"] == out["docs"][0]["pages_build"]
def test_a_document_that_sets_files_apart_scans_its_tree_once_per_poll(self):
    # ms built with apart=apart_paths(...) for a figure folder inside its root: after one meta, a second meta
    # within the 2 s memo makes no scandir (one memo key per document)
def test_a_figure_documents_page_facts_do_not_reach_what_is_kept(self):
    # helpers_figure.write_build(fig, B1, b2_map()): summary twice at 150 and once at 300 ->
    # the 150 answers are equal, and the rows of cache.pages(fig, fig.dir / B1).rows(150) carry only name, pt_w, pt_h
def test_a_new_build_is_answered_at_the_next_read(self): ...      # publish B2 (2 pages) after B1 (3): n_pages 2
def test_a_folder_on_screen_that_is_gone_answers_the_legacy_name(self):
    # rmtree(ms.dir / B1) after a warm read: pages_build == "pages", n_pages == 0, pages == []
```

성질 시험(Hypothesis, 같은 파일): 사건 열(새 빌드 발행과 포인터 교체 / 화면이 아닌 폴더 삭제 / 화면이 아닌 폴더를 `artifacts.slim_pages`로 가볍게 / 화면 폴더 삭제 / 옛 배치 `pages`에 쪽 더하기와 포인터를 `pages`로 / 읽지 못하는 그림이 든 빌드 발행)마다, 한 캐시를 계속 쓰는 조회의 `summary(doc, state, 150)`와 `brief`가 새 캐시로 만든 조회의 것과 같다. 발행한 폴더는 다시 쓰지 않고, 가볍게 남긴 폴더로 포인터를 옮기지 않는다(제품이 하지 않는 일).

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest -q -n 0 src/limn/documents/tests/test_light_poll_reads.py`
Expected: FAIL (`AttributeError: ... has no attribute 'brief'`)

- [ ] **Step 3: `shown_source_newer`·`build_state`, `BuildQueries.pages`·`brief`·`summary`, `DocumentBuildQueries.brief`, `BuildFacts.brief`, `reads.doc_brief`·`meta`를 구현한다**

`documents/reads.py`의 모듈 docstring과 `meta`·`doc_brief`의 docstring, `needs.py`의 `BuildFacts`·`BuildSummary` docstring을 새 동작에 맞춘다. `BuildFacts`를 손으로 만든 시험 대역이 있으면(`grep -rn "BuildFacts\|DocumentBuildQueries(" src tests`) `brief`를 더한다.

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest -q -m "not browser" src/limn/documents src/limn/builds tests/contracts`
Expected: PASS

Run: `uv run python tools/check_boundaries.py && uv run python tools/check_fitness.py && uv run python tools/check_types.py`
Expected: 셋 다 통과(기준선 불변)

- [ ] **Step 5: 변이로 실패를 본다**

요약만의 조회가 `built_at.txt`·`head.txt`를 읽는다, 요약만의 조회가 이력에 없는 빌드의 기준 mtime을 찾지 않는다(0.0), 요약만의 조회가 쪽 기억을 채우지 않는다(`count_folder_pages`만), `meta`가 고른 문서의 요약을 다시 읽는다, `src_mtime`에 빌드 이름을 넘긴다, `summary`가 `self.heading`을 부른다(포인터 두 번), `summary`가 `state_snapshot`을 쓴다(`built_at.txt` 두 번), `rows`를 캐시의 dict 그대로 넘긴다.

- [ ] **Step 6: 커밋**

```bash
git add src/limn/builds/artifacts.py src/limn/builds/queries.py src/limn/builds/contracts.py src/limn/documents/needs.py src/limn/documents/reads.py src/limn/documents/tests/test_light_poll_reads.py tests/support/helpers.py
git commit -s -m "perf(documents): a poll reads each document's build facts once, and a brief reads only what a brief holds" -m "I agree to the Limn CLA (CLA.md)."
```

---

### Task 3: 표시 경로는 기동 때 푼 경로 (`runtime/documents.py`)

**Files:**
- Modify: `src/limn/runtime/documents.py` (`Doc.rel_path`)
- Test: `src/limn/documents/tests/test_light_poll_reads.py`(같은 픽스처), 필요하면 `src/limn/pins/tests/`의 pick 시험 하나

**Interfaces:**
- Produces: `Doc.rel_path() -> str` — `str(self.registered_main.relative_to(self.registered_manuscript))`, 주 파일이 원고 폴더 밖이면(`ValueError`) `str(self.main)`. 파일 시스템을 묻지 않는다. docstring에 호출자 넷(요약의 `path`, `pins.md` 머리말, 기동 줄, 보기 전용 PDF와 지도 PDF가 주 파일인 그림 문서의 pick 응답 `pdf`)과 "기동 뒤 링크를 바꿔도 재시작까지 기동 때의 경로"를 적는다.

- [ ] **Step 1: 실패하는 시험을 쓴다**

```python
def test_the_display_path_asks_the_file_system_nothing(self):
    calls, path = fs_calls(self.rr.rel_path)
    self.assertEqual(path, "rr/rr.tex"); self.assertEqual(sum(calls.values()), 0)

def test_the_display_path_is_the_one_resolved_at_startup(self):
    # after the documents are made: move ms/rr to ms/elsewhere and leave ms/rr a symlink to it
    self.assertEqual(self.rr.rel_path(), "rr/rr.tex")
    self.assertEqual(q.brief(self.rr, self.state)["path"], "rr/rr.tex")

def test_a_main_file_outside_the_manuscript_is_answered_as_given(self): ...   # str(doc.main)
def test_a_document_registered_through_a_link_answers_the_resolved_path(self):
    # the manuscript folder reached through a symlink at construction: the same string the old code gave
def test_a_warm_meta_makes_no_lstat(self):   # fs_calls of the second reads.meta: calls["lstat"] == 0
```

기존 시험이 전제하던 값이 바뀌는지 본다: `uv run pytest -q -m "not browser" -k "rel_path or path or pins_md or region"`.

- [ ] **Step 2: 실패를 확인한다** — Run: `uv run pytest -q -n 0 src/limn/documents/tests/test_light_poll_reads.py -k "display_path or lstat"` / Expected: FAIL(`lstat` 수가 0이 아님, 링크를 바꾼 뒤 경로가 달라짐)

- [ ] **Step 3: `Doc.rel_path`를 구현한다**

- [ ] **Step 4: 통과를 확인한다** — Run: `uv run pytest -q -m "not browser"` / Expected: PASS. 실패가 표시 경로의 수명을 전제한 시험이면 그 시험이 무엇을 고정하려던 것인지 보고, 계약(같은 경로 문자열)이 유지되는 한에서 고친다. 그렇지 않으면 멈추고 보고한다.

- [ ] **Step 5: 변이** — `rel_path`가 요청마다 `resolve()`한다 → `lstat` 시험과 링크 시험이 실패해야 한다.

- [ ] **Step 6: 커밋**

```bash
git add src/limn/runtime/documents.py src/limn/documents/tests/test_light_poll_reads.py
git commit -s -m "perf(runtime): a document's display path is the one resolved at startup" -m "I agree to the Limn CLA (CLA.md)."
```

---

### Task 4: 실행별 자원과 조립 (`runtime/resources.py`, `server.py`, `builds/application.py`)

**Files:**
- Modify: `src/limn/runtime/resources.py` (TypeVar `Pages`, 필드 `page_folders: Pages`를 `pin_lines` 다음에, 클래스 docstring)
- Modify: `src/limn/server.py` (`RunResources`, `new_runtime`, `assemble_builds(..., pages=lambda: resources().page_folders)`)
- Modify: `src/limn/builds/application.py` (`assemble_builds`의 키워드 인자 `pages: PageFolderCache | Callable[[], PageFolderCache] | None = None`, `maps`와 같은 방식)
- Modify: `src/limn/builds/__init__.py` (`PageFolderCache`를 `__all__`·`_EXPORTS`에), `tools/check_boundaries.py` (`ENTRYPOINT_IMPORTS["limn.server"]`에 `PageFolderCache`)
- Modify: `RuntimeResources[...]`를 적은 곳 넷(`pins/runtime.py` 두 곳, `pins/application.py`, `security/application.py`)에 `object` 하나를 더한다
- Test: `src/limn/documents/tests/test_light_poll_reads.py` (`Base`를 쓰는 클래스 하나)

**Interfaces:**
- Consumes: Task 1의 `PageFolderCache`, Task 2의 `BuildQueries.pages`.
- Produces: `RuntimeResources.page_folders`, `limn.builds.PageFolderCache`(표면).

- [ ] **Step 1: 실패하는 시험을 쓴다**

```python
class ThroughTheRun(Base):
    def test_each_run_has_its_own_page_memory(self):
        viewer = ps.APP.RT.viewer
        one, two = ps.new_runtime(viewer).page_folders, ps.new_runtime(viewer).page_folders
        self.assertIsNot(one, two); self.assertEqual(one.held(), 0)

    def test_the_second_light_poll_opens_no_page_image(self):
        # a build with three pages on screen for the default document; req("GET", "/api/meta?light=1") twice
        names = [Path(p).name for p in opened(lambda: req("GET", "/api/meta?light=1"))[0]]
        self.assertEqual([n for n in names if n.endswith(".png")], [])
        self.assertEqual(ps.APP.RT.page_folders.held(), 3)

    def test_a_restarted_run_reads_the_folder_again(self):
        # helpers.fresh_runtime(): held() == 0, and the next poll opens the three images once
```

- [ ] **Step 2: 실패를 확인한다** — Expected: FAIL(`AttributeError: ... 'page_folders'`)

- [ ] **Step 3: 구현한다**

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest -q -m "not browser"` / Expected: PASS
Run: `uv run python tools/check_boundaries.py && uv run python tools/check_fitness.py && uv run python tools/check_types.py && uv run ruff check && uv run ruff format --check`
Expected: 모두 통과

- [ ] **Step 5: 변이** — 실행 둘이 캐시 하나를 공유한다(모듈 전역) → 첫째·셋째 시험 실패. 조립이 실행의 캐시를 넘기지 않는다 → `held() == 3` 실패.

- [ ] **Step 6: 커밋**

```bash
git add src/limn/runtime/resources.py src/limn/server.py src/limn/builds/application.py src/limn/builds/__init__.py tools/check_boundaries.py src/limn/pins/runtime.py src/limn/pins/application.py src/limn/security/application.py src/limn/documents/tests/test_light_poll_reads.py
git commit -s -m "perf(server): the run owns the page folder memory its build queries read" -m "I agree to the Limn CLA (CLA.md)."
```

---

### Task 5: Handbook 동기화와 증명

**Files:**
- Modify: `docs/handbook/build-sync.md` (§자동 동기화 (가벼운 meta 폴링), §쪽 교체), `docs/handbook/architecture.md` (§현재 구조 표의 빌드·실행 자원 행, §의존 방향 표의 "문서 조회 ← 빌드" 행, 표시 경로), `docs/handbook/api.md` (§GET의 영속 무효과의 메모리 캐시 목록, `path`·pick `pdf`·`pins.md` 머리말의 표시 경로 설명), `docs/handbook/verification.md` (§불안정한 테스트: 파일 시스템 호출 수를 세는 검사)
- 저장소 밖: `~/scratch/limn-light-poll-2026-11-19/`의 `differential.sh`, `paired.sh`, `count.sh`, `count_spaced.sh`

- [ ] **Step 1: Handbook topic을 현재형으로 고친다.** 날짜·전후 수치는 넣지 않는다. 규칙은 실패 조건과 이유로 적는다(쪽 기억의 전제, 담는 조건, 손으로 고친 폴더, 표식은 왜 기억하지 않는가, 표시 경로의 수명).

Run: `uv run pytest -q -n 0 tests/architecture/test_handbook_refs.py tests/architecture/test_naming.py`
Expected: PASS

- [ ] **Step 2: 차등 비교.** `main`(`fe822d53`)의 `src`만 꺼낸 워크트리(`git worktree add --no-checkout --detach`, sparse `src`)와 이 가지를 `differential.sh final <main 트리> plain <이 트리> plain`으로 대조한다. `differential.py`에 단계를 더한다: 실제 `POST /api/rebuild` 한 번(빌드 이름과 `built_at`·`head`·`last_build`의 시각을 가리고), 원고 파일을 고친 뒤(`stale_build` true), 붙잡은 빌드(`POST /api/hold`). Expected: 화면 폴더를 손으로 지운 단계를 뺀 모든 답이 바이트로 같다. 건수를 적는다.

- [ ] **Step 3: 호출 수.** `count.sh after <이 트리>`와 `count.sh main <main 트리>`, `count_spaced.sh`를 `paper-big`으로 둘 다. Expected: 원고 수정 시각의 기억에 맞은 폴링이 약 22번(시제품 `lean0`), 쪽 그림 열기 0.

- [ ] **Step 4: 지연.** `paired.sh final 5 main:plain:<main 트리> new:plain:<이 트리>`와 `PAPER=paper-big POLL_GAP=2.2 HEAVY_KS=2 BUSY_KS=1 paired.sh final-big 3 ...`. `uptime`과 슬롯 대기·슬롯 안 시간을 함께 적는다. 기대값은 spec의 "이 설계 + `path` 기동 경로" 열이고, 크게 어긋나면 원인을 찾는다.

- [ ] **Step 5: 전체 게이트.** `CLAUDE.md` §검증의 명령 전부(브라우저 시험 포함). 결과를 수치로 적는다.

- [ ] **Step 6: 커밋**

```bash
git add docs/handbook/build-sync.md docs/handbook/architecture.md docs/handbook/api.md docs/handbook/verification.md
git commit -s -m "docs(handbook): what a poll reads each time and what the run keeps of a published page folder" -m "I agree to the Limn CLA (CLA.md)."
```

---

### Task 6: 독립 리뷰, PR, ADR 결정

- [ ] **Step 1: 새 맥락의 독립 리뷰.** 리뷰어에게 spec·plan 경로와 `git diff fe822d53...HEAD`를 주고, 결론이 아니라 코드를 준다. 물을 것: spec의 요구사항·불변식 위반, 기억한 값이 고쳐지거나 낡은 답이 나가는 경로, 계약 바이트가 바뀌는 경우, 시험이 구조가 아닌 동작을 고정하는지. 찾은 것은 확인한 뒤 고치고 시험을 더한다.
- [ ] **Step 2: PR.** 본문에 호출 수 전후, 지연 전후(부하와 함께), K=4·8의 슬롯 대기 몫, 차등 비교 건수, 변이 목록과 결과, 게이트 수치, 남은 한계(원고 폴더 훑기, Linux 미측정)를 적는다. 브랜치를 푸시하고 `gh pr create`.
- [ ] **Step 3: 소유자에게 묻는다(선택 창).** ADR로 남길지와 조항, 릴리스할지.
- [ ] **Step 4: 머지.** CI 녹색과 리뷰 반영 뒤 `gh pr merge <번호> --merge`를 단독 명령으로.
