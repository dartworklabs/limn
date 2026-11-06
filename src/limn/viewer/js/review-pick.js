// ------------------------------------------------ Confirming several pins awaiting review from their result rows (ADR-0035)
// The review section's [골라서 확인] (#review-pick) turns its cards into result rows: a box with #N and the place, the
// badges, what was asked and what the agent answered (reply, reference, changed lines), and [변경 보기]. A person ticks the
// rows whose result they have read and confirms them together with [N건 확인] in the section head's second line (#rv-bar).
// Each confirm is the one-pin route with the done_at the row showed when it was ticked, so a pin closed again since is
// refused (409 conflict) instead of confirmed (ADR-0013). docs/handbook/viewer.md §스레드와 검토 has the rules.

// The ticked rows while the review section picks: pin id -> the done_at its row showed when it was ticked ('' for a close
// with none). null while the section shows cards.
let RV_PICK=/** @type {Map<number,string>|null} */(null);

// Whether pin p's row shows a result a person can have read: the agent's reply or the lines it changed. A row without one
// cannot be ticked - that pin is confirmed from its card (ADR-0035 D2). Pure.
/** @param {Pin} p @returns {boolean} */
function rvShowsResult(p){return !!String(p.close_reply||'').trim()||(Array.isArray(p.changes)&&p.changes.length>0);}

// The changed lines of p's close, short: '바뀐 줄 L33-L35', with the file's name first when the first range is in another
// file than the pin's, and '+N' for the ranges after it. '' when the close names none. Pure.
/** @param {Pin} p @returns {string} */
function rvChanged(p){const c=Array.isArray(p.changes)?p.changes:[]; if(!c.length)return '';
  const f=c[0],own=String(p.file||''),other=own&&f.file!==own?String(f.file||'').split('/').pop()+' ':'';
  return tl('바뀐 줄 {at}',{at:other+rng(f.lo,f.hi)})+(c.length>1?' +'+(c.length-1):'');}

// Whether the review section may pick now: a person who may confirm, two or more listed pins and one row with a result.
/** @param {Pin[]} list the review pins the section lists @returns {boolean} */
function rvCanPick(list){return canConfirmReview()&&list.length>=2&&list.some(rvShowsResult);}

// One result row of pin p (the review section while it picks). Its box is named by its head line (#N · place · page) and
// described by its answer line; a row with no result has its box disabled and says where to confirm it instead.
/** @param {Pin} p @returns {Html} */
function rvRow(p){const ok=rvShowsResult(p),on=!!RV_PICK&&RV_PICK.has(p.id),first=String(p.note||'').split('\n')[0].trim();
  const at=pinPlace(p).page,page=typeof at==='number'&&!isMdPin(p)?tl('{page}쪽',{page:at}):'';
  const tags=[verdictBadge(p),verdictOldMarker(p),verdictTarget(p),
    isQuestion(p)?html`<span class="badge badge-question" data-tip="${T.question}">${ic('circle-question-mark')}${tr('질문')}</span>`:null,
    suggestBadge(p,true)].filter(t=>!!t&&String(t)!=='');
  const ask=first?fmtText(first,p.mentions):html`<span class="dim">${tr(p.suggest?'(제안 문안만)':verdictOf(p)?'(판정만)':'(메모 없음)')}</span>`;
  const facts=[p.close_ref?String(p.close_ref):'',rvChanged(p)].filter(Boolean).join(' · ');
  const ans=ok?html`${p.close_reply?html`<span translate="no">${fmtText(String(p.close_reply).trim(),p.mentions)}</span>`:html`<span class="dim">${tr('답 없음')}</span>`}\
${facts?html`<span class="rv-facts" translate="no"> · ${facts}</span>`:''}`
    :html`${tr('설명 없이 닫혀 결과가 목록에 없습니다 — 카드에서 하나씩 확인하세요')}`;
  return html`<div class="rv-row${on?' on':''}${ok?'':' off'}" data-id="${p.id}" data-doc="${pdoc(p)}">\
<div class="rv-l1"><label class="rv-ck"><span class="ck"><input type="checkbox" data-pick="${p.id}"${on?' checked':''}${ok?'':' disabled'} aria-describedby="rv-a-${p.id}">\
${ic('check')}${ic('minus')}</span><span class="rv-h"><span class="rv-no">#${p.id}</span> · ${locText(p)}${page?' · '+page:''}</span>${docChip(p)}</label>\
<button type="button" class="btn-sm btn-secondary rv-chg hit" data-act="change" data-tip="${T.change}">${tr('변경 보기')}</button></div>\
<div class="rv-body">${tags.length?html`<div class="rv-tags">${tags}</div>`:''}\
<span class="rv-k">${tr('요청')}</span><span class="rv-ask" translate="no">${ask}</span>\
<span class="rv-k">${tr('답')}</span><span class="rv-ans" id="rv-a-${p.id}">${ans}</span></div></div>`;}

