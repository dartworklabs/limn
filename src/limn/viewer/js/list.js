// ------------------------------------------------ Pin list: loading pins, list sections, marks on the PDF, jumping to a pin or card
// If the people list changes (a new person/name), the list is redrawn - the very first render can show a login instead of a name -
// and so is the composer's assignee row: a draft restored at boot is read before the list arrives, when none of its tags resolves yet.
async function loadPeople(){try{const r=(await api('/api/people',{what:'사람 목록',silent:true})).data;
  if(Array.isArray(r.people)){const was=JSON.stringify(PEOPLE),first=!PEOPLE_KNOWN; PEOPLE=r.people; PEOPLE_KNOWN=true;
    const changed=JSON.stringify(PEOPLE)!==was; if(changed)drawPins(); if(changed||first)renderAssignNew();}}catch(e){}}
// A refresh that started earlier must not replace one already applied from a newer request. A failed request claims no snapshot.
let PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0;
// Classifies one server snapshot without reading viewer state or changing the page. Legacy pins with no doc belong to defaultDoc.
// confirming (optional) holds the ids whose [확인] waits for its undo (CONFIRMING): they stay out of the review list.
function derivePinLists(rows,doc,defaultDoc,confirming){
  const openAll=[],reviewAll=[],doneAll=[],openHere=[],doneHere=[];
  for(const pin of rows){const state=pinState(pin),here=!doc||(pin.doc||defaultDoc)===doc;
    if(state===PIN_STATE.OPEN){openAll.push(pin); if(here)openHere.push(pin);}
    else if(state===PIN_STATE.REVIEW){if(!(confirming&&confirming.has(pin.id)))reviewAll.push(pin);}
    else if(state===PIN_STATE.DONE){doneAll.push(pin); if(here)doneHere.push(pin);}}
  return {openAll,reviewAll,doneAll,openHere,doneHere};
}
// Applies an accepted snapshot: announces transitions on the status line, keeps active editors honest (an edit or reply whose
// pin left says so there too, with a dot on [핀 N]), then redraws the current document.
/** Apply a fresh snapshot while retaining dirty or saving editors whose pin is still present, including a rival close. */
function applyPinLists(rows,dropped,lists){
  const prevOpen=OPEN_ALL,prevReview=REVIEW_ALL;
  notePinChanges(prevOpen,rows,dropped); noteReviewChanges(prevReview,rows); updNewPins(rows);   // others' new pins (updates.js)
  OPEN_ALL=lists.openAll; REVIEW_ALL=lists.reviewAll; DONE_ALL=lists.doneAll; DROPPED=dropped;
  PINS=lists.openHere; DONE=lists.doneHere;
  // A pin whose [확인] waits for its undo stays in the verdict order (verdictOrder) as this snapshot has it - still awaiting
  // review - and leaves it once the snapshot no longer has it so (deleted from another window, reopened, confirmed elsewhere).
  CONFIRMING_PIN.forEach((_,id)=>{const r=rows.find(x=>x.id===id); if(r&&pinState(r)===PIN_STATE.REVIEW)CONFIRMING_PIN.set(id,r); else CONFIRMING_PIN.delete(id);});
  const E=EDITOR.current; if(E&&!OPEN_ALL.some(p=>p.id===E.id)){
    if(rows.some(p=>p.id===E.id)&&(EDITOR.saving||editDirty()))SEC.open=true;
    else{lineNote(tl('편집 중이던 핀 #{id} 이 목록에서 빠졌습니다(다른 쪽에서 닫았거나 지움)',{id:E.id}),NOTICE_KIND.WARN,null,{dot:NOTICE_DOT.SIDE}); EDITOR.current=null;}}
  const R=REPLY; if(R&&!rows.some(p=>p.id===R.id)){closeReply(false); lineNote('답글을 쓰던 핀이 목록에서 빠졌습니다(지워짐) — 쓰던 글은 남겨 둡니다',NOTICE_KIND.WARN,null,{dot:NOTICE_DOT.SIDE});}
  if(!SEC_SEEN.open){SEC_SEEN.open=new Set(OPEN_ALL.map(p=>p.id)); SEC_SEEN.review=new Set(REVIEW_ALL.map(p=>p.id)); SEC_SEEN.done=new Set(DONE_ALL.map(p=>p.id));}
  drawPins(); marks(); drawDocTabs();
  if(COMPOSE.current){recomputeOverlap(); renderOverlapBanner();}   // if the list changes (someone else's save/completion), overlap is recomputed too
  docTitle(true);
}
// Fetches one pin snapshot and its Trash. Returns whether it applied; only a newer applied snapshot supersedes it: a read
// another one started later overtook (a light poll's, an action's) returns false and draws nothing, and the list stays as
// the newer one drew it. A failed read is a banner on top of the panel with [다시 시도].
async function loadPins(){const seq=++PINS_LOAD_SEQ; let d;
  try{d=(await api('/api/pins?all=1',{what:'핀 읽기',where:NOTICE_HOST.LIST,retry:()=>{loadPins();}})).data;}catch(e){return false;}
  if(seq<PINS_APPLIED_SEQ)return false;
  let dropped=[];
  // Said, not silent: this read failing stops the whole snapshot from being applied, and a refresh that stops
  // without a word looks like a list that simply did not change (docs/handbook/viewer.md §알림 자리).
  try{dropped=(await api('/api/pins/dropped',{what:'삭제한 핀',where:NOTICE_HOST.LIST,retry:()=>{loadPins();}})).data.dropped||[];}catch(e){return false;}
  if(seq<PINS_APPLIED_SEQ)return false;
  loadPeople();
  // All-document lists drive notices; only the current document's open and done pins drive its marks and rows.
  PINS_APPLIED_SEQ=seq;   // before the redraw it makes: a page verdict line stops reading '판정 읽는 중…' with this list (pvLineHtml)
  applyPinLists(d,dropped,derivePinLists(d,DOC,DEFAULT_DOC,CONFIRMING));
  return true;
}
// Reads the list again for a caller that goes on to act on it as it stands (a pin link opening its card). Resolves true
// when the list now shows a snapshot asked for by this call or a later one - its own read applied, or a newer read that
// overtook it did - and false only when none since the call has applied (the read failed and said so). loadPins' own
// answer is false when overtaken, the light poll's cue to read that revision again (docs/handbook/build-sync.md §자동
// 동기화 (가벼운 meta 폴링)), so a caller that waits for the list itself reads it with this.
/** @returns {Promise<boolean>} */
async function loadPinsNow(){const since=PINS_LOAD_SEQ; await loadPins(); return PINS_APPLIED_SEQ>since;}
// The list drawn in the sidebar: the current document by default, everything if 'all documents'. A pin being edited is kept even from another document (so the draft text doesn't disappear).
function listOpen(){return SHOW_ALL&&multiDoc()?OPEN_ALL:OPEN_ALL.filter(p=>pdoc(p)===DOC||!DOC||(EDITOR.current&&EDITOR.current.id===p.id));}
function listDone(){return SHOW_ALL&&multiDoc()?DONE_ALL:DONE;}
function listReview(){return SHOW_ALL&&multiDoc()?REVIEW_ALL:REVIEW_ALL.filter(p=>pdoc(p)===DOC||!DOC);}
// Awaiting-review count: counted across documents (the inbox of work for a person to confirm). The purple number next to [핀 N] (compact) / the tool bar chip (wide).
// [⬚ 선택] keeps the width of its pressed face [⬚ 선택 중] wherever it shows its label (docs/handbook/viewer.md §모바일 레이아웃
// 선택 모드), so pressing it moves neither it nor its neighbours - on the landscape phone's top row a wider face moved the
// button itself under the finger. Effect: --sel-w on the button, measured with the pressed face drawn for a moment (in the
// interface language), or removed where the label is hidden (the portrait phone's 36px icon, a stepped-down sheet bar).
function holdSelectWidth(){const b=$('#btn-select'),l=/** @type {HTMLElement} */(b.querySelector('.lbl')); b.style.removeProperty('--sel-w');
  if(!b.getClientRects().length||getComputedStyle(l).display==='none')return;
  const pressed=b.getAttribute('aria-pressed')||'false',text=l.textContent; b.setAttribute('aria-pressed','true'); l.textContent=tr('선택 중');
  const w=b.getBoundingClientRect().width; b.setAttribute('aria-pressed',pressed); l.textContent=text; b.style.setProperty('--sel-w',Math.ceil(w)+'px');}
