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
// draft still knows them, or its next write would add a reason that had landed again; from: the parts of its text that
// were moved off a pin whose reason may still be written there (a write out, a [다시 시도], a write that lost its answer)
// - every such pin, however often the draft moved on ('a → 쪽 → b', 'a → b → c'; a page's draft is no pin and adds none),
// each part with its place in the text and that pin's lost writes (ReasonPart). Kept as the last key alone, a write that
// landed on a afterwards left the copy, which was then written again (#317). A part is a place, not a string: a sentence
// the person typed again elsewhere in the draft is not it, and the place follows every edit (rdEdit) - an edit inside
// it makes it no longer that text, and it is let go. Once one of those pins' writes lands with the part's text, the part
// leaves the copy (pvReasonWrittenOff), its failure does not make the old key again (pvReasonFailed), and a write of the
// copy waits for one that is out (pvReasonKin) and first settles the lost ones from that pin (pvReasonCheck). An older
// viewer kept one key, as a string: the whole text. Written on every input; taken out
// once written, dropped (Esc twice, [지우기]), moved to a new verdict, or when its pin is found gone from the lists
// (pvReasonRestore).
const RD_V=1;
/** @typedef {{text:string,base:string,rev:number,mode:string,folded:boolean,at:number,tried:ReasonTry[],from:ReasonPart[]}} ReasonDraft */
// A part of a draft's text moved off pin key k: text[s, e) is what k's reason write may put on k, and tried are k's writes
// whose answer was lost - the evidence that one may have put it there already.
/** @typedef {{k:string,s:number,e:number,tried:ReasonTry[]}} ReasonPart */
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
  tried:Array.isArray(x.tried)?x.tried.filter(rdTry):[],from:rdFromOf(x.from,x.text)}:null;}
// A kept draft's from as its parts that still fit its text (an older viewer kept one key, as a string: the whole text).
/** @param {unknown} x @param {string} text @returns {ReasonPart[]} */
function rdFromOf(x,text){if(typeof x==='string')return x?[{k:x,s:0,e:text.length,tried:[]}]:[];
  if(!Array.isArray(x))return [];
  return x.filter(p=>!!p&&typeof p.k==='string'&&!!p.k&&Number.isInteger(p.s)&&Number.isInteger(p.e)&&p.s>=0&&p.s<p.e&&p.e<=text.length)
    .map(p=>({k:p.k,s:p.s,e:p.e,tried:Array.isArray(p.tried)?p.tried.filter(rdTry):[]}));}
// Text compared as a reason is written: line breaks as '\n', no space around it (a write sends the draft trimmed).
/** @param {string} t */
function rdNorm(t){return t.replace(/\r\n?/g,'\n').trim();}
// Parts after their text's [ds, de) became n other characters: one before or after it keeps its text (moved by the
// difference); one it touched inside - typed into, cut, taken away - is no longer that text and goes.
/** @param {ReasonPart[]} parts @param {number} ds @param {number} de @param {number} n @returns {ReasonPart[]} */
function rdShift(parts,ds,de,n){const d=n-(de-ds); return parts.flatMap(p=>p.e<=ds?[p]:p.s>=de?[{...p,s:p.s+d,e:p.e+d}]:[]);}
// Parts of text `was` in `now`, the field's text after one input, the caret at `caret` (the end of what was typed or pasted,
// or where a deletion was): what changed is what lies between their longest common start and end - the end no further
// than the caret, so a letter typed before the same letter is placed where it was typed. (Text typed next to it on its own
// line keeps its place too: whether that changed its sentence is judged when it would leave, rdLined - a line typed above
// it is typed before its line break.)
/** @param {ReasonPart[]} parts @param {string} was @param {string} now @param {number} caret @returns {ReasonPart[]} */
function rdEdit(parts,was,now,caret){if(!parts.length||was===now)return parts; let suf=0,pre=0;
  const ms=Math.min(was.length,now.length-Math.min(Math.max(caret,0),now.length)); while(suf<ms&&was[was.length-1-suf]===now[now.length-1-suf])suf++;
  const mp=Math.min(was.length,now.length)-suf; while(pre<mp&&was[pre]===now[pre])pre++;
  return rdShift(parts,pre,was.length-suf,now.length-suf-pre);}
// Whether part p of text t still has its lines to itself: nothing but spaces between each end and a line break or the
// text's end. Text typed next to it on its line, at either end, or a line break beside it taken away, made its sentence a
// new one - as an edit inside it does -, which stays whole (RC failure test of 0.4.36: ' 더함' typed after a moved
// '문장 끝' left only '더함' to be written, without a word, once '문장 끝' was found on the earlier verdict). Spaces typed
// after it change no sentence.
/** @param {string} t @param {ReasonPart} p */
function rdLined(t,p){return /(^|\n)[ \t]*$/.test(t.slice(0,p.s))&&/^[ \t]*(\r?\n|$)/.test(t.slice(p.e));}
// Draft x (text and parts) joined under draft pd's on a new line - pd null: x as it is.
/** @param {{text:string,from:ReasonPart[]}|null} pd @param {{text:string,from:ReasonPart[]}} x @returns {{text:string,from:ReasonPart[]}} */
function rdJoin(pd,x){if(!pd)return {text:x.text,from:x.from}; const o=pd.text.length+1;
  return {text:pd.text+'\n'+x.text,from:[...pd.from,...x.from.map(p=>({...p,s:p.s+o,e:p.e+o}))]};}
// Text t (with its parts) less every part moved off pin key k whose text is `written` (rdNorm) and that still has its lines
// to itself (rdLined) - with the line break that set it apart, the rest kept as it is - or null when none is.
/** @param {string} t @param {ReasonPart[]} parts @param {string} k @param {string} written @returns {{text:string,from:ReasonPart[]}|null} */
function rdCut(t,parts,k,written){const n=rdNorm(written); if(!n)return null; let ps=parts,hit=false;
  const at=(/** @type {ReasonPart} */q)=>q.k===k&&rdNorm(t.slice(q.s,q.e))===n&&rdLined(t,q);
  for(let p=ps.find(at);p;p=ps.find(at)){hit=true; let s=p.s,e=p.e;
    const after=/^[ \t]*\r?\n/.exec(t.slice(e)),before=after?null:/\r?\n[ \t]*$/.exec(t.slice(0,s)); if(after)e+=after[0].length; else if(before)s-=before[0].length;
    const q=p; t=t.slice(0,s)+t.slice(e); ps=rdShift(ps.filter(x=>x!==q),s,e,0);}
  return hit?{text:t,from:ps}:null;}
