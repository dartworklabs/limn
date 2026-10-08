# Native PDF direct find and inline assignment exploration

Status: authorized bounded exploration; production adoption is pending.

## Purpose, scope, and exit

The user authorized continuing the pending UX work and requires desktop, phone,
tablet and foldable PoCs before adopting any appearance change. This spike asks
whether the native whole viewer can expose desktop PDF search and mobile
disclosure at the main topbar's right edge,
map repeated find hits to their actual pages, and show inline `@` assignment in
both native note surfaces while retaining existing selection/drafts/card actions.
It ends when those interactions are reviewable with a real anonymous multi-page
PDF and the viewport matrix is ready for the parent's browser inspection.

Only `tools/ux-poc/` and its existing tool tests are implementation scope. Existing
spec/plan/review records describe evidence and pending choices. Production viewer
code, server assignment rules, API, pins format, security and persistence do not
change. The canonical machine preview configuration may point the existing
LaunchAgent at the delivery worktree; auth and Serve routes stay unchanged.

The superpowers tools are unavailable in this session. No installation is
attempted. The explicit exploratory path is scope → disposable spike → evidence
→ post-exploration record, under `workflow.md` and `arch-design(spec)`; it supplies
no approval to adopt this code in production.

## Current authority and state

- purpose: `docs/handbook/purpose.md`; viewer code/tests are screen authority,
  and machine service state is runtime authority.
