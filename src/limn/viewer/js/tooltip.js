// ------------------------------------------------ Tooltip
const TIP=$('#tip'); let tipT=/** @type {ReturnType<typeof setTimeout>|undefined} */(undefined),tipEl=/** @type {HTMLElement|null} */(null),
  TIPXY=/** @type {number[]|null} */(null);
document.addEventListener('mousemove',e=>{TIPXY=[e.clientX,e.clientY];},{passive:true});
function hideTip(){clearTimeout(tipT);tipT=undefined;tipEl=null;TIP.hidden=true;}
// Shows el's description over it. The box is translate="no": a description is already in the UI language (the translator
// rewrote the attribute, or the code drew it with tr()), and one that quotes a note ('#38 · 완료') must not be rewritten again.
function showTip(el){showTipText(el,el.dataset.tip||'');}
// Shows txt over el as its description box (showTip's drawing; statusWhy shows [이유]'s sentence at the line this way). Nothing
// without a text or for an element no longer in the page.
/** @param {HTMLElement} el @param {string} txt */
function showTipText(el,txt){if(!txt||!document.contains(el))return;
  TIP.textContent=txt; TIP.hidden=false;
  const r=el.getBoundingClientRect(),tw=TIP.offsetWidth,th=TIP.offsetHeight;
  let top=r.top-th-8, cx=r.left+r.width/2;
  if(top<4) top=r.bottom+8;
  if(top>innerHeight-th-4 && TIPXY){top=TIPXY[1]+18; cx=TIPXY[0];}   // an element taller than the window (#grip/a long card) anchors to the pointer instead
  top=Math.max(4,Math.min(top,innerHeight-th-4));
  const left=Math.min(Math.max(4,cx-tw/2),innerWidth-tw-4);
  TIP.style.left=left+'px'; TIP.style.top=top+'px';}
function armTip(el){if(el===tipEl)return; hideTip(); if(!el)return; tipEl=el; tipT=setTimeout(()=>showTip(el),300);}
// Hover/focus tooltips are never shown right after a touch - mobile Chrome simulates mouseover/focusin on every tap, so a
// description used to pop up every time a button was pressed. Touch relies on long-press instead (below).
const touchRecent=()=>Date.now()-LAST_TOUCH_T<1500;
document.addEventListener('pointerdown',e=>{LAST_PTR=e.pointerType||'mouse'; if(LAST_PTR!=='mouse')LAST_TOUCH_T=Date.now();},true);
// Whether a key press makes the keyboard the input the focus ring answers: any key outside a text field (Tab, a shortcut such
// as '?'), and in a field only a key that leaves it or acts (Tab, Escape, or with Ctrl/⌘/Alt) - typing is not, nor a touch
// keyboard's 'Unidentified' key or an IME's composing one. Pure.
function keyNavigates(key,inField,mod){if(!key||key==='Unidentified'||key==='Process')return false;
  return !inField||key==='Tab'||key==='Escape'||!!mod;}
// The input the focus ring answers (docs/handbook/viewer.md §뜻과 모양): html[data-input] is 'pointer' after a press and 'key'
// after a key that navigates, and components.css draws the ring only outside 'pointer'. A sheet takes the first focus itself,
// but closing one gives the focus back by script ([본문 1/2 ▾], help's opener), and Chrome rings a script focus whenever the
// last input it counted was a key - on Android a tap on a bar button did not reset that.
document.addEventListener('pointerdown',()=>{document.documentElement.dataset.input='pointer';},true);
// Makes the keyboard the input the ring answers when a key press navigates (keyNavigates); a press makes it the pointer (above).
function inputFromKey(e){if(keyNavigates(e.key,typingNow(),e.ctrlKey||e.metaKey||e.altKey))document.documentElement.dataset.input='key';}
document.addEventListener('keydown',inputFromKey,true);
document.addEventListener('mouseover',e=>{if(touchRecent()||MQ_NOHOVER.matches)return; const t=/** @type {HTMLElement} */(e.target); armTip(t.closest?t.closest('[data-tip]'):null);});
// A focus tooltip is never shown on an input field (textarea) - it covered the snippet while typing, and the tooltip
// swallowed the first Esc, so "Esc to cancel -> Ctrl+Enter" ended up saving a pin that was meant to be discarded (observed).
document.addEventListener('focusin',e=>{const t=/** @type {HTMLElement} */(e.target);
  if((t&&t.tagName==='TEXTAREA')||touchRecent()||MQ_NOHOVER.matches){if(Date.now()>=SWALLOW_CLICK)hideTip();return;}
  armTip(t.closest?t.closest('[data-tip]'):null);});
// Long-press tooltip (touch/pen): holding for 500ms shows the description, and the one click after release is swallowed (so the button doesn't fire).
// Over a page image, quick selection (long-press = that paragraph) takes priority, so only badges (.mark [data-act=mark-jump]) apply. Input fields keep their paste menu.
let PRESS=/** @type {{el:HTMLElement,x:number,y:number,t:ReturnType<typeof setTimeout>,shown?:boolean}|null} */(null),SWALLOW_CLICK=0;
/** Find a touch tooltip target while preserving native input menus and paragraph selection outside pin badges. */
function pressTarget(t){const el=t&&t.closest?t.closest('[data-tip]'):null; if(!el)return null;
  if(el.tagName==='TEXTAREA'||el.tagName==='INPUT')return null;
  if(el.closest('.pg')&&!el.closest('.mark [data-act=mark-jump]'))return null; return el;}
document.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse')return; if(!TIP.hidden)hideTip();
  const el=pressTarget(e.target); if(!el)return;
  PRESS={el,x:e.clientX,y:e.clientY,t:setTimeout(()=>{showTip(el); if(PRESS)PRESS.shown=true; SWALLOW_CLICK=Date.now()+900;
    setTimeout(()=>{if(!TIP.hidden&&TIP.textContent===el.dataset.tip)hideTip();},4000);},500)};},true);
function endPress(){if(PRESS){clearTimeout(PRESS.t); PRESS=null;}}
document.addEventListener('pointermove',e=>{if(PRESS&&Math.hypot(e.clientX-PRESS.x,e.clientY-PRESS.y)>10)endPress();},true);
document.addEventListener('pointerup',endPress,true);
document.addEventListener('pointercancel',endPress,true);
document.addEventListener('click',e=>{if(Date.now()<SWALLOW_CLICK){SWALLOW_CLICK=0;e.preventDefault();e.stopImmediatePropagation();}},true);
// Inside that window a touch's compatibility mousedown must not move focus either: after a quick pick opened the sheet under
// the finger it focused the note field and raised the virtual keyboard (input review 2026-09-26, s12_seltap).
document.addEventListener('mousedown',e=>{if(Date.now()<SWALLOW_CLICK&&LAST_PTR!=='mouse')e.preventDefault();},true);
document.addEventListener('contextmenu',e=>{if(LAST_PTR==='mouse')return; const t=/** @type {HTMLElement} */(e.target);
  if(t&&t.closest&&(t.closest('.pg')||pressTarget(t)))e.preventDefault();});
document.addEventListener('input',hideTip,true);
document.addEventListener('focusout',hideTip);
document.addEventListener('scroll',hideTip,true);
// Releasing right after a long-press opens it, Chrome sends a simulated mousedown - that alone must never close it.
document.addEventListener('mousedown',()=>{if(Date.now()>=SWALLOW_CLICK)hideTip();},true);
