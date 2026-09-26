function pageSrc(p){return dq('/pages/'+encodeURIComponent(p.name)+'?v='+encodeURIComponent(META.built_at));}
function buildDoc(){
  const doc=$('#doc'); doc.innerHTML=''; PENDING=null;
  META.pages.forEach((p,i)=>{const d=document.createElement('div'); d.className='pg'; d.id='p'+(i+1); d.dataset.page=i+1;
    d.style.width=W+'px'; d.style.aspectRatio=p.pt_w+' / '+p.pt_h;
    d.innerHTML='<span class="no">'+(i+1)+'</span><img loading="lazy" draggable="false" alt="'+esc(tl('{page}쪽',{page:i+1}))+'" src="'+esc(pageSrc(p))+'">';
    doc.appendChild(d);});
  marks(); vecObserve();
}
// save=false is auto-fit - never saved. If a width fit for a narrow first window persisted into a wider window, the pages would look too small.
// Width is never saved in compact (mid/narrow) - so a width fit for a folded screen never overrides the spread/desktop setting.
// The page width limit is ZOOM_MIN-ZOOM_MAX times the fit-width (minimum 160px). Overflow scrolls horizontally only within the PDF area (#left).
const ZOOM_MIN=0.5,ZOOM_MAX=5,ZOOM_STEP=1.2;
function wBounds(fit){const f=Math.max(160,fit),lo=Math.max(160,Math.round(f*ZOOM_MIN)); return [lo,Math.max(lo,Math.round(f*ZOOM_MAX))];}
function setW(w,save){const b=wBounds(fitWidth()); W=Math.round(Math.min(b[1],Math.max(b[0],w))); $$('.pg').forEach(e=>e.style.width=W+'px');
  if(save!==false&&LAYOUT==='wide')savePrefs({w:W}); vecInvalidate();}
function innerW(){const L=$('#left'),cs=getComputedStyle(L); return L.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);}
// Fit-width: in compact, the body's inner width; in wide, #left.clientWidth minus 48px (left/right margins).
function fitWidth(){return LAYOUT!=='wide'?innerW():$('#left').clientWidth-48;}
// compact always fits the screen width (unless the user pressed -/+, in which case it stays fixed for that layout). wide behaves as before.
function autoW(){if(LAYOUT!=='wide'){if(!ZOOMED)setW(innerW(),false);return;}
  if(prefs().w!==undefined)return; const f=$('#left').clientWidth-44-16; setW(f<900?f:900,false);}
// Zoom anchor: the page under screen coordinates (cx,cy) and its fraction within that page. If the point falls in the gap between pages, the vertically nearest page is used.
// Without coordinates, the center of the PDF area is used (keyboard/button).
function zoomAnchor(cx,cy){const L=$('#left'),lr=L.getBoundingClientRect();
  if(cx==null){cx=lr.left+L.clientWidth/2; cy=lr.top+L.clientHeight/2;}
  let best=null,bd=Infinity;
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(),d=cy<r.top?r.top-cy:(cy>r.bottom?cy-r.bottom:0);
    if(d<bd){bd=d; best={pg,r};} if(d===0)break;}
  return best?{pg:best.pg,cx,cy,fx:(cx-best.r.left)/best.r.width,fy:(cy-best.r.top)/best.r.height}:null;}
// Restores the anchor's in-page fractional position back to screen coordinates (cx,cy) - so the text under the pointer stays put even after zooming.
function zoomRestore(a,cx,cy){if(!a)return; const L=$('#left'),r=a.pg.getBoundingClientRect();
  L.scrollLeft+=r.left+a.fx*r.width-(cx==null?a.cx:cx); L.scrollTop+=r.top+a.fy*r.height-(cy==null?a.cy:cy);}
function zoomTo(w,cx,cy){const a=zoomAnchor(cx,cy); setW(w); if(LAYOUT!=='wide')ZOOMED=true; zoomRestore(a);}
function zoom(k){zoomTo(W*Math.pow(ZOOM_STEP,k));}
// Fit width: keeps the viewed page/position (anchored at the top) and resets horizontal scroll to the start.
function fitW(){const a=topAnchor(),L=$('#left');
  if(LAYOUT!=='wide'){ZOOMED=false; setW(innerW(),false);} else setW(L.clientWidth-48);
  restoreAnchor(a); L.scrollLeft=0;}
function goPage(v){const el=document.getElementById('p'+parseInt(v===undefined?$('#jump').value:v,10)); if(el) el.scrollIntoView({behavior:SMOOTH});}
$('#jump').addEventListener('keydown',e=>{if(e.key==='Enter')goPage();});
$('#m-jump').addEventListener('keydown',e=>{if(e.key==='Enter'){$('#more').close(); goPage($('#m-jump').value);}});

