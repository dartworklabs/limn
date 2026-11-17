// ------------------------------------------------ Drag selection (mouse/touch/pen - one Pointer Events path)
// Mouse: press and drag draws a rectangle. Touch/pen: a drag draws a rectangle only in selection mode
// (SELMODE), and a tap does quick selection; outside selection mode, scroll/pinch zoom work as usual and a
// long-press does quick selection. Only pages get touch-action:none in selection mode (a one-finger drag is
// handled by this code, two fingers by the app zoom - §PDF 영역 전용 확대).
// Coordinates are computed as fractions within the page from clientX/Y and getBoundingClientRect on the same
// basis (the layout viewport), so they stay correct even during a pinch zoom.
import {
  DOC,
  PAGE_SCALE,
  LAYOUT,
  META,
  REPICK,
  REPLY,
  SELMODE,
  SIDE_OPEN,
  isFigureKind,
  COMPOSE,
  EDITOR,
  setComposeBox,
} from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { translate } from '../platform/i18n.ts';
import { SWALLOW_CLICK, setSwallowClick } from '../platform/tooltip.ts';
import { fitScale, zoomTo } from './view-pages.ts';
import { $, eventElement } from '../platform/dom.ts';
import { LAYOUT_MODE } from '../app/rules-tables.ts';
import { isMarkdownDoc } from '../documents/state.ts';
import { LONGPRESS_MS } from '../layout/input.ts';
import { endJumpForScroll } from '../layout/flow-scroll.ts';
import { markBadgeIn, markBadgeRoom } from './view-badges.ts';
import { pageSelection } from './state-seams.ts';

let DRAG = null as {
    pg: HTMLElement;
    sx: number;
    sy: number;
    id: number;
    mouse: boolean;
    cx: number;
    cy: number;
    box: HTMLElement | null;
    badge?: boolean;
  } | null,
  LONG_PRESS = null as { id: number; pg: HTMLElement; cx: number; cy: number; t: ReturnType<typeof setTimeout> } | null;
const clampUnit = (value: number) => Math.min(1, Math.max(0, value));
const TAP_SLOP = 8,
  QUICK_HALF_WIDTH = 0.07,
  QUICK_HALF_HEIGHT = 0.006,
  QUICK_FIGURE_HALF = 0.004;
function fracAt(pageElement: HTMLElement, clientX: number, clientY: number) {
  const rect = pageElement.getBoundingClientRect();
  return [clampUnit((clientX - rect.left) / rect.width), clampUnit((clientY - rect.top) / rect.height)];
}
function newBox(pageElement: HTMLElement) {
  const box = document.createElement('div');
  box.className = 'sel';
  pageElement.appendChild(box);
  return box;
}
// The pending box's badge - the composer's '새 핀', a re-place's '새 위치': a '+' where a saved mark's number badge
// goes, outside the box's left edge at its top, or in its top-left corner when the page margin has no room
// (pendingBadgeSide). The name is for screen readers only: a visible tag above the box would cover the text line above
// it.
function pendingBadge(box: HTMLElement, name: string) {
  setHtml(box, html`<i aria-hidden="true">${lucideIcon('plus')}</i><span class="sr-only">${translate(name)}</span>`);
  pendingBadgeSide(box);
}
// Decides a pending box's badge side by the mark rule (markBadgeIn) for its left edge, its page's width and margin now.
function pendingBadgeSide(box: HTMLElement) {
  const room = markBadgeRoom(box.parentElement);
  if (room)
    box.classList.toggle('in', markBadgeIn((parseFloat(box.style.left) || 0) / 100, room.w, room.pad, room.reach));
}
// Sizes a box (page fractions) between the drag's start point and the point (x, y).
function drawBox(box: HTMLElement, startX: number, startY: number, x: number, y: number) {
  Object.assign(box.style, {
    left: Math.min(startX, x) * 100 + '%',
    top: Math.min(startY, y) * 100 + '%',
    width: Math.abs(x - startX) * 100 + '%',
    height: Math.abs(y - startY) * 100 + '%',
  });
}
function cancelDrag() {
  if (DRAG && DRAG.box) DRAG.box.remove();
  DRAG = null;
}
function cancelLongPress() {
  if (LONG_PRESS) {
    clearTimeout(LONG_PRESS.t);
    LONG_PRESS = null;
  }
}
// Prevents the default behavior of a mouse press on a page (focus shift, image dragging), so the note field keeps its
// focus.
$('#doc').addEventListener('mousedown', (event: MouseEvent) => {
  const target = eventElement(event);
  if (event.button === 0 && target && target.closest('.pg')) event.preventDefault();
});
// A quick selection made by a long-press or a [선택]-mode tap opens the panel or sheet under the finger, and the click
// that follows the touch would land on it (it would open an edit, switch the kind, focus the note) - that one click is
// swallowed (SWALLOW_CLICK). LONG_PRESS_PICKED = the pointer whose long-press already picked. TAP/LAST_TAP = double-tap
// zoom (touch, outside [선택] mode).
let LONG_PRESS_PICKED = null as number | null,
  TAP = null as { id: number; x: number; y: number; t: number } | null,
  LAST_TAP = null as { t: number; x: number; y: number } | null;
