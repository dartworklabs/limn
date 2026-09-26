function card(p){
  const loc='L'+p.lo+'-L'+p.hi,name=p.name||String(p.file||'').split('/').pop(),tags=[];   // loc stays in the copy format
  if(p.stale)tags.push('<span class="badge badge-warning" data-tip="'+esc(T.stale)+'">'+ic('triangle-alert')+'위치 잃음</span>');
  else{const m=/^moved ([+-]\d+)$/.exec(p.sync||''); if(m)tags.push('<span class="badge" data-tip="'+
    esc(tl('원고가 고쳐져 {n}줄 밀렸고, 핀을 찍을 때 떠 둔 첫·끝 문장으로 새 위치를 다시 찾았습니다',{n:m[1].replace('+','')}))+'">'+ic('move-vertical')+esc(tl('줄 {delta} 이동',{delta:m[1]}))+'</span>');}
  const claimed=claimActive(p);
  if(claimed)tags.push(claimTag(p));
  if(p.edited_at)tags.push('<span class="badge" data-tip="'+esc(tl('저장한 뒤 메모나 범위를 고쳤습니다({when})',{when:p.edited_at.slice(11,16)+
    (p.edited_by?' · '+who(p.edited_by):'')}))+'">'+ic('pencil')+esc(tr('수정됨'))+'</span>');
  const closedCard=pinState(p)!=='open';   // overlap/location-confidence badges are meaningless on an awaiting-review/done card (line matching doesn't run, QA)
  const rb=closedCard?null:relBadge(p.rel,p);
  if(rb)tags.push('<span class="badge" data-tip="'+esc(tl(rb.rel==='partial'?'핀 #{id}{p} 줄 범위가 일부 겹칩니다. 참고만 하고 따로 고쳐도 됩니다':
    '핀 #{id}{p} 같은 곳을 가리킵니다. 한 번에 고치고 함께 닫는 편이 낫습니다',{id:rb.id,p:josa(rb.id,'과','와')}))+'">'+esc(rb.label)+'</span>');
  const v=closedCard?null:viaTag(p); if(v)tags.push('<span class="badge'+(v.low?' badge-warning':'')+'" data-tip="'+esc(v.tip)+'">'+esc(v.t)+'</span>');
  const tip=esc(authorTip(p));
  const au=p.author?'<span class="au" data-tip="'+tip+'">'+avatar(p.author)+'<span class="au-n">'+esc(who(p.author))+(isMe(p.author)?'<span class="me-tag"> (나)</span>':'')+'</span></span>'
    :'<span class="au old" data-tip="'+tip+'">기록 전</span>';
  const editing=!!(EDIT&&EDIT.id===p.id),open=OPEN_CARDS.has(p.id);
  // Header line: number/line-range/page on the left, author/collapse on the right. Badges (.tags) drop to one line below the header.
  // compact accordion: a collapsed card shows only number/location/page/the note's first line (.sum); clicking expands badges/note/buttons (CSS).
  // In wide, .sum and the collapse button are hidden and the card is always expanded. Actions form an equal-width grid; only [완료] is emphasized, [삭제] is the destructive color.
  const first=String(p.note||'').split('\n')[0].trim();
  // Collapsed card's (compact) note preview: up to two lines on its own line below the header. It used to only get the
  // leftover width after the number/location inside the header's single line, clipping to '[C...', and an awaiting-review
  // card's prefixed '내 확인 차례 · ' ate even more of that width (QA 2026-09-24). Review status is conveyed by the dot color.
  const sum='<div class="sum" data-act="card-toggle">'+(first?fmtText(first,p.mentions):'<span class="dim">(메모 없음)</span>')+'</div>';
  if(isRegion(p))tags.unshift('<span class="badge" data-tip="보기 전용 PDF의 핀 — 줄 번호 없이 쪽·영역과 영역 글자로 가리킵니다">보기 전용</span>');
  if(isQuestion(p))tags.unshift('<span class="badge badge-question" data-tip="'+esc(T.question)+'">'+ic('circle-question-mark')+'질문</span>');
  const adr=p.assignee?'':addressedTag(p); if(adr)tags.push(adr);   // a pin with a recorded assignee already says the same thing via the header's assignee chip
  const fyi=fyiTag(p); if(fyi)tags.push(fyi);   // a fix pin's FYI @-tags - this line once sat after the comment above and never executed (QA 2026-09-24)
  const rv=pinState(p)==='review';
  if(rv)tags.unshift('<span class="badge badge-review" data-tip="'+esc(tr(T.review)+' · '+tl('닫은 쪽: {name}',{name:who(p.closed_by)||'?'})+' · '+(p.done_at||''))+'">'+ic('eye')+esc(reviewerLabel(p))+'</span>');
  const ro=!rv&&reopenedTurn(p);
  if(ro)tags.unshift('<span class="badge badge-reopen" data-tip="'+esc(tl('검토에서 되돌아온 핀 — {name} · {time}',{name:who(ro.by)||'?',time:arcTime(ro.at)})+(ro.text?' · '+tl('이유: {text}',{text:ro.text}):''))+'">'+ic('rotate-ccw')+'다시 열림</span>');
  const nr=replyCount(p);
  const thn=nr?'<span class="th-n" role="button" tabindex="0" data-act="reply-open" aria-label="'+esc(tl('답글 {n}건 — 답글 쓰기',{n:nr}))+'" data-tip="'+esc(tl('이 핀의 답글 {n}건 — 누르면 카드를 펴고 답글 칸을 엽니다',{n:nr}))+'">'+ic('message-square')+nr+'</span>':'';
  if(rv)return '<div class="pin card review'+(open?' open':'')+'" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'">'+
    '<div class="row head">'+stDot(rv?'review':p.stale?'lost':claimed?'claimed':'open')+'<span class="n go" role="button" tabindex="0" data-act="view" data-tip="'+esc(T.n)+'">#'+p.id+'</span>'+docChip(p)+
    '<span class="loc" tabindex="0" data-copy="'+esc(isRegion(p)?locCopy(p):name+' '+loc)+'" data-tip="'+esc(isRegion(p)?'영역이 있는 PDF 쪽. 클릭하면 복사':T.loc)+'">'+locText(p)+'</span>'+
    '<span class="pg-link" tabindex="0" data-act="view" data-tip="클릭하면 그 쪽으로 이동">'+esc(tl('{page}쪽',{page:p.page}))+'</span>'+
    '<span class="sp"></span><span class="h-meta">'+assignChip(p)+thn+au+'</span>'+
    '<button class="btn-icon btn-sm btn-ghost cmp b-fold" data-act="card-toggle" aria-expanded="'+open+'" aria-label="'+(open?'카드 접기':'카드 펼치기')+'">'+ic(open?'chevron-down':'chevron-right')+'</button></div>'+
    sum+
    '<div class="tags">'+tags.join('')+'</div>'+
    '<div class="note">'+(p.note?fmtText(p.note,p.mentions):'<span class="dim">(메모 없음)</span>')+'</div>'+
    threadHtml(p,LAYOUT==='wide')+
    '<div class="acts">'+
    '<button class="btn-sm b-change" data-act="change" data-tip="'+esc(T.change)+'">변경 보기</button>'+
    '<button class="btn-sm b-reply" data-act="reply-open" data-tip="'+esc(T.reply)+'">답글</button>'+
    '<button class="btn-sm b-confirm'+(isMe(p.author)?' btn-soft':'')+'" data-act="confirm" data-tip="'+esc(T.confirm)+'">확인</button>'+
    '</div></div>';
  return '<div class="pin card'+(p.stale?' st':'')+(claimed?' claimed':'')+(editing?' editing':'')+(open?' open':'')+'" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'">'+
    '<div class="row head">'+stDot(rv?'review':p.stale?'lost':claimed?'claimed':'open')+'<span class="n go" role="button" tabindex="0" data-act="view" data-tip="'+esc(T.n)+'">#'+p.id+'</span>'+docChip(p)+
    '<span class="loc" tabindex="0" data-copy="'+esc(isRegion(p)?locCopy(p):name+' '+loc)+'" data-tip="'+esc(isRegion(p)?'영역이 있는 PDF 쪽. 클릭하면 복사':T.loc)+'">'+locText(p)+'</span>'+
    '<span class="pg-link" tabindex="0" data-act="view" data-tip="클릭하면 그 쪽으로 이동">'+esc(tl('{page}쪽',{page:p.page}))+'</span>'+
    '<span class="sp"></span><span class="h-meta">'+assignChip(p)+thn+au+'</span>'+
    '<button class="btn-icon btn-sm btn-ghost cmp b-fold" data-act="card-toggle" aria-expanded="'+(open||editing)+'" aria-label="'+(open?'카드 접기':'카드 펼치기')+'">'+ic(open||editing?'chevron-down':'chevron-right')+'</button></div>'+
    sum+
    '<div class="tags">'+tags.join('')+'</div>'+
    (editing?'<div class="edit-slot"></div>':
    '<div class="note" data-act="edit" data-tip="클릭하면 메모와 범위를 고칩니다">'+(p.note?fmtText(p.note,p.mentions):'<span class="dim">(메모 없음)</span>')+'</div>'+
    threadHtml(p,LAYOUT==='wide')+
    '<div class="acts"><button class="btn-sm b-view" data-act="view" data-tip="'+esc(T.view)+'">보기</button>'+
    '<button class="btn-sm b-edit" data-act="edit" data-tip="'+esc(T.edit)+'">수정</button>'+
    '<button class="btn-sm b-reply" data-act="reply-open" data-tip="'+esc(T.reply)+'">답글</button>'+
    (claimed?'<button class="btn-sm b-unclaim" data-act="unclaim" data-tip="'+esc('처리 중 표시를 풉니다(에이전트가 멈췄거나 잘못 잡은 경우)')+'">풀기</button>':'')+
    '<button class="btn-sm btn-destructive b-drop" data-act="drop" data-tip="'+esc(T.drop)+'">삭제</button>'+
    '<button class="btn-sm btn-soft b-close" data-act="close" data-tip="'+esc(T.close)+'">완료</button>'+
    '</div>')+'</div>';
}
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
function relSpan(s,cls,tip){return '<span class="rt'+(cls?' '+cls:'')+'" data-at="'+esc(s||'')+'" data-tip="'+esc((tip?tip+' ':'')+(s||'?'))+'">'+esc(relTime(s))+'</span>';}
function tickRel(){if(document.hidden)return; $$('.rt[data-at]').forEach(e=>{const v=relTime(e.dataset.at); if(e.textContent!==v)e.textContent=v;});}
setInterval(tickRel,60000);
function arcTime(s){s=String(s||''); return /^\d{4}-\d\d-\d\d \d\d:\d\d/.test(s)?s.slice(5,16):s;}
function arcLoc(p){const name=p.name||String(p.file||p.pdf||'').split('/').pop();
  return '<span class="loc" tabindex="0" data-copy="'+esc(isRegion(p)?locCopy(p):name+' L'+p.lo+'-L'+p.hi)+'" data-tip="'+esc(T.loc)+'">'+esc(isRegion(p)?tl('쪽 {page} 영역',{page:p.page}):rng(p.lo,p.hi))+'</span>';}
