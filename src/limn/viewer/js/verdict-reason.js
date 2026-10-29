// ------------------------------------------------ A verdict's reason (docs/handbook/viewer.md §판정 핀 — 판정과 함께 이유)
// After a save on a page verdict line a person may say why in a short text that becomes the pin's note. It is written in a
// small popover over the line (.pv-pop: inside the line and laid above it, so it never pushes the page down or makes the
// floating line taller). A key save (a digit, Enter or Space on a word) opens it with the focus; a click save opens nothing
// - the line offers [이유 추가] on the person's own open verdict without a reason, and that verdict's saved reason (a check and its first line)
// opens it again to change it or clear it ([지우기]). One popover at a time: the session (PV_REASON) belongs to its pin,
// document and visit and keeps what is typed. A draft is never lost without a word:
// - it is kept per pin in this tab (sessionStorage, rd*) and a reload brings it back; leaving the page with one asks first
//   (beforeunload);
// - with text, Esc takes two presses - the first lets the focus go (the keys then change the verdict) and says what the
//   second does, which drops it;
// - changing the verdict while it is being typed moves it to the new verdict (pvReasonAfterSave);
// - [되돌리기] of a cancel or of the save chip brings it back with its verdict (pvReasonRevive);
// - a write that fails - unreachable, refused, too long - keeps it, and the line marks it '초안 있음'.
// Moving on - the reading page leaving the popover's page after it was there, another save on another page, another
// document - closes it and writes what was typed, said in one line.

// ---------------- Drafts kept per pin (sessionStorage)
// One record per instance label for this tab: {v:1, d:{'<doc>:<pin id>': {text, base, rev, at}}} - the text typed for a
// pin's reason and not written yet, the reason it was typed over (base: '' for a new reason, the saved one when it is being
// changed) with the pin's rev when it was opened (a change is written against that rev, never a later one), and when. Written on every input; taken out once it is written, dropped (Esc twice, [지우기]), moved to a new
// verdict, or when its pin is found gone from the lists (pvReasonRestore).
const RD_V=1;
/** @typedef {{text:string,base:string,rev:number,at:number}} ReasonDraft */
function rdKey(){return 'limnReason:'+encodeURIComponent(META&&META.label||'');}
/** @returns {Record<string,ReasonDraft>} */
function rdAll(){try{const o=JSON.parse(sessionStorage.getItem(rdKey())||'null'); return o&&o.v===RD_V&&o.d&&typeof o.d==='object'?o.d:{};}catch(e){return {};}}
/** @param {Record<string,ReasonDraft>} d */
function rdSave(d){try{if(Object.keys(d).length)sessionStorage.setItem(rdKey(),JSON.stringify({v:RD_V,d})); else sessionStorage.removeItem(rdKey());}catch(e){}}
/** @param {string|null} doc @param {number} id */
function rdName(doc,id){return (doc||'')+':'+id;}
// Pin id's draft on document doc, or null.
/** @param {string|null} doc @param {number} id @returns {ReasonDraft|null} */
function rdGet(doc,id){const x=rdAll()[rdName(doc,id)];
  return x&&typeof x.text==='string'&&x.text.trim()?{text:x.text,base:typeof x.base==='string'?x.base:'',rev:typeof x.rev==='number'?x.rev:-1,at:Number(x.at)||0}:null;}
// Keeps text as pin id's draft - or drops it when nothing is unsaved (empty, or the reason as it is saved).
/** @param {string|null} doc @param {number} id @param {string} text @param {string} base @param {number} [rev] */
function rdPut(doc,id,text,base,rev){const d=rdAll(),k=rdName(doc,id);
  if(text.trim()&&text.trim()!==base.trim())d[k]={text,base,rev:rev===undefined?-1:rev,at:Date.now()}; else delete d[k]; rdSave(d);}
// Keeps reason session r's text as its pin's draft.
/** @param {ReasonSession} r */
function rdKeep(r){rdPut(r.doc,r.id,r.text,r.base,r.rev);}
/** @param {string|null} doc @param {number} id */
function rdDrop(doc,id){const d=rdAll(),k=rdName(doc,id); if(k in d){delete d[k]; rdSave(d);}}

