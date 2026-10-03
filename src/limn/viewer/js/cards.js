// The open or awaiting-review pin card: header, badges, note and actions. A figure pin's page link follows its element, and a
// lost element is flagged like a lost line. The note, its preview and the author's name are user text (translate="no"); the UI
// words drawn inside them are translated here.
/** @param {Pin} p */
function card(p){
  const loc='L'+p.lo+'-L'+p.hi,name=p.name||String(p.file||'').split('/').pop(),tags=[];   // loc stays in the copy format
  if(p.stale)tags.push(html`<span class="badge badge-warning" data-tip="${T.stale}">${ic('triangle-alert')}위치 잃음</span>`);
  else{const m=/^moved ([+-]\d+)$/.exec(p.sync||''); if(m)tags.push(html`<span class="badge" data-tip="${
    tl('원고가 고쳐져 {n}줄 밀렸고, 핀을 찍을 때 떠 둔 첫·끝 문장으로 새 위치를 다시 찾았습니다',{n:m[1].replace('+','')})}">${ic('move-vertical')}${tl('줄 {delta} 이동',{delta:m[1]})}</span>`);}
  const lostEl=elLostTag(p); if(lostEl)tags.push(lostEl);   // a figure pin whose element the re-rendered map no longer has
  const claimed=claimActive(p);
  if(claimed)tags.push(claimTag(p));
  if(p.edited_at)tags.push(html`<span class="badge" data-tip="${tl('저장한 뒤 메모나 범위를 고쳤습니다({when})',{when:p.edited_at.slice(11,16)+
    (p.edited_by?' · '+who(p.edited_by):'')})}">${ic('pencil')}${tr('수정됨')}</span>`);
  const closedCard=pinState(p)!==PIN_STATE.OPEN;   // overlap/location-confidence badges are meaningless on an awaiting-review/done card (line matching doesn't run, QA)
  const rb=closedCard?null:relBadge(p.rel,p);
  if(rb)tags.push(html`<span class="badge" data-tip="${tl(rb.rel===RANGE_REL.PARTIAL?'핀 #{id}{p} 줄 범위가 일부 겹칩니다. 참고만 하고 따로 고쳐도 됩니다':
    '핀 #{id}{p} 같은 곳을 가리킵니다. 한 번에 고치고 함께 닫는 편이 낫습니다',{id:rb.id,p:josa(rb.id,'과','와')})}">${rb.label}</span>`);
  const v=closedCard?null:viaTag(p); if(v)tags.push(html`<span class="badge${v.low?' badge-warning':''}" data-tip="${v.tip}">${v.t}</span>`);
  const tip=authorTip(p),me=isMe(p.author)?html`<span class="me-tag"> ${tr('(나)')}</span>`:'';
  const au=p.author?html`<span class="au" data-tip="${tip}">${avatar(p.author)}<span class="au-n" translate="no">${who(p.author)}${me}</span></span>`
    :html`<span class="au old" data-tip="${tip}">기록 전</span>`;
  const editing=!!(EDITOR.current&&EDITOR.current.id===p.id),open=OPEN_CARDS.has(p.id);
  // Header line: number/line-range/page on the left, author/collapse on the right. Badges (.tags) drop to one line below the header.
  // compact accordion: a collapsed card shows only number/location/page/the note's first line (.sum); clicking expands badges/note/buttons (CSS).
  // In wide, .sum and the collapse button are hidden and the card is always expanded. Actions form an equal-width grid; only [완료] is emphasized, [삭제] is the destructive color.
  const first=String(p.note||'').split('\n')[0].trim(),noNote=html`<span class="dim">${tr('(메모 없음)')}</span>`;
  // Collapsed card's (compact) note preview: up to two lines on its own line below the header. It used to only get the
  // leftover width after the number/location inside the header's single line, clipping to '[C...', and an awaiting-review
  // card's prefixed '내 확인 차례 · ' ate even more of that width (QA 2026-09-24). Review status is conveyed by the dot color.
  const sum=html`<div class="sum" translate="no" data-act="card-toggle">${first?fmtText(first,p.mentions):noNote}</div>`;
  if(isRegion(p)){const fb=figRegionBadge(p.el,isFigureKind((docInfo(pdoc(p))||{}).kind));   // a figure region: element without code, or map unreadable
    tags.unshift(fb?html`<span class="badge" data-tip="${fb.tip}">${fb.t}</span>`:html`<span class="badge" data-tip="보기 전용 PDF의 핀 — 줄 번호 없이 쪽·영역과 영역 글자로 가리킵니다">보기 전용</span>`);}
  if(isQuestion(p))tags.unshift(html`<span class="badge badge-question" data-tip="${T.question}">${ic('circle-question-mark')}질문</span>`);
  const adr=p.assignee?null:addressedTag(p); if(adr)tags.push(adr);   // a pin with a recorded assignee already says the same thing via the header's assignee chip
  const fyi=fyiTag(p); if(fyi)tags.push(fyi);   // a fix pin's FYI @-tags - this line once sat after the comment above and never executed (QA 2026-09-24)
  const rv=pinState(p)===PIN_STATE.REVIEW;
  if(rv)tags.unshift(html`<span class="badge badge-review" data-tip="${tr(T.review)+' · '+tl('닫은 쪽: {name}',{name:who(p.closed_by)||'?'})+' · '+(p.done_at||'')}">${ic('eye')}${reviewerLabel(p)}</span>`);
  const ro=!rv&&reopenedTurn(p);
  if(ro)tags.unshift(html`<span class="badge badge-reopen" data-tip="${tl('검토에서 되돌아온 핀 — {name} · {time}',{name:who(ro.by)||'?',time:arcTime(ro.at)})+(ro.text?' · '+tl('이유: {text}',{text:ro.text}):'')}">${ic('rotate-ccw')}다시 열림</span>`);
  // compact's head link (CSS shows it in place of #N, the line range and N쪽, diagnosis P6/U5): one 44px target that does what
  // [보기] does - the same data-act, so it also replaces the row's [보기] there.
  const page=tl('{page}쪽',{page:pinPlace(p).page});
  const go=html`<span class="go-all" role="button" tabindex="0" data-act="view" data-tip="${T.view}">#${p.id} · ${locText(p)} · ${page}</span>`;
  const nr=replyCount(p);
  const thn=nr?html`<span class="th-n" role="button" tabindex="0" data-act="reply-open" aria-label="${tl('답글 {n}건 — 답글 쓰기',{n:nr})}" data-tip="${tl('이 핀의 답글 {n}건 — 누르면 카드를 펴고 답글 칸을 엽니다',{n:nr})}">${ic('message-square')}${nr}</span>`:'';
  const dot=stDot(rv?CARD_DOT.REVIEW:p.stale||elLost(p)?CARD_DOT.LOST:claimed?CARD_DOT.CLAIMED:CARD_DOT.OPEN),unfold=open||(!rv&&editing);
  const head=html`<div class="row head">${dot}${go}<span class="n go" role="button" tabindex="0" data-act="view" data-tip="${T.n}">#${p.id}</span>${docChip(p)}\
<span class="loc" tabindex="0" data-copy="${isRegion(p)?locCopy(p):name+' '+loc}" data-tip="${isRegion(p)?'영역이 있는 PDF 쪽. 클릭하면 복사':T.loc}">${locText(p)}</span>\
<span class="pg-link" tabindex="0" data-act="view" data-tip="클릭하면 그 쪽으로 이동">${page}</span>\
<span class="sp"></span><span class="h-meta">${assignChip(p)}${thn}${au}</span>\
<button class="btn-icon btn-sm btn-ghost cmp b-fold" data-act="card-toggle" aria-expanded="${unfold}" aria-label="${open?'카드 접기':'카드 펼치기'}">${ic(unfold?'chevron-down':'chevron-right')}</button></div>\
${sum}<div class="tags">${tags}</div>`;
  if(rv)return html`<div class="pin card review${open?' open':''}" data-id="${p.id}" data-doc="${pdoc(p)}">${head}\
<div class="note" translate="no">${p.note?fmtText(p.note,p.mentions):noNote}</div>${threadHtml(p,LAYOUT===LAYOUT_MODE.WIDE)}\
<div class="acts"><button class="btn-sm b-change" data-act="change" data-tip="${T.change}">변경 보기</button>\
<button class="btn-sm b-reply" data-act="reply-open" data-tip="${T.reply}">답글</button>\
<button class="btn-sm b-confirm${isMe(p.author)?' btn-soft':''}" data-act="confirm" data-tip="${T.confirm}">확인</button></div></div>`;
  const body=editing?html`<div class="edit-slot"></div>`
    :html`<div class="note" translate="no" data-act="edit" data-tip="${tr('클릭하면 메모와 범위를 고칩니다')}">${p.note?fmtText(p.note,p.mentions):noNote}</div>\
${threadHtml(p,LAYOUT===LAYOUT_MODE.WIDE)}<div class="acts">${cardActs(claimed,LAYOUT!==LAYOUT_MODE.WIDE)}</div>`;
  return html`<div class="pin card${p.stale||elLost(p)?' st':''}${claimed?' claimed':''}${editing?' editing':''}${open?' open':''}" data-id="${p.id}" data-doc="${pdoc(p)}">${head}${body}</div>`;
}
// An open card's action row, in the order it is seen so that Tab follows it. wide: [보기] [수정] [답글] ([풀기]) [삭제] [완료], by name.
// compact (narrow and mid, any pointer): [삭제] [수정] ([풀기]) ...... [답글] [완료] - [보기] is the head's '#N · L… · N쪽' link, and
// [수정][풀기][삭제] show only their icon (the name stays in aria-label and the tooltip); CSS picks icon or name per layout.
function cardActs(claimed,compact){
  const b={view:html`<button class="btn-sm b-view" data-act="view" data-tip="${T.view}">보기</button>`,
    edit:html`<button class="btn-sm b-edit" data-act="edit" aria-label="수정" data-tip="${T.edit}">${ic('pencil')}<span class="lbl">수정</span></button>`,
    reply:html`<button class="btn-sm b-reply" data-act="reply-open" data-tip="${T.reply}">답글</button>`,
    unclaim:claimed?html`<button class="btn-sm b-unclaim" data-act="unclaim" aria-label="풀기" data-tip="처리 중 표시를 풉니다(에이전트가 멈췄거나 잘못 잡은 경우)">${ic('lock-open')}<span class="lbl">풀기</span></button>`:'',
    drop:html`<button class="btn-sm btn-destructive b-drop" data-act="drop" aria-label="삭제" data-tip="${T.drop}">${ic('trash-2')}<span class="lbl">삭제</span></button>`,
    close:html`<button class="btn-sm btn-soft b-close" data-act="close" data-tip="${T.close}">완료</button>`};
  return html`${(compact?['drop','edit','unclaim','reply','close']:['view','edit','reply','unclaim','drop','close']).map(k=>b[k])}`;}
