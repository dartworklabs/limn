// ------------------------------------------------ A verdict's reason (docs/handbook/viewer.md §판정 핀 — 판정과 함께 이유)
// After a save on a page verdict line a person may say why in a short text that becomes the pin's note. It is written in a
// small popover over the line (.pv-pop: inside the line and laid above it, so it never pushes the page down or makes the
// floating line taller). No save opens it by itself: the line offers [이유 추가] after a click and, while the keys act on
// the line, 'Enter 이유 쓰기' - Enter opens it with the focus. Once open, every character typed in it is text, digits too
// (a data plot's reason often starts with one: '12월 값이 튐'); before it opens the digits are the line's verdict keys. The
// verdict's saved reason (a check and its first line, a pencil) opens it again to change it or clear it ([지우기]). One
// popover at a time: the session (PV_REASON) belongs to its pin, document and visit and keeps what is typed. A draft is
// never lost without a word:
// - it is kept per pin in this tab (sessionStorage, rd*) and a reload brings it back; leaving the page with one asks first
//   (beforeunload);
// - with text, Esc takes two presses - the first lets the focus go (the keys then change the verdict) and says what the
//   second does, which drops it; [접기] folds it away behind the line's '초안 있음' (and it stays folded after a reload);
// - changing the verdict while it is being typed moves it to the new verdict (pvReasonAfterSave);
// - [되돌리기] of a cancel or of the save chip brings it back with its verdict (pvReasonRevive);
// - a verdict taken back elsewhere while its reason is being typed leaves the text as its page's draft, said in one line,
//   and the keys typed after the field went are not verdict keys (pvKeyGuarded);
// - a write that fails - unreachable, refused, too long, a note changed elsewhere - keeps it, and the line marks it '초안 있음'.
// Moving on - the reading page leaving the popover's page after it was there, another save on another page, another
// document - closes it and writes what was typed, said in one line; a folded draft waits for the person.

// ---------------- Drafts kept per pin (sessionStorage)
// One record per instance label for this tab: {v:1, d:{<key>: {text, base, rev, mode, folded, at, tried, from}}}. The key is
// '<doc>:<pin id>' for a verdict's draft, '<doc>:p<page>' for a page's (the draft of a verdict taken back elsewhere, waiting
// for the next verdict on that page). text: typed and not written yet; base: the reason it was typed over ('' for a new
// reason); rev: the pin's rev when a saved reason was opened (a change is written against that rev, never a later one); mode:
// 'replace' (the whole note, against rev) or 'add' (into an empty note, or under someone's); folded: put away with [접기] - it
// never opens by itself; tried: the session's writes whose answer was lost (ReasonTry) - a folded, reopened or reloaded
// draft still knows them, or its next write would add a reason that had landed again; from: the key it was moved from
// while that pin's reason may still be written there (a write out, or a [다시 시도]): once that write lands the moved copy
// goes, and its failure does not make the old key again (pvReasonCommit, pvReasonFailed). Written on every input; taken out
// once written, dropped (Esc twice, [지우기]), moved to a new verdict, or when its pin is found gone from the lists
// (pvReasonRestore).
const RD_V=1;
/** @typedef {{text:string,base:string,rev:number,mode:string,folded:boolean,at:number,tried:ReasonTry[],from:string}} ReasonDraft */
function rdKey(){return 'limnReason:'+encodeURIComponent(META&&META.label||'');}
/** @returns {Record<string,ReasonDraft>} */
function rdAll(){try{const o=JSON.parse(sessionStorage.getItem(rdKey())||'null'); return o&&o.v===RD_V&&o.d&&typeof o.d==='object'?o.d:{};}catch(e){return {};}}
/** @param {Record<string,ReasonDraft>} d */
function rdSave(d){try{if(Object.keys(d).length)sessionStorage.setItem(rdKey(),JSON.stringify({v:RD_V,d})); else sessionStorage.removeItem(rdKey());}catch(e){}}
// A verdict's draft key (id a pin number) or a page's (id 'p<page>').
/** @param {string|null} doc @param {number|string} id */
function rdName(doc,id){return (doc||'')+':'+id;}
/** @param {any} x @returns {ReasonDraft|null} */
function rdRead(x){return x&&typeof x.text==='string'&&x.text.trim()?{text:x.text,base:typeof x.base==='string'?x.base:'',rev:typeof x.rev==='number'?x.rev:-1,
  mode:x.mode==='replace'||(x.mode!=='add'&&typeof x.base==='string'&&!!x.base.trim())?'replace':'add',folded:!!x.folded,at:Number(x.at)||0,
  tried:Array.isArray(x.tried)?x.tried.filter(rdTry):[],from:typeof x.from==='string'?x.from:''}:null;}
// Whether a stored lost write is one (ReasonTry).
/** @param {any} a @returns {a is ReasonTry} */
function rdTry(a){return !!a&&typeof a.text==='string'&&typeof a.rev==='number'&&typeof a.pre==='string'&&typeof a.stamp==='boolean'&&typeof a.post==='string';}
// The draft kept under id (a pin number, or 'p<page>') on document doc, or null.
/** @param {string|null} doc @param {number|string} id @returns {ReasonDraft|null} */
function rdGet(doc,id){return rdRead(rdAll()[rdName(doc,id)]);}
// Keeps text under id - or drops it when nothing is unsaved (empty, or the reason as it is saved). A from the draft there
// had stays unless o names one.
/** @param {string|null} doc @param {number|string} id @param {string} text @param {string} base @param {number} [rev] @param {{mode?:string,folded?:boolean,tried?:ReasonTry[],from?:string}} [o] */
function rdPut(doc,id,text,base,rev,o){const d=rdAll(),k=rdName(doc,id),mode=o&&o.mode||(base.trim()?'replace':'add'),was=rdRead(d[k]);
  const from=o&&o.from!==undefined?o.from:was?was.from:'';
  if(text.trim()&&text.trim()!==base.trim())d[k]={text,base,rev:rev===undefined?-1:rev,mode,folded:!!(o&&o.folded),at:Date.now(),tried:o&&o.tried||[],from};
  else delete d[k]; rdSave(d);}
// Keeps reason session r's text as its pin's draft (open, not folded), with its lost writes.
/** @param {ReasonSession} r @param {boolean} [folded] */
function rdKeep(r,folded){rdPut(r.doc,r.id||'p'+r.page,r.text,r.base,r.rev,{mode:r.mode,folded:!!folded,tried:r.tried});}   // not bound yet: the page's
/** @param {string|null} doc @param {number|string} id */
function rdDrop(doc,id){const d=rdAll(),k=rdName(doc,id); if(k in d){delete d[k]; rdSave(d);}}
// Moves the draft under from (a pin or a page) to verdict pin id, as a new reason - it was never written on the other (its
// lost writes stay behind: they were the other pin's), remembering where it came from (rdMovedOff).
/** @param {string|null} doc @param {number|string} from @param {number} id @returns {ReasonDraft|null} */
function rdMove(doc,from,id){const x=rdGet(doc,from); if(!x)return null; rdDrop(doc,from); rdPut(doc,id,x.text,'',-1,{mode:'add',folded:x.folded,from:rdName(doc,from)}); return x;}
// The drafts moved off pin id's key on document doc (rdMove, pvReasonUncancelDraft) while its reason may still be written
// there, by key.
/** @param {string|null} doc @param {number} id @returns {string[]} */
function rdMovedOff(doc,id){const d=rdAll(),k=rdName(doc,id); return Object.keys(d).filter(x=>{const r=rdRead(d[x]); return !!r&&r.from===k;});}
// Pin id's reason text was written there: a copy moved off its key goes - or, joined under a page's draft, its part does.
/** @param {string|null} doc @param {number} id @param {string} text */
function rdWrittenOff(doc,id,text){const d=rdAll(); let ch=false;
  for(const x of rdMovedOff(doc,id)){const r=rdRead(d[x]); if(!r)continue; const t=r.text.trim();
    if(t===text){delete d[x]; ch=true;} else if(t.endsWith('\n'+text)){d[x]={...r,text:t.slice(0,t.length-text.length-1),from:''}; ch=true;}}
  if(ch)rdSave(d);}

// ---------------- The session
// sid: the popover's own number - its field stays the same element while its draft moves to another verdict, so the focus
// and an input method's composition stay with it. base: the reason the field opened on ('' for a new one). mode: 'replace'
// (it changes the saved reason, or puts its text over a newer note the person has seen: the whole note, against rev) or
// 'add' (a new reason: into an empty note, or under the note someone wrote, read fresh before writing). rev: the pin's rev
// when the replaced note was read - the change and [지우기] are written against it, so a note changed meanwhile elsewhere
// is never written over. conflict: that newer note and its rev, once a write found it (the popover shows it whole and
// offers [그 위에 쓰기], pvReasonReapply). from: the verdict the draft moved from (0 when it did not), said in the popover.
// escArm: the first Esc (or [닫기]) with text was pressed - 'key' or 'btn' - and the next one drops the draft. saved: the
// text the session has written; tried: its writes that failed without an answer that says they did not land (they may
// have), each with the rev it was sent against and what it made of the note (ReasonTry, pvReasonLanded); clearTried: a
// [지우기] whose answer was lost (the next one reads the note first). id 0: the popover was opened by Enter
// while its verdict's save was still out (pvReasonOpenPending) - the text waits for the verdict's number (pvReasonAfterSave
// binds it), and an Enter in it meanwhile saves once it has one (saveWhenBound). onto: the verdict its line changed to while
// its write was out - that write's outcome is said and settled by pvReasonOnto.
/** @typedef {{sid:number,page:number,id:number,key:string,doc:string|null,visit:any,text:string,base:string,mode:string,rev:number,conflict:{note:string,rev:number}|null,from:number,seen:boolean,listed:boolean,writing:Promise<boolean>|null,saved:string|null,tried:ReasonTry[],clearTried:boolean,escArm:string,saveWhenBound?:boolean,onto?:number}} ReasonSession */
// A new reason's write whose answer was lost: text, sent against the pin's rev `rev`, would have made the note pre, then the
// stamp a note_append puts first when stamp ('(추가 12:30) ', the time the server's), then text, then post.
/** @typedef {{text:string,rev:number,pre:string,stamp:boolean,post:string}} ReasonTry */
let PV_REASON=/** @type {ReasonSession|null} */(null);
let PV_RSEQ=0;
// The popovers moved away from (another page, another document, another popover) before their verdict's save answered, by
// line (pvSlot of the document they were typed on): each stays bound to that save, not to the screen.
const PV_DETACHED=/** @type {Map<string,ReasonSession>} */(new Map());
let PV_LAST_SAVE=0;   // the verdict pin the last save on a page line made: its line offers the way to its reason wherever it is
let PV_KEY_SAVE=0;   // ...when that save was a key's: its line says 'Enter 이유 쓰기'
// The pins this person withdrew (the save's undo, [판정 취소], a pressed word pressed again) while a reason for them may still
// be on its way: its failure, or its finding the pin gone, is no news to them - nothing is said. A failed withdrawal or a
// restore takes the pin out again.
const PV_WITHDRAWN=/** @type {Set<number>} */(new Set());
/** @param {number} page @param {number} id @param {string} key @param {string} text @param {string} base @param {number} [rev] @param {string} [mode] @returns {ReasonSession} */
function pvReasonNew(page,id,key,text,base,rev,mode){
  return {sid:++PV_RSEQ,page,id,key,doc:DOC,visit:captureVisit(),text,base,mode:mode||(base.trim()?'replace':'add'),rev:rev===undefined?-1:rev,conflict:null,from:0,
    seen:pvReadingPage()===page,listed:false,writing:null,saved:null,tried:[],clearTried:false,escArm:''};}
