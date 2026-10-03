// ------------------------------------------------ PoC variants for issues #167 and #168 (branch poc/toast-and-select)
// Not a final design: the owner picks one of each, and the pick is then built properly. A URL flag turns a variant on and
// flags combine (?poc=q1b,q2a). Without a flag nothing in this part changes the page: every hook below is behind POC_Q1/POC_Q2.
//   q1a | q1b | q1c   #167, what replaces the toasts: (a) context only, (b) the status line, (c) the hybrid.
//   q2a | q2b | q2c   #168, the pin-select control: (a) marquee icon + label, (b) segmented [보기 | 선택],
//                     (c) marquee icon + a mode bar inside the PDF while the mode is on.
// GET /poc lists the variants with one line each.
const POC=(()=>{const s=new Set();
  try{String(new URLSearchParams(location.search).get('poc')||'').split(/[\s,+]+/).forEach(v=>{if(/^q[12][abc]$/.test(v))s.add(v);});}catch(e){}
  return s;})();
const POC_Q1=['a','b','c'].find(v=>POC.has('q1'+v))||'';
const POC_Q2=['a','b','c'].find(v=>POC.has('q2'+v))||'';
POC.forEach(v=>document.body.classList.add('poc-'+v));

// ---------------- #167: messages without toasts
// A message is what toast() was given, plus where it came from (dd.poc at the call site: purpose, site, pin id, section and the
// card before it). pocWhere() picks its place by the variant's rule; the message lives there until it is replaced, dismissed
// with [x], or - for an inline note - until the next press elsewhere. A deferred send ([되돌리기] of a reply, a confirm, a
// permanent delete) still leaves after 6 seconds, as the toast did, and its leaving sends the request (deferred()'s _gone).
/** @typedef {{label:string,fn:Function,tip?:string}} PocAct */
/** @typedef {{kind:string,title:string,desc:string,acts:PocAct[],site:string,id:number|null,ids:number[]|null,sec:string,prev:number|null,
 *   purpose:string,what:string,badge:string,literal:boolean,deferred:boolean,keep:boolean,alive:boolean,where:string,host:string,
 *   el:HTMLElement,timer:ReturnType<typeof setTimeout>|undefined}} PocMsg */
let POC_LINE=/** @type {PocMsg|null} */(null);           // the status line's message (b; c's background events and hint)
const POC_NOTES=/** @type {Map<number,PocMsg>} */(new Map());   // pin id -> a note drawn inside that card (a, c)
const POC_TOMBS=/** @type {Map<number,PocMsg>} */(new Map());   // pin id -> a row drawn where that card was (a, c)
const POC_BANNERS=/** @type {Map<string,PocMsg>} */(new Map()); // 'composer' | 'list' -> the one banner on top of that panel
const POC_MARKS=/** @type {Map<number,PocMsg>} */(new Map());   // pin id -> a chip on that pin's mark on the PDF (a)
let POC_FIELD=/** @type {PocMsg|null} */(null),POC_HINT=/** @type {PocMsg|null} */(null);
const POC_IC=/** @type {Record<string,()=>Html>} */({ok:()=>ic('circle-check'),warn:()=>ic('triangle-alert'),err:()=>ic('circle-x'),info:()=>ic('info')});

