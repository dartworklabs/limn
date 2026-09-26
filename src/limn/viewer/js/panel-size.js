// ------------------------------------------------ Panel width (P0b-06 + docs/handbook/viewer.md §패널 정리)
// wide/mid adjusts the right panel's width; narrow adjusts the bottom sheet's height. Width is remembered separately
// per screen kind (pinPrefs.side = wide, pinPrefs.sideMid = mid) - so a width fit for a spread-out screen never covers the desktop width.
// If the saved value exceeds the current screen's limit (collapsing/expanding, shrinking the window), the saved value is kept
// and only the visible width is clamped within the limit. The limit: the minimum is the width where the panel's tool bar fits
// on one line, the maximum is the width that leaves the body (PDF) side its minimum width.
function outlineBounds(){if(LAYOUT==='mid')return {min:220,max:320};const max=Math.max(180,Math.min(320,innerWidth-curSideW()-290));return {min:Math.min(220,max),max};}
function showOutlineWidth(w){const b=outlineBounds();w=Math.round(Math.max(b.min,Math.min(b.max,w)));
  document.documentElement.style.setProperty('--outline-width',w+'px');
  const g=$('#outline-grip');g.setAttribute('aria-valuemin',b.min);g.setAttribute('aria-valuemax',b.max);g.setAttribute('aria-valuenow',w);return w;}
// Draws the outline's open/collapsed state and width for the layout (mid keeps its own, unsaved) and syncs the back layer.
function applyOutlineState(){
  const p=prefs(),closed=LAYOUT==='mid'?!OUTLINE_MID_OPEN:p.outlineClosed===true;
  document.body.classList.toggle('outline-collapsed',closed);
  const t=$('#nav-toc-toggle');t.setAttribute('aria-expanded',String(!closed));t.setAttribute('aria-label',closed?'목차 펼치기':'목차 접기');
  if(LAYOUT!=='narrow')showOutlineWidth(typeof p.outlineWidth==='number'?p.outlineWidth:240);
  syncBackLayer();   // the mid outline overlay is a layer the back gesture closes
}
function setOutlineWidth(w){if(LAYOUT==='narrow')return;w=showOutlineWidth(w);savePrefs({outlineWidth:w});relayout();}
function toggleOutline(){const a=topAnchor(),closed=!document.body.classList.contains('outline-collapsed');
  if(LAYOUT==='mid'){OUTLINE_MID_OPEN=!closed;if(!closed)setSide(false);}
  else savePrefs({outlineClosed:closed});
  applyOutlineState();relayout();restoreAnchor(a);$('#nav-toc-toggle').focus({preventScroll:true});}
function sideBounds(layout,iw){const cl=(w,a,b)=>Math.round(Math.min(b,Math.max(a,w)));
  if(layout==='mid'){const min=300,max=iw<=900?Math.min(440,iw-240):Math.max(min,iw-488);
    const def=cl(330,min,max); return {min,max,def,presets:[min,def,cl(iw*0.5,min,max)]};}
  const min=280,max=Math.max(min,Math.min(Math.round(iw*0.8),iw-486)),def=cl(348,min,max);
  return {min,max,def,presets:[cl(300,min,max),def,cl(iw*0.42,min,max)]};}
function clampSide(w,b){return Math.round(Math.min(b.max,Math.max(b.min,w)));}
// Cycles through preset steps: the next step wider than the current width, wrapping to the narrowest if already at the widest. presetIndex is the step within +-4px (or -1 if none matches).
function nextPreset(presets,w){const n=presets.find(p=>p>w+4); return n===undefined?presets[0]:n;}
function presetIndex(presets,w){return presets.findIndex(p=>Math.abs(p-w)<=4);}
// Where a handle drag lands (docs/handbook/viewer.md §패널 폭과 시트 높이). wRaw = the width the pointer asks for: the drag-start
// width plus how far it moved left, unclamped (a drag from the collapsed rail starts at 0). T = half the minimum, rounded down.
// Returns {w: the width to show, zone}: 'follow' at or above the minimum (the width follows, up to the maximum); 'min' from T up
// to the minimum (it stops at the minimum and the handle turns primary); 'collapse' below T (a release collapses the panel);
// 'blocked' there while a draft is open (composing/editing/replying/relocating - it stops at the minimum instead).
function snapSide(wRaw,b,composing){const T=Math.floor(b.min/2);
  if(wRaw>=b.min)return {w:Math.min(b.max,Math.round(wRaw)),zone:'follow'};
  if(wRaw>=T)return {w:b.min,zone:'min'};
  return {w:b.min,zone:composing?'blocked':'collapse'};}
