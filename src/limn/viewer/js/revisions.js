// One changes-view visit owns the selected commit, source text and request sequence. overlay is a figure document's two
// builds from /api/revisions (null for any other document), side the one its overlay shows, history whether it has commits.
// Issue #188: base is a range's old side ('' for one commit against its first parent); rows the loaded commits (newest
// first, REVISION_PAGE a page) of rowsDoc, more whether older ones remain; range the quick range and its ends (RevRange);
// seen this browser's last-seen commit of the document, seenState what the server said of it (SEEN_STATE), seenN how many
// commits it compares with the newest and seenIds which (the server's count, never the list's positions); rangeIds the
// commits the shown range compares (the server's commit_ids; null until it answers), rangeBase its old side; listOpen
// whether the phone shows every loaded row; rangeLine the range's summary for the status line.
const REV={seq:0,files:/** @type {{name:string,text:string}[]} */([]),whole:'',commit:'',sourceCommit:'',format:/** @type {string} */(DIFF_FORMAT.PDF),scope:/** @type {any} */(null),other:'',target:/** @type {RevTarget|null} */(null),pdfCommit:'',back:/** @type {string|null} */(null),
  overlay:/** @type {RevisionOverlay|null} */(null),side:/** @type {string} */(OVERLAY_SIDE.CUR),history:false,
  base:'',rows:/** @type {RevisionRow[]} */([]),rowsDoc:'',more:false,range:/** @type {RevRange} */({mode:RANGE_MODE.ONE,start:'',end:'',endSet:false}),
  seen:/** @type {RevSeen|null} */(null),seenState:/** @type {string} */(SEEN_STATE.NONE),seenN:0,seenIds:/** @type {Set<string>} */(new Set()),
  rangeIds:/** @type {string[]|null} */(null),rangeBase:'',listOpen:false,rangeLine:''};
const REVISION_PAGE=30;   // rows of one /api/revisions page (the server's history window is 500, api.md)
const REVISION_RECENT=12;   // the commits [변경 보기] picks a pin's commit among - the server resolves a close_ref among the same
const REVISION_PHONE_ROWS=5;   // rows the phone's list shows before [더 보기]
// v0.3 (docs/handbook/viewer.md §변경 보기): a pin's view of a commit. REV.scope is the source diff's scope object
// ({mode:'pin'|'commit', source, hunks, other, ...}); REV_PDF holds the comparison PDF's toggle - whole commit or only this pin.
const REV_SCOPE={whole:false,partial:false,fallback:false};
const REV_PDF={doc:/** @type {any} */(null),loading:/** @type {any} */(null),observer:/** @type {IntersectionObserver|null} */(null),tasks:new Set()};
function revisionFiles(patch){
  const starts=[];const re=/^diff --git .+$/gm;let m;
  while((m=re.exec(patch))!==null)starts.push({at:m.index,head:m[0]});
  return starts.map((s,i)=>{const n=s.head.lastIndexOf(' b/');return {
    name:n>=0?s.head.slice(n+3):tl('파일 {n}',{n:i+1}),text:patch.slice(s.at,i+1<starts.length?starts[i+1].at:undefined)};});
}
// A patch as Html of numbered lines (file, hunk, add, del, context, meta). The code itself is the manuscript's text, so
// it is translate="no"; the lines are text.
function renderRevisionDiff(patch){
  const lines=String(patch||'').split('\n'); if(lines[lines.length-1]==='')lines.pop();
  let oldLine=/** @type {number|null} */(null),newLine=/** @type {number|null} */(null),inHunk=false;
  return html`${lines.map(line=>{
    let kind='meta',number=/** @type {number|string} */('');
    if(line.startsWith('diff --git ')){kind='file';inHunk=false;oldLine=newLine=null;}
    else if(line.startsWith('@@ ')){
      kind='hunk';inHunk=true;
      const at=/^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);
      oldLine=at?Number(at[1]):null;newLine=at?Number(at[2]):null;
    }
    else if(!inHunk&&(line.startsWith('--- ')||line.startsWith('+++ '))){kind='meta';}
    else if(line.startsWith('+')){kind='add';if(newLine!==null)number=newLine++;}
    else if(line.startsWith('-')){kind='del';if(oldLine!==null)number=oldLine++;}
    else if(line.startsWith(' ')){kind='context';if(newLine!==null){number=newLine++; if(oldLine!==null)oldLine++;}}
    return html`<span class="rd-line rd-${kind}"><span class="rd-no" aria-hidden="true">${number}</span><span class="rd-code" translate="no">${line}</span></span>`;
  })}`;
}
function renderRevisionFile(){const v=$('#revision-file').value,i=Number(v);
  setHtml($('#revision-diff'),renderRevisionDiff(v==='all'?REV.whole:(REV.files[i]&&REV.files[i].text)||REV.whole));}
// The rest of the commit, folded under one control (v0.3). Hidden when the pin owns the whole commit or the view is not a pin's.
function drawRevisionOther(sc){const b=$('#revision-other-toggle'),o=$('#revision-other');
  o.hidden=true;o.replaceChildren();b.setAttribute('aria-expanded','false');
  REV.other=sc&&sc.mode===SCOPE_MODE.PIN?String(sc.other_diff||'')+(sc.other_truncated?'\n\n'+tr('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.'):''):'';
  b.hidden=!REV.other;if(REV.other)b.querySelector('span').textContent=tl('이 커밋의 다른 변경 {n}곳',{n:sc.other});}
function toggleRevisionOther(){const b=$('#revision-other-toggle'),o=$('#revision-other'),open=b.getAttribute('aria-expanded')!=='true';
  b.setAttribute('aria-expanded',String(open));o.hidden=!open;
  if(open&&!o.firstChild)setHtml(o,renderRevisionDiff(REV.other));}
// [커밋 전체 비교]: shown only for the PDF of a pin that owns part of the commit, and not after a fallback (there is nothing to switch to).
function syncRevisionWhole(){const b=$('#revision-whole');
  b.hidden=!(REV.format===DIFF_FORMAT.PDF&&revisionPinFor(REV.commit)&&REV_SCOPE.partial&&!REV_SCOPE.fallback);
  b.setAttribute('aria-pressed',String(REV_SCOPE.whole));}
// The pin whose hunks a commit's view is scoped to: only the commit picked for the pin ([변경 보기]); any other commit
// chosen in the list is shown whole (review M1 - another commit's lines are not this pin's), and so is a range (#188:
// pin scoping and ranges do not combine yet; the server refuses pin with base).
function revisionPinFor(id){const tg=REV.target; return tg&&!tg.region&&tg.commit&&id===tg.commit&&!REV.base?tg:null;}
function setRevisionWhole(on){REV_SCOPE.whole=!!on;++REV.seq;REV.pdfCommit='';
  clearRevisionPdf();$('#revision-warning').hidden=true;setRevisionFormat(DIFF_FORMAT.PDF);}
