// ------------------------------------------------ Browser notifications (docs/handbook/viewer.md §브라우저 알림) - only while the tab is alive
// Turned on per device (pinPrefs.notify). Notification.requestPermission() is only ever called from the [알림 켜기] click. The server
// carries "events addressed to the current identity" in the 5-second poll (/api/meta?light=1&ev=<cursor>), and this tab shows them as
// notifications. The cursor (pinNotifyCursor) is kept in this browser's localStorage, so a reload or two tabs never announce the same
// event twice. Display always goes through the service worker's showNotification() (Chrome on Android blocks new Notification()); tag is
// the pin number, so the same pin collapses into one slot. If the tab is visible and focused, a toast is shown instead of a notification.
// This only works in a secure context (an https tailnet address, or http://127.0.0.1/localhost) - the browser blocks plain http on other hosts.
const NOTIFY_RANK={dropped:6,assigned:5,mention:4,reopened:3,review_requested:2,replied:1};
let SW_REG=null;
function notifySupported(){return !!(window.isSecureContext&&'serviceWorker' in navigator&&'Notification' in window);}
function notifyPerm(){return 'Notification' in window?Notification.permission:'unsupported';}
function notifyOn(){return !!prefs().notify&&notifySupported()&&notifyPerm()==='granted';}
function notifyCursor(){const v=parseInt(localStorage.getItem('pinNotifyCursor')||'',10); return isNaN(v)?null:v;}
function setNotifyCursor(v){const c=notifyCursor(); if(c==null||v>c)try{localStorage.setItem('pinNotifyCursor',String(v));}catch(e){}}
function notifyQuery(){if(!notifyOn())return ''; const c=notifyCursor(); return c==null?'':'&ev='+c;}
// Picks what to notify about (a pure function): after the cursor, addressed to me (to), not my own doing. One per pin - mention > reopen > awaiting review > reply, ties go to the later one.
function pickNotifications(evs,me,cursor){const login=me&&me.login; if(!login||login==='local')return [];
  const by=new Map();
  (evs||[]).forEach(e=>{if(!(e.seq>(cursor==null?-1:cursor)))return; if(!NOTIFY_RANK[e.type])return;
    if(!(e.to||[]).includes(login)||(e.by&&e.by.login===login))return;
    const o=by.get(e.pin); if(!o||NOTIFY_RANK[e.type]>NOTIFY_RANK[o.type]||(NOTIFY_RANK[e.type]===NOTIFY_RANK[o.type]&&e.seq>o.seq))by.set(e.pin,e);});
  return Array.from(by.values()).sort((a,b)=>a.seq-b.seq);}
function notifyText(e){const nm=who(e.by)||tr('누군가'),ex=String(e.excerpt||'').split('\n')[0].slice(0,80),q={name:nm,text:ex};
  const body={mention:tl('{name}님이 불렀습니다: {text}',q),review_requested:tl('검토 대기: {text}',{text:ex||tr('설명 없이 닫힘')}),
    replied:tl('{name}님 답글: {text}',q),reopened:ex?tl('{name}님이 다시 열었습니다: {text}',q):tl('{name}님이 다시 열었습니다',q),
    assigned:tl('{name}님이 담당으로 지정했습니다: {text}',q),dropped:tl('{name}님이 삭제했습니다: {text}',q)}[e.type]||ex;
  return {title:tl('핀 #{id}',{id:e.pin})+' · '+(e.doc_name||e.doc||(META&&META.label)||''),body};}
async function notifyShow(e){const t=notifyText(e);
  if(document.visibilityState==='visible'&&document.hasFocus()){
    const act=e.type==='dropped'?(isViewer()?{label:'열기',tip:'휴지통에서 봅니다',fn:()=>openPinFromLink(e.doc,e.pin)}:{label:'되살리기',tip:'휴지통에서 같은 번호로 되살립니다',fn:()=>restorePin(e.pin)})
      :{label:'열기',tip:'그 핀으로 갑니다',fn:()=>openPinFromLink(e.doc,e.pin)};
    toast(t.title+' — '+t.body,e.type==='dropped'?'warn':'ok',act,{keys:[e.type+':'+e.pin],rank:2});return;}
  try{const reg=SW_REG||await navigator.serviceWorker.ready;
    await reg.showNotification(t.title,{body:t.body,tag:'pin-'+e.pin,icon:(document.querySelector('link[rel=apple-touch-icon]')||document.querySelector('link[rel=icon]')||{}).href,
      actions:e.type==='dropped'&&!isViewer()?[{action:'restore',title:tr('되살리기')}]:[],   // [되살리기] on "X deleted your pin" (the service worker hands it to this tab)
      data:{pin:e.pin,doc:e.doc,url:'/#doc='+encodeURIComponent(e.doc||'')+'&pin='+e.pin}});}catch(err){}}
function notifyHandle(d){if(!d||typeof d.ev_seq!=='number')return;
  if(!notifyOn())return;
  const c=notifyCursor(); if(c==null){setNotifyCursor(d.ev_seq); return;}   // first time enabled in this browser - never floods with a backlog of past events
  if(!Array.isArray(d.events)){if(d.ev_seq<c)try{localStorage.setItem('pinNotifyCursor',String(d.ev_seq));}catch(e){}return;}
  const list=pickNotifications(d.events,META&&META.me,notifyCursor());   // only what's after it, if another tab just advanced the cursor
  const top=d.events.reduce((m,e)=>Math.max(m,e.seq||0),c); setNotifyCursor(top);
  list.forEach(notifyShow);}
async function notifyRegister(){if(!notifySupported())return null;
  try{SW_REG=await navigator.serviceWorker.register('/sw.js',{scope:'/'}); return SW_REG;}catch(e){return null;}}
