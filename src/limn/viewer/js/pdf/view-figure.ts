// ------------------------------------------------ Figure documents: the element a pick chose, its box and path
// A figure document's pick answers the element under the drag and the ladder of its ancestors; every rung carries its
// element (levels[].el with id, path root first, label, part, impl and its box `frac` on the pick's page). The composer
// shows that element without another request (docs/handbook/viewer.md §패널 정리): the pending box snaps to it - the
// mark the pin will get - and the location line names its path. The selection keeps the element it shows as elSel.
import { html, lucideIcon } from '../platform/markup.ts';
import { translateTemplate, translate, TIP_TEXT } from '../platform/i18n.ts';
import { drawBox, pendingBadgeSide } from './input-selection.ts';
import { popoverFreeArea } from '../composer/view-selection-popover.ts';
import { $ } from '../platform/dom.ts';
import { ELEMENT_SYNC } from '../app/rules-tables.ts';
import { levelOf } from '../documents/rules.ts';
import { COMPOSE } from '../app/state.ts';
import { endJumpForScroll } from '../layout/flow-scroll.ts';

// Whether box is a page box [x, y, w, h] of four finite numbers - the shape of a pin's frac and an element's frac.
function isFrac(box: unknown): box is number[] {
  return (
    Array.isArray(box) &&
    box.length === 4 &&
    box.every((coordinate) => typeof coordinate === 'number' && Number.isFinite(coordinate))
  );
}
// A person's name for an element: its label, else its part, else its id - the rule the pick answer's rung labels
// follow.
function elementName(element) {
  return String((element && (element.label || element.part || element.id)) || '');
}
// The selected element's path, root first, as the location line shows it ('B2 › 달력 › 7월'). Each id is named by the
// name the map gives it - the pick's path_names, one per id of its el.path (label, else part) - else by the rung that
// carries it, else by the pick's own element, else by the id itself: an ancestor merged into an inner rung, past the
// ladder's cap, drawn in another file or above a region answer's element has no rung, and the map's name or its id
// still says where it is.
function elementPathText(selection) {
  const selectedElement = selection && selection.elSel;
  if (!selectedElement || !Array.isArray(selectedElement.path)) return '';
  const names = new Map();
  if (selection.el && selection.el.id) names.set(selection.el.id, elementName(selection.el));
  (selection.levels || []).forEach((level) => {
    if (level.el && level.el.id) names.set(level.el.id, String(level.label || elementName(level.el)));
  });
  const ids = selection.el && Array.isArray(selection.el.path) ? selection.el.path : [],
    given = Array.isArray(selection.path_names) ? selection.path_names : [];
  ids.forEach((id, index) => {
    const name = given[index];
    if (typeof name === 'string' && name) names.set(id, name);
  });
  return selectedElement.path.map((id) => names.get(id) || String(id)).join(' › ');
}
// A figure rung's tooltip text: the whole figure's lines for the page's root (its path is itself), else the element's.
function rungTip(level) {
  return Array.isArray(level.el.path) && level.el.path.length <= 1 ? TIP_TEXT.fig : TIP_TEXT.el;
}
// Puts a pending box (the composer's '새 핀', a re-place's '새 위치') on the element it will pin, so the person sees
// the mark before saving. An element without a usable box, or no box on screen, leaves the box as dragged.
function snapBox(box, element) {
  if (!box || !element || !isFrac(element.frac)) return;
  const frac = element.frac;
  drawBox(box, frac[0], frac[1], frac[0] + frac[2], frac[1] + frac[3]);
  pendingBadgeSide(box);
}
// The element part of the composer for the selection and its pending box: the path line '#c-path' (hidden when the pick
// found no element - a manuscript, a view-only PDF, a figure whose map is unreadable) and the snapped box.
function renderElement(selection, box) {
  const line = $('#c-path'),
    selectedElement = selection.elSel;
  line.hidden = !selectedElement;
  if (selectedElement) {
    line.textContent = elementPathText(selection) + ' ·';
    line.dataset.tip = translateTemplate('요소 {id} · 누르면 쪽에서 이 상자를 보입니다', { id: selectedElement.id });
    line.setAttribute('aria-description', translate('누르면 쪽에서 고른 요소의 상자를 보입니다'));
  }
  snapBox(box, selectedElement);
  if (box) box.classList.toggle('hi', !!selectedElement && line.matches(':hover,:focus-visible'));
}
// The path in the composer is also the way to check which element was chosen: the pending box on the page is drawn on
// it (snapBox), and pointing at the path - the mouse over it, the focus on it - draws that box stronger (.sel.hi);
// pressing it (a tap on touch, where nothing hovers) brings the box into view if it is out of it and flashes it
// (.sel.flash), as [보기] does a pin's mark. The path stays a muted label and answers only to a pointer that comes to
// it.
function highlightElementBox(on: boolean) {
  const box = COMPOSE.box;
  if (box && box.isConnected) box.classList.toggle('hi', on);
}
for (const [eventName, on] of [
  ['mouseenter', true],
  ['focus', true],
  ['mouseleave', false],
  ['blur', false],
] as [string, boolean][])
  $('#c-path').addEventListener(eventName, () => highlightElementBox(on));
