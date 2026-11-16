// ------------------------------------------------ The note popover by the selection box (docs/handbook/viewer.md §패널 정리 '선택 상자 곁 메모', #192)
// With a mouse on the desktop and mid layouts, a drag that ends opens a small popover under the dashed box: the location, a note
// field, [자세히 →] and [저장], so the note can be written where the eye already is. The field is the composer's note - one
// value, edited from either place - and [저장] and Ctrl/⌘+Enter take savePin(), the composer's own path, so the saved chip
// with its undo and every rule of §알림 자리 hold unchanged. '@' in the field offers the composer's @-list by the field; a
// pick's tag is kept on the composer's note (mentions.js mentionModel). [자세히 →] hands over to the composer in the panel,
// which keeps the kind, the range and the overlap. Esc and a short click off the box cancel the selection as before; a press
// on the popover is a press inside the box (pressOutsideSelection). Touch and the phone keep the composer alone (it is a sheet).
import { $, KIND_NEW, LAST_PTR, LAYOUT, LAYOUT_MODE, REPICK } from './core.ts';
import { tl, tr } from './i18n.ts';
import { isRegion } from './doc-tabs.ts';
import { applySide, setSide } from './layout.ts';
import { rng } from './levels.ts';
import { COMPOSE, qHint } from './composer.ts';
import { saveDraftSoon } from './draft.ts';
import { MENTION, mentionClose, mentionEdited, mentionPlace, renderAssignNew } from './mentions.ts';
import { autoGrow } from './edit.ts';
const SEL_POP = $('#sel-pop'),
  SEL_POP_FIELD = SEL_POP.querySelector('textarea') as HTMLTextAreaElement,
  SELECTION_POPOVER_GAP = 8;
