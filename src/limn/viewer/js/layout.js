// ------------------------------------------------ Layout bands (docs/handbook/viewer.md §모바일 레이아웃)
// The window's width, height and primary pointer pick a band (layoutFor), and the band a layout mode (BAND_MODE): wide - a right
// sidebar (width-adjustable); mid - the panel between the nav bar and the action row (an overlay up to 900px, else beside the
// document; the short band of a landscape phone folds both rows into one top row); narrow - a bottom sheet, collapsed by
// default. If the band changes partway through a collapse/expand or a rotation, the page width is re-fit while preserving the
// viewed position (topAnchor). Marks and the selection box are % coordinates within the page, so they fall back into place
// automatically once the page width is fit.
// The band for a w x h CSS px window whose primary pointer is coarse (touch) or not. Pure. A mouse reads the width only:
// phone up to 700px, the overlay panel up to 900px, the side panel up to 1099px, wide from 1100px. Touch reads the height and
// the orientation too, first match wins: under 600px wide a phone at any height; under 480px high the short band (a landscape
// phone); up to 839px, or up to 900px in portrait (h > w; a square window is landscape), the tablet sheet; up to 900px the
// overlay panel (an unfolded foldable); up to 1366px the side panel; wider, the desktop.
function layoutFor(w,h,coarse){
  if(!coarse){if(w<=700)return LAYOUT_BAND.PHONE; if(w<=900)return LAYOUT_BAND.MID_OVERLAY; if(w<=1099)return LAYOUT_BAND.MID_SIDE; return LAYOUT_BAND.WIDE;}
  if(w<600)return LAYOUT_BAND.PHONE; if(h<480)return LAYOUT_BAND.SHORT;
  if(w<=839||(w<=900&&h>w))return LAYOUT_BAND.TABLET_SHEET; if(w<=900)return LAYOUT_BAND.MID_OVERLAY;
  if(w<=1366)return LAYOUT_BAND.MID_SIDE; return LAYOUT_BAND.WIDE;}
// What layoutFor reads from the window now: {w, h, coarse}.
function bandInput(){return {w:innerWidth,h:innerHeight,coarse:MQ_COARSE.matches};}
// Keeping the band steady on touch (docs/handbook/viewer.md §모바일 레이아웃): a height change under BAND_HOLD_PX from the settled
// one is the address bar, and a new size or pointer must stay BAND_SETTLE_MS before the band follows it. Starting values,
// chosen by emulation; a real device may move them.
const BAND_HOLD_PX=96,BAND_SETTLE_MS=200;
// What a new observation N does to the settled input C ({w,h,coarse}, null before the first): settle at once with no C yet or
// for a mouse (both fine pointers); keep the band while a text field has focus (typing - the keyboard shrinks the layout) or
// when only the height moved less than BAND_HOLD_PX from C (C stays, so slow steps add up); otherwise wait for N to hold. Pure.
function settleBand(C,N,typing){if(!C||(!C.coarse&&!N.coarse))return BAND_STEP.SETTLE; if(typing)return BAND_STEP.KEEP;
  if(N.w===C.w&&N.coarse===C.coarse&&Math.abs(N.h-C.h)<BAND_HOLD_PX)return BAND_STEP.KEEP; return BAND_STEP.WAIT;}
