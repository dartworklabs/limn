// ------------------------------------------------ composer
// The active selection owns its PDF box, in-flight pick/save, and overlap choice for one composer visit.
const COMPOSE={current:null,box:null,picking:false,pendingSave:false,saving:false,dismissedOverlap:null};
// A completed save may clear only the selection and box that sent the request in this document visit.
function composeOwns(selection,box,visit){return currentVisit(visit)&&COMPOSE.current===selection&&COMPOSE.box===box;}
function setBusy(on){$('#c-spin').hidden=!on; $('#c-body').classList.toggle('busy',on);}
// Turns a dragged PDF region into source lines (/api/pick) and fills the composer - or, while relocating, the banner.
// A new selection opens a collapsed panel; stale responses (PICKSEQ) are dropped; a save queued meanwhile runs after it.
async function pick(r){
  const seq=++PICKSEQ,rp=REPICK;
  // When a new selection (not a re-place) starts, the previous COMPOSE.current is cleared right away - so that a [핀 저장] within
  // this window (~1.1s) never silently saves the stale COMPOSE.current, and instead goes through the COMPOSE.pendingSave queue (docs/handbook/viewer.md §패널 정리) to
  // save the just-chosen new location (regression: the old location used to get saved on a re-select).
  if(rp){banner('<span>되짚는 중…</span>');} else {COMPOSE.current=null; $('#composer').hidden=false; setBusy(true); COMPOSE.picking=true; $('#c-err').hidden=true; $('#c-body').hidden=false;
    setSide(true); applySide();   // a collapsed panel opens for a new selection in every layout (wide included)
    if(MID_OVERLAY)relayout();    // composing in the overlay pads the PDF by the panel width (CSS): re-fit now, then reveal the box
    if(LAYOUT!==LAYOUT_MODE.WIDE){$('#right').scrollTop=0; revealBox(COMPOSE.box);}}
  let d;
  try{d=(await api('/api/pick',{method:'POST',body:r,what:'위치 찾기'})).data;}
  catch(e){if(seq!==PICKSEQ)return; setBusy(false); if(!rp){COMPOSE.picking=false; clearPendingSave();}
    if(rp){bannerRepick();} else {if(COMPOSE.box){COMPOSE.box.remove();COMPOSE.box=null;} if(!COMPOSE.current){$('#composer').hidden=true; applySide();}} return;}
  if(seq!==PICKSEQ)return;
  setBusy(false); if(!rp)COMPOSE.picking=false;
  if(d.error){
    if(d.pdf_build_gone){try{await refreshDoc();}catch(e){} if(seq!==PICKSEQ)return;
      if(rp&&rp.box){rp.box.remove();rp.box=null;} else if(!rp&&COMPOSE.box){COMPOSE.box.remove();COMPOSE.box=null;}}
    if(rp){bannerRepick(errText(d));return;}
    // Even a pending save is never carried out if pick fails - only the existing error panel is shown (regression: prevents a silent save failure).
    COMPOSE.current=null; clearPendingSave(); $('#c-err').textContent=errText(d); $('#c-err').hidden=false; $('#c-body').hidden=true; return;}
  if(rp){rp.cand=d; bannerCompare(); return;}
  COMPOSE.current=d; COMPOSE.current.scope=null; COMPOSE.current.elSel=d.el||null; if(!isRegion(d)){useLevel(COMPOSE.current,d.default_level); if(!COMPOSE.current.scope){COMPOSE.current.lo=d.lo;COMPOSE.current.hi=d.hi;}}
  COMPOSE.dismissedOverlap=null;   // a freshly chosen selection - re-notified even if [별도 핀으로 저장] was pressed for a previous selection
  COMPOSE.current.overlaps=overlapsFor(COMPOSE.current,PINS);
  // If a pin the server saw as overlapping isn't in this tab's PINS (someone else just saved it), the list is re-fetched - loadPins recomputes overlap too.
  if((d.overlaps||[]).some(o=>!PINS.some(p=>p.id===o.id)))loadPins();
  SNIP_OPEN=false; $('#c-err').hidden=true; $('#c-body').hidden=false; renderComposer();
  $('#composer').scrollTop=0;   // so a second drag's new location/ladder never hides above the scroll (the note stays as-is)
  if(LAYOUT!==LAYOUT_MODE.WIDE)$('#right').scrollTop=0;
  // Drag -> straight into the note field. Never focused on touch - the virtual keyboard would pop up immediately and cover the range ladder and page.
  if(LAST_PTR==='mouse')$('#note').focus({preventScroll:true});
  // If [핀 저장] was pressed while pick was still slow (~1.1s), the queued save runs here (COMPOSE.current has just been filled in).
  if(COMPOSE.pendingSave){clearPendingSave(); savePin();}
}
// docs/handbook/api.md §겹친 핀과 덧붙이기: if the pre-save selection (COMPOSE.current) overlaps an open pin, one representative is chosen and a "append" banner
// is drawn. Never auto-merged - the user picks between [메모에 덧붙이기]/[별도 핀으로 저장].
// Overlap is recomputed against this tab's PINS every time the range changes (drag/level switch/up-down). Computing
// it only once at pick time meant switching levels to produce the exact same range as an existing pin never showed
// the banner, and a duplicate pin got saved (observed). The rule matches the server's selection_rel (a regression
// test compares them): equal (same range) - inside (selection is inside the pin) - contains (selection wraps the pin) - partial.
function selRel(lo,hi,blo,bhi){
  if(hi<blo||bhi<lo)return null;
  if(lo===blo&&hi===bhi)return RANGE_REL.EQUAL;
  if(blo<=lo&&hi<=bhi)return RANGE_REL.INSIDE;
  if(lo<=blo&&bhi<=hi)return RANGE_REL.CONTAINS;
  return RANGE_REL.PARTIAL;
}
function overlapsFor(o,pins){const out=[]; if(!o||!o.file)return out;   // a selection on a view-only PDF has no line
  (pins||[]).forEach(p=>{if(pinState(p)!==PIN_STATE.OPEN||p.file!==o.file)return; const rel=selRel(o.lo,o.hi,p.lo,p.hi);
    if(rel)out.push({id:p.id,lo:p.lo,hi:p.hi,rel:rel});});
  return out;}
