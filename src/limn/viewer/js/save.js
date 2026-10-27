// Append a note to an existing pin; a late response must leave any newer selection on screen. Its undo is a chip on that pin's
// mark ('덧붙임 [되돌리기]', docs/handbook/viewer.md §알림 자리), and a failure a banner over the composer's save row.
/** Append once to the displayed pin revision; conflicts keep the draft, and undo can restore only that verified prior note. */
async function appendToPin(id,text){
  if(COMPOSE.saving||viewerBlocked())return;
  const prior=PINS.find(p=>p.id===id); if(!prior){await loadPins();return;}
  COMPOSE.saving=true; syncComposeSaveButtons();
  const visit=captureVisit(),selection=COMPOSE.current,box=COMPOSE.box,priorNote=prior.note||'',fields=composeFields();
  const draft=savedDraftSnapshot();
  // The hints go along, as on a new pin and an edit: the pin's own first (its note's tags), then the ones picked for this
  // text - without them a name two people share would tag nobody, while the preview line named whom it tells.
  const mh=[...new Set((prior.mentions||[]).concat(mentionHints($('#note'))))],body=/** @type {Record<string, unknown>} */({note_append:text,base_rev:prior.rev||0});
  if(mh.length)body.mentions=mh;
  try{const {status,data}=await api('/api/pins/'+id+'/edit',{method:'POST',body,what:'메모 덧붙이기',where:NOTICE_HOST.COMPOSER,intent:'append',expect:[409]});
    if(status===409){bannerNote(NOTICE_HOST.COMPOSER,'다른 쪽이 이 핀을 먼저 바꿨습니다 — 최신 메모를 확인하고 다시 덧붙이세요',NOTICE_KIND.WARN,null,{source:'POST /api/pins/'+id+'/edit append'});
      await loadPins();return;}
    if(composeOwns(selection,box,visit,fields)){COMPOSE.box=null; cancelSelection(true); if(box)box.remove(); syncDraft();}
    else if(restoredDraftOwns(draft)){cancelSelection(true); syncDraft();}
    else clearSavedDraft(draft);
    const chip=undoNote(NOTICE_PLACE.CHIP,tl('#{id} 에 덧붙였습니다',{id}),{label:'되돌리기',wait:true,fn:()=>undoAppend(id,priorNote,data.pin.rev)},
      {pin:id,pending:true,label:tr('덧붙임')});
    await loadPins(); settleChip(chip);
  }catch(e){}finally{COMPOSE.saving=false; syncComposeSaveButtons();}}
/** Keep all create and append controls in step with their shared request lifetime; editable fields remain available. An append
 * also waits while a suggested edit is written (it is saved with a new pin only, renderOverlapBanner). */
function syncComposeSaveButtons(){document.querySelectorAll('#btn-save,[data-act="overlap-append"],[data-act="pop-save"]').forEach(b=>{
  /** @type {HTMLButtonElement} */(b).disabled=COMPOSE.saving;});
  if(suggestPending())document.querySelectorAll('[data-act="overlap-append"]').forEach(b=>{/** @type {HTMLButtonElement} */(b).disabled=true;});
  renderVerdictRow();}   // the verdict buttons wait for the request too, and come back when it ends - a selection picked meanwhile included
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
// whose button then reads [다시 저장] (api's save flag). A suggested edit goes along (suggestForSave); when its base no longer
// reads as the lines (409 suggest_base_changed) nothing is saved, the draft stays, the editor shows the current text against it
// and the failure's banner offers [지금 원문으로 맞추기].
// With verdict (a word of the document's, the composer's verdict row - which calls it only with a found selection: its buttons
// are off while the pick runs) the pin is a verdict pin: a fix request with no suggestion; its undo withdraws it and does
// not bring the composer back (verdictUndo, D10).
/** Save the submitted selection once, preserving any later edits as a draft and offering undo for the created pin.
 * @param {string} [verdict] */
