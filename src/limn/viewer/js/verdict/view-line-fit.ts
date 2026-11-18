import { LAYOUT_MODE, VERDICT_PLACE } from '../app/rules-tables.ts';
import { LAYOUT, topPinId, COARSE_POINTER_QUERY } from '../app/state.ts';
import { pageVerdictsOn } from '../documents/state.ts';
import { JUMP_TARGET } from '../layout/flow-scroll.ts';
import { topAnchor } from '../layout/flow.ts';
import { readingDepth } from '../pdf/view-page-jump.ts';
import { pdfAreaInnerWidth } from '../pdf/view-pages.ts';
import { $, findAll, findElement, $$, findMaybe } from '../platform/dom.ts';
import { translate } from '../platform/i18n.ts';
import { setHtml, html, lucideIcon } from '../platform/markup.ts';
import { chipAway } from '../platform/notices.ts';
import { ARMED_VERDICT } from './flow-words.ts';
import { stickSoon } from './state-line-renderer.ts';
import { SAVING_LINES, pageLineSlot } from './state-lines.ts';
import { LAST_KEY_SAVE } from './state-reason.ts';
import { holdFarLines, letFarLinesGo } from './view-far-lines.ts';
import { keepFocusOnLine } from './view-line.ts';
import { shouldStandBeside, IS_BESIDE_PAGES, fitPanel } from './view-panel.ts';

// The width of each line and whether it is one row or stacked - per line. A line is its own page's width, never past
// what the PDF area shows; a page narrower than the widest has a line as narrow, under it. Where the pages are fitted
// (no sideways scroll) a line also ends before what lies over the area's right side (measureInsetRight: an overlay
// panel, the closed panel's status box) and still starts where its page does: centred with the room cut on one side,
// the sticky line would be pushed past the page's left edge. A zoomed page's line keeps the room the area shows and
// stays in view as the page scrolls sideways (sticky). Then each line on its own (fitPageLines). Measured only while
// the pages are laid out (the changes view hides them); read and written in batches. a cut line narrower than this
// keeps its page's width and lets the sticky edge push it instead
const MIN_CUT_LINE_WIDTH = 320;

function sizePageLines() {
  const insetRight = measureInsetRight(),
    area = $('#left'),
    lines = findAll(document, '#doc .pv', HTMLElement);
  area.style.setProperty('--pv-inset-r', insetRight + 'px');
  INSET_RIGHT = insetRight;
  $('#doc').classList.remove('pv-stack');
  if (!lines.length || !lines[0].getClientRects().length) return;
  // A zoom or a new width took the room across its bar: the lines move at the next frame (stickReadingLine), never
  // here. A zoom restores its place after this call, and the reading page read before that is not the one being read
  // (verdict/view-panel.ts).
  if (shouldStandBeside() !== IS_BESIDE_PAGES) stickSoon();
  if (IS_BESIDE_PAGES) {
    fitPageLines(lines);
    return;
  } // the panel keeps its own width
  const room = pdfAreaInnerWidth() - insetRight,
    areaRect = area.getBoundingClientRect(),
    fitted = area.scrollWidth <= area.clientWidth + 1;
  const end =
    // the room's right edge on screen
    areaRect.left + area.clientLeft + area.clientWidth - parseFloat(getComputedStyle(area).paddingRight) - insetRight;
  const at = lines.map((line) => {
    const pageElement = document.getElementById('p' + line.dataset.page),
      block = line.parentElement;
    if (!pageElement || !block) return null;
    const rect = pageElement.getBoundingClientRect();
    return {
      w: parseFloat(pageElement.style.width) || rect.width,
      left: rect.left,
      off: rect.left - block.getBoundingClientRect().left,
    };
  });
  lines.forEach((line, index) => {
    const place = at[index];
    let width = place ? Math.min(place.w, room) : room,
      marginLeft = '';
    if (place && fitted && end - place.left < width && end - place.left >= MIN_CUT_LINE_WIDTH) {
      width = end - place.left;
      marginLeft = Math.round(place.off) + 'px';
    }
    line.style.width = Math.round(width) + 'px';
    line.style.marginLeft = marginLeft;
  });
  fitPageLines(lines);
}

// The verdict pins saved by a key on this screen (LAST_KEY_SAVE, each in turn): their lines (.pv-kw) are fitted at
// either look of the way to the reason (fitPageLines). The last key save's alone says 'Enter 이유 쓰기', and fitting
// one again on [이유 추가] alone when it stops being the last would move the pages under the next key save.
const KEY_SAVED_PINS: Set<number> = new Set();

