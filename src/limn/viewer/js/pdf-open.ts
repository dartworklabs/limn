// ------------------------------------------------ Vector rendering (PDF.js) - docs/handbook/viewer.md §벡터 렌더링
// Each page draws the PDF directly onto a canvas. Backing size = page CSS size x devicePixelRatio (x the browser's pinch
// scale), and app zoom is already baked into each page's CSS width (pt_w x K). The page box, aspect ratio, and % coordinates stay
// exactly as they were for PNG, so drag frac/marks/pdf_build never change.
// - Only pages near the visible area (VEC_KEEP) are drawn; canvases for pages that scroll away are released (IntersectionObserver).
// - A single canvas never exceeds VEC_PIX_CAP pixels. At zoom beyond that, the page canvas is capped and a detail canvas (.dt)
//   rendered at native resolution for just the visible portion is overlaid on top.
// - When zoom changes, the existing canvas is stretched via CSS to stay visible while a debounced redraw happens (no flicker).
// - If pdf.js/the PDF fails to load or render, the canvas is torn down, falling back to the PNG <img>, and the status chip (#vec-chip) reports it.
// No text-selection layer is added - since dragging means selecting a region, it would conflict with text selection.
import { $, DOC, META } from './core.ts';
import { tl } from './i18n.ts';
import { dq } from './doc-tabs.ts';
import { loadOutline, outlineForget } from './outline.ts';
import { vecCancel, vecClose, vecFail, vecSchedule } from './pdf-draw.ts';
import { searchClear, searchOffer } from './search.ts';
import { isMdDoc } from './md-surface.ts';
const PDFJS_V = '__PDFJS_VERSION__';
const VEC_PIX_CAP = 16777216,
  VEC_KEEP = '150% 0px',
  VEC_DT_MARGIN = 0.25;
// PDF.js has no type declarations here, so its library, document and render task are `any`.
const VEC = {
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
// Multiple documents: holds up to VEC_CACHE_MAX recently opened PDF document objects keyed by 'document|build' - switching tabs back
// draws immediately without re-fetching. Beyond that, the least recently used is closed first (worker memory). An old build of the same document is closed when a new build opens.
const VECTOR_CACHE_MAX = 3;
function vectorCacheKey(docName, build) {
  return (docName || '') + '|' + (build || '');
}
function cacheVectorDocument(key, doc) {
  const cache = VEC.cache;
  cache.delete(key);
  cache.set(key, doc);
  const docPrefix = key.split('|')[0] + '|';
  Array.from(cache.keys()).forEach((cachedKey) => {
    if (cachedKey !== key && cachedKey.startsWith(docPrefix)) {
      const cachedDoc = cache.get(cachedKey);
      cache.delete(cachedKey);
      if (cachedDoc !== VEC.doc) vecClose(cachedDoc);
    }
  });
  while (cache.size > VECTOR_CACHE_MAX) {
    const cachedKey = cache.keys().next().value,
      cachedDoc = cache.get(cachedKey);
    cache.delete(cachedKey);
    if (cachedDoc !== VEC.doc && cachedDoc !== doc) vecClose(cachedDoc);
  }
}
function isVectorCached(doc) {
  for (const cachedDoc of VEC.cache.values()) if (cachedDoc === doc) return true;
  return false;
}
function vecForget(doc) {
  VEC.cache.forEach((cachedDoc, cachedKey) => {
    if (cachedDoc === doc) VEC.cache.delete(cachedKey);
  });
}
window.__pinVec = VEC; // for measurement (Playwright) - canvas count, render time
async function vecBoot() {
  if (!window.IntersectionObserver) {
    vecFail('이 브라우저는 IntersectionObserver 가 없습니다');
    return;
  }
  try {
    VEC.lib = await import('/vendor/pdfjs/pdf.min.mjs?v=' + PDFJS_V);
    VEC.lib.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.min.mjs?v=' + PDFJS_V;
  } catch (error) {
    VEC.lib = null;
    vecFail('pdf.js 를 불러오지 못했습니다', error);
    return;
  }
  await vecOpen();
}
// Opens the PDF for the currently displayed build (META.pages_build). Never used if the page count differs from what's on screen (coordinates would be off).
async function vecOpen() {
  // A Markdown document has no PDF: the PDF work still pending for the document left (its fetch, outline, pages) is
  // stale from here, or its outline would land over the Markdown headings.
  if (isMdDoc()) {
    VEC.gen++;
    vecCancel();
    return;
  }
  if (!VEC.lib || !META) return;
  const gen = ++VEC.gen,
    build = META.pages_build || '',
    pageCount = META.pages.length,
    key = vectorCacheKey(DOC, build);
  let doc = VEC.cache.get(key);
  vecCancel();
  searchClear(); // another document or build: its search starts empty (search.js)
  outlineForget(); // and the outline and page names of the document left behind are not the new one's (outline.js)
  if (!doc) {
    // The old document (a different document/old build) is never used for the new page DOM - PNG is shown while fetching.
    const previousDoc = VEC.doc;
    VEC.doc = null;
    VEC.build = null;
    if (previousDoc && !isVectorCached(previousDoc)) vecClose(previousDoc);
    try {
      const response = await fetch(
        dq('/pdf?build=' + encodeURIComponent(build) + '&v=' + encodeURIComponent(META.built_at || '')),
      );
      if (!response.ok) throw new Error('PDF HTTP ' + response.status);
      const data = new Uint8Array(await response.arrayBuffer());
      if (gen !== VEC.gen) return;
      doc = await VEC.lib.getDocument({ data, isEvalSupported: false, useWasm: false, enableXfa: false }).promise;
    } catch (error) {
      if (gen === VEC.gen) vecFail('PDF 를 벡터로 열지 못했습니다', error);
      return;
    }
    if (gen !== VEC.gen) {
      vecClose(doc);
      return;
    }
    if (doc.numPages !== pageCount) {
      vecClose(doc);
      vecFail(tl('PDF 쪽 수({pdf})가 화면({view})과 다릅니다', { pdf: doc.numPages, view: pageCount }));
      return;
    }
    cacheVectorDocument(key, doc);
  } else cacheVectorDocument(key, doc); // promoted as most recently used
  if (gen !== VEC.gen) return;
  const old = VEC.doc;
  VEC.doc = doc;
  VEC.build = build;
  VEC.failed = null;
  VEC.tDoc = performance.now();
  $('#vec-chip').hidden = true;
  loadOutline(doc, gen);
  searchOffer(); // its text can be searched now
  VEC.st.forEach((pageState) => {
    pageState.stale = true;
  });
  if (old && old !== doc && !isVectorCached(old)) vecClose(old);
  vecSchedule(0);
}
export { PDFJS_V, VEC, VEC_DT_MARGIN, VEC_KEEP, VEC_PIX_CAP, vecBoot, vecForget, vecOpen };
