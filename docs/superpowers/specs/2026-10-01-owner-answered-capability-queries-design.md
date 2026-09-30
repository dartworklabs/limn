# Owner-answered capability queries

Status: direction approved in conversation; written spec awaiting review.

## Intent and success criterion

The user wants a consumer to ask another capability for the information needed to do its job, rather than
importing that capability's domain machinery or reconstructing its answer from storage details. This extends
the capability-boundary refactor in PR #115, not the product's HTTP API or persisted formats.

Success means a provider can change its file layout, record keys, internal models, or map parser without
changing consumers, provided its declared query and effect contracts retain their meaning. Zero imports is
not the target. A facade around the same internal helper inventory is not an acceptable result.

The existing server composition/lifecycle separation stays in place. Documents remains a viewer read-composition
capability, not an independent domain that must duplicate all the information it displays.

## Handbook context

### Current authority and state

- Question kinds: current implementation, current constraints, and proposed change.
- Role: purpose. Path: `docs/handbook/purpose.md`. Actual sources: production code and tests for behavior;
  `docs/handbook/api.md` and the paired agent skills for external contracts; state-directory files for data.
- Role: architecture. Path: `docs/handbook/architecture.md`. Current rules: capability-owned declared surfaces,
  acyclic import paths, no feature dependencies from shared boundaries, entry points that only compose,
  stdlib-only runtime, and pin writes under the existing transaction boundary.
- Role: verification. Path: `docs/handbook/verification.md`. Current evidence sources: output/contract tests,
  boundary checks, strict types, platform/browser/TeX CI, and differential checks for behavior-preserving moves.
- Role: general topic. Path: `docs/handbook/code-style-roadmap.md`. Current rules: pure decisions receive facts,
  storage representations remain private, documentation describes effects and outcomes, and new tests need
  a demonstrated red step or mutation.
- Inspected implementation: PR head `686990829f2561b9753f873be1eddb38170071c4`. It has 17 cross-capability
  imported-name occurrences, including type-only imports. Its `BuildView` exposes 16 methods, documents reads
  build marker files, and collaboration still consumes pin-shaped attribution and notice inputs.
- Refreshed integration target: `origin/main` at `c5e4003`, including PR #117's figure-element pick/pin feature.
  This is newer than the PR's original base `71adbcd`. A read-only merge simulation reports 11 conflicting files.

### Current invariants to preserve

1. Preserve HTTP paths, fields, refusal behavior, notification stream, pin Markdown, and stored records, including
   the figure additions already on main. Do not rewrite older state or add a new persisted projection.
2. Preserve verified identity, document/run-bound mutation authority, read-time manuscript-file checks,
   deny-by-default access, and existing cache bounds and ownership.
3. Preserve transaction ordering and post-commit notification/audit timing. Query-triggered resynchronization
   stays explicit; a new name must not silently make an existing read write or stop its required refresh.
4. Preserve the build selected by the viewer at drag time. Do not replace a requested historical publication
   with the latest publication when its coordinates or figure map are being interpreted.
5. Keep server runtime dependencies empty and Python 3.10 support. No new thread, event bus, worker, or outbox.

### Reasons and constraints

- Role/path: architecture / `docs/handbook/architecture.md`. Ownership keeps one home for each rule; queries
  may cross capabilities, but storage, parsers, and rendering implementations do not become shared code.
- Role/path: verification / `docs/handbook/verification.md`. Structural lint does not establish data minimization
  or behavior preservation; observable contracts and provider/consumer tests establish those separately.
- Role/path: general topic / `docs/handbook/code-style-roadmap.md`. Small explicit facts are preferred to a
  service locator, generic dictionary, or abstractions introduced only to make mocking easier.

### Conflicts and unverified state

- Main's figure work and the existing PR need reconciliation before production edits. No rebase, reset,
  force-push, or conflict resolution has been performed while writing this spec.
- Earlier test evidence applies to the earlier PR tree, not to a reconciled or newly implemented tree.
- The current Handbook describes the broad view contracts. Its description is not evidence that all current
  consumers actually hide provider storage knowledge. Update current-state topics with the implementation.

## Alternatives and selected direction

1. **Owner-answered queries and explicit effect inputs — selected.** Keep existing capability owners and replace
   low-level helper access with consumer-relevant results. This changes internal interfaces but avoids new storage,
   deployment units, and the unnecessary relocation of pin rules.
