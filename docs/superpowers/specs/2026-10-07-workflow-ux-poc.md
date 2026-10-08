# Workflow and viewer UX proof of concept

## Approved production adoption: assignee presentation only

Approval evidence: after reviewing the actual mobile and desktop card crops and
Tailnet comparison, the user instructed **“수정시안 적용”**. This approves the last
assignee/card metadata refinement for production. It supersedes pending adoption
statements below only for this presentation; other workflow proposals retain
their recorded approval status.

Accepted behavior: move the existing human assignee button/span from the header
to one quiet metadata line after the visible note, with neutral 12px normal
text and aligned baselines. Preserve its resolved identity, tooltip,
`translate="no"`, native `data-act="edit"` behavior and existing button/span
identity and permission gating. Render the agent default as plain noninteractive
text in that line. Keep author, reply count and collapse in the header. Compact
collapsed cards expose kind, assignee and relevant native status; expanded cards
retain meaningful question/review/claim/reopen/location-warning badges and their
actions, with duplicated summary values shown only while those badges are hidden.
The accepted visual reference is `tools/ux-poc/native.js` and `native.css` at the
last assignee refinement, rather than the complete proposal variant.

Scope: presentation in `src/limn/viewer/js/cards.js`, `card-parts.js` and
`css/cards.css`, necessary UI translations, focused behavioral/browser
regressions and `docs/handbook/viewer.md` synchronization. The no-tag default is
already agent. Assignment/mention resolution, leading-tag inference, tags
anywhere, first-colleague/multiple-FYI rules and reply behavior do not change.
Do not adopt main-bar reading/search or hide the new-pin assignment selector.
Do not change API/storage contracts, roles, server security, daemon configuration,
runtime dependencies or unrelated workflow controls.

Current authority and state: purpose / `docs/handbook/purpose.md` identifies
`src/limn/viewer/` and viewer tests as the screen authority; viewer /
`docs/handbook/viewer.md` currently documents the header human-assignee chip.
Architecture / `docs/handbook/architecture.md` owns additive API/pin contracts,
standard-library runtime and unchanged trust boundaries. Verification /
`docs/handbook/verification.md` owns existing regression, browser, static/type
and Handbook publication gates. The approval is a target until production edits
and checks establish the actual behavior.

Current invariants: preserve assignment identity/edit gating, native state
badges/actions and existing mention/reply semantics; no server or wire/storage
change. Design reasons and constraints: viewer / `docs/handbook/viewer.md`
requires compact cards to communicate their work context while keeping the
header readable; the accepted neutral line expresses assignment once. Retaining
native badges preserves review/claim/warning meaning and native hit utilities
preserve fine/coarse input reach. Verification /
`docs/handbook/verification.md` requires behavior and observed screen evidence;
viewport emulation does not prove physical-phone or screen-reader behavior.
Conflicts/unverified: production rendering, role gating, collapsed/expanded
visibility and touch-hit separation must be checked after adoption; the earlier
PoC evidence is visual-reference evidence, not proof of production parity.

Reuse Task 4 of the existing plan, recording this approval before implementation.
The existing narrower context and checks remain valid; no new architecture or
separate broad workflow implementation is authorized.

Adoption result: Task 4 is complete for this scope. Production source and current
Handbook are aligned, and the current review records passing design, behavior,
browser and required gates. Other workflow proposals retain their pending status.

## Assignee presentation refinement: finite exploration (historical)

This is the current proposal's presentation scope. It supersedes the earlier
collapsed-only context placement recorded below.

Purpose: compare the existing blue header assignee chip with a quiet, left-aligned
metadata line below the note. The current variant preserves the actual native
chip; the previous proposal repeated its assignment in collapsed context.

Scope: remove that repetition by moving the existing native button/span into
one metadata line, without cloning it or replacing its native edit action.
Keep its tooltip, resolved identity and `translate="no"` text. Use neutral
12px text with a common baseline and hover/focus edit affordance. Agent
assignment is plain noninteractive text. Expanded question, claim, review and
warning badges retain their meaningful native information; the metadata does
not repeat those values while the badges are visible. Header author and reply
controls, native actions, document reading/find and current assignment rules
retain ownership. No new badge, background, control strip or product source
change belongs to this exploration.

Stop: one bounded implementation and any necessary correction, followed by
syntax/strict JS/whitespace checks and root-owned desktop/compact browser
inspection of row alignment, single assignment, edit action and native state
visibility. Preserve raw evidence outside the repository. This comparison does
not establish production deployment parity, end-to-end fixture mention/reply
semantics, physical mobile gestures or screen-reader usability. Production
adoption still requires review and explicit confirmation.

