# Workflow UX PoC and narrow repairs review

## Approved assignee adoption: PASS

The user's **“수정시안 적용”**, following the mobile/desktop card crops and Tailnet
comparison, approves only the last assignee/card metadata presentation. Approval
and Task 4 were recorded before production edits. Pending statements below are
historical for this presentation; main-bar reading/find, hiding the new-pin
assignment selector, new @assignment rules and other workflows remain unapproved.

Root's final design/code review passes: `cards.js`, `card-parts.js` and
`css/cards.css` own one neutral 12px normal-weight metadata line after the note.
Author/reply count stay in the header, and native question/review/claim/warning
badges retain meaning without repeated expanded context. Human identity,
escaping, role gating and the native edit action are preserved; agent assignment
is plain text. Missing legacy assignment displays unspecified without changing
stored assignment. Composer assignment and mention/reply rules are unchanged.
`docs/handbook/viewer.md` matches that production state. No ADR, API/storage,
security, daemon or dependency contract changes are introduced.

Review target: HEAD `38dc0d7` plus this uncommitted adoption and preserved earlier
work; fresh fetch shows HEAD and origin/main at 0/0. External
`limn-adopt-badge-source-proof.json` identifies source bytes and proves the changed
native JS/CSS is contained byte for byte in the served current HTTPS page.
`limn-adopt-badge-validation.json` consolidates the final gate and runtime verdicts.

Root verifies the final current HTTPS page and all 16 loaded assets return 200;
proposal JS/CSS also return 200. Both 1440px variants show one native metadata row,
zero PoC summaries, a 152.492px card and an 18px row at 12px/400. The 390px compact
card is 75.5px. Widths 320, 390, 768 and 1440 have no horizontal overflow. Clicking
the relocated assignee opens the correct pin's native editor with its assignment
control intact. Expanded native badge context and fine/coarse input checks pass;
focused regressions include observed RED/GREEN and a hit-clearance mutation.
Raw browser and implementation evidence remains outside the repository in
`limn-adopt-badge-browser.json`, `limn-adopt-badge-tests.log` and
`limn-adopt-badge-code.log`. Physical-phone and screen-reader behavior is unverified.

| Applicable gate | Final result | Evidence and scope |
| --- | --- | --- |
| Required full pytest | PASS: 3634 passed, 9 skipped, 2534 subtests, 237.40s; exit 0 | `limn-adopt-badge-font-recovery.log`; skips are eight macOS bwrap-unavailable cases and one optional real-state copy |
| Focused Hangul rendering | PASS: 3 passed, 10 subtests, 6.25s | `limn-adopt-badge-font-recovery.log`; official Noto font registered temporarily for existing fallback-font checks |
| Instance administration | PASS: 202 passed, 0 failed | `limn-adopt-badge-administration.log` |
| Sync, Ruff, formatting, ShellCheck, boundaries | PASS; 479 files already formatted | External `limn-adopt-badge-*.log` records |
| mypy and Darwin mypy | PASS: 162 source files each | `limn-adopt-badge-mypy.log`, `limn-adopt-badge-mypy-darwin.log` |
| npm install, JS types, strict ratchet | PASS: 0 vulnerabilities; strict 0 errors | Corresponding external npm-ci/typecheck/strict-ratchet logs |
| Handbook publication and references | PASS: check/build exit 0; 4 reference tests passed | `limn-assignee-adoption-doc-checks.json`; unchanged pinned font/Pandoc prerequisites |

The first full attempt lacked the fallback test font. Recovery used temporary
CoreText Session registration of an official Noto font; product and test sources
were identical before/after, and no test was weakened. Registration was removed
successfully and fresh Chromium confirms Noto is absent. The external font
registration/run evidence preserves provenance, checksums and cleanup.

Task 4 is complete. The accepted presentation is implemented and verified in the
worktree and managed comparison; no commit, PR, release or real-instance
production deployment is claimed. Other proposed workflows retain their original
review boundaries.

## Assignee presentation refinement review (historical)

