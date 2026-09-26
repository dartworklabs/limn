// ------------------------------------------------ Drag selection (mouse/touch/pen - one Pointer Events path)
// Mouse: press and drag draws a rectangle, as before. Touch/pen: a drag draws a rectangle only in selection mode
// (SELMODE), and a tap does quick selection; outside selection mode, scroll/pinch zoom work as usual and a
// long-press does quick selection. Only pages get touch-action:none in selection mode (a one-finger drag is
// handled by this code, two fingers by the app zoom - §PDF 영역 전용 확대).
// Coordinates are computed as fractions within the page from clientX/Y and getBoundingClientRect on the same
// basis (the layout viewport), so they stay correct even during a pinch zoom.
let DRAG=null,LP=null;
const c01=v=>Math.min(1,Math.max(0,v));
const LONGPRESS_MS=450,TAP_SLOP=8,QUICK_W=0.07,QUICK_H=0.006;
function fracAt(pg,cx,cy){const r=pg.getBoundingClientRect(); return [c01((cx-r.left)/r.width),c01((cy-r.top)/r.height)];}
function newBox(pg){const b=document.createElement('div'); b.className='sel'; pg.appendChild(b); return b;}
function drawBox(box,sx,sy,x,y){Object.assign(box.style,{left:Math.min(sx,x)*100+'%',top:Math.min(sy,y)*100+'%',
  width:Math.abs(x-sx)*100+'%',height:Math.abs(y-sy)*100+'%'});}
function cancelDrag(){if(DRAG&&DRAG.box)DRAG.box.remove(); DRAG=null;}
function cancelLP(){if(LP){clearTimeout(LP.t); LP=null;}}
// Prevents the default behavior of a mouse press on a page (focus shift, image dragging), as the old mousedown did - the note field's focus is preserved.
$('#doc').addEventListener('mousedown',e=>{if(e.button===0&&e.target.closest('.pg'))e.preventDefault();});
// A quick selection made by a long-press or a [선택]-mode tap opens the panel or sheet under the finger, and the click that follows
// the touch would land on it (it opened edits, switched the kind, focused the note) - that one click is swallowed (SWALLOW_CLICK).
// LP_PICKED = the pointer whose long-press already picked. TAP/LAST_TAP = double-tap zoom (touch, outside [선택] mode).
let LP_PICKED=null,TAP=null,LAST_TAP=null;
$('#doc').addEventListener('pointerdown',e=>{
  if(e.target.closest('.mark b'))return;
  if(!e.isPrimary){cancelDrag(); cancelLP(); TAP=null; LAST_TAP=null; return;}   // a second finger = a pinch - the box being drawn is discarded
  const pg=e.target.closest('.pg'); if(!pg)return;
  const mouse=e.pointerType==='mouse';
  if(mouse&&e.button!==0)return;
  if(mouse||SELMODE){const [sx,sy]=fracAt(pg,e.clientX,e.clientY);
    DRAG={pg,sx,sy,id:e.pointerId,mouse,cx:e.clientX,cy:e.clientY,box:mouse?newBox(pg):null};
    if(!mouse){try{pg.setPointerCapture(e.pointerId);}catch(_){}}
    return;}
  cancelLP(); TAP={id:e.pointerId,x:e.clientX,y:e.clientY,t:performance.now()};
  LP={id:e.pointerId,pg,cx:e.clientX,cy:e.clientY,t:setTimeout(()=>{const L=LP; LP=null; if(L){LP_PICKED=L.id; quickPick(L.pg,L.cx,L.cy);}},LONGPRESS_MS)};
});
window.addEventListener('pointermove',e=>{
  if(LP&&e.pointerId===LP.id&&Math.hypot(e.clientX-LP.cx,e.clientY-LP.cy)>10)cancelLP();
  if(TAP&&e.pointerId===TAP.id&&Math.hypot(e.clientX-TAP.x,e.clientY-TAP.y)>TAP_SLOP)TAP=null;
  if(!DRAG||e.pointerId!==DRAG.id)return;
  if(!DRAG.box){if(Math.hypot(e.clientX-DRAG.cx,e.clientY-DRAG.cy)<TAP_SLOP)return; DRAG.box=newBox(DRAG.pg);}
  const [x,y]=fracAt(DRAG.pg,e.clientX,e.clientY); drawBox(DRAG.box,DRAG.sx,DRAG.sy,x,y);});