- topic: `docs/handbook/viewer.md`; current new-pin assignment uses leading tags
  (or a question's first tag), with agent default when no colleague assigns it.
  Native selection, note ownership, edit assignment and replies retain ownership.
- invariant: `docs/handbook/architecture.md`; standard-library server, exact
  identity boundaries, additive contracts and transaction write ordering remain.
- gate: `docs/handbook/verification.md`; visible observations and actual outcomes
  are evidence. Fine-pointer resize cannot establish coarse-pointer or physical
  mobile behavior.
- workflow: `docs/handbook/workflow.md`; exploration and production adoption are
  separate, and appearance changes require the user's PoC review.

## Candidate to inspect

The proposal's first resolved non-self colleague anywhere in the new note is its
single assignee; later resolved colleagues are FYI. Explicit autocomplete login
hints disambiguate identical displayed names. Unresolved or removed tags assign
nobody; no colleague tag retains the already-approved agent default. Self tags
carry no notification or assignment. This is a candidate, not a production rule.
The existing mention preview communicates who receives assignment/FYI, and the
saved native card shows the chosen assignee. There is no separate new assignment
control, scenario panel, status header, pin search or new reply category.

The latest user direction polishes the persistent search field with a faint
empty-field hint (`Search  ⌘ F` on Apple platforms, `Search  Ctrl F` elsewhere).
The actual query keeps normal foreground contrast. Native document/view context
stays left, followed by one flexible gap, search, and the compact numeric page
control at the far right. Desktop/tablet reuse the existing document-row height;
the native `nav-page` opens the native page list and its accessible name retains
the full page wording. The duplicate wide section-strip page count is hidden,
while its current-section context remains.

The phone replaces the floating PDF overlay with a reserved top row: 44px for
controls plus the larger of the native 4px stripe or top safe area and 4px bottom
breathing space. Idle phones show a magnifier; activation reveals search in this
same row. Its existing
`btn-pos` moves to that row, keeps native document/view/page-sheet behavior, and
returns to its original lower-bar home on leaving the phone band. The measured
phone PDF height cost is explicit; input and page control never cover PDF text.
Coarse-pointer input text remains 16px and touch targets remain at least 44px.
No second page control, extra status strip, or feature change is added.

## Extraction and review boundaries

The bundled PDF.js reads actual `/pdf` bytes on demand. Search enumerates every
non-overlapping normalized occurrence and maps its text-item geometry to the
true page. Highlighting uses whole text-item bounds, not glyph-precise bounds.
PDF rendering remains native; no extracted-text reading mode is exposed.
CJK and simple mathematics are included in the sample, but general CJK spacing,
complex formulas, ligatures, rotated text, scans and OCR are not promised.
Extraction is bounded to 12 pages and 200,000 characters; no OCR is added.

Required captures: 1440×900; 390×844 and 320×720; tablet 768×1024 and 1024×768;
foldable outside narrow and inside approximately 673–717px portrait/landscape.
Inspect PDF, find inactive/active, pin panel open/closed, middle/leading/multi
tags, ambiguity, deletion, no tag, and handoff between popover and panel.
Record width, height, pointer media, native band, stable overflow and viewport
cost. Actual coarse-pointer and physical-device checks remain separately named.

## Mobile disclosure refinement scope and exit

The user's latest review requests a distinct mobile interface because the
persistent field is too large and flush against the row. This remains the same
authorized disposable exploration. Before implementation, the resolved geometry
is a 44px control area with native 4px top stripe/safe-area padding and 4px bottom
breathing space: 52px total without safe insets, with 12px horizontal/safe-area
edges. Idle phone layout shows only a 16px native magnifier in a 44px button,
followed by the existing trailing numeric position control. Activation reveals a
transparent 16px search field and a 44px close button in this reserved row.
Empty search can therefore be dismissed without opening a results panel.
The final active-phone review removes the duplicate result-strip close: the
phone row close handles both empty and active search, while the strip contains
only count/page and two arrows. Non-phone result strips retain their close.
The browser's native search-input clear remains a distinct query-clear action.
Entering the phone band retains active search disclosure so its strip has a
visible input anchor. A focused close that the new band hides transfers focus
to the visible close with the same action in either direction. Input/caret and
ordinary pointer-media changes receive no new focus effects.

Phone disclosure follows the settled native band, including native typing holds.
The input remains focused through coarse-pointer resizing/IME, and leaving the
phone band restores the persistent field and original position-control home.
Only wide fine-pointer fields retain the faint platform hint. Compact bands
and coarse-pointer fields show only `본문 검색`; media changes update the hint, without inferring keyboard
presence. Actual hardware Cmd/Ctrl+F events still reveal/focus supported search.
Native revision/modal ownership and hidden-row guards preserve browser find.
Explicit close/Escape retains query/native drafts and returns phone focus to the
magnifier. Document/build/page/view dismissal blurs a field before hiding it,
invalidates search generation, and never leaves stale results or invisible focus.

Exit requires tap/open/type/clear/dismiss, hardware activation, native band
restoration/typing hold, revision guards, and observed bounds/spacing/page
projection to pass in isolated Chromium. The owner presents paired native T3
captures across the required device matrix. Physical-device checks and product
adoption remain pending.

## Direct-input interaction contract

Plain hardware Cmd+F or Ctrl+F reveals, focuses and selects the retained query; Alt, Shift, both
modifiers, IME composition and native open dialogs remain excluded. Enter moves
next and Shift+Enter previous only inside the input; result buttons use their
normal Enter/Space activation. Escape hides results/highlights and retains the
query, collapsing phone disclosure to its magnifier and restoring focus there.
Desktop restores the prior visible control or panel note if its local selection
composer is hidden. Native selection/drafts are not cleared.

The results strip appears only for an active nonempty query. It shows count and
page with previous/next, plus close outside the phone band. Phones use only the
row close to dismiss search; navigation is disabled for no hits. Searches and
extractions retain stale-query/document/build generation guards and bounds.
Result navigation centers its actual hit, then advances to that page's head if
the preceding page would remain above it. Native scroll-based page projection
therefore agrees with the search result without a forced counter override.
Native page/pin/doc/build/view transitions dismiss search. In 변경사항 the input
is disabled and browser find remains available; comparison-PDF search is outside
this candidate. Mid-width native navigation spans the screen above the side
panel, so its right-end field follows that native geometry.