function arcLine(key,text,tip,logins){const open=ARC_OPEN.has(key);
  return '<span class="arc-reply'+(open?' open':'')+'" role="button" tabindex="0" data-act="arc-toggle" data-key="'+esc(key)+'" aria-expanded="'+open+'" data-tip="'+esc(tip)+'">'+fmtText(text,logins)+'</span>';}
function allMentions(p){const out=(p.mentions||[]).slice(); threadOf(p).forEach(m=>(m.mentions||[]).forEach(l=>{if(!out.includes(l))out.push(l);})); return out;}
function doneCard(p){
  const ref=hasRef(p.close_ref)?'<span class="badge arc-ref" data-tip="닫을 때 남긴 참조 — 같은 값이면 같은 처리에 딸린 핀입니다">'+esc(p.close_ref)+'</span>':'';
  const reply=p.close_reply?arcLine('r:'+p.id,p.close_reply,'닫으며 남긴 설명 — 누르면 펼치고 접습니다',allMentions(p)):'<span class="arc-reply none">설명 없이 닫힘</span>';
  const oo=ARC_OPEN.has('o:'+p.id);
  // If the thread is longer than a single close record (there was a reply/reopen), it expands via [스레드 N] - with only
  // one record, it's the same as the single answer line above. [답글] opens the same reply box as a card (openReply): a person's
  // reply on a done pin reopens it by the server rule, and the line under the box says so before sending. The thread is kept
  // expanded while replying so the box is visible.
  const replying=REPLY&&REPLY.id===p.id;
  const th=threadOf(p),tn=th.length>1||(th.length>0&&!th[0].ev),to=(tn&&ARC_OPEN.has('t:'+p.id))||replying;
  return '<div class="arc-row done" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'" data-tip="'+esc(authorTip(p))+'">'+
    '<div class="arc-l1">'+ic('check')+'<span class="n" data-tip="완료한 핀 번호">#'+p.id+'</span>'+docChip(p)+arcLoc(p)+ref+
    relSpan(p.done_at,'arc-t',tl('닫은 사람 {name} · 닫은 시각',{name:who(p.closed_by)||tr('기록 전')}))+'<span class="sp"></span>'+
    '<button class="btn-sm btn-secondary arc-b b-reply" data-act="reply-open" data-tip="'+esc(T.reply)+'">답글</button></div>'+
    '<div class="arc-l2">'+reply+(p.note?'<button class="arc-orig-t" data-act="arc-toggle" data-key="o:'+p.id+'" aria-expanded="'+oo+'" data-tip="핀을 남길 때 쓴 메모를 펼치고 접습니다">원래 요청</button>':'')+
    '<button class="arc-orig-t b-change" data-act="change" data-tip="'+esc(T.change)+'">변경 보기</button>'+
    (tn?'<button class="arc-orig-t" data-act="arc-toggle" data-key="t:'+p.id+'" aria-expanded="'+to+'" data-tip="답글과 닫기·다시 열기 이력을 펼치고 접습니다">'+esc(tl('스레드 {n}',{n:th.length}))+'</button>':'')+'</div>'+
    (p.note&&oo?'<div class="arc-orig"><b>원래 요청</b>'+fmtText(p.note,p.mentions)+'</div>':'')+
    (to?'<div class="arc-thread"><div class="thread">'+th.map((m,i)=>msgHtml(m,p.id+':'+i)).join('')+(replying?'<div class="reply-slot"></div>':'')+'</div></div>':'')+'</div>';}