// Whether reason session r writes the whole note against its rev (a change of a saved reason, or over a newer note seen).
/** @param {ReasonSession} r */
function pvReasonEdits(r){return r.mode==='replace';}
/** @param {number} page */
function pvReasonOn(page){const r=PV_REASON; return !!r&&r.page===page&&r.doc===DOC&&currentVisit(r.visit);}
// The pin a reason session is for, from the lists, or undefined.
/** @param {number} id */
function pvReasonPin(id){return OPEN_ALL.concat(REVIEW_ALL,DONE_ALL).find(p=>p.id===id);}
/** @param {unknown} t @returns {t is HTMLTextAreaElement} */
function pvIsReasonField(t){return t instanceof HTMLTextAreaElement&&t.classList.contains('pv-reason');}
// The open popover's field, or null.
function pvReasonField(){return /** @type {HTMLTextAreaElement|null} */(document.querySelector('#doc .pv-pop .pv-reason'));}
// Whether the session's text is something not yet written: not empty, not the reason it opened on, not what it wrote.
/** @param {ReasonSession} r */
function pvReasonDirty(r){const t=r.text.trim(); return !!t&&t!==r.base.trim()&&t!==r.saved;}
// The current verdict of page `page`'s line on the document on screen, or undefined.
/** @param {number} page */
function pvCurOf(page){return (pageVerdictPins().get(page)||[])[0];}
// Before a line is drawn: a session of another document or visit goes (its text saved, pvReasonLeave); one whose pin left
// the lists (undone or taken back elsewhere) goes - its text kept as its page's draft, said in one line, and the keys typed
// after its field went are not verdict keys (pvReasonLost); else it follows its pin to the page that pin's target is on now.
// Without a session, a document's first lines bring back its newest kept draft (pvReasonRestore).
function pvReasonSync(){const r=PV_REASON;
  if(r&&(r.doc!==DOC||!currentVisit(r.visit))){pvReasonLeave(); return;}
  if(!PINS_APPLIED_SEQ)return;
  if(!r){pvReasonRestore(); return;}
  const p=pvReasonPin(r.id);
  if(!p){if(r.listed)pvReasonLost(r); return;}   // not listed yet right after its save; gone once it was
  r.listed=true; const t=pageTargetOf(p,META?META.kind:undefined); if(t)r.page=t.page;}
// The verdict reason session r was for left the lists while it was open - taken back in another tab or by another person, or
// its save undone elsewhere. What was typed is not lost: it waits as its page's draft ('초안 있음' on the line, moved to the
// next verdict saved there), the status line says so, and when the field had the focus the line's draft mark takes it and
// the keys pressed next are not taken as verdict keys - the person was typing text (pvKeyGuard).
/** @param {ReasonSession} r */
function pvReasonLost(r){const f=pvReasonField(),had=!!f&&document.activeElement===f; PV_REASON=null;
  if(pvReasonDirty(r)&&!PV_WITHDRAWN.has(r.id)){rdDrop(r.doc,r.id); rdPut(r.doc,'p'+r.page,r.text,'',-1,{mode:'add',folded:true});
    lineNote(tl('판정 #{id}{p} 다른 곳에서 거둬졌습니다 · 쓰던 이유는 이 쪽의 초안으로 남겼습니다 — {target}',{id:r.id,p:josa(r.id,'이','가'),target:pvReasonName(r)}),NOTICE_KIND.WARN,null,{literal:true});}
  if(had){PV_KEY_GUARD=true; PV_REFOCUS={page:r.page,sel:'[data-act="pv-reason-open"]'};}}
// After the lines are drawn (drawPageVerdicts): a focus a session's end owes goes to its line's control (PV_REFOCUS).
let PV_REFOCUS=/** @type {{page:number,sel:string}|null} */(null);
function pvReasonAfterLines(){const w=PV_REFOCUS; if(!w)return; PV_REFOCUS=null;
  const c=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+w.page+'"] '+w.sel)); if(c)c.focus({preventScroll:true});}
// Once per document in this page's life, when its first lines are drawn: the drafts kept for pins that are gone are let go,
// one kept for a verdict that is not its line's current one of the person's becomes its page's draft (only that is marked
// there), and the others wait on their lines ('초안 있음') - none opens by itself: a popover restored on a page far from the reading
// one opened out of sight, said only to a screen reader. The status line says how many came back, with [보기], which brings
// the first one's line into view and puts the focus on its mark.
const PV_RESTORED=/** @type {Set<string>} */(new Set());
function pvReasonRestore(){const doc=DOC||''; if(PV_RESTORED.has(doc)||!META)return; PV_RESTORED.add(doc);
  const d=rdAll(),pre=doc+':',kind=META.kind; let ch=false; const pages=/** @type {Set<number>} */(new Set());
  for(const k of Object.keys(d)){if(!k.startsWith(pre))continue; const rest=k.slice(pre.length),x=rdRead(d[k]); if(!x)continue;
    if(rest.startsWith('p')){pages.add(Number(rest.slice(1))||0); continue;}   // a page's draft waits on its line
    const p=pvReasonPin(Number(rest));
    if(!p){delete d[k]; ch=true; continue;}
    const t=pageTargetOf(p,kind); if(!t)continue; pages.add(t.page);
    const cur=pvCurOf(t.page); if(cur&&cur.id===p.id&&pvCanCancel(cur))continue;
    // Not its line's current verdict of the person's (a newer one came, or it was handled): no line marks it - the page's
    // draft does, so what this says is true.
    const pk=pre+'p'+t.page,pd=rdRead(d[pk]); delete d[k]; ch=true;
    d[pk]={...x,text:pd?pd.text+'\n'+x.text:x.text,base:'',rev:-1,mode:'add',folded:true,tried:[],from:''};}
  if(ch)rdSave(d);
  const shown=[...pages].filter(n=>n>0).sort((a,b)=>a-b); if(!shown.length)return; const first=shown[0];
  lineNote(tl('저장 안 된 이유 초안 {n}건 · 줄의 [초안 있음]이 엽니다 — {target}',{n:shown.length,target:pageTargetShort(first)}),NOTICE_KIND.INFO,
    {label:'보기',fn:()=>pvShowLine(first)},{literal:true,source:'reason-restore'});}
// Brings page `page`'s line into view and puts the focus on its draft's mark ('초안 있음') - before the saved reason, which
// comes first on the line and opens the popover too - else its reason control (pvFocusLine).
/** @param {number} page */
function pvShowLine(page){const l=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"]')); if(!l)return;
  const blk=/** @type {HTMLElement} */(l.parentElement||l); blk.scrollIntoView({block:blk.getBoundingClientRect().height<=$('#left').clientHeight?'center':'end'});
  requestAnimationFrame(()=>{const m=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"] .pv-draft'));
    if(m)m.focus({preventScroll:true}); else if(!pvFocusLine(page))searchToPage();});}
// A draft that changes a saved reason, opened again after its pin's note changed elsewhere: it knows the newer note at once
// - unless that note is its own lost write, landed (pvReasonRebase).
/** @param {ReasonSession} r @param {Pin} p */
function pvReasonSeeConflict(r,p){const note=String(p.note||''); pvReasonRebase(r,p);
  r.conflict=pvReasonEdits(r)&&note.trim()!==r.base.trim()?{note,rev:typeof p.rev==='number'?p.rev:-1}:null;}
// Closes the popover. Closed on purpose (back: Esc, Enter after its save, [닫기], [지우기], [접기]) the focus stays on its own
// page: on the line's reason control ([이유 추가], the saved reason, '초안 있음' - whichever the line shows now), else the
// pressed word, else the line's first word - never the PDF area, from which the next Tab went to the first page's line and
// scrolled the document there. Closed by moving on with the focus inside, the focus goes to the PDF area.
/** @param {boolean} back */
function pvReasonEnd(back){const r=PV_REASON,pop=document.querySelector('#doc .pv-pop'),had=!!pop&&pop.contains(document.activeElement);
  PV_REASON=null; drawPageVerdicts(); if(!back){if(had)searchToPage(); return;}
  if(!r||!pvFocusLine(r.page))searchToPage();}
// Puts the focus on page `page`'s line: its reason control, else its pressed word, else its first word. Returns whether it did.
/** @param {number} page */
function pvFocusLine(page){const l=document.querySelector('#doc .pv[data-page="'+page+'"]'); if(!l)return false;
  const c=/** @type {HTMLElement|null} */(l.querySelector('[data-act="pv-reason-open"]')||l.querySelector('.vd-b[aria-pressed="true"]')||l.querySelector('.vd-b'));
  if(!c)return false; c.focus({preventScroll:true}); return true;}
