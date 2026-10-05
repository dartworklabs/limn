// ------------------------------------------------ The status line (docs/handbook/viewer.md §모바일 레이아웃, 상태는 한 줄이다)
// One element, #status, shows one state at a time on every band, in the band's place (placeStatus): a 24px line on the phone
// and tablet sheet's top edge (#status-dock, outside the sheet so its action can reach 44px up over the PDF), a short text in
// the short band's top row and the middle of the mid action row (#status-slot), and on the desktop (wide) a line under the
// status chips (#status-wide). The line is the compact face of those chips: whenever one of them changes (a MutationObserver
// on #bar2) it is drawn again from the state they come from. It also carries the messages of notices.js (LINE): background
// events, first-visit hints and an undo whose place has left the screen - the only items the desktop's line shows besides
// a rebuild's 'no changes', since its chips say the rest (statusShown).
let STATUS_SYNC=/** @type {SyncStatus|null} */(null),STATUS_SIG='';   // the last meta `sync`; the drawn item's kind, action and count
let STATUS_TOP=0;   // the number of the message the line shows (0: none, or another item): lineNote reads out one it does not
const STATUS_TRANSIENT_MS=6000;   // a passing answer (no changes) stays on the line as long as an undo's window (NOTICE_MS)

// A build's countable progress {done, total}: integers with total > 0 and 0 <= done <= total, else null - as if the field were
// missing (GET /api/build `progress`: the pages drawn of the PDF's while a render runs, null otherwise, absent from an older
// server; without it the bar does not know its end, docs/handbook/build-sync.md §진행 폴링). Pure.
function statusProgress(pr){if(!pr||typeof pr!=='object')return null; const {done,total}=pr;
  return Number.isInteger(done)&&Number.isInteger(total)&&total>0&&done>=0&&done<=total?{done,total}:null;}

// The items the status line shows for s = {notices, build, buildErr, offline, sync, stale, png, canRebuild, unchanged}
// (statusInput), highest priority first - errors before information (docs/handbook/viewer.md §알림 자리, rule 1): the line's
// error messages (alert, or kind ERR), newest first (notices, notices.js LINE; act 'notice'); the last build failed or had
// LaTeX errors; the connection is lost; the line's other messages, newest first; a build runs (rendering in the
// page render, else building); main sync is blocked; this tab's rebuild changed nothing (unchanged, for STATUS_TRANSIENT_MS);
// the PDF is older than its source - not while a build runs, which clears it, nor while the unchanged answer says the
// rebuild found nothing new (the line would contradict itself); main sync is under way; the PDF shows as PNG. Each item is {kind, act} plus what
// its text needs; act is the data-act of its one action, or null - [재빌드] and [그래도 빌드] (rebuild-force, a cold build)
// only where canRebuild (a LaTeX document and a person who may build). The phase whose work can
// be counted - the page render, whose progress field gives pages done of total - is looked up, not compared. Pure.
function statusList(s){const out=[],b=s.build,running=!!b&&b.state===BUILD_STATE.RUNNING,e=s.buildErr,sy=s.sync&&s.sync.state;
  const notes=s.notices||[],alert=(/** @type {Notice} */ n)=>!!n.alert||n.kind===NOTICE_KIND.ERR;
  notes.filter(alert).forEach(n=>out.push({kind:STATUS_KIND.NOTICE,notice:n,act:'notice'}));
  if(e&&e.state===BUILD_STATE.FAIL)out.push({kind:STATUS_KIND.FAILED,act:'build-err-reopen'});
  else if(e&&e.state===BUILD_STATE.OK_ERRORS)out.push({kind:STATUS_KIND.ERRORS,n:(e.errors||[]).length,act:'build-err-reopen'});
  if(s.offline)out.push({kind:STATUS_KIND.OFFLINE,act:null});
  notes.filter(n=>!alert(n)).forEach(n=>out.push({kind:STATUS_KIND.NOTICE,notice:n,act:'notice'}));
  if(running)out.push({kind:{render:STATUS_KIND.RENDERING}[b.phase]||STATUS_KIND.BUILDING,phase:b.phase||'',el:Math.round(b.elapsed_s||0),
    last:b.last_s?Math.round(b.last_s):0,progress:statusProgress(b.progress),act:null});
  if(sy===SYNC_STATE.BLOCKED||sy===SYNC_STATE.ERROR)out.push({kind:STATUS_KIND.SYNC_BLOCKED,reason:s.sync.reason||'',act:'status-why'});
  if(s.unchanged&&!running)out.push({kind:STATUS_KIND.UNCHANGED,pull:s.unchanged.pull||'',act:s.canRebuild?'rebuild-force':null});
  if(s.stale&&!running&&!s.unchanged)out.push({kind:STATUS_KIND.STALE,act:s.canRebuild?'rebuild':null});
  if(sy===SYNC_STATE.CHECKING||sy===SYNC_STATE.DEFERRED||sy===SYNC_STATE.UPDATING||sy===SYNC_STATE.UPDATED)out.push({kind:STATUS_KIND.SYNC,state:sy,act:null});
  if(s.png)out.push({kind:STATUS_KIND.PNG,act:null});
  return out;}
