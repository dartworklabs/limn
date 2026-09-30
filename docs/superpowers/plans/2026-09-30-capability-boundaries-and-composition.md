# Capability Boundaries and Composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace implementation-shaped capability crossings with narrow query/command contracts and remove the integrated `ServerApplication` service locator without changing observable behavior.

**Architecture:** Each capability assembles one typed subsystem containing its reads, commands, routes and lifecycle hooks. `server.py` connects those subsystems to a concrete boundary-only `WebApplication`; an explicit allowlist makes every capability crossing reviewable.

**Tech Stack:** Python 3.10+ standard library, dataclasses and Protocols, unittest/pytest, Hypothesis architecture tests, Ruff, mypy, ShellCheck.

**Spec:** `docs/superpowers/specs/2026-09-30-capability-boundaries-and-composition-design.md`

## Global Constraints

- Preserve every HTTP path, request/response field, status code, stable reason, Korean contract message and `pins.md` byte contract.
- Preserve `PinStore.transact()` locking/write/notification order and old state-directory compatibility.
- Preserve complete mediation, fail-closed access behavior and authority scope binding.
- Preserve startup refusal order, watcher ownership, partial-start cleanup and socket/thread cleanup precedence.
- Keep runtime dependencies empty and shared `runtime`, `security`, `platform` and `web` code free of capability imports.
- Do not add a generic container, registry, mediator, event bus or compatibility copy.
- Write code, comments, docstrings and commit messages in English; write Handbook changes in Korean.

## Review Focus

- A pin-scoped revision whose stored absolute paths moved must still resolve through the current locator and select the same hunks; Task 2 keeps and extends the moved-checkout test.
- A figure document whose map names a PDF must keep returning that PDF for both pick and parser facts; Task 3 covers current and historical page directories.
- A malformed `people.json` must remain fail-closed while pin-derived people are unavailable; Task 4 exercises the unreadable-file path through `PeopleView`.
- Partial startup after one watcher begins must stop that watcher exactly once and preserve the first refusal; Task 6 retains the failure-order test.
- Importing one public read contract must not initialize route/HTTP modules; Tasks 3, 4 and 7 add import-isolation assertions.

---

### Task 1: Make Approved Crossings Enforceable

**Files:**
- Modify: `tools/check_boundaries.py`
- Modify: `tests/architecture/test_boundaries.py`
- Test: `tests/architecture/test_boundaries.py`

**Interfaces:**
- Consumes: existing `owner()`, `imports()` and `violations()` import-graph analysis.
- Produces: `violations(code, packages, crossings=None, entrypoint_imports=None)` with optional exact-name allowlists; production enforcement remains disabled until Task 7.

- [ ] **Step 1: Write failing synthetic allowlist tests**

Add tests whose in-memory modules declare a valid public surface but import an unapproved public name, and whose entry point imports a domain helper instead of its approved assembly symbol:

```python
errors = violations(code, packages, {("limn.alpha", "limn.beta"): {"BetaView"}}, {"limn.server": {"assemble_beta"}})
self.assertIn("limn.alpha.use: unapproved crossing limn.beta.BetaHelper", errors)
self.assertIn("limn.server: unapproved composition import limn.beta.BetaHelper", errors)
```

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `uv run pytest -q tests/architecture/test_boundaries.py -k 'allowlist or composition_import'`

Expected: FAIL because `violations()` has no allowlist parameters and reports neither diagnostic.

- [ ] **Step 3: Implement optional exact-name enforcement**

Add typed `CrossingKey`, `CrossingNames` and `EntrypointImports` aliases. Record every cross-owner `from limn.<capability> import <name>` and every entry-point capability import. When the optional mapping is supplied, reject names not present for that source/target pair. Keep existing private import, shared-path and cycle checks unchanged.

- [ ] **Step 4: Prove the checker catches mutations and preserves existing behavior**

Run: `uv run pytest -q tests/architecture/test_boundaries.py`

Expected: all boundary checker tests pass, including existing generated-path and package-initializer cases.

- [ ] **Step 5: Commit**

```bash
git add tools/check_boundaries.py tests/architecture/test_boundaries.py
git commit -m "Enforce reviewed capability crossings"
```