// BADGE_HOLD = the SWALLOW_CLICK a drag from a badge armed at its release (0 for none). A pen's drag is followed by a
// click, but a finger's is not, so the hold would outlive the gesture and swallow the next tap, on another badge: the
// next press retires it (a click always comes before the next press) - unless another hold has taken SWALLOW_CLICK over
// since, which is not this one's to end.
let BADGE_HOLD = 0;
window.addEventListener(
  'pointerdown',
  () => {
    if (SWALLOW_CLICK === BADGE_HOLD) setSwallowClick(0);
    BADGE_HOLD = 0;
  },
  true,
);
// A finger in [선택] mode that lands on a pin's number badge - its 44px press area reaches over the page's text - still
// starts a box (DRAG.badge) once it moves: on a small page the badges' areas cover much of its left edge, where no drag
// could start otherwise. A tap stays the badge's (its click), and a mouse or a finger outside the mode leaves the badge
// alone.
$('#doc').addEventListener('pointerdown', (event: PointerEvent) => {
  const element = eventElement(event);
  if (!element) return;
  const badge = element.closest('.mark [data-act=mark-jump]'),
    mouse = event.pointerType === 'mouse';
  if (badge && (mouse || !SELMODE || !event.isPrimary)) return;
  // A second finger is a pinch: the box being drawn is discarded.
  if (!event.isPrimary) {
    cancelDrag();
    cancelLongPress();
    TAP = null;
    LAST_TAP = null;
    return;
  }
  const pageElement = element.closest('.pg');
  if (!(pageElement instanceof HTMLElement)) return;
  if (mouse && event.button !== 0) return;
  if (mouse || SELMODE) {
    const [startX, startY] = fracAt(pageElement, event.clientX, event.clientY);
    DRAG = {
      pg: pageElement,
      sx: startX,
      sy: startY,
      id: event.pointerId,
      mouse,
      cx: event.clientX,
      cy: event.clientY,
      box: mouse ? newBox(pageElement) : null,
      badge: !!badge,
    };
    // A badge keeps the press until it moves: a tap is its click.
    if (!mouse && !badge) {
      try {
        pageElement.setPointerCapture(event.pointerId);
      } catch (_) {}
    }
    return;
  }
  cancelLongPress();
  TAP = { id: event.pointerId, x: event.clientX, y: event.clientY, t: performance.now() };
  LONG_PRESS = {
    id: event.pointerId,
    pg: pageElement,
    cx: event.clientX,
    cy: event.clientY,
    t: setTimeout(() => {
      const longPress = LONG_PRESS;
      LONG_PRESS = null;
      if (longPress) {
        LONG_PRESS_PICKED = longPress.id;
        quickPick(longPress.pg, longPress.cx, longPress.cy);
      }
    }, LONGPRESS_MS),
  };
});
window.addEventListener('pointermove', (event) => {
  if (
    LONG_PRESS &&
    event.pointerId === LONG_PRESS.id &&
    Math.hypot(event.clientX - LONG_PRESS.cx, event.clientY - LONG_PRESS.cy) > 10
  )
    cancelLongPress();
  if (TAP && event.pointerId === TAP.id && Math.hypot(event.clientX - TAP.x, event.clientY - TAP.y) > TAP_SLOP)
    TAP = null;
  if (!DRAG || event.pointerId !== DRAG.id) return;
  if (!DRAG.box) {
    if (Math.hypot(event.clientX - DRAG.cx, event.clientY - DRAG.cy) < TAP_SLOP) return;
    DRAG.box = newBox(DRAG.pg);
  }
  const [x, y] = fracAt(DRAG.pg, event.clientX, event.clientY);
  drawBox(DRAG.box, DRAG.sx, DRAG.sy, x, y);
});
window.addEventListener('pointerup', (event) => {
  const off = PRESS_OFF && PRESS_OFF.id === event.pointerId ? PRESS_OFF : null;
  // This press, if it could be a click-off.
  PRESS_OFF = null;
  // A long press has already picked: its release is no tap.
  const picked = LONG_PRESS_PICKED === event.pointerId;
  if (LONG_PRESS && event.pointerId === LONG_PRESS.id) cancelLongPress();
  if (picked) {
    LONG_PRESS_PICKED = null;
    setSwallowClick(Date.now() + 400);
  }
  // Touch outside [선택] mode: whether the press stayed under TAP_SLOP, and whether it is a double tap.
  let tapped = false,
    doubled = false;
  if (TAP && event.pointerId === TAP.id) {
    const tap = TAP,
      now = performance.now();
    TAP = null;
    tapped = !picked;
    if (now - tap.t < 300) {
      const tapNow = { t: now, x: event.clientX, y: event.clientY };
      if (isDoubleTap(LAST_TAP, tapNow)) {
        LAST_TAP = null;
        doubled = true;
        clickOffStop();
        doubleTapZoom(tapNow.x, tapNow.y);
      } else LAST_TAP = tapNow;
    }
  }
  // A finger's tap waits out the double-tap window first.
  if (off && !off.mouse && tapped && !doubled) clickOffSoon(off.box);
  // A press off the pages.
  if (
    off &&
    off.mouse &&
    !(DRAG && event.pointerId === DRAG.id) &&
    Math.hypot(event.clientX - off.x, event.clientY - off.y) < TAP_SLOP
  )
    clickOffNow(off.box);
  if (!DRAG || event.pointerId !== DRAG.id) return;
  const drag = DRAG;
  DRAG = null;
  // A tap in selection mode is a quick selection (on a badge, the badge's).
  if (!drag.box) {
    if (drag.badge) return;
    quickPick(drag.pg, event.clientX, event.clientY);
    setSwallowClick(Date.now() + 400);
    return;
  }
  // A drag from a badge is a box, never the badge's click as well: the click is held off from the release, which it
  // follows, however long the drag ran.
  if (drag.badge) setSwallowClick((BADGE_HOLD = Date.now() + 400));
  const [x, y] = fracAt(drag.pg, event.clientX, event.clientY);
  // Too small for a box: a click.
  if (!finishRect(drag.pg, drag.box, drag.sx, drag.sy, x, y) && off && off.mouse) clickOffNow(off.box);
});
window.addEventListener('pointercancel', (event) => {
  if (PRESS_OFF && PRESS_OFF.id === event.pointerId) PRESS_OFF = null;
  if (LONG_PRESS && event.pointerId === LONG_PRESS.id) cancelLongPress();
  if (DRAG && event.pointerId === DRAG.id) cancelDrag();
  if (TAP && event.pointerId === TAP.id) TAP = null;
  if (LONG_PRESS_PICKED === event.pointerId) LONG_PRESS_PICKED = null;
});
// ------------------------------------------------ Click-off: a short press outside the selection cancels it
// With a selection open (the dashed box and the composer), a short press on the PDF area outside the box is [취소]/Esc
// (discardSelection, so a typed note keeps its `선택 취소됨 · [되돌리기]`). Short: the mouse moves under a drag
// (finishRect's size, the one that makes a box), the finger under TAP_SLOP and is not a long press (that picks a
// paragraph). Never a cancel: a press inside the box or its badge, on a pin mark, on a control, one that becomes a drag
// (a new selection) or a pinch, a double tap (app zoom) and - on touch - any tap in [선택] mode (a quick selection: it
// is no TAP, so it never reaches clickOffSoon). A finger's cancel waits CLICKOFF_WAIT_MS, past the 300ms double-tap
// window (isDoubleTap), so the first tap of a double tap does not close the composer under the zoom. PRESS_OFF is the
// press that may become one (set on pointerdown, resolved on pointerup); CLICKOFF_TIMER the finger's wait.
const CLICKOFF_WAIT_MS = 350;
let PRESS_OFF = null as { id: number; mouse: boolean; x: number; y: number; box: HTMLElement | null } | null,
  CLICKOFF_TIMER = null as ReturnType<typeof setTimeout> | null;
