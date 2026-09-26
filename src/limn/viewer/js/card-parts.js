// ------------------------------------------------ Pin card parts: people, badges, claims, @-tags and #refs in text, the thread
function who(a){if(a&&a.login==='local')return tr(a.name||'로컬/에이전트'); return (a&&(a.name||a.login))||'';}   // the stored local name is Korean ('로컬/에이전트'); shown in the UI language
const BADPIC=new Set();   // an avatar URL that has already failed is never requested again (otherwise console errors would pile up on every re-render)
// A person = a photo or an initial circle (primary color); local/agent = a faded circle with a robot icon - distinguishes people from agents at a glance.
function isAgent(a){return !!a&&(a.login==='local'||String(a.login).startsWith('agent:'));}
function avatar(a){if(!a||!(a.name||a.login))return ''; if(isAgent(a))return '<span class="av i agent" aria-hidden="true">'+ic('bot')+'</span>';
  const ini=esc((who(a).trim()[0]||'?').toUpperCase());
  return a.pic&&!BADPIC.has(a.pic)?'<img class="av" src="'+esc(a.pic)+'" alt="" referrerpolicy="no-referrer" data-ini="'+ini+'">'
    :'<span class="av i" aria-hidden="true">'+ini+'</span>';}
document.addEventListener('error',e=>{const t=e.target;
  if(t&&t.tagName==='IMG'&&t.classList.contains('av')){BADPIC.add(t.getAttribute('src')); const s=document.createElement('span');s.className='av i';
    s.textContent=t.dataset.ini||'?';t.replaceWith(s);}},true);
function authorTip(p){let s=tl('작성: {name} · {at}',{name:p.author?who(p.author):tr('기록 전'),at:p.at||'?'});
  if(p.edited_at)s+=' / '+tl('수정: {name} · {at}',{name:who(p.edited_by)||tr('기록 전'),at:p.edited_at}); return s;}
