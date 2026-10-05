// ------------------------------------------------ Pin card parts: people, badges, claims, @-tags and #refs in text, the thread
function who(a){if(a&&a.login===LOCAL_LOGIN)return tr(a.name||'로컬/에이전트'); return (a&&(a.name||a.login))||'';}   // the stored local name is Korean ('로컬/에이전트'); shown in the UI language
const BADPIC=new Set();   // an avatar URL that has already failed is never requested again (otherwise console errors would pile up on every re-render)
// A person = a photo or an initial circle (primary color); local/agent = a faded circle with a robot icon - distinguishes people from agents at a glance.
function isAgent(a){return !!a&&(a.login===LOCAL_LOGIN||String(a.login).startsWith('agent:'));}
function avatar(a){if(!a||!(a.name||a.login))return html``; if(isAgent(a))return html`<span class="av i agent" aria-hidden="true">${ic('bot')}</span>`;
  const ini=(who(a).trim()[0]||'?').toUpperCase();
  return a.pic&&!BADPIC.has(a.pic)?html`<img class="av" src="${a.pic}" alt="" referrerpolicy="no-referrer" data-ini="${ini}">`
    :html`<span class="av i" aria-hidden="true">${ini}</span>`;}
document.addEventListener('error',e=>{const t=/** @type {HTMLImageElement} */(e.target);
  if(t&&t.tagName==='IMG'&&t.classList.contains('av')){BADPIC.add(t.getAttribute('src')); const s=document.createElement('span');s.className='av i';
    s.textContent=t.dataset.ini||'?';t.replaceWith(s);}},true);
/** @param {Pin} p */
function authorTip(p){let s=tl('작성: {name} · {at}',{name:p.author?who(p.author):tr('기록 전'),at:p.at||'?'});
  if(p.edited_at)s+=' / '+tl('수정: {name} · {at}',{name:who(p.edited_by)||tr('기록 전'),at:p.edited_at}); return s;}
