// Draw page verdict lines and track the line that follows the reading page.
import { VERDICT_PLACE, LAYOUT_MODE } from '../app/rules-tables.ts';
import { META, PINS, REVIEW_ALL, DONE, LAYOUT, COARSE_POINTER_QUERY } from '../app/state.ts';
import { pageVerdictsOn } from '../documents/state.ts';
import { glideInto, arrivalWatch, scrollTopFor } from '../layout/flow-scroll.ts';
import { setSide } from '../layout/flow.ts';
import { figureTop, arrivePage } from '../pdf/view-page-jump.ts';
import { findMaybe, focusedElement, findClosest, $$, findAll, searchToPage, $, typingNow } from '../platform/dom.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { setHtml } from '../platform/markup.ts';
import { hideTip } from '../platform/tooltip.ts';
import { leaveReason, syncReasonSession, leaveReasonOffPage, refocusAfterLines } from './flow-reason.ts';
import { ARMED_VERDICT, armStillHolds, disarmVerdict, refocusVerdictButton } from './flow-words.ts';
import { syncTypingFold } from './input-typing-fold.ts';
import { READING_LINE_PAGE, setReadingLinePages, KEYED_PAGE } from './state-lines.ts';
import { isReasonOpenOn, REASON_SESSION, setReasonSeen, setKeyGuard } from './state-reason.ts';
import { FAR_OBSERVER, FAR_HEIGHT, watchFarLines } from './view-far-lines.ts';
import { isHeldLow, reachesNextPage, leanFloatingLine, placePopover, placePopoverRoom } from './view-floating-line.ts';
import { pageLineHtml, morphChildren } from './view-line-content.ts';
import { sizePageLines, measureInsetRight, INSET_RIGHT, fitPageLines } from './view-line-fit.ts';
import { LINE_TEXT } from './view-line.ts';
import {
  removePanel,
  IS_BESIDE_PAGES,
  applyBeside,
  startBesideTurn,
  heldReadingPage,
  fillPanel,
  drawSummaries,
  settleBesideTurn,
  finishBesideTurn,
  bringPage,
  flashPanelOn,
  redrawOnBesideChange,
  heldPanelPage,
  pageUnderReadingLine,
  isPanelStale,
  ensurePanel,
  placePanel,
  markReadingSummary,
} from './view-panel.ts';
import { pageVerdictPins, pageTakesVerdict, pageTargetOf, canVerdict } from './view-pins.ts';
import { isReasonField } from './view-reason-field.ts';
import { fillReasonField, focusLine } from './view-reason.ts';

// The ids of the pins a page verdict line shows now (drawPageVerdicts): their page-size mark is not drawn and their
// card's [보기] goes to the line (marks, jumpPin).
let SHOWN_ON_PAGE_LINES: Set<number> = new Set();

// Draws page `page`'s line. The list redraws on every poll and many other changes, so a line is never rewritten: what
// changed is changed in place (morphNode) - its words and links, a button's state - and every button, the '#N' link and
// the earlier link stay the same elements. A press whose down and up straddle a redraw still lands on its button (a
// rewritten one would send the click to the line), and the focus stays where it was, also on a '#N' whose number just
// changed. A line whose words are what it shows is left alone. Every verdict pin the line accounts for - the current
// one and the earlier ones - draws no page-size mark.
function fillPageLine(line: HTMLElement, page: number, list: Pin[] | undefined, verdicts: DocVerdicts) {
  line.dataset.page = String(page);
  line.classList.toggle('reading', READING_LINE_PAGE === page);
  const cur = list && list[0];
  if (cur) line.dataset.pin = String(cur.id);
  else delete line.dataset.pin;
  (list || []).forEach((pin) => SHOWN_ON_PAGE_LINES.add(pin.id));
  line.setAttribute('role', 'group');
  line.setAttribute('aria-label', translateTemplate('{page}쪽 판정', { page }));
  // a save's undo chip (drawChips) stays on its line; drawChips moves it if it is another pin's
  const chip = line.querySelector(':scope>.nt-chip');
  // While its save chip stands or its reason popover is open the line draws no descriptions: no box over either.
  const markup = pageLineHtml(page, list, verdicts, !!chip || isReasonOpenOn(page), line.id === 'pv-panel');
  if (LINE_TEXT.get(line) === markup.text) return;
  LINE_TEXT.set(line, markup.text);
  // The focused reason field keeps the focus and the caret when the line around it changes shape (its verdict's save
  // landing while it is typed in: a morph by place can replace it), so what is typed next stays text - never a verdict
  // key.
  const active = document.activeElement,
    field = isReasonField(active) && line.contains(active) ? active : null,
    caret = field ? [field.selectionStart, field.selectionEnd] : null;
  if (chip) chip.remove();
  const next = document.createElement('div');
  setHtml(next, markup);
  morphChildren(line, next);
  if (chip) line.appendChild(chip);
  line.classList.toggle('pv-pop-open', !!line.querySelector(':scope>.pv-pop'));
  fillReasonField(line);
  if (field && caret && !field.isConnected) {
    const redrawn = findMaybe(line, '.pv-pop .pv-reason[data-id="' + field.dataset.id + '"]', HTMLTextAreaElement);
    if (redrawn) {
      redrawn.focus({ preventScroll: true });
      redrawn.setSelectionRange(caret[0], caret[1]);
    }
  }
}

