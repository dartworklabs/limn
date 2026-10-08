# Native reading and inline assignment PoC evidence

Status: ready for the owner's desktop/mobile/tablet/foldable presentation;
production adoption and physical-device validation remain pending.

Scope: [bounded spec](../specs/2026-10-08-native-reading-inline-assignment-poc.md)
and [spike checklist](../plans/2026-10-08-native-reading-inline-assignment-poc.md).
The user's every-appearance PoC rule is reflected in project `AGENTS.md`,
`docs/handbook/workflow.md` and the tool README. Native production rules remain
the current authority; the candidate exists only in the anonymous proposal.

## Observed behavior

Bundled PDF.js extracts the real anonymous PDF: page 1 has 746 characters in 144
text items, page 2 has 336 characters in 26 items, and page 3 has no text items.
The two `thermal` occurrences both map to page 2, at different searchable
offsets. `온도` has hits on pages 1 and 2. The reader renders the extracted runs
and identifies page 3 as having no extractable text. The fixture's authored
geometry remains the source-location stand-in; it is no longer the search or
reader input. English math symbols and Korean text are sample observations,
not arbitrary-document fidelity promises.

The desktop real-drag test opens the native selection-local note, chooses the
second `Robin Lee` login from native autocomplete, and hands the same text and
login hint to the panel. Adding a later `@동료` produces FYI while the native
saved card displays `Robin Lee` as assignee. Typing the ambiguous name without
a hint, deleting a colleague tag, no tags and a self tag retain the agent.
The coarse tablet test retains the exact chosen login and note through reading
and native document-draft parking/return.

## Actual coarse-pointer browser contexts

Every row reports actual `matchMedia('(pointer:coarse)') === true`, native body
classes, 0px horizontal overflow, and unchanged `#left` height against current.
The phone tools overlay a 102×44px area at the top-right, with separate 44×44px
buttons. They preserve PDF viewport height and occlude that small content area.
Tablet/foldable contexts retain their existing 48px main navigation row.

| State | CSS viewport | Native band | Current/proposal PDF height |
| --- | --- | --- | --- |
| Small phone | 320×720 | phone | 720 / 720px |
| Phone | 390×844 | phone | 844 / 844px |
| Foldable outside | 344×882 | phone | 882 / 882px |
| Tablet portrait | 768×1024 | tablet-sheet | 976 / 976px |
| Tablet landscape | 1024×768 | mid-side | 671 / 671px |
| Foldable inside portrait | 673×960 | tablet-sheet | 912 / 912px |
| Foldable inside portrait | 717×960 | tablet-sheet | 912 / 912px |
| Foldable inside landscape | 960×717 | mid-side | 620 / 620px |

Each context exercises real page-2 search paint, next occurrence, extracted
reading, the textless page, closing find and returning to the PDF. These are
repository browser-harness emulations. The owner's native T3 browser has fine
pointer/width-resize evidence, which must be recorded separately. Neither
establishes physical keyboards, pinch/rotation, hinge transitions, safe insets,
stylus or assistive technology.

## Checks, failures and limits

- Final tool suite: `uv run pytest -n 0 -q -s tests/tools/test_ux_poc_serve.py`:
  138 passed, 8 subtests passed in 14.21s.
- First actual-gesture run: 2 failed, 136 passed, 8 subtests passed. Both note
  tests exposed the fixture parser rejecting native pick coordinates
  `x0/y0/x1/y1`. Accepting those finite numeric fields restored native selection;
  the next browser run had 3 passed and 8 subtests passed in 13.93s.
- A mutation of only the isolated test server's extraction response removed hit
  geometry while retaining counts. All 8 viewport subtests failed `0 != 1` for
  page-2 paint. The checkout and persistent preview were never mutated for this
  experiment. The initial note failures and this mutation cover the new tests'
  failure sensitivity. No new property generator was added: these checks own
  concrete PDF/gesture integration observations; existing Host/parser property
  tests continue to gate the tool's input boundary.
- `ruff check`: 0 errors; `ruff format --check`: 4 files already formatted.
  Node syntax checks and the separate PoC TypeScript check passed. The parent's
  integrated product gates are a separate result.

Raw records live outside the product repository under the machine log directory:
`limn-native-device-poc-extraction.json`, `*-extraction-probe.log`,
`*-tool-tests.log`, `*-browser-tests.log`, `*-final-tool-tests.log`,
`*-mutation.log`, `*-runtime.json`, `*-launch-before/after.txt` and
`*-serve-before/after.json`.

The direct Node extraction probe uses real bundled PDF.js and its worker. Since
Node lacks browser rendering globals, it installs a `DOMMatrix` constructor that
throws if invoked; extraction completes without invoking it. Node rendering is
not claimed. Browser checks use actual Chromium DOM and PDF.js.

## Persistent review runtime

The canonical dotfiles preview plist changes only its working directory and
worktree environment value. Its exact prior contents are preserved outside the
repo for rollback. The existing installer dry-run/start passed; launchd reports
the delivery worktree and running PID 68203 with RunAtLoad and KeepAlive.
The complete before/after Tailscale Serve JSON is identical. All actual page,
proposal, PDF, vendor, PNG and font resources checked over the derived Tailnet
HTTPS URL returned 200. An initial extra probe guessed a nonexistent font CSS
name and received 404; checking the stylesheet linked by the rendered HTML and
its font leaf returned 200. It was a probe-path error, not a missing UI resource.

The anonymous static server keeps exact Host checks, loopback binding, resource
allowlisting and refusal of API reads/HTTP mutations. New routes are static
anonymous samples under that existing grant. No production instance, owner
token, manuscript, Serve route, identity rule or deployment changed. Reviewers
need an authorized connected Tailnet device; the host/user login and Tailscale
must remain available. No claim is made about an untested reviewer's ACL.

## Pending owner review

The owner must inspect the whole native viewer at desktop/phone/tablet/foldable
widths, with pin panel and find/reading opened and closed, and compare phone
content occlusion against retained viewport height. The candidate's semantic
choice, body control placement, screen appearance and limits require review
before any production implementation. No commit, push, PR or release is made.