// Archive row (docs/handbook/viewer.md §보관함): a closed/dropped pin is a flat, borderless, backgroundless row with faded text, not a card.
// The first line is icon/#number/location/reference/time/[다시 열기|되살리기]; the second line is one line of the agent's
// answer (close_reply) - truncated on overflow, expandable on click. The original request note is only shown by pressing
// [원래 요청]. The expanded state is kept in ARC_OPEN ('r:'|'o:'|'d:' + id) so it survives a redraw.
const ARC_OPEN=new Set();
// Relative time (docs/handbook/viewer.md §뜻과 모양): '방금'/'N분 전'/'N시간 전'/'N일 전', 'M-D' past a week. Absolute time is in the description (hover).
// The original string is kept in data-at and re-computed every 60 seconds (tickRel).
function relTime(s,now){s=String(s||''); const m=/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(s); if(!m)return s;
  const t=new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5]).getTime(),d=Math.max(0,((now==null?Date.now():now)-t)/60000);
  if(d<1)return tr('방금'); if(d<60)return tl('{n}분 전',{n:Math.floor(d)}); if(d<24*60)return tl('{n}시간 전',{n:Math.floor(d/60)}); if(d<7*24*60)return tl('{n}일 전',{n:Math.floor(d/1440)});
  return (+m[2])+'-'+(+m[3]);}
