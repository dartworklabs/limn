// ------------------------------------------------ PDF-area-only zoom - docs/handbook/viewer.md §PDF 영역 전용 확대
// Browser zoom would also enlarge the sidebar and tool bar. Zoom input over the PDF area is intercepted to change only the page width (W).
// - Desktop: Ctrl(Cmd)+wheel over #left. Trackpad pinch also arrives as a wheel event with ctrlKey set, in Chrome/Firefox. Anchored to the pointer.
// - Safari trackpad pinch: gesturestart/gesturechange (e.scale).
// - Keyboard Ctrl(Cmd) + = / + / - / 0 -> zoom in/out/fit width (never intercepted while an input field has focus - see the key handler).
// - Touch: #left has touch-action:pan-x pan-y, so there's no browser pinch. W changes with the ratio of the two-finger distance, and the
//   point under the midpoint of the two fingers follows the fingers (drag while zooming). A page in selection mode has touch-action:none, so it goes through the same path.
function zoomKey(e){const k=e.key,c=e.code;
  if(k==='='||k==='+'||c==='Equal'||c==='NumpadAdd')return 'in';
  if(k==='-'||k==='_'||c==='Minus'||c==='NumpadSubtract')return 'out';
  if(k==='0'||c==='Digit0'||c==='Numpad0')return 'fit';
  return null;}
// The factor for one wheel tick. One mouse-wheel notch (|dy|>=50 pixels or a line unit) gets the same ZOOM_STEP as one button
// press; a trackpad pinch's finely divided dy is composed via exp(-dy/100) - the inverse of the formula Chrome uses to turn
// pinch scale into wheel events, so it grows in proportion to how far the fingers spread. dy is clamped to +-18 so a single
// event never exceeds one button press's worth (ZOOM_STEP ~ exp(0.18)).
function wheelFactor(dy,mode){if(!dy)return 1;
  if(mode===1||mode===2||Math.abs(dy)>=50)return dy<0?ZOOM_STEP:1/ZOOM_STEP;
  return Math.exp(-Math.max(-18,Math.min(18,dy))/100);}
(function(){const L=$('#left'); let acc=1,pt=null,raf=0,G=null,TP=null;
  const flush=()=>{raf=0; if(acc===1)return; const f=acc; acc=1; zoomTo(W*f,pt[0],pt[1]);};
  L.addEventListener('wheel',e=>{if(!(e.ctrlKey||e.metaKey))return; e.preventDefault();
    acc*=wheelFactor(e.deltaY,e.deltaMode); pt=[e.clientX,e.clientY]; if(!raf)raf=requestAnimationFrame(flush);},{passive:false});
  L.addEventListener('gesturestart',e=>{e.preventDefault(); if(!TP)G={w:W};},{passive:false});
  L.addEventListener('gesturechange',e=>{e.preventDefault(); if(G&&!TP&&e.scale>0)zoomTo(G.w*e.scale,e.clientX,e.clientY);},{passive:false});
  L.addEventListener('gestureend',e=>{e.preventDefault(); G=null;},{passive:false});
  const mid=(a,b)=>[(a.clientX+b.clientX)/2,(a.clientY+b.clientY)/2];
  const dist=(a,b)=>Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY)||1;
  let tr=0,last=null;
  const apply=()=>{tr=0; if(!TP||!last)return; const w=TP.w*last.d/TP.d;
    setW(w); if(LAYOUT!=='wide')ZOOMED=true; zoomRestore(TP.a,last.m[0],last.m[1]);};
  L.addEventListener('touchstart',e=>{if(e.touches.length!==2){if(e.touches.length>2)TP=null; return;}
    if(e.cancelable)e.preventDefault();
    const a=e.touches[0],b=e.touches[1],m=mid(a,b); cancelDrag(); cancelLP();
    TP={d:dist(a,b),w:W,a:zoomAnchor(m[0],m[1])}; last={d:TP.d,m};},{passive:false});
  L.addEventListener('touchmove',e=>{if(!TP||e.touches.length!==2)return; if(e.cancelable)e.preventDefault();
    const a=e.touches[0],b=e.touches[1]; last={d:dist(a,b),m:mid(a,b)}; if(!tr)tr=requestAnimationFrame(apply);},{passive:false});
  const end=e=>{if(TP&&e.touches.length<2){if(tr){cancelAnimationFrame(tr); apply();} TP=null; last=null;}};
  L.addEventListener('touchend',end); L.addEventListener('touchcancel',end);
})();

