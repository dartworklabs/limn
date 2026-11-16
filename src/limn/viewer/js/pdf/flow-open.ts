// ------------------------------------------------ Vector rendering (PDF.js) - docs/handbook/viewer.md §벡터 렌더링
// Each page draws the PDF directly onto a canvas. Backing size = page CSS size x devicePixelRatio (x the browser's
// pinch scale), and app zoom is already baked into each page's CSS width (pt_w x PAGE_SCALE). The page box, aspect
// ratio and % coordinates are the PNG page's, so drag frac, marks and pdf_build do not depend on the renderer.
// - Only pages near the visible area (VECTOR_KEEP_MARGIN) are drawn; canvases for pages that scroll away are released
//   (IntersectionObserver).
// - A single canvas never exceeds VECTOR_PIXEL_CAP pixels. At zoom beyond that, the page canvas is capped and a detail
//   canvas (.dt) rendered at native resolution for just the visible portion is overlaid on top.
// - When zoom changes, the existing canvas is stretched via CSS to stay visible while a debounced redraw happens (no
//   flicker).
// - If pdf.js or the PDF fails to load or render, the canvas is torn down, falling back to the PNG <img>, and the
//   status chip (#vec-chip) reports it.
// No text-selection layer is added: dragging selects a region, and a text layer would conflict with it.
import { DOC, META } from '../app/state.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { loadOutline, outlineForget } from './view-outline.ts';
import { cancelVectorDraw, closeVectorDocument, failVector, scheduleVectorDraw } from './view-draw.ts';
import { searchClear, searchOffer } from './flow.ts';
import { $ } from '../platform/dom.ts';
import { isMarkdownDoc, withDocQuery } from '../documents/state.ts';
const PDFJS_VERSION = '__PDFJS_VERSION__';
const VECTOR_PIXEL_CAP = 16777216,
  VECTOR_KEEP_MARGIN = '150% 0px',
  VECTOR_DETAIL_MARGIN = 0.25;
