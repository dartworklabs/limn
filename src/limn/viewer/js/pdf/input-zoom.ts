// ------------------------------------------------ PDF-area-only zoom - docs/handbook/viewer.md §PDF 영역 전용 확대
// Browser zoom would also enlarge the sidebar and tool bar, so zoom input over the PDF area is intercepted to change
// only the pages' scale (PAGE_SCALE).
// - Desktop: Ctrl(Cmd)+wheel over #left, anchored to the pointer. A trackpad pinch also arrives as a wheel event with
//   ctrlKey set, in Chrome and Firefox.
// - Safari trackpad pinch: gesturestart/gesturechange (the event's scale).
// - Keyboard Ctrl(Cmd) + = / + / - / 0 -> zoom in/out/fit width (never intercepted while an input field has focus -
//   see the key handler).
// - Touch: #left has touch-action:pan-x pan-y, so there is no browser pinch. PAGE_SCALE changes with the ratio of the
//   two-finger distance, and the point under the midpoint of the two fingers follows the fingers (drag while zooming).
//   A page in selection mode has touch-action:none, so it goes through the same path.
// - A Markdown document (markdown/view.ts) has no pages to scale: every one of these leaves its input to the browser -
//   Ctrl+wheel, a trackpad's gesture and two fingers zoom the page as anywhere else (md-surface.css lets #left pinch
//   there).
import { PAGE_SCALE } from '../app/state.ts';
import { ZOOM_STEP, markZoomed, setScale, zoomAnchor, zoomRestore, zoomTo } from './view-pages.ts';
import { cancelDrag, cancelLongPress } from './input-selection.ts';
import { $ } from '../platform/dom.ts';
import { isMarkdownDoc } from '../documents/state.ts';
// The zoom a key event asks for: 'in', 'out', 'fit' (fit width), or null for any other key.
function zoomKey(event: KeyboardEvent) {
  const key = event.key,
    code = event.code;
  if (key === '=' || key === '+' || code === 'Equal' || code === 'NumpadAdd') return 'in';
  if (key === '-' || key === '_' || code === 'Minus' || code === 'NumpadSubtract') return 'out';
  if (key === '0' || code === 'Digit0' || code === 'Numpad0') return 'fit';
  return null;
}
// The factor for one wheel tick. One mouse-wheel notch (|deltaY| >= 50 pixels, or a line or page unit) gets the same
// ZOOM_STEP as one button press; a trackpad pinch's finely divided deltaY is composed via exp(-deltaY/100) - the
// inverse of the formula Chrome uses to turn pinch scale into wheel events, so it grows in proportion to how far the
// fingers spread. deltaY is clamped to +-18 so a single event never exceeds one button press's worth (ZOOM_STEP ~
// exp(0.18)).
function wheelFactor(deltaY: number, mode: number) {
  if (!deltaY) return 1;
  if (mode === 1 || mode === 2 || Math.abs(deltaY) >= 50) return deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
  return Math.exp(-Math.max(-18, Math.min(18, deltaY)) / 100);
}
(function () {
  const pdfArea = $('#left');
  let pendingFactor = 1,
    wheelPoint: number[] | null = null,
    wheelFrame = 0,
    gestureStart: { k: number } | null = null,
    pinchStart: { d: number; k: number; a: ReturnType<typeof zoomAnchor> } | null = null;
  const flush = () => {
    wheelFrame = 0;
    if (pendingFactor === 1 || !wheelPoint) return;
    const factor = pendingFactor;
    pendingFactor = 1;
    zoomTo(PAGE_SCALE * factor, wheelPoint[0], wheelPoint[1]);
  };
  pdfArea.addEventListener(
    'wheel',
    (event: WheelEvent) => {
      if (!(event.ctrlKey || event.metaKey) || isMarkdownDoc()) return;
      event.preventDefault(); // a Markdown document's text zooms with the browser
      pendingFactor *= wheelFactor(event.deltaY, event.deltaMode);
      wheelPoint = [event.clientX, event.clientY];
      if (!wheelFrame) wheelFrame = requestAnimationFrame(flush);
    },
    { passive: false },
  );
  pdfArea.addEventListener(
    'gesturestart',
    (event: SafariGestureEvent) => {
      if (isMarkdownDoc()) return;
      event.preventDefault();
      if (!pinchStart) gestureStart = { k: PAGE_SCALE };
    },
    { passive: false },
  );
  pdfArea.addEventListener(
    'gesturechange',
    (event: SafariGestureEvent) => {
      if (isMarkdownDoc()) return;
      event.preventDefault();
      if (gestureStart && !pinchStart && event.scale > 0)
        zoomTo(gestureStart.k * event.scale, event.clientX, event.clientY);
    },
    { passive: false },
  );
  pdfArea.addEventListener(
    'gestureend',
    (event: SafariGestureEvent) => {
      gestureStart = null;
      if (isMarkdownDoc()) return;
      event.preventDefault();
    },
    { passive: false },
  );
  const midpointOf = (first: Touch, second: Touch) => [
    (first.clientX + second.clientX) / 2,
    (first.clientY + second.clientY) / 2,
  ];
  const fingerDistance = (first: Touch, second: Touch) =>
    Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY) || 1;
  let pinchFrame = 0,
    last: { d: number; m: number[] } | null = null;
  const apply = () => {
    pinchFrame = 0;
    if (!pinchStart || !last) return;
    setScale((pinchStart.k * last.d) / pinchStart.d);
    markZoomed();
    zoomRestore(pinchStart.a, last.m[0], last.m[1]);
  };
  pdfArea.addEventListener(
    'touchstart',
    (event: TouchEvent) => {
      if (isMarkdownDoc()) {
        pinchStart = null;
        return;
      }
      if (event.touches.length !== 2) {
        if (event.touches.length > 2) pinchStart = null;
        return;
      }
      if (event.cancelable) event.preventDefault();
      const first = event.touches[0],
        second = event.touches[1],
        midpoint = midpointOf(first, second);
      cancelDrag();
      cancelLongPress();
      pinchStart = { d: fingerDistance(first, second), k: PAGE_SCALE, a: zoomAnchor(midpoint[0], midpoint[1]) };
      last = { d: pinchStart.d, m: midpoint };
    },
    { passive: false },
  );
  pdfArea.addEventListener(
    'touchmove',
    (event: TouchEvent) => {
      if (!pinchStart || event.touches.length !== 2) return;
      if (event.cancelable) event.preventDefault();
      const first = event.touches[0],
        second = event.touches[1];
      last = { d: fingerDistance(first, second), m: midpointOf(first, second) };
      if (!pinchFrame) pinchFrame = requestAnimationFrame(apply);
    },
    { passive: false },
  );
  const end = (event: TouchEvent) => {
    if (pinchStart && event.touches.length < 2) {
      if (pinchFrame) {
        cancelAnimationFrame(pinchFrame);
        apply();
      }
      pinchStart = null;
      last = null;
    }
  };
  pdfArea.addEventListener('touchend', end);
  pdfArea.addEventListener('touchcancel', end);
})();

export { wheelFactor, zoomKey };
