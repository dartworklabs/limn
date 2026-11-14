// ------------------------------------------------ Auto sync - lightweight meta polling (docs/handbook/build-sync.md §자동 동기화 (가벼운 meta 폴링))
let LAST_PINS_REV=/** @type {string|null} */(null),LAST_SRC_MTIME=/** @type {string|number|null} */(null),POLL_FAILS=0,
  LIGHT_TIMER=/** @type {ReturnType<typeof setInterval>|undefined} */(undefined),LIGHT_INFLIGHT=/** @type {Promise<void>|null} */(null);
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
let NOTIFY_HIDDEN_TIMER=/** @type {ReturnType<typeof setInterval>|undefined} */(undefined),NOTIFY_HIDDEN_INFLIGHT=/** @type {Promise<void>|null} */(null);
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
  clearInterval(NOTIFY_HIDDEN_TIMER); NOTIFY_HIDDEN_TIMER=undefined;
  if(document.hidden&&notifyOn()){pollHiddenNotify(); NOTIFY_HIDDEN_TIMER=setInterval(pollHiddenNotify,NOTIFY_HIDDEN_INTERVAL_MS);}
}
// Applies connection and document status only to the visit that sent the request; notifications remain independent of document visits.
// Back after AWAY_MS without an answer (the tab hidden, the device asleep, the connection lost), what this poll and the build
// it may set going say is gathered into one message (notices.js digestBegin, docs/handbook/viewer.md §새 소식); a poll back
// from that, or one every VERSION_EVERY_MS, asks which Limn the server runs (updates.js checkVersion).
let LIGHT_OK_AT=0;
const AWAY_MS=120000;
async function pollLightOnce(){
  let d; const k=DOC,visit=SWITCHSEQ,gap=LIGHT_OK_AT?Date.now()-LIGHT_OK_AT:0,back=gap>=AWAY_MS,lost=POLL_FAILS>=2;
  if(back)digestBegin(awayTitle(gap,lost));
  try{d=(await api(dq('/api/meta?light=1')+notifyQuery(),{what:'상태 확인',silent:true})).data;}
  catch(e){if(back)digestSoon(); if(k!==DOC||visit!==SWITCHSEQ)return;
    POLL_FAILS++; if(POLL_FAILS===2)announce(tr('연결 끊김 · 다시 잇는 중'),true);   // read out once, as it is lost (rule 1)
    if(POLL_FAILS>=2)$('#conn-lost').hidden=false; return;}
  const was=POLL_FAILS; LIGHT_OK_AT=Date.now();
  notifyHandle(d);                      // browser notifications - independent of the document (handled first even mid document-switch)
  if(k!==DOC||visit!==SWITCHSEQ){if(back)digestSoon(DIGEST_TAIL_MS); return;}  // a return to the same document is a new visit too
  POLL_FAILS=0; $('#conn-lost').hidden=true;
  if(back||was>0||versionDue())checkVersion();
  if(was>0&&OFF.n)void offlineFlush();   // the connection is back: the pins kept while it was gone are written (offline.js)
  updateStaleBadge(d); updateSyncBadge(d.sync); noteOtherDocs(d.docs);
  // With multiple documents, re-read even if src_sig (per-document src_mtime) changed - another document's manuscript changing shifts that document's pins' lines too.
  const sig=d.src_sig||d.src_mtime;
  // A failed or superseded pin refresh has not observed this revision; retry it on the next light poll.
  const needsPins=LAST_PINS_REV===null||d.pins_rev!==LAST_PINS_REV||sig!==LAST_SRC_MTIME;
  if(sig!==LAST_SRC_MTIME||d.building||(d.sync&&d.sync.state===SYNC_STATE.UPDATING))updExpect(sig!==LAST_SRC_MTIME);   // its pins' moves wait for its update message
  const applied=!needsPins||await loadPins();
  if(k!==DOC||visit!==SWITCHSEQ)return;
  // Its source changed since the last read that answered: the Markdown surface reads and draws it again, asked once per change
  // while that read is on its way (MD.asked), and again on the next poll if it failed (mdBuild clears MD.asked).
  if(isMdDoc()&&d.src_mtime!==MD.mtime&&d.src_mtime!==MD.asked){MD.asked=d.src_mtime; mdBuild();}
  else if(isMdDoc())void mdPicCheck();   // a tree image rewritten on disk shows without a reload (md-surface.js)
  if(applied){LAST_PINS_REV=d.pins_rev; LAST_SRC_MTIME=sig;}
  // A build started via curl by another session/agent is also caught through light meta's build.state - the 1-second poll only
  // runs during that (or when this tab itself pressed rebuild()).
  if(d.build&&d.build.state===BUILD_STATE.RUNNING&&!BUILD.timer)pollBuild();
  // If build_seq (number of finished builds) differs from what this tab has seen, it means a build started and finished entirely
  // within a 5-second polling gap, never observed as "running" - the details are fetched to sync up the screen/banner/chip.
  else if(typeof d.build_seq==='number'&&d.build_seq!==BUILD.lastSeq)pollBuild();
  if(back)digestSoon(DIGEST_TAIL_MS);
}
// Reflects another document's staleness/in-progress build on its tab, and if that document's build finished in the background,
// says so on the status line with [열기] - a success for NOTICE_MS, a failure until [x] - and drops the meta cache (a fresh page
// when you switch back).
// A finished build of another document - or a new source of another Markdown or text document - is its update: said as that
// document's update message with [열기] (updates.js checkDocUpdate, docs/handbook/viewer.md §새 소식).
function noteOtherDocs(list){if(!Array.isArray(list)||!list.length)return; let redraw=false;
  list.forEach(n=>{const d=docInfo(n.key); if(!d)return;
    if(d.stale_build!==n.stale_build||d.building!==n.building){d.stale_build=n.stale_build; d.building=n.building; redraw=true;}
    const src=d.src_mtime; d.src_mtime=n.src_mtime; d.pages_build=n.pages_build;
    if(n.key!==DOC&&rendersInBrowser(d.kind)&&src!==undefined&&src!==n.src_mtime)checkDocUpdate(n.key,{});
    const was=DOC_SEQ.get(n.key); DOC_SEQ.set(n.key,n.build_seq);
    if(n.key===DOC||was===undefined||was===n.build_seq)return;
    META_BY.delete(n.key); redraw=true;
    if(n.last_state===BUILD_STATE.OK)checkDocUpdate(n.key,{});
    else if(n.last_state===BUILD_STATE.OK_ERRORS||n.last_state===BUILD_STATE.FAIL)lineNote(tl(n.last_state===BUILD_STATE.FAIL?'{name} 빌드 실패':'{name} 빌드에 LaTeX 오류',{name:d.name}),
      n.last_state===BUILD_STATE.FAIL?NOTICE_KIND.ERR:NOTICE_KIND.WARN,{label:'열기',tip:'그 문서로 바꿔 오류를 봅니다',fn:()=>switchDoc(n.key)},{literal:true});});
  if(redraw)drawDocTabs();}