// docs/handbook/api.md §겹친 핀과 덧붙이기: one representative among the rel entries - if there's an inside (the outer pin with the smallest range),
// otherwise the smallest-id partial. Must follow the same rule as the server's rel_badge() (pins.md) so card tags and
// pins.md rows never disagree - since a rel entry is only {id,rel}, the range is looked up by id from PINS (all currently loaded open pins).
// The badge wording is phrased to be self-explanatory: '#20과 같은 범위' > '#20 범위 안' > '#20과 일부 겹침'. Same-range is distinguished using p's (this pin's) lo/hi.
function josa(n,c,v){const d=String(n).slice(-1); return d==='0'||'13678'.includes(d)?c:v;}
function relBadge(rel,p){
  if(!rel||!rel.length)return null;
  const byId=new Map(PINS.map(p=>[p.id,p]));
  if(p){const same=rel.filter(x=>{const o=byId.get(x.id); return o&&o.lo===p.lo&&o.hi===p.hi;});
    if(same.length){const n=Math.min.apply(null,same.map(x=>x.id)); return {id:n,rel:RANGE_REL.EQUAL,label:tl('#{id}{p} 같은 범위',{id:n,p:josa(n,'과','와')})};}}
  const insides=rel.filter(x=>x.rel===RANGE_REL.INSIDE);
  if(insides.length){
    const span=x=>{const o=byId.get(x.id); return o?(/** @type {number} */(o.hi)-/** @type {number} */(o.lo)):Number.MAX_SAFE_INTEGER;};   // rel names line pins
    const best=insides.reduce((a,b)=>{const sa=span(a),sb=span(b);
      return (sb<sa||(sb===sa&&b.id<a.id))?b:a;});
    return {id:best.id,rel:RANGE_REL.INSIDE,label:tl('#{id} 범위 안',{id:best.id})};
  }
  const partials=rel.filter(x=>x.rel===RANGE_REL.PARTIAL).sort((a,b)=>a.id-b.id);
  if(partials.length){const n=partials[0].id; return {id:n,rel:RANGE_REL.PARTIAL,label:tl('#{id}{p} 일부 겹침',{id:n,p:josa(n,'과','와')})};}
  return null;
}
// The in-progress marker (docs/handbook/api.md §처리 중 표시 (claim)). claim_until is epoch seconds, compared independent of the browser's timezone (numbers
// instead of a wall-clock string, for the same reason as docs/handbook/build-sync.md §위치 추정). The viewer never places a claim (agent-only) - it only offers [풀기].
/** @param {Pin} p */
function claimActive(p){return typeof p.claim_until==='number'&&p.claim_until>Date.now()/1000;}
// Estimated time to handle (docs/handbook/api.md §처리 중 표시): if an agent gives eta_min on a claim, the server sets eta_ts
// (epoch). The badge shows '처리 중 · 약 15분 · 20:40쯤' - both the remaining minutes and the time are rounded up to
// 5-minute steps (an estimate is approximate). Past it, '예상보다 늦어짐 (+5분)'. A legacy claim with no eta shows
// '처리 중 · 20:02부터 (23분째)'. The lock's auto-expiry (claim_until) was misread as the estimated completion (observed:
// '~04:02'), so it's never shown on screen - only in the description. The time is the viewing device's local time. now is injected by tests.
function ceil5(m){return Math.max(5,Math.ceil(m/5-1e-9)*5);}
function hhmm(ms){const d=new Date(ms); return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');}
/** @param {Pin} p @param {number} [now] */
function claimInfo(p,now){now=now==null?Date.now():now; const w=who(p.claimed_by)||'?',st=typeof p.claim_ts==='number'?p.claim_ts*1000:null;
  const tail=' · '+tl('잠금 자동 해제 {time}(그 뒤에는 다른 쪽이 잡을 수 있습니다). 에이전트가 멈췄으면 [풀기]',{time:hhmm(/** @type {number} */(p.claim_until)*1000)});   // claimInfo runs for an active claim (claimActive)
  const head=tl('처리하는 쪽: {name}',{name:w})+(st?' · '+tl('시작 {time}',{time:hhmm(st)}):'');
  if(typeof p.eta_ts==='number'){const eta=p.eta_ts*1000;
    if(now<=eta)return {t:tl('처리 중 · 약 {n}분 · {time}쯤',{n:ceil5((eta-now)/60000),time:hhmm(Math.ceil(eta/300000)*300000)}),late:false,
      tip:head+' · '+tl('예상 완료 {time}',{time:hhmm(eta)})+tail};
    return {t:tl('예상보다 늦어짐 (+{n}분)',{n:ceil5((now-eta)/60000)}),late:true,tip:head+' · '+tl('예상 완료 {time}였음',{time:hhmm(eta)})+tail};}
  if(st)return {t:tl('처리 중 · {time}부터 ({n}분째)',{time:hhmm(st),n:Math.max(1,Math.ceil((now-st)/60000))}),late:false,tip:head+' · '+tr('예상 시간 없음')+tail};
  return {t:tr('처리 중'),late:false,tip:head+tail};}
/** @param {Pin} p @param {number} [now] */
function claimLabel(p,now){return claimInfo(p,now).t;}
/** @param {Pin} p */
function claimTag(p){const c=claimInfo(p);
  return html`<span class="badge badge-claimed${c.late?' late':''}" data-claim="${p.id}" data-tip="${c.tip}">${ic('clock')}<span class="ct">${c.t}</span></span>`;}
// The remaining/elapsed minutes change with time - only the badge text is updated every 30 seconds (the card isn't redrawn). The list is redrawn if any pin's lock has expired.
function tickClaims(){if(document.hidden)return; let gone=false;
  $$('.badge-claimed[data-claim]').forEach(el=>{const p=OPEN_ALL.find(x=>x.id===+el.dataset.claim);
    if(!p||!claimActive(p)){gone=true; return;} const c=claimInfo(p); el.querySelector('.ct').textContent=c.t; el.dataset.tip=c.tip; el.classList.toggle('late',c.late);});
  if(gone)drawPins();}
setInterval(tickClaims,30000);
// A card's location text: 'L12-L18' for a LaTeX pin, '영역' for a view-only PDF's pin (the page is a separate field). The copy format is 'file L12-L18' / 'x.pdf 쪽 3'; a
// region's page is the one its mark is on in the current build (pinPlace), which a figure pin's element can move.
/** @param {Pin} p */
function locText(p){return isRegion(p)?tr('영역'):rng(p.lo,p.hi);}
/** @param {Pin} p */
function locCopy(p){const name=p.name||String(p.file||p.pdf||'').split('/').pop(); return isRegion(p)?name+' 쪽 '+pinPlace(p).page:name+' L'+p.lo+'-L'+p.hi;}
// The document chip attached to a card header when viewing all documents. Another document's is dashed-bordered - clicking it switches to that document.
// The name is user text (translate="no"); its description's UI words are translated here.
/** @param {Pin} p */
function docChip(p){if(!(SHOW_ALL&&multiDoc()))return html``; const d=docInfo(pdoc(p)),other=pdoc(p)!==DOC;
  const tip=(d?d.name+' · '+d.path:tl('{doc} (설정에 없는 문서)',{doc:pdoc(p)}))+(other?' — '+tr('#번호·[보기]를 누르면 이 문서로 바꿉니다'):'');
  return html`<span class="badge badge-secondary dchip${other?' other':''}" translate="no" data-tip="${tip}">${d?d.name:pdoc(p)}</span>`;}
// Thread (docs/handbook/viewer.md §스레드와 검토): replies and state-transition records (close/reopen/confirm) form a single line of history, built with html``.
// wide shows the last 3, compact shows only the last 1, expanded via [이전 N건] (THREAD_OPEN). The input field (REPLY) is inserted in place like EDITOR.current.
/** @param {Pin} p */
function isQuestion(p){return !!p&&p.kind_req===KIND_REQ.QUESTION;}
// The current assignee - the recorded value (p.assignee); for a legacy pin without one, the person the server inferred (the first of p.addressed); if neither, the agent.
/** @param {Pin} p */
function assigneeOf(p){if(!p)return ASSIGNEE_AGENT; if(p.assignee)return p.assignee; const a=p.addressed||[]; return a.length?a[0]:ASSIGNEE_AGENT;}
// The card header's assignee chip: shown only when the assignee is a person (the agent is the default, so it's not shown). The author (or an identity-less local screen) changes it by clicking into [수정].
// The name is user text (translate="no").
/** @param {Pin} p */
function assignChip(p){if(!p.assignee||p.assignee===ASSIGNEE_AGENT)return html``; const me=meLogin(),mine=p.assignee===me,nm=mine?tr('나'):'@'+(String(peopleName(p.assignee)).split(/\s+/)[0]||p.assignee);   // the chip shows the first word of the name; the full name goes in the description
  const canEdit=pinState(p)===PIN_STATE.OPEN&&(isMe(p.author)||!me),tip=tl('담당: {name} — 에이전트는 이 핀을 건너뜁니다',{name:mine?tr('나'):peopleName(p.assignee)})+(canEdit?tr('. 누르면 [수정]에서 담당을 바꿉니다'):'');
  return canEdit?html`<button class="badge badge-assign as-chip${mine?' me':''}" data-act="edit" data-tip="${tip}">${tr('담당')} <span class="as-n" translate="no">${nm}</span></button>`
    :html`<span class="badge badge-assign as-chip${mine?' me':''}" data-tip="${tip}">${tr('담당')} <span class="as-n" translate="no">${nm}</span></span>`;}
// Status dot (docs/handbook/viewer.md §상태 표현): color + a readable name (aria-label/description). A badge states the same meaning in text once more.
const ST_NAME={open:'열림',claimed:'처리 중',review:'검토 대기',lost:'위치 잃음'};
function stDot(st){const t=tl('상태: {name}',{name:tr(ST_NAME[st])}); return html`<span class="st-dot${st===CARD_DOT.OPEN?'':' '+st}" role="img" aria-label="${t}" data-tip="${t}"></span>`;}
// Did the current round start with a reopen (a pin that returned from review)? True if the thread's last close/reopen record is a reopen.
/** @param {Pin} p */
function reopenedTurn(p){const th=threadOf(p); for(let i=th.length-1;i>=0;i--){const e=th[i].ev; if(e===THREAD_EV.CLOSE||e===THREAD_EV.REOPEN)return e===THREAD_EV.REOPEN?th[i]:null;} return null;}
/** @param {Pin} p */
function threadOf(p){const th=p&&p.thread; return Array.isArray(th)?th:[];}
/** @param {Pin} p */
function replyCount(p){return threadOf(p).filter(m=>!m.ev).length;}
/** @param {ThreadEntry} m */
function msgText(m){return fmtText(m.text,m.mentions);}
// Turns '@name' (only resolved mentions) and '#number' (an existing pin) in text into tokens (docs/handbook/viewer.md §@태그).
// Names and numbers are found in the text as written and the result is built with html``, so the text between and
// inside the tokens stays text - what a person wrote never leaks as HTML. Names are matched with the same candidates as the server's resolve_mentions() (full
// name/login/the part of the login before @/the first word of the name), longest first, case-insensitive. Skipped when
// '@' follows a word (mentionAfterWord - an email address); a name ending in an ASCII letter followed by an ASCII letter
// (@Alicex) is a different word. An unresolved '@word' stays plain text - it must never look like it called someone.
function peopleName(login){const x=PEOPLE.find(p=>p.login===login); return x?x.name:login;}
function mentionToks(logins){const out=[]; (logins||[]).forEach(lg=>{const x=PEOPLE.find(p=>p.login===lg),nm=String((x&&x.name)||'');
    const w=nm.split(/\s+/).filter(Boolean); [nm,lg,String(lg).split('@')[0]].concat(w.length>1?[w[0]]:[]).forEach((t,k)=>{if([...t].length>=2)out.push({t,lg,k});});});
  return out.sort((a,b)=>b.t.length-a.t.length||a.k-b.k);}   // for a tie in text length, full name > login > first word
// Whether the '@' at text[i] continues a word, so it is no tag - the server's rule: the character before it is a letter or
// digit of any script (Python's str.isalnum(): Unicode L*/N*, so 'é@' and '김@' too) or one of '._-'. That character
// is a whole code point, as Python reads it: an astral letter before '@' is two UTF-16 units.
function mentionAfterWord(text,i){if(i<=0)return false; const lo=text.charCodeAt(i-1),hi=i>1?text.charCodeAt(i-2):0;
  const c=lo>=0xDC00&&lo<=0xDFFF&&hi>=0xD800&&hi<=0xDBFF?text.slice(i-2,i):text[i-1]; return /^[\p{L}\p{N}._-]$/u.test(c);}
function reEsc(t){return t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
function meLogin(){const me=typeof META!=='undefined'&&META&&META.me; return me&&me.login&&me.login!==LOCAL_LOGIN?me.login:null;}
// text as Html with its resolved @-tags (logins) and existing #refs as tokens. A match the rules turn down is consumed and
// stays text, and the text between two tags is searched for #refs only, so a name never holds a link.
function fmtText(text,logins){const s=String(text==null?'':text),toks=mentionToks(logins),me=meLogin(),out=[]; let at=0;
  if(toks.length){const re=new RegExp('@('+toks.map(x=>reEsc(x.t)).join('|')+')','gi');
    for(const m of s.matchAll(re)){const t=m[1],off=m.index; if(mentionAfterWord(s,off))continue;
      const nx=s.charAt(off+m[0].length); if(/[A-Za-z0-9]$/.test(t)&&/[A-Za-z0-9_]/.test(nx))continue;
      const tk=toks.find(x=>x.t.toLowerCase()===t.toLowerCase()); if(!tk)continue;
      const mine=!!me&&tk.lg===me,tip=mine?tr('나를 부름 — 이 핀 알림이 나에게 옵니다'):tl('@태그 — {name}에게 알림이 갑니다',{name:peopleName(tk.lg)});
      out.push(pinRefs(s.slice(at,off)),html`<span class="mention${mine?' me':''}" data-tip="${tip}">${m[0]}</span>`); at=off+m[0].length;}}
  out.push(pinRefs(s.slice(at)));
  return html`${out}`;}
// s with each '#12' whose pin exists as a link, as html`` values. '#12;' and a number glued to a word, digit or '#' stay
// text. A '#12' whose pin is in the Trash renders as '#12 deleted pin' (faded) and opens the Trash at that row.
function pinRefs(s){const out=[]; let at=0;
  for(const m of s.matchAll(/(^|[^0-9A-Za-z#])#(\d{1,6})(?![\d;])/g)){const id=+m[2],start=m.index+m[1].length;
    const ref=pinRefExists(id)?html`<span class="pin-ref" role="link" tabindex="0" data-act="pin-ref" data-ref="${id}" data-tip="${tl('핀 #{id} 로 갑니다',{id})}">#${id}</span>`
      :pinRefGone(id)?html`<span class="pin-ref gone" role="link" tabindex="0" data-act="pin-ref" data-ref="${id}" data-tip="${tl('핀 #{id} 은 삭제되었습니다 — 누르면 휴지통에서 봅니다',{id})}">#${id} <small>${tr('삭제된 핀')}</small></span>`:null;
    if(!ref)continue; out.push(s.slice(at,start),ref); at=m.index+m[0].length;}
  out.push(s.slice(at)); return out;}
function pinRefExists(id){return typeof findAnyPin==='function'&&!!findAnyPin(id);}
function pinRefGone(id){return typeof DROPPED!=='undefined'&&Array.isArray(DROPPED)&&DROPPED.some(p=>p.id===id);}
// The [나를 부른 핀] filter (docs/handbook/viewer.md §@태그): uses the same material as the badge/pins.md's '→ @name'
// (p.addressed, which the server counts only for the current round via thread_round) - the old version scanned the
// entire thread (threadOf(p).some(...)) and had a defect where an @-tag from an old round kept a pin marked "called me"
// even after reopening (observed). addressed_to() only has a value on question pins.
/** @param {Pin} p */
function mentionsMe(p){const me=META&&META.me; if(!me||!me.login||me.login===LOCAL_LOGIN)return false;
  return (p.addressed||[]).includes(me.login);}
// The badges of a question pin that calls people: '나를 부름', and the others' names (user text, translate="no").
/** @param {Pin} p */
function addressedTag(p){const to=(p.addressed||[]); if(!to.length)return null;
  const me=META&&META.me&&META.me.login,mine=to.includes(me),others=to.filter(x=>x!==me);
  const self=mine?html`<span class="badge badge-mention" data-tip="이 핀이 나를 @태그했습니다 — 에이전트는 이 핀을 건너뜁니다(사용자가 시키면 예외)">${ic('at-sign')}나를 부름</span>`:'';
  const rest=others.length?html`<span class="badge badge-mention" data-tip="사람을 부른 핀입니다 — 에이전트는 사용자가 따로 시키지 않으면 건너뜁니다">${ic('at-sign')}<span translate="no">${others.map(peopleName).join(', ')}</span></span>`:'';
  return html`${self}${rest}`;}
// A fix pin's FYI @-tags (never skipped) - kept separate from p.addressed (question-pin only) and sent in p.fyi instead.
/** @param {Pin} p */
function fyiTag(p){const to=(p.fyi||[]); if(!to.length)return null;
  return html`<span class="badge badge-mention" data-tip="참고로 부른 사람입니다 — 질문이 아니라 수정 요청이라 건너뛰지 않습니다">${ic('at-sign')}${tl('참고 {names}',{names:to.map(peopleName).join(', ')})}</span>`;}
// Is the reference (ref) a meaningful value? '-' is a placeholder QA scripts/legacy callers use for "no reference" - shown as-is
// it would produce meaningless text like '닫음 · -' (observed defect). An empty or whitespace-only value is filtered out the same way.
function hasRef(v){return !!v&&String(v).trim()!==''&&String(v).trim()!=='-';}
const EV_LABEL={close:'닫음',reopen:'다시 엶',confirm:'확인',assign:'담당 바꿈'};
// The cards whose quote line is open ('<doc>:<id>', toggleQuote), kept across redraws.
const QUOTE_OPEN=new Set();
// A card's quote line, right above its note: the composer's line for the pin's saved quote (shownQuote, quoteInner), folded to
// one line with the whole text as its tooltip until it is pressed. null when the pin shows no quote.
/** @param {Pin} p @returns {Html|null} */
function cardQuote(p){const q=shownQuote(p,(docInfo(pdoc(p))||{}).kind); if(!q)return null;
  const k=pdoc(p)+':'+p.id,open=QUOTE_OPEN.has(k);
  return html`<div class="quote hit${open?' open':''}" role="button" tabindex="0" data-act="quote" data-key="${k}" aria-expanded="${String(open)}"\
 data-tip="${open?null:q}" translate="no">${quoteInner(q)}</div>`;}
// A long post collapses at 6 lines with [더 보기] (keyed 'id:index' in MSG_OPEN). If the author is me, '(나)'. The post and its
// author's name are user text (translate="no"); '(나)' is translated here.
const MSG_OPEN=new Set();
// A thread entry's text (user text, translate="no") clamped at 6 lines with [더 보기]/[접기] when long; key ('id:index') keeps
// it open across redraws (MSG_OPEN), and without a key it is drawn whole with no button.
/** @param {ThreadEntry} m */
function msgBody(m,key){const long=String(m.text||'').length>280||String(m.text||'').split('\n').length>6,open=!key||MSG_OPEN.has(key);
  const more=long&&key?html`<button class="btn-sm btn-ghost msg-more" data-act="msg-more" data-key="${key}" aria-expanded="${open}">${open?'접기':'더 보기'}</button>`:'';
  return html`<div class="msg-t${long&&!open?' clamp':''}" translate="no">${msgText(m)}</div>${more}`;}
// One thread entry: a post (avatar, author, time, text) or a state record (who, what, reference, time, optional text).
/** @param {ThreadEntry} m */
function msgHtml(m,key){const by=m.by||{},nm=who(by)||'?',mine=isMe(by)?html`<span class="me-tag"> ${tr('(나)')}</span>`:'';
  if(m.ev)return html`<div class="msg ev ev-${m.ev}"><div class="msg-h"><b translate="no">${nm}${mine}</b><span>${tr(EV_LABEL[m.ev]||m.ev)}${hasRef(m.ref)?' · '+m.ref:''}</span>${relSpan(m.at)}</div>${m.text?msgBody(m,key):''}</div>`;
  return html`<div class="msg">${avatar(by)}<div class="msg-b"><div class="msg-h"><b translate="no">${nm}${mine}</b>${relSpan(m.at)}</div>${msgBody(m,key)}</div></div>`;}
// The thread of p as Html (empty without entries): the last 3 entries in wide, the last 1 elsewhere, unless THREAD_OPEN
// holds p; the button that shows the rest or folds them; and the reply slot when p's reply box is open.
/** @param {Pin} p */
function threadHtml(p,wide){const th=threadOf(p),keep=wide?3:1,all=THREAD_OPEN.has(p.id),hide=all?0:Math.max(0,th.length-keep);
  const more=hide?html`<button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="false">${tl('이전 {n}건 보기',{n:hide})}</button>`
    :all&&th.length>keep?html`<button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="true">스레드 접기</button>`:'';
  const msgs=th.slice(hide).map((m,i)=>msgHtml(m,p.id+':'+(i+hide))),slot=REPLY&&REPLY.id===p.id?html`<div class="reply-slot"></div>`:'';
  return more||msgs.length||slot?html`<div class="thread">${more}${msgs}${slot}</div>`:html``;}