The resulting comparison shows one assignee in a plain note-level line. Root's
native browser inspection confirms 12px text, a common baseline, no compact
overflow and the relocated native edit action. At 390px, the compact card is
75.5px rather than the native current 57.5px or prior proposal 74px. Expanded
ordinary cards gain 22px for the line; meaningful question/review/claim badges
remain native. These measured presentation costs do not approve production
adoption or establish physical-touch and assistive-technology behavior.

## Earlier bounded revision: document reading and collapsed pin context (historical)

This revision follows the user's review of eight comparison captures. It is
another finite anonymous exploration under the existing PoC authorization,
not approval to adopt the proposed workflows in production. This section
supersedes the earlier exploration scope for the currently served proposal;
the observations below remain historical evidence of prior variants.

Purpose: judge body search and selectable reading from the main document top
bar, together with meaningful kind/assignee/status context on collapsed pins,
in the whole desktop and mobile viewer rather than isolated control crops.

Scope: keep the actual native viewer, reply controls and inline @mentions.
Remove the rejected pin search/filter group, explicit reply-intent controls,
human work-start/ETA controls, explicit assignee row/popover choices and save
consequence preview. Consecutive review and rebuild/location recovery have
not been accepted; defer both and remove their proposal controls/wrappers.
Do not add or assume new assignment semantics: the no-tag assignment default
is confirmed as agent (the existing default), while new @mention assignment
semantics remain pending. The native frontend computation stays in place. Existing native controls are retained.

Body find/read entry points are directly visible in `#doc-nav`, the main
document navigation, rather than More or the pin-panel toolbar. Desktop
navigation keeps its existing 44px height. On narrow layouts the comparison
may retain a condensed 44px document top bar because native document
navigation is hidden there; measure and disclose the resulting PDF viewport
cost. Native bottom location navigation remains, so document selection is
available at both ends on the phone. This duplication is an explicit comparison
tradeoff. The proposed inline-only presentation hides the conditional native
assignee row while preserving its inference. The no-tag default is confirmed as agent. The
requested tags-anywhere assignment rule and first-colleague/multiple-FYI details
remain pending; no reply rule changes. This inline-only presentation concerns
new pins; native edit assignment retains ownership. Fixture writes do not prove
server-side typed-mention resolution/storage parity.
Do not add PoC status, scenario or separate presentation chrome.

Stop conditions: present and inspect whole-view comparisons at 1440px desktop,
1024/768px intermediate widths and 390px narrow width, with the pin panel
closed/open and reading/find closed/open as relevant. Verify direct entry,
keyboard find navigation, exit back to PDF, collapsed summaries and absence
of rejected/deferred extensions. Record the mobile top-bar cost, overflow,
simulation limits and pending assignment decision before requesting review.
Physical mobile keyboard and coarse-pointer tablet behavior remain unverified
by width-only desktop browser captures.
No production source, API, Handbook, hosting configuration or fixture-backend
change belongs to this revision. Production adoption still requires review
and explicit confirmation.

The narrowed comparison's native-browser result is recorded in the review:
desktop bars retain their heights, intermediate 44px controls fit the bar,
phone top controls and labels fit without horizontal overflow, the phone PDF
loses 44px of visible height, and collapsed cards gain 16.5px for context.
Find/read and resolved-colleague autocomplete were exercised on authored sample
data. These results provide a reviewable comparison; production adoption and
the remaining @assignment details are not confirmed.

## Authorization and approval boundary

The user authorized all improvements in the workflow/interface diagnosis and
explicitly required a working PoC, presentation, and confirmation before
implementing changes with substantial UX/UI impact. Earlier authorization for
dynamic agent allocation remains applicable.

The small repairs to role-appropriate confirmation controls, local-human
onboarding, and keyboard navigation have their own approved scope in
`2026-10-07-ux-safety-fixes.md`. The larger workflow changes below remain
**proposed**, pending review of this PoC. Completing or running the PoC does not
approve production implementation.

The external `superpowers:brainstorming` and `superpowers:writing-plans` skills
are unavailable in this project. The local architecture skills and explicit
user authorization govern this bounded exploration and its records.

## Handbook context

### 현재 권위와 상태

- **질문 종류**: current implementation and proposed UX change.
- **role**: purpose; **path**: `docs/handbook/purpose.md`.
  **실제 정본**: `src/limn/viewer/` and its browser tests. Limn connects PDF
  selections to source locations and collaboration pins.
- **role**: architecture; **path**: `docs/handbook/architecture.md`.
  **실제 정본**: the topic's invariants and stop signals. The packaged viewer
  uses plain JS/CSS, bundled PDF.js, and no frontend build step.
