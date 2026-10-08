// ------------------------------------------------ Drag selection (mouse/touch/pen - one Pointer Events path)
// Mouse: press and drag draws a rectangle, as before. Touch/pen: a drag draws a rectangle only in selection mode
// (SELMODE), and a tap does quick selection; outside selection mode, scroll/pinch zoom work as usual and a
// long-press does quick selection. Only pages get touch-action:none in selection mode (a one-finger drag is
// handled by this code, two fingers by the app zoom - §PDF 영역 전용 확대).
// Coordinates are computed as fractions within the page from clientX/Y and getBoundingClientRect on the same
// basis (the layout viewport), so they stay correct even during a pinch zoom.
let DRAG=/** @type {{pg:HTMLElement,sx:number,sy:number,id:number,mouse:boolean,cx:number,cy:number,box:HTMLElement|null}|null} */(null),
  LP=/** @type {{id:number,pg:HTMLElement,cx:number,cy:number,t:ReturnType<typeof setTimeout>}|null} */(null);
const c01=v=>Math.min(1,Math.max(0,v));
const LONGPRESS_MS=450,TAP_SLOP=8,QUICK_W=0.07,QUICK_H=0.006,QUICK_FIG=0.004;
function fracAt(pg,cx,cy){const r=pg.getBoundingClientRect(); return [c01((cx-r.left)/r.width),c01((cy-r.top)/r.height)];}
function newBox(pg){const b=document.createElement('div'); b.className='sel'; pg.appendChild(b); return b;}
// The pending box's badge - the composer's '새 핀', a re-place's '새 위치': a '+' where a saved mark's number badge goes, outside
// the box's left edge at its top, or in its top-left corner when the page margin has no room (pendingBadgeSide). The old name
// tag sat 21px above the box, over the line above it; the name is now for screen readers only.
function pendingBadge(box,name){setHtml(box,html`<i aria-hidden="true">${ic('plus')}</i><span class="sr-only">${tr(name)}</span>`); pendingBadgeSide(box);}
// Decides a pending box's badge side by the mark rule (markBadgeIn) for its left edge, the page width and the margin now.
function pendingBadgeSide(box){const r=markBadgeRoom(); box.classList.toggle('in',markBadgeIn((parseFloat(box.style.left)||0)/100,W,r.pad,r.reach));}
function drawBox(box,sx,sy,x,y){Object.assign(box.style,{left:Math.min(sx,x)*100+'%',top:Math.min(sy,y)*100+'%',
  width:Math.abs(x-sx)*100+'%',height:Math.abs(y-sy)*100+'%'});}
function cancelDrag(){if(DRAG&&DRAG.box)DRAG.box.remove(); DRAG=null;}
function cancelLP(){if(LP){clearTimeout(LP.t); LP=null;}}
// Prevents the default behavior of a mouse press on a page (focus shift, image dragging), as the old mousedown did - the note field's focus is preserved.
$('#doc').addEventListener('mousedown',e=>{if(e.button===0&&e.target.closest('.pg'))e.preventDefault();});
// A quick selection made by a long-press or a [선택]-mode tap opens the panel or sheet under the finger, and the click that follows
// the touch would land on it (it opened edits, switched the kind, focused the note) - that one click is swallowed (SWALLOW_CLICK).
// LP_PICKED = the pointer whose long-press already picked. TAP/LAST_TAP = double-tap zoom (touch, outside [선택] mode).
let LP_PICKED=/** @type {number|null} */(null),TAP=/** @type {{id:number,x:number,y:number,t:number}|null} */(null),
  LAST_TAP=/** @type {{t:number,x:number,y:number}|null} */(null);
$('#doc').addEventListener('pointerdown',e=>{
  if(e.target.closest('.mark [data-act=mark-jump]'))return;
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
  const off=PRESS_OFF&&PRESS_OFF.id===e.pointerId?PRESS_OFF:null; PRESS_OFF=null;   // this press, if it could be a click-off
  const picked=LP_PICKED===e.pointerId;   // a long press has already picked: its release is no tap
  if(LP&&e.pointerId===LP.id)cancelLP();
  if(picked){LP_PICKED=null; SWALLOW_CLICK=Date.now()+400;}
  let tapped=false,doubled=false;   // touch outside [선택] mode: the press stayed under TAP_SLOP, and a double tap
  if(TAP&&e.pointerId===TAP.id){const tp=TAP,now=performance.now(); TAP=null; tapped=!picked;
    if(now-tp.t<300){const cur={t:now,x:e.clientX,y:e.clientY}; if(isDoubleTap(LAST_TAP,cur)){LAST_TAP=null; doubled=true; clickOffStop(); doubleTapZoom(cur.x,cur.y);} else LAST_TAP=cur;}}
  if(off&&!off.mouse&&tapped&&!doubled)clickOffSoon(off.box);   // a finger's tap waits out the double-tap window first
  if(off&&off.mouse&&!(DRAG&&e.pointerId===DRAG.id)&&Math.hypot(e.clientX-off.x,e.clientY-off.y)<TAP_SLOP)clickOffNow(off.box);   // a press off the pages
  if(!DRAG||e.pointerId!==DRAG.id)return;
  const D=DRAG; DRAG=null;
  if(!D.box){quickPick(D.pg,e.clientX,e.clientY); SWALLOW_CLICK=Date.now()+400; return;}   // a tap in selection mode = quick selection
  const [x,y]=fracAt(D.pg,e.clientX,e.clientY);
  if(!finishRect(D.pg,D.box,D.sx,D.sy,x,y)&&off&&off.mouse)clickOffNow(off.box);});   // too small for a box: a click