// ---------------- The session
// sid: the popover's own number - its field stays the same element while its draft moves to another verdict, so the focus
// and an input method's composition stay with it. base: the reason the field opened on ('' for a new one); a change of it
// writes the whole note against its rev. from: the verdict the draft moved from (0 when it did not), said in the popover.
// rev: the pin's rev when a saved reason was opened to change it (-1 for a new reason) - the change and [지우기] are
// written against it, so a note changed meanwhile elsewhere is never written over. conflict: that newer note and its rev,
// once a write found it (the popover shows it and offers to put this text over it, pvReasonReapply). opener: what opened
// the popover - 'line' (its line's [이유 추가], saved reason or draft mark, which takes the focus back when it closes) or
// 'save' (a save on the line: the focus goes to the PDF area). focus: the field takes the focus once its save is done. escArm: the first Esc (or [닫기]) with text was pressed - 'key' or
// 'btn' - and the next one drops the draft. saved: the text the session has written; tried: texts whose write failed
// without an answer that says it did not land (it may have).
/** @typedef {{sid:number,page:number,id:number,key:string,doc:string|null,visit:any,text:string,base:string,rev:number,conflict:{note:string,rev:number}|null,opener:string,from:number,focus:boolean,seen:boolean,listed:boolean,writing:Promise<boolean>|null,saved:string|null,tried:string[],escArm:string}} ReasonSession */
let PV_REASON=/** @type {ReasonSession|null} */(null);
let PV_RSEQ=0;
let PV_LAST_SAVE=0;   // the verdict pin the last save on a page line made: its line offers [이유 추가] wherever it is
// The pins this person withdrew (the save's undo, [판정 취소], a pressed word pressed again) while a reason for them may still
// be on its way: its failure, or its finding the pin gone, is no news to them - nothing is said. A failed withdrawal or a
// restore takes the pin out again.
const PV_WITHDRAWN=/** @type {Set<number>} */(new Set());
/** @param {number} page @param {number} id @param {string} key @param {string} text @param {string} base @param {boolean} focus @param {number} [rev] @param {string} [opener] @returns {ReasonSession} */
function pvReasonNew(page,id,key,text,base,focus,rev,opener){
  return {sid:++PV_RSEQ,page,id,key,doc:DOC,visit:captureVisit(),text,base,rev:rev===undefined?-1:rev,conflict:null,opener:opener||'save',from:0,focus,
    seen:pvReadingPage()===page,listed:false,writing:null,saved:null,tried:[],escArm:''};}
// Whether reason session r changes a saved reason (and so is written whole, against the rev it was opened at).
/** @param {ReasonSession} r */
function pvReasonEdits(r){return !!r.base.trim();}
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
// Before a line is drawn: a session of another document or visit goes (its text saved, pvReasonLeave); one whose pin left
// the lists (undone or deleted elsewhere) goes unsaved - its draft stays kept; else it follows its pin to the page that
// pin's target is on now. Without a session, a document's first lines bring back its newest kept draft (pvReasonRestore).
function pvReasonSync(){const r=PV_REASON;
  if(r&&(r.doc!==DOC||!currentVisit(r.visit))){pvReasonLeave(); return;}
  if(!PINS_APPLIED_SEQ)return;
  if(!r){pvReasonRestore(); return;}
  const p=pvReasonPin(r.id);
  if(!p){if(r.listed)PV_REASON=null; return;}   // not listed yet right after its save; gone once it was
  r.listed=true; const t=pageTargetOf(p,META?META.kind:undefined); if(t)r.page=t.page;}
// Once per document in this page's life, when its first lines are drawn: the drafts kept for pins that are gone are let go,
// and the newest one for a person's own open verdict that its line shows is opened again - without the focus - as it was
// before the reload. The others wait on their lines ('초안 있음').
const PV_RESTORED=/** @type {Set<string>} */(new Set());
function pvReasonRestore(){const doc=DOC||''; if(PV_RESTORED.has(doc)||!META)return; PV_RESTORED.add(doc);
  const d=rdAll(),pre=doc+':',kind=META.kind; let best=/** @type {{page:number,p:Pin,x:ReasonDraft}|null} */(null),gone=false;
  for(const k of Object.keys(d)){if(!k.startsWith(pre))continue; const p=pvReasonPin(Number(k.slice(pre.length)));
    if(!p){delete d[k]; gone=true; continue;}
    const t=pageTargetOf(p,kind),cur=t?(pageVerdictPins().get(t.page)||[])[0]:null,x=d[k];
    if(t&&cur&&cur.id===p.id&&pvCanCancel(p)&&typeof x.text==='string'&&x.text.trim()&&(!best||x.at>best.x.at))best={page:t.page,p,x};}
  if(gone)rdSave(d);
  if(best){const r=pvReasonNew(best.page,best.p.id,verdictOf(best.p)||'',best.x.text,best.x.base||'',false,best.x.rev); r.listed=true; pvReasonSeeConflict(r,best.p); PV_REASON=r;}}
// A draft that changes a saved reason, opened again after its pin's note changed elsewhere: it knows the newer note at once.
/** @param {ReasonSession} r @param {Pin} p */
function pvReasonSeeConflict(r,p){const note=String(p.note||'');
  r.conflict=pvReasonEdits(r)&&note.trim()!==r.base.trim()?{note,rev:typeof p.rev==='number'?p.rev:-1}:null;}
// Closes the popover. Closed on purpose (back: Esc, Enter after its save, [닫기], [지우기]) the focus goes back to what
// opened it: the line's reason control when the line opened it ([이유 추가], the saved
// reason, the draft mark - whichever the line shows now), else the PDF area - a save opened it, and sending the focus to
// the pressed word let a Space read on another page save a verdict out of view. Closed by moving on with the focus inside,
// the focus goes to the PDF area.
/** @param {boolean} back */
function pvReasonEnd(back){const r=PV_REASON,pop=document.querySelector('#doc .pv-pop'),had=!!pop&&pop.contains(document.activeElement);
  PV_REASON=null; drawPageVerdicts(); if(!back){if(had)searchToPage(); return;}   // moved on with the focus inside: the PDF area
  const c=r&&r.opener==='line'?/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+r.page+'"] [data-act="pv-reason-open"]')):null;
  if(c)c.focus({preventScroll:true}); else searchToPage();}