// Whether a stored lost write is one (ReasonTry).
/** @param {any} a @returns {a is ReasonTry} */
function rdTry(a){return !!a&&typeof a.text==='string'&&typeof a.rev==='number'&&typeof a.pre==='string'&&typeof a.stamp==='boolean'&&typeof a.post==='string';}
// The draft kept under id (a pin number, or 'p<page>') on document doc, or null.
/** @param {string|null} doc @param {number|string} id @returns {ReasonDraft|null} */
function rdGet(doc,id){return rdRead(rdAll()[rdName(doc,id)]);}
// Keeps text under id - or drops it when nothing is unsaved (empty, or the reason as it is saved). The parts the draft there
// had stay unless o names others (and its text is the same); a draft never counts its own key.
/** @param {string|null} doc @param {number|string} id @param {string} text @param {string} base @param {number} [rev] @param {{mode?:string,folded?:boolean,tried?:ReasonTry[],from?:ReasonPart[]}} [o] */
function rdPut(doc,id,text,base,rev,o){const d=rdAll(),k=rdName(doc,id),mode=o&&o.mode||(base.trim()?'replace':'add'),was=rdRead(d[k]);
  const from=rdFromOf(o&&o.from!==undefined?o.from:was&&was.text===text?was.from:[],text).filter(p=>p.k!==k);
  if(text.trim()&&text.trim()!==base.trim())d[k]={text,base,rev:rev===undefined?-1:rev,mode,folded:!!(o&&o.folded),at:Date.now(),tried:o&&o.tried||[],from};
  else delete d[k]; rdSave(d);}
// Keeps reason session r's text as its pin's draft (open, not folded), with its lost writes and the parts it came from.
/** @param {ReasonSession} r @param {boolean} [folded] */
function rdKeep(r,folded){rdPut(r.doc,r.id||'p'+r.page,r.text,r.base,r.rev,{mode:r.mode,folded:!!folded,tried:r.tried,from:r.via});}   // not bound yet: the page's
/** @param {string|null} doc @param {number|string} id */
function rdDrop(doc,id){const d=rdAll(),k=rdName(doc,id); if(k in d){delete d[k]; rdSave(d);}}
// The part a draft (text, lost writes) becomes when it is moved off pin key k: all of it, with k's lost writes.
/** @param {string} k @param {{text:string,tried:ReasonTry[]}} x @returns {ReasonPart} */
function rdPart(k,x){return {k,s:0,e:x.text.length,tried:x.tried};}
// The text of a draft that is the person's own: as typed, less - when it changes a saved reason (mode 'replace') - the
// stamped lines others added under it ('(추가 HH:MM) …') as that saved note (base) held them.
/** @param {string} mode @param {string} text @param {string} base */
function rdOwn(mode,text,base){if(mode!=='replace')return text; const st=/^\(추가 \d{1,2}:\d{2}\) /,theirs=new Set(base.split(/\r?\n/).filter(l=>st.test(l)));
  return text.split('\n').filter(l=>!(st.test(l.replace(/\r$/,''))&&theirs.has(l.replace(/\r$/,'')))).join('\n');}
// What draft x becomes moved off key k (a pin's, or '' for none) to another verdict, as a new reason: its own text only
// (rdOwn: the lines others added under a saved reason being changed stay on the verdict they were written on), with the
// parts it came with (while that text is all of it) and, k a pin, all of it as a part moved off k with k's lost writes.
/** @param {string} k @param {{text:string,base:string,mode:string,tried:ReasonTry[],from:ReasonPart[]}} x @returns {{text:string,from:ReasonPart[]}} */
function rdOff(k,x){const own=rdOwn(x.mode,x.text,x.base); return {text:own,from:[...(own===x.text?x.from:[]),...(k?[rdPart(k,{text:own,tried:x.tried})]:[])]};}
// Moves the draft under from (a pin or a page) to verdict pin id, as a new reason - it was never written on the other -
// remembering where it came from (rdOff, rdMovedOff). The same whether a popover held it or it was folded or kept: a
// folded change of a saved reason used to carry others' lines into the new verdict's reason (RC failure test of 0.4.36).
// A draft with nothing of the person's own stays where it is.
/** @param {string|null} doc @param {number|string} from @param {number} id @returns {ReasonDraft|null} */
function rdMove(doc,from,id){const x=rdGet(doc,from); if(!x)return null; const m=rdOff(typeof from==='number'?rdName(doc,from):'',x); if(!m.text.trim())return null;
  rdDrop(doc,from); rdPut(doc,id,m.text,'',-1,{mode:'add',folded:x.folded,from:m.from}); return x;}
// The drafts moved off pin id's key on document doc (rdMove, pvReasonUncancelDraft) while its reason may still be written
// there, by key.
/** @param {string|null} doc @param {number} id @returns {string[]} */
function rdMovedOff(doc,id){const d=rdAll(),k=rdName(doc,id); return Object.keys(d).filter(x=>{const r=rdRead(d[x]); return !!r&&r.from.some(p=>p.k===k);});}
// Pin id's reason text was written there: the drafts moved off its key lose the parts that are that text (rdCut).
/** @param {string|null} doc @param {number} id @param {string} text */
function rdWrittenOff(doc,id,text){const d=rdAll(),k=rdName(doc,id); let ch=false;
  for(const x of Object.keys(d)){const r=rdRead(d[x]),c=r?rdCut(r.text,r.from,k,text):null; if(!r||!c)continue;
    if(c.text.trim())d[x]={...r,text:c.text,from:c.from}; else delete d[x]; ch=true;}
  if(ch)rdSave(d);}
