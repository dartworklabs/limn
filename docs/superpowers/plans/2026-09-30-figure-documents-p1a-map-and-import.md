# Figure Documents P1a: Map Parser, Registration and Import Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `--doc`/`DOCS=` entry ending in `.limnmap.json` serves a figure document whose PDF and element map are imported (never built), kept per build, watched like a view-only PDF, and picked and pinned as regions.

**Architecture:** A pure parser `src/limn/figmap.py` turns map bytes into frozen values or a `MapRejected`. Registration adds the kind `figure` and the capability `has_element_map`. The import in `src/limn/features/builds/figure.py` reads the map and the PDF once, imports them only when the map's `pdf_sha256` matches the PDF bytes, and renders exactly the bytes it checked through the existing `run_tracked` path. It publishes the map next to the PDF copy in every `pages-<build>/`. Shared readers of that per-build copy live in `src/limn/build.py`, so the builds and pins slices never import each other.

**Tech Stack:** Python 3.10+ standard library at runtime; pytest, pytest-xdist, Hypothesis; Ruff; mypy (`strict`, `exhaustive-match`); ShellCheck; bash for the instance manager.

**Spec:** [`docs/superpowers/specs/2026-09-30-figure-documents-design.md`](../specs/2026-09-30-figure-documents-design.md). The index [`2026-09-30-figure-documents.md`](2026-09-30-figure-documents.md) fixes the shared names (§Shared contract). The P0 plan [`2026-09-30-figure-documents-p0-capabilities.md`](2026-09-30-figure-documents-p0-capabilities.md) fixes the capability names this plan builds on. Decisions are in [ADR-0011](../../adr/0011-figure-documents.md).

## Contract issues

None open. P1a raised three, all accepted; the index's §Shared contract now contains them (index §Contract amendments at handover, row P1a), and Task 0 only checks that it does:

1. `FIGMAP_NAME` and `load_build_map(doc, build)` live in `src/limn/build.py`, not in `features/builds/figure.py`: the pick slice, `documents.DocumentFacts` and the composition root read them, and a slice never imports another (architecture.md, §의존 방향). `features/builds/figure.py` owns the import and `figure_src_hash`.
2. `Doc.has_element_map` (true only for `figure`) tells a figure's import from a view-only PDF's render, since both have the same five capabilities in P1a and branches never read `kind`.
3. `figure_src_hash(pdf_raw, map_raw)`: SHA-256 over the SHA-256 digest of the PDF bytes followed by that of the map bytes, first 32 hex digits.

The index also fixes two rules this plan builds in: a map missing at startup refuses the start like a missing view-only PDF (Task 2), and `MAP_MAX_TEXT = 200` caps `figure`, `title`, element `id`, `part` and `label` (`bad_shape` otherwise), because P1b pins store them (Task 1).

## Global Constraints