// The head's second line while the section picks: [모두 고르기 (N)] (half-ticked while some are), how many are ticked and
// [N건 확인]. Hidden while it does not pick.
/** @param {Pin[]} list the review pins the section lists */
function rvBar(list){const bar=$('#rv-bar'); bar.hidden=!RV_PICK; if(!RV_PICK){bar.replaceChildren(); return;}
  const can=list.filter(rvShowsResult),n=can.filter(p=>!!RV_PICK&&RV_PICK.has(p.id)).length,all=n>0&&n===can.length;
  setHtml(bar,html`<label class="rv-all"><span class="ck"><input type="checkbox" id="rv-all"${all?' checked':''}>${ic('check')}${ic('minus')}</span>\
<span class="lbl">${tl('모두 고르기 ({n})',{n:can.length})}</span></label>\
<span class="rv-cnt" id="rv-cnt" aria-live="polite">${tl('{n}건 고름',{n})}</span><span class="sp"></span>\
<button type="button" class="btn-sm btn-default rv-go" id="rv-go" data-act="rv-go"${n?'':' disabled'} data-tip="${tr('고른 핀을 각 줄이 보인 결과로 확인합니다. 6초 안에 되돌릴 수 있습니다')}">${n?tl('{n}건 확인',{n}):tr('확인')}</button>`);
  /** @type {HTMLInputElement} */($('#rv-all')).indeterminate=n>0&&!all;}

// What has the focus in the picking section, as a selector a redraw can find it by again: a row's box or [변경 보기] (by its
// pin), or one of the bar's controls (by its id). null when the focus is elsewhere.
/** @returns {string|null} */
function rvFocusKeep(){const a=/** @type {HTMLElement|null} */(document.activeElement); if(!a||!a.closest)return null;
  const row=/** @type {HTMLElement|null} */(a.closest('.rv-row[data-id]')),at=row?'.rv-row[data-id="'+row.dataset.id+'"] ':'';
  if(row&&a.matches('input[data-pick]'))return at+'input[data-pick]';
  if(row&&a.dataset.act)return at+'[data-act="'+CSS.escape(a.dataset.act)+'"]';
  return a.closest('#rv-bar')&&a.id?'#'+CSS.escape(a.id):null;}
// Gives the focus back after a redraw to what rvFocusKeep found (sel), or - that gone or disabled - to [골라서 확인], else to
// the section's toggle. Only when the redraw dropped the focus to the page.
/** @param {string|null} sel */
function rvFocusBack(sel){const a=document.activeElement; if(!sel||(a&&a!==document.body))return;
  const el=/** @type {HTMLElement|null} */(document.querySelector(sel)),pick=/** @type {HTMLElement} */($('#review-pick'));
  const to=el&&!/** @type {HTMLInputElement} */(el).disabled?el:!pick.hidden?pick:/** @type {HTMLElement} */($('#review-toggle'));
  to.focus({preventScroll:true});}

