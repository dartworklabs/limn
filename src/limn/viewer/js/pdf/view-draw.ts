// ------------------------------------------ Vector rendering: drawing the pages (docs/handbook/viewer.md §벡터 렌더링)
// The pages of the PDF pdf/flow-open.ts opened, drawn onto canvases one job at a time: pages within the viewport first,
// each page's canvas sized to the screen, a detail canvas over a capped one, and every canvas released when its page
// scrolls out of reach.
import { translateTemplate, translate } from '../platform/i18n.ts';
import {
  VECTOR_PDF,
  VECTOR_DETAIL_MARGIN,
  VECTOR_KEEP_MARGIN,
  VECTOR_PIXEL_CAP,
  forgetVectorDocument,
  setVectorFailed,
  advanceVectorGeneration,
  setVectorDocument,
  setVectorObserver,
  setVectorTimer,
  setVectorPumping,
  setVectorCurrent,
  setVectorFirstDrawn,
} from './state-vector.ts';
import { searchOffer } from './flow.ts';
import { $, $$ } from '../platform/dom.ts';
// Closes one document - PDFDocumentProxy has no destroy of its own; loadingTask frees the worker-side resources too.
function closeVectorDocument(doc: PdfDocument | null) {
  if (!doc) return;
  try {
    doc.loadingTask.destroy();
  } catch (error) {}
}
// Gives up on vector drawing for the document on screen: the pages stay PNG, and #vec-chip says why.
function failVector(message: string, cause?: unknown) {
  setVectorFailed(message);
  advanceVectorGeneration();
  cancelVectorDraw();
  releaseAllVectorPages();
  forgetVectorDocument(VECTOR_PDF.doc);
  closeVectorDocument(VECTOR_PDF.doc);
  setVectorDocument(null);
  // No PDF to read: no search.
  searchOffer();
  const chip = $('#vec-chip');
  chip.hidden = false;
  chip.dataset.tip = translateTemplate(
    'PDF를 벡터로 그리지 못해 이미지(PNG)로 보입니다 — {reason}. 확대하면 흐릴 수 있습니다',
    {
      reason:
        translate(message) +
        (typeof cause === 'object' && cause !== null && 'message' in cause && cause.message
          ? ' (' + String(cause.message).slice(0, 100) + ')'
          : ''),
    },
  );
}
// The draw state of a page (its canvases and the size they were drawn at), made on first use.
function pageDrawState(pageNumber: number) {
  let pageState = VECTOR_PDF.st.get(pageNumber);
  if (!pageState) {
    pageState = { base: null, bw: 0, bh: 0, dt: null, reg: null, dtCw: 0, dtK: 0, stale: false };
    VECTOR_PDF.st.set(pageNumber, pageState);
  }
  return pageState;
}
// Removes a canvas. It must shrink to 0 first, so Safari too releases its memory right away.
function dropCanvas(canvas: HTMLCanvasElement | null) {
  if (!canvas) return;
  canvas.width = 0;
  canvas.height = 0;
  canvas.remove();
}
function releasePageCanvases(pageNumber: number) {
  if (VECTOR_PDF.cur && VECTOR_PDF.cur.n === pageNumber) cancelVectorDraw();
  const pageState = VECTOR_PDF.st.get(pageNumber);
  if (!pageState) return;
  dropCanvas(pageState.base);
  dropCanvas(pageState.dt);
  VECTOR_PDF.st.delete(pageNumber);
  const pageElement = document.getElementById('p' + pageNumber);
  if (pageElement) pageElement.classList.remove('drawn');
}
function releaseAllVectorPages() {
  cancelVectorDraw();
  Array.from(VECTOR_PDF.st.keys()).forEach(releasePageCanvases);
}
function cancelVectorDraw() {
  const drawing = VECTOR_PDF.cur;
  setVectorCurrent(null);
  if (drawing && drawing.task) {
    try {
      drawing.task.cancel();
    } catch (error) {}
  }
}
function observeVectorPages() {
  if (VECTOR_PDF.io) VECTOR_PDF.io.disconnect();
  releaseAllVectorPages();
  VECTOR_PDF.near.clear();
  if (!window.IntersectionObserver) return;
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((en) => {
        const pageNumber = Number(en.target instanceof HTMLElement ? en.target.dataset.page : undefined);
        if (en.isIntersecting) VECTOR_PDF.near.add(pageNumber);
        else {
          VECTOR_PDF.near.delete(pageNumber);
          releasePageCanvases(pageNumber);
        }
      });
      scheduleVectorDraw(0);
    },
    { root: $('#left'), rootMargin: VECTOR_KEEP_MARGIN },
  );
  setVectorObserver(io);
  $$('.pg').forEach((pageElement) => io.observe(pageElement));
}
function scheduleVectorDraw(ms: number) {
  clearTimeout(VECTOR_PDF.timer);
  setVectorTimer(setTimeout(pumpDrawJobs, ms || 0));
}
// Zoom, window size or DPR changed: whatever was being drawn (at the old size) is discarded and redrawn shortly after.
// Meanwhile, the old canvas is shown stretched.
function invalidateVectorDraws() {
  if (!VECTOR_PDF.doc) return;
  cancelVectorDraw();
  scheduleVectorDraw(150);
}
// Backing pixels per CSS pixel: the device pixel ratio times the browser's pinch scale.
function backingScale() {
  const viewport = window.visualViewport;
  return (window.devicePixelRatio || 1) * Math.max(1, (viewport && viewport.scale) || 1);
}
// The page canvas's backing size. If it exceeds the cap, it is scaled down proportionally and marked capped (the
// detail canvas fills in the visible portion).
function canvasBackingTarget(cssWidth: number, cssHeight: number, pixelRatio: number, cap: number) {
  let backingWidth = Math.round(cssWidth * pixelRatio),
    backingHeight = Math.round(cssHeight * pixelRatio),
    capped = false;
  if (backingWidth * backingHeight > cap) {
    const shrinkFactor = Math.sqrt(cap / (backingWidth * backingHeight));
    backingWidth = Math.max(1, Math.floor(backingWidth * shrinkFactor));
    backingHeight = Math.max(1, Math.floor(backingHeight * shrinkFactor));
    capped = true;
  }
  return { cw: cssWidth, ch: cssHeight, k: pixelRatio, bw: backingWidth, bh: backingHeight, capped };
}
function pageBackingTarget(pageElement: HTMLElement) {
  const cssWidth = pageElement.clientWidth,
    cssHeight = pageElement.clientHeight;
  return cssWidth && cssHeight ? canvasBackingTarget(cssWidth, cssHeight, backingScale(), VECTOR_PIXEL_CAP) : null;
}
// The portion of a page visible on screen (page CSS px). margin is extra room relative to the viewport size (the
// detail canvas is drawn a bit larger).
function visiblePagePortion(pageElement: HTMLElement, margin: number) {
  const pdfArea = $('#left'),
    areaRect = pdfArea.getBoundingClientRect(),
    pageRect = pageElement.getBoundingClientRect();
  const originX = pageRect.left + pageElement.clientLeft,
    originY = pageRect.top + pageElement.clientTop,
    cssWidth = pageElement.clientWidth,
    cssHeight = pageElement.clientHeight;
  const viewX = areaRect.left + pdfArea.clientLeft,
    viewY = areaRect.top + pdfArea.clientTop,
    viewWidth = pdfArea.clientWidth,
    viewHeight = pdfArea.clientHeight,
    marginX = viewWidth * margin,
    marginY = viewHeight * margin;
  const x0 = Math.max(0, viewX - marginX - originX),
    y0 = Math.max(0, viewY - marginY - originY),
    x1 = Math.min(cssWidth, viewX + viewWidth + marginX - originX),
    y1 = Math.min(cssHeight, viewY + viewHeight + marginY - originY);
  return x1 > x0 && y1 > y0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0, cw: cssWidth, ch: cssHeight } : null;
}
// Whether a detail canvas's region (fractions of the page) covers the visible portion.
function regionCovers(
  region: { x: number; y: number; w: number; h: number } | null,
  visible: { x: number; y: number; w: number; h: number; cw: number; ch: number },
) {
  return (
    !!region &&
    region.x <= visible.x / visible.cw + 1e-6 &&
    region.y <= visible.y / visible.ch + 1e-6 &&
    region.x + region.w >= (visible.x + visible.w) / visible.cw - 1e-6 &&
    region.y + region.h >= (visible.y + visible.h) / visible.ch - 1e-6
  );
}
// The one thing to draw next: pages within the viewport first (nearest to center), page canvas before detail canvas.
function nextDrawJob() {
  if (!VECTOR_PDF.doc) return null;
  const pdfArea = $('#left'),
    areaRect = pdfArea.getBoundingClientRect(),
    top = areaRect.top,
    bottom = areaRect.top + pdfArea.clientHeight,
    centerY = (top + bottom) / 2;
  const list: { n: number; pg: HTMLElement; vis: boolean; d: number }[] = [];
  VECTOR_PDF.near.forEach((pageNumber) => {
    const pageElement = document.getElementById('p' + pageNumber);
    if (!pageElement) return;
    const pageRect = pageElement.getBoundingClientRect();
    list.push({
      n: pageNumber,
      pg: pageElement,
      vis: pageRect.bottom > top && pageRect.top < bottom,
      d: Math.abs((pageRect.top + pageRect.bottom) / 2 - centerY),
    });
  });
  list.sort((first, second) => Number(second.vis) - Number(first.vis) || first.d - second.d);
  for (const candidate of list) {
    const pageState = pageDrawState(candidate.n),
      target = pageBackingTarget(candidate.pg);
    if (!target) continue;
    if (!pageState.base || pageState.stale || pageState.bw !== target.bw || pageState.bh !== target.bh)
      return { n: candidate.n, kind: 'base' };
    if (target.capped && candidate.vis) {
      const visible = visiblePagePortion(candidate.pg, 0);
      if (
        visible &&
        (!pageState.dt ||
          pageState.dtCw !== target.cw ||
          pageState.dtK !== target.k ||
          !regionCovers(pageState.reg, visible))
      )
        return { n: candidate.n, kind: 'dt' };
    } else if (pageState.dt) {
      dropCanvas(pageState.dt);
      pageState.dt = null;
      pageState.reg = null;
    }
  }
  return null;
}
// Runs the draw jobs one after another until none is left; one pump at a time.
async function pumpDrawJobs() {
  if (VECTOR_PDF.pumping || !VECTOR_PDF.doc) return;
  setVectorPumping(true);
  try {
    for (let i = 0; i < 400; i++) {
      const job = nextDrawJob();
      if (!job) break;
      await runDrawJob(job);
    }
  } finally {
    setVectorPumping(false);
  }
}
async function runDrawJob(job: { n: number; kind: string }) {
  const pageNumber = job.n,
    pageElement = document.getElementById('p' + pageNumber),
    doc = VECTOR_PDF.doc,
    gen = VECTOR_PDF.gen;
  if (!pageElement || !doc) return;
  // A page number past the document's last page means another document or build replaced it. openVectorDocument's
  // generation check keeps that from happening; this only skips the case.
  if (pageNumber > doc.numPages) return;
  let page;
  try {
    page = await doc.getPage(pageNumber);
  } catch (error) {
    if (gen === VECTOR_PDF.gen) failVector('쪽을 읽지 못했습니다', error);
    return;
  }
  if (gen !== VECTOR_PDF.gen || !VECTOR_PDF.near.has(pageNumber) || !document.contains(pageElement)) return;
  const target = pageBackingTarget(pageElement);
  if (!target) return;
  const unitViewport = page.getViewport({ scale: 1 }),
    canvas = document.createElement('canvas');
  let scale,
    transform,
    region: { x: number; y: number; w: number; h: number } | null = null;
  // Width and height are fit independently (the transform's vertical scale) - the page box's aspect ratio comes from
  // the PNG pixel dimensions and differs from the PDF page's aspect ratio by less than 0.1%. The PNG fills that same
  // box, so this is what lands the canvas's text at the same % position as the PNG's.
  if (job.kind === 'base') {
    canvas.width = target.bw;
    canvas.height = target.bh;
    scale = target.bw / unitViewport.width;
    transform = [1, 0, 0, target.bh / (unitViewport.height * scale), 0, 0];
  } else {
    const visible = visiblePagePortion(pageElement, VECTOR_DETAIL_MARGIN);
    if (!visible) return;
    let pixelRatio = target.k;
    if (visible.w * visible.h * pixelRatio * pixelRatio > VECTOR_PIXEL_CAP)
      pixelRatio = Math.sqrt(VECTOR_PIXEL_CAP / (visible.w * visible.h));
    scale = (target.cw * pixelRatio) / unitViewport.width;
    canvas.width = Math.max(1, Math.round(visible.w * pixelRatio));
    canvas.height = Math.max(1, Math.round(visible.h * pixelRatio));
    transform = [
      1,
      0,
      0,
      (target.ch * pixelRatio) / (unitViewport.height * scale),
      -visible.x * pixelRatio,
      -visible.y * pixelRatio,
    ];
    region = { x: visible.x / target.cw, y: visible.y / target.ch, w: visible.w / target.cw, h: visible.h / target.ch };
  }
  const canvasContext = canvas.getContext('2d', { alpha: false }),
    startedAt = performance.now();
  // PDF.js reads canvasContext.canvas, so it fails on a null context as well; this fails the same way, outside the try.
  if (!canvasContext) throw new Error('the page canvas has no 2D context');
  const task = page.render({
    canvasContext: canvasContext,
    viewport: page.getViewport({ scale }),
    transform: transform,
  });
  setVectorCurrent({ n: pageNumber, task });
  try {
    await task.promise;
  } catch (error) {
    if (VECTOR_PDF.cur && VECTOR_PDF.cur.task === task) setVectorCurrent(null);
    dropCanvas(canvas);
    if (error instanceof Error && error.name === 'RenderingCancelledException') return;
    if (gen === VECTOR_PDF.gen) failVector('쪽을 그리지 못했습니다', error);
    return;
  }
  if (VECTOR_PDF.cur && VECTOR_PDF.cur.task === task) setVectorCurrent(null);
  const targetAfter =
    gen === VECTOR_PDF.gen && VECTOR_PDF.near.has(pageNumber) && document.contains(pageElement)
      ? pageBackingTarget(pageElement)
      : null;
  // Zoom or window size changed while drawing.
  if (!targetAfter || targetAfter.cw !== target.cw || targetAfter.ch !== target.ch || targetAfter.k !== target.k) {
    dropCanvas(canvas);
    return;
  }
  VECTOR_PDF.stats.push({
    n: pageNumber,
    kind: job.kind,
    ms: Math.round(performance.now() - startedAt),
    w: canvas.width,
    h: canvas.height,
  });
  if (VECTOR_PDF.stats.length > 200) VECTOR_PDF.stats.splice(0, VECTOR_PDF.stats.length - 200);
  const pageState = pageDrawState(pageNumber);
  if (job.kind === 'base') {
    dropCanvas(pageState.base);
    pageState.base = canvas;
    pageState.bw = target.bw;
    pageState.bh = target.bh;
    pageState.stale = false;
    canvas.className = 'vb';
    pageElement.prepend(canvas);
    pageElement.classList.add('drawn');
    if (VECTOR_PDF.tFirst === null) setVectorFirstDrawn(performance.now());
  } else if (region) {
    // A detail job always measures its region above.
    const drawnRegion = region;
    dropCanvas(pageState.dt);
    pageState.dt = canvas;
    pageState.reg = drawnRegion;
    pageState.dtCw = target.cw;
    pageState.dtK = target.k;
    canvas.className = 'dt';
    Object.assign(canvas.style, {
      left: drawnRegion.x * 100 + '%',
      top: drawnRegion.y * 100 + '%',
      width: drawnRegion.w * 100 + '%',
      height: drawnRegion.h * 100 + '%',
    });
    if (pageState.base) pageState.base.after(canvas);
    else pageElement.prepend(canvas);
  }
}
$('#left').addEventListener(
  'scroll',
  () => {
    if (VECTOR_PDF.doc) scheduleVectorDraw(120);
  },
  { passive: true },
);
// devicePixelRatio changes with browser zoom (Ctrl+wheel outside the PDF, etc.) or moving the window to a different
// screen: the pages redraw at that scale.
(function watchDpr() {
  if (!window.matchMedia) return;
  matchMedia('(resolution: ' + (window.devicePixelRatio || 1) + 'dppx)').addEventListener(
    'change',
    () => {
      invalidateVectorDraws();
      watchDpr();
    },
    { once: true },
  );
})();
{
  const viewport = window.visualViewport;
  if (viewport)
    viewport.addEventListener('resize', () => {
      if (VECTOR_PDF.doc) scheduleVectorDraw(300);
    });
}

export {
  cancelVectorDraw,
  closeVectorDocument,
  failVector,
  invalidateVectorDraws,
  observeVectorPages,
  releaseAllVectorPages,
  scheduleVectorDraw,
  canvasBackingTarget,
};
