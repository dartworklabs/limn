# HTML document surface plan (deferred)

Scope: [HTML document surface — Markdown and other line-based sources](../specs/2026-10-24-html-document-surface.md) (revision 1). **Deferred and not approved.** Nothing in this plan starts until the owner approves a revised spec and [ADR-0025](../../adr/0025-html-document-surface.md) (now `제안`). Revision 1 re-checked every task against `main` 0.4.45; the line references below are to that tree. A throwaway PoC on branch `poc/html-surface` shows the direction and is not merged.

## Task 0: Approval

- [ ] Step 1: The owner settles the spec's open calls: decision 1 (Markdown pins store no `page`/`frac`), 4 (vendored markdown-it), 5 (security policy: raw HTML as placeholders, no remote images, CSP first) and the UI points of 7 seen in the PoC. Expected: a revised spec marked approved, with the exact approval recorded.
- [ ] Step 2: ADR-0025 raised to `승인됨` at merge (partial supersession of ADR-0011 D1's scope wording and ADR-0020 D1's "LaTeX only").
- [ ] Step 3: A separate design and ADR for the viewer page's Content-Security-Policy (`script-src 'self' 'sha256-…'`, `object-src 'none'`, `base-uri 'none'`; `img-src` and the PDF.js worker measured). It lands before the HTML surface.

## Task 1: Capabilities, registration, startup

- [ ] Step 1: `markdown` in `DocKind` (`runtime/documents.py:40`) and capabilities `renders_in_browser`, `takes_suggestions` (`:298-336`). Expected: `documents/tests/test_meta.py` capability table extended first, then green.
- [ ] Step 2: Replace the remaining kind checks with capabilities: verdict placement (`pins/runtime.py:273-280`, `pins/verdict.py:84`, `:191-200`), the startup build (`builds/run.py:51-58`, `builds/service.py:79-86`). Expected: a Markdown verdict pin gets `superseded_by`; startup records no failed build for a Markdown document.
- [ ] Step 3: Suffix registration (`.md`) in `administration/serve_documents.py:256-266`, its start-line label (`:356-367`), `administration/instance_documents.sh:55-63`. Expected: registration tests and `test_instances.sh` cover `.md`; other suffixes still refused.

## Task 2: Serving the source

- [ ] Step 1: A read route for a browser-rendered document: its lines as `tex_lines` numbers them, read through the checked handle with a size limit (`read_bounded`), declared in `security/access.py` READ_PATHS. Expected: an edit to the `.md` reaches the viewer within one light poll (`src_mtime` already follows the file, `builds/artifacts.py:409`); nothing writes the manuscript.

## Task 3: Pins on Markdown

- [ ] Step 1: Line pins without `page`/`frac`/`pdf_build` on a browser-rendered document: `parse_loc` drops them (`pins/editing/location.py:200`, `:51`), `LinePlace` stops requiring `page` there (`pins/editing/rules.py:142-154`), `pins.md` writes `—` in the page column (`pins/listing/render.py:694`). Expected: contract and rollback tests (precedent `tests/contracts/test_suggest_rollback.py`).
- [ ] Step 2: Rung values `block`, `section` (`pins/editing/values.py:22-25`) and pin kinds `md:<block>`, `md:section`; the `pins.md` section suffix for a Markdown document (`render.py:812-819`). Expected: range column and section title tests.
- [ ] Step 3: Suggestion gate on `takes_suggestions` (`pins/editing/rules.py:525-532`, `:686-692`, `pins/editing/service.py:79`, `pins/editing/http.py:85`). Expected: Markdown line pins accept suggestions; view-only and figure documents still refuse. SKILL examples of an obvious error in Markdown under ADR-0024 (broken table cells, unclosed emphasis or code, list indentation).

## Task 4: Change view for Markdown

- [ ] Step 1: `md` in the revision pathspec (`revisions/core.py:424-426`); source diff and pin-scoped hunks (line mapping already in `revisions/scope.py:252-264`); no comparison PDF; the viewer opens Markdown changes on the source diff. Expected: revision tests on a Markdown fixture.

## Task 5: Viewer HTML surface

- [ ] Step 1: Vendor markdown-it with its licence notice and sha256 (`src/limn/vendor/markdown-it/`, `THIRD_PARTY_NOTICES.md`, `viewer/assemble.py:44`, `viewer/routes.py:27-32`, `:98-101`, `viewer/application.py:32-38`, `security/access.py:689`). Expected: vendor tests like PDF.js's.
- [ ] Step 2: The second document pane (one new part, md-surface): DOM-only rendering, raw HTML as placeholders, links and images restricted, per-block and per-line source ranges, selection and tap to lines, the ladder, marks and gutter badges, the outline from headings; branches in `buildDoc`, `marks`, `jumpPin`, `pickOutline`, `vecOpen`, `pressOutsideSelection`, meta polling. Page-only controls hidden; page verdict line and panel off. Expected: behaviour tests and security fixtures; PDF-surface guards unchanged.
- [ ] Step 3: Pins without `page` in the viewer: card page label (`cards.js:64`), list order (`list.js:161-163`), lost-answer recovery (`save.js:96`). Expected: behaviour tests.
- [ ] Step 4: Four-device-group PoC with measured sizes and a live instance for the owner. Expected: the owner has looked before merge.

## Task 6: Contract documents and migration

- [ ] Step 1: Handbook (`purpose.md`, `architecture.md`, `domain.md`, `api.md`, `viewer.md`, `instances.md`, `operations.md`, `build-sync.md`, `index.md` file map), `skill/SKILL.md` and `.ko.md`, CHANGELOG. Expected: `test_handbook_refs.py` green.
- [ ] Step 2: After release, papers that commit a generated LaTeX rendering of a Markdown document switch the tab to the `.md` itself and drop the generated files and their CI check. Expected: pins on the old generated tab are closed or re-placed first; the tab key change is recorded in that paper's agent instructions.