// The items a band's line shows of statusList's: all of them on the compact bands; on the desktop (wide) only the messages
// and a rebuild's 'no changes' - its status chips (#bar2) already show the build, the connection, sync, staleness and PNG. Pure.
function statusShown(list,wide){return wide?list.filter(i=>i.kind===STATUS_KIND.NOTICE||i.kind===STATUS_KIND.UNCHANGED):list;}

// A filled template's text as [label, tail], cut at the template's first placeholder: the words before it (without the
// separator) are the label, the rest - the numbers - the tail. tl('쪽 {done}/{total}',{done:3,total:9}) is ['쪽', ' 3/9'].
function statusSplit(key,p){const tpl=tl(key,{}),i=tpl.indexOf('{'),head=(i<0?tpl:tpl.slice(0,i)).replace(/[\s·]+$/,''),full=tl(key,p);
  return [head,full.slice(head.length)];}

// The text of item in its long form (fit 'long') or its short one ('short'), as [label, tail]: the label is what a screen
// reader hears when the item appears, the tail the seconds and pages that tick (drawn aria-hidden). Only tr/tl beyond itself.
function statusText(item,fit){const long=fit!=='short';
  switch(item.kind){
    case STATUS_KIND.NOTICE:{const n=item.notice; return [long&&n.desc?n.title+' · '+n.desc:n.title,''];}   // already in the UI language
    case STATUS_KIND.FAILED:return [long?tr('빌드 실패 · 이전 PDF를 보는 중'):tr('빌드 실패'),''];
    case STATUS_KIND.ERRORS:return [long?tl('LaTeX 오류 {n}건 · 새 PDF',{n:item.n}):tl('LaTeX 오류 {n}',{n:item.n}),''];
    case STATUS_KIND.OFFLINE:return [long?tr('연결 끊김 · 다시 잇는 중'):tr('연결 끊김'),''];
    case STATUS_KIND.RENDERING:if(item.progress){const pr=item.progress;
        return long?statusSplit('쪽 그리는 중 · {done}/{total}쪽',pr):statusSplit('쪽 {done}/{total}',pr);}
      // falls through: no progress field - the seconds, as for any other phase
    case STATUS_KIND.BUILDING:{const name=tr({pull:'원격 main 당겨오는 중',copy:'원고 복사 중',latex:'LaTeX 컴파일 중',render:'쪽 그리는 중'}[item.phase]||'재빌드 중').replace(/…$/,'');
      const s=tl('{s}초',{s:item.el});
      return [name,long?' · '+s+(item.last?' '+tl('(지난번 {s}초)',{s:item.last}):''):' '+s];}
    case STATUS_KIND.SYNC_BLOCKED:return [long?tl('main 동기화 확인 필요 · {reason}',{reason:tr(SYNC_REASON[item.reason]||item.reason||'')}):tr('main 동기화 막힘'),''];
    case STATUS_KIND.UNCHANGED:return [tr('변경 없음')+(long?item.pull||'':''),''];
    case STATUS_KIND.STALE:return [long?tr('원고가 PDF보다 새롭습니다'):tr('원고 수정됨'),''];
    case STATUS_KIND.SYNC:return [tr(item.state===SYNC_STATE.UPDATING?'최신 main PDF 반영 중':item.state===SYNC_STATE.UPDATED?'최신 main 반영됨':
      item.state===SYNC_STATE.DEFERRED?'빌드 뒤 main 확인':'main 확인 중'),''];
    case STATUS_KIND.PNG:return [long?tr('PNG로 보는 중 · 확대하면 흐릴 수 있습니다'):tr('PNG로 보는 중'),''];
  }
  return ['',''];}