- Server runtime stays standard-library only (`dependencies = []`). No SVG rasterising, no external API calls, no subprocess other than the existing `pdftoppm` path.
- The agent contract (`pins.md`, HTTP API) only grows. P1a adds one value: document `kind` `"figure"` in `/api/docs` and `/api/meta`, with `view_only: true`. No existing field, path, status or value changes meaning. `pins.md` bytes do not change for existing documents. Do not re-record `tests/data/contract_snapshot.json` or `tests/data/pin_records.jsonl`.
- Pin files are written only through `PinStore.transact()`. The import never writes pins.
- Old state folders are read without migration.
- Code, comments, docstrings, test names, commit messages: English. Handbook: Korean, present tense, no dates. `README`/`skill/SKILL` are not touched in P1a (a figure document is `view_only: true`, so SKILL's rebuild rule still holds).
- No real e-mails, home paths or host names in code, tests or docs (`alice@example.com`, `/srv/paper`).
- **Handbook references.** `tests/test_handbook_refs.py` checks every `docs/handbook/<topic>.md §<heading>` in tracked files under `src/`, `tests/` and `docs/`, this plan included. Code written in Tasks 1–6 cites only headings that exist before Task 7: `docs/handbook/domain.md §여러 문서`, `docs/handbook/build-sync.md §보기 전용 PDF 문서`, `docs/handbook/api.md §보기 전용 PDF 문서의 pick·핀`, `docs/handbook/code-style-roadmap.md §R10`. The new Handbook headings (build-sync `그림 문서`, domain `그림 문서`, api `그림 요소 지도`) are linked only from Handbook topics, in Task 7.
- **Commits.** `git commit -s`, then one amend that puts `I agree to the Limn CLA (CLA.md).` directly after `Signed-off-by:`. Every commit step shows both commands. Never put the CLA line into the message given to `git commit -s`: git then appends a second sign-off after it.
- **Coding rules** (docs/handbook/code-style-roadmap.md §R1, §R3, §R5, §R7, §R8, §R9, §R10 — the "지금 적용" rules):
  - **R1:** decisions are pure functions: `figmap.parse_map`, `figure.import_due`, `figure.accept_pdf`, `figure.figure_src_hash`. File reads, stat calls, `pdftoppm` and `stderr` stay at the edge (`figure.read_figure_import`, `figure.watch_signature`, `figure.render_figure_doc`, `build.load_build_map`).
  - **R3:** the map is parsed once at the boundary into typed values. Domain refusals are values (`MapRejected`, `ImportDeferred`, the `DocSpecRefusal` types). No new HTTP mapping: a figure document reuses the view-only answers (`view_only_no_rebuild`, `no_source_lines`).
  - **R5:** new functions read no module globals (`C.`, `cur_doc()`, `DOCS`). Each touched module keeps its existing no-server-state test, and `figure.py` gets one.
  - **R7:** every new or touched module, type, function, method and property has a docstring stating its contract, private helpers and test helpers included.
  - **R8:** `DocKind` includes `"figure"`; no bare `str` holds a kind or a reject reason.
  - **R9:** every test name states condition and expectation, every test has a docstring, and every test is run red first.
  - **R10:** every boundary change gets negative tests: map paths outside the folder, symlinks out, oversized or deeply nested maps, a wrong suffix, a `::` form with a PDF.
- **Test placement** (ADR-0010, verification.md §1): the pure top-level module's tests go to `tests/test_figmap.py`, `build.py`'s to `tests/test_build.py`. Slice tests are colocated: `src/limn/features/administration/test_serve_documents.py`, `src/limn/features/builds/test_figure.py`, `src/limn/features/pins/location/test_figure_region.py`, `src/limn/features/document_views/test_meta.py`.
- **Formatting.** Before each commit run `uv run ruff check --fix <changed .py files>` and `uv run ruff format <changed .py files>`. The code below is written to Ruff's rules, and the formatter may still re-wrap long lines.
- Gates for the PR:
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

1. **A producer writes the new PDF, then the map (the `pdf_sha256` mismatch window), or the other way round.** Expected: while the two disagree, nothing renders. No page directory, `builds.json` entry, `build_seq` change or failure is recorded, and the screen keeps the last figure. One `stderr` line names the reason once per change. The pair is imported on the first tick after the second file lands. Pinned in Task 4 (`test_a_pdf_newer_than_its_map_is_not_imported_and_records_no_build`, `test_a_map_written_before_its_pdf_waits_for_the_pdf`) and Task 5 (`test_the_watch_imports_a_figure_once_its_map_catches_up`).
2. **A map pointing outside the figure's folder:** `pdf` or `src.file` with `../`, an absolute path, a dot folder, or a symlink out. Expected: no such file is ever read or named. The map is rejected (`path_outside`) or the import is deferred (`pdf_outside`), and the pick falls back to naming the map file. Pinned in Task 1 (`test_a_source_path_the_document_does_not_hold_is_path_outside`), Task 3 (`test_a_source_path_is_accepted_only_inside_the_documents_folder`, `test_the_pdf_a_map_names_is_resolved_from_the_maps_folder_inside_the_document`), Task 4 (`test_a_pdf_outside_the_figure_folder_is_never_read`) and Task 6 (`test_a_map_copy_that_is_missing_or_names_a_pdf_outside_names_the_map_file`).
3. **A huge or deeply nested map.** Expected: at most `MAP_MAX_BYTES + 1` bytes are read, and a larger file is `too_large` before decoding. Nesting deeper than the JSON parser's stack is `not_json`, never a crash. More than 5000 elements on a page is refused before they are read. A 5000-deep parent chain parses without recursion. An unchanged map is not re-read on every 3-second tick. Pinned in Task 1 (`test_a_file_over_the_size_cap_is_refused_before_it_is_decoded`, `test_bytes_that_are_not_one_json_object_are_refused`, `test_too_many_elements_on_a_page_is_refused_before_they_are_read`, `test_a_parent_chain_as_deep_as_the_element_cap_parses`) and Task 4 (`test_a_changed_map_is_read_again_and_its_new_pdf_followed`).
4. **A map whose page count differs from the PDF's.** Expected: the pair is imported anyway. Map pages beyond the PDF are never asked for, and PDF pages without a map page are picked as regions. Pinned in Task 4 (`test_a_map_with_more_pages_than_the_pdf_still_imports`).
5. **A figure folder that lies inside a LaTeX document's build root.** Expected: a file-only request (agent `curl`) never routes to the figure document, because it takes no line pins. The LaTeX document may show `원고 수정됨` when the figure PDF changes, the known limitation of scanning the whole build root, which Task 7 writes into domain.md. Pinned in Task 2 (`test_a_file_under_a_figure_folder_routes_to_the_latex_document_around_it`) and Task 6 (`test_a_file_only_pin_under_the_figure_folder_goes_to_the_latex_document`).
6. **The map is missing.** Expected: at startup, the start is refused exactly like a missing view-only PDF (`--doc fig: 파일이 없습니다: …`). While running, the watch does nothing and keeps the last pages. Pinned in Task 2 (`test_a_missing_map_refuses_startup_like_a_missing_file`) and Task 4 (`test_a_missing_map_imports_nothing_and_records_nothing`).

---

## Before you start

- [ ] **Step 1: Branch from the current `main` in its own worktree**

```bash
git fetch origin --prune
git worktree add ../limn-p1a -b feat/figure-documents-p1a origin/main
cd ../limn-p1a
git status --short
```

Expected: `git status --short` prints nothing.

- [ ] **Step 2: Check that P0 and ADR-0011 are on `main`**

```bash
grep -n "def is_pdf" src/limn/documents.py src/limn/web/parse.py src/limn/build.py
grep -n "^DocKind\|def kind_builds_from_source\|def builds_from_source\|def watches_files\|def takes_line_pins\|def shows_revisions\|def view_only" src/limn/documents.py
grep -n "def doc_start_line" src/limn/features/administration/serve_documents.py
grep -n "CAPABILITY_TABLE = {" src/limn/features/document_views/test_meta.py
test -f docs/adr/0011-figure-documents.md && echo "ADR-0011 present"
```

Expected: the first command prints nothing. The second prints the `DocKind` line, `kind_builds_from_source` and the five capability properties (7 lines). The third and fourth print one line each. The last prints `ADR-0011 present`. If any expectation fails, stop: this plan assumes P0 has landed.

- [ ] **Step 3: Record the baseline**

```bash
uv sync --group dev
uv run pytest -q -rs -n 4 --dist loadscope 2>&1 | tail -n 1
```

Expected: one summary line with `passed` and no `failed` or `error`. Note the counts for the PR description.

### What P0 leaves, and what a figure document gets from it

Line numbers are `main` at `5d1c4b6`; the names are P0's (P0 plan, Table A).

| Site | P0 branch | A figure document in P1a | P1a action |
| --- | --- | --- | --- |
| `documents.py:209` `doc_for_file` | `not d.takes_line_pins` → skip | skipped | none (Task 2 pins it) |
| `documents.py:281` `DocumentFacts.view_only` | `Doc.view_only` | `True`: region parsing | none |
| `documents.py:283` `DocumentFacts.pdf` | `Doc.main` | would name the map file | Task 6: the map's PDF |
| `build.py:234` `cur_pdf` fallback | `not builds_from_source` → `D.main` | reached only before any import, never by the pick | none |
| `build.py:275` `migrate_pages` | `not builds_from_source` → return | returns | none |
| `build.py:550` `doc_fingerprint` | `not builds_from_source` → hash `D.main` | hashes the map; used only when seeding a build missing from history | none (the import computes its own `src_hash`) |
| `build.py:595` `src_mtime` | `not builds_from_source` → `D.main` mtime | the map's mtime | none |
| `server.py:759` → `doc_start_line` | exhaustive `match kind` | mypy demands a label | Task 2: `case "figure"` |
| `render.py:418,490,494` `DocHeading` | `view_only` / `builds_from_source` | `, 보기 전용`, stamp `그림` | none |
| `service.py:54` `tracked` | `builds_from_source` → compile, else `render_pdf_doc` | would render the map as a PDF | Task 5: `build_step` |
| `service.py:90` watch | `watches_files` → `engine.refresh_pdf_doc` | would stat the map as a PDF | Task 5: `refresh_watched` |
| `run.py:46` `request_rebuild` | `not builds_from_source` → `ViewOnlyNoRebuild` | `400 view_only_no_rebuild` | none (Task 5 pins it) |
| `run.py:56` `needs_build` | `watches_files` → `pdf_changed` | never called for a figure | Task 5 routes `init_doc` first |
| `engine.py:352` `refresh_pdf_doc` | `watches_files` guard | never called for a figure | Task 5 routes the watch first |
| `location/input.py:80`, `resolve.py:148`, `editing/input.py:44` | `view_only` | region | none |
| `revisions/core.py:300` | `not shows_revisions` | unavailable | none (Task 5 pins it) |
| `reads.py:57,116,168` | `builds_from_source` | never stale, no outline | none (Task 2 pins it) |
| `reads.py:64,134` | `view_only` | `true` | none (Task 2 pins it) |
| `sync/run.py:206,232` | `builds_from_source` | never pulled or rebuilt | none |
| `serve_documents.py:314,365` | `kind_builds_from_source` | own state folder; never the run's main | none (Task 2 pins it) |

---

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `docs/superpowers/plans/2026-09-30-figure-documents.md` | Read only (Task 0) | The index already carries P1a's amendments; Task 0 checks them |
| `src/limn/figmap.py` | Create (Task 1) | Pure parser of `limn-figure-map/1`: constants, `SourceRef`, `MapElement`, `MapPage`, `FigureMap`, `MapRejectReason`, `MapRejected`, `parse_map` |
| `tests/test_figmap.py` | Create (Task 1) | Example tests for every rejection and accepted edge; Hypothesis properties; purity |
| `tests/helpers.py` | Modify (Task 1) | `figure_map(pdf, pdf_name)` and `map_bytes(m)`: the design's example map, shared by four test modules |
| `src/limn/documents.py` | Modify (Tasks 2, 6) | `DocKind` gains `"figure"`; `watches_files`, `has_element_map`, `pdf_name`; `DocumentFacts.pdf` names the map's PDF |
| `src/limn/features/administration/serve_documents.py` | Modify (Task 2) | `.limnmap.json` → `figure`; `::` accepts a map; refusal wording; `doc_start_line` label |
| `src/limn/features/administration/instance_documents.sh` | Modify (Task 2) | Shell mirror of the suffix rules |
| `src/limn/args.py` | Modify (Task 2) | `--doc` help names the map suffix |
| `src/limn/features/administration/test_serve_documents.py` | Modify (Task 2) | Registration tests, shell-mirror guard |
| `src/limn/features/document_views/test_meta.py` | Modify (Task 2) | Capability table row; figure document reads and lookups |
| `tests/test_startup.py` | Modify (Task 2) | Renamed refusal type and the new wording |
| `tests/test_instances.sh` | Modify (Task 2) | `limn add` accepts and refuses map paths |
| `src/limn/build.py` | Modify (Task 3) | `FIGMAP_NAME`, `figure_source_check`, `figure_pdf`, `load_build_map`, `build_figure_pdf` |
| `tests/test_build.py` | Modify (Task 3) | `FigureBuildFacts` |
| `src/limn/build_values.py`, `src/limn/web/errors.py` | Modify (Task 4) | `AbortKind` `figure_unready` and its text |
| `src/limn/features/builds/figure.py` | Create (Task 4) | The import: signature, deferral, verified read, render with the map copy, `import_now` |
| `src/limn/features/builds/test_figure.py` | Create (Tasks 4, 5) | Import unit tests and the server-level figure document tests |
| `src/limn/features/builds/service.py` | Modify (Task 5) | `build_step`, `import_figure`, `refresh_watched`, figure branch in `init_doc`, watch loop |
| `src/limn/features/pins/location/resolve.py`, `src/limn/web/parse.py` | Modify (Task 6) | Region pick names the map's PDF; protocol docstring |
| `src/limn/features/pins/location/test_figure_region.py` | Create (Task 6) | Pick and pin on a figure document |
| `docs/handbook/{purpose,instances,operations,build-sync,domain,api,architecture,index}.md`, `CHANGELOG.md` | Modify (Task 7) | Current state in Korean; changelog |

---

### Task 0: Check that the index carries the P1a contract

**Files:**
- Read: `docs/superpowers/plans/2026-09-30-figure-documents.md` (§Shared contract, §Contract amendments at handover). Nothing is edited or committed.

**Interfaces:**
- Consumes: nothing.
- Produces: certainty that the names later tasks use are the index's: `Doc.has_element_map`, `limn.build.FIGMAP_NAME` and `limn.build.load_build_map`, `figure.figure_src_hash`, the startup refusal for a missing map, and `MAP_MAX_TEXT = 200`.

- [ ] **Step 1: Check the amendments**

```bash
INDEX=docs/superpowers/plans/2026-09-30-figure-documents.md
grep -n "def has_element_map" "$INDEX"
grep -n "Shared build facts live in \`src/limn/build.py\`" "$INDEX"
grep -n "figure_src_hash(pdf_raw: bytes, map_raw: bytes) -> str" "$INDEX"
grep -n "missing at startup refuses the start" "$INDEX"
grep -n "MAP_MAX_TEXT = 200" "$INDEX"
grep -n "^| P1a | \`FIGMAP_NAME\`" "$INDEX"
```

Expected: every command prints at least one line (the `MAP_MAX_TEXT` rule appears twice: in the parse rules and in the amendments table); the last is the P1a row of §Contract amendments at handover. If any prints nothing, stop: the index and this plan disagree, and the index wins (index: "A phase plan must not rename anything defined in §Shared contract").

---

### Task 1: `figmap.py`, the element map parser

**Files:**
- Create: `src/limn/figmap.py`
- Modify: `tests/helpers.py` (imports; the module docstring; two helpers after `minimal_pdf`)
- Test: `tests/test_figmap.py`

**Interfaces:**
- Consumes: `limn.pins.shapes.is_finite_num`, `limn.pins.shapes.is_int`.
- Produces (exact names from the index's §Shared contract, plus the helpers the later tasks' tests use):
  - `MAP_FORMAT = "limn-figure-map/1"`, `MAP_SUFFIX = ".limnmap.json"`, `MAP_MAX_BYTES = 4 * 1024 * 1024`, `MAP_MAX_ELEMENTS = 5000`, `Frac: TypeAlias = tuple[float, float, float, float]`
  - `MAP_MAX_TEXT = 200` (index §Shared contract: `figure`, `title`, element `id`, `part` and `label` are at most 200 characters, `bad_shape` otherwise, because P1b pins store them)
  - also `FRAC_EPS = 1e-6` and `FULL_PAGE: Frac = (0.0, 0.0, 1.0, 1.0)`
  - `SourceRef(file: str, lo: int, hi: int)`, `MapElement(id, parent, frac, src, impl, part, label)`, `MapPage(page, figure, title, elements)` with `root()`, `by_id(el_id)`, `ancestors(el)`, `FigureMap(pdf, pdf_sha256, pages)` with `page(n)`, `find(el_id)`
  - `MapRejectReason`, `MapRejected(reason, detail)`
  - `parse_map(raw: bytes, *, source_inside: Callable[[str], bool]) -> FigureMap | MapRejected`
  - test helpers `helpers.figure_map(pdf: bytes, pdf_name: str = "figures.pdf") -> dict` and `helpers.map_bytes(m: dict) -> bytes`

- [ ] **Step 1: Add the shared example map to `tests/helpers.py`**

In the module docstring, replace `a minimal PDF for the browser's comparison view).` with `a minimal PDF for the browser's comparison view, a figure's element map).`

Add `import hashlib` to the standard-library imports (after `import functools`).

After `minimal_pdf`, append:

```python
def figure_map(pdf: bytes, pdf_name: str = "figures.pdf") -> dict:
    """The element map (limn-figure-map/1) of the design's example - one page, figure B2 with a calendar strip and its
    July cell, whose code lines are in src/B2_calendar.py and whose shared component is in lib/components.py - that
    describes the PDF bytes pdf and names that PDF pdf_name, relative to the map's folder."""
    return {
        "format": "limn-figure-map/1",
        "pdf": pdf_name,
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "pages": [
            {
                "page": 1,
                "figure": "B2",
                "title": "Deployment calendar",
                "elements": [
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
                        "frac": [0.47, 0.18, 0.07, 0.12],
                        "src": {"file": "src/B2_calendar.py", "lo": 88, "hi": 95},
                        "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
                    },
                ],
            }
        ],
    }


def map_bytes(m: dict) -> bytes:
    """The bytes a producer writes for map m: its JSON text with non-ASCII escaped, so a lone surrogate stays
    expressible for the tests that need one."""
    return json.dumps(m).encode("ascii")
```

- [ ] **Step 2: Write the failing parser tests**

Create `tests/test_figmap.py`:

```python
"""limn.figmap - the element map a figure repository writes (limn-figure-map/1), parsed once at the boundary.

The module is pure, so these tests hand it bytes and a path check and look only at the values it returns (coding rule
R9). Every rejection reason has examples that break exactly that rule. The accepted edges are pinned too: unknown keys,
elements drawn without code (ADR-0011 D7), a root listed last, rounding at the page edge, a parent chain as deep as
the element cap, a file exactly at the size cap. Hypothesis checks that parse_map never raises, whatever bytes or JSON
it gets, and that every map it accepts is one tree per page rooted at the page's figure.

Run: uv run pytest -q tests/test_figmap.py
"""

import ast
import copy
import json
import unittest
from collections.abc import Callable
from pathlib import Path

from hypothesis import given, strategies as st

from limn import figmap
from limn.figmap import (
    FULL_PAGE,
    MAP_FORMAT,
    MAP_MAX_BYTES,
    MAP_MAX_ELEMENTS,
    MAP_MAX_TEXT,
    FigureMap,
    MapElement,
    MapRejected,
    SourceRef,
    parse_map,
)

from helpers import MINI_PDF, figure_map, map_bytes

FIGMAP_PY = Path(figmap.__file__)
PURE_IMPORTS = {"__future__", "json", "collections.abc", "dataclasses", "typing", "limn.pins.shapes"}


def anywhere(path: str) -> bool:
    """A source check that accepts every path: the rules under test are the map's own."""
    return True


def parse(m: dict, source_inside: Callable[[str], bool] = anywhere) -> FigureMap | MapRejected:
    """parse_map of the bytes a producer writes for map m."""
    return parse_map(map_bytes(m), source_inside=source_inside)


def page0(m: dict) -> dict:
    """The first page object of map m."""
    return m["pages"][0]


def elements0(m: dict) -> list:
    """The element list of map m's first page."""
    return m["pages"][0]["elements"]


def changed(change: Callable[[dict], object]) -> dict:
    """The design's example map (helpers.figure_map) after change(m) has edited it in place."""
    m = figure_map(MINI_PDF)
    change(m)
    return m


def second_page(figure: str, *elements: dict, number: int = 2) -> Callable[[dict], object]:
    """A change that appends page `number`, whose figure is `figure`, with these elements."""
    return lambda m: m["pages"].append({"page": number, "figure": figure, "elements": list(elements)})


ROOT_ONLY = {"id": "C1", "frac": [0, 0, 1, 1]}


def put_figure(m: dict, text: str) -> None:
    """Rename the first page's figure to text, and its root (and the root's child) with it, so the page stays rooted."""
    page0(m)["figure"] = text
    elements0(m)[0]["id"] = text
    elements0(m)[1]["parent"] = text


# The five names a pin stores, each with a change that sets it to a given text (index §Shared contract: MAP_MAX_TEXT).
# The id is the July cell's: a leaf, so no parent refers to it.
TEXT_FIELDS: dict[str, Callable[[dict, str], object]] = {
    "figure": put_figure,
    "title": lambda m, text: page0(m).update(title=text),
    "id": lambda m, text: elements0(m)[2].update(id=text),
    "part": lambda m, text: elements0(m)[2].update(part=text),
    "label": lambda m, text: elements0(m)[2].update(label=text),
}

# (what breaks, the change to the example map, the reason parse_map names)
REJECTIONS = [
    ("format missing", lambda m: m.pop("format"), "bad_format"),
    ("format of a later version", lambda m: m.update(format="limn-figure-map/2"), "bad_format"),
    ("pdf empty", lambda m: m.update(pdf=""), "bad_shape"),
    ("pdf not a string", lambda m: m.update(pdf=["figures.pdf"]), "bad_shape"),
    ("pdf_sha256 in upper case", lambda m: m.update(pdf_sha256=m["pdf_sha256"].upper()), "bad_shape"),
    ("pdf_sha256 one digit short", lambda m: m.update(pdf_sha256=m["pdf_sha256"][:63]), "bad_shape"),
    ("pages an object", lambda m: m.update(pages={}), "bad_shape"),
    ("a page that is a list", lambda m: m["pages"].append([]), "bad_shape"),
    ("figure empty", lambda m: page0(m).update(figure=""), "bad_shape"),
    ("title a number", lambda m: page0(m).update(title=7), "bad_shape"),
    ("elements an object", lambda m: page0(m).update(elements={}), "bad_shape"),
    ("an element that is a string", lambda m: elements0(m).append("B2/x"), "bad_shape"),
    ("id empty", lambda m: elements0(m)[1].update(id=""), "bad_shape"),
    ("id with a lone surrogate", lambda m: elements0(m)[1].update(id="B2/\ud800"), "bad_shape"),
    ("parent a number", lambda m: elements0(m)[1].update(parent=1), "bad_shape"),
    ("src a string", lambda m: elements0(m)[1].update(src="src/B2_calendar.py"), "bad_shape"),
    ("src file empty", lambda m: elements0(m)[1]["src"].update(file=""), "bad_shape"),
    ("lo a boolean", lambda m: elements0(m)[1]["src"].update(lo=True), "bad_shape"),
    ("lo zero", lambda m: elements0(m)[1]["src"].update(lo=0), "bad_shape"),
    ("lo after hi", lambda m: elements0(m)[1]["src"].update(lo=98, hi=97), "bad_shape"),
    ("impl without hi", lambda m: elements0(m)[2]["impl"].pop("hi"), "bad_shape"),
    ("part a number", lambda m: elements0(m)[1].update(part=3), "bad_shape"),
    ("label a list", lambda m: elements0(m)[1].update(label=["달력"]), "bad_shape"),
    ("page zero", lambda m: page0(m).update(page=0), "bad_page"),
    ("page a string", lambda m: page0(m).update(page="1"), "bad_page"),
    ("page a boolean", lambda m: page0(m).update(page=True), "bad_page"),
    ("page number used twice", second_page("C1", ROOT_ONLY, number=1), "bad_page"),
    ("frac missing", lambda m: elements0(m)[1].pop("frac"), "bad_frac"),
    ("frac of three numbers", lambda m: elements0(m)[1].update(frac=[0, 0, 1]), "bad_frac"),
    ("frac with a string", lambda m: elements0(m)[1].update(frac=[0, 0, "1", 1]), "bad_frac"),
    ("frac with NaN", lambda m: elements0(m)[1].update(frac=[0, 0, float("nan"), 1]), "bad_frac"),
    ("frac with infinity", lambda m: elements0(m)[1].update(frac=[0, 0, float("inf"), 1]), "bad_frac"),
    ("frac left of the page", lambda m: elements0(m)[1].update(frac=[-0.1, 0, 0.5, 0.5]), "bad_frac"),
    ("frac of zero width", lambda m: elements0(m)[1].update(frac=[0.1, 0.1, 0, 0.5]), "bad_frac"),
    ("frac past the right edge", lambda m: elements0(m)[1].update(frac=[0.6, 0, 0.5, 0.5]), "bad_frac"),
    ("frac past the bottom edge", lambda m: elements0(m)[1].update(frac=[0, 0.6, 0.5, 0.5]), "bad_frac"),
    (
        "an id twice on one page",
        lambda m: elements0(m).append({"id": "B2/calendar", "parent": "B2", "frac": [0, 0, 1, 1]}),
        "duplicate_id",
    ),
    ("a figure id used again on the next page", second_page("B2", {"id": "B2", "frac": [0, 0, 1, 1]}), "duplicate_id"),
    ("a parent that is no element", lambda m: elements0(m)[2].update(parent="B2/nothing"), "bad_parent"),
    (
        "a parent on another page",
        second_page("C1", ROOT_ONLY, {"id": "C1/x", "parent": "B2/calendar", "frac": [0, 0, 1, 1]}),
        "bad_parent",
    ),
    ("two elements parenting each other", lambda m: elements0(m)[1].update(parent="B2/calendar/m07"), "bad_parent"),
    ("an element its own parent", lambda m: elements0(m)[1].update(parent="B2/calendar"), "bad_parent"),
    ("no element without a parent", lambda m: elements0(m)[0].update(parent="B2/calendar"), "no_root"),
    ("two elements without a parent", lambda m: elements0(m)[1].pop("parent"), "no_root"),
    ("the root is not the figure", lambda m: page0(m).update(figure="B3"), "no_root"),
    ("the root is not the whole page", lambda m: elements0(m)[0].update(frac=[0, 0, 1, 0.5]), "no_root"),
    ("a page without elements", lambda m: page0(m).update(elements=[]), "no_root"),
]


class Purity(unittest.TestCase):
    """The parser reaches no file, process, network or server state (architecture.md stop signal)."""

    def test_imports_only_pure_standard_modules(self):
        """Every import of figmap.py is in PURE_IMPORTS: no os, pathlib, subprocess or limn module with effects."""
        tree = ast.parse(FIGMAP_PY.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertLessEqual(imported, PURE_IMPORTS)


class Accepted(unittest.TestCase):
    """What the example map parses into, and the edges the format allows."""

    def test_the_example_map_becomes_its_values(self):
        """Pages, elements (root first), sources, the ancestor chain nearest first, and lookups by page and id."""
        got = parse(figure_map(MINI_PDF))
        self.assertIsInstance(got, FigureMap)
        page = got.page(1)
        self.assertEqual((got.pdf, len(got.pdf_sha256)), ("figures.pdf", 64))
        self.assertEqual(
            (page.figure, page.title, [e.id for e in page.elements]),
            ("B2", "Deployment calendar", ["B2", "B2/calendar", "B2/calendar/m07"]),
        )
        cell = page.by_id("B2/calendar/m07")
        self.assertEqual(
            cell,
            MapElement(
                "B2/calendar/m07",
                "B2/calendar",
                (0.47, 0.18, 0.07, 0.12),
                SourceRef("src/B2_calendar.py", 88, 95),
                SourceRef("lib/components.py", 410, 470),
                "MonthCell",
                "7월",
            ),
        )
        self.assertEqual([e.id for e in page.ancestors(cell)], ["B2/calendar", "B2"])
        self.assertEqual(page.ancestors(page.root()), ())
        self.assertEqual(got.find("B2/calendar"), (page, page.by_id("B2/calendar")))
        self.assertEqual((got.find("B9"), got.page(2), page.by_id("B9")), (None, None, None))

    def test_unknown_keys_are_ignored_at_every_level(self):
        """The format grows additively: a key this version does not know changes nothing it parses."""
        m = figure_map(MINI_PDF)
        extra = copy.deepcopy(m)
        extra["generator"] = "fig-tool 2"
        page0(extra)["layout"] = {"w": 180}
        for el in elements0(extra):
            el["style"] = ["bold"]
        elements0(extra)[1]["src"]["col"] = 4
        self.assertEqual(parse(extra), parse(m))

    def test_an_element_drawn_without_code_has_no_source(self):
        """A vector graphic exported from a design tool has no code lines (ADR-0011 D7): src and impl are None."""

        def drop_code(m: dict) -> None:
            """Remove src and impl from every element."""
            for el in elements0(m):
                el.pop("src", None)
                el.pop("impl", None)

        got = parse(changed(drop_code))
        self.assertEqual([(e.src, e.impl) for e in got.page(1).elements], [(None, None)] * 3)

    def test_a_root_listed_last_comes_first_and_a_null_parent_is_no_parent(self):
        """Element order in the file is free; the parsed page puts its root first. "parent": null means no parent."""

        def root_last(m: dict) -> None:
            """Move the root to the end of the list and give it an explicit null parent."""
            els = elements0(m)
            els.append(els.pop(0))
            els[-1]["parent"] = None

        got = parse(changed(root_last))
        self.assertEqual([e.id for e in got.page(1).elements], ["B2", "B2/calendar", "B2/calendar/m07"])
        self.assertIsNone(got.page(1).root().parent)

    def test_a_box_may_pass_the_page_edge_by_rounding_only(self):
        """x + w and y + h may exceed 1 by at most FRAC_EPS (a producer's float rounding), not by more."""
        ok = parse(changed(lambda m: elements0(m)[1].update(frac=[0.5, 0.5, 0.5000005, 0.5000005])))
        self.assertIsInstance(ok, FigureMap)
        over = parse(changed(lambda m: elements0(m)[1].update(frac=[0.5, 0.5, 0.500002, 0.5])))
        self.assertEqual(over.reason, "bad_frac")

    def test_a_map_without_pages_is_a_map(self):
        """An empty page list is accepted; every lookup answers None."""
        got = parse(changed(lambda m: m.update(pages=[])))
        self.assertEqual((got.pages, got.page(1), got.find("B2")), ((), None, None))

    def test_a_parent_chain_as_deep_as_the_element_cap_parses(self):
        """MAP_MAX_ELEMENTS elements each the child of the one before: no recursion limit is hit, and the last one's
        ancestors are all the others, root last."""
        chain = [{"id": "B2", "frac": [0, 0, 1, 1]}] + [
            {"id": "B2/%d" % i, "parent": "B2" if i == 0 else "B2/%d" % (i - 1), "frac": [0, 0, 1, 1]}
            for i in range(MAP_MAX_ELEMENTS - 1)
        ]
        got = parse(changed(lambda m: page0(m).update(elements=chain)))
        page = got.page(1)
        self.assertEqual(len(page.elements), MAP_MAX_ELEMENTS)
        ancestors = page.ancestors(page.elements[-1])
        self.assertEqual((len(ancestors), ancestors[-1].id), (MAP_MAX_ELEMENTS - 1, "B2"))

    def test_a_file_exactly_at_the_size_cap_is_read(self):
        """MAP_MAX_BYTES bytes (a map padded with trailing whitespace) are still a map."""
        raw = map_bytes(figure_map(MINI_PDF))
        padded = raw + b" " * (MAP_MAX_BYTES - len(raw))
        self.assertIsInstance(parse_map(padded, source_inside=anywhere), FigureMap)

    def test_every_source_path_is_put_to_the_check(self):
        """source_inside is asked about each src.file and impl.file the map names."""
        asked: list[str] = []

        def record(path: str) -> bool:
            """Remember the path and accept it."""
            asked.append(path)
            return True

        parse(figure_map(MINI_PDF), source_inside=record)
        self.assertEqual(sorted(set(asked)), ["lib/components.py", "src/B2_calendar.py"])


class Rejected(unittest.TestCase):
    """Each rule of the map breaks alone and parse_map names it; nothing is raised."""

    def test_each_broken_rule_is_named(self):
        """One change to the example map per row of REJECTIONS; the reason is the row's."""
        for what, change, reason in REJECTIONS:
            with self.subTest(what):
                got = parse(changed(change))
                self.assertIsInstance(got, MapRejected)
                self.assertEqual(got.reason, reason, got.detail)

    def test_names_a_pin_stores_are_at_most_map_max_text_characters(self):
        """figure, title, id, part and label of MAP_MAX_TEXT - 1 and MAP_MAX_TEXT characters are kept whole; one
        character more is bad_shape. Characters, not bytes: the text is Hangul."""
        for field, put in TEXT_FIELDS.items():
            for length in (MAP_MAX_TEXT - 1, MAP_MAX_TEXT, MAP_MAX_TEXT + 1):
                with self.subTest(field=field, length=length):
                    text = "가" * length
                    got = parse(changed(lambda m, put=put, text=text: put(m, text)))
                    if length > MAP_MAX_TEXT:
                        self.assertIsInstance(got, MapRejected)
                        self.assertEqual(got.reason, "bad_shape", got.detail)
                    else:
                        self.assertIsInstance(got, FigureMap)
                        page = got.page(1)
                        cell = page.elements[2]
                        kept = {
                            "figure": page.figure,
                            "title": page.title,
                            "id": cell.id,
                            "part": cell.part,
                            "label": cell.label,
                        }
                        self.assertEqual(kept[field], text)

    def test_the_detail_says_where_the_rule_broke(self):
        """The detail starts with the path into the map, so a producer can find the element."""
        got = parse(changed(lambda m: elements0(m)[1].update(frac=[0.1, 0.1, 0, 0.5])))
        self.assertTrue(got.detail.startswith("pages[0].elements[1].frac"), got.detail)

    def test_a_file_over_the_size_cap_is_refused_before_it_is_decoded(self):
        """MAP_MAX_BYTES + 1 bytes are too_large even though they are not JSON: the size is checked first."""
        self.assertEqual(parse_map(b" " * (MAP_MAX_BYTES + 1), source_inside=anywhere).reason, "too_large")

    def test_bytes_that_are_not_one_json_object_are_refused(self):
        """Broken JSON, bytes that are not UTF-8, a repeated key and nesting deeper than the parser's stack are
        not_json; a JSON array is not a map (bad_shape)."""
        repeated = b'{"format": "limn-figure-map/1", "format": "limn-figure-map/1"}'
        deep = b"[" * 100_000 + b"]" * 100_000
        for raw in (b"{", b"\xff\xfe{}", repeated, deep):
            with self.subTest(raw=raw[:20]):
                self.assertEqual(parse_map(raw, source_inside=anywhere).reason, "not_json")
        self.assertEqual(parse_map(b"[]", source_inside=anywhere).reason, "bad_shape")

    def test_too_many_elements_on_a_page_is_refused_before_they_are_read(self):
        """A root and MAP_MAX_ELEMENTS children are one element over the cap."""
        many = [{"id": "B2", "frac": [0, 0, 1, 1]}] + [
            {"id": "B2/%d" % i, "parent": "B2", "frac": [0, 0, 1, 1]} for i in range(MAP_MAX_ELEMENTS)
        ]
        self.assertEqual(parse(changed(lambda m: page0(m).update(elements=many))).reason, "too_many_elements")

    def test_a_source_path_the_document_does_not_hold_is_path_outside(self):
        """source_inside decides for src.file and impl.file alike (docs/handbook/code-style-roadmap.md §R10)."""
        for refused in ("src/B2_calendar.py", "lib/components.py"):
            with self.subTest(refused):
                got = parse(figure_map(MINI_PDF), source_inside=lambda f, refused=refused: f != refused)
                self.assertEqual(got.reason, "path_outside")


LEAVES = st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=12)
JSON_VALUES = st.recursive(
    LEAVES,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=24,
)
ELEMENT_KEYS = st.sampled_from(["id", "parent", "frac", "src", "impl", "part", "label", "x"])
ELEMENT_LIKE = st.dictionaries(ELEMENT_KEYS, JSON_VALUES | st.just("F") | st.just([0, 0, 1, 1]), max_size=8)
PAGE_LIKE = st.fixed_dictionaries(
    {
        "page": JSON_VALUES | st.integers(0, 3),
        "figure": JSON_VALUES | st.just("F"),
        "elements": st.lists(ELEMENT_LIKE, max_size=5),
    }
)
MAP_LIKE = st.fixed_dictionaries(
    {
        "format": st.just(MAP_FORMAT),
        "pdf": JSON_VALUES | st.just("figures.pdf"),
        "pdf_sha256": JSON_VALUES | st.just("0" * 64),
        "pages": st.lists(PAGE_LIKE, max_size=3),
    }
)


@st.composite
def valid_maps(draw) -> dict:
    """A map every rule accepts: up to three pages with distinct numbers, each a random tree under its root, the
    elements in any order, some with code lines."""
    numbers = draw(st.lists(st.integers(1, 40), max_size=3, unique=True))
    pages = []
    for k, number in enumerate(numbers):
        figure = "F%d" % k
        elements: list[dict] = [{"id": figure, "frac": [0, 0, 1, 1]}]
        for i in range(draw(st.integers(0, 6))):
            x = draw(st.floats(0, 0.9))
            y = draw(st.floats(0, 0.9))
            el = {
                "id": "%s/%d" % (figure, i),
                "parent": draw(st.sampled_from([e["id"] for e in elements])),
                "frac": [x, y, draw(st.floats(0.01, 1 - x)), draw(st.floats(0.01, 1 - y))],
            }
            if draw(st.booleans()):
                lo = draw(st.integers(1, 500))
                el["src"] = {"file": "src/f%d.py" % k, "lo": lo, "hi": lo + draw(st.integers(0, 50))}
            elements.append(el)
        pages.append({"page": number, "figure": figure, "elements": draw(st.permutations(elements))})
    return {"format": MAP_FORMAT, "pdf": "figures.pdf", "pdf_sha256": "a" * 64, "pages": pages}


class NeverRaises(unittest.TestCase):
    """parse_map answers every input with a value (coding rule R3: rejections are values)."""

    @given(st.binary(max_size=512))
    def test_any_bytes_give_a_map_or_a_rejection(self, raw):
        """Arbitrary bytes, JSON or not, never raise."""
        self.assertIsInstance(parse_map(raw, source_inside=anywhere), (FigureMap, MapRejected))

    @given(st.one_of(JSON_VALUES, MAP_LIKE))
    def test_any_json_gives_a_map_or_a_rejection(self, value):
        """Any JSON value - and objects shaped almost like a map whose keys hold anything - never raise."""
        raw = json.dumps(value).encode("ascii")
        self.assertIsInstance(parse_map(raw, source_inside=anywhere), (FigureMap, MapRejected))


class AcceptedMaps(unittest.TestCase):
    """Every map the rules accept is a set of trees, one per page, each rooted at its figure."""

    @given(valid_maps())
    def test_an_accepted_map_is_a_tree_per_page_rooted_at_its_figure(self, m):
        """The root is first, is the figure and covers the page; every other element's ancestors start at its parent
        and end at the root; find() returns each element with its page."""
        got = parse(m)
        self.assertIsInstance(got, FigureMap)
        for sent in m["pages"]:
            page = got.page(sent["page"])
            root = page.root()
            self.assertEqual((root.id, root.parent, root.frac), (sent["figure"], None, FULL_PAGE))
            self.assertEqual({e.id for e in page.elements}, {e["id"] for e in sent["elements"]})
            for el in page.elements[1:]:
                chain = page.ancestors(el)
                self.assertEqual((chain[0].id, chain[-1]), (el.parent, root))
                self.assertEqual(got.find(el.id), (page, el))

    @given(valid_maps())
    def test_unknown_keys_never_change_an_accepted_map(self, m):
        """Adding a key the format does not know, at every level, parses to an equal map."""
        extra = copy.deepcopy(m)
        extra["future"] = 1
        for p in extra["pages"]:
            p["future"] = [1]
            for el in p["elements"]:
                el["future"] = {"x": 1}
        self.assertEqual(parse(extra), parse(m))
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `uv run pytest -q tests/test_figmap.py`

Expected: collection fails with `ImportError: cannot import name 'figmap' from 'limn'`.

- [ ] **Step 4: Write `src/limn/figmap.py`**

```python
"""The element map a figure repository writes next to its PDF (limn-figure-map/1), parsed into values.

A figure document is a PDF - one figure per page - plus this map: per page, a tree of elements, each with its box on
the page (frac) and the lines of the code that drew it (src). The map takes the place SyncTeX has for a LaTeX
manuscript (docs/handbook/domain.md §여러 문서). Limn never runs the code that wrote it. The map is input: it is
parsed here once (coding rule R3) into frozen values, or into a MapRejected naming the first rule it breaks. The
format grows additively, so unknown keys are ignored; a repeated key is refused, since which value a reader keeps
would be a guess.

Pure: no file, subprocess or HTTP. The caller reads the bytes and passes source_inside, the path check of its
document's folder (limn.build.figure_source_check).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

from limn.pins.shapes import is_finite_num, is_int

MAP_FORMAT = "limn-figure-map/1"
MAP_SUFFIX = ".limnmap.json"
MAP_MAX_BYTES = 4 * 1024 * 1024
MAP_MAX_ELEMENTS = 5000  # per page
MAP_MAX_TEXT = 200  # characters of a figure, title, element id, part or label: pins store them
Frac: TypeAlias = tuple[float, float, float, float]  # x, y, w, h; top-left origin; page fractions

FRAC_EPS = 1e-6  # how far past the page edge a producer's float rounding may put x + w or y + h
FULL_PAGE: Frac = (0.0, 0.0, 1.0, 1.0)  # the root element's box: the whole page
DETAIL_TEXT_MAX = 80  # how much of the map's own text a rejection's detail quotes
_HEX = frozenset("0123456789abcdef")

MapRejectReason: TypeAlias = Literal[
    "too_large",
    "not_json",
    "bad_format",
    "bad_shape",
    "bad_page",
    "bad_frac",
    "duplicate_id",
    "bad_parent",
    "no_root",
    "too_many_elements",
    "path_outside",
]


@dataclass(frozen=True)
class MapRejected:
    """Why a map is not used: the first rule it breaks (reason) and where in the map (detail - English, for logs;
    never shown as a contract value)."""

    reason: MapRejectReason
    detail: str


@dataclass(frozen=True)
class SourceRef:
    """Lines lo..hi (1-based, lo <= hi) of file, a path relative to the figure document's folder (Doc.src) with POSIX
    separators."""

    file: str
    lo: int
    hi: int


@dataclass(frozen=True)
class MapElement:
    """One element of a figure page: its id (unique in the map, stable across renders), its parent's id (None only for
    the page root), its box on the page, the code lines that called it (src - None for a vector graphic drawn without
    code, ADR-0011 D7), the lines of the shared component that implements it (impl), and the names a person sees
    (part, label)."""

    id: str
    parent: str | None
    frac: Frac
    src: SourceRef | None
    impl: SourceRef | None
    part: str | None
    label: str | None


@dataclass(frozen=True)
class MapPage:
    """One page of the figure PDF: its 1-based number, the figure's id (the root element's id), an optional title, and
    its elements with the root first and the rest in map order. The id index is built once, at construction."""

    page: int
    figure: str
    title: str | None
    elements: tuple[MapElement, ...]
    _by_id: dict[str, MapElement] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Index the elements by id; when an id repeats (parse_map never lets one), the first in order wins."""
        index: dict[str, MapElement] = {}
        for el in self.elements:
            index.setdefault(el.id, el)
        object.__setattr__(self, "_by_id", index)

    def root(self) -> MapElement:
        """The page's root element, the first element (parse_map puts it there). Precondition: the page has one."""
        return self.elements[0]

    def by_id(self, el_id: str) -> MapElement | None:
        """The element of this page whose id is el_id, or None."""
        return self._by_id.get(el_id)

    def ancestors(self, el: MapElement) -> tuple[MapElement, ...]:
        """el's parent, its parent, and so on up to the root: nearest first, root last; () for the root. The walk stops
        at a parent that is not on this page or already seen, so it ends even for a page built by hand."""
        out: list[MapElement] = []
        seen = {el.id}
        parent = el.parent
        while parent is not None and parent not in seen:
            node = self._by_id.get(parent)
            if node is None:
                break
            out.append(node)
            seen.add(parent)
            parent = node.parent
        return tuple(out)