// Moving on: the popover closes and what was typed is written as Enter would, said in one line; nothing unsaved just closes.
// One still waiting for its verdict's number (opened by Enter while the save was out) is kept with that save (PV_DETACHED):
// its text waits as its page's draft, and the save, when it answers, writes it on the verdict it made (pvReasonSettle).
function pvReasonLeave(){const r=PV_REASON; if(!r)return; pvReasonEnd(false);
  if(!r.id){const s=pvSlot(r.page,r.doc); if(r.text.trim()&&PV_BUSY.has(s)){r.escArm=''; rdKeep(r,true); PV_DETACHED.set(s,r);} return;}
  if(pvReasonDirty(r))pvReasonCommit(r,r.text.trim(),true);}
// The save on line `slot` answered - verdict pin id, or 0 when it failed: a popover moved away from while it was out is
// bound to that verdict and its text written there, on the document it was typed on, as moving on writes (said in one line);
// a failed save leaves the text as the page's draft ('초안 있음'), said.
/** @param {string} slot @param {number} id @param {string} key */
function pvReasonSettle(slot,id,key){const r=PV_DETACHED.get(slot); if(!r)return; PV_DETACHED.delete(slot);
  if(!id){lineNote(tl('판정 저장 실패 · 쓰던 이유는 이 쪽의 초안으로 남겼습니다 — {target}',{target:pvReasonName(r)}),NOTICE_KIND.WARN,null,{literal:true}); return;}
  rdMove(r.doc,'p'+r.page,id); Object.assign(r,{id,key,base:'',mode:'add',rev:-1,saveWhenBound:false,listed:false});
  pvReasonCommit(r,r.text.trim(),true);}
// Opens the popover on page `page`'s line for its current verdict - the person's own open one ([이유 추가], Enter, its saved
// reason, its kept draft): with that draft (unfolded), else the page's draft (moved to this verdict), else the saved reason
// to change. Another popover moves on first. A page's draft with no verdict of the person's to take it says so.
/** @param {number} page @param {boolean} focus */
function pvReasonOpen(page,focus){const cur=pvCurOf(page); if(viewerBlocked())return;
  if(PV_DETACHED.has(pvSlot(page))){pvReasonOpenPending(page); return;}   // its verdict's save is still out: that popover again
  if(!cur||!pvCanCancel(cur)){if(rdGet(DOC,'p'+page))lineNote(tl('이유를 붙일 내 판정이 없습니다 · 판정을 누르면 이 초안이 그 판정으로 갑니다 — {target}',{target:pageTargetShort(page)}),NOTICE_KIND.INFO,null,{literal:true,life:NOTICE_LIFE.TIMER}); return;}
  if(!(PV_REASON&&PV_REASON.id===cur.id&&pvReasonOn(page))){pvReasonLeave();
    if(!rdGet(DOC,cur.id))rdMove(DOC,'p'+page,cur.id);   // a page's draft goes to the verdict it now has
    const note=String(cur.note||''),d=rdGet(DOC,cur.id),rev=typeof cur.rev==='number'?cur.rev:-1;
    const r=d?pvReasonNew(page,cur.id,verdictOf(cur)||'',d.text,d.base,d.rev>=0?d.rev:rev,d.mode):pvReasonNew(page,cur.id,verdictOf(cur)||'',note,note,rev);
    if(d)r.tried=d.tried;   // its writes whose answer was lost: one may have landed
    r.listed=true; pvReasonSeeConflict(r,cur); PV_REASON=r; if(d&&d.folded)rdKeep(r);}
  PV_KEY_GUARD=false; hideTip(); drawPageVerdicts(); if(focus)pvReasonFocus();}
// Enter while page `page`'s save is still out (a fast typist: a key, then Enter at once): the Enter is the intent to write, so
// the popover opens now with the focus, bound to that pending verdict (id 0) - every key after it is text in the field,
// digits included, never a verdict key - and takes the verdict's number when the save answers (pvReasonAfterSave). A save
// that fails leaves the text as the page's draft (pvReasonUnbound).
/** @param {number} page */
function pvReasonOpenPending(page){const s=pvSlot(page),key=PV_BUSY.get(s)||''; if(PV_REASON&&pvReasonOn(page)){pvReasonFocus(); return;}
  pvReasonLeave(); const det=PV_DETACHED.get(s); PV_DETACHED.delete(s);   // moved away from earlier: the same popover, with its Enter
  const d=rdGet(DOC,'p'+page),r=det?Object.assign(det,{visit:captureVisit(),seen:pvReadingPage()===page}):pvReasonNew(page,0,key,d?d.text:'','',-1,'add');
  PV_REASON=r; PV_KEY_GUARD=false; hideTip(); drawPageVerdicts(); pvReasonFocus();}
// Page `page`'s save failed while a popover waited for its number: what was typed stays as the page's draft ('초안 있음'),
// said in one line, and the popover closes. As when a verdict is taken back while its reason is typed (pvReasonLost): when
// the field had the focus its line's draft mark takes it and the keys pressed next are not verdict keys (PV_KEY_GUARD) -
// a digit typed on would have saved a verdict; a focus elsewhere (the search, the composer) stays where it is.
/** @param {number} page */
function pvReasonUnbound(page){const r=PV_REASON; if(!r||r.id||r.page!==page||r.doc!==DOC)return;
  const pop=document.querySelector('#doc .pv-pop'),had=!!pop&&pop.contains(document.activeElement); PV_REASON=null;
  if(r.text.trim()){rdPut(r.doc,'p'+page,r.text,'',-1,{mode:'add',folded:true});
    lineNote(tl('판정 저장 실패 · 쓰던 이유는 이 쪽의 초안으로 남겼습니다 — {target}',{target:pageTargetShort(page)}),NOTICE_KIND.WARN,null,{literal:true});}
  drawPageVerdicts(); if(!had)return; PV_KEY_GUARD=true; if(!pvFocusLine(page))searchToPage();}
// Puts the focus in the open field, its caret at the end.
function pvReasonFocus(){const f=pvReasonField(); if(!f||f.disabled)return; f.focus({preventScroll:true}); const n=f.value.length; f.setSelectionRange(n,n);}
// A save on page `page`'s line made verdict pin id (savePageVerdict) in place of verdict pin prev (the line's current one
// before it, 0 for none). A popover open on that line follows it: its draft moves to the new verdict - never written on
// the one it replaced - and says where it goes now, keeping its field, focus and composition; an empty one stays open for
// the new verdict. A draft kept for prev without a popover (a failed write, a folded one) or for the page (a verdict taken
// back elsewhere) moves too, and the line marks it on the new verdict. A popover elsewhere, or one whose write is out,
// moves on. No save opens one: after a click the line offers [이유 추가]; after a key, 'Enter 이유 쓰기'.
// A change of a saved reason moves only the person's own text: the lines others added under it ('(추가 HH:MM) …', as the
// note held them) stay on the verdict they were written on and are not copied as the person's reason (pvReasonOwn); a
// change that leaves nothing of the person's own is no draft, and an unchanged one moves nothing.
// A reason ends on one verdict: while prev's reason write is out (PV_WRITES) its draft does not move - that write settles
// first (pvReasonOnto: written, or found landed, it stays prev's and the status line says so; not landed, the draft moves
// to the new verdict and prev's [다시 시도] goes). Moved at once, a write that landed or a [다시 시도] afterwards put the
// reason on both verdicts.
/** @param {number} page @param {number} id @param {string} key @param {boolean} kb @param {number} prev */
function pvReasonAfterSave(page,id,key,kb,prev){const r=PV_REASON; PV_LAST_SAVE=id; PV_KEY_SAVE=kb?id:0;
  if(r&&pvReasonOn(page)&&!r.writing){const own=pvReasonOwn(r),dirty=pvReasonDirty(r)&&!!own.trim(),from=r.id;
    if(dirty){r.text=own; rdDrop(r.doc,from||'p'+page); rdPut(DOC,id,own,'',-1,{mode:'add'});} else if(from)r.text='';   // an unbound popover keeps what is typed
    Object.assign(r,{id,key,base:'',mode:'add',rev:-1,conflict:null,from:dirty?from:0,saved:null,tried:[],clearTried:false,listed:false,escArm:''});
    if(r.saveWhenBound){r.saveWhenBound=false; const f=pvReasonField(); if(f)setTimeout(()=>pvReasonSave(f),0);}   // its Enter came before the number
    return;}
  if(PV_DETACHED.has(pvSlot(page)))return;   // its popover was moved away from: pvReasonSettle writes it; the open one stays
  const o=prev?PV_WRITES.get(rdName(DOC,prev)):null;
  if(o){const w=o.r; w.onto=id; o.w.then(ok=>pvReasonOnto(w,ok,page));}   // its write settles first
  else if(!(prev&&rdMove(DOC,prev,id)))rdMove(DOC,'p'+page,id);
  pvReasonLeave();}
// The text of reason session r that is the person's own: the field's text, less - when it changes a saved reason - the
// stamped lines others added under it ('(추가 HH:MM) …') as the saved note held them. (A new reason's text is the field's,
// as typed.)
/** @param {ReasonSession} r */
function pvReasonOwn(r){if(!pvReasonEdits(r))return r.text; const st=/^\(추가 \d{1,2}:\d{2}\) /,theirs=new Set(r.base.split(/\r?\n/).filter(l=>st.test(l)));
  return r.text.split('\n').filter(l=>!(st.test(l.replace(/\r$/,''))&&theirs.has(l.replace(/\r$/,'')))).join('\n');}