window.addEventListener('pointercancel',e=>{if(PRESS_OFF&&PRESS_OFF.id===e.pointerId)PRESS_OFF=null; if(LP&&e.pointerId===LP.id)cancelLP(); if(DRAG&&e.pointerId===DRAG.id)cancelDrag();
  if(TAP&&e.pointerId===TAP.id)TAP=null; if(LP_PICKED===e.pointerId)LP_PICKED=null;});
// ------------------------------------------------ Click-off: a short press outside the selection cancels it
// With a selection open (the dashed box and the composer), a short press on the PDF area outside the box is [취소]/Esc (discardSelection,
// so a typed note keeps its `선택 취소됨 · [되돌리기]`). Short: the mouse moves under a drag (finishRect's size, the one that makes a
// box), the finger under TAP_SLOP and is not a long press (that picks a paragraph). Never a cancel: a press inside the box or its
// badge, on a pin mark, on a control, one that becomes a drag (a new selection) or a pinch, a double tap (app zoom) and - on touch - any
// tap in [선택] mode (a quick selection: it is no TAP, so it never reaches clickOffSoon). A finger's cancel waits CLICKOFF_WAIT_MS, past the 300ms double-tap window (isDoubleTap),
// so the first tap of a double tap does not close the composer under the zoom. PRESS_OFF is the press that may become one (set on
// pointerdown, resolved on pointerup); CLICKOFF_T the finger's wait.
const CLICKOFF_WAIT_MS=350;
let PRESS_OFF=/** @type {{id:number,mouse:boolean,x:number,y:number,box:HTMLElement|null}|null} */(null),CLICKOFF_T=/** @type {ReturnType<typeof setTimeout>|null} */(null);
// Whether the point (x, y) lies in one of rects ({left, top, right, bottom}), each grown by pad px. Pure.
function hitsAny(rects,x,y,pad){return rects.some(r=>x>=r.left-pad&&x<=r.right+pad&&y>=r.top-pad&&y<=r.bottom+pad);}
// A selection is open and nothing above it is the thing to close first - Esc's order: a re-place, a reply, an edit, then the selection.
function selectionOpen(){return !!(COMPOSE.current||!$('#composer').hidden)&&!REPICK&&!REPLY&&!EDITOR.current;}
// Whether the press of pointerdown event e is outside the selection on the PDF area: not on a control or a pin's number badge, not on the
// scrollbar, and not in the box, its badge, its note popover (sel-popover.js, which counts as the box) or a pin mark (their boxes
// ignore the pointer, so the page is what the press lands on).
/** Whether a primary press can cancel the open selection; pin badge buttons, controls and marks never cancel it. */
function pressOutsideSelection(e){const t=/** @type {Element} */(e.target); if(!selectionOpen())return false;
  if(t.closest('.mark [data-act=mark-jump],button,a,input,textarea,select,[data-act],[role=button],#sel-pop'))return false;
  const L=$('#left'); if(t===L&&(e.offsetX>=L.clientWidth||e.offsetY>=L.clientHeight))return false;
  const inside=[...document.querySelectorAll('.mark'),...(COMPOSE.box?[COMPOSE.box,...COMPOSE.box.querySelectorAll('i')]:[]),...(selPopOpen()?[SEL_POP]:[])].map(n=>n.getBoundingClientRect());
  return !hitsAny(inside,e.clientX,e.clientY,0);}
$('#left').addEventListener('pointerdown',e=>{
  PRESS_OFF=e.isPrimary&&pressOutsideSelection(e)
    ?{id:e.pointerId,mouse:e.pointerType==='mouse',x:e.clientX,y:e.clientY,box:COMPOSE.box}:null;});
