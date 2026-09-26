// Panel width handle - mouse/touch/pen all share one Pointer Events path (replacing the old desktop-only mousedown
// implementation). The handle has touch-action:none, so dragging it never fights browser scrolling, and
// setPointerCapture keeps tracking it even outside the handle. While dragging, only the width changes (the body's
// page width stays put); relayout runs once on release. Where the drag lands is snapSide(): the width follows, stops at
// the minimum (the handle turns primary), or - past half the minimum - previews a collapse (the panel's contents at 40%,
// a w-resize cursor) that a release carries out; a draft blocks that zone (not-allowed cursor, release = minimum).
// A collapsed wide panel leaves the handle as a 6px rail at the right edge: dragging it left past half the minimum opens
// the panel at the minimum and then follows; a double-click (a tap on touch) opens it at the saved width. A tap on an open
// handle (double-click with a mouse) cycles the presets. Keys follow gripKey() (WAI-ARIA window splitter).
(function(){const g=$('#grip'); let D=null;
  // The drag's cues: the handle turns primary once it stops at the minimum; the collapse preview fades the panel's contents
  // (never #right itself - see §펼친 화면 레이아웃) and the blocked zone shows not-allowed.
  const cue=(zone,rail)=>{const b=document.body; g.classList.toggle('snap-min',!!zone&&zone!=='follow'&&!(rail&&(zone==='collapse'||zone==='blocked')));
    b.classList.toggle('side-snap-collapse',zone==='collapse'&&!rail); b.classList.toggle('side-snap-blocked',zone==='blocked'&&!rail);};
  // A drag from the rail shows the panel without deciding anything yet (the release does).
  const preview=on=>{document.body.classList.toggle('side-open',on);};
  g.addEventListener('pointerdown',e=>{if(LAYOUT==='narrow'||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault(); hideTip(); finishSideSlide();
    D={id:e.pointerId,x:e.clientX,w:SIDE_OPEN?curSideW():0,rail:!SIDE_OPEN,moved:false,mouse:e.pointerType==='mouse',zone:null};
    try{g.setPointerCapture(e.pointerId);}catch(_){}
    g.classList.add('on'); document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(!D||e.pointerId!==D.id)return; const dx=D.x-e.clientX;
    if(!D.moved&&Math.abs(dx)<4)return; D.moved=true;
    const b=sideBounds(LAYOUT,innerWidth),s=snapSide(D.w+dx,b,draftOpen()); D.zone=s.zone;
    if(D.rail)preview(s.zone==='follow'||s.zone==='min');
    showSideW(s.w,b); cue(s.zone,D.rail);});
  // The release: a cancel restores the state before the drag; a tap opens the rail or cycles the presets; a rail drag opens past T;
  // an open drag collapses in the collapse zone and otherwise saves the width (the minimum in the min and blocked zones).
  const end=e=>{if(!D||e.pointerId!==D.id)return; const d=D; D=null; g.classList.remove('on'); document.body.classList.remove('resizing'); cue(null);
    if(e.type==='pointercancel'){applySide(); applySideWidth(); relayout(); return;}   // back to exactly how it was before the drag
    if(!d.moved){if(d.mouse||Date.now()<SWALLOW_CLICK)return;
      if(d.rail)setSide(true,true,true); else cycleSideWidth();
      SWALLOW_CLICK=Date.now()+400;   // the tap moved the panel: the click that follows would land on whatever is under the finger now
      return;}
    if(d.rail){if(d.zone==='collapse'||d.zone==='blocked'){applySide(); applySideWidth(); return;}
      setSide(true,true); setSideWidth(curSideW()); return;}
    if(d.zone==='collapse'){SWALLOW_CLICK=Date.now()+400; setSide(false,true,true); focusSideToggle(); coachSideCollapsed(); return;}
    setSideWidth(curSideW());};
  g.addEventListener('pointerup',end); g.addEventListener('pointercancel',end);
  g.addEventListener('dblclick',()=>{if(SIDE_OPEN)cycleSideWidth(); else setSide(true,true,true);});
  g.addEventListener('keydown',e=>{if(LAYOUT==='narrow')return; const k=gripKey(e.key,curSideW(),sideBounds(LAYOUT,innerWidth),!SIDE_OPEN);
    if(!k)return; e.preventDefault();
    if(k.act==='collapse'||k.act==='open')toggleSide();
    else if(k.act==='cycle')cycleSideWidth();
    else{if(!SIDE_OPEN)setSide(true,true,true); setSideWidth(k.w);}});
})();
// Outline width is independent of the right work panel's handle. While dragging, only the width changes; the PDF position is restored when it ends.
(function(){const g=$('#outline-grip');let D=null;
  g.addEventListener('pointerdown',e=>{if(LAYOUT==='narrow'||document.body.classList.contains('outline-collapsed')||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault();D={id:e.pointerId,x:e.clientX,w:Math.round($('#outline').getBoundingClientRect().width)};
    try{g.setPointerCapture(e.pointerId);}catch(_){}g.classList.add('on');document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(D&&e.pointerId===D.id)showOutlineWidth(D.w+e.clientX-D.x);});
  const end=e=>{if(!D||e.pointerId!==D.id)return;D=null;g.classList.remove('on');document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){applyOutlineState();relayout();}else setOutlineWidth($('#outline').getBoundingClientRect().width);};
  g.addEventListener('pointerup',end);g.addEventListener('pointercancel',end);
  g.addEventListener('keydown',e=>{if(LAYOUT==='narrow')return;const b=outlineBounds(),w=Math.round($('#outline').getBoundingClientRect().width);
    const next={ArrowLeft:w-16,ArrowRight:w+16,Home:b.min,End:b.max}[e.key];
    if(next!==undefined){e.preventDefault();setOutlineWidth(next);}});
})();
// The release speed of a drag from its last 100ms of samples [[t, pos], ...], in px/ms (positive = toward larger pos).
function dragSpeed(pts){if(pts.length<2)return 0; const a=pts[0],b=pts[pts.length-1]; return (b[1]-a[1])/Math.max(1,b[0]-a[0]);}
// Adds one [time, position] sample to a drag, keeping only the last 100ms (dragSpeed's window).
function dragSample(pts,t,pos){pts.push([t,pos]); while(pts.length>2&&t-pts[0][0]>100)pts.shift();}
// Where the phone sheet settles when a drag ends (docs/handbook/viewer.md §패널 폭과 시트 높이). f = the sheet height as a fraction
// of the screen, dy = the whole move (down positive), v = the release speed (px/ms, down positive). Below 25% or a downward fling
// (more than 24px at 0.5px/ms or faster) collapses it - or, while a draft is open, stops it at 30% (a drag never hides a draft);
// an upward fling goes to the next height stop; otherwise it stays where it was let go. Returns {close:true} or {f}.
function sheetRelease(f,dy,v,composing){
  if(f<SHEET_CLOSE_F||(dy>24&&v>=0.5))return composing?{f:SHEET_MIN_F}:{close:true};
  if(dy<-24&&v<=-0.5){const n=SHEET_F.find(x=>x>f+0.02); return {f:n===undefined?1:n};}
  return {f:Math.max(SHEET_MIN_F,Math.min(1,f))};}
// Carries out sheetRelease() for the draft state now: collapse the sheet (remembered) or set its height.
function settleSheet(f,dy,v){const r=sheetRelease(f,dy,v,draftOpen()); if(r.close){applySheet(); setSide(false,true);} else setSheetF(r.f);}
// The height a dragged sheet shows: never below 12% - or 30% while a draft is open, where it will stop anyway.
function dragSheetTo(h){document.documentElement.style.setProperty('--sheet-f',String(Math.max(draftOpen()?SHEET_MIN_F:0.12,h/innerHeight)));}
// Sheet height (narrow): the top-edge handle and the whole tool bar move the sheet. On the handle a drag starts at once (6px); on
// the tool bar a vertical move of more than 8px on a button turns into a sheet drag and swallows that button's click. Dragging
// up opens a collapsed sheet; the release is sheetRelease(). A tap on the handle opens it or cycles the heights, and swallows the
// ghost click that would otherwise land on whatever moved under the finger.
(function(){const g=$('#sheet-grip'),bar=$('#bar1'); let D=null;
  // grab = the drag owns the pointer (capture, cues); down = the handle grabs at once, the tool bar only once the move is vertical
  // (lazy - its buttons keep their taps); end = settle by sheetRelease(), or a handle tap.
  const grab=e=>{try{D.el.setPointerCapture(e.pointerId);}catch(_){} D.el.classList.add('on'); document.body.classList.add('resizing');};
  const down=(e,lazy)=>{if(LAYOUT!=='narrow'||!e.isPrimary||(e.pointerType==='mouse'&&e.button!==0))return;
    if(lazy&&e.target.closest&&e.target.closest('input,textarea,select'))return;
    D={id:e.pointerId,x:e.clientX,y:e.clientY,h:$('#right').getBoundingClientRect().height,moved:false,lazy,el:lazy?bar:g,pts:[]};
    if(!lazy){e.preventDefault(); grab(e);}};
  g.addEventListener('pointerdown',e=>down(e,false));
  bar.addEventListener('pointerdown',e=>down(e,true));
  window.addEventListener('pointermove',e=>{if(!D||e.pointerId!==D.id)return; const dy=D.y-e.clientY;
    if(!D.moved){if(Math.abs(dy)<(D.lazy?8:6))return;
      if(D.lazy&&Math.abs(e.clientX-D.x)>Math.abs(dy)){D=null; return;}
      D.moved=true; if(D.lazy){grab(e); hideTip(); endPress();}}
    dragSample(D.pts,performance.now(),e.clientY);
    if(!SIDE_OPEN&&dy>0)setSide(true);
    if(SIDE_OPEN)dragSheetTo(D.h+dy);});
  const end=e=>{if(!D||e.pointerId!==D.id)return; const d=D; D=null; d.el.classList.remove('on'); document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){if(d.moved)applySheet(); return;}
    if(!d.moved){if(d.lazy||Date.now()<SWALLOW_CLICK)return; if(!SIDE_OPEN)setSide(true,true); else cycleSheet(); SWALLOW_CLICK=Date.now()+400; return;}
    SWALLOW_CLICK=Date.now()+400;   // a drag that started on a tool-bar button never also presses it
    if(!SIDE_OPEN){applySheet(); return;}
    settleSheet($('#right').getBoundingClientRect().height/innerHeight,e.clientY-d.y,dragSpeed(d.pts));};
  window.addEventListener('pointerup',end); window.addEventListener('pointercancel',end);
  g.addEventListener('keydown',e=>{if(LAYOUT!=='narrow')return; const f=sheetF();
    if(e.key==='ArrowUp'){e.preventDefault(); setSheetF(f+0.05);} else if(e.key==='ArrowDown'){e.preventDefault(); setSheetF(f-0.05);}
    else if(e.key==='Enter'||e.key===' '){e.preventDefault(); cycleSheet();}});
})();
// A pull-down that a scroll box at its top hands to its sheet (the phone sheet's content, the documents sheet): touch events,
// because the browser cancels a pointer stream as soon as it starts its own scroll. The first move decides - down, mostly
// vertical, the box at scrollTop 0, not in a text field or a nested scroller - and from then on the move is the sheet's
// (preventDefault). ok(e) filters the touchstart; onMove(dy) follows; onEnd(dy, v) settles (dy null = cancelled; v px/ms, down +).
function pullDown(box,ok,onStart,onMove,onEnd){let P=null;
  box.addEventListener('touchstart',e=>{if(P&&P.on)onEnd(null,0); P=null; const t=e.touches[0];   // a second finger cancels a pull
    if(e.touches.length!==1||!ok(e)||(e.target.closest&&e.target.closest('textarea,input,select,pre,.seg')))return;
    P={x:t.clientX,y:t.clientY,on:false,pts:[]};},{passive:true});
  box.addEventListener('touchmove',e=>{if(!P)return; const t=e.touches[0],dx=t.clientX-P.x,dy=t.clientY-P.y;
    if(!P.on){if(Math.hypot(dx,dy)<8)return;
      if(!(dy>0&&dy>Math.abs(dx)&&box.scrollTop<=0&&e.cancelable)){P=null; return;}
      P.on=true; onStart();}
    e.preventDefault(); dragSample(P.pts,performance.now(),t.clientY); onMove(dy);},{passive:false});
  const end=e=>{if(!P)return; const p=P; P=null; if(!p.on)return;
    onEnd(e.type==='touchcancel'?null:e.changedTouches[0].clientY-p.y,dragSpeed(p.pts));};
  box.addEventListener('touchend',end); box.addEventListener('touchcancel',end);}