function relSpan(s,cls,tip){return html`<span class="rt${cls?' '+cls:''}" data-at="${s||''}" data-tip="${(tip?tip+' ':'')+(s||'?')}">${relTime(s)}</span>`;}
function tickRel(){if(document.hidden)return; $$('.rt[data-at]').forEach(e=>{const v=relTime(e.dataset.at); if(e.textContent!==v)e.textContent=v;});}
setInterval(tickRel,60000);
function arcTime(s){s=String(s||''); return /^\d{4}-\d\d-\d\d \d\d:\d\d/.test(s)?s.slice(5,16):s;}
// The location span of an archive row (done or trashed pin): 'L12-L18' for lines, '쪽 N 영역' for a region, N being the page
// its mark is on now (pinPlace); the copy text carries the same.
/** @param {Pin} p */
function arcLoc(p){const name=p.name||String(p.file||p.pdf||'').split('/').pop();
  return html`<span class="loc" tabindex="0" data-copy="${isRegion(p)?locCopy(p):name+' L'+p.lo+'-L'+p.hi}" data-tip="${T.loc}">${isRegion(p)?tl('쪽 {page} 영역',{page:pinPlace(p).page}):rng(p.lo,p.hi)}</span>`;}
// One expandable line of an archive row: text (a close reply or a deleted pin's note) is user text (translate="no"), so its
// Korean description tip is translated here.
function arcLine(key,text,tip,logins){const open=ARC_OPEN.has(key);
  return html`<span class="arc-reply${open?' open':''}" translate="no" role="button" tabindex="0" data-act="arc-toggle" data-key="${key}" aria-expanded="${open}" data-tip="${trMsg(tip)}">${fmtText(text,logins)}</span>`;}
