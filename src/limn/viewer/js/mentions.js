// ------------------------------------------------ @-tag autocomplete (docs/handbook/viewer.md §@태그)
// Typing '@' in the note/edit/reply field shows known people (PEOPLE, excluding me). Picking one inserts '@name ' and
// remembers that login on the field (ta._mentions), carried as a hint (mentions) when sending - the server re-resolves
// it from the text (dropped if the name was deleted from the text). There is no external notification.
const MENTION={ta:/** @type {HTMLTextAreaElement|null} */(null),start:0,items:/** @type {PersonSeen[]} */([]),sel:0};
function mentionQuery(ta){const pos=ta.selectionStart; if(pos==null||pos!==ta.selectionEnd)return null;
  const m=/(^|[^\p{L}\p{N}._@-])@([^\s@]{0,30})$/u.exec(ta.value.slice(0,pos)); return m?{start:pos-m[2].length-1,q:m[2]}:null;}
function mentionMatches(q,people,meLogin){q=String(q||'').toLowerCase();
  const rows=people.filter(p=>p.login!==meLogin).map(p=>{const n=String(p.name||'').toLowerCase(),l=p.login.toLowerCase();
    const at=Math.min(...[n.indexOf(q),l.indexOf(q)].filter(i=>i>=0).concat([99]));
    const word=n.split(/\s+/).some(w=>w.startsWith(q)); return {p,rank:!q?0:at===0?0:word?1:at<99?2:9};});
  return rows.filter(r=>r.rank<9).sort((a,b)=>a.rank-b.rank||String(a.p.name).localeCompare(String(b.p.name))).slice(0,6).map(r=>r.p);}
function mentionHints(ta){if(!ta||!ta._mentions)return []; const v=ta.value;
  return Array.from(ta._mentions).filter(l=>v.includes('@'+peopleName(l)));}
// An '@word' still being typed (the cursor sits at its end) is never flagged as '등록된 사람이 아님' yet - the warning
// used to appear while still picking (QA 2026-09-25). It's flagged once the cursor leaves it or the field. If the same word appears earlier too (an already-finished '@word'), it's still flagged as usual.
function mentionBadSettled(bad,text,q){if(!q)return bad; const w=q.q, before=String(text||'').slice(0,q.start);
  return bad.filter(x=>x!==w||before.includes('@'+w));}
function mentionClose(){MENTION.ta=null; $('#mention-pop').hidden=true;}
// The line below the input field: who will be notified on save (resolved @names) and any '@word' that won't resolve
// ('not a registered person'). Since text can't be colored inside a textarea, this is previewed here instead - so it's
// known before saving whether a tag will actually become a notification. It is the server's resolve_mentions() step for
// step (tests/viewer/test_mentions_parity.py runs one corpus through both): hit is what the server records, in first-seen order.
/** @param {string} text @param {Iterable<string>} [hints] @returns {{hit:string[],bad:string[]}} */
function mentionScan(text,hints){return mentionResolve(text,hints||[],PEOPLE,false);}
// mentionScan's reading over an explicit list of people. A name several people share tags those of them the hints name: in
// the server's order (by login), or with byHint in the hints' own order - the order the text names them (mentionRemember),
// which is what decides who was tagged first (assignOutcome). Pure.
/** @param {string} text @param {Iterable<string>} hints @param {PersonSeen[]} people @param {boolean} byHint @returns {{hit:string[],bad:string[]}} */
function mentionResolve(text,hints,people,byHint){text=String(text||''); const toks=mentionTokens(people),order=[...hints],hs=new Set(order);
  const hit=/** @type {string[]} */([]),bad=/** @type {string[]} */([]),low=text.toLowerCase();
  for(let i=0;i<text.length;i++){if(text[i]!=='@'||mentionAfterWord(text,i))continue;
    const rest=low.slice(i+1); let got=/** @type {string[]|null} */(null);
    for(const x of toks){if(!rest.startsWith(x.t))continue;
      const nx=rest.charAt(x.t.length); if(/[a-z0-9]$/.test(x.t)&&/[a-z0-9_]/.test(nx))continue;
      const pick=x.lg.length===1?x.lg:byHint?order.filter(l=>x.lg.includes(l)):x.lg.filter(l=>hs.has(l)); if(pick.length){got=pick;break;}}
    if(got)got.forEach(l=>{if(!hit.includes(l))hit.push(l);});
    else{const w=/^[^\s@]{1,30}/.exec(text.slice(i+1)); if(w&&!bad.includes(w[0]))bad.push(w[0]);}}
  return {hit,bad};}
