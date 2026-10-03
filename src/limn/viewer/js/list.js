// ------------------------------------------------ Pin list: loading pins, list sections, marks on the PDF, jumping to a pin or card
// If the people list changes (a new person/name), the list is redrawn - the very first render can show a login instead of a name.
async function loadPeople(){try{const r=(await api('/api/people',{what:'사람 목록',silent:true})).data;
  if(Array.isArray(r.people)){const was=JSON.stringify(PEOPLE); PEOPLE=r.people; if(JSON.stringify(PEOPLE)!==was)drawPins();}}catch(e){}}
// A refresh that started earlier must not replace one already applied from a newer request. A failed request claims no snapshot.
let PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0;
// Classifies one server snapshot without reading viewer state or changing the page. Legacy pins with no doc belong to defaultDoc.
// confirming (optional) holds the ids whose [확인] waits for its undo toast (CONFIRMING): they stay out of the review list.
function derivePinLists(rows,doc,defaultDoc,confirming){
  const openAll=[],reviewAll=[],doneAll=[],openHere=[],doneHere=[];
  for(const pin of rows){const state=pinState(pin),here=!doc||(pin.doc||defaultDoc)===doc;
    if(state===PIN_STATE.OPEN){openAll.push(pin); if(here)openHere.push(pin);}
    else if(state===PIN_STATE.REVIEW){if(!(confirming&&confirming.has(pin.id)))reviewAll.push(pin);}
    else if(state===PIN_STATE.DONE){doneAll.push(pin); if(here)doneHere.push(pin);}}
  return {openAll,reviewAll,doneAll,openHere,doneHere};
}
// Applies an accepted snapshot: announces transitions, keeps active editors honest, then redraws the current document.
function applyPinLists(rows,dropped,lists){
  const prevOpen=OPEN_ALL,prevReview=REVIEW_ALL;
  diffToast(prevOpen,rows,dropped); reviewToast(prevReview,rows);
  OPEN_ALL=lists.openAll; REVIEW_ALL=lists.reviewAll; DONE_ALL=lists.doneAll; DROPPED=dropped;
  PINS=lists.openHere; DONE=lists.doneHere;
  if(EDITOR.current&&!OPEN_ALL.some(p=>p.id===EDITOR.current.id)){toast(tl('편집 중이던 핀 #{id} 이 목록에서 빠졌습니다(다른 쪽에서 닫았거나 지움)',{id:EDITOR.current.id}),'warn'); EDITOR.current=null;}
  if(REPLY&&!rows.some(p=>p.id===REPLY.id)){closeReply(false); toast('답글을 쓰던 핀이 목록에서 빠졌습니다(지워짐) — 쓰던 글은 남겨 둡니다','warn');}
  if(!SEC_SEEN.open){SEC_SEEN.open=new Set(OPEN_ALL.map(p=>p.id)); SEC_SEEN.review=new Set(REVIEW_ALL.map(p=>p.id)); SEC_SEEN.done=new Set(DONE_ALL.map(p=>p.id));}
  drawPins(); marks(); drawDocTabs();
  if(COMPOSE.current){recomputeOverlap(); renderOverlapBanner();}   // if the list changes (someone else's save/completion), overlap is recomputed too
  docTitle(true);
}
// Fetches one pin snapshot and its Trash. Returns whether it applied; only a newer applied snapshot supersedes it.
async function loadPins(){const seq=++PINS_LOAD_SEQ; let d;
  try{d=(await api('/api/pins?all=1',{what:'핀 읽기'})).data;}catch(e){return false;}
  if(seq<PINS_APPLIED_SEQ)return false;
  let dropped=[];
  try{dropped=(await api('/api/pins/dropped',{what:'삭제한 핀',silent:true})).data.dropped||[];}catch(e){return false;}
  if(seq<PINS_APPLIED_SEQ)return false;
  loadPeople();
  // All-document lists drive notices; only the current document's open and done pins drive its marks and rows.
  applyPinLists(d,dropped,derivePinLists(d,DOC,DEFAULT_DOC,CONFIRMING));
  PINS_APPLIED_SEQ=seq;
  return true;
}
// The list drawn in the sidebar: the current document by default, everything if 'all documents'. A pin being edited is kept even from another document (so the draft text doesn't disappear).
function listOpen(){return SHOW_ALL&&multiDoc()?OPEN_ALL:OPEN_ALL.filter(p=>pdoc(p)===DOC||!DOC||(EDITOR.current&&EDITOR.current.id===p.id));}
function listDone(){return SHOW_ALL&&multiDoc()?DONE_ALL:DONE;}
function listReview(){return SHOW_ALL&&multiDoc()?REVIEW_ALL:REVIEW_ALL.filter(p=>pdoc(p)===DOC||!DOC);}
// Awaiting-review count: counted across documents (the inbox of work for a person to confirm). The purple number next to [핀 N] (compact) / the tool bar chip (wide).
// The phone and tablet sheet bar's left cell steps down until [핀 N | 검토 M] and [⬚] fit it (English, three-digit counts,
// a folded cover): first the chip's halves pad one 4px step less and the cell's gap is 4px (#bar1.bar-snug); then the words
// '핀' and '검토' give way to a dot each - green for the open pins, purple for those awaiting review (#bar1.bar-tight) - so a
// count never stands alone. Measured each time a count or the band changes; decoration only - nothing moves.
function fitBarWords(){const b=$('#bar1'),l=b.querySelector('.bar-l'); b.classList.remove('bar-snug','bar-tight'); if(LAYOUT!==LAYOUT_MODE.NARROW)return;
  const over=()=>{const k=[...l.children].filter(e=>e.getClientRects().length);   // the last control's edge, not scrollWidth: the hits overflow too
    return k.length>0&&k[k.length-1].getBoundingClientRect().right>l.getBoundingClientRect().right+0.05;};   // past the cell, [⬚]'s hit reaches the grabber's column
  for(const step of ['bar-snug','bar-tight']){if(!over())return; b.classList.add(step);}}
