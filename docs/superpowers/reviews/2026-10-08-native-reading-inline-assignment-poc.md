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

The latest direction replaces the two Find/Reading buttons with one persistent
upper-right manuscript search input. The extracted-text Reading surface is
removed because reviewing two-column text or mathematics needs PDF/source
correspondence. A nonempty active query shows a compact results-only strip.
The input uses native tokens, the existing toolbar's right end and existing
height. Mid-width native navigation spans the screen above an open side panel;
that band therefore places the input at screen-right.

Plain Cmd+F/Ctrl+F focuses/selects the query. Active unchanged query/index survives
refocusing and the shortcut. Enter/Shift+Enter navigate inside the query; native
result buttons retain Enter/Space activation. Alt, Shift, combined Cmd+Ctrl,
IME composition/keyCode 229 and open native dialogs are excluded from the
find chord. Escape hides results and paint, keeps the query and restores the
prior visible control. A selection-local note hidden by native positioning
falls back to the panel note. Native selection and drafts are preserved.

Actual bundled PDF.js extraction still yields two `thermal` hits on page 2 and
`온도` hits on pages 1 and 2. Search uses actual anonymous PDF bytes, while source
location/selection geometry remains the authored fixture. Highlights cover PDF
text-item bounds. Empty queries hide the strip; no-hit queries disable its
navigation. Search/build/document generations and existing extraction bounds
remain. Page/pin/document/build/view changes dismiss results. The input is
explicitly disabled in 변경사항, so it cannot paint or navigate the hidden
manuscript; comparison-PDF search remains outside this candidate.

Inline assignment still uses existing native autocomplete in both note fields.
The first resolved non-self colleague anywhere becomes the candidate assignee;
later colleagues are FYI. Selected login hints distinguish the two anonymous
Robin Lee identities through handoff and document-draft parking/return. No tag,
removed tags, an unresolved ambiguous display name and self tags retain agent.
This remains a fixture-only proposal rather than server assignment behavior.

## Measured viewport behavior

Actual coarse-pointer Chromium contexts report native bands, 0px horizontal
overflow and unchanged PDF height against current at 320×720, 390×844,
344×882, 768×1024, 1024×768, 673×960, 717×960 and 960×717.
The phone field overlays a 148×44px area at top-right, preserving PDF height
while occluding that region. Coarse non-phone bars retain 48px height with
44px search/result targets. The result strip remains inside the viewport with
the pin panel open and closed.

Fine-pointer 1440×900, 1024×768, 768×1024, 717×960 and 673×960 contexts preserve
PDF height and have no horizontal overflow. Fine compact non-phone fields draw
at native control height within the existing bar rather than bleeding below it.
At fine-pointer 673px the native band is phone, so its intentional overlay is
measured separately from a nonexistent navigation row.

These browser emulations are distinct from the owner's native T3 width-only
screenshots. Neither establishes physical keyboards, hinge/rotation behavior,
safe insets, stylus, mobile browser differences or assistive technology.
Physical-device validation was explicitly postponed.

## Checks and failure sensitivity

- `uv run pytest -q tests/tools/test_ux_poc_serve.py`: 141 passed and 13
  viewport subtests passed in 13.71s; raw output is preserved in
  `limn-search-input-poc-final-tool-tests.log` outside the repository.
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
  The standalone PoC TypeScript check uses checked-in native surface/fixture
  declarations and wire/screen types, including the verified `setViewMode`
  signature. Production type configuration is unchanged.
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
This worker changed only the tool candidate, its existing tests/type seam and
these existing exploration records. Exact diff and hashes are retained outside
the repository; final owner evidence must be added before claiming its visual
presentation/runtime verification complete. No adoption approval is inferred.
