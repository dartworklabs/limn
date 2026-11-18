import { VERDICT_PLACE } from '../app/rules-tables.ts';
import { imeKey, EDITOR, REPLY, captureVisit, META, currentVisit } from '../app/state.ts';
import { pageVerdictsOn } from '../documents/state.ts';
import {
  isAutoScrolling,
  HAND_ON_PAGES,
  JUMP_TARGET,
  LAST_SCROLL_AT,
  setJumpTarget,
  setGliding,
  HAND_SCROLL_AT,
  setLastScrollAt,
  endJumpForScroll,
} from '../layout/flow-scroll.ts';
import { SCROLL_KEYS } from '../pdf/view-outline.ts';
import {
  eventElement,
  findClosest,
  typingNow,
  searchToPage,
  $,
  eventClosest,
  findMaybe,
  focusedElement,
  findAll,
  isDisabled,
  TABBABLE,
  isTabStop,
} from '../platform/dom.ts';
import { lineNote } from '../platform/notices.ts';
import { NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
import { isInAreaView, stickReadingLine } from './flow-line.ts';
import { verdictPress } from './flow-save.ts';
import { ARMED_VERDICT, disarmVerdict } from './flow-words.ts';
import { openReadingReason, isKeyGuarded } from './input-reason.ts';
import { stickSoon } from './state-line-renderer.ts';
import { READING_LINE_PAGE, CANCEL_OUT, pageLineSlot } from './state-lines.ts';
import {
  pageUnderReadingLine,
  sayGliding,
  IS_BESIDE_PAGES,
  ensurePanel,
  readingPageWithLine,
  markStops,
  bringPage,
  flashPanel,
} from './view-panel.ts';
import { canVerdict, pageTakesVerdict } from './view-pins.ts';
import { focusLine } from './view-reason.ts';

// The line control the focus went to and the reading page then: one focused on the reading page's line that is no
// longer it is the page the person left (stopOffPageKey), even before the frame that moves the focus
// (moveFocusOffPage).
let LINE_FOCUS: { el: Element; read: number } | null = null;

document.addEventListener('focusin', (event) => {
  const target = eventElement(event);
  LINE_FOCUS = target && target.closest('#doc .pv') ? { el: target, read: READING_LINE_PAGE } : null;
});

// Enter or Space on a control of a line that is not the reading page's - out of view, or the line of the page the
// person left (focused while it was the reading page) - does not act there (a press read before the focus moved,
// moveFocusOffPage): the focus goes to the PDF area, and Enter is taken as on the pages - the reading page's reason
// (openReasonOnEnter) - while Space is only said.
function stopOffPageKey(event: KeyboardEvent) {
  if ((event.key !== 'Enter' && event.key !== ' ') || event.ctrlKey || event.metaKey || event.altKey || imeKey(event))
    return;
  const target = eventElement(event);
  const line = target ? findClosest(target, '#doc .pv', HTMLElement) : null;
  if (!target || !line || target.closest('.pv-pop') || typingNow()) return;
  const readingPage = pageUnderReadingLine(),
    page = Number(line.dataset.page),
    left = !!LINE_FOCUS && LINE_FOCUS.el === target && LINE_FOCUS.read === page;
  if (CANCEL_OUT.has(pageLineSlot(page))) {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  } // its take-back is out
  if (!readingPage || page === readingPage || (isInAreaView(target) && !left)) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  searchToPage();
  if (event.type !== 'keydown') return;
  if (event.key === 'Enter') {
    openReadingReason(event);
    return;
  }
  lineNote('보이지 않는 쪽의 단추라 누르지 않았습니다 — 읽는 쪽에서 다시 누릅니다', NOTICE_KIND.INFO, null, {
    source: 'pv-offpage',
    life: NOTICE_LIFE.TIMER,
  });
}

window.addEventListener('keydown', stopOffPageKey, true);

window.addEventListener('keyup', stopOffPageKey, true); // keyup: a button's Space acts on its keyup

$('#doc').addEventListener('input', (event: InputEvent) => {
  if (eventClosest(event, '.pv-pop', Element)) stickSoon();
}); // the reason field grows: its side again

// The keys: 1-5 press the document's verdict words in file order on the line of the page under the reading line, as a
// press on that button does - a confirm word arms on the first press and saves on the second while its page, document
// and build hold (verdictPress). The page is read from the layout at the key, not from the last frame: a key right
// after a scroll across a page's end would otherwise go to the page before - and confirm its armed word. A confirm word
// armed for another page is let go first. Not in a text field, not while a dialog or a popover is open, not while a
// selection is being written (the composer is open) or the changes view is shown, not with Ctrl, Alt or Meta (Alt+digit
// switches documents). On a page that takes no verdict a key says so on the status line, once. The button and its line
// say the key (verdictButton's keyNumber).
function verdictKey(event: KeyboardEvent) {
  if (
    event.defaultPrevented ||
    event.repeat ||
    imeKey(event) ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    !/^[1-5]$/.test(event.key)
  )
    return;
  const target = eventElement(event);
  if (
    target &&
    (target.tagName === 'TEXTAREA' ||
      target.tagName === 'INPUT' ||
      target.tagName === 'SELECT' ||
      (target instanceof HTMLElement && target.isContentEditable))
  )
    return;
  if (
    document.querySelector('dialog[open]') ||
    !$('#page-pop').hidden ||
    !$('#doc-pop').hidden ||
    !$('#composer').hidden
  )
    return;
  // A card's editor or reply open with the focus outside the pages (on its [저장], say): its keys, not the pages' - a
  // digit would take the focus from it, and the Enter after it would open nothing (openReadingReason waits for the
  // editor).
  if ((EDITOR.current || REPLY) && !$('#left').contains(document.activeElement)) return;
  const verdicts = pageVerdictsOn(),
    digit = +event.key,
    choice = verdicts && verdicts.choices[digit - 1],
    at = pageUnderReadingLine();
  if (!choice || !at || !canVerdict()) return;
  if (isKeyGuarded(event)) return; // a reason field went from under the typing: its digits are not verdict keys
  if (isAutoScrolling()) {
    event.preventDefault();
    sayGliding();
    return;
  } // a jump still gliding: the reading page is not yet the one asked for
  if (!pageTakesVerdict(at)) {
    event.preventDefault();
    lineNote('이 쪽은 판정을 받지 않습니다', NOTICE_KIND.INFO, null, {
      source: 'verdict-key',
      life: NOTICE_LIFE.TIMER,
    });
    return;
  }
  if (ARMED_VERDICT && ARMED_VERDICT.kbd && ARMED_VERDICT.where === VERDICT_PLACE.PAGE && ARMED_VERDICT.page !== at)
    disarmVerdict(true, true);
  // The panel shows the page under the reading line at the key, also before the frame that would show it
  // (verdict/view-panel.ts).
  if (IS_BESIDE_PAGES && ensurePanel().dataset.page !== String(at)) stickReadingLine();
  const button = findMaybe(
    document,
    '#doc .pv[data-page="' + at + '"] button[data-act="pv-save"][data-key="' + CSS.escape(choice.key) + '"]',
    HTMLElement,
  );
  if (!button) return;
  event.preventDefault();
  // A digit pressed with the focus outside the pages (an outline entry, the page list's or the section strip's button,
  // a document tab, a card) brings the focus to the PDF area at once, as the save's end brings it to the line: left on
  // that control while the save is out, the Enter typed after the digit would press it again instead of opening the
  // reason. The area is a named region (index.html), so a screen reader says 'PDF 쪽' for the moment it has the focus,
  // not every page's text one after the other. Where the focus came from is kept: Shift+Tab from the line goes back
  // there (CAME_FROM).
  const active = focusedElement(),
    area = $('#left');
  if (active && active !== document.body && active !== area && !area.contains(active)) {
    noteCameFrom(active);
    searchToPage();
  }
  verdictPress(button, 'key');
}

window.addEventListener('keydown', verdictKey);

for (const eventType of ['wheel', 'touchstart', 'touchmove', 'pointerdown'])
  $('#left').addEventListener(eventType, HAND_ON_PAGES, { passive: true, capture: true });

$('#left').addEventListener(
  'pointermove',
  (event: PointerEvent) => {
    if (event.buttons) HAND_ON_PAGES();
  },
  { passive: true, capture: true },
); // a scroll bar dragged

// A scrolling key is the person's hand on the pages only where it scrolls them: on the PDF area, on a control in it (a
// line's word lets the arrows through) or on nothing - not in a text field, and not Space on a button, which it
// presses. ↓ in the outline's filter or list moves to a result, and the Enter after it starts a jump the guard must not
// take for the person's own scroll, or a digit pressed while it glides would save on a page passed.
window.addEventListener(
  'keydown',
  (event) => {
    if (!SCROLL_KEYS.has(event.key)) return;
    const target = event.target;
    if (!(
      target === document.body ||
      target === document.documentElement ||
      (target instanceof Element && !!target.closest('#left'))
    ))
      return;
    if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)))
      return;
    if (event.key === ' ' && target instanceof Element && target.closest('button,[role=button],summary')) return;
    HAND_ON_PAGES();
  },
  true,
);

