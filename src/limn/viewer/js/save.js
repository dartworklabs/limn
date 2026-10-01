// Append a note to an existing pin; a late response must leave any newer selection on screen.
async function appendToPin(id,text){
  const visit=captureVisit(),selection=COMPOSE.current,box=COMPOSE.box,prior=PINS.find(p=>p.id===id),priorNote=prior?(prior.note||''):'';
  const draft=savedDraftSnapshot();
  try{const {data}=await api('/api/pins/'+id+'/edit',{method:'POST',body:{note_append:text},what:'메모 덧붙이기'});
    if(composeOwns(selection,box,visit)){COMPOSE.box=null; cancelSelection(true); if(box)box.remove(); syncDraft();}
    else if(restoredDraftOwns(draft)){cancelSelection(true); syncDraft();}
    else clearSavedDraft(draft);
    toast(tl('#{id} 에 덧붙였습니다',{id}),'ok',{label:'되돌리기',fn:()=>undoAppend(id,priorNote,data.pin.rev)});
    await loadPins();
  }catch(e){}}
async function undoAppend(id,note,rev){
  try{await api('/api/pins/'+id+'/edit',{method:'POST',body:{note:note,base_rev:rev},what:'되돌리기'});
    toast(tl('#{id} 메모를 되돌렸습니다',{id}),'ok');}catch(e){} await loadPins();}
// The normal label for the save-pin button (shared by boot and clearing the pending state).
function saveBtnLabel(){return MQ_COARSE.matches?tr('핀 저장'):tr('핀 저장')+' <span class="kh">'+(IS_MAC?'⌘ Enter':'Ctrl+Enter')+'</span>';}
// docs/handbook/viewer.md §패널 정리 (드래그 직후 저장): pressing [핀 저장] right after a drag but before SyncTeX pick finishes (~1.1s) used to just silently vanish, since
// COMPOSE.current didn't exist yet (observed). Now that save request is queued and auto-saved once pick succeeds - the note re-reads
// #note at the moment of saving (when pick resolves), picking up even characters the user edited in the meantime. If pick
// fails or the selection is canceled, the queue is cleared too. Pressing the button again cancels the pending save (a toggle) - so it can be undone without a separate cancel button.
function togglePendingSave(){if(COMPOSE.pendingSave){clearPendingSave();return;}
  COMPOSE.pendingSave=true; const btn=$('#btn-save'); btn.dataset.pending='1';
  btn.innerHTML=tr('위치 찾는 중… 저장 대기')+' <span class="spin" aria-hidden="true"></span>';}
function clearPendingSave(){if(!COMPOSE.pendingSave)return; COMPOSE.pendingSave=false;
  const btn=$('#btn-save'); delete btn.dataset.pending; btn.innerHTML=saveBtnLabel();}
// Saves the selection as a pin (or queues the save while pick runs). The toast's [되돌리기] drops the pin again and
// reopens the composer with the same selection and note.
async function savePin(){
  if(COMPOSE.saving)return;
  if(!COMPOSE.current){if(COMPOSE.picking)togglePendingSave(); return;}   // pick hasn't finished yet - queue it (toggle) or cancel the pending save
  COMPOSE.saving=true; const visit=captureVisit(),btn=$('#btn-save'); btn.disabled=true;
  const d=COMPOSE.current,box=COMPOSE.box,note=$('#note').value.trim();
  let body={file:d.file,name:d.name,page:d.page,lo:d.lo,hi:d.hi,raw_lo:d.raw_lo,raw_hi:d.raw_hi,via:d.via,score:d.score,
    frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};
  if(d.scope){body.scope=d.scope; body.kind=kindFor(d.scope,d.env);} else body.kind=d.kind;
  if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};   // view-only: page/region only
  figureFields(body,d.elSel,isRegion(d)?null:figRung(d));   // a figure pick: its element as el, the element's box as frac, its kind
  body.doc=d.doc||DOC||undefined;
  body.kind_req=KIND_NEW;
  const mh=mentionHints($('#note')); if(mh.length)body.mentions=mh;
  renderAssignNew(); body.assignee=ASSIGN_NEW.v||ASSIGNEE_AGENT;   // a pin created by the viewer always records an assignee (otherwise a legacy pin's inference rule applies)
  const snap=selectionSnapshot();   // [되돌리기] takes the pin back and hands this selection and note back for another try
  const draft=savedDraftSnapshot();
  const question=KIND_NEW===KIND_REQ.QUESTION;
  try{const {data}=await api('/api/pin',{method:'POST',body,what:'핀 저장'});
    const id=data.id;
    const cleared=composeOwns(d,box,visit),restored=restoredDraftOwns(draft);
    if(cleared){COMPOSE.box=null; cancelSelection(true); if(box)box.remove(); syncDraft();}   // a saved pin leaves no draft
    else if(restored){cancelSelection(true); syncDraft();}
    else clearSavedDraft(draft);
    if(SEC_SEEN.open)SEC_SEEN.open.add(id);   // my own new pin is never 'new' on a collapsed header
    toast(tl(question?'질문 #{id} 저장됨 · pins.md 갱신':'핀 #{id} 저장됨 · pins.md 갱신',{id}),'ok',
      {label:'되돌리기',fn:()=>{dropPin(id,true); if((cleared||restored)&&DOC===visit.doc&&
        !COMPOSE.current&&!COMPOSE.box&&!COMPOSE.picking&&!$('#note').value)restoreSelection(snap);}});
    await loadPins();
  }catch(e){} finally{COMPOSE.saving=false; btn.disabled=false;}
}