// The handle's keys as a WAI-ARIA window splitter whose primary pane is the panel (aria-valuenow = its width). Open: Enter
// collapses, Space cycles the presets, Home/End go to the minimum/maximum, ←/→ widen/narrow by 16px within the bounds (never
// below the minimum - collapsing is Enter's job). Collapsed: Enter/Space open to the saved width, Home/← open at the minimum,
// End at the maximum; → does nothing. Returns {act:'collapse'|'cycle'|'open'} or {act:'width', w}, or null for any other key.
function gripKey(key,w,b,collapsed){
  if(collapsed){if(key==='Enter'||key===' ')return {act:'open'}; if(key==='Home'||key==='ArrowLeft')return {act:'width',w:b.min};
    return key==='End'?{act:'width',w:b.max}:null;}
  if(key==='Enter')return {act:'collapse'}; if(key===' ')return {act:'cycle'};
  const to={Home:b.min,End:b.max,ArrowLeft:w+16,ArrowRight:w-16}[key];
  return to===undefined?null:{act:'width',w:clampSide(to,b)};}
function sideKey(){return LAYOUT==='mid'?'sideMid':'side';}
function curSideW(){return Math.round($('#right').getBoundingClientRect().width);}
// The width last shown and its bounds - the handle's ARIA value while the panel is open (gripAria).
let SIDE_SHOWN=null;
// Shows a panel width without saving it: #right, --side-w, and the handle's ARIA while the panel is open.
function showSideW(w,b){$('#right').style.width=w+'px'; document.documentElement.style.setProperty('--side-w',w+'px');
  SIDE_SHOWN={w,min:b.min,max:b.max}; if(SIDE_OPEN)gripAria();}
function applySideWidth(){
  if(LAYOUT==='narrow'){$('#right').style.width=''; applySheet(); return;}
  const b=sideBounds(LAYOUT,innerWidth),p=prefs()[sideKey()];
  showSideW(clampSide(typeof p==='number'?p:b.def,b),b);
}
// Sets and remembers the width, then re-fits page width/marks (position is preserved - relayout uses topAnchor/restoreAnchor).
function setSideWidth(w){if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth); w=clampSide(w,b);
  showSideW(w,b); savePrefs({[sideKey()]:w}); relayout(); renderSizeSeg();}
function cycleSideWidth(){if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth); setSideWidth(nextPreset(b.presets,curSideW()));}
// Sheet height is stored as a fraction of screen height (--sheet-f) - CSS shrinks it to fit within the visible height when the keyboard is up.
const SHEET_F=[0.45,0.64,1],SHEET_MIN_F=0.3,SHEET_CLOSE_F=0.25;
function sheetF(){const f=prefs().sheetF; return typeof f==='number'?Math.min(1,Math.max(SHEET_MIN_F,f)):0.64;}
function applySheet(){document.documentElement.style.setProperty('--sheet-f',String(sheetF()));}
function setSheetF(f){f=Math.min(1,Math.max(SHEET_MIN_F,f)); savePrefs({sheetF:Math.round(f*1000)/1000}); applySheet(); if(!SIDE_OPEN)setSide(true); renderSizeSeg();}
function cycleSheet(){const f=sheetF(),i=SHEET_F.findIndex(x=>x>f+0.02); setSheetF(SHEET_F[i<0?0:i]);}
// The '패널 폭' (wide/mid) / '시트 높이' (narrow) segment control inside [⋯].
function renderSizeSeg(){const box=$('#m-size'); if(!box)return; const narrow=LAYOUT==='narrow';
  $('#m-size-l').textContent=narrow?'시트 높이':'패널 폭'; box.setAttribute('aria-label',narrow?'시트 높이':'패널 폭');
  let names,cur;
  if(narrow){names=['낮게','보통','높게']; const f=sheetF(); cur=SHEET_F.findIndex(x=>Math.abs(x-f)<=0.02);}
  else{names=['좁게','보통','넓게']; cur=presetIndex(sideBounds(LAYOUT,innerWidth).presets,curSideW());}
  box.innerHTML=names.map((n,i)=>'<button class="'+(i===cur?'on':'')+'" aria-pressed="'+(i===cur)+'" data-act="size-preset" data-i="'+i+'">'+n+'</button>').join('');}
function sizePreset(i){if(LAYOUT==='narrow'){setSheetF(SHEET_F[i]);return;} setSideWidth(sideBounds(LAYOUT,innerWidth).presets[i]);}