/** @param {Pin} p */
function allMentions(p){const out=(p.mentions||[]).slice(); threadOf(p).forEach(m=>(m.mentions||[]).forEach(l=>{if(!out.includes(l))out.push(l);})); return out;}
// A done pin's archive row (docs/handbook/viewer.md §보관함): icon, #N, location, reference and time with [답글]; the close
// reply as one expandable line (user text) with [원래 요청], [변경 보기] and [스레드 N]; the original request and the thread
// when expanded (ARC_OPEN), the thread also while a reply box is open on it.
/** @param {Pin} p */
function doneCard(p){
  const ref=hasRef(p.close_ref)?html`<span class="badge arc-ref" data-tip="닫을 때 남긴 참조 — 같은 값이면 같은 처리에 딸린 핀입니다">${p.close_ref}</span>`:'';
  const reply=p.close_reply?arcLine('r:'+p.id,p.close_reply,'닫으며 남긴 설명 — 누르면 펼치고 접습니다',allMentions(p)):html`<span class="arc-reply none">설명 없이 닫힘</span>`;
  const oo=ARC_OPEN.has('o:'+p.id);
  // If the thread is longer than a single close record (there was a reply/reopen), it expands via [스레드 N] - with only
  // one record, it's the same as the single answer line above. [답글] opens the same reply box as a card (openReply): a person's
  // reply on a done pin reopens it by the server rule, and the line under the box says so before sending. The thread is kept
  // expanded while replying so the box is visible.
  const replying=REPLY&&REPLY.id===p.id;
  const th=threadOf(p),tn=th.length>1||(th.length>0&&!th[0].ev),to=!!((tn&&ARC_OPEN.has('t:'+p.id))||replying);
  const origT=p.note?html`<button class="arc-orig-t" data-act="arc-toggle" data-key="o:${p.id}" aria-expanded="${oo}" data-tip="핀을 남길 때 쓴 메모를 펼치고 접습니다">원래 요청</button>`:'';
  const threadT=tn?html`<button class="arc-orig-t" data-act="arc-toggle" data-key="t:${p.id}" aria-expanded="${to}" data-tip="답글과 닫기·다시 열기 이력을 펼치고 접습니다">${tl('스레드 {n}',{n:th.length})}</button>`:'';
  const orig=p.note&&oo?html`<div class="arc-orig" translate="no"><b>${tr('원래 요청')}</b>${fmtText(p.note,p.mentions)}</div>`:'';
  const thread=to?html`<div class="arc-thread"><div class="thread">${th.map((m,i)=>msgHtml(m,p.id+':'+i))}${replying?html`<div class="reply-slot"></div>`:''}</div></div>`:'';
  return html`<div class="arc-row done" data-id="${p.id}" data-doc="${pdoc(p)}" data-tip="${authorTip(p)}">\
<div class="arc-l1">${ic('check')}<span class="n" data-tip="완료한 핀 번호">#${p.id}</span>${docChip(p)}${arcLoc(p)}${ref}\
${relSpan(p.done_at,'arc-t',tl('닫은 사람 {name} · 닫은 시각',{name:who(p.closed_by)||tr('기록 전')}))}<span class="sp"></span>\
<button class="btn-sm btn-secondary arc-b b-reply" data-act="reply-open" data-tip="${T.reply}">답글</button></div>\
<div class="arc-l2">${reply}${origT}<button class="arc-orig-t b-change" data-act="change" data-tip="${T.change}">변경 보기</button>${threadT}</div>${orig}${thread}</div>`;}
// A Trash row (docs/handbook/viewer.md §휴지통): who deleted it and when, how many days are left before it is purged, [되살리기], and -
// for the owner only - [영구 삭제] (sent after its undo toast goes away, like a reply). The buttons follow the two lines in the
// markup; CSS sets them beside the meta line, or on a phone beside the note line (two lines, not three).
const TRASH_DAYS=30;
function trashDaysLeft(at,now,exp){if(typeof exp==='number')return Math.max(0,Math.ceil((exp*1000-(now==null?Date.now():now))/86400000));
  const m=/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(String(at||'')); if(!m)return null;
  const t=new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5]).getTime(); return Math.max(0,Math.ceil(TRASH_DAYS-((now==null?Date.now():now)-t)/86400000));}
