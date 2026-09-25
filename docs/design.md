# Design and rationale

Open this when restructuring something, or when a result looks wrong and you need to find out why. Covers when to use this (original text), the architecture, reverse mapping, the scope ladder, line resync, storage safety, author attribution, the mobile layout and panels, design tokens and components, vector rendering (PDF.js), PDF-area-only zoom, and known limitations.

## When to use and when not to (original)

Activates when: the user says "fix this part" while trying to paste a screenshot, or points at a specific spot in the manuscript PDF and asks for a change. Also activates when processing pins that have already piled up (`<state_dir>/pins.md`).

- When the user wants to point at a specific paragraph, table, figure, or equation on screen and say "change this like so."
- When you want to pile up reviewer comments or co-author feedback as markup on the manuscript PDF (a pin = a located TODO). A co-author can enter from the same tailnet address and leave pins, and who left them is recorded (§Author attribution).
- When an agent processes the open pins in bulk, either at session start or when the user says "check the pins."

When not to use it:

- If the manuscript doesn't build under SyncTeX yet (a structural compile error), fix the build first with `latex-editing`.
- If the location is already unambiguous (e.g. the user already knows the file:line), skip this and go straight to `manuscript-revision` — the overhead of standing up a server is wasted.
- Doesn't apply to Typst manuscripts (SyncTeX is LaTeX-only). Typst position mapping is out of scope for this tool.

## Architecture overview

```
Browser (drag to select a region)
   │  coordinates
   ▼
limn serve  ──(1)──▶  builds a copy of <manuscript_dir> in a separate
  127.0.0.1:<port>      build directory with latexmk -synctex=1 (never touches the original checkout)
   │
   ├─(2) races two reverse-mapping paths, then computes the scope ladder (dragged line/paragraph/environment) → snippet
   ├─(3) the user attaches a note and saves it as a "pin" → <state_dir>/pins.jsonl (lock + atomic replace)
   └─(4) regenerates <state_dir>/pins.md — the one file an agent reads
```

Why building happens from an rsync copy instead of opening the original checkout directly: so a build never catches the manuscript mid-edit even while it's being edited concurrently. The mapping that turns a build-copy path back into an original path (`build_dir → manuscript_dir`) is handled internally by the server — an agent is always told the original path. If the state directory is moved or duplicated and synctex points at an old build path, the path is only rewritten when its tail matches a file inside the manuscript tree; anything outside that tree is never read.

## Why reverse mapping uses two paths

`synctex edit` alone isn't enough. Inside `minipage`·`tabular` (typically a nomenclature table), SyncTeX nodes are sparse, and selecting that area **silently lands on the wrong body-text line** — confirmed by measurement. So a second path pulls the actual characters covered by the selection rectangle via `pdftotext` and looks them up in the source. Korean word units rarely pass through markup unchanged (e.g. `타겟--소스 $i$ 간 코사인 거리`, "cosine distance between target--source $i$"), so they survive intact in the source.

The two paths **compete on the same scale rather than one being a conditional fallback for the other.** Pinning either one as primary means there's no way to catch it when that path is silently wrong. Scoring is based on how much of the region's word units fall within a candidate line range, but **weighted by word rarity** — without that weighting, common words like "데이터" ("data")·"학습" ("training") dominate the score, and a body paragraph scores as well as a nomenclature table (also confirmed by measurement). Ties favor SyncTeX, since it's the only path that works on a region with no text (a figure).

The response's `via` (`synctex`/`text`) and `score` (0 to 1) report which path was used and how confident it is. The UI attaches nothing when the match is 90% or higher, and only shows a "position uncertain" badge when it's lower (a warning color under 30%). The badge's tooltip states what method was used (coordinates/text), the match rate, and what to check — the old `일치 93%`·`글자 일치 100%` labels ("match 93%"·"text match 100%") didn't convey any of that (§Status representation).
If `score` is low, the server also returns a warning message.

## Scope ladder

`POST /api/pick` returns not one line range but a list of levels (`levels`). The client switches between levels without a round trip to the server.

| `level` | Meaning |
| --- | --- |
| `raw` | The line(s) the drag directly pointed at |
| `para` | The paragraph containing that line. Pure `%`-comment lines before/after are excluded — this stops a TODO comment from becoming part of the range and the anchor tail in a manuscript where one line is one paragraph. Never crosses a section-heading line, never leaves the innermost enclosing environment (excluding the `\begin`/`\end` lines themselves when inside one), and never half-straddles an environment outside the drag |
| `env`, `env2`, `env3` | The enclosing `\begin{X}…\end{X}` from the innermost outward, up to 3 levels (any name, excluding `document`). If an outer environment wraps the inner one by exactly one line front and back, they're treated as the same block and merged |
| `lines` | The range the user adjusted directly with the one-line +/− step buttons |

Levels with identical ranges are merged (`merged`), and the default level (`default_level`) is that `env` level if it's inside a `--float-envs` environment, otherwise `para`. The response's `lo`/`hi`/`kind` are the default level's values. There's no section level (that would too easily produce hundred-line ranges).

## Line renumbering resync (`anchor`)

**The whole point of this tool is "an agent edits the manuscript" — a design where fixing a pin kills the pin isn't usable.**
Fixing one pin by adding three lines shifts every pin below it.

So when a pin is saved, the **head and tail text** of the block are captured alongside it (`anchor`, skipping pure comment lines). The number of skipped comment lines is kept as `head_off`·`tail_off`, so a pin that deliberately included leading/trailing comment lines doesn't shrink after resync. Any request that reads or writes a pin re-locates that text and refreshes `lo`/`hi` whenever the target file's mtime is newer than `synced_at`. Since `rev` increments whenever a line moves, an edit sent from a stale screen is caught with `409`.

| Outcome | `sync` | Display |
| --- | --- | --- |
| Unchanged | `ok` | — |
| Shifted | `moved +3` | Updated to the new line numbers ("moved +3 lines") |
| The head line vanished from the source | `lost` | `stale: true` — a warning in the UI ("position lost") and in `<state_dir>/pins.md` |

A `stale` pin is never guessed-and-closed. It's reported to the user (who can fix it via [Edit] → relocate). The exception is when that range is exactly what you yourself just edited (e.g. an earlier pin's fix rewrote that very sentence) — in that case, check the source and it's fine to close it (see SKILL.md's pin-processing rules, linked from [`SKILL.md`](../skill/SKILL.md)).

## Storage safety

- Every code path that touches the pin file follows, under one lock: **read → resync → apply the requested change → write to a temp file and `os.replace` → regenerate `<state_dir>/pins.md`**. Before locking existed, saving 30 pins concurrently left only 2 of them (observed).
- `pins.jsonl` is **rewritten in full each time**, not append-only. Appending state-update records would make every reader fold up the event log, so instead one file simply *is* the current state — simpler, with less room for error.
- Ids are issued from `pins.seq` and never reused after a delete or `clear` — a "#2" mentioned in chat should never point at a different pin. If the file doesn't exist, it's seeded once at startup from the current max id.
- An unparseable line, or a JSON record with a malformed `id` (integer)·`file` (string)·`lo`/`hi` (integer, `1 ≤ lo ≤ hi`)·`page` (integer, if present), is skipped with a warning, and the original file is preserved as `pins.jsonl.corrupt-<timestamp>.bak` right before the first write in that state. A single bad record never turns a `GET` into a `500`.
- `<state_dir>/pins.md` is built in memory first, then written in the order `pins.jsonl` → `<state_dir>/pins.md`. If rendering fails, nothing is written — committing and then returning `500` would make a retry create a duplicate pin.
- Restoring a pin (`restore`) only removes it from the drop record after the `pins.jsonl` write has succeeded. If the process dies mid-way, the worst case is "it exists in both places" (recoverable), never "it exists in neither."

## Author attribution

A co-author enters pins from their own computer, over the same tailnet address. Tailnet members are trusted colleagues, so **access is never restricted — only who-did-what is distinguished.**