### Task 2: Move Revision Scoping to Its Owner

**Files:**
- Create: `src/limn/pins/revision.py`
- Create: `src/limn/revisions/scope.py`
- Modify: `src/limn/pins/record.py`
- Delete: `src/limn/pins/changes.py`
- Modify: `src/limn/revisions/core.py`
- Modify: `src/limn/revisions/execution.py`
- Modify: `src/limn/revisions/answer.py`
- Modify: `src/limn/pins/__init__.py`
- Modify: `src/limn/revisions/__init__.py`
- Modify: `src/limn/revisions/tests/test_revisions.py`
- Modify: pin record/scope tests under `src/limn/pins/tests/` and `tests/contracts/`

**Interfaces:**
- Consumes: stored pin records and current path locator.
- Produces: `RevisionPin` and `revision_pin()` in pins; `revisions.scope` owns `Block`, `FileChange`, `PinScope`, parsing, attribution, payload and write planning.

- [ ] **Step 1: Add a failing ownership and projection test**

Add a pin test for:

```python
projection = pin_revision(record, relative_path="paper/main.tex", head="a" * 40, revisions=history)
assert projection.id == record["id"]
assert projection.changes == (("paper/main.tex", 10, 12),)
```

Add an architecture assertion that `revisions` no longer requires `Block`, `FileChange`, parsers or scope helpers from `limn.pins`.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest -q src/limn/pins/tests src/limn/revisions/tests/test_revisions.py tests/architecture/test_boundaries.py -k 'revision or crossing'`

Expected: FAIL because `RevisionPin` does not exist and revision scoping is still pin-owned.

- [ ] **Step 3: Separate pin projection from revision algorithms**

Move `ChangeRecord` validation and pin-record interpretation into `pins/revision.py`. Define immutable `RevisionPin` with id, relative file/range, stale flag, anchor facts and commit-filtered recorded changes. Keep unknown stored fields in the record layer; the projection copies only inputs needed by revision attribution.

Move Git diff values, parsing, hunk attribution, scoped patch rendering, scope metadata and synthetic-tree planning into `revisions/scope.py`. Make `PinNotInDoc`, unsafe/mismatch/unreadable/unwritable refusals revision-owned.

- [ ] **Step 4: Rewire revision core and execution**

Replace the large pin import with `RevisionPin`/`revision_pin`. Keep current locator application before repository-relative conversion. Update tests to import revision-owned scope values from `limn.revisions.scope`, not through the pin package.

- [ ] **Step 5: Verify byte-compatible revision and record behavior**

Run: `uv run pytest -q src/limn/revisions/tests src/limn/pins/tests tests/contracts/test_contract_snapshot.py tests/contracts/test_pbt_invariants.py`

Expected: all selected tests pass; moved-checkout, binary, rename, root-commit, scoped PDF and stored-record cases retain their outputs.

- [ ] **Step 6: Commit**

```bash
git add src/limn/pins src/limn/revisions tests/contracts
git commit -m "Move revision scoping into revisions"
```

### Task 3: Replace Build Helpers with Build Views and Commands

**Files:**
- Create: `src/limn/builds/application.py`
- Modify: `src/limn/builds/service.py`
- Modify: `src/limn/builds/__init__.py`
- Modify: `src/limn/builds/document_facts.py`
- Modify: `src/limn/documents/reads.py`
- Modify: `src/limn/documents/service.py`
- Modify: `src/limn/pins/context.py`
- Modify: `src/limn/pins/editing/service.py`
- Modify: `src/limn/pins/listing/markdown.py`
- Modify: `src/limn/pins/location/input.py`
- Modify: `src/limn/pins/location/lookup.py`
- Modify: `src/limn/pins/location/resolve.py`
- Modify: `src/limn/sync/run.py`
- Modify: corresponding tests under `src/limn/builds/tests/`, `documents/tests/`, `pins/**/tests/`, and `sync/tests/`

**Interfaces:**
- Produces: concrete stateless `BuildView` for reads, `BuildCommands` around `BuildRequests`, and `BuildSubsystem(view, commands, routes, startup)` from `assemble_builds()`.
- Consumers import only `BuildView` or receive `BuildCommands`/callables from composition.

- [ ] **Step 1: Write failing BuildView contract tests**

Test current pages, page metadata, historical PDF selection, figure-map PDF, state snapshot, source freshness, build stamps and last-failure through one `BuildView` instance. Add an import-isolation test asserting `from limn.builds import BuildView` does not load `limn.builds.http` or route adapters.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest -q src/limn/builds/tests -k 'view or import'`

