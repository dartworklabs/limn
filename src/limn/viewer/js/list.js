// If the people list changes (a new person/name), the list is redrawn - the very first render can show a login instead of a name.
async function loadPeople(){try{const r=(await api('/api/people',{what:'사람 목록',silent:true})).data;
  if(Array.isArray(r.people)){const was=JSON.stringify(PEOPLE); PEOPLE=r.people; if(JSON.stringify(PEOPLE)!==was)drawPins();}}catch(e){}}
async function loadPins(){let d;
  try{d=(await api('/api/pins?all=1',{what:'핀 읽기'})).data;}catch(e){return;}
  loadPeople();
  let dropped=[];
  try{dropped=(await api('/api/pins/dropped',{what:'삭제한 핀',silent:true})).data.dropped||[];}catch(e){}
  // Multiple documents: the fetched list is for every document (diffToast also sees all of it too). PINS/DONE are only the current document's; if SHOW_ALL, only the rendered list shows everything.
  const prevOpen=OPEN_ALL,prevReview=REVIEW_ALL;
  const nextOpen=d.filter(p=>!p.done); REVIEW_ALL=d.filter(p=>pinState(p)==='review'); DONE_ALL=d.filter(p=>pinState(p)==='done'); DROPPED=dropped;
  diffToast(prevOpen,d,dropped); reviewToast(prevReview,d);
  OPEN_ALL=nextOpen; PINS=nextOpen.filter(p=>pdoc(p)===DOC||!DOC); DONE=DONE_ALL.filter(p=>pdoc(p)===DOC||!DOC);
  if(EDIT&&!OPEN_ALL.some(p=>p.id===EDIT.id)){toast(tl('편집 중이던 핀 #{id} 이 목록에서 빠졌습니다(다른 쪽에서 닫았거나 지움)',{id:EDIT.id}),'warn'); EDIT=null;}
  if(REPLY&&!d.some(p=>p.id===REPLY.id)){closeReply(false); toast('답글을 쓰던 핀이 목록에서 빠졌습니다(지워짐) — 쓰던 글은 남겨 둡니다','warn');}
  if(!SEC_SEEN.open){SEC_SEEN.open=new Set(OPEN_ALL.map(p=>p.id)); SEC_SEEN.review=new Set(REVIEW_ALL.map(p=>p.id)); SEC_SEEN.done=new Set(DONE_ALL.map(p=>p.id));}
  drawPins(); marks(); drawDocTabs();
  if(CUR){recomputeOverlap(); renderOverlapBanner();}   // if the list changes (someone else's save/completion), overlap is recomputed too
  docTitle(true);
}
// The list drawn in the sidebar: the current document by default, everything if 'all documents'. A pin being edited is kept even from another document (so the draft text doesn't disappear).
function listOpen(){return SHOW_ALL&&multiDoc()?OPEN_ALL:OPEN_ALL.filter(p=>pdoc(p)===DOC||!DOC||(EDIT&&EDIT.id===p.id));}
function listDone(){return SHOW_ALL&&multiDoc()?DONE_ALL:DONE;}
function listReview(){return SHOW_ALL&&multiDoc()?REVIEW_ALL:REVIEW_ALL.filter(p=>pdoc(p)===DOC||!DOC);}
// Awaiting-review count: counted across documents (the inbox of work for a person to confirm). The purple number next to [핀 N] (compact) / the tool bar chip (wide).
// The pill rides on both [핀 N] toggles (the tool bar's and the collapsed wide nav bar's); the chip is the open wide panel's.
function updateReviewCount(){const n=REVIEW_ALL.length,chip=$('#rv-chip');
  for(const pill of $$('#btn-side .rv-n,#nav-side .rv-n')){pill.hidden=!n; pill.textContent=n; pill.setAttribute('aria-label',tl('검토 대기 {n}',{n}));}
  const here=listReview().length; chip.hidden=!n||LAYOUT!=='wide'||!SIDE_OPEN; chip.textContent=tl('검토 대기 {n}',{n})+(multiDoc()&&here!==n?' '+tl('(이 문서 {n})',{n:here}):'');}
