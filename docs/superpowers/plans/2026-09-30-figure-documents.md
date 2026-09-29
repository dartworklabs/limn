# Figure Documents Implementation Plan (index and shared contract)

<!-- Code blocks here are transcribed into the repository and formatted there; ruff leaves them as written. -->
<!-- fmt: off -->

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement the phase plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person drag on a figure (a vector graphic delivered as PDF) and get the element and the lines of the code that drew it, handled as an ordinary Limn pin.

**Architecture:** A third document kind, `figure`, reuses the view-only PDF path (watch, page images, PDF.js). A producer-written element map (`limn-figure-map/1`) replaces SyncTeX. A figure pin is a line pin on the generating script with one extra optional field `el`. Positions across re-renders are computed at read time.

**Tech Stack:** Python 3.10+, standard library only at runtime, pytest + Hypothesis, Ruff, mypy; build-free static viewer (plain JS/CSS).

**Spec:** [`docs/superpowers/specs/2026-09-30-figure-documents-design.md`](../specs/2026-09-30-figure-documents-design.md). Decisions are recorded in [ADR-0011](../../adr/0011-figure-documents.md).

This file is the index. It fixes the order of the phase plans and the names and types they share. Each phase plan owns its tasks. **A phase plan must not rename anything defined in §Shared contract.** If code facts force a change, stop, change this file first, and note it in the PR.

## Before execution — owner confirmations

The plans are written on these premises. Confirm them before P1a starts, or change ADR-0011 and this index first.

- ADR-0011 D2, D3, D4, D6, D7 (recorded as plan premises; D1 and D5 are decided).
- The `bad_scope`/`bad_via` error sentences list the grown values (their `reason` codes stay).

P0 has no open premise and can start now.

## Phase plans

| Phase | Plan | Delivers | Depends on | Release |
| --- | --- | --- | --- | --- |
| P0 | [`2026-09-30-figure-documents-p0-capabilities.md`](2026-09-30-figure-documents-p0-capabilities.md) | `Doc.is_pdf` replaced by capability properties; no behaviour change | — | patch (0.3.x) |
| P1a | [`2026-09-30-figure-documents-p1a-map-and-import.md`](2026-09-30-figure-documents-p1a-map-and-import.md) | `figmap.py` parser, `figure` kind registration, import build with per-build map copy; figure docs pick as regions | P0 | none (unreleased on `main`) |
| P1b | [`2026-09-30-figure-documents-p1b-pick-and-pins.md`](2026-09-30-figure-documents-p1b-pick-and-pins.md) | map pick, `el` pins, read-time `mark`/`el_sync`, API and `pins.md` additions, SKILL | P1a | none (unreleased) |
| P1c | [`2026-09-30-figure-documents-p1c-viewer.md`](2026-09-30-figure-documents-p1c-viewer.md) | viewer: figure tab, element outline, location line, ladder, marks, `지도` badge | P1b | **0.4.0** once P1a–P1c are on `main` |
| P2 | §P2 outline below | revisions for figure docs, before/after page overlay | P1c | patch |
| P3 | spec §이행 절단면 | manuscript `\includegraphics` → figure element (exploration branch first) | P1c | — |
| P4 | spec D7 | exporter for vector graphics without code (outside the server) | P1b | — |

Each phase is one PR. Merge it only when [verification.md](../../handbook/verification.md) gates are green and its own §Done checklist is ticked. P1a and P1b leave `main` in a consistent intermediate state (see §Intermediate states), so no release tag is cut until P1c.

## Global Constraints