// The pill rides on both [핀 N] toggles (the tool bar's and the collapsed wide nav bar's); the phone and tablet sheet's bar shows
// the count as its own half [검토 M] (#btn-rv) instead; the chip is the open wide panel's.
// The pill is the eye icon and the count, so it never reads as part of the open count beside it ('11 1', UX audit P10).
function updateReviewCount(){const n=REVIEW_ALL.length,chip=$('#rv-chip');
  for(const pill of $$('#btn-side .rv-n,#nav-side .rv-n')){pill.hidden=!n; setHtml(pill,html`${ic('eye')}${n}`); pill.setAttribute('aria-label',tl('검토 대기 {n}',{n}));}
  const rb=$('#btn-rv'); rb.hidden=!n; rb.querySelector('.rv-c').textContent=n; rb.setAttribute('aria-label',tl('검토 {n} · 검토 대기 핀으로 가기',{n}));   // the sheet bar's [검토 M] half: its name starts with what it shows
  fitBarWords();
  const here=listReview().length; chip.hidden=!n||LAYOUT!==LAYOUT_MODE.WIDE||!SIDE_OPEN; chip.textContent=tl('검토 대기 {n}',{n})+(multiDoc()&&here!==n?' '+tl('(이 문서 {n})',{n:here}):'');}
function gotoReview(){if(!listReview().length&&REVIEW_ALL.length&&multiDoc())SHOW_ALL=true;
  if(!SEC.review){SEC.review=true; savePrefs({sec:SEC});} drawPins();
  setSide(true); requestAnimationFrame(()=>{const t=$('#sec-review'); if(t&&!t.hidden)t.scrollIntoView({block:'start',behavior:SMOOTH});});}
