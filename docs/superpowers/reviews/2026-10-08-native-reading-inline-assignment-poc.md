# Native direct PDF find and inline assignment PoC evidence

Status: candidate implementation and local tool checks complete; owner viewport
presentation, production adoption and physical-device validation remain pending.

Scope: [bounded spec](../specs/2026-10-08-native-reading-inline-assignment-poc.md)
and [spike checklist](../plans/2026-10-08-native-reading-inline-assignment-poc.md).
The candidate is disposable. Current screen rules remain in native viewer
code/tests; `purpose`, `architecture`, `viewer`, `verification` and `workflow`
Handbook responsibilities were read. No product, API, persistence, identity,
server-runtime dependency or service configuration changes enter this revision.

## Current candidate

The latest direction places the quiet manuscript search immediately before one
native page control at the far right. Native document/view context stays left;
the collapsed-desktop pin toggle also precedes the single flexible gap. Only wide fine-pointer
fields show the small faint platform hint, `Search ⌘ F` or `Search Ctrl F`.
Compact native bands and coarse pointers show `본문 검색`, including fine-pointer
T3 width comparisons. This conservative hint policy makes no keyboard-presence
claim. Actual queries retain normal foreground contrast. The extracted-text Reading surface is
removed because reviewing two-column text or mathematics needs PDF/source
correspondence. A nonempty active query shows a compact results-only strip.
Desktop/tablet reuse their existing document row and native page-list trigger.
The wide current-section strip remains, with its duplicate page count hidden.
The phone reserves a compact top row with 4px bottom breathing and 12px safe-area
aware horizontal edges. Its idle state has a 16px magnifier inside a 44px native
button; tap reveals/focuses a transparent 16px input and 44px close button in
that same row, including an exit for empty search.
The final active-phone refinement hides the strip's duplicate close: phones have
count/page and two arrows in the strip, with one 44px row close for empty and
active search. Other bands retain strip close; native input clear remains.
Active search stays disclosed on entering phone. When a close becomes hidden
by a settled band change, only that close hands focus to the equivalent visible
close; ordinary media changes and input/caret focus retain their ownership.
The original position/sheet control relocates to the reserved row; the settled native band class owns relocation and restoration
to its lower-bar home. Native document-name, status-dot and accessible-name
projections remain intact. Observers survive persisted `pagehide` and disconnect
when their document is discarded.

Plain Cmd+F/Ctrl+F focuses/selects the query. Active unchanged query/index survives
refocusing and the shortcut. Enter/Shift+Enter navigate inside the query; native
result buttons retain Enter/Space activation. Alt, Shift, combined Cmd+Ctrl,
IME composition/keyCode 229 and open native dialogs are excluded from the
find chord. Escape hides results and paint and keeps the query. Phone disclosure
collapses and returns focus to the magnifier; non-phone search restores the
prior visible control, with a hidden selection-local note falling back to the
panel note. Native selection and drafts are preserved. Disclosure/focus follows
the settled native band, so coarse typing/IME holds retain the input/caret
through viewport changes. Native transitions blur the phone input before hiding
it and invalidate stale results. Hidden native rows leave browser find owned
by the browser. Reactive pointer-media changes update hints without stealing
focus.

Actual bundled PDF.js extraction still yields two `thermal` hits on page 2 and
`온도` hits on pages 1 and 2. Search uses actual anonymous PDF bytes, while source
location/selection geometry remains the authored fixture. Highlights cover PDF
text-item bounds. Empty queries hide the strip; no-hit queries disable its
navigation. Search/build/document generations and existing extraction bounds
remain. Page/pin/document/build/view changes dismiss results. The input is
explicitly disabled in 변경사항, so it cannot paint or navigate the hidden
manuscript; comparison-PDF search remains outside this candidate.
Hit navigation advances to the actual hit page's head if centering would leave
the previous page above it. Native scroll-derived `2/3` therefore agrees with
the sample's page-2 result; no synthetic native-page override is applied.

Inline assignment still uses existing native autocomplete in both note fields.
The first resolved non-self colleague anywhere becomes the candidate assignee;
later colleagues are FYI. Selected login hints distinguish the two anonymous
Robin Lee identities through handoff and document-draft parking/return. No tag,
removed tags, an unresolved ambiguous display name and self tags retain agent.
This remains a fixture-only proposal rather than server assignment behavior.

## Measured viewport behavior