- **role**: viewer; **path**: `docs/handbook/viewer.md`.
  **실제 정본**: `index.html`, CSS, `js/list.js`, `mentions.js`, `reply.js`,
  `revisions.js`, `pdf-draw.js`, and browser tests. Current pin lists lack a
  text search; assignment/reopening defaults depend on mentions; confirming a
  review exits the changes view; canvas rendering has no text layer.
- **role**: domain; **path**: `docs/handbook/domain.md`.
  **실제 정본**: pin rules and tests in `src/limn/pins/`. Open/review/done are
  existing states; claim is an expiring indication, not a lock or new state.
- **role**: API; **path**: `docs/handbook/api.md`.
  **실제 정본**: this topic's additive-only wire/storage contracts.
- **role**: verification; **path**: `docs/handbook/verification.md`.
  **실제 정본**: the topic's gates and observed browser evidence.
- **role**: workflow; **path**: `docs/handbook/workflow.md`.
  **실제 정본**: bounded exploration must record questions, scope, stop
  conditions, results, and approval before production adoption.

### 지켜야 할 현재 불변식

1. Keep server identity, role permissions, loopback binding, and Host/Origin
   enforcement unchanged. Only a human with edit permission confirms reviews.
2. Preserve API routes/fields, pin record format, and open/review/done states.
   Use existing explicit reply/assignment/claim controls when adopted.
3. Preserve server-authoritative revision checks and bind confirmation to the
   close actually shown. Consecutive review still requires a click per pin.
4. Keep draft and selected-location ownership across async visits. A rebuilt
   PDF cannot silently approve a previous selection's new source location.
5. The PoC reads and modifies only anonymous, in-memory demo data. It must not
   load manuscript files, authenticate to a real instance, or submit API writes.
6. Add no runtime dependency or frontend build step. PoC assets stay under
   `tools/ux-poc/`, outside the packaged runtime.

### 설계 이유와 제약

- **role / path**: purpose / `docs/handbook/purpose.md`: reduce location and
  handoff costs; keep PDF, source context, and tasks adjacent.
- **role / path**: viewer / `docs/handbook/viewer.md`: keep the familiar desktop
  outline/PDF/pin structure and neutral visual hierarchy. Region selection
  conflicts with normal text selection, so reading mode must be explicit.
- **role / path**: domain / `docs/handbook/domain.md`: preserve separate
  execution and human review. Stale source/PDF warning is informative today;
  provide a recovery path without discarding notes or silently relocating pins.
- **role / path**: verification / `docs/handbook/verification.md`: browser
  viewport checks do not establish physical-phone or screen-reader usability.

### 충돌·미확인

- PDF extraction can have an imperfect reading order or no text for figures.
  Mock reading results demonstrate interaction only, not extraction fidelity.
- Native preview capture/interaction availability must be checked and results
  reported without substituting an unapproved browser tool.
- A user review is required for the larger flows. No elapsed timeout substitutes
  for this approval.

## Exploration questions, scope, and stop conditions

Build one finite, interactive desktop/mobile PoC to answer whether users can:

1. Find a pin by number/text/assignee and distinguish current-document scope
   from all-document scope; filter all/my work/my reviews/in progress with counts.
2. See and choose request kind and assignee before saving, including from the
   selection-local composer; mentions remain notification recipients.
3. Reply to a closed pin with an explicit intent: discussion only or request
   another change, with state/assignee consequences visible before sending.
4. Inspect a result and choose confirm or confirm-and-next, without approving
   the next result automatically.
5. Recover from a stale PDF through rebuilding and explicitly checking a
   suggested position while retaining the note.
6. Indicate human work in progress and ETA, extend it, or release it with the
   semantics of the existing claim API.
7. Switch to a distinct reading/search mode and reach a result via keyboard
   without competing with region-selection gestures.
8. Understand a compact mobile card's type, assignee, and most relevant status
   without opening every card.

The PoC uses a synthetic page and seeded anonymous pins. Search/filter,
composer/reply intent, review advancement, claim/ETA, and rebuild/reselection
must be locally interactive. The README and presentation identify the
simulation; reload resets its in-memory data. Keep visual changes localized to
the relevant controls, without additional prototype chrome.

Stop exploration when these scenarios work, desktop and compact viewport layouts
are inspected, limitations are recorded, and reviewable artifacts are presented.
Do not add backend features, ship the mock PDF/text, redesign unrelated
navigation, or implement the proposed larger flows in `src/` before approval.

## Acceptance for presentation