function revisionCurrent(seq,k,id){return seq===REV.seq&&k===DOC&&id===REV.commit&&document.body.classList.contains('revision-open');}
/** Release comparison rendering and PDF.js resources on visit or scope change. */
function clearRevisionPdf(){
  disposeRevisionZoom();
  if(REV_PDF.observer){REV_PDF.observer.disconnect();REV_PDF.observer=null;}
  REV_PDF.tasks.forEach(t=>{try{t.cancel();}catch(e){}});REV_PDF.tasks.clear();
  if(REV_PDF.loading){try{void REV_PDF.loading.destroy().catch(()=>{});}catch(e){}REV_PDF.loading=null;}
  REV_PDF.doc=null;$('#revision-pdf').replaceChildren();
}
// The format a document's changes show for the one asked (docs/handbook/viewer.md §변경 보기): the source diff when asked;
// otherwise a figure document's overlay of two builds, and a LaTeX document's comparison PDF - never the overlay. Pure.
function revisionFormatFor(asked,figure){return asked===DIFF_FORMAT.SOURCE?DIFF_FORMAT.SOURCE:figure?DIFF_FORMAT.OVERLAY:DIFF_FORMAT.PDF;}
// Shows REV.format: the pressed tab, the pane, [이전 | 지금] with the overlay, and the overlay's status line on a figure
// document (its source diff has none). Loads nothing.
function drawRevisionFormat(){
  $('#revision-pdf-tab').setAttribute('aria-pressed',String(REV.format===DIFF_FORMAT.PDF));
  $('#revision-overlay-tab').setAttribute('aria-pressed',String(REV.format===DIFF_FORMAT.OVERLAY));
  $('#revision-source-tab').setAttribute('aria-pressed',String(REV.format===DIFF_FORMAT.SOURCE));
  $('#revision-view').dataset.format=REV.format;
  $('#revision-pdf').hidden=REV.format!==DIFF_FORMAT.PDF;$('#revision-source').hidden=REV.format!==DIFF_FORMAT.SOURCE;
  $('#revision-overlay').hidden=$('#revision-side').hidden=REV.format!==DIFF_FORMAT.OVERLAY;
  if(REV.overlay)$('#revision-status').textContent=REV.format===DIFF_FORMAT.OVERLAY?overlayStatus(REV.overlay):'';}
/** Switch formats while retaining comparison scale for the selected commit. */
function setRevisionFormat(format){REV.format=revisionFormatFor(format,!!REV.overlay); drawRevisionFormat();
  if(REV.format===DIFF_FORMAT.SOURCE&&REV.commit&&REV.sourceCommit!==revKey())
    loadRevisionSource(REV.commit,REV.seq,DOC);
  if(REV.format===DIFF_FORMAT.SOURCE&&REV.base&&REV.sourceCommit===revKey())$('#revision-status').textContent=REV.rangeLine;
  // The comparison PDF is only built when that format is actually viewed - [변경 보기] and a range go straight to the source diff, so neither wastes a latexdiff build.
  if(REV.format===DIFF_FORMAT.PDF&&REV.commit&&REV.pdfCommit!==revKey()){REV.pdfCommit=revKey();
    $('#revision-status').textContent='비교 PDF 상태를 확인하는 중입니다.'; loadRevisionPdf(REV.commit,REV.seq,DOC);}
  syncRevisionWhole();drawRevisionZoom();
  if(revisionPdfActive())resizeRevisionPdf();
  if(REV.format===DIFF_FORMAT.OVERLAY&&REV.target)scrollOverlayTo(REV.target.page);
  if(REV.target)revTargetNote();
}
// Shows the manuscript or the changes view: the nav bar's tabs, the navigation sheet's switch and the phone's position button
// ([변경사항 ▾] in the changes view) follow; leaving the changes view forgets the pin it was opened for and redraws the pages.
// The mark badges' press areas are measured again as the pages show (markHitSides: marks drawn meanwhile had no boxes).
function setViewMode(mode){
  const revisions=mode===VIEW_MODE.REVISIONS; if(!revisions&&document.body.classList.contains('revision-open'))leaveRevisions();
  document.body.classList.toggle('revision-open',revisions);
  $('#view-manuscript').setAttribute('aria-pressed',String(!revisions));
  $('#view-revisions').setAttribute('aria-pressed',String(revisions));
  if(!revisions)REV.target=null;
  if(revisions)loadRevisions(); else{++REV.seq;clearRevisionPdf();setRevisionOverlay(null);$('#revision-pin').hidden=true;revTargetActs();if(VEC.doc)vecSchedule(0);updateSectionStrip();markHitSides();}
  drawNavView(); drawPos();
}
// Reads the document's recent commits into the changes view. Without history (not Git, a view-only PDF, or no recent commit) the
// one reason line stays and the unusable [변경 PDF] [소스 diff] and the comparison note are hidden; a pin's guide line stays.
// A figure document's answer carries its two builds (overlay): its [겹쳐 보기] takes the place of [변경 PDF] and opens first,
// with or without history; its [소스 diff] shows only with history.
async function loadRevisions(){
  const seq=++REV.seq,k=DOC,list=$('#revision-list'),out=$('#revision-diff'),tg=REV.target,again=!tg&&REV.rowsDoc===k&&REV.rows.length>0;
  clearRevisionPdf();list.hidden=false;list.textContent='최근 변경사항을 읽는 중입니다.';out.textContent='';$('#revision-pin').hidden=!tg;
  if(tg)revTargetNote('변경사항을 읽는 중입니다.'); else revTargetActs();
  let data; try{data=(await api(dq('/api/revisions?limit='+REVISION_PAGE,k),{what:'변경사항 읽기',silent:true})).data;}
  catch(e){if(seq===REV.seq)list.textContent='변경사항을 읽지 못했습니다.';return;}
  if(seq!==REV.seq||k!==DOC)return;
  const rows=/** @type {RevisionRow[]} */(data.available?data.revisions:[]),kept=REV.range;
  REV.rows=rows; REV.rowsDoc=k||''; REV.more=!!data.more; if(!again)REV.listOpen=false;
  if(!again||!REV.seen||REV.seenState!==SEEN_STATE.OK)openSeen(revSeen(k||''),rows);
  REV.history=!!data.available&&rows.length>0; setRevisionOverlay(data.overlay||null);
  const fig=!!REV.overlay; REV.format=revisionFormatFor(REV.format,fig); drawRevisionFormat();   // a LaTeX document after a figure leaves the overlay
  $('#revision-controls').hidden=!REV.history&&!fig; $('#revision-note').hidden=!REV.history;
  $('#revision-pdf-tab').hidden=fig; $('#revision-overlay-tab').hidden=!fig; $('#revision-source-tab').hidden=!REV.history;
  if(!data.available){list.textContent='이 문서의 Git 변경사항을 볼 수 없습니다.'; drawRange();
    if(fig){setRevisionFormat(DIFF_FORMAT.OVERLAY);return;}
    if(tg)revTargetNote(tg.region?'보기 전용 PDF 문서의 핀이라 Git 변경사항이 없습니다 — 고친 곳은 LaTeX 문서(본문 등)의 변경사항에서 찾으세요.':
      '이 문서는 Git 이력을 읽을 수 없어(Git 저장소가 아니거나 경로가 밖) 핀 자리를 변경과 맞출 수 없습니다.'); return;}
  if(!rows.length){list.textContent='이 문서의 최근 변경사항이 없습니다.'; drawRange();
    if(fig)setRevisionFormat(DIFF_FORMAT.OVERLAY); else if(tg)revTargetNote('이 문서의 최근 12개 커밋에 변경이 없습니다.'); return;}
  list.hidden=true; list.textContent='';
  // A pin's commit is picked by the server's rule over the same window (api.md §두 커밋 사이): a hash anywhere in it, a PR
  // number or the lines in its first rows.
  if(tg){if(REV.seenState===SEEN_STATE.PENDING)resolveSeen(k||'',rows[0].id);
    const pick=await pickRevisionFor(tg,seq,k); if(seq!==REV.seq||k!==DOC||REV.target!==tg)return;
    tg.commit=pick.id; tg.via=pick.via; tg.hit=pick.hit; REV.range={mode:RANGE_MODE.ONE,start:pick.id,end:pick.id,endSet:false};
    // a figure's lines and pictures are both exact: its overlay opens first; a LaTeX pin's lines exist only in the source diff
    if(fig)showRevision(pick.id,DIFF_FORMAT.OVERLAY); else showRevision(pick.id,DIFF_FORMAT.SOURCE); drawRange(); return;}
  // The same document read again while the view is open (a new build) keeps the range shown, moved to the newest commit;
  // a range comes back in its source diff, so a new build never starts its comparison PDF (only [변경 PDF] does).
  if(again&&rows.some(r=>r.id===kept.start)){if(REV.seenState===SEEN_STATE.OK&&kept.mode!==RANGE_MODE.LAST)resolveSeen(k||'',rows[0].id);
    showRange(kept.mode===RANGE_MODE.ONE?kept:{...kept,end:kept.endSet?kept.end:rows[0].id},REV.format);return;}
  if(REV.seenState===SEEN_STATE.PENDING&&!fig){showRange(rangeMode(rows,REV.range,RANGE_MODE.LAST,REV.seen));return;}
  if(REV.seenState===SEEN_STATE.PENDING)resolveSeen(k||'',rows[0].id);
  const id=rows.some(r=>r.id===REV.commit)?REV.commit:rows[0].id;
  REV.range={mode:RANGE_MODE.ONE,start:id,end:id,endSet:false};
  showRevision(id,fig?DIFF_FORMAT.OVERLAY:undefined); drawRange();
}
// ------------------------------------------------ Comparing two commits (issue #188, docs/handbook/viewer.md §변경 보기)
// The quick range [마지막으로 본 뒤 N | 이 커밋부터 | 이 커밋만] (#revision-range) and the commit list that stays on screen
// (#revision-commits). The rules below are pure functions of the loaded rows (newest first); showRange() shows their request.
// What is painted and counted comes from the server's range answer (commit_ids, commits): a range follows ancestry, which the
// list's positions do not show (a merged line, a base on another line, a pull that merged older commits).

