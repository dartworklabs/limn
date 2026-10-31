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
// The most common page width of widths ws (points): the mode, the wider on a tie; 0 for none. A figure document opens by it
// (openScale): its one wide outlier (a graphical abstract) scrolls sideways instead of shrinking every figure. Pure.
function commonWidth(ws){const n=new Map(); let best=0,most=0;
  for(const w of ws){if(!(w>0))continue; const c=(n.get(w)||0)+1; n.set(w,c); if(c>most||(c===most&&w>best)){most=c; best=w;}}
  return best;}
function ptCommon(){const c=META&&META.pages?commonWidth(META.pages.map(p=>p.pt_w)):0; return c>0?c:ptMax();}
// A page box's CSS width for a page pt_w points wide at scale k: whole px, at least 1. Pure.
function pageWidth(ptw,k){return Math.max(1,Math.round(ptw*k));}
// Every page box sits in a block of its own (.pgw) that a page verdict line (verdict.js) joins under it: the line is sticky
// to the bottom of the PDF area within that block, so it floats while its page is in view and settles under the page at its
// end - in one block with every page it would float over the next pages' lines.
function buildDoc(){
  const doc=$('#doc'); doc.replaceChildren(); COMPOSE.box=null;
  META.pages.forEach((p,i)=>{const d=document.createElement('div'); d.className='pg'; d.id='p'+(i+1); d.dataset.page=String(i+1);
    d.dataset.ptw=String(p.pt_w); d.style.width=pageWidth(p.pt_w,K)+'px'; d.style.aspectRatio=p.pt_w+' / '+p.pt_h;
    setHtml(d,html`<span class="no">${i+1}</span><img loading="lazy" draggable="false" alt="${tl('{page}쪽',{page:i+1})}" src="${pageSrc(p)}">`);
    const w=document.createElement('div'); w.className='pgw'; w.dataset.page=String(i+1); w.appendChild(d); doc.appendChild(w);});
  pageWidthVars(); marks(); vecObserve(); drawZoom();
}
// save=false is auto-fit - never saved. If a width fit for a narrow first window persisted into a wider window, the pages would look too small.
// The scale is never saved in compact (mid/narrow) - so a width fit for a folded screen never overrides the spread/desktop setting.
// The widest page's width stays within ZOOM_MIN-ZOOM_MAX times the fit-width (minimum 160px), widened to hold the print size so
// [100%] is always in reach - also for a page smaller than 160px. Overflow scrolls horizontally only within the PDF area (#left).
const ZOOM_MIN=0.5,ZOOM_MAX=5,ZOOM_STEP=1.2;
// The widest page's width limits [lo, hi] in px, for the fitted width fit and the print-size width actual. Not rounded: a
// rounded limit put the print size a fraction of a pixel out of reach (522pt drawn 697px at [100%]). Pure.
function wBounds(fit,actual){const f=Math.max(160,fit),lo=Math.min(actual,Math.max(160,f*ZOOM_MIN));
  return [lo,Math.max(lo,f*ZOOM_MAX,actual)];}
// The scale that fits the widest page to the PDF area (fitWidth).
function fitK(){return fitWidth()/ptMax();}
// Sets the scale K within wBounds and gives every page box its own width (pageWidth); saved in wide unless save is false
// (saveK). The marks' badges follow the new widths (markBadgeSides), and so do the page verdict lines (sizePv), the save
// chips (placeChips) and [더보기]'s zoom figure (drawZoom).
function setK(k,save){const m=ptMax(),b=wBounds(fitWidth(),m*PT_PX); K=Math.min(b[1],Math.max(b[0],k*m))/m; K_UNBOUND=false;
  sizePages(); markBadgeSides(); sizePv(); placeChips(); if(save!==false&&LAYOUT===LAYOUT_MODE.WIDE)saveK(); vecInvalidate(); drawZoom();}