- The user can open the persistent Tailnet HTTPS preview and run all eight scenarios.
- Controls expose understandable labels, focus, and state changes.
- Search/filter counts, empty states, and scope reflect the demo data.
- Confirmation advances only after confirming the shown pin.
- Rebuild demonstrates note retention and requires another position check.
- Desktop and compact screenshots, or an explicit capture limitation, accompany
  the review request. The final approval request names the concrete proposal.

## Production implementation after approval

Record the accepted/revised proposal, then create the implementation plan with
tasks and acceptance checks. Use existing APIs where possible. Any discovered
need for changed permissions, wire/storage contracts, external dependencies, or
a new state machine returns to the architecture stop/approval path.

## Exploration result (historical)

The first independent prototype demonstrated the interactions, but the user
rejected its presentation: the extra PoC/status/scenario rows and expanded upper
controls changed the actual viewer's density and prevented a reasonable design
decision. Its captures are historical exploration evidence, not an accepted UI.
No production adoption decision is recorded.

## Revised exploration: preserve the actual viewer (historical)

Authorization: the user's requested correction applies within the existing
bounded PoC. The production approval gate remains unchanged. Read-only current
authority is the packaged `src/limn/viewer/index.html`, its assembled CSS/JS,
bundled Pretendard/Lucide, and `docs/handbook/viewer.md`.

The revised comparison serves the real assembled viewer with anonymous fixture
data. It preserves the existing document navigation, compact tool/meta rows,
outline, panel sizing, card structure, fonts, icons, colors, and responsive
layouts. It adds only the proposed controls at their actual interaction sites.
There is no PoC status bar, scenario navigation, large task-dashboard heading or
permanent reading toolbar. Demo/reset/comparison instructions live in the README
and review response; baseline/proposal URLs use the same data and viewport.

The browser's fixture adapter supplies only seeded anonymous responses and
local demonstration effects. The dedicated loopback server serves an allowlist
of the assembled viewer, bundled assets, sample page and prototype additions;
it has no production instance credentials or manuscript/state access. No
production write request is forwarded. Existing mock assets may supply sample
text/geometry, but they are not shipped or presented as extraction accuracy.

Finite stop conditions: inspect and capture the baseline and revised proposal
at the same desktop/compact sizes; measure identical unaffected navigation and
toolbar geometry; verify all eight existing scenarios at their actual native
controls; document simulations/limits; and present the comparison for user
confirmation. Production adoption remains pending.

### Revised exploration result (historical)

The dedicated comparison now uses the actual viewer assembly and bundled
PDF.js, Pretendard and Lucide, with a real anonymous Korean sample PDF. The old
independent HTML/CSS/JS/SVG prototype has been removed. The fixture reproduces
the native short Git head display instead of forcing an artificial metadata
wrap. All eight proposed flows are locally interactive at the native sites.

Native T3 browser measurements at 1440 × 900 show zero geometry delta for the
ten unaffected shell/page elements: document navigation 44px, tool row 45px,
metadata row 61.59375px, outline 240px, right panel 348px and page origin
(290, 98) with width 780px. Body/button fonts and a representative unchanged
card height match. The corresponding closed-panel measurements at 390 × 844
also match exactly; the PDF starts at (12, 12), width 366px, and the native
bottom tool row is 52px.

The browser exercised search/scope, explicit assignment and local save, closed
reply intent, confirmation with native undo, rebuild/location confirmation,
claim/ETA extension/release, reading/search and compact-card information.
Selection setup called the actual native pick command from the preview because
the available T3 tools do not expose pointer dragging; this is not physical-drag
evidence. Rebuilding and source/diff results remain authored simulations.

The review record contains fresh captures, exact observations and checks. The
corrected comparison is ready for user review; no production adoption approval
has been received.

## Appendix: authorized persistent Tailnet presentation

The user explicitly instructed: "테일넷에 항상 띄우라니까 하네스 설정해".
This authorizes persistent hosting of the anonymous PoC on Tailnet HTTPS and
the harness instructions needed to make that presentation the default. It does
not approve production adoption of the eight proposed UX workflows.

The machine owns its service-manager configuration outside this product
repository. The preview starts at login or boot as supported by that manager
and restarts after unexpected exit, retaining the existing loopback-only
fixture server and exact Tailnet Host allowlist. A user LaunchAgent provides
the preview during a logged-in session; logout, power-off and Tailnet loss
remain availability limits. Existing Tailscale Serve routes are preserved;
public Funnel and weaker authentication are outside this authorization.

Before presenting a link, verify the actual HTTPS page and its assets as well
as the service state, and report any unresolved reachability or access failure.
Machine addresses, installed paths, operational settings and logs remain in
the external operating source of truth. The earlier loopback browser captures
remain historical interaction evidence; they are not evidence of Tailnet
reachability. The substantial production UX/UI approval gate remains pending.