/** The range after a row press (id): in [이 커밋만] that commit alone; otherwise that commit to the newest - except that, right
 * after such a press, a newer row ends the range there, and the start pressed again is that commit alone. Pure.
 * @param {{id:string}[]} rows @param {RevRange} rg @param {string} id @returns {RevRange} */
function rangePress(rows,rg,id){const at=x=>rows.findIndex(r=>r.id===x),newest=rows.length?rows[0].id:id;
  if(rg.mode===RANGE_MODE.ONE)return {mode:RANGE_MODE.ONE,start:id,end:id,endSet:false};
  if(rg.mode===RANGE_MODE.FROM&&id===rg.start)return {mode:RANGE_MODE.FROM,start:id,end:id,endSet:true};
  if(rg.mode===RANGE_MODE.FROM&&!rg.endSet&&at(id)>=0&&at(id)<at(rg.start))return {mode:RANGE_MODE.FROM,start:rg.start,end:id,endSet:true};
  return {mode:RANGE_MODE.FROM,start:id,end:newest,endSet:false};}
/** The range after a segment press: [마지막으로 본 뒤] the last-seen commit to the newest; [이 커밋부터] the commit in focus to
 * the newest; [이 커밋만] the commit in focus alone (the newest after [마지막으로 본 뒤]). Pure.
 * @param {{id:string}[]} rows @param {RevRange} rg @param {string} mode @param {RevSeen|null} seen @returns {RevRange} */
function rangeMode(rows,rg,mode,seen){const newest=rows.length?rows[0].id:rg.end;
  if(mode===RANGE_MODE.LAST)return {mode,start:newest,end:newest,endSet:false};
  const focus=rg.mode===RANGE_MODE.LAST&&mode===RANGE_MODE.ONE?rg.end:rg.start;
  return {mode,start:focus,end:mode===RANGE_MODE.FROM?newest:focus,endSet:false};}
/** What a range asks the server: {commit, base}, base '' for one commit against its first parent. [마지막으로 본 뒤] compares
 * the last-seen commit with the newest; [이 커밋부터] the start's first parent with the end - a start that is the end, or a
 * root commit (no parent), is that commit alone. Pure. @param {{id:string,parents:string[]}[]} rows @param {RevRange} rg
 * @param {RevSeen|null} seen @returns {{commit:string,base:string}} */
function rangeRequest(rows,rg,seen){
  if(rg.mode===RANGE_MODE.LAST&&seen)return {commit:rg.end,base:seen.id};
  if(rg.mode!==RANGE_MODE.FROM||rg.start===rg.end)return {commit:rg.start,base:''};
  const s=rows.find(r=>r.id===rg.start);
  return s&&s.parents.length?{commit:rg.end,base:s.parents[0]}:{commit:rg.start,base:''};}
/** The commits the list paints for request req: one commit itself; a range the commits the server's answer names (ids,
 * its commit_ids), none while that answer is unknown. Pure. @param {{commit:string,base:string}} req
 * @param {string[]|null} ids @returns {string[]} */
function paintedIds(req,ids){return req.base?(ids||[]).slice():[req.commit];}
/** The rows of merged lines: those between a merge and its first parent, when that parent is loaded. Pages come in ancestry
 * order (the server's --topo-order), so a merged line's commits sit right below their merge; a merge whose first parent is
 * not loaded marks nothing. Pure. @param {{id:string,parents:string[]}[]} rows @returns {Set<string>} */
function sideRows(rows){const out=new Set();
  rows.forEach((r,i)=>{if(r.parents.length<2)return; const j=rows.findIndex(x=>x.id===r.parents[0]); for(let k=i+1;k<j;k++)out.add(rows[k].id);});
  return out;}
// The key a source diff or comparison PDF was loaded for: the commit, or base..commit for a range.
function revKey(){return REV.base?REV.base+'..'+REV.commit:REV.commit;}
// Shows range rg: opens what it asks, then draws the picker - a range always in its source diff (its comparison PDF is built
// only when [변경 PDF] is pressed, whatever format was shown), one commit as a list choice always opened (format undefined:
// the comparison PDF of a LaTeX document, the format shown of a figure document).
/** @param {RevRange} rg @param {string} [format] */
function showRange(rg,format){REV.range=rg; const q=rangeRequest(REV.rows,rg,REV.seen);
  showRevision(q.commit,q.base?format===DIFF_FORMAT.OVERLAY?format:DIFF_FORMAT.SOURCE:format,q.base); drawRange();}