// Gives every page box its width at the scale K, bounded or not (setK bounds the scale first).
function sizePages(){const m=ptMax(); $$('.pg').forEach(e=>{e.style.width=pageWidth(+e.dataset.ptw||m,K)+'px';}); pageWidthVars();}
// The page widths as the side column of the page verdict panel lays the blocks out (verdict-panel.css): each block's page
// width (--pg-w) and the widest page's (--pg-max, on #doc), so that pages of different widths stand on one axis.
function pageWidthVars(){const m=ptMax(); $('#doc').style.setProperty('--pg-max',pageWidth(m,K)+'px');
  $$('#doc .pgw>.pg').forEach(e=>{/** @type {HTMLElement} */(e.parentElement).style.setProperty('--pg-w',/** @type {HTMLElement} */(e).style.width);});}
// Whether the pages stand at a scale K that no PDF-area width has bounded since their sizes changed (reapplyK). Only the changes
// view brings it about: it hides the PDF area, and a scroller that is not drawn measures 0 wide, so bounding the scale by that
// width cut a 1800px page to the least it allows (816px, the print size of a letter page).
let K_UNBOUND=false;
// Applies K again after the pages' paper sizes changed (a new build with the same page count). A drawn PDF area bounds the
// scale as ever (setK). A hidden one has no width to bound it by: the boxes take their new widths at K as it is, and the bounds
// follow when the area shows again (boundK).
function reapplyK(){if($('#left').getClientRects().length){setK(K,false); return;} sizePages(); K_UNBOUND=true;}
// The PDF area shows again: bounds a scale reapplyK left alone by the width it has now, keeping the reading spot.
function boundK(){if(!K_UNBOUND||!$('#left').getClientRects().length)return; const a=topAnchor(); setK(K,false); restoreAnchor(a);}
// The zoom as [더보기] and the tool bar's zoom button show it: scale k against the print size, in percent, rounded; 100 before
// a scale is known. Pure.
function zoomPct(k){return k>0?Math.round(k/PT_PX*100):100;}
// Writes the zoom figure: [더보기]'s (a live region: it is read out as it changes) and the desktop tool bar's zoom button, which
// shows the zoom now and goes to 100% - pressed (aria-pressed) while the figure is 100%. Its name and tip say both.
function drawZoom(){const t=zoomPct(K)+'%',z=$('#m-zoom'); if(z)z.textContent=t;
  const b=$('#btn-actual'); if(!b)return; const v=b.querySelector('.z'); if(v)v.textContent=t;
  b.setAttribute('aria-pressed',String(t==='100%')); b.setAttribute('aria-label',tl('실제 크기(100%)로 · 지금 {pct}',{pct:t}));
  b.dataset.tip=tl('실제 크기(100%)로: PDF 쪽을 인쇄한 지면 크기로 봅니다 · 지금 {pct}',{pct:t});}
// The saved scale of the document on screen (wide only), or null: a figure document keeps its zoom against the print size
// (pinPrefs.figZoom), since print size is what a figure is checked at; any other document the widest page's width in px
// (pinPrefs.w), as it always has - one value for every LaTeX and view-only document.
// A page width saved before this release (w) was set while reading a manuscript: a figure document never takes it, and opens
// at its own default (openScale) until a zoom is chosen on it.
function savedK(){const p=prefs();
  if(isFigureKind(META.kind))return typeof p.figZoom==='number'&&p.figZoom>0?p.figZoom*PT_PX:null;
  return typeof p.w==='number'&&p.w>0?p.w/ptMax():null;}
