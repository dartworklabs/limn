// ------------------------------------------------ The pin list's sections (docs/handbook/viewer.md §목록 구획)
// Which pins each section lists - open, awaiting review, done, from the lists as this tab shows them (derivePinLists) -
// in the chosen order, drawn as day-grouped rows under a section head with its count and order control.
import { SECTION_OPEN, SECTION_SEEN, countNewInSection, ORDER } from '../platform/prefs.ts';
import { html, setHtml, lucideIcon } from '../platform/markup.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { LIST_ORDER, NOTICE_PLACE } from '../platform/tables.ts';
import { timeParts } from './view-time.ts';
import { pinPlace } from '../pdf/view-figure.ts';
import { DOCS, SHOW_ALL, OPEN_ALL, DOC, EDITOR, DONE_ALL, DONE, REVIEW_ALL } from '../app/state.ts';
import { pdoc } from '../documents/state.ts';
import type { Html } from '../platform/markup.ts';
import { NOTICES } from '../platform/notices.ts';
import { dayName, card } from './view-cards.ts';
import { findAnyPin } from '../revisions/flow.ts';
import { $$, $, findAll } from '../platform/dom.ts';
import { roveSegment } from '../platform/segments.ts';
import { pinState } from '../app/rules-pins.ts';
import { PIN_STATE } from '../app/rules-tables.ts';
import { multiDoc } from '../documents/view-tabs.ts';
// Classifies one server snapshot without reading viewer state or changing the page. Legacy pins with no doc belong to
// defaultDoc. confirming (optional) holds the ids whose [확인] waits for its undo (CONFIRMING): they stay out of the
// review list.
function derivePinLists(rows: Pin[], doc: string | null, defaultDoc: string, confirming: Set<number>) {
  const openAll: Pin[] = [],
    reviewAll: Pin[] = [],
    doneAll: Pin[] = [],
    openHere: Pin[] = [],
    doneHere: Pin[] = [];
  for (const pin of rows) {
    const state = pinState(pin),
      here = !doc || (pin.doc || defaultDoc) === doc;
    if (state === PIN_STATE.OPEN) {
      openAll.push(pin);
      if (here) openHere.push(pin);
    } else if (state === PIN_STATE.REVIEW) {
      if (!(confirming && confirming.has(pin.id))) reviewAll.push(pin);
    } else if (state === PIN_STATE.DONE) {
      doneAll.push(pin);
      if (here) doneHere.push(pin);
    }
  }
  return { openAll, reviewAll, doneAll, openHere, doneHere };
}
// The list drawn in the sidebar: the current document by default, everything if 'all documents'. A pin being edited is
// kept even from another document (so the draft text doesn't disappear).
function listOpen() {
  return SHOW_ALL && multiDoc()
    ? OPEN_ALL
    : OPEN_ALL.filter((pin) => pdoc(pin) === DOC || !DOC || (EDITOR.current && EDITOR.current.id === pin.id));
}
function listDone() {
  return SHOW_ALL && multiDoc() ? DONE_ALL : DONE;
}
function listReview() {
  return SHOW_ALL && multiDoc() ? REVIEW_ALL : REVIEW_ALL.filter((pin) => pdoc(pin) === DOC || !DOC);
}