// The end of a jump is at its place: a manual scroll's own end, coming after the jump began, must not end the guard in
// its first frames.
$('#left').addEventListener('scrollend', () => {
  if (JUMP_TARGET !== null && Math.abs($('#left').scrollTop - JUMP_TARGET) > 2) return;
  setJumpTarget(null);
  setGliding(false);
});

// Tab from the PDF area (where Esc, a moved-on popover or a search leaves the focus) goes to the reading page's line -
// its first control - not to the first page's line, whose focus would scroll the document there. The focus on nothing
// (body) counts as on the PDF area after a press there: a press on a page leaves the focus where it was, and Chromium's
// next Tab starts from the pressed node - which a redrawn canvas may have taken away, so it would start from the
// document's first line. A reading page with no line (a figure document's list pages, which take no verdict -
// pageTakesVerdict) or with none of its controls to stop on (a viewer who may not make a verdict, '판정 없음') keeps
// the pages where they are as well: the Tab goes to the next stop in the pages from that page on - a mark, the next
// page's line - while it shows whole in the area's view, else on past the pages (findEdgeStop: the status line's
// action, the panel's grip), else nowhere (the focus stays). Left to the DOM's order it would go to the first line
// after the pages' start and scroll them there, also on first open.
let PRESSED_ON_PAGES = false;