- Server runtime stays standard-library only (`dependencies = []`). No SVG rasterising, no external API calls, no subprocess other than the existing `pdftoppm` path.
- The agent contract (`pins.md`, HTTP API) only grows. Decided in ADR-0011 (D5 = A): the value lists `kind` (document), `scope`/`levels[].level`, pin `kind`, and `via` gain the values in §Shared contract. No existing field, path, status or value changes meaning.
- Pin files are written only through `PinStore.transact()`. Rendering never writes pins (positions across renders are read-time fields).
- Old state folders are read without migration; a state folder with figure pins must stay valid for the previous release (`fits_record` accepts it, unknown fields round-trip byte for byte).
- Code, comments, docstrings, test names, commit messages: English. Handbook: Korean, present tense, no dates. `README`/`skill/SKILL` are edited in both languages together.
- No real e-mails, home paths or host names in code, tests or docs (`alice@example.com`, `/srv/paper`).
- A Handbook section reference (the `docs/handbook/<topic>.md §<heading>` form) may name only a heading that exists when the file is committed: `tests/test_handbook_refs.py` scans every tracked file under `src/`, `tests/` and `docs/`, these plans included. New headings are linked from Handbook topics only; code is re-pointed to them after they exist.
- Commits: `git commit -s`, then the line `I agree to the Limn CLA (CLA.md).` right after `Signed-off-by:`.
- Coding rules: team skills `code-implement`, `code-testing`, `code-security` over existing habits; tests colocated with their slice (ADR-0010); one owner per action (ADR-0009): figure pick lives in `features/pins/location`, figure import in `features/builds`.
- Gates for every PR:
  ```bash
  uv sync --group dev
  uv run pytest -q -rs -n 4 --dist loadscope
  bash tests/test_instances.sh
  uv run ruff check
  uv run ruff format --check
  uv run shellcheck src/limn/instances.sh src/limn/features/administration/instance_*.sh tests/test_instances.sh
  uv run mypy
  ```

## Shared contract

### Document kinds and capabilities (P0 introduces, P1a/P1b extend)

`src/limn/documents.py`:

```python
DocKind: TypeAlias = Literal["tex", "pdf"]  # P1a adds "figure"


class Doc:
    kind: DocKind

    @property
    def builds_from_source(self) -> bool:
        """latexmk builds, --git-pull, POST /api/rebuild, stale_build."""
        return kind_builds_from_source(self.kind)

    @property
    def watches_files(self) -> bool:
        """The view-only watch thread redraws the pages when the watched files change."""
        return self.kind == "pdf"  # P1a: kind in ("pdf", "figure")

    @property
    def takes_line_pins(self) -> bool:
        """file/lo/hi pins, anchor re-sync, doc_for_file routing."""
        return self.kind == "tex"  # P1b: kind in ("tex", "figure")

    @property
    def shows_revisions(self) -> bool:
        """The 변경사항 view (git history of the manuscript files, latexdiff)."""
        return self.kind == "tex"  # P2 may extend

    @property
    def view_only(self) -> bool:
        """Region pins only. The API's `view_only`."""
        return not self.takes_line_pins

    @property
    def has_element_map(self) -> bool:  # P1a adds this property
        """Its pages come with a producer's element map: the watch imports the map with its PDF, and every page
        folder keeps the map."""
        return self.kind == "figure"


def kind_builds_from_source(kind: DocKind) -> bool:
    """The rule behind Doc.builds_from_source, for decisions on a parsed --doc (DocSpec) before a Doc exists."""
    return kind == "tex"
```

`is_pdf` is removed everywhere in P0: `Doc`, both `DocumentFacts`, the build/sync/revision protocols (`build.BuildDoc`, `features.builds.run.Rebuildable`, `features.sync.run.SyncDoc`, `features.revisions.core.RevisionDoc`) and `pins.render.DocHeading`. Each carrier keeps only the capabilities it reads (P0 plan §Contract issues 2); the pin parsers read `DocumentFacts.view_only`. Branches read capabilities, never `kind`; `kind` itself is only reported (API `kind`, the startup line).