// The server's mention_tokens(): [{t, lg:[login...]}], longest first. The candidates of a person are the full name, the
// login, the login before '@' and the name's first word (when it has several), lower-cased; a candidate shorter than two
// characters (code points, as Python counts) is none. The same candidate twice for one person is one entry ('Bob' for
// bob@example.com), and a candidate several people share lists them all (sorted) - it then needs a hint.
function mentionTokens(people){const by=new Map();
  (people||[]).forEach(p=>{const lg=String(p.login),nm=String(p.name||''),w=nm.split(/\s+/).filter(Boolean);
    [nm,lg,lg.split('@')[0]].concat(w.length>1?[w[0]]:[]).forEach(t=>{if([...t].length<2)return; const k=t.toLowerCase();
      if(!by.has(k))by.set(k,new Set()); by.get(k).add(lg);});});
  return [...by].map(([t,s])=>({t,lg:[...s].sort()})).sort((a,b)=>[...b.t].length-[...a.t].length);}
// The colleagues a note tags, in the order it first names them - whom an assignee row offers. A colleague is a resolved
// @-tag that is not me (the server drops a tag of its author too), so an unresolved word, a tag taken out of the text and a
// tag of myself are nobody. keep (an edit card's stored assignee) stays offered after its tag left the note. Pure.
/** @param {string} text @param {Iterable<string>} hints @param {PersonSeen[]} people @param {string|null} me @param {string} [keep] @returns {string[]} */
function assignPeople(text,hints,people,me,keep){const out=mentionResolve(text,hints,people,true).hit.filter(l=>l!==me);
  if(keep&&keep!==ASSIGNEE_AGENT&&!out.includes(keep))out.push(keep); return out;}
// Assignee (docs/handbook/viewer.md §담당): what a save of the composer's note does. Every input is an argument - text,
// kind (the request kind), hints (the logins picked from the @-list, in the order the text names them), people (the known
// people), me (the author's login, null on the identity-less screen), mode and pick (the assignee row's state) - so the
// preview line, the assignee row and the request all read one answer, worked out when each needs it.
// - SAVE_MODE.NEW, a new pin: its assignee is the author's pick while that stands (kept: the agent, or a colleague the note
//   still tags), else the first colleague the note tags, wherever the tag sits and whatever the kind, else the agent. told
//   are the colleagues who are only notified - the assignee is told through the assignment.
// - SAVE_MODE.APPEND, the note joins an existing pin: that pin's assignee (stored) and kind stay as they are, there is nobody
//   to choose (people is empty), and every colleague the note tags is told.
// Pure.
/** @param {{text:string,kind:string,hints:string[],people:PersonSeen[],me:string|null,mode:string,pick:{v:string,touched:boolean},stored?:string|null}} q
 *  @returns {{mode:string,kind:string|null,people:string[],assignee:string|null,told:string[],kept:boolean}} */
function assignOutcome(q){const tagged=assignPeople(q.text,q.hints,q.people,q.me);
  if(q.mode===SAVE_MODE.APPEND)return {mode:q.mode,kind:null,people:[],assignee:q.stored||null,told:tagged,kept:false};
  const kept=q.pick.touched&&(q.pick.v===ASSIGNEE_AGENT||tagged.includes(q.pick.v)),assignee=kept?q.pick.v:tagged.length?tagged[0]:ASSIGNEE_AGENT;
  return {mode:q.mode,kind:q.kind,people:tagged,assignee,told:tagged.filter(l=>l!==assignee),kept};}
// assignOutcome's inputs as the composer holds them at this moment, for a save in mode; an append reads the pin it joins.
/** @param {string} mode @returns {Parameters<typeof assignOutcome>[0]} */
function composeAsk(mode){const ta=/** @type {HTMLTextAreaElement} */($('#note')),ov=mode===SAVE_MODE.APPEND?appendTarget():null,p=ov?PINS.find(x=>x.id===ov.id):null;
  return {text:ta.value,kind:KIND_NEW,hints:mentionHints(ta),people:PEOPLE,me:meLogin(),mode,pick:{v:ASSIGN_NEW.v,touched:ASSIGN_NEW.touched},stored:p?p.assignee||null:null};}