// One representative: same range > inside (the narrowest enclosing pin) > contains (the widest inner pin) > overlap (the smallest id).
function pickOverlap(ovs){
  if(!ovs||!ovs.length)return null;
  const eq=ovs.filter(o=>o.rel===RANGE_REL.EQUAL);
  if(eq.length)return eq.reduce((a,b)=>b.id<a.id?b:a);
  const insides=ovs.filter(o=>o.rel===RANGE_REL.INSIDE);
  if(insides.length)return insides.reduce((a,b)=>(b.hi-b.lo)<(a.hi-a.lo)?b:a);
  const contains=ovs.filter(o=>o.rel===RANGE_REL.CONTAINS);
  if(contains.length)return contains.reduce((a,b)=>(b.hi-b.lo)>(a.hi-a.lo)?b:a);
  const partials=ovs.filter(o=>o.rel===RANGE_REL.PARTIAL);
  if(partials.length)return partials.reduce((a,b)=>b.id<a.id?b:a);
  return null;
}
// Overlap-banner wording: what relationship the selection has to that pin - '#4와 같은 범위' - '#4 범위 안' - '#4를 감쌈' - '#4와 일부 겹침'.
// The whole banner sentence in the UI language: '열린 핀 #4와 같은 범위입니다' / 'Same range as open pin #4'.
function overlapText(rel,id){const k={equal:'열린 핀 #{id}{p} 같은 범위입니다',inside:'열린 핀 #{id} 범위 안입니다',contains:'열린 핀 #{id}{p} 감쌉니다',
    partial:'열린 핀 #{id}{p} 일부 겹칩니다'}[rel]||'열린 핀 #{id}{p} 겹칩니다';
  return tl(k,{id,p:rel===RANGE_REL.CONTAINS?josa(id,'을','를'):josa(id,'과','와')});}
// [별도 핀으로 저장] turns off "that relationship with that pin" (id:rel). Re-announced if changing the range changes the
// relationship, and reset on a fresh drag (pick) - prevents a regression where one press permanently silenced it for every later selection.