// The leading mark of an item: a message's own (by its kind, notices.js noticeIcon), a warning triangle for a failure or
// blocked sync, the lost-connection icon, a spinner while work runs (a check once main sync is applied), an 8px warning dot
// for a stale PDF, the image icon for PNG.
function statusIcon(item){const K=STATUS_KIND;
  if(item.kind===K.NOTICE)return html`<span class="st-ic nk-${item.notice.kind}">${noticeIcon(item.notice.kind)}</span>`;
  if(item.kind===K.FAILED||item.kind===K.ERRORS||item.kind===K.SYNC_BLOCKED)return html`<span class="st-ic warn">${ic('triangle-alert')}</span>`;
  if(item.kind===K.OFFLINE)return html`<span class="st-ic">${ic('wifi-off')}</span>`;
  if(item.kind===K.STALE)return html`<span class="st-ic"><i class="st-stale"></i></span>`;
  if(item.kind===K.PNG)return html`<span class="st-ic">${ic('image')}</span>`;
  if(item.kind===K.UNCHANGED||item.kind===K.SYNC&&item.state===SYNC_STATE.UPDATED)return html`<span class="st-ic">${ic('check')}</span>`;
  return html`<span class="st-ic"><i class="spin"></i></span>`;}

// An item's one action as a button (its data-act; [재빌드] is the line's one primary fill), or '' without one. [그래도 빌드]
// carries 0.4.5's tip on what a cold build is for, [이유] the reason itself (statusWhy). A message brings its own action and
// [x] (noticeButtons). The label is a span (.lbl) so CSS can trim it to its cap height.
function statusAct(item){if(!item.act)return html``; if(item.kind===STATUS_KIND.NOTICE)return noticeButtons(item.notice,true);
  const force=item.act==='rebuild-force',why=item.act==='status-why',name=item.act==='rebuild'?tr('재빌드'):why?tr('이유'):force?tr(T.buildanyway):tr('보기');
  const tip=force?html` data-tip="${T.buildanywaytip}"`:why?html` data-tip="${syncWhyText(STATUS_SYNC)}"`:'';
  return html`<button class="btn-sm st-act ${item.act==='rebuild'?'btn-default':'btn-secondary'}" data-act="${item.act}"${tip}><span class="lbl">${name}</span></button>`;}

// What the status line is drawn from, gathered from the shell: its messages (LINE), the running build (BUILD.cur) and the last
// failed one, the light poll's failures, the last meta `sync`, and the chips that already say stale and PNG - plus whether
// this document and person may rebuild.
function statusInput(){return {notices:LINE,build:BUILD.cur,buildErr:BUILD.error,offline:POLL_FAILS>=2,sync:STATUS_SYNC,stale:!$('#meta-stale').hidden,
  png:!$('#vec-chip').hidden,canRebuild:!!META&&buildsFromSource(META.kind)&&!isViewer(),unchanged:BUILD.unchanged};}

// The answer to this tab's rebuild that kept the pages (0.4.5: ok, unchanged, the same seq), with [그래도 빌드] for a cold
// build: the status line says it on every band - the desktop's line under its chips too - for STATUS_TRANSIENT_MS, then shows
// what it showed before; a build that starts, a document switch or [그래도 빌드] ends it sooner.
function buildUnchanged(b){
  const mark={pull:pullSuffix(b)}; BUILD.unchanged=mark; drawStatus();
  setTimeout(()=>{if(BUILD.unchanged!==mark)return; BUILD.unchanged=null; drawStatus();},STATUS_TRANSIENT_MS);}

