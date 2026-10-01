// ------------------------------------------------ Layout bands (docs/handbook/viewer.md §모바일 레이아웃)
// The window's width, height and primary pointer pick a band (layoutFor), and the band a layout mode (BAND_MODE): wide - a right
// sidebar (width-adjustable); mid - the panel between the nav bar and the action row (an overlay up to 900px, else beside the
// document; the short band of a landscape phone folds both rows into one top row); narrow - a bottom sheet, collapsed by
// default. If the band changes partway through a collapse/expand or a rotation, the page width is re-fit while preserving the
// viewed position (topAnchor). Marks and the selection box are % coordinates within the page, so they fall back into place
// automatically once the page width is fit.
// The band for a w x h CSS px window whose primary pointer is coarse (touch) or not. Pure. A mouse reads the width only:
// phone up to 700px, the overlay panel up to 900px, the side panel up to 1099px, wide from 1100px. Touch reads the height too:
// under 600px wide is a phone at any height, then under 480px high is the short band (a landscape phone); a touch tablet up to
// 1366px wide keeps the side panel (mid-side), so only a touch screen wider than that is the desktop.
function layoutFor(w,h,coarse){
  if(!coarse){if(w<=700)return LAYOUT_BAND.PHONE; if(w<=900)return LAYOUT_BAND.MID_OVERLAY; if(w<=1099)return LAYOUT_BAND.MID_SIDE; return LAYOUT_BAND.WIDE;}
  if(w<600)return LAYOUT_BAND.PHONE; if(h<480)return LAYOUT_BAND.SHORT;
  if(w<=700)return LAYOUT_BAND.PHONE; if(w<=900)return LAYOUT_BAND.MID_OVERLAY; if(w<=1366)return LAYOUT_BAND.MID_SIDE; return LAYOUT_BAND.WIDE;}
// What layoutFor reads from the window now: {w, h, coarse}.
function bandInput(){return {w:innerWidth,h:innerHeight,coarse:MQ_COARSE.matches};}
// Picks the band for the window and its panel state: the body classes (lay-*, band-*, mid-overlay, compact), then wide follows the
// per-device pinPrefs.sideClosed (open by default), mid its midClosed (else open beside the document, collapsed as an overlay),
// narrow starts collapsed. An open draft keeps it open. Returns whether the band or its overlay changed.
function applyLayout(){const o=bandInput(),band=layoutFor(o.w,o.h,o.coarse),L=BAND_MODE[band],overlay=L===LAYOUT_MODE.MID&&o.w<=900;
  if(band===BAND&&overlay===MID_OVERLAY)return false;
  BAND=band; LAYOUT=L; MID_OVERLAY=overlay; OUTLINE_MID_OPEN=false; const b=document.body,p=prefs(); ZOOMED=false; endSideSlide();
  Object.values(LAYOUT_MODE).forEach(k=>b.classList.toggle('lay-'+k,k===L)); Object.values(LAYOUT_BAND).forEach(k=>b.classList.toggle('band-'+k,k===band));
  b.classList.toggle('mid-overlay',overlay); b.classList.toggle('compact',L!==LAYOUT_MODE.WIDE);
  SIDE_OPEN=L===LAYOUT_MODE.WIDE?p.sideClosed!==true:(L===LAYOUT_MODE.MID?(typeof p.midClosed==='boolean'?!p.midClosed:!overlay):false);
  if(!REPICK&&(COMPOSE.current||EDITOR.current||REPLY||!$('#composer').hidden))SIDE_OPEN=true;   // an in-progress note/edit/reply is never left hidden collapsed
  applySide(); stickTop(); return true;}
