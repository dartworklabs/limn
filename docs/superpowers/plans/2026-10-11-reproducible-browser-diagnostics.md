# Reproducible browser diagnostics implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. The root orchestrates the already assigned workers, reviews their source/evidence, and owns Git integration.

**Goal:** Automatically provide a suitable fixed test face for the existing browser regressions and measure the search hint's actual eight-CSS-pixel inner spacing.

**Architecture:** Repair the existing browser-test preparation and search-geometry observer. A test-only verified font cache supplies a page-scoped face before viewer boot; a restored, zero-size grid marker measures the used inner edge. Product rendering and runtime boundaries remain unchanged.

**Tech Stack:** Python 3.10+, pytest with existing xdist/loadscope, standard-library test preparation, Playwright Chromium/Firefox/WebKit, browser FontFace API.

**Spec:** `docs/superpowers/specs/2026-10-11-reproducible-browser-diagnostics-design.md`

## Approval and preserved Handbook context

The owner explicitly approved the bounded in-chat design with “고”. This plan records the already authorized execution; it does not claim the owner separately reviewed a document that did not exist. Apply `brainstorming`'s bounded classification and the project-required spec/checkbox-plan records in this order before implementation. Root has selected worker execution. No additional approval is required for routine choices inside this scope.

The spec's four context sections, `현재 권위와 상태`, `지켜야 할 현재 불변식`, `설계 이유와 제약`, and `충돌·미확인`, are inputs to every task. Their role/path mappings remain: purpose / `docs/handbook/purpose.md`; architecture / `docs/handbook/architecture.md`; 일반 주제 / `docs/handbook/viewer.md`; verification / `docs/handbook/verification.md`. The actual source is viewer source/tests, `tests/support/helpers_browser.py`, `.github/workflows/ci.yml`, and `pyproject.toml`; ADRs do not substitute for those preconditions. Current installed-font dependence and the outer `8 + 1` assertion are current reality, while automatic provision and actual-inner-edge observation are the approved target until implementation and verification complete.

## Global constraints

- Server runtime dependencies remain `[]`; product HTML, CSS, JavaScript, served assets, authentication, storage, and HTTP/pins contracts remain unchanged.
- Keep existing glyph-ink assertions, font identity checks, skip policies, and tolerances. The inner-spacing assertion retains `delta=0.01` CSS pixels and expects eight CSS pixels.
- Tests observe real renderer output at the boundary and wait for actual conditions; do not add sleep, retries, or a fake renderer.
- Test-only font provision must work with standard pytest preparation and xdist, without permanent font installation or editing global configuration.
- Handbook prose is Korean and describes current rules; source, spec, plan, and changelog prose is English. Product documents contain no actual home paths or hostnames.

## Review focus

- Empty/corrupt/truncated cache bytes must not reach FontFace: test digest and byte-count rejection at the real cache boundary.
- Concurrent first use must not consume partial bytes: exercise simultaneous provision against a new isolated cache.
- Offline warm use must reuse only verified bytes; a cold network failure must report its reason under existing strict prerequisite policy.
- Viewer boot must see the font before geometry/ink code runs, while a fresh unprovisioned Chromium page cannot inherit that face.
- Fractional DPR, right padding, and wider borders must preserve an independent inner-edge oracle; margin 7/9 and padding 1 must fail the identical assertion, and border 2 must pass.

## Task 1: Automatically provision the fixed face for existing font-sensitive tests

**Owner:** font worker. **Files:** create `tests/support/helpers_browser_font.py`, `tests/test_browser_font.py`, and `tests/fixtures/browser-font/` provenance/license records; modify `tests/support/helpers_browser.py`, `src/limn/viewer/tests/test_viewer_input.py`, `src/limn/viewer/tests/test_viewer_size_alignment.py`, and `.github/workflows/ci.yml`. Add any necessary forwarding keyword only inside the existing test fixture methods that those classes call.

**Interfaces:** `provision_test_font(cache_dir: Path | None = None) -> VerifiedTestFont | FontProvisionFailure`; `prepare_font_document(html: str) -> str`; `install_test_font(page: Page, font: VerifiedTestFont, viewer_route: Callable[[Route], None]) -> None`. `VerifiedTestFont` holds verified immutable bytes; `FontProvisionFailure.message` includes the source/cache context for provision errors. `BrowserBase.open`, the separate `ViewerBase.view` page-creation seam, `SizeAlignmentBase.view`, and `CardFixture.cards` accept/forward optional `test_font=False` only for the two explicit regression contexts. The helper wraps the served root document's classic inline script and awaits an explicit font-ready marker before viewer boot. No later task imports this helper.

- [x] **Step 1: Preserve the red baseline.** Run the unchanged font-sensitive classes in the current font-deficient environment and save argv, source hashes, output, timing, and strict prerequisite failure. Existing source and earlier spike evidence must remain distinguishable.

  ```bash
  LIMN_TEST_REQUIRE_BROWSER=1 LIMN_TEST_REQUIRE_NODE=1 uv run pytest -q -rs -n 0 src/limn/viewer/tests/test_viewer_input.py::HangulInkInClippingBoxes src/limn/viewer/tests/test_viewer_size_alignment.py::LabelInkCentre
  ```

  Expected before the repair: the missing wide-Hangul face is an assertion/prerequisite failure, not a skipped green run.