// The phone sheet: pulling its content down at the top lowers the sheet (nested scroll hand-off); the release is sheetRelease().
(function(){let h=0;
  pullDown($('#right'),e=>LAYOUT==='narrow'&&SIDE_OPEN&&!e.target.closest('#bar1,#sheet-grip'),
    ()=>{h=$('#right').getBoundingClientRect().height; document.body.classList.add('resizing'); hideTip(); endPress();},
    dy=>dragSheetTo(h-dy),
    (dy,v)=>{document.body.classList.remove('resizing'); if(dy===null){applySheet(); return;}
      SWALLOW_CLICK=Date.now()+400; settleSheet($('#right').getBoundingClientRect().height/innerHeight,dy,v);});
})();
// The documents sheet follows a pull-down and closes on a release past 35% of its height or a flick (dismissOutcome).
(function(){const d=$('#docs-menu');
  pullDown(d,()=>d.open,()=>{},dy=>{d.style.transform='translateY('+Math.max(0,Math.round(dy))+'px)';},
    (dy,v)=>{const close=dy!==null&&dismissOutcome(dy,d.getBoundingClientRect().height,v)==='close'; d.style.transform=''; if(close)d.close();});
})();

// ------------------------------------------------ The overlay panel's swipe (701-900px, touch)
// The overlay panel is dismissed by a rightward swipe (docs/handbook/viewer.md §펼친 화면 레이아웃). swipeAxis() waits for 10px and
// then takes only a mostly horizontal, rightward drag; the panel follows the finger through right (never a transform, which would
// move the fixed tool bar with it), and dismissOutcome() decides the release: slide out (remembered like [핀]) or spring back,
// 0.18s each. A draft only rubber-bands (swipeFollow). Gestures that start in a horizontal scroller (.seg, pre.nowrap), a text field,
// the handle or the tool bar are theirs, and a press held still for 450ms is a text selection. 901-1099px (beside the document) has
// no swipe - only the handle - and outside taps never close the overlay (it is not modal, and a long-press re-pick needs the PDF).
function swipeAxis(dx,dy){if(Math.hypot(dx,dy)<10)return null; return dx>0&&Math.abs(dx)>1.5*Math.abs(dy)?'x':'none';}
// How far the panel follows a rightward drag: the finger itself, or while a draft is open a rubber band (a quarter, at most 24px).
function swipeFollow(dx,composing){dx=Math.max(0,dx); return composing?Math.min(24,dx*0.25):dx;}
// A dismiss gesture's release (the panel swipe, the documents sheet): d = the distance moved toward closing, size = the panel's
// size along it, v = the release speed toward closing in px/ms. Past 35% of the size, or a fling (more than 24px at 0.5px/ms or faster), closes.
function dismissOutcome(d,size,v){return d>=0.35*size||(d>24&&v>=0.5)?'close':'back';}
(function(){const R=$('#right'),SKIP='.seg,pre.nowrap,textarea,input,select,#grip,#bar1'; let S=null;
  // setX moves the panel (and handle) by px through --swipe-x; settle ends a swipe - 'close' slides it out and collapses it
  // (remembered), 'back' springs it back - and always leaves --swipe-x at 0.
  const setX=px=>document.documentElement.style.setProperty('--swipe-x',Math.round(px)+'px');
  const settle=out=>{const b=document.body,ms=MQ_REDUCED.matches?0:SLIDE_MS; b.classList.remove('side-swiping');
    const done=()=>{b.classList.remove('side-settling'); if(out==='close'){setSide(false,true); focusSideToggle();} setX(0);};
    if(!ms){done(); return;} b.classList.add('side-settling'); setX(out==='close'?curSideW():0); setTimeout(done,ms);};
  R.addEventListener('pointerdown',e=>{if(!e.isPrimary){if(S&&S.axis==='x')settle('back'); S=null; return;}   // a second finger ends the swipe
    S=null; if(e.pointerType==='mouse'||!(LAYOUT==='mid'&&MID_OVERLAY&&SIDE_OPEN))return;
    if(e.target.closest&&e.target.closest(SKIP))return;
    S={id:e.pointerId,x:e.clientX,y:e.clientY,t:performance.now(),axis:null,w:0,pts:[]};});
  window.addEventListener('pointermove',e=>{if(!S||e.pointerId!==S.id)return; const dx=e.clientX-S.x,dy=e.clientY-S.y,now=performance.now();
    if(!S.axis){const a=swipeAxis(dx,dy); if(a===null)return;
      if(a!=='x'||now-S.t>=LONGPRESS_MS){S=null; return;}   // a scroll, a leftward drag, or a still press that selects text
      S.axis=a; S.w=curSideW(); document.body.classList.add('side-swiping'); hideTip(); endPress();}
    dragSample(S.pts,now,e.clientX); setX(swipeFollow(dx,draftOpen()));});
  const end=e=>{if(!S||e.pointerId!==S.id)return; const s=S; S=null; if(s.axis!=='x')return;
    if(e.type==='pointercancel'||draftOpen()){settle('back'); return;}
    settle(dismissOutcome(Math.max(0,e.clientX-s.x),s.w,dragSpeed(s.pts)));};
  window.addEventListener('pointerup',end); window.addEventListener('pointercancel',end);
})();

