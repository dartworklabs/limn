# Owner-answered Capability Queries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Consumers use purpose-specific facts and completed effect inputs without understanding provider storage or parser models.

**Architecture:** Preserve the capability owners and server composition. Providers interpret their files and internal records; consumers receive explicit results and narrowly injected operations. Reconcile main's figure functionality before reshaping the interfaces.

**Tech Stack:** Python 3.10+, standard library runtime, pytest/Hypothesis, Ruff, mypy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-01-owner-answered-capability-queries-design.md`

## Global Constraints

- Preserve HTTP paths, fields, refusal behavior, notification stream, pin Markdown, and stored records, including the figure additions already on main.
- Keep server runtime dependencies empty and Python 3.10 support. No new thread, event bus, worker, or outbox.
- Preserve transaction ordering and post-commit notification/audit timing.
- Preserve the build selected by the viewer at drag time; source reads remain checked at read time.
- No release or deployment; preserve main's P1c release blocker.
- The user approved direct inline implementation: no additional plan-review pause.
- Handbook context: preserve the spec's Current authority and state, Current invariants to preserve, Reasons and constraints, and Conflicts and unverified state sections. Actual code/tests settle behavior; architecture and verification Handbook topics settle invariants/gates.

## Review Focus

- A request for an old figure publication must not use the current map or PDF.
- Participant extraction must preserve duplicate-actor precedence and exclude workflow fields.
- A missing marker or corrupt history must retain existing output defaults rather than crash.
- A warm map cache must not authorize a source path changed to an escaping symlink.
- Notifications must preserve optional fields, recipients, and emission after pin commit.

## Files and ownership

- Builds: `queries.py` owns provider projections; `application.py` wires queries; artifact/map implementations stay private.
- Pins: `application.py`, `runtime.py`, `context.py`, location/editing/listing consumers, and `revision.py` extract owned facts and notice inputs.
- Collaboration/security: directory/notices/events/people consume flat identity and notice facts, never pin record schemas.
- Documents: service/reads assemble returned facts; outline parsing stays here.
- Revisions: core/scope consume immutable pin facts and own close-reference resolution.
- Server, package exports, boundary checker, and Handbook: connect/enforce/document the above.

### Task 1: Preserve current main and establish the integrated baseline

**Files:** The merge-conflicting Handbook/build/pin/server/test files plus upstream additions.
**Interfaces:** Consumes both committed histories; produces the reconciled figure-capable application without dropping either side's behavior.

- [x] Step 1: Use `git merge --no-commit --no-ff origin/main`, inspect each conflict and both parent versions. Resolve with `apply_patch`, retaining new figure functionality and the existing composition refactor.
- [x] Step 2: Restore every new figure callback/cache/startup hook at its capability owner. Verify via `rg -n 'figure_map|figure_imported|rewrite_pins' src/limn` and actual tests, not textual resolution alone.
- [x] Step 3: Run `uv run pytest -q -rs -m 'not browser and not tex'` and static checks. Expected: existing LaTeX, figure, rollback, and contract tests pass; no merge markers.
- [x] Step 4: Commit the deliberate merge with sign-off and CLA text. Record the baseline and any integration defects fixed with focused failing regression tests.

### Task 2: Publish owner-interpreted build queries

**Files:** Create `src/limn/builds/queries.py`, add `builds/tests/test_queries.py`; modify build assembly and exports.
**Interfaces:** Produce immutable/detached document summary, selected-publication assets, position-history facts, header facts, outline input, figure selection and element lookup. Named missing results preserve current refusal behavior. No consumer gets `FigureMap`, `MapPage`, `MapElement`, raw history/state, or marker filenames.

- [x] Step 1: Write provider tests against real temporary publication/history/map files. For example:

```python
def test_selected_publication_keeps_its_build_when_current_changes(tmp_path):
    """The selected publication remains distinct from the new current build."""
    # Use the existing document/publication fixtures to publish two builds.
    selected = queries.publication(document, old_build)
    assert selected.build == old_build
    assert selected.pdf != queries.publication(document, current_build).pdf