// One row or stacked, decided per line (.pv-stack), so one line with an earlier verdict or a reason never stacks every
// line of the document over the plot. Each line is laid out as one row - the figure's title cut first, down to its
// identifier ('6쪽 · PL17', pageLineName; --pv-fig-min), then the reason and the earlier link (components.css) - and
// stacks only when its state's own words, [판정 취소] and its buttons still cannot share the row: the state runs past
// its share, or the buttons went to a row of their own (a narrow page). On the wide band a line that does not fit first
// lets the reason go further and the earlier link say its count alone (.pv-tight): a desktop keeps one row, since a
// second row covers the plot. A line narrower than a verdict's state beside its words stacks whatever it shows, so a
// press never stacks it. A line whose confirm word waits for its second press, or whose save is out, keeps the rows it
// has (holdsRows): its words must not move between the two presses, or the second press lands elsewhere. The save chip
// is placed after (placeLineChips). Read and written in batches. The PDF area does not anchor its scroll for the pass
// (holdPageView): the pass grows every line above the reading page and shrinks it back (#doc.pv-measure). Anchoring
// that follows part of it would move the pages down when a reason opens, and while pinch-zoomed Chromium carries the
// anchoring of the shrink - the area is the page's root scroller there - into the zoomed view, which would jump to the
// page's top at every drawing of the lines. The pass moves nothing below a line it measures either (keepLineBlocks):
// WebKit anchors the growth on the next page's block and not the shrink, which would move a phone's pages at a key
// save.
function fitPageLines(lines: HTMLElement[]) {
  const panel = lines.find((line) => line.id === 'pv-panel');
  if (panel) {
    fitPanel(panel);
    lines = lines.filter((line) => line !== panel);
    if (!lines.length) return;
  } // the panel: rows down it, never one row (verdict/view-panel.ts)
  const held = lines.map(holdsRows),
    docElement = $('#doc'),
    hold = holdPageView(true),
    kept = keepLineBlocks(lines);
  try {
    // a line skipped far from the view is laid out to be measured, and keeps its height after (letFarLinesGo)
    holdFarLines(lines);
    if (LAST_KEY_SAVE) KEY_SAVED_PINS.add(LAST_KEY_SAVE);
    lines.forEach((line, index) => {
      line.classList.toggle('pv-kw', KEY_SAVED_PINS.has(Number(line.dataset.pin)));
      if (!held[index]) {
        line.classList.remove('pv-stack', 'pv-tight', 'pv-early-out');
        line.style.removeProperty('--pv-t-h');
      }
    });
    // Every line is measured as the reading line (#doc.pv-measure shows each hidden identifier, components.css):
    // otherwise a line that stacks only while it is read would shrink when the reading page leaves, and move the pages.
    docElement.classList.add('pv-measure');
    // The figure's least width is its identifier's (--pv-fig-min): its title's own text would otherwise count in it.
    const ids = lines.map((line) => {
      const identifier = line.querySelector(':scope>.pv-fig>.pv-fig-id');
      return identifier && identifier.getClientRects().length ? Math.ceil(identifier.getBoundingClientRect().width) : 0;
    });
    lines.forEach((line, index) => {
      const width = ids[index] + 'px';
      if (line.style.getPropertyValue('--pv-fig-min') !== width) line.style.setProperty('--pv-fig-min', width);
    });
    // How far a line's state runs past its share, in px (its parts, also those inside a display: contents span - the
    // reason and [이유 추가]; 0 or less where it holds), less keySaveStateCut - a key save's way to the reason is drawn
    // at the wider of its two looks (--pv-add-w, set below) with the earlier link beside it, which it never shows at
    // once -, or Infinity where the buttons went to a row of their own. Its row does not hold (tight) past 1px.
    const past = (line: HTMLElement) => {
      const state = line.querySelector(':scope>.pv-t'),
        group = line.querySelector(':scope>.vd-btns');
      if (!state) return -Infinity;
      const stateRect = state.getBoundingClientRect();
      if (group && group.getClientRects().length > 0 && group.getBoundingClientRect().top >= stateRect.bottom - 1)
        return Infinity;
      const right = [...state.querySelectorAll(':scope>*,:scope>*>*')].reduce(
        (most, child) =>
          child.getClientRects().length > 0 ? Math.max(most, child.getBoundingClientRect().right) : most,
        -Infinity,
      );
      return right - stateRect.right - keySaveStateCut(line, state, addDifference);
    };
    const tight = (line: HTMLElement) => past(line) > 1;
    // A line too narrow for the state a press brings beside its words stacks whatever it shows now, so a press that
    // turns '판정 없음' into '판정 #26 보류 · 처리 대기 · 이유 추가 · 판정 취소' never stacks it then and moves every
    // word under the finger. That state's width is measured, not guessed (measureStateNeed), and so is all that shares
    // its row: the words as they are drawn, with the check a press puts on one of them (STATE_NEED.check) where none is
    // pressed yet; the identifier and the dot after it; and the row's gaps between the four (its column gap). The sum
    // is the row the press brings, to the subpixel: a fixed allowance is too much for a resting line or too little for
    // a press (the English words are sized for a 620px line, ui_en.json).
    const need = lines.length ? measureStateNeed(lines[0]) : 0,
      gap = lines.length ? parseFloat(getComputedStyle(lines[0]).columnGap) || 0 : 0;
    // A key save's line - read, it says 'Enter 이유 쓰기'; at rest, [이유 추가] - lays its way to the reason out at the
    // wider of the two (the probe's, STATE_NEED.add; .pv-kw, components.css #doc.pv-measure), so it is fitted the same
    // whichever page is read. Fitted on the look it shows, a line within the difference between them would stack only
    // while it is read.
    const addWidths = STATE_NEED.add,
      addDifference = Math.max(0, addWidths[1] - addWidths[0]),
      addWidth = Math.max(addWidths[0], addWidths[1]) + 'px';
    if (docElement.style.getPropertyValue('--pv-add-w') !== addWidth)
      docElement.style.setProperty('--pv-add-w', addWidth);
    const widthOf = (element: Element | null) =>
      element && element.getClientRects().length ? element.getBoundingClientRect().width : 0;
    const narrow = lines.map((line, index) => {
      if (held[index]) return false;
      const group = line.querySelector(':scope>.vd-btns'),
        identifierWidth = widthOf(line.querySelector(':scope>.pv-fig>.pv-fig-id'));
      if (!group || !group.getClientRects().length) return false;
      const press = group.querySelector(':scope>.vd-b[aria-pressed="true"]') ? 0 : STATE_NEED.check,
        id = identifierWidth ? identifierWidth + widthOf(line.querySelector(':scope>.pv-fig-sep')) + 2 * gap : 0;
      return line.getBoundingClientRect().width < widthOf(group) + press + id + gap + need;
    });
    let over = lines.map((line, index) => !held[index] && (narrow[index] || tight(line)));
    // A tight line whose row holds all but its earlier link's count lets that step out too (.pv-early-out) rather than
    // stack: the last thing a desktop row gives way, at its bar - a line the person saved by a key over an earlier
    // verdict there ('+1' beside [이유 추가] at rest, which 'Enter 이유 쓰기' takes the place of while it is read:
    // components.css).
    const out = lines.map(() => false);
    if (LAYOUT === LAYOUT_MODE.WIDE && over.some((isOver) => isOver)) {
      lines.forEach((line, index) => {
        if (over[index]) line.classList.add('pv-tight');
      });
      over = lines.map((line, index) => {
        if (!over[index] || narrow[index]) return over[index];
        const overflow = past(line);
        if (overflow <= 1) return false;
        const state = findElement(line, ':scope>.pv-t', Element);
        out[index] = overflow - earlierLinkRoom(state) + keySaveStateCut(line, state, addDifference) <= 1;
        return !out[index];
      });
      lines.forEach((line, index) => {
        if (out[index]) line.classList.add('pv-early-out');
      });
    }
    lines.forEach((line, index) => {
      if (over[index]) line.classList.add('pv-stack');
    });
    // A stacked line's state rows are the reading line's too: their height, measured here with what only the reading
    // line shows ([이유 추가], laid out unseen), is the least the state takes (--pv-t-h, components.css), so a line
    // whose state wraps to a second row only while it is read (beside an earlier link) does not grow when it is read.
    // Where that is more than the state takes now (.pv-t-kept), its rows stand at the top and the room is kept under
    // them: centred in it, a resting line's state would stand off its identifier's row.
    const keptHeights = lines.map((line, index) => {
      const state = over[index] ? line.querySelector(':scope>.pv-t') : null;
      return state ? state.getBoundingClientRect().height : 0;
    });
    docElement.classList.remove('pv-measure');
    const nat = lines.map((line, index) =>
      keptHeights[index] ? findElement(line, ':scope>.pv-t', Element).getBoundingClientRect().height : 0,
    );
    lines.forEach((line, index) => {
      if (held[index]) return;
      const isKept = keptHeights[index] > nat[index] + 0.5;
      line.classList.toggle('pv-t-kept', isKept);
      if (isKept) line.style.setProperty('--pv-t-h', keptHeights[index] + 'px');
    });
    // The lines' fitted heights, their kept rows included: what moves now is real, and letLineBlocks keeps the reading
    // page where it stood. Let go before the rows are kept again, a stacked line above the reading page would shrink
    // there and grow back after the correction, and with the area not anchoring for the pass (holdPageView) the reading
    // page would go down by the rows.
    letLineBlocks(kept);
    placeLineChips(lines);
    // A word group that wraps keeps every button at its own width (fitWrappedWords), read for every line before any is
    // written.
    const groups = lines.map((line) => line.querySelector('.vd-btns')),
      wrap = groups.map(
        (group) =>
          !!group &&
          new Set([...group.children].map((button) => Math.round(button.getBoundingClientRect().top))).size > 1,
      );
    groups.forEach((group, index) => {
      if (group) group.classList.toggle('wrapped', wrap[index]);
    });
    keepFocusOnLine(lines);
  } finally {
    // Also when a step throws: never left measuring, every line keeps the height it is drawn at and may be skipped
    // again (letFarLinesGo, read once the measure is gone), and the view anchors again only after that - whatever
    // letFarLinesGo does.
    docElement.classList.remove('pv-measure');
    letLineBlocks(kept);
    try {
      letFarLinesGo(lines);
    } finally {
      holdPageView(false, hold);
    }
  }
}

