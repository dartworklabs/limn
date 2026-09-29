# Trust Boundary Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Close concrete input, authority and manuscript-path enforcement gaps from the conformance audit.
**Architecture:** Shared request recognition and access authorization produce constrained values. Feature shells consume authority and checked file handles; pure domain values stay independent of I/O.
**Tech Stack:** Python 3.10+, standard-library runtime, pytest/Hypothesis, Ruff/mypy.
**Spec:** docs/superpowers/specs/2026-09-29-trust-boundary-completion.md

## Global Constraints

Preserve ordinary requests, existing role permissions, pins.md and storage; no runtime dependency or auth-provider changes. English source/docstrings, Korean Handbook. No automatic follow-up merge without validation. Existing PR #107 merge is user-authorized.

## Review Focus

- Malformed transport must not persist people/pins or consume trailing requests.
- Unknown newly registered operations fail closed even for owner.
- Authority cannot be reused across target/action/instance or altered through actor mutation.
- Symlink replacement cannot expose excluded manuscript content.
- Refusals preserve current error precedence and normal client behavior.

### Task 1: Unambiguous input

**Files:** web/handler.py, new web request parser, web/parse.py if necessary; focused transport/property tests; singleton identity helper coordinated with access owner.
- [x] Step 1: Add failing boundary and parser-property tests for duplicate JSON/query/header inputs and no effects.
- [x] Step 2: Implement parsers/header checks and move person recording after transport parse.
- [x] Step 3: Run affected HTTP/error tests, verify red evidence and normal requests, provide integration handoff.

### Task 2: Scoped authority

**Files:** access.py, web/routes.py, web/app.py, server.py, feature mutation services/HTTP adapters and affected tests. Coordinate handler integration with Task 1 and editing service with Task 3.
- [x] Step 1: Pin role/operation behavior and rejection of new registration and wrong scope.
- [x] Step 2: Implement explicit policy and immutable action/target/instance-bound authority consumed at mutation boundaries; protect construction with a source guard.
- [x] Step 3: Run access/service/HTTP behavior tests and type checks; independently review enforcement coverage.

### Task 3: Checked manuscript file handles

**Files:** files.py, documents.py, locate.py, feature source consumers and tests. Keep pure rules free of filesystem imports.
- [x] Step 1: Add failing real-FS tests for excluded paths and post-validation replacement.
- [x] Step 2: Implement checked capability/read sink and propagate to all manuscript read consumers; coordinate shared file edits.
- [x] Step 3: Test source/location/Markdown/editing behavior and mutation proof, review race and descriptor lifetime.

### Task 4: Integration and evidence

**Files:** docs/handbook/{api,architecture,code-style-roadmap,verification,index}.md, ui_en.json, skill/SKILL*.md if client contract guidance changes, focused behavior/property tests.
- [x] Step 1: Replace remaining concrete internal-call assertions where behavior can be observed; add useful transition-sequence properties without claiming exhaustiveness.
- [x] Step 2: Update contract and current-state documentation, audit findings and compatibility note.
- [x] Step 3: Independent review and full pytest, instances, Ruff/format, mypy, ShellCheck, package and Handbook checks.
- [x] Step 4: Commit logical changes and publish follow-up PR with exact evidence and limitations.

## Execution evidence

- PR #107 merged at d8dfe92 after all six CI jobs passed (Python 3.10/3.12, macOS, TeX, lint and installed command).
- Input boundary: JSON/query/header rejection, no-write and connection-close tests; JSON/query/header guard mutations detected. Independent review additionally reproduced raw non-ASCII query acceptance and excessive Content-Length returning 500; fixed with new regressions. Input suite: 25 passed, 46 subtests.
- Authority: 112 new matrix/negative/resource/dispatch tests. Focused authority/web/access suite: 199 passed, 1 skipped, 148 subtests. Claim guard deletion mutation detected. Review strengthened same-name and mutated document rejection, replaced state/jobs/cache resources and post-authorization attribution recording.
- Filesystem: real path/exclusion/symlink-replacement/descriptor-lifetime tests. Broader file/location/render/store suite: 231 passed, 1 skipped, 13 subtests. Disabling no-follow caused two deterministic secret-disclosure regressions; no disk mutations left behind.
- Test behavior: lifecycle sequences detect a missing reopen revision increment. Revision retry checks the new failure outcome, not compiler call count. Six shutdown tests observe actual socket and worker termination; both omitted-cleanup mutations detected. OS signaling adapter assertions remain legitimate boundary evidence.
- Changed-code documentation: 56 missing docstrings added to changed test/helper functions; executable AST unchanged. No untouched bulk documentation.
- Collection: 1889 previous tests, 2039 current; 150 additions and two explicit renames (clear now requires owner authority; flags consume a single parsed value). No unexplained loss.
- Ruff/format, mypy (134 production sources), ShellCheck, instance suite (190 passed), Handbook check/build and clean wheel CLI/import checks passed. Wheel contains no tests or runtime dependencies.
- Independent final authority review approved current request-boundary enforcement. This is not an atomic hot-reconfiguration guarantee; no production hot-reconfiguration path exists in the inspected runtime.

- First full integration run identified three unmigrated test fixtures (direct claim adapter authority and document-facts checked source). Updated those fixtures without weakening assertions; targeted 39 passed, 7 subtests. The full suite was rerun after correction.

- Final full regression: 2028 passed, 11 skipped, 1046 subtests passed in 129.76s. All local gates passed; follow-up CI evidence is recorded on the PR.
