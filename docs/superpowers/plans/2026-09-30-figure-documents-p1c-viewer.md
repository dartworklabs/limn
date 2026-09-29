# Figure Documents P1c — Viewer Implementation Plan

<!-- Code blocks here are transcribed into the repository and formatted there; ruff leaves them as written. -->
<!-- fmt: off -->

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make figure documents usable in the browser viewer: a `그림` tab without rebuild, a drag that snaps the pending box onto the element the map chose and names its path and code lines, a range ladder that moves between elements without a request, figure pins saved with their element, marks that follow the element across re-renders (or say `요소 잃음`), and `지도로 찾음` in the location-uncertain badge.

**Architecture:** The viewer stays a build-free set of classic-script parts joined by `src/limn/viewer/assemble.py`. One new part, `js/figure.js`, holds the figure-document helpers (element path, snapped box, what a figure pin saves, where its mark goes); the existing parts call them at the seams the spec names (composer, save, repick, marks, cards, document tabs). Every figure value comes from the index's §Shared contract (including `el.frac` on the pick's `el` and every rung's `el`; Task 0 checks the index says so and that P1b's answer carries it); no endpoint is added and no decision step is added — the snapped box is the preview of the mark.

**Tech Stack:** plain JS/CSS viewer parts; pytest running the page's real functions under node (`helpers.extract_js_fn`), Playwright + Chromium browser tests (`tests/helpers_browser.BrowserBase`); stdlib-only Python server (unchanged here).

**Spec:** [`docs/superpowers/specs/2026-09-30-figure-documents-design.md`](../specs/2026-09-30-figure-documents-design.md) (§사용 흐름, §뷰어) and the index [`2026-09-30-figure-documents.md`](2026-09-30-figure-documents.md) (§Shared contract is binding; §Viewer (P1c)). Decisions: [ADR-0011](../../adr/0011-figure-documents.md).

Base: `main` at `5d1c4b6` plus the merged P0, P1a and P1b PRs. Viewer line numbers quoted below are at `5d1c4b6`; P0–P1b change no viewer part except possibly `js/i18n.js` and `src/limn/ui_en.json` (pick warnings). Re-find each quoted line before editing.

## Global Constraints

- Server runtime stays standard-library only (`dependencies = []`); the viewer stays build-free: no bundler, no module loader, no CDN, no new runtime or dev dependency.
- The viewer consumes only the index's §Shared contract fields plus `/api/docs`/`/api/meta` `kind` ("Rebuild UI shows only for `kind == "tex"` (`body.no-rebuild` replaces `body.view-only`). No new endpoint. The new viewer part is `js/figure.js`; the viewer never reads the map."). That includes optional `el.frac` on the pick answer's `el` and every rung's `el`, kept in the record; Task 0 checks the index and P1b's answer before any viewer code. Nothing in §Shared contract is renamed.
- `el` is a location field: a `loc` without `el` drops it, and `/edit` never turns a region pin into a line pin or back (index §Pin record).
- Shared build facts (`FIGMAP_NAME`, `load_build_map`) are imported from `limn.build`; `limn.features.builds.figure` owns only the import (`render_figure_doc`, `figure_src_hash`). Test fixtures branch on document capabilities (`has_element_map`, `view_only`), not on `kind`.
- Owner's product rule: keep decision steps minimal — no new confirm buttons or modes; the server rule decides (map pick) and the UI previews the result before sending (the snapped '새 핀' box is the mark the pin will get). The range ladder is the only choice, as for LaTeX pins.
- Viewer rules (`docs/handbook/viewer.md`): colours only through tokens (`var(--…)`), no new literal outside §리터럴 예외(허용 목록); values compared against are members of the frozen tables in `core.js` (§닫힌 값 표) and each server table is listed in `tests/test_viewer_source.py` `SERVER_SETS`; one-layer wrapping (no bordered box inside a bordered box); icons only Lucide via `ic()`; spacing on the 4px grid.
- UI strings: Korean in the code is the source; every new string goes through `tr()`/`tl()` (or the `T` tooltip table read through `tr(T.x)`) and gets its English in `src/limn/ui_en.json` (`json.dumps(..., ensure_ascii=False, indent=1) + "\n"` reproduces the file byte for byte). User text (element labels, notes) is not given a translation.
- R7: every new or changed JS function has a `//` comment right above it stating intent and contract (the viewer's convention); new Python test modules, classes and helpers have docstrings. R9: test names state the condition and the expectation; write the failing test first and see it fail (or do the stated mutation check for a guard that passes on arrival).
- Browser tests wait on state only (`wait_for_function`, `settle()`, `wait_for_selector`) — never `time.sleep` or `wait_for_timeout` (`docs/handbook/verification.md` §1). CDP touch sequences are dispatched back to back; the long-press waits on the viewer's `LP_PICKED` state.
- Code, comments, docstrings, test names, commit messages: English. Handbook (`viewer.md`): Korean, present tense, no dates. `README.md` and `README.ko.md` change together.
- No real e-mails, home paths or host names (`alice@example.com`, `/srv/paper`).
- JS `//` comments must not end in a call followed by `;` and must not contain `name=call(` (`tests/test_viewer_source.py` `CODE_IN_COMMENT`); a `docs/handbook/X.md §Heading` reference must name an existing heading (`tests/test_handbook_refs.py`).
- Commits: every commit is made with `-s`, then the CLA line is placed right after `Signed-off-by:`:
  ```bash
  git commit -s -m "<subject>" -m "<body>"
  { printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
  ```
- Before each commit: `uv run ruff check --fix <changed .py files>` then `uv run ruff format <changed .py files>`.
- Gates for the PR (Task 7):
  ```bash
  uv sync --group dev
  uv run pytest -q -rs -n 4 --dist loadscope
  bash tests/test_instances.sh
  uv run ruff check
  uv run ruff format --check
  uv run shellcheck src/limn/instances.sh src/limn/features/administration/instance_*.sh tests/test_instances.sh
  uv run mypy
  ```

## Review Focus

1. **Zoom and HiDPI.** At 300 % or on a DPR 2 screen the snapped box and the saved mark stay on the element PDF.js draws (within one CSS pixel of the element's `frac`; the drawn stroke under the box edges). → Task 3 `test_the_snapped_box_stays_on_the_cell_at_fit_and_300_percent_at_dpr_1_and_2`; Task 8 measurement (canvas pixels under the box edges at 100 %/300 %, DPR 1/2/3).
2. **Switching documents while a figure pick is in flight.** The answer that arrives after the switch draws nothing on the new document — no box, no path line, no composer — and raises no error. → Task 3 `test_switching_documents_while_a_figure_pick_is_in_flight_leaves_nothing_behind`.
3. **A landscape / very wide figure page (3:1).** The box and marks line up on it, and a long-press picks the element under the finger instead of a text-line strip that crosses several small elements and climbs to an outer one. → every browser flow runs on the fixture's 3:1 page 1; Task 4 `test_a_long_press_on_a_phone_picks_the_cell_under_the_finger`.
4. **A pin whose element moved to another page.** The mark is drawn on the new page, the card's page link says that page, and [보기] scrolls there. → Task 6 `test_a_mark_whose_element_moved_to_page_2_is_drawn_and_counted_there`.
5. **Touch drag on a phone.** With [선택] on, a one-finger drag across an element picks and snaps exactly like a mouse drag. → Task 3 `test_a_select_mode_finger_drag_on_a_phone_snaps_like_a_mouse_drag`.

---

## Contract issues

**C1 — the viewer needs each rung's element box: `el.frac` (additive; blocks the outline).** The index's pick answer names elements by id only (`el: {id, path, label?, part?, impl?}`, `levels[].el`). The spec requires the element outline over the page and rung switching *without asking the server again* (§사용 흐름 3). The viewer cannot read the map (server-side build state; no endpoint may be added), so every element it may show must carry its box. Needed: optional `frac: [x, y, w, h]` (page fractions on the pick's page, from the `pdf_build` map) on the top-level `el` and on every rung's `el`. **Settled in the index** (§Pick answer `el` row, §Pin record, §Read-time fields): key order `id, path, label?, part?, impl?, frac?`, kept in the record, `frac_then = el.frac` for the read-time follow, and the viewer saves the pin's own `frac` as the element box. The viewer sends `el.frac` back when saving. Task 0 stops before any viewer code if the index or P1b's pick answer lacks it (consumer-side test `tests/test_server.py::FigurePickFeedsTheViewer`); this plan writes no server code. Without it the viewer would still work (no snap; path, ladder, save and marks work), but the spec's outline would be missing.

**C2 — settled in the index** (§Pick answer `levels` and `default_level` rows): rungs with equal lines merge into the **inner** rung (the dragged element stays the default and the top-level `el`; the outer level name goes under `merged`), rungs carry `n`, every rung lies in the chosen element's `src.file`, and `default_level` is the first rung's level (`"el"`, or `"fig"` for a root pick). The viewer follows the kept rung's `el`, derives `n` if it is ever absent (Task 3 `rungLines`) and reads `default_level` as given.

**C3 — the edit card's ladder (now in the index, §Pick answer; P1b Task 7 implements it).** For a file of a figure document, `/api/snippet?levels=1` returns only the `raw` rung, which is also its `default_level` (no map rungs; the edit card has no drag to pick an element from). The viewer's own `lines` rung comes from nudging, as today. Task 5 makes the edit card work with exactly that answer and tests against it.

## Decisions

1. **The outline is the pending box itself.** The '새 핀' box (`COMPOSE.box`) snaps to the chosen rung's element box, and a re-place's '새 위치' box to the candidate's. One box, no extra overlay element or owner; it is exactly the mark the pin will get (preview before sending).
2. **Location line** = `#c-path` (new, `B2 › 달력 › 7월 ·`) + the existing `#c-loc` (`B2_calendar.py L88-L95`). The file part keeps the viewer's notation (`name Llo-Lhi`, the pick's `name`) and its copy format, instead of the spec example's `file:lo–hi`, so composer, cards and copied text stay one format. Path names come from the rung labels; an ancestor without a rung (merged, past the cap, drawn in another file) is written as its id.
3. **Rung labels** are the server's `label` shown as is (a person's words: not run through `levelLabel`), with the usual `· N줄`; tooltips `T.el` / `T.fig`.
4. **The element's range kind is computed in the viewer** (`elKind`, mirroring `figmap.element_kind` including the index's 77-character `part` cap), with a parity test against the server function — no new rung field.
5. **What a figure pin saves.** `el` = the element with only the record's fields (`id, path, label?, part?, impl?, frac?`; the pick's other keys dropped), and the pin's own `frac` = the same element box (not the drag rectangle), so a mark drawn without the current map (lost element, unreadable map) sits where the person saw the box. `el_sync` does not depend on it: P1b's follow reads `el.frac`.
6. **Quick pick on a figure** (long-press, [선택]-mode tap) sends a ±0.4 % square — the map reads it as the point under the finger. The text-line strip (±7 % × ±0.6 %) would climb to an outer element on figures.
7. **Lost element** = the lost-line look (warning dot, border, `triangle-alert` badge) with the text `요소 잃음`, the mark drawn where the pin was placed, and one toast `#N 요소를 잃었습니다` when it happens (as `#N 위치를 잃었습니다` for lines). `moved` shows nothing. A mark the server placed (`mark`) is never dashed (`.est`).
8. **Rebuild hiding** keys on the document kind: `body.no-rebuild` = `META.kind !== DOC_KIND.TEX`, replacing `body.view-only` (whose only use was that rule). The rebuild/redraw toasts key on the kind too. The view-only PDF's behaviour is unchanged.
9. **A region answer with an element** (element without code) is labelled `코드 없는 요소` in the composer and on the card instead of `보기 전용`.
10. **Browser tests send the figure document's pick to the real in-process server** (its map answers without SyncTeX); the manuscript keeps BrowserBase's computed answer. P1b's `tests/helpers_figure.py` is the one figure fixture; this plan appends the viewer tests' documents to it (`viewer_docs`, `viewer_rerender`) and changes nothing P1b defined.
11. **No release here.** Task 7 adds a `## Unreleased` CHANGELOG entry; the version bump and the `v0.4.0` tag follow `docs/handbook/workflow.md` §릴리스 after Task 8's measurement.
12. **Re-place keeps the pin's shape and follows the location rule for `el`.** `applyRepick` always builds a whole new `loc`: with the candidate's element when it has one, without `el` when it has none — then the server drops the pin's old `el` (index: `el` is a location field). Because `/edit` never turns a region pin into a line pin or back, a candidate of the other shape (a figure line pin re-placed where the map is unreadable or the element has no code, or a region pin re-placed onto code) is not offered: the banner says so and waits for another drag (Task 5 `bannerCompare`). No request is sent that the server would refuse.
13. **The edit card of a figure pin** (C3: its ladder is `raw`/`lines` only) keeps the element and its kind unless the lines change: pressing a rung alone sends nothing; nudged lines are saved with scope and kind `lines`, and `el` stays (a range edit is not a `loc`). The pin's element is `EDITOR.current.pinEl` (`EDITOR.current.el` is the card's DOM node). Rungs without a tooltip of their own fall back to `T.cur`.

## Open questions (for the owner; the plan works either way)

