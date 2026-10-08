# Diagnosed build, pin, and outline repairs

## Agreed scope

The owner approved proceeding with every diagnosed repair and dynamically assigning agents in this session. The owner also specified first-line alignment of outline numbers, bare page labels, and separation between adjacent selected and hovered rows. The read-only diagnosis supplied reproductions before implementation.

- Preserve edits made in the same composer or editor while its submitted request is pending.
- Refuse a stale append without losing its draft; bind undo to a validated prior note and the successful revision.
- Prevent simultaneous create/append requests from the same composer.
- Recompile a changed recorded input even when its size and modification time have not changed.
- Improve selection of thin figure elements and comparison between unrelated branches, with measured evidence before adopting a rule.
- Isolate deterministic revision fixtures from automatic Git signing.
- Cover critical pin operations in Firefox and WebKit as well as existing Chromium coverage.
- Align outline numbers and printed page labels with the title's first line; omit page suffixes in outline lists and keep adjacent shades separated. Retain touch target size.

## Constraints and non-goals

Runtime dependencies remain empty. The HTTP API, figure-map schema, `pins.md`, stored pin records, authentication, and pin transaction order retain their contracts. Figure selection changes only calculated choice; it retains the actual element box, ladder, and original-box score. No manuscript is changed by the repair. No deployment or release is included.

Existing completed items in issue #127 are not implemented again. WebKit automation is useful coverage but cannot attest to physical iPhone/iPad gestures, keyboard behavior, or Safari chrome.

## Acceptance

Submitted data reaches the real pin store while later input remains editable and recoverable; stale revisions cannot erase another writer's note. Duplicate gestures yield one append. A same-size, same-mtime CSV edit appears in actual PDF text, and unchanged builds still skip. Outline spans share a first-line top, shades have a visible gap, and touch targets remain at least 44px. The revision snapshot passes with automatic signing enabled in the contributor's global settings.

Figure selection is compared on the map used for ADR-0015. The exact original drag script is sought; if it cannot be recovered, a reconstructed seeded experiment is identified explicitly and its results are not described as the original 59,492 samples. Improvements must retain tight, broad, and sibling selection behavior in the regression suite. The full applicable gates in the Handbook must pass.

## Current authority

Rules: `docs/handbook/purpose.md`, `architecture.md`, `domain.md`, `viewer.md`, `build-sync.md`, `code-style-roadmap.md`, and `verification.md`. The current figure thresholds come from ADR-0015; their numeric values are preserved. Production effects remain at existing slice boundaries.
