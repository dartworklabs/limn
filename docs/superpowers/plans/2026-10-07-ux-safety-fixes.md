# UX safety repair implementation plan

**Goal:** Implement the narrow production repairs approved in `docs/superpowers/specs/2026-10-07-ux-safety-fixes.md`, keeping larger UX work in the PoC approval path.

**Authority:** Viewer code and `docs/handbook/viewer.md` own presentation; `src/limn/security/access.py` and pin lifecycle own human-only confirmation. Preserve the current API, storage, dependency and transaction invariants from `docs/handbook/architecture.md`. Verification follows `docs/handbook/verification.md`.

**Approval:** The user's current instruction approves proceeding with the diagnosis and requires PoCs before large UX/UI changes. Only the role-affordance, bilingual local quickstart and native keyboard badge repairs are authorized here. Superpowers tooling is unavailable as established by the coordinating agent; record the approved work locally without repeating the approval request.

## Task 1: Verify the role and keyboard regressions

- [x] Step 1: Add colocated real-browser tests in `src/limn/viewer/tests/`, using the real handler and pin store. Cover agent/viewer/human review controls, human confirmation and direct agent refusal; cover Tab/Enter/Space mark navigation without a new selection.
- [x] Step 2: Run the focused tests before changing production code. Expected: agent confirmation affordance and native keyboard mark activation fail on observable assertions; existing viewer restrictions and server refusals retain their behavior.

Logical commit boundary: tests exposing the approved defects. Do not commit or push during this delegated task.

## Task 2: Repair presentation and native keyboard navigation

- [x] Step 3: Gate review card and changes-guide confirmation using the existing person/viewer facts, and present contextual human-review guidance for non-confirming screens. Do not modify `src/limn/security/` or lifecycle authorization.
- [x] Step 4: Replace mark badges with named native buttons, adapt existing badge selectors and reset button chrome while preserving 22px desktop/26px touch geometry and existing hit extensions. Update affected tests' DOM locators without reducing their coverage.
- [x] Step 5: Run focused real-browser tests and affected source/style guards. Expected: role matrix and persisted human confirmation pass, direct agent confirmation stays 403, keyboard mark navigation and existing pointer/touch behavior pass.

Logical commit boundary: viewer behavior and its regression coverage; no new API or state model.

## Task 3: Document and verify

- [x] Step 6: Update both READMEs with distinct local-person and tailscale-sharing starts; synchronize `docs/handbook/viewer.md` with role affordances and button navigation. Keep `docs/handbook/operations.md` authentication policy unchanged.
- [x] Step 7: Run affected authority/browser/translation/source guards, Ruff, `npm run typecheck` and diff checks. Report red/green evidence, files, checks not run and remaining device limits to the coordinating agent.

Logical commit boundary: synchronized documentation and final verification. Larger UX production changes remain blocked on the user's PoC confirmation.

## Validation record

Validated on 2026-10-07 against HEAD `38dc0d7` with the existing authorized uncommitted repairs preserved.

- Initial real-browser regression run before production edits: 4 failed, 1 passed in 8.73s. Headerless local-agent, named agent-role and viewer review cards exposed refused confirm controls; Tab did not reach the inert PDF badge. The existing human confirmation flow was coverage-only green in this initial run.
- Human positive oracle: temporarily making `canConfirmReview()` return false caused the human confirmation test to fail on the visible control assertion (1 failed in 0.99s). Restored the production helper immediately before final checks.
- Final focused role/keyboard and existing pointer/touch regressions: 22 passed, 13 subtests passed in 17.30s. Observations include persisted human confirmation, direct 403 refusal for non-confirming identities, Tab/Enter/Space navigation, desktop badge placement and 24px hit reach, touch controls and selection preservation.
- Existing local-owner and role authorization tests plus viewer source/CSS/i18n guards: 321 passed, 114 subtests passed in 8.59s. `src/limn/security/` and `src/limn/pins/lifecycle/` have no diff.
- `uv run ruff check`, `uv run ruff format --check` on the three affected viewer test files, `npm run typecheck` and `git diff --check` passed.
- Existing badge tests retain their scenarios with native-button locators. One review-card Node harness now extracts the actual newly required role helpers and uses an editor role fixture; no coverage was removed or replaced with a fake policy oracle. The coarse badge-size token has its own declaration so the existing font-scale guard stays intact.

Focused checks are complete. The coordinating agent owns the final repository-wide gates and combined review. No physical iOS device, real tailnet identity transport or non-Chromium keyboard/role coverage is claimed. No commit, push or large UX production change was made.

## Focused qualitative review

The implementation matches the approved specification and plan: confirmation availability reads existing server-provided identity facts, keeps authorization and deferred confirmation authoritative, and offers contextual guidance at both review surfaces. Named native PDF buttons reuse the existing navigation dispatcher, selection exclusions and responsive hit extensions. The README pair and viewer/verification topics reflect the current behavior. No architecture stop signal, new dependency, API/storage change or ADR change applies.

The reviewed content at 2026-10-07 05:42 UTC is identified by SHA-256 `cecde3c72673a9806680d774674eca673d5be87f82b2590c8482dcd9bcf439cd`, computed from each sorted path, NUL, file bytes and NUL: the six affected viewer JS files (`boot`, `cards`, `list`, `revisions`, `selection`, `tooltip`), three CSS files (`components`, `responsive`, `tokens`), `ui_en.json`, three viewer test files (`test_viewer.py`, `test_viewer_input.py`, `test_viewer_role_keyboard.py`), both READMEs and Handbook `viewer.md`/`verification.md`. This identifies the full files, including preserved repairs from other authorized tasks. Test output is retained in the execution session; no separate test-output artifact was produced.

Focused scope: PASS. Repository-wide merge readiness remains with the coordinating agent's final gates; local focused evidence does not replace those gates or remote CI.

The coordinating agent's [combined review](../reviews/2026-10-07-workflow-ux-poc.md)
records the final full-suite result (3,495 tests and 2,517 subtests passed), the
additional legacy-tooltip locator and clear-PDF touch-fixture corrections, and
the unchanged user-confirmation boundary for larger UX production work.