- Cards show no element label (`pins.md` has `«label»`). Add later if people ask.
- An element label that happens to equal a UI string (`그림`, `영역`) is translated by the English observer, as any text node is.

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `docs/superpowers/plans/2026-09-30-figure-documents.md` | Check only | Index: `el.frac` on `el` and rung `el`, kept in the record; `el` dropped by a `loc` without it |
| `tests/helpers_figure.py` | Modify (extends P1b's fixture) | Appends the viewer tests' three documents with two-page builds (`viewer_docs`), the re-render (`viewer_rerender`, `viewer_map`) and drag boxes; P1b's names untouched |
| `docs/handbook/verification.md` | Modify | The `tests/helpers_figure.py` row names the viewer part |
| `tests/test_server.py` | Modify | `FigurePickFeedsTheViewer`: what the viewer reads from a figure pick, through the handler |
| `src/limn/viewer/js/core.js` | Modify | Closed tables `VIA`, `DOC_KIND`, `EL_SYNC`; tooltips `T.map`, `T.el`, `T.fig`, `T.elregion`, `T.ellost` |
| `src/limn/viewer/js/figure.js` | Create | Figure helpers: element name/path, snapped box, element line, save fields, element kind, mark place, lost badge |
| `src/limn/viewer/parts.txt` | Modify | `js/figure.js` between `js/levels.js` and `js/composer.js` |
| `src/limn/viewer/js/levels.js` | Modify | `viaTag` names the map; figure rungs in `levelName`/`levelBtns`; `useLevel` selects the rung's element; `rungLines` |
| `src/limn/viewer/js/composer.js` | Modify | `pick` keeps the element; both composer branches draw the element; region-with-element label |
| `src/limn/viewer/js/selection.js` | Modify | `quickBox`, `QUICK_FIG`; `quickPick` uses a point on figures |
| `src/limn/viewer/js/save.js` | Modify | `savePin` adds the figure fields |
| `src/limn/viewer/js/repick.js` | Modify | Candidate box snaps; a candidate of the other shape is not offered; `applyRepick` adds the figure fields |
| `src/limn/viewer/js/edit.js` | Modify | A figure pin's edit card sends a range only when its lines change |
| `src/limn/viewer/js/list.js` | Modify | `marks` at `mark`/`mark_page`, lost style, no `.est` when placed; `jumpPin` page |
| `src/limn/viewer/js/cards.js` | Modify | Lost element badge/dot/border; page link at the mark's page; region-with-element badge |
| `src/limn/viewer/js/polling.js` | Modify | Redraw toast by kind; one toast when an element is lost |
| `src/limn/viewer/js/boot.js`, `js/build-chip.js`, `js/doc-tabs.js` | Modify | Rebuild hiding and toasts by kind; `그림` marker and tip |
| `src/limn/viewer/index.html` | Modify | `#c-path` slot in the location line |
| `src/limn/viewer/css/composer.css`, `css/responsive.css` | Modify | `#c-path`; `.dfig`; `body.no-rebuild` |
| `src/limn/ui_en.json` | Modify | English for every new string |
| `tests/helpers_browser.py` | Modify | `BrowserBase.forward()` split out of `route()` |
| `tests/test_viewer.py` | Modify | `FrontendFigure` guards and node tests; harnesses of `quickPick`, `card`, `savePin`; `FrontendDocs` rule |
| `tests/test_viewer_source.py` | Modify | `SERVER_SETS`: `VIA`, `DOC_KIND`, `EL_SYNC` |
| `tests/test_viewer_async_visits.py` | Modify | Stubs for the new save/repick helpers |
| `tests/test_viewer_browser.py` | Modify | `FigureDocuments` browser flows |
| `tests/test_i18n.py` | Modify | Every `T` tooltip has English |
| `docs/handbook/viewer.md` | Modify | Closed tables, 조작 한눈에, 패널 정리 (그림 요소), 모바일 레이아웃, 상태 표현, 여러 문서 전환, 컴포넌트, 알려진 제약 |
| `README.md`, `README.ko.md`, `CHANGELOG.md` | Modify | One figure-documents line each; Unreleased entry |

`docs/handbook/index.md` is not changed: its file-map row `src/limn/viewer/*` already covers `js/*.js` and says a new part is a `parts.txt` line (checked in Task 7).

---

### Task 0: Contract gate — `el.frac` in the index, the figure fixture, the viewer's pick check

**Files:**
- Check only: `docs/superpowers/plans/2026-09-30-figure-documents.md` (§Pick answer, §Pin record)
- Modify (extends P1b's fixture): `tests/helpers_figure.py` (docstring paragraph, imports, appended viewer helpers)
- Modify: `tests/test_server.py` (new class before `class SocketHarness`)
- Modify: `docs/handbook/verification.md` (§테스트 파일의 배치, the `tests/helpers_figure.py` row)

**Interfaces:**
- Consumes (P0–P1b, index §Shared contract): `limn.documents.DocKind`, `Doc.has_element_map`, `Doc.view_only`, `limn.figmap.MAP_FORMAT`, `MAP_SUFFIX`, `ElSync`, `limn.build.FIGMAP_NAME`, `limn.build.load_build_map`, `limn.web.parse.Via`, `startup_documents.make_docs(specs, ms, paths)` with a `KEY=NAME:PATH.limnmap.json` entry, `POST /api/pick` figure line body.
- Reuses (P1b's `tests/helpers_figure.py`, unchanged): `figure_doc(src, paths) -> Doc`, `b2_map(july=JULY, august=True) -> dict`, `write_build(D, name, fmap, pages=1) -> Path`, `JULY = (0.47, 0.18, 0.07, 0.12)`, `BUILD1 = "pages-20260926100000"`, `BUILD2 = "pages-20260926110000"`.
- Produces (appended to `tests/helpers_figure.py`): `FIG = "fig"`, `ROOT_ID = "B2"`, `STRIP_ID = "B2/calendar"`, `CELL_ID = "B2/calendar/m07"`, `STRIP_FRAC`, `CELL_DRAG`, `STRIP_DRAG`, `WIDE_PX`, `TALL_PX`, `viewer_map(july=JULY, july_page=1) -> dict`, `viewer_build(D, name, fmap=None) -> Path`, `viewer_docs(app, src) -> list[Doc]` (ms, fig, rv), `viewer_rerender(D, july=JULY, july_page=1) -> None`.

- [ ] **Step 1: Confirm P0–P1b are on the branch**

Run:
```bash
uv run python - <<'EOF'
from typing import get_args
from limn import build, documents, figmap
from limn.web import parse
print(sorted(get_args(documents.DocKind)), sorted(get_args(parse.Via)), sorted(get_args(figmap.ElSync)),
      build.FIGMAP_NAME, callable(build.load_build_map), figmap.MAP_SUFFIX, hasattr(documents.Doc, "has_element_map"))
EOF
uv run pytest -q tests/test_i18n.py -k "PickWarnings"
```
Expected: `['figure', 'pdf', 'tex'] ['map', 'synctex', 'text'] ['lost', 'moved', 'ok'] figmap.json True .limnmap.json True`, then `passed`. Anything else: stop — P0–P1b are not in the state the index describes.

- [ ] **Step 2: Check that the index says what the viewer relies on (C1, C2, location rule)**

Run:
```bash
I=docs/superpowers/plans/2026-09-30-figure-documents.md
grep -c '`frac` = the element'"'"'s box on the traced build. The top-level `el` and every rung'"'"'s `el` carry `frac`' "$I"
grep -c 'Rungs with equal `lo`/`hi` merge into the \*\*inner\*\* rung' "$I"
grep -c '| `default_level` | the first rung'"'"'s level' "$I"
grep -c '`el` is a location field: a `loc` without `el` drops it' "$I"
grep -c 'The viewer saves a figure pin'"'"'s own `frac` as the element box' "$I"
```
Expected: `1` five times (§Pick answer `el`, `levels` and `default_level` rows; §Pin record; §Read-time fields). A `0` means the index changed after this plan was written: stop and reconcile the plan with the index before any code.

- [ ] **Step 3: Extend P1b's figure fixture**

`tests/helpers_figure.py` exists (P1b Task 5 creates it; P1b Task 7 appends `pin_from_pick`). Reuse its objects — `figure_doc(src, paths)` (key `fig`, folder `figs/`, script `figs/src/B2_calendar.py`, shared component `lib/components.py`), `b2_map(july=JULY, august=True)` (figure `B2` lines 12-140, strip `B2/calendar` 80-97, July cell `B2/calendar/m07` 88-95 with `impl` `lib/components.py` 410-470, August cell `m08` without code), `JULY`, `BUILD1`, `BUILD2` and `write_build(D, name, fmap, pages=1)` — and append only what the viewer tests need, under names P1b does not use. Do not change any existing name, signature or behaviour.

In the module docstring, append this paragraph before the closing `"""`:

```python

The viewer tests (P1c) add viewer_docs(): the manuscript, figure_doc()'s figure and a reviewer's view-only PDF served
together, each with a two-page build of real page images (the figure's page 1 is 3:1); viewer_map() and
viewer_rerender() move the July cell, take it to page 2 or drop it, as a re-render does.
```

Add `from limn.features.administration import serve_documents as startup_documents` to the `limn` imports, and `blank_png` and `minimal_pdf` to the `from helpers import …` line (create that line if P1b's version has none). Then append at the end of the file:

```python
# ---------------------------------------------------------------- the viewer tests' documents (P1c)

FIG = "fig"  # figure_doc()'s key
ROOT_ID, STRIP_ID, CELL_ID = "B2", "B2/calendar", "B2/calendar/m07"
STRIP_FRAC = (0.06, 0.18, 0.88, 0.12)  # the calendar strip's box in b2_map()
CELL_DRAG = (0.48, 0.20, 0.04, 0.08)  # a drag inside the July cell (JULY), as page fractions
STRIP_DRAG = (0.20, 0.20, 0.04, 0.08)  # a drag inside the strip, clear of the July and August cells
WIDE_PX, TALL_PX = (2400, 800), (1275, 1650)  # page images at 150 dpi: the figure's page 1 is 3:1, the rest portrait


def viewer_map(july=JULY, july_page: int = 1) -> dict:
    """b2_map() with a second page (figure B3, lines 1-10) and the July cell where a re-render left it: at box july on
    page july_page (2: under figure B3), or gone (july None) - its id renamed or dropped."""
    fmap = b2_map(JULY if july is None else july)
    one = fmap["pages"][0]["elements"]
    cell = next(e for e in one if e["id"] == CELL_ID)
    two = [{"id": "B3", "frac": [0, 0, 1, 1], "src": {"file": "src/B2_calendar.py", "lo": 1, "hi": 10}}]
    if july is None or july_page != 1:
        one.remove(cell)
    if july is not None and july_page == 2:
        two.append(dict(cell, parent="B3"))
    fmap["pages"].append({"page": 2, "figure": "B3", "title": "Review flow", "elements": two})
    return fmap


def viewer_build(D: Doc, name: str, fmap: dict | None = None) -> Path:
    """Put the two-page build `name` of document D on screen for the browser: write_build()'s folder (with fmap's copy
    for a figure) whose page images are real PNGs - page 1 WIDE_PX on a figure, TALL_PX otherwise, page 2 TALL_PX - a
    view-only document's own PDF as its copy, and the built_at/head files the meta route reads."""
    d = write_build(D, name, fmap, pages=2)
    for i, (w, h) in enumerate((WIDE_PX if D.has_element_map else TALL_PX, TALL_PX), 1):
        (d / ("page-%d.png" % i)).write_bytes(blank_png(w, h))
    if D.view_only:
        (d / D.pdf_name).write_bytes(D.main.read_bytes())
    (D.dir / "built_at.txt").write_text("2026-09-25 10:00:00")
    (D.dir / "head.txt").write_text("abc1234")
    return d


def viewer_docs(app, src: Path) -> list:
    """Serve the LaTeX manuscript src/main.tex (ms), figure_doc()'s figure (fig) and a reviewer's view-only PDF (rv) from
    app, each with build BUILD1 on screen (viewer_map() for the figure); returns the three documents in that order."""
    (src / "reviewer.pdf").write_bytes(minimal_pdf("reviewer"))
    docs = startup_documents.make_docs(["ms=본문:main.tex", "rv=리뷰어:reviewer.pdf"], src, app.C.paths)
    assert isinstance(docs, list), docs
    ms, rv = docs
    fig = figure_doc(src, app.C.paths)
    app.set_docs([ms, fig, rv])
    for D in (ms, fig, rv):
        viewer_build(D, BUILD1, viewer_map() if D.has_element_map else None)
    return [ms, fig, rv]


def viewer_rerender(D: Doc, july=JULY, july_page: int = 1) -> None:
    """The figure repository rendered again and the import took it: build BUILD2 on screen, with the July cell at july on
    july_page, or gone (july None)."""
    viewer_build(D, BUILD2, viewer_map(july, july_page))
```

Run: `uv run pytest -q -n 4 --dist loadscope $(git grep -l helpers_figure -- 'tests/test_*.py' 'src/**/test_*.py')`
Expected: `0 failed` — P1b's tests that use the fixture are unchanged by the additions.

In `docs/handbook/verification.md` §테스트 파일의 배치, in the `tests/helpers_figure.py` row P1b added, replace `pick 답을 뷰어처럼 저장하는 도우미` with `pick 답을 뷰어처럼 저장하는 도우미, 뷰어 테스트가 쓰는 세 문서(원고·그림·보기 전용 PDF)의 등록과 다시 렌더`.

- [ ] **Step 4: Write the viewer's pick check**

In `tests/test_server.py`, add `import helpers_figure` to the local imports (next to `from helpers import (`; `ruff check --fix` orders it), and insert before `class SocketHarness(unittest.TestCase):`:

```python
class FigurePickFeedsTheViewer(Base):
    """A figure document's pick carries what the viewer draws without asking again (index §Pick answer, P1c): the
    chosen element and every rung's element with its box, so the composer snaps its pending box to the element and the
    range ladder moves it client-side. The viewer's side of P1b's answer, run end to end through the handler."""

    def setUp(self):
        """The manuscript, the figure and the view-only PDF of helpers_figure.viewer_docs, each with a finished build."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, self.src)

    def tearDown(self):
        """Back to the single document the next test expects."""
        ps.APP.set_docs(None)
        super().tearDown()

    def pick_figure(self, drag):
        """POST /api/pick over drag [x, y, w, h] on page 1 of the figure's current build; the decoded 200 body."""
        code, _, raw = split_resp(self.talk(req("GET", "/api/meta?doc=" + helpers_figure.FIG)))
        self.assertEqual(code, 200, raw)
        page = json.loads(raw)["pages"][0]
        x, y, w, h = drag
        body = {
            "doc": helpers_figure.FIG,
            "page": 1,
            "x0": x * page["pt_w"],
            "y0": y * page["pt_h"],
            "x1": (x + w) * page["pt_w"],
            "y1": (y + h) * page["pt_h"],
            "frac": list(drag),
            "pdf_build": helpers_figure.BUILD1,
        }
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pick", body)))
        self.assertEqual(code, 200, raw)
        return json.loads(raw)

    def assert_box(self, got, want):
        """A frac equal to want within float noise."""
        self.assertEqual(len(got), 4, got)
        for g, w in zip(got, want, strict=True):
            self.assertAlmostEqual(g, w, places=6)

    def test_a_drag_in_the_july_cell_answers_every_rung_with_its_element_box(self):
        """The map chooses the cell; the rungs el/el2/fig carry the cell, the strip and the figure, each with its lines
        and its box from the build's map, and the answer's own el is the cell with its box."""
        d = self.pick_figure(helpers_figure.CELL_DRAG)
        self.assertEqual((d["via"], d["default_level"], d["el"]["id"]), ("map", "el", helpers_figure.CELL_ID))
        self.assertEqual(d["el"]["path"], [helpers_figure.ROOT_ID, helpers_figure.STRIP_ID, helpers_figure.CELL_ID])
        self.assert_box(d["el"]["frac"], helpers_figure.JULY)
        rungs = {lv["level"]: lv for lv in d["levels"]}
        want = {
            "el": (helpers_figure.CELL_ID, helpers_figure.JULY, 88, 95),
            "el2": (helpers_figure.STRIP_ID, helpers_figure.STRIP_FRAC, 80, 97),
            "fig": (helpers_figure.ROOT_ID, (0, 0, 1, 1), 12, 140),
        }
        self.assertEqual(sorted(rungs), sorted(want))
        for level, (eid, box, lo, hi) in want.items():
            with self.subTest(level=level):
                self.assertEqual((rungs[level]["el"]["id"], rungs[level]["lo"], rungs[level]["hi"]), (eid, lo, hi))
                self.assert_box(rungs[level]["el"]["frac"], box)
```

- [ ] **Step 5: Run the check**

Run: `uv run pytest -q tests/test_server.py -k FigurePickFeedsTheViewer`
Expected: `1 passed`.
If it fails with `KeyError: 'frac'`: STOP. P1b's pick answer lacks the index's `el.frac` (§Pick answer). The addition belongs to P1b's slice (`src/limn/features/pins/location`); open it as a P1b follow-up PR, merge it, then resume here. Do not add server code in this plan.

- [ ] **Step 6: Red check (R9)**

Temporarily change the first line of the test body to `d = self.pick_figure((0.9, 0.05, 0.02, 0.05))` (the page margin: only the root holds it). Run the same command. Expected: `FAILED` with `AssertionError: Tuples differ` naming `'B2'` where `'B2/calendar/m07'` was expected (the map chose the root). Restore `helpers_figure.CELL_DRAG` and rerun: `1 passed`.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix tests/helpers_figure.py tests/test_server.py && uv run ruff format tests/helpers_figure.py tests/test_server.py
git add tests/helpers_figure.py tests/test_server.py docs/handbook/verification.md
git commit -s -m "test(figure): extend the figure fixture for the viewer and check the pick it reads" -m "P1b's fixture gains the viewer tests' documents: the manuscript, its figure and a view-only PDF with two-page builds (the figure's page 1 is 3:1), and a re-render that moves, relocates or drops the July cell. The server check pins the chosen element and each rung's element box that the viewer draws."
{ printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
```

---

### Task 1: `지도로 찾음` in the location-uncertain badge (closed table `VIA`)

**Files:**
- Modify: `src/limn/viewer/js/core.js:29-30` (closed tables), `:79-80` (`T`)
- Modify: `src/limn/viewer/js/levels.js:49-56` (`viaTag`)
- Modify: `src/limn/ui_en.json`
- Modify: `tests/test_viewer_source.py:23-27, 297-312`
- Modify: `tests/test_viewer.py` (module helpers + new class `FrontendFigure` before `# ---------------------------------------------------------------- icons: Lucide only`)
- Modify: `tests/test_i18n.py` (`MessageTable`)
- Modify: `docs/handbook/viewer.md` (§닫힌 값 표, §상태 표현)

**Interfaces:**
- Consumes: `limn.web.parse.Via` (`synctex|text|map`).
- Produces: `const VIA=Object.freeze({SYNCTEX:'synctex',TEXT:'text',MAP:'map'})`; `T.map`; test helpers `js_tooltips() -> str`, `js_via_limits() -> str` and class `FrontendFigure` (with `node()`) in `tests/test_viewer.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_viewer_source.py`: add `from limn.web import parse as web_parse` after `from limn.viewer import assemble`, and in `SERVER_SETS` after the `"EVENT_TYPE"` line:
```python
    "VIA": lambda: set(get_args(web_parse.Via)),
```

`tests/test_viewer.py`: before the line `# ---------------------------------------------------------------- icons: Lucide only, no emoji/symbol glyphs` add:

```python
def js_tooltips() -> str:
    """The viewer's tooltip table (`const T` in core.js) as the page declares it, for harnesses whose functions read T.x."""
    return re.search(r"^const T=\{.*?^\};$", HTML, re.S | re.M).group(0)


def js_via_limits() -> str:
    """The location-confidence thresholds viaTag() reads (`const VIA_HIDE=...` in levels.js)."""
    return re.search(r"^const VIA_HIDE=.*;$", HTML, re.M).group(0)


# ---------------------------------------------------------------- figure documents (docs/handbook/viewer.md §패널 정리, §상태 표현)
class FrontendFigure(unittest.TestCase):
    """Figure documents in the viewer (P1c): the map as a way of finding, the figure tab without rebuild, the element a
    pick chose (path, rungs, snapped box), what a figure pin saves, and where its mark goes. Pure functions run under
    node; wiring is read from the served source."""

    def node(self):
        """Skip the calling check when node is missing."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_a_figure_pick_under_90_percent_says_it_was_found_by_the_map(self):
        """A figure pick's badge says '지도로 찾음' and the map's hint in Korean and English; 90 % and up shows no
        badge, under 30 % the warning colour."""
        self.node()
        for lang, head in (
            ("ko", "지도로 찾음 · 일치 50% — 그림 지도에서 드래그와"),
            ("en", "Found by the figure map · 50% match — The figure map chose"),
        ):
            with self.subTest(lang=lang):
                js = "\n".join(
                    [
                        js_i18n(lang),
                        js_tooltips(),
                        js_via_limits(),
                        extract_js_fn("viaTag"),
                        "console.log(JSON.stringify([viaTag({via:'map',score:0.5}),viaTag({via:'map',score:0.95}),"
                        "viaTag({via:'map',score:0.2})]));",
                    ]
                )
                half, confident, weak = json.loads(run_node(js))
                self.assertTrue(half["tip"].startswith(head), half["tip"])
                self.assertFalse(half["low"])
                self.assertIsNone(confident)
                self.assertTrue(weak["low"])
```

`tests/test_i18n.py`, class `MessageTable`, after `test_every_composed_key_has_a_translation`:

```python
    def test_every_tooltip_text_has_a_translation(self):
        """The tooltip table T (core.js) reaches the screen through tr(T.x), which composed_keys() cannot see: every text
        in it has an English entry, so a new tooltip is never left in Korean."""
        block = re.search(r"^const T=\{(.*?)^\};$", HTML, re.S | re.M).group(1)
        texts = [re.sub(r"\\(.)", r"\1", m.group(2)) for m in re.finditer(r"\w+:(['\"])((?:\\.|(?!\1).)*)\1", block)]
        self.assertGreater(len(texts), 20)
        self.assertEqual(sorted(t for t in texts if t not in UI_EN), [])
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q tests/test_viewer_source.py tests/test_viewer.py tests/test_i18n.py -k "ClosedSets or FrontendFigure or tooltip"`
Expected: `ClosedSets` fails (`Items in the second set but not the first: 'VIA'` and `KeyError: 'VIA'`); the badge test fails (`'찾은 방법: map · 일치 50% — …' does not start with …`); the tooltip test passes (nothing new in `T` yet).

- [ ] **Step 3: Implement**

`src/limn/viewer/js/core.js`, after the `const EVENT_TYPE=…` line (29):
```js
const VIA=Object.freeze({SYNCTEX:'synctex',TEXT:'text',MAP:'map'});   // how a pick traced its range: a pick's and a pin's `via` (web.parse.Via)
```
In `T`, after the `text:` entry (line 80):
```js
  map:'그림 지도에서 드래그와 가장 많이 겹치는 요소를 골랐습니다. 고른 상자가 고칠 곳을 덮는지 확인하세요.',
```

`src/limn/viewer/js/levels.js`, replace lines 49-56 (the two comment lines, `const VIA_HIDE…` and `viaTag`) with:
```js
// Location match-rate badge: hidden at 90% or above (a number on a location you can trust is just noise). Below that, '위치 불확실';
// below 30%, the warning color. The method used (coordinates, text, or the figure map - whose score is how much of the drag lies in
// the chosen element), the match rate and what to check go in the description. Shared by the composer panel and cards.
const VIA_HIDE=90,VIA_WARN=30;
function viaTag(p){if(!p.via)return null; const pct=Math.round((+p.score||0)*100);
  if(pct>=VIA_HIDE)return null; const low=pct<VIA_WARN;
  const how=p.via===VIA.SYNCTEX?tr('좌표로 찾음'):p.via===VIA.TEXT?tr('글자로 찾음'):p.via===VIA.MAP?tr('지도로 찾음'):tl('찾은 방법: {via}',{via:p.via});
  const why=tr(p.via===VIA.TEXT?T.text:p.via===VIA.MAP?T.map:T.synctex);
  return {t:tr('위치 불확실'),tip:tl('{how} · 일치 {pct}% — {why}',{how,pct,why})+(low?' '+tr('많이 어긋났을 수 있습니다.'):''),low};}
```

- [ ] **Step 4: Run the tests again**

Run the Step 2 command. Expected: `ClosedSets` and the badge test pass for `ko`; the badge test's `en` case and `test_every_tooltip_text_has_a_translation` fail (`['그림 지도에서 드래그와 가장 많이 겹치는 …']` missing from the table).

- [ ] **Step 5: Add the English strings**

```bash
uv run python - <<'EOF'
import json
from pathlib import Path

path = Path("src/limn/ui_en.json")
table = json.loads(path.read_text(encoding="utf-8"))
table.update({
    "지도로 찾음": "Found by the figure map",
    "그림 지도에서 드래그와 가장 많이 겹치는 요소를 골랐습니다. 고른 상자가 고칠 곳을 덮는지 확인하세요.": "The figure map chose the element the drag overlaps most. Check that the chosen box covers the spot to fix.",
})
path.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
EOF
git diff --stat src/limn/ui_en.json
```
Expected: `1 file changed, 3 insertions(+), 1 deletion(-)`.

- [ ] **Step 6: Run the tests and the viewer suites**

Run: `uv run pytest -q tests/test_viewer_source.py tests/test_viewer.py tests/test_i18n.py`
Expected: `0 failed` (the existing `test_via_tag_hides_confident_matches_and_flags_uncertain` still passes: its `synctex`/`text` rows are unchanged).

- [ ] **Step 7: Update viewer.md**

In §닫힌 값 표, after the row
```markdown
| `EVENT_TYPE` | mention · review_requested · replied · reopened · assigned · dropped | `events.EventType` |
```
add
```markdown
| `VIA` | synctex · text · map | pick과 핀의 `via`(`web.parse.Via`) |
```
In §상태 표현, replace the row
```markdown
| `위치 불확실` | 드래그한 글자가 찾은 줄 범위에 90%보다 적게 있다. 30% 미만은 경고 색. 설명에 '좌표로 찾음/글자로 찾음 · 일치 N%'와 확인할 것 | 90% 미만일 때만(작성 패널의 위치 줄도 같다) |
```
with
```markdown
| `위치 불확실` | 드래그한 글자가 찾은 줄 범위에 90%보다 적게 있다. 그림 문서에서는 드래그가 고른 요소 안에 90%보다 적게 들어 있다. 30% 미만은 경고 색. 설명에 '좌표로 찾음/글자로 찾음/지도로 찾음 · 일치 N%'와 확인할 것 | 90% 미만일 때만(작성 패널의 위치 줄도 같다) |
```

Run: `uv run pytest -q tests/test_handbook_refs.py` — Expected: `passed`.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix tests/test_viewer.py tests/test_viewer_source.py tests/test_i18n.py && uv run ruff format tests/test_viewer.py tests/test_viewer_source.py tests/test_i18n.py
git add src/limn/viewer/js/core.js src/limn/viewer/js/levels.js src/limn/ui_en.json tests/test_viewer.py tests/test_viewer_source.py tests/test_i18n.py docs/handbook/viewer.md
git commit -s -m "feat(viewer): name the figure map in the location-uncertain badge" -m "via values are a closed table checked against web.parse.Via; a map pick's badge says 지도로 찾음 with the map's hint. Every tooltip text now needs an English entry."
{ printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
```

---

### Task 2: The figure tab — `그림` marker and rebuild by document kind (closed table `DOC_KIND`)

**Files:**
- Modify: `src/limn/viewer/js/core.js` (after `VIA`)
- Modify: `src/limn/viewer/js/boot.js:59`, `src/limn/viewer/js/build-chip.js:60`, `src/limn/viewer/js/polling.js:63`, `src/limn/viewer/js/doc-tabs.js:19-23`
- Modify: `src/limn/viewer/css/responsive.css:239, 245`
- Modify: `src/limn/ui_en.json`
- Modify: `tests/helpers_browser.py:194-246` (`BrowserBase.route` → `route` + `forward`)
- Modify: `tests/test_viewer.py:1819` (`FrontendDocs`), `FrontendFigure`
- Modify: `tests/test_viewer_source.py` (`SERVER_SETS`)
- Modify: `tests/test_viewer_browser.py` (imports; new class `FigureDocuments` at the end)
- Modify: `docs/handbook/viewer.md` (§닫힌 값 표, §조작 한눈에, §여러 문서 전환, §컴포넌트)

**Interfaces:**
- Consumes: `/api/docs` and `/api/meta` `kind`; `helpers_figure.viewer_docs`, `FIG`.
- Produces: `const DOC_KIND=Object.freeze({TEX:'tex',PDF:'pdf',FIGURE:'figure'})`; body class `no-rebuild`; badge class `.dfig`; `BrowserBase.forward(route)`; browser class `FigureDocuments(BrowserBase)` with `route(route)`, `open_fig(lang="ko", **device) -> page`, static `text(page, sel) -> str | None`.

- [ ] **Step 1: Split `BrowserBase.route` (no behaviour change)**

In `tests/helpers_browser.py`, in `BrowserBase.route`, replace everything from `        body = rq.post_data_buffer or b""` to the end of the method (the final `route.fulfill(...)`) with `        return self.forward(route)`, change the docstring's middle clause to `every other viewer.test request goes to the handler (forward)`, and add after the method:

```python
    def forward(self, route):
        """Send one viewer.test request to the in-process handler as WHO (tailnet headers, and a same-origin Origin on a
        POST) and fulfil the route with the handler's answer."""
        rq = route.request
        u = urlparse(rq.url)
        body = rq.post_data_buffer or b""
        h = {
            "Host": "127.0.0.1:18999",
            "Tailscale-User-Login": self.WHO["Tailscale-User-Login"],
            "Tailscale-User-Name": self.WHO["Tailscale-User-Name"],
        }
        if rq.headers.get("content-type"):
            h["Content-Type"] = rq.headers["content-type"]
        if body:
            h["Content-Length"] = str(len(body))
        if rq.method == "POST":
            h["Origin"] = "http://127.0.0.1:18999"
        raw = (
            "%s %s HTTP/1.1\r\n" % (rq.method, u.path + ("?" + u.query if u.query else ""))
            + "".join("%s: %s\r\n" % kv for kv in h.items())
            + "\r\n"
        ).encode("latin-1") + body
        code, hdrs, data = self.talk(raw)
        route.fulfill(
            status=code, headers={"content-type": hdrs.get("content-type", "application/octet-stream")}, body=data
        )
```

Run: `uv run pytest -q tests/test_viewer_browser.py -k "BrowserOpenWaitsForPins or ViewerRoleUi"` — Expected: `passed` (skipped only without Chromium).

- [ ] **Step 2: Write the failing tests**

`tests/test_viewer_source.py`: import `documents` (`from limn import access, build, documents, events, scope`) and add to `SERVER_SETS` after `"VIA"`:
```python
    "DOC_KIND": lambda: set(get_args(documents.DocKind)),
```

`tests/test_viewer.py`, `FrontendDocs.test_document_selector_and_mobile_button`: replace
```python
        self.assertIn("body.view-only #btn-rebuild{display:none}", css)
```
with
```python
        self.assertIn("body.no-rebuild #btn-rebuild{display:none}", css)
```
and add to `FrontendFigure`:

```python
    def test_rebuild_hides_by_document_kind_not_by_view_only(self):
        """Only a LaTeX document builds: the rebuild button and the rebuilt/redrawn wording follow META.kind and a
        document's kind, never view_only (a figure document is view_only:false and still has no rebuild)."""
        css = HTML[HTML.index("<style>") : HTML.index("</style>")]
        self.assertIn("body.no-rebuild #btn-rebuild{display:none}", css)
        self.assertNotIn("body.view-only", css)
        self.assertIn("document.body.classList.toggle('no-rebuild',META.kind!==DOC_KIND.TEX)", extract_js_fn("drawMeta"))
        for fn in ("drawMeta", "pollBuildOnce", "noteOtherDocs"):
            with self.subTest(fn=fn):
                self.assertNotIn("view_only", extract_js_fn(fn))
                self.assertIn("DOC_KIND.TEX", extract_js_fn(fn))
        self.assertIn(
            "d.kind===DOC_KIND.FIGURE?' · '+tr('그림 문서(드래그하면 요소와 그 요소를 그린 코드 줄을 찾습니다)'):''",
            extract_js_fn("docTip"),
        )

    def test_the_documents_list_marks_a_figure_and_keeps_the_pdf_mark(self):
        """The documents sheet marks a figure '그림' (English 'Figure'), keeps 'PDF' on a view-only PDF, and marks a
        LaTeX document with neither."""
        self.node()
        for lang, word, label in (("ko", "그림", "그림 문서"), ("en", "Figure", "Figure document")):
            with self.subTest(lang=lang):
                js = "\n".join(
                    [
                        js_i18n(lang),
                        js_esc(),
                        "let OPEN_ALL=[]; const DEFAULT_DOC='ms';",
                        extract_js_fn("pdoc"),
                        extract_js_fn("docCount"),
                        extract_js_fn("docBadge"),
                        "console.log(JSON.stringify([{key:'ms',kind:'tex',view_only:false},"
                        "{key:'fig',kind:'figure',view_only:false},{key:'rv',kind:'pdf',view_only:true}].map(docBadge)));",
                    ]
                )
                tex, fig, pdf = json.loads(run_node(js))
                self.assertNotIn("dfig", tex)
                self.assertNotIn("dvo", tex)
                self.assertIn('<span class="badge dfig" aria-label="%s">%s</span>' % (label, word), fig)
                self.assertNotIn("dvo", fig)
                self.assertIn('<span class="badge dvo" aria-label="보기 전용">PDF</span>', pdf)
                self.assertNotIn("dfig", pdf)
```

`tests/test_viewer_browser.py`: add `from urllib.parse import urlparse` to the standard imports and `import helpers_figure` to the local imports; append at the end of the file:

```python
# ---------------------------------------------------------------- figure documents (P1c)


class FigureDocuments(BrowserBase):
    """A figure document (limn-figure-map/1) beside the manuscript and a view-only PDF, in the real viewer: the tab,
    the element a drag picks, the pin saved from it and its mark across re-renders. Page 1 of the figure is 3:1, so
    every flow runs on a very wide page. /api/pick on the figure goes to the real server (its map answers without
    SyncTeX); the manuscript keeps BrowserBase's computed answer."""

    WHO = ALICE
    # First-visit coach marks off, so no hint sits over the page a test drags on.
    NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1}}))}catch(e){}"

    def setUp(self):
        """The three documents of helpers_figure.viewer_docs (P1b's figure_doc among them), each with a finished
        two-page build."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)

    def route(self, route):
        """Send the figure document's pick to the real server; route everything else as BrowserBase does."""
        rq = route.request
        if urlparse(rq.url).path == "/api/pick" and json.loads(rq.post_data or "{}").get("doc") == helpers_figure.FIG:
            return self.forward(route)
        return super().route(route)

    def open_fig(self, lang="ko", **device):
        """The viewer switched to the figure document and settled (open() boots on the manuscript, the first one)."""
        page = self.open(0, lang=lang, init=self.NO_COACH, **device)
        page.evaluate("async()=>await switchDoc('fig')")
        page.wait_for_function("DOC==='fig'&&document.querySelectorAll('#doc .pg').length===2", timeout=8000)
        settle(page)
        return page

    @staticmethod
    def text(page, sel):
        """The textContent of the first element sel matches, or None when there is none (no wait)."""
        return page.evaluate("s=>{const e=document.querySelector(s);return e?e.textContent:null;}", sel)

    def test_a_figure_tab_and_a_view_only_tab_hide_rebuild_and_the_manuscript_keeps_it(self):
        """Rebuild follows the document kind: the manuscript shows [PDF 재빌드]; the figure and the view-only PDF, which
        redraw when their files change, hide it - there and back again."""
        page = self.open(0, init=self.NO_COACH)
        for key, shown in (("ms", True), ("fig", False), ("rv", False), ("ms", True)):
            with self.subTest(doc=key):
                page.evaluate("async k=>await switchDoc(k)", key)
                page.wait_for_function("k=>DOC===k", arg=key, timeout=8000)
                settle(page)
                self.assertEqual(page.locator("#btn-rebuild").is_visible(), shown)
                self.assertEqual(page.evaluate("document.body.classList.contains('no-rebuild')"), not shown)

    def test_the_phone_documents_sheet_marks_the_figure_and_the_view_only_pdf(self):
        """On a phone the documents sheet shows '그림' ('Figure' in English) on the figure and 'PDF' on the view-only
        document, and nothing on the manuscript."""
        for lang, word in (("ko", "그림"), ("en", "Figure")):
            with self.subTest(lang=lang):
                page = self.open(0, lang=lang, init=self.NO_COACH, **DEVICES["phone"])
                page.evaluate("openDocsMenu()")
                page.wait_for_selector("#docs-menu[open] .dm-item", timeout=8000)
                marks = page.eval_on_selector_all(
                    "#docs-menu-list .dm-item",
                    "els=>els.map(e=>[e.dataset.doc,(e.querySelector('.dfig')||{}).textContent||'',"
                    "(e.querySelector('.dvo')||{}).textContent||''])",
                )
                self.assertEqual(marks, [["ms", "", ""], ["fig", word, ""], ["rv", "", "PDF"]])
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest -q tests/test_viewer_source.py tests/test_viewer.py tests/test_viewer_browser.py -k "ClosedSets or FrontendDocs or FrontendFigure or FigureDocuments"`
Expected: `ClosedSets` fails on `DOC_KIND`; `test_document_selector_and_mobile_button` and `test_rebuild_hides_by_document_kind_not_by_view_only` fail (the rule is still `body.view-only`); `test_the_documents_list_marks…` fails (no `dfig`); the browser tab test fails at `doc='fig'` with `AssertionError: True != False`; the sheet test fails (`['fig', '', '']`).

- [ ] **Step 4: Implement**

`src/limn/viewer/js/core.js`, after the `VIA` line:
```js
const DOC_KIND=Object.freeze({TEX:'tex',PDF:'pdf',FIGURE:'figure'});   // a document's `kind` in /api/docs and /api/meta (documents.DocKind)
```

`src/limn/viewer/js/boot.js:59`, replace `  document.body.classList.toggle('view-only',!!META.view_only);` with:
```js
  document.body.classList.toggle('no-rebuild',META.kind!==DOC_KIND.TEX);   // only a LaTeX document builds from source; a view-only PDF and a figure redraw when their files change
```

`src/limn/viewer/js/build-chip.js:60`: replace `toast(tr(META.view_only?'PDF가 바뀌어 쪽을 새로 그렸습니다'` with `toast(tr(META.kind!==DOC_KIND.TEX?'PDF가 바뀌어 쪽을 새로 그렸습니다'`.

`src/limn/viewer/js/polling.js:63`: replace `toast(tl(d.view_only?'{name} PDF 쪽을 새로 그렸습니다'` with `toast(tl(d.kind!==DOC_KIND.TEX?'{name} PDF 쪽을 새로 그렸습니다'`.

`src/limn/viewer/js/doc-tabs.js`, replace lines 19-23 (`docBadge` and `docTip`) with:
```js
// A document's marks in the documents list: building (spinner) or manuscript newer (dot), view-only 'PDF', figure '그림',
// and its open-pin count.
function docBadge(d){const n=docCount(d.key);
  return (d.building?'<span class="spin" aria-label="빌드 중"></span>':(d.stale_build?'<span class="ddot" aria-label="원고 수정됨"></span>':''))+
    (d.view_only?'<span class="badge dvo" aria-label="보기 전용">PDF</span>':'')+
    (d.kind===DOC_KIND.FIGURE?'<span class="badge dfig" aria-label="'+esc(tr('그림 문서'))+'">'+esc(tr('그림'))+'</span>':'')+
    '<span class="badge badge-secondary dcnt'+(n?'':' z')+'" aria-label="'+esc(tl('열린 핀 {n}',{n}))+'">'+n+'</span>';}
// A document link's description: name, path, what kind of document it is, and its build state.
function docTip(d){return d.name+' · '+d.path+(d.view_only?' · 보기 전용 PDF(줄 번호 없이 쪽·영역으로 핀을 남깁니다)':'')+
  (d.kind===DOC_KIND.FIGURE?' · '+tr('그림 문서(드래그하면 요소와 그 요소를 그린 코드 줄을 찾습니다)'):'')+
  (d.building?' · 빌드 중':(d.stale_build?' · 원고가 이 PDF보다 새롭습니다(그 탭에서 [PDF 재빌드])':''));}
```

`src/limn/viewer/css/responsive.css:239`: `.dvo{flex:none;…}` → `.dvo,.dfig{flex:none;line-height:14px;padding:0 var(--space-1);letter-spacing:.02em}`. Line 245: `body.view-only #btn-rebuild{display:none}` → `body.no-rebuild #btn-rebuild{display:none}`.

`src/limn/ui_en.json`:
```bash
uv run python - <<'EOF'
import json
from pathlib import Path

path = Path("src/limn/ui_en.json")
table = json.loads(path.read_text(encoding="utf-8"))
table.update({
    "그림": "Figure",
    "그림 문서": "Figure document",
    "그림 문서(드래그하면 요소와 그 요소를 그린 코드 줄을 찾습니다)": "Figure document (a drag finds the element and the code lines that drew it)",
})
path.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
EOF
```

- [ ] **Step 5: Run the tests again**

Run the Step 3 command. Expected: `0 failed`. Then `uv run pytest -q tests/test_viewer.py tests/test_viewer_list.py tests/test_i18n.py tests/test_viewer_files.py tests/test_viewer_source.py` — Expected: `0 failed` (the `pollBuildOnce` harnesses in `test_viewer.py`/`test_viewer_list.py` receive `DOC_KIND` through `extract_js_fn`'s closed-set prelude and assert no toast text).

- [ ] **Step 6: Update viewer.md**

§닫힌 값 표, after the `VIA` row:
```markdown
| `DOC_KIND` | tex · pdf · figure | 문서의 `kind`(`/api/docs`·`/api/meta`, `documents.DocKind`) |
```
§조작 한눈에 (데스크톱), in the `문서 전환` row replace `스피너는 빌드 중, \`PDF\`는 보기 전용이다` with `스피너는 빌드 중, \`PDF\`는 보기 전용, \`그림\`은 그림 문서다`, and after the `보기 전용 PDF` row add:
```markdown
| 그림 문서 | 문서 목록에 `그림`이 붙고 [PDF 재빌드]는 없다. 그림 저장소가 PDF와 지도를 다시 쓰면 저절로 다시 그린다 | §여러 문서 전환 |
```
§여러 문서 전환, table row `접은 폴드(\`narrow\`)`: replace `아래 시트 목록(이름·경로·핀 수·보기 전용)` with `아래 시트 목록(이름·경로·핀 수·보기 전용 \`PDF\`·그림 문서 \`그림\`)`. Replace
```markdown
**빌드.** [PDF 재빌드]는 지금 문서만 빌드하고, 보기 전용 문서면 숨긴다.
```
with
```markdown
**빌드.** [PDF 재빌드]는 지금 문서만 빌드한다. LaTeX 문서가 아니면(보기 전용 PDF, 그림 문서) 숨긴다. 숨김은 `/api/meta`의 문서 종류(`kind`)로 정하고 `body.no-rebuild`가 맡는다. 두 문서는 파일이 바뀌면 저절로 다시 그리고, 알림은 'PDF가 바뀌어 쪽을 새로 그렸습니다'다.
```
§컴포넌트, `배지` row: replace `참조(\`.arc-ref\`)·보기 전용 표시(\`.dvo\`) |` with `참조(\`.arc-ref\`)·보기 전용 표시(\`.dvo\`)·그림 문서 표시(\`.dfig\`) |`.

Run: `uv run pytest -q tests/test_handbook_refs.py` — Expected: `passed`.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix tests/helpers_browser.py tests/test_viewer.py tests/test_viewer_source.py tests/test_viewer_browser.py && uv run ruff format tests/helpers_browser.py tests/test_viewer.py tests/test_viewer_source.py tests/test_viewer_browser.py
git add src/limn/viewer tests/helpers_browser.py tests/test_viewer.py tests/test_viewer_source.py tests/test_viewer_browser.py src/limn/ui_en.json docs/handbook/viewer.md
git commit -s -m "feat(viewer): mark figure documents and hide rebuild by document kind" -m "A figure document is view_only:false yet has no source build. Rebuild hiding and the rebuilt/redrawn toasts now read the document kind; the documents sheet marks a figure 그림. BrowserBase gains forward() so a test can send one route to the real handler."
{ printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
```

---

### Task 3: The composer shows the picked element — snapped box, path line, element rungs

**Files:**
- Create: `src/limn/viewer/js/figure.js`
- Modify: `src/limn/viewer/parts.txt:48-49`
- Modify: `src/limn/viewer/js/levels.js:17-26` (`levelName`, `levelBtns`), `:37` (`useLevel`)
- Modify: `src/limn/viewer/js/composer.js:31` (`pick`), `:96-104` (`renderRegionComposer`), `:105-111` (`renderComposer`)
- Modify: `src/limn/viewer/js/core.js` (`T`, after `env:`)
- Modify: `src/limn/viewer/index.html:57`, `src/limn/viewer/css/composer.css:5`
- Modify: `src/limn/ui_en.json`
- Modify: `tests/test_viewer.py` (`FrontendFigure`), `tests/test_viewer_browser.py` (`FigureDocuments`)
- Modify: `docs/handbook/viewer.md` (§조작 한눈에, §패널 정리, §여러 문서 전환)

**Interfaces:**
- Consumes: pick answer `el`, `levels[].el` with `frac` (Task 0); `drawBox(box,sx,sy,x,y)` (selection.js); `lvOf`, `tl`, `tr`, `$`.
- Produces (figure.js): `isFrac(f) -> boolean`; `elName(el) -> string`; `elPathText(o) -> string`; `rungTip(lv) -> string`; `snapBox(box, el) -> void`; `renderElement(o, box) -> void`. (levels.js) `rungLines(lv) -> number`. Selection field `COMPOSE.current.elSel` (the element shown: set by `pick()` to `d.el`, replaced by `useLevel()` with the rung's `el`, kept by nudges). `T.el`, `T.fig`, `T.elregion`. Markup `#c-path`. Browser helpers on `FigureDocuments`: `BOX` (JS), `assert_box(page, sel, n, frac)`, `drag(page, frac, n=1, ready=...)`, static `touch(cdp, kind, pts)`, `on_page(page, fx, fy, n=1) -> (x, y)`.

- [ ] **Step 1: Write the failing node and wiring tests**

Add to `FrontendFigure` in `tests/test_viewer.py`:

```python
    def test_the_path_names_each_ancestor_by_its_rung_and_falls_back_to_the_id(self):
        """The location path is root first, named by the rung that carries each id; an ancestor with no rung of its own
        (merged into the inner rung, past the cap, drawn in another file) is written as its id, and a region answer names
        its element itself."""
        self.node()
        js = "\n".join(
            [extract_js_fn("elName"), extract_js_fn("elPathText")]
            + [
                r"""
            const cell={id:'B2/c/m07',path:['B2','B2/c','B2/c/m07'],label:'7월'},root={id:'B2',path:['B2']};
            const full=[{level:'el',lo:24,hi:26,label:'7월',el:cell},{level:'el2',lo:20,hi:30,label:'달력',el:{id:'B2/c',path:['B2','B2/c']}},
                        {level:'fig',lo:1,hi:40,label:'B2',el:root}];
            const merged=[{level:'el',lo:20,hi:30,label:'7월',merged:['el2'],el:cell},{level:'fig',lo:1,hi:40,label:'B2',el:root}];
            const box={id:'B9/x',path:['B9','B9/x'],part:'Box'};
            console.log(JSON.stringify([elPathText({levels:full,el:cell,elSel:cell}),elPathText({levels:full,el:cell,elSel:full[1].el}),
              elPathText({levels:merged,el:cell,elSel:cell}),elPathText({levels:[],el:box,elSel:box}),elPathText({levels:[],elSel:null})]));"""
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)), ["B2 › 달력 › 7월", "B2 › 달력", "B2 › B2/c › 7월", "B9 › Box", ""]
        )

    def test_figure_rungs_are_named_by_their_element_with_a_line_count(self):
        """A figure rung's segment reads its element's name and line count (derived when the rung has no n); its
        tooltip says the element's lines, or the whole figure's for the root."""
        self.node()
        js = "\n".join(
            [js_esc(), js_tooltips()]
            + [
                extract_js_fn(n)
                for n in ("lvOf", "curLevel", "rng", "levelLabel", "elName", "levelName", "rungLines", "rungTip", "levelBtns")
            ]
            + [
                r"""
            const o={lo:24,hi:26,scope:'el',levels:[
              {level:'el',lo:24,hi:26,label:'7월',snippet:'',el:{id:'B2/c/m07',path:['B2','B2/c','B2/c/m07']}},
              {level:'el2',lo:20,hi:30,n:11,label:'달력',snippet:'',el:{id:'B2/c',path:['B2','B2/c']}},
              {level:'fig',lo:1,hi:40,label:'B2',snippet:'',el:{id:'B2',path:['B2']}}]};
            const re=/data-level="([^"]+)" aria-pressed="([^"]+)"[^>]*data-tip="([^"]*)">([^<]*)<span class="k[^"]*">· ([^<]*)</g;
            console.log(JSON.stringify([...levelBtns(o,false).matchAll(re)].map(m=>[m[1],m[2],m[3],m[4].trim(),m[5]])));"""
            ]
        )
        el = "이 요소를 그린 코드 줄입니다. 대기 상자가 그림의 이 요소에 맞춰집니다"
        self.assertEqual(
            json.loads(run_node(js)),
            [
                ["el", "true", "L24-L26 · " + el, "7월", "3줄"],
                ["el2", "false", "L20-L30 · " + el, "달력", "11줄"],
                ["fig", "false", "L1-L40 · 그림 전체를 그린 코드 줄입니다", "B2", "40줄"],
            ],
        )

    def test_the_element_line_names_the_path_and_the_box_snaps_only_to_a_real_box(self):
        """renderElement shows '#c-path' with the path and the element id as its tip, and snaps the pending box to the
        element's frac; an element without a box keeps the dragged box, no element hides the line, no box is no error."""
        self.node()
        js = "\n".join(
            [extract_js_fn(n) for n in ("isFrac", "elName", "elPathText", "drawBox", "snapBox", "renderElement")]
            + [
                r"""
            const nodes={'#c-path':{hidden:true,textContent:'',dataset:{}}}; const $=s=>nodes[s];
            const vals=b=>['left','top','width','height'].map(k=>parseFloat(b.style[k]));
            const cell={id:'B2/c/m07',path:['B2','B2/c','B2/c/m07'],label:'7월',frac:[0.47,0.18,0.07,0.12]};
            const levels=[{level:'el',lo:24,hi:26,label:'7월',el:cell},{level:'el2',lo:20,hi:30,label:'달력',el:{id:'B2/c',path:['B2','B2/c']}},
                          {level:'fig',lo:1,hi:40,label:'B2',el:{id:'B2',path:['B2']}}];
            const line=nodes['#c-path'],out=[];
            const box={style:{left:'48%',top:'20%',width:'4%',height:'8%'}};
            renderElement({levels,el:cell,elSel:cell},box); out.push([line.hidden,line.textContent,line.dataset.tip,vals(box)]);
            const drag={style:{left:'48%',top:'20%',width:'4%',height:'8%'}};
            renderElement({levels,el:cell,elSel:levels[1].el},drag); out.push([line.textContent,vals(drag)]);
            renderElement({file:'/m.tex',elSel:null},drag); out.push([line.hidden,vals(drag)]);
            renderElement({levels,el:cell,elSel:cell},null); out.push(line.hidden);
            console.log(JSON.stringify(out));"""
            ]
        )
        snapped, strip, none, boxless = json.loads(run_node(js))
        self.assertEqual(snapped[:3], [False, "B2 › 달력 › 7월 ·", "요소 B2/c/m07"])
        for got, want in zip(snapped[3], (47, 18, 7, 12), strict=True):
            self.assertAlmostEqual(got, want, places=6)
        self.assertEqual(strip, ["B2 › 달력 ·", [48, 20, 4, 8]])
        self.assertEqual(none, [True, [48, 20, 4, 8]])
        self.assertFalse(boxless)

    def test_a_rung_switch_selects_its_element_and_nudged_lines_keep_it(self):
        """useLevel moves the selection to the rung's lines and element; a nudge makes the lines manual but keeps the
        element; a rung without an element (a LaTeX rung) leaves the element as it was."""
        self.node()
        js = "\n".join(
            [extract_js_fn("lvOf"), extract_js_fn("useLevel"), extract_js_fn("nudge")]
            + [
                r"""
            const cell={id:'c'},strip={id:'s'};
            const o={lo:24,hi:26,n_lines:40,elSel:cell,levels:[{level:'el',lo:24,hi:26,snippet:'a',el:cell},
              {level:'el2',lo:20,hi:30,snippet:'b',el:strip},{level:'raw',lo:5,hi:5,snippet:'r'}]};
            const out=[]; useLevel(o,'el2'); out.push([o.scope,o.lo,o.hi,o.elSel.id]);
            nudge(o,'up-grow'); out.push([o.scope,o.lo,o.elSel.id]);
            useLevel(o,'raw'); out.push([o.scope,o.elSel.id]);
            console.log(JSON.stringify(out));"""
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [["el2", 20, 30, "s"], ["lines", 19, "s"], ["raw", "s"]])

    def test_the_composer_shows_the_element_from_the_pick_without_asking_again(self):
        """The location line has a path slot before the lines; both composer branches draw the element; a pick selects
        its element, a rung its rung's; the element code sends no request; figure.js sits between the ladder and the
        composer parts."""
        self.assertIn('<div class="c-loc-main"><span id="c-path" hidden></span><span id="c-loc"', HTML)
        for fn in ("renderComposer", "renderRegionComposer"):
            self.assertIn("renderElement(d,COMPOSE.box)", extract_js_fn(fn), fn)
        self.assertIn("COMPOSE.current.elSel=d.el||null;", extract_js_fn("pick"))
        self.assertIn("if(lv.el)o.elSel=lv.el;", extract_js_fn("useLevel"))
        for fn in ("elPathText", "snapBox", "renderElement"):
            self.assertNotIn("api(", extract_js_fn(fn), fn)
        parts = (PKG / "viewer" / "parts.txt").read_text(encoding="utf-8")
        self.assertLess(parts.index("js/levels.js"), parts.index("js/figure.js"))
        self.assertLess(parts.index("js/figure.js"), parts.index("js/composer.js"))
```

- [ ] **Step 2: Write the failing browser tests**

Add to `FigureDocuments` in `tests/test_viewer_browser.py`:

```python
    # Where element sel sits on page n, as page fractions of that page's box (inside its border), plus the box's size.
    BOX = """([sel, n]) => {const b=document.querySelector(sel), pg=document.getElementById('p'+n);
      if(!b||b.parentNode!==pg)return null;
      const r=b.getBoundingClientRect(), p=pg.getBoundingClientRect(), L=p.left+pg.clientLeft, T=p.top+pg.clientTop;
      return [(r.left-L)/pg.clientWidth,(r.top-T)/pg.clientHeight,r.width/pg.clientWidth,r.height/pg.clientHeight,
        pg.clientWidth,pg.clientHeight];}"""

    def assert_box(self, page, sel, n, frac):
        """Element sel sits on page n at frac [x, y, w, h], to within one CSS pixel of that page's box."""
        got = page.evaluate(self.BOX, [sel, n])
        self.assertIsNotNone(got, "%s is not on page %d" % (sel, n))
        pw, ph = got[4], got[5]
        for i, (g, want, size) in enumerate(zip(got[:4], frac, (pw, ph, pw, ph), strict=True)):
            self.assertAlmostEqual(g, want, delta=1.0 / size, msg="%s[%d] on a %dx%d page" % (sel, i, pw, ph))

    def drag(self, page, frac, n=1, ready="COMPOSE.current&&!COMPOSE.picking"):
        """A mouse drag across frac [x, y, w, h] of page n through the real pointer path, then wait for ready."""
        page.locator("#p%d" % n).scroll_into_view_if_needed()
        b = page.locator("#p%d" % n).bounding_box()
        x0, y0 = b["x"] + b["width"] * frac[0], b["y"] + b["height"] * frac[1]
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x0 + b["width"] * frac[2], y0 + b["height"] * frac[3], steps=5)
        page.mouse.up()
        page.wait_for_function(ready, timeout=8000)
        settle(page)

    @staticmethod
    def touch(cdp, kind, pts):
        """One CDP touch event (touchStart/touchMove/touchEnd) at the given viewport points."""
        cdp.send(
            "Input.dispatchTouchEvent",
            {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]},
        )

    @staticmethod
    def on_page(page, fx, fy, n=1):
        """The viewport point at fractions (fx, fy) of page n's box."""
        b = page.locator("#p%d" % n).bounding_box()
        return b["x"] + b["width"] * fx, b["y"] + b["height"] * fy

    def test_a_drag_on_the_july_cell_snaps_the_box_to_it_and_names_its_path_and_lines(self):
        """The map chose the cell: '새 핀' sits on the cell's box, the location line reads its path and code lines, and
        the ladder offers cell, strip and figure by name with the cell pressed."""
        page = self.open_fig()
        self.drag(page, helpers_figure.CELL_DRAG)
        self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)
        self.assertEqual(self.text(page, "#c-path"), "B2 › 달력 › 7월 ·")
        self.assertEqual(self.text(page, "#c-loc"), "B2_calendar.py L88-L95")
        self.assertEqual(
            page.eval_on_selector_all(
                "#c-levels button",
                "bs=>bs.map(b=>[b.dataset.level,b.firstChild.textContent.trim(),b.getAttribute('aria-pressed')])",
            ),
            [["el", "7월", "true"], ["el2", "달력", "false"], ["fig", "B2", "false"]],
        )

    def test_a_rung_moves_the_box_path_and_lines_without_asking_the_server(self):
        """Pressing strip, figure, then cell moves '새 핀', the path and the lines each time, and no pick is requested."""
        page = self.open_fig()
        self.drag(page, helpers_figure.CELL_DRAG)
        page.evaluate(
            """()=>{window.pickCalls=0; const f=window.fetch; window.fetch=function(u,o){
              if(String(u).startsWith('/api/pick'))window.pickCalls++; return f.call(this,u,o);};}"""
        )
        for level, box, path, loc in (
            ("el2", helpers_figure.STRIP_FRAC, "B2 › 달력 ·", "B2_calendar.py L80-L97"),
            ("fig", (0, 0, 1, 1), "B2 ·", "B2_calendar.py L12-L140"),
            ("el", helpers_figure.JULY, "B2 › 달력 › 7월 ·", "B2_calendar.py L88-L95"),
        ):
            with self.subTest(level=level):
                page.click('#c-levels [data-level="%s"]' % level)
                settle(page)
                self.assert_box(page, "#doc .sel", 1, box)
                self.assertEqual(self.text(page, "#c-path"), path)
                self.assertEqual(self.text(page, "#c-loc"), loc)
        self.assertEqual(page.evaluate("window.pickCalls"), 0)

    def test_the_snapped_box_stays_on_the_cell_at_fit_and_300_percent_at_dpr_1_and_2(self):
        """The box is placed in page fractions, so it stays on the cell at fit width and at three times that, on a 1x and
        a 2x screen."""
        for dpr in (1, 2):
            with self.subTest(dpr=dpr):
                page = self.open_fig(viewport={"width": 1400, "height": 850}, device_scale_factor=dpr)
                self.drag(page, helpers_figure.CELL_DRAG)
                self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)
                page.evaluate("zoomTo(fitWidth()*3)")
                settle(page)
                self.assertGreater(page.evaluate("document.getElementById('p1').clientWidth"), 2000)
                self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)

    def test_switching_documents_while_a_figure_pick_is_in_flight_leaves_nothing_behind(self):
        """The figure pick answers after the switch to the manuscript: no box, path line or composer appears there and
        the late answer is dropped."""
        page = self.open_fig()
        page.evaluate(
            """()=>{const real=api; window.heldPicks=[];
              api=(path,options)=>path==='/api/pick'?new Promise((ok,no)=>window.heldPicks.push(()=>real(path,options).then(ok,no)))
                :real(path,options);}"""
        )
        page.evaluate("(()=>{const pg=document.getElementById('p1');finishRect(pg,newBox(pg),0.48,0.2,0.52,0.28);})()")
        page.wait_for_function("window.heldPicks.length===1", timeout=8000)
        page.evaluate("async()=>await switchDoc('ms')")
        page.wait_for_function("DOC==='ms'", timeout=8000)
        page.evaluate("window.heldPicks[0]()")
        settle(page)
        self.assertEqual(
            page.evaluate(
                "[COMPOSE.current,COMPOSE.box,COMPOSE.picking,document.querySelectorAll('#doc .sel').length,"
                "document.getElementById('composer').hidden,document.getElementById('c-path').hidden]"
            ),
            [None, None, False, 0, True, True],
        )

    def test_a_select_mode_finger_drag_on_a_phone_snaps_like_a_mouse_drag(self):
        """[선택] on, one finger drags across the cell on a phone: the map chooses the cell and the box snaps to it."""
        page = self.open_fig(**DEVICES["phone"])
        page.evaluate("setSelMode(true)")
        x, y, w, h = helpers_figure.CELL_DRAG
        x0, y0 = self.on_page(page, x, y)
        x1, y1 = self.on_page(page, x + w, y + h)
        cdp = page.context.new_cdp_session(page)
        self.touch(cdp, "touchStart", [(x0, y0)])
        for i in range(1, 7):
            self.touch(cdp, "touchMove", [(x0 + (x1 - x0) * i / 6, y0 + (y1 - y0) * i / 6)])
        self.touch(cdp, "touchEnd", [])
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking", timeout=8000)
        settle(page)
        self.assertEqual(page.evaluate("COMPOSE.current.elSel&&COMPOSE.current.elSel.id"), helpers_figure.CELL_ID)
        self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest -q tests/test_viewer.py tests/test_viewer_browser.py -k "FrontendFigure or FigureDocuments"`
Expected failures: the node tests raise `LookupError: no top-level function elName` (and `rungLines`, `renderElement`); the wiring test fails on `#c-path`; the browser composer/rung/zoom/phone tests fail in `assert_box` (the box is at the drag, `47.9…` vs `0.47`) or on `#c-path` being `None`. The in-flight test already passes (existing `PICKSEQ` handling) — its red phase is Step 6's mutation check.

- [ ] **Step 4: Implement**

Create `src/limn/viewer/js/figure.js`:
```js
// ------------------------------------------------ Figure documents: the element a pick chose, its box and path, what a figure pin saves, where its mark goes
// A figure document's pick answers the element under the drag and the ladder of its ancestors; every rung carries its
// element (levels[].el with id, path root first, label, part, impl and its box `frac` on the pick's page). The composer
// shows that element without another request (docs/handbook/viewer.md §패널 정리): the pending box snaps to it - the mark
// the pin will get - and the location line names its path. The selection keeps the element it shows as elSel.

// Whether f is a page box [x, y, w, h] of four finite numbers - the shape of a pin's frac and an element's frac.
function isFrac(f){return Array.isArray(f)&&f.length===4&&f.every(v=>typeof v==='number'&&Number.isFinite(v));}
// A person's name for an element: its label, else its part, else its id - the rule the pick answer's rung labels follow.
function elName(el){return String((el&&(el.label||el.part||el.id))||'');}
// The selected element's path, root first, as the location line shows it ('B2 › 달력 › 7월'). Each id is named by the
// rung that carries it, else by the pick's own element, else by the id itself: an ancestor merged into an inner rung,
// past the ladder's cap or drawn in another file has no rung, and its id still says where it is.
function elPathText(o){const el=o&&o.elSel; if(!el||!Array.isArray(el.path))return '';
  const names=new Map(); if(o.el&&o.el.id)names.set(o.el.id,elName(o.el));
  (o.levels||[]).forEach(lv=>{if(lv.el&&lv.el.id)names.set(lv.el.id,String(lv.label||elName(lv.el)));});
  return el.path.map(id=>names.get(id)||String(id)).join(' › ');}
// A figure rung's tooltip text: the whole figure's lines for the page's root (its path is itself), else the element's.
function rungTip(lv){return Array.isArray(lv.el.path)&&lv.el.path.length<=1?T.fig:T.el;}
// Puts a pending box (the composer's '새 핀', a re-place's '새 위치') on the element it will pin, so the person sees the
// mark before saving. An element without a box, or no box on screen, leaves the box as dragged.
function snapBox(box,el){if(!box||!el||!isFrac(el.frac))return; const f=el.frac; drawBox(box,f[0],f[1],f[0]+f[2],f[1]+f[3]);}
// The element part of the composer for selection o and its pending box: the path line '#c-path' (hidden when the pick
// found no element - a manuscript, a view-only PDF, a figure whose map is unreadable) and the snapped box.
function renderElement(o,box){const line=$('#c-path'),el=o.elSel; line.hidden=!el;
  if(el){line.textContent=elPathText(o)+' ·'; line.dataset.tip=tl('요소 {id}',{id:el.id});}
  snapBox(box,el);}
```

`src/limn/viewer/parts.txt`, between the `js/levels.js` and `js/composer.js` lines:
```
js/figure.js            # figure documents: the chosen element's box and path, what a figure pin saves, where its mark goes
```

`src/limn/viewer/js/levels.js` — replace the `levelName` declaration line (19) with:
```js
// A figure rung is named by its element as the server labelled it (a person's words, not run through levelLabel).
function levelName(lv,all){if(lv.el)return String(lv.label||elName(lv.el)); if(!lv.env)return levelLabel(lv.label);
```
Replace `levelBtns` (lines 21-26) with:
```js
// The range ladder's segments (composer and edit card): one button per rung, the rung matching the range pressed. A
// figure rung (it carries an element) gets the element's tooltip; its line count comes from lo-hi when the rung has no n.
function levelBtns(o,isEdit){const cur=curLevel(o),ls=o.levels||[]; return ls.map(lv=>{const on=lv===cur,n=rungLines(lv);
  const tip=lv.el?rungTip(lv):isEdit&&lv.level==='raw'?T.cur:(lv.level.startsWith('env')?T.env:T[lv.level]);
  const label=isEdit&&lv.level==='raw'?tr('지금 범위'):levelName(lv,ls),nl=tl('{n}줄',{n});
  return '<button class="'+(on?'on':'')+'" data-act="level" data-level="'+esc(lv.level)+'" aria-pressed="'+on+'" aria-label="'+
    esc(label+' '+rng(lv.lo,lv.hi)+' · '+nl)+'" data-tip="'+esc(rng(lv.lo,lv.hi)+' · '+tr(tip))+'">'+
    esc(label)+' <span class="k'+(n>50?' wn':'')+'">· '+esc(nl)+'</span></button>';}).join('');}
// A rung's line count: the server's n, else its lo-hi span (a figure rung may come without n).
function rungLines(lv){return typeof lv.n==='number'?lv.n:lv.hi-lv.lo+1;}
```
Replace `useLevel` (line 37) with:
```js
// Applies rung key to o (the composer's selection or an edit card): its lines, scope and source; a figure rung also selects
// its element (elSel), which a later nudge to other lines keeps.
function useLevel(o,key){const lv=lvOf(o,key); if(!lv)return; o.lo=lv.lo;o.hi=lv.hi;o.scope=lv.level;o.env=lv.env||null;o.snippet=lv.snippet; if(lv.el)o.elSel=lv.el;}
```

`src/limn/viewer/js/composer.js:31`: replace `COMPOSE.current=d; COMPOSE.current.scope=null; if(!isRegion(d)){` with `COMPOSE.current=d; COMPOSE.current.scope=null; COMPOSE.current.elSel=d.el||null; if(!isRegion(d)){`.
In `renderRegionComposer`, replace
```js
  const pg=$('#c-page'); pg.textContent=tr('보기 전용'); pg.dataset.tip='LaTeX 소스가 없는 PDF입니다 — 줄 번호 없이 쪽·영역과 영역 글자로 핀을 남깁니다';
```
with
```js
  const pg=$('#c-page'); pg.textContent=tr(d.el?'코드 없는 요소':'보기 전용'); pg.dataset.tip=d.el?tr(T.elregion):'LaTeX 소스가 없는 PDF입니다 — 줄 번호 없이 쪽·영역과 영역 글자로 핀을 남깁니다';
```
and its last line `  $('#c-expand').hidden=true;}` with `  $('#c-expand').hidden=true; renderElement(d,COMPOSE.box);}`. Add one line to the comment above it (line 96): `// A figure element without code lines comes back as a region with its element: labelled '코드 없는 요소', its box snapped.`
In `renderComposer`, replace
```js
  $('#c-loc').textContent=d.name+' '+rng(d.lo,d.hi); $('#c-loc').dataset.copy=copy;
```
with
```js
  $('#c-loc').textContent=d.name+' '+rng(d.lo,d.hi); $('#c-loc').dataset.copy=copy; renderElement(d,COMPOSE.box);
```

`src/limn/viewer/js/core.js`, in `T` after the `env:` entry:
```js
  el:'이 요소를 그린 코드 줄입니다. 대기 상자가 그림의 이 요소에 맞춰집니다',
  fig:'그림 전체를 그린 코드 줄입니다',
  elregion:'이 요소를 그린 코드 줄이 지도에 없습니다 — 쪽·영역과 요소로 핀을 남깁니다',
```

`src/limn/viewer/index.html:57`: `<div class="c-loc-main"><span id="c-loc"` → `<div class="c-loc-main"><span id="c-path" hidden></span><span id="c-loc"`.

`src/limn/viewer/css/composer.css`, after `.c-loc-main .loc{font-weight:600}`:
```css
#c-path{color:var(--muted-foreground);font-size:var(--text-sm);overflow-wrap:anywhere}   /* a figure element's path before its code lines */
```

`src/limn/ui_en.json`:
```bash
uv run python - <<'EOF'
import json
from pathlib import Path

path = Path("src/limn/ui_en.json")
table = json.loads(path.read_text(encoding="utf-8"))
table.update({
    "이 요소를 그린 코드 줄입니다. 대기 상자가 그림의 이 요소에 맞춰집니다": "The code lines that drew this element. The pending box snaps to this element in the figure",
    "그림 전체를 그린 코드 줄입니다": "The code lines that drew the whole figure",
    "이 요소를 그린 코드 줄이 지도에 없습니다 — 쪽·영역과 요소로 핀을 남깁니다": "The map has no code lines for this element — the pin keeps its page, region and element",
    "요소 {id}": "Element {id}",
    "코드 없는 요소": "Element without code",
})
path.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
EOF
```

- [ ] **Step 5: Run the tests again**

Run:
```bash
uv run pytest -q tests/test_viewer_files.py tests/test_viewer_source.py
uv run pytest -q tests/test_viewer.py tests/test_i18n.py tests/test_viewer_browser.py -k "FrontendFigure or FigureDocuments or FrontendPanelWidthLogic or FrontendLogic or MessageTable"
```
Expected: `0 failed` in both (`test_viewer_files` checks the new part is listed once and parses; `test_viewer_source` that every new function is called and no comment swallows code).

- [ ] **Step 6: Mutation check for the in-flight guard (R9)**

In `src/limn/viewer/js/composer.js` (`pick`), temporarily replace
```js
  if(seq!==PICKSEQ)return;
  setBusy(false); if(!rp)COMPOSE.picking=false;
```
with
```js
  setBusy(false); if(!rp)COMPOSE.picking=false;
```
Run: `uv run pytest -q tests/test_viewer_browser.py -k in_flight` — Expected: `FAILED` (`[{…}, …, False, …]` ≠ `[None, None, False, 0, True, True]`: the late answer fills the manuscript's composer). Restore the two lines and rerun: `passed`.

- [ ] **Step 7: Update viewer.md**

§조작 한눈에 (데스크톱): replace the `그림 문서` row from Task 2 with:
```markdown
| 그림 문서 | 드래그하면 '새 핀' 상자가 지도가 고른 요소에 맞춰지고, 위치 줄이 요소 경로와 코드 줄(`B2 › 달력 › 7월 · B2_calendar.py L88-L95`)을 보인다. 범위 사다리는 요소 → 부품 → 그림 순이고, 칸을 바꿔도 서버에 다시 묻지 않는다. 문서 목록에 `그림`이 붙고 [PDF 재빌드]는 없다. 그림 저장소가 다시 렌더하면 저절로 다시 그린다 | §패널 정리, §여러 문서 전환 |
```
§패널 정리: insert before the paragraph that starts `**원문.** 기본 4줄로 접고,`:
```markdown
**그림 요소.** 그림 문서의 pick은 드래그 밑의 요소와 그 조상의 사다리를 돌려준다. 단계마다 그 요소(`levels[].el`: id, 뿌리부터의 경로, 이름, 쪽 위 상자 `frac`)가 붙어 있어, 작성 패널은 서버에 다시 묻지 않고 요소를 보인다.

- '새 핀' 상자가 고른 요소의 상자로 옮겨 붙는다. 저장하면 이 상자가 핀의 마크가 된다. 저장 전에 결과를 보이는 미리보기이고, 따로 확인하는 단계는 없다.
- 위치 줄은 요소 경로(`#c-path`)와 코드 줄(`#c-loc`)이다. 예: `B2 › 달력 › 7월 · B2_calendar.py L88-L95`. 경로의 이름은 그 요소를 실은 단계의 이름이고, 단계가 없는 조상(합쳐진 단계, 사다리 한도 밖, 다른 파일에서 그린 요소)은 id로 적는다. 경로의 설명은 요소 id다. 복사 형식은 줄 핀과 같은 `파일 L시작-L끝`이다.
- 범위 사다리의 칸 이름은 요소 이름(`label`, 없으면 `part`, 없으면 id)이고 줄 수가 붙는다. 사용자가 쓴 이름이라 환경 이름 틀(`levelLabel`)을 거치지 않는다. 칸을 바꾸면 상자·위치 줄·원문이 그 요소로 바뀐다. 줄이 같아 합쳐진 칸은 남은 칸의 요소를 쓴다.
- 한 줄 버튼으로 줄을 직접 맞춰도 고른 요소와 상자는 그대로다.
- 요소 상자가 없는 답이면 상자는 드래그한 자리에 남는다.
- 코드 줄이 없는 요소는 영역 선택처럼 보이고, 쪽 옆에 '코드 없는 요소'가 붙는다. 지도를 읽지 못하면 보기 전용 PDF처럼 영역으로 떨어지고, 경고 줄이 이유를 말한다.

```
§여러 문서 전환 (화면 상태의 소유자): after the sentence `저장 응답은 \`composeOwns()\`로 요청 당시 문서 방문과 선택·상자가 여전히 현재 것인지 확인한 뒤 작성 패널을 비운다.` insert:
```markdown
그림 pick이 고른 요소(`COMPOSE.current.elSel`)는 선택의 일부라 선택과 함께 거둬지고, `renderComposer()`가 대기 상자를 그 요소 자리에 맞춘다. 그래서 새 소유자나 요청 번호가 없다. 다른 문서로 옮긴 뒤 도착한 그림 pick 응답은 `PICKSEQ`로 버린다.
```

Run: `uv run pytest -q tests/test_handbook_refs.py` — Expected: `passed`.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix tests/test_viewer.py tests/test_viewer_browser.py && uv run ruff format tests/test_viewer.py tests/test_viewer_browser.py
git add src/limn/viewer src/limn/ui_en.json tests/test_viewer.py tests/test_viewer_browser.py docs/handbook/viewer.md
git commit -s -m "feat(viewer): snap the pending box to the picked figure element" -m "A figure pick carries its element per rung. The pending box snaps to the chosen element (the mark the pin will get), the location line names its path, and rungs switch box, path and lines without a request. New part js/figure.js."
{ printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
```

---

### Task 4: A quick pick on a figure is a point

**Files:**
- Modify: `src/limn/viewer/js/selection.js:10` (constants), `:60-64` (`quickPick`)
- Modify: `tests/test_viewer.py:1009-1024` (`FrontendMobileLogic.test_quick_pick_box_is_small_and_clamped`)
- Modify: `tests/test_viewer_browser.py` (`FigureDocuments`)
- Modify: `docs/handbook/viewer.md` (§모바일 레이아웃)

**Interfaces:**
- Consumes: `META.kind`, `DOC_KIND.FIGURE` (Task 2); `FigureDocuments.touch`, `on_page`, `assert_box` (Task 3).
- Produces: `QUICK_FIG = 0.004`; `quickBox(x, y, figure) -> [x0, y0, x1, y1]` (page fractions).

- [ ] **Step 1: Write the failing tests**

Replace `test_quick_pick_box_is_small_and_clamped` in `tests/test_viewer.py` with:

```python
    def test_quick_pick_box_is_a_line_on_a_manuscript_and_a_point_on_a_figure(self):
        """A quick selection sends about one text line around the point on a manuscript page (+-7 % x +-0.6 %), and a
        +-0.4 % square - the point - on a figure document; both are clamped to the page."""
        js = "\n".join(
            [
                r"""
            const c01=v=>Math.min(1,Math.max(0,v)); const QUICK_W=0.07,QUICK_H=0.006,QUICK_FIG=0.004; const out=[]; let META=null;
            const pg={getBoundingClientRect:()=>({left:100,top:50,width:400,height:600})};
            function newBox(){return {};} function finishRect(pg,box,x0,y0,x1,y1){out.push([x0,y0,x1,y1].map(v=>+v.toFixed(4)));}
            """,
                extract_js_fn("fracAt"),
                extract_js_fn("quickBox"),
                extract_js_fn("quickPick"),
                "quickPick(pg,300,350); quickPick(pg,90,40); quickPick(pg,510,660);"
                " META={kind:'figure'}; quickPick(pg,300,350); quickPick(pg,90,40); console.log(JSON.stringify(out));",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [
                [0.43, 0.494, 0.57, 0.506],
                [0, 0, 0.07, 0.006],
                [0.93, 0.994, 1, 1],
                [0.496, 0.496, 0.504, 0.504],
                [0, 0, 0.004, 0.004],
            ],
        )
```

Add to `FigureDocuments` in `tests/test_viewer_browser.py`:

```python
    def test_a_long_press_on_a_phone_picks_the_cell_under_the_finger(self):
        """A long-press on the cell of a very wide figure picks the cell, not the strip a text-line box would reach, and
        the box snaps to it."""
        page = self.open_fig(**DEVICES["phone"])
        x, y, w, h = helpers_figure.JULY
        px, py = self.on_page(page, x + w / 2, y + h / 2)
        cdp = page.context.new_cdp_session(page)
        self.touch(cdp, "touchStart", [(px, py)])
        page.wait_for_function("LP===null&&LP_PICKED!==null", timeout=8000)
        self.touch(cdp, "touchEnd", [])
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking", timeout=8000)
        settle(page)
        self.assertEqual(page.evaluate("COMPOSE.current.elSel&&COMPOSE.current.elSel.id"), helpers_figure.CELL_ID)
        self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q tests/test_viewer.py tests/test_viewer_browser.py -k "quick_pick or long_press"`
Expected: the node test raises `LookupError: no top-level function quickBox`; the browser test fails with `'B2/calendar' != 'B2/calendar/m07'` (the line-shaped box covers the cell by half only, so the strip wins).

- [ ] **Step 3: Implement**

`src/limn/viewer/js/selection.js:10`: `const LONGPRESS_MS=450,TAP_SLOP=8,QUICK_W=0.07,QUICK_H=0.006;` → `const LONGPRESS_MS=450,TAP_SLOP=8,QUICK_W=0.07,QUICK_H=0.006,QUICK_FIG=0.004;`.
Replace lines 60-64 (the three comment lines and `quickPick`) with:
```js
// Quick selection: calls the existing /api/pick with a small box around the pressed point (quickBox). The server's
// default level is used as-is - 'paragraph' in body text, 'environment' inside a figure/table, the element under the
// point on a figure document - and then widened or narrowed via the range ladder.
function quickPick(pg,cx,cy){const [x,y]=fracAt(pg,cx,cy),b=quickBox(x,y,!!META&&META.kind===DOC_KIND.FIGURE);
  finishRect(pg,newBox(pg),b[0],b[1],b[2],b[3]);}
// The box a quick selection sends around the point (x, y), as page fractions [x0, y0, x1, y1]: about one text line on a
// manuscript page (page width +-7%, height +-0.6%); a small square on a figure, which the map reads as the point - the
// deepest element holding it (docs/handbook/viewer.md §모바일 레이아웃). A line-shaped strip would cross a figure's
// small elements and resolve to an outer one.
function quickBox(x,y,figure){const w=figure?QUICK_FIG:QUICK_W,h=figure?QUICK_FIG:QUICK_H;
  return [c01(x-w),c01(y-h),c01(x+w),c01(y+h)];}
```

- [ ] **Step 4: Run the tests again**

Run the Step 2 command. Expected: `2 passed` (the browser one skipped only without Chromium).

- [ ] **Step 5: Update viewer.md**

§모바일 레이아웃, in the bullet that starts `- 빠른 선택은 누른 점 둘레의 작은 상자(쪽 폭 ±7%, 높이 ±0.6%)로`, append after `…범위 사다리로 넓힌다([domain.md](domain.md) §범위 사다리).`:
```markdown
 그림 문서에서는 상자가 ±0.4% 정사각형이다. 지도는 이 점을 품은 가장 깊은 요소를 고른다. 글 한 줄 모양의 긴 띠는 작은 요소 여럿에 걸쳐 바깥 요소로 올라가기 때문이다.
```

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix tests/test_viewer.py tests/test_viewer_browser.py && uv run ruff format tests/test_viewer.py tests/test_viewer_browser.py
git add src/limn/viewer/js/selection.js tests/test_viewer.py tests/test_viewer_browser.py docs/handbook/viewer.md
git commit -s -m "feat(viewer): quick-pick a point on figure documents" -m "A long-press or a select-mode tap sent a text-line strip; on a wide figure it crossed small elements and resolved to an outer one. On a figure it now sends a small square the map reads as the point."
{ printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
```

---

### Task 5: Save and re-place send the element

**Files:**
- Modify: `src/limn/viewer/js/figure.js` (append)
- Modify: `src/limn/viewer/js/save.js:36`
- Modify: `src/limn/viewer/js/repick.js:6-10` (`bannerCompare`), `:18` (`startRepick`), `:23-28` (`applyRepick`)
- Modify: `src/limn/viewer/js/edit.js:27-30` (`openEdit`), `:63` (`saveEdit`); `src/limn/viewer/js/levels.js` (`levelBtns` tooltip fallback)
- Modify: `src/limn/viewer/js/core.js` (`T`), `src/limn/ui_en.json`
- Modify: `tests/test_viewer.py` (imports; `FrontendFigure`; `FrontendSaveWhilePicking._harness` stub at line 2456)
- Modify: `tests/test_viewer_async_visits.py:137, 394, 430` (stubs)
- Modify: `tests/test_viewer_browser.py` (`FigureDocuments`)
- Modify: `docs/handbook/viewer.md` (§패널 정리 — 그림 요소)

**Interfaces:**
- Consumes: `COMPOSE.current.elSel`, `isFrac`, `snapBox` (Task 3); `lvOf`; `limn.figmap.MapElement`, `SourceRef`, `element_kind`.
- Consumes (index §Pin record): `el` is a location field — a `loc` without `el` drops it; `/edit` never turns a region pin into a line pin or back. C3: `/api/snippet?levels=1` for a figure file answers `raw`/`lines` rungs only.
- Produces (figure.js): `elForSave(el) -> {id, path, label?, part?, impl?, frac?}`; `elKind(el) -> 'figure' | 'el:<part, at most 77 chars>' | 'el:?'`; `figureFields(body, el, rung) -> body`; `figRung(o) -> rung | null`; `repickEl(c) -> el | null`. `REPICK.from.region` (the pin's shape); `EDITOR.current.pinEl` (the pin's element); `T.shape`. Browser helpers `saved_cell_pin(page, note) -> int`, `assert_frac(got, want)`.

- [ ] **Step 1: Write the failing node and wiring tests**

In `tests/test_viewer.py` add `from limn import figmap` to the imports, and add to `FrontendFigure`:

```python
    def test_figure_fields_send_the_element_with_its_box_and_the_box_as_frac(self):
        """A pin body gets el with the record's fields only (id, path, label, part, impl, frac - no unknown keys), the
        element's box as its own frac too, and the element's kind when the range is that element's rung; nudged lines
        keep the body's kind; a pick without an element is untouched."""
        self.node()
        js = "\n".join(
            [extract_js_fn(n) for n in ("isFrac", "elForSave", "elKind", "figureFields")]
            + [
                r"""
            const cell={id:'B2/c/m07',path:['B2','B2/c','B2/c/m07'],label:'7월',part:'MonthCell',
              impl:{file:'lib/components.py',lo:1,hi:5,extra:1},frac:[0.47,0.18,0.07,0.12],unknown:'x'};
            const root={id:'B2',path:['B2'],frac:[0,0,1,1]};
            console.log(JSON.stringify([
              figureFields({frac:[0.48,0.2,0.04,0.08],kind:'lines'},cell,{el:cell}),
              figureFields({frac:[0.48,0.2,0.04,0.08],kind:'lines'},cell,null),
              figureFields({frac:[0.1,0.1,0.1,0.1]},{id:'x',path:['B2','x']},null),
              figureFields({kind:'lines'},root,{el:root}),
              figureFields({kind:'paragraph'},null,null)]));"""
            ]
        )
        cell = {
            "id": "B2/c/m07",
            "path": ["B2", "B2/c", "B2/c/m07"],
            "label": "7월",
            "part": "MonthCell",
            "impl": {"file": "lib/components.py", "lo": 1, "hi": 5},
            "frac": [0.47, 0.18, 0.07, 0.12],
        }
        got = json.loads(run_node(js))
        self.assertEqual(
            got,
            [
                {"frac": [0.47, 0.18, 0.07, 0.12], "kind": "el:MonthCell", "el": cell},
                {"frac": [0.47, 0.18, 0.07, 0.12], "kind": "lines", "el": cell},
                {"frac": [0.1, 0.1, 0.1, 0.1], "el": {"id": "x", "path": ["B2", "x"]}},
                {"kind": "figure", "el": {"id": "B2", "path": ["B2"], "frac": [0, 0, 1, 1]}, "frac": [0, 0, 1, 1]},
                {"kind": "paragraph"},
            ],
        )
        self.assertEqual(list(got[0]["el"]), ["id", "path", "label", "part", "impl", "frac"])  # the record's key order

    def test_el_kind_names_elements_like_the_server(self):
        """The viewer's elKind() and the server's figmap.element_kind() name the same elements the same way: 'figure'
        for a page's root (with or without a part), 'el:<part>' below it with the part cut to 77 characters, 'el:?'
        without a part."""
        self.node()
        src = figmap.SourceRef(file="B2_calendar.py", lo=1, hi=40)

        def element(eid, parent, part, label):
            return figmap.MapElement(
                id=eid, parent=parent, frac=(0.1, 0.1, 0.2, 0.2), src=src, impl=None, part=part, label=label
            )

        cases = [
            (element("B2", None, None, None), True, {"id": "B2", "path": ["B2"]}),
            (element("B2", None, "Figure", "그림"), True, {"id": "B2", "path": ["B2"], "part": "Figure"}),
            (element("B2/c", "B2", "CalendarStrip", "달력"), False, {"id": "B2/c", "path": ["B2", "B2/c"], "part": "CalendarStrip"}),
            (element("B2/c/x", "B2/c", None, "7월"), False, {"id": "B2/c/x", "path": ["B2", "B2/c", "B2/c/x"]}),
            (element("B2/c/y", "B2/c", "P" * 100, None), False, {"id": "B2/c/y", "path": ["B2", "B2/c", "B2/c/y"], "part": "P" * 100}),
        ]
        js = extract_js_fn("elKind") + "\nconsole.log(JSON.stringify(%s.map(elKind)));" % json.dumps(
            [c[2] for c in cases], ensure_ascii=False
        )
        self.assertEqual(json.loads(run_node(js)), [figmap.element_kind(e, root) for e, root, _ in cases])

    def test_saving_and_re_placing_send_the_figure_element(self):
        """savePin adds the figure fields after the region shape is chosen; a re-place adds them to its loc and snaps
        its '새 위치' box to the candidate's element."""
        save = extract_js_fn("savePin")
        region = "if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};"
        self.assertLess(save.index(region), save.index("figureFields(body,d.elSel,isRegion(d)?null:figRung(d));"))
        rp = extract_js_fn("applyRepick")
        self.assertLess(
            rp.index("if(isRegion(c))loc="), rp.index("figureFields(loc,repickEl(c),isRegion(c)||!lv.el?null:lv);")
        )
        self.assertIn("snapBox(REPICK.box,repickEl(c));", extract_js_fn("bannerCompare"))
        self.assertIn("region:!!EDITOR.current.region", extract_js_fn("startRepick"))
        self.assertIn("pinEl:p.el||null", extract_js_fn("openEdit"))
        self.assertIn("(!E.pinEl&&(E.scope||null)!==(E.orig.scope||null))", extract_js_fn("saveEdit"))

    def test_a_re_place_candidate_of_the_other_shape_is_not_offered(self):
        """/edit never turns a line pin into a region pin or back, so a candidate of the other shape (a region answer for
        a line pin, lines for a region pin) is dropped and the banner asks for another drag with the reason; a candidate
        of the same shape gets [이 위치로 바꾸기]."""
        self.node()
        js = "\n".join(
            [js_tooltips(), js_esc()]
            + [
                extract_js_fn(n)
                for n in ("isRegion", "lvOf", "levelLabel", "isFrac", "drawBox", "snapBox", "repickEl", "bannerCompare")
            ]
            + [
                r"""
            const out=[]; let REPICK;
            function banner(h){out.push(/data-act="rp-apply"/.test(h)?'apply':'banner');}
            function bannerRepick(err){out.push(['again',err]);} function scopeLabel(){return '';}
            const region={kind:'region',page:1,frac:[0.2,0.2,0.1,0.1],pdf:'x.pdf',quote:''};
            const line={file:'/f.py',page:1,lo:20,hi:30,default_level:'el',
              levels:[{level:'el',lo:20,hi:30,label:'달력',el:{id:'B2/c',path:['B2','B2/c']}}]};
            for(const [fromRegion,cand] of [[false,region],[true,line],[false,line],[true,region]]){
              REPICK={id:7,from:{lo:24,hi:26,page:1,region:fromRegion},box:null,cand};
              bannerCompare(); out.push(REPICK.cand===null);}
            console.log(JSON.stringify(out));"""
            ]
        )
        shape = "이 자리는 지금 핀과 모양(줄/영역)이 달라 옮길 수 없습니다 — 다른 자리를 고르거나 새 핀을 남기세요"
        self.assertEqual(
            json.loads(run_node(js)),
            [["again", shape], True, ["again", shape], True, "apply", False, "apply", False],
        )

    def test_an_edit_ladder_of_raw_and_lines_rungs_has_real_tooltips(self):
        """A figure pin's edit card gets only raw/lines rungs from /api/snippet?levels=1 (C3): the current range reads
        '지금 범위', and a rung the tooltip table has no entry for falls back to the current-range tooltip instead of
        'undefined'."""
        self.node()
        js = "\n".join(
            [js_esc(), js_tooltips()]
            + [
                extract_js_fn(n)
                for n in ("lvOf", "curLevel", "rng", "levelLabel", "elName", "levelName", "rungLines", "rungTip", "levelBtns")
            ]
            + [
                r"""
            const E={lo:24,hi:26,scope:'el',levels:[{level:'raw',lo:24,hi:26,label:'드래그한 줄',snippet:''},
              {level:'lines',lo:20,hi:30,label:'줄',snippet:''}]};
            const re=/data-level="([^"]+)" aria-pressed="([^"]+)"[^>]*data-tip="([^"]*)">([^<]*)</g;
            console.log(JSON.stringify([...levelBtns(E,true).matchAll(re)].map(m=>[m[1],m[2],m[3],m[4].trim()])));"""
            ]
        )
        cur = "지금 핀이 가리키는 범위 그대로입니다"
        self.assertEqual(
            json.loads(run_node(js)),
            [["raw", "true", "L24-L26 · " + cur, "지금 범위"], ["lines", "false", "L20-L30 · " + cur, "줄"]],
        )
```

- [ ] **Step 2: Write the failing browser tests**

Add to `FigureDocuments`:

```python
    def assert_frac(self, got, want):
        """A stored frac equal to want within float noise."""
        self.assertEqual(len(got), 4, got)
        for g, w in zip(got, want, strict=True):
            self.assertAlmostEqual(g, w, places=6)

    def saved_cell_pin(self, page, note):
        """Pick the July cell, write note, press [핀 저장], and return the new pin's id once the list shows it."""
        self.drag(page, helpers_figure.CELL_DRAG)
        page.locator("#note").fill(note)
        page.click("#btn-save")
        page.wait_for_function("n=>OPEN_ALL.some(p=>p.note===n)", arg=note, timeout=8000)
        settle(page)
        return page.evaluate("n=>OPEN_ALL.find(p=>p.note===n).id", note)

    def test_saving_a_pick_stores_the_chosen_element_its_box_and_kind(self):
        """[핀 저장] on the cell stores the cell with its box as el, the cell's box as frac too, el:MonthCell and its
        lines; after pressing the strip rung, the strip with its box, kind and lines."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        rec = find_record(ps.APP.snapshot_pins(), pid)
        self.assertEqual(
            (rec["doc"], rec["scope"], rec["kind"], rec["via"], rec["lo"], rec["hi"]),
            ("fig", "el", "el:MonthCell", "map", 88, 95),
        )
        self.assertEqual(
            {k: v for k, v in rec["el"].items() if k != "frac"},
            {
                "id": helpers_figure.CELL_ID,
                "path": [helpers_figure.ROOT_ID, helpers_figure.STRIP_ID, helpers_figure.CELL_ID],
                "label": "7월",
                "part": "MonthCell",
                "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
            },
        )
        self.assert_frac(rec["el"]["frac"], helpers_figure.JULY)
        self.assert_frac(rec["frac"], helpers_figure.JULY)
        self.drag(page, helpers_figure.CELL_DRAG)
        page.click('#c-levels [data-level="el2"]')
        settle(page)
        page.locator("#note").fill("달력 줄 간격")
        page.click("#btn-save")
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='달력 줄 간격')", timeout=8000)
        settle(page)
        strip = find_record(ps.APP.snapshot_pins(), page.evaluate("OPEN_ALL.find(p=>p.note==='달력 줄 간격').id"))
        self.assertEqual(
            (strip["scope"], strip["kind"], strip["lo"], strip["hi"], strip["el"]["id"]),
            ("el2", "el:CalendarStrip", 80, 97, helpers_figure.STRIP_ID),
        )
        self.assert_frac(strip["el"]["frac"], helpers_figure.STRIP_FRAC)
        self.assert_frac(strip["frac"], helpers_figure.STRIP_FRAC)

    def test_re_placing_a_cell_pin_on_the_strip_moves_its_element_box_and_lines(self):
        """[위치 다시 잡기] on the strip: '새 위치' snaps to the strip before [이 위치로 바꾸기], and the pin then stores
        the strip - its element, box, kind and lines."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_selector(".edit .b-repick", timeout=8000)
        page.click(".edit .b-repick")
        page.wait_for_function("REPICK!==null", timeout=8000)
        self.drag(page, helpers_figure.STRIP_DRAG, ready="REPICK&&REPICK.cand")
        self.assert_box(page, "#doc .sel", 1, helpers_figure.STRIP_FRAC)
        page.click('#banner [data-act="rp-apply"]')
        page.wait_for_function("REPICK===null", timeout=8000)
        settle(page)
        rec = find_record(ps.APP.snapshot_pins(), pid)
        self.assertEqual(
            (rec["lo"], rec["hi"], rec["kind"], rec["el"]["id"]), (80, 97, "el:CalendarStrip", helpers_figure.STRIP_ID)
        )
        self.assert_frac(rec["frac"], helpers_figure.STRIP_FRAC)

    def test_the_edit_card_keeps_a_figure_pins_element_and_kind_unless_its_lines_change(self):
        """The edit card's ladder is the snippet route's raw/lines rungs (C3): pressing '지금 범위' and saving sends
        nothing; nudging a line saves the new lines with kind 'lines', and the pin keeps its el (a range edit is no loc)."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        for step in ("press the current range", "nudge one line down"):
            with self.subTest(step=step):
                page.evaluate("id=>openEdit(id)", pid)
                page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0", timeout=8000)
                settle(page)
                tips = page.eval_on_selector_all(".edit .e-levels button", "bs=>bs.map(b=>b.dataset.tip)")
                self.assertTrue(tips and all("undefined" not in t for t in tips), tips)
                if step == "press the current range":
                    page.click('.edit .e-levels [data-level="raw"]')
                else:
                    page.click('.edit [data-dir="down-grow"]')
                settle(page)
                page.click(".edit .b-esave")
                page.wait_for_function("EDITOR.current===null", timeout=8000)
                settle(page)
                rec = find_record(ps.APP.snapshot_pins(), pid)
                want = ("el", "el:MonthCell", 88, 95) if step == "press the current range" else ("lines", "lines", 88, 96)
                self.assertEqual((rec["scope"], rec["kind"], rec["lo"], rec["hi"]), want)
                self.assertEqual(rec["el"]["id"], helpers_figure.CELL_ID)
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest -q tests/test_viewer.py tests/test_viewer_browser.py -k "FrontendFigure or saving_a_pick or re_placing or edit_card"`
Expected: `LookupError: no top-level function elForSave` / `elKind` / `repickEl`; the wiring test fails (`substring not found`); the edit-ladder test shows `'L20-L30 · undefined'`; the browser tests fail on `KeyError: 'el'` (the record has no element), on `kind` `'lines'` ≠ `'el:MonthCell'`, or on the edit card's `('raw', 'lines', 88, 95)` ≠ `('el', 'el:MonthCell', 88, 95)`.

- [ ] **Step 4: Implement**

Append to `src/limn/viewer/js/figure.js`:
```js
// The `el` a pin stores (POST /api/pin, an edit's loc): the pick's element with only the fields the pin record defines, in
// its order - id, path, label, part, impl and the element's box `frac` on the build it was picked on, which the server's
// read-time follow compares with the current build.
function elForSave(el){const out={id:el.id,path:Array.isArray(el.path)?el.path.slice():[]};
  for(const k of ['label','part'])if(typeof el[k]==='string')out[k]=el[k];
  if(el.impl&&typeof el.impl==='object')out.impl={file:el.impl.file,lo:el.impl.lo,hi:el.impl.hi};
  if(isFrac(el.frac))out.frac=el.frac.slice();
  return out;}
// The range kind of an element rung as the server names it (figmap.element_kind): 'figure' for the page's root (its path
// is itself), else 'el:<part>' with the part cut to 77 characters (a kind stays within 80), 'el:?' without a part.
// tests/test_viewer.py runs both on the same elements.
function elKind(el){return Array.isArray(el.path)&&el.path.length<=1?'figure':'el:'+String(el.part||'?').slice(0,77);}
// Adds a figure pick's fields to a pin body or a re-place loc and returns it: `el`, the element's box as the pin's own
// `frac` too (a mark drawn without the current map then sits where the person saw the snapped box), and the element's
// kind when the range is that element's rung (rung given). A pick without an element is left as it is; lines nudged by
// hand keep the kind the body already has.
function figureFields(body,el,rung){if(!el)return body; body.el=elForSave(el); if(isFrac(el.frac))body.frac=el.frac.slice();
  if(rung&&rung.el)body.kind=elKind(el); return body;}
// The rung the selection's scope names when it is a figure rung (it carries an element), else null.
function figRung(o){const lv=o&&o.scope&&lvOf(o,o.scope); return lv&&lv.el?lv:null;}
// The element a re-place candidate would move the pin to: its default rung's, else the answer's own (a region answer).
function repickEl(c){const lv=lvOf(c,c.default_level); return (lv&&lv.el)||c.el||null;}
```

`src/limn/viewer/js/save.js`, after line 36 (`  if(isRegion(d))body={page:d.page,…};   // view-only: page/region only`) add:
```js
  figureFields(body,d.elSel,isRegion(d)?null:figRung(d));   // a figure pick: its element as el, the element's box as frac, its kind
```

`src/limn/viewer/js/repick.js` — in `bannerCompare`, replace
```js
    '<button class="btn-sm btn-default" data-act="rp-apply" data-tip="번호와 메모는 그대로 두고 위치만 바꿉니다">이 위치로 바꾸기</button>'+
    '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');}
```
with
```js
    '<button class="btn-sm btn-default" data-act="rp-apply" data-tip="번호와 메모는 그대로 두고 위치만 바꿉니다">이 위치로 바꾸기</button>'+
    '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');
  snapBox(REPICK.box,repickEl(c));}
```
and replace the first line of `bannerCompare`
```js
function bannerCompare(){const c=REPICK.cand,lv=lvOf(c,c.default_level)||c,rg=isRegion(c);
```
with
```js
// The re-place banner compares the current and the new place; on a figure the '새 위치' box snaps to the new element. A
// candidate of the other shape (a region for a line pin, lines for a region pin) is dropped and the banner asks for
// another drag: /edit never changes a pin's shape, so no request it would refuse is offered.
function bannerCompare(){const c=REPICK.cand,lv=lvOf(c,c.default_level)||c,rg=isRegion(c);
  if(rg!==!!REPICK.from.region){REPICK.cand=null; bannerRepick(tr(T.shape)); return;}
```
In `startRepick` (line 18), replace `from:{lo:EDITOR.current.lo,hi:EDITOR.current.hi,page:EDITOR.current.page}` with `from:{lo:EDITOR.current.lo,hi:EDITOR.current.hi,page:EDITOR.current.page,region:!!EDITOR.current.region}`.
In `applyRepick`, after `  if(isRegion(c))loc={page:c.page,frac:c.frac,quote:c.quote,pdf_build:c.pdf_build||undefined};   // view-only: only the region is re-placed` add:
```js
  figureFields(loc,repickEl(c),isRegion(c)||!lv.el?null:lv);   // a new loc names its element or none: a loc without el drops the pin's el
```

`src/limn/viewer/js/edit.js` — in `openEdit`'s `EDITOR.current={…}` literal, replace `doc:pdoc(p),region:isRegion(p),page:p.page,` with `doc:pdoc(p),region:isRegion(p),pinEl:p.el||null,page:p.page,` (`el` there is already the card's DOM node). In `saveEdit`, replace
```js
  if(E.lo!==E.orig.lo||E.hi!==E.orig.hi||(E.scope||null)!==(E.orig.scope||null)){body.lo=E.lo;body.hi=E.hi;
```
with
```js
  // A figure pin's ladder here is raw/lines only (no element rungs): a rung press alone would trade the element's kind
  // for 'lines', so only changed lines are sent; the pin keeps its el either way (a range edit is not a loc).
  if(E.lo!==E.orig.lo||E.hi!==E.orig.hi||(!E.pinEl&&(E.scope||null)!==(E.orig.scope||null))){body.lo=E.lo;body.hi=E.hi;
```

`src/limn/viewer/js/levels.js`, in `levelBtns` (the tooltip line written in Task 3), replace `(lv.level.startsWith('env')?T.env:T[lv.level]);` with `(lv.level.startsWith('env')?T.env:T[lv.level])||T.cur;` — a rung the tooltip table has no entry for (`lines` on a figure pin's edit card) reads as the current range.

`src/limn/viewer/js/core.js`, in `T` after the `elregion:` entry:
```js
  shape:'이 자리는 지금 핀과 모양(줄/영역)이 달라 옮길 수 없습니다 — 다른 자리를 고르거나 새 핀을 남기세요',
```
`src/limn/ui_en.json`:
```bash
uv run python - <<'EOF'
import json
from pathlib import Path

path = Path("src/limn/ui_en.json")
table = json.loads(path.read_text(encoding="utf-8"))
table.update({
    "이 자리는 지금 핀과 모양(줄/영역)이 달라 옮길 수 없습니다 — 다른 자리를 고르거나 새 핀을 남기세요": "This spot has a different shape (lines/region) from the pin, so the pin cannot move there — pick another spot or leave a new pin",
})
path.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
EOF
```

Harness stubs (the real functions are not pulled into these harnesses):
- `tests/test_viewer.py:2456`: `async function loadPins(){} function useLevel(){} function isRegion(){return false;} function kindFor(){return 'line';}` → append ` function figureFields(b){return b;} function figRung(){return null;}` inside the same string line.
- `tests/test_viewer_async_visits.py:137`: `function isRegion(){return false;}function kindFor(){return 'line';}` → `function isRegion(){return false;}function kindFor(){return 'line';}function figureFields(b){return b;}function figRung(){return null;}`.
- `tests/test_viewer_async_visits.py:394` and `:430` (replace all): `function lvOf(){return null;}function isRegion(){return false;}` → `function lvOf(){return null;}function isRegion(){return false;}function figureFields(b){return b;}function repickEl(){return null;}`.

- [ ] **Step 5: Run the tests again**

Run: `uv run pytest -q tests/test_viewer.py tests/test_viewer_async_visits.py tests/test_viewer_repick_race.py tests/test_viewer_source.py tests/test_i18n.py tests/test_viewer_browser.py -k "FrontendFigure or FrontendSaveWhilePicking or FrontendDocs or VisitLocal or Repick or ClosedSets or DeadAndDoubled or MessageTable or FigureDocuments"`
Expected: `0 failed` (the repick-race and async-visit harnesses build `REPICK.from` and edit cards without `region`/`pinEl`, which reads as a line pin with no element — their behaviour is unchanged).

- [ ] **Step 6: Update viewer.md**

In the `**그림 요소.**` bullet list (§패널 정리), after `- 한 줄 버튼으로 줄을 직접 맞춰도 고른 요소와 상자는 그대로다.` add:
```markdown
- 저장과 위치 다시 잡기는 고른 요소를 쪽 위 상자(`frac`)까지 `el`로 보내고, 그 상자를 핀의 `frac`으로도 보낸다. 그래서 지금 빌드의 지도 없이 그리는 마크도 사람이 본 상자 자리에 온다. 요소 칸이면 범위 종류도 그 요소의 것(`el:<부품>`, 뿌리는 `figure`)이다. 이 이름 규칙은 서버의 `figmap.element_kind`와 같고, [`tests/test_viewer.py`](../../tests/test_viewer.py)가 같은 요소로 둘을 대조한다. 위치 다시 잡기 배너의 '새 위치' 상자도 새 요소에 맞춰진다.
- 위치 다시 잡기는 늘 새 위치 전체를 보낸다. 새 자리에 요소가 있으면 그 요소를, 없으면 `el` 없이 보내고, 그러면 서버가 핀의 `el`을 지운다(`el`은 위치 필드다). 서버는 줄 핀을 영역 핀으로, 영역 핀을 줄 핀으로 바꾸지 않는다. 그래서 모양이 다른 후보(줄 핀인데 지도를 못 읽었거나 코드 없는 요소가 답한 자리, 또는 그 반대)는 [이 위치로 바꾸기]를 내놓지 않고, 배너가 이유를 말하며 다시 고르기를 기다린다.
- 편집 카드의 범위 사다리는 원문 줄 단계(`지금 범위`)뿐이다. 그림 문서 파일에는 `/api/snippet`이 요소 단계를 주지 않는다. 칸만 누르고 저장하면 아무것도 보내지 않는다. 한 줄 버튼으로 줄을 바꾸면 범위 종류가 `lines`가 되고, 핀의 `el`은 그대로 남는다(범위 고치기는 위치 바꾸기가 아니다).
```

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix tests/test_viewer.py tests/test_viewer_async_visits.py tests/test_viewer_browser.py && uv run ruff format tests/test_viewer.py tests/test_viewer_async_visits.py tests/test_viewer_browser.py
git add src/limn/viewer tests/test_viewer.py tests/test_viewer_async_visits.py tests/test_viewer_browser.py docs/handbook/viewer.md
git commit -s -m "feat(viewer): save and re-place figure pins with their element" -m "A figure pin sends its element as el with its box, the same box as the pin's frac, and the element's range kind, which matches figmap.element_kind in a parity test. The re-place banner snaps its box to the new element and does not offer a candidate of the other shape; a figure pin's edit card sends a range only when its lines change."
{ printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
```

---

### Task 6: Marks follow the element; a lost element says `요소 잃음` (closed table `EL_SYNC`)

**Files:**
- Modify: `src/limn/viewer/js/core.js` (after `DOC_KIND`; `T` after `stale:`)
- Modify: `src/limn/viewer/js/figure.js` (append)
- Modify: `src/limn/viewer/js/list.js:108-118` (`marks`), `:161` (`jumpPin`)
- Modify: `src/limn/viewer/js/cards.js:3-5, 27, 38, 40, 52-55` (`card`)
- Modify: `src/limn/viewer/js/polling.js:97-98` (`diffToast`)
- Modify: `src/limn/ui_en.json`
- Modify: `tests/test_viewer_source.py` (`SERVER_SETS`), `tests/test_viewer.py` (`FrontendFigure`; card harnesses at 1072 and 2889), `tests/test_viewer_browser.py` (`FigureDocuments`)
- Modify: `docs/handbook/viewer.md` (§닫힌 값 표, §조작 한눈에, §상태 표현)

**Interfaces:**
- Consumes: pin payload `mark`, `mark_page`, `el_sync` (index §Read-time fields); `isFrac` (Task 3); `saved_cell_pin` (Task 5); `helpers_figure.viewer_rerender`, `BUILD2`.
- Produces: `const EL_SYNC=Object.freeze({OK:'ok',MOVED:'moved',LOST:'lost'})`; `T.ellost`; (figure.js) `hasMark(p) -> boolean`, `pinPlace(p) -> {page, frac}`, `elLost(p) -> boolean`, `elLostTag(p) -> string`; browser helper `rerender_and_refresh(page, **cell)`.

- [ ] **Step 1: Write the failing node and wiring tests**

`tests/test_viewer_source.py`: `from limn import access, build, documents, events, figmap, scope`, and in `SERVER_SETS` after `"DOC_KIND"`:
```python
    "EL_SYNC": lambda: set(get_args(figmap.ElSync)),
```

Add to `FrontendFigure`:

```python
    def test_a_figure_pins_mark_goes_to_its_element_and_otherwise_where_it_was_pinned(self):
        """pinPlace uses the server's mark on mark_page when both are well formed, else the pin's page and frac; elLost
        is true only for el_sync 'lost'."""
        self.node()
        js = "\n".join(
            [extract_js_fn(n) for n in ("isFrac", "hasMark", "pinPlace", "elLost")]
            + [
                r"""
            const P=[{page:1,frac:[0.1,0.1,0.1,0.1],mark:[0.55,0.2,0.07,0.12],mark_page:2,el_sync:'moved'},
                     {page:1,frac:[0.1,0.1,0.1,0.1],el_sync:'lost'},
                     {page:3,frac:[0.2,0.2,0.2,0.2]},
                     {page:1,frac:[0.1,0.1,0.1,0.1],mark:[0.5,0.5],mark_page:1},
                     {page:1,frac:[0.1,0.1,0.1,0.1],mark:[0.5,0.5,0.1,0.1],mark_page:0}];
            console.log(JSON.stringify(P.map(p=>[pinPlace(p),elLost(p)])));"""
            ]
        )
        pinned = {"page": 1, "frac": [0.1, 0.1, 0.1, 0.1]}
        self.assertEqual(
            json.loads(run_node(js)),
            [
                [{"page": 2, "frac": [0.55, 0.2, 0.07, 0.12]}, False],
                [pinned, True],
                [{"page": 3, "frac": [0.2, 0.2, 0.2, 0.2]}, False],
                [pinned, False],
                [pinned, False],
            ],
        )

    def test_a_lost_element_badge_reads_element_lost_in_both_languages(self):
        """The lost-element badge is the lost-line warning look with the text '요소 잃음' ('Element lost'); a moved or
        plain pin has none."""
        self.node()
        for lang, word in (("ko", "요소 잃음"), ("en", "Element lost")):
            with self.subTest(lang=lang):
                js = "\n".join(
                    [js_i18n(lang), js_esc(), js_icons(), js_tooltips(), extract_js_fn("elLost"), extract_js_fn("elLostTag")]
                    + ["console.log(JSON.stringify([elLostTag({el_sync:'lost'}),elLostTag({el_sync:'moved'}),elLostTag({})]));"]
                )
                tag, moved, plain = json.loads(run_node(js))
                self.assertIn(word, tag)
                self.assertIn('class="badge badge-warning"', tag)
                self.assertIn("ic-triangle-alert", tag)
                self.assertEqual((moved, plain), ("", ""))

    def test_a_pin_that_loses_its_element_is_announced_once(self):
        """The list refresh announces '#N 요소를 잃었습니다' when an open pin's element becomes lost, not when it already
        was, and not for a move."""
        self.node()
        js = "\n".join(
            [
                r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(m,k){TOASTS.push([m,k]);} function restorePin(){}
            const MY_ACTIONS=new Map();""",
                extract_js_fn("markMine"),
                extract_js_fn("consumeMine"),
                extract_js_fn("pinState"),
                extract_js_fn("diffToast"),
                r"""
            diffToast([{id:1,el_sync:'ok'},{id:2,el_sync:'lost'},{id:3}],[{id:1,el_sync:'lost'},{id:2,el_sync:'lost'},{id:3,el_sync:'moved'}],[]);
            console.log(JSON.stringify(TOASTS));""",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [["#1 요소를 잃었습니다", "warn"]])

    def test_marks_and_cards_place_a_figure_pin_where_its_element_is(self):
        """marks() and the card's page link use pinPlace; a placed mark is not dashed; a lost element marks the card and
        mark like a lost line; [보기] falls back to the mark's page."""
        m = extract_js_fn("marks")
        self.assertIn("const at=pinPlace(p),el=document.getElementById('p'+at.page);", m)
        self.assertIn("const est=isEstimated(p)&&!hasMark(p),lost=p.stale||elLost(p);", m)
        c = extract_js_fn("card")
        self.assertEqual(c.count("{page:pinPlace(p).page}"), 2)
        self.assertEqual(c.count("p.stale||elLost(p)?CARD_DOT.LOST"), 2)
        self.assertIn("const lostEl=elLostTag(p); if(lostEl)tags.push(lostEl);", c)
        self.assertIn("document.getElementById('p'+pinPlace(p).page)", extract_js_fn("jumpPin"))
        self.assertIn("p.el_sync===EL_SYNC.LOST", extract_js_fn("diffToast"))
```

- [ ] **Step 2: Write the failing browser tests**

Add to `FigureDocuments`:

```python
    def rerender_and_refresh(self, page, **july):
        """The figure is rendered again into build BUILD2 (helpers_figure.viewer_rerender with july/july_page) and the
        viewer takes it the way its poll does (refreshDoc: pages, then pins)."""
        helpers_figure.viewer_rerender(self.fig, **july)
        page.evaluate("async()=>await refreshDoc()")
        page.wait_for_function("b=>META.pages_build===b", arg=helpers_figure.BUILD2, timeout=8000)
        settle(page)

    def test_a_saved_pins_mark_follows_its_element_after_a_re_render(self):
        """The mark starts on the cell; after a re-render moves the cell it is drawn at the cell's new box, solid (a
        placed element is no estimate)."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        mark = '.mark[data-pin="%d"]' % pid
        self.assert_box(page, mark, 1, helpers_figure.JULY)
        moved = (0.30, 0.18, 0.07, 0.12)  # clear of the August cell
        self.rerender_and_refresh(page, july=moved)
        self.assert_box(page, mark, 1, moved)
        self.assertEqual(page.evaluate("s=>[...document.querySelector(s).classList]", mark), ["mark"])

    def test_a_mark_whose_element_moved_to_page_2_is_drawn_and_counted_there(self):
        """The cell moves to page 2: its mark is drawn there, the card's page link says 2쪽, and [보기] brings the mark
        on screen."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        there = (0.30, 0.40, 0.10, 0.05)
        self.rerender_and_refresh(page, july=there, july_page=2)
        mark, card = '.mark[data-pin="%d"]' % pid, '.pin[data-id="%d"]' % pid
        self.assert_box(page, mark, 2, there)
        self.assertEqual(self.text(page, card + " .pg-link"), "2쪽")
        page.click(card + " .pg-link")
        settle(page)
        self.assertTrue(
            page.evaluate(
                """s=>{const m=document.querySelector(s).getBoundingClientRect(),l=document.getElementById('left').getBoundingClientRect();
                return m.top>=l.top&&m.bottom<=l.bottom;}""",
                mark,
            )
        )

    def test_a_lost_element_shows_element_lost_like_a_lost_line(self):
        """The re-render drops the cell: the card gets '요소 잃음', the lost dot and the warning border, the mark stays
        where the pin was placed in the warning colour, and one toast says so."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        self.rerender_and_refresh(page, july=None)
        card, mark = '.pin[data-id="%d"]' % pid, '.mark[data-pin="%d"]' % pid
        self.assertIn("요소 잃음", self.text(page, card + " .tags"))
        self.assertEqual(page.evaluate("s=>[...document.querySelector(s).classList]", card + " .st-dot"), ["st-dot", "lost"])
        self.assertTrue(page.evaluate("s=>document.querySelector(s).classList.contains('st')", card))
        self.assertTrue(page.evaluate("s=>document.querySelector(s).classList.contains('st')", mark))
        self.assert_box(page, mark, 1, helpers_figure.JULY)
        self.assertEqual(page.locator("#toasts .toast").filter(has_text="#%d 요소를 잃었습니다" % pid).count(), 1)
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest -q tests/test_viewer_source.py tests/test_viewer.py tests/test_viewer_browser.py -k "ClosedSets or FrontendFigure or FigureDocuments"`
Expected: `ClosedSets` fails on `EL_SYNC`; `LookupError: no top-level function hasMark` / `elLostTag`; the toast test gets `[]`; the wiring test fails; the browser tests fail — the mark stays at `CELL` after the move (`0.47` vs `0.55`), stays on page 1 (`is not on page 2`), and the card has no `요소 잃음`.

- [ ] **Step 4: Implement**

`src/limn/viewer/js/core.js`, after the `DOC_KIND` line:
```js
const EL_SYNC=Object.freeze({OK:'ok',MOVED:'moved',LOST:'lost'});   // where a figure pin's element is in the current build: a pin's `el_sync` (figmap.ElSync)
```
In `T`, after the `stale:` entry:
```js
  ellost:'그림을 다시 그린 뒤 지도에서 이 요소를 찾지 못했습니다(요소 id가 바뀌었거나 지워짐). 표시는 핀을 찍은 때 자리에 그립니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
```

Append to `src/limn/viewer/js/figure.js`:
```js
// Whether the server found this figure pin's element in the current build: the read-time `mark` box on `mark_page`.
function hasMark(p){return isFrac(p.mark)&&Number.isInteger(p.mark_page)&&p.mark_page>=1;}
// Where a pin's mark goes (docs/handbook/viewer.md §상태 표현): its element's box in the current build when the server found
// it, else the page and box the pin was placed on - a manuscript pin, a view-only pin, a figure pin whose element was
// lost or whose map is unreadable.
function pinPlace(p){return hasMark(p)?{page:p.mark_page,frac:p.mark}:{page:p.page,frac:p.frac};}
// Whether a figure pin's element is gone from the current build's map (`el_sync` lost) - shown like a lost line.
function elLost(p){return !!p&&p.el_sync===EL_SYNC.LOST;}
// The card badge of a lost element ('요소 잃음', the warning look of '위치 잃음'), or ''.
function elLostTag(p){return elLost(p)?'<span class="badge badge-warning" data-tip="'+esc(tr(T.ellost))+'">'+ic('triangle-alert')+esc(tr('요소 잃음'))+'</span>':'';}
```

`src/limn/viewer/js/list.js`, replace lines 111-116 (from `  PINS.concat(REVIEW_ALL…` to the `const tip=…` line) with:
```js
  // A figure pin is drawn where the server found its element in this build (see pinPlace), and a found element is no estimate.
  PINS.concat(REVIEW_ALL.filter(p=>pdoc(p)===DOC)).forEach(p=>{const at=pinPlace(p),el=document.getElementById('p'+at.page); if(!el||!Array.isArray(at.frac))return;
    const est=isEstimated(p)&&!hasMark(p),lost=p.stale||elLost(p);
    const m=document.createElement('div'); m.className='mark'+(lost?' st':'')+(est?' est':'')+(pinState(p)===PIN_STATE.REVIEW?' rv':''); m.dataset.pin=p.id;
    Object.assign(m.style,{left:at.frac[0]*100+'%',top:at.frac[1]*100+'%',width:at.frac[2]*100+'%',height:at.frac[3]*100+'%'});
    const n=String(p.note||'').replace(/\s+/g,' ').trim();
    const tip='#'+p.id+' · '+(n?(n.length>60?n.slice(0,60)+'…':n):tr('(메모 없음)'))+(est?' '+tr('(PDF가 새로 만들어져 위치는 추정입니다)'):'')+(elLost(p)?' · '+tr('요소 잃음'):'');
```
(the next line, `m.innerHTML=…; el.appendChild(m);});`, stays). In `jumpPin` (line 161): `const el=document.getElementById('p'+p.page);` → `const el=document.getElementById('p'+pinPlace(p).page);`.

`src/limn/viewer/js/cards.js`:
- After line 5 (the `else{const m=/^moved …/…}` statement) add: `  const lostEl=elLostTag(p); if(lostEl)tags.push(lostEl);   // a figure pin whose element the re-rendered map no longer has`
- Line 27: replace `  if(isRegion(p))tags.unshift('<span class="badge" data-tip="보기 전용 PDF의 핀 — 줄 번호 없이 쪽·영역과 영역 글자로 가리킵니다">보기 전용</span>');` with
  ```js
  if(isRegion(p))tags.unshift(p.el?'<span class="badge" data-tip="'+esc(tr(T.elregion))+'">'+esc(tr('코드 없는 요소'))+'</span>':'<span class="badge" data-tip="보기 전용 PDF의 핀 — 줄 번호 없이 쪽·영역과 영역 글자로 가리킵니다">보기 전용</span>');
  ```
- Replace all (lines 38 and 53): `stDot(rv?CARD_DOT.REVIEW:p.stale?CARD_DOT.LOST:` → `stDot(rv?CARD_DOT.REVIEW:p.stale||elLost(p)?CARD_DOT.LOST:`.
- Replace all (lines 40 and 55): `esc(tl('{page}쪽',{page:p.page}))` → `esc(tl('{page}쪽',{page:pinPlace(p).page}))`.
- Line 52: `'<div class="pin card'+(p.stale?' st':'')` → `'<div class="pin card'+(p.stale||elLost(p)?' st':'')`.

`src/limn/viewer/js/polling.js`, after line 98 (`    if(!was.stale&&p.stale){toast(tl('#{id} 위치를 잃었습니다',{id:p.id}),'warn');return;}`) add:
```js
    if(was.el_sync!==EL_SYNC.LOST&&p.el_sync===EL_SYNC.LOST){toast(tl('#{id} 요소를 잃었습니다',{id:p.id}),'warn');return;}   // a re-render lost a figure pin's element
```

Card harnesses in `tests/test_viewer.py` (lines 1072 and 2889 — replace all occurrences of the exact line `                extract_js_fn("card"),`) with:
```python
                extract_js_fn("isFrac"),
                extract_js_fn("hasMark"),
                extract_js_fn("pinPlace"),
                extract_js_fn("elLost"),
                extract_js_fn("elLostTag"),
                extract_js_fn("card"),
```

`src/limn/ui_en.json`:
```bash
uv run python - <<'EOF'
import json
from pathlib import Path

path = Path("src/limn/ui_en.json")
table = json.loads(path.read_text(encoding="utf-8"))
table.update({
    "요소 잃음": "Element lost",
    "#{id} 요소를 잃었습니다": "#{id} lost its element",
    "그림을 다시 그린 뒤 지도에서 이 요소를 찾지 못했습니다(요소 id가 바뀌었거나 지워짐). 표시는 핀을 찍은 때 자리에 그립니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요": "After the figure was redrawn, its map no longer has this element (its id changed or it was removed). The mark stays where the pin was placed. It may already be fixed — check, then mark it done, or use [Edit] → Relocate",
})
path.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
EOF
```

- [ ] **Step 5: Run the tests again**

Run: `uv run pytest -q tests/test_viewer.py tests/test_viewer_source.py tests/test_i18n.py tests/test_viewer_list.py tests/test_viewer_browser.py`
Expected: `0 failed` (the two card harnesses now pull `pinPlace`/`elLost`/`elLostTag`; `diffToast`'s harnesses get `EL_SYNC` from the closed-set prelude).

- [ ] **Step 6: Update viewer.md**

§닫힌 값 표, after the `DOC_KIND` row:
```markdown
| `EL_SYNC` | ok · moved · lost | 그림 핀의 `el_sync`(`figmap.ElSync`) |
```
§조작 한눈에, `카드의 [보기]` row: replace `점선 테두리(\`.est\`)는 좌표가 추정치라는 뜻이다 |` with `점선 테두리(\`.est\`)는 좌표가 추정치라는 뜻이다. 그림 핀의 마크는 서버가 읽을 때 찾은 요소 자리(\`mark\`·\`mark_page\`)에 그리며 점선이 되지 않는다. 요소가 다른 쪽으로 옮겨 가면 마크와 카드의 쪽 표시도 그 쪽이다 |`.
§상태 표현, after the row `| 위치 잃음 | 경고색 점 \`--status-warning\` | \`triangle-alert\` \`위치 잃음\` | 카드, 테두리도 경고색 |` add:
```markdown
| 요소 잃음 | 경고색 점 `--status-warning` | `triangle-alert` `요소 잃음` | 카드, 테두리도 경고색. 그림을 다시 그린 뒤 지도에 핀의 요소가 없다(`el_sync`가 `lost`). 마크는 찍은 때 자리에 경고색으로 남고, 목록이 바뀔 때 `#N 요소를 잃었습니다` 알림이 한 번 뜬다. 요소가 옮겨 간 것(`moved`)은 배지가 없다 |
```

Run: `uv run pytest -q tests/test_handbook_refs.py` — Expected: `passed`.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix tests/test_viewer.py tests/test_viewer_source.py tests/test_viewer_browser.py && uv run ruff format tests/test_viewer.py tests/test_viewer_source.py tests/test_viewer_browser.py
git add src/limn/viewer src/limn/ui_en.json tests/test_viewer.py tests/test_viewer_source.py tests/test_viewer_browser.py docs/handbook/viewer.md
git commit -s -m "feat(viewer): draw figure marks where their element is and flag lost elements" -m "A figure pin's mark uses the read-time mark and mark_page, is never dashed when placed, and the card's page link follows it. el_sync lost shows 요소 잃음 in the lost-line style with one toast; el_sync is a closed table checked against figmap.ElSync."
{ printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
```

---

### Task 7: READMEs, changelog, file map check, full gates

**Files:**
- Modify: `README.md:13`, `README.ko.md:12`, `CHANGELOG.md` (`## Unreleased`)
- Check (no change): `docs/handbook/index.md` (`src/limn/viewer/*` row)

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: user-facing mentions; a green branch.

- [ ] **Step 1: Check what P1a/P1b already wrote**

Run: `grep -n "limnmap\|Figure documents\|그림 문서" README.md README.ko.md CHANGELOG.md`
Expected: no README line (P1a/P1b add none). If a README line exists, replace it with the lines below instead of adding a second. CHANGELOG lines from P1a/P1b stay.

- [ ] **Step 2: READMEs**

`README.md`, after `- Several documents per manuscript (manuscript, response letter, view-only reviewer PDFs) as tabs` add:
```markdown
- Figure documents: a figure set drawn by code (one PDF page per figure plus a `limn-figure-map/1` element map) opens as a tab; a drag names the element and the script lines that drew it, and the pin's mark follows the element when the figure is rendered again
```
`README.ko.md`, after `- 원고 하나에 여러 문서(본문·답변서·보기 전용 리뷰어 PDF)를 탭으로` add:
```markdown
- 그림 문서: 코드로 그린 그림 모음(그림 한 장이 PDF 한 쪽, 요소 지도 `limn-figure-map/1`)을 탭으로 연다. 드래그하면 요소와 그 요소를 그린 스크립트 줄을 찾고, 그림을 다시 렌더해도 핀 표시가 요소를 따라간다
```

- [ ] **Step 3: Changelog**

Under `## Unreleased`, in the `### Added` subsection (insert `### Added` right before `### Security` if P1a/P1b have not created it), add:
```markdown
- **Figure documents in the viewer.** A figure tab is marked `그림` in the documents list and has no [PDF rebuild]. A drag snaps the pending box onto the element the map chose and names it in the location line (`B2 › 달력 › 7월 · B2_calendar.py L88-L95`); the range ladder runs element → part → figure without asking the server again. Saving sends the element as `el` with its box, and that box as the pin's `frac`. A figure pin's mark follows its element across re-renders (`mark`, `mark_page`), a lost element shows `요소 잃음` like a lost line, and the location-uncertain badge says `지도로 찾음`. A long-press on a figure picks the element under the finger.
```

- [ ] **Step 4: File map check**

Run: `grep -n '`src/limn/viewer/\*`' docs/handbook/index.md`
Expected: the one row whose text includes `스크립트 조각 \`js/*.js\`` and `조각 추가(\`parts.txt\`에 줄을 더한다)` — it covers `js/figure.js`; no change.

- [ ] **Step 5: Full gates**

Run the Global Constraints gate block. Expected: pytest `0 failed` (report counts as `docs/handbook/verification.md` §결과를 보고하는 법 asks, e.g. `NNNN passed, NN skipped in NNNs (pytest -n 4)`); `test_instances.sh` all `PASS`; `ruff check` 0 errors; `ruff format --check` ok; `shellcheck` 0 warnings; `mypy` `Success: no issues found`. With `LIMN_TEST_REQUIRE_BROWSER=1 LIMN_TEST_REQUIRE_NODE=1` set (as CI does), no browser or node test may be skipped.
Handbook: if `.handbook/fonts/Pretendard-Regular.otf` is present, `uv run python tools/handbook-publish/publish.py check docs/handbook/index.md` — Expected: exit 0 (`docs/handbook/verification.md` §7).

- [ ] **Step 6: Commit**

```bash
git add README.md README.ko.md CHANGELOG.md
git commit -s -m "docs: mention figure documents in the READMEs and the changelog" -m "One line in each README and the viewer's part of the Unreleased entry."
{ printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
```

---

### Task 8: Real measurement on a sample figure set (verification §5)

**Files:**
- Create (not committed): `/tmp/limn-measure/make_figure_set.py`, `/tmp/limn-measure/measure.py`, screenshots in `/tmp/limn-measure/`
- Modify: `docs/handbook/viewer.md` (§알려진 제약)

**Interfaces:**
- Consumes: the branch after Task 7; Poppler (`pdftoppm`) and Chromium (`$LIMN_CHROMIUM`, system Chrome, or Playwright's).
- Produces: numbers and screenshots for the PR description; the measured range recorded in viewer.md.

- [ ] **Step 1: Write the sample figure set generator**

```bash
mkdir -p /tmp/limn-measure && cat > /tmp/limn-measure/make_figure_set.py <<'EOF'
"""Write a sample figure set for measuring Limn's figure documents (docs/handbook/verification.md §5).

<ms>/figures/out/figures.pdf              two vector pages; every element is a red 1 pt box at a known place (page 1 is 2:1)
<ms>/figures/out/figures.limnmap.json     limn-figure-map/1: the same boxes as page fractions, and the lines that drew them
<ms>/figures/src/*.py, figures/lib/components.py   the script lines the map points at
<ms>/reviewer.pdf                         the same PDF, registered as a view-only document for comparison

Usage: uv run python make_figure_set.py <ms>
"""

import hashlib
import json
import os
import sys
from pathlib import Path

MS = Path(sys.argv[1])
ROOT = MS / "figures"
MONTHS = [
    (f"B2/calendar/m{m:02d}", "B2/calendar", (round(0.06 + 0.88 * (m - 1) / 12, 6), 0.18, round(0.88 / 12, 6), 0.12),
     "MonthCell", f"{m}월", f"M{m:02d}", (10 + 2 * m, 11 + 2 * m), ("lib/components.py", 1, 12))
    for m in range(1, 13)
]
BOXES = [
    (f"B3/{k}", "B3", (0.2, round(0.1 + 0.3 * i, 6), 0.6, 0.18), "Box", k, k.title(), (4 + 4 * i, 6 + 4 * i), None)
    for i, k in enumerate(("draft", "review", "merge"))
]
# (width pt, height pt, figure id, title, script, script lines, elements); an element is
# (id, parent, (x, y, w, h), part, label, text drawn in the PDF or None, (lo, hi), impl or None)
PAGES = [
    (864, 432, "B2", "Deployment calendar", "src/B2_calendar.py", 60,
     [("B2/calendar", "B2", (0.06, 0.18, 0.88, 0.12), "CalendarStrip", "달력", None, (10, 40), None)] + MONTHS),
    (432, 576, "B3", "Review flow", "src/B3_flow.py", 20, BOXES),
]


def content(w, h, title, elements):
    """One page's content stream: every element's box stroked in red, labels and the title in black Helvetica."""
    ops = ["1 0 0 RG 1 w"]
    for _id, _parent, (x, y, bw, bh), *_ in elements:
        ops.append("%.3f %.3f %.3f %.3f re S" % (x * w, h - (y + bh) * h, bw * w, bh * h))
    ops.append("0 g BT /F1 14 Tf %.1f %.1f Td (%s) Tj ET" % (0.06 * w, h - 0.1 * h, title))
    for _id, _parent, (x, y, _bw, bh), _part, _label, text, *_ in elements:
        if text:
            ops.append("BT /F1 8 Tf %.3f %.3f Td (%s) Tj ET" % (x * w + 2, h - (y + bh) * h + 3, text))
    return "\n".join(ops).encode("ascii")


def pdf(pages):
    """A two-page PDF 1.4 with one standard font (Helvetica), objects numbered in page order, and its xref table."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>"]
    for i, (w, h, _fig, title, _script, _n, elements) in enumerate(pages):
        stream = content(w, h, title, elements)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                    b"/Resources << /Font << /F1 7 0 R >> >> >>" % (w, h, 4 + 2 * i))
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def figure_map(pdf_bytes):
    """The limn-figure-map/1 map of PAGES: a root per page, then its elements with their lines (and impl for cells)."""
    pages = []
    for n, (_w, _h, fig, title, script, lines, elements) in enumerate(PAGES, 1):
        els = [{"id": fig, "frac": [0, 0, 1, 1], "src": {"file": script, "lo": 1, "hi": lines}}]
        for eid, parent, frac, part, label, _text, (lo, hi), impl in elements:
            el = {"id": eid, "parent": parent, "frac": list(frac), "part": part, "label": label,
                  "src": {"file": script, "lo": lo, "hi": hi}}
            if impl:
                el["impl"] = {"file": impl[0], "lo": impl[1], "hi": impl[2]}
            els.append(el)
        pages.append({"page": n, "figure": fig, "title": title, "elements": els})
    return {"format": "limn-figure-map/1", "pdf": "figures.pdf",
            "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(), "pages": pages}


def main():
    """Write the scripts, then the PDF, then the map last through a rename (the producer's order)."""
    for folder in ("out", "src", "lib"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    for _w, _h, _fig, _title, script, lines, _els in PAGES:
        (ROOT / script).write_text("".join(f"draw_step({i})\n" for i in range(1, lines + 1)), encoding="utf-8")
    (ROOT / "lib/components.py").write_text("".join(f"component_line_{i} = {i}\n" for i in range(1, 13)), encoding="utf-8")
    data = pdf(PAGES)
    (ROOT / "out/figures.pdf").write_bytes(data)
    (MS / "reviewer.pdf").write_bytes(data)
    tmp = ROOT / "out/figures.limnmap.json.tmp"
    tmp.write_text(json.dumps(figure_map(data), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ROOT / "out/figures.limnmap.json")


main()
EOF
rm -rf /tmp/limn-fig-measure && mkdir -p /tmp/limn-fig-measure/ms
uv run python /tmp/limn-measure/make_figure_set.py /tmp/limn-fig-measure/ms
pdfinfo /tmp/limn-fig-measure/ms/figures/out/figures.pdf | grep -E "Pages|Page size"
```
Expected: `Pages:           2` and `Page size:       864 x 432 pts` (page 1 is 2:1; the July cell `B2/calendar/m07` is at `[0.5, 0.18, 0.073333, 0.12]`).

- [ ] **Step 2: Start a local instance on it**

```bash
MS=/tmp/limn-fig-measure/ms
DOCS=(--doc 'fig=Figures:figures::out/figures.limnmap.json' --doc 'rv=Reviewer:reviewer.pdf')
if command -v latexmk >/dev/null; then
  printf '%s\n' '\documentclass{article}' '\begin{document}' 'Figure measurement.' '\end{document}' > "$MS/main.tex"
  DOCS=(--doc 'ms=Manuscript:main.tex' "${DOCS[@]}")
fi
uv run limn serve --manuscript "$MS" "${DOCS[@]}" --state-dir /tmp/limn-fig-measure/state --port 18351 --auth local \
  > /tmp/limn-measure/server.log 2>&1 &
echo $! > /tmp/limn-measure/server.pid
for i in $(seq 1 60); do
  python3 -c "import json,sys,urllib.request as u; d=json.load(u.urlopen('http://127.0.0.1:18351/api/docs')); f=[x for x in d['docs'] if x['key']=='fig']; sys.exit(0 if f and f[0]['n_pages']==2 and f[0]['kind']=='figure' else 1)" 2>/dev/null && echo ready && break
  sleep 1
done
```
Expected: `ready` (the figure import has drawn both pages). If the server refuses to start without a LaTeX document, install TeX (README requirements) and rerun; `tail /tmp/limn-measure/server.log` shows why.

- [ ] **Step 3: Write and run the measurement**

```bash
cat > /tmp/limn-measure/measure.py <<'EOF'
"""Measure a running Limn against the sample figure set (docs/handbook/verification.md §5): the pending box and the
saved pin's mark sit on the element PDF.js draws, at fit width and 300 %, at DPR 1 and 2, on desktop, an unfolded fold
and a phone. Prints one JSON line per case and exits 1 if any check misses; screenshots go to the output folder.

Usage: uv run python measure.py http://127.0.0.1:18351 <figures.limnmap.json> <out dir>
"""

import json
import os
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, MAP, OUT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
CELL_ID = "B2/calendar/m07"
CELL = next(e["frac"] for p in json.loads(MAP.read_text(encoding="utf-8"))["pages"] for e in p["elements"] if e["id"] == CELL_ID)
DESK = {"viewport": {"width": 1400, "height": 850}}
CASES = [  # name, context options, zoom (x fit width), touch input
    ("desktop-dpr1-fit", dict(DESK, device_scale_factor=1), 1, False),
    ("desktop-dpr1-300", dict(DESK, device_scale_factor=1), 3, False),
    ("desktop-dpr2-fit", dict(DESK, device_scale_factor=2), 1, False),
    ("desktop-dpr2-300", dict(DESK, device_scale_factor=2), 3, False),
    ("fold-842", {"viewport": {"width": 842, "height": 758}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}, 1, True),
    ("phone-384", {"viewport": {"width": 384, "height": 832}, "device_scale_factor": 3, "is_mobile": True, "has_touch": True}, 1, True),
]
BOOTED = "typeof LIGHT_TIMER!=='undefined'&&LIGHT_TIMER!==null&&DOC==='fig'"
# Page 1's vector canvas is drawn at the size it is shown (or at the 16.7 MP cap).
DRAWN = """() => {const pg=document.getElementById('p1'), cv=pg&&pg.querySelector('canvas.vb');
  if(!cv||!pg.classList.contains('drawn'))return false;
  const want=Math.min(16777216, pg.clientWidth*pg.clientHeight*devicePixelRatio*devicePixelRatio); return cv.width*cv.height>=want*0.9;}"""
CENTER = """f => {const pg=document.getElementById('p1'), L=document.getElementById('left'), r=pg.getBoundingClientRect(), l=L.getBoundingClientRect();
  L.scrollLeft+=r.left+r.width*(f[0]+f[2]/2)-(l.left+l.width/2); L.scrollTop+=r.top+r.height*(f[1]+f[3]/2)-(l.top+l.height/2);}"""
# Where sel and the canvas sit on page 1 (fractions of the page box), and for each edge of frac how many of 8 points have
# a red canvas pixel within 3 device pixels: the stroke PDF.js drew under the box's edge.
EDGES = """([sel, frac]) => {
  const pg=document.getElementById('p1'), cv=pg.querySelector('canvas.vb'), el=document.querySelector(sel);
  const P=pg.getBoundingClientRect(), L=P.left+pg.clientLeft, T=P.top+pg.clientTop, W=pg.clientWidth, H=pg.clientHeight;
  const rel=r=>[(r.left-L)/W,(r.top-T)/H,r.width/W,r.height/H];
  const ctx=cv.getContext('2d'), cw=cv.width, ch=cv.height;
  const red=(x,y)=>{for(let dx=-3;dx<=3;dx++)for(let dy=-3;dy<=3;dy++){const px=Math.round(x)+dx,py=Math.round(y)+dy;
      if(px<0||py<0||px>=cw||py>=ch)continue; const d=ctx.getImageData(px,py,1,1).data; if(d[0]-d[1]>60&&d[0]-d[2]>60)return 1;}
    return 0;};
  const x=frac[0]*cw, y=frac[1]*ch, w=frac[2]*cw, h=frac[3]*ch, n=8, hits={left:0,right:0,top:0,bottom:0};
  for(let k=1;k<=n;k++){const t=k/(n+1); hits.left+=red(x,y+t*h); hits.right+=red(x+w,y+t*h); hits.top+=red(x+t*w,y); hits.bottom+=red(x+t*w,y+h);}
  return {box:rel(el.getBoundingClientRect()),canvas:rel(cv.getBoundingClientRect()),page:[W,H],hits,n,backing:[cw,ch],dpr:devicePixelRatio};}"""


def ok(r):
    """The box on the cell and the canvas on the page within one CSS pixel, and at least 6 of 8 red points per edge."""
    W, H = r["page"]
    within = lambda got, want: all(abs(a - b) <= 1.0 / s for a, b, s in zip(got, want, (W, H, W, H)))
    return within(r["box"], CELL) and within(r["canvas"], (0, 0, 1, 1)) and all(v >= r["n"] - 2 for v in r["hits"].values())


def run(browser, name, ctx_args, zoom, touch):
    """One case: open the figure, zoom, pick the July cell (drag or long-press), measure the box, save, measure the mark."""
    ctx = browser.new_context(**ctx_args)
    page = ctx.new_page()
    page.goto(BASE + "/?lang=ko#doc=fig")
    page.wait_for_function(BOOTED, timeout=30000)
    page.wait_for_function(DRAWN, timeout=30000)
    if zoom != 1:
        page.evaluate("z=>zoomTo(fitWidth()*z)", zoom)
    page.evaluate(CENTER, CELL)
    page.wait_for_function(DRAWN, timeout=30000)
    b = page.locator("#p1").bounding_box()
    cx, cy = b["x"] + b["width"] * (CELL[0] + CELL[2] / 2), b["y"] + b["height"] * (CELL[1] + CELL[3] / 2)
    if touch:
        cdp = ctx.new_cdp_session(page)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": cx, "y": cy, "id": 0}]})
        page.wait_for_function("LP===null&&LP_PICKED!==null", timeout=8000)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    else:
        w, h = b["width"] * CELL[2] * 0.4, b["height"] * CELL[3] * 0.4
        page.mouse.move(cx - w / 2, cy - h / 2)
        page.mouse.down()
        page.mouse.move(cx + w / 2, cy + h / 2, steps=5)
        page.mouse.up()
    page.wait_for_function("id=>COMPOSE.current&&!COMPOSE.picking&&COMPOSE.current.elSel&&COMPOSE.current.elSel.id===id",
                           arg=CELL_ID, timeout=15000)
    page.wait_for_function(DRAWN, timeout=30000)
    pick = page.evaluate(EDGES, ["#doc .sel", CELL])
    page.screenshot(path=str(OUT / (name + "-pick.png")))
    note = "measure " + name
    page.fill("#note", note)
    page.click("#btn-save")
    page.wait_for_function("n=>PINS.some(p=>p.note===n)", arg=note, timeout=15000)
    pid = page.evaluate("n=>PINS.find(p=>p.note===n).id", note)
    if touch:
        page.evaluate("setSide(false)")
    page.evaluate(CENTER, CELL)
    page.wait_for_function(DRAWN, timeout=30000)
    mark = page.evaluate(EDGES, ['.mark[data-pin="%d"]' % pid, CELL])
    page.screenshot(path=str(OUT / (name + "-mark.png")))
    ctx.close()
    return {"case": name, "pick": pick, "mark": mark, "ok": ok(pick) and ok(mark)}


def chrome(browser):
    """The figure and view-only tabs hide [PDF 재빌드]; screenshots of the desktop tool bar and the phone documents sheet."""
    ctx = browser.new_context(**DESK)
    page = ctx.new_page()
    page.goto(BASE + "/?lang=ko#doc=fig")
    page.wait_for_function(BOOTED, timeout=30000)
    shown = {"fig": page.locator("#btn-rebuild").is_visible()}
    page.locator("#bar1").screenshot(path=str(OUT / "desktop-toolbar-fig.png"))
    page.evaluate("async()=>await switchDoc('rv')")
    page.wait_for_function("DOC==='rv'", timeout=15000)
    shown["rv"] = page.locator("#btn-rebuild").is_visible()
    ctx.close()
    ctx = browser.new_context(viewport={"width": 384, "height": 832}, device_scale_factor=3, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.goto(BASE + "/?lang=ko#doc=fig")
    page.wait_for_function(BOOTED, timeout=30000)
    page.evaluate("openDocsMenu()")
    page.wait_for_selector("#docs-menu[open] .dm-item", timeout=15000)
    page.screenshot(path=str(OUT / "phone-documents-sheet.png"))
    ctx.close()
    return shown


with sync_playwright() as pw:
    exe = os.environ.get("LIMN_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
    browser = pw.chromium.launch(executable_path=exe or None, args=["--no-sandbox"])
    results = [run(browser, *c) for c in CASES]
    rebuild = chrome(browser)
    browser.close()
for r in results:
    print(json.dumps({"case": r["case"], "ok": r["ok"], "pick_box": [round(v, 4) for v in r["pick"]["box"]],
                      "pick_hits": r["pick"]["hits"], "mark_hits": r["mark"]["hits"], "backing": r["pick"]["backing"],
                      "dpr": r["pick"]["dpr"]}))
print(json.dumps({"rebuild_visible": rebuild}))
sys.exit(0 if all(r["ok"] for r in results) and not any(rebuild.values()) else 1)
EOF
uv run python /tmp/limn-measure/measure.py http://127.0.0.1:18351 /tmp/limn-fig-measure/ms/figures/out/figures.limnmap.json /tmp/limn-measure
echo "exit $?"
```
Expected: six lines with `"ok": true`, each `pick_hits`/`mark_hits` edge at `6`–`8` of 8, `pick_box` ≈ `[0.5, 0.18, 0.0733, 0.12]`; then `{"rebuild_visible": {"fig": false, "rv": false}}` and `exit 0`.

- [ ] **Step 4: Look at the screenshots**

Open `/tmp/limn-measure/desktop-dpr1-fit-pick.png`, `desktop-dpr1-300-pick.png`, `desktop-dpr2-300-mark.png`, `phone-384-pick.png`, `phone-384-mark.png`, `desktop-toolbar-fig.png` and `phone-documents-sheet.png` (an image viewer or the agent's Read tool). Check by eye: the dashed '새 핀' box lies on the red M07 box at 100 % and 300 %, the green mark covers it after saving, the location line reads `B2 › 달력 › 7월 · B2_calendar.py L24-L25`, the tool bar has no [PDF 재빌드], the phone sheet shows `그림` on Figures and `PDF` on Reviewer. Attach the screenshots and paste the JSON lines into the PR description.

- [ ] **Step 5: Stop the instance (by its PID, not its port)**

```bash
kill "$(cat /tmp/limn-measure/server.pid)" && echo stopped
```
Expected: `stopped`.

- [ ] **Step 6: Record the measured range in viewer.md**

§알려진 제약, in the list under `**실기기에서 확인하지 않는 것.**`, add after the bullet that starts `- 벡터 렌더링과 PDF 영역 전용 확대는`:
```markdown
- 그림 요소 상자와 PDF.js가 그린 요소의 겹침은 표본 그림 세트로 헤드리스 크롬(데스크톱·펼친 폴드·휴대폰, 폭 맞춤·300%, DPR 1·2·3)에서만 잰다. 사파리와 실기기에서는 재지 않는다.
```
Run: `uv run pytest -q tests/test_handbook_refs.py` — Expected: `passed`.

- [ ] **Step 7: Commit**

```bash
git add docs/handbook/viewer.md
git commit -s -m "docs(viewer): record where the figure box alignment is measured" -m "Measured on a sample figure set in headless Chrome at fit width and 300 percent, DPR 1 to 3; numbers and screenshots are in the PR."
{ printf '%s\n' "$(git log -1 --format=%B)"; echo 'I agree to the Limn CLA (CLA.md).'; } | git commit --amend -F -
```

---

## Self-Review

**1. Spec and brief coverage.**

| Requirement | Task |
| --- | --- |
| Figure tab marker `그림` (doc-tabs, narrow sheet list) | 2 |
| Rebuild UI only for `kind == "tex"`; view-only PDF identical (button hidden, `PDF` mark, redraw toast) | 2 |
| Element outline over the page from `el` + per-rung `frac`; Contract issue for `frac` | 0 (C1), 3 |
| Location line `path › … · file lines`, path labels from rungs | 3 |
| Ladder rung labels from `label`/`part`, client-side rung switch | 3 |
| COMPOSE ownership (captureVisit/currentVisit, PICKSEQ) respected | 3 (no new async; in-flight guard + mutation check) |
| Save and repick send `el` (with `el.frac`, as the index's record keeps it) | 5 |
| `el` is a location field (a `loc` without it drops it); no line↔region change by `/edit` | 5 (`applyRepick` builds a whole `loc`; `bannerCompare` drops a candidate of the other shape) |
| Edit card with the snippet route's `raw`/`lines` rungs (C3) | 5 (tooltip fallback, `pinEl`, browser test against that answer) |
| Marks at `mark`/`mark_page`, else `frac`/`page`; `lost` → lost style + `요소 잃음`; `moved` no badge; no `.est` when placed | 6 |
| Badge method `지도` for `via: "map"` | 1 |
| Strings in `ui_en.json`, parity (`test_i18n`) | 1, 2, 3, 6 (+ tooltip coverage test) |
| Frontend* guards per rule | 1–6 (`FrontendFigure`, `FrontendDocs`, `ClosedSets`) |
| Browser: figure tab no rebuild | 2 |
| Browser: pick shows outline and location line | 3 |
| Browser: switching rungs changes the outline | 3 |
| Browser: saved mark follows `mark` after re-render | 6 |
| Browser: lost element shows `요소 잃음` | 6 |
| viewer.md (tab, composer, marks, lost, closed tables); index.md file map | 1–6, 8; 7 (checked, no change) |
| README en/ko | 7 |
| Real measurement (desktop/narrow, 100 %/300 %) | 8 |
| Spec §뷰어: "요소를 찾은 핀은 점선(추정)이 되지 않는다" | 6 |
| Spec §사용 흐름 3: "결정 단계는 원고 핀과 같다" (no new confirm) | 3 (snapped box is the preview) |

**2. Placeholder scan.** Every code step shows the code; every run step names the command and the expected result. The only open counts are the full-suite totals in Task 7, which the step tells how to report.

**3. Type and name consistency.** `isFrac`, `elName`, `elPathText`, `rungTip`, `snapBox`, `renderElement(o, box)` (Task 3) → used by Tasks 5–6; `elSel` set in `pick`/`useLevel` (Task 3) → read by `figureFields(body, d.elSel, …)` (Task 5); `repickEl(c)` used by `bannerCompare` and `applyRepick` (Task 5); `hasMark`, `pinPlace`, `elLost`, `elLostTag` (Task 6) → `marks`, `card`, `jumpPin`; `EL_SYNC.LOST` inline in `diffToast`. Tables `VIA` (1), `DOC_KIND` (2), `EL_SYNC` (6) each join `SERVER_SETS` in the same task. `T.map` (1), `T.el`/`T.fig`/`T.elregion` (3), `T.shape` (5), `T.ellost` (6). `REPICK.from.region` and `EDITOR.current.pinEl` (5). `FIGMAP_NAME` comes from `limn.build` everywhere. Browser helpers: `open_fig`, `text` (2); `BOX`, `assert_box`, `drag`, `touch`, `on_page` (3); `assert_frac`, `saved_cell_pin` (5); `rerender_and_refresh` (6). Fixture names: P1b's `figure_doc`, `b2_map`, `write_build`, `JULY`, `BUILD1`, `BUILD2` are reused as they are; the appended `FIG`, `ROOT_ID`, `STRIP_ID`, `CELL_ID`, `STRIP_FRAC`, `CELL_DRAG`, `STRIP_DRAG`, `WIDE_PX`, `TALL_PX`, `viewer_map`, `viewer_build`, `viewer_docs`, `viewer_rerender` clash with none of P1b's (`PAGE_PT`, `AUGUST`, `*_BOX`, `SCRIPT`, `png_header`, `script_lines`, `SAVE_LINE`, `pin_from_pick`).

**4. Review Focus.** All five lines have a test in the owning task (Tasks 3, 4, 6) and the measurement in Task 8 covers the drawn-stroke half of line 1. Harnesses that pull changed functions (`quickPick`, `card`, `savePin`, `applyRepick`) are updated in the task that changes them, so every task ends green.