// Picks the band for the settled input (BAND_IN; the window's at the first call) and its panel state: the body classes (lay-*, band-*, mid-overlay, compact), then wide follows the
// per-device pinPrefs.sideClosed (open by default), mid its midClosed (else open beside the document, collapsed as an overlay),
// narrow starts collapsed - except between the phone and the tablet sheet, both sheets, which keep it as it was. An open draft
// keeps it open. The status line moves to the band's place (placeStatus); the phone's navigation sheet closes when the band
// is no longer the phone (the nav bar does its job there); an open [더보기] stays open and redraws its sheet-height or panel-width
// row; the changes view's guide-line buttons move to the thumb row or back (revTargetActs). Returns whether the band or its
// overlay changed.
function applyLayout(){if(!BAND_IN)BAND_IN=bandInput(); const o=BAND_IN,band=layoutFor(o.w,o.h,o.coarse),L=BAND_MODE[band],overlay=L===LAYOUT_MODE.MID&&o.w<=900;
  if(band===BAND&&overlay===MID_OVERLAY)return false;
  const sheetToSheet=L===LAYOUT_MODE.NARROW&&LAYOUT===LAYOUT_MODE.NARROW,wasOpen=SIDE_OPEN;
  BAND=band; LAYOUT=L; MID_OVERLAY=overlay; OUTLINE_MID_OPEN=false; const b=document.body,p=prefs(); ZOOMED=false; endSideSlide();
  Object.values(LAYOUT_MODE).forEach(k=>b.classList.toggle('lay-'+k,k===L)); Object.values(LAYOUT_BAND).forEach(k=>b.classList.toggle('band-'+k,k===band));
  b.classList.toggle('mid-overlay',overlay); b.classList.toggle('compact',L!==LAYOUT_MODE.WIDE);
  SIDE_OPEN=L===LAYOUT_MODE.WIDE?p.sideClosed!==true:(L===LAYOUT_MODE.MID?(typeof p.midClosed==='boolean'?!p.midClosed:!overlay):sheetToSheet&&wasOpen);
  if(!REPICK&&(COMPOSE.current||EDITOR.current||REPLY||!$('#composer').hidden))SIDE_OPEN=true;   // an in-progress note/edit/reply is never left hidden collapsed
  if(band!==LAYOUT_BAND.PHONE&&$('#nav-sheet').open)$('#nav-sheet').close();
  applySide(); stickTop(); placeStatus(); if($('#more').open){renderSizeSeg(); placeMore();} if(REV.target)revTargetActs(); return true;}