function showElementBox() {
  const box = COMPOSE.box;
  if (!box || !box.isConnected) return;
  const area = popoverFreeArea(),
    rect = box.getBoundingClientRect();
  if (rect.top < area.top || rect.bottom > area.bottom) {
    endJumpForScroll();
    $('#left').scrollTop += rect.top - (area.top + (area.bottom - area.top) * 0.3);
  }
  box.classList.remove('flash');
  void box.offsetWidth;
  box.classList.add('flash');
  box.addEventListener('animationend', () => box.classList.remove('flash'), { once: true });
}
// The page badge of a region on a figure document (composer and card): '코드 없는 요소' when the map chose an element
// it has no code lines for, '영역' when the map could not be read; null off figure documents without an element - the
// caller keeps its view-only wording.
function figureRegionBadge(element, figure) {
  return element
    ? { t: translate('코드 없는 요소'), tip: translate(TIP_TEXT.elregion) }
    : figure
      ? { t: translate('영역'), tip: translate(TIP_TEXT.figregion) }
      : null;
}
// The `el` a pin stores (POST /api/pin, an edit's loc): the pick's element with only the fields the pin record defines,
// in its order - id, path, label, part, impl and the element's box `frac` on the build it was picked on, which the
// server's read-time follow compares with the current build. A box that is not four finite numbers is left out.
function elementForSave(element) {
  const out: PinElement = { id: element.id, path: Array.isArray(element.path) ? element.path.slice() : [] };
  for (const k of ['label', 'part']) if (typeof element[k] === 'string') out[k] = element[k];
  if (element.impl && typeof element.impl === 'object')
    out.impl = { file: element.impl.file, lo: element.impl.lo, hi: element.impl.hi };
  if (isFrac(element.frac)) out.frac = element.frac.slice();
  return out;
}
// The range kind of an element rung as the server names it (limn.builds.figure_map.element_kind): 'figure' for the
// page's root (its path is itself), else 'el:<part>' with the part cut to 77 characters (a kind stays within 80),
// 'el:?' without a part. src/limn/viewer/tests/test_viewer.py runs both on the same elements.
function elementKind(element) {
  return Array.isArray(element.path) && element.path.length <= 1
    ? 'figure'
    : 'el:' + String(element.part || '?').slice(0, 77);
}
// Adds a figure pick's fields to a pin body or a re-place loc and returns it: `el`, the element's box as the pin's own
// `frac` too (a mark drawn without the current map then sits where the person saw the snapped box), and the element's
// kind when the range is that element's rung (rung given). A pick without an element is left as it is; lines set by
// hand in the excerpt keep the kind the body already has.
function figureFields(body, element, rung) {
  if (!element) return body;
  body.el = elementForSave(element);
  if (isFrac(element.frac)) body.frac = element.frac.slice();
  if (rung && rung.el) body.kind = elementKind(element);
  return body;
}
// The rung the selection's scope names when it is a figure rung (it carries an element), else null.
function figureRung(selection) {
  const level = selection && selection.scope && levelOf(selection, selection.scope);
  return level && level.el ? level : null;
}
// The element a re-place candidate would move the pin to: its default rung's, else the answer's own (a region answer).
function repickElement(candidate) {
  const level = levelOf(candidate, candidate.default_level);
  return (level && level.el) || candidate.el || null;
}
// Whether the server found this figure pin's element in the current build: the read-time `mark` box on `mark_page`.
function hasMark(pin: Pin) {
  return isFrac(pin.mark) && typeof pin.mark_page === 'number' && Number.isInteger(pin.mark_page) && pin.mark_page >= 1;
}
// Where a pin's mark goes (docs/handbook/viewer.md §상태 표현): its element's box in the current build when the server
// found it, else the page and box the pin was placed on - a manuscript pin, a view-only pin, a figure pin whose element
// was lost or whose map is unreadable. The box can be null (a stored box that is not finite reads null as a whole): the
// caller draws nothing for it.
function pinPlace(pin: Pin) {
  return hasMark(pin) ? { page: pin.mark_page as number, frac: pin.mark } : { page: pin.page, frac: pin.frac };
}
// Whether a figure pin's element is gone from the current build's map (`el_sync` lost) - shown like a lost line.
function isElementLost(pin: Pin) {
  return !!pin && pin.el_sync === ELEMENT_SYNC.LOST;
}
// The card badge of a lost element ('요소 잃음', the warning look of '위치 잃음'), or ''.
function lostElementTag(pin: Pin) {
  return isElementLost(pin)
    ? html`<span class="badge badge-warning" data-tip="${translate(TIP_TEXT.ellost)}">${lucideIcon('triangle-alert')}${translate('요소 잃음')}</span>`
    : null;
}
export {
  isElementLost,
  lostElementTag,
  elementName,
  figureRegionBadge,
  figureRung,
  figureFields,
  hasMark,
  isFrac,
  pinPlace,
  renderElement,
  repickElement,
  rungTip,
  showElementBox,
  snapBox,
};
