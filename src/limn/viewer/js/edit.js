// ------------------------------------------------ Edit
// The active edit card and its save request share a lifetime; a dirty card may remain visible across document switches.
const EDITOR={current:/** @type {EditCard|null} */(null),saving:false};
// A dirty edit card survives document switches, so only replacement or cancellation revokes its pending response.
function editorOwns(card){return EDITOR.current===card;}
/** Capture editable card values independently of its mutable range, mention hints, and controls - the suggested edit's switch,
 * text and base among them. */
function editFields(E){return JSON.stringify({note:editNote(E).value,mentions:Array.from(editNote(E)._mentions||[]),
  lo:E.lo,hi:E.hi,scope:E.scope,kind_req:E.kind_req,assignee:E.assignee,sg:{on:E.sg.on,text:E.sg.text,base:E.sg.base}});}
/** Reflect the editor's shared request lifetime on whichever card is currently visible. */
function syncEditSaveButton(){const b=EDITOR.current&&EDITOR.current.el.querySelector('.b-esave');
  if(b)/** @type {HTMLButtonElement} */(b).disabled=EDITOR.saving;}
// The note field of edit card E (openEdit puts exactly one in every card).
/** @param {EditCard} E @returns {HTMLTextAreaElement} */
function editNote(E){return /** @type {HTMLTextAreaElement} */(E.el.querySelector('.e-note'));}
// Opens the edit card for pin `id` (the pin's document is switched to first) and focuses its note: builds the card markup,
// records the pin's current values as the editor's baseline (EDITOR.current, including a figure pin's element) and loads the
// snippet and range ladder. An edit already open on that pin is left as it is.
/** Open an editable card with independent original mention hints, preserving the pin's identity and revision baseline. */
function openEdit(id){if(viaDoc(id,openEdit))return; const p=PINS.find(x=>x.id===id); if(!p)return;
  if(document.body.classList.contains('revision-open'))jumpPin(id);
  if(EDITOR.current&&EDITOR.current.id===id)return;
  const el=document.createElement('div'); el.className='edit';
  setHtml(el,html`<div class="e-kind seg kind-seg" role="radiogroup" aria-label="핀 종류"><button data-act="e-kind" data-kind="fix" role="radio" data-tip="고쳐 달라는 요청">수정 요청</button>\
<button data-act="e-kind" data-kind="question" role="radio" data-tip="${T.question}">질문</button></div>\
<textarea class="e-note" rows="3" aria-label="메모 고치기" data-tip="메모를 고칩니다. ⌘ Enter / Ctrl+Enter 저장, Esc 취소"></textarea><div class="m-preview" aria-live="polite" hidden></div>\
<div class="e-qhint q-hint" role="status" hidden>${ic('circle-question-mark')}<span>질문처럼 보입니다 —</span><button data-act="e-kind" data-kind="question" data-tip="이 핀을 질문으로 바꿉니다">질문으로 보내기</button></div>\
<div class="e-assign assign-row" role="radiogroup" aria-label="담당" hidden></div>\
<div class="e-sg-row sg-row"><button class="btn-ghost sg-tg hit" role="switch" aria-checked="false" data-act="sg-toggle" \
data-tip="이 줄 범위를 바꿀 글을 직접 씁니다. 끄고 저장하면 이 핀의 제안 수정을 지웁니다"><span class="sg-sw" aria-hidden="true"></span><span class="lbl">제안 수정</span></button>\
<span class="sg-why" hidden></span></div>\
<div class="sg e-sg" hidden><textarea class="sg-text e-sg-text" rows="2" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="제안 문안" \
placeholder="이 줄들을 바꿀 글 (비우면 이 줄들을 지웁니다)" data-tip="이 줄 범위를 바꿀 글입니다. ⌘ Enter / Ctrl+Enter 저장, Esc 취소"></textarea>\
<div class="sg-note q-hint" aria-live="polite" hidden></div><div class="sg-cur" hidden></div></div>\
<div class="e-sg-ro" hidden></div>\
<div class="rg-cap e-cap" aria-live="polite" aria-atomic="true"></div>\
<div class="e-levels seg lad" role="group" aria-label="범위" data-rungs="0"></div>\
<div class="xp e-xp" hidden></div>\
<pre class="e-snip wrap" translate="no">${tr('원문 읽는 중…')}</pre>\
<div class="e-acts"><button class="btn-sm b-repick" data-act="repick" data-tip="${T.repick}">위치 다시 잡기</button>\
<button class="btn-sm b-ecancel" data-act="ecancel" data-tip="${T.ecancel}">취소</button>\
<button class="btn-sm btn-default b-esave" data-act="esave" data-tip="${T.esave}">저장</button></div>`);
  const ta=/** @type {HTMLTextAreaElement} */(el.querySelector('.e-note')); ta.value=p.note||''; ta._mentions=new Set(p.mentions||[]); autoGrow(ta); mentionPreview(ta);
  EDITOR.current={id,el,base_rev:p.rev||0,file:p.file,name:p.name||String(p.file||p.pdf||'').split('/').pop()||'',lo:p.lo,hi:p.hi,scope:p.scope||null,
    kind:p.kind,env:null,levels:[],n_lines:null,snippet:'',orig:{lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',mentions:mentionHints(ta),kind_req:isQuestion(p)?KIND_REQ.QUESTION:KIND_REQ.FIX,assignee:assigneeOf(p)},
    assignee:assigneeOf(p),
    doc:pdoc(p),region:isRegion(p),pinEl:p.el||null,page:pinPlace(p).page,quote:p.quote||'',kind_req:isQuestion(p)?KIND_REQ.QUESTION:KIND_REQ.FIX,sg:suggestOfPin(p)};
  if(EDITOR.current.region)el.classList.add('region');
  if(verdictOf(p))el.classList.add('verdict');   // a verdict pin keeps its verdict and target (D3): only the note and the assignee are edited
  drawPins(); renderEdit(); ta.focus(); editSnip(true);
}
// Does the edit field have unsaved changes (whether it's safe to close the edit when switching documents)?
/** Report unsaved note, mention hints, range, scope, kind, assignee or suggested-edit changes before a card may close or change documents. */
function editDirty(){const E=EDITOR.current; if(!E)return false; const ta=editNote(E);
  return (ta&&ta.value!==E.orig.note)||JSON.stringify(mentionHints(ta))!==JSON.stringify(E.orig.mentions||[])||E.lo!==E.orig.lo||E.hi!==E.orig.hi||(E.scope||null)!==(E.orig.scope||null)||E.kind_req!==E.orig.kind_req||E.assignee!==E.orig.assignee||
    suggestForEdit(E.sg,suggestOff(E,editDocKind(E)))!==undefined;}
function autoGrow(ta){ta.style.height='auto'; const lh=20; ta.style.height=Math.min(12*lh,Math.max(3*lh,ta.scrollHeight+2))+'px';}
document.addEventListener('input',e=>{const t=/** @type {HTMLElement} */(e.target); if(t.classList&&(t.classList.contains('e-note')||t.classList.contains('r-text')||t.id==='note'))autoGrow(t);});
async function editSnip(withLevels){const E=EDITOR.current; if(!E)return;
  if(E.region){E.snippet=E.quote?tl('영역 글자: {text}',{text:E.quote}):tr('(영역 글자 없음)'); renderEdit(); return;}   // view-only: there is no source line
  try{const {status,data}=await api(dq('/api/snippet?file='+encodeURIComponent(String(E.file))+'&lo='+E.lo+'&hi='+E.hi+(withLevels?'&levels=1':''),E.doc),
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
/** Draw current editable fields and their save availability, including a card opened while an earlier edit is pending. */
function renderEdit(){const E=EDITOR.current; if(!E)return; const el=E.el; syncEditSaveButton();
  /** @type {NodeListOf<HTMLElement>} */(el.querySelectorAll('.e-kind button')).forEach(b=>{const on=b.dataset.kind===(E.kind_req||KIND_REQ.FIX); b.classList.toggle('on',on); b.setAttribute('aria-checked',String(on));});
  setCap(el.querySelector('.e-cap'),E.region?html`<span class="e-range loc" tabindex="0" data-copy="${E.name+' 쪽 '+E.page}">${tl('쪽 {page} · 영역',{page:E.page})}</span>`:rangeCap(E,true));
  drawLadder(el.querySelector('.e-levels'),E,true);
  const pre=/** @type {HTMLElement} */(el.querySelector('.e-snip')); pre.className='e-snip wrap'; pre.textContent=snipText(E.snippet,false); renderAssignEdit();
  drawExcerpt(E,el.querySelector('.e-xp'),true);
  renderEditSuggest(E);   // the [제안 수정] switch and its editor (suggest.js); a closed pin's suggestion read-only
  qHint(el.querySelector('.e-qhint'),editNote(E).value,E.kind_req);
  const pin=findAnyPin(E.id),closed=!!pin&&pinState(pin)!==PIN_STATE.OPEN;
  /** @type {HTMLElement} */(el.querySelector('.b-repick')).hidden=closed;
  if(closed){/** @type {HTMLElement} */(el.querySelector('.e-levels')).hidden=true; /** @type {HTMLElement} */(el.querySelector('.e-xp')).hidden=true;}}
function cancelEdit(){EDITOR.current=null; drawPins();}
// Saves the open edit card (POST /api/pins/<id>/edit with `base_rev`): only what changed is sent - the note and its hints, the kind, the
// assignee, the suggested edit (suggestForEdit: set, replaced, or null to remove it) and, when the lines or the ladder rung moved,
// lo/hi with scope and kind. Nothing changed just closes the card. On 409 suggest_base_changed nothing was saved: the card keeps
// its draft, shows the lines' current text against it and the banner offers [지금 원문으로 맞추기].
// On 409 for a closed pin (error===done), the card retains its note against the latest stored range and a warning banner says
// only the note can still be changed; on any other 409 (a rival edit) the card adopts the stored pin's rev, range, scope, file and element, and a banner
// says so. A saved edit is silent (the card shows it; read out only). Always reloads the pins. A viewer role and a save already
// under way send nothing.
/** Submit one edit revision, including hint-only changes; later input keeps the card open against the successful response's baseline. */
async function saveEdit(){const E=EDITOR.current; if(!E||EDITOR.saving||viewerBlocked())return;
  const note=editNote(E).value, body={base_rev:E.base_rev};
  if(note!==E.orig.note||JSON.stringify(mentionHints(editNote(E)))!==JSON.stringify(E.orig.mentions||[]))body.note=note;
  if(E.kind_req&&E.kind_req!==E.orig.kind_req)body.kind_req=E.kind_req;
  if(E.assignee&&E.assignee!==E.orig.assignee)body.assignee=E.assignee;
  if(body.note!==undefined){const mh=mentionHints(editNote(E)); if(mh.length)body.mentions=mh;}
  // A figure pin's ladder here is raw/lines only (no element rungs): a rung press alone would trade the element's kind
  // for 'lines', so only changed lines are sent; the pin keeps its el either way (a range edit is not a loc).
  if(E.lo!==E.orig.lo||E.hi!==E.orig.hi||(!E.pinEl&&(E.scope||null)!==(E.orig.scope||null))){body.lo=E.lo;body.hi=E.hi;
    if(E.scope){body.scope=E.scope; body.kind=kindFor(E.scope,E.env);}}
  const sg=suggestForEdit(E.sg,suggestOff(E,editDocKind(E))); if(sg!==undefined)body.suggest=sg;
  if(Object.keys(body).length===1){cancelEdit();return;}
  const fields=editFields(E),hints=mentionHints(editNote(E)); EDITOR.saving=true; syncEditSaveButton();
  try{const {status,data}=await api('/api/pins/'+E.id+'/edit',{method:'POST',body,what:'핀 수정',where:NOTICE_HOST.LIST,expect:[409],intent:'edit'});
    if(status===409){
      if(data&&data.reason==='suggest_base_changed'){editSuggestRefused(E,data); return;}
      if(data&&data.error===PIN_STATE.DONE){bannerNote(NOTICE_HOST.LIST,tl('핀 #{id} 은 이미 닫혀 범위를 바꿀 수 없습니다 — 메모만 고칠 수 있습니다',{id:E.id}),NOTICE_KIND.WARN);
        if(editorOwns(E)){const p=data.pin; E.base_rev=p.rev; E.lo=p.lo; E.hi=p.hi; E.scope=p.scope||null; E.file=p.file; E.pinEl=p.el||null;
          E.orig={lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',mentions:(p.mentions||[]).filter(l=>(p.note||'').includes('@'+peopleName(l))),kind_req:isQuestion(p)?KIND_REQ.QUESTION:KIND_REQ.FIX,assignee:assigneeOf(p)}; editSnip(true);}
        await loadPins(); return;}
      const p=data.pin; bannerNote(NOTICE_HOST.LIST,'다른 쪽(에이전트나 자동 줄 맞춤)이 이 핀을 먼저 바꿨습니다 — 최신 위치를 불러왔습니다',NOTICE_KIND.WARN);
      if(editorOwns(E)){const keep=suggestForEdit(E.sg,suggestOff(E,editDocKind(E)))!==undefined;   // a suggestion being changed is kept; else the stored one is taken
        E.base_rev=p.rev; E.lo=p.lo; E.hi=p.hi; E.scope=p.scope||null; E.file=p.file; E.pinEl=p.el||null;
        if(keep)E.sg.had=p.suggest?{base:p.suggest.base,text:p.suggest.text}:null; else E.sg=suggestOfPin(p);
        E.orig={lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',mentions:(p.mentions||[]).filter(l=>(p.note||'').includes('@'+peopleName(l))),kind_req:E.orig.kind_req,assignee:assigneeOf(p)}; editSnip(true);}
      await loadPins(); return;}
    if(editorOwns(E)){if(editFields(E)===fields)EDITOR.current=null;
      else{const p=data.pin; E.base_rev=p.rev; E.orig={lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',mentions:hints.slice(),kind_req:isQuestion(p)?KIND_REQ.QUESTION:KIND_REQ.FIX,assignee:assigneeOf(p)};
        E.sg.had=p.suggest?{base:p.suggest.base,text:p.suggest.text}:null;}}
    quietNote(tl('핀 #{id} 수정됨',{id:E.id})); await loadPins();
  }catch(e){} finally{EDITOR.saving=false; syncEditSaveButton();}
}
// An edit the server answered 409 suggest_base_changed: nothing was saved and card E keeps its draft. The editor shows the lines'
// current text against the draft and the list's banner offers [지금 원문으로 맞추기] (the draft keeps its text and takes that text as
// its base); then [저장] again.
/** @param {EditCard} E @param {any} data */
function editSuggestRefused(E,data){if(editorOwns(E)){E.sg.current={text:String(data.current||''),file:E.file||null,lo:/** @type {number} */(E.lo),hi:/** @type {number} */(E.hi)}; renderEdit();}
  bannerNote(NOTICE_HOST.LIST,tl('핀 #{id} 수정 실패',{id:E.id})+' — '+tr('그사이 그 줄들의 원문이 바뀌었습니다'),NOTICE_KIND.ERR,
    {label:'지금 원문으로 맞추기',tip:'쓰던 글은 그대로 두고, 이 제안이 바꿀 원문을 지금 그 줄들의 글로 바꿉니다. 그다음 다시 저장합니다',
      fn:()=>{if(editorOwns(E))suggestRebase(E.sg,E,()=>editorOwns(E),()=>{if(editorOwns(E))renderEditSuggest(E);});}},
    {source:'POST /api/pins/'+E.id+'/edit edit'});}