// Draws the review section's rows while it picks, and its head's button and bar either way; drawPins calls it with the pins
// the section lists. A pick that can no longer be (one pin left, no row with a result, no right to confirm) or whose rows
// are folded away (the section collapsed) ends here, and a tick on a pin that left the list or lost its result goes.
// Returns whether it drew rows (else drawPins draws the cards).
/** @param {Pin[]} list @returns {boolean} */
function rvDraw(list){const can=rvCanPick(list),keep=RV_PICK?rvFocusKeep():null;
  if(RV_PICK&&(!can||!SEC.review)){RV_PICK=null; if(keep)/** @type {HTMLElement} */($('#review-toggle')).focus({preventScroll:true});}   // the cards drawn next hold no focus
  if(RV_PICK){const listed=new Map(list.map(p=>[p.id,p]));
    for(const id of [...RV_PICK.keys()]){const p=listed.get(id); if(!p||!rvShowsResult(p))RV_PICK.delete(id);}}
  const b=/** @type {HTMLElement} */($('#review-pick')); b.hidden=!can;
  b.setAttribute('aria-pressed',String(!!RV_PICK)); b.textContent=tr(RV_PICK?'고르기 끝':'골라서 확인');
  $('#sec-review').classList.toggle('rv-picking',!!RV_PICK);
  rvBar(list);
  if(RV_PICK)setHtml($('#review-pins'),html`${orderPins(list,ORDER).map(rvRow)}`);
  rvFocusBack(keep); return !!RV_PICK;}

// Starts (on) or ends picking. Starting opens a collapsed section (and keeps it open, as [검토 M] does), brings the section
// to the top of the list and gives the focus to [모두 고르기]; ending gives it back to [골라서 확인].
/** @param {boolean} on */
function rvPick(on){RV_PICK=on?new Map():null; if(on&&!SEC.review){SEC.review=true; savePrefs({sec:SEC});} drawPins();
  if(on)$('#sec-review').scrollIntoView({block:'start'});   // the section, not its head: a stuck head is where it is shown already and would not scroll
  const f=/** @type {HTMLElement|null} */(on?$('#rv-all'):$('#review-pick')); if(f&&f.getClientRects().length)f.focus({preventScroll:true});}

// A box was ticked or cleared: a row's records the done_at its row shows now (ADR-0035 D3); [모두 고르기] ticks every row with
// a result the section lists, or clears them.
/** @param {HTMLInputElement} box */
function rvTick(box){if(!RV_PICK)return; const list=listReviewShown();
  if(box.id==='rv-all'){RV_PICK=new Map(box.checked?list.filter(rvShowsResult).map(p=>[p.id,String(p.done_at||'')]):[]);}
  else{const id=Number(box.dataset.pick),p=list.find(q=>q.id===id); if(!p)return;
    if(box.checked)RV_PICK.set(id,String(p.done_at||'')); else RV_PICK.delete(id);}
  drawPins();}

// The review pins the section lists now - the same filter drawPins uses ([나를 부른 핀], else the document or [모든 문서]).
/** @returns {Pin[]} */
function listReviewShown(){return MENTION_ONLY?REVIEW_ALL.filter(mentionsMe):listReview();}

// [N건 확인]: the ticked pins leave the section at once and picking ends; one undo row stands at the section's top for
// NOTICE_MS and gets the focus. When it goes (or the page is hidden) every confirm is sent at once (rvSend); its [되돌리기]
// sends nothing and puts the pins and their ticks back.
function rvConfirm(){if(!RV_PICK)return;
  const items=[...RV_PICK].map(([id,at])=>{const pin=REVIEW_ALL.find(p=>p.id===id); return pin&&!CONFIRMING.has(id)?{pin,at}:null;})
    .filter(x=>!!x).map(x=>/** @type {{pin:Pin,at:string}} */(x));
  if(!items.length)return;
  const where=new Map(items.map(x=>[x.pin.id,REVIEW_ALL.indexOf(x.pin)])),ticks=new Map(items.map(x=>[x.pin.id,x.at]));
  for(const {pin} of items){CONFIRMING.add(pin.id); CONFIRMING_PIN.set(pin.id,pin);}
  REVIEW_ALL=REVIEW_ALL.filter(p=>!where.has(p.id)); RV_PICK=null; drawPins(); marks();
  const d=deferred(()=>{rvSend(items);},()=>rvUndo(items,where,ticks));
  const n=deferredNote(d,NOTICE_PLACE.ROW,tl('핀 {n}건 확인 · 완료로 옮겼습니다',{n:items.length}),{sec:'review',prev:null,rec:null});
  const u=/** @type {HTMLElement|null} */(n.el&&n.el.querySelector('.nt-act'));
  if(u&&document.contains(u))u.focus({preventScroll:true}); else /** @type {HTMLElement} */($('#review-toggle')).focus({preventScroll:true});}