2. Merge documents/collaboration/build consumers into pins. This reduces some crossings by enlarging pins but mixes
   viewer aggregation, compilation, people persistence, and pin lifecycle rules. It does not meet the intent.
3. Introduce a shared read-model database or generic event/query bus. This adds freshness, ordering, migration,
   and lifecycle costs not justified by the current single-process application.

## Boundary design

### Build facts: answers instead of artifact helpers

Builds owns reading and interpreting its publication directories, marker files, history, build-state records,
page inventory, and parsed figure maps. Replace external use of `BuildView` with these purpose-specific operations:

| Query intent | Consumer | Result contract |
| --- | --- | --- |
| Viewer publication summary | documents | Completed publication/status facts: build identifier, page sizes/count, timestamps, source age/staleness, running phase and last outcome |
| Selected publication assets | pin picking/input | Document-bound assets and redraw/staleness facts for the requested build, not a directory the consumer must search |
| Position-estimation history | pins | Normalized build identifiers and source/publication times, without `builds.json` records or its `by` index |
| Document Markdown header | pins | Published commit and timestamp, with existing missing-value behavior preserved |
| Outline input | documents | Published auxiliary text or an explicit unavailable result; the document owner still parses its own outline rules |
| Figure selection | pins | Chosen element and ordered ancestor/rung facts, score and kind; no `FigureMap`, `MapPage`, `MapElement`, parser, or traversal functions |
| Figure element lookup | pins | Current element/path/geometry facts or an explicit missing/unavailable result for mark and `el_sync` |

Result values have explicit fields and no mutable provider-owned objects. Use frozen dataclasses/tuples or detached
outbound response fragments where that fragment is itself the declared contract. A detached copy of an internal
state/history dictionary is not a projection.

Filesystem paths cross only when an owned adapter must use an asset, such as passing the selected PDF to SyncTeX.
The asset's identity and lookup belong to builds; a consumer cannot derive marker/map/page filenames from it.
An asset path is not manuscript-read authority. Source-file reads retain the existing `ManuscriptFile` boundary.

Keep build-state selection, history decoding, missing marker defaults, and the existing source-newer threshold
inside builds. Keep pin estimation, source tracing, source-range validation, snippets, and pin semantics inside pins.
Keep viewer response composition and outline parsing inside documents. Do not move policies merely to reduce counts.

Do not add an atomic snapshot guarantee that the current implementation does not have: bind versioned assets to
one requested publication, while preserving existing live status and refresh behavior under concurrent builds.

### Pin queries: one answer per consumer need

- Document count queries return document/state totals and the pin change token; documents no longer stats
  `pins.jsonl` or knows how that token is constructed. Preserve the exact existing token format externally.
- Participant queries return an ordered sequence of actor facts, not dictionaries shaped like pin records with
  `author`, `*_by`, or nested `thread.by` fields. Pins owns extracting actors from its lifecycle and thread model.
  Collaboration owns merging people-file facts, excluding agents, and applying existing ordering/precedence.
  Identity facts remain data, never role or mutation authority.
- Revision queries return immutable location, anchor, and recorded-change facts needed for attribution.
  Revisions owns resolving close references against Git/PR history and applying commit-specific scope policy;
  pins does not receive revision-list dictionaries to interpret their `id`/`subject` representation.
- Refresh semantics are part of each query contract. Preserve the existing distinctions between ordinary reads,
  resynchronized counts/candidates, and reads performed while already holding the pin transaction lock.

Remove consumer access to a multi-purpose pin query facade. Prefer concrete functions and independently meaningful
typed results; use a small query bundle only where the same consumer genuinely needs its operations.

### Notifications: completed inputs instead of pin records

Pins owns extracting notice context from the pin/thread transition: event type, pin/document identity, optional
kind, actor, recipients, optional message identity, and optional text. Collaboration receives a declared immutable
notice input and owns recipient filtering, excerpt normalization, event serialization, sequencing, retention, and
polling. Neither collaboration nor security traverses pin records or thread schemas.

Collaboration declares its notice input and sink. Participant reads are injected as a concrete function returning
provider-neutral identity facts, so collaboration does not import pin implementations or create a bidirectional
slice import cycle. Define identity facts in the existing identity boundary only if they are genuinely
provider-neutral; do not introduce a shared package that depends on a capability.

This is an internal input change. Preserve `events.jsonl` fields, optional-field presence, recipient behavior,
ordering and emission after committed pin changes. Do not claim transactional delivery stronger than the existing
file-based implementation or introduce an outbox as part of the refactor.

### Figure functionality already on main