// A person's name where the reader must tell people apart (an assignee row, the composer's preview line): the name, with the
// login beside it for a name another known person shares - as the @-list shows every person (.ml).
/** @param {string} login @returns {Html} */
function personLabel(login){return nameShared(login)?html`${peopleName(login)} <span class="ml">${login}</span>`:html`${peopleName(login)}`;}
// Whether another known person has login's displayed name.
/** @param {string} login @returns {boolean} */
function nameShared(login){const nm=peopleName(login); return PEOPLE.some(p=>p.login!==login&&p.name===nm);}
// The assignee row (Html) for people, value pressed; empty Html without people. Each option carries act as its data-act.
// The track scrolls sideways inside the row when it is longer (.lad, the range ladder's rule), so every name reads in full.
// A segment's words are in .as-t, trimmed to their cap height like the row's label, so the two share one centre in any font.
/** @param {string[]} people @param {string} value @param {string} act @returns {Html} */
function assignSeg(people,value,act){if(!people.length)return html``;
  const opt=(v,label,tip)=>html`<button type="button" role="radio" data-act="${act}" data-v="${v}" aria-checked="${v===value}"${v===value?html` class="on"`:''} data-tip="${tip}"><span class="as-t">${label}</span></button>`;
  const agent=opt(ASSIGNEE_AGENT,tr('에이전트'),tr('에이전트가 이 핀을 처리합니다 — @태그한 사람에게는 알림만 갑니다'));
  const others=people.map(l=>opt(l,html`@${personLabel(l)}`,tl('{name}에게 맡깁니다 — 에이전트는 이 핀을 건너뜁니다',{name:peopleName(l)+(nameShared(l)?' ('+l+')':'')})));
  return html`<span class="as-lab">${tr('담당')}</span><div class="seg lad as-seg" data-reveal="whole"><div class="lad-t">${agent}${others}</div></div>`;}
// The composer panel's assignee: the author's pick (touched) or, until there is one, the default re-chosen every time the note
// changes. A pick whose person left the note is dropped. Both assignee rows read the note with the hints the save carries
// (mentionHints), so they offer exactly whom the server tags.
const ASSIGN_NEW={v:ASSIGNEE_AGENT,touched:false};
// Draws the composer's assignee row and the preview line from the note as it is now (assignOutcome), and drops a pick whose
// person left the note. No row without a tagged colleague - the agent has the pin - and none while the note would join an
// existing pin (appendTarget): an append keeps that pin's assignee, so the row would choose nothing. Before the people list
// has arrived (PEOPLE_KNOWN) no pick is dropped: a draft restored at boot keeps its pick until its person can be looked up
// (loadPeople draws the row again). savePin() does not read what is settled here: it asks assignOutcome itself.
function renderAssignNew(){const ta=$('#note'),box=$('#c-assign'); if(!ta||!box)return;
  const o=assignOutcome(composeAsk(SAVE_MODE.NEW)); if(PEOPLE_KNOWN){ASSIGN_NEW.v=/** @type {string} */(o.assignee); ASSIGN_NEW.touched=o.kept;}
  if(o.people.length&&!appendTarget()){setHtml(box,assignSeg(o.people,/** @type {string} */(o.assignee),'assign-new')); box.hidden=false; segReveal(box.querySelector('.as-seg'));}
  else{box.hidden=true; box.replaceChildren();}
  mentionPreview(ta);}
// The edit card's assignee row: the stored assignee stays pressed until the author changes it - a stored pin never takes the
// new pin's default.
function renderAssignEdit(){const E=EDITOR.current; if(!E)return; const ta=editNote(E),box=/** @type {HTMLElement} */(E.el.querySelector('.e-assign')); if(!ta||!box)return;
  const ppl=assignPeople(ta.value,mentionHints(ta),PEOPLE,meLogin(),E.assignee);
  if(!ppl.length){box.hidden=true; box.replaceChildren(); return;}
  setHtml(box,assignSeg(ppl,E.assignee,'assign-edit')); box.hidden=false; segReveal(box.querySelector('.as-seg'));}