// The phone and tablet sheet bar's left cell steps down until [핀 N | 검토 M] and [⬚] fit it (English, three-digit counts,
// a folded cover): first [⬚ 선택] drops its label for the 36px icon the phone has (#bar1.bar-sel-icon) - the chip never
// shrinks for it; then the chip's halves pad one 4px step less and the cell's gap is 4px (#bar1.bar-snug); then the words
// '핀' and '검토' give way to a dot each - green for the open pins, purple for those awaiting review (#bar1.bar-tight) - so a
// count never stands alone. Measured each time a count or the band changes, after [⬚ 선택] has its width (holdSelectWidth,
// every band); decoration only - nothing moves.
function fitBarWords(){const b=$('#bar1'),l=b.querySelector('.bar-l'); b.classList.remove('bar-sel-icon','bar-snug','bar-tight'); holdSelectWidth();
  if(LAYOUT!==LAYOUT_MODE.NARROW)return;
  const over=()=>{const k=[...l.children].filter(e=>e.getClientRects().length);   // the last control's edge, not scrollWidth: the hits overflow too
    return k.length>0&&k[k.length-1].getBoundingClientRect().right>l.getBoundingClientRect().right+0.05;};   // past the cell, [⬚]'s hit reaches the grabber's column
  for(const step of ['bar-sel-icon','bar-snug','bar-tight']){if(!over())return; b.classList.add(step); if(step==='bar-sel-icon')holdSelectWidth();}}
// The pill rides on both [핀 N] toggles (the tool bar's and the collapsed wide nav bar's); the phone and tablet sheet's bar shows
// the count as its own half [검토 M] (#btn-rv) instead; the chip is the open wide panel's.
// The pill is the eye icon and the count, so it never reads as part of the open count beside it ('11 1', UX audit P10).
function updateReviewCount(){const n=REVIEW_ALL.length,chip=$('#rv-chip');
  for(const pill of $$('#btn-side .rv-n,#nav-side .rv-n')){pill.hidden=!n; setHtml(pill,html`${ic('eye')}${n}`); pill.setAttribute('aria-label',tl('검토 대기 {n}',{n}));}
  const rb=$('#btn-rv'); rb.hidden=!n; rb.querySelector('.rv-c').textContent=n; rb.setAttribute('aria-label',tl('검토 {n} · 검토 대기 핀으로 가기',{n}));   // the sheet bar's [검토 M] half: its name starts with what it shows
  fitBarWords();
  const here=listReview().length; chip.hidden=!n||LAYOUT!==LAYOUT_MODE.WIDE||!SIDE_OPEN; chip.textContent=tl('검토 대기 {n}',{n})+(multiDoc()&&here!==n?' '+tl('(이 문서 {n})',{n:here}):'');}
// [검토 M], the review chip and a review message's [보기]: the review section, opened and scrolled to; its dot goes (seen).
function gotoReview(){noticeSeen(NOTICE_DOT.RV); if(!listReview().length&&REVIEW_ALL.length&&multiDoc())SHOW_ALL=true;
  if(!SEC.review){SEC.review=true; savePrefs({sec:SEC});} drawPins();
  setSide(true); requestAnimationFrame(()=>{const t=$('#sec-review'); if(t&&!t.hidden)t.scrollIntoView({block:'start',behavior:SMOOTH});});}
// The reviewer shown on an awaiting-review card: the author is suggested (anyone can confirm - a trust model). If I'm the author, '내 확인 차례'.
function isMe(a){const me=META&&META.me; return !!(a&&me&&me.login&&me.login!==LOCAL_LOGIN&&a.login===me.login);}
/** @param {Pin} p */
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
  const body=document.getElementById(b.getAttribute('aria-controls')||''); if(body)body.hidden=!open;}