// toast()'s stand-in while a q1 flag is on. Returns a handle element that deferred() can hook (_gone, isConnected, remove()).
/** @returns {HTMLElement} */
function pocToast(msg,kind,action,dd){
  const ctx=Object.assign({},(dd&&dd.poc)||{}),[title,desc]=toastSplit(msg),el=document.createElement('div');
  // A toast with event keys ('<event>:<pin>', toastDup) is someone else's doing: the list comparison and the browser-notification
  // path. Its pins and a review request's badge come from the keys, so those call sites stay as they are.
  const keys=/** @type {string[]} */((dd&&dd.keys)||[]);
  if(keys.length&&!ctx.purpose){ctx.purpose='background';
    const ids=keys.map(k=>Number(k.slice(k.lastIndexOf(':')+1))).filter(n=>n>0); if(ids.length)ctx.ids=ids;
    if(keys.some(k=>k.indexOf(EVENT_TYPE.REVIEW_REQUESTED+':')===0))ctx.badge='rv';
    if(keys.some(k=>k.indexOf(EVENT_TYPE.DROPPED+':')===0)&&ids.length){ctx.site='tomb'; ctx.id=ids[0]; ctx.sec='open';}}   // (a) a row with [되살리기] where it was
  const deferredUndo=!!(action&&action.tip==='보내기 전에 취소합니다');
  /** @type {PocMsg} */
  const m={kind:kind||'ok',title,desc,acts:action?[action]:[],site:ctx.site||'',id:ctx.id==null?null:ctx.id,ids:ctx.ids||null,sec:ctx.sec||'',
    prev:ctx.prev==null?null:ctx.prev,purpose:ctx.purpose||(kind==='err'?'error':kind==='warn'?'warn':'success'),what:ctx.what||'',badge:ctx.badge||'',
    literal:!!(dd&&dd.literal),deferred:deferredUndo,keep:false,alive:true,where:'',host:'',el,timer:undefined};
  Object.defineProperty(el,'isConnected',{get:()=>m.alive});
  el.remove=()=>{if(m.keep&&m.alive){m.acts=[]; m.deferred=false; pocRedraw(m);} else pocDrop(m);};
  if(m.what==='핀 저장'&&m.purpose==='error'){m.title=tr('저장하지 못했습니다'); m.desc=tr(ctx.net?'서버에 닿지 않습니다 · 메모는 그대로입니다':m.desc);
    if(POC_Q1!=='a')m.acts=[{label:'다시 시도',fn:()=>savePin()}];}
  if(m.site==='save'){pocDrop(POC_FIELD); pocDrop(POC_BANNERS.get('composer'));}   // a save that went through clears its failure
  if(m.badge==='rv'&&!m.acts.length&&POC_Q1!=='a')m.acts=[{label:'보기',fn:()=>gotoReview()}];   // a line far from the list takes you there
  pocShow(m,pocWhere(m));
  if(m.deferred&&m.alive)m.timer=setTimeout(()=>{if(!m.alive)return; m.keep=m.where==='line'; toastGone(m.el);},6000);
  return el;}

// Where a message goes, by the variant's rule.
/** @param {PocMsg} m */
function pocWhere(m){const v=POC_Q1,attn=m.purpose==='error'||m.purpose==='warn'||m.purpose==='conflict';
  if(v==='b')return 'line';                                              // (b) everything: one line, until replaced
  if(m.purpose==='hint')return v==='a'?'pdf':'line';
  if(v==='a'){                                                           // (a) where it happened
    if(m.site==='save')return 'mark';                                    // the new pin's mark, where the finger picked
    if(m.what==='핀 저장'&&attn)return 'field';
    if(m.site==='tomb'&&m.id!=null)return 'tomb';
    if((m.id!=null||m.ids)&&(m.site==='card'||m.purpose==='background'))return 'card';
    if(attn)return 'banner';
    return m.acts.length?'banner':'none';}
  if(m.purpose==='background')return 'line';                             // (c) background: the line and a badge
  if(attn)return 'banner';                                               //     errors and conflicts: a banner on the panel
  if(m.site==='tomb'&&m.id!=null)return 'tomb';                          //     success: silent, or inline when it can be undone
  if((m.id!=null)&&m.acts.length)return 'card';
  return m.acts.length?'line':'none';}