// The reviewer shown on an awaiting-review card: the author is suggested (anyone can confirm - a trust model). If I'm the author, '내 확인 차례'.
function isMe(a){const me=META&&META.me; return !!(a&&me&&me.login&&me.login!==LOCAL_LOGIN&&a.login===me.login);}
function reviewerLabel(p){if(!p.author||!(p.author.name||p.author.login))return tr('확인 필요'); return isMe(p.author)?tr('내 확인 차례'):tl('{name}님 확인 필요',{name:who(p.author)});}
function listDropped(){return SHOW_ALL&&multiDoc()?DROPPED:DROPPED.filter(p=>pdoc(p)===DOC||!DOC);}
// One section header (docs/handbook/viewer.md §목록 구획): chevron, name, count and - while collapsed - 'new N' (ids the section did not show
// when it was last expanded). The body it controls (aria-controls) is hidden while collapsed.
const SEC_NAME_ID={open:'list-h',review:'review-h',done:'done-h'};
// ids = the pins this section lists now; all = the section's pins across every document. While expanded, everything is marked seen
// (all, so switching documents never reads as arrivals); SEC_SEEN starts from the first load, so nothing is 'new' at boot.
function secHead(key,name,ids,all){const b=document.getElementById(key+'-toggle'); if(!b)return; const open=!!SEC[key],seen=SEC_SEEN[key];
  if(open&&seen)(all||ids).forEach(id=>seen.add(id));
  const nn=open?0:secNewCount(seen,ids);
  const fresh=nn?html`<span class="sec-new">${tl('새 {n}',{n:nn})}</span>`:'';
  setHtml(b,html`${ic(open?'chevron-down':'chevron-right')}<span class="sec-name" id="${SEC_NAME_ID[key]}">${name} <span class="badge badge-secondary sec-n">${ids.length}</span></span>${fresh}`);
  b.setAttribute('aria-expanded',String(open));
  const body=document.getElementById(b.getAttribute('aria-controls')); if(body)body.hidden=!open;}