// The write of reason session r, out while its line's verdict changed to r.onto (pvReasonAfterSave), settled - ok: it was
// written. Its reason ends on one verdict. Written - or, its answer lost or a 5xx, found landed when the pin is read again
// (pvReasonLanded) - it stays on r's verdict, now an earlier one, and the status line says so ('이유는 이전 판정 #15 채택에
// 저장됨 · 지금 판정은 #16 보류'). Not landed (also refused, or the pin gone), its draft moves to the new verdict - or to the
// page's draft, when that verdict is no longer the line's or already has a draft or a popover - its failure and that
// [다시 시도] go, and the status line says where it went with [보기]. A read that fails decides nothing: the status line
// says so with [다시 시도], which reads again. (pvReasonWrite and pvReasonFailed say nothing of such a write themselves.)
/** @param {ReasonSession} r @param {boolean} ok @param {number} page */
async function pvReasonOnto(r,ok,page){const to=r.onto,doc=r.doc,src='POST /api/pins/'+r.id+'/edit reason'; if(!to)return;
  const target=pvNameOn(doc,page,r.id),word=verdictLabel(r.key,doc);
  const saved=()=>{r.onto=0; const now=pvCurOn(doc,page),nk=now?verdictOf(now):null;
    lineNote(now&&nk&&now.id!==r.id?tl('이유는 이전 판정 #{id} {word}에 저장됨 · 지금 판정은 #{cur} {now} — {target}',{id:r.id,word,cur:now.id,now:verdictLabel(nk,doc),target})
      :tl('이유 저장됨 · 판정 #{id} {word} — {target}',{id:r.id,word,target}),NOTICE_KIND.OK,null,{literal:true,life:NOTICE_LIFE.TIMER});};
  if(ok){saved(); return;}
  let p=/** @type {Pin|null|undefined} */(undefined);
  try{p=(await api('/api/pins/'+r.id,{what:'핀 읽기',silent:true})).data.pin;}
  catch(e){const x=/** @type {ApiError} */(e); if(!x||!x.status||x.status>=500){
      lineNote(tl('이유 저장 실패 · {why} — {target}',{why:tr('서버에 닿지 않습니다'),target}),NOTICE_KIND.ERR,{label:'다시 시도',fn:()=>pvReasonOnto(r,false,page)},{source:src,literal:true});
      return;}
    p=null;}
  const got=p&&!p.dropped_at?[...r.tried].reverse().find(a=>pvReasonLanded(a,/** @type {Pin} */(p))):null;
  if(got){r.saved=got.text; r.tried=[]; rdDrop(doc,r.id); sourceOk(src); saved(); if(doc===DOC)loadPins().catch(()=>{}); return;}
  r.onto=0; r.tried=[]; sourceOk(src); const d=rdGet(doc,r.id),text=d?d.text:r.text; rdDrop(doc,r.id); if(!text.trim())return;
  const open=!!PV_REASON&&PV_REASON.doc===doc&&PV_REASON.page===page,cur=pvCurOn(doc,page);
  if(cur&&cur.id===to&&!open&&!rdGet(doc,to))rdPut(doc,to,text,'',-1,{mode:'add',folded:true});
  else{const pd=rdGet(doc,'p'+page); rdPut(doc,'p'+page,pd?pd.text+'\n'+text:text,'',-1,{mode:'add',folded:true});}
  lineNote(tl('판정 #{id} 이유는 저장되지 않아 지금 판정의 초안으로 옮겼습니다 · 줄의 [초안 있음]이 엽니다 — {target}',{id:r.id,target}),NOTICE_KIND.WARN,
    doc===DOC?{label:'보기',fn:()=>pvShowLine(page)}:null,{literal:true,source:'reason-onto'});
  if(doc===DOC)drawPageVerdicts();}
// A take-back of verdict pin id about page `page` of document doc failed (pvCancelPin): the verdict is back. Its reason
// popover left with it (kept: that session, or null) and comes back with its text while nothing took its place: no other
// popover open (a newer session: another page's, the earlier verdict's the line showed meanwhile, a new verdict's, also one
// still waiting for its verdict's number), the same document and visit, and the verdict is its line's current one again (a
// save out on the line then moves it to the new verdict, pvReasonAfterSave - unless its own write is out too). Otherwise
// what was typed - kept as the verdict's draft when it left (pvCancelPin) - is never let go without a word
// (pvReasonUncancelDraft).
/** @param {number} id @param {number} page @param {string|null} doc @param {ReasonSession|null} kept */
function pvReasonUncancel(id,page,doc,kept){const cur=pvCurOn(doc,page),back=!!cur&&cur.id===id;
  if(PV_REASON&&PV_REASON.id===id)return;   // opened again meanwhile (its line's '초안 있음' came back with it)
  if(kept&&back&&!PV_REASON&&doc===DOC&&currentVisit(kept.visit)&&!(kept.writing&&PV_BUSY.has(pvSlot(page,doc)))){PV_REASON=kept; drawPageVerdicts(); return;}
  pvReasonUncancelDraft(id,page,doc,!!kept);}
// Where the draft of verdict pin id, back but perhaps no longer current (its take-back failed, or a [되돌리기] restored it
// under a newer verdict), waits - decided once nothing can still change it: a write of its
// reason that is out settles first (PV_WRITES: written, there is nothing left to keep; failed, it is the draft again), and a
// save out on its line answers first (PV_UNCANCEL, pvReasonUncancelSettle: that save decides whether the verdict is still
// its line's current one). When the verdict is its line's current one it waits there as its draft; when a newer verdict
// was saved on the line it would wait on no line (a line marks its current verdict's draft only), so it becomes the page's
// draft, which goes to the verdict it is opened on (pvReasonOpen; joined under a page's draft waiting there already), and
// remembers its key (from): a [다시 시도] of the old write that lands later takes it away (rdWrittenOff). Either way the line
// marks it '초안 있음' and the status line says so with [보기] (its line in view, the focus on the mark, pvShowLine) - a
// warning after the take-back's own failure, which stands first with its [다시 시도]. shown: a popover was displaced. A draft
// kept for the verdict without one (folded, or a failed write) moves the same way and is said too; one that stays on its
// verdict's line, where it was before, is not.
const PV_UNCANCEL=/** @type {Map<string,{id:number,page:number,doc:string|null,shown:boolean}>} */(new Map());
/** @param {number} id @param {number} page @param {string|null} doc @param {boolean} shown */
function pvReasonUncancelDraft(id,page,doc,shown){const o=PV_WRITES.get(rdName(doc,id));
  if(o){o.w.then(()=>pvReasonUncancelDraft(id,page,doc,shown)); return;}
  const s=pvSlot(page,doc); if(PV_BUSY.has(s)){const u=PV_UNCANCEL.get(s); PV_UNCANCEL.set(s,{id,page,doc,shown:shown||(!!u&&u.id===id&&u.shown)}); return;}
  if(PV_REASON&&PV_REASON.id===id)return;
  const cur=pvCurOn(doc,page),back=!!cur&&cur.id===id,d=rdGet(doc,id); if(!d||(back&&!shown))return;
  if(!back){const pd=rdGet(doc,'p'+page); rdDrop(doc,id); rdPut(doc,'p'+page,pd?pd.text+'\n'+d.text:d.text,'',-1,{mode:'add',folded:true,from:rdName(doc,id)});}
  const target=pvNameOn(doc,page,id);
  lineNote(back?tl('판정 #{id} 이유는 초안으로 남겼습니다 · 줄의 [초안 있음]이 엽니다 — {target}',{id,target})
    :tl('판정 #{id} 이유는 이 쪽의 초안으로 남겼습니다 · 줄의 [초안 있음]이 엽니다 — {target}',{id,target}),
    NOTICE_KIND.WARN,doc===DOC?{label:'보기',fn:()=>pvShowLine(page)}:null,{literal:true,source:'reason-uncancel'});
  if(doc===DOC)drawPageVerdicts();}
// The save on line `slot` answered (savePageVerdict, after it bound or kept a popover waiting for it): a failed take-back's
// draft that waited for it is placed now.
/** @param {string} slot */
function pvReasonUncancelSettle(slot){const u=PV_UNCANCEL.get(slot); if(!u)return; PV_UNCANCEL.delete(slot); pvReasonUncancelDraft(u.id,u.page,u.doc,u.shown);}
// [되돌리기] brought verdict pin id back (a cancel's, the save chip's): its kept draft opens again on its line, without the
// focus - only while it is that line's current verdict (a newer verdict of someone else's keeps the line; verdict.js says so).
/** @param {number} id */
function pvReasonRevive(id){const d=rdGet(DOC,id),p=pvReasonPin(id); if(!d||!p||(PV_REASON&&PV_REASON.id===id))return;
  const t=pageTargetOf(p,META?META.kind:undefined); if(!t)return; const cur=pvCurOf(t.page); if(!cur||cur.id!==id)return; pvReasonLeave();
  const r=pvReasonNew(t.page,id,verdictOf(p)||'',d.text,d.base,d.rev,d.mode); r.tried=d.tried; r.listed=true; pvReasonSeeConflict(r,p); PV_REASON=r; drawPageVerdicts();}

// ---------------- Writing
// The one write of reason session r: text as its pin's note (pvReasonWrite). While a write is out it is that write - Enter
// and then moving on, another save or another document before the answer start no second one - and text the session has
// written is not written again. A failed write may be tried again. Resolves with whether the reason is written; once it
// is, its kept draft goes (unless more was typed meanwhile), so does a copy of it moved off the pin's key meanwhile
// (rdWrittenOff), and its lost writes are settled. The write is listed while it is out (PV_WRITES, with its session): a
// draft is not moved off the key it may still be written for (pvReasonUncancelDraft, pvReasonAfterSave).
const PV_WRITES=/** @type {Map<string,{r:ReasonSession,w:Promise<boolean>}>} */(new Map());
/** @param {ReasonSession} r @param {string} text @param {boolean} said @returns {Promise<boolean>} */
function pvReasonCommit(r,text,said){if(r.saved===text)return Promise.resolve(true);
  if(!r.writing){const k=rdName(r.doc,r.id);
    const w=pvReasonWrite(r,text,said).then(ok=>{r.writing=null; const o=PV_WRITES.get(k); if(o&&o.w===w)PV_WRITES.delete(k);
      if(ok){r.saved=text; r.tried=[]; const d=rdGet(r.doc,r.id); if(d&&d.text.trim()===text)rdDrop(r.doc,r.id); rdWrittenOff(r.doc,r.id,text);} return ok;});
    r.writing=w; PV_WRITES.set(k,{r,w});}
  return r.writing;}
// [다시 시도] on a failed reason: the session's draft as it is now (after a failed Enter the field stays open and may have been
// corrected) written as its one write. A field still open for it waits while it writes, and closes only when what was
// written is what it holds.
/** @param {ReasonSession} r */
function pvReasonRetry(r){const text=r.text.trim(); if(!text||r.writing)return;
  const w=pvReasonCommit(r,text,true); if(PV_REASON===r)drawPageVerdicts();
  w.then(ok=>{if(PV_REASON!==r)return; if(ok&&r.text.trim()===text)pvReasonEnd(false); else drawPageVerdicts();});}
