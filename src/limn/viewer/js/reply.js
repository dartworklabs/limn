// ------------------------------------------------ Reply input field (docs/handbook/viewer.md §스레드와 검토)
// Only one input field is ever open. Its DOM is held on REPLY.el, and when drawPins() redraws cards, it's re-inserted
// into .reply-slot - so the 5-second auto-sync redrawing the list never loses the draft text or cursor (focus is
// restored too). There is one [답글] for every state: on a closed pin (awaiting review or done) the server decides whether the
// reply reopens it (reply_reopens), and the line under the box (.r-outcome) previews that decision with the same rule
// (replyReopens) - [상태 유지] (REPLY.keep) overrides it with reopen:false. Sending is deferred behind an undo toast.
function isHuman(){const me=typeof META!=='undefined'&&META&&META.me; return !!(me&&me.login&&me.login!=='local'&&!String(me.login).startsWith('agent:')&&me.role!=='agent');}
// Mirrors the server's reply_reopens(): an open pin never changes; an explicit override (true/false) wins; otherwise a person's reply
// on a closed pin reopens it unless it tags a person or the pin is a question. mentioned = the post's resolved @-tags without me.
function replyReopens(p,human,mentioned,override){if(pinState(p)==='open')return false;
  if(override!==undefined&&override!==null)return !!override;
  if(p.kind_req==='question'||!human)return false; return !(mentioned&&mentioned.length);}
// The outcome line: {text, toggle}, or null for an open pin (a reply never changes it). toggle names the one rare override the box
// offers: 'keep' ([상태 유지], reopen:false) where the rule would reopen, 'reopen' ([다시 열기], reopen:true) where it keeps a closed pin
// as it is. flip = that toggle is pressed.
function replyPreview(p,human,mentioned,flip){if(!p||pinState(p)==='open')return null; const m=mentioned||[];
  const reopens=replyReopens(p,human,m),toggle=reopens?'keep':'reopen',names=m.map(peopleName).join(', ');
  if(flip&&!reopens)return {text:m.length?tl('보내면 이 핀이 다시 열려 에이전트에게 가고, {names}에게 알림이 갑니다',{names}):tr('보내면 이 핀이 다시 열려 에이전트에게 갑니다'),toggle};
  if(flip)return {text:tr('보내도 상태는 그대로입니다'),toggle};
  if(reopens)return {text:tr('보내면 이 핀이 다시 열려 에이전트에게 갑니다'),toggle};
  if(p.kind_req==='question')return {text:tr('답으로 남고 상태는 그대로입니다'),toggle};
  if(!human)return {text:tr('이 화면은 에이전트로 보내므로 상태는 그대로입니다'),toggle};
  return {text:tl('보내면 {names}에게 알림이 가고 상태는 그대로입니다',{names}),toggle};}
// The empty box's placeholder says the same outcome as the line under it would for a reply without @-tags.
function replyPlaceholder(p,human,flip){const closed=!!p&&pinState(p)!=='open',def=closed&&replyReopens(p,human,[]);
  return tr(closed&&(flip?!def:def)?'무엇이 틀렸는지 적으면 다시 열려 에이전트에게 갑니다 (⌘/Ctrl+Enter 보내기)':'답글 (⌘/Ctrl+Enter 보내기)');}
// After the deferred send: a note only when the server's decision differs from the preview (the pin changed state while the
// undo toast was up, e.g. someone else's reply reopened it first). Worded from the response, not from the guess.
function replyServerNote(id,predicted,data){if(!data||!data.ok||!!data.reopened===!!predicted)return null;
  if(data.reopened)return tl('#{id} 은 그사이 닫혀서 이 답글이 다시 열었습니다',{id});
  return data.state==='open'?tl('#{id} 은 그사이 이미 열려 있어 답글로만 남았습니다',{id}):tl('#{id} 은 다시 열리지 않고 답글로만 남았습니다',{id});}
// The post's @-tags that count as asking a person: without me and without agent-role accounts (as the server's rule).
// Resolved with exactly the hints the request will carry (mentionHints) - the server resolves the same text with the same hints,
// so an autocompleted '@Robin Lee' later edited down to an ambiguous '@Robin' previews what the server will do (PR #11 review).
function replyMentioned(ta){const me=meLogin(); return mentionScan(ta.value,new Set(mentionHints(ta))).hit.filter(l=>l!==me&&(PEOPLE.find(x=>x.login===l)||{}).role!=='agent');}
function replyEl(p){const el=document.createElement('div'); el.className='reply-box';
  el.innerHTML='<textarea class="r-text" rows="2" maxlength="1000" aria-label="답글" placeholder="'+esc(replyPlaceholder(p,isHuman(),false))+'"></textarea><div class="m-preview" aria-live="polite" hidden></div>'+
    '<div class="r-outcome" aria-live="polite" hidden><span class="r-out-t"></span><button type="button" class="btn-sm r-keep" role="switch" data-act="reply-flip" aria-checked="false"></button></div>'+
    '<div class="r-err errline" role="alert" hidden></div>'+
    '<div class="r-acts"><button class="btn-sm" data-act="reply-cancel" data-tip="입력 칸을 닫습니다 (Esc). 쓰던 글은 남겨 둡니다">취소</button>'+
    '<button class="btn-sm btn-default" data-act="reply-send" data-tip="답글을 보냅니다. 알림의 [되돌리기]를 누르면 보내기 전에 취소됩니다">보내기</button></div>';
  return el;}
