// ------------------------------------------------ Auto sync (P0b-02) - lightweight meta polling
let LAST_PINS_REV=null,LAST_SRC_MTIME=null,POLL_FAILS=0,LIGHT_TIMER=null,LIGHT_INFLIGHT=null;
// Single-flight: same pattern as pollBuild - even if visibilitychange/focus/the 5-second timer overlap and
// call this together (e.g. focus returning at the same moment as a tab switch), /api/meta and loadPins only go out once (observed defect: overlapping calls fired loadPins 3 times).
function pollLight(){
  if(document.hidden)return Promise.resolve();   // a heavy refresh (including redrawing the list) is never sent while the tab is hidden
  if(LIGHT_INFLIGHT)return LIGHT_INFLIGHT;
  LIGHT_INFLIGHT=pollLightOnce().finally(()=>{LIGHT_INFLIGHT=null;});
  return LIGHT_INFLIGHT;
}
// While the tab is hidden, the list is never redrawn (observed defect: a hidden tab received no notifications at all), but if notifications
// are on (notifyOn), a light (slow - the browser throttles it anyway) /api/meta?light=1 call is still made just to surface events as notifications.
// This is a notification-only branch splitting off at the same point as pollLight's document.hidden bailout - it never touches the screen.
let NOTIFY_HIDDEN_TIMER=null,NOTIFY_HIDDEN_INFLIGHT=null;
const NOTIFY_HIDDEN_INTERVAL_MS=20000;
function pollHiddenNotify(){
  if(!document.hidden||!notifyOn())return Promise.resolve();
  if(NOTIFY_HIDDEN_INFLIGHT)return NOTIFY_HIDDEN_INFLIGHT;
  NOTIFY_HIDDEN_INFLIGHT=pollHiddenNotifyOnce().finally(()=>{NOTIFY_HIDDEN_INFLIGHT=null;});
  return NOTIFY_HIDDEN_INFLIGHT;
}
async function pollHiddenNotifyOnce(){
  let d;
  try{d=(await api(dq('/api/meta?light=1')+notifyQuery(),{what:'알림 확인',silent:true})).data;}catch(e){return;}
  if(document.hidden)notifyHandle(d);   // if the tab came back while waiting, normal polling has already handled it
}
// If the tab hides while notifications are on, the slow timer is started; it's stopped when the tab returns or notifications are turned off (avoids duplicate polling).
function syncHiddenNotifyTimer(){
  clearInterval(NOTIFY_HIDDEN_TIMER); NOTIFY_HIDDEN_TIMER=null;
  if(document.hidden&&notifyOn()){pollHiddenNotify(); NOTIFY_HIDDEN_TIMER=setInterval(pollHiddenNotify,NOTIFY_HIDDEN_INTERVAL_MS);}
}
async function pollLightOnce(){
  let d; const k=DOC;
  try{d=(await api(dq('/api/meta?light=1')+notifyQuery(),{what:'상태 확인',silent:true})).data; POLL_FAILS=0;}
  catch(e){POLL_FAILS++; if(POLL_FAILS>=2)$('#conn-lost').hidden=false; return;}
  $('#conn-lost').hidden=true;
  notifyHandle(d);                      // browser notifications - independent of the document (handled first even mid document-switch)
  if(k!==DOC)return;                    // the document changed while waiting - the screen is never painted with a stale document's state
  updateStaleBadge(d); updateSyncBadge(d.sync); noteOtherDocs(d.docs);
  // With multiple documents, re-read even if src_sig (per-document src_mtime) changed - another document's manuscript changing shifts that document's pins' lines too.
  const sig=d.src_sig||d.src_mtime;
  if(LAST_PINS_REV!==null&&(d.pins_rev!==LAST_PINS_REV||sig!==LAST_SRC_MTIME)) await loadPins();
  LAST_PINS_REV=d.pins_rev; LAST_SRC_MTIME=sig;
  // A build started via curl by another session/agent is also caught through light meta's build.state - the 1-second poll only
  // runs during that (or when this tab itself pressed rebuild()).
  if(d.build&&d.build.state==='running'&&!BUILD_TIMER)pollBuild();
  // If build_seq (number of finished builds) differs from what this tab has seen, it means a build started and finished entirely
  // within a 5-second polling gap, never observed as "running" - the details are fetched to sync up the screen/banner/chip.
  else if(typeof d.build_seq==='number'&&d.build_seq!==LAST_BUILD_SEQ)pollBuild();
}
// Reflects another document's staleness/in-progress build on its tab, and if that document's build finished in the background, notifies and then drops the meta cache (a fresh page when you switch back).
function noteOtherDocs(list){if(!Array.isArray(list)||!list.length)return; let redraw=false;
  list.forEach(n=>{const d=docInfo(n.key); if(!d)return;
    if(d.stale_build!==n.stale_build||d.building!==n.building){d.stale_build=n.stale_build; d.building=n.building; redraw=true;}
    const was=DOC_SEQ.get(n.key); DOC_SEQ.set(n.key,n.build_seq);
    if(n.key===DOC||was===undefined||was===n.build_seq)return;
    META_BY.delete(n.key); redraw=true;
    if(n.last_state==='ok')toast(tl(d.view_only?'{name} PDF 쪽을 새로 그렸습니다':'{name} PDF 재빌드 완료',{name:d.name}),'ok',{label:'열기',tip:'그 문서로 바꿉니다',fn:()=>switchDoc(n.key)});
    else if(n.last_state==='ok_errors'||n.last_state==='fail')toast(tl(n.last_state==='fail'?'{name} 빌드 실패':'{name} 빌드에 LaTeX 오류',{name:d.name}),n.last_state==='fail'?'err':'warn',{label:'열기',tip:'그 문서로 바꿔 오류를 봅니다',fn:()=>switchDoc(n.key)});});
  if(redraw)drawDocTabs();}