function toggleSec(key,force){if(!(key in SEC_DEFAULT))return; SEC[key]=force===undefined?!SEC[key]:!!force; savePrefs({sec:SEC}); drawPins();}
// Redraws the pin panel from the lists (sections, counts, the Trash count, a reply in progress, the undo rows and notes and the
// banners of notices.js, keeping a focus that was in one) - and, while the changes view shows a pin, its guide line's buttons,
// whose [확인] follows that pin's state (revTargetActs). The status line's review arrivals follow the review list it draws:
// those whose pins left it go, with [검토 M]'s dot (dropStaleReview).
/** Redraw active lists and retain the live editor, even when a rival close moved its pin out of the open list. */
function drawPins(){dropStaleReview();
  const keep=listKeep();   // the rows in the list's view: one of them is put back where it stood once the cards are drawn (lazyCards)
  const LIST=listOpen(),LDONE=listDone(),LDROP=listDropped();
  const nfocus=noticeFocus();   // a focus in an undo row or note, given back once they are drawn again (drawOffers)
  // The '나를 부른 핀' filter: only the open/awaiting-review pins across every document that @-tagged me (a cross-document inbox).
  const MINE=OPEN_ALL.concat(REVIEW_ALL).filter(mentionsMe),mf=$('#mention-filter');
  if(MENTION_ONLY&&!MINE.length)MENTION_ONLY=false;
  mf.hidden=!MINE.length; mf.setAttribute('aria-pressed',String(MENTION_ONLY)); setHtml(mf,html`${ic('at-sign')}${MINE.length}`); mf.setAttribute('aria-label',tl('나를 부른 핀 {n}',{n:MINE.length}));
  const SHOWN=MENTION_ONLY?OPEN_ALL.filter(mentionsMe):LIST;
  // If the cursor was in the reply input field or the edit card's note, it's restored to that position after redrawing (so auto-sync
  // redrawing the list, or a layout change redrawing the cards, never interrupts typing).
  const rta=REPLY&&replyNote(REPLY),rfocus=rta&&document.activeElement===rta?[rta.selectionStart,rta.selectionEnd]:null;
  // The edit card's note or suggested-edit field keeps its focus and selection the same way.
  const ef=EDITOR.current&&document.activeElement&&EDITOR.current.el.contains(document.activeElement)&&document.activeElement.matches('.e-note,.e-sg-text')?/** @type {HTMLTextAreaElement} */(document.activeElement):null;
  const eta=ef,efocus=eta?[eta.selectionStart,eta.selectionEnd]:null,cfocus=cardFocusKeep();
  secHead('open',tr(MENTION_ONLY?'나를 부른 열린 핀':SHOW_ALL&&multiDoc()?'모든 문서의 열린 핀':'열린 핀'),SHOWN.map(p=>p.id),OPEN_ALL.map(p=>p.id));
  const ab=$('#all-docs'); ab.setAttribute('aria-pressed',String(SHOW_ALL)); setHtml(ab,html`${SHOW_ALL?ic('check'):''}${tr('모든 문서')}`);
  $('#side-n').textContent=PINS.length; applySide();
  // In compact, the Trash is a row in [⋯] with its count. On desktop the Trash is the link under the list.
  const nTrash=LDROP.filter(p=>!PURGING.has(p.id)).length;
  $('#m-trash-n').textContent=nTrash; $('#trash-link').textContent=tl('휴지통 {n}',{n:nTrash}); $('#trash-link').hidden=!nTrash;
  $('#empty').hidden=SHOWN.length>0||OPEN_ALL.length>0||REVIEW_ALL.length>0||!!EDITOR.current;
  // Empty list: the header's count already says it - a separate '아직 없습니다.' line is never added too (QA). Only a note that another document has pins is left.
  setHtml($('#pins'),SHOWN.length?cardRows(SHOWN,'open'):html`${cardRows([],'open')}${multiDoc()&&!SHOW_ALL&&OPEN_ALL.length?html`<div class="dim list-empty">${tl('이 문서에는 없습니다 · 다른 문서에 {n}건',{n:OPEN_ALL.length})}</div>`:''}`);   // with no card, an undo row still gets its slot (cardRows)
  if(EDITOR.current){const slot=$('#pins .edit-slot'); if(slot)slot.replaceWith(EDITOR.current.el); else $('#pins').appendChild(EDITOR.current.el); renderEdit();
    if(efocus&&eta&&document.contains(eta)){eta.focus(); try{eta.setSelectionRange(efocus[0],efocus[1]);}catch(e){}}}
  // Awaiting-review section: between open pins and done. Hidden when empty - but not while a confirm's undo row stands in it
  // (offersIn). The card looks the same as an open pin (thread/replies); only the actions are [확인]/[답글].
  const LREV=MENTION_ONLY?REVIEW_ALL.filter(mentionsMe):listReview();
  $('#sec-review').hidden=!LREV.length&&!offersIn('review'); secHead('review',tr('검토 대기'),LREV.map(p=>p.id),REVIEW_ALL.map(p=>p.id));
  setHtml($('#review-pins'),cardRows(LREV,'review'));
  drawOrderControl((SEC.open&&SHOWN.length>0)||(SEC.review&&LREV.length>0));
  updateReviewCount();
  // Done section: hidden header and all if empty. The header stays stuck to the top while scrolling.
  $('#sec-done').hidden=!LDONE.length; secHead('done',tr('완료'),LDONE.map(p=>p.id),DONE_ALL.map(p=>p.id));
  if(SEC.done)setHtml($('#done-list'),LDONE.length?html`${LDONE.slice().reverse().map(doneCard)}`:html`<div class="dim">없습니다.</div>`);
  if($('#trash').open)drawTrash();
  if(REPLY){const slot=document.querySelector('#list .reply-slot'); if(slot)slot.replaceWith(REPLY.el); renderReplyOutcome();   // the pin may have changed state meanwhile
    if(rfocus&&rta&&document.contains(rta)){rta.focus(); try{rta.setSelectionRange(rfocus[0],rfocus[1]);}catch(e){}}}
  drawOffers(nfocus); drawBanners(); lazyCards(keep); cardFocusBack(cfocus);
  if(REV.target)revTargetActs();
}
// The pins of a list section in order (docs/handbook/viewer.md §목록 순서), list itself untouched. LIST_ORDER.NEW: the newest `at`
// first, the later pin first within a minute, a pin with no readable time last. LIST_ORDER.PAGE: by page, where the pin's mark is
// now, then line, then height on the page for a region, which has no line; pins of several documents stand document by document,
// since page numbers mean nothing across them. A pin with no page (a Markdown document's, ADR-0025 D2) is ordered by its lines
// alone - its page counts as 0. LIST_ORDER.ID: as the server lists them.
/** @param {Pin[]} list @param {string} order - a LIST_ORDER value @returns {Pin[]} */
function orderPins(list,order){if(order===LIST_ORDER.ID)return list;
  const key=(/** @type {Pin} */p)=>{if(order===LIST_ORDER.NEW){const t=timeParts(p.at); return [t?-t.t:Infinity,-p.id];}
    const at=pinPlace(p),d=DOCS.findIndex(x=>x.key===pdoc(p)); return [d<0?DOCS.length:d,typeof at.page==='number'?at.page:0,p.lo==null?Infinity:p.lo,at.frac?at.frac[1]:Infinity,p.id];};
  // Two missing values subtract to NaN, which falls through to the next key as a tie does.
  return list.map(p=>({p,k:key(p)})).sort((a,b)=>{for(let i=0;i<a.k.length;i++){const c=a.k[i]-b.k[i]; if(c)return c;} return 0;}).map(r=>r.p);}