function toggleSec(key,force){if(!(key in SEC_DEFAULT))return; SEC[key]=force===undefined?!SEC[key]:!!force; savePrefs({sec:SEC}); drawPins();}
// Redraws the pin panel from the lists (sections, counts, the Trash count, a reply in progress) - and, while the changes view
// shows a pin, its guide line's buttons, whose [확인] follows that pin's state (revTargetActs).
function drawPins(){
  const LIST=listOpen(),LDONE=listDone(),LDROP=listDropped();
  // The '나를 부른 핀' filter: only the open/awaiting-review pins across every document that @-tagged me (a cross-document inbox).
  const MINE=OPEN_ALL.concat(REVIEW_ALL).filter(mentionsMe),mf=$('#mention-filter');
  if(MENTION_ONLY&&!MINE.length)MENTION_ONLY=false;
  mf.hidden=!MINE.length; mf.setAttribute('aria-pressed',String(MENTION_ONLY)); setHtml(mf,html`${ic('at-sign')}${MINE.length}`); mf.setAttribute('aria-label',tl('나를 부른 핀 {n}',{n:MINE.length}));
  const SHOWN=MENTION_ONLY?OPEN_ALL.filter(mentionsMe):LIST;
  // If the cursor was in the reply input field or the edit card's note, it's restored to that position after redrawing (so auto-sync
  // redrawing the list, or a layout change redrawing the cards, never interrupts typing).
  const rta=REPLY&&REPLY.el.querySelector('textarea'),rfocus=rta&&document.activeElement===rta?[rta.selectionStart,rta.selectionEnd]:null;
  const eta=EDITOR.current&&EDITOR.current.el.querySelector('.e-note'),efocus=eta&&document.activeElement===eta?[eta.selectionStart,eta.selectionEnd]:null;
  secHead('open',tr(MENTION_ONLY?'나를 부른 열린 핀':SHOW_ALL&&multiDoc()?'모든 문서의 열린 핀':'열린 핀'),SHOWN.map(p=>p.id),OPEN_ALL.map(p=>p.id));
  const ab=$('#all-docs'); ab.setAttribute('aria-pressed',String(SHOW_ALL)); setHtml(ab,html`${SHOW_ALL?ic('check'):''}${tr('모든 문서')}`);
  $('#side-n').textContent=PINS.length; applySide();
  // In compact, the Trash is a row in [⋯] with its count. On desktop the Trash is the link under the list.
  const nTrash=LDROP.filter(p=>!PURGING.has(p.id)).length;
  $('#m-trash-n').textContent=nTrash; $('#trash-link').textContent=tl('휴지통 {n}',{n:nTrash}); $('#trash-link').hidden=!nTrash;
  $('#empty').hidden=SHOWN.length>0||OPEN_ALL.length>0||REVIEW_ALL.length>0;
  // Empty list: the header's count already says it - a separate '아직 없습니다.' line is never added too (QA). Only a note that another document has pins is left.
  $('#pins').innerHTML=SHOWN.length?SHOWN.map(card).join(''):(multiDoc()&&!SHOW_ALL&&OPEN_ALL.length?'<div class="dim list-empty">'+esc(tl('이 문서에는 없습니다 · 다른 문서에 {n}건',{n:OPEN_ALL.length}))+'</div>':'');
  if(EDITOR.current){const slot=$('#pins .edit-slot'); if(slot)slot.replaceWith(EDITOR.current.el);
    if(efocus&&document.contains(eta)){eta.focus(); try{eta.setSelectionRange(efocus[0],efocus[1]);}catch(e){}}}
  // Awaiting-review section: between open pins and done. Hidden when empty. The card looks the same as an open pin (thread/replies); only the actions are [확인]/[답글].
  const LREV=MENTION_ONLY?REVIEW_ALL.filter(mentionsMe):listReview();
  $('#sec-review').hidden=!LREV.length; secHead('review',tr('검토 대기'),LREV.map(p=>p.id),REVIEW_ALL.map(p=>p.id));
  $('#review-pins').innerHTML=LREV.map(card).join('');
  updateReviewCount();
  // Done section: hidden header and all if empty. The header stays stuck to the top while scrolling.
  $('#sec-done').hidden=!LDONE.length; secHead('done',tr('완료'),LDONE.map(p=>p.id),DONE_ALL.map(p=>p.id));
  if(SEC.done)$('#done-list').innerHTML=LDONE.length?LDONE.slice().reverse().map(doneCard).join(''):'<div class="dim">없습니다.</div>';
  if($('#trash').open)drawTrash();
  if(REPLY){const slot=document.querySelector('#list .reply-slot'); if(slot)slot.replaceWith(REPLY.el); renderReplyOutcome();   // the pin may have changed state meanwhile
    if(rfocus&&document.contains(rta)){rta.focus(); try{rta.setSelectionRange(rfocus[0],rfocus[1]);}catch(e){}}}
  if(REV.target)revTargetActs();
}
// Location estimation (.est, dashed) is judged by the server and carried as est in /api/pins (pin_est - comparing the
// manuscript fingerprint of the build the pin was placed on with the current build). Back when the viewer judged this by
// wall clock, it was wrong across the board with browser timezone, a note-only edited_at, and a pin placed on a stale
// PDF (confirmed by independent verification). The viewer just renders the value it's given.
function isEstimated(p){return p.est===true;}
// Whether a mark's number badge goes inside the mark (docs/handbook/viewer.md §모바일 레이아웃): fx is the mark's left as a
// fraction of the page, w the page width, pad the room left of the page in the PDF scroller (its margin) and reach how far
// the badge hangs left of the mark (28px on touch, 24px with a mouse). Only when the margin and the offset together are
// short of the reach would the badge be clipped, and only then does it sit in the mark's top-left corner - inside, it covers
// the text the mark points at. Pure.
function markBadgeIn(fx,w,pad,reach){return fx*w+pad<reach;}
// The room left of the page in the PDF scroller, in scroll coordinates (a horizontal scroll does not count), and the badge's
// reach for the primary pointer: {pad, reach}.
function markBadgeRoom(){const L=$('#left'),p=$('#doc .pg'); if(!L||!p)return {pad:0,reach:28};
  return {pad:p.getBoundingClientRect().left-L.getBoundingClientRect().left-L.clientLeft+L.scrollLeft,reach:MQ_COARSE.matches?28:24};}