@dataclass(frozen=True)
class FigureMap:
    """A parsed map: the PDF it describes (relative to the map file's folder), that PDF's SHA-256 (64 lowercase hex
    digits), and its pages in map order. Page numbers and element ids are indexed once, at construction."""

    pdf: str
    pdf_sha256: str
    pages: tuple[MapPage, ...]
    _by_page: dict[int, MapPage] = field(init=False, repr=False, compare=False)
    _by_id: dict[str, tuple[MapPage, MapElement]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Index the pages by number and the elements by id; the first in map order wins a repeat."""
        by_page: dict[int, MapPage] = {}
        by_id: dict[str, tuple[MapPage, MapElement]] = {}
        for p in self.pages:
            by_page.setdefault(p.page, p)
            for el in p.elements:
                by_id.setdefault(el.id, (p, el))
        object.__setattr__(self, "_by_page", by_page)
        object.__setattr__(self, "_by_id", by_id)

    def page(self, n: int) -> MapPage | None:
        """The page numbered n (1-based), or None when the map has none."""
        return self._by_page.get(n)

    def find(self, el_id: str) -> tuple[MapPage, MapElement] | None:
        """The page and the element whose id is el_id, or None."""
        return self._by_id.get(el_id)


def parse_map(raw: bytes, *, source_inside: Callable[[str], bool]) -> FigureMap | MapRejected:
    """The map raw holds, or the first rule it breaks, in this order: the size (at most MAP_MAX_BYTES, checked before
    decoding: too_large); UTF-8 JSON with no repeated key and no nesting deeper than the decoder's stack (not_json); a
    top-level object (bad_shape); format (bad_format); pdf a non-empty string and pdf_sha256 64 lowercase hex digits
    (bad_shape); pages a list; then each page in map order (_page). The names a pin stores - figure, title, element
    id, part, label - are at most MAP_MAX_TEXT characters (bad_shape). Unknown keys are ignored everywhere. Never
    raises. source_inside is asked about every src.file and impl.file and must not raise either."""
    if len(raw) > MAP_MAX_BYTES:
        return MapRejected("too_large", "%d bytes > %d" % (len(raw), MAP_MAX_BYTES))
    try:
        top = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (ValueError, RecursionError) as e:
        return MapRejected("not_json", str(e)[:200])
    if not isinstance(top, dict):
        return MapRejected("bad_shape", "the map is not a JSON object")
    if top.get("format") != MAP_FORMAT:
        return MapRejected("bad_format", "format is %s, not %r" % (_short(top.get("format")), MAP_FORMAT))
    pdf = _text(top.get("pdf"))
    if not pdf:
        return MapRejected("bad_shape", "pdf must be a non-empty string")
    sha = top.get("pdf_sha256")
    if not (isinstance(sha, str) and len(sha) == 64 and set(sha) <= _HEX):
        return MapRejected("bad_shape", "pdf_sha256 must be 64 lowercase hex digits")
    raw_pages = top.get("pages")
    if not isinstance(raw_pages, list):
        return MapRejected("bad_shape", "pages must be a list")
    pages: list[MapPage] = []
    numbers: set[int] = set()
    ids: set[str] = set()
    for i, p in enumerate(raw_pages):
        page = _page(p, "pages[%d]" % i, numbers, ids, source_inside)
        if isinstance(page, MapRejected):
            return page
        pages.append(page)
    return FigureMap(pdf, sha, tuple(pages))


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """json's object hook: a JSON object as a dict. A repeated key raises ValueError, which parse_map answers
    not_json - which of two values a reader keeps is ambiguous."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("repeated key %r" % key[:DETAIL_TEXT_MAX])
        out[key] = value
    return out


def _short(v: object) -> str:
    """A map value for a rejection's detail: a string, number, boolean or null cut to DETAIL_TEXT_MAX characters;
    otherwise only its JSON type (a huge or deep value is never rendered)."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return repr(v)[:DETAIL_TEXT_MAX]
    return type(v).__name__


def _text(v: object) -> str | None:
    """v when it is a string UTF-8 can encode, else None. json.loads lets an escaped lone surrogate through, and such
    a string could never be written to pins.md."""
    if not isinstance(v, str):
        return None
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return v


def _name(v: object) -> str | None:
    """v when it is a non-empty string UTF-8 can encode (_text) of at most MAP_MAX_TEXT characters - a figure id or
    an element id, which pins store - else None."""
    text = _text(v)
    return text if text and len(text) <= MAP_MAX_TEXT else None


def _opt_text(v: object, where: str) -> str | None | MapRejected:
    """An optional name a person sees (title, part, label): None when absent or null, the string when it is one
    (_text) of at most MAP_MAX_TEXT characters, else bad_shape."""
    if v is None:
        return None
    text = _text(v)
    if text is None or len(text) > MAP_MAX_TEXT:
        return MapRejected("bad_shape", "%s must be a string of at most %d characters, or absent" % (where, MAP_MAX_TEXT))
    return text


def _int(v: object) -> int | None:
    """v when it is a JSON integer (not a boolean), else None."""
    return v if is_int(v) else None


def _page(
    v: object, where: str, numbers: set[int], ids: set[str], source_inside: Callable[[str], bool]
) -> MapPage | MapRejected:
    """One page, or the first rule it breaks: an object (bad_shape); page a JSON integer >= 1 no earlier page used
    (bad_page); figure a non-empty string and title absent or a string (bad_shape); elements a list (bad_shape) of at
    most MAP_MAX_ELEMENTS, counted before any is read (too_many_elements); each element (_element, ids unique across
    the map); exactly one root (_rooted: no_root); every parent on this page and no cycle (_tree_rejection:
    bad_parent). figure and title are at most MAP_MAX_TEXT characters. numbers and ids collect what this page uses,
    for the pages after it."""
    if not isinstance(v, dict):
        return MapRejected("bad_shape", "%s is not an object" % where)
    number = _int(v.get("page"))
    if number is None or number < 1 or number in numbers:
        return MapRejected("bad_page", "%s.page must be an unused integer >= 1, not %s" % (where, _short(v.get("page"))))
    numbers.add(number)
    figure = _name(v.get("figure"))
    if figure is None:
        return MapRejected("bad_shape", "%s.figure must be a non-empty string of at most %d characters" % (where, MAP_MAX_TEXT))
    title = _opt_text(v.get("title"), where + ".title")
    if isinstance(title, MapRejected):
        return title
    raw_elements = v.get("elements")
    if not isinstance(raw_elements, list):
        return MapRejected("bad_shape", "%s.elements must be a list" % where)
    if len(raw_elements) > MAP_MAX_ELEMENTS:
        return MapRejected(
            "too_many_elements", "%s has %d elements > %d" % (where, len(raw_elements), MAP_MAX_ELEMENTS)
        )
    elements: list[MapElement] = []
    for j, e in enumerate(raw_elements):
        el = _element(e, "%s.elements[%d]" % (where, j), ids, source_inside)
        if isinstance(el, MapRejected):
            return el
        elements.append(el)
    ordered = _rooted(elements, figure, where)
    if isinstance(ordered, MapRejected):
        return ordered
    broken = _tree_rejection(ordered, where)
    if broken is not None:
        return broken
    return MapPage(number, figure, title, ordered)


def _element(v: object, where: str, ids: set[str], source_inside: Callable[[str], bool]) -> MapElement | MapRejected:
    """One element, or the first rule it breaks: an object (bad_shape); id a non-empty string of at most MAP_MAX_TEXT
    characters (bad_shape) not used earlier in the map (duplicate_id); parent absent, null or a non-empty string
    (bad_shape); frac (_frac: bad_frac); src and impl (_source: bad_shape, path_outside); part and label absent or
    strings of at most MAP_MAX_TEXT characters (bad_shape). The id is added to ids."""
    if not isinstance(v, dict):
        return MapRejected("bad_shape", "%s is not an object" % where)
    el_id = _name(v.get("id"))
    if el_id is None:
        return MapRejected("bad_shape", "%s.id must be a non-empty string of at most %d characters" % (where, MAP_MAX_TEXT))
    if el_id in ids:
        return MapRejected("duplicate_id", "%s.id %r is used earlier in the map" % (where, el_id[:DETAIL_TEXT_MAX]))
    ids.add(el_id)
    parent: str | None = None
    if v.get("parent") is not None:
        parent = _text(v.get("parent"))
        if not parent:
            return MapRejected("bad_shape", "%s.parent must be a non-empty string or absent" % where)
    frac = _frac(v.get("frac"), where + ".frac")
    if isinstance(frac, MapRejected):
        return frac
    src = _source(v.get("src"), where + ".src", source_inside)
    if isinstance(src, MapRejected):
        return src
    impl = _source(v.get("impl"), where + ".impl", source_inside)
    if isinstance(impl, MapRejected):
        return impl
    part = _opt_text(v.get("part"), where + ".part")
    if isinstance(part, MapRejected):
        return part
    label = _opt_text(v.get("label"), where + ".label")
    if isinstance(label, MapRejected):
        return label
    return MapElement(el_id, parent, frac, src, impl, part, label)


def _frac(v: object, where: str) -> Frac | MapRejected:
    """[x, y, w, h] as page fractions with the origin at the top left, or bad_frac: four finite JSON numbers
    (limn.pins.shapes.is_finite_num) with 0 <= x, 0 <= y, w > 0, h > 0, x + w <= 1 + FRAC_EPS and
    y + h <= 1 + FRAC_EPS."""
    if not (isinstance(v, list) and len(v) == 4 and all(is_finite_num(n) for n in v)):
        return MapRejected("bad_frac", "%s must be four finite numbers" % where)
    x, y, w, h = float(v[0]), float(v[1]), float(v[2]), float(v[3])
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1 + FRAC_EPS or y + h > 1 + FRAC_EPS:
        return MapRejected("bad_frac", "%s = [%g, %g, %g, %g] is not a box on the page" % (where, x, y, w, h))
    return x, y, w, h


def _source(v: object, where: str, source_inside: Callable[[str], bool]) -> SourceRef | None | MapRejected:
    """An optional {file, lo, hi}: None when absent or null (a vector graphic without code, ADR-0011 D7); bad_shape
    unless an object whose file is a non-empty string and lo, hi JSON integers with 1 <= lo <= hi; path_outside when
    source_inside refuses file."""
    if v is None:
        return None
    if not isinstance(v, dict):
        return MapRejected("bad_shape", "%s must be an object {file, lo, hi}" % where)
    file = _text(v.get("file"))
    lo, hi = _int(v.get("lo")), _int(v.get("hi"))
    if not file or lo is None or hi is None or not 1 <= lo <= hi:
        return MapRejected("bad_shape", "%s must be {file, lo, hi} with 1 <= lo <= hi" % where)
    if not source_inside(file):
        return MapRejected("path_outside", "%s.file %r is outside the figure's folder" % (where, file[:DETAIL_TEXT_MAX]))
    return SourceRef(file, lo, hi)


def _rooted(elements: list[MapElement], figure: str, where: str) -> tuple[MapElement, ...] | MapRejected:
    """The elements with the page root first and the rest in map order, or no_root unless exactly one element has no
    parent, its id is the page's figure and its frac is the whole page (FULL_PAGE)."""
    roots = [el for el in elements if el.parent is None]
    if len(roots) != 1 or roots[0].id != figure or roots[0].frac != FULL_PAGE:
        return MapRejected(
            "no_root",
            "%s needs exactly one element without parent, with id %r and frac [0, 0, 1, 1]"
            % (where, figure[:DETAIL_TEXT_MAX]),
        )
    root = roots[0]
    return (root,) + tuple(el for el in elements if el is not root)


def _tree_rejection(elements: tuple[MapElement, ...], where: str) -> MapRejected | None:
    """bad_parent when a parent names no element of this page, or when following the parents from an element never
    reaches the root (a cycle); None for a tree. elements has the root first. The walk is iterative and marks what
    reaches the root, so a chain of MAP_MAX_ELEMENTS elements costs one pass."""
    by_id = {el.id: el for el in elements}
    for el in elements:
        if el.parent is not None and el.parent not in by_id:
            return MapRejected(
                "bad_parent", "%s: parent %r of %r is not on this page" % (where, el.parent[:80], el.id[:80])
            )
    reaches = {elements[0].id}
    for el in elements:
        walk: list[str] = []
        on_walk: set[str] = set()
        cur = el
        while cur.id not in reaches:
            if cur.id in on_walk or cur.parent is None:
                return MapRejected("bad_parent", "%s: %r is on a parent cycle" % (where, cur.id[:DETAIL_TEXT_MAX]))
            walk.append(cur.id)
            on_walk.add(cur.id)
            cur = by_id[cur.parent]
        reaches.update(walk)
    return None
```

- [ ] **Step 5: Run the tests and the type check**

Run: `uv run ruff check --fix src/limn/figmap.py tests/test_figmap.py tests/helpers.py && uv run ruff format src/limn/figmap.py tests/test_figmap.py tests/helpers.py && uv run pytest -q tests/test_figmap.py && uv run mypy`

Expected: all tests pass (21 tests, 68 subtests), and mypy prints `Success: no issues found`.

- [ ] **Step 6: Mutation check: drop the cycle guard and watch a test fail, then restore**

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/figmap.py 'if cur.id in on_walk or cur.parent is None:' 'if cur.parent is None:'
timeout 60 uv run pytest -q tests/test_figmap.py -k test_each_broken_rule_is_named -x
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/figmap.py 'if cur.parent is None:' 'if cur.id in on_walk or cur.parent is None:'
git diff --stat
```

Expected: the middle command does not pass (it hangs until `timeout` stops it, or fails): without the guard a cycle loops forever. After the restore, `git diff --stat` lists only this task's files.

- [ ] **Step 7: Commit**

```bash
git add src/limn/figmap.py tests/test_figmap.py tests/helpers.py
git commit -s -m "feat(figmap): parse the limn-figure-map/1 element map" -m "A pure parser turns a figure repository's map bytes into frozen pages and element trees, or a MapRejected naming the first rule broken: size before decoding, JSON without repeated keys, format, frac boxes, unique ids, one root per page, parents without cycles, and source paths the caller's check accepts. Unknown keys are ignored."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 2: Register figure documents

**Files:**
- Modify: `src/limn/documents.py` (`DocKind`, `Doc` docstring, `src`/`main`/`pdf_name` docstrings, `watches_files`; add `has_element_map`)
- Modify: `src/limn/features/administration/serve_documents.py` (imports, `DocSpec`, `DocExtendedNotTex` → `DocExtendedWrongKind`, `DocKindUnknown`, `DocSpecRefusal`, `parse_doc_arg`, `doc_refusal_message`, `doc_start_line`)
- Modify: `src/limn/features/administration/instance_documents.sh:4-9,33-64`
- Modify: `src/limn/args.py` (`--doc` help)
- Test: `src/limn/features/administration/test_serve_documents.py` (new class `FigureRegistration`), `src/limn/features/document_views/test_meta.py` (`CAPABILITY_TABLE`, new class `FigureDocumentReads`), `tests/test_startup.py` (`DocArgs`), `tests/test_instances.sh` (§8)

**Interfaces:**
- Consumes: `figmap.MAP_SUFFIX` (Task 1); P0's `DocKind`, `kind_builds_from_source`, `doc_start_line`, the capability properties.
- Produces:
  - `DocKind: TypeAlias = Literal["tex", "pdf", "figure"]`
  - `Doc.watches_files` true for `"pdf"` and `"figure"`; `Doc.has_element_map -> bool` true only for `"figure"`
  - `Doc.pdf_name` for a figure document: the map's name without `MAP_SUFFIX` plus `.pdf` (`figures.limnmap.json` → `figures.pdf`)
  - `serve_documents.DocExtendedWrongKind(key: str, main: Path)` (replaces `DocExtendedNotTex`)
  - `parse_doc_arg` returns `kind="figure"`, `src=<ROOT>` for `ROOT::REL/x.limnmap.json`, else `src=<the map's folder>`

- [ ] **Step 1: Write the failing registration tests**

In `src/limn/features/administration/test_serve_documents.py`, extend the imports at the top so they read:

```python
import tempfile
import unittest
from pathlib import Path

from limn.documents import RunPaths
from limn.features.administration import serve_documents
from limn.features.administration.serve_documents import (
    DocExtendedWrongKind,
    DocFileMissing,
    DocKindUnknown,
    DocMainOutsideRoot,
    DocOutsideManuscript,
    RunDocuments,
)
from limn.figmap import MAP_SUFFIX
from limn.startup import StartupRefused
```

Append:

```python
class FigureRegistration(unittest.TestCase):
    """A --doc path ending in figmap.MAP_SUFFIX registers a figure document (docs/handbook/domain.md §여러 문서): its
    folder is the root before '::' or the map's folder, and every other suffix stays refused."""

    def setUp(self):
        """A manuscript with a body, a view-only PDF, a figure map under figs/out, a plain .json beside it, an
        upper-case map name in another folder, and a map outside the manuscript."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.ms = root / "repo"
        (self.ms / "figs" / "out").mkdir(parents=True)
        (self.ms / "figs" / "upper").mkdir()
        (self.ms / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (self.ms / "review.pdf").write_bytes(b"%PDF-1.4\n")
        self.map = self.ms / "figs" / "out" / "figures.limnmap.json"
        self.map.write_text("{}", encoding="utf-8")
        (self.ms / "figs" / "out" / "figures.json").write_text("{}", encoding="utf-8")
        (self.ms / "figs" / "upper" / "Figures.LIMNMAP.JSON").write_text("{}", encoding="utf-8")
        (root / "outside.limnmap.json").write_text("{}", encoding="utf-8")
        self.paths = RunPaths(self.ms, self.ms / "main.tex", root / "state")

    def test_a_map_path_is_a_figure_document_rooted_at_the_maps_folder(self):
        """Without '::' the document's folder - the base of the map's source paths - is the folder holding the map."""
        d = serve_documents.parse_doc_arg("fig=그림:figs/out/figures.limnmap.json", self.ms)
        self.assertEqual((d["kind"], d["src"], d["main"]), ("figure", self.ms / "figs" / "out", self.map))

    def test_the_root_form_roots_a_figure_document_at_the_folder_before_the_separator(self):
        """ROOT::REL/x.limnmap.json keeps the map as main and makes ROOT the document's folder."""
        d = serve_documents.parse_doc_arg("fig=그림:figs::out/figures.limnmap.json", self.ms)
        self.assertEqual((d["kind"], d["src"], d["main"]), ("figure", self.ms / "figs", self.map))

    def test_a_missing_map_refuses_startup_like_a_missing_file(self):
        """A map that does not exist is DocFileMissing, and the server refuses to start with the same words a missing
        view-only PDF gets."""
        missing = self.ms / "figs" / "out" / "none.limnmap.json"
        self.assertEqual(
            serve_documents.parse_doc_arg("fig=그림:figs/out/none.limnmap.json", self.ms), DocFileMissing("fig", missing)
        )
        self.assertEqual(
            serve_documents.pick_documents(self.ms, ["ms=본문:main.tex", "fig=그림:figs/out/none.limnmap.json"], None),
            StartupRefused("--doc fig: 파일이 없습니다: %s" % missing),
        )

    def test_only_the_exact_map_suffix_names_a_figure(self):
        """A plain .json and an upper-case suffix are unknown kinds, and the refusal lists every accepted suffix
        (docs/handbook/code-style-roadmap.md §R10)."""
        for rel in ("figs/out/figures.json", "figs/upper/Figures.LIMNMAP.JSON"):
            with self.subTest(rel=rel):
                got = serve_documents.parse_doc_arg("fig=그림:" + rel, self.ms)
                self.assertEqual(got, DocKindUnknown("fig", self.ms / rel))
                self.assertEqual(
                    serve_documents.doc_refusal_message(got),
                    "--doc fig: .tex(LaTeX), .pdf(보기 전용), .limnmap.json(그림)만 받습니다: %s" % (self.ms / rel),
                )

    def test_the_root_form_takes_latex_or_a_map_and_refuses_a_pdf(self):
        """'::' is for a document with a folder of its own: a LaTeX main or a figure map, never a view-only PDF."""
        got = serve_documents.parse_doc_arg("rv=코멘트:.::review.pdf", self.ms)
        self.assertEqual(got, DocExtendedWrongKind("rv", self.ms / "review.pdf"))
        self.assertEqual(
            serve_documents.doc_refusal_message(got),
            "--doc rv: '::' 표기는 LaTeX 문서(.tex)와 그림 지도(.limnmap.json)에만 씁니다: %s" % (self.ms / "review.pdf"),
        )

    def test_a_map_outside_the_manuscript_or_its_root_is_refused(self):
        """A map reached through ../ from the manuscript, or from the root of the '::' form, is refused before its
        existence is checked."""
        self.assertEqual(
            serve_documents.parse_doc_arg("fig=그림:../outside.limnmap.json", self.ms),
            DocOutsideManuscript("fig", "path", self.ms, self.ms.parent / "outside.limnmap.json"),
        )
        self.assertEqual(
            serve_documents.parse_doc_arg("fig=그림:figs::../main.limnmap.json", self.ms),
            DocMainOutsideRoot("fig", self.ms / "main.limnmap.json"),
        )

    def test_a_figure_document_is_watched_view_only_and_keeps_its_own_folder(self):
        """Keyed main, a figure document still gets docs/main (only a document built from source takes the state
        root); it is watched, view-only, has an element map, and its PDF copy is named after the map."""
        docs = serve_documents.make_docs(
            ["main=그림:figs::out/figures.limnmap.json", "ms=본문:main.tex"], self.ms, self.paths
        )
        fig = docs[0]
        self.assertEqual(
            (fig.kind, fig.root, fig.dir, fig.pdf_name),
            ("figure", False, self.paths.state / "docs" / "main", "figures.pdf"),
        )
        self.assertEqual(
            (
                fig.builds_from_source,
                fig.watches_files,
                fig.takes_line_pins,
                fig.shows_revisions,
                fig.view_only,
                fig.has_element_map,
            ),
            (False, True, False, False, True, True),
        )

    def test_the_run_main_is_never_a_figure_map(self):
        """The run's main file is the first document built from source, even behind a figure document."""
        got = serve_documents.pick_documents(
            self.ms, ["fig=그림:figs/out/figures.limnmap.json", "ms=본문:main.tex"], None
        )
        self.assertIsInstance(got, RunDocuments)
        self.assertEqual(got.main, self.ms / "main.tex")

    def test_the_startup_line_names_a_figure(self):
        """A figure document's startup line reads 'figure' in the label column, aligned with 'view-only'."""
        self.assertEqual(
            serve_documents.doc_start_line("fig", "figure", "figs/out/figures.limnmap.json", False),
            "doc    fig        figure    figs/out/figures.limnmap.json",
        )

    def test_the_shell_mirror_accepts_the_same_suffix(self):
        """instance_documents.sh names the Python suffix in both of its case patterns, so limn add and the server agree."""
        sh = (Path(serve_documents.__file__).parent / "instance_documents.sh").read_text(encoding="utf-8")
        self.assertEqual(sh.count("*" + MAP_SUFFIX), 2)
```

In `src/limn/features/document_views/test_meta.py`, replace P0's `CAPABILITY_TABLE` with:

```python
# The capability table of the shared contract (docs/superpowers/plans/2026-09-30-figure-documents.md, Shared contract).
# A new DocKind value adds its row here before any branch can serve it.
CAPABILITY_TABLE = {
    "tex": {
        "builds_from_source": True,
        "watches_files": False,
        "takes_line_pins": True,
        "shows_revisions": True,
        "view_only": False,
        "has_element_map": False,
    },
    "pdf": {
        "builds_from_source": False,
        "watches_files": True,
        "takes_line_pins": False,
        "shows_revisions": False,
        "view_only": True,
        "has_element_map": False,
    },
    "figure": {
        "builds_from_source": False,
        "watches_files": True,
        "takes_line_pins": False,
        "shows_revisions": False,
        "view_only": True,
        "has_element_map": True,
    },
}
```

and append to the same file, after `DocumentFactsReads`:

```python
class FigureDocumentReads(Fixture):
    """A figure document (a map under figs/out, the document's folder figs/) as the reads and lookups see it."""

    def setUp(self):
        """The fixture tree plus figs/out/figures.limnmap.json and the figure document fig."""
        super().setUp()
        (self.src / "figs" / "out").mkdir(parents=True)
        self.map = self.src / "figs" / "out" / "figures.limnmap.json"
        self.map.write_text("{}", encoding="utf-8")
        self.fig = Doc("fig", "그림", "figure", self.src / "figs", self.map, paths=self.paths)

    def test_the_copy_of_its_pdf_is_named_after_the_map(self):
        """pages-<build>/ holds figures.pdf for figures.limnmap.json - never figures.limnmap.pdf."""
        self.assertEqual(self.fig.pdf_name, "figures.pdf")

    def test_its_brief_and_meta_report_kind_figure_view_only_and_never_stale(self):
        """/api/docs and /api/meta say kind figure and view_only true; a map newer than the pages is not 'stale'
        (only a document built from source is), and path and main name the map."""
        self.pages(self.fig)
        later = time.time() + 60
        os.utime(self.map, (later, later))
        brief = meta.doc_brief(self.fig, self.state)
        self.assertEqual(
            (brief["kind"], brief["view_only"], brief["stale_build"], brief["main"], brief["path"]),
            ("figure", True, False, "figures.limnmap.json", "figs/out/figures.limnmap.json"),
        )
        out = meta.meta(self.fig, {}, self.settings, [self.ms, self.fig], {}, time.time())
        self.assertEqual((out["kind"], out["view_only"], out["stale_build"]), ("figure", True, False))

    def test_it_has_no_outline_labels(self):
        """Nothing is compiled, so no .aux is read even if a file of that name sits in its page directory."""
        d = self.pages(self.fig, aux=AUX)
        self.assertEqual(meta.outline_labels(self.fig), {"build": d.name, "labels": []})

    def test_a_file_under_a_figure_folder_routes_to_the_latex_document_around_it(self):
        """The figure folder lies inside the body's build root and deeper: a file-only request (agent curl) still goes
        to the LaTeX document, since a figure document takes no line pin."""
        docs = [self.fig, self.ms]
        self.assertIs(documents.doc_for_file(docs, self.src, "figs/src/B2_calendar.py"), self.ms)
```

In `tests/test_startup.py`, replace `DocExtendedNotTex,` in the import list with `DocExtendedWrongKind,`. In `DocArgs.test_rejects_bad_specs`, replace the two cases:

```python
            (
                "rr=답변서:notes.txt",
                DocKindUnknown("rr", ms / "notes.txt"),
                "--doc rr: .tex(LaTeX) 또는 .pdf(보기 전용)만 받습니다: %s" % (ms / "notes.txt"),
            ),
            (
                "rv=코멘트:sub::review.pdf",
                DocExtendedNotTex("rv", ms / "sub" / "review.pdf"),
                "--doc rv: '::' 표기는 LaTeX 문서(.tex)에만 씁니다: %s" % (ms / "sub" / "review.pdf"),
            ),
```

with:

```python
            (
                "rr=답변서:notes.txt",
                DocKindUnknown("rr", ms / "notes.txt"),
                "--doc rr: .tex(LaTeX), .pdf(보기 전용), .limnmap.json(그림)만 받습니다: %s" % (ms / "notes.txt"),
            ),
            (
                "rv=코멘트:sub::review.pdf",
                DocExtendedWrongKind("rv", ms / "sub" / "review.pdf"),
                "--doc rv: '::' 표기는 LaTeX 문서(.tex)와 그림 지도(.limnmap.json)에만 씁니다: %s"
                % (ms / "sub" / "review.pdf"),
            ),
```

- [ ] **Step 2: Write the failing shell tests**

In `tests/test_instances.sh` §8, insert before the line `chk "a rejected --doc add leaves no config behind" "[[ ! -e '$T/src/docs-x.env' ]]"`:

```bash
mkdir -p "$ms/figs/out"
printf '{"format": "limn-figure-map/1"}\n' > "$ms/figs/out/figures.limnmap.json"
printf '{}\n' > "$ms/figs/out/figures.json"
chk "rejects a .json that is not a figure map (.limnmap.json)" "! '$PV' add docs-x --manuscript '$ms' --doc 'x=그림:figs/out/figures.json' --no-start >/dev/null 2>&1"
chk "rejects a figure map that does not exist" "! '$PV' add docs-x --manuscript '$ms' --doc 'x=그림:figs/out/none.limnmap.json' --no-start >/dev/null 2>&1"
chk "the '::' form still rejects a view-only PDF" "! '$PV' add docs-x --manuscript '$ms' --doc 'x=제출본:submission::submission_ready/manuscript.pdf' --no-start >/dev/null 2>&1"
```

After the line `chk "add output (snippet) shows the doc key list and the #doc= link" …` (the end of the `docs-1` block), insert:

```bash
out=$("$PV" add docs-fig --manuscript "$ms" --no-serve \
    --doc 'ms=본문:main.tex' \
    --doc 'fig=그림:figs::out/figures.limnmap.json' \
    --doc 'fg=그림 폴더:figs/out/figures.limnmap.json' \
    --no-start 2>&1)
rc=$?
chk "a figure map is accepted in the ROOT:: form and as a plain path" "[[ $rc -eq 0 ]]"
chk "DOCS keeps the figure entries as given" \
    "grep -qx 'DOCS=\"ms=본문:main.tex;fig=그림:figs::out/figures.limnmap.json;fg=그림 폴더:figs/out/figures.limnmap.json\"' '$T/src/docs-fig.env'"
"$PV" remove docs-fig > /dev/null 2>&1
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `uv run pytest -q src/limn/features/administration/test_serve_documents.py src/limn/features/document_views/test_meta.py tests/test_startup.py; bash tests/test_instances.sh 2>&1 | grep -E "✗|passed|failed" | head`

Expected:
- `test_serve_documents.py` and `tests/test_startup.py` fail to collect: `ImportError: cannot import name 'DocExtendedWrongKind'`.
- `test_meta.py` fails `Capabilities::test_the_table_has_a_row_for_every_document_kind` (the table has a `figure` row that `DocKind` lacks) and `FigureDocumentReads` (a `KeyError` or a wrong kind).
- The shell run prints `✗` for `a figure map is accepted in the ROOT:: form and as a plain path` and for `DOCS keeps the figure entries as given`.

- [ ] **Step 4: Add the kind and its capabilities to `documents.py`**

In `src/limn/documents.py`, add `from limn.figmap import MAP_SUFFIX` after `from limn.files import ManuscriptFile, tex_lines`.

Replace P0's `DocKind: TypeAlias = Literal["tex", "pdf"]` with:

```python
DocKind: TypeAlias = Literal["tex", "pdf", "figure"]
```

In the comment block above it, replace `an instance started without --doc serves one "tex" document.` with `an instance started without --doc serves one "tex" document; a path ending in limn.figmap.MAP_SUFFIX is a "figure".`

In the `Doc` docstring, replace P0's first sentences

```python
    """One document of a kind (DocKind): 'tex' is LaTeX, lines traced back via SyncTeX; 'pdf' is a view-only PDF,
    pinned by page and region.
```

with:

```python
    """One document of a kind (DocKind): 'tex' is LaTeX, lines traced back via SyncTeX; 'pdf' is a view-only PDF,
    pinned by page and region; 'figure' is a PDF a figure repository renders with its element map (limn.figmap),
    imported rather than built.
```

Replace the docstrings of `src`, `main` and the whole `pdf_name` property:

```python
    @property
    def src(self) -> Path:
        """Build root - the scope copied into the build copy. For view-only, the folder holding the PDF; for a figure
        document, its folder - the base of the map's source paths (the root before '::', else the map's folder)."""
```

```python
    @property
    def main(self) -> Path:
        """The main .tex for LaTeX, the PDF file for view-only, the element map for a figure document."""
```

```python
    @property
    def pdf_name(self) -> str:
        """Name of the PDF copy inside the page directory: the main file's stem + .pdf, and for a document with an
        element map the map's name without MAP_SUFFIX + .pdf (figures.limnmap.json -> figures.pdf)."""
        if self.has_element_map:
            return self.main.name.removesuffix(MAP_SUFFIX) + ".pdf"
        return self.main.stem + ".pdf"
```

Replace P0's `watches_files` and add `has_element_map` after `view_only`:

```python
    @property
    def watches_files(self) -> bool:
        """The watch thread brings in new pages when its files change - a view-only PDF's file, a figure document's
        map and the PDF the map names - and startup does so when they changed since the last time (--no-build or
        not)."""
        return self.kind in ("pdf", "figure")
```

```python
    @property
    def has_element_map(self) -> bool:
        """Its pages come with a producer-written element map (limn.figmap) - a figure document: the watch imports the
        map with the PDF it names instead of rendering one file, and every page directory keeps the map it was
        imported with."""
        return self.kind == "figure"
```

- [ ] **Step 5: Parse the map suffix in `serve_documents.py`**

In `src/limn/features/administration/serve_documents.py`, add `from limn.figmap import MAP_SUFFIX` after the `limn.documents` import.

Replace the `DocSpec` docstring with:

```python
    """One parsed --doc: key, display name, kind (the DocKind its path's suffix names: .tex, .pdf or
    limn.figmap.MAP_SUFFIX), build root (src - for a figure document the base of its map's source paths) and main
    file, both resolved."""
```

Replace the class `DocExtendedNotTex` with:

```python
@dataclass(frozen=True)
class DocExtendedWrongKind:
    """The '::' form names a main file that is neither .tex nor a figure map (MAP_SUFFIX) - the form gives a LaTeX or
    a figure document a folder of its own, and a view-only PDF has none."""

    key: str
    main: Path
```

Replace the `DocKindUnknown` docstring with `"""The main file is neither .tex (LaTeX), .pdf (view-only) nor a figure map (MAP_SUFFIX, exact case)."""`. In `DocSpecRefusal`, replace `| DocExtendedNotTex` with `| DocExtendedWrongKind`.

In `parse_doc_arg`'s docstring, after the `x/review.pdf` bullet, add:

```python
    - `<key>=<name>:x/figures.limnmap.json` - a figure document (limn.figmap.MAP_SUFFIX, exact case): its PDF and
      element map are imported, never built; its folder, the base of the map's source paths, is x.
    - `<key>=<name>:a::b/figures.limnmap.json` - a figure document whose folder is a; the map is a/b/figures.limnmap.json.
```

In the `::` branch, replace:

```python
        if main.suffix.lower() != ".tex":
            return DocExtendedNotTex(key, main)
```

with:

```python
        if main.suffix.lower() != ".tex" and not main.name.endswith(MAP_SUFFIX):
            return DocExtendedWrongKind(key, main)
```

Replace P0's kind block (from `suf = main.suffix.lower()` to `return DocKindUnknown(key, main)`) with:

```python
    suf = main.suffix.lower()
    kind: DocKind
    if main.name.endswith(MAP_SUFFIX):
        kind = "figure"
    elif suf == ".tex":
        kind = "tex"
    elif suf == ".pdf":
        kind = "pdf"
    else:
        return DocKindUnknown(key, main)
```

In `doc_refusal_message`, replace the two cases:

```python
        case DocExtendedNotTex(key=key, main=main):
            return "--doc %s: '::' 표기는 LaTeX 문서(.tex)에만 씁니다: %s" % (key, main)
```

```python
        case DocKindUnknown(key=key, main=main):
            return "--doc %s: .tex(LaTeX) 또는 .pdf(보기 전용)만 받습니다: %s" % (key, main)
```

with:

```python
        case DocExtendedWrongKind(key=key, main=main):
            return "--doc %s: '::' 표기는 LaTeX 문서(.tex)와 그림 지도(%s)에만 씁니다: %s" % (key, MAP_SUFFIX, main)
```

```python
        case DocKindUnknown(key=key, main=main):
            return "--doc %s: .tex(LaTeX), .pdf(보기 전용), %s(그림)만 받습니다: %s" % (key, MAP_SUFFIX, main)
```

In P0's `doc_start_line`, add the third case after `case "pdf": label = "view-only"`:

```python
        case "figure":
            label = "figure   "
```

- [ ] **Step 6: Mirror the suffix in the shell and the help text**

In `src/limn/features/administration/instance_documents.sh`, replace the comment line `# (parse_doc_arg/make_docs in limn/startup.py) — the server re-validates on startup, but filtering` with `# (parse_doc_arg/make_docs in limn/features/administration/serve_documents.py; the figure-map suffix is limn.figmap.MAP_SUFFIX) — the server re-validates on startup, but filtering`. In the `doc_check_path` comment, replace `The `::` notation (<build root>::<main.tex>) checks` with `The `::` notation (<build root>::<main.tex or figure map>) checks`.

Replace the two `case` blocks in `doc_check_path`:

```bash
        case "${main##*.}" in
            tex) ;;
            *) die "--doc $key: '::' notation is only for LaTeX documents (.tex): $main" ;;
        esac
```

```bash
        case "${main##*.}" in
            tex | pdf) ;;
            *) die "--doc $key: only .tex (LaTeX) or .pdf (view-only) are accepted: $main" ;;
        esac
```

with:

```bash
        case "$main" in
            *.tex | *.limnmap.json) ;;
            *) die "--doc $key: '::' notation is only for LaTeX documents (.tex) and figure maps (.limnmap.json): $main" ;;
        esac
```

```bash
        case "$main" in
            *.tex | *.pdf | *.limnmap.json) ;;
            *) die "--doc $key: only .tex (LaTeX), .pdf (view-only) or .limnmap.json (figure) are accepted: $main" ;;
        esac
```

In `src/limn/args.py`, in the `--doc` help, replace `"<build root>::<main.tex> = build root given separately, .pdf = view-only. The first document is the default. "` with:

```python
        "<build root>::<main.tex> = build root given separately, .pdf = view-only, "
        ".limnmap.json = figure document (the PDF its element map names, imported; ROOT::map sets the map's source "
        "folder). The first document is the default. "
```

- [ ] **Step 7: Run the tests, the shell tests and the static gates**

Run:

```bash
uv run ruff check --fix src/limn/documents.py src/limn/features/administration/serve_documents.py src/limn/args.py src/limn/features/administration/test_serve_documents.py src/limn/features/document_views/test_meta.py tests/test_startup.py
uv run ruff format src/limn/documents.py src/limn/features/administration/serve_documents.py src/limn/args.py src/limn/features/administration/test_serve_documents.py src/limn/features/document_views/test_meta.py tests/test_startup.py
uv run pytest -q src/limn/features/administration/test_serve_documents.py src/limn/features/document_views/test_meta.py tests/test_startup.py tests/test_server.py -k "not Browser"
bash tests/test_instances.sh 2>&1 | tail -n 3
uv run shellcheck src/limn/instances.sh src/limn/features/administration/instance_*.sh tests/test_instances.sh
uv run mypy
```

Expected: pytest reports no failures; the shell run ends with its pass/fail summary showing `0` failed; shellcheck prints nothing; mypy prints `Success: no issues found` (an exhaustive-match error here means `doc_start_line` lacks `case "figure"`).

- [ ] **Step 8: Mutation check: collapse the two watched kinds and watch the table test fail, then restore**

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/documents.py 'return self.kind in ("pdf", "figure")' 'return self.kind == "pdf"'
uv run pytest -q src/limn/features/document_views/test_meta.py src/limn/features/administration/test_serve_documents.py -k "capabilities or watched"
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/documents.py 'return self.kind == "pdf"' 'return self.kind in ("pdf", "figure")'
git diff --stat
```

Expected: the middle command fails `Capabilities::test_each_kind_has_exactly_the_capabilities_of_its_table_row` and `FigureRegistration::test_a_figure_document_is_watched_view_only_and_keeps_its_own_folder`. After the restore, `git diff --stat` lists only this task's files.

- [ ] **Step 9: Commit**

```bash
git add src/limn/documents.py src/limn/features/administration/serve_documents.py src/limn/features/administration/instance_documents.sh src/limn/args.py src/limn/features/administration/test_serve_documents.py src/limn/features/document_views/test_meta.py tests/test_startup.py tests/test_instances.sh
git commit -s -m "feat(documents): register figure documents by their map suffix" -m "A --doc or DOCS= path ending in .limnmap.json is a figure document: kind figure, watched and view-only like a PDF, with an element map. ROOT::map sets the folder its source paths are relative to; without it the map's folder is used. A missing map refuses startup as a missing PDF does. The instance manager's shell check accepts the same suffix."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 3: Shared figure build facts in `build.py`

**Files:**
- Modify: `src/limn/build.py` (imports; new functions after `build_pdf`)
- Test: `tests/test_build.py` (imports; new class `FigureBuildFacts` before the "through server.py's wiring" banner)

**Interfaces:**
- Consumes: `figmap.MAP_MAX_BYTES`, `FigureMap`, `MapRejected`, `parse_map` (Task 1); `files.PATH_MAX_CHARS`; `BuildDoc.src`, `.main`, `.dir`.
- Produces (Contract issue 1):
  - `build.FIGMAP_NAME = "figmap.json"`
  - `build.figure_source_check(root: Path) -> Callable[[str], bool]`: the `source_inside` for `parse_map`
  - `build.figure_pdf(doc: BuildDoc, figure_map: FigureMap) -> Path | None`: the PDF a map names, inside `doc.src`
  - `build.load_build_map(doc: BuildDoc, build: str) -> FigureMap | MapRejected | None`
  - `build.build_figure_pdf(doc: BuildDoc, build: str) -> Path | None`

- [ ] **Step 1: Write the failing tests**

In `tests/test_build.py`, replace `from limn import build, build as limn_build, files` with `from limn import build, build as limn_build, figmap, files`, and extend the helpers import to `from helpers import MINI_PDF, Base, blank_png, figure_map, map_bytes, needs_tex, ps, req`.

Insert before the banner `# ---------------------------------------------------------------- through server.py's wiring`:

```python
class FigureBuildFacts(unittest.TestCase):
    """The figure build facts limn.build shares with the builds and pins slices: which map paths a figure document
    accepts, the PDF a map names, and the map a published build kept (docs/handbook/code-style-roadmap.md §R10)."""

    def setUp(self):
        """A manuscript with a figure folder figs/ (out/, src/, a dot folder, a symlink src/out-link to a folder
        outside the manuscript) served as figure document fig."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.figs = root / "ms" / "figs"
        for sub in ("out", "src", ".cache"):
            (self.figs / sub).mkdir(parents=True)
        (root / "elsewhere").mkdir()
        (self.figs / "src" / "out-link").symlink_to(root / "elsewhere")
        paths = RunPaths(root / "ms", root / "ms" / "main.tex", root / "state")
        self.doc = Doc("fig", "그림", "figure", self.figs, self.figs / "out" / "figures.limnmap.json", paths=paths)
        self.inside = build.figure_source_check(self.figs)

    def map_naming(self, pdf: str) -> figmap.FigureMap:
        """A map with no pages that names pdf."""
        return figmap.FigureMap(pdf, "0" * 64, ())

    def publish(self, name: str, raw: bytes) -> Path:
        """Page directory `name` of the figure document holding a map copy with bytes raw."""
        pdir = self.doc.dir / name
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / build.FIGMAP_NAME).write_bytes(raw)
        return pdir

    def test_a_source_path_is_accepted_only_inside_the_documents_folder(self):
        """Relative paths that resolve inside figs/ pass, existing or not; empty, absolute, escaping, dot-named,
        backslashed, NUL-holding, over-long and symlinked-out paths and the folder itself do not."""
        for rel in ("src/B2_calendar.py", "lib/components.py", "./src/a.py", "src/../lib/b.py"):
            self.assertTrue(self.inside(rel), rel)
        for rel in (
            "",
            "/etc/passwd",
            "../main.tex",
            "src/../../main.tex",
            ".cache/x.py",
            "src/.hidden/x.py",
            "src\\a.py",
            "src/a\x00.py",
            "src/out-link/x.py",
            "a" * 5000,
            ".",
        ):
            self.assertFalse(self.inside(rel), repr(rel[:40]))

    def test_the_pdf_a_map_names_is_resolved_from_the_maps_folder_inside_the_document(self):
        """pdf is relative to the folder holding the map and may step up, but only to a path inside figs/."""
        self.assertEqual(build.figure_pdf(self.doc, self.map_naming("figures.pdf")), self.figs / "out" / "figures.pdf")
        self.assertEqual(
            build.figure_pdf(self.doc, self.map_naming("../render/figures.pdf")), self.figs / "render" / "figures.pdf"
        )
        for pdf in ("../../outside.pdf", "/srv/paper/figures.pdf", ".figures.pdf", "../src/out-link/f.pdf"):
            self.assertIsNone(build.figure_pdf(self.doc, self.map_naming(pdf)), pdf)

    def test_a_published_build_map_is_read_back_or_absent(self):
        """A build with a map copy gives the map and the PDF it names; a build without one, a gone build and a name
        that is no page directory give None."""
        pdir = self.doc.dir / "pages-20260101000000"
        pdir.mkdir(parents=True)
        self.assertIsNone(build.load_build_map(self.doc, pdir.name))
        self.publish(pdir.name, map_bytes(figure_map(MINI_PDF)))
        self.assertIsInstance(build.load_build_map(self.doc, pdir.name), figmap.FigureMap)
        self.assertEqual(build.build_figure_pdf(self.doc, pdir.name), self.figs / "out" / "figures.pdf")
        for name in ("../pages-20260101000000", "pages-x", "", "figure-import", "pages-20260102000000"):
            self.assertIsNone(build.load_build_map(self.doc, name), name)
            self.assertIsNone(build.build_figure_pdf(self.doc, name), name)

    def test_a_published_map_is_checked_again_when_read(self):
        """The copy is parsed with the document's own source check: a source outside figs/ is path_outside, a copy
        over the size cap is too_large, and neither names a PDF."""
        m = figure_map(MINI_PDF)
        m["pages"][0]["elements"][0]["src"]["file"] = "../../main.tex"
        self.publish("pages-20260101000000", map_bytes(m))
        self.assertEqual(build.load_build_map(self.doc, "pages-20260101000000").reason, "path_outside")
        self.publish("pages-20260102000000", b" " * (figmap.MAP_MAX_BYTES + 10))
        self.assertEqual(build.load_build_map(self.doc, "pages-20260102000000").reason, "too_large")
        self.assertIsNone(build.build_figure_pdf(self.doc, "pages-20260101000000"))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest -q tests/test_build.py -k FigureBuildFacts`

Expected: 4 failed, `AttributeError: module 'limn.build' has no attribute 'figure_source_check'`.

- [ ] **Step 3: Add the figure build facts to `build.py`**

In `src/limn/build.py`, replace `from collections.abc import Iterator` with `from collections.abc import Callable, Iterator`, replace `from limn.files import atomic_write` with `from limn.files import PATH_MAX_CHARS, atomic_write`, and add `from limn.figmap import MAP_MAX_BYTES, FigureMap, MapRejected, parse_map` after the `limn.build_values` import block.

After the constant `BUILD_OUTDIRS = …`, add:

```python
FIGMAP_NAME = "figmap.json"  # a figure document's element map, copied into every page directory next to its PDF
```

After the function `build_pdf`, add:

```python
# ---------------------------------------------------------------- Figure documents: map paths and the per-build map
#
# A figure document's import (limn.features.builds.figure) publishes the map next to the PDF copy in every page
# directory. The pick and the pin input read it back per build; these readers live here, with the other shared build
# artifacts, so no feature imports another.


def _inside_folder(base: Path, start: Path, rel: str) -> Path | None:
    """rel - a path a figure map names, POSIX separators - resolved from the folder start, when it lies strictly inside
    base (already resolved) and no part below base starts with '.', the manuscript tree's rule for dot names
    (limn.files.tree_part). None for an empty, absolute or over-long path, one holding a backslash or a NUL, the folder
    base itself, or a path that cannot be resolved. Symlinks are resolved, so a link that leads out of base is outside.
    The file need not exist; only metadata is read."""
    if not rel or len(rel) > PATH_MAX_CHARS or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return None
    try:
        real = (start / rel).resolve()
        below = real.relative_to(base)
    except (ValueError, OSError, RuntimeError):
        return None
    if not below.parts or any(part.startswith(".") for part in below.parts):
        return None
    return real


def figure_source_check(root: Path) -> Callable[[str], bool]:
    """The source_inside limn.figmap.parse_map takes for a figure document whose folder (Doc.src) is root: a map's
    src.file or impl.file passes when _inside_folder finds it inside root, resolved from root itself. Answers are kept
    per path for the life of the returned check, so a map naming one script for many elements resolves it once. A
    root that cannot be resolved lets nothing pass."""
    try:
        base = root.resolve()
    except (OSError, RuntimeError):
        return lambda rel: False
    known: dict[str, bool] = {}

    def inside(rel: str) -> bool:
        """Whether rel lies inside the figure document's folder (remembered per path)."""
        if rel not in known:
            known[rel] = _inside_folder(base, base, rel) is not None
        return known[rel]

    return inside


def figure_pdf(doc: BuildDoc, figure_map: FigureMap) -> Path | None:
    """The PDF figure_map names, resolved from the folder holding doc's map (doc.main) and kept only when it lies inside
    doc.src (_inside_folder): the one path the import may read, or None. The file need not exist."""
    try:
        base = doc.src.resolve()
    except (OSError, RuntimeError):
        return None
    return _inside_folder(base, doc.main.parent, figure_map.pdf)


def load_build_map(doc: BuildDoc, build: str) -> FigureMap | MapRejected | None:
    """The element map published with page directory `build` of figure document doc (<doc.dir>/<build>/figmap.json),
    parsed with doc's own source check (figure_source_check of doc.src), so a copy is judged by today's folder. None
    when build is not a page directory name or that directory has no readable copy. Reads at most MAP_MAX_BYTES + 1
    bytes; a larger copy is MapRejected too_large."""
    if not valid_build_name(build):
        return None
    try:
        with open(doc.dir / build / FIGMAP_NAME, "rb") as fh:
            raw = fh.read(MAP_MAX_BYTES + 1)
    except OSError:
        return None
    return parse_map(raw, source_inside=figure_source_check(doc.src))


def build_figure_pdf(doc: BuildDoc, build: str) -> Path | None:
    """The source PDF named by the map published with page directory `build` of figure document doc (load_build_map,
    then figure_pdf), or None when that build has no loadable map or its pdf lies outside doc.src."""
    found = load_build_map(doc, build)
    return figure_pdf(doc, found) if isinstance(found, FigureMap) else None
```

- [ ] **Step 4: Run the tests and the gates**

Run: `uv run ruff check --fix src/limn/build.py tests/test_build.py && uv run ruff format src/limn/build.py tests/test_build.py && uv run pytest -q tests/test_build.py && uv run mypy`

Expected: all of `tests/test_build.py` passes, including `NoServerState` (the new text holds no `C.`); mypy prints `Success: no issues found`.

- [ ] **Step 5: Mutation check: allow dot names and watch the path test fail, then restore**

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/build.py 'if not below.parts or any(part.startswith(".") for part in below.parts):' 'if not below.parts:'
uv run pytest -q tests/test_build.py -k FigureBuildFacts
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/build.py 'if not below.parts:' 'if not below.parts or any(part.startswith(".") for part in below.parts):'
git diff --stat
```

Expected: the middle command fails `test_a_source_path_is_accepted_only_inside_the_documents_folder` and `test_the_pdf_a_map_names_is_resolved_from_the_maps_folder_inside_the_document`. After the restore, only this task's two files differ.

- [ ] **Step 6: Commit**

```bash
git add src/limn/build.py tests/test_build.py
git commit -s -m "feat(build): share the figure map paths and per-build map copy" -m "limn.build gains FIGMAP_NAME, the source check a figure map is parsed with, the PDF a map names, and the readers of the map copy a page directory keeps. Paths must resolve inside the figure document's folder, with no dot-named part and no symlink out. These live beside build_pdf so the builds and pins slices share them without importing each other."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 4: The import build, `features/builds/figure.py`

**Files:**
- Create: `src/limn/features/builds/figure.py`
- Modify: `src/limn/build_values.py:26-31` (`BuildFailureKind`, `AbortKind`), the `BuildAborted` docstring
- Modify: `src/limn/web/errors.py` (`BUILD_FAILURES`)
- Test: `src/limn/features/builds/test_figure.py` (create)

**Interfaces:**
- Consumes: `build.FIGMAP_NAME`, `build.figure_source_check`, `build.figure_pdf`, `build.page_list`, `build.cur_pages` (Task 3); `engine.render_pages`, `engine.commit_pages`; `figmap.parse_map`, `MAP_MAX_BYTES`, `FigureMap`, `MapRejected` (Task 1); `Doc(kind="figure")` (Task 2).
- Produces (Task 5 and Task 6 rely on these):
  - `AbortKind` gains `"figure_unready"`; `BUILD_FAILURES["figure_unready"] = "그림 PDF 와 지도를 가져오지 못했습니다: {detail}"`
  - `figure.FileRead(raw: bytes, signature: str)`
  - `figure.FigureImport(map_raw: bytes, figure_map: FigureMap, pdf_raw: bytes, signature: str)`
  - `figure.DeferReason = Literal["map_missing", "map_rejected", "pdf_outside", "pdf_missing", "pdf_mismatch"]`, `figure.ImportDeferred(reason, detail, signature: str | None)`
  - `figure.MapLooks()` (per-run memo; field `seen`)
  - `figure.watch_signature(D, looks) -> str | None`
  - `figure.import_due(now: str | None, settled: str | None, missing_pages: bool) -> bool` (pure)
  - `figure.read_figure_import(D) -> FigureImport | ImportDeferred`
  - `figure.accept_pdf(map_read: FileRead, figure_map: FigureMap, pdf_read: FileRead) -> FigureImport | ImportDeferred` (pure)
  - `figure.settled_signature(D) -> str | None`, `figure.settle(D, signature) -> None`
  - `figure.pending_import(D, looks, dpi, *, first: bool) -> FigureImport | None`
  - `figure.figure_src_hash(pdf_raw: bytes, map_raw: bytes) -> str` (pure)
  - `figure.render_figure_doc(D, cfg: BuildConfig, ready: FigureImport) -> BuildOk | BuildFailed`
  - `figure.import_now(D, cfg: BuildConfig, ready: FigureImport | None) -> BuildOk | BuildFailed | BuildAborted`
  - constants `figure.SIG_FILE = "pdf_sig.txt"`, `figure.STAGE_DIR = "figure-import"`, `figure.NO_FILE = "-"`

- [ ] **Step 1: Write the failing import tests**

Create `src/limn/features/builds/test_figure.py`:

```python
"""The import build of a figure document (limn.features.builds.figure) and, at the end, its wiring through server.py.

A figure repository writes a PDF, then its element map; Limn imports the pair only when the map's pdf_sha256 is the
PDF's SHA-256, renders exactly the bytes it checked, and keeps the map in the new page directory. Files that do not
agree yet are left alone - no build, no failure - until one of them changes again. The classes up to NoServerState
call the module on a real temporary tree with a fake pdftoppm on PATH (it copies a 200x100 PNG), so no Poppler is
needed; FigureDocumentThroughTheServer drives the same through server.py's build service and routes.

Run: uv run pytest -q src/limn/features/builds/test_figure.py
"""

import ast
import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from limn import build
from limn.build import BuildConfig, BuildFailed, BuildOk
from limn.documents import Doc, RunPaths
from limn.features.builds import figure
from limn.figmap import FigureMap
from limn.web.errors import build_failure_log

from helpers import MINI_PDF, blank_png, figure_map, map_bytes

# pdftoppm stand-in (pdftoppm -r DPI -png PDF PREFIX): one page, the PNG named by LIMN_TEST_PAGE_PNG; exit 1 when
# LIMN_TEST_PDFTOPPM is "fail".
FAKE_PDFTOPPM = """#!/bin/sh
[ "$LIMN_TEST_PDFTOPPM" = fail ] && exit 1
cp "$LIMN_TEST_PAGE_PNG" "$5-1.png"
"""
OTHER_PDF = MINI_PDF.replace(b"Reviewer one", b"Reviewer two")  # the same size, other bytes


def fake_pdftoppm(case: unittest.TestCase, root: Path) -> None:
    """Put FAKE_PDFTOPPM first on PATH for the rest of case, with a 200x100 page image under root."""
    bin_dir = root / "bin"
    bin_dir.mkdir()
    (bin_dir / "pdftoppm").write_text(FAKE_PDFTOPPM, encoding="utf-8")
    (bin_dir / "pdftoppm").chmod(0o755)
    page = root / "page.png"
    page.write_bytes(blank_png(200, 100))
    env = mock.patch.dict(
        os.environ,
        {
            "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "LIMN_TEST_PAGE_PNG": str(page),
            "LIMN_TEST_PDFTOPPM": "ok",
        },
    )
    env.start()
    case.addCleanup(env.stop)


class Producer:
    """Writes a figure repository's files the way its render does, each write with a later mtime than the one before
    (so a same-size rewrite still changes the watch signature)."""

    def __init__(self, pdf: Path, map_file: Path) -> None:
        """Bind the PDF path and the map path the producer writes."""
        self.pdf, self.map = pdf, map_file
        self.clock = time.time_ns() + 10**9

    def write(self, path: Path, raw: bytes) -> None:
        """Write raw to path and stamp it one second after the last write."""
        path.write_bytes(raw)
        self.clock += 10**9
        os.utime(path, ns=(self.clock, self.clock))

    def render(self, pdf: bytes = MINI_PDF, described: bytes | None = None, **over: object) -> None:
        """A whole render: the PDF first, then the map describing `described` (default: that PDF), its top-level keys
        replaced by over."""
        self.write(self.pdf, pdf)
        m = figure_map(pdf if described is None else described)
        m.update(over)
        self.write(self.map, map_bytes(m))


class FigureTree(unittest.TestCase):
    """figs/out/figures.pdf and figs/out/figures.limnmap.json under a manuscript, served as figure document fig with
    folder figs/, a fake pdftoppm, and no server."""

    def setUp(self):
        """The tree, the document (its state folder made), build settings at 72 dpi, a fresh map memo."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.ms = root / "ms"
        self.figs = self.ms / "figs"
        (self.figs / "out").mkdir(parents=True)
        self.pdf = self.figs / "out" / "figures.pdf"
        self.map = self.figs / "out" / "figures.limnmap.json"
        paths = RunPaths(self.ms, self.ms / "main.tex", root / "state")
        self.doc = Doc("fig", "그림", "figure", self.figs, self.map, paths=paths)
        self.doc.dir.mkdir(parents=True)
        self.cfg = BuildConfig(state=root / "state", dpi=72, timeout=5)
        self.looks = figure.MapLooks()
        self.producer = Producer(self.pdf, self.map)
        fake_pdftoppm(self, root)

    def pending(self, first: bool = False) -> figure.FigureImport | None:
        """figure.pending_import for the document, its stderr line swallowed."""
        with contextlib.redirect_stderr(io.StringIO()):
            return figure.pending_import(self.doc, self.looks, 72, first=first)

    def imported(self) -> BuildOk | BuildFailed:
        """Import the files as they are now (startup rules), expecting them to agree."""
        ready = self.pending(first=True)
        self.assertIsInstance(ready, figure.FigureImport)
        return figure.render_figure_doc(self.doc, self.cfg, ready)


class Signatures(FigureTree):
    """watch_signature: what one 3-second tick looks at without reading an unchanged map."""

    def test_the_signature_names_the_map_and_the_pdf_it_points_to(self):
        """mtime_ns:size of the map, a bar, then mtime_ns:size of the PDF the map names."""
        self.producer.render()
        m, p = self.map.stat(), self.pdf.stat()
        self.assertEqual(
            figure.watch_signature(self.doc, self.looks),
            "%d:%d|%d:%d" % (m.st_mtime_ns, m.st_size, p.st_mtime_ns, p.st_size),
        )

    def test_no_signature_without_a_map(self):
        """A figure document whose map is missing has nothing to look at."""
        self.producer.write(self.pdf, MINI_PDF)
        self.assertIsNone(figure.watch_signature(self.doc, self.looks))

    def test_a_rejected_map_or_a_missing_pdf_leaves_the_pdf_half_empty(self):
        """The PDF half is NO_FILE when the map is rejected or the PDF it names does not exist."""
        self.producer.render(format="limn-figure-map/2")
        self.assertTrue(figure.watch_signature(self.doc, self.looks).endswith("|" + figure.NO_FILE))
        self.producer.render()
        self.pdf.unlink()
        self.assertTrue(figure.watch_signature(self.doc, self.looks).endswith("|" + figure.NO_FILE))

    def test_a_changed_map_is_read_again_and_its_new_pdf_followed(self):
        """An unchanged map is not re-read (its memo holds), but once the map changes to name another PDF, the
        signature follows that PDF."""
        self.producer.render()
        first = figure.watch_signature(self.doc, self.looks)
        with mock.patch.object(figure, "parse_map", side_effect=AssertionError("an unchanged map is not re-read")):
            self.assertEqual(figure.watch_signature(self.doc, self.looks), first)
        other = self.figs / "out" / "other.pdf"
        self.producer.write(other, OTHER_PDF)
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF, "other.pdf")))
        o = other.stat()
        now = figure.watch_signature(self.doc, self.looks)
        self.assertNotEqual(now, first)
        self.assertTrue(now.endswith("|%d:%d" % (o.st_mtime_ns, o.st_size)))


class ImportDue(unittest.TestCase):
    """import_due: the pure rule for when the files are read and checked."""

    def test_files_are_read_only_when_their_signature_moved_or_startup_lacks_pages(self):
        """No map: never. A new signature: always. The settled one: only at startup without page images."""
        for now, settled, missing, want in (
            (None, None, True, False),
            ("a|b", None, False, True),
            ("a|b", "a|c", False, True),
            ("a|b", "a|b", False, False),
            ("a|b", "a|b", True, True),
        ):
            with self.subTest(now=now, settled=settled, missing=missing):
                self.assertIs(figure.import_due(now, settled, missing), want)


class Deferral(FigureTree):
    """Files that do not agree are left alone: no build, no failure, one log line, and a look again on change."""

    def test_a_pdf_newer_than_its_map_is_not_imported_and_records_no_build(self):
        """The producer has written the new PDF but not yet its map: nothing renders, no page directory, no
        builds.json, build_seq stays 0, one stderr line names pdf_mismatch, and the next tick reads nothing. When the
        map lands, the new pair is ready."""
        self.producer.render()
        self.producer.write(self.pdf, OTHER_PDF)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=True))
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=False))
        self.assertEqual(err.getvalue().count("pdf_mismatch"), 1)
        self.assertEqual(list(self.doc.dir.glob("pages-*")), [])
        self.assertFalse((self.doc.dir / "builds.json").exists())
        self.assertEqual(build.state_snapshot(self.doc)["seq"], 0)
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF)))
        ready = self.pending()
        self.assertIsInstance(ready, figure.FigureImport)
        self.assertEqual(ready.pdf_raw, OTHER_PDF)

    def test_a_map_written_before_its_pdf_waits_for_the_pdf(self):
        """The other order: the new map lands first and describes a PDF not yet written. The pair waits and is ready
        once the PDF matches."""
        self.producer.render()
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF)))
        self.assertIsNone(self.pending())
        self.producer.write(self.pdf, OTHER_PDF)
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_a_rejected_map_waits_for_its_next_change(self):
        """A map breaking a rule (a box of zero width) is logged once as map_rejected with the parser's reason, is
        not read again while unchanged, and the fixed map is imported."""
        self.producer.write(self.pdf, MINI_PDF)
        broken = figure_map(MINI_PDF)
        broken["pages"][0]["elements"][1]["frac"] = [0.1, 0.1, 0, 0.1]
        self.producer.write(self.map, map_bytes(broken))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=False))
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=False))
        self.assertEqual(err.getvalue().count("map_rejected: bad_frac"), 1)
        self.producer.write(self.map, map_bytes(figure_map(MINI_PDF)))
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_a_pdf_outside_the_figure_folder_is_never_read(self):
        """A map naming a PDF outside figs/ - by ../ or through a symlink - is pdf_outside even though that file
        exists and matches the hash; nothing is rendered (docs/handbook/code-style-roadmap.md §R10)."""
        outside = self.ms / "elsewhere.pdf"
        outside.write_bytes(MINI_PDF)
        (self.figs / "out" / "link.pdf").symlink_to(outside)
        for name in ("../../elsewhere.pdf", "link.pdf"):
            with self.subTest(pdf=name):
                self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, name)))
                got = figure.read_figure_import(self.doc)
                self.assertIsInstance(got, figure.ImportDeferred)
                self.assertEqual(got.reason, "pdf_outside")
                self.assertIsNone(self.pending(first=True))
        self.assertEqual(list(self.doc.dir.glob("pages-*")), [])

    def test_a_map_naming_a_source_outside_its_folder_is_rejected(self):
        """A src.file that escapes figs/ rejects the whole map (path_outside), so the pair is not imported."""
        m = figure_map(MINI_PDF)
        m["pages"][0]["elements"][1]["src"]["file"] = "../../main.tex"
        self.producer.write(self.pdf, MINI_PDF)
        self.producer.write(self.map, map_bytes(m))
        got = figure.read_figure_import(self.doc)
        self.assertEqual((got.reason, got.detail.split(":")[0]), ("map_rejected", "path_outside"))

    def test_a_missing_map_imports_nothing_and_records_nothing(self):
        """No map: no signature, no read, nothing settled - the last pages stay."""
        self.producer.write(self.pdf, MINI_PDF)
        self.assertIsNone(self.pending(first=True))
        self.assertIsNone(figure.settled_signature(self.doc))


class Render(FigureTree):
    """render_figure_doc and import_now: the pages, the PDF copy and the map copy land together."""

    def test_an_import_publishes_the_pages_the_pdf_and_the_map_together(self):
        """One page directory holds the page image, the PDF bytes that were checked (named after the map) and the
        map bytes; pages.cur points at it; the staging folder is gone; the settled signature is the files' own."""
        self.producer.render()
        res = self.imported()
        self.assertIsInstance(res, BuildOk)
        pdir = build.cur_pages(self.doc)
        self.assertEqual((res.build, res.pages, res.log, res.src_mtime), (pdir.name, 1, "", None))
        self.assertEqual(sorted(p.name for p in pdir.iterdir()), ["figmap.json", "figures.pdf", "page-1.png"])
        self.assertEqual((pdir / "figures.pdf").read_bytes(), self.pdf.read_bytes())
        self.assertEqual((pdir / build.FIGMAP_NAME).read_bytes(), self.map.read_bytes())
        self.assertEqual(res.src_hash, figure.figure_src_hash(self.pdf.read_bytes(), self.map.read_bytes()))
        self.assertEqual(figure.settled_signature(self.doc), figure.watch_signature(self.doc, self.looks))
        self.assertFalse((self.doc.dir / figure.STAGE_DIR).exists())
        self.assertIsInstance(build.load_build_map(self.doc, pdir.name), FigureMap)

    def test_an_unchanged_pair_is_imported_again_only_at_startup_without_pages(self):
        """After an import the watch finds nothing to do, and so does startup - until the page images are gone."""
        self.producer.render()
        self.imported()
        self.assertIsNone(self.pending())
        self.assertIsNone(self.pending(first=True))
        for page in build.cur_pages(self.doc).glob("page-*.png"):
            page.unlink()
        self.assertIsNone(self.pending())
        self.assertIsInstance(self.pending(first=True), figure.FigureImport)

    def test_a_failed_render_is_settled_and_not_retried_until_a_file_changes(self):
        """pdftoppm failing is BuildFailed render with no latexmk output; no page directory is kept, the same files
        are not tried again, and the next render of the files is."""
        self.producer.render()
        ready = self.pending(first=True)
        with mock.patch.dict(os.environ, {"LIMN_TEST_PDFTOPPM": "fail"}):
            res = figure.render_figure_doc(self.doc, self.cfg, ready)
        self.assertIsInstance(res, BuildFailed)
        self.assertEqual((res.kind, res.output), ("render", None))
        self.assertEqual(list(self.doc.dir.glob("pages-*")), [])
        self.assertIsNone(self.pending())
        self.producer.render()
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_a_map_with_more_pages_than_the_pdf_still_imports(self):
        """The PDF has one page and the map describes two: the one page is imported with the whole map; the map's
        page 2 has no page image to be picked on."""
        m = figure_map(MINI_PDF)
        m["pages"].append({"page": 2, "figure": "C1", "elements": [{"id": "C1", "frac": [0, 0, 1, 1]}]})
        self.producer.write(self.pdf, MINI_PDF)
        self.producer.write(self.map, map_bytes(m))
        res = self.imported()
        self.assertEqual(res.pages, 1)
        self.assertEqual([p.page for p in build.load_build_map(self.doc, res.build).pages], [1, 2])

    def test_the_fingerprint_follows_either_file_and_their_boundary(self):
        """32 hex digits that change with the PDF bytes, the map bytes, and a byte moved from one to the other."""
        a = figure.figure_src_hash(b"pdf", b"map")
        self.assertEqual(len(a), 32)
        for other in (("pdf2", "map"), ("pdf", "map2"), ("pdfm", "ap")):
            self.assertNotEqual(a, figure.figure_src_hash(other[0].encode(), other[1].encode()), other)

    def test_a_tracked_step_without_a_verified_pair_checks_the_files_itself(self):
        """import_now with no pair reads and checks the files: a pair that does not agree is BuildAborted
        figure_unready naming the reason, logged with its Korean text, and nothing is settled; a pair that agrees is
        imported."""
        self.producer.render(described=b"a pdf not written yet")
        res = figure.import_now(self.doc, self.cfg, None)
        self.assertEqual(res.kind, "figure_unready")
        self.assertTrue(res.detail.startswith("pdf_mismatch: "), res.detail)
        self.assertTrue(build_failure_log(res).startswith("그림 PDF 와 지도를 가져오지 못했습니다: pdf_mismatch"))
        self.assertIsNone(figure.settled_signature(self.doc))
        self.producer.render()
        self.assertIsInstance(figure.import_now(self.doc, self.cfg, None), BuildOk)


class NoServerState(unittest.TestCase):
    """The import reads no server global and imports neither the server nor the web layer (coding rule R5)."""

    def test_the_import_module_names_no_server_state(self):
        """No C., cur_doc() or document list, and no import of server.py or limn.web."""
        source = Path(figure.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertEqual(names & {"C", "cur_doc", "DOCS", "LEGACY_DOC", "BUILD_STATE", "BUILD_LOCK"}, set())
        self.assertNotIn("C.", source)
        modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertFalse({m for m in modules if "server" in m or m.startswith("limn.web")})
```

Task 5 appends a server-level class to this file and adds the imports it needs then.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest -q src/limn/features/builds/test_figure.py`

Expected: collection fails with `ImportError: cannot import name 'figure' from 'limn.features.builds'`.

- [ ] **Step 3: Add the abort kind and its text**

In `src/limn/build_values.py`, replace:

```python
BuildFailureKind: TypeAlias = Literal[
    "copy", "timeout", "no_pdf", "no_synctex", "render", "pdf_copy", "pdf_missing", "crashed", "worker_crashed"
]
```

```python
AbortKind: TypeAlias = Literal["pdf_missing", "crashed", "worker_crashed"]
```

with:

```python
BuildFailureKind: TypeAlias = Literal[
    "copy",
    "timeout",
    "no_pdf",
    "no_synctex",
    "render",
    "pdf_copy",
    "pdf_missing",
    "figure_unready",
    "crashed",
    "worker_crashed",
]
```

```python
AbortKind: TypeAlias = Literal["pdf_missing", "figure_unready", "crashed", "worker_crashed"]
```

Replace the `BuildAborted` docstring with:

```python
    """The build stopped before it measured anything: a view-only document's PDF is missing (detail: its path), a
    figure document's map and PDF do not agree when a tracked build is asked to import them (figure_unready; detail:
    the reason and its detail - the watch never gets here, it waits instead), or the build died of an unexpected
    exception (detail: its repr) - in the tracked build (crashed) or in the background worker around it
    (worker_crashed). Reported with elapsed_s 0.0."""
```

In `src/limn/web/errors.py`, add to `BUILD_FAILURES` after the `"pdf_missing"` entry:

```python
    "figure_unready": "그림 PDF 와 지도를 가져오지 못했습니다: {detail}",
```

- [ ] **Step 4: Write `src/limn/features/builds/figure.py`**

```python
"""The import build of a figure document: its element map and the PDF the map names become a page directory.

A figure repository renders a PDF and writes an element map (limn.figmap); Limn never runs its code. The watch looks
at the two files and imports them only when the map describes exactly that PDF (pdf_sha256). The pages are then
rendered from the bytes that were checked, through the same tracked build a view-only PDF uses (run_tracked), and the
map is published next to the PDF copy in the new page directory, so a drag on an older build is traced with that
build's map (limn.build.load_build_map). Files that do not agree yet are left alone - no build, no failure - and
looked at again when either changes. The watch and its signature file are the view-only PDF's
(docs/handbook/build-sync.md §보기 전용 PDF 문서).

The decisions (import_due, accept_pdf, figure_src_hash) take values. The readers, the log line and the render at the
edge take the document and the build settings as arguments and read no server global (coding rules R1, R5).
"""

import contextlib
import hashlib
import os
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

from limn import build
from limn.build import BuildAborted, BuildConfig, BuildDoc, BuildFailed, BuildOk, PagesNotRendered
from limn.features.builds import engine
from limn.figmap import MAP_MAX_BYTES, FigureMap, MapRejected, parse_map
from limn.files import atomic_write

SIG_FILE = "pdf_sig.txt"  # the watch's signature file, shared with view-only PDFs (engine.render_pdf_doc)
STAGE_DIR = "figure-import"  # private staging folder in the document's state folder; never a page directory name
NO_FILE = "-"  # the PDF half of a signature when there is no PDF to look at

DeferReason: TypeAlias = Literal["map_missing", "map_rejected", "pdf_outside", "pdf_missing", "pdf_mismatch"]


@dataclass(frozen=True)
class FileRead:
    """One read of a file: its bytes and "<mtime_ns>:<size>" taken from the same open descriptor, so both describe the
    same version even while a producer replaces the file."""

    raw: bytes
    signature: str


@dataclass(frozen=True)
class FigureImport:
    """A figure document's map and PDF read together and verified: the map's bytes and parse, the PDF's bytes (their
    SHA-256 is the map's pdf_sha256), and the watch signature of the two files as read."""

    map_raw: bytes
    figure_map: FigureMap
    pdf_raw: bytes
    signature: str


@dataclass(frozen=True)
class ImportDeferred:
    """Why a figure document's files are not imported now, a detail for the log, and the watch signature of what was
    seen - None when the map could not be read. The watch settles that signature, so only a change is looked at."""

    reason: DeferReason
    detail: str
    signature: str | None


@dataclass
class MapLooks:
    """What the watch last learned from each figure document's map, keyed by the map's path: the map's signature and
    the PDF it names (None when the map is rejected or names a PDF outside the document's folder). One per run
    (features.builds.service.BuildRequests): a tick stats both files and reads the map again only when its signature
    changed. Startup and the watch thread never look at one document at the same time; a lost update would only cost
    one extra read."""

    seen: dict[str, tuple[str, Path | None]] = field(default_factory=dict)


def stat_signature(st: os.stat_result) -> str:
    """ "<mtime_ns>:<size>" of a stat result, the view-only PDF's signature format (engine.pdf_signature)."""
    return "%d:%d" % (st.st_mtime_ns, st.st_size)


def _file_signature(path: Path | None) -> str:
    """The signature of the regular file at path, not following a symlink in its last part; NO_FILE when there is no
    path or no such regular file."""
    if path is None:
        return NO_FILE
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return NO_FILE
    return stat_signature(st) if stat.S_ISREG(st.st_mode) else NO_FILE


def _read_file(path: Path, limit: int | None) -> FileRead | None:
    """One read of the regular file at path, not following a symlink in its last part: all its bytes, or at most
    limit + 1 when limit is given (the caller refuses an oversized file without holding it), and the signature from the
    same descriptor. None when it is missing, a symlink, not a regular file, or unreadable. Opened non-blocking, so a
    FIFO in its place cannot stall the watch."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as fh:
            raw = fh.read() if limit is None else fh.read(limit + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    return FileRead(raw, stat_signature(st))


def _named_pdf(D: BuildDoc, raw: bytes) -> Path | None:
    """The PDF the map bytes raw name inside D's folder (limn.build.figure_pdf), or None when the map is rejected or
    names a PDF outside that folder."""
    parsed = parse_map(raw, source_inside=build.figure_source_check(D.src))
    return build.figure_pdf(D, parsed) if isinstance(parsed, FigureMap) else None


def watch_signature(D: BuildDoc, looks: MapLooks) -> str | None:
    """ "<map mtime_ns>:<map size>|<pdf mtime_ns>:<pdf size>" of figure document D now, or None when its map is missing
    (or not a regular file). The PDF half is NO_FILE when the map is rejected, names a PDF outside D's folder, or that
    PDF is missing. The map is read only when its own signature differs from the one looks remembers for it."""
    key = str(D.main)
    map_sig = _file_signature(D.main)
    if map_sig == NO_FILE:
        return None
    known = looks.seen.get(key)
    if known is not None and known[0] == map_sig:
        pdf = known[1]
    else:
        got = _read_file(D.main, MAP_MAX_BYTES)
        if got is None:
            return None
        map_sig, pdf = got.signature, _named_pdf(D, got.raw)
        looks.seen[key] = (map_sig, pdf)
    return map_sig + "|" + _file_signature(pdf)


def import_due(now: str | None, settled: str | None, missing_pages: bool) -> bool:
    """Whether figure files must be read and checked: never without a map (now is None); when their signature differs
    from the one last settled; and when nothing changed but the document has no page images at startup
    (missing_pages)."""
    return now is not None and (now != settled or missing_pages)


def accept_pdf(map_read: FileRead, figure_map: FigureMap, pdf_read: FileRead) -> FigureImport | ImportDeferred:
    """The pair as read: a FigureImport when the SHA-256 of the PDF bytes is figure_map.pdf_sha256, else pdf_mismatch -
    the producer has written one file and not yet the other. Either way the signature is the map's and the PDF's."""
    signature = map_read.signature + "|" + pdf_read.signature
    if hashlib.sha256(pdf_read.raw).hexdigest() != figure_map.pdf_sha256:
        return ImportDeferred("pdf_mismatch", figure_map.pdf, signature)
    return FigureImport(map_read.raw, figure_map, pdf_read.raw, signature)


def read_figure_import(D: BuildDoc) -> FigureImport | ImportDeferred:
    """Read figure document D's map and the PDF it names once each, and check them in this order: the map is a
    readable regular file (map_missing); it parses with D's source check (map_rejected: the parser's reason and
    detail); it names a PDF inside D.src (pdf_outside); that PDF is a readable regular file (pdf_missing); its SHA-256
    is the map's pdf_sha256 (pdf_mismatch, accept_pdf). Every deferral but map_missing carries the signature of what
    was read, with NO_FILE for a PDF that was not read."""
    got = _read_file(D.main, MAP_MAX_BYTES)
    if got is None:
        return ImportDeferred("map_missing", str(D.main), None)
    no_pdf = got.signature + "|" + NO_FILE
    parsed = parse_map(got.raw, source_inside=build.figure_source_check(D.src))
    if isinstance(parsed, MapRejected):
        return ImportDeferred("map_rejected", "%s: %s" % (parsed.reason, parsed.detail), no_pdf)
    pdf = build.figure_pdf(D, parsed)
    if pdf is None:
        return ImportDeferred("pdf_outside", parsed.pdf, no_pdf)
    pdf_read = _read_file(pdf, None)
    if pdf_read is None:
        return ImportDeferred("pdf_missing", str(pdf), no_pdf)
    return accept_pdf(got, parsed, pdf_read)


def settled_signature(D: BuildDoc) -> str | None:
    """The signature the watch last settled for D (SIG_FILE in D's state folder), or None before any."""
    try:
        return (D.dir / SIG_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def settle(D: BuildDoc, signature: str) -> None:
    """Record signature as settled for D - after a render, a failed render or a deferral - so the watch looks again
    only when a file changes. A failed write is ignored: the next tick then looks again."""
    with contextlib.suppress(OSError):
        D.dir.mkdir(parents=True, exist_ok=True)
        atomic_write(D.dir / SIG_FILE, signature)


def pending_import(D: BuildDoc, looks: MapLooks, dpi: int, *, first: bool) -> FigureImport | None:
    """The verified pair figure document D should import now, or None. first is startup: D is then also imported when
    its files did not change but it has no page images at dpi. None when the map is missing, when nothing changed since
    the settled signature, or when the files do not agree - then the deferral's signature is settled and one line
    naming the reason goes to stderr, so no build and no failure is recorded and the next change is looked at."""
    now = watch_signature(D, looks)
    missing_pages = first and not build.page_list(build.cur_pages(D), dpi)
    if not import_due(now, settled_signature(D), missing_pages):
        return None
    found = read_figure_import(D)
    if isinstance(found, FigureImport):
        return found
    if found.signature is not None:
        settle(D, found.signature)
        print(
            "figure %s: not imported (%s: %s) - waiting for the next change" % (D.main, found.reason, found.detail),
            file=sys.stderr,
        )
    return None


def figure_src_hash(pdf_raw: bytes, map_raw: bytes) -> str:
    """The build fingerprint of an imported pair: SHA-256 over the SHA-256 digest of the PDF bytes followed by that of
    the map bytes, cut to 32 hex digits like every build fingerprint (limn.build.doc_fingerprint). A change to either
    file changes it, so pins made on the previous build are drawn as estimates (est)."""
    pair = hashlib.sha256(pdf_raw).digest() + hashlib.sha256(map_raw).digest()
    return hashlib.sha256(pair).hexdigest()[:32]


def render_figure_doc(D: BuildDoc, cfg: BuildConfig, ready: FigureImport) -> BuildOk | BuildFailed:
    """The 'build' of figure document D from a verified pair, the figure counterpart of engine.render_pdf_doc. The PDF
    and map bytes are staged in D's state folder (STAGE_DIR), the pages are rendered from the staged PDF at cfg.dpi
    (engine.render_pages), and the new page directory holds the PDF copy (D.pdf_name) and the map copy
    (limn.build.FIGMAP_NAME); then pages.cur moves to it (engine.commit_pages). The signature is settled after the
    commit, or after a failed render, so a pair that cannot be rendered is retried only when a file changes. src_hash
    is figure_src_hash of the pair. A staging failure is BuildFailed pdf_copy; the staging folder never survives."""
    t0 = time.time()
    src_hash = figure_src_hash(ready.pdf_raw, ready.map_raw)
    stage = D.dir / STAGE_DIR
    shutil.rmtree(stage, ignore_errors=True)
    newdir: Path | PagesNotRendered
    try:
        stage.mkdir(parents=True)
        (stage / D.pdf_name).write_bytes(ready.pdf_raw)
        (stage / build.FIGMAP_NAME).write_bytes(ready.map_raw)
        newdir = engine.render_pages(D, stage / D.pdf_name, [stage / build.FIGMAP_NAME], cfg.dpi)
    except OSError as e:
        newdir = PagesNotRendered("pdf_copy", str(e))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    if isinstance(newdir, PagesNotRendered):
        settle(D, ready.signature)
        return BuildFailed(newdir.kind, newdir.detail, None, [], round(time.time() - t0, 1), None, None, src_hash)
    head = engine.commit_pages(D, newdir)
    settle(D, ready.signature)
    pages = len(list(newdir.glob("page-*.png")))
    return BuildOk("", round(time.time() - t0, 1), None, None, src_hash, head, newdir.name, pages)


def import_now(D: BuildDoc, cfg: BuildConfig, ready: FigureImport | None) -> BuildOk | BuildFailed | BuildAborted:
    """The tracked build step of figure document D (features.builds.service.BuildRequests.build_step): render ready,
    the pair the watch or startup verified, or - when none was given - read and check D's files now and render them.
    Files that do not agree end as BuildAborted figure_unready naming the reason; nothing is settled, so the watch
    still looks at them."""
    found = ready if ready is not None else read_figure_import(D)
    if isinstance(found, ImportDeferred):
        return BuildAborted("figure_unready", "%s: %s" % (found.reason, found.detail))
    return render_figure_doc(D, cfg, found)
```

- [ ] **Step 5: Run the tests and the gates**

Run:

```bash
uv run ruff check --fix src/limn/features/builds/figure.py src/limn/features/builds/test_figure.py src/limn/build_values.py src/limn/web/errors.py
uv run ruff format src/limn/features/builds/figure.py src/limn/features/builds/test_figure.py src/limn/build_values.py src/limn/web/errors.py
uv run pytest -q src/limn/features/builds/test_figure.py tests/test_errors.py tests/test_build.py
uv run mypy
```

Expected: all pass, including `tests/test_errors.py`'s `test_the_document_build_failure_table_has_a_text_for_every_kind` (the new kind has its Korean text); mypy prints `Success: no issues found`.

- [ ] **Step 6: Mutation check: skip the hash comparison and watch the deferral tests fail, then restore**

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/builds/figure.py 'if hashlib.sha256(pdf_read.raw).hexdigest() != figure_map.pdf_sha256:' 'if False:'
uv run pytest -q src/limn/features/builds/test_figure.py -k "Deferral or tracked_step"
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/builds/figure.py 'if False:' 'if hashlib.sha256(pdf_read.raw).hexdigest() != figure_map.pdf_sha256:'
git diff --stat
```

Expected: the middle command fails `test_a_pdf_newer_than_its_map_is_not_imported_and_records_no_build`, `test_a_map_written_before_its_pdf_waits_for_the_pdf` and `test_a_tracked_step_without_a_verified_pair_checks_the_files_itself`. After the restore, `git diff --stat` shows only this task's files.

- [ ] **Step 7: Commit**

```bash
git add src/limn/features/builds/figure.py src/limn/features/builds/test_figure.py src/limn/build_values.py src/limn/web/errors.py
git commit -s -m "feat(builds): import a figure document's PDF and element map" -m "The import reads the map and the PDF it names once each and renders them only when the map's pdf_sha256 is the PDF's SHA-256, from exactly the checked bytes, publishing the map next to the PDF copy in the new page directory. Files that disagree, a rejected map, or a PDF outside the figure's folder build nothing and record no failure; the watch settles their signature and looks again on the next change. A tracked build asked to import such files fails as figure_unready."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 5: Wire figure documents into the build service

**Files:**
- Modify: `src/limn/features/builds/service.py` (imports; `BuildRequests.__init__`, `tracked`, `init_doc`, `watch_pdf_docs`; add `build_step`, `import_figure`, `refresh_watched`)
- Test: `src/limn/features/builds/test_figure.py` (imports; new class `FigureDocumentThroughTheServer`)

**Interfaces:**
- Consumes: `figure.MapLooks`, `figure.pending_import`, `figure.import_now`, `figure.FigureImport` (Task 4); `Doc.builds_from_source`, `Doc.watches_files`, `Doc.has_element_map` (P0, Task 2); `run.run_tracked`, `run.build_now`, `run.build_in_background`, `run.needs_build`, `engine.refresh_pdf_doc`, `engine.render_pdf_doc`.
- Produces:
  - `BuildRequests.figure_looks: figure.MapLooks` (one per run)
  - `BuildRequests.tracked(doc: Doc, ready: FigureImport | None = None) -> FinishedBuild`
  - `BuildRequests.build_step(doc: Doc, ready: FigureImport | None = None) -> FinishedBuild`
  - `BuildRequests.import_figure(doc: Doc, ready: FigureImport, wait: bool) -> FinishedBuild | BuildStarted | BuildBusy`
  - `BuildRequests.refresh_watched(doc: Doc) -> bool`
  - `init_doc` imports a figure document only through `figure.pending_import(..., first=True)`; `--no-build` does not apply to it.

- [ ] **Step 1: Write the failing server-level tests**

In `src/limn/features/builds/test_figure.py`, extend the imports so they read:

```python
import ast
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from limn import build
from limn.build import BuildConfig, BuildFailed, BuildOk, BuildSkipped
from limn.documents import Doc, RunPaths
from limn.features.administration import serve_documents as startup_documents
from limn.features.builds import figure
from limn.figmap import FigureMap
from limn.web.errors import build_failure_log

from helpers import MINI_PDF, Base, blank_png, figure_map, map_bytes, ps, req, split_resp
```

Append:

```python
class FigureDocumentThroughTheServer(Base):
    """A figure document served beside a LaTeX body, driven through server.py's build service and routes: startup
    import, the watch tick, and the answers a figure document shares with a view-only PDF."""

    def setUp(self):
        """figs/out/figures.pdf with its map under the fixture manuscript, documents ms and fig (folder figs/), and the
        fake pdftoppm on PATH."""
        super().setUp()
        self.figs = self.src / "figs"
        (self.figs / "out").mkdir(parents=True)
        self.pdf = self.figs / "out" / "figures.pdf"
        self.map = self.figs / "out" / "figures.limnmap.json"
        self.producer = Producer(self.pdf, self.map)
        self.producer.render()
        docs = startup_documents.make_docs(
            ["ms=본문:main.tex", "fig=그림:figs::out/figures.limnmap.json"], self.src, ps.APP.C
        )
        ps.APP.set_docs(docs)
        self.fig = docs[1]
        self.bin = tempfile.TemporaryDirectory()
        self.addCleanup(self.bin.cleanup)
        fake_pdftoppm(self, Path(self.bin.name))

    def tearDown(self):
        """Back to the single document before the fixture removes the manuscript."""
        ps.APP.set_docs(None)
        super().tearDown()

    def test_startup_imports_a_figure_document_whose_files_agree(self):
        """init_doc imports the pair even under --no-build; /pdf serves the checked PDF bytes, and /api/docs and
        /api/meta report kind figure, view_only true, never stale, the map as main."""
        self.assertIsInstance(ps.APP.build_requests.init_doc(self.fig, no_build=True, wait=True), BuildOk)
        code, hdrs, body = split_resp(self.talk(req("GET", "/pdf?doc=fig")))
        self.assertEqual((code, hdrs["content-type"], body), (200, "application/pdf", MINI_PDF))
        code, _, body = split_resp(self.talk(req("GET", "/api/docs")))
        brief = json.loads(body)["docs"][1]
        self.assertEqual(
            (brief["key"], brief["kind"], brief["view_only"], brief["stale_build"], brief["n_pages"]),
            ("fig", "figure", True, False, 1),
        )
        code, _, body = split_resp(self.talk(req("GET", "/api/meta?doc=fig")))
        m = json.loads(body)
        self.assertEqual(
            (m["kind"], m["view_only"], m["stale_build"], m["main"], m["build_seq"]),
            ("figure", True, False, "figures.limnmap.json", 1),
        )

    def test_startup_leaves_a_figure_whose_files_disagree_unbuilt(self):
        """A map describing a PDF not yet written: startup skips the document - no build state, no history."""
        self.producer.write(self.map, map_bytes(figure_map(b"a pdf not written yet")))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ps.APP.build_requests.init_doc(self.fig, no_build=False, wait=True), BuildSkipped())
        self.assertEqual(build.state_snapshot(self.fig)["state"], "idle")
        self.assertEqual(build.load_builds(self.fig)["seq"], 0)

    def test_the_watch_imports_a_figure_once_its_map_catches_up(self):
        """A new PDF alone starts nothing and leaves build_seq; once its map lands, the tick starts a background
        import that publishes the new PDF as the next build."""
        ps.APP.build_requests.init_doc(self.fig, no_build=False, wait=True)
        self.producer.write(self.pdf, OTHER_PDF)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(ps.APP.build_requests.refresh_watched(self.fig))
        self.assertEqual(build.state_snapshot(self.fig)["seq"], 1)
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF)))
        self.assertTrue(ps.APP.build_requests.refresh_watched(self.fig))
        self.assertTrue(self.fig.lock.acquire(timeout=10))  # the background import holds the lock until it is done
        self.fig.lock.release()
        self.assertEqual(build.state_snapshot(self.fig)["seq"], 2)
        self.assertEqual((build.cur_pages(self.fig) / "figures.pdf").read_bytes(), OTHER_PDF)

    def test_a_latex_document_is_not_refreshed_by_the_watch(self):
        """refresh_watched answers False for a document built from source and starts nothing."""
        self.assertFalse(ps.APP.build_requests.refresh_watched(ps.APP.docs[0]))
        self.assertEqual(build.state_snapshot(ps.APP.docs[0])["state"], "idle")

    def test_rebuild_snippet_and_revisions_refuse_a_figure_document(self):
        """POST /api/rebuild is 400 view_only_no_rebuild, a snippet is 400 no_source_lines, and the changes view is
        unavailable - as for a view-only PDF."""
        code, _, body = split_resp(self.talk(req("POST", "/api/rebuild?doc=fig")))
        self.assertEqual((code, json.loads(body)["reason"]), (400, "view_only_no_rebuild"))
        code, _, body = split_resp(self.talk(req("GET", "/api/snippet?doc=fig&file=main.tex&lo=1&hi=2")))
        self.assertEqual((code, json.loads(body)["reason"]), (400, "no_source_lines"))
        code, _, body = split_resp(self.talk(req("GET", "/api/revisions?doc=fig")))
        self.assertEqual((code, json.loads(body)["available"]), (200, False))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest -q src/limn/features/builds/test_figure.py -k FigureDocumentThroughTheServer`

Expected:
- `test_startup_imports_a_figure_document_whose_files_agree` fails: P0's `init_doc` renders the map file as a PDF, so `/pdf` answers the map's bytes, not `MINI_PDF`.
- `test_startup_leaves_a_figure_whose_files_disagree_unbuilt` fails: a build ran.
- `test_the_watch_imports_a_figure_once_its_map_catches_up` and `test_a_latex_document_is_not_refreshed_by_the_watch` fail with `AttributeError: 'BuildRequests' object has no attribute 'refresh_watched'`.
- `test_rebuild_snippet_and_revisions_refuse_a_figure_document` passes already; it pins P0's capability branches for the new kind.

- [ ] **Step 3: Route figure documents through the import**

In `src/limn/features/builds/service.py`, replace `from limn.features.builds import engine, run` with:

```python
from limn.features.builds import engine, figure, run
from limn.features.builds.figure import FigureImport
```

At the end of `BuildRequests.__init__`, add:

```python
        self.figure_looks = figure.MapLooks()  # this run's memo of each figure map's PDF (figure.watch_signature)
