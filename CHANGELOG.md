# Changelog

## Unreleased

### Fixed

- **`limn update` and `limn start` keep the TeX a machine's instances rebuild with.** The systemd unit's PATH was
  taken afresh from whatever shell rendered the unit. Run over a non-login SSH shell (`ssh host limn update`), that
  shell has no TeX Live on its PATH and finds the distribution's pdflatex, so the rewritten unit sent every instance on
  the machine to a TeX without the journal classes: the next rebuild failed with `File 'elsarticle.cls' not found`.
  The unit is now rewritten by the pdflatex each PATH reaches, not by whether it reaches one (every unit PATH ends in
  `/usr/bin:/bin`). When the unit's PATH and the shell's reach different pdflatex binaries and the unit's is not the
  distribution's (`/usr/bin`, `/bin`), the unit keeps its PATH and a warning names both. A unit that reaches only the
  distribution's TeX, or none, takes the shell's PATH, so a unit already written this way is repaired by the next
  `limn update` from a login shell. `LIMN_UNIT_PATH` still sets the PATH outright.

The agent contract is unchanged.

## 0.4.59 — 2026-11-12

### Changed

- **The viewer's rows stand on whole pixels and their words on their icons' centres.** The owner found the person's name
  on the desktop panel off its avatar and the details unsteady; measured at the ink, the cause was mostly one line. The
  meta text at the top of the panel had an 18.6px line, so the chips' row and the whole pin list under it stood 0.6px
  between pixels: boxes and icons are drawn on whole pixels and letters where they fall, and the two came apart by up
  to a pixel in every card. That line is 19px now, and the list is on whole pixels. The same holds for the note field
  (67 and 22px, not 67.2 and 21.7), the composer's overlap line, the changes view's caption, status and commit head
  lines, the help's rows (its rules are the cells' own - a collapsed table hung half a pixel outside itself), a
  dialog's greatest height (a phone's sheet stood on a fraction of 88vh), the section strip (its contents centre in an
  even 36px) and the [⋯] menu's foot (its bottom edge, and a phone's whole sheet, stood 0.7-0.8px off).
- **The person on the meta row is a part of the row.** The name touched the avatar (0px) in the body's 14px beside
  12px text, on a 22px avatar beside 20px chips, 0.7-0.9px over the avatar's centre, right after the review chip.
  The person now ends the row; the avatar is the chips' 20px; the name stands 8px from it in 12px with its cap height
  on the avatar's centre; a long name ends in an ellipsis.
- **A comment's avatar is on its writer's line.** In a card's thread the avatar stood 2px, and a record's dot 1px,
  under the centre of the name beside it: both are on it. An avatar's initial is on the circle's centre (1px over it).
- **Smaller ones.** In the [⋯] menu [100%] is as tall as [−] and [+] (19 against 28px) and the zoom figure is on their
  centre. A done row's number, line range and time are on one centre (the time stood 1.1px over it, the range 0.5px
  under), and on the desktop panel the row starts on the text line, under its section's chevron (13px left of it
  before). In the excerpt a [−] stands where a [+] does on its line (0.75px under). A card head's reply count stands
  4px from its icon (2px). The help's tables share one key column on the centred dialog (87, 135 and 89px before), so
  the explanations start on one line.

The alignment changes above change no behaviour, wording or control.

### Fixed

- **One very long formula no longer holds a Markdown document's page still.** KaTeX lays a formula out in one call
  that cannot pause or be stopped, and past some ten thousand characters its time grows much faster than the formula:
  one display formula of 45,000 lines (90,000 characters) held the page for 3 seconds on a desktop and for 15 on a
  slow machine, where a limit fixture's draw then ran past its 15 seconds every few runs. A formula whose TeX is longer
  than 10,000 characters is no longer handed to KaTeX: that formula alone stays as its source characters - a display
  formula line by line, each line one that can be chosen - and the rest of the document is drawn as before (ADR-0039).
  At the limit the slowest formula measured takes 0.03 seconds. The longest of the 763 display formulas in the lab's
  Markdown documents is 299 characters.

The agent contract is unchanged.

## 0.4.58 — 2026-11-11

### Added

- **The pin marks can be taken off the page for a look at what is under them.** A mark lies over what it marks - a
  frame, an 8% tint and a badge on a PDF page, a tinted line and a gutter badge on the Markdown and text surfaces - so a
  pinned figure was seen through its mark, and the only ways to see it bare were to confirm the pin or leave for the
  changes view. `H` (outside an input field, an open dialog and the changes view) now switches the marks off and on; held for longer than 350 ms it flips
  them only while it is down. [⋯] has a `핀 표시` (`Pin marks`) switch for a touch screen. While they are off the status
  line says `핀 표시를 숨겼습니다 [다시 보이기]`, and a card's [보기], which goes to a pin's mark, brings them back. A save's or an append's undo chip
  stays on show where its mark is, with the marks still off. Off is never stored - a reload shows every mark - and nothing is
  sent: the pins and their cards are as they were.

### Changed

- **A figure document's marks no longer tint the figure.** A figure is judged by its colours, and a review mark's 8%
  tint showed white as `#f3eefc` and a pale yellow `#fff3b0` as `#f3e3b3`. On a figure document a mark is now its 2px
  frame and badge only. Marks on a LaTeX document and a view-only PDF keep their tint.

- **Search finds the sentences above a line wider than the column again** (ADR-0038). A line wider than the column
  standing within one line pitch of body text - a publisher's download stamp at the foot of the page, a rule drawn in
  characters, a page-wide table row, a caption set right under a paragraph - shared a block with that body, on a
  two-column page with both columns, and gave the block the page's width: no line in it reached the right edge, so no
  query crossed any of its line breaks. Each page's own gutter is now read from its lines (`searchGutter`), and in a
  block holding a line that crosses it, the lines on one side take that column's measure back. Short entries under such
  a line still stay apart, because the right edge is the whole column's, not the block's longest entry. A pair joins on a
  column's measure only when both lines were given the same one, so a column's last line does not run into a page-wide
  line under it, and a page-wide caption still runs on into its short last line. A page whose gutter cannot be told
  from that page alone (one column nearly empty, fewer than 8 lines, a gap under 8pt) keeps the limitation; no
  gutter is borrowed from another page, so a result never depends on which page was read first. The pin format, the
  HTTP API, `pins.md` and stored pins do not change.

## 0.4.57 — 2026-11-09

### Changed

- **A formula written over a source line end is drawn too** (ADR-0037). 0.4.56 left one kind of formula as characters
  although KaTeX could have drawn it: an inline formula the writer wrapped at a line end (`$a_1 +` ⏎ `b_2$`). The parse
  worker still cuts such a formula into one token per source line - that is what keeps every line of a paragraph its
  own - but it now says how it cut (`info` `whole`, `head`, `tail`), and the page joins the pieces back at the line ends
  they were cut at (`mdTexRun`) and draws the formula once, in the line it starts in. A piece on its own is still never
  drawn: the second piece of `\(a` ⏎ `\(b\)` carries both delimiters and would otherwise draw the same formula twice.
- **A drawn formula that covers several lines carries them itself.** Such a box stands in the span of the line it starts
  in but holds `data-lo`/`data-hi` with `data-kind="lines"`, and the reader of a point's lines (`mdRangeAt`) now follows
  the **nearest** carrier. So a pin on a formula written over two lines has both of those lines for its range while its
  quote is the whole source TeX - the range and the quote say the same thing, which is what ADR-0036 D4 asks for. The
  ladder is unchanged: `lines` is no block kind, so the block rung is still the paragraph the formula stands in.
- The fallbacks are now only the four where a formula **cannot** be drawn or **must not** be: no module, no stylesheet,
  KaTeX refuses the TeX, or the formula holds a character that hides or reorders text (ADR-0029 D5). No character
  disappears in any of them, exactly as before.
- Saved pins are untouched, and so are the pin format, the API and `pins.md`. What is given up is choosing a single
  line inside a drawn formula - the same loss drawn display math already had, for the same reason.

### Fixed

- **A drawn inline formula wider than the column no longer runs off the screen** (ADR-0037 D5). KaTeX lays a formula out
  as one inline-block, which cannot be broken over lines, so one wider than the column reached past the screen's edge -
  and the viewer's `body` does not scroll sideways, so those glyphs could not be reached at all. 0.4.56 drew such a
  formula 328 px wide with its right edge at 380 px on a 320 px screen. The drawn inline formulas are now measured after
  a build and after the column changes width (`mdTexFit`), and only those wider than the text of the block they stand in
  (a paragraph, a list item, a table cell) are held to it and made to scroll inside themselves, as a display block did. A formula that fits is left alone, because a box that
  scrolls sits on its bottom edge rather than the sentence's baseline. Found while measuring this release's PoC at
  320 px; it is why the formulas of the three manuscripts were never affected - the widest was 83% of the column.

## 0.4.56 — 2026-11-09

### Added