The current variant preserves the actual native header assignee chip. The
earlier proposal repeated that recipient in collapsed metadata. This bounded
refinement moves the original button/span after the note and places assignment
once in neutral 12px text, retaining `data-act="edit"`, native button/span
permission gating, tooltip and `translate="no"` identity text. The editable
button also names its existing edit consequence and gains hover/focus underline.
Agent assignment uses plain noninteractive text. Header author and reply
affordances remain native.

Expanded question and active claim/review/reopen/location-loss badges retain
their meaning and actions; matching summary values appear only in the compact
collapsed state where native badges are hidden. Ordinary fix/open cards show
kind, assignment and state together. Existing fine/coarse hit utilities remain;
coarse rows reserve space around an editable assignee so its 44px hit does not
reach an adjacent thread action. No new badge, filled container or control strip
is introduced. Native document reading/find keeps the latest main-bar placement.

Syntax and isolated strict `checkJs` checks pass with the actual native wire
declarations. Path-scoped whitespace checks and checks of the untracked authored
files pass. Exact command output and source hashes remain in the external
refinement log. No tests mirror this reversible presentation code and no
production suite was rerun for this tools-only change. Assignment/mention/reply
rules, API/server/runtime configuration,
dependencies and production files have no change in this refinement. Earlier
production and browser evidence above or below retains its original revision
scope; it does not establish production adoption or fixture write parity.

Root inspected the actual proposal at 390px and 1440px in the native browser.
The compact header contains no assignee; each metadata line contains the single
original native chip. Its text is 12px, normal weight and transparent; the row
and assignee have aligned 18px line boxes on the inspected ordinary cards. The
collapsed card measures 75.5px, compared with 57.5px for native current and 74px
for the prior duplicated proposal. There is no compact horizontal overflow.
Expanded metadata follows the note with a 4px gap. Clicking the relocated
native assignee opens that pin's actual editor, whose native assignment control
remains visible. Desktop authors remain in the header; ordinary expanded cards
gain 22px. Native question/review/claim badges remain visible without repeated
summary values. Whole-view captures and raw observations remain in the external
browser evidence. These are desktop-browser viewports, not physical-phone,
coarse-pointer or screen-reader verification; current worktree presentation
does not establish identical production deployment bytes.

## Scope and decision

The user authorized all diagnosed improvements and dynamic agent allocation,
and explicitly required a working PoC and confirmation before production
changes with substantial UX/UI impact. The
[exploration spec](../specs/2026-10-07-workflow-ux-poc.md) and
[plan](../plans/2026-10-07-workflow-ux-poc.md) preserve this boundary.

The user rejected the first independent presentation because extra prototype
chrome and expanded upper controls prevented a reasonable design decision.
Three dynamically assigned agents rebuilt the anonymous fixture around the
actual viewer assembly, localized the proposed controls, and independently
reviewed fidelity and interaction ownership. Root owns native-browser comparison
and presentation. This revision changes only `tools/ux-poc/` and the exploration
records; existing production repairs are preserved. No commit, push, release,
deployment, or manuscript change was included in that presentation revision.
The user's later authorization adds persistent Tailnet hosting of the anonymous
PoC and harness instructions; it does not approve production UX adoption.

The finite exploration is ready for user review. **Production adoption of the
eight larger workflows remains pending explicit confirmation.** The revised mock assets
stay under `tools/ux-poc/`; the packaged viewer does not import them. The existing
three-column desktop organization is retained, with controls added where their
consequences can be previewed before acting. The old independent prototype's
six HTML/CSS/JS/JSON/SVG assets have been removed.

## Revised native-viewer comparison

The dedicated loopback server assembles `read_viewer()` / `run_page()` from the
current source. `?variant=current` receives the original viewer plus the shared
anonymous fixture; `?variant=proposal` adds only `native.js` and `native.css`.
Fonts, icons, navigation, outline, tool/meta rows and responsive organization
are the actual bundled viewer. No status/scenario/dashboard header or permanent
reading toolbar is added. Reload resets in-memory data; instructions live in
the [README](../../../tools/ux-poc/README.md).

The authored Korean sample is a real PDF with bookmarks rendered by bundled
PDF.js. Its paragraph geometry is authored in native `x/y/width/height` form.
The fixture uses the same short Git head shape as `builds/engine.py`; the first
fixture's full SHA had artificially wrapped the metadata row and was corrected
before the final paired comparison. Seed references also use supported short
Git refs, while revision API IDs retain their complete commit identifiers.

