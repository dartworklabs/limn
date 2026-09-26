// ------------------------------------------------ Layout by screen width (mobile)
// wide: 1100px and up, a right sidebar (width-adjustable). mid: over 700px, under 1100px - a narrow side
// panel; when collapsed, only the bottom-right tool bar remains. narrow: 700px and below (a folded foldable/phone) -
// a bottom sheet, collapsed by default. If the width changes partway through a collapse/expand, the layout is re-chosen
// and the page width is re-fit while preserving the viewed position (topAnchor). Marks and the selection box are % coordinates within the page, so they fall back into place automatically once the page width is fit.
function layoutFor(){const w=innerWidth; if(w<=700)return 'narrow'; if(w<1100)return 'mid'; return 'wide';}
// Picks the layout for the window width and its panel state: wide follows the per-device pinPrefs.sideClosed (open by default),
// mid its midClosed (else open beside the document, collapsed as an overlay), narrow starts collapsed. An open draft keeps it open.
function applyLayout(){const L=layoutFor(),overlay=L==='mid'&&innerWidth<=900; if(L===LAYOUT&&overlay===MID_OVERLAY)return false;
  LAYOUT=L; MID_OVERLAY=overlay; OUTLINE_MID_OPEN=false; const b=document.body,p=prefs(); ZOOMED=false; endSideSlide();
  ['wide','mid','narrow'].forEach(k=>b.classList.toggle('lay-'+k,k===L)); b.classList.toggle('compact',L!=='wide');
  SIDE_OPEN=L==='wide'?p.sideClosed!==true:(L==='mid'?(typeof p.midClosed==='boolean'?!p.midClosed:!overlay):false);
  if(!REPICK&&(CUR||EDIT||REPLY||!$('#composer').hidden))SIDE_OPEN=true;   // an in-progress note/edit/reply is never left hidden collapsed
  applySide(); stickTop(); return true;}
// A draft the panel is holding: the composer (a selection being noted), an open edit or reply, or a relocation. Collapsing by a
// drag stops short of it, a swipe only rubber-bands, and a collapsed [핀 N] shows a dot for it.
function draftOpen(){return !$('#composer').hidden||!!EDIT||!!REPLY||!!REPICK;}
// Draws the panel state (docs/handbook/viewer.md §패널 폭과 시트 높이): the body classes, both [핀 N] toggles - the tool bar's and,
// for a collapsed wide panel, the nav bar's - with the open count, the draft dot and the arrow, the handle's ARIA and the back-gesture
// layer. Idempotent and cheap: drawPins() calls it on every redraw. The panel keeps its open layout while it slides out.
function applySide(){const open=SIDE_OPEN,b=document.body,dot=!open&&draftOpen(),n=PINS.length;
  b.classList.toggle('side-open',open||!!(SIDE_SLIDE&&SIDE_SLIDE.kind==='closing')); b.classList.toggle('composing',!$('#composer').hidden);
  const label=tr(open?'패널 접기':'패널 펴기')+' · '+tl('열린 핀 {n}',{n})+(dot?' · '+tr('작성 중'):'');
  for(const t of [$('#btn-side'),$('#nav-side')]){t.setAttribute('aria-expanded',String(open)); t.setAttribute('aria-label',label);
    t.querySelector('.side-n').textContent=n; t.querySelector('.c-dot').hidden=!dot;}
  $('#nav-side').hidden=!(LAYOUT==='wide'&&!open);
  $('#side-arrow').innerHTML=ic(LAYOUT==='narrow'?(open?'chevron-down':'chevron-up'):(open?'chevron-right':'chevron-left'));
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
  if(open&&LAYOUT==='mid'){OUTLINE_MID_OPEN=false;applyOutlineState();}
  if(remember&&LAYOUT==='mid')savePrefs({midClosed:!open});
  if(remember&&LAYOUT==='wide')savePrefs({sideClosed:!open});
  if(SIDE_OPEN===open)return; SIDE_OPEN=open; const cut=!!SIDE_SLIDE&&SIDE_SLIDE.kind==='closing'; endSideSlide();
  if(open)document.documentElement.style.setProperty('--swipe-x','0px');   // never reopen an overlay still offset by a swipe
  const ms=slideMs(); if(ms&&slide)startSideSlide(open?'opening':'closing',ms);
  applySide(); hideTip(); if((!open&&!SIDE_SLIDE)||(open&&cut))applySideWidth();}   // reopened mid-slide: back from a drag's minimum to the saved width