// The undo of [N건 확인]: each pin comes back as the latest list has it (CONFIRMING_PIN) at the place it had, and the
// section picks again with the same ticks, the focus on [N건 확인] (its undo row, which had it, is gone). A pin gone from
// that list meanwhile is not brought back; one deleted elsewhere is said so.
/** @param {{pin:Pin,at:string}[]} items @param {Map<number,number>} where @param {Map<number,string>} ticks */
function rvUndo(items,where,ticks){const back=[],lost=[];
  for(const {pin} of items){const now=CONFIRMING_PIN.get(pin.id); CONFIRMING.delete(pin.id); CONFIRMING_PIN.delete(pin.id);
    if(now&&!REVIEW_ALL.some(p=>p.id===pin.id))back.push(now);
    else if(!now&&![OPEN_ALL,REVIEW_ALL,DONE_ALL].some(l=>l.some(p=>p.id===pin.id)))lost.push(pin.id);}
  back.sort((a,b)=>(where.get(a.id)||0)-(where.get(b.id)||0));
  for(const p of back){const i=Math.min(where.get(p.id)||0,REVIEW_ALL.length); REVIEW_ALL=[...REVIEW_ALL.slice(0,i),p,...REVIEW_ALL.slice(i)];}
  RV_PICK=new Map(back.map(p=>[p.id,ticks.get(p.id)||''])); drawPins(); marks();
  const to=/** @type {HTMLElement|null} */(RV_PICK?$('#rv-go'):$('#review-pick'));   // the undo row that had the focus is gone
  if(to&&to.getClientRects().length&&!/** @type {HTMLButtonElement} */(to).disabled)to.focus({preventScroll:true});
  if(lost.length)lineNote(tl('핀 {ids} 은 그사이 다른 곳에서 지워졌습니다',{ids:lost.map(i=>'#'+i).join(', ')}),NOTICE_KIND.WARN);}

// What the server did with one confirm. CLOSED_AGAIN: closed again since the row was ticked (409 conflict, still awaiting
// review); DONE_BY_PERSON: closed straight to done meanwhile (409 conflict, done); REOPENED: reopened (409 open); GONE: no
// such pin (200 ok:false); REFUSED: any other refusal (its text); UNREACHED: no answer - the only one [다시 시도] sends again.
const RV_OUT=Object.freeze({OK:'ok',CLOSED_AGAIN:'closed-again',DONE_BY_PERSON:'done',REOPENED:'reopened',GONE:'gone',REFUSED:'refused',UNREACHED:'unreached'});
// The outcome of one confirm from its answer: status and body of an answered request (409 expected), or the error api()
// threw (an ApiError with a status for a refusal, none when the server was not reached). Pure.
/** @param {{status:number,data:any}|null} r @param {ApiError|null} [err] @returns {{out:string,why?:string}} */
function rvOutcome(r,err){if(err)return err.status?{out:RV_OUT.REFUSED,why:errText(err.data)||'HTTP '+err.status}:{out:RV_OUT.UNREACHED};
  const d=r&&r.data;
  if(d&&d.error===PIN_STATE.OPEN)return {out:RV_OUT.REOPENED};
  if(d&&d.error==='conflict')return {out:d.pin&&pinState(d.pin)!==PIN_STATE.REVIEW?RV_OUT.DONE_BY_PERSON:RV_OUT.CLOSED_AGAIN};
  return d&&d.ok?{out:RV_OUT.OK}:{out:RV_OUT.GONE};}

// Sends the confirms of items all at once (each with the done_at its row showed when ticked; keepalive, so a page being
// closed sends them all) and says what came of them: all done is said quietly; anything refused is one banner on top of
// the review section that names each pin with why (rvSaid). Then the list is read again.
/** @param {{pin:Pin,at:string}[]} items */
async function rvSend(items){
  const outs=await Promise.all(items.map(({pin,at})=>api('/api/pins/'+pin.id+'/confirm',{method:'POST',silent:true,expect:[409],keepalive:true,body:at?{done_at:at}:{}})
    .then(r=>rvOutcome(r),e=>rvOutcome(null,/** @type {ApiError} */(e)))));
  outs.forEach((o,i)=>{if(o.out===RV_OUT.OK)markMine(items[i].pin.id);});
  for(const {pin} of items){CONFIRMING.delete(pin.id); CONFIRMING_PIN.delete(pin.id);}
  await loadPins();
  const said=rvSaid(items.map((x,i)=>({id:x.pin.id,...outs[i]})));
  if(!said){quietNote(tl('핀 {n}건 확인했습니다',{n:items.length})); return;}
  const again=items.filter((x,i)=>outs[i].out===RV_OUT.UNREACHED),first=items.find((x,i)=>outs[i].out===RV_OUT.CLOSED_AGAIN);
  const act=again.length?{label:'다시 시도',tip:tr('서버에 닿지 않은 핀만 같은 결과로 다시 보냅니다'),fn:()=>rvRetry(again)}
    :first?{label:'변경 보기',tip:T.change,fn:()=>showChange(first.pin.id)}:null;
  bannerNote(NOTICE_HOST.REVIEW,said.msg,said.kind,act,{literal:true});}