SEL_POP_FIELD._mirrorOf = $('#note') as HTMLTextAreaElement; // its @-tags are the note's, which saves them
// The box the popover belongs to; null while it is closed.
let SEL_POP_BOX = null as HTMLElement | null;
// Where a w x h popover goes for a box in the free area (rectangles {left, top, right, bottom}), gap px from the box and from
// the area's edges: below the box with its left edge, above it when below has no room, at the area's foot when neither side
// has room; moved left to stay inside the area's right edge, never past its left. Not shown when the box is outside the area
// (scrolled away). Whole pixels, so its text is drawn crisp. Pure.
function popPlace(
  box: { left: number; top: number; right: number; bottom: number },
  area: { left: number; top: number; right: number; bottom: number },
  width: number,
  height: number,
  gap: number,
): { left: number; top: number; side: string; shown: boolean } {
  const below = box.bottom + gap + height <= area.bottom - gap,
    above = box.top - gap - height >= area.top + gap;
  const top =
    below || !above
      ? Math.max(area.top + gap, Math.min(box.bottom + gap, area.bottom - gap - height))
      : box.top - gap - height;
  const left = Math.max(area.left + gap, Math.min(box.left, area.right - gap - width));
  return {
    left: Math.round(left),
    top: Math.round(top),
    side: below || !above ? 'below' : 'above',
    shown: box.bottom > area.top && box.top < area.bottom,
  };
}
// The part of the PDF area nothing covers (the select mode's frame, #sel-mode: under the section strip, above a sheet, left of an
// overlay panel and its handle), inside #left's scrollbar and under the select mode's bar while it shows.
function selPopArea() {
  const leftPane = $('#left'),
    paneRect = leftPane.getBoundingClientRect(),
    frameRect = $('#sel-mode').getBoundingClientRect(),
    bar = $('#sel-bar');
  const area = {
    left: Math.max(paneRect.left, frameRect.left),
    top: Math.max(paneRect.top, frameRect.top),
    right: Math.min(paneRect.left + leftPane.clientLeft + leftPane.clientWidth, frameRect.right),
    bottom: Math.min(paneRect.top + leftPane.clientTop + leftPane.clientHeight, frameRect.bottom),
  };
  if (bar.getClientRects().length) area.top = Math.max(area.top, bar.getBoundingClientRect().bottom);
  return area;
}
// Whether this selection gets the popover: a mouse drag outside the phone layout, not a re-place.
function wantsSelectionPopover() {
  return LAYOUT !== LAYOUT_MODE.NARROW && LAST_PTR === 'mouse' && !REPICK;
}
// Opens the popover for the box a mouse drag just drew (finishRect): the field takes the composer's note and the focus.
function openSelPop(box: HTMLElement) {
  if (!wantsSelectionPopover()) return;
  SEL_POP_BOX = box;
  SEL_POP_FIELD.value = $('#note').value;
  drawSelPop();
  if (!SEL_POP.hidden) SEL_POP_FIELD.focus({ preventScroll: true });
}
function closeSelPop() {
  SEL_POP_BOX = null;
  SEL_POP.hidden = true;
  if (MENTION.ta === SEL_POP_FIELD) mentionClose();
}
function selPopOpen() {
  return !SEL_POP.hidden;
}
// Draws the popover from the selection: the location (or '찾는 중' while the pick runs), the note's placeholder, its place. It
// closes when its box is no longer the selection's, the composer closed, the pick failed or the layout became the phone's.
function drawSelPop() {
  const selection = COMPOSE.current;
  if (
    !SEL_POP_BOX ||
    COMPOSE.box !== SEL_POP_BOX ||
    !document.contains(SEL_POP_BOX) ||
    $('#composer').hidden ||
    (!selection && !COMPOSE.picking) ||
    !wantsSelectionPopover()
  ) {
    closeSelPop();
    return;
  }
  const loc = SEL_POP.querySelector('.sp-loc');
  loc.textContent = !selection
    ? tr('찾는 중')
    : isRegion(selection)
      ? tl('쪽 {page} 영역', { page: selection.page })
      : selection.name + ' ' + rng(selection.lo as number, selection.hi as number);
  SEL_POP_FIELD.placeholder = $('#note').placeholder;
  SEL_POP.hidden = false;
  placeSelPop();
}
// Puts the popover by its box in the free area (popPlace); hidden while the box is scrolled out of it. An @-list open on its
// field goes with it, and closes while it is hidden.
function placeSelPop() {
  if (SEL_POP.hidden || !SEL_POP_BOX) return;
  if (!wantsSelectionPopover()) {
    closeSelPop();
    return;
  }
  const place = popPlace(
    SEL_POP_BOX.getBoundingClientRect(),
    selPopArea(),
    SEL_POP.offsetWidth,
    SEL_POP.offsetHeight,
    SELECTION_POPOVER_GAP,
  );
  SEL_POP.style.left = place.left + 'px';
  SEL_POP.style.top = place.top + 'px';
  SEL_POP.dataset.side = place.side;
  SEL_POP.style.visibility = place.shown ? '' : 'hidden';
  if (MENTION.ta === SEL_POP_FIELD) {
    if (place.shown) mentionPlace();
    else mentionClose();
  }
}
// One note: what is typed here is the composer's note (its @-tag preview, assignee row, question hint and draft follow), and
// what is typed in the composer shows here (a name picked there from the @-list too: mentions.js mentionMirror).
SEL_POP_FIELD.addEventListener('input', () => {
  const noteField = $('#note') as HTMLTextAreaElement;
  noteField.value = SEL_POP_FIELD.value;
  mentionEdited(noteField, SEL_POP_FIELD.selectionStart);
  autoGrow(noteField);
  renderAssignNew();
  qHint($('#c-qhint'), noteField.value, KIND_NEW);
  saveDraftSoon();
});
$('#note').addEventListener('input', () => {
  const note = ($('#note') as HTMLTextAreaElement).value;
  if (selPopOpen() && SEL_POP_FIELD.value !== note) SEL_POP_FIELD.value = note;
});
SEL_POP_FIELD.addEventListener('focus', () => {
  SEL_POP_FIELD.value = ($('#note') as HTMLTextAreaElement).value;
});
// [자세히 →]: the composer in the panel takes over with the focus in its note; the popover does not come back for this selection.
function selPopMore() {
  closeSelPop();
  setSide(true);
  applySide();
  $('#note').focus();
}
$('#left').addEventListener('scroll', placeSelPop, { passive: true });
addEventListener('resize', placeSelPop);
new ResizeObserver(placeSelPop).observe($('#doc')); // a zoom moves the box with its page
export {
  SEL_POP,
  SEL_POP_BOX,
  SEL_POP_FIELD,
  closeSelPop,
  drawSelPop,
  openSelPop,
  placeSelPop,
  selPopArea,
  selPopMore,
  selPopOpen,
};
