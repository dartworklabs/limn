// Append a note to an existing pin; a late response must leave any newer selection on screen. Its undo is a chip on that pin's
// mark ('덧붙임 [되돌리기]', docs/handbook/viewer.md §알림 자리), and a failure a banner over the composer's save row.
/** Append once to the displayed pin revision; conflicts keep the draft, and undo can restore only that verified prior note. */
async function appendToPin(id,text){
  if(COMPOSE.saving||viewerBlocked())return;
  const prior=PINS.find(p=>p.id===id); if(!prior){await loadPins();return;}
  COMPOSE.saving=true; syncComposeSaveButtons();
  const visit=captureVisit(),selection=COMPOSE.current,box=COMPOSE.box,priorNote=prior.note||'',fields=composeFields();
  const draft=savedDraftSnapshot();
  try{const {status,data}=await api('/api/pins/'+id+'/edit',{method:'POST',body:{note_append:text,base_rev:prior.rev||0},what:'메모 덧붙이기',where:NOTICE_HOST.COMPOSER,intent:'append',expect:[409]});
    if(status===409){bannerNote(NOTICE_HOST.COMPOSER,'다른 쪽이 이 핀을 먼저 바꿨습니다 — 최신 메모를 확인하고 다시 덧붙이세요',NOTICE_KIND.WARN,null,{source:'POST /api/pins/'+id+'/edit append'});
      await loadPins();return;}
    if(composeOwns(selection,box,visit,fields)){COMPOSE.box=null; cancelSelection(true); if(box)box.remove(); syncDraft();}
    else if(restoredDraftOwns(draft)){cancelSelection(true); syncDraft();}
    else clearSavedDraft(draft);
    const chip=undoNote(NOTICE_PLACE.CHIP,tl('#{id} 에 덧붙였습니다',{id}),{label:'되돌리기',wait:true,fn:()=>undoAppend(id,priorNote,data.pin.rev)},
      {pin:id,pending:true,label:tr('덧붙임')});
    await loadPins(); settleChip(chip);
  }catch(e){}finally{COMPOSE.saving=false; syncComposeSaveButtons();}}
/** Keep all create and append controls in step with their shared request lifetime; editable fields remain available. */
function syncComposeSaveButtons(){document.querySelectorAll('#btn-save,[data-act="overlap-append"],[data-act="pop-save"]').forEach(b=>{
  /** @type {HTMLButtonElement} */(b).disabled=COMPOSE.saving;});}
// Undo of an append: the note goes back to what it was before (base_rev = the append's revision). Silent - the card shows it.
// Resolves with whether it went back (its chip waits for it, noticeAct).
/** @param {number} id @param {string} note @param {number} rev @returns {Promise<boolean>} */
async function undoAppend(id,note,rev){let ok=false;
  try{await api('/api/pins/'+id+'/edit',{method:'POST',body:{note:note,base_rev:rev},what:'되돌리기',where:NOTICE_HOST.LIST,intent:'append-undo'});
    ok=true; quietNote(tl('#{id} 메모를 되돌렸습니다',{id}));}catch(e){} await loadPins(); return ok;}
// The save-pin button's label (boot, clearing the pending state, syncSaveBtn): [다시 저장] while the composer's banner says a
// save failed, else [핀 저장]; with the shortcut where there is a keyboard.
function saveBtnLabel(){const b=BANNERS.get(NOTICE_HOST.COMPOSER),t=tr(b&&b.save?'다시 저장':'핀 저장');
  return MQ_COARSE.matches?html`${t}`:html`${t} <span class="kh">${IS_MAC?'⌘ Enter':'Ctrl+Enter'}</span>`;}
// docs/handbook/viewer.md §패널 정리 (드래그 직후 저장): pressing [핀 저장] right after a drag but before SyncTeX pick finishes (~1.1s) used to just silently vanish, since
// COMPOSE.current didn't exist yet (observed). Now that save request is queued and auto-saved once pick succeeds - the note re-reads
// #note at the moment of saving (when pick resolves), picking up even characters the user edited in the meantime. If pick
// fails or the selection is canceled, the queue is cleared too. Pressing the button again cancels the pending save (a toggle) - so it can be undone without a separate cancel button.
function togglePendingSave(){if(COMPOSE.pendingSave){clearPendingSave();return;}
  COMPOSE.pendingSave=true; const btn=$('#btn-save'); btn.dataset.pending='1';
  setHtml(btn,html`${tr('위치 찾는 중… 저장 대기')} <span class="spin" aria-hidden="true"></span>`);}