// Keeps the block of each line fitPageLines is about to measure at the height it is drawn at, until letLineBlocks: the
// pass takes a line's rows off and measures it as the reading line (#doc.pv-measure), and the line may grow inside its
// block, but the block, and the pages after it, stand still. So the area's scroll anchoring - WebKit's too, which
// carries the growth and not the shrink - has nothing to follow, while a line whose fitted height does change moves the
// pages after the pass. A block's height set, its last line's bottom margin does not collapse through it: the block
// carries the space to the next block itself. The last block, with nothing after it, is left alone. Read before any is
// written; what each had inline is put back.
function keepLineBlocks(lines: HTMLElement[]): [HTMLElement, string, string][] {
  const set: Set<HTMLElement> = new Set();
  lines.forEach((line) => {
    const block = line.parentElement;
    if (block && block.classList.contains('pgw') && block.nextElementSibling) set.add(block);
  });
  const blocks = [...set],
    at = blocks.map((block) => {
      const rect = block.getBoundingClientRect(),
        next = block.nextElementSibling;
      return [rect.height, next ? next.getBoundingClientRect().top - rect.bottom : 0];
    });
  const kept: [HTMLElement, string, string][] = [];
  blocks.forEach((block, index) => {
    const [height, gap] = at[index];
    if (!height) return;
    kept.push([block, block.style.height, block.style.marginBottom]);
    block.style.height = height + 'px';
    block.style.marginBottom = gap + 'px';
  });
  return kept;
}