// Moving on: the popover closes and what was typed is written as Enter would, said in one line; nothing unsaved just closes.
function pvReasonLeave(){const r=PV_REASON; if(!r)return; pvReasonEnd(false); if(pvReasonDirty(r))pvReasonCommit(r,r.text.trim(),true);}
// Opens the popover on page `page`'s line for its current verdict - the person's own open one ([이유 추가], its saved reason,
// its kept draft): with that draft, else the saved reason to change. Another popover moves on first.
/** @param {number} page @param {boolean} focus */
function pvReasonOpen(page,focus){const cur=(pageVerdictPins().get(page)||[])[0]; if(!cur||!pvCanCancel(cur)||viewerBlocked())return;
  if(!(PV_REASON&&PV_REASON.id===cur.id&&pvReasonOn(page))){pvReasonLeave();
    const note=String(cur.note||''),d=rdGet(DOC,cur.id),rev=typeof cur.rev==='number'?cur.rev:-1;
    const r=pvReasonNew(page,cur.id,verdictOf(cur)||'',d?d.text:note,d?d.base:note,focus,d&&d.rev>=0?d.rev:rev,'line'); r.listed=true; pvReasonSeeConflict(r,cur); PV_REASON=r;}
  hideTip(); drawPageVerdicts(); if(focus)pvReasonFocus();}
// Puts the focus in the open field, its caret at the end.
function pvReasonFocus(){const f=pvReasonField(); if(!f||f.disabled)return; f.focus({preventScroll:true}); const n=f.value.length; f.setSelectionRange(n,n);}
// A save on page `page`'s line made verdict pin id (savePageVerdict) in place of verdict pin prev (the line's current one
// before it, 0 for none). A popover open on that line follows it: its draft moves to the new verdict - never written on
// the one it replaced - and says where it goes now, keeping its field, focus and composition; an empty one stays open for
// the new verdict. A draft kept for prev without a popover (a write that failed) moves too, and the line marks it on the
// new verdict. A popover elsewhere, or one whose write is out, moves on. A key save opens one with the focus.
/** @param {number} page @param {number} id @param {string} key @param {boolean} kb @param {number} prev */
function pvReasonAfterSave(page,id,key,kb,prev){const r=PV_REASON; PV_LAST_SAVE=id;
  if(r&&pvReasonOn(page)&&!r.writing){const dirty=pvReasonDirty(r),from=r.id;
    if(dirty){rdDrop(r.doc,from); rdPut(DOC,id,r.text,'');} else r.text='';
    Object.assign(r,{id,key,base:'',rev:-1,conflict:null,from:dirty?from:0,saved:null,tried:[],listed:false,escArm:''}); r.focus=r.focus||kb; return;}
  const d=prev&&!(r&&r.id===prev)?rdGet(DOC,prev):null; if(d){rdDrop(DOC,prev); rdPut(DOC,id,d.text,'');}
  pvReasonLeave();
  if(kb)PV_REASON=pvReasonNew(page,id,key,d?d.text:'','',true);}
// After a page line's save ends: the popover that waits for the focus takes it - unless the person put the focus anywhere
// else meanwhile (away). Returns whether it did.
/** @param {number} page @param {boolean} away */
function pvReasonFocusAfter(page,away){const r=PV_REASON; if(!r||r.page!==page||!r.focus)return false; r.focus=false;
  if(away)return false; const f=pvReasonField(); if(!f)return false; pvReasonFocus(); return true;}
// [되돌리기] brought verdict pin id back (a cancel's, the save chip's): its kept draft opens again on its line, without the focus.
/** @param {number} id */
function pvReasonRevive(id){const d=rdGet(DOC,id),p=pvReasonPin(id); if(!d||!p||(PV_REASON&&PV_REASON.id===id))return;
  const t=pageTargetOf(p,META?META.kind:undefined); if(!t)return; pvReasonLeave();
  const r=pvReasonNew(t.page,id,verdictOf(p)||'',d.text,d.base,false,d.rev); r.listed=true; pvReasonSeeConflict(r,p); PV_REASON=r; drawPageVerdicts();}

// ---------------- Writing
// The one write of reason session r: text as its pin's note (pvReasonWrite). While a write is out it is that write - Enter
// and then moving on, another save or another document before the answer start no second one - and text the session has
// written is not written again. A failed write may be tried again. Resolves with whether the reason is written; once it
// is, its kept draft goes (unless more was typed meanwhile).
/** @param {ReasonSession} r @param {string} text @param {boolean} said @returns {Promise<boolean>} */
function pvReasonCommit(r,text,said){if(r.saved===text)return Promise.resolve(true);
  if(!r.writing)r.writing=pvReasonWrite(r,text,said).then(ok=>{r.writing=null;
    if(ok){r.saved=text; const d=rdGet(r.doc,r.id); if(d&&d.text.trim()===text)rdDrop(r.doc,r.id);} return ok;});
  return r.writing;}