Expected: FAIL because `BuildView` and `assemble_builds()` do not exist.

- [ ] **Step 3: Implement BuildView and BuildSubsystem**

`BuildView` delegates to the current artifact/figure functions without caching or changing I/O. `BuildCommands` exposes build, initialization, watch and authority operations already owned by `BuildRequests`. `assemble_builds()` owns route binding and returns the subsystem.

- [ ] **Step 4: Inject BuildView into consumers**

Pass one view through `DocumentViews`, `PinContext`, `PickContext`, `PinMarkdown` and sync context. Replace helper imports with method calls such as `builds.current_pages(doc)`, `builds.snapshot(doc)` and `builds.figure_pdf(doc, build)`. Pass `last_failed` and build-start callables to sync rather than importing build modules there.

- [ ] **Step 5: Verify build, document, pick, listing and sync behavior**

Run: `uv run pytest -q src/limn/builds/tests src/limn/documents/tests src/limn/pins src/limn/sync/tests tests/contracts`

Expected: all selected tests pass, including figure document facts and historical pick builds.

- [ ] **Step 6: Commit**

```bash
git add src/limn/builds src/limn/documents src/limn/pins src/limn/sync tests/contracts
git commit -m "Expose build reads through one capability view"
```

### Task 4: Introduce Pin and Collaboration Boundary Views

**Files:**
- Create: `src/limn/pins/application.py`
- Modify: `src/limn/pins/context.py`
- Modify: `src/limn/pins/mentions.py`
- Modify: `src/limn/pins/__init__.py`
- Create: `src/limn/collaboration/application.py`
- Modify: `src/limn/collaboration/directory.py`
- Modify: `src/limn/collaboration/notices.py`
- Modify: `src/limn/collaboration/__init__.py`
- Create: `src/limn/documents/application.py`
- Modify: `src/limn/documents/service.py`
- Modify: `src/limn/documents/__init__.py`
- Modify: `src/limn/revisions/core.py`
- Modify: affected tests in pins, collaboration, documents and revisions

**Interfaces:**
- Produces: `PinReadView`, `PinCommands`, `PinRoutes`, `PinStartup`, `PinSubsystem`, `assemble_pins()`; `PeopleView`, `NoticeSink`, `CollaborationSubsystem`, `assemble_collaboration()`; `DocumentsSubsystem`, `assemble_documents()`.
- `PinReadView` returns pin-owned projections/JSON facts, counts, people facts and `RevisionPin`; it does not expose `PinStore` or mutable pin objects.

- [ ] **Step 1: Write failing consumer-facing view tests**