// Whether the point (x, y) lies in one of rects ({left, top, right, bottom}), each grown by pad px. Pure.
function hitsAny(rects: DOMRect[], x: number, y: number, pad: number) {
  return rects.some(
    (rect) => x >= rect.left - pad && x <= rect.right + pad && y >= rect.top - pad && y <= rect.bottom + pad,
  );
}
// A selection is open and nothing above it is the thing to close first - Esc's order: a re-place, a reply, an edit,
// then the selection.
function selectionOpen() {
  return !!(COMPOSE.current || !$('#composer').hidden) && !REPICK && !REPLY && !EDITOR.current;
}
// Whether a pointerdown press is outside the open selection on the PDF area, so it can cancel it: not on a control or a
// pin's number badge, not on the scrollbar, and not in the box, its badge, its note popover
// (composer/view-selection-popover.ts, which counts as the box) or a pin mark (their boxes ignore the pointer, so the
// page is what the press lands on).
function pressOutsideSelection(event: PointerEvent) {
  const target = event.target as Element;
  if (!selectionOpen()) return false;
  // A press on the Markdown surface picks (markdown/view.ts), never cancels.
  if (isMarkdownDoc() && target.closest('#md')) return false;
  if (target.closest('.mark [data-act=mark-jump],button,a,input,textarea,select,[data-act],[role=button],#sel-pop'))
    return false;
  const pdfArea = $('#left');
  if (target === pdfArea && (event.offsetX >= pdfArea.clientWidth || event.offsetY >= pdfArea.clientHeight))
    return false;
  const inside = [
    ...document.querySelectorAll('.mark'),
    ...(COMPOSE.box ? [COMPOSE.box, ...COMPOSE.box.querySelectorAll('i')] : []),
    ...(pageSelection().popoverOpen() ? [pageSelection().popover()] : []),
  ].map((element) => element.getBoundingClientRect());
  return !hitsAny(inside, event.clientX, event.clientY, 0);
}
$('#left').addEventListener('pointerdown', (event: PointerEvent) => {
  PRESS_OFF =
    event.isPrimary && pressOutsideSelection(event)
      ? {
          id: event.pointerId,
          mouse: event.pointerType === 'mouse',
          x: event.clientX,
          y: event.clientY,
          box: COMPOSE.box,
        }
      : null;
});
// Cancels the selection the press began on, if it is still the one open and still the thing to close.
function clickOffNow(box: HTMLElement | null) {
  if (!selectionOpen() || COMPOSE.box !== box) return;
  pageSelection().discard();
  // The panel may move under the click that follows.
  setSwallowClick(Date.now() + 400);
}
// Stops a finger's pending click-off.
function clickOffStop() {
  if (CLICKOFF_TIMER !== null) {
    clearTimeout(CLICKOFF_TIMER);
    CLICKOFF_TIMER = null;
  }
}
// A finger's click-off: cancels the selection once the double-tap window has passed without a second tap.
function clickOffSoon(box: HTMLElement | null) {
  clickOffStop();
  CLICKOFF_TIMER = setTimeout(() => {
    CLICKOFF_TIMER = null;
    clickOffNow(box);
  }, CLICKOFF_WAIT_MS);
}
// Double-tap on the PDF (touch, outside [선택] mode - the browser's own double-tap zoom is off there): a second tap
// within 300ms and 24px of the first. At fit width it zooms to 2x, from any other width back to fit width - both around
// the tapped point.
function isDoubleTap(
  previous: { t: number; x: number; y: number } | null,
  latest: { t: number; x: number; y: number },
) {
  return (
    !!previous &&
    !!latest &&
    latest.t - previous.t <= 300 &&
    Math.hypot(latest.x - previous.x, latest.y - previous.y) <= 24
  );
}
// The scale (or width) a double tap goes to: 2x from fit width (within 5%), fit width from any other. Pure.
function doubleTapWidth(width: number, fit: number) {
  return Math.abs(width - fit) <= fit * 0.05 ? fit * 2 : fit;
}
// Zooms around (x, y) to doubleTapWidth() of the scale; landing on the screen's own scale, compact stops counting as
// zoomed and re-fits again (markZoomed, in zoomTo).
function doubleTapZoom(x: number, y: number) {
  zoomTo(doubleTapWidth(PAGE_SCALE, fitScale()), x, y);
}
// Quick selection: calls the existing /api/pick with a small box around the pressed point (quickBox). The server's
// default level is used as-is - 'paragraph' in body text, 'environment' inside a figure/table, the element under the
// point on a figure document - and then widened or narrowed via the range ladder.
function quickPick(pageElement: HTMLElement, clientX: number, clientY: number) {
  const [x, y] = fracAt(pageElement, clientX, clientY),
    quickFrac = quickBox(x, y, isFigureKind(META && META.kind));
  finishRect(pageElement, newBox(pageElement), quickFrac[0], quickFrac[1], quickFrac[2], quickFrac[3]);
}
// The box a quick selection sends around the point (x, y), as page fractions [x0, y0, x1, y1]: about one text line on a
// manuscript page (page width +-7%, height +-0.6%); on a figure a small box of +-0.4% of the page width by +-0.4% of
// its height (a rectangle on a page that is not square), which the map reads as the point - the deepest element holding
// it (docs/handbook/viewer.md §모바일 레이아웃). A line-shaped strip would cross a figure's small elements and resolve
// to an outer one.
function quickBox(x: number, y: number, figure: boolean) {
  const halfWidth = figure ? QUICK_FIGURE_HALF : QUICK_HALF_WIDTH,
    halfHeight = figure ? QUICK_FIGURE_HALF : QUICK_HALF_HEIGHT;
  return [clampUnit(x - halfWidth), clampUnit(y - halfHeight), clampUnit(x + halfWidth), clampUnit(y + halfHeight)];
}
// Turns a drawn rectangle into a selection and asks the server for its lines. Returns false, drawing nothing and
// removing the box, when the rectangle is smaller than a drag (under 0.4% of the page in both directions) - a click,
// not a selection.
function finishRect(pageElement: HTMLElement, box: HTMLElement, startX: number, startY: number, x: number, y: number) {
  const width = Math.abs(x - startX),
    height = Math.abs(y - startY);
  if (width < 0.004 && height < 0.004) {
    box.remove();
    return false;
  }
  drawBox(box, startX, startY, x, y);
  box.classList.add('pending');
  if (REPICK) {
    if (REPICK.box) REPICK.box.remove();
    REPICK.box = box;
    pendingBadge(box, '새 위치');
  } else {
    if (COMPOSE.box) COMPOSE.box.remove();
    setComposeBox(box);
    pendingBadge(box, '새 핀');
  }
  const page = Number(pageElement.dataset.page),
    pageInfo = META.pages[page - 1],
    repick = !!REPICK;
  pageSelection().pick({
    page,
    x0: Math.min(startX, x) * pageInfo.pt_w,
    y0: Math.min(startY, y) * pageInfo.pt_h,
    x1: Math.max(startX, x) * pageInfo.pt_w,
    y1: Math.max(startY, y) * pageInfo.pt_h,
    frac: [Math.min(startX, x), Math.min(startY, y), width, height],
    pdf_build: META.pages_build || undefined,
    doc: DOC || undefined,
  });
  // A mouse drag's note popover (composer/view-selection-popover.ts); pick() has opened the composer.
  if (!repick) pageSelection().openPopover(box);
  return true;
}
// If the sheet or panel covers the selection box, the body scrolls up until the box is visible (compact only; with
// wide, in every layout - the Markdown surface's chosen lines after a reflow, keepReadingSpot). The view's top is 28px
// into the PDF area, or 8px under the select mode's bar while it shows, so the box never stays under the bar
// (selectionRoom).
function revealBox(box: HTMLElement | null, wide?: boolean) {
  if (!box || (LAYOUT === LAYOUT_MODE.WIDE && !wide) || !document.contains(box)) return;
  const pdfArea = $('#left'),
    boxRect = box.getBoundingClientRect(),
    { top, bottom } = selectionRoom();
  if (boxRect.top >= top && boxRect.bottom <= bottom - 8) return;
  endJumpForScroll();
  pdfArea.scrollTop += boxRect.top - top - Math.max(0, (bottom - top - boxRect.height) / 3);
}
// The part of the document area a chosen place can be seen in, as viewport y's: from 28px under the area's top (or 8px
// under the select mode's bar) down to the area's bottom - or to the sheet's top, where the narrow sheet is open over
// it.
function selectionRoom(): { top: number; bottom: number } {
  const areaRect = $('#left').getBoundingClientRect(),
    bar = $('#sel-bar');
  let bottom = areaRect.bottom;
  if (LAYOUT === LAYOUT_MODE.NARROW && SIDE_OPEN) bottom = Math.min(bottom, $('#right').getBoundingClientRect().top);
  return {
    top: Math.max(areaRect.top + 28, bar.getClientRects().length ? bar.getBoundingClientRect().bottom + 8 : 0),
    bottom,
  };
}
export { cancelDrag, cancelLongPress, drawBox, newBox, pendingBadge, pendingBadgeSide, revealBox, selectionRoom };
