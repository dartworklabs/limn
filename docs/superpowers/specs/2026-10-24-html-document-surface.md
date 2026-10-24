# HTML document surface — Markdown and other line-based sources (deferred proposal)

## Status

**Deferred. Not approved; do not implement.** On 2026-10-24 the owner chose to keep Limn LaTeX-only for now ("일단은 tex 만 하자") and asked for this plan to be written down concretely and handed to a co-maintainer for review. Implementation needs the owner's explicit approval of a later revision of this document (HARD-GATE, [workflow.md](../../handbook/workflow.md) §기본 경로), a new ADR, and the four-device-group PoC before any viewer change reaches `main`.

Interim practice that this plan would replace: a paper repository that wants a Markdown document in Limn commits a line-preserving LaTeX rendering of it (one generated line per Markdown line) and registers that `.tex` as an ordinary LaTeX document, with CI checking that the generated file matches its source. One paper already does this for its manuscript backbone.

## Problem

Limn only gives line pins on LaTeX. Working documents that people and agents edit together — design backbones, notes, plans, response drafts — are often Markdown. Today they either go through a committed LaTeX rendering (a generated file to keep in sync, LaTeX-escaped text in the suggestion editor, print-style pages on phones) or become view-only PDFs (no line numbers).

## Diagnosis: why not convert Markdown to LaTeX inside Limn

Converting at build time reuses the whole PDF pipeline (pages, `frac` marks, zoom, search, page list, comparison PDF), so it is the least viewer work. Its costs, measured against the current code:

| Cost | Where it shows |
| --- | --- |
| A TeX toolchain and CJK fonts just to show Markdown | `builds/engine.py` latexmk path; the converter's preamble needs `kotex` and other packages (an external-tool stop signal, [architecture.md](../../handbook/architecture.md) §멈춤 신호) |
| Silent stale pages after a Markdown-only edit | `builds/artifacts.py` `SRC_TEX_EXTS` drives `src_mtime`, `stale_build` and the fingerprint; `.md` is not in it, and the generated file is filtered out of the reads digest, so the build ends `BuildUnchanged` |
| Print pages for a screen format | Markdown reflows; A4 pages on a phone need zooming |
| A hand-written Markdown→LaTeX converter | fenced code, display math, images, footnotes, HTML and `_emph_` are unsupported; `%`/`&` inside math can break a table row; lazy regexes are quadratic on long lines |
| Every new format needs its own "format → LaTeX" converter | extensibility grows by converters, each with escaping rules |

The detour exists only because the viewer can draw nothing but PDFs. The proposal removes that limit instead of feeding it.

## Proposal: two surfaces

A document is defined by **how it is drawn** and **how a picked spot maps back to its source**.

| Surface | Drawn by | Maps back by | Kinds |
| --- | --- | --- | --- |
| **PDF surface** (unchanged, primary) | LaTeX → PDF | SyncTeX | `tex` |
| | the PDF itself | none (page and region) | `pdf` (view-only) |
| | a figure PDF plus element map | the element map | `figure` |
| **HTML surface** (new) | the browser, from the source text | every rendered block carries the source line range it came from | `markdown` (`.md`) first; later plain text and code |

On the HTML surface the viewer renders the source directly. Each block element (paragraph, heading, list item, table row, code block, quote) carries its source line range, so a selection maps to `lo..hi` by construction — no SyncTeX, no build step, no generated file. LaTeX documents and everything built on the PDF surface stay exactly as they are.

### Scope of the first phase

- Kind `markdown` registered by suffix `.md` (`--doc KEY=NAME:path.md`, `limn doc add`), served without a build.
- Read view: reflowing render on all four device groups; headings as the outline; in-document search over the rendered text.
- Line pins on Markdown: pick by text selection or block tap → `file`, `lo`, `hi`, `quote`; marks drawn on the rendered blocks; the composer, card, edit card, overlap rules and anchor re-sync work on the `.md` file.
- Range ladder for Markdown: selected lines → block → section (heading to next heading of the same or higher level). No LaTeX environment rungs.
- Suggested-edit pins on Markdown line pins, showing raw Markdown in the editor (partially supersedes ADR-0020 D1, which limits suggestions to LaTeX).
- Change view: source diff and pin-scoped hunks for `.md` files (`revisions/core.py` pathspec gains `md`). No rendered comparison yet.

Out of scope for the first phase: rendered before/after comparison, plain text and code kinds, images outside the manuscript tree, raw HTML in Markdown, Markdown extensions beyond CommonMark plus GFM tables.

## Design decisions to settle before implementation