// Lets the blocks keepLineBlocks held go to their lines' fitted heights, keeping the view by hand: the page under the
// reading line stands where it stood. A block's height on the anchor's path - the reading page's own block is held too
// - suppresses the PDF area's scroll anchoring, so every line above that changes its height would move the view with
// nothing to follow. The area's own anchoring is off for the step, so it adds no correction of its own, and is put back
// as it was (a pinch-zoom hold's included). A touch screen at its very top stays there, as restoreAnchor keeps it: the
// space above page 1 is not scrolled away. A jump on its way (JUMP_TARGET) is left to go on: a script's write ends a
// smooth scroll where it stands, so fitting a line as a far jump passes it would stop the jump there, short of its
// figure. Every glide has the settling, which measures its place again when it rests and glides what moved
// (arrivalWatch, arrivalSettle) - unless the person has acted meanwhile, which lets it go.
function letLineBlocks(kept: [HTMLElement, string, string][]) {
  if (!kept.length) return;
  const area = $('#left'),
    anchor = area.getClientRects().length ? topAnchor(readingDepth(area)) : null;
  const pageElement = anchor ? document.getElementById('p' + anchor.page) : null,
    y = pageElement ? pageElement.getBoundingClientRect().top : 0,
    was = area.style.getPropertyValue('overflow-anchor');
  if (pageElement) area.style.setProperty('overflow-anchor', 'none');
  kept.forEach(([block, height, margin]) => {
    block.style.height = height;
    block.style.marginBottom = margin;
  });
  kept.length = 0;
  if (!pageElement || !anchor) return;
  const drift = pageElement.getBoundingClientRect().top - y;
  // a touch screen's top stays the top (restoreAnchor)
  if (Math.abs(drift) > 0.5 && !anchor.atTop && JUMP_TARGET === null) area.scrollTop += drift;
  void area.offsetHeight;
  if (was) area.style.setProperty('overflow-anchor', was);
  else area.style.removeProperty('overflow-anchor');
}

