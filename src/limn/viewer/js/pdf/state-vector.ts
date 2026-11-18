// The PDF document on screen, its drawing state and cached documents.
const VECTOR_PIXEL_CAP = 16777216,
  VECTOR_KEEP_MARGIN = '150% 0px',
  VECTOR_DETAIL_MARGIN = 0.25;
// What is drawn for one page (view-draw.ts pageDrawState): its page canvas and the size it was drawn at, its detail canvas
// with the region of the page (fractions) it covers and the size and pixel ratio it was drawn at, and whether the page
// must be drawn again.
interface PageDrawState {
  base: HTMLCanvasElement | null;
  bw: number;
  bh: number;
  dt: HTMLCanvasElement | null;
  reg: { x: number; y: number; w: number; h: number } | null;
  dtCw: number;
  dtK: number;
  stale: boolean;
}
// The vector view's state (VECTOR_PDF): the PDF.js library once imported, the document on screen and its build, the
// generation each open and each failure bumps (a draw of an older one is dropped), why vector drawing gave up, the observer of the pages near the view and those pages,
// what is drawn for each page, the render running now, whether the draw queue is being worked, its timer, the draws'
// timings, when the first page and the document were drawn, and the opened documents cached by 'document|build'.
interface VectorPdfState {
  lib: PdfLibrary | null;
  doc: PdfDocument | null;
  build: string | null;
  gen: number;
  failed: string | null;
  io: IntersectionObserver | null;
  near: Set<number>;
  st: Map<number, PageDrawState>;
  cur: { n: number; task: PdfRenderTask } | null;
  pumping: boolean;
  timer: number;
  stats: { n: number; kind: string; ms: number; w: number; h: number }[];
  tFirst: number | null;
  tDoc: number | null;
  cache: Map<string, PdfDocument>;
}
// The PDF.js library (types/pdfjs.d.ts), the document on screen and the opened documents cached by 'document|build'.
const VECTOR_PDF: VectorPdfState = {
  lib: null,
  doc: null,
  build: null,
  gen: 0,
  failed: null,
  io: null,
  near: new Set(),
  st: new Map(),
  cur: null,
  pumping: false,
  timer: 0,
  stats: [],
  tFirst: null,
  tDoc: null,
  cache: new Map(),
};
// Each sets one field of VECTOR_PDF for another module that changes it (ADR-0042 D1): the assignment, nothing more.
function setVectorFailed(value: string | null) {
  VECTOR_PDF.failed = value;
}
function advanceVectorGeneration() {
  return ++VECTOR_PDF.gen;
}
function setVectorDocument(value: PdfDocument | null) {
  VECTOR_PDF.doc = value;
}
function setVectorObserver(value: IntersectionObserver | null) {
  VECTOR_PDF.io = value;
}
function setVectorTimer(value: number) {
  VECTOR_PDF.timer = value;
}
function setVectorPumping(value: boolean) {
  VECTOR_PDF.pumping = value;
}
function setVectorCurrent(value: typeof VECTOR_PDF.cur) {
  VECTOR_PDF.cur = value;
}
function setVectorFirstDrawn(value: number | null) {
  VECTOR_PDF.tFirst = value;
}
// Whether a PDF document object is one the cache still holds (and so must not be closed).
function isVectorCached(doc: PdfDocument | null) {
  for (const cachedDoc of VECTOR_PDF.cache.values()) if (cachedDoc === doc) return true;
  return false;
}
// Drops a PDF document object from the cache without closing it.
function forgetVectorDocument(doc: PdfDocument | null) {
  VECTOR_PDF.cache.forEach((cachedDoc, cachedKey) => {
    if (cachedDoc === doc) VECTOR_PDF.cache.delete(cachedKey);
  });
}
// For measurement (Playwright): canvas count, render time.
window.__pinVec = VECTOR_PDF;

function setVectorLibrary(library: PdfLibrary | null) {
  VECTOR_PDF.lib = library;
}
function setVectorBuild(build: string | null) {
  VECTOR_PDF.build = build;
}
function setVectorOpenedAt(time: number) {
  VECTOR_PDF.tDoc = time;
}
export {
  VECTOR_PDF,
  VECTOR_PIXEL_CAP,
  VECTOR_KEEP_MARGIN,
  VECTOR_DETAIL_MARGIN,
  setVectorFailed,
  advanceVectorGeneration,
  setVectorDocument,
  setVectorObserver,
  setVectorTimer,
  setVectorPumping,
  setVectorCurrent,
  setVectorFirstDrawn,
  setVectorLibrary,
  setVectorBuild,
  setVectorOpenedAt,
  isVectorCached,
  forgetVectorDocument,
};
