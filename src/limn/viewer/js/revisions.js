// One changes-view visit owns the selected commit, source text and request sequence.
const REV={seq:0,files:[],whole:'',commit:'',sourceCommit:'',format:/** @type {string} */(DIFF_FORMAT.PDF),scope:null,other:'',target:null,pdfCommit:'',back:null};
// v0.3 (docs/handbook/viewer.md §변경 보기): a pin's view of a commit. REV.scope is the source diff's scope object
// ({mode:'pin'|'commit', source, hunks, other, ...}); REV_PDF holds the comparison PDF's toggle - whole commit or only this pin.
const REV_SCOPE={whole:false,partial:false,fallback:false};
const REV_PDF={doc:null,loading:null,observer:null,tasks:new Set()};
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
  let oldLine=null,newLine=null,inHunk=false;
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
    else if(line.startsWith(' ')){kind='context';if(newLine!==null){number=newLine++;oldLine++;}}
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
// chosen in the list is shown whole (review M1 - another commit's lines are not this pin's).
function revisionPinFor(id){const tg=REV.target; return tg&&!tg.region&&tg.commit&&id===tg.commit?tg:null;}
function setRevisionWhole(on){REV_SCOPE.whole=!!on;++REV.seq;REV.pdfCommit='';
  clearRevisionPdf();$('#revision-warning').hidden=true;setRevisionFormat(DIFF_FORMAT.PDF);}
