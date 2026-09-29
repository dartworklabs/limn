# Figure Documents P0: Document Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the boolean `Doc.is_pdf` with the five capability properties of the shared contract and type `Doc.kind` as `DocKind`, with no observable behaviour change for LaTeX and view-only PDF documents.

**Architecture:** `src/limn/documents.py` gains `DocKind`, the kind-level rule `kind_builds_from_source`, and the five capability properties. Every branch that read `is_pdf` or compared a kind string moves, one slice per task, to the capability that matches its intent. Each task updates that slice's protocol and test doubles in the same commit. Only sites that report the kind itself keep `kind`: the API field, a document's authority identity, and the startup line, which moves into an exhaustively matched pure function. The last task deletes the retired name, guards against it, and proves the move changed nothing.

**Tech Stack:** Python 3.10+ standard library; pytest + pytest-xdist; Ruff; mypy (`strict`, `strict_equality`, `exhaustive-match`); `tools/test_id_map.py` for the differential proof.

**Spec:** [`docs/superpowers/specs/2026-09-30-figure-documents-design.md`](../specs/2026-09-30-figure-documents-design.md) (§서버 → 문서 종류, §현재 코드의 이음매 → 위험한 자리 1, §이행 절단면 P0). The index [`2026-09-30-figure-documents.md`](2026-09-30-figure-documents.md) fixes the names; its §Shared contract is binding.

## Contract issues

These are code facts the index's §Shared contract did not cover. Each is an addition, not a rename, and the plan is written with the proposal. While this plan was written, the index took over issues 1 and 2: it now lists `kind_builds_from_source` and "`is_pdf` is removed everywhere". One difference remains. The index writes `Doc.builds_from_source` as `return self.kind == "tex"`, and this plan writes it as `return kind_builds_from_source(self.kind)`. Both have the same truth table, and the plan's form keeps a single rule. Either form satisfies the capability-table test.

1. **Two capability decisions happen before a `Doc` exists.** `serve_documents.docs_of` decides the state-root layout (`p["kind"] == "tex"`, `serve_documents.py:314`), and `serve_documents.pick_documents` picks the run's main file (`d["kind"] != "pdf"`, `serve_documents.py:365`). Both read the parsed `--doc` value `DocSpec`, which is a `TypedDict`, not a `Doc`. Both mean "builds from source". Left as string comparisons, the second one would take a figure's map file as the run's main `.tex` once P1a adds `"figure"`.
   **Proposal:** `documents.py` gains `def kind_builds_from_source(kind: DocKind) -> bool: return kind == "tex"`. `Doc.builds_from_source` returns `kind_builds_from_source(self.kind)`. The truth table is the contract's. Only the body form of that one property differs from the index, and P1a needs no edit there. **Add to the index's §Shared contract block:** the function signature, with the note "the rule behind `Doc.builds_from_source`, for decisions on a parsed `--doc`".