```

and replace its docstring with `"""Bind run facts as call-time lookups so a new setting or runtime is seen on the next build, and start this run's memo of figure maps."""`.

Replace P0's `tracked` with:

```python
    def tracked(self, doc: Doc, ready: FigureImport | None = None) -> FinishedBuild:
        """Run one build of doc (build_step) and commit its status and page history (run.run_tracked). ready is a
        figure document's verified pair (figure.pending_import); without it such a document reads and checks its files
        itself."""
        return run.run_tracked(
            doc, self.settings().state, lambda: self.build_step(doc, ready), self.now(), self.describe
        )

    def build_step(self, doc: Doc, ready: FigureImport | None = None) -> FinishedBuild:
        """One untracked build of doc, chosen by capability: latexmk for a document built from source; the import of
        its map and PDF for a document with an element map (figure.import_now, with ready when given); otherwise the
        render of its view-only PDF."""
        if doc.builds_from_source:
            return self.compile(doc)
        if doc.has_element_map:
            return figure.import_now(doc, self.config(), ready)
        return engine.render_pdf_doc(doc, self.config())

    def import_figure(self, doc: Doc, ready: FigureImport, wait: bool) -> FinishedBuild | BuildStarted | BuildBusy:
        """Import a verified figure pair through the tracked build: now when wait, else on a daemon thread. BuildBusy
        when doc is already building; nothing was settled then, so the watch tries again on its next tick."""
        if wait:
            return run.build_now(doc, lambda: self.tracked(doc, ready))
        return run.build_in_background(doc, lambda: self.tracked(doc, ready), self.now(), self.describe)
