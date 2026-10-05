// ------------------------------------------------ The composer draft, kept per tab (docs/handbook/viewer.md §패널 정리)
// A draft - the composer's selection, box, note, kind and assignee, or a note waiting for the next pick - is written to
// sessionStorage on every edit (debounced 300ms, flushed when the page hides) under draftKey(label, document), so leaving the
// page - a reload, the back gesture past the sheet - never loses it, and this tab's next boot restores it (restoreDraft). Saving
// clears it; a discard clears it once its undo window is over (DRAFT.holds has that document's undo). Only this tab sees it.
// The tab owns the debounce timer and the active document's draft key; a discard's undo holds its own document's key.
const DRAFT={timer:/** @type {ReturnType<typeof setTimeout>|0} */(0),ready:false,holds:new Map(),key:/** @type {string|null} */(null),
  origin:/** @type {{key:string|null,value:string|null,current:Selection|null}|null} */(null)};
// Keep a discarded draft until its undo (note, on the status line) leaves, unless a newer draft replaced it first.
/** @param {Notice} note */
function holdDraftUntil(note){let value=/** @type {string|null} */(null); try{if(DRAFT.key)value=sessionStorage.getItem(DRAFT.key);}catch(e){}
  const held={note,key:DRAFT.key,value}; if(held.key)DRAFT.holds.set(held.key,held);
  note.gone=()=>{if(!held.key||DRAFT.holds.get(held.key)!==held)return; DRAFT.holds.delete(held.key);
    if(DRAFT.key===held.key&&DRAFT.ready&&draftRecord()){syncDraft();return;}   // a restored or newer active draft wins, even with identical bytes
    if(held.key&&held.value){try{if(sessionStorage.getItem(held.key)===held.value){sessionStorage.removeItem(held.key);
      if(DRAFT.key===held.key)DRAFT.key=null;}}catch(e){}}};}
// The storage key of a draft: one per instance label and document.
function draftKey(label,doc){return 'limnDraft:'+encodeURIComponent(label||'')+':'+doc;}
// What a stored draft brings back on this document and build: 'full' (selection, box, note) when its box was drawn on this build,
// 'note' (the note waits for the next pick) when the build changed or no selection had come back yet, null for nothing to keep,
// another document, or another record version.
function draftRestore(rec,doc,build){if(!rec||rec.v!==1||rec.doc!==doc)return null;
  if(rec.cur&&rec.build===build)return 'full'; return String(rec.note||'').trim()?'note':null;}
// The draft on screen now, or null: the open composer (with its pick, or a note while the pick is still running) or a note
// kept in the hidden composer for the next pick.
function draftRecord(){const n=$('#note'),open=!$('#composer').hidden,note=n.value,cur=open?COMPOSE.current:null;
  if(!cur&&!note.trim())return null;
  return {v:1,doc:(cur&&cur.doc)||DOC,build:(cur&&cur.pdf_build)||(META&&META.pages_build)||'',cur,note,
    mentions:n._mentions?Array.from(n._mentions):[],kind:KIND_NEW,assign:{v:ASSIGN_NEW.v,touched:ASSIGN_NEW.touched}};}
// Every edit schedules a write (no-op until the boot restore has run, so booting never overwrites the stored draft).
function saveDraftSoon(){if(!DRAFT.ready)return; clearTimeout(DRAFT.timer); DRAFT.timer=setTimeout(syncDraft,300);}
// Writes the draft now, or removes it when there is nothing to keep - unless a discard's undo still holds it.
function syncDraft(){clearTimeout(DRAFT.timer); DRAFT.timer=0; if(!DRAFT.ready||!META)return; const rec=draftRecord();
  try{if(rec){const k=draftKey(META.label,rec.doc); DRAFT.holds.delete(k);   // a newer draft replaces a discarded one
      sessionStorage.setItem(k,JSON.stringify(rec)); DRAFT.key=k; return;}
    const held=DRAFT.holds.get(DRAFT.key); if(held&&NOTICES.has(held.note.n))return;
    if(DRAFT.key)sessionStorage.removeItem(DRAFT.key); DRAFT.key=null;}catch(e){}}