// A row of the list pressed (rangePress) and a quick-range segment pressed (rangeMode).
function pressRevisionRow(id){if(id)showRange(rangePress(REV.rows,REV.range,id));}
function setRevisionRange(mode){if(!REV.rows.length||mode===REV.range.mode)return; showRange(rangeMode(REV.rows,REV.range,mode,REV.seen));}
// Draws the quick range: the pressed segment, and [마지막으로 본 뒤 N] - hidden without a record of this document in this
// browser; N is the server's count ('…' while it is asked); not pressable when nothing is new (N = 0) or the record could not
// be read; a record the history no longer has says so (SEEN_STATE.GONE). Then the list.
function drawRange(){const rows=REV.rows,rg=REV.range,st=REV.seenState;
  $('#revision-range').hidden=!rows.length;
  for(const b of /** @type {HTMLButtonElement[]} */($$('#revision-range [role=radio]'))){const on=b.dataset.range===rg.mode;
    b.setAttribute('aria-checked',String(on)); b.classList.toggle('on',on);
    if(b.dataset.range!==RANGE_MODE.LAST)continue;
    const lbl=b.querySelector('.lbl'),k=b.querySelector('.k');
    b.hidden=st===SEEN_STATE.NONE; b.disabled=st!==SEEN_STATE.OK&&st!==SEEN_STATE.PENDING||st===SEEN_STATE.OK&&REV.seenN===0;
    if(lbl)lbl.textContent=tr(st===SEEN_STATE.GONE?'기록한 커밋을 찾을 수 없음':st===SEEN_STATE.OLD?'기록한 커밋이 최근 500개보다 오래됨':'마지막으로 본 뒤');
    if(k)k.textContent=st===SEEN_STATE.OK?String(REV.seenN):st===SEEN_STATE.PENDING?'…':'';}
  renderCommitList();}
// A commit's time as the list shows it: MM-DD HH:MM of its ISO commit time (the committer's own clock), else its date.
/** @param {RevisionRow} r */
function rowWhen(r){const t=String(r.time||'');return /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(t)?t.slice(5,10)+' '+t.slice(11,16):String(r.date||'');}
// The commit list (#revision-commits): a row per loaded commit with its subject, author, time and short hash; a merged line's
// rows indented under their merge (sideRows). The commits the shown comparison covers (paintedIds - the server's, never the
// rows' positions) ride the rail, the first and last of them bold, its old side (left out) a hollow dot; the commits the
// server counts since the last-seen one are marked new, with a line above the last-seen row saying where reading stopped.
// The phone shows REVISION_PHONE_ROWS rows until [더 보기]; [더 보기] then reads the next page while the server has more.
function renderCommitList(){const box=$('#revision-commits'),rows=REV.rows,seen=REV.seen;
  box.hidden=!rows.length; if(!rows.length){box.replaceChildren();return;}
  const focused=/** @type {HTMLElement|null} */(document.activeElement),refocus=focused&&focused.classList.contains('rc-row')?focused.dataset.commit:null;
  const inside=new Set(paintedIds({commit:REV.commit,base:REV.base},REV.rangeIds)),side=sideRows(rows),fresh=REV.seenState===SEEN_STATE.OK?REV.seenIds:new Set();
  const order=rows.filter(r=>inside.has(r.id)).map(r=>r.id),ends=new Set([order[0],order[order.length-1]]),base=REV.base?REV.rangeBase||REV.base:'';
  const seenAt=REV.seenState===SEEN_STATE.OK&&seen?rows.findIndex(r=>r.id===seen.id):-1;
  const cut=LAYOUT===LAYOUT_MODE.NARROW&&!REV.listOpen?Math.min(REVISION_PHONE_ROWS,rows.length):rows.length;
  const items=rows.map((r,i)=>{const cls=['rc-row'];
    if(inside.has(r.id))cls.push('in'); if(ends.has(r.id))cls.push('end'); if(r.parents.length>1)cls.push('merge'); if(side.has(r.id))cls.push('side');
    if(r.id===base)cls.push('base'); if(fresh.has(r.id))cls.push('new'); if(i===0)cls.push('first'); if(i===rows.length-1)cls.push('last');
    const line=i===seenAt&&i>0?html`<div class="rc-seen" data-i="${i}">${seen&&seen.at?tl('{when} 여기까지 봄',{when:seen.at}):tr('여기까지 봄')}</div>`:'';
    return html`${line}<button class="${cls.join(' ')}" data-act="revision-row" data-commit="${r.id}" data-i="${i}" aria-pressed="${inside.has(r.id)}">\
<span class="rc-rail" aria-hidden="true"><span class="rc-dot"></span></span><span class="rc-txt"><span class="rc-t" translate="no">${r.subject}</span>\
<span class="rc-m"><span translate="no">${r.author||''}</span> · ${rowWhen(r)} · <span class="rc-code" translate="no">${r.id.slice(0,7)}</span></span></span>\
${fresh.has(r.id)?html`<span class="rc-tag">새로</span>`:''}</button>`;});
  const more=cut<rows.length?tl('이전 커밋 {n}개 더 보기',{n:rows.length-cut}):REV.more?tr('이전 커밋 더 보기'):'';
  const hint=REV.range.mode===RANGE_MODE.ONE?'최신이 위 · 누르면 그 커밋 하나':'최신이 위 · 누르면 그 커밋부터 지금까지';
  setHtml(box,html`<div class="rc-head">${tr(hint)}</div><div class="rc-list">${items}</div>\
${more?html`<button id="revision-more" class="btn-ghost" data-act="revision-more">${ic('chevron-down')}<span>${more}</span></button>`:''}`);
  for(const el of /** @type {HTMLElement[]} */($$('#revision-commits [data-i]')))el.hidden=Number(el.dataset.i)>=cut;
  if(refocus){const again=/** @type {HTMLElement|null} */(box.querySelector('.rc-row[data-commit="'+refocus+'"]')); if(again)again.focus();}}
// [더 보기]: the phone's first press shows every loaded row; after that (and on a wide screen) the next page of the history.
async function moreRevisions(){
  if(LAYOUT===LAYOUT_MODE.NARROW&&!REV.listOpen&&REV.rows.length>REVISION_PHONE_ROWS){REV.listOpen=true; renderCommitList(); return;}
  if(!REV.more||!REV.rows.length)return; REV.listOpen=true;
  if(await moreRows(DOC||'',REVISION_PAGE))renderCommitList();}
// Reads the next page (up to limit rows) of document k's window onto REV.rows; whether it did. Nothing when the list is
// another document's or was replaced meanwhile.
/** @param {string} k @param {number} limit */
async function moreRows(k,limit){if(!REV.more||!REV.rows.length)return false;
  const last=REV.rows[REV.rows.length-1].id; let data;
  try{data=(await api(dq('/api/revisions?before='+encodeURIComponent(last)+'&limit='+limit,k),{what:'변경사항 읽기',silent:true})).data;}catch(e){return false;}
  if(k!==DOC||REV.rowsDoc!==k||!REV.rows.length||REV.rows[REV.rows.length-1].id!==last)return false;
  REV.rows=REV.rows.concat(data.revisions||[]); REV.more=!!data.more; return true;}
// ------------------------------------------------ The last-seen commit (docs/handbook/viewer.md §변경 보기)
// This browser's last-seen commit per document (localStorage limnRevSeen: {<doc>:{id, at}}). No server state: another
// browser or device keeps its own. The server says what it is (resolveSeen): how many commits it compares with the newest,
// or that it is no longer in the history. A record is never overwritten until the server has answered for it.
/** @returns {Record<string,RevSeen>} */
function revSeenAll(){try{const v=JSON.parse(localStorage.getItem('limnRevSeen')||'{}');return v&&typeof v==='object'?v:{};}catch(e){return {};}}
/** @param {string} k @returns {RevSeen|null} */
function revSeen(k){const v=revSeenAll()[k]; return v&&typeof v.id==='string'?{id:v.id,at:String(v.at||'')}:null;}
// Takes the document's record for this visit: none, the newest commit itself (0 new, nothing to ask), or one to ask about.
/** @param {RevSeen|null} seen @param {RevisionRow[]} rows */
function openSeen(seen,rows){REV.seen=seen; REV.seenIds=new Set(); REV.seenN=0;
  REV.seenState=!seen?SEEN_STATE.NONE:rows.length&&rows[0].id===seen.id?SEEN_STATE.OK:SEEN_STATE.PENDING;}