// Re-decides every drawn mark's badge side for the page width W and the margin now (a zoom, a re-fit or a band change moves both).
function markBadgeSides(){const r=markBadgeRoom(); $$('.mark').forEach(m=>m.classList.toggle('in',markBadgeIn(+m.dataset.fx,W,r.pad,r.reach)));
  $$('.sel.pending').forEach(pendingBadgeSide);}   // the pending boxes' '+' badges follow the same rule
// Draws one mark per open or awaiting-review pin of this document on its page: where the pin's element is now for a figure
// pin (pinPlace), else where it was pinned, then decides each badge's side (markBadgeSides). A pin without a usable box or
// page draws nothing.
function marks(){
  $$('.mark').forEach(m=>m.remove());
  // Awaiting-review pins are also drawn as purple marks - so the reviewer can see right there what was fixed (unrelated to an open pin's overlap/editing).
  // A figure pin is drawn where the server found its element in this build (see pinPlace), and a found element is no estimate.
  PINS.concat(REVIEW_ALL.filter(p=>pdoc(p)===DOC)).forEach(p=>{const at=pinPlace(p),el=document.getElementById('p'+at.page); if(!el||!isFrac(at.frac))return;
    const est=isEstimated(p)&&!hasMark(p),lost=p.stale||elLost(p);
    const m=document.createElement('div'); m.className='mark'+(lost?' st':'')+(est?' est':'')+(pinState(p)===PIN_STATE.REVIEW?' rv':''); m.dataset.pin=p.id; m.dataset.fx=at.frac[0];
    Object.assign(m.style,{left:at.frac[0]*100+'%',top:at.frac[1]*100+'%',width:at.frac[2]*100+'%',height:at.frac[3]*100+'%'});
    const n=String(p.note||'').replace(/\s+/g,' ').trim();
    const tip='#'+p.id+' · '+(n?(n.length>60?n.slice(0,60)+'…':n):tr('(메모 없음)'))+(est?' '+tr('(PDF가 새로 만들어져 위치는 추정입니다)'):'')+(elLost(p)?' · '+tr('요소 잃음'):'');
    setHtml(m,html`<b translate="no" data-act="mark-jump" data-id="${p.id}" data-tip="${tip}">${p.id}</b>`); el.appendChild(m);});   // the tip carries the note
  markBadgeSides();
}
// Clicking a badge scrolls to and flashes the card (never calls pick). The mark box itself has pointer-events:none, so
// a drag over it still becomes a new selection - only the badge (<b>) needs to block mousedown.
$('#doc').addEventListener('mousedown',e=>{
  if(e.target.closest('.mark b')){e.stopPropagation();e.preventDefault();}
},true);
// Clicking a badge -> scroll to the card + .cur highlight (spec) + a 1.2-second flash. The highlight is never left on -
// it releases; when it was a static box-shadow, it stayed on the card until the next click.
// compact: clicking a badge expands the panel/sheet and that card, then scrolls via jumpToCard.
// Expands the section that holds pin id if it is collapsed (a mark click, a notification, [검토 대기 N]). Returns true if it changed.
function secOpenFor(id){const p=findAnyPin(id); if(!p)return false; const st=pinState(p),key=st===PIN_STATE.REVIEW?'review':st===PIN_STATE.DONE?'done':'open';
  if(SEC[key])return false; SEC[key]=true; savePrefs({sec:SEC}); return true;}