// [다시 시도] on a failed reason: the session's draft as it is now (after a failed Enter the field stays open and may have been
// corrected) written as its one write. A field still open for it waits while it writes, and closes only when what was
// written is what it holds.
/** @param {ReasonSession} r */
function pvReasonRetry(r){const text=r.text.trim(); if(!text||r.writing)return;
  const w=pvReasonCommit(r,text,true); if(PV_REASON===r)drawPageVerdicts();
  w.then(ok=>{if(PV_REASON!==r)return; if(ok&&r.text.trim()===text)pvReasonEnd(false); else drawPageVerdicts();});}
// Where text sits as a reason this viewer wrote at the end of note: the whole note (written into an empty one), or after the
// stamp a note_append puts before it ('\n(추가 12:30) <text>'); -1 when it does not.
/** @param {string} note @param {string} text */
function reasonAt(note,text){if(note===text)return 0; const i=note.length-text.length;
  return i>0&&note.endsWith(text)&&/\(추가 \d{1,2}:\d{2}\) $/.test(note.slice(0,i))?i:-1;}
/** @param {string} note @param {string} text */
function reasonIn(note,text){if(text.includes('\n'))return reasonAt(note,text)>=0;
  return note.split('\n').some(l=>l===text||l.replace(/^\(추가 \d{1,2}:\d{2}\) /,'')===text);}
// The edit that writes text into pin p's note for session r, or null when p already holds it. A change of a saved reason
// (r.base) is the whole note, against the rev it was opened at (r.rev) - never p's later one, which would write over a note
// changed meanwhile without the server's 409. A new one: after a write whose answer was lost (r.tried) the server may have
// it - when the note holds this very text it is saved already, and when it ends with an earlier draft of this session that
// landed, the draft is replaced (a corrected reason, not a second one); otherwise the text goes into an empty note, or
// under the note someone wrote (note_append).
/** @param {ReasonSession} r @param {string} text @param {Pin} p @returns {Record<string, unknown>|null} */
function pvReasonBody(r,text,p){const note=String(p.note||'');
  if(pvReasonEdits(r))return note.trim()===text?null:{note:text,base_rev:r.rev>=0?r.rev:p.rev};
  if(r.tried.length&&reasonIn(note,text))return null;
  const old=r.tried.find(t=>t!==text&&reasonAt(note,t)>=0);
  if(old)return {note:note.slice(0,reasonAt(note,old))+text,base_rev:p.rev};
  return note?{note_append:text}:{note:text,base_rev:p.rev};}
const NOTE_APPEND_LIMIT=2000,NOTE_LIMIT=4000;   // the server's (pins/editing): a note_append, a whole note
// Why edit body b would be refused for its length - said instead of sending it, the draft kept - or ''.
/** @param {Record<string, unknown>} b */
function pvReasonTooLong(b){const a=b.note_append,n=b.note,f=(/** @type {number} */x)=>x.toLocaleString('en-US');
  if(typeof a==='string'&&a.length>NOTE_APPEND_LIMIT)return tl('덧붙일 이유는 {max}자까지입니다(지금 {len}자)',{max:f(NOTE_APPEND_LIMIT),len:f(a.length)});
  if(typeof n==='string'&&n.length>NOTE_LIMIT)return tl('메모는 {max}자까지입니다(지금 {len}자)',{max:f(NOTE_LIMIT),len:f(n.length)});
  return '';}