// Pin key k's write lost its answer (lost write a): every part moved off k keeps it as evidence, stored and in a session -
// also in the texts a session's field may come back to (pvReasonEvidence).
/** @param {string|null} doc @param {number} id @param {ReasonTry} a */
function rdTriedOff(doc,id,a){const d=rdAll(),k=rdName(doc,id),add=(/** @type {ReasonPart[]} */ps)=>ps.map(p=>p.k===k?{...p,tried:[...p.tried,a]}:p); let ch=false;
  for(const x of Object.keys(d)){const r=rdRead(d[x]); if(r&&r.from.some(p=>p.k===k)){d[x]={...r,from:add(r.from)}; ch=true;}}
  if(ch)rdSave(d);
  for(const s of pvReasonLive())if(s.id!==id||s.doc!==doc)pvReasonEvidence(s,k,t=>[...t,a]);}

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
// its write was out - that write's outcome is said and settled by pvReasonOnto. via: the parts of its text moved off pins
// whose reason may still be written there (its draft's from, kept with it by rdKeep and placed again on every input,
// pvReasonPlace): a write of a part's text there takes that part out of this one (pvReasonWrittenOff). hist: the texts its
// field held since its text or parts were last set from elsewhere, with their parts (pvReasonPlace).
/** @typedef {{sid:number,page:number,id:number,key:string,doc:string|null,visit:any,text:string,base:string,mode:string,rev:number,conflict:{note:string,rev:number}|null,from:number,via:ReasonPart[],seen:boolean,listed:boolean,writing:Promise<boolean>|null,saved:string|null,tried:ReasonTry[],clearTried:boolean,escArm:string,saveWhenBound?:boolean,onto?:number,hist?:ReasonHist}} ReasonSession */
// What a session's field held, for its undo and redo (pvReasonPlace).
/** @typedef {{last:{text:string,via:ReasonPart[]},seen:Map<string,ReasonPart[]>,size:number,landed:{doc:string|null,id:number,word:string,text:string}[]}} ReasonHist */
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
  return {sid:++PV_RSEQ,page,id,key,doc:DOC,visit:captureVisit(),text,base,mode:mode||(base.trim()?'replace':'add'),rev:rev===undefined?-1:rev,conflict:null,from:0,via:[],
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
  if(pvReasonDirty(r)&&!PV_WITHDRAWN.has(r.id)){rdDrop(r.doc,r.id); rdPut(r.doc,'p'+r.page,r.text,'',-1,{mode:'add',folded:true,from:r.via});
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
    // It becomes a part moved off its verdict, with that verdict's lost writes: one may have landed (#317: a reload let them
    // go, and the page's draft, opened on the newer verdict, wrote a reason already on the earlier one).
    const m=rdOff(k,x); if(!m.text.trim())continue; const j=rdJoin(pd,m);
    d[pk]={...x,text:j.text,base:'',rev:-1,mode:'add',folded:true,tried:[],from:j.from};}
  if(ch)rdSave(d);
  const shown=[...pages].filter(n=>n>0).sort((a,b)=>a-b); if(!shown.length)return; const first=shown[0];
  lineNote(tl('저장 안 된 이유 초안 {n}건 · 줄의 [초안 있음]이 엽니다 — {target}',{n:shown.length,target:pageTargetShort(first)}),NOTICE_KIND.INFO,
    {label:'보기',fn:()=>pvShowLine(first)},{literal:true,source:'reason-restore'});}