```

Replace P0's `init_doc` with:

```python
    def init_doc(self, doc: Doc, no_build: bool, wait: bool) -> FinishedBuild | BuildStarted | BuildBusy | BuildSkipped:
        """Restore build history and start a needed build, synchronously only when requested. A document with an
        element map is imported only when figure.pending_import (startup rules) finds its map and PDF changed or its
        page images missing, and the two agree; --no-build does not apply to it, as to a view-only PDF."""
        doc.dir.mkdir(parents=True, exist_ok=True)
        if doc.root:
            build.migrate_pages(doc)
        build.seed_builds(doc, self.settings().state)
        if doc.has_element_map:
            ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=True)
            return BuildSkipped() if ready is None else self.import_figure(doc, ready, wait)
        if not run.needs_build(doc, no_build, self.settings().dpi):
            return BuildSkipped()
        return self.build_all(doc) if wait else self.build_async(doc)
```

Replace P0's `watch_pdf_docs` with:

```python
    def watch_pdf_docs(self, stop: threading.Event, every: float = 3.0) -> None:
        """Every `every` seconds until this run's stop event is set, give each document whose files are watched one
        refresh_watched tick. An exception is printed and the watch goes on."""
        while not stop.wait(every):
            for doc in list(self.docs()):
                if doc.watches_files:
                    try:
                        self.refresh_watched(doc)
                    except Exception:  # noqa: BLE001 — the watch thread must never die
                        traceback.print_exc(file=sys.stderr)

    def refresh_watched(self, doc: Doc) -> bool:
        """One watch tick for doc. A document with an element map imports its map and PDF once they agree
        (figure.pending_import) and otherwise builds nothing and records no failure; a view-only PDF re-renders when
        its file changed (engine.refresh_pdf_doc). True when a build started; False for a document whose files are not
        watched."""
        if not doc.watches_files:
            return False
        if doc.has_element_map:
            ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=False)
            return ready is not None and isinstance(self.import_figure(doc, ready, wait=False), BuildStarted)
        return engine.refresh_pdf_doc(doc, self.build_async)