// Where lost write a's text sits in note when the note is what a made of the one it was sent against - its pre, its stamp,
// its text, its post - with nothing after but lines added under it since (a later note_append's '\n(추가 …', or an agent's
// '\r\n' one): the text's [start, end], else null.
/** @param {ReasonTry} a @param {string} note @returns {number[]|null} */
function pvReasonTryAt(a,note){if(!note.startsWith(a.pre))return null; let i=a.pre.length;
  if(a.stamp){const m=/^\(추가 \d{1,2}:\d{2}\) /.exec(note.slice(i)); if(!m)return null; i+=m[0].length;}
  const end=i+a.text.length; if(note.slice(i,end)!==a.text||note.slice(end,end+a.post.length)!==a.post)return null;
  const rest=note.slice(end+a.post.length); return !rest||/^\r?\n/.test(rest)?[i,end]:null;}
// Whether lost write a landed, from pin p as the server reads now. Every reason write is sent against the rev it read
// (base_rev), so a write lands only as the change right after that rev, or never - a copy still on its way meets a 409 once
// anything else changed the pin. So: p's rev not past a.rev - it has not landed (a write to try again, against that same rev:
// one of the two lands at most); past it, it landed when the note is what it made (pvReasonTryAt) and, when that was the only
// change since, the change was this person's (edited_by) - someone's note that happens to read the same is not this write.
// Text the note held already - someone's, or the person's own earlier line - is no sign of it: a reason repeated is a new
// one. (Two or more changes since leave the note to say it: someone writing the very same text under the same note in that
// window would read as this write.)
/** @param {ReasonTry} a @param {Pin} p */
function pvReasonLanded(a,p){const rev=typeof p.rev==='number'?p.rev:0;
  return rev>a.rev&&!!pvReasonTryAt(a,String(p.note||''))&&(rev>a.rev+1||isMe(p.edited_by));}
// The edit that writes text into pin p's note for session r, with what it makes of the note (kept as a lost write when its
// answer is lost) - or null when p holds it already; p read from the server just before. Replace mode is the whole note
// against the rev it was read at (r.rev) - never p's later one, which would write over a note changed meanwhile without the
// server's 409 - also over an empty note the person chose to write over. A new one is sent against p's rev, a note_append
// too (pvReasonLanded). After a write whose answer was lost (r.tried) the newest one that landed is the reason: its very
// text is saved already, and a corrected draft takes its place (a corrected reason, not a second one); lost writes that can
// no longer land (sent against an older rev, not landed) are let go. Otherwise the text goes into an empty note, or under the
// note someone wrote (note_append).
/** @param {ReasonSession} r @param {string} text @param {Pin} p @returns {{body:Record<string, unknown>,sent:ReasonTry|null}|null} */
function pvReasonBody(r,text,p){const note=String(p.note||''),rev=typeof p.rev==='number'?p.rev:0;
  if(pvReasonEdits(r)){const at=r.rev>=0?r.rev:rev; return note.trim()===text?null:{body:{note:text,base_rev:at},sent:{text,rev:at,pre:'',stamp:false,post:''}};}
  const got=[...r.tried].reverse().find(a=>pvReasonLanded(a,p)); r.tried=r.tried.filter(a=>a===got||a.rev>=rev);
  const at=got?pvReasonTryAt(got,note):null;
  if(got&&at){if(got.text===text)return null; const pre=note.slice(0,at[0]),post=note.slice(at[1]);
    return {body:{note:pre+text+post,base_rev:rev},sent:{text,rev,pre,stamp:false,post}};}
  if(!note.trim())return {body:{note:text,base_rev:rev},sent:{text,rev,pre:'',stamp:false,post:''}};
  return {body:{note_append:text,base_rev:rev},sent:{text,rev,pre:note+'\n',stamp:true,post:''}};}
const NOTE_APPEND_LIMIT=2000,NOTE_LIMIT=4000;   // the server's (pins/editing): a note_append, a whole note
// Why edit body b would be refused for its length - said instead of sending it, the draft kept - or ''.
/** @param {Record<string, unknown>} b */
function pvReasonTooLong(b){const a=b.note_append,n=b.note,f=(/** @type {number} */x)=>x.toLocaleString('en-US');
  if(typeof a==='string'&&a.length>NOTE_APPEND_LIMIT)return tl('덧붙일 이유는 {max}자까지입니다(지금 {len}자)',{max:f(NOTE_APPEND_LIMIT),len:f(a.length)});
  if(typeof n==='string'&&n.length>NOTE_LIMIT)return tl('메모는 {max}자까지입니다(지금 {len}자)',{max:f(NOTE_LIMIT),len:f(n.length)});
  return '';}
// Writes text as reason session r's pin's note. The pin is read from the server first (a list read a while ago may hold a
// note someone has emptied, which would add a stamped line to an empty note, or not hold one written since); a note someone
// wrote meanwhile is kept and a new reason is added to it (note_append), while a replace that finds the note changed since it
// was read is not written over theirs (pvReasonConflict). A pin that is gone takes nothing. said: the status line says it was
// saved (moving on, a draft that moved to a new verdict), with the verdict it went to. Each 409 - the pin changed since it
// was read - brings the pin as it is, and the edit is made again from it, up to PV_REASON_409 times. A write whose answer is
// lost (or a 5xx) is kept with what it made of the note (r.tried): the next write knows from the pin whether it landed. A
// failure is said by pvReasonFailed. Returns whether it was written.
const PV_REASON_409=3;
// A change of a saved reason (session r) whose write landed though its answer was lost - pin p's rev past the one it was
// sent against and its note exactly what it wrote (pvReasonLanded): the note r changes is that one now, at p's rev. The
// person's own text is never shown back as a note changed elsewhere ('지금 메모'), and the next Enter writes over it at
// once. Returns whether it did.
/** @param {ReasonSession} r @param {Pin} p */
function pvReasonRebase(r,p){if(!pvReasonEdits(r)||!r.tried.length)return false; const note=String(p.note||'');
  const got=[...r.tried].reverse().find(a=>note===a.pre+a.text+a.post&&pvReasonLanded(a,p)); if(!got)return false;
  r.base=note; r.rev=typeof p.rev==='number'?p.rev:r.rev; r.tried=[]; r.conflict=null; return true;}
/** @param {ReasonSession} r @param {string} text @param {boolean} said @returns {Promise<boolean>} */
async function pvReasonWrite(r,text,said){if(viewerBlocked())return false;
  let p; try{p=(await api('/api/pins/'+r.id,{what:'핀 읽기',silent:true})).data.pin;}
  catch(e){const x=/** @type {ApiError} */(e); if(!x||!x.status||x.status>=500){pvReasonFailed(r,text,x); return false;} p=undefined;}
  if(!p||p.dropped_at){if(!PV_WITHDRAWN.has(r.id))lineNote(tl('핀 #{id} 은 그사이 다른 곳에서 지워졌습니다',{id:r.id}),NOTICE_KIND.WARN); return false;}
  pvReasonRebase(r,p);   // its own lost write, landed, is the note it changes now
  if(pvReasonEdits(r)&&String(p.note||'').trim()!==r.base.trim()&&String(p.note||'').trim()!==text){pvReasonConflict(r,text,p); return false;}   // changed since it was read: never sent
  const url='/api/pins/'+r.id+'/edit',o={method:'POST',intent:'reason',silent:true};   // silent: pvReasonFailed says a failure, with its target
  let sent=/** @type {ReasonTry|null} */(null);   // the write out now, while its answer is awaited
  try{for(let n=1;;n++){const b=pvReasonBody(r,text,p); if(!b)break;
      const long=pvReasonTooLong(b.body); if(long){pvReasonFailed(r,text,null,long); return false;}
      sent=b.sent; const {status,data}=await api(url,{...o,body:b.body,expect:n<PV_REASON_409?[409]:[]}); sent=null;
      if(status!==409)break;
      const q=data&&data.pin;   // someone changed the pin meanwhile: their note stays
      if(!q){pvReasonFailed(r,text,null,tr('그사이 다른 곳에서 메모가 바뀌었습니다')); return false;}
      if(pvReasonEdits(r)){pvReasonRebase(r,q); if(String(q.note||'').trim()!==r.base.trim()){pvReasonConflict(r,text,q); return false;}
        r.rev=typeof q.rev==='number'?q.rev:r.rev;}   // only something else changed (a claim, the assignee): the note is the one it was read at
      p=q;}
  }catch(e){const x=/** @type {ApiError} */(e); if(sent&&(!x||!x.status||x.status>=500))r.tried.push(sent);   // it may have landed
    pvReasonFailed(r,text,x); return false;}
  r.conflict=null; sourceOk('POST /api/pins/'+r.id+'/edit reason');   // a failure this write answers goes (also when nothing had to be sent)
  if(r.onto){/* its line's verdict changed meanwhile: pvReasonOnto says where it is */}
  else if(said)lineNote(tl('이유 저장됨 · 판정 #{id} {word} — {target}',{id:r.id,word:verdictLabel(r.key,r.doc),target:pvReasonName(r)}),NOTICE_KIND.OK,null,{life:NOTICE_LIFE.TIMER,literal:true});   // result first: the folded line shows it
  else quietNote(tl('판정 #{id} 이유를 저장했습니다',{id:r.id}));
  if(r.doc===DOC)loadPins().catch(()=>{});
  return true;}
