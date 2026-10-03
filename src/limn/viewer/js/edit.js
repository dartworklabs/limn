// ------------------------------------------------ Edit
// The active edit card and its save request share a lifetime; a dirty card may remain visible across document switches.
const EDITOR={current:null,saving:false};
// A dirty edit card survives document switches, so only replacement or cancellation revokes its pending response.
function editorOwns(card){return EDITOR.current===card;}
// Opens the edit card for pin `id` (the pin's document is switched to first) and focuses its note: builds the card markup,
// records the pin's current values as the editor's baseline (EDITOR.current, including a figure pin's element) and loads the
// snippet and range ladder. An edit already open on that pin is left as it is.
function openEdit(id){if(viaDoc(id,openEdit))return; const p=PINS.find(x=>x.id===id); if(!p)return;
  if(document.body.classList.contains('revision-open'))jumpPin(id);
  if(EDITOR.current&&EDITOR.current.id===id)return;
  const el=document.createElement('div'); el.className='edit';
  setHtml(el,html`<div class="e-kind seg kind-seg" role="radiogroup" aria-label="핀 종류"><button data-act="e-kind" data-kind="fix" role="radio" data-tip="고쳐 달라는 요청">수정 요청</button>\
<button data-act="e-kind" data-kind="question" role="radio" data-tip="${T.question}">질문</button></div>\
<textarea class="e-note" rows="3" aria-label="메모 고치기" data-tip="메모를 고칩니다. ⌘ Enter / Ctrl+Enter 저장, Esc 취소"></textarea><div class="m-preview" aria-live="polite" hidden></div>\
<div class="e-qhint q-hint" role="status" hidden>${ic('circle-question-mark')}<span>질문처럼 보입니다 —</span><button data-act="e-kind" data-kind="question" data-tip="이 핀을 질문으로 바꿉니다">질문으로 보내기</button></div>\
<div class="e-assign assign-row" role="radiogroup" aria-label="담당" hidden></div>\
<div class="rg-cap e-cap" aria-live="polite" aria-atomic="true"></div>\
<div class="e-levels seg lad" role="group" aria-label="범위" data-rungs="0"></div>\
<div class="xp e-xp" hidden></div>\
<pre class="e-snip wrap" translate="no">${tr('원문 읽는 중…')}</pre>\
<div class="e-acts"><button class="btn-sm b-repick" data-act="repick" data-tip="${T.repick}">위치 다시 잡기</button>\
<button class="btn-sm b-ecancel" data-act="ecancel" data-tip="${T.ecancel}">취소</button>\
<button class="btn-sm btn-default b-esave" data-act="esave" data-tip="${T.esave}">저장</button></div>`);
  const ta=/** @type {HTMLTextAreaElement} */(el.querySelector('.e-note')); ta.value=p.note||''; ta._mentions=new Set(p.mentions||[]); autoGrow(ta); mentionPreview(ta);
  EDITOR.current={id,el,base_rev:p.rev||0,file:p.file,name:p.name||String(p.file||p.pdf||'').split('/').pop(),lo:p.lo,hi:p.hi,scope:p.scope||null,
    kind:p.kind,env:null,levels:[],n_lines:null,snippet:'',orig:{lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',kind_req:isQuestion(p)?KIND_REQ.QUESTION:KIND_REQ.FIX,assignee:assigneeOf(p)},
    assignee:assigneeOf(p),
    doc:pdoc(p),region:isRegion(p),pinEl:p.el||null,page:pinPlace(p).page,quote:p.quote||'',kind_req:isQuestion(p)?KIND_REQ.QUESTION:KIND_REQ.FIX};
  if(EDITOR.current.region)el.classList.add('region');
  drawPins(); renderEdit(); ta.focus(); editSnip(true);
}
// Does the edit field have unsaved changes (whether it's safe to close the edit when switching documents)?
function editDirty(){const E=EDITOR.current; if(!E)return false; const ta=E.el.querySelector('.e-note');
  return (ta&&ta.value!==E.orig.note)||E.lo!==E.orig.lo||E.hi!==E.orig.hi||E.kind_req!==E.orig.kind_req||E.assignee!==E.orig.assignee;}
function autoGrow(ta){ta.style.height='auto'; const lh=20; ta.style.height=Math.min(12*lh,Math.max(3*lh,ta.scrollHeight+2))+'px';}
document.addEventListener('input',e=>{const t=/** @type {HTMLElement} */(e.target); if(t.classList&&(t.classList.contains('e-note')||t.classList.contains('r-text')||t.id==='note'))autoGrow(t);});
async function editSnip(withLevels){const E=EDITOR.current; if(!E)return;
  if(E.region){E.snippet=E.quote?tl('영역 글자: {text}',{text:E.quote}):tr('(영역 글자 없음)'); renderEdit(); return;}   // view-only: there is no source line
  try{const {status,data}=await api(dq('/api/snippet?file='+encodeURIComponent(E.file)+'&lo='+E.lo+'&hi='+E.hi+(withLevels?'&levels=1':''),E.doc),
      {what:'원문 읽기',expect:[400]});
    if(EDITOR.current!==E)return;
    if(status===400){E.snippet=tr('원문을 읽지 못했습니다')+' — '+errText(data)+'\n'+tr('위치 다시 잡기로 고치세요.'); renderEdit(); return;}
    E.snippet=data.snippet; E.n_lines=data.n_lines;
    if(withLevels&&data.levels){E.levels=data.levels; if(!E.scope||!lvOf(E,E.scope)){const cur=E.levels.find(l=>l.lo===E.lo&&l.hi===E.hi);
      if(cur&&!E.scope)E.scope=null;}}
    renderEdit();}catch(e){}}
// Draws the open edit card from EDITOR.current: the kind, the range caption (a region's page and area instead), the ladder -
// shown only with two or more rungs - the range excerpt (a region's text in the plain source) and the assignee and question
// hints.
function renderEdit(){const E=EDITOR.current; if(!E)return; const el=E.el;
  el.querySelectorAll('.e-kind button').forEach(b=>{const on=b.dataset.kind===(E.kind_req||KIND_REQ.FIX); b.classList.toggle('on',on); b.setAttribute('aria-checked',String(on));});
  setCap(el.querySelector('.e-cap'),E.region?html`<span class="e-range loc" tabindex="0" data-copy="${E.name+' 쪽 '+E.page}">${tl('쪽 {page} · 영역',{page:E.page})}</span>`:rangeCap(E,true));
  drawLadder(el.querySelector('.e-levels'),E,true);
  const pre=el.querySelector('.e-snip'); pre.className='e-snip wrap'; pre.textContent=snipText(E.snippet,false); renderAssignEdit();
  drawExcerpt(E,el.querySelector('.e-xp'),true);
  qHint(el.querySelector('.e-qhint'),el.querySelector('.e-note').value,E.kind_req);}
function cancelEdit(){EDITOR.current=null; drawPins();}
// Saves the open edit card (POST /api/pins/<id>/edit with `base_rev`): only what changed is sent - the note, the kind, the
// assignee and, when the lines or the ladder rung moved, lo/hi with scope and kind. Nothing changed just closes the card.
// On 409 for a closed pin (error===done) the card closes and a warning says only the note can still be changed; on any other
// 409 (a rival edit) the card adopts the stored pin's rev, range, scope, file and element. Always reloads the pins. A viewer
// role and a save already under way send nothing.
async function saveEdit(){const E=EDITOR.current; if(!E||EDITOR.saving||viewerBlocked())return;
  const note=E.el.querySelector('.e-note').value, body={base_rev:E.base_rev};
  if(note!==E.orig.note)body.note=note;
  if(E.kind_req&&E.kind_req!==E.orig.kind_req)body.kind_req=E.kind_req;
  if(E.assignee&&E.assignee!==E.orig.assignee)body.assignee=E.assignee;
  if(body.note!==undefined){const mh=mentionHints(E.el.querySelector('.e-note')); if(mh.length)body.mentions=mh;}
  // A figure pin's ladder here is raw/lines only (no element rungs): a rung press alone would trade the element's kind
  // for 'lines', so only changed lines are sent; the pin keeps its el either way (a range edit is not a loc).
  if(E.lo!==E.orig.lo||E.hi!==E.orig.hi||(!E.pinEl&&(E.scope||null)!==(E.orig.scope||null))){body.lo=E.lo;body.hi=E.hi;
    if(E.scope){body.scope=E.scope; body.kind=kindFor(E.scope,E.env);}}
  if(Object.keys(body).length===1){cancelEdit();return;}
  EDITOR.saving=true;
  try{const {status,data}=await api('/api/pins/'+E.id+'/edit',{method:'POST',body,what:'핀 수정',expect:[409]});
    if(status===409){
      if(data&&data.error===PIN_STATE.DONE){toast(tl('핀 #{id} 은 이미 닫혀 범위를 바꿀 수 없습니다 — 메모만 고칠 수 있습니다',{id:E.id}),'warn'); if(editorOwns(E))EDITOR.current=null; await loadPins(); return;}
      const p=data.pin; toast('다른 쪽(에이전트나 자동 줄 맞춤)이 이 핀을 먼저 바꿨습니다 — 최신 위치를 불러왔습니다','warn');
      if(editorOwns(E)){E.base_rev=p.rev; E.lo=p.lo; E.hi=p.hi; E.scope=p.scope||null; E.file=p.file; E.pinEl=p.el||null;
        E.orig={lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',kind_req:E.orig.kind_req,assignee:assigneeOf(p)}; editSnip(true);}
      await loadPins(); return;}
    if(editorOwns(E))EDITOR.current=null; toast(tl('핀 #{id} 수정됨',{id:E.id}),'ok'); await loadPins();
  }catch(e){} finally{EDITOR.saving=false;}
}