// A draft the panel is holding: the composer (a selection being noted), an open edit or reply, or a relocation. Collapsing by a
// drag stops short of it, a swipe only rubber-bands, and a collapsed [핀 N] shows a dot for it.
function draftOpen(){return !$('#composer').hidden||!!EDITOR.current||!!REPLY||!!REPICK;}
// Draws the panel state (docs/handbook/viewer.md §패널 폭과 시트 높이): the body classes (with the phone sheet's composing lift), both [핀 N] toggles - the tool bar's and,
// for a collapsed wide panel, the nav bar's - with the open count, the draft dot and the arrow, the handle's ARIA and the back-gesture
// layer. Idempotent and cheap: drawPins() calls it on every redraw. The panel keeps its open layout while it slides out.
function applySide(){const open=SIDE_OPEN,b=document.body,dot=!open&&draftOpen(),n=PINS.length,composing=!$('#composer').hidden;
  b.classList.toggle('side-open',open||!!(SIDE_SLIDE&&SIDE_SLIDE.kind==='closing')); b.classList.toggle('composing',composing);
  if(!composing)SHEET_KEPT=false; b.classList.toggle('sheet-up',composing&&!SHEET_KEPT&&LAYOUT===LAYOUT_MODE.NARROW);   // the phone sheet's composing lift (panel-size.js)
  const label=tr(open?'패널 접기':'패널 펴기')+' · '+tl('열린 핀 {n}',{n})+(dot?' · '+tr('작성 중'):'');
  for(const t of [$('#btn-side'),$('#nav-side')]){t.setAttribute('aria-expanded',String(open)); t.setAttribute('aria-label',label);
    t.querySelector('.side-n').textContent=n; t.querySelector('.c-dot').hidden=!dot;}
  $('#nav-side').hidden=!(LAYOUT===LAYOUT_MODE.WIDE&&!open);
  $('#side-arrow').innerHTML=ic(LAYOUT===LAYOUT_MODE.NARROW?(open?'chevron-down':'chevron-up'):(open?'chevron-right':'chevron-left'));
  gripAria(); updateReviewCount(); syncBackLayer();}
const GRIP_TIP=$('#grip').dataset.tip;   // the open handle's hint (the markup's, translated by tr())
// The handle's ARIA as a window splitter: the panel width, or 0 (named '패널 폭 · 접힘') while collapsed - a collapsed wide panel's
// handle is the rail at the right edge, and its hint says how to bring the panel back.
function gripAria(){const g=$('#grip'),s=SIDE_SHOWN;
  if(!SIDE_OPEN){g.setAttribute('aria-valuenow','0'); g.setAttribute('aria-valuemin','0'); g.setAttribute('aria-label',tr('패널 폭')+' · '+tr('접힘'));
    g.dataset.tip=tr('끌어서 핀 패널을 폅니다. 두 번 클릭(터치는 탭)하거나 Enter 를 누르면 전에 쓰던 폭으로 폅니다'); return;}
  g.setAttribute('aria-label',tr('패널 폭')); g.dataset.tip=tr(GRIP_TIP);
  if(s){g.setAttribute('aria-valuenow',s.w); g.setAttribute('aria-valuemin',s.min); g.setAttribute('aria-valuemax',s.max);}}
// Opens or collapses the pin panel in every layout (the wide side panel, the mid side or overlay panel, the narrow sheet).
// remember = the user did it (a toggle, Ctrl+\, a handle drag or key, a swipe): wide keeps it per device in pinPrefs.sideClosed,
// mid in midClosed; narrow always starts collapsed. slide = move with the 0.18s slide where the layout has one (wide, and the
// 701-900px overlay, whose opening slide is CSS's own); things that merely need the panel (a pick, a link) open it at once.
// Opening the mid panel closes the mid outline (one overlay at a time). Collapsing never touches the saved width - once
// collapsed, the panel's width is put back to it for the next opening.
function setSide(open,remember,slide){open=!!open;
  if(open&&LAYOUT===LAYOUT_MODE.MID){OUTLINE_MID_OPEN=false;applyOutlineState();}
  if(remember&&LAYOUT===LAYOUT_MODE.MID)savePrefs({midClosed:!open});
  if(remember&&LAYOUT===LAYOUT_MODE.WIDE)savePrefs({sideClosed:!open});
  if(SIDE_OPEN===open)return; SIDE_OPEN=open; const cut=!!SIDE_SLIDE&&SIDE_SLIDE.kind==='closing'; endSideSlide();
  if(open)document.documentElement.style.setProperty('--swipe-x','0px');   // never reopen an overlay still offset by a swipe
  const ms=slideMs(); if(ms&&slide)startSideSlide(open?'opening':'closing',ms);
  applySide(); hideTip(); if((!open&&!SIDE_SLIDE)||(open&&cut))applySideWidth();}   // reopened mid-slide: back from a drag's minimum to the saved width