function saveK(){if(isFigureKind(META.kind))savePrefs({figZoom:Math.round(K/PT_PX*1e4)/1e4}); else savePrefs({w:pageWidth(ptMax(),K)});}
// The scale a document opens at with nothing saved, for its most common and its widest page width (points) and the fitted
// width fit (px): a figure document at print size when its common page fits the PDF area - a wider outlier scrolls sideways -
// else with the common page fitted; any other document with its widest page fitted - in wide (wide true) at most 900px. Pure.
function openScale(fig,common,widest,fit,wide){return fig?Math.min(PT_PX,fit/common):(wide?Math.min(fit,900):fit)/widest;}
function defaultK(){return openScale(isFigureKind(META.kind),ptCommon(),ptMax(),fitWidth(),LAYOUT===LAYOUT_MODE.WIDE);}
// In compact, whether the scale on screen is one the user chose rather than the one the screen picks (defaultK): only a chosen
// one survives a re-fit (ZOOMED). Pressing [↔] on a figure that opened at print size is a choice; landing back on it is not.
function markZoomed(){if(LAYOUT!==LAYOUT_MODE.WIDE)ZOOMED=Math.abs(K-defaultK())>K*1e-3;}
function innerW(){const L=$('#left'),cs=getComputedStyle(L); return L.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);}
// Fit-width: the scroller's inner width in whole px (innerW: its padding is the gap, which on touch keeps the page off the
// handles' hit areas), on every band. The mouse's #left.clientWidth minus 48px was 12px wider than the room inside its 44px
// and 16px padding, so a fitted page scrolled sideways by 12px.
function fitWidth(){return Math.floor(innerW());}
// compact always takes the screen's scale (defaultK) unless the user chose another (ZOOMED). wide takes it too unless a scale
// is saved. A scroller that is not drawn - the changes view hides it - has no width to fit: fitted to it the pages shrank to
// the smallest width while the changes view was open, and the re-fit on the way back took the reading spot from those small
// pages, so the manuscript came back somewhere else (docs/handbook/viewer.md §변경 보기).
// A scale it leaves alone still meets a new column width: the badges and page numbers are placed again (markBadgeSides).
function autoW(){if(!$('#left').getClientRects().length)return;
  if(LAYOUT!==LAYOUT_MODE.WIDE?!ZOOMED:savedK()===null)setK(defaultK(),false); else markBadgeSides();}
// The page number stands outside a page (.no-out) where a wider page leaves room left of it - a page centred under one at
// least the number's width and 8px wider on each side - and in the page's corner otherwise: on the widest pages, and on every
// page of a document whose pages are all one size, wherever the column puts them (a manuscript looks as it did).
function pageNoSides(){const pgs=$$('#doc .pg'); if(!pgs.length||!pgs[0].getClientRects().length)return;
  const ws=pgs.map(pg=>pg.getBoundingClientRect().width),widest=Math.max(...ws);
  pgs.forEach((pg,i)=>{const no=/** @type {HTMLElement|null} */(pg.querySelector('.no')); if(no)pg.classList.toggle('no-out',(widest-ws[i])/2>=no.offsetWidth+8);});}
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
// [100%]: the print size, around the middle of the PDF area as the zoom buttons.
function actualSize(){zoomTo(PT_PX);}
// Fit width (fitK): keeps the viewed page/position (anchored at the top) and resets horizontal scroll to the start.
function fitW(){const a=topAnchor(),L=$('#left');
  setK(fitK(),LAYOUT===LAYOUT_MODE.WIDE); markZoomed(); restoreAnchor(a); L.scrollLeft=0;}
// Arriving at page n - from the outline, a page field or the page list (goPage) and from a card's [보기] (jumpPin, jumpPv): a
// figure page, one whose map names its figure body (meta figure_top), at its figure (figureTop); any other page at its top.
// The same arrival again while the pages rest on that figure goes to the page's top, and once more to the figure
// (docs/handbook/viewer.md §그림 쪽 도착). Each is a glide (pvGlideTo, pvGlideInto), so the keys wait for it to end.
/** @param {number} n */
function arrivePage(n){const el=document.getElementById('p'+n); if(!el)return; const to=figureTop(n),L=$('#left');
  if(to===null){pvGlideInto(el); return;}
  const top=!pvAutoScrolling()&&Math.abs(L.scrollTop-to)<=FIGURE_REST_PX;
  if(top)pvGlideInto(el); else pvGlideTo(to);
  arrivalWatch(n,!top);}