- [x] **Step 2: Pin official bytes and provenance.** Record the exact upstream commit URL, SHA-256, byte count, original OFL text, and test-only cache policy under `tests/fixtures/browser-font/`. Check the artifact against the prior verified spike and official source. Preserve download/provenance evidence outside the repository. No product vendor file changes.

- [x] **Step 3: Add cache-boundary regression checks before the helper fix.** In `tests/test_browser_font.py`, exercise valid real-cache bytes, digest/length corruption, cold network failure, offline warm reuse, and parallel cold cache publication. Use an isolated cache directory, not a developer's default cache. Observe the new contract checks fail before implementation or under a plausible cache-integrity/publication mutation; record actual failures.

  ```bash
  uv run pytest -q -rs -n 0 tests/test_browser_font.py
  ```

  Expected after implementation: valid artifact reuse succeeds, corrupt bytes are rejected or replaced only with freshly verified bytes, and every concurrent consumer receives complete verified bytes. A download failure remains diagnostic.

- [x] **Step 4: Wire scoped preparation into the existing browser fixture.** Implement bounded download and atomic publication in the helper. Route only the font-requesting test page through preparation that awaits face loading before the existing viewer boot script. Forward `test_font` through the existing fixture and request it in `HangulInkInClippingBoxes` and the fallback branch of `LabelInkCentre`. Keep `FIRST_FONT`, drawn-face inspection, clipping pixel checks, Hangul/capital ink assertions, and skips/tolerances intact. Extend the existing `macos-browser` command with the two original classes and `tests/test_browser_font.py::BrowserFontProvision` to gate native-host font scoping as well as ink.

- [x] **Step 5: Verify normal preparation and isolation.** Run the exact Step 1 command without the external session-font wrapper, then run with two xdist workers. Confirm real Chromium reports Noto Sans CJK KR for the provisioned Hangul probe, viewer geometry starts after the font is available, and a fresh unprovisioned page retains its native environment. No OS font is installed or registered. Preserve cold/warm cache results and artifact hashes.

- [x] **Step 6: Review and prepare the logical commit.** Affected Ruff checks and task tests completed, and root's independent spec/quality review passed after the scoped corrections. Source/evidence has been handed to root. The actual source commit is the next integration stage in Task 3 Step 5; worker performs no Git writes.

## Task 2: Observe the actual inner border and preserve regression sensitivity

**Owner:** oracle worker. **Files:** modify only `src/limn/viewer/tests/test_viewer_search.py`.

**Interfaces:** colocated `hint_inner_inset(page)` returns the rendered inner-border-to-hint gap in CSS pixels. `SearchBarGeometry.test_the_hint_is_small_muted_right_aligned_and_gone_with_a_query` and new `SearchHintInsetChromium.test_the_hint_keeps_eight_pixels_inside_its_actual_border` call the same observer. `SearchHintInsetFirefox` and `SearchHintInsetWebKit` select the existing `BROWSER_ENGINE` fixture surface; they do not use the font helper from Task 1.

- [x] **Step 1: Preserve the outer-edge red case.** Run the original `8 + 1` outer assertion at WebKit DPR 1.5 against unchanged product source, retaining the original `.01` tolerance. Preserve the actual assertion failure and source hashes externally. The earlier wider DPR 1.25/1.5 diagnostic matrix remains supplemental evidence.

- [x] **Step 2: Implement the observer inside the search test module.** Append a zero-size final grid child to reveal the used content edge, include measured right padding to locate the inner border, and remove the marker/restore every inline style in `finally`. Verify all pre-existing child rectangles and screenshot bytes agree before and after probing. Do not derive the result from a declared border width or margin.

- [x] **Step 3: Correct the existing assertion and add the bounded engine/DPR matrix.** Preserve the original method's font size, muted color, vertical center, focus, query visibility, and touch assertions. Use the same inner-distance contract:

  ```python
  self.assertAlmostEqual(hint_inner_inset(page), 8, delta=0.01)
  ```

  Add the named Chromium method over DPR `(1, 1.25, 1.5, 2)` and inherited Firefox/WebKit methods. Expected: twelve real renderer contexts pass with native hint, bundled body font, light theme; missing engines obey existing required-browser handling.

- [x] **Step 4: Prove the persisted assertion rejects plausible regressions.** Inject browser-only margin 7, margin 9, and padding 1 into separate evidence runs and call the same helper/assertion; each must fail on the expected actual value. Border 2 must still measure inner 8 and pass. Restore mutations before the next case and preserve their failing output, not only a wrapper's exit-zero summary.