1. **Pin geometry on the HTML surface.** Markdown pins have no `page`/`frac`. Proposal: they are ordinary line pins (`file`, `lo`, `hi`, `kind`, `scope`, `quote`) with `page` and `frac` absent; marks are drawn from `lo..hi` on the rendered blocks. This is additive for the record (no new stored field) but every reader that assumes `page`/`frac` on a line pin must accept their absence. Alternative: store a block index — rejected, it does not survive edits.
2. **Kind value and old agents.** A new `kind: "markdown"` in `/api/docs` and `/api/meta` is honest but old agents follow SKILL rules written for `tex`/`pdf`/`figure` (for example "rebuild only `kind:"tex"`"). Markdown needs no rebuild, so an old agent's behaviour stays correct; the SKILL and `api.md` gain the new value. Precedent: ADR-0011 D5 extended the value lists in one change.
3. **Capabilities, not kind checks.** `runtime/documents.py` already routes behaviour through capabilities (`builds_from_source`, `watches_files`, `takes_line_pins`, `shows_revisions`, `view_only`, `has_element_map`). Add `renders_in_browser` (HTML surface) and keep `takes_line_pins` true for Markdown, `builds_from_source` false. The suggestion gate (`pins/editing/rules.py` `check_suggestion`, fed by `builds_from_source` today) moves to its own capability `takes_suggestions` so it no longer means "LaTeX".
4. **Markdown parser.** Rendering happens in the viewer. Proposal: vendor a CommonMark parser with source maps (markdown-it gives each block token a `map` of its source lines) under `src/limn/vendor/`, with raw HTML off. Vendoring is a stop signal (runtime bundle) and needs the ADR; the server stays stdlib-only because it never parses Markdown for display. Alternative: a stdlib Python renderer on the server that emits HTML with `data-lines` — more code to own and test, but no bundle.
5. **Security.** The rendered document shares the viewer's origin, which carries the user's identity. Raw HTML off; links limited to `http(s)`/`mailto` and relative paths inside the document's tree; images only from the manuscript tree through an existing checked file route; no inline event handlers; the rendered tree built with DOM APIs or sanitized. A document must not be able to issue API requests as the viewer.
6. **Line splitting.** The viewer's line numbers must equal the server's (`platform/files.py` uses `str.splitlines()`), including `\r\n`, form feeds and Unicode separators; a fixture pins this.
7. **Surface switching in the viewer.** The viewer is built around PDF.js pages (`pdf-open.js`, `pdf-draw.js`, `pages.js`, `selection.js`, `gestures.js`, `zoom.js`, `search.js`, `outline.js`, `page-list.js`). The HTML surface is a second document pane behind the same tabs, panel, list and composer; page-only controls (page field, page list, PDF zoom, rebuild) hide for it, and the phone sheet, keyboard and bottom action row rules in [viewer.md](../../handbook/viewer.md) apply unchanged.

## Change points (from a read-only survey of the current code)

| Area | Files | Size |
| --- | --- | --- |
| Registration: `DocKind`, capabilities, suffix rules, messages, `doc_start_line`, `apart_paths`, shell validator | `runtime/documents.py`, `administration/serve_documents.py`, `administration/instance_documents.sh`, `server.py` | medium |
| Serving the source and file-change polling (no build) | `documents/`, `builds/` (watch like `watches_files`, without import) | medium |
| Pick for Markdown (selection → lines), ladder for Markdown | `pins/location/` (`mapping.py` `compute_levels`, `resolve.py`, `http.py`) | medium |
| Pins without `page`/`frac` on a line pin | `pins/model.py`, `pins/record.py`, `pins/listing/render.py` (`pins.md` page column), `builds/document_facts.py` | medium, contract |
| Suggestion gate as a capability | `pins/editing/rules.py`, `pins/editing/service.py`, `pins/editing/http.py` | small, contract (new ADR partially superseding ADR-0020 D1) |
| Change view for `.md` | `revisions/core.py` pathspec and window; viewer defaults to source diff for Markdown | small to medium |
| Viewer HTML surface | new parts (render, marks, selection, search, outline) plus `core.js` `DOC_KIND`, `doc-tabs.js`, `composer.js`, `cards.js`, `suggest.js`, `boot.js`, `status.js`, `page-list.js` | large |
| Vendored parser and its licence notice | `src/limn/vendor/`, `THIRD_PARTY_NOTICES.md` | small, stop signal |
| Handbook and skill | `purpose.md` (scope), `architecture.md`, `domain.md` (capability table), `api.md` (kind values, pins without page), `viewer.md`, `instances.md`, `operations.md`, `build-sync.md`, `skill/SKILL.md` and `.ko.md` | broad |
| Tests that enumerate kinds | `documents/tests/test_meta.py`, `administration/tests/test_serve_documents.py`, `runtime/tests/test_startup.py`, `administration/tests/test_instances.sh`, viewer tests on `DOC_KIND`, contract snapshots | medium |

## Phases after the first

1. Plain text and source code files on the same surface (one block per line or per paragraph).
2. Rendered comparison for Markdown (two rendered versions with changed blocks marked).
3. Other line-based formats with a renderer that keeps source positions.

## Verification

- Pure tests: Markdown line splitting equals the server's; ladder rungs; selection → lines on fixtures with tables, nested lists, code blocks and CRLF.
- Contract tests: `/api/docs` and `/api/meta` with `markdown`; a Markdown line pin without `page`/`frac` round-trips and renders in `pins.md`; older-version rollback keeps such records.
- Security tests: script, event-handler, `javascript:` link and out-of-tree image fixtures render inert.
- Viewer: behaviour tests for pick, marks, composer, suggestions on Markdown; all existing PDF-surface guards unchanged; the four-device-group PoC.