// The preview line under a mention field: what sending the text does. The composer's note says who handles the pin first -
// '담당' and the assignee the save sends (assignOutcome, SAVE_MODE.NEW) - then '알림' and the people who are only notified:
// the assignee is told through the assignment and is not listed again. While the note may also join an existing pin
// (appendTarget - the overlap notice's [덧붙이기]) the line says both saves: '덧붙이면 담당' and that pin's assignee, which
// stays, '새 핀이면 담당' and the assignee [핀 저장] sends, and under '알림' everyone the note tags, whom either save tells.
// An edit or a reply assigns nobody and lists whom it notifies. Hidden while the text has no '@' word to report.
function mentionPreview(ta){if(!ta)return; const box=ta.nextElementSibling; if(!box||!box.classList.contains('m-preview'))return;
  const r=mentionScan(ta.value,mentionHints(ta)),me=meLogin();   // the same hints the save/send carries
  r.bad=mentionBadSettled(r.bad,ta.value,document.activeElement===ta?mentionQuery(ta):null);
  if(!r.hit.length&&!r.bad.length){box.hidden=true; box.replaceChildren(); return;}
  const o=ta.id==='note'?assignOutcome(composeAsk(SAVE_MODE.NEW)):null,join=o&&appendTarget()?assignOutcome(composeAsk(SAVE_MODE.APPEND)):null;
  const told=o&&!join?r.hit.filter(l=>l!==o.assignee):r.hit;
  const name=l=>l===ASSIGNEE_AGENT?html`<span class="m-who">${tr('에이전트')}</span>`:html`<span class="mention">${personLabel(l)}</span>`;
  const kept=join?html`<span class="m-lab">${tr('덧붙이면 담당')}</span><span class="m-who">${tl('{name} 그대로',{name:assigneeWord(join.assignee)})}</span>`:'';
  const who=!o?'':html`${kept}<span class="m-lab">${tr(join?'새 핀이면 담당':'담당')}</span>${name(/** @type {string} */(o.assignee))}`;
  const hits=told.length?html`<span class="m-lab">${ic('at-sign')}알림</span>${told.map(l=>html`<span class="mention${l===me?' me':''}">${personLabel(l)}${l===me?' '+tr('(나 — 알림 없음)'):''}</span>`)}`:'';
  const bad=r.bad.map(w=>html`<span class="mention-bad" data-tip="등록된 사람이 아님 — 이 이름으로는 알림이 가지 않습니다. 이 뷰어를 연 테일넷 사람만 부를 수 있습니다">@${w}</span>`);
  setHtml(box,html`${who}${hits}${bad}${r.bad.length?html`<span class="m-note">등록된 사람이 아님</span>`:''}`);
  box.hidden=false;}
function mentionUpdate(ta){const q=mentionQuery(ta); if(!q){if(MENTION.ta===ta)mentionClose(); return;}
  const me=META&&META.me&&META.me.login; MENTION.ta=ta; MENTION.start=q.start; MENTION.items=mentionMatches(q.q,PEOPLE,me);
  MENTION.sel=Math.min(MENTION.sel,Math.max(0,MENTION.items.length-1));
  const pop=$('#mention-pop');
  const none=(q.q?tl("'{q}' 와 맞는 사람이 없습니다",{q:q.q}):tr('부를 수 있는 사람이 없습니다'))+' — '+tr('이 뷰어를 연 테일넷 사람만 부를 수 있습니다');
  setHtml(pop,MENTION.items.length?html`${MENTION.items.map((p,i)=>html`<button type="button" role="option" aria-selected="${i===MENTION.sel}" data-act="mention-pick" data-i="${i}">\
${avatar(p)}<span>${p.name}</span><span class="ml">${p.login}</span></button>`)}`:html`<div class="dim">${none}</div>`);
  pop.hidden=false; const r=ta.getBoundingClientRect(),h=pop.offsetHeight,w=pop.offsetWidth,vv=window.visualViewport;
  const g=mentionGuard(ta); pop.style.top=mentionTop(r,g?g.getBoundingClientRect():null,h,vv?vv.offsetTop:0,vv?vv.offsetTop+vv.height:innerHeight)+'px';
  pop.style.left=Math.max(4,Math.min(r.left,innerWidth-w-4))+'px';}
