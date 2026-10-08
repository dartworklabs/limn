# Non-UI follow-up plan

This plan tracks the owner's authorized existing-contract work in the
[scope record](../specs/2026-10-08-non-ui-followups.md). It does not authorize the separate workload-policy
proposal or any UX/UI adoption. Implementers preserve the scope record's authority paths, invariants,
reasons and unresolved decisions. Each task is one reviewable logical change; the root combines related
tasks into the requested PR after inspecting raw evidence. Workers do not commit or push independently.

## Task 1: Build-role HTTP verification

- [x] Step 1: Read `security/access.py` and Handbook `api.md` role contracts. Expected: document existing
  rebuild and comparison grants without changing policy or runtime routes.
- [x] Step 2: Add `security/tests/test_build_access.py` beside its owning boundary. Expected: real requests,
  Git/files/locks/workers, denied-request filesystem and publication snapshots, plus real TeX PDF checks.
- [ ] Step 3: Review focused execution and source-mutant evidence. Expected: assertions expose weakened
  rebuild/comparison permissions; tool-dependent PDF success runs under the TeX gate or is expressly unverified.
- [ ] Step 4: Root confirms integration and logical commit boundary. Expected: production permission source,
  viewer assets and HTTP/pin snapshots remain unchanged.

## Task 2: CI tool/backend pins

- [x] Step 1: Pin every existing `setup-uv` invocation in `.github/workflows/ci.yml` and Hatchling in
  `pyproject.toml`. Expected: exact reviewed versions; no new runtime dependency or credential exposure.
- [x] Step 2: Extend `tests/architecture/test_ci_pins.py` at its current ownership boundary. Expected:
  missing/floating uv and backend declarations fail, alongside existing action SHA and checkout guards.
- [ ] Step 3: Inspect mutation evidence, installation smoke and static checks. Expected: every job uses the
  selected pin and isolated wheel installation succeeds with required assets and no collected test files.
- [ ] Step 4: Root confirms exact CI revision and logical commit boundary. Expected: remote CI success is
  reported for this branch rather than borrowed from main or the stopped draft UX PR.

## Task 3: Preserve startup-failure evidence

- [x] Step 1: Inspect the real-server probe in `administration/tests/test_token_file.py` and its failed CI
  evidence. Expected: separate actual failure mechanisms from generic timeout symptoms.
- [x] Step 2: Keep per-test child stdout/stderr, exit/interpreter details and a stack dump before the existing
  readiness deadline; use that child's listener marker and bounded terminate/kill/reap cleanup. Expected:
  one actual startup attempt, no false success from another listener, retry loop or increased timeout.
- [x] Step 3: Remove reverse DNS from `web/handler.py` socket binding and add adapter-owned IPv4/IPv6
  listener regressions. Expected: a failing resolver cannot prevent an actual listener response; real bind
  errors and configured Host/Origin authority remain intact.
- [ ] Step 4: Inspect red/green and real-server regression evidence. Expected: invalid startup reports the
  actual refusal, and existing token/loopback response cases keep their intended assertions.
- [ ] Step 5: Root links unresolved historical CI mechanism to #221/#223. Expected: diagnostics do not falsely
  claim the earlier flake cause has been repaired merely because a rerun is green.

## Task 4: Measurement and operations evidence

- [x] Step 1: Recover the map from historical producer Git data without running producer code. Expected:
  hash matches the prior review, root/non-root and usable-page counts reconcile with ADR-0015.
- [x] Step 2: Replay `tools/measure_figure_pick.py` twice on identical seeded samples. Expected: identical
  output, improvements and cohort regressions recorded, original 59,492-drag generator kept distinct.
- [x] Step 3: Compare the tool's frozen rule with actual pre-repair picker source. Expected: no chosen-element
  mismatches across the reconstructed sample pool; no claim of original-generator equivalence.
- [x] Step 4: Read installed provenance and actual Tailnet HTTPS `/api/version` for known services. Expected:
  no tokens/manuscripts/pins required; uv-tool and source-backed service impacts recorded outside the repository.
- [x] Step 5: Prepare explicit adoption/rollback alternatives. Expected: whole-package viewer adoption blocked
  while #220 is stopped; no service update/restart, source deployment change or release marker mutation.
- [x] Step 6: Complete narrowly authorized original-harness recovery in producer/temporary/session evidence. Expected:
  extract measurement scripts only; keep #209 open unless original acceptance or an explicit acceptance change
  is evidenced. Root owns any remote issue mutation.

## Task 5: Documentation, integration and review

- [x] Step 1: Update Handbook `verification.md`, `code-style-roadmap.md` and `operations.md` from actual worker
  source. Expected: role build matrix, diagnostic limits, CI pins and listener DNS behavior are current;
  principal workload-policy gaps remain.
- [x] Step 2: Run Handbook reference checks and inspect documentation links/privacy markers. Expected: no broken
  source/section targets, actual personal paths/hosts, progress dates or per-run counts in Handbook topics.
  Replace the two workflow directory links with the existing ADR index file; preserve the tracked catalog
  and frozen numbered records. Pinned publisher link checking and HTML build pass.
- [ ] Step 3: Root inspects the complete diff and relevant standard gates. Expected: tests, contract snapshots,
  boundaries, linters, both mypy platforms, install smoke and unchanged-viewer checks pass or remaining failures
  are clearly named. No new tests merely mirror implementation.
- [ ] Step 4: Recheck main freshness, open the reviewable non-UI PR and await its exact remote CI. Expected:
  preserve the existing dirty workspace/draft UX branch; do not widen scope to unapproved policy or UI work.
- [ ] Step 5: Close only originally satisfied issues and report remaining gates. Expected: #209 acceptance gap,
  #222 proposed policy, deployment/version distinction and any unresolved CI diagnosis remain explicit.

Full task outcomes, mutation/red evidence and gate measurements belong in reviews and the PR. Checkboxes
describe observed task status, not design approval, release approval or deployed state.