// Bind an in-flight pin save to the exact stored draft it sent; later documents and selections own their own records.
function savedDraftSnapshot(){syncDraft(); if(!DRAFT.key)return null;
  try{return {doc:DOC,key:DRAFT.key,value:sessionStorage.getItem(DRAFT.key)};}catch(e){return null;}}
// A returned visit may clear the original draft only while its restored selection and every unsaved field still match the submitted record.
function restoredDraftOwns(snap){const origin=DRAFT.origin;
  if(!snap||!snap.value||!origin||DOC!==snap.doc||DRAFT.key!==snap.key||origin.key!==snap.key||origin.value!==snap.value||
      origin.current!==COMPOSE.current)return false;
  const rec=draftRecord(); if(!rec||JSON.stringify(rec)!==snap.value)return false;
  try{return sessionStorage.getItem(snap.key)===snap.value;}catch(e){return false;}}
// A successful save may discard its parked draft only while that record is unchanged and its document is away.
function clearSavedDraft(snap){if(!snap||!snap.value||DOC===snap.doc)return;
  try{if(sessionStorage.getItem(snap.key)===snap.value)sessionStorage.removeItem(snap.key);}catch(e){}}
// Finish one document's draft before a switch; later debounce and pagehide callbacks must not write it under the next document.
function parkDraft(){syncDraft(); clearTimeout(DRAFT.timer); DRAFT.timer=0; DRAFT.ready=false; DRAFT.key=null; DRAFT.origin=null;}
// Start the next document with its own note and assignment before restoring any stored draft for it.
function openDraftDoc(){const n=$('#note'); n.value=''; n._mentions=null; ASSIGN_NEW.v=ASSIGNEE_AGENT; ASSIGN_NEW.touched=false;
  setKind(KIND_REQ.FIX); mentionPreview(n); autoGrow(n); restoreDraft();}
addEventListener('pagehide',syncDraft);
document.addEventListener('visibilitychange',()=>{if(document.hidden)syncDraft();});
// Boot: brings back this tab's draft for the document on screen and says so on the status line with [버리기], until the next
// press elsewhere. A full restore redraws the box and opens a collapsed panel or sheet (not remembered); a note-only one leaves
// the note in the note field for the next pick. [버리기] is the usual discard (a full draft gets its undo; the draft goes once
// that window is over).
function restoreDraft(){let rec=/** @type {any} */(null),raw=/** @type {string|null} */(null); const k=META?draftKey(META.label,DOC):null; DRAFT.origin=null;
  try{raw=k?sessionStorage.getItem(k):null; rec=JSON.parse(raw||'null');}catch(e){rec=null;}
  const how=draftRestore(rec,DOC,META&&META.pages_build); DRAFT.key=rec?k:null; DRAFT.ready=true;
  if(!how){syncDraft(); return;}
  const n=$('#note'); n.value=rec.note||''; n._mentions=rec.mentions&&rec.mentions.length?new Set(rec.mentions):null;
  setKind(rec.kind); Object.assign(ASSIGN_NEW,rec.assign||{}); renderAssignNew(); mentionPreview(n); autoGrow(n);
  if(how==='full'){const c=rec.cur,pg=document.getElementById('p'+c.page);
    if(pg&&Array.isArray(c.frac)){const b=newBox(pg),f=c.frac; drawBox(b,f[0],f[1],f[0]+f[2],f[1]+f[3]); b.classList.add('pending'); pendingBadge(b,'새 핀'); COMPOSE.box=b;}
    COMPOSE.current=c; recomputeOverlap(); SNIP_OPEN=false; $('#c-err').hidden=true; $('#c-body').hidden=false; $('#composer').hidden=false;
    renderComposer(); DRAFT.origin={key:k,value:raw,current:c}; setSide(true); applySide(); if(LAYOUT!==LAYOUT_MODE.WIDE)revealBox(COMPOSE.box);}
  lineNote(how==='full'?'작성 중이던 메모를 되살렸습니다':'작성 중이던 메모를 되살렸습니다 — PDF가 바뀌어 자리를 다시 골라야 합니다',NOTICE_KIND.INFO,
    {label:'버리기',tip:'되살린 선택과 메모를 버립니다',fn:()=>{if(!$('#composer').hidden)discardSelection(); else{cancelSelection(true); syncDraft();}}},
    {life:NOTICE_LIFE.CLICK});}
