# Diagnosed repairs review

## Scope and assessment

The owner authorized all diagnosed repairs, dynamic agent allocation, and three outline adjustments. The
[spec](../specs/2026-10-07-diagnosed-fixes.md) and [plan](../plans/2026-10-07-diagnosed-fixes.md) define this scope.
The working branch and refreshed `origin/main` are both based at `38dc0d7`; changes remain in the worktree.
No PR, commit, deployment, release, or external manuscript edit is included.

The implementation preserves the existing capability boundaries, HTTP paths and response fields, stored pin
format, `pins.md`, transaction ordering, authentication, and empty runtime dependency set. Figure selection
retains actual element boxes, scores, and ladders. Historical ADRs are unchanged. Current rules and reasons
are synchronized in the viewer, domain, build-sync, and verification Handbook topics.

Root reviewed pin request lifetimes, revision checks, later-input preservation, test observations, and current
documentation. A second agent independently reviewed the build, picker, outline, measurement, browser helper,
and CI changes without editing them; it found no additional blocker. Applied references include Handbook
read/sync/review, code implementation, testing, and security. Security review concerns the preservation of
the existing revision and safe-text boundaries; no new trust authority or executable input is introduced.

## Observable repairs and regression evidence

| Repair | Observed failure and resulting behavior |
| --- | --- |
| Pending create, append, and edit | Seven original pin regression failures preceded the fix. Successful requests persist submitted data while later input remains editable; unchanged submissions still clear normally. The final focused real-server/browser run passes 17 tests in 7.43 seconds, including the cross-engine flows. |
| Stale append, undo, and rapid submission | The displayed revision is checked before append; rejection keeps the draft. Undo restores only its verified prior note at the successful revision. A shared create/append lock prevents duplicate writes. Tests inspect the actual pin store and rendered controls. |
| Remote close during edit | An additional failing regression demonstrated loss of the dirty editor on `409 done`. The editor now retains the note and current non-location input, adopts the stored location, and permits an explicit note-only retry without reopening the pin. |
| Mention hints | Separate red steps exposed a later same-text recipient choice being lost and an unchanged typed alias becoming falsely dirty. Baselines now distinguish persisted recipients from active autocomplete hints; hint-only changes remain saveable. |
| Metadata-colliding input edit | Real TeX tests preserve exact file size and nanosecond mtime and check actual PDF text. The recorded-input repair initially missed unknown recorder inputs; two deterministic recorder-off/shipped-recorder failures exposed that path. Changed or unproven inputs now force latexmk rules while retaining auxiliary caches. The real TeX class passes 14 tests in 15.78 seconds; all warm tests pass 52 tests and 23 subtests in 25.74 seconds. Unchanged skips and trusted dpi-only PDF reuse still pass. |
| Outline | The original wrapped-title case showed a 16.8px number offset and no row gap. Desktop and touch regressions now verify common first-line tops, bare roman/numeric labels, at least 4px separation, and 44px touch targets. Native collaborative browser inspection at desktop and phone widths confirms the requested appearance. |
| Revision fixture | Global automatic signing changed deterministic Git identifiers and failed the revision snapshot. The fixture disables signing only in its temporary repository; all 30 range tests pass in 11.88 seconds with contributor settings intact. |
| Thin/small figure choice | Four initial examples failed for a thin line, dot, padded label, and unrelated branch depth. The repair adds bounded selection-only boxes and prunes candidate ancestors. Guard, actual-fill, actual-score, and no-overlap mutations are detected by the examples/generated invariants. Picker and measurement-tool checks pass 43 tests and two subtests. |
| Measurement page edges | Parser-tolerated fractional overshoot caused generated negative drag widths. Nine examples failed before clamping, then all 11 example/generated checks passed. The original-map metrics below are unchanged by this tool correction. |

Firefox and WebKit add six coverage flows through rendered controls and the real server/store. These are
coverage additions observed green; the report does not claim each engine variant independently ran red.
The browser CI job installs all three engines and makes required-engine failures fail the job.

## Reconstructed figure comparison

The original `fig/concept-limnmap` producer branch was recovered through its historical head commit
`e4770c63e8cd64b6f27703ffaca63d54f20b1289`. The source map is
`figures/concept/out/limn/figures.limnmap.json`, SHA-256
`a380fef5f7afd92535abd03d99416250bb3eb5b6322f32bb801a2c19abec46e6`: 24 pages and 7,831 non-root elements.
The external map and its manuscript/source identities are not checked into this repository.