// Writes text as reason session r's pin's note: the note edit with the pin's rev (read again when the lists do not hold the
// pin); a note someone wrote meanwhile is kept and a new reason is added to it (note_append), while a change of a saved
// reason that someone changed meanwhile is not written over theirs. A pin that is gone takes nothing. said: the status
// line says it was saved (moving on, a draft that moved to a new verdict), with the verdict it went to. A failure is said
// by pvReasonFailed. Returns whether it was written.
/** @param {ReasonSession} r @param {string} text @param {boolean} said @returns {Promise<boolean>} */
async function pvReasonWrite(r,text,said){if(viewerBlocked())return false;
  // After a lost answer the lists may not say whether it landed: the pin is read from the server.
  let p=r.tried.length?undefined:pvReasonPin(r.id);
  if(!p){try{p=(await api('/api/pins/'+r.id,{what:'핀 읽기',silent:true})).data.pin;}
    catch(e){const x=/** @type {ApiError} */(e); if(!x||!x.status||x.status>=500){pvReasonFailed(r,text,x); return false;} p=undefined;}}
  if(!p||p.dropped_at){if(!PV_WITHDRAWN.has(r.id))lineNote(tl('핀 #{id} 은 그사이 다른 곳에서 지워졌습니다',{id:r.id}),NOTICE_KIND.WARN); return false;}
  const url='/api/pins/'+r.id+'/edit',o={method:'POST',intent:'reason',silent:true};   // silent: pvReasonFailed says a failure, with its target
  try{const body=pvReasonBody(r,text,p);
    if(body){const long=pvReasonTooLong(body); if(long){pvReasonFailed(r,text,null,long); return false;}
      const {status,data}=await api(url,{...o,body,expect:[409]});
      if(status===409){const q=data&&data.pin;   // someone changed the pin meanwhile: their note stays
        if(!q){pvReasonFailed(r,text,null,tr('그사이 다른 곳에서 메모가 바뀌었습니다')); return false;}
        if(pvReasonEdits(r)){if(String(q.note||'').trim()!==r.base.trim()){pvReasonConflict(r,text,q); return false;}
          r.rev=typeof q.rev==='number'?q.rev:r.rev;}   // only something else changed (a claim, the assignee): the note is the one it opened on
        const again=pvReasonBody(r,text,q),l2=again?pvReasonTooLong(again):'';
        if(l2){pvReasonFailed(r,text,null,l2); return false;}
        if(again)await api(url,{...o,body:again});}}
  }catch(e){pvReasonFailed(r,text,/** @type {ApiError} */(e)); return false;}
  if(said)lineNote(tl('이유 저장됨 · 판정 #{id} {word} — {target}',{id:r.id,word:verdictLabel(r.key,r.doc),target:pvReasonName(r)}),NOTICE_KIND.OK,null,{life:NOTICE_LIFE.TIMER,literal:true});   // result first: the folded line shows it
  else quietNote(tl('판정 #{id} 이유를 저장했습니다',{id:r.id}));
  if(r.doc===DOC)loadPins().catch(()=>{});
  return true;}
// What a reason session's verdict is about, by a short name for the status line: its page's target while its document is on
// screen ('PL16'), else its document's name.
/** @param {ReasonSession} r */
function pvReasonName(r){if(r.doc===DOC)return pageTargetShort(r.page); const d=r.doc?docInfo(r.doc):null; return d&&d.name||'#'+r.id;}
// A reason that could not be written, said on the status line result first ('이유 저장 실패 · 서버에 닿지 않습니다 — PL16') in
// place of api()'s line, keyed by the request as api() keys it (a later answer from it clears it). The draft is kept
// whatever failed (rdPut) and the line marks it; unless the server refused it (a 4xx would refuse again) or it is too long
// (why: said before sending) the message offers [다시 시도], which writes the session's draft (pvReasonRetry). Stays until
// [x] or its action (STICKY). A write without an answer is remembered (tried): it may have landed. The reason for a pin this
// person has withdrawn meanwhile goes quietly (PV_WITHDRAWN).
/** @param {ReasonSession} r @param {string} text @param {ApiError|null} e @param {string} [why0] */
function pvReasonFailed(r,text,e,why0){const st=e&&typeof e.status==='number'?e.status:0,again=!why0&&(!st||st>=500);
  if(again&&!r.tried.includes(text))r.tried.push(text);
  rdPut(r.doc,r.id,r.text.trim()?r.text:text,r.base,r.rev);
  if(PV_WITHDRAWN.has(r.id))return;
  const why=why0||(st?(e&&e.data&&errText(e.data))||'HTTP '+st:tr('서버에 닿지 않습니다'));
  lineNote(tl('이유 저장 실패 · {why} — {target}',{why,target:pvReasonName(r)}),NOTICE_KIND.ERR,again?{label:'다시 시도',fn:()=>pvReasonRetry(r)}:null,
    {source:'POST /api/pins/'+r.id+'/edit reason',literal:true});
  if(PV_REASON!==r&&r.doc===DOC)drawPageVerdicts();}   // the line marks the draft it keeps
// A change of a saved reason found the note changed elsewhere since the popover opened (newer note q): nothing is written
// over it. The draft is kept, the popover - when open - shows the newer note and offers [그 위에 쓰기] (pvReasonReapply),
// and the status line says so, result first, with [메모 보기] (the pin's card).
/** @param {ReasonSession} r @param {string} text @param {Pin} q */
function pvReasonConflict(r,text,q){r.conflict={note:String(q.note||''),rev:typeof q.rev==='number'?q.rev:-1};
  rdPut(r.doc,r.id,r.text.trim()?r.text:text,r.base,r.rev);
  lineNote(tl('이유 저장 안 함 · 그사이 다른 곳에서 메모가 바뀌었습니다 — {target}',{target:pvReasonName(r)}),NOTICE_KIND.WARN,{label:'메모 보기',fn:()=>gotoPinRef(r.id)},
    {source:'POST /api/pins/'+r.id+'/edit reason',literal:true});
  if(PV_REASON!==r&&r.doc===DOC)drawPageVerdicts();}