// What a reason session's verdict is about, by a short name for the status line: its page's target while its document is on
// screen ('PL16'), else its document's name.
/** @param {ReasonSession} r */
function pvReasonName(r){return pvNameOn(r.doc,r.page,r.id);}
// The same for verdict pin id (0 while it has none) about page `page` of document doc.
/** @param {string|null} doc @param {number} page @param {number} id */
function pvNameOn(doc,page,id){if(doc===DOC)return pageTargetShort(page); const d=doc?docInfo(doc):null; return d&&d.name||(id?'#'+id:tl('{page}쪽',{page}));}
// A reason that could not be written, said on the status line result first ('이유 저장 실패 · 서버에 닿지 않습니다 — PL16') in
// place of api()'s line, keyed by the request as api() keys it (a later answer from it clears it). The draft is kept
// whatever failed (rdPut, with its lost writes) and the line marks it - or the copy moved off the pin's key meanwhile is
// (rdMovedOff); unless the server refused it (a 4xx would refuse again) or it is too long
// (why: said before sending) the message offers [다시 시도], which writes the session's draft (pvReasonRetry). Stays until
// [x] or its action (STICKY). (A write without an answer is remembered by pvReasonWrite, r.tried: it may have landed.) The
// reason for a pin this person has withdrawn meanwhile goes quietly (PV_WITHDRAWN).
/** @param {ReasonSession} r @param {string} text @param {ApiError|null} e @param {string} [why0] */
function pvReasonFailed(r,text,e,why0){const st=e&&typeof e.status==='number'?e.status:0,again=!why0&&(!st||st>=500);
  if(!rdMovedOff(r.doc,r.id).length)rdPut(r.doc,r.id,r.text.trim()?r.text:text,r.base,r.rev,{mode:r.mode,tried:r.tried});   // moved off meanwhile: that copy is the draft
  if(PV_WITHDRAWN.has(r.id)||r.onto)return;   // withdrawn, or its line's verdict changed meanwhile (pvReasonOnto decides)
  const why=why0||(st?(e&&e.data&&errText(e.data))||'HTTP '+st:tr('서버에 닿지 않습니다'));
  lineNote(tl('이유 저장 실패 · {why} — {target}',{why,target:pvReasonName(r)}),NOTICE_KIND.ERR,again?{label:'다시 시도',fn:()=>pvReasonRetry(r)}:null,
    {source:'POST /api/pins/'+r.id+'/edit reason',literal:true});
  if(PV_REASON!==r&&r.doc===DOC)drawPageVerdicts();}   // the line marks the draft it keeps
// A replace found the note changed elsewhere since it was read (newer note q): nothing is written over it. The draft is kept,
// the popover - when open - shows the newer note whole and offers [그 위에 쓰기] (pvReasonReapply); every further 409 shows
// the note it found. The status line says so, result first, with [메모 보기] (the pin's card), and the line is read again so
// it shows the newer note too.
/** @param {ReasonSession} r @param {string} text @param {Pin} q */
function pvReasonConflict(r,text,q){r.conflict={note:String(q.note||''),rev:typeof q.rev==='number'?q.rev:-1};
  if(!rdMovedOff(r.doc,r.id).length)rdPut(r.doc,r.id,r.text.trim()?r.text:text,r.base,r.rev,{mode:r.mode,tried:r.tried});
  if(!r.onto)lineNote(tl('이유 저장 안 함 · 그사이 다른 곳에서 메모가 바뀌었습니다 — {target}',{target:pvReasonName(r)}),NOTICE_KIND.WARN,{label:'메모 보기',fn:()=>gotoPinRef(r.id)},
    {source:'POST /api/pins/'+r.id+'/edit reason',literal:true});
  if(r.doc===DOC){if(PV_REASON===r)pvRefill(r.page); loadPins().catch(()=>{});}}
// [그 위에 쓰기] in a popover that shows a newer note: the person has read it and puts their text over it - a replace, made
// from that note and written against its rev (also when it is empty: never an append that needs no rev).
function pvReasonReapply(){const r=PV_REASON,f=pvReasonField(); if(!r||!r.conflict||!f||r.writing)return;
  r.base=r.conflict.note; r.rev=r.conflict.rev; r.mode='replace'; r.conflict=null; rdKeep(r); if(!pvReasonDirty(r)){pvRefill(r.page); return;} pvReasonSave(f);}
// Enter (or [저장]): the text written as the note and the popover closed. Empty is a skip - a saved reason stays - and the
// reason as it is saved has nothing to write. While the request is out the field waits (disabled, the popover says
// '저장 중…'); a failure leaves the text in it for another Enter.
/** @param {HTMLTextAreaElement} f */
async function pvReasonSave(f){const r=PV_REASON; if(!r||r.writing||f.disabled)return; r.text=f.value; const text=r.text.trim();
  if(!r.id){if(text){r.saveWhenBound=true; rdKeep(r); pvRefill(r.page);} return;}   // its verdict has no number yet: saved once it has
  if(!text||text===r.base.trim()){rdDrop(r.doc,r.id||'p'+r.page); pvReasonEnd(true); return;}
  if(r.conflict){pvRefill(r.page); pvReasonFocus(); return;}   // the newer note is on screen: [그 위에 쓰기] or [메모 보기] first
  const w=pvReasonCommit(r,text,!!r.from); f.disabled=true; pvRefill(r.page); const ok=await w;
  if(PV_REASON!==r)return;   // closed meanwhile (moved on, the undo, another document): its one write had the text
  if(ok){pvReasonEnd(true); return;}
  drawPageVerdicts(); pvReasonFocus();}
// Esc in the field, or [닫기] (how 'btn'): with nothing unsaved the popover closes. With text the first press lets the focus
// go to the PDF area - the keys then change the verdict, the draft following - and says that the next one drops it; the
// next one drops it (the kept draft too).
/** @param {string} how */
function pvReasonEsc(how){const r=PV_REASON; if(!r)return;
  if(!pvReasonDirty(r)){rdDrop(r.doc,r.id||'p'+r.page); pvReasonEnd(true); return;}
  if(!r.escArm){r.escArm=how; if(how==='key')searchToPage(); pvRefill(r.page);
    announce(how==='key'?tr('Esc 한 번 더 누르면 이 이유를 버립니다'):tr('[닫기]를 한 번 더 누르면 이 이유를 버립니다')); return;}
  rdDrop(r.doc,r.id||'p'+r.page); pvReasonEnd(true); announce(tl('판정 #{id} 이유를 버렸습니다',{id:r.id}));}
// [접기]: the popover folds away, nothing written - over the plot it hid what the reason is about. The draft stays kept, folded
// (a reload leaves it folded), and the line marks it '초안 있음', which opens it again and takes the focus. Moving on writes
// nothing: a folded draft waits for the person.
function pvReasonFold(){const r=PV_REASON; if(!r||r.writing)return; if(pvReasonDirty(r))rdKeep(r,true); else rdDrop(r.doc,r.id);
  PV_REASON=null; drawPageVerdicts();
  const c=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+r.page+'"] [data-act="pv-reason-open"]'));
  if(c)c.focus({preventScroll:true}); else pvFocusLine(r.page);
  announce(tr('이유 초안을 접었습니다 — 줄의 [초안 있음]이 다시 엽니다'));}
// [지우기]: the saved reason goes - the note emptied against the rev the popover read it at - and the status line offers
// [되돌리기], which writes it back. The popover and its draft stay until the server says it is done. A [지우기] whose answer was
// lost may have landed: the next one reads the note first, and an empty note is the clear done. A failure keeps both (the
// status line says it, with [다시 시도] when the server was not reached or failed - 5xx), and a note changed elsewhere
// meanwhile is not cleared (pvReasonConflict).
async function pvReasonClear(){const r=PV_REASON; if(!r||r.writing||viewerBlocked()||!pvReasonEdits(r))return;
  if(r.conflict){pvRefill(r.page); return;}
  const old=r.base,target=pvReasonName(r),word=verdictLabel(r.key),url='/api/pins/'+r.id+'/edit',o={method:'POST',intent:'reason',silent:true,expect:[409]};
  const go=async()=>{try{
      if(r.clearTried){const p=(await api('/api/pins/'+r.id,{what:'핀 읽기',silent:true})).data.pin; if(p&&!String(p.note||'').trim())return 'ok';}
      const {status,data}=await api(url,{...o,body:{note:'',base_rev:r.rev}}); if(status!==409)return 'ok';
      const q=data&&data.pin; if(!q)return 'gone';
      if(!String(q.note||'').trim())return 'ok';   // empty already: the clear that lost its answer landed
      if(String(q.note||'').trim()!==r.base.trim()){pvReasonConflict(r,r.text,q); return 'conflict';}
      await api(url,{...o,expect:[],body:{note:'',base_rev:q.rev}}); return 'ok';}
    catch(e){const x=/** @type {ApiError} */(e),st=x&&typeof x.status==='number'?x.status:0; if(!st)r.clearTried=true;
      lineNote(tl('이유 지우기 실패 · {why} — {target}',{why:st?(x.data&&errText(x.data))||'HTTP '+st:tr('서버에 닿지 않습니다'),target}),NOTICE_KIND.ERR,
        !st||st>=500?{label:'다시 시도',fn:()=>{if(PV_REASON===r)pvReasonClear();}}:null,{source:'POST '+url+' reason',literal:true});
      return 'fail';}};
  const w=go(); r.writing=w.then(x=>x==='ok'); rdKeep(r); pvRefill(r.page);
  const res=await w; r.writing=null;
  if(res==='ok'){sourceOk('POST '+url+' reason'); rdDrop(r.doc,r.id); if(PV_REASON===r)pvReasonEnd(true);
    lineNote(tl('판정 #{id} {word} 이유 지움 — {target}',{id:r.id,word,target}),NOTICE_KIND.OK,{label:'되돌리기',tip:T.undo,wait:true,fn:()=>pvReasonUnclear(r.id,old)},
      {life:NOTICE_LIFE.TIMER,undo:true,literal:true});}
  else if(PV_REASON===r){drawPageVerdicts(); pvReasonFocus();}
  if(r.doc===DOC)await loadPins();}
// The undo of [지우기]: the reason written back, unless someone wrote a note meanwhile.
/** @param {number} id @param {string} old @returns {Promise<boolean>} */
async function pvReasonUnclear(id,old){let ok=false;
  try{const p=(await api('/api/pins/'+id,{what:'핀 읽기',where:NOTICE_HOST.LINE})).data.pin;
    if(p&&!String(p.note||'').trim()){await api('/api/pins/'+id+'/edit',{method:'POST',body:{note:old,base_rev:p.rev},intent:'reason',what:'이유 되돌리기',where:NOTICE_HOST.LINE}); ok=true;}}
  catch(e){}
  await loadPins(); return ok;}