// The panel's slide (0.18s; none with reduced motion, and none beside the document at 901-1099px, where the page re-fits instead).
// While it slides out the body keeps side-open, so the layout does not jump until it is gone.
const SLIDE_MS=180; let SIDE_SLIDE=null;
// The slide's length for this layout in ms: 0 with reduced motion, beside the document (901-1099px) and for the narrow sheet.
function slideMs(){return MQ_REDUCED.matches||!(LAYOUT===LAYOUT_MODE.WIDE||MID_OVERLAY)?0:SLIDE_MS;}
// Starts the 'opening'/'closing' slide; when it ends the panel settles (a collapsed one gets its saved width back).
function startSideSlide(kind,ms){document.body.classList.add('side-'+kind); SIDE_SLIDE={kind,t:setTimeout(finishSideSlide,ms)};}
// Ends a running slide now and settles the panel as the slide's end would (a collapsed one gets its saved width back) - a handle
// pressed mid-slide starts from the settled state, not from a half-slid one.
function finishSideSlide(){if(!SIDE_SLIDE)return; endSideSlide(); applySide(); if(!SIDE_OPEN)applySideWidth();}
// Stops a running slide at once without settling anything - the caller re-applies the panel (setSide, applyLayout); a handle
// drag uses finishSideSlide() instead.
function endSideSlide(){if(!SIDE_SLIDE)return; clearTimeout(SIDE_SLIDE.t); SIDE_SLIDE=null; document.body.classList.remove('side-closing','side-opening');}
// After a collapse, a focus left inside the hidden panel (or on the mid handle, which hides with it) moves to the [핀 N] that
// reopens it. Compact keeps its tool bar and status chips visible, so a focus there stays.
function focusSideToggle(){const a=document.activeElement; if(SIDE_OPEN||!a)return;
  const hidden=(a===$('#grip')&&LAYOUT!==LAYOUT_MODE.WIDE)||($('#right').contains(a)&&!$('#bar2').contains(a)&&!(LAYOUT!==LAYOUT_MODE.WIDE&&$('#bar1').contains(a)));
  if(hidden)(LAYOUT===LAYOUT_MODE.WIDE?$('#nav-side'):$('#btn-side')).focus({preventScroll:true});}
// [핀 N], Ctrl/⌘+\ and the handle's Enter: collapse with the slide, or open. Collapsing moves a focus out of the hidden panel;
// opening from the nav bar's [핀 N] (which hides as the panel opens) moves the focus to the handle beside the panel.
function toggleSide(){const open=!SIDE_OPEN,a=document.activeElement; setSide(open,true,true);
  if(!open)focusSideToggle(); else if(a===$('#nav-side'))$('#grip').focus({preventScroll:true});}
// The first drag-collapse on a wide screen says once how to bring the panel back (it leaves only a 6px rail behind).
function coachSideCollapsed(){if(LAYOUT===LAYOUT_MODE.WIDE&&!SIDE_OPEN)coach('side','핀 패널은 오른쪽 위 [핀 N] 또는 Ctrl+\\ 로 다시 엽니다');}
// Re-fits everything to the window: the layout (a changed one redraws the cards, whose action row is ordered per layout), the panel
// and outline widths, the page width at the same reading spot, the composer, the stuck heads and the section strip - and keeps a
// panel text field that has focus in view (the keyboard or the short band's hidden top row moved it).
function relayout(){const a=topAnchor(),changed=applyLayout(); if(changed&&META)drawPins(); applySideWidth(); applyOutlineState();autoW(); restoreAnchor(a); hideTip(); if(COMPOSE.current)renderComposer(); stickTop();updateSectionStrip(); keepFieldInView();}
// The height a list section header (sticky) sticks below. In compact, #right is the scroll box and the tool bar (#bar1, which holds
// the sheet handle in narrow) is already stuck above it, so the header sticks below that. In wide, #list itself is the scroll box, so this is 0.
function stickTop(){let t=0; const b=$('#bar1');
  if(LAYOUT!==LAYOUT_MODE.WIDE&&b){const cs=getComputedStyle(b); if(cs.position==='sticky')t=Math.round((parseFloat(cs.top)||0)+b.offsetHeight);}
  document.documentElement.style.setProperty('--stick-top',t+'px');}
// The tool bar's width (--bar1-w): the short band draws the tool bar over the right end of its one top row, and the nav bar's
// links end where it begins.
function barWidth(){document.documentElement.style.setProperty('--bar1-w',Math.ceil($('#bar1').getBoundingClientRect().width)+'px');}
if(window.ResizeObserver)new ResizeObserver(()=>{stickTop(); barWidth();}).observe($('#bar1'),{box:'border-box'});   // padding-only changes (the collapsed sheet) count
let RELAY=0;
function scheduleRelayout(){if(RELAY)return; RELAY=requestAnimationFrame(()=>{RELAY=0; if(META)relayout(); else applyLayout();});}
window.addEventListener('resize',scheduleRelayout);
MQ_COARSE.addEventListener('change',scheduleRelayout);
// Even a mere #left width change from expanding/collapsing the panel (compact) re-fits the page width. The layout is never
// changed directly in the callback - it's deferred to the next frame (avoids a ResizeObserver loop warning). wide still only reacts to window-size changes, as before.
// Never re-fit while the handle is being dragged (body.resizing) - setSideWidth fits it once on release.
if(window.ResizeObserver)new ResizeObserver(()=>{if(LAYOUT&&LAYOUT!==LAYOUT_MODE.WIDE&&!document.body.classList.contains('resizing'))scheduleRelayout();}).observe($('#left'));