// [그 위에 쓰기] in a popover that knows a newer note: the person has seen it and puts their text over it - the newer note is
// what the change is now made from, and it is written against that note's rev.
function pvReasonReapply(){const r=PV_REASON,f=pvReasonField(); if(!r||!r.conflict||!f||r.writing)return;
  r.base=r.conflict.note; r.rev=r.conflict.rev; r.conflict=null; rdKeep(r); if(!pvReasonDirty(r)){pvRefill(r.page); return;} pvReasonSave(f);}
// Enter (or [저장]): the text written as the note and the popover closed. Empty is a skip - a saved reason stays - and the
// reason as it is saved has nothing to write. While the request is out the field waits (disabled, the popover says
// '저장 중…'); a failure leaves the text in it for another Enter.
/** @param {HTMLTextAreaElement} f */
async function pvReasonSave(f){const r=PV_REASON; if(!r||r.writing||f.disabled)return; r.text=f.value; const text=r.text.trim();
  if(!text||text===r.base.trim()){rdDrop(r.doc,r.id); pvReasonEnd(true); return;}
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
  if(!pvReasonDirty(r)){if(!r.text.trim()||r.text.trim()===r.base.trim())rdDrop(r.doc,r.id); pvReasonEnd(true); return;}
  if(!r.escArm){r.escArm=how; if(how==='key')searchToPage(); pvRefill(r.page);
    announce(how==='key'?tr('Esc 한 번 더 누르면 이 이유를 버립니다'):tr('[닫기]를 한 번 더 누르면 이 이유를 버립니다')); return;}
  rdDrop(r.doc,r.id); pvReasonEnd(true); announce(tl('판정 #{id} 이유를 버렸습니다',{id:r.id}));}
// [접기]: the popover folds away, nothing written - over the plot it hid what the reason is about. The draft stays kept and
// the line marks it '초안 있음', which opens it again (and takes the focus back). Moving on then writes nothing: a folded
// draft waits for the person.
function pvReasonFold(){const r=PV_REASON; if(!r||r.writing)return; if(pvReasonDirty(r))rdKeep(r); else rdDrop(r.doc,r.id);
  PV_REASON=null; drawPageVerdicts();
  const c=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+r.page+'"] [data-act="pv-reason-open"]'));
  if(c)c.focus({preventScroll:true}); else searchToPage();
  announce(tr('이유 초안을 접었습니다 — 줄의 [초안 있음]이 다시 엽니다'));}