- `tailscale serve` attaches `Tailscale-User-Login`, `Tailscale-User-Name`, and `Tailscale-User-Profile-Pic` headers to every request. Non-ASCII names arrive RFC 2047-encoded, and the server decodes them before storing. Since the server binds only to `127.0.0.1`, these headers can only arrive via tailscale (a local process on the same machine could of course spoof them — this is attribution, not authentication).
- A request with no headers (local `curl`, an agent) is recorded as `{"login": "local", "name": "로컬/에이전트"}` ("local/agent").
- A pin card shows the author's name and a 22px circular avatar (the first letter of the name if there's no photo or it fails to load); the tooltip on the name/avatar reads "created: name · time / edited: name · time" (작성: 이름 · 시각 / 수정: 이름 · 시각). The card as a whole has no tooltip — with one on the whole card, the tooltip popped up no matter where the pointer was while reading the note, and lingered above the list after a tap on phones (QA 2026-09-24). Devices with no hover (`(hover:none)`) never show hover/focus tooltips at all — only long-press. A pin from before this feature existed shows as "기록 전" ("before this was recorded").
- `<state_dir>/pins.md` has no author column ([api.md](api.md) §pins.md format) — who left a pin is only visible via `GET /api/pins`'s `author`/`edited_by` fields or the viewer card.
- There's no permission restriction. If you need to block someone, pass a login allowlist with `--allow`. A tailnet request with no identity header, like one from a tagged device, is rejected when `--allow` is set and recorded as `로컬/에이전트` ("local/agent") when it isn't ([operations.md](operations.md) §Command-line arguments).
- Who handles what is also never split up by author (author's decision, 2026-09-22) — whoever was asked to process the pins handles all of the open ones (SKILL.md).

## Mobile layout

Added to fix narrow body text and drag-vs-scroll conflicts on foldables (Galaxy Z Fold 7: folded screen roughly 412×915, unfolded roughly 880×790 CSS px) (2026-09-23). The server API and pin format are unchanged — only the viewer changes.

| Layout | Condition | Sidebar | Table of contents |
| --- | --- | --- | --- |
| `wide` | ≥1100px | Right-hand panel, default 348px, resizable | Fixed left panel; collapsed state and width are remembered |
| `mid` | 701–1099px, independent of input device | Default 330px. 701–900px starts as a collapsed overlay, 901–1099px starts open beside the document. Only opens/collapses between the top nav bar and the bottom action bar (§Unfolded-screen layout) | Starts collapsed. When expanded, overlays the document; opens exclusively with the pin panel |
| `narrow` | ≤700px | Bottom sheet, collapsed by default; resize by dragging the top-edge handle | Keeps the existing mobile document-switch behavior |

- The layout is chosen by JS from `innerWidth` (`layoutFor`). `pointer:coarse` only affects touch button size and selection input. When collapsing/expanding changes the width, `resize`·`ResizeObserver` re-pick the layout on the next frame and refit the page width while preserving the viewing spot (`topAnchor`). Marks and the selection box use page-relative % coordinates, so they don't need to be moved separately.
- **A single table-of-contents toggle**: `#nav-toc-toggle`, at the far left of the document nav bar, stays in the same spot whether open or closed. It updates `aria-expanded` and its accessible name and responds to Enter/Space. At medium width, the table of contents closes on Escape or on picking a chapter/section, returning focus to the toggle. The page and in-page ratio from before opening it are restored on close. Opening the table of contents at medium width and collapsing the pin panel never changes the desktop table-of-contents saved state.
- At medium width, manually opening/closing [Pins] is remembered in `pinPrefs.midClosed` and persists across width changes. With no saved choice, the default above kicks in when crossing the 900px boundary. The panel stays open while a note is being written or edited.
- **Top area**: document links keep to one line, scrolling horizontally within that line if needed. At medium width, the label goes into [more], and the view switcher and table-of-contents button never shrink. The nav bar is 44px for mouse, 48px for touch. The first-run hint appears below the nav bar in `wide`, and just above the action bar (above [Select]) at the left in `mid`; the hint text doesn't intercept clicks — only its close button does.
- In compact layouts (`mid`·`narrow`), the page width is always fit to the screen and never saved (pressing −/+ keeps it only for that layout session). This keeps a folded screen's width from overwriting the desktop setting.
- The toolbar keeps just four items: `[핀 N]` ("[Pins N]", panel/sheet toggle, open pin count) · `[선택]` ("[Select]", touch only) · `[PDF 재빌드]` ("[Rebuild PDF]") · `[더보기]` ("[More]"). Re-read pins, page navigation, zoom out/in, fit width, theme, help, closed pins, and dropped pins all move into the `[더보기]` ("[More]") dialog (along with the file, page count, commit, build time, and author line). The manuscript-edited, build-in-progress, disconnected, and build-error chips stay above the toolbar even when it's collapsed (`mid` shows them as a card just above and to the right of the action bar).
- Pin cards are accordions — a collapsed card shows only a one-line header (number, line range, page … assignee chip, reply count, collapse) and a two-line note preview (`.sum`) below it; tapping expands the tags, note, and buttons. The preview used to only get the leftover width of the header line, cutting it down to something like "[C…" — fixed (QA 2026-09-24). A pending-review card's preview no longer gets "내 확인 차례 · " ("my turn to review · ") prepended — the purple dot already communicates the state. Tapping a mark badge opens the panel and expands that card. `wide` keeps the old card as-is.
- Selection input is a single Pointer Events path. A mouse always drags to select, regardless of mode. Touch and pen only turn a one-finger drag into a rectangle when **selection mode** is on (`touch-action:none` on the page — §PDF-area-only zoom handles two fingers), and a tap is **quick select**. Outside selection mode, scrolling and zooming work as normal and a **long press (450ms)** is quick select. Quick select calls the existing `/api/pick` with a small box around the pressed point (±7% of page width, ±0.6% of height) — the server's default level is "paragraph" in body text and "environment" in figures/tables, so it's used as-is and widened with the scope ladder. Selection mode turns off by itself on save or cancel (so scrolling resumes). A second finger touching down discards the box being drawn.
- Coordinates are the page-relative ratio of `clientX/Y` divided by `getBoundingClientRect`. Both are in the same layout-viewport frame, so they stay correct even during a browser pinch-zoom (verified with Playwright at 5× scale, dragging afterward with error under 1e-8). Browser pinch is now blocked over the PDF area in favor of the app's own zoom (§PDF-area-only zoom).
- Simulated `mouseover`·`focusin` right after a touch never trigger a tooltip. A tooltip only shows on a long-press of a button, and the `click` that follows lifting the finger is swallowed (so the button doesn't also activate). After a touch selection, the note field never gets auto-focus — the virtual keyboard used to cover the scope ladder.
- The virtual keyboard is handled via the viewport meta's `interactive-widget=resizes-content` (Chrome on Android) shrinking the layout itself; browsers that don't understand that value instead raise the screen by the height measured via `visualViewport` (`--kb`). A `visualViewport` shrunk by pinch-zoom is scaled back by `scale` so it isn't mistaken for the keyboard.
- On touch devices (`pointer:coarse`), buttons and input fields are at least 44px, input text is 16px (prevents iOS auto-zoom on focus), and safe areas (`env(safe-area-inset-*)`, `viewport-fit=cover`) are kept clear. In compact layouts, notifications move to just below the nav bar (`narrow`: top of screen; `mid`: top-left of the body) so they don't collide with the bottom toolbar or the first-run hint.

## Unfolded-screen layout

Fold-7 user feedback (2026-09-24): on an unfolded screen, collapsing/expanding the panel with `[핀 N]` ("[Pins N]") made the button jump between top-right (panel header) and bottom-right (a floating toolbar) — measured y 56 ↔ 693 at 842×758, y 56 ↔ 1039 at 884×1104 — and the beside-document panel (901–1099px) clipped the document nav bar by its own width (630px of nav bar left at 968px). So `mid` now fixes the screen into three tiers. `wide`·`narrow` are unchanged.

| Tier | Position | Contains |
| --- | --- | --- |
| Top | Nav bar `#doc-nav`, full screen width, `position:fixed` | Table-of-contents toggle · document links · `원고`/`변경사항` ("manuscript"/"changes"). Never clipped by the panel |
| Middle | Body (`#main`) and panel (`#right`) | The panel only extends from below the nav bar to above the action bar (701–900px overlays the document; 901–1099px sits beside it) |
| Bottom | Action bar `#bar1`, full screen width, `position:fixed` | `[선택]` ···· `[PDF 재빌드] [⋯] [핀 N]` |

- **Hand ergonomics**: an unfolded fold or a tablet is usually held with two hands, thumbs reaching the bottom corners. So frequent actions were moved to the bottom — `[선택]` ("[Select]") at the bottom-left (a PDF-side tool, so it's under the document-side thumb), the panel toggle `[핀 N]` at the bottom-right where the panel appears, with `[⋯]` and `[PDF 재빌드]` next to it. The composer's `[취소] [핀 저장]` ("[Cancel] [Save pin]", `#c-actions`) sits at the bottom of the panel, right above the action bar, so it's within reach of the right thumb. Rare actions (page navigation, zoom, theme, help) stay in `[⋯]` as before. Pinning things to the bottom also matches the `narrow` bottom sheet's direction.
- **Nothing moves**: the action bar doesn't follow the panel, so `[핀 N]` sits in the same spot whether the panel is open or closed (measured ±0px at 842×758·968×842·884×1104·820×1180). Its width is also floored at 88px, so a growing pin count doesn't shift the right edge as the label gets longer. The open state is shown with the button's fill color (`--accent`) and an arrow (`›` open / `‹` closed), plus `aria-expanded="true"`.
- **Implementation**: the toolbar stays inside `#right` in the DOM but is pulled out visually with `position:fixed` — because the `narrow` sheet reuses the same markup as a sticky element below its handle. So `mid`'s `#right` never gets `transform`·`filter`·`opacity`·`contain` (that would change a fixed child's containing block and make the action bar move with the panel). Button order is changed with CSS `order` only (keyboard focus order stays the DOM order, `[핀]→[선택]→[재빌드]→[⋯]`). Body and panel are only drawn between `body`'s top/bottom margins (`--mid-top` = nav bar + top safe area, `--mbar-h` = toolbar height + 16px + border + bottom safe area). The action bar is 60px on touch (44px buttons), 44px on mouse (28px buttons).
- **Collapsed panel**: `#right` remains as an invisible frame (accepts no input); only the status-chip row (`#bar2`) and the relocate banner (`#banner`) float as a card just above and to the right of the action bar.
- **Open/close motion**: the overlay (701–900px) slides the panel in from the right over 0.18s (only `right` moves — the constraint above). The beside-document panel (901–1099px) changes the PDF's width, so it switches instantly with no motion. `prefers-reduced-motion: reduce` removes all motion (a global rule).
- **Overflowing document links**: they scroll horizontally within the line, fading the overflowing edge instead of showing a scrollbar (`.fade-l`·`.fade-r`, `docLinksFade`). When the document changes, the current document's link is scrolled into view (a redraw from polling leaves the user's own scroll position alone).
- **First-run hint**: shown as a small chip just above the action bar, at the left (above what it's pointing at, `[선택]`), so it never covers the nav bar or panel. Notifications sit just below the nav bar at the top-left, so they don't collide with the first-run hint.

## Panel cleanup and width adjustment

Cleaned up after feedback (2026-09-23) that the composer panel looked cluttered on an unfolded foldable (880×790). Server API and pin format are unchanged.

- **One spacing system**: an 8px grid, buttons on the same row share a height (44px touch, 48px action bar). The accent color (`--primary`, `.btn-default`) is reserved for exactly one primary action, [핀 저장] ("[Save pin]"); a card's [완료] ("[Done]") is a soft blue (`.btn-soft`, an author choice from 2026-09-23), and [삭제] ("[Delete]") is a soft danger color (`.btn-destructive`). Everything else is outline-only (§Design tokens and components).
- **Toolbar** (compact): the collapsed fold/phone sheet orders things by frequency of use — `[핀 N] [선택] [문서] ··· [재빌드] [⋯]` (QA 2026-09-24). The pending-review count is a pill inside `[핀 N]` (it used to float half-off the button's corner), `[선택]` gets a leading `square-dashed` icon matching the on-PDF dashed selection box, `[PDF 재빌드]` is rare enough to go icon-only (name via `aria-label`/long-press), matching `[⋯]`'s borderless ghost style. All joined in one row at the same height. Gaps are 4px (`--space-1`); if width runs out, the label chip shrinks first (`flex-shrink: 50`, minimum 28px, full name in the tooltip) — it used to clip button text down to something like "DF 재빌드" ("...D rebuild"). The desktop toolbar wraps to two rows when the panel is narrowed. On a collapsed fold (`narrow`, measured at 344px), the label chip is pulled out of the toolbar entirely and placed at the top of `[더보기]` ("[More]", `#more-label`, dialog title `더보기 · <label>`, "more · label") — a shrunk chip left only "C…", unreadable, and the top label-color stripe already distinguishes the instance. In that spot, the `[문서]` ("[Document]") button never shrinks and always shows the short document name (body·response·cover letter, roughly 5 characters — confirmed with `커버레터` ("cover letter"), one line, no clipping).
- **Toolbar height**: buttons and the page field share one height (`--tb-h`: 28px desktop, 44px touch), and icon buttons are square. The page field is 54×28px·`--text-base`·left-aligned with placeholder `쪽 이동` ("go to page") (touch: 84×44px·`--text-xl` 16px — prevents iOS zoom). The single-character `쪽` ("page") field and the word button `폭` ("width") both read like passwords or noise (QA 2026-09-24) — fit-to-width is now a `move-horizontal` icon button. In the default 348px panel, the mouse toolbar `[PDF 재빌드] [쪽 이동] [−] [＋] [↔] [알림] [테마] [?]` ("[Rebuild PDF] [go to page] [−] [+] [fit width] [notify] [theme] [?]") fits on one line. Hierarchy: page/zoom-out/zoom-in/fit-width are outlined navigation controls, notify/theme/help are borderless utility icons, and `[PDF 재빌드]` ("[Rebuild PDF]") is dim ghost text (promoted to `.btn-default` once the manuscript is newer than the PDF). Touch, or a panel the user narrowed, wraps rows as needed. [Re-read pins] lives at the top of the open-pin list's [Reread] link, and sits inside `[더보기]` ("[More]") in compact layouts.

- **A single location line**: `파일 L159` ("file L159") + page + (only when the score is low) a "position uncertain" badge + [Copy]. It used to repeat the same information three times — file·line, a match-method badge, and a line like "page 1 · paragraph · 1 line · dragged line". The scope kind and line count are already visible in the segmented control's selected item, and the dragged-line detail moved into the page indicator's tooltip. A one-line "specify manually" link appears next to the page indicator if the one-line buttons don't fit any of the segments.
- **Scope ladder**: a single-row segmented control. Segment labels are short (`문단 · 1줄` "paragraph · 1 line", `abstract · 19줄` "abstract · 19 lines", `frontmatter · 73줄` "frontmatter · 73 lines"); "(바깥)" ("(outer)") is only appended when the same environment name repeats. Line ranges moved into each segment's tooltip and `aria-label`. Overflow scrolls horizontally and scrolls the selected segment into view. Fine adjustment is a single attached stepper (`위 [+][−] 아래 [+][−]`, "top [+][−] bottom [+][−]").
- **Source text**: collapses to 4 lines by default (fades out if it overflows), with a left [줄바꿈] toggle ("[wrap]", the `text-wrap` icon, filled like the diff view's [줄바꿈] toggle when on) on the line right below it, and [원문 펼치기] ("[expand source]") on the right. [줄바꿈] used to sit at the end of the stepper row, where it fell alone onto a new line on a folded 330px panel (QA 2026-09-25). Both change how the source is displayed, so they're grouped right below it. Since long single lines that wrap across several visual lines are common in this kind of manuscript, overflow is measured by rendered height rather than line count.
- **Action row**: `[취소] [핀 저장]` ("[Cancel] [Save pin]") split 1:2, pinned to the bottom of the panel (`#c-actions`, outside the composer, after the list). `wide` pins it to the bottom of the panel's flex column; compact pins it to the sticky bottom of the scroll box (`#right`) so it stays visible whether the list is scrolled or the keyboard is up (the layout shrinks / `--kb`). The `narrow` sheet raises the note field above the source text (so the note field never hides beneath the action row).
- **Saving right after a drag (P0c fix)**: the drag → SyncTeX `/api/pick` round trip takes about 1.1s (`#c-spin`), during which [핀 저장] ("[Save pin]") stays pressable — it used to silently do nothing (`CUR` wasn't set yet, so `savePin()` was a no-op) and the note vanished (⌘/Ctrl+Enter took the same path). Now, pressing save before the pick finishes queues the request (`PEND_SAVE`) and the button changes to "위치 찾는 중… 저장 대기" ("locating… queued to save", with a spinner). The note text is never snapshotted — the moment the pick resolves and the save actually happens, `#note` is re-read fresh, deliberately picking up anything typed while waiting. A successful pick auto-runs the queued save; a failure (`d.error`, a network error) clears the queue without saving, leaving only the existing error panel. Pressing the button again, or [Cancel], cancels the queue (a toggle) — Ctrl+Enter follows the same path as the button, so it behaves the same.
- The first-run hint paragraph (`#empty`) is hidden while a selection is in progress.
- **Pin card**: the header has number·line range·page (left) and a right-hand group `.h-meta` (assignee chip·reply count·author) · collapse, with badges on the line below. When space runs out, `.h-meta` wraps as a whole group to the next line on the right — cramming it all onto one line used to clip the author's name down to a single "W" when there was also an assignee chip (QA 2026-09-24). Within the group, the assignee chip's name truncates first (`담당 @Sa…`, "assignee @Sa…"), then the author's name. Actions are an equal-width grid, `[보기] [수정] [삭제] [완료]` ("[View] [Edit] [Delete] [Done]", plus [Unclaim] when in progress).

Panel width:

| | Unfolded screen (`mid`) | Desktop (`wide`) |
| --- | --- | --- |
| Minimum | 300px — the width where the touch toolbar still fits on one row | 280px (unchanged) |
| Maximum | 701–900px: 440px overlay. 901–1099px: screen − 488px (480px body + 8px handle) | `min(80%, screen − 486px)` |
| Default | 330px | 348px |
| Steps (narrow · normal · wide) | 300 · 330 · 50% (clamped within the limits) | 300 · 348 · 42% (clamped within the limits) |
| Remembered as | `pinPrefs.sideMid` | `pinPrefs.side` (unchanged key) |

- The handle (`#grip`, `role=separator`) is a single Pointer Events implementation shared by wide and mid (replacing desktop's old `mousedown`-based one). The visible bar is 6–8px, and the grabbable area is 24px via `::after` on touch (12px on mouse, so it doesn't cover the body's scrollbar). The handle is `touch-action:none`, so dragging it never fights scrolling, and `setPointerCapture` keeps tracking even past the handle's own bounds. `mid` draws the grab bar centered.
- While dragging, only the panel width changes (`body.resizing` suppresses `ResizeObserver` refitting); releasing runs one `relayout` to refit the page width. Marks and the selection box are page-relative % coordinates, so they land correctly on their own (measured error under 0.02px). The viewing spot is preserved via `topAnchor`.
- Buttons: on touch, **tapping** the handle cycles narrow → normal → wide; on mouse, a **double-click** does the same (a single click doesn't jump the width). A "panel width" segmented control lives inside `[더보기]` ("[More]"). Keyboard: ←/→ steps 16px, Home/End hit the limits, Enter/Space cycles.
- When the screen width changes (fold/unfold), the saved width is kept and only the visible width is clamped to the current limits — going back to a wider screen restores the saved width.
- **Sheet height** (narrow): dragging the top-edge handle (`#sheet-grip`) resizes it, and releasing below 25% of the screen collapses it. Dragging up or tapping a collapsed sheet expands it. Tapping an expanded sheet cycles low (45%) → normal (64%) → high (screen − 48px); `[더보기]` ("[More]") offers the same as a "sheet height" choice. Height is remembered as a fraction of screen height (`pinPrefs.sheetF`), and CSS shrinks it to fit when the keyboard comes up.

## Toasts

The `핀 #N 저장됨 · 되돌리기` ("pin #N saved · undo") toast that appears after saving used to pop up far from the panel (desktop bottom-left — 1,133px from the save button's center; on a fold, top-left of the body — 810px) (author feedback, 2026-09-24). Now it appears near wherever you just pressed.

| Layout | Placement (`placeToasts()` measures and sets `--toast-r`·`--toast-w`·`--toast-b`) |
| --- | --- |
| `wide` | Bottom-right inside the panel column (column width − 24px, capped at 380px). While composing, just above the save/cancel row (`#c-actions`) |
| `mid` | Right side of the panel, just above the bottom action bar (`#bar1`). While composing, above the save/cancel row; with the panel collapsed, above the floating status chips (`#bar2`·`#banner`) |
| `narrow` | Just above the top of the sheet, screen width − 16px. If the sheet covers more than 70% of the screen (no room above it), it moves inside the sheet, near the bottom — above the save/cancel row if it's visible. Raising it above the screen used to cover the sheet's own toolbar (`[더보기]`, "[More]") |

- On touch devices, the toast body passes taps through (only its buttons intercept them) — so a toast appearing right above the sheet never steals a long-press on the PDF.
- Its position is re-measured every 250ms while visible (`watchToasts`) — so opening the composer or resizing the panel never covers the save/cancel buttons or the toolbar below.
- Its look follows sonner: a single floating surface (`--popover` background, a thin `--border`, `--radius-lg`, `--shadow` — shadow is reserved for floating surfaces), a leading state icon (done `circle-check` green · warning `triangle-alert` amber · error `circle-x` red), one bold title line + one dim description line, small outline action buttons ([되돌리기]·[열기], "[undo]"·"[open]"), and a close `x`. The text is split at the first ` — ` (or the first ` · ` if there's none) into title and description (`toastSplit` — a toast's title is `핀 #10 · 본문`, "pin #10 · body"). No color stripe.
- New toasts stack on top; past 3, the rest collapse (hovering or focusing expands them). They disappear after 6 seconds, paused while hovered. The entrance motion (0.16s) is turned off under `prefers-reduced-motion`.

## Status representation

The left vertical color stripe is gone (author feedback, 2026-09-24 — "tacky, looks like AI slop"). An open card is distinguished by a **small dot (8px) at the front of the header** and a **badge with the same meaning** (text·icon); closed and dropped pins are distinguished by a **leading icon** on their dimmed archive row — no state is ever conveyed by color alone (the dot also carries `aria-label` and a `상태: …` ("state: …") tooltip). Badge text is written to be self-explanatory (author feedback, 2026-09-23: `⏳ 처리 중 · ~04:02`·`#20 안`·`일치 100%` ("in progress"·"inside #20"·"match 100%") weren't).

| State | Dot/icon | Text (badge) | Shape |
| --- | --- | --- | --- |
| Open | Green dot `--status-open` | None (default) | Card |
| In progress (claimed) | Amber dot `--status-claimed` (dark `#f0b43c`, light `#b86e00`) | `clock` `처리 중 · …` ("in progress · …") | Card |
| Pending review | Purple dot `--status-review` (dark `#b197fc`, light `#6d28d9`) | `eye` `<author>님 확인 필요` ("… needs to confirm") | Card (§Threads and review), pending-review section |
| Reopened | Green dot (open) | `rotate-ccw` `다시 열림` ("reopened") (a warning color, who/when/why in the tooltip) | Card — when the thread's last close/reopen entry is a reopen |
| Position lost | Warning-color dot `--status-warning` | `triangle-alert` `위치 잃음` ("position lost") | Card, border also warning-colored |
| Question | (same dot as open) | `circle-question-mark` `질문` ("question", primary color) | Card — a kind, not a state |
| Done | `check` green `--status-closed` | Close time · one-line reply | Archive row (§Archive) |
| Dropped | `trash-2` gray `--status-dropped` | One-line note | Archive row, dimmer text (`--subtle-foreground`) |

Dot/icon colors meet 3:1 (non-text) contrast against both the card and panel backgrounds in both themes (3.7–10.0), and dimmed text meets 4.5:1 (`--subtle-foreground` is 5.3 dark / 4.8 light).

Badges:

| Badge | Meaning | Shown when |
| --- | --- | --- |
| `처리 중 · 약 15분 · 20:40쯤` ("in progress · ~15 min · around 20:40") | An agent claimed it with an estimate (`eta_min`). Remaining minutes and the time are both rounded up to 5 minutes | Has an estimate |
| `예상보다 늦어짐 (+5분)` ("later than expected (+5 min)") | Past the estimate (minutes over, rounded to 5). Warning color | Past the estimate |
| `처리 중 · 20:02부터 (23분째)` ("in progress · since 20:02 (23 min so far)") | Claimed with no estimate | A legacy-style claim |
| `#20 범위 안` · `#20과 같은 범위` · `#20과 일부 겹침` ("inside #20's range" · "same range as #20" · "partially overlaps #20") | Overlaps another open pin. One shown, in priority: same range > inside (narrowest containing pin) > partial overlap. The particle is chosen based on how the number reads aloud (`#2와`, `#20과`) | On overlap. The pins.md number column uses the same wording |
| `위치 불확실` ("position uncertain") | The dragged text matched under 90% of the found line range. Warning color under 30%. Tooltip explains "found by coordinates/found by text · N% match" and what to check | Only below 90% (also shown in the composer's location line) |
| `줄 +3 이동` · `위치 잃음` · `수정됨` ("moved +3 lines" · "position lost" · "edited") | Resync shifted it · lost its anchor · edited after saving | As-is |

The in-progress badge's time is the viewing device's local time, recomputed every 30 seconds. The lock auto-release time (`claim_until`) is never on the badge, only in the tooltip — it used to read as the expected completion time. The lock is only a safety net ([api.md](api.md) §In-progress marker).

## Meaning and appearance

Every visual distinction must carry meaning, and everything meaningful must be visually distinct (author feedback, 2026-09-24). Rules reviewed:

| What | Shape |
| --- | --- |
| A clickable reference (`#number`·line range·`N쪽`·an in-text `#12`·an archive row's line range·[원래 요청]·[변경 보기]·[스레드 N] — "[original request]"·"[view changes]"·"[thread N]") | One link style: primary-color text, no underline at rest, solid underline on hover/focus. Used to be three separate shapes (bold dotted underline · blue · gray dotted underline), now unified (QA 2026-09-24). Even in a dimmed archive row, only the clickable text is primary-colored. Gray text (author, time, `#20과 같은 범위` inside a badge) is never clickable. Dotted underline is now reserved for an unresolved "@word" (`.mention-bad`) |
| Copyable text (a line range, `.loc`) | Same link style, but monospace + `cursor:copy`, tooltip "click to copy" |
| Actions | One highlight per context (composer [핀 저장] = default, card [완료] = soft). The riskiest action is the least visually loud (card [삭제] = danger-colored text, no fill). A disabled button gets a not-allowed cursor; [핀 저장]'s "queued to save" state is dim primary color + a progress cursor |
| A person | A photo or an initial-letter circle (primary color). "You" gets `(나)` ("(me)") after the name (card author, thread poster) |
| An agent | A `bot` icon in a dim circle — visually distinct from a person's circle |
| Time | Threads and the archive use relative time (`방금`·`N분 전`·`N시간 전`·`N일 전`, "just now"·"N min ago"·"N hr ago"·"N days ago"; `M-D` past a week), absolute time in the tooltip. Recomputed every 60 seconds (`tickRel`). Archive times are never abbreviated (they used to read as `09-24 1…`) |
| Long text | A thread message collapses at 6 lines with a [더 보기] ("[show more]") button — one 1,000-character reply used to stretch a card to 1,390px (now ≈310px) |
| A pending-review or done card | Hides overlap/confidence badges (`#N과 같은 범위`·`위치 불확실`) — a closed pin isn't resynced, so they're meaningless |
| Reply count (`.th-n`) | Tapping expands the card and opens the reply field in one step (from a collapsed compact card) |
| Pending-review count | The status chip counts across all documents — if it differs from this document, it reads `검토 대기 2 (이 문서 1)` ("2 pending review (1 in this document)") |
| Filtering "pins addressed to me" | An `@` icon + count in the list header (name via `aria-label`/tooltip) — the header wrapped onto two lines at a 360px panel width |
| Focus | Every interactive element shares the same `:focus-visible` ring (2px `--ring`). A tooltip is only used where the meaning isn't already fully conveyed by text — a toast's close `x` gets only an `aria-label` |

A duplicate notification for the same event never fires twice: the browser-notification path (a toast if the tab has focus) and the list-comparison notification (`검토 대기로 넘어왔습니다`·`다시 열림`, "moved to pending review"·"reopened") both firing for the same pin's same transition within 8 seconds means the browser notification wins (`toastDup`, keyed by `<event>:<pin>`).

The [변경 보기] ("[view changes]") instructions line wraps its text instead of overflowing, and the [원고로] ("[back to manuscript]") button is never clipped (it used to run off-screen at 842px). Clicking [변경 보기] remembers the document you were viewing (`REV_BACK`) and returns you there; if it's a different document, the button reads `<document name>(으)로` ("back to …"). The source diff has a [줄바꿈] ("[wrap]") toggle, defaulted on for touch devices (a paragraph is one unbroken line of source, which was 6,273px wide on a phone; `pinPrefs.diffWrap`).

## Threads and review

Question pins (24% of them) and pins an agent closed that later got reopened (#28, #42) were the trigger for this (2026-09-24). Data and transitions are in [api.md](api.md) §Threads and §Pending review.

- **Composer**: a two-item segmented control above the note, `[수정 요청 | 질문]` ("[fix request | question]", `#c-kind`, defaults to fix request, resets on save/cancel). The edit panel has the same control. A question card gets a `질문` ("question") badge (primary-color outline). **Suggesting the right kind**: if a fix-request note reads like a question (ends in `?`·`？`, or a Korean question ending like 는가·나요·까요·인가·건가·니·냐·까 — ignoring a trailing period, ellipsis, parenthesis, or @-mention, `looksQuestion`), a one-line hint (`.q-hint`) appears just below the note field: `질문처럼 보입니다 — [질문으로 보내기]` ("this looks like a question — [send as a question]"). Clicking it switches the kind to question and the line disappears. It never switches automatically. It disappears once the kind is question, or once the text stops reading like one. Applies to both the composer and the edit panel. Trigger: a co-author saved "…is this an intentional choice?" as a fix request (missed the segmented control entirely, 2026-09-25). It's placed below the note field rather than beside the control because inserting a line right as you type a `?` would shift the input field and move the cursor. The button is link-styled (primary-color text, underline on hover), with no surrounding box.
- **Thread**: below the note, past a dotted divider, replies and transition records (close/reopen/confirm) appear one line at a time. `wide` shows the last 3, compact shows only the last 1, with [이전 N건 보기] ("[view previous N]") to expand. A collapsed compact card hides the thread entirely and shows only a reply count (a speech-bubble icon) in the header. Clicking [답글] ("[reply]") opens an input field inside the card — the input DOM is kept and reinserted in place (with the cursor restored) whenever the 5-second auto-sync redraws the list (`REPLY`, the same approach as `EDIT`). Closing it keeps whatever was typed.
- **Pending-review section** (`#sec-review`): between open pins and done. Cards look like open cards, with a purple header dot (`--status-review`, dark `#b197fc`·light `#6d28d9` — roughly 7:1 against the card background), and the PDF mark is purple too. Badge: `<author>님 확인 필요` ("… needs to confirm", or `내 확인 차례`, "my turn to confirm," if you're the author). Actions: `[변경 보기] [답글] [다시 열기] [확인]` ("[view changes] [reply] [reopen] [confirm]") — [확인] ("[confirm]") is only highlighted (`.btn-soft`) when the author is viewing it. Anyone can press it, but the natural person is suggested (the trust model). [다시 열기] ("[reopen]") requires a one-line reason before it sends.
- **Counts**: compact shows a purple pill inside `[핀 N]` (`#side-rv`); wide shows `검토 대기 N` ("pending review N", `#rv-chip`, in the status-chip row, click to jump to the section). Counted across documents. The tab title gets `· 검토 M` ("· review M").
- If this screen has no identity (local `127.0.0.1`, SSH port-forwarding), [완료] ("[done]") is also treated as an agent close, becoming pending review — the notification says so.

## Viewing changes

[변경 보기] ("[view changes]") on a pending-review card or a done row opens the changes tab (#81/#82) scoped to that pin.

| Step | Commit chosen (within the last 12) |
| --- | --- |
| 1 | A 7–40 character hash prefix in the close-time reference (`close_ref`) (e.g. `PR #235 (f47c6bf)`) |
| 2 | A commit whose title contains the reference's PR number — a squash `(#236)`, or a merge `Merge pull request #236` |
| 3 | The most recent commit that touched within ±5 lines of the pin's line in the pin's file (fetched per commit and matched against diff hunks) |
| 4 | The most recent commit |

- Line matching only exists in the **source diff**. So it opens directly to [Source diff], selects the pin's file (matching by path suffix), and highlights and centers the new-side line numbers that fall within the pin's range. A line right below the header (`#revision-pin`) explains which rule matched and offers [원고로] ("[back to manuscript]").
- The comparison PDF (latexdiff) has no SyncTeX mapping. Opening that tab builds it on demand (it used to always be built even when only viewing the source), scrolls near the pin's page, and labels it "approximate."
- What it can't do: a closed pin isn't resynced, so highlighting can drift if the manuscript changes substantially after it's closed (it says so if nothing is found). Commits outside the last 12, commits on a not-yet-merged PR branch, and uncommitted changes are all invisible. A view-only PDF document, or a document not backed by a Git repository, opens the tab and states why.
- Also opens on a collapsed fold (narrow) — it never used to. With no nav bar, the instructions line's [원고로] ("[back to manuscript]") is the way back.
- Phone/fold QA (2026-09-25, light and dark):
  - At widths where the pin panel overlays the body (701–900px, 842px on a fold), the changes view leaves an empty strip on the right the width of the panel (`--side-w`). The body PDF can be scrolled sideways to see under it, but the diff can't — the right half of a wrapped line, and the instructions line's [원고로], ended up hidden under the panel.
  - Touch targets for commit selection (`#revision-list select`), file selection, and [빌드 경고 보기] ("[view build warnings]") are now 44px — they were 18px·16px.
  - If the pin's line range isn't in the diff but its immediate neighborhood (±5 lines) changed, the instructions line says so (`tg.near`) — it used to say "the highlighted line is the pin's range" with nothing actually highlighted (#47).
  - Left as-is: the instructions line's `참조 PR #240` ("reference PR #240") is unclickable gray text (the link-shape rule), and only [원고로] is clickable.

## @mentions

- Typing `@` in a note, edit, or reply field opens a people list (`#mention-pop`, up to 6, excluding yourself). Its placement (`mentionTop`) avoids covering that field's action row ([취소][보내기] for reply/reopen, "[cancel][send]"; [저장] for edit, "[save]"; [핀 저장] for the composer, "[save pin]"): below the field if there's room before the action row, else above the field, else below the action row, else pull whatever fits below the field back onto the screen. A reply field's two buttons sit right below it, so the list opens upward — it used to open downward and cover [취소][보내기] while picking (QA 2026-09-25, all three widths). The selected row is a flat, full-width strip (`--accent`, no rounded corners — a shadcn Command look). No extra rounded box inside the frame (§One layer of containment). ↑/↓, Enter/Tab to pick, Escape to close (caught before selection-cancel — window capture). Clicking the list never steals focus from the input field. Picking inserts `@name `.
- A resolved `@name` in text (someone in that message's `mentions`) is a **mention token** — primary-color text on a light primary-tint pill (`.mention`, Slack/GitHub-style), tooltip `@태그 — <name>에게 알림이 갑니다` ("@mention — a notification goes to name"). A mention naming the current identity gets a one-step-darker tint (`.mention.me`, tooltip `나를 부름`, "addressed to me"). Same treatment in the note, thread messages, collapsed-card summaries (`.sum`), archive one-liners, original requests, and dropped-pin notes. An unresolved `@word` stays plain text — it must never look like it addressed someone (author feedback, 2026-09-24: couldn't tell a real mention from plain text).
- Resolution matches the server's `resolve_mentions()`: full name·login·the part of a login before `@`·the first word of a name, longest match first, case-insensitive; skipped if what follows `@` is a letter or digit (an email address); a different thing entirely if a Latin-ending name is immediately followed by more Latin letters. Text is escaped with `esc()` first, and tokens are wrapped within the already-escaped text (via placeholders rather than double-wrapping) — so user-written text never leaks into HTML.
- **Live preview while typing**: since a `textarea` can't color text, one line right below the note/edit/reply field (`.m-preview`, `#note-mentions`) shows, once saved, who would be notified (`@ 알림  Bob Park`, "@ notify Bob Park") and any unresolved `@word` (dotted underline, `등록된 사람이 아님`, "not a registered person"). An `@word` still being typed (cursor at its end) isn't flagged yet — it's only evaluated once the cursor leaves it (arrow keys, a click) or the field loses focus (`mentionBadSettled`) — the warning used to fire while still picking from the list mid-`@Sa` (QA 2026-09-25). This lets you know, before saving, whether what you typed will actually notify anyone. A self-mention shows `(나 — 알림 없음)` ("(me — no notification)").
- **`#number` links**: an in-text `#12` is a link (`.pin-ref`, the link style above) if that pin exists (open, pending review, done, or dropped) — clicking expands and scrolls to that card or archive row and flashes it (switches on "all documents" first if it's in a different one). A nonexistent number, or an escape like `&#39;`, is left untouched.
- A card that mentions someone gets `나를 부름`·`@name` ("addressed to me"·"@name") badges (for an old pin with no assignee recorded).

## Assignee

Turns the guessed "who handles this" into an explicit value (`assignee`, [api.md](api.md) §@mentions, people, and events) — an early pilot pin (#43, "does this call actually work, @Bob Park please confirm", a fix request) was meant for Bob Park, but showed as `참고 @Bob Park` ("for reference @Bob Park") and an agent nearly read it as its own job.

- **Composer**: if the note resolves at least one @-mention, a `담당  [에이전트 | @Bob Park | …]` ("assignee [agent | @Bob Park | …]") segmented control appears below the notification line (`#c-assign`, one segment per tagged person, excluding yourself). Default — whichever person the note **starts** with a resolved @-mention for; otherwise, on a question pin, the first @-mention; otherwise agent (`defaultAssignee`). Before you pick one, the default is recomputed every time the note changes; once you pick, it only reverts to the default if that person drops out of the note. With no @-mentions, there's no control at all (agent).
- **Card**: a person assignee gets a `담당 @name` ("assignee @name") chip in the header (`담당 나`, "assignee me," one step darker tint, if it's you). Agent is the default, so no chip. The author (or an identity-less local screen) can click the chip to open [Edit] and change it with the same control — a change adds a `담당 바꿈` ("assignee changed") line to the thread.
- A person assignee means the agent skips it (`→ @name`) and that person gets an `assigned` notification (notification priority: assignee > mentioned > reopened > pending review > reply). Agent assignee means an @-mention is just `fyi` (`참고 @name`). Either way, a tagged person still gets a mention notification.

- A `[나를 부른 핀 N]` ("[pins addressed to me, N]") toggle in the list header (`#mention-filter`) — shows only open/pending-review pins across all documents that mention the current identity. Hidden if there are none. Never shown for a local identity.

## Browser notifications

A tier-one, tab-must-be-alive notification (no web push, no external service, no new dependency).

- **Turned on per device**: a bell on the desktop toolbar (`#btn-notify`) and an [알림 켜기] ("[turn on notifications]") button under `[더보기]` ("[More]", `#m-notify`). `Notification.requestPermission()` is only called from this click. State reads `켜짐`/`꺼짐`/`브라우저에서 차단됨`/`이 주소에서는 안 됨`/`테일넷 주소에서만` ("on"/"off"/"blocked in the browser" (address-bar lock → notifications → allow)/"not available at this address"/"tailnet address only" — see local identity, below). Whether it's on is kept in `pinPrefs.notify` (localStorage).
- **A local identity can't turn this on**: a tab opened with no tailnet login (e.g. hitting `127.0.0.1` directly) gets no events from the server at all (§@mentions, people, and events, `events_since`), so notifications never arrive. The button/menu item stays disabled with the message "open this over a tailnet address to turn this on" — it never hides a state where getting browser permission wouldn't help anyway.
- **Secure context**: the service worker and notifications only work over https (a tailnet `*.ts.net` address) and `http://127.0.0.1`·`localhost`. Plain http on any other host (a LAN IP, say) is blocked by the browser.
- **Flow**: the 5-second light poll (`pollLight`) appends `ev=<cursor>` to fetch events addressed to me ([api.md](api.md) §Browser notification cursor). The cursor (`pinNotifyCursor`) lives in the browser's localStorage, so a refresh or two open tabs never notify twice for the same event. Turning it on for the first time starts counting from the current `ev_seq` (it never floods you with past events).
- **What triggers it**: being mentioned (`mention`), your pin moving to pending review (`review_requested`), a reply on a pin you wrote or were mentioned on (`replied`), your pin being reopened (`reopened`). Things you did yourself never notify you (filtered on both the server's `to` and the viewer). Within one fetched batch, at most one notification per pin (priority: mentioned > reopened > pending review > reply).
- **Display**: always via the service worker's `registration.showNotification()` (Chrome on Android blocks a page's own `new Notification()`). `tag` = `pin-<number>`, so notifications for the same pin collapse into one slot — if an agent replies and then closes within a 5-second gap, both fire but only the later one (`검토 대기`, "pending review") stays on screen. Title `핀 #N · <document name>`, body `Bob Park님이 불렀습니다: <80 chars>` ("Bob Park mentioned you: …", using the mentioner's `name` as-is + "님") or `검토 대기: <first line of the reply>` ("pending review: …"), icon = the favicon. If the tab is visible and focused, a toast replaces the notification ([Open]). Even with the tab **hidden**, as long as notifications are on (§Browser notifications), a slower (20-second) events-only poll keeps running — it never redraws the list.
- **On click**: the service worker brings an already-open viewer tab to the front and opens that pin via `postMessage`; with no open tab, it opens a new one at `/#doc=<key>&pin=<number>` (the hash's `pin=` also opens on boot).
- Verified with Playwright's new headless mode (`channel="chromium"`) — the old headless shell reports `Notification.permission` as `denied` even when granted. Not tested on real Android/iOS devices (iOS only notifies a web app added to the home screen).

## Archive

Expanding closed and dropped pins used to look just like open cards, with no clear boundary for where "closed" started (author feedback, 2026-09-23). The list is split into three `section`s.

- A **section header** is one full-width line: `완료 18 ───────── 펼치기` ("done 18 ───── expand", collapsing it reads `접기`, "collapse"), `삭제 2 ─── 펼치기` ("dropped 2 ─── expand"). The open list's header (`열린 핀 N`, "open pins N") looks the same. Headers are `position:sticky`, so scrolling keeps them visible and shows which section you're in, and the next header pushes the previous one out of the way (thanks to wrapping each in its own `section`). In compact layouts, `#right` is the scroll box and the toolbar is already sticky at the top, so JS measures its height as `--stick-top`. An empty, collapsed section is hidden header and all.
- An **archive row** isn't a card — no border, background, or stripe, just a single divider between rows, and dimmer text. State is a leading icon.
  - First line: icon (done `check`, dropped `trash-2`) · `#number` · line range · reference (`close_ref`, e.g. a PR number) · time (`MM-DD HH:MM`, closer's name in the tooltip) · [다시 열기] / [되살리기] ("[reopen]" / "[restore]").
  - Second line: for done, the agent's reply (`close_reply`) on one line — truncates with an ellipsis, click to expand. With no reply, "설명 없이 닫힘" ("closed with no explanation"). The original note only appears via [원래 요청] ("[original request]"). For dropped, that pin's note (with no reply, it's the only clue for identifying it).
  - An expanded line survives a redraw (auto-sync).
- Document tabs and the "all documents" toggle use the same list functions as the open list (`listDone`·`listDropped`) — across all documents, a row gets a document chip.

## Design tokens and components

With 49–54 color literals, 14 radius values (2·4·5·6·7·8·9·10·12·14px, 50%, 0, and combinations), 13 font sizes, and only 32 tokens, buttons and badges playing the same role looked slightly different everywhere (2026-09-23). Only [shadcn/ui](https://ui.shadcn.com)'s **system** (token names, roles, variant names) was borrowed to unify all of this — no React, Tailwind, build step, or CDN; the CSS is still a single `<style>` block inside `src/limn/server.py` (deployment is only installing the package). Behavior, the API, and layout rules are unchanged.

### Tokens

Color literals only exist as variable definitions inside **two token blocks** (`:root` = dark, `:root[data-theme=light]` = light). Every rule uses `var(--…)`, and light fills (a selection box, a mark, a danger-button background) are made with `color-mix(in srgb, var(--token) N%, transparent)`. Neutrals are zinc-family.

| Group | Token | Used for |
| --- | --- | --- |
| Surface | `--background`·`--foreground` | The PDF-area background (dark zinc-950, light zinc-200 — so the light page reads as floating above it) and default text |
| | `--sidebar` | Right panel·sheet·toolbar·sticky headers |
| | `--card`·`--card-foreground` | Pin card·composer panel·banners |
| | `--popover`·`--popover-foreground` | Dialogs·toasts |
| | `--muted`·`--muted-foreground`·`--subtle-foreground` | A light fill (kbd)·dim text·even dimmer text (dropped pins) |
| | `--field`·`--code` | Input-field background·source-text (`pre`) background |
| Action | `--primary`·`--primary-foreground`·`--ring` | Primary action·selection·focus ring (blue — the old `--acc` value, unchanged) |
| | `--secondary`·`--secondary-foreground` | Filled secondary buttons·count badges |
| | `--accent`·`--accent-foreground` | Hover surfaces |
| | `--destructive`·`--destructive-foreground` | Delete·error |
| Lines | `--border`·`--border-strong`·`--input`·`--outline-bg` | Dividers·emphasis border (badge outline)·control border·outline-button fill |
| State | `--success`·`--warning` (+`-foreground`) | Notification icons·warning text |
| | `--status-open`·`--status-claimed`·`--status-closed`·`--status-dropped`·`--status-warning` | Mark/open dot / in-progress dot / done icon / dropped icon / position-lost·overdue·reopened (§Status representation) |
| Other | `--tooltip`·`--tooltip-foreground`·`--shadow-color`·`--shadow-page` | Tooltip·shadow color·page shadow |
| Instance | `--brand`·`--brand-foreground` | The label color (filled in by the server from the `--accent` argument, theme-independent)·white text on top of it |

Theme-independent scales (a third `:root` block):

| Scale | Values |
| --- | --- |
| radius | `--radius-sm` 4px (badges·kbd·small bars) · `--radius` 6px (buttons·inputs·tooltips) · `--radius-lg` 10px (cards·dialogs·sheet corners·count pills). Only circular dots/avatars/spinners use `50%`, and only where corners are removed entirely does it use `0` |
| font size | `--text-xs` 11px (badges·page number) · `--text-sm` 12px (small buttons·secondary text) · `--text-base` 13px (buttons·inputs·notifications) · `--text-lg` 14px (body text, touch buttons) · `--text-xl` 16px (dialog titles, touch inputs — prevents iOS zoom) |
| spacing | `--space-1..6` = 4·8·12·16·20·24px. padding·margin·gap all sit on this grid (grid cleanup 2026-09-25 — moved odd values like 6·10·14·18·22px onto the 4/8 grid; 1–2px hairlines, optical correction, and negative margins are left alone). Guard: `FrontendSpacingGrid` |
| control height | `--control-h-sm` 24 · `--control-h` 28 (toolbar `--tb-h`) · `--control-h-lg` 36 (action bar) · `--control-h-touch` 44 |
| shadow | `--shadow-sm`·`--shadow`·`--shadow-lg` |
| font | `--font-sans`·`--font-mono` |

Notable changes and non-changes from the grid cleanup (2026-09-25): default button horizontal padding 10→12px, badge horizontal padding 6→8px, input vertical padding 6→8px, segmented-control frame padding 3→4px, gap between pages 18→16px. Widening desktop [PDF rebuild] to 8px dropped [?] to a second row in the default 348px panel, so it stayed at 4px. The archive's first-line gap is 4px, and the line-range (`.loc`) is never allowed to shrink — next to a long reference (`paper PR #236; code P…`), `L890-L897` was clipping to `L89` (a pre-existing problem, found on a fold before this cleanup). Before/after screenshots at three widths and both themes were compared in pairs.

### Components

| Component | Class | Used in |
| --- | --- | --- |
| Button, outline (default) | No variant class | Toolbar buttons, card [보기]·[수정]·[풀기] ("[view]"·"[edit]"·"[unclaim]"), archive [다시 열기]·[되살리기] ("[reopen]"·"[restore]"), [취소] ("[cancel]"), dialog buttons, list header [다시 읽기]·[모든 문서] ("[reread]"·"[all documents]") |
| Button, default | `.btn-default` | [핀 저장] ("[save pin]"), edit [저장] ("[save]"), [이 위치로 바꾸기] ("[relocate here]"), [PDF 재빌드] after the manuscript changed, active [선택] ("[select]") |
| Button, secondary | `.btn-secondary` | Buttons inside the `[더보기]` dialog. Card [보기]·[수정]·[답글]·[풀기]·[변경 보기]·[다시 열기]·[확인] and the input field's [취소] share this look too (the card rules give it to them) — filled, no border |
| Button, soft | `.btn-soft` | Only the card's [완료] ("[done]") — 14% primary-tint fill + primary-color text (contrast 6.1 dark · 4.55 light; hover raises the border instead of the fill). A variant shadcn doesn't have: it keeps [완료] light blue per an author decision (2026-09-23) while leaving `--secondary` as the neutral for count badges |
| Button, ghost | `.btn-ghost` | [원문 펼치기] ("[expand source]"), card collapse, closing a notification/hint |
| Button, destructive | `.btn-destructive` | Card [삭제] ("[delete]") — inside a card, danger-color text with no fill (a light tint only on hover). Never the loudest button |
| Sizes | Default (28px) · `.btn-sm` · `.btn-icon` (square, 24px combined with `.btn-sm`) | Card·archive·dialog buttons are sm; icon-only buttons are icon. All at least 44px on touch |
| Badge | `.badge` (= light fill, no border) · `.badge-default` · `.badge-secondary` · `.badge-destructive` · `.badge-claimed` (+`.late`) · `.badge-warning` | Card badges, toolbar status chips (manuscript newer·PNG view·disconnected·build error), counts (`.dcnt`·`.arc-n` = secondary pills), document chip (`.dchip`), reference (`.arc-ref`)·view-only indicator (`.dvo`) |
| Card | `.card` | Pin card (`.pin.card`) |
| Input | `input`·`textarea` | Note·page field. The toolbar's page field matches the button height (`--tb-h`) |

Old display-only classes (`.p`·`.x`·`.ghost`·`.ib`·`.ico`·`.tag`·`.t`, `.tag.claim`) are gone. Names like `.b-close`·`.b-drop`·`.arc-b` remain as role markers — the variant class decides the look. Things that press like a button but look different — the segmented control (`.seg`), stepper (`.step`), section header (`.arc-head`), the [원래 요청] text link (`.arc-orig-t`, underlined) — are separate shapes that still use the same tokens.

### One layer of containment

Drawing a bordered box inside another bordered box (a bordered badge/button inside a card, a bordered cell inside a bordered segmented control, a bordered source-text box, a bordered overlap-warning box, a bordered thread box inside an archive row) looked tacky (author feedback, 2026-09-24). Only one containing layer is ever drawn.

| Layer | Shape |
| --- | --- |
| Panel·section | No border. Section header + one divider (the `.arc-head` top line) |
| Card (`.card`) | One thin `--border`. No shadow |
| Inside a card | Badge = light fill (a meaningful badge gets that color's 14% tint) · button = filled secondary (done = soft, delete = borderless danger text) · thread = one divider then a list · edit = spacing only |
| Composer | No box at all. Scope ladder/kind = shadcn Tabs (a filled frame + a floating selected cell) · stepper = a filled group (no internal dividers) · source text = `--code` fill (no border) · overlap banner = text + buttons · the only border is the note input field |
| Archive row | No box. One divider between rows; thread and original-request only indent |
| A floating surface (dialog, toast, @-mention list) | A thin `--border` + `--shadow-lg`/`--shadow` — shadow is reserved for these. Buttons inside are filled secondary |

Guard: `FrontendNoNestedOutlines` (no bordered box inside an inner component's CSS), plus a screenshot harness's DOM check (any four-sided-border element inside a four-sided-border ancestor, excluding inputs) — before the fix: 72 in the main list, 13 in [more] → 0 after.

### Literal exceptions (allowlist)

| Location | Value | Why |
| --- | --- | --- |
| The three token blocks (`:root`·`:root[data-theme=light]`·the scale block) | Color·px values | This is where they're defined |
| `#brand-stripe`·`#brand-chip`'s `style="background:__ACCENT__"` | The instance color | Filled by the server from `--accent`. Must survive a theme change, and the regression test (`BuildHtmlSubstitution`) checks this exact shape |
| The favicon SVG (`favicon_href`) | `fill="#ffffff"` etc. | A data-URI image, outside CSS |
| PDF pages (PNG·PDF.js canvas) | Paper color | This is the manuscript PDF's own color. A theme never changes paper color |
| `vendor/pdfjs`·original Lucide | — | External code (Lucide uses `currentColor`, so it follows text color) |
| Sizing literals (width·height, negative margins, position coordinates, `calc`) | px | Rounding to the scale would shift the layout. Spacing (padding·margin·gap) is not exempt — only 1–2px hairlines are |

Guard: `tests/test_server.py`'s `FrontendDesignTokens` parses the inline CSS and blocks color literals outside the token blocks, radius/font-size values outside the scale, color/font literals in inline `style`/JS, undefined `var()` references (excluding `--kb`·`--vvh`·`--side-w`·`--sheet-f`·`--stick-top`, which JS sets), and a color-token mismatch between the two themes. Adding an exception means updating both the table above and the test's allowlist.

## Icons

Emoji and basic character icons (⏳ ▾ ▸ ☾ ◐ ✓ ✎ ⚠ ⧉ ⋯ ＋ ×) looked different across devices and fonts and looked bad (author feedback, 2026-09-23). All were removed in favor of [Lucide](https://github.com/lucide-icons/lucide) (ISC) icons, used only where truly needed. Provenance, version, and the icon list are in [`vendor/lucide/README.md`](../src/limn/vendor/lucide/README.md).

- Only the elements inside the `<svg>` from the `lucide-static` npm package are inlined into `src/limn/server.py`'s `LUCIDE` (no external CDN). `stroke="currentColor"`·`stroke-width="2"` (24-unit grid)·16px (12–14px in badges/rows), so it follows text color. The server fills in a `{{ic:name}}` placeholder, and JS draws the same shape via `ic(name)`.
- A button whose meaning is clear without an icon keeps text only: card [보기]·[수정]·[풀기]·[삭제]·[완료], archive [다시 열기]·[되살리기], [원문 펼치기], and inside `[더보기]`: [축소]·[확대]·[폭 맞춤]·[테마] ("[zoom out]"·"[zoom in]"·"[fit width]"·"[theme]") etc. An icon-only button (zoom out, zoom in, theme, help, more, copy location, close notification) gets its name via `aria-label`.
- An arrow in prose (→) and a key name (⌘ Enter) stay as text — they aren't icons.

## Multiple documents

A single paper repository has several documents — body, response letter, cover letter, highlights — with different folders and build methods. The author's decision (2026-09-23) was **one viewer, one address, per paper repository** (option A), switching documents within it. A separate viewer per document would multiply ports, tailnet addresses, and browser tabs by the document count, and "handle #12" would become ambiguous about which viewer's #12.

### Server

| Decision | Reason |
| --- | --- |
| One pin store (`pins.jsonl`·`pins.seq`) | Numbers must be unique across documents so a chat's "#12" is never ambiguous. Records gain a `doc` field; an old record without one is only read as the first document (never migrated on write — reverting to an old state directory still works) |
| Record validation is shape-based | A record with `file` is a LaTeX pin (validated as before); one with only `pdf` is view-only. A document key that's not in the current configuration doesn't make it a corrupt line — treating it as corrupt would let the next write erase that pin (only the backup would survive). pins.md surfaces such pins under a `## 설정에 없는 문서` ("## document not in configuration") section |
| Build/pages/history are per-document folders (`docs/<key>/`) | Page-image version (`pages.cur`)·build history (`builds.json`, the source of position estimation)·`built_at` all differ by document. Only the key `main` LaTeX document uses the state-directory root — so adding a document to a single-document instance with `--doc main=…` keeps the body's build history intact and doesn't flip every old pin to a dotted estimate |
| The document is threaded per-request as a thread-local value (`using_doc`) | Dozens of build/page/fingerprint functions look at "the current document" with no argument. A single document is treated as "whichever document is read at the time" (`LEGACY_DOC`), so old paths and regression tests keep running unchanged |
| The build lock is per document | Since build folders are per document, different documents build concurrently without stepping on each other's `.aux`. The same document is still limited to one at a time (`409`) as before |
| `--git-pull` is per repository | With multiple documents, pulls serialize behind one lock, and a document that pulls within 20 seconds of another shares that result (`pull.shared`). Simultaneous fetch/merge would collide on `.git/index.lock`, and the tree could change mid-copy for one document |
| A LaTeX document builds from the folder its main `.tex` lives in | Exactly like running `cd <that folder> && latexmk` by hand. The build root in `<build root>::<main>` is only the range copied into the build copy — confirmed by measurement: a second paper's body (`manuscript/2nd`) reads figures from a sibling folder via `\graphicspath{{../1st/images/}}`, so copying only one folder would drop the figures |
| Startup builds for multiple documents run in the background | So the server doesn't wait document-count × tens-of-seconds before coming up. A failure doesn't block startup (that tab opens an error panel). A single document still builds synchronously and exits on failure, as before |

### View-only PDF

A PDF with no LaTeX source (reviewer comments, a received PDF, a committed submission copy) goes into the same list. Since there's no line number to recover, a pin's location is **page and region (`frac`)**, and `pick` returns region text with no SyncTeX (`pdftotext`, 160 characters) — with no lines, this text is the agent's only clue about the source. So pins.md always shows it as `«…»`, with no 60-character or long-single-line condition. There's no rebuild. A watcher thread checks the PDF's `mtime:size` every 3 seconds, and on a change, redraws the pages through the same build path (`_build_tracked` → history·`build_seq`) — the viewer updates the screen exactly like a LaTeX rebuild, and an old pin whose fingerprint (a hash of the PDF's content) no longer matches is drawn dotted (an estimate).

### Viewer

| Screen | How to switch |
| --- | --- |
| Desktop, unfolded fold (`wide`·`mid`) | A low strip above the PDF area with inline document links and `원고`/`변경사항` ("manuscript"/"changes") view switching. `목차` ("table of contents") expands on the left when PDF.js reports an actual outline, and jumps to a page. Page, zoom, and rebuild tools stay in the existing right panel |
| Collapsed fold (`narrow`) | The existing toolbar's `[문서 이름 ▾]` ("[document name ▾]") → a sheet list below (name·path·pin count·view-only). The desktop nav bar is hidden, keeping the existing mobile PDF/sheet flow |
| A single document | The document picker, document buttons, and "all documents" toggle disappear. Desktop's view switching and table of contents still work |

- **Switching must feel instant.** Meta is cached per document, so it draws immediately with no wait, then fetches the latest meta in the background and swaps just the pages if the build changed. PDF.js document objects are kept for the most recent 3 `document|build` pairs (the least-recently-used one closes once that's exceeded — worker memory). Measured (1440×900, 43- and 111-page manuscripts): first switch with no cache 63ms, returning 67ms (the PDF isn't refetched), and only the visible pages are redrawn as vectors afterward.
- **Per-document viewing spot and zoom are remembered** (top-anchored page and ratio, page width, compact's hand-zoom state, horizontal scroll). Only the width seen under the same layout is restored — a width fitted on a collapsed screen never leaks to desktop. Kept in `sessionStorage` to survive a refresh.
- **Address**: `#doc=<key>` (for sharing links, refreshing). The first document shown follows: the hash → this device's last document (localStorage) → the first document.
- **Keyboard**: Ctrl+PgUp/PgDn (previous·next), Alt+1…9 (`e.code` — Option+number on Mac produces a different character). The document picker uses standard keyboard operation. Global shortcuts don't fire while an input field has focus.
- **Sidebar**: defaults to the current document's pins. The "all documents" toggle shows everything, with a document chip on each card. A different document's card `#number`·[보기]·[수정] switches to that document first, then jumps there (`jumpPin`·`openEdit` route through `viaDoc` up front). Marks, the overlap banner, and editing only ever look at the current document's pins (`PINS`) — page coordinates only mean something within that document's PDF.
- **Build**: [PDF rebuild] only covers the current document, and is hidden for view-only. If another document is stale or building, the picker shows it, and a notification with an [Open] button appears once a background build finishes (`build_seq` counted per document).
- **Changes**: shows the last 12 Git commits that touched `.tex`·`.bib`·`.sty`·`.cls`·`.bst` files under the selected main `.tex`'s folder. Documents sharing a build root but with different main-file folders never mix histories. The first screen is the actual patch of the most recent commit. Both commit and file are selectable. The API only accepts a 40-character commit id from the current list, and the diff is cut at 256 KiB. Uncommitted changes in a separate work tree, and binary changes to a view-only PDF, are never shown.
- Switching documents drops any pending selection/relocation (keeping any note text you typed). An unsaved edit isn't closed — that card stays in the list.

## Vector rendering

Author's question (2026-09-23): "is the blur when the PDF renders just unavoidable? the text doesn't seem to still be vector." Before this, pages were drawn as `pdftoppm -r 150` PNGs, shown via `<img>`. An A4 page is 1241×1754px, so at the desktop fit-width (954 CSS px) and DPR 2, it was already at 0.65× screen pixels, getting blurrier with more zoom (0.16× at 4×). Now the viewer draws the same build's PDF directly onto a canvas via PDF.js. The server API and pin format are unchanged — only two extra routes (`GET /pdf`·`GET /vendor/pdfjs/…`, [api.md](api.md)).

| Item | Rule |
| --- | --- |
| Library | The `pdfjs-dist` 6.3.289 `legacy` build lives in `vendor/pdfjs/` (no external CDN). Provenance, sha256, and what was excluded are documented in [`vendor/pdfjs/README.md`](../src/limn/vendor/pdfjs/README.md) |
| Document | `GET /pdf?build=<META.pages_build>` — the PDF for the same build as the page images. If the page count differs from what's on screen, it's not used |
| Backing size | Page CSS size × `devicePixelRatio` × (browser pinch factor, minimum 1). The app's own zoom is already baked into the page CSS width (`W`) |
| Width and height | Fitted separately (the render `transform`'s vertical scale). The page box's aspect ratio comes from the PNG pixel dimensions and differs from the PDF page's own ratio by under 0.1% — since the PNG also filled that box exactly, this keeps text landing at the same % position it did under PNG |
| Visible area | Only pages inside an `IntersectionObserver` (root `#left`, ±150%) are drawn. A page's canvas that scrolls out is shrunk to zero size and detached (Safari reclaims the memory immediately too) |
| Order | Visible pages nearest the center first, one at a time. Page canvas → detail canvas, in that order |
| Pixel cap | 16,777,216 pixels per canvas (the iOS canvas limit, and mobile memory). Above that, the page canvas is scaled down to the cap, and only the visible portion (+25% of screen size as margin) is drawn at full resolution into an overlaid **detail canvas** (`.dt`), positioned with page-relative % coordinates. Scrolling past the detail area redraws it |
| Redraw | A zoom, window-resize, or DPR change cancels any in-progress draw and redraws 150ms later. The old canvas stretches via CSS in the meantime (no flicker). Once done, the new canvas is swapped in |
| Rebuild | Canvases are torn down and the new PNG shown first (so the old PDF drawing never lingers over new coordinates), then the new build's PDF is opened and redrawn. The old document is closed via `loadingTask.destroy()` |
| Fallback | If pdf.js fails to load (a `vendor` 404, network), the PDF fails to open, the page count differs, or drawing fails, every canvas is torn down. The PNG `<img>` that's always underneath shows through, and a status chip ("PNG view", `#vec-chip`) explains why in its tooltip. The server's `pdftoppm` render is kept regardless (first paint, fallback) |
| Text layer | Not added. Dragging selects a region, not text, and a text-selection layer would fight with that. Copying uses the source snippet (composer panel) instead |

The coordinate system is unchanged. Canvases are `pointer-events:none`, so drag/long-press are still caught by the page box (`.pg`) as before, and `frac` is a fraction of that page box. The page box's size and ratio are the same as under PNG (`pt_w`·`pt_h` still come from the PNG).

Measured (2026-09-23, headless Chrome, a 28-page test manuscript, before = PNG on `origin/main`):

| Item | Before (PNG) | After (vector) |
| --- | --- | --- |
| Desktop 1440×900 DPR 2, backing width ÷ (CSS width × DPR) — 1×·2×·4× | 0.65 · 0.33 · 0.16 | 1.00 · 1.00 · 1.00 (2×·4× via the detail canvas; the page canvas hits the cap at 0.90 · 0.45) |
| `frac` of the same drag · reverse-mapped line (page 1, page 5, 1×, 3×) | — | 0 difference, same line range |
| Difference between the pin mark box and `frac`'s position | 0.74px | 0.74px (unchanged) |
| Text position (peak cross-correlation of the same-region screenshot) | — | 1×·2× 0.5 CSS px, 4× 1 CSS px (within a single PNG pixel) |
| First PNG · PDF opened · first canvas (from navigation start) | 87ms · — · — | 87ms · 190ms · 310ms |
| Simultaneous canvases while scrolling through all 28 pages | — | Desktop up to 4 (18.2M pixels), collapsed fold up to 8 (10.5M pixels) |
| Redraw finished after a zoom step (1×→2× etc., including the 150ms debounce) | — | ≈0.4s. 10–60ms per page (the first page ≈120ms, loading fonts) |

## PDF-area-only zoom

Author's question (2026-09-23): "when zooming the PDF with the browser's own zoom, the sidebar zooms with it — is that also just unavoidable?" Without intercepting zoom input, browser page zoom kicks in and enlarges the sidebar and toolbar too. Now zoom input over the PDF area is intercepted and only changes the page width (`W`).

| Input | Handling |
| --- | --- |
| Ctrl(⌘)+wheel (over `#left`) | `wheel` is received `passive:false` and `preventDefault`ed. One mouse-wheel notch (\|dy\|≥50, or a line unit) equals a 1.2× step, the same as one button press; a trackpad pinch (Chrome/Firefox send finely-grained wheel events with `ctrlKey` set) uses `exp(−dy/100)` (the inverse of how Chrome turns a pinch factor into wheel deltas, clamped to ±18 per event). Batched into one apply per frame |
| Safari trackpad pinch | `gesturestart`/`gesturechange`'s `e.scale` (start width × scale) |
| Ctrl(⌘) + `=`·`+` / `−` / `0` | Zoom in / out / fit width. Never intercepted while an input field has focus |
| Two fingers (touch) | `touch-action: pan-x pan-y` on `#left` — blocks the browser's own pinch and double-tap zoom, letting only scroll through. `touchstart`/`touchmove` (`passive:false`) change `W` by the ratio of the two-finger distance, scrolling so the point under the fingers' midpoint tracks them. In selection mode, the page gets `touch-action:none` (one finger = select, two fingers = the same app zoom). A second finger landing discards any in-progress selection box or long-press |
| Buttons [＋]·[−]·[↔ fit width] | The same 1.2× step and fit-width (centered on the PDF area) |

- Zoom **preserves its anchor point**. The page and in-page ratio under the pointer (keyboard/buttons anchor to the PDF area's center) are captured, the width is changed, and `#left` is scrolled so that same ratio lands at the same screen position afterward. Fit-width preserves the top of the page you were viewing and resets horizontal scroll.
- The limit is 0.5–5× the fit-width width (minimum 160px). The old hard cap of 2200px is gone. An overflowing page only scrolls horizontally within `#left`; `body` never overflows.
- The sidebar, sheet, and toolbar are outside `#left`, so they're unaffected. Ctrl+wheel over the panel is never intercepted (it's not the PDF area).
- The viewport meta is unchanged (no `maximum-scale`·`user-scalable=no`) — pinching over the panel is still browser zoom, so accessibility zoom is never taken away.

Measured (2026-09-23, headless Chrome):

| Item | Result |
| --- | --- |
| Desktop Ctrl+wheel up 3 notches · down 1 · Ctrl+= · Ctrl+− · Ctrl+0 | Page width 900 → 1555 → 1296 → 1555 → 1296 → 956. `visualViewport.scale` stays 1, sidebar 430px and toolbar height unchanged. Every wheel/keydown was `defaultPrevented` |
| Wheel anchor point | Difference in in-page ratio under the pointer ≤0.0004 (≈0.5px) |
| Simulated trackpad pinch (ctrl wheel dy −6 × 20) | 1.82×, anchor difference within 3px |
| 5× | Page width 4780px, only `#left` scrolls horizontally, document width unchanged from window width |
| Ctrl+wheel over the panel · Ctrl+= inside an input field | Never intercepted (`defaultPrevented` false) |
| Unfolded fold 880×790 DPR 2.5 · collapsed fold 412×915 DPR 2.6, two-finger CDP touch (distance 80→272px) | Before: `visualViewport.scale` 5 (the whole screen enlarges); after: scale 1, page width 3.4×, panel/sheet/toolbar boxes unchanged. Same in selection mode |

## Known limitations

- **If the on-screen PDF is older than the manuscript, coordinates and source text disagree.** This happens while an agent has edited the manuscript but hasn't rebuilt yet. The text path still tends to find a similar-enough paragraph and narrowly clears the warning threshold (0.3) — measured once, picking a nomenclature table returned the introduction's contribution list at `0.32` with no warning. So the server compares the manuscript `.tex`'s modified time against the PDF's build time and reports it via `meta.stale_build`, and `pick`'s `warn` leads with this fact regardless of score. A "manuscript is newer" badge appears at the top of the screen. A pin picked in this state should have its line range double-checked.
- A SyncTeX coordinate lookup can grab a float just outside the selected region (nearest-node matching), corrected with dense clustering + the scope ladder. Not fully safe — if the result's `kind` is `float`·`env:*` but differs from what the user expected, check `raw_lo`/`raw_hi` (the range before correction) and retry.
- If the manuscript is edited and the PDF isn't rebuilt, pick still runs against the mismatched on-screen (old) PDF and source line numbers. Rebuild the PDF first whenever an agent has edited the manuscript.
- With several `.tex` files split via `\input`/`\include`, SyncTeX returns the individual file path inside the build copy — the server maps it back to the original path relative to `<manuscript_dir>` (§Architecture overview). If that mapping breaks (e.g. the build copy's directory structure differs from the original), the path is wrong.
- Anchor resync only works **while the head line still exists in the source**. Rewriting that sentence entirely drops it to `stale` — this is a signal, not automatic recovery. A pin picked on blank lines only has no anchor and is never resynced.
- If the same sentence appears more than once in the manuscript, the closest one to the original line number is chosen. This can be wrong in a manuscript with a lot of repeated structure.
- Picking a bibliography region has SyncTeX point at the generated `.bbl` file. The server detects this, advises against editing it, and refuses the selection.
- The render text path needs `pdftotext` to be able to extract characters. Text baked as a raster inside a figure is never picked up, so that area relies on the SyncTeX path alone.
- A pin changed by someone else (an agent) is picked up automatically within a few seconds by lightweight polling (5 seconds, [build-sync.md](build-sync.md) §Auto-sync).
- `claim` is a TTL-bound marker, not a lock — the server never stops someone else from closing a pin with a valid claim, or force-reclaiming it. Collaboration relies on the convention in SKILL.md's pin-processing procedure (claim only the pin you're about to fix, right before you fix it, and skip anything showing `처리 중(…)`).
- `--git-pull` only ever does `--ff-only` — if the server checkout has local commits and has diverged, the pull is skipped (`skipped:diverged`) and it builds against the current checkout. It never creates a rebase or merge commit as a substitute.
- The allowed Host set is hardcoded — see [operations.md](operations.md) §Differences from the design draft.
- Vector rendering and PDF-area-only zoom were only measured under headless Chrome (Playwright). Safari's `gesturechange` path, real-device pinch (with acceleration and inertia), and actual GPU render time were never measured.
- Ctrl/⌘ + `=`·`−`·`0` while an input field has focus, and Ctrl+wheel/pinch over the panel, are never intercepted (browser zoom applies) — so as not to steal an input field's browser shortcuts, and because the sidebar isn't the PDF area. A page already zoomed by the browser can't be reset with Ctrl+0 outside an input field (that resets PDF fit-width instead) — use the browser menu or an input field to reset it.
- `GET /pdf` doesn't accept `Range`, so the whole PDF is fetched before it opens (5.5MB for the test manuscript, smaller than the sum of all 28 PNGs). On a very large manuscript, the first canvas may be slow to appear — the PNG shows in the meantime.
- The mobile layout and the panel-width/sheet-height handles were only measured under headless Chrome emulation (Playwright, `isMobile`·`hasTouch`, dragging via CDP touch events). A real device's virtual keyboard was simulated by shrinking the visualViewport height, and pinch-zoom was simulated with two-finger CDP touch. Needs one more pass on an actual Galaxy Z Fold 7.
- Quick select's box is small, so a saved pin's mark also draws as a small box (it never paints the whole paragraph) — the server doesn't return a paragraph's PDF coordinates.
- `mid` is only used on touch screens. A mouse window narrower than 1100px still gets the old sidebar all the way down to 700px.
- Tab switching across multiple documents was only measured under headless Chrome (1440×900·880×790·412×915 touch emulation). Ctrl+PgUp/PgDn can be claimed first by real Chrome's own tab-switching (headless let the page have it).
- A view-only PDF's pins have no line-resync anchor. If the PDF changes, the region coordinates stay put and are only flagged dotted (an estimate) — where it moved to is never searched for.
- Multiple documents' `src_mtime` each scan their whole build root with a 2-second cache. A large build root (e.g. `manuscript/` also holding a first-round PDF and figures) can flag a document as "manuscript edited" even when an unrelated PDF inside it changed — keeping the build root narrow avoids this.
