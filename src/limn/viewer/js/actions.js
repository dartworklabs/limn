// [완료] on an open card. Done (or sent to review, for a screen without identity): a row in the card's place with [되돌리기]
// (reopenPin) for NOTICE_MS - other presses never end it (docs/handbook/viewer.md §알림 자리). A refusal: a banner on top
// of the panel.
async function closePin(id){const prev=drawnBefore($('#pins'),'.pin.card',id);
  try{const {data}=await api('/api/pins/'+id+'/close',{method:'POST',what:'완료',where:NOTICE_HOST.LIST,retry:()=>closePin(id)});
  if(!data.ok){bannerNote(NOTICE_HOST.LIST,tl('완료 실패 — 핀 #{id} 이 없습니다',{id}),NOTICE_KIND.ERR);}
  else {markMine(id); undoNote(NOTICE_PLACE.ROW,tl(data.state===PIN_STATE.REVIEW?'핀 #{id} 검토 대기로 보냄 — 이 화면에 신원이 없어(로컬) 에이전트가 닫은 것으로 칩니다':'핀 #{id} 완료',{id}),
    {label:'되돌리기',wait:true,fn:()=>reopenPin(id)},{pin:id,sec:'open',prev});}}catch(e){} await loadPins();}
// Awaiting review -> done; the person who confirmed (confirmed_by) is recorded. The card's [확인] and the changes view's guide
// line call this one function. Like a reply it is a deferred send: the card leaves the review section at once (CONFIRMING keeps
// it out of every pin snapshot meanwhile, derivePinLists), a row in its place offers [되돌리기] for NOTICE_MS and the request
// goes when that row does; the undo puts the card back with nothing sent. The request names the close the card showed
// (done_at), so a pin reopened and closed again in between answers 409 'conflict' instead of confirming a result nobody looked
// at; a 409 'open' means it was reopened and is still open (docs/handbook/api.md §검토 대기). Both are banners on top of the
// review section (confirmConflict).
const CONFIRMING=new Set();
// The warning for a confirm answered 409 'conflict', chosen by the pin that 409 carries: still awaiting review means it
// was closed again - look at the new result, then confirm; any other state (a person closed it straight to done) has
// nothing to confirm. A body without the pin (an older server) keeps the closed-again warning.
function confirmConflictText(id,pin){return pin&&pinState(pin)!==PIN_STATE.REVIEW
  ?tl('핀 #{id} 은 이미 완료로 닫혔습니다 — 확인할 것이 없습니다',{id})
  :tl('핀 #{id} 은 다시 닫혔습니다 — 새 결과를 보고 확인하세요',{id});}
// What kind of banner that 409 conflict is, by the same rule as its text: closed again is a WARN that still asks for a look
// ([변경 보기]); already done by a person is INFO with nothing to do. Pure.
/** @param {Pin|null|undefined} pin @returns {string} */
function confirmConflictKind(pin){return pin&&pinState(pin)!==PIN_STATE.REVIEW?NOTICE_KIND.INFO:NOTICE_KIND.WARN;}
// Says a confirm answered 409 'conflict' in a banner on top of the review section (confirmConflictText, confirmConflictKind).
/** @param {number} id @param {Pin|null|undefined} pin */
function confirmConflict(id,pin){const kind=confirmConflictKind(pin);
  bannerNote(NOTICE_HOST.REVIEW,confirmConflictText(id,pin),kind,kind===NOTICE_KIND.WARN?{label:'변경 보기',tip:T.change,fn:()=>showChange(id)}:null);}
function confirmPin(id){if(CONFIRMING.has(id))return; const at=REVIEW_ALL.findIndex(p=>p.id===id),pin=at<0?null:REVIEW_ALL[at];
  const prev=drawnBefore($('#review-pins'),'.pin.card',id);
  CONFIRMING.add(id); REVIEW_ALL=REVIEW_ALL.filter(p=>p.id!==id); drawPins(); marks();
  const d=deferred(async()=>{
      try{const {data}=await api('/api/pins/'+id+'/confirm',{method:'POST',what:'확인',where:NOTICE_HOST.REVIEW,expect:[409],keepalive:true,
          body:pin&&pin.done_at?{done_at:pin.done_at}:{}});
        if(data&&data.error===PIN_STATE.OPEN)bannerNote(NOTICE_HOST.REVIEW,tl('핀 #{id} 은 이미 다시 열렸습니다',{id}),NOTICE_KIND.WARN);
        else if(data&&data.error==='conflict')confirmConflict(id,data.pin);
        else if(!data.ok)bannerNote(NOTICE_HOST.REVIEW,tl('확인 실패 — 핀 #{id} 이 없습니다',{id}),NOTICE_KIND.ERR);
        else markMine(id);}catch(e){}
      CONFIRMING.delete(id); await loadPins();},
    ()=>{CONFIRMING.delete(id);
      if(pin&&!REVIEW_ALL.some(p=>p.id===id)){const i=Math.min(at,REVIEW_ALL.length); REVIEW_ALL=[...REVIEW_ALL.slice(0,i),pin,...REVIEW_ALL.slice(i)];}
      drawPins(); marks();});
  deferredNote(d,NOTICE_PLACE.ROW,tl('핀 #{id} 확인 · 완료로 옮겼습니다',{id}),{pin:id,sec:'review',prev});}
