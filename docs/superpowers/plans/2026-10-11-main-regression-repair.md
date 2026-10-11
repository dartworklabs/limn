# Main regression repair implementation plan

Scope: [main regression repair](../specs/2026-10-11-main-regression-repair.md). Authority is the user's repair request and the existing contracts recorded there; this is not a new design approval. Each task is one logical review unit. Commit points are recorded for integration only; this session does not stage, commit, push, deploy or change services.

## Task 1: One external-document build generation

- [x] Step 1: Reproduce source replacement before/during/after real rendering in `src/limn/builds/tests/` and preserve assertion reds. Verify the current source and publication contract in `src/limn/builds/engine.py` and `docs/handbook/build-sync.md`.
- [x] Step 2: Render and publish from an immutable private snapshot; bind the successful fingerprint to that snapshot and retain `.part` publication. Exercise failed copy/render cleanup without changing the published pair.
- [x] Step 3: Verify actual page/PDF identity through HTTP and the next watcher recovery, then synchronize `docs/handbook/build-sync.md`. Expected: complete coherent generations, preserved old publication on failure, no temporary leak. Commit point: coherent build repair after review.

## Task 2: Persisted parsing rejection boundaries

- [x] Step 1: Write assertion-red cases and pure generated invariants for local timestamps, unencodable pin rows and malformed non-strict token stores in the owning slices. Check `docs/handbook/domain.md` and `docs/handbook/api.md` against current parser and access code.
- [x] Step 2: Preserve timestamp value-or-`None`, isolate corrupt pin rows under existing backup behavior, and retain invalid bearer `401` plus strict CLI refusal. Use real persisted files and actual request handling for boundary examples.
- [x] Step 3: Verify finite epochs/platform bounds, valid legacy/unknown pin fields, next locked write and unchanged authorization results; synchronize the owning Handbook topics. Expected: malformed input stays rejected without poisoning valid state. Commit point: persisted parsing repair after review.

## Task 3: Browser test portability and native macOS gate

- [x] Step 1: Reproduce unchanged shortcut/caret assertion reds and the two hint ink failures in `src/limn/viewer/tests/`; preserve command, UTC, exit, output, source diff and hashes.
- [x] Step 2: Keep explicit non-Apple/Apple shortcut contract fixtures, send native search keys in generic journeys, and use native start-of-text navigation before insertion/deletion. Preserve outcome assertions and layout/key-code cases.
- [x] Step 3: Add an actual-platform shortcut assertion; observe its red with the old Control-only input and its green with native input. Run the search/focus/document-row/assignee classes against real Chromium.
- [x] Step 4: Extend `.github/workflows/ci.yml` with bounded macOS Chromium coverage using required-tool flags, pinned actions and read-only credentials. Update `docs/handbook/verification.md`. Expected: selected classes collect and execute with zero failures/skips locally; remote job execution remains unverified until CI runs. Commit point: portability repair after review.
- [x] Step 5: Measure unchanged hint ink, actual drawn fonts and cap-trim geometry in controlled platform/font contexts. Expected: classify residuals without changing production UI or the `0.5px` expectation; report any remaining failure to integration.

## Task 4: Integration review

- [ ] Step 1: Freeze worker changes, recheck refreshed target movement, and review original evidence and diffs against `docs/handbook/architecture.md`, scope, plan and current contracts. No approved ADR changes, added runtime dependencies or cross-slice imports are expected.
- [ ] Step 2: Run applicable full checks once after integration, sequentially for shared mypy cache, and retain complete red/green results and skip reasons. Run affected checks again only after a new change/failure warrants it.
- [ ] Step 3: Report measured results, residual UI failures and unexecuted remote gates. Expected: passing repairs are distinct from unresolved gate failures; no merge, deployment or complete-gate claim without the corresponding evidence. Commit point: reviewer-controlled integration after all applicable gates and scope review.