// One list section's cards as Html, in the list's order; newest first, a day line stands over each day's first card. Its name is
// worked out here, so it is right from the next draw on when the date turns. An undo row of the section (sec: 'open', 'review')
// whose card has left gets an empty slot where its pin stands in that order, under its day's line, which stays while the row
// does if the pin was that day's only card (drawOffers puts the row in the slot). In the server's order the row follows the card
// drawn before it, as it always did.
/** @param {Pin[]} list @param {string} sec @returns {Html} */
function cardRows(list,sec){const now=Date.now(),slots=new Map(); let day='';
  if(ORDER!==LIST_ORDER.ID)for(const n of NOTICES.values())if(n.place===NOTICE_PLACE.ROW&&n.sec===sec&&n.rec&&!list.some(p=>p.id===n.pin))slots.set(n.rec,n.n);
  return html`${orderPins(list.concat([...slots.keys()]),ORDER).map(p=>{const d=ORDER===LIST_ORDER.NEW?dayName(p.at,now):'',over=d&&d!==day?html`<div class="day-line"><span>${d}</span></div>`:''; if(d)day=d;
    const slot=slots.get(p); return html`${over}${slot?html`<div class="nt-slot" data-slot="${slot}"></div>`:card(p)}`;})}`;}
// Where undo row e of notice n goes in list section box when the list drew no slot for it (the row came after that draw): where
// the list's next draw puts its slot (cardRows), so that draw moves nothing. Its place is by orderPins among what is drawn -
// the cards and the other rows that know their pins: after the one before it when that is of its day (newest first; in the
// page order always), else before the one after it when that is, else, its day having nothing else, under a line made for it
// between the two, which stays while the row does (dropBareDayLines). In the server's order, or for a row that does not know
// its pin, it follows the card drawn before it (prev), else it goes first.
/** @param {HTMLElement} box @param {Notice} n @param {HTMLElement} e */
function placeRow(box,n,e){const prev=n.prev!=null?box.querySelector('.pin.card[data-id="'+n.prev+'"]'):null;
  if(!n.rec||ORDER===LIST_ORDER.ID){if(prev)prev.after(e); else box.prepend(e); return;}
  const drawn=/** @type {Map<Pin,Element>} */(new Map());
  for(const el of box.children){const h=/** @type {HTMLElement} */(el),o=h.matches('.pin.card')?findAnyPin(Number(h.dataset.id)):h.matches('.nt-row')?((NOTICES.get(Number(h.dataset.n))||{}).rec||null):null;
    if(o&&o!==n.rec)drawn.set(o,el);}
  const order=orderPins([...drawn.keys(),n.rec],ORDER),i=order.indexOf(n.rec),before=order[i-1],after=order[i+1],now=Date.now();
  const day=(/** @type {Pin|undefined} */p)=>p&&ORDER===LIST_ORDER.NEW?dayName(p.at,now):'',d=day(n.rec);
  if(before&&day(before)===d){/** @type {Element} */(drawn.get(before)).after(e); return;}
  if(after&&day(after)===d){/** @type {Element} */(drawn.get(after)).before(e); return;}
  const l=document.createElement('div'); l.className='day-line'; l.append(document.createElement('span')); /** @type {HTMLElement} */(l.firstChild).textContent=d;
  if(before)/** @type {Element} */(drawn.get(before)).after(l);
  else if(after){const a=/** @type {Element} */(drawn.get(after)),over=a.previousElementSibling; (over&&over.matches('.day-line')?over:a).before(l);}
  else box.prepend(l);
  if(d)l.after(e); else l.replaceWith(e);}   // the page order has no day lines
// Takes out a day line with nothing of its day under it - its last undo row gone - in the open and review sections.
function dropBareDayLines(){for(const l of $$('#pins>.day-line,#review-pins>.day-line')){const nx=l.nextElementSibling; if(!nx||nx.matches('.day-line'))l.remove();}}
// [최신순 | 위치순 | 번호순]: shown while the open or review section shows a card, the list's order pressed.
/** @param {boolean} any */
function drawOrderControl(any){const c=$('#list-order'); c.hidden=!any;
  for(const b of c.querySelectorAll('button')){const on=/** @type {HTMLElement} */(b).dataset.order===ORDER; b.classList.toggle('on',on); b.setAttribute('aria-pressed',String(on));}}
// A press on the order control: the list is drawn in order o, remembered for this browser, with the control where it stood under
// the pointer - a card kept in place (lazyCards) would scroll it away - and its button keeps the focus (it is not redrawn).
/** @param {string|undefined} o - a LIST_ORDER value */
function setListOrder(o){const next=listOrderOf(o); if(next===ORDER)return; ORDER=next; savePrefs({order:next});
  const c=$('#list-order'),y=c.getBoundingClientRect().top; drawPins();
  listScroller().scrollTop+=c.getBoundingClientRect().top-y;}
// Cards far from the list's view are left for the browser to skip (.lazy: content-visibility:auto, list.css): it does not
// lay them out or paint them until they come near the view. Their markup stays whole and current all the while - a card
// coming back is drawn from what it holds then - and a focus, a find or a selection reaching into one draws it at once; a
// script's measure inside one lays it out for the answer, but the innerText of what is skipped is empty.
// What it saves: each page PDF.js draws for the first time adds its embedded fonts to document.fonts, and every font added
// makes the browser lay out all the text in the page again - every card in the open panel with it. 127 cards made the first
// wheel scroll through a 91-page figure document 77-84 long tasks (4.4-4.9s), none with the panel folded (issue #305).
// Only a card more than a view's height above or below the list's view is skipped (lazyWatch): skipping contains a card
// (paint containment), which draws its parts on whole pixels and clips what reaches past its edge (a focus ring, a 44px
// touch target's hit area), so a card in view, or scrolled to, is never held and draws as it always did. A card being
// edited or holding the reply box is never skipped: containment would hold the fixed action row (compact) inside the card.
// A skipped card stands at the height it had when it went (--card-h, from the observer's own measure: no extra layout).
// With a guessed height instead the list moved under a person scrolled down it at every draw, by the guess's error over
// every card above, and a jump to a card (a mark's badge, [검토 M]) would aim by guesses. The height goes stale when the
// list's width or its font changes, so then every card is drawn again and sorted anew (lazyAgain), as at each draw - which
// makes new cards, all drawn once. A height that goes stale otherwise (a card changed in place while skipped) comes right
// as the card comes near: the browser's scroll anchoring keeps the view where it stands as it grows or shrinks. A draw
// makes new elements, which that anchoring cannot hold, so a row in the view before it (listKeep) is put back where it
// stood: its cards may stand at other heights than the ones they replace.
let LAZY_IO=/** @type {IntersectionObserver|null} */(null),LAZY_ROOT=/** @type {HTMLElement|null} */(null),LAZY_W=0,LAZY_H=-1;
// After a draw: the first row kept (listKeep) that is still drawn in the section it was in is put back where it stood - a row
// whose pin a poll moved to another section (검토 대기, 완료) or deleted gives way to the next, and with none left nothing is
// put back: followed into its new section, the view jumped past every card still open. Then every new card is sorted.
/** @param {{sel:string,sec:string,top:number}[]} keep */
function lazyCards(keep){const S=listScroller();
  for(const a of keep){const r=/** @type {HTMLElement|null} */(document.querySelector(a.sel)); if(!r||!r.getClientRects().length||listSection(r)!==a.sec)continue;
    const moved=r.getBoundingClientRect().top-a.top; if(Math.abs(moved)>=0.5)S.scrollTop+=moved; break;}
  const L=$('#list'); LAZY_W=L.getClientRects().length?L.clientWidth:0;
  lazyWatch();}