// Holds the view where it is across fitPageLines's pass (on) and lets go after it (off, given what on returned): the
// PDF area does not anchor its scroll (overflow-anchor), and its layout is brought up to date before it anchors again,
// so the anchor it then takes is where the pass left the pages - never a measure's grown lines. The pass holds the
// blocks of the lines it measures (keepLineBlocks), but #doc.pv-measure lays out every line in the document as the
// reading line, those it does not hold too: a stacked line above the reading page measures a row taller (the key marks
// on its words) and pushes the reading page down and back within the pass. Anchoring that follows part of that would
// move the pages when a reason opens or closes, and while the page is pinch-zoomed Chromium carries a shrink's
// anchoring into the zoomed view. Nothing the pass does is to move the pages: what moves after it is the lines' fitted
// heights, which letLineBlocks lets go with the reading page kept where it stood. On returns the area's own value it
// replaced, which off puts back (a pass inside a pass leaves the outer one's hold), or null where it held nothing (no
// PDF area). No scroll of its own, ever.
function holdPageView(on: boolean, was?: string | null): string | null {
  const area = $('#left');
  if (!on) {
    if (typeof was !== 'string') return null;
    void area.offsetHeight;
    if (was) area.style.setProperty('overflow-anchor', was);
    else area.style.removeProperty('overflow-anchor');
    return null;
  }
  if (!area) return null;
  const previous = area.style.getPropertyValue('overflow-anchor');
  area.style.setProperty('overflow-anchor', 'none');
  return previous;
}

// The width the state of a person's fresh verdict takes on a line in a row, drawn in a hidden line like the given one
// (its text size, the screen's language and pointer) and kept until those or the next pin number's digits change. Two
// states follow a press: after a click '판정 #0 <the longest word> · 처리 대기 · 이유 추가 · 판정 취소', and on a mouse
// screen after a key 'Enter 이유 쓰기' in place of [이유 추가] - the wider of the two is the need, with one more gap of
// the state's row for a save's words ('· 보류 저장 중…', .pv-busy), which give way down to nothing while the save is
// out (components.css). The pin number is drawn with as many digits as the next pin's (topPinId), each a 0. A line
// narrower than that beside its words and identifier is stacked before any press (fitPageLines). Measuring the click
// state alone would let a key save near the bar stack the line under the press, and a second save's words push [판정
// 취소] out of the held row. The probe then draws the longest word pressed and not (its check before it, its weight;
// one key mark on both): what a press adds to the words, kept as STATE_NEED.check, which a line with no pressed word
// counts so its first press does not stack it. STATE_NEED.add: the way to the reason's own width as [이유 추가] and as
// 'Enter 이유 쓰기' (a mouse screen's; [이유 추가]'s again on a touch one), which every line is fitted at the wider of
// (fitPageLines).
let STATE_NEED = { key: '', w: 0, check: 0, add: [0, 0] };

