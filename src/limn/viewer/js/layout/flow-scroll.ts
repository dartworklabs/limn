// ------------------------------------------------ Scrolling the reading area: jumps, glides and arrival
// A jump's target and the glide that takes the pages there, the scroll a hand made, and the watch that lands a jump
// where it says once the pages rest (arrivalWatch); every surface and the pin list jump through these.
import { DOC, scrollMotion } from '../app/state.ts';
import { $ } from '../platform/dom.ts';
// The pages rest on a jump's place within this (a glide ends on or next to its pixel).
const FIGURE_REST_PX = 2;
// Every jump of the PDF area - a page, an outline entry's place, a card's [보기]; each glide starts this watch with its
// place, a function that measures it now - lands where it says once the pages rest. The glide's place is reckoned at
// its start, and the layout can still move under it: a save's list reload redraws hundreds of lines and stalls the
// glide past its guard (JUMP_TARGET lapses after a second), which gives scroll anchoring back, and the anchoring's
// adjustment can leave the figure tens to hundreds of pixels off; a line fitted on the way moves the pages after it,
// and a glide may not be written to (letLineBlocks). So each time the pages come to rest - after ARRIVAL_REST_MS
// without a scroll, the glide guard down - it measures the place again and glides the rest (glideTo: the guard and the
// held anchoring again), at most ARRIVAL_FIXES times, until ARRIVAL_SETTLE_MS after the rest that found nothing to do:
// each correction counts the window again from its own rest, which is always measured. A window counted from the first
// rest would close on a correction stopped on its way, whose guard lapses up to two seconds later, and leave the figure
// short by what remains. It only settles what nobody asked for: anything the person does meanwhile - a press, a key, a
// wheel or a touch anywhere, a window resize - lets it go (arrivalLetGo), for that starts a move of its own (a card's
// mark, a search hit, a zoom, another page) the watch must not undo; so do the person's scroll (HAND_ON_PAGES), another
// document and the pages not shown. A script that scrolls to show something lets it go too, with no input before it
// (endJumpForScroll: a search hit landing as the PDF's text is read, in the middle of a jump); a script that only keeps
// what is on screen does not, and may stop the glide: the place moved with it, and the settling goes on. A scroll by
// anything else, once the pages have rested at the place, lets it go at that rest: the place stayed and the pages left
// it, which is no layout's doing (at). A new jump replaces it. An instant jump needs no watch: nothing is on its way
// when a pass comes, and the pass keeps the view itself.
const ARRIVAL_REST_MS = 120,
  ARRIVAL_SETTLE_MS = 2000,
  ARRIVAL_FIXES = 3;
let ARRIVAL: {
    place: () => number | null;
    hand: number;
    doc: string | null;
    fixes: number;
    until: number;
    at: number | null;
  } | null = null,
  ARRIVAL_TIMER = 0;
/** @param place - the scrollTop the jump goes to, measured now; null once it is gone */
function arrivalWatch(place: () => number | null) {
  ARRIVAL = { place, hand: HAND_SCROLL_AT, doc: DOC, fixes: 0, until: 0, at: null };
  arrivalSoon();
}
// Measures again at the next rest: ARRIVAL_REST_MS from now, unless another scroll comes first.
function arrivalSoon() {
  clearTimeout(ARRIVAL_TIMER);
  ARRIVAL_TIMER = setTimeout(arrivalSettle, ARRIVAL_REST_MS);
}
// Ends the watch: the person or a script has started a move of its own.
function arrivalLetGo() {
  if (!ARRIVAL) return;
  ARRIVAL = null;
  clearTimeout(ARRIVAL_TIMER);
}
// The watch at a rest: lets go, waits for the glide, records the pages at the place, or glides the rest.
function arrivalSettle() {
  const arrival = ARRIVAL,
    pdfArea = $('#left');
  if (!arrival) return;
  if (arrival.hand !== HAND_SCROLL_AT || arrival.doc !== DOC || !pdfArea.getClientRects().length) {
    ARRIVAL = null;
    return;
  }
  // Still on its way.
  if (JUMP_TARGET !== null || isAutoScrolling()) {
    arrivalSoon();
    return;
  }
  const now = performance.now();
  if (!arrival.until) arrival.until = now + ARRIVAL_SETTLE_MS;
  else if (now > arrival.until) {
    ARRIVAL = null;
    return;
  }
  const place = arrival.place();
  if (place === null) {
    ARRIVAL = null;
    return;
  }
  const to = Math.max(0, Math.min(pdfArea.scrollHeight - pdfArea.clientHeight, place));
  if (Math.abs(pdfArea.scrollTop - to) <= FIGURE_REST_PX) {
    arrival.at = to;
    return;
  }
  if (arrival.fixes >= ARRIVAL_FIXES || (arrival.at !== null && Math.abs(arrival.at - to) <= FIGURE_REST_PX)) {
    ARRIVAL = null;
    return;
  }
  arrival.fixes++;
  arrival.until = 0;
  arrival.at = null;
  glideTo(to);
  arrivalSoon();
}
// Whether the pages are gliding where a jump sent them (the outline, the page list, a card's [보기]): the PDF area is
// scrolling
// - from a scroll event to its scrollend (where the browser has none, 160ms after the last scroll) - and no wheel,
//   touch,
// press or scrolling key of the person's came in the 500ms before it began. While it glides the page under the reading
// line is one it passes, not the one asked for: a verdict key or Enter then would act on a page scrolled past. A scroll
// the person makes goes on acting at once; an instant jump ends at once.
let LAST_SCROLL_AT = 0,
  HAND_SCROLL_AT = 0,
  IS_GLIDING = false,
  JUMP_TARGET: number | null = null;