// Has every card sorted from its first report, by an observer whose margin is the scroller's height now, in px above and
// below its view (a percentage would be of the root's width): it is made again when that height or the scroller changes.
function lazyWatch(){if(!window.IntersectionObserver)return; const S=listScroller(),h=S.clientHeight; if(LAZY_IO)LAZY_IO.disconnect();
  if(!LAZY_IO||LAZY_ROOT!==S||LAZY_H!==h){LAZY_ROOT=S; LAZY_H=h; LAZY_IO=new IntersectionObserver(lazySort,{root:S,rootMargin:h+'px 0px'});}
  for(const c of $$('#list .pin.card'))LAZY_IO.observe(c);}
// The observer's reports: a card that came within a view's height of the list's view is drawn as it is; one that went
// further is skipped at the height it has now - not a card that is not laid out (the panel folded: no height to stand at),
// being edited or holding the reply box.
/** @param {IntersectionObserverEntry[]} es */
function lazySort(es){for(const e of es){const c=/** @type {HTMLElement} */(e.target);
  if(e.isIntersecting){c.classList.remove('lazy'); continue;}
  if(c.classList.contains('lazy')||!e.boundingClientRect.height||c.classList.contains('editing')||c.querySelector('.reply-box'))continue;
  const s=getComputedStyle(c);   // the content box: what contain-intrinsic-size sets
  c.style.setProperty('--card-h',e.boundingClientRect.height-parseFloat(s.paddingTop)-parseFloat(s.paddingBottom)-parseFloat(s.borderTopWidth)-parseFloat(s.borderBottomWidth)+'px');
  c.classList.add('lazy');}}
// Every card drawn once more and sorted anew, a row in the view kept in place: the skipped cards' heights are
// stale. So they are when the list's width changes or it is shown (a card not laid out was not skipped), and when a font the
// list is set in comes in (a slice of the bundled Pretendard for letters not drawn before): their heights were read in the
// fallback face. The fonts PDF.js adds are not the list's, and fire no loadingdone besides.
function lazyAgain(){const keep=listKeep(); $$('#list .pin.card.lazy').forEach(c=>c.classList.remove('lazy')); lazyCards(keep);}
// The scroller's height changed (a window, the sheet dragged): the observer's margin follows it.
if(window.ResizeObserver){const o=new ResizeObserver(()=>{const L=$('#list'),w=L.getClientRects().length?L.clientWidth:0;
  if(w&&w!==LAZY_W)lazyAgain(); else if(LAZY_IO&&listScroller().clientHeight!==LAZY_H)lazyWatch();}); o.observe($('#list')); o.observe($('#right'));}
