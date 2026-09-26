// ------------------------------------------------ Server calls and notifications
async function api(url,o){o=o||{};
  const init={method:o.method||'GET',headers:{}}; if(o.keepalive)init.keepalive=true;
  if(o.body!==undefined){init.body=JSON.stringify(o.body);init.headers['Content-Type']='application/json';}
  let r;
  const failed=()=>tl('{what} 실패',{what:tr(o.what||'요청').replace(/…$/,'')});
  try{r=await fetch(url,init);}catch(e){if(!o.silent)toast(failed()+' — '+tr('서버에 닿지 않습니다'),'err');throw e;}
  let d=null; try{d=await r.json();}catch(e){}
  if(r.status>=400&&!(o.expect||[]).includes(r.status)){
    if(!o.silent)toast(failed()+' — '+(errText(d)||('HTTP '+r.status)),'err');
    const err=new Error('HTTP '+r.status); err.status=r.status; err.data=d; throw err;}
  return {status:r.status,data:d};
}
// Toasts (docs/handbook/viewer.md §알림(토스트)): one title line + one faded description line. Text is split into title/description at the first ' — ' (or the first ' · ' if none).
const TOAST_IC={ok:()=>ic('circle-check'),warn:()=>ic('triangle-alert'),err:()=>ic('circle-x')};
// If ' — ' is present, everything before it is the title (the title of '핀 #10 · 본문 — 서준님이 불렀습니다: …' is '핀 #10 · 본문'), otherwise everything before the first ' · '.
function toastSplit(msg){msg=String(msg==null?'':msg); const m=/^(.+?) — (.+)$/.exec(msg)||/^(.+?) · (.+)$/.exec(msg); return m?[m[1],m[2]]:[msg,''];}
// Never announces the same transition on the same pin twice (QA: a focused tab showed both '핀 #37 · 본문 — 검토 대기: …' and '#37 이 검토 대기로 넘어왔습니다'
// at once). dd={keys:['review_requested:37'],rank}: if a toast with the same key is already showing within 8 seconds, a higher-rank new one replaces the old,
// while a lower-rank one is suppressed. The same rank (the same path) is treated as a different event and both are shown (e.g. a second awaiting-review after a reopen). The browser-notification path (notifyShow, rank 2) beats the list-comparison toast (rank 1).
const TOAST_KEYS=[];
function toastDup(dd){if(!dd||!dd.keys||!dd.keys.length)return false; const now=Date.now(),rank=dd.rank||1;
  for(let i=TOAST_KEYS.length-1;i>=0;i--){const x=TOAST_KEYS[i]; if(now-x.t>8000||!x.el.isConnected){TOAST_KEYS.splice(i,1);continue;}
    if(!dd.keys.some(k=>x.keys.includes(k)))continue;
    if(x.rank>rank&&dd.keys.every(k=>x.keys.includes(k)))return true;   // a new toast on the same path (same rank) is a different event - never suppressed
    if(rank>x.rank){x.el.remove(); TOAST_KEYS.splice(i,1);}}
  return false;}
// Shows one toast, newest on top (more than six drop the oldest, firing its _gone), with an optional action button;
// returns the element, or null when toastDup() suppressed it.
function toast(msg,kind,action,dd){msg=trMsg(msg);
  if(toastDup(dd))return null;
  kind=TOAST_IC[kind]?kind:'ok';
  const box=toastHost(),t=document.createElement('div'); t.className='toast '+kind;
  const [title,desc]=toastSplit(msg);
  t.innerHTML=TOAST_IC[kind]()+'<div class="t-body"><div class="t-title"></div>'+(desc?'<div class="t-desc"></div>':'')+'</div><div class="t-acts"></div>';
  t.querySelector('.t-title').textContent=title; if(desc)t.querySelector('.t-desc').textContent=desc;
  const acts=t.querySelector('.t-acts');
  let timer=null; const kill=()=>{clearTimeout(timer);t.remove();hideTip();toastGone(t);};
  const arm=()=>{clearTimeout(timer);timer=setTimeout(kill,6000);};
  if(action){const b=document.createElement('button');b.className='btn-sm';b.textContent=action.label;b.dataset.tip=action.tip||T.undo;
    b.addEventListener('click',()=>{t._gone=null;kill();action.fn();});acts.appendChild(b);}
  const c=document.createElement('button');c.className='btn-icon btn-sm btn-ghost';c.innerHTML=ic('x');
  c.setAttribute('aria-label','알림 닫기');c.addEventListener('click',kill);acts.appendChild(c);
  t.addEventListener('mouseenter',()=>clearTimeout(timer)); t.addEventListener('mouseleave',arm);
  placeToasts(); box.insertBefore(t,box.firstChild); arm();
  for(let ts=box.querySelectorAll('.toast');ts.length>6;ts=box.querySelectorAll('.toast')){const l=ts[ts.length-1]; l.remove(); toastGone(l);}
  if(dd&&dd.keys&&dd.keys.length)TOAST_KEYS.push({keys:dd.keys.slice(),rank:dd.rank||1,el:t,t:Date.now()});
  watchToasts();
  return t;
}
// A toast's _gone hook runs once when it leaves the screen for any reason but its own action button - timeout, [x], or being
// pushed out by newer toasts. deferred() uses it: the action commits only once [되돌리기] is no longer on screen.
function toastGone(t){const g=t&&t._gone; if(g){t._gone=null; g();}}
// While a modal dialog is open (the Trash), the rest of the page is inert - a toast outside it could not be clicked. The toast box
// moves into the open modal dialog and back to <body> when it closes.
function toastHost(){const box=$('#toasts'),d=document.querySelector('dialog[open]:modal'),host=d||document.body;
  if(box.parentNode!==host)host.appendChild(box); return box;}