// Undo of [완료] (its row's [되돌리기]) - the viewer has no [다시 열기] button any more; a reply reopens by the server rule.
// Silent: the card comes back. Resolves with whether the pin was reopened (the row waits for it, noticeAct).
/** @param {number} id @returns {Promise<boolean>} */
async function reopenPin(id){let ok=false; try{await api('/api/pins/'+id+'/reopen',{method:'POST',what:'다시 열기',where:NOTICE_HOST.LIST});
  ok=true; markMine(id); quietNote(tl('핀 #{id} 완료를 되돌렸습니다',{id}));}catch(e){} await loadPins(); return ok;}
// [삭제] takes the pin off the list at once (no confirmation) and leaves a row in its place with [되돌리기] for NOTICE_MS; it
// waits in the Trash. A failure puts the card back. undoSave = the save chip's [되돌리기]: silent, as the composer comes back
// with the selection - and again = what that failure's [다시 시도] runs (the whole undo, so the composer comes back too).
// Resolves with whether the pin was deleted.
/** @param {number|null} id @param {boolean} undoSave @param {()=>unknown} [again] @returns {Promise<boolean>} */
async function dropPin(id,undoSave,again){const was=OPEN_ALL,applied=PINS_APPLIED_SEQ,prev=drawnBefore($('#pins'),'.pin.card',id); let ok=false;
  OPEN_ALL=OPEN_ALL.filter(p=>p.id!==id); PINS=PINS.filter(p=>p.id!==id); if(EDITOR.current&&EDITOR.current.id===id)EDITOR.current=null; drawPins(); marks();
  try{await api('/api/pins/'+id+'/drop',{method:'POST',what:'삭제',where:NOTICE_HOST.LIST,retry:again||(()=>{dropPin(id,undoSave);})});
    ok=true; markMine(id);
    if(undoSave)quietNote(tl('핀 #{id} 저장을 되돌렸습니다',{id}));
    else undoNote(NOTICE_PLACE.ROW,tl('핀 #{id} 삭제됨 · 휴지통에 30일 보관',{id}),{label:'되돌리기',wait:true,fn:()=>restorePin(id)},{pin:id,sec:'open',prev});}
  catch(e){if(PINS_APPLIED_SEQ===applied){const old=was.find(p=>p.id===id);
      if(old&&!OPEN_ALL.some(p=>p.id===id)){const next=was.slice(was.indexOf(old)+1).find(p=>OPEN_ALL.some(x=>x.id===p.id));
        const at=next?OPEN_ALL.findIndex(p=>p.id===next.id):OPEN_ALL.length;
        OPEN_ALL=[...OPEN_ALL.slice(0,at),old,...OPEN_ALL.slice(at)];
        PINS=OPEN_ALL.filter(p=>pdoc(p)===DOC); drawPins(); marks();}}} await loadPins(); return ok;}
// [영구 삭제] (owner): the row leaves the Trash at once and a row in its place offers [되돌리기]; the request goes out when that
// row does (deferred, NOTICE_MS).
const PURGING=new Set();
function purgePin(id){const prev=drawnBefore($('#trash-list'),'.arc-row',id); PURGING.add(id); drawTrash(); drawPins();
  const d=deferred(async()=>{try{await api('/api/pins/'+id+'/purge',{method:'POST',what:'영구 삭제',where:NOTICE_HOST.TRASH,keepalive:true});}catch(e){}
      PURGING.delete(id); await loadPins();},
    ()=>{PURGING.delete(id); drawTrash(); drawPins();});
  deferredNote(d,NOTICE_PLACE.TRASH,tl('핀 #{id} 영구 삭제',{id}),{pin:id,prev});}
// [되살리기] (the Trash, a deleted pin's row, a background message): the pin is back as it was. Silent - its card is there.
// Resolves with whether it was restored: a message whose action this is stays until then (noticeAct); a failure says itself
// where it can be seen (bannerNote: the status line while the panel is closed).
/** @param {number|null} id @returns {Promise<boolean>} */
async function restorePin(id){let ok=false; try{await api('/api/pins/'+id+'/restore',{method:'POST',what:'되살리기',where:NOTICE_HOST.LIST,retry:()=>{restorePin(id);}});
  ok=true; markMine(id); quietNote(tl('핀 #{id} 되살림',{id}));}catch(e){} await loadPins(); return ok;}
// [풀기]: the in-progress mark goes. Silent - the badge goes with it.
async function unclaimPin(id){try{await api('/api/pins/'+id+'/unclaim',{method:'POST',what:'처리 중 풀기',where:NOTICE_HOST.LIST,retry:()=>unclaimPin(id)});
  markMine(id); quietNote(tl('핀 #{id} 처리 중 표시를 풀었습니다',{id}));}catch(e){} await loadPins();}
