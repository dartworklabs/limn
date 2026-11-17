// ------------------------------------------------ Going to a page, or a spot on one
// Where a page, a figure or a picked heading lands in the PDF area: under the free area's top with the reading line on
// it, a figure page at its figure. The outline, the page field and list, and a card's [보기] go through these.
import { $ } from '../platform/dom.ts';
import {
  scrollTopFor,
  glideInto,
  arrivalWatch,
  isAutoScrolling,
  FIGURE_REST_PX,
  glideTo,
  JUMP_TARGET,
  ARRIVAL,
} from '../layout/flow-scroll.ts';
import { META } from '../app/state.ts';
import { popoverFreeArea } from './view-area.ts';
// Px between the top of the free PDF area and a picked heading.
const OUTLINE_PICK_GAP = 8;
// #left's scrollTop that puts the place `frac` down a page box `gap` px under the top of the free PDF area
// (popoverFreeArea: under the section strip, the instance band or the select mode's bar) - lower when it stands near
// its page's bottom, so that the reading line (readingDepth) still falls on its page and the strip names it - as far as
// the pages scroll.
function spotTop(pageBox: HTMLElement, frac: number, gap: number) {
  const pdfArea = $('#left'),
    rect = pageBox.getBoundingClientRect(),
    y = rect.top + frac * rect.height,
    read = pdfArea.getBoundingClientRect().top + readingDepth(pdfArea);
  const want = Math.max(popoverFreeArea().top + gap, read + 2 - (rect.bottom - y));
  return Math.max(0, Math.min(pdfArea.scrollHeight - pdfArea.clientHeight, Math.round(pdfArea.scrollTop + y - want)));
}
// How far under the top of the PDF pane the reading line is: a quarter of the pane's height, at most 160px.
function readingDepth(pane: HTMLElement | null) {
  return pane ? Math.min(160, pane.clientHeight / 4) : 0;
}

// Arriving at a page - from the outline, a page field or the page list (goPage) and from a card's [보기] (jumpPin,
// jumpToPageLine): a figure page, one whose map names its figure body (meta figure_top), at its figure (figureTop); any
// other page at its top.
// The same arrival again while the pages rest on that figure goes to the page's top, and once more to the figure
// (docs/handbook/viewer.md §그림 쪽 도착). Each is a glide (glideTo, glideInto), so the keys wait for it to end.
function arrivePage(pageNumber: number) {
  const pageBox = document.getElementById('p' + pageNumber);
  if (!pageBox) return;
  const to = figureTop(pageNumber),
    pdfArea = $('#left');
  const pageTop = () => {
    const currentBox = document.getElementById('p' + pageNumber);
    return currentBox ? scrollTopFor(currentBox) : null;
  };
  if (to === null) {
    glideInto(pageBox);
    arrivalWatch(pageTop);
    return;
  }
  const top = !isAutoScrolling() && Math.abs(pdfArea.scrollTop - to) <= FIGURE_REST_PX;
  if (top) glideInto(pageBox);
  else glideTo(to);
  arrivalWatch(top ? pageTop : () => figureTop(pageNumber));
}
// The points of the page kept above an arrived figure at most: its label line ('PL18 · 지금 판') has no element.
const FIGURE_ROOM_POINTS = 24;
// Whether the last jump is still on its way to its place: gliding (the guard, as above) or owed its settling - its
// watch has neither found the pages at the place nor let it go, and may glide the rest. A stop between scrolls is no
// rest while either holds, however long: a busy machine's frames come late. An outline pick waits on this before it
// lets go (outlinePickRest).
function jumpOnItsWay() {
  return JUMP_TARGET !== null || isAutoScrolling() || (ARRIVAL !== null && ARRIVAL.at === null);
}
// #left's scrollTop of a page's figure arrival - its figure's top edge under the free PDF area's top (spotTop) with up
// to FIGURE_ROOM_POINTS of the page above it, down to the element above (figure_above) or else the page's top, and at
// least OUTLINE_PICK_GAP px - or null for a page without a figure body. In page points, so the room is the label line's
// at every zoom. Room past the page's top would stand the page below the reading line at a large zoom: the line would
// read the page before it.
function figureTop(pageNumber: number) {
  const pageBox = document.getElementById('p' + pageNumber),
    pageFacts = META && META.pages ? META.pages[pageNumber - 1] : null;
  if (!pageBox || !pageFacts || typeof pageFacts.figure_top !== 'number' || !(pageFacts.pt_h > 0)) return null;
  const height = pageBox.getBoundingClientRect().height,
    free = (pageFacts.figure_top - (typeof pageFacts.figure_above === 'number' ? pageFacts.figure_above : 0)) * height;
  return spotTop(
    pageBox,
    pageFacts.figure_top,
    Math.max(OUTLINE_PICK_GAP, Math.min((FIGURE_ROOM_POINTS * height) / pageFacts.pt_h, free)),
  );
}
// Goes to the page typed in the tool bar's [쪽 이동] field, or to the page given.
function goPage(entry?: number) {
  arrivePage(parseInt(entry === undefined ? $('#jump').value : entry, 10));
}
// The page a typed entry goes to in a document of pageCount pages: a whole number clamped to 1..pageCount; null for an
// empty or non-number entry, which goes nowhere. Pure.
function clampPage(entry: string, pageCount: number) {
  const text = String(entry == null ? '' : entry).trim();
  if (!/^-?\d+$/.test(text) || !(pageCount >= 1)) return null;
  return Math.min(pageCount, Math.max(1, parseInt(text, 10)));
}
export { figureTop, arrivePage, jumpOnItsWay, clampPage, goPage, OUTLINE_PICK_GAP, spotTop, readingDepth };