document.fonts.addEventListener('loadingdone',e=>{if(!$$('#list .pin.card.lazy').length)return; const ff=getComputedStyle($('#list')).fontFamily;
  if(/** @type {FontFaceSetLoadEvent} */(e).fontfaces.some(f=>ff.includes(f.family.replace(/^["']|["']$/g,''))))lazyAgain();});
// The box the list scrolls in: the list itself, or in compact the panel (#right), which holds the tool bar above it.
function listScroller(){return document.body.classList.contains('compact')?$('#right'):$('#list');}
// The cards and archive rows in the list's view, top first, each with its section and its top: the rows lazyCards may put
// back. None while the list is at its top (the browser does not anchor there either: what a draw adds above it shows) or is
// not laid out.
/** @returns {{sel:string,sec:string,top:number}[]} */
function listKeep(){const S=listScroller(),out=[]; if(!S.scrollTop||!S.getClientRects().length)return out; const R=S.getBoundingClientRect();
  for(const r of /** @type {HTMLElement[]} */($$('#list .pin[data-id],#list .arc-row[data-id]'))){if(!r.getClientRects().length)continue; const b=r.getBoundingClientRect();
    if(b.bottom<=R.top)continue; if(b.top>=R.bottom)break;
    out.push({sel:'#list '+(r.classList.contains('arc-row')?'.arc-row':'.pin')+'[data-id="'+CSS.escape(r.dataset.id||'')+'"]',sec:listSection(r),top:b.top});}
  return out;}
// The section a row is drawn in: open (#pins), awaiting review (#review-pins) or done (#done-list).
/** @param {Element} r */
function listSection(r){const s=r.closest('#pins,#review-pins,#done-list'); return s?s.id:'';}
// A focus on a card's control (its number, a button) goes back to the same control of the same card once the lists are drawn
// again (a poll, someone's change, the list read after a [지우기] whose focus went to the card beside): drawn anew, it fell
// to the page and the next Tab started over. Text fields keep theirs above; a card gone leaves the focus where it fell, and a
// focus that is somewhere again (a notice's, drawOffers) stays there.
/** @returns {{el:HTMLElement,id:string,act:string,i:number}|null} */
function cardFocusKeep(){const a=/** @type {HTMLElement|null} */(document.activeElement),c=a&&a.closest?/** @type {HTMLElement|null} */(a.closest('#list .pin[data-id]')):null;
  const act=a&&a.dataset?a.dataset.act||'':''; if(!a||!c||!act||a.matches('textarea,input'))return null;
  return {el:a,id:c.dataset.id||'',act,i:[...c.querySelectorAll('[data-act="'+CSS.escape(act)+'"]')].indexOf(a)};}
/** @param {{el:HTMLElement,id:string,act:string,i:number}|null} k */
function cardFocusBack(k){const a=document.activeElement; if(!k||(a&&a!==document.body))return;
  if(document.contains(k.el)){k.el.focus({preventScroll:true}); return;}   // the edit card or the reply, put back in its slot
  const c=document.querySelector('#list .pin[data-id="'+CSS.escape(k.id)+'"]'),same=c?c.querySelectorAll('[data-act="'+CSS.escape(k.act)+'"]'):null;
  const b=/** @type {HTMLElement|null} */(same&&(same[Math.max(0,k.i)]||same[0])); if(b)b.focus({preventScroll:true});}
// Location estimation (.est, dashed) is judged by the server and carried as est in /api/pins (pin_est - comparing the
// manuscript fingerprint of the build the pin was placed on with the current build). Back when the viewer judged this by
// wall clock, it was wrong across the board with browser timezone, a note-only edited_at, and a pin placed on a stale
// PDF (confirmed by independent verification). The viewer just renders the value it's given.
/** @param {Pin} p */
function isEstimated(p){return p.est===true;}
// Whether a mark's number badge goes inside the mark (docs/handbook/viewer.md §모바일 레이아웃): fx is the mark's left as a
// fraction of the page, w the page width, pad the room left of the page in the PDF scroller (its margin) and reach how far
// the badge hangs left of the mark (28px on touch, 24px with a mouse). Only when the margin and the offset together are
// short of the reach would the badge be clipped, and only then does it sit in the mark's top-left corner - inside, it covers
// the text the mark points at. Pure.
function markBadgeIn(fx,w,pad,reach){return fx*w+pad<reach;}
// Page pg's room: the room left of it in the PDF scroller, in scroll coordinates (a horizontal scroll does not count), its
// width, and the badge's reach for the primary pointer: {pad, w, reach}. Pages have their own widths and a narrower page is
// centred, so each page has its own margin. null for a page that is not laid out (the changes view hides the pages).
/** @param {Element|null} pg */
function markBadgeRoom(pg){const L=$('#left'); if(!L||!pg||!pg.getClientRects().length)return null; const r=pg.getBoundingClientRect();
  return {pad:r.left-L.getBoundingClientRect().left-L.clientLeft+L.scrollLeft,w:r.width,reach:MQ_COARSE.matches?28:24};}
// Re-decides every page number's place (pageNoSides) and every drawn mark's badge side for its page's width and margin now (a
// zoom, a re-fit or a band change moves both),
// then how far each badge's press area reaches (markHitSides: the badges' distances follow the same width). A mark on a page
// that is not laid out keeps its side until the page shows again.
function markBadgeSides(){pageNoSides(); const rooms=new Map(); $$('.mark').forEach(m=>{const pg=m.parentElement;
    if(!rooms.has(pg))rooms.set(pg,markBadgeRoom(pg)); const r=rooms.get(pg); if(r)m.classList.toggle('in',markBadgeIn(+m.dataset.fx,r.w,r.pad,r.reach));});
  $$('.sel.pending').forEach(pendingBadgeSide); markHitSides(); markCoverSkip();}   // the pending boxes' '+' badges follow the same rule
// A badge the panel, the sheet or a bar covers is no stop for the keyboard (docs/handbook/viewer.md §모바일 레이아웃): Tab put
// the ring on a mark the person could not see, and its tooltip floated over the box that hid it (issue #418). The covers are
// the boxes drawn over the pages, each where it is laid out (MARK_COVERS): the panel (#right: the sheet, the overlay panel,
// the closed sheet's bar) and the status line standing on the sheet's top edge (#status-dock, outside the panel so its action
// can reach up over the pages). The bars that also stand over the pages do so inside the panel's box: the tool bar is the
// sheet's head, and the phone's search row (#doc-nav at its foot) lies over the closed bar. A badge whose centre lies in the
// pages' view (#left's box within the window) leaves the tab order while a cover is over that centre. A badge scrolled out of the view keeps its stop only
// while the pages can scroll it to where no cover is (markShift): Tab brings it there (markReveal). With the sheet pulled up
// to the document bar nothing can show, and no badge is a stop. The boxes are compared, not hit-tested: a hit test per badge
// took 15 ms a pass in Chromium with 150 badges on screen, which a scroll pays every frame; the comparison takes under 1 ms.
// Every box is read before any stop is written, and only a stop that changes is written. A description standing over (or
// waiting for) a badge that has just left goes with it.
const MARK_COVERS=['#right','#status-dock'],MARK_EDGE=8;   // MARK_EDGE: px a revealed badge keeps clear of a cover or the view's edge
/** The pages' view: #left's box within the window. @returns {{left:number,top:number,right:number,bottom:number}} */
function markView(){const v=$('#left').getBoundingClientRect();
  return {left:Math.max(v.left,0),top:Math.max(v.top,0),right:Math.min(v.right,innerWidth),bottom:Math.min(v.bottom,innerHeight)};}
/** The covers' boxes laid out over view v, each cut to it. @param {{left:number,top:number,right:number,bottom:number}} v */
function markCoverBoxes(v){const out=[];
  for(const s of MARK_COVERS){const e=$(s); if(!e||!e.getClientRects().length)continue; const c=e.getBoundingClientRect();
    const x0=Math.max(c.left,v.left),y0=Math.max(c.top,v.top),x1=Math.min(c.right,v.right),y1=Math.min(c.bottom,v.bottom);
    if(x1>x0&&y1>y0)out.push({left:x0,top:y0,right:x1,bottom:y1});}
  return out;}
// How far the pages scroll down (px, up negative) to bring badge box r into a part of view v that none of the boxes cs is over
// in r's columns, the scroll kept within [lo, hi] (what the pages can still scroll up and down): the least such distance, null
// where no part can hold it. A badge wholly in such a part already is 0 - it is not moved, as the browser leaves a control in
// view - and one brought in stands MARK_EDGE px clear of that part's ends where the part has the room. Pure.
/** @param {{left:number,top:number,right:number,bottom:number}} r @param {{left:number,top:number,right:number,bottom:number}} v
 * @param {{left:number,top:number,right:number,bottom:number}[]} cs @param {number} lo @param {number} hi @returns {number|null} */
function markShift(r,v,cs,lo,hi){let spans=[[v.top,v.bottom]];
  for(const c of cs){if(c.right<=r.left||c.left>=r.right)continue;
    spans=spans.flatMap(([t,b])=>c.bottom<=t||c.top>=b?[[t,b]]:[...(c.top>t?[[t,c.top]]:[]),...(c.bottom<b?[[c.bottom,b]]:[])]);}
  const h=r.bottom-r.top; let best=/** @type {number|null} */(null);
  for(const [t,b] of spans){if(b-t<h)continue; const e=r.top>=t&&r.bottom<=b?0:Math.min(MARK_EDGE,(b-t-h)/2);
    const dy=Math.min(hi,Math.max(lo,r.top<t+e?r.top-t-e:r.bottom>b-e?r.bottom-b+e:0));
    if(r.top-dy<t-0.5||r.bottom-dy>b+0.5)continue;   // the pages end before the badge gets there
    if(best===null||Math.abs(dy)<Math.abs(best))best=dy;}
  return best;}
function markCoverSkip(){const L=$('#left'); if(!L)return; const v=markView(),cs=markCoverBoxes(v),lo=-L.scrollTop,hi=L.scrollHeight-L.clientHeight-L.scrollTop;
  const bs=/** @type {HTMLElement[]} */($$('.mark button.mark-jump'));
  const stops=bs.map(b=>{const r=b.getBoundingClientRect(); if(!r.width)return 0; const cx=r.left+r.width/2,cy=r.top+r.height/2;
    if(cx>=v.left&&cx<v.right&&cy>=v.top&&cy<v.bottom)return cs.some(c=>cx>=c.left&&cx<c.right&&cy>=c.top&&cy<c.bottom)?-1:0;   // in view: covered or not
    return markShift(r,v,cs,lo,hi)===null?-1:0;});   // out of view: a stop while the pages can bring it to where it shows
  bs.forEach((b,i)=>{if(b.tabIndex!==stops[i])b.tabIndex=stops[i];});
  for(const t of [TIP_AT&&TIP_AT.el,tipEl])if(t instanceof HTMLElement&&t.tabIndex<0&&t.matches('.mark button.mark-jump')){hideTip(); break;}}
// Scrolls the pages to bring badge b to where it shows (markShift), when they can. It shows something, so a jump on its way
// ends first (pvShow): its settling would glide the pages back.
/** @param {HTMLElement} b */
function markReveal(b){const L=$('#left'),v=markView(),r=b.getBoundingClientRect(); if(!r.width)return;
  const dy=markShift(r,v,markCoverBoxes(v),-L.scrollTop,L.scrollHeight-L.clientHeight-L.scrollTop); if(!dy)return;
  pvShow(); L.scrollBy({top:dy,behavior:'instant'});}
// Tab and Shift+Tab bring the badge they reach to where it shows. The browser scrolls a focused control into the pages' box
// only, and on the tablet's or the phone's sheet, under its status line or its closed bar, that was out of sight: the focus
// stayed under the cover and its description over it. The key moves the focus as its default action, in its own task, so a
// focus that arrives while MARK_TAB is set is the walk's; a focus a script puts on a badge (focusPlace, without a scroll) is
// left where it is. The focus events come before the browser's own scroll for the focus, which then finds the badge in view.
let MARK_TAB=false;
/** @param {KeyboardEvent} e */
function markTabKey(e){if(e.key!=='Tab')return; MARK_TAB=true; setTimeout(()=>{MARK_TAB=false;},0);}
document.addEventListener('keydown',markTabKey,true);
$('#left').addEventListener('focusin',e=>{const b=e.target; if(!MARK_TAB||!(b instanceof HTMLElement)||!b.matches('.mark button.mark-jump'))return;
  markReveal(b);});
// What the covers cover changes without the marks being drawn again: the sheet opens, closes or is dragged to another height,
// the status line comes or goes, the overlay panel slides in, the window is resized, or the pages scroll under them. The
// covers' sizes are watched (the sheet's open and closed heights differ, a status line goes from none to its line); a scroll
// asks again at most once a frame. The keyboard's focus on a badge a cover has come over (the sheet a press of Enter on it opened, Ctrl+\ or
// a height chosen) is brought out again, as the keyboard's focus in a field is kept above the touch keyboard; a badge the
// person scrolls under a cover keeps the focus where it is, as a control scrolled out of the window does, and only its
// description goes - scrolling the pages back would undo the person's own scroll, and moving the focus would lose their place
// in the Tab order. The next Tab goes on from it.
function markCoversMoved(){markCoverSkip(); const a=document.activeElement;
  if(a instanceof HTMLElement&&a.tabIndex<0&&a.matches('.mark button.mark-jump')&&keyInput())markReveal(a);}
if(window.ResizeObserver){const o=new ResizeObserver(markCoversMoved); for(const s of MARK_COVERS){const e=$(s); if(e)o.observe(e,{box:'border-box'});}}
// The overlay panel slides in and out by its offset, its size unchanged (responsive.css mid-panel-in, side-panel.css side-in):
// the observer hears of the panel only while it is still off the pages, so the slide's end asks again.
$('#right').addEventListener('animationend',e=>{if(e.target===e.currentTarget)markCoversMoved();});
let MARK_COVER_TICK=0;
$('#left').addEventListener('scroll',()=>{if(MARK_COVER_TICK)return;
  MARK_COVER_TICK=requestAnimationFrame(()=>{MARK_COVER_TICK=0; markCoverSkip();});},{passive:true});
// How far each mark badge's press area may reach on each side (docs/handbook/viewer.md §모바일 레이아웃): boxes are the badges'
// drawn boxes {x,y,w,h} in one coordinate space and reach the press area's full size.
// Two badges whose press areas would overlap split the gap between their drawn boxes in half, along the axis on which their
// centres are further apart - so a press goes to the nearer badge, and a badge with no close neighbour keeps its whole area.
// Returns one {t,r,b,l} per box: the room in px on that side, or null where no neighbour limits it; 0 where the drawn
// boxes touch or overlap. Pure.
function markHitRooms(boxes,reach){const rooms=boxes.map(()=>({t:null,r:null,b:null,l:null}));
  const cut=(room,side,v)=>{room[side]=room[side]===null?v:Math.min(room[side],v);};
  boxes.forEach((a,i)=>{for(let j=i+1;j<boxes.length;j++){const b=boxes[j];
    const dx=b.x+b.w/2-(a.x+a.w/2),dy=b.y+b.h/2-(a.y+a.h/2); if(Math.abs(dx)>=reach||Math.abs(dy)>=reach)continue;
    if(Math.abs(dy)>=Math.abs(dx)){const v=Math.max(0,(Math.abs(dy)-(a.h+b.h)/2)/2); cut(rooms[i],dy>=0?'b':'t',v); cut(rooms[j],dy>=0?'t':'b',v);}
    else{const v=Math.max(0,(Math.abs(dx)-(a.w+b.w)/2)/2); cut(rooms[i],dx>=0?'r':'l',v); cut(rooms[j],dx>=0?'l':'r',v);}}});
  return rooms;}
// Gives every drawn badge its sides' room (markHitRooms) as --room-t/-r/-b/-l, which the badge's ::after caps its reach by
// (components.css); a side no neighbour limits has no property and reaches the whole way. The boxes are read in the
// viewport, so badges on two pages are neighbours too; the press area is the touch one, 44px (a mouse's 24px lies inside it).
// Badges that are not laid out (the changes view hides the pages) have no boxes to read: nothing is set, and setViewMode
// measures when the pages show again.
function markHitSides(){const bs=/** @type {HTMLElement[]} */($$('.mark button.mark-jump')); if(bs.some(b=>!b.getClientRects().length))return;
  const rooms=markHitRooms(bs.map(b=>{const r=b.getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height};}),44);
  bs.forEach((b,i)=>{const r=rooms[i],px=v=>v===null?'':v+'px';   // '' takes the property off
    b.style.setProperty('--room-t',px(r.t)); b.style.setProperty('--room-r',px(r.r)); b.style.setProperty('--room-b',px(r.b)); b.style.setProperty('--room-l',px(r.l));});}
// Draws one mark per open or awaiting-review pin of this document on its page: where the pin's element is now for a figure
// pin (pinPlace), else where it was pinned, then decides each badge's side (markBadgeSides) and puts a save's or an append's
// undo chip back on its mark (drawChips). A pin without a usable box or page draws nothing.
/** Draw native, named pin badge buttons at the current mark coordinates, preserving mark and undo-chip geometry. */
// A pin a page verdict line shows (pvShows) draws no page-size box: the line under its page says it (drawPageVerdicts, first).
function marks(){
  if(isMdDoc()){mdMarks(); drawChips(); return;}   // the Markdown surface marks its lines (md-surface.js)
  $$('.mark').forEach(m=>m.remove()); drawPageVerdicts();
  // Awaiting-review pins are also drawn as purple marks - so the reviewer can see right there what was fixed (unrelated to an open pin's overlap/editing).
  // A figure pin is drawn where the server found its element in this build (see pinPlace), and a found element is no estimate.
  PINS.concat(REVIEW_ALL.filter(p=>pdoc(p)===DOC)).forEach(p=>{const at=pinPlace(p),el=document.getElementById('p'+at.page); if(!el||!isFrac(at.frac))return; if(pvShows(p))return;
    const est=isEstimated(p)&&!hasMark(p),lost=p.stale||elLost(p);
    const m=document.createElement('div'); m.className='mark'+(lost?' st':'')+(est?' est':'')+(pinState(p)===PIN_STATE.REVIEW?' rv':''); m.dataset.pin=String(p.id); m.dataset.fx=String(at.frac[0]);
    Object.assign(m.style,{left:at.frac[0]*100+'%',top:at.frac[1]*100+'%',width:at.frac[2]*100+'%',height:at.frac[3]*100+'%'});
    const n=String(p.note||'').replace(/\s+/g,' ').trim();
    const tip='#'+p.id+' · '+(n?(n.length>60?n.slice(0,60)+'…':n):tr('(메모 없음)'))+(est?' '+tr('(PDF가 새로 만들어져 위치는 추정입니다)'):'')+(elLost(p)?' · '+tr('요소 잃음'):'');
    setHtml(m,html`<button type="button" class="mark-jump" translate="no" data-act="mark-jump" data-id="${p.id}" aria-label="${tl('핀 #{id} 카드로 이동',{id:p.id})}" data-tip="${tip}">${p.id}</button>`); el.appendChild(m);});   // the tip carries the note
  markBadgeSides(); drawChips();
}
// Clicking a badge scrolls to and flashes the card (never calls pick). The mark box itself has pointer-events:none, so
// a drag over it still becomes a new selection - only the badge button needs to block mousedown.
$('#doc').addEventListener('mousedown',e=>{
  if(e.target.closest('.mark [data-act=mark-jump]')){e.stopPropagation();e.preventDefault();}
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
  const el=/** @type {HTMLElement} */(document.querySelector('.pin[data-id="'+id+'"]')); if(!el)return;
  el.scrollIntoView({behavior:SMOOTH,block:'nearest'});
  $$('.pin.cur').forEach(x=>{if(x!==el)x.classList.remove('cur');});
  clearTimeout(el._curT);
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('cur','flash');
  el._curT=setTimeout(()=>el.classList.remove('cur','flash'),1200);
}
// A '#12' link in text: expands and scrolls to that pin's card/archive row, then flashes it. If it's on another document, '모든 문서' is turned on.
/** @param {number} id @param {boolean} [focus] - by keyboard: the focus goes to the card (its number) */
function gotoPinRef(id,focus){const p=findAnyPin(id); if(!p){if(DROPPED.some(x=>x.id===id))openTrash(id); return;}
  const st=pinState(p);
  if(multiDoc()&&DOC&&pdoc(p)!==DOC)SHOW_ALL=true;
  if(st===PIN_STATE.DONE)SEC.done=true; else{OPEN_CARDS.add(id); SEC[st===PIN_STATE.REVIEW?'review':'open']=true;} savePrefs({sec:SEC});
  setSide(true); drawPins();
  requestAnimationFrame(()=>{const el=/** @type {HTMLElement} */(document.querySelector('.pin[data-id="'+id+'"],.arc-row[data-id="'+id+'"]')); if(!el)return;
    el.scrollIntoView({behavior:SMOOTH,block:'nearest'}); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    clearTimeout(el._flT); el._flT=setTimeout(()=>el.classList.remove('flash'),1200);
    if(focus)focusCard(id);});}
// The pin id beside the card that holds control a - the next card in its section, else the one before - or null: where the
// focus goes when that card leaves by a keyboard press ([삭제], [지우기]).
/** @param {HTMLElement} a @returns {number|null} */
function cardNeighbour(a){const c=a.closest('.pin.card'); if(!c)return null; let n=c.nextElementSibling; while(n&&!n.matches('.pin.card'))n=n.nextElementSibling;
  let b=c.previousElementSibling; while(b&&!b.matches('.pin.card'))b=b.previousElementSibling; const t=/** @type {HTMLElement|null} */(n||b); return t?Number(t.dataset.id):null;}
// Puts the focus on pin id's card - its number (a button) - when it is drawn.
/** @param {number} id */
function focusCard(id){const n=/** @type {HTMLElement|null} */(document.querySelector('.pin[data-id="'+id+'"] .n.go,.arc-row[data-id="'+id+'"] .n')); if(n)n.focus({preventScroll:true});}
// Scrolls the mark of pin id into view and flashes it (switching to the pin's document first); a pin whose mark is not drawn
// scrolls to the page the mark would be on.
function jumpPin(id){if(viaDoc(id,jumpPin))return; const p=PINS.find(x=>x.id===id)||REVIEW_ALL.find(x=>x.id===id&&pdoc(x)===DOC);
  if(!p){const q=REVIEW_ALL.find(x=>x.id===id); if(q&&docInfo(pdoc(q))){const k=pdoc(q),opening=switchDoc(k),visit=SWITCHSEQ;
    opening.then(()=>{if(DOC===k&&visit===SWITCHSEQ)jumpPin(id);});} return;}
  if(document.body.classList.contains('revision-open'))setViewMode(VIEW_MODE.MANUSCRIPT);
  if(jumpPv(id))return;   // a pin its page verdict line shows: the line
  if(LAYOUT===LAYOUT_MODE.NARROW)setSide(false);   // collapsed first so the sheet doesn't cover the page, then measured
  if(isMdDoc()){mdJump(id); return;}   // its first line on the Markdown surface
  const m=/** @type {HTMLElement} */(document.querySelector('.mark[data-pin="'+id+'"]'));
  if(m){
    const L=$('#left'),lr=L.getBoundingClientRect(),mr=m.getBoundingClientRect();
    pvShow(); L.scrollTop+=(mr.top-(lr.top+lr.height*0.30));
    m.classList.remove('flash');void m.offsetWidth;m.classList.add('flash');
  } else {
    arrivePage(pinPlace(p).page);   // the page's top, or a figure page's figure
  }
}
// Hovering a card highlights its mark, along with any overlapping counterpart marks.
/** @param {Pin} p */
function markIdsFor(p){return [p.id].concat((p.rel||[]).map(x=>x.id));}
$('#pins').addEventListener('mouseover',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.add('hi');});});
$('#pins').addEventListener('mouseout',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.remove('hi');});});