| Capability | tex | pdf | figure after P1a | figure after P1b |
| --- | --- | --- | --- | --- |
| `builds_from_source` | ✓ | | | |
| `watches_files` | | ✓ | ✓ | ✓ |
| `takes_line_pins` | ✓ | | | ✓ |
| `shows_revisions` | ✓ | | | |
| `view_only` | | ✓ | ✓ | |
| `has_element_map` | | | ✓ | ✓ |

### Registration (P1a)

- `DOCS=`/`--doc` entry `KEY=NAME:ROOT::REL/PATH/x.limnmap.json` → `kind="figure"`, `src = ROOT`, `main = the map file`. Without `::`, `src` is the map's folder.
- The suffix constant is `figmap.MAP_SUFFIX = ".limnmap.json"`. The Python check and the shell mirror (`instance_documents.sh`) change in the same commit.
- Paths in the map: `pdf` is relative to the map file's folder; `src.file`/`impl.file` are relative to `Doc.src`. All must resolve inside `Doc.src`.

### `src/limn/figmap.py` (pure, P1a creates, P1b extends)

No file, subprocess or HTTP imports. Inputs are bytes and values.

```python
MAP_FORMAT = "limn-figure-map/1"
MAP_SUFFIX = ".limnmap.json"
MAP_MAX_BYTES = 4 * 1024 * 1024
MAP_MAX_ELEMENTS = 5000  # per page
Frac: TypeAlias = tuple[float, float, float, float]  # x, y, w, h; top-left origin; page fractions


@dataclass(frozen=True)
class SourceRef:
    file: str  # relative to Doc.src, POSIX separators
    lo: int  # 1-based, lo <= hi
    hi: int


@dataclass(frozen=True)
class MapElement:
    id: str
    parent: str | None  # None only for the page root
    frac: Frac
    src: SourceRef | None  # None: vector graphic without code (D7)
    impl: SourceRef | None
    part: str | None
    label: str | None


@dataclass(frozen=True)
class MapPage:
    page: int  # 1-based
    figure: str
    title: str | None
    elements: tuple[MapElement, ...]  # root first

    def root(self) -> MapElement: ...
    def by_id(self, el_id: str) -> MapElement | None: ...
    def ancestors(self, el: MapElement) -> tuple[MapElement, ...]:  # nearest first, root last
        ...


@dataclass(frozen=True)
class FigureMap:
    pdf: str
    pdf_sha256: str  # 64 lowercase hex
    pages: tuple[MapPage, ...]

    def page(self, n: int) -> MapPage | None: ...
    def find(self, el_id: str) -> tuple[MapPage, MapElement] | None: ...


MapRejectReason: TypeAlias = Literal[
    "too_large", "not_json", "bad_format", "bad_shape", "bad_page", "bad_frac",
    "duplicate_id", "bad_parent", "no_root", "too_many_elements", "path_outside",
]


@dataclass(frozen=True)
class MapRejected:
    reason: MapRejectReason
    detail: str  # English, for logs; never shown as a contract value


def parse_map(raw: bytes, *, source_inside: Callable[[str], bool]) -> FigureMap | MapRejected: ...
```

Rules `parse_map` enforces: size ≤ `MAP_MAX_BYTES` before decoding; `figure`, `title`, element `id`, `part` and `label` are at most `MAP_MAX_TEXT = 200` characters (`bad_shape` otherwise), because pins store them; `format == MAP_FORMAT`; pages have distinct 1-based `page`; element ids are unique across the whole map; exactly one root per page (`parent` absent, `id == figure`, `frac == (0, 0, 1, 1)`); every `parent` names an element of the same page and there is no cycle; every `frac` value is a finite number (use `limn.pins.shapes.is_finite_num`) with `0 ≤ x, y`, `w, h > 0`, `x + w ≤ 1 + 1e-6`, `y + h ≤ 1 + 1e-6`; `lo`/`hi` are ints (`is_int`) with `1 ≤ lo ≤ hi`; every `src.file`/`impl.file` passes `source_inside`; ≤ `MAP_MAX_ELEMENTS` per page. Unknown keys are ignored (the format grows additively).