function measureStateNeed(line: HTMLElement) {
  const verdicts = pageVerdictsOn();
  if (!verdicts) return 0;
  const word = verdicts.choices
      .map((choice) => choice.label)
      .reduce((longest, label) => (label.length > longest.length ? label : longest), ''),
    fine = matchMedia('(pointer:fine)').matches,
    number = '#' + '0'.repeat(String(topPinId() + 1).length);
  const key = [
    getComputedStyle(line).fontSize,
    translate('판정'),
    word,
    COARSE_POINTER_QUERY.matches,
    fine,
    number,
  ].join('|');
  if (STATE_NEED.key === key) return STATE_NEED.w;
  const probe = document.createElement('div');
  probe.className = 'pv';
  probe.setAttribute('aria-hidden', 'true');
  probe.style.cssText =
    // its own width, not the lines' (fitPageLines)
    'position:absolute;left:0;top:0;width:max-content;visibility:hidden;pointer-events:none;--pv-add-w:0px';
  $('#doc').appendChild(probe);
  const state = (byKey: boolean) => {
    setHtml(
      probe,
      html`<span class="pv-t"><span class="pv-s">${translate('판정')} <span class="pin-ref pv-ref hit">${number}</span> <b class="vd-w">${word}</b></span><span class="pv-sep">·</span>\
<span class="pv-st">${translate('처리 대기')}</span><span class="pv-ra"><span class="pv-sep">·</span><button type="button" class="btn-ghost btn-sm pv-add hit" tabindex="-1">\
${byKey ? html`<kbd class="pv-kbd">Enter</kbd> ${translate('이유 쓰기')}` : translate('이유 추가')}</button></span>\
<span class="pv-sep pv-cn">·</span><button type="button" class="btn-ghost btn-sm pv-cancel pv-cn hit" tabindex="-1">${translate('판정 취소')}</button></span>`,
    );
    const stateRow = findElement(probe, ':scope>.pv-t', Element),
      addButton = findElement(stateRow, '.pv-add', Element);
    return [
      stateRow.getBoundingClientRect().width + (parseFloat(getComputedStyle(stateRow).columnGap) || 0),
      addButton.getBoundingClientRect().width,
    ];
  };
  const clickState = state(false),
    keyState = fine ? state(true) : clickState,
    width = Math.ceil(Math.max(clickState[0], keyState[0]));
  setHtml(
    probe,
    html`<span class="vd-btns"><button type="button" class="vd-b" aria-pressed="true" data-kn="1" tabindex="-1">${lucideIcon('check')}<span class="lbl">${word}</span></button>\
<button type="button" class="vd-b" aria-pressed="false" data-kn="1" tabindex="-1"><span class="lbl">${word}</span></button></span>`,
  );
  const widths = [...probe.querySelectorAll('.vd-b')].map((x) => x.getBoundingClientRect().width),
    check = Math.max(0, widths[0] - widths[1]);
  probe.remove();
  STATE_NEED = { key, w: width, check, add: [clickState[1], keyState[1]] };
  return width;
}

// A web font that arrives after the lines were measured - the bundled Pretendard after the fallback face - changes
// every width: the state's width is measured again and every line fits itself again (sizePageLines), once each font
// load is done and when the fonts are ready after boot. Kept from the fallback face, a width near the stacking
// threshold would let the first save still move the words.
function refitForFonts() {
  STATE_NEED = { key: '', w: 0, check: 0, add: [0, 0] };
  if ($$('#doc .pv').length) sizePageLines();
}

// How much less than drawn a key save's line's state takes at most in a row, while it is fitted (fitPageLines): with
// its way to the reason drawn at the wider of its looks (`difference` px more than [이유 추가]: 'Enter 이유 쓰기') and
// the earlier link beside it - which a tight line shows beside [이유 추가] but not beside 'Enter 이유 쓰기'
// (components.css) - the more of the two looks takes `difference` less, or the link and its gap less, whichever is
// less. 0 for any other line, and for one that is not tight: it shows the link beside both.
function keySaveStateCut(line: HTMLElement, state: Element, difference: number): number {
  if (
    !difference ||
    !line.classList.contains('pv-kw') ||
    !line.classList.contains('pv-tight') ||
    !state.querySelector(':scope>.pv-ra>.pv-add')
  )
    return 0;
  const earlierRoom = earlierLinkRoom(state);
  return earlierRoom ? Math.min(difference, earlierRoom) : 0;
}

// The room a state's earlier link takes in its row as drawn - its width, the dot before it and the gap before each - or
// 0 where it shows none.
function earlierLinkRoom(state: Element): number {
  const link = state.querySelector(':scope>.pv-early');
  if (!link || !link.getClientRects().length) return 0;
  const gap = parseFloat(getComputedStyle(state).columnGap) || 0,
    dot = link.previousElementSibling,
    dotWidth =
      dot && dot.classList.contains('pv-ea') && dot.getClientRects().length
        ? dot.getBoundingClientRect().width + gap
        : 0;
  return link.getBoundingClientRect().width + gap + dotWidth;
}

// Whether a line keeps the rows it has now: its confirm word waits for the second press, or its save is out.
function holdsRows(line: HTMLElement) {
  const page = Number(line.dataset.page) || 0;
  return (
    (!!ARMED_VERDICT && ARMED_VERDICT.where === VERDICT_PLACE.PAGE && ARMED_VERDICT.page === page) ||
    SAVING_LINES.has(pageLineSlot(page))
  );
}