// Virtual keyboard: on Chrome Android, the layout itself shrinks via the viewport meta's interactive-widget=resizes-content.
// A browser that doesn't understand that value instead measures the keyboard height (--kb) via visualViewport and raises the
// whole screen by that amount. A visualViewport shrunk by pinch zoom is not the keyboard (undone by multiplying by scale).
// If an input field has focus, it's scrolled into view.
function onViewport(){const vv=window.visualViewport; if(!vv)return;
  const lh=document.documentElement.clientHeight;
  let kb=Math.round(lh-vv.height*vv.scale); if(!(kb>=80)||!MQ_COARSE.matches)kb=0;
  const R=document.documentElement.style, prev=R.getPropertyValue('--kb');
  R.setProperty('--kb',kb+'px'); R.setProperty('--vvh',(lh-kb)+'px');
  const a=document.activeElement;
  if(prev!==kb+'px'&&a&&(a.tagName==='TEXTAREA'||a.tagName==='INPUT')&&$('#right').contains(a))
    requestAnimationFrame(()=>a.scrollIntoView({block:'center'}));}
if(window.visualViewport){visualViewport.addEventListener('resize',onViewport); visualViewport.addEventListener('scroll',onViewport);}
document.addEventListener('focusin',e=>{const t=e.target;
  if(LAYOUT!==LAYOUT_MODE.WIDE&&t&&t.tagName==='TEXTAREA'&&$('#right').contains(t))setTimeout(()=>t.scrollIntoView({block:'center'}),350);});
// Whether a text field has focus - a textarea, a text input or editable content - which on a touch screen means the keyboard is up.
function typingNow(){const a=document.activeElement; if(!a||a===document.body)return false; if(a.isContentEditable||a.tagName==='TEXTAREA')return true;
  return a.tagName==='INPUT'&&!/^(checkbox|radio|button|submit|reset|range|color|file|image|hidden)$/i.test(a.type||'');}
// The panel's text field that has focus (a note, an edit or a reply), or null.
function panelField(){const a=document.activeElement; return typingNow()&&$('#right').contains(a)?a:null;}
// body.typing while a panel text field has focus: the short band hides its top row then, leaving the keyboard's ~200px to the panel.
function syncTyping(){document.body.classList.toggle('typing',!!panelField());}
document.addEventListener('focusin',syncTyping);
document.addEventListener('focusout',()=>setTimeout(syncTyping,0));   // after the focus has moved on
// Scrolls a panel text field that has focus back into view after a re-fit; the scroller's scroll-padding keeps it clear of the save row.
function keepFieldInView(){const f=panelField(); if(f)f.scrollIntoView({block:'nearest'});}

// Onboarding shown only the first time (remembers that it's been seen in localStorage pinPrefs.coach).
let COACH_T=null;
function coach(key,text){const seen=Object.assign({},prefs().coach||{}); if(seen[key])return; seen[key]=1; savePrefs({coach:seen});
  $('#coach-t').textContent=text; $('#coach').hidden=false; clearTimeout(COACH_T); COACH_T=setTimeout(()=>{$('#coach').hidden=true;},8000);}
function setSelMode(on){SELMODE=!!on; document.body.classList.toggle('selmode',SELMODE);
  const b=$('#btn-select'); b.setAttribute('aria-pressed',String(SELMODE)); b.querySelector('.lbl').textContent=SELMODE?'선택 중':'선택';
  if(SELMODE)coach('sel','끌어서 고칠 곳을 고르세요 · 탭하면 그 문단 · 두 손가락으로 확대');}
function openMore(){const d=$('#more'); if(d.open)return; hideTip(); renderSizeSeg(); d.showModal(); toastHost();}
// Expanding done/dropped pins from [⋯] opens the panel and scrolls to that list.
function revealList(sel,shown){if(!shown)return; setSide(true); requestAnimationFrame(()=>{const t=$(sel); if(t)t.scrollIntoView({block:'start'});});}
// Clicking outside a dialog (the backdrop) closes it - only for a click whose target is the dialog itself and that falls outside its
// box rectangle. The same for [더보기], help and the documents sheet (and the Trash, below); help and the documents sheet used to
// stay open (input review 2026-09-26).
for(const sel of ['#more','#help','#docs-menu'])$(sel).addEventListener('click',e=>{const d=e.currentTarget; if(e.target!==d)return; const r=d.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});

