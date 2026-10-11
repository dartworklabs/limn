# Reproducible browser diagnostics

## Approval and scope

The owner approved the bounded follow-up design with “고” after the proposal to provide a fixed test font during normal test preparation, measure the search hint from the actual inner border at eight CSS pixels, and integrate both repairs into the repository tests. This document records that existing approval; it does not represent a new architectural approval stage. The existing font-dependent and search-geometry test flows define the scope. The preceding throwaway diagnostics establish feasibility but are not the implementation.

The intended outcome is a normal `uv run pytest -q -rs` run that provides the required font availability without a manual external wrapper and detects an actual search-hint spacing regression across supported browser engines. The approved design changes test preparation and observation only.

## Handbook context

### 현재 권위와 상태

- **질문 종류:** current behavior and approved change intent. **role:** purpose. **path:** `docs/handbook/purpose.md`. **실제 정본:** viewer source and its tests for rendering; `docs/handbook/verification.md` for verification procedures and acceptance. **확인한 현재값:** the product uses bundled Pretendard; separate wide-Hangul checks currently depend on installed fallback fonts.
- **질문 종류:** current boundary contract. **role:** architecture. **path:** `docs/handbook/architecture.md`. **실제 정본:** the current ownership map and invariants in that topic. **확인한 현재값:** standard-library-only server runtime, feature-local tests, no new runtime dependency or product vendor bundle.
- **질문 종류:** current spacing contract. **role:** 일반 주제. **path:** `docs/handbook/viewer.md`, “본문 검색”. **실제 정본:** `src/limn/viewer/css/search.css` and `src/limn/viewer/tests/test_viewer_search.py`. **확인한 현재값:** the hint ends eight CSS pixels inside the right border; `SearchBarGeometry.test_the_hint_is_small_muted_right_aligned_and_gone_with_a_query` initially asserts an outer distance of `8 + 1` in the desktop fixture at DPR 2. The fractional-DPR red reproduction explicitly overrides that fixture.
- **질문 종류:** current verification contract. **role:** verification. **path:** `docs/handbook/verification.md`. **실제 정본:** `.github/workflows/ci.yml`, `pyproject.toml`, and the repository browser test harness in `tests/support/helpers_browser.py`. **확인한 현재값:** normal pytest collection gates CI; strict browser prerequisites fail instead of skipping; retries and tolerance changes cannot establish correctness.

### 지켜야 할 현재 불변식

1. Server runtime dependencies remain `[]`; product HTML, CSS, JavaScript, served assets, authentication, storage, and HTTP/pins contracts remain unchanged.
2. Keep existing glyph-ink assertions, font identity checks, skip policies, and tolerances. The inner-spacing assertion retains `delta=0.01` CSS pixels and expects eight CSS pixels.
3. Tests observe real renderer output at the boundary and wait for actual conditions; do not add sleep, retries, or a fake renderer.
4. Test-only font provision must work with standard pytest preparation and xdist, without permanent font installation or editing global configuration.
5. Handbook prose is Korean and describes current rules; source, spec, plan, and changelog prose is English. Product documents contain no actual home paths or hostnames.

### 설계 이유와 제약

- **role / path:** verification / `docs/handbook/verification.md`. A test must pin the rendered contract and expose a plausible regression. Environment-dependent missing fonts and an assumed one-CSS-pixel border create false alarms; repairing those mechanisms preserves the acceptance criteria.
- **role / path:** 일반 주제 / `docs/handbook/viewer.md`. The fixed eight-pixel space is inside the border. Device-pixel border snapping means a specified `1px` border need not occupy exactly one CSS pixel at fractional DPR. The used inner edge must therefore be independently observed.
- **role / path:** architecture / `docs/handbook/architecture.md`. A licensed, pinned test artifact belongs under the test tree and outside the product wheel and served vendor tree. Its provenance and digest must travel with it.

### 충돌·미확인

- No architecture, runtime, authentication, storage, or external API boundary change is intended. No new ADR is required for this bounded test repair.
- Actual Safari application, physical iOS/Android devices, arbitrary font/zoom combinations, and remote CI results are outside local diagnostic evidence.
- Implementation details are approved routine choices inside this scope; Handbook statements about the chosen provision and observer are synchronized only after confirming actual source and runs.

## Design

### Fixed test font

Keep one official Noto Sans CJK KR source at a pinned upstream commit with SHA-256, expected byte count, and the original SIL OFL license. Normal preparation for the font-sensitive tests lazily downloads the exact artifact into a test-only external cache and validates its bytes before use. Verified warm preparation and cache checks work offline. The persistent empty-cache publication test consumes the actual verified canonical bytes through the owning source adapter; preserve a real official cold-download proof as external evidence rather than forcing a fresh network fetch in every test run. Cold download and invalid-cache failures remain actionable test failures. Publish cache entries atomically so parallel workers cannot consume partial bytes; do not write a large font blob into the product package.

Load the verified font as a page-scoped `FontFace` before the fixture's viewer script executes, and preserve the existing font-identity checks and font priority. This guarantees a suitable face is available when the host lacks one; it does not guarantee identical glyph dimensions on every host, because a preinstalled WenQuanYi face can retain its existing priority. Only the explicit wide-Hangul/fallback tests request this face. Other native system-font and bundled Pretendard checks retain their original environment. No operating-system font registration or cleanup is needed, and fresh pages without the provision must not inherit it. The existing `HangulInkInClippingBoxes` and `LabelInkCentre` remain the rendered behavior oracles.

### Inner-border observation

Repair the existing hint-spacing assertion to measure `inner_border_right - hint_right == 8` using a rendered content-edge probe. A zero-width final grid marker can reveal the used content edge; adding measured right padding locates the inner border. The probe must restore the DOM and inline styles and preserve all existing child rectangles and screenshot bytes. Reading a declared border width or margin alone is insufficient.

The repository regression covers Chromium, Firefox, and bundled WebKit at DPR 1, 1.25, 1.5, and 2 with the native hint, bundled font, and light theme. Preserve the existing broader ink tests. Retain expanded native Apple/controlled non-Apple strings, light/dark themes, and bundled/sans-serif/monospace contexts as supplemental diagnostic evidence; do not describe this expanded matrix as a CI gate. Required-engine handling follows the existing browser policy.

### Acceptance evidence

Record the original missing-font and fractional-DPR outer-spacing failures and the corrected passing runs with exact source identity. The same strict eight-pixel assertion must genuinely fail for margin 7, margin 9, and padding 1 browser-only mutations; increasing the border to 2 must preserve the valid inner eight-pixel space. Before/after observer geometry and paint must agree. Run the two original font-sensitive classes without the external wrapper, then standard pytest and the applicable project checks. Restore every temporary mutation before integration.

These risks are renderer/environment interactions, so use real-browser integration checks and a bounded input matrix rather than an artificial pure-domain property test. Keep raw logs, source hashes, timings, font cleanup evidence, and mutation observations outside the product repository. CI completion and physical-device coverage must be reported separately.

## Non-goals

No product layout, interaction, text, or font change; no preview service or deployment; no runtime dependency; no new public API; no permanent font installation; no weakening glyph assertions, tolerances, prerequisite failures, or retry policy.