document.addEventListener('close',e=>{if(e.target&&e.target.tagName==='DIALOG'){const box=$('#toasts'); if(box.parentNode===e.target)document.body.appendChild(box);}},true);
// Deferred commit with an undo toast (docs/handbook/viewer.md §알림(토스트)): the change is sent when the toast goes away - after its 6 seconds
// (paused while hovered), on [x], or when the page is hidden - and [되돌리기] cancels it before anything reaches the server. So an
// agent never sees a reply or permanent delete that was taken back. The page being hidden or closed sends what is pending (fetch keepalive).
const DEFERRED=new Set();
function deferred(msg,commit,undo){let done=false,t=null;
  // Committing early (page hidden) also takes the toast away - an [되돌리기] that can no longer cancel anything must not stay on screen.
  const d={run:()=>{if(done)return; done=true; DEFERRED.delete(d); if(t&&t.isConnected){t._gone=null; t.remove();} commit();}};
  DEFERRED.add(d);
  t=toast(msg,'ok',{label:'되돌리기',tip:'보내기 전에 취소합니다',fn:()=>{if(done)return; done=true; DEFERRED.delete(d); undo();}});
  d.toast=t; if(t)t._gone=d.run; else d.run();
  return d;}
function flushDeferred(){Array.from(DEFERRED).forEach(d=>d.run());}
window.addEventListener('pagehide',flushDeferred);
document.addEventListener('visibilitychange',()=>{if(document.hidden)flushDeferred();});
// Toast placement: near where you just clicked. wide/mid is bottom-right of the panel column - just above the top edge of whichever action row is
// visible (#c-actions: save/cancel, mid's bottom tool bar, or the status chips floating in collapsed mid). narrow is just above the sheet's top edge
// (or above the screen if the sheet nearly fills it). While showing, the position is re-measured (watchToasts) whenever the panel opens/closes or the
// composer panel appears - so the save/cancel buttons and the bottom tool bar are never covered.
function placeToasts(){const box=$('#toasts'),right=$('#right'); if(!box||!right)return;
  const R=document.documentElement.style,gap=8,vh=innerHeight;
  const shown=el=>{if(!el||el.hidden)return false; const cs=getComputedStyle(el); if(cs.display==='none'||cs.visibility==='hidden')return false;
    const r=el.getBoundingClientRect(); return r.height>0&&r.width>0&&r.top<vh;};
  let top=vh,r=12,w=360;
  if(LAYOUT==='narrow'){r=8; w=innerWidth-16; if(shown(right))top=Math.min(top,right.getBoundingClientRect().top);
    // If the sheet covers most of the screen (starts within the top 30%), there's no room above it - raising it above the screen
    // instead covered the sheet's own tool bar ([더보기] etc.), making it unpressable (a touch regression). In that case, it's placed inside the
    // sheet near the bottom, above the save/cancel row if that's visible.
    if(top<vh*0.3){top=vh; const ca=$('#c-actions'); if(shown(ca))top=ca.getBoundingClientRect().top;}}
  else{const open=SIDE_OPEN,rr=right.getBoundingClientRect();
    if(open&&rr.width>0){r=Math.max(gap,innerWidth-rr.right+12); w=Math.min(380,rr.width-24);}
    else if(LAYOUT==='wide'){const L=$('#left'),lr=L.getBoundingClientRect();   // collapsed wide: the PDF area's bottom-right, left of its scrollbar
      r=Math.max(gap,innerWidth-(lr.left+L.clientLeft+L.clientWidth)+12); w=Math.min(360,L.clientWidth-24);}
    else w=Math.min(360,innerWidth-24);
    ['#c-actions'].concat(LAYOUT==='mid'?['#bar1']:[],!open?['#bar2','#banner']:[]).forEach(s=>{const e=$(s);
      if(shown(e))top=Math.min(top,e.getBoundingClientRect().top);});}
  R.setProperty('--toast-b',Math.max(gap,Math.round(vh-top+gap))+'px'); R.setProperty('--toast-r',Math.round(r)+'px'); R.setProperty('--toast-w',Math.round(Math.max(200,w))+'px');}
let TOAST_WATCH=0;
// Re-places the toasts every 250ms while any is on screen - panels and sheets open and close under them.
function watchToasts(){if(TOAST_WATCH)return; TOAST_WATCH=setInterval(()=>{if(!$('#toasts .toast')){clearInterval(TOAST_WATCH);TOAST_WATCH=0;return;} placeToasts();},250);}
// More than three toasts fold into a stack (docs/handbook/viewer.md §알림(토스트)). A mouse opens it by hovering or focusing it; on
// touch - where a toast's body lets taps through to the PDF - the '+N' button under the stack opens it. Three or fewer: unfolded again.
function syncToastStack(){const box=$('#toasts'),n=box.querySelectorAll('.toast').length; let m=$('#toasts-more');
  if(n<=3)box.classList.remove('expanded');
  if(!m){if(n<=3)return; m=document.createElement('button'); m.id='toasts-more'; m.type='button'; m.className='btn-sm t-more'; m.dataset.act='toasts-expand';}
  if(box.lastElementChild!==m)box.appendChild(m);   // after the toasts, so the newest-first order and nth-child stay as they are
  m.hidden=n<=3||box.classList.contains('expanded'); if(!m.hidden)m.textContent=tl('알림 {n}건 더 보기',{n:n-3});}
new MutationObserver(syncToastStack).observe($('#toasts'),{childList:true});
async function copyText(s){
  try{await navigator.clipboard.writeText(s);}catch(e){
    const ta=document.createElement('textarea');ta.value=s;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');}catch(e2){} ta.remove();}
  toast(tl('복사함: {text}',{text:s}),'ok');
}

