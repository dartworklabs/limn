# Native PDF reading/find and inline assignment exploration

Status: authorized bounded exploration; production adoption is pending.

## Purpose, scope, and exit

The user authorized continuing the pending UX work and requires desktop, phone,
tablet and foldable PoCs before adopting any appearance change. This spike asks
whether the native whole viewer can expose real PDF text from the main topbar,
map repeated find hits to their actual pages, and show inline `@` assignment in
both native note surfaces while retaining existing selection/drafts/card actions.
It ends when those interactions are reviewable with a real anonymous multi-page
PDF and the viewport matrix is ready for the parent's browser inspection.

Only `tools/ux-poc/` and its existing tool tests are implementation scope. New
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

Find and reading remain direct main-topbar actions. Desktop/tablet reuse its
height. Where the phone has no native document row, its compact tools overlay
the PDF at the top rather than reserving another 44px row. The existing lower
navigation remains the phone's document-selection route.

## Extraction and review boundaries

The bundled PDF.js reads actual `/pdf` bytes on demand. Search enumerates every
non-overlapping normalized occurrence and maps its text-item geometry to the
true page. Highlighting uses whole text-item bounds, not glyph-precise bounds.
Reading preserves PDF content-stream order; semantic column order is unproven.
CJK and simple mathematics are included in the sample, but general CJK spacing,
complex formulas, ligatures, rotated text, scans and OCR are not promised.
Extraction is bounded to 12 pages and 200,000 characters; no OCR is added.

Required captures: 1440×900; 390×844 and 320×720; tablet 768×1024 and 1024×768;
foldable outside narrow and inside approximately 673–717px portrait/landscape.
Inspect PDF/reading, find open/closed, pin panel open/closed, middle/leading/multi
tags, ambiguity, deletion, no tag, and handoff between popover and panel.
Record width, height, pointer media, native band, stable overflow and viewport
cost. Actual coarse-pointer and physical-device checks remain separately named.
