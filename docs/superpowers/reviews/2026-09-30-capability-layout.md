# Capability layout review

## Scope and outcome

The user authorized a complete source reorganization, including merging the two
pin trees and removing the loose business modules from the package root. This
review covers the PR branch based on upstream `main` at `be283cc` and supersedes
the earlier layout assessment in `2026-09-30-structure-and-tests.md`. The upstream
logo and figure-document work is preserved in the new owners. No deployment was
performed.

`src/limn/` now has four Python files: `__init__.py`, `__main__.py`, `cli.py` and
`server.py`. The PR base has 25. Business code belongs to eight capability
packages. All pin values, storage, transactions, location calculations, rendering
and request handling live under one `src/limn/pins/`. The old `features/` and
`service/` namespaces are removed, without compatibility copies.

Pin subdirectories are operations inside one aggregate, not independent slices
sharing a second pin domain. Existing operation modules remain separate where
their decisions, persistence effects and HTTP concerns change for different reasons.

## Ownership and imports

| Owner | Changed files and responsibility |
| --- | --- |
| `src/limn/pins/` | Existing pin domain and feature modules merged; `store.py`, `context.py`, `mentions.py` and `changes.py` moved here. Location owns `mapping.py`, `lookup.py` and `position.py`; listing owns `render.py` and `projection.py`; editing owns `values.py`. |
| `src/limn/builds/` | Existing build feature plus `artifacts.py`, `values.py`, `document_facts.py`, `figure.py` and `figure_map.py`. `answer.py` owns build failure descriptions previously in the shared HTTP module. |
| `src/limn/collaboration/` | Existing collaboration feature plus event persistence. Pin event vocabulary and mention decisions are consumed through the public pin surface. |
| `src/limn/documents/` | Document tab, meta and outline capability, including its tests. The runtime document resource is distinct from this query capability. |
| `src/limn/revisions/` | Existing revision feature moved intact; `answer.py` now owns the scope refusal table and mapping previously in shared HTTP. |
| `src/limn/sync/` | Existing synchronization feature; build state is read through the build capability's public operation. |
| `src/limn/administration/` | Existing administration feature plus `instances.sh` and `systemd/limn@.service`. CLI resource paths and shell includes use these destinations. |
| `src/limn/viewer/` | Existing HTML/CSS/JS and assembly plus serving routes, `mark.py`, the unchanged brand assets in `brand/`, `ui_en.json` and tests. UI behavior and translation contents are preserved. |
| `src/limn/runtime/` | Arguments, frozen configuration, startup and document resources, including document-kind suffix registration. `paths.py` holds the existing fixed state locations, including `PinFiles`; it creates no new stored format. |
| `src/limn/security/` | Existing access control, authority values, people facts, audit persistence and authentication guidance. No permission or identity policy changes. |
| `src/limn/platform/` | Four business-independent modules: `files.py`, `git.py`, `values.py`, `text.py`. Text normalization was already consumed by startup, pins and events; numeric predicates were already consumed throughout the application. |
| `src/limn/web/` | Common transport remains here. It no longer imports build or pin implementations; the application protocol requests viewer messages rather than a concrete viewer type. |

Production imports between capabilities are:

- collaboration → pins;
- documents → builds and pins;
- pins → builds;
- revisions → pins;
- sync → builds.

Every crossing uses a declared value or operation. Concrete feature modules are
not exposed as public module objects. The composition root also imports public
surfaces. Root and pin operation exports load lazily, preserving the ability to
import pure values without initializing HTTP adapters. Runtime, security, platform
and common HTTP have no dependency path into a capability.

## Tests and enforcement

Feature, runtime, security, platform and HTTP tests live with their owning code.
The repository-level test tree retains contracts, architecture, support, data and
test-tool checks. Existing source tests and repository-root tests follow their owners, including the
figure map, figure import, document registration and region-pin tests added upstream.

`pyproject.toml` collects `tests` and `src/limn`, uses importlib collection and four
xdist workers with `loadscope`, excludes all colocated tests from the wheel and
keeps every production module under strict mypy. CI commands and its package asset
checks follow the relocated shell, systemd and viewer resources.

`tools/check_boundaries.py` checks eight capability owners. It rejects private
imports, dependency paths from boundary code to capabilities, cycles, empty source
discovery, loose root business modules and undeclared production packages. The same
command gates CI lint; `tests/architecture/test_boundaries.py` verifies detection.
Its existing cases still exercise direct private imports, indirect shared paths,
cycles including package initialization, allowed internal imports and generated
indirection lengths.