P1b adds to the same module:

```python
COVER_MIN = 0.6
FILL_MIN = 0.5
LADDER_MAX = 8  # element rungs below the root: "el", "el2", ..., "el8"; the root rung is "fig"
FOLLOW_EPS = 1e-4
ElSync: TypeAlias = Literal["ok", "moved", "lost"]


@dataclass(frozen=True)
class ElementPick:
    chosen: MapElement
    ladder: tuple[MapElement, ...]  # chosen first, root last; at most LADDER_MAX rungs plus the root
    score: float  # cover of chosen, 0..1


def pick_element(page: MapPage, drag: Frac) -> ElementPick: ...  # total: falls back to the root
def ladder_scopes(ladder: tuple[MapElement, ...]) -> tuple[str, ...]: ...  # ("el", "el2", ..., "fig")
def element_kind(el: MapElement, root: bool) -> str: ...  # "figure" for the root, else "el:<part>" or "el:?"


@dataclass(frozen=True)
class ElementFollow:
    page: int | None
    frac: Frac | None
    sync: ElSync


def follow_element(m: FigureMap, el_id: str, page_then: int, frac_then: Frac) -> ElementFollow: ...
```

`pick_element` rule (spec §pick): `cover = |E∩D| / |D|`; the deepest **non-root** element with `cover ≥ COVER_MIN` wins (ties: smaller area, then map order); else the nearest common ancestor of the non-root elements with `fill = |E∩D| / |E| ≥ FILL_MIN`; else the root. The root never competes in the first two steps, because its cover is always 1. `element_kind` returns `"figure"` for the root and `"el:" + part[:77]` (or `"el:?"`) otherwise, so a pin `kind` stays within its 80-character limit. A zero-area drag counts as a point: cover is 1 for elements containing the point. The ladder keeps the chosen element, then its ancestors nearest first, capped at `LADDER_MAX` element rungs, then the root. `follow_element`: not found → `(None, None, "lost")`; found on the same page with every frac component within `FOLLOW_EPS` → `"ok"`; otherwise `"moved"`.

### Build import (P1a)

Shared build facts live in `src/limn/build.py`, because the pick slice, `documents.DocumentFacts` and the composition root read them and one feature slice must not import another (architecture.md §의존 방향):

- `FIGMAP_NAME = "figmap.json"`: the map copied into every `pages-<build>/` folder next to the PDF copy.
- `load_build_map(doc: Doc, build: str) -> FigureMap | MapRejected | None`: reads `pages-<build>/figmap.json` (None when absent). The pick and the read-time fields call this with the pick's `pdf_build` or the current build. P1b puts a per-run `BuildMapCache` (keyed by document folder, build, mtime_ns, size; 16 entries) in front of it.

`src/limn/features/builds/figure.py` owns the import:

- `render_figure_doc(...)` mirrors `render_pdf_doc` (same result type, same `run_tracked` path). Watch signature: `"<map mtime_ns>:<map size>|<pdf mtime_ns>:<pdf size>"` in the same signature file the view-only PDF uses. If the map is rejected, the PDF is missing, or `pdf_sha256` ≠ SHA-256 of the PDF bytes, the tick does not build and does not record a failure; the signature is saved so the pair is rechecked only after a change. The import renders exactly the bytes it hashed.
- `figure_src_hash(pdf_raw: bytes, map_raw: bytes) -> str`: SHA-256 over the SHA-256 digest of the PDF bytes followed by that of the map bytes, first 32 hex digits (as `build.doc_fingerprint`).
- A map that is missing at startup refuses the start with the same error as a missing view-only PDF. A map that disappears while running leaves the last pages in place.

### Pick answer (P1b)

For a figure doc with a loadable map for the requested `pdf_build`, `POST /api/pick` answers the **line body** (same fields as today) with:

