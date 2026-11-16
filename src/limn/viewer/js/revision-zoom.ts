import { $, DIFF_FORMAT } from './core.ts';
import { tl } from './i18n.ts';
import { REV, REV_PDF, revTargetNote, revisionCurrent } from './revisions.ts';
import { ZOOM_STEP } from './pages.ts';
import { VEC_PIX_CAP } from './pdf-open.ts';
import { vecTarget } from './pdf-draw.ts';
import { wheelFactor } from './zoom.ts';
// ------------------------------------------------ The comparison PDF's zoom (docs/handbook/viewer.md §변경 보기)
// The changes view's own page geometry, zoom and rendering: its ratio is the comparison's alone, and nothing here
// writes the manuscript's zoom or any other preference. RZ: the ratio, the fit width and pane height it was laid out
// at, the generation stale work compares against (gen), the generation a paint runs for (busy), the frame a paint waits
// on, whether a paint was asked for while one ran (repaint), the pages, the reading point kept across a layout (anchor)
// and the reset of the gesture state (resetInput).
type RevisionPage = {
  el: HTMLElement;
  page: any;
  base: { width: number; height: number };
  canvas: HTMLCanvasElement | null;
  task: any;
};
type RevisionAnchor = { el: HTMLElement; fx: number; fy: number; x: number; y: number };
const RZ = {
  ratio: 1,
  fit: 0,
  height: 0,
  gen: 0,
  busy: 0,
  frame: 0,
  repaint: false,
  pages: [] as RevisionPage[],
  anchor: null as RevisionAnchor | null,
  resetInput: () => {},
};

/** Clamp a requested ratio, including non-finite input, to the comparison range. */
function revisionRatio(ratio) {
  return Number.isNaN(ratio) ? 1 : Math.max(0.5, Math.min(5, ratio));
}

/** Only a ready, visible comparison PDF owns PDF zoom input. */
function revisionPdfActive() {
  return document.body.classList.contains('revision-open') && REV.format === DIFF_FORMAT.PDF && RZ.pages.length > 0;
}

/** Synchronize the comparison toolbar without touching manuscript controls. */
function drawRevisionZoom() {
  $('#revision-zoom').hidden = REV.format !== DIFF_FORMAT.PDF;
  const ready = revisionPdfActive();
  $('#revision-zoom-value').textContent = Math.round(RZ.ratio * 100) + '%';
  $('#revision-zoom-out').disabled = !ready || RZ.ratio <= 0.5;
  $('#revision-zoom-in').disabled = !ready || RZ.ratio >= 5;
  $('#revision-fit').disabled = !ready;
}