// Draws the status line from statusInput() - the items the band shows (statusShown): the first item with its icon, its text
// (the long form, the short one where the long does not fit and always in the short band's top row, then an ellipsis), '+N' for
// the rest and its action (a message's and its [x]), and a 2px progress bar while a build runs - counted
// when the build gives its progress, else one that does not know its end, all in .st-body, drawn again when the item, its
// action or the count changes. The spoken label is a separate live node (.st-sr) that stays: every draw puts the item's label
// there, and its text changes - and is read out - only when the label does, never for a redraw or the ticking numbers; an
// alert (an error message, a warning whose banner had no place on screen, a failed build, a lost connection) is left out
// there, as it was read out assertively when it came (lineNote, showBuildErr, pollLightOnce). A message whose button has the
// keyboard focus keeps the line while the focus is on it, and a redraw puts the focus back on that button (statusFocus): a
// new message never takes it from a [되돌리기] that is still there. Also the [⋯] row [PDF 재빌드]: off with '빌드 중' while a
// build runs. body.has-status says a line is up (the sheet joins it).
function drawStatus(){const box=$('#status'),sr=box.querySelector('.st-sr'),body=box.querySelector('.st-body'),running=!!BUILD.cur;
  const f=statusFocus(); let list=statusShown(statusList(statusInput()),LAYOUT===LAYOUT_MODE.WIDE);
  const held=f&&f.n?list.findIndex(i=>!!i.notice&&String(i.notice.n)===f.n):-1;
  if(held>0)list=[list[held],...list.slice(0,held),...list.slice(held+1)];
  const top=list[0]; STATUS_TOP=top&&top.notice?top.notice.n:0;
  const m=$('#m-rebuild'); if(m){m.disabled=running; const tail=m.querySelector('.m-tail'); if(tail)tail.hidden=!running;}
  document.body.classList.toggle('has-status',!!top); box.hidden=!top;
  if($('#status-list').open)drawStatusList(list);
  if(!top){if(STATUS_SIG){body.replaceChildren(); STATUS_SIG='';} sr.textContent=''; lineVisible(false); return;}   // hidden: it holds nothing
  const sig=top.kind+'|'+(top.act||'')+'|'+list.length+'|'+(top.state||'')+'|'+(top.notice?top.notice.n:'');
  if(sig!==STATUS_SIG){STATUS_SIG=sig;
    const more=list.length>1?html`<button class="btn-sm btn-ghost st-more" data-act="status-more" aria-haspopup="dialog" aria-label="${tl('상태 {n}건 더 보기',{n:list.length-1})}"><span class="lbl">${tl('+{n}',{n:list.length-1})}</span></button>`:'';
    const bar=running?html`<span class="st-bar" role="progressbar" aria-label="${tr('빌드 진행')}"><i></i></span>`:'';
    setHtml(body,html`${statusIcon(top)}<span class="st-tx" aria-hidden="true"></span>${more}${statusAct(top)}${bar}`);}
  const tx=box.querySelector('.st-tx'),long=statusText(top,'long'),short=statusText(top,'short');
  tx.textContent=BAND===LAYOUT_BAND.SHORT?short[0]+short[1]:long[0]+long[1];   // the short band's one row always takes the short text
  if(tx.scrollWidth>tx.clientWidth)tx.textContent=short[0]+short[1];
  const said=top.notice?top.notice.alert:top.kind===STATUS_KIND.FAILED||top.kind===STATUS_KIND.ERRORS||top.kind===STATUS_KIND.OFFLINE;
  const say=said?'':long[0]; if(sr.textContent!==say)sr.textContent=say;
  refocusStatus(f);
  const bar=box.querySelector('.st-bar'); if(!bar)return; const {done,total}=top.progress||{},pct=top.progress?Math.round(done/total*100):null;
  bar.classList.toggle('indet',pct===null); bar.querySelector('i').style.width=pct===null?'':pct+'%';
  if(pct===null){bar.removeAttribute('aria-valuenow');} else{bar.setAttribute('aria-valuemin','0'); bar.setAttribute('aria-valuemax','100'); bar.setAttribute('aria-valuenow',String(pct));}}

// The button of the line or its '+N' list that has the keyboard focus, as its data-act and data-n ('' for an item's own
// action), or null: the line's redraw gives the focus back to it (refocusStatus).
/** @returns {{act:string,n:string}|null} */
function statusFocus(){const a=/** @type {HTMLElement|null} */(document.activeElement);
  return a&&a.closest&&a.closest('#status,#status-list')&&a.dataset.act?{act:a.dataset.act,n:a.dataset.n||''}:null;}
