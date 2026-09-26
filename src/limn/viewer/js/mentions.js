// ------------------------------------------------ @-tag autocomplete (docs/handbook/viewer.md §@태그)
// Typing '@' in the note/edit/reply field shows known people (PEOPLE, excluding me). Picking one inserts '@name ' and
// remembers that login on the field (ta._mentions), carried as a hint (mentions) when sending - the server re-resolves
// it from the text (dropped if the name was deleted from the text). There is no external notification.
const MENTION={ta:null,start:0,items:[],sel:0};
function mentionQuery(ta){const pos=ta.selectionStart; if(pos==null||pos!==ta.selectionEnd)return null;
  const m=/(^|[^0-9A-Za-z가-힣._@-])@([^\s@]{0,30})$/.exec(ta.value.slice(0,pos)); return m?{start:pos-m[2].length-1,q:m[2]}:null;}
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
// known before saving whether a tag will actually become a notification. The rule matches the server's resolve_mentions() (see the fmtText comment).
function mentionScan(text,hints){text=String(text||''); const toks=mentionToks(PEOPLE.map(p=>p.login)).map(x=>({t:x.t.toLowerCase(),lg:x.lg}));
  const hit=[],bad=[],low=text.toLowerCase(),hs=hints||new Set(); let first=null;
  for(let i=0;i<text.length;i++){if(text[i]!=='@'||(i>0&&/[0-9A-Za-z가-힣._-]/.test(text[i-1])))continue;
    const rest=low.slice(i+1); let got=null;
    for(const x of toks){const t=x.t.replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'");
      if(!rest.startsWith(t))continue; const nx=rest.charAt(t.length); if(/[a-z0-9]$/.test(t)&&/[a-z0-9_]/.test(nx))continue;
      const all=toks.filter(y=>y.t===x.t).map(y=>y.lg),pick=all.length===1?all:all.filter(l=>hs.has(l)); if(pick.length){got=pick;break;}}
    if(got){got.forEach(l=>{if(!hit.includes(l))hit.push(l);}); if(first===null&&!text.slice(0,i).trim())first=got[0];}
    else{const w=/^[^\s@]{1,30}/.exec(text.slice(i+1)); if(w&&!bad.includes(w[0]))bad.push(w[0]);}}
  return {hit,bad,first};}
// Assignee (docs/handbook/viewer.md §담당): who handles this pin. Default - if the note starts with a resolved @-tag, that
// person; otherwise a question pin's first @-tag; otherwise the agent. I can never be picked (just as the server
// excludes a tag mentioning me). With no @-tags, there's nothing to pick (the agent).
function defaultAssignee(text,kind,hints){const r=mentionScan(text,hints),me=meLogin(),hit=r.hit.filter(l=>l!==me);
  if(r.first&&r.first!==me)return r.first; if(kind==='question'&&hit.length)return hit[0]; return 'agent';}
function assignPeople(text,hints,keep){const me=meLogin(),out=mentionScan(text,hints).hit.filter(l=>l!==me);
  if(keep&&keep!=='agent'&&!out.includes(keep))out.push(keep); return out;}
function assignSeg(people,value,act){if(!people.length)return '';
  const opt=(v,label,tip)=>'<button type="button" role="radio" data-act="'+act+'" data-v="'+esc(v)+'" aria-checked="'+(v===value)+'"'+(v===value?' class="on"':'')+
    ' data-tip="'+esc(tip)+'">'+label+'</button>';
  return '<span class="as-lab">'+esc(tr('담당'))+'</span><div class="seg as-seg">'+opt('agent',esc(tr('에이전트')),tr('에이전트가 이 핀을 처리합니다 — @태그한 사람에게는 알림만 갑니다'))+
    people.map(l=>opt(l,'@'+esc(peopleName(l)),tl('{name}에게 맡깁니다 — 에이전트는 이 핀을 건너뜁니다',{name:peopleName(l)}))).join('')+'</div>';}
// The composer panel's assignee: before the user picks one (touched=false), the default is re-chosen every time the note changes. If the picked person disappears from the note, it falls back to the default.
const ASSIGN_NEW={v:'agent',touched:false};
function renderAssignNew(){const ta=$('#note'),box=$('#c-assign'); if(!ta||!box)return;
  const ppl=assignPeople(ta.value,ta._mentions);
  if(!ASSIGN_NEW.touched||(ASSIGN_NEW.v!=='agent'&&!ppl.includes(ASSIGN_NEW.v))){ASSIGN_NEW.v=defaultAssignee(ta.value,KIND_NEW,ta._mentions); ASSIGN_NEW.touched=false;}
  if(!ppl.length){ASSIGN_NEW.v='agent'; box.hidden=true; box.innerHTML=''; return;}
  box.innerHTML=assignSeg(ppl,ASSIGN_NEW.v,'assign-new'); box.hidden=false;}