// [지우기]: the saved reason goes - the note emptied against the rev the popover opened at - and the status line offers
// [되돌리기], which writes it back. The popover and its draft stay until the server says it is done: a failure keeps both
// (the status line says it, with [다시 시도] when the server was not reached), and a note changed elsewhere meanwhile is not
// cleared (pvReasonConflict).
async function pvReasonClear(){const r=PV_REASON; if(!r||r.writing||viewerBlocked()||!pvReasonEdits(r))return;
  if(r.conflict){pvRefill(r.page); return;}
  const old=r.base,target=pvReasonName(r),word=verdictLabel(r.key),url='/api/pins/'+r.id+'/edit',o={method:'POST',intent:'reason',silent:true,expect:[409]};
  const go=async()=>{try{const {status,data}=await api(url,{...o,body:{note:'',base_rev:r.rev}}); if(status!==409)return 'ok';
      const q=data&&data.pin; if(!q)return 'gone';
      if(String(q.note||'').trim()!==r.base.trim()){pvReasonConflict(r,r.text,q); return 'conflict';}
      await api(url,{...o,expect:[],body:{note:'',base_rev:q.rev}}); return 'ok';}
    catch(e){const x=/** @type {ApiError} */(e),st=x&&typeof x.status==='number'?x.status:0;
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
function pvReasonState(r){if(r.writing)return {text:tr('저장 중…'),cls:'busy'}; const t=r.text.trim(); if(!t)return {text:'',cls:''};
  return t===r.saved||t===r.base.trim()?{text:tr('저장됨'),cls:'ok'}:{text:tr('저장 안 됨'),cls:'warn'};}
// What the keys do now, under the field: with a fine pointer - empty, Enter and Esc and that the digits change the verdict;
// with text, that Enter saves and the digits wait for Esc; after a first Esc, what the second does. With touch only the
// second press of [닫기] is said.
/** @param {ReasonSession} r @param {boolean} focused */
function pvReasonHint(r,focused){const fine=matchMedia('(pointer:fine)').matches,t=r.text.trim(),v=pageVerdictsOn(),n=v?v.choices.length:0;
  if(r.escArm==='btn')return tr('[닫기]를 한 번 더 누르면 이 이유를 버립니다');
  if(!fine)return '';
  if(r.escArm)return tr('Esc 한 번 더 누르면 이 이유를 버립니다')+' · '+tr('숫자로 판정 바꾸기');
  if(!focused)return '';
  return t?tr('Enter 저장')+' · '+tr('Esc 뒤 숫자로 판정 바꾸기'):tr('Enter 저장')+' · '+tr('Esc 닫기')+(n?' · '+tl('1–{last} 판정 바꾸기',{last:n}):'');}
// The popover on page `page`'s line while its session is open there (a person who may make a verdict): a labelled,
// non-modal group - the field, then one row: whose reason it is ('판정 #16 보류 이유', '판정 #16 보류 · 저장된 이유 수정' when it
// changes a saved one, '#15 채택에서 옮김' after a move), the draft's state, the keys, and [지우기] (a saved reason), [접기]
// (a draft: the popover folds to the line's '초안 있음', the draft kept), [닫기], [저장]. When a write found the note changed
// elsewhere, a row above the field shows the newer note's first line with [메모 보기] and [그 위에 쓰기]. The field is drawn
// empty; its text is put in after drawing (pvReasonAfterDraw), never as markup a redraw could put back under the caret or
// an input method.
/** @param {number} page */
function pvReasonPop(page){const r=pvReasonOn(page)&&canVerdict()?PV_REASON:null; if(!r)return '';
  const a=document.activeElement,focused=pvIsReasonField(a)&&a.dataset.id==='s'+r.sid,st=pvReasonState(r),hint=pvReasonHint(r,focused);
  const word=verdictLabel(r.key),who=pvReasonEdits(r)?tl('판정 #{id} {word} · 저장된 이유 수정',{id:r.id,word}):tl('판정 #{id} {word} 이유',{id:r.id,word});
  const from=r.from?pvReasonPin(r.from):null,moved=r.from?tl('#{id} {word}에서 옮김',{id:r.from,word:verdictLabel(from&&verdictOf(from)||'')}):'';
  const cf=r.conflict?html`<div class="pv-pop-cf" role="alert"><span class="pv-pop-cf-t">${tr('그사이 다른 곳에서 메모가 바뀌었습니다')}: \
<q translate="no">${r.conflict.note.split('\n')[0]||tr('(빈 메모)')}</q></span><span class="pv-pop-acts">\
<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-see">${tr('메모 보기')}</button>\
<button type="button" class="btn-sm hit" data-act="pv-reason-reapply" data-tip="${tr('바뀐 메모를 이 글로 바꿉니다')}">${tr('그 위에 쓰기')}</button></span></div>`:'';
  return html`<div class="pv-pop" role="group" data-id="s${r.sid}" aria-labelledby="pv-pop-to-${r.sid}" aria-describedby="pv-pop-h-${r.sid}">${cf}\
<textarea class="pv-reason" rows="1" maxlength="4000" autocomplete="off" enterkeyhint="done" data-id="s${r.sid}" data-pin="${r.id}"${r.writing?html` disabled`:''} \
placeholder="${tr('이유 (선택)')}" aria-label="${tl('{who} (선택)',{who})}" aria-describedby="pv-pop-h-${r.sid}"></textarea>\
<div class="pv-pop-f"><span class="pv-pop-to" id="pv-pop-to-${r.sid}" translate="no">${who}${moved?html`<span class="pv-pop-from"> · ${moved}</span>`:''}</span>\
<span class="pv-pop-st${st.cls?' '+st.cls:''}" aria-live="polite">${st.cls==='ok'?ic('check'):''}${st.text}</span><span class="pv-pop-h" id="pv-pop-h-${r.sid}">${hint}</span>\
<span class="pv-pop-acts">${pvReasonEdits(r)?html`<button type="button" class="btn-ghost btn-sm pv-pop-clear hit" data-act="pv-reason-clear" \
data-tip="${tr('저장한 이유를 지웁니다. 상태 줄의 [되돌리기]가 되살립니다')}">${tr('지우기')}</button>`:''}\
${pvReasonDirty(r)?html`<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-fold" data-tip="${tr('초안을 둔 채 접습니다. 줄의 [초안 있음]이 다시 엽니다')}">${tr('접기')}</button>`:''}\
<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-close" data-tip="${tr('닫습니다. 쓰던 이유가 있으면 한 번 더 눌러야 버립니다')}">${tr('닫기')}</button>\
<button type="button" class="btn-sm pv-pop-save hit" data-act="pv-reason-save"${r.writing||r.conflict?html` aria-disabled="true"`:''}>${tr('저장')}</button></span></div></div>`;}
// The reason on page `page`'s line, after its state: the saved reason of its current verdict (a check and its first line,
// .pv-rn) - a button that opens the popover to change it on the person's own open verdict, with a pencil and the name
// '저장된 이유 수정' -, then (.pv-ra) a kept draft not written yet ('초안 있음', which opens it: a folded popover, a failed
// write, a reload's other drafts) on any line, or [이유 추가] for the person's own open verdict without a
// reason on the reading line - the one that floats - and on the line of the last click save (PV_LAST_SAVE), wherever it
// is. The other lines keep their length: [이유 추가] on each of them made a long line wrap its buttons. Nothing for the
// reason the open popover holds.
/** @param {number} page @param {Pin|undefined} cur */
function pvReasonInline(page,cur){if(!cur)return '';
  const mine=pvCanCancel(cur),open=pvReasonOn(page)&&!!PV_REASON&&PV_REASON.id===cur.id,note=String(cur.note||''),first=note.split('\n')[0];
  const sep=html`<span class="pv-sep" aria-hidden="true">·</span>`,d=open?null:rdGet(DOC,cur.id),draft=!!d&&d.text.trim()!==note.trim();
  const ok=html`<span class="pv-ok" aria-hidden="true">${ic('check')}</span>`;
  const saved=!note?'':mine&&!open?html`<span class="pv-rn">${sep}<button type="button" class="btn-ghost btn-sm pv-note hit" data-act="pv-reason-open" translate="no" \
aria-label="${tl('저장된 이유 수정 — 판정 #{id} · {note}',{id:cur.id,note:first})}" data-tip="${tr('저장된 이유 수정')}">${ok}<span class="pv-note-t">${first}</span>${ic('pencil')}</button></span>`
    :html`<span class="pv-rn">${sep}<span class="pv-note" translate="no"${open?'':html` data-tip="${note}"`}>${ok}${first}</span></span>`;   // open: no box over the popover
  const act=!mine||open?'':draft?html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-draft hit" data-act="pv-reason-open" \
aria-label="${tr('저장 안 된 이유 초안이 있습니다 — 누르면 이어 씁니다')}" data-tip="${tr('저장 안 된 이유 초안이 있습니다 — 누르면 이어 씁니다')}">${tr('초안 있음')}</button></span>`
    :!note&&(PV_READ===page||PV_LAST_SAVE===cur.id)?html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" data-act="pv-reason-open" \
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
// Every input keeps the draft (rdPut) and lets a first Esc go; the line follows its emptiness (the key marks, the state).
$('#doc').addEventListener('input',e=>{const f=e.target; if(!pvIsReasonField(f))return; const r=PV_REASON; if(!r||f.dataset.id!=='s'+r.sid)return;
  r.text=f.value; r.escArm=''; rdKeep(r); pvReasonGrow(f); pvRefill(r.page); pvStickSoon();});
// Keys in the field: Enter saves (Shift+Enter is a new line), Esc closes or takes two presses with text, and a digit 1-5 in
// an empty field is the line's verdict key - it changes the verdict and the field stays open for it. With text the digits
// are text (the field says to press Esc first). Nothing while an input method composes.
$('#doc').addEventListener('keydown',e=>{const f=e.target; if(!pvIsReasonField(f)||e.isComposing||e.keyCode===229)return; const r=PV_REASON;
  if(e.key==='Enter'&&!e.shiftKey&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault(); e.stopPropagation(); pvReasonSave(f); return;}
  if(e.key==='Escape'){e.preventDefault(); e.stopPropagation(); pvReasonEsc('key'); return;}
  if(!r||e.ctrlKey||e.metaKey||e.altKey||e.repeat||!/^[1-5]$/.test(e.key)||f.value.trim())return;
  const v=pageVerdictsOn(),c=v&&v.choices[Number(e.key)-1]; if(!c||!canVerdict())return; e.preventDefault(); e.stopPropagation();
  const b=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+r.page+'"] button[data-act="pv-save"][data-key="'+CSS.escape(c.key)+'"]'));
  if(b)verdictPress(b,'key');});
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
// A popover's buttons and the line's reason (events.js).
/** @param {HTMLElement} a */
function pvReasonAct(a){const act=a.dataset.act,line=a.closest('.pv'),page=Number(line&&line.getAttribute('data-page'))||0;
  if(act==='pv-reason-open'){pvReasonOpen(page,true); return;}
  if(act==='pv-reason-close'){pvReasonEsc('btn'); return;}
  if(act==='pv-reason-clear'){pvReasonClear(); return;}
  if(act==='pv-reason-fold'){pvReasonFold(); return;}
  if(act==='pv-reason-reapply'){pvReasonReapply(); return;}
  if(act==='pv-reason-see'){if(PV_REASON)gotoPinRef(PV_REASON.id); return;}
  const f=pvReasonField(); if(act==='pv-reason-save'&&f)pvReasonSave(f);}
// Whether this tab holds a reason not written yet that the person can see: the open popover's, a kept draft for the
// current verdict of a line on screen (the line marks it), or one of another document. A withdrawn verdict's draft waits
// for its [되돌리기], and one for a verdict that is no longer current is not on any line: neither asks.
function pvUnsaved(){if(PV_REASON&&pvReasonDirty(PV_REASON))return true; if(!META)return false; const d=rdAll(),kind=META.kind;
  return Object.keys(d).some(k=>{const i=k.lastIndexOf(':'),doc=k.slice(0,i),id=Number(k.slice(i+1)); if(doc!==(DOC||''))return true;
    const p=pvReasonPin(id),t=p&&!PV_WITHDRAWN.has(id)?pageTargetOf(p,kind):null,cur=t?(pageVerdictPins().get(t.page)||[])[0]:null;
    return !!cur&&cur.id===id;});}
// Leaving the page (a reload, closing the tab, another address) with a reason not written yet asks first. The draft is kept
// either way for this tab: a reload brings it back.
addEventListener('beforeunload',e=>{if(!pvUnsaved())return; e.preventDefault(); e.returnValue='';});
