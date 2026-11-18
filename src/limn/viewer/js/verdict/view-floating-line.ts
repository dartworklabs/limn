import { findMaybe, $$, $ } from '../platform/dom.ts';
import { keepFocusOnLine } from './view-line.ts';

// The reason popover's side (placePopover): above its line, as drawn - unless the room above inside what the PDF area
// shows (under the section strip) is too short for it while the room below holds it: then under the line
// (.pv-pop-below). Where neither holds it, the larger side, the popover no taller than that (--pv-pop-max; it scrolls).
// So near the top an in-place line's popover never opens under the strip and the top bar.
function placePopover() {
  const pop = findMaybe(document, '#doc .pv>.pv-pop', HTMLElement);
  $$('#doc .pv.pv-pop-below').forEach((line) => {
    if (!pop || line !== pop.parentElement) line.classList.remove('pv-pop-below');
  });
  const line = pop && pop.parentElement;
  if (!pop || !line) return;
  const area = $('#left'),
    areaRect = area.getBoundingClientRect();
  if (line.id === 'pv-panel') {
    line.classList.remove('pv-pop-below');
    line.style.removeProperty('--pv-pop-max');
    return;
  } // in the panel's flow, under its state
  let top = Math.max(areaRect.top, 0);
  const strip = document.getElementById('section-strip');
  if (strip && strip.getClientRects().length) {
    const stripRect = strip.getBoundingClientRect();
    if (stripRect.bottom > top && stripRect.top <= top + 1) top = stripRect.bottom;
  }
  const cover =
    (parseFloat(getComputedStyle(document.body).getPropertyValue('--pv-inset')) || 0) +
    (parseFloat(area.style.getPropertyValue('--pv-kb-over')) || 0);
  const bottom = areaRect.top + area.clientHeight - cover;
  if (line.style.getPropertyValue('--pv-pop-max')) line.style.removeProperty('--pv-pop-max');
  const lineRect = line.getBoundingClientRect(),
    height = pop.offsetHeight,
    above = lineRect.top - 8 - top,
    below = bottom - (lineRect.bottom + 8);
  const under = height > above && (height <= below || below > above);
  line.classList.toggle('pv-pop-below', under);
  if (height > Math.max(above, below))
    line.style.setProperty('--pv-pop-max', Math.max(0, Math.floor(under ? below : above)) + 'px');
}

// Room to read a page's end under its open reason popover. The popover stands above its line, so where the line stands
// in its place under the page the popover covers the page's end - a figure's caption, written under the plot - and no
// scroll would uncover it, since the line and the popover with it go on with the page. While a popover is open above a
// line in the pages, that line's block holds a room as tall as what the popover covers there (.pv-roomy, --pv-room: an
// empty box after the line whose negative margin gives its height back, so no page and no block moves), and the line's
// top edge is sticky where it stands (its own top). Scrolling on, the line and the popover stay while the page's end
// comes up from under them by the room, then go on with the page. The line only ever stands lower than its own place,
// never higher; scrolled back, it goes down with the page, and wherever it then stands unheld - lower, or floating - is
// where it holds next (also when the field's focus folds the line and the page moves on a phone). Held lower it floats
// over the gap and the next page's top, set off as a floating line is (isHeldLow). A sticky top wins over the floating
// bottom, so the top is never lower than the floating place (a keyboard laid over the page raises that). Opening and
// closing move nothing and nothing scrolls: closed, the room stays while the line stands lower than its place in view -
// dropping it would lift the line under the eye - and goes once the line is back in its place or out of view. The
// panel's popover is in the panel's flow, beside the page: it covers nothing. line -> the room its block holds (px) and
// that block
const POPOVER_ROOM: Map<HTMLElement, { room: number; blk: HTMLElement }> = new Map();

// The gap between a page and its line in its own place: the page's bottom margin and the line's top margin, collapsed.
function lineOwnGap(line: HTMLElement, pageElement: HTMLElement) {
  const pageMargin = parseFloat(getComputedStyle(pageElement).marginBottom) || 0,
    lineMargin = parseFloat(getComputedStyle(line).marginTop) || 0;
  return Math.max(pageMargin, lineMargin, 0) + Math.min(pageMargin, lineMargin, 0);
}

// Whether a line (its top edge at `top`, its page's bottom at `pageBottom`) stands lower than its own place, held there
// by a reason's room.
function isHeldLow(line: HTMLElement, pageElement: HTMLElement, top: number, pageBottom: number) {
  return POPOVER_ROOM.has(line) && top > pageBottom + lineOwnGap(line, pageElement) + 0.5;
}

// Whether a line (its box `rect`), with the ring its floating look paints around it, reaches over the next page's top.
function reachesNextPage(line: HTMLElement, rect: DOMRect) {
  const block = line.parentElement,
    nextBlock = block && block.nextElementSibling,
    nextPage = nextBlock && nextBlock.querySelector(':scope>.pg');
  if (!nextPage) return false;
  return (
    nextPage.getBoundingClientRect().top <
    rect.bottom + (parseFloat(getComputedStyle(line).getPropertyValue('--pv-ring')) || 0)
  );
}

function dropPopoverRoom(line: HTMLElement) {
  const room = POPOVER_ROOM.get(line);
  POPOVER_ROOM.delete(line);
  line.style.removeProperty('top');
  line.classList.remove('pv-over');
  if (room) {
    room.blk.classList.remove('pv-roomy');
    room.blk.style.removeProperty('--pv-room');
  }
} // its block, also once the line is gone from it (the side panel took it)

