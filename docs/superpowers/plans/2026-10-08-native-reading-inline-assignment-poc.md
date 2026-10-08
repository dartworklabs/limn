# Bounded native direct-find and assignment spike

Scope/exit: [exploration spec](../specs/2026-10-08-native-reading-inline-assignment-poc.md).
This checklist tracks the disposable PoC, not a production implementation plan.

- [x] Preserve native viewer and anonymous fixture isolation; extend the sample
  to real multiple PDF pages and allowlisted fallback images.
- [x] Extract with bundled PDF.js on demand and map
  every repeated find occurrence to its actual page/item bounds.
- [x] Connect the selection-local textarea to existing autocomplete/hints and
  inspect first resolved colleague assignment plus FYI in native previews/cards.
- [x] Keep desktop/tablet controls within existing geometry; prepare
  desktop/phone/tablet/foldable interactions for review.
- [x] Run meaningful tool checks, preserve raw evidence outside the repo, and
  point the existing persistent preview at the delivery worktree through its
  canonical dotfiles plist and installer without changing routes/auth.
- [x] Record actual browser evidence and limitations; stop before adoption.

- [x] Replace Find/Reading buttons with a persistent upper-right input and
  query-dependent results strip; remove the extracted-text reader.
- [x] Scope shortcuts to supported plain chords and the manuscript view; retain
  native button keys, modal ownership, IME and draft/selection behavior.
- [x] Verify actual sample hits, empty/no-hit queries, native transitions and
  coarse geometry; preserve failure-sensitive check evidence outside the repo.
- [x] Polish the search hint and order native document context, search, numeric
  page control in one aligned row; preserve full native navigation behavior.
- [x] Replace the phone overlay with a reserved compact row using its original
  position/sheet control; measure its PDF height cost and breakpoint restoration.
- [x] Verify narrow widths, side states, hint/query contrast and native page
  selection using the isolated browser harness; run syntax and PoC type checks.
- [x] Owner captures six paired desktop/phone/tablet/foldable idle comparisons
  plus phone empty/active search and confirms Tailnet runtime responses.
- [ ] Present the final design for user acceptance before production adoption.
- [ ] Validate physical devices; this work remains explicitly deferred.

Mobile disclosure refinement resumes this authorized spike under the latest
user feedback; no production-adoption approval is inferred.

- [x] Step 1: Reproduce missing phone disclosure and empty-query dismissal with
  focused behavioral checks in `tests/tools/test_ux_poc_serve.py`; preserve red
  evidence outside the repository.
- [x] Step 2: In `tools/ux-poc/native.js` and `native.css`, add native accessible
  magnifier/close controls and quiet reserved-row input. Follow settled bands
  and coarse media; retain native typing, position control, drafts and generation
  guards. Expected: 44px tap targets, 16px text, breathing space, no invisible
  focused field or stale results after native transitions.
- [x] Step 3: Verify behavioral journeys and the device matrix once settled;
  run syntax/standalone PoC types, update README/review with observations and
  limits, and announce stable bytes before the owner's T3 captures. The owner
  owns the single logical Git/PR checkpoint and final HTTPS presentation.

- [x] Step 4: Resolve the final active-phone review's duplicate close by hiding
  only the phone result-strip close in `native.css`; retain native query clear
  and 44px row dismissal for empty/results states. Verify two visible arrow
  targets, viewport margin, native page projection and equivalent close focus
  across native bands, then run the complete
  existing tool suite and syntax/types/Ruff once against the final source.
