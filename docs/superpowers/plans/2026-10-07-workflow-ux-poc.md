# Workflow UX exploration plan

## Approved adoption scope

The user instructed **“수정시안 적용”** after reviewing the last assignee/card
metadata refinement. The approved scope is recorded in the spec's
“Approved production adoption: assignee presentation only” section. Reuse
Task 4 for that scope; pending adoption statements below remain historical for
this presentation and current for all other proposals. This is a target until
implementation and verification complete.

## Assignee presentation refinement tasks (historical)

These tasks use the finite refinement in the existing spec and supersede the
earlier collapsed-only context placement for the current proposal.

- [x] Record the purpose, bounded presentation scope and stop conditions before
  implementation; preserve native behavior and the production review gate.
- [x] Move the original native assignee button/span into one quiet 12px metadata
  line after the visible note. Keep action/tooltip/identity/translation safety,
  remove duplicate assignment, and retain native state badges and controls.
- [x] Run syntax, isolated strict JS types and path-scoped whitespace checks;
  preserve exact output and source hashes outside the repository.
- [x] Inspect collapsed/expanded desktop and compact cards in the native browser,
  checking common baseline, one assignment, edit action, native status controls
  and viewport limits; record root-owned observations before delivery.
  Root checked 390px compact and 1440px desktop: one transparent 12px assignee,
  preserved native edit action, common row baseline and no compact overflow.

No production file, fixture write semantics, assignment/reply rule, dependency,
service configuration or Handbook contract changes in this refinement.

## Earlier narrowed comparison tasks (historical)

These tasks supersede the earlier eight-workflow proposal for the currently
served comparison, using the latest bounded revision in the existing spec.
Prior checked tasks remain historical work, not approval of their designs.

- [x] Record finite purpose, narrowed scope, rejected controls, deferred flows,
  pending assignment semantics and viewport stop conditions before code edits.
- [x] Remove pin search/filter, explicit reply intent, work-start/ETA, separate
  assignment and save-consequence extensions; remove deferred consecutive
  review and location-recovery wrappers while retaining native actions.
- [x] Add direct main document-bar reading/find and collapsed kind/recorded
  assignee/native-status context. Hide the conditional assignee row for the
  new-pin inline-only presentation while leaving native @mention inference
  and native edit controls unchanged.
- [x] Run JavaScript syntax, isolated strict type checks and whitespace checks;
  record exact results and source identities in external operating logs.
- [x] Inspect and capture whole desktop/intermediate/phone viewers, including
  closed/open pin panel and reading/find, measure the phone 44px viewport cost,
  check overflow and touch targets, and record the observations.
  Native-browser checks cover 1440px desktop, 1024px intermediate and 390px
  phone layouts; the review records the actual observed geometry and limits.
- [x] Prepare delivery of the narrowed comparison with confirmed agent no-tag default, pending
  tags-anywhere/first-colleague/multiple-FYI semantics, duplicated phone document
  navigation, fixture mention-write parity limits and physical
  mobile keyboard limits. Production adoption still requires confirmation.
  The final response includes whole desktop and paired phone captures, measured
  costs and verified Tailnet links; user acceptance remains pending.

Scope and adoption boundary:
`../specs/2026-10-07-workflow-ux-poc.md`.

Only this bounded PoC is authorized for the larger workflows. Production
adoption remains pending explicit user review. The smaller production repairs
use their separate approved plan, `2026-10-07-ux-safety-fixes.md`.

The user rejected the first presentation's added upper chrome and design drift.
Revised work uses the actual assembled viewer and the same anonymous examples;
the original checked tasks record the first exploration, not UI acceptance.

## Revision tasks: native-viewer comparison (historical)

- [x] Serve the current assembled viewer and bundled assets through a bounded
  loopback fixture server; intercept demo API responses without forwarding
  production writes or reading a real manuscript.
- [x] Place the eight proposed flows inside the existing native controls/card
  structure; remove all PoC/status/scenario chrome from the application view.
- [x] Compare unchanged navigation/toolbars/typography/card geometry with a
  baseline URL on identical data at desktop and compact widths.
- [x] Exercise the proposal, record captures and simulation limits, and present
  the corrected comparison. Production adoption still requires user review.

## Task 1: Record current authority and exploration boundary

- [x] Step 1: Read the current Handbook roles, relevant viewer/domain code, and
  the user request. Expected: distinguish current rules from proposed controls.
- [x] Step 2: Refresh the target branch and compare with HEAD while preserving
  existing uncommitted repairs. Expected: identify any concurrent movement.
- [x] Step 3: Record scope, questions, invariants, and finite stop conditions in
  the spec. Expected: production UX requires a separate approval.

Commit point: reviewable exploration spec; no commit is requested this session.

## Task 2: Build the working proposal

- [x] Step 1: Implement anonymous local search/work queues, composer, explicit
  reply intent, consecutive review, human work status, and compact card layout
  under `tools/ux-poc/`. Expected: the README scenarios work on demo data only.
- [x] Step 2: Add a synthetic page, reading/search mode, and simulated
  rebuild/reselection with note retention. Expected: no actual manuscript is
  read, and a suggested position needs explicit confirmation.