function revisionCurrent(seq,k,id){return seq===REV.seq&&k===DOC&&id===REV.commit&&document.body.classList.contains('revision-open');}
function clearRevisionPdf(){
  if(REV_PDF.observer){REV_PDF.observer.disconnect();REV_PDF.observer=null;}
  REV_PDF.tasks.forEach(t=>{try{t.cancel();}catch(e){}});REV_PDF.tasks.clear();
  if(REV_PDF.loading){try{REV_PDF.loading.destroy();}catch(e){}REV_PDF.loading=null;}
  REV_PDF.doc=null;$('#revision-pdf').replaceChildren();
}
function setRevisionFormat(format){REV.format=format===DIFF_FORMAT.SOURCE?DIFF_FORMAT.SOURCE:DIFF_FORMAT.PDF;
  $('#revision-pdf-tab').setAttribute('aria-pressed',String(REV.format===DIFF_FORMAT.PDF));
  $('#revision-source-tab').setAttribute('aria-pressed',String(REV.format===DIFF_FORMAT.SOURCE));
  $('#revision-pdf').hidden=REV.format!==DIFF_FORMAT.PDF;$('#revision-source').hidden=REV.format!==DIFF_FORMAT.SOURCE;
  if(REV.format===DIFF_FORMAT.SOURCE&&REV.commit&&REV.sourceCommit!==REV.commit)
    loadRevisionSource(REV.commit,REV.seq,DOC);
  // The comparison PDF is only built when that format is actually viewed - [변경 보기] goes straight to the source diff, so it never wastes a latexdiff build.
  if(REV.format===DIFF_FORMAT.PDF&&REV.commit&&REV.pdfCommit!==REV.commit){REV.pdfCommit=REV.commit;
    $('#revision-status').textContent='비교 PDF 상태를 확인하는 중입니다.'; loadRevisionPdf(REV.commit,REV.seq,DOC);}
  syncRevisionWhole();
  if(REV.target)revTargetNote();
}
// Shows the manuscript or the changes view: the nav bar's tabs, the navigation sheet's switch and the phone's position button
// ([변경사항 ▾] in the changes view) follow; leaving the changes view forgets the pin it was opened for and redraws the pages.
function setViewMode(mode){
  const revisions=mode===VIEW_MODE.REVISIONS; document.body.classList.toggle('revision-open',revisions);
  $('#view-manuscript').setAttribute('aria-pressed',String(!revisions));
  $('#view-revisions').setAttribute('aria-pressed',String(revisions));
  if(!revisions)REV.target=null;
  if(revisions)loadRevisions(); else{++REV.seq;clearRevisionPdf();$('#revision-pin').hidden=true;revTargetActs();if(VEC.doc)vecSchedule(0);updateSectionStrip();}
  drawNavView(); drawPos();
}
// Reads the document's recent commits into the changes view. Without history (not Git, a view-only PDF, or no recent commit) the
// one reason line stays and the unusable [변경 PDF] [소스 diff] and the comparison note are hidden; a pin's guide line stays.
async function loadRevisions(){
  const seq=++REV.seq,k=DOC,list=$('#revision-list'),out=$('#revision-diff'),tg=REV.target;
  clearRevisionPdf();list.textContent='최근 변경사항을 읽는 중입니다.';out.textContent='';$('#revision-pin').hidden=!tg;
  if(tg)revTargetNote('변경사항을 읽는 중입니다.'); else revTargetActs();
  let data; try{data=(await api(dq('/api/revisions',k),{what:'변경사항 읽기',silent:true})).data;}
  catch(e){if(seq===REV.seq)list.textContent='변경사항을 읽지 못했습니다.';return;}
  if(seq!==REV.seq||k!==DOC)return;
  $('#revision-controls').hidden=$('#revision-note').hidden=!data.available||!data.revisions.length;
  if(!data.available){list.textContent='이 문서의 Git 변경사항을 볼 수 없습니다.';
    if(tg)revTargetNote(tg.region?'보기 전용 PDF 문서의 핀이라 Git 변경사항이 없습니다 — 고친 곳은 LaTeX 문서(본문 등)의 변경사항에서 찾으세요.':
      '이 문서는 Git 이력을 읽을 수 없어(Git 저장소가 아니거나 경로가 밖) 핀 자리를 변경과 맞출 수 없습니다.'); return;}
  if(!data.revisions.length){list.textContent='이 문서의 최근 변경사항이 없습니다.'; if(tg)revTargetNote('이 문서의 최근 12개 커밋에 변경이 없습니다.'); return;}
  const options=data.revisions.map(r=>html`<option value="${r.id}">${r.subject} · ${r.date} · ${r.id.slice(0,8)}</option>`);
  setHtml(list,html`<label class="sr-only" for="revision-select">비교할 커밋</label><select id="revision-select" aria-label="비교할 커밋">${options}</select>`);
  if(tg){const pick=await pickRevisionFor(tg,data.revisions,seq,k); if(seq!==REV.seq||k!==DOC||REV.target!==tg)return;
    tg.commit=pick.id; tg.via=pick.via; tg.hit=pick.hit; showRevision(pick.id,DIFF_FORMAT.SOURCE); return;}
  showRevision(data.revisions.some(r=>r.id===REV.commit)?REV.commit:data.revisions[0].id);
}
async function showRevision(id,format){
  ++REV.seq;REV.commit=id;REV.sourceCommit='';REV.pdfCommit='';clearRevisionPdf();
  const select=$('#revision-select');if(select)select.value=id;
  REV.scope=null;REV_SCOPE.whole=REV_SCOPE.partial=REV_SCOPE.fallback=false;drawRevisionOther(null);
  $('#revision-diff').textContent='';$('#revision-file-row').hidden=true;$('#revision-warning').hidden=true;
  $('#revision-status').textContent='';
  setRevisionFormat(format||DIFF_FORMAT.PDF);
}
async function loadRevisionSource(id,seq,k){
  const out=$('#revision-diff');out.textContent='소스 변경 내용을 읽는 중입니다.';$('#revision-file-row').hidden=true;
  const tg0=revisionPinFor(id),pq=tg0?'&pin='+tg0.id:'';
  try{const r=(await api(dq('/api/revision-diff?commit='+encodeURIComponent(id)+pq,k),{what:'변경 내용 읽기',silent:true})).data;
    if(!revisionCurrent(seq,k,id))return;
    // v0.3: a pin's own hunks when it owns part of the commit; otherwise the whole commit exactly as before
    const sc=r.scope&&r.scope.mode===SCOPE_MODE.PIN?r.scope:null;REV.scope=r.scope||null;
    if(sc){REV_SCOPE.partial=true;syncRevisionWhole();}
    const cut='\n\n'+tr('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.');
    REV.whole=sc?sc.diff+(sc.truncated?cut:''):(r.diff||tr('이 커밋에서 표시할 원고 텍스트 변경이 없습니다.'))+(r.truncated?cut:'');
    REV.files=revisionFiles(sc?sc.diff:(r.diff||''));drawRevisionOther(sc);
    const select=$('#revision-file');setHtml(select,html`<option value="all">전체 파일</option>${REV.files.map((f,i)=>html`<option value="${i}">${f.name}</option>`)}`);
    select.value='all';$('#revision-file-row').hidden=REV.files.length<2;REV.sourceCommit=id;
    const tg=REV.target,fi=tg?pinFileIndex(REV.files,tg.file):-1;
    if(fi>=0&&REV.files.length>1)select.value=String(fi);
    renderRevisionFile(); if(tg)revHighlight(tg);
  }catch(e){if(revisionCurrent(seq,k,id))out.textContent='소스 변경 내용을 읽지 못했습니다.';}
}
// ------------------------------------------------ [변경 보기] (docs/handbook/viewer.md §변경 보기): opens the changes tab from an awaiting-review/done pin.
// Commit selection: the commit hash (7+ characters) in the close-time reference (ref) > a commit whose subject contains the reference's PR number
// ('(#236)'/'pull request #236') > among the last 12 commits, the most recent one that touched the pin's file/lines (+-5 lines) > the most recent commit.
// Line matching exists only for the source diff - a line whose new-side line number falls within the pin's range is highlighted and scrolled to.
// The comparison PDF (latexdiff) has no SyncTeX mapping, so it only moves to roughly the pin's page.
function matchRevision(ref,revs){ref=String(ref||'');
  for(const m of ref.matchAll(/\b[0-9a-f]{7,40}\b/g)){const r=revs.find(x=>x.id.startsWith(m[0])); if(r)return {id:r.id,via:'sha',tok:m[0]};}
  for(const m of ref.matchAll(/#(\d+)/g)){const n=m[1],re=new RegExp('\\(#'+n+'\\)|pull request #'+n+'\\b|#'+n+'\\b');
    const r=revs.find(x=>re.test(x.subject||'')); if(r)return {id:r.id,via:'pr',tok:'#'+n};}
  return null;}
function pinFileIndex(files,file){file=String(file||''); let best=-1,len=0;
  files.forEach((f,i)=>{const n=f.name; if(n&&(file===n||file.endsWith('/'+n))&&n.length>len){best=i;len=n.length;}}); return best;}
function hunkRanges(text){const out=[]; for(const m of String(text||'').matchAll(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm)){
  const a=+m[1],n=m[2]===undefined?1:+m[2]; out.push([a,a+Math.max(n,1)-1]);} return out;}
function touchesPin(files,tg,slack){const i=pinFileIndex(files,tg.file); if(i<0)return false; slack=slack==null?5:slack;
  return hunkRanges(files[i].text).some(([a,b])=>b>=tg.lo-slack&&a<=tg.hi+slack);}
async function pickRevisionFor(tg,revs,seq,k){
  const m=matchRevision(tg.ref,revs); if(m)return m;
  if(!tg.region&&tg.file){for(const r of revs){if(seq!==REV.seq||k!==DOC)break;
    try{const d=(await api(dq('/api/revision-diff?commit='+encodeURIComponent(r.id),k),{what:'변경 내용 읽기',silent:true})).data;
      if(touchesPin(revisionFiles(d.diff||''),tg))return {id:r.id,via:'lines'};}catch(e){}}}
  return {id:revs[0].id,via:'latest'};}
function revTargetNote(msg){const tg=REV.target,box=$('#revision-pin'); if(!tg){box.hidden=true;return;}
  const via={sha:tl('참조의 커밋 {tok}',{tok:tg.tokOf||''}),pr:tr('참조의 PR'),lines:tr('이 줄을 바꾼 가장 최근 커밋'),latest:tr('참조로 커밋을 찾지 못해 가장 최근 커밋')}[tg.via]||'';
  const where=tg.region?tl('쪽 {page} 영역',{page:tg.page}):tg.name+' '+rng(tg.lo,tg.hi);
  const sc=REV.format===DIFF_FORMAT.SOURCE&&REV.scope&&REV.scope.mode===SCOPE_MODE.PIN?REV.scope:null;
  const scopeMsg=sc?tl('이 핀의 변경 {n}곳만 보입니다',{n:sc.hunks})+' ('+tr(sc.source===SCOPE_SOURCE.CHANGES?'에이전트가 기록한 줄':'핀 자리로 추정')+') · ':'';
  let t=msg?tr(msg):scopeMsg+(REV.format===DIFF_FORMAT.PDF?tl('비교 PDF에는 줄 대응이 없어 원고 {page}쪽 근처로만 옮겼습니다(삭제 문장이 끼어 쪽이 밀릴 수 있음). 정확한 줄은 [소스 diff]',{page:tg.page}):
    tr(tg.hit===false?'이 커밋의 diff에서 핀 범위를 찾지 못했습니다 — 가장 가까운 줄을 보입니다':
     tg.near?'핀 범위 줄 자체는 바뀌지 않았고 바로 곁(±5줄)이 바뀌었습니다 — 가장 가까운 줄을 보입니다':'강조한 줄이 핀 범위입니다'));
  setHtml(box,html`<span><b>${tl('핀 #{id}',{id:tg.id})}</b> · ${where}${tg.ref?' · '+tl('참조 {ref}',{ref:tg.ref}):''}${via?' · '+via:''}</span><span class="rp-msg">${t}</span>`);
  box.dataset.id=tg.id; box.hidden=false; revTargetActs();}
// The guide line's buttons (docs/handbook/viewer.md §변경 보기): [원고로] and, for a pin awaiting review that this person may confirm
// (not a viewer, not a view-only region pin), the card's [확인] - the same data-act="confirm" and confirmPin(), soft for the
// author as on the card. On the phone and tablet sheet they sit in the thumb row (#revision-acts) right above the status line
// and the tool bar; in the other bands at the guide line's right. Redrawn on a band change and whenever the pin lists change.
function revTargetActs(){const tg=REV.target,row=$('#revision-acts'),narrow=LAYOUT===LAYOUT_MODE.NARROW;
  $$('.rp-acts').forEach(e=>e.remove());
  if(!tg||$('#revision-pin').hidden){row.hidden=true; document.body.classList.remove('rev-thumb'); return;}
  const p=findAnyPin(tg.id),confirm=!!p&&pinState(p)===PIN_STATE.REVIEW&&!tg.region&&!isViewer();
  const back=REV.back&&REV.back!==DOC&&docInfo(REV.back)?docInfo(REV.back).name:null,acts=document.createElement('span');
  acts.className='rp-acts';
  const ok=confirm?html`<button class="btn-sm b-confirm ${isMe(p.author)?'btn-soft':'btn-secondary'}" data-act="confirm" data-tip="${T.confirm}">확인</button>`:'';
  setHtml(acts,html`<button class="btn-sm" data-act="rev-back" data-tip="${back?tl('{name} 원고 보기로 돌아갑니다',{name:back}):tr('원고 보기로 돌아갑니다')}">${back?tl('{name}(으)로',{name:back}):tr('원고로')}</button>${ok}`);
  (narrow?row:$('#revision-pin')).appendChild(acts);
  row.dataset.id=tg.id; row.hidden=!narrow; document.body.classList.toggle('rev-thumb',narrow);}
function revHighlight(tg){const rows=$$('#revision-diff .rd-line'); let first=null;
  rows.forEach(el=>{if(!(el.classList.contains('rd-add')||el.classList.contains('rd-context')))return; const n=+el.querySelector('.rd-no').textContent;
    if(n>=tg.lo&&n<=tg.hi){el.classList.add('rd-pin'); if(!first)first=el;}});
  tg.hit=!!first||touchesPin(REV.files,tg,5); tg.near=!first&&tg.hit;   // when only a neighboring line changed, it's never described as "the highlighted line" (there is none)
  if(!first){const f=pinFileIndex(REV.files,tg.file); if(f<0)tg.hit=false;
    else{let best=null,dist=Infinity; rows.forEach(el=>{const n=+el.querySelector('.rd-no').textContent; if(!n)return; const d=Math.min(Math.abs(n-tg.lo),Math.abs(n-tg.hi)); if(d<dist){dist=d;best=el;}}); first=best;}}
  revTargetNote(); if(first)requestAnimationFrame(()=>first.scrollIntoView({block:'center'}));}
function findAnyPin(id){return OPEN_ALL.find(p=>p.id===id)||REVIEW_ALL.find(p=>p.id===id)||DONE_ALL.find(p=>p.id===id)||null;}
// REV.back remembers the manuscript document that opened [변경 보기], so [원고로] returns there.
// [원고로] and Esc in the changes view: back to the manuscript view, and to the document it was opened from.
function revBack(){const b=REV.back; REV.back=null; setViewMode(VIEW_MODE.MANUSCRIPT); if(b&&b!==DOC&&docInfo(b))switchDoc(b);}
// Opens a pin's change view only for the document visit that initiated the switch.
async function showChange(id){const p=findAnyPin(id); if(!p)return; const k=pdoc(p),back=DOC,fromManuscript=!document.body.classList.contains('revision-open');
  if(k!==DOC&&docInfo(k)){const opening=switchDoc(k),visit=SWITCHSEQ; await opening; if(DOC!==k||visit!==SWITCHSEQ)return;}
  if(fromManuscript)REV.back=back;
  REV.target={id:p.id,file:p.file||p.pdf||'',name:p.name||String(p.file||p.pdf||'').split('/').pop(),lo:p.lo,hi:p.hi,page:p.page,ref:p.close_ref||'',region:isRegion(p)};
  const m=/\b[0-9a-f]{7,40}\b/.exec(REV.target.ref); REV.target.tokOf=m?m[0]:'';
  if(LAYOUT===LAYOUT_MODE.NARROW)setSide(false);
  if(document.body.classList.contains('revision-open'))loadRevisions(); else setViewMode(VIEW_MODE.REVISIONS);}
// Start or read the comparison PDF for this revision; late responses and module imports cannot attach to another view.
async function loadRevisionPdf(id,seq,k){
  const statusBox=$('#revision-status'),warningBox=$('#revision-warning'),tg=REV.target;
  // v0.3: for a pin, the comparison is old + only that pin's hunks unless [커밋 전체 비교] is on or that build already failed
  const pin=revisionPinFor(id)&&!REV_SCOPE.whole&&!REV_SCOPE.fallback?tg.id:null,pq=pin?'&pin='+pin:'';
  try{
    let status=(await api('/api/revision-build',{method:'POST',body:pin?{commit:id,doc:k,pin}:{commit:id,doc:k},what:'비교 PDF 만들기',silent:true})).data;
    if(!revisionCurrent(seq,k,id))return;
    if(pin&&status.scope){REV_SCOPE.partial=status.scope===SCOPE_MODE.PIN;syncRevisionWhole();}
    for(let tries=0;status.state===REVISION_STATE.RUNNING&&tries<180;tries++){
      if(!revisionCurrent(seq,k,id))return;
      statusBox.textContent='선택 커밋의 비교 PDF를 만드는 중입니다. 원고와 핀은 그대로 사용할 수 있습니다.';
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
    if(!revisionCurrent(seq,k,id)){try{loading.destroy();}catch(e){}return;}
    REV_PDF.doc=pdf;
    const lead=pin&&status.scope===SCOPE_MODE.PIN?tl('핀 #{id}의 변경만',{id:pin})+' · ':REV_SCOPE.fallback&&tg?tr('이 핀의 변경만으로는 비교 PDF를 만들지 못해 커밋 전체를 비교합니다')+' · ':'';
    statusBox.textContent=lead+tl('첫 부모 {base} → {head} · {n}쪽 · 읽기 전용 · 빨강 삭제 / 파랑 추가',{base:String(status.base||'').slice(0,8),head:id.slice(0,8),n:pdf.numPages});
    const box=$('#revision-pdf');setHtml(box,html`${Array.from({length:pdf.numPages},(_,i)=>html`<div class="revision-page" data-page="${i+1}" aria-label="${tl('비교 PDF {page}쪽',{page:i+1})}"></div>`)}`);
    if(window.IntersectionObserver){REV_PDF.observer=new IntersectionObserver(rows=>{for(const row of rows)if(row.isIntersecting){
      REV_PDF.observer.unobserve(row.target);renderRevisionPage(row.target,pdf,seq,k,id);
    }},{root:box,rootMargin:'600px 0px'});box.querySelectorAll('.revision-page').forEach(el=>REV_PDF.observer.observe(el));}
    else for(const el of box.querySelectorAll('.revision-page'))renderRevisionPage(el,pdf,seq,k,id);
    if(REV.target&&REV.target.page){const el=box.querySelector('.revision-page[data-page="'+Math.min(REV.target.page,pdf.numPages)+'"]'); if(el)el.scrollIntoView({block:'start'}); revTargetNote();}
  }catch(e){if(revisionCurrent(seq,k,id)){
    statusBox.textContent=tl('비교 PDF: {error} 소스 diff에서 변경 내용을 확인할 수 있습니다.',{error:e&&/** @type {Error} */(e).message?/** @type {Error} */(e).message:tr('표시하지 못했습니다.')});
  }}
}
async function renderRevisionPage(el,pdf,seq,k,id){
  if(el.dataset.state||!revisionCurrent(seq,k,id))return;el.dataset.state='loading';
  try{const page=await pdf.getPage(Number(el.dataset.page));if(!revisionCurrent(seq,k,id))return;
    const base=page.getViewport({scale:1}),cssWidth=Math.min(780,$('#revision-pdf').clientWidth-24),scale=Math.max(0.25,cssWidth/base.width);
    const viewport=page.getViewport({scale}),dpr=Math.min(2,window.devicePixelRatio||1),canvas=document.createElement('canvas');
    canvas.width=Math.ceil(viewport.width*dpr);canvas.height=Math.ceil(viewport.height*dpr);
    canvas.style.width=viewport.width+'px';canvas.style.height=viewport.height+'px';el.style.minHeight=viewport.height+'px';el.append(canvas);
    const task=page.render({canvasContext:canvas.getContext('2d'),viewport,transform:[dpr,0,0,dpr,0,0]});REV_PDF.tasks.add(task);
    try{await task.promise;el.dataset.state='ready';}finally{REV_PDF.tasks.delete(task);}
  }catch(e){if(revisionCurrent(seq,k,id)){$('#revision-status').textContent='일부 비교 PDF 쪽을 그리지 못했습니다. 소스 diff를 확인할 수 있습니다.';el.dataset.state='error';}}
}