Actual coarse-pointer Chromium contexts report native bands and 0px horizontal
overflow against current at 320×720, 390×844,
344×882, 768×1024, 1024×768, 673×960, 717×960 and 960×717.
The reserved phone row costs 52px of PDF height with zero safe-area inset:
44px controls below the native 4px stripe, plus 4px bottom breathing. Search and position control share
one vertical center above the PDF. Non-phone PDF height is unchanged. Coarse
inputs retain 16px query text and 44px search/page/result targets. The result
strip remains inside the viewport with the pin panel open and closed.

Fine-pointer 1440×900, 320×720, 344×882, 1024×768, 960×717, 768×1024,
717×960 and 673×960 contexts have no horizontal overflow with the pin panel
open and closed. Phone bands incur the reserved-row cost; non-phone PDF height
is unchanged and fields remain inside the native bar. Native page selection
and phone→tablet→phone control restoration pass in the isolated browser.

These browser emulations are distinct from the owner's native T3 width-only
screenshots. Neither establishes physical keyboards, hinge/rotation behavior,
safe insets, stylus, mobile browser differences or assistive technology.
Physical-device validation was explicitly postponed.

## Final phone single-close checks

The final single-close source passes the complete existing tool suite:
`uv run pytest -q -s tests/tools/test_ux_poc_serve.py`: 146 passed and 19 viewport
subtests passed in 24.92s. Syntax, strict standalone PoC types, Ruff check and
Ruff format check pass against the same final source. Raw output is
`limn-mobile-search-worker/single-close-tool-final-pass.log`; exact commands and
exit statuses are in `single-close-checks-final.json` outside the repository.

The focused phone duplicate-close and desktop-result-close-to-phone regression
checks both failed before this refinement (`single-close-red-final.log`). The
first broad refinement run then exposed reverse focus loss: hiding row close
blurred it before reading activeElement. Focus ownership is now captured before
visibility mutations. The regression passes phone/wide/phone close projection,
row dismissal, retained query, 8px strip margins and native page-2 projection.
The earlier failed broad output remains in `single-close-tool-final.log`.

The independent final lifecycle probe passes five checks, including equivalent
visible close focus in both band directions, coherent query/results anchor and
8px bounds, row Enter dismissal with retained query, and idle magnifier leaving
phone without invisible focus or keyboard reopening. Its final source hashes
and observations are in `limn-mobile-search-review.final-transitions.json`.
Native query clear remains intact. Final owner T3 presentation/HTTPS delivery
and production adoption remain separate from these isolated browser observations.

## Earlier mobile refinement checks and failure sensitivity

- The broad `uv run pytest -q -s tests/tools/test_ux_poc_serve.py` run passed
  145 tests and 19 viewport subtests in 24.14s before the final icon factory
  correction. Raw output is
  `limn-mobile-search-worker/tool-tests-final.log` outside the repository.
- The three added mobile behavioral checks failed against the previous candidate
  (visible permanent phone input and missing disclosure controls); `red.log`
  preserves that run. They subsequently passed in `focused.log`. They observe
  tap/keyboard opening, empty close, clear/retained query, native note/selection,
  IME/viewport hold, band restoration and page/build/document/revision dismissal.
- The first broad run found a 320px results strip left edge of -4.5px because the
  new close button moved the input's right edge. Its position now clamps to the
  viewport. `tool-tests.log` preserves this failure; the final matrix checks
  strip bounds and actual page-2/native `2/3` projection with both panel states.
- Independent read-only reviewer probes pass 4/4, including actual CDP pointer
  coarse/fine changes, retained caret during settled native typing holds, hidden
  short-band navigation retaining browser find, and revision disable/no invisible
  focused input. `limn-mobile-search-review.probe.json` preserves observations
  and identical source hashes before/after. These probes use isolated Chromium,
  separate from the owner's T3 screenshot work.
The broad 145-test/19-subtest result predates replacement of the fixed SVG
markup factory with equivalent SVG DOM creation. Source review then corrected
fallback button text with `replaceChildren(svg)` and added an icon-only assertion.
After that final correction, the three relevant mobile journeys passed in 5.57s,
and syntax/strict PoC types and independent glyph/ARIA/trusted-activation/empty
close probes passed (`limn-mobile-search-review.glyph.json`). The conservative
hint matrix also passes in `limn-mobile-search-review.hints.json`. The broad
suite was not rerun after that icon-only correction;
its count does not claim a whole-suite execution against the final bytes.
`icon-only-final-checks.json` retains the final affected checks. The earlier icon-only checkpoint native JS
SHA256 was `2a07e35a70b37baf0f4e71f3d0184aaf901da70f52ad93c1b1d0181a61025eea`.
The final idle and expanded screenshots in `limn-mobile-search-worker` are
isolated Chromium observations; they are separate from the owner's T3 captures.