// No description box over a line's save chip. The chip ('#42 저장됨 · 채택 [되돌리기]') stands at the line's end above
// it, where a word's box stands too: the press's own focus arms the box again (platform/tooltip.ts armTip), and a
// resting hand's slight move would bring it back after anything hid it. While a chip is on a line (drawChips puts it
// there, its window takes it away) the line's words are drawn without their descriptions (verdictButton quiet), so
// neither hover nor focus has a box to show; a chip that comes closes the box that is up. Its leaving draws the
// descriptions back. Watched per line (childList only: the chip is a child of the line).
const CHIP_WATCH =
  typeof MutationObserver !== 'undefined'
    ? new MutationObserver((recs) => {
        // Whether a line now holds a chip it did not, or lost one: a chip taken out and put back on the same line
        // (fillPageLine's morph) is no change; one moved to another line is a change on both.
        const had = new Map<Node, Map<Element, number>>();
        recs.forEach((record) => {
          const countChips = (nodes: NodeList, step: number) =>
            [...nodes].forEach((node) => {
              if (node instanceof Element && node.classList.contains('nt-chip')) {
                const counts = had.get(record.target) || new Map<Element, number>();
                counts.set(node, (counts.get(node) || 0) + step);
                had.set(record.target, counts);
              }
            });
          countChips(record.addedNodes, 1);
          countChips(record.removedNodes, -1);
        });
        let came = false,
          went = false;
        had.forEach((counts) =>
          counts.forEach((change) => {
            if (change > 0) came = true;
            else if (change < 0) went = true;
          }),
        );
        if (!came && !went) return;
        if (came) hideTip();
        drawPageVerdicts();
      })
    : null;

/** Observe chip changes on page lines and on the panel that can take their place. */
function watchLineChips(line: HTMLElement) {
  CHIP_WATCH?.observe(line, { childList: true });
}

