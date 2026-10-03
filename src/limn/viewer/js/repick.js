// ------------------------------------------------ Re-place location
function banner(markup){const b=$('#banner'); b.innerHTML=markup; b.hidden=false;}
function bannerRepick(err){banner('<span>'+esc(tl('핀 #{id} 의 새 위치를 PDF에서 드래그하세요 · Esc 취소',{id:REPICK.id}))+'</span>'+
  (err?'<span class="errline" style="margin:0">'+esc(err)+'</span>':'')+'<span class="sp"></span>'+
  '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');}
// The re-place banner compares the current and the new place; on a figure the '새 위치' box snaps to the new element. A
// candidate of the other shape (a region for a line pin, lines for a region pin) is dropped and the banner asks for
// another drag: /edit never changes a pin's shape, so no request it would refuse is offered.
function bannerCompare(){const c=REPICK.cand,lv=lvOf(c,c.default_level)||c,rg=isRegion(c);
  if(rg!==!!REPICK.from.region){REPICK.cand=null; bannerRepick(tr(T.shape)); return;}
  banner('<span class="loc" data-tip="지금 위치 → 새 위치" tabindex="0">'+esc(rg?tl('지금 쪽 {from} · 새 쪽 {to} 영역',{from:REPICK.from.page,to:c.page}):tl('지금 {from} · 새 {to}',{from:'L'+REPICK.from.lo+'-L'+REPICK.from.hi,to:'L'+lv.lo+'-L'+lv.hi}))+'</span>'+
    '<span class="dim">('+esc(rg?(c.quote?String(c.quote).slice(0,40):tr('글자 없는 영역')):(lv.label?levelLabel(lv.label):scopeLabel(c)))+')</span><span class="sp"></span>'+
    '<button class="btn-sm btn-default" data-act="rp-apply" data-tip="번호와 메모는 그대로 두고 위치만 바꿉니다">이 위치로 바꾸기</button>'+
    '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');
  snapBox(REPICK.box,repickEl(c));}
// On touch, selection mode is turned on during a re-place, and narrow collapses the sheet to reveal the page (the banner stays visible even on the collapsed sheet).
async function startRepick(){if(!EDITOR.current)return;
  if(EDITOR.current.doc&&EDITOR.current.doc!==DOC){const E=EDITOR.current,opening=switchDoc(E.doc),visit=SWITCHSEQ;
    await opening; if(DOC!==E.doc||EDITOR.current!==E||visit!==SWITCHSEQ)return;}   // selection happens on that pin's document
  // Repick clears an unfinished drag or error panel; a completed selection remains available if repick is cancelled.
  if(COMPOSE.picking||(!COMPOSE.current&&!$('#composer').hidden))cancelSelection(false);
  if(REPICK)cancelRepick();
  REPICK={id:EDITOR.current.id,from:{lo:EDITOR.current.lo,hi:EDITOR.current.hi,page:EDITOR.current.page,region:!!EDITOR.current.region},box:null,cand:null}; bannerRepick();
  if(MQ_COARSE.matches)setSelMode(true); if(LAYOUT===LAYOUT_MODE.NARROW)setSide(false);}
// Cancelling also invalidates an in-flight /api/pick; its continuation must not render a banner for the cleared re-place.
function cancelRepick(){const was=!!REPICK; if(was)PICKSEQ++; if(REPICK&&REPICK.box)REPICK.box.remove(); REPICK=null; $('#banner').hidden=true;
  if(was){if(!COMPOSE.current)setSelMode(false); if(EDITOR.current&&LAYOUT!==LAYOUT_MODE.WIDE)setSide(true);}}
// Sends the re-place candidate as the pin's new location (POST /api/pins/<id>/edit with `loc` and the `base_rev` the editor
// holds). The loc carries the candidate's range, its element and that element's box on a figure, or only the region on a
// view-only page; one without an element drops the pin's el. On 409 it keeps the editor's rev current and reloads the pins;
// on success it syncs the open editor with the stored pin. Does nothing without a candidate.
async function applyRepick(){const R=REPICK; if(!R||!R.cand)return; const c=R.cand,lv=lvOf(c,c.default_level)||c;
  const visit=captureVisit(),E=EDITOR.current;
  let loc={file:c.file,page:c.page,lo:lv.lo,hi:lv.hi,raw_lo:c.raw_lo,raw_hi:c.raw_hi,via:c.via,score:c.score,frac:c.frac,pdf_build:c.pdf_build||undefined,
    scope:lv.level||null,kind:lv.level?kindFor(lv.level,lv.env):c.kind};
  if(!loc.scope)delete loc.scope;
  if(isRegion(c))loc={page:c.page,frac:c.frac,quote:c.quote,pdf_build:c.pdf_build||undefined};   // view-only: only the region is re-placed
  figureFields(loc,repickEl(c),isRegion(c)||!lv.el?null:lv);   // a new loc names its element or none: a loc without el drops the pin's el
  const base=EDITOR.current&&EDITOR.current.id===R.id?EDITOR.current.base_rev:0;
  try{const {status,data}=await api('/api/pins/'+R.id+'/edit',{method:'POST',body:{loc,base_rev:base},what:'위치 바꾸기',expect:[409]});
    if(status===409){toast(data&&data.error===PIN_STATE.DONE?'닫힌 핀은 위치를 바꿀 수 없습니다':'다른 쪽이 이 핀을 먼저 바꿨습니다 — 최신 값을 불러왔습니다','warn');
      if(EDITOR.current===E&&E&&data.pin)E.base_rev=data.pin.rev;
      if(currentVisit(visit)&&REPICK===R)cancelRepick();
      await loadPins(); return;}
    const p=data.pin;
    if(currentVisit(visit)&&REPICK===R)cancelRepick();
    if(EDITOR.current===E&&E&&E.id===p.id){Object.assign(E,{base_rev:p.rev,lo:p.lo,hi:p.hi,file:p.file,name:p.name,scope:p.scope||null,page:pinPlace(p).page,quote:p.quote||'',pinEl:p.el||null});
      E.orig.lo=p.lo;E.orig.hi=p.hi;E.orig.scope=p.scope||null; editSnip(true);}
    toast(tl('핀 #{id} 위치를 {where} 로 바꿨습니다',{id:p.id,where:isRegion(p)?tl('쪽 {page} 영역',{page:pinPlace(p).page}):'L'+p.lo+'-L'+p.hi}),'ok'); await loadPins();
  }catch(e){}}