const FIGURE_ROOM_PT=24;   // of the page kept above an arrived figure at most: its label line ('PL18 · 지금 판') has no element
const FIGURE_REST_PX=2;   // the pages rest on a figure's arrival within this (a glide ends on or next to its pixel)
// A figure page's arrival (its figure, or its top on the press again) lands where it says once the pages rest. The glide's
// place is reckoned at its start, and the layout can still move under it: a save's list reload redraws hundreds of lines and
// stalls the glide past its guard (PV_JUMP lapses after a second), which gives scroll anchoring back, and the anchoring's
// adjustment left the figure 30-300px off (#345). So each time the pages come to rest - after ARRIVAL_REST_MS without a
// scroll, the glide guard down - it measures the place again and glides the rest (pvGlideTo: the guard and the held anchoring
// again), until ARRIVAL_SETTLE_MS after the first rest, at most ARRIVAL_FIXES times. Never once the person has scrolled
// (PV_HAND), on another document, or with the pages not shown; a new arrival replaces it.
const ARRIVAL_REST_MS=120,ARRIVAL_SETTLE_MS=2000,ARRIVAL_FIXES=3;
let ARRIVAL=/** @type {{n:number,figure:boolean,hand:number,doc:string|null,fixes:number,until:number}|null} */(null),ARRIVAL_TIMER=0;
/** @param {number} n @param {boolean} figure */
function arrivalWatch(n,figure){ARRIVAL={n,figure,hand:PV_SCROLL_HAND,doc:DOC,fixes:0,until:0}; arrivalSoon();}
function arrivalSoon(){clearTimeout(ARRIVAL_TIMER); ARRIVAL_TIMER=setTimeout(arrivalSettle,ARRIVAL_REST_MS);}
function arrivalSettle(){const a=ARRIVAL,L=$('#left'),el=a?document.getElementById('p'+a.n):null; if(!a)return;
  if(!el||a.hand!==PV_SCROLL_HAND||a.doc!==DOC||!L.getClientRects().length){ARRIVAL=null; return;}
  if(PV_JUMP!==null||pvAutoScrolling()){arrivalSoon(); return;}   // still on its way
  const now=performance.now(); if(!a.until)a.until=now+ARRIVAL_SETTLE_MS; else if(now>a.until){ARRIVAL=null; return;}
  const to=a.figure?figureTop(a.n):Math.max(0,Math.min(L.scrollHeight-L.clientHeight,L.scrollTop+el.getBoundingClientRect().top-L.getBoundingClientRect().top-L.clientTop));
  if(to===null){ARRIVAL=null; return;}
  if(Math.abs(L.scrollTop-to)>FIGURE_REST_PX){if(a.fixes>=ARRIVAL_FIXES){ARRIVAL=null; return;} a.fixes++; pvGlideTo(to); arrivalSoon();}}
// A scroll while it watches - the glide's own, an anchoring adjustment, a correction - waits for the next rest; a person's
// scroll (PV_HAND) lets it go at that rest.
$('#left').addEventListener('scroll',()=>{if(ARRIVAL)arrivalSoon();},{passive:true});
// #left's scrollTop of page n's figure arrival - its figure's top edge under the free PDF area's top (spotTop) with up to
// FIGURE_ROOM_PT of the page above it, down to the element above (figure_above) or else the page's top, and at least
// OUTLINE_PICK_GAP px - or null for a page without a figure body. In page points, so the room is the label line's at every
// zoom. Room past the page's top would stand the page below the reading line at a large zoom: the line would read the page
// before it.
/** @param {number} n */
function figureTop(n){const pg=document.getElementById('p'+n),m=META&&META.pages?META.pages[n-1]:null;
  if(!pg||!m||typeof m.figure_top!=='number'||!(m.pt_h>0))return null;
  const h=pg.getBoundingClientRect().height,free=(m.figure_top-(typeof m.figure_above==='number'?m.figure_above:0))*h;
  return spotTop(pg,m.figure_top,Math.max(OUTLINE_PICK_GAP,Math.min(FIGURE_ROOM_PT*h/m.pt_h,free)));}
function goPage(v){arrivePage(parseInt(v===undefined?$('#jump').value:v,10));}
$('#jump').addEventListener('keydown',e=>{if(e.key==='Enter')goPage();});
// The page a typed entry v goes to in a document of n pages: a whole number clamped to 1..n; null for an empty or non-number
// entry, which goes nowhere. Pure.
function clampPage(v,n){const s=String(v==null?'':v).trim(); if(!/^-?\d+$/.test(s)||!(n>=1))return null; return Math.min(n,Math.max(1,parseInt(s,10)));}
// The navigation sheet's page field (Enter or [이동]): goes to the clamped page and closes the sheet; nothing typed does nothing.
function navGo(){const p=clampPage($('#ns-page-in').value,META&&META.pages?META.pages.length:0); if(p===null)return;
  $('#nav-sheet').close(); if(document.body.classList.contains('revision-open'))setViewMode(VIEW_MODE.MANUSCRIPT); goPage(p);}
$('#ns-page-in').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault(); navGo();}});