// ---------------- The popover and the line's reason
// What the popover says of its draft: '저장 중…' while it writes, '저장됨' with a check when its text is the saved reason, '저장 안 됨'
// when it is not written yet, nothing when empty.
/** @param {ReasonSession} r @returns {{text:string,cls:string}} */
function pvReasonState(r){if(r.writing||r.saveWhenBound)return {text:tr('저장 중…'),cls:'busy'}; const t=r.text.trim(); if(!t)return {text:'',cls:''};
  return t===r.saved||t===r.base.trim()?{text:tr('저장됨'),cls:'ok'}:{text:tr('저장 안 됨'),cls:'warn'};}
// What the keys do now, under the field: with a fine pointer and the focus in it, Enter saves (and with nothing typed Esc
// closes); after a first Esc, what the second does. With touch only the second press of [닫기] is said. The digits are not
// mentioned: in the field they are text.
/** @param {ReasonSession} r @param {boolean} focused */
function pvReasonHint(r,focused){const fine=matchMedia('(pointer:fine)').matches;
  if(r.escArm==='btn')return tr('[닫기]를 한 번 더 누르면 이 이유를 버립니다');
  if(!fine)return '';
  if(r.escArm)return tr('Esc 한 번 더 누르면 이 이유를 버립니다');
  if(!focused)return '';
  return r.text.trim()?tr('Enter 저장'):tr('Enter 저장')+' · '+tr('Esc 닫기');}
// The popover on page `page`'s line while its session is open there (a person who may make a verdict): a labelled,
// non-modal group - the field, then one row: whose reason it is ('판정 #16 보류 이유', '판정 #16 보류 · 저장된 이유 수정' when it
// changes a saved one, '#15 채택에서 옮김' after a move), the draft's state, the keys, and [지우기] (a saved reason), [접기]
// (a draft, not while it is being written: the popover folds to the line's '초안 있음'), [닫기], [저장]. When a write found
// the note changed elsewhere, a row above the field shows that note whole (scrolling when long) with [메모 보기] and
// [그 위에 쓰기]. The keys' line is always there (aria-describedby never points at nothing), empty when there is nothing to
// say. The field is drawn empty; its text is put in after drawing (pvReasonAfterDraw), never as markup a redraw could put
// back under the caret or an input method.
/** @param {number} page */
function pvReasonPop(page){const r=pvReasonOn(page)&&canVerdict()?PV_REASON:null; if(!r)return '';
  const a=document.activeElement,focused=pvIsReasonField(a)&&a.dataset.id==='s'+r.sid,st=pvReasonState(r),hint=pvReasonHint(r,focused);
  const word=verdictLabel(r.key),who=!r.id?tl('{word} 판정 이유 · 판정 저장 중',{word}):pvReasonEdits(r)&&r.base.trim()?tl('판정 #{id} {word} · 저장된 이유 수정',{id:r.id,word}):tl('판정 #{id} {word} 이유',{id:r.id,word});
  const from=r.from?pvReasonPin(r.from):null,moved=r.from?tl('#{id} {word}에서 옮김',{id:r.from,word:verdictLabel(from&&verdictOf(from)||'')}):'';
  const cf=r.conflict?html`<div class="pv-pop-cf" role="alert"><span class="pv-pop-cf-t">${tr('그사이 다른 곳에서 메모가 바뀌었습니다 — 지금 메모')}</span>\
<div class="pv-pop-cf-note" translate="no" tabindex="0">${r.conflict.note||tr('(빈 메모)')}</div><span class="pv-pop-acts">\
<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-see">${tr('메모 보기')}</button>\
<button type="button" class="btn-sm hit" data-act="pv-reason-reapply" data-tip="${tr('바뀐 메모를 이 글로 바꿉니다')}">${tr('그 위에 쓰기')}</button></span></div>`:'';
  const desc=hint&&!r.writing?html` aria-describedby="pv-pop-h-${r.sid}"`:'';   // never pointing at a line that says nothing (while it writes)
  return html`<div class="pv-pop" role="group" data-id="s${r.sid}" aria-labelledby="pv-pop-to-${r.sid}"${desc}>${cf}\
<textarea class="pv-reason" rows="1" maxlength="4000" autocomplete="off" enterkeyhint="done" data-id="s${r.sid}" data-pin="${r.id}"${r.writing?html` disabled`:''} \
placeholder="${tr('이유 (선택)')}" aria-label="${tl('{who} (선택)',{who})}"${desc}></textarea>\
<div class="pv-pop-f"><span class="pv-pop-to" id="pv-pop-to-${r.sid}" translate="no">${who}${moved?html`<span class="pv-pop-from"> · ${moved}</span>`:''}</span>\
<span class="pv-pop-st${st.cls?' '+st.cls:''}" aria-live="polite">${st.cls==='ok'?ic('check'):''}${st.text}</span><span class="pv-pop-h" id="pv-pop-h-${r.sid}">${hint}</span>\
<span class="pv-pop-acts">${pvReasonEdits(r)&&r.base.trim()?html`<button type="button" class="btn-ghost btn-sm pv-pop-clear hit" data-act="pv-reason-clear" \
data-tip="${tr('저장한 이유를 지웁니다. 상태 줄의 [되돌리기]가 되살립니다')}">${tr('지우기')}</button>`:''}\
${pvReasonDirty(r)&&!r.writing&&r.id?html`<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-fold" data-tip="${tr('초안을 둔 채 접습니다. 줄의 [초안 있음]이 다시 엽니다')}">${tr('접기')}</button>`:''}\
<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-close" data-tip="${tr('닫습니다. 쓰던 이유가 있으면 한 번 더 눌러야 버립니다')}">${tr('닫기')}</button>\
<button type="button" class="btn-sm pv-pop-save hit" data-act="pv-reason-save"${r.writing||r.conflict?html` aria-disabled="true"`:''}>${tr('저장')}</button></span></div></div>`;}
// The reason on page `page`'s line, after its state: the saved reason of its current verdict (a check and its first line,
// .pv-rn) - a button that opens the popover to change it on the person's own open verdict, with a pencil and the name
// '저장된 이유 수정' -, then (.pv-ra) a kept draft not written yet ('초안 있음', which opens it: a folded popover, a failed
// write, a reload's other drafts, a page's draft whose verdict went) on any line, or the way to write one for the person's
// own open verdict without a reason - on the reading line and on the line of the last save (PV_LAST_SAVE): after a key save,
// while the keys act on the line (a mouse screen), 'Enter 이유 쓰기' (Enter opens it, pvReasonEnterKey); else [이유 추가] - a
// click save's, as before. The other lines
// keep their length. Every name holds the words the button shows. Nothing for the reason the open popover holds.
/** @param {number} page @param {Pin|undefined} cur */
function pvReasonInline(page,cur){const open=pvReasonOn(page)&&!!PV_REASON&&(!cur||PV_REASON.id===cur.id||!PV_REASON.id),pd=open?null:rdGet(DOC,'p'+page);
  const sep=html`<span class="pv-sep" aria-hidden="true">·</span>`;
  const mark=html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-draft hit" data-act="pv-reason-open" \
aria-label="${tr('초안 있음 — 저장 안 된 이유 초안, 누르면 이어 씁니다')}" data-tip="${tr('저장 안 된 이유 초안이 있습니다 — 누르면 이어 씁니다')}">${tr('초안 있음')}</button></span>`;
  if(!cur)return pd?mark:'';
  const mine=pvCanCancel(cur),note=String(cur.note||''),first=note.split('\n')[0];
  const d=open?null:rdGet(DOC,cur.id),draft=!!d&&d.text.trim()!==note.trim();
  const ok=html`<span class="pv-ok" aria-hidden="true">${ic('check')}</span>`;
  const saved=!note?'':mine&&!open?html`<span class="pv-rn">${sep}<button type="button" class="btn-ghost btn-sm pv-note hit" data-act="pv-reason-open" translate="no" \
aria-label="${tl('{note} — 저장된 이유 수정, 판정 #{id}',{id:cur.id,note:first})}" data-tip="${tr('저장된 이유 수정')}">${ok}<span class="pv-note-t">${first}</span>${ic('pencil')}</button></span>`
    :html`<span class="pv-rn">${sep}<span class="pv-note" translate="no"${open?'':html` data-tip="${note}"`}>${ok}${first}</span></span>`;   // open: no box over the popover
  const keys=PV_KEYS===page&&PV_KEY_SAVE===cur.id&&matchMedia('(pointer:fine)').matches;   // a key save: its line says the key
  const act=(draft||(pd&&!d))&&mine&&!open?mark:pd&&!mine?mark:!mine||open||note?'':PV_READ===page||PV_LAST_SAVE===cur.id
    ?keys?html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" data-act="pv-reason-open" aria-keyshortcuts="Enter" \
data-tip="${tr('이 판정의 이유를 씁니다. 메모로 붙습니다')}"><kbd class="pv-kbd">Enter</kbd> ${tr('이유 쓰기')}</button></span>`
      :html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" data-act="pv-reason-open" \
data-tip="${tr('이 판정의 이유를 씁니다. 메모로 붙습니다')}">${tr('이유 추가')}</button></span>`:'';
  return html`${saved}${act}`;}
// After a line is drawn (fillPv): the open field holds the session's text - put in only when it differs and no input method
// is composing - and its height follows its lines.
/** @param {HTMLElement} line */
function pvReasonAfterDraw(line){const r=PV_REASON,f=/** @type {HTMLTextAreaElement|null} */(line.querySelector('.pv-pop .pv-reason')); if(!r||!f)return;
  if(f.value!==r.text&&!PV_COMPOSING){const had=document.activeElement===f; f.value=r.text; if(had){const n=f.value.length; f.setSelectionRange(n,n);}}
  pvReasonGrow(f);}
// The field's height: its lines, up to its max-height (CSS), from one line.
/** @param {HTMLTextAreaElement} f */
function pvReasonGrow(f){f.style.height='auto'; f.style.height=Math.ceil(f.scrollHeight+(f.offsetHeight-f.clientHeight))+'px';}
// Page `page`'s line drawn again now: what its popover says follows the field's text and focus.
/** @param {number} page */
function pvRefill(page){const v=pageVerdictsOn(),e=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"]'));
  if(v&&e)fillPv(e,page,pageVerdictPins().get(page),v);}

