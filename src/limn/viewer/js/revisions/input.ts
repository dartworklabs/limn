import { translateTemplate } from '../platform/i18n.ts';
import { REVISION_VIEW, COMPARISON_PDF, drawPinGuide, revisionCurrent } from './flow.ts';
import { ZOOM_STEP } from '../pdf/view-pages.ts';
import { VECTOR_PIXEL_CAP } from '../pdf/flow-open.ts';
import { canvasBackingTarget } from '../pdf/view-draw.ts';
import { wheelFactor } from '../pdf/input-zoom.ts';
import { $ } from '../platform/dom.ts';
import { DIFF_FORMAT } from '../app/rules-tables.ts';
// ------------------------------------------------ The comparison PDF's zoom (docs/handbook/viewer.md §변경 보기)
// The changes view's own page geometry, zoom and rendering: its ratio is the comparison's alone, and nothing here
// writes the manuscript's zoom or any other preference. REVISION_ZOOM: the ratio, the fit width and pane height it was
// laid out at, the generation stale work compares against (gen), the generation a paint runs for (busy), the frame a
// paint waits on, whether a paint was asked for while one ran (repaint), the pages, the reading point kept across a
// layout (anchor) and the reset of the gesture state (resetInput).
type RevisionPage = {
  el: HTMLElement;
  page: any;
  base: { width: number; height: number };
  canvas: HTMLCanvasElement | null;
  task: any;
};
// The comparison PDF as mountRevisionPdf reads it (a PDF.js document): its page count and each page's size at scale 1.
interface RevisionPdf {
  numPages: number;
  getPage(pageNumber: number): Promise<{ getViewport(options: { scale: number }): { width: number; height: number } }>;
}
type RevisionAnchor = { el: HTMLElement; fx: number; fy: number; x: number; y: number };
interface RevisionZoomState {
  ratio: number;
  fit: number;
  height: number;
  gen: number;
  busy: number;
  frame: number;
  repaint: boolean;
  pages: RevisionPage[];
  anchor: RevisionAnchor | null;
  resetInput: () => void;
}
const REVISION_ZOOM: RevisionZoomState = {
  ratio: 1,
  fit: 0,
  height: 0,
  gen: 0,
  busy: 0,
  frame: 0,
  repaint: false,
  pages: [],
  anchor: null,
  resetInput: () => {},
};

/** Clamp a requested ratio, including non-finite input, to the comparison range. */
function revisionRatio(ratio: number) {
  return Number.isNaN(ratio) ? 1 : Math.max(0.5, Math.min(5, ratio));
}

/** Only a ready, visible comparison PDF owns PDF zoom input. */
function revisionPdfActive() {
  return (
    document.body.classList.contains('revision-open') &&
    REVISION_VIEW.format === DIFF_FORMAT.PDF &&
    REVISION_ZOOM.pages.length > 0
  );
}

/** Synchronize the comparison toolbar without touching manuscript controls. */
function drawRevisionZoom() {
  $('#revision-zoom').hidden = REVISION_VIEW.format !== DIFF_FORMAT.PDF;
  const ready = revisionPdfActive();
  $('#revision-zoom-value').textContent = Math.round(REVISION_ZOOM.ratio * 100) + '%';
  $('#revision-zoom-out').disabled = !ready || REVISION_ZOOM.ratio <= 0.5;
  $('#revision-zoom-in').disabled = !ready || REVISION_ZOOM.ratio >= 5;
  $('#revision-fit').disabled = !ready;
}

/** Cancel a page and release its pixel allocation on zoom, eviction or exit. */
function dropRevisionPage(item: RevisionPage) {
  if (item.task) {
    item.task.cancel();
    COMPARISON_PDF.tasks.delete(item.task);
    item.task = null;
  }
  if (item.canvas) {
    item.canvas.width = item.canvas.height = 0;
    item.canvas.remove();
    item.canvas = null;
  }
  delete item.el.dataset.state;
}

/** Invalidate asynchronous work and retained gesture anchors for a document visit. */
function disposeRevisionZoom() {
  ++REVISION_ZOOM.gen;
  REVISION_ZOOM.resetInput();
  REVISION_ZOOM.repaint = false;
  if (REVISION_ZOOM.frame) {
    cancelAnimationFrame(REVISION_ZOOM.frame);
    REVISION_ZOOM.frame = 0;
  }
  REVISION_ZOOM.pages.forEach(dropRevisionPage);
  REVISION_ZOOM.pages = [];
  REVISION_ZOOM.anchor = null;
  REVISION_ZOOM.fit = REVISION_ZOOM.height = 0;
  drawRevisionZoom();
}

