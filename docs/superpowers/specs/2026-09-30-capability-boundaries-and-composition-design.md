# Capability Boundaries and Composition Design

Status: approved for implementation

## Intent

Limn already groups production code by capability, but its public package surfaces still expose implementation-shaped
types and helpers. Other capabilities then reconstruct the provider's behavior from those pieces. The composition root
has the same problem at a larger scale: `ServerApplication` combines resource ownership, security adapters, pin
storage, route registration, document selection, startup and shutdown in one object.

This refactor makes capabilities meet through use-case and query contracts and reduces `server.py` to composition and
process lifecycle. It changes no user-visible behavior, HTTP contract, stored data or permission rule.

## Current evidence

- `src/limn/pins/__init__.py` exports 80 names.
- Production capability-to-capability imports consume 64 names in total.
- `src/limn/revisions/core.py` alone imports 20 pin scope values and operations.
- `src/limn/server.py` is 899 lines. `ServerApplication` spans 465 lines with 21 annotated fields and 49 methods.
- `tools/check_boundaries.py` rejects private imports, shared-to-capability paths and cycles, but deliberately accepts
  every name declared by a capability's `__all__`. It therefore enforces visibility without limiting semantic
  coupling.
- The capability-layout refactor did not create the large application object: its parent revision already had an
  876-line `server.py`. The new public imports made the existing coupling more visible.

## Handbook context

### 현재 권위와 상태

- **질문 종류**: 현재 실재 / 현재 계약 / 변경 의도
- **role**: purpose
- **path**: `docs/handbook/purpose.md`
- **실제 정본**: server behavior is the code under `src/limn/` and its tests; HTTP and `pins.md` are additionally
  governed by `docs/handbook/api.md`.
- **확인한 현재값**: behavior and external contracts are already covered by capability tests, repository contract
  tests and the current startup/server tests.
- **role**: architecture
- **path**: `docs/handbook/architecture.md`
- **실제 정본**: the Handbook owns the adopted ownership and dependency rules; the import graph and package exports
  in `src/limn/` are the current implementation.
- **확인한 현재값**: capabilities may import only another capability's package surface, boundary packages must not
  reach capabilities, and `server.py` currently composes all concrete services.
- **role**: 일반 주제
- **path**: `docs/handbook/code-style-roadmap.md`
- **실제 정본**: team skills `code-implement`, `code-testing` and `code-security` own coding policy.
- **확인한 현재값**: entry points only wire; capability slices own their rules, services, handlers, queries, DTOs and
  tests; cross-capability storage, parsers, renderers and helpers must not leak.

### 지켜야 할 현재 불변식

1. HTTP paths, request and response fields, status codes, stable error reasons and `pins.md` remain compatible.
2. Pin writes continue to pass through `PinStore.transact()` and retain their lock, write and notification ordering.
3. Identity, admission, role checks and authority binding remain closed by default and centrally mediated.
4. Runtime, security, platform and common HTTP code do not import capability implementations.
5. Runtime dependencies remain empty and one process owns isolated locks, caches, watchers and cleanup state.
6. Expected business refusals remain values owned and translated by their capability; trust-boundary failures remain
   immediate `HTTPError` refusals.
7. Old state directories and old agents remain readable without a write migration.

### 설계 이유와 제약

- **architecture / `docs/handbook/architecture.md`**: capability ownership keeps code that changes together local;
  public package surfaces define dependency direction; shared packages must not become a route around ownership.
- **일반 주제 / `docs/handbook/code-style-roadmap.md`**: functional decisions remain separate from effects, entry
  points only wire, and abstractions are introduced for an observed boundary rather than shape similarity.
- The standard-library-only runtime, file safety, startup ordering, background-thread ownership and complete
  mediation rules constrain the move. The refactor may relocate and compose code but may not dilute these checks.

### 충돌·미확인

- There is no current contract conflict. The implementation satisfies the existing syntactic boundary rule while its
  public surfaces are broader than the intended information-hiding boundary. This is a design-quality gap rather than
  Handbook drift.
- Exact final export counts depend on type-checking and import-initialization constraints discovered during the move.
  The acceptance rule is semantic and enforced by an explicit crossing allowlist; a numeric count is supporting
  evidence, not the contract.

## Requirements

1. Remove the integrated `ServerApplication` service locator.
2. Keep `server.py` responsible only for argument/configuration handling, subsystem assembly, startup, listening and
   cleanup.
3. Give each capability one assembled subsystem that owns its services, routes and lifecycle hooks.
4. Replace cross-capability helper and domain-internal imports with narrow read, command and sink contracts.
5. Move revision diff parsing, hunk attribution, scoped patch generation and synthetic-tree planning from
   `pins/changes.py` to the revision capability.
6. Reduce every capability `__init__.py` to assembled subsystem entry points and intentional cross-capability
   contracts. Internal stores, parsers, renderers, route constants and helper functions are not package exports.