Three new layout cases failed before the unowned-source rule was implemented and
passed afterward. Two existing diff tests now run real Git commits larger than the
production limit instead of patching an imported constant. The process test wraps
the owned process adapter while running real Git and inspects its OS exit status;
it does not assert a call to the internal termination helper. Raising the cap caused
the truncation assertion to fail; replacing SIGKILL with SIGTERM caused the process
exit assertion to fail. Both mutations were reverted.

Collection comparison against the PR base preserves all 2,154 test nodes and adds
13 boundary checks, with no duplicate IDs. Two parameter IDs change with their
import paths. `tools/test_id_map.py` reports zero unmapped differences; an exact
file-and-node mapping independently preserves every upstream node, including the
four class/test keys the tool reports as ambiguous. The final favicon rebase adds
one upstream test; the current comparison reports zero unmapped differences.

## Handbook and contracts

The current authority remains code and configuration for behavior, `api.md` and the
agent skill for agent contracts, and state files for stored data. The Handbook
catalog retains its purpose, architecture and verification roles.

`docs/handbook/architecture.md` describes the capability ownership, dependency
direction and separation of pure decisions from effects inside a capability.
`index.md` has a responsibility map rather than a copied full file tree.
`verification.md` describes colocation, collection, packaging and the new layout
guard. Current topic links, `AGENTS.md`, `CONTRIBUTING.md` and CI references follow
the real paths. Scope and build refusal tables are documented at their feature
owners. Historical ADRs are untouched.

The HTTP paths, response fields, status names, refusal text, pin JSONL and Markdown
formats, transaction ordering and authority scope checks remain covered by the
existing contract and security suites. No runtime dependency, state machine,
permission grant or stored file format was added.

## Verification

| Check | Evidence | Limit |
| --- | --- | --- |
| Full suite before final favicon rebase | `uv run pytest -q -rs --durations=10`: 2,155 passed, 11 skipped, 1,270 subtests; 182.96 seconds | Ten TeX/sandbox cases lack local tools; one real-state-copy case lacks its opt-in fixture. |
| Python 3.10 core before final favicon rebase | `uv run --isolated --python 3.10 --locked pytest -q -rs -m 'not browser and not tex'`: 2,015 passed, one skipped, 1,151 subtests; 68.79 seconds | Browser and TeX suites excluded by the CI marker. |
| Instance shell | `bash src/limn/administration/tests/test_instances.sh`: 195 passed, zero failed | Real systemd and tailscale are replaced at the owned shell boundary. |
| Final favicon rebase | Brand/browser assets, packaged viewer, HTTP routes, runtime startup/server and architecture: 246 passed, one TeX skip, 316 subtests; 6.93 seconds | Final rebase preserves upstream favicon behavior. Installed Python 3.10 wheel and Handbook checks rerun successfully. |
| Focused Python 3.10 | Map parser, registration and build outcomes: 51 passed, 104 subtests; 10.35 seconds | Rerun after removing the parser's unnecessary runtime import. |
| Static checks | Ruff: zero errors; 368 files formatted. ShellCheck: zero diagnostics. Mypy: 138 production modules, zero issues. Boundary checker and `git diff --check` pass. | Dynamic import strings remain a review concern. |
| Packaging | Wheel and sdist built; a clean Python 3.10 environment installed the wheel. Version, serve version, serve help, CLI help, viewer assembly, translations and required assets pass. Wheel excludes tests; sdist includes validation tooling and support. | No published release. |
| Handbook | Publisher check and standalone HTML build pass. | Remote CI results are reported on the PR separately. |

Validation initially found a parser purity violation, fixed by keeping the document
suffix in runtime registration and removing the unused parser import. The first
concurrent Python 3.10 run also returned a failed build in a one-second fake-tool
test; the isolated test and focused outcome suite pass on rerun. This does not
establish a speed improvement over the preceding layout.

## Applied references and assessment

Applied `code-implement` references: Python, structure, format and integration.
Applied `code-testing` and its Python reference, `code-security`, Handbook read,
guard, synchronization and review, plus Handbook formatting style. Implementation
references were read before source changes. The Handbook style reference was loaded
at final review to verify current-tense prose and responsibility routing.

The user's source ownership and test organization requirements are satisfied in
the PR branch. Applicable local gates pass within the limits above. Browser
behavior is covered by the full suite; the visual layout was not changed. Remote
CI and production operation are not inferred from these results. Existing untouched
tests still include legacy implementation-coupled assertions; this reorganization
does not claim complete conformance of every existing test to the current skill.