window.addEventListener(
  'pointerdown',
  (event) => {
    const target = eventElement(event);
    PRESSED_ON_PAGES = !!target && !!target.closest('#left') && !target.closest('#doc .pv');
  },
  true,
);

document.addEventListener('focusin', (event) => {
  const target = event.target;
  if (target && target !== $('#left')) PRESSED_ON_PAGES = false;
});

// So does Tab with nothing focused where no stop is drawn before the pages - a phone, whose nav bar, outline and
// section strip are not, whose first Tab after opening would otherwise go to a later page's line and scroll there.
window.addEventListener('keydown', (event) => {
  const active = document.activeElement;
  if (event.key !== 'Tab' || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented)
    return;
  if (!(active === $('#left') || ((!active || active === document.body) && (PRESSED_ON_PAGES || !findEdgeStop(false)))))
    return;
  const at = pageUnderReadingLine();
  if (!at) return; // no page lines, or the pages are not shown: the DOM's order scrolls nothing to a line
  const readingPage = readingPageWithLine(),
    line = readingPage ? document.querySelector('#doc .pv[data-page="' + readingPage + '"]') : null;
  const control = line
    ? findAll(line, 'a,button,[tabindex="0"]', HTMLElement).find((x) => x.getClientRects().length > 0 && !isDisabled(x))
    : undefined;
  event.preventDefault();
  const stopInView = control ? null : findStopInView(at),
    to = control || stopInView || findEdgeStop(true);
  STOP_IN_VIEW = stopInView ? { el: stopInView, visit: captureVisit(), build: (META && META.pages_build) || '' } : null;
  if (to) to.focus({ preventScroll: true });
});