function recomputeOverlap(){if(COMPOSE.current)COMPOSE.current.overlaps=overlapsFor(COMPOSE.current,PINS);}
// Draws the overlap notice for the current selection, or hides it. On the phone sheet it is one line (diagnosis P2: three lines
// took 72px above the note): the short relation ('#4와 같은 범위', the full sentence and the lines in its tooltip) and the two
// actions with short names; elsewhere the sentence with the lines and the two full-named buttons.
function renderOverlapBanner(){
  const box=$('#c-overlap'); const d=COMPOSE.current;
  const ov=d?pickOverlap(d.overlaps):null;
  if(!ov||COMPOSE.dismissedOverlap===ov.id+':'+ov.rel){box.hidden=true;return;}
  box.hidden=false; box.dataset.rel=ov.rel;
  const one=LAYOUT===LAYOUT_MODE.NARROW,full=overlapText(ov.rel,ov.id)+' (L'+ov.lo+'-L'+ov.hi+')';
  box.classList.toggle('one',one);
  box.innerHTML=(one?'<span class="ov-t" data-tip="'+esc(full)+'">'+esc(overlapShort(ov.rel,ov.id))+'</span>'
      :'<span>'+overlapText(ov.rel,ov.id)+' <span class="dim">(L'+ov.lo+'-L'+ov.hi+')</span></span>')+
    '<button class="btn-sm hit" data-act="overlap-append" data-oid="'+ov.id+'" data-tip="'+tl('이 선택의 메모를 #{id} 에 덧붙이고, 지금 선택은 새 핀으로 만들지 않습니다',{id:ov.id})+'">'+
    (one?tr('덧붙이기'):tl('#{id} 메모에 덧붙이기',{id:ov.id}))+'</button>'+
    '<button class="btn-sm hit" data-act="overlap-separate" data-key="'+ov.id+':'+ov.rel+'" data-tip="겹쳐도 별도 핀으로 저장합니다">'+(one?tr('따로 저장'):'별도 핀으로 저장')+'</button>';
}
// The overlap in a few words for the one-line notice: '#4와 같은 범위' - '#4 범위 안' - '#4를 감쌈' - '#4와 일부 겹침' (the card badges' wording).
function overlapShort(rel,id){const k={equal:'#{id}{p} 같은 범위',inside:'#{id} 범위 안',contains:'#{id}{p} 감쌈',partial:'#{id}{p} 일부 겹침'}[rel]||'#{id}{p} 일부 겹침';
  return tl(k,{id,p:rel===RANGE_REL.CONTAINS?josa(id,'을','를'):josa(id,'과','와')});}
// Location is one line: 'file L159' + page + match badge + [copy]. Range kind/line count are never repeated: the range
// caption (rangeCap) under it says them, and the ladder's pressed segment. The dragged line goes into the description.
// Selection on a view-only PDF: the location is '쪽 N - 영역', and the region's text (pdftotext) is shown in the source field. The range ladder/stepper are hidden.
function renderRegionComposer(d){
  $('#composer').classList.add('region');
  $('#c-loc').textContent=d.name+' · '+tl('쪽 {page} 영역',{page:d.page}); $('#c-loc').dataset.copy=d.name+' 쪽 '+d.page;
  // A figure region: '코드 없는 요소' (element without code lines, its box snapped) or '영역' (map unreadable).
  const pg=$('#c-page'),fb=figRegionBadge(d.el,isFigureKind(META&&META.kind));
  pg.textContent=fb?fb.t:tr('보기 전용'); pg.dataset.tip=fb?fb.tip:'LaTeX 소스가 없는 PDF입니다 — 줄 번호 없이 쪽·영역과 영역 글자로 핀을 남깁니다';
  $('#c-tag').hidden=true; $('#c-warn').hidden=!d.warn; $('#c-warn').textContent=warnText(d.warn); $('#c-overlap').hidden=true;
  $('#c-levels').innerHTML=''; $('#c-cap').innerHTML=''; drawExcerpt(null,$('#c-xp'),false);
  const pre=$('#c-snip'); pre.className='wrap open'; pre.textContent=d.quote?tl('영역 글자: {text}',{text:d.quote}):tr('(이 영역에는 글자가 없습니다)');
  $('#c-expand').hidden=true; renderElement(d,COMPOSE.box);}