/** @param {PocMsg} m @param {string} where */
function pocShow(m,where){m.where=where;
  switch(where){
    case 'line':pocDrop(POC_LINE); POC_LINE=m; if(m.badge&&POC_Q1==='c')document.body.classList.add('poc-new-'+m.badge); drawStatus(); break;
    case 'banner':{const host=m.what==='핀 저장'||m.site==='save'?'composer':m.sec==='review'?'review':'list'; pocDrop(POC_BANNERS.get(host)); POC_BANNERS.set(host,m); m.host=host;
      if(POC_Q1==='c'&&LAYOUT!==LAYOUT_MODE.WIDE&&!SIDE_OPEN)document.body.classList.add('poc-new-side'); pocDrawBanners();
      const e=document.querySelector('.poc-banner[data-host="'+host+'"]'); if(e)e.scrollIntoView({block:'nearest'}); break;}
    // (a) A note goes at the next press elsewhere; a background note waits to be seen ([x] or a newer note on that card).
    // (c) A success note (its [되돌리기]) stays until a newer success note replaces it: on the phone the sheet folds after a
    // save, and the press that opens it again must not take the undo away.
    case 'card':if(POC_Q1==='c'&&m.purpose==='success')POC_NOTES.forEach(v=>{if(v.purpose==='success')pocDrop(v);});
      (m.ids||[/** @type {number} */(m.id)]).forEach(i=>{pocDrop(POC_NOTES.get(i)); POC_NOTES.set(i,m); OPEN_CARDS.add(i);}); drawPins();
      if(POC_Q1==='a'&&m.purpose!=='background')pocArmClear(m); break;
    case 'tomb':pocDrop(POC_TOMBS.get(/** @type {number} */(m.id))); POC_TOMBS.set(/** @type {number} */(m.id),m); drawPins(); pocArmClear(m); break;
    case 'mark':pocDrop(POC_MARKS.get(/** @type {number} */(m.id))); POC_MARKS.set(/** @type {number} */(m.id),m); marks(); pocArmClear(m); break;
    case 'field':pocDrop(POC_FIELD); POC_FIELD=m; pocDrawField(); break;
    case 'pdf':pocDrop(POC_HINT); POC_HINT=m; pocDrawPdfHint(); break;
    default:m.alive=false; if(m.deferred)setTimeout(()=>toastGone(m.el));}}

// Takes a message away (replaced, dismissed, or its time is up) and lets deferred() send what it held.
/** @param {PocMsg|null|undefined} m */
function pocDrop(m){if(!m||!m.alive)return; m.alive=false; clearTimeout(m.timer);
  if(POC_LINE===m)POC_LINE=null;
  for(const map of /** @type {Map<string|number,PocMsg>[]} */([POC_BANNERS,POC_NOTES,POC_TOMBS,POC_MARKS]))map.forEach((v,k)=>{if(v===m)map.delete(k);});
  if(POC_FIELD===m)POC_FIELD=null; if(POC_HINT===m)POC_HINT=null;
  pocRedraw(m); toastGone(m.el);}
/** @param {PocMsg} m */
function pocRedraw(m){switch(m.where){case 'line':drawStatus();break; case 'banner':pocDrawBanners();break; case 'card':case 'tomb':drawPins();break;
  case 'mark':marks();break; case 'field':pocDrawField();break; case 'pdf':pocDrawPdfHint();break;}}
// An inline note stays until the next press somewhere else (a deterministic end, no timer), except a deferred send's.
/** @param {PocMsg} m */
function pocArmClear(m){const t0=Date.now(),off=()=>document.removeEventListener('pointerdown',h,true);
  const h=/** @param {Event} e */e=>{if(!m.alive){off();return;} if(Date.now()-t0<400)return;
    const t=/** @type {HTMLElement} */(e.target); if(t&&t.closest&&t.closest('.poc-msg'))return; off(); if(!m.deferred)pocDrop(m);};
  document.addEventListener('pointerdown',h,true);}