// P0b-03: one representative among the rel entries - if there's an inside (the outer pin with the smallest range),
// otherwise the smallest-id partial. Must follow the same rule as the server's rel_badge() (pins.md) so card tags and
// pins.md rows never disagree - since a rel entry is only {id,rel}, the range is looked up by id from PINS (all currently loaded open pins).
// The badge wording is phrased to be self-explanatory: '#20과 같은 범위' > '#20 범위 안' > '#20과 일부 겹침'. Same-range is distinguished using p's (this pin's) lo/hi.
function josa(n,c,v){const d=String(n).slice(-1); return d==='0'||'13678'.includes(d)?c:v;}
function relBadge(rel,p){
  if(!rel||!rel.length)return null;
  const byId=new Map(PINS.map(p=>[p.id,p]));
  if(p){const same=rel.filter(x=>{const o=byId.get(x.id); return o&&o.lo===p.lo&&o.hi===p.hi;});
    if(same.length){const n=Math.min.apply(null,same.map(x=>x.id)); return {id:n,rel:'equal',label:tl('#{id}{p} 같은 범위',{id:n,p:josa(n,'과','와')})};}}
  const insides=rel.filter(x=>x.rel==='inside');
  if(insides.length){
    const span=x=>{const o=byId.get(x.id); return o?(o.hi-o.lo):Number.MAX_SAFE_INTEGER;};
    const best=insides.reduce((a,b)=>{const sa=span(a),sb=span(b);
      return (sb<sa||(sb===sa&&b.id<a.id))?b:a;});
    return {id:best.id,rel:'inside',label:tl('#{id} 범위 안',{id:best.id})};
  }
  const partials=rel.filter(x=>x.rel==='partial').sort((a,b)=>a.id-b.id);
  if(partials.length){const n=partials[0].id; return {id:n,rel:'partial',label:tl('#{id}{p} 일부 겹침',{id:n,p:josa(n,'과','와')})};}
  return null;
}
// §P0c-C: the in-progress marker. claim_until is epoch seconds, compared independent of the browser's timezone (numbers
// instead of a wall-clock string, for the same reason as §Position estimation). The viewer never places a claim (agent-only) - it only offers [풀기].
function claimActive(p){return typeof p.claim_until==='number'&&p.claim_until>Date.now()/1000;}
// Estimated time to handle (docs/handbook/api.md §처리 중 표시): if an agent gives eta_min on a claim, the server sets eta_ts
// (epoch). The badge shows '처리 중 · 약 15분 · 20:40쯤' - both the remaining minutes and the time are rounded up to
// 5-minute steps (an estimate is approximate). Past it, '예상보다 늦어짐 (+5분)'. A legacy claim with no eta shows
// '처리 중 · 20:02부터 (23분째)'. The lock's auto-expiry (claim_until) was misread as the estimated completion (observed:
// '~04:02'), so it's never shown on screen - only in the description. The time is the viewing device's local time. now is injected by tests.
function ceil5(m){return Math.max(5,Math.ceil(m/5-1e-9)*5);}
function hhmm(ms){const d=new Date(ms); return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');}
function claimInfo(p,now){now=now==null?Date.now():now; const w=who(p.claimed_by)||'?',st=typeof p.claim_ts==='number'?p.claim_ts*1000:null;
  const tail=' · '+tl('잠금 자동 해제 {time}(그 뒤에는 다른 쪽이 잡을 수 있습니다). 에이전트가 멈췄으면 [풀기]',{time:hhmm(p.claim_until*1000)});
  const head=tl('처리하는 쪽: {name}',{name:w})+(st?' · '+tl('시작 {time}',{time:hhmm(st)}):'');
  if(typeof p.eta_ts==='number'){const eta=p.eta_ts*1000;
    if(now<=eta)return {t:tl('처리 중 · 약 {n}분 · {time}쯤',{n:ceil5((eta-now)/60000),time:hhmm(Math.ceil(eta/300000)*300000)}),late:false,
      tip:head+' · '+tl('예상 완료 {time}',{time:hhmm(eta)})+tail};
    return {t:tl('예상보다 늦어짐 (+{n}분)',{n:ceil5((now-eta)/60000)}),late:true,tip:head+' · '+tl('예상 완료 {time}였음',{time:hhmm(eta)})+tail};}
  if(st)return {t:tl('처리 중 · {time}부터 ({n}분째)',{time:hhmm(st),n:Math.max(1,Math.ceil((now-st)/60000))}),late:false,tip:head+' · '+tr('예상 시간 없음')+tail};
  return {t:tr('처리 중'),late:false,tip:head+tail};}
function claimLabel(p,now){return claimInfo(p,now).t;}
function claimTag(p){const c=claimInfo(p);
  return '<span class="badge badge-claimed'+(c.late?' late':'')+'" data-claim="'+p.id+'" data-tip="'+esc(c.tip)+'">'+ic('clock')+'<span class="ct">'+esc(c.t)+'</span></span>';}
// The remaining/elapsed minutes change with time - only the badge text is updated every 30 seconds (the card isn't redrawn). The list is redrawn if any pin's lock has expired.
function tickClaims(){if(document.hidden)return; let gone=false;
  $$('.badge-claimed[data-claim]').forEach(el=>{const p=OPEN_ALL.find(x=>x.id===+el.dataset.claim);
    if(!p||!claimActive(p)){gone=true; return;} const c=claimInfo(p); el.querySelector('.ct').textContent=c.t; el.dataset.tip=c.tip; el.classList.toggle('late',c.late);});
  if(gone)drawPins();}
setInterval(tickClaims,30000);
// A card's location text: 'L12-L18' for a LaTeX pin, '영역' for a view-only PDF's pin (the page is a separate field). The copy format is 'file L12-L18' / 'x.pdf 쪽 3'.
function locText(p){return isRegion(p)?tr('영역'):rng(p.lo,p.hi);}
function locCopy(p){const name=p.name||String(p.file||p.pdf||'').split('/').pop(); return isRegion(p)?name+' 쪽 '+p.page:name+' L'+p.lo+'-L'+p.hi;}
// The document chip attached to a card header when viewing all documents. Another document's is dashed-bordered - clicking it switches to that document.
function docChip(p){if(!(SHOW_ALL&&multiDoc()))return ''; const d=docInfo(pdoc(p)),other=pdoc(p)!==DOC;
  return '<span class="badge badge-secondary dchip'+(other?' other':'')+'" data-tip="'+esc((d?d.name+' · '+d.path:tl('{doc} (설정에 없는 문서)',{doc:pdoc(p)}))+(other?' — '+tr('#번호·[보기]를 누르면 이 문서로 바꿉니다'):''))+'">'+esc(d?d.name:pdoc(p))+'</span>';}
// Thread (docs/handbook/viewer.md §스레드와 검토): replies and state-transition records (close/reopen/confirm) form a single line of history. Text goes through esc().
// wide shows the last 3, compact shows only the last 1, expanded via [이전 N건] (THREAD_OPEN). The input field (REPLY) is inserted in place like EDIT.
function isQuestion(p){return !!p&&p.kind_req==='question';}
// The current assignee - the recorded value (p.assignee); for a legacy pin without one, the person the server inferred (the first of p.addressed); if neither, the agent.
function assigneeOf(p){if(!p)return 'agent'; if(p.assignee)return p.assignee; const a=p.addressed||[]; return a.length?a[0]:'agent';}
// The card header's assignee chip: shown only when the assignee is a person (the agent is the default, so it's not shown). The author (or an identity-less local screen) changes it by clicking into [수정].
function assignChip(p){if(!p.assignee||p.assignee==='agent')return ''; const me=meLogin(),mine=p.assignee===me,nm=mine?tr('나'):'@'+(String(peopleName(p.assignee)).split(/\s+/)[0]||p.assignee);   // the chip shows the first word of the name; the full name goes in the description
  const canEdit=pinState(p)==='open'&&(isMe(p.author)||!me),tip=tl('담당: {name} — 에이전트는 이 핀을 건너뜁니다',{name:mine?tr('나'):peopleName(p.assignee)})+(canEdit?tr('. 누르면 [수정]에서 담당을 바꿉니다'):'');
  return canEdit?'<button class="badge badge-assign as-chip'+(mine?' me':'')+'" data-act="edit" data-tip="'+esc(tip)+'">'+esc(tr('담당'))+' <span class="as-n">'+esc(nm)+'</span></button>'
    :'<span class="badge badge-assign as-chip'+(mine?' me':'')+'" data-tip="'+esc(tip)+'">'+esc(tr('담당'))+' <span class="as-n">'+esc(nm)+'</span></span>';}
// Status dot (docs/handbook/viewer.md §상태 표현): color + a readable name (aria-label/description). A badge states the same meaning in text once more.
const ST_NAME={open:'열림',claimed:'처리 중',review:'검토 대기',lost:'위치 잃음'};
function stDot(st){const t=esc(tl('상태: {name}',{name:tr(ST_NAME[st])})); return '<span class="st-dot'+(st==='open'?'':' '+st)+'" role="img" aria-label="'+t+'" data-tip="'+t+'"></span>';}
// Did the current round start with a reopen (a pin that returned from review)? True if the thread's last close/reopen record is a reopen.
function reopenedTurn(p){const th=threadOf(p); for(let i=th.length-1;i>=0;i--){const e=th[i].ev; if(e==='close'||e==='reopen')return e==='reopen'?th[i]:null;} return null;}
function threadOf(p){return Array.isArray(p&&p.thread)?p.thread:[];}
function replyCount(p){return threadOf(p).filter(m=>!m.ev).length;}
function msgText(m){return fmtText(m.text,m.mentions);}
// Turns '@name' (only resolved mentions) and '#number' (an existing pin) in text into tokens (docs/handbook/viewer.md §@태그).
// Text goes through esc() first, and names/numbers are found and wrapped within that already-escaped text - so text a
// person wrote never leaks as HTML. Names are matched with the same candidates as the server's resolve_mentions() (full
// name/login/the part of the login before @/the first word of the name), longest first, case-insensitive. Skipped if the
// character before '@' is alphanumeric (an email address); a name ending in an ASCII letter followed by an ASCII letter
// (@Alicex) is a different word. An unresolved '@word' stays plain text - it must never look like it called someone.
function peopleName(login){const x=PEOPLE.find(p=>p.login===login); return x?x.name:login;}
function mentionToks(logins){const out=[]; (logins||[]).forEach(lg=>{const x=PEOPLE.find(p=>p.login===lg),nm=String((x&&x.name)||'');
    const w=nm.split(/\s+/).filter(Boolean); [nm,lg,String(lg).split('@')[0]].concat(w.length>1?[w[0]]:[]).forEach((t,k)=>{if(t&&t.length>=2)out.push({t:esc(t),lg,k});});});
  return out.sort((a,b)=>b.t.length-a.t.length||a.k-b.k);}   // for a tie in text length, full name > login > first word
function reEsc(t){return t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
function meLogin(){const me=typeof META!=='undefined'&&META&&META.me; return me&&me.login&&me.login!=='local'?me.login:null;}
function fmtText(text,logins){let h=esc(text); const toks=mentionToks(logins),hit=[],me=meLogin();
  if(toks.length){const re=new RegExp('@('+toks.map(x=>reEsc(x.t)).join('|')+')','gi');
    // First swapped for placeholders (\u0001number\u0002) - so that after a long name is wrapped, a short name never re-wraps inside it.
    h=h.replace(re,(m,t,off,all)=>{const prev=off>0?all[off-1]:''; if(prev&&/[0-9A-Za-z가-힣._-]/.test(prev))return m;
      const nx=all.charAt(off+m.length); if(/[A-Za-z0-9]$/.test(t)&&/[A-Za-z0-9_]/.test(nx))return m;
      const tk=toks.find(x=>x.t.toLowerCase()===t.toLowerCase()); if(!tk)return m; hit.push({m,lg:tk.lg}); return '\u0001'+(hit.length-1)+'\u0002';});}
  // '#12' - a link to that pin if it exists. An escape like '&#39;' (preceded by &) and '#12;' are left untouched.
  // A '#12' whose pin is in the Trash renders as '#12 deleted pin' (faded) and opens the Trash at that row.
  h=h.replace(/(^|[^&0-9A-Za-z#])#(\d{1,6})(?![\d;])/g,(m,pre,n)=>{const id=+n;
    if(pinRefExists(id))return pre+'<span class="pin-ref" role="link" tabindex="0" data-act="pin-ref" data-ref="'+id+'" data-tip="'+esc(tl('핀 #{id} 로 갑니다',{id}))+'">#'+id+'</span>';
    if(pinRefGone(id))return pre+'<span class="pin-ref gone" role="link" tabindex="0" data-act="pin-ref" data-ref="'+id+'" data-tip="'+esc(tl('핀 #{id} 은 삭제되었습니다 — 누르면 휴지통에서 봅니다',{id}))+'">#'+id+' <small>'+esc(tr('삭제된 핀'))+'</small></span>';
    return m;});
  return h.replace(/\u0001(\d+)\u0002/g,(_,k)=>{const x=hit[+k],mine=!!me&&x.lg===me;
    return '<span class="mention'+(mine?' me':'')+'" data-tip="'+esc(mine?tr('나를 부름 — 이 핀 알림이 나에게 옵니다'):tl('@태그 — {name}에게 알림이 갑니다',{name:peopleName(x.lg)}))+'">'+x.m+'</span>';});}
function pinRefExists(id){return typeof findAnyPin==='function'&&!!findAnyPin(id);}
function pinRefGone(id){return typeof DROPPED!=='undefined'&&Array.isArray(DROPPED)&&DROPPED.some(p=>p.id===id);}
// The [나를 부른 핀] filter (docs/handbook/viewer.md §@태그): uses the same material as the badge/pins.md's '→ @name'
// (p.addressed, which the server counts only for the current round via thread_round) - the old version scanned the
// entire thread (threadOf(p).some(...)) and had a defect where an @-tag from an old round kept a pin marked "called me"
// even after reopening (observed). addressed_to() only has a value on question pins.
function mentionsMe(p){const me=META&&META.me; if(!me||!me.login||me.login==='local')return false;
  return (p.addressed||[]).includes(me.login);}
function addressedTag(p){const to=(p.addressed||[]); if(!to.length)return '';
  const me=META&&META.me&&META.me.login,mine=to.includes(me),others=to.filter(x=>x!==me);
  return (mine?'<span class="badge badge-mention" data-tip="이 핀이 나를 @태그했습니다 — 에이전트는 이 핀을 건너뜁니다(사용자가 시키면 예외)">'+ic('at-sign')+'나를 부름</span>':'')+
    (others.length?'<span class="badge badge-mention" data-tip="사람을 부른 핀입니다 — 에이전트는 사용자가 따로 시키지 않으면 건너뜁니다">'+ic('at-sign')+esc(others.map(peopleName).join(', '))+'</span>':'');}
// A fix pin's FYI @-tags (never skipped) - kept separate from p.addressed (question-pin only) and sent in p.fyi instead.
function fyiTag(p){const to=(p.fyi||[]); if(!to.length)return '';
  return '<span class="badge badge-mention" data-tip="참고로 부른 사람입니다 — 질문이 아니라 수정 요청이라 건너뛰지 않습니다">'+ic('at-sign')+esc(tl('참고 {names}',{names:to.map(peopleName).join(', ')}))+'</span>';}
// Is the reference (ref) a meaningful value? '-' is a placeholder QA scripts/legacy callers use for "no reference" - shown as-is
// it would produce meaningless text like '닫음 · -' (observed defect). An empty or whitespace-only value is filtered out the same way.
function hasRef(v){return !!v&&String(v).trim()!==''&&String(v).trim()!=='-';}
const EV_LABEL={close:'닫음',reopen:'다시 엶',confirm:'확인',assign:'담당 바꿈'};
// A long post collapses at 6 lines with [더 보기] (keyed 'id:index' in MSG_OPEN). If the author is me, '(나)'.
const MSG_OPEN=new Set();
function msgBody(m,key){const long=String(m.text||'').length>280||String(m.text||'').split('\n').length>6,open=!key||MSG_OPEN.has(key);
  return '<div class="msg-t'+(long&&!open?' clamp':'')+'">'+msgText(m)+'</div>'+
    (long&&key?'<button class="btn-sm btn-ghost msg-more" data-act="msg-more" data-key="'+esc(key)+'" aria-expanded="'+open+'">'+(open?'접기':'더 보기')+'</button>':'');}
function msgHtml(m,key){const by=m.by||{},nm=who(by)||'?',mine=isMe(by)?'<span class="me-tag"> (나)</span>':'';
  if(m.ev)return '<div class="msg ev ev-'+esc(m.ev)+'"><div class="msg-h"><b>'+esc(nm)+mine+'</b><span>'+esc(tr(EV_LABEL[m.ev]||m.ev))+(hasRef(m.ref)?' · '+esc(m.ref):'')+'</span>'+relSpan(m.at)+'</div>'+
    (m.text?msgBody(m,key):'')+'</div>';
  return '<div class="msg">'+avatar(by)+'<div class="msg-b"><div class="msg-h"><b>'+esc(nm)+mine+'</b>'+relSpan(m.at)+'</div>'+msgBody(m,key)+'</div></div>';}
function threadHtml(p,wide){const th=threadOf(p),keep=wide?3:1,all=THREAD_OPEN.has(p.id),hide=all?0:Math.max(0,th.length-keep);
  let h='';
  if(hide)h+='<button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="false">'+esc(tl('이전 {n}건 보기',{n:hide}))+'</button>';
  else if(all&&th.length>keep)h+='<button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="true">스레드 접기</button>';
  h+=th.slice(hide).map((m,i)=>msgHtml(m,p.id+':'+(i+hide))).join('');
  if(REPLY&&REPLY.id===p.id)h+='<div class="reply-slot"></div>';
  return h?'<div class="thread">'+h+'</div>':'';}