// The server's answer for the last-seen range (seen..newest): its count and commits, or why it has none. A refusal that says
// the commit is not in this document's history (or shares none with it) is a record the history no longer has; base_too_old
// is a record still in the history but older than the window (SEEN_STATE.OLD, kept); any other failure leaves the record
// unread, and so kept.
/** @param {any} r the /api/revision-diff answer with base */
function seenAnswered(r){REV.seenState=SEEN_STATE.OK; REV.seenN=Number(r.commits)||0; REV.seenIds=new Set(r.commit_ids||[]);}
/** @param {unknown} e */
function seenFailed(e){const d=/** @type {any} */(e&&/** @type {ApiError} */(e).data),why=d&&d.reason;
  REV.seenState=why==='base_too_old'?SEEN_STATE.OLD:why==='commit_not_recent'||why==='no_merge_base'||why==='base_after_head'?SEEN_STATE.GONE:SEEN_STATE.ERROR;}
// Asks the server about the last-seen commit when the view does not open on its range (a pin's [변경 보기], a figure's overlay).
/** @param {string} k @param {string} newest */
async function resolveSeen(k,newest){const seen=REV.seen; if(!seen)return;
  try{const r=(await api(dq('/api/revision-diff?commit='+encodeURIComponent(newest)+'&base='+encodeURIComponent(seen.id),k),{what:'변경사항 읽기',silent:true})).data;
    if(k===DOC&&REV.seen===seen)seenAnswered(r);}
  catch(e){if(k===DOC&&REV.seen===seen)seenFailed(e);}
  if(k===DOC&&REV.seen===seen)drawRange();}
// Leaving the changes view (to the manuscript, another document, or closing the page): once the server has answered for the
// record (or there was none), the document's newest loaded commit becomes its last-seen one, with this moment as MM-DD HH:MM.
// A record still being asked about, one the server could not answer for, or one older than the window (still in the
// history, so not to be lost) is kept. The list is forgotten, so coming back
// starts afresh.
function leaveRevisions(){const k=REV.rowsDoc,top=REV.rows[0]; REV.rowsDoc=''; if(!k||!top)return;
  if(REV.seenState===SEEN_STATE.PENDING||REV.seenState===SEEN_STATE.ERROR||REV.seenState===SEEN_STATE.OLD)return;
  const d=new Date(),p=n=>String(n).padStart(2,'0'),all=revSeenAll();
  all[k]={id:top.id,at:p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes())};
  try{localStorage.setItem('limnRevSeen',JSON.stringify(all));}catch(e){}}
addEventListener('pagehide',()=>{if(document.body.classList.contains('revision-open'))leaveRevisions();});
/** A newly selected commit (or range, from base) starts with fit width. Without a format a LaTeX document shows its
 * comparison PDF and a figure document stays in the format it shows (choosing a commit in its source diff keeps the source
 * diff). @param {string} id @param {string} [format] @param {string} [base] */
async function showRevision(id,format,base){
  RZ.ratio=1;
  ++REV.seq;REV.commit=id;REV.base=base||'';REV.rangeLine='';REV.rangeIds=null;REV.rangeBase='';REV.sourceCommit='';REV.pdfCommit='';clearRevisionPdf();
  $('#revision-note').textContent=REV.base?'두 커밋 사이의 누적 변경 · 이 문서의 Git 이력 · 미커밋 수정 제외':'선택 커밋의 첫 부모와 비교 · 이 문서의 Git 이력 · 미커밋 수정 제외';
  REV.scope=null;REV_SCOPE.whole=REV_SCOPE.partial=REV_SCOPE.fallback=false;drawRevisionOther(null);
  $('#revision-diff').textContent='';$('#revision-file-row').hidden=true;$('#revision-warning').hidden=true;
  $('#revision-status').textContent='';
  setRevisionFormat(format||(REV.overlay?REV.format:DIFF_FORMAT.PDF));
}
// ------------------------------------------------ A figure document's overlay (docs/handbook/viewer.md §변경 보기)
// A figure has no comparison PDF: its changes view lays the previous build's page images over the current ones, page by page in
// one box, and [이전 | 지금] (#revision-side) shows one of the two at a time. The images are the page routes' own
// (/pages/<build>/<file>); the two builds come with /api/revisions.

/** The overlay's pages: each page of the build on screen paired with the same page of the previous build, as the box that
 * holds both ({page, ratio}) and each image's name and share of that box in percent ({name, w, h}; null when that build has
 * no such page). The box is as wide and as tall as the larger of the two, and each image keeps its own size from the top
 * left, so a figure that grew or shrank is never stretched to the other. Pure.
 * @param {RevisionOverlay} ov */
function overlayPages(ov){const cur=ov.pages||[],prev=ov.prev_pages||[],out=[];
  for(let i=0;i<Math.max(cur.length,prev.length);i++){const c=cur[i],p=prev[i];
    const w=Math.max(c?c.pt_w:0,p?p.pt_w:0),h=Math.max(c?c.pt_h:0,p?p.pt_h:0);
    const share=x=>x?{name:x.name,w:Math.round(x.pt_w/w*1e4)/100,h:Math.round(x.pt_h/h*1e4)/100}:null;
    out.push({page:i+1,ratio:w+' / '+h,cur:share(c),prev:share(p)});}
  return out;}
// A build as a person reads it: a page folder name pages-<YYYYmmddHHMMSS>[-<n>] as 'MM-DD HH:MM:SS', with ' (n)' for a second
// build in the same second; any other name as it is. Pure.
function buildStamp(name){const s=String(name||''),m=/^pages-\d{4}(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:-(\d+))?$/.exec(s);
  return m?m[1]+'-'+m[2]+' '+m[3]+':'+m[4]+':'+m[5]+(m[6]?' ('+m[6]+')':''):s;}
/** The overlay's status line: which two builds it lays one over the other, or that there is no previous build.
 * @param {RevisionOverlay} ov */
function overlayStatus(ov){
  if(!ov.prev_build)return tr('이전 빌드가 없습니다 — 그림을 다시 가져오면 직전 빌드와 겹쳐 볼 수 있습니다.');
  return tl('직전 빌드 {prev} → 지금 {cur} · {n}쪽 · [이전]·[지금]으로 같은 자리를 바꿔 봅니다',
    {prev:buildStamp(ov.prev_build),cur:buildStamp(ov.build),n:Math.max(ov.pages.length,ov.prev_pages.length)});}
// Takes a document's two builds from /api/revisions (null: not a figure document) and draws them anew, the current one shown.
/** @param {RevisionOverlay|null} ov */
function setRevisionOverlay(ov){REV.overlay=ov; REV.side=OVERLAY_SIDE.CUR; renderRevisionOverlay(); drawRevisionSide();}
// Draws the overlay's pages (overlayPages) into #revision-overlay: per page a box holding the current build's image and the
// previous build's, each at its share of the box; a build without that page has a line saying so in its place.
function renderRevisionOverlay(){const ov=REV.overlay,box=$('#revision-overlay'); box.replaceChildren(); if(!ov)return;
  const side=(x,build,cls,alt,none)=>x&&build?
    html`<img class="${cls}" loading="lazy" draggable="false" alt="${alt}" src="${dq('/pages/'+encodeURIComponent(build)+'/'+encodeURIComponent(x.name))}">`:
    html`<span class="ov-none ${cls}">${none}</span>`;
  for(const pg of overlayPages(ov)){const d=document.createElement('div'); d.className='ov-page'; d.dataset.page=String(pg.page); d.style.aspectRatio=pg.ratio;
    setHtml(d,html`${side(pg.cur,ov.build,'ov-cur',tl('지금 {page}쪽',{page:pg.page}),tr('지금 빌드에 없는 쪽'))}\
${side(pg.prev,ov.prev_build,'ov-prev',tl('이전 {page}쪽',{page:pg.page}),tr('이전 빌드에 없는 쪽'))}<span class="ov-no">${pg.page}</span>`);
    for(const [sel,x] of [['img.ov-cur',pg.cur],['img.ov-prev',pg.prev]]){const img=/** @type {HTMLElement|null} */(d.querySelector(sel));
      if(img&&x){img.style.width=x.w+'%'; img.style.height=x.h+'%';}}
    box.appendChild(d);}}
