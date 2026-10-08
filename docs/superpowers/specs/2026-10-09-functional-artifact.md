# Functional artifact scope

The owner authorized continuing the previously approved functional repairs while excluding UX/UI work.
This candidate backports the non-UI portions of merged PRs #218 and #224 onto release `v0.4.20`
(`d21f51819de0ac62edeecc2a739fba50c8455a34`). It reuses their existing-contract approval;
it does not introduce a new design or authorize installation, restart, publishing, tagging, or deployment.

The candidate's package version is `0.4.21.dev1`. It is an unreleased development artifact identified
by its full Git commit, not a released `v0.4.21` or a modified package described as `0.4.20`.

## Authority and constraints

- Purpose / `docs/handbook/purpose.md`: source and tests own product behavior; installed provenance and
  actual version responses own live adoption. A merged change alone does not establish deployment.
- Architecture / `docs/handbook/architecture.md`: keep the single stdlib runtime, feature ownership,
  pin transaction locks, default loopback listener, authentication and existing role grants.
- Verification / `docs/handbook/verification.md`: exercise real files, processes and observable outcomes;
  retain red evidence and report unavailable Linux sandbox coverage without claiming it ran on macOS.
- General topics / `docs/handbook/build-sync.md`, `domain.md`, `operations.md`: recorded-input edits
  reach the PDF; the picker preserves original geometry, score and map schema; socket binding does
  not wait for reverse DNS and keeps configured Host/Origin authority.
- Workflow / `docs/handbook/workflow.md`: contracts and frozen ADRs remain intact; only this branch's
  development version changes. Machine-specific service details and operation logs remain outside the repo.

## Included and excluded behavior

Port recorded-input rebuild repair, guarded thin-element selection and unrelated-branch ranking,
DNS-free IPv4/IPv6 binding, startup-probe diagnostics and bounded child cleanup, exact reviewed
uv/Hatchling pins, and genuine regression/role verification. Test-only unsigned Git fixtures retain
the reviewed deterministic behavior without changing contributor signing settings.

Preserve the entire tracked `src/limn/viewer/` and `src/limn/vendor/` trees from the release base.
Compare packaged runtime bytes with the remote installed release; packaging still excludes tests and
development-only viewer type declarations. PR #219, viewer adoption, proposed workload quotas,
new `429`/`503` behavior, API/state/role changes and manuscript edits are excluded.

The operational baselines differ. This release-based artifact preserves the remote release's viewer.
The local services already run a later main revision with its own viewer. They require a separately
validated backend-only main update that preserves that later viewer; installing this candidate locally
would revert existing UI and is outside this scope. The operator packet records separate targets and rollbacks.

## Acceptance

The corresponding [plan](../plans/2026-10-09-functional-artifact.md) records the work and checks.
The reviewed production patches apply without additional feature imports or transitive backend migration.
Original API and pin snapshots remain compatible. The exact candidate passes applicable standard gates,
isolated package smoke tests, dependency checks and complete viewer/vendor byte checks. Linux sandbox
and remote CI results remain explicit pending gates until the exact candidate has that evidence.

The original-harness measurement gap tracked by #209 remains; this backport does not change that
acceptance criterion or claim a reconstructed experiment is the original measurement.