// Cancels the selection the press began on, if it is still the one open and still the thing to close.
function clickOffNow(box){if(!selectionOpen()||COMPOSE.box!==box)return; discardSelection(); SWALLOW_CLICK=Date.now()+400;}   // the panel may move under the click that follows
function clickOffStop(){if(CLICKOFF_T!==null){clearTimeout(CLICKOFF_T); CLICKOFF_T=null;}}
function clickOffSoon(box){clickOffStop(); CLICKOFF_T=setTimeout(()=>{CLICKOFF_T=null; clickOffNow(box);},CLICKOFF_WAIT_MS);}
// Double-tap on the PDF (touch, outside [선택] mode - the browser's own double-tap zoom is off there): a second tap within 300ms
// and 24px of the first. At fit width it zooms to 2x, from any other width back to fit width - both around the tapped point.
function isDoubleTap(a,b){return !!a&&!!b&&b.t-a.t<=300&&Math.hypot(b.x-a.x,b.y-a.y)<=24;}
// The width a double tap goes to: 2x from fit width (within 5%), fit width from any other width.
function doubleTapWidth(w,fit){return Math.abs(w-fit)<=fit*0.05?fit*2:fit;}
// Zooms around (x, y) to doubleTapWidth(); landing on fit width, compact stops counting as zoomed (it re-fits again).
function doubleTapZoom(x,y){const fit=fitWidth(),w=doubleTapWidth(W,fit); zoomTo(w,x,y); if(w===fit&&LAYOUT!==LAYOUT_MODE.WIDE)ZOOMED=false;}
// Quick selection: calls the existing /api/pick with a small box around the pressed point (quickBox). The server's
// default level is used as-is - 'paragraph' in body text, 'environment' inside a figure/table, the element under the
// point on a figure document - and then widened or narrowed via the range ladder.
function quickPick(pg,cx,cy){const [x,y]=fracAt(pg,cx,cy),b=quickBox(x,y,isFigureKind(META&&META.kind));
  finishRect(pg,newBox(pg),b[0],b[1],b[2],b[3]);}
// The box a quick selection sends around the point (x, y), as page fractions [x0, y0, x1, y1]: about one text line on a
// manuscript page (page width +-7%, height +-0.6%); on a figure a small box of +-0.4% of the page width by +-0.4% of its
// height (a rectangle on a page that is not square), which the map reads as the point - the deepest element holding it
// (docs/handbook/viewer.md §모바일 레이아웃). A line-shaped strip would cross a figure's small elements and resolve to
// an outer one.
function quickBox(x,y,figure){const w=figure?QUICK_FIG:QUICK_W,h=figure?QUICK_FIG:QUICK_H;
  return [c01(x-w),c01(y-h),c01(x+w),c01(y+h)];}
// Turns a drawn rectangle into a selection and asks the server for its lines. Returns false, drawing nothing and removing the
// box, when the rectangle is smaller than a drag (under 0.4% of the page in both directions) - a click, not a selection.
function finishRect(pg,box,sx,sy,x,y){
  const w=Math.abs(x-sx),h=Math.abs(y-sy);
  if(w<0.004&&h<0.004){box.remove();return false;}
  drawBox(box,sx,sy,x,y);
  box.classList.add('pending');
  if(REPICK){ if(REPICK.box)REPICK.box.remove(); REPICK.box=box; pendingBadge(box,'새 위치'); }
  else { if(COMPOSE.box)COMPOSE.box.remove(); COMPOSE.box=box; pendingBadge(box,'새 핀'); }
  const page=+pg.dataset.page,p=META.pages[page-1],repick=!!REPICK;
  pick({page,x0:Math.min(sx,x)*p.pt_w,y0:Math.min(sy,y)*p.pt_h,x1:Math.max(sx,x)*p.pt_w,y1:Math.max(sy,y)*p.pt_h,
    frac:[Math.min(sx,x),Math.min(sy,y),w,h],pdf_build:META.pages_build||undefined,doc:DOC||undefined});
  if(!repick)openSelPop(box);   // a mouse drag's note popover (sel-popover.js); pick() has opened the composer
  return true;}
// If the sheet/panel covers the selection box, the body scrolls up until the box is visible (compact only). The view's top
// is 28px into the PDF area, or 8px under the select mode's bar while it shows, so the box never stays under the bar.
function revealBox(box){if(!box||LAYOUT===LAYOUT_MODE.WIDE||!document.contains(box))return;
  const L=$('#left'),lr=L.getBoundingClientRect(),br=box.getBoundingClientRect(),bar=$('#sel-bar');
  let bottom=lr.bottom; if(LAYOUT===LAYOUT_MODE.NARROW&&SIDE_OPEN)bottom=Math.min(bottom,$('#right').getBoundingClientRect().top);
  const top=Math.max(lr.top+28,bar.getClientRects().length?bar.getBoundingClientRect().bottom+8:0); if(br.top>=top&&br.bottom<=bottom-8)return;
  L.scrollTop+=br.top-top-Math.max(0,(bottom-top-br.height)/3);}