```

- [ ] **Step 4: Run the tests and the gates**

Run:

```bash
uv run ruff check --fix src/limn/features/builds/service.py src/limn/features/builds/test_figure.py
uv run ruff format src/limn/features/builds/service.py src/limn/features/builds/test_figure.py
uv run pytest -q src/limn/features/builds/ tests/test_build.py tests/test_server.py -k "not Browser"
uv run mypy
```

Expected: all pass (`tests/test_server.py`'s `MultiDoc` view-only tests unchanged); mypy prints `Success: no issues found`.

- [ ] **Step 5: Mutation check: send figure documents down the view-only render and watch the tests fail, then restore**

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/builds/service.py '        if doc.has_element_map:
            ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=True)' '        if False:
            ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=True)'
uv run pytest -q src/limn/features/builds/test_figure.py -k startup
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/builds/service.py '        if False:
            ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=True)' '        if doc.has_element_map:
            ready = figure.pending_import(doc, self.figure_looks, self.settings().dpi, first=True)'
git diff --stat
```

Expected: the middle command fails both startup tests. After the restore, only this task's two files differ.

- [ ] **Step 6: Commit**

```bash
git add src/limn/features/builds/service.py src/limn/features/builds/test_figure.py
git commit -s -m "feat(builds): watch and import figure documents at startup and on change" -m "BuildRequests chooses the build step by capability: latexmk for a document built from source, the figure import for a document with an element map, the PDF render otherwise. Startup and the watch import a figure only when its map and PDF agree, passing the verified bytes into the tracked build; rebuild requests stay 400."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 6: Figure documents pick and pin as regions named after the map's PDF

**Files:**
- Modify: `src/limn/features/pins/location/resolve.py` (`PickedRegion` docstring, the region branch of `pick`, `_pick_region`; add `_region_pdf`)
- Modify: `src/limn/documents.py` (`DocumentFacts.pdf`)
- Modify: `src/limn/web/parse.py` (docstring of the protocol's `pdf`)
- Test: `src/limn/features/pins/location/test_figure_region.py` (create)

**Interfaces:**
- Consumes: `build.build_figure_pdf`, `build.FIGMAP_NAME` (Task 3); `Doc.has_element_map`, `Doc.pdf_name` (Task 2); P0's region branch `if D.view_only:` in `pick`.
- Produces:
  - `POST /api/pick` on a figure document answers the existing region body. Its `pdf` is the manuscript-relative path of the PDF named by the map of the drag's build (`pdf_build`) and `name` is that PDF's file name; pdftotext reads the PDF copy of that build. Without a loadable map, or when the map's `pdf` lies outside the document folder, it names the map file.
  - `DocumentFacts.pdf` for a figure document is the absolute path of the PDF the on-screen build's map names (the map file before any import), so a region pin records `pdf`/`name` of that PDF.

- [ ] **Step 1: Write the failing tests**

Create `src/limn/features/pins/location/test_figure_region.py`:

```python
"""Picking and pinning on a figure document (docs/handbook/api.md §보기 전용 PDF 문서의 pick·핀): until the map drives
the pick, a figure document answers the view-only region body, named after the PDF its build's map names.

The page directory is made by hand the way an import leaves it (a page image, the PDF copy and the map copy), so no
renderer runs; pdftotext is replaced by a stand-in that records which PDF it was asked to read.

Run: uv run pytest -q src/limn/features/pins/location/test_figure_region.py
"""