// The banner for a send whose confirms did not all go through, or null when they did: 'N건 중 K건 확인 — ' and, per kind,
// the pins and why, joined by ' · '. ERR when a pin did not reach the server, WARN when one was closed again, reopened,
// gone or refused, INFO when the rest were only done by a person meanwhile. Pure.
/** @param {{id:number,out:string,why?:string}[]} res @returns {{msg:string,kind:string}|null} */
function rvSaid(res){const of=(/** @type {string} */k)=>res.filter(r=>r.out===k),ids=(/** @type {{id:number}[]} */l)=>l.map(r=>'#'+r.id).join(', ');
  const ok=of(RV_OUT.OK).length; if(ok===res.length)return null;
  const refused=of(RV_OUT.REFUSED),why=[
    [RV_OUT.CLOSED_AGAIN,'{ids} 다시 닫힘 — 새 결과를 보고 확인하세요'],[RV_OUT.REOPENED,'{ids} 그사이 다시 열림'],
    [RV_OUT.DONE_BY_PERSON,'{ids} 이미 완료로 닫힘'],[RV_OUT.GONE,'{ids} 지워짐'],[RV_OUT.UNREACHED,'{ids} 서버에 닿지 않아 보내지 못함']]
    .map(([k,t])=>{const l=of(k); return l.length?tl(t,{ids:ids(l)}):'';}).filter(Boolean);
  for(const r of refused)why.push(tl('#{id} 거절됨: {why}',{id:r.id,why:r.why||''}));
  const kind=of(RV_OUT.UNREACHED).length?NOTICE_KIND.ERR:res.every(r=>r.out===RV_OUT.OK||r.out===RV_OUT.DONE_BY_PERSON)?NOTICE_KIND.INFO:NOTICE_KIND.WARN;
  return {msg:tl('{n}건 중 {k}건 확인',{n:res.length,k:ok})+' — '+why.join(' · '),kind};}

// [다시 시도]: the pins that did not reach the server, sent again at once with the same done_at - no second undo. A pin
// confirmed or sent again meanwhile is left out.
/** @param {{pin:Pin,at:string}[]} items */
function rvRetry(items){const still=items.filter(x=>!CONFIRMING.has(x.pin.id)&&REVIEW_ALL.some(p=>p.id===x.pin.id)); if(!still.length)return;
  for(const {pin} of still){CONFIRMING.add(pin.id); CONFIRMING_PIN.set(pin.id,pin);}
  REVIEW_ALL=REVIEW_ALL.filter(p=>!CONFIRMING.has(p.id)); drawPins(); marks(); rvSend(still);}

// Esc while the focus is in the picking section ends picking. Listened in the capture phase, before the page's own Esc
// (events.js), which would close the panel or the sheet the section is in.
/** @param {KeyboardEvent} e */
function rvEscape(e){if(e.key!=='Escape'||!RV_PICK||e.isComposing)return; const a=document.activeElement;
  if(!a||!a.closest||!a.closest('#sec-review'))return; e.preventDefault(); e.stopPropagation(); rvPick(false);}
document.addEventListener('keydown',rvEscape,true);
// A box's change (a click on it or its label, Space on it) ticks or clears it.
/** @param {Event} e */
function rvChange(e){const t=/** @type {HTMLInputElement} */(e.target);
  if(t&&t.type==='checkbox'&&t.closest&&t.closest('#sec-review'))rvTick(t);}
document.addEventListener('change',rvChange);