// Whether it lifted a held line (its floating place rose above it): the popover's side is chosen again then
// (stickReadingLine).
function placePopoverRoom(area: HTMLElement, areaRect: DOMRect): boolean {
  const pop = findMaybe(document, '#doc .pv>.pv-pop', HTMLElement);
  const open = pop && pop.parentElement && pop.parentElement.id !== 'pv-panel' ? pop.parentElement : null;
  if (!open && !POPOVER_ROOM.size) return false;
  const style = getComputedStyle(area),
    top0 = areaRect.top + area.clientTop + (parseFloat(style.paddingTop) || 0),
    // what a sticky line keeps within
    end = areaRect.top + area.clientTop + area.clientHeight - (parseFloat(style.paddingBottom) || 0);
  POPOVER_ROOM.forEach((room, line) => {
    if (line === open) return;
    const pageElement = line.previousElementSibling;
    if (!line.isConnected || !(pageElement instanceof HTMLElement) || line.parentElement !== room.blk) {
      dropPopoverRoom(line);
      return;
    }
    const rect = line.getBoundingClientRect();
    if (
      !isHeldLow(line, pageElement, rect.top, pageElement.getBoundingClientRect().bottom) ||
      rect.bottom <= areaRect.top ||
      rect.top >= areaRect.top + area.clientHeight
    )
      dropPopoverRoom(line);
  });
  if (open) {
    const previous = open.previousElementSibling,
      pageElement = previous instanceof HTMLElement ? previous : null,
      block = open.parentElement;
    const want =
      pop && pageElement && block && block.classList.contains('pgw')
        ? Math.ceil(-pop.offsetTop - lineOwnGap(open, pageElement))
        : 0; // under its line: 0 or less
    let had = POPOVER_ROOM.get(open);
    if (had && had.blk !== block) {
      dropPopoverRoom(open);
      had = undefined;
    }
    if (!had && want > 0 && block) {
      had = { room: 0, blk: block };
      POPOVER_ROOM.set(open, had);
      block.classList.add('pv-roomy');
    }
    if (had && pageElement) {
      if (want > had.room) {
        had.room = want;
        had.blk.style.setProperty('--pv-room', want + 'px');
      } // a taller popover: more room, never less while it is open
      // Its top is sticky where it stands - and lower where it comes to stand without being held (the page moved down:
      // a scroll back, or the line growing or shrinking as the field takes the focus), so the room is under it wherever
      // the person turns to read on.
      const rect = open.getBoundingClientRect(),
        stickyTop = rect.top - top0;
      if (
        !isHeldLow(open, pageElement, rect.top, pageElement.getBoundingClientRect().bottom) &&
        !(parseFloat(open.style.top) >= stickyTop)
      )
        open.style.top = stickyTop + 'px';
    }
  }
  let lifted = false;
  POPOVER_ROOM.forEach((_, line) => {
    const bottom = getComputedStyle(line).bottom;
    if (bottom === 'auto') return; // a floating line: its top stays above where it floats
    const most = end - (parseFloat(bottom) || 0) - line.getBoundingClientRect().height - top0;
    if ((parseFloat(line.style.top) || 0) > most) {
      line.style.top = most + 'px';
      lifted = true;
    }
  });
  return lifted;
}

// A phone's floating line holds [판정 취소] back (.pv-lean, components.css): unseen, not pressed, focused or heard -
// and in its place, so the line keeps its rows whether it floats or stands in its place. Taken out of the row, it would
// let the short earlier link ('이전 1건') rise into its row while the line floats, and the next page would jump under
// the finger as the line crosses its page's end. The in-place line and the card still offer it, with its 44px.
// Hysteresis keeps it from flipping at a page's end: shown, it leans once the line floats; leaning, it is shown again
// only when the line (its full height, measured when it was last shown) fits in its place under the page. Desktop and
// every other band: never.
const FULL_LINE_HEIGHT: WeakMap<HTMLElement, { h: number; gap: number }> = new WeakMap();

function leanFloatingLine(
  line: HTMLElement,
  pageElement: HTMLElement,
  rect: DOMRect,
  stuck: boolean,
  area: HTMLElement,
  areaRect: DOMRect,
) {
  if (
    !document.body.classList.contains('band-phone') ||
    !line.classList.contains('reading') ||
    !line.querySelector('.pv-cancel')
  ) {
    line.classList.remove('pv-lean');
    return;
  }
  const full = FULL_LINE_HEIGHT.get(line) || { h: 0, gap: 8 },
    pageBottom = pageElement.getBoundingClientRect().bottom;
  FULL_LINE_HEIGHT.set(line, full);
  if (!stuck) full.gap = Math.max(0, rect.top - pageBottom);
  if (!line.classList.contains('pv-lean')) {
    full.h = rect.height;
    if (stuck) {
      line.classList.add('pv-lean');
      keepFocusOnLine([line]);
    }
    return;
  }
  // Where a floating line's bottom stands: the area's bottom less its end padding and the line's sticky inset.
  const style = getComputedStyle(area),
    limit =
      areaRect.top +
      area.clientHeight -
      parseFloat(style.paddingBottom) -
      (parseFloat(getComputedStyle(line).bottom) || 0);
  if (pageBottom + full.gap + (full.h || rect.height + 64) <= limit) line.classList.remove('pv-lean');
}

export { isHeldLow, leanFloatingLine, placePopover, placePopoverRoom, reachesNextPage };