// Draws the page verdict line under every page after the pages, the pin lists or the build change. Without page
// verdicts every line goes and the marks draw every pin.
function drawPageVerdicts() {
  const verdicts = pageVerdictsOn(),
    focused = focusedElement();
  const on = focused ? findClosest(focused, '.pv', HTMLElement) : null,
    had = !!on,
    onPage = on ? Number(on.dataset.page) || 0 : 0;
  if (ARMED_VERDICT && ARMED_VERDICT.where === VERDICT_PLACE.PAGE && (!verdicts || !armStillHolds(ARMED_VERDICT)))
    disarmVerdict(false);
  SHOWN_ON_PAGE_LINES = new Set();
  // A document with no page lines has no reason field either: a session left from the one before (or from this one
  // before its words went) closes here, its text saved - syncReasonSession, after this, is never reached for it.
  if (!verdicts || !META) {
    if (REASON_SESSION) leaveReason();
    $$('#doc .pv,#doc .pv-sum').forEach((element) => element.remove());
    removePanel();
    if (IS_BESIDE_PAGES) applyBeside(false);
    syncTypingFold();
    return;
  }
  // beside the pages or under them (verdict/view-panel.ts): the reading page holds until the spot is back
  const turn = startBesideTurn();
  try {
    syncReasonSession();
    const map = pageVerdictPins();
    const readingPage = heldReadingPage();
    setReadingLinePages(readingPage, keyedPageFor(readingPage));
    // Beside the pages: one panel for the reading page, and every page's verdicts are its - none draws a page-size
    // mark.
    if (IS_BESIDE_PAGES) {
      $$('#doc .pgw>.pv').forEach((element) => element.remove());
      map.forEach((list) => list.forEach((pin) => SHOWN_ON_PAGE_LINES.add(pin.id)));
      fillPanel(map, verdicts, leaveReasonOffPage);
    } else {
      removePanel();
      findAll(document, '#doc .pg', HTMLElement).forEach((pageElement) => {
        const page = Number(pageElement.dataset.page);
        const next = pageElement.nextElementSibling;
        let line = next instanceof HTMLElement ? next : null;
        if (!pageTakesVerdict(page)) {
          if (line && line.classList.contains('pv')) line.remove();
          return;
        } // the map says this page takes none
        if (!line || !line.classList.contains('pv')) {
          line = document.createElement('div');
          line.className = 'pv';
          pageElement.after(line);
          watchLineChips(line);
        }
        fillPageLine(line, page, map.get(page), verdicts);
      });
    }
    drawSummaries(map);
    sizePageLines();
  } finally {
    if (turn) settleBesideTurn(turn);
  }
  stickReadingLine();
  if (had) refocusVerdictButton(focused);
  refocusAfterLines(); // a reason field that went from under the focus hands it to its line
  if (turn) finishBesideTurn(turn); // the lines moved: the reading spot, a save chip and the focus come along
  // The control the focus was on went with this drawing (a take-back shows the verdict before it): its line's, never
  // nothing.
  if (had) {
    const active = document.activeElement;
    if ((!active || active === document.body) && !focusLine(onPage)) searchToPage();
  }
  syncTypingFold();
} // a redraw or a rebuild can take the focused reason field away without a focusout

// Whether a pin's page verdict line shows it, so its page-size mark is not drawn (marks).
function isShownOnLine(pin: Pin) {
  return SHOWN_ON_PAGE_LINES.has(pin.id);
}

// A card's [보기] for a pin a line shows: its page comes into view with the line and the line flashes. A figure page
// arrives at its figure (arrivePage, §그림 쪽 도착). Any other page and its line are one block (.pgw): centred when it
// fits the PDF area, else from the page's top - the line then floats at the area's bottom (scrolling to the sticky line
// itself would follow where it floats, not where it is). Returns whether it did.
function jumpToPageLine(id: number) {
  if (!SHOWN_ON_PAGE_LINES.has(id)) return false;
  const pin = PINS.find((x) => x.id === id) || REVIEW_ALL.find((x) => x.id === id) || DONE.find((x) => x.id === id);
  const target = pin && pageTargetOf(pin, META ? META.kind : undefined);
  if (!target) return false;
  if (LAYOUT === LAYOUT_MODE.NARROW) setSide(false);
  const flash = (element: HTMLElement) => {
    element.classList.remove('flash');
    void element.offsetWidth;
    element.classList.add('flash');
    clearTimeout(element._flT);
    element._flT = setTimeout(() => element.classList.remove('flash'), 1200);
  };
  const isFigure = figureTop(target.page) !== null;
  if (IS_BESIDE_PAGES) {
    if (!document.getElementById('p' + target.page)) return false;
    if (isFigure) arrivePage(target.page);
    else bringPage(target.page, true);
    flashPanelOn(target.page);
    return true;
  } // the panel flashes where the page lands (verdict/view-panel.ts)
  const line = findMaybe(document, '#doc .pv[data-page="' + target.page + '"]', HTMLElement),
    block = line && line.parentElement;
  if (!line || !block) return false;
  const area = $('#left'),
    how = block.getBoundingClientRect().height <= area.clientHeight ? 'center' : 'start';
  if (isFigure) arrivePage(target.page);
  else {
    glideInto(block, how);
    arrivalWatch(() => (block.isConnected ? scrollTopFor(block, how) : null));
  }
  flash(line);
  return true;
}