### Observed geometry

Root measured both variants at the same clean preferences and pointer settings
after fonts, PDF and outline became ready. The ten shell/page rectangles had
**zero CSS-pixel delta** at 1440 × 900. Typography and a representative unchanged
card height also matched.

| Native surface | Current | Proposal |
| --- | --- | --- |
| Document navigation height | 44px | 44px |
| Tool row / tool control height | 45px / 28px | 45px / 28px |
| Metadata row height | 61.59375px | 61.59375px |
| Right panel / outline width | 348px / 240px | 348px / 240px |
| PDF page origin and width | (290, 98), 780px | (290, 98), 780px |
| Body font | Pretendard Variable, 14px / 21.7px | Same |
| Tool font | Pretendard Variable, 13px / 18.2px | Same |
| Pin 11 card height | 152.1875px | 152.1875px |

The proposed search/filter group occupies 64.9453125px inside the scrollable
pin list. It moves that list's first card, not the native header or PDF. Human
work controls appear only on the eligible person's status row; ordinary card
action rows retain their native layout.

At 390 × 844, the six closed-panel shell/page rectangles again matched exactly:
the PDF begins at (12, 12), width 366px; bottom tool row is 52px. The opened native
sheet is 540px high and its content width/scroll width are both 390px. The
proposed search and reply-purpose controls are 44px high. Native send/cancel
buttons retain their fine-pointer dimensions; this viewport test does not
claim coarse touch or an actual phone keyboard.

### Observed workflows

| Proposal | Native-browser evidence |
| --- | --- |
| Search and work queues | `#17` reveals the completed archive example with one result and no empty state. My-work shows 12; the native all-documents toggle adds 19 and changes the count from one to two. Search focus survives list rendering. |
| Kind and assignee | The native composer previews question / myself / open. Native save creates local pin 21 with those facts and clears the submitted note. |
| Reply purpose | A comment on 16 keeps review state. Explicit request-again survives mention and list redraw, reopens 16, and retains its question kind and colleague assignment. The existing delayed-send path is used. |
| Consecutive review | Native undo is visible after confirming 15 and opening 16. After the deferred command, 15 is done while 16 remains review; the next item needs its own confirmation. |
| Stale recovery | Existing rebuild produces a new mock build, retains the note and blocks save. Ctrl+Enter adds no pin. Search navigation disables candidate confirmation; Escape closes search while retaining selection/note. Explicit show/check re-enables save. A document round trip with an observed pending candidate retains only the note and requires reselection. |
| Human claim and ETA | Start 12 at 15 minutes, open its extension form, redraw the list, and extend to 30 minutes. The live form and value survive redraw. Native release removes the claim; state remains open. ETA selection was applied with a DOM change event, not physical select interaction. |
| Reading and search | Enter activates an authored PDF-search rectangle. Reading mode displays selectable authored text; Enter focuses the matching reading section. Leaving reading returns to PDF with the composer note intact. Arrow keys are bound inside the search field. |
| Compact information | Collapsed 14 displays type, agent assignment, work status and approximate ETA. Search and explicit reply intent fit the opened native sheet without horizontal overflow. |

T3 exposes no pointer-drag action in this session. Root initialized selections
through the actual native pick command and inspected its real composer; this
does not establish physical drag gestures. The viewport keeps a desktop browser
user agent and fine pointer. Real source mapping, PDF extraction order, actual
build/diff accuracy, physical-phone gestures and screen readers remain outside
this authored fixture's evidence. The mock revision PDF reuses the sample PDF.

Actual final captures (native browser artifacts):

- Current desktop: `browser-screenshot-127-0-0-1-muxy2068-d4361b42.png`.
- Proposed desktop: `browser-screenshot-127-0-0-1-muxy15lb-aca0c843.png`.
- Proposed compact pin 14: `browser-screenshot-127-0-0-1-muxy0fq2-c816a5a4.png`.

### Revised checks and source identity