// Brings page `page`'s line into view and puts the focus on its draft's mark ('초안 있음') - before the saved reason, which
// comes first on the line and opens the popover too - else its reason control (pvFocusLine).
/** @param {number} page */
function pvShowLine(page){if(PV_SIDE){pvBring(page); pvStick();}   // beside the pages the panel is the line, once the page is read (verdict-panel.js)
  const l=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"]')); if(!l)return;
  if(!PV_SIDE){const blk=/** @type {HTMLElement} */(l.parentElement||l); blk.scrollIntoView({block:blk.getBoundingClientRect().height<=$('#left').clientHeight?'center':'end'});}
  requestAnimationFrame(()=>{if(pvIsReasonField(document.activeElement))return;   // the mark was already pressed: its field keeps the focus
    const m=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"] .pv-draft'));
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
// a failed save leaves the text as the page's draft ('초안 있음'), said. (Its text written meanwhile on a verdict it was moved
// off, pvReasonWrittenOff, leaves nothing to keep or write.)
/** @param {string} slot @param {number} id @param {string} key */
function pvReasonSettle(slot,id,key){const r=PV_DETACHED.get(slot); if(!r)return; PV_DETACHED.delete(slot); if(!r.text.trim())return;
  if(!id){lineNote(tl('판정 저장 실패 · 쓰던 이유는 이 쪽의 초안으로 남겼습니다 — {target}',{target:pvReasonName(r)}),NOTICE_KIND.WARN,null,{literal:true}); return;}
  rdMove(r.doc,'p'+r.page,id); Object.assign(r,{id,key,base:'',mode:'add',rev:-1,saveWhenBound:false,listed:false});
  pvReasonCommit(r,r.text.trim(),true);}
// Opens the popover on page `page`'s line for its current verdict - the person's own open one ([이유 추가], Enter, its saved
// reason, its kept draft): with that draft (unfolded), else the page's draft (moved to this verdict), else the saved reason
// to change. Another popover moves on first. A page's draft with no verdict of the person's to take it says so.
/** @param {number} page @param {boolean} focus */
function pvReasonOpen(page,focus){const cur=pvCurOf(page); if(viewerBlocked())return;
  // A save out on this line: the reason is the new verdict's, whose number is coming; the list still has the one it replaces.
  if(PV_BUSY.has(pvSlot(page))){pvReasonOpenPending(page); return;}
  if(PV_DETACHED.has(pvSlot(page))){pvReasonOpenPending(page); return;}   // its verdict's save is still out: that popover again
  if(!cur||!pvCanCancel(cur)){if(rdGet(DOC,'p'+page))lineNote(tl('이유를 붙일 내 판정이 없습니다 · 판정을 누르면 이 초안이 그 판정으로 갑니다 — {target}',{target:pageTargetShort(page)}),NOTICE_KIND.INFO,null,{literal:true,life:NOTICE_LIFE.TIMER}); return;}
  if(!(PV_REASON&&PV_REASON.id===cur.id&&pvReasonOn(page))){pvReasonLeave();
    if(!rdGet(DOC,cur.id))rdMove(DOC,'p'+page,cur.id);   // a page's draft goes to the verdict it now has
    const note=String(cur.note||''),d=rdGet(DOC,cur.id),rev=typeof cur.rev==='number'?cur.rev:-1;
    const r=d?pvReasonNew(page,cur.id,verdictOf(cur)||'',d.text,d.base,d.rev>=0?d.rev:rev,d.mode):pvReasonNew(page,cur.id,verdictOf(cur)||'',note,note,rev);
    if(d){r.tried=d.tried; r.via=d.from;}   // its writes whose answer was lost (one may have landed), and the pins it came from
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
  if(!det&&d)r.via=d.from;
  PV_REASON=r; PV_KEY_GUARD=false; hideTip(); drawPageVerdicts(); pvReasonFocus();}
// Page `page`'s save failed while a popover waited for its number: what was typed stays as the page's draft ('초안 있음'),
// said in one line, and the popover closes. As when a verdict is taken back while its reason is typed (pvReasonLost): when
// the field had the focus its line's draft mark takes it and the keys pressed next are not verdict keys (PV_KEY_GUARD) -
// a digit typed on would have saved a verdict; a focus elsewhere (the search, the composer) stays where it is.
/** @param {number} page */
function pvReasonUnbound(page){const r=PV_REASON; if(!r||r.id||r.page!==page||r.doc!==DOC)return;
  const pop=document.querySelector('#doc .pv-pop'),had=!!pop&&pop.contains(document.activeElement); PV_REASON=null;
  if(r.text.trim()){rdPut(r.doc,'p'+page,r.text,'',-1,{mode:'add',folded:true,from:r.via});
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
    // The draft it moves is a part moved off the verdict it leaves, with that verdict's lost writes, as rdMove makes it -
    // another session's write of it may still land there (moving on, then the draft opened again on that verdict and moved
    // here) - and keeps the parts it came with (not when others' lines were left out of it: their places changed).
    if(dirty){const k0=from||'p'+page; r.via=[...(own===r.text?r.via:[]),...(from?[rdPart(rdName(r.doc,from),{text:own,tried:r.tried})]:[])]; r.text=own;
      rdDrop(r.doc,k0); rdPut(DOC,id,own,'',-1,{mode:'add',from:r.via});}
    else if(from){r.text=''; r.via=[];}   // an unbound popover keeps what is typed
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
function pvReasonOwn(r){return rdOwn(r.mode,r.text,r.base);}
// The write of reason session r, out while its line's verdict changed to r.onto (pvReasonAfterSave), settled - ok: it was
// written. Its reason ends on one verdict. Written - or, its answer lost or a 5xx, found landed when the pin is read again
// (pvReasonLanded) - it stays on r's verdict, now an earlier one, and the status line says so ('이유는 이전 판정 #15 채택에
// 저장됨 · 지금 판정은 #16 보류'). Not landed (also refused, or the pin gone), its draft moves to the new verdict - or to the
// page's draft, when that verdict is no longer the line's or already has a draft or a popover - its failure and that
// [다시 시도] go, and the status line says where it went with [보기] - remembering the pins the draft came from before
// (from), as every move does, and this verdict while its write may land yet. A read that fails decides nothing: the
// status line says so with [다시 시도], which reads again. (pvReasonWrite and pvReasonFailed say nothing of such a write themselves.)
/** @param {ReasonSession} r @param {boolean} ok @param {number} page */
async function pvReasonOnto(r,ok,page){const to=r.onto,doc=r.doc,src='POST /api/pins/'+r.id+'/edit reason'; if(!to)return;
  const target=pvNameOn(doc,page,r.id),saved=()=>{r.onto=0; pvReasonSaidOn(doc,page,r.id,r.key);};
  if(ok){if(r.text.trim())saved(); else r.onto=0; return;}   // nothing of it was left to write: a pin it came from had it (pvReasonCommit)
  let p=/** @type {Pin|null|undefined} */(undefined);
  try{p=(await api('/api/pins/'+r.id,{what:'핀 읽기',silent:true})).data.pin;}
  catch(e){const x=/** @type {ApiError} */(e); if(!x||!x.status||x.status>=500){
      lineNote(tl('이유 저장 실패 · {why} — {target}',{why:tr('서버에 닿지 않습니다'),target}),NOTICE_KIND.ERR,{label:'다시 시도',fn:()=>pvReasonOnto(r,false,page)},{source:src,literal:true});
      return;}
    p=null;}
  const got=p&&!p.dropped_at?[...r.tried].reverse().find(a=>pvReasonLanded(a,/** @type {Pin} */(p))):null;
  PV_RETRY.delete(r);   // its [다시 시도] goes either way (sourceOk)
  if(got){r.saved=got.text; r.tried=[]; rdDrop(doc,r.id); sourceOk(src); pvReasonWrittenOff(doc,r.id,r.key,got.text,r); saved(); if(doc===DOC)loadPins().catch(()=>{}); return;}
  // Not landed - yet: one sent against the rev the pin still has may still be on its way. The draft keeps it as a part moved
  // off this verdict with that evidence, so a write of it on the new verdict fences it off first (pvReasonCheck, #327).
  const can=p&&!p.dropped_at?r.tried.filter(a=>a.rev>=(typeof p.rev==='number'?p.rev:0)):[];
  r.onto=0; r.tried=[]; sourceOk(src); const x=rdGet(doc,r.id)||{text:r.text,base:r.base,mode:r.mode,tried:[],from:r.via};
  const m=rdOff(can.length?rdName(doc,r.id):'',{...x,tried:can}),text=m.text,via=m.from;
  rdDrop(doc,r.id); if(!text.trim())return;
  const open=!!PV_REASON&&PV_REASON.doc===doc&&PV_REASON.page===page,cur=pvCurOn(doc,page);   // it moves with the pins it came from
  if(cur&&cur.id===to&&!open&&!rdGet(doc,to))rdPut(doc,to,text,'',-1,{mode:'add',folded:true,from:via});
  else{const j=rdJoin(rdGet(doc,'p'+page),{text,from:via}); rdPut(doc,'p'+page,j.text,'',-1,{mode:'add',folded:true,from:j.from});}
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
// remembers that all of it was moved off that verdict, with the verdict's lost writes, and the parts it came with (from):
// a [다시 시도] of the old write that lands later takes it away, also after it moved on again (pvReasonWrittenOff), and a
// write of it elsewhere first settles those lost writes (pvReasonCheck). Either way the line
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
  if(!back){const m=rdOff(rdName(doc,id),d); rdDrop(doc,id); if(!m.text.trim())return; const j=rdJoin(rdGet(doc,'p'+page),m); rdPut(doc,'p'+page,j.text,'',-1,{mode:'add',folded:true,from:j.from});}
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
  const t=pageTargetOf(p,META?META.kind:undefined); if(!t)return; const cur=pvCurOf(t.page); if(!cur||cur.id!==id)return;
  // A reason being written on another page stays as it is, and where the popover cannot show (the panel beside the pages shows the
  // reading page alone) none opens: the draft stays this verdict's, marked on its line or summary. Opened, it wrote the other
  // page's half text and took its field, and its own session wrote on the next verdict saved anywhere.
  if((PV_REASON&&PV_REASON.page!==t.page)||(PV_SIDE&&t.page!==PV_READ)){drawPageVerdicts(); return;}
  pvReasonLeave();
  const r=pvReasonNew(t.page,id,verdictOf(p)||'',d.text,d.base,d.rev,d.mode); r.tried=d.tried; r.via=d.from; r.listed=true; pvReasonSeeConflict(r,p); PV_REASON=r; drawPageVerdicts();}

// ---------------- Writing
// The one write of reason session r: text as its pin's note (pvReasonWrite). While a write is out it is that write - Enter
// and then moving on, another save or another document before the answer start no second one - and text the session has
// written is not written again. A failed write may be tried again. Resolves with whether the reason is written; once it
// is, its kept draft goes (unless more was typed meanwhile), so does every other place the text waits to be written - a
// part moved off the pin's key, the pins it was moved off (pvReasonWrittenOff) - and its lost writes are settled. The write
// is listed while it is out (PV_WRITES, with its session): a draft is not moved off the key it may still be written for
// (pvReasonUncancelDraft, pvReasonAfterSave). A reason ends on one verdict, so before text moved off other pins is written
// here, whatever may still put it there is settled first: a write out from one of those pins, or from a copy moved off
// this one, answers first (pvReasonKin), and the lost writes of those pins are read from the server (pvReasonCheck) - what
// landed leaves this text (pvReasonWrittenOff), what may still land is fenced off (pvReasonFence), and only what is left is
// written, nothing when nothing is. A pin that cannot be read or fenced leaves it unsure: nothing is written, the draft
// stays and the status line says the write failed, with [다시 시도]. (#317: the moved copy opened, and Enter pressed,
// before the old verdict's [다시 시도] answered - or its answer was lost after it landed, or a reload let its evidence go -
// and the reason landed on both verdicts.)
const PV_WRITES=/** @type {Map<string,{r:ReasonSession,w:Promise<boolean>}>} */(new Map());
// The sessions whose failure the status line offers [다시 시도] for (pvReasonFailed), with that message: a write elsewhere of
// their text takes it out of them and the message goes (pvReasonWrittenOff) - the [다시 시도] would write it a second time.
const PV_RETRY=/** @type {Map<ReasonSession,Notice>} */(new Map());
/** @param {ReasonSession} r @param {string} text @param {boolean} said @returns {Promise<boolean>} */
function pvReasonCommit(r,text,said){if(r.saved===text)return Promise.resolve(true);
  if(!r.writing){const k=rdName(r.doc,r.id),kin=pvReasonKin(r); let sent=text;
    const go=kin||r.via.some(p=>p.tried.length)?(kin||Promise.resolve()).then(()=>pvReasonCheck(r)).then(sure=>{sent=r.text.trim(); if(!sent)return true;
        if(sure!==true){pvReasonFailed(r,sent,sure); return false;}   // whether it is, or will be, on a pin it came from is not known: kept, not written
        return pvReasonWrite(r,sent,said);})
      :pvReasonWrite(r,text,said);
    const w=go.then(ok=>{r.writing=null; const o=PV_WRITES.get(k); if(o&&o.w===w)PV_WRITES.delete(k);
      if(ok&&sent){r.saved=sent; r.tried=[]; PV_RETRY.delete(r); const d=rdGet(r.doc,r.id); if(d&&d.text.trim()===sent)rdDrop(r.doc,r.id); pvReasonWrittenOff(r.doc,r.id,r.key,sent,r);}
      return ok;});
    r.writing=w; PV_WRITES.set(k,{r,w});}
  return r.writing;}
// The writes out (PV_WRITES) that may put reason session r's text on another verdict - those of the pins it was moved off
// (r.via) and of the copies moved off its own pin -, all answered (failed ones too), or null when none is out.
/** @param {ReasonSession} r @returns {Promise<unknown>|null} */
function pvReasonKin(r){const k=rdName(r.doc,r.id);
  const ws=[...PV_WRITES].filter(([x,o])=>o.r!==r&&(r.via.some(p=>p.k===x)||o.r.via.some(p=>p.k===k))).map(([,o])=>o.w.catch(()=>false));
  return ws.length?Promise.all(ws):null;}
// Before session r writes text moved off other pins: each of those pins whose writes lost their answer (its parts' tried)
// is read as the server has it now, and every such write is judged by the pin's rev (pvReasonLanded). One that landed with
// a part's very text put it on that pin: the part leaves r and every other copy, and its failure goes (pvReasonWrittenOff);
// one the pin's rev is past and that did not land never will, and is let go. One sent against the rev the pin still has
// may land yet - a request that lost its answer may still be on its way to the server -, so it is fenced off first
// (pvReasonFence): then it never lands, or it landed first and is judged so, and only then is the copy written (#327: the
// copy was written, and the old request landed after it). Resolves true when every pin is settled, else with what left one
// unknown - a read or a fence without an answer, a 5xx, a refusal (null: no answer at all): nothing is decided for it.
/** @param {ReasonSession} r @returns {Promise<true|ApiError|null>} */
async function pvReasonCheck(r){let sure=/** @type {true|ApiError|null} */(true);
  for(const k of new Set(r.via.filter(p=>p.tried.length).map(p=>p.k))){const id=Number(k.slice(k.lastIndexOf(':')+1)); let p=/** @type {Pin|null} */(null);
    try{p=(await api('/api/pins/'+id,{what:'핀 읽기',silent:true})).data.pin||null;}
    catch(e){const x=/** @type {ApiError} */(e); if(!x||!x.status||x.status>=500){sure=x||null; continue;}}
    for(let fenced=false;;fenced=true){const pin=p&&!p.dropped_at?p:null,rev=pin&&typeof pin.rev==='number'?pin.rev:Infinity;
      for(;;){const q=pin?r.via.find(q=>q.k===k&&q.tried.some(a=>rdNorm(a.text)===rdNorm(r.text.slice(q.s,q.e))&&pvReasonLanded(a,pin))):null; if(!q||!pin)break;
        const a=/** @type {ReasonTry} */(q.tried.find(a=>rdNorm(a.text)===rdNorm(r.text.slice(q.s,q.e))&&pvReasonLanded(a,pin)));
        pvReasonWrittenOff(r.doc,id,verdictOf(pin)||'',a.text,null);
        if(r.via.includes(q))break;}   // not taken out (cannot be): stop
      pvReasonEvidence(r,k,t=>t.filter(a=>a.rev>=rev));
      if(!pin||!r.via.some(q=>q.k===k&&q.tried.length))break;   // none may land now
      if(fenced){sure=null; break;}   // a fence's 409 brings a newer pin, past them all: never here
      const f=await pvReasonFence(id,pin);
      if('fenced' in f){pvReasonEvidence(r,k,()=>[]); break;}   // none landed, and none can now
      if('unknown' in f){sure=f.unknown; break;}
      p=f.pin;}}   // something changed the pin first - one of them landing, perhaps: judged again on the pin as it is
  return sure;}
// Fences off what may still land on pin id - read just now as p - of the reason writes that lost their answer: those sent
// against the rev p has. Its note is written back as it is, against that rev. Accepted, the pin's rev is past every such
// write, so its request is refused with a 409 when it arrives (an edit's base_rev, docs/handbook/api.md), and none had
// landed (the rev would not have been p's). Refused with a 409, something changed the pin first - perhaps one of them,
// landing -, and the answer brings the pin as it is. A pin gone takes none of them. Anything else - no answer, a 5xx,
// another refusal - decides nothing; a fence whose answer was lost may land later, and is then no lost write's landing
// unless the note is exactly what that write made (pvReasonLanded). Nothing of the note changes: the pin's edited_at and
// rev do.
/** @param {number} id @param {Pin} p @returns {Promise<{fenced:true}|{pin:Pin|null}|{unknown:ApiError|null}>} */
async function pvReasonFence(id,p){
  try{const {status,data}=await api('/api/pins/'+id+'/edit',{method:'POST',intent:'reason-fence',silent:true,expect:[409],
      body:{note:String(p.note||''),base_rev:typeof p.rev==='number'?p.rev:0}});
    if(status!==409)return {fenced:true}; const q=data&&data.pin; return q?{pin:q}:{unknown:null};}
  catch(e){const x=/** @type {ApiError} */(e); return x&&x.status===404?{pin:null}:{unknown:x||null};}}
// Session s's evidence of pin key k's lost writes (ReasonPart.tried) made fn(tried): in its text's parts and in those of the
// texts its field may come back to (hist, pvReasonPlace).
/** @param {ReasonSession} s @param {string} k @param {(t:ReasonTry[])=>ReasonTry[]} fn */
function pvReasonEvidence(s,k,fn){const m=(/** @type {ReasonPart[]} */ps)=>ps.map(p=>p.k===k?{...p,tried:fn(p.tried)}:p);
  s.via=m(s.via); const h=s.hist; if(!h)return; h.last={text:h.last.text,via:m(h.last.via)}; for(const [t,v] of h.seen)h.seen.set(t,m(v));}
// The sessions that may still write: the open popover, those moved away from while their save is out, those writing, and
// those whose failure offers [다시 시도].
function pvReasonLive(){return /** @type {Set<ReasonSession>} */(new Set([PV_REASON,...PV_DETACHED.values(),...[...PV_WRITES.values()].map(o=>o.r),...PV_RETRY.keys()].filter(Boolean)));}
// Pin id (verdict word `word`) of document doc has text as its reason now - session w wrote it, or (w null) a write that lost
// its answer is found landed. A reason ends on one verdict, so the text leaves every other place it waits to be written:
// the parts moved off that pin with that text (rdCut) - in the drafts kept (rdWrittenOff) and in the sessions holding one
// (pvReasonLive), each keeping what else it holds: lines typed around it, another draft joined to it, the same sentence
// typed again -; and, w's text holding parts moved off other pins (w.via), the sessions of those pins whose text is such a
// part. The sessions of pin id with that text have it saved. A session left with nothing has nothing to write: its
// [다시 시도] goes, and the open popover closes (pvReasonTaken).
/** @param {string|null} doc @param {number} id @param {string} word @param {string} text @param {ReasonSession|null} w */
function pvReasonWrittenOff(doc,id,word,text,w){const k=rdName(doc,id),n=rdNorm(text); rdWrittenOff(doc,id,text);
  for(const s of pvReasonLive()){if(s===w)continue; if(s.hist)s.hist.landed.push({doc,id,word,text});   // an undo may bring such a part back (pvReasonFollow)
    const c=rdCut(s.text,s.via,k,text);
    if(c){s.text=c.text.trim()?c.text:''; s.via=s.text?c.from:[]; if(!s.text)pvReasonGone(s); if(s===PV_REASON)pvReasonTaken(s,doc,id,word,!!s.text); continue;}
    if(s===PV_REASON||!s.id||!s.text.trim())continue;
    if(rdName(s.doc,s.id)===k&&rdNorm(s.text)===n){s.saved=s.text.trim(); s.tried=[]; pvReasonGone(s);}   // its own lost write, found landed
    else if(w&&pvReasonCameFrom(w,s))pvReasonGone(s);}}
// Session s, left with nothing to write: its text goes and so does its [다시 시도].
/** @param {ReasonSession} s */
function pvReasonGone(s){s.text=''; s.via=[]; const m=PV_RETRY.get(s); PV_RETRY.delete(s); if(m)endNotice(m,true);}
// Whether session s - a verdict's, with text - holds what session w's copy came from: a part of w's text moved off s's pin
// is s's very text.
/** @param {ReasonSession} w @param {ReasonSession} s */
function pvReasonCameFrom(w,s){const sk=rdName(s.doc,s.id),t=rdNorm(s.text); return w.via.some(p=>p.k===sk&&rdNorm(w.text.slice(p.s,p.e))===t);}
// The write of copy session w lost its answer (or met a 5xx): it may have landed on w's verdict, and its [다시 시도] or a
// later write there settles that (pvReasonBody). The sessions its copy came from have nothing left to write: their
// [다시 시도] goes - pressed, it put the reason on their verdict too, and w's request landed as well (#327, the order after
// the fence: w's write is the one that may still land). The open popover is never such a session.
/** @param {ReasonSession} w */
function pvReasonHandedOn(w){for(const s of pvReasonLive())if(s!==w&&s!==PV_REASON&&s.id&&s.text.trim()&&pvReasonCameFrom(w,s))pvReasonGone(s);}
// The open popover s held a reason that pin id (verdict word `word`) of document doc has just been given, on a verdict s's
// draft was moved off (pvReasonWrittenOff). With something left - lines typed around it, a draft joined to it - it stays
// with that, and the status line says the rest went. With nothing left it closes, and the status line says where the
// reason is, as when a write out at a verdict change lands ('이유는 이전 판정 #15 채택에 저장됨 · 지금 판정은 #16 보류',
// pvReasonSaidOn): left open, its Enter or moving on wrote the reason on this verdict as well. When the popover had the
// focus - typed in, or waiting on its Enter (the field disabled, the focus nowhere) - the line's reason control takes it and
// the keys pressed next are not verdict keys (PV_KEY_GUARD): the person was typing text, or about to.
/** @param {ReasonSession} s @param {string|null} doc @param {number} id @param {string} word @param {boolean} part */
function pvReasonTaken(s,doc,id,word,part){
  if(part){pvRefill(s.page); const l=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+s.page+'"]')); if(l)pvReasonAfterDraw(l);
    lineNote(tl('이유 일부는 이전 판정 #{id} {word}에 저장됨 · 초안에는 나머지를 남겼습니다 — {target}',{id,word:verdictLabel(word,doc),target:pvReasonName(s)}),
      NOTICE_KIND.INFO,null,{literal:true,life:NOTICE_LIFE.TIMER});
    return;}
  const a=document.activeElement,pop=document.querySelector('#doc .pv-pop'),had=!!pop&&!!a&&pop.contains(a)||(!!s.writing&&(!a||a===document.body));
  PV_REASON=null; drawPageVerdicts(); if(had){PV_KEY_GUARD=true; if(!pvFocusLine(s.page))searchToPage();}
  pvReasonSaidOn(doc,s.page,id,word);}
// Says that pin id's reason (verdict word key) was saved, about page `page` of document doc - on an earlier verdict when the
// line's current verdict is another one now.
/** @param {string|null} doc @param {number} page @param {number} id @param {string} key */
function pvReasonSaidOn(doc,page,id,key){const target=pvNameOn(doc,page,id),word=verdictLabel(key,doc),now=pvCurOn(doc,page),nk=now?verdictOf(now):null;
  lineNote(now&&nk&&now.id!==id?tl('이유는 이전 판정 #{id} {word}에 저장됨 · 지금 판정은 #{cur} {now} — {target}',{id,word,cur:now.id,now:verdictLabel(nk,doc),target})
    :tl('이유 저장됨 · 판정 #{id} {word} — {target}',{id,word,target}),NOTICE_KIND.OK,null,{literal:true,life:NOTICE_LIFE.TIMER});}
// [다시 시도] on a failed reason: the session's draft as it is now (after a failed Enter the field stays open and may have been
// corrected) written as its one write. A field still open for it waits while it writes, and closes only when what was
// written is what it holds.
/** @param {ReasonSession} r */
function pvReasonRetry(r){const text=r.text.trim(); if(!text||r.writing)return;
  const w=pvReasonCommit(r,text,true); if(PV_REASON===r)drawPageVerdicts();
  w.then(ok=>{if(PV_REASON!==r)return; if(ok&&r.text.trim()===r.saved)pvReasonEnd(false); else drawPageVerdicts();});}
// Where lost write a's text sits in note when the note is what a made of the one it was sent against - its pre, its stamp,
// its text, its post - with nothing after but lines added under it since (a later note_append's '\n(추가 …', or an agent's
// '\r\n' one), or nothing at all when `exact` (no change came after it): the text's [start, end], else null.
/** @param {ReasonTry} a @param {string} note @param {boolean} [exact] @returns {number[]|null} */
function pvReasonTryAt(a,note,exact){if(!note.startsWith(a.pre))return null; let i=a.pre.length;
  if(a.stamp){const m=/^\(추가 \d{1,2}:\d{2}\) /.exec(note.slice(i)); if(!m)return null; i+=m[0].length;}
  const end=i+a.text.length; if(note.slice(i,end)!==a.text||note.slice(end,end+a.post.length)!==a.post)return null;
  const rest=note.slice(end+a.post.length); return !rest||(!exact&&/^\r?\n/.test(rest))?[i,end]:null;}
// Whether lost write a landed, from pin p as the server reads now. Every reason write is sent against the rev it read
// (base_rev), so a write lands only as the change right after that rev, or never - a copy still on its way meets a 409 once
// anything else changed the pin. So: p's rev not past a.rev - it has not landed (a write to try again, against that same rev:
// one of the two lands at most); past it, it landed when the note is what it made (pvReasonTryAt) and, when that was the only
// change since, the change was this person's (edited_by) and the note is exactly what it made, with no line under it - that
// change was it, or another one: someone's note that happens to read the same, or a fence that wrote the note back as it was
// (pvReasonFence), is not this write. Text the note held already - someone's, or the person's own earlier line - is no sign
// of it: a reason repeated is a new one. (Two or more changes since leave the note to say it: someone writing the very same
// text under the same note in that window would read as this write.)
/** @param {ReasonTry} a @param {Pin} p */
function pvReasonLanded(a,p){const rev=typeof p.rev==='number'?p.rev:0,one=rev===a.rev+1;
  return rev>a.rev&&!!pvReasonTryAt(a,String(p.note||''),one)&&(!one||isMe(p.edited_by));}
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
  }catch(e){const x=/** @type {ApiError} */(e); if(sent&&(!x||!x.status||x.status>=500)){r.tried.push(sent); rdTriedOff(r.doc,r.id,sent); pvReasonHandedOn(r);}   // it may have landed - so may the copies moved off it know, and what it was copied from lets it be
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
// [x] or its action (STICKY), or until a write elsewhere puts its text on another verdict (PV_RETRY, pvReasonWrittenOff).
// (A write without an answer is remembered by pvReasonWrite, r.tried: it may have landed.) The
// reason for a pin this person has withdrawn meanwhile goes quietly (PV_WITHDRAWN).
/** @param {ReasonSession} r @param {string} text @param {ApiError|null} e @param {string} [why0] */
function pvReasonFailed(r,text,e,why0){const st=e&&typeof e.status==='number'?e.status:0,again=!why0&&(!st||st>=500);
  if(!rdMovedOff(r.doc,r.id).length)rdPut(r.doc,r.id,r.text.trim()?r.text:text,r.base,r.rev,{mode:r.mode,tried:r.tried,from:r.via});   // moved off meanwhile: that copy is the draft
  if(PV_WITHDRAWN.has(r.id)||r.onto)return;   // withdrawn, or its line's verdict changed meanwhile (pvReasonOnto decides)
  const why=why0||(st?(e&&e.data&&errText(e.data))||'HTTP '+st:tr('서버에 닿지 않습니다'));
  const n=lineNote(tl('이유 저장 실패 · {why} — {target}',{why,target:pvReasonName(r)}),NOTICE_KIND.ERR,again?{label:'다시 시도',fn:()=>pvReasonRetry(r)}:null,
    {source:'POST /api/pins/'+r.id+'/edit reason',literal:true});
  if(again&&n)PV_RETRY.set(r,n); else PV_RETRY.delete(r);
  if(PV_REASON!==r&&r.doc===DOC)drawPageVerdicts();}   // the line marks the draft it keeps
// A replace found the note changed elsewhere since it was read (newer note q): nothing is written over it. The draft is kept,
// the popover - when open - shows the newer note whole and offers [그 위에 쓰기] (pvReasonReapply); every further 409 shows
// the note it found. The status line says so, result first, with [메모 보기] (the pin's card), and the line is read again so
// it shows the newer note too.
/** @param {ReasonSession} r @param {string} text @param {Pin} q */
function pvReasonConflict(r,text,q){r.conflict={note:String(q.note||''),rev:typeof q.rev==='number'?q.rev:-1};
  if(!rdMovedOff(r.doc,r.id).length)rdPut(r.doc,r.id,r.text.trim()?r.text:text,r.base,r.rev,{mode:r.mode,tried:r.tried,from:r.via});
  if(!r.onto)lineNote(tl('이유 저장 안 함 · 그사이 다른 곳에서 메모가 바뀌었습니다 — {target}',{target:pvReasonName(r)}),NOTICE_KIND.WARN,{label:'메모 보기',fn:()=>gotoPinRef(r.id)},
    {source:'POST /api/pins/'+r.id+'/edit reason',literal:true});
  if(r.doc===DOC){if(PV_REASON===r)pvRefill(r.page); loadPins().catch(()=>{});}}
// [그 위에 쓰기] in a popover that shows a newer note: the person has read it and puts their text over it - a replace, made
// from that note and written against its rev (also when it is empty: never an append that needs no rev).
function pvReasonReapply(){const r=PV_REASON,f=pvReasonField(); if(!r||!r.conflict||!f||r.writing)return;
  r.base=r.conflict.note; r.rev=r.conflict.rev; r.mode='replace'; r.conflict=null; rdKeep(r); if(!pvReasonDirty(r)){pvRefill(r.page); return;} pvReasonSave(f);}
// Enter (or [저장]): the text written as the note and the popover closed. Empty is a skip - a saved reason stays - and the
// reason as it is saved has nothing to write. While the request is out the field waits (read-only, keeping the focus: disabled it
// dropped it to nothing and the next digit was a verdict key; the popover says '저장 중…'); a failure leaves the text in it
// for another Enter.
/** @param {HTMLTextAreaElement} f */
async function pvReasonSave(f){const r=PV_REASON; if(!r||r.writing||f.readOnly)return; r.text=f.value; const text=r.text.trim();
  if(!r.id){if(text){r.saveWhenBound=true; rdKeep(r); pvRefill(r.page);} return;}   // its verdict has no number yet: saved once it has
  if(!text||text===r.base.trim()){rdDrop(r.doc,r.id||'p'+r.page); pvReasonEnd(true); return;}
  if(r.conflict){pvRefill(r.page); pvReasonFocus(); return;}   // the newer note is on screen: [그 위에 쓰기] or [메모 보기] first
  const w=pvReasonCommit(r,text,!!r.from); f.readOnly=true; pvRefill(r.page); const ok=await w;
  if(PV_REASON!==r)return;   // closed meanwhile (moved on, the undo, another document): its one write had the text
  if(ok){pvReasonEnd(true); return;}
  drawPageVerdicts(); pvReasonFocus();}
// Esc in the field, or [닫기] (how 'btn'): with nothing unsaved the popover closes. With text the first press lets the focus
// go to the PDF area - the keys then change the verdict, the draft following - and says that the next one drops it; the
// next one drops it (the kept draft too).
/** @param {string} how */
function pvReasonEsc(how){const r=PV_REASON; if(!r||(how==='key'&&r.writing))return;
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
<textarea class="pv-reason" rows="1" maxlength="4000" autocomplete="off" enterkeyhint="done" data-id="s${r.sid}" data-pin="${r.id}"${r.writing?html` readonly aria-busy="true"`:''} \
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
// click save's, as before. Every other line with such a verdict holds that [이유 추가] hidden (the identifier's way, hidden:
// never shown, focused or heard), which pvFit lays out unseen (#doc.pv-measure, components.css): every line is fitted as the
// reading line it may become, so becoming it or leaving it never stacks or unstacks a line (#308 review: a line with an
// earlier link stacked only while read). Every name holds the words the button shows. Nothing for the reason the open
// popover holds.
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
data-tip="${tr('이 판정의 이유를 씁니다. 메모로 붙습니다')}">${tr('이유 추가')}</button></span>`
    :html`<span class="pv-ra" hidden>${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" tabindex="-1">${tr('이유 추가')}</button></span>`;   // no data-act: no focus or press finds it
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
// Every input keeps the draft (rdPut), with the parts moved into it placed where they are now (pvReasonPlace) - a part
// brought back whose text has landed on its pin meanwhile leaves at once (pvReasonFollow) - and lets a first Esc go; the
// line follows its emptiness (the state).
$('#doc').addEventListener('input',e=>{const f=e.target; if(!pvIsReasonField(f))return; const r=PV_REASON; if(!r||f.dataset.id!=='s'+r.sid)return;
  const was=r.text; r.text=f.value; r.via=pvReasonPlace(r,was,f.selectionEnd); r.escArm=''; pvReasonFollow(r); rdKeep(r); pvReasonGrow(f); pvRefill(r.page);});
// The parts of session r's text once an input made it r.text from `was`, the caret at `caret`. A text the field held before
// - back by an undo or a redo, a paste or a typed letter taken back, a composition given up - has the parts it had then: an
// edit inside a part lets it go (rdEdit), and the undo that put the text back left it with none, so the text was no longer
// known as moved off its pin, and a write that landed there left it in the copy, to be written twice (#327). The undo
// and redo records are the texts kept (hist.seen, the newest parts for each text), with their parts - their lost writes
// kept up to date (pvReasonEvidence) and the writes that landed meanwhile on the pins they came from (hist.landed,
// pvReasonFollow) -, since the session's text or parts were last set from elsewhere: opened, moved to a new verdict, a part
// taken out. What the field held before that is not this session's to come back to with those parts - a part taken out
// because its text landed on its pin and typed back is a new reason, as it is when it is typed again (and the browser lets
// the field's own undo records go when its text is set). Any other text is placed by rdEdit. Texts with parts are kept
// until then, however many: one let go, the undo past it brought the text back without its part again. Texts without
// one go oldest first past PV_HIST_CHARS characters - one missed is placed by rdEdit, which may keep a part the text had
// meanwhile, never invents one.
const PV_HIST_CHARS=200000;
/** @param {ReasonSession} r @param {string} was @param {number} caret @returns {ReasonPart[]} */
function pvReasonPlace(r,was,caret){const same=(/** @type {ReasonPart[]} */x,/** @type {ReasonPart[]} */y)=>x.length===y.length&&x.every((p,i)=>p.k===y[i].k&&p.s===y[i].s&&p.e===y[i].e);
  let h=r.hist; if(!h||h.last.text!==was||!same(h.last.via,r.via)){h={last:{text:was,via:r.via},seen:new Map(),size:0,landed:[]}; pvHistKeep(h,was,r.via);}
  const back=h.seen.get(r.text),via=back!==undefined?back:rdEdit(r.via,was,r.text,caret);
  pvHistKeep(h,r.text,via); h.last={text:r.text,via}; r.hist=h; return via;}
// Record h keeps text with its parts, as the newest; past PV_HIST_CHARS it lets the oldest texts without a part go.
/** @param {ReasonHist} h @param {string} text @param {ReasonPart[]} via */
function pvHistKeep(h,text,via){if(h.seen.has(text)){h.size-=text.length; h.seen.delete(text);} h.seen.set(text,via); h.size+=text.length;
  for(const [t,v] of h.seen){if(h.size<=PV_HIST_CHARS)break; if(v.length||t===text)continue; h.seen.delete(t); h.size-=t.length;}}
// After an input, session r's text holds a part whose very text landed on the pin it was moved off while the part was not
// in the text (an edit inside it had let it go, and an undo brought it back, pvReasonPlace): the part leaves now, as it
// would have then (pvReasonWrittenOff) - with something left the popover keeps that and says the rest went, with nothing
// left it closes and says where the reason is (pvReasonTaken). Left in, Enter wrote it on this verdict as well.
/** @param {ReasonSession} r */
function pvReasonFollow(r){const h=r.hist; if(!h||!h.landed.length)return;
  for(const L of h.landed){const c=rdCut(r.text,r.via,rdName(L.doc,L.id),L.text); if(!c)continue;
    r.text=c.text.trim()?c.text:''; r.via=r.text?c.from:[]; if(!r.text)pvReasonGone(r); if(r===PV_REASON)pvReasonTaken(r,L.doc,L.id,L.word,!!r.text); return;}}
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
  // On a control of the line whose digit key's save is out the Enter is that intent too: the focus may rest on any of them.
  const l=!!t&&!!t.closest&&!t.closest('.pv-pop')?/** @type {HTMLElement|null} */(t.closest('#doc .pv')):null,n=l?Number(l.dataset.page)||0:0;
  if(n&&PV_KEY_OUT.has(pvSlot(n))&&n===pvReadingAt()){e.preventDefault(); e.stopImmediatePropagation(); pvReasonOpenPending(n); return;}
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