// ------------------------------------------------ The back gesture closes the top layer (touch)
// On a phone or tablet the system back gesture closes the top layer first (docs/handbook/viewer.md §모바일 레이아웃) instead of
// leaving Limn with a draft on screen. While the narrow sheet, the 701-900px overlay panel or the mid outline is open, one
// CloseWatcher stands for it (Chrome on Android routes back there; modal dialogs have their own); without CloseWatcher, one history
// entry does (popstate). Closing the layer any other way removes it again, so back never has a dead press, and document
// switches never add entries (they replace the hash). Mouse devices have no system back, so nothing is registered there.
let BACK=null,BACK_SKIP=false;
// Which layer covers the document: the narrow sheet, the 701-900px overlay panel, or the mid outline overlay ('side'|'outline'|null).
function backLayer(layout,overlay,sideOpen,outlineOpen){if(layout==='narrow')return sideOpen?'side':null;
  if(layout==='mid'){if(outlineOpen)return 'outline'; if(overlay&&sideOpen)return 'side';} return null;}
// Registers or removes the back layer to match the screen (called by applySide and applyOutlineState; idempotent).
function syncBackLayer(){const want=MQ_COARSE.matches&&!!backLayer(LAYOUT,MID_OVERLAY,SIDE_OPEN,OUTLINE_MID_OPEN);
  if(want&&!BACK)armBack(); else if(!want&&BACK)disarmBack();}