- [x] **Step 5: Run affected tests and review nonperturbation.** Run the original geometry class and the new engine classes with existing strict prerequisites. Confirm unchanged product source hashes and no leaked observer marker/styles. Retain the broader fonts/theme/platform matrix as supplemental evidence if executed; do not count it as CI scope.

  ```bash
  LIMN_TEST_REQUIRE_BROWSER=1 LIMN_TEST_REQUIRE_NODE=1 uv run pytest -q -rs -n 0 src/limn/viewer/tests/test_viewer_search.py::SearchBarGeometry src/limn/viewer/tests/test_viewer_search.py::SearchHintInsetChromium src/limn/viewer/tests/test_viewer_search.py::SearchHintInsetFirefox src/limn/viewer/tests/test_viewer_search.py::SearchHintInsetWebKit
  ```

  Record the three engines' actual launch versions in the evidence; bundled WebKit is not the Safari application.

- [x] **Step 6: Review and prepare the logical commit.** Affected Ruff checks and the strict renderer/mutation evidence completed, and root's independent spec/quality review passed. Source/evidence has been handed to root. The actual source commit is the next integration stage in Task 3 Step 5; worker performs no Git writes.

## Task 3: Integrate verification and synchronize current documentation

**Owner:** root for integration/checks, records worker for documentation. **Files:** modify `docs/handbook/verification.md`, `docs/handbook/viewer.md`, `CHANGELOG.md`; change the Handbook index filemap only if new test preparation responsibility requires it. Spec/plan remain the work records.

**Interfaces:** consume both workers' actual source paths, test names, red/green logs, artifact identity, timing, and limits. Produce current Korean procedures and an English changelog entry that agree with the final implementation.

- [x] **Step 1: Review actual implementations against the spec.** Task 1 provision remains test-only/page-scoped and Task 2 shares the strict rendered oracle. Independent review confirmed unchanged glyph-ink assertions, skips, tolerances, retries, product assets, runtime dependencies, and public contracts. Root's final remote-main recheck and any reconciliation belong to Step 5 before integration and must preserve the original T3 checkout.

- [x] **Step 2: Synchronize current Handbook facts.** `verification.md` describes normal fixed-font provision, verified-cache failure policy, and the actual gate command/config. `viewer.md` describes used inner-border measurement, the twelve-context engine/DPR scope, unchanged ink acceptance, and physical-device/Safari limits; former Chrome-only wording is narrowed only for the inset scope. `CHANGELOG.md` records developer-test reliability. Dates, incident timeline, and raw measurements remain outside Handbook prose.

- [x] **Step 3: Run standard preparation and project checks.** Root ran standard preparation and pytest with existing strict prerequisites and no external font wrapper, together with every project check required by `AGENTS.md`. Command/output/timing and legitimate prerequisite limits are retained externally. Node/engine/TeX prerequisites retain existing policy. Do not repeat green suites without a new change or unresolved concern.

  ```bash
  uv run pytest -q -rs
  bash src/limn/administration/tests/test_instances.sh
  uv run ruff check
  uv run ruff format --check
  uv run shellcheck src/limn/administration/instances.sh src/limn/administration/instance_*.sh src/limn/administration/tests/test_instances.sh
  uv run python tools/check_boundaries.py
  uv run mypy
  uv run mypy --platform darwin
  npm ci --ignore-scripts
  npm run typecheck
  uv run python tools/strict_ratchet.py
  ```

- [x] **Step 4: Check documentation/source traceability.** Changed relative links, Handbook references, and final source/diff were reviewed. The wheel contains 347 entries, excludes tests/test-font artifacts, and declares no runtime `Requires-Dist`; all 343 product files remain byte-identical. Checkboxes reflect completed local work while physical-device, remote-CI, merge, and main-validation limits remain explicit.

- [ ] **Step 5: Final review and integration commit point.** Root performs the final design/contract review and Git integration authorized for this task. Report actual checks, genuine red mutations, unchanged product scope, and remaining limits. No service, preview, deployment, or external message is part of this plan.

  The local source handoff has `3958 passed`, `10 skipped`, and `2991 subtests passed` in `433.94s`; the instance checks report 202 passes. Ruff lint/format, shell checks, feature boundaries, mypy including Darwin, JavaScript types, and the strict ratchet pass. The final assertion-line formatting wrap preserves the exact Python AST; the post-wrap global formatter reports 517 files already formatted and lint passes. The full pytest result belongs to the identical-AST pre-wrap source; the remaining diff is formatting and plan records. These results describe the local tested source, not a main merge or remote CI result.

  Root rechecks remote main and reconciles movement before committing/integrating. The source commit, exact PR/CI tree, remote check results, actual main merge, and main validation are tracked in the PR and external execution ledger. Final review covers the plan-record and formatting delta; Step 5 stays open until the authorized integration and validation actually complete.

## Plan self-review

The tasks cover every spec requirement: fixed font/provenance/cache/isolation in Task 1; inner eight-pixel observation/nonperturbation/engine matrix/mutations in Task 2; standard test preparation, actual-source Handbook sync, and integration checks in Task 3. The five review-focus risks have explicit observations in their owning tasks. No pure-domain property was introduced because these changes observe renderer and cache/process boundaries; the matrix and real-cache checks must use trustworthy independent expectations. The preserved user approval authorizes this bounded execution; no new subsystem or irreversible product boundary is hidden in it.
