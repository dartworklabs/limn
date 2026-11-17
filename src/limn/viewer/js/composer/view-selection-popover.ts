// ---------------------- The note popover by the selection box (docs/handbook/viewer.md §패널 정리 '선택 상자 곁 메모')
// With a mouse on the desktop and mid layouts, a drag that ends opens a small popover under the dashed box: the
// location, a note field, [자세히 →] and [저장], so the note can be written where the eye already is. The field is the
// composer's note - one value, edited from either place - and [저장] and Ctrl/⌘+Enter take savePin(), the composer's
// own path, so the saved chip with its undo and every rule of §알림 자리 hold unchanged. '@' in the field offers the
// composer's @-list by the field; a pick's tag is kept on the composer's note (composer/input-mentions.ts mentionModel).
// [자세히 →] hands over to the composer in the panel, which keeps the kind, the range and the overlap. Esc and a short
// click off the box cancel the selection as they do without it; a press on the popover is a press inside the box
// (pressOutsideSelection). Touch and the phone keep the composer alone (it is a sheet).
import { KIND_NEW, LAYOUT, REPICK, COMPOSE } from '../app/state.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { applySide, setSide } from '../layout/flow.ts';
import { saveDraftSoon } from './flow-draft.ts';
import { MENTION, mentionClose, mentionEdited, mentionPlace, renderAssignNew } from './input-mentions.ts';
import { $, findElement } from '../platform/dom.ts';
import { LAYOUT_MODE } from '../app/rules-tables.ts';
import { lineRange } from '../app/rules-pins.ts';
import { isRegion } from '../documents/state.ts';
import { LAST_POINTER } from '../platform/tooltip.ts';
import { popoverFreeArea } from '../pdf/view-area.ts';
import { autoGrow } from './view-text.ts';
import { syncQuestionHint } from './view-note-hints.ts';
const SELECTION_POPOVER = $('#sel-pop'),
  SELECTION_POPOVER_FIELD = SELECTION_POPOVER.querySelector('textarea') as HTMLTextAreaElement,
  SELECTION_POPOVER_GAP = 8;