// The save chip on a line ('#42 저장됨 · 채택 [되돌리기]') never changes the line: it is laid over it (notices.css), in
// room no control or state word of the line takes - never over the figure's identifier, the state, a text action, a
// word or a focus ring (8px clear of each), nor over the reason popover. The first room that holds it: in a row,
// between everything before the words and the words; in a stacked line, after the end of the state's last row; then
// over the figure's title after its identifier (its own row on a stacked line) - words that only describe; its words
// shown where any room holds them. Its words fold first (.pv-chip-short: its icon and [되돌리기]), then its icon
// (.pv-chip-bare); where not even [되돌리기] fits anywhere, the undo goes to the status line (chipAway). In the line's
// flow the chip would add a row on a phone and move the words under a waiting finger, and laid over them it would take
// presses meant for [이유 추가] and [판정 취소]. --pv-chip-r and --pv-chip-y place it from the line's right edge and
// top. how long a chip with no room waits for its line to settle before its undo goes to the status line
const CHIP_WAIT_MS = 3000;

const CHIP_WAIT_TIMERS: WeakMap<HTMLElement, number> = new WeakMap();

function placeLineChips(lines: HTMLElement[]) {
  const chips = lines.map((line) => findMaybe(line, ':scope>.nt-chip', HTMLElement));
  lines.forEach((line, index) => {
    if (chips[index]) {
      line.classList.toggle('pv-chip-short', false);
      line.classList.toggle('pv-chip-bare', false);
    } else line.classList.remove('pv-chip-wait');
  });
  const got = lines.map((line, index) => {
    const chip = chips[index];
    if (!chip) return null;
    const lineRect = line.getBoundingClientRect(),
      rectOf = (element: Element) => element.getBoundingClientRect(),
      shown = (element: Element) => element.getClientRects().length > 0;
    const words = [...line.querySelectorAll(':scope>.vd-btns>*')].filter(shown).map(rectOf);
    const parts = [
      ...line.querySelectorAll(':scope>.pv-fig>.pv-fig-id,:scope>.pv-fig-sep,:scope>.pv-t *,:scope>.pv-err'),
    ]
      .filter((element) => shown(element) && !element.closest('.pv-pop'))
      .map(rectOf);
    const pop = line.querySelector(':scope>.pv-pop'),
      keep = parts.concat(words, pop && shown(pop) ? [rectOf(pop)] : []),
      chipRect = rectOf(chip),
      gap = parseFloat(getComputedStyle(chip).columnGap) || 0,
      partWidth = (selector: string) => {
        const element = chip.querySelector(selector);
        return element && shown(element) ? rectOf(element).width + gap : 0;
      }; // a part and the chip's own gap beside it, as measured: the folded chip is placed at its real width
    const sizes = [
      chipRect.width,
      chipRect.width - partWidth('.nt-t'),
      chipRect.width - partWidth('.nt-t') - partWidth('.nt-ic'),
    ];
    // A room on the row through y (a box's middle) from left to right: the room less 8px off every part in that row's
    // height.
    const room = (y: number, left: number, right: number) => {
      const top = y - chipRect.height / 2,
        bot = y + chipRect.height / 2;
      let start = left,
        end = right;
      keep
        .filter((box) => box.top < bot && box.bottom > top)
        .forEach((box) => {
          if (box.right <= (start + end) / 2) start = Math.max(start, box.right + 8);
          else end = Math.min(end, box.left - 8);
        });
      return { a: start, z: end, y };
    };
    const rooms: { a: number; z: number; y: number }[] = [];
    const stack = line.classList.contains('pv-stack');
    if (!stack && words.length) {
      const y = (Math.min(...words.map((box) => box.top)) + Math.max(...words.map((box) => box.bottom))) / 2;
      rooms.push(
        room(
          y,
          parts
            .filter((box) => box.top < y && box.bottom > y)
            .reduce((most, box) => Math.max(most, box.right), lineRect.left) + 8,
          Math.min(...words.map((box) => box.left)) - 8,
        ),
      );
    } else {
      const stateBoxes = [...line.querySelectorAll(':scope>.pv-t *')]
        .filter((element) => shown(element) && !element.closest('.pv-pop'))
        .map(rectOf)
        .filter((box) => box.height > 0);
      if (stateBoxes.length) {
        const last = Math.max(...stateBoxes.map((box) => box.top)),
          row = stateBoxes.filter((box) => box.bottom > last + 1),
          y = (Math.min(...row.map((box) => box.top)) + Math.max(...row.map((box) => box.bottom))) / 2;
        rooms.push(room(y, row.reduce((most, box) => Math.max(most, box.right), lineRect.left) + 8, lineRect.right));
      }
    }
    const id = line.querySelector(':scope>.pv-fig>.pv-fig-id'),
      title = line.querySelector(':scope>.pv-fig>.pv-fig-t');
    if (id && title && shown(title)) {
      const idRect = rectOf(id);
      rooms.push(
        room((idRect.top + idRect.bottom) / 2, idRect.right + 8, stack ? lineRect.right : rectOf(title).right),
      );
    }
    for (let k = 0; k < 3; k++)
      for (const candidate of rooms)
        if (sizes[k] <= candidate.z - candidate.a)
          return {
            r: Math.round(lineRect.right - candidate.z),
            y: Math.round(candidate.y - lineRect.top),
            short: k > 0,
            bare: k > 1,
          }; // its words where any room holds them
    return { away: true };
  });
  // Going to the status line is for good (chipAway), so it is never decided on a line that is about to change: while
  // its save is out or a confirm word waits (holdsRows - the chip comes before the save's end, and the line then shows
  // the new verdict and still '· 보류 저장 중…', so its room is about to grow), or while a web font loads (a fresh
  // state's new characters are drawn in a fallback face until their Pretendard slice arrives). It waits unseen
  // (.pv-chip-wait) and is placed when the line settles - the save's end redraws the lines (drawPageVerdicts), the
  // fonts' load fits them (refitForFonts) - or goes once CHIP_WAIT_MS have passed since it first had no room.
  lines.forEach((line, index) => {
    const placed = got[index],
      chip = chips[index];
    if (!placed || !chip) return;
    if (placed.away) {
      const firstMiss = Number(chip.dataset.noRoom) || Date.now();
      chip.dataset.noRoom = String(firstMiss);
      if (
        (holdsRows(line) || (document.fonts && document.fonts.status === 'loading')) &&
        Date.now() - firstMiss < CHIP_WAIT_MS
      ) {
        line.classList.add('pv-chip-wait');
        clearTimeout(CHIP_WAIT_TIMERS.get(chip));
        CHIP_WAIT_TIMERS.set(
          chip,
          setTimeout(() => {
            if (chip.isConnected && chip.parentElement === line) fitPageLines([line]);
          }, CHIP_WAIT_MS + 20),
        );
        return;
      }
      line.classList.remove('pv-chip-wait');
      chipAway(chip);
      return;
    }
    delete chip.dataset.noRoom;
    line.classList.remove('pv-chip-wait');
    line.style.setProperty('--pv-chip-r', placed.r + 'px');
    line.style.setProperty('--pv-chip-y', placed.y + 'px');
    line.classList.toggle('pv-chip-short', !!placed.short);
    line.classList.toggle('pv-chip-bare', !!placed.bare);
  });
}