// One message as an element: status icon, title and description, its actions ([되돌리기] and the like) and [x].
/** @param {PocMsg} m @param {string} cls */
function pocMsgEl(m,cls){const e=document.createElement('div'); e.className='poc-msg '+cls+' pm-'+m.kind; e.setAttribute('role',m.kind==='err'?'alert':'status');
  setHtml(e,html`<span class="pm-ic">${(POC_IC[m.kind]||POC_IC.ok)()}</span><span class="pm-t"><span class="pm-ti"></span><span class="pm-d"></span></span><span class="pm-acts"></span>`);
  /** @type {HTMLElement} */(e.querySelector('.pm-ti')).textContent=m.title;
  const d=/** @type {HTMLElement} */(e.querySelector('.pm-d')); if(m.desc)d.textContent=m.desc; else d.remove();
  if(m.literal)/** @type {HTMLElement} */(e.querySelector('.pm-t')).translate=false;
  const acts=/** @type {HTMLElement} */(e.querySelector('.pm-acts'));
  m.acts.forEach(a=>{const b=document.createElement('button'); b.type='button'; b.className='btn-sm btn-secondary pm-act'; b.textContent=tr(a.label);
    b.addEventListener('click',ev=>{ev.stopPropagation(); m.el._gone=null; pocDrop(m); a.fn();}); acts.appendChild(b);});
  const x=document.createElement('button'); x.type='button'; x.className='btn-icon btn-sm btn-ghost pm-x'; x.setAttribute('aria-label',tr('알림 닫기')); setHtml(x,ic('x'));
  x.addEventListener('click',ev=>{ev.stopPropagation(); pocDrop(m);}); acts.appendChild(x);
  return e;}

// (b, c) The status line: the message takes the line's first place and the build/sync items stay behind '+N'. On the desktop,
// whose status is the chip row (#bar2) with no line, the message gets a line of its own right under that row (#poc-wline).
// Called by drawStatus(); true when it drew the line.
function pocDrawLine(){const m=POC_LINE,w=$('#poc-wline');
  if(LAYOUT===LAYOUT_MODE.WIDE){if(w)w.remove(); if(m&&m.alive){const n=document.createElement('div'); n.id='poc-wline'; n.appendChild(pocMsgEl(m,'poc-line')); $('#bar2').after(n);} return false;}
  if(w)w.remove(); if(!m||!m.alive)return false;
  const box=$('#status'),body=/** @type {HTMLElement} */(box.querySelector('.st-body')),list=statusList(statusInput());
  document.body.classList.add('has-status'); box.hidden=false; STATUS_SIG='';
  const e=pocMsgEl(m,'poc-line'); body.replaceChildren(e);
  if(list.length){const more=document.createElement('button'); more.className='btn-sm btn-ghost st-more'; more.dataset.act='status-more';
    setHtml(more,html`<span class="lbl">${tl('+{n}',{n:list.length})}</span>`); /** @type {HTMLElement} */(e.querySelector('.pm-acts')).prepend(more);}
  const sr=/** @type {HTMLElement} */(box.querySelector('.st-sr')); if(sr.textContent!==m.title)sr.textContent=m.title;
  return true;}

// (a errors, c errors and conflicts) One banner on top of the panel or section it concerns: the composer for a save, the
// review section for a confirm, else the list. Shown into view once when it arrives.
function pocDrawBanners(){document.querySelectorAll('.poc-banner').forEach(e=>e.remove());
  POC_BANNERS.forEach((m,host)=>{const e=pocMsgEl(m,'poc-banner'); e.dataset.host=host;
    if(host==='composer')$('#composer').prepend(e); else if(host==='review'){$('#sec-review').hidden=false; $('#review-pins').before(e);} else $('#list').prepend(e);});}