2. **The flag has more carriers than `Doc`.** Seven other declarations also carry `is_pdf`:
   - the parser-facing protocol `web.parse.DocumentFacts` and its implementation `documents.DocumentFacts`
   - the internal protocols `build.BuildDoc`, `features.builds.run.Rebuildable`, `features.sync.run.SyncDoc` and `features.revisions.core.RevisionDoc`
   - the pure value `pins.render.DocHeading`

   **Proposal:** each carrier keeps only the capabilities it actually reads:

   | Carrier | Capabilities it keeps |
   | --- | --- |
   | `DocumentFacts` (both) | `view_only` |
   | `BuildDoc` | `builds_from_source`, `watches_files` |
   | `Rebuildable` | `builds_from_source` |
   | `SyncDoc` | `builds_from_source` |
   | `RevisionDoc` | `shows_revisions` |
   | `DocHeading` | `view_only` and `builds_from_source` (two fields, because pins.md's heading makes two different decisions; see Table A rows 8–10) |

   **Change in the index:** "`Doc.is_pdf` is removed in P0" becomes "`is_pdf` is removed everywhere in P0 (`Doc`, `DocumentFacts`, the build/sync/revision protocols, `DocHeading`)". P1a/P1b plans must know that the pin parsers read `DocumentFacts.view_only`.
3. **Spec note (not an index conflict).** The spec says "`is_pdf`는 API 출력에만 파생 값으로 남긴다(`/api/docs`의 옛 필드)". No API response has an `is_pdf` field. The API field is `view_only`, in `/api/docs`, `/api/meta` and the view-only pick body. P0 keeps it byte-identical, fed by `Doc.view_only`. The spec sentence should be corrected by the orchestrator. The plan does not touch the spec.

## Global Constraints

- **No behaviour change.** For `tex` and `pdf` documents, the following stay exactly as they are: every HTTP status and body, every `pins.md` byte, every state-folder file, and every stdout line. Do not re-record `tests/data/contract_snapshot.json` or `tests/data/pin_records.jsonl`.
- **Do not rename anything in the index's §Shared contract.** The names are `DocKind`, `Doc.kind`, `builds_from_source`, `watches_files`, `takes_line_pins`, `shows_revisions` and `view_only`. `kind_builds_from_source` is the addition from Contract issue 1.
- Server runtime stays standard-library only (`dependencies = []`).
- **Language.** Code, comments, docstrings, test names and commit messages are in English. Handbook edits are in Korean, present tense, with no dates.
- **No personal data.** No real e-mails, home paths or host names (use `alice@example.com`, `/srv/paper`). `tests/test_naming.py` scans tracked *and* untracked files, so keep proof files outside the repository (see §Before you start).
- **Handbook references.** Never write a reference of the form `docs/handbook/<topic>.md §<heading>` to a heading that does not exist yet. `tests/test_handbook_refs.py` checks every tracked file under `src/`, `tests/` and `docs/`, this plan included. Code in this plan cites `docs/handbook/domain.md §여러 문서`, which exists.
- **Commits.** Use `git commit -s`, then put the line `I agree to the Limn CLA (CLA.md).` directly after `Signed-off-by:` with one amend. Every commit step shows the two commands. Do not put the CLA line into a message passed to `git commit -s`: git then appends a second sign-off after it.
- **Coding rules** (`docs/handbook/code-style-roadmap.md`):
  - **R1:** `kind_builds_from_source` and `doc_start_line` are pure. They take values and return values, and `print` stays in `server.prepare`.
  - **R3:** the kind is parsed once at the boundary (`parse_doc_arg` returns a `DocKind`), and inner code never compares suffixes or kind strings. Domain refusals keep their existing values (`ViewOnlyNoRebuild`, `InputRejected`) and their existing HTTP mapping; P0 adds no mapping.
  - **R5:** new functions read no module globals (`C.`, `cur_doc()`, `DOCS`). `test_meta.NoServerState` and `test_startup.ModuleBoundary` keep checking this.
  - **R7:** every touched function, method, property and protocol member has a docstring stating its contract. This includes private helpers and test doubles. The replacement code below carries these docstrings.
  - **R8:** `Doc.kind` and `DocSpec.kind` are `DocKind`. No bare `str` holds a kind.
  - **R9:** every new test name states the condition and the expectation, and every new test has a docstring. Run each new test red first. After green, invert the branch in the mutation step and watch a named test fail. New tests use `msg=` arguments, not `self.subTest`, so the subtest total stays equal for the differential proof.
  - **R10:** the kind boundary keeps its negative tests: `tests/test_startup.py` `DocArgs.test_rejects_bad_specs` covers `notes.txt`, and Task 1 adds a `.svg` refusal.
- The formatter owns layout. Before any `ruff format --check`, run `uv run ruff format` on the files the task touched. Wrapped lines in this plan's code may differ from the formatter's output.
- Gates for the PR, from `AGENTS.md`:
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

1. **An inverted branch that no test observes.** Before this plan, several branches could be inverted without a single test failing. Among them are the per-document startup line (`server.py:759`) and the `cur_pdf` fallback before the first render (`build.py:234`). Table A's "Pinned by" column names, for every site, the test that fails when the branch is inverted. Where no test did, the owning task adds one. Every task that moves a branch ends with a mutation step.
2. **A test double that still answers the retired flag.** A double may still answer `is_pdf` while production reads a capability. This fails silently wherever the double is only constructed and never read. Task 9's token guard fails on any identifier `is_pdf` under `src/limn` or `tests`.
3. **A kind string outside `DocKind` reaching `Doc` from untyped test code.** Tests are excluded from mypy. Such a document now answers every capability like a view-only PDF, where it used to answer like LaTeX. Task 1's table test requires one row per `DocKind` value, so a new kind cannot arrive without stated capabilities. Production code is typed.
4. **The per-document startup line that operators grep.** The bytes must stay `doc    <key padded to 10> LaTeX    <path>` and `... view-only <path>`, with or without `  (build started)`. Task 2 pins both lines byte for byte.
5. **One pins.md heading reads two capabilities.** The `보기 전용` label follows `view_only`. The `기준: … · 빌드|그림` stamp word follows `builds_from_source`. Collapsing them back into one flag would misname a future figure heading. Task 8 tests a heading that is neither view-only nor built from source.

---

## Site inventory and classification

This is the core of P0. Each site moves to the one capability its branch means, so that a future kind lands correctly: a figure document must never run latexmk, be pulled for, or get latexdiff. Line numbers are those of `main` at `5d1c4b6`. The "Pinned by" column names a test that fails when the branch is inverted. The column comes from a mutation probe on that commit: each branch was inverted in turn and the full suite was run.

Capabilities (index §Shared contract), for tex / pdf:

| Capability | tex | pdf | Meaning |
| --- | --- | --- | --- |
| `builds_from_source` | ✓ | | latexmk builds it; `--git-pull` rebuilds it; `POST /api/rebuild` runs; `stale_build` and the `.aux` outline apply; the fingerprint and `src_mtime` scan the source tree |
| `watches_files` | | ✓ | The watch thread re-renders its pages when its file changes; startup renders on a changed file |
| `takes_line_pins` | ✓ | | `file`/`lo`/`hi` pins with anchor re-sync; `doc_for_file` routes a file to it |
| `shows_revisions` | ✓ | | The changes view (Git history, latexdiff) |
| `view_only` | | ✓ | Region pins only; the API's `view_only`; always `not takes_line_pins` |

### Table A: production decision sites (29)

| # | Site | Today | Becomes | Capability | Why this one | Pinned by (fails when inverted) | Task |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `src/limn/server.py:759` | `"view-only" if D.is_pdf else "LaTeX   "` | `serve_documents.doc_start_line(D.key, D.kind, …)` | **kind** | The line names the kind itself; an exhaustive `match` makes mypy demand a label for every new kind | none before; new `DocStartLine` tests | 2 |
| 2 | `src/limn/documents.py:209` (`doc_for_file`) | `if d.is_pdf: continue` | `if not d.takes_line_pins: continue` | `takes_line_pins` | Routes a file-only request (agent curl) to a document whose pins are lines; the contract lists `doc_for_file` routing here | `test_meta.Lookups.test_doc_for_file_takes_the_deepest_latex_root`, `test_server.MultiDoc.test_pin_doc_is_inferred_from_file_and_body_query_must_agree` | 3 |
| 3 | `src/limn/documents.py:281` (`DocumentFacts`) | `return self._doc.is_pdf` | `return self._doc.view_only` | `view_only` | The parsers ask "are this document's pins regions?" | `test_server.MultiDoc.test_view_only_pin_save_validation_and_pins_md` and every line-pin add through the handler (e.g. `test_server.CrossOrigin.test_own_origin_and_curl_allowed`); new `DocumentFactsReads` test | 3 |
| 4 | `src/limn/build.py:234` (`cur_pdf`) | `if D.is_pdf: return D.main` | `if not D.builds_from_source: return D.main` | `builds_from_source` | Before any page copy, a built document's PDF is latexmk's output; a document nothing compiles *is* its file | none before; new `ReadsBeforeAndBetweenBuilds` test | 4 |
| 5 | `src/limn/build.py:275` (`migrate_pages`) | `if D.is_pdf: return` | `if not D.builds_from_source: return` | `builds_from_source` | The legacy `pages/` + `build/<main>.pdf` layout exists only for latexmk output | `test_build.Legacy.test_migrate_copies_pdf_next_to_pages` | 4 |
| 6 | `src/limn/build.py:550` (`doc_fingerprint`) | `if D.is_pdf:` hash main | `if not D.builds_from_source:` | `builds_from_source` | A built document is fingerprinted over its source tree; any other over its own file | `test_build.Outcomes.test_ok_when_a_fresh_pdf_and_synctex_come_out`, `test_locate.Estimate.test_seed_builds_fingerprints_current_build_when_source_unchanged`, `test_server.MultiDoc.test_view_only_pdf_renders_and_rerenders_on_change` | 4 |
| 7 | `src/limn/build.py:595` (`src_mtime`) | `if D.is_pdf:` main's mtime | `if not D.builds_from_source:` | `builds_from_source` | Same split: tree scan vs the one file | none before; new `ReadsBeforeAndBetweenBuilds` test | 4 |
| 8 | `src/limn/pins/render.py:418` | `", 보기 전용" if d.is_pdf` | `if d.view_only` | `view_only` | The header says its pins are regions | `test_pins_render.DocumentSections.test_multi_document_sections_in_configured_order`, `test_server.MultiDoc.test_view_only_pin_save_validation_and_pins_md` | 8 |
| 9 | `src/limn/pins/render.py:490` | `if d.is_pdf: title += " — 보기 전용 PDF(줄 번호 없음)"` | `if d.view_only:` | `view_only` | "No line numbers" is the absence of line pins | `test_pins_render.DocumentSections.test_multi_document_sections_in_configured_order`, `test_server.MultiDoc.test_view_only_pin_save_validation_and_pins_md` | 8 |
| 10 | `src/limn/pins/render.py:494` | `"그림" if d.is_pdf else "빌드"` | `"빌드" if d.builds_from_source else "그림"` | `builds_from_source` | The stamp says whether the pages came from a build or from a file read in; a future figure (line pins, no build) must still say `그림` | `test_pins_render.DocumentSections.test_multi_document_sections_in_configured_order` | 8 |
| 11 | `src/limn/features/builds/service.py:54` (`tracked`) | `render_pdf_doc if doc.is_pdf else compile` | `compile if doc.builds_from_source else render_pdf_doc` | `builds_from_source` | latexmk runs only for a document built from source | `test_build.AsyncBuild` (every test in the class) | 4 |
| 12 | `src/limn/features/builds/service.py:90` (`watch_pdf_docs`) | `if doc.is_pdf:` | `if doc.watches_files:` | `watches_files` | The watch thread's own membership test | none before; new `WatchMembership` test | 4 |
| 13 | `src/limn/features/builds/run.py:46` (`request_rebuild`) | `if D.is_pdf: ViewOnlyNoRebuild` | `if not D.builds_from_source:` | `builds_from_source` | `POST /api/rebuild` is for documents built from source (contract) | `test_build.RebuildRules.test_a_view_only_document_is_never_rebuilt_on_request`, `test_server.MultiDoc.test_view_only_rebuild_is_refused_and_pick_snippet_guarded`, `test_server.RebuildLogDiet` | 4 |
| 14 | `src/limn/features/builds/run.py:56` (`needs_build`) | `if D.is_pdf: pdf_changed …` | `if D.watches_files:` | `watches_files` | The branch body is the watch signature check; `--no-build` does not apply to a watched file | `test_build.RebuildRules.test_startup_builds_what_is_missing_or_changed` | 4 |
| 15 | `src/limn/features/builds/engine.py:352` (`refresh_pdf_doc`) | `if not D.is_pdf or …` | `if not D.watches_files or …` | `watches_files` | Re-render on file change is the watch's job | none before; new `WatchMembership` test | 4 |
| 16 | `src/limn/features/pins/location/input.py:80` (`parse_snippet`) | `if facts.is_pdf:` refuse | `if facts.view_only:` | `view_only` | A region-only document has no source lines to show | `test_web_parse.Locations.test_source_range_reads_the_file_before_the_numbers`, `test_server.MultiDoc.test_view_only_rebuild_is_refused_and_pick_snippet_guarded`, `test_security.DotPaths.test_a_viewer_cannot_read_a_dot_file_through_snippet_or_overlaps` | 3 |
| 17 | `src/limn/features/pins/location/resolve.py:148` (`pick`) | `if D.is_pdf: return _pick_region(…)` | `if D.view_only:` | `view_only` | The region answer is what a region-only document picks | `test_locate.PickOutcomes.test_a_traced_selection_carries_its_range_and_build_facts`, `test_server.MultiDoc.test_view_only_pick_returns_region_without_synctex` | 3 |
| 18 | `src/limn/features/pins/editing/input.py:44` (`parse_add`) | `if facts.is_pdf:` region | `if facts.view_only:` | `view_only` | A new pin is a region exactly when the document takes no line pins | `test_web_parse.Locations.test_region_add_on_a_view_only_document`, `test_web_parse.Locations.test_add_checks_the_location_before_the_note`, every line-pin add through the handler | 3 |
| 19 | `src/limn/features/pins/listing/markdown.py:93` | `DocHeading(…, d.is_pdf, …)` | `DocHeading(…, d.view_only, d.builds_from_source, …)` | carrier | No decision; it hands rows 8–10 their two values | `test_server.MultiDoc.test_view_only_pin_save_validation_and_pins_md` | 8 |
| 20 | `src/limn/features/document_views/reads.py:57` (`doc_brief`) | `(not D.is_pdf) and source_newer > 2` | `D.builds_from_source and …` | `builds_from_source` | `stale_build` means "the source is newer than the build" (contract) | none before; new `Meta.test_staleness_and_view_only_follow_the_document_capabilities` | 7 |
| 21 | `src/limn/features/document_views/reads.py:64` | `"view_only": D.is_pdf` | `"view_only": D.view_only` | `view_only` | The API field of the same name (contract) | `test_meta.Meta.test_several_documents_add_their_briefs_and_signature`, `test_server.MultiDoc.test_api_docs_lists_kind_and_counts` | 7 |
| 22 | `src/limn/features/document_views/reads.py:116` (`meta`) | `0.0 if D.is_pdf else source_newer` | `source_newer if D.builds_from_source else 0.0` | `builds_from_source` | Same `stale_build` rule on the light meta | `test_gitsync.GitPullBuildIntegration.test_edit_after_copy_phase_still_marks_stale` (LaTeX side only); new `Meta` test for both sides | 7 |
| 23 | `src/limn/features/document_views/reads.py:134` | `"view_only": D.is_pdf` | `"view_only": D.view_only` | `view_only` | The API field | only a browser test (`test_viewer_browser.ViewerRoleUi.test_editor_still_sees_them`); new `Meta` test | 7 |
| 24 | `src/limn/features/document_views/reads.py:168` (`outline_labels`) | `if D.is_pdf: return` | `if not D.builds_from_source: return` | `builds_from_source` | The outline reads the `.aux` a LaTeX build publishes | `test_meta.OutlineLabels.test_no_labels_for_a_view_only_document`, `test_meta.OutlineLabels.test_reads_the_aux_of_the_build_on_screen` | 7 |
| 25 | `src/limn/features/revisions/core.py:300` (`revision_scope`) | `if D.is_pdf: return None` | `if not D.shows_revisions: return None` | `shows_revisions` | The changes view's own gate (contract; P2 may extend) | LaTeX side: `test_revisions.ManuscriptRevisions.test_latest_revision_diff_is_real_and_scoped`; view-only side: none before, new `ManuscriptRevisions` test | 6 |
| 26 | `src/limn/features/sync/run.py:206` (`SyncWatch.status`) | `if not D.is_pdf` | `if D.builds_from_source` | `builds_from_source` | Only documents built from source are rebuilt after a pull | `test_gitsync.Watch.test_status_settles_when_every_document_reached_the_commit`, `test_gitsync.Watch.test_status_reports_a_failed_build`, `test_gitsync.AutomaticMainSync.test_failed_pdf_build_reports_error` | 5 |
| 27 | `src/limn/features/sync/run.py:232` (`SyncWatch.once`) | `[D … if not D.is_pdf]` | `[D … if D.builds_from_source]` | `builds_from_source` | `--git-pull` locks and rebuilds only those (contract) | `test_gitsync.Watch.test_fast_forward_rebuilds_every_latex_document`, `test_gitsync.Watch.test_up_to_date_rebuilds_only_the_document_behind`, `test_gitsync.AutomaticMainSync.test_new_head_schedules_each_tex_document_once` | 5 |
| 28 | `src/limn/features/administration/serve_documents.py:314` (`docs_of`) | `p["kind"] == "tex"` | `kind_builds_from_source(p["kind"])` | `builds_from_source` | The state-root layout continues a single LaTeX document's build history | `tests/test_startup.py` `DocArgs.test_make_docs_rejects_duplicate_keys_and_marks_main_root`; new `BuildsFromSourceAtStartup` test | 1 |
| 29 | `src/limn/features/administration/serve_documents.py:365` (`pick_documents`) | `d["kind"] != "pdf"` | `kind_builds_from_source(d["kind"])` | `builds_from_source` | The run's main file is "the main .tex": the first document built from source | `tests/test_startup.py` `Documents.test_main_is_the_first_latex_document_or_the_detected_one`; new `BuildsFromSourceAtStartup` test | 1 |

Tally: `builds_from_source` 14 (rows 4, 5, 6, 7, 10, 11, 13, 20, 22, 24, 26, 27, 28, 29); `view_only` 8 (3, 8, 9, 16, 17, 18, 21, 23); `watches_files` 3 (12, 14, 15); `takes_line_pins` 1 (2); `shows_revisions` 1 (25); kind 1 (1); carrier 1 (19).

### Table B: declarations of the flag (8), all removed

| Site | Today | Becomes | Task |
| --- | --- | --- | --- |
| `src/limn/documents.py:158-161` | `Doc.is_pdf` | deleted; the five capabilities from Task 1 | 9 |
| `src/limn/documents.py:278-281` | `DocumentFacts.is_pdf` | `DocumentFacts.view_only` | 3 |
| `src/limn/web/parse.py:41-44` | protocol `DocumentFacts.is_pdf` | `view_only` | 3 |
| `src/limn/build.py:113-115` | protocol `BuildDoc.is_pdf` | `builds_from_source`, `watches_files` | 4 |
| `src/limn/features/builds/run.py:33-35` | protocol `Rebuildable.is_pdf` | `builds_from_source` | 4 |
| `src/limn/features/sync/run.py:60-63` | protocol `SyncDoc.is_pdf` | `builds_from_source` | 5 |
| `src/limn/features/revisions/core.py:77-80` | protocol `RevisionDoc.is_pdf` | `shows_revisions` | 6 |
| `src/limn/pins/render.py:32` | field `DocHeading.is_pdf` | fields `view_only`, `builds_from_source` | 8 |

### Table C: kind reads that stay, and the kind boundary

| Site | What it is | P0 |
| --- | --- | --- |
| `src/limn/documents.py:72,86,101` | `Doc` docstring, `kind` parameter, attribute | typed `DocKind` (Task 1) |
| `src/limn/documents.py:329` (`document_authority_target`) | `doc.kind` in a document's identity snapshot | keeps `kind`: it reports identity |
| `src/limn/features/document_views/reads.py:63,133` | `"kind": D.kind` in `/api/docs`, `/api/meta` | keeps `kind`: the API reports the kind |
| `src/limn/features/administration/serve_documents.py:17,21` | `DocSpec` docstring and `kind: str` | `kind: DocKind` (Task 1) |
| `src/limn/features/administration/serve_documents.py:238-245` (`parse_doc_arg`) | suffix → kind, the one parse of the kind | annotated `kind: DocKind` (Task 1); the rule is unchanged |
| `src/limn/features/pins/location/http.py:159` | `"view_only": True` in the region pick body | a constant of the region answer, not a document branch; unchanged |

### Table D: test doubles and tests carrying the flag

| Site | Today | Becomes | Task |
| --- | --- | --- | --- |
| `tests/test_web_parse.py:46,48` (`Facts`) | `is_pdf` parameter and attribute | `view_only` | 3 |
| `tests/test_web_parse.py:550,585,681` | `Facts(…, is_pdf=True…)` | `view_only=True` | 3 |
| `src/limn/features/document_views/test_meta.py:302` | `facts.is_pdf` | `facts.view_only` | 3 |
| `tests/test_build.py:86` (`PlainDoc`) | field `is_pdf: bool = False` | fields `builds_from_source: bool = True`, `watches_files: bool = False` | 4 |
| `tests/test_build.py:371,709` | `PlainDoc(…, is_pdf=True)` | `builds_from_source=False, watches_files=True` | 4 |
| `tests/test_build.py:712` | `D.key = "rv" if D.is_pdf else "ms"` | `"ms" if D.builds_from_source else "rv"` | 4 |
| `src/limn/features/sync/test_gitsync.py:284,286,303` (`FakeDoc`) | `is_pdf` parameter and attribute | `builds_from_source` | 5 |
| `tests/test_gitrun.py:229` | `SimpleNamespace(is_pdf=False, …)` | `shows_revisions=True` | 6 |
| `tests/test_pins_render.py:48,285,286,309,334` | `DocHeading(…, False/True, …)` positional | keyword `view_only=…, builds_from_source=…` | 8 |

Tests that assert the kind *value* (`tests/test_startup.py:683,698,703,807`, `tests/test_server.py:1190,1200,1283`) observe the contract. They stay as they are.

### Table E: viewer (reads the API; no change in P0)

The viewer never reads the document `kind`. It reads `view_only` from `/api/meta` (`META.view_only`) and `/api/docs` (`d.view_only`):

| Site | Use | Intent | Note for P1c |
| --- | --- | --- | --- |
| `src/limn/viewer/js/boot.js:59` | `body.view-only` class, which hides `#btn-rebuild` through `src/limn/viewer/css/responsive.css:245` | builds_from_source | After P1b, a figure document is `view_only:false`, so the rebuild button shows (its `POST` answers `400`). The index says P1c switches the rebuild UI to `kind === "tex"`. |
| `src/limn/viewer/js/build-chip.js:60` | Toast `PDF가 바뀌어 쪽을 새로 그렸습니다` vs `PDF 재빌드 완료` | builds_from_source | Same: switch to `kind` in P1c |
| `src/limn/viewer/js/polling.js:63` | The same toast for another document | builds_from_source | Same |
| `src/limn/viewer/js/doc-tabs.js:21` | `PDF` badge, `aria-label="보기 전용"` | view_only | Fine through P1b; P1c adds the `그림` badge by `kind` |
| `src/limn/viewer/js/doc-tabs.js:22` | Tab tooltip `보기 전용 PDF(줄 번호 없이 …)` | view_only | Same |

The composer's region layout (`#composer.region`) follows the pick answer's shape (`isRegion`, `doc-tabs.js:5`), not the document.

### Table F: shell mirror (no change in P0)

| Site | Rule | Note |
| --- | --- | --- |
| `src/limn/features/administration/instance_documents.sh:54-57` | `::` form accepts only `tex` | Mirrors `DocExtendedNotTex`. P1a lets `::` take `.limnmap.json`, changed together with `parse_doc_arg`. |
| `src/limn/features/administration/instance_documents.sh:60-63` | Plain path accepts `tex` or `pdf` | Mirrors `DocKindUnknown`. P1a adds the map suffix. |
| `src/limn/instances.sh` | No kind or suffix rule | Nothing to do |

---

## File Structure

| File | Change | Responsibility after P0 |
| --- | --- | --- |
| `src/limn/documents.py` | Modify | `DocKind`, `kind_builds_from_source`, `Doc` capabilities, `doc_for_file` on `takes_line_pins`, `DocumentFacts.view_only` |
| `src/limn/features/administration/serve_documents.py` | Modify | `DocSpec.kind: DocKind`; startup decisions on `kind_builds_from_source`; pure `doc_start_line` |
| `src/limn/features/administration/test_serve_documents.py` | Create | Colocated tests: kind from suffix, startup build-from-source decisions, startup line bytes |
| `src/limn/server.py` | Modify | `prepare` prints `doc_start_line(...)` |
| `src/limn/web/parse.py` | Modify | Protocol `DocumentFacts.view_only` |
| `src/limn/features/pins/editing/input.py`, `src/limn/features/pins/location/input.py`, `src/limn/features/pins/location/resolve.py` | Modify | Branch on `view_only` |
| `src/limn/build.py` | Modify | `BuildDoc` capabilities; four branches on `builds_from_source` |
| `src/limn/features/builds/run.py`, `service.py`, `engine.py` | Modify | `Rebuildable.builds_from_source`; branches on `builds_from_source` / `watches_files` |
| `src/limn/features/builds/test_watch.py` | Create | Colocated test: one watch round re-renders only the watched, changed document |
| `src/limn/features/sync/run.py` | Modify | `SyncDoc.builds_from_source` |
| `src/limn/features/revisions/core.py` | Modify | `RevisionDoc.shows_revisions` |
| `src/limn/features/document_views/reads.py` | Modify | `stale_build`/outline on `builds_from_source`; API `view_only` from `Doc.view_only` |
| `src/limn/pins/render.py`, `src/limn/features/pins/listing/markdown.py` | Modify | `DocHeading.view_only` and `.builds_from_source` |
| Tests: `src/limn/features/document_views/test_meta.py`, `tests/test_web_parse.py`, `tests/test_build.py`, `src/limn/features/sync/test_gitsync.py`, `tests/test_gitrun.py`, `src/limn/features/revisions/test_revisions.py`, `tests/test_pins_render.py` | Modify | Doubles speak capabilities; new characterization tests |
| `docs/handbook/domain.md`, `docs/handbook/index.md`, `docs/handbook/verification.md`, `CHANGELOG.md` | Modify | Kinds and capabilities in present tense; file map; test placement; internal changelog line |

The capability-table test lives in `src/limn/features/document_views/test_meta.py`. That is where `Doc`, `DocumentFacts` and the document lookups are tested today (`Lookups`, `DocumentFactsReads`, `ToSource`).

---

## Before you start: record the before oracle

Do this once, on the commit P0 starts from, before any edit. This is step 1 of `docs/handbook/verification.md §구조 이동의 동작 불변 증명(차등 비교)`.

- [ ] **Step 1: Make a clean worktree branch and a proof folder outside the repository**

```bash
git fetch origin --prune
git switch -c refactor/document-capabilities origin/main
git status --short
export P0_PROOF="${TMPDIR:-/tmp}/limn-p0-proof"
mkdir -p "$P0_PROOF"
git rev-parse HEAD > "$P0_PROOF/base.txt"
```

Expected: `git status --short` prints nothing. `$P0_PROOF/base.txt` holds one 40-character hash.

- [ ] **Step 2: Run the whole suite once with both machine-readable outputs**

```bash
uv sync --group dev
uv run pytest -q -rA -n 4 --dist loadscope --junitxml="$P0_PROOF/before.xml" > "$P0_PROOF/before-rA.txt" 2>&1; tail -n 1 "$P0_PROOF/before-rA.txt"
uv run pytest --collect-only -q -p no:cacheprovider > "$P0_PROOF/before-ids.txt"; tail -n 1 "$P0_PROOF/before-ids.txt"
```

Collect the ids now, from this checkout. Do not use `tools/test_id_map.py --ref` at the end. `--ref` collects the old tests in a temporary worktree, and if an environment variable points that run at the new sources, old tests import new code and fail to collect.

Expected:
- `before-rA.txt` ends with one summary line of the form `N passed, S skipped, T subtests passed in …s`, with no `failed` and no `error`.
- `before-ids.txt` ends with `N+S tests collected`.

On the machine that wrote this plan it read `2038 passed, 1 skipped, 1046 subtests passed` and `2039 tests collected`. Your counts may differ with the installed TeX tools. Record your own numbers, because the proof compares against them.

- [ ] **Step 3: Keep the list of added tests next to the oracle**

```bash
cat > "$P0_PROOF/p0-map.txt" <<'EOF'
# Tests P0 adds; every other test id must be unchanged (tools/test_id_map.py).
+ Capabilities::test_each_kind_has_exactly_the_capabilities_of_its_table_row
+ Capabilities::test_the_table_has_a_row_for_every_document_kind
+ Capabilities::test_view_only_is_the_absence_of_line_pins_for_every_kind
+ Capabilities::test_the_kind_level_build_rule_agrees_with_the_document_property
+ Capabilities::test_the_single_legacy_document_is_a_latex_document
+ DocumentKindFromPath::test_tex_and_pdf_suffixes_name_their_kinds_in_any_case
+ DocumentKindFromPath::test_an_svg_is_not_a_document_kind
+ BuildsFromSourceAtStartup::test_a_view_only_document_keyed_main_does_not_take_the_state_root
+ BuildsFromSourceAtStartup::test_the_run_main_skips_view_only_documents_listed_first
+ DocStartLine::test_a_latex_document_with_a_started_build_reads_latex
+ DocStartLine::test_a_view_only_document_without_a_build_reads_view_only
+ DocumentFactsReads::test_view_only_is_the_document_capability
+ ReadsBeforeAndBetweenBuilds::test_a_document_built_from_source_reads_latexmk_output_and_any_other_its_own_file
+ ReadsBeforeAndBetweenBuilds::test_src_mtime_scans_the_tree_only_for_a_document_built_from_source
+ WatchMembership::test_one_round_starts_a_render_for_the_changed_watched_pdf_only
+ ManuscriptRevisions::test_a_view_only_document_has_no_history_even_beside_committed_sources
+ Meta::test_staleness_and_view_only_follow_the_document_capabilities
+ DocumentSections::test_stamp_word_follows_builds_from_source_and_label_follows_view_only
+ RetiredKindFlag::test_no_python_identifier_in_the_package_or_the_tests_is_the_retired_flag
+ RetiredKindFlag::test_documents_and_their_facts_have_no_attribute_of_that_name
EOF
```

Expected: the file exists. It lists every test the tasks below add. If you add any other test, append a `+ Class::test` line for it here, with its reason in the PR.

---

### Task 1: `DocKind`, the kind-level build rule, and the capability properties

**Files:**
- Modify: `src/limn/documents.py:16-34` (imports, constants), `:71-111` (`Doc` docstring and `__init__`), insert after `:156` (`pdf_name`)
- Modify: `src/limn/features/administration/serve_documents.py:10`, `:16-23`, `:238-245`, `:304-318`, `:343-366`
- Test: `src/limn/features/document_views/test_meta.py` (new class `Capabilities`)
- Create: `src/limn/features/administration/test_serve_documents.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (every later task uses these exact names):
  - `limn.documents.DocKind: TypeAlias = Literal["tex", "pdf"]`
  - `limn.documents.kind_builds_from_source(kind: DocKind) -> bool`
  - `Doc.kind: DocKind`, and the properties `Doc.builds_from_source`, `Doc.watches_files`, `Doc.takes_line_pins`, `Doc.shows_revisions`, `Doc.view_only`, each typed `-> bool`
  - `serve_documents.DocSpec["kind"]: DocKind`
  - `Doc.is_pdf` still exists until Task 9. Do not use it in new code.

- [ ] **Step 1: Write the failing capability-table test**

In `src/limn/features/document_views/test_meta.py`, change the imports:

```python
import ast
import json
import os
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from limn import build as limn_build, documents
from limn.access import LOCAL_ACTOR
from limn.documents import Doc, DocKind, DocNotFound, kind_builds_from_source
```

After the `LIGHT_KEYS` list, add:

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
    },
    "pdf": {
        "builds_from_source": False,
        "watches_files": True,
        "takes_line_pins": False,
        "shows_revisions": False,
        "view_only": True,
    },
}
```

After the `Fixture` class, add:

```python
class Capabilities(Fixture):
    """What each document kind can do (docs/handbook/domain.md §여러 문서): branches read these, never the kind."""

    def doc_of(self, kind: DocKind) -> Doc:
        """A --doc document of this kind over the fixture's tree (its files need not exist to answer capabilities)."""
        return Doc("k", "이름", kind, self.src, self.src / "main.tex", paths=self.paths)

    def test_each_kind_has_exactly_the_capabilities_of_its_table_row(self):
        """A LaTeX document builds from source, takes line pins and shows revisions; a view-only PDF is watched and
        view-only - and nothing else."""
        for kind, row in CAPABILITY_TABLE.items():
            doc = self.doc_of(kind)
            self.assertEqual({name: getattr(doc, name) for name in row}, row, msg=kind)

    def test_the_table_has_a_row_for_every_document_kind(self):
        """Adding a value to DocKind fails here until its row is written, so no branch has to guess a new kind."""
        self.assertEqual(sorted(get_args(DocKind)), sorted(CAPABILITY_TABLE))

    def test_view_only_is_the_absence_of_line_pins_for_every_kind(self):
        """view_only is derived, never stated: True exactly when the kind takes no line pins."""
        for kind in get_args(DocKind):
            doc = self.doc_of(kind)
            self.assertIs(doc.view_only, not doc.takes_line_pins, msg=kind)

    def test_the_kind_level_build_rule_agrees_with_the_document_property(self):
        """kind_builds_from_source, used on a parsed --doc before its Doc exists, answers what Doc.builds_from_source
        answers for every kind."""
        for kind in get_args(DocKind):
            self.assertIs(kind_builds_from_source(kind), self.doc_of(kind).builds_from_source, msg=kind)

    def test_the_single_legacy_document_is_a_latex_document(self):
        """An instance started without --doc serves one document of kind tex with the LaTeX row's capabilities."""
        self.assertEqual(self.legacy.kind, "tex")
        row = CAPABILITY_TABLE["tex"]
        self.assertEqual({name: getattr(self.legacy, name) for name in row}, row)
```

- [ ] **Step 2: Write the colocated startup tests**

Create `src/limn/features/administration/test_serve_documents.py`:

```python
"""Startup document selection (limn.features.administration.serve_documents) as it depends on document kinds.

Which kind a --doc path names, and the two startup decisions made on a parsed --doc before any Doc exists - whether
a document keyed main keeps the state-folder root, and which document's main file is the run's - follow
limn.documents.kind_builds_from_source, never a kind name. Every suffix other than .tex and .pdf is refused at this
boundary (docs/handbook/code-style-roadmap.md §R10); tests/test_startup.py DocArgs pins the full refusal list and
its messages.

Run: uv run pytest -q src/limn/features/administration/test_serve_documents.py
"""

import tempfile
import unittest
from pathlib import Path

from limn.documents import RunPaths
from limn.features.administration import serve_documents
from limn.features.administration.serve_documents import DocKindUnknown, RunDocuments

TEX = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
PDF = b"%PDF-1.4\n"


class StartupTree(unittest.TestCase):
    """A manuscript with a LaTeX body, a lower-case .pdf, an upper-case .PDF and an SVG, and a state folder beside it."""

    def setUp(self):
        """Temporary manuscript and state folders; the manuscript path is resolved as pick_documents expects."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.ms = root / "repo"
        (self.ms / "sub").mkdir(parents=True)
        (self.ms / "main.tex").write_text(TEX, encoding="utf-8")
        (self.ms / "sub" / "review.pdf").write_bytes(PDF)
        (self.ms / "sub" / "SCAN.PDF").write_bytes(PDF)
        (self.ms / "sub" / "figure.svg").write_text("<svg/>", encoding="utf-8")
        self.paths = RunPaths(self.ms, self.ms / "main.tex", root / "state")


class DocumentKindFromPath(StartupTree):
    """parse_doc_arg reads the kind from the path's suffix, case-insensitively, and refuses every other suffix."""

    def test_tex_and_pdf_suffixes_name_their_kinds_in_any_case(self):
        """main.tex is tex; review.pdf and SCAN.PDF are pdf - the suffix is compared lower-cased."""
        specs = ("ms=본문:main.tex", "rv=리뷰:sub/review.pdf", "sc=스캔:sub/SCAN.PDF")
        got = [serve_documents.parse_doc_arg(spec, self.ms) for spec in specs]
        self.assertEqual([d["kind"] for d in got], ["tex", "pdf", "pdf"])

    def test_an_svg_is_not_a_document_kind(self):
        """A vector graphic file on its own is refused with its resolved path; the server never serves SVG."""
        self.assertEqual(
            serve_documents.parse_doc_arg("fg=그림:sub/figure.svg", self.ms),
            DocKindUnknown("fg", self.ms / "sub" / "figure.svg"),
        )


class BuildsFromSourceAtStartup(StartupTree):
    """The two startup decisions on parsed --doc values ask whether the kind builds from source."""

    def test_a_view_only_document_keyed_main_does_not_take_the_state_root(self):
        """Only a document built from source keyed main inherits the single-document layout at the state-folder root;
        a view-only PDF keyed main keeps its own docs/main folder."""
        docs = serve_documents.make_docs(["main=리뷰:sub/review.pdf", "ms=본문:main.tex"], self.ms, self.paths)
        self.assertIsInstance(docs, list)
        self.assertEqual([(d.key, d.kind, d.root) for d in docs], [("main", "pdf", False), ("ms", "tex", False)])
        self.assertEqual(docs[0].dir, self.paths.state / "docs" / "main")

    def test_the_run_main_skips_view_only_documents_listed_first(self):
        """The run's main file is the first document that builds from source, even behind two view-only PDFs."""
        got = serve_documents.pick_documents(
            self.ms, ["rv=리뷰:sub/review.pdf", "sc=스캔:sub/SCAN.PDF", "ms=본문:main.tex"], None
        )
        self.assertIsInstance(got, RunDocuments)
        self.assertEqual(got.main, self.ms / "main.tex")
```

- [ ] **Step 3: Run the new tests and watch the capability table fail**

Run: `uv run pytest -q src/limn/features/document_views/test_meta.py src/limn/features/administration/test_serve_documents.py`

Expected:
- `test_meta.py` fails to collect with `ImportError: cannot import name 'DocKind' from 'limn.documents'`.
- The four `test_serve_documents.py` tests pass. They characterize today's behaviour; their red comes from the mutation in Step 7.

- [ ] **Step 4: Add `DocKind`, `kind_builds_from_source` and the capabilities to `documents.py`**

In `src/limn/documents.py`, replace `from typing import Any` with:

```python
from typing import Any, Literal, TypeAlias
```

After `DEFAULT_DOC_KEY = "main"`, add:

```python
# What a document is, read once from a --doc path's suffix (limn.features.administration.serve_documents.parse_doc_arg);
# an instance started without --doc serves one "tex" document. Branches ask a capability of Doc - builds_from_source,
# watches_files, takes_line_pins, shows_revisions, view_only - never the kind. Only what reports the kind itself reads
# it: the API's kind, a document's authority identity, the startup line (docs/handbook/domain.md §여러 문서).
DocKind: TypeAlias = Literal["tex", "pdf"]


def kind_builds_from_source(kind: DocKind) -> bool:
    """Whether documents of `kind` are built from their source by latexmk - "tex" only.

    The one rule behind Doc.builds_from_source, for the startup decisions made on a parsed --doc
    (serve_documents.DocSpec) before its Doc exists."""
    return kind == "tex"
```

Replace the first line of the `Doc` docstring:

```python
    """One document. kind is 'tex' (LaTeX, lines traced back via SyncTeX) or 'pdf' (view-only - page/region only).
```

with:

```python
    """One document of a kind (DocKind): 'tex' is LaTeX, lines traced back via SyncTeX; 'pdf' is a view-only PDF,
    pinned by page and region. What it can do is read from its capability properties (builds_from_source,
    watches_files, takes_line_pins, shows_revisions, view_only), never from kind.
```

In `Doc.__init__`, replace `kind: str = "tex",` with `kind: DocKind = "tex",`.

After the `pdf_name` property (keep `is_pdf` below it for now), add:

```python
    @property
    def builds_from_source(self) -> bool:
        """latexmk builds it from its source tree: startup and POST /api/rebuild compile it, --git-pull rebuilds it,
        stale_build and the .aux outline apply, and its fingerprint and src_mtime scan the tree. False: its pages come
        from a file Limn only reads."""
        return kind_builds_from_source(self.kind)

    @property
    def watches_files(self) -> bool:
        """The view-only watch thread re-renders its pages when its file changes, and startup renders them when the
        file changed since the last render (--no-build or not)."""
        return self.kind == "pdf"

    @property
    def takes_line_pins(self) -> bool:
        """Its pins are file/lo/hi line ranges with anchor re-sync, and a request that names only a file can route to
        it (doc_for_file)."""
        return self.kind == "tex"

    @property
    def shows_revisions(self) -> bool:
        """The changes view is available: the Git history of its manuscript files and the latexdiff comparison."""
        return self.kind == "tex"

    @property
    def view_only(self) -> bool:
        """Its pins are page regions only - the API's view_only. Exactly the absence of line pins."""
        return not self.takes_line_pins
```

- [ ] **Step 5: Type `DocSpec.kind` and move the two startup decisions to `kind_builds_from_source`**

In `src/limn/features/administration/serve_documents.py`, replace the `limn.documents` import with:

```python
from limn.documents import (
    DEFAULT_DOC_KEY,
    DOC_KEY_RE,
    DOC_NAME_MAX,
    DOCS_MAX,
    Doc,
    DocKind,
    RunPaths,
    kind_builds_from_source,
)
```

Replace the `DocSpec` class with:

```python
class DocSpec(TypedDict):
    """One parsed --doc: key, display name, kind (the DocKind its path's suffix names), build root (src) and main
    file, both resolved."""

    key: str
    name: str
    kind: DocKind
    src: Path
    main: Path
```

In `parse_doc_arg`, replace:

```python
    suf = main.suffix.lower()
    if suf == ".tex":
        kind = "tex"
```

with:

```python
    suf = main.suffix.lower()
    kind: DocKind
    if suf == ".tex":
        kind = "tex"
```

Replace `docs_of` with:

```python
def docs_of(specs: Sequence[DocSpec], paths: RunPaths) -> list[Doc]:
    """The documents of parsed --doc specs over the run's paths (the frozen value the composition root made once the
    state folder was known). A document keyed main whose kind builds from source (kind_builds_from_source) uses the
    state-folder-root layout (root), so it continues a single-document instance's build history."""
    return [
        Doc(
            p["key"],
            p["name"],
            p["kind"],
            src=p["src"],
            main=p["main"],
            root=(p["key"] == DEFAULT_DOC_KEY and kind_builds_from_source(p["kind"])),
            paths=paths,
        )
        for p in specs
    ]
```

Replace the `RunDocuments` docstring with:

```python
    """What the command line serves: the parsed --doc documents (None without --doc: the single document of --main) and
    the main .tex of the run (the first --doc document whose kind builds from source, else the first document's; else
    --main's or the detected one). The documents are made over the run's paths (docs_of) once the state folder is
    known."""
```

In `pick_documents`, replace:

```python
        first_tex = next((d for d in docs if d["kind"] != "pdf"), docs[0])
        return RunDocuments(docs, first_tex["main"])
```

with:

```python
        first_built = next((d for d in docs if kind_builds_from_source(d["kind"])), docs[0])
        return RunDocuments(docs, first_built["main"])
```

Append this sentence to the end of the `pick_documents` docstring: `The run's main file is the first --doc document whose kind builds from source, else the first document's.`

- [ ] **Step 6: Run the tests and the type check**

Run: `uv run pytest -q src/limn/features/document_views/test_meta.py src/limn/features/administration/test_serve_documents.py tests/test_startup.py && uv run mypy && uv run ruff check && uv run ruff format --check`

Expected: all pass. `mypy` prints `Success: no issues found`.

- [ ] **Step 7: Mutation check. Invert the build rule and watch the startup tests fail, then restore**

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/documents.py 'return kind == "tex"' 'return kind != "tex"'
uv run pytest -q src/limn/features/administration/test_serve_documents.py tests/test_startup.py -k "main or state_root"
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/documents.py 'return kind != "tex"' 'return kind == "tex"'
git diff --stat
```

Expected: the middle command fails 4 tests:
- `BuildsFromSourceAtStartup::test_a_view_only_document_keyed_main_does_not_take_the_state_root`
- `BuildsFromSourceAtStartup::test_the_run_main_skips_view_only_documents_listed_first`
- `DocArgs::test_make_docs_rejects_duplicate_keys_and_marks_main_root`
- `Documents::test_main_is_the_first_latex_document_or_the_detected_one`

After the restore, `git diff --stat` lists only this task's four files.

- [ ] **Step 8: Commit**

```bash
git add src/limn/documents.py src/limn/features/administration/serve_documents.py src/limn/features/document_views/test_meta.py src/limn/features/administration/test_serve_documents.py
git commit -s -m "refactor(documents): add DocKind and document capabilities" -m "Doc.kind is the closed type DocKind and five capability properties answer what a document can do. The two startup decisions on a parsed --doc read kind_builds_from_source instead of kind strings. No behaviour change."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
git log -1 --format=%B | tail -n 2
```

Expected: the last two lines are `Signed-off-by: <you>` and `I agree to the Limn CLA (CLA.md).`

---

### Task 2: The per-document startup line reports the kind through an exhaustive match

**Files:**
- Modify: `src/limn/features/administration/serve_documents.py` (add `doc_start_line` after `make_docs`)
- Modify: `src/limn/server.py:753-763`
- Test: `src/limn/features/administration/test_serve_documents.py` (new class `DocStartLine`)

**Interfaces:**
- Consumes: `DocKind` (Task 1).
- Produces: `serve_documents.doc_start_line(key: str, kind: DocKind, path: str, build_started: bool) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `src/limn/features/administration/test_serve_documents.py`:

```python
class DocStartLine(unittest.TestCase):
    """doc_start_line is the stdout line server.prepare prints per --doc document, byte for byte as operators see it."""

    def test_a_latex_document_with_a_started_build_reads_latex(self):
        """tex prints 'LaTeX' and three spaces after the key padded to ten, then the path and the build note."""
        self.assertEqual(
            serve_documents.doc_start_line("ms", "tex", "main.tex", True),
            "doc    ms         LaTeX    main.tex  (build started)",
        )

    def test_a_view_only_document_without_a_build_reads_view_only(self):
        """pdf prints 'view-only'; a document whose startup build was skipped carries no note."""
        self.assertEqual(
            serve_documents.doc_start_line("rv", "pdf", "sub/review.pdf", False),
            "doc    rv         view-only sub/review.pdf",
        )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest -q src/limn/features/administration/test_serve_documents.py -k DocStartLine`

Expected: 2 failed, `AttributeError: module 'limn.features.administration.serve_documents' has no attribute 'doc_start_line'`.

- [ ] **Step 3: Add `doc_start_line`**

In `src/limn/features/administration/serve_documents.py`, after `make_docs`, add:

```python
def doc_start_line(key: str, kind: DocKind, path: str, build_started: bool) -> str:
    """The startup line naming one --doc document: its key padded to ten, its kind's label, its path relative to
    --manuscript and, when startup began its build, "  (build started)". The label is chosen by an exhaustive match on
    kind, so a new DocKind fails the type check until it has a label (mypy exhaustive-match)."""
    match kind:
        case "tex":
            label = "LaTeX   "
        case "pdf":
            label = "view-only"
    return "doc    %-10s %s %s%s" % (key, label, path, "  (build started)" if build_started else "")
```

- [ ] **Step 4: Print it from `server.prepare`**

In `src/limn/server.py`, replace:

```python
            for D in self.docs:
                r = self.build_requests.init_doc(D, no_build, wait=False)
                print(
                    "doc    %-10s %s %s%s"
                    % (
                        D.key,
                        "view-only" if D.is_pdf else "LaTeX   ",
                        D.rel_path(),
                        "" if isinstance(r, BuildSkipped) else "  (build started)",
                    )
                )
```

with:

```python
            for D in self.docs:
                r = self.build_requests.init_doc(D, no_build, wait=False)
                print(startup_documents.doc_start_line(D.key, D.kind, D.rel_path(), not isinstance(r, BuildSkipped)))
```

`server.py` already imports the module as `startup_documents` (see `configure_run`). `prepare`'s docstring is unchanged and stays accurate.

- [ ] **Step 5: Run the tests, the type check and the style gates**

Run: `uv run pytest -q src/limn/features/administration/test_serve_documents.py tests/test_startup.py tests/test_server.py && uv run mypy && uv run ruff check && uv run ruff format --check`

Expected: all pass.

- [ ] **Step 6: Mutation check. Swap the labels and watch both tests fail, then restore**

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/administration/serve_documents.py 'label = "LaTeX   "' 'label = "view-only"'
uv run pytest -q src/limn/features/administration/test_serve_documents.py -k DocStartLine
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/administration/serve_documents.py 'case "tex":
            label = "view-only"' 'case "tex":
            label = "LaTeX   "'
uv run pytest -q src/limn/features/administration/test_serve_documents.py -k DocStartLine
```

Expected: the first run fails `test_a_latex_document_with_a_started_build_reads_latex`; the second passes.

- [ ] **Step 7: Commit**

```bash
git add src/limn/features/administration/serve_documents.py src/limn/server.py src/limn/features/administration/test_serve_documents.py
git commit -s -m "refactor(startup): name a document's kind in one exhaustive match" -m "server.prepare prints serve_documents.doc_start_line, which picks the kind's label by an exhaustive match, so a new DocKind cannot start without one. Same bytes as before."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 3: Pick and pin input read `view_only`; file routing reads `takes_line_pins`

**Files:**
- Modify: `src/limn/documents.py:198-218` (`doc_for_file`), `:278-281` (`DocumentFacts.is_pdf`)
- Modify: `src/limn/web/parse.py:41-44`
- Modify: `src/limn/features/pins/editing/input.py:36-45`
- Modify: `src/limn/features/pins/location/input.py:78-82`
- Modify: `src/limn/features/pins/location/resolve.py:131-149`
- Test: `tests/test_web_parse.py:43-50,550,585,681`; `src/limn/features/document_views/test_meta.py:281-303`

**Interfaces:**
- Consumes: `Doc.takes_line_pins`, `Doc.view_only` (Task 1).
- Produces: `DocumentFacts.view_only -> bool` (protocol in `limn.web.parse`, implementation in `limn.documents`). `DocumentFacts.is_pdf` no longer exists after this task.

- [ ] **Step 1: Switch the test double and the facts test to `view_only`, and add a facts test**

In `tests/test_web_parse.py`, replace the `Facts.__init__` head:

```python
    def __init__(self, root: Path, is_pdf: bool = False, pages: dict | None = None, current: str = "pages"):
        """root is the tree; pages maps a build name to its page sizes; current names the build on screen."""
        self.key, self.is_pdf, self.root, self.state = "rev" if is_pdf else "main", is_pdf, root, NO_STATE
```

with:

```python
    def __init__(self, root: Path, view_only: bool = False, pages: dict | None = None, current: str = "pages"):
        """root is the tree; view_only says the document's pins are regions (DocumentFacts.view_only); pages maps a
        build name to its page sizes; current names the build on screen."""
        self.key, self.view_only, self.root, self.state = "rev" if view_only else "main", view_only, root, NO_STATE
```

In the same file, replace these three calls:
- line 550: `Facts(self.root, is_pdf=True)` → `Facts(self.root, view_only=True)`
- line 585: `Facts(self.root, is_pdf=True, pages=` → `Facts(self.root, view_only=True, pages=`
- line 681: `Facts(self.root, is_pdf=True)` → `Facts(self.root, view_only=True)`

In `src/limn/features/document_views/test_meta.py`, in `DocumentFactsReads.test_pages_of_the_build_on_screen_or_a_named_one`, replace:

```python
            (facts.key, facts.is_pdf, facts.root, facts.pdf), ("ms", False, self.src, self.src / "main.tex")
```

with:

```python
            (facts.key, facts.view_only, facts.root, facts.pdf), ("ms", False, self.src, self.src / "main.tex")
```

Add to `DocumentFactsReads`:

```python
    def test_view_only_is_the_document_capability(self):
        """A view-only PDF's facts are view_only and a LaTeX document's are not: the pin parsers branch on this alone."""
        self.assertEqual(
            [documents.DocumentFacts(D, self.src, self.state, 150).view_only for D in (self.ms, self.rv)], [False, True]
        )
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest -q tests/test_web_parse.py src/limn/features/document_views/test_meta.py -k "region or snippet or DocumentFactsReads"`

Expected:
- `DocumentFactsReads` fails with `AttributeError: 'DocumentFacts' object has no attribute 'view_only'`.
- The region tests in `test_web_parse.py` fail with `AttributeError: 'Facts' object has no attribute 'is_pdf'`.

- [ ] **Step 3: Replace the facts property, its protocol, and the routing branch**

In `src/limn/web/parse.py`, replace:

```python
    @property
    def is_pdf(self) -> bool:
        """True for a view-only PDF document: its pins are regions, it has no source lines."""
        ...
```

with:

```python
    @property
    def view_only(self) -> bool:
        """True when the document's pins are page regions only (limn.documents.Doc.view_only): it has no source
        lines."""
        ...
```

In `src/limn/documents.py` (`DocumentFacts`), replace:

```python
    @property
    def is_pdf(self) -> bool:
        """True for a view-only PDF document."""
        return self._doc.is_pdf
```

with:

```python
    @property
    def view_only(self) -> bool:
        """True when D's pins are page regions only (Doc.view_only): the parsers refuse file/lo/hi and snippets."""
        return self._doc.view_only
```

In `src/limn/documents.py`, replace `doc_for_file`'s docstring and loop head:

```python
    """Which LaTeX document of docs a request that only gave a file (agent curl) belongs to: the one whose build root
    most deeply contains it (a relative path is taken under the manuscript root), or the first document if none does
    or the path cannot be resolved. View-only documents never match."""
```

```python
    for d in docs:
        if d.is_pdf:
            continue
```

with:

```python
    """Which document of docs that takes line pins a request that only gave a file (agent curl) belongs to: the one
    whose build root most deeply contains it (a relative path is taken under the manuscript root), or the first
    document if none does or the path cannot be resolved. A document without line pins (view-only) never matches."""
```

```python
    for d in docs:
        if not d.takes_line_pins:
            continue
```

- [ ] **Step 4: Move the three parser and pick branches**

In `src/limn/features/pins/editing/input.py` (`parse_add`), replace `    if facts.is_pdf:` with `    if facts.view_only:`. Replace its docstring's first sentence with:

```python
    """A POST /api/pin body for the request's document -> the new pin's validated place and fields, or the first field
    refused, in the contract's order: the location first (parse_region when the document's pins are regions -
    facts.view_only - which refuses file/lo/hi/scope; parse_loc otherwise, which reads the named file), then note,
    kind_req, mention hints and assignee (known: the logins supplied by EditingRequests)."""
```

In `src/limn/features/pins/location/input.py`, replace `parse_snippet` with:

```python
def parse_snippet(q: Query, facts: DocumentFacts) -> SourceRange | InputRejected:
    """GET /api/snippet: refused for a document whose pins are regions (facts.view_only - it has no source lines),
    else parse_source_range."""
    if facts.view_only:
        return InputRejected("보기 전용 문서(%s)에는 원문 줄이 없습니다." % facts.key, "no_source_lines")
    return parse_source_range(q, facts)
```

In `src/limn/features/pins/location/resolve.py` (`pick`), replace `    if D.is_pdf:` with `    if D.view_only:`. In its docstring, replace `a view-only document's region (PickedRegion)` with `the region of a document whose pins are regions (D.view_only; PickedRegion)`.

- [ ] **Step 5: Run the affected tests and the gates**

Run: `uv run pytest -q tests/test_web_parse.py src/limn/features/document_views/test_meta.py tests/test_server.py -k "not Browser" && uv run mypy && uv run ruff check && uv run ruff format --check`

Expected: all pass.

- [ ] **Step 6: Mutation check. Invert each branch, one at a time, and restore**

For each row below, run the flip, then the test, then the flip back (swap the last two arguments). Expected: the listed test fails on the flip, and passes after the flip back.

| File | Flip `old` → `new` | Test that fails |
| --- | --- | --- |
| `src/limn/documents.py` | `if not d.takes_line_pins:` → `if d.takes_line_pins:` | `uv run pytest -q src/limn/features/document_views/test_meta.py -k doc_for_file` |
| `src/limn/documents.py` | `return self._doc.view_only` → `return not self._doc.view_only` | `uv run pytest -q src/limn/features/document_views/test_meta.py -k test_view_only_is_the_document_capability` |
| `src/limn/features/pins/editing/input.py` | `    if facts.view_only:` → `    if not facts.view_only:` | `uv run pytest -q tests/test_web_parse.py -k "test_region_add_on_a_view_only_document or test_add_checks_the_location_before_the_note"` |
| `src/limn/features/pins/location/input.py` | `    if facts.view_only:` → `    if not facts.view_only:` | `uv run pytest -q tests/test_web_parse.py tests/test_server.py -k "test_source_range_reads_the_file_before_the_numbers or test_view_only_rebuild_is_refused_and_pick_snippet_guarded"` |
| `src/limn/features/pins/location/resolve.py` | `    if D.view_only:` → `    if not D.view_only:` | `uv run pytest -q tests/test_locate.py tests/test_server.py -k "test_a_traced_selection_carries_its_range_and_build_facts or test_view_only_pick_returns_region_without_synctex"` |

The flip command, for the first row:

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/documents.py 'if not d.takes_line_pins:' 'if d.takes_line_pins:'
```

Finish with `git diff --stat`. Expected: only this task's files.

- [ ] **Step 7: Commit**

```bash
git add src/limn/documents.py src/limn/web/parse.py src/limn/features/pins/editing/input.py src/limn/features/pins/location/input.py src/limn/features/pins/location/resolve.py tests/test_web_parse.py src/limn/features/document_views/test_meta.py
git commit -s -m "refactor(pins): branch pick and pin input on view_only" -m "DocumentFacts answers view_only; parse_add, parse_snippet and pick branch on it, and doc_for_file routes a file only to documents that take line pins. No behaviour change."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 4: Builds branch on `builds_from_source` and `watches_files`

**Files:**
- Modify: `src/limn/build.py:77-126` (`BuildDoc`), `:226-236` (`cur_pdf`), `:271-276` (`migrate_pages`), `:548-557` (`doc_fingerprint`), `:573-603` (`src_mtime`)
- Modify: `src/limn/features/builds/run.py:26-58` (`Rebuildable`, `request_rebuild`, `needs_build`)
- Modify: `src/limn/features/builds/service.py:51-56` (`tracked`), `:86-94` (`watch_pdf_docs`)
- Modify: `src/limn/features/builds/engine.py:348-354` (`refresh_pdf_doc`)
- Test: `tests/test_build.py:73-107` (`PlainDoc`), `:371`, `:709-712`; new class `ReadsBeforeAndBetweenBuilds` in `tests/test_build.py`
- Create: `src/limn/features/builds/test_watch.py` (colocated with `service.py`, ADR-0010)

**Interfaces:**
- Consumes: `Doc.builds_from_source`, `Doc.watches_files` (Task 1).
- Produces: `BuildDoc.builds_from_source -> bool`, `BuildDoc.watches_files -> bool`, `Rebuildable.builds_from_source -> bool`. Every `BuildDoc` double must answer both.

- [ ] **Step 1: Switch the build double to capabilities**

In `tests/test_build.py`, replace the `PlainDoc` docstring and its last field:

```python
@dataclass
class PlainDoc:
    """A document as the build sees it (the BuildDoc protocol), with every path given - nothing global. LaTeX by
    default; a view-only PDF sets builds_from_source=False and watches_files=True, as limn.documents.Doc answers for
    kind "pdf"."""
```

```python
    mcache_lock: threading.Lock = field(default_factory=threading.Lock)
    builds_from_source: bool = True
    watches_files: bool = False
```

In the same file, replace:
- line 371 `self.P = PlainDoc(src=src, main=pdf, dir=self.state / "docs" / "rv", is_pdf=True)` with:

```python
        self.P = PlainDoc(
            src=src, main=pdf, dir=self.state / "docs" / "rv", builds_from_source=False, watches_files=True
        )
```

- line 709 `self.pdf = PlainDoc(root, root / "review.pdf", root / "state-pdf", is_pdf=True)` with:

```python
        self.pdf = PlainDoc(root, root / "review.pdf", root / "state-pdf", builds_from_source=False, watches_files=True)
```

- line 712 `D.key = "rv" if D.is_pdf else "ms"` with `D.key = "ms" if D.builds_from_source else "rv"`.

- [ ] **Step 2: Add the two build-read tests no existing test pinned**

Append to `tests/test_build.py`, before the `# ---- through server.py's wiring` banner:

```python
class ReadsBeforeAndBetweenBuilds(unittest.TestCase):
    """What the build reads of a document, by whether it builds from source: the PDF before any page copy and the
    manuscript's newest modification time."""

    def setUp(self):
        """A LaTeX body, a view-only PDF and a second .tex in one folder, 100 s apart in that order; no build yet."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "ms"
        self.root.mkdir()
        self.state = Path(tmp.name) / "state"
        self.t = time.time() - 1000
        for name, at in (("main.tex", self.t), ("review.pdf", self.t + 100), ("other.tex", self.t + 200)):
            path = self.root / name
            path.write_bytes(b"%PDF-1.4 x" if name.endswith(".pdf") else b"x")
            os.utime(path, (at, at))
        self.tex = PlainDoc(self.root, self.root / "main.tex", self.state / "docs" / "ms")
        self.pdf = PlainDoc(
            self.root,
            self.root / "review.pdf",
            self.state / "docs" / "rv",
            builds_from_source=False,
            watches_files=True,
        )

    def test_a_document_built_from_source_reads_latexmk_output_and_any_other_its_own_file(self):
        """No page copy yet: a LaTeX document's PDF is where latexmk writes it in the build copy, even before it
        exists; a view-only document's PDF is its main file."""
        self.assertEqual(build.cur_pdf(self.tex), self.tex.out / "main.pdf")
        self.assertEqual(build.cur_pdf(self.pdf), self.pdf.main)

    def test_src_mtime_scans_the_tree_only_for_a_document_built_from_source(self):
        """A LaTeX document's manuscript time is its newest source file (other.tex); a view-only document's is its PDF
        alone, however new the .tex files beside it."""
        self.assertAlmostEqual(build.src_mtime(self.tex, self.state, force=True), self.t + 200, places=3)
        self.assertAlmostEqual(build.src_mtime(self.pdf, self.state, force=True), self.t + 100, places=3)
```

- [ ] **Step 3: Add the watch test no existing test pinned**

Create `src/limn/features/builds/test_watch.py`:

```python
"""The view-only watch (limn.features.builds.service.BuildRequests.watch_pdf_docs) over real documents.

One round of the watch starts a re-render only for a document it follows (limn.documents.Doc.watches_files) whose
file changed (limn.features.builds.engine.refresh_pdf_doc). The build start is the watch's own injection point
(BuildRequests.build_async); the test records it instead of launching pdftoppm.

Run: uv run pytest -q src/limn/features/builds/test_watch.py
"""

import tempfile
import unittest
from pathlib import Path

from limn.build import BuildStarted
from limn.documents import Doc, RunPaths
from limn.features.builds.service import BuildRequests


class OneRound:
    """A stop event that lets exactly one round of a watch loop run: the first wait says "go on", every later one
    "stop"."""

    def __init__(self) -> None:
        """No round has run yet."""
        self.waits = 0

    def wait(self, timeout: float | None = None) -> bool:
        """False on the first call, True on every later one (threading.Event.wait's answer)."""
        self.waits += 1
        return self.waits > 1


class WatchMembership(unittest.TestCase):
    """Which documents one round of the watch re-renders."""

    def test_one_round_starts_a_render_for_the_changed_watched_pdf_only(self):
        """A never-rendered view-only PDF counts as changed, so the round starts its render; the LaTeX body beside it
        is never started by the watch."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ms"
            src.mkdir()
            (src / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
            (src / "review.pdf").write_bytes(b"%PDF-1.4\n")
            paths = RunPaths(src, src / "main.tex", Path(tmp) / "state")
            docs = [
                Doc("ms", "본문", "tex", src, src / "main.tex", paths=paths),
                Doc("rv", "리뷰", "pdf", src, src / "review.pdf", paths=paths),
            ]
            requests = BuildRequests(lambda: None, lambda: {}, lambda: docs, lambda: "T", lambda r: "")
            started = []

            def start(doc):
                """Record the document the watch asked to re-render, as a started background build."""
                started.append(doc.key)
                return BuildStarted()

            requests.build_async = start
            requests.watch_pdf_docs(OneRound(), every=0)
            self.assertEqual(started, ["rv"])
```

- [ ] **Step 4: Run them and watch them fail**

Run: `uv run pytest -q tests/test_build.py src/limn/features/builds/test_watch.py`

Expected:
- Every test whose `PlainDoc` reaches an `is_pdf` read fails with `AttributeError: 'PlainDoc' object has no attribute 'is_pdf'`. Among them are `RebuildRules` and both `ReadsBeforeAndBetweenBuilds` tests.
- `WatchMembership` passes, because it runs on real `Doc`s and characterizes today's behaviour. Its red comes in Step 9.

- [ ] **Step 5: Replace the `BuildDoc` member and the four build-module branches**

In `src/limn/build.py`, replace:

```python
    @property
    def is_pdf(self) -> bool:
        """A view-only PDF document (no LaTeX source)."""
```

with:

```python
    @property
    def builds_from_source(self) -> bool:
        """latexmk builds it from the tree under src (limn.documents.Doc.builds_from_source); False: main is the PDF."""

    @property
    def watches_files(self) -> bool:
        """The watch re-renders its pages when its file changes (limn.documents.Doc.watches_files)."""
```

Replace `cur_pdf` with:

```python
def cur_pdf(D: BuildDoc, pdir: Path | None = None) -> Path:
    """The PDF matched to the page images. Uses the copy in the version directory if present; otherwise a document
    built from source reads latexmk's output in its build copy (the legacy layout's build/), and any other document
    its own main file (a view-only PDF before its first render).

    Why matching matters: even if a build fails, the screen still shows the old PDF - if pick read the
    newly broken PDF instead, it would point at a different spot than what's visible."""
    f = (pdir or cur_pages(D)) / D.pdf_name
    if f.exists():
        return f
    if not D.builds_from_source:  # nothing compiles it: its own file until pages are rendered
        return D.main
    return D.out / D.pdf_name
```

In `migrate_pages`, replace:

```python
    in build/ gets overwritten in place by a rebuild (and drifts if a build is in progress or fails partway)."""
    if D.is_pdf:
        return
```

with:

```python
    in build/ gets overwritten in place by a rebuild (and drifts if a build is in progress or fails partway). Only a
    document built from source has that layout; any other returns at once."""
    if not D.builds_from_source:  # only latexmk output has the legacy layout
        return
```

Replace the head of `doc_fingerprint`:

```python
def doc_fingerprint(D: BuildDoc, state_dir: Path) -> str:
    """The document's manuscript fingerprint: its source tree's (source_fingerprint) for a document built from source,
    else the hash of its main file's contents (a view-only PDF)."""
    if not D.builds_from_source:  # one file, hashed whole
```

In `src_mtime`, replace the docstring's first line:

```python
    """Max mtime over manuscript/figure extensions under D.src (2-second memo in D.mcache). Build artifacts and the main PDF are excluded (iter_sources).
```

with:

```python
    """Max mtime over manuscript/figure extensions under D.src (2-second memo in D.mcache). Build artifacts and the main PDF are excluded (iter_sources).
    A document not built from source measures its main file alone.
```

Then replace `    if D.is_pdf:  # view-only: that one PDF file is the manuscript` with:

```python
    if not D.builds_from_source:  # not built from a tree: that one file is the manuscript
```

- [ ] **Step 6: Replace the rebuild rules**

In `src/limn/features/builds/run.py`, replace `Rebuildable`, `request_rebuild` and the head of `needs_build` with:

```python
class Rebuildable(Protocol):
    """What request_rebuild reads of a document: its key and whether it builds from source."""

    @property
    def key(self) -> str:
        """The document key (?doc=), which the view-only refusal names."""

    @property
    def builds_from_source(self) -> bool:
        """latexmk builds it (limn.documents.Doc.builds_from_source); only such a document is rebuilt on request."""


R = TypeVar("R")
Target = TypeVar("Target", bound=Rebuildable)


def request_rebuild(D: Target, run: Callable[[Target], R]) -> R | ViewOnlyNoRebuild:
    """POST /api/rebuild's rule: a document built from source is built by run (the composition root's synchronous or
    background build) and its outcome returned; any other (a view-only PDF) is never rebuilt on request
    (ViewOnlyNoRebuild) - its pages follow its file (refresh_pdf_doc)."""
    if not D.builds_from_source:
        return ViewOnlyNoRebuild(D.key)
    return run(D)


def needs_build(D: BuildDoc, no_build: bool, dpi: int) -> bool:
    """Whether startup builds D: a watched document (D.watches_files - a view-only PDF) when its file changed since its
    pages were rendered or it has no page images at dpi (--no-build does not apply to it); a LaTeX document unless
    no_build (--no-build), and even then when its PDF or its page images are missing. Reads the page directory on
    screen and, for a watched document, its file's signature."""
    if D.watches_files:
        return engine.pdf_changed(D) or not build.page_list(build.cur_pages(D), dpi)
    return not no_build or not build.cur_pdf(D).exists() or not build.page_list(build.cur_pages(D), dpi)
```

- [ ] **Step 7: Replace the build service and watch branches**

In `src/limn/features/builds/service.py`, replace `tracked`:

```python
    def tracked(self, doc: Doc) -> FinishedBuild:
        """Run the document's build - latexmk for a document built from source, else the render of its PDF - and
        commit its status and page history."""
        step: Callable[[], FinishedBuild] = (
            (lambda: self.compile(doc))
            if doc.builds_from_source
            else (lambda: engine.render_pdf_doc(doc, self.config()))
        )
        return run.run_tracked(doc, self.settings().state, step, self.now(), self.describe)
```

Replace the head of `watch_pdf_docs`:

```python
    def watch_pdf_docs(self, stop: threading.Event, every: float = 3.0) -> None:
        """Re-render every watched document (Doc.watches_files) whose file changed, until this run's stop event is set."""
        while not stop.wait(every):
            for doc in list(self.docs()):
                if doc.watches_files:
```

In `src/limn/features/builds/engine.py`, replace `refresh_pdf_doc`:

```python
def refresh_pdf_doc(D: Doc, start: Callable[[Doc], BuildStarted | BuildBusy]) -> bool:
    """If watched document D's PDF changed (pdf_changed), start its tracked re-render with `start` (the composition
    root's background build). True when a render started; False for a document the watch does not follow (not
    D.watches_files), an unchanged or missing PDF, or a render already running (start answered BuildBusy)."""
    if not D.watches_files or not pdf_changed(D):
        return False
    return isinstance(start(D), BuildStarted)
```

- [ ] **Step 8: Run the build tests and the gates**

Run: `uv run pytest -q tests/test_build.py src/limn/features/builds tests/test_locate.py tests/test_server.py tests/test_trash.py && uv run mypy && uv run ruff check && uv run ruff format --check`

Expected: all pass.

- [ ] **Step 9: Mutation check. Invert each branch, one at a time, and restore**

The flip one-liner:

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' FILE OLD NEW
```

Apply each row, run its test (expect FAIL), then apply the reverse flip (expect the test to pass again):

| File | Flip `old` → `new` | Test that fails |
| --- | --- | --- |
| `src/limn/build.py` | `if not D.builds_from_source:  # nothing compiles it` → `if D.builds_from_source:  # nothing compiles it` | `uv run pytest -q tests/test_build.py -k test_a_document_built_from_source_reads_latexmk_output_and_any_other_its_own_file` |
| `src/limn/build.py` | `if not D.builds_from_source:  # only latexmk output` → `if D.builds_from_source:  # only latexmk output` | `uv run pytest -q tests/test_build.py -k test_migrate_copies_pdf_next_to_pages` |
| `src/limn/build.py` | `if not D.builds_from_source:  # one file, hashed whole` → `if D.builds_from_source:  # one file, hashed whole` | `uv run pytest -q tests/test_build.py tests/test_locate.py -k "test_ok_when_a_fresh_pdf_and_synctex_come_out or test_seed_builds_fingerprints_current_build_when_source_unchanged"` |
| `src/limn/build.py` | `if not D.builds_from_source:  # not built from a tree` → `if D.builds_from_source:  # not built from a tree` | `uv run pytest -q tests/test_build.py -k test_src_mtime_scans_the_tree_only_for_a_document_built_from_source` |
| `src/limn/features/builds/service.py` | `            if doc.builds_from_source` (its own line in `tracked`) → `            if not doc.builds_from_source` | `uv run pytest -q tests/test_build.py -k AsyncBuild` |
| `src/limn/features/builds/service.py` | `                if doc.watches_files:` → `                if not doc.watches_files:` | `uv run pytest -q src/limn/features/builds/test_watch.py` |
| `src/limn/features/builds/run.py` | `    if not D.builds_from_source:` → `    if D.builds_from_source:` | `uv run pytest -q tests/test_build.py -k test_a_view_only_document_is_never_rebuilt_on_request` |
| `src/limn/features/builds/run.py` | `    if D.watches_files:` → `    if not D.watches_files:` | `uv run pytest -q tests/test_build.py -k test_startup_builds_what_is_missing_or_changed` |
| `src/limn/features/builds/engine.py` | `if not D.watches_files or not pdf_changed(D):` → `if D.watches_files or not pdf_changed(D):` | `uv run pytest -q src/limn/features/builds/test_watch.py` |

Finish with `git diff --stat`. Expected: only this task's files.

- [ ] **Step 10: Commit**

```bash
git add src/limn/build.py src/limn/features/builds/run.py src/limn/features/builds/service.py src/limn/features/builds/engine.py tests/test_build.py src/limn/features/builds/test_watch.py
git commit -s -m "refactor(builds): branch builds on builds_from_source and watches_files" -m "BuildDoc answers both capabilities; latexmk, rebuild requests, the legacy layout, fingerprints and src_mtime follow builds_from_source, and the watch follows watches_files. Adds tests for the cur_pdf fallback, src_mtime and the watch's membership, which no test pinned. No behaviour change."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 5: `--git-pull` pulls for and rebuilds documents that build from source

**Files:**
- Modify: `src/limn/features/sync/run.py:57-63` (`SyncDoc`), `:198-212` (`SyncWatch.status`), `:214-264` (`SyncWatch.once`)
- Test: `src/limn/features/sync/test_gitsync.py:281-303` (`FakeDoc`, `Watch.setUp`)

**Interfaces:**
- Consumes: `Doc.builds_from_source` (Task 1).
- Produces: `SyncDoc.builds_from_source -> bool`.

- [ ] **Step 1: Switch the test double**

In `src/limn/features/sync/test_gitsync.py`, replace the `FakeDoc` docstring, `__init__` signature, docstring and first line:

```python
class FakeDoc:
    """A document as the watch reads it: a state folder, a build lock, a build state, and whether it builds from source
    (only such a document is pulled for and rebuilt)."""

    def __init__(self, folder, builds_from_source=True, built=None, state="idle"):
        """builds_from_source: False for a view-only PDF; built: head.txt's text, or None for no head.txt."""
        self.dir, self.builds_from_source = Path(folder), builds_from_source
```

In `Watch.setUp`, replace `self.pdf = FakeDoc(root / "pdf", is_pdf=True)` with `self.pdf = FakeDoc(root / "pdf", builds_from_source=False)`.

- [ ] **Step 2: Run the watch tests and watch them fail**

Run: `uv run pytest -q src/limn/features/sync/test_gitsync.py -k Watch`

Expected: FAIL with `AttributeError: 'FakeDoc' object has no attribute 'is_pdf'`.

- [ ] **Step 3: Move the protocol and both branches**

In `src/limn/features/sync/run.py`, replace:

```python
    @property
    def is_pdf(self) -> bool:
        """A view-only PDF document is never pulled for or rebuilt."""
        ...
```

with:

```python
    @property
    def builds_from_source(self) -> bool:
        """Only a document built from source is pulled for and rebuilt (limn.documents.Doc.builds_from_source)."""
        ...
```

In `SyncWatch.status`, replace the docstring and the settle line:

```python
        """The status for GET /api/meta: "disabled" without --git-pull. An "updating" status is settled here once every
        document built from source was built from the pulled commit ("current"), or one still behind it failed its
        build ("error", build_failed). Returns a copy."""
```

```python
        done = settled(head, [_progress(D) for D in list(docs) if D.builds_from_source])
```

In `SyncWatch.once`, replace the docstring:

```python
        """One round: pull remote main and start the build of each document built from source that the pull left
        behind. Also run on a --no-build startup.

        A round is deferred ("deferred", building) when any document built from source is building. Otherwise the
        build lock of every such document is held during the pull, so a fast-forward never lands while a build is
        mid-copy. The pull is shared-recorded (PullShare) like a build's. Returns the round's status; "updating" when
        builds were started."""
```

Then replace `latex_docs = [D for D in docs if not D.is_pdf]` with `source_docs = [D for D in docs if D.builds_from_source]`, and both `for D in latex_docs:` with `for D in source_docs:`.

- [ ] **Step 4: Run the sync tests and the gates**

Run: `uv run pytest -q src/limn/features/sync tests/test_server.py -k "sync or pull or Watch or MultiDoc" && uv run mypy && uv run ruff check && uv run ruff format --check`

Expected: all pass.

- [ ] **Step 5: Mutation check**

Use the flip one-liner:

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' FILE OLD NEW
```

Apply each row, run its test, then apply the reverse flip:

| Flip in `src/limn/features/sync/run.py` | Test that fails |
| --- | --- |
| `for D in list(docs) if D.builds_from_source]` → `for D in list(docs) if not D.builds_from_source]` | `uv run pytest -q src/limn/features/sync/test_gitsync.py -k "test_status_settles_when_every_document_reached_the_commit or test_status_reports_a_failed_build"` |
| `source_docs = [D for D in docs if D.builds_from_source]` → `source_docs = [D for D in docs if not D.builds_from_source]` | `uv run pytest -q src/limn/features/sync/test_gitsync.py -k "test_fast_forward_rebuilds_every_latex_document or test_up_to_date_rebuilds_only_the_document_behind"` |

Expected: each flip fails the listed test, and it passes again after the reverse flip.

- [ ] **Step 6: Commit**

```bash
git add src/limn/features/sync/run.py src/limn/features/sync/test_gitsync.py
git commit -s -m "refactor(sync): pull for documents that build from source" -m "SyncDoc answers builds_from_source; the remote-main watch locks, rebuilds and settles only those documents. No behaviour change."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 6: The changes view opens for documents that show revisions

**Files:**
- Modify: `src/limn/features/revisions/core.py:69-80` (`RevisionDoc`), `:295-301` (`revision_scope`)
- Test: `tests/test_gitrun.py:229`; `src/limn/features/revisions/test_revisions.py` (new test in `ManuscriptRevisions`)

**Interfaces:**
- Consumes: `Doc.shows_revisions` (Task 1).
- Produces: `RevisionDoc.shows_revisions -> bool`.

- [ ] **Step 1: Switch the double and add the missing test**

In `tests/test_gitrun.py`, in `test_every_call_site_runs_a_clean_git`, replace:

```python
        doc = SimpleNamespace(is_pdf=False, main=repo / "main.tex", src=repo)
```

with:

```python
        doc = SimpleNamespace(shows_revisions=True, main=repo / "main.tex", src=repo)
```

In `src/limn/features/revisions/test_revisions.py`, add to `ManuscriptRevisions`. No existing test observed this branch before:

```python
    def test_a_view_only_document_has_no_history_even_beside_committed_sources(self):
        """A PDF in the body's own folder shows no revisions: the changes view belongs to documents that show
        revisions, not to any file that happens to sit in a Git repository."""
        pdf = self.src / "review.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        rv = Doc("rv", "리뷰", "pdf", src=self.src, main=pdf, paths=ps.APP.C.paths)
        self.assertEqual(revisions.revision_history(rv), {"available": False, "revisions": []})
        self.assertTrue(revisions.revision_history(ps.APP.docs[0])["available"])
```

- [ ] **Step 2: Run them and watch the double fail**

Run: `uv run pytest -q tests/test_gitrun.py src/limn/features/revisions/test_revisions.py -k "clean_git or view_only_document_has_no_history"`

Expected:
- `test_every_call_site_runs_a_clean_git` fails with `AttributeError: 'types.SimpleNamespace' object has no attribute 'is_pdf'`.
- The new revisions test passes, because it characterizes today's behaviour. Its red comes in Step 5.

- [ ] **Step 3: Move the protocol and the gate**

In `src/limn/features/revisions/core.py`, replace:

```python
    @property
    def is_pdf(self) -> bool:
        """A view-only PDF document has no manuscript history."""
        ...
```

with:

```python
    @property
    def shows_revisions(self) -> bool:
        """Whether it has a manuscript history to show (limn.documents.Doc.shows_revisions); a view-only PDF has none."""
        ...
```

Replace the head of `revision_scope`:

```python
def revision_scope(D: RevisionDoc) -> tuple[Path, list[str]] | None:
    """Returns a Git pathspec scoped to just the manuscript text inside the chosen main .tex's folder.
```

```python
    if D.is_pdf:
        return None
```

with:

```python
def revision_scope(D: RevisionDoc) -> tuple[Path, list[str]] | None:
    """Returns a Git pathspec scoped to just the manuscript text inside the chosen main .tex's folder, or None for a
    document without revisions (not D.shows_revisions), a main file outside its build root, or a folder outside Git.
```

```python
    if not D.shows_revisions:
        return None
```

Keep the rest of that docstring ("D.src is the build-copy scope, …") unchanged.

- [ ] **Step 4: Run the tests and the gates**

Run: `uv run pytest -q tests/test_gitrun.py src/limn/features/revisions && uv run mypy && uv run ruff check && uv run ruff format --check`

Expected: all pass.

- [ ] **Step 5: Mutation check**

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/revisions/core.py '    if not D.shows_revisions:' '    if D.shows_revisions:'
uv run pytest -q src/limn/features/revisions/test_revisions.py -k "view_only_document_has_no_history or latest_revision_diff_is_real_and_scoped"
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' src/limn/features/revisions/core.py '    if D.shows_revisions:' '    if not D.shows_revisions:'
```

Expected: the middle command fails both named tests.

- [ ] **Step 6: Commit**

```bash
git add src/limn/features/revisions/core.py src/limn/features/revisions/test_revisions.py tests/test_gitrun.py
git commit -s -m "refactor(revisions): gate the changes view on shows_revisions" -m "RevisionDoc answers shows_revisions and revision_scope returns None for a document without revisions. Adds the missing test for a PDF beside committed sources. No behaviour change."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 7: Document views read `builds_from_source` for staleness and outline, `view_only` for the API

**Files:**
- Modify: `src/limn/features/document_views/reads.py:50-73` (`doc_brief`), `:98-150` (`meta`), `:161-178` (`outline_labels`)
- Test: `src/limn/features/document_views/test_meta.py` (new test in `Meta`)

**Interfaces:**
- Consumes: `Doc.builds_from_source`, `Doc.view_only` (Task 1).
- Produces: nothing new. The `/api/docs`, `/api/meta` and `/api/outline-labels` bodies stay byte-identical.

- [ ] **Step 1: Add the test no existing test pinned**

Before this task, no test failed when the `/api/docs` staleness branch (`reads.py:57`) was inverted. Only a browser test caught the light meta's `view_only` (`reads.py:134`). Add to `Meta` in `src/limn/features/document_views/test_meta.py`:

```python
    def test_staleness_and_view_only_follow_the_document_capabilities(self):
        """A .tex saved after the build on screen makes the LaTeX document stale in /api/docs and /api/meta; the
        view-only PDF in the same folder is never stale, however new its file, and is the one marked view_only."""
        for D in (self.ms, self.rv):
            self.pages(D)
            (D.dir / "built_src_mtime.txt").write_text("1.0", encoding="utf-8")
        later = time.time() + 30
        for name in ("main.tex", "review.pdf"):
            os.utime(self.src / name, (later, later))
        docs = [self.ms, self.rv]
        briefs = meta.docs_payload(docs, [], lambda r: "ms", self.state)["docs"]
        self.assertEqual(
            [(b["key"], b["stale_build"], b["view_only"]) for b in briefs], [("ms", True, False), ("rv", False, True)]
        )
        light = [meta.meta(D, {}, self.settings, docs, {}, later) for D in docs]
        self.assertEqual(
            [(m["doc"], m["stale_build"], m["view_only"]) for m in light], [("ms", True, False), ("rv", False, True)]
        )
```

- [ ] **Step 2: Run it**

Run: `uv run pytest -q src/limn/features/document_views/test_meta.py -k "Meta or OutlineLabels"`

Expected: PASS. This task's sites read `Doc`, which already has both answers, so the new test characterizes today's behaviour. Its red comes in Step 5.

- [ ] **Step 3: Move the five branches**

In `src/limn/features/document_views/reads.py`, replace `doc_brief`'s docstring and its two flag reads:

```python
    """A summary of document D - an entry of /api/docs and (with several documents) of /api/meta's docs: kind, whether
    its pins are regions only (view_only), path, staleness against its manuscript (only for a document built from
    source), build in progress and last result, the page directory on screen and its page count. Never writes (called
    from polling)."""
    b = build.state_snapshot(D)
    stale = D.builds_from_source and build.source_newer(D, state_dir) > 2
```

```python
        "view_only": D.view_only,
```

In `meta`, replace the word `staleness,` in the docstring's first sentence with `staleness (only for a document built from source),`. Then replace:

```python
    # view-only: the server re-renders on its own when the PDF changes
    newer = 0.0 if D.is_pdf else build.source_newer(D, settings.state)
```

with:

```python
    # not built from source: the server re-renders on its own when the watched file changes
    newer = build.source_newer(D, settings.state) if D.builds_from_source else 0.0
```

In the same function, replace `"view_only": D.is_pdf,` with `"view_only": D.view_only,`.

In `outline_labels`, replace `No labels for a view-only document,` in the docstring with `No labels for a document not built from source (it publishes no .aux),`, and replace:

```python
    if D.is_pdf:
        return result
```

with:

```python
    if not D.builds_from_source:
        return result
```

- [ ] **Step 4: Run the document-view tests and the gates**

Run: `uv run pytest -q src/limn/features/document_views tests/test_server.py src/limn/features/sync && uv run mypy && uv run ruff check && uv run ruff format --check`

Expected: all pass.

- [ ] **Step 5: Mutation check**

The flip one-liner:

```bash
uv run python -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); s=p.read_text(encoding="utf-8"); assert s.count(sys.argv[2])==1; p.write_text(s.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")' FILE OLD NEW
```

The `view_only` line appears twice in `reads.py`, so its rows flip two lines including the line after it (quote the newline inside the argument, as in Task 2 Step 6). Apply each row, run its test (expect FAIL), then apply the reverse flip:

| Flip in `src/limn/features/document_views/reads.py` | Test that fails |
| --- | --- |
| `stale = D.builds_from_source and` → `stale = not D.builds_from_source and` | `uv run pytest -q src/limn/features/document_views/test_meta.py -k test_staleness_and_view_only_follow_the_document_capabilities` |
| `"view_only": D.view_only,⏎        "path"` → `"view_only": not D.view_only,⏎        "path"` | the same, and `-k test_several_documents_add_their_briefs_and_signature` |
| `if D.builds_from_source else 0.0` → `if not D.builds_from_source else 0.0` | the same new test |
| `"view_only": D.view_only,⏎        "multi"` → `"view_only": not D.view_only,⏎        "multi"` | the same new test |
| `    if not D.builds_from_source:⏎        return result` → `    if D.builds_from_source:⏎        return result` | `uv run pytest -q src/limn/features/document_views/test_meta.py -k OutlineLabels` |

(`⏎` is a line break followed by the indentation shown.)

- [ ] **Step 6: Commit**

```bash
git add src/limn/features/document_views/reads.py src/limn/features/document_views/test_meta.py
git commit -s -m "refactor(document-views): stale_build and outline read builds_from_source" -m "Staleness and the .aux outline apply to documents built from source; the API's view_only is Doc.view_only. Adds the missing test for /api/docs staleness and the light meta's view_only. Same bodies."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 8: pins.md headings read two capabilities

**Files:**
- Modify: `src/limn/pins/render.py:20-33` (`DocHeading`), `:418`, `:490-494`
- Modify: `src/limn/features/pins/listing/markdown.py:92-95`
- Test: `tests/test_pins_render.py:48,285-286,309,334` and a new test in `DocumentSections`

**Interfaces:**
- Consumes: `Doc.view_only`, `Doc.builds_from_source` (Task 1).
- Produces: `DocHeading(key: str, name: str, path: str, view_only: bool, builds_from_source: bool, head: str | None, built_at: str | None)`. The positional arity grows from 6 to 7, so any leftover positional construction fails loudly.

- [ ] **Step 1: Write the tests in the new shape**

In `tests/test_pins_render.py`, replace:
- `MAIN = DocHeading("main", "본문", "main.tex", False, None, None)` with:

```python
MAIN = DocHeading("main", "본문", "main.tex", view_only=False, builds_from_source=True, head=None, built_at=None)
```

- each of the three `DocHeading("rr", "답변서", "rr/rr.tex", False, None, None)` (lines 285, 309, 334) with:

```python
DocHeading("rr", "답변서", "rr/rr.tex", view_only=False, builds_from_source=True, head=None, built_at=None)
```

- `rv = DocHeading("rv", "리뷰", "review.pdf", True, "bbb2222", "2026-09-25 08:00")` with:

```python
        rv = DocHeading(
            "rv",
            "리뷰",
            "review.pdf",
            view_only=True,
            builds_from_source=False,
            head="bbb2222",
            built_at="2026-09-25 08:00",
        )
```

Add to `DocumentSections`:

```python
    def test_stamp_word_follows_builds_from_source_and_label_follows_view_only(self):
        """The heading's two decisions read two capabilities: a document with line pins whose pages are read in, not
        built, gets the '그림' stamp and no view-only label anywhere."""
        fg = DocHeading(
            "fg",
            "도표",
            "fig/figs.pdf",
            view_only=False,
            builds_from_source=False,
            head="ccc3333",
            built_at="2026-09-25 09:00",
        )
        md = pins_md_text(page([line_pin(1)], {1: facts(doc_key="fg", location="fig/make.py")}, docs=(MAIN, fg)))
        self.assertIn("## 도표 · `fg` · `fig/figs.pdf`\n기준: ccc3333 · 그림 2026-09-25 09:00", md)
        self.assertIn("문서: 본문(`main`) 0건 · 도표(`fg`) 1건", md)
        self.assertNotIn("보기 전용", md)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest -q tests/test_pins_render.py`

Expected: collection error `TypeError: DocHeading.__init__() got an unexpected keyword argument 'view_only'`.

- [ ] **Step 3: Replace the field and the three decisions**

In `src/limn/pins/render.py`, replace the `DocHeading` class with:

```python
@dataclass(frozen=True)
class DocHeading:
    """One configured document as pins.md names it, with its build stamp as read from its build folder.

    view_only: its pins are page regions - the header says ", 보기 전용" and its section title "— 보기 전용 PDF(줄 번호
    없음)". builds_from_source: its stamp reads "빌드" (latexmk built the pages); otherwise "그림" (the pages were
    rendered from a file Limn only reads). head is the short git hash the page images came from ('-' outside git) and
    built_at when they were committed; either is None when the document was never built. path is the main file
    relative to --manuscript."""

    key: str
    name: str
    path: str
    view_only: bool
    builds_from_source: bool
    head: str | None
    built_at: str | None
```

Replace:
- `", 보기 전용" if d.is_pdf else ""` with `", 보기 전용" if d.view_only else ""`
- `        if d.is_pdf:\n            title += " — 보기 전용 PDF(줄 번호 없음)"` with `        if d.view_only:\n            title += " — 보기 전용 PDF(줄 번호 없음)"`
- `"그림" if d.is_pdf else "빌드"` with `"빌드" if d.builds_from_source else "그림"`

In `src/limn/features/pins/listing/markdown.py`, replace:

```python
        docs = tuple(
            DocHeading(d.key, d.name, d.rel_path(), d.is_pdf, build.read_head(d), build.read_built_at(d))
            for d in self.deps.docs
        )
```

with:

```python
        docs = tuple(
            DocHeading(
                d.key,
                d.name,
                d.rel_path(),
                view_only=d.view_only,
                builds_from_source=d.builds_from_source,
                head=build.read_head(d),
                built_at=build.read_built_at(d),
            )
            for d in self.deps.docs
        )
```

The docstring of the method that builds this input does not mention the flag. Leave it as it is.

- [ ] **Step 4: Run the tests and the gates**

Run: `uv run pytest -q tests/test_pins_render.py tests/test_server.py tests/test_contract_snapshot.py && uv run mypy && uv run ruff check && uv run ruff format --check`

Expected: all pass. The contract snapshot passes unchanged.

- [ ] **Step 5: Mutation check**

Use the flip one-liner (`FILE OLD NEW`, as in Task 5). Apply each row, run its test, then apply the reverse flip:

| File | Flip | Test that fails |
| --- | --- | --- |
| `src/limn/pins/render.py` | `", 보기 전용" if d.view_only else ""` → `", 보기 전용" if not d.view_only else ""` | `uv run pytest -q tests/test_pins_render.py -k "test_multi_document_sections_in_configured_order or test_stamp_word_follows_builds_from_source_and_label_follows_view_only"` |
| `src/limn/pins/render.py` | `        if d.view_only:` → `        if not d.view_only:` | `uv run pytest -q tests/test_pins_render.py -k test_multi_document_sections_in_configured_order` |
| `src/limn/pins/render.py` | `"빌드" if d.builds_from_source else "그림"` → `"빌드" if not d.builds_from_source else "그림"` | `uv run pytest -q tests/test_pins_render.py -k "test_multi_document_sections_in_configured_order or test_stamp_word_follows_builds_from_source_and_label_follows_view_only"` |
| `src/limn/features/pins/listing/markdown.py` | `view_only=d.view_only,` → `view_only=not d.view_only,` | `uv run pytest -q tests/test_server.py -k test_view_only_pin_save_validation_and_pins_md` |

Expected: each flip fails its listed test, and the test passes after the reverse flip.

- [ ] **Step 6: Commit**

```bash
git add src/limn/pins/render.py src/limn/features/pins/listing/markdown.py tests/test_pins_render.py
git commit -s -m "refactor(pins-md): headings read view_only and builds_from_source" -m "DocHeading carries the two capabilities the heading decides on: the view-only label and the build/picture stamp word. Same pins.md bytes for LaTeX and view-only documents."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

---

### Task 9: Retire `is_pdf`, document the kinds, and prove nothing changed

**Files:**
- Modify: `src/limn/documents.py:158-161` (delete `Doc.is_pdf`)
- Test: `src/limn/features/document_views/test_meta.py` (new class `RetiredKindFlag`)
- Modify: `docs/handbook/domain.md` (§여러 문서, new subsection), `docs/handbook/index.md` (file map rows), `docs/handbook/verification.md` (§1 test placement row), `CHANGELOG.md` (Unreleased → Internal)

**Interfaces:**
- Consumes: every earlier task. After Tasks 1–8, the only identifier `is_pdf` left under `src/limn` and `tests` is the `Doc.is_pdf` definition.
- Produces: no `is_pdf` anywhere under `src/limn` or `tests`.

- [ ] **Step 1: Write the guard**

In `src/limn/features/document_views/test_meta.py`, add `import tokenize` to the standard-library imports, and add after `class ToSource`:

```python
class RetiredKindFlag(unittest.TestCase):
    """The boolean that split documents into LaTeX and view-only is gone: every branch reads a capability of Doc."""

    FLAG = "is_pdf"

    def test_no_python_identifier_in_the_package_or_the_tests_is_the_retired_flag(self):
        """No attribute, parameter, field or test double in src/limn or tests is named after the flag, so no branch can
        read it and no double can stand in for a document by it."""
        hits = []
        for root in (PKG, PKG.parent.parent / "tests"):
            for path in sorted(root.rglob("*.py")):
                with tokenize.open(path) as fh:
                    names = [t for t in tokenize.generate_tokens(fh.readline) if t.type == tokenize.NAME]
                hits += ["%s:%d" % (path, t.start[0]) for t in names if t.string == self.FLAG]
        self.assertEqual(hits, [])

    def test_documents_and_their_facts_have_no_attribute_of_that_name(self):
        """Doc and DocumentFacts answer capabilities only."""
        self.assertFalse(hasattr(Doc, self.FLAG))
        self.assertFalse(hasattr(documents.DocumentFacts, self.FLAG))
```

`PKG` is the module's existing `Path(documents.__file__).parent` (`src/limn`), so `PKG.parent.parent / "tests"` is the repository's `tests/`. The flag's name appears only as a string token here, which the scan ignores.

- [ ] **Step 2: Run it and watch it fail on the one definition left**

Run: `uv run pytest -q src/limn/features/document_views/test_meta.py -k RetiredKindFlag`

Expected: 2 failed.
- The scan lists exactly one hit, `…/src/limn/documents.py:159`.
- `hasattr(Doc, "is_pdf")` is True.

If the scan lists any other file, an earlier task left a site. Fix that site with its task's capability before going on.

- [ ] **Step 3: Delete `Doc.is_pdf`**

In `src/limn/documents.py`, delete:

```python
    @property
    def is_pdf(self) -> bool:
        """A view-only PDF document (no LaTeX source, no rebuild)."""
        return self.kind == "pdf"

```

- [ ] **Step 4: Run the guard, the type check and the style gates**

Run: `uv run pytest -q src/limn/features/document_views/test_meta.py && uv run mypy && uv run ruff check && uv run ruff format --check`

Expected: all pass. `mypy` prints `Success: no issues found`, which confirms no production reference remains.

- [ ] **Step 5: Commit the code**

```bash
git add src/limn/documents.py src/limn/features/document_views/test_meta.py
git commit -s -m "refactor(documents): retire Doc.is_pdf" -m "Every branch now reads a capability; a token guard keeps the name out of src/limn and tests. No behaviour change."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

- [ ] **Step 6: Handbook, domain topic**

In `docs/handbook/domain.md`, under `## 여러 문서`, insert the following subsection after the paragraph that ends with "`[viewer.md](viewer.md)`에 있다." and before `### 서버`:

```markdown
### 문서 종류와 능력

문서 종류(`Doc.kind`)는 `tex`(LaTeX 원고)와 `pdf`(보기 전용 PDF) 둘이다. 종류는 기동할 때 `--doc` 경로의 확장자에서 한 번 정한다(`parse_doc_arg`). 대소문자는 가리지 않는다. 그 뒤로는 닫힌 타입 `DocKind`로 다닌다. `--doc` 없이 띄운 단일 문서는 `tex`다.

분기는 종류 이름을 묻지 않고 **능력**을 묻는다. 능력은 `Doc`의 속성이고, 종류에서 능력을 정하는 규칙은 [`limn/documents.py`](../../src/limn/documents.py) 한 곳에 있다. 그래서 종류가 늘어도 분기마다 종류 목록을 고치지 않는다.

| 능력 | 뜻 | `tex` | `pdf` |
| --- | --- | --- | --- |
| `builds_from_source` | 원고에서 빌드한다. latexmk, `--git-pull` 뒤 재빌드, `POST /api/rebuild`, 원고가 더 새롭다는 `stale_build`, `.aux` 목차, 원고 트리의 지문과 `src_mtime`이 여기에 걸린다 | 예 | 아니요 |
| `watches_files` | 감시 스레드가 파일이 바뀌면 쪽을 다시 그린다. 기동 때도 파일이 바뀌었으면 `--no-build`와 상관없이 그린다 | 아니요 | 예 |
| `takes_line_pins` | 줄 핀(`file`·`lo`·`hi`)과 anchor 재동기화를 받는다. 파일만 준 요청은 이 능력이 있는 문서 가운데서 찾는다(`doc_for_file`) | 예 | 아니요 |
| `shows_revisions` | 변경 보기가 있다. 원고 Git 이력과 latexdiff 비교다 | 예 | 아니요 |
| `view_only` | 핀이 쪽·영역뿐이다. 늘 `takes_line_pins`의 반대이며, API의 `view_only`가 이 값이다 | 아니요 | 예 |

기동 때 `--doc` 값을 파싱한 뒤, 아직 `Doc`을 만들기 전에 두 가지를 정한다. 키가 `main`인 문서가 상태 폴더 루트를 쓰는지와 실행의 메인 파일이 무엇인지다. 둘 다 같은 규칙(`kind_builds_from_source`)을 쓴다.

종류 자체를 알리는 곳만 `kind`를 읽는다. API의 `kind`, 권한 대상의 문서 신원, 기동 로그의 문서 줄(`doc_start_line`)이 그렇다. 기동 로그는 종류마다 이름을 고르는 `match`라서, 종류가 늘면 타입 검사가 빠진 이름을 잡는다. 종류를 더할 때는 [`test_meta.py`](../../src/limn/features/document_views/test_meta.py)의 능력 표에 그 종류의 행을 먼저 적는다. 행이 없으면 테스트가 실패한다.
```

- [ ] **Step 7: Handbook, file map and test placement**

In `docs/handbook/index.md`, replace the `src/limn/documents.py` row with:

```markdown
| `src/limn/documents.py` | 문서(`Doc`: 종류 `DocKind`와 능력 속성 `builds_from_source`·`watches_files`·`takes_line_pins`·`shows_revisions`·`view_only`, 빌드 루트·메인·문서별 상태 폴더와 빌드 잠금·상태), 파싱한 `--doc`에 쓰는 종류 규칙(`kind_builds_from_source`), 문서 키 규칙, 문서 목록을 인자로 받는 조회(`request_doc`·`doc_for_file`·`pin_doc_key`)와 조회 결과 값(`DocNotFound`), 파서가 읽는 원고 사실(`DocumentFacts`), `to_source` | 문서 종류·능력 추가나 변경, 문서 경로·키 규칙 변경 | domain.md §여러 문서, build-sync.md |
```

In the same file's `src/limn/features/administration/*` row, replace `서버 기동의 문서 인자·선택 규칙(`serve_documents.py`)` with `서버 기동의 문서 인자·선택 규칙과 기동 로그의 문서 줄(`serve_documents.py`)`.

In `docs/handbook/verification.md` §1, in the `src/limn/features/*/test_*.py` row, replace `원고 복사는 `builds/`에서 검증한다.` with `원고 복사는 `builds/`, 기동 문서 선택과 기동 로그의 문서 줄은 `administration/`에서 검증한다.`

- [ ] **Step 8: CHANGELOG**

In `CHANGELOG.md`, under `## Unreleased` → `### Internal`, add as the first bullet:

```markdown
- **Internal: document kinds are read through capabilities.** `Doc.kind` is the closed type `DocKind` (`"tex"`,
  `"pdf"`) and the boolean `is_pdf` is gone: every branch asks what a document can do - `builds_from_source`,
  `watches_files`, `takes_line_pins`, `shows_revisions`, `view_only`. No change to the HTTP API, `pins.md`, the state
  directory or the command line; the move was checked by a differential run against the code before it.
```

- [ ] **Step 9: Check the Handbook**

Run: `uv run pytest -q tests/test_handbook_refs.py tests/test_naming.py && uv run python tools/handbook-publish/publish.py check docs/handbook/index.md`

Expected: the tests pass, and `publish.py check` exits 0. It needs `.handbook/fonts/Pretendard-Regular.otf` (`docs/handbook/verification.md §7`). If the font is missing, say so in the PR instead of skipping silently.

- [ ] **Step 10: Commit the documentation**

```bash
git add docs/handbook/domain.md docs/handbook/index.md docs/handbook/verification.md CHANGELOG.md
git commit -s -m "docs(handbook): document kinds and their capabilities" -m "domain.md states the kind-to-capability table and where the kind itself is still read; the file map and test placement follow the code."
git commit --amend -m "$(git log -1 --format=%B)
I agree to the Limn CLA (CLA.md)."
```

- [ ] **Step 11: Run every gate**

```bash
uv sync --group dev
uv run pytest -q -rs -n 4 --dist loadscope
bash tests/test_instances.sh
uv run ruff check
uv run ruff format --check
uv run shellcheck src/limn/instances.sh src/limn/features/administration/instance_*.sh tests/test_instances.sh
uv run mypy
```

Expected: every command exits 0. The pytest summary shows the before-oracle counts plus the added tests, with no `failed` or `error`.

- [ ] **Step 12: Differential proof against the before oracle**

This is steps 3–5 of `docs/handbook/verification.md §구조 이동의 동작 불변 증명(차등 비교)`.

```bash
export P0_PROOF="${TMPDIR:-/tmp}/limn-p0-proof"
uv run pytest -q -rA -n 4 --dist loadscope --junitxml="$P0_PROOF/after.xml" > "$P0_PROOF/after-rA.txt" 2>&1; tail -n 1 "$P0_PROOF/after-rA.txt"
uv run python tools/test_id_map.py --before-ids "$P0_PROOF/before-ids.txt" --map "$P0_PROOF/p0-map.txt" --results "$P0_PROOF/before.xml" "$P0_PROOF/after.xml" --results "$P0_PROOF/before-rA.txt" "$P0_PROOF/after-rA.txt"
git diff --exit-code "$(cat "$P0_PROOF/base.txt")" -- tests/data/
uv run pytest -q tests/test_contract_snapshot.py tests/test_pins_model.py
```

Expected:
- `after-rA.txt`'s summary shows the before counts plus the map's `+` lines as passed, with the same skipped and subtest totals. A dry run of this whole plan on a copy of `5d1c4b6` gave `2058 passed, 1 skipped, 1046 subtests passed` (2038 + 20).
- `test_id_map.py` prints `before: N tests, after: N+M tests` (M = the number of `+` lines), lists every `+` entry under "expected new", shows empty LOST, DUPLICATED, "NEW (not in the map)", "UNUSED map entries" and "RESULT differences" sections, ends with `unmapped differences: 0`, and exits 0.
- `git diff --exit-code … -- tests/data/` prints nothing: the contract snapshot and the record corpus are the base's bytes.
- The snapshot and record-corpus tests pass.

If a browser test flips between runs, re-run that test alone on both commits and report it as flaky with both results. Do not add it to the map.

- [ ] **Step 13: Push and write the PR description with the numbers**

```bash
git push -u origin refactor/document-capabilities
```

The PR body states the following:
- the base hash
- before and after totals, and the wall time of both full runs
- the `test_id_map.py` result line
- `git diff --stat "$(cat "$P0_PROOF/base.txt")"` (files and lines)
- that `tests/data/` is unchanged
- the mutation table: which test failed for each inverted site

The PR merges when the gates are green. The index lists P0 as a patch release.

---

## Notes for later phases (not P0 work)

After P0, every site sits on the capability that stays true for a figure document. Some branches go further and assume that the document's main file is a PDF, or dispatch to the PDF importer. A figure's `main` is its map file (index §Registration), so these branches need more work than a capability flip. The later phase plans should cite this table.

| Site after P0 | What a figure needs | Phase |
| --- | --- | --- |
| `build.cur_pdf`: `if not D.builds_from_source: return D.main` | The PDF, not the map | P1a |
| `build.doc_fingerprint`, `build.src_mtime` (the not-built branch) | They hash and time the map alone; the index wants PDF + map | P1a |
| `features/builds/service.tracked`: else-branch `render_pdf_doc` | `render_figure_doc` | P1a |
| `run.needs_build`, `engine.refresh_pdf_doc` through `pdf_changed`/`pdf_signature` | A signature over both the map and the PDF (index §Build import) | P1a |
| `serve_documents.doc_start_line` | mypy (`exhaustive-match`) fails until `"figure"` has a label | P1a |
| `serve_documents.parse_doc_arg` and `instance_documents.sh:54-63` | `.limnmap.json` and the `::` form, in the same commit | P1a |
| `test_meta.CAPABILITY_TABLE` | `test_the_table_has_a_row_for_every_document_kind` fails until the figure row is written (the index's "after P1a" column, then "after P1b") | P1a, P1b |
| `Doc.watches_files`, `Doc.takes_line_pins` bodies | As the index's comments say | P1a, P1b |
| `pins/render.py:490`: `— 보기 전용 PDF(줄 번호 없음)` | Under P1a a figure is view-only and gets this "PDF" title; decide the wording there | P1a |
| `location/resolve.pick`: `if D.view_only` → region, else SyncTeX | After P1b a figure is not view-only, so the map branch must come before SyncTeX | P1b |
| `viewer/js/boot.js:59`, `build-chip.js:60`, `polling.js:63` | They read `view_only` for decisions that mean `builds_from_source`. After P1b a figure shows the rebuild button until these read `kind` | P1b or P1c |

## Self-review

- **Spec coverage.** Spec §서버 → 문서 종류 asks to turn `is_pdf` into capability values, and to test that behaviour does not change. The P0 cut in §이행 절단면 asks to prove this with the contract snapshot and the full suite. The capabilities are Tasks 1–9, with Table A as the classification. The proof is §Before you start plus Task 9 Steps 11–12. Spec risk 1 ("`is_pdf` 분기의 누락") is covered by the token guard (Task 9) and the per-task mutation steps. The spec's `is_pdf`-as-API-field sentence is Contract issue 3.
- **Placeholder scan.** No TBD or TODO, and no step that describes code without showing it. Where a test was missing (rows 1, 4, 7, 25 and the others marked "new" in Table A), the owning task adds it.
- **Type consistency.**
  - The names are the same in every task: `DocKind`, `kind_builds_from_source`, the five properties, `DocumentFacts.view_only`, `BuildDoc.builds_from_source`/`watches_files`, `Rebuildable.builds_from_source`, `SyncDoc.builds_from_source`, `RevisionDoc.shows_revisions`, `DocHeading(view_only=…, builds_from_source=…)` and `doc_start_line(key, kind, path, build_started)`.
  - Test class and method names in the map of §Before you start match the tasks' code.
- **Review Focus.**
  - Item 1: Tasks 2, 4, 6 and 7 add tests for the branches no test observed.
  - Item 2: Task 9.
  - Item 3: Task 1 (`test_the_table_has_a_row_for_every_document_kind`).
  - Item 4: Task 2.
  - Item 5: Task 8 (`test_stamp_word_follows_builds_from_source_and_label_follows_view_only`).
- **Dry run.** Every code block of Tasks 1–9 was applied to a scratch copy of `5d1c4b6` outside the repository. On that copy:
  - `ruff check` was clean and `mypy` passed (`Success: no issues found in 134 source files`). `ruff format` rewrapped three blocks; the plan now shows the formatter's output.
  - The full suite gave `2058 passed, 1 skipped, 1046 subtests passed`.
  - Each of the 28 mutation flips in the task tables failed its named test and was green again after the restore.
  - `tools/test_id_map.py` with the map of §Before you start reported `unmapped differences: 0`.
  - `tests/test_handbook_refs.py` and `tests/test_naming.py` passed with the Handbook edits and with this file.
  - `publish.py check` was not run, because the font is not on that machine.