function renderReplyOutcome(){const R=REPLY; if(!R)return; const box=R.el.querySelector('.r-outcome'),ta=R.el.querySelector('textarea'); if(!box||!ta)return;
  const p=findAnyPin(R.id),ment=replyMentioned(ta);
  let pv=p&&replyPreview(p,isHuman(),ment,!!R.flip);
  ta.placeholder=replyPlaceholder(p,isHuman(),!!R.flip);
  if(!pv){box.hidden=true; R.flip=false; R.toggle=null; return;}
  if(R.toggle&&R.toggle!==pv.toggle&&R.flip){R.flip=false; pv=replyPreview(p,isHuman(),ment,false);}   // the rule changed direction (a tag added/removed): the override resets
  R.toggle=pv.toggle; box.hidden=false; box.querySelector('.r-out-t').textContent=pv.text;
  box.classList.toggle('reopen',replyReopens(p,isHuman(),ment,R.flip?pv.toggle==='reopen':undefined));
  const k=box.querySelector('[data-act=reply-flip]'),keep=pv.toggle==='keep';
  k.textContent=tr(keep?'상태 유지':'다시 열기'); k.dataset.tip=tr(keep?'보내도 핀을 다시 열지 않고 답글만 남깁니다(드물게 씁니다)':'보내면서 핀을 다시 열어 에이전트에게 보냅니다(드물게 씁니다)');
  k.setAttribute('aria-checked',String(!!R.flip));}
// Opens the one reply box on pin id with its kept draft; the panel opens if it was collapsed.
function openReply(id){
  if(REPLY&&REPLY.id===id){const t=REPLY.el.querySelector('textarea'); if(t)t.focus(); return;}
  if(REPLY)closeReply(false);
  const p=findAnyPin(id);
  REPLY={id,flip:false,toggle:null,el:replyEl(p)}; OPEN_CARDS.add(id); setSide(true); drawPins();
  const ta=REPLY.el.querySelector('textarea'); ta.value=REPLY_DRAFT.get('reply:'+id)||''; autoGrow(ta); mentionPreview(ta); renderReplyOutcome(); ta.focus();
  REPLY.el.scrollIntoView({block:'nearest'});}
function closeReply(redraw){if(!REPLY)return; const ta=REPLY.el.querySelector('textarea');
  if(ta&&ta.value.trim())REPLY_DRAFT.set('reply:'+REPLY.id,ta.value); else REPLY_DRAFT.delete('reply:'+REPLY.id);
  REPLY=null; if(redraw!==false)drawPins();}
function sendReply(){const R=REPLY; if(!R||viewerBlocked())return; const ta=R.el.querySelector('textarea'),text=ta.value.trim();
  if(!text){toast('답글이 비어 있습니다','warn'); ta.focus(); return;}
  const id=R.id,p=findAnyPin(id),body={text},mh=mentionHints(ta),hints=ta._mentions,flip=!!R.flip; if(mh.length)body.mentions=mh;
  if(flip&&p&&pinState(p)!=='open'&&R.toggle)body.reopen=R.toggle==='reopen';
  const reopens=!!p&&replyReopens(p,isHuman(),replyMentioned(ta),body.reopen);
  // Back into the box - after [되돌리기], or with an inline error when sending failed (offline), so the draft is visibly kept.
  const back=err=>{REPLY_DRAFT.set('reply:'+id,text); openReply(id);
    if(REPLY&&REPLY.id===id){const t=REPLY.el.querySelector('textarea'); if(hints)t._mentions=hints; REPLY.flip=flip; mentionPreview(t); renderReplyOutcome();
      const e=REPLY.el.querySelector('.r-err'); if(e){e.textContent=err||''; e.hidden=!err;}}};
  REPLY_DRAFT.delete('reply:'+id); REPLY=null; drawPins();          // the box closes at once; the post waits for the undo toast
  const d=deferred(tl(reopens?'핀 #{id} 다시 열어 에이전트에게 보냄':'#{id} 에 답글을 남겼습니다',{id}),
    async()=>{markMine(id);
      try{const {data}=await api('/api/pins/'+id+'/reply',{method:'POST',body,what:'답글',keepalive:true});
        if(!data.ok)toast(tl('핀 #{id} 이 없습니다',{id}),'err');
        else{const note=replyServerNote(id,reopens,data); if(note)toast(note,'warn');}}
      catch(e){back(tr('보내지 못했습니다 — 글은 그대로 두었습니다. 연결을 확인하고 다시 보내세요'));}
      await loadPins();},
    ()=>back(null));
  // Keyboard users (Ctrl+Enter) land on [되돌리기], so Enter undoes; the toast still commits when it goes away.
  const b=d.toast&&d.toast.querySelector('.t-acts button'); if(b)b.focus({preventScroll:true});}