/** Cancel a page and release its pixel allocation on zoom, eviction or exit. */
function dropRevisionPage(item) {
  if (item.task) {
    item.task.cancel();
    REV_PDF.tasks.delete(item.task);
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
  ++RZ.gen;
  RZ.resetInput();
  RZ.repaint = false;
  if (RZ.frame) {
    cancelAnimationFrame(RZ.frame);
    RZ.frame = 0;
  }
  RZ.pages.forEach(dropRevisionPage);
  RZ.pages = [];
  RZ.anchor = null;
  RZ.fit = RZ.height = 0;
  drawRevisionZoom();
}

/** Remember the nearest page and fractional position under a viewport point. */
function revisionAnchor(x?, y?) {
  const box = $('#revision-pdf'),
    boxRect = box.getBoundingClientRect();
  x = x ?? boxRect.left + box.clientWidth / 2;
  y = y ?? boxRect.top + box.clientHeight / 2;
  let nearest = null as HTMLElement | null,
    distance = Infinity;
  for (const item of RZ.pages) {
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
function restoreRevisionAnchor(anchor, x?, y?) {
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
    anchor = RZ.anchor ? { ...RZ.anchor, x: box.clientWidth / 2, y: box.clientHeight / 2 } : null;
  layoutRevisionPdf(anchor);
}

// Resize all page boxes before restoring the anchor; redraw at the new width. The widest page takes the zoomed width
// and every other page its own share of it, so pages keep their sizes on paper relative to each other, as the
// manuscript's do.
function layoutRevisionPdf(anchor) {
  if (!revisionPdfActive()) return;
  const box = $('#revision-pdf'),
    fit = revisionFitWidth();
  if (fit <= 0) return;
  RZ.fit = fit;
  RZ.height = box.clientHeight;
  ++RZ.gen;
  RZ.pages.forEach(dropRevisionPage);
  const width = fit * RZ.ratio,
    group = box.firstElementChild,
    widest = Math.max(...RZ.pages.map((item) => item.base.width));
  if (group instanceof HTMLElement) group.style.width = width + 'px';
  for (const item of RZ.pages) {
    const pageWidth = (width * item.base.width) / widest;
    item.el.style.width = pageWidth + 'px';
    item.el.style.height = (pageWidth * item.base.height) / item.base.width + 'px';
  }
  restoreRevisionAnchor(anchor);
  RZ.anchor = revisionAnchor();
  drawRevisionZoom();
  scheduleRevisionPaint();
}

/** Zoom around a pointer, a touch midpoint or the viewport center. */
function revisionZoomTo(ratio, x?, y?, anchor?) {
  if (!revisionPdfActive()) return;
  const point = anchor || revisionAnchor(x, y);
  RZ.ratio = revisionRatio(ratio);
  layoutRevisionPdf(point);
  if (anchor) {
    restoreRevisionAnchor(anchor, x, y);
    RZ.anchor = revisionAnchor();
  }
}

/** Apply the same button step as the manuscript, or restore fit width. */
function revisionZoom(action) {
  revisionZoomTo(action === 'fit' ? 1 : RZ.ratio * (action === 'in' ? ZOOM_STEP : 1 / ZOOM_STEP));
}

/** Obtain page geometry without allocating canvases; abandon stale PDF visits. */
async function mountRevisionPdf(pdf, seq, docKey, id) {
  const generation = RZ.gen,
    pages = [] as RevisionPage[];
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
    const page = await pdf.getPage(pageNumber);
    if (generation !== RZ.gen || !revisionCurrent(seq, docKey, id)) return;
    const pageElement = document.createElement('div');
    pageElement.className = 'revision-page';
    pageElement.dataset.page = String(pageNumber);
    pageElement.setAttribute('aria-label', tl('비교 PDF {page}쪽', { page: pageNumber }));
    pages.push({ el: pageElement, page, base: page.getViewport({ scale: 1 }), canvas: null, task: null });
  }
  const group = document.createElement('div');
  group.className = 'revision-pages';
  for (const item of pages) group.append(item.el);
  $('#revision-pdf').replaceChildren(group);
  RZ.pages = pages;
  layoutRevisionPdf(null);
  drawRevisionZoom();
  if (REV.target && REV.target.page) {
    pages[Math.min(REV.target.page, pages.length) - 1]?.el.scrollIntoView({ block: 'start' });
    revTargetNote();
  }
  RZ.anchor = revisionAnchor();
  scheduleRevisionPaint();
}

/** Coalesce scroll/layout updates and release canvases outside a viewport margin. */
function scheduleRevisionPaint() {
  if (RZ.frame || !revisionPdfActive()) return;
  RZ.frame = requestAnimationFrame(() => {
    RZ.frame = 0;
    void paintRevisionPdf();
  });
}

/** Render near pages serially with a pixel cap; canceled work never reports errors. */
async function paintRevisionPdf() {
  if (!revisionPdfActive()) return;
  if (RZ.busy === RZ.gen) {
    RZ.repaint = true;
    return;
  }
  RZ.repaint = false;
  const generation = RZ.gen;
  RZ.busy = generation;
  try {
    const box = $('#revision-pdf'),
      boxRect = box.getBoundingClientRect(),
      margin = box.clientHeight * 1.5;
    const near = RZ.pages.filter((item) => {
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
      if (generation !== RZ.gen || !revisionPdfActive()) return;
      if (item.canvas || item.el.dataset.state === 'error') continue;
      const pageRect = item.el.getBoundingClientRect();
      if (pageRect.bottom < boxRect.top - margin || pageRect.top > boxRect.bottom + margin) continue;
      const canvas = document.createElement('canvas'),
        width = item.el.clientWidth,
        height = item.el.clientHeight;
      const target = vecTarget(width, height, Math.min(2, devicePixelRatio || 1), VEC_PIX_CAP);
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
      REV_PDF.tasks.add(task);
      try {
        await task.promise;
        if (generation === RZ.gen && item.canvas === canvas) item.el.dataset.state = 'ready';
      } catch (error) {
        if (generation === RZ.gen && item.canvas === canvas) {
          item.el.dataset.state = 'error';
          $('#revision-status').textContent = '일부 비교 PDF 쪽을 그리지 못했습니다. 소스 diff를 확인할 수 있습니다.';
        }
      } finally {
        REV_PDF.tasks.delete(task);
        if (item.task === task) item.task = null;
      }
    }
  } catch (error) {
    if (generation === RZ.gen && revisionPdfActive())
      $('#revision-status').textContent = '일부 비교 PDF 쪽을 그리지 못했습니다. 소스 diff를 확인할 수 있습니다.';
  } finally {
    if (RZ.busy === generation) {
      RZ.busy = 0;
      if (RZ.repaint) scheduleRevisionPaint();
    }
  }
}

/** Comparison input stays on its scroll area; detach gesture state on document exit. */
(function revisionZoomInputs() {
  const box = $('#revision-pdf');
  let frame = 0,
    pendingFactor = 1,
    point = null as number[] | null;
  let gesture = null as { ratio: number; anchor: RevisionAnchor | null } | null;
  let touch = null as { distance: number; ratio: number; anchor: RevisionAnchor | null } | null;
  /** Apply the composed wheel gesture only to the current comparison. */
  const flush = () => {
    frame = 0;
    const factor = pendingFactor,
      wheelPoint = point;
    pendingFactor = 1;
    point = null;
    if (wheelPoint) revisionZoomTo(RZ.ratio * factor, wheelPoint[0], wheelPoint[1]);
  };
  RZ.resetInput = () => {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    pendingFactor = 1;
    point = null;
    gesture = null;
    touch = null;
  };
  box.addEventListener(
    'wheel',
    (event) => {
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
    (event) => {
      if (!revisionPdfActive()) return;
      event.preventDefault();
      gesture = { ratio: RZ.ratio, anchor: revisionAnchor(event.clientX, event.clientY) };
    },
    { passive: false },
  );
  box.addEventListener(
    'gesturechange',
    (event) => {
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
  const points = (touches) => {
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
    (event) => {
      if (!revisionPdfActive() || event.touches.length !== 2) {
        touch = null;
        return;
      }
      if (event.cancelable) event.preventDefault();
      const pinch = points(event.touches);
      touch = { distance: pinch.distance, ratio: RZ.ratio, anchor: revisionAnchor(pinch.x, pinch.y) };
    },
    { passive: false },
  );
  box.addEventListener(
    'touchmove',
    (event) => {
      if (!touch || event.touches.length !== 2 || !revisionPdfActive()) return;
      if (event.cancelable) event.preventDefault();
      const pinch = points(event.touches);
      revisionZoomTo((touch.ratio * pinch.distance) / touch.distance, pinch.x, pinch.y, touch.anchor);
    },
    { passive: false },
  );
  box.addEventListener('touchend', (event) => {
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
        if (Math.abs(revisionFitWidth() - RZ.fit) <= 0.5 && box.clientHeight === RZ.height)
          RZ.anchor = revisionAnchor();
        scheduleRevisionPaint();
      }
    },
    { passive: true },
  );
  const observer = new ResizeObserver(() => {
    if (!revisionPdfActive()) return;
    if (Math.abs(revisionFitWidth() - RZ.fit) > 0.5 || box.clientHeight !== RZ.height) resizeRevisionPdf();
  });
  observer.observe(box);
})();
export {
  RZ,
  disposeRevisionZoom,
  drawRevisionZoom,
  mountRevisionPdf,
  resizeRevisionPdf,
  revisionPdfActive,
  revisionZoom,
};