window.addEventListener('pointerup',e=>{
  if(LP&&e.pointerId===LP.id)cancelLP();
  if(LP_PICKED===e.pointerId){LP_PICKED=null; SWALLOW_CLICK=Date.now()+400;}
  if(TAP&&e.pointerId===TAP.id){const tp=TAP,now=performance.now(); TAP=null;
    if(now-tp.t<300){const cur={t:now,x:e.clientX,y:e.clientY}; if(isDoubleTap(LAST_TAP,cur)){LAST_TAP=null; doubleTapZoom(cur.x,cur.y);} else LAST_TAP=cur;}}
  if(!DRAG||e.pointerId!==DRAG.id)return;
  const D=DRAG; DRAG=null;
  if(!D.box){quickPick(D.pg,e.clientX,e.clientY); SWALLOW_CLICK=Date.now()+400; return;}   // a tap in selection mode = quick selection
  const [x,y]=fracAt(D.pg,e.clientX,e.clientY); finishRect(D.pg,D.box,D.sx,D.sy,x,y);});
window.addEventListener('pointercancel',e=>{if(LP&&e.pointerId===LP.id)cancelLP(); if(DRAG&&e.pointerId===DRAG.id)cancelDrag();
  if(TAP&&e.pointerId===TAP.id)TAP=null; if(LP_PICKED===e.pointerId)LP_PICKED=null;});
// Double-tap on the PDF (touch, outside [선택] mode - the browser's own double-tap zoom is off there): a second tap within 300ms
// and 24px of the first. At fit width it zooms to 2x, from any other width back to fit width - both around the tapped point.
function isDoubleTap(a,b){return !!a&&!!b&&b.t-a.t<=300&&Math.hypot(b.x-a.x,b.y-a.y)<=24;}
// The width a double tap goes to: 2x from fit width (within 5%), fit width from any other width.
function doubleTapWidth(w,fit){return Math.abs(w-fit)<=fit*0.05?fit*2:fit;}
// Zooms around (x, y) to doubleTapWidth(); landing on fit width, compact stops counting as zoomed (it re-fits again).
function doubleTapZoom(x,y){const fit=fitWidth(),w=doubleTapWidth(W,fit); zoomTo(w,x,y); if(w===fit&&LAYOUT!=='wide')ZOOMED=false;}
// Quick selection: calls the existing /api/pick with a small box around the pressed point (page width +-7%, height
// +-0.6% ~ one line). The server's default level is used as-is - 'paragraph' in body text, 'environment' inside a
// figure/table - and then widened or narrowed via the range ladder.
function quickPick(pg,cx,cy){const [x,y]=fracAt(pg,cx,cy);
  finishRect(pg,newBox(pg),c01(x-QUICK_W),c01(y-QUICK_H),c01(x+QUICK_W),c01(y+QUICK_H));}
function finishRect(pg,box,sx,sy,x,y){
  const w=Math.abs(x-sx),h=Math.abs(y-sy);
  if(w<0.004&&h<0.004){box.remove();return;}
  drawBox(box,sx,sy,x,y);
  box.classList.add('pending');
  if(REPICK){ if(REPICK.box)REPICK.box.remove(); REPICK.box=box; box.innerHTML='<i>새 위치</i>'; }
  else { if(PENDING)PENDING.remove(); PENDING=box; box.innerHTML='<i>새 핀</i>'; }
  const page=+pg.dataset.page,p=META.pages[page-1];
  pick({page,x0:Math.min(sx,x)*p.pt_w,y0:Math.min(sy,y)*p.pt_h,x1:Math.max(sx,x)*p.pt_w,y1:Math.max(sy,y)*p.pt_h,
    frac:[Math.min(sx,x),Math.min(sy,y),w,h],pdf_build:META.pages_build||undefined,doc:DOC||undefined});}
// If the sheet/panel covers the selection box, the body scrolls up until the box is visible (compact only).
function revealBox(box){if(!box||LAYOUT==='wide'||!document.contains(box))return;
  const L=$('#left'),lr=L.getBoundingClientRect(),br=box.getBoundingClientRect();
  let bottom=lr.bottom; if(LAYOUT==='narrow'&&SIDE_OPEN)bottom=Math.min(bottom,$('#right').getBoundingClientRect().top);
  const top=lr.top+28; if(br.top>=top&&br.bottom<=bottom-8)return;
  L.scrollTop+=br.top-top-Math.max(0,(bottom-top-br.height)/3);}

