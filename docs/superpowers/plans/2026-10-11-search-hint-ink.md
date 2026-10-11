# Search shortcut hint formal adoption plan

Scope and approval: [adopted search shortcut hint typography](../specs/2026-10-11-search-hint-ink.md). The owner replied **“고”** after the exact rendered nine-pair PoC and explicit adoption question. Existing authorization covers this precise candidate and PR #236 integration. The prototype remains frozen; new formal records precede source adoption.

## Task 1: Record current authority and approved target

- [x] Step 1: Confirm integration HEAD `6e3d05b068700d0655a6dd1e2a6e10264b67afd9`, refreshed main `ff8ee0d5590aeb05c46aff5e932028f0cee00592`, clean integration state and the four frozen candidate hashes. Expected: same base/target as the supplied review, no prototype edits.
- [x] Step 2: Write the formal spec and this plan before source copy. Preserve the spec's `현재 권위와 상태`, `지켜야 할 현재 불변식`, `설계 이유와 제약`, `충돌·미확인` roles/paths and distinction between existing source, adopted target and external results. Expected: exact owner approval, tradeoff, nine rendered pairs and retained diagnostic limits recorded without fabricated CI/main/physical-device approval.

## Task 2: Adopt the exact frozen implementation and current rules

- [x] Step 1: Copy only `src/limn/viewer/css/search.css`, `.github/workflows/ci.yml`, `docs/handbook/viewer.md`, `docs/handbook/verification.md` from the verified freeze; byte-compare all four afterward. Expected: approved CSS SHA256 `8f83ff4a37e5e92c868404e7daf88ddf19ec8658c45c22d525fa9cde727c0f2b`; one viewer rule plus English reason, unchanged original tests/JS/helpers.
- [x] Step 2: Add an Unreleased/Fixed changelog item for the hint font and PR #236's already established backend fixes. Expected: no version, release, tag or deployment claim; Handbook describes the current rule/reason and exact bounded macOS command, with no experiment timeline. Commit point: one logical adoption commit after review and checks; the orchestrator stages/commits it.

## Task 3: Verify the adopted source without changing the oracle

- [x] Step 1: Run `uv sync --locked --group dev` for this exact worktree. Run the unchanged full `src/limn/viewer/tests/test_viewer_search.py` with required browser/node flags. Expected: search tests collect and pass without skips; real managed browser and fixture server execute against adopted source.
- [x] Step 2: Run the exact `macos-browser` command from `.github/workflows/ci.yml` with both required-tool flags, including the existing fallback-font SearchInk method. Expected: native keys/focus/scope/document/tagging and original hint ink assertions pass at unchanged tolerance.
- [x] Step 3: Run `tests/architecture/test_ci_pins.py`, `test_handbook_refs.py`, `test_naming.py`, applicable source/static checks and scoped diff review. Expected: configured gate/doc/naming contracts pass, byte comparison succeeds and no new CI privilege/credential exposure or excluded source change appears. Install npm before any npm-dependent strict-ratchet check; never share a mypy cache between parallel checks.
- [x] Step 4: Freeze all seven changed/new files, preserved source hashes, full diff and per-command external evidence. Expected: review can reproduce the exact candidate; historical 24 WebKit diagnostic failures remain reported, not relabeled PASS. Commit point: orchestrator uses this freeze only after independent review.

## Task 4: Review, PR CI and actual-main integration (orchestrator)

- [ ] Step 1: Independently compare the seven-file candidate against the formal spec, current Handbook authority and exact frozen prototype bytes. Expected: adopted intent and existing API/storage/authentication/keyboard contracts agree; no broader UI correction or architectural stop signal.
- [ ] Step 2: Refresh target and PR #236 head, reconcile movement with preserved work, commit/push the reviewed adoption and update the PR description around final backend/native-key/hint scope. Expected: reviewed final head is explicit; owner approval and PoC/evidence limits remain correctly attributed.
- [ ] Step 3: Await required CI for that exact new head. Expected: all required checks complete green; unknown or failed checks are not treated as approval.
- [ ] Step 4: Merge PR #236 under existing authorization, fetch main and verify the actual merged source and relevant full gates once. Expected: source identity and actual-main results are retained externally; report real pass/skip/fail limits. No release/version/tag or live-instance update. Retry affected checks only for relevant source/target movement, new failures or missing evidence.