| Field | Value |
| --- | --- |
| `file`, `name`, `lo`, `hi`, `raw_lo`, `raw_hi` | from the default rung's `src` (raw = chosen element's `src`) |
| `via` | `"map"` |
| `score` | `ElementPick.score` |
| `kind` | `element_kind(...)` of the default rung |
| `levels` | one rung per ladder element: `{level, lo, hi, n, label, snippet, el, merged?}`; `label` = element `label` or `part` or id; `n = hi - lo + 1`. Every rung lies in the chosen element's `src.file`; a ladder element drawn in another file gets no rung (it stays in `el.path`). Rungs with equal `lo`/`hi` merge into the **inner** rung, and the outer level name goes under `merged` |
| `default_level` | the first rung's level: `"el"`, or `"fig"` when the root was picked |
| `quote` | chosen element `label` or `""` |
| `el` | `{id, path, label?, part?, impl?: {file, lo, hi}, frac?}` in this key order; `path` = ids root first; `impl.file` relative to `Doc.src`; `frac` = the element's box on the traced build. The top-level `el` and every rung's `el` carry `frac` (the viewer draws the outline from it and switches rungs without a request) |
| `warn` | as today for low score |

Fallbacks → the **region body** (as view-only today) plus `el` when an element was found, and `warn` naming the reason:

- `figure_map_unavailable`: no loadable map for that build.
- `element_without_source`: the chosen element's lines cannot be given — no `src` (D7), the script is unreadable inside `Doc.src` (deleted, or a symlink leading out), or the range is past the script's current end.

`GET /api/snippet?levels=1` on a figure document returns only the `raw` rung (also its `default_level`); the LaTeX paragraph/environment ladder is not run over scripts.

### Pin record (P1b)

- New optional field `el` with the shape of the pick's `el`. `fits_record`: when present, `el` must be a dict whose `id` is a non-empty string and whose `path` is a list of strings; `label`/`part` strings when present; `impl` a dict `{file: str, lo: int, hi: int}` when present; `frac` four numbers when present. Malformed → broken, like other optional fields. A region-shaped pin may carry `el` (D7).
- `via` value list: `"synctex" | "text" | "map"`. `scope` value list gains `"el"`, `"el2"`…`"el8"`, `"fig"`. Pin `kind` gains `"el:<part>"` and `"figure"`. The `bad_scope`/`bad_via` error sentences list the grown values; their `reason` codes stay (owner to confirm: api.md §오류 응답 says a sentence does not change).
- `POST /api/pin` and `/edit` `loc` whitelist gain `el`; a malformed `el` is `400 bad_el` (new reason code). `el` is a location field: a `loc` without `el` drops it, as other location fields are dropped today. `/edit` does not turn a region pin into a line pin or back; the person re-pins.
- The anchor's comment marker follows the file suffix: `.py` skips `#` lines, every other file keeps `%`. LaTeX anchors stay byte-identical.

### Read-time fields (P1b)

`GET /api/pins` and `GET /api/pins/{id}` add (where `est` is added today; the Trash list and the `pin` echoed by change requests get none), for a pin with `el` in a figure doc whose current build map loads: `mark` (`[x, y, w, h]`), `mark_page` (int), `el_sync` (`"ok" | "moved" | "lost"`), from `follow_element` with `frac_then = el.frac` (the pin's own `frac` when `el.frac` is absent, as for an agent's pin; that can never be `"ok"`). Absent otherwise. Nothing is written; a render never changes `rev`. The viewer saves a figure pin's own `frac` as the element box, so a mark drawn without a current map sits where the person saw it.

### `pins.md` (P1b)