function clearPendingSave(){if(!COMPOSE.pendingSave)return; COMPOSE.pendingSave=false;
  const btn=$('#btn-save'); delete btn.dataset.pending; setHtml(btn,saveBtnLabel());}
// Saves the selection as a pin (or queues the save while pick runs). Saved: a chip '저장됨 [되돌리기]' on the new pin's mark
// for NOTICE_MS, visible with the phone's sheet folded; its [되돌리기] drops the pin again and - only once that delete went
// through - reopens the composer with the same selection and note. A failed undo keeps the pin and no composer (a second
// save would duplicate it); its failure's [다시 시도] runs the whole undo again. Failed save: a banner over the save row,
// whose button then reads [다시 저장] (api's save flag).
/** Save the submitted selection once, preserving any later edits as a draft and offering undo for the created pin. */
async function savePin(){
  if(COMPOSE.saving)return;
  if(!COMPOSE.current){if(COMPOSE.picking)togglePendingSave(); return;}   // pick hasn't finished yet - queue it (toggle) or cancel the pending save
  COMPOSE.saving=true; const visit=captureVisit(); syncComposeSaveButtons();
  const d=COMPOSE.current,box=COMPOSE.box,note=$('#note').value.trim();
  let body=/** @type {Record<string, unknown>} */({file:d.file,name:d.name,page:d.page,lo:d.lo,hi:d.hi,raw_lo:d.raw_lo,raw_hi:d.raw_hi,via:d.via,score:d.score,
    frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined});
  if(d.scope){body.scope=d.scope; body.kind=kindFor(d.scope,d.env);} else body.kind=d.kind;
  if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};   // view-only: page/region only
  figureFields(body,d.elSel,isRegion(d)?null:figRung(d));   // a figure pick: its element as el, the element's box as frac, its kind
  body.doc=d.doc||DOC||undefined;
  body.kind_req=KIND_NEW;
  const mh=mentionHints($('#note')); if(mh.length)body.mentions=mh;
  renderAssignNew(); body.assignee=ASSIGN_NEW.v||ASSIGNEE_AGENT;   // a pin created by the viewer always records an assignee (otherwise a legacy pin's inference rule applies): the outcome the preview line shows (assignOutcome)
  const snap=selectionSnapshot(),fields=composeFields();   // [되돌리기] takes the pin back and hands this selection and note back for another try
  const draft=savedDraftSnapshot();
  const question=KIND_NEW===KIND_REQ.QUESTION;
  try{const {data}=await api('/api/pin',{method:'POST',body,what:'핀 저장',where:NOTICE_HOST.COMPOSER,save:true});
    const id=data.id,failed=BANNERS.get(NOTICE_HOST.COMPOSER);
    if(failed&&failed.save)endNotice(failed,false);   // this save went through: its earlier failure is over
    const cleared=composeOwns(d,box,visit,fields),restored=restoredDraftOwns(draft);
    if(cleared){COMPOSE.box=null; cancelSelection(true); if(box)box.remove(); syncDraft();}   // a saved pin leaves no draft
    else if(restored){cancelSelection(true); syncDraft();}
    else clearSavedDraft(draft);
    if(SEC_SEEN.open)SEC_SEEN.open.add(id);   // my own new pin is never 'new' on a collapsed header
    /** @type {()=>Promise<boolean>} */
    const undo=async()=>{const ok=await dropPin(id,true,undo);
      if(ok&&(cleared||restored)&&DOC===visit.doc&&!COMPOSE.current&&!COMPOSE.box&&!COMPOSE.picking&&!$('#note').value)restoreSelection(snap);
      return ok;};
    const chip=undoNote(NOTICE_PLACE.CHIP,tl(question?'질문 #{id} 저장됨 · pins.md 갱신':'핀 #{id} 저장됨 · pins.md 갱신',{id}),
      {label:'되돌리기',wait:true,fn:undo},{pin:id,pending:true,label:tr('저장됨')});
    await loadPins(); settleChip(chip);
  }catch(e){} finally{COMPOSE.saving=false; syncComposeSaveButtons();}
}
