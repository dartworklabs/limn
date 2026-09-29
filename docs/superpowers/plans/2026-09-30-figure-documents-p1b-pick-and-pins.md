# Figure Documents P1b — Map Pick and Element Pins Implementation Plan

<!-- Code blocks here are transcribed into the repository and formatted there; ruff leaves them as written. -->
<!-- fmt: off -->

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A drag on a figure document is traced through its build's element map to the element and the lines of code that drew it, saved as a line pin with an optional `el`, followed across re-renders at read time, and presented to agents in `pins.md` and SKILL.

**Architecture:** The rules are pure: `limn/figmap.py` gains the pick, ladder and follow functions, and a new `limn/pins/element.py` owns the shape of a pin's `el`. The figure branch of `POST /api/pick` lives in `features/pins/location/figure.py`. It receives the per-build map through a callable that the composition root injects (`PickContext.figure_map`), backed by a per-run `BuildMapCache` in `limn/build.py` (next to P1a's `load_build_map`), and it reads only the chosen element's script through the checked-file helpers. `pins/view.py` computes the read-time fields `mark`, `mark_page` and `el_sync` from the current build's map, which it receives per document. Nothing is written outside `PinStore.transact()`, and a render never writes a pin.

**Tech Stack:** Python 3.10+ standard library at runtime; pytest, pytest-xdist, Hypothesis, Ruff, mypy (dev). The only viewer file touched is the i18n warning table.

**Spec:** [`docs/superpowers/specs/2026-09-30-figure-documents-design.md`](../specs/2026-09-30-figure-documents-design.md). **Index and shared contract:** [`2026-09-30-figure-documents.md`](2026-09-30-figure-documents.md). **Decisions:** ADR-0011.

Existing code is cited at `main` `5d1c4b6`, the base of this branch. P0 and P1a move lines, so find each site by its symbol.

---

## Contract issues

The index's §Shared contract is binding. The facts below conflicted with its first version or left a gap. Each item gives the proposal this plan implements. **All nine are accepted and already folded into the index** (§Shared contract and §Contract amendments at handover). Task 11, Step 7 only checks the index. Item 5 waits for the owner's confirmation, and the Done list has a line for it. Nothing is renamed.

1. **`el` needs the element's box: `el.frac` (additive, optional).** The index's `el` is `{id, path, label?, part?, impl?}`. Two consumers need the element's box at pick time, and nothing in the pick answer carries it:
   - P1c must draw the element outline, per rung.
   - `follow_element(m, el_id, page_then, frac_then)` needs `frac_then`. The pin's `frac` is the viewer's *drag* box, so comparing it with the element box answers `moved` even on the same build, and `ok` would never occur. Reading the element's box from the pin's own build map instead fails after two re-renders, because only the current and previous page folders are kept.

   **Proposal:** `el` gains optional `frac` (`[x, y, w, h]`, the element's box on the build the pick was traced in). The pick writes it on the top-level `el` and on every rung's `el`, and the record keeps it. `fits_record` checks that it is four numbers when present. The read-time fields use `el.frac` as `frac_then` and fall back to the pin's `frac` when it is absent (an agent's pin), which can never be `ok`. Key order: `id, path, label?, part?, impl?, frac?`.
2. **Step 1 of the pick rule excludes the root.** The root's `frac` is the whole page, so its cover is always 1. If the root competed in "the deepest element with cover ≥ COVER_MIN", steps 2 and 3 could never run, and the spec's step 4 ("그것도 없으면 … 뿌리") would be dead. **Proposal:** steps 1–2 range over the page's non-root elements, and the root is the last resort. The index sentence becomes "the deepest non-root element with cover ≥ COVER_MIN".
3. **`default_level` is `"fig"` when the drag chose the root.** A root pick's ladder is `(root,)` and its only scope is `"fig"`, so a constant `"el"` would name no rung (`lvOf(d, "el")` finds nothing). **Proposal:** `default_level` is the first rung's level: `"el"`, or `"fig"` for the whole figure.
4. **Figure rungs.** Three clarifications to "one rung per ladder element … merge as today":
   - Every rung lies in the chosen element's `src.file`. Today every rung shares the pick's `file`, and both the viewer (P1b and P1c) and `/edit` assume a rung switch never changes the file. A ladder element drawn in another file is left out, and it still appears in `el.path`.
   - Rungs with the same lines merge into the **inner** rung, and the outer level name goes under `merged`. LaTeX's `add()` keeps the later name. For a figure the inner element is the one the person dragged on, and the top-level `el` must stay that element.
   - Rungs also carry `n` (`hi - lo + 1`), as LaTeX rungs do. The P1b viewer renders `{n}줄` from it.
5. **The `bad_scope` and `bad_via` sentences grow.** api.md §오류 응답 says an `error` sentence never changes. These two sentences are built from the value lists (`"scope 는 %s 중 하나입니다." % "\|".join(SCOPES)`, `"via 는 synctex\|text 입니다."`), which ADR-0011 grows. **Proposal:** the sentences list the grown values, and the `reason` codes stay the same. A fixed old sentence would tell agents that `el` and `map` are refused. `tests/test_web_parse.py:232` pins the old scope sentence and changes with it.
6. **The `pins.md` shared-part path is relative to `--manuscript`.** The index prints `공통 부품: <impl.file>:<lo>-<hi>`, but `impl.file` is relative to `Doc.src`, while the location column is relative to `--manuscript`. Printed as stored, `lib/components.py` would send an agent to the wrong file when the figure folder is `figs/`. **Proposal:** `pins.md` prints `figs/lib/components.py:410-470`, that is the document folder relative to `--manuscript` joined with `impl.file`. The record and the API keep `impl.file` relative to `Doc.src` as the index says.
7. **`element_kind` keeps a pin's `kind` within 80 characters.** `kind` is refused above 80 characters (`bad_kind`), and a map's `part` has no length limit. **Proposal:** `"el:" + part[:77]`.
8. **`element_without_source` also covers unusable source.** The index names two fallbacks. **Proposal:** `element_without_source` covers every case in which the chosen element's lines cannot be given: no `src` (D7), a script that cannot be read inside `Doc.src` (deleted, or a symlink leading out), or a range longer than the script is now (the script changed after the render). Both reasons stay as named.
9. **New rejection code `bad_el` (additive).** A malformed `el` in `POST /api/pin` or an edit's `loc` is answered with `400 bad_el`. The index names no code for this case.

