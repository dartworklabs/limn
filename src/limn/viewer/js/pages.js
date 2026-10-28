// The URL of page image p of the build on screen: /pages/<META.pages_build>/<name>, which the server caches for a year
// because a build's images never change (docs/handbook/api.md). Without a build name, the old /pages/<name>?v=<built_at>.
function pageSrc(p){const b=META.pages_build;
  return dq(b?'/pages/'+encodeURIComponent(b)+'/'+encodeURIComponent(p.name):'/pages/'+encodeURIComponent(p.name)+'?v='+encodeURIComponent(META.built_at));}
// Page sizes (docs/handbook/viewer.md §PDF 영역 전용 확대): every page box is its own paper width (pt_w, in points) times one
// scale K for the document on screen (CSS px per point), so the pages keep the sizes they have on paper relative to each
// other - a one-column figure is half as wide as a two-column one, as in print. K = PT_PX is the print size (1pt = 1/72in,
// the CSS inch 96px), which the zoom figure reads as 100%. Fit-width fits the widest page.
const PT_PX=96/72;
// The widest page's width in points: fit-width fits it and the limits count it. 612 (a letter page) before there are pages,
// only so that the arithmetic never divides by zero - nothing is drawn then.
function ptMax(){const m=META&&META.pages?META.pages.reduce((a,p)=>Math.max(a,p.pt_w||0),0):0; return m>0?m:612;}
// A page box's CSS width for a page pt_w points wide at scale k: whole px, at least 1. Pure.
function pageWidth(ptw,k){return Math.max(1,Math.round(ptw*k));}
function buildDoc(){
  const doc=$('#doc'); doc.replaceChildren(); COMPOSE.box=null;
  META.pages.forEach((p,i)=>{const d=document.createElement('div'); d.className='pg'; d.id='p'+(i+1); d.dataset.page=String(i+1);
    d.dataset.ptw=String(p.pt_w); d.style.width=pageWidth(p.pt_w,K)+'px'; d.style.aspectRatio=p.pt_w+' / '+p.pt_h;
    setHtml(d,html`<span class="no">${i+1}</span><img loading="lazy" draggable="false" alt="${tl('{page}쪽',{page:i+1})}" src="${pageSrc(p)}">`);
    doc.appendChild(d);});
  marks(); vecObserve();
}
// save=false is auto-fit - never saved. If a width fit for a narrow first window persisted into a wider window, the pages would look too small.
// The scale is never saved in compact (mid/narrow) - so a width fit for a folded screen never overrides the spread/desktop setting.
// The widest page's width stays within ZOOM_MIN-ZOOM_MAX times the fit-width (minimum 160px), widened to hold the print size so
// [100%] is always in reach. Overflow scrolls horizontally only within the PDF area (#left).
const ZOOM_MIN=0.5,ZOOM_MAX=5,ZOOM_STEP=1.2;
// The widest page's width limits [lo, hi] in px, for the fitted width fit and the print-size width actual. Pure.
function wBounds(fit,actual){const f=Math.max(160,fit),lo=Math.max(160,Math.round(Math.min(f*ZOOM_MIN,actual)));
  return [lo,Math.max(lo,Math.round(Math.max(f*ZOOM_MAX,actual)))];}
// The scale that fits the widest page to the PDF area (fitWidth).
function fitK(){return fitWidth()/ptMax();}
// Sets the scale K within wBounds and gives every page box its own width (pageWidth); saved in wide unless save is false
// (saveK). The marks' badges follow the new widths (markBadgeSides), and so do the page verdict lines (sizePv), the save
// chips (placeChips) and [더보기]'s zoom figure (drawZoom).
function setK(k,save){const m=ptMax(),b=wBounds(fitWidth(),m*PT_PX); K=Math.min(b[1],Math.max(b[0],k*m))/m;
  $$('.pg').forEach(e=>{e.style.width=pageWidth(+e.dataset.ptw||m,K)+'px';});
  markBadgeSides(); sizePv(); placeChips(); if(save!==false&&LAYOUT===LAYOUT_MODE.WIDE)saveK(); vecInvalidate(); drawZoom();}
// The zoom as [더보기] shows it: scale k against the print size, in percent, rounded; 100 before a scale is known. Pure.
function zoomPct(k){return k>0?Math.round(k/PT_PX*100):100;}
// Writes [더보기]'s zoom figure (a live region: it is read out as it changes).
function drawZoom(){const z=$('#m-zoom'); if(z)z.textContent=zoomPct(K)+'%';}
// The saved scale of the document on screen (wide only), or null: a figure document keeps its zoom against the print size
// (pinPrefs.figZoom), since print size is what a figure is checked at; any other document the widest page's width in px
// (pinPrefs.w), as it always has - one value for every LaTeX and view-only document.
function savedK(){const p=prefs();
  if(isFigureKind(META.kind))return typeof p.figZoom==='number'&&p.figZoom>0?p.figZoom*PT_PX:null;
  return typeof p.w==='number'&&p.w>0?p.w/ptMax():null;}