// (a, c) Notes inside a card and rows where a card was. drawPins() calls this after it drew the list.
function pocDecorate(){if(!POC_Q1)return;
  POC_NOTES.forEach((m,id)=>{const c=document.querySelector('#list .pin.card[data-id="'+id+'"]'); if(!c)return;
    c.classList.add('poc-hl'); const at=c.querySelector('.tags')||c.querySelector('.head'); if(at)at.after(pocMsgEl(m,'poc-note'));});
  POC_TOMBS.forEach((m,id)=>{if(document.querySelector('#list .pin.card[data-id="'+id+'"]'))return;
    const box=m.sec==='review'?$('#review-pins'):$('#pins'); if(m.sec==='review')$('#sec-review').hidden=false;
    const e=pocMsgEl(m,'poc-tomb'),prev=m.prev!=null?box.querySelector('[data-id="'+m.prev+'"]'):null;
    if(prev)prev.after(e); else box.prepend(e);});}

// (a) The new pin's mark on the PDF carries the result - where the finger picked, still on screen after the phone's sheet
// folds: [✓ 핀 #N 저장됨 · 되돌리기]. marks() calls this after it drew the marks.
function pocDecorateMarks(){if(!POC_Q1)return;
  POC_MARKS.forEach((m,id)=>{const k=/** @type {HTMLElement|null} */(document.querySelector('.mark[data-pin="'+id+'"]')); if(!k)return;
    const c=pocMsgEl(m,'poc-markchip'); k.appendChild(c);
    const pg=/** @type {HTMLElement} */(k.closest('.pg')),pr=pg.getBoundingClientRect(),cr=c.getBoundingClientRect(),over=cr.right-(pr.right-4);   // stays on its page
    if(over>0)c.style.left=Math.max(-(cr.left-pr.left-4),-over)+'px';});}

// (a) A failed save says so right over [핀 저장], which then reads [다시 저장]; the note stays in the field.
function pocDrawField(){const old=$('#poc-field'); if(old)old.remove(); const b=$('#btn-save');
  if(!POC_FIELD){if(b.dataset.pocRetry){delete b.dataset.pocRetry; setHtml(b,saveBtnLabel());} return;}
  const e=pocMsgEl(POC_FIELD,'poc-fielderr'); e.id='poc-field'; $('#c-actions').prepend(e);
  b.dataset.pocRetry='1'; b.textContent=tr('다시 저장');}

// (a) The first-visit hint as a strip on top of the PDF area, stuck there until [x].
function pocDrawPdfHint(){const old=$('#poc-pdfhint'); if(old)old.remove(); if(!POC_HINT)return;
  const e=pocMsgEl(POC_HINT,'poc-pdfhint'); e.id='poc-pdfhint'; $('#left').prepend(e);}

// A save's failure belongs to that selection: when the composer closes (saved, cancelled), it goes with it.
if(POC_Q1)new MutationObserver(()=>{if($('#composer').hidden){pocDrop(POC_FIELD); pocDrop(POC_BANNERS.get('composer'));}})
  .observe($('#composer'),{attributes:true,attributeFilter:['hidden']});

// coach()'s stand-in: the first-visit hint becomes a message of purpose 'hint'. True when it took it.
function pocHint(text){if(!POC_Q1)return false;
  if(POC_Q1==='c')document.body.classList.add('poc-new-sel');
  const t=pocToast(text,'info',null,{poc:{purpose:'hint'}}); return !!t;}

// A badge says "new since you last looked": pressing what it sits on clears it.
document.addEventListener('click',e=>{if(!POC.size)return; const a=/** @type {HTMLElement|null} */(/** @type {HTMLElement} */(e.target).closest('[data-act]')); if(!a)return;
  const act=a.dataset.act||'',B=document.body.classList;
  if(act==='goto-review'||act==='side'){B.remove('poc-new-rv','poc-new-side');}
  if(act==='selmode'||act==='poc-sel')B.remove('poc-new-sel');
  if(act==='poc-sel'){const on=a.dataset.on==='1'; if(on!==SELMODE){setSelMode(on); if(on&&LAYOUT===LAYOUT_MODE.NARROW&&!COMPOSE.current&&!EDITOR.current)setSide(false);}}},true);