The original ADR-0015 drag harness was not recovered. This comparison uses
[measure_figure_pick.py](../../../tools/measure_figure_pick.py), seed `2090015`, 150 targets per page, and
20 sibling samples per parent. It freezes the pre-fix thresholds and priority, isolates ancestor pruning,
and compares the current picker on identical reconstructed samples. This is 15,790 single-target drags
and 3,113 sibling drags, not ADR-0015's original 59,492-sample experiment or measured human accuracy.

| Cohort | Legacy exact match | Current exact match |
| --- | --- | --- |
| All single-target drags | 74.44% | 79.06% |
| Absolute padding | 45.28% | 65.26% |
| Thin elements with padding | 6.83% | 63.57% |
| Tiny elements with padding | 10.03% | 54.76% |
| Tight | 83.25% | 84.14% |
| Partial | 80.05% | 80.27% |
| Point | 77.55% | 78.34% |
| Siblings, direct parent | 38.48% | 42.82% |

Unrelated single-target choices decrease from 12.24% to 8.85%; unrelated sibling choices decrease from
13.52% to 6.49%. The trade-off is bounded but real: large tight targets lose one exact match out of 502
(58.57% to 58.37%), and large partial targets lose three (52.99% to 52.39%). Relative to ancestor pruning
alone, bounded hit expansion also lowers direct-parent sibling matches from 45.33% to 42.82% by choosing
more descendants. All 1,578 current sibling-descendant answers retain the intended parent in their real
ladder. These limits are retained in the assessment rather than describing every subgroup as improved.

The selection-only minimum axis is 1.2% of the page; it is not a fixed screen-pixel tolerance at every zoom.
Actual-fill and strong-original-candidate guards prevent vacant-area hits and stealing a well-covered
candidate. Actual scores can remain weak for a thin chosen element. Broad/tight safety examples, all four
page edges, root-only maps, and bounded parser/pin integration remain covered. A maximum-size/depth probe
(5,000 elements, depth 64) averaged 19.69ms over ten selections on this machine; this is an observation,
not a portable latency guarantee.

## Final verification

| Check | Result and limits |
| --- | --- |
| Full integration | `LIMN_TEST_REQUIRE_BROWSER=1 LIMN_TEST_REQUIRE_NODE=1 uv run pytest -q -rs`: 3,490 passed, 2,517 subtests passed, nine skipped; 236.34 seconds, exit 0. Python 3.14.7 on macOS arm64. Eight Linux sandbox cases lack `bwrap`; one real-state-copy case is explicitly opt-in. No browser, Node, or font skips. |
| Instance manager | 202 passed, zero failed. Existing owned shell adapters replace system services. |
| Installation | Isolated `uv tool install .` passes CLI version/help, required assets, all 92 font-slice hashes, test exclusion from the wheel, viewer assembly, and icon routes. No global tool installation changed. |
| Static checks | Ruff: zero errors; format: 467 files already formatted. ShellCheck: zero diagnostics. Feature boundaries pass. Both mypy platforms pass 162 production modules. Viewer typecheck passes; strict ratchet remains zero errors. `git diff --check` passes. |
| Documentation references | Four Handbook reference checks pass in 0.80 seconds after link corrections. |
| Handbook publication | Five pre-existing invalid link targets produced exit 2 before correction. With exact pinned Pandoc/font bytes, publisher check passes in 1.03 seconds and standalone HTML build passes in 2.23 seconds. The HTML has 11 chapters, 355 valid fragment links, no scripts, and no external assets; it remains at `.handbook/out/index.html`. Transient tools/font are cleaned up. |

The first integration run after repair found the unknown-recorder defect and missing CJK font dependency.
The actual build defect was repaired with deterministic red/green cases; no timeout or retry policy was
relaxed. Required Hangul clipping checks use an official pinned Noto font temporarily registered with
CoreText for the test session, not a fabricated fallback. The final suite runs with that font and both
required flags; registration is removed and temporary font files are deleted afterward.

Physical iOS gestures and keyboard/Safari behavior remain unverified because device access is disabled in
this environment. Desktop WebKit coverage does not substitute for this check. Issue #127's already
completed items are marked complete while the physical-iOS item stays open; issue #209 is not closed on
the strength of unmerged local changes. Remote CI, live tailnet operation, and deployment are not inferred
from local evidence.