// Puts the focus back on the button f named (statusFocus) when a redraw replaced it: in the open '+N' list, else on the line.
/** @param {{act:string,n:string}|null} f */
function refocusStatus(f){if(!f)return; const a=document.activeElement; if(a&&a!==document.body&&document.contains(a))return;
  const sel='[data-act="'+f.act+'"]'+(f.n?'[data-n="'+f.n+'"]':''),l=$('#status-list');
  const b=/** @type {HTMLElement|null} */((l.open&&l.querySelector(sel))||$('#status').querySelector(sel)); if(b)b.focus({preventScroll:true});}
// The line follows the focus: when it leaves a message's button, the line shows again what comes first.
$('#status').addEventListener('focusout',()=>setTimeout(()=>{if(!statusFocus())drawStatus();},0));
// The '+N' list: every item as a 44px row with its long text and its action. A modal dialog over the line, so an outside tap,
// Esc and the back gesture fold it like the sheets; a row's action folds it too. While it is open the line's undo windows
// wait (notices.js lineHeld).
function drawStatusList(list){setHtml($('#status-list-rows'),html`${list.map(it=>{const t=statusText(it,'long');
  return html`<div class="st-row">${statusIcon(it)}<span class="st-row-t" translate="no">${t[0]+t[1]}</span>${statusAct(it)}</div>`;})}`);}
// The sentence [이유] of blocked main sync explains: main sync is blocked, why (SYNC_REASON), and that the previous PDF may be
// showing. Only tr/tl beyond its argument.
/** @param {SyncStatus|null} s */
function syncWhyText(s){const r=s&&s.reason||''; return tr('main 동기화 막힘')+' — '+tr(SYNC_REASON[r]||r)+' · '+tr('기존 PDF가 보일 수 있습니다');}
// [이유] of blocked main sync: its sentence (syncWhyText, also the button's description) shown right at the button - or,
// pressed in the '+N' list, which has just folded, at the line - and read out.
/** @param {HTMLElement} btn */
function statusWhy(btn){const text=syncWhyText(STATUS_SYNC); showTipText(btn.getClientRects().length?btn:$('#status'),text); announce(text);}
// Opens the '+N' list just over the status line (under it in the short band's top row), or folds it on a second press.
function toggleStatusList(){const d=$('#status-list'); if(d.open){d.close(); return;}
  drawStatusList(statusShown(statusList(statusInput()),LAYOUT===LAYOUT_MODE.WIDE)); const r=$('#status').getBoundingClientRect(),short=BAND===LAYOUT_BAND.SHORT;
  d.style.top=short?Math.round(r.bottom+4)+'px':'auto'; d.style.bottom=short?'auto':Math.round(innerHeight-r.top+4)+'px';
  hideTip(); d.showModal(); holdLine();}

// Moves #status to the band's place - the dock over the sheet (phone, tablet sheet), the short band's top row after the view
// switch, the mid action row's middle, the desktop's line under its status chips (#status-wide) - keeping a focus that was
// inside it, then draws it. An open '+N' list folds: it was placed for the old band.
function placeStatus(){const s=$('#status'),a=/** @type {HTMLElement} */(document.activeElement),had=s.contains(a); if($('#status-list').open)$('#status-list').close();
  lineVisible(false);   // moved out from under the pointer: no hover is left holding its windows
  if(BAND===LAYOUT_BAND.SHORT){if(s.previousElementSibling!==$('#view-switch'))$('#view-switch').after(s);}
  else if(LAYOUT===LAYOUT_MODE.MID){if(s.parentNode!==$('#status-slot'))$('#status-slot').appendChild(s);}
  else if(LAYOUT===LAYOUT_MODE.WIDE){if(s.parentNode!==$('#status-wide'))$('#status-wide').appendChild(s);}
  else if(s.parentNode!==$('#status-dock'))$('#status-dock').appendChild(s);
  if(had&&a.focus)a.focus({preventScroll:true});
  STATUS_SIG=''; drawStatus();}
new MutationObserver(()=>drawStatus()).observe($('#bar2'),{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['hidden']});
// The dock sits on the sheet's top edge: the sheet's height (with the keyboard's --kb under it) is its bottom.
if(window.ResizeObserver)new ResizeObserver(()=>{document.documentElement.style.setProperty('--sheet-h',Math.round($('#right').getBoundingClientRect().height)+'px');}).observe($('#right'),{box:'border-box'});