/** Remember the nearest page and fractional position under a viewport point. */
function revisionAnchor(x?: number, y?: number) {
  const box = $('#revision-pdf'),
    boxRect = box.getBoundingClientRect();
  x = x ?? boxRect.left + box.clientWidth / 2;
  y = y ?? boxRect.top + box.clientHeight / 2;
  let nearest: HTMLElement | null = null,
    distance = Infinity;
  for (const item of REVISION_ZOOM.pages) {
    const pageRect = item.el.getBoundingClientRect(),
      gap = Math.max(pageRect.top - y, y - pageRect.bottom, 0);
    if (gap < distance) {
      nearest = item.el;
      distance = gap;
    }
  }
  if (!nearest) return null;
  const pageRect = nearest.getBoundingClientRect();
  return {
    el: nearest,
    fx: (x - pageRect.left) / pageRect.width,
    fy: (y - pageRect.top) / pageRect.height,
    x: x - boxRect.left,
    y: y - boxRect.top,
  };
}

/** Restore the same page point after layout, allowing ordinary edge clamping. */
function restoreRevisionAnchor(anchor: RevisionAnchor | null, x?: number, y?: number) {
  if (!anchor || !anchor.el.isConnected) return;
  const box = $('#revision-pdf'),
    boxRect = box.getBoundingClientRect(),
    pageRect = anchor.el.getBoundingClientRect();
  box.scrollLeft += pageRect.left + pageRect.width * anchor.fx - (x ?? boxRect.left + anchor.x);
  box.scrollTop += pageRect.top + pageRect.height * anchor.fy - (y ?? boxRect.top + anchor.y);
}

/** Measure usable width, excluding scroll-area padding and its scrollbar. */
function revisionFitWidth() {
  const box = $('#revision-pdf'),
    style = getComputedStyle(box);
  return box.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
}

/** Move the retained reading point to the resized viewport's new center. */
function resizeRevisionPdf() {
  const box = $('#revision-pdf'),
    anchor = REVISION_ZOOM.anchor ? { ...REVISION_ZOOM.anchor, x: box.clientWidth / 2, y: box.clientHeight / 2 } : null;
  layoutRevisionPdf(anchor);
}

// Resize all page boxes before restoring the anchor; redraw at the new width. The widest page takes the zoomed width
// and every other page its own share of it, so pages keep their sizes on paper relative to each other, as the
// manuscript's do.
function layoutRevisionPdf(anchor: RevisionAnchor | null) {
  if (!revisionPdfActive()) return;
  const box = $('#revision-pdf'),
    fit = revisionFitWidth();
  if (fit <= 0) return;
  REVISION_ZOOM.fit = fit;
  REVISION_ZOOM.height = box.clientHeight;
  ++REVISION_ZOOM.gen;
  REVISION_ZOOM.pages.forEach(dropRevisionPage);
  const width = fit * REVISION_ZOOM.ratio,
    group = box.firstElementChild,
    widest = Math.max(...REVISION_ZOOM.pages.map((item) => item.base.width));
  if (group instanceof HTMLElement) group.style.width = width + 'px';
  for (const item of REVISION_ZOOM.pages) {
    const pageWidth = (width * item.base.width) / widest;
    item.el.style.width = pageWidth + 'px';
    item.el.style.height = (pageWidth * item.base.height) / item.base.width + 'px';
  }
  restoreRevisionAnchor(anchor);
  REVISION_ZOOM.anchor = revisionAnchor();
  drawRevisionZoom();
  scheduleRevisionPaint();
}

/** Zoom around a pointer, a touch midpoint or the viewport center. */
function revisionZoomTo(ratio: number, x?: number, y?: number, anchor?: RevisionAnchor | null) {
  if (!revisionPdfActive()) return;
  const point = anchor || revisionAnchor(x, y);
  REVISION_ZOOM.ratio = revisionRatio(ratio);
  layoutRevisionPdf(point);
  if (anchor) {
    restoreRevisionAnchor(anchor, x, y);
    REVISION_ZOOM.anchor = revisionAnchor();
  }
}

/** Apply the same button step as the manuscript, or restore fit width. */
function revisionZoom(action: string | undefined) {
  revisionZoomTo(action === 'fit' ? 1 : REVISION_ZOOM.ratio * (action === 'in' ? ZOOM_STEP : 1 / ZOOM_STEP));
}