- Final syntax, strict standalone PoC type checking and targeted Ruff checks pass;
  exact commands/results are in `limn-mobile-search-worker/checks.json` outside
  the repository. There are no dependencies, cross-slice imports, new gates or
  type-seam changes. Browser ES2022/DOM remains the configured runtime.

The following records describe earlier candidate verification and its retained
search/extraction/assignment boundaries; their counts are historical evidence.

## Earlier candidate checks and failure sensitivity

- `uv run pytest -q -s tests/tools/test_ux_poc_serve.py`: 142 passed and 19
  viewport subtests passed in 19.37s; raw output is preserved in
  `limn-toolbar-polish-worker/tool-tests.log` outside the repository.
- The new toolbar/native-page test reproduced three pre-polish viewport
  failures; `limn-toolbar-polish-worker/red.log` retains them. Search/page
  projection assertions reproduced five coarse portrait mismatches before the
  actual-scroll correction; `search-page-red.log` retains them. The final suite
  confirms page-2 hits and native `2/3` agree.
- A focused synthetic persisted-`pagehide` probe confirms that band relocation
  and numeric-page observers remain active across settled native band changes
  and page-2 search. `limn-toolbar-polish-worker/lifecycle-final.log` retains
  the result. This checks event handling, not actual browser BFcache eligibility.
- The direct-field shortcut test failed before implementation because no
  persistent query was visible; `limn-search-input-poc-red.log` preserves it.
  Initial candidate checks exposed re-focus resetting the active index and
  hidden selection-local focus restoration; both were fixed and rechecked.
- The isolated mutation server reads external mutant JS/CSS leaves rather than
  changing this checkout or persistent preview. Mutations intercept button
  Enter, keep revision search enabled, clear native note on dismissal, shrink
  coarse input and draw fine compact fields too tall. Five browser test methods
  produce 14 assertion failures and 0 errors. The script and raw output are
  `limn-search-input-poc-mutation.py` and `*-mutation.log` outside the repository.
- `ruff check` reports 0 errors; `ruff format --check` passes for the changed
  tool test. Node syntax checks pass for `native.js` and `native-pdf.mjs`.
  The standalone strict PoC TypeScript check uses checked-in native
  surface/fixture declarations and API/state/globals types. No type seam or
  production type configuration changes. `limn-toolbar-polish-worker/types.log`
  retains its clean result.
- `uv run pytest -q tests/architecture/test_handbook_refs.py`: 4 passed.
  The independent reviewer probe passes real keyboard result buttons,
  modal/legacy-IME exclusions, revision ownership and Escape while extraction
  is pending; its raw log is `limn-search-field-independent-probe-final.log`.

No property generator was added: changed tests observe concrete DOM/PDF/native
transition outcomes, while existing Host/parser properties still run. Chromium,
real PDF bytes, bundled PDF.js and the real fixture server were used. Production
integration gates were not rerun for this tool-only scope. General mathematical
or CJK fidelity, glyph-precise highlighting, scans/OCR, actual rebuild/source
mapping and physical-device behavior remain unproven.

## Review handoff and evidence identity

Baseline JS/CSS/README bytes from clean HEAD `a78cfd1` are preserved outside the
repo as `limn-search-input-poc-baseline.*`. The owner captured the previous
proposal before edits and owns final desktop/phone/tablet/foldable screenshots,
HTTPS asset responses, persistent launchd/Serve checks and Git/PR delivery.
This refinement worker changed only `native.js`, `native.css`, the PoC README,
the existing tool test and these existing exploration records. Type seams remain
unchanged. Stable source hashes and copied final sources are preserved in
`limn-mobile-search-worker` outside the repository. Exact diff and hashes are retained outside
the repository. Owner capture/runtime evidence is recorded below; user design
acceptance and physical-device validation remain pending. No adoption approval
is inferred.

## Owner capture and runtime evidence

The owner completed six paired native T3 idle comparisons and phone empty/active
search, totaling eight final images against the verified final source. All
observed layouts have zero horizontal overflow, and active search agrees with
native page `2/3`. The independent reviewer inspected all eight final images and
passed their visual review. These are native T3 observations, separate from
coarse-pointer emulation and physical-device testing.

Owner evidence is preserved outside the repository as
`limn-mobile-search-comparison-20261008.json` and
`limn-mobile-search-comparison-20261008.md`. Eleven HTTPS resources returned 200;
served JS/CSS matched the delivery worktree, and the persistent LaunchAgent was
running with RunAtLoad and KeepAlive enabled. User design acceptance and
physical-device validation remain pending.