function startLightPolling(){
  clearInterval(LIGHT_TIMER); LIGHT_TIMER=setInterval(pollLight,5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollLight(); syncHiddenNotifyTimer();});
  window.addEventListener('focus',()=>pollLight());
  syncHiddenNotifyTimer();   // catches it right away if already hidden at boot (a rare case) and notifications are on
}
// This tab's own close/drop/reopen/restore already said so where it happened, so the next loadPins()'s
// A list comparison's group without the pins whose events a message of a higher rank says (groupNote's less): the pins named
// '<type>:<id>' leave data[field] - numbers or pins - and each of also beside them, or null when none is left. Pure.
/** @param {string} type @param {string} field @param {...string} also @returns {(d:any,keys:string[])=>any} */
function newsWithout(type,field,...also){return (d,keys)=>{const keep=d[field].map((/** @type {any} */x)=>!keys.includes(type+':'+(typeof x==='number'?x:x.id)));
  if(!keep.some(Boolean))return null; const out={...d}; [field,...also].forEach(f=>{out[f]=d[f].filter((/** @type {any} */_,/** @type {number} */i)=>keep[i]);}); return out;};}
// notePinChanges never announces the same transition again - only the first notePinChanges judgment right after markMine(id) is swallowed
// (consumeMine removes it as soon as it's confirmed), and if that judgment hasn't arrived after 10 seconds (e.g. a lost response), it's
// given up on and subsequent values are announced normally. An action from another tab isn't in this map, so it's shown as usual.
const MY_ACTIONS=new Map();
function markMine(id){MY_ACTIONS.set(id,Date.now()+10000);}
function consumeMine(id){const until=MY_ACTIONS.get(id); if(until===undefined)return false;
  MY_ACTIONS.delete(id); return Date.now()<=until;}