Cover `counts_by_document()`, `state_counts()`, `people_records()`, and `revision_pin()`. Test unreadable `people.json` through `PeopleView` remains fail-closed and excludes agents. Add import-isolation tests for `PinReadView` and `PeopleView`.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest -q src/limn/pins src/limn/collaboration/tests src/limn/documents/tests src/limn/revisions/tests -k 'view or people or revision_pin'`

Expected: FAIL because the views and subsystem assemblers do not exist.

- [ ] **Step 3: Implement pin reads without leaking models or storage**

Bind existing store/location/projection behavior behind `PinReadView`. Keep transaction-capable services under `PinCommands`. Move note-tag policy back under pins; give it recent event rows and people facts through callables. `NoticeSink` creates/emits events but never imports pin types.

- [ ] **Step 4: Migrate collaboration, documents and revisions**

Make `PeopleDirectory` consume `people_records()` rather than `Pin` values. Make document views consume pin count/query methods rather than `Pin`/`Record`. Replace revision context's raw pin list and document-key callbacks with `PinReadView.revision_pin()`.

- [ ] **Step 5: Verify pin, people, document and revision contracts**

Run: `uv run pytest -q src/limn/pins src/limn/collaboration/tests src/limn/documents/tests src/limn/revisions/tests tests/contracts`

Expected: all selected tests pass; notice emission remains after committed writes and malformed people data remains closed.

- [ ] **Step 6: Commit**

```bash
git add src/limn/pins src/limn/collaboration src/limn/documents src/limn/revisions tests/contracts
git commit -m "Bind capability consumers to narrow pin views"
```

### Task 5: Assemble Every Capability Behind Route Bundles

**Files:**
- Create or complete: `src/limn/revisions/application.py`
- Create or complete: `src/limn/sync/application.py`
- Create or complete: `src/limn/viewer/application.py`
- Modify: `src/limn/administration/__init__.py`
- Modify: capability `__init__.py` files
- Modify: `src/limn/web/routes.py`
- Modify: route registration tests in each capability and `src/limn/web/tests/`

**Interfaces:**
- Produces: `RouteBundle(get, post_documents, pin_actions, other_posts)` and `merge_routes()` in web; one `assemble_*()` per HTTP-facing capability.
- Consumes: the views/commands from Tasks 3 and 4 and explicit deferred callables for build/pull and pin/people cycles.

- [ ] **Step 1: Write failing route-bundle tests**

Test stable GET fallthrough ordering and rejection of duplicate document POST paths, pin action names and other POST paths. Test every capability assembler returns only its public subsystem and route bundle.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest -q src/limn/web/tests src/limn/*/tests -k 'route_bundle or assembler or duplicate'`

Expected: FAIL because route bundles and remaining assemblers do not exist.

- [ ] **Step 3: Implement RouteBundle and remaining assemblers**

Move current route/action construction from `ServerApplication.__post_init__` into owning capability application modules. Preserve GET route order. `merge_routes()` rejects duplicate keyed routes while leaving ordered GET dispatch intact.

- [ ] **Step 4: Verify assembled route behavior**

Run: `uv run pytest -q src/limn/web/tests src/limn/builds/tests src/limn/pins src/limn/collaboration/tests src/limn/documents/tests src/limn/revisions/tests src/limn/viewer/tests`

Expected: route and HTTP response tests pass with unchanged bodies and status codes.

- [ ] **Step 5: Commit**

```bash
git add src/limn/administration src/limn/builds src/limn/collaboration src/limn/documents src/limn/pins src/limn/revisions src/limn/sync src/limn/viewer src/limn/web
git commit -m "Assemble capability routes at their owners"
```

### Task 6: Replace ServerApplication with Boundary Ports

**Files:**
- Create: `src/limn/runtime/resources.py`
- Create: `src/limn/security/application.py`
- Modify: `src/limn/web/app.py`
- Modify: `src/limn/web/handler.py`
- Modify: `src/limn/server.py`
- Modify: `src/limn/runtime/tests/test_server.py`
- Modify: `src/limn/runtime/tests/test_startup.py`
- Modify: `src/limn/web/tests/test_web.py`
- Modify: `tests/support/helpers.py`

**Interfaces:**
- Produces: `RuntimeResources`; boundary-only `RequestGuards`, `DocumentSelector`, `RouteRegistry`, and concrete frozen `WebApplication`.
- Removes: `ServerApplication` and its 49-method service-locator surface.

- [ ] **Step 1: Write failing application-shape and lifecycle tests**

Add an AST assertion that `server.py` defines no `ServerApplication` and imports no names outside the approved composition surface. Add/retain runtime assertions for two isolated servers, one started watcher followed by startup failure, repeated stop, listen refusal and cleanup-error precedence.

- [ ] **Step 2: Observe RED**

Run: `uv run pytest -q src/limn/runtime/tests src/limn/web/tests tests/architecture/test_boundaries.py -k 'application or server or startup or cleanup'`

Expected: structure assertions fail while existing lifecycle behavior remains green.

- [ ] **Step 3: Move process resources and access adapters**

Move locks, caches, stop event and thread registry to `runtime/resources.py`. Build `RequestGuards` in `security/application.py` from settings and people/token callables without importing collaboration. Keep authorization decisions in `security/access.py`.