// Stands one CloseWatcher for the open layer, or pushes one history entry (same URL) where CloseWatcher is missing.
function armBack(){
  if(window.CloseWatcher){try{const w=new CloseWatcher(); BACK={kind:'watcher',w}; w.onclose=()=>{if(BACK&&BACK.w===w){BACK=null; closeTopLayer();}}; return;}catch(e){}}
  history.pushState({limnLayer:1},'',location.href); BACK={kind:'history'};}
// Removes the layer without closing anything: destroys the watcher, or pops our entry (that popstate is skipped).
function disarmBack(){const b=BACK; BACK=null;
  if(b.kind==='watcher'){b.w.destroy(); return;}
  if(history.state&&history.state.limnLayer){BACK_SKIP=true; history.back();}}
// The back gesture's action: close the mid outline, or collapse the sheet or overlay panel (remembered, with the slide).
function closeTopLayer(){const k=backLayer(LAYOUT,MID_OVERLAY,SIDE_OPEN,OUTLINE_MID_OPEN);
  if(k==='outline')toggleOutline(); else if(k==='side'){setSide(false,true,true); focusSideToggle();}}
window.addEventListener('popstate',()=>{const ours=BACK_SKIP||(BACK&&BACK.kind==='history'); if(!ours)return;
  if(DOC)setHash(DOC);   // the entry below may carry an older #doc= - the document on screen stays
  if(BACK_SKIP){BACK_SKIP=false; return;} BACK=null;
  const d=document.querySelector('dialog[open]'); if(d){d.close(); syncBackLayer(); return;}   // a dialog over the sheet closes first
  closeTopLayer();});