// A local identity (no tailnet login) never gets events from the server's events_since() at all (§@태그·사람·이벤트), so
// notifications would never arrive - since getting browser permission wouldn't help, turning it on is blocked outright and the reason is shown.
function isLocalIdentity(){const me=META&&META.me; return !me||!me.login||me.login==='local';}
function notifyState(){if(isLocalIdentity())return 'local'; if(!notifySupported())return 'unsupported'; const pm=notifyPerm();
  if(pm==='denied')return 'blocked'; return prefs().notify&&pm==='granted'?'on':'off';}
function drawNotify(){const st=notifyState(),b=$('#btn-notify'),m=$('#m-notify');
  const lab={on:'알림: 켜짐',off:'알림: 꺼짐',blocked:'알림: 브라우저에서 차단됨',unsupported:'알림: 이 주소에서는 안 됨',local:'알림: 테일넷 주소에서만'}[st];
  const tip={on:'이 기기에서 켜져 있습니다. 누르면 끕니다',off:'누르면 이 기기에서 켭니다(브라우저가 허용을 묻습니다)',
    blocked:'브라우저가 이 사이트의 알림을 막았습니다. 주소창 왼쪽 자물쇠(사이트 설정) → 알림 → 허용으로 바꾼 뒤 다시 누르세요',
    unsupported:'브라우저 알림은 https(테일넷 주소)나 http://127.0.0.1·localhost 에서만 됩니다',
    local:'테일넷 주소로 열면 켤 수 있습니다'}[st];
  b.innerHTML=st==='on'?ic('bell'):ic('bell-off'); b.setAttribute('aria-label',tr('브라우저 '+lab)); b.setAttribute('aria-pressed',String(st==='on')); b.dataset.tip=lab+' — '+tip;
  b.disabled=st==='local'; m.disabled=st==='local';
  m.textContent=st==='on'?'알림 끄기 (켜짐)':st==='off'?'알림 켜기':lab; m.dataset.tip=tip;}
async function notifyToggle(){const st=notifyState();
  if(st==='local'){toast('테일넷 주소로 열면 켤 수 있습니다','warn'); return;}
  if(st==='on'){savePrefs({notify:false}); drawNotify(); syncHiddenNotifyTimer(); toast('이 기기의 브라우저 알림을 껐습니다','ok'); return;}
  if(st==='unsupported'){toast('브라우저 알림은 https 테일넷 주소나 http://127.0.0.1 에서만 됩니다','warn'); return;}
  if(st==='blocked'){toast('브라우저가 알림을 막았습니다 — 주소창 자물쇠 → 알림 → 허용으로 바꾼 뒤 다시 누르세요','warn'); return;}
  let pm=notifyPerm(); if(pm!=='granted'){try{pm=await Notification.requestPermission();}catch(e){pm='denied';}}   // only ever asked from within this click
  if(pm!=='granted'){drawNotify(); toast(pm==='denied'?'알림을 허용하지 않아 켜지 않았습니다':'알림 허용을 고르지 않았습니다','warn'); return;}
  await notifyRegister(); savePrefs({notify:true});
  try{const d=(await api(dq('/api/meta?light=1'),{silent:true})).data; if(notifyCursor()==null)setNotifyCursor(d.ev_seq);}catch(e){}
  drawNotify(); syncHiddenNotifyTimer(); toast('이 기기에서 브라우저 알림을 켰습니다 — 나를 부르거나 내 핀에 일이 생기면 알립니다','ok');}
// Clicking a notification (service worker -> postMessage, or a new tab's #doc=<key>&pin=<number>) switches to that document and opens that pin.
function hashPin(){const m=/(?:^#|[#&])pin=(\d{1,9})(?:&|$)/.exec(location.hash||''); return m?+m[1]:null;}
// Reads a one-shot pin link (#doc=<key>&pin=<n>[&act=restore]) and removes pin=/act= from the address right away, so a
// reload never repeats it (a reload of an &act=restore link restored a pin someone had deleted again - PR #11 review).
function takeLinkHash(){const link={pin:hashPin(),doc:hashDoc(),restore:/(?:^#|[#&])act=restore(?:&|$)/.test(location.hash||'')};
  if(link.pin)history.replaceState(history.state,'',location.pathname+location.search+(link.doc?'#doc='+link.doc:''));
  return link;}
// restore = the [되살리기] action of a 'dropped' notification: bring the pin back from the Trash first (never for a viewer).
async function openPinFromLink(doc,pin,restore){if(!pin)return; if(doc&&doc!==DOC&&docInfo(doc)){await switchDoc(doc); if(DOC!==doc)return;}
  await loadPins(); if(restore&&!isViewer()&&!findAnyPin(pin)&&DROPPED.some(x=>x.id===pin))await restorePin(pin);
  const p=findAnyPin(pin); if(!p){if(DROPPED.some(x=>x.id===pin))openTrash(pin); return;} if(pinState(p)==='done'){SEC.done=true;}
  OPEN_CARDS.add(pin); setSide(true); drawPins(); if(pinState(p)!=='done')jumpPin(pin);
  requestAnimationFrame(()=>jumpToCard(pin));}
if('serviceWorker' in navigator)navigator.serviceWorker.addEventListener('message',e=>{const d=e.data||{};
  if(d.type==='open-pin')openPinFromLink(d.doc,+d.pin); else if(d.type==='restore-pin'&&!isViewer())restorePin(+d.pin);});
window.addEventListener('hashchange',()=>{const l=takeLinkHash(); if(l.pin)openPinFromLink(l.doc,l.pin,l.restore);});

