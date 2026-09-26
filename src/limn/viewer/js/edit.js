// ------------------------------------------------ Edit
function openEdit(id){if(viaDoc(id,openEdit))return; const p=PINS.find(x=>x.id===id); if(!p)return;
  if(document.body.classList.contains('revision-open'))jumpPin(id);
  if(EDIT&&EDIT.id===id)return;
  const el=document.createElement('div'); el.className='edit';
  el.innerHTML='<div class="e-kind seg kind-seg" role="radiogroup" aria-label="핀 종류"><button data-act="e-kind" data-kind="fix" role="radio" data-tip="고쳐 달라는 요청">수정 요청</button>'+
    '<button data-act="e-kind" data-kind="question" role="radio" data-tip="'+esc(T.question)+'">질문</button></div>'+
    '<textarea class="e-note" rows="3" aria-label="메모 고치기" data-tip="메모를 고칩니다. ⌘ Enter / Ctrl+Enter 저장, Esc 취소"></textarea><div class="m-preview" aria-live="polite" hidden></div>'+
    '<div class="e-qhint q-hint" role="status" hidden>'+ic('circle-question-mark')+'<span>질문처럼 보입니다 —</span><button data-act="e-kind" data-kind="question" data-tip="이 핀을 질문으로 바꿉니다">질문으로 보내기</button></div>'+
    '<div class="e-assign assign-row" role="radiogroup" aria-label="담당" hidden></div>'+
    '<div class="e-levels seg" role="group" aria-label="범위 단계"></div>'+
    '<div class="c-tools"><div class="step" role="group" aria-label="한 줄씩 넓히고 좁히기">'+
    '<span class="sl" aria-hidden="true">위</span><button data-act="nudge" data-dir="up-grow" aria-label="위로 한 줄 넓히기" data-tip="위로 한 줄 넓힙니다">'+ic('plus')+'</button>'+
    '<button data-act="nudge" data-dir="up-shrink" aria-label="위에서 한 줄 좁히기" data-tip="위에서 한 줄 좁힙니다">'+ic('minus')+'</button>'+
    '<span class="sl" aria-hidden="true">아래</span><button data-act="nudge" data-dir="down-grow" aria-label="아래로 한 줄 넓히기" data-tip="아래로 한 줄 넓힙니다">'+ic('plus')+'</button>'+
    '<button data-act="nudge" data-dir="down-shrink" aria-label="아래에서 한 줄 좁히기" data-tip="아래에서 한 줄 좁힙니다">'+ic('minus')+'</button></div>'+
    '<span class="e-range loc" tabindex="0" data-tip="저장하면 핀이 가리킬 원문 줄. 누르면 복사"></span></div>'+
    '<pre class="e-snip wrap">원문 읽는 중…</pre>'+
    '<div class="e-acts"><button class="btn-sm b-repick" data-act="repick" data-tip="'+esc(T.repick)+'">위치 다시 잡기</button>'+
    '<button class="btn-sm b-ecancel" data-act="ecancel" data-tip="'+esc(T.ecancel)+'">취소</button>'+
    '<button class="btn-sm btn-default b-esave" data-act="esave" data-tip="'+esc(T.esave)+'">저장</button></div>';
  const ta=el.querySelector('.e-note'); ta.value=p.note||''; ta._mentions=new Set(p.mentions||[]); autoGrow(ta); mentionPreview(ta);
  EDIT={id,el,base_rev:p.rev||0,file:p.file,name:p.name||String(p.file||p.pdf||'').split('/').pop(),lo:p.lo,hi:p.hi,scope:p.scope||null,
    kind:p.kind,env:null,levels:[],n_lines:null,snippet:'',orig:{lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',kind_req:isQuestion(p)?'question':'fix',assignee:assigneeOf(p)},
    assignee:assigneeOf(p),
    doc:pdoc(p),region:isRegion(p),page:p.page,quote:p.quote||'',kind_req:isQuestion(p)?'question':'fix'};
  if(EDIT.region)el.classList.add('region');
  drawPins(); renderEdit(); ta.focus(); editSnip(true);
}
// Does the edit field have unsaved changes (whether it's safe to close the edit when switching documents)?
function editDirty(){const E=EDIT; if(!E)return false; const ta=E.el.querySelector('.e-note');
  return (ta&&ta.value!==E.orig.note)||E.lo!==E.orig.lo||E.hi!==E.orig.hi||E.kind_req!==E.orig.kind_req||E.assignee!==E.orig.assignee;}
function autoGrow(ta){ta.style.height='auto'; const lh=20; ta.style.height=Math.min(12*lh,Math.max(3*lh,ta.scrollHeight+2))+'px';}
document.addEventListener('input',e=>{if(e.target.classList&&(e.target.classList.contains('e-note')||e.target.classList.contains('r-text')||e.target.id==='note'))autoGrow(e.target);});
async function editSnip(withLevels){const E=EDIT; if(!E)return;
  if(E.region){E.snippet=E.quote?tl('영역 글자: {text}',{text:E.quote}):tr('(영역 글자 없음)'); renderEdit(); return;}   // view-only: there is no source line
  try{const {status,data}=await api(dq('/api/snippet?file='+encodeURIComponent(E.file)+'&lo='+E.lo+'&hi='+E.hi+(withLevels?'&levels=1':''),E.doc),
      {what:'원문 읽기',expect:[400]});
    if(EDIT!==E)return;
    if(status===400){E.snippet=tr('원문을 읽지 못했습니다')+' — '+errText(data)+'\n'+tr('위치 다시 잡기로 고치세요.'); renderEdit(); return;}
    E.snippet=data.snippet; E.n_lines=data.n_lines;
    if(withLevels&&data.levels){E.levels=data.levels; if(!E.scope||!lvOf(E,E.scope)){const cur=E.levels.find(l=>l.lo===E.lo&&l.hi===E.hi);
      if(cur&&!E.scope)E.scope=null;}}
    renderEdit();}catch(e){}}
function renderEdit(){const E=EDIT; if(!E)return; const el=E.el;
  el.querySelectorAll('.e-kind button').forEach(b=>{const on=b.dataset.kind===(E.kind_req||'fix'); b.classList.toggle('on',on); b.setAttribute('aria-checked',String(on));});
  el.querySelector('.e-range').textContent=E.region?tl('쪽 {page} · 영역',{page:E.page}):rng(E.lo,E.hi);
  el.querySelector('.e-range').dataset.copy=E.region?E.name+' 쪽 '+E.page:E.name+' L'+E.lo+'-L'+E.hi;
  el.querySelector('.e-levels').innerHTML=levelBtns(E,true); segReveal(el.querySelector('.e-levels'));
  const pre=el.querySelector('.e-snip'); pre.className='e-snip '+(WRAP?'wrap':'nowrap'); pre.textContent=snipText(E.snippet,false); renderAssignEdit();
  qHint(el.querySelector('.e-qhint'),el.querySelector('.e-note').value,E.kind_req);}
function cancelEdit(){EDIT=null; drawPins();}
async function saveEdit(){const E=EDIT; if(!E||ESAVING||viewerBlocked())return;
  const note=E.el.querySelector('.e-note').value, body={base_rev:E.base_rev};
  if(note!==E.orig.note)body.note=note;
  if(E.kind_req&&E.kind_req!==E.orig.kind_req)body.kind_req=E.kind_req;
  if(E.assignee&&E.assignee!==E.orig.assignee)body.assignee=E.assignee;
  if(body.note!==undefined){const mh=mentionHints(E.el.querySelector('.e-note')); if(mh.length)body.mentions=mh;}
  if(E.lo!==E.orig.lo||E.hi!==E.orig.hi||(E.scope||null)!==(E.orig.scope||null)){body.lo=E.lo;body.hi=E.hi;
    if(E.scope){body.scope=E.scope; body.kind=kindFor(E.scope,E.env);}}
  if(Object.keys(body).length===1){cancelEdit();return;}
  ESAVING=true;
  try{const {status,data}=await api('/api/pins/'+E.id+'/edit',{method:'POST',body,what:'핀 수정',expect:[409]});
    if(status===409){
      if(data&&data.error==='done'){toast(tl('핀 #{id} 은 이미 닫혀 범위를 바꿀 수 없습니다 — 메모만 고칠 수 있습니다',{id:E.id}),'warn'); EDIT=null; await loadPins(); return;}
      const p=data.pin; toast('다른 쪽(에이전트나 자동 줄 맞춤)이 이 핀을 먼저 바꿨습니다 — 최신 위치를 불러왔습니다','warn');
      E.base_rev=p.rev; E.lo=p.lo; E.hi=p.hi; E.scope=p.scope||null; E.file=p.file;
      E.orig={lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',kind_req:E.orig.kind_req,assignee:assigneeOf(p)}; editSnip(true); await loadPins(); return;}
    EDIT=null; toast(tl('핀 #{id} 수정됨',{id:E.id}),'ok'); await loadPins();
  }catch(e){} finally{ESAVING=false;}
}