import json
from pathlib import Path
from unittest import mock

from limn import build as limn_build, files
from limn.features.administration import serve_documents as startup_documents
from limn.features.pins.location import source as pick_source

from helpers import MINI_PDF, Base, blank_png, figure_map, fits, jreq, map_bytes, ps, split_resp

DRAG = {"doc": "fig", "page": 1, "x0": 10, "y0": 10, "x1": 40, "y1": 30}


class FigureRegionPick(Base):
    """Documents ms (the fixture body) and fig (folder figs/, map figs/out/figures.limnmap.json) with one imported
    build on screen."""

    def setUp(self):
        """The figure files, the two documents, and build pages-20260101000000 of fig on screen."""
        super().setUp()
        self.figs = self.src / "figs"
        (self.figs / "out").mkdir(parents=True)
        (self.figs / "out" / "figures.pdf").write_bytes(MINI_PDF)
        (self.figs / "out" / "figures.limnmap.json").write_bytes(map_bytes(figure_map(MINI_PDF)))
        docs = startup_documents.make_docs(
            ["ms=본문:main.tex", "fig=그림:figs::out/figures.limnmap.json"], self.src, ps.APP.C
        )
        ps.APP.set_docs(docs)
        self.fig = docs[1]
        self.pdir = self.publish("pages-20260101000000", figure_map(MINI_PDF))

    def tearDown(self):
        """Back to the single document before the fixture removes the manuscript."""
        ps.APP.set_docs(None)
        super().tearDown()

    def publish(self, name: str, m: dict) -> Path:
        """Page directory `name` of fig as an import leaves it - one 200x200 page, the PDF copy and map m - put on
        screen."""
        d = self.fig.dir / name
        d.mkdir(parents=True)
        (d / "page-1.png").write_bytes(blank_png(200, 200))
        (d / self.fig.pdf_name).write_bytes(MINI_PDF)
        (d / limn_build.FIGMAP_NAME).write_bytes(map_bytes(m))
        files.atomic_write(self.fig.dir / "pages.cur", name)
        return d

    def pick(self, body: dict) -> dict:
        """POST /api/pick with body, pdftotext answering nothing; the 200 body."""
        with mock.patch.object(pick_source, "region_text", return_value=""):
            code, _, raw = split_resp(self.talk(jreq("POST", "/api/pick", body)))
        self.assertEqual(code, 200, raw)
        return json.loads(raw)

    def test_a_figure_pick_answers_a_region_named_after_the_maps_pdf(self):
        """The region body of a view-only PDF, with pdf and name taken from the build's map; the region's text is read
        from that build's PDF copy, and SyncTeX is never asked."""
        with (
            mock.patch.object(pick_source, "region_text", return_value="July") as text,
            mock.patch.object(pick_source, "by_synctex", side_effect=AssertionError("no SyncTeX for a figure")),
        ):
            code, _, raw = split_resp(self.talk(jreq("POST", "/api/pick", DRAG)))
        d = json.loads(raw)
        self.assertEqual(code, 200)
        self.assertEqual(
            (d["kind"], d["view_only"], d["pdf"], d["name"], d["quote"], d["pdf_build"]),
            ("region", True, "figs/out/figures.pdf", "figures.pdf", "July", self.pdir.name),
        )
        self.assertEqual(text.call_args.args[0], self.pdir / "figures.pdf")

    def test_a_pick_on_an_older_build_names_that_builds_pdf(self):
        """A drag made on the previous build is named after that build's map, not the one on screen."""
        old = self.publish("pages-20251231000000", figure_map(MINI_PDF, "older.pdf"))
        files.atomic_write(self.fig.dir / "pages.cur", self.pdir.name)
        d = self.pick(dict(DRAG, pdf_build=old.name))
        self.assertEqual((d["pdf"], d["name"], d["pdf_build"]), ("figs/out/older.pdf", "older.pdf", old.name))

    def test_a_map_copy_that_is_missing_or_names_a_pdf_outside_names_the_map_file(self):
        """Without a loadable map, or with one whose pdf escapes the document folder, the region names the map file -
        never a path outside (docs/handbook/code-style-roadmap.md §R10)."""
        copy = self.pdir / limn_build.FIGMAP_NAME
        for m in (None, figure_map(MINI_PDF, "../../../outside.pdf")):
            with self.subTest(pdf=m and m["pdf"]):
                copy.unlink(missing_ok=True)
                if m is not None:
                    copy.write_bytes(map_bytes(m))
                d = self.pick(DRAG)
                self.assertEqual((d["pdf"], d["name"]), ("figs/out/figures.limnmap.json", "figures.limnmap.json"))

    def test_a_region_pin_on_a_figure_document_records_the_maps_pdf(self):
        """POST /api/pin stores a region pin whose pdf is the absolute path of the PDF the map on screen names."""
        body = {"doc": "fig", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "7월 글자", "quote": "July"}
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        self.assertEqual(code, 200, raw)
        rec = self.pin(json.loads(raw)["id"])
        self.assertEqual(
            (rec["doc"], rec["kind"], rec["pdf"], rec["name"]),
            ("fig", "region", str((self.figs / "out" / "figures.pdf").resolve()), "figures.pdf"),
        )
        self.assertNotIn("file", rec)
        self.assertTrue(fits(rec))

    def test_a_figure_document_takes_no_line_pin(self):
        """A line pin on a figure document is refused as on a view-only PDF (400 no_source_lines)."""
        body = {"doc": "fig", "file": "figs/src/B2_calendar.py", "lo": 1, "hi": 2, "page": 1}
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        self.assertEqual((code, json.loads(raw)["reason"]), (400, "no_source_lines"))

    def test_a_file_only_pin_under_the_figure_folder_goes_to_the_latex_document(self):
        """The figure folder lies inside the body's build root: an agent's pin that names only a file there becomes a
        line pin of the LaTeX document, never of the figure."""
        (self.figs / "src").mkdir()
        (self.figs / "src" / "B2_calendar.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        body = {"file": "figs/src/B2_calendar.py", "lo": 1, "hi": 2}
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pin", body)))
        self.assertEqual(code, 200, raw)
        self.assertEqual(self.pin(json.loads(raw)["id"])["doc"], "ms")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest -q src/limn/features/pins/location/test_figure_region.py`

Expected: `test_a_figure_pick_answers_a_region_named_after_the_maps_pdf`, `test_a_pick_on_an_older_build_names_that_builds_pdf` and `test_a_region_pin_on_a_figure_document_records_the_maps_pdf` fail: they get `figs/out/figures.limnmap.json` / `figures.limnmap.json`. The other three pass already; they pin the region fallback and the routing for the new kind.

- [ ] **Step 3: Name the map's PDF in the region pick**

In `src/limn/features/pins/location/resolve.py`, replace the `PickedRegion` docstring with:

```python
    """A selection on a document whose pins are regions: its key, the page and page-relative box (frac), the PDF's
    path from the manuscript root and file name (for a document with an element map, the PDF the map of the drag's
    build names), the region's printed text as a quote and its length, and the page directory. blank: the region has
    no printed text (a figure or scan); redrawing: the pages are being redrawn now."""
```

In `pick`, replace P0's region return

```python
        return _pick_region(D, pdir, page, (x0, y0, x1, y1), (pw, ph), frac, rtext)
```

with:

```python
        return _pick_region(D, pdir, page, (x0, y0, x1, y1), (pw, ph), frac, rtext, ctx.root)
```

Replace `_pick_region` with:

```python
def _pick_region(
    D: Doc,
    pdir: Path,
    page: int,
    box: tuple[float, float, float, float],
    size: tuple[float, float],
    frac: list[float] | None,
    rtext: str,
    root: Path,
) -> PickedRegion:
    """pick for a document whose pins are regions - only page/region and the region's text (pdftotext), no SyncTeX.
    If frac wasn't sent (agent curl), it's built from the coordinates - for such a pin, the region is the whole
    location. The PDF it names is _region_pdf's, relative to the manuscript root."""
    x0, y0, x1, y1 = box
    pw, ph = size
    if frac is None:
        frac = [x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph]
    text = norm(rtext)
    bstate = build.state_snapshot(D)
    pdf, name = _region_pdf(D, pdir, root)
    return PickedRegion(
        doc=D.key,
        page=page,
        frac=frac,
        pdf=pdf,
        name=name,
        quote=truncate_quote(text, PDF_QUOTE_MAX),
        n_chars=len(text),
        blank=not text,
        redrawing=bstate["state"] == "running",
        pdf_build=pdir.name,
    )


def _region_pdf(D: Doc, pdir: Path, root: Path) -> tuple[str, str]:
    """The PDF a region pick names, as (path from the manuscript root, file name). A view-only PDF names itself
    (Doc.rel_path). A document with an element map names the PDF the map of the drag's build (pdir) names
    (limn.build.build_figure_pdf) - or its map file when that build has no loadable map or the map's PDF lies outside
    the document's folder, so no path outside it is ever named."""
    if D.has_element_map:
        named = build.build_figure_pdf(D, pdir.name)
        if named is not None:
            try:
                return str(named.relative_to(root.resolve())), named.name
            except (ValueError, OSError, RuntimeError):
                return str(named), named.name
    return D.rel_path(), D.main.name
```

- [ ] **Step 4: Record the same PDF on a region pin**

In `src/limn/documents.py`, replace `DocumentFacts.pdf` with:

```python
    @property
    def pdf(self) -> Path:
        """The PDF a region pin on D records: a view-only document's own PDF (its main file); for a document with an
        element map, the PDF named by the map of the build on screen (limn.build.build_figure_pdf), or the map file
        itself before an import has published a loadable map."""
        if self._doc.has_element_map:
            named = build.build_figure_pdf(self._doc, build.cur_pages(self._doc).name)
            if named is not None:
                return named
        return self._doc.main
```

In `src/limn/web/parse.py`, replace the protocol's `pdf` docstring `"""A view-only document's PDF (its main file), which a region pin records."""` with:

```python
        """The PDF a region pin records: a view-only document's own PDF (its main file), or the PDF a figure
        document's on-screen build map names."""
```

- [ ] **Step 5: Run the tests and the gates**

Run:

```bash
uv run ruff check --fix src/limn/features/pins/location/resolve.py src/limn/documents.py src/limn/web/parse.py src/limn/features/pins/location/test_figure_region.py
uv run ruff format src/limn/features/pins/location/resolve.py src/limn/documents.py src/limn/web/parse.py src/limn/features/pins/location/test_figure_region.py
uv run pytest -q src/limn/features/pins/location/ src/limn/features/document_views/test_meta.py tests/test_server.py tests/test_web_parse.py -k "not Browser"
uv run mypy
```

Expected: all pass (`MultiDoc.test_view_only_pick_returns_region_without_synctex` still answers `review.pdf`); mypy prints `Success: no issues found`.

- [ ] **Step 6: Mutation check: name the map for every region and watch the pick tests fail, then restore**

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/pins/location/resolve.py '    if D.has_element_map:
        named = build.build_figure_pdf(D, pdir.name)' '    if False:
        named = build.build_figure_pdf(D, pdir.name)'
uv run pytest -q src/limn/features/pins/location/test_figure_region.py -k pick
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/pins/location/resolve.py '    if False:
        named = build.build_figure_pdf(D, pdir.name)' '    if D.has_element_map:
        named = build.build_figure_pdf(D, pdir.name)'
git diff --stat
```

Expected: the middle command fails `test_a_figure_pick_answers_a_region_named_after_the_maps_pdf` and `test_a_pick_on_an_older_build_names_that_builds_pdf`. After the restore, only this task's four files differ.

- [ ] **Step 7: Commit**

```bash
git add src/limn/features/pins/location/resolve.py src/limn/documents.py src/limn/web/parse.py src/limn/features/pins/location/test_figure_region.py
git commit -s -m "feat(pins): name a figure's PDF in its region picks and pins" -m "A figure document picks and pins as a view-only region; the pick names the PDF its build's map names and reads that build's PDF copy, and a region pin records the PDF of the map on screen. Without a loadable map, or with a map whose PDF escapes the figure folder, the map file is named instead."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 7: Handbook and CHANGELOG

**Files:**
- Modify: `docs/handbook/purpose.md` (first paragraph, §지원 범위, §다루지 않는 상황, §하지 않는 일)
- Modify: `docs/handbook/instances.md` (§여러 문서 (`DOCS=`))
- Modify: `docs/handbook/operations.md` (§여러 문서 (`--doc`) table)
- Modify: `docs/handbook/build-sync.md` (intro paragraph, 한눈에 box, §빌드 결과 `BuildAborted` row, new last section `## 그림 문서`)
- Modify: `docs/handbook/domain.md` (summary box, §용어, P0's capability table in §여러 문서, new `### 그림 문서`, §알려진 제약)
- Modify: `docs/handbook/api.md` (§엔드포인트 rows `/api/docs`, `/pdf`, `/api/rebuild`; §보기 전용 PDF 문서의 pick·핀; §핀 레코드 스키마 `pdf` row; new `## 그림 요소 지도 (\`limn-figure-map/1\`)` before `## 휴지통`)
- Modify: `docs/handbook/architecture.md` (§현재 구조 table, §의존 방향 diagram)
- Modify: `docs/handbook/index.md` (catalog rows, file map)
- Modify: `CHANGELOG.md` (Unreleased)

**Interfaces:**
- Consumes: the behaviour of Tasks 1–6.
- Produces: the Handbook headings `build-sync.md` `## 그림 문서`, `domain.md` `### 그림 문서`, `api.md` `## 그림 요소 지도 (\`limn-figure-map/1\`)`, which P1b's plan and code may cite. The map format and its checks are written in `api.md`: they are a contract with another repository and follow the API's rule of growing only. `domain.md` holds the concept and links there.

All text below is Korean, present tense, with no dates. Where P0 already reworded a sentence being replaced, apply the same change to P0's wording.

- [ ] **Step 1: `purpose.md`**

Replace the first paragraph (the one starting `Limn은 LaTeX 논문 원고와 PDF 뷰어 사이를 잇는`) with:

```markdown
Limn은 LaTeX 원고와 벡터 그래픽을 PDF로 띄우고 그 위에 핀을 찍는 리뷰 도구다. 사람이 브라우저에서 PDF 위에 핀(메모)을 찍으면, 에이전트(또는 다른 사람)가 그 핀을 보고 원고나 그림의 해당 자리를 고치고 핀을 닫는다. 범위를 LaTeX 원고와 벡터 그래픽으로 둔 결정은 [ADR-0011](../adr/0011-figure-documents.md) D1이다.
```

In §지원 범위, after the `LaTeX 원고:` bullet, add:

```markdown
- 벡터 그래픽: 그림 저장소가 그림을 PDF(그림 한 장이 한 쪽)로 렌더하고 요소 지도(`.limnmap.json`)를 함께 낸 그림. Limn은 렌더하지 않고 두 파일을 가져온다([build-sync.md](build-sync.md) §그림 문서). 지도 형식은 [api.md](api.md) §그림 요소 지도 (`limn-figure-map/1`)에 있다.
```

In §다루지 않는 상황, add as the last bullet:

```markdown
- 요소 지도가 없는 그림(사진, 받은 래스터 그림)은 그림 문서가 아니다. 보기 전용 PDF로 띄운다.
```

In §하지 않는 일, add as the last bullet:

```markdown
- **그림을 렌더하지 않는다.** 그림 저장소의 코드를 실행하지 않고, SVG를 래스터화하지도 않는다. 화면에는 그림 저장소가 낸 PDF만 그린다.
```

- [ ] **Step 2: `instances.md` and `operations.md`**

In `instances.md` §여러 문서 (`DOCS=`), in the example block, add after the `limn doc add paper2 --doc 'cl=…' --restart` line:

```bash
> limn doc add paper2 --doc 'fig=그림:figures::out/figures.limnmap.json' --restart
```

In its table, replace the `경로` row's last sentence `` `.tex`(LaTeX)나 `.pdf`(보기 전용)만 받는다 `` with `` `.tex`(LaTeX), `.pdf`(보기 전용), `.limnmap.json`(그림 문서)만 받는다 ``, and add after the `x/file.pdf` row:

```markdown
| `x/figures.limnmap.json` | 그림 문서. 지도가 가리키는 PDF를 가져온다(재빌드 없음). 문서 폴더는 지도가 있는 `x/` |
| `root::sub/figures.limnmap.json` | 그림 문서. 문서 폴더는 `root/`, 지도는 `root/sub/figures.limnmap.json`. 지도 속 코드 경로(`src`·`impl`)가 `root/` 기준일 때 쓴다 |
```

After the table (before the paragraph starting `` `limn`은 설정에 쓰기 전에 ``), add:

```markdown
그림 문서는 지도 파일이 있어야 등록된다. 없으면 `limn add`·`limn doc add`와 서버 기동이 거절한다. 보기 전용 PDF가 없을 때와 같다. 지도가 가리키는 PDF는 등록 때 보지 않는다. 확장자는 소문자 `.limnmap.json` 그대로여야 한다. 지도 형식은 [api.md](api.md) §그림 요소 지도 (`limn-figure-map/1`), 가져오기는 [build-sync.md](build-sync.md) §그림 문서에 있다.
```

In `operations.md` §여러 문서 (`--doc`), in the table, add after the `x/file.pdf` row:

```markdown
| `x/figures.limnmap.json` | 그림 문서. 그림 저장소가 낸 PDF와 요소 지도를 가져온다. 재빌드가 없고, 두 파일이 바뀌고 서로 맞으면(3초마다 확인) 쪽을 다시 그린다. 핀은 쪽과 영역으로 찍는다 |
| `root::sub/figures.limnmap.json` | 그림 문서. 문서 폴더(지도 속 코드 경로의 기준)가 `root/`다 |
```

and replace the end of the `root::sub/main.tex` row, `메인은 빌드 루트 안에 있어야 한다`, with `메인은 빌드 루트 안에 있어야 한다. 그림 지도에도 쓴다(아래 줄)`.

- [ ] **Step 3: `build-sync.md`**

At the end of the intro paragraph that names the build modules (the one ending `실행 설정은 서비스가 호출 시점에 받는다.`), append:

```markdown
그림 문서의 가져오기는 같은 기능의 [`figure.py`](../../src/limn/features/builds/figure.py)가, 빌드마다 보관한 지도 사본 읽기와 지도 경로 검사는 공통 `build.py`가 맡는다(§그림 문서).
```

In the `> **한눈에**` box, replace `보기 전용 PDF는 빌드 대신 파일 변화를 감시한다.` with `보기 전용 PDF는 빌드 대신 파일 변화를 감시하고, 그림 문서는 지도와 PDF가 서로 맞을 때만 가져온다.`

In §빌드 결과, replace the `BuildAborted(kind)` row's kind list `` `kind` 는 `pdf_missing`(보기 전용 PDF가 없다)·`crashed`(추적 빌드의 예상 밖 예외)·`worker_crashed`(백그라운드 스레드의 예상 밖 예외) `` with:

```markdown
`kind` 는 `pdf_missing`(보기 전용 PDF가 없다)·`figure_unready`(감시 밖에서 가져오기를 불렀는데 그림 문서의 지도와 PDF가 맞지 않는다. 감시는 여기까지 오지 않고 기다린다)·`crashed`(추적 빌드의 예상 밖 예외)·`worker_crashed`(백그라운드 스레드의 예상 밖 예외)
```

Append at the end of the file:

````markdown
## 그림 문서

`--doc` 의 경로가 `.limnmap.json` 인 문서는 그림 저장소가 낸 PDF와 요소 지도를 가져온다. Limn은 그림 저장소의 코드를 실행하지 않는다. 지도 형식은 [api.md](api.md) §그림 요소 지도 (`limn-figure-map/1`), 문서 폴더의 뜻은 [domain.md](domain.md) §그림 문서에 있다.

감시 스레드는 보기 전용 PDF와 같다. 3초마다 지문을 재고, 가져온 뒤나 미룬 뒤에는 그 지문을 `docs/<키>/pdf_sig.txt` 에 적는다.

```text
지문 = <지도 mtime_ns>:<지도 크기>|<PDF mtime_ns>:<PDF 크기>
```

- PDF는 지도가 가리키는 파일이다. 지도가 바뀌지 않았으면 지도를 다시 읽지 않고 두 파일의 `mtime:크기`만 본다. 지도를 받지 않았거나 PDF가 없으면 PDF 쪽은 `-` 다.
- 지문이 적힌 값과 다르면 지도와 PDF를 한 번씩 읽어 검사한다. 지도가 검사를 통과하는지, 지도의 `pdf` 가 문서 폴더 안인지, PDF 바이트의 SHA-256이 `pdf_sha256` 과 같은지 본다.
- 하나라도 어긋나면 이번 차례는 빌드하지 않고 실패도 기록하지 않는다. 화면은 앞 빌드 그대로다. 그때 본 지문만 적고 이유를 서버 로그에 한 줄 남긴다. 그래서 두 파일 중 하나가 다시 바뀌어야 다시 본다. 생산자가 PDF를 먼저 쓰고 지도를 나중에 쓰는 사이의 틈이 여기에 걸린다. 쓰는 순서가 거꾸로여도 두 파일이 맞는 차례에 가져온다.
- 맞으면 검사한 바이트 그대로 쪽을 그린다. 그래서 검사한 PDF와 화면의 PDF가 어긋날 수 없다. 새 `pages-<build>/` 에는 쪽 이미지, PDF 사본(지도 이름에서 `.limnmap.json` 을 뺀 `<이름>.pdf`), 지도 사본 `figmap.json` 이 함께 있다. 쪽 폴더는 지금 것과 바로 앞 것을 남기므로, 옛 빌드 화면에서 한 드래그는 그 빌드의 지도로 읽는다.
- 빌드 경로는 보기 전용 PDF와 같은 `run_tracked` 다. 그래서 `build_seq`, 빌드 이력, 뷰어의 쪽 교체가 LaTeX 빌드와 똑같이 돈다. 이력의 `src_hash` 는 PDF 바이트의 SHA-256과 지도 바이트의 SHA-256을 이어 다시 해시한 값(앞 32자)이다. 둘 중 하나가 바뀌면 옛 핀은 점선(추정)이 된다(§위치 추정 (`est`)).
- 쪽 그리기가 실패하면 보기 전용 PDF처럼 같은 파일로 되풀이하지 않는다.
- 지도의 쪽 수가 PDF의 쪽 수와 달라도 가져온다. PDF에 없는 쪽의 지도 항목은 쓰이지 않는다.
- 지도 파일이 사라지면 아무것도 하지 않는다. 화면은 마지막으로 가져온 그림이다. 지도가 없는 채로는 서버가 뜨지 않는다([instances.md](instances.md) §여러 문서 (`DOCS=`)).
- 지도와 PDF는 경로의 마지막 조각이 심볼릭 링크면 읽지 않는다. 지도는 4 MiB까지만 읽는다.
- 기동 때는 지문이 바뀌었거나 쪽 이미지가 없을 때 가져온다. `--no-build` 는 그림 문서에 적용하지 않는다.
- `stale_build` 는 늘 `false` 다. `POST /api/rebuild?doc=<키>` 는 보기 전용 문서처럼 `400` 이다. 그림을 고쳤으면 그림 저장소에서 다시 렌더한다.
- 감시가 아닌 경로로 추적 빌드가 그림 문서를 가져오다 두 파일이 맞지 않으면, 실패를 `BuildAborted("figure_unready")` 로 기록한다(§빌드 결과).
````

- [ ] **Step 4: `domain.md`**

In the summary box at the top, replace `여러 문서의 서버 결정과 보기 전용 PDF` with `여러 문서의 서버 결정, 보기 전용 PDF와 그림 문서`.

In §용어, add after the `**보기 전용 PDF**` row:

```markdown
| **그림 문서** | 그림 저장소가 렌더한 PDF와 요소 지도를 가져와 띄우는 문서다. 문서 목록에는 지도 파일(`.limnmap.json`)을 적는다(§그림 문서). |
| **요소 지도** | 그림 PDF의 쪽마다 요소의 나무를 적은 JSON이다. 요소마다 쪽 위 영역과, 그 요소를 그린 코드의 파일·줄이 있다. 형식은 [api.md](api.md) §그림 요소 지도 (`limn-figure-map/1`)에 있다. |
```

In the capability table P0 put in §여러 문서, add the kind `figure` with these values, in the table's own orientation: `builds_from_source` 아니요, `watches_files` 예, `takes_line_pins` 아니요, `shows_revisions` 아니요, `view_only` 예. Add the capability `has_element_map`, 예 only for `figure`, described as `요소 지도를 가진다. 감시가 지도와 그 PDF를 함께 가져오고 쪽 폴더마다 지도를 보관한다`.

After `### 보기 전용 PDF` and its paragraphs, before `## 알려진 제약`, add:

```markdown
### 그림 문서

코드로 그린 그림은 PDF로 받아 같은 문서 목록에 둔다. 그림 저장소는 PDF(그림 한 장이 한 쪽)와 요소 지도(`.limnmap.json`)를 내고, 문서 목록에는 지도 파일을 적는다. 지도는 쪽마다 요소의 나무다. 요소마다 쪽 위 영역(`frac`)과, 그 요소를 그린 코드의 파일·줄(`src`)이 있다. 형식과 검사 규칙은 [api.md](api.md) §그림 요소 지도 (`limn-figure-map/1`)에 있다.

문서 폴더는 `<폴더>::<지도>` 의 앞 폴더이고, `::` 가 없으면 지도가 있는 폴더다. 지도 속 `src`·`impl` 경로는 이 폴더 기준이고, `pdf` 는 지도가 있는 폴더 기준이다. 어느 경로든 문서 폴더 밖이거나 점으로 시작하는 이름 아래면 받지 않는다. 심볼릭 링크는 푼 뒤에 본다.

그림 문서는 빌드하지 않고 가져온다([build-sync.md](build-sync.md) §그림 문서). 가져올 때마다 지도를 쪽 폴더에 함께 보관하므로, 핀을 찍은 빌드의 지도를 다시 읽을 수 있다.

지금 그림 문서의 pick과 핀은 보기 전용 PDF와 같다. pick은 쪽·영역과 영역 글자를 돌려주고, 핀은 쪽·영역 핀이다. 다만 pick의 `pdf`·`name` 은 드래그한 빌드의 지도가 가리키는 PDF를, 핀 레코드의 `pdf`·`name` 은 화면 빌드의 지도가 가리키는 PDF를 적는다. `/api/docs`·`/api/meta` 의 `kind` 는 `figure` 이고 `view_only` 는 `true` 다.

그림 문서는 줄 핀을 받지 않으므로, 파일만 준 요청으로 문서를 고르는 규칙(`doc_for_file`)의 후보가 아니다. 그래서 그림 폴더가 LaTeX 문서의 빌드 루트 안에 있어도 그 폴더 파일의 줄 핀은 LaTeX 문서로 간다.
```

In §알려진 제약 → §상태와 운영 규칙의 한계, append to the bullet `**여러 문서의 src_mtime은 빌드 루트 전체를 훑는다.**`:

```markdown
 그림 폴더가 LaTeX 문서의 빌드 루트 안에 있으면, 그림 PDF를 다시 렌더할 때 그 LaTeX 문서도 '원고 수정됨'으로 보인다.
```

- [ ] **Step 5: `api.md`**

In §엔드포인트 → 버전·상태·사람, in the `/api/docs` row, replace `kind:"tex"\|"pdf"` with `kind:"tex"\|"pdf"\|"figure"`, and after `` `other_open` 은 지금 설정에 없는 문서 키의 열린 핀 수다 `` add ``. `view_only` 는 보기 전용 PDF와 그림 문서(§그림 요소 지도 (`limn-figure-map/1`))에서 `true` 다``.

In §화면·PDF·정적 파일, in the `/pdf?build=<pages_build>` row, replace `PDF 사본(`pages-<build>/<main>.pdf`)` with `PDF 사본(`pages-<build>/<main>.pdf`, 그림 문서는 지도 이름에서 `.limnmap.json` 을 뺀 `<이름>.pdf`)`.

In §빌드, in the `POST /api/rebuild` row, replace `보기 전용 문서면 `400`` with `보기 전용 문서와 그림 문서면 `400` 이다(`view_only_no_rebuild`)`.

In §보기 전용 PDF 문서의 pick·핀, append after the last bullet list (after `` `/api/snippet` 도 `400` 이다. ``):

```markdown
**그림 문서.** `kind:"figure"` 문서도 지금은 이 절의 규칙을 그대로 따른다. `view_only` 가 `true` 이고, pick·핀·수정·거절이 모두 같다. 다른 것은 PDF를 적는 두 값이다.

- pick의 `pdf` 는 드래그한 빌드(`pdf_build`)의 지도가 가리키는 PDF의 원고 폴더 기준 경로이고, `name` 은 그 파일 이름이다. 영역 글자는 그 빌드의 PDF 사본에서 뽑는다.
- 저장 레코드의 `pdf` 는 화면 빌드의 지도가 가리키는 PDF의 절대경로이고, `name` 은 그 파일 이름이다.
- 그 빌드에 읽을 수 있는 지도가 없거나 지도의 `pdf` 가 문서 폴더 밖이면, 두 값 모두 지도 파일을 적는다. 문서 폴더 밖의 경로는 적지 않는다.
```

In §핀 레코드 스키마, replace the `pdf` row's first sentence `보기 전용 PDF 문서의 핀에만 있다. 그 PDF의 절대경로다.` with `보기 전용 PDF 문서와 그림 문서의 영역 핀에만 있다. 그 PDF의 절대경로다(그림 문서는 지도가 가리키는 PDF, §보기 전용 PDF 문서의 pick·핀).`

Before `## 휴지통`, add:

````markdown
## 그림 요소 지도 (`limn-figure-map/1`)

그림 문서([domain.md](domain.md) §그림 문서)의 요소 지도는 그림 저장소가 쓰고 Limn이 읽는 생산자 계약이다. Limn은 지도를 만든 도구를 모른다. 형식은 더하기만 한다. 이 판이 모르는 키는 무시하고, 뜻을 바꾸는 변경은 `format` 의 판 번호를 올린다. 지금 서버는 지도를 가져와 빌드마다 보관하고, 핀의 PDF 이름에 쓴다([build-sync.md](build-sync.md) §그림 문서).

```json
{
  "format": "limn-figure-map/1",
  "pdf": "figures.pdf",
  "pdf_sha256": "<PDF 바이트의 SHA-256, 소문자 16진 64자>",
  "pages": [
    {
      "page": 1,
      "figure": "B2",
      "title": "Deployment calendar",
      "elements": [
        {"id": "B2", "frac": [0, 0, 1, 1],
         "src": {"file": "src/B2_calendar.py", "lo": 12, "hi": 140}},
        {"id": "B2/calendar", "parent": "B2", "part": "CalendarStrip", "label": "달력",
         "frac": [0.06, 0.18, 0.88, 0.12],
         "src": {"file": "src/B2_calendar.py", "lo": 80, "hi": 97}},
        {"id": "B2/calendar/m07", "parent": "B2/calendar", "part": "MonthCell", "label": "7월",
         "frac": [0.47, 0.18, 0.07, 0.12],
         "src": {"file": "src/B2_calendar.py", "lo": 88, "hi": 95},
         "impl": {"file": "lib/components.py", "lo": 410, "hi": 470}}
      ]
    }
  ]
}
```

| 필드 | 규칙 |
| --- | --- |
| `format` | `"limn-figure-map/1"` |
| `pdf` | 지도 파일이 있는 폴더 기준 상대 경로. 문서 폴더 안이어야 한다 |
| `pdf_sha256` | 지도가 설명하는 PDF 바이트의 SHA-256. 소문자 16진 64자 |
| `pages[].page` | 1부터 세는 쪽 번호. 지도 안에서 겹치지 않는다 |
| `pages[].figure` | 그림 id. 그 쪽의 뿌리 요소 id와 같다. 200자 이하 |
| `pages[].title` | 선택. 그림 제목. 200자 이하 |
| `elements[].id` | 비어 있지 않은 문자열, 200자 이하. 지도 전체에서 유일하다. 다시 렌더해도 같은 뜻의 요소는 같은 id를 받는다 |
| `elements[].parent` | 같은 쪽 요소의 id. 뿌리만 없다(또는 `null`). 순환이 없다 |
| `elements[].frac` | `[x, y, w, h]`. 쪽 폭·높이에 대한 비율이고 원점은 왼쪽 위다. 뿌리는 `[0, 0, 1, 1]` 이다 |
| `elements[].src` | 선택. 그 요소를 부른 코드 `{file, lo, hi}`. `file` 은 문서 폴더 기준 상대 경로(`/` 구분)다. 코드 줄이 없는 벡터 그래픽의 요소는 뺀다 |
| `elements[].impl` | 선택. 공통 부품을 구현한 코드. `src` 와 같은 모양이다 |
| `elements[].part`, `elements[].label` | 선택. 사람에게 보이는 이름. 200자 이하 |

**검사.** 서버는 지도를 읽을 때 아래를 차례로 본다. 하나라도 어기면 지도 전체를 받지 않는다. 괄호 안은 서버 로그에 남는 이유 코드다.

- 파일이 4 MiB 이하다(`too_large`). 크기는 해석 전에 본다.
- UTF-8 JSON이고 같은 키가 두 번 나오지 않는다(`not_json`). 맨 위는 객체다(`bad_shape`).
- `format` 이 맞다(`bad_format`). `pdf` 와 `pdf_sha256` 의 모양이 맞다(`bad_shape`).
- 쪽 번호가 1 이상의 정수이고 겹치지 않는다(`bad_page`).
- 쪽마다 요소는 5000개까지다(`too_many_elements`). 개수는 요소를 읽기 전에 센다.
- `figure`·`title`·요소 `id`·`part`·`label` 은 200자(`MAP_MAX_TEXT`, 바이트가 아니라 글자 수) 이하다(`bad_shape`). 핀이 이 값을 저장하기 때문이다.
- `frac` 은 유한수 넷이고 `0 ≤ x`, `0 ≤ y`, `w > 0`, `h > 0`, `x + w ≤ 1 + 1e-6`, `y + h ≤ 1 + 1e-6` 이다(`bad_frac`).
- `lo`·`hi` 는 정수이고 `1 ≤ lo ≤ hi` 다. 그 밖의 필드도 적힌 모양이어야 한다(`bad_shape`).
- id가 지도 전체에서 유일하다(`duplicate_id`).
- 쪽마다 `parent` 없는 요소가 정확히 하나이고, 그 id가 `figure`, `frac` 이 `[0, 0, 1, 1]` 이다(`no_root`).
- 모든 `parent` 가 같은 쪽 요소를 가리키고 순환이 없다(`bad_parent`).
- `src`·`impl` 의 `file` 은 문서 폴더 안이고, 점으로 시작하는 이름 아래가 아니다. 심볼릭 링크는 푼 뒤에 본다(`path_outside`). `pdf` 가 문서 폴더 밖이면 가져오기가 미룬다.

**쓰는 순서.** 생산자는 PDF를 먼저 쓰고, 지도는 마지막에 원자적으로 바꾼다(임시 파일에 쓰고 이름 바꾸기). 순서가 달라도 `pdf_sha256` 이 맞을 때만 가져오므로, 어긋난 짝이 화면에 오르지는 않는다.
````

- [ ] **Step 6: `architecture.md` and `index.md`**

In `architecture.md` §현재 구조, in the `순수 도메인` row, add `` `figmap.py`(그림 요소 지도 파서) `` after `` `mapping.py` ``. In §의존 방향, replace `순수 도메인 (pins/, build_values, mapping, scope, mentions, guidance, mark)` with `순수 도메인 (pins/, build_values, mapping, figmap, scope, mentions, guidance, mark)`.

In `index.md`, in the catalog:
- `domain.md` responsibility: replace `여러 문서 서버 규칙` with `여러 문서 서버 규칙(보기 전용 PDF·그림 문서)`.
- `build-sync.md` responsibility: replace `보기 전용 PDF 감시` with `보기 전용 PDF 감시, 그림 문서 가져오기`.
- `api.md` responsibility: replace `pins.md 형식` with `pins.md 형식, 그림 요소 지도 형식`.

In the file map:
- In the `src/limn/features/builds/*` row's responsibility, after `원고 복사·LaTeX·PDF 렌더(`engine.py`)`, add `, 그림 문서 가져오기(`figure.py`: 지도·PDF 검사, 지문, 미루기, 빌드별 지도 사본)`.
- In the `src/limn/build.py` row's responsibility, append `, 그림 문서의 지도 경로 검사(`figure_source_check`·`figure_pdf`)와 빌드별 지도 사본 읽기(`load_build_map`·`build_figure_pdf`)`.
- Add after the `src/limn/mapping.py` row:

```markdown
| `src/limn/figmap.py` | 그림 요소 지도(`limn-figure-map/1`)의 순수 파서: 상수, 값 타입(`FigureMap`·`MapPage`·`MapElement`), 거절 값(`MapRejected`)과 `parse_map` | 지도 형식·검사 규칙 변경(생산자 계약) | api.md §그림 요소 지도 (`limn-figure-map/1`), domain.md, build-sync.md |
```

- [ ] **Step 7: CHANGELOG**

In `CHANGELOG.md` under `## Unreleased`, append to the summary paragraph: ` Figure documents arrive in part: they register, import and pick as regions, and `/api/docs` and `/api/meta` gain the document kind `figure`.` Then add, before `### Security`:

```markdown
### Added

- **Figure documents: registration and import.** A `--doc`/`DOCS=` entry whose path ends in `.limnmap.json` serves
  a figure document: the PDF a figure repository renders, plus its element map (`limn-figure-map/1`, Handbook
  api.md). `ROOT::path/figures.limnmap.json` sets the folder the map's source paths are relative to; without `::`
  it is the map's folder. The watch imports the pair only when the map's `pdf_sha256` is the PDF's SHA-256, renders
  exactly the bytes it checked, and keeps the map in every page directory. While the two disagree (the producer has
  written one and not yet the other), nothing is built and no failure is recorded. `/api/docs` and `/api/meta`
  report `kind: "figure"` with `view_only: true` (ADR-0011 D5: the document kind value list grows). Picks and pins
  on a figure document are region pins named after the map's PDF, and `POST /api/rebuild` answers `400`. A missing
  map refuses startup, like a missing view-only PDF. Existing documents, fields and `pins.md` are unchanged.
```

- [ ] **Step 8: Check the Handbook**

Run:

```bash
uv run pytest -q tests/test_handbook_refs.py tests/test_naming.py
uv run python tools/handbook-publish/publish.py check docs/handbook/index.md
```

Expected: both pytest modules pass. The publish check ends with exit code 0 when the fonts and the Pandoc version of `docs/handbook/book.json` are installed (verification.md §7). If it stops only on a tool-version or font mismatch, record that in the PR, and rely on `tests/test_handbook_refs.py` for the links and section references.

- [ ] **Step 9: Commit**

```bash
git add docs/handbook/purpose.md docs/handbook/instances.md docs/handbook/operations.md docs/handbook/build-sync.md docs/handbook/domain.md docs/handbook/api.md docs/handbook/architecture.md docs/handbook/index.md CHANGELOG.md
git commit -s -m "docs: describe figure documents and the element map format" -m "The scope becomes LaTeX manuscripts and vector graphics (ADR-0011 D1). The Handbook states how a figure document is registered, how its map and PDF are imported and deferred, the map format and checks as a producer contract, and that it picks and pins as regions for now. CHANGELOG notes the new document kind value."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 8: Whole-branch gates and the pull request

**Files:** none changed.

**Interfaces:** Consumes everything above; produces the PR.

- [ ] **Step 1: Run every gate once**

```bash
uv sync --group dev
uv run pytest -q -rs -n 4 --dist loadscope 2>&1 | tail -n 3
bash tests/test_instances.sh 2>&1 | tail -n 2
uv run ruff check
uv run ruff format --check
uv run shellcheck src/limn/instances.sh src/limn/features/administration/instance_*.sh tests/test_instances.sh
uv run mypy
git diff --exit-code origin/main -- tests/data/contract_snapshot.json tests/data/pin_records.jsonl
```

Expected: pytest ends with `passed` and no `failed`/`error`, its count above the baseline by the new tests. The shell summary shows 0 failed. Ruff prints `All checks passed!` and the format check reports every file already formatted. ShellCheck prints nothing. mypy prints `Success: no issues found`. The last command prints nothing: the contract snapshot and the record corpus did not change.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin feat/figure-documents-p1a
gh pr create --title "Figure documents P1a: element map parser, registration and import" --body-file - <<'EOF'
Implements docs/superpowers/plans/2026-09-30-figure-documents-p1a-map-and-import.md (index: 2026-09-30-figure-documents.md, ADR-0011).

- `limn.figmap`: pure parser of `limn-figure-map/1` (every rejection a value; Hypothesis properties).
- `.limnmap.json` in `--doc`/`DOCS=` registers `kind: "figure"` (Python and the shell mirror); a missing map refuses startup like a missing PDF.
- Import build: renders only when `pdf_sha256` matches the PDF, from the checked bytes; defers without building or failing otherwise; keeps the map per build.
- Figure documents pick and pin as regions named after the map's PDF; rebuild stays 400.
- Follows the index's P1a amendments: `has_element_map`, shared readers in `limn.build`, `figure_src_hash`, the missing-map refusal, `MAP_MAX_TEXT`.
- Contract: `/api/docs`/`/api/meta` `kind` gains `figure` (ADR-0011 D5). Snapshot and record corpus unchanged.

Gates: <paste the Step 1 numbers>.
EOF
```

Expected: the PR URL. Merge only after review: P1a is unreleased groundwork (index: no release until P1c).

---

## Done (P1a)

- [ ] Task 0's check passed; Tasks 1–7 committed with sign-off and the CLA line; Task 8 gates green.
- [ ] Code uses the index's names: `Doc.has_element_map`, `limn.build.FIGMAP_NAME`/`load_build_map`, `figure.figure_src_hash`, `figmap.MAP_MAX_TEXT`.
- [ ] A figure document registers (Python and shell), imports only matching pairs, never records a failure from the watch while the files disagree, keeps `figmap.json` in every page directory, and serves `/pdf`.
- [ ] Picks and pins on a figure document are region pins named after the map's PDF; no path outside the figure folder is read or named.
- [ ] Handbook topics purpose, instances, operations, build-sync, domain, api, architecture and index are current; CHANGELOG has the Unreleased entry.
- [ ] `tests/data/contract_snapshot.json` and `tests/data/pin_records.jsonl` unchanged.

## Self-review notes

- **Spec coverage (P1a slice).** D1 scope → Task 7 purpose.md. D2 registration by suffix, with the shell mirror in the same commit → Task 2. D3 Limn never renders → Task 4 (import only) and Task 7. Import rules (signature, `pdf_sha256` deferral, per-build map copy, `src_hash`, rebuild 400) → Tasks 3–5. Map checks (size, element cap, `MAP_MAX_TEXT`, finite `frac`, unique ids, parents, paths) → Task 1. `pdf` containment → Tasks 3–4. SVG never served → nothing serves SVG. Region fallback of the pick → Task 6. Map format written in the Handbook, not only in code → Task 7. Map pick, `el`, read-time fields, SKILL and viewer are P1b/P1c.
- **Index rules this plan builds in.** A missing map refuses startup (`DocFileMissing`), as a missing view-only PDF does (Task 2). `MAP_MAX_TEXT = 200` for figure, title, id, part and label (Task 1, Handbook in Task 7). The `src_hash` formula `figure_src_hash` (Task 4).
- **Decisions this plan makes that the index left open.** The map suffix is case-sensitive in Python and shell alike, while `.tex`/`.pdf` stay as they are. A deferral settles its signature, so a mismatched pair is re-hashed only after a file changes, and it logs one `stderr` line. `render_figure_doc` takes the verified pair, so the rendered bytes are the checked bytes; the tracked step `import_now` covers a direct call, and `figure_unready` is recorded only then. A page-count mismatch is imported anyway. An empty `pages` list is a valid map. Repeated JSON keys and lone surrogates are refused. A region pin's `pdf` names the map's PDF, falling back to the map file. Test placement: `tests/test_figmap.py` for the pure module, the slices for the rest.
- **For P1b.** `load_build_map` parses the copy on every call; the index puts P1b's `BuildMapCache` in front of it. The startup line and `pins.md` heading for a figure document follow `view_only`, which flips in P1b. Names a pin stores are capped at `MAP_MAX_TEXT` (200 characters) from P1a on.

