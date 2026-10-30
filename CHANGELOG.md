# Changelog

## Unreleased

Follow-ups to the reviews of 0.4.34. The agent contract is unchanged: the server writes integer anchor offsets, and
those read as before.

### Fixed

- **`superseded_by` compares two verdicts' anchors as JSON values** (#303). Two closed verdict pins on the same lines
  count together only when they share one `anchor`. The server compared an offset hand-edited into a list or an object
  by its printed form, so the list `[0]` and the string `"[0]"` were one anchor to it (and so were `true` and `1`) - a
  false `superseded_by` the viewer's card did not show - and one object written with its keys in another order was two,
  to the viewer as well. The server and the viewer's verdict order now both compare offsets as JSON values: an object's
  keys in any order, `1` and `1.0` one number, never a value of another type.

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
