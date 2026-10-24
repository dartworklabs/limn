# HTML document surface plan (deferred)

Scope: [HTML document surface — Markdown and other line-based sources](../specs/2026-10-24-html-document-surface.md). **Deferred and not approved.** Nothing in this plan starts until the owner approves a revised spec and its ADR. The tasks are written so that the work can start from here once approved.

## Task 0: Approval

- [ ] Step 1: Revisit the spec's seven design decisions with the owner and a co-maintainer; settle the parser choice (vendored CommonMark parser with source maps vs a stdlib server renderer) and the pin geometry for pins without `page`/`frac`. Expected: a revised spec marked approved, with the exact approval recorded.
- [ ] Step 2: Write the ADR (new document kind and surface, scope widening in `purpose.md`, vendored bundle if chosen, partial supersession of ADR-0020 D1 so Markdown line pins take suggestions). Expected: ADR `제안`, raised to `승인됨` at merge.

## Task 1: Capabilities and registration

- [ ] Step 1: Add `markdown` to `DocKind` and the capabilities `renders_in_browser` and `takes_suggestions` in `runtime/documents.py`; route existing checks through capabilities only. Expected: `documents/tests/test_meta.py` capability table extended first, then green.
- [ ] Step 2: Suffix registration (`.md`) in `administration/serve_documents.py` and `instance_documents.sh`, messages, `doc_start_line`, `apart_paths`; refuse `--main x.md` or support it explicitly. Expected: registration tests and `test_instances.sh` cover `.md` acceptance and the remaining refusals.

## Task 2: Serving and watching a Markdown document

- [ ] Step 1: Serve the source text and its revision stamp to the viewer through a checked manuscript read; poll for changes like a watched file, with no build. Expected: an edit to the `.md` reaches the viewer within one poll; nothing writes the manuscript.

## Task 3: Pins on Markdown

- [ ] Step 1: Pick from a selection to `file`, `lo`, `hi`, `quote`, with line splitting identical to `str.splitlines()`. Expected: fixture tests with tables, nested lists, code blocks, CRLF and form feeds.
- [ ] Step 2: A Markdown ladder (lines → block → section) in `pins/location/mapping.py`. Expected: pure tests.
- [ ] Step 3: Line pins without `page`/`frac` through the model, record check, listing and `pins.md`. Expected: contract and rollback tests.
- [ ] Step 4: Suggestion gate on `takes_suggestions`. Expected: Markdown line pins accept suggestions; view-only and figure documents still refuse.

## Task 4: Change view for Markdown

- [ ] Step 1: Add `md` to the revision pathspec and window; source diff and pin-scoped hunks for `.md`; the viewer opens Markdown changes on the source diff. Expected: revision tests on a Markdown fixture.

## Task 5: Viewer HTML surface

- [ ] Step 1: Vendor the chosen parser (if chosen) with its licence notice; render with raw HTML off and links/images restricted. Expected: security fixtures render inert.
- [ ] Step 2: The second document pane: render with per-block line ranges, marks from `lo..hi`, selection → pick, outline from headings, in-document search; page-only controls hidden for this surface. Expected: behaviour tests; PDF-surface guards unchanged.
- [ ] Step 3: Composer, card, edit card and suggestions on Markdown pins; the suggestion editor shows raw Markdown. Expected: behaviour tests.
- [ ] Step 4: Four-device-group PoC with measured sizes and a live instance for the owner. Expected: the owner has looked before merge.

## Task 6: Contract documents and migration

- [ ] Step 1: Handbook (`purpose.md`, `architecture.md`, `domain.md`, `api.md`, `viewer.md`, `instances.md`, `operations.md`, `build-sync.md`), `skill/SKILL.md` and `.ko.md`, CHANGELOG. Expected: `test_handbook_refs.py` green.
- [ ] Step 2: After release, papers that commit a generated LaTeX rendering of a Markdown document switch the tab to the `.md` itself and drop the generated files and their CI check. Expected: pins on the old generated tab are closed or re-placed first; the tab key change is recorded in that paper's agent instructions.