// A Trash row (docs/handbook/viewer.md §휴지통): who deleted it and when, how many days are left before it is purged, [되살리기], and -
// for the owner only - [영구 삭제] (sent after its undo toast goes away, like a reply).
const TRASH_DAYS=30;
function trashDaysLeft(at,now,exp){if(typeof exp==='number')return Math.max(0,Math.ceil((exp*1000-(now==null?Date.now():now))/86400000));
  const m=/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(String(at||'')); if(!m)return null;
  const t=new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5]).getTime(); return Math.max(0,Math.ceil(TRASH_DAYS-((now==null?Date.now():now)-t)/86400000));}
function isOwner(){return !!(typeof META!=='undefined'&&META&&META.me&&META.me.role==='owner');}
function droppedCard(p){
  const line=p.note?arcLine('d:'+p.id,p.note,'삭제한 핀의 메모 — 누르면 펼치고 접습니다',p.mentions):'<span class="arc-reply none">(메모 없음)</span>';
  const left=trashDaysLeft(p.dropped_at,null,p.expires_ts);
  return '<div class="arc-row dropped" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'" data-tip="'+esc(authorTip(p))+'">'+
    '<div class="arc-l1">'+ic('trash-2')+'<span class="n" data-tip="삭제한 핀 번호">#'+p.id+'</span>'+docChip(p)+arcLoc(p)+
    relSpan(p.dropped_at,'arc-t',tl('삭제한 사람 {name} · 삭제한 시각',{name:who(p.dropped_by)||tr('기록 전')}))+
    '<span class="arc-sep" aria-hidden="true">·</span><span class="arc-t trash-by">'+esc(tl('{name} 삭제',{name:who(p.dropped_by)||tr('기록 전')}))+'</span>'+
    (left!=null?'<span class="arc-sep" aria-hidden="true">·</span><span class="arc-t trash-left" data-tip="'+esc(tl('{n}일이 지나면 저절로 지워집니다',{n:TRASH_DAYS}))+'">'+esc(tl('{n}일 뒤 지워짐',{n:left}))+'</span>':'')+'<span class="sp"></span>'+
    // a viewer reads the Trash but is offered no state change (the server answers 403 anyway) - not rendered, not only hidden
    '<span class="arc-acts">'+(isViewer()?'':'<button class="btn-sm btn-secondary arc-b b-restore" data-act="restore" data-tip="'+esc(T.restore)+'">되살리기</button>')+
    (isOwner()?'<button class="btn-sm arc-b btn-destructive b-purge" data-act="purge" data-tip="'+esc(T.purge)+'">영구 삭제</button>':'')+'</span></div>'+
    '<div class="arc-l2">'+line+'</div></div>';}