7. Preserve lazy loading where importing a pure contract must not initialize HTTP adapters or process resources.
8. Extend the architecture checker with an explicit allowlist of capability-to-capability names and composition-root
   imports. Adding a crossing becomes a reviewed architecture change.
9. Preserve all externally observable behavior and all security, persistence and lifecycle invariants.

## Non-goals

- No HTTP, `pins.md`, JSONL or state-file format changes.
- No new state machine, permission, authentication or background flow.
- No viewer behavior or visual change.
- No new runtime dependency.
- No generic dependency-injection container, service registry, mediator or event bus.
- No compatibility copies of internal modules and no deprecated duplicate public surface.
- No broad test rewrite to match implementation structure.
- No performance claim unless measured separately.

## Considered approaches

### Export-only facades

Keep the current ownership and wrap groups of exports in a few facade objects. This would shorten import lists but leave
revision scoping, document summaries and mention decisions assembled by consumers. It treats the symptom and is
rejected.

### Capability subsystems and narrow contracts

Each capability assembles its own services and exposes intent-shaped read, command, route and sink contracts. The
composition root connects these contracts explicitly. This addresses both information leakage and the large
application object without hiding control flow. This is the selected approach.

### Central mediator or event bus

Route every cross-capability interaction through a generic dispatcher. This can reduce static imports but replaces
them with runtime naming, weaker type checking and harder tracing. Limn does not need that indirection and the approach
is rejected.

## Target architecture

### Capability subsystem

Each capability gains an owning `application.py` or equivalently focused assembly module. Its `assemble_*()` function
returns one frozen subsystem value. A subsystem contains only the capability's public roles, for example:

```python
@dataclass(frozen=True)
class PinSubsystem:
    reads: PinReadView
    commands: PinCommands
    routes: PinRoutes
    startup: PinStartup
```

The exact set varies by capability; empty roles are omitted. An assembler receives narrow ports, runtime values and
configuration. It does not read the global server or another capability's internals.

Subsystems do not become generic containers. Their fields are named capability operations with concrete types. Tests
may construct a subsystem or the smaller service under test directly.

### Public surface

A capability package exports only:

- its `assemble_*()` entry point and subsystem value;
- provider-owned cross-capability read/command/sink contracts;
- immutable projection or refusal values required by those contracts.

It does not export storage classes, parsers, render functions, low-level route functions, action dictionaries, path
constants or helper algorithms merely because `server.py` previously assembled them.

The package initializer may retain lazy `__getattr__` loading when it prevents an exported contract from initializing
unrelated adapters. Static declarations remain available to mypy and the boundary checker.

### Cross-capability contracts

| Provider | Contract | Consumer and purpose |
| --- | --- | --- |
| pins | `PinReadView` | documents reads counts by document; collaboration reads people facts; revisions reads one immutable `RevisionPin` projection |
| pins | `PinCommands` | composition-owned startup and explicit feature workflows invoke pin writes without reaching `PinStore` |
| builds | `BuildView` | documents reads page/build summaries; pins reads document/build facts and published stamps |
| builds | `BuildCommands` | sync starts a document build; startup initializes or watches builds |
| collaboration | `PeopleView` | the composition root supplies current people and role callables to security guards and pin assembly; security does not import collaboration |
| collaboration | `NoticeSink` | pin services create and emit committed notices without importing collaboration implementation |
| sync | `SyncStatus` / pull callable | documents reports sync status and builds requests one configured pull |
| each HTTP-facing capability | capability route bundle | the composition root mounts routes without importing path constants or handler functions |

Provider-owned projections contain only facts needed by the named use case. They are not aliases for mutable records,
stores or service objects.

### Revision ownership correction

`pins/changes.py` currently contains two different responsibilities: extracting pin facts and implementing Git-diff
scoping. The target design separates them:

- pins produces an immutable `RevisionPin` containing only the pin identity, document ownership, located source/range,
  anchor state and recorded revision-change facts needed for attribution;
- revisions owns `Block`, `FileChange`, raw Git parsing, hunk attribution, `PinScope`, payload construction and
  synthetic-tree write planning in `revisions/scope.py`;
- revision services request a `RevisionPin` from `PinReadView` and never receive the live pin store or raw pin model;
- revision refusals such as a missing pin for the requested document are owned by revisions because they are revision
  request outcomes.

This keeps pin state interpretation with pins and commit/diff interpretation with revisions.

### Common HTTP application

`web/app.py` becomes a concrete immutable `WebApplication` over narrow boundary ports rather than a protocol matching
dozens of methods on one object. It contains:

- `RequestGuards` for host, origin, identity, admission, read and post authority;
- `DocumentSelector` for request document resolution;
- `RouteRegistry` for GET, document POST, pin action and other POST routes;
- `PeopleRecorder` and `ViewerMessages` for the two common-handler needs.