// The stop in the pages that Tab from the PDF area went to in view, while the reading page had no line to go to
// (above): a mark, or a later page's line. Shift+Tab from it leaves the pages the way the reading line's first stop
// does (findOutStop, below) - the DOM's stop before it is a page above, off the screen, and the focus would scroll the
// pages there. Let go when the focus leaves the pages, on another document or build, and by the next Tab from the area.
let STOP_IN_VIEW: { el: HTMLElement; visit: { doc: string | null; seq: number }; build: string } | null = null;

// The first Tab stop in the pages from page `at` on - its own marks, then the next pages' marks and lines in the DOM's
// order - when that stop shows whole in the PDF area's view (its client box, within the window) and nothing lies over
// any of it (the status line or the sheet over the area's bottom, a panel laid over its side: what its middle and four
// points 4px in from its corners hit is it), else null. Hit at its middle alone, a line half under the status line
// would be taken. Reads the page blocks from `at` down to the area's bottom only.
function findStopInView(at: number): HTMLElement | null {
  const area = $('#left'),
    areaRect = area.getBoundingClientRect(),
    top = Math.max(0, areaRect.top + area.clientTop),
    left = Math.max(0, areaRect.left + area.clientLeft);
  const bot = Math.min(window.innerHeight, areaRect.top + area.clientTop + area.clientHeight),
    right = Math.min(window.innerWidth, areaRect.left + area.clientLeft + area.clientWidth);
  for (
    let page = at, block = document.querySelector('#doc .pgw[data-page="' + page + '"]');
    block;
    block = document.querySelector('#doc .pgw[data-page="' + ++page + '"]')
  ) {
    if (block.getBoundingClientRect().top >= bot) return null;
    const x = [...block.querySelectorAll(TABBABLE)].find(isTabStop);
    if (!x) continue;
    const rect = x.getBoundingClientRect();
    if (rect.top < top || rect.bottom > bot || rect.left < left || rect.right > right) return null;
    const insetX = Math.min(4, rect.width / 4),
      insetY = Math.min(4, rect.height / 4),
      xPoints = [rect.left + insetX, (rect.left + rect.right) / 2, rect.right - insetX],
      yPoints = [rect.top + insetY, (rect.top + rect.bottom) / 2, rect.bottom - insetY];
    const points = [
      [xPoints[1], yPoints[1]],
      [xPoints[0], yPoints[0]],
      [xPoints[2], yPoints[0]],
      [xPoints[0], yPoints[2]],
      [xPoints[2], yPoints[2]],
    ];
    return points.every(([pointX, pointY]) => {
      const hit = document.elementFromPoint(pointX, pointY);
      return !!hit && (hit === x || (!!hit.closest && hit.closest(TABBABLE) === x));
    })
      ? x
      : null;
  }
  return null;
}