// The panel's slide (0.18s; none with reduced motion, and none beside the document at 901-1099px, where the page re-fits instead).
// While it slides out the body keeps side-open, so the layout does not jump until it is gone.
const SLIDE_MS=180; let SIDE_SLIDE=null;
// The slide's length for this layout in ms: 0 with reduced motion, beside the document (901-1099px) and for the narrow sheet.
function slideMs(){return MQ_REDUCED.matches||!(LAYOUT==='wide'||MID_OVERLAY)?0:SLIDE_MS;}
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
  const hidden=(a===$('#grip')&&LAYOUT!=='wide')||($('#right').contains(a)&&!$('#bar2').contains(a)&&!(LAYOUT!=='wide'&&$('#bar1').contains(a)));
  if(hidden)(LAYOUT==='wide'?$('#nav-side'):$('#btn-side')).focus({preventScroll:true});}
// [핀 N], Ctrl/⌘+\ and the handle's Enter: collapse with the slide, or open. Collapsing moves a focus out of the hidden panel;
// opening from the nav bar's [핀 N] (which hides as the panel opens) moves the focus to the handle beside the panel.
function toggleSide(){const open=!SIDE_OPEN,a=document.activeElement; setSide(open,true,true);
  if(!open)focusSideToggle(); else if(a===$('#nav-side'))$('#grip').focus({preventScroll:true});}
// The first drag-collapse on a wide screen says once how to bring the panel back (it leaves only a 6px rail behind).
function coachSideCollapsed(){if(LAYOUT==='wide'&&!SIDE_OPEN)coach('side','핀 패널은 오른쪽 위 [핀 N] 또는 Ctrl+\\ 로 다시 엽니다');}
function relayout(){const a=topAnchor(); applyLayout(); applySideWidth(); applyOutlineState();autoW(); restoreAnchor(a); hideTip(); if(CUR)renderComposer(); stickTop();updateSectionStrip();}
// The height a list section header (sticky) sticks below. In compact, #right is the scroll box and the tool bar (#bar1, below the
// sheet handle in narrow) is already stuck above it, so the header sticks below that. In wide, #list itself is the scroll box, so this is 0.
function stickTop(){let t=0; const b=$('#bar1');
  if(LAYOUT!=='wide'&&b){const cs=getComputedStyle(b); if(cs.position==='sticky')t=Math.round((parseFloat(cs.top)||0)+b.offsetHeight);}
  document.documentElement.style.setProperty('--stick-top',t+'px');}
if(window.ResizeObserver)new ResizeObserver(()=>stickTop()).observe($('#bar1'));
let RELAY=0;
function scheduleRelayout(){if(RELAY)return; RELAY=requestAnimationFrame(()=>{RELAY=0; if(META)relayout(); else applyLayout();});}
window.addEventListener('resize',scheduleRelayout);
MQ_COARSE.addEventListener('change',scheduleRelayout);
// Even a mere #left width change from expanding/collapsing the panel (compact) re-fits the page width. The layout is never
// changed directly in the callback - it's deferred to the next frame (avoids a ResizeObserver loop warning). wide still only reacts to window-size changes, as before.
// Never re-fit while the handle is being dragged (body.resizing) - setSideWidth fits it once on release.
if(window.ResizeObserver)new ResizeObserver(()=>{if(LAYOUT&&LAYOUT!=='wide'&&!document.body.classList.contains('resizing'))scheduleRelayout();}).observe($('#left'));

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
  if(LAYOUT!=='wide'&&t&&t.tagName==='TEXTAREA'&&$('#right').contains(t))setTimeout(()=>t.scrollIntoView({block:'center'}),350);});

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

