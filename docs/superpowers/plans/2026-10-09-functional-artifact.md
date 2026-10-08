# Functional artifact work record

Scope and existing approval: [functional artifact scope](../specs/2026-10-09-functional-artifact.md).
This checklist describes candidate preparation, not permission to deploy.

- [x] Confirm fresh upstream and immutable release base; preserve unrelated worktrees and live checkouts.
- [x] Compare both operational viewer baselines and distinguish source exports from packaged assets.
- [x] Port genuine regressions first and observe original build/picker/listener and pin-guard failures.
- [x] Apply only approved functional source patches, test infrastructure and corresponding Korean topics.
- [x] Give this branch truthful unreleased development metadata without a release tag or main release edit.
- [x] Run applicable local gates; after adding a generated score regression, rerun its owning module
  and static checks. Preserve the complete-suite run, cache-isolated type check and measured outputs.
- [x] Build and install in an isolated tool environment; compare every packaged viewer/vendor file and
  verify zero runtime dependencies, startup assets and command entry points.
- [x] Review exact source diff and prepare distinct remote/local operation targets, per-service pilots,
  rollback refs and preserved Tailnet/auth settings.
- [ ] Obtain actual Linux/CI evidence on the exact candidate before approval for remote adoption.

No live package installation, service restart, checkout update, release tag, external issue write,
Tailnet mutation or launch configuration write is part of this checklist.