// Whether the outline is an overlay over the document that opens one at a time with the pin panel (OUTLINE_MID_OPEN, never
// saved): in the mid bands and on the tablet sheet. The phone has no outline; wide keeps it beside the document.
function outlineOverlay(){return LAYOUT===LAYOUT_MODE.MID||BAND===LAYOUT_BAND.TABLET_SHEET;}
// A draft the panel is holding: the composer (a selection being noted), an open edit or reply, or a relocation. Collapsing by a
// drag stops short of it, a swipe only rubber-bands, and a collapsed [핀 N] shows a dot for it.
function draftOpen(){return !$('#composer').hidden||!!EDITOR.current||!!REPLY||!!REPICK;}
// Draws the panel state (docs/handbook/viewer.md §패널 폭과 시트 높이): the body classes (with the phone sheet's composing lift, the phone only), both [핀 N] toggles - the tool bar's and,
// for a collapsed wide panel, the nav bar's - with the open count and the draft dot, the handle's ARIA and the back-gesture layer.
// Their name says what they show: the nav bar's icon and pill '패널 펴기 · 열린 핀 11 · 검토 대기 1', every compact bar's chip half
// '핀 11 · 패널 펴기' (+ ' · 작성 중' for a draft). No arrow: the open state is the panel itself and aria-expanded.
// Idempotent and cheap: drawPins() calls it on every redraw. The panel keeps its open layout while it slides out.
function applySide(){const open=SIDE_OPEN,b=document.body,dot=!open&&draftOpen(),n=PINS.length,rv=REVIEW_ALL.length,composing=!$('#composer').hidden;
  b.classList.toggle('side-open',open||!!(SIDE_SLIDE&&SIDE_SLIDE.kind==='closing')); b.classList.toggle('composing',composing);
  if(!composing)SHEET_KEPT=false; b.classList.toggle('sheet-up',composing&&!SHEET_KEPT&&BAND===LAYOUT_BAND.PHONE);   // the phone sheet's composing lift; the tablet sheet's is tabletLift (panel-size.js)
  // The toggles' names: the review count only where its pill sits inside them (the wide nav bar); every compact bar's [핀 N]
  // names what it shows first and leaves the count to its own half [검토 M].
  const label=tr(open?'패널 접기':'패널 펴기')+' · '+tl('열린 핀 {n}',{n})+(rv?' · '+tl('검토 대기 {n}',{n:rv}):'')+(dot?' · '+tr('작성 중'):''),
    sheet=tl('핀 {n}',{n})+' · '+tr(open?'패널 접기':'패널 펴기')+(dot?' · '+tr('작성 중'):'');
  for(const t of [$('#btn-side'),$('#nav-side')]){t.setAttribute('aria-expanded',String(open)); t.setAttribute('aria-label',t.id==='btn-side'&&LAYOUT!==LAYOUT_MODE.WIDE?sheet:label);
    t.querySelector('.side-n').textContent=n; t.querySelector('.c-dot').hidden=!dot;}
  $('#nav-side').hidden=!(LAYOUT===LAYOUT_MODE.WIDE&&!open);
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
// Opening the mid panel or the tablet sheet closes the outline overlay (one at a time). Collapsing never touches the saved width -
// once collapsed, the panel's width is put back to it for the next opening.
function setSide(open,remember,slide){open=!!open;
  if(open&&outlineOverlay()){OUTLINE_MID_OPEN=false;applyOutlineState();}
  if(remember&&LAYOUT===LAYOUT_MODE.MID)savePrefs({midClosed:!open});
  if(remember&&LAYOUT===LAYOUT_MODE.WIDE)savePrefs({sideClosed:!open});
  if(SIDE_OPEN===open)return; SIDE_OPEN=open; const cut=!!SIDE_SLIDE&&SIDE_SLIDE.kind==='closing'; endSideSlide();
  if(open)document.documentElement.style.setProperty('--swipe-x','0px');   // never reopen an overlay still offset by a swipe
  const ms=slideMs(); if(ms&&slide)startSideSlide(open?'opening':'closing',ms);
  applySide(); hideTip(); if((!open&&!SIDE_SLIDE)||(open&&cut))applySideWidth();}   // reopened mid-slide: back from a drag's minimum to the saved width
// The panel's slide (0.18s; none with reduced motion, and none beside the document at 901-1099px, where the page re-fits instead).
// While it slides out the body keeps side-open, so the layout does not jump until it is gone.
const SLIDE_MS=180; let SIDE_SLIDE=/** @type {{kind:string,t:ReturnType<typeof setTimeout>}|null} */(null);
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
function relayout(){const a=topAnchor(),changed=applyLayout(); if(changed&&META)drawPins(); applySideWidth(); applyOutlineState();autoW(); restoreAnchor(a); hideTip(); if(COMPOSE.current)renderComposer(); stickTop();updateSectionStrip(); keepFieldInView(); fitBarWords();}
// The height a list section header (sticky) sticks below. In compact, #right is the scroll box and the tool bar (#bar1, which holds
// the sheet handle in narrow) is already stuck above it, so the header sticks below that. In wide, #list itself is the scroll box, so this is 0.
function stickTop(){let t=0; const b=$('#bar1');
  if(LAYOUT!==LAYOUT_MODE.WIDE&&b){const cs=getComputedStyle(b); if(cs.position==='sticky')t=Math.round((parseFloat(cs.top)||0)+b.offsetHeight);}
  document.documentElement.style.setProperty('--stick-top',t+'px');}
// The tool bar's width (--bar1-w): the short band draws the tool bar over the right end of its one top row, and the nav bar's
// links end where it begins - exactly there: rounded up, the nav bar ended up to a pixel short and the PDF showed through.
function barWidth(){document.documentElement.style.setProperty('--bar1-w',$('#bar1').getBoundingClientRect().width+'px');}
if(window.ResizeObserver)new ResizeObserver(()=>{stickTop(); barWidth();}).observe($('#bar1'),{box:'border-box'});   // padding-only changes (the collapsed sheet) count
let RELAY=0,BAND_T=0;
// Re-fits on the next frame after a resize, a pointer change or a panel/keyboard change - unless the band input is waiting to
// settle (bandSettle), in which case the band and the page width stay as they are until it does.
function scheduleRelayout(){if(RELAY)return; RELAY=requestAnimationFrame(()=>{RELAY=0; if(bandSettle())refit();});}
// The re-fit itself: relayout once the document is open, else only the layout.
function refit(){if(META)relayout(); else applyLayout();}
// Applies settleBand to the window now. Settle: BAND_IN takes the new input. Keep: BAND_IN stays (a pending wait is dropped - the
// window came back). Wait: (re)starts BAND_SETTLE_MS; when it runs out with no text field focused, BAND_IN takes the window's input
// and the page re-fits once. Returns whether the caller may re-fit now.
function bandSettle(){const N=bandInput(),step=settleBand(BAND_IN,N,typingNow()); clearTimeout(BAND_T); BAND_T=0;
  if(step===BAND_STEP.WAIT){BAND_T=setTimeout(()=>{BAND_T=0; if(typingNow())return; BAND_IN=bandInput(); refit();},BAND_SETTLE_MS); return false;}
  if(step===BAND_STEP.SETTLE)BAND_IN=N; return true;}
// Whether the window differs from the settled band input (a band change may be due).
function bandStale(){const o=bandInput(); return !!BAND_IN&&(o.w!==BAND_IN.w||o.h!==BAND_IN.h||o.coarse!==BAND_IN.coarse);}
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
{const vv=window.visualViewport; if(vv){vv.addEventListener('resize',onViewport); vv.addEventListener('scroll',onViewport);}}
document.addEventListener('focusin',e=>{const t=/** @type {HTMLElement} */(e.target);
  if(LAYOUT!==LAYOUT_MODE.WIDE&&t&&t.tagName==='TEXTAREA'&&$('#right').contains(t))setTimeout(()=>{if(BAND===LAYOUT_BAND.TABLET_SHEET)keepFieldInView(); else t.scrollIntoView({block:'center'});},350);});
// Whether a text field has focus - a textarea, a text input or editable content - which on a touch screen means the keyboard is up.
function typingNow(){const a=/** @type {HTMLInputElement} */(document.activeElement); if(!a||a===document.body)return false; if(a.isContentEditable||a.tagName==='TEXTAREA')return true;
  return a.tagName==='INPUT'&&!/^(checkbox|radio|button|submit|reset|range|color|file|image|hidden)$/i.test(a.type||'');}
// The panel's text field that has focus (a note, an edit or a reply), or null.
function panelField(){const a=document.activeElement; return typingNow()&&$('#right').contains(a)?a:null;}
let TYPING_PRESS=-1e9;   // performance.now() of the last pointerup: a focus change that soon after is that press's
document.addEventListener('pointerup',()=>{TYPING_PRESS=performance.now();},true);
// body.typing while a panel text field has focus: the short band hides its top row then, leaving the keyboard's ~200px to the panel;
// the tablet sheet re-measures its keyboard lift (applySheet, tabletLift). When a press takes the focus from the field, the class
// waits for that press's click (or 350ms): taking the short band's top row back at once moved the panel 48px under the finger
// between the touch's end and its click, so the click hit what was there now - a first tap on an edit card's dimmed line did
// nothing and the second worked.
let TYPING_HELD=false;   // syncTyping() is waiting for the press that took the focus (its click or 350ms)
function syncTyping(){const on=!!panelField(),b=document.body;
  if(!on&&b.classList.contains('typing')&&performance.now()-TYPING_PRESS<300){if(TYPING_HELD)return; TYPING_HELD=true;
    const go=()=>{if(!TYPING_HELD)return; TYPING_HELD=false; document.removeEventListener('click',go); syncTyping();};
    document.addEventListener('click',go); setTimeout(go,350); return;}
  b.classList.toggle('typing',on); if(BAND===LAYOUT_BAND.TABLET_SHEET)applySheet();}
document.addEventListener('focusin',syncTyping);
// After the focus has moved on: the typing class, and a band held while a text field had focus gets its turn (settleBand).
document.addEventListener('focusout',()=>setTimeout(()=>{syncTyping(); if(bandStale())scheduleRelayout();},0));
// Scrolls a panel text field that has focus back into view after a re-fit; the scroller's scroll-padding keeps it clear of the save row
// and, on a sheet, of the tool bar stuck above. On the tablet sheet the composer's location line comes to the top first, so it stays
// above the note.
function keepFieldInView(){const f=panelField(); if(!f||!MQ_COARSE.matches)return;   // touch only: a mouse window scrolls as it always did
  if(f===$('#note')&&BAND===LAYOUT_BAND.TABLET_SHEET)$('#composer .c-loc-row').scrollIntoView({block:'start'}); f.scrollIntoView({block:'nearest'});}

// Onboarding shown only the first time (remembers that it's been seen in localStorage pinPrefs.coach).
let COACH_T=/** @type {ReturnType<typeof setTimeout>|undefined} */(undefined);
function coach(key,text){const seen=Object.assign({},prefs().coach||{}); if(seen[key])return; seen[key]=1; savePrefs({coach:seen});
  $('#coach-t').textContent=text; $('#coach').hidden=false; clearTimeout(COACH_T); COACH_T=setTimeout(()=>{$('#coach').hidden=true;},8000);}
// The touch select mode (docs/handbook/viewer.md §모바일 레이아웃 선택 모드), on or off. Effects: body.selmode (the pages take
// one-finger drags, the PDF area gets its accent frame and the mode bar), the toggle's aria-pressed and its label ('선택' /
// '선택 중' where the bar shows one), the live region's words (the bar's, said once as it turns on; empty when off), and
// the mode bar's height for the reserve above page 1 (--sel-bar-h). The reserve comes and goes with the mode: scrolled to
// the top, page 1 moves below the bar; anywhere else the pages keep their place (selModeScrollTop). A focus left on the
// hidden bar's [끝내기] goes to the toggle. Idempotent; no coach mark - the bar says what a drag and a tap do.
function setSelMode(on){const was=SELMODE,L=$('#left'),doc=$('#doc'),top0=L.scrollTop,y0=doc.getBoundingClientRect().top;
  SELMODE=!!on; document.body.classList.toggle('selmode',SELMODE);
  const b=$('#btn-select'); b.setAttribute('aria-pressed',String(SELMODE)); /** @type {HTMLElement} */(b.querySelector('.lbl')).textContent=tr(SELMODE?'선택 중':'선택');
  $('#sel-sr').textContent=SELMODE?$('#sel-bar-t').textContent:'';
  if(SELMODE)selBarFit(); else if($('#sel-bar').contains(document.activeElement))b.focus({preventScroll:true});
  if(was!==SELMODE)L.scrollTop=selModeScrollTop(top0,L.scrollTop,doc.getBoundingClientRect().top-y0);}
// Where the PDF scroller goes (px) when the select mode's reserve above page 1 comes or goes and the pages move by moved px
// (down positive): at the very top (top0, the position before, at 0 or above) it stays at 0, so the reserve uncovers page 1's
// first line rather than the bar covering it; anywhere else the pages keep their place on screen - from now (the position
// after, which a browser's scroll anchoring may already have moved, then moved is 0) by as far as they moved, never above
// the top. Pure.
function selModeScrollTop(top0,now,moved){return top0<=0?0:Math.max(0,now+moved);}
// Fits the mode bar to what is around it: its width as --sel-bar-w (selBarWidth, from its natural width and the PDF area's)
// and its drawn height as --sel-bar-h, which the reserve above page 1 adds up (responsive.css). Once as the mode turns on
// (setSelMode reads the height in the same task) and whenever the bar or the PDF area changes size (words wrapping anew, a
// rotation, the overlay panel). A hidden bar (0 high) leaves the last values.
function selBarFit(){const b=$('#sel-bar'); if(!b.offsetHeight)return; b.style.removeProperty('--sel-bar-w');
  b.style.setProperty('--sel-bar-w',selBarWidth(b.getBoundingClientRect().width,$('#sel-mode').clientWidth)+'px');
  document.documentElement.style.setProperty('--sel-bar-h',b.offsetHeight+'px');}
// The mode bar's width (px) for its natural width w in a PDF area a px wide: the next whole pixel up, and one more when that
// leaves the two sides an odd remainder, so the centred bar's edges - and the icon tile and [끝내기] 4px inside them - fall on
// whole pixels. Icons are drawn at whole pixels: a bar centred at x.47 drew its icon half a pixel off its tile. Pure.
function selBarWidth(w,a){let W=Math.ceil(w-0.01); if((Math.round(a)-W)%2)W++; return W;}
if(window.ResizeObserver){const o=new ResizeObserver(selBarFit); o.observe($('#sel-bar')); o.observe($('#sel-mode'));}
// Opens dialog d (a sheet in compact: [더보기], the navigation sheet, the help, the Trash) as a modal with the focus on d itself
// (tabindex=-1, drawn without a ring), not on its first control: a phone's browser drew the focus ring on [닫기] each time a
// tap opened one. Tab goes on to [닫기], the first control.
function showSheet(d){d.showModal(); d.focus({preventScroll:true});}
// Opens [더보기] with its view group drawn for now: the sheet-height or panel-width segment and the zoom figure, and its foot on
// one ink line (footInk); on the wide desktop it is a menu under [⋯] (placeMore), which says it is open (aria-expanded).
function openMore(){const d=$('#more'); if(d.open)return; hideTip(); drawZoom(); renderSizeSeg(); placeMore(); showSheet(d); footInk(); toastHost();
  $('#btn-more').setAttribute('aria-expanded','true');}
$('#more').addEventListener('close',()=>$('#btn-more').setAttribute('aria-expanded','false'));
// The wide desktop's [더보기] as a menu under [⋯]: its top 4px under the button and its right edge on the button's - the
// --more-top and --more-right that body.lay-wide #more reads (the compact sheets ignore them). Again on a relayout while open.
function placeMore(){const b=$('#btn-more'); if(LAYOUT!==LAYOUT_MODE.WIDE||!b.getClientRects().length)return; const r=b.getBoundingClientRect(),d=$('#more');
  d.style.setProperty('--more-top',(r.bottom+4)+'px'); d.style.setProperty('--more-right',(document.documentElement.clientWidth-r.right)+'px');}
// How far the foot's wordmark and version drop so their ink bottoms meet [도움말]'s: from the label's Hangul ink descent below
// the shared baseline and the version's (px, positive = below). The wordmark has none ("limn" ends on the baseline); a label
// without Hangul ('Help', whose 'p' hangs below by design) counts as none. Pure.
function inkDrops(labelDescent,versionDescent){return {word:labelDescent,ver:labelDescent-versionDescent};}
// [더보기]'s foot on one ink line (docs/handbook/viewer.md §모바일 레이아웃): Hangul reaches below the Latin baseline the row
// shares, so on one baseline [도움말] read lower than "limn" and the version. From the fonts in use - canvas metrics of the
// very strings, read at 64 times the size because the canvas rounds them to whole pixels - the wordmark and the version drop
// until their ink bottoms meet the label's Hangul (inkDrops), and the chevron moves to the centre of the label's ink.
function footInk(){const f=$('#more-foot'),h=f&&f.querySelector('[data-act=help]'),v=f&&f.querySelector('.m-ver'); if(!h||!v)return;
  const t=[...h.childNodes].find(n=>n.nodeType===3&&n.nodeValue.trim()),ch=h.querySelector('svg'); if(!t)return;
  const label=t.nodeValue.trim(),hangul=hangulOf(label),hm=inkMetrics(h,label);
  const d=inkDrops(hangul?inkMetrics(h,hangul).d:0,inkMetrics(v,v.textContent.trim()).d);
  f.style.setProperty('--ink-word',d.word+'px'); f.style.setProperty('--ink-ver',d.ver+'px'); f.style.setProperty('--help-chev','0px');
  if(!ch)return; const w=document.createElement('span'),k=document.createElement('span');   // the label's baseline: an empty inline-block on it
  k.style.cssText='display:inline-block;width:0;height:0'; h.insertBefore(w,t); w.append(t,k); const base=k.getBoundingClientRect().bottom;
  h.insertBefore(t,w); w.remove(); const mid=base-(hm.a-hm.d)/2,cr=ch.getBoundingClientRect();
  f.style.setProperty('--help-chev',(mid-(cr.top+cr.height/2))+'px');}
// The ink of s in el's font as {a, d}: how far it rises above and reaches below the baseline (px), from the canvas's text
// metrics read at 64 times the size, because the canvas rounds them to whole pixels.
let INK_CTX=/** @type {CanvasRenderingContext2D|null} */(null);   // inkMetrics()'s canvas context, made on first use
function inkMetrics(el,s){const c=/** @type {CanvasRenderingContext2D} */(INK_CTX||(INK_CTX=document.createElement('canvas').getContext('2d'))),S=64,cs=getComputedStyle(el);
  c.font=cs.fontStyle+' '+cs.fontWeight+' '+parseFloat(cs.fontSize)*S+'px '+cs.fontFamily; const x=c.measureText(s);
  return {a:x.actualBoundingBoxAscent/S,d:x.actualBoundingBoxDescent/S};}
// The Hangul letters of s (syllables and jamo) - the glyphs that reach below the Latin baseline. Pure.
function hangulOf(s){return String(s).replace(/[^ᄀ-ᇿ㄰-㆏가-힣]/g,'');}
// Help's head on one ink line (docs/handbook/viewer.md §마크와 파비콘), the foot's rule: the wordmark ("limn" ends on the
// baseline) drops by the title's Hangul ink descent ('— 사용법'), so their ink bottoms meet. Its 20px box was centred on the
// row and "limn" stood 3.3px below the title's foot. English ('— How to use') has no Hangul and no drop.
function headInk(){const h=$('#help-h'),t=h&&h.querySelector(':scope>span'); if(!t)return; const hangul=hangulOf(t.textContent);
  h.style.setProperty('--ink-word',inkDrops(hangul?inkMetrics(t,hangul).d:0,0).word+'px');}
// Clicking outside a dialog (the backdrop) closes it - only for a click whose target is the dialog itself and that falls outside its
// box rectangle. The same for [더보기], help, the navigation sheet and the status line's list (and the Trash, below); help and
// the documents sheet used to stay open (input review 2026-09-26).
for(const sel of ['#more','#help','#nav-sheet','#status-list'])$(sel).addEventListener('click',e=>{const d=e.currentTarget; if(e.target!==d)return; const r=d.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});
// However the navigation sheet closes, the focus goes back to the button that opens it.
$('#nav-sheet').addEventListener('close',()=>{const b=$('#btn-pos'); if(b.getClientRects().length)b.focus({preventScroll:true});});