- Section title: a figure document's section ends with ` — 그림(요소 지도)` (`DocHeading.has_element_map`); the view-only PDF suffix is unchanged.
- Range column: unchanged code path; unknown scopes already print `kind` (`el:MonthCell`).
- Memo: `«label»` prefix whenever `el.label` is set; `공통 부품: <path>:<lo>-<hi>` appended when `el.impl` is set, where `<path>` is the document folder relative to `--manuscript` joined with `impl.file` (the same base as the location column).
- `el_sync == "lost"` prints the same warning style as `stale`: `요소 잃음`. The on-disk `pins.md` is only as fresh as its last render (known limit; `GET /pins.md` renders on request).
- One guidance line in the header when any open pin has `el` (same mechanism as the view-only guidance).

### Viewer (P1c)

Consumes only the fields above plus `/api/docs`/`/api/meta` `kind`. Rebuild UI shows only for `kind == "tex"` (`body.no-rebuild` replaces `body.view-only`). No new endpoint. The new viewer part is `js/figure.js`; the viewer never reads the map.

### Contract amendments at handover

The phase plans raised these; they are folded into the sections above. Plans that still describe "write the amendment into the index" now only check that the index says so.

| From | Amendment |
| --- | --- |
| P0 | `kind_builds_from_source` (and `Doc.builds_from_source` calls it); `is_pdf` removed from every carrier |
| P1a | `FIGMAP_NAME`/`load_build_map` in `build.py`; `has_element_map`; `figure_src_hash`; missing map at startup refuses the start |
| P1b | `el.frac`; root excluded from pick steps 1–2; `default_level` from the first rung; rungs in one file, merged inward, with `n`; grown error sentences; `pins.md` shared-part path; `element_kind` 77-character cap; broader `element_without_source`; `bad_el`; `.py` anchor comments; `raw`-only snippet ladder; `pins.md` figure section title |
| P1c | `body.no-rebuild` by kind |
| Orchestrator | `MAP_MAX_TEXT = 200`; `el` dropped by a `loc` without it |

## Intermediate states

| After | A figure document… |
| --- | --- |
| P0 | does not exist yet; behaviour identical to before |
| P1a | registers, imports, renders and watches like a view-only PDF; pick answers the region body; pins are region pins; its `pins.md` section is titled like a view-only PDF's |
| P1b | picks through the map; pins are line pins with `el`; agents see them in `pins.md` under a section titled `— 그림(요소 지도)`; the viewer still shows the plain line composer (works, no outline) and still shows the rebuild button, which answers `400`, because the viewer reads `view_only` there until P1c |
| P1c | full UI |

## P2 outline (plan written after P1c ships)

- `shows_revisions` true for figure docs. History pathspec = the distinct `src.file` and `impl.file` of the current build's map plus the map and PDF paths.
- Comparison: no latexdiff. The viewer overlays the previous build's page image on the current one (both builds' page folders are kept: `pages.cur` and the previous). New read route only if the existing page routes cannot serve a named previous build.
- Handbook `viewer.md` §변경 보기 and `api.md` §변경 보기와 비교 PDF gain the figure case.
- Pull when a figure pin closes. The user should see the fixed figure by the time the "처리됨" notice arrives, not after up to 60 seconds. When an agent closes a pin on a `watches_files` document with a `close_ref`, run the sync check at once. The check is a fast-forward only, with the same safety rules as the periodic check.
- `--git-pull` for figure documents. The 60-second fast-forward is what brings a merged figure change to the watched checkout, after which the watch imports it within seconds. P0 keeps the pull watch keyed on documents built from source, so check whether an instance whose only documents are figures still fast-forwards. If it does not, the pull must run for `watches_files` documents too, without a rebuild.

## Done (whole feature)

- [ ] P0, P1a, P1b, P1c merged; each PR's gates green.
- [ ] Contract snapshot contains a figure flow; the previous release reads a state folder with figure pins without dropping any (test from P1b).
- [ ] Handbook topics current: purpose, domain, build-sync, api, viewer, instances, index (file map); SKILL en/ko; README en/ko mention figure documents.
- [ ] CHANGELOG `0.4.0` entry states the contract additions (value lists grown per ADR-0011).
- [ ] `v0.4.0` tag after the viewer is measured on a real figure set.
