# Adopted search shortcut hint typography

## Request and owner approval

The owner reviewed the actual rendered before/after Tailnet PoC and replied **“고”** to the explicit adoption question ending **“이 시안으로 반영할까요?”**, after being told that the candidate was not yet on main. That answer approves the displayed hint-only `system-ui` proposal, its existing macOS gate extension and synchronized documentation. It authorizes updating PR #236, waiting for CI, merging and testing actual main. It does not approve a broader UI redesign, release/version/tag change or operating-instance update.

This is the formal adoption record written before source integration. The exploratory prototype and its pending-adoption records remain frozen as historical evidence; they are not merged or copied as current approval records. The [earlier backend repair scope](2026-10-11-main-regression-repair.md) remains the authority for PR #236's established backend repairs and native browser fixture corrections, not the approval for this typography choice.

## 현재 권위와 상태

- **질문 종류**: current behavior, adopted target and verification limits.
- **role / path**: purpose / `docs/handbook/purpose.md`. **실제 정본**: viewer source and tests. **확인한 현재값**: integration starts from PR #236 head `6e3d05b068700d0655a6dd1e2a6e10264b67afd9`; refreshed main is `ff8ee0d5590aeb05c46aff5e932028f0cee00592`. These are distinct trees.
- **role / path**: architecture / `docs/handbook/architecture.md`. **실제 정본**: declared invariants and `pyproject.toml`. **확인한 현재값**: stdlib-only runtime, existing slice boundaries, compatible API/storage/authentication contracts.
- **role / path**: 일반 주제 / `docs/handbook/viewer.md`. **실제 정본**: [`search.css`](../../../src/limn/viewer/css/search.css), unchanged [`search.js`](../../../src/limn/viewer/js/search.js), [`test_viewer_search.py`](../../../src/limn/viewer/tests/test_viewer_search.py). **확인한 현재값**: the base hint inherits the controls' font; the adopted target uses `system-ui` only on `#search-hint`.
- **role / path**: verification / `docs/handbook/verification.md`. **실제 정본**: [CI workflow](../../../.github/workflows/ci.yml) and unchanged search screenshot assertions. **확인한 현재값**: the native macOS gate covers keys/focus/scope/document rows/tagging; the adopted target additionally collects its existing fallback-font SearchInk method.
- **role / path**: 일반 주제 / `docs/handbook/workflow.md`. **실제 정본**: workflow and supplied owner approval. **확인한 현재값**: rendered four-device-group review precedes UI integration; the actual nine-pair PoC has been shown and this precise candidate is approved.

## 지켜야 할 현재 불변식

1. Native Apple `⌘F`, other-platform `Ctrl F`, query lifecycle, focus return and touch/phone hint concealment keep their existing behavior.
2. The original SearchInk screenshot oracle still requires hint ink within `0.5` CSS px of the bar centre. Hint-slot/right-inset assertions, tolerances, skips, deadlines and retries are unchanged.
3. Input/count typography and geometry, production JavaScript, templates, original tests and browser helpers are untouched.
4. No runtime dependency, cross-slice import, public route/field/status, persisted format, identity policy or CI credential authority changes.
5. Product documentation states the adopted rule and reason in the same change; external machine paths, hostnames and personal identifiers stay outside the repository.

## 설계 이유와 제약

- **role / path**: 일반 주제 / `docs/handbook/viewer.md`. **이유·감수한 비용·적용 조건**: fixed keyboard names use one native system UI face independently of generic control fallback. The original monospace Latin `F` and fallback Command symbol paint a mixed-face hint whose centred cap box leaves its ink high. A hint-only font-family declaration avoids that composition without runtime offsets or raster measurement. Ordinary Pretendard hint glyph shape and width can change; the owner saw and approved that tradeoff.
- **role / path**: verification / `docs/handbook/verification.md`. **이유·감수한 비용·적용 조건**: collect the unchanged fallback-font method in the required native macOS Chromium gate at DPR 1/2. It exercises actual hint paint with `sans-serif`/`monospace` control contexts, not arbitrary mixed-font centring or every engine/platform.
- **role / path**: architecture / `docs/handbook/architecture.md`. **이유·감수한 비용·적용 조건**: the reversible typography decision introduces no stop signal or architectural contract change, so this formal spec records the bounded choice without a new ADR.

## Exact implementation and rendered coverage

Adopt the four frozen tracked candidate files byte-for-byte: `src/limn/viewer/css/search.css`, `.github/workflows/ci.yml`, `docs/handbook/viewer.md`, `docs/handbook/verification.md`. Approved CSS SHA256 is `8f83ff4a37e5e92c868404e7daf88ddf19ec8658c45c22d525fa9cde727c0f2b`. The sole viewer-source edit adds `font-family:system-ui` to `#search-hint` and its English reason. The native CI selector adds only the existing fallback-font method; pins, read-only token, required tools and non-persisted checkout credentials remain intact.

The reviewed gallery has nine equal-scale rendered before/after pairs with enlarged hint detail where useful:

| Group | Actual rendered comparison |
| --- | --- |
| Desktop | 1440×900 ordinary bundled-font controls; separate 1440×900 monospace stress fixture |
| Phone | 390×844 and 320×720 coarse-pointer layouts |
| Tablet | 768×1024 and 1024×768 coarse-pointer layouts |
| Foldable | 344×882 outer, 673×841 inner portrait, 841×673 inner landscape coarse-pointer layouts |

The 18 images were captured by an actual macOS browser. All seven coarse-layout before/after pairs have identical PNG bytes and hide the hint. These are emulated layouts, not physical phone/tablet/foldable tests. Owner visual approval applies to the displayed proposal; it is not owner physical-device approval. Persistent Tailnet HTTPS and exact resource hashes were verified from the authorized host; other reviewers need Tailnet access, and a reboot/login was not exercised.

## Evidence, acceptance and 충돌·미확인

The frozen prototype's source-bound evidence records original assertion red around `-1.081` CSS px at DPR 1/2, then 96 unchanged search tests/153 subtests and the exact expanded native gate's 24 tests/13 subtests passing. Full prototype validation passed 3936 tests with 23 disclosed environmental skips and 2967 subtests; 202 instance checks and completed static/type checks passed. These are prior frozen-prototype results, not results for a future PR revision or merged main.

An actual macOS Chromium/Firefox/WebKit matrix passed all 144 screenshot ink and outer-midpoint observations across two hint strings, three control fonts, two themes and four DPRs. Its aggregate command still exited **1** on **24** stricter WebKit fractional-DPR right-inset diagnostic failures. Exact original CSS reproduced all 24; all 48 paired inset measurements were identical. This diagnostic remains FAIL and pre-existing, with no assertion relaxation. The unchanged original search suite and expanded Chromium gate pass separately.

Native Linux/Windows system fonts, Safari application, physical touch devices, older engines without cap trimming and other reviewers' ACLs remain untested. Initial prototype mypy cache contention and pre-install missing `tsc` failures are retained alongside valid completed runs; they are not erased or attributed conclusively beyond evidence. No search assertion, tolerance, skip, helper or retry is adjusted to obtain green.

Fresh integration checks must bind the exact adopted bytes and preserve commands, UTC, exit status, full output and source hashes outside the repository. Review must compare adoption scope, source/docs, preserved tests and CI privileges. PR CI must pass on the new exact head before merge. Main must then be fetched and checked at its actual merged head. Remote CI, merge and actual-main results are not yet established by this spec; their owner is the integration orchestrator. No release, tag, deployment or live-instance update is implied.