// PDF.js has no type declarations here, so its library, document and render task are `any`.
const VECTOR_PDF = {
  lib: null as any,
  doc: null as any,
  build: null as string | null,
  gen: 0,
  failed: null as string | null,
  io: null as IntersectionObserver | null,
  near: new Set<number>(),
  st: new Map(),
  cur: null as { n: number; task: any } | null,
  pumping: false,
  timer: 0,
  stats: [] as { n: number; kind: string; ms: number; w: number; h: number }[],
  tFirst: null as number | null,
  tDoc: null as number | null,
  cache: new Map(),
};
// Multiple documents: holds up to VECTOR_CACHE_MAX recently opened PDF document objects keyed by 'document|build', so
// switching tabs back draws immediately without re-fetching. Beyond that, the least recently used is closed first
// (worker memory). An old build of the same document is closed when a new build opens.
const VECTOR_CACHE_MAX = 3;
function vectorCacheKey(docName, build) {
  return (docName || '') + '|' + (build || '');
}
function cacheVectorDocument(key, doc) {
  const cache = VECTOR_PDF.cache;
  cache.delete(key);
  cache.set(key, doc);
  const docPrefix = key.split('|')[0] + '|';
  Array.from(cache.keys()).forEach((cachedKey) => {
    if (cachedKey !== key && cachedKey.startsWith(docPrefix)) {
      const cachedDoc = cache.get(cachedKey);
      cache.delete(cachedKey);
      if (cachedDoc !== VECTOR_PDF.doc) closeVectorDocument(cachedDoc);
    }
  });
  while (cache.size > VECTOR_CACHE_MAX) {
    const cachedKey = cache.keys().next().value,
      cachedDoc = cache.get(cachedKey);
    cache.delete(cachedKey);
    if (cachedDoc !== VECTOR_PDF.doc && cachedDoc !== doc) closeVectorDocument(cachedDoc);
  }
}
// Whether a PDF document object is one the cache still holds (and so must not be closed).
function isVectorCached(doc) {
  for (const cachedDoc of VECTOR_PDF.cache.values()) if (cachedDoc === doc) return true;
  return false;
}
// Drops a PDF document object from the cache without closing it.
function forgetVectorDocument(doc) {
  VECTOR_PDF.cache.forEach((cachedDoc, cachedKey) => {
    if (cachedDoc === doc) VECTOR_PDF.cache.delete(cachedKey);
  });
}
// For measurement (Playwright): canvas count, render time.
window.__pinVec = VECTOR_PDF;
// Loads pdf.js (once) and opens the PDF on screen; a browser without IntersectionObserver keeps the PNG pages.
async function bootVector() {
  if (!window.IntersectionObserver) {
    failVector('이 브라우저는 IntersectionObserver 가 없습니다');
    return;
  }
  try {
    VECTOR_PDF.lib = await import('/vendor/pdfjs/pdf.min.mjs?v=' + PDFJS_VERSION);
    VECTOR_PDF.lib.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.min.mjs?v=' + PDFJS_VERSION;
  } catch (error) {
    VECTOR_PDF.lib = null;
    failVector('pdf.js 를 불러오지 못했습니다', error);
    return;
  }
  await openVectorDocument();
}
// Opens the PDF for the currently displayed build (META.pages_build). A PDF whose page count differs from the pages on
// screen is never used: its coordinates would be off.
async function openVectorDocument() {
  // A Markdown document has no PDF: the PDF work still pending for the document left (its fetch, outline, pages) is
  // stale from here, or its outline would land over the Markdown headings.
  if (isMarkdownDoc()) {
    VECTOR_PDF.gen++;
    cancelVectorDraw();
    return;
  }
  if (!VECTOR_PDF.lib || !META) return;
  const gen = ++VECTOR_PDF.gen,
    build = META.pages_build || '',
    pageCount = META.pages.length,
    key = vectorCacheKey(DOC, build);
  let doc = VECTOR_PDF.cache.get(key);
  cancelVectorDraw();
  // Another document or build: its search starts empty (search.ts), and the outline and page names of the document
  // left behind are not the new one's (outline.ts).
  searchClear();
  outlineForget();
  if (!doc) {
    // The old document (a different document or an old build) is never used for the new page DOM: the PNG pages show
    // while the PDF is fetched.
    const previousDoc = VECTOR_PDF.doc;
    VECTOR_PDF.doc = null;
    VECTOR_PDF.build = null;
    if (previousDoc && !isVectorCached(previousDoc)) closeVectorDocument(previousDoc);
    try {
      const response = await fetch(
        withDocQuery('/pdf?build=' + encodeURIComponent(build) + '&v=' + encodeURIComponent(META.built_at || '')),
      );
      if (!response.ok) throw new Error('PDF HTTP ' + response.status);
      const data = new Uint8Array(await response.arrayBuffer());
      if (gen !== VECTOR_PDF.gen) return;
      doc = await VECTOR_PDF.lib.getDocument({ data, isEvalSupported: false, useWasm: false, enableXfa: false })
        .promise;
    } catch (error) {
      if (gen === VECTOR_PDF.gen) failVector('PDF 를 벡터로 열지 못했습니다', error);
      return;
    }
    if (gen !== VECTOR_PDF.gen) {
      closeVectorDocument(doc);
      return;
    }
    if (doc.numPages !== pageCount) {
      closeVectorDocument(doc);
      failVector(
        translateTemplate('PDF 쪽 수({pdf})가 화면({view})과 다릅니다', { pdf: doc.numPages, view: pageCount }),
      );
      return;
    }
    cacheVectorDocument(key, doc);
  } else cacheVectorDocument(key, doc); // promoted as most recently used
  if (gen !== VECTOR_PDF.gen) return;
  const old = VECTOR_PDF.doc;
  VECTOR_PDF.doc = doc;
  VECTOR_PDF.build = build;
  VECTOR_PDF.failed = null;
  VECTOR_PDF.tDoc = performance.now();
  $('#vec-chip').hidden = true;
  loadOutline(doc, gen);
  searchOffer(); // its text can be searched now
  VECTOR_PDF.st.forEach((pageState) => {
    pageState.stale = true;
  });
  if (old && old !== doc && !isVectorCached(old)) closeVectorDocument(old);
  scheduleVectorDraw(0);
}
export {
  PDFJS_VERSION,
  VECTOR_PDF,
  VECTOR_DETAIL_MARGIN,
  VECTOR_KEEP_MARGIN,
  VECTOR_PIXEL_CAP,
  bootVector,
  forgetVectorDocument,
  openVectorDocument,
};