- [ ] **Step 4: Implement concrete WebApplication**

Replace method-shaped `App` with a frozen value containing guards, selector, routes, recorder and viewer messages. Update the handler to delegate through those ports. Preserve the handler's guard and dispatch order.

- [ ] **Step 5: Rewrite server.py as explicit composition and lifecycle**

Keep parser/configuration, viewer loading, `start()` and `main()`. Assemble subsystems with local typed deferred callables for build/pull and pin/people relationships, execute the existing prepare order, bind `WebApplication`, listen and clean up. Delete `ServerApplication` and wrapper methods.

- [ ] **Step 6: Verify server, access and HTTP contracts**

Run: `uv run pytest -q src/limn/runtime/tests src/limn/security/tests src/limn/web/tests tests/contracts src/limn/pins tests/support`

Expected: all selected tests pass; structure assertion confirms the mega-class is absent.

- [ ] **Step 7: Commit**

```bash
git add src/limn/runtime src/limn/security src/limn/web src/limn/server.py tests/support tests/contracts tests/architecture
git commit -m "Reduce the server to composition and lifecycle"
```

### Task 7: Close Public Surfaces and Synchronize the Handbook

**Files:**
- Modify: every capability `src/limn/*/__init__.py`
- Modify: `tools/check_boundaries.py`
- Modify: `tests/architecture/test_boundaries.py`
- Modify: `docs/handbook/architecture.md`
- Modify: `docs/handbook/code-style-roadmap.md`
- Modify: `docs/handbook/verification.md`
- Modify: `docs/handbook/index.md`
- Modify: packaging/import tests as required

**Interfaces:**
- Enables production `CROSSING_NAMES` and `ENTRYPOINT_IMPORTS` exact allowlists.
- Removes all obsolete helper/domain exports and compatibility aliases.

- [ ] **Step 1: Enable the final allowlist and observe remaining RED crossings**

Use the approved graph:

```python
{
    ("limn.collaboration", "limn.pins"): {"PinReadView"},
    ("limn.documents", "limn.builds"): {"BuildView"},
    ("limn.documents", "limn.pins"): {"PinReadView"},
    ("limn.pins", "limn.builds"): {"BuildView"},
    ("limn.revisions", "limn.pins"): {"PinReadView", "RevisionPin"},
}
```

Run: `uv run python tools/check_boundaries.py`

Expected: FAIL listing every leftover crossing, with no hidden private-import or cycle diagnostic.

- [ ] **Step 2: Remove obsolete exports and imports**

Delete package exports unused by the final subsystem/query contracts. Keep lazy loading only for final public names that need it. Remove stale aliases and update import-isolation/type-check tests.

- [ ] **Step 3: Update Handbook current responsibilities**

Document capability subsystem ownership, exact cross-capability contracts, concrete `WebApplication`, composition-only `server.py`, the allowlist gate and its limitations. Update the index file map; keep prose current-tense and avoid line counts or migration progress.

- [ ] **Step 4: Run focused structural and contract verification**

Run:

```bash
uv run python tools/check_boundaries.py
uv run pytest -q tests/architecture tests/contracts src/limn/runtime/tests src/limn/web/tests
uv run mypy
uv run ruff check
uv run ruff format --check
git diff --check
```

Expected: every command exits zero.

- [ ] **Step 5: Run complete repository verification**

Run:

```bash
uv sync --group dev
uv run pytest -q -rs
bash src/limn/administration/tests/test_instances.sh
uv run ruff check
uv run ruff format --check
uv run shellcheck src/limn/administration/instances.sh src/limn/administration/instance_*.sh src/limn/administration/tests/test_instances.sh
uv run python tools/check_boundaries.py
uv run mypy
```

Expected: all commands exit zero; environment-dependent skips are reported by name and not generalized beyond their evidence.

- [ ] **Step 6: Record before/after evidence and commit**

Report final `__all__` sizes, cross-capability imported-name count and `server.py`/composition shape without turning numeric counts into future contracts.

```bash
git add src tools tests docs/handbook
git commit -m "Close capability surfaces and document composition"
```