**How this plan reads two index phrases.** Neither reading renames anything. Both are for the coordinator to confirm.
- §Read-time fields says "every pin payload built by `pins/view.py`". This plan reads that as the pin views of `GET /api/pins` and `/api/pins/{id}` (`pin_view`), where `est` already lives. The Trash list (`dropped_payload`) and the `pin` echoed by change requests carry no read-time fields, as they carry no `est` today.
- The figure snippet ladder (the coordinator's decision): `GET /api/snippet?levels=1` on a figure document answers only the `raw` rung (Task 7).

## Assumed state after P0 and P1a

This plan assumes the P0 and P1a names below. **Task 1, Step 1 verifies them.** If P0 or P1a spelled a name differently, substitute that spelling everywhere this plan uses it. The changes are mechanical and leave the semantics as stated.

| Assumed | Meaning |
| --- | --- |
| `Doc.kind: DocKind` with `"figure"`; `Doc.builds_from_source`, `watches_files`, `takes_line_pins`, `shows_revisions`, `view_only` | the index's §Document kinds and capabilities; for `"figure"`, `takes_line_pins` is `False` until Task 7 |
| `DocumentFacts.view_only` (replaces `is_pdf`, `documents.py:278-281` at `5d1c4b6`) and the same name in `web.parse.DocumentFacts` and in the test fake `tests/test_web_parse.py:43` | "region pins only" |
| `Doc.has_element_map` (P1a Contract issue 2: `True` only for `"figure"`) and `Doc.pdf_name` (`figures.limnmap.json` → `figures.pdf`) | branches read capabilities, never `kind` (P0 R3) |
| `resolve.pick` branches `if D.view_only:` to `_pick_region(D, pdir, page, box, size, frac, rtext, ctx.root)` (`resolve.py:148` at `5d1c4b6`; P1a Task 6 adds `root` and names the PDF the build's map names) | figure documents pick as regions after P1a |
| `documents.doc_for_file` skips documents without `takes_line_pins` (`documents.py:209`) | routing |
| `limn/figmap.py`: `Frac`, `SourceRef`, `MapElement`, `MapPage` (`root`, `by_id`, `ancestors`), `FigureMap` (`page`, `find`), `MapRejected`, `parse_map` exactly as the index | pure, no I/O |
| `limn/build.py` (P1a Contract issue 1, not `features/builds/figure.py`): `FIGMAP_NAME = "figmap.json"`, `load_build_map(doc, build) -> FigureMap \| MapRejected \| None` (reads `doc.dir / build / FIGMAP_NAME`, parses with the document folder's source check), `build_figure_pdf` | shared build facts; slices never import each other |
| P1a tests that P1b's flip reverses: `CAPABILITY_TABLE["figure"]` and the figure routing test in `src/limn/features/document_views/test_meta.py`; `test_a_figure_document_takes_no_line_pin` and `test_a_file_only_pin_under_the_figure_folder_goes_to_the_latex_document` in `src/limn/features/pins/location/test_figure_region.py` | Task 7 updates them |

## Global Constraints

- Server runtime stays standard-library only (`dependencies = []`). No SVG rasterising, no external API calls, and no subprocess besides the existing ones. The map pick never runs `pdftotext` or SyncTeX.
- The agent contract (`pins.md`, HTTP API) only grows. The value lists `via` (`map`), `scope`/`levels[].level` (`el`, `el2` … `el8`, `fig`) and pin `kind` (`el:<part>`, `figure`) grow as ADR-0011 (D5 = A) decided. No existing field, path, status or value changes meaning. Existing `pins.md` and API bytes stay the same for states without figure pins, and `tests/data/contract_snapshot.json` must not change. The one exception is the two refusal sentences in §Contract issues 5, whose `reason` codes stay the same.
- Pin files are written only through `PinStore.transact()`. Rendering never writes pins: `mark`, `mark_page` and `el_sync` are read-time fields, and a re-render never changes a pin's `rev`.
- Old state folders are read without migration. A state folder with figure pins stays valid for the previous release: `valid_rec` in v0.3.5 accepts every figure record, and v0.3.5 writes unknown fields back byte for byte.
- Code, comments, docstrings, test names and commit messages are in English. The Handbook is in Korean, present tense, with no dates. `skill/SKILL.md` and `skill/SKILL.ko.md` are edited together, in one commit.
- Use no real e-mails, home paths or host names (`alice@example.com`, `/srv/paper`, `/tmp/limn-test`).
- Coding rules (Handbook ch.11 "지금 적용"):
  - R1: pure decisions, side effects at the edge.
  - R3: parse at the boundary. Inner code knows no HTTP, and rejections are values mapped by one table in `http.py`.
  - R5: no new `C.`/`cur_doc()` references outside `server.py`.
  - R7: a contract docstring on every touched function.
  - R8: precise types.
  - R9: test names state the condition and the expectation, every test has a docstring, and the failing test comes first.
  - R10: negative tests for every boundary change.
  - Tests live with their slice (ADR-0010). One owner per action (ADR-0009): the figure pick lives in `features/pins/location`. Map reading and its per-run cache live in the shared `limn/build.py` (P1a Contract issue 1), and the composition root hands them to the slices.
- Commits use `git commit -s`. Then append the CLA line right after `Signed-off-by:` with this exact pair of commands (every Commit step below uses it):
  ```bash
  git commit -s -m "<subject>" -m "<body>"
  git commit --amend -q -m "$(git log -1 --format=%B)
  I agree to the Limn CLA (CLA.md)."
  ```
- Gates for the PR (Task 11 runs them all):
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

Most likely first. Each line names the test that pins it.

1. **A drag on a figure made against an older build whose map differs** is traced through that build's own map copy, not the current one. The pin keeps that build as `pdf_build`, and the read-time fields then report where the element is now. → Task 6 `test_a_drag_on_an_older_build_is_traced_through_that_builds_map`; Task 8 `test_a_re_render_moves_or_loses_the_mark_without_writing_the_pins`.
2. **An element id removed by a re-render while an editor has the pin open.** `GET /api/pins` shows `el_sync: "lost"` with no `mark`, and `rev` and the stored bytes stay the same, so the editor's save with the `base_rev` it loaded succeeds (no `409` caused by a render). → Task 8 `test_an_editor_holding_the_pin_saves_after_its_element_is_lost`.
3. **A map whose src line range exceeds the script's current length** (the script changed after the render). If the chosen element does not fit, the pick answers the region body with that element and `element_without_source`. An ancestor that does not fit is left out of the ladder. The pick never offers lines the save would refuse. → Task 6 `test_lines_past_the_end_of_the_script_fall_back_or_drop_the_rung`.
4. **Two elements with identical boxes.** A child that fills its parent exactly wins by depth, and equal siblings go by map order. The result is deterministic, including under Hypothesis. → Task 1 `test_equal_boxes_go_to_the_deeper_then_the_earlier_element`.
5. **An agent that creates a pin by curl on a figure document without `el`.** The pin routes by file to the figure document (the deepest root) and is a plain line pin without read-time fields. Its `pins.md` row has no `«label»`, and the figure guidance clause does not appear for it alone. → Task 7 `test_an_agent_curl_without_el_routes_by_file_and_is_a_plain_line_pin`; Task 9 `test_the_figure_clause_needs_an_element_pin`.
6. **A malformed `el` sent by a client** is `400 bad_el`, and nothing is stored. A malformed `el` found in `pins.jsonl` makes that line broken. → Task 7 `test_a_malformed_el_is_refused_and_nothing_is_stored`; Task 2 `test_a_malformed_element_breaks_the_line`.
7. **A map source that is a symlink leading out of the figure folder** is never read, and the pick answers the region. → Task 6 `test_a_script_outside_the_document_folder_is_not_read`.

## State after this plan (P1b, unreleased on `main`)

- The map pick, `el` pins, read-time fields, `pins.md` rows and SKILL are live.
- The viewer is still P1a's. Its composer saves `scope` and `kind: "lines"` (`kindFor`) and no `el`, so pins made in the browser carry no element until P1c. The rebuild button shows on figure documents because `view_only` is now `false`. Clicking it answers `400`. P1c hides the button (index §Viewer).
- The level tooltips (`T[lv.level]`) have no entry for the `el*`/`fig` levels until P1c.

## File Structure

| Path | Change | Responsibility |
| --- | --- | --- |
| `src/limn/figmap.py` | modify | + `COVER_MIN`, `FILL_MIN`, `LADDER_MAX`, `FOLLOW_EPS`, `KIND_PART_MAX`, `ElSync`, `ElementPick`, `pick_element`, `ladder_scopes`, `element_kind`, `ElementFollow`, `follow_element` (pure) |
| `src/limn/pins/element.py` | create | the pin's `el`: `ElementImpl`, `PinElement`, `is_element_record`, `element_of` (pure) |
| `src/limn/pins/record.py` | modify | `fits_record` checks `el` |
| `src/limn/pins/edit.py` | modify | `Scope` gains `el`…`el8`, `fig` |
| `src/limn/mapping.py` | modify | `Via` gains `map`, `VIAS`; `comment_marker`; `is_comment`/`anchor_of` take the marker |
| `src/limn/pins/position.py` | modify | legacy anchor backfill uses the file's marker |
| `src/limn/web/parse.py` | modify | `Via` re-exported from `mapping`; `DocumentFacts.has_element_map` |
| `src/limn/documents.py` | modify | `takes_line_pins` includes `figure`; `DocumentFacts.has_element_map` |
| `src/limn/build.py` | modify | + `MAP_CACHE_MAX`, `BuildMapCache` (next to P1a's `load_build_map`) |
| `src/limn/server.py` | modify | `Runtime.figure_maps`; `ServerApplication.figure_map`, `doc_figure_map`; `PickContext` gets `figure_map` |
| `src/limn/features/pins/location/figure.py` | create | figure branch of the pick: `FigureFallback`, `Rung`, `PickedElement`, `drag_frac`, `pin_element`, `element_rungs`, `read_source`, `pick_figure` |
| `src/limn/features/pins/location/resolve.py` | modify | `PickContext.figure_map`; `PickedRegion.el`, `.fallback`; figure dispatch |
| `src/limn/features/pins/location/service.py` | modify | return type |
| `src/limn/features/pins/location/http.py` | modify | two `PICK_WARNINGS`; `_element_body`, `_rung_level`, `element_warning`; region body `el` and fallback warn |
| `src/limn/viewer/js/i18n.js`, `src/limn/ui_en.json` | modify | the two new warning templates; `reason:bad_el`; `reason:bad_via` text |
| `src/limn/features/pins/editing/location.py` | modify | `parse_el`; `LineLoc.el`, `RegionLoc.el`; via by `VIAS` |
| `src/limn/features/pins/editing/input.py` | modify | whitelist `el`; region-or-line choice on figure docs |
| `src/limn/features/pins/editing/rules.py` | modify | `LOC_FIELDS`/`REGION_PLACE_FIELDS` gain `el`; places validate and freeze `el`; via by `VIAS` |
| `src/limn/features/pins/editing/service.py` | modify | anchors use the file's comment marker |
| `src/limn/pins/view.py` | modify | `element_marks`; `pin_view(..., fmap)`; `pins_payload(..., figure_map)` |
| `src/limn/features/pins/listing/service.py` | modify | `ListingDeps.doc_figure_map`; passes it |
| `src/limn/pins/render.py` | modify | `PinFacts.el_sync`, `.impl_location`; `FIGURE_GUIDANCE`, `element_quote`, `shared_part_md`; rows and guidance |
| `src/limn/features/pins/listing/markdown.py` | modify | `MarkdownDeps.doc_figure_map`; `_element_facts` |
| `tests/helpers_figure.py` | create | figure document fixture (script, components, map, build folders, `pin_from_pick`) |
| `tests/test_figmap_pick.py` | create | pick/ladder/kind/follow examples + Hypothesis |
| `tests/test_pins_element.py` | create | `el` shape, read, write, round trip |
| `tests/test_figure_rollback.py` | create | v0.3.5 reads and rewrites figure records byte for byte |
| `tests/data/pin_records.jsonl` | modify | + 4 figure records |
| `tests/data/contract_snapshot_figure.json` | create | recorded figure flow |
| `tests/test_build.py` | modify | + `BuildMapCacheReads` |
| `src/limn/features/pins/location/test_figure_region.py`, `src/limn/features/document_views/test_meta.py` (P1a's) | modify | the tests P1b's flip reverses (Task 7) |
| `src/limn/features/pins/location/test_figure.py` | create | rungs, bodies, map pick through the feature |
| `src/limn/features/pins/editing/test_figure_pins.py` | create | `el` in create/edit, routing, `bad_el`, snippet |
| `src/limn/features/pins/listing/test_figure_pins.py` | create | read-time fields, `rev`, `pins.md` rows through the server |
| `tests/test_pins_record.py`, `tests/test_pins_lifecycle.py`, `tests/test_web_parse.py`, `tests/test_mapping.py`, `tests/test_pins_position.py`, `tests/test_pins_view.py`, `tests/test_pins_render.py`, `tests/test_contract_snapshot.py`, `src/limn/features/pins/editing/test_rules.py`, `src/limn/features/document_views/test_meta.py` | modify | as each task says |
| `skill/SKILL.md`, `skill/SKILL.ko.md` | modify | figure pin rules; the rebuild rule keys on `kind: "tex"` |
| `docs/handbook/domain.md`, `api.md`, `index.md`, `verification.md`, `CHANGELOG.md` | modify | current state (the index plan is only checked, Task 11 Step 7) |

---

### Task 1: Element pick, ladder and follow rules (`limn/figmap.py`)

**Files:**
- Modify: `src/limn/figmap.py` (append after P1a's code)
- Create: `tests/test_figmap_pick.py`

**Interfaces:**
- Consumes (P1a): `Frac`, `SourceRef(file, lo, hi)`, `MapElement(id, parent, frac, src, impl, part, label)`, `MapPage(page, figure, title, elements)` with `root()`, `by_id(id)`, `ancestors(el)` (nearest first, root last; `()` for the root), `FigureMap(pdf, pdf_sha256, pages)` with `page(n)`, `find(id) -> (MapPage, MapElement) | None`.
- Produces:
  - `COVER_MIN = 0.6`, `FILL_MIN = 0.5`, `LADDER_MAX = 8`, `FOLLOW_EPS = 1e-4`, `KIND_PART_MAX = 77`
  - `ElSync = Literal["ok", "moved", "lost"]`
  - `ElementPick(chosen: MapElement, ladder: tuple[MapElement, ...], score: float)`
  - `pick_element(page: MapPage, drag: Frac) -> ElementPick`
  - `ladder_scopes(ladder: tuple[MapElement, ...]) -> tuple[str, ...]`
  - `element_kind(el: MapElement, root: bool) -> str`
  - `ElementFollow(page: int | None, frac: Frac | None, sync: ElSync)`
  - `follow_element(m: FigureMap, el_id: str, page_then: int, frac_then: Frac) -> ElementFollow`

- [ ] **Step 1: Verify the P0/P1a names this plan relies on**

Run:
```bash
cd <worktree>
grep -n "DocKind\|def takes_line_pins\|def view_only\|def builds_from_source" src/limn/documents.py
grep -n "view_only\|is_pdf" src/limn/web/parse.py src/limn/documents.py src/limn/features/pins/location/resolve.py src/limn/features/pins/location/input.py src/limn/features/pins/editing/input.py tests/test_web_parse.py
grep -n "^class \|^def \|^[A-Z_]* = \|TypeAlias" src/limn/figmap.py
grep -n "^FIGMAP_NAME\|^def load_build_map\|^def build_figure_pdf" src/limn/build.py
grep -n "def has_element_map\|def pdf_name" src/limn/documents.py
grep -n "def _pick_region" -A9 src/limn/features/pins/location/resolve.py
```
Expected:
- `DocKind` includes `"figure"`.
- The five capability properties exist, and `takes_line_pins` returns `self.kind == "tex"`.
- No `is_pdf` is left in those files. `DocumentFacts` and the fake have `view_only`.
- `figmap.py` defines `SourceRef`, `MapElement`, `MapPage`, `FigureMap`, `MapRejected`, `parse_map`. `build.py` defines `FIGMAP_NAME`, `load_build_map` and `build_figure_pdf`. `documents.py` has `has_element_map` and `pdf_name`, and `_pick_region` takes `root` last.

If a name differs, substitute P0/P1a's name wherever this plan uses the assumed one, and note it in the PR.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_figmap_pick.py`:

```python
"""limn.figmap's pick, ladder and follow rules: which element a drag on a figure page points at, the range ladder
above it, and where a pinned element is on a later build's map - pure functions over map values.

The parser half of the module (parse_map) is tested with P1a's tests. Here pages are built from the value types
directly, so each rule is seen without JSON, files or a server. docs/handbook/domain.md §범위 사다리
describes the ladder the rules feed; the Hypothesis properties at the end check them on generated element trees against an oracle
written from that description.

Run: uv run pytest -q tests/test_figmap_pick.py
"""

import unittest

from hypothesis import given, settings, strategies as st

from limn.figmap import (
    COVER_MIN,
    FILL_MIN,
    FOLLOW_EPS,
    LADDER_MAX,
    ElementFollow,
    FigureMap,
    MapElement,
    MapPage,
    SourceRef,
    element_kind,
    follow_element,
    ladder_scopes,
    pick_element,
)

SHA = "0" * 64


def el(eid, parent, frac, src=None, part=None, label=None):
    """A map element of f.py; src given as (lo, hi), or None for an element drawn without code (D7)."""
    return MapElement(eid, parent, tuple(frac), None if src is None else SourceRef("f.py", *src), None, part, label)


ROOT = el("F", None, (0, 0, 1, 1), src=(1, 200))
# A calendar strip with two month cells side by side, like the spec's example map.
CAL = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(80, 97), part="CalendarStrip", label="달력")
JUL = el("F/cal/m07", "F/cal", (0.2, 0.2, 0.2, 0.2), src=(88, 95), part="MonthCell", label="7월")
AUG = el("F/cal/m08", "F/cal", (0.4, 0.2, 0.2, 0.2), part="MonthCell", label="8월")


def page(*elements, n=1):
    """Page n of figure F: the root, then elements in map order."""
    return MapPage(n, "F", None, (ROOT, *elements))


CAL_PAGE = page(CAL, JUL, AUG)


def fmap(*pages):
    """A map of the given pages."""
    return FigureMap("figures.pdf", SHA, tuple(pages))


class Pick(unittest.TestCase):
    """pick_element: the deepest covering element, else the common ancestor of the filled ones, else the root."""

    def test_a_point_picks_the_deepest_element_holding_it(self):
        """A click (a drag without area) is its point: every box holding it covers it fully and the deepest wins."""
        got = pick_element(CAL_PAGE, (0.3, 0.3, 0.0, 0.0))
        self.assertEqual((got.chosen.id, got.score), ("F/cal/m07", 1.0))

    def test_a_small_box_inside_a_leaf_picks_the_leaf(self):
        """A box wholly inside the July cell is covered by the cell, the strip and the root; the cell is deepest."""
        got = pick_element(CAL_PAGE, (0.25, 0.25, 0.05, 0.05))
        self.assertEqual((got.chosen.id, got.score), ("F/cal/m07", 1.0))

    def test_a_box_inside_the_parent_across_siblings_picks_the_parent(self):
        """Each cell covers only half of a box straddling both; the strip holding the whole box covers it."""
        self.assertEqual(pick_element(CAL_PAGE, (0.3, 0.25, 0.2, 0.1)).chosen.id, "F/cal")

    def test_a_box_across_siblings_and_beyond_their_parent_picks_the_common_ancestor(self):
        """The box reaches past the strip (its cover 0.5 < COVER_MIN) but fills both cells: their nearest common
        ancestor is chosen and scored by its own cover."""
        got = pick_element(CAL_PAGE, (0.25, 0.1, 0.3, 0.4))
        self.assertEqual(got.chosen.id, "F/cal")
        self.assertAlmostEqual(got.score, 0.5)

    def test_nothing_qualifying_picks_the_root(self):
        """A box over empty space: no element covers it or is filled by it, so the whole figure is chosen."""
        got = pick_element(CAL_PAGE, (0.8, 0.8, 0.1, 0.1))
        self.assertEqual((got.chosen.id, got.ladder, got.score), ("F", (ROOT,), 1.0))

    def test_equal_boxes_go_to_the_deeper_then_the_earlier_element(self):
        """A child filling its parent exactly wins by depth; two siblings with one box go by map order."""
        parent = el("F/p", "F", (0.1, 0.1, 0.3, 0.3), src=(1, 9))
        child = el("F/p/c", "F/p", (0.1, 0.1, 0.3, 0.3), src=(2, 3))
        self.assertEqual(pick_element(page(parent, child), (0.2, 0.2, 0.05, 0.05)).chosen.id, "F/p/c")
        a = el("F/a", "F", (0.5, 0.5, 0.2, 0.2), src=(4, 5))
        b = el("F/b", "F", (0.5, 0.5, 0.2, 0.2), src=(6, 7))
        self.assertEqual(pick_element(page(a, b), (0.55, 0.55, 0.05, 0.05)).chosen.id, "F/a")
        self.assertEqual(pick_element(page(b, a), (0.55, 0.55, 0.05, 0.05)).chosen.id, "F/b")

    def test_a_smaller_box_wins_among_equally_deep_covering_elements(self):
        """Two overlapping siblings both cover the drag: the smaller one is the more specific answer."""
        big = el("F/big", "F", (0.1, 0.1, 0.6, 0.6))
        small = el("F/small", "F", (0.2, 0.2, 0.2, 0.2))
        self.assertEqual(pick_element(page(big, small), (0.25, 0.25, 0.05, 0.05)).chosen.id, "F/small")

    def test_an_element_without_source_is_picked_by_its_box_alone(self):
        """An element drawn without code (D7) competes like any other; the pick never looks at src."""
        got = pick_element(CAL_PAGE, (0.45, 0.25, 0.05, 0.05))
        self.assertEqual((got.chosen.id, got.chosen.src), ("F/cal/m08", None))

    def test_a_line_drag_counts_as_its_centre_point(self):
        """A drag with width but no height has no area: it is the point at its centre (0.3, 0.3)."""
        self.assertEqual(pick_element(CAL_PAGE, (0.25, 0.3, 0.1, 0.0)).chosen.id, "F/cal/m07")


class Ladder(unittest.TestCase):
    """The ladder: the chosen element, its ancestors nearest first up to LADDER_MAX rungs, then the root."""

    def test_the_ladder_climbs_from_the_element_to_the_root(self):
        """A click on the July cell gives the cell, the strip and the figure, named el, el2 and fig."""
        got = pick_element(CAL_PAGE, (0.3, 0.3, 0.0, 0.0))
        self.assertEqual([e.id for e in got.ladder], ["F/cal/m07", "F/cal", "F"])
        self.assertEqual(ladder_scopes(got.ladder), ("el", "el2", "fig"))

    def test_a_deep_chain_keeps_the_nearest_rungs_up_to_the_cap_then_the_root(self):
        """Twelve nested elements: the ladder keeps the chosen one and its seven nearest ancestors, then the root."""
        chain, parent = [], "F"
        for i in range(12):
            side = 0.8 - 0.05 * i
            e = el("F/%d" % i, parent, (0.1, 0.1, side, side))
            chain.append(e)
            parent = e.id
        got = pick_element(page(*chain), (0.12, 0.12, 0.0, 0.0))
        self.assertEqual(got.chosen.id, "F/11")
        self.assertEqual([e.id for e in got.ladder], ["F/%d" % i for i in range(11, 3, -1)] + ["F"])
        self.assertEqual(len(got.ladder), LADDER_MAX + 1)
        self.assertEqual(ladder_scopes(got.ladder), ("el", "el2", "el3", "el4", "el5", "el6", "el7", "el8", "fig"))

    def test_scopes_refuse_a_ladder_no_pick_makes(self):
        """An empty ladder, or one with more than LADDER_MAX element rungs, is a defect (ValueError)."""
        with self.assertRaises(ValueError):
            ladder_scopes(())
        with self.assertRaises(ValueError):
            ladder_scopes((ROOT,) * (LADDER_MAX + 2))


class Kind(unittest.TestCase):
    """element_kind: the pin kind of a rung."""

    def test_the_root_is_figure_and_an_element_is_its_part(self):
        """figure for the root; el:<part>, or el:? without a part, for any other element."""
        self.assertEqual(element_kind(ROOT, True), "figure")
        self.assertEqual(element_kind(JUL, False), "el:MonthCell")
        self.assertEqual(element_kind(el("F/x", "F", (0, 0, 1, 1)), False), "el:?")

    def test_a_long_part_is_cut_so_the_kind_fits_a_pin(self):
        """A pin's kind is at most 80 characters, so a longer part is cut to 77."""
        self.assertEqual(element_kind(el("F/x", "F", (0, 0, 1, 1), part="P" * 200), False), "el:" + "P" * 77)


class Follow(unittest.TestCase):
    """follow_element: where a pinned element is on another build's map."""

    def test_the_same_place_within_eps_is_ok(self):
        """Same page, every component within FOLLOW_EPS: ok, with the element's box on this map."""
        got = follow_element(fmap(CAL_PAGE), "F/cal/m07", 1, (0.2, 0.2 + FOLLOW_EPS / 2, 0.2, 0.2))
        self.assertEqual(got, ElementFollow(1, JUL.frac, "ok"))

    def test_a_new_box_or_a_new_page_is_moved(self):
        """A box that changed, or the same box on another page, is moved to where the map puts it now."""
        moved = el("F/cal/m07", "F/cal", (0.25, 0.2, 0.2, 0.2), src=(88, 95))
        self.assertEqual(
            follow_element(fmap(page(CAL, moved, AUG)), "F/cal/m07", 1, JUL.frac),
            ElementFollow(1, moved.frac, "moved"),
        )
        self.assertEqual(
            follow_element(fmap(page(CAL, JUL, AUG, n=2)), "F/cal/m07", 1, JUL.frac),
            ElementFollow(2, JUL.frac, "moved"),
        )

    def test_an_id_gone_from_the_map_is_lost(self):
        """No element with that id on any page: lost, with no page or box."""
        self.assertEqual(
            follow_element(fmap(page(CAL, AUG)), "F/cal/m07", 1, JUL.frac), ElementFollow(None, None, "lost")
        )


# ---------------------------------------------------------------- properties on generated element trees


@st.composite
def pages(draw):
    """A page with a random element tree: each element's parent is an earlier element, boxes anywhere on the page."""
    count = draw(st.integers(min_value=0, max_value=12))
    elements = [ROOT]
    for i in range(count):
        parent = draw(st.sampled_from([e.id for e in elements]))
        x = draw(st.floats(0.0, 0.95))
        y = draw(st.floats(0.0, 0.95))
        w = draw(st.floats(0.01, 1.0 - x))
        h = draw(st.floats(0.01, 1.0 - y))
        elements.append(el("F/%d" % i, parent, (x, y, w, h), src=(1, 2)))
    return MapPage(1, "F", None, tuple(elements))


@st.composite
def drags(draw):
    """A drag inside the page, possibly without width or height (a click or a line)."""
    x = draw(st.floats(0.0, 1.0))
    y = draw(st.floats(0.0, 1.0))
    return (x, y, draw(st.floats(0.0, 1.0 - x)), draw(st.floats(0.0, 1.0 - y)))


def overlap(a, b):
    """The oracle's shared area of two boxes."""
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def cover(box, d):
    """The oracle's cover: the share of the drag inside box; a drag without area is its centre point."""
    if d[2] * d[3] <= 0:
        x, y = d[0] + d[2] / 2, d[1] + d[3] / 2
        return 1.0 if box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3] else 0.0
    return min(1.0, overlap(box, d) / (d[2] * d[3]))


def fill(box, d):
    """The oracle's fill: the share of box the drag covers."""
    return min(1.0, overlap(box, d) / (box[2] * box[3]))


def common_ancestor(pg, els):
    """The oracle's nearest common ancestor (an element counts as its own ancestor)."""
    chains = [[e.id, *(a.id for a in pg.ancestors(e))] for e in els]
    return pg.by_id(next(i for i in chains[0] if all(i in c for c in chains)))


class Properties(unittest.TestCase):
    """The rules hold for every generated page and drag."""

    @settings(deadline=None, max_examples=200)
    @given(pages(), drags())
    def test_the_choice_is_the_deepest_cover_else_the_common_ancestor_else_the_root(self, pg, d):
        """Total, and never another element: step 1 by depth, step 2 by the filled elements, step 3 the root;
        score is the chosen element's cover."""
        got = pick_element(pg, d)
        others = pg.elements[1:]
        covering = [e for e in others if cover(e.frac, d) >= COVER_MIN]
        if covering:
            self.assertGreaterEqual(cover(got.chosen.frac, d), COVER_MIN)
            self.assertEqual(len(pg.ancestors(got.chosen)), max(len(pg.ancestors(e)) for e in covering))
        else:
            filled = [e for e in others if fill(e.frac, d) >= FILL_MIN]
            want = common_ancestor(pg, filled) if filled else pg.root()
            self.assertEqual(got.chosen.id, want.id)
        self.assertEqual(got.score, cover(got.chosen.frac, d))

    @settings(deadline=None, max_examples=200)
    @given(pages(), drags())
    def test_the_ladder_climbs_parents_ends_with_the_root_and_names_match_its_length(self, pg, d):
        """First the choice, then parents one by one, at most LADDER_MAX of them, the root last; scopes el..fig."""
        got = pick_element(pg, d)
        root = pg.root()
        self.assertEqual(got.ladder[0].id, got.chosen.id)
        self.assertEqual(got.ladder[-1].id, root.id)
        self.assertLessEqual(len(got.ladder), LADDER_MAX + 1)
        rungs = got.ladder[:-1]
        for child, parent in zip(rungs, rungs[1:]):
            self.assertEqual(child.parent, parent.id)
        scopes = ladder_scopes(got.ladder)
        self.assertEqual(len(scopes), len(got.ladder))
        self.assertEqual(scopes, tuple("el" if i == 0 else "el%d" % (i + 1) for i in range(len(scopes) - 1)) + ("fig",))

    @settings(deadline=None, max_examples=100)
    @given(pages())
    def test_following_any_element_on_its_own_map_is_ok(self, pg):
        """Nothing moved: every element found at its own page and box."""
        m = FigureMap("figures.pdf", SHA, (pg,))
        for e in pg.elements:
            self.assertEqual(follow_element(m, e.id, 1, e.frac), ElementFollow(1, e.frac, "ok"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests and see them fail**

Run: `uv run pytest -q tests/test_figmap_pick.py`
Expected: collection error, `ImportError: cannot import name 'COVER_MIN' from 'limn.figmap'`.

- [ ] **Step 4: Implement**

Append to `src/limn/figmap.py`. Make sure the module imports `from collections.abc import Sequence`, `from dataclasses import dataclass` and `from typing import Literal, TypeAlias`, and add any of them it lacks:

```python
# ---------------------------------------------------------------- Picking an element and following it (P1b)
#
# docs/handbook/domain.md §역변환이 두 경로인 이유 and §범위 사다리 describe the pick and the ladder these rules extend.

COVER_MIN = 0.6  # an element holding at least this share of the drag is a candidate (step 1)
FILL_MIN = 0.5  # an element the drag covers at least this share of joins the common-ancestor step (step 2)
LADDER_MAX = 8  # element rungs below the root: "el", "el2", ..., "el8"; the root rung is "fig"
FOLLOW_EPS = 1e-4  # a box component moved by no more than this is where it was
KIND_PART_MAX = 77  # "el:" + part stays within a pin kind's 80 characters
# Where a pinned element is on a later build's map: where it was, somewhere else, or gone.
ElSync: TypeAlias = Literal["ok", "moved", "lost"]


@dataclass(frozen=True)
class ElementPick:
    """What a drag on a figure page chose (pick_element): the element; its range ladder - the element, then its
    ancestors nearest first, at most LADDER_MAX element rungs, then the page root (just the root when the root was
    chosen); and the element's cover of the drag, 0..1."""

    chosen: MapElement
    ladder: tuple[MapElement, ...]
    score: float


def _area(box: Frac) -> float:
    """The area of a page box in page fractions."""
    return box[2] * box[3]


def _overlap(a: Frac, b: Frac) -> float:
    """The area two page boxes share; 0.0 when they only touch or are apart."""
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _cover(box: Frac, drag: Frac) -> float:
    """How much of the drag lies in box, |box ∩ drag| / |drag|. A drag without area is the point at its centre: 1.0
    when box holds that point (edges included), else 0.0."""
    if _area(drag) <= 0:
        x, y = drag[0] + drag[2] / 2, drag[1] + drag[3] / 2
        return 1.0 if box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3] else 0.0
    return min(1.0, _overlap(box, drag) / _area(drag))


def _fill(box: Frac, drag: Frac) -> float:
    """How much of box the drag covers, |box ∩ drag| / |box|; 0.0 for a box without area (parse_map refuses one)."""
    return min(1.0, _overlap(box, drag) / _area(box)) if _area(box) > 0 else 0.0


def _common_ancestor(page: MapPage, els: Sequence[MapElement]) -> MapElement:
    """The deepest element of page that is each of els or an ancestor of it (an element counts as its own ancestor).
    els is not empty; every chain ends at the root, so there always is one."""
    chains = [(e, *page.ancestors(e)) for e in els]
    shared = set.intersection(*({a.id for a in chain} for chain in chains))
    return next(a for a in chains[0] if a.id in shared)


def _ladder(page: MapPage, chosen: MapElement) -> tuple[MapElement, ...]:
    """chosen, its ancestors nearest first - at most LADDER_MAX element rungs in all - then the page root; (root,)
    when chosen is the root."""
    root = page.root()
    if chosen.id == root.id:
        return (root,)
    rungs = [chosen, *(a for a in page.ancestors(chosen) if a.id != root.id)]
    return (*rungs[:LADDER_MAX], root)


def pick_element(page: MapPage, drag: Frac) -> ElementPick:
    """The element a drag on this page points at; total - every drag gets an answer.

    Only the page's non-root elements compete in steps 1 and 2 (the root spans the page, so it always covers the
    drag and would hide both steps):
    1. the deepest element whose cover of the drag (_cover) is at least COVER_MIN - ties go to the smaller box, then
       to the earlier element in the map;
    2. else the nearest common ancestor of the elements the drag fills to at least FILL_MIN (_fill) - a drag across
       siblings (a drag without area fills nothing);
    3. else the root, the whole figure.
    score is the chosen element's cover."""
    root = page.root()
    others = [e for e in page.elements if e.id != root.id]
    order = {e.id: i for i, e in enumerate(page.elements)}
    covering = [e for e in others if _cover(e.frac, drag) >= COVER_MIN]
    if covering:
        chosen = min(covering, key=lambda e: (-len(page.ancestors(e)), _area(e.frac), order[e.id]))
    else:
        filled = [e for e in others if _fill(e.frac, drag) >= FILL_MIN]
        chosen = _common_ancestor(page, filled) if filled else root
    return ElementPick(chosen, _ladder(page, chosen), _cover(chosen.frac, drag))


def ladder_scopes(ladder: tuple[MapElement, ...]) -> tuple[str, ...]:
    """The range-ladder level names of a pick_element ladder, rung for rung: "el", "el2", ... for the element rungs,
    nearest first, and "fig" for the last rung, the page root. ValueError for an empty ladder or one with more than
    LADDER_MAX element rungs, which pick_element never makes."""
    n = len(ladder) - 1
    if n < 0 or n > LADDER_MAX:
        raise ValueError("a ladder is the root and at most %d element rungs" % LADDER_MAX)
    return tuple("el" if i == 0 else "el%d" % (i + 1) for i in range(n)) + ("fig",)


def element_kind(el: MapElement, root: bool) -> str:
    """The pin kind of a rung: "figure" for the page root; else "el:<part>" with the part cut to KIND_PART_MAX
    characters (a pin's kind is at most 80), or "el:?" for an element without a part."""
    if root:
        return "figure"
    return "el:" + (el.part[:KIND_PART_MAX] if el.part else "?")


@dataclass(frozen=True)
class ElementFollow:
    """Where a pinned element is on a map (follow_element): its page and box, both None when it is lost, and sync."""

    page: int | None
    frac: Frac | None
    sync: ElSync


def follow_element(m: FigureMap, el_id: str, page_then: int, frac_then: Frac) -> ElementFollow:
    """Where element el_id, pinned on page page_then at box frac_then, is on map m: lost (None, None) when no page of m
    has it; ok when it is on the same page with every box component within FOLLOW_EPS; else moved, with its page and
    box on m."""
    found = m.find(el_id)
    if found is None:
        return ElementFollow(None, None, "lost")
    page, el = found
    same = page.page == page_then and all(abs(a - b) <= FOLLOW_EPS for a, b in zip(el.frac, frac_then))
    return ElementFollow(page.page, el.frac, "ok" if same else "moved")
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `uv run pytest -q tests/test_figmap_pick.py`
Expected: `20 passed`.

Then run P1a's figmap tests and its purity guard with them. Run: `uv run pytest -q tests -k figmap`
Expected: all pass. The new code imports only `collections.abc`, `dataclasses` and `typing`.

- [ ] **Step 6: Break the rule and see the tests catch it (R9, Red)**

Temporarily change `if covering:` to `if False:` in `pick_element`. Run: `uv run pytest -q tests/test_figmap_pick.py -x`
Expected: FAIL in `Pick` or `Properties`. Restore the line and run again. Expected: `20 passed`.

- [ ] **Step 7: Lint, type-check and commit**

```bash
uv run ruff check src/limn/figmap.py tests/test_figmap_pick.py
uv run ruff format src/limn/figmap.py tests/test_figmap_pick.py
uv run mypy
git add src/limn/figmap.py tests/test_figmap_pick.py
git commit -s -m "feat(figmap): pick an element from a drag, name its ladder, follow it across maps" -m "Pure rules for figure documents: cover/fill pick with the root as last resort, a ladder capped at eight element rungs, pin kinds, and follow_element for read-time positions."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```
Expected: `All checks passed!` and `Success: no issues found`.

---

### Task 2: The pin's `el` shape, the record check, and rollback safety

**Files:**
- Create: `src/limn/pins/element.py`
- Modify: `src/limn/pins/record.py` (`fits_record`, `5d1c4b6` `record.py:58-127`)
- Modify: `tests/test_pins_lifecycle.py:21-39` (`PURE_IMPORTS`)
- Create: `tests/test_pins_element.py`
- Modify: `tests/test_pins_record.py`
- Modify: `tests/data/pin_records.jsonl` (append four lines)
- Create: `tests/test_figure_rollback.py`

**Interfaces:**
- Produces:
  - `ElementFrac = tuple[float, float, float, float]`
  - `ElementImpl(file: str, lo: int, hi: int)`
  - `PinElement(id: str, path: tuple[str, ...], label: str | None = None, part: str | None = None, impl: ElementImpl | None = None, frac: ElementFrac | None = None)` with `to_record() -> dict[str, Any]`, whose key order is `id, path, label?, part?, impl?, frac?`
  - `is_element_record(v: object) -> TypeGuard[dict[str, Any]]`
  - `element_of(v: object) -> PinElement | None`

**Why v0.3.5 keeps figure records (the rollback argument).** v0.3.5 checks stored records with `valid_rec` (`git show v0.3.5:src/limn/server.py`, lines 2716–2789). It types the new values only as strings and never looks at a field it does not know:

```python
    for k in ("name", "kind", "via", "scope", "sync", "pdf_build", "frac_build", "file_rel"):
        if r.get(k) is not None and not isinstance(r[k], str):
            return False
    for k, v in r.items():
        if k == "at" or k.endswith("_at") and k != "synced_at":
            ...
        elif k == "author" or k.endswith("_by"):
            ...
```

So `"via": "map"`, `"scope": "el2"`/`"fig"` and `"kind": "el:MonthCell"`/`"figure"` are plain strings to it. `el` is neither `at`, `*_at`, `author` nor `*_by`, so its nested object is never inspected. A region pin with `el` is still `is_region_pin` (lines 2792–2795: no `file`, a `pdf` string). v0.3.5's store writes every row back with `json.dumps(r, ensure_ascii=False)` (`store.py:67`, `write_pins` 141–152), the same bytes this version writes. Its `range_label` (lines 4774–4787) prints the stored `kind` for an unknown scope, so `el:MonthCell` shows in its `pins.md`. `tests/test_figure_rollback.py` runs v0.3.5's own store on the figure records, and the Done checklist repeats the check by hand with the whole v0.3.5 server.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pins_element.py`:

```python
"""limn.pins.element - a figure pin's `el`: its stored shape (is_element_record), the value readers lift from it
(element_of) and the shape it is written in (PinElement.to_record), on values alone.

Run: uv run pytest -q tests/test_pins_element.py
"""

import unittest

from hypothesis import given, strategies as st

from limn.pins.element import ElementImpl, PinElement, element_of, is_element_record

FULL = PinElement(
    "B2/m07", ("B2", "B2/m07"), "7월", "MonthCell", ElementImpl("lib/c.py", 410, 470), (0.47, 0.18, 0.07, 0.12)
)


class Shape(unittest.TestCase):
    """The record an element is written as, and what reads back from a record."""

    def test_the_record_is_id_and_path_then_only_the_set_fields_in_order(self):
        """id and path always; label, part, impl and frac only when set, in that order."""
        self.assertEqual(list(FULL.to_record()), ["id", "path", "label", "part", "impl", "frac"])
        self.assertEqual(FULL.to_record()["impl"], {"file": "lib/c.py", "lo": 410, "hi": 470})
        self.assertEqual(FULL.to_record()["frac"], [0.47, 0.18, 0.07, 0.12])
        self.assertEqual(PinElement("B2", ("B2",)).to_record(), {"id": "B2", "path": ["B2"]})

    def test_a_record_reads_back_as_the_same_element(self):
        """element_of undoes to_record; a null label reads as no label."""
        self.assertEqual(element_of(FULL.to_record()), FULL)
        self.assertEqual(element_of({"id": "B2", "path": ["B2"], "label": None}), PinElement("B2", ("B2",)))

    def test_what_is_not_an_element_reads_as_none(self):
        """Missing, not an object, an empty id, a non-string path entry or a three-number frac is no element."""
        for v in (
            None,
            "B2",
            {"id": "", "path": []},
            {"id": "B2", "path": ["B2", 1]},
            {"id": "B2", "path": ["B2"], "frac": [0, 0, 1]},
        ):
            with self.subTest(v=v):
                self.assertFalse(is_element_record(v))
                self.assertIsNone(element_of(v))

    @given(
        st.builds(
            PinElement,
            id=st.text(min_size=1, max_size=20),
            path=st.lists(st.text(max_size=20), max_size=5).map(tuple),
            label=st.none() | st.text(max_size=20),
            part=st.none() | st.text(max_size=20),
            impl=st.none() | st.builds(ElementImpl, st.text(max_size=20), st.integers(), st.integers()),
            frac=st.none() | st.tuples(st.floats(0, 1), st.floats(0, 1), st.floats(0, 1), st.floats(0, 1)),
        )
    )
    def test_every_element_round_trips_through_its_record(self, el):
        """Writing an element and reading it back gives the same value, and the record passes the store's check."""
        rec = el.to_record()
        self.assertTrue(is_element_record(rec))
        self.assertEqual(element_of(rec), el)


if __name__ == "__main__":
    unittest.main()
```

Add to `tests/test_pins_record.py`: the imports `import json` and `from pathlib import Path`, the constant `CORPUS = Path(__file__).parent / "data" / "pin_records.jsonl"`, and this class before `class IsInt`:

```python
class FigureElement(unittest.TestCase):
    """A figure pin's optional `el` (limn.pins.element): the check vouches for its shape; a line pin and a region pin
    may carry one; a malformed one breaks the line like any other field."""

    EL = {
        "id": "B2/calendar/m07",
        "path": ["B2", "B2/calendar", "B2/calendar/m07"],
        "label": "7월",
        "part": "MonthCell",
        "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
        "frac": [0.47, 0.18, 0.07, 0.12],
    }

    def test_line_and_region_pins_with_an_element_pass(self):
        """A line pin with el and the figure values of kind, via and scope; a region pin with el; a null el."""
        self.assertTrue(check(dict(LINE, el=self.EL, scope="el", kind="el:MonthCell", via="map")))
        self.assertTrue(check(dict(REGION, el={"id": "B2/calendar/m08", "path": ["B2", "B2/calendar", "B2/calendar/m08"]})))
        self.assertTrue(check(dict(LINE, el=None)))

    def test_a_malformed_element_breaks_the_line(self):
        """Not an object, an empty or non-string id, no path or a non-string entry, a non-string label or part, an impl
        that is not {file: str, lo: int, hi: int}, or a frac that is not four numbers: broken, line or region pin."""
        for bad in (
            "B2",
            [],
            {"path": ["B2"]},
            {"id": "", "path": []},
            {"id": 7, "path": []},
            {"id": "B2"},
            {"id": "B2", "path": "B2"},
            {"id": "B2", "path": ["B2", 3]},
            {**self.EL, "label": 7},
            {**self.EL, "part": ["x"]},
            {**self.EL, "impl": "lib.py"},
            {**self.EL, "impl": {"file": 3, "lo": 1, "hi": 2}},
            {**self.EL, "impl": {"file": "a.py", "lo": True, "hi": 2}},
            {**self.EL, "impl": {"file": "a.py", "lo": 1}},
            {**self.EL, "frac": [0.1, 0.2, 0.3]},
            {**self.EL, "frac": [0.1, 0.2, 0.3, "x"]},
        ):
            with self.subTest(bad=bad):
                self.assertFalse(check(dict(LINE, el=bad)))
                self.assertFalse(check(dict(REGION, el=bad)))

    def test_every_figure_record_of_the_corpus_passes(self):
        """The corpus's figure records - open, awaiting review, region, Trash copy - are records the store trusts."""
        lines = [json.loads(t) for t in CORPUS.read_text(encoding="utf-8").splitlines() if '"el": ' in t]
        self.assertGreaterEqual(len(lines), 4)
        for r in lines:
            with self.subTest(id=r["id"]):
                self.assertTrue(check(r))
```

Append these four lines to `tests/data/pin_records.jsonl`, exactly as written (they are `json.dumps(record, ensure_ascii=False)`). They are an open figure line pin, an element pin awaiting review, a region pin with `el` (D7) and a Trash copy of an `el2` pin:

```text
{"file": "/tmp/limn-test/ms/figs/src/B2_calendar.py", "name": "B2_calendar.py", "lo": 88, "hi": 95, "page": 1, "raw_lo": 88, "raw_hi": 95, "kind": "el:MonthCell", "via": "map", "score": 1.0, "frac": [0.479, 0.198, 0.049, 0.073], "scope": "el", "quote": "7월", "pdf_build": "pages-20260926100000", "el": {"id": "B2/calendar/m07", "path": ["B2", "B2/calendar", "B2/calendar/m07"], "label": "7월", "part": "MonthCell", "impl": {"file": "lib/components.py", "lo": 410, "hi": 470}, "frac": [0.47, 0.18, 0.07, 0.12]}, "note": "글자를 키워 줘", "at": "2026-09-26 10:00:00", "id": 201, "author": {"login": "alice@example.com", "name": "Alice Kim"}, "anchor": {"head": "step_089 = draw(89)", "tail": "step_095 = draw(95)", "head_off": 1, "tail_off": 0}, "synced_at": 1790384400.0, "doc": "fig", "rev": 0, "file_rel": "figs/src/B2_calendar.py"}
{"file": "/tmp/limn-test/ms/figs/src/B2_calendar.py", "name": "B2_calendar.py", "lo": 12, "hi": 140, "page": 1, "raw_lo": 12, "raw_hi": 140, "kind": "figure", "via": "map", "score": 1.0, "frac": [0.1, 0.62, 0.14, 0.2], "scope": "fig", "pdf_build": "pages-20260926100000", "el": {"id": "B2", "path": ["B2"], "frac": [0, 0, 1, 1]}, "note": "여백을 줄여 줘", "at": "2026-09-26 10:00:00", "id": 202, "author": {"login": "local", "name": "로컬/에이전트"}, "anchor": {"head": "def draw_b2():", "tail": "return fig", "head_off": 0, "tail_off": 0}, "synced_at": 1790384400.0, "doc": "fig", "rev": 1, "file_rel": "figs/src/B2_calendar.py", "done": true, "review": true, "done_at": "2026-09-26 10:05:00", "closed_by": {"login": "local", "name": "로컬/에이전트"}, "thread": [{"id": 1, "by": {"login": "local", "name": "로컬/에이전트"}, "at": "2026-09-26 10:05:00", "text": "여백을 줄임", "ev": "close"}]}
{"pdf": "/tmp/limn-test/ms/figs/out/figures.pdf", "name": "figures.pdf", "kind": "region", "page": 1, "frac": [0.556, 0.198, 0.056, 0.073], "pdf_build": "pages-20260926100000", "el": {"id": "B2/calendar/m08", "path": ["B2", "B2/calendar", "B2/calendar/m08"], "label": "8월", "part": "MonthCell", "frac": [0.55, 0.18, 0.07, 0.12]}, "note": "색을 바꿔 줘", "at": "2026-09-26 10:00:00", "id": 203, "author": {"login": "bob@example.com", "name": "Bob Park"}, "doc": "fig", "rev": 0}
{"file": "/tmp/limn-test/ms/figs/src/B2_calendar.py", "name": "B2_calendar.py", "lo": 80, "hi": 97, "page": 1, "kind": "el:CalendarStrip", "via": "map", "score": 0.83, "frac": [0.3, 0.17, 0.4, 0.15], "scope": "el2", "pdf_build": "pages-20260926100000", "el": {"id": "B2/calendar", "path": ["B2", "B2/calendar"], "label": "달력", "part": "CalendarStrip", "frac": [0.06, 0.18, 0.88, 0.12]}, "note": "달력 간격", "at": "2026-09-26 10:00:00", "id": 204, "author": {"login": "alice@example.com", "name": "Alice Kim"}, "anchor": {"head": "step_080 = draw(80)", "tail": "step_097 = draw(97)", "head_off": 0, "tail_off": 0}, "synced_at": 1790384400.0, "doc": "fig", "rev": 2, "file_rel": "figs/src/B2_calendar.py", "dropped_at": "2026-09-26 10:10:00", "dropped_by": {"login": "alice@example.com", "name": "Alice Kim"}}
```

Create `tests/test_figure_rollback.py`:

```python
"""A state folder with figure pins stays valid for the release before them, v0.3.5.

Figure pins add the `el` field and the values via "map", scope el..el8/fig and kind el:<part>/figure. The
previous release must read every such record without a broken line and write it back byte for byte, so rolling
back loses nothing (docs/superpowers/plans/2026-09-30-figure-documents.md §Global Constraints). v0.3.5's valid_rec
types kind, via and scope only as strings and passes the fields it does not know. This test runs that release's
own store on the figure records of tests/data/pin_records.jsonl: the release's src/limn is taken from git and run by
a separate interpreter without site-packages, so this checkout's limn cannot shadow it. A clone without the tag
(shallow) skips; CI checks out full history.

Run: uv run pytest -q tests/test_figure_rollback.py
"""

import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "data" / "pin_records.jsonl"
TAG = "v0.3.5"

# Run by the old release: its store reads pins.jsonl through its own record check, then writes every row back.
OLD_STORE = r"""
import json, sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from limn import server, store
state = Path(sys.argv[2])
pins = store.PinStore(store.PinFiles(state), threading.RLock(), server.valid_rec, lambda rows: False,
                      lambda rows: "", Exception)
rows, bad = pins.read_pins()
pins.write_pins(rows, bad)
print(json.dumps({"module": server.__file__, "bad": bad, "ids": [r["id"] for r in rows]}))
"""


def extract_release(tag: str, dest: Path) -> Path | None:
    """The src/ folder of release `tag`, extracted under dest from `git archive` of its src/limn; None when this clone
    does not have the tag."""
    r = subprocess.run(
        ["git", "archive", "--format=tar", tag, "src/limn"], cwd=ROOT, capture_output=True, timeout=60, check=False
    )
    if r.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:  # a Python without the extraction filters; the archive is this repository's own tree
            tar.extractall(dest)
    return dest / "src"


def figure_lines() -> list[str]:
    """The corpus lines of figure pins (every record carrying `el`), exactly as stored."""
    return [line for line in CORPUS.read_text(encoding="utf-8").splitlines() if '"el": ' in line]


class RollbackToV035(unittest.TestCase):
    """v0.3.5's store on a state folder that holds only figure records."""

    def setUp(self):
        """Extract the release and make an empty state folder; skip without the tag."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_src = extract_release(TAG, Path(self.tmp.name) / "release")
        if self.old_src is None:
            self.skipTest("%s is not in this clone's history (shallow checkout)" % TAG)
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()

    def run_old_store(self) -> dict:
        """One run of OLD_STORE on self.state by the release; its JSON report."""
        r = subprocess.run(
            [sys.executable, "-S", "-c", OLD_STORE, str(self.old_src), str(self.state)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_corpus_holds_the_figure_shapes(self):
        """Line pins and a region pin with el, and the element scopes: the shapes P1b writes are all checked."""
        records = [json.loads(line) for line in figure_lines()]
        self.assertGreaterEqual(len(records), 4)
        self.assertTrue(any("file" in r for r in records) and any("pdf" in r for r in records))
        self.assertLessEqual({"el", "el2", "fig"}, {r.get("scope") for r in records})

    def test_v035_reads_every_figure_record_and_writes_it_back_byte_for_byte(self):
        """No line is broken for the old record check, every pin is read, and the old rewrite is the original bytes."""
        text = "".join(line + "\n" for line in figure_lines())
        (self.state / "pins.jsonl").write_text(text, encoding="utf-8")
        got = self.run_old_store()
        self.assertTrue(got["module"].startswith(str(self.old_src)), got["module"])
        self.assertEqual(got["bad"], [])
        self.assertEqual(got["ids"], [json.loads(line)["id"] for line in figure_lines()])
        self.assertEqual((self.state / "pins.jsonl").read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest -q tests/test_pins_element.py tests/test_pins_record.py tests/test_figure_rollback.py tests/test_pins_model.py`
Expected:
- `test_pins_element.py` fails to collect with `ModuleNotFoundError: No module named 'limn.pins.element'`.
- `FigureElement.test_a_malformed_element_breaks_the_line` fails, because `el` is not checked yet.
- `test_figure_rollback.py` passes (2 passed). This is already true of v0.3.5. The test guards the property from now on.
- `test_pins_model.py` passes. The corpus round trip keeps unknown fields.

- [ ] **Step 3: Implement**

Create `src/limn/pins/element.py`:

```python
"""The `el` field of a figure pin: which element of a figure's map the pin points at (docs/handbook/api.md §핀
레코드 스키마).

A figure pin records its element as {id, path, label?, part?, impl?: {file, lo, hi}, frac?}: id is the element's
map id, path the ids from the page root down to it, label and part its display names, impl the lines of its shared
implementation (file relative to the document's folder), frac its box [x, y, w, h] on the build the pin was placed
on. The record check (limn.pins.record) accepts a stored value by its shape alone (is_element_record); readers lift
it with element_of; the pick and the request parsers write PinElement.to_record(). Pure.
"""

from dataclasses import dataclass
from typing import Any, TypeAlias, TypeGuard

from limn.pins.shapes import is_int, is_num

# An element's box on its page: x, y, w, h in page fractions, origin top left (limn.figmap.Frac).
ElementFrac: TypeAlias = tuple[float, float, float, float]


@dataclass(frozen=True)
class ElementImpl:
    """Where an element's shared implementation is: a file relative to the document's folder, lines lo..hi."""

    file: str
    lo: int
    hi: int


@dataclass(frozen=True)
class PinElement:
    """A figure pin's element: its map id, the ids from the page root down to it, its label and part when the map
    names them, its shared implementation when the map records one, and its box on the build it was pinned on."""

    id: str
    path: tuple[str, ...]
    label: str | None = None
    part: str | None = None
    impl: ElementImpl | None = None
    frac: ElementFrac | None = None

    def to_record(self) -> dict[str, Any]:
        """The shape stored in a record and answered by the API: id and path, then label, part, impl and frac only
        when set, in that order (lists for path and frac)."""
        out: dict[str, Any] = {"id": self.id, "path": list(self.path)}
        if self.label is not None:
            out["label"] = self.label
        if self.part is not None:
            out["part"] = self.part
        if self.impl is not None:
            out["impl"] = {"file": self.impl.file, "lo": self.impl.lo, "hi": self.impl.hi}
        if self.frac is not None:
            out["frac"] = list(self.frac)
        return out


def is_element_record(v: object) -> TypeGuard[dict[str, Any]]:
    """Is v a stored `el` the store may trust? An object whose id is a non-empty string and whose path is a list of
    strings; label and part strings when present (null counts as absent); impl, when present, {file: string,
    lo: integer, hi: integer}; frac, when present, a list of four numbers. Keys it does not know pass."""
    if not isinstance(v, dict):
        return False
    eid, path = v.get("id"), v.get("path")
    if not (isinstance(eid, str) and eid and isinstance(path, list) and all(isinstance(p, str) for p in path)):
        return False
    if any(v.get(k) is not None and not isinstance(v[k], str) for k in ("label", "part")):
        return False
    impl = v.get("impl")
    if impl is not None and not (
        isinstance(impl, dict) and isinstance(impl.get("file"), str) and is_int(impl.get("lo")) and is_int(impl.get("hi"))
    ):
        return False
    frac = v.get("frac")
    return frac is None or (isinstance(frac, list) and len(frac) == 4 and all(is_num(x) for x in frac))


def element_of(v: object) -> PinElement | None:
    """The element a stored `el` names, or None when v is missing, null or not a shape is_element_record accepts."""
    if not is_element_record(v):
        return None
    impl, frac = v.get("impl"), v.get("frac")
    return PinElement(
        v["id"],
        tuple(v["path"]),
        v.get("label"),
        v.get("part"),
        None if impl is None else ElementImpl(impl["file"], impl["lo"], impl["hi"]),
        None if frac is None else (float(frac[0]), float(frac[1]), float(frac[2]), float(frac[3])),
    )
```

In `src/limn/pins/record.py`, import `from limn.pins.element import is_element_record`. In `fits_record`, right after the `changes` check (`5d1c4b6` `record.py:94-95`), add:

```python
    # A figure pin's element (limn.pins.element): optional, but a malformed one breaks the line like any other field.
    if r.get("el") is not None and not is_element_record(r["el"]):
        return False
```

Extend `fits_record`'s docstring: "... frac instead of file/lo/hi; a figure pin's `el`, when present, has its element shape (limn.pins.element.is_element_record)."

In `tests/test_pins_lifecycle.py` `PURE_IMPORTS`, add `"limn.pins.element",  # a figure pin's el shape; pure (tests/test_pins_element.py)`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run pytest -q tests/test_pins_element.py tests/test_pins_record.py tests/test_figure_rollback.py tests/test_pins_model.py tests/test_pins_lifecycle.py tests/test_viewer_source.py`
Expected: all pass, with `RollbackToV035` 2 passed (not skipped, the clone has tags).

- [ ] **Step 5: Break the check and see the tests catch it (Red)**

Temporarily replace the new `fits_record` lines with `pass`. Run: `uv run pytest -q tests/test_pins_record.py -k FigureElement`
Expected: 1 failed (`test_a_malformed_element_breaks_the_line`). Restore the lines.

- [ ] **Step 6: Commit**

```bash
uv run ruff format && uv run ruff check && uv run mypy
git add src/limn/pins/element.py src/limn/pins/record.py tests/test_pins_element.py tests/test_pins_record.py tests/test_pins_lifecycle.py tests/data/pin_records.jsonl tests/test_figure_rollback.py
git commit -s -m "feat(pins): the figure pin element field and its record check" -m "el is optional; a malformed one breaks the line. The corpus gains figure records, and v0.3.5's own store reads and rewrites them byte for byte (tests/test_figure_rollback.py)."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 3: Value lists — `via: "map"` and the element scopes

**Files:**
- Modify: `src/limn/mapping.py:320` (`Via`), plus `VIAS`
- Modify: `src/limn/web/parse.py:29` (`Via` becomes a re-export)
- Modify: `src/limn/pins/edit.py:13` (`Scope`)
- Modify: `src/limn/features/pins/editing/location.py:143-145` (via check)
- Modify: `src/limn/features/pins/editing/rules.py:77-78` (`LinePlace` via check)
- Modify: `src/limn/ui_en.json` (`reason:bad_via`)
- Modify: `tests/test_web_parse.py:232`, plus a new class
- Modify: `src/limn/features/pins/editing/test_rules.py`

**Interfaces:**
- Produces: `mapping.Via = Literal["synctex", "text", "map"]`, `mapping.VIAS: tuple[Via, ...]`, and `pins.edit.Scope`, which gains `"el", "el2", …, "el8", "fig"`. `web.parse.Via` is the same type as `mapping.Via`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_web_parse.py`, change the expected scope sentence at line 232 to:

```python
            InputRejected(
                "scope 는 raw|para|env|env2|env3|lines|el|el2|el3|el4|el5|el6|el7|el8|fig 중 하나입니다.", "bad_scope"
            ),
```

Add this class after `class Fields` (it uses the file's `Tree` fixture). Add the imports `from limn.figmap import LADDER_MAX, MapElement, ladder_scopes` and `from limn.pins.edit import SCOPES`:

```python
class FigureValueLists(Tree):
    """The value lists ADR-0011 grows: via takes map and the scope list takes the figure ladder's names."""

    def test_a_line_location_takes_via_map_and_the_figure_scopes(self):
        """via map and the scopes el, el3 and fig are accepted on a line location."""
        for scope in ("el", "el3", "fig"):
            loc = editing_location.parse_loc(
                {"file": "main.tex", "lo": 1, "hi": 2, "via": "map", "scope": scope}, Facts(self.root)
            )
            self.assertEqual((loc.via, loc.scope), ("map", scope))

    def test_a_via_outside_the_list_names_the_whole_list(self):
        """A via outside synctex|text|map is 400 bad_via, and the sentence lists the three values."""
        self.assertEqual(
            editing_location.parse_loc({"file": "main.tex", "lo": 1, "hi": 2, "via": "svg"}, Facts(self.root)),
            InputRejected("via 는 synctex|text|map 입니다.", "bad_via"),
        )

    def test_a_scope_past_the_ladder_cap_is_refused(self):
        """el9 is past LADDER_MAX: bad_scope."""
        self.assertEqual(editing_fields.parse_scope("el9").reason, "bad_scope")

    def test_every_ladder_name_is_a_scope_a_pin_may_store(self):
        """The longest ladder's level names (el..el8, fig) are all pin scopes."""
        root = MapElement("F", None, (0.0, 0.0, 1.0, 1.0), None, None, None, None)
        self.assertLessEqual(set(ladder_scopes((root,) * (LADDER_MAX + 1))), set(SCOPES))
```

In `src/limn/features/pins/editing/test_rules.py`, add to `class PlaceInvariants`:

```python
    def test_a_line_place_takes_via_map_and_the_figure_scopes(self):
        """A figure pin's line place carries via map, an el/el8/fig scope and an el:<part> kind."""
        for scope in ("el", "el8", "fig"):
            place = LinePlace(
                {"file": "/ms/a.py", "name": "a.py", "lo": 2, "hi": 3, "page": 1, "via": "map", "scope": scope},
                frozenset(),
            )
            self.assertEqual((place.fields["via"], place.fields["scope"]), ("map", scope))
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest -q tests/test_web_parse.py src/limn/features/pins/editing/test_rules.py`
Expected: FAIL. The scope sentence differs, `via 는 synctex|text 입니다.` is not the new sentence, and `LinePlace` raises `ValueError: line place via must name a location method`.

- [ ] **Step 3: Implement**

`src/limn/mapping.py`: import `get_args` from `typing`, and replace line 319–320 with:

```python
# How a selection's range was found: SyncTeX's answer for the box, the rendered text's tokens (by_text), or - on a
# figure document - its build's element map (limn.figmap, features/pins/location/figure.py).
Via: TypeAlias = Literal["synctex", "text", "map"]
VIAS: tuple[Via, ...] = get_args(Via)
```

`src/limn/web/parse.py`: replace line 29 with the explicit re-export (the same convention as `access.py`'s `AuthorityScope as AuthorityScope`), and drop `Literal` from the `typing` import if nothing else uses it:

```python
from limn.mapping import Via as Via  # how a line pin's range was traced (limn.mapping); the location parsers read it
```

`src/limn/pins/edit.py:11-13`:

```python
# scope: which rung of the range ladder a line pin was placed at - limn.mapping.compute_levels (raw drag, paragraph,
# the innermost environment and up to two outer ones, or plain lines), or on a figure document
# limn.figmap.ladder_scopes (the element and up to seven ancestors, el..el8, and the whole figure, fig).
Scope: TypeAlias = Literal[
    "raw", "para", "env", "env2", "env3", "lines", "el", "el2", "el3", "el4", "el5", "el6", "el7", "el8", "fig"
]
```

`src/limn/features/pins/editing/location.py`: import `from limn.mapping import VIAS, norm, truncate_quote`, and replace lines 143–145:

```python
    via = d.get("via")
    if via is not None and via not in VIAS:
        return InputRejected("via 는 %s 입니다." % "|".join(VIAS), "bad_via")
```

`src/limn/features/pins/editing/rules.py`: import `from limn.mapping import VIAS`, and replace lines 77–78:

```python
        if "via" in fields and fields["via"] not in VIAS:
            raise ValueError("line place via must name a location method")
```

`src/limn/ui_en.json`: change the value of `"reason:bad_via"` to `"via must be synctex, text or map."`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run pytest -q tests/test_web_parse.py src/limn/features/pins/editing tests/test_errors.py tests/test_mapping.py tests/test_figmap_pick.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format && uv run ruff check && uv run mypy
git add src/limn/mapping.py src/limn/web/parse.py src/limn/pins/edit.py src/limn/features/pins/editing/location.py src/limn/features/pins/editing/rules.py src/limn/ui_en.json tests/test_web_parse.py src/limn/features/pins/editing/test_rules.py
git commit -s -m "feat(pins): via map and the figure ladder scopes" -m "The value lists grow as ADR-0011 decided (via map; scope el..el8, fig). The bad_scope and bad_via sentences list the grown values; their reason codes are unchanged."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 4: Anchors skip Python `#` comment lines

The spec (§충돌·미확인) asks whether `anchor_of` should skip `#` comment lines for `.py` sources. **Rule (smallest safe):** the comment marker follows the pin file's suffix. `.py` skips lines whose first non-blank character is `#`, and every other file keeps `%`. Existing LaTeX anchors are unchanged byte for byte. A `%` line in Python is code and a `#` line in LaTeX is text. Resync reads the stored `head_off`/`tail_off`, so v0.3.5 follows these anchors too. The rule only affects capture (a new pin, an edit, a legacy backfill).

**Files:**
- Modify: `src/limn/mapping.py:58-60` (`is_comment`) and `383-403` (`anchor_of`), plus `comment_marker`
- Modify: `src/limn/pins/position.py:287` (backfill)
- Modify: `src/limn/features/pins/editing/service.py:63,127`
- Modify: `tests/test_mapping.py`, `tests/test_pins_position.py`

**Interfaces:**
- Produces:
  - `comment_marker(path: str) -> str`
  - `is_comment(line: str, marker: str = "%") -> bool`
  - `anchor_of(lines, lo, hi, marker: str = "%") -> dict[str, str | int]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mapping.py`:

```python
class AnchorComments(unittest.TestCase):
    """anchor_of skips whole-line comments by the file's own marker (comment_marker): % for LaTeX, # for Python."""

    PY = ["def draw():", "    # July cell", "    cell = month(7)", "    cell.label('7월')", "    # TODO bigger"]

    def test_the_marker_follows_the_file_suffix(self):
        """# for a .py drawing script; % for LaTeX and every other file, as before."""
        self.assertEqual(mapping.comment_marker("/ms/figs/src/B2_calendar.py"), "#")
        for path in ("/ms/main.tex", "/ms/refs.bib", "/ms/figs/src/draw.js", "/ms/notes"):
            self.assertEqual(mapping.comment_marker(path), "%", path)

    def test_python_hash_comments_are_skipped_at_both_ends(self):
        """A range opening and closing on # lines anchors on the code between them, offsets recorded."""
        self.assertEqual(
            mapping.anchor_of(self.PY, 2, 5, "#"),
            {"head": "cell = month(7)", "tail": "cell.label('7월')", "head_off": 1, "tail_off": 1},
        )

    def test_latex_keeps_skipping_percent_and_not_hash(self):
        """The default marker is %: a LaTeX line starting with # is text."""
        tex = ["% TODO", "#1 is the first argument", "text"]
        self.assertEqual(
            mapping.anchor_of(tex, 1, 3),
            {"head": "#1 is the first argument", "tail": "text", "head_off": 1, "tail_off": 0},
        )

    def test_a_percent_line_in_python_is_code(self):
        """With the # marker a line starting with % is not a comment."""
        self.assertEqual(mapping.anchor_of(["    % (a, b)", "x = 1"], 1, 2, "#")["head"], "% (a, b)")

    def test_a_range_of_comments_only_still_anchors_on_them(self):
        """Nothing but comments: the comments themselves are the anchor, as for LaTeX."""
        self.assertEqual(
            mapping.anchor_of(["# a", "# b"], 1, 2, "#"), {"head": "# a", "tail": "# b", "head_off": 0, "tail_off": 0}
        )
```

Append to `tests/test_pins_position.py` (it imports `OpenPin` and `LineSpan` from `limn.pins.model`, so add them to the import if missing):

```python
class FigureAnchorBackfill(unittest.TestCase):
    """A legacy pin on a Python script gets an anchor that skips # comment lines."""

    def test_a_python_pin_without_an_anchor_is_backfilled_past_its_comment(self):
        """The first line of the range is a # comment: head is the code line after it, head_off 1."""
        lines = ["x = 0", "# July cell", "cell = month(7)"]
        pin = OpenPin.from_record({"id": 1, "file": "/ms/figs/a.py", "lo": 2, "hi": 3})
        out = position.resync(pin, LineSpan("/ms/figs/a.py", 2, 3), lines, [norm(t) for t in lines], 5.0, "/ms/figs/a.py")
        self.assertEqual(
            out.record["anchor"], {"head": "cell = month(7)", "tail": "cell = month(7)", "head_off": 1, "tail_off": 0}
        )
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest -q tests/test_mapping.py tests/test_pins_position.py`
Expected: `AttributeError: module 'limn.mapping' has no attribute 'comment_marker'` and `TypeError: anchor_of() takes 3 positional arguments but 4 were given`. The backfill head is `"# July cell"`.

- [ ] **Step 3: Implement**

`src/limn/mapping.py`: replace `is_comment` (lines 58–60) and add `comment_marker` right after it:

```python
def is_comment(line: str, marker: str = "%") -> bool:
    """True for a whole-line comment: the first non-blank character is marker (a LaTeX % by default)."""
    return line.lstrip().startswith(marker)


def comment_marker(path: str) -> str:
    """The character a whole-line comment starts with in the source file at path, as anchor_of skips it: "#" for a
    Python script (a figure's drawing code, suffix .py), "%" for every other file - LaTeX, as always."""
    return "#" if path.endswith(".py") else "%"
```

Change `anchor_of`'s signature and its comment filter (lines 383–395), and extend its docstring:

```python
def anchor_of(lines: Sequence[str], lo: int, hi: int, marker: str = "%") -> dict[str, str | int]:
    """Captures the head/tail text of the block a pin points at (whole-line comments - lines starting with marker,
    comment_marker() of the pin's file - are skipped).
    ...(the rest of the docstring as it is)..."""
    idx = [i for i in range(lo - 1, min(hi, len(lines))) if lines[i].strip()]
    body = [i for i in idx if not is_comment(lines[i], marker)] or idx
```

`src/limn/pins/position.py`: import `comment_marker` from `limn.mapping`. At line 287: `out["anchor"] = anchor_of(lines, span.lo, span.hi, comment_marker(span.file))`. In `resync`'s docstring, add "(skipping the comment lines of that file's kind, limn.mapping.comment_marker)" to the backfill bullet.

`src/limn/features/pins/editing/service.py`: import `comment_marker`. Line 63 becomes `anchoring = Anchoring(anchor_of(lines, place.lo, place.hi, comment_marker(place.file)), mtime)` and line 127 becomes `anchoring = Anchoring(anchor_of(lines, *span, comment_marker(str(where.path))), mtime)`. In `add_pin`'s and `edit_pin`'s docstrings, add "the anchor skips the comment lines of the file's kind (comment_marker)".

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run pytest -q tests/test_mapping.py tests/test_pins_position.py tests/test_pins_model.py src/limn/features/pins/editing tests/test_contract_snapshot.py`
Expected: all pass. The contract snapshot is unchanged, because LaTeX anchors are the same.

- [ ] **Step 5: Commit**

```bash
uv run ruff format && uv run ruff check && uv run mypy
git add src/limn/mapping.py src/limn/pins/position.py src/limn/features/pins/editing/service.py tests/test_mapping.py tests/test_pins_position.py
git commit -s -m "feat(mapping): anchors of Python sources skip # comment lines" -m "The comment marker follows the pin file's suffix (.py: #, else %); LaTeX anchors are unchanged, and stored offsets keep older servers following them."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 5: A per-run cache of build maps and the composition root's map lookups

**Files:**
- Modify: `src/limn/build.py` (after P1a's `build_figure_pdf`)
- Modify: `src/limn/server.py` (`Runtime` `5d1c4b6:151-203`; `ServerApplication` methods next to `_doc_est_context` `589-593`)
- Create: `tests/helpers_figure.py`
- Modify: `tests/test_build.py` (append `BuildMapCacheReads`)

**Interfaces:**
- Consumes: P1a `build.load_build_map(doc, build)`, `build.FIGMAP_NAME`, `Doc.has_element_map`, `Doc.pdf_name`; `build.valid_build_name`, `build.cur_pages`.
- Produces:
  - `build.MAP_CACHE_MAX = 16`
  - `build.BuildMapCache.get(doc: BuildDoc, build: str) -> FigureMap | MapRejected | None`
  - `Runtime.figure_maps: BuildMapCache`
  - `ServerApplication.figure_map(D: Doc, build: str) -> FigureMap | MapRejected | None`
  - `ServerApplication.doc_figure_map(key: str) -> FigureMap | None`
  - tests: `helpers_figure.BUILD1`, `BUILD2`, `PAGE_PT`, `JULY`, `AUGUST`, `JULY_BOX`, `AUGUST_BOX`, `EMPTY_BOX`, `SCRIPT`, `png_header(w, h)`, `script_lines(n=140)`, `b2_map(july=JULY, august=True)`, `figure_doc(src, paths) -> Doc`, `write_build(D, name, fmap, pages=1) -> Path`

- [ ] **Step 1: Create the fixture**

Create `tests/helpers_figure.py`:

```python
"""A figure document for the tests: a figure folder with its drawing script and shared components, the element map of
the spec's example, and build folders with that map's copy on screen - no producer or pdftoppm (the map pick reads
the map copy and the script only). tests/helpers.py's figure_map() (P1a) is the same example without the August cell;
b2_map() here adds that cell (drawn without code) and a July box that a re-render can move.

figure_doc() makes figs/ under a manuscript and returns the document (key fig, folder figs/, map
figs/out/figures.limnmap.json); write_build() puts a build of it on screen. Every page is PAGE_PT points (a
1500 x 1000 px image at the tests' 150 dpi), and the *_BOX drags are in those points. Test modules import fixtures
only from helpers modules, never from one another (tests/helpers.py).
"""

import json
from pathlib import Path

from limn import files
from limn.build import FIGMAP_NAME
from limn.documents import Doc, RunPaths

BUILD1 = "pages-20260926100000"
BUILD2 = "pages-20260926110000"
PAGE_PT = (720.0, 480.0)
JULY = (0.47, 0.18, 0.07, 0.12)  # the July cell: x 338.4-388.8, y 86.4-144 points
AUGUST = (0.55, 0.18, 0.07, 0.12)  # the August cell, drawn without code (D7): x 396-446.4
JULY_BOX = (345.0, 95.0, 380.0, 130.0)  # a drag inside the July cell
AUGUST_BOX = (400.0, 95.0, 440.0, 130.0)  # a drag inside the August cell
EMPTY_BOX = (100.0, 300.0, 200.0, 400.0)  # a drag below the calendar strip, over no element but the figure
SCRIPT = "figs/src/B2_calendar.py"  # the drawing script, relative to the manuscript


def png_header(w: int, h: int) -> bytes:
    """The first bytes of a w x h PNG - all limn.build.page_list reads of a page image."""
    return (
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    )


def script_lines(n: int = 140) -> list[str]:
    """The first n lines of the drawing script: a distinct statement per line, where L12 opens the figure, L88 is the
    comment above the July cell's call (L89-L95) and L140 closes the figure."""
    lines = ["step_%03d = draw(%d)" % (i, i) for i in range(1, n + 1)]
    for no, text in ((12, "def draw_b2():"), (88, "    # July cell"), (140, "    return fig")):
        if no <= n:
            lines[no - 1] = text
    return lines


def b2_map(july: tuple[float, float, float, float] = JULY, august: bool = True) -> dict:
    """The element map of the spec's example: figure B2 (lines 12-140), its calendar strip (80-97), the July cell (88-95,
    shared component lib/components.py 410-470) at box `july`, and - unless august is False - the August cell drawn
    without code (no src, D7). Paths are relative to the figure folder."""
    elements = [
        {"id": "B2", "frac": [0, 0, 1, 1], "src": {"file": "src/B2_calendar.py", "lo": 12, "hi": 140}},
        {
            "id": "B2/calendar",
            "parent": "B2",
            "part": "CalendarStrip",
            "label": "달력",
            "frac": [0.06, 0.18, 0.88, 0.12],
            "src": {"file": "src/B2_calendar.py", "lo": 80, "hi": 97},
        },
        {
            "id": "B2/calendar/m07",
            "parent": "B2/calendar",
            "part": "MonthCell",
            "label": "7월",
            "frac": list(july),
            "src": {"file": "src/B2_calendar.py", "lo": 88, "hi": 95},
            "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
        },
    ]
    if august:
        elements.append(
            {"id": "B2/calendar/m08", "parent": "B2/calendar", "part": "MonthCell", "label": "8월", "frac": list(AUGUST)}
        )
    return {
        "format": "limn-figure-map/1",
        "pdf": "figures.pdf",
        "pdf_sha256": "0" * 64,
        "pages": [{"page": 1, "figure": "B2", "title": "Deployment calendar", "elements": elements}],
    }


def figure_doc(src: Path, paths: RunPaths) -> Doc:
    """Figure document fig (그림) over manuscript src: figs/ holds src/B2_calendar.py (script_lines()),
    lib/components.py (480 lines) and out/figures.limnmap.json (b2_map()) beside out/figures.pdf."""
    fig = src / "figs"
    for sub in ("src", "lib", "out"):
        (fig / sub).mkdir(parents=True, exist_ok=True)
    (fig / "src" / "B2_calendar.py").write_text("\n".join(script_lines()) + "\n", encoding="utf-8")
    (fig / "lib" / "components.py").write_text(
        "".join("part_%03d = shape(%d)\n" % (i, i) for i in range(1, 481)), encoding="utf-8"
    )
    (fig / "out" / "figures.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (fig / "out" / "figures.limnmap.json").write_text(json.dumps(b2_map(), ensure_ascii=False), encoding="utf-8")
    return Doc("fig", "그림", "figure", fig, fig / "out" / "figures.limnmap.json", paths=paths)


def write_build(D: Doc, name: str, fmap: dict | None, pages: int = 1) -> Path:
    """Put build `name` of figure document D on screen as an import leaves it: `pages` page images of PAGE_PT, the PDF
    copy (D.pdf_name) and, unless fmap is None, the map copy (FIGMAP_NAME). Returns the build folder."""
    d = D.dir / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, pages + 1):
        (d / ("page-%d.png" % i)).write_bytes(png_header(1500, 1000))
    (d / D.pdf_name).write_bytes(b"%PDF-1.4\n%%EOF\n")
    if fmap is not None:
        (d / FIGMAP_NAME).write_text(json.dumps(fmap, ensure_ascii=False), encoding="utf-8")
    files.atomic_write(D.dir / "pages.cur", name)
    return d
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_build.py` (the tests of `limn/build.py`, verification.md §1). Add the imports it lacks: `import tempfile`, `import unittest`, `from pathlib import Path`, `from limn.build import FIGMAP_NAME, MAP_CACHE_MAX, BuildMapCache`, `from limn.documents import RunPaths`, `from limn.figmap import FigureMap, MapRejected`, and `from helpers_figure import BUILD1, b2_map, figure_doc, write_build`:

```python
class BuildMapCacheReads(unittest.TestCase):
    """limn.build.BuildMapCache, the per-run cache of parsed figure maps: a build's map copy is parsed once and served
    again while the copy is unchanged; a rewritten copy, a missing one and a name that is not a build miss. One figure
    document with build BUILD1 on screen and a fresh cache."""

    def setUp(self):
        """Temp manuscript and state folder, the figure document, its first build."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        src = root / "ms"
        src.mkdir()
        (root / "state").mkdir()
        self.fig = figure_doc(src, RunPaths(src, src / "main.tex", root / "state"))
        write_build(self.fig, BUILD1, b2_map())
        self.cache = BuildMapCache()

    def test_an_unchanged_copy_is_parsed_once(self):
        """The second read of the same copy is the very map the first one parsed."""
        first = self.cache.get(self.fig, BUILD1)
        self.assertIsInstance(first, FigureMap)
        self.assertIs(self.cache.get(self.fig, BUILD1), first)

    def test_a_rewritten_copy_is_parsed_again(self):
        """A copy written again (another size) is a miss, and the new map is what comes back."""
        first = self.cache.get(self.fig, BUILD1)
        write_build(self.fig, BUILD1, b2_map(july=(0.4, 0.18, 0.07, 0.12)))
        second = self.cache.get(self.fig, BUILD1)
        self.assertIsNot(second, first)
        self.assertEqual(second.find("B2/calendar/m07")[1].frac, (0.4, 0.18, 0.07, 0.12))

    def test_a_missing_copy_or_a_name_that_is_not_a_build_is_none(self):
        """No copy in that build, or a name no page directory can have (a path), gives None and reads nothing."""
        self.assertIsNone(self.cache.get(self.fig, "pages-20990101000000"))
        self.assertIsNone(self.cache.get(self.fig, "../state"))

    def test_a_refused_copy_is_cached_as_refused(self):
        """A copy the parser refuses is MapRejected, and it is not parsed again while unchanged."""
        (self.fig.dir / BUILD1 / FIGMAP_NAME).write_text("not json", encoding="utf-8")
        got = self.cache.get(self.fig, BUILD1)
        self.assertIsInstance(got, MapRejected)
        self.assertIs(self.cache.get(self.fig, BUILD1), got)

    def test_the_oldest_entry_goes_first_beyond_the_cap(self):
        """MAP_CACHE_MAX + 1 builds read in turn: the first is parsed again, the last is still cached."""
        names = ["pages-202609261000%02d" % i for i in range(MAP_CACHE_MAX + 1)]
        for name in names:
            write_build(self.fig, name, b2_map())
        first = self.cache.get(self.fig, names[0])
        last = [self.cache.get(self.fig, name) for name in names[1:]][-1]
        self.assertIs(self.cache.get(self.fig, names[-1]), last)
        self.assertIsNot(self.cache.get(self.fig, names[0]), first)
```

- [ ] **Step 3: Run the tests and see them fail**

Run: `uv run pytest -q tests/test_build.py -k BuildMapCacheReads`
Expected: collection error, `ImportError: cannot import name 'MAP_CACHE_MAX' from 'limn.build'`.

- [ ] **Step 4: Implement**

In `src/limn/build.py`, after P1a's `build_figure_pdf`, add the following. `build.py` cannot import `documents` (documents imports build), so the document is typed `BuildDoc`, like `load_build_map`. Add `import threading` and `field` to the `dataclasses` import if they are missing:

```python
MAP_CACHE_MAX = 16  # parsed maps kept per run: the current and previous builds of a few figure documents


@dataclass
class BuildMapCache:
    """The parsed maps of one run's figure builds, so a pick, GET /api/pins and every pins.md render do not parse the
    same map copy again. An entry is keyed by the document's folder, the build name and the copy's (mtime_ns, size):
    the import writes a build's copy once, so an entry stays right, and a copy written again misses. At most
    MAP_CACHE_MAX entries, the oldest dropped first. Request threads share it under its lock; the composition root
    makes one per run (server.Runtime.figure_maps)."""

    _entries: dict[tuple[str, str, int, int], FigureMap | MapRejected] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, doc: BuildDoc, build: str) -> FigureMap | MapRejected | None:
        """The map of build `build` of figure document doc as load_build_map reads it - from the cache while the copy
        is unchanged. None, without reading, when build is not a page directory name or the build has no map copy."""
        if not valid_build_name(build):
            return None
        try:
            st = (doc.dir / build / FIGMAP_NAME).stat()
        except OSError:
            return None
        key = (str(doc.dir), build, st.st_mtime_ns, st.st_size)
        with self._lock:
            hit = self._entries.get(key)
        if hit is not None:
            return hit
        got = load_build_map(doc, build)
        if got is None:
            return None
        with self._lock:
            self._entries[key] = got
            while len(self._entries) > MAP_CACHE_MAX:
                del self._entries[next(iter(self._entries))]
        return got
```

`src/limn/server.py`:

- Import `from limn.figmap import FigureMap, MapRejected` (`build` is already imported from `limn`).
- In `Runtime`, after `token_cache`:

```python
    # the parsed element maps of figure builds, one parse per build copy (limn.build.BuildMapCache)
    figure_maps: build.BuildMapCache = field(default_factory=build.BuildMapCache)
```

- In `ServerApplication`, after `_doc_est_context`:

```python
    def figure_map(self, D: Doc, build: str) -> FigureMap | MapRejected | None:
        """The element map of build `build` (a page directory name) of figure document D, parsed once per build copy in
        this run (RT.figure_maps), or None for a document without an element map or a build without a map copy."""
        if not D.has_element_map:
            return None
        return self.RT.figure_maps.get(D, build)

    def doc_figure_map(self, key: str) -> FigureMap | None:
        """The loadable map of the build on screen of the figure document key names - what the read-time fields and
        pins.md follow elements on - or None: another kind of document, one no longer served, no map copy, or a map
        the parser refuses."""
        D = self.doc_by_key(key)
        got = None if D is None else self.figure_map(D, build.cur_pages(D).name)
        return got if isinstance(got, FigureMap) else None
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `uv run pytest -q tests/test_build.py -k BuildMapCacheReads`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
uv run ruff format && uv run ruff check && uv run mypy
git add src/limn/build.py src/limn/server.py tests/helpers_figure.py tests/test_build.py
git commit -s -m "feat(build): parse each figure build's map once per run" -m "BuildMapCache keys a build's map copy by folder, name, mtime and size; the composition root exposes figure_map and doc_figure_map to the pick and the read-time fields."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 6: The map pick (figure branch of `POST /api/pick`)

**Internal representation, and why.** A trace through the map is its own value type, `PickedElement` in `features/pins/location/figure.py`, and the fallback reuses `PickedRegion`, which gains two optional fields (`el`, `fallback`). The alternative would have been a `Picked` with a fabricated `Traced`. The reasons:

- **One owner per action (ADR-0009).** The pick stays owned by `features/pins/location`. `resolve.pick` does the dispatch on `Doc.has_element_map`, `figure.py` owns the figure branch, and `http.py` owns every body. The map is read through a callable the composition root injects (`PickContext.figure_map`), so this slice never imports the builds slice. `figure.py` does not import `resolve.py`, which avoids a cycle. It returns `PickedElement` or `FigureFallback`, and `resolve.pick` turns a fallback into the region answer.
- **R3/R8.** `Traced` is the LaTeX two-path contest (`via: synctex|text`, `split`, `weak` from token weights). A figure trace has an element, a cover score and per-rung elements, so a precise type avoids fake values and keeps `trace_range`'s meaning. No figure code knows HTTP. `http.py` maps each result type in one `match` (`pick_answer`), and the new fallback reasons are one table (`PICK_WARNINGS`) with their sentences. Refusals (`PickRefusal`) are unchanged.

**Files:**
- Create: `src/limn/features/pins/location/figure.py`
- Modify: `src/limn/features/pins/location/resolve.py` (`5d1c4b6` `48-59` `PickContext`, `83-98` `PickedRegion`, `132-180` `pick`)
- Modify: `src/limn/features/pins/location/service.py:19-21`
- Modify: `src/limn/features/pins/location/http.py` (`56-63` `PICK_WARNINGS`, `86-100` `pick_answer`, `151-169` `_region_body`)
- Modify: `src/limn/server.py:377-381` (`PickContext(...)` gets `self.figure_map`)
- Modify: `src/limn/viewer/js/i18n.js:25-27` (`PICK_WARNS`), `src/limn/ui_en.json`
- Create: `src/limn/features/pins/location/test_figure.py`

**Interfaces:**
- Consumes: Task 1 (`pick_element`, `ladder_scopes`, `element_kind`), Task 2 (`PinElement`, `ElementImpl`), Task 5 (`ServerApplication.figure_map`, `helpers_figure`).
- Produces:
  - `FigureFallbackReason = Literal["figure_map_unavailable", "element_without_source"]`
  - `FigureFallback(reason, el: PinElement | None)`
  - `Rung(level, lo, hi, label, snippet, el: PinElement, merged: tuple[str, ...] = ())`
  - `PickedElement(file: Path, n_lines: int, page: int, frac: list[float] | None, kind: str, score: float, rungs: tuple[Rung, ...], quote: str, el: PinElement, overlaps: list[dict[str, Any]], pdf_build: str, redrawing: bool)`
  - `drag_frac(box, size) -> tuple[float, float, float, float]`
  - `pin_element(page: MapPage, el: MapElement) -> PinElement`
  - `element_rungs(page: MapPage, pick: ElementPick, lines: Sequence[str]) -> tuple[Rung, ...]`
  - `read_source(D, rel, root, state) -> tuple[ManuscriptFile, list[str]] | None`
  - `pick_figure(D, page_no, box, size, frac, pdir, fmap, root, state, overlaps, redrawing) -> PickedElement | FigureFallback`
  - `PickContext.figure_map: Callable[[Doc, str], FigureMap | MapRejected | None]`
  - `PickedRegion.el: PinElement | None = None`, `PickedRegion.fallback: FigureFallbackReason | None = None`
  - `resolve.pick(...) -> Picked | PickedElement | PickedRegion | PickRefusal`

- [ ] **Step 1: Write the failing tests**

Create `src/limn/features/pins/location/test_figure.py`:

```python
"""The figure branch of POST /api/pick (features/pins/location/figure.py): a drag on a figure document traced through
its build's element map. First the ladder rungs and the answer bodies as pure values, then the pick through the
location feature's HTTP entry on a real state folder with a figure build (tests/helpers_figure.py).
docs/handbook/api.md §보기 전용 PDF 문서의 pick·핀 is the region answer it falls back to; docs/handbook/domain.md
§범위 사다리 the ladder.

Run: uv run pytest -q src/limn/features/pins/location/test_figure.py
"""

import os
import unittest
from dataclasses import replace
from unittest import mock

from limn.documents import Doc
from limn.features.pins.location import source as pick_source
from limn.features.pins.location.figure import drag_frac, element_rungs
from limn.features.pins.location.http import PICK_WARNINGS, pick_answer
from limn.features.pins.location.resolve import PickedRegion
from limn.figmap import MapElement, MapPage, SourceRef, pick_element
from limn.mapping import snippet
from limn.pins.element import PinElement

from helpers import Base, pick, ps
from helpers_figure import (
    AUGUST_BOX,
    BUILD1,
    BUILD2,
    EMPTY_BOX,
    JULY_BOX,
    b2_map,
    figure_doc,
    script_lines,
    write_build,
)

LINES = ["line %d" % i for i in range(1, 201)]
LATEX_KEYS = [
    "file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score", "warn", "n_lines", "snippet",
    "frac", "quote", "levels", "default_level", "overlaps", "pdf_build",
]
REGION_KEYS = ["doc", "kind", "view_only", "page", "frac", "pdf", "name", "quote", "n_chars", "warn", "overlaps", "pdf_build"]


def el(eid, parent, frac, src=None, file="f.py", part=None, label=None):
    """A map element; src as (lo, hi) in file."""
    return MapElement(eid, parent, tuple(frac), None if src is None else SourceRef(file, *src), None, part, label)


ROOT = el("F", None, (0, 0, 1, 1), src=(1, 200))
CAL = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(80, 97), part="CalendarStrip", label="달력")
JUL = el("F/cal/m07", "F/cal", (0.2, 0.2, 0.2, 0.2), src=(88, 95), part="MonthCell", label="7월")


def rungs(*elements, drag=(0.3, 0.3, 0.0, 0.0), lines=LINES):
    """element_rungs for a click at drag on a page of the root and elements, with the chosen file's lines."""
    pg = MapPage(1, "F", None, (ROOT, *elements))
    return element_rungs(pg, pick_element(pg, drag), lines)


class Rungs(unittest.TestCase):
    """The ladder of a map pick as rungs in the chosen element's file."""

    def test_one_rung_per_ladder_element_the_chosen_one_first(self):
        """The July cell, the strip and the figure: their lines, names, snippets and elements."""
        got = rungs(CAL, JUL)
        self.assertEqual(
            [(r.level, r.lo, r.hi, r.label) for r in got],
            [("el", 88, 95, "7월"), ("el2", 80, 97, "달력"), ("fig", 1, 200, "F")],
        )
        self.assertEqual(got[0].el, PinElement("F/cal/m07", ("F", "F/cal", "F/cal/m07"), "7월", "MonthCell", None, JUL.frac))
        self.assertEqual(got[0].snippet, snippet(LINES, 88, 95))

    def test_same_lines_merge_into_the_inner_rung(self):
        """A strip drawn by the same lines as its cell: one rung, the cell's, with el2 listed as merged."""
        same = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(88, 95), part="CalendarStrip")
        got = rungs(same, JUL)
        self.assertEqual([(r.level, r.merged) for r in got], [("el", ("el2",)), ("fig", ())])
        self.assertEqual(got[0].el.id, "F/cal/m07")

    def test_a_rung_in_another_file_or_past_the_file_end_is_left_out(self):
        """A strip drawn in lib.py is not a rung of f.py; with 96 lines the strip (to 97) and figure (to 200) drop."""
        other = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(80, 97), file="lib.py")
        self.assertEqual([r.level for r in rungs(other, JUL)], ["el", "fig"])
        self.assertEqual([r.level for r in rungs(CAL, JUL, lines=LINES[:96])], ["el"])

    def test_no_rungs_when_the_chosen_element_has_no_usable_lines(self):
        """No src (D7), or lines past the end of the file: empty - the pick falls back to the region."""
        self.assertEqual(rungs(CAL, el("F/cal/m07", "F/cal", (0.2, 0.2, 0.2, 0.2))), ())
        self.assertEqual(rungs(CAL, JUL, lines=LINES[:90]), ())

    def test_a_rung_is_named_by_label_else_part_else_id(self):
        """Without a label the part names the rung; without either, the element id."""
        named_by_part = el("F/cal", "F", (0.2, 0.2, 0.4, 0.2), src=(80, 97), part="CalendarStrip")
        bare = el("F/cal/m07", "F/cal", (0.2, 0.2, 0.2, 0.2), src=(88, 95))
        self.assertEqual([r.label for r in rungs(named_by_part, bare)], ["F/cal/m07", "CalendarStrip", "F"])


class DragFrac(unittest.TestCase):
    """drag_frac: the drag in points as page fractions."""

    def test_points_become_page_fractions(self):
        """A 36 x 24 point drag at (72, 48) on a 720 x 480 page."""
        self.assertEqual(drag_frac((72.0, 48.0, 108.0, 72.0), (720.0, 480.0)), (0.1, 0.1, 0.05, 0.05))

    def test_a_page_without_size_is_the_origin_point(self):
        """No size to divide by: the point (0, 0) - the pick then chooses by that point, never raises."""
        self.assertEqual(drag_frac((1.0, 1.0, 2.0, 2.0), (0.0, 480.0)), (0.0, 0.0, 0.0, 0.0))


class RegionBodies(unittest.TestCase):
    """The region body: unchanged for a view-only document, with el and the reason first for a figure fallback."""

    REGION = PickedRegion("rv", 1, [0.1, 0.1, 0.2, 0.2], "review.pdf", "review.pdf", "", 0, True, False, "pages")

    def test_a_view_only_region_body_is_unchanged(self):
        """Same keys in the same order, no el, the blank-region sentence only."""
        body = pick_answer(self.REGION)
        self.assertEqual(list(body), REGION_KEYS)
        self.assertEqual(body["warn"], PICK_WARNINGS["blank"])

    def test_a_figure_fallback_names_its_reason_first_and_adds_the_element(self):
        """The reason's sentence leads the warn, and el follows the contract keys."""
        el08 = PinElement("B2/m08", ("B2", "B2/m08"))
        body = pick_answer(replace(self.REGION, el=el08, fallback="element_without_source"))
        self.assertEqual(list(body), REGION_KEYS + ["el"])
        self.assertEqual(body["warn"], PICK_WARNINGS["element_without_source"] + " " + PICK_WARNINGS["blank"])
        self.assertEqual(body["el"], {"id": "B2/m08", "path": ["B2", "B2/m08"]})


class FigurePick(Base):
    """POST /api/pick on figure document fig through the location feature, with a real build and scripts."""

    def setUp(self):
        """A LaTeX document ms and the figure document fig, whose build BUILD1 with the example map is on screen."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())
        self.script = self.fig.src / "src" / "B2_calendar.py"

    def drag(self, box, build=BUILD1, page=1, **extra):
        """POST /api/pick of box (points) on page of build; pdftotext answers no text and SyncTeX must not run."""
        x0, y0, x1, y1 = box
        body = {"doc": "fig", "page": page, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "pdf_build": build, **extra}
        with (
            mock.patch.object(pick_source, "region_text", return_value=""),
            mock.patch.object(pick_source, "by_synctex", side_effect=AssertionError("no SyncTeX on a figure")),
        ):
            return pick(body, doc=self.fig)

    def test_a_drag_on_an_element_answers_its_lines_through_the_map(self):
        """The July cell: the line body in the contract's key order plus el, via map, the cell's call lines, its kind
        and name, and the ladder cell - strip - figure; pdftotext is never run for a map pick."""
        with mock.patch.object(pick_source, "region_text", side_effect=AssertionError("no pdftotext on a map pick")):
            x0, y0, x1, y1 = JULY_BOX
            d = pick({"doc": "fig", "page": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "pdf_build": BUILD1}, doc=self.fig)
        self.assertEqual(list(d), LATEX_KEYS + ["el"])
        self.assertEqual(
            (d["file"], d["name"], d["lo"], d["hi"], d["raw_lo"], d["raw_hi"], d["n_lines"]),
            (str(self.script), "B2_calendar.py", 88, 95, 88, 95, 140),
        )
        self.assertEqual(
            (d["kind"], d["via"], d["score"], d["quote"], d["default_level"], d["warn"], d["pdf_build"]),
            ("el:MonthCell", "map", 1.0, "7월", "el", "", BUILD1),
        )
        self.assertEqual(
            d["el"],
            {
                "id": "B2/calendar/m07",
                "path": ["B2", "B2/calendar", "B2/calendar/m07"],
                "label": "7월",
                "part": "MonthCell",
                "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
                "frac": [0.47, 0.18, 0.07, 0.12],
            },
        )
        self.assertEqual(
            [(lv["level"], lv["lo"], lv["hi"], lv["label"], lv["n"], lv["el"]["id"]) for lv in d["levels"]],
            [
                ("el", 88, 95, "7월", 8, "B2/calendar/m07"),
                ("el2", 80, 97, "달력", 18, "B2/calendar"),
                ("fig", 12, 140, "B2", 129, "B2"),
            ],
        )
        self.assertTrue(d["snippet"].startswith("   88      # July cell"))

    def test_a_drag_on_empty_space_picks_the_whole_figure(self):
        """No element but the root under the drag: kind figure, default level fig, the figure's lines."""
        d = self.drag(EMPTY_BOX)
        self.assertEqual((d["kind"], d["default_level"], d["lo"], d["hi"]), ("figure", "fig", 12, 140))
        self.assertEqual([lv["level"] for lv in d["levels"]], ["fig"])
        self.assertEqual(d["el"], {"id": "B2", "path": ["B2"], "frac": [0, 0, 1, 1]})

    def test_an_element_drawn_without_code_answers_the_region_with_the_element(self):
        """The August cell has no src: the region body, its reason first, and the element (D7)."""
        d = self.drag(AUGUST_BOX)
        self.assertEqual((d["kind"], d["el"]["id"]), ("region", "B2/calendar/m08"))
        self.assertTrue(d["warn"].startswith(PICK_WARNINGS["element_without_source"]))
        self.assertNotIn("lo", d)

    def test_no_loadable_map_answers_the_region_without_an_element(self):
        """No map copy, a copy the parser refuses, or a page the map does not describe: the region, no el."""
        copy = self.fig.dir / BUILD1 / "figmap.json"
        copy.unlink()
        for setup in (lambda: None, lambda: copy.write_text("not json", encoding="utf-8")):
            setup()
            d = self.drag(JULY_BOX)
            self.assertTrue(d["warn"].startswith(PICK_WARNINGS["figure_map_unavailable"]), d)
            self.assertNotIn("el", d)
        write_build(self.fig, BUILD2, b2_map(), pages=2)
        d = self.drag(JULY_BOX, build=BUILD2, page=2)
        self.assertTrue(d["warn"].startswith(PICK_WARNINGS["figure_map_unavailable"]))

    def test_a_drag_on_an_older_build_is_traced_through_that_builds_map(self):
        """After a re-render moved the July cell, a drag made on the old screen still finds the July cell (its build's
        map), while the same box on the new build lands on the strip."""
        write_build(self.fig, BUILD2, b2_map(july=(0.6, 0.18, 0.07, 0.12)))
        self.assertEqual(self.drag(JULY_BOX, build=BUILD1)["el"]["id"], "B2/calendar/m07")
        self.assertEqual(self.drag(JULY_BOX, build=BUILD2)["el"]["id"], "B2/calendar")

    def test_lines_past_the_end_of_the_script_fall_back_or_drop_the_rung(self):
        """The script shortened after the render: at 96 lines the cell's call still fits but the strip and figure do
        not (one rung); at 90 lines the cell does not fit either - the region with the cell."""
        self.script.write_text("\n".join(script_lines(96)) + "\n", encoding="utf-8")
        d = self.drag(JULY_BOX)
        self.assertEqual([lv["level"] for lv in d["levels"]], ["el"])
        self.script.write_text("\n".join(script_lines(90)) + "\n", encoding="utf-8")
        d = self.drag(JULY_BOX)
        self.assertEqual((d["kind"], d["el"]["id"]), ("region", "B2/calendar/m07"))
        self.assertTrue(d["warn"].startswith(PICK_WARNINGS["element_without_source"]))

    def test_a_script_outside_the_document_folder_is_not_read(self):
        """The script is a symlink to a file of the manuscript outside figs/: never read, the region answers."""
        outside = self.src / "elsewhere.py"
        outside.write_text("\n".join(script_lines()) + "\n", encoding="utf-8")
        self.script.unlink()
        os.symlink(outside, self.script)
        d = self.drag(JULY_BOX)
        self.assertEqual((d["kind"], d["el"]["id"]), ("region", "B2/calendar/m07"))

    def test_a_small_cover_warns_like_a_weak_match(self):
        """A tall drag across two cells and far past the strip picks the strip (their common ancestor) with a cover of
        22%: the weak-match sentence."""
        d = self.drag((345.6, 24.0, 432.0, 288.0))
        self.assertEqual((d["el"]["id"], d["score"]), ("B2/calendar", 0.22))
        self.assertTrue(d["warn"].startswith("이 영역은 원문 대조가 약합니다(22%)."))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest -q src/limn/features/pins/location/test_figure.py`
Expected: `ModuleNotFoundError: No module named 'limn.features.pins.location.figure'`.

- [ ] **Step 3: Implement the figure branch**

Create `src/limn/features/pins/location/figure.py`:

```python
"""The figure branch of POST /api/pick: a drag on a figure document traced through its build's element map to the
lines of code that drew the element (the ladder: docs/handbook/domain.md §범위 사다리; the region fallback:
docs/handbook/api.md §보기 전용 PDF 문서의 pick·핀).

resolve.pick sends a figure document here before anything else. The map comes from the composition root
(PickContext.figure_map: the pick's own build's copy, parsed once per build); which element and which ladder are
limn.figmap's pure rules (pick_element, ladder_scopes, element_kind) and element_rungs below. This module reads
only the chosen element's source file, through the checked-file helpers and only inside the document's folder, and
never the PDF. What it cannot answer with lines it answers with a FigureFallback, which resolve.pick turns into the
region answer. No HTTP here: location.http shapes every body.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, TypeAlias

from limn.documents import Doc
from limn.figmap import (
    ElementPick,
    FigureMap,
    MapElement,
    MapPage,
    MapRejected,
    element_kind,
    ladder_scopes,
    pick_element,
)
from limn.files import ManuscriptFile, file_in_tree, tex_lines, tree_part
from limn.mapping import snippet
from limn.pins.element import ElementImpl, PinElement

# Why a drag on a figure is answered with the region body instead of lines; location.http.PICK_WARNINGS words each.
FigureFallbackReason: TypeAlias = Literal["figure_map_unavailable", "element_without_source"]


@dataclass(frozen=True)
class FigureFallback:
    """A drag on a figure that cannot be given code lines: why, and the element it chose when it chose one."""

    reason: FigureFallbackReason
    el: PinElement | None


@dataclass(frozen=True)
class Rung:
    """One range-ladder rung of a map pick: its level name ("el", "el2", ..., "fig"), the lines lo..hi of the chosen
    element's file that drew its element, the name shown for it (the element's label, else part, else id), those lines
    as a snippet, the element as a pin records it, and the level names merged into it (outer rungs with the same
    lines)."""

    level: str
    lo: int
    hi: int
    label: str
    snippet: str
    el: PinElement
    merged: tuple[str, ...] = ()


@dataclass(frozen=True)
class PickedElement:
    """A drag on a figure traced through its build's map: the chosen element's source file (inside the manuscript tree
    and the document's folder) and its line count, the page, the viewer's frac as sent, the pin kind (element_kind),
    the element's cover of the drag (score), the ladder rungs (the chosen element's own first - the default), the quote
    (the element's label or ""), the element as a pin records it, the stored open pins the default rung overlaps, the
    page directory it was traced in, and whether the pages are being redrawn now."""

    file: Path
    n_lines: int
    page: int
    frac: list[float] | None
    kind: str
    score: float
    rungs: tuple[Rung, ...]
    quote: str
    el: PinElement
    overlaps: list[dict[str, Any]]
    pdf_build: str
    redrawing: bool


def drag_frac(box: tuple[float, float, float, float], size: tuple[float, float]) -> tuple[float, float, float, float]:
    """The drag box (x0, y0, x1, y1 in points, already clamped to the page) as page fractions [x, y, w, h]; the point
    (0, 0) without area when the page has no size to divide by."""
    (x0, y0, x1, y1), (pw, ph) = box, size
    if pw <= 0 or ph <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph)


def pin_element(page: MapPage, el: MapElement) -> PinElement:
    """el of page as a pin records it (limn.pins.element): its id, the ids from the page root down to it, its label and
    part, its shared implementation's file and lines when the map names them, and its box on this build."""
    chain = (el, *page.ancestors(el))
    impl = None if el.impl is None else ElementImpl(el.impl.file, el.impl.lo, el.impl.hi)
    return PinElement(el.id, tuple(e.id for e in reversed(chain)), el.label, el.part, impl, el.frac)


def element_rungs(page: MapPage, pick: ElementPick, lines: Sequence[str]) -> tuple[Rung, ...]:
    """The range ladder of a map pick in the chosen element's source file, whose current lines are `lines`: one rung per
    ladder element (level names from ladder_scopes), nearest first, for each element whose src names that same file
    and fits in it (1 <= lo <= hi <= len(lines)). A rung with the same lines as an earlier one merges into it: the
    earlier, inner rung stays - its element is the more precise answer - and lists the later level name under merged.
    Empty when the chosen element itself has no src or its lines do not fit: the pick then falls back to the region."""
    chosen = pick.chosen
    if chosen.src is None:
        return ()
    file = chosen.src.file
    out: list[Rung] = []
    for level, el in zip(ladder_scopes(pick.ladder), pick.ladder):
        ref = el.src
        if ref is None or ref.file != file or not 1 <= ref.lo <= ref.hi <= len(lines):
            continue
        same = next((i for i, r in enumerate(out) if (r.lo, r.hi) == (ref.lo, ref.hi)), None)
        if same is not None:
            out[same] = replace(out[same], merged=(*out[same].merged, level))
            continue
        name = el.label or el.part or el.id
        out.append(Rung(level, ref.lo, ref.hi, name, snippet(lines, ref.lo, ref.hi), pin_element(page, el)))
    return tuple(out) if out and out[0].el.id == chosen.id else ()


def read_source(D: Doc, rel: str, root: Path, state: Path) -> tuple[ManuscriptFile, list[str]] | None:
    """The checked source file a map names (rel, relative to the document's folder D.src) and its lines read now, or
    None: not a regular file inside the manuscript tree (limn.files.file_in_tree), not inside D.src once symlinks are
    resolved (tree_part), or no readable UTF-8 lines."""
    found = file_in_tree(str(D.src / rel), root, state)
    if not isinstance(found, ManuscriptFile) or tree_part(found.path, D.src, state) is None:
        return None
    lines = tex_lines(found)
    return (found, lines) if lines else None


def pick_figure(
    D: Doc,
    page_no: int,
    box: tuple[float, float, float, float],
    size: tuple[float, float],
    frac: list[float] | None,
    pdir: Path,
    fmap: FigureMap | MapRejected | None,
    root: Path,
    state: Path,
    overlaps: Callable[[str, int, int], list[dict[str, Any]]],
    redrawing: bool,
) -> PickedElement | FigureFallback:
    """A drag on figure document D's page page_no (box in points, size the page's, frac the viewer's as sent) traced
    through fmap, the map of the page directory pdir it was made on: the element's lines (PickedElement), or why not
    (FigureFallback) - no loadable map or no such page in it (figure_map_unavailable, no element), or a chosen element
    whose src is missing, unreadable, outside D.src or longer than its file now (element_without_source, with that
    element). overlaps gives the stored open pins the default rung overlaps; redrawing says the pages are being
    redrawn. Reads the chosen element's source file once; never the PDF."""
    if not isinstance(fmap, FigureMap):
        return FigureFallback("figure_map_unavailable", None)
    page = fmap.page(page_no)
    if page is None:
        return FigureFallback("figure_map_unavailable", None)
    pick = pick_element(page, drag_frac(box, size))
    chosen = pick.chosen
    source = read_source(D, chosen.src.file, root, state) if chosen.src is not None else None
    rungs = element_rungs(page, pick, source[1]) if source is not None else ()
    if source is None or not rungs:
        return FigureFallback("element_without_source", pin_element(page, chosen))
    found, lines = source
    first = rungs[0]
    return PickedElement(
        file=found.path,
        n_lines=len(lines),
        page=page_no,
        frac=frac,
        kind=element_kind(chosen, chosen.id == page.root().id),
        score=pick.score,
        rungs=rungs,
        quote=chosen.label or "",
        el=first.el,
        overlaps=overlaps(str(found), first.lo, first.hi),
        pdf_build=pdir.name,
        redrawing=redrawing,
    )
```

- [ ] **Step 4: Dispatch, context, service and bodies**

`src/limn/features/pins/location/resolve.py`:
- Imports: `from dataclasses import dataclass, replace`; `from limn.features.pins.location import figure, source`; `from limn.figmap import FigureMap, MapRejected`; `from limn.pins.element import PinElement`.
- `PickContext`: add the last field and extend the docstring ("…and figure_map, the element map of a build of a figure document by page directory name (the composition root's per-run cache)"):

```python
    figure_map: Callable[[Doc, str], FigureMap | MapRejected | None]
```

- `PickedRegion`: add as its last fields, and extend the docstring ("el and fallback are set for a drag on a figure document that fell back to the region: the element it chose, if any, and why"):

```python
    el: PinElement | None = None
    fallback: figure.FigureFallbackReason | None = None
```

- `pick`: return type `Picked | figure.PickedElement | PickedRegion | PickRefusal`. Replace the first lines of the body (`5d1c4b6` `145-149`) with the following, and leave the rest as it is:

```python
    pdir, page, box, (pw, ph), frac = request.pdir, request.page, request.box, request.size, request.frac
    x0, y0, x1, y1 = box
    fallback: figure.FigureFallback | None = None
    if D.has_element_map:
        traced = figure.pick_figure(
            D, page, box, (pw, ph), frac, pdir, ctx.figure_map(D, pdir.name), ctx.root, ctx.state, ctx.overlaps,
            build.state_snapshot(D)["state"] == "running",
        )
        if isinstance(traced, figure.PickedElement):
            return traced
        fallback = traced
    pdf = build.cur_pdf(D, pdir)
    rtext = source.region_text(pdf, page, x0, y0, x1, y1)
    if fallback is not None:
        region = _pick_region(D, pdir, page, box, (pw, ph), frac, rtext, ctx.root)
        return replace(region, el=fallback.el, fallback=fallback.reason)
    if D.view_only:
        return _pick_region(D, pdir, page, box, (pw, ph), frac, rtext, ctx.root)
```

  Extend `pick`'s docstring: "A figure document is traced through its build's element map first (location.figure.pick_figure, no pdftotext or SyncTeX); when that gives no lines, the region answer carries its element and reason."

`src/limn/features/pins/location/service.py`: import `PickedElement` from `.figure`, and give `resolve` the return type `Picked | PickedElement | PickedRegion | PickRefusal` and the docstring "Return source lines, a figure element's lines, a region or a named refusal."

`src/limn/features/pins/location/http.py`:
- Imports: `from limn.features.pins.location.figure import PickedElement, Rung`; `from limn.mapping import WEAK_SCORE`.
- `PICK_WARNINGS` gains two entries (keep the table comment and extend it with "figure_map_unavailable/element_without_source lead a figure's region answer"):

```python
    "figure_map_unavailable": "이 그림의 요소 지도를 읽지 못해 영역으로 찍습니다 — 그림 저장소가 지도를 다시 쓰면 다시 고르세요.",
    "element_without_source": "이 요소를 그린 코드 줄을 찾지 못해 영역으로 찍습니다 — 스크립트를 고친 뒤라면 그림을 다시 렌더하고 다시 고르세요.",
```

- `pick_answer`: the parameter type becomes `Picked | PickedElement | PickedRegion | PickRefusal`. Add `case PickedElement(): return _element_body(result)` after `case Picked():`, and extend the docstring ("…the traced range with its ladder, a figure element's lines…").
- Add after `pick_warning`:

```python
def _element_body(p: PickedElement) -> Body:
    """The body of a drag traced through a figure's map: the traced-selection body's keys in their contract order -
    the default rung's lines, via "map", the element's kind and name - then el (docs/handbook/api.md §핀 만들기와
    상태 바꾸기, the pick row)."""
    first = p.rungs[0]
    return {
        "file": str(p.file),
        "name": p.file.name,
        "page": p.page,
        "lo": first.lo,
        "hi": first.hi,
        "raw_lo": first.lo,
        "raw_hi": first.hi,
        "kind": p.kind,
        "via": "map",
        "score": round(p.score, 2),
        "warn": element_warning(p),
        "n_lines": p.n_lines,
        "snippet": first.snippet,
        "frac": p.frac,
        "quote": p.quote,
        "levels": [_rung_level(r) for r in p.rungs],
        "default_level": first.level,
        "overlaps": p.overlaps,
        "pdf_build": p.pdf_build,
        "el": p.el.to_record(),
    }


def _rung_level(r: Rung) -> dict[str, object]:
    """One levels entry of a map pick, keys in the index's order (§Pick answer): level, lo, hi, n, label, snippet, then
    its el, then merged when outer rungs had the same lines."""
    out: dict[str, object] = {
        "level": r.level,
        "lo": r.lo,
        "hi": r.hi,
        "n": r.hi - r.lo + 1,
        "label": r.label,
        "snippet": r.snippet,
        "el": r.el.to_record(),
    }
    if r.merged:
        out["merged"] = list(r.merged)
    return out


def element_warning(p: PickedElement) -> str:
    """A map pick's warn: the weak-match sentence when the chosen element holds less than WEAK_SCORE of the drag, then
    the redraw sentence while the pages are being redrawn; "" when neither applies."""
    warn = PICK_WARNINGS["weak"] % (p.score * 100) if p.score < WEAK_SCORE else ""
    if p.redrawing:
        warn = (warn + " " if warn else "") + PICK_WARNINGS["redrawing"]
    return warn
```

- `_region_body` becomes (the view-only body's keys, order and warn are unchanged when `fallback` and `el` are unset):

```python
def _region_body(r: PickedRegion) -> Body:
    """The body of a selection answered as a region - a view-only document's, or a figure's that fell back - keys in
    the order the agent contract has always had them. A figure's fallback leads the warn with its reason's sentence
    and adds el, the element it chose, after the contract keys."""
    warn = PICK_WARNINGS[r.fallback] if r.fallback is not None else ""
    if r.blank:
        warn = (warn + " " if warn else "") + PICK_WARNINGS["blank"]
    if r.redrawing:
        warn = (warn + " " if warn else "") + PICK_WARNINGS["redrawing"]
    body: Body = {
        "doc": r.doc,
        "kind": "region",
        "view_only": True,
        "page": r.page,
        "frac": r.frac,
        "pdf": r.pdf,
        "name": r.name,
        "quote": r.quote,
        "n_chars": r.n_chars,
        "warn": warn,
        "overlaps": [],
        "pdf_build": r.pdf_build,
    }
    if r.el is not None:
        body["el"] = r.el.to_record()
    return body
```

`src/limn/server.py:378-380`: pass the map lookup:

```python
            lambda: pick_resolve.PickContext(
                self.C.src, self.C.envs, self.C.state, self.RT.token_cache, self.overlaps_for_range, self.figure_map
            )
```

`src/limn/viewer/js/i18n.js`: the `PICK_WARNS` array (lines 25–27) gains the two sentences, exactly as the server writes them:

```js
const PICK_WARNS=['이 영역은 원문 대조가 약합니다({pct}%). 줄 범위를 눈으로 확인하세요.','두 경로가 다른 곳을 가리킵니다(L{a} / L{b}). 확인이 필요합니다.',
  '화면의 PDF 가 지금 원고보다 낡았습니다 — [PDF 재빌드] 뒤에 다시 고르세요.','빌드 중이라 결과가 흔들릴 수 있습니다.',
  '이 영역에는 글자가 없습니다(그림·스캔본). 메모에 무엇을 가리키는지 적어 주세요.','PDF 가 바뀌어 쪽을 다시 그리는 중입니다 — 끝나면 다시 고르세요.',
  '이 그림의 요소 지도를 읽지 못해 영역으로 찍습니다 — 그림 저장소가 지도를 다시 쓰면 다시 고르세요.',
  '이 요소를 그린 코드 줄을 찾지 못해 영역으로 찍습니다 — 스크립트를 고친 뒤라면 그림을 다시 렌더하고 다시 고르세요.'];
```

`src/limn/ui_en.json`: add after the `"PDF 가 바뀌어 쪽을 다시 그리는 중입니다 — …"` entry:

```json
 "이 그림의 요소 지도를 읽지 못해 영역으로 찍습니다 — 그림 저장소가 지도를 다시 쓰면 다시 고르세요.": "The figure's element map could not be read, so the region is pinned — select again once the figure repository writes the map.",
 "이 요소를 그린 코드 줄을 찾지 못해 영역으로 찍습니다 — 스크립트를 고친 뒤라면 그림을 다시 렌더하고 다시 고르세요.": "No code line was found for this element, so the region is pinned — if the script changed, re-render the figure and select again.",
```

P1a's pick tests in `src/limn/features/pins/location/test_figure_region.py` keep passing without change. Their fixture has a map but no drawing script, so every drag there falls back to the region body, which still names the map's PDF (`_region_pdf`). A missing map copy gives `figure_map_unavailable`. Those tests assert only the region fields.

- [ ] **Step 5: Run the tests and see them pass**

Run: `uv run pytest -q src/limn/features/pins/location tests/test_i18n.py tests/test_errors.py tests/test_server.py -k "pick or Pick or figure or Figure or Warn"`
Expected: all pass. `Rungs`, `DragFrac`, `RegionBodies` and `FigurePick` give 17 passed in `test_figure.py`.

Run the whole suite once to catch P1a expectations. Run: `uv run pytest -q -n 4 --dist loadscope`
Expected: 0 failed.

- [ ] **Step 6: Break the one-file rule and see a test catch it (Red)**

Temporarily remove `ref.file != file or` from `element_rungs`. Run: `uv run pytest -q src/limn/features/pins/location/test_figure.py -k another_file`
Expected: 1 failed. Restore the condition.

- [ ] **Step 7: Commit**

```bash
uv run ruff format && uv run ruff check && uv run mypy
git add src/limn/features/pins/location src/limn/server.py src/limn/viewer/js/i18n.js src/limn/ui_en.json
git commit -s -m "feat(pick): trace a drag on a figure through its build's element map" -m "POST /api/pick on a figure document answers the lines that drew the chosen element with via map, the element ladder and el; no loadable map or no usable lines answers the region with el and the reason first. pdftotext and SyncTeX never run for a map pick."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 7: Figure pins in `POST /api/pin` and `/edit`; figure documents take line pins

**Files:**
- Modify: `src/limn/documents.py` (`takes_line_pins`, `DocumentFacts.has_element_map`, `doc_for_file` docstring)
- Modify: `src/limn/web/parse.py` (`DocumentFacts.has_element_map`)
- Modify: `src/limn/features/pins/editing/location.py` (`parse_el`, `LineLoc.el`, `RegionLoc.el`)
- Modify: `src/limn/features/pins/editing/input.py:17-67` (whitelists, region-or-line choice)
- Modify: `src/limn/features/pins/editing/rules.py` (`LOC_FIELDS`, `REGION_PLACE_FIELDS`, `_place_*`, `LinePlace`, `RegionPlace`, `evolve_edit`)
- Modify: `tests/test_web_parse.py:43-51` (fake `Facts.has_element_map`)
- Modify: `src/limn/features/pins/editing/test_rules.py`, `src/limn/features/document_views/test_meta.py` (a new routing test; P1a's `CAPABILITY_TABLE["figure"]` and figure routing test)
- Modify: `src/limn/features/pins/location/test_figure_region.py` (P1a's two tests of "no line pins on a figure")
- Modify: `src/limn/features/pins/location/range.py` (`snippet_api`, `raw_ladder`), `service.py` (`snippet`), `http.py` (`snippet`), and `src/limn/features/pins/location/test_figure.py` (the edit card's ladder on a figure script)
- Modify: `tests/helpers_figure.py` (`pin_from_pick`)
- Modify: `src/limn/ui_en.json` (`reason:bad_el`)
- Create: `src/limn/features/pins/editing/test_figure_pins.py`

**Interfaces:**
- Produces:
  - `Doc.takes_line_pins` is `True` for `"figure"`, so `view_only` is `False`
  - `DocumentFacts.has_element_map -> bool`
  - `parse_el(v: object) -> PinElement | None | InputRejected`
  - the constants `EL_TEXT_MAX = 200`, `EL_PATH_MAX = 64`, `EL_FILE_MAX = 1024`, `EL_LINE_MAX = 1_000_000`, `EL_REFUSAL`
  - `LineLoc.el`, `RegionLoc.el`
  - `LOC_FIELDS` and `REGION_PLACE_FIELDS` end with `"el"`
  - `range.snippet_api(rng, levels, envs, source_ladder: bool = True)`, `range.raw_ladder(lines, lo, hi) -> dict[str, Any]`, `PinLocationService.snippet(rng, levels, source_ladder: bool = True)`: `GET /api/snippet?levels=1` on a figure document answers only the `raw` rung
  - tests: `helpers_figure.pin_from_pick(fig, box, actor, note="n") -> int`

- [ ] **Step 1: Write the failing tests**

Append to `tests/helpers_figure.py` (with the imports `from unittest import mock`, `from limn.features.pins.location import source as pick_source`, `from limn.web.errors import InputRejected` and `from helpers import add_pin, pick`):

```python
SAVE_LINE = ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score", "frac", "quote", "pdf_build", "el")


def pin_from_pick(fig: Doc, box: tuple[float, float, float, float], actor: dict, note: str = "n") -> int:
    """Pick box (points) on build BUILD1 of figure document fig and save the answer as the viewer does - a line pin with
    its el at the default level, or, when the pick fell back, a region pin with the el - as actor; the new pin's id.
    pdftotext answers no text."""
    x0, y0, x1, y1 = box
    with mock.patch.object(pick_source, "region_text", return_value=""):
        d = pick({"doc": fig.key, "page": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "pdf_build": BUILD1}, doc=fig)
    if d.get("kind") == "region":
        body = {k: d[k] for k in ("page", "frac", "quote", "pdf_build", "el") if d.get(k) not in (None, "")}
    else:
        body = {k: d[k] for k in SAVE_LINE if d.get(k) is not None}
        body["scope"] = d["default_level"]
    body.update(doc=fig.key, note=note)
    pin = add_pin(body, dict(actor))
    assert not isinstance(pin, InputRejected), pin
    return pin.core.pid
```

In `tests/test_web_parse.py`, give the fake `Facts` the new fact. Add the constructor parameter `has_element_map: bool = False` and the line `self.has_element_map = has_element_map` after the attribute line.

Append to `src/limn/features/document_views/test_meta.py` `class Lookups`:

```python
    def test_doc_for_file_takes_the_deepest_root_among_latex_and_figure_documents(self):
        """A figure document takes line pins too: a file under both a LaTeX build root and a figure root goes to the
        deeper root, whichever kind it is; a view-only document still never matches."""
        (self.src / "figs" / "src").mkdir(parents=True)
        (self.src / "figs" / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        fig = Doc("fig", "그림", "figure", self.src / "figs", self.src / "figs" / "f.limnmap.json", paths=self.paths)
        self.assertIs(documents.doc_for_file([self.rv, self.ms, fig], self.src, "figs/src/a.py"), fig)
        self.assertIs(documents.doc_for_file([self.rv, self.ms, fig], self.src, "main.tex"), self.ms)
        outer = Doc("all", "그림 전체", "figure", self.src, self.src / "all.limnmap.json", paths=self.paths)
        self.assertIs(documents.doc_for_file([self.rv, outer, self.rr], self.src, "rr/rr.tex"), self.rr)
        self.assertIs(documents.doc_for_file([self.rv, outer, self.rr], self.src, "main.tex"), outer)
```

Append to `src/limn/features/pins/editing/test_rules.py`:

```python
class FigurePlaces(unittest.TestCase):
    """A figure pin's place carries an el; a malformed one is refused; a re-placement replaces or drops it."""

    EL = {"id": "B2/calendar/m07", "path": ["B2", "B2/calendar", "B2/calendar/m07"], "label": "7월", "part": "MonthCell"}
    LINE = {"file": "/ms/figs/src/B2_calendar.py", "name": "B2_calendar.py", "lo": 88, "hi": 95, "page": 1}
    REGION = {"pdf": "/ms/figs/out/figures.pdf", "name": "figures.pdf", "kind": "region", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2]}

    def test_line_and_region_places_keep_the_el(self):
        """A line place and a region place both carry an el and give it back as its record."""
        self.assertEqual(LinePlace({**self.LINE, "el": self.EL}, frozenset()).fields["el"], self.EL)
        self.assertEqual(RegionPlace({**self.REGION, "el": self.EL}).fields["el"], self.EL)

    def test_a_place_refuses_a_malformed_el(self):
        """An el the record check would call broken never gets into a place (ValueError)."""
        for bad in ("B2", {**self.EL, "id": ""}, {**self.EL, "path": "B2"}, {**self.EL, "label": 7}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    LinePlace({**self.LINE, "el": bad}, frozenset())
                with self.assertRaises(ValueError):
                    RegionPlace({**self.REGION, "el": bad})

    def test_the_el_of_a_place_is_a_snapshot(self):
        """Changing the caller's el or an exposed record cannot change the validated place."""
        el = {**self.EL, "path": list(self.EL["path"])}
        place = LinePlace({**self.LINE, "el": el}, frozenset({"el"}))
        el["path"].append("x")
        place.fields["el"]["path"].append("y")
        self.assertEqual(place.fields["el"], self.EL)

    def test_a_line_re_placement_replaces_or_drops_the_el(self):
        """A re-placement with an el writes it; one without drops the old el (it no longer describes the place)."""
        record = line_record(el=dict(self.EL), scope="el")
        with_el = LinePlace({**self.LINE, "el": {"id": "B2", "path": ["B2"]}}, frozenset({"file", "lo", "hi", "el"}))
        out = evolve_edit(OpenPin.from_record(record), edited(place=with_el, range_changed=True), None, None, None, None)
        self.assertEqual(out.record["el"], {"id": "B2", "path": ["B2"]})
        bare = LinePlace(dict(self.LINE), frozenset({"file", "lo", "hi"}))
        out = evolve_edit(OpenPin.from_record(record), edited(place=bare, range_changed=True), None, None, None, None)
        self.assertNotIn("el", out.record)

    def test_a_lines_edit_keeps_the_el(self):
        """Narrowing the lines of a figure pin keeps the element it names."""
        out = evolve_edit(
            OpenPin.from_record(line_record(el=dict(self.EL))), edited(lines=(4, 6), range_changed=True), None, None, None, None
        )
        self.assertEqual(out.record["el"], self.EL)

    def test_a_region_re_placement_replaces_or_drops_the_el(self):
        """Like the quote: a region re-placed with an el writes it, without one drops it."""
        record = {"pdf": "/ms/figs/out/figures.pdf", "page": 1, "frac": [0, 0, 1, 1], "kind": "region", "el": dict(self.EL), "rev": 0}
        out = evolve_edit(OpenPin.from_record(record), edited(place=RegionPlace(dict(self.REGION))), None, None, None, None)
        self.assertNotIn("el", out.record)
        placed = RegionPlace({**self.REGION, "el": {"id": "B2", "path": ["B2"]}})
        out = evolve_edit(OpenPin.from_record(record), edited(place=placed), None, None, None, None)
        self.assertEqual(out.record["el"], {"id": "B2", "path": ["B2"]})
```

Create `src/limn/features/pins/editing/test_figure_pins.py`:

```python
"""Figure pins through pin creation and editing: POST /api/pin and /api/pins/{id}/edit keep a figure pin's el
(features/pins/editing), a figure document takes line pins (Doc.takes_line_pins), an agent's curl without el is a plain
line pin routed by its file, and a malformed el is 400 bad_el with nothing stored. parse_el is checked on its own
first. docs/handbook/api.md §핀 레코드 스키마 and §핀 수정 (`/api/pins/{id}/edit`) are the contract they extend.

Run: uv run pytest -q src/limn/features/pins/editing/test_figure_pins.py
"""

import json
import unittest

from limn.access import LOCAL_ACTOR
from limn.documents import Doc
from limn.features.pins.editing.location import EL_TEXT_MAX, parse_el
from limn.pins.element import ElementImpl, PinElement

from helpers import Base, add_pin, edit_pin, fits, jreq, ps, record_of, req, split_resp
from helpers_access import ALICE_ACTOR, BOB_ACTOR
from helpers_figure import AUGUST_BOX, BUILD1, JULY_BOX, SCRIPT, b2_map, figure_doc, pin_from_pick, write_build

GOOD = {"id": "B2/calendar/m07", "path": ["B2", "B2/calendar", "B2/calendar/m07"]}


class ParseEl(unittest.TestCase):
    """parse_el: the el a request sends, parsed once at the boundary."""

    def test_a_well_formed_el_is_its_value_and_unknown_keys_are_dropped(self):
        """Every field comes over; a key the contract does not have is dropped, as unknown top-level fields are."""
        got = parse_el(
            {
                **GOOD,
                "label": "7월",
                "part": "MonthCell",
                "impl": {"file": "lib/components.py", "lo": 410, "hi": 470, "x": 1},
                "frac": [0.47, 0.18, 0.07, 0.12],
                "future": True,
            }
        )
        self.assertEqual(
            got,
            PinElement(
                "B2/calendar/m07",
                ("B2", "B2/calendar", "B2/calendar/m07"),
                "7월",
                "MonthCell",
                ElementImpl("lib/components.py", 410, 470),
                (0.47, 0.18, 0.07, 0.12),
            ),
        )
        self.assertIsNone(parse_el(None))

    def test_a_malformed_el_is_bad_el(self):
        """Not an object; a bad id or path (empty, not strings, not ending with the id, too long); a non-string label
        or part; an impl that is absolute, climbs out, is backwards or not integers; a frac off the page."""
        for bad in (
            "B2",
            {"path": ["B2"]},
            {**GOOD, "id": ""},
            {**GOOD, "path": "B2"},
            {**GOOD, "path": []},
            {**GOOD, "path": ["B2"]},
            {**GOOD, "path": ["B2", 7, "B2/calendar/m07"]},
            {**GOOD, "label": 7},
            {**GOOD, "part": ["x"]},
            {**GOOD, "label": "x" * (EL_TEXT_MAX + 1)},
            {**GOOD, "impl": "lib.py:1-2"},
            {**GOOD, "impl": {"file": "/etc/passwd", "lo": 1, "hi": 2}},
            {**GOOD, "impl": {"file": "../lib.py", "lo": 1, "hi": 2}},
            {**GOOD, "impl": {"file": "lib.py", "lo": 3, "hi": 2}},
            {**GOOD, "impl": {"file": "lib.py", "lo": True, "hi": 2}},
            {**GOOD, "frac": [0.9, 0.1, 0.5, 0.1]},
            {**GOOD, "frac": [0.1, 0.1, 0.0, 0.1]},
        ):
            with self.subTest(bad=bad):
                self.assertEqual(parse_el(bad).reason, "bad_el")


class FigurePins(Base):
    """A LaTeX document ms and figure document fig with build BUILD1 on screen."""

    def setUp(self):
        """The two documents; the figure's first build."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())

    def post_pin(self, body):
        """POST /api/pin through the handler; (status, parsed body)."""
        code, _, out = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        return code, json.loads(out)

    def test_a_figure_document_takes_line_pins_and_serves_snippets(self):
        """takes_line_pins, so not view-only; GET /api/snippet reads the script."""
        self.assertTrue(self.fig.takes_line_pins)
        self.assertFalse(self.fig.view_only)
        code, _, body = split_resp(self.talk(req("GET", "/api/snippet?doc=fig&file=%s&lo=88&hi=89" % SCRIPT)))
        self.assertEqual(code, 200, body)
        self.assertIn("step_089", json.loads(body)["snippet"])

    def test_a_pin_from_a_map_pick_stores_its_lines_and_element(self):
        """The saved pin is a line pin on the script with the pick's el, scope el, kind el:MonthCell and via map; its
        anchor skips the # comment that opens the range; the store trusts the record."""
        rec = self.pin(pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR, "글자를 키워 줘"))
        self.assertEqual(
            (rec["doc"], rec["lo"], rec["hi"], rec["scope"], rec["kind"], rec["via"], rec["file_rel"]),
            ("fig", 88, 95, "el", "el:MonthCell", "map", SCRIPT),
        )
        self.assertEqual((rec["el"]["id"], rec["el"]["frac"]), ("B2/calendar/m07", [0.47, 0.18, 0.07, 0.12]))
        self.assertEqual(
            rec["anchor"], {"head": "step_089 = draw(89)", "tail": "step_095 = draw(95)", "head_off": 1, "tail_off": 0}
        )
        self.assertTrue(fits(rec))

    def test_a_region_pin_on_a_figure_carries_the_element(self):
        """An element drawn without code is pinned as a region with its el; no file, no lines."""
        rec = self.pin(pin_from_pick(self.fig, AUGUST_BOX, BOB_ACTOR, "색을 바꿔 줘"))
        self.assertEqual((rec["kind"], rec["el"]["id"]), ("region", "B2/calendar/m08"))
        self.assertNotIn("file", rec)
        self.assertTrue(fits(rec))

    def test_an_agent_curl_without_el_routes_by_file_and_is_a_plain_line_pin(self):
        """No doc, no el: the file under figs/ routes the pin to the figure document, where it is a plain line pin."""
        code, d = self.post_pin({"file": SCRIPT, "lo": 20, "hi": 22, "note": "선 굵기"})
        self.assertEqual(code, 200, d)
        rec = self.pin(d["id"])
        self.assertEqual((rec["doc"], rec["kind"], rec["lo"], rec["hi"]), ("fig", "lines", 20, 22))
        self.assertNotIn("el", rec)

    def test_el_is_not_kept_on_a_latex_document(self):
        """el means nothing on a LaTeX document: dropped like an unknown field."""
        pin = add_pin({"doc": "ms", "file": str(self.main), "lo": 4, "hi": 5, "el": GOOD}, dict(LOCAL_ACTOR))
        self.assertNotIn("el", self.pin(pin.core.pid))

    def test_a_malformed_el_is_refused_and_nothing_is_stored(self):
        """On a line pin and on a region pin: 400 bad_el, and pins.jsonl stays empty."""
        line = {"doc": "fig", "file": SCRIPT, "lo": 88, "hi": 95}
        region = {"doc": "fig", "page": 1, "frac": [0.55, 0.18, 0.07, 0.12]}
        for base in (line, region):
            for bad in ("B2", {**GOOD, "path": ["B2"]}, {**GOOD, "impl": {"file": "../x.py", "lo": 1, "hi": 2}}):
                with self.subTest(base=base, bad=bad):
                    code, d = self.post_pin({**base, "el": bad})
                    self.assertEqual((code, d["reason"]), (400, "bad_el"))
        self.assertEqual(ps.APP.read_pins()[0], [])

    def test_an_edit_re_places_the_element_and_a_lines_edit_keeps_it(self):
        """loc with the strip's el re-places the pin on the strip; lo/hi keep that el; loc without el drops it."""
        pid = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR)
        strip = {"id": "B2/calendar", "path": ["B2", "B2/calendar"], "label": "달력", "part": "CalendarStrip"}
        loc = {"file": SCRIPT, "lo": 80, "hi": 97, "scope": "el2", "kind": "el:CalendarStrip", "via": "map", "el": strip}
        p = record_of(edit_pin(pid, {"loc": loc, "base_rev": self.pin(pid)["rev"]}, dict(ALICE_ACTOR)))
        self.assertEqual((p["lo"], p["hi"], p["el"]), (80, 97, strip))
        p = record_of(edit_pin(pid, {"lo": 81, "hi": 97, "base_rev": p["rev"]}, dict(ALICE_ACTOR)))
        self.assertEqual(p["el"], strip)
        p = record_of(edit_pin(pid, {"loc": {"file": SCRIPT, "lo": 20, "hi": 22}, "base_rev": p["rev"]}, dict(ALICE_ACTOR)))
        self.assertNotIn("el", p)

    def test_an_edit_with_a_malformed_el_is_refused(self):
        """An edit's loc goes through the same parse: bad_el, and the pin is unchanged."""
        pid = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR)
        before = self.pin(pid)
        got = edit_pin(pid, {"loc": {"file": SCRIPT, "lo": 88, "hi": 95, "el": {"id": 3}}, "base_rev": before["rev"]}, dict(ALICE_ACTOR))
        self.assertEqual(got.reason, "bad_el")
        self.assertEqual(self.pin(pid), before)


if __name__ == "__main__":
    unittest.main()
```

**The edit card's ladder on a figure script.** The viewer's edit card reads its ladder from `GET /api/snippet?levels=1`. On a figure document that ladder is only the `raw` rung (the lines as they are, shown as '지금 범위'), never the LaTeX paragraph/environment rungs computed over Python source. The element ladder exists only in the pick answer, and the pin's `el` stays as it is unless a `loc` replaces it. Append to `src/limn/features/pins/location/test_figure.py`. Add the imports `import json`, `from pathlib import Path`, `from limn.features.pins.location.range import SourceRange, snippet_api`, `from limn.mapping import compute_levels`, `req` and `split_resp` from `helpers`, and `SCRIPT` from `helpers_figure`:

```python
class SnippetLadder(unittest.TestCase):
    """snippet_api: the source ladder (compute_levels) where a document's ladder comes from its text; only the raw
    rung where it comes from an element map (a figure's script, whose element ladder is the pick's)."""

    TEX = ["\\begin{table}", "a", "", "b", "\\end{table}"]

    def test_a_map_ladder_document_gets_only_the_raw_rung(self):
        """Python lines: one raw rung for the range, and it is the default - no paragraph or environment rung."""
        rng = SourceRange(Path("/ms/figs/src/a.py"), ["x = 1", "", "y = 2", "z = 3"], 3, 4)
        out = snippet_api(rng, True, ("table",), source_ladder=False)
        self.assertEqual(
            out["levels"],
            [{"level": "raw", "lo": 3, "hi": 4, "label": "드래그한 줄", "n": 2, "snippet": snippet(rng.lines, 3, 4)}],
        )
        self.assertEqual(out["default_level"], "raw")

    def test_a_source_ladder_document_keeps_compute_levels(self):
        """LaTeX lines: the ladder is compute_levels', unchanged."""
        rng = SourceRange(Path("/ms/main.tex"), self.TEX, 2, 2)
        out = snippet_api(rng, True, ("table",), source_ladder=True)
        want = compute_levels(self.TEX, 2, 2, ("table",))
        self.assertEqual((out["levels"], out["default_level"]), (want["levels"], want["default_level"]))
```

and to `class FigurePick` in the same file:

```python
    def test_the_edit_cards_ladder_on_a_figure_script_is_the_raw_rung_only(self):
        """GET /api/snippet?levels=1 on the figure's script: one raw rung; on the LaTeX document the paragraph rung is
        still there."""
        code, _, body = split_resp(self.talk(req("GET", "/api/snippet?doc=fig&file=%s&lo=88&hi=95&levels=1" % SCRIPT)))
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        self.assertEqual(([lv["level"] for lv in d["levels"]], d["default_level"]), (["raw"], "raw"))
        code, _, body = split_resp(self.talk(req("GET", "/api/snippet?doc=ms&file=main.tex&lo=4&hi=4&levels=1")))
        self.assertIn("para", [lv["level"] for lv in json.loads(body)["levels"]])
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest -q src/limn/features/pins/editing src/limn/features/document_views/test_meta.py tests/test_web_parse.py`
Expected: `ImportError: cannot import name 'EL_TEXT_MAX'`. `test_doc_for_file_takes_the_deepest_root_among_latex_and_figure_documents` fails because the figure document never matches. `FigurePlaces` fails with `ValueError: line place contains fields outside its location`. `SnippetLadder` fails with `TypeError: snippet_api() got an unexpected keyword argument 'source_ladder'`, and the figure snippet test fails with `400` because a figure document is still view-only.

- [ ] **Step 3: Implement**

`src/limn/documents.py`: flip the capability, and add the fact the parsers need:

```python
    @property
    def takes_line_pins(self) -> bool:
        """file/lo/hi pins, anchor re-sync, doc_for_file routing: a LaTeX document, and a figure document - its pins
        are lines of the code that drew it (docs/handbook/domain.md §여러 문서)."""
        return self.kind in ("tex", "figure")
```

In `DocumentFacts`, after `key`:

```python
    @property
    def has_element_map(self) -> bool:
        """The document is a figure with an element map (Doc.has_element_map): the location parsers keep a pin's el
        only there, and a body without file, lo or hi is a region pin on it."""
        return self._doc.has_element_map
```

`doc_for_file`'s docstring: "Which document that takes line pins (LaTeX or figure) of docs a request that only gave a file (agent curl) belongs to: the one whose folder most deeply contains it … View-only documents never match."

`src/limn/web/parse.py` `DocumentFacts` Protocol, after `key`:

```python
    @property
    def has_element_map(self) -> bool:
        """A figure document with an element map: a pin's el is kept only there, and a body without file, lo or hi is a
        region pin on it."""
        ...
```

`src/limn/features/pins/editing/location.py`: add the imports `from typing import Any` (already imported), `from limn.pins.element import ElementImpl, PinElement` and `from limn.pins.shapes import is_int`. Then:

- `LineLoc`: add `el: PinElement | None = None` as its last field (docstring: "…and each optional field the request sent - None when it did not; el is the figure element, kept on a figure document only"). Its `to_record` becomes:

```python
    def to_record(self) -> Record:
        """The fields as a pin record stores them: file, name, lo, hi, page, then each optional field that was sent,
        in this order (the key order pin records have always had; frac as a JSON list), a figure pin's el last."""
        out: dict[str, Any] = {"file": self.file, "name": self.name, "lo": self.lo, "hi": self.hi, "page": self.page}
        optional: tuple[tuple[str, object], ...] = (
            ("raw_lo", self.raw_lo),
            ("raw_hi", self.raw_hi),
            ("kind", self.kind),
            ("via", self.via),
            ("score", self.score),
            ("frac", None if self.frac is None else list(self.frac)),
            ("scope", self.scope),
            ("quote", self.quote),
            ("pdf_build", self.pdf_build),
            ("el", None if self.el is None else self.el.to_record()),
        )
        out.update((k, v) for k, v in optional if v is not None)
        return out
```

- `RegionLoc`: add `el: PinElement | None = None` as its last field (docstring: "…and the optional quote and pdf_build - None when not sent - and a figure pin's el"). Its `to_record` becomes:

```python
    def to_record(self) -> Record:
        """The fields as a pin record stores them: pdf, name, kind "region", page, frac (a JSON list), then quote,
        pdf_build and a figure pin's el when present - the key order region pins have always had, el last."""
        out: dict[str, Any] = {
            "pdf": self.pdf,
            "name": self.name,
            "kind": "region",
            "page": self.page,
            "frac": list(self.frac),
        }
        if self.quote is not None:
            out["quote"] = self.quote
        if self.pdf_build is not None:
            out["pdf_build"] = self.pdf_build
        if self.el is not None:
            out["el"] = self.el.to_record()
        return out
```
- Add after `_frac4`:

```python
EL_TEXT_MAX = 200  # characters of an element id, path entry, label or part
EL_PATH_MAX = 64  # ids from the page root down to the element
EL_FILE_MAX = 1024  # characters of impl.file
EL_LINE_MAX = 1_000_000  # the highest impl line, as for a close's changes
EL_REFUSAL = (
    "el 은 pick 이 준 요소 {id, path, label?, part?, impl?: {file, lo, hi}, frac?} 여야 합니다"
    "(문자열 200자 이하, path 는 뿌리부터 그 요소까지의 id, impl.file 은 문서 폴더 기준 상대 경로)."
)


def parse_el(v: object) -> PinElement | None | InputRejected:
    """A figure pin's el as a request sends it (POST /api/pin, an edit's loc) - the element the pick answered -> its
    value, None when absent or null, or 400 bad_el. id is a non-empty string; path a list of 1..EL_PATH_MAX non-empty
    strings ending with id; label and part strings when sent; impl, when sent, {file, lo, hi} with file a relative
    POSIX path of at most EL_FILE_MAX characters without NUL, backslash or '..' parts and 1 <= lo <= hi <= EL_LINE_MAX;
    frac, when sent, four finite numbers inside the page with positive area (parse_frac); every other string at most
    EL_TEXT_MAX characters. Keys other than these are dropped, as unknown top-level fields are."""
    if v is None:
        return None
    bad = InputRejected(EL_REFUSAL, "bad_el")
    if not isinstance(v, dict):
        return bad
    eid = v.get("id")
    if not isinstance(eid, str) or not 0 < len(eid) <= EL_TEXT_MAX:
        return bad
    path = v.get("path")
    if not isinstance(path, list) or not 1 <= len(path) <= EL_PATH_MAX or path[-1] != eid:
        return bad
    if not all(isinstance(p, str) and 0 < len(p) <= EL_TEXT_MAX for p in path):
        return bad
    label, part = v.get("label"), v.get("part")
    if any(t is not None and not (isinstance(t, str) and len(t) <= EL_TEXT_MAX) for t in (label, part)):
        return bad
    impl = _el_impl(v.get("impl"))
    if isinstance(impl, InputRejected):
        return impl
    frac: tuple[float, float, float, float] | None = None
    if v.get("frac") is not None:
        got = parse_frac(v["frac"])
        if isinstance(got, InputRejected):
            return bad
        frac = got
    return PinElement(eid, tuple(path), label, part, impl, frac)


def _el_impl(v: object) -> ElementImpl | None | InputRejected:
    """An el's impl as sent -> ElementImpl, None when absent or null, or parse_el's refusal (see its rule)."""
    if v is None:
        return None
    bad = InputRejected(EL_REFUSAL, "bad_el")
    if not isinstance(v, dict):
        return bad
    file, lo, hi = v.get("file"), v.get("lo"), v.get("hi")
    if not (isinstance(file, str) and 0 < len(file) <= EL_FILE_MAX and "\x00" not in file and "\\" not in file):
        return bad
    if file.startswith("/") or ".." in file.split("/"):
        return bad
    if not (is_int(lo) and is_int(hi) and 1 <= lo <= hi <= EL_LINE_MAX):
        return bad
    return ElementImpl(file, lo, hi)
```

- `parse_loc`: after the `pdf_build` check, parse the element on a figure document, and pass it on:

```python
    el = parse_el(d.get("el")) if facts.has_element_map else None  # a figure pin's element (api.md §핀 레코드 스키마)
    if isinstance(el, InputRejected):
        return el
```

  Add `el=el` to the `LineLoc(...)` call, and add "then el on a figure document (parse_el)" to the docstring's order.
- `parse_region`: after the quote, add the same two lines, and return `RegionLoc(str(pdf), pdf.name, page, frac, quote, want, el)`. Docstring: "…quote is whitespace-normalized and truncated to PDF_QUOTE_MAX; on a figure document the body's el (parse_el)."

`src/limn/features/pins/editing/input.py`:
- `ADD_FIELDS` gets `"el"` last, and `REGION_FIELDS = ("page", "frac", "note", "quote", "pdf_build", "el")`.
- In `parse_add`, replace the branch condition (line 44) and extend the docstring:

```python
    if facts.view_only or (facts.has_element_map and all(d.get(k) is None for k in ("file", "lo", "hi"))):
```

  Docstring: "…the location first: a region (parse_region, which refuses file/lo/hi/scope) on a view-only document, and on a figure document when the body names no file, lo or hi - an element drawn without code (docs/handbook/api.md §보기 전용 PDF 문서의 pick·핀); lines (parse_loc, which reads the named file) otherwise. A figure document's place keeps the body's el…"

`src/limn/features/pins/editing/rules.py`: import `from limn.pins.element import PinElement, element_of`, then:

```python
# A line re-placement replaces these fields as a whole; unnamed fields are dropped (a figure pin's el too).
LOC_FIELDS = ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score", "frac", "scope", "quote", "el")


# A region without a quote or an el drops the previous one.
REGION_PLACE_FIELDS = ("page", "frac", "quote", "pdf_build", "el")


def _place_record(items: tuple[tuple[str, object], ...]) -> Record:
    """Rebuild ordered JSON fields from a frozen place: a new list for its fractional coordinates, the element's record
    for its el."""
    return {key: _thawed(key, value) for key, value in items}


def _thawed(key: str, value: object) -> object:
    """A frozen place value back as JSON: a list for frac, the record of a PinElement for el."""
    if key == "frac" and isinstance(value, tuple):
        return list(value)
    if key == "el" and isinstance(value, PinElement):
        return value.to_record()
    return value


def _place_items(fields: Record) -> tuple[tuple[str, object], ...]:
    """Freeze a place's fields in their order: frac as a tuple, el as its PinElement value (validated before)."""
    return tuple((key, _frozen(key, value)) for key, value in fields.items())


def _frozen(key: str, value: object) -> object:
    """A place value frozen for its snapshot: a tuple for frac, the element value (limn.pins.element) for el."""
    if key == "frac" and isinstance(value, list):
        return tuple(value)
    if key == "el":
        return element_of(value)
    return value
```

- `LinePlace.__init__`, after the `pdf_build` check: `if "el" in fields and element_of(fields["el"]) is None: raise ValueError("line place el must be a figure element")`. Docstring: add "and a figure pin's el (limn.pins.element)".
- `RegionPlace.__init__`: the allowed keys become `{"pdf", "name", "kind", "page", "frac", "quote", "pdf_build", "el"}`, and after the `pdf_build` check add `if "el" in fields and element_of(fields["el"]) is None: raise ValueError("region place el must be a figure element")`.
- `evolve_edit`'s region branch (lines 371–375):

```python
        for key in REGION_PLACE_FIELDS:
            if key in fields:
                record[key] = fields[key]
            elif key in ("quote", "el"):
                record.pop(key, None)
```

  Docstring: "A region re-placement sets page, frac, quote and el (each dropped if not sent) and pdf_build. A line re-placement replaces every location field, el included…; a lo/hi edit keeps the el."

`src/limn/ui_en.json`: add after `"reason:bad_doc"` (every emitted reason needs its English message, `tests/test_errors.py`):

```json
 "reason:bad_el": "el must be the element the pick returned: {id, path, label?, part?, impl?: {file, lo, hi}, frac?}.",
```

**P1a's tests that this flip deliberately reverses** change in the same commit (index §Intermediate states: after P1b a figure takes line pins):

- `src/limn/features/document_views/test_meta.py`:
  - In `CAPABILITY_TABLE["figure"]`, set `"takes_line_pins": True` and `"view_only": False`.
  - In `FigureDocumentReads.test_its_brief_and_meta_report_kind_figure_view_only_and_never_stale`, rename it to `test_its_brief_and_meta_report_kind_figure_not_view_only_and_never_stale`. Its two expected tuples read `("figure", False, False, "figures.limnmap.json", "figs/out/figures.limnmap.json")` and `("figure", False, False)`, and its docstring says "view_only false (it takes line pins)".
  - Rename `test_a_file_under_a_figure_folder_routes_to_the_latex_document_around_it` to `test_a_file_under_a_figure_folder_routes_to_the_figure_document_inside`, with the docstring "The figure folder lies inside the body's build root and deeper: a file-only request (agent curl) goes to the figure document, the deepest root that takes line pins." Its assertion becomes `self.assertIs(documents.doc_for_file(docs, self.src, "figs/src/B2_calendar.py"), self.fig)`.
- `src/limn/features/builds/test_figure.py` (P1a), `test_startup_imports_a_figure_document_whose_files_agree`: `view_only` is `False` in both expected tuples, and the docstring says "view_only false".
- `src/limn/features/pins/location/test_figure_region.py` (P1a): replace the last two tests with:

```python
    def test_a_figure_document_takes_a_line_pin_on_its_script(self):
        """Since P1b a figure document takes line pins: file/lo/hi on its script make a line pin of fig, no el."""
        (self.figs / "src").mkdir()
        (self.figs / "src" / "B2_calendar.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        body = {"doc": "fig", "file": "figs/src/B2_calendar.py", "lo": 1, "hi": 2, "page": 1}
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        self.assertEqual(code, 200, raw)
        rec = self.pin(json.loads(raw)["id"])
        self.assertEqual((rec["doc"], rec["lo"], rec["hi"]), ("fig", 1, 2))
        self.assertNotIn("el", rec)

    def test_a_file_only_pin_under_the_figure_folder_goes_to_the_figure_document(self):
        """The figure folder lies inside the body's build root: an agent's pin that names only a file there goes to the
        figure document, the deepest root that takes line pins."""
        (self.figs / "src").mkdir()
        (self.figs / "src" / "B2_calendar.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        body = {"file": "figs/src/B2_calendar.py", "lo": 1, "hi": 2}
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        self.assertEqual(code, 200, raw)
        self.assertEqual(self.pin(json.loads(raw)["id"])["doc"], "fig")
```

**The figure snippet ladder** (location slice). `src/limn/features/pins/location/range.py`: `snippet_api` gains the parameter `source_ladder: bool = True`, and its `if levels:` block becomes:

```python
    if levels:
        lad = compute_levels(lines, lo, hi, envs) if source_ladder else raw_ladder(lines, lo, hi)
        out["levels"] = lad["levels"]
        out["default_level"] = lad["default_level"]
```

Extend its docstring: "…and with levels the range ladder around them - compute_levels' for the float environments envs when the document's ladder comes from its text (source_ladder), else raw_ladder's." Then add:

```python
def raw_ladder(lines: Sequence[str], lo: int, hi: int) -> dict[str, Any]:
    """The ladder of a range in a document whose rungs come from its element map rather than its text (a figure's
    drawing script): the raw rung alone - the lines as they are - and it is the default. Paragraph and environment
    rungs are LaTeX rules and mean nothing in code; the element ladder is the pick's (docs/handbook/domain.md §범위
    사다리)."""
    rung = {"level": "raw", "lo": lo, "hi": hi, "label": "드래그한 줄", "n": hi - lo + 1, "snippet": snippet(lines, lo, hi)}
    return {"levels": [rung], "default_level": "raw"}
```

`src/limn/features/pins/location/service.py`: `snippet` becomes

```python
    def snippet(self, rng: SourceRange, levels: bool, source_ladder: bool = True) -> dict[str, Any]:
        """Render a source range and optionally its range ladder: the source ladder, or the raw rung alone when the
        document's ladder comes from an element map (range.snippet_api)."""
        return source_range.snippet_api(rng, levels, self.context().envs, source_ladder)
```

`src/limn/features/pins/location/http.py`: `snippet` passes the document's capability:

```python
def snippet(app: LocationApp, doc: Doc, query: Query) -> Body:
    """GET /api/snippet after the common request guards; a document with an element map gets the raw rung as its
    ladder."""
    rng = accepted(pick_input.parse_snippet(query, app.document_facts(doc)))
    return app.location_service.snippet(rng, parse_flag(query, "levels"), not doc.has_element_map)
```

Then run `grep -rn "view_only" src/limn/features tests --include=test_*.py | grep -in "fig"`. Any other figure expectation of `view_only: true` it lists follows the same rule.

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run pytest -q src/limn/features/pins/editing src/limn/features/pins/location src/limn/features/document_views tests/test_web_parse.py tests/test_errors.py tests/test_server.py`
Expected: all pass, with `test_figure_pins.py` 10 passed and `test_figure.py` 20 passed.

Run the whole suite once. Run: `uv run pytest -q -n 4 --dist loadscope`
Expected: 0 failed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format && uv run ruff check && uv run mypy
git add src/limn/documents.py src/limn/web/parse.py src/limn/features/pins/editing src/limn/ui_en.json tests/test_web_parse.py tests/helpers_figure.py src/limn/features/document_views/test_meta.py src/limn/features/builds/test_figure.py src/limn/features/pins/location
git commit -s -m "feat(pins): figure pins keep their element; figure documents take line pins" -m "POST /api/pin and an edit's loc accept el on a figure document (400 bad_el when malformed); without file/lo/hi a figure pin is a region with el. doc_for_file routes a file to the deepest root among LaTeX and figure documents; GET /api/snippet?levels=1 on a figure script answers only the raw rung."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 8: Read-time element position in `GET /api/pins`

**Files:**
- Modify: `src/limn/pins/view.py` (`5d1c4b6` `62-101`)
- Modify: `src/limn/features/pins/listing/service.py` (`17-63`)
- Modify: `tests/test_pins_lifecycle.py` (`PURE_IMPORTS` + `"limn.figmap"`)
- Modify: `tests/test_pins_view.py`
- Create: `src/limn/features/pins/listing/test_figure_pins.py`

**Interfaces:**
- Consumes: `figmap.follow_element`, `pins.element.element_of`, `ServerApplication.doc_figure_map`.
- Produces:
  - `view.element_marks(r: Row, fmap: FigureMap | None) -> Json`
  - `pin_view(r, shown, rel, est, doc, now, fmap: FigureMap | None = None)`
  - `pins_payload(rows, allp, rel, show, doc_of, est_context, now, figure_map: Callable[[str], FigureMap | None] = no_figure_maps)`
  - `no_figure_maps(key: str) -> None`
  - `ListingDeps.doc_figure_map(key) -> FigureMap | None`

**Cache strategy.** `pins_payload` asks for a document's map at most once per request, and only for a document with a listed pin that carries a well-formed `el`, as it already does for `est_context`. Across requests, `Runtime.figure_maps` (Task 5) returns the already parsed map while the build's copy is unchanged. A poll therefore parses nothing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pins_view.py` (imports: `from limn.figmap import FigureMap, MapElement, MapPage`, and `element_marks` from `limn.pins.view`):

```python
FIG = FigureMap(
    "figures.pdf",
    "0" * 64,
    (
        MapPage(
            1,
            "B2",
            None,
            (
                MapElement("B2", None, (0.0, 0.0, 1.0, 1.0), None, None, None, None),
                MapElement("B2/m07", "B2", (0.47, 0.18, 0.07, 0.12), None, None, "MonthCell", "7월"),
            ),
        ),
    ),
)
EL = {"id": "B2/m07", "path": ["B2", "B2/m07"], "frac": [0.47, 0.18, 0.07, 0.12]}


class ElementMarks(unittest.TestCase):
    """element_marks: where a figure pin's element is on its document's current map."""

    def test_an_element_where_it_was_pinned_is_ok_with_its_mark(self):
        """The same page and box as el.frac: ok, with the box as mark and the page."""
        r = {"id": 1, "page": 1, "frac": [0.48, 0.2, 0.04, 0.07], "el": EL}
        self.assertEqual(element_marks(r, FIG), {"mark": [0.47, 0.18, 0.07, 0.12], "mark_page": 1, "el_sync": "ok"})

    def test_a_moved_element_gives_its_new_box_and_a_gone_one_only_lost(self):
        """Pinned at another box: moved, with the box it has now; an id the map lacks: lost and no mark."""
        r = {"id": 1, "page": 1, "el": {**EL, "frac": [0.4, 0.18, 0.07, 0.12]}}
        self.assertEqual(element_marks(r, FIG)["el_sync"], "moved")
        self.assertEqual(element_marks({"id": 1, "page": 1, "el": {"id": "B2/gone", "path": ["B2", "B2/gone"]}}, FIG), {"el_sync": "lost"})

    def test_without_the_elements_box_the_pins_own_frac_is_compared_and_never_ok_by_default(self):
        """An agent's el has no frac and its pin no frac either: the element is found, but never ok."""
        self.assertEqual(
            element_marks({"id": 1, "el": {"id": "B2/m07", "path": ["B2", "B2/m07"]}}, FIG),
            {"mark": [0.47, 0.18, 0.07, 0.12], "mark_page": 1, "el_sync": "moved"},
        )

    def test_nothing_without_a_well_formed_el_or_a_map(self):
        """No el, a malformed el or no loadable map: no fields at all."""
        self.assertEqual(element_marks({"id": 1, "page": 1, "frac": [0, 0, 1, 1]}, FIG), {})
        self.assertEqual(element_marks({"id": 1, "el": {"id": ""}}, FIG), {})
        self.assertEqual(element_marks({"id": 1, "el": EL}, None), {})


class FigurePayload(unittest.TestCase):
    """pins_payload with figure maps: the fields follow the computed ones, each document's map asked once."""

    def test_marks_come_last_and_each_documents_map_is_asked_once_and_only_for_element_pins(self):
        """Two element pins of fig ask its map once; a pin without el and a LaTeX pin get nothing and ask nothing."""
        rows = [
            {"id": 1, "doc": "fig", "page": 1, "el": EL},
            {"id": 2, "doc": "fig", "el": EL},
            {"id": 3, "doc": "ms"},
            {"id": 4, "doc": "fig"},
        ]
        asked = []

        def figure_map(key):
            """Record the question; fig's map."""
            asked.append(key)
            return FIG

        out = pins_payload(rows, False, {}, shown, lambda r: r["doc"], lambda k: CUR, NOW, figure_map)
        self.assertEqual(asked, ["fig"])
        self.assertEqual(list(out[0])[-3:], ["mark", "mark_page", "el_sync"])
        self.assertNotIn("el_sync", out[2])
        self.assertNotIn("el_sync", out[3])
```

Create `src/limn/features/pins/listing/test_figure_pins.py`:

```python
"""Figure pins as the listing reads them through the server: GET /api/pins and /api/pins/{id} carry the read-time
mark, mark_page and el_sync of each pin with an element, computed on the build on screen and never written - a
re-render moves or loses the mark without touching pins.jsonl or rev (docs/handbook/api.md §핀 읽기).

Run: uv run pytest -q src/limn/features/pins/listing/test_figure_pins.py
"""

import json

from limn.access import LOCAL_ACTOR
from limn.documents import Doc

from helpers import Base, add_pin, edit_pin, ps, record_of, req, split_resp
from helpers_access import ALICE_ACTOR, BOB_ACTOR
from helpers_figure import AUGUST, AUGUST_BOX, BUILD1, BUILD2, JULY, JULY_BOX, SCRIPT, b2_map, figure_doc, pin_from_pick, write_build


class FigureBase(Base):
    """A LaTeX document ms and figure document fig with BUILD1 on screen, and three pins on fig: the July cell (a line
    pin with el, Alice), the August cell (a region pin with el, Bob) and lines 20-22 without el (the agent)."""

    def setUp(self):
        """The documents, the build and the three pins."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())
        self.july = pin_from_pick(self.fig, JULY_BOX, ALICE_ACTOR, "글자를 키워 줘")
        self.august = pin_from_pick(self.fig, AUGUST_BOX, BOB_ACTOR, "색을 바꿔 줘")
        self.plain = add_pin({"doc": "fig", "file": SCRIPT, "lo": 20, "hi": 22, "note": "선 굵기"}, dict(LOCAL_ACTOR)).core.pid

    def listed(self):
        """GET /api/pins?all=1 through the handler, by id."""
        code, _, body = split_resp(self.talk(req("GET", "/api/pins?all=1")))
        self.assertEqual(code, 200, body)
        return {p["id"]: p for p in json.loads(body)}


class FigureReadTime(FigureBase):
    """The read-time position fields."""

    def test_each_element_pin_is_marked_where_its_element_is_on_the_build_on_screen(self):
        """Both element pins are ok at their element's box; the pin without el has none of the fields."""
        pins = self.listed()
        self.assertEqual(
            (pins[self.july]["mark"], pins[self.july]["mark_page"], pins[self.july]["el_sync"]), (list(JULY), 1, "ok")
        )
        self.assertEqual((pins[self.august]["mark"], pins[self.august]["el_sync"]), (list(AUGUST), "ok"))
        for key in ("mark", "mark_page", "el_sync"):
            self.assertNotIn(key, pins[self.plain])

    def test_a_re_render_moves_or_loses_the_mark_without_writing_the_pins(self):
        """The July cell moved and the August cell is gone on the new build: moved with the new box, lost without a
        mark - and pins.jsonl is the same bytes, rev still 0."""
        before = ps.APP.C.pins_jsonl.read_bytes()
        write_build(self.fig, BUILD2, b2_map(july=(0.4, 0.18, 0.07, 0.12), august=False))
        pins = self.listed()
        self.assertEqual((pins[self.july]["mark"], pins[self.july]["el_sync"]), ([0.4, 0.18, 0.07, 0.12], "moved"))
        self.assertEqual(pins[self.august]["el_sync"], "lost")
        self.assertNotIn("mark", pins[self.august])
        self.assertEqual([pins[i]["rev"] for i in (self.july, self.august)], [0, 0])
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)

    def test_an_editor_holding_the_pin_saves_after_its_element_is_lost(self):
        """An editor loaded rev before a re-render lost the element: its save with that base_rev is accepted."""
        rev = self.listed()[self.august]["rev"]
        write_build(self.fig, BUILD2, b2_map(august=False))
        self.assertEqual(self.listed()[self.august]["el_sync"], "lost")
        got = edit_pin(self.august, {"note": "색을 바꿔 줘(8월 칸)", "base_rev": rev}, dict(BOB_ACTOR))
        self.assertEqual(record_of(got)["note"], "색을 바꿔 줘(8월 칸)")

    def test_a_build_without_a_loadable_map_drops_the_fields(self):
        """The build on screen has no map copy: no element pin gets the fields."""
        write_build(self.fig, BUILD2, None)
        pins = self.listed()
        for pid in (self.july, self.august):
            self.assertNotIn("el_sync", pins[pid])

    def test_one_pin_by_id_carries_the_fields_too(self):
        """GET /api/pins/{id} is the list's entry: el_sync is there."""
        code, _, body = split_resp(self.talk(req("GET", "/api/pins/%d" % self.july)))
        self.assertEqual((code, json.loads(body)["pin"]["el_sync"]), (200, "ok"))
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest -q tests/test_pins_view.py src/limn/features/pins/listing/test_figure_pins.py`
Expected: `ImportError: cannot import name 'element_marks' from 'limn.pins.view'`, and `KeyError: 'mark'` in the listing tests.

- [ ] **Step 3: Implement**

`src/limn/pins/view.py`: the imports `from limn.figmap import FigureMap, Frac, follow_element`, `from limn.pins.element import element_of` and `from limn.pins.shapes import is_finite_num, is_int, is_num`. Extend the module docstring: "…and for a figure pin with an element, `mark`, `mark_page` and `el_sync` on its document's current map (docs/handbook/api.md §핀 읽기)". Then:

```python
# The box compared with when neither the element nor the pin recorded one: no element's box has zero size, so it is
# never "ok".
NO_FRAC: Frac = (0.0, 0.0, 0.0, 0.0)


def no_figure_maps(key: str) -> None:
    """The figure_map of an instance without figure documents: no document has a map."""
    return None


def element_marks(r: Row, fmap: FigureMap | None) -> Json:
    """The read-time position of pin r's element on its figure document's current map: {} unless r carries a well-formed
    el (limn.pins.element) and fmap is that map; else el_sync (limn.figmap.follow_element) and, when the element is on
    the map, mark ([x, y, w, h]) and mark_page before it. Where the element was when pinned is el.frac (its box then);
    a pin without it is compared by its own frac, and a pin with neither by NO_FRAC, so it is never "ok". The page is
    the pin's page. Never stored; never changes r."""
    el = element_of(r.get("el"))
    if el is None or fmap is None:
        return {}
    frac = r.get("frac")
    then = el.frac
    if then is None and isinstance(frac, list) and len(frac) == 4 and all(is_finite_num(v) for v in frac):
        then = (float(frac[0]), float(frac[1]), float(frac[2]), float(frac[3]))
    page = r.get("page")
    got = follow_element(fmap, el.id, page if is_int(page) else 0, then or NO_FRAC)
    if got.page is None or got.frac is None:
        return {"el_sync": got.sync}
    return {"mark": list(got.frac), "mark_page": got.page, "el_sync": got.sync}
```

`pin_view` and `pins_payload` become:

```python
def pin_view(
    r: Row, shown: Json, rel: list[Json], est: bool, doc: str, now: float, fmap: FigureMap | None = None
) -> Json:
    """One GET /api/pins record: shown (r as the API shows it) followed by rel, est, doc, state, addressed and fyi, in
    that order, then - for a figure pin with an element on fmap, its document's current map - mark, mark_page and
    el_sync (element_marks). A claim that holds at epoch now but was written before claim_ts existed also gets
    claim_ts, its start epoch read from claimed_at (the viewer's "since 20:02 (23 min in)"); none when claimed_at is
    not a readable time. Never changes r or shown."""
    pin = parse_pin(r)
    rec = dict(shown, rel=rel, est=est, doc=doc, state=pin.state, addressed=addressed_to(pin), fyi=fyi_mentions_to(pin))
    rec.update(element_marks(r, fmap))
    if claim_holds(r, now) and not is_num(r.get("claim_ts")):
        ts = epoch(r.get("claimed_at"))
        if ts is not None:
            rec["claim_ts"] = ts
    return rec


def pins_payload(
    rows: Sequence[Row],
    allp: bool,
    rel: Mapping[int, list[Json]],
    show: Show,
    doc_of: Callable[[Row], str],
    est_context: Callable[[str], EstContext | None],
    now: float,
    figure_map: Callable[[str], FigureMap | None] = no_figure_maps,
) -> list[Json]:
    """GET /api/pins: the open pins of rows in row order (every pin when allp), each as pin_view() gives it.

    rel is the overlaps of all rows (limn.pins.position.overlaps_by_id; a listed pin without an entry has []).
    doc_of names a pin's document and est_context gives the estimation facts of a document by key, or None when the
    instance no longer serves it - then est is True (placed on a PDF that is not on screen). est_context is asked
    once per document, and only for documents with a listed pin, since it reads that document's build history.
    figure_map gives a figure document's current map by key (None for another document or one that does not load);
    it is asked at most once per document, and only for a document with a listed pin that carries an el."""
    ctxs: dict[str, EstContext | None] = {}
    maps: dict[str, FigureMap | None] = {}
    out = []
    for r in rows:
        if not (allp or state_of(r) is OpenPin):
            continue
        k = doc_of(r)
        if k not in ctxs:
            ctxs[k] = est_context(k)
        ctx = ctxs[k]
        fmap = None
        if element_of(r.get("el")) is not None:
            if k not in maps:
                maps[k] = figure_map(k)
            fmap = maps[k]
        est = pin_est(r, ctx) if ctx is not None else True
        out.append(pin_view(r, show(r), rel.get(r["id"], []), est, k, now, fmap))
    return out
```

`src/limn/features/pins/listing/service.py`: `from limn.figmap import FigureMap`. `ListingDeps` gains:

```python
    def doc_figure_map(self, key: str) -> FigureMap | None:
        """The loadable map of the build on screen of the figure document key names, or None."""
        ...
```

and `PinListing.pins_payload` passes `self.deps.doc_figure_map` as the last argument of `view.pins_payload`. Docstring: "…with overlap, estimation and figure element positions computed over the full live set."

`tests/test_pins_lifecycle.py` `PURE_IMPORTS`: add `"limn.figmap",  # view.py follows elements on a figure map; pure (P1a's purity test)`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run pytest -q tests/test_pins_view.py tests/test_pins_lifecycle.py src/limn/features/pins/listing tests/test_contract_snapshot.py`
Expected: all pass. The contract snapshot is unchanged, because no pin has an `el`.

- [ ] **Step 5: Break the follow and see the tests catch it (Red)**

Temporarily replace `then or NO_FRAC` with `NO_FRAC` in `element_marks`, so it ignores where the element was pinned. Run: `uv run pytest -q tests/test_pins_view.py src/limn/features/pins/listing/test_figure_pins.py -k "ElementMarks or FigureReadTime"`
Expected: FAIL. `ok` is now reported as `moved` in `test_an_element_where_it_was_pinned_is_ok_with_its_mark` and `test_each_element_pin_is_marked_where_its_element_is_on_the_build_on_screen`. Restore the expression and run again. Expected: pass.

- [ ] **Step 6: Commit**

```bash
uv run ruff format && uv run ruff check && uv run mypy
git add src/limn/pins/view.py src/limn/features/pins/listing/service.py tests/test_pins_view.py tests/test_pins_lifecycle.py src/limn/features/pins/listing/test_figure_pins.py
git commit -s -m "feat(api): read-time mark, mark_page and el_sync for figure pins" -m "GET /api/pins follows each pin's element on its document's current map (el.frac is where it was pinned); nothing is written and a re-render never changes rev. Each document's map is asked once per request and parsed once per build."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 9: `pins.md` figure rows, the figure section title, and the contract snapshot

**Files:**
- Modify: `src/limn/pins/render.py` (`DocHeading` `5d1c4b6:22-35`, `PinFacts` `37-57`, `pins_md_text` `321-507`: the section title at `489-491`)
- Modify: `src/limn/features/pins/listing/markdown.py` (`26-109`, the `DocHeading(...)` construction at `92-95`)
- Modify: `tests/test_pins_render.py`
- Modify: `src/limn/features/pins/listing/test_figure_pins.py`
- Modify: `tests/test_contract_snapshot.py`
- Create: `tests/data/contract_snapshot_figure.json` (recorded)

**Interfaces:**
- Produces:
  - `PinFacts.el_sync: str | None = None`, `PinFacts.impl_location: str | None = None`
  - `DocHeading.has_element_map: bool = False` (after P0's `key, name, path, view_only, builds_from_source, head, built_at`). A section titled `… — 그림(요소 지도)` holds figure pins. A view-only document keeps `— 보기 전용 PDF(줄 번호 없음)`, and the stamp word keeps P0's rule (`빌드` if `builds_from_source`, else `그림`)
  - `render.FIGURE_GUIDANCE`, `element_quote(r) -> str`, `shared_part_md(r, facts) -> str`
  - `MarkdownDeps.doc_figure_map`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pins_render.py`:

```python
EL7 = {
    "id": "B2/calendar/m07",
    "path": ["B2", "B2/calendar", "B2/calendar/m07"],
    "label": "7월",
    "part": "MonthCell",
    "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
    "frac": [0.47, 0.18, 0.07, 0.12],
}


def guidance_line(md):
    """The close-guidance paragraph of pins.md."""
    return next(line for line in md.splitlines() if line.startswith("처리한 핀은 닫는다"))


class FigureRows(unittest.TestCase):
    """A figure pin's pins.md row: lines and kind as any line pin, the element's «label», its shared part and a lost
    element, and one guidance clause while figure pins are open."""

    def test_a_figure_pin_row_shows_its_lines_kind_label_and_shared_part(self):
        """Location and range as the record says; «7월» before the note; the shared part after it, manuscript-relative."""
        r = line_pin(1, file="/ms/figs/src/B2_calendar.py", lo=88, hi=95, scope="el", kind="el:MonthCell", el=EL7, note="글자를 키워 줘")
        md = pins_md_text(page([r], {1: facts(location="figs/src/B2_calendar.py", impl_location="figs/lib/components.py")}))
        self.assertIn(
            "| 1 | 1 | `figs/src/B2_calendar.py L88-L95` | el:MonthCell | «7월» 글자를 키워 줘 ⏎ 공통 부품: figs/lib/components.py:410-470 |",
            md,
        )

    def test_a_lost_element_is_marked_like_a_lost_location(self):
        """el_sync lost: 요소 잃음 in the number cell."""
        md = pins_md_text(page([line_pin(1, scope="el", kind="el:MonthCell", el=EL7)], {1: facts(el_sync="lost")}))
        self.assertIn("| 1 · 요소 잃음 |", md)

    def test_the_figure_clause_needs_an_element_pin(self):
        """Without an element pin the guidance is as before; with one it gains exactly FIGURE_GUIDANCE."""
        plain = guidance_line(pins_md_text(page([line_pin(1)])))
        self.assertNotIn(render.FIGURE_GUIDANCE, plain)
        self.assertEqual(guidance_line(pins_md_text(page([line_pin(1, el=EL7)]))), plain + render.FIGURE_GUIDANCE)

    def test_a_region_pin_with_an_element_takes_the_figure_clause_not_the_view_only_one(self):
        """An element drawn without code is a region pin: «label» before the note, the figure clause, no view-only one."""
        r = {"id": 1, "pdf": "/ms/figs/out/figures.pdf", "page": 1, "frac": [0.55, 0.18, 0.07, 0.12], "kind": "region",
             "quote": "8월", "el": {"id": "B2/calendar/m08", "path": ["B2", "B2/calendar", "B2/calendar/m08"], "label": "8월"},
             "note": "색"}
        md = pins_md_text(page([r]))
        self.assertIn("| 영역 | «8월» 색 |", md)
        self.assertIn(render.FIGURE_GUIDANCE, md)
        self.assertNotIn("보기 전용 PDF 의 핀은 줄 번호가 없다", md)

    def test_an_element_without_a_label_keeps_the_usual_quote_rule(self):
        """No label: the long-line quote rule applies as to any line pin."""
        r = line_pin(1, lo=4, hi=4, quote="q", el={"id": "B2", "path": ["B2"]})
        self.assertIn("«q» note 1", pins_md_text(page([r], {1: facts(line_len=700)})))

    def test_a_figure_section_is_titled_as_a_figure_and_the_view_only_title_is_unchanged(self):
        """A document with an element map gets the title suffix — 그림(요소 지도) and keeps the stamp word 그림 (not
        built from source); a view-only PDF keeps — 보기 전용 PDF(줄 번호 없음) exactly; a LaTeX section gets neither."""
        fg = DocHeading(
            "fig", "그림", "figs/out/figures.limnmap.json", view_only=False, builds_from_source=False,
            head="abc1234", built_at="2026-09-26 10:00", has_element_map=True,
        )
        rv = DocHeading("rv", "리뷰", "review.pdf", view_only=True, builds_from_source=False, head=None, built_at=None)
        region = {"id": 2, "pdf": "/ms/review.pdf", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "kind": "region", "note": "r"}
        rows = [line_pin(1, el=EL7), region, line_pin(3)]
        pin_facts = {1: facts(doc_key="fig"), 2: facts(doc_key="rv", location=""), 3: facts()}
        lines = pins_md_text(page(rows, pin_facts, docs=(MAIN, fg, rv))).splitlines()
        self.assertIn("## 그림 · `fig` · `figs/out/figures.limnmap.json` — 그림(요소 지도)", lines)
        self.assertIn("기준: abc1234 · 그림 2026-09-26 10:00", lines)
        self.assertIn("## 리뷰 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)", lines)
        self.assertIn("## 본문 · `main` · `main.tex`", lines)

    def test_a_heading_without_the_new_field_is_no_figure(self):
        """has_element_map defaults to False: headings built before the field keep their titles."""
        self.assertFalse(MAIN.has_element_map)
```

Append to `src/limn/features/pins/listing/test_figure_pins.py` (with the import `from limn.pins import render`):

```python
class FigureMarkdown(FigureBase):
    """pins.md for the three figure pins, rendered as the store writes it."""

    def md(self, only=None):
        """pins.md over the live pins (only those whose id is in only, when given) - a render, no write."""
        pins = ps.APP.snapshot_pins()
        return ps.APP.pin_markdown.pins_md_text([p for p in pins if only is None or p.core.pid in only])

    def row(self, md, pid):
        """The table row of pin pid."""
        return next(line for line in md.splitlines() if line.startswith("| %d |" % pid) or line.startswith("| %d · " % pid))

    def test_the_figure_section_is_titled_as_a_figure(self):
        """The figure document's subsection title ends with — 그림(요소 지도), never the view-only suffix."""
        lines = self.md().splitlines()
        self.assertIn("## 그림 · `fig` · `figs/out/figures.limnmap.json` — 그림(요소 지도)", lines)
        self.assertFalse(any("보기 전용 PDF(줄 번호 없음)" in line for line in lines))

    def test_rows_name_the_element_and_its_shared_part_manuscript_relative(self):
        """The July row: the script lines, the kind, «7월» and the shared part under figs/; the clause is there."""
        md = self.md()
        row = self.row(md, self.july)
        self.assertIn("| `%s L88-L95` | el:MonthCell | «7월» " % SCRIPT, row)
        self.assertTrue(row.endswith("⏎ 공통 부품: figs/lib/components.py:410-470 |"), row)
        self.assertIn(render.FIGURE_GUIDANCE, md)

    def test_an_agent_pin_without_el_is_a_plain_row_and_brings_no_clause(self):
        """The pin without el has no «…»; rendered alone, pins.md has no figure clause."""
        self.assertNotIn("«", self.row(self.md(), self.plain))
        self.assertNotIn(render.FIGURE_GUIDANCE, self.md(only={self.plain}))

    def test_a_lost_element_is_marked_in_the_number_cell(self):
        """After a re-render without the August cell its row says 요소 잃음."""
        write_build(self.fig, BUILD2, b2_map(august=False))
        self.assertIn("요소 잃음", self.row(self.md(), self.august))

    def test_get_pins_md_renders_on_request_while_the_file_waits_for_a_pin_write(self):
        """A re-render writes no pin, so the pins.md file keeps its last render; GET /pins.md renders on request and
        already says 요소 잃음 (the known limit of the file, docs/handbook/domain.md §알려진 제약)."""
        write_build(self.fig, BUILD2, b2_map(august=False))
        code, _, body = split_resp(self.talk(req("GET", "/pins.md")))
        self.assertEqual(code, 200)
        self.assertIn("요소 잃음", self.row(body.decode("utf-8"), self.august))
        self.assertNotIn("요소 잃음", ps.APP.C.pins_md.read_text(encoding="utf-8"))
```

**Why no fix for the file's freshness is needed.** `GET /pins.md` renders on request. `listing/routes.py` sends `/pins.md` to `http.markdown`, which calls `PinMarkdown.current_text(base)`, which calls `pins_md_text(snapshot_pins(), base)` (`5d1c4b6` `features/pins/listing/markdown.py:56-58`). A remote agent therefore always reads the current `요소 잃음`. The file on disk refreshes on the next pin write and at startup, like its line numbers today, and the index records this as a known limit. A re-render must not trigger a pin transaction just to refresh the file, because rendering never writes pins.

In `tests/test_contract_snapshot.py`:
- Rename the existing class body's shared part into a base class. `ContractSnapshot` currently holds `setUp`, `restore_zone`, `text`, `step` and the test. Move `setUp`, `restore_zone`, `text` and `step` unchanged into `class SnapshotBase(AccessBase)`, with the docstring "The pinned clocks and zone and the recording of one flow's answers (every snapshot test's setup)." Add to it:

```python
    def assert_recorded(self, path: Path) -> None:
        """The answers seen equal the snapshot at path, step by step; LIMN_RECORD_SNAPSHOT=1 writes it first."""
        if os.environ.get("LIMN_RECORD_SNAPSHOT") == "1":
            path.write_text(json.dumps(self.seen, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        recorded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([s["step"] for s in self.seen], [s["step"] for s in recorded])
        for got, want in zip(self.seen, recorded, strict=True):
            self.assertEqual(got, want, got["step"])
```

- Leave `class ContractSnapshot(SnapshotBase)` with only `test_the_pin_flow_answers_as_recorded`, whose last lines (174–179) become `self.assert_recorded(SNAPSHOT)`. Its test id is unchanged.
- Add (imports: `from limn.documents import Doc`, `from limn.features.pins.location import source as pick_source`, `from helpers_figure import AUGUST_BOX, BUILD1, BUILD2, JULY_BOX, SCRIPT, b2_map, figure_doc, write_build`):

```python
FIGURE_SNAPSHOT = Path(__file__).parent / "data" / "contract_snapshot_figure.json"


class FigureContractSnapshot(SnapshotBase):
    """The figure flow, recorded in tests/data/contract_snapshot_figure.json: a map pick and its pin, an agent's pin
    without el, a pick on an element drawn without code and its region pin, pins.md and the pin list, then a re-render
    that moves one element and removes the other (read-time mark and el_sync, 요소 잃음). pdftotext answers no text,
    so the fallback's quote does not depend on the machine."""

    def setUp(self):
        """The pinned clocks; a LaTeX document ms and figure document fig with BUILD1 on screen; the scripts' mtime T0."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())
        for path in (self.fig.src / "src" / "B2_calendar.py", self.fig.src / "lib" / "components.py"):
            os.utime(path, (T0, T0))
        patcher = mock.patch.object(pick_source, "region_text", return_value="")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_figure_pin_flow_answers_as_recorded(self):
        """Every answer and pins.md along the figure flow equal the recorded snapshot."""
        x0, y0, x1, y1 = JULY_BOX
        july = self.step(
            "figure: person picks the July cell",
            "POST",
            "/api/pick",
            {"doc": "fig", "page": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "frac": [0.479, 0.198, 0.049, 0.073], "pdf_build": BUILD1},
            ALICE,
        )
        body = {k: july[k] for k in ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score", "frac", "quote", "pdf_build", "el")}
        body.update(doc="fig", scope=july["default_level"], note="글자를 키워 줘")
        self.step("figure: person pins the element", "POST", "/api/pin", body, ALICE)
        self.step("figure: agent pins lines without el", "POST", "/api/pin", {"file": SCRIPT, "lo": 20, "hi": 22, "note": "선 굵기"})
        x0, y0, x1, y1 = AUGUST_BOX
        august = self.step(
            "figure: person picks the August cell drawn without code",
            "POST",
            "/api/pick",
            {"doc": "fig", "page": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "pdf_build": BUILD1},
            BOB,
        )
        self.step(
            "figure: person pins the August cell as a region",
            "POST",
            "/api/pin",
            {"doc": "fig", "page": 1, "frac": august["frac"], "el": august["el"], "pdf_build": BUILD1, "note": "색을 바꿔 줘"},
            BOB,
        )
        self.step("figure: GET /pins.md", "GET", "/pins.md")
        self.step("figure: GET /api/pins", "GET", "/api/pins")
        write_build(self.fig, BUILD2, b2_map(july=(0.4, 0.18, 0.07, 0.12), august=False))
        self.step("figure: re-rendered, GET /api/pins", "GET", "/api/pins")
        self.step("figure: re-rendered, GET /pins.md", "GET", "/pins.md")
        self.assert_recorded(FIGURE_SNAPSHOT)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest -q tests/test_pins_render.py src/limn/features/pins/listing/test_figure_pins.py -k "FigureRows or FigureMarkdown"`
Expected: `TypeError: PinFacts.__init__() got an unexpected keyword argument 'impl_location'`, `TypeError: DocHeading.__init__() got an unexpected keyword argument 'has_element_map'`, and `AttributeError: module 'limn.pins.render' has no attribute 'FIGURE_GUIDANCE'`.

- [ ] **Step 3: Implement the renderer**

`src/limn/pins/render.py`: `from limn.pins.element import element_of`. `PinFacts` gains two last fields, and its docstring gains "el_sync: a figure pin's element on its document's current map ('ok' | 'moved' | 'lost'), None for another pin or when the map does not load. impl_location: the file of the element's shared part relative to --manuscript, None when it has none.":

```python
    el_sync: str | None = None
    impl_location: str | None = None
```

After `REPLY_GUIDANCE`:

```python
# The guidance clause pins.md adds while figure pins (pins with an el) are open (docs/handbook/api.md §pins.md 형식).
FIGURE_GUIDANCE = (
    " · 그림 핀(메모 앞 «요소 이름»)의 위치 칸은 그 요소를 그린 코드 줄이다 — 그 줄을 고친다 · "
    "'공통 부품: 파일:줄' 은 여러 그림이 함께 쓰는 정의라, 요청이 공통 모양에 관한 것이면 한 그림만 덮어쓰지 말고 사람에게 묻는다 · "
    "닫기 전에 그림 저장소에서 그림을 다시 렌더한다(그림 문서에는 /api/rebuild 가 없다) · "
    "'요소 잃음' = 지금 그림의 지도에 그 요소가 없다, 추측해 닫지 말고 보고한다 · "
    "위치 칸이 쪽·영역뿐인 그림 핀은 코드 없이 그린 요소다 — 고칠 곳을 못 찾으면 닫지 말고 보고"
)


def element_quote(r: Record) -> str:
    """A figure pin's element name in front of its note, «label» - always, with no length condition, when the pin has
    a well-formed el with a label; "" otherwise (docs/handbook/api.md §pins.md 형식)."""
    el = element_of(r.get("el"))
    return "«%s» " % md_cell(el.label) if el is not None and el.label else ""


def shared_part_md(r: Record, facts: PinFacts) -> str:
    """'공통 부품: <file>:<lo>-<hi>' for a figure pin whose element names its shared implementation (el.impl): the file as
    facts.impl_location gives it (relative to --manuscript, like the location column), else as stored; "" otherwise."""
    el = element_of(r.get("el"))
    if el is None or el.impl is None:
        return ""
    return "공통 부품: %s:%d-%d" % (md_cell(facts.impl_location or el.impl.file), el.impl.lo, el.impl.hi)
```

In `pins_md_text`:
- After `if r.get("stale"): syms.append("위치 잃음")`, add `if f.el_sync == "lost": syms.append("요소 잃음")`.
- After `note = md_cell(r.get("note") or "", newline=" ⏎ ")`, add:

```python
        part = shared_part_md(r, f)
        if part:
            note = (note + " ⏎ " if note else "") + part
```

- Replace `q = render_quote(r, f)` and its `if q:` block with:

```python
        eq = element_quote(r)
        q = eq or render_quote(r, f)
        if q and not eq:  # the legend explains «…» as rendered text; a figure's «label» is explained by FIGURE_GUIDANCE
            any_symbol = True
        if q:
            note = q + note
```

- Count the two kinds of pins:

```python
    n_region = sum(1 for r in openn if is_region_pin(r) and element_of(r.get("el")) is None)
    n_el = sum(1 for r in openn if element_of(r.get("el")) is not None)
```

- After the `if n_region:` clause, add `if n_el: guidance += FIGURE_GUIDANCE`.
- `DocHeading` gains a last field `has_element_map: bool = False`. Its docstring gains: "has_element_map: a figure document (Doc.has_element_map) - its section title says '— 그림(요소 지도)': its pins are lines of the drawing code, re-rendered in the figure repository and never rebuilt." The default keeps every heading built without it a non-figure. The one production carrier, `markdown.py`, always passes it.
- The section title (P0's `if d.view_only:` at `5d1c4b6` `render.py:490-491`) becomes the lines below. The stamp line after it (`"빌드" if d.builds_from_source else "그림"`) is unchanged:

```python
        title = "## %s · `%s` · `%s`" % (md_cell(d.name), d.key, md_cell(d.path))
        if d.view_only:
            title += " — 보기 전용 PDF(줄 번호 없음)"
        elif d.has_element_map:
            title += " — 그림(요소 지도)"
```

- Extend the docstring of `pins_md_text`: "A figure pin (with an el) shows its element's «label» before the note, its shared part after it and 요소 잃음 when the element is lost; while any is open, the guidance gains FIGURE_GUIDANCE, and region pins with an el do not count as view-only ones. A figure document's section title ends with — 그림(요소 지도)."

`src/limn/features/pins/listing/markdown.py`: in the `DocHeading(...)` construction (`5d1c4b6` `markdown.py:92-95`, P0's keyword form), add `has_element_map=d.has_element_map`. Add the imports `from limn.documents import Doc, doc_by_key`, `from limn.figmap import FigureMap`, `from limn.locate import PinLocation, doc_scope`, `from limn.pins.element import element_of` and `from limn.pins.view import element_marks`. `MarkdownDeps` gains:

```python
    def doc_figure_map(self, key: str) -> FigureMap | None:
        """The loadable map of the build on screen of the figure document key names, or None."""
        ...
```

In `pins_md_input`, the loop over the pins (`5d1c4b6` `markdown.py:77-91`) becomes the one below. Add "and figure-element" to the docstring's list of rules, and "(each figure document's current map read at most once per render)" after it:

```python
        maps: dict[str, FigureMap | None] = {}
        for pin in pins:
            r = pin.record
            if state_of(r) is DonePin:
                continue
            location, line_len = self._location_and_line_len(pin, sources)
            doc_key = self.deps.pin_doc_key(r)
            el_sync, impl_location = self._element_facts(r, doc_key, maps)
            facts[r["id"]] = PinFacts(
                doc_key=doc_key,
                location=location,
                line_len=line_len,
                badge=rel_badge(rel.get(r["id"], []), by_id, r),
                reopened=pin_reopened_in_round(pin.core.thread),
                addressed=tuple(addressed_to(pin)),
                fyi=tuple(fyi_mentions_to(pin)),
                round=tuple(thread_round(pin.core.thread)),
                el_sync=el_sync,
                impl_location=impl_location,
            )
```

Add the method:

```python
    def _element_facts(
        self, r: Record, doc_key: str, maps: dict[str, FigureMap | None]
    ) -> tuple[str | None, str | None]:
        """A figure pin's facts for its row: el_sync on its document's current map (asked at most once per document per
        render, kept in maps) and its shared part's file relative to --manuscript (impl.file lies in the document's
        folder, doc_scope). (None, None) for a pin without a well-formed el."""
        el = element_of(r.get("el"))
        if el is None:
            return None, None
        if doc_key not in maps:
            maps[doc_key] = self.deps.doc_figure_map(doc_key)
        sync = element_marks(r, maps[doc_key]).get("el_sync")
        impl = None
        if el.impl is not None:
            scope = doc_scope(doc_by_key(self.deps.docs, doc_key), self.deps.C.src)
            impl = scope + "/" + el.impl.file if scope else el.impl.file
        return sync, impl
```

- [ ] **Step 4: Run the render and listing tests**

Run: `uv run pytest -q tests/test_pins_render.py src/limn/features/pins/listing tests/test_server.py tests/test_access.py`
Expected: all pass. Existing `pins.md` bytes are unchanged (`tests/test_access.py`'s v0.1 comparison passes).

- [ ] **Step 5: Record the figure snapshot and check it**

Run: `LIMN_RECORD_SNAPSHOT=1 uv run pytest -q tests/test_contract_snapshot.py -k FigureContractSnapshot`
Expected: `1 passed`, and `tests/data/contract_snapshot_figure.json` is written.

Check the recording against the contract:
```bash
git diff --exit-code tests/data/contract_snapshot.json && echo LATEX-SNAPSHOT-UNCHANGED
python3 - <<'EOF'
import json
steps = {s["step"]: s["body"] for s in json.load(open("tests/data/contract_snapshot_figure.json", encoding="utf-8"))}
pick = json.loads(steps["figure: person picks the July cell"])
assert (pick["via"], pick["kind"], pick["default_level"], pick["el"]["id"]) == ("map", "el:MonthCell", "el", "B2/calendar/m07")
d7 = json.loads(steps["figure: person picks the August cell drawn without code"])
assert d7["kind"] == "region" and d7["el"]["id"] == "B2/calendar/m08" and d7["warn"].startswith("이 요소를 그린 코드 줄")
after = {p["id"]: p for p in json.loads(steps["figure: re-rendered, GET /api/pins"])}
assert sorted(p.get("el_sync") for p in after.values() if "el" in p) == ["lost", "moved"]
assert "요소 잃음" in steps["figure: re-rendered, GET /pins.md"] and "공통 부품: figs/lib/components.py:410-470" in steps["figure: GET /pins.md"]
assert "## 그림 · `fig` · `figs/out/figures.limnmap.json` — 그림(요소 지도)" in steps["figure: GET /pins.md"].splitlines()
print("FIGURE-SNAPSHOT-OK")
EOF
```
Expected: `LATEX-SNAPSHOT-UNCHANGED` and `FIGURE-SNAPSHOT-OK`. Read the JSON diff once by eye before committing. It is the contract addition.

Then run: `uv run pytest -q tests/test_contract_snapshot.py`
Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
uv run ruff format && uv run ruff check && uv run mypy
git add src/limn/pins/render.py src/limn/features/pins/listing/markdown.py tests/test_pins_render.py src/limn/features/pins/listing/test_figure_pins.py tests/test_contract_snapshot.py tests/data/contract_snapshot_figure.json
git commit -s -m "feat(pins.md): figure rows, 요소 잃음 and one guidance clause" -m "A figure pin's row shows the element «label», its shared part (manuscript-relative) and 요소 잃음; a guidance clause appears while figure pins are open. The contract snapshot gains a figure flow in its own file; the LaTeX snapshot is unchanged."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 10: SKILL (en/ko) — figure pin rules and the rebuild rule

**Files:**
- Modify: `skill/SKILL.md`, `skill/SKILL.ko.md` (same commit)

- [ ] **Step 1: Write the failing check**

Append to `tests/test_pins_render.py`, next to `test_skill_symbol_table_uses_words`:

```python
    def test_skill_teaches_figure_pins_and_rebuilds_only_latex(self):
        """Both SKILLs: the 요소 잃음 marker row, the figure pin rule tied to the section title — 그림(요소 지도), and a
        rebuild rule keyed on kind "tex"."""
        for path, head, end, words in (
            (SKILL_MD, "### Markers in the number column", "### Rules", ('kind` in `GET /api/docs` is `"tex"`', "figure repository", "— 그림(요소 지도)")),
            (SKILL_KO, "### 번호 칸의 표시", "### 규칙", ('`kind` 가 `"tex"`', "그림 저장소", "— 그림(요소 지도)")),
        ):
            skill = path.read_text(encoding="utf-8")
            self.assertIn("| `요소 잃음` |", skill[skill.index(head) : skill.index(end)])
            for w in words:
                self.assertIn(w, skill)
            self.assertNotIn("View-only documents have no rebuild.", skill)
            self.assertNotIn("보기 전용 문서는 재빌드가 없다.", skill)
```

Run: `uv run pytest -q tests/test_pins_render.py -k skill`
Expected: 1 failed.

- [ ] **Step 2: Edit `skill/SKILL.md`**

- Front-matter `description`: replace "turns a region picked on a LaTeX manuscript PDF into a .tex file:line range" with "turns a region picked on a LaTeX manuscript PDF - or on a figure drawn by code - into a source file:line range". Replace "point at a spot in the manuscript PDF instead" with "point at a spot in the manuscript PDF or a figure instead".
- Glossary: add after the **view-only document** row:

```markdown
| **figure document** | A figure drawn by code, served as one PDF page per figure with an element map from the figure repository (`kind: "figure"` in `GET /api/docs`). Its pins are line pins on the drawing script and name the element (`el`). |
```

- "What you may do": `- Rebuild the PDF after editing (§Rules).` → `- Rebuild a LaTeX document's PDF after editing (§Rules).`
- Processing pins, step 1: add after the view-only bullet:

```markdown
   - **Figure pins** (a subsection whose title ends with `— 그림(요소 지도)`, "figure (element map)"): the location is the drawing script's `<file> L<lo>-L<hi>` - the call that drew the element - and the range is the element kind (`el:MonthCell`, `figure`). The note starts with the element's name `«label»`; `공통 부품: <file>:<lo>-<hi>` ("shared part") after the note is the shared component's definition. A figure pin whose location is `쪽 N, 영역 …` is an element drawn without code: work out the place from the page, the name and the note; if you cannot, do not close it; report it.
```

- Markers table: add after the `위치 잃음` row, and change the `«…»` row:

```markdown
| `요소 잃음` | The figure pin's element is no longer in the figure's current map ("element lost": a re-render gave it another id or removed it) | Do not close by guessing; report it |
| `«…»` | Quote of the rendered text (≤60 chars, `…` if truncated); on a figure pin, the element's name | Use only as a search hint; never as `Edit`'s `old_string` |
```

- Rules: replace the last bullet (the rebuild rule) with these two bullets:

```markdown
- Rebuild after editing only a document whose `kind` in `GET /api/docs` is `"tex"`: `POST /api/rebuild?async=1&doc=<key>` (omit `doc` for a single document). Picks on an old PDF map to wrong line numbers. View-only PDFs (`"pdf"`) and figure documents (`"figure"`) have no rebuild; `POST /api/rebuild` answers them `400`.
- Figure pins (every pin in a subsection titled `… — 그림(요소 지도)`): edit the lines in the location column (the call that drew the element). If the request is about a shared look - the element's `공통 부품` would change every figure that uses it - ask the human instead of patching one figure. Before closing, re-render the figure in the figure repository (its own command, e.g. `make figures`) and commit it, so the human sees the fixed figure; Limn picks up the new PDF and map by itself.
```

- Common API: the `POST /api/rebuild?async=1` row becomes "Rebuild a LaTeX document's PDF (`kind: "tex"` only; figure and view-only documents answer `400`); progress at `GET /api/build`. With several documents add `&doc=<key>` to both". The `GET /api/docs` row becomes "Document list (key, name, kind `tex`/`pdf`/`figure`, open pin count, build state)".

- [ ] **Step 3: Edit `skill/SKILL.ko.md` the same way**

- `description`: replace "LaTeX 원고 PDF에서 드래그로 고른 영역을 SyncTeX 역변환으로 .tex 파일·줄 범위와 요청 메모(핀)로 받는다" with "LaTeX 원고 PDF나 코드로 그린 그림에서 드래그로 고른 영역을 원본 파일·줄 범위와 요청 메모(핀)로 받는다". Replace "원고 PDF의 특정 위치를 지목하려 할 때" with "원고 PDF나 그림의 특정 위치를 지목하려 할 때".
- 용어: add after **보기 전용 PDF**:

```markdown
| **그림 문서** | 코드로 그린 그림을 그림 한 장 = PDF 한 쪽으로 요소 지도와 함께 받는 문서(`GET /api/docs` 의 `kind: "figure"`). 핀은 그림 스크립트의 줄 핀이고 요소(`el`)를 적는다. |
```

- 해도 되는 것: `- 고친 뒤 PDF를 재빌드한다(§규칙).` → `- 고친 뒤 LaTeX 문서의 PDF를 재빌드한다(§규칙).`
- 핀 처리 1단계, after the 보기 전용 PDF bullet:

```markdown
   - **그림 핀**(제목이 `— 그림(요소 지도)` 로 끝나는 소절): 위치 칸은 그 요소를 그린 호출, 곧 그림 스크립트의 `<파일> L<lo>-L<hi>` 이고 범위 칸은 요소 종류(`el:MonthCell`, `figure`)다. 메모 앞 `«…»` 는 요소 이름이고, 메모 뒤 `공통 부품: <파일>:<lo>-<hi>` 는 공통 부품의 정의다. 위치 칸이 `쪽 N, 영역 …` 인 그림 핀은 코드 없이 그린 요소다. 쪽·요소 이름·메모로 고칠 곳을 찾고, 못 찾으면 닫지 말고 보고한다.
```

- 번호 칸의 표시: after the `위치 잃음` row, and change `«…»`:

```markdown
| `요소 잃음` | 그림 핀의 요소가 지금 그림의 지도에 없다(다시 렌더하며 id가 바뀌었거나 빠짐) | 추측해 닫지 말고 보고한다 |
| `«…»` | 렌더된 글자 인용(≤60자, 잘리면 `…`). 그림 핀에서는 요소 이름 | 검색 힌트로만 쓴다. `Edit` 의 `old_string` 으로 쓰지 않는다 |
```

- 규칙: replace the last bullet with:

```markdown
- 원고를 고친 뒤 재빌드는 `GET /api/docs` 의 `kind` 가 `"tex"` 인 문서만 한다: `POST /api/rebuild?async=1&doc=<키>`(단일 문서는 `doc` 생략). 옛 PDF 위의 pick 은 줄 번호가 어긋난다. 보기 전용 PDF(`"pdf"`)와 그림 문서(`"figure"`)는 재빌드가 없고 `POST /api/rebuild` 는 `400` 이다.
- 그림 핀(제목이 `… — 그림(요소 지도)` 인 소절의 핀): 위치 칸의 줄(그 요소를 그린 호출)을 고친다. 요청이 공통 모양에 관한 것이면 — 요소의 `공통 부품` 을 고치면 그 부품을 쓰는 그림이 모두 바뀐다 — 한 그림만 덮어쓰지 말고 사람에게 묻는다. 닫기 전에 그림 저장소에서 그림을 다시 렌더하고(그 저장소의 명령, 예: `make figures`) 커밋한다. 그래야 사람이 고친 그림을 본다. 새 PDF와 지도는 Limn 이 알아서 가져온다.
```

- 자주 쓰는 API: `POST /api/rebuild?async=1` → "LaTeX 문서의 PDF 재빌드(`kind: "tex"` 만. 그림·보기 전용 문서는 `400`). 진행은 `GET /api/build`. 여러 문서면 둘 다 `&doc=<키>`". `GET /api/docs` → "문서 목록(키·이름·종류 `tex`/`pdf`/`figure`·열린 핀 수·빌드 상태)".

- [ ] **Step 4: Run the checks**

Run: `uv run pytest -q tests/test_pins_render.py tests/test_naming.py` and then `uv run pytest -q tests/test_server.py tests/test_viewer.py -k "skill or Skill or rebuild"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add skill/SKILL.md skill/SKILL.ko.md tests/test_pins_render.py
git commit -s -m "docs(skill): figure pin rules; rebuild only kind tex documents" -m "Both SKILLs teach figure pins (edit the drawing lines, ask before changing a shared part, re-render in the figure repository before closing, 요소 잃음) and key the rebuild rule on kind tex instead of view-only."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 11: Handbook, CHANGELOG, the index check, and the full gate

**Files:**
- Modify: `docs/handbook/domain.md`, `docs/handbook/api.md`, `docs/handbook/index.md`, `docs/handbook/verification.md`
- Modify: `CHANGELOG.md`
- Check (no edit): `docs/superpowers/plans/2026-09-30-figure-documents.md` (§Shared contract and §Contract amendments at handover already carry §Contract issues)

- [ ] **Step 1: `docs/handbook/domain.md`**

1. 용어 table, after **보기 전용 PDF**. Add the rows below. If P1a already wrote a row for the same term, replace it with this text:

```markdown
| **그림 문서** | 코드로 그린 그림(벡터 그래픽)을 그림 한 장 = PDF 한 쪽으로 받는 문서다(`kind:"figure"`). 그림 저장소가 PDF와 요소 지도를 내고 Limn은 가져와 보여 준다. 핀은 그림을 그린 코드의 줄 핀이다. |
| **요소 지도** | 그림 문서의 쪽마다 요소 목록을 적은 파일이다(`limn-figure-map/1`). 요소 id, 쪽 위 영역, 그 요소를 그린 코드의 파일·줄을 담는다. 빌드마다 쪽 폴더에 사본이 있다. |
| **요소(`el`)** | 그림 핀이 가리키는 지도의 요소다. 핀 레코드의 선택 필드 `el`에 id·경로·이름·공통 부품·영역을 적는다. |
```

2. §역변환이 두 경로인 이유, append:

```markdown
그림 문서에는 SyncTeX도 되짚을 원문 글자도 없다. 대신 그림을 그린 코드가 요소마다 쪽 위 영역과 호출 줄을 요소 지도에 적어 둔다. 그래서 그림 문서의 pick은 두 경로를 경쟁시키지 않고 지도로 되짚으며, 이때 `via`는 `map`이다(§그림 문서의 요소 pick).
```

3. §범위 사다리: the `level` table gains two rows after `env…`:

```markdown
| `el`, `el2` … `el8` | 그림 문서에서 고른 요소와 그 조상 요소를 안쪽부터 최대 8단까지(`LADDER_MAX`) |
| `fig` | 그림 문서의 뿌리 요소, 곧 그림 전체 |
```

and after "section 단계는 두지 않는다…", add:

```markdown
그림 문서의 사다리는 고른 요소에서 뿌리까지 올라간다. 단계의 줄 범위는 그 요소의 `src`이고, 이름(`label`)은 요소의 `label`, 없으면 `part`, 없으면 id다. 한 사다리의 단계는 모두 고른 요소의 `src`와 같은 파일에 있다. 단계를 바꿔도 파일이 바뀌지 않게 하려는 것이다. 그래서 다른 파일에서 그린 조상과, 줄 범위가 지금 파일 길이를 넘는 조상은 단계에서 빠진다. 줄 범위가 같은 단계는 하나로 합친다. LaTeX와 달리 안쪽 단계가 남고 바깥 이름이 `merged`에 들어간다. 안쪽 요소가 사람이 드래그한 자리에 더 가깝기 때문이다. 기본 단계는 고른 요소의 단계 `el`이고, 그림 전체를 골랐으면 `fig`다. 단계마다 그 요소의 `el`이 붙어 있어서, 단계를 바꾸면 핀이 가리키는 요소도 함께 바뀐다. 실행 정본은 [`src/limn/features/pins/location/figure.py`](../../src/limn/features/pins/location/figure.py)의 `element_rungs`와 `limn/figmap.py`의 `ladder_scopes`다.
```

4. New section after §범위 사다리:

```markdown
## 그림 문서의 요소 pick

그림 문서의 `POST /api/pick`은 드래그한 빌드(`pdf_build`)의 쪽 폴더에 있는 지도 사본으로 되짚는다. 그 사이 다시 렌더해 요소가 옮겼어도 사람이 화면에서 본 요소가 잡힌다.

요소 `E`마다 드래그 영역 `D`에 대해 두 비율을 잰다.

| 비율 | 뜻 |
| --- | --- |
| `cover = \|E∩D\| / \|D\|` | 드래그가 요소 안에 든 몫이다. 넓이가 없는 드래그(클릭)는 그 가운데 점으로 보고, 그 점을 품은 요소면 1, 아니면 0이다 |
| `fill = \|E∩D\| / \|E\|` | 요소가 드래그에 덮인 몫이다 |

고르는 순서는 다음과 같다. 1·2단계에는 쪽의 뿌리 요소가 끼지 않는다. 뿌리는 쪽 전체라서 늘 드래그를 품기 때문이다.

1. `cover ≥ 0.6`(`COVER_MIN`)인 요소 가운데 가장 깊은 것을 고른다. 깊이가 같으면 영역이 작은 것, 그다음 지도 순서가 앞선 것이다. 그래서 작은 드래그와 클릭은 잎 요소로 간다.
2. 그런 요소가 없으면 드래그가 여러 요소에 걸친 경우다. `fill ≥ 0.5`(`FILL_MIN`)인 요소들의 가장 가까운 공통 조상을 고른다.
3. 그것도 없으면 뿌리, 곧 그림 전체다.

`score`는 고른 요소의 `cover`다. 0.3 미만이면 원고 pick처럼 약한 일치 경고를 붙인다. 판단은 파일을 모르는 [`limn/figmap.py`](../../src/limn/figmap.py)의 `pick_element`가 한다. 지도 사본을 받고 코드 줄을 읽는 쪽은 [`features/pins/location/figure.py`](../../src/limn/features/pins/location/figure.py)다. 줄은 원고 트리 안이면서 문서 폴더 안인 파일에서만 읽는다(`file_in_tree`, `tree_part`). 지도 사본은 실행마다 빌드 하나에 한 번만 파싱한다([`limn/build.py`](../../src/limn/build.py)의 `BuildMapCache`).

**줄을 줄 수 없으면 영역으로 떨어진다.** 두 경우가 있다.

| 이유 | 언제 |
| --- | --- |
| `figure_map_unavailable` | 그 빌드에 지도 사본이 없거나, 검사를 어겼거나, 그 쪽이 지도에 없다 |
| `element_without_source` | 고른 요소에 `src`가 없거나(코드 없이 그린 벡터 그래픽), 그 파일을 문서 폴더 안에서 읽지 못하거나, 줄 범위가 지금 파일 길이를 넘는다 |

두 경우 모두 보기 전용 PDF와 같은 영역 답을 돌려주고, `warn` 앞에 이유 문장을 놓는다. 요소를 골랐으면 영역 답에도 `el`을 싣는다. 줄 범위가 파일을 넘는 것은 그림을 렌더한 뒤 스크립트가 바뀐 경우다. 그림을 다시 렌더하면 풀린다.
```

5. §줄 번호 재동기화: replace "순수 주석 줄은 건너뛰고 뜬다." with:

```markdown
순수 주석 줄은 건너뛰고 뜬다. 주석 줄은 파일의 종류로 가린다. 파이썬 스크립트(`.py`, 그림을 그린 코드)는 `#`으로 시작하는 줄이고, 그 밖의 파일은 LaTeX처럼 `%`로 시작하는 줄이다(`mapping.comment_marker`).
```

   Replace "줄 맞춤은 열린 LaTeX 핀에만 한다. 닫힌 핀과 보기 전용 PDF 핀은 건너뛴다." with "줄 맞춤은 열린 줄 핀(LaTeX 핀과 그림 핀)에만 한다. 닫힌 핀과 영역 핀은 건너뛴다." At the end of the section, add a subsection:

```markdown
### 그림 핀의 요소 위치 — 읽을 때 계산한다

그림 핀의 줄은 위의 anchor로 따라간다. 다시 렌더해 요소가 쪽 위에서 자리를 옮기는 것은 따로 따라가며, 이것은 저장하지 않고 읽을 때 계산한다. `GET /api/pins`는 `el`이 있는 핀마다 그 문서의 지금 빌드 지도에서 `el.id`를 찾아(`figmap.follow_element`) 필드를 붙인다.

| 결과 | `el_sync` | 붙는 필드 |
| --- | --- | --- |
| 찍은 때와 같은 쪽, 같은 영역(값마다 차이 `1e-4` 이하) | `ok` | `mark`, `mark_page` |
| 다른 영역이나 다른 쪽 | `moved` | `mark`, `mark_page`(새 자리) |
| 지도에 그 id가 없다 | `lost` | 없음 |

찍은 때의 영역은 `el.frac`, 곧 찍을 때 그 요소의 영역이다. 이것이 없는 핀(에이전트가 만든 핀)은 핀의 `frac`과 비교하므로 `ok`가 되지 않는다. 지도를 읽지 못하면 세 필드가 모두 없다. 계산은 순수 함수 [`pins/view.py`](../../src/limn/pins/view.py)의 `element_marks`이고, 지도는 조립 지점이 문서마다 한 번 넘긴다.

저장하지 않는 이유는 둘이다. 트랜잭션 안에서 `frac`·`page`를 고쳐 쓰면 `rev`가 올라, 편집 중인 사람의 저장이 `409`로 거절된다. 또 옛 서버로 되돌려도 레코드는 찍은 때의 값 그대로 남는다. 그래서 다시 렌더해도 핀 파일은 쓰이지 않고 `rev`도 오르지 않는다.
```

6. §여러 문서: after `### 보기 전용 PDF`, add the subsection below. If P1a added a `### 그림 문서` subsection, keep its import sentences and replace its pick/pin sentences with this text:

```markdown
### 그림 문서

그림 문서(`kind:"figure"`)는 빌드가 보기 전용 PDF처럼 가져오기이고, 핀은 LaTeX처럼 줄 핀이다. 그래서 문서 종류 하나가 아니라 능력 값으로 가른다(`Doc.builds_from_source`·`watches_files`·`takes_line_pins`·`has_element_map`). 그림 문서는 줄 핀을 받고(`takes_line_pins`) 재빌드하지 않는다.

- 핀은 그림을 그린 스크립트의 `file`·`lo`·`hi`에 선택 필드 `el`을 더한 줄 핀이다. 줄 검증과 anchor 재동기화를 LaTeX 핀과 똑같이 받는다. 그래서 그림을 모르는 에이전트도 줄 핀으로 처리할 수 있다.
- 코드 없이 그린 요소를 고르면 영역 핀(`pdf`·`page`·`frac`)에 `el`을 더한다.
- `doc` 없이 `file`만 온 요청(에이전트의 `curl`)은, 줄 핀을 받는 문서 가운데 그 파일을 가장 깊게 감싸는 문서 폴더의 문서로 간다. 그림 폴더가 LaTeX 문서의 빌드 루트 안에 있으면 그림 문서가 이긴다.
- `POST /api/rebuild`는 `400`이다. 그림은 그림 저장소에서 다시 렌더한다.
```

7. §알려진 제약: add a subsection after §줄 맞춤의 한계:

```markdown
### 그림 핀의 한계

- **요소 id가 렌더마다 같아야 따라간다.** 생산자가 같은 요소에 다른 id를 주면 그 핀은 `요소 잃음`이 된다.
- **`pins.md`의 `요소 잃음`은 그 파일을 렌더한 때의 지도 기준이다.** 파일은 핀을 쓸 때마다 다시 렌더된다. 다시 렌더만 하고 핀을 쓰지 않았으면 `GET /pins.md`와 `GET /api/pins`가 지금 값을 준다.
- **그림 핀은 위치 다시 잡기로 영역 핀과 줄 핀 사이를 오가지 않는다.** 영역 핀의 `loc` 은 영역만, 줄 핀의 `loc` 은 줄만 받는다. 코드가 생기거나 사라졌으면 새로 찍는다. 같은 모양 안에서 `loc` 에 `el` 이 없으면 핀의 `el` 은 지워진다.
- **그림 문서의 `/api/snippet?levels=1` 사다리는 `raw` 단계 하나다.** 문단·환경 단계는 LaTeX 규칙이라 코드에 뜻이 없고, 요소 사다리는 pick 답에만 있다. 편집 카드에서 줄을 조정해도 핀의 `el` 은 `loc` 이 바꾸기 전까지 그대로다.
- **옛 서버로 되돌린 동안 그림 핀의 위치를 다시 잡으면 `el`이 옛 요소 그대로 남는다.** 옛 서버는 `el`을 모르는 필드로 그대로 두기 때문이다. 다시 올리면 `mark`가 옛 요소를 따라간다. 사람이 위치를 다시 잡으면 풀린다.
```

- [ ] **Step 2: `docs/handbook/api.md`**

1. §오류 응답 table, row 핀 입력: add `` `bad_el` `` after `` `bad_scope` ``.
2. §문서 매개변수: "서버는 그 파일을 빌드 루트가 가장 깊게 감싸는 LaTeX 문서를 고른다." → "서버는 줄 핀을 받는 문서(LaTeX 문서와 그림 문서) 가운데 그 파일을 가장 깊게 감싸는 문서 폴더의 문서를 고른다."
3. §엔드포인트:
   - `/api/docs`: the kind reads `kind:"tex"\|"pdf"\|"figure"`, and after the list add the sentence "그림 문서의 `view_only` 는 `false` 다(줄 핀을 받는다)."
   - `/api/pins`: after "`state`(§검토 대기)가 채워진다" add "`el` 이 있는 그림 핀에는 `mark`·`mark_page`·`el_sync` 도 붙는다(§그림 문서의 pick·핀)".
   - `/api/pick`: at the end of the cell add "그림 문서의 답은 §그림 문서의 pick·핀".
   - `/api/snippet`: after "`&levels=1` 이면 그 범위를 기준으로 한 범위 사다리도 준다" add "(그림 문서의 파일이면 `raw` 단계 하나. §그림 문서의 pick·핀)".
   - `/api/pin`: the whitelist ends `…, pdf_build, el`, and add "`el` 은 그림 문서에서만 저장한다(§그림 문서의 pick·핀)".
4. §핀 수정: `loc: {file, page, lo, hi, raw_lo, raw_hi, kind, via, score, frac, scope, pdf_build}` → `loc: {…, pdf_build, el}`, with the added sentence "`el` 은 위치 필드다. 그림 문서에서만 받고, 다른 위치 필드처럼 `loc` 에 없으면 핀의 `el` 이 지워진다. `lo`·`hi` 만 고치는 편집은 `el` 을 둔다. 영역 핀과 줄 핀은 위치 다시 잡기로 서로 바뀌지 않는다."
5. New section after §보기 전용 PDF 문서의 pick·핀:

```markdown
## 그림 문서의 pick·핀

`kind:"figure"` 문서는 그림 저장소가 낸 PDF와 요소 지도(`limn-figure-map/1`)를 가져온 문서다. 핀은 그림을 그린 코드의 줄 핀이고, 선택 필드 `el` 로 어느 요소인지 적는다. 되짚는 규칙은 [domain.md](domain.md) §그림 문서의 요소 pick 에 있다.

**pick.** 요청 형식은 원고와 같다. 그 빌드(`pdf_build`)의 지도로 줄을 찾으면 원고 pick 과 같은 키를 같은 순서로 주고, 끝에 `el` 을 더한다.

| 필드 | 값 |
| --- | --- |
| `file`·`name`·`lo`·`hi`·`raw_lo`·`raw_hi` | 고른 요소의 `src`, 곧 그림 스크립트에서 그 요소를 부른 줄 |
| `via` | `map` |
| `score` | 고른 요소가 드래그를 품은 몫(`cover`) |
| `kind` | `el:<부품>`(`el:MonthCell`, 부품 이름이 없으면 `el:?`, 부품 이름은 77자에서 자른다). 그림 전체를 골랐으면 `figure` |
| `levels` | 사다리 단계마다 `{level, lo, hi, n, label, snippet, el, merged?}`. `level` 은 `el`·`el2`…`el8`·`fig` |
| `default_level` | `el`. 그림 전체를 골랐으면 `fig` |
| `quote` | 고른 요소의 `label`, 없으면 `""` |
| `el` | `{id, path, label?, part?, impl?: {file, lo, hi}, frac}`. `path` 는 뿌리부터 그 요소까지의 id, `impl` 은 공통 부품(구현)의 줄이고 `impl.file` 은 문서 폴더 기준 상대 경로, `frac` 은 이 빌드에서 그 요소의 영역 `[x, y, w, h]` 다 |
| `warn` | 원고와 같다. 고른 요소의 `score` 가 0.3 미만이면 약한 일치 문장이다 |

줄을 줄 수 없으면 보기 전용 PDF 의 영역 답(`kind:"region"`)을 준다. 이때 `warn` 은 이유 문장으로 시작한다. 지도를 읽지 못하면 `figure_map_unavailable` 문장이고, 고른 요소의 코드 줄을 줄 수 없으면 `element_without_source` 문장이다. 코드 줄을 줄 수 없는 것은 요소에 `src` 가 없거나, 파일을 문서 폴더 안에서 읽지 못하거나, 줄 범위가 지금 파일을 넘는 경우다. 요소를 골랐으면 영역 답에도 `el` 이 붙는다.

**핀 만들기.** `POST /api/pin` 은 두 모양을 받는다.

- 줄 핀: 원고 핀과 같은 필드에 `el` 을 더한다.
- 영역 핀: `file`·`lo`·`hi` 가 없으면 영역 핀이고, 보기 전용 핀과 같은 필드에 `el` 을 더한다.

`el` 은 그림 문서에서만 저장하고, 다른 문서에서는 모르는 필드처럼 버린다. `el` 은 pick 이 준 모양이어야 하고, 어기면 `400 bad_el` 이다.

- `id` 는 비어 있지 않은 문자열이다.
- `path` 는 `id` 로 끝나는 문자열 목록이고 64개 이하다.
- `label`·`part` 는 문자열이다.
- `impl` 은 `{file, lo, hi}` 이다. `file` 은 `..` 가 없는 상대 경로이고 `1 ≤ lo ≤ hi` 다.
- `frac` 은 쪽 안의 숫자 4개다.
- 문자열은 200자 이하다.

`el` 안의 모르는 키는 버린다. `el` 없이 `file`·`lo`·`hi` 만 보낸 에이전트의 핀도 받는다. 그 핀은 요소 없는 줄 핀이다.

**수정.** `el` 은 위치 필드다. `/edit` 의 `loc` 도 `el` 을 받고, 다른 위치 필드처럼 `loc` 에 `el` 이 없으면 핀의 `el` 이 지워진다. `lo`·`hi` 만 고치는 편집은 `el` 을 그대로 둔다. `/edit` 는 영역 핀을 줄 핀으로, 줄 핀을 영역 핀으로 바꾸지 않는다. 코드가 생기거나 사라졌으면 새로 찍는다(§핀 수정 (`/api/pins/{id}/edit`)).

**읽을 때 계산하는 필드.** `GET /api/pins` 와 `/api/pins/{id}` 는 `el` 이 있는 핀에 그 문서의 지금 빌드 지도로 계산한 필드를 붙인다. 이 필드는 저장하지 않고, 다시 렌더해도 `rev` 가 오르지 않는다.

| 필드 | 뜻 |
| --- | --- |
| `mark` | 그 요소의 지금 영역 `[x, y, w, h]` |
| `mark_page` | 그 요소가 지금 있는 쪽 |
| `el_sync` | `ok`(찍은 때 자리), `moved`(옮김), `lost`(지도에 없음. 이때 `mark`·`mark_page` 는 없다) |

지도를 읽지 못하는 핀과 `el` 이 없는 핀에는 세 필드가 모두 없다. 휴지통 목록과 변경 요청의 응답 `pin` 에는 붙지 않는다(`est` 와 같다).

**편집 카드의 사다리.** `GET /api/snippet?levels=1` 은 그림 문서의 파일에 대해 `raw` 단계 하나만 준다(`default_level` 도 `raw`). 문단·환경 단계는 LaTeX 원고의 규칙이라 그림 스크립트에 뜻이 없고, 요소 사다리는 pick 답에만 있다. 이 사다리로 줄을 조정해도 핀의 `el` 은 그대로다.

**그 밖의 경로.** 닫기·claim·drop 은 원고 핀과 같다. `POST /api/rebuild` 는 `400` 이다. 그림은 그림 저장소에서 다시 렌더하고, Limn 이 새 PDF와 지도를 가져와 쪽을 다시 그린다.
```

6. §핀 레코드 스키마 table:
   - `scope`: "`raw\|para\|env\|env2\|env3\|lines`, 그림 핀은 `el\|el2\|…\|el8\|fig`. 저장할 때 고른 범위 사다리 단계다".
   - `kind`: "… `env:<이름>`, `lines`. 그림 핀은 `el:<부품>`(`el:MonthCell`, `el:?`)과 `figure`. 모르는 값은 원문 그대로 둔다".
   - Add these rows after `scope`:

```markdown
| `via` | 범위를 찾은 방법 `synctex\|text\|map`. `map` 은 그림 문서의 요소 지도다 |
| `el` | 그림 핀만 가진다. 가리킨 요소 `{id, path, label?, part?, impl?: {file, lo, hi}, frac?}`(§그림 문서의 pick·핀)다. 모양이 틀리면 그 줄은 깨진 줄이다. 모양이 틀린 경우는 객체가 아니거나, `id` 가 빈 문자열이거나, `path` 가 문자열 목록이 아니거나, `label`·`part` 가 문자열이 아니거나, `impl` 이 `{file: 문자열, lo: 정수, hi: 정수}` 가 아니거나, `frac` 이 숫자 4개가 아닌 때다. 0.3.5 이하 서버는 이 필드를 모르는 필드로 지나치고, 되쓸 때 그대로 둔다 |
```

   - The response-only sentence after the table: add `mark`, `mark_page`, `el_sync` to the list.
7. §pins.md 형식:
   - In §번호 칸의 표시 table, after `위치 잃음`, add `` | `요소 잃음` | 그림 핀의 요소가 지금 그림의 지도에 없다(`el_sync` 가 `lost`) | 추측해 닫지 않고 보고한다 | ``.
   - In §보기 전용 핀의 행, change the last bullet's "보기 전용 핀이 있으면" to "요소(`el`)가 없는 영역 핀이 있으면".
   - In §여러 문서, item 2: after "보기 전용이면 제목 끝에 `— 보기 전용 PDF(줄 번호 없음)` 이 붙는다." add "그림 문서면 `— 그림(요소 지도)` 가 붙는다. `기준:` 줄의 낱말은 그대로(원고에서 빌드하지 않는 문서는 `그림`)다."
   - Add after §보기 전용 핀의 행:

```markdown
### 그림 핀의 행

- 그림 문서의 소절 제목 끝에는 `— 그림(요소 지도)` 가 붙는다. 이 소절의 핀이 그림 핀이다. 그림은 그림 저장소에서 다시 렌더하고 재빌드하지 않는다.
- 위치 칸은 원고 핀처럼 그림 스크립트의 `파일 L<lo>-L<hi>` 다. 범위 칸은 핀의 `kind`(`el:MonthCell`, `figure`)다.
- 메모 앞에 요소 이름 `«label»` 이 늘 붙는다. 한 줄·600자 조건은 없다. `label` 이 있으면 원고 핀의 `«…»` 인용 대신 이것이 붙는다.
- 요소에 공통 부품(`el.impl`)이 있으면 메모 뒤에 ` ⏎ 공통 부품: <파일>:<lo>-<hi>` 가 붙는다. 파일은 위치 칸처럼 `--manuscript` 기준 경로다.
- 요소를 잃은 핀(`el_sync` 가 `lost`)은 번호 칸에 `요소 잃음` 이 붙는다. `pins.md` 를 렌더한 때의 지도 기준이다.
- `el` 이 있는 열린 핀이 있으면 안내 문단에 그림 핀 안내가 붙는다. 줄을 고칠 것, 공통 부품 요청은 사람에게 물을 것, 닫기 전에 그림 저장소에서 다시 렌더할 것, `요소 잃음` 핀은 추측해 닫지 않을 것을 알린다. `el` 이 있는 영역 핀에는 보기 전용 PDF 안내를 붙이지 않는다.
```

- [ ] **Step 3: `docs/handbook/index.md` file map and `verification.md`**

- `src/limn/features/pins/location/*` row, responsibility cell: after "역변환 결과와 판단(`resolve.py`)" insert ", 그림 문서의 지도 pick과 사다리 단계(`figure.py`)".
- `src/limn/build.py` row: after P1a's clause about the per-build map copy (`FIGMAP_NAME`·`load_build_map`), append ", 그 지도 사본의 실행별 파싱 캐시(`BuildMapCache`)".
- `src/limn/pins/*` row: after "JSON 정수·숫자 판정(`shapes.py`)" insert ", 그림 핀의 요소 필드 모양(`element.py`)". After "`view.py`: `public_record`·`state`·`GET /api/pins`·휴지통 본문" add "·그림 핀의 `mark`·`el_sync`".
- `src/limn/mapping.py` row: after "anchor 찾기" insert ", 파일 종류별 주석 줄(`comment_marker`: `.py`는 `#`)".
- The `src/limn/figmap.py` row (P1a added it; add it after `mapping.py` if it is missing) reads in full:

```markdown
| `src/limn/figmap.py` | 그림 문서의 요소 지도(`limn-figure-map/1`) 순수 코드: 파싱과 검사(`parse_map`), 드래그로 요소 고르기(`pick_element`)·사다리 단계 이름(`ladder_scopes`)·요소 종류(`element_kind`), 다시 렌더를 건넌 요소 따라가기(`follow_element`) | 지도 형식·pick 규칙·임계값·따라가기 변경 | domain.md §그림 문서의 요소 pick, api.md §그림 문서의 pick·핀 |
```

- `docs/handbook/verification.md`:
  - §1 table, row `tests/test_contract_snapshot.py`: after "…바이트 단위로 비교한다." add "그림 문서 흐름(지도 pick, 요소 핀, 다시 렌더 뒤의 계산 필드)은 따로 [`tests/data/contract_snapshot_figure.json`](../../tests/data/contract_snapshot_figure.json)과 비교한다."
  - Add a row after `tests/helpers.py`: `` | [`tests/helpers_figure.py`](../../tests/helpers_figure.py) | 그림 문서 fixture: 그림 스크립트·공통 부품·요소 지도·빌드 폴더와, pick 답을 뷰어처럼 저장하는 도우미 | ``.
  - §4 row 실행: "자동: `tests/test_contract_snapshot.py`, `tests/test_pins_model.py`" → "자동: `tests/test_contract_snapshot.py`(원고 흐름과 그림 문서 흐름), `tests/test_pins_model.py`, `tests/test_figure_rollback.py`(직전 릴리스가 그림 핀 레코드를 읽고 바이트 그대로 되쓰는지)".

- [ ] **Step 4: `CHANGELOG.md`**

Under `## Unreleased`, add the bullets below to the `### Added` subsection. If P0/P1a did not create that heading, create it right after the Unreleased intro paragraph:

```markdown
- **Figure pins (unreleased on `main`; ships with the viewer in 0.4.0).** A drag on a figure document is traced through
  its build's element map: `POST /api/pick` answers the lines of the drawing script with `via: "map"`, the element
  ladder (`levels` `el`, `el2` … `el8`, `fig`) and the element `el` (`id`, `path`, `label`, `part`, `impl`, `frac`).
  An element drawn without code, or a figure whose map does not load, answers the region with `el` and a `warn` that
  says why. Pins take the optional `el` (`POST /api/pin`, an edit's `loc`); a malformed one is `400 bad_el`. Figure
  documents take line pins: an agent's `curl` with only a file routes to the deepest document folder, figure or LaTeX.
- **Read-time element position.** `GET /api/pins` adds `mark`, `mark_page` and `el_sync` (`ok`/`moved`/`lost`) to a
  figure pin; nothing is written and a re-render never changes `rev`. Each build's map is parsed once per run.
- **`pins.md` figure rows.** The element's `«label»`, `공통 부품: file:lo-hi` and `요소 잃음`, and one guidance clause
  while figure pins are open. A figure document's section title ends with `— 그림(요소 지도)`; the view-only title is
  unchanged. Existing bytes are unchanged; the contract snapshot gains a separate figure flow.
- **Value lists grow as ADR-0011 decided.** `via` gains `map`, `scope` gains `el`…`el8` and `fig`, pin `kind` gains
  `el:<part>` and `figure`. The `bad_scope` and `bad_via` sentences list the new values; their reason codes are unchanged.
- **Anchors of Python sources skip `#` comment lines** (LaTeX anchors are unchanged).
- **SKILL (en/ko)** teaches figure pins and rebuilds only documents whose `kind` is `"tex"`.
- **Rollback.** v0.3.5 reads a state folder with figure pins without dropping any and writes them back byte for byte
  (`tests/test_figure_rollback.py`); remove the figure document from its `--doc` list first.
```

- [ ] **Step 5: Handbook checks**

Run: `uv run pytest -q tests/test_handbook_refs.py tests/test_naming.py`
Expected: pass. Every new `§…` reference names an existing heading, and no dates appear in topics.

If the Handbook font is installed locally, run: `uv run python tools/handbook-publish/publish.py check docs/handbook/index.md`
Expected: exit 0.

- [ ] **Step 6: Point the new code at the new headings**

Tasks 1–10 cite only headings that exist on `main` `5d1c4b6`, because `tests/test_handbook_refs.py` checks every Handbook reference in tracked files, code fences included. Now that Steps 1–2 have written the new headings, change the heading text in these references. Keep the path, and change only the words after the section sign:

| File | Where | Cites now | Cites after this step (topic · heading) |
| --- | --- | --- | --- |
| `tests/test_figmap_pick.py` | module docstring | domain · 범위 사다리 | domain · 그림 문서의 요소 pick |
| `src/limn/figmap.py` | comment above `COVER_MIN` | domain · 역변환이 두 경로인 이유, 범위 사다리 | domain · 그림 문서의 요소 pick, 그림 핀의 요소 위치 — 읽을 때 계산한다 |
| `src/limn/pins/element.py` | module docstring | api · 핀 레코드 스키마 | api · 그림 문서의 pick·핀 |
| `src/limn/features/pins/location/figure.py` | module docstring | domain · 범위 사다리; api · 보기 전용 PDF 문서의 pick·핀 | domain · 그림 문서의 요소 pick; api · 그림 문서의 pick·핀 |
| `src/limn/features/pins/location/test_figure.py` | module docstring | api · 보기 전용 PDF 문서의 pick·핀; domain · 범위 사다리 | api · 그림 문서의 pick·핀; domain · 그림 문서의 요소 pick |
| `src/limn/features/pins/location/http.py` | `_element_body` docstring | api · 핀 만들기와 상태 바꾸기 | api · 그림 문서의 pick·핀 |
| `src/limn/features/pins/location/range.py` | `raw_ladder` docstring | domain · 범위 사다리 | api · 그림 문서의 pick·핀 |
| `src/limn/features/pins/editing/input.py` | `parse_add` docstring | api · 보기 전용 PDF 문서의 pick·핀 | api · 그림 문서의 pick·핀 |
| `src/limn/features/pins/editing/location.py` | comment on `el = parse_el(...)` in `parse_loc` | api · 핀 레코드 스키마 | api · 그림 문서의 pick·핀 |
| `src/limn/features/pins/editing/test_figure_pins.py` | module docstring | api · 핀 레코드 스키마, 핀 수정 | api · 그림 문서의 pick·핀 |
| `src/limn/pins/view.py` | module docstring | api · 핀 읽기 | api · 그림 문서의 pick·핀 |
| `src/limn/features/pins/listing/test_figure_pins.py` | module docstring | api · 핀 읽기 | api · 그림 문서의 pick·핀 |
| `src/limn/features/pins/listing/test_figure_pins.py` | `test_get_pins_md_renders_on_request_while_the_file_waits_for_a_pin_write` docstring | domain · 알려진 제약 | domain · 그림 핀의 한계 |
| `src/limn/pins/render.py` | comment above `FIGURE_GUIDANCE`; `element_quote` docstring | api · pins.md 형식 | api · 그림 핀의 행 |

Run: `uv run pytest -q tests/test_handbook_refs.py`
Expected: pass. Every changed reference names a heading that Steps 1–2 wrote.

- [ ] **Step 7: Check the index (no edit)**

The index already carries this plan's amendments. Check that the code matches it and do not edit the file:

```bash
f=docs/superpowers/plans/2026-09-30-figure-documents.md
grep -n "deepest \*\*non-root\*\* element" $f
grep -n "the first rung's level" $f
grep -n "merge into the \*\*inner\*\* rung" $f
grep -n 'impl?: {file, lo, hi}, frac?}' $f
grep -n "bad_el" $f
grep -n "a \`loc\` without \`el\` drops it" $f
grep -n "BuildMapCache" $f
grep -n "renders on request" $f
git diff --exit-code -- $f && echo INDEX-UNCHANGED
```

Expected: every `grep` prints at least one line, and `INDEX-UNCHANGED` prints. If a line is missing, the index and this plan diverge. Stop and ask the coordinator; do not edit the index from this PR.

- [ ] **Step 8: Full gate**

Run every gate in §Global Constraints.
Expected:
- pytest: `N passed, M skipped` with 0 failed. Report the numbers and seconds as verification.md §결과를 보고하는 법 asks.
- `test_instances.sh`: all PASS.
- `ruff check`: `All checks passed!` `ruff format --check`: no changes. shellcheck: no output.
- mypy: `Success: no issues found`.

- [ ] **Step 9: Commit**

```bash
git add docs/handbook CHANGELOG.md src/limn tests
git commit -s -m "docs(handbook): figure pick, element pins and read-time positions" -m "domain, api, index file map, verification and CHANGELOG describe the map pick, the el field, mark/el_sync, the pins.md figure rows, the figure snippet ladder and the anchor comment rule."
git commit --amend -q -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

## Done

- [ ] Every gate in §Global Constraints is green on the PR (CI checks out full history, so `RollbackToV035` runs, not skips).
- [ ] `git diff --exit-code origin/main -- tests/data/contract_snapshot.json` prints nothing, and `tests/data/contract_snapshot_figure.json` was read once by eye against api.md §그림 문서의 pick·핀.
- [ ] **Manual rollback check with the whole previous server.** Use a copy of a state folder, never the live one.
  ```bash
  # 1. On this branch, serve a throwaway copy of a paper checkout with a figure document; pin one element with code and
  #    one drawn without code; stop that server by the PID you started it with (never by port).
  # 2. Copy its state folder and keep the figure records as they are.
  cp -a <state-with-figure-pins> /tmp/limn-rollback-state
  grep '"el": ' /tmp/limn-rollback-state/pins.jsonl > /tmp/limn-rollback-before.jsonl
  wc -l < /tmp/limn-rollback-before.jsonl                         # N figure records
  # 3. Run v0.3.5 from the tag on the copy, without the figure document (0.3.5 does not know .limnmap.json).
  rel=$(mktemp -d) && git archive --format=tar v0.3.5 src/limn | tar -x -C "$rel"
  PYTHONPATH="$rel/src" python3 -S -m limn serve --manuscript <paper checkout> --doc ms=본문:main.tex \
    --state-dir /tmp/limn-rollback-state --port 18777 --no-build & pid=$!
  # 4. Every figure pin is served, listed under the unconfigured document, and survives a write to another pin.
  curl -s 'http://127.0.0.1:18777/api/pins?all=1' | python3 -c 'import json,sys; print(sum(1 for p in json.load(sys.stdin) if "el" in p))'   # N
  curl -s http://127.0.0.1:18777/pins.md | grep -n '설정에 없는 문서'
  curl -s -X POST http://127.0.0.1:18777/api/pins/<a LaTeX pin id>/reply -H 'Content-Type: application/json' -d '{"text":"rollback check"}'
  grep '"el": ' /tmp/limn-rollback-state/pins.jsonl | diff - /tmp/limn-rollback-before.jsonl && echo FIGURE-RECORDS-UNCHANGED
  kill "$pid"
  ```
  Expected: the count prints N, the `## 설정에 없는 문서 · \`fig\`` subsection is present, and `FIGURE-RECORDS-UNCHANGED` prints.
- [ ] Manual: on a real figure set, drag a point, a small box and a box across two cells. Each answer is the expected element. Record whether `COVER_MIN`/`FILL_MIN` (D6) feel right in the PR, and change nothing without a measured reason.
- [ ] The PR description lists the §Contract issues (already in the index, checked in Task 11, Step 7) and the value-list growth (ADR-0011 D5).
- [ ] owner confirmed the grown bad_scope/bad_via sentences

## Self-review

1. **Spec coverage** (spec §pick, §핀 저장, §요소 위치는 읽을 때 계산한다, §에이전트 계약, §충돌·미확인):
   - The pick rule, the ladder, `via: map`, the score warning and the fallbacks are Tasks 1 and 6.
   - `el` in pins and the record check are Tasks 2 and 7.
   - The read-time `mark`/`el_sync` without writes are Task 8.
   - The `pins.md` rows and the guidance are Task 9.
   - The value lists are Task 3, and SKILL (en/ko) with the rebuild rule fixed is Task 10.
   - The anchor comment question is Task 4, and the doc root overlap is Task 7.
   - Rollback safety is Task 2 and the Done list, and the contract snapshot is Task 9.
   - The viewer (outline, badge, `mark` drawing) is P1c by the index and is not in this plan.
2. **Placeholder scan.** No TBD or TODO is left, and every code step shows its code. The P0/P1a names are stated assumptions with a verification command (Task 1, Step 1), not blanks.
3. **Type consistency.**
   - `PinElement(id, path, label, part, impl, frac)` is the same type in Tasks 2, 6, 7, 8 and 9.
   - `pick_figure` returns `PickedElement | FigureFallback`.
   - `PickedRegion.el`/`.fallback` are set in Task 6 and read by `_region_body`.
   - `ServerApplication.figure_map`/`doc_figure_map` are defined in Task 5 and consumed in Tasks 6, 8 and 9.
   - `element_marks` is defined in Task 8 and reused by `markdown.py` in Task 9.
   - `LOC_FIELDS`/`REGION_PLACE_FIELDS` end with `el`, and `VIAS` comes from `mapping`.
4. **Review Focus.** Each of the seven lines names its test in the owning task. Lines 1–5 are the five input classes required by the brief.
