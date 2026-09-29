# Remaining Roadmap Cleanup Implementation Plan

> **For agentic workers:** Use subagent-driven-development with isolated ownership and independent review. Preserve the previous uncommitted cleanup.

**Goal:** Implement all four remaining candidates from the prior audit and assess code against the team's rules without claiming absolute conformance.

**Architecture:** Complete lifecycle/editing feature ownership, separate build completion projection from effects, put the existing shared Git outcome adapter at its execution boundary, and colocate pin service tests over one real-store fixture. Runtime behavior remains unchanged.

**Tech Stack:** Python >=3.10; standard-library runtime; uv, pytest, Hypothesis, Ruff and strict mypy.

**Spec:** Existing accepted backend VSA design `docs/superpowers/specs/2026-09-28-backend-vsa-migration-design.md`; user explicitly requested all remaining work after reading the prior report.

## Current authority and state

- purpose — `docs/handbook/purpose.md`: actual behavior is source/tests; API contract lives in api.md.
- architecture — `docs/handbook/architecture.md`: single distribution, feature ownership, explicit per-run resources, common storage/security boundary.
- verification — `docs/handbook/verification.md`: differential behavior, contract snapshots, type/lint/package and documentation gates.
- general topic — `docs/handbook/code-style-roadmap.md`: R1–R10 and current limitations.
- actual baseline — previous working tree: 1863 passed, 11 skipped, 1000 subtests (120.53s); prior changes are retained.

## Invariants

No HTTP or pins.md byte changes, stored record migrations, authentication/bind/permission policy changes, new threads or dependencies. Preserve Git environment filtering, argument arrays, timeout values, execution failure outcomes and no-prompt policy. Pure modules import no effectful modules. Shared pins modules never import features. Tests may move but existing assertions/identities must be accounted for.

## Design reasons and constraints

Lifecycle/editing mutation rules have feature owners; shared rendering/thread primitives and constants remain genuinely shared. Completion projection is a value calculation while history/state publication must retain existing order and lock timing. Sync must not consume revision internals for a general Git adapter. Service fixtures must remain one real temporary PinStore, with no inherited test duplication.

## Conflicts and unknowns

Repository-wide skill conformance is not inferred from clean lint/tests. Audit R1–R10 against actual source and tests and record precise residual findings/verification limitations. Preserve compatibility quirks; flag any change requiring a product decision instead of silently altering policy.

## Global Constraints

- No commits, push, merge or deployment.
- Preserve all previous work and snapshot files.
- English code/docstrings; Korean current Handbook.
- Independent workers do not edit another worker's assigned files.

## Review Focus

Legacy records and insertion order; shared-to-feature dependency cycles; build failure and publication order; Git failure/environment policy; test fixture inheritance and test loss; mocks that merely mirror implementation.

### Task 1: Lifecycle and editing rule ownership

**Files:** `pins/lifecycle.py`, `pins/edit.py`, new pure rule modules in existing lifecycle/editing features, all their consumers and corresponding pure tests. Do not edit `tests/test_service.py`; report its necessary import changes to root for Task 4.
**Interfaces:** Preserve every moved function/type signature and body. Retain helpers used by other slices or shared pure code at their current common owner; no compatibility reexports into features.

- [x] Step 1: Audit symbol consumers and record exact ownership split before editing; run pure rule and contract baselines.
- [x] Step 2: Extract single-owner commands/outcomes/mutations into feature rules and update imports.
- [x] Step 3: Colocate pure mutation tests; place reused fixtures in test helpers rather than importing test modules. Keep genuinely shared predicate tests at root.
- [x] Step 4: Extend purity coverage, compare original definition ASTs and test identities, run affected behavior tests and snapshot. Expected unchanged behavior and dependency direction.
- [x] Step 5: Review as an independent logical commit unit; leave uncommitted.

### Task 2: Pure build completion projection

**Files:** `features/builds/run.py`, new feature-owned pure completion module, colocated output tests; relevant existing `tests/test_build.py` callers if required.
**Interfaces:** A named completion value constructed from FinishedBuild, timestamps, source baseline and already rendered failure log. Caller reads clock/started state, persists history and publishes state. Avoid a generic framework or unrelated rewrites.

- [x] Step 1: Run existing build behavior baseline; characterize all outcome variants and exact last/history/state payloads.
- [x] Step 2: Extract pure projection and leave time, locks, record_build and state_update at the shell. Preserve five-error cap, 4000-character history tail, full live log, key order and success-only history entry.
- [x] Step 3: Add output-focused examples and meaningful properties (truncation/prefix/order invariants), with red or mutation proof. Pure code must not import I/O; separate shared value imports if needed without moving shared infrastructure.
- [x] Step 4: Run build/service/meta/contract tests and static checks. Expected failure and success paths unchanged.
- [x] Step 5: Review independently; leave uncommitted.

### Task 3: Shared Git outcome adapter