Map parsing, build-scoped map caching, element selection, and map traversal remain build-owned. Pins consumes explicit
selection/lookup projections and owns pin persistence, ladder range checks against current source, and pin status.
Preserve nested/overlapping element selection, label/part normalization, ancestry, shared-part metadata, fallback
reasons, mark/mark_page/el_sync, historical-build behavior, and Markdown regeneration after publication.

Cached map projections do not authorize opening source files. Resolve and check `src.file` at every read, including
warm-cache and symlink-change cases. `impl.file` remains display metadata and is never opened. Do not read a figure
map for a LaTeX document. Preserve main's finite-number/null behavior and rollback fixtures.

### Composition and dependency direction

Server wiring supplies each consumer only its specific queries and effect sinks. It neither interprets result
records nor converts pin records to notice inputs. Those conversions live with the owning feature.

Pure decision code consumes plain facts; it does not receive `BuildView`, `PinReadView`, runtime resources, or a
generic provider object. Effect shells receive the concrete query functions they execute.

Update `__all__`, exact crossing-name allowlists, and entry-point import allowlists together. Keep runtime/security/
platform/web independent of capability implementations, including indirect paths. Internal API removal is permitted:
these Python surfaces are application-owned, not the documented agent HTTP/file contract.

## Integration and scope

Before production edits, reconcile the existing PR with latest main using a deliberate, history-preserving
integration commit on the PR branch, resolving both sides' intent rather than taking one side wholesale. Preserve
the original refactor commits, all figure behavior/tests, branding, rollback and release-blocking changes. No force-push
or branch replacement is needed. If remote main moves again, inspect the new changes and verify the affected behavior.

Scope includes owner queries/results, consuming shells and pure functions, notification mapping, tests, server
wiring, boundary enforcement, and relevant Handbook topics. No new endpoint, format migration, storage file,
background process, runtime dependency, UI redesign, release, or deployment is included. Do not bypass the P1c
release blocker added on main. Keep paired README/agent-skill content unchanged unless integration requires preserving
their upstream changes or the final implementation actually changes their documented contract.

## Acceptance and verification

1. No consumer reads build marker/history/map filenames, traverses raw build-state/history/map objects, or scans
   published page folders. No document consumer reads/statistics pin storage. No collaboration/security code
   interprets pin/thread record keys. Necessary selected artifact and checked source reads remain explicit.
2. Provider projection tests use real temporary state/publication files and assert complete answers, missing/corrupt
   behavior, current versus historical build identity, and absence of raw storage data.
3. Consumer tests use declared result values at the public query boundary and assert HTTP/Markdown/event outputs,
   not calls to private helpers. Demonstrate that equivalent provider storage representations yield the same
   declared answers and that consumers need no internal schema to construct those outputs.
4. Use Hypothesis for participant extraction/data-minimization and normalized projection invariants where applicable.
   Observe red assertions or focused mutations for new regressions; record what each failure proves.
5. Preserve actor precedence, ordered event recipients, refresh effects, zero/missing marker defaults, stale
   thresholds, requested historical PDFs/maps, figure fallback/ladder/position behavior, and all rollback cases.
6. Retain negative checks for private imports, indirect shared-to-feature dependencies, and cycles, plus an allowed
   same-owner import. Add focused enforcement for the removed broad surfaces and identified storage leaks; do not
   present static scans as proof against all dynamic leakage.
7. Run targeted tests and types while editing, then the full project gates once on the reconciled final tree:
   pytest, instance shell tests, Ruff/format, ShellCheck, boundary checker, mypy, package smoke and Handbook checks.
   Remote CI must pass for the exact PR head, including Python/platform/browser/real-TeX jobs, before merge.
8. Report the actual remaining query/result contracts, consumer knowledge, runtime callback relationships,
   import counts and checked limits. A lower export/import count alone is not acceptance evidence.

## Review and handoff

This spec replaces the broad-view interface portion of the earlier design when approved; it preserves that design's
composition/lifecycle work and all external contracts. No new ADR is required for reversible application-internal
interfaces under the existing ownership decision. Any proposed external/security/storage change requires a separate
design decision instead of being smuggled into this refactor.

Self-review: intent, owner responsibilities, hidden callback inputs, upstream figure functionality, read-time
authority, immutable/detached results, behavioral limits, reconciliation, and validation are explicitly covered.
Implementation has not started. After written-spec review, write the checkbox implementation plan and obtain its
review/execution-method choice before production edits, as required by the architectural brainstorming workflow.
