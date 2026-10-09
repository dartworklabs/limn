// The URL of page image p of the build on screen: /pages/<META.pages_build>/<name>, which the server caches for a year
// because a build's images never change (docs/handbook/api.md). Without a build name, the old /pages/<name>?v=<built_at>.
function pageSrc(p){const b=META.pages_build;
  return dq(b?'/pages/'+encodeURIComponent(b)+'/'+encodeURIComponent(p.name):'/pages/'+encodeURIComponent(p.name)+'?v='+encodeURIComponent(META.built_at));}
function buildDoc(){
  const doc=$('#doc'); doc.replaceChildren(); COMPOSE.box=null;
  META.pages.forEach((p,i)=>{const d=document.createElement('div'); d.className='pg'; d.id='p'+(i+1); d.dataset.page=String(i+1);
    d.style.width=W+'px'; d.style.aspectRatio=p.pt_w+' / '+p.pt_h;
    setHtml(d,html`<span class="no">${i+1}</span><img loading="lazy" draggable="false" alt="${tl('{page}쪽',{page:i+1})}" src="${pageSrc(p)}">`);
    doc.appendChild(d);});
  marks(); vecObserve();
}
// save=false is auto-fit - never saved. If a width fit for a narrow first window persisted into a wider window, the pages would look too small.
// Width is never saved in compact (mid/narrow) - so a width fit for a folded screen never overrides the spread/desktop setting.
// The page width limit is ZOOM_MIN-ZOOM_MAX times the fit-width (minimum 160px). Overflow scrolls horizontally only within the PDF area (#left).
const ZOOM_MIN=0.5,ZOOM_MAX=5,ZOOM_STEP=1.2;
function wBounds(fit){const f=Math.max(160,fit),lo=Math.max(160,Math.round(f*ZOOM_MIN)); return [lo,Math.max(lo,Math.round(f*ZOOM_MAX))];}
// Sets the page width W within wBounds (saved in wide unless save is false); the marks' badges follow the new width (markBadgeSides)
// and so does [더보기]'s zoom figure (drawZoom).
function setW(w,save){const b=wBounds(fitWidth()); W=Math.round(Math.min(b[1],Math.max(b[0],w))); $$('.pg').forEach(e=>e.style.width=W+'px');
  markBadgeSides(); if(save!==false&&LAYOUT===LAYOUT_MODE.WIDE)savePrefs({w:W}); vecInvalidate(); drawZoom();}
// The zoom as [더보기] shows it: the page width W over the fitted width, in percent, rounded; 100 before a width is known. Pure.
function zoomPct(w,fit){return fit>0?Math.round(w/fit*100):100;}
// Writes [더보기]'s zoom figure (a live region: it is read out as it changes).
function drawZoom(){const z=$('#m-zoom'); if(z)z.textContent=zoomPct(W,fitWidth())+'%';}
function innerW(){const L=$('#left'),cs=getComputedStyle(L); return L.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);}
// Fit-width: in compact and on a wide touch screen, the scroller's inner width (innerW: its padding is the gap, which on touch keeps
// the page off the handles' hit areas); with a mouse in wide, #left.clientWidth minus 48px (left/right margins), as always.
function fitWidth(){return LAYOUT!==LAYOUT_MODE.WIDE||MQ_COARSE.matches?innerW():$('#left').clientWidth-48;}
// compact always fits the screen width (unless the user pressed -/+, in which case it stays fixed for that layout). wide fits the
// padded width up to 900px unless a width is saved. A scroller that is not drawn - the changes view hides it - has no width to
// fit: fitted to it the pages shrank to the smallest width while the changes view was open, and the re-fit on the way back
// took the reading spot from those small pages, so the manuscript came back somewhere else (docs/handbook/viewer.md §변경 보기).
function autoW(){if(!$('#left').getClientRects().length)return;
  if(LAYOUT!==LAYOUT_MODE.WIDE){if(!ZOOMED)setW(innerW(),false);return;}
  if(prefs().w!==undefined)return; const f=innerW(); setW(f<900?f:900,false);}   // innerW = width - 44 - 16 with a mouse
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
function zoomTo(w,cx,cy){const a=zoomAnchor(cx,cy); setW(w); if(LAYOUT!==LAYOUT_MODE.WIDE)ZOOMED=true; zoomRestore(a);}
function zoom(k){zoomTo(W*Math.pow(ZOOM_STEP,k));}
// Fit width (fitWidth): keeps the viewed page/position (anchored at the top) and resets horizontal scroll to the start.
function fitW(){const a=topAnchor(),L=$('#left');
  if(LAYOUT!==LAYOUT_MODE.WIDE){ZOOMED=false; setW(innerW(),false);} else setW(fitWidth());
  restoreAnchor(a); L.scrollLeft=0;}
function goPage(v){const el=document.getElementById('p'+parseInt(v===undefined?$('#jump').value:v,10)); if(el) el.scrollIntoView({behavior:SMOOTH});}
$('#jump').addEventListener('keydown',e=>{if(e.key==='Enter')goPage();});
// The page a typed entry v goes to in a document of n pages: a whole number clamped to 1..n; null for an empty or non-number
// entry, which goes nowhere. Pure.
function clampPage(v,n){const s=String(v==null?'':v).trim(); if(!/^-?\d+$/.test(s)||!(n>=1))return null; return Math.min(n,Math.max(1,parseInt(s,10)));}
// The navigation sheet's page field (Enter or [이동]): goes to the clamped page and closes the sheet; nothing typed does nothing.
function navGo(){const p=clampPage($('#ns-page-in').value,META&&META.pages?META.pages.length:0); if(p===null)return;
  $('#nav-sheet').close(); if(document.body.classList.contains('revision-open'))setViewMode(VIEW_MODE.MANUSCRIPT); goPage(p);}
$('#ns-page-in').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault(); navGo();}});

