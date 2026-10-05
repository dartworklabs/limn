// ------------------------------------------------ Async build-progress chip (docs/handbook/build-sync.md §비동기 재빌드)
// BUILD.timer only exists while a build is actually running - /api/build is never hit every second once there's
// nothing to do (already settled into idle/ok/fail). There are only three places it starts: this tab pressing rebuild(),
// pollLight (the 5-second poll) seeing build.state==='running', and catching an already-running build at boot.
// A finished build is counted via build_seq (the server bumps it by 1 per build). BUILD.lastSeq is the value this tab
// has already processed - processing (swapping the screen, saying so) happens exactly once per seq. Counting via the
// started_at string or "was running ever observed" instead missed a build that finished within a 5-second gap, or
// double-processed the same completion when a hidden tab came back via two paths at once (observed: said twice).
// The active document visit owns one poll timer, request and completion baseline; the error panel follows that visit.
// BUILD.cur is the running build's last /api/build answer (null when none runs): the status line reads its phase and seconds.
// BUILD.unchanged is {pull} while the status line answers an unchanged rebuild of this tab (buildUnchanged), else null.
const BUILD={timer:/** @type {ReturnType<typeof setInterval>|null} */(null),error:/** @type {any} */(null),lastSeq:/** @type {number|null} */(null),booted:false,
  inflight:/** @type {Promise<void>|null} */(null),asked:false,cur:/** @type {BuildStatus|null} */(null),unchanged:/** @type {{pull:string}|null} */(null)};
// Reset the visible build controls and baseline when a different document takes the screen.
function resetBuildForDoc(){if(BUILD.timer){clearInterval(BUILD.timer);BUILD.timer=null;}
  BUILD.cur=null; BUILD.unchanged=null; $('#build-chip').hidden=true; $('#btn-rebuild').disabled=false;
  BUILD.lastSeq=(typeof META.build_seq==='number')?META.build_seq:0; BUILD.asked=false; BUILD.error=BUILD_ERR_BY.get(DOC)||null;
  if(BUILD.error)hideBuildErr(); else{$('#build-err').hidden=true; $('#build-err-chip').hidden=true;}
  BUILD.booted=true; if(BUILD.inflight)BUILD.inflight.then(()=>pollBuild()); else pollBuild();}
function buildChipText(b){
  const label={pull:'원격 main 당겨오는 중',copy:'원고 복사 중',latex:'LaTeX 컴파일 중',render:'쪽 그리는 중'}[b.phase]||'재빌드 중';
  const el=Math.round(b.elapsed_s||0), last=b.last_s?' '+tl('(지난번 {s}초)',{s:Math.round(b.last_s)}):'';
  return tr(label)+' · '+tl('{s}초',{s:el})+last;
}
// --git-pull (docs/handbook/build-sync.md §재빌드 전 원격 main 당겨오기): appends one line about the pull result to the
// build's completion (the status line's message, or the error panel's title). ok gets the applied commit range,
// skipped/error just the reason - up_to_date has nothing worth reporting, so nothing is appended.
function pullSuffix(b){
  const p=b&&b.pull; if(!p||!p.state)return '';
  if(p.state===PULL_STATE.OK)return ' · '+tl('원격 반영 {range}',{range:String(p.head_before||'?').slice(0,7)+'..'+String(p.head_after||'?').slice(0,7)});
  if(p.state===PULL_STATE.SKIPPED||p.state===PULL_STATE.ERROR)return ' · '+tl(p.state===PULL_STATE.ERROR?'git pull 실패({reason})':'git pull 건너뜀({reason})',{reason:p.reason||'?'});
  return '';
}
// Single-flight: if a request is already in flight, that same promise is returned instead of sending a new one (even if the
// 1-second timer, visibilitychange, focus, and pollLight all call it together, /api/build only goes out once and completion is only processed once).
function pollBuild(){
  if(document.hidden)return Promise.resolve();   // the request is never even sent while the tab is hidden
  if(BUILD.inflight)return BUILD.inflight;
  BUILD.inflight=pollBuildOnce().finally(()=>{BUILD.inflight=null;});
  return BUILD.inflight;
}
// One /api/build poll for the document on screen: shows or hides the progress chip and the 1-second timer, and processes a
// finished build exactly once per `seq` (refresh the pages; a success says so on the status line for NOTICE_MS, a failure or
// LaTeX errors open the error panel, and the line's failure item and the chips keep it). A rebuild this tab asked for that kept
// the pages (unchanged: true, the same seq) gets one "no changes" answer on the status line whose [그래도 빌드] forces a cold
// rebuild (buildUnchanged). A reply that arrives after a document switch is dropped. Resolves with nothing and never throws; a
// failed request is ignored (the next poll retries).
async function pollBuildOnce(){
  let b; const k=DOC,visit=SWITCHSEQ;
  try{b=(await api(dq('/api/build?log=1'),{what:'빌드 상태',silent:true})).data;}catch(e){return;}
  if(k!==DOC||visit!==SWITCHSEQ)return;  // showDoc queries again after a switch, including a return to this key
  const chip=$('#build-chip');
  if(b.state===BUILD_STATE.RUNNING){
    BUILD.cur=b; BUILD.unchanged=null; chip.hidden=false; chip.textContent=buildChipText(b); $('#btn-rebuild').disabled=true;
    if(!BUILD.timer)BUILD.timer=setInterval(pollBuild,1000);
    BUILD.booted=true; return;
  }
  BUILD.cur=null; chip.hidden=true; $('#btn-rebuild').disabled=false;
  if(BUILD.timer){clearInterval(BUILD.timer);BUILD.timer=null;}    // polling stops once there's nothing left to watch
  const seq=(typeof b.seq==='number')?b.seq:0;
  const booted=BUILD.booted; BUILD.booted=true;
  if(BUILD.lastSeq===null)BUILD.lastSeq=seq;
  if(seq===BUILD.lastSeq&&BUILD.asked&&b.unchanged===true){
    BUILD.asked=false; buildUnchanged(b);
  }else if(seq!==BUILD.lastSeq){
    BUILD.lastSeq=seq; BUILD.asked=false;  // claimed before the await - so the same completion is never processed twice
    DOC_SEQ.set(k,seq);
    try{await refreshDoc();}catch(e){}
    if(k!==DOC||visit!==SWITCHSEQ)return;
    const secs=Math.round(b.elapsed_s||0);
    if(b.state===BUILD_STATE.OK){lineNote(tr(!buildsFromSource(META.kind)?'PDF가 바뀌어 쪽을 새로 그렸습니다':'PDF 재빌드 완료')+' · '+tl('{n}쪽',{n:META.pages.length})+' · '+tl('{s}초',{s:secs})+pullSuffix(b),NOTICE_KIND.OK,null,{life:NOTICE_LIFE.TIMER}); BUILD.error=null; BUILD_ERR_BY.delete(k); hideBuildErr();}
    else if(b.state===BUILD_STATE.OK_ERRORS||b.state===BUILD_STATE.FAIL)showBuildErr(b);   // its panel opens; the line and the chips keep the failure
  }else if(!booted&&(b.state===BUILD_STATE.FAIL||b.state===BUILD_STATE.OK_ERRORS)){
    showBuildErr(b);   // a freshly opened tab - a build that already failed just opens the panel/chip (leaves a way to look at it again)
  }
}
function startBuildPolling(){
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollBuild();});
  window.addEventListener('focus',()=>pollBuild());
  pollBuild();   // once at boot - if a build is already running (started by another session), this turns on the 1-second poll
}