function startLightPolling(){
  clearInterval(LIGHT_TIMER); LIGHT_TIMER=setInterval(pollLight,5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollLight(); syncHiddenNotifyTimer();});
  window.addEventListener('focus',()=>pollLight());
  syncHiddenNotifyTimer();   // catches it right away if already hidden at boot (a rare case) and notifications are on
}
// This tab's own close/drop/reopen/restore already showed a local toast, so the next loadPins()'s
// diffToast never announces the same transition again - only the first diffToast judgment right after markMine(id) is swallowed
// (consumeMine removes it as soon as it's confirmed), and if that judgment hasn't arrived after 10 seconds (e.g. a lost response), it's
// given up on and subsequent values are announced normally. An action from another tab isn't in this map, so it's shown as usual.
const MY_ACTIONS=new Map();
function markMine(id){MY_ACTIONS.set(id,Date.now()+10000);}
function consumeMine(id){const until=MY_ACTIONS.get(id); if(until===undefined)return false;
  MY_ACTIONS.delete(id); return Date.now()<=until;}
function diffToast(prev,d,dropped){
  // prev is only the "open pins" this tab saw last time (PINS never holds done ones). d is every open+closed
  // pin (all=1) from this GET - if an id that was in prev is also in d with done=true, it was completed; if it's
  // not in d at all (neither open nor closed), it was dropped. The old implementation never distinguished the
  // two and announced everything as "completed" - if a co-author deleted a pin, the author's screen showed "#N 이 완료되었습니다" (observed).
  if(!prev||!prev.length)return;
  const byId=new Map(prev.map(p=>[p.id,p]));
  const known=new Map((d||[]).map(p=>[p.id,p]));
  const dropById=new Map((dropped||[]).map(p=>[p.id,p]));
  const closed=[],droppedIds=[],reviewed=[];
  byId.forEach((_,id)=>{const n=known.get(id);
    if(n&&n.done){if(!consumeMine(id))(n.review?reviewed:closed).push(id);}
    else if(!n){if(!consumeMine(id))droppedIds.push(id);}});
  if(closed.length)toast(tl('#{ids} 이 완료되었습니다',{ids:closed.join(', #'),n:closed.length}),'ok');
  if(reviewed.length)toast(tl('#{ids} 이 검토 대기로 넘어왔습니다 — 결과를 보고 [확인]하세요',{ids:reviewed.join(', #'),n:reviewed.length}),'ok',null,{keys:reviewed.map(i=>'review_requested:'+i)});
  droppedIds.forEach(id=>{const rec=dropById.get(id),nm=rec?who(rec.dropped_by):'';
    toast(tl('#{id} 을 {name} 가 삭제함',{id,name:nm||tr('다른 세션')}),'warn',{label:'되살리기',fn:()=>restorePin(id)},{keys:['dropped:'+id]});});
  (d||[]).filter(p=>!p.done).forEach(p=>{const was=byId.get(p.id); if(!was)return;
    if(!was.stale&&p.stale){toast(tl('#{id} 위치를 잃었습니다',{id:p.id}),'warn');return;}
    const m=/^moved ([+-]\d+)$/.exec(p.sync||''),wm=/^moved ([+-]\d+)$/.exec(was.sync||'');
    if(m&&(!wm||wm[1]!==m[1]))toast(tl('#{id} 줄 {delta} 이동',{id:p.id,delta:m[1]}),'ok');});
}

// Announces when a pin that was awaiting review gets confirmed (done) or reopened elsewhere. An action this tab performed (markMine) is swallowed.
function pinState(p){return (p&&p.state)||(p&&p.done?(p.review?'review':'done'):'open');}
function reviewToast(prev,d){if(!prev||!prev.length)return; const known=new Map((d||[]).map(p=>[p.id,p]));
  prev.forEach(p=>{const n=known.get(p.id); if(!n)return; const st=pinState(n); if(st==='review')return; if(consumeMine(p.id))return;
    if(st==='done')toast(tl('#{id} 확인됨',{id:p.id})+(n.confirmed_by?' · '+who(n.confirmed_by):''),'ok');
    else toast(tl('#{id} 다시 열림',{id:p.id})+(n.reopened_by?' · '+who(n.reopened_by):''),'warn',null,{keys:['reopened:'+p.id]});});}