// ---------------- Input
let PV_COMPOSING=false;   // an input method is composing in the reason field: its value is not put back
$('#doc').addEventListener('compositionstart',e=>{if(pvIsReasonField(e.target))PV_COMPOSING=true;});
$('#doc').addEventListener('compositionend',e=>{if(pvIsReasonField(e.target))PV_COMPOSING=false;});
// Every input keeps the draft (rdPut) and lets a first Esc go; the line follows its emptiness (the state).
$('#doc').addEventListener('input',e=>{const f=e.target; if(!pvIsReasonField(f))return; const r=PV_REASON; if(!r||f.dataset.id!=='s'+r.sid)return;
  r.text=f.value; r.escArm=''; rdKeep(r); pvReasonGrow(f); pvRefill(r.page);});
// Keys in the field: Enter saves (Shift+Enter is a new line), Esc closes or takes two presses with text. Every other key is
// the field's own - digits included. Nothing while an input method composes. Esc on the popover's buttons ([접기], [닫기],
// [저장], [지우기]) is the field's Esc: it did nothing there.
$('#doc').addEventListener('keydown',e=>{const t=/** @type {HTMLElement} */(e.target);
  if(e.key==='Escape'&&!pvIsReasonField(t)&&PV_REASON&&t&&t.closest&&t.closest('#doc .pv-pop')&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault(); e.stopPropagation(); hideTip(); pvReasonEsc('key'); return;}});
$('#doc').addEventListener('keydown',e=>{const f=e.target; if(!pvIsReasonField(f)||e.isComposing||e.keyCode===229)return;
  if(e.key==='Enter'&&!e.shiftKey&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault(); e.stopPropagation(); pvReasonSave(f); return;}
  if(e.key==='Escape'){e.preventDefault(); e.stopPropagation(); pvReasonEsc('key');}});
// While a popover is open, Tab and Shift+Tab keep to it and its line, from anywhere in either: past the last control (the
// popover's) the focus goes to the line's first, and before the first (the line's) to the popover's last. The DOM's next
// or previous stop is another page's line, whose focus scrolled the reading page away and closed the popover, writing what
// was being edited.
$('#doc').addEventListener('keydown',e=>{if(e.key!=='Tab'||e.ctrlKey||e.metaKey||e.altKey)return; const t=/** @type {HTMLElement} */(e.target),line=t&&t.closest?t.closest('#doc .pv'):null;
  const pop=line&&line.querySelector(':scope>.pv-pop'); if(!line||!pop)return;
  const vis=(/** @type {Element} */x)=>x instanceof HTMLElement&&x.getClientRects().length>0&&!(/** @type {HTMLButtonElement} */(x).disabled);
  const all=[...line.querySelectorAll('a,button,textarea,[tabindex="0"]')].filter(vis); if(all.length<2)return;
  if(!e.shiftKey&&t===all[all.length-1]){e.preventDefault(); /** @type {HTMLElement} */(all[0]).focus({preventScroll:true});}
  else if(e.shiftKey&&t===all[0]){e.preventDefault(); /** @type {HTMLElement} */(all[all.length-1]).focus({preventScroll:true});}});
// The field's focus changes what it says (the keys). The popover stays open while the focus is anywhere inside it - Tab
// from the field to its buttons included - and an empty one closes when the focus leaves it for somewhere else (a press
// on its own buttons never closes it, even where a press does not move the focus).
let PV_POP_DOWN=0;   // performance.now() of the last press inside a popover
$('#doc').addEventListener('pointerdown',e=>{const t=/** @type {HTMLElement} */(e.target); if(t&&t.closest&&t.closest('.pv-pop'))PV_POP_DOWN=performance.now();},true);
$('#doc').addEventListener('focusin',e=>{if(!pvIsReasonField(e.target)||!PV_REASON)return; PV_REASON.escArm=''; pvRefill(PV_REASON.page);});
$('#doc').addEventListener('focusout',e=>{const t=/** @type {HTMLElement} */(e.target),pop=t&&t.closest?t.closest('.pv-pop'):null; if(!pop)return;
  const rel=/** @type {Node|null} */(e.relatedTarget); if(rel&&pop.contains(rel))return;
  setTimeout(()=>{const r=PV_REASON; if(!r||pop.getAttribute('data-id')!=='s'+r.sid||!pop.isConnected||pop.contains(document.activeElement))return;
    const f=pvReasonField(); if(f&&!f.disabled&&!f.value.trim()&&!r.writing&&performance.now()-PV_POP_DOWN>600){pvReasonEnd(false); return;}
    pvRefill(r.page);},0);});
// The second Esc after a first one from the field (the focus is then on the PDF area): it drops the draft - unless something
// on top answers Esc first (a dialog, a popover, the composer, an edit or a reply).
/** @param {KeyboardEvent} e */
function pvReasonEscKey(e){if(e.key!=='Escape'||e.defaultPrevented||!PV_REASON||PV_REASON.escArm!=='key'||typingNow())return;
  if(document.querySelector('dialog[open]')||!$('#page-pop').hidden||!$('#doc-pop').hidden||!$('#composer').hidden||EDITOR.current||REPLY)return;
  e.preventDefault(); e.stopImmediatePropagation(); pvReasonEsc('key');}
document.addEventListener('keydown',pvReasonEscKey);
// Enter on the pages - the focus on the PDF area, the page itself or nothing - opens the reading page's reason popover with
// the focus, for the person's own open current verdict there ('Enter 이유 쓰기' on its line). A control's own Enter stays its
// own, and so does anything on top (a dialog, a popover, the composer, an edit or a reply). Not while the pages are still
// gliding to where a jump sends them (pvAutoScrolling): the reading page is not yet the one asked for. While that page's
// save is still out the popover opens bound to it (pvReasonOpenPending) - a key and Enter at once is one intent.
/** @param {KeyboardEvent} e */
function pvReasonEnterKey(e){if(e.key!=='Enter'||e.defaultPrevented||e.isComposing||e.ctrlKey||e.metaKey||e.altKey||e.shiftKey||e.repeat)return;
  const t=/** @type {HTMLElement|null} */(e.target),L=$('#left');
  if(!(t===document.body||t===L||t===$('#doc')||(!!t&&!!t.closest&&!!t.closest('#doc .pg'))))return;
  pvReasonEnterPages(e);}
// Enter taken as pressed on the pages (pvReasonEnterKey, or one on an off-screen line's control, pvOffPageKey): the reading
// page's reason - its popover, or a pending one while its save is out.
/** @param {KeyboardEvent} e */
function pvReasonEnterPages(e){if(document.querySelector('dialog[open]')||!$('#page-pop').hidden||!$('#doc-pop').hidden||!$('#composer').hidden||EDITOR.current||REPLY||!canVerdict())return;
  const page=pvReadingAt(); if(!page||!pageTakesVerdict(page))return;
  if(PV_BUSY.has(pvSlot(page))){e.preventDefault(); e.stopImmediatePropagation(); pvReasonOpenPending(page); return;}   // the save is out: the Enter is the intent to write
  const cur=pvCurOf(page); if(!cur||!pvCanCancel(cur))return;
  e.preventDefault(); e.stopImmediatePropagation(); if(pvAutoScrolling()){pvSayGliding(); return;} pvReasonOpen(page,true);}
document.addEventListener('keydown',pvReasonEnterKey);
// After a focused reason field went from under the person (its verdict taken back elsewhere), the keys they go on typing
// are not verdict keys: one would save a verdict they never chose (and the text is in its page's draft). It lasts until
// they press something on purpose - a press of the pointer, Esc, or opening the popover again.
let PV_KEY_GUARD=false;
// Whether verdict key e falls under that guard - said once on the status line when it does.
/** @param {KeyboardEvent} e */
function pvKeyGuarded(e){if(!PV_KEY_GUARD)return false; e.preventDefault();
  lineNote('이유 칸이 닫혀 숫자를 판정으로 받지 않았습니다 — Esc를 누르거나 쪽을 누른 뒤 다시 누릅니다',NOTICE_KIND.INFO,null,{source:'verdict-key-guard',life:NOTICE_LIFE.TIMER});
  return true;}
addEventListener('pointerdown',()=>{PV_KEY_GUARD=false;},true);
addEventListener('keydown',e=>{if(e.key==='Escape')PV_KEY_GUARD=false;},true);
// A popover's buttons and the line's reason (events.js).
/** @param {HTMLElement} a */
function pvReasonAct(a){const act=a.dataset.act,line=a.closest('.pv'),page=Number(line&&line.getAttribute('data-page'))||0;
  if(act==='pv-reason-open'){pvReasonOpen(page,true); return;}
  if(act==='pv-reason-close'){pvReasonEsc('btn'); return;}
  if(act==='pv-reason-clear'){pvReasonClear(); return;}
  if(act==='pv-reason-fold'){pvReasonFold(); return;}
  if(act==='pv-reason-reapply'){pvReasonReapply(); return;}
  if(act==='pv-reason-see'){if(PV_REASON)gotoPinRef(PV_REASON.id,true); return;}
  const f=pvReasonField(); if(act==='pv-reason-save'&&f)pvReasonSave(f);}
// Whether this tab holds a reason not written yet that the person can see: the open popover's, a kept draft for the
// current verdict of a line on screen or a page's draft (the line marks either), or one of another document. A withdrawn
// verdict's draft waits for its [되돌리기], and one for a verdict that is no longer current is not on any line: neither asks.
function pvUnsaved(){if(PV_REASON&&pvReasonDirty(PV_REASON))return true; if(!META)return false; const d=rdAll(),kind=META.kind;
  return Object.keys(d).some(k=>{const i=k.lastIndexOf(':'),doc=k.slice(0,i),rest=k.slice(i+1); if(doc!==(DOC||''))return true; if(rest.startsWith('p'))return true;
    const id=Number(rest),p=pvReasonPin(id),t=p&&!PV_WITHDRAWN.has(id)?pageTargetOf(p,kind):null,cur=t?pvCurOf(t.page):null;
    return !!cur&&cur.id===id;});}
// Leaving the page (a reload, closing the tab, another address) with a reason not written yet asks first. The draft is kept
// either way for this tab: a reload brings it back.
addEventListener('beforeunload',e=>{if(!pvUnsaved())return; e.preventDefault(); e.returnValue='';});