// The PDF area's height can change with no line fitted again - a window made only shorter while a scale is saved keeps
// that scale (autoFitWidth), so sizePageLines does not run: the margin follows it here, so far still means a view's
// height away.
if (window.ResizeObserver && window.IntersectionObserver)
  new ResizeObserver(() => {
    const viewHeight = $('#left').clientHeight;
    if (FAR_OBSERVER && viewHeight && viewHeight !== FAR_HEIGHT) watchFarLines([], viewHeight);
  }).observe($('#left'));

// ---------------- The line that floats, and the keys (docs/handbook/viewer.md §판정 핀)
// Only the reading page's line floats: the page under the reading line, the one the section strip names and the keys
// act on (READING_LINE_PAGE). Its line (.reading) is sticky to the PDF area's bottom within its page's block (.pgw,
// pdf/view-pages.ts buildDoc): while its own place is below the area it floats there over the page (.stuck: an edge
// that sets it off the page), and it names the figure it decides; at the page's end it settles under it. Every other
// line stays in its place - a next page's line floating as soon as that page's top edge comes in would show a second
// '판정 없음' for a figure not yet in view, and put another figure's buttons under a resting mouse or thumb. It does
// not float while a selection is being written (the composer has its own verdict row, and the line would cover the
// selection - or on a phone the sheet) nor over an open phone sheet (CSS). stickReadingLine follows the reading page
// and marks the floating line; run once a frame while the area scrolls.
function stickReadingLine() {
  // the room crossed its bar: drawn again beside or under the pages (verdict/view-panel.ts), which ran this
  if (pageVerdictsOn() && redrawOnBesideChange()) return;
  const lines = findAll(document, '#doc .pv', HTMLElement);
  if (!lines.length) return;
  const area = $('#left'),
    areaRect = area.getBoundingClientRect();
  if (!areaRect.height) return;
  const pad = getComputedStyle(area).paddingBottom;
  // the end padding a sticky line keeps clear of (components.css)
  if (area.style.getPropertyValue('--pv-pad-b') !== pad) area.style.setProperty('--pv-pad-b', pad);
  // A keyboard laid over the page without the layout giving way (the visual viewport shorter than the PDF area reaches
  // - an iPad's Safari, or a band whose PDF area does not follow --kb): the floating line and its popover rise by what
  // it hides.
  const viewport = window.visualViewport,
    keyboardOver =
      viewport && COARSE_POINTER_QUERY.matches
        ? Math.max(0, Math.round(areaRect.top + area.clientHeight - (viewport.offsetTop + viewport.height)))
        : 0;
  if (area.style.getPropertyValue('--pv-kb-over') !== keyboardOver + 'px')
    area.style.setProperty('--pv-kb-over', keyboardOver + 'px');
  if (measureInsetRight() !== INSET_RIGHT) sizePageLines(); // a panel came over the area, went, or changed its width
  const at = heldPanelPage() || pageUnderReadingLine(),
    readingPage = at && pageTakesVerdict(at) ? at : 0,
    keyedPage = keyedPageFor(readingPage); // a jump's glide: the panel's page held (verdict/view-panel.ts)
  if (REASON_SESSION && REASON_SESSION.page === readingPage) setReasonSeen(REASON_SESSION, true);
  else if (REASON_SESSION && REASON_SESSION.seen) leaveReason(); // the reading page left the field's page: moving on
  // A key's armed confirm word belongs to the page it was read on: another reading page lets it go.
  if (
    ARMED_VERDICT &&
    ARMED_VERDICT.kbd &&
    ARMED_VERDICT.where === VERDICT_PLACE.PAGE &&
    ARMED_VERDICT.page !== readingPage
  )
    disarmVerdict(false, true);
  // The new reading page stays where it is on screen without a scroll: a stacked line keeps the row of the figure's
  // name it shows while it is the reading line (components.css), so the line the reading page leaves keeps its height.
  // Scrolling the area by what a line's change moved a page would end a jump's smooth scroll where it is, and on a
  // phone a slow scroll down would never pass a page's end: the page above would come back under the reading line and
  // the reading page would flip back and forth. Two pages in a row that take no verdict read 0 here, one after the
  // other: the panel names the page, so it asks too.
  if (readingPage !== READING_LINE_PAGE || keyedPage !== KEYED_PAGE || isPanelStale(at)) {
    // the person moved on: they are not typing on into a field that went
    if (readingPage !== READING_LINE_PAGE) setKeyGuard(false);
    const was = [READING_LINE_PAGE, KEYED_PAGE];
    setReadingLinePages(readingPage, keyedPage);
    const map = pageVerdictPins(),
      verdicts = pageVerdictsOn();
    const refit: HTMLElement[] = [];
    if (verdicts && IS_BESIDE_PAGES) {
      fillPanel(map, verdicts, leaveReasonOffPage);
      refit.push(ensurePanel());
    } // the panel shows the new reading page
    else if (verdicts)
      new Set([...was, readingPage, keyedPage]).forEach((page) => {
        const line = page ? findMaybe(document, '#doc .pv[data-page="' + page + '"]', HTMLElement) : null;
        if (line) {
          fillPageLine(line, page, map.get(page), verdicts);
          refit.push(line);
        }
      });
    if (refit.length) fitPageLines(refit); // the reading line names its figure: its row is measured again
    moveFocusOffPage(readingPage, was[0]);
  }
  placePanel();
  markReadingSummary();
  lines.forEach((line) => {
    if (line.id === 'pv-panel') return; // the panel stands sticky beside the pages: it never floats at their foot
    const pageElement = line.previousElementSibling;
    if (!(pageElement instanceof HTMLElement)) return;
    const rect = line.getBoundingClientRect(),
      pageBottom = pageElement.getBoundingClientRect().bottom;
    // In its own place it stands 8px under the page; held lower by a reason's room (placePopoverRoom) it floats over
    // the gap and the next page's top, and is set off as a floating line is - with an edge under it too while it lies
    // over that page (.pv-over), since its band would read as the next page's head.
    const low = isHeldLow(line, pageElement, rect.top, pageBottom),
      stuck =
        (line.classList.contains('reading') &&
          rect.bottom > areaRect.top &&
          rect.top < areaRect.bottom &&
          rect.top < pageBottom + 4) ||
        low;
    line.classList.toggle('stuck', stuck);
    line.classList.toggle('pv-over', low && reachesNextPage(line, rect));
    leanFloatingLine(line, pageElement, rect, stuck, area, areaRect);
  });
  placePopover();
  if (placePopoverRoom(area, areaRect)) placePopover();
} // a held line its floating place lifted: the popover's side again

