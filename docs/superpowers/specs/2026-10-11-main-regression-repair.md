# Main regression repair scope

## Request and authority

The user requested **“테스트해서 개선해”** after the current-main diagnosis reported four backend defects and local browser-test failures. This document records the requested repair of existing contracts. It does not claim that the user approved a new design, changed API, security policy, storage format, or UI. The existing contracts below bound implementation; any required contract change stops for a separate decision.

## Current authority and state

| Role | Path | Current authority |
| --- | --- | --- |
| purpose | `docs/handbook/purpose.md` | Code and tests define runtime behavior; Handbook defines contracts and verification |
| architecture | `docs/handbook/architecture.md` | Slice ownership, stdlib-only server, security boundaries and stop signals |
| verification | `docs/handbook/verification.md` | Assertion-based red/green evidence, managed dependencies, CI gates and reporting limits |
| build behavior | `docs/handbook/build-sync.md`, `src/limn/builds/engine.py` | Published external-document artifacts describe one completed build |
| pin behavior | `docs/handbook/domain.md`, `src/limn/pins/` | A malformed stored record is isolated; valid records remain readable and writes use `transact()` |
| agent contract | `docs/handbook/api.md`, `src/limn/security/access.py` | Invalid bearer credentials are denied; routes, fields and storage formats remain compatible |
| viewer behavior | `docs/handbook/viewer.md`, `src/limn/viewer/tests/` | Apple search uses Command+F; other platforms use Control+F; geometry tolerances remain unchanged |

The diagnosed base is current main `ff8ee0d5590aeb05c46aff5e932028f0cee00592`. Its Linux CI browser gate does not supply native macOS browser evidence. Local macOS failures include incorrect test keyboard inputs and two unchanged fallback-font hint measurements whose cause requires investigation.

## Existing invariants to restore

1. Each external-document render uses one immutable PDF generation for rendered pages, named downloadable PDF and successful source fingerprint. Source replacement during rendering must not publish a mixed pair; a subsequent watcher pass can recover the new source.
2. Local timestamp parsing returns a usable timestamp or `None` for malformed, non-finite or platform-unrepresentable input; valid existing formats remain supported.
3. An unencodable stored pin row does not prevent valid rows from loading or the next locked write. Existing corrupt-backup rules isolate it while valid legacy and unknown fields remain supported.
4. A malformed non-strict token store denies bearer access with the existing `401` result. Strict CLI validation continues to refuse invalid stores.
5. Browser fixtures send the key required by the stated platform and move the caret to the intended location before typing/deleting. Behavioral assertions remain intact. Native macOS browser coverage exercises the actual platform rather than only an injected `navigator.platform`.

## Reasons and constraints

The PDF pair and source fingerprint must describe the same generation because users and agents consume both. Parser failures must stay at the existing rejection boundary so one malformed persisted input cannot make unrelated reads fail. Browser tests must test the advertised native controls; synthetic platform fixtures remain useful for explicit cross-platform contract checks but do not prove native behavior.

No runtime dependency, route, field, status name, stored filename or record format is added. The build temporary implementation is private and preserves the existing `.part` publication contract. Pin writes retain their locking order; identity and role policy remain unchanged. Auth, workload/admission activation, deployment, release and operational publishing are outside this request. Existing approved ADRs are not edited.

## Scope limits and unresolved measurements

Production viewer JS, CSS and templates, manual browser navigation and PoC work are excluded by the user's continuing scope. Existing automated browser tests may run. The two search-hint ink measurements keep their current `0.5px` oracle: investigation can distinguish fixture/oracle and product causes, but cannot silently change expected values, skip tests or implement a UI correction. Any remaining UI defect is reported separately and keeps its observed failure status.

## Acceptance and evidence

Each repair has genuine assertion red on the diagnosed base and green on the changed source, using real files, managed processes, Poppler/browser tools where the risk requires them. Pure parser invariants use generated inputs. No retries, inflated deadlines, quarantine or fake rendered output count as repair. Focused native macOS browser CI runs with required-tool flags and existing pinned actions/read-only credentials; Linux browser coverage remains present. The full gates, skip reasons and unexecuted remote CI remain the integration reviewer's responsibility. Local focused green does not establish merge readiness or all-device UI correctness.