**Files:** `gitrun.py`, `features/revisions/core.py`, `server.py`, affected Git/sync/revision tests. Security overlay: code-security.
**Interfaces:** Move existing `(returncode | None, stdout, stderr)` adapter to gitrun with existing timeout default preserved or explicitly passed; sync/revisions use that owner. Preserve no-shell/no-prompt/environment policy and exception handling.

- [x] Step 1: Trace callers, timeout constant and exception normalization. Record trust boundary: manuscript-scope commands assembled by existing trusted code, execution enforced in gitrun; no new authority or policy.
- [x] Step 2: Move adapter and remove sync's revision implementation dependency; no duplicate forwarding implementation.
- [x] Step 3: Update callers/tests to owned boundary and test success, nonzero, timeout/start failures and environment isolation. Avoid replacing real managed Git repositories with mocks.
- [x] Step 4: Run gitrun/sync/revision behavioral tests and strict static checks. Expected existing outcome bytes and settings.
- [x] Step 5: Review security preservation independently; leave uncommitted.

### Task 4: Service test ownership and skills audit

**Files:** `tests/test_service.py`, shared test-only helper and feature-owned service/API tests, current docs and audit report.
**Interfaces:** Reuse real PinStore fixture without inheriting tests. Keep shared context/actor/import boundary tests under root. Move each behavior class once to its capability; preserve test identity or record explicit rename mappings.

- [x] Step 1: Save current test identities; map classes to lifecycle, editing, claims and trash, identify shared fixture dependencies.
- [x] Step 2: Move fixture and test classes, update imports for Task 1 rules, remove imports of test modules as helpers. Replace redundant fake managed-store tests with real fixture behavior where concrete value exists and account for any test replacement.
- [x] Step 3: Run direct feature suites and compare all preexisting IDs/assertions. Expected no unexplained test loss or duplicates.
- [x] Step 4: Audit actual R1–R10 evidence: production purity/dependencies, request values, globals/resources, ownership, docstrings, typing and test doubles. Fix concrete local violations introduced/touched by this work; describe substantive unrelated gaps and required design decisions accurately.
- [x] Step 5: Update Handbook/current paths, run full pytest, Ruff/format/mypy/ShellCheck, shell suite, package smoke and Handbook check/build. Independently review final integration and record exact counts/skips/limitations.

## Execution record

- Task 1: moved 52 lifecycle/editing definitions and 13 constants/type aliases with identical ASTs; shared primitives remain in pins. Pure/render/property/snapshot checks: 167 passed, 109 subtests. Broader affected HTTP/store/access/viewer tests: 433 passed, 2 skipped, 198 subtests. Both new rule modules rejected deliberate clock imports; mutations restored.
- Task 2: ten existing build outcome class ASTs retained in pure build_values.py; build.py reexports the same class objects. Completion effect ordering preserved. Nine new outcome/property/purity tests; changes to error cap, log-tail cap and imports were each detected. Focused checks: 67 passed, 1 skipped, 22 subtests.
- Task 3: Git adapter's signature and executable AST preserved; only owner and documentation changed. Five new output/failure tests observed failing before implementation. Targeted: 120 passed, 7 skipped, 88 subtests (baseline 115 passed).
- Task 4: service fixture extracted once; lifecycle/editing/claims/trash tests colocated. All 94 original service class methods retain bodies; original identities preserved. Claim feature fake store replaced with real temporary PinStore; returned-vs-persisted assertions reject an in-memory skipped-write mutation. Direct service suites before/after: 87 passed, 21 subtests (1.06s/0.72s).
- Additional R9 fix: sync and async HTTP tests use real local Git, scheduler, copy and persisted history instead of own-method call counts. Controlled external compiler input uses Events and bounded lock acquisition. New topic-branch policy test. Policy bypass/no-op scheduler mutations rejected. Affected suites: 77 passed, 5 skipped, 18 subtests (15.27s).
- Collection mapping: 1874 before, 1889 after; 125 existing tests moved, 15 explicitly added; no lost/duplicated/unexplained identities. Map: `2026-09-29-remaining-roadmap-tests.txt`.
- Independent reviews: Tasks 1/4 preserve source/test ASTs and behavior; Tasks 2/3 preserve publication ordering, type identities, Git policy and pure dependency closure. Stale source ownership comments found in review were corrected.
- Static checks: Ruff zero errors, 337 files formatted, mypy 132 production files. ShellCheck zero warnings. Instance suite 190 passed, zero failed.
- Package and docs: wheel/sdist and Handbook check/build pass; clean wheel help/version/server imports and type identities pass; no tests or runtime dependencies in wheel.
- Final regression: 1878 passed, 11 skipped, 1000 subtests passed in 126.99s. Skips require unavailable TeX/bwrap tools or an explicitly supplied real-state copy. Follow-up independent review approved the real Git/scheduler tests, checked Event release and bounded completion cleanup, and reran seven affected tests successfully. Real compiler success/rendering and execution on Python 3.10 remain outside this local verification.
- Scope limitation: no authentication/permission/input policy change. The separately documented audit identifies ambiguous input, new-route default-deny, and capability/path type gaps. See `docs/superpowers/reviews/2026-09-29-skill-conformance.md`.