/** Obtain page geometry without allocating canvases; abandon stale PDF visits. */
async function mountRevisionPdf(pdf: RevisionPdf, seq: number, docKey: string | null, id: string) {
  const generation = REVISION_ZOOM.gen,
    pages: RevisionPage[] = [];
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
    const page = await pdf.getPage(pageNumber);
    if (generation !== REVISION_ZOOM.gen || !revisionCurrent(seq, docKey, id)) return;
    const pageElement = document.createElement('div');
    pageElement.className = 'revision-page';
    pageElement.dataset.page = String(pageNumber);
    pageElement.setAttribute('aria-label', translateTemplate('비교 PDF {page}쪽', { page: pageNumber }));
    pages.push({ el: pageElement, page, base: page.getViewport({ scale: 1 }), canvas: null, task: null });
  }
  const group = document.createElement('div');
  group.className = 'revision-pages';
  for (const item of pages) group.append(item.el);
  $('#revision-pdf').replaceChildren(group);
  REVISION_ZOOM.pages = pages;
  layoutRevisionPdf(null);
  drawRevisionZoom();
  if (REVISION_VIEW.target && REVISION_VIEW.target.page) {
    pages[Math.min(REVISION_VIEW.target.page, pages.length) - 1]?.el.scrollIntoView({ block: 'start' });
    drawPinGuide();
  }
  REVISION_ZOOM.anchor = revisionAnchor();
  scheduleRevisionPaint();
}

/** Coalesce scroll/layout updates and release canvases outside a viewport margin. */
function scheduleRevisionPaint() {
  if (REVISION_ZOOM.frame || !revisionPdfActive()) return;
  REVISION_ZOOM.frame = requestAnimationFrame(() => {
    REVISION_ZOOM.frame = 0;
    void paintRevisionPdf();
  });
}

/** Render near pages serially with a pixel cap; canceled work never reports errors. */
async function paintRevisionPdf() {
  if (!revisionPdfActive()) return;
  if (REVISION_ZOOM.busy === REVISION_ZOOM.gen) {
    REVISION_ZOOM.repaint = true;
    return;
  }
  REVISION_ZOOM.repaint = false;
  const generation = REVISION_ZOOM.gen;
  REVISION_ZOOM.busy = generation;
  try {
    const box = $('#revision-pdf'),
      boxRect = box.getBoundingClientRect(),
      margin = box.clientHeight * 1.5;
    const near = REVISION_ZOOM.pages.filter((item) => {
      const pageRect = item.el.getBoundingClientRect();
      const keep = pageRect.bottom >= boxRect.top - margin && pageRect.top <= boxRect.bottom + margin;
      if (!keep) dropRevisionPage(item);
      return keep;
    });
    near.sort(
      (left, right) =>
        Math.abs(left.el.getBoundingClientRect().top - boxRect.top) -
        Math.abs(right.el.getBoundingClientRect().top - boxRect.top),
    );
    for (const item of near) {
      if (generation !== REVISION_ZOOM.gen || !revisionPdfActive()) return;
      if (item.canvas || item.el.dataset.state === 'error') continue;
      const pageRect = item.el.getBoundingClientRect();
      if (pageRect.bottom < boxRect.top - margin || pageRect.top > boxRect.bottom + margin) continue;
      const canvas = document.createElement('canvas'),
        width = item.el.clientWidth,
        height = item.el.clientHeight;
      const target = canvasBackingTarget(width, height, Math.min(2, devicePixelRatio || 1), VECTOR_PIXEL_CAP);
      canvas.width = target.bw;
      canvas.height = target.bh;
      item.canvas = canvas;
      item.el.append(canvas);
      item.el.dataset.state = 'loading';
      const viewport = item.page.getViewport({ scale: width / item.base.width });
      const task = item.page.render({
        canvasContext: canvas.getContext('2d'),
        viewport,
        transform: [target.bw / width, 0, 0, target.bh / height, 0, 0],
      });
      item.task = task;
      COMPARISON_PDF.tasks.add(task);
      try {
        await task.promise;
        if (generation === REVISION_ZOOM.gen && item.canvas === canvas) item.el.dataset.state = 'ready';
      } catch (error) {
        if (generation === REVISION_ZOOM.gen && item.canvas === canvas) {
          item.el.dataset.state = 'error';
          $('#revision-status').textContent = '일부 비교 PDF 쪽을 그리지 못했습니다. 소스 diff를 확인할 수 있습니다.';
        }
      } finally {
        COMPARISON_PDF.tasks.delete(task);
        if (item.task === task) item.task = null;
      }
    }
  } catch (error) {
    if (generation === REVISION_ZOOM.gen && revisionPdfActive())
      $('#revision-status').textContent = '일부 비교 PDF 쪽을 그리지 못했습니다. 소스 diff를 확인할 수 있습니다.';
  } finally {
    if (REVISION_ZOOM.busy === generation) {
      REVISION_ZOOM.busy = 0;
      if (REVISION_ZOOM.repaint) scheduleRevisionPaint();
    }
  }
}

