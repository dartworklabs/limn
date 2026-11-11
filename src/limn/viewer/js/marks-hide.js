// ------------------------------------------------ Hiding the pin marks for a look at the page itself (docs/handbook/viewer.md §핀 표시 숨기기)
// A pin's mark lies over what it marks - a box and a badge on a PDF page, a tinted line and a gutter badge on the Markdown
// and text surfaces - so a pinned figure is seen through the mark. To judge how it was fixed the marks can be taken off:
// - H, pressed and let go, turns them off, and on again; held, it flips them only for as long as it is down (MARKS_HOLD_MS).
// - [더보기]'s switch [핀 표시] does the same on a touch screen; it closes the sheet so the page shows.
// While they are off the status line says so and offers [다시 보이기]. They come back by themselves when a mark has
// something to show: a [보기] that goes to a pin's mark, and a save's or an append's undo chip, which sits on its mark.
// Off is this page's state only (never stored): a reload shows every mark.
// Only the marks go. The pins, the cards, the page verdict lines and the selection box are as they were.
const MARKS={off:false,held:/** @type {{code:string,at:number}|null} */(null)};
const MARKS_HOLD_MS=350;   // a press this long is a look, not a switch
const MARKS_SOURCE='marks-off';   // the status line's one reminder (sourceEntry)
// Whether keydown e is the marks key: the key that types h, alone, whatever its place on the layout. A key that types no
// Latin letter (a Hangul jamo, an input method's 'Process') counts by its place: the physical H key. Pure.
/** @param {{key?:string,code?:string,ctrlKey?:boolean,metaKey?:boolean,altKey?:boolean,shiftKey?:boolean}} e @returns {boolean} */
function marksKey(e){if(e.ctrlKey||e.metaKey||e.altKey||e.shiftKey)return false; const k=e.key||'';
  return /^[a-z]$/i.test(k)?k.toLowerCase()==='h':e.code==='KeyH';}
// What a press of the marks key that lasted ms does to the marks, off or not before it: a short one switches them, a long
// one was only a look and leaves them as they were. Returns whether they are off after it. Pure.
/** @param {boolean} off @param {number} ms @returns {boolean} */
function marksAfterPress(off,ms){return ms>=MARKS_HOLD_MS?off:!off;}
// Shows the page with or without its marks, for now: the class the styles read (components.css, md-surface.css). The
// state itself (MARKS.off), the switch and the reminder are marksSet's.
/** @param {boolean} off */
function marksLook(off){document.body.classList.toggle('marks-off',off);}
// Paints [더보기]'s switch from the state: on while the marks show.
function drawMarksSwitch(){const m=$('#m-marks'); m.setAttribute('aria-checked',String(!MARKS.off));
  m.dataset.tip=MARKS.off?'핀 표시가 숨겨져 있습니다. 누르면 다시 보입니다 (H)':'누르면 쪽 위의 핀 표시를 숨깁니다. 핀과 카드는 그대로입니다 (H)';}
// Turns the marks off or on for good: the look, the switch, and the status line's reminder - put there when they go off,
// taken away when they come back. Says the change to a screen reader (the reminder reads itself). No request is sent.
/** @param {boolean} off */
function marksSet(off){const was=MARKS.off; MARKS.off=off; MARKS.held=null; marksLook(off); drawMarksSwitch();
  if(off)lineNote('핀 표시를 숨겼습니다',NOTICE_KIND.INFO,{label:'다시 보이기',tip:'쪽 위의 핀 표시를 다시 보입니다 (H)',fn:()=>marksSet(false)},{life:NOTICE_LIFE.STICKY,source:MARKS_SOURCE});
  else{sourceOk(MARKS_SOURCE); if(was)quietNote('핀 표시를 다시 보입니다');}}
// The marks come back because one of them has something to show (a [보기], an undo chip). Nothing when they already show.
function marksShow(){if(MARKS.off||MARKS.held)marksSet(false);}
// The marks key goes down: the marks flip at once, so a look starts with the press. Not in a text field, under a dialog or
// in the changes view (no marks there), and a repeat of a held key is the same press.
/** @param {KeyboardEvent} e */
function marksKeyDown(e){if(e.isComposing||!marksKey(e))return;
  const t=/** @type {HTMLElement|null} */(e.target),inField=!!t&&(t.tagName==='TEXTAREA'||t.tagName==='INPUT'||t.tagName==='SELECT'||t.isContentEditable);
  if(inField||document.querySelector('dialog[open]')||document.body.classList.contains('revision-open'))return;
  e.preventDefault(); if(e.repeat||MARKS.held)return;
  MARKS.held={code:e.code,at:e.timeStamp}; marksLook(!MARKS.off);}
// The marks key comes up: a short press was a switch, a long one a look (marksAfterPress).
/** @param {KeyboardEvent} e */
function marksKeyUp(e){const h=MARKS.held; if(!h||e.code!==h.code)return;
  const off=marksAfterPress(MARKS.off,e.timeStamp-h.at); if(off===MARKS.off){MARKS.held=null; marksLook(off);} else marksSet(off);}
// A press whose key never comes up here (the window lost the focus, the tab was hidden) was a look: the marks are as before.
function marksPressLost(){if(!MARKS.held)return; MARKS.held=null; marksLook(MARKS.off);}
addEventListener('keydown',marksKeyDown); addEventListener('keyup',marksKeyUp);
addEventListener('blur',marksPressLost); document.addEventListener('visibilitychange',()=>{if(document.hidden)marksPressLost();});
drawMarksSwitch();
