// ------------------------------------------------ The composer draft, kept per tab (docs/handbook/viewer.md §패널 정리)
// A draft - the composer's selection, box, note, kind and assignee, or a note waiting for the next pick - is written to
// sessionStorage on every edit (debounced 300ms, flushed when the page hides) under draftKey(label, document), so leaving the
// page - a reload, the back gesture past the sheet - never loses it, and this tab's next boot restores it (restoreDraft). Saving
// clears it; a discard clears it once its undo window is over (DRAFT_HOLD = that toast). Only this tab sees it.
let DRAFT_T=0,DRAFT_READY=false,DRAFT_HOLD=null,DRAFT_KEY_AT=null;
// The storage key of a draft: one per instance label and document.
function draftKey(label,doc){return 'limnDraft:'+encodeURIComponent(label||'')+':'+doc;}
// What a stored draft brings back on this document and build: 'full' (selection, box, note) when its box was drawn on this build,
// 'note' (the note waits for the next pick) when the build changed or no selection had come back yet, null for nothing to keep,
// another document, or another record version.
function draftRestore(rec,doc,build){if(!rec||rec.v!==1||rec.doc!==doc)return null;
  if(rec.cur&&rec.build===build)return 'full'; return String(rec.note||'').trim()?'note':null;}
// The draft on screen now, or null: the open composer (with its pick, or a note while the pick is still running) or a note
// kept in the hidden composer for the next pick.
function draftRecord(){const n=$('#note'),open=!$('#composer').hidden,note=n.value,cur=open?CUR:null;
  if(!cur&&!note.trim())return null;
  return {v:1,doc:(cur&&cur.doc)||DOC,build:(cur&&cur.pdf_build)||(META&&META.pages_build)||'',cur,note,
    mentions:n._mentions?Array.from(n._mentions):[],kind:KIND_NEW,assign:{v:ASSIGN_NEW.v,touched:ASSIGN_NEW.touched}};}
// Every edit schedules a write (no-op until the boot restore has run, so booting never overwrites the stored draft).
function saveDraftSoon(){if(!DRAFT_READY)return; clearTimeout(DRAFT_T); DRAFT_T=setTimeout(syncDraft,300);}
// Writes the draft now, or removes it when there is nothing to keep - unless a discard's undo toast still holds it.
function syncDraft(){clearTimeout(DRAFT_T); DRAFT_T=0; if(!DRAFT_READY||!META)return; const rec=draftRecord();
  try{if(rec){const k=draftKey(META.label,rec.doc); DRAFT_HOLD=null;   // a newer draft replaces a discarded one
      if(DRAFT_KEY_AT&&DRAFT_KEY_AT!==k)sessionStorage.removeItem(DRAFT_KEY_AT);
      sessionStorage.setItem(k,JSON.stringify(rec)); DRAFT_KEY_AT=k; return;}
    if(DRAFT_HOLD&&DRAFT_HOLD.isConnected)return;
    DRAFT_HOLD=null; if(DRAFT_KEY_AT)sessionStorage.removeItem(DRAFT_KEY_AT); DRAFT_KEY_AT=null;}catch(e){}}
addEventListener('pagehide',syncDraft);
document.addEventListener('visibilitychange',()=>{if(document.hidden)syncDraft();});
// Boot: brings back this tab's draft for the document on screen and says so with [버리기]. A full restore redraws the box and
// opens a collapsed panel or sheet (not remembered); a note-only one leaves the note in the note field for the next pick.
// [버리기] is the usual discard (a full draft gets its undo toast; the draft goes once that window is over).
function restoreDraft(){let rec=null; const k=META?draftKey(META.label,DOC):null;
  try{rec=k?JSON.parse(sessionStorage.getItem(k)||'null'):null;}catch(e){rec=null;}
  const how=draftRestore(rec,DOC,META&&META.pages_build); DRAFT_KEY_AT=rec?k:null; DRAFT_READY=true;
  if(!how){syncDraft(); return;}
  const n=$('#note'); n.value=rec.note||''; n._mentions=rec.mentions&&rec.mentions.length?new Set(rec.mentions):null;
  setKind(rec.kind); Object.assign(ASSIGN_NEW,rec.assign||{}); renderAssignNew(); mentionPreview(n); autoGrow(n);
  if(how==='full'){const c=rec.cur,pg=document.getElementById('p'+c.page);
    if(pg&&Array.isArray(c.frac)){const b=newBox(pg),f=c.frac; drawBox(b,f[0],f[1],f[0]+f[2],f[1]+f[3]); b.classList.add('pending'); b.innerHTML='<i>새 핀</i>'; PENDING=b;}
    CUR=c; recomputeOverlap(); SNIP_OPEN=false; $('#c-err').hidden=true; $('#c-body').hidden=false; $('#composer').hidden=false;
    renderComposer(); setSide(true); applySide(); if(LAYOUT!=='wide')revealBox(PENDING);}
  toast(how==='full'?'작성 중이던 메모를 되살렸습니다':'작성 중이던 메모를 되살렸습니다 — PDF가 바뀌어 자리를 다시 골라야 합니다','ok',
    {label:'버리기',tip:'되살린 선택과 메모를 버립니다',fn:()=>{if(!$('#composer').hidden)discardSelection(); else{cancelSelection(true); syncDraft();}}});}