The fixture server serves only fixed allowlisted resources on loopback. API
reads are not served by HTTP and all HTTP mutations are refused. The browser
adapter handles anonymous API effects in tab memory and forwards only permitted
same-origin GET assets. It opens no real instance, manuscript or credentials.
The fixture agent reports 21 route/Host/method checks and command/invalid-input
checks with zero API forwarding. Root reviewed that boundary and independently
ran the final syntax/strict JS check against real viewer wire types, Ruff and
formatting, mypy for both Python tool files, and whitespace checks: all pass.

Independent review identified and resolved candidate/document ownership,
candidate visibility under mobile sheets, save/append keyboard bypass, search
Escape bubbling, document-roundtrip restoration and ETA redraw loss. Confirm
advancement now reuses the native close binding, delayed command and undo.
The reviewer found no remaining shell CSS override or identified blocker after
those corrections. No production UX adoption is implied by these checks.

The presentation revision's 11 sorted regular files in `tools/ux-poc/` were
identified by SHA-256
`c594cb8ee6cdec89dcae64ecfcb9716a438d14d113cffdcfda16ad12876e0799`,
hashing each relative path, NUL, complete bytes and NUL. This is a historical
digest of that revision, before the later `serve.py` Host-option and README
hosting changes; it does not identify the current complete PoC directory.
The native UI
and fixture hashes begin `9b69b783` and `2c76901b`. The full production suite
below was completed before this tools-only presentation revision and was not
rerun for the fixture changes. Its production scope is unchanged.

## Persistent Tailnet hosting verification

The user authorized persistent anonymous PoC hosting and harness configuration.
Canonical global instructions now reach the actual harness home as well as the
default home; the project's instructions and Handbook require verified Tailnet
HTTPS presentation. The external machine configuration uses a user LaunchAgent
with login start and automatic restart. The runtime remained loopback-bound,
and an owned TERM changed its process ID before HTTPS recovered successfully.

The recorded before/after Serve configuration preserves all 13 existing TCP
entries and 14 Web entries; only the preview route was added. No Funnel entry
was introduced. Current, proposal and stale-example HTTPS pages and authored
assets returned 200 with default certificate verification. A foreign Host was
refused with 403; API reads and path escapes returned 404; HTTP writes returned
405. The server grants only one parsed exact Tailnet authority in addition to
its original loopback hosts. It reads no real manuscript or credentials.

The focused server-boundary suite passed 132 cases in 1.72 seconds. Eleven
mutation families were rejected, including public/default Host denial, writes,
unlisted paths, wrong variants, response headers, HEAD bodies, CLI validation,
capability validation and authority normalization. A stale-bytecode artifact
was detected and corrected before counting the affected mutation as rejected.
These are isolated test-server observations, separate from deployment proof.

The native browser inspected the actual HTTPS proposal at 11:09:02 UTC. It
reported a secure context, loaded fonts, a rendered 1556 × 2202 PDF canvas,
seven pin cards and four outline sections. All 18 observed resource URLs used
HTTPS. Root visually inspected the fresh native screenshot and confirmed the
preserved viewer layout. The screenshot and raw browser, lifecycle, boundary
and Serve comparison evidence remain in external operating logs; machine
addresses and paths are not copied into this product record.

Ruff checks and formatting, feature boundaries, and mypy for both default and
Darwin platforms passed: 478 formatted files and 162 checked source files.
The final whole-repository `uv run pytest -q -rs` completed with exit 0:
3626 passed, 2507 subtests passed and 20 skipped in 245.86 seconds. No
require-environment flags were set for this run. Eight skips cover Linux bwrap
being unavailable on macOS, one is an unset opt-in real-state copy, and eleven
cover wide-extent Hangul font cases without the required WenQuanYi/Noto font.
The unchanged production font scope was verified in the earlier reviewed run
using a temporary CoreText font, with nine skips; that evidence remains scoped
to the earlier revision and does not remove the current run's font skips.
The complete fresh output remains in the external operating log. Hosting does
not approve the eight proposed product
UX workflows; Task 4 and production adoption remain pending user confirmation.
The preview remains running during the logged-in session, with logout, power-off
and Tailnet connectivity as availability limits.

## Historical first-prototype observations (presentation rejected)