// Draws the composer from COMPOSE.current (location, ladder, source, overlap) and schedules the draft write - every change of the
// selection (a pick, a level, a nudge, a restore) passes through here.
function renderComposer(){const d=COMPOSE.current; if(!d)return; saveDraftSoon();
  if(isRegion(d)){renderRegionComposer(d); return;}
  $('#composer').classList.remove('region');
  const copy=d.name+' L'+d.lo+'-L'+d.hi;
  $('#c-loc').textContent=d.name+' '+rng(d.lo,d.hi); $('#c-loc').dataset.copy=copy; renderElement(d,COMPOSE.box);
  const pg=$('#c-page'),pgn=tl('{page}쪽',{page:d.page}),sc=scopeLabel(d); pg.textContent=pgn;
  pg.dataset.tip=pgn+(sc?' · '+sc:'')+' · '+tl('{n}줄',{n:d.hi-d.lo+1})+' · '+tl('드래그한 줄 {range}',{range:rng(d.raw_lo,d.raw_hi)});
  const v=viaTag(d),tg=$('#c-tag'); tg.hidden=!v; if(v){tg.textContent=v.t;tg.dataset.tip=v.tip;tg.classList.toggle('badge-warning',!!v.low);}
  $('#c-warn').hidden=!d.warn; $('#c-warn').textContent=warnText(d.warn);
  renderOverlapBanner();
  $('#c-cap').innerHTML=rangeCap(d,false); drawLadder($('#c-levels'),d,false);
  const pre=$('#c-snip'); pre.className=(WRAP?'wrap':'nowrap')+(SNIP_OPEN?' open':''); pre.textContent=snipText(d.snippet,SNIP_OPEN);
  // A collapsed source is cut to 4 lines by CSS. Whether it was cut is measured after rendering (a manuscript where one long line wraps into several is common).
  const over=SNIP_OPEN||pre.scrollHeight>pre.clientHeight+2, nl=String(d.snippet||'').split('\n').length;
  pre.classList.toggle('clip',!SNIP_OPEN&&over);
  $('#c-expand').hidden=!over; $('#c-expand').textContent=SNIP_OPEN?tr('원문 접기'):tr('원문 펼치기')+(nl>1?' · '+tl('{n}줄',{n:nl}):'');
  $('#c-wrap').setAttribute('aria-pressed',String(WRAP));
  drawExcerpt(d,$('#c-xp'),false);   // the compact bands' range excerpt (excerpt.js)
}
// When a selection ends via save/cancel/append, selection mode is turned off (scrolling resumes) and the narrow sheet collapses (the body comes forward again).
// The composer panel's pin kind (fix request / question). Reverts to fix request on save or discard (the default for the next pin).
function setKind(k){KIND_NEW=k===KIND_REQ.QUESTION?KIND_REQ.QUESTION:KIND_REQ.FIX; saveDraftSoon();
  $$('#c-kind button').forEach(b=>{const on=b.dataset.kind===KIND_NEW; b.classList.toggle('on',on); b.setAttribute('aria-checked',String(on));});
  $('#note').placeholder=KIND_NEW===KIND_REQ.QUESTION?'무엇이 궁금한지 적어 주세요':'메모: 여기를 어떻게 고칠지 (비워도 됩니다)'; renderAssignNew(); qHint($('#c-qhint'),$('#note').value,KIND_NEW);}
// A note that reads like a question (docs/handbook/viewer.md §스레드와 검토 - suggesting the kind). True if it ends in ?/? or a
// Korean interrogative ending (는가/나요/까요/인가/건가/니/냐/까). A trailing period/ellipsis/closing bracket/quote and a
// trailing @-tag (e.g. '맞나요? @Bob Park') are ignored. Only judges - never changes the kind itself.
function looksQuestion(text){let t=String(text||'').trim();
  for(let i=0;i<3;i++)t=t.replace(/[\s.…~!。)\]"'”’]+$/,'').replace(/(?:\s*@[^\s@?？]+(?:\s+[A-Za-z][A-Za-z.'-]*)?)+$/,'');
  return /[?？]$/.test(t)||/(는가|나요|까요|인가|건가|니|냐|까)$/.test(t);}