The common handler imports no capability implementation. Route assembly preserves the existing ordered GET
fallthrough and rejects duplicate keys in keyed POST/action registries before listening.

### Composition and lifecycle

`server.py` performs an explicit top-level sequence:

1. parse and validate access and run configuration;
2. create process runtime resources;
3. assemble people/notices, pins, builds/sync, documents, revisions and viewer subsystems through narrow ports;
4. merge their route bundles into `WebApplication`;
5. execute the existing ordered preparation steps;
6. bind the handler, listen and preserve the current cleanup precedence.

Mutually referring runtime workflows such as build-after-pull are connected through typed callables created at the
composition root. They do not create module import cycles or a generic mutable service registry.

Preparation keeps its observable order: documents are installed, pin sequence and Trash are initialized, builds are
initialized, watchers start when configured, `pins.md` is rendered under the pin lock, state permissions tighten, the
summary is printed and the listener opens. Cleanup keeps socket closure and runtime-thread shutdown semantics.

## Errors and compatibility

- Capability-specific expected refusals remain values and are converted by that capability's HTTP adapter.
- Host, origin, authentication, admission and authority failures remain fail-closed `HTTPError` paths.
- The refactor does not translate exceptions from one capability in another capability.
- Startup refusals remain `StartupRefused` values and `main()` remains the only process-exit boundary.
- Existing Korean messages, stable `reason` values, response key ordering where byte snapshots require it and status
  codes remain unchanged.
- Stored records retain unknown fields and ordering exactly as before.

## Migration sequence

1. Add failing architecture tests for the approved crossing allowlist and composition-root shape.
2. Move revision scoping behind `RevisionPin`/`PinReadView`, retaining output-based scope and comparison tests.
3. Introduce `BuildView`, `BuildCommands`, `PinReadView`, `PeopleView` and `NoticeSink`; migrate one crossing at a time.
4. Add capability assemblers and route bundles while the existing composition root still drives startup.
5. Introduce `WebApplication`, switch the handler binding and remove `ServerApplication`.
6. Remove obsolete exports and tighten the boundary checker to the final allowlist.
7. Synchronize Handbook architecture, code-style and verification responsibilities and run the complete gates.

Every step must leave a runnable application. A moved algorithm is first protected by its existing behavior tests and
new structure test; no behavior assertion is replaced with an implementation call assertion.

## Testing and verification

### Red-green structure tests

- The current public crossing outside the approved allowlist fails before production changes.
- A fixture importing another capability's private module fails.
- A fixture adding an unapproved public name to an otherwise legal crossing fails.
- A boundary package reaching a capability indirectly fails.
- A capability cycle, including package initialization paths, fails.
- A composition-root fixture importing a storage/parser/render helper fails.

Each injected violation is observed failing before the checker is implemented or tightened, then restored.

### Behavior preservation

- Existing revision scope, diff, comparison PDF and refusal tests remain output-based and byte-compatible.
- Contract snapshots cover HTTP bodies and `pins.md`.
- Startup/server tests cover configuration refusal order, partial-start cleanup, two-server resource isolation and
  watcher shutdown.
- Pin tests preserve transaction ordering, corrupt-file handling, Trash expiry and notice emission after commit.
- Import-isolation tests prove that importing public contracts does not initialize unrelated HTTP or runtime modules.
- Test collection and wheel/sdist contents retain the current production/test separation.

### Required gates

Run the repository commands from `AGENTS.md`, including the full pytest suite, instance shell suite, Ruff checks,
format check, ShellCheck, boundary checker and strict mypy. Contract and architecture suites run after each relevant
task; the full suite is fresh before completion.

## Documentation synchronization

The implementation updates these current responsibilities in the same change:

- `docs/handbook/architecture.md`: subsystem ownership, public-contract direction and composition root;
- `docs/handbook/code-style-roadmap.md`: entry-point wiring and cross-capability contract rules;
- `docs/handbook/verification.md`: crossing allowlist and composition-root structure checks;
- `docs/handbook/index.md`: file map entries for capability assembly and boundary tooling.

No ADR is required unless implementation discovers a trade-off that changes an external contract, trust boundary,
persistence format, async lifecycle or another Handbook stop signal beyond this approved refactor.

## Acceptance criteria

1. `ServerApplication` no longer exists.
2. `server.py` imports subsystem assembly/public boundary objects, not pin/build/revision domain helpers or stores.
3. No capability imports another capability's store, parser, renderer, low-level route handler or internal domain
   helper.
4. Every capability-to-capability imported name appears in the explicit reviewed crossing allowlist.
5. `pins.__all__` and the total cross-capability name count are materially smaller than the recorded baseline; the
   exact counts are reported as evidence rather than used as a substitute for the allowlist.
6. Runtime, security, platform and web retain no dependency path into capability implementation.
7. Existing API, `pins.md`, persistence, permission and lifecycle tests pass without compatibility shims.
8. All required local gates pass, or every environmental skip/failure is named without inferring success.