/** Comparison input stays on its scroll area; detach gesture state on document exit. */
(function revisionZoomInputs() {
  const box = $('#revision-pdf');
  let frame = 0,
    pendingFactor = 1,
    point: number[] | null = null;
  let gesture: { ratio: number; anchor: RevisionAnchor | null } | null = null;
  let touch: { distance: number; ratio: number; anchor: RevisionAnchor | null } | null = null;
  /** Apply the composed wheel gesture only to the current comparison. */
  const flush = () => {
    frame = 0;
    const factor = pendingFactor,
      wheelPoint = point;
    pendingFactor = 1;
    point = null;
    if (wheelPoint) revisionZoomTo(REVISION_ZOOM.ratio * factor, wheelPoint[0], wheelPoint[1]);
  };
  REVISION_ZOOM.resetInput = () => {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    pendingFactor = 1;
    point = null;
    gesture = null;
    touch = null;
  };
  box.addEventListener(
    'wheel',
    (event: WheelEvent) => {
      if (!revisionPdfActive() || !(event.ctrlKey || event.metaKey)) return;
      event.preventDefault();
      pendingFactor *= wheelFactor(event.deltaY, event.deltaMode);
      point = [event.clientX, event.clientY];
      if (!frame) frame = requestAnimationFrame(flush);
    },
    { passive: false },
  );
  box.addEventListener(
    'gesturestart',
    (event: SafariGestureEvent) => {
      if (!revisionPdfActive()) return;
      event.preventDefault();
      gesture = { ratio: REVISION_ZOOM.ratio, anchor: revisionAnchor(event.clientX, event.clientY) };
    },
    { passive: false },
  );
  box.addEventListener(
    'gesturechange',
    (event: SafariGestureEvent) => {
      if (!gesture || touch || !revisionPdfActive() || !(event.scale > 0)) return;
      event.preventDefault();
      revisionZoomTo(gesture.ratio * event.scale, event.clientX, event.clientY, gesture.anchor);
    },
    { passive: false },
  );
  box.addEventListener('gestureend', () => {
    gesture = null;
  });
  /** Distance and midpoint of the two touches in viewport coordinates. */
  const points = (touches: TouchList) => {
    const first = touches[0],
      second = touches[1];
    return {
      distance: Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY) || 1,
      x: (first.clientX + second.clientX) / 2,
      y: (first.clientY + second.clientY) / 2,
    };
  };
  box.addEventListener(
    'touchstart',
    (event: TouchEvent) => {
      if (!revisionPdfActive() || event.touches.length !== 2) {
        touch = null;
        return;
      }
      if (event.cancelable) event.preventDefault();
      const pinch = points(event.touches);
      touch = { distance: pinch.distance, ratio: REVISION_ZOOM.ratio, anchor: revisionAnchor(pinch.x, pinch.y) };
    },
    { passive: false },
  );
  box.addEventListener(
    'touchmove',
    (event: TouchEvent) => {
      if (!touch || event.touches.length !== 2 || !revisionPdfActive()) return;
      if (event.cancelable) event.preventDefault();
      const pinch = points(event.touches);
      revisionZoomTo((touch.ratio * pinch.distance) / touch.distance, pinch.x, pinch.y, touch.anchor);
    },
    { passive: false },
  );
  box.addEventListener('touchend', (event: TouchEvent) => {
    if (event.touches.length !== 2) touch = null;
  });
  box.addEventListener('touchcancel', () => {
    touch = null;
  });
  box.addEventListener(
    'scroll',
    () => {
      if (revisionPdfActive()) {
        // A resize may clamp the scroll before its observer runs: the reading point read before stays until the layout
        // handles it.
        if (Math.abs(revisionFitWidth() - REVISION_ZOOM.fit) <= 0.5 && box.clientHeight === REVISION_ZOOM.height)
          REVISION_ZOOM.anchor = revisionAnchor();
        scheduleRevisionPaint();
      }
    },
    { passive: true },
  );
  const observer = new ResizeObserver(() => {
    if (!revisionPdfActive()) return;
    if (Math.abs(revisionFitWidth() - REVISION_ZOOM.fit) > 0.5 || box.clientHeight !== REVISION_ZOOM.height)
      resizeRevisionPdf();
  });
  observer.observe(box);
})();
export {
  REVISION_ZOOM,
  disposeRevisionZoom,
  drawRevisionZoom,
  mountRevisionPdf,
  resizeRevisionPdf,
  revisionPdfActive,
  revisionZoom,
};