// One section header (docs/handbook/viewer.md §목록 구획): chevron, name, count and - while collapsed - 'new N' (ids
// the section did not show when it was last expanded). The body it controls (aria-controls) is hidden while collapsed.
const SECTION_NAME_ID = { open: 'list-h', review: 'review-h', done: 'done-h' };
// ids = the pins this section lists now; all = the section's pins across every document. While expanded, everything is
// marked seen (all, so switching documents never reads as arrivals); SECTION_SEEN starts from the first load, so
// nothing is 'new' at boot.
function drawSectionHead(key: keyof typeof SECTION_SEEN, name: string, ids: number[], all: number[]) {
  const toggle = document.getElementById(key + '-toggle');
  if (!toggle) return;
  const open = !!SECTION_OPEN[key],
    seen = SECTION_SEEN[key];
  if (open && seen) (all || ids).forEach((id) => seen.add(id));
  const newCount = open ? 0 : countNewInSection(seen, ids);
  const fresh = newCount ? html`<span class="sec-new">${translateTemplate('새 {n}', { n: newCount })}</span>` : '';
  setHtml(
    toggle,
    html`${lucideIcon(open ? 'chevron-down' : 'chevron-right')}<span class="sec-name" id="${SECTION_NAME_ID[key]}">${name} <span class="badge badge-secondary sec-n">${ids.length}</span></span>${fresh}`,
  );
  toggle.setAttribute('aria-expanded', String(open));
  const body = document.getElementById(toggle.getAttribute('aria-controls') || '');
  if (body) body.hidden = !open;
}
// The pins of a list section in order (docs/handbook/viewer.md §목록 순서), list itself untouched. LIST_ORDER.NEW: the
// newest `at` first, the later pin first within a minute, a pin with no readable time last. LIST_ORDER.PAGE: by page,
// where the pin's mark is now, then line, then height on the page for a region, which has no line; pins of several
// documents stand document by document, since page numbers mean nothing across them. A pin with no page (a Markdown
// document's, ADR-0025 D2) is ordered by its lines alone - its page counts as 0. LIST_ORDER.ID: as the server lists
// them.
/** @param order - a LIST_ORDER value */
function orderPins(list: Pin[], order: string): Pin[] {
  if (order === LIST_ORDER.ID) return list;
  const key = (pin: Pin) => {
    if (order === LIST_ORDER.NEW) {
      const parts = timeParts(pin.at);
      return [parts ? -parts.t : Infinity, -pin.id];
    }
    const at = pinPlace(pin),
      docIndex = DOCS.findIndex((entry) => entry.key === pdoc(pin));
    return [
      docIndex < 0 ? DOCS.length : docIndex,
      typeof at.page === 'number' ? at.page : 0,
      pin.lo == null ? Infinity : pin.lo,
      at.frac ? at.frac[1] : Infinity,
      pin.id,
    ];
  };
  // Two missing values subtract to NaN, which falls through to the next key as a tie does.
  return list
    .map((pin) => ({ p: pin, k: key(pin) }))
    .sort((left, right) => {
      for (let i = 0; i < left.k.length; i++) {
        const difference = left.k[i] - right.k[i];
        if (difference) return difference;
      }
      return 0;
    })
    .map((entry) => entry.p);
}
// One list section's cards as Html, in the list's order; newest first, a day line stands over each day's first card.
// Its name is worked out here, so it is right from the next draw on when the date turns. An undo row of the section
// (sec: 'open', 'review') whose card has left gets an empty slot where its pin stands in that order, under its day's
// line, which stays while the row does if the pin was that day's only card (drawOffers puts the row in the slot). In
// the server's order the row follows the card drawn before it.
function cardRows(list: Pin[], section: string): Html {
  const now = Date.now(),
    slots = new Map<Pin, number>();
  let day = '';
  if (ORDER !== LIST_ORDER.ID)
    for (const notice of NOTICES.values())
      if (
        notice.place === NOTICE_PLACE.ROW &&
        notice.sec === section &&
        notice.rec &&
        !list.some((pin) => pin.id === notice.pin)
      )
        slots.set(notice.rec, notice.n);
  return html`${orderPins(list.concat([...slots.keys()]), ORDER).map((pin) => {
    const dayText = ORDER === LIST_ORDER.NEW ? dayName(pin.at, now) : '',
      over = dayText && dayText !== day ? html`<div class="day-line"><span>${dayText}</span></div>` : '';
    if (dayText) day = dayText;
    const slot = slots.get(pin);
    return html`${over}${slot ? html`<div class="nt-slot" data-slot="${slot}"></div>` : card(pin)}`;
  })}`;
}
// Where a notice's undo row goes in a list section's box when the list drew no slot for it (the row came after that
// draw): where the list's next draw puts its slot (cardRows), so that draw moves nothing. Its place is by orderPins
// among what is drawn - the cards and the other rows that know their pins: after the one before it when that is of its
// day (newest first; in the page order always), else before the one after it when that is, else, its day having nothing
// else, under a line made for it between the two, which stays while the row does (dropBareDayLines). In the server's
// order, or for a row that does not know its pin, it follows the card drawn before it (the notice's prev), else it goes
// first.
function placeRow(box: HTMLElement, notice: Notice, row: HTMLElement) {
  const cardBefore = notice.prev != null ? box.querySelector('.pin.card[data-id="' + notice.prev + '"]') : null;
  if (!notice.rec || ORDER === LIST_ORDER.ID) {
    if (cardBefore) cardBefore.after(row);
    else box.prepend(row);
    return;
  }
  const drawn: Map<Pin, Element> = new Map();
  for (const element of findAll(box, ':scope > *', HTMLElement)) {
    const drawnPin = element.matches('.pin.card')
      ? findAnyPin(Number(element.dataset.id))
      : element.matches('.nt-row')
        ? (NOTICES.get(Number(element.dataset.n)) || {}).rec || null
        : null;
    if (drawnPin && drawnPin !== notice.rec) drawn.set(drawnPin, element);
  }
  const order = orderPins([...drawn.keys(), notice.rec], ORDER),
    index = order.indexOf(notice.rec),
    before = order[index - 1],
    after = order[index + 1],
    now = Date.now();
  const day = (pin: Pin | undefined) => (pin && ORDER === LIST_ORDER.NEW ? dayName(pin.at, now) : ''),
    dayText = day(notice.rec);
  // The pins beside notice.rec in the order are drawn ones: each has its element in drawn.
  const beforeElement = before && drawn.get(before),
    afterElement = after && drawn.get(after);
  if (beforeElement && day(before) === dayText) {
    beforeElement.after(row);
    return;
  }
  if (afterElement && day(after) === dayText) {
    afterElement.before(row);
    return;
  }
  const dayLine = document.createElement('div'),
    dayLabel = document.createElement('span');
  dayLine.className = 'day-line';
  dayLine.append(dayLabel);
  dayLabel.textContent = dayText;
  if (beforeElement) beforeElement.after(dayLine);
  else if (afterElement) {
    const over = afterElement.previousElementSibling;
    (over && over.matches('.day-line') ? over : afterElement).before(dayLine);
  } else box.prepend(dayLine);
  if (dayText) dayLine.after(row);
  else dayLine.replaceWith(row);
} // the page order has no day lines
// Takes out a day line with nothing of its day under it - its last undo row gone - in the open and review sections.
function dropBareDayLines() {
  for (const dayLine of $$('#pins>.day-line,#review-pins>.day-line')) {
    const next = dayLine.nextElementSibling;
    if (!next || next.matches('.day-line')) dayLine.remove();
  }
}
// [최신순 | 위치순 | 번호순]: shown while the open or review section shows a card, the list's order checked.
function drawOrderControl(any: boolean) {
  const control = $('#list-order');
  control.hidden = !any;
  for (const button of control.querySelectorAll('button')) {
    const on = button.dataset.order === ORDER;
    button.classList.toggle('on', on);
    button.setAttribute('aria-checked', String(on));
  }
  roveSegment(control);
} // the group's one Tab stop is the order now chosen (main.ts)
export {
  drawSectionHead,
  orderPins,
  cardRows,
  placeRow,
  dropBareDayLines,
  drawOrderControl,
  derivePinLists,
  listOpen,
  listDone,
  listReview,
};