- [x] Step 3: Include a visible simulation notice and reset control. Expected:
  effects are local, resettable, and do not call production write APIs.

Commit point: finite prototype assets outside `src/`; never merge as runtime.

## Task 3: Review and present

- [x] Step 1: Check JS syntax/types, local asset availability, prototype data,
  labels, keyboard controls, document scope, and side-effect ownership. Expected:
  no new dependency, production import, write endpoint, or persisted demo state.
- [x] Step 2: Inspect desktop and compact layouts with native T3 preview tools.
  Expected: presentation screenshots if available; otherwise clearly record the
  native capture limitation and provide a directly openable local preview.
- [x] Step 3: Document feasibility and remaining limits against current code
  (`viewer/js/`, bundled PDF.js, existing claim/reply/rebuild APIs).
- [x] Step 4: Present the concrete PoC and ask for review of its UX direction.
  Expected: the user can accept or revise the proposal before production work.

Commit point: review evidence and decision request; no implied approval.

The implementation and native-browser observations are recorded in
`../reviews/2026-10-07-workflow-ux-poc.md`. The earlier presentation included
the loopback URL, actual desktop capture and compact-screen evidence. Step 4
records the review request, not acceptance. Task 4 is complete only for the approved assignee presentation.

## Task 4: Adopt approved assignee presentation

- [x] Step 1: Record the actual user instruction “수정시안 적용”, its last-card
  visual reference and exact scope in the existing spec before production edits.
  Expected: human assignee relocation and compact context are approved; main-bar
  reading/find, composer-selector hiding and new assignment/reply rules remain
  outside this approval.
- [x] Step 2: Reassess architecture stop signals against
  `docs/handbook/architecture.md` and preserve the existing screen authority in
  `src/limn/viewer/`. Expected: no changed contract, role, state machine,
  dependency, server/runtime configuration or storage format; no ADR is needed
  for presentation inside the existing viewer boundary.
- [x] Step 3: Implement the approved row in `src/limn/viewer/js/cards.js`,
  `card-parts.js` and `css/cards.css`, with necessary labels in `ui_en.json`.
  Expected: original human assignee action/gating/tooltip/identity appears once
  after the note as 12px normal text; agent is plain text; header author/reply
  count remain; compact kind/status and meaningful expanded native badges work
  without duplicated values. Preserve native composer assignment and all existing
  mention/reply behavior.
- [x] Step 4: Add focused observable regressions in viewer tests and execute
  the existing applicable gates from `docs/handbook/verification.md` and AGENTS.
  Expected: native edit action and identity/role gating, compact collapsed and
  expanded badge visibility, assignment uniqueness, no overflow, fine/coarse hit
  separation and existing composer/mention/reply behavior are verified. Record
  actual failing-before/passing-after or mutation evidence for new tests; existing
  async/conflict recovery and contract checks remain unchanged and must pass.
- [x] Step 5: Root inspects production-derived desktop and compact screens,
  including coarse-pointer emulation, and verifies the final Tailnet HTTPS page
  and assets. Sync `docs/handbook/viewer.md` from the actual implementation and
  update this review with exact checks, source identity and limitations.
  Expected: design intent and current-state Handbook match production, no unrelated
  workflow has been adopted, and every applicable gate has current evidence.

Completion evidence: root's final design/code review is PASS. Required pytest is
3634 passed, 9 skipped, 2534 subtests in 237.40s; administration is 202/0; existing
static/type and Handbook gates pass. Native edit/state/role behavior, single-row
parity, coarse hit separation, final Tailnet HTTPS resources and widths
320/390/768/1440 are verified. The current review records source identity, exact
gates, temporary fallback-font recovery and remaining physical-device limits.

Commit point: one logical assignee-presentation adoption after verification;
no commit, push, PR, release or real-instance deployment is requested. The other
workflow proposals remain pending explicit user review.

## Persistent Tailnet presentation task

The spec appendix records the user's authorization to host the anonymous PoC
persistently on Tailnet HTTPS and configure the harness. This supersedes local
URLs as the presentation default. The original notice/reset tasks above are
historical first-prototype work; the native-viewer correction removes that
extra application chrome. Task 4 uses the later assignee-only confirmation; other production UX proposals remain pending.

- [x] Extend the canonical global and project instructions to require verified
  Tailnet HTTPS links and service-manager persistence; connect the canonical
  instructions to the actual harness home with the narrow dotfiles installer.
- [x] Record the current presentation policy in the Handbook and the bounded
  authorization in the spec, preserving earlier loopback capture evidence.
- [x] Author the external machine LaunchAgent and installer with login start,
  restart after unexpected exit, ownership checks and loopback readiness.
- [x] Add one explicitly validated Tailnet Host option to the anonymous server,
  retaining fixed assets, refused HTTP API reads/writes and loopback binding.
- [x] Complete final boundary and lifecycle verification after all changes,
  install/start the known machine job, and confirm persistent runtime ownership.
- [x] Verify the actual Tailnet HTTPS page and assets in the runtime and native
  browser, then present the user-accessible link with availability limits.

Machine addresses, installed paths, service settings, operational logs and
deployment evidence remain outside the product repository. Login-session
services do not promise availability during logout, power-off or Tailnet loss.
