async function closePin(id){try{const {data}=await api('/api/pins/'+id+'/close',{method:'POST',what:'완료'});
  if(!data.ok){toast(tl('완료 실패 — 핀 #{id} 이 없습니다',{id}),'err');}
  else {markMine(id); toast(tl(data.state===PIN_STATE.REVIEW?'핀 #{id} 검토 대기로 보냄 — 이 화면에 신원이 없어(로컬) 에이전트가 닫은 것으로 칩니다':'핀 #{id} 완료',{id}),
    'ok',{label:'되돌리기',fn:()=>reopenPin(id)});}}catch(e){} await loadPins();}
// Awaiting review -> done; the person who confirmed (confirmed_by) is recorded. The card's [확인] and the changes view's guide
// line call this one function. Like a reply it is a deferred send: the card leaves the review section at once (CONFIRMING keeps
// it out of every pin snapshot meanwhile, derivePinLists), the request goes when the [되돌리기] toast does, and the undo puts
// the card back with nothing sent. The request names the close the card showed (done_at), so a pin reopened and closed
// again in between answers 409 'conflict' instead of confirming a result nobody looked at; a 409 'open' means it was
// reopened and is still open (docs/handbook/api.md §검토 대기).
const CONFIRMING=new Set();
function confirmPin(id){if(CONFIRMING.has(id))return; const at=REVIEW_ALL.findIndex(p=>p.id===id),pin=at<0?null:REVIEW_ALL[at];
  CONFIRMING.add(id); REVIEW_ALL=REVIEW_ALL.filter(p=>p.id!==id); drawPins(); marks();
  deferred(tl('핀 #{id} 확인 · 완료로 옮겼습니다',{id}),async()=>{
      try{const {data}=await api('/api/pins/'+id+'/confirm',{method:'POST',what:'확인',expect:[409],keepalive:true,
          body:pin&&pin.done_at?{done_at:pin.done_at}:{}});
        if(data&&data.error===PIN_STATE.OPEN)toast(tl('핀 #{id} 은 이미 다시 열렸습니다',{id}),'warn');
        else if(data&&data.error==='conflict')toast(tl('핀 #{id} 은 다시 닫혔습니다 — 새 결과를 보고 확인하세요',{id}),'warn');
        else if(!data.ok)toast(tl('확인 실패 — 핀 #{id} 이 없습니다',{id}),'err');
        else markMine(id);}catch(e){}
      CONFIRMING.delete(id); await loadPins();},
    ()=>{CONFIRMING.delete(id);
      if(pin&&!REVIEW_ALL.some(p=>p.id===id)){const i=Math.min(at,REVIEW_ALL.length); REVIEW_ALL=[...REVIEW_ALL.slice(0,i),pin,...REVIEW_ALL.slice(i)];}
      drawPins(); marks();});}
// Undo of [완료] (the toast's [되돌리기]) - the viewer has no [다시 열기] button any more; a reply reopens by the server rule.
async function reopenPin(id){try{await api('/api/pins/'+id+'/reopen',{method:'POST',what:'다시 열기'});
  markMine(id); toast(tl('핀 #{id} 완료를 되돌렸습니다',{id}),'ok');}catch(e){} await loadPins();}
// [삭제] takes the pin off the list at once (no confirmation) and says so next to the action with [되돌리기]; it waits in the Trash.
async function dropPin(id,undoSave){const was=OPEN_ALL,applied=PINS_APPLIED_SEQ;
  OPEN_ALL=OPEN_ALL.filter(p=>p.id!==id); PINS=PINS.filter(p=>p.id!==id); if(EDITOR.current&&EDITOR.current.id===id)EDITOR.current=null; drawPins(); marks();
  try{await api('/api/pins/'+id+'/drop',{method:'POST',what:'삭제'});
    markMine(id); toast(tl(undoSave?'핀 #{id} 저장을 되돌렸습니다':'핀 #{id} 삭제됨 · 휴지통에 30일 보관',{id}),'ok',{label:'되돌리기',fn:()=>restorePin(id)});}
  catch(e){if(PINS_APPLIED_SEQ===applied){const old=was.find(p=>p.id===id);
      if(old&&!OPEN_ALL.some(p=>p.id===id)){const next=was.slice(was.indexOf(old)+1).find(p=>OPEN_ALL.some(x=>x.id===p.id));
        const at=next?OPEN_ALL.findIndex(p=>p.id===next.id):OPEN_ALL.length;
        OPEN_ALL=[...OPEN_ALL.slice(0,at),old,...OPEN_ALL.slice(at)];
        PINS=OPEN_ALL.filter(p=>pdoc(p)===DOC); drawPins(); marks();}}} await loadPins();}
// [영구 삭제] (owner): the row leaves the Trash at once; the request goes out when the undo toast does (deferred).
const PURGING=new Set();
function purgePin(id){PURGING.add(id); drawTrash(); drawPins();
  deferred(tl('핀 #{id} 영구 삭제',{id}),async()=>{try{await api('/api/pins/'+id+'/purge',{method:'POST',what:'영구 삭제',keepalive:true});}catch(e){}
      PURGING.delete(id); await loadPins();},
    ()=>{PURGING.delete(id); drawTrash(); drawPins();});}
async function restorePin(id){try{await api('/api/pins/'+id+'/restore',{method:'POST',what:'되살리기'});
  markMine(id); toast(tl('핀 #{id} 되살림',{id}),'ok');}catch(e){} await loadPins();}
async function unclaimPin(id){try{await api('/api/pins/'+id+'/unclaim',{method:'POST',what:'처리 중 풀기'});
  markMine(id); toast(tl('핀 #{id} 처리 중 표시를 풀었습니다',{id}),'ok');}catch(e){} await loadPins();}