// ---------------- #168: the pin-select control
// (a) and (c) draw the symmetric marquee (square-dashed) in place of the scan icon; (a) also names it on every band - [⬚ 선택],
// pressed [⬚ 선택 중] in the accent fill. (b) swaps the button for the segmented control [보기 | 선택]. (c) keeps the icon alone in
// the bar and, while the mode is on, shows a bar at the top of the PDF: what a drag and a tap do, and [끝내기].
function pocSelBoot(){if(!POC_Q2)return; const b=$('#btn-select');
  if(POC_Q2!=='b')setHtml(b,html`${ic('square-dashed')}<span class="lbl">${tr(SELMODE?'선택 중':'선택')}</span>`);
  if(POC_Q2==='b'){const s=document.createElement('div'); s.id='poc-selseg'; s.className='seg tch'; s.setAttribute('role','radiogroup'); s.setAttribute('aria-label',tr('PDF를 누르면'));
    setHtml(s,html`<button role="radio" data-act="poc-sel" data-on="0" data-tip="${tr('PDF를 끌면 스크롤합니다. 길게 누르면 그 문단을 고릅니다')}">${tr('보기')}</button><button role="radio" data-act="poc-sel" data-on="1" data-tip="${tr('PDF를 끌면 영역을, 탭하면 그 문단을 고릅니다')}">${tr('선택')}</button>`);
    b.after(s);}
  if(POC_Q2==='c'){const bar=document.createElement('div'); bar.id='poc-selbar';
    setHtml(bar,html`<div class="psb" role="status">${ic('square-dashed')}<span class="psb-t"><b>${tr('선택 중')}</b><span>${tr('끌면 영역 · 탭하면 문단')}</span></span><button class="btn-sm btn-secondary" data-act="selmode">${tr('끝내기')}</button></div>`);
    $('#left').prepend(bar);}
  pocSelSync();}
// Follows SELMODE: the segment that is on, and the bar's fit.
function pocSelSync(){if(!POC_Q2)return; const s=$('#poc-selseg');
  if(s)s.querySelectorAll('button').forEach(x=>{const on=(/** @type {HTMLElement} */(x).dataset.on==='1')===SELMODE; x.classList.toggle('on',on); x.setAttribute('aria-checked',String(on));});
  if(LAYOUT)fitBarWords();}
// Before the bar is measured (fitBarWords): (a) holds the width of its pressed face [⬚ 선택 중] in both states, so pressing it
// never moves or squeezes its neighbours; (b) on the phone puts the segmented control over the PDF's bottom-left corner, just
// above the sheet - the bar's left cell (172px at 411) cannot hold [핀 N | 검토 M] (two 44px hits at least) and two 44px
// segments in a 36px track (98px) - and back into the bar on every other band.
function pocSelPlace(){
  if(POC_Q2==='a'){const b=$('#btn-select'),l=/** @type {HTMLElement} */(b.querySelector('.lbl')),cur=l.textContent,pressed=b.getAttribute('aria-pressed');
    b.style.minWidth=''; b.setAttribute('aria-pressed','true'); l.textContent=tr('선택 중'); const w=b.getBoundingClientRect().width;
    l.textContent=cur; b.setAttribute('aria-pressed',pressed||'false'); if(w)b.style.minWidth=Math.ceil(w)+'px';}
  if(POC_Q2==='b'){const s=$('#poc-selseg'),b=$('#btn-select'); if(!s)return;
    if(BAND===LAYOUT_BAND.PHONE){if(s.parentNode!==document.body)document.body.appendChild(s);} else if(s.previousElementSibling!==b)b.after(s);}}

// The card shown before pin id in list (an open or review list as drawn), or null: where a row left in its place goes.
/** @param {Pin[]} list @param {number} id */
function pocPrev(list,id){const i=list.findIndex(p=>p.id===id); return i>0?list[i-1].id:null;}
pocSelBoot();