// The action row of that input field that the @-list must never cover: reply/reopen [취소][보내기], edit [저장], composer panel [취소][핀 저장].
function mentionGuard(ta){const box=ta.closest('.reply-box,.edit'); return box?box.querySelector('.r-acts,.e-acts'):ta.id==='note'?$('#c-actions'):null;}
// The @-list's top (docs/handbook/viewer.md §@태그). A spot that never covers the action row (guard) is chosen in this order -
// (1) right below the input field (if it fits above the action row) (2) above the input field (3) below the action row
// (4) if nothing fits, below the input field (the old spot). A reply field has [취소][보내기] right below it, so (1)
// never fits and (2) is used instead (the list used to cover both buttons, QA 2026-09-25).
function mentionTop(r,g,h,top,bot){const gap=4,lim=g&&g.top>=r.bottom?Math.min(bot,g.top):bot;
  if(r.bottom+gap+h<=lim)return r.bottom+gap;
  if(r.top-gap-h>=top+gap)return r.top-gap-h;
  if(g&&g.bottom+gap+h<=bot)return g.bottom+gap;
  return Math.max(top+gap,Math.min(r.bottom+gap,bot-h-gap));}
// Remembers login as a hint of ta, for a tag that starts at `at` in its text. Among the hints of people with the same
// displayed name it takes the place its tag has among that name's tags in the text - the n-th '@name' is the n-th of them -
// so the hints say who was tagged first (mentionResolve's byHint); the other hints keep their order.
/** @param {HTMLTextAreaElement} ta @param {string} login @param {number} at */
function mentionRemember(ta,login,at){const name=peopleName(login),all=Array.from(ta._mentions||[]).filter(l=>l!==login);
  const next=all.filter(l=>peopleName(l)===name)[ta.value.slice(0,at).split('@'+name).length-1];
  all.splice(next===undefined?all.length:all.indexOf(next),0,login); ta._mentions=new Set(all);}
// Inserts the picked person as '@name ' at the cursor, remembers the login as a hint, and refreshes what depends on the
// field (the preview, the assignee, the reply outcome; the note's draft).
function mentionApply(i){const ta=MENTION.ta,p=MENTION.items[i]; if(!ta||!p)return; const pos=ta.selectionStart,ins='@'+p.name+' ';
  ta.value=ta.value.slice(0,MENTION.start)+ins+ta.value.slice(pos); const c=MENTION.start+ins.length; ta.setSelectionRange(c,c);
  mentionRemember(ta,p.login,MENTION.start); mentionClose(); ta.focus(); autoGrow(ta);
  if(ta.id==='note'){renderAssignNew(); saveDraftSoon(); return;}   // the composer's row draws its preview line too
  mentionPreview(ta); if(ta.classList.contains('e-note'))renderAssignEdit(); else if(ta.classList.contains('r-text'))renderReplyOutcome();}
const isMentionField=t=>!!t&&t.tagName==='TEXTAREA'&&(t.id==='note'||t.classList.contains('e-note')||t.classList.contains('r-text'));
document.addEventListener('input',e=>{const t=/** @type {HTMLTextAreaElement} */(e.target); if(!isMentionField(t))return; mentionUpdate(t);
  if(t.id==='note'){renderAssignNew(); qHint($('#c-qhint'),t.value,KIND_NEW); saveDraftSoon(); return;}   // the row draws the preview line too
  mentionPreview(t);
  if(t.classList.contains('e-note')){renderAssignEdit(); if(EDITOR.current)qHint(EDITOR.current.el.querySelector('.e-qhint'),t.value,EDITOR.current.kind_req);}
  else if(t.classList.contains('r-text'))renderReplyOutcome();});
window.addEventListener('keydown',e=>{if(!MENTION.ta||e.target!==MENTION.ta||$('#mention-pop').hidden||e.isComposing)return;
  const n=MENTION.items.length;
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){if(!n)return; e.preventDefault(); e.stopImmediatePropagation();
    MENTION.sel=(MENTION.sel+(e.key==='ArrowDown'?1:n-1))%n; mentionUpdate(MENTION.ta);}
  else if((e.key==='Enter'&&!e.metaKey&&!e.ctrlKey)||e.key==='Tab'){if(!n)return; e.preventDefault(); e.stopImmediatePropagation(); mentionApply(MENTION.sel);}
  else if(e.key==='Escape'){e.preventDefault(); e.stopImmediatePropagation(); mentionClose();}},true);
// When the cursor leaves the '@word' being typed (arrow key/click/leaving the field), the preview redraws and warns at that point.
['keyup','click','focusout'].forEach(t=>document.addEventListener(t,e=>{if(isMentionField(e.target))setTimeout(()=>mentionPreview(e.target),0);}));
document.addEventListener('focusout',e=>{if(e.target===MENTION.ta)setTimeout(()=>{if(document.activeElement!==MENTION.ta)mentionClose();},150);});
$('#mention-pop').addEventListener('pointerdown',e=>e.preventDefault());

