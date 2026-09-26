// ------------------------------------------------ Vector rendering (PDF.js) - docs/handbook/viewer.md §벡터 렌더링
// Each page draws the PDF directly onto a canvas. Backing size = page CSS size x devicePixelRatio (x the browser's pinch
// scale), and app zoom is already baked into the page CSS width (W). The page box, aspect ratio, and % coordinates stay
// exactly as they were for PNG, so drag frac/marks/pdf_build never change.
// - Only pages near the visible area (VEC_KEEP) are drawn; canvases for pages that scroll away are released (IntersectionObserver).
// - A single canvas never exceeds VEC_PIX_CAP pixels. At zoom beyond that, the page canvas is capped and a detail canvas (.dt)
//   rendered at native resolution for just the visible portion is overlaid on top.
// - When zoom changes, the existing canvas is stretched via CSS to stay visible while a debounced redraw happens (no flicker).
// - If pdf.js/the PDF fails to load or render, the canvas is torn down, falling back to the PNG <img>, and the status chip (#vec-chip) reports it.
// No text-selection layer is added - since dragging means selecting a region, it would conflict with text selection.
const PDFJS_V='__PDFJS_VERSION__';
const VEC_PIX_CAP=16777216, VEC_KEEP='150% 0px', VEC_DT_MARGIN=0.25;
const VEC={lib:null,doc:null,build:null,gen:0,failed:null,io:null,near:new Set(),st:new Map(),cur:null,
  pumping:false,timer:0,stats:[],tFirst:null,tDoc:null,cache:new Map()};
// Multiple documents: holds up to VEC_CACHE_MAX recently opened PDF document objects keyed by 'document|build' - switching tabs back
// draws immediately without re-fetching. Beyond that, the least recently used is closed first (worker memory). An old build of the same document is closed when a new build opens.
const VEC_CACHE_MAX=3;
function vecCacheKey(k,b){return (k||'')+'|'+(b||'');}
function vecCachePut(key,doc){const c=VEC.cache; c.delete(key); c.set(key,doc);
  const pre=key.split('|')[0]+'|';
  Array.from(c.keys()).forEach(x=>{if(x!==key&&x.startsWith(pre)){const d=c.get(x); c.delete(x); if(d!==VEC.doc)vecClose(d);}});
  while(c.size>VEC_CACHE_MAX){const x=c.keys().next().value,d=c.get(x); c.delete(x); if(d!==VEC.doc&&d!==doc)vecClose(d);}}
function vecCached(doc){for(const d of VEC.cache.values())if(d===doc)return true; return false;}
function vecForget(doc){VEC.cache.forEach((d,x)=>{if(d===doc)VEC.cache.delete(x);});}
window.__pinVec=VEC;   // for measurement (Playwright) - canvas count, render time
async function vecBoot(){
  if(!window.IntersectionObserver){vecFail('이 브라우저는 IntersectionObserver 가 없습니다');return;}
  try{VEC.lib=await import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V);
    VEC.lib.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V;}
  catch(e){VEC.lib=null; vecFail('pdf.js 를 불러오지 못했습니다',e); return;}
  await vecOpen();
}
// Opens the PDF for the currently displayed build (META.pages_build). Never used if the page count differs from what's on screen (coordinates would be off).
async function vecOpen(){
  if(!VEC.lib||!META)return;
  const gen=++VEC.gen, build=META.pages_build||'', n=META.pages.length, key=vecCacheKey(DOC,build); let doc=VEC.cache.get(key);
  vecCancel();
  if(!doc){
    // The old document (a different document/old build) is never used for the new page DOM - PNG is shown while fetching.
    const prev=VEC.doc; VEC.doc=null; VEC.build=null; if(prev&&!vecCached(prev))vecClose(prev);
    try{const r=await fetch(dq('/pdf?build='+encodeURIComponent(build)+'&v='+encodeURIComponent(META.built_at||'')));
      if(!r.ok)throw new Error('PDF HTTP '+r.status);
      const data=new Uint8Array(await r.arrayBuffer()); if(gen!==VEC.gen)return;
      doc=await VEC.lib.getDocument({data,isEvalSupported:false,useWasm:false,enableXfa:false}).promise;}
    catch(e){if(gen===VEC.gen)vecFail('PDF 를 벡터로 열지 못했습니다',e); return;}
    if(gen!==VEC.gen){vecClose(doc); return;}
    if(doc.numPages!==n){vecClose(doc); vecFail(tl('PDF 쪽 수({pdf})가 화면({view})과 다릅니다',{pdf:doc.numPages,view:n})); return;}
    vecCachePut(key,doc);
  }else vecCachePut(key,doc);           // promoted as most recently used
  if(gen!==VEC.gen)return;
  const old=VEC.doc; VEC.doc=doc; VEC.build=build; VEC.failed=null; VEC.tDoc=performance.now(); $('#vec-chip').hidden=true;
  loadOutline(doc,gen);
  VEC.st.forEach(s=>{s.stale=true;});
  if(old&&old!==doc&&!vecCached(old))vecClose(old);
  vecSchedule(0);
}