let TRASH_ALL=false;   // the Trash shows every document while open for another document's pin - the list's own filter (SHOW_ALL) is untouched
function drawTrash(){const L=TRASH_ALL?DROPPED:listDropped(),box=$('#trash-list'); if(!box)return;
  $('#trash-note').textContent=tl('삭제한 핀은 {n}일 동안 여기 있다가 저절로 지워집니다. 되살리면 같은 번호로 돌아옵니다',{n:TRASH_DAYS});
  box.innerHTML=L.length?L.slice().reverse().filter(p=>!PURGING.has(p.id)).map(droppedCard).join(''):'<div class="dim">'+esc(tr('휴지통이 비어 있습니다'))+'</div>';}
function openTrash(flashId){const d=$('#trash');
  if(flashId!=null&&!listDropped().some(p=>p.id===flashId)&&DROPPED.some(p=>p.id===flashId))TRASH_ALL=true;   // another document's pin
  drawTrash(); if(!d.open){hideTip(); d.showModal(); toastHost();}
  if(flashId!=null)requestAnimationFrame(()=>{const el=document.querySelector('#trash .arc-row[data-id="'+flashId+'"]'); if(!el)return;
    el.scrollIntoView({block:'nearest'}); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');});}
$('#trash').addEventListener('close',()=>{TRASH_ALL=false;});
$('#trash').addEventListener('click',e=>{const d=$('#trash'); if(e.target!==d)return; const r=d.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});