// Says on the status line what changed between two list refreshes (docs/handbook/viewer.md §알림 자리): pins sent to review
// ([보기], a dot on [검토 M]), dropped ([되살리기]) or closed by someone else, and an open pin whose location or figure element
// was lost or whose lines moved. What needs a look stays until [x] or its action and dots [핀 N]; passing news (closed
// elsewhere, lines moved) goes after NOTICE_MS. An action this tab performed is swallowed (markMine).
function notePinChanges(prev,d,dropped){
  // prev is only the "open pins" this tab saw last time (PINS never holds done ones). d is every open+closed
  // pin (all=1) from this GET - if an id that was in prev is also in d with done=true, it was completed; if it's
  // not in d at all (neither open nor closed), it was dropped. The old implementation never distinguished the
  // two and announced everything as "completed" - if a co-author deleted a pin, the author's screen showed "#N 이 완료되었습니다" (observed).
  if(!prev||!prev.length)return;
  const byId=new Map(prev.map(p=>[p.id,p]));
  const known=new Map((d||[]).map(p=>[p.id,p]));
  const dropById=new Map((dropped||[]).map(p=>[p.id,p]));
  const closed=[],droppedIds=[],reviewed=[];
  byId.forEach((_,id)=>{const n=known.get(id),st=n&&pinState(n);
    if(n&&st!==PIN_STATE.OPEN){if(!consumeMine(id))(st===PIN_STATE.REVIEW?reviewed:closed).push(id);}
    else if(!n){if(!consumeMine(id))droppedIds.push(id);}});
  // Each kind of change is one message however many pins and polls it spans (groupNote): up to three pins by number, more
  // as a count with the first numbers after it ('핀 12개가 완료되었습니다 — #3, #5, #8 외 9개').
  const ids=(/** @type {number[]} */a)=>a.slice(0,3).map(i=>'#'+i).join(', ')+(a.length>3?' '+tl('외 {n}개',{n:a.length-3}):'');
  const some=(/** @type {number[]} */a,one,many)=>a.length<=3?tl(one,{ids:a.join(', #'),n:a.length}):tl(many,{n:a.length})+' — '+ids(a);
  const merge=(/** @type {any} */a,/** @type {any} */b)=>({...b,ids:[...new Set([...a.ids,...b.ids])]});
  if(closed.length)groupNote('done',{ids:closed},g=>({msg:some(g.ids,'#{ids} 이 완료되었습니다','핀 {n}개가 완료되었습니다'),kind:NOTICE_KIND.OK,act:null,
    o:{life:NOTICE_LIFE.TIMER,dot:NOTICE_DOT.SIDE,literal:true,brief:tl('완료 {n}',{n:g.ids.length})}}),merge);
  if(reviewed.length)groupNote('review',{ids:reviewed},g=>({msg:g.ids.length<=3?tl('#{ids} 이 검토 대기로 넘어왔습니다 — 결과를 보고 [확인]하세요',{ids:g.ids.join(', #'),n:g.ids.length})
      :tl('핀 {n}개가 검토 대기로 넘어왔습니다',{n:g.ids.length})+' — '+ids(g.ids),kind:NOTICE_KIND.OK,act:{label:'보기',tip:'검토 대기 핀으로 갑니다',fn:gotoReview},
    o:{keys:g.ids.map(i=>EVENT_TYPE.REVIEW_REQUESTED+':'+i),dot:NOTICE_DOT.RV,literal:true,brief:tl('검토 대기 {n}',{n:g.ids.length})}}),merge,newsWithout(EVENT_TYPE.REVIEW_REQUESTED,'ids'));
  // One dropped pin offers [되살리기]; several, the Trash they are in.
  if(droppedIds.length)groupNote('drop',{ids:droppedIds,names:droppedIds.map(id=>{const rec=dropById.get(id); return (rec&&who(rec.dropped_by))||tr('다른 세션');})},g=>{
    const name=[...new Set(g.names)].join(', '),one=g.ids.length===1,id=g.ids[0];
    return {msg:one?tl('#{id}{o} {name}{p} 삭제함',{id,o:josa(id,'을','를'),name,p:josaName(name,'이','가')}):tl('핀 {n}개를 {name}{p} 삭제함',{n:g.ids.length,name,p:josaName(name,'이','가')})+' — '+ids(g.ids),
      kind:NOTICE_KIND.WARN,act:one?{label:'되살리기',wait:true,fn:()=>restorePin(id)}:{label:'휴지통',tip:'지운 핀을 휴지통에서 봅니다',fn:()=>openTrash(id)},
      o:{keys:g.ids.map(i=>EVENT_TYPE.DROPPED+':'+i),dot:NOTICE_DOT.SIDE,literal:true,brief:tl('삭제됨 {n}',{n:g.ids.length})}};},   // tl() spoke the UI language; the name is as written
    (a,b)=>{const add=b.ids.map((i,j)=>j).filter(j=>!a.ids.includes(b.ids[j]));   // names stay beside their ids
      return {ids:[...a.ids,...add.map(j=>b.ids[j])],names:[...a.names,...add.map(j=>b.names[j])]};},newsWithout(EVENT_TYPE.DROPPED,'ids','names'));
  const lost=[],gone=[],moved=[]; (d||[]).filter(p=>pinState(p)===PIN_STATE.OPEN).forEach(p=>{const was=byId.get(p.id); if(!was)return;
    if(!was.stale&&p.stale){lost.push(p); return;}
    if(was.el_sync!==EL_SYNC.LOST&&p.el_sync===EL_SYNC.LOST){gone.push(p); return;}   // a re-render lost a figure pin's element
    const m=/^moved ([+-]\d+)$/.exec(p.sync||''),wm=/^moved ([+-]\d+)$/.exec(was.sync||'');
    if(m&&p.el_sync!==EL_SYNC.OK&&(!wm||wm[1]!==m[1]))moved.push({id:p.id,delta:m[1],p});});
  // A pin that lost its place asks for a new one: said on its own, and counted in its document's update message.
  lost.forEach(p=>updPinMoved(p,true)); gone.forEach(p=>updPinMoved(p,true));
  const each=(/** @type {number[]} */a,one,many)=>a.length===1?tl(one,{id:a[0]}):tl(many,{n:a.length})+' — '+ids(a);
  if(lost.length)groupNote('lost',{ids:lost.map(p=>p.id)},g=>({msg:each(g.ids,'#{id} 위치를 잃었습니다','핀 {n}개가 위치를 잃었습니다'),kind:NOTICE_KIND.WARN,act:null,
    o:{dot:NOTICE_DOT.SIDE,literal:true,brief:tl('위치 잃음 {n}',{n:g.ids.length})}}),merge);
  if(gone.length)groupNote('el-lost',{ids:gone.map(p=>p.id)},g=>({msg:each(g.ids,'#{id} 요소를 잃었습니다','핀 {n}개가 요소를 잃었습니다'),kind:NOTICE_KIND.WARN,act:null,
    o:{dot:NOTICE_DOT.SIDE,literal:true,brief:tl('요소 잃음 {n}',{n:g.ids.length})}}),merge);
  // Lines that moved with a document's update are said in its update message; others pass by as one message.
  const said=moved.filter(x=>!updPinMoved(x.p,false));
  if(said.length)groupNote('moved',{moves:said.map(x=>({id:x.id,delta:x.delta}))},g=>{const ms=g.moves.slice(-12);
    return {msg:ms.length===1?tl('#{id} 줄 {delta} 이동',{id:ms[0].id,delta:ms[0].delta}):tl('핀 {n}개 줄 이동',{n:g.moves.length})+' — '+ms.map(/** @param {any} x */x=>'#'+x.id+' '+x.delta).join(', '),
      kind:NOTICE_KIND.OK,act:null,o:{life:NOTICE_LIFE.TIMER,literal:true}};},
    (a,b)=>({moves:[...a.moves.filter(/** @param {any} x */x=>!b.moves.some(/** @param {any} y */y=>y.id===x.id)),...b.moves]}));
}