```

- [x] Step 2: Run the new tests before implementation. Expected: missing query/result API, then assertion-level red mutations for historical identity and projected values.
- [x] Step 3: Implement queries using build-owned artifact/map reads. Define explicit fields for state/outcome/history/page and element facts; normalize missing marker values in the provider. Keep the original cache identity and source-path checks.
- [x] Step 4: Run provider tests and existing build/map tests plus Ruff/mypy. Expected: query outputs and old behavior pass; no storage-shaped result escapes.
- [x] Step 5: Commit the provider contracts with sign-off and CLA text.

### Task 3: Bind pin and document consumers to build answers

**Files:** Pin context/runtime/location/figure/editing/listing, document reads/service/application, build document facts, server wiring and corresponding tests.
**Interfaces:** Consume Task 2 results through concrete query functions; produce unchanged pick, pin, Markdown, document/meta and outline answers.

- [x] Step 1: Write boundary-consumer tests from explicit facts, including historical figure selections, missing headers, and warm-cache escaping source paths. Use real manuscript files; do not mock private helpers.
- [x] Step 2: Run the new tests and demonstrate red failures for the broad-provider contract or leaked artifact reconstruction.
- [x] Step 3: Replace `BuildView` and figure parser/model imports in consumers. Consumers use complete answers; pure calculations accept plain values. Documents cannot glob page folders or read build marker files. Pins cannot decode build history or traverse map objects.
- [x] Step 4: Run pin location/editing/listing, document, figure rollback and HTTP contract tests; run boundary/type checks. Expected: all preserved outputs including figure refusal/ladder/mark/el_sync behavior.
- [x] Step 5: Commit the consuming boundary change and ownership documentation with sign-off and CLA text.

### Task 4: Publish flat participants and completed notice inputs

**Files:** Pin assembly/runtime/context/service notice bindings; collaboration directory/notices/events/application; security people; projection/notification tests.
**Interfaces:** Produce flat provider-neutral actor facts and immutable notice input; collaboration merges/filter/serializes without pin/thread schemas. Participant callable injection avoids a bidirectional slice import cycle.

- [x] Step 1: Add example and Hypothesis tests for actor extraction and data minimization. Pin records carrying location/note/claim data yield only actor facts; duplicate ordering and agent exclusion preserve current behavior.
- [x] Step 2: Add notification output cases for message id 0, absent/present kind, empty recipients, duplicate recipients and excerpts. Run red tests before changing the adapters.
- [x] Step 3: Extract actors and notice context inside pins, convert at that owned boundary, and remove record traversal from collaboration/security. Keep notification emission timing unchanged.
- [x] Step 4: Run collaboration/security-people and pin editing/lifecycle/trash tests. Expected: actor/candidate and persisted/polled notification contracts pass.
- [x] Step 5: Commit the participant/effect contracts with sign-off and CLA text.

### Task 5: Close pin counts/revision contracts and enforce the surfaces

**Files:** Pin projection/query/revision, documents, revisions core/scope, package exports, `tools/check_boundaries.py`, architecture tests and Handbook topics.
**Interfaces:** Produce pin count/change-token answers and detached revision facts; revisions owns Git/PR close-reference resolution. Remove consumer use of `PinReadView` and broad build surfaces.

- [x] Step 1: Add failing projection/consumer cases for missing pins, moved/renamed paths, stale anchors, multiple close-reference candidates, and change-token stability/change after write.
- [x] Step 2: Move representation decoding to the owner and close-reference matching to revisions. Preserve explicit normal-read/refresh behavior and existing null/error outputs.
- [x] Step 3: Update exact import allowlists and add synthetic negative tests for private imports, indirect boundary paths, cycles and removed broad surfaces, with a same-owner positive case.
- [x] Step 4: Run projection, document, revision, architecture and contract tests. Expected: compatible answers and rejected leaked interfaces.
- [x] Step 5: Synchronize current-state Handbook architecture/code-style/verification/index responsibilities and commit with sign-off and CLA text.

### Task 6: Verify, independently review, update PR and merge

**Files:** Plan evidence, review package, any independently identified fixes and PR description.
**Interfaces:** Consumes the final tree; produces verified PR head and a merge only after CI success.

- [ ] Step 1: Run full pytest, shell instance tests, Ruff/format, ShellCheck, boundary checker, mypy, build/entry-point and Handbook publication checks. Expected: no failures; explain every skip and actual elapsed/count evidence.
- [ ] Step 2: Dispatch one fresh-context whole-branch reviewer as required by executing-plans. Provide spec/plan, review focus, base/head, and ledger rulings; regrade findings by shipped effect and verify important fixes RED→GREEN.
- [ ] Step 3: Recheck remote main and reconcile any subsequent movement safely. Rerun affected checks; never infer an old green run verifies a changed tree.
- [ ] Step 4: Push without force, update PR #115 with actual boundary/evidence changes, and wait for every head CI job. Expected: exact head checks succeed and merge is allowed.
- [ ] Step 5: Merge with a matched head SHA, fetch the actual merged main, and report PR URL, tests, limits and any rulings/deferred minors. No release/deployment.

## Execution rulings and evidence

- Integrated main c5e4003 with signed merge 83d211e; retained figure import/cache/source-check behavior and the P1c release blocker.
- Ruling: tasks 2–5 land as one atomic interface migration. Provider export removal, consumer wiring and the exact boundary allowlist cannot independently remain green; no compatibility facade is kept solely to split commits.
- Red evidence: provider API absent; actor facts nested rather than flat; Notice absent; change-token query absent; retired BuildView/PinReadView imports still accepted. Each gate passed after implementing the corresponding owner contract.
- Removed the dormant pin-owned build-history interpretation as well as live consumers; its source-equivalence/default tests now belong to builds.
- Integrated non-browser/non-TeX regression run: 2,343 passed, 1 skipped, 1,413 subtests. Final full-tree verification and independent review follow in Task 6.