// If it's a fix request but the note reads like a question, a one-line suggestion appears next to the kind control. Never
// auto-changes it - only changes on click (author feedback 2026-09-25: "...표현한 의도가 있는건가?" got saved as a fix
// request). Disappears once it becomes a question or the text no longer reads like one.
function qHint(box,text,kind){if(box)box.hidden=kind===KIND_REQ.QUESTION||!looksQuestion(text);}
// Drops the current selection and its box (clearNote also empties the note, kind and assignee). No undo here -
// discardSelection() is the user's Esc/[취소], which offers one.
function cancelSelection(clearNote){if(REPICK)cancelRepick(); COMPOSE.current=null; PICKSEQ++; COMPOSE.picking=false; clearPendingSave(); if(COMPOSE.box){COMPOSE.box.remove();COMPOSE.box=null;} saveDraftSoon();
  COMPOSE.dismissedOverlap=null; setBusy(false); $('#composer').hidden=true; if(clearNote){$('#note').value=''; $('#note')._mentions=null; ASSIGN_NEW.touched=false; mentionPreview($('#note')); setKind(KIND_REQ.FIX);}
  if(!REPICK)setSelMode(false); if(LAYOUT===LAYOUT_MODE.NARROW&&!EDITOR.current)setSide(false); applySide();}
// What a discarded or saved selection needs to come back (restoreSelection): the pick (COMPOSE.current), its box on the page, the note with its
// @-tag hints, the kind and the assignee choice, and the document/build the box belongs to. null when there is no selection.
function selectionSnapshot(){if(!COMPOSE.current&&!COMPOSE.picking&&$('#composer').hidden)return null; const n=$('#note');
  return {cur:COMPOSE.current,box:COMPOSE.box,page:COMPOSE.box&&COMPOSE.box.parentNode,note:n.value,mentions:n._mentions||null,kind:KIND_NEW,
    assign:{v:ASSIGN_NEW.v,touched:ASSIGN_NEW.touched},doc:DOC,build:META&&META.pages_build};}
// Brings a snapshot back - the undo of a discard or of a save: the note, kind and assignee always; the selection, its box and the
// composer when they still belong to the pages on screen (same document and build; the box if its page is still there). Never over
// a newer selection - that one wins.
// Returns whether anything came back.
function restoreSelection(snap){if(!snap||COMPOSE.current||COMPOSE.picking||REPICK||!$('#composer').hidden)return false;
  const n=$('#note'); if(n.value)return false;   // a note-only draft also belongs to the current document
  n.value=snap.note; n._mentions=snap.mentions; setKind(snap.kind); Object.assign(ASSIGN_NEW,snap.assign);
  renderAssignNew(); mentionPreview(n); autoGrow(n);
  if(!(snap.cur&&snap.doc===DOC&&META&&snap.build===META.pages_build)){toast('메모만 되살렸습니다 — PDF가 바뀌어 자리를 다시 골라야 합니다','warn'); return true;}
  if(COMPOSE.box)COMPOSE.box.remove(); COMPOSE.box=null;
  if(snap.box&&snap.page&&document.contains(snap.page)){COMPOSE.box=snap.box; snap.page.appendChild(snap.box);}
  COMPOSE.current=snap.cur; recomputeOverlap(); SNIP_OPEN=false; $('#c-err').hidden=true; $('#c-body').hidden=false; $('#composer').hidden=false;
  renderComposer(); setSide(true); applySide(); if(LAYOUT!==LAYOUT_MODE.WIDE)revealBox(COMPOSE.box); if(LAST_PTR==='mouse')n.focus({preventScroll:true});
  return true;}
// Esc and [취소] on a selection (docs/handbook/viewer.md §패널 정리): it goes at once, and when its note had text the toast offers
// [되돌리기] for its 6 seconds, bringing back the selection, the note and the box - an undo instead of a confirmation. The stored
// draft stays for that window (a page left meanwhile still restores it) and is removed when the toast goes.
function discardSelection(){syncDraft(); const snap=selectionSnapshot(); cancelSelection(true);
  if(!(snap&&snap.cur&&snap.note.trim())){syncDraft(); return;}
  const t=toast('선택 취소됨','ok',{label:'되돌리기',tip:'선택과 메모를 되살립니다',fn:()=>restoreSelection(snap)});
  if(t)holdDraftUntil(t);}   // the kept draft goes when the window does