async function savePin(verdict){
  if(COMPOSE.saving)return;
  if(!COMPOSE.current){if(COMPOSE.picking)togglePendingSave(); return;}   // pick hasn't finished yet - queue it (toggle) or cancel the pending save
  COMPOSE.saving=true; const visit=captureVisit(); syncComposeSaveButtons();
  const d=COMPOSE.current,box=COMPOSE.box,note=$('#note').value.trim();
  // [다시 저장] after a verdict's failed save carries that verdict again while the selection is the one it was bound to
  // (the same pick, page, lines, rung and box) and the composer still asks for a verdict pin: a fix request with [제안 수정]
  // off. A changed selection, or a kind or switch changed meanwhile (setKind, suggestAct drop it), is a plain pin's save.
  const rv=COMPOSE.retryVerdict,at=JSON.stringify([d.page,d.lo,d.hi,d.scope,d.frac]); COMPOSE.retryVerdict=null;
  if(verdict===undefined&&rv&&rv.sel===d&&rv.at===at&&KIND_NEW===KIND_REQ.FIX&&!SG.on)verdict=rv.key;
  let body=/** @type {Record<string, unknown>} */({file:d.file,name:d.name,page:d.page,lo:d.lo,hi:d.hi,raw_lo:d.raw_lo,raw_hi:d.raw_hi,via:d.via,score:d.score,
    frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined});
  if(d.scope){body.scope=d.scope; body.kind=kindFor(d.scope,d.env);} else body.kind=d.kind;
  if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};   // view-only: page/region only
  figureFields(body,d.elSel,isRegion(d)?null:figRung(d));   // a figure pick: its element as el, the element's box as frac, its kind
  body.doc=d.doc||DOC||undefined;
  // The kind and the assignee are assignOutcome's answer for the note as it is at this moment - the answer the preview line
  // and the assignee row draw - never a value an earlier drawing left behind: a restored pick whose person cannot be looked
  // up yet is not sent. A pin created by the viewer always records an assignee (otherwise a legacy pin's inference applies).
  const out=assignOutcome(composeAsk(SAVE_MODE.NEW)); body.kind_req=out.kind; body.assignee=out.assignee;
  const mh=mentionHints($('#note')); if(mh.length)body.mentions=mh;
  const sg=isRegion(d)||verdict?null:suggestForSave(SG,suggestOff(d,META?META.kind:undefined)); if(sg)body.suggest=sg;
  if(verdict){body.verdict=verdict; body.kind_req=KIND_REQ.FIX;}
  const snap=selectionSnapshot(),fields=composeFields();   // [되돌리기] takes the pin back and hands this selection and note back for another try
  const draft=savedDraftSnapshot();
  const question=out.kind===KIND_REQ.QUESTION;
  try{const {status,data}=await api('/api/pin',{method:'POST',body,what:verdict?'판정 저장':'핀 저장',where:NOTICE_HOST.COMPOSER,save:true,expect:sg?[409]:[]});
    if(status===409){suggestSaveRefused(d,data); return;}
    const id=data.id,failed=BANNERS.get(NOTICE_HOST.COMPOSER);
    if(failed&&failed.save)endNotice(failed,false);   // this save went through: its earlier failure is over
    const cleared=composeOwns(d,box,visit,fields),restored=restoredDraftOwns(draft);
    if(cleared){COMPOSE.box=null; cancelSelection(true); if(box)box.remove(); syncDraft();}   // a saved pin leaves no draft
    else if(restored){cancelSelection(true); syncDraft();}
    else clearSavedDraft(draft);
    if(SEC_SEEN.open)SEC_SEEN.open.add(id);   // my own new pin is never 'new' on a collapsed header
    /** @type {()=>Promise<boolean>} */
    const undo=verdict?verdictUndo(id):async()=>{const ok=await dropPin(id,true,undo);
      if(ok&&(cleared||restored)&&DOC===visit.doc&&!COMPOSE.current&&!COMPOSE.box&&!COMPOSE.picking&&!$('#note').value)restoreSelection(snap);
      return ok;};
    const chip=verdict?undoNote(NOTICE_PLACE.CHIP,tl('#{id} 저장됨 · {word} 판정',{id,word:verdictLabel(verdict)}),{label:'되돌리기',wait:true,fn:undo},{pin:id,pending:true,label:tl('#{id} 저장됨',{id})})
      :undoNote(NOTICE_PLACE.CHIP,tl(question?'질문 #{id} 저장됨 · pins.md 갱신':'핀 #{id} 저장됨 · pins.md 갱신',{id}),
      {label:'되돌리기',wait:true,fn:undo},{pin:id,pending:true,label:tr('저장됨')});
    await loadPins(); settleChip(chip);
  }catch(e){if(verdict)COMPOSE.retryVerdict={key:verdict,sel:d,at};}   // the failure's [다시 저장] saves this verdict again
  finally{COMPOSE.saving=false; syncComposeSaveButtons();}
}
// A new pin's save the server answered 409 while it carried a suggested edit: nothing was saved and the draft stays. When the
// suggestion's base no longer reads as the selection's lines (suggest_base_changed), the editor shows the lines' current text
// against the draft and the banner over the save row offers [지금 원문으로 맞추기] (the draft keeps its text and takes that text as
// its base); any other 409 is said as the failure it is. Either way the save row reads [다시 저장].
/** @param {Selection} d @param {any} data */
function suggestSaveRefused(d,data){const source='POST /api/pin',head=tl('{what} 실패',{what:tr('핀 저장')});
  if(!(data&&data.reason==='suggest_base_changed')){bannerNote(NOTICE_HOST.COMPOSER,head+' — '+(errText(data)||'HTTP 409'),NOTICE_KIND.ERR,null,{save:true,source}); return;}
  if(COMPOSE.current===d){SG.current={text:String(data.current||''),file:d.file||null,lo:/** @type {number} */(d.lo),hi:/** @type {number} */(d.hi)}; renderSuggest(d);}
  bannerNote(NOTICE_HOST.COMPOSER,head+' — '+tr('그사이 그 줄들의 원문이 바뀌었습니다'),NOTICE_KIND.ERR,
    {label:'지금 원문으로 맞추기',tip:'쓰던 글은 그대로 두고, 이 제안이 바꿀 원문을 지금 그 줄들의 글로 바꿉니다. 그다음 다시 저장합니다',
      fn:()=>{const c=COMPOSE.current; if(!c)return; suggestRebase(SG,c,()=>COMPOSE.current===c,()=>{if(COMPOSE.current!==c)return; renderSuggest(c); renderOverlapBanner(); saveDraftSoon();});}},
    {save:true,source});}