- **The Markdown screen draws TeX math** (ADR-0036). `$…$`, `$$…$$`, `\(…\)` and a `\[…\]` block were shown as the
  characters they are written with; a reader of a manuscript full of formulas read TeX. The viewer now draws them with
  the bundled KaTeX 0.19.1 (`src/limn/vendor/katex/`), which the page fetches - module, stylesheet and the fonts the
  stylesheet asks for - only when a Markdown document whose text holds math opens. Nothing else asks for a byte of it.
  **No character disappears:** a formula stays as its source characters, exactly as before, when the module or the
  stylesheet does not arrive, when KaTeX refuses the TeX, when an inline formula runs over a source line end (one piece
  is no TeX on its own) or when the formula holds a character that hides or reorders text, which drawn glyphs could
  neither show nor name. One formula of a document may stay as characters while the rest are drawn.

  **A pin still points at the manuscript.** A drawn formula stands where its characters stood, with the same source
  lines, so every pin's range, `snippet`, ladder and `md:math` are what they were - a pin saved before this release
  points at the same lines. The `quote` of a selection over drawn math is the **source TeX**, not the glyphs: each drawn
  formula gives its `data-tex` back as the quote is read, and a selection that cuts into the middle of a formula takes
  that formula whole. Inside a drawn display block a single line can no longer be chosen - the block is the smallest
  thing there, as a one-line `$$ … $$` already was. The rendered compare keeps the source characters, which its block
  keys and its word diff read.

  The page policy is not widened: KaTeX gives its boxes their sizes through the CSSOM and the stylesheet is a
  same-origin link, so `'self'` already covered both. One read path is added, `GET /vendor/katex/<name>`
  (`.mjs`, `.css`, `.woff2`, a leaf name only, a year's immutable cache). The HTTP API, `pins.md` and the stored format
  do not change.

## 0.4.55 — 2026-11-07

### Changed

- **A figure map may be up to 16 MiB (was 4 MiB).** A figure repository that keeps every element of its candidate
  figures wrote more than 4 MB, so it had to thin those pages to their groups, and a pin there landed on a group
  rather than on the mark drawn. The watch still reads and hashes the map on every tick (a few ms at 16 MiB) and
  parses it only when it changes. The parsed build maps a run keeps are now bounded by their copies' bytes as well
  (64 MiB, the newest always kept), not only by their count (16), and the watch now remembers per document only the
  map's signature and the PDF it names, not the whole parse, so the larger cap cannot hold close to a gigabyte.
- The agent contract (`pins.md`, HTTP API) is unchanged. `limn-figure-map/1` keeps its format; only its size limit
  grows.

## 0.4.54 — 2026-11-07

### Added

- **Confirm several pins awaiting review from their result rows** (#453, ADR-0035). An agent that closes twenty pins
  at once left twenty cards to confirm one by one. The review section's head now has [골라서 확인] for a person who may
  confirm while two or more pins are listed: it turns the cards into rows that show each result - the agent's
  explanation (folded at six lines), its reference and the lines it changed - with a box each and [변경 보기]. Tick the
  rows you have read, or [모두 고르기], and [N건 확인] confirms them together after one undo row, while the rest stay
  ticked-or-not as they were; each is sent with the close its row showed when it was ticked, so a pin closed again
  since is refused, not confirmed. A pin closed with nothing said has no result to show: its row leads to its card
  ([카드에서 확인]). What was not confirmed - closed again, reopened, gone, not sent - is
  named in one banner, and [다시 시도] sends again only the pins that did not reach the server. The rows follow the
  list's filters and order, take the section head's insets (a box under the head's chevron, the text under #N, the
  buttons on the head's right edge) and are used with the keyboard alone (Esc ends the pick). The agent contract does
  not change: the viewer sends the one-pin `POST /api/pins/{id}/confirm`, one per pin, all started at once.

### Fixed

- **[검토 M] no longer hides the first review card under the section's head on a phone or a tablet.** The jump scrolled
  the review section to the very top of the sheet, under the stuck tool bar, so the section's sticky head stood under
  the bar and covered the top of the first card. The section now stops under the bar.
- The agent contract (`pins.md`, HTTP API) is unchanged.

## 0.4.53 — 2026-11-07

### Fixed

- **A sheet pulled up to the document bar and let go slowly stays on the bar** (#456). On a phone or a tablet, the
  sheet dragged by its grabber as high as it goes and let go without a fling stood 1px below the document bar: the
  height it was held at (the visible height less the gap) was saved as a fraction under 1, and drawn again rounded
  down to a whole pixel. Held at its highest, the release now chooses the highest stop, as a fling does - with the
  keyboard up too, so the sheet goes back under the bar when the keyboard goes instead of staying 300px lower. Let go
  anywhere lower, the sheet keeps the pixel it was let go at, where about every other release had come back 1px lower.
- **A control that cannot be pressed no longer answers the mouse** (#416). A disabled button - [더보기]'s
  [브라우저 알림] row where notifications cannot turn on - and one that waits (`aria-disabled`: a page verdict line's
  words before the first pin list) filled with the hover colour, as if a press would do something. Every hover rule of
  the viewer now skips both, and so does the touch press wash; the rules keep their specificity, so nothing else
  changes look. The pointer says which of the two a control is: not-allowed over one turned off (`disabled`), the busy
  pointer over one held for a moment (`aria-disabled`), where an arrow with no hover look read as broken.
- **A segmented control is one Tab stop, walked with the arrow keys** (#417). The one-of-many segments - the kind and
  assignee rows of the composer and the edit card, [더보기]'s theme and language, the navigation sheet's
  [원고 | 변경사항], the changes view's quick range and [이전 | 지금] - took one Tab stop per word and ignored the
  arrows. Tab now enters on the chosen word and the next Tab leaves the segment; ←/→ (↑/↓) move to the previous or next
  word and choose it, wrapping at the ends, Home/End go to the first and last word, and a disabled word is passed over.
  On the assignee row, which draws its words again on every pick, the focus stays on the word in the same place. A key
  that lands on the word already chosen only moves the focus. The two segments whose choice changes the context -
  [더보기]'s language, which reopens the page, and the phone navigation sheet's [원고 | 변경사항], which changes the view
  and closes the sheet (Home on the chosen 원고 shut it) - are walked without choosing, as tabs with manual activation
  are (WCAG 3.2.2): the keys move the focus, and Enter or Space chooses.
- **The list order, [더보기]'s panel width and the range ladder are walked with the arrow keys too** (#438). The
  list's [최신순 | 위치순 | 번호순], [좁게 | 보통 | 넓게] (the phone's [낮게 | 보통 | 높게] for the sheet) and the range
  ladder of the composer and the edit card were rows of toggle buttons, one Tab stop per word. They are one-of-many
  segments now, as #417 made the others: one Tab stop on the chosen word, and ←/→ (↑/↓), Home and End move and choose
  at once - the list sorts again, the panel or the sheet takes the size, the range becomes the rung's lines. None of the
  three changes the context, so none waits for Enter or Space. The groups that draw their words again - the assignee
  row, the ladder (once more when the excerpt's missing lines come back) and the width - give the focus back to the
  word in the same place after any press: Enter or Space on a rung or a width had dropped it on the page, and the next
  Tab started from the top. The focus given back shows the word's description only after a key, as the keyboard's
  focus does, not after a click. The width control checks the width the panel has in the layout now, open or folded:
  on a tablet, whose panel starts folded, it checked none, not even the one just chosen, and after a change of layout
  with [더보기] open it checked the old layout's width. In Firefox an overflowing range ladder or assignee row is one
  Tab stop too: the browser made its scroll box a stop of its own. A press on the gap between two words gives the focus
  to the chosen word, not to the box, so the next Tab goes on from the ladder; in Firefox it began again at the page's
  start.
- **Tab rests on a mark badge in turn and shows it, passing over only one no scroll can show** (#418). On a tablet or
  phone with the sheet open, Tab put the focus ring on a badge under the sheet, out of sight, and its tooltip floated over
  the sheet. A badge is a Tab stop while the pages can scroll it, up or down within their ends, to where it stands whole
  in the pages' box clear of every cover in its columns - the panel or sheet, or the status line standing on it (the first
  visit's line on the tablet's closed sheet) - wherever it stands now, and Tab and Shift+Tab bring it there, 8px clear: the
  browser had scrolled a badge only to the pages' edge, under the sheet, where the focus and its description stayed. So
  Tab from #3 goes to #4 and #5 under the sheet, then #6; passing over every badge a cover was over at that moment went
  from #3 to #6, and the scroll that brought #6 up showed the two it had passed. Passed over are a badge under the overlay
  panel, which runs the pages' height (measured again once it has slid in), one at the last page's foot that the pages
  end before bringing above the sheet, and every badge with the sheet pulled up to the document bar. A badge a cover is
  over shows no description; a focused one a scroll takes under a cover loses it and keeps the focus, and one the sheet a
  key opened comes over is brought out again. The check compares boxes and costs well under a millisecond per scroll
  frame with hundreds of badges.
- **At 320px the sheet bar's [⬚] keeps its 44px press area** (#418). With a pin awaiting review, the left cell was
  narrower than the pin chip and [⬚] together, so [⬚] stood in the grabber's column and answered only 38px. Under 332px
  the bar's side edges are 4px instead of 12px; the gap and the icon keep their size, and in Korean the chip keeps its
  words (핀 2 | 검토 1). The bar's hit areas are placed without a transform: a hit test rounded a transformed box's
  fractional edge, and in Firefox [⬚] answered 43.6px at 330 and 331px and the grabber 43px at 331.
- **Tab crosses the tool bar from left to right in every band** (#418). The bar is one markup, the phone and tablet
  sheet's, that the other bands draw in their own order with CSS `order`, and Tab follows the markup: on the desktop the
  first stop was [⋯] at the row's right end, then back to [PDF 재빌드]; on the mid rows (1024x768 and 841x673 by touch,
  701 to 1099px with a mouse) and the landscape phone's top row it went [핀] [검토] at the right end, back to [⬚ 선택] at
  the left (touch only), then [⋯], then back left to the status line's actions. When the band changes, the markup now moves into the order that
  band draws (`placeBarTools`), and back to the sheet's on a sheet; nothing on screen moves, and a control that has the
  focus keeps it, also from a sheet straight to the desktop, whose bar shows only once the panel is drawn for it.
- **A page list row's focus ring is whole** (#418). The page list - the page count's popover and the phone's navigation
  sheet - scrolls, so it clips what passes its sides, and its rows fill its width: the ring every control draws 1px
  outside its box lost 3px on both sides of every row, on the first row's top and on the last row's bottom. The rows
  now draw it inside (`outline-offset: -2px`), as the documents popover's rows do.
- **A reduced-motion setting changed with the viewer open reaches every jump** (#418). The viewer read
  `prefers-reduced-motion` once, at load, for its scripted scrolls: turned on later, a page jump, an outline entry, a
  card's [보기], a Markdown heading and the pin list's card and review jumps still glided (only the panel's slide and the
  outline's follow heard the change), and turned off later they stayed instant. Each scroll now asks the setting as it is
  (`scrollMotion()`), so the next jump follows it; with it on, a jump lands before the call returns and the pages' glide
  guard and a heading jump's flight are not set. The changes view's [바뀐 곳] glided whatever the setting; it follows it
  too. A guard in `test_viewer_scroll_writes.py` keeps every scripted scroll's `behavior` instant or `scrollMotion()`.
- **An image that loads before a scroll's frame no longer takes the document back** (#435). On the Markdown and text
  surfaces the reading spot is read on a scroll's animation frame; on a renderer too busy to paint an image's load or
  failure came first and put back the spot read before the scroll. Home pressed while a linked document's images loaded
  went back down 240-1,230px with the page's frames held (on CI now and then, `HeadingJumpFirefox`, 1,817px and
  2,947px), End before an image shrinking near the end stopped 217px short of the end, and the browser's find, a pin's
  [보기] and [바뀐 곳] were undone the same way. Just before an image changes size, a pane found elsewhere than where the
  spot was read is read again there (`mdSpotFresh`), unless that offset is the one a reflow at the same width makes
  itself - the offset read before beyond what the pane can scroll now and the pane at its new end, as when a web font
  that came late shortens the document - and then the spot read before is put back across the reflow, as after a width's
  change; any other offset is a move, whatever reflowed the column (Home after a run of raw HTML blocks opened or
  closed, after a font's cut); during a jump to a heading an image's change reads the spot where the jump leaves the
  pane (`mdPicMoved`), so an End after a failed image shortened the document is not taken for that cut; an image's box keeps the ratio its load gave it until its next load is handled
  (`mdPicSize`), so the browser no longer reshapes it beforehand and cuts the offset at a document's end, which #433's
  first try took for a scroll; a pin's [보기] and [바뀐 곳] read the spot where they land (`mdShowLines`), so a width that
  changes before their frame keeps their place. The spot also keeps the px of the room past its line's end (a line's
  leading, a margin), which it used to drop: put back, a top in that room moved up to 8px.
- **In Firefox a key, a wheel or a press during a heading jump now ends its smooth scroll too** (#441). On the
  Markdown surface such an input ended the jump to a heading but wrote the pane's own offset to end its smooth scroll,
  and once Firefox's compositor (APZ) had moved the pane that write reached it as nothing: the scroll went on to the
  heading, with an arrow key's or the wheel's own step added to its destination (in the new tests the pane came to
  rest some 8,800px past where a press found it, one ArrowDown step or 300px of wheel past the heading). On CI it showed as a pane taken back to the heading after Home at the top
  (`HeadingJumpFirefox`) and as an End that never reached the end (`ErrorOnAJumpThenEndFirefox`). The input now writes
  the offset a pixel off and back in one task - down at the very top, up elsewhere - which ends the scroll where the
  pane stands in every engine; the key's step or the wheel's turn then goes from there. Nothing is drawn between the two
  writes, and a jump nobody interrupts glides as before. The End test no longer waits for the jump's scroll to rest
  first.
- **A field's first key puts its caret back, so a tap into it takes the keys** (#431). Leaving a panel field by a
  press on static text (the range caption) left the document's selection in that text, and a tap back into the field
  moved the focus but not the selection. While the two were apart the browser turned no key into an edit: at the fold's
  inner screen (673x841, macOS Chromium) a note rewritten right after the tap lost what was typed in its first 350ms,
  until the sheet's own scroll moved the selection (`@Bob Park 확인` came out `확인`). The first key in a field now puts
  its caret back where it already stands before the key is handled, which takes the selection in with the focus. A
  selection being made in the field is left alone.
- **A field's scroll keys stay in the field, so the pages do not move under what is being written** (#414). In the
  verdict reason field, Home pressed while writing scrolled the PDF pane to the top on macOS (-1104px at 1920x1080),
  the reading page changed and the open field closed with what was in it; End, PageUp and PageDown did the same, and
  in the tablet sheet the composer's note moved the panel instead. The page keys are no field's keys on any host, so
  PageUp and PageDown are dropped in a text field everywhere; Home and End are dropped only on macOS, where they are
  not a field's caret keys. Only the default goes, so the caret stays where it stands. A key with a modifier
  (Shift+Home selects, Cmd+Up is the host's caret key) is left to the host.
- **A field's scroll keys stay in it mid-syllable and while it is read-only** (#452, after #449). #449 drops the
  default of PageUp and PageDown in a text field on every host, and of Home and End on macOS. Two cases still moved
  the scroller outside. A key pressed while a Hangul syllable was composing comes marked composing, and the viewer left
  it to the input method: Home in the reason field with '나' composing took the pane to its top on macOS (-2208px at
  1920x1080, page 3 to page 1, the field gone), End to its end, and PageUp and PageDown moved it on Linux too. Now those
  keys are dropped mid-syllable as well. The composition is not touched: it stays open, and the syllable committed after
  the key and the next one land in place ('가나다'). And a field that is read-only for a while - the reason field while
  its save is out, the suggestion's editor until the range's text is read - takes no caret key, so Chromium gave the
  arrows (40px, sideways too when the PDF is zoomed wider than the area), Space and Shift+Space (a screen; Shift+Space
  closed the reason field) and, on Linux, Home and End (-1671px and +9684, the field gone) to the pane, and in the
  tablet sheet to the panel. In a read-only field those keys are now dropped on every host; Shift with a moving key
  moves nothing outside, so it is left alone (Firefox extends the selection with it; Chromium keeps the selection as
  it was in a read-only field). Firefox moved nothing outside in either case; its
  caret in a read-only field now stays where it stands too. Chords with Ctrl, Alt or Cmd are still the host's (in a
  read-only field Ctrl+Home and Cmd+Up can still move the pane).
- **A long field's keys move no page at its ends either** (#455, after #449 and #452). A field that holds more than it
  shows was left its scroll keys, as scrolling inside it is the field's own doing. At its end, though, Chromium handed
  the key on to the scroller outside: with forty lines in the reason field (106px of 728 shown) scrolled to the end,
  PageDown moved the pane +873px, and in the read-only field (its save out) ArrowDown +40, Space +873 - the reading page
  went from 4 to 5 and the field closed - and End +4034 on Linux; at its top PageUp, Shift+Space and Home went up the
  same way, and ArrowLeft and ArrowRight moved a zoomed pane 40px sideways at any height, as the field has no width to
  scroll. Such a field is now left a key only while it can still scroll that way (up: `scrollTop > 0`; down: short of
  `scrollHeight - clientHeight` by more than a pixel; sideways by its width); at that end the key's default is dropped
  as #449 and #452 drop it, and the caret stays where it stands. In the middle the field scrolls and the pane stays, and
  a key going back from an end (ArrowUp at the end) is still the field's. A writable field's PageUp and PageDown are
  dropped in the middle too: Chromium moves the caret a page and lines it up with the scroller's top, so they moved the
  pane from anywhere in the field (+226px beside the pages, +576 under them, PageUp downwards as well). The caret no
  longer pages through a long field with them; the arrows and the wheel still do. Firefox moved nothing outside in any
  of these.
- The agent contract (`pins.md`, HTTP API) is unchanged.

## 0.4.52 — 2026-11-06

### Added

- **A Markdown document's changes view draws both versions and marks what changed (ADR-0031).** The changes view of a
  Markdown document opens on a new tab, [그린 비교] (Rendered), next to [소스 diff]: the document as it was before the
  commit (its first parent, or a range's old side) and as it is at the commit are drawn with the Markdown surface's
  renderer and compared block by block - a paragraph, a heading, a list item, a table row, a code block, display math,
  the front matter, a rule, a raw HTML placeholder. One column: the new version with each removed block put back where it
  was, struck through; a block changed in place has its removed words struck through and its added words marked; a moved
  block leaves one line at its old place ("The 2 blocks here moved to L5–L7"). A block whose words stayed but whose
  structure changed (bold, out of a quote, list numbering, an image's alt text, a table column's alignment, a code
  block's language or spacing) is a changed block that says what changed; a paragraph only rewrapped in the source -
  inside bold, a link or a formula too - is unchanged. A removed block goes back into the very list, item or table it
  sat in. A list item's key is its own text's: an image, a link or an alt text in a quote or table inside it belongs to
  that block. A quote or list split in two (a blank line between a quote's paragraphs, another bullet) or two joined
  into one marks the two blocks beside the cut and says so; every bullet of one list changed is no change, and two
  tables joined or one split show as the header row taken out or added, not as a quote or list. Each change
  is a tint and a word in the left gutter, never colour alone; a screen reader hears "Added block:" and so on. A
  navigator steps through the changes and the status line counts them. A range - picked in the list, or the new commits
  a document-changed message's [변경 보기] opens - is compared in [그린 비교] too, with its commit and file counts, unless
  [소스 diff] was the tab last shown: that tab is kept. Characters that hide or reorder text stay in their boxes on both
  sides, and a changed one is a changed word. Images on both sides are the manuscript tree's files of now, and the
  compare says so; links inside the document stay words. A side over 1 MiB, not UTF-8 or not a file is not drawn: the
  compare says why and offers the source diff. A text document keeps its source diff.
  - **A pin's [변경 보기] still opens its source diff** - the pin's own hunks, the rest folded (ADR-0005). [그린 비교]
    beside it shows the whole commit with the pin's blocks ringed, and says it is the whole commit. A pin-only drawn
    version is a later step.
  - **New read route for agents and the viewer:** `GET /api/revision-source?doc=&commit=[&base=]` gives the document's
    file on the two sides the source diff compares, `{id, base, merge_base?, path, old, new}`, each side `{lines,
    git_line_starts?}` (lines as `GET /api/source` counts them; where git's LF-only lines start among them, only when the
    two differ), `null` for no file, or `{reason}` (`source_too_large` with `bytes`/`limit`, `source_not_utf8`,
    `not_a_file`, `source_unreadable`). Only commits of the document's history window, at the path it was registered
    with; 1 MiB a side; it writes nothing. Other documents get `404 commit_not_recent`; a range's refusals are the source
    diff's.

- **Markdown documents show YAML front matter and TeX math as written (ADR-0032).** Front matter at the very top of a
  `.md` file (a first line `---`, a second line that opens a YAML mapping - `key:` or a `#` comment - and a closing
  `---` or `...`: Pandoc's rule and a check of the second line) is one open block of its own: a head line "Front matter · YAML, N lines" over its lines
  exactly as the server sends them, never parsed, long values wrapping inside the box. It is no longer drawn as a rule,
  paragraphs and setext headings, so a skill file's `name:` and `description:` no longer stand in the outline and the
  section strip. TeX math - `$…$` and `$$…$$` by Pandoc's dollar rules (so `$5 and $10` stays text), `\(…\)`, and `\[…\]`
  on lines of its own - is recognised, never rendered: it shows its source, delimiters and backslashes included, in the
  code face, so emphasis and escapes no longer eat the `*`, `_` and `\` inside it (`$t^*$ … $t^*=\infty$`). Inline math
  has no tint and keeps every line of its paragraph on its own source line; display math is a code box like a code
  block. A code span comes before math, also across line ends. Characters that hide or reorder text show by name in
  their boxes in both, as in the rest of the drawn body.
  - **Two new pin kinds for agents:** tapping the front matter picks the block, saved as kind `md:front` (scope
    `block`; the ladder is chosen lines -> front matter): edit those YAML lines. Display math is kind `md:math` (chosen
    lines -> math -> section): edit that TeX; its `quote` is the TeX as written. pins.md's range column names both.
    Nothing changes on the server, and 0.4.51 reads, keeps and lists these pins as they are (it draws the front matter as
    a rule and paragraphs and the math as text, on the same lines).
  - **Not included:** rendered math (KaTeX), Typst, `.qmd`/`.Rmd`, TOML front matter (`+++`) and metadata blocks in the
    middle of a document. In a table, a `|` inside math must be written `\|`, as on GitHub.
- **The viewer says what arrived while you read (ADR-0033).** One status-line message per kind of news, from reads the
  page already makes - no new endpoint, storage or agent contract:
  - a document changed (a merge the instance pulled, a push without a PR, an edit in the server's tree, a figure or PDF
    fetched again): `본문이 바뀌었습니다 — PR #12 … · Bob Park · 핀 2개 줄 이동`, until closed. [변경 보기] opens only the
    new commits, and keeps to them when a build comes while it is open; a drawn Markdown or text document also tints the
    changed lines and [바뀐 곳] steps through them. When the build's commit cannot be known, no PR or author is named;
  - new pins by coauthors or agents, one message per document; replies and edits on others' pins are not news;
  - events addressed to me (mentions, replies, review waits, reopenings, assignment, deletion), now in the tab whatever
    the browser-notification switch says; the switch decides only system notifications;
  - a different Limn on the server: [새로 고침], which first says so if a reply or edit is being written, never
    reloading by itself;
  - back after more than two minutes away: one line for everything that came meanwhile.
  News of one kind grows one message (an agent closing twelve pins one by one is one line). What this browser has seen is
  kept in its `localStorage`, shared by its tabs, and only moves forward.

### Changed

- **A drawn Markdown document marks the characters that hide or reorder text, as a text document does (ADR-0029 D5).**
  Bidirectional overrides and isolates, zero-width characters, controls, tags and the rest of the same repertoire now show
  by name in their box wherever the document draws its source's text - paragraphs, headings, list items, table cells,
  link text, inline code, code blocks, the raw HTML placeholder's first line, an image's alt text, and the line view a
  limit falls back to - so a line never reads in another order than its source (a Trojan Source line in a README reads as
  it is). The character stays in the text: a selection, a copy and a pin's quote keep it. The same exceptions apply (an
  emoji's joiners, the file's first byte-order mark), entities markdown-it decodes (`&#x202E;`) are marked too, and a
  notice above the document counts them. The outline's rows and the section strip name them as text (`⟨U+202E⟩`). A box
  counts as two of the 60,000 drawn elements; past the limit the line view names them as text, as the text surface's
  names view does. A document with none of them draws as before (about 2 ms more for 1 MB of paragraphs).
  A document with a NUL (U+0000) anywhere is shown as its source lines, its NULs in their boxes, with a line saying why:
  markdown-it turns NUL into U+FFFD (CommonMark's rule) and keeps no column to put it back by (`data-limit` `nul`).
- **A tree image rewritten on disk shows without reopening the page.** While a Markdown document is open, the light poll
  asks the images that have loaded near the document area again (at most six, nearest first and then the one asked
  longest ago, so more than six on screen take turns; every four seconds or more, one request at a time) with a revalidating `GET /api/asset`; an image whose `ETag` moved on is loaded again from its
  address with `&v=<tag>` (the server reads only `doc` and `path`), keeping the reading line as any image that loads does,
  and a redraw keeps the new picture. The tag of the picture shown is read when it loads, from the answer its `<img>` left
  in the browser's cache; with nothing cached (the cache cleared or turned off) it is unknown, and the first check moves
  the image once to the address of the tag now rather than taking that tag for the old picture. No route or field is
  added. This and the stat `304` below reverse two trade-offs ADR-0030 accepted; ADR-0034 (approved) records them.
- **An unchanged tree image revalidates without being read.** The server keeps, per run and in memory only, the content
  tag of each image it sent under the identity of the file it read (resolved path, device, inode, size, mtime and ctime;
  at most 1,024, the least recently asked dropped first), so an `If-None-Match` for an unchanged image is one no-follow
  stat and a `304` - the file is not opened (an 8 MiB image: about 12 ms of reading and hashing before, about 0.06 ms
  now). The `ETag` is still a hash of the content. A rewrite - at the same size, with its mtime put back - is read again,
  and a file changed less than two seconds ago is not remembered.
- **The agent contract gains values, one read path and a meaning fix; nothing is removed or renamed.** Pin `kind`
  `md:front` (fix those YAML lines, keeping YAML syntax) and `md:math` (fix that TeX; its `quote` is the TeX as
  written); `pins.md`'s range column names them, and 0.4.51 keeps such pins byte for byte. `GET /api/revision-source`
  serves the viewer's rendered compare (both sides of a drawn document; a side's `reason` `source_too_large`,
  `source_not_utf8`, `source_unreadable` or `not_a_file`); agents have no use for it. `GET /api/version` now names the
  code the process runs. A figure document whose map names more than 200 files answers `/api/revisions` with
  `reason: "too_many_files"` and `/api/revision-diff` with `404 too_many_files`, and startup refuses a document under a
  dot-named folder. Nothing to rebuild.

### Fixed

- **`--main` with a text document's suffix is refused at startup,** as a `.md` already is: `limn serve --main plot.py`
  (or `notes.txt`, `config.yaml`, any of ADR-0029's suffixes but LaTeX's own `.bib`, `.sty`, `.cls`, `.bst`, which can
  hold a LaTeX main) used to be built as LaTeX and fail; it now stops with the `--doc <key>=<name>:<path>` form that
  registers a text document; a figure map (`figures.limnmap.json`) is refused with the figure form. `limn add --main`
  refuses both the same way before writing any configuration.
- A pin's quote taken by a tap, or from a selection cut back to the document, keeps a hidden character exactly where it
  stands. It was read with `innerText`, which in Chromium put a line break on each side of the character's box and in
  Firefox dropped bidirectional controls altogether (on the text surface too).
- **`GET /api/version` names the code the server runs, not the file on disk** (HTTP API semantics, #415). It read
  `__version__` from the package file on every request, so a checkout pulled or an install upgraded under a running
  server made it answer the new version while the old code kept running - an instance 28 releases behind looked
  current. It is now read once when the process starts (`limn serve --version` gives the same value), so it changes only
  after a restart, and a difference from `limn version` (the installed one) shows an instance that was not restarted.
  The path, its fields and their types are unchanged.

### Security

- **The change view no longer shows readers files it promises to withhold** (GHSA-qf8q-c9hg-3ph4). The commit history,
  diffs and comparison PDFs (`/api/revisions`, `/api/revision-diff`, `/api/revision-build`, `/api/revision-pdf`) could
  include committed files under a dot-named folder (`.git`, `.private`, …) and files outside a document's own sources:
  - each document's source folder, main file and repository are now the ones resolved at startup and used literally,
    so a folder later replaced by a link (by a local account, or a pushed symlink fetched by `--git-pull`) no longer
    leads the history, diff or pin scope elsewhere;
  - dot-named parts are left out of every history pathspec (the LaTeX `**/*.tex` ones too), figure scope and comparison
    build snapshot. A main that `\input`s a dot-folder file can no longer put it into a comparison PDF. The comparison
    cache key changed, so PDFs built before are built again;
  - a figure map's files under a dot-named folder are left out, and a map naming more than 200 files gives no history
    (`too_many_files`) instead of widening the scope to the whole folder;
  - glob characters in a registered folder's name (`paper[1]`) are matched literally, not as a pattern that also takes
    in a sibling `paper1/`.

  `/api/source`, `/api/snippet`, `/api/overlaps`, `pins.md` and `/api/pins` were not affected. A document registered
  under a dot-named folder is now refused at startup.

## 0.4.51 — 2026-11-05

### Added

- **Plain text and source code can be registered, read and pinned in the viewer (ADR-0029).** A `--doc` path whose
  suffix is on a closed list of 48 - prose and data (`.txt`, `.rst`, `.csv`, …), configuration (`.json`, `.toml`,
  `.yaml`, `.ini`, `.xml`, …), code (`.py`, `.r`, `.js`, `.ts`, `.sh`, `.c`, `.go`, `.rs`, `.sql`, …) and LaTeX's other
  sources (`.bib`, `.sty`, `.cls`, `.bst`), in any case - is a text document (or
  `limn doc add <name> --doc '<key>=<name>:<path>'`): no build, no PDF - the viewer shows the file's lines as they are, in
  one monospace column with line numbers, never parsed and never highlighted. A press picks its line, a drag the lines
  it covers; the range ladder is chosen lines -> paragraph (between blank lines) -> indented block (a function, a YAML
  item, a call's arguments, a `.bib` entry), the shorter first. Pins are ordinary line pins of that file with no page,
  take suggested edits and verdicts, and the changes view opens on the file's source diff. Long lines always wrap,
  their continuation hanging under the indentation, so the page never scrolls sideways. It keeps its reading line
  across width changes and its focus after Esc or a save as a Markdown document does (below); the document area is
  named "Text document", and each pin badge stands just before its own line.
  - **Not accepted:** files without a suffix (`Makefile`), suffixes not on the list, and `.typ`, `.ipynb`, `.env`,
    `.pem`, `.key`. `Figures.LIMNMAP.JSON` (a figure map's suffix in another case) is refused rather than shown as text.
  - **Line ends:** Limn numbers lines as Python's `str.splitlines()` does. A file with line ends that are not LF or CRLF
    (a form feed, U+2028, a lone CR) gets a notice naming them, because its line numbers past them differ from an
    editor's or git's. A copy keeps each line's text exactly and joins lines with LF.
  - **Limits:** 1 MiB and 50,000 lines, as for Markdown; past 60,000 drawn elements the hidden characters are named as
    text instead of boxed (a notice says so, and that a copy then gives the names).
  - **Rollback:** 0.4.50 and earlier do not start with a text document in the configuration. Take it out first
    (`limn doc remove <name> <key>`), then `limn update --ref v0.4.50`; its pins stay in the state folder and show under
    the documents not configured.
- **A Markdown document shows the images of its manuscript tree and opens links to the other documents (ADR-0030).**
  An image whose source is a relative path - resolved against the document's own folder, `/` the tree's root, as
  GitHub reads a repository - that stays inside `--manuscript` and ends in `png`, `jpg`, `jpeg`, `gif`, `webp` or
  `svg` is drawn, lazily, in a box that keeps its place until its size is known; the text being read stays where it is
  when an image above it loads, also one that loads while the changes view is open, and a jump to a heading is not cut
  short when the column changes width on the way. A pin on an image's line outlines the image, a click on it picks its
  paragraph, and in the dark theme a light plate stays behind it. A remote, `data:` or out-of-tree image is still its
  alt text, and its tip now says why. A relative link to another registered document (its `GET /api/docs` `path`)
  switches to it, at its `#heading` for a Markdown document (where a link followed from the keyboard leaves the
  focus), with one history entry so the browser's back returns (none while a phone's back layer is open); a link to an
  image of the tree opens it in a new tab; any other relative link stays text and says why. A tip that shows a path or
  a `#heading` names the hidden characters in it, as the excerpts do. The allowlist of absolute links is unchanged.
- **`GET /api/asset?doc=&path=`**, the read route those images load from: a normalized tree-relative image path only
  (`400 bad_asset_path` otherwise), the same tree check as every file route, the content checked against the suffix's
  format (`415 asset_not_image`), at most 8 MiB (`413 asset_too_large`) and 8192 × 8192 pixels for a raster image
  (`413 asset_too_many_pixels`), `422 asset_unreadable` when the file goes away after the check. The same roles as
  `GET /api/source` read it, and it writes nothing. Agents have no use for it: a pin on an image's line is an ordinary
  line pin.

### Changed

- **Characters that hide or reorder text are shown by name, in every document.** A bidirectional override, a
  zero-width or tag character and the other default-ignorable and control characters (not tab or LF) can make a line
  read otherwise than its source (Trojan Source). On a text document's lines, in the excerpt under the ladder, a rung's
  label, a card's quote, every suggestion diff and the changes view's source diff, each now stands in a box with its
  name (`U+202E`), kept in the text so a copy still has it; a text document's head counts them. Sequences that need one
  (an emoji's joiner, a joiner between Persian or Indic letters, a variation selector after a Han character, a BOM at
  the file's start, …) are left alone. Under the suggestion editor, which cannot show them, a line warns when the
  draft adds any and shows the lines that hold them.
- **The agent contract gains values and two additive fields; nothing is removed or renamed.** Document `kind` `text`,
  `scope` `indent` and pin `kind` `indent`; a text document's `pins.md` section title ends in `— 텍스트(쪽 없음)`.
  `GET /api/source` adds `line_ends` (`{"U+000C": 2}`, `{}` for none). In `pins.md`'s `## 제안 문안`, a suggestion whose
  text adds such characters to its base gets one line under its heading, `숨은 문자: 원문에 없는 U+202E 1개 — …`:
  agents ask in a reply whether those characters are needed before applying it. A `pins.md` without such a suggestion
  is byte for byte unchanged. Make a pin on a text document with `file`, `lo` and `hi`; a `page` sent is dropped. There
  is nothing to rebuild.

### Fixed

- **A Markdown document keeps its reading line when its column changes width.** A rotation, collapsing the panel
  beside it or resizing the window reflowed the column and kept only the scroll offset, so the top line jumped by tens
  of lines (L247 to L307) and a chosen line could leave the screen with only the composer showing. The line at the top
  and how far into it the top stands are kept across every reflow, as the PDF surface keeps its spot, and a chosen line
  that was on screen is brought back into view. Opening the changes view and coming back keeps it too, also when the
  window turned meanwhile, and when the source changed on disk and was drawn again while the changes view was open.
- **[위치 다시 잡기] on a Markdown pin marks the candidate in the document,** as the PDF surface draws its box, and the
  banner and the moved-pin message write a one-line range as `L9`, not `L9-L9`, on both surfaces.
- **Screen readers and the keyboard on a Markdown document.** The document area is the region "Markdown document", not
  "PDF pages", and the composer's and the cards' quote say the text was chosen in the document. Pin badges come in line
  order, each just before its line, instead of after the last link in pin order; they stay where they were drawn. The
  document says its language is unknown (`lang=""`), so an English screen does not read a Korean document with an
  English voice. An outline entry is named by its heading alone, not the dot and the line label, which is its
  description.
- **Esc, [취소] and a save leave the focus at the place, on both surfaces,** instead of on the page's body, where the next
  Tab went to the sidebar: Esc and [취소] put it on the line clicked (Markdown) or the page of the selection (PDF), and a
  save or an append on the pin's badge or mark. A save whose answer comes after a new selection was opened leaves the
  focus in the new note. A composition cut off by its field going away (switching documents while a verdict reason was
  being composed) no longer keeps the focus on the page's body afterwards.

### Security

- Every `/api/asset` answer carries its own policy, `default-src 'none'; style-src 'unsafe-inline'; img-src data:;
  sandbox; frame-ancestors 'none'` (an SVG opened on its own is an inert document of an opaque origin that runs no
  script and fetches nothing), `Cross-Origin-Resource-Policy: same-origin` (another site cannot embed an image to
  learn whether a file exists or how large it is), `nosniff` and a media type taken from the suffix alone. The viewer
  page's policy is unchanged.

## 0.4.50 — 2026-11-05

### Security

- **No GET writes anything persistent (ADR-0027, ADR-0028).** A page on another site could make the owner's browser
  send Limn GETs (an image, a script, a no-cors fetch) or open `/`, and the viewer's own requests then recorded the
  visit, re-saved pins, cleaned the trash and created comparison folders. Every GET (and any future HEAD) now runs
  under a read-only scope: no file or folder is created, changed or deleted and no writing work is scheduled, and the
  Git reads behind the change view can neither fetch missing objects nor refresh the index. Pure GETs still need no
  Fetch Metadata, so curl, agents and old browsers work as before.
- Path arguments are length-limited before parsing, and repeated tracebacks and damaged-pin warnings are capped and
  de-duplicated.
- GET computation slots are taken only after the request body is read and the request admitted, so incomplete or
  refused requests cannot hold the four read slots.

### Changed

- **People are recorded only on real changes.** Opening or polling the viewer no longer records a reader or updates a
  name, photo or seen time; a person is recorded after an authorized change (a pin, a reply, a close and the like). A
  new reader with no stored row and no pin is not in the people list or the @-mention candidates until their first
  change, and owners add viewers with `limn member add`. Existing rows and roles stay. The mention help and the
  `unknown_assignee` error now say who can be mentioned.
- **GET serves saved pin positions, and upkeep saves them soon after a manuscript change.** GET returns only saved
  positions and revisions, so an edit based on a position the manuscript has since moved is refused as stale, as
  before. A request-independent check stats the pinned sources every 2 seconds and runs a pass when one changed,
  besides startup and every 60 seconds; a pass re-syncs and saves pins, rewrites `pins.md` and prunes the trash,
  writes nothing when nothing changed and keeps the originals when it fails. After a manuscript edit, pin positions in
  the viewer and in HTTP and disk `pins.md` trail by about that interval plus the pass time (longer if a pass is slow
  or fails).
- The agent contract (`pins.md` format, HTTP API) is unchanged; what changed is who is recorded and when positions are
  saved.

## 0.4.49 — 2026-11-05

### Fixed

- **A triple click on a Markdown document's last paragraph picks its lines.** Chromium ends that selection after the
  document (there is no next block to end at; Firefox ends it in the paragraph), and a selection reaching outside the
  document was dropped whole, so the first click's pick stood: at desktop width the pin was saved as the paragraph
  block instead of the chosen lines, and in the mid layout no composer opened. Only the part of a selection inside the
  document counts now - the same for a drag that starts above it - and its quote is that part's rendered text. A
  selection with both ends outside the document (select-all) still picks nothing.
- The agent contract (`pins.md`, HTTP API) is unchanged.

## 0.4.48 — 2026-11-04

### Added

- **Markdown documents can be registered, read and pinned in the viewer.** A `--doc` path ending in `.md` (or
  `limn doc add <name> --doc '<key>=<name>:<path>.md'`) is a Markdown document: no build, no PDF - the viewer draws the
  file itself as one flowing column (CommonMark with GFM tables and strikethrough) and every block it draws carries
  its source lines. Drag over text to pin those lines, click or tap a block to pin it, or a heading to pin its section;
  the range ladder is chosen lines -> block (or the blocks a drag spans) -> section. Pins are ordinary line pins of the `.md` file with no page
  (`pins.md` writes `—` in the page column), take suggested edits in Markdown, and show as tinted lines with a number
  badge in the left margin. The outline comes from the headings, the changes view opens on the file's source diff,
  and an edit to the file is on screen within a few seconds.
  - **Drawn without running anything:** raw HTML is shown as a placeholder with its lines, never drawn (raw HTML
    blocks in a row, such as a README's head, fold into one placeholder that opens to each block); images are
    not loaded (their alt text stands in); a link opens only if it goes to another site's `http(s)` address, a
    `mailto:` or a heading in the document - the viewer's own address, loopback and addresses with a user or password
    stay plain text. The viewer's Content-Security-Policy is unchanged and applies here too.
  - **Limits:** a file over 1 MiB is not drawn (a notice says its size). A document too deep, too large or too slow
    to parse (nesting 20, 30,000 block or 150,000 inline tokens, 60,000 drawn elements, 2 s) is shown as its numbered
    source lines instead, which still take pins; past 50,000 lines a notice says so.
  - **No page controls:** page counts, the page list, zoom buttons, [select] and PDF download are hidden on such a
    document; find (Ctrl/⌘+F) and zoom, a two-finger pinch included, are the browser's.
  - **`--main` stays LaTeX:** `--main notes.md` is refused with the `--doc` form to use instead.
  - **Agents:** the contract only gains values (document `kind` `markdown`, `scope` `block`/`section`, pin `kind`
    `md:<block>`/`md:section`, already in 0.4.47's server). Make a pin on such a document with `file`, `lo` and `hi`; a
    `page` sent is dropped. There is nothing to rebuild.
  - **Rollback:** 0.4.47 and earlier do not start with a Markdown document in the configuration. Take it out first
    (`limn doc remove <name> <key>`), then `limn update --ref v0.4.47`; its pins stay in the state folder and show under
    the documents not configured.

### Changed

- **The list order `[쪽순]` is `[위치순]` (`Page` is `Position` in English)** on every document: it orders pins by
  where they are, which is a page and a line on a PDF and a line on a Markdown document.
- **A description that ends in an address breaks the address anywhere** and the words before it only between words;
  in the dark theme the description box has a 1px edge.

## 0.4.47 — 2026-11-04

### Security

- **The viewer permits hash-matching inline scripts and styles, and same-origin script and stylesheet files, whoever inserted them.** The viewer page and the page a
  browser sees when it is refused now carry a Content-Security-Policy that is enforced from this release on: inline
  code runs only if its text matches the SHA-256 of the page's own inline scripts and stylesheet, scripts and styles
  load only from the same server, and the one outside resource is an `https:` avatar image. If someone else's text
  gets markup into the page, an event handler, a `javascript:` URL or a `style` attribute in it is refused, an inline
  script or stylesheet in it is refused unless its text matches one of the page's hashes, a script or style from
  another site does not load, and an injected `<base>`, form, plugin or frame does nothing. This narrows what such an
  injection can do; it is not a sanitizer: a script or stylesheet pointing at a file of this server, or inline text
  matching one of the page's hashes, still runs or applies whoever inserted it. It is the
  second wall, behind the viewer's escaping, that the Markdown documents of a coming release are drawn behind. Every
  other response (JSON, `pins.md`, PDFs, page images) keeps `frame-ancestors 'none'` alone, so agents see no change.
  - **What you see:** nothing should look or work differently. The viewer's four `style` attributes became CSS rules
    of the same values (the instance colour stripe takes `--brand`).
  - **Browser extensions:** an extension that inserts its own `<style>` or `<script>` into pages (a dark mode, a
    grammar checker) may be partly blocked on the viewer, and the browser's console shows a CSP report for it. The
    viewer itself is unaffected.
  - **Rollback:** there is no option that turns the policy off or reports instead of enforcing. If a browser shows the
    viewer broken by it, go back to the previous release (`limn update --ref v0.4.46`, which reinstalls it and restarts
    the running instances); no state, pin, setting or API changed, so nothing is left behind.

### Fixed

- **A notification's pin link opens the pin even when the light poll reads the list first.** Clicking a browser
  notification brings the viewer tab forward and opens the pin's card after reading the list again. The tab coming
  forward also starts a light poll, and when the poll's read of the list, asked after the link's, was answered first, the
  link took its own read, overtaken, for a failed one and did nothing: no card opened and the PDF stayed where it was.
  The list the link waited for was already there, so the link now goes on; it still stops when the read of the list
  fails. The pin list and its scroll position were right in that race all along: an answer older than the one the list
  shows is not drawn.

### Internal

- **The pin list's scroll tests no longer fail when the light poll's read overtakes theirs (#392).** They asked that
  their own read of the list was the one drawn, which an overtaken read is not, by design. They now check that the list
  shows a read asked since their change and what it holds, and a new test makes the poll overtake a read whose answer
  predates an agent's close: the late answer is not drawn, and the card and the view stay as the poll left them.

- **Server groundwork for Markdown documents (ADR-0025), not reachable yet.** No `--doc` suffix chooses a Markdown
  document until the viewer can draw one, so nothing below changes what an instance serves today.
  - `GET /api/source?doc=<key>` answers a document the browser draws with its source as
    `{doc, file, src_mtime, lines}`: the lines split as every other line of the server is counted (UTF-8,
    `str.splitlines()`), read through the checked manuscript handle with a 1 MiB bounded read. Over the limit it answers
    `413 source_too_large` with `bytes` and `limit` and no lines; bytes that are not UTF-8 `422 source_not_utf8`; a
    document shown as pages `400 not_rendered_in_browser`; a file outside the manuscript tree the same `400` every file
    route gives. Every admitted role reads it, and it writes nothing. The agent contract gains this path and its three
    reasons; every existing path, field and reason keeps its meaning.
  - A Markdown document's changes are the Git history of its own file. The LaTeX history keeps its suffix pathspec, so a
    LaTeX main and a Markdown document in one folder never share commits. The source diff and a pin's own hunks work on
    it; there is no comparison PDF.
  - A Markdown file inside a LaTeX document's tree is not one of its sources: editing it never marks the LaTeX build
    stale or makes a rebuild run latexmk (a test pins this).

- **Pins on Markdown documents (ADR-0025), not reachable yet.** No `--doc` suffix chooses a Markdown document until the
  viewer can draw one, so no instance serves one today; these rules hold for it once one is served.
  - A Markdown line pin has no `page`, `frac` or `pdf_build`. Sent with a new pin or a re-placement they are dropped
    unread, as an `el` is outside a figure document, so an agent's habitual `page: 1` is no refusal; no `pdf_build` is
    stamped when none is sent; and any write of such a pin removes the page fields and the legacy `frac_build` a record
    still carries: an edit (a note-only one too), a claim or unclaim, a reply, a close (an agent's with `changes` too),
    a confirmation, a reopen, a drop into the Trash, a restore, and the anchor re-sync. A LaTeX line pin keeps its page
    fields exactly as before, and so does a pin of a document the instance does not serve, on every write: an edit
    reads that from the pin's own record, not from the first document, even when the first document is Markdown.
  - `scope` gains `block` and `section`, and pin kinds `md:paragraph`, `md:item`, `md:table`, `md:code`, `md:quote`,
    `md:html` and `md:section` appear. In `pins.md` the range column names them, a Markdown document's section title
    ends with `— Markdown(쪽 없음)` (a lone Markdown document is sectioned, as a figure document is), and the page
    column shows `—` for any line pin without a page. Before, such a pin showed `0`; only a record from before page was
    stored, or a hand edit, has none on a LaTeX document.
  - The suggestion gate asks the document's capability (`takes_suggestions`), so a Markdown line pin takes a suggested
    edit with the same limits, base check and `suggest_state`; a view-only PDF, a figure document and a region pin still
    answer `suggest_unsupported`, whose message now names LaTeX and Markdown, in Korean and in the English viewer. The
    `bad_scope` message lists the two new values. The SKILL counts broken Markdown (a table row's cell count, unclosed
    emphasis or code, a list item's indentation) among the obvious errors to check before applying a suggestion.
  - A request that names only a file goes to the Markdown document whose file it is, even beside a LaTeX main or a
    figure document in the same folder and whatever order the documents are registered in; every other file goes by
    folder as before, so a `.tex` below a Markdown document's folder stays with the LaTeX document.
  - A fourth contract snapshot records the Markdown pin flow, and v0.4.46 reads the Markdown records and writes them
    back byte for byte (`tests/contracts/test_markdown_rollback.py`).

## 0.4.46 — 2026-11-04

### Fixed

- **The key that ends a Korean composition only ends it, on Linux too.** ibus-hangul on Linux commits the last syllable
  first and then hands the same Enter or Esc on as a plain key, so the viewer took it as its own: in a page verdict's
  reason, the Enter that committed `한글` also saved the reason and closed the popover, and in an edit card the Esc that
  committed a syllable of a suggested edit closed the edit and lost the unsaved suggestion. macOS marks that key as
  composing, and it was already left alone there.
  - **The rule:** when a key the input method took in that composition is still down as the composition ends, the first
    key after the end, in the field it ended in and within 100 ms of it, is that key and belongs to the input method.
    Held down, its repeats are that key too, until it comes up: holding the Enter no longer saves the reason on its first
    repeat, nor does holding the Esc close the edit. A composition that no key ended (a click, the focus moving, text
    put in at once) has no such key, and neither has one after the key's release was missed: the field or the window
    losing the focus, the page hidden or left, and a new composition forget a key still down, and a key pressed in
    another field never counts. Where the browser names no physical key (Android's on-screen keyboards), any key's
    release ends it, and its repeats are known by the key's name. While that key is down a page verdict's reason field
    stays as it is: a new build that would rebuild the pages, or a window resize that would move the verdict lines
    beside or under them, waits until it comes up, so the key handed on and its repeats reach the field that composed.
    That wait has an end: if the key's release never reaches the page while the field keeps the focus, the rebuild and
    the move go on 2.5 s after the key's last press or repeat, and at once when another key goes down. Text coming in
    ends neither the wait nor the key: nothing tells the text the input method commits - late when the page is busy with
    the end of the composition, other than it showed, in parts, or before the end - from other text, so the Enter handed
    on after it belongs to the input method whatever the text, and text put in with no key (a paste from a menu) does
    not cut short a wait whose release was missed. A held key's repeats keep the field all along, and a repeat that
    comes after the wait has ended still belongs to the input method, also in the field drawn anew. One limit remains:
    with a key repeat delay set longer than 2 s, Chromium on Linux reports a held key's first repeat as a new press of
    the key, so that press and the repeats after it act as the viewer's keys, as the key held without an input method
    would. One rule serves every field that acts on Enter or Esc: the reason popover, the composer's and the edit card's
    save and cancel keys, replies, the @-list, search, the outline filter, the page number fields and the document
    list's filter. The next Enter or Esc acts as before, and so does a key pressed after that key came up.
  - **What the browser does with it:** that Esc no longer empties the search field or closes the phone's navigation
    sheet either. That Enter still starts a new line in a note, a reply or a suggested edit, as the input method gives
    it, but not in the reason field or while the @-list is open.
- **A screen reader hears a page verdict's save once.** Pressing a word on a page verdict line with the pointer made
  Orca read the word's new description, `This verdict is being saved · Key 2` (Korean `이 판정을 저장하는 중입니다 ·
  단축키 2`), twice before the line's status said the save: the press gave the word the focus and changed its
  description at the same moment. The word being saved now has no description of its own (its hover box keeps the
  words), and the line's status says the save once. The saved result is still read once.
- The agent contract (`pins.md`, HTTP API) is unchanged.

## 0.4.45 — 2026-11-03

### Changed

- **A suggested edit the agent will not apply says so on its card.** A card whose suggestion's lines changed since it
  was written (`Suggested edit · source changed`) or cannot be checked (`Suggested edit · cannot check`) said that the
  agent will not apply it only in the badge's hover box, which touch screens show on a long press, and in words only a
  screen reader reads.
  - **The line:** an open card in either state now shows one line over its diff, in the badge's warning colour:
    `The agent won't apply it · rebase it in Edit` when the lines changed, `The agent won't apply it · can't be
    checked` when they cannot be checked (Korean: `에이전트는 넣지 않음 · 수정해서 원문에 맞추기` and
    `에이전트는 넣지 않음 · 원문과 대조 불가`). The words fit one line in the desktop panel and on the narrowest touch
    cards in both languages.
  - **Its action:** `rebase it in Edit` is a link that opens the card's editor, as [Edit] does; on touch [Edit] is a
    pencil icon alone, so the line no longer names a label that is not on screen. It keeps the line's height and
    answers a 24px click with a mouse and a 44px tap on touch. On touch that area rises from the diff's top edge, with
    the room for it above the line (the suggestion starts 24px under the note), and the diff keeps its own taps: a tap
    just inside the diff no longer opens the editor. A viewer, who cannot edit, gets no action: the changed line
    is `The agent won't apply it` alone, while the unknown line keeps its reason.
  - **The editor says it too:** while an edit card keeps the pin's own base, its line under the editor starts with the
    same warning, in the warning colour: `The agent won't apply it · the source changed meanwhile` with [Use the
    current source], or `The agent won't apply it · can't be checked`. It goes once the base is new (rebased, or read
    again for a new range), as the card's line goes once that is saved.
  - **Where it is not:** cards awaiting review, done rows, ready suggestions and folded compact cards.
  - **The badges:** the two warning badges keep their hover explanation but no longer carry a screen-reader copy of it,
    since the line says it. Other badges and labels keep theirs.
  - The agent contract (`pins.md`, HTTP API) is unchanged.

## 0.4.44 — 2026-11-02

### Fixed

- **Explanations reach the keyboard and screen readers.** The explanation a control shows in its hover box was only in
  that box, so a screen reader heard the composer's [Suggested edit] switch as `switch "Suggested edit"` and nothing more,
  and a card's `Suggested edit · source changed` badge never said that the agent will not apply it.
  - **Controls:** a focusable control's explanation is its accessible description, read with its name (without the name
    again), in the screen's language. No tab stop is added.
  - **Badges:** a badge's explanation is read with the card, as words only a screen reader reads; nothing changes on
    screen or in the Tab order, and the words are neither copied with a selection nor found by the browser's find. So is
    the short reason that stands where [Suggested edit] cannot go.
  - **Keyboard:** the keyboard's focus shows the box on a tablet with a keyboard too, an Esc before it shows cancels it,
    and the scroll a Tab makes to reach a control no longer takes its box away. In a sheet or menu ([More], help) the
    first Esc closes a control's box and the second the sheet.
  - The agent contract (`pins.md`, HTTP API) is unchanged.
- **A language pick takes effect at once** (#377). On the viewer's usual address (`/#doc=…`), picking a language in
  [더보기] stored the choice but left the screen in the old language until a manual reload. The same address was
  replaced, which browsers treat as a move within the page. The pick now reloads when the address would not change.
  The place, the other query values and the tab's draft stay.
- **An outline pick waits for its jump before it lets go** (#378). An item picked in the outline was let go once no
  scroll had been heard for 250 ms. Under load, or when a build landed during the jump, that happened before the page
  moved, and the section strip then named the other item at the same place. It now waits while the jump is on its way
  and checks the reading line where the jump ended. The handbook gains two notes on browser tests: reproduce a
  load-only race by fixing its order, and a test may end the CSS transitions its own action starts.

## 0.4.43 — 2026-11-02

### Changed

- **A suggested edit is checked for obvious errors before it goes in** ([ADR-0024](docs/adr/0024-suggested-edit-obvious-errors.md)).
  Agents used to apply a suggestion character for character, so a typo or a contradiction in the author's own text went
  into the manuscript as written, and review let it pass as the author's words.
  - **The check:** the agent now reads the suggestion against the lines around it for three things only: typos, broken
    sentences and logical contradictions.
  - **No error:** it goes in as written.
  - **A typo or broken sentence with one fix that keeps the meaning:** the agent fixes it minimally. It commits the
    suggestion as written first, then the fix, and lists each fix in the closing reply and the PR.
  - **More than one fix, or a fix that would change a claim, number, condition or what a citation supports:** the
    agent applies nothing. It replies with the passage, the problem and a minimal fix, and leaves the pin open.
  - **What stays:** the pin keeps the author's text as written. `changed` and `unknown` are still not applied. Style,
    taste and making a sentence shorter are not errors.
  - **Where it shows:** the `pins.md` guidance clause and legend entry, both skills, and the viewer's [제안 수정] switch
    and card badge explanations say this instead of "word for word".

### Internal

- **CI takes about 10 minutes instead of 42-44.** Each Python version's browser suite runs in five parts on their own
  runners. Each part gets whole test classes, balanced by measured seconds (`--shard i/n`,
  `tests/data/shard_seconds.json`, refreshed with `--shard-record`). A class the timings do not know is weighed by the
  mean, so it still runs. The required checks keep their names and fail unless every part passed. Release tags no longer
  run CI, because a tag's commit is the merge commit main already ran (#369, #374).
- **Cheaper slow browser tests, nothing weakened.** ManyCardsWhileThePdfScrolls built its 300 pins with each re-reading
  every earlier one (287-337 s → 62-80 s). Other tests repeated loads, typing, theme switches or real waits:
  - LinePolish and the seen holds use several pages at once, each wait keeping its own deadline. The handbook now
    describes when that is allowed.
  - The slow phone scroll waits one frame per 4 px step, as its docstring says, instead of two.
  - Four assignee tests stopped repeating loads and typing.
  - The contrast test makes one theme switch per state.

  Each change was proven by mutations that fail the old and the new test alike (#370-#373).

## 0.4.42 — 2026-11-02

### Changed

- **A comment says when it was written.** A card's first comment had no time at all, only a mouse hover, and a reply only
  `13시간 전`. The first comment now has a reply's head (avatar, name, time, `수정 <time>` once edited) on its own line over
  the note, which stands on the reply text's edge, on open and review cards alike. The author leaves the card's head; a folded
  compact card keeps the avatar there, and its preview starts with the short time. Comments, replies and state records say
  relative and absolute time together (`14시간 전 · 11-01 20:41`), the absolute alone from seven days on, with the year when it
  is not this year; the hover keeps the stored string. Archive rows and the verdict line read as before.
- **A card's thread is a timeline.** A line runs through the avatars from the first comment to the last entry, with no divider
  above the thread. State records have a coloured dot in the avatar's place, their time beside the name and what happened on
  the next line. A card with no thread has no line.
- **A long name keeps its time beside it.** A comment's, a reply's or a state record's name ends in an ellipsis on the head's
  line, so the list never scrolls sideways and the time stays in view; the whole name is its description. A name or a close's
  reference that reads like a UI word ('완료') stays as written in English, its description too.

### Added

- **The pin list has an order.** `[최신순 | 쪽순 | 번호순]` under the open pins' head orders the open and review sections:
  newest first with a line per day (the default), by page and line, or as before by number. The choice stays in this browser
  across documents, and Tab, focus, jumps and undo rows follow the order drawn: an undo row stands under its day's line where
  its card was, rows of two cards deleted in a row stand in their cards' order, and a day's line stays while the row of its
  only card does. `pins.md` and the HTTP API are unchanged.

## 0.4.41 — 2026-11-02

### Fixed

- **A band switch keeps the page being read where it stands (#356).** Widening a foldable to a desktop or narrowing it
  back moved the page read when the top of the PDF area or the reading line stood in the space between two pages: the
  re-fit lost how far above the page the spot was and put the page's top on the line, up to the height of that space
  off, and on the way back a touch window moved the page lines at the old band's narrowed width first, which left it up
  to 200 px off. The spot now keeps that distance, and the lines wait for the band to settle. The switch holds the page
  read within a pixel in both directions; a page above the reading line still moves by the change in the space, as the
  line under it becomes a one-row summary (12 px on a touch desktop). The agent contract is unchanged.
- **The keyboard's focus no longer falls to nothing when a message ends.** A [되돌리기] or [x] with the focus went with its
  message when the six seconds ended or [x] was pressed, and the next Tab started again from the top of the page. The focus
  now goes to the line of the chip's page or the reading page's line, else to the pages, as a press on an action already did.
  A focus moved elsewhere stays there. The agent contract is unchanged.
- **A manuscript that cites through BibTeX gets its comparison PDF.** The comparison's sandbox did not show
  `/etc/alternatives`, through which Debian and Ubuntu link `bibtex`, so every document with a bibliography ended in
  `compile_failed`. The comparison cache's version is new, so a pin's failed comparison, which a POST does not retry, is
  built again.
- **A folder that keeps past comparison PDFs gets its comparison PDF.** A build root past the snapshot's 256 MiB was refused
  with `size_limit`, though a manuscript's 350 MB of old PDFs are not what it builds from. Such a snapshot now keeps each
  PDF and picture that nothing names as a blank file of its size, which takes no disk, and is refused only if it is still
  past the limit. A file read after all ends in `compile_failed`, not in a wrong PDF. The limits and a folder within them
  are unchanged.
- **A far arrival at a figure no longer stops short when a line is fitted on the way (#357).** A line above the reading
  page that changed height in a fitting pass made the viewer write the pages' scroll to keep the reading page in place,
  and a write ends a smooth scroll where it stands: a jump to page 4 rested 3,200 px short until the settling picked it up.
  The pass now leaves a jump alone. The settling itself gave up on a correction stopped on its way, because its two seconds
  counted from the first rest and the stopped glide's guard lapses about as late: the figure stayed short by what remained.
  Each correction now counts them from its own rest. The agent contract is unchanged.
- **Every jump ends where it asked, with or without a figure.** A jump to a page with no figure, an outline entry's place
  or a card's [보기] had nothing to measure its place after the glide, so a line fitted on the way left the page up to 200
  px off. Every glide now settles as a figure's arrival does; anything the person does lets it go, a search hit or anything
  else a script shows lets it go too, and a scroll by anything else after the pages rested is left alone.
- **A commit pressed while another comparison builds gets its PDF.** A document builds one comparison at a time and opening
  the changes view starts the newest commit's, so pressing another commit meanwhile was answered busy, and the view stopped
  on '이 문서의 비교 PDF를 만드는 중입니다' for good. It now says it waits, and shows its own PDF when that one ends.
- **A drag along a line of text reads that line, and the '위치 불확실' badge stops crying wolf.** A drag a few points high, the
  way one strokes along a sentence, got no text: `pdftotext`'s crop takes a word only when its lower part lies inside the
  rectangle, so 8 pt over the top of a 9.3 pt word gave nothing. The source line was right, but the pin had no quote and a
  warning badge saying 0% of the drag matched. Every recent false badge on a real manuscript was this. Such a drag now reads
  the words it touches. A drag with nothing to weigh, a picture or words too common to name a place, has no score
  (`score: null` in the pick answer) and no badge, rather than 0%; pins saved so stay as they are and show none. Drags that
  had text are read as before.
- **A number no longer outvotes the words around it.** A number a `\ref` printed is in no line of the source, yet it was
  weighed as the rarest word of all, so '한계는 Section 5.5에' on its right line scored 34%; such a number is left out now.
  And where a printed number matched an unrelated one it outweighed every word, which took a drag whose line held all of its
  words to another paragraph; numbers now weigh together no more than the lightest word beside them, so they can still tell
  two rows of one label apart. A word the file does not hold still counts, as it may mean the drag is on another file.
- **A drag over a picture stays on the picture.** SyncTeX names a picture by its own `\includegraphics` line, but its words
  could match a sentence elsewhere, and the text path then took the pin to that sentence. There the text path no longer
  competes, and the match has no score, as those words tell nothing about the place.
- **One word of the title finds the title.** SyncTeX names the title block by `\end{frontmatter}`, and the text path wanted
  two words, so a drag on one word stayed there at 0%. Where SyncTeX names a line without text, a word on exactly one line of
  the file is now enough. On a line of text the 0% stays, as the drag may be on another file.
- **Moving a pin keeps the text it was moved to.** [위치 다시 잡기] did not send the new quote, so the pin lost it.
- **Each rung of the range has its own score.** SyncTeX names a table's cells by its `\end` line, so a drag on a table scored
  0% on that line though the table the pin shows holds every word. The paths still compete on their raw lines, the answer
  gives the default rung's score, and choosing another rung takes that rung's (`levels[].score`).

## 0.4.40 — 2026-11-01

### Fixed

- **A far move from the phone's navigation sheet lands after the keyboard was up (#346).** On a Chromium phone, with the
  sheet's outline filter used while the keyboard shrank the screen, the next far move from the page field (page 105 to
  page 80) stopped on page 102 or 103: the band the keyboard had held settled 200 ms into the glide, and its re-fit wrote
  the pages' scroll offset back to where it already was, which ends a smooth scroll in Chromium. A re-fit that leaves the
  reading spot's page where it stood, at the same height, no longer touches the scroll. The agent contract is unchanged.
- **A Hangul syllable still composing no longer costs the reason typed before it (#352).** A key save and Enter at once
  open the reason popover while the save is out. When the save landed while an input method was still composing a
  syllable in the field, the line gained the pressed word's context in front of the popover and the field was drawn
  again: it came back empty, and the syllable committed next was saved as the whole reason ('묶이는 이유' became '유').
  The field now stays the same element whatever comes or goes before it, so its text, focus, caret and composition carry
  on. A field drawn anew while a syllable composes (a new build with another page count builds the pages again) holds
  the text typed so far instead of starting empty.
- **A new build that builds the pages again keeps the focus in an open reason (#352).** The focus fell to nothing with
  the old popover: the text typed on was lost and a digit saved a verdict. It now comes back to the field drawn again,
  with its selection, or to the popover's button that had it - also when the new pages move the lines between the side
  panel and under the pages. A focus elsewhere stays where it is; a popover not drawn again leaves the digits typed on
  no verdict keys.
- **Nothing moves or rebuilds a reason field while a syllable composes in it (#352).** Crossing the side panel's bar
  (a wider window: 1440 to 1920) moved the lines while '유' was still composing; the field moved was a new one, the
  composition ended with the old one, and the input method's commit landed on top of the text carried over: '묶이는 이유'
  was saved as '묶이는 이유유123'. A new build with another page count did the same on a foldable or a tablet. The lines
  now stay where they are until the syllable ends and then move, and such a build waits to build the pages again until
  then; a newer build that arrives meanwhile wins, and the waiting one is dropped rather than put back over it. A
  failed verdict save while a syllable composes closes the popover as before, keeping the text with the
  syllable once as the page's draft.
- **A new build keeps the reading page while it builds the pages again (#352).** Read from the new column before the
  summaries under the pages above were back, the reading page was the next one: a reason being typed in the side panel
  was moved on from - written and closed - and the focus fell to nothing (the digits typed on could save verdicts).
- **Test only:** a save that fails while the text is still being typed closes the popover with what was typed by then,
  as before; the RcRound2 test whose failure could arrive mid-text under load now holds the save until the text is in.

The agent contract is unchanged.
- **A page verdict on a figure page saves where a large element covers the page.** The line's whole-page pick chooses an
  element that covers 40% of the page or more, so on such pages (the concept figures' pages 1 and 17) it answered with
  that element instead of the figure, and [채택] or a digit key said '이 그림은 쪽 판정을 받지 못합니다' and saved nothing.
  The line now saves the verdict of the element's figure over the whole page, as the composer's verdict does. A pick that
  names no element still saves nothing. The API and the agent contract are unchanged.

## 0.4.39 — 2026-11-01

### Changed

- **A figure page is arrived at by its figure (#345 item 2).** On a figure document page whose map names its figure body
  (the element `<figure>/@figure`), the outline, a page field, the page list and a card's [보기] now put the figure's top
  edge under the PDF area's top, keeping up to 24 pt above it for the figure's label line, instead of the page's top:
  the page's head and text box no longer push the figure below the first screen (at 1440 x 900 the whole figure showed on
  26 of 88 pages of a 1.6.0 gallery, now on all 88). The same entry again while the pages rest on the figure goes to the
  page's top, and once more back to the figure. It lands there once the pages rest, even when the layout above moves
  on the way (a save's list reload, scroll anchoring after a stall); a person's own scroll is left alone. The reading
  line falls inside the figure, so the section strip, the page count, the keys 1-5 and the verdict panel name the
  arrived page. Pages without a figure body, and every LaTeX or view-only page, arrive at their top as before. `GET /api/meta` adds `figure_top` and `figure_above` to such a page's
  facts; the agent contract is otherwise unchanged.

### Fixed

- **The page's end scrolls clear of an open reason (#345 item 1).** The reason popover stands above its page line, so at
  a page's end it covered the page's last lines - a figure's caption - and no scroll uncovered them: the line and the
  popover came up with the page. While the popover is open, the line and the popover now stay where they are as the
  pages scroll on, until the page's end has come up from under them by what they covered, then go on with the page.
  Opening and closing it moves nothing, no page moves in the flow and nothing scrolls by itself; held lower than its
  place, the line floats over the gap, and while it lies over the next page's head it has an edge and a shadow under it
  as over it, so it does not read as part of that page. The side panel's popover, beside the page, is unchanged. The
  agent contract is unchanged.
- **Opening or closing a reason no longer scrolls the pages (#345, also in 0.4.38).** Each drawing of the page lines
  measures every line in the document as the reading line for a moment, and the lines above the reading page that it
  does not hold grew and shrank back; the PDF area's scroll anchoring kept part of that. With the pin panel closed on a
  1440 figure document, the pages went 46px down when a reason opened (by Enter or a click) and again when it closed,
  and 39px on a phone when it opened. The measure now never anchors the scroll at any zoom, as it already did while
  pinch-zoomed.

## 0.4.38 — 2026-10-31

### Fixed

- **An undo whose request does not answer says so (#334).** A message's [되돌리기] or [되살리기] that sends a request -
  the status line's undo of a key-saved verdict (its drop) or of a taken-back one (its restore), and every other such
  undo: a save's or an append's chip, a done or deleted card's row, a deleted pin's [되살리기] - kept saying what it had
  done (`#N 채택 판정 저장됨 … 되돌리기`) for as long as the answer took. Past 8 seconds, the bound a page line's take-back
  already has, the message now says `되돌리기의 답이 늦습니다` (`Undo: no answer yet`; `되살리기의 답이 늦습니다`, `Restore:
  no answer yet`) before what it undoes, as one text whose end a narrow line cuts (`되돌리기의 답이 늦습니다 · #12 채택…`),
  so the target stays readable and the line keeps its width: on the status line the message itself does, as a warning
  and first on the line - also while the focus on its busy button holds the line - and for an undo elsewhere the status
  line says it in one message of its own. The late answer, a success or a failure, is taken once and the lateness goes
  with it. A focus the person has moved meanwhile stays where it is - a save's undo answered late, or its failure's
  [다시 시도], then brings the composer back without taking the focus into the note - and one left alone goes to the
  reading page's line as with an answer in time. Nothing was locked, so nothing else changes.
- **The Trash keeps the keyboard focus and says a late restore (#336).** A row's [되살리기] pressed by key took its row
  away with the answer and left the focus on nothing (also in 0.4.37), so Tab and Esc started again from the page's top.
  A redraw of the Trash now puts the focus on the next row's [되살리기], else the one before's, else [닫기] - back on the
  row's own when the restore failed - unless the person moved it out of the list meanwhile. The row's restore also has
  the 8-second bound: past it the Trash (or, closed, the list) says `되살리기의 답이 늦습니다 · 핀 #N` until the answer.
  Tab no longer leaves the open Trash (Tab from [닫기] after the last restore left the focus on nothing), and a row's
  [되살리기] or [영구 삭제] shows its description beside the row's buttons instead of over the row before it; a description
  showing when a banner pushes the list down (or the list is drawn again) goes rather than stay over another row.
- **A key save on a phone no longer moves the pages in WebKit.** Fitting the page lines measures each as the reading line,
  which grew a line above the reading page for the length of the pass; WebKit's scroll anchoring followed the growth and
  not the shrink, and the pages moved 39px. The measured lines' page blocks now keep their size during the pass. Letting
  them go keeps the page under the reading line where it stood: a window narrowed past the panel's bar and widened again
  right after a save no longer moves the reading page.
- **The page verdict panel, polished (#335 items 1, 2, 4, and pages of mixed widths).** A page that takes no verdict
  names itself in one form - its page on the name's row, the map's whole title under it - whether it is a list page or a
  comparison board. A far jump (the outline, the page list, a card's [보기]) fills the panel once where it lands instead
  of for every page passed, and a card's [보기] flashes the panel when it shows that page. The pressed word in the panel
  no longer shows a description box over the page's name - a long press shows it, and its context under the panel stands
  after a press and on the keyboard's focus, not on a hover - and every other description in the panel stands left of it,
  over neither the name nor a control, with an edge over the page. The widest page now
  decides the room beside the pages, so a document whose pages differ in width keeps every page on one axis beside the
  panel, never under it, and scrolling never turns the panel on or off. A panel tall enough to scroll inside brings the
  control the keyboard focuses whole into view with its focus ring, and ends above the cards that float at the PDF area's
  bottom right while the pin panel is closed. When the line moves between the panel and under its page, a control that had
  the focus on it has the focus on the moved line too, not the PDF area. The agent contract is unchanged.
- **A reason moved to a newer verdict lands on one verdict even when the earlier verdict's write is still on its way
  (#327).** A reason write whose answer was lost may still reach the server later. When the draft had moved to a newer
  verdict, a read of the earlier one found its rev unchanged, the copy was written on the new verdict, and the old request
  then landed too: the reason was on both. Before the copy is written, the viewer now fences such a write off with the
  edit contract as it is: the earlier verdict's note written back unchanged against the rev that write was sent against.
  Accepted, the rev moves on and the old request is refused (409) when it arrives; refused, something landed first and
  the pin in the answer is judged again (the old write found there leaves the copy). A fence without an answer writes
  nothing and keeps the draft, with [다시 시도]. The earlier verdict's pin gets an `edited_at` (`수정됨` in `pins.md`) with
  its note unchanged. A draft moved when a write that was out at the verdict change lost its answer carries that write
  along, so its copy is fenced the same way. A copy's own write that loses its answer now takes the earlier verdict's
  failure and its [다시 시도] away: pressed, it wrote the reason there while the copy's request could still land.
- **Undo keeps where a moved reason came from (#327).** An edit inside the part of a draft moved off an earlier verdict
  lets the part go; Ctrl+Z (or a paste taken back, an input method's composition given up) brought the text back without
  it, so the earlier verdict's [다시 시도] landing no longer took it out of the copy, which was written twice. A text the
  field held before now comes back with the parts it had then, redo included, however much was typed meanwhile; a part
  brought back after its text landed on the earlier verdict leaves at once, as it would have had it been there. No
  server or agent contract change.
- **Going up, the outline shows the section the current row is in (#335).** Reading back, the current row came to rest
  48px - a row and a half - under the filter, so from a section's second entry on its head (`비교판 · 14`) was out of
  sight. The list now keeps two whole rows over the row on the way up, and where the row's section fits in the panel
  with it, its head and the two rows above that: the list moves once as the reading comes up into a section and not
  again until it reaches the head; near the outline's top it goes to the very top only while the row keeps its margin
  there, so on the tablet sheet it never lands under the folded sheet's bar. Only where it lands changes: whether it moves is still the 48px margin's, so a row
  already clear stays put and two neighbouring rows cannot send a low panel back and forth. Going down nothing changes;
  the pages and the focus never move.
- **The phone's navigation sheet opens at the current section, and its top stays put (#335).** The sheet kept the current
  document's row (or the view's) under its head and so stopped at the top of a long outline, the current section
  thousands of px below. Now the open sheet is a column: the head with the search, the documents, the view and the page
  field keep their place, and the page list and the outline's rows share the height left, each showing whole rows around
  its current one in a box exactly as tall - five page rows while the outline has three, then fewer, down to the current
  page's, then one outline row, then no page list - so no row is cut at a list's edge, under the outline's filter or at the
  foot, and the sheet itself does not scroll. Its top stands at one height on any page and while a filter shows fewer
  results or none; emptying the filter brings the current section back, and the keyboard coming or going fits it again. Only where
  not even one outline row fits (many documents on a tiny screen) does the sheet scroll, by whole parts, with the current
  document's row (with one document, the view) pinned under the head. The pages do not move and the focus stays where it
  was.
- **The tablet sheet's outline overlay brings the current row above the bottom bar (#335).** On an upright tablet or an
  unfolded foldable (882x1104) the overlay runs to the screen's bottom under the collapsed sheet and the status line on
  it, and it opened and followed with the current row under them, out of sight and out of reach. The follow now counts
  what they cover as out of view, and the overlay's foot is padded by their height so the list's last rows come up too.
  The bars and the overlay stay where they are.
- **A far jump reaches its page in WebKit (#343).** A jump to a page (the page field, the phone's position sheet, the
  outline, a card's [보기]) glides there; WebKit ended the glide at the scroll anchoring adjustment that came with the lines
  drawn again as pages passed under the reading line, so on a phone a jump to page 105 of a 105-page figure document
  rested at page 89. The PDF area no longer anchors its scroll while a jump glides.

## 0.4.37 — 2026-10-31

On a wide desktop the page verdict line becomes one panel beside the pages, with a one-row summary under each page, and
keys pressed around a save or a reason land on the verdict they show. The outline panel keeps the current section in
view as the reading moves, with its filter in reach at the top. The agent contract is unchanged.

### Added

- **The page verdict line beside the pages on a wide desktop (#329).** Where the PDF area leaves room right of the pages
  (its inner width less the page's is 360px or more; back under the pages below 328px), the page verdict line is one
  panel in that margin - the reading page's line, the page the section strip and the keys name - with the page's name,
  its words, its state, the reason, [판정 취소], the earlier verdicts' link and the save chip in rows down it, and under
  each page a one-row summary (`6쪽 · PL17 · 판정 #7 채택 · 처리 대기`, the reading page's in bold) that brings its page to
  the panel. The words stand at one place on the screen for every page; the page stays centred while the margin holds
  the panel and moves left only by what it lacks. Keys 1-5, Enter and Esc act as on the reading line; Tab from the
  pages goes to the panel, Shift+Tab from its first control goes back where it came from, and Tab from its last goes to
  the pin panel; PageDown, the arrows, Home, End and the wheel on the panel move the pages. A kept reason draft on another
  page shows on that page's summary. When the room crosses its bar the page in view, a save chip and an open reason - its
  text, caret, focus, and a save or a write it waits for - carry over, and nothing is written. 1920 takes it with the pin
  panel open, 1680 with it closed; narrower windows, a zoom past the bar, the unfolded foldable and phones keep the line
  under each page as before.

### Fixed

- **The outline panel keeps the current section in view (#330).** The panel marked the current section but never scrolled
  to it, so in a long outline (a figure document lists every figure, under its status and again under the manuscript
  figure that holds it) the mark sat out of sight. The current row now keeps 48px from the panel's edges: when the mark
  moves to a row inside that margin or out of view the list moves just enough, gliding unless reduced motion is asked for or
  the way is longer than the panel is high, where it jumps. A row clear of the margin moves nothing, the panel starts at the
  current row when it opens, and only the panel moves - the pages, the window
  and the focus stay where they are. The list stays where the person has it while the mouse is over it, while its width
  grip is dragged, for 3 seconds after a wheel, press, touch or key in it or on the grip, while the keyboard is on a row,
  and while the filter has text; a move of the mark meanwhile is caught up when they let go. The filter and its hint now
  stay at the top of the panel, with the rows passing under them, so a panel opened at a row far down keeps its filter in
  reach; the margin counts from under them. The overlay of the mid bands is the same panel and does the same. The phone's
  navigation sheet keeps its own rule.
- **Enter while a digit's save is out is the reason, wherever the focus rests on the line.** On a word it pressed that word:
  a second verdict over the one being saved. `Enter 이유 쓰기` and [이유 추가] on a line whose save is out wait for the new
  verdict: before the list was read again, the reason went on the verdict it replaced.
- **The reason field keeps the focus while its write is out.** Disabled, it dropped the focus to nothing, and the next
  digit was a verdict key. It waits read-only; a failure leaves the text and the focus there.
- **Restoring a take-back leaves the reason being written on another page alone.** It wrote that page's half text and
  closed its field. The restored verdict's draft stays its own, marked on its line.
- **The reading line is exact at a page's end.** Within its last pixel the strip and the keys already named the next page.
- **A jump is a jump from its first frame.** Every smooth jump of the pages (the page list, an outline entry, a card's [보기])
  counts from before its first scroll event, also right after a wheel; a digit there acted on the page being left.
- **A save chip's or the status line's [되돌리기] pressed by key leaves the focus on the line,** a press with a reason being
  typed leaves it in the field, and a digit on a take-back's [되돌리기] leaves it on the word being saved, not on nothing.
- **While a digit's take-back is out the focus stays on its line and Enter and Space wait.** The line shows the verdict before
  it meanwhile, and Enter opened a reason for that one or took it back too. A guard on the digits after a field went
  ends when the reading page changes.

## 0.4.36 — 2026-10-30

Follow-ups to the reviews of 0.4.35, nearly all on the page verdict line: a long press, a tap while the reason is
typed and a save in a pinch-zoomed view do what they show on a phone, a phone's floating line keeps its rows, and the
status line's `+N` list reads there; Tab from a page without a line keeps the pages where they are, a line saved by a
key keeps its rows and the earlier link is short and never cut; a reason draft moved more than once ends on one verdict.
The lines far from the view are left for the browser to skip, so the first scroll through a long figure document no
longer stalls. The agent contract is unchanged.

### Changed

- **The earlier verdicts' link is short and never cut.** A page verdict line's link to the open verdicts a newer one
  replaced reads `이전 2건` (`+2 earlier`), and on a line that is short of room on the wide band its count alone, `+2`;
  its accessible name and its tooltip still say `이전 판정 2건 · 새 판정으로 대체됨` in full. The whole words were cut to
  fit: on a 620px English line (1280 x 800, panel open, three-digit pin numbers) the link read `1 ea…`, and kept at 5em
  that line stacked. On a row a dot sets it off from the state before it (a bare `+2` after [판정 취소] or a button's
  key digit read as that button's count), and the count's press area is 24 x 32px; a stacked line (a phone) has no dot. Where not even the count fits beside the rest, the link steps out rather than stack the
  line. Whenever fitting a line hides its earlier link - stepped out, or beside `Enter 이유 쓰기` on a row that a resize or
  a zoom made tight - a focus on it moves to the control before it on the line instead of being lost (#322).

### Fixed

- **A reason draft moved more than once still ends on one verdict (#317).** A draft that moved off a verdict whose reason
  write could still land there (a write out, its [다시 시도], a write whose answer was lost) remembered only the last key
  it moved off: moved again (`a → 쪽 → b`, `a → b → c`), a write that then landed on a left the copy, which was written
  on the newer verdict too. It now remembers every verdict it moved off, as the place of the moved text in the draft -
  followed through every edit - with that verdict's lost writes. A write of that text on one of them takes that place
  out of the copy with the line break that set it apart, keeping lines typed around it, a draft joined to it and the same
  sentence typed again; trailing spaces or a CRLF no longer hide it. Text typed next to the moved sentence on its line
  (at either end) makes it a new sentence, written whole on the newer verdict, where only the fragment used to be. A popover open on the copy follows: with nothing left
  it closes, the status line says the reason was saved on the earlier verdict, and the line's reason control takes the
  focus with the next digit not taken as a verdict key - also when its Enter was waiting; with something left it keeps
  that and says the rest went. Before the copy is written, a write out on the earlier verdict answers first and a write
  there that lost its answer is settled from the pin's rev - also after the draft moved on or the page was reloaded;
  landed, nothing is written twice; when the pin cannot be read nothing is written, the draft stays and the status line
  says the save failed, with [다시 시도]. The other order holds too: once the copy is written the earlier verdict's
  failure and its [다시 시도] go, and that [다시 시도] pressed while the copy's write is out waits for it. A folded or
  kept change of a saved reason that moves to a new verdict takes only the person's own text, as an open one did, not
  the lines others added under it.
- **A long press on a page verdict line is the same press whatever the line holds** (#320). While a save chip stood on
  the line or its reason popover was open, the line's words, [판정 취소] and earlier link were drawn without their
  description (no box over the chip or the popover), and so was a confirm word waiting for its second press; a long press
  then found no description, nothing swallowed its release, and the click took the pressed word's verdict back - or saved
  the armed word. They now keep the description for a long press only (`data-tip-press`): hover and focus still raise no
  box, a long press shows it and its release presses nothing, and it does not let an armed word go either. While that
  description is up, the line's own context over the words ('지금 채택 판정 · 다시 누르면 판정 취소'), which says the same,
  steps aside.
- **Descriptions wrap Korean between words** (`#tip{word-break:keep-all}`): '판정 취소)' broke as '판정 취/소)'. A token
  wider than the box still breaks inside it.
- **A tap on a word while the reason is typed takes the first tap** (#320). On a phone the reason field folds the line's
  figure name; the tap's focus brought it back before the click, the words moved 22px down under the finger and the click
  fell on the line. The fold now holds until a press on the line has been handled, as it already did for the popover's
  own buttons.
- **Saving a verdict in a pinch-zoomed view leaves the view where it is** (#320). Every drawing of the lines measures
  them as the reading line (`#doc.pv-measure`), which grows the lines above the reading page and shrinks them back;
  Chromium carried the scroll anchoring of that shrink into the zoomed view, which jumped to the top (422 -> 0 at 2x).
  While the page is zoomed the PDF area no longer anchors during that measure.
- **The status line's `+N` list reads and stays in view on a phone zoomed in** (#322 item 5). Held inside the 2x view
  (179px), a row's [되돌리기] and [x] left its text no width: one character a line, 685-806px a row, and the list - at
  least a row tall - ran 418-639px above the window, the focus on its first row pulling the zoomed view after it. A row's
  buttons now go under its text when the text would get less than 6em, and the list is never taller than the visible
  part nor past it.
- **Tab from the PDF area on a page without a line keeps the pages where they are.** When the reading page takes no
  verdict (a figure document's list pages) or its line has no control to stop on, Tab from the PDF area - or from
  nothing after a press on a page - goes to the next stop in the pages only while it shows whole in the area's view
  with nothing over any of it (the next page's line on a small zoom; Shift+Tab from there leaves the way it came in),
  else past the pages (the panel's grip, the status line's action). It went to the first line after the pages' start
  and scrolled there: from page 1 of a 91-page figure document to page 4, also on first open, since 0.4.34. So does the
  first Tab with nothing focused where no stop is drawn before the pages (a phone, just opened: page 4's line, scrolled
  0 to 2067px). Tab into the pages from the outline or the section strip, and Shift+Tab back out, are unchanged (#322).
- **A phone's floating line keeps its rows.** A floating line on a phone holds [판정 취소] back unseen but keeps its
  place, so the line is as tall floating as in its place. Taken out of the row, it let the short earlier link rise into
  it: a line with a reason and an earlier verdict was 131px floating and 191px in place, and the next page jumped 60px
  under the finger as the line crossed its page's end (#322).
- **A line saved by a key keeps its rows whichever page is read.** Such a line says `Enter 이유 쓰기` (`Enter reason`)
  while it is read and [이유 추가] at rest - 40px narrower in Korean, 15px in English, with the earlier link beside it on
  a tight row. It was fitted on the look it showed, so near its threshold it stacked, or its stacked state took a second
  row (91 to 123px), only while it was read, or only at rest. It is now fitted at the wider of the two looks and states,
  as the hidden identifier and key digits are (#322).
- **The first scroll through a long figure document no longer stalls on its page verdict lines** (#322, item 4). Each
  page PDF.js draws for the first time adds its embedded fonts to `document.fonts`, and every font added makes the
  browser lay out all the text in the page again. Since 0.4.35 skips the far pin cards (#305), what was left was the
  pages' verdict lines: on the 91-page figure document (`pl`, 200 pins, panel open, 1400 x 850, a wheel scroll from the
  top to the end) the 88 lines were 4,300 of the 7,378 objects laid out after each font, and the scroll had 3-9 long tasks
  (0.16-0.51 s; 8-9 on a busier machine). A line more than a view's height above or below what the PDF area shows is now
  left for the browser to skip (`content-visibility: auto`): 3,243 objects per font, no long task in three runs, frame
  p95 33 -> 17 ms. Nothing looks or moves differently. A skipped line stands at the height it is drawn at, and every line
  is still measured drawn - as the reading line - whenever what it shows or its width changes, so no line's rows or
  height and no page's place change, and nothing scrolls to make up for one. The reading line (which floats), a line in
  or near the view and a line holding the focus, its reason popover or a save chip are never skipped (skipping contains
  a line, which snaps its parts to whole pixels and clips what reaches past it). The outline is not skipped: its rows
  share one grid's columns, which a skipped row would leave.

## 0.4.35 — 2026-10-30

Follow-ups to the reviews of 0.4.34, nearly all on the page verdict line: Shift+Tab leaves the reading line the way
Tab came in and the PDF area has a name; English lines stay one row on a desktop and every English take-back says
`Retract`; a resting stacked line names its page; a reason is judged saved by the pin's rev, not by its text, ends on
one verdict and survives a failed take-back; the status line's `+N` list opens where its rows can be pressed, and a
touch screen no longer names verdict keys. Scrolling the PDF with hundreds of pins in the open panel no longer stalls.
The agent contract is unchanged: `superseded_by` compares anchors as JSON values, as the viewer now does too; the
server writes integer anchor offsets, and those read as before.

### Changed

- **A resting stacked line names its page.** A page verdict line that stacks (a phone, a folded cover, a page at a small
  zoom) and is not the reading line now shows its identifier (`6쪽 · PL17`) in the row the reading line's name takes, in
  the line's muted text at weight 400; the reading line still names its figure in full, the foreground at 600. The row
  was kept empty since 0.4.34 so that the reading page never changes a line's height, and on a 390px phone it left
  about 44px between a page and the state under it - the line looked loose, as far from its page as from the next. The
  row's height, the line's height and its words' places are unchanged whichever page is read (#308).
- **English: `Retract` for 판정 취소, `Enter reason` after a key save.** The line's take-back reads `Retract` (was
  `Cancel verdict`), with the same verb in its description, its name, the pressed word's hint and the status line
  (`Verdict #17 채택 retracted · …`), and every English take-back wording says retract (the keys' help, the save's undo,
  the card's [Erase], `Undo — retracted verdict #17`, `… was retracted elsewhere`); after a digit-key save the way to the
  reason reads `Enter reason` (was
  `Enter write a reason`). Both are the line's own words, sized for one row beside the words on a 620px line.

### Fixed

- **`superseded_by` compares two verdicts' anchors as JSON values** (#303). Two closed verdict pins on the same lines
  count together only when they share one `anchor`. The server compared an offset hand-edited into a list or an object
  by its printed form, so the list `[0]` and the string `"[0]"` were one anchor to it (and so were `true` and `1`) - a
  false `superseded_by` the viewer's card did not show - and one object written with its keys in another order was two,
  to the viewer as well. The server and the viewer's verdict order now both compare offsets as JSON values: an object's
  keys in any order, never a value of another type, and a number as the double the viewer reads it as - `1` and `1.0`,
  `2^53` and `2^53+1`, `10^21` and `1e21` are one number, and one no double holds (`1e400`) is `null`.
- **Shift+Tab leaves the reading page's line the way Tab came in** (#306). From the reading page's first stop - its
  line's first control, or the badge of the first pin marked on that page, which Shift+Tab from the line passes first -
  it goes back to where the focus came into the pages: the stop a Tab into them was pressed on, or the outline entry or
  document tab a digit key was pressed on; otherwise (a card, which is after the pages, or a stop no longer shown) to
  the stop right before them, the section strip's page button. A phone draws nothing before the pages: there it goes
  back to a tool-bar origin, else to the position button (`#btn-pos`). An origin is forgotten when the document or its
  build changes. The pages do not move. It went to the page before's line and scrolled the document a page up; 80
  presses on a 91-page figure document never reached the outline. The earlier pages' lines are reached by PageUp;
  Enter on the line's `#N` still goes back to a card.
- **The PDF area is a named region** (`role="region"`, `PDF 쪽` / `PDF pages`, #307). A digit key pressed outside the
  pages puts the focus on it while the save is out, so that Enter opens the reason; with no role and no name a screen
  reader started reading every page's text run together (`1 1쪽 2 2쪽 …`). Every other path that leaves the focus on the
  PDF area (Esc in the reason field, a search closed, the reading page moving away from a focused line) says the
  same name.
- **A digit during an outline jump's glide no longer saves on a page passed.** ↓ in the outline's filter or on its
  list counted as the person scrolling the pages and turned the glide guard off, so `PL83` from page 60, ↓, Enter and 2
  saved 보류 on page 71 while the view landed on page 85. A scrolling key counts only where it scrolls the pages: on the
  PDF area, a control in it or nothing, not in a text field and not Space on a button.
- **Alt+digit with the focus in the pages keeps it on the PDF area.** The new document's pages took the focused element
  away, the focus fell to nothing, and the next Tab went to the first page's line and scrolled there.
- **A Tab outside the pages no longer reads every control of every line** (#308, item 3). Only a Tab across the pages'
  edge is taken - from the last stop before the PDF area, or by Shift+Tab from the first after it - and that stop is
  found by walking out from the area, past parts that are not drawn. Each Tab outside the pages read all focusable
  elements of the document and their boxes (678 on 91 pages, about 1.3 ms a press; now about 0.04 ms). Tab from the
  section strip also goes to the reading line when page 1 has a pin mark before its line.
- **English lines stay one row on a desktop.** At 1280 x 900 with the panel open (a 620px line) a third of the 88
  resting lines of a 91-page figure document stacked into three rows, and a digit-key save stacked the rest. A line now
  stacks before any press only when the row the press brings does not fit, summed from what is measured: the words as
  drawn, plus the check a press puts on a word (21px) where none is pressed yet; the identifier and the dot after it;
  the fresh verdict's state (`pvStateNeed`: the wider of the state after a click and, on a mouse screen, after a key
  save with `Enter 이유 쓰기`, the pin number drawn with the next pin's digits, plus one gap for a save's words); and the
  row's gaps. The 8px and 24px allowances it replaces counted the dot (3px) as 8px and the check as nothing, so a line
  within 21px of the bar also stacked under its first press, in Korean too; measured on the click state alone, a line at
  the bar stacked right after a key save. While a save is out its words (`· 보류 저장 중…`) give way down to nothing,
  with the reason, and the earlier link steps out: the line's rows are held then, and at their 6em the words of a second
  save pushed `판정 취소` past the row's end, where it was clipped. English at 1280, 1366, 1400 (the test default), 1440, 1536 and 1920 with the panel open: no line stacks;
  Korean: none, as before.
- **A line with an earlier verdict keeps its rows whichever page is read.** `이유 추가` shows only on the reading line and
  the last save's, so a line with the person's own open verdict, no reason and an earlier verdict's link stacked near
  its bar only while it was read, and a stacked one grew a row (91 -> 123px at 420px) - breaking 0.4.34's rule that the
  reading page never changes a line's height. Such a line now holds that `이유 추가` hidden (never shown, focused or read
  aloud), and the fit lays it out unseen, as it does the identifier and the key digits; a stacked line keeps the reading
  line's state height as its least (`--pv-t-h`), its state rows at the top under the identifier and the room kept below.
- **No description box over the pressed word's description after a key save.** The focus a digit-key save moves to
  `Enter 이유 쓰기` no longer raises that control's description box; on a one-row English line at 1280 it overlapped the
  pressed word's description (`Current verdict: … press again to retract it`) by 39px. A focus the person moves raises
  it as before.
- **A retried reason is judged by the pin's rev, not by its text (#299).** A reason write whose answer was lost was taken
  as saved when the note already held the same text, so a write that never reached the server reported a repeated
  reason as saved without adding it, and a corrected draft could replace someone else's identical text. Every new reason
  is now sent against the rev it read (`base_rev`, a `note_append` too), so it can only land as the change right after
  that rev; a lost write is kept with that rev and the note it would have made. The next write reads the pin: the same
  rev means it never landed and it is sent again; a later rev means it landed only when the note is exactly what it made
  (later lines under it allowed) and, when that was the only change since, the change was this person's (`edited_by`).
  A 409 rebuilds the write from the pin it brings, up to three times. The lost writes are kept with the draft too, so a
  folded, reopened or reloaded draft still knows them, and a line added under the reason after a CRLF counts like one
  after an LF. No API change.
- **A failed take-back no longer drops the reason it took away (#299).** When [판정 취소] (or pressing the pressed word)
  failed after something took the reason popover's place - another popover, another document or visit, a newer verdict
  saved on the line meanwhile - the typed reason came back nowhere, and with a newer verdict on its line it could not be
  reached at all. It is now kept as a draft its line marks ('초안 있음'): the verdict's own when it is current again, else
  the page's, which goes to the verdict it is opened on - decided once that verdict's own reason write and a newer save
  on its line (one whose popover still waits for its number included) have answered, and a page's copy that the old
  verdict's [다시 시도] then writes goes with it. The status line says so after the failure, with [보기], which
  brings that line into view with the focus on the mark. A newer popover keeps its text and the focus, also on the same
  line, where the focus used to go to the line and the next digit was a verdict key.
- **A reason ends on one verdict when the line's verdict changes while its write is out.** The draft no longer moves to
  the new verdict before that write answers: written, or found landed after a lost answer or a 5xx, it stays on the
  earlier verdict and the status line says so; not landed, it moves to the new verdict and the earlier verdict's
  [다시 시도] goes. Three of four orders put the reason on both verdicts. A changed saved reason that follows the new
  verdict moves only the person's own text, not the lines others added under it.
- **A verdict restored under a newer one gives its draft to the line**, as the page's draft with a status-line word, and a
  reload does the same for any draft on a verdict that is not the line's current one - so the reload's '줄의 [초안 있음]이
  엽니다' is true and leaving asks first.
- **One's own landed change of a saved reason is not a conflict.** A change whose answer was lost but whose write landed
  is taken as the note it changes; it is not shown back as a note changed elsewhere.
- **A verdict written before a 500 is the line's verdict.** A 5xx on the save is checked against the list like a lost
  answer, so the next press does not make a second verdict.
- **How a phone's floating line takes a verdict back is documented (#299).** It holds [판정 취소] back for its height;
  its pressed word does the same (since 0.4.34) and says so - over the words for four seconds after the press, and in
  its long-press description - and its [되돌리기] comes on the line. A test holds it at 390x844.
- **The status line's `+N` list opens where its rows can be pressed.** It always opened over the line, and on a desktop
  the line sits under the status chips, about 114px from the top: four stacked messages put the list's top at -76px at
  1400 x 850, its first two rows and their [되돌리기] above the window. The list now opens over the line where the whole
  list fits there (under it in the short band's top row, as before), else on the other side where it fits, else on the
  side with more room, cut to it with its rows scrolling inside. The room is counted in the part of the window a person
  sees (a keyboard that does not resize the layout, a pinch zoom), and the list is placed again while it is open when
  its rows change (a list opened over the line with two rows kept scrolling in that room as more came) or the window or
  its visible part changes. On a desktop the list now stands under the line's own buttons - its right edge follows the
  line's and it reaches left - where it floated centred in the window, about 350px left of the line. Zoomed in, the list
  is held inside the visible part across too, and it is placed before it is shown, so opening it no longer moves the
  view to where its first row stood (a phone zoomed in on the line lost the line from view). Desktop 1400 x 850, an unfolded foldable 882 x 1104 and a phone 390 x 844 (sheet folded or
  open): every row's action is on screen and takes a press (#314).
- **Folding the `+N` list gives the focus back to `+N`.** A message that came while the list was open drew the line
  and its `+N` again, so Esc (or an outside press) left the focus on the page and the next Tab started from the top. It
  now goes to the line's `+N`, else to the line's first control; a focus a row's action put elsewhere stays.
- **No `단축키 1` on a touch screen.** A page verdict word's description ended in `· 단축키 1` (`· 단축키 3 (두 번)`
  for a confirm word) on every screen, so a long press on a phone named a key it has none of. The key is now said - in
  the description and as `aria-keyshortcuts` - only where its mark is drawn after the word, a mouse screen
  (`(hover:hover) and (pointer:fine)`, the condition of the mark's CSS); the lines are drawn again when that changes.
  Touch screens keep the description without the key; the desktop is unchanged (#315).
- **Scrolling the PDF with hundreds of pins in the open panel no longer stalls** (#305). Each page PDF.js draws for the
  first time adds its embedded fonts to `document.fonts`, and every font added makes the browser lay out all the text in
  the page again - every card in the open panel with it. On a 91-page figure document (`pl`) with 127 pins the first wheel
  scroll had 77-84 long tasks (4.4-4.9 s); with the panel folded, none. Cards more than a view's height above or below the
  list's view are now left for the browser to skip (`content-visibility: auto`), so a font added lays out the cards near
  the view only. With 200 pins on the same document (1400 x 850, the same wheel scroll from the top to the end) the long
  tasks went from 106-120 (7.2-8.3 s) to 8-9 (0.4-0.5 s), frames over 50 ms from 78-92 to 2-4, and the layout after a
  font from 19,674 laid-out objects to 7,403; what is left is the pages' verdict lines and the outline.
  Nothing looks different. A card in view or near it is never skipped (skipping contains a card, which snaps its text to
  whole pixels and clips focus rings and touch targets), and a skipped card's markup is always current. It stands at the
  height it had when it went; every card is drawn once more and sorted again when the list's width changes, when it is
  shown (the panel or the sheet opened) and when a slice of the list's font arrives, so the list does not move under a
  person scrolled down it and a jump to a card is aimed by real heights. A redraw also puts a card in view back where it
  stood, as the browser's scroll anchoring would - the first one still in its section, so a top card whose pin a poll
  moved to 검토 대기 or deleted hands over to the next instead of dragging the view after it - and a card above that
  someone else made longer no longer pushes the list. The card being edited or holding the reply box is never skipped. A browser test bounds the
  layout per font added with 300 pins by a count from a Chrome trace, not a duration.

## 0.4.34 — 2026-10-30

The page verdict line from an owner-requested UX review of 0.4.33 on a figure document (`pl`), and agents told which
verdicts were superseded. On the line its words become a toggle, a verdict's reason is never lost without a word, and the
line stays one row on a desktop, with targets a mouse can hit and the line on a foldable's open sheet. For agents
(ADR-0023) the contract only grows: one optional pin field and one `pins.md` marker, nothing renamed or
removed, and nothing stored - a 0.4.33 server or an older agent reads the same records as before. Every route stays as it
was; the viewer still counts the verdict order itself, and a browser test holds its count and the server's together.

### Added

- **`superseded_by` on a superseded verdict pin** in `GET /api/pins`, `GET /api/pins?all=1` and `GET /api/pins/{id}`.
  A verdict pin that a newer explicit verdict pin (one with a `verdict` field) about the same target has overtaken - and
  that newer pin is not in the Trash - carries that pin's number, right after `fyi`. With three explicit verdicts `#41`,
  `#42` and `#43`, `#41` and `#42` both say `43`. The field is computed on every read, never stored, and absent
  (not `null`) on the newest verdict, on a pin that is not a verdict and on a verdict whose target the server cannot
  resolve; deleting the newer verdict takes it away and restoring it brings it back. The target is read from the
  stored place by the viewer's own rule: a figure document's `el.path[0]` (a verdict on the figure and one on a panel
  of it are one target, ADR-0022 D1), a view-only PDF's whole-page region by `page` (not one whose mark is only an
  estimate, `est`), a LaTeX pin's file and lines as located now (not a `stale` pin; two pins on the same lines count
  together only when both are open or share one `anchor`). State, author, replies and reopening do not change the
  order. The server never reads a memo (ADR-0021 D1), so a verdict pin of the older form - no `verdict`, the memo's first
  word is the verdict word - neither supersedes nor is superseded: with explicit `#1`, `#2` and an older-form `#3` the
  server says `{1: 2}`, while an agent that counts both forms takes `#3`. So the value is the newest *explicit*
  verdict, not necessarily the current one, and without the field a verdict pin is not necessarily current either: an
  agent still resolves the target by its repository's rules and counts from `?all=1` as before. The pass over a long history is linear in the number of verdict pins.
- **`#N로 대체됨` in `pins.md`.** An open verdict pin that a newer verdict supersedes reads
  `41 · 판정 보류(쪽 전체) · #43으로 대체됨` in its number cell, right after the verdict marker (`로` or `으로` by
  the last syllable the number is read with: `#10으로`, `#17로`, `#1000000000000로` for 일조). While one is open the guidance paragraph and the legend gain one clause each, after the
  verdict ones; the review table shows no marker. A `pins.md` without a superseded verdict is byte for byte what it was.
- **The agent skill** (`SKILL.md`, `SKILL.ko.md`): an agent does not carry out a pin that carries `superseded_by`, but
  still resolves its target and makes step 5's checks, re-reads the pin just before closing it with `#N 판정이
  앞섭니다`, and picks what to carry out by the ordering rule, which counts older-form verdicts; the counting rule for
  pins without the field is unchanged.

### Changed

- **The line's words are a toggle.** The current verdict's word is pressed (`aria-pressed="true"`, filled: the primary
  colour, a confirm word such as 삭제 the destructive colour). Pressing the pressed word takes the verdict back - the
  same as `판정 취소`, with the status line's [되돌리기] - when it is the person's own open verdict; pressing the current
  word never saves a second pin of that word. Someone else's verdict, or one already handled (검토 대기, 처리됨), is pressed
  too but stays: the status line says why (`지금 판정 #4 채택 그대로 · 다른 사람의 판정은 여기서 거두지 않습니다`). Any other
  word saves that verdict as before (a confirm word on its second press). The keys 1-5 do the same as the buttons. Right
  after a word was taken back, the same word waits 0.8 s, so a double press takes one verdict back and does not save it
  again. `판정 취소` on the line and [지우기] on the card stay.
- **Presses during a save are kept.** While a save on a line is out, the line says what it saves (`· 보류 저장 중…`) with
  that word pressed, and the buttons take presses: the last one wins and is applied when the save is done - a word that
  is current by then does nothing. Pressing 채택, 보류, 채택 150 ms apart ends on one 채택 pin (0.4.33 made two and ended on
  보류).
- **The reason is written in a popover over the line.** It never pushes the plot down or makes the floating line taller.
  No save opens it: a click save leaves `이유 추가` on the line (the reading line and the last-saved line); a key save
  leaves `Enter 이유 쓰기` there with the focus on it, and Enter - there, on the PDF area or a page - opens it with the
  focus. The popover names whose reason it is (`판정 #16 보류 이유`), marks a draft
  `저장 안 됨` and a written reason 체크 표시와 `저장됨`, says the keys, and has [닫기] and [저장] (and [지우기] for a saved
  reason). The field grows to five lines; Enter saves, Shift+Enter is a new line.
- **A saved reason is changed or cleared from the line.** The line shows it as a check and `<first line>`; on the person's own
  open verdict it opens the popover with the reason. Enter writes the changed text over it (the whole note, against its
  revision; if someone changed the note meanwhile it is not written over and the draft is kept), [지우기] clears it with
  [되돌리기], and Enter on an empty field keeps it.
- **Changing the verdict while typing moves the draft.** The draft goes to the new verdict - never to the one it
  replaces - and the popover says so (`판정 #16 보류 이유 · #15 채택에서 옮김`); once written, the status line says where
  (`이유 저장됨 · 판정 #16 보류 — <대상>`). A draft kept after a failed write moves the same way and is marked on the new
  verdict.
- **Digits in the reason field are always text.** Before the popover opens, 1-5 are the line's verdict keys (1 then 2
  saves 보류); once it is open every digit typed is text - a data plot's reason often starts with one (`12월 값이 튐`,
  `33개 건물에서 손해`). A digit an input method is composing is text too.
- **Taking a verdict back is found without a hover.** The pressed word carries a check, and a short line -
  `지금 삭제 판정 · 다시 누르면 판정 취소` - is its description (`aria-describedby`) and shows over the word group (never in
  the line's flow) on hover, on keyboard focus and for 4 s after a press made it the verdict, touch included.
- **Fold a reason away while writing.** [접기] folds the popover without writing, so the plot shows again; the draft is
  kept and the line marks it `초안 있음`, which opens it again. An editable saved reason shows a pencil and is named
  `저장된 이유 수정`.
- **The popover keeps the focus inside.** It is a labelled non-modal group that stays open while the focus is anywhere
  in it (Tab from the field to its buttons); a close gives the focus back to what opened it.
- **Status-line messages put the result first** (P3-12, shared with the line layout work): `판정 #17 채택 취소 · 지금 판정
  #12 보류 — <대상>` (or `· 남은 판정 없음`), `이유 저장 실패 · <까닭> — <대상>`, `판정 저장 실패 · <까닭> — <대상>`.
- **The page verdict line stays one row on a desktop, and stacking is decided per line.** One line with an earlier
  verdict or a reason used to put every page's buttons on a row of their own - at 1440 x 900 each line grew to 79-88px
  over the plot. Now each line is one row unless its own state and buttons cannot share it: the figure's title gives way
  first, down to a short identifier that is never cut (`6쪽 · PL17`, the code heading the map title), then the reason and
  the earlier verdicts' link, cut to fit; the state, [판정 취소] and the buttons never shrink. At 1440 the floating line is
  32px.
- **Targets a mouse can hit.** The words, [판정 취소] and the earlier link are 32px tall and the `#N` link answers
  32 x 32px (they were 28, 24 and 14px); the words stand 8px apart and the confirm word (`삭제`) 16px with a divider - on
  a foldable its 44px touch area no longer meets its neighbour's. The words' outline reads 3:1 and more on the button and
  the line's ground in both themes (it was 1.5:1).
- **The save chip stands in the line**, just left of the words, never over the plot, the figure's identifier or the
  current verdict and its state: where its words would reach them it folds to [되돌리기]. The line does not move for it.
  A confirm word waiting for its second press has no description box (it covered the figure's name).
- **The page being read stays put when the reading page changes.** A stacked line (a phone) gives the reading figure's
  name a row of its own; the line above the new reading page lost that row and pulled the page up 23px under the reader's
  eyes - a two-finger zoom over it then missed its anchor. Every other stacked line now keeps that row's place empty, and
  every line is fitted as the reading line it may become (its identifier and its keys' digits counted), so no line
  changes its rows or height with the reading page and nothing is scrolled to make up for it (a scroll doing so ended
  outline and page-list jumps part-way and trapped a slow phone scroll at a page's end).
- **The focus after a key save is never lost.** A new verdict saved right after a digit took one back left the focus on
  nothing (the line still offered the take-back's [되돌리기] and its [이유 추가] had stepped out); the new verdict now ends
  that offer on its line. A digit pressed with the focus on the outline, the page list, a document tab or a card brings the
  focus to the pages at once, so an Enter typed straight after it opens the reason instead of pressing that control again.
  While a card's editor or reply is open and has the focus, digits are its own and make no verdict.
- **A line starts where its page does.** With the panel closed at 1280 x 800 the status box at the bottom right pushed the
  line 36px left of its page; the line now ends before the box instead.
- **Foldable in portrait (and tablets).** With the pin sheet open the line floats on the sheet's top edge instead of going
  under it; while the reason is typed the line folds the figure's name, the chip shows only [되돌리기] and the status
  line over the sheet steps aside, so the plot keeps the room the keyboard leaves. A phone's open sheet still keeps the
  line in its place.
- **A folded verdict card shows what it is.** Its preview leads with the `판정 채택` badge and the figure's name, the
  reason on a line under them (a reason used to take the whole preview).

### Fixed

- **A changed saved reason never overwrites a note changed elsewhere.** The change and [지우기] are written against the
  revision the popover opened at - not the newer one a poll brought - so another tab's, person's or agent's change gets
  the server's 409: nothing is written, the draft is kept, and the popover shows the newer note with [메모 보기] and
  [그 위에 쓰기].
- **[지우기] keeps the popover and its draft until it succeeds**: a lost request or a conflict leaves both, and the
  status line says so (`이유 지우기 실패 · <까닭> — <대상>`, [다시 시도] when the server was not reached or failed - 5xx).
- **A page line's pending save belongs to its document.** A save held on one document's page no longer queues or
  swallows a press on the same page number of another document.
- **A key typed into the reason field after a key save no longer becomes the reason** (P1-1): 1, then 2 in the field,
  then Enter saved the note `2` on 채택 and made no 보류. Typing right after a key save no longer lands nowhere either.
- **The focus stays on its page.** Closing the popover (Enter, Esc, [닫기], [접기]) leaves the focus on the same page's
  line - its reason control, else the pressed word - not the PDF area, from which Tab went to the first page's line and
  scrolled ~39,000 px; Tab from the PDF area now goes to the reading page's line; Tab past the popover's last control
  comes back to its line instead of the next page's (which moved the reading page and closed the popover). A take-back
  by keyboard leaves the focus on the line's own [되돌리기], which the line offers while the status line does. Enter on a
  line's `#N` moves the focus to its card; a card deleted by keyboard hands it to its neighbour (a verdict card too), and
  a redrawn list (the list read after it, a poll) gives a card control's focus back to the same control. Tab after a
  press on a page or its margin goes to the reading page's line too; Shift+Tab from a line's first control while its
  popover is open goes to the popover's last instead of the page before. A take-back by a digit key leaves the focus on
  the line's [되돌리기].
- **Enter after a key save always opens the reason** (RC retest, P1-A). Pressed while the save was still out - a fast
  typist's 1 then Enter - it was ignored, and the digits typed next (`12월 값이 튐`) saved other verdicts. It now opens
  the popover for the verdict being saved (`채택 판정 이유 · 판정 저장 중`) with the focus in the field, binds it when the
  save lands - keeping the focus and caret while the line changes shape around it - and writes an Enter pressed before
  that as soon as it is bound. A save that fails keeps the text as the page's draft and says so.
- **Keys never act on a page scrolled out of view** (RC retest, P1-B). A focus left on another page's line control (the
  saved reason's pencil) when the reading page changes goes to the PDF area, and Enter or Space read on such a control
  before it moved does not act there: Enter goes to the reading page's reason, Space is only said. The wheel to the next
  page then Enter no longer opened the page before's reason off-screen and appended the text to its note.
- **A reason typed while its verdict's save is out is never lost or turned into verdicts** (RC round 3). When that save
  fails, the text is the page's draft and, if the field had the focus, the focus goes to the line's `초안 있음` and the
  digits typed on are not verdict keys; a focus elsewhere (search, composer) stays. Moving to another page or document
  before the save answers keeps the popover with that save: once it answers, the text is written on the verdict it made,
  on the document it was typed on.
- **The focus leaves the page the person left** even while its line still shows (after a PageDown), and Space or Enter
  read before that frame does not act on it. A digit take-back moves the focus to the line's [되돌리기] from anywhere (the
  outline), Tab into the pages from the outline or the section strip goes to the reading page's line, and Esc on the
  popover's buttons acts as in its field.
- **While a reason is written** its field and group no longer point at an empty description, and a [다시 시도] that finds
  a lost answer written clears the earlier `이유 저장 실패` notice, for an added and a changed reason alike.
- **No verdict key acts on a page a jump is gliding past.** While the pages scroll where the outline, the page list or
  a card sent them, 1-5 and Enter are not taken (the status line says so) until the scroll ends.
- **A press queued during a save is never dropped.** A save runs on the document, build and page it was pressed on:
  switching documents (A→B, or A→B→A) no longer drops it or the press queued meanwhile - both complete, the undo on the
  status line if the document is not on screen.
- **A verdict taken back elsewhere while its reason is typed** (another tab or person) no longer loses the text or turns
  the next digit into a verdict: the text becomes the page's draft (`초안 있음`, moved to the next verdict saved there),
  the status line says so, and the keys typed on are not verdict keys until a press or Esc.
- **A folded draft stays folded** after a reload and is never written by merely scrolling past.
- **Lost answers are read before they are called failures.** A page-line verdict, a composer save, a take-back and a
  [지우기] whose answer the network lost are checked against the list (or the note) first: a save that landed is a
  save - no `실패` left, no duplicate from a second press, no `#21 을 Alice 가 삭제함` for one's own take-back, no false
  `(빈 메모)` conflict.
- **A conflict shows the whole note**, scrolled, refreshed at every 409, and the line shows it too; [그 위에 쓰기] is a
  replace against the rev it read - also over an empty note - and a new reason reads the pin before writing (a stale
  list put `(추가 hh:mm)` into an emptied note).
- **A restored verdict superseded meanwhile says so** (`판정 #21 채택 되살림 · 지금 판정은 Bob의 #34 보류`) and opens no
  popover over the other person's line.
- **The card's edit no longer writes over a rival's note**: a 409 shows the note now, and only
  [내 메모로 덮어쓰기] replaces it.
- **Quieter and clearer for screen readers.** A save chip's undo moved to the status line is not read out again with the
  next save; the outline filter says `찾은 장·절이 없습니다.` once, not at every keystroke; drafts restored by a reload are
  announced; names hold their visible words (`초안 있음 — …`, `판정 취소 — …`); no `aria-describedby` points at nothing
  and no inert [접기] shows while a reason is being written. A name's particle follows its sound (`Bob이`, `Alice가`).
- **An unsaved reason is never lost without a word** (P1-2). Drafts are kept per pin in the tab (sessionStorage); a
  reload opens none by itself - each waits on its line as `초안 있음`, and the status line says how many with [보기], which
  brings the first one's line into view with the focus on it - and leaving the page with one asks first (beforeunload). With text,
  Esc takes two presses: the first only lets the focus out of the field while the popover stays open with its text - the
  keys then change the verdict and the draft follows - and says the next one drops it; the second drops it. On touch
  [닫기] does the same. Once the popover closes - Esc, Enter, [닫기], [접기] - the focus stays on that page's line: its reason
  control, else the pressed word (never the PDF area, from which Tab went to the first page's line). [되돌리기] of `판정 취소` (or of pressing the
  word again) and of the save chip bring the verdict back with its draft. Every failed write keeps the draft - lost on
  the network, refused (4xx) or too long - and the line marks it `초안 있음`; a reason that could only be added
  to someone's note (2,000 characters at most) and is longer says so instead of being sent.
- **An armed confirm word says how long it waits, and stops saying so** (P3-13). The line shows `4초 안에 한 번 더 누르면
  저장` beside it and a screen reader hears `삭제 — 4초 안에 한 번 더 누르면 저장합니다`; when it lets go - its time, Esc or a
  press elsewhere - that is replaced by `삭제 확정을 풀었습니다`, and after its saving press it is cleared.

- **The popover's buttons take the first tap with the keyboard up** (RC review). A tap on [저장], [접기] or [지우기] took the
  focus out of the field, the status line came back and a phone's line stacked again, so the button moved 24-85px between
  the touch and its click and the first tap fell on the popover. The fold the field makes holds until that click has run.
- **The save chip never moves the line or covers a control.** It is laid over the line, out of its flow - on a phone it
  added a row (131 -> 251px) and a tap on the old 삭제 spot undid the save - in room nothing takes: before the words, after
  the state's last row, or over the figure's title after its identifier; it folds to [되돌리기], and where even that has no
  room the undo is on the status line. It covered [이유 추가] (25 of 32 pages) and [판정 취소]; a click aimed at them under
  automation scrolled the document 583-1358px. A mouse resting on it holds it at most 4 seconds past its window (30).
- **A line too narrow for a verdict's state stacks whatever it shows**, and a line whose confirm word waits or whose save is
  out keeps its rows: a press no longer restacks a phone's line under the finger. On a desktop row that is tight, the earlier link
  steps out while a press's extra - `Enter 이유 쓰기` after a key save, the line's [되돌리기] of a take-back - is on the
  line, and while the line offers that [되돌리기] its [이유 추가] steps out on every row (as for an armed word's wait), the
  focus on it moving to the [되돌리기]: beside them the extras ran 7 and 25px past a 620px row (1280 x 800, panel open)
  and stacked it.
- **The reason popover opens below a line near the top** (under the section strip it showed one line of five) and is
  never taller than its room; **a keyboard laid over the page** (iPad Safari) no longer hides the floating line and the
  popover; on touch the floating line stands clear of the status line's [x], whose 44px took taps on the words' bottom.
- **Contrast and spacing.** The armed `삭제 확정` and `4초 안에 한 번 더 누르면 저장` read 6.3 and 5.8:1 in the light theme (3.6,
  4.2); the wait is said in full while armed (the reason, the earlier link, [이유 추가] and [판정 취소] give way); the reason
  field's edge reads 4.4:1 (1.5); a long reason is cut before its pencil; [판정 취소] stands 16px from the reason's button and
  the popover's [지우기] 16px from [닫기] with a divider.
- **No layout read per scroll for chips.** The select bar's check runs once a frame and reads nothing while no chip is up
  (seconds of long tasks over a first scroll through a hundred pins).

- **A first save moves no word of a narrow line** (RC retest). A line narrower than the state a press brings - measured
  once in a hidden line, not guessed - is stacked from the start on every band (on the wide band the rule was skipped:
  at 1280 x 800 zoomed to 66% and less a one-row line went to three rows, 91px, the words 59px down); a stacked line's state
  row and a touch row are as tall from the start as a text action makes them (a phone's line in its place dropped its
  words 25px).
- **Touch areas along both edges.** The status line's [x] reaches right, not over the right 6px of [되돌리기], and its
  buttons' areas cover their 1px borders: [되돌리기], [x] and the line's `#N` answer 44px at their left edge, middle and
  right edge on a phone and a folded-open foldable.
- **A web font that arrives late is measured again.** The width a fresh verdict's state takes, kept from the fallback face,
  is taken again and every line refitted when a font load is done and when the fonts are ready after boot.
- **A sheet's banner is scrolled clear of the stuck tool bar**: a card's [수정] conflict on a phone hid its first line.

### Internal

- The verdict contract snapshot gains a newer verdict on a panel of the figure and a newer one on the closed pin's lines;
  `test_viewer_supersession_parity.py` runs one flow of verdicts (a figure's root and panel, LaTeX lines, PDF pages, a
  region, older-form first-word pins, a deleted and restored verdict) and asserts that every `superseded_by` equals the
  viewer's own order. A mixed explicit/older-form scenario, a check of the index against scanning every newer pin on random
  mixes, and a 20,000-pin history with a time bound cover the reading; the particle is tested for numbers read with a
  unit name (만, 억, 조, 경, ...).

## 0.4.33 — 2026-10-29

Verdicts taken back where they were given, the page line's reason field in its rare orders, the outline filter, the
figure pick's badge and the figure pin's chip (#295 from a figure-document author's test, #294, #293). The agent
contract grows by addition only: `POST /api/pick`'s answer on a figure map gains `fill` and `rival`, and a pin may store
them with its `score`. `pins.md` and every route are unchanged.

### Added

- **[판정 취소] on the page verdict line** (#295). When the line's current verdict is the person's own and still open
  (waiting or being handled), `· 판정 취소` follows its state - also on the floating line. It sends the pin to the Trash
  the way the card does, and the line counts again at once: the newest earlier verdict about the same figure or page is
  the current verdict again (ADR-0021 D4), or `판정 없음`. The status line says `판정 #17 채택 취소됨 · <target> — 지금
  판정은 #12 보류입니다` with [되돌리기], which restores the pin. A verdict an agent had claimed still goes, with the
  save undo's warning that its run may have started. Someone else's verdict, a handled one and the agent and viewer roles
  get no [판정 취소] (D16); a double press takes back one verdict, not two. It is muted destructive text, not the blue of
  the line's links, underlined on hover and focus. A phone's floating line leaves it out (it made the line a row taller
  over the figure); the line in its place under the page and the card still offer it. A failed cancel brings back the
  reason being typed for that verdict, and a reason still on its way for a cancelled verdict fails quietly.
- **The outline filter takes the keyboard into its results** (#295). In the filter field Enter chooses the first result
  (the focus goes to its row) and ↓ moves the focus to it without choosing; on a result ↑/↓ move one row (↑ on the
  first goes back to the field), Enter chooses and Esc goes back to the field, without also closing the overlay panel or
  the phone's navigation sheet that Esc closes from the field. The panel's field and the sheet's field each work on
  their own list. A key an input method is composing with (Korean typing commits a syllable with Enter) or one pressed
  with Ctrl, Alt, Cmd or Shift is left alone, and with nothing found Enter and ↓ stay the field's. Enter in an empty
  field does nothing (it would have chosen the first entry of the whole list); ↓ there still goes to the list. A key
  that moves the focus makes the keyboard the input the focus ring answers, so the ring shows on the row after a click
  in the field and a few letters.
- **The filter says its keys and how many it found.** The field is described by one line (`↓ 결과로 · Enter 첫 결과 ·
  Esc 찾기 칸으로`, `aria-describedby`), shown under the panel's field while it has the focus with a mouse and read, not
  shown, on touch and in the sheet; a polite status after each keystroke says the number of results or that there are
  none (nothing for an empty field).
- **A filter result says its group when another group has the same name** (#295). The results are a flat list, so a
  figure listed under `채택` and again under the manuscript figure that holds it was two identical rows. Each now has
  its group on a line of its own above the row (`채택 ›`, small and muted, one line cut with an ellipsis, the whole in the
  row's description). Only a number and title that two groups share are named, and only in a filter's results; a row
  reads the same whatever else is typed.
- **The composer's element path shows the chosen element's box.** Pointing at the path (`B2 › 달력 › 7월 ·`) with the
  mouse or the focus draws the pending box on the page stronger; pressing it (a tap on touch) brings the box into view
  if it is out of it and flashes it. It was already the box snapped to the element; the path is now the way to check it.
- **`POST /api/pick` answers `fill` and `rival` for a figure map pick** (0.4.33+, additive). `fill` is the share of the
  element the drag covers (the element side; `score` is the share of the drag the element holds). `rival` is true when
  another element that is neither the winner's ancestor nor its descendant competes: a candidate within 0.1 of its
  `score`, or an element the drag covers 90% of. A pin stores them with its `score` (`POST /api/pin`, a `loc`), and a
  range edit forgets them with it.

### Changed

- **A verdict pin's card calls its [삭제] [지우기]** (#295). A word file may name a verdict `삭제`, and the card's
  `판정 삭제` badge beside a [삭제] read as that verdict; its description says the earlier verdict becomes current again.
  Ordinary cards keep [삭제]. `핀 지우기`, the name first proposed, broke onto two lines in the card's equal-width action
  cells at the default panel width.
- **No description box over a page line's save chip** (#295). Right after a save the pressed word's box came back over
  the button - and over the save chip at the line's end - from the click's focus or a resting hand's slight move. While
  a save chip stands on a line, its words now hold their descriptions back (their names and keys are still said), and
  they come back when the chip goes.
- **A map pick's `위치 불확실` badge is hidden below 90% too when the pick is sure** (#295). On a figure document the
  share is the chosen element's part of the drag, so a drag drawn with a margin round a legend or a label never reached
  90% and the badge stood over a pick that was right. It now hides when the share is at least 75%, the drag covers at
  least 95% of the element (`fill`) and nothing rivals it; any other pick keeps the badge up to 90% (the card and the
  composer agree, a pin saved before `fill` and `rival` keeps 90%). Measured on a real figure set's map (a sweep of
  12,435 drags at margins 0-100% round each element, 20 recorded drags, and 15,764 held-out drags on that map and on a
  concept figure map) the rule hides 784 right picks and no wrong one in the range under 90% (a plain 61% rule hid 3,687
  right and 5,886 wrong picks there: a drag round a small element can leave it out of the candidates and choose the big
  box behind it at 63-86%).
- **A figure pin whose element is where it was shows no `줄 +N 이동` chip** (#295). Its code lines can shift (a script
  edit above the element) while `el_sync` is `ok`: the pin follows the element, its mark and path have not moved, and
  the chip told of nothing. The card and the passing note `#N 줄 +N 이동` both leave it out; a pin whose element moved
  or is lost, and a manuscript pin, show it as before.
- **The section lookup (`outlineIndexAt`) stays under 1 ms for entries at one height with their left edges apart**
  (#293). Entries that share a height and differ only in their left edge, 2,000 on one page, were still compared in all
  pairs (about 11-15 ms a call). The winners of each spot are now put in two lists, by height and by left edge, and
  each is compared only with those in its height window and left-edge window (the shorter one walked), so this and the
  other distributions measured (one height with edges apart, in clumps, or crowded within 1e-3; one edge with heights
  apart; distinct spots; one spot; forty to a spot; fifty pages) are all under 1 ms. The answer is the 0.4.30 rule's, checked
  against the pairwise rule on random outlines.

### Fixed

- **The reason field in its rare orders** (#294). Going to a document with no page lines (a LaTeX manuscript) closed
  nothing and the typed reason was never saved; it is now saved as on any other move. Moving on while Enter's write was
  still out started a second write on the same revision, whose conflict retry added the reason twice; a session now
  writes once and the field waits while its write is out. A failed write on moving on lost the text; the status line now
  keeps it (`이유 저장 실패 · <target> — <why>`) with [다시 시도] unless the server refused it. [다시 시도] writes the draft
  as it is now (a field corrected after a failed Enter), and a write whose answer was lost is checked against the pin
  first, so a reason the server already holds is not added again.
- **A long press held for seconds no longer goes to the page when it lets go** (#293). The truncated title of the page list
  (and any button's description) shows on a long press, and the click the release brings is swallowed - but only for 900 ms
  after the description opened, so a finger held ~1.6 s navigated on release. The swallowing is armed again at the
  release of the press that opened the description, however long it was held. The hold belongs to that press: when the
  browser cancels it (no click follows) or the next press starts, it is let go, so a cancelled press cannot swallow the
  next tap.

## 0.4.32 — 2026-10-29

Verdicts on figure documents (ADR-0022), and an outline and page list for long figure documents. The agent contract
grows by addition only: `GET /api/meta`'s `pages[i]` carries a figure document's map facts, and `limn-figure-map/1` takes
an optional page key `verdict`. `pins.md` and every route are unchanged.

### Added

- **The reading page's verdict line floats.** Each page and its line are one block, and the line of the page under the
  reading line (the page the section strip names) is sticky to the PDF area's bottom within it: it floats above the
  bottom (an edge, a 1px separator and the area's own background set it off the page) and settles under the page at its
  end. Every other line stays in its place, so a figure not yet in view never shows a second line and the buttons under
  a resting mouse or thumb change only with the reading page. The floating line names what it decides (`7쪽 · [후보]
  PL18 · …`). At 1440x900 only 18 of the 88 figure pages of one paper showed their header and their line on one screen.
  It stays under save chips and over the page's marks, rises above a phone's sheet bar (and keyboard), keeps left of an
  overlay panel, does not float over a selection being written or an open phone sheet, and a focused button in it no
  longer scrolls the area. Compact screens keep the 44px words with a tighter edge and a smaller shadow.
- **Keys 1-5 press the verdict words** on the reading page's line, in the word file's order; a confirm word takes its key
  twice, as its button does. The page is read when the key is pressed, and a key's armed word lets go when the reading
  page changes. Not in a text field, a dialog or a popover, while a selection is being written or with Ctrl, Alt or
  Meta; on a page that takes no verdict a key says so on the status line. The line the keys reach shows each word's key
  on a mouse screen, and the buttons say it (`aria-keyshortcuts`, `단축키 1`); the help lists them.
- **A reason with a verdict, in place.** A save from a page line opens a one-line `이유 (선택)` field on that line - with
  the focus after a key, waiting after a click or a tap. Enter saves the text as the pin's note (the note edit a verdict
  pin takes; `pins.md` then marks the pin `수정됨`); Esc skips it; either sends the focus to the PDF area. Moving on - the
  reading page leaving the field's page, another save, another document - saves what was typed and says so
  (`이유 저장됨 · PL16`); an empty field just closes. The field and its text survive a rebuild; the undo takes them with
  the pin. The reason shows on the line and the card.
- **A verdict card names its figure** - the page's title from the map (`[후보] PL26 · …`), else `그림 <id>` - so the figure
  just put on hold is easy to find in the list.
- **`"verdict": false` on a figure map's page** (`limn-figure-map/1`, optional, additive): that page - a list, a question
  or a removed-figure page - has no verdict line and no verdict words in the composer. Any other value is as if absent.
- **`GET /api/meta`'s `pages[i]`** gains, on a figure document whose map loads, `figure` (the root id), `title` (when the
  map has one) and `verdict: false` (only when set), after `name`, `pt_w` and `pt_h`.

### Changed

- **On a figure document a verdict is the figure's.** The composer's verdict on any element saves a whole-page verdict
  about its figure (`el.path[0]`) with the note, as a press on the page line does - the line used to ignore it while the
  repository's agent ran it. Its lead names the figure (`판정 바로 저장 · [후보] PL35 · … 전체`). The page line, the
  `이전 판정` marker, the page-size marks and [보기] count an older element verdict as its figure's too (newest number
  first, as before). The server's `(쪽 전체)` is unchanged.
- **One save chip at a time.** A new save's chip moves an earlier one, with its [되돌리기], to the status line, whose
  title - all the folded line shows - names the verdict's figure.
- **A failed page-line save is said under that line** as well as on the status line.
- **A phone draws every verdict word 44px tall** (was 36px with a 44px hit).

- **The outline is read and drawn whole up to 2,000 entries, and says what it did not read.** The viewer stopped
  reading a PDF's outline at 180 entries (and at five levels) without a word, so a figure document whose outline runs to
  170 entries today was one page of figures from losing its tail unseen. The first 2,000 entries are read now - about
  twelve times today's figure document, about 0.18 s to read and draw at the limit, a section change costing 0.2 ms - and
  entries beyond that count or deeper than five levels are counted (only those with a destination) and said on the last
  line of the outline, the navigation sheet's list and the filter's results: `목차 항목 408개를 생략했습니다 — 읽는
  한도는 2,000개, 5단계입니다` (under a filter: `생략한 목차 항목 408개는 검색하지 않았습니다 — …`, also under `찾은
  장·절이 없습니다.`; shown even when every entry was left out). The line is quiet text, not a row. With nothing left unread no line appears, so an ordinary LaTeX
  outline is drawn exactly as before.
- **The section strip no longer redraws the outline.** Scrolling a long document changes the current section at every
  page, and each change rebuilt every row of both outline lists. It moves the highlight (`ol-active`, `aria-current`)
  on the rows already drawn, so the cost no longer grows with the outline - nor does choosing an entry or opening the
  phone's sheet; a filter keystroke redraws its own list only. Destinations are resolved 100 siblings at a time instead
  of one by one, and one that cannot be resolved leaves out its own entry, not the outline. The reading stops between
  batches when another document or build comes on screen, and the section lookup (`outlineIndexAt`) no longer compares
  every entry of a page with every other (26 ms a call at 2,000 distinct spots on one page, now under 1 ms; same
  answers).
- **A figure document's page list shows each figure's title.** The page jump (`3 / 91쪽 ⌄`, the foldable and tablet
  page count, and the phone's navigation sheet) listed page numbers only for a figure document. Each row now carries the
  page's title - `/api/meta`'s `pages[i].title` when the server gives one (the figure map's page title, e.g.
  `[후보] PL26 · 제목`), else the outline entry that points at the page (the deepest, first listed), else the number
  alone. A long title ends in an ellipsis; its whole text shows on hover and on a long press (a tap still goes to the page);
  a list with titles opens 380px wide instead of 300px. A list opened while the outline of a switched-to document is still
  being read shows numbers, not the previous document's headings, and is drawn again when the outline arrives. The
  tooltip box is a top-layer popover now, so it shows over the modal sheets too. A LaTeX manuscript's list and a
  view-only PDF's are unchanged.

## 0.4.31 — 2026-10-29

Follow-ups: small secondary text at 4.5:1 in both themes, `limn update` that reports a failed restart, and two fixes to
the actual-size view. The agent contract and `pins.md` are unchanged. A script that took every `limn update` exit as
success now sees status 3 when an instance did not come back.

### Changed

- **Small secondary text reads at 4.5:1 in the light theme and under a hover** (#277). The light theme's subtle text
  (`--subtle-foreground`) is now `#63636b` (was zinc-500 `#71717a`, 3.8:1 under a commit row's hover and 4.3:1 on a
  diff's added and removed rows): a commit's short hash reads 4.7:1 under the hover and 5.4:1 on a selected row (was
  4.4), a diff's line numbers 5.2:1 (was 4.3). It is still a step under the muted text (1.3 times on a card). The
  excerpt's context line numbers are no longer the muted text at 70% opacity (3.4:1 in light, 3.2:1 under a light
  hover, 4.0:1 under a dark hover) but the subtle text, opaque: 5.4:1 in light, 4.7:1 and 4.8:1 under the hovers. The
  shortcut in [핀 저장] (`Ctrl+Enter`) loses its 80% opacity (4.3:1 in light, 3.7:1 under the hover) and is set off by
  weight and size. The dark theme's tokens are unchanged; only its context line numbers and that shortcut change.
  The light theme's other colours are unchanged; the subtle token also draws [더보기]'s off switch track, a shade
  darker.

### Fixed

- **`limn update` exits 3 when a restart or its readiness check fails** (#274). After the install it restarted each
  instance that was running and warned about a failed restart or a server that did not answer, but ended with status 0,
  so a script or an agent that judged by the exit status called an update done while a server was down. Every instance
  is still tried; those whose restart failed, whose unit failed after the restart, or that did not answer 200 in time
  (`LIMN_WAIT`) are remembered, named in one line (`limn: update installed, but 2 of 3 running instance(s) did not come
  back: paper-a (restart failed), paper-b (not responding)`) and make the command end with 3. A 401 from the check stays
  a warning: the server answered, the check was refused for want of a usable token, as in `limn start`. Status 1 stays
  for what happens before any restart (bad arguments, no remote tag, a failed install, an unwritable unit file); 0 for
  `--dry-run`, `--no-restart`, no running instance and the shortcut below.
- **`limn update --help` and the Handbook say what `limn update` does not do.** `limn update --help` was an unknown
  argument; it now prints the options, the exit statuses, that a ref equal to the installed version ends with
  `already vX — not reinstalling` (status 0, nothing installed or restarted, `--force` overrides, `--from` has no such
  check) and that only instances that were active before the install are restarted.
- **A long drag from a pin badge's press area no longer ends in the badge's click** (#284). In [선택] mode a pen or
  finger that lands in a badge's 44px press area and moves draws a box, and the click on the badge was held off for
  400ms from the start of the drag only, so a drag that ran longer and was let go on the badge opened its card as well
  as drawing the box. The click is held off from the release now, however long the drag ran, and the hold ends when the
  next press begins - a finger's drag is not followed by a click, and the hold would have swallowed the next tap, on
  another badge. A tap that does not move is still the badge's, with a mouse or a finger, in or out of [선택] mode.
- **The zoom is kept when the figure is drawn again under the changes view** (#284). A new build with the same page
  count and other page sizes that arrived while the changes view hid the PDF area measured that area as 0 wide and cut
  the zoom to the limits of that width (a page viewed at 1800px came back at 816px, the printed size of a letter
  page). The zoom now stays, the pages take their new sizes at it, and the limits apply when the PDF area shows again.
  The reading spot is kept the same way: the page being read and how far down it is remembered when the changes view
  opens and restored on the way back, where the scroll offset in pixels had pointed at another place once the pages
  changed height (page 2 at 30% came back at 79%).

### Internal

- **A contrast test that reads the page as drawn** (#277). `RenderedSecondaryContrast` serves the manuscript, the
  figure, the reviewer's PDF and six more documents, an outlined PDF and verdict words, and opens - on a desktop (real
  hovers and keyboard focus) and a phone, plus the list on an unfolded foldable, in both themes - the cards, done and
  trash rows, notices, the outline, the documents bar and its popover, the navigation sheet, search, the composer's
  excerpt, verdict row and suggested edit on each kind of document, the page verdict lines and the changes view's
  commit list and diffs. It reads text nodes, an SVG text's fill, `::before`/`::after` text and fields' values and
  placeholders, composites each colour with the backgrounds and opacities under it, and holds small text to 4.5:1;
  text over a gradient, an image, a mask, a filter or a blend fails unless listed. Every rule that sets text in the
  muted or subtle colour (also through custom properties) or sets an opacity is either used by text it reads or
  listed with a reason (and its colour, with its selector's opacity, checked on the plain surfaces), so a new one
  fails the test until classified. `FrontendColourRoles`' token pairs cover the light theme and the pin's diff row
  too.

## 0.4.30 — 2026-10-28

Pages at their printed size with 100% = print size, and a section strip and outline that follow the page. Viewer only:
the agent contract and `pins.md` are unchanged. A browser that goes back to an older release keeps the page width it
saved (`pinPrefs.w`) and ignores the figure documents' new settings.

### Changed

- **Pages are drawn at their sizes on paper, and 100% is the printed size** (#281). Every page was drawn at one width,
  so in a figure document a one-column figure (252pt) was stretched to the width of a two-column one (522pt) and nobody
  could tell how large a figure would print. A page is now its paper width times one scale for the document: the
  one-column figure is half as wide as the two-column one, and a narrower page is centred with its page number outside
  it. The zoom figure reads against the printed size (1pt = 1/72in, the CSS inch 96px), as other PDF viewers' 100% does,
  where it read against the fitted width. Fit-width fits the widest page. A document whose pages are all one size keeps
  the widths it had at its opening scale (only its zoom figure reads differently); a manuscript with a landscape page
  now fits that page, and its portrait pages are narrower. The page verdict lines, the mark badges, the save chips, the
  vector canvases, the two-finger and double-tap zoom, the figure overlay of the changes view and the comparison PDF's
  pages all follow each page's own width.
- **A fitted page no longer scrolls sideways.** With a mouse, fit-width was 12px wider than the room inside the PDF
  area's padding; it is now that room, on every screen.
- **The zoom limits always hold the printed size**, also for a page smaller than 160px, and are no longer rounded (a
  522pt page drew 697px at 100%).

### Added

- **The desktop tool bar's zoom button shows the zoom and goes to 100%**: before [↔], it reads the zoom now (`89%`),
  and pressed it shows the pages at their printed size and reads `100%`, pressed. [⋯]'s zoom row on every screen has a
  [100%] button. The changes view hides both: its comparison PDF's zoom is against its fitted width. There is no
  keyboard shortcut for it - Ctrl/⌘ 1 stays the browser's first tab.
- **A figure document opens at its printed size** when nothing is saved and its most common page width fits the PDF
  area - a rare wider page (a graphical abstract) scrolls sideways - else with that common page fitted. A zoom chosen on
  a desktop is kept per kind of document: figure documents keep their zoom against the printed size
  (`pinPrefs.figZoom`), LaTeX and view-only documents their page width as before - so zooming the manuscript no longer
  decides how a figure opens. A page width saved before this release was set on the manuscript: it stays the
  manuscript's, and a figure document opens at its own default.
- **In [선택] mode a drag that starts on a pin badge's press area over the page draws a box.** On a small page the
  badges' 44px areas covered much of its left edge and no drag could start there; a tap on a badge still opens its card.

### Fixed

- **The section strip names the page's own entry when the outline is not in page order** (#279). It named the last
  entry the outline lists at or before the page, taking the outline to be in page order; a figure set's outline grouped
  by status (`본문` on pages 3, 8 and 9, then `채택`, then every `후보` from page 1) showed page 2's `D4-scale` on page 3
  and page 7's `FP5-three-decisions` on pages 8 and 9. The page now decides first: the latest page with an entry that
  starts above the reading line - this page, else the nearest earlier one. On that page the outline's order is still the
  reading order (a two-column page), and of entries at the same spot - the same height and the same left edge, so two
  headings at one height in the two columns are two spots - the deepest wins, then the one listed first. An outline in
  page order with a spot per heading, as LaTeX writes it, gets the entry it always got.
- **An entry picked in the outline stays in the section strip on its page.** The pick was let go at once, before the
  scroll it starts had reached the page, so a page with two entries showed the other one. It now holds from when the
  page is reached until the reader leaves it. A pick that never gets there is let go: when the reader takes over (a
  wheel, a touch, a press on the pages or the scroll bar, a scrolling key), the window changes size, another pick comes,
  or the pages stop for 250 ms on another page - so a later visit to that page by hand names the page's own entry.
- **A heading picked in the outline is in view at the top.** A pick scrolled to its page's top, so a heading low on the
  page (`3.2` at 83% of page 8) lay under the window's bottom while the strip already named it. A heading with a place
  on its page now stands 8px under the top of the PDF area, lower only so that the reading line stays on its page, and
  as far as the document scrolls. An entry for a whole page, and every entry of a figure document, still lands on the
  page's top.

### Internal

- **A verdict-line test no longer races the first pin list.** It released the held `GET /api/pins` as soon as the page
  verdict line had drawn, but the line can draw before the list is asked for; it now waits for the request (#283).

## 0.4.29 — 2026-10-28

Dark theme contrast for small secondary text, and a steadier CI. Viewer only: the agent contract and `pins.md` are
unchanged, and rolling back to 0.4.28 loses nothing.

### Changed

- **Small secondary text reads better in the dark theme.** The dark theme's muted text (`--muted-foreground`) is now
  `#b3b3ba` and its subtle text (`--subtle-foreground`) `#9a9aa3`, so relative times, names, page numbers and the
  neutral badges (`이전 판정 · #4로 대체됨`, `보기 전용`) read at 4.8:1 or more on every surface they sit on at full strength -
  7.2:1 on a badge (was 5.8) and 8.9:1 on a card (was 7.2); the subtle text read 4.0:1 under a commit row's hover.
  Foreground, muted and subtle stay three distinct steps. The light theme is unchanged. Still short of 4.5:1: the
  excerpt's context line numbers, which dim the muted text to 70% (4.0:1 under a dark hover), and the light theme's
  subtle text under a hover (3.8:1) - #277.

### Internal

- **A rotation test no longer races the band's settle wait.**
  `test_a_text_field_focused_during_the_settle_wait_holds_the_band` focused the note from Python after the 200 ms wait
  had started, and on a slow CI runner the round trip outlasted the wait (one failure on main). The note now takes the
  focus inside the page, in the task that ends the wait, just before the viewer's own check; under 40x CPU throttling
  the old test failed 30 of 30 runs and the new one none (#275).

## 0.4.28 — 2026-10-28

Fixes from the functional re-test of 0.4.27's verdict buttons and its review. Viewer only: the agent contract and
`pins.md` are unchanged, and rolling back to 0.4.27 loses nothing.

### Fixed

- **A save chip's [되돌리기] can always be pressed.** On the unfolded foldable (841×673) the longer verdict chip
  (`#12 저장됨 · 채택 [되돌리기]`) ran under the panel laid over the PDF area, so a tap landed on the panel. A chip now
  stays inside its page, what the PDF area shows and clear of such a panel and of its handle's touch area; where the
  room is narrow its words give way (ellipsis), never [되돌리기]. It is placed again after a zoom and while the PDF area
  scrolls either way.
- **The page verdict line waits for the first pin list.** Until it arrives the line reads `판정 읽는 중…` and its
  buttons wait (they said `판정 없음` and took presses - for 16 s on a throttled connection).
- **An agent-role person is not offered what D16 refuses:** no [삭제] on a verdict card, no [되살리기] on a verdict pin
  in the Trash.
- **A wrapped verdict word group keeps each word at its own width.** In English at the 280 px panel a lone `이동` on
  the second row ran across the whole row.

## 0.4.27 — 2026-10-27

Fixes from the reviews and the functional test of 0.4.26's verdict buttons, a card badge for a verdict a newer one
replaced, and one owner decision on the agent contract (D16): agents may not delete or restore verdict pins. That adds a
refusal and nothing else; `pins.md` and every other answer are unchanged, so an agent written against 0.4.26 keeps
working unless it deleted verdict pins, and rolling back to 0.4.26 loses nothing.

### Changed (agent contract)

- **Agents neither delete nor restore verdict pins** (ADR-0021 D9, spec D16). An agent's - a token's, the headerless
  loopback agent's or an agent-role person's - `POST /api/pins/{id}/drop` of a verdict pin answers `403 {"error": "판정은
  사람이 정합니다 — 에이전트는 판정 핀을 지우지 않습니다.", "reason": "verdict_human"}` and `POST /api/pins/{id}/restore`
  `403` with the same reason (`… 판정 핀을 되살리지 않습니다.`); nothing is written. Deleting the newest verdict about a
  target silently made an older one current again, so it is a verdict decision in effect, a person's as making one is
  (D11). People keep their rights, and agents still delete and restore pins without a verdict; purge and clear were
  already owner-only. The agent skill says so.

### Added

- **Replaced verdicts say so on their cards.** A verdict pin whose target has a newer verdict carries a neutral
  `이전 판정 · #4로 대체됨` next to its verdict badge (`Earlier verdict · replaced by #4`), on open cards, review cards
  and completed rows; only `#4` is a link, to the current verdict's card. A folded card's preview line becomes its
  verdict badge and this marker, then the words `메모 있음` (`has note`) when it has a note (shown when opened), and does
  not clip the link's 44 px touch area. Such a completed row keeps its facts on two lines at every width: the number,
  the verdict badge and the marker with [답글] at the end, then the page and region, reference and time. The current
  verdict comes from the same ordering as the page verdict line (the highest pin number per target, deleted pins
  excluded), built once per list change as an index. Targets are read by location only: a whole page, a figure element,
  or the same file and lines of a LaTeX document when both pins are open (their lines are matched to the text now) or
  share an anchor (saved on the same text); a closed pin whose lines may be from older text is its own target. Pins
  whose target cannot be read carry nothing. It shows without a page line (`page: false`, LaTeX documents) and on other
  documents' cards under [모든 문서].

### Fixed

- **A retried verdict save keeps its verdict.** When a composer verdict save failed on the network, [다시 저장] saved a
  plain pin and the author's verdict was lost. The retry now carries the verdict only while nothing the composer asks
  has changed since the press and it still asks for a verdict pin (a fix request with [제안 수정] off): a new, cleared or
  restored selection, its rung or lines, the kind or the switch each start a new intent (also when changed back), and a
  change made while the request was still out leaves no retry at all. A retry never overrides a choice made after the
  press.
- **A confirmed verdict still counts while its undo is offered.** Pressing [확인] on the newest verdict awaiting review
  took it off the review list during the undo window, and the page verdict line showed the older verdict as the newest.
- **The verdict buttons come back after a save.** A selection picked while a save was in flight kept its verdict
  buttons off after the request ended.
- **The focus comes back after a keyboard save on a page verdict line**, to the same word's button, unless it was
  moved anywhere else meanwhile (another page's word, a `#N` link, the panel).
- **A confirmed verdict deleted elsewhere during its undo window leaves the verdict order** at the next list read, and
  the confirm's [되돌리기] no longer brings it back (it restored the copy it had taken, making the deleted pin current
  again); it says `핀 #N 은 그사이 다른 곳에서 지워졌습니다`. A pin still awaiting review comes back as the latest list has
  it.
- **Completed rows name a region's page as `2쪽 영역`**, as the cards do (`쪽 2 영역` before).
- **A zoomed page's verdict line stays in view with a mouse.** At 1440 px with Ctrl+= the line scrolled away with
  the page: the pages' column kept the fitted width, so the sticky line had nowhere to stick. The column is now as wide
  as the widest page on every pointer (touch already was).
- **A press survives a line whose words change under it.** A newer verdict by someone else, or the minute tick, while
  the mouse was down rewrote the line and lost the press. Lines are now changed in place: the buttons, the `#N` link
  and the earlier link stay the same elements.
- **The focus stays during a page line's save.** The pressed button waits as `aria-disabled` instead of `disabled`, so
  the focus is not dropped to the page and Tab goes on from it; a `#N` link whose number changes keeps the focus.
- **The page line's `#N` link answers 44 px on touch** and is named like the card marker's link (`지금 판정 #4 카드로
  갑니다`).
- **The retry banner says when the verdict was dropped.** After the kind, the switch or the selection changed - after
  the failure or while the request was still out - the banner read `판정 저장 실패` while [다시 저장] saved a plain pin;
  it now reads `핀 저장 실패 — 선택했던 판정은 해제됐습니다 — 판정으로 저장하려면 판정 버튼을 다시 누릅니다`.
- **A second pick turns the composer's verdict buttons off for real** (disabled, with `위치를 찾는 중입니다`), not only
  greyed.
- **No page-size mark for any verdict the page line accounts for**, the earlier ones included.
- **The narrow English panel wraps the verdict words rather than cutting them** when a word is armed.
- **Letting an armed word go by time or Esc is announced** (`삭제 확정을 풀었습니다`).
- **The undo message after an agent's claim shows whole on the folded status line**: `처리 중이던 판정이라 이미 실행됐을
  수 있습니다`.
- **A press on a page verdict line is not lost to a list refresh.** Every poll redrew the line's buttons, and a redraw
  between the mouse going down and up sent the click to the line instead of the button. Lines whose text is unchanged
  are no longer rewritten.
- **A card of another document names its own word** under [모든 문서] (the label came from the document on screen).
- **The location line, the note and the verdict row all show with the keyboard up at 841×673** (the line went 20 px
  under the nav bar): on touch panels the location line now sticks at the panel's top while the note or the suggestion
  editor has focus, as it already did on the sheets.

### Changed

- **Page verdict line wording**, one order for every state: `판정 #4 채택 · 처리 대기`, `판정 #5 삭제 · 처리 중 · Bob 7분
  전`, `판정 #8 보류 · 검토 대기`, `판정 #8 보류 · 처리됨`, `판정 없음`. `#4` links to the card; the page buttons say
  `누르면 이 쪽에 새 판정 핀을 저장합니다`. The earlier-verdicts link reads `이전 판정 N건 · 새 판정으로 대체됨` (`N earlier verdicts · replaced`) and, like
  every viewer link, is underlined only on hover and keyboard focus.
- **Page line and chip wording**: a claimed verdict names its claimer, `판정 #5 삭제 · 처리 중(Agent B) · Bob 7분 전`;
  the save chip shows the word, `#12 저장됨 · 채택`.
- **Composer verdict row**: the lead label is `판정 바로 저장` and each button says `누르면 지금 선택과 메모를 <낱말> 판정
  핀으로 바로 저장합니다`; the reasons for turned-off buttons point at the control: `질문에는 판정을 붙이지 않습니다 — 아래에서
  [수정 요청]을 고릅니다`, `판정을 저장하려면 [제안 수정]을 끕니다`. The row sits one 8 px step from its neighbours (the gap was
  doubled), drawn 36 px on touch.
- **Narrow widths**: when any page's line cannot hold its words and buttons on one row (phones, a folded cover), every
  page's line puts its buttons on a row of their own, at its start.
- **Cards**: a verdict pin without a note no longer spends a line on `(판정만)` (its `판정 X` badge says it; a folded
  card's preview is the badge; `pins.md` keeps `(판정만)`), and two verdict pins about the same page target no longer
  carry overlap badges such as `#4와 같은 범위` where the page line shows them both (it orders them); with `page: false`,
  without a word file or on another document's card under [모든 문서] the badge stays. Overlap badges with ordinary
  pins stay.

## 0.4.26 — 2026-10-27

Verdict pins (ADR-0021): on the server, and in the viewer as one-press buttons in the composer and under each page
of figure documents and view-only PDFs. A project opts in per document with a `<name>.limnverdicts.json` word file;
without one nothing changes. The agent contract only grows: an agent written against 0.4.25 keeps working, and a
0.4.25 server reads and rewrites the new field unchanged, so rolling back loses nothing.

### Added

- **Verdict word files.** A document may declare one to five verdict words in `<name>.limnverdicts.json` next to its
  main file (format `limn-verdicts/1`: each word a `key`, an optional `label` and `confirm`, and an optional `page`
  for the file). Limn reads it through the checked manuscript handle, never more than 4,097 bytes, and again only when
  the file changes. The file is untrusted input: a repeated name, a bad key or label, more than 4,096 bytes or anything
  else off the format makes it unusable, and the server log says so once per version. There is no setting key, and the
  file is not a LaTeX source, so editing it neither rebuilds nor marks the manuscript as changed.
- **`verdicts` on `GET /api/docs` and the full `GET /api/meta`** (`{page, choices: [{key, label, confirm}]}`), or
  `verdicts_error` (`unreadable`, `too_large`, `invalid`) when the file cannot be used. `page` is true only for figure
  documents and view-only PDFs. The light poll and the `docs` copies inside meta carry neither.
- **`verdict` on `POST /api/pin`.** A person with the editor or owner role may give a new pin one of its document's
  keys; it is stored as written and returned as stored. Refusals, checked inside the pin transaction against the
  words and map read just before it takes the pin lock (so a stalled word file holds up no other pin operation), in
  this order: `403 verdict_human` (any agent), `400 verdict_unsupported` (no usable word file), `400 verdict_unknown`
  (with the document's `choices`), `400 verdict_conflict` (with a question or a suggested edit) and
  `400 verdict_page_target` (a whole figure that the map of its build does not confirm as the root of that page).
- **A verdict pin keeps its verdict and target.** `POST /api/pins/{id}/edit` with `verdict`, `loc`, `lo`, `hi`,
  `scope`, `kind`, `kind_req` or `suggest` on a verdict pin, or with `verdict` on any pin, answers
  `400 verdict_fixed` and writes nothing. The note, `note_append`, the assignee and mention hints still change, and
  line realignment still moves the pin.
- **`pins.md`**: `판정 <key>` right after the number (`판정 <key>(쪽 전체)` for a whole figure or a whole view-only PDF
  page), `(판정만)` for a verdict pin without a memo, a legend entry and a guidance clause on ordering verdicts by pin
  number - all only while an open verdict pin is listed. Without one the file is byte-identical to 0.4.25's.
- **The agent procedure for verdict pins** in both skill files: the two forms (a JSON `verdict` and a repository's
  first-word pins), resolving a pin to the repository's target ID, the highest pin number over the whole history
  wins, one target at a time with a recheck right before pushing, and a `대상: <대상 ID>` line when closing.
- The viewer's English mode has texts for the six new reasons.
- **Verdict buttons in the composer.** On a document with verdict words, a row `판정으로 저장 [채택] [보류] [삭제]`
  under the note saves the selection and its note as a verdict pin in one press, with the usual `#N 저장됨
  [되돌리기]`; with the note focused on a touch sheet the row stays on screen above the keyboard. The buttons are off,
  with the reason under them, for a question, while a suggested edit is on and while the location is still being
  found (a press then does nothing; it does not queue as [핀 저장] does). A word marked `confirm` (shown in the
  danger colour) takes two presses: the first turns it into `<word> 확정` for 4 s, bound to the document, build,
  selection and word, and Esc, another press, a new selection or the timeout lets it go.
- **A page verdict line on figure documents and view-only PDFs** whose word file says `"page": true`: under each page,
  the newest verdict about that page's figure (or that page) with its state - `처리 기다리는 판정`, `처리 중`, `검토
  대기`, `처리됨` or `판정 없음` - a link to earlier open verdicts it overrides, and a button per word that saves a
  verdict about the whole page without touching the composer. Its pin draws no page-size mark; the card's [보기] goes
  to the line. The page list shows `#42 채택` on such pages. The owner picked this place - a line under each page -
  over a floating bar for the page in view after the four-device PoC on 2026-10-27.
- **Verdict pins on cards.** A `판정 채택` badge on open, awaiting-review and done cards; `(판정만)` for an empty
  note. Undoing a verdict's save withdraws it without reopening the composer, and says so when an agent had already
  claimed it. A verdict pin's edit card offers only the note and the assignee. A viewer sees the line, never a button.

### Fixed

- **The composer's location line stays above the field you type in on phone and tablet sheets.** While the note or
  the suggestion editor has focus on a touch sheet, the location line sticks under the tool bar, as a list section's
  header does, and a field scrolled into view stays below it. With the keyboard up, focusing the suggestion editor
  scrolled the line off (0 of 44 px on every phone and tablet-sheet size), and at 320×720 centring the note hid half
  of it (23 of 44 px).
- **The tablet sheet makes room for an open suggestion editor.** With `[제안 수정]` on, the 45% sheet rises just
  enough for the editor to end one 8 px step above the save row, at most 60% as for the keyboard; the lift follows the
  editor as it grows, is never saved, and ends when the switch goes off or the composer is saved or cancelled. The
  editor used to run under the save row (107 of 114 px shown at 768×1024, 25 of 114 px at 673×841).

## 0.4.25 — 2026-10-25

The note popover by the selection box offers the @-list. The agent contract (`pins.md` and the HTTP API) is unchanged.

### Fixed

- **@-tags in the note popover.** Typing `@` in the small note popover that a mouse drag opens by the selection box
  now opens the same people list as the panel's note: the same matching, arrow keys, Enter or Tab to pick, Esc to close,
  and a mouse pick. A pick inserts `@name ` and records the hint on the composer's note, so the preview line, the
  assignee row, the draft and a save from the popover (`[저장]`, Ctrl/Cmd+Enter) carry it. Before, the popover's field
  was not a mention field: `@` showed nothing and no tag was sent. The list never covers the popover's
  `[자세히 →]`/`[저장]` row and, in a short window, fits beside it and scrolls.
- The @-list follows the caret when it moves while the list is open, and a pick in the panel's note shows in an open
  note popover.

## 0.4.24 — 2026-10-24

Suggested-edit pins (ADR-0020). The agent contract only grows: an agent written against
0.4.23 keeps working, and a 0.4.23 server reads and rewrites the new field unchanged, so rolling back loses nothing.

### Added

- **Suggested-edit pins.** A LaTeX line pin may carry `suggest: {base, text}`, the lines the author saw and the exact
  text that replaces them (`""` deletes them). `POST /api/pin` and `POST /api/pins/{id}/edit` take it; edit replaces it
  or removes it with `null`, still needs `base_rev`, and a range edit without it keeps it. Limn checks `base` against
  the file before writing and answers `409 suggest_base_changed` with the lines' `current` text instead of saving a
  suggestion against text the author never saw; other refusals are `bad_suggest`, `suggest_unsupported` (view-only,
  figure and region pins), `suggest_too_long` (over 80 lines or 16,000 characters) and `suggest_noop`. Limn still
  never writes the manuscript: the agent applies the text verbatim through its usual pull request and close.
- **`suggest_state`.** Pin responses with a suggestion end with `ready`, `changed` or `unknown`, computed on every read
  from the lines as they are now and never stored.
- **`GET /api/snippet?…&text=1`** adds the range's exact unnumbered lines when it spans at most 80 lines.
- **`pins.md`**: the number-cell marker `제안 수정` (with `(원문 바뀜)` or `(확인 불가)`), `(제안 문안만)` for a pin
  without a memo, a `## 제안 문안` section with each text in a fence one backtick longer than its longest backtick run,
  a guidance clause and a legend entry - all only while an open pin carries a suggestion. Without one the file is
  byte-identical to 0.4.23's.
- **Suggested edits in the viewer.** The composer's kind row ends in a `[제안 수정]` switch for a LaTeX line selection of
  at most 80 lines (elsewhere a short reason stands in its place). It opens a monospace editor filled with the range's
  exact lines; until edited the text follows range changes, after that a line offers `[원문 다시 불러오기]`. A save
  sends `suggest` only when the text was edited, a memo is then optional, and a `409 suggest_base_changed` keeps the
  draft, shows the current lines against it and offers `[지금 원문으로 맞추기]`. Undo and the tab's draft bring the
  suggestion back with the memo. Cards show a `제안 수정` badge (`원문 바뀜` / `확인 불가` from `suggest_state`) and a
  line diff of base → text in the source-diff look, folded past five rows; the edit card edits the suggestion or
  removes it by switching it off, and a closed pin shows it read-only.

## 0.4.23 — 2026-10-19

A fix-only release. The agent contract (`pins.md`, the HTTP API, the state directory) is unchanged, so an agent
written against 0.4.22 needs no edit and instances keep their state as it is.

### Fixed

- **In-document search reads a column's wrapped lines again when something stands across the columns.** A line's
  column edges now come from its own block — the lines that overlap it sideways within one line pitch — so a
  full-width title, author line or figure caption, a table or figure wider than the text, or a page number reaching
  into a column no longer widens that column and breaks every line break in it. A list item's wrapped line, standing
  at the margin a first-level list's lines stand at, is read on from the item's first line. A query still never
  crosses into another column, a table's cells or rows, an `\hfill` line, or a gap inside a line wider than its font.
- **Browser diagnostics prepare their Korean test font automatically.** Font-sensitive regressions load a pinned,
  verified Noto face only in their test pages, with an offline reusable cache. Search-hint spacing checks measure
  eight CSS pixels from the actual inner border across Chromium, Firefox and WebKit at integer and fractional scales.
- **Search shortcut hints keep one system UI font.** The fixed keyboard hint stays vertically centred when the
  surrounding controls fall back to sans-serif or monospace; its glyph shape and width can differ from Pretendard.
- **External-document publication keeps one PDF generation.** Rendered pages, the downloadable PDF and the source
  fingerprint describe the same snapshot even when the source changes during rendering; the watcher recovers the
  next completed generation.
- **Malformed persisted input is rejected at its boundary.** An unencodable pin row does not block valid records or
  the next locked write, malformed or unrepresentable timestamps return no usable time, and an invalid token store
  denies bearer access while strict CLI validation continues to refuse it.

## 0.4.22 — 2026-10-10

### Changed

- **Many documents fit the nav bar whole.** When the document links do not all fit, the bar shows as many whole links
  as it has room for, in order, always including the current document's (in the last place when it would be left out),
  followed by a `+N` button for the N it leaves out. When not even the current link and `+N` fit, the row becomes one
  chooser showing the current document's name (shortened with an ellipsis as needed), and below about three characters
  of room a `files` icon; nothing in the row is cut, and only once the row is down to that icon does the instance's
  name shorten or, on a landscape phone, the status line drop its words (whole or not at all; its dot and action
  stay). The row no longer scrolls sideways or fades at its edges. The button opens a list of every document with its
  build state, page count and Alt+number, and a filter from nine documents; the list follows the button when the bar changes
  and is worked by mouse, touch and keyboard (Tab and Shift+Tab leave it to the bar, Alt+number works from its filter;
  checked in Chromium and Firefox), picking through the same document switch as a link. Focus rings in the row, on the
  view tabs and in the list are drawn inside their controls, 2px clear of their words. A bar whose links all fit is
  drawn as before (pixel-compared with 0.4.21 at the release viewports, light and dark), and phones keep the
  navigation sheet.

## 0.4.21 — 2026-10-10

Search the text of the document on screen, assign a pin by tagging a colleague in its note, and set the viewer's
controls on whole pixels and one ink centre. Later edits and chosen reply recipients survive pending saves, changed
recorded inputs rebuild, and figure picking is more consistent. `pins.md`, the HTTP API, stored pin records,
authentication and runtime dependencies are unchanged.

### Added

- **In-document text search.** The nav bar has a search field for the text of the PDF on screen (⌘F / Ctrl+F, taken
  only when the field can receive focus; Enter and Shift+Enter step through the hits, Esc closes and returns focus).
  Hits are highlighted on the page, the current one more strongly. Case, Unicode forms, curly quotes and dashes are
  folded; a hit may run over a line end or a hyphenated line break within one page. Lines that a table, a second
  column or a stretched line break apart are not joined, so some such text is not found (#231). The field folds to a
  magnifier in a crowded bar and covers its neighbours whole while open; on a phone it opens from the head of the
  navigation sheet. IME composition is respected.

- **Optional connection admission control (#222, ADR-0016).** Direct `limn serve --max-connections N` accepts a
  positive integer and counts pending, active and idle keep-alive sockets per listener through physical cleanup.
  Saturation closes the transport before HTTP. Omission preserves the existing unlimited admission and startup-failure
  behavior; no default cap or production activation is selected. In enabled mode uncertain native worker startup
  closes the listener and exits nonzero after existing cleanup, with the accepted cost of interrupting other daemon
  work. It adds no whole-process exit SLA, graceful drain, rollback or universal child-reaping policy.

### Changed

- **A new pin goes to the first colleague its note tags.** The tag may stand anywhere in the note, and questions follow
  the same rule; later colleagues are notified only. The line under the note says who is assigned and who is notified
  (`@알림 X · 따로 저장하면 담당 X` when appending), the preview, the control and the save use one rule, and colleagues
  with the same name show their login. The assignee control remains the override: plain text on touch, a pencil on hover
  with a mouse.
- **Folded cards say only what differs from the default.** A question, a colleague or yourself as assignee, and any
  status other than open appear on one muted line; a default pin keeps its v0.4.20 height.
- **Controls stand on whole pixels and centre their labels.** Small buttons are 24px and badges 20px; labels, badge
  icons and pin-mark numbers are centred on the cap height of whichever font draws them. Outline rows give each depth
  a number column and share one baseline. Note text is 22px per line and thread text 19px. A press between two close
  pin marks goes to the nearer mark.

### Fixed

- **The changes view returns to the reading position.** Leaving it no longer jumps the pages several pages away; the
  page width is not recomputed while the page column is hidden.
- **[확인] in the changes view is no longer covered** by the panel handle on tablets.
- **The assignee control no longer runs past the composer at 320px**, and a restored draft keeps the assignee picked.
- **Later input survives a pending save.** Composer, append and edit submissions retain text and metadata edited
  while their requests are pending. A stale append refuses without losing its draft, its undo is bound to the saved
  revision, and repeated create/append gestures cannot send the same submission twice.
- **Reply drafts retain chosen recipients.** Cancelling or switching pins preserves autocomplete login hints along
  with the text, including duplicate display names. An older deferred reply's undo or late failure cannot replace a
  newer live or cached draft, recipient, outcome override or cursor. A late failure is reported on the existing status
  line. Reply drafts remain confined to the current page, with one draft per pin.
- **Changed recorded inputs rebuild even with unchanged size and mtime.** Warm builds recompile changed input
  content, while unchanged builds and DPI-only page rendering retain their existing reuse behavior.
- **Thin figure marks and unrelated branches are picked more consistently.** Selection-only padding admits nearby
  narrow marks with sufficient overlap; eligible descendants beat ancestors, and unrelated branches compare original
  area and map order. Stored element geometry, location ladders and original-box scores retain their contracts.
- **Outline titles, numbers and page labels share their first line.** Both outline lists keep adjacent selected and
  hovered rows separated, omit page suffixes and retain touch target sizes.
- **Native collaboration controls keep their permissions and keyboard behavior.** Confirmation controls follow the
  existing human-review rule in cards and the changes view. Pin marks support Tab, Enter and Space, and card metadata
  retains native author editing plus question, claim, review and location-warning badges.

### Development

- Critical save flows run in Chromium, Firefox and WebKit. Revision fixtures do not depend on a contributor's
  automatic Git signing settings. Browser automation does not establish physical phone or tablet behavior.

## 0.4.20 — 2026-10-06

The figure pick threshold D6 is measured and set. `pins.md`, the HTTP API and the state directory are unchanged.

### Changed

- **Figure picks: `cover ≥ 0.4` (was 0.6), `fill ≥ 0.5` unchanged (ADR-0015, #126).**
  - **How it was measured.** The first real map-producing tool now exists: the paper's concept figures, 24 pages with
    7,855 elements. 59,492 seeded drags modelled on a person's hand were run through Limn's own pick.
  - **What changes.** A drag aimed at one element now picks it 61.4% of the time (was 47.4%). Answers too shallow to
    fix by stepping up the ladder fall from 20.3% to 12.1%.
  - **The trade-off.** A drag split evenly over two neighbours picks one of them, and their parent is the next ladder
    rung.
  - **What it does not fix.** Thin lines and dots, which no threshold reaches, remain a separate design question
    (#209).

## 0.4.19 — 2026-10-06

Compare two commits in the changes view, a note popover under the selection box, and the download row's icon.
`pins.md` and SKILL are unchanged. The HTTP API gains optional fields and refusal reasons; the few answers that
change without `base` are listed in `api.md` and ADR-0014.

### Added

- **The changes view compares two commits (#188, ADR-0014).** A quick range control
  `[마지막으로 본 뒤 N | 이 커밋부터 | 이 커밋만]` sits above a commit list that stays on screen. Side-branch commits
  are indented under their merge. Pressing a row shows that commit through now. The list is painted with exactly the
  commits the server compared, and N is the server's count. A range opens its source diff first; the comparison PDF
  is built only on [변경 PDF]. "Last seen" is kept per document in the browser and is never silently lost: a commit
  gone from history and one older than the latest 500 each say so.
  - API: an optional `base` on `/api/revision-diff`, `/api/revision-build` and `/api/revision-pdf`. A range answer
    adds `base`, `merge_base`, `commits`, `commit_ids` and `files`. `/api/revisions` rows gain `author`, `time`
    and `parents`, and `?before=&limit=` pages through the latest 500. New reasons: `base_after_head`,
    `no_merge_base`, `empty_range`, `pin_with_base`, `bad_limit`, `base_too_old`.
  - One history window (`git log -500 --topo-order`, read once per HEAD) now serves the list, validation, a pin's
    [변경 보기] and its `close_ref`. A pin closed with a commit hash is found anywhere in that window.
- **A note popover right under the selection box (#192).** After a mouse drag, a popover with the location, the
  note, [자세히 →] and [저장] opens 8 px under the box. The note is the composer's note. [저장] and Ctrl/⌘+Enter
  save through the usual path, with its 6 s undo. It flips and shifts at the edges and never covers the select-mode
  bar, the overlay panel or the save row. Touch and phones are unchanged.

### Changed

- **[더보기]'s [PDF 내려받기] row has the Lucide `download` icon**, aligned with the other rows.

## 0.4.18 — 2026-10-06

Quoted text, a page list, PDF download, click-off cancel, panel seams and one component standard. `pins.md` and the
state directory are unchanged; the HTTP API gains optional behaviour only (`GET /pdf?download=1`, a longer `quote`).

### Added

- **Download the PDF you are viewing (#186).** [더보기] has a [PDF 내려받기] row that saves the build on screen as
  `<document name>.pdf`. `GET /pdf?download=1` adds only `Content-Disposition: attachment` (an ASCII `filename` plus a
  UTF-8 `filename*`). Bytes, caching and access rules are the plain route's. Any other `download` value is ignored.
- **Go to a page without typing (#187).** The page count above the page (desktop) and in the nav bar (tablet) opens
  a list with one row per page and the sections that start on it. The current page is checked and scrolled into
  view, a page field sits on top, and choosing a row goes there at once. The phone's navigation sheet shows the same
  rows. Figure documents and view-only PDFs list page numbers only.
- **The dragged PDF text is shown (#185).** For LaTeX documents, one line with the dragged text sits under the
  composer's location row and above each pin card's note. It is ellipsized with the full text in a tooltip, and a
  press expands it. Pick and pin `quote` now keep up to 160 characters; `pins.md` still prints 60.

### Changed

- **A short press outside the selection cancels it (#191).** It works like [취소] or Esc, including the 6 s undo
  for a typed note. Drags still start a new selection. Presses inside the box, on pin marks or controls, pinches,
  double taps, long presses and select-mode taps are unaffected.
- **A seam line where the nav bar, outline and panel heads meet (#190).** A new `--border-seam` token, one step
  darker than `--border`, is used in light and dark. Phones are unchanged.
- **One component standard (#189).** `viewer.md` §컴포넌트 규격 defines buttons, inputs, popovers, sheets and
  chips, and the CSS uses tokens throughout. The comparison PDF's zoom buttons are now standard 28 px outline
  buttons, and the desktop outline toggle is 28 px. A test fails on new raw CSS values outside `tokens.css` unless
  an allowlist entry gives a reason.

### Fixed

- **A merge commit's source diff is no longer empty.** It is now taken against the first parent, like the
  comparison PDF.

## 0.4.17 — 2026-10-05

The interface is drawn in the bundled Pretendard Variable on every device. `pins.md`, the existing HTTP API and the
state directory are unchanged; one GET path is added.

### Changed

- **The interface is drawn in the bundled Pretendard Variable on every device.**
  - **What ships.** The viewer now ships Pretendard 1.3.9 (SIL OFL 1.1). It is the font's official unicode-range subset.
  - **How it is served.** The server serves it at `GET /vendor/pretendard/<file>`, with immutable, versioned URLs and
    the same access rules as `/vendor/pdfjs/`. No external origin is involved.
  - **What a page loads.** A phone loads only the slices its text uses: about 200 KB on a Korean page, plus the
    53 KB stylesheet, on the first visit.
  - **Fallback fonts are gone.** Phones without Pretendard no longer fall back to a wider system Korean font.
  - **First visit.** It shows the fallback until the slices arrive (`font-display: swap`). The bar's steps and
    [더보기]'s ink line are measured again once they have.
  - **Install size.** The wheel grows from 1.3 MB to 4.3 MB.
- **Text-ink checks run everywhere.** The alignment tests that measured text ink only where Pretendard happened to be
  installed now run on every machine, CI included.

## 0.4.16 — 2026-10-05

Hangul is no longer clipped in the phone bar. `pins.md`, the HTTP API and the state directory are unchanged.

### Fixed

- **Hangul no longer clipped in the phone bar.** On phones without Pretendard, the document name in [본문 1/25 ⌄]
  and the instance name in the [더보기] head lost the feet of their Hangul. Under some fonts "본문" read as "부무".
  Both labels are trimmed to their cap height and clipped for their ellipsis; they now have room for the full ink
  inside the clip, and the row's centre line does not move. A browser test renders the labels under a wide-extent
  Korean font and fails if any glyph pixel is cut.

## 0.4.15 — 2026-10-05

No toasts: every message is said where it happened. `pins.md`, the HTTP API and the state directory are unchanged.

### Changed

- **No toasts: every message is said where it happened (#167).**
  - **Undo.** A save's or an append's undo is a chip `저장됨 [되돌리기]` (Saved [Undo]) on the new pin's mark for 6 s,
    and it is there even with the phone's sheet folded. Deleting, completing and confirming leave a row with [되돌리기]
    in the card's place. A reply keeps its undo inside the card, and a permanent delete leaves its undo in the Trash
    row's place.
  - **Errors and conflicts** are a banner on top of the panel or section concerned, with its action. A failed save shows
    right above the save row, and the button reads [다시 저장] (Save again).
  - **Background events and first-visit hints** go to the status line, which on the desktop is a line under the status
    chips. A red dot stays on [핀 N] or [검토 M] until they are seen. Copying shows "✓ 복사됨" for a moment.
- **Where each kind of notice goes** (the new rules, in `viewer.md` §알림 자리):
  - An error shows where it can be seen now. Otherwise it goes on the status line, read out, with a dot. Errors come
    before other notices, and a build failure or a lost connection comes first.
  - An undo lives its full 6 s unless it is used or dismissed. Several undos can be open at once, and the notice limit
    never removes one.
  - A repeated error replaces the earlier one, and the next success of the same request clears it.
  - Moving the mouse over an undo pauses its timer. A message drawn under a pointer that is not moving does not count.
  - Sends that wait behind an undo still wait 6 s, and are sent at once when the page is left.
- **Nothing covers the select-mode bar any more.** In 0.4.14 the first-visit hint covered it on the phone. The hint is
  now on the status line.

## 0.4.14 — 2026-10-05

The touch select control says what it is and when it is on. `pins.md`, the HTTP API and the state directory are
unchanged; the desktop is unchanged.

### Changed

- **The select control says what it is and when it is on (#168).** The touch select button is now a symmetric dashed
  square. While select mode is on, a bar at the top of the PDF reads `선택 중 · 끌면 영역 · 탭하면 문단` (Selecting ·
  drag for an area · tap for a paragraph) with [끝내기] (Done), and a thin accent frame goes round the PDF area. At the
  top, page 1 starts below the bar. [끝내기] or Esc ends the mode in one step. Tablets, the landscape phone and the
  unfolded Fold label the button [⬚ 선택] / [⬚ 선택 중] at one width; the portrait phone keeps the icon, so
  [핀 N | 검토 M] never shrinks. The mode's first-use hint and the dashed outline round each page are gone.

### Docs

- `api.md` marks the first version of `progress` (0.4.11+), `overlay` and `path_names` (0.4.13+).

## 0.4.13 — 2026-10-04

Figure documents P2: a changes view that overlays the previous import, a figure pin's close that brings the edited
figure first, and element names on the path row. `pins.md` and the state directory are unchanged; the HTTP API only
gains optional fields. Reload viewer tabs opened before the upgrade: until then a figure document's changes view
there asks for a comparison PDF and gets `404 commit_not_recent`.

### Added

- **Changes view for figure documents.** History covers the files the current map names (scripts, shared components,
  the map and its PDF). [겹쳐 보기] lays the previous import's pages over the current ones and `[이전 | 지금]` flips
  them; [이전] is the previous import, not the state before a pin's `ref`. `GET /api/revisions` gains `overlay` for
  figure documents; no comparison PDF is built for them. The LaTeX changes view is unchanged (#126).
- **A close brings the edited files first.** A close that goes to review with a `ref`, on a document whose files the
  watch follows (a figure document or a view-only PDF), first pulls (with `--git-pull`) and imports or redraws, then
  writes the close and notifies the author, so the edited figure is already on screen. The refresh has one budget of
  30 s, waits for a pull or build already in flight, and never keeps the pin open: past the budget or on an error the
  close goes ahead and the watch catches up. SKILL notes that such a close can take up to 30 s and that a retried
  close is safe (#126).
- **Path names.** `POST /api/pick` on a figure gains `path_names`, and the path row names each element (`B2 › 달력 ›
  8월`) instead of its id (#126).

### Fixed

- **A figure folder reached through a symlink keeps its history.** Paths are compared with their folder resolved, as
  the LaTeX history does, so the history no longer drops script and component commits on macOS (`/var` → `/private/var`).

## 0.4.12 — 2026-10-04

Comparison PDFs now mark changes inside a document's own text macros, such as a reply letter's `\response{...}`.
`pins.md`, the HTTP API and the state directory are unchanged; cached comparison PDFs are rebuilt once.

### Fixed

- **The comparison PDF marks changes inside the document's own text macros.** latexdiff took a call such as
  `\response{...}` as one token, so a changed argument's old text was hidden and its new text drawn unmarked; a reply
  letter showed changes only in its plain opening paragraphs (#162). The comparison now passes latexdiff the commands
  that the new side's preamble defines with `\newcommand`/`\renewcommand`/`\providecommand` and whose last argument is
  typeset as text. Labels, file names, lengths, options and math are left as before. If a run with those commands does
  not build, the comparison is built once more with plain latexdiff, as before this release, and says so in its
  warnings. Macros defined in `\input` files, `.sty` files, `\NewDocumentCommand` or `\def` are not detected. Cached
  comparisons are rebuilt once (cache version `latex-pdf-v2`).

## 0.4.11 — 2026-10-04

Comparison PDFs zoom, the status line counts the pages it draws, and a batch of fixes: watched files rewritten within
one timestamp tick, provider logins, a viewer's 500 body, the [Confirm] notice and the band beside the overlay's
handle. `pins.md` is unchanged. The HTTP API gains the optional `progress` field on `GET /api/build`, and a viewer's
`500` body no longer carries the exception text. In the state directory `pdf_sig.txt` changes format, so each view-only
PDF is drawn once more after the upgrade.

### Added

- **Comparison PDFs zoom.** 50–500%, fit width, scrolling, keyboard shortcuts, wheel and trackpad gestures and touch
  pinch. Zoom keeps the page point under the pointer, a resize keeps the reading point at the centre, and the
  comparison's scale is independent of the manuscript's (#161).
- **The status line's progress bar counts pages.** `GET /api/build` gains an optional field
  `progress: {"done", "total"}` while a running build draws its page images, and `null` otherwise. On phones and tablets
  the bar fills to that share and reads `쪽 그리는 중 · 3/9쪽`. The TeX pass keeps the indeterminate bar, since
  latexmk's number of runs is not known ahead. A viewer on an older server looks as before (#127).

### Changed

- **A viewer's 500 no longer shows the exception.** An unexpected error answers the viewer role, and a request that
  fails before it is admitted, with the fixed `서버 내부 오류`. Owner, editor and agent still get
  `서버 내부 오류: <exception>`. Status 500, `reason: internal` and the stderr traceback are unchanged (#140).
- **A plainer "위치 불확실" tooltip.** In whole sentences, it now says how the place was found, how much of the drag it
  matches, that it may be far off (below 30%), and what to check. The badge and its 90%/30% limits are unchanged (#163).
- **[Confirm] on a pin a person already closed.** When the pin was reopened and closed straight to done while your
  confirm waited, the viewer now says it was already closed and there is nothing to confirm. It no longer asks you to
  look and confirm again.

### Fixed

- **Same-tick rewrites of watched PDFs and figure maps.** The watch for view-only PDFs and figure documents told two
  versions of a file apart by modification time and size. A same-size rewrite in the same timestamp tick kept the
  signature, so the screen stayed on the first version, and a figure document stuck on `pdf_mismatch`.
  - The signatures now carry the inode, which differs after an atomic replace.
  - A figure map is also signed with a digest of its bytes, so the watch reads the map (at most 4 MiB) on every tick.
  - An in-place, same-size overwrite of a PDF within one tick is still not seen; the handbook records this limit.
  - `pdf_sig.txt` changes format, so each view-only PDF is redrawn once and each figure document imported once,
    then they settle (#165).
- **Provider logins are validated whole.** A login was cleaned and truncated before the role lookup, so a malformed
  value could become another member's login. The identity is now decoded and checked apart from its display text,
  and a malformed value gets the existing `401 unauthenticated`. `SourceRange` checks its integer bounds when it is
  built and freezes its source snapshot.
- **The PDF beside the overlay panel's handle answers again.** On an unfolded Fold or a landscape phone with the panel
  open and no note being written, the handle's touch area covered a 36 px band of the PDF down the whole screen. The
  handle now answers a 44 px square on its grab mark; the rest of the band picks and scrolls the PDF (#127).

### Docs

- **Default language.** The instances guide says to start an instance written in Korean with `--ui-lang ko`
  (`UI_LANG=ko`), so phones with an English locale open in Korean.

## 0.4.10 — 2026-10-03

[Confirm] binds to the close you saw, and the viewer's internals are hardened: its markup goes through one escaping
tag and its JS parts are type-checked with strict null checks. `pins.md` and the state directory are unchanged; the
HTTP API gains one optional field on confirm and its `409` answer. The screens are the same as 0.4.9.

### Added

- **[Confirm] binds to the close you saw.** `POST /api/pins/{id}/confirm` takes an optional body `{"done_at": "<the
  close's done_at>"}`. If the agent reopened the pin and closed it again after you looked, the request answers
  `409 {"error": "conflict", "reason": "conflict", "pin": <latest>}` and changes nothing; the viewer sends the card's
  `done_at` and says the pin was closed again. A request without the field confirms the current close, as before.
  A `done_at` that is not a non-blank string of at most 64 characters is `400 bad_done_at`. Agents never confirm, so
  the agent contract (`pins.md`, SKILL) is unchanged; the HTTP API only gains the optional field and the new code.

### Internal

- **Viewer markup goes through one escaping tag.** Every part that builds HTML from data - toasts, the status line,
  page frames, the document choosers, the composer, the edit card, the reply box, pin cards, archive and Trash rows,
  the @-list and the changes view - writes it with an `html` template tag that escapes each interpolated value, into
  one sink. On the demo manuscript the phone, tablet and desktop screens, the composer, the edit card, the reply box,
  the More menu and the changes view render pixel for pixel as in 0.4.9.
- **The viewer's JS is type-checked.** CI runs `tsc` over the viewer's parts with `strictNullChecks`, and the pin,
  document, build and people answers are declared and checked against the handlers and the contract snapshot.
- **Security tests.** A role × action/read matrix, a check that every POST entry point is registered, and property
  tests for the header parser.
- **CI.** Actions are pinned to commit SHAs, checkout keeps no credentials, Dependabot watches the actions, and mypy
  also checks as macOS.

## 0.4.9 — 2026-10-03

The cross-resolution pass: one composer and one panel toggle on every layout, the desktop's [⋯] menu, and spacing
measured on phones, the Fold, tablets and the desktop. This release does not change `pins.md`, the API or the state
directory: the agent contract stays as it is. The composer's Wrap toggle and the line stepper are gone.

### Changed

- **One composer on every layout.** The wide layout takes the composer of phones and tablets: location, note, kind, the
  overlap notice, then the range block, on the panel's own background. Its range is set in the source like everywhere
  else - click a dimmed line to widen the range to it, the − on the band's first or last line to drop it, or Tab there
  and press Enter - and the "above + − below + −" stepper is gone from every layout. The help's tour has one range step.
- **The source always wraps.** The Wrap toggles under the composer's source and in the changes view are gone, with
  their saved settings: the source, the range excerpt, the edit card and both diffs always wrap, and a long token with
  nowhere to break (a URL, a command) breaks inside the box instead of running past its edge.
- **One panel toggle on every compact layout.** The unfolded Fold, the landscape tablets and the landscape phone show
  the phone's split chip [Pin N | Review M] where the pin icon pill [📍 N 👁 M ›] was, with [Select] on the same fill.
  The pins half opens and closes the panel; the review half goes to the review list.
- **Rows centred top to bottom.** The space above a tool row's controls now equals the space below them: 4 px each on
  the tablets' action row, 12 px each on the sheet's row (it was 12 over 4 with the sheet open, 12 over 8 collapsed).
  The bottom safe area is added underneath. Every icon, count and label in the row, including the status line's
  [Rebuild], sits on one centre line; [Rebuild]'s label had been drawn 1.9 px high.
- **The landscape phone's top row is 48 px.** It was 44 px, and the instance's colour stripe cut the tops of [Rebuild]
  and the pin chip. The row now has the height of the other touch nav bars, and its controls sit centred between the
  stripe and the row's line. Its icons are 18 px, each centred in its box. Neighbouring controls are 8 px apart. The
  row's ends line up with the panel and the page below it. The hairline where the PDF showed through between the row's
  two halves is gone.
- **One [⋯] on the desktop.** The wide tool row's bell, theme button and help button are replaced by one [⋯] at the
  row's end. It opens the same More panel as phones and tablets, as a menu under the button: theme and language are
  segmented controls, notifications a switch, and the foot shows the Limn wordmark, the version and Help. Esc, a click
  outside it and a row that closes it give the focus back to [⋯].
- **The desktop panel on two lines.** Without changing the panel's insets, every box in the wide panel now starts 12 px
  in from its edges and every unboxed label 25 px in, where the cards' text already started: the tool row's ends, its
  [Rebuild PDF] label, the section head's chevron and its tools' labels moved onto these lines.
- **Spacing measured for symmetry.** The nav bars on tablets, the unfolded Fold and the desktop centre their controls
  between the instance's colour stripe and their line; they stood 2 to 3 px high. The desktop tool row has 6 px above
  and below its controls (it had 4 and 8). The tablet rows end on the same edge line as the panel. The sheets' [Close]
  and the More foot's [Help] end their labels on the same line the titles start on, and help's title no longer stands
  4 px high. The pin chip's counts use proportional figures, so each half's label is centred.

### Fixed

- **A manuscript outside Git** leaves the commit out of the meta lines: they read `main.tex · 2 pp. · -`.
- **Help's head is one ink line.** The wordmark ends on the title's ink bottom, as in More's foot; it stood 3.3 px below.
- **Help and the Trash open under the same sheet head** as More and the navigation sheet on phones and tablets: a grab
  band and the title row with [Close], which stay at the top while the rest scrolls.
- **The segmented control is one size with a mouse too**: a 36 px track round 28 px segments.
- **Every compact layout draws the composer in one order**: location, note, kind, then the range block.
- **One border in the composer.** [Cancel] and the overlap notice's actions are filled; the copy button is a ghost on
  every layout.
- **Touch text fields answer 44 px**: the page fields and the outline search.
- **The focus a sheet gives back draws no ring after a tap**; it shows for the keyboard only.
- **The desktop's help and Trash close with the same ghost [Close]** as every sheet.
- **A first tap on a dimmed line works while a note has focus.** On a landscape phone the top row came back as the
  tap took the focus from the note and moved the panel under the finger, so only a second tap widened the range.

## 0.4.8 — 2026-10-02

The pin composer and the edit card on phones and tablets. This release does not change `pins.md`, the API or the
state directory: the agent contract stays as it is. The wide layout keeps its arrangement and its line stepper; it
shares the range caption, the ladder rule, the "+" badge and the segmented control.

### Changed

- **The range is set in the source.** In every layout but the wide one (phones, tablets, and a mouse window up to
  1099 px), the composer and the edit card show the selected lines in a tinted band with one dimmed line above and
  below. Tap a dimmed line to widen the range to it; tap the − on the band's first or last line to drop that line. A
  band longer than five lines folds its middle. This replaces the "above + − below + −" stepper, which read as moving
  the pin. The wide layout keeps the stepper, whatever the pointer, and the help's tour follows the layout. With a
  keyboard, Enter on + or − keeps the focus in place, so pressing it again repeats the step, and a screen reader hears
  the new range.
- **Range caption and ladder.** A caption over the source says the lines a save hands over and how many, such as
  "Range L5-L6 · 2 lines". The ladder of dragged lines, paragraph and environment shows only when there are two or
  more choices, under "Range". "Lines set by hand" is gone from the location line.
- **The save row stays at the bottom.** The composer's Cancel and Save pin, and the edit card's Re-place, Cancel and
  Save, sit at the bottom of the screen (or the panel), above the keyboard when it is up, instead of following a
  short list up the sheet.
- **Composer order.** On phones: location, note, kind, then the range block (caption, ladder, source), one 8 px step
  apart. Tab follows the same order. The pending box's "New pin" tag is a "+" badge where a saved pin's number goes. The copy button beside the
  location is a plain icon, and the composer has the sheet's background.
- **One segmented control.** Kind, range, sheet height, theme, language and the navigation sheet's view use the same
  track: segments 4 px in from every edge, a raised thumb whose shadow stays inside, 36 px drawn and 44 px to tap on
  touch. More's rows no longer touch each other.
- **Bottom bar on phones and tablet sheets.** The left cell is one chip in two halves, "Pin N | Review M": the first
  opens and closes the sheet, the second (purple, shown only when pins await review) goes to the review list. Select is
  a corners icon on the same fill. The row sits 12 px under the sheet's edge, with the grabber in that space, and
  every icon is centred on the numbers. When the cell is too narrow (English, a folded cover's 344 px, three-digit
  counts), the halves first take less padding, then the words give way to a green and a purple dot. A count never
  stands alone.
- **Sheets take the focus themselves.** More, the navigation sheet, Help and the Trash focus the sheet, not its Close
  button, so a phone no longer draws a focus ring on Close. Tab still reaches Close first.
- **More's foot.** The wordmark is 16 px, and the wordmark and the version line up with the bottom of "Help".

## 0.4.7 — 2026-10-02

A fix for pin polling. This release does not change `pins.md`, the API's paths or fields, or the state directory: the
agent contract stays as it is.

### Fixed

- **Pin changes in the same timestamp tick.** The pin list's change token (`pins_rev` in `/api/meta`) was the pins
  file's modification time and size. A rewrite of the same size that landed in the same filesystem timestamp tick kept
  the token, so a viewer could miss the change until the next one. The token now also carries the file's inode. The
  pins file is only written by atomic replace, so two consecutive writes always differ there. `pins_rev` is still an
  opaque string compared for equality; its value now ends with `:<inode>`. The test that met this under load (#121)
  now forces the same tick and passes every time.

## 0.4.6 — 2026-10-02

Phones and tablets get a three-column bottom bar, one status line and two sheets, Navigation and More. A review can
now end in the changes view. This release does not change `pins.md`, the API or the state directory: the agent
contract stays as it is. The desktop with a mouse looks the same, apart from the review controls in the changes view.

### Added

- **`--ui-lang ko|en`** (instance key `UI_LANG`, `limn add --ui-lang`) sets an instance's default viewer language. The
  viewer takes the language a person picked in More first, then this default, then the browser's language. Without
  the option nothing changes. The page shown to a refused browser follows the same order. Set the key, not
  `EXTRA_ARGS`: an older server refuses the unknown option.
- **Confirm in the changes view.** When View changes shows a pin awaiting review, its guide line has Confirm next to
  "to the manuscript". It confirms the pin and returns to the manuscript. On phones and tablet sheets both buttons sit
  in a thumb row right above the tool bar.

### Changed

- **Bottom bar.** On phones and tablet sheets the bar has three columns: pins and Select on the left, the sheet
  grabber exactly in the centre, the position button and More on the right. Phones use the 12 px edge. Below 400 px
  the position button shows only the page and the review count only its number; below 360 px the buttons' padding
  narrows. Nothing is cut.
- **One status line** replaces the row of chips on compact screens. Rebuild appears only when the PDF is older than
  the manuscript. While a build runs, the line shows its step and elapsed time over a progress bar that has no end:
  the server sends no page count yet. The viewer is ready to fill the bar from a `progress` field once builds report
  one. Failure, LaTeX errors, offline and sync problems use the same line. Rebuild PDF moves from the bar into
  More. A rebuild that changes nothing (0.4.5) says "No changes" on the line with Build anyway for six seconds, as long
  as a toast stays; the desktop keeps its toast.
- **Navigation sheet.** On phones, the position button (the document's name and the page, `[본문 3/25 ▾]`) opens one
  sheet with the documents, Manuscript or Changes, a page field and the outline. Picking an entry goes there and closes
  the sheet.
- **More** is rebuilt. It shows the instance label with its colour dot and two lines of build facts that never break
  inside a word. Zoom shows its percentage. Sheet height, theme and language are segmented controls. Browser
  notifications are a switch that says why it is off. The foot carries the Limn wordmark, the version and Help.
- **Confirm can be undone.** Confirm, on a card or in the changes view, takes the card out at once and shows Undo.
  The request is sent when the toast goes away, as with replies.
- The changes view hides the PDF, source and wrap controls when the document has no Git history or no recent commit.

### Removed

- The closed-pins row and the page field in More. The list's done section and the navigation sheet do their jobs.
- The 14 px Limn icon next to the instance label.

## 0.4.5 — 2026-10-02

Faster builds and faster page loads. On a 25-page manuscript at 150 dpi, measured on a busy 64-thread machine:

| | 0.4.4 | 0.4.5 |
| --- | --- | --- |
| Drawing the page images | 16.6 s | 1.2 s |
| A one-paragraph edit | 24 s, three pdflatex runs | 4 s, one run |
| A rebuild that changes nothing | 25 s | 0.2 s |
| A cold build | 38 s | 8 s |

`pins.md` does not change. The API only grows. `builds.json` gains no field.

### Changed

- **Parallel page render.** Each page has its own `pdftoppm`, with up to min(8, available CPUs) running at once.
  - The standard library writes the PNG at zlib level 1. The pixels are the same as before, and the bytes are 19% fewer.
  - A page that fails is named in the build log.
  - `pdfinfo`, from the same Poppler package as `pdftoppm`, is now required.
- **Warm LaTeX.** The build copy keeps latexmk's byproducts between builds, so an edit runs pdflatex once.
  - A PDF committed beside the main file never replaces the build's own output.
  - A forced build, a failed build and a build that crashes clear the byproducts.
- **The "go cold" rule.** Some changes are invisible to latexmk:
  - any latexmkrc it reads (system, user or project, picked as latexmk 4.87 picks them);
  - the toolchain on PATH: `latexmk`, the engine, bibtex, biber and makeindex, by real path and stat;
  - a makeindex or bibtex style file.

  When one of these changes, the build clears the byproducts before latexmk and starts from scratch, so a switch to
  xelatex or an edited `.ist` reaches the PDF.
- **Page URLs carry the build.** `/pages/<build>/page-NN.png` and `/pdf?build=<build>` are served
  `private, max-age=31536000, immutable`. They carry an ETag, and a matching `If-None-Match` gets `304`.
  - The viewer asks for these URLs.
  - The old `/pages/page-NN.png` keeps its ten-minute cache for this release only.

### Added

- **No-change rebuild.** A rebuild ends at once as `ok` with `unchanged: true`, and no new `build_seq`, when all of
  these match the ok build on screen:
  - the manuscript;
  - every file that build read, inside the tree by content and outside it (TeX Live, TEXINPUTS) by stat;
  - its recipe.

  The viewer shows "변경 없음 · [그래도 빌드]". The action sends `POST /api/rebuild?force=1`, which clears the kept
  byproducts and builds from scratch. Agents can send `?force=1` themselves.
- **`recipe.json`.** Each new page folder holds `recipe.json` beside the build's `.fls`. It records how the pages were
  made and what the build read.

## 0.4.4 — 2026-10-02

Viewer polish on phones and tablets: equal page margins, one edge grid, and no stray hover colours. This release does
not change `pins.md`, the API or the state directory, and it keeps the layout bands. The desktop with a mouse looks
the same.

### Changed

- **Equal page margins.** At fit, the page has the same margin on the left and on the right. On phones the margins
  were 32 and 8 px; they are now 12 and 12 px, and on tablet sheets 16 and 16 px. A pin's number badge sits outside its
  mark when the page margin has room for it. It moves inside only when the mark starts too close to the page edge.
- **One edge grid.** Section heads, cards, the documents sheet, Help and Trash share one edge and one text line. On
  phone and tablet widths, Help and Trash open as bottom sheets, like More and Documents. Trash rows take two lines.
- **Touch feedback.** Hover colours answer a mouse only, so a tapped row no longer stays grey. A short press colour
  marks a tap instead.
- **Colour roles.** Count badges are neutral. The awaiting-review count carries an eye icon. The sheet grabber
  reaches 3:1 contrast in light and dark themes.

### Fixed

- **User-written text is never translated.** This covers document names, notes, authors, thread posts, mark tooltips,
  notification titles, outline titles, the instance label and source excerpts. A document named `그림` stays `그림`
  on an English screen.

## 0.4.3 — 2026-10-01

A figure set that lives inside a LaTeX document's folder no longer makes that document look stale. Nothing changes in
`pins.md`, the API or its fields. No state file gains a field or changes its format: `builds.json`,
`built_src_mtime.txt` and the pin files are read and written as before. The one addition on disk is a file inside each
kept page folder, the build's latexmk `.fls` (see Fixed).

### Fixed

- **Re-rendering a figure document inside a LaTeX document's folder** no longer marks the LaTeX tab "manuscript
  edited", no longer puts the stale-PDF warning on a pick, and no longer turns the pins of the next rebuild into
  estimates (dashed marks). The LaTeX document's source list now leaves out two things another document owns: the
  figure files (`png`, `jpg`, `jpeg`, `pdf`, `eps`, `svg`) under a figure document's folder, and a view-only
  document's PDF as that one file - not the other files of its folder, so a PDF in the manuscript root no longer
  stales the manuscript when it is saved again. `.tex`, `.bib`, `.sty`, `.cls` and `.bst` still count wherever they
  are, and so does everything outside those two. A figure folder that is the LaTeX build root, holds it or holds the
  document's main file sets nothing apart.
- **A figure file the manuscript includes still counts.** The build keeps latexmk's recorder file (`<main>.fls`) in its
  page directory, next to the `.synctex.gz` and `.aux`, and a figure-set file it lists is part of the manuscript again:
  re-rendering that file makes the document stale, and the build's fingerprint includes it. Only files that were in the
  copy before latexmk ran count, at the mtime they had then: a file latexmk makes itself (an epstopdf conversion) does
  not move the baseline, so a source edited while a build runs still leaves the document stale. Only a `.fls` that the
  run wrote is read; one that came with the manuscript is ignored. A build with no `.fls`
  (made before this release, or latexmk's recorder switched off) is treated as having read none, so the re-render of a
  figure it did read is not reported until the next rebuild.
- The first rebuild after the upgrade can turn the pins of a document that has a figure set inside its folder into
  estimates once, because the fingerprint of the older build still included the figure files.
- The page directory kept for the build on screen and the one before it now also holds that build's `.fls` (typically
  tens to a few hundred KB). The server reads it and never serves it; it is removed with its page folder, and an older
  Limn ignores it, so going back to 0.4.2 needs no cleanup (its first rebuild can dash the pins of such a document once, the upgrade's effect in reverse).

## 0.4.2 — 2026-10-01

The viewer's layout now depends on the input device and, on touch, on the screen's height and orientation. A mouse
window is unchanged: it still picks its layout from the width alone (phone sheet up to 700 px, the panel up to 1099 px,
the desktop from 1100 px). Nothing changes in `pins.md`, the API or the state directory; the browser keeps one new
optional preference, `pinPrefs.sheetFTab`.

### Changed

- **Landscape phones** (touch, at least 600 px wide and under 480 px high). One 44 px row on top holds the document
  links and [선택] [⋯] [핀 N]; the bottom action row is gone and [PDF 재빌드] moves into [⋯]. The composer puts the note
  right after the location line, as on the phone sheet. While a note field has focus the row hides, so the whole note
  stays visible above the keyboard.
- **Portrait tablets** (touch, at least 480 px high: 600–839 px wide in either orientation, and 840–900 px wide in
  portrait only; a square window counts as landscape). The pin panel is a bottom sheet under the
  navigation row, opening at 45% with its own remembered height, instead of an overlay that covered the right part of
  the page; the outline opens as an overlay, one at a time with the sheet. While you write a pin the sheet stays at 45%,
  so the page you just selected on stays in view; with the keyboard up it rises only as far as the location line, the
  note and the save row need, never above 60%. The phone sheet still rises to 80% while composing.
- **Touch tablets 1100–1366 px wide** (an 11-inch iPad in landscape). They use the side panel with a bottom action row
  and folded cards instead of the desktop layout with touch-sized buttons. Only touch screens wider than 1366 px get
  the desktop layout, and there the outline starts collapsed until you open it.
- **Rotation and folding** change the layout once, after the size has held for 200 ms; the layout does not change while
  a text field has focus (the keyboard is up), so a note being written keeps its place. A mouse plugged in or removed
  switches the layout the same way.
- **Fixes.** The edit card keeps its focus and selection when the list is redrawn; the mid panel handle and the wide
  outline handle answer a 44 px touch.

## 0.4.1 — 2026-10-01

A tighter viewer on phones and tablets. Nothing changes in `pins.md`, the API or the state directory, and the layout
bands are unchanged.

### Changed

- **Touch sizes.** Every touch control has a hit area of at least 44×44 CSS px, while the drawn controls are tighter:
  card actions 32 (phone) or 36, tool bar 40, primary buttons 44. Touch text is never under 12 px. The wide layout
  keeps its controls out of the safe-area insets.
- **Phone composer.** The note comes second, right after the location line, so it stays visible above the keyboard;
  the overlap notice is one line and the sheet rises to 80% while composing.
- **Phone sheet header.** The handle sits in the tool bar row, so it no longer takes the top of the buttons; the
  header is 80 px instead of 129.
- **Compact card row** (phone and tablet widths). `#N · L… · 쪽` is the link that shows the pin, replacing [보기];
  [수정], [풀기] and [삭제] are icon buttons with labels for screen readers; [답글] and [완료] keep their names. The
  keyboard order follows the order on screen. No new confirmation and no extra menu.
- **Tablet chrome.** The section strip is hidden at mid widths and the page count moves to the navigation row;
  [더보기] opens as a bottom sheet and the touch help is shorter.

## 0.4.0 — 2026-10-01

Figure documents: a figure set drawn by code (one PDF page per figure plus a `limn-figure-map/1` element map) opens as a
tab. A drag is traced to the element and the lines of the script that drew it, a pin records its element, and its mark
follows the element across re-renders. The agent contract grows (new fields and new values in existing lists); one
field changes its value for figure documents (below). For an instance without figure documents `pins.md`, the API and
the state directory are unchanged, with these exceptions: the grown value lists and the `bad_via` and `bad_scope`
sentences that list them, the wording of the `no_source_lines` and `view_only_no_rebuild` refusal sentences (same
reason codes), anchors of `.py` sources skipping `#` comment lines, non-finite stored numbers reading as `null`, and the
three retired `/favicon-dark*` icon paths (below).

### Added

- **Figure documents in the viewer.** A figure document is marked `그림` on the documents sheet (the desktop document
  links name it in their tooltip) and has no [PDF rebuild]; rebuild is shown only for documents whose `kind` is
  `"tex"`. A drag snaps the pending box onto the element the map
  chose and names it in the location line (`B2 › 달력 › 7월 · B2_calendar.py L88-L95`); the range ladder runs from the
  element up through its ancestors to the whole figure without asking the server again, and the selected rung's
  element is the one pinned. Saving and re-placing send the element as `el` with its box, and that box as the pin's
  `frac`. A figure pin's mark follows its element across re-renders (`mark`, `mark_page`) and is solid while the
  element is found; a lost element's mark stays where the pin was placed, in the warning colour and dashed (`.est`), and
  the card shows `요소 잃음` like a lost line. The location-uncertain badge keeps its text `위치 불확실`; for a pick the map made,
  its tooltip says `지도로 찾음`. A figure region is labelled `코드 없는 요소` (element without code lines) or `영역`
  (map unreadable), not `보기 전용`. A long-press on a figure picks the element under the finger. A `null` box from
  the API draws no mark.
- **Figure pins.** A drag on a figure document is traced through its build's element map: `POST /api/pick` answers the
  lines of the drawing script with `via: "map"`, the element ladder (`levels` `el`, `el2` … `el8`, `fig`) and the
  element `el` (`id`, `path`, `label`, `part`, `impl`, `frac`). An element drawn without code, or a figure whose map
  does not load, answers the region with a `warn` that leads with the reason (there is no reason code field), and
  with `el` when an element was chosen. Pins take the optional `el` (`POST /api/pin`, an edit's `loc`); a malformed
  one is `400 bad_el`. Figure documents take line pins: an agent's `curl` with only a file routes to the document
  whose folder holds the file most deeply; at equal depth a `.tex`, `.bib`, `.sty`, `.cls` or `.bst` file (any case)
  goes to the LaTeX document and any other file to the figure document.
- **Read-time element position.** `GET /api/pins` adds `mark`, `mark_page` and `el_sync` (`ok`/`moved`/`lost`) to a
  figure pin, computed on the build on screen; nothing is written and a re-render never changes `rev`. A pin without
  any recorded box is never `ok`. Each build's map copy is parsed once per run.
- **`pins.md` figure rows.** The element's `«label»`, `공통 부품: file:lo-hi` and `요소 잃음`, and one guidance clause
  while figure pins are open. A figure document always gets its own section, also when it is the only document; the
  title ends with `— 그림(요소 지도)` and its `기준:` line reads `· 그림 <built_at>`. The view-only title is unchanged.
  The file on disk is also rewritten when a figure import puts a new build on screen, so `요소 잃음` follows the map
  on screen without a pin write (`pins.jsonl` and `rev` are untouched; a failed rewrite keeps the old file).
- **Value lists grow as ADR-0011 decided.** `via` gains `map`, `scope` gains `el`…`el8` and `fig`, pin `kind` gains
  `el:<part>` and `figure`. The `bad_scope` and `bad_via` sentences list the new values; their reason codes are
  unchanged.
- **Anchors of Python sources skip `#` comment lines** (the file suffix `.py`, any case; LaTeX anchors are unchanged).
- **SKILL (en/ko)** teaches figure pins: edit the lines, ask about a shared part by replying on the open pin,
  re-render in the figure repository and commit before closing, `요소 잃음`, the `.limnmap.json` path in `--doc`, and
  rebuilds only for documents whose `kind` is `"tex"`.

### Changed

- **A figure document's `view_only` is `false`.** 0.3.8 reported `view_only: true` in `/api/docs` and `/api/meta`,
  when its picks and pins were regions. Figure documents now take line pins, and `view_only` is the absence of line
  pins. `kind` is still `"figure"`, `POST /api/rebuild` still answers `400`, and the region answer of a figure pick
  that finds no lines still carries `view_only: true` (it names that answer, not the document).
- The refusal sentences of `no_source_lines` (lines sent with a region pin, in a new pin or an edit) and
  `view_only_no_rebuild` no longer call the document "view-only", since a figure document meets them too. Their reason
  codes are unchanged.
- `GET /api/snippet` no longer refuses a figure document; with `levels=1` it gives the `raw` rung alone.

### Fixes

- **No NaN or Infinity in a pin response.** A stored number that is NaN, an Infinity or an integer no float holds (a
  hand-edited or legacy line) reads as `null` in every pin response, including the `claim_until` and `eta_ts` of a
  `409 claimed`. A `frac` or `el.frac` with any such entry is `null` as a whole, since a box built from the finite
  entries would put the mark at a made-up position. Every other number (`synced_at`, `score`, `claim_until`,
  `claim_ts`, `eta_ts`, and numbers inside `anchor`, `thread` or a field this version does not know) is `null` one by
  one. The stored line is untouched. `pins.md` no longer fails for a region pin with such a `frac`, which had failed
  every later pin write.

### Removed

- **`/favicon-dark.ico`, `/favicon-dark-16.png`, `/favicon-dark-32.png`.** 0.3.8 announced them as deprecated, serving
  the same bytes as the paths without `-dark`; they are gone now and answer `404` like any unknown path. A tab still
  open on a 0.3.6-0.3.7 page in a dark colour scheme shows no favicon until the page is reloaded; the current page
  links only `/favicon.ico`, `/favicon-16.png` and `/favicon-32.png`. `pins.md` and the state directory are unchanged.

### Rollback

- Rolling back to v0.3.8 keeps every figure pin: its store reads each figure record and writes it back byte for byte
  (`tests/contracts/test_figure_rollback.py`, which also covers v0.3.5 and v0.3.7). v0.3.8 serves figure documents, so
  their `--doc` entries can stay; how its viewer shows a line pin on a figure document was not tried. v0.3.5 and
  v0.3.7 do not know figure documents: remove the figure document from `--doc` first.

## 0.3.8 — unreleased

A larger browser favicon, and figure documents arrive in part. `pins.md` and the state directory are unchanged; the
three `/favicon-dark*` icon paths are deprecated (below).

### Favicon

- **One 먹 favicon for light and dark tabs.** On a light tab the 뼈종이 tile had almost the tab's colour (ΔE 8), so
  the favicon read as a 2 × 9 px i next to other sites. The tab favicon is now its own drawing: the i (미색 stem, 주
  pin) on a 먹 rounded square that fills the whole 16 px square, as 16 and 32 px pixel drawings from limn-sans
  (`LIMN.favicon`). `/favicon.ico`, `/favicon-16.png` and `/favicon-32.png` serve it; `<head>` links one set,
  without `media=` and without the colour-scheme script. The home-screen icon (`/apple-touch-icon.png`) and the
  in-app marks are unchanged.
- **Deprecated: `/favicon-dark.ico`, `/favicon-dark-16.png`, `/favicon-dark-32.png`.** In 0.3.8 they serve the same
  bytes as the paths without `-dark`, so tabs still open with a 0.3.6-0.3.7 page (whose script switches a dark tab
  to them) show the new favicon. They are removed in the next release.
- Rolling back to 0.3.7 is safe: nothing is stored.

### Figure documents

Figure documents arrive in part: they register, import and pick as regions, and `/api/docs` and `/api/meta` gain the document kind `figure`.

### Added

- **Figure documents: registration and import.** A `--doc`/`DOCS=` entry whose path ends in `.limnmap.json` serves
  a figure document: the PDF a figure repository renders, plus its element map (`limn-figure-map/1`, Handbook
  api.md). `ROOT::path/figures.limnmap.json` sets the folder the map's source paths are relative to; without `::`
  it is the map's folder. The watch imports the pair only when the map's `pdf_sha256` is the PDF's SHA-256, renders
  exactly the bytes it checked, and keeps the map in every page directory. While the two disagree (the producer has
  written one and not yet the other), nothing is built and no failure is recorded. `/api/docs` and `/api/meta`
  report `kind: "figure"` with `view_only: true` (ADR-0011 D5: the document kind value list grows). Picks and pins
  on a figure document are region pins named after the map's PDF, and `POST /api/rebuild` answers `400`. A missing
  map refuses startup, like a missing view-only PDF. Existing documents, fields and `pins.md` are unchanged.

## 0.3.7 — unreleased

One internal refactor; the HTTP API, `pins.md` and the state directory are unchanged.

### Internal

- **Internal: document kinds are read through capabilities.** `Doc.kind` is the closed type `DocKind` (`"tex"`,
  `"pdf"`) and the boolean `is_pdf` is gone: every branch asks what a document can do - `builds_from_source`,
  `watches_files`, `takes_line_pins`, `shows_revisions`, `view_only`. No change to the HTTP API, `pins.md`, the state
  directory or the command line; the move was checked by a differential run against the code before it.

## 0.3.6 — unreleased

The confirmed Limn logo, security boundary hardening, closed security types, one documented trust assumption, server and
viewer fixes and an internal restructuring. `pins.md` and the HTTP API's fields are unchanged; the API adds four icon
paths and `/favicon.ico` now answers an icon instead of `204`. Ambiguous requests now receive explicit rejection
reasons, the responses gain two headers and page images change their `Cache-Control`.

### Logo

- **The confirmed Limn logo replaces the first-draft mark.** The app icon (the letter i, a stem and a vermilion pin, on
  a squircle tile) and the wordmark "limn" come from the brand source (dartworklabs/limn-sans, `make icons`) and are
  vendored byte for byte in `src/limn/brand/` with their `SHA256SUMS` and provenance; nothing is drawn at run time any
  more, and the standard-library PNG drawer is gone. See `docs/handbook/viewer.md` §마크와 파비콘.
- **Tab favicons follow the browser's colour scheme.** The 16 and 32 px pixel drawings, 뼈종이 in a light scheme and 먹
  in a dark one: `GET /favicon.ico` and the new `GET /favicon-dark.ico` (16 + 32), `GET /favicon-16.png`,
  `GET /favicon-32.png` and the new `GET /favicon-dark-16.png`, `GET /favicon-dark-32.png`. The links choose by
  `media`, and a small head script points every icon link at the current scheme's file for browsers that ignore it.
  `GET /apple-touch-icon.png` (also the browser notification icon) is the 180 px 뼈종이 icon, square to the edges. The
  links carry `?v=<content key>` instead of `?c=<accent>`; the accent-coloured SVG favicon is gone.
- **The favicon no longer carries the instance colour.** Tabs of different instances are told apart by their title
  (`Limn · <label>`); the accent still colours the top stripe and the label chip.
- **In the viewer** the top bar (16 px) and the [More] label chip (14 px) show the icon, the help header shows the
  wordmark 20 px tall in place of the word Limn. 뼈종이 tile and 먹 strokes in the light theme, 먹 tile and 미색 strokes
  in the dark theme, the pin 주 in both, from new brand tokens (`--limn-ink`, `--limn-ver`, `--limn-bone`,
  `--limn-cream`, `--mark-tile`, `--mark-stroke`).
- Rolling back to 0.3.5 is safe: nothing is stored; 0.3.5 serves its own page and icons again.

### Security

- **Ambiguous requests fail closed.** Duplicate JSON keys (including nested keys), non-finite numbers and lone
  Unicode surrogates are rejected as `bad_json`. Repeated decoded query keys and malformed URL encodings are
  rejected as `bad_query`. Duplicate singleton security headers are rejected as `duplicate_header`, while duplicate
  Authorization and Content-Length retain `bad_bearer` and `bad_content_length`. Even identical duplicates are
  rejected. Clients should send each key/header once; ordinary single-value requests and successful responses are
  unchanged. Invalid transport input no longer records the person before rejection.
- **Mutation authority is explicit.** Registered operations must be explicitly authorized; new routes cannot
  inherit owner/editor/agent permissions accidentally. Services consume authority bound to the operation, target
  and server instance, rather than treating an attribution dictionary as permission.
- **Manuscript reads retain their checked scope.** Checked file handles enforce root, hidden-file and state-folder
  exclusions at reads, including rejection of symlink replacement after validation.

- **Dot-named files are not manuscript.** `GET /api/snippet`, `GET /api/overlaps`, `POST /api/pin`, an edit's `loc` and
  a close's `changes` accepted any regular file under `--manuscript`, so any admitted principal, a `viewer` too, could
  read `.git/config` or `.env` (`/api/snippet?file=.git/config&lo=1&hi=80`). A path whose part below the manuscript,
  symlinks resolved, has a component starting with `.` is now outside the tree, refused with the existing
  `400 file_outside_manuscript` / `change_outside_manuscript` and the same message. A stored pin or change pointing
  there is no longer located (it becomes a pin outside the tree), so its lines are never read again. A manuscript file
  that itself lives under a dot folder can no longer be pinned; `a.b.tex` and a `--manuscript` under `~/.local` are fine.
- **A state folder inside the manuscript is not manuscript.** With `--state-dir` inside `--manuscript` under a normal
  (non-dot) name, the same routes could read the state files: `people.json`, `tokens.json` (hashes), `audit.jsonl`,
  `events.jsonl` and the pin files. Every path in the state folder, symlinks resolved, is now outside the tree, with
  the same `400 file_outside_manuscript` / `change_outside_manuscript` and message; a stored pin pointing there is no
  longer located. The build copy no longer copies the folder (it used to nest its own `build/` one level deeper on
  every build). Such a start prints one warning on stderr; a state folder that holds a served document's main file
  (`--state-dir` = `--manuscript`, say) refuses to start, since that document could take no pin. The default state
  folder lies outside the manuscript and is unaffected.
- **Security values are closed types.** Roles, identity providers and how a principal was identified are `Literal`
  types parsed once at the boundary (`people.json`'s `role`, `--auth`, `limn member`), so a mistyped comparison fails
  `mypy`; an unknown role still reads as `viewer`. The handler's two role questions (is a reply a person's, does a
  close go to review) moved into `limn/access.py`. No behaviour change.
- **An unusable `people.json` fails closed.** A `people.json` that existed but could not be read or parsed was read as
  empty: everyone got the default role (`editor`, so a `viewer` gained edits), and the next visit rewrote the file with
  only the visitor, erasing every role including the owner's. Now every header-identified person is a `viewer` while it
  is unusable, `--members-only` admits only `--allow` logins, the server never rewrites the file and warns once on
  stderr, and fixing the file (content or permissions) restores the roles on the next request. A document that is not
  `{"people": [...]}` counts as unusable for the server too (before, only `limn member` refused it). Tokens and the
  `--auth local` owner are unaffected.
- **No framing.** Every response carries `X-Frame-Options: DENY` and `Content-Security-Policy: frame-ancestors 'none'`
  (that directive only; scripts are not restricted). Page images (`/pages/page-N.png`) are now
  `Cache-Control: private, max-age=600` instead of `public`, like the PDFs.
- **Trust assumption documented.** The main LaTeX build runs `latexmk` without `-norc` or a sandbox, so a repository's
  `latexmkrc` runs with the server's rights, and with `--git-pull` a push to `main` is built within a minute. SECURITY.md
  and build-sync.md now say so: the manuscript repository is trusted code; comparison builds are sandboxed, the main
  build is not. No behaviour change.

### Fixes

- **New-pin notices name the pin's own document (fix).** On an instance started with several `--doc`, the `mention`
  and `assigned` records a new line pin writes to `events.jsonl` carried the first document's key in `doc`, because
  they were made before the record had its `doc`; a notice about a pin in the second document opened the first one.
  They now carry the pin's document, like every other notice. Region pins, single-document instances and the other
  fields are unchanged; records already written are left as they are.
- **No '등록된 사람이 아님' while a name is still being typed (fix).** The 2026-09-25 QA fix that holds the warning
  for the `@word` under the caret had stopped running: a later edit left its statement at the end of a `//` comment in
  `mentionPreview`. It runs again, and a test now fails when a viewer `//` comment ends in code.
- **The viewer reads @-tags exactly as the server does (fix).** The preview line, the reply outcome and the assignee
  choice now find the same people the server records ([viewer.md](docs/handbook/viewer.md) §@태그). A person whose name
  or first word equals their login's local part (`Bob`, `bob@example.com`; `@Alice` for `alice@example.com`) was shown
  as nobody, and an `@` right after a non-ASCII letter (`é@rlee`) was shown - and rendered in cards - as a tag the
  server skips. The assignee row resolved the note with every login ever picked in the field instead of the hints the
  save sends, so a pick edited down to a shared first word saved a pin handed to someone its note did not tag. A shared
  corpus (tests/test_mentions_parity.py) now runs through both resolvers.

### Internal

- **Internal: the server is split into modules.** No change to the HTTP API, `pins.md`, the state directory or the
  command line; each move was checked by a differential run against the code before it, in a separate process.
  - `src/limn/server.py` is only the composition root: the run settings, the document list, the per-process locks and
    caches, one-line wirings and the startup steps. The logic lives in modules of their own - the pure pin domain
    (`limn/pins/`), the pin services (`limn/service/`), the pin store, build, location, access control, startup, and
    the HTTP layer (`limn/web/`).
  - Pin states are types (`OpenPin`, `ReviewPin`, `DonePin`, `TrashedPin`) that carry only their own fields; records
    are still read and written byte for byte as before, guarded by a round-trip corpus of every record shape.
  - Expected refusals are return values (`confirm()` returns `DonePin | AlreadyDone | PinStillOpen`); the HTTP layer
    answers them with the same statuses, bodies and `reason` codes. Identity, admission and role checks still raise, so
    a caller cannot miss a refusal.
  - Request bodies and queries are parsed in `limn/web/parse.py`; there is no thread-local "current document" any more,
    the handler passes the request's document to every service.
  - The viewer's page, styles and scripts are build-free files in `src/limn/viewer/`, joined in `parts.txt` order into
    the same single HTML page.
  - New gates: Ruff lint and `ruff format --check`, ShellCheck, strict mypy over the whole package, `node --check` of
    the viewer scripts, and a snapshot test of `pins.md` and the main API answers for one fixed pin flow.
  - The Handbook states the current design only; `docs/handbook/code-style-roadmap.md` now holds the coding rules
    R1–R10, and a test checks that Handbook section references and paths resolve.

## 0.3.5 — unreleased

Mouse and touch usability from the 2026-09-26 input review ([viewer.md](docs/handbook/viewer.md) §패널 폭과 시트 높이,
§펼친 화면 레이아웃, §모바일 레이아웃). Viewer only: the HTTP API, `pins.md` and the state directory are unchanged; the
browser keeps two new preferences (`pinPrefs.sideClosed`, and the `side`/`mouse` hints in `pinPrefs.coach`) and a
per-tab draft (`sessionStorage` `limnDraft:<label>:<doc>`).

- **Collapse the panel by its handle, in every layout.** Drag it right: the width follows down to the minimum, stops
  there between half the minimum and the minimum (the bar turns primary), and below half the minimum the panel's
  contents fade to 40% as a preview; a release collapses it with a 0.18s slide, keeping the drag-start width as the
  saved width. A draft (composing, editing, replying, relocating) stops the drag at the minimum instead. The wide panel,
  which could not be closed before, leaves a 6px rail at the right edge (drag it back or double-click it), shows
  `[핀 N ‹]` at the right end of the nav bar, floats the status chips and toasts at the PDF area's bottom-right, and
  opens again for a pick, a mark, a pin link, the review list or an in-text `#N`. Remembered per device
  (`pinPrefs.sideClosed`).
- **Keys.** The handle follows the WAI-ARIA window splitter: Enter collapses and expands, Space cycles the presets,
  Home = minimum, End = maximum (they were reversed); collapsed = `aria-valuenow` 0. `Ctrl/⌘+\` toggles the panel (or
  the phone sheet) at every width outside text fields. Esc closes the 701-900px overlay after a selection, and returns
  from [변경 보기] to the manuscript.
- **Touch.** Swipe the 701-900px overlay right to dismiss it (35% of its width or a fling; a draft only rubber-bands).
  Drag the phone sheet by its whole tool bar, or pull its content down at the top; a downward fling collapses it, an
  upward fling goes to the next height, and a draft stops it at 30% instead of hiding the note. The system back
  gesture closes the sheet, the overlay or the mid outline first (CloseWatcher, else one history entry), and a right
  swipe no longer navigates back out of Limn. A double tap on the PDF toggles fit width and 2x. The click that used to
  follow a handle tap or a quick pick and land on the panel under the finger is swallowed. The documents sheet and help
  close on an outside tap; the documents sheet also follows a pull-down.
- **Undo instead of loss.** Esc or [취소] on a selection with a written note offers `선택 취소됨 · [되돌리기]`, which
  brings back the selection, the note and the box; [되돌리기] after saving a pin also reopens the composer with them.
  The composer draft is also kept per tab in `sessionStorage` (per instance and document, written on every edit): a
  reload, or leaving Limn with a second back gesture and coming back, restores it with `작성 중이던 메모를 되살렸습니다 ·
  [버리기]` (only the note when the PDF was rebuilt meanwhile). Saving clears it; a discard clears it after its undo window.
- **Smaller things.** Mouse hit targets reach 24x24 (WCAG 2.5.8) without changing what is drawn; the PDF shows a
  crosshair and a first-time mouse user gets one hint; a pick in the overlay's right column is no longer hidden
  under the panel; the handle's tooltip hides when the drag starts; more than three toasts get a button that opens
  the stack on touch.
- Rolling back to 0.3.4 is safe: it ignores `pinPrefs.sideClosed` (a wide panel just opens).

## 0.3.4 — unreleased

English error messages, a Limn mark, and the two ADR-0006 follow-ups of
[issue #24](https://github.com/dartworklabs/limn/issues/24). The `pins.md` format and the stored pin record are
unchanged. The HTTP API adds one field to every error body and two icon routes.

- **Every error body names a stable reason code (API, additive).** Error responses are now
  `{"error": "<Korean text>", "reason": "<code>"}`; the Korean text is unchanged byte for byte. The 409 bodies whose
  `error` is already a code (`done`, `conflict`, `open`, `full`, `claimed`) repeat it in `reason`; the comparison PDF
  status and the `200` refusals of `POST /api/pick` use the same codes. `HTTPError` cannot be built without one. The
  codes are listed in `docs/handbook/api.md` §오류 응답; agents should branch on `reason`, not on the text.
- **The English viewer shows API errors in English.** One function, `errText()`, shows every API error: Korean shows
  the server text as before; English looks up `reason:<code>` in `ui_en.json` (one message per code, tested) and falls
  back to the server text. It covers the error toasts, the pick error in the composer and the re-place banner, the
  edit card's source box and the comparison PDF status line. The composer's pick warning (a UI hint the server composes
  from up to three Korean sentences, not an error body) is shown in English too, sentence by sentence. The English chrome test now drives the common refusals
  (403 view-only, 409 `base_rev` conflict, 400 validation, 404 pin, 422 pin scope) and checks the toasts carry no
  Hangul; the Korean run checks they show the server text unchanged.
- **The Limn mark.** One stroke that starts at a small dot (the pin) and runs into a line (the source line). It replaces
  the label's first letter in the favicon, sits before the instance label in the top bar and the [More] label chip (in
  the instance colour) and in the help dialog header (monochrome, follows the theme). Inline SVG coloured by CSS
  tokens; the geometry lives once in the new pure module `limn.mark`, which also draws the PNG fallbacks at runtime with
  the standard library (`GET /favicon-32.png`, `GET /apple-touch-icon.png`, keyed by `?c=<accent>`). Browser
  notifications use the 180px PNG (Android draws no SVG icons).
- **[View changes] keeps the recorded lines after a move (issue #24 §1).** The absolute paths in a closed pin's `changes`
  are located on read by the ADR-0006 rule, so a moved or cloned checkout still reports `source: "changes"` instead of
  inferring the hunks. The stored `changes` and the API's `changes[].file` are unchanged; a path that cannot be placed
  is dropped as before.
- **Tails stay in the pin's own document (issue #24 §2).** For a moved record without `file_rel`, the longest existing
  tail is searched in the pin's document folder (its build root) instead of the whole manuscript folder, so a
  same-named file of another document is never picked, and a document folder renamed with its `--doc` spec is followed.
  Instances started without `--doc` behave as before (a single `--doc` pointing at a sub-folder searches only it). No
  write migration.
- Rolling back to 0.3.3 is safe: nothing new is stored, so 0.3.3 reads the same state directory. Its error bodies
  simply have no `reason`, and it serves its own page and favicon.

## 0.3.3 — unreleased

Agents on the machine that serves an instance get a standard place for their token, so the instance can turn off
the deprecated headerless loopback agent (decision record [ADR-0007](docs/adr/0007-agent-token-file.md)); the
instance manager also runs on macOS semantics ([issue #12](https://github.com/dartworklabs/limn/issues/12)). The
`pins.md` format and the HTTP API change only by addition: one clause at the end of the agent-auth line once a token
file exists, and a hint after the existing text of one `401`. The state directory is unchanged.

- **Token file.** `limn token create <instance> --save` writes the new token to `~/.config/limn/<instance>.token`
  (the instance config folder, `LIMN_CONFIG_DIR`; never the `LIMN_SOURCE_DIR` copy): mode 0600, a missing folder
  made 0700, the token not printed unless `--print`. It refuses an existing file (`--force` replaces it atomically and
  names the replaced token if it is still valid) and a folder inside a git work tree that does not ignore the file
  (even with `--force`). Every refusal comes before the token exists; a failed write revokes the new token.
  `limn token path <instance>` prints the path, `limn token list` says which token the file holds, and
  `limn token revoke` removes the file when it held the revoked token.
- **Server (additive).** `--agent-token-file` (default `LIMN_AGENT_TOKEN_FILE`, which `limn run` sets; no new argv, so
  a config without access keys still runs the v0.1 argv) tells the server where the file is. It only checks that the
  file exists, never reads it. Then pins.md's agent-auth line ends with
  `` 이 기기의 에이전트는 토큰 파일을 붙인다: `curl -H "Authorization: Bearer $(cat ~/.config/limn/<instance>.token)" …`… ``
  (not for a remote `GET /pins.md`), and with the loopback agent off a headerless local request gets `401` whose
  text is the old message followed by where the token file is (a proxied request keeps the old text).
- **Instance manager.** `limn status`, `list`, and the waits in `start`, `update` and `doc … --restart` send the
  token file (on curl's stdin, never its command line), so they keep working with `AGENT_LOOPBACK=0` - and only when
  every listener on the port is this account's (`/proc/net/tcp` on Linux, `lsof` on macOS), so another account holding
  the port while the instance is down never receives it. A `401` is
  reported with the command that fixes it and ends the wait at once instead of running out `LIMN_WAIT`. A token
  file that is a symlink, belongs to another account, is open to group/others, or is not one token line is not used
  (a warning says why). `limn snippet` tells agents on the serving machine to use the token file.
- **macOS.** `instances.sh` checks that its Python is >= 3.10 (`LIMN_PYTHON` too old is an error; run directly it
  takes the first new-enough `python3`/`python3.1x`, not macOS's 3.9 `/usr/bin/python3`), reads `stat` fields on
  GNU or BSD, and bounds `limn update`'s tag lookup without `timeout(1)` (`gtimeout` or `perl`). The tests follow:
  `test_instances.sh` picks a Python >= 3.10 and a portable `stat`, and `test_cli_env_parsing_matches_instances_sh`
  no longer relies on `source <(…)`, which sources nothing in macOS's bash 3.2. CI gains a `macos` job (Python
  tests without TeX/Chromium, the instance manager under `/bin/bash` 3.2).
- **Rollout per instance:** install 0.3.3, `limn token create <instance> --name <name> --save`, switch the paper
  repository's AGENTS.md to `limn snippet <instance>`, then `AGENT_LOOPBACK=0` and restart.
- Rolling back to 0.3.2 is safe: it neither sets nor reads `LIMN_AGENT_TOKEN_FILE` and ignores token files; with
  `AGENT_LOOPBACK=0` its `limn status` shows `401` again and its start wait runs out `LIMN_WAIT`, while the server and
  token-using agents behave the same.

## 0.3.2 — unreleased

Pins follow a moved manuscript ([issue #7](https://github.com/dartworklabs/limn/issues/7), decision record
[ADR-0006](docs/adr/0006-relative-pin-paths.md)). The stored pin record gains one optional field. The
HTTP API adds one computed field, and `file` in responses now names the file where it is now. The `pins.md` format is
unchanged.

- **`file_rel` (stored, additive).** When the server creates, edits (note, range or relocation) or restores a pin, it
  also stores the file's path relative to `--manuscript` (`sections/intro.tex`) and rewrites `file` as the current
  absolute path. Records written earlier are **not** rewritten to add it (no write migration), not even when another
  write touches the file.
- **Locating a pin's file (every read).** The stored `file` if it lies under the current manuscript folder; else a
  `file_rel` that the stored `file` ends with (a stale one left by a 0.3.0 relocation is ignored; a longer existing
  tail of `file` wins, for a widened folder); else, for older records, the longest tail of `file` that exists under
  the folder (the rule `to_source()` uses for SyncTeX paths), never with `..` parts. The result must still resolve
  inside the folder, so a symlink cannot lead out. Pins that cannot be located stay outside the tree exactly as
  before: no line re-sync, no range edit, no quote, nothing read.
- **Line re-sync of a moved record.** Its `synced_at` was measured on another file, so the mtime shortcut is taken only
  while the anchor's head is still at the recorded line; a re-match also writes the located path into `file`, so the
  lines and `file` describe one file (switching back to an old checkout follows its lines again). No anchor is
  backfilled from a located file.
- **What changes after moving a checkout.** Pins keep following edits via their anchor, `/edit` with `lo`/`hi` works
  (it was `400`), `pins.md` keeps `sections/x.tex L12-L18` and the long-line `«…»` quote, overlaps join pins made
  before and after the move, and [View changes] uses the current path.
- **API (additive).** Pin responses carry a computed `rel_path` (old records too) and `file` is the absolute path
  valid on this machine now (the stored value when the pin cannot be located). The stored `file_rel` is not returned.
  The issue's suggested name `rel` is already the overlap list in `GET /api/pins`.
- `/edit` checks a `note_append` that would exceed the note limit before changing anything (a 400 could leave a
  partial edit when the same write re-synced lines).
- Not covered: the paths inside a closed pin's `changes` stay absolute (after a move, [View changes] infers the hunks),
  and view-only PDF pins keep their `pdf` path (they are found by document key). Follow-ups:
  [issue #24](https://github.com/dartworklabs/limn/issues/24).
- Rolling back to 0.3.1 (or 0.3.0) is safe: both ignore `file_rel` (and never return a `rel_path`), records
  rewritten by 0.3.2 carry a current `file`, and untouched records look exactly as they did before the upgrade.

## 0.3.1 — 2026-09-26

Two low-severity findings of the v0.2.1 security review ([issue #10](https://github.com/dartworklabs/limn/issues/10)).
The `pins.md` format and the HTTP API are unchanged. One notification behaviour changes; the state directory gains two
files once something is audited (`audit.jsonl` and its lock `.audit.lock`).

- **Note mentions have a ten-minute cooldown (L3).** A note save, edit or `note_append` that tags someone again sends
  that person a `mention` at most once per ten minutes per (editor, person, pin) (`NOTE_MENTION_COOLDOWN_S` = 600 s).
  Toggling `@Bob` off and on through repeated edits used to notify Bob on every edit. Suppressed mentions are not
  written; the pin's `mentions` field still follows the note. Replies and reopen reasons still notify every time.
  The rule reads `events.jsonl`: a `mention` without `msg` came from a note.
- **Audit log (L5).** Destructive and owner actions are appended to `<state_dir>/audit.jsonl`, one
  `{at, ts, action, by, via, details}` per line: `cleared` and `purged` from the server (`via: "http"`), and
  `token_created`, `token_revoked`, `member_added`, `member_role`, `member_removed` from `limn token` / `limn member`
  (`via: "cli"`, `by` = the OS account that ran the command). Limn only ever appends to it (never truncated, unlike
  `events.jsonl`, which keeps the newest 5000 and could rotate the `cleared` record out), under a cross-process lock
  (`.audit.lock`), mode 0600, no symlinks followed. Token lines carry the id and name, never the token or its hash.
  A failed audit write is a warning; the action stands. The `cleared` and `purged` events are still written.
- Rolling back to 0.3.0 is safe: 0.3.0 never opens `audit.jsonl` or `.audit.lock`, and the cooldown keeps no state
  of its own.

## 0.3.0 — 2026-09-26

Pin-scoped [View changes] ([issue #9](https://github.com/dartworklabs/limn/issues/9), decision record
[ADR-0005](docs/adr/0005-pin-scoped-changes.md)). The HTTP API changes are additive. One `pins.md` line changes: the close
instruction; everything else in `pins.md` is byte-for-byte the same.

- **Agents: always send `changes` (agent-visible).** The close instruction in `pins.md` and the skill now ask agents to
  close with `changes` (the lines changed for the pin, numbered as in the commit `ref` names — after a squash merge, the
  merged `main`) and `ref` = `PR #<n> (<commit hash>)`. Committing each pin separately helps but is not required; PRs may
  be squash-merged. Nothing enforces it; old agents keep working.
- **`changes` on close (additive).** `POST /api/pins/{id}/close` takes an optional `changes: [{file, lo, hi}]`, the
  new-side line ranges the agent changed for this pin (`file` relative to the manuscript folder like the `pins.md`
  location column, or absolute inside it). Invalid shapes are `400` and change nothing; `[]` is the old close. Stored on
  the pin as `changes` (absolute paths, with `changes_at` = that close's `done_at`) on the first close, kept on re-close,
  cleared by reopen; exposed in the pins API.
- **Inference for everything else.** For a pin without `changes` (or whose `changes` hit nothing in the commit) the
  server picks the commit's hunks that overlap the pin's range mapped through the commit (its anchor on the new side,
  else the old side; renames followed). If nothing overlaps, the view is the whole commit, as before.
- **API (additive).** `GET /api/revision-diff?pin=<id>` adds `scope: {pin, mode, source, hunks, other, diff, other_diff}`;
  `POST /api/revision-build` accepts `pin` in its body, and `GET /api/revision-build` / `GET /api/revision-pdf` accept
  `&pin=`; build statuses add `scope`, `pin`, `source`, `hunks`, `other` (never stored, so responses without `pin` stay
  as in 0.2.2); the scoped patches are cut at 256 KiB with `truncated` / `other_truncated`.
- **Viewer.** A pin's source diff shows only its hunks, with "N other changes in this commit ▸" folded below (expands in
  place). Its comparison PDF is old + only its hunks, run through the same bwrap latexdiff/latexmk pipeline and cached
  per (pin, commit, hunk set); one toggle [Whole commit] switches to the whole-commit comparison. If the pin's hunks
  alone do not compile, the whole commit is shown with a one-line note. A commit that is entirely the pin's looks as in
  0.2.2, with no extra control.
- Recorded `changes` count only on the commit `close_ref` names (hash, or the squash/merge commit found by PR number);
  on any other commit the view is inferred, and the viewer scopes only the commit it picked for the pin. The
  comparison cache is keyed by (commit, block set) and counts pin-scoped entries apart; transient read failures are
  not cached; symlink and submodule entries are never read as text.
- Rolling back to 0.2.2 is safe: 0.2.2 ignores the `changes` field, and the new cache entries expire on their own.

## 0.2.2 — 2026-09-25

One [Reply], a Trash, and collapsible list sections ([issue #8](https://github.com/dartworklabs/limn/issues/8),
decision record [ADR-0004](docs/adr/0004-one-reply-trash-sections.md)). The `pins.md` format is unchanged and the HTTP
API changes are additive. One agent-visible behaviour changes; it is listed first.

- **A person's reply on a closed pin reopens it (agent-visible).** `POST /api/pins/{id}/reply` decides by one server
  rule: a reply by a person on a pin awaiting review or done reopens it, and the reply becomes the reason
  (`ev:"reopen"`, exactly as `/reopen`), so the pin returns to the open table of `pins.md` with `다시 열림` and
  `다시 연 이유(<name>): <reply>`. A reply that @-tags a person keeps the state (that person gets a `mention`); replies
  on open pins and question pins never change state; an agent's reply (token, headerless loopback, agent role) never
  reopens by the rule. Optional `"reopen": true|false` overrides the rule (`400` if not a boolean); the response adds
  `reopened` and `state`. `/reopen` is kept.
- Viewer: the review card is `[변경 보기] [답글] [확인]` and a done row offers `[답글]`; the `[다시 열기]` buttons are gone.
  A line under the reply box previews the outcome ("Sending will reopen this pin for the agent", "Sending notifies Bob
  Park; state stays", …), with one rarely used override toggle: `[상태 유지]` (Keep state) where the rule reopens,
  `[다시 열기]` (Reopen) where it keeps the state. A reply is sent when its undo toast goes away, so `[되돌리기]` (Undo)
  takes it back before anyone sees it. Tagging an agent-role account is not tagging a person; a reopening reply still
  notifies everyone tagged on the pin before (`replied`).
- **Trash.** Deleted pins leave the list at once (with Undo) and live in `[⋯] → 휴지통 N` (desktop: a link under the
  list) for 30 days, with Restore. Older entries are hidden and purged at startup and on every drop/restore. New
  owner-only `POST /api/pins/{id}/purge` deletes one for good (`purged` audit event). When someone else deletes your pin
  you get a `dropped` notification with Restore. A `#12` that points at a deleted pin reads "#12 deleted pin".
  `GET /api/pins/dropped` adds the computed `expires_ts`. A long-running server also drops expired entries during
  `GET /api/pins` / `GET /pins.md` at most once an hour (the light poll stays write-free).
- Fixed (older than 0.2.1): on an instance with several documents, a `/#doc=<key>&pin=<n>` link lost the pin on load,
  so a notification clicked with no tab open did not open the pin. The boot now reads the link first; the `[되살리기]`
  action of a `dropped` notification opens the link with `&act=restore`, which restores the pin and opens it.
- Open pins, awaiting review and done share one collapsible header (click/Enter/Space, `aria-expanded`), remembered per
  device; done starts collapsed; a collapsed header shows "new N".
- Help defines a pin once: a place in the output + a request or question + its conversation.
- **What the preview says is what happens.** The preview and the request resolve @-tags with the same hints, so an
  autocompleted name edited down to an ambiguous first word previews the server's decision. The override is a switch
  whose label is the non-default outcome, and the preview still names who is notified when it is on; the placeholder
  follows the same outcome. A failed send reopens the box with the draft and an inline error; Ctrl+Enter moves focus to
  [되돌리기]. A `#…&pin=N&act=restore` link runs once (the address is cleaned at once).
- `pins.md`: one more additive line after the token line (`REPLY_GUIDANCE`): an agent sending as a person without a token
  sends `"reopen": false` with replies. The same note is in SKILL and api.md.
- Tests: `tests/test_v022.py` (the rule table, API, Trash with a fake clock, cold deep links, the real input pipeline from
  text and autocomplete to the server's decision, and browser flows on desktop, fold and phone in ko/en). Decision
  record ADR-0004 is accepted.

## 0.2.1 — 2026-09-25

Fixes from the end-to-end QA of 0.2.0. Two changes affect the agent contract; both are listed first.

- **Headerless requests through the tailnet address are refused (contract change).** Under `--auth tailscale`, a request
  without identity headers that came through `tailscale serve` (`Host` `*.ts.net` or a `--public-host`, e.g. from a
  tagged device) used to be treated as the loopback agent, which could do everything but confirm. It now gets `403`
  (a proxied request is recognised by a non-loopback Host or any `X-Forwarded-*`/`Forwarded` header, which
  `tailscale serve` always sets — Host alone can be spoofed because serve routes by the TLS name)
  with a hint to send a token, as 0.1 did when `--allow` was set. **Remote agents on tagged devices or CI must send
  `Authorization: Bearer <token>`**; agents on a machine signed in to the tailnet as a person keep working (they carry
  that person's identity and still send `"review": true` when closing), and loopback agents are unchanged.
  `--tailnet-agent` (`TAILNET_AGENT=1`) restores the 0.2.0 behaviour on purpose (logged as deprecated).
  Decision record: [ADR-0003](docs/adr/0003-tailnet-headerless-and-owner-clear.md).
- Hardening from the security review: `X-Real-IP`, `X-Forwarded-Port` and `Via` also mark a proxied request; under
  `--auth local` a proxied request is `403` instead of the owner; `people.json` is written `0600` and an older file
  that others can write is tightened at startup. A raw TCP forward that adds no header stays indistinguishable from a
  local request (SECURITY.md) — use tokens and `AGENT_LOOPBACK=0` there.
- **`POST /api/clear` is owner-only and needs a confirmation (contract change).** Editors, viewers and every agent get
  `403`; the owner must send `{"confirm": "clear all pins"}` (else `400`). The `.jsonl.bak` archive is kept, the
  response adds `cleared` and `archive`, and a `cleared` event records who did it. The viewer never used it.
- **@mentions notify every time.** A person tagged earlier on a pin got nothing when tagged again in a reply or reopen
  reason. Now every @-tag in a reply or reopen reason is a `mention` for that person (never the poster), everyone else
  involved gets `replied` (`reopened` for the author), and nobody gets both for one post. A note edit notifies people
  whose @-tag occurs more often than before (a typo fix stays quiet; `note_append` with `@name` notifies).
- `pins.md`: a new line after the close instruction shows how to claim a pin (`/api/pins/N/claim` with `eta_min`,
  `409` = taken, `/unclaim` to give up); the token line says remote agents must use a token. Both are additive lines.
- Viewer: the viewer role no longer sees edit/reply/close/drop/reopen/confirm/rebuild/save controls (the server already
  refused them) and the composer says why; `[질문으로 보내기]` keeps focus in the memo and Ctrl+Enter saves from anywhere
  in the composer; the section strip shows the first section at the very top of page 1 instead of the last heading on
  the page (it now uses the heading's position on the page); a browser refused on `GET /` gets a short ko/en page
  instead of raw JSON.
- CLI: `limn member add` rejects logins with whitespace (the server's `valid_login` now does too, the same rule as
  `--local-user`); `limn member list` no longer says a role is "recorded on first visit"; `limn serve --port N` on a
  busy port prints one line and exits 1 instead of a traceback.
- Docs: `limn update` has defaulted to the https source since 0.1.1; 0.1.0 defaulted to SSH, so the first update from
  0.1.0 still fetches over SSH (`docs/handbook/instances.md` §업데이트와 되돌리기 shows the https override). An endpoint audit, the
  principal x entry path x operation matrix and the new behaviour are covered by `tests/test_qa_021.py`.
- Documentation moved into a Korean System Handbook (`docs/handbook/`) with decision records
  (`docs/adr/`). The former `docs/design.md`, `docs/build-sync.md`, `docs/api.md`,
  `docs/operations*.md`, `docs/instances*.md` and `docs/design/access-and-sync*.md` are its chapters
  now; the access-control draft is ADR-0002. The documentation move itself changes neither `pins.md` nor the HTTP API.
- Roadmap for aligning the code with the team coding rules: `docs/handbook/code-style-roadmap.md`.

## 0.2.0 — 2026-09-25

Access control, stage v0.2 of [ADR-0002](docs/adr/0002-access-control.md). An existing
0.1 instance (no `AUTH`, no `tokens.json`, `people.json` without roles) behaves exactly as before; the only
visible difference is a deprecation warning in the server log and one added guidance line in `pins.md`.

- **Identity providers** (`--auth`, config `AUTH=`): `tailscale` (default — the 0.1 behaviour; the
  `Tailscale-User-*` headers are now trusted only from a loopback TCP peer), `local` (a single user on their own
  machine: every loopback request is the owner), `trusted-proxy` (configurable user/name/e-mail headers, trusted
  only from `--trusted-proxies`; everything else is `401`).
- **Agent API tokens**: `limn token create|list|revoke <instance>` (or `--state-dir`). Sent as
  `Authorization: Bearer <token>`, accepted by every provider, stored as SHA-256 hashes in `<state>/tokens.json`
  (mode 0600), shown once, revocable without a restart. Token principals are `agent:<name>` and follow the agent
  contract (close goes to review, never confirm, never recorded in `people.json`).
- **Headerless loopback agent** kept by default under `tailscale` but deprecated (warning at startup and on the
  first such request); `--no-agent-loopback` / `AGENT_LOOPBACK=0` turns it off. Always off under `local`,
  `trusted-proxy` and on a non-loopback bind, where asking for it refuses to start.
- **Member roles** in `people.json` (`owner`, `editor`, `viewer`, `agent`; missing = `editor`), enforced once in
  the handler: viewers may only read and run `/api/pick`/`/api/revision-build`, agents may not confirm.
  `limn member add|list|remove|role <instance>`; changes apply without a restart. `--members-only`
  (`MEMBERS_ONLY=1`) admits only listed people (and `--allow`). Without an allowlist, unknown tailnet people are
  still auto-added as editors. `/api/people` entries and `me` carry an additive `role`.
- **Binding**: `--bind` (`BIND=`, default `127.0.0.1`). A non-loopback address refuses to start unless
  `--auth trusted-proxy`, or `--i-know-this-is-insecure` (loud warning). `--public-host` (`PUBLIC_HOSTS=`) adds
  names accepted as Host/Origin and used as the `pins.md` base URL. The startup log gains an `auth` line.
- **Instance manager**: `limn run` maps and validates the new config keys (a 0.1 config gives the same argv);
  `limn add --auth`; `limn doc add|remove` keep the access keys; `tailscale serve` is refused for `AUTH=local`
  and `AUTH=trusted-proxy`.
- Docs: SECURITY.md threat model, README security note, instances/operations guides, API §Authentication, skill
  (where an agent's token comes from).

## 0.1.1 — 2026-09-25

English UI finished; no change to the agent contract (`pins.md`, HTTP API) or to the Korean UI.

- Composed UI strings (page counts, "awaiting review N", "<name>'s review", relative times, "show N earlier",
  claim and build status, toasts, tooltips, the tab title) go through the message table with parameters and
  plural forms (`tl('{n}쪽', {n})`), so `?lang=en` leaves no Korean chrome. Stored names such as the local agent's
  are shown in the UI language. Document tab names, notes, replies and the manuscript stay as written.
- The desktop toolbar fits one row at the default 348px panel width in both languages (the page field shrinks
  before anything wraps; its English placeholder is "Page").
- New browser test: the real viewer in English against an in-process server must show no Hangul outside user
  content (desktop, fold and phone), the toolbar stays on one row in both languages, and Korean stays as it was.
- Install and `limn update` use the public `git+https://github.com/dartworklabs/limn` source (SSH still works
  through `LIMN_REPO`).

## 0.1.0 — 2026-09-25

First standalone release. Mechanical move of the app and its instance manager into this repository,
with history from both sources preserved (see README, History).

- Package `dartwork-limn` with the `limn` command: `limn serve`, `limn version`, instance management
  (`limn add|start|stop|update|list|status|url|snippet|doc|remove|run`) and `limn migrate`.
- Former names replaced by Limn: systemd unit `limn@<name>`, config `~/.config/limn/<name>.env`,
  data `~/.local/share/limn/`, environment variables `LIMN_*`. `limn migrate` moves instances from the
  former `pin-viewer` install (config copy, optional state move, printed systemd switch commands).
- `limn update` reinstalls through `uv tool` (latest tag or `--ref`), restarts running instances, and
  prints the rollback command; `--dry-run` shows the plan.
- `GET /api/version` and `limn serve --version`.
- Viewer UI: English message table alongside Korean (`?lang=`, saved preference, browser language).
- The `pins.md` format and the HTTP API are unchanged.