// The page the keys 1-5 act on: the reading page while this screen may make a verdict, no selection is being written
// and no text field has the focus (its digits are text).
function keyedPageFor(readingPage: number) {
  return readingPage && canVerdict() && $('#composer').hidden && !typingNow() ? readingPage : 0;
}

// Whether an element shows in the PDF area now (any part of it).
function isInAreaView(element: Element) {
  const area = $('#left'),
    areaRect = area.getBoundingClientRect(),
    rect = element.getBoundingClientRect();
  return (
    rect.bottom > areaRect.top &&
    rect.top < areaRect.top + area.clientHeight &&
    rect.right > areaRect.left &&
    rect.left < areaRect.right
  );
}

// The reading page moved from page `was` to readingPage while the focus stays on a control of another page's line - the
// left page's own line (still in view after a PageDown) or one now out of view (the saved reason's pencil, a word): the
// focus goes to the PDF area, where Enter opens the reading page's reason and Tab goes to its line. Left there, the
// next Enter or Space would act on the page the person left - its reason would open off-screen and the text meant for
// this page would go into that page's note. A focus put on a third page's line in view stays: the person went there.
function moveFocusOffPage(readingPage: number, was: number) {
  const active = document.activeElement,
    line = active ? findClosest(active, '#doc .pv', HTMLElement) : null;
  if (!active || !line || active.closest('.pv-pop')) return;
  const page = Number(line.dataset.page);
  if (page !== readingPage && (page === was || !isInAreaView(active))) searchToPage();
}

export {
  drawPageVerdicts,
  fillPageLine,
  isInAreaView,
  isShownOnLine,
  jumpToPageLine,
  stickReadingLine,
  watchLineChips,
};