function saveK(){if(isFigureKind(META.kind))savePrefs({figZoom:Math.round(K/PT_PX*1e4)/1e4}); else savePrefs({w:pageWidth(ptMax(),K)});}
// The scale a document opens at with nothing saved, for its widest page m (points), the fitted width fit and the scroller's
// inner width inner (px): a figure document at print size, or fitted when its widest page is wider than the PDF area; any
// other fitted to the inner width - in wide (wide true) at most 900px. Pure.
function openScale(fig,m,fit,inner,wide){return fig?Math.min(PT_PX,fit/m):(wide?Math.min(inner,900):inner)/m;}
function defaultK(){return openScale(isFigureKind(META.kind),ptMax(),fitWidth(),innerW(),LAYOUT===LAYOUT_MODE.WIDE);}
// In compact, whether the scale on screen is one the user chose rather than the one the screen picks (defaultK): only a chosen
// one survives a re-fit (ZOOMED). Pressing [↔] on a figure that opened at print size is a choice; landing back on it is not.
function markZoomed(){if(LAYOUT!==LAYOUT_MODE.WIDE)ZOOMED=Math.abs(K-defaultK())>K*1e-3;}
function innerW(){const L=$('#left'),cs=getComputedStyle(L); return L.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);}
// Fit-width: in compact and on a wide touch screen, the scroller's inner width (innerW: its padding is the gap, which on touch keeps
// the page off the handles' hit areas); with a mouse in wide, #left.clientWidth minus 48px (left/right margins), as always.
function fitWidth(){return LAYOUT!==LAYOUT_MODE.WIDE||MQ_COARSE.matches?innerW():$('#left').clientWidth-48;}
// compact always takes the screen's scale (defaultK) unless the user chose another (ZOOMED). wide takes it too unless a scale
// is saved. A scroller that is not drawn - the changes view hides it - has no width to fit: fitted to it the pages shrank to
// the smallest width while the changes view was open, and the re-fit on the way back took the reading spot from those small
// pages, so the manuscript came back somewhere else (docs/handbook/viewer.md §변경 보기).
function autoW(){if(!$('#left').getClientRects().length)return;
  if(LAYOUT!==LAYOUT_MODE.WIDE){if(!ZOOMED)setK(defaultK(),false);return;}
  if(savedK()!==null)return; setK(defaultK(),false);}
// The scale to build a document's pages at before autoW looks again: a saved one in wide, else the screen's, else the one
// on screen (a scroller that is not drawn has no width to take it from).
function startK(){const s=LAYOUT===LAYOUT_MODE.WIDE?savedK():null; if(s!==null)return s;
  const d=$('#left').getClientRects().length?defaultK():0; return d>0?d:(K>0?K:PT_PX);}
// Zoom anchor: the page under screen coordinates (cx,cy) and its fraction within that page. If the point falls in the gap between pages, the vertically nearest page is used.
// Without coordinates, the center of the PDF area is used (keyboard/button).
function zoomAnchor(cx,cy){const L=$('#left'),lr=L.getBoundingClientRect();
  if(cx==null){cx=lr.left+L.clientWidth/2; cy=lr.top+L.clientHeight/2;}
  let best=/** @type {{pg:HTMLElement,r:DOMRect}|null} */(null),bd=Infinity;
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(),d=cy<r.top?r.top-cy:(cy>r.bottom?cy-r.bottom:0);
    if(d<bd){bd=d; best={pg,r};} if(d===0)break;}
  return best?{pg:best.pg,cx,cy,fx:(cx-best.r.left)/best.r.width,fy:(cy-best.r.top)/best.r.height}:null;}
// Restores the anchor's in-page fractional position back to screen coordinates (cx,cy) - so the text under the pointer stays put even after zooming.
function zoomRestore(a,cx,cy){if(!a)return; const L=$('#left'),r=a.pg.getBoundingClientRect();
  L.scrollLeft+=r.left+a.fx*r.width-(cx==null?a.cx:cx); L.scrollTop+=r.top+a.fy*r.height-(cy==null?a.cy:cy);}
function zoomTo(k,cx,cy){const a=zoomAnchor(cx,cy); setK(k); markZoomed(); zoomRestore(a);}
function zoom(n){zoomTo(K*Math.pow(ZOOM_STEP,n));}
// [100%] and Ctrl/Cmd 1: the print size, around the middle of the PDF area as the zoom buttons.
function actualSize(){zoomTo(PT_PX);}
// Fit width (fitK): keeps the viewed page/position (anchored at the top) and resets horizontal scroll to the start.
function fitW(){const a=topAnchor(),L=$('#left');
  setK(fitK(),LAYOUT===LAYOUT_MODE.WIDE); markZoomed(); restoreAnchor(a); L.scrollLeft=0;}
function goPage(v){const el=document.getElementById('p'+parseInt(v===undefined?$('#jump').value:v,10)); if(el) el.scrollIntoView({behavior:SMOOTH});}
$('#jump').addEventListener('keydown',e=>{if(e.key==='Enter')goPage();});
// The page a typed entry v goes to in a document of n pages: a whole number clamped to 1..n; null for an empty or non-number
// entry, which goes nowhere. Pure.
function clampPage(v,n){const s=String(v==null?'':v).trim(); if(!/^-?\d+$/.test(s)||!(n>=1))return null; return Math.min(n,Math.max(1,parseInt(s,10)));}
// The navigation sheet's page field (Enter or [이동]): goes to the clamped page and closes the sheet; nothing typed does nothing.
function navGo(){const p=clampPage($('#ns-page-in').value,META&&META.pages?META.pages.length:0); if(p===null)return;
  $('#nav-sheet').close(); if(document.body.classList.contains('revision-open'))setViewMode(VIEW_MODE.MANUSCRIPT); goPage(p);}
$('#ns-page-in').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault(); navGo();}});