// What lies over the PDF area's right side, in px in from the area's content edge: a panel laid over it - the unfolded
// foldable's overlay panel, beside which the pages run on underneath - and its handle's touch area, as for a save chip
// (chipInRoom). 0 where the panel stands beside the area or at its bottom (a sheet). A line is never wider than the
// room left of them, and keeps out of them as it floats (sticky right, --pv-inset-r): its words would lie under the
// panel.
let INSET_RIGHT = 0;

function measureInsetRight() {
  const area = $('#left'),
    panel = $('#right'),
    grip = $('#grip');
  if (!area.getClientRects().length) return 0;
  const areaRect = area.getBoundingClientRect(),
    edge = areaRect.left + area.clientWidth - parseFloat(getComputedStyle(area).paddingRight);
  let right = edge;
  if (panel && panel.getClientRects().length) {
    const panelRect = panel.getBoundingClientRect();
    if (panelRect.left > areaRect.left + 40 && panelRect.top < areaRect.bottom - 40)
      right = Math.min(right, panelRect.left - 4);
  }
  if (grip && grip.getClientRects().length) {
    const gripRect = grip.getBoundingClientRect(),
      reach = Math.max(gripRect.width, parseFloat(getComputedStyle(grip, '::after').width) || 0);
    if (gripRect.left > areaRect.left + 40) right = Math.min(right, gripRect.right - reach - 4);
  }
  return Math.max(0, Math.round(edge - right));
}

function watchVerdictFonts() {
  if (document.fonts) {
    document.fonts.addEventListener('loadingdone', refitForFonts);
    document.fonts.addEventListener('loadingerror', refitForFonts);
    document.fonts.ready.then(refitForFonts);
  }
}

export { INSET_RIGHT, fitPageLines, measureInsetRight, sizePageLines, watchVerdictFonts };