// The nearest Tab stop outside the PDF area on one side of it - the last before it, or (after) the first after it - or
// null. Walks out from the area element by element and passes a part that is not drawn (display: none, hidden, inert)
// whole.
function findEdgeStop(after: boolean): HTMLElement | null {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
    acceptNode: (node) => {
      if (!(node instanceof Element)) return NodeFilter.FILTER_SKIP;
      const x = node;
      if (
        x.hasAttribute('hidden') ||
        x.hasAttribute('inert') ||
        (!x.getClientRects().length && getComputedStyle(x).display === 'none')
      )
        return NodeFilter.FILTER_REJECT;
      return isTabStop(x) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  let node: Node = $('#left');
  if (after) while (node.lastChild) node = node.lastChild; // from the area's last node the next one is past the area
  walker.currentNode = node;
  const found = after ? walker.nextNode() : walker.previousNode();
  return found instanceof HTMLElement ? found : null;
}

// Where the focus came into the pages from, while it is in them: the stop a Tab into the pages was pressed on, or the
// control a digit key was pressed on (verdictKey) - an outline entry, a document tab, the section strip, the phone's
// tool bar - with the visit (captureVisit: the document and its switch) and build it was pressed on: a switch - also
// away and back - or a new build lets it go (findOutStop), as any focus outside the pages does. Shift+Tab from the
// reading line goes back there (below).
let CAME_FROM: { el: HTMLElement; visit: { doc: string | null; seq: number }; build: string } | null = null;

function noteCameFrom(element: HTMLElement) {
  CAME_FROM = { el: element, visit: captureVisit(), build: (META && META.pages_build) || '' };
}

document.addEventListener('focusin', (event) => {
  const target = event.target;
  if (target instanceof Element && !target.closest('#left')) {
    CAME_FROM = null;
    STOP_IN_VIEW = null;
  }
});

// Where Shift+Tab leaves the pages to: where the focus came from (CAME_FROM) while it is still a stop of this document
// and build before the pages - or, where nothing comes before them (a phone: the nav bar, the outline and the section
// strip are not drawn), one in the tool bar over the sheet (#bar1) -, else the last stop before the pages
// (findEdgeStop: the section strip's or the nav bar's page button), else the phone's position button (#btn-pos, which
// opens its pages as those do). null for none.
function findOutStop() {
  const came = CAME_FROM;
  if (came && !(currentVisit(came.visit) && came.build === ((META && META.pages_build) || ''))) CAME_FROM = null;
  const area = $('#left'),
    edge = findEdgeStop(false),
    control = CAME_FROM ? CAME_FROM.el : null;
  // the summary whose press brought the focus to the panel (goToSummaryPage)
  if (control && control.isConnected && control.classList.contains('pv-sum')) return control;
  if (
    control &&
    control.isConnected &&
    !area.contains(control) &&
    isTabStop(control) &&
    (control.compareDocumentPosition(area) & Node.DOCUMENT_POSITION_FOLLOWING || (!edge && control.closest('#bar1')))
  )
    return control;
  const positionButton = $('#btn-pos');
  return edge || (isTabStop(positionButton) ? positionButton : null);
}

window.addEventListener('keydown', (event) => {
  const active = focusedElement(),
    area = $('#left');
  if (
    event.key !== 'Tab' ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.defaultPrevented ||
    !active ||
    active === document.body ||
    !active.closest ||
    active.closest('#left')
  )
    return;
  // The focus on the side of the area this Tab leaves from, the area shown with page lines, and the focus on the edge's
  // stop.
  if (
    !(
      active.compareDocumentPosition(area) &
      (event.shiftKey ? Node.DOCUMENT_POSITION_PRECEDING : Node.DOCUMENT_POSITION_FOLLOWING)
    ) ||
    !area.getClientRects().length ||
    !document.querySelector('#doc .pv') ||
    findEdgeStop(event.shiftKey) !== active
  )
    return;
  const readingPage = readingPageWithLine(),
    line = readingPage ? document.querySelector('#doc .pv[data-page="' + readingPage + '"]') : null,
    controls = line ? [...line.querySelectorAll('a,button,textarea,[tabindex="0"]')].filter(isTabStop) : [];
  event.preventDefault();
  const control = event.shiftKey ? controls[controls.length - 1] : controls[0];
  noteCameFrom(active);
  if (control) control.focus({ preventScroll: true });
  else searchToPage();
});

// Shift+Tab from the reading page's first stop leaves the pages the way the focus came in (findOutStop): back to where
// it came from while that is still a stop before the pages - the outline entry or the document tab a digit key was
// pressed on, the section strip's page button Tab came from - else to the last stop before them, the section strip's
// page button (a phone's position button). The pages do not move. The reading page's first stop is its line's first
// control, or - when pins are marked on that page - its first mark's badge, which Shift+Tab from the line reaches first
// in the DOM's order. The DOM's stop before it is the page before's line: each Shift+Tab would scroll the document a
// page up and never reach the outline. The earlier pages' lines are reached by PageUp, which makes each the reading
// page in turn. A line with its reason popover open keeps Tab to itself first (verdict/input-reason.ts, on #doc), and
// another page's line or mark is left to the DOM's order - but for the stop Tab from the PDF area went to in view while
// the reading page had no line (STOP_IN_VIEW), which leaves the same way.
window.addEventListener('keydown', (event) => {
  if (
    event.key !== 'Tab' ||
    !event.shiftKey ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.defaultPrevented
  )
    return;
  // Beside the pages the panel is the reading line, and it stands after the pages in the DOM (verdict/view-panel.ts):
  // from its first stop the reading page's marks come next, as they do from a line, and from the first of those the way
  // out.
  const active = focusedElement(),
    panel = active ? findClosest(active, '#pv-panel', HTMLElement) : null;
  const block = panel || (active ? findClosest(active, '#doc .pgw', HTMLElement) : null),
    line = panel || (block && (findMaybe(block, ':scope>.pv', HTMLElement) || document.getElementById('pv-panel')));
  const inView = STOP_IN_VIEW;
  if (inView && !(currentVisit(inView.visit) && inView.build === ((META && META.pages_build) || '')))
    STOP_IN_VIEW = null;
  if (!(active && STOP_IN_VIEW && STOP_IN_VIEW.el === active)) {
    // the stop Tab went to in view (above), on a page with a line or none
    if (!active || !block || !line || Number(block.dataset.page) !== readingPageWithLine()) return;
    const first = [...block.querySelectorAll(TABBABLE)].find(isTabStop);
    if (first !== active) return;
    const marks = panel ? markStops(Number(panel.dataset.page)) : [];
    if (marks.length) {
      event.preventDefault();
      marks[marks.length - 1].focus();
      return;
    }
  }
  const to = findOutStop();
  if (!to) return;
  event.preventDefault();
  to.focus({ preventScroll: true });
  if (to.closest('#outline') || to.classList.contains('pv-sum')) {
    endJumpForScroll();
    to.scrollIntoView({ block: 'nearest' });
  }
}); // an outline entry comes into the outline's view; the pages stay

// A press on page `page`'s summary: the page comes to the reading place, the panel shows it at once, and the focus goes
// to the panel's pressed word, else its first (focusLine); the panel flashes.
function goToSummaryPage(summary: HTMLElement) {
  const page = Number(summary.dataset.page) || 0;
  if (!document.getElementById('p' + page)) return;
  noteCameFrom(summary);
  bringPage(page);
  stickReadingLine();
  const panel = document.getElementById('pv-panel');
  if (!panel || panel.dataset.page !== String(page)) return;
  focusLine(page);
  flashPanel(panel);
}

function watchVerdictLayout() {
  $('#left').addEventListener('scroll', stickSoon, { passive: true });
  window.addEventListener('resize', stickSoon);
  const viewport = window.visualViewport;
  if (viewport) {
    viewport.addEventListener('resize', stickSoon);
    viewport.addEventListener('scroll', stickSoon);
  }
  new MutationObserver(stickSoon).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  if (typeof ResizeObserver !== 'undefined') {
    const panel = document.getElementById('right');
    if (panel) new ResizeObserver(stickSoon).observe(panel);
  }
  $('#left').addEventListener(
    'scroll',
    () => {
      const now = performance.now();
      if (JUMP_TARGET !== null && now - LAST_SCROLL_AT > 1000) setJumpTarget(null); // a jump that never got there
      if (JUMP_TARGET === null && now - LAST_SCROLL_AT > 200) setGliding(now - HAND_SCROLL_AT > 500);
      setLastScrollAt(now);
    },
    { passive: true },
  );
}

export { goToSummaryPage, watchVerdictLayout };