function renderAssignEdit(){const E=EDIT; if(!E)return; const ta=E.el.querySelector('.e-note'),box=E.el.querySelector('.e-assign'); if(!ta||!box)return;
  const ppl=assignPeople(ta.value,ta._mentions,E.assignee);
  if(!ppl.length){box.hidden=true; box.innerHTML=''; return;}
  box.innerHTML=assignSeg(ppl,E.assignee,'assign-edit'); box.hidden=false;}
function mentionPreview(ta){if(!ta)return; const box=ta.nextElementSibling; if(!box||!box.classList.contains('m-preview'))return;
  const r=mentionScan(ta.value,new Set(mentionHints(ta))),me=meLogin();   // the same hints the save/send carries r.bad=mentionBadSettled(r.bad,ta.value,document.activeElement===ta?mentionQuery(ta):null);
  if(!r.hit.length&&!r.bad.length){box.hidden=true; box.innerHTML=''; return;}
  box.innerHTML=(r.hit.length?'<span class="m-lab">'+ic('at-sign')+'알림</span>'+r.hit.map(l=>'<span class="mention'+(l===me?' me':'')+'">'+esc(peopleName(l))+(l===me?' '+esc(tr('(나 — 알림 없음)')):'')+'</span>').join(''):'')+
    r.bad.map(w=>'<span class="mention-bad" data-tip="등록된 사람이 아님 — 이 이름으로는 알림이 가지 않습니다. 이 뷰어를 연 테일넷 사람만 부를 수 있습니다">@'+esc(w)+'</span>').join('')+
    (r.bad.length?'<span class="m-note">등록된 사람이 아님</span>':'');
  box.hidden=false;}
function mentionUpdate(ta){const q=mentionQuery(ta); if(!q){if(MENTION.ta===ta)mentionClose(); return;}
  const me=META&&META.me&&META.me.login; MENTION.ta=ta; MENTION.start=q.start; MENTION.items=mentionMatches(q.q,PEOPLE,me);
  MENTION.sel=Math.min(MENTION.sel,Math.max(0,MENTION.items.length-1));
  const pop=$('#mention-pop');
  pop.innerHTML=MENTION.items.length?MENTION.items.map((p,i)=>'<button type="button" role="option" aria-selected="'+(i===MENTION.sel)+'" data-act="mention-pick" data-i="'+i+'">'+
    avatar(p)+'<span>'+esc(p.name)+'</span><span class="ml">'+esc(p.login)+'</span></button>').join(''):
    '<div class="dim">'+esc((q.q?tl("'{q}' 와 맞는 사람이 없습니다",{q:q.q}):tr('부를 수 있는 사람이 없습니다'))+' — '+tr('이 뷰어를 연 테일넷 사람만 부를 수 있습니다'))+'</div>';
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
// Inserts the picked person as '@name ' at the cursor, remembers the login as a hint, and refreshes what depends on the
// field (the preview, the assignee, the reply outcome; the note's draft).
function mentionApply(i){const ta=MENTION.ta,p=MENTION.items[i]; if(!ta||!p)return; const pos=ta.selectionStart,ins='@'+p.name+' ';
  ta.value=ta.value.slice(0,MENTION.start)+ins+ta.value.slice(pos); const c=MENTION.start+ins.length; ta.setSelectionRange(c,c);
  (ta._mentions=ta._mentions||new Set()).add(p.login); mentionClose(); ta.focus(); autoGrow(ta); mentionPreview(ta);
  if(ta.id==='note'){renderAssignNew(); saveDraftSoon();} else if(ta.classList.contains('e-note'))renderAssignEdit(); else if(ta.classList.contains('r-text'))renderReplyOutcome();}
const isMentionField=t=>!!t&&t.tagName==='TEXTAREA'&&(t.id==='note'||t.classList.contains('e-note')||t.classList.contains('r-text'));
document.addEventListener('input',e=>{if(isMentionField(e.target)){mentionUpdate(e.target); mentionPreview(e.target);
  if(e.target.id==='note'){renderAssignNew(); qHint($('#c-qhint'),e.target.value,KIND_NEW); saveDraftSoon();}
  else if(e.target.classList.contains('e-note')){renderAssignEdit(); if(EDIT)qHint(EDIT.el.querySelector('.e-qhint'),e.target.value,EDIT.kind_req);}
  else if(e.target.classList.contains('r-text'))renderReplyOutcome();}});
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

