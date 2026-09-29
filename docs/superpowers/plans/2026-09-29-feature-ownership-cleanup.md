# Feature Ownership Cleanup Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Steps use checkbox syntax for tracking.

**Goal:** Resolve the audited claim, trash and outline ownership gaps and colocate the listed feature tests without changing behavior.

**Architecture:** Move single-consumer pure rules into their existing feature; retain genuinely shared predicates and state primitives in the shared domain. Colocate feature-specific tests while preserving their identities and assertions. No new runtime, storage, permission or API contracts.

**Tech Stack:** Python >=3.10, standard-library runtime, uv, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-28-backend-vsa-migration-design.md`, the adopted roadmap R1/R6/R9, and the user's explicit request to plan and execute this cleanup with subagents.

## Current authority and state

- purpose — `docs/handbook/purpose.md`: source and tests own runtime behavior; `docs/handbook/api.md` owns agent contracts.
- architecture — `docs/handbook/architecture.md`: existing feature slices, common pin persistence and run-specific resource ownership.
- verification — `docs/handbook/verification.md`: before/after behavior runs, contract snapshot, package smoke, static checks and test identity comparison.
- general topic — `docs/handbook/code-style-roadmap.md`: R1 pure decisions, R6 capability ownership/test colocation, R7 authored contracts and R9 behavioral assertions.

## Current invariants

Preserve HTTP/status/message/key order, record and pins.md bytes, PinStore.transact ordering, shared claim display semantics, legacy records, run isolation, standard-library-only dependencies and Python 3.10 syntax. Pure modules never import I/O or HTTP. No shared-domain import of features.

## Design reasons and constraints

Claim mutation and trash mutation each have a single feature owner; claim display and trash visibility have multiple consumers and stay shared. The outline parser has one production consumer in document_views. Shared build facts and broad server assembly remain common because their consumers span features. Each implementation task is independently reviewable and reversible.

## Conflicts and unknowns

The existing pytest layout exposes root test helpers only during root collection. Colocation must support direct feature invocation. Strict mypy currently discovers colocated tests despite the handbook stating tests are excluded; scope only test modules out while retaining strict production checking. Actual before/after counts and local environment skips must be recorded, not inferred.

## Global Constraints

- No runtime dependencies, API/storage/security changes or snapshot regeneration.
- No commits, push, merge or deploy during this working-tree cleanup.
- Preserve unrelated changes and historical specs/ADRs.
- English code/docstrings; Korean Handbook.

## Review Focus

- Legacy claim display differs intentionally from mutation eligibility: retain claim_holds in shared domain.
- Trash restoration must preserve record ordering and revision behavior.
- A moved test must run exactly once and retain all assertions.
- Direct feature tests must resolve helpers without depending on collection order.
- Wheel must exclude all colocated test modules; strict typing must still cover production.

### Task 1: Pin mutation rule ownership

**Files:** `src/limn/pins/lifecycle.py`, new `features/pins/claims/rules.py` and `features/pins/trash/rules.py`, both features' input/http/service consumers, tests importing moved symbols.
**Interfaces:** Preserve names/signatures of ClaimRequest, ClaimClosedPin, ClaimedByOther, NotClaimed, claim, claim_open, unclaim, NotInTrash, AlreadyLive, drop, find_trashed and restore. Keep CLAIM_FIELDS, claim_holds, rev_after and signature shared. No compatibility reexports from shared code.

- [x] Step 1: Run existing pure lifecycle/claims/trash/service/web tests before changing code; record counts/time.
- [x] Step 2: Move the listed definitions without changing bodies, update all imports and add explicit module contracts.
- [x] Step 3: Move ClaimTransitions and TrashTransitions tests into their feature folders, preserving names/assertions and imports; retain shared lifecycle coverage at root.
- [x] Step 4: Extend the existing pure import guard to include the new pure rules and prove it rejects a deliberate I/O import, restoring immediately.
- [x] Step 5: Run the same behavior tests and contract snapshot; inspect AST/body differences and all remaining callers. Expected: identical existing behaviors and no shared-to-feature dependency.
- [x] Step 6: Review the diff as one logical commit unit; leave it uncommitted as required above.

### Task 2: Document outline ownership

**Files:** move `src/limn/outline.py` to `src/limn/features/document_views/outline.py`; move `tests/test_outline.py` to the same feature; update `reads.py` and current consumers/guards.
**Interfaces:** Preserve parser function signatures and returned values; no forwarding module.

- [x] Step 1: Run existing outline tests and record counts/time.
- [x] Step 2: Move parser/tests and update import paths, including pure import guards. Preserve assertions and parser bodies.
- [x] Step 3: Run moved tests plus document metadata tests. Expected: identical parsed labels and failures.
- [x] Step 4: Review this independent logical commit unit; leave uncommitted.

### Task 3: Capability test colocation and direct invocation

**Files:** `pyproject.toml`; move `tests/test_gitsync.py`, `test_pull.py` into sync; `test_revisions.py` into revisions; `test_meta.py` into document_views; `test_reply.py` into pins/lifecycle; `test_build_copy.py` into builds. Root shared-domain and cross-cutting tests remain.
**Interfaces:** Preserve test class/method identities and helpers. Add `pythonpath = ["tests"]` to pytest config and an anchored mypy test-module discovery exclusion, without weakening production strictness.

- [x] Step 1: Save pre-move collection IDs; use existing baseline run and targeted pre-move tests.
- [x] Step 2: Move the six files unchanged apart from path-dependent imports/fixtures; verify every use of __file__ and sibling imports.
- [x] Step 3: Configure direct invocation and type-check discovery. Run moved tests by explicit feature paths, Ruff and mypy. Expected: helpers import successfully and all production files stay checked.
- [x] Step 4: Compare collection IDs with `tools/test_id_map.py`; no lost/duplicated test identities.
- [x] Step 5: Review this independent logical commit unit; leave uncommitted.

### Task 4: Integration, current documentation and independent review

**Files:** `docs/handbook/index.md`, `architecture.md`, `code-style-roadmap.md`, `verification.md`; other current documentation only when its links move.

- [x] Step 1: Update ownership and test paths in current Handbook, without rewriting history or adding progress logs to topics.
- [x] Step 2: Run full pytest, contract snapshot, shell suite, Ruff check/format, ShellCheck and mypy; record counts/times/skips.
- [x] Step 3: Build wheel/sdist and verify installed help/version and wheel test exclusion; run Handbook check/build.
- [x] Step 4: Independently review final diff for semantics, dependency direction, all callers and current docs; fix concrete findings and rerun affected checks only.
- [x] Step 5: Record measured results and remaining audited candidates; report actual completion scope.

## Execution evidence

- Clean initial worktree on existing `refactor/vsa-test-colocation-phase3`; no unrelated modifications.
- Full pre-change baseline: 1863 passed, 11 skipped, 1000 subtests in 134.15s. Skips require TeX/SyncTeX, bwrap/latexdiff, or an explicitly supplied real state copy.
- Task 1 targeted baseline: 215 passed, 263 subtests in 1.86s.
- Task 2 before/after: 15 passed, 7 subtests in 0.10s each; parser byte-identical and test assertions AST-identical. Injected `import os` was rejected, then restored. Combined outline/meta: 44 passed, 14 subtests in 0.41s.
- Task 3's initial concurrent targeted run encountered the other worker's outline move (one stale source-path guard); this is not a pristine baseline. The complete pre-change run above is the before oracle.

## Audited follow-up candidates

- Shared `pins/lifecycle.py` and `pins/edit.py` still combine feature-owned mutations with genuinely shared helpers. Continue ownership-by-caller analysis before a later lifecycle/editing extraction; this cleanup does not claim the entire VSA migration is finished.

- `features/builds/run.py::finish_build` still mixes completion projection with persistence. A separate behavior-preserving extraction should test truncation, key order and success-only history before changing it.
- `server.py` injects the revision Git wrapper into synchronization. Moving that subprocess adapter would touch a shared execution/security boundary; keep it as a separately reviewed task.
- `tests/test_service.py` combines several capabilities through inherited fixtures. Split only with collection-identity proof and real-store fixtures; do not duplicate inherited tests.
- Shared `build.py`, `mentions.py`, `people.py`, pin model, serialization and contract suites have genuine multi-feature consumers and retain their current shared ownership.

- Task 1 after: 215 passed, 263 subtests in 3.21s; all 42 production-definition ASTs and 15 claim/trash test-method ASTs unchanged. Deliberate subprocess import rejected (1 failure, 0.24s), restored; direct rules/purity 15 passed, 8 subtests in 0.21s.
- Task 3 direct moved suites: 165 passed, 7 skipped, 69 subtests in 43.39s. Final collection mapping: 1874 before/after, 198 moved, zero unmapped differences; four existing ambiguous class/method keys retain their multiplicities.
- Ruff check: zero errors; format: 323 files unchanged; mypy: 128 production files pass. ShellCheck: zero warnings. Instance suite: 190 passed, zero failed.
- Handbook check/build succeeded. Wheel/sdist built; clean wheel installation passed help/version/server import. Wheel contains moved production modules, no test modules, no runtime dependencies.
- Independent Tasks 2/3 review: no actionable findings; parser byte identity, seven moved test ASTs and source guards verified.
- Independent Task 1 review: 12 moved and 30 retained definitions identical; all 54 original lifecycle test identities preserved once; no stale imports, dependency inversion or changed claim-display semantics.
- First integrated run: 1862 passed, 11 skipped, 1000 subtests, one source-guard failure in 141.18s. `NoOtherGitCall` recursively treated colocated Git fixtures as production (45 literals). `test_gitrun.py` and the analogous `test_errors.py` scanner now exclude only `test_*.py`, matching distribution ownership. Reproduced red before the fix; both affected suites passed (28 tests, 58 subtests, 3.90s). A temporary production module containing a literal Git command still failed the guard and was removed in `finally`. No runtime code changed in this fix.

- Scoped source-guard fix review: no issues; recursive production coverage retained and exclusion matches wheel test naming.
- Final full verification: **1863 passed, 11 skipped, 1000 subtests in 120.53s**, with the same counts and environment-limited skips as the baseline. Contract snapshot remained unchanged and passed in both complete runs.
- Final assessment: all four planned tasks complete; runtime semantics and distribution contracts preserved. Remaining ownership candidates above are not claimed as completed. No commits, push, merge or deployment performed.