// [이전 | 지금]: the side the overlay shows. [이전] cannot be pressed when there is no previous build.
function drawRevisionSide(){const ov=REV.overlay,none=!ov||!ov.prev_build;
  for(const b of /** @type {HTMLButtonElement[]} */($$('#revision-side [role=radio]'))){const on=b.dataset.side===REV.side;
    b.setAttribute('aria-checked',String(on)); b.classList.toggle('on',on); b.disabled=none&&b.dataset.side===OVERLAY_SIDE.PREV;}
  $('#revision-overlay').dataset.side=REV.side;}
// Shows the previous build's pages (side PREV, when there is one) or the current build's.
function setRevisionSide(side){REV.side=side===OVERLAY_SIDE.PREV&&REV.overlay&&REV.overlay.prev_build?OVERLAY_SIDE.PREV:OVERLAY_SIDE.CUR; drawRevisionSide();}
// Brings page n of the overlay to the top of its view, once it is laid out ([변경 보기] of a pin on that page).
function scrollOverlayTo(n){requestAnimationFrame(()=>{const box=$('#revision-overlay'),pg=box.querySelector('.ov-page[data-page="'+n+'"]');
  if(pg)box.scrollTop+=pg.getBoundingClientRect().top-box.getBoundingClientRect().top;});}
async function loadRevisionSource(id,seq,k){
  const out=$('#revision-diff');out.textContent='소스 변경 내용을 읽는 중입니다.';$('#revision-file-row').hidden=true;
  const tg0=revisionPinFor(id),base=REV.base,pq=tg0?'&pin='+tg0.id:base?'&base='+encodeURIComponent(base):'';
  try{const r=(await api(dq('/api/revision-diff?commit='+encodeURIComponent(id)+pq,k),{what:'변경 내용 읽기',silent:true})).data;
    if(!revisionCurrent(seq,k,id))return;
    if(base){REV.rangeLine=rangeSummary(r); if(REV.format===DIFF_FORMAT.SOURCE)$('#revision-status').textContent=REV.rangeLine;
      REV.rangeIds=Array.isArray(r.commit_ids)?r.commit_ids:[]; REV.rangeBase=String(r.base||'');
      if(REV.range.mode===RANGE_MODE.LAST&&REV.seen&&base===REV.seen.id)seenAnswered(r);
      drawRange();}
    // v0.3: a pin's own hunks when it owns part of the commit; otherwise the whole commit exactly as before
    const sc=r.scope&&r.scope.mode===SCOPE_MODE.PIN?r.scope:null;REV.scope=r.scope||null;
    if(sc){REV_SCOPE.partial=true;syncRevisionWhole();}
    const cut='\n\n'+tr('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.');
    REV.whole=sc?sc.diff+(sc.truncated?cut:''):(r.diff||tr(base?'이 범위에서 표시할 원고 텍스트 변경이 없습니다.':'이 커밋에서 표시할 원고 텍스트 변경이 없습니다.'))+(r.truncated?cut:'');
    REV.files=revisionFiles(sc?sc.diff:(r.diff||''));drawRevisionOther(sc);
    const select=$('#revision-file');setHtml(select,html`<option value="all">전체 파일</option>${REV.files.map((f,i)=>html`<option value="${i}">${f.name}</option>`)}`);
    select.value='all';$('#revision-file-row').hidden=REV.files.length<2;REV.sourceCommit=revKey();
    const tg=REV.target,fi=tg?pinFileIndex(REV.files,tg.file):-1;
    if(fi>=0&&REV.files.length>1)select.value=String(fi);
    renderRevisionFile(); if(tg)revHighlight(tg);
  }catch(e){if(revisionCurrent(seq,k,id)){const why=e&&/** @type {ApiError} */(e).data?errText(/** @type {ApiError} */(e).data):'';
    out.textContent=why?tl('소스 변경 내용을 읽지 못했습니다: {error}',{error:why}):tr('소스 변경 내용을 읽지 못했습니다.');
    // the last-seen range could not be compared: say why on its segment, and show the newest commit alone instead
    if(base&&REV.range.mode===RANGE_MODE.LAST&&REV.seen&&base===REV.seen.id){seenFailed(e);
      if((REV.seenState===SEEN_STATE.GONE||REV.seenState===SEEN_STATE.OLD)&&REV.rows.length){const top=REV.rows[0].id; showRange({mode:RANGE_MODE.ONE,start:top,end:top,endSet:false});}
      else drawRange();}}}
}
// A range's summary on the status line (its source diff): the two ends, the commits and files in it, the merge base when the
// base was on another line, and a warning when the range is wide enough for its comparison PDF to fail (more than 60
// manuscript files, or a diff cut at the server's limit). @param {any} r the /api/revision-diff answer with base
function rangeSummary(r){const files=Array.isArray(r.files)?r.files:[];
  let t=tl('{base} → {head} · 커밋 {commits}개 · 파일 {files}개',{base:String(r.base||'').slice(0,8),head:String(r.id||'').slice(0,8),commits:r.commits,files:files.length});
  if(r.merge_base)t+=' · '+tl('공통 조상 {mb}부터 비교',{mb:String(r.merge_base).slice(0,8)});
  if(files.length>60||r.truncated)t+=' · '+tr('범위가 넓어 비교 PDF가 실패할 수 있습니다');
  return t;}