// Says on the status line when a pin that was awaiting review gets confirmed (done; passing news) or reopened (until [x], with
// a dot on [핀 N]) elsewhere. An action this tab performed (markMine) is swallowed.
/** @param {Pin} p */
function pinState(p){return (p&&p.state)||(p&&p.done?(p.review?PIN_STATE.REVIEW:PIN_STATE.DONE):PIN_STATE.OPEN);}
function noteReviewChanges(prev,d){if(!prev||!prev.length)return; const known=new Map((d||[]).map(p=>[p.id,p]));
  const ok=[],back=[]; prev.forEach(p=>{const n=known.get(p.id); if(!n)return; const st=pinState(n); if(st===PIN_STATE.REVIEW)return; if(consumeMine(p.id))return;
    (st===PIN_STATE.DONE?ok:back).push({id:p.id,by:who(st===PIN_STATE.DONE?n.confirmed_by:n.reopened_by)});});
  // Each is one message however many pins (groupNote): one pin with who did it, more as a count.
  const text=(/** @type {{id:number,by:string}[]} */a,one,many)=>a.length===1?tl(one,{id:a[0].id})+(a[0].by?' · '+a[0].by:''):tl(many,{n:a.length})+' — '+a.slice(0,3).map(x=>'#'+x.id).join(', ')+(a.length>3?' '+tl('외 {n}개',{n:a.length-3}):'');
  const merge=(/** @type {any} */a,/** @type {any} */b)=>({pins:[...a.pins,...b.pins.filter(x=>!a.pins.some(y=>y.id===x.id))]});
  if(ok.length)groupNote('confirmed',{pins:ok},g=>({msg:text(g.pins,'#{id} 확인됨','핀 {n}개 확인됨'),kind:NOTICE_KIND.OK,act:null,o:{life:NOTICE_LIFE.TIMER,dot:NOTICE_DOT.SIDE,literal:true,brief:tl('확인됨 {n}',{n:g.pins.length})}}),merge);
  if(back.length)groupNote('reopened',{pins:back},g=>({msg:text(g.pins,'#{id} 다시 열림','핀 {n}개 다시 열림'),kind:NOTICE_KIND.WARN,act:null,
    o:{keys:g.pins.map(x=>EVENT_TYPE.REOPENED+':'+x.id),dot:NOTICE_DOT.SIDE,literal:true,brief:tl('다시 열림 {n}',{n:g.pins.length})}}),merge,newsWithout(EVENT_TYPE.REOPENED,'pins'));}