SELECTION_POPOVER_FIELD._mirrorOf = $('#note') as HTMLTextAreaElement; // its @-tags are the note's, which saves them
// The box the popover belongs to; null while it is closed.
let SELECTION_POPOVER_BOX = null as HTMLElement | null;
// Where a popover of width x height goes for a box in the free area (rectangles {left, top, right, bottom}), gap px
// from the box and from the area's edges: below the box with its left edge, above it when below has no room, at the
// area's foot when neither side has room; moved left to stay inside the area's right edge, never past its left. Not
// shown when the box is outside the area (scrolled away). Whole pixels, so its text is drawn crisp. Pure.
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
// Whether this selection gets the popover: a mouse drag outside the phone layout, not a re-place.
function wantsSelectionPopover() {
  return LAYOUT !== LAYOUT_MODE.NARROW && LAST_POINTER === 'mouse' && !REPICK;
}
// Opens the popover for the box a mouse drag just drew (finishRect): the field takes the composer's note and the focus.
function openSelectionPopover(box: HTMLElement) {
  if (!wantsSelectionPopover()) return;
  SELECTION_POPOVER_BOX = box;
  SELECTION_POPOVER_FIELD.value = $('#note').value;
  drawSelectionPopover();
  if (!SELECTION_POPOVER.hidden) SELECTION_POPOVER_FIELD.focus({ preventScroll: true });
}
function closeSelectionPopover() {
  SELECTION_POPOVER_BOX = null;
  SELECTION_POPOVER.hidden = true;
  if (MENTION.ta === SELECTION_POPOVER_FIELD) mentionClose();
}
function isSelectionPopoverOpen() {
  return !SELECTION_POPOVER.hidden;
}
// Draws the popover from the selection: the location (or '찾는 중' while the pick runs), the note's placeholder, its
// place. It closes when its box is not the selection's, the composer is closed, the pick failed or the layout is the
// phone's.
function drawSelectionPopover() {
  const selection = COMPOSE.current;
  if (
    !SELECTION_POPOVER_BOX ||
    COMPOSE.box !== SELECTION_POPOVER_BOX ||
    !document.contains(SELECTION_POPOVER_BOX) ||
    $('#composer').hidden ||
    (!selection && !COMPOSE.picking) ||
    !wantsSelectionPopover()
  ) {
    closeSelectionPopover();
    return;
  }
  const loc = findElement(SELECTION_POPOVER, '.sp-loc', HTMLElement);
  loc.textContent = !selection
    ? translate('찾는 중')
    : isRegion(selection)
      ? translateTemplate('쪽 {page} 영역', { page: selection.page })
      : selection.name + ' ' + lineRange(selection.lo as number, selection.hi as number);
  SELECTION_POPOVER_FIELD.placeholder = $('#note').placeholder;
  SELECTION_POPOVER.hidden = false;
  placeSelectionPopover();
}
// Puts the popover by its box in the free area (popPlace); hidden while the box is scrolled out of it. An @-list open
// on its field goes with it, and closes while it is hidden.
function placeSelectionPopover() {
  if (SELECTION_POPOVER.hidden || !SELECTION_POPOVER_BOX) return;
  if (!wantsSelectionPopover()) {
    closeSelectionPopover();
    return;
  }
  const place = popPlace(
    SELECTION_POPOVER_BOX.getBoundingClientRect(),
    popoverFreeArea(),
    SELECTION_POPOVER.offsetWidth,
    SELECTION_POPOVER.offsetHeight,
    SELECTION_POPOVER_GAP,
  );
  SELECTION_POPOVER.style.left = place.left + 'px';
  SELECTION_POPOVER.style.top = place.top + 'px';
  SELECTION_POPOVER.dataset.side = place.side;
  SELECTION_POPOVER.style.visibility = place.shown ? '' : 'hidden';
  if (MENTION.ta === SELECTION_POPOVER_FIELD) {
    if (place.shown) mentionPlace();
    else mentionClose();
  }
}
// One note: what is typed here is the composer's note (its @-tag preview, assignee row, question hint and draft
// follow), and what is typed in the composer shows here (a name picked there from the @-list too:
// composer/input-mentions.ts mentionMirror).
SELECTION_POPOVER_FIELD.addEventListener('input', () => {
  const noteField = $('#note') as HTMLTextAreaElement;
  noteField.value = SELECTION_POPOVER_FIELD.value;
  mentionEdited(noteField, SELECTION_POPOVER_FIELD.selectionStart);
  autoGrow(noteField);
  renderAssignNew();
  syncQuestionHint($('#c-qhint'), noteField.value, KIND_NEW);
  saveDraftSoon();
});
$('#note').addEventListener('input', () => {
  const note = ($('#note') as HTMLTextAreaElement).value;
  if (isSelectionPopoverOpen() && SELECTION_POPOVER_FIELD.value !== note) SELECTION_POPOVER_FIELD.value = note;
});
SELECTION_POPOVER_FIELD.addEventListener('focus', () => {
  SELECTION_POPOVER_FIELD.value = ($('#note') as HTMLTextAreaElement).value;
});
// [자세히 →]: the composer in the panel takes over with the focus in its note; the popover does not come back for this
// selection.
function handPopoverToComposer() {
  closeSelectionPopover();
  setSide(true);
  applySide();
  $('#note').focus();
}
$('#left').addEventListener('scroll', placeSelectionPopover, { passive: true });
addEventListener('resize', placeSelectionPopover);
new ResizeObserver(placeSelectionPopover).observe($('#doc')); // a zoom moves the box with its page
export {
  SELECTION_POPOVER,
  SELECTION_POPOVER_BOX,
  SELECTION_POPOVER_FIELD,
  closeSelectionPopover,
  drawSelectionPopover,
  openSelectionPopover,
  placeSelectionPopover,
  handPopoverToComposer,
  isSelectionPopoverOpen,
};