function gotoReview(){if(!listReview().length&&REVIEW_ALL.length&&multiDoc())SHOW_ALL=true;
  if(!SEC.review){SEC.review=true; savePrefs({sec:SEC});} drawPins();
  setSide(true); requestAnimationFrame(()=>{const t=$('#sec-review'); if(t&&!t.hidden)t.scrollIntoView({block:'start',behavior:SMOOTH});});}
// The reviewer shown on an awaiting-review card: the author is suggested (anyone can confirm - a trust model). If I'm the author, '내 확인 차례'.
function isMe(a){const me=META&&META.me; return !!(a&&me&&me.login&&me.login!=='local'&&a.login===me.login);}
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
  b.innerHTML=ic(open?'chevron-down':'chevron-right')+'<span class="sec-name" id="'+SEC_NAME_ID[key]+'">'+esc(name)+' <span class="badge badge-secondary sec-n">'+ids.length+'</span></span>'+
    (nn?'<span class="sec-new">'+esc(tl('새 {n}',{n:nn}))+'</span>':'');
  b.setAttribute('aria-expanded',String(open));
  const body=document.getElementById(b.getAttribute('aria-controls')); if(body)body.hidden=!open;}
function toggleSec(key,force){if(!(key in SEC_DEFAULT))return; SEC[key]=force===undefined?!SEC[key]:!!force; savePrefs({sec:SEC}); drawPins();}
function drawPins(){
  const LIST=listOpen(),LDONE=listDone(),LDROP=listDropped();
  // The '나를 부른 핀' filter: only the open/awaiting-review pins across every document that @-tagged me (a cross-document inbox).
  const MINE=OPEN_ALL.concat(REVIEW_ALL).filter(mentionsMe),mf=$('#mention-filter');
  if(MENTION_ONLY&&!MINE.length)MENTION_ONLY=false;
  mf.hidden=!MINE.length; mf.setAttribute('aria-pressed',String(MENTION_ONLY)); mf.innerHTML=ic('at-sign')+MINE.length; mf.setAttribute('aria-label',tl('나를 부른 핀 {n}',{n:MINE.length}));
  const SHOWN=MENTION_ONLY?OPEN_ALL.filter(mentionsMe):LIST;
  // If the cursor was in the reply input field, it's restored to that position after redrawing (so auto-sync redrawing the list never interrupts typing).
  const rta=REPLY&&REPLY.el.querySelector('textarea'),rfocus=rta&&document.activeElement===rta?[rta.selectionStart,rta.selectionEnd]:null;
  secHead('open',tr(MENTION_ONLY?'나를 부른 열린 핀':SHOW_ALL&&multiDoc()?'모든 문서의 열린 핀':'열린 핀'),SHOWN.map(p=>p.id),OPEN_ALL.map(p=>p.id));
  const ab=$('#all-docs'); ab.setAttribute('aria-pressed',String(SHOW_ALL)); ab.innerHTML=(SHOW_ALL?ic('check'):'')+esc(tr('모든 문서'));
  $('#side-n').textContent=PINS.length; applySide();
  // In compact, the done toggle and the Trash are also in [⋯]. On desktop the Trash is the link under the list.
  $('#m-done').textContent=tl(SEC.done?'닫힌 핀 {n} 숨기기':'닫힌 핀 {n} 보기',{n:LDONE.length});
  const nTrash=LDROP.filter(p=>!PURGING.has(p.id)).length;
  $('#m-trash').textContent=tl('휴지통 {n}',{n:nTrash}); $('#trash-link').textContent=tl('휴지통 {n}',{n:nTrash}); $('#trash-link').hidden=!nTrash;
  $('#empty').hidden=SHOWN.length>0||OPEN_ALL.length>0||REVIEW_ALL.length>0;
  // Empty list: the header's count already says it - a separate '아직 없습니다.' line is never added too (QA). Only a note that another document has pins is left.
  $('#pins').innerHTML=SHOWN.length?SHOWN.map(card).join(''):(multiDoc()&&!SHOW_ALL&&OPEN_ALL.length?'<div class="dim list-empty">'+esc(tl('이 문서에는 없습니다 · 다른 문서에 {n}건',{n:OPEN_ALL.length}))+'</div>':'');
  if(EDIT){const slot=$('#pins .edit-slot'); if(slot)slot.replaceWith(EDIT.el);}
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
}
// Location estimation (.est, dashed) is judged by the server and carried as est in /api/pins (pin_est - comparing the
// manuscript fingerprint of the build the pin was placed on with the current build). Back when the viewer judged this by
// wall clock, it was wrong across the board with browser timezone, a note-only edited_at, and a pin placed on a stale
// PDF (confirmed by independent verification). The viewer just renders the value it's given.
function isEstimated(p){return p.est===true;}
function marks(){
  $$('.mark').forEach(m=>m.remove());
  // Awaiting-review pins are also drawn as purple marks - so the reviewer can see right there what was fixed (unrelated to an open pin's overlap/editing).
  PINS.concat(REVIEW_ALL.filter(p=>pdoc(p)===DOC)).forEach(p=>{const el=document.getElementById('p'+p.page); if(!el||!Array.isArray(p.frac))return;
    const est=isEstimated(p);
    const m=document.createElement('div'); m.className='mark'+(p.stale?' st':'')+(est?' est':'')+(p.done?' rv':''); m.dataset.pin=p.id;
    Object.assign(m.style,{left:p.frac[0]*100+'%',top:p.frac[1]*100+'%',width:p.frac[2]*100+'%',height:p.frac[3]*100+'%'});
    const n=String(p.note||'').replace(/\s+/g,' ').trim();
    const tip='#'+p.id+' · '+(n?(n.length>60?n.slice(0,60)+'…':n):tr('(메모 없음)'))+(est?' '+tr('(PDF가 새로 만들어져 위치는 추정입니다)'):'');
    m.innerHTML='<b data-act="mark-jump" data-id="'+p.id+'" data-tip="'+esc(tip)+'">'+p.id+'</b>'; el.appendChild(m);});
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
function secOpenFor(id){const p=findAnyPin(id); if(!p)return false; const st=pinState(p),key=st==='review'?'review':st==='done'?'done':'open';
  if(SEC[key])return false; SEC[key]=true; savePrefs({sec:SEC}); return true;}
// A mark badge's card: opens its section and the panel (a collapsed one too); compact also expands the card.
function revealCard(id){if(secOpenFor(id))drawPins(); setSide(true); if(LAYOUT==='wide')return;
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
  if(st==='done')SEC.done=true; else{OPEN_CARDS.add(id); SEC[st==='review'?'review':'open']=true;} savePrefs({sec:SEC});
  setSide(true); drawPins();
  requestAnimationFrame(()=>{const el=document.querySelector('.pin[data-id="'+id+'"],.arc-row[data-id="'+id+'"]'); if(!el)return;
    el.scrollIntoView({behavior:SMOOTH,block:'nearest'}); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    clearTimeout(el._flT); el._flT=setTimeout(()=>el.classList.remove('flash'),1200);});}
function jumpPin(id){if(viaDoc(id,jumpPin))return; const p=PINS.find(x=>x.id===id)||REVIEW_ALL.find(x=>x.id===id&&pdoc(x)===DOC);
  if(!p){const q=REVIEW_ALL.find(x=>x.id===id); if(q&&docInfo(pdoc(q)))switchDoc(pdoc(q)).then(()=>{if(DOC===pdoc(q))jumpPin(id);}); return;}
  if(document.body.classList.contains('revision-open'))setViewMode('manuscript');
  if(LAYOUT==='narrow')setSide(false);   // collapsed first so the sheet doesn't cover the page, then measured
  const m=document.querySelector('.mark[data-pin="'+id+'"]');
  if(m){
    const L=$('#left'),lr=L.getBoundingClientRect(),mr=m.getBoundingClientRect();
    L.scrollTop+=(mr.top-(lr.top+lr.height*0.30));
    m.classList.remove('flash');void m.offsetWidth;m.classList.add('flash');
  } else {
    const el=document.getElementById('p'+p.page); if(el)el.scrollIntoView({behavior:SMOOTH});
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