The native T3 collaborative preview inspected the loopback prototype at desktop
1440 × 900 and compact 390 × 844. The following effects were observed in the
actual page, not inferred from mock screenshots or JS syntax checks.

| Proposal | Observed interaction |
| --- | --- |
| Search and work queues | Searching `#17` reveals the completed example in its archive with one result. My-work scope shows pin 12; changing to all documents adds pin 19 and updates counts and scope labels. The document-scope change was applied through the select's DOM change event; native select keyboard interaction was not established. |
| Explicit request kind and assignee | A question assigned to myself shows question, recipient, page and open state in the save preview. Submitting creates local pin 21 with those facts and clears the submitted draft. The agent/fix default is also visible in the presentation capture. |
| Explicit reply purpose | Pin 16 defaults to discussion only. Sending keeps its review state. Switching to request again retains the text, previews the retained colleague/question assignment and reopening, and submitting reopens only that local example. |
| Consecutive review | Confirm-and-next on pin 15 confirms that example and opens pin 16. Pin 16 still requires a separate confirmation; the remaining-review count becomes one. |
| Stale PDF recovery | A stale example invalidates the selected location but retains the note and disables save. Simulated rebuilding proposes a location. Navigating elsewhere disables its confirmation; viewing and explicitly confirming the proposal restores a saveable selection with the latest note. |
| Human work status | Pin 12 accepts a local 15-minute work indication, extends it to 30 minutes, and returns to open when released. These are simulations of the existing claim affordance, not an API permission change. |
| Reading and body search | Enter and ArrowDown activate authored body-search results and move the reading focus/overlay to the result. Searching elsewhere does not relocate the composer selection or erase its note. Reading mode hides the page graphic and displays selectable authored text. |
| Compact card information | At 390 × 844 a collapsed pin 14 retains type, assignee and work/ETA status. Search and explicit reply controls remain usable without page or panel horizontal overflow; observed filter and send/cancel controls are 44px high. |

Prototype inspection exposed and corrected a completed-search empty-state error,
an overlay that prioritized the composer over the active body-search result,
reading focus being reset by note edits, and proposal confirmation being enabled
while looking elsewhere. These corrections affect only prototype behavior.

Actual captures are retained in the browser artifacts folder for presentation:

- Desktop composer: `browser-screenshot-127-0-0-1-muxpmwd6-b11f4678.png`.
- Compact collapsed search: `browser-screenshot-127-0-0-1-muxox259-bd90af49.png`.
- Compact explicit reply: `browser-screenshot-127-0-0-1-muxorakn-27936320.png`.

The prototype server binds to `127.0.0.1:5174`. Reload and reset restore anonymous
in-memory examples. Source and network inspection found only local assets and a
same-origin `reading.json` fetch, without production API calls or persistence.
The authored SVG and eight reading regions are valid and within the sample page;
HTML element IDs are unique and both referenced scripts exist. Both JS syntax
checks and their combined strict `allowJs/checkJs` TypeScript check pass.

## Narrow production repairs

The [approved safety spec](../specs/2026-10-07-ux-safety-fixes.md) and
[completed plan](../plans/2026-10-07-ux-safety-fixes.md) cover role-appropriate
confirmation, bilingual local-human onboarding, and keyboard PDF badges.
Root reviewed the existing server-provided identity facts, both confirmation
surfaces, native-button navigation/selection exclusions, responsive geometry,
translation strings and documentation. Server authorization, lifecycle, API
contracts, pin records and transaction ordering have no corresponding change.

The new real-server/browser regressions initially failed for refused agent/viewer
confirmation controls and an inert keyboard badge: four failures and one pass.
A temporary false human-permission helper also caused the positive human oracle
to fail; it was restored immediately. Focused checks pass with persisted human
confirmation and direct agent refusal remaining 403. The previous save/build,
outline, picker and cross-engine repairs remain in the worktree and are covered
by their [existing review](2026-10-07-diagnosed-fixes.md).

The combined suite exposed a remaining old `<b>` locator in the English tooltip
test. Its locator now selects the badge action while retaining the exact
user-text and translation assertions. All 29 i18n tests and 14 subtests pass.

