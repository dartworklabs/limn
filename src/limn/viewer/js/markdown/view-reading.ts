/** Track the reading anchor through scrolling, heading jumps, redraws and reflow. */
import { $, findAll, findMaybe, findClosest } from '../platform/dom.ts';
import { setReadingSpot, MARKDOWN_VIEW } from './state.ts';
import { isMarkdownDoc } from '../documents/state.ts';
import { DOC, scrollMotion } from '../app/state.ts';
import { revealBox, selectionRoom } from '../pdf/input-selection.ts';
import { setOutlineSelected, markOutline } from '../pdf/view-outline.ts';
import { endJumpForScroll } from '../layout/flow-scroll.ts';

let HEADING_JUMP: { el: HTMLElement; doc: string | null } | null = null;
// The elements that carry lines, in document order (line spans and blocks). Their tops never decrease in that order - a
// block precedes what it holds and stands no lower - so the one at a height is found by halving (lineElementAt), never
// by measuring them all.
function lineElements() {
  const column = $('#md');
  return column ? findAll(column, '[data-line],[data-lo]', HTMLElement) : [];
}
// The last of elements whose top is at or above y (viewport px), or null before the first. O(log n) measures.
function lineElementAt(elements: HTMLElement[], y: number) {
  let low = 0,
    high = elements.length - 1,
    at = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (elements[middle].getBoundingClientRect().top <= y) {
      at = middle;
      low = middle + 1;
    } else high = middle - 1;
  }
  return at < 0 ? null : elements[at];
}
// The reading spot: the line span or block at the pane's top (lineElementAt), its first line and the px of it above
// that top.
function readingAnchor() {
  const pane = $('#left');
  if (!$('#md') || !MARKDOWN_VIEW.lines.length) return null;
  const top = pane.getBoundingClientRect().top,
    element = lineElementAt(lineElements(), top);
  return element
    ? {
        line: +(element.dataset.line || element.dataset.lo || 0),
        off: top - element.getBoundingClientRect().top,
        top: pane.scrollTop,
      }
    : null;
}
function restoreReadingAnchor(anchor: { line: number; off: number; top: number } | null) {
  const pane = $('#left');
  if (!anchor) {
    return;
  }
  const element = lineLeaves(anchor.line, anchor.line)[0];
  if (!element) {
    pane.scrollTop = anchor.top;
    return;
  }
  pane.scrollTop += element.getBoundingClientRect().top + anchor.off - pane.getBoundingClientRect().top;
}
// ---------------- The reading spot across a reflow (docs/handbook/viewer.md §그리기)
// The column reflows the moment its width changes - a rotation, the panel collapsing beside it, a window resized, the
// outline opening - and the scroll offset alone then stands on other lines (the top line moves by tens of lines). So
// the spot is read while the width stands - on each scroll's frame and after each draw (readSpot) - and put back once
// the width has moved (keepReadingSpot): from relayout, and from the column's ResizeObserver, which runs after the
// layout and before the paint. A scroll the reflow itself makes (an offset cut back to the new height) reads only after
// the spot is back. Reads the spot now: the line element at the document area's top (lineElementAt) and how far down it
// the top is (frac, 0-1, and past: the px below the element's end when the top falls in the room after it - the rest of
// a line's leading, a block's margin, which no reflow changes; el null at the very top), the column's width and the
// pane's scroll offset (top), and whether the chosen lines (.md-sel) are on screen. A read at a width that is not the
// spot's is left for keepReadingSpot - the reflow moved what it would read - unless force (a new draw: nothing to
// keep). While the column is not laid out (hidden under the changes view, or 0 wide) nothing is read: the spot read
// before stays - a redraw there too (showDocumentNode) - for keepReadingSpot to put back once the column is shown
// again. A spot a hidden redraw left to be put back (again) is not read over before that, even at its width: the scroll
// the column's showing makes is not the person's.
function readSpot(force?: boolean) {
  const column = $('#md'),
    pane = $('#left');
  if (!isMarkdownDoc() || !column || MARKDOWN_VIEW.shown !== DOC) {
    setReadingSpot(null);
    return;
  }
  const spot = MARKDOWN_VIEW.spot,
    width = column.getBoundingClientRect().width;
  if (!isColumnLaidOut(width)) return;
  if (!force && spot && spot.doc === DOC && (spot.w !== width || spot.again)) return;
  const top = pane.getBoundingClientRect().top,
    element = pane.scrollTop > 0 ? lineElementAt(lineElements(), top) : null,
    rect = element && element.getBoundingClientRect(),
    into = rect ? top - rect.top : 0;
  setReadingSpot({
    doc: DOC,
    w: width,
    top: pane.scrollTop,
    el: element,
    line: element ? +(element.dataset.line || element.dataset.lo || 0) : 0,
    key: element ? (element.dataset.line ? 'line' : 'lo') : '',
    frac: rect && rect.height ? Math.min(1, Math.max(0, into / rect.height)) : 0,
    past: rect ? Math.max(0, into - rect.height) : 0,
    off: null,
    sel: isChosenSeen(),
    again: false,
  });
}
// The element that stands for the spot's line now: its element if still drawn, else the one a redraw drew for that line
// - the same kind (a line span, a block starting there), else the first that carries the line (lineLeaves), else - the
// line is gone, the source got shorter - the nearest line kept before it (nearestLineElement). null: the very top.
function spotElement(spot: NonNullable<typeof MARKDOWN_VIEW.spot>) {
  if (spot.el && spot.el.isConnected) return spot.el;
  if (!spot.line) return null;
  const column = $('#md'),
    attribute = spot.key === 'lo' ? 'data-lo' : 'data-line',
    element = column ? findMaybe(column, '[' + attribute + '="' + spot.line + '"]', HTMLElement) : null;
  return element || lineLeaves(spot.line, spot.line)[0] || nearestLineElement(spot.line);
}
// The last line element that starts at or before line (lineElements are in document order, their first lines never
// going back), or null when none does.
function nearestLineElement(line: number) {
  const elements = lineElements();
  let at = -1;
  for (let i = 0; i < elements.length; i++) {
    if (+(elements[i].dataset.line || elements[i].dataset.lo || 0) > line) break;
    at = i;
  }
  return at < 0 ? null : elements[at];
}
// Whether element carries line: a line span of it, or a block whose lines first..last hold it.
function carriesLine(element: HTMLElement, line: number) {
  if (element.dataset.line) return +element.dataset.line === line;
  const first = +(element.dataset.lo || 0),
    last = +(element.dataset.hi || element.dataset.lo || 0);
  return first <= line && line <= last;
}
// Puts the spot back after the column's width moved: the same point of the same line element at the area's top (as far
// into it, as far past its end; the very top stays the top), then - when the chosen lines were on screen - those lines
// back into view (revealBox, every layout), and reads the spot at the new width. Nothing moves while the width is the
// spot's - unless the document was drawn again while the column was hidden (again: the scroll offset then stands on
// other lines even at the same width) - nor while the column is not laid out (isColumnLaidOut): the spot waits for the
// column's next width. A write is held under half a pixel. During a jump to a heading (HEADING_JUMP) the spot is
// only a point the scroll passes: the jump is aimed again at its heading instead (goOnToHeading).
function keepReadingSpot() {
  const spot = MARKDOWN_VIEW.spot,
    column = $('#md'),
    pane = $('#left');
  if (!spot || spot.doc !== DOC || !column || !isMarkdownDoc() || MARKDOWN_VIEW.shown !== DOC) return;
  const width = column.getBoundingClientRect().width;
  if ((width === spot.w && !spot.again) || !isColumnLaidOut(width)) return;
  if (goOnToHeading()) {
    readSpot(true);
    return;
  } // a jump in flight goes on to its heading's new place: the spot is a point it passes
  const element = spotElement(spot);
  if (!element) {
    if (pane.scrollTop > 0) pane.scrollTop = 0;
  } else {
    const rect = element.getBoundingClientRect(),
      into =
        !spot.line || carriesLine(element, spot.line)
          ? spot.off !== null
            ? spot.off
            : spot.frac * rect.height + spot.past
          : 0; // a nearer line kept: its top
    const drift = rect.top + into - pane.getBoundingClientRect().top;
    if (Math.abs(drift) >= 0.5) pane.scrollTop += drift;
  }
  if (spot.sel) revealBox(findMaybe(document, '#md .md-sel', HTMLElement), true);
  readSpot(true);
}
// Something above the reading spot changed its height while the width stood - an image that got its size or gave way to
// its alt text (onImageLoad, onImageError): the spot is put back as after a reflow (keepReadingSpot), one model for
// both. While the column is hidden (under the changes view) nothing can be measured: the spot waits, marked again, for
// the column to be shown. The spot put back is the one refreshMovedSpot made sure of just before the change.
function putSpotBack() {
  const spot = MARKDOWN_VIEW.spot;
  if (!spot || spot.doc !== DOC) return;
  spot.again = true;
  keepReadingSpot();
}
// Just before the page changes the column's layout (an image's new size, onImageLoad, onImageError): when the pane
// stands elsewhere than where the spot was read (top, to 1px), something has moved the pane since - a scroll whose
// frame has not come (the pane's scroll listener reads on the frame, and on a renderer too busy to paint an image's
// load comes first), the browser's find, a focus or another script, the browser's scroll anchoring after another change
// - and the spot is read where the pane stands, so putSpotBack does not undo that move. The image's own change comes
// after this check (an image's box changes nowhere but in those handlers, sizeImage), but a reflow at the same width
// may have come before it - a web font swapped in, a run of HTML blocks opened or closed - and one that shortened the
// document may have moved the offset itself: the browser cuts an offset the pane can no longer scroll to back to its
// new end. That one cut, and no other offset, is not taken for a move: the offset read before beyond what the pane can
// scroll now (its end, scrollHeight - clientHeight) and the pane standing at that end, to 1px. The spot read before is
// then kept for putSpotBack to put back across the reflow, as after a width's (keepReadingSpot); a move to the end made
// before the same frame - End, or a scroll the cut then ate - goes back with it. Any other offset is a move, the cut's
// too once a move took the pane from that end (Home after a font's reflow), whatever reflowed the column: told by the
// offset and the scroll range alone, the check asks nothing of the page's other changes - whether they read the spot
// again after them. An image's own change reads it after (putSpotBack, or afterImageChange during a heading jump), so
// the next image's check starts from the layout this one left, and an End after a failed image shortened the document
// is not taken for a cut. Not while the width moved (a reflow is keepReadingSpot's), nor while a redraw or a load under
// the hidden column waits (again), nor while the column is not laid out (a hidden pane's offset reads 0).
function refreshMovedSpot() {
  const spot = MARKDOWN_VIEW.spot,
    column = $('#md'),
    pane = $('#left');
  if (!spot || spot.doc !== DOC || spot.again || !column || !isMarkdownDoc() || MARKDOWN_VIEW.shown !== DOC) return;
  const width = column.getBoundingClientRect().width;
  if (width !== spot.w || !isColumnLaidOut(width)) return;
  const end = pane.scrollHeight - pane.clientHeight;
  if (spot.top > end && pane.scrollTop >= end - 1) return; // cut back to a shorter end
  if (Math.abs(pane.scrollTop - spot.top) >= 1) readSpot(true);
}
// Whether the document column is laid out at width (#md's): shown (#left has boxes - not under the changes view) and
// wider than 0.
function isColumnLaidOut(width: number) {
  return width > 0 && isColumnShown();
}
function isColumnShown() {
  return $('#left').getClientRects().length > 0;
}
// Whether any of the chosen lines (.md-sel) stands in the part of the document area they can be seen in
// (selectionRoom).
function isChosenSeen() {
  const chosen = document.querySelector('#md .md-sel');
  if (!chosen) return false;
  const rect = chosen.getBoundingClientRect(),
    room = selectionRoom();
  return rect.bottom > room.top && rect.top < room.bottom - 8;
}
// The elements that stand for lines first..last: each line span in range, and each block in range that has no line
// spans of its own and no smaller block in range (a rule, an HTML block) - the smallest things on screen that carry
// those lines. A table cell's line stands for its row: the row is what is tinted, so a pinned row reads as one band.
function lineLeaves(first: number, last: number) {
  const column = $('#md');
  if (!column) return [];
  const lines = findAll(column, '[data-line]', HTMLElement).filter((element) => {
    const line = +(element.dataset.line || 0);
    return line >= first && line <= last;
  });
  const blocks = findAll(column, '[data-lo]', HTMLElement).filter((element) => {
    const block = element,
      start = +(block.dataset.lo || 0),
      end = +(block.dataset.hi || 0);
    return start <= last && end >= first && !block.querySelector('[data-line],[data-lo]');
  });
  const out = new Set<HTMLElement>();
  for (const element of [...lines, ...blocks]) {
    const row = findClosest(element, 'tr[data-lo]', HTMLElement);
    out.add(row && column.contains(row) ? row : element);
  }
  return [...out];
}
// Goes to heading index: the pane scrolls (smoothly unless reduced motion is asked for) until the heading stands 8px
// under its top. The jump is kept in flight (HEADING_JUMP) until it lands there (endLandedJump) or the person
// scrolls: an image that gets its size on the way - a lazy one the scroll passes - moves the heading, and the jump goes
// on to its new place (goOnToHeading).
function goToHeading(index: number) {
  const heading = MARKDOWN_VIEW.heads[index];
  if (!heading) return;
  setOutlineSelected(index);
  markOutline();
  HEADING_JUMP = { el: heading.el, doc: DOC };
  goOnToHeading();
  endLandedJump();
}
// The scroll top that puts element 8px under the pane's top, within what the pane can scroll.
function headingScrollTop(element: HTMLElement) {
  const pane = $('#left'),
    top = pane.scrollTop + element.getBoundingClientRect().top - pane.getBoundingClientRect().top - 8;
  return Math.max(0, Math.min(top, pane.scrollHeight - pane.clientHeight));
}
// Scrolls on to the destination of the jump in flight, measured again; false when there is none (or its heading is
// gone).
function goOnToHeading() {
  const jump = HEADING_JUMP;
  if (!jump) return false;
  if (jump.doc !== DOC || !jump.el.isConnected) {
    HEADING_JUMP = null;
    return false;
  }
  endJumpForScroll();
  $('#left').scrollTo({ top: headingScrollTop(jump.el), behavior: scrollMotion() });
  return true;
}
// The jump in flight has landed when the pane stands at its destination: it ends, and that is the reading spot.
function endLandedJump() {
  const jump = HEADING_JUMP;
  if (!jump) return;
  if (jump.doc !== DOC || !jump.el.isConnected) {
    HEADING_JUMP = null;
    return;
  }
  if (Math.abs($('#left').scrollTop - headingScrollTop(jump.el)) <= 1) {
    HEADING_JUMP = null;
    readSpot(true);
  }
}
// The person scrolls (a wheel, a touch, a press on the pane or its scroll bar, a key): a jump in flight ends where it
// is - its smooth scroll too, running or only asked for, so what the person's input does next starts from here. The
// pane's offset is written a pixel off and back, in one task (nothing is drawn between) - down at the very top, up
// elsewhere, so the first write moves at either end (Home's place, End's): a write of the offset it already has does
// not end the scroll in Firefox, whose compositor (APZ) runs it - once that scroll has moved the pane, such a write
// sends the compositor nothing, and the scroll would go on to the heading with the key's or the wheel's own step added.
// A write that moves the offset ends it there, in every engine.
function stopHeadingJump() {
  if (!HEADING_JUMP) return;
  HEADING_JUMP = null;
  const pane = $('#left'),
    top = pane.scrollTop;
  pane.scrollTo({ top: top > 0 ? top - 1 : top + 1, behavior: 'instant' });
  pane.scrollTo({ top: top, behavior: 'instant' });
}

export {
  lineLeaves,
  isColumnShown,
  isChosenSeen,
  readSpot,
  readingAnchor,
  restoreReadingAnchor,
  keepReadingSpot,
  refreshMovedSpot,
  goOnToHeading,
  putSpotBack,
  goToHeading,
  lineElementAt,
  lineElements,
  endLandedJump,
  stopHeadingJump,
};