function isOwner(){return !!(typeof META!=='undefined'&&META&&META.me&&META.me.role===ROLE.OWNER);}
// A Trash row: #N, location, when and by whom it was deleted and the days left, the note as one expandable line (user text),
// and [되살리기] (not for a viewer) and [영구 삭제] (the owner only) after the two lines.
/** @param {Pin} p */
function droppedCard(p){
  const line=p.note?arcLine('d:'+p.id,p.note,'삭제한 핀의 메모 — 누르면 펼치고 접습니다',p.mentions):html`<span class="arc-reply none">(메모 없음)</span>`;
  const left=trashDaysLeft(p.dropped_at,null,p.expires_ts),by=who(p.dropped_by)||tr('기록 전');
  const leftT=left!=null?html`<span class="arc-sep" aria-hidden="true">·</span><span class="arc-t trash-left" data-tip="${tl('{n}일이 지나면 저절로 지워집니다',{n:TRASH_DAYS})}">${tl('{n}일 뒤 지워짐',{n:left})}</span>`:'';
  // a viewer reads the Trash but is offered no state change (the server answers 403 anyway) - not rendered, not only hidden
  const restore=isViewer()?'':html`<button class="btn-sm btn-secondary arc-b b-restore" data-act="restore" data-tip="${T.restore}">되살리기</button>`;
  const purge=isOwner()?html`<button class="btn-sm arc-b btn-destructive b-purge" data-act="purge" data-tip="${T.purge}">영구 삭제</button>`:'';
  return html`<div class="arc-row dropped" data-id="${p.id}" data-doc="${pdoc(p)}" data-tip="${authorTip(p)}">\
<div class="arc-l1">${ic('trash-2')}<span class="n" data-tip="삭제한 핀 번호">#${p.id}</span>${docChip(p)}${arcLoc(p)}\
${relSpan(p.dropped_at,'arc-t',tl('삭제한 사람 {name} · 삭제한 시각',{name:by}))}\
<span class="arc-sep" aria-hidden="true">·</span><span class="arc-t trash-by">${tl('{name} 삭제',{name:by})}</span>${leftT}<span class="sp"></span>\
</div><div class="arc-l2">${line}</div><span class="arc-acts">${restore}${purge}</span></div>`;}
let TRASH_ALL=false;   // the Trash shows every document while open for another document's pin - the list's own filter (SHOW_ALL) is untouched
function drawTrash(){const L=TRASH_ALL?DROPPED:listDropped(),box=$('#trash-list'); if(!box)return;
  $('#trash-note').textContent=tl('삭제한 핀은 {n}일 동안 여기 있다가 저절로 지워집니다. 되살리면 같은 번호로 돌아옵니다',{n:TRASH_DAYS});
  setHtml(box,L.length?html`${L.slice().reverse().filter(p=>!PURGING.has(p.id)).map(droppedCard)}`:html`<div class="dim">${tr('휴지통이 비어 있습니다')}</div>`);}
function openTrash(flashId){const d=$('#trash');
  if(flashId!=null&&!listDropped().some(p=>p.id===flashId)&&DROPPED.some(p=>p.id===flashId))TRASH_ALL=true;   // another document's pin
  drawTrash(); if(!d.open){hideTip(); showSheet(d); toastHost();}
  if(flashId!=null)requestAnimationFrame(()=>{const el=/** @type {HTMLElement} */(document.querySelector('#trash .arc-row[data-id="'+flashId+'"]')); if(!el)return;
    el.scrollIntoView({block:'nearest'}); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');});}
$('#trash').addEventListener('close',()=>{TRASH_ALL=false;});
$('#trash').addEventListener('click',e=>{const d=$('#trash'); if(e.target!==d)return; const r=d.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});
