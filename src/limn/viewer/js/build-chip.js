// ------------------------------------------------ Async build-progress chip (docs/handbook/build-sync.md §비동기 재빌드)
// BUILD_TIMER only exists while a build is actually running - /api/build is never hit every second once there's
// nothing to do (already settled into idle/ok/fail). There are only three places it starts: this tab pressing rebuild(),
// pollLight (the 5-second poll) seeing build.state==='running', and catching an already-running build at boot.
// A finished build is counted via build_seq (the server bumps it by 1 per build). LAST_BUILD_SEQ is the value this tab
// has already processed - processing (swapping the screen, toasting) happens exactly once per seq. Counting via the
// started_at string or "was running ever observed" instead missed a build that finished within a 5-second gap, or
// double-processed the same completion when a hidden tab came back via two paths at once (observed: toast x2).
let BUILD_TIMER=null,LAST_BUILD_ERR=null,LAST_BUILD_SEQ=null,BUILD_BOOTED=false,BUILD_INFLIGHT=null;
function buildChipText(b){
  const label={pull:'원격 main 당겨오는 중',copy:'원고 복사 중',latex:'LaTeX 컴파일 중',render:'쪽 그리는 중'}[b.phase]||'재빌드 중';
  const el=Math.round(b.elapsed_s||0), last=b.last_s?' '+tl('(지난번 {s}초)',{s:Math.round(b.last_s)}):'';
  return tr(label)+' · '+tl('{s}초',{s:el})+last;
}
// --git-pull (docs/handbook/build-sync.md §재빌드 전 원격 main 당겨오기): appends one line about the pull result to the
// build-complete toast. ok gets the applied commit range,
// skipped/error just the reason - up_to_date has nothing worth reporting, so nothing is appended.
function pullSuffix(b){
  const p=b&&b.pull; if(!p||!p.state)return '';
  if(p.state==='ok')return ' · '+tl('원격 반영 {range}',{range:String(p.head_before||'?').slice(0,7)+'..'+String(p.head_after||'?').slice(0,7)});
  if(p.state==='skipped'||p.state==='error')return ' · '+tl(p.state==='error'?'git pull 실패({reason})':'git pull 건너뜀({reason})',{reason:p.reason||'?'});
  return '';
}
// Single-flight: if a request is already in flight, that same promise is returned instead of sending a new one (even if the
// 1-second timer, visibilitychange, focus, and pollLight all call it together, /api/build only goes out once and completion is only processed once).
function pollBuild(){
  if(document.hidden)return Promise.resolve();   // the request is never even sent while the tab is hidden
  if(BUILD_INFLIGHT)return BUILD_INFLIGHT;
  BUILD_INFLIGHT=pollBuildOnce().finally(()=>{BUILD_INFLIGHT=null;});
  return BUILD_INFLIGHT;
}
async function pollBuildOnce(){
  let b; const k=DOC;
  try{b=(await api(dq('/api/build?log=1'),{what:'빌드 상태',silent:true})).data;}catch(e){return;}
  if(k!==DOC)return;                    // the document changed - showDoc will query the new one again
  const chip=$('#build-chip');
  if(b.state==='running'){
    chip.hidden=false; chip.textContent=buildChipText(b); $('#btn-rebuild').disabled=true;
    if(!BUILD_TIMER)BUILD_TIMER=setInterval(pollBuild,1000);
    BUILD_BOOTED=true; return;
  }
  chip.hidden=true; $('#btn-rebuild').disabled=false;
  if(BUILD_TIMER){clearInterval(BUILD_TIMER);BUILD_TIMER=null;}    // polling stops once there's nothing left to watch
  const seq=(typeof b.seq==='number')?b.seq:0;
  const booted=BUILD_BOOTED; BUILD_BOOTED=true;
  if(LAST_BUILD_SEQ===null)LAST_BUILD_SEQ=seq;
  if(seq!==LAST_BUILD_SEQ){
    LAST_BUILD_SEQ=seq;                 // claimed before the await - so the same completion is never processed twice
    DOC_SEQ.set(k,seq);
    try{await refreshDoc();}catch(e){}
    if(k!==DOC)return;
    const secs=Math.round(b.elapsed_s||0);
    if(b.state==='ok'){toast(tr(META.view_only?'PDF가 바뀌어 쪽을 새로 그렸습니다':'PDF 재빌드 완료')+' · '+tl('{n}쪽',{n:META.pages.length})+' · '+tl('{s}초',{s:secs})+pullSuffix(b),'ok'); LAST_BUILD_ERR=null; BUILD_ERR_BY.delete(k); hideBuildErr();}
    else if(b.state==='ok_errors'){toast(tr('PDF를 재빌드했지만 LaTeX 오류가 있습니다')+pullSuffix(b),'warn'); showBuildErr(b);}
    else if(b.state==='fail'){toast(tr('빌드 실패 — 화면은 이전 PDF입니다')+pullSuffix(b),'err'); showBuildErr(b);}
  }else if(!booted&&(b.state==='fail'||b.state==='ok_errors')){
    showBuildErr(b);   // a freshly opened tab - a build that already failed just opens the panel/chip with no toast (leaves a way to look at it again)
  }
}
function startBuildPolling(){
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollBuild();});
  window.addEventListener('focus',()=>pollBuild());
  pollBuild();   // once at boot - if a build is already running (started by another session), this turns on the 1-second poll
}

