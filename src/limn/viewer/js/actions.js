async function closePin(id){try{const {data}=await api('/api/pins/'+id+'/close',{method:'POST',what:'완료'});
  if(!data.ok){toast(tl('완료 실패 — 핀 #{id} 이 없습니다',{id}),'err');}
  else {markMine(id); toast(tl(data.state==='review'?'핀 #{id} 검토 대기로 보냄 — 이 화면에 신원이 없어(로컬) 에이전트가 닫은 것으로 칩니다':'핀 #{id} 완료',{id}),
    'ok',{label:'되돌리기',fn:()=>reopenPin(id)});}}catch(e){} await loadPins();}
// Awaiting review -> done. The person who confirmed (confirmed_by) is recorded.
async function confirmPin(id){try{const {data}=await api('/api/pins/'+id+'/confirm',{method:'POST',what:'확인',expect:[409]});
  if(data&&data.error==='open')toast(tl('핀 #{id} 은 이미 다시 열렸습니다',{id}),'warn');
  else if(!data.ok)toast(tl('확인 실패 — 핀 #{id} 이 없습니다',{id}),'err');
  else{markMine(id); toast(tl('핀 #{id} 확인 · 완료로 옮겼습니다',{id}),'ok');}}catch(e){} await loadPins();}
// Undo of [완료] (the toast's [되돌리기]) - the viewer has no [다시 열기] button any more; a reply reopens by the server rule.
async function reopenPin(id){try{await api('/api/pins/'+id+'/reopen',{method:'POST',what:'다시 열기'});
  markMine(id); toast(tl('핀 #{id} 완료를 되돌렸습니다',{id}),'ok');}catch(e){} await loadPins();}
// [삭제] takes the pin off the list at once (no confirmation) and says so next to the action with [되돌리기]; it waits in the Trash.
async function dropPin(id,undoSave){const was={o:OPEN_ALL,p:PINS};
  OPEN_ALL=OPEN_ALL.filter(p=>p.id!==id); PINS=PINS.filter(p=>p.id!==id); if(EDIT&&EDIT.id===id)EDIT=null; drawPins(); marks();
  try{await api('/api/pins/'+id+'/drop',{method:'POST',what:'삭제'});
    markMine(id); toast(tl(undoSave?'핀 #{id} 저장을 되돌렸습니다':'핀 #{id} 삭제됨 · 휴지통에 30일 보관',{id}),'ok',{label:'되돌리기',fn:()=>restorePin(id)});}
  catch(e){OPEN_ALL=was.o; PINS=was.p; drawPins(); marks();} await loadPins();}
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