A lower-phone ghost-click test also failed deterministically at `(100, 700)`.
Transient event tracing showed that `elementFromPoint` returned the PDF image,
but Chromium delivered pointerdown, pointerup and click to the nearby native
badge button. No pick ran (`PICKSEQ = 0`). The badge still measured 26px and its
CSS extension remained 44px; this was native touch-target adjustment rather than
an async selection failure. The clear PDF test point is now `(140, 700)`, at the
same height. All four scenarios retain their resolved-location, no-ghost-click,
kind and focus assertions, and additionally verify that the settled opening
panel covers the tap point. No timeout increase or retry was added. A second
agent independently reviewed the trace and this correction. Chromium's
[touch-adjustment implementation](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/core/page/touch_adjustment.cc)
corroborates the observed preference for nearby focusable controls.

## Feasibility and remaining limits

The existing claim API permits a human writer to claim with ETA, extend their
own claim and unclaim. Claim remains an expiring indication, not a new pin state
or exclusive lock. Production work must preserve conflict/closed/viewer refusal
semantics and existing claim ownership, not copy the simplified mock mutation.

The bundled PDF.js 6.3.289 exposes page text extraction and `TextLayer`, confirmed
against its version-matched primary
[page API source](https://raw.githubusercontent.com/mozilla/pdf.js/v6.3.289/src/display/api.js)
and [text-layer source](https://raw.githubusercontent.com/mozilla/pdf.js/v6.3.289/src/display/text_layer.js).
The viewer currently has no text-layer builder/CSS. Adoption must handle the
existing region-drag/long-press gesture conflict through explicit modes, preserve
document/build guards and viewport lifetimes, and keep the current PDF safety
options. No new runtime dependency has been added by the PoC.

Production stale recovery already has build-generation and document-visit
guards. A rebuilt composer restores its note and requires a new selection.
Automatically proposing a mapped location is not an established production
contract; its real matching and verification require a separate adoption task.
The prototype's simulated proposal establishes only the interaction direction.

The sample graphic and reading JSON do not establish real PDF reading order,
math/search fidelity, scanned-document extraction, source-line mapping or build
accuracy. Card line ranges are fixtures: their location-information action
shows the range rather than navigating to a real mapped PDF pin. Viewport checks
do not establish physical iOS gestures, screen-reader behavior or actual tailnet
identity transport. These limits are also stated in the prototype README.

## Combined verification

The final repository-wide run after the locator and touch-test corrections
passes: **3,495 tests and 2,517 subtests; nine skips; 233.97 seconds; exit 0**.
Both `LIMN_TEST_REQUIRE_BROWSER=1` and `LIMN_TEST_REQUIRE_NODE=1` were set. The
skips are eight Linux sandbox cases without `bwrap` on macOS and one explicitly
opt-in real-state-copy case. No browser, Node or font checks were skipped.
The focused corrected ghost-click case also passes all four subtests.

The real Hangul clipping checks used the official pinned Noto font bytes,
SHA-256 `6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a`,
temporarily registered with CoreText session scope. The validation wrapper
unregistered the font successfully and deleted its temporary file in `finally`.
No persistent font installation changed.

| Gate | Final result |
| --- | --- |
| Ruff and formatting | Zero errors; 475 files already formatted. |
| Feature boundaries | Passed. |
| mypy | Both default and Darwin platforms pass 162 production files. |
| Viewer TypeScript | Passed. |
| Strict ratchet | Zero errors in zero files. |
| Prototype JS | Both syntax checks and the combined strict JS type check pass. |
| Diff | Whitespace check passes; transient tracing is absent. |

The prior instance manager, shell, installation and Handbook publication checks
remain applicable to their unchanged scopes; detailed evidence is in the
previous review. Local evidence does not claim remote CI, deployment, physical
iOS, actual tailnet operation or complete assistive-technology coverage.

The assessment separates implementation intent from regression gates: the narrow
repairs preserve the existing collaboration/authorization contracts, and the
exploration demonstrates the requested flows without adopting them. User review
of the concrete PoC is the remaining gate for larger production UX work.

The historical pre-revision reviewed content was identified by SHA-256
`cc5f2e3bc3074a1c3f78ccac0a013ea6c2853334f1b9b858769d0b1a409abb4e`.
It covers the 48 sorted modified/untracked worktree files outside
`docs/superpowers/`, hashing each relative path, NUL, full file bytes and NUL.
This includes preserved authorized repairs, Handbook synchronization, both
README languages, tests and the seven prototype assets; review/spec/plan records
are excluded to avoid self-referential identities.

## Latest narrowed comparison: revision record

The user rejected pin search, explicit reply-intent controls, work-start badges
and separate assignment controls after viewing eight paired captures. These
extensions are removed from the currently served proposal. Consecutive review
and rebuild/location recovery have no adoption decision and are deferred;
their extension controls and command wrappers are removed. Earlier observations
above describe historical variants and do not identify the current proposal.

The bounded revision retains body find/selectable reading, now directly in
the main document `#doc-nav`, and collapsed-card kind/recorded assignee/native
status. No production viewer, API, fixture backend, Handbook or hosting
configuration is changed by this revision. The native reply/composer/mention
computations and native review/build commands retain ownership. The conditional
new-pin native assignee row is hidden solely to preview inline @mention
presentation; native edit-assignment controls remain. The user confirmed the
no-tag default as agent, matching current behavior. Tags-anywhere assignment
and first-colleague/multiple-FYI details remain pending, and this preview does
not implement those new rules. Fixture writes do not reproduce all server-side
typed-mention resolution/storage and reply hints; only native frontend
autocomplete/new-pin presentation is claimed.

Desktop bars retain their configured heights. The phone comparison adds a
condensed 44px main document bar (plus safe top inset), reducing exposed PDF
height by that amount. Native bottom navigation remains, making document
selection available at both ends on the phone. The temporary find panel floats
below the document bar and covers content while open. The native-browser
observations below establish the inspected geometry. Physical mobile keyboards
and coarse-pointer tablet layouts
are not established by desktop-browser width-only captures.

After the revision, `node --check` and isolated strict TypeScript `checkJs`
with the native fixture/viewer declarations pass. TypeScript requires
`--ignoreConfig` when files are listed directly; the initial TS5112 attempt was
corrected and preserved with the successful command in the external check log.
Path-scoped whitespace checks pass. No new tests mirror the reversible PoC
implementation, and no production suite result is claimed for this tools-only
revision. User review remains pending; production adoption remains gated.

### Final native-browser observations

Root inspected the revised actual HTTPS viewer at desktop, intermediate and
phone widths, preserving whole-view captures and measurement identities in the
external operating evidence. The measurements compare current then proposal.

| Surface | Observed result |
| --- | --- |
| 1440px desktop | Main document bar remains 44px; metadata row remains 61.59375px. |
| 1024px intermediate | New controls occupy y=0 through y=44, fitting the existing 44px document bar after the inset correction. |
| 390px phone | One visible **찾기** label, 44px top-bar controls and no horizontal overflow. |
| Phone PDF, panel closed | Exposed height changes from 791px to 747px. |
| Phone PDF, panel open | Exposed height changes from 304px to 260px. |
| Collapsed phone card | Height changes from 57.5px to 74px for the added context line. |
| Phone PDF find | A 62px temporary overlay covers content below the bar; it adds no permanent layout row. |

Find Enter, next-result navigation and Escape were exercised. Reading starts
without automatically opening find and returns to PDF. Native inline
autocomplete selected a resolved colleague and the current frontend computed
that assignee while the new-pin assignment row remained hidden. Selection setup
used native commands; no physical pointer drag was performed. These observations
cover an authored one-page reading/search fixture and desktop-browser fine
pointer viewports, not production extraction, physical touch/mobile keyboards
or fixture typed-mention/reply write parity.

The current/proposal pages, revised JS/CSS and sample PDF returned HTTPS 200,
and the persistent service was running. Machine addresses, runtime paths,
resource responses, captures and service evidence remain outside the repository.
Path-scoped whitespace checks pass. The default agent assignment is confirmed;
tags-anywhere and first-colleague/multiple-FYI rules remain pending. No production
adoption is approved by these measurements or hosting checks.