// ------------------------------------------------ [변경 보기] (docs/handbook/viewer.md §변경 보기): opens the changes tab from an awaiting-review/done pin.
// Commit selection: the commit hash (7+ characters) in the close-time reference (ref) > a commit whose subject contains the reference's PR number
// ('(#236)'/'pull request #236') > among the last 12 commits, the most recent one that touched the pin's file/lines (+-5 lines) > the most recent commit.
// Line matching exists only for the source diff - a line whose new-side line number falls within the pin's range is highlighted and scrolled to.
// The comparison PDF (latexdiff) has no SyncTeX mapping, so it only moves to roughly the pin's page.
// The commit a close reference names among revs (the window's rows, in order) - the server's _ref_commit rule: a 7-40 digit
// hash in every row, a PR number only in the first `recent` rows (REVISION_RECENT; a #N deeper is another PR's). Pure.
/** @param {unknown} ref @param {{id:string,subject?:string}[]} revs @param {number} [recent] */
function matchRevision(ref,revs,recent){const text=String(ref||'');
  for(const m of text.matchAll(/\b[0-9a-f]{7,40}\b/g)){const r=revs.find(x=>x.id.startsWith(m[0])); if(r)return {id:r.id,via:'sha',tok:m[0]};}
  for(const m of text.matchAll(/#(\d+)/g)){const n=m[1],re=new RegExp('\\(#'+n+'\\)|pull request #'+n+'\\b|#'+n+'\\b');
    const r=revs.slice(0,recent).find(x=>re.test(x.subject||'')); if(r)return {id:r.id,via:'pr',tok:'#'+n};}
  return null;}
function pinFileIndex(files,file){file=String(file||''); let best=-1,len=0;
  files.forEach((f,i)=>{const n=f.name; if(n&&(file===n||file.endsWith('/'+n))&&n.length>len){best=i;len=n.length;}}); return best;}
function hunkRanges(text){const out=[]; for(const m of String(text||'').matchAll(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm)){
  const a=+m[1],n=m[2]===undefined?1:+m[2]; out.push([a,a+Math.max(n,1)-1]);} return out;}
function touchesPin(files,tg,slack){const i=pinFileIndex(files,tg.file); if(i<0)return false; slack=slack==null?5:slack;
  return hunkRanges(files[i].text).some(([a,b])=>b>=tg.lo-slack&&a<=tg.hi+slack);}
// A pin's commit: the one its close_ref names (matchRevision over the whole window - a hash not among the loaded rows reads
// further pages until found or the window ends, as the server resolves it), else the most recent of the first REVISION_RECENT
// rows that touched the pin's lines, else the newest.
async function pickRevisionFor(tg,seq,k){
  let m=matchRevision(tg.ref,REV.rows,REVISION_RECENT);
  while(!m&&/\b[0-9a-f]{7,40}\b/.test(String(tg.ref||''))&&REV.more&&seq===REV.seq&&k===DOC){
    if(!await moreRows(k,50))break; m=matchRevision(tg.ref,REV.rows,REVISION_RECENT);}
  if(m)return m;
  const revs=REV.rows.slice(0,REVISION_RECENT);
  if(!tg.region&&tg.file){for(const r of revs){if(seq!==REV.seq||k!==DOC)break;
    try{const d=(await api(dq('/api/revision-diff?commit='+encodeURIComponent(r.id),k),{what:'변경 내용 읽기',silent:true})).data;
      if(touchesPin(revisionFiles(d.diff||''),tg))return {id:r.id,via:'lines'};}catch(e){}}}
  return {id:revs[0].id,via:'latest'};}
/** Explain the shown change and review access for the current pin, retaining the existing source/PDF scope guidance. */
function revTargetNote(msg){const tg=REV.target,box=$('#revision-pin'); if(!tg){box.hidden=true;return;}
  const via={sha:tl('참조의 커밋 {tok}',{tok:tg.tokOf||''}),pr:tr('참조의 PR'),lines:tr('이 줄을 바꾼 가장 최근 커밋'),latest:tr('참조로 커밋을 찾지 못해 가장 최근 커밋')}[tg.via]||'';
  const where=tg.region?tl('쪽 {page} 영역',{page:tg.page}):tg.name+' '+rng(tg.lo,tg.hi);
  const sc=REV.format===DIFF_FORMAT.SOURCE&&REV.scope&&REV.scope.mode===SCOPE_MODE.PIN?REV.scope:null;
  const scopeMsg=sc?tl('이 핀의 변경 {n}곳만 보입니다',{n:sc.hunks})+' ('+tr(sc.source===SCOPE_SOURCE.CHANGES?'에이전트가 기록한 줄':'핀 자리로 추정')+') · ':'';
  let t=msg?tr(msg):REV.format===DIFF_FORMAT.OVERLAY?tl('직전 빌드와 지금 빌드의 {page}쪽을 겹쳐 보입니다 — [이전]·[지금]으로 바꿔 보세요',{page:tg.page})+
    (REV.history?' · '+tr('고친 줄은 [소스 diff]'):''):scopeMsg+(REV.format===DIFF_FORMAT.PDF?tl('비교 PDF에는 줄 대응이 없어 원고 {page}쪽 근처로만 옮겼습니다(삭제 문장이 끼어 쪽이 밀릴 수 있음). 정확한 줄은 [소스 diff]',{page:tg.page}):
    tr(tg.hit===false?'이 커밋의 diff에서 핀 범위를 찾지 못했습니다 — 가장 가까운 줄을 보입니다':
     tg.near?'핀 범위 줄 자체는 바뀌지 않았고 바로 곁(±5줄)이 바뀌었습니다 — 가장 가까운 줄을 보입니다':'강조한 줄이 핀 범위입니다'));
  const p=findAnyPin(tg.id),access=p&&pinState(p)===PIN_STATE.REVIEW&&!canConfirmReview()?confirmAccessText():'';
  setHtml(box,html`<span><b>${tl('핀 #{id}',{id:tg.id})}</b> · ${where}${tg.ref?' · '+tl('참조 {ref}',{ref:tg.ref}):''}${via?' · '+via:''}</span><span class="rp-msg">${t}${access?html` <span class="review-access">${access}</span>`:''}</span>`);
  box.dataset.id=tg.id; box.hidden=false; revTargetActs();}
// The guide line's buttons (docs/handbook/viewer.md §변경 보기): [원고로] and, for a pin awaiting review that this person may confirm
// (a person with write access, not a view-only region pin), the card's [확인] - the same data-act="confirm" and confirmPin(), soft for the
// author as on the card. On the phone and tablet sheet they sit in the thumb row (#revision-acts) right above the status line
// and the tool bar; in the other bands at the guide line's right. Redrawn on a band change and whenever the pin lists change.
/** Draw the current pin's navigation and human-only confirmation controls in the changes guide or compact action row. */
function revTargetActs(){const tg=REV.target,row=$('#revision-acts'),narrow=LAYOUT===LAYOUT_MODE.NARROW;
  $$('.rp-acts').forEach(e=>e.remove());
  if(!tg||$('#revision-pin').hidden){row.hidden=true; document.body.classList.remove('rev-thumb'); return;}
  const p=findAnyPin(tg.id),confirm=!!p&&pinState(p)===PIN_STATE.REVIEW&&!tg.region&&canConfirmReview();
  const backDoc=REV.back&&REV.back!==DOC?docInfo(REV.back):null,back=backDoc?backDoc.name:null,acts=document.createElement('span');
  acts.className='rp-acts';
  const ok=confirm?html`<button class="btn-sm b-confirm ${isMe(p.author)?'btn-soft':'btn-secondary'}" data-act="confirm" data-tip="${T.confirm}">확인</button>`:'';
  setHtml(acts,html`<button class="btn-sm" data-act="rev-back" data-tip="${back?tl('{name} 원고 보기로 돌아갑니다',{name:back}):tr('원고 보기로 돌아갑니다')}">${back?tl('{name}(으)로',{name:back}):tr('원고로')}</button>${ok}`);
  (narrow?row:$('#revision-pin')).appendChild(acts);
  row.dataset.id=tg.id; row.hidden=!narrow; document.body.classList.toggle('rev-thumb',narrow);}
function revHighlight(tg){const rows=$$('#revision-diff .rd-line'); let first=/** @type {Element|null} */(null);
  rows.forEach(el=>{if(!(el.classList.contains('rd-add')||el.classList.contains('rd-context')))return; const n=+el.querySelector('.rd-no').textContent;
    if(n>=tg.lo&&n<=tg.hi){el.classList.add('rd-pin'); if(!first)first=el;}});
  tg.hit=!!first||touchesPin(REV.files,tg,5); tg.near=!first&&tg.hit;   // when only a neighboring line changed, it's never described as "the highlighted line" (there is none)
  if(!first){const f=pinFileIndex(REV.files,tg.file); if(f<0)tg.hit=false;
    else{let best=/** @type {Element|null} */(null),dist=Infinity; rows.forEach(el=>{const n=+el.querySelector('.rd-no').textContent; if(!n)return; const d=Math.min(Math.abs(n-tg.lo),Math.abs(n-tg.hi)); if(d<dist){dist=d;best=el;}}); first=best;}}
  revTargetNote(); const top=first; if(top)requestAnimationFrame(()=>top.scrollIntoView({block:'center'}));}
function findAnyPin(id){return OPEN_ALL.find(p=>p.id===id)||REVIEW_ALL.find(p=>p.id===id)||DONE_ALL.find(p=>p.id===id)||null;}
// REV.back remembers the manuscript document that opened [변경 보기], so [원고로] returns there.
// [원고로] and Esc in the changes view: back to the manuscript view, and to the document it was opened from.
function revBack(){const b=REV.back; REV.back=null; setViewMode(VIEW_MODE.MANUSCRIPT); if(b&&b!==DOC&&docInfo(b))switchDoc(b);}
// Opens a pin's change view only for the document visit that initiated the switch.
async function showChange(id){const p=findAnyPin(id); if(!p)return; const k=pdoc(p),back=DOC,fromManuscript=!document.body.classList.contains('revision-open');
  if(k!==DOC&&docInfo(k)){const opening=switchDoc(k),visit=SWITCHSEQ; await opening; if(DOC!==k||visit!==SWITCHSEQ)return;}
  if(fromManuscript)REV.back=back;
  REV.target={id:p.id,file:p.file||p.pdf||'',name:p.name||String(p.file||p.pdf||'').split('/').pop()||'',lo:p.lo,hi:p.hi,page:pinPlace(p).page,ref:p.close_ref||'',region:isRegion(p)};
  const m=/\b[0-9a-f]{7,40}\b/.exec(REV.target.ref); REV.target.tokOf=m?m[0]:'';
  if(LAYOUT===LAYOUT_MODE.NARROW)setSide(false);
  if(document.body.classList.contains('revision-open'))loadRevisions(); else setViewMode(VIEW_MODE.REVISIONS);}
// Start or read the comparison PDF for this revision; late responses and module imports cannot attach to another view.
/** Load one comparison visit; mounting owns zoomable page geometry. */
async function loadRevisionPdf(id,seq,k){
  const statusBox=$('#revision-status'),warningBox=$('#revision-warning'),tg=REV.target;
  // v0.3: for a pin, the comparison is old + only that pin's hunks unless [커밋 전체 비교] is on or that build already failed
  const pin=tg&&revisionPinFor(id)&&!REV_SCOPE.whole&&!REV_SCOPE.fallback?tg.id:null,base=REV.base,pq=pin?'&pin='+pin:base?'&base='+encodeURIComponent(base):'';
  try{
    let status=(await api('/api/revision-build',{method:'POST',body:pin?{commit:id,doc:k,pin}:base?{commit:id,doc:k,base}:{commit:id,doc:k},what:'비교 PDF 만들기',silent:true})).data;
    if(!revisionCurrent(seq,k,id))return;
    if(pin&&status.scope){REV_SCOPE.partial=status.scope===SCOPE_MODE.PIN;syncRevisionWhole();}
    for(let tries=0;status.state===REVISION_STATE.RUNNING&&tries<180;tries++){
      if(!revisionCurrent(seq,k,id))return;
      statusBox.textContent=base?'두 커밋 사이의 비교 PDF를 만드는 중입니다. 원고와 핀은 그대로 사용할 수 있습니다.':'선택 커밋의 비교 PDF를 만드는 중입니다. 원고와 핀은 그대로 사용할 수 있습니다.';
      await new Promise(resolve=>setTimeout(resolve,1000));
      if(!revisionCurrent(seq,k,id))return;
      status=(await api(dq('/api/revision-build?commit='+encodeURIComponent(id)+pq,k),{what:'비교 PDF 상태',silent:true})).data;
    }
    if(!revisionCurrent(seq,k,id))return;
    if(pin&&status.scope===SCOPE_MODE.PIN&&status.state===REVISION_STATE.ERROR){   // the pin's hunks alone did not compile: show the whole commit, say so in one line
      REV_SCOPE.fallback=true;syncRevisionWhole();return loadRevisionPdf(id,seq,k);}
    if(status.state!==REVISION_STATE.READY)throw new Error(errText(status)||tr(status.state===REVISION_STATE.RUNNING?'비교 PDF 대기 시간이 지났습니다. 다시 열어 재시도하세요.':'비교 PDF를 만들지 못했습니다.'));
    if(status.head&&status.head!==id)throw new Error(tr('요청한 커밋과 비교 PDF의 커밋이 다릅니다.'));
    const warnings=Array.isArray(status.warnings)?status.warnings:[];
    warningBox.hidden=!warnings.length;warningBox.querySelector('summary').textContent=tl('빌드 경고 {n}건 보기',{n:warnings.length});
    warningBox.querySelector('pre').textContent=warnings.join('\n');warningBox.open=false;
    statusBox.textContent='비교 PDF를 읽는 중입니다.';
    const response=await fetch(dq('/api/revision-pdf?commit='+encodeURIComponent(id)+pq,k));
    if(!response.ok)throw new Error(tl('비교 PDF를 열지 못했습니다 (HTTP {status}).',{status:response.status}));
    const bytes=new Uint8Array(await response.arrayBuffer());
    if(!revisionCurrent(seq,k,id))return;
    const lib=VEC.lib||await import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V);
    if(!revisionCurrent(seq,k,id))return;
    lib.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V;
    const loading=lib.getDocument({data:bytes,isEvalSupported:false,useWasm:false,enableXfa:false});REV_PDF.loading=loading;
    const pdf=await loading.promise;
    if(!revisionCurrent(seq,k,id)){try{void loading.destroy().catch(()=>{});}catch(e){}return;}
    REV_PDF.doc=pdf;
    const lead=pin&&status.scope===SCOPE_MODE.PIN?tl('핀 #{id}의 변경만',{id:pin})+' · ':REV_SCOPE.fallback&&tg?tr('이 핀의 변경만으로는 비교 PDF를 만들지 못해 커밋 전체를 비교합니다')+' · ':'';
    const sides={base:String(status.base||'').slice(0,8),head:id.slice(0,8),n:pdf.numPages};
    statusBox.textContent=lead+(base?tl('기준 {base} → {head} · {n}쪽 · 읽기 전용 · 빨강 삭제 / 파랑 추가',sides)+
      (status.merge_base?' · '+tl('공통 조상 {mb}부터 비교',{mb:String(status.merge_base).slice(0,8)}):''):
      tl('첫 부모 {base} → {head} · {n}쪽 · 읽기 전용 · 빨강 삭제 / 파랑 추가',sides));
    await mountRevisionPdf(pdf,seq,k,id);
  }catch(e){if(revisionCurrent(seq,k,id)){
    clearRevisionPdf();
    const data=/** @type {any} */(e&&/** @type {ApiError} */(e).data);
    statusBox.textContent=tl('비교 PDF: {error} 소스 diff에서 변경 내용을 확인할 수 있습니다.',{error:data&&data.error?errText(data):e&&/** @type {Error} */(e).message?/** @type {Error} */(e).message:tr('표시하지 못했습니다.')});
  }}
}