// A mark badge's card: opens its section and the panel (a collapsed one too); compact also expands the card.
function revealCard(id){if(secOpenFor(id))drawPins(); setSide(true); if(LAYOUT===LAYOUT_MODE.WIDE)return;
  if(!OPEN_CARDS.has(id)&&(PINS.some(p=>p.id===id)||REVIEW_ALL.some(p=>p.id===id))){OPEN_CARDS.add(id); drawPins();}}
function jumpToCard(id){if(secOpenFor(id))drawPins();
  const el=document.querySelector('.pin[data-id="'+id+'"]'); if(!el)return;
  el.scrollIntoView({behavior:SMOOTH,block:'nearest'});
  $$('.pin.cur').forEach(x=>{if(x!==el)x.classList.remove('cur');});
  clearTimeout(el._curT);
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('cur','flash');
  el._curT=setTimeout(()=>el.classList.remove('cur','flash'),1200);
}
// A '#12' link in text: expands and scrolls to that pin's card/archive row, then flashes it. If it's on another document, '모든 문서' is turned on.
function gotoPinRef(id){const p=findAnyPin(id); if(!p){if(DROPPED.some(x=>x.id===id))openTrash(id); return;}
  const st=pinState(p);
  if(multiDoc()&&DOC&&pdoc(p)!==DOC)SHOW_ALL=true;
  if(st===PIN_STATE.DONE)SEC.done=true; else{OPEN_CARDS.add(id); SEC[st===PIN_STATE.REVIEW?'review':'open']=true;} savePrefs({sec:SEC});
  setSide(true); drawPins();
  requestAnimationFrame(()=>{const el=document.querySelector('.pin[data-id="'+id+'"],.arc-row[data-id="'+id+'"]'); if(!el)return;
    el.scrollIntoView({behavior:SMOOTH,block:'nearest'}); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    clearTimeout(el._flT); el._flT=setTimeout(()=>el.classList.remove('flash'),1200);});}
// Scrolls the mark of pin id into view and flashes it (switching to the pin's document first); a pin whose mark is not drawn
// scrolls to the page the mark would be on.
function jumpPin(id){if(viaDoc(id,jumpPin))return; const p=PINS.find(x=>x.id===id)||REVIEW_ALL.find(x=>x.id===id&&pdoc(x)===DOC);
  if(!p){const q=REVIEW_ALL.find(x=>x.id===id); if(q&&docInfo(pdoc(q))){const k=pdoc(q),opening=switchDoc(k),visit=SWITCHSEQ;
    opening.then(()=>{if(DOC===k&&visit===SWITCHSEQ)jumpPin(id);});} return;}
  if(document.body.classList.contains('revision-open'))setViewMode(VIEW_MODE.MANUSCRIPT);
  if(LAYOUT===LAYOUT_MODE.NARROW)setSide(false);   // collapsed first so the sheet doesn't cover the page, then measured
  const m=document.querySelector('.mark[data-pin="'+id+'"]');
  if(m){
    const L=$('#left'),lr=L.getBoundingClientRect(),mr=m.getBoundingClientRect();
    L.scrollTop+=(mr.top-(lr.top+lr.height*0.30));
    m.classList.remove('flash');void m.offsetWidth;m.classList.add('flash');
  } else {
    const el=document.getElementById('p'+pinPlace(p).page); if(el)el.scrollIntoView({behavior:SMOOTH});
  }
}
// Hovering a card highlights its mark, along with any overlapping counterpart marks.
function markIdsFor(p){return [p.id].concat((p.rel||[]).map(x=>x.id));}
$('#pins').addEventListener('mouseover',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.add('hi');});});
$('#pins').addEventListener('mouseout',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.remove('hi');});});