const HAND_ON_PAGES = () => {
  HAND_SCROLL_AT = performance.now();
  IS_GLIDING = false;
  setJumpTarget(null);
}; // the person takes the pages over
// A script is about to scroll the PDF area to show something - a search hit, a mark, a box, a line, another document -
// so a jump on its way is over: its guard comes down, and its settling, which would glide the pages back, lets go. No
// input need come before: a search hit lands when the PDF's text has been read. A write that only keeps what is on
// screen across a layout change does not come here (restoreAnchor, letLineBlocks, setSelectMode, zoomRestore,
// settleBesideTurn): it moves with the place, so the settling stays right. test_viewer_scroll_writes.py holds the list:
// a new scripted scroll has to be put in it. Given what it shows as a place, the pages settle there when a glide was on
// its way: the write stops it a frame or two late.
function endJumpForScroll(place?: () => number | null) {
  arrivalLetGo();
  if (JUMP_TARGET === null) return;
  setJumpTarget(null);
  IS_GLIDING = false;
  if (place) arrivalWatch(place);
}
// Sets where a jump is going (JUMP_TARGET, null when none), and while it goes holds the PDF area's scroll anchoring off
// (#left.pv-glide, frame.css). WebKit ends a smooth scroll at any anchoring adjustment of its scroller, and on the way
// the lines are drawn again as each page passes under the reading line, so on a phone a long jump would rest short of
// its page. The glide's place is reckoned at its start and nothing above it changes size on the way (the lines keep
// their heights, a far one its drawn one), so there is nothing for anchoring to keep in the meantime. A jump that does
// not end at its place - the browser stopped it short, a document switch or a rebuild took the pages over, a late
// scroll end of an earlier scroll came instead of its own - is let go once the pages have been still for a second, as
// the guard lets it go (isAutoScrolling): the hold is never left on, which would take anchoring from a line changing
// height above the view. Checked past settle()'s timer window (IDLE_TIMER_MS) so that a test waiting for quiet does not
// wait it out.
let JUMP_TIMER = 0;
function setJumpTarget(target: number | null) {
  JUMP_TARGET = target;
  $('#left').classList.toggle('pv-glide', target !== null);
  clearTimeout(JUMP_TIMER);
  if (target !== null) JUMP_TIMER = setTimeout(lapseJump, 1100);
}
function lapseJump() {
  if (JUMP_TARGET === null) return;
  if (performance.now() - LAST_SCROLL_AT >= 1000) setJumpTarget(null);
  else JUMP_TIMER = setTimeout(lapseJump, 1100);
}
const HAS_SCROLLEND = 'onscrollend' in window;
function isAutoScrolling() {
  return IS_GLIDING && performance.now() - LAST_SCROLL_AT < (HAS_SCROLLEND ? 1000 : 160);
}
// Every smooth jump of the PDF area starts here (a page, an outline entry's place, a card's [보기]): it is a glide from
// now, not from its first scroll event a frame later, in which a digit would act on the page being left, and whatever
// the hand did just before - a recent wheel would make the guard take the jump for the person's own scroll. Nothing to
// glide (reduced motion, or already there): no guard, no scroll event would end it. Returns how the jump's scroll goes
// (scrollMotion, read once here, so the guard and the scroll agree).
/** @param to - the scrollTop it goes to */
function armGlide(to: number): ScrollBehavior {
  const area = $('#left'),
    top = Math.max(0, Math.min(area.scrollHeight - area.clientHeight, to)),
    how = scrollMotion();
  if (how === 'smooth' && Math.abs(top - area.scrollTop) > 1) {
    setJumpTarget(top);
    IS_GLIDING = true;
    LAST_SCROLL_AT = performance.now();
  } else if (JUMP_TARGET !== null) {
    setJumpTarget(null);
    IS_GLIDING = false;
  } // this scroll replaces a glide in flight (reduced motion turned on during it): its guard goes with it
  return how;
}
function glideTo(top: number) {
  $('#left').scrollTo({ top, behavior: armGlide(top) });
}
/** The scrollTop that brings an element to the top of the PDF area, or its middle to the area's middle (center). */
function scrollTopFor(element: Element, block?: 'start' | 'center') {
  const area = $('#left'),
    rect = element.getBoundingClientRect(),
    areaRect = area.getBoundingClientRect();
  return (
    area.scrollTop +
    (block === 'center'
      ? rect.top + rect.height / 2 - (areaRect.top + area.clientTop + area.clientHeight / 2)
      : rect.top - areaRect.top - area.clientTop)
  );
}
function glideInto(element: Element, block?: 'start' | 'center') {
  element.scrollIntoView({ behavior: armGlide(scrollTopFor(element, block)), block: block || 'start' });
}

// JUMP_TARGET: the scrollTop a jump is going to

// Set IS_GLIDING and LAST_SCROLL_AT, which this module declares, for the scroll listeners of verdict/flow-line.ts:
// the assignment each made, nothing more.
function setGliding(value: boolean) {
  IS_GLIDING = value;
}
function setLastScrollAt(value: number) {
  LAST_SCROLL_AT = value;
}
export {
  setGliding,
  setLastScrollAt,
  FIGURE_REST_PX,
  ARRIVAL_REST_MS,
  ARRIVAL_SETTLE_MS,
  ARRIVAL_FIXES,
  ARRIVAL,
  ARRIVAL_TIMER,
  arrivalWatch,
  arrivalSoon,
  arrivalLetGo,
  LAST_SCROLL_AT,
  HAND_SCROLL_AT,
  IS_GLIDING,
  JUMP_TARGET,
  HAND_ON_PAGES,
  endJumpForScroll,
  setJumpTarget,
  HAS_SCROLLEND,
  isAutoScrolling,
  glideTo,
  scrollTopFor,
  glideInto,
};
