# Non-UI follow-up scope

## Authority and intended result

The owner's current instruction authorizes closing verified resolved issues and completing unfinished
non-UX/UI work. UX/UI remains stopped in [#220](https://github.com/dartworklabs/limn/issues/220).
This document records that agreed task scope and its existing-contract verification points. It does not
approve a new security policy, change #209's acceptance criteria, or authorize live adoption of viewer changes.

The base is main `b1487ecd6ea7cdb3e424df1f7e662f7e49049bee`. Preserve the historical dirty workspace and
the separate draft [PR #219](https://github.com/dartworklabs/limn/pull/219); neither supplies code to this work.

## Current authority and state

- **Question type:** current contract and current implementation.
- **role / path: purpose / `docs/handbook/purpose.md`.** Product behavior comes from source; installed package
  metadata and live `/api/version` determine operational adoption. Merged changes and deployed changes differ.
- **role / path: architecture / `docs/handbook/architecture.md`.** Feature ownership, standard-library runtime,
  transaction writes, and default loopback/security boundaries remain unchanged.
- **role / path: verification / `docs/handbook/verification.md`.** Tests observe outcomes and effects, new
  regressions expose their failure, and a missing managed dependency is reported rather than replaced silently.
- **role / path: general topic / `docs/handbook/code-style-roadmap.md`.** Existing role permissions are the
  oracle. Principal workload limits and connection bounds are known gaps, not approved new policy.
- **role / path: general topic / `docs/handbook/workflow.md`.** Contract/security/storage behavior changes
  require explicit design approval; historical approved ADRs are frozen; unreleased metadata is not a release.

## Invariants to preserve

1. Keep HTTP paths, fields, status/reason contracts, stored pin records, `pins.md`, authentication, and role grants.
2. Rebuild remains permitted for owner/editor/agent and denied for viewer. Comparison remains permitted for all
   admitted roles. Rejected requests have no manuscript, state-file, directory, or publication effects.
3. Preserve source/state ownership, document locks, managed process lifetimes, and runtime dependencies `[]`.
4. Preserve every runtime viewer, translation, stylesheet, and brand asset in this follow-up.
5. Keep historical measurement evidence and current acceptance separate; do not substitute a reconstructed
   experiment for the original harness without an explicit acceptance decision.
6. Keep machine-specific operator data outside the repository; inventory does not grant deployment authority.

## Included work

| Area | Result and observation |
| --- | --- |
| Build permission coverage | Co-located HTTP tests exercise synchronous/asynchronous rebuilds, comparison workers, admitted roles and denied identities. Denial preserves source/state bytes and build state; real TeX cases verify actual PDF publication. |
| CI toolchain | Pin the existing uv installer version and Hatchling build backend, retain existing action SHA/credential rules, and make the architecture guard fail for a missing or floating tool/backend version. |
| Server-probe diagnostics and startup | Preserve each real child's stdout/stderr, exit status, interpreter and a pre-deadline stack dump without retries or a longer readiness allowance. Confirm that child's own listener, reap it through bounded terminate/kill cleanup, and remove reverse DNS from IPv4/IPv6 socket binding without changing Host/Origin authority. Preserve actual authentication and instance-adapter checks. |
| Measurement reconciliation | Recover the producer map, reconcile root/non-root counts, replay the checked-in tool deterministically, verify its frozen legacy rule against actual pre-repair source, and record original-harness recovery limits. |
| Operational inventory | Read package provenance and actual HTTPS version responses, distinguish uv-tool and source-backed services, and prepare explicit restart/rollback impacts without executing them. |
| Documentation and issue reconciliation | Reflect actual verification in the Handbook; close only items whose original acceptance has evidence. Track incomplete CI diagnosis and unapproved workload policy separately. |

## Design reasons and constraints

- **role / path: verification / `docs/handbook/verification.md`.** Real HTTP responses and filesystem effects
  verify security intent; worker-start or internal-call assertions alone do not prove permission outcomes.
  TeX/sandbox success belongs to the real-tool gate rather than a fabricated successful build.
- **role / path: general topic / `docs/handbook/code-style-roadmap.md`.** Exact tool/backend versions close
  installation variability outside the development lockfile. Pins identify reviewed versions; they do not
  claim every downloaded distribution byte is authenticated.
- **role / path: general topic / `docs/handbook/operations.md`.** The listener's bound address identifies its
  socket independently of reverse DNS; configured Host/Origin checks still own request authority. Removing
  a blocking display-name lookup preserves the existing bind/auth contract and is independently reproducible.
- **role / path: general topic / `docs/handbook/workflow.md`.** New resource refusals and deadlines change
  security/API behavior. They remain a separate proposed design requiring explicit approval.

## Excluded work and unresolved decisions

No UX/UI implementation, physical-device verification, PR #219 merge/adoption, manuscript edits, production
service restart/update, release tag, or conversion of 0.4.21 Unreleased to a released version is included.
Whole-main adoption would also introduce PR #218's merged but not yet deployed viewer changes; it is outside
this non-UI instruction while the stop remains active.

[#209](https://github.com/dartworklabs/limn/issues/209) retains its same-original-harness acceptance gap.
[#221](https://github.com/dartworklabs/limn/issues/221) and [#223](https://github.com/dartworklabs/limn/issues/223)
track CI/server-probe diagnosis. [#222](https://github.com/dartworklabs/limn/issues/222) and the separate
[workload-limit proposal](2026-10-08-backend-workload-limits.md) retain the unapproved policy decision.
No new ADR is needed for the existing-contract tests and diagnostics; a policy implementation would require
its own approval and decision record.

## Acceptance

Focused tests and source-mutant/red evidence establish the added observations. The final relevant standard
gates and CI run on the exact proposed revision. Handbook source/section links remain valid and describe
present behavior without progress dates or per-run metrics. Review records contain measured outcomes,
unavailable tools and unresolved gates. No remote issue is marked complete from inferred adoption or a waived
criterion. The [audit](../reviews/2026-10-08-non-ui-measurement-operations.md) owns measurement/adoption evidence;
the [plan](../plans/2026-10-08-non-ui-followups.md) owns task tracking.
