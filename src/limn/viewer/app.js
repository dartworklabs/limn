
'use strict';
const $=s=>document.querySelector(s);
const $$=s=>Array.from(document.querySelectorAll(s));
// Lucide icons (vendor/lucide/README.md). Same shape as the server's icon_svg() - size is set by CSS (.ic).
const ICONS=__LUCIDE_JSON__;
function ic(n){const b=ICONS[n]; return b?'<svg class="ic ic-'+n+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'+b+'</svg>':'';}
const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const IS_MAC=/Mac|iPhone|iPad/i.test(navigator.platform||navigator.userAgent||'');
const SMOOTH=matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth';
const MQ=matchMedia('(prefers-color-scheme: light)');
let META=null,PINS=[],DONE=[],DROPPED=[],CUR=null,SAVING=false,ESAVING=false,EDIT=null,REPICK=null,PICKSEQ=0,PENDING=null,PICKING=false,PEND_SAVE=false;
let SNIP_OPEN=false,W=900,WRAP=true;
// Mobile: LAYOUT is 'wide'|'mid'|'narrow', SIDE_OPEN is whether the panel/sheet is expanded, SELMODE is touch selection mode,
// ZOOMED is whether the user changed the width via -/+ in compact (while true, it's never auto-fit to the screen width).
const MQ_COARSE=matchMedia('(pointer:coarse)');
// A device with no hover (phone/tablet): hover/focus tooltips are never shown at all - a tap sent a simulated mouseover and left the description stuck over the list (phone QA). Only long-press is used.
const MQ_NOHOVER=matchMedia('(hover:none)');
let OUTLINE_MID_OPEN=false,MID_OVERLAY=false;
let LAYOUT=null,SIDE_OPEN=true,SELMODE=false,ZOOMED=false,LAST_PTR='mouse',LAST_TOUCH_T=0;
const OPEN_CARDS=new Set();   // ids of pin cards expanded in compact
// Pin kind/thread (docs/handbook/viewer.md §스레드와 검토): KIND_NEW = the composer panel's kind (fix|question), REPLY = the open reply/reopen
// input field {id,mode,el} (holds onto the DOM like EDIT does, and re-inserts it in place when the list redraws), THREAD_OPEN = cards with the thread fully expanded,
// REPLY_DRAFT = a closed input field's draft text ('reply:12').
let KIND_NEW='fix',REPLY=null;
// @-tags (docs/handbook/viewer.md §@태그): PEOPLE = /api/people (tailnet people who opened this viewer + pin authors/actors), MENTION_ONLY = viewing only "pins that called me".
let PEOPLE=[],MENTION_ONLY=false;
const THREAD_OPEN=new Set(),REPLY_DRAFT=new Map();
// Multiple documents (§Multiple documents, docs/handbook/domain.md §여러 문서): DOCS = the /api/docs list, DOC = the current document key, DEFAULT_DOC = the first
// document that a legacy pin with no doc field belongs to. OPEN_ALL = open pins across all documents (PINS is the subset for the current document - marks/overlap/editing only look at PINS).
// META_BY = per-document meta cache (instant tab switching), VIEW_BY = per-document viewed position/zoom, BUILD_ERR_BY = per-document last build error,
// DOC_SEQ = another document's finished-build count (used to notice a build that finished in the background).
let DOCS=[],DOC=null,DEFAULT_DOC='main',OPEN_ALL=[],DONE_ALL=[],SHOW_ALL=false,SWITCHSEQ=0;
// Awaiting review (a pin closed by an agent, waiting for a person's [확인], state==='review'). Never put into DONE_ALL - drawn separately from the done archive.
let REVIEW_ALL=[];
const META_BY=new Map(),VIEW_BY=new Map(),BUILD_ERR_BY=new Map(),DOC_SEQ=new Map();
window.__pinViewerBoot=Date.now();   // a marker for checking reload status from outside

const T={
  stale:'핀을 찍은 첫 문장이 바뀌거나 지워져 위치를 되찾지 못했습니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
  n:"누르면 PDF에서 이 핀 자리로 갑니다. 에이전트에게는 '#2 처리해줘'처럼 번호로 부르세요. 번호는 다시 쓰이지 않습니다",
  loc:'핀이 가리키는 원문 줄. 클릭하면 복사',
  view:'PDF에서 이 핀 자리로 가서 깜빡입니다', edit:'메모와 범위를 고칩니다. 번호는 그대로입니다',
  close:"처리됨으로 표시해 목록과 pins.md에서 뺍니다. 아래 '닫힌 핀'에서 되돌릴 수 있습니다",
  drop:'핀을 휴지통으로 보냅니다. 알림의 [되돌리기]나 휴지통에서 같은 번호 그대로 되살릴 수 있습니다(30일 보관)',
  repick:'번호와 메모는 그대로 두고 PDF에서 새 위치를 드래그해 바꿉니다 (Esc 취소)',
  esave:'수정한 내용을 저장합니다 (⌘ Enter / Ctrl+Enter)', ecancel:'수정을 버립니다 (Esc)',
  restore:'삭제한 핀을 같은 번호로 되살려 열린 핀에 올립니다',
  purge:'휴지통에서 영구 삭제합니다(소유자만). 알림이 떠 있는 동안 [되돌리기]로 취소할 수 있고, 알림이 사라지면 지웁니다',
  synctex:'PDF 좌표(SyncTeX)로 줄을 찾았지만 드래그한 글자가 이 줄 범위에 다 있지는 않습니다(드문 낱말에 가중한 비율). 원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.',
  text:'드래그한 글자를 원문에서 직접 찾아 위치를 정했습니다(표·기호표처럼 좌표 조회가 약한 곳). 원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.',
  raw:'넓히기 전에 드래그 영역이 직접 가리킨 줄만 잡습니다',
  para:'드래그한 자리를 감싸는 문단 전체입니다(앞뒤 % 주석 줄은 뺍니다)',
  env:'감싸는 \\begin{…}…\\end{…} 블록 전체입니다. (바깥)은 한 단계 더 바깥 블록입니다',
  cur:'지금 핀이 가리키는 범위 그대로입니다',
  undo:'방금 한 저장·완료·삭제를 되돌립니다',
  question:'고칠 곳이 아니라 묻는 핀입니다. 답은 아래 스레드에 달리고, 원고는 질문이 수정을 뜻할 때만 고칩니다',
  review:'에이전트가 닫은 핀입니다. 사람이 결과를 보고 [확인]하면 완료로 가고, [답글]에 틀린 점을 쓰면 다시 열려 에이전트가 고칩니다',
  confirm:'결과를 확인했다고 기록하고 완료로 옮깁니다. 작성자에게 권하지만 누구나 누를 수 있고, 누른 사람이 기록됩니다',
  change:'변경사항 탭을 열어 이 핀을 고친 커밋(닫을 때 남긴 참조, 없으면 이 줄을 바꾼 최근 커밋)의 diff 에서 핀 자리를 강조합니다',
  reply:'이 핀에 답글을 답니다. 닫힌 핀이면 보내기 전에 칸 아래 한 줄이 결과(다시 열림·알림·그대로)를 알려 줍니다 (⌘ Enter / Ctrl+Enter 보내기)'
};

// ------------------------------------------------ Preferences (merged save)
// UI language (window.LIMN_LANG from the head script). Korean strings in this file are the source; in English
// mode tr()/trMsg() look them up in I18N_EN (src/limn/ui_en.json) and a MutationObserver translates text
// nodes and UI attributes as they are rendered. Strings missing from the table stay Korean.
const LANG=window.LIMN_LANG==='en'?'en':'ko', I18N_EN=__UI_EN_JSON__, I18N_ATTRS=['data-tip','aria-label','title','placeholder'];
function tr(s){if(LANG!=='en'||typeof s!=='string')return s; const t=s.trim();
  if(!t||!Object.prototype.hasOwnProperty.call(I18N_EN,t)||typeof I18N_EN[t]!=='string')return s; return s.replace(t,I18N_EN[t]);}
// Composed UI strings: tl('{n}쪽',{n:3}). The Korean key is the template and the Korean output; in English the
// table value is the template - a string, or plural forms {"one":...,"other":...} picked by p.n. {x} placeholders
// are filled from p (values are inserted as given - escape them first if the result goes into HTML).
function tl(k,p){let s=k; if(LANG==='en'&&Object.prototype.hasOwnProperty.call(I18N_EN,k)){const v=I18N_EN[k];
    s=typeof v==='string'?v:(v&&(Number(p&&p.n)===1&&v.one?v.one:v.other))||k;}
  return s.replace(/\{(\w+)\}/g,(m,x)=>p&&p[x]!=null?String(p[x]):m);}
function trMsg(s){if(LANG!=='en'||typeof s!=='string')return s; const e=tr(s); if(e!==s)return e;
  for(const sep of [' — ',' · ']){if(s.indexOf(sep)>0)return s.split(sep).map(tr).join(sep);} return s;}
// An API error body {error, reason} as the UI shows it (docs/handbook/viewer.md §뷰어 규칙을 바꿀 때). Korean shows the
// server's `error` text as is - it is the agent contract (api.md §오류 응답). English looks up the stable reason code
// ('reason:<code>' in the table) and falls back to the server text through the table. '' when there is no body.
function errText(d){if(!d)return ''; const s=d.error==null?'':String(d.error);
  if(LANG==='en'&&typeof d.reason==='string'){const v=I18N_EN['reason:'+d.reason]; if(typeof v==='string')return v;}
  return trMsg(s);}
// The pick's `warn` (a Korean UI hint, not an error body) is up to three sentences the server joins with a space, some
// with numbers. Each Korean template here matches one server sentence ({x} = the number); English fills the table's
// template through tl(). Korean shows the server text as is; a sentence no template matches stays as it is.
const PICK_WARNS=['이 영역은 원문 대조가 약합니다({pct}%). 줄 범위를 눈으로 확인하세요.','두 경로가 다른 곳을 가리킵니다(L{a} / L{b}). 확인이 필요합니다.',
  '화면의 PDF 가 지금 원고보다 낡았습니다 — [PDF 재빌드] 뒤에 다시 고르세요.','빌드 중이라 결과가 흔들릴 수 있습니다.',
  '이 영역에는 글자가 없습니다(그림·스캔본). 메모에 무엇을 가리키는지 적어 주세요.','PDF 가 바뀌어 쪽을 다시 그리는 중입니다 — 끝나면 다시 고르세요.'];
function warnText(s){s=s==null?'':String(s); if(LANG!=='en'||!s)return s;
  for(const k of PICK_WARNS){const names=[],lit=k.split(/\{(\w+)\}/).filter((p,i)=>i%2===0||!names.push(p));
    const re=new RegExp(lit.map(p=>p.replace(/[.*+?^$()|[\]\\{}]/g,'\\$&')).join('(\\d+)'),'g');
    s=s.replace(re,(...m)=>tl(k,Object.fromEntries(names.map((n,i)=>[n,m[i+1]]))));}
  return s;}
function i18nEl(el){for(const a of I18N_ATTRS){const v=el.getAttribute(a); if(v){const e=trMsg(v); if(e!==v)el.setAttribute(a,e);}}}
function i18nText(n){const p=n.parentNode; if(!p||/^(TEXTAREA|SCRIPT|STYLE)$/.test(p.nodeName))return;
  const e=trMsg(n.nodeValue); if(e!==n.nodeValue)n.nodeValue=e;}
function i18nTree(root){if(LANG!=='en'||!root)return;
  if(root.nodeType===3)return i18nText(root);
  if(root.nodeType!==1)return; i18nEl(root);
  const w=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT); let n;
  while((n=w.nextNode())){if(n.nodeType===3)i18nText(n); else i18nEl(n);}}
function i18nStart(){const b=document.getElementById('m-lang'); if(b)b.textContent=LANG==='en'?'한국어':'English';
  if(LANG!=='en')return; i18nTree(document.body);
  new MutationObserver(ms=>{for(const m of ms){
    if(m.type==='childList')m.addedNodes.forEach(i18nTree);
    else if(m.type==='characterData')i18nText(m.target);
    else if(m.type==='attributes'&&m.target.nodeType===1){const v=m.target.getAttribute(m.attributeName);
      if(v){const e=trMsg(v); if(e!==v)m.target.setAttribute(m.attributeName,e);}}}})
    .observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:I18N_ATTRS});}
function switchLang(){try{localStorage.setItem('limnLang',LANG==='en'?'ko':'en');}catch(e){}
  const u=new URL(location.href); u.searchParams.delete('lang'); location.replace(u.toString());}
function prefs(){try{const p=JSON.parse(localStorage.getItem('pinPrefs')||'{}');return p&&typeof p==='object'?p:{};}catch(e){return {};}}
function savePrefs(patch){try{localStorage.setItem('pinPrefs',JSON.stringify(Object.assign(prefs(),patch)));}catch(e){}}
(function(){const p=prefs(); if(p.side)$('#right').style.width=p.side+'px'; if(p.w)W=p.w; if(p.wrap!==undefined)WRAP=!!p.wrap;})();
// List sections (docs/handbook/viewer.md §목록 구획): expanded/collapsed per section, remembered in pinPrefs.sec. Defaults: open pins and
// awaiting review expanded, done collapsed. SEC_SEEN holds, per section, the ids known at the first load plus everything the section
// held while expanded - while collapsed, a listed id not in it is counted as 'new N' on the header.
const SEC_DEFAULT={open:true,review:true,done:false};
function secState(saved){const o=Object.assign({},SEC_DEFAULT); if(saved&&typeof saved==='object')for(const k in SEC_DEFAULT)if(typeof saved[k]==='boolean')o[k]=saved[k]; return o;}
function secNewCount(seen,ids){if(!seen)return 0; return ids.filter(id=>!seen.has(id)).length;}
let SEC=secState(prefs().sec);
const SEC_SEEN={open:null,review:null,done:null};

const THEMES=['system','light','dark'],THEME_ICON={system:'sun-moon',light:'sun',dark:'moon'},THEME_NAME={system:'시스템',light:'밝게',dark:'어둡게'};
function applyTheme(){let t=prefs().theme||'light'; if(!THEME_ICON[t])t='light';
  const eff=t==='system'?(MQ.matches?'light':'dark'):(t==='light'?'light':'dark');
  document.documentElement.setAttribute('data-theme',eff); const b=$('#btn-theme'); b.innerHTML=ic(THEME_ICON[t]);
  const nm=tr(THEME_NAME[t]); b.setAttribute('aria-label',tl('화면 테마: {name}',{name:nm}));
  b.dataset.tip=tl('화면 테마: 지금 {name}. 누르면 시스템 따름 → 밝게 → 어둡게 순으로 바뀝니다. PDF 종이 색은 그대로입니다',{name:nm});
  const m=$('#m-theme'); if(m)m.textContent=tl('테마: {name}',{name:nm});}
MQ.addEventListener('change',applyTheme);
function cycleTheme(){const t=prefs().theme||'light';savePrefs({theme:THEMES[(THEMES.indexOf(t)+1)%3]});applyTheme();}

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
  placeToasts(); box.insertBefore(t,box.firstChild); arm(); while(box.children.length>6){const l=box.lastChild; l.remove(); toastGone(l);}
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
  else{const open=LAYOUT==='wide'||SIDE_OPEN,rr=right.getBoundingClientRect();
    if(open&&rr.width>0){r=Math.max(gap,innerWidth-rr.right+12); w=Math.min(380,rr.width-24);} else w=Math.min(360,innerWidth-24);
    ['#c-actions'].concat(LAYOUT==='mid'?['#bar1']:[],LAYOUT==='mid'&&!open?['#bar2','#banner']:[]).forEach(s=>{const e=$(s);
      if(shown(e))top=Math.min(top,e.getBoundingClientRect().top);});}
  R.setProperty('--toast-b',Math.max(gap,Math.round(vh-top+gap))+'px'); R.setProperty('--toast-r',Math.round(r)+'px'); R.setProperty('--toast-w',Math.round(Math.max(200,w))+'px');}
let TOAST_WATCH=0;
function watchToasts(){if(TOAST_WATCH)return; TOAST_WATCH=setInterval(()=>{if(!$('#toasts').children.length){clearInterval(TOAST_WATCH);TOAST_WATCH=0;return;} placeToasts();},250);}
async function copyText(s){
  try{await navigator.clipboard.writeText(s);}catch(e){
    const ta=document.createElement('textarea');ta.value=s;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');}catch(e2){} ta.remove();}
  toast(tl('복사함: {text}',{text:s}),'ok');
}

// ------------------------------------------------ Tooltip
const TIP=$('#tip'); let tipT=null,tipEl=null,TIPXY=null;
document.addEventListener('mousemove',e=>{TIPXY=[e.clientX,e.clientY];},{passive:true});
function hideTip(){clearTimeout(tipT);tipT=null;tipEl=null;TIP.hidden=true;}
function showTip(el){const txt=el.dataset.tip; if(!txt||!document.contains(el))return;
  TIP.textContent=txt; TIP.hidden=false;
  const r=el.getBoundingClientRect(),tw=TIP.offsetWidth,th=TIP.offsetHeight;
  let top=r.top-th-8, cx=r.left+r.width/2;
  if(top<4) top=r.bottom+8;
  if(top>innerHeight-th-4 && TIPXY){top=TIPXY[1]+18; cx=TIPXY[0];}   // an element taller than the window (#grip/a long card) anchors to the pointer instead
  top=Math.max(4,Math.min(top,innerHeight-th-4));
  const left=Math.min(Math.max(4,cx-tw/2),innerWidth-tw-4);
  TIP.style.left=left+'px'; TIP.style.top=top+'px';}
function armTip(el){if(el===tipEl)return; hideTip(); if(!el)return; tipEl=el; tipT=setTimeout(()=>showTip(el),300);}
// Hover/focus tooltips are never shown right after a touch - mobile Chrome simulates mouseover/focusin on every tap, so a
// description used to pop up every time a button was pressed. Touch relies on long-press instead (below).
const touchRecent=()=>Date.now()-LAST_TOUCH_T<1500;
document.addEventListener('pointerdown',e=>{LAST_PTR=e.pointerType||'mouse'; if(LAST_PTR!=='mouse')LAST_TOUCH_T=Date.now();},true);
document.addEventListener('mouseover',e=>{if(touchRecent()||MQ_NOHOVER.matches)return; armTip(e.target.closest?e.target.closest('[data-tip]'):null);});
// A focus tooltip is never shown on an input field (textarea) - it covered the snippet while typing, and the tooltip
// swallowed the first Esc, so "Esc to cancel -> Ctrl+Enter" ended up saving a pin that was meant to be discarded (observed).
document.addEventListener('focusin',e=>{const t=e.target;
  if((t&&t.tagName==='TEXTAREA')||touchRecent()||MQ_NOHOVER.matches){if(Date.now()>=SWALLOW_CLICK)hideTip();return;}
  armTip(t.closest?t.closest('[data-tip]'):null);});
// Long-press tooltip (touch/pen): holding for 500ms shows the description, and the one click after release is swallowed (so the button doesn't fire).
// Over a page image, quick selection (long-press = that paragraph) takes priority, so only badges (.mark b) apply. Input fields keep their paste menu.
let PRESS=null,SWALLOW_CLICK=0;
function pressTarget(t){const el=t&&t.closest?t.closest('[data-tip]'):null; if(!el)return null;
  if(el.tagName==='TEXTAREA'||el.tagName==='INPUT')return null;
  if(el.closest('.pg')&&!el.closest('.mark b'))return null; return el;}
document.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse')return; if(!TIP.hidden)hideTip();
  const el=pressTarget(e.target); if(!el)return;
  PRESS={el,x:e.clientX,y:e.clientY,t:setTimeout(()=>{showTip(el); PRESS.shown=true; SWALLOW_CLICK=Date.now()+900;
    setTimeout(()=>{if(!TIP.hidden&&TIP.textContent===el.dataset.tip)hideTip();},4000);},500)};},true);
function endPress(){if(PRESS){clearTimeout(PRESS.t); PRESS=null;}}
document.addEventListener('pointermove',e=>{if(PRESS&&Math.hypot(e.clientX-PRESS.x,e.clientY-PRESS.y)>10)endPress();},true);
document.addEventListener('pointerup',endPress,true);
document.addEventListener('pointercancel',endPress,true);
document.addEventListener('click',e=>{if(Date.now()<SWALLOW_CLICK){SWALLOW_CLICK=0;e.preventDefault();e.stopImmediatePropagation();}},true);
document.addEventListener('contextmenu',e=>{if(LAST_PTR==='mouse')return; const t=e.target;
  if(t&&t.closest&&(t.closest('.pg')||pressTarget(t)))e.preventDefault();});
document.addEventListener('input',hideTip,true);
document.addEventListener('focusout',hideTip);
document.addEventListener('scroll',hideTip,true);
// Releasing right after a long-press opens it, Chrome sends a simulated mousedown - that alone must never close it.
document.addEventListener('mousedown',()=>{if(Date.now()>=SWALLOW_CLICK)hideTip();},true);

// ------------------------------------------------ Multiple documents - list/tabs/switching (docs/handbook/domain.md §여러 문서)
function multiDoc(){return DOCS.length>1;}
function docInfo(k){return DOCS.find(d=>d.key===k)||null;}
function pdoc(p){return (p&&p.doc)||DEFAULT_DOC;}
function isRegion(p){return !!p&&(p.kind==='region'||(!p.file&&!!p.pdf));}
// Appends ?doc=<key> to a document-scoped path (the server treats it as the first document if absent).
function dq(u,k){k=k||DOC; if(!k)return u; return u+(u.indexOf('?')<0?'?':'&')+'doc='+encodeURIComponent(k);}
function hashDoc(){const m=/(?:^#|[#&])doc=([a-z0-9-]{1,24})(?:&|$)/.exec(location.hash||''); return m?m[1]:null;}
function setHash(k){if(!multiDoc())return; const h='#doc='+k; if(location.hash!==h)history.replaceState(null,'',location.pathname+location.search+h);}
// The document shown first: URL hash (link sharing/reload) > the last document viewed on this device > the first document.
function initialDoc(){const h=hashDoc(); if(h&&docInfo(h))return h; const l=prefs().lastDoc; if(l&&docInfo(l))return l;
  return DOCS.length?DOCS[0].key:null;}
async function loadDocs(){try{const r=(await api('/api/docs',{what:'문서 목록',silent:true})).data;
    DOCS=Array.isArray(r.docs)?r.docs:[]; DEFAULT_DOC=r.default||(DOCS[0]&&DOCS[0].key)||'main';}catch(e){DOCS=[];}
  document.body.classList.toggle('docs-multi',multiDoc()); $('#all-docs').hidden=!multiDoc();}
function docCount(k){return OPEN_ALL.filter(p=>pdoc(p)===k).length;}
function docBadge(d){const n=docCount(d.key);
  return (d.building?'<span class="spin" aria-label="빌드 중"></span>':(d.stale_build?'<span class="ddot" aria-label="원고 수정됨"></span>':''))+
    (d.view_only?'<span class="badge dvo" aria-label="보기 전용">PDF</span>':'')+'<span class="badge badge-secondary dcnt'+(n?'':' z')+'" aria-label="'+esc(tl('열린 핀 {n}',{n}))+'">'+n+'</span>';}
function docTip(d){return d.name+' · '+d.path+(d.view_only?' · 보기 전용 PDF(줄 번호 없이 쪽·영역으로 핀을 남깁니다)':'')+
  (d.building?' · 빌드 중':(d.stale_build?' · 원고가 이 PDF보다 새롭습니다(그 탭에서 [PDF 재빌드])':''));}
function drawDocTabs(){
  const box=$('#doc-select');
  box.innerHTML=DOCS.map(d=>'<option value="'+esc(d.key)+'">'+esc(d.name)+(d.building?' · 빌드 중':d.stale_build?' · 원고 수정됨':'')+'</option>').join('');
  if(DOC)box.value=DOC;
  $('#doc-links').innerHTML=DOCS.map(d=>'<button data-act="doc" data-doc="'+esc(d.key)+'" aria-current="'+(d.key===DOC?'page':'false')+'" title="'+esc(docTip(d))+'">'+esc(d.name)+(d.n_pages?'<span class="doc-link-count">'+tl('{n}쪽',{n:d.n_pages})+'</span>':'')+'</button>').join('');
  const cur=docInfo(DOC); $('#btn-doc-n').textContent=cur?cur.name:tr('문서');
  $('#btn-doc-dot').hidden=!DOCS.some(d=>d.key!==DOC&&(d.stale_build||d.building));
  if(DOC!==DOC_LINK_SHOWN){DOC_LINK_SHOWN=DOC; docLinksReveal();} else docLinksFade();
  if($('#docs-menu').open)drawDocsMenu();}
// When the document-links row overflows (e.g. 5 documents in mid): the overflowing edge is faded (fade-l/fade-r) to show there's more,
// and when the document changes, the current document's link is scrolled into view. A polling redraw never touches wherever the user has scrolled to (only a document change does).
let DOC_LINK_SHOWN=null;
function docLinksFade(){const d=$('#doc-links'); if(!d)return; const over=d.scrollWidth-d.clientWidth;
  d.classList.toggle('fade-l',over>1&&d.scrollLeft>1); d.classList.toggle('fade-r',over>1&&over-d.scrollLeft>1);}
function docLinksReveal(){const d=$('#doc-links'),a=d&&d.querySelector('[aria-current=page]');
  if(a&&d.scrollWidth>d.clientWidth){const dr=d.getBoundingClientRect(),ar=a.getBoundingClientRect(),pad=40;
    if(ar.left<dr.left+pad)d.scrollLeft-=dr.left+pad-ar.left; else if(ar.right>dr.right-pad)d.scrollLeft+=ar.right-(dr.right-pad);}
  docLinksFade();}
$('#doc-links').addEventListener('scroll',docLinksFade,{passive:true});
if(window.ResizeObserver)new ResizeObserver(()=>docLinksReveal()).observe($('#doc-links'));
let REVISION_SEQ=0,REVISION_FILES=[],REVISION_WHOLE='',REVISION_COMMIT='',REVISION_SOURCE_COMMIT='',REVISION_FORMAT='pdf';
// v0.3 (docs/handbook/viewer.md §변경 보기): a pin's view of a commit. REVISION_SCOPE is the source diff's scope object
// ({mode:'pin'|'commit', source, hunks, other, ...}); REV_PDF holds the comparison PDF's toggle - whole commit or only this pin.
let REVISION_SCOPE=null,REVISION_OTHER='';
const REV_SCOPE={whole:false,partial:false,fallback:false};
const REV_PDF={doc:null,loading:null,observer:null,tasks:new Set()};
function revisionFiles(patch){
  const starts=[];const re=/^diff --git .+$/gm;let m;
  while((m=re.exec(patch))!==null)starts.push({at:m.index,head:m[0]});
  return starts.map((s,i)=>{const n=s.head.lastIndexOf(' b/');return {
    name:n>=0?s.head.slice(n+3):tl('파일 {n}',{n:i+1}),text:patch.slice(s.at,i+1<starts.length?starts[i+1].at:undefined)};});
}
// Source diff wrapping: on by default for touch devices (a manuscript where a paragraph is one line was 6,273px wide on a phone, QA). The on/off value is stored in pinPrefs.diffWrap.
let DIFF_WRAP=null;
function setDiffWrap(on){DIFF_WRAP=!!on; savePrefs({diffWrap:DIFF_WRAP}); for(const d of [$('#revision-diff'),$('#revision-other')])if(d)d.className=DIFF_WRAP?'wrap':'nowrap';
  const b=$('#revision-wrap'); if(b)b.setAttribute('aria-pressed',String(DIFF_WRAP));}
function initDiffWrap(){const v=prefs().diffWrap; setDiffWrap(typeof v==='boolean'?v:MQ_COARSE.matches);}
function renderRevisionDiff(patch){
  const lines=String(patch||'').split('\n'); if(lines[lines.length-1]==='')lines.pop();
  let oldLine=null,newLine=null,inHunk=false;
  return lines.map(line=>{
    let kind='meta',number='';
    if(line.startsWith('diff --git ')){kind='file';inHunk=false;oldLine=newLine=null;}
    else if(line.startsWith('@@ ')){
      kind='hunk';inHunk=true;
      const at=/^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);
      oldLine=at?Number(at[1]):null;newLine=at?Number(at[2]):null;
    }
    else if(!inHunk&&(line.startsWith('--- ')||line.startsWith('+++ '))){kind='meta';}
    else if(line.startsWith('+')){kind='add';if(newLine!==null)number=newLine++;}
    else if(line.startsWith('-')){kind='del';if(oldLine!==null)number=oldLine++;}
    else if(line.startsWith(' ')){kind='context';if(newLine!==null){number=newLine++;oldLine++;}}
    return '<span class="rd-line rd-'+kind+'"><span class="rd-no" aria-hidden="true">'+number+'</span><span class="rd-code">'+esc(line)+'</span></span>';
  }).join('');
}
function renderRevisionFile(){const v=$('#revision-file').value,i=Number(v);
  $('#revision-diff').innerHTML=renderRevisionDiff(v==='all'?REVISION_WHOLE:(REVISION_FILES[i]&&REVISION_FILES[i].text)||REVISION_WHOLE);}
// The rest of the commit, folded under one control (v0.3). Hidden when the pin owns the whole commit or the view is not a pin's.
function drawRevisionOther(sc){const b=$('#revision-other-toggle'),o=$('#revision-other');
  o.hidden=true;o.innerHTML='';b.setAttribute('aria-expanded','false');
  REVISION_OTHER=sc&&sc.mode==='pin'?String(sc.other_diff||'')+(sc.other_truncated?'\n\n'+tr('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.'):''):'';
  b.hidden=!REVISION_OTHER;if(REVISION_OTHER)b.querySelector('span').textContent=tl('이 커밋의 다른 변경 {n}곳',{n:sc.other});}
function toggleRevisionOther(){const b=$('#revision-other-toggle'),o=$('#revision-other'),open=b.getAttribute('aria-expanded')!=='true';
  b.setAttribute('aria-expanded',String(open));o.hidden=!open;
  if(open&&!o.innerHTML)o.innerHTML=renderRevisionDiff(REVISION_OTHER);}
// [커밋 전체 비교]: shown only for the PDF of a pin that owns part of the commit, and not after a fallback (there is nothing to switch to).
function syncRevisionWhole(){const b=$('#revision-whole');
  b.hidden=!(REVISION_FORMAT==='pdf'&&revisionPinFor(REVISION_COMMIT)&&REV_SCOPE.partial&&!REV_SCOPE.fallback);
  b.setAttribute('aria-pressed',String(REV_SCOPE.whole));}
// The pin whose hunks a commit's view is scoped to: only the commit picked for the pin ([변경 보기]); any other commit
// chosen in the list is shown whole (review M1 - another commit's lines are not this pin's).
function revisionPinFor(id){const tg=REV_TARGET; return tg&&!tg.region&&tg.commit&&id===tg.commit?tg:null;}
function setRevisionWhole(on){REV_SCOPE.whole=!!on;++REVISION_SEQ;REVISION_PDF_COMMIT='';
  clearRevisionPdf();$('#revision-warning').hidden=true;setRevisionFormat('pdf');}
function revisionCurrent(seq,k,id){return seq===REVISION_SEQ&&k===DOC&&id===REVISION_COMMIT&&document.body.classList.contains('revision-open');}
function clearRevisionPdf(){
  if(REV_PDF.observer){REV_PDF.observer.disconnect();REV_PDF.observer=null;}
  REV_PDF.tasks.forEach(t=>{try{t.cancel();}catch(e){}});REV_PDF.tasks.clear();
  if(REV_PDF.loading){try{REV_PDF.loading.destroy();}catch(e){}REV_PDF.loading=null;}
  REV_PDF.doc=null;$('#revision-pdf').replaceChildren();
}
function setRevisionFormat(format){REVISION_FORMAT=format==='source'?'source':'pdf';
  $('#revision-pdf-tab').setAttribute('aria-pressed',String(REVISION_FORMAT==='pdf'));
  $('#revision-source-tab').setAttribute('aria-pressed',String(REVISION_FORMAT==='source'));
  $('#revision-pdf').hidden=REVISION_FORMAT!=='pdf';$('#revision-source').hidden=REVISION_FORMAT!=='source';
  if(REVISION_FORMAT==='source'&&REVISION_COMMIT&&REVISION_SOURCE_COMMIT!==REVISION_COMMIT)
    loadRevisionSource(REVISION_COMMIT,REVISION_SEQ,DOC);
  // The comparison PDF is only built when that format is actually viewed - [변경 보기] goes straight to the source diff, so it never wastes a latexdiff build.
  if(REVISION_FORMAT==='pdf'&&REVISION_COMMIT&&REVISION_PDF_COMMIT!==REVISION_COMMIT){REVISION_PDF_COMMIT=REVISION_COMMIT;
    $('#revision-status').textContent='비교 PDF 상태를 확인하는 중입니다.'; loadRevisionPdf(REVISION_COMMIT,REVISION_SEQ,DOC);}
  syncRevisionWhole();
  if(REV_TARGET)revTargetNote();
}
function setViewMode(mode){
  const revisions=mode==='revisions'; document.body.classList.toggle('revision-open',revisions);
  $('#view-manuscript').setAttribute('aria-pressed',String(!revisions));
  $('#view-revisions').setAttribute('aria-pressed',String(revisions));
  if(!revisions)REV_TARGET=null;
  if(revisions)loadRevisions(); else{++REVISION_SEQ;clearRevisionPdf();$('#revision-pin').hidden=true;if(VEC.doc)vecSchedule(0);updateSectionStrip();}
}
async function loadRevisions(){
  const seq=++REVISION_SEQ,k=DOC,list=$('#revision-list'),out=$('#revision-diff'),tg=REV_TARGET;
  clearRevisionPdf();list.textContent='최근 변경사항을 읽는 중입니다.';out.textContent='';$('#revision-pin').hidden=!tg;
  if(tg)revTargetNote('변경사항을 읽는 중입니다.');
  let data; try{data=(await api(dq('/api/revisions',k),{what:'변경사항 읽기',silent:true})).data;}
  catch(e){if(seq===REVISION_SEQ)list.textContent='변경사항을 읽지 못했습니다.';return;}
  if(seq!==REVISION_SEQ||k!==DOC)return;
  if(!data.available){list.textContent='이 문서의 Git 변경사항을 볼 수 없습니다.';
    if(tg)revTargetNote(tg.region?'보기 전용 PDF 문서의 핀이라 Git 변경사항이 없습니다 — 고친 곳은 LaTeX 문서(본문 등)의 변경사항에서 찾으세요.':
      '이 문서는 Git 이력을 읽을 수 없어(Git 저장소가 아니거나 경로가 밖) 핀 자리를 변경과 맞출 수 없습니다.'); return;}
  if(!data.revisions.length){list.textContent='이 문서의 최근 변경사항이 없습니다.'; if(tg)revTargetNote('이 문서의 최근 12개 커밋에 변경이 없습니다.'); return;}
  list.innerHTML='<label class="sr-only" for="revision-select">비교할 커밋</label><select id="revision-select" aria-label="비교할 커밋">'+data.revisions.map(r=>'<option value="'+esc(r.id)+'">'+esc(r.subject)+' · '+esc(r.date)+' · '+esc(r.id.slice(0,8))+'</option>').join('')+'</select>';
  if(tg){const pick=await pickRevisionFor(tg,data.revisions,seq,k); if(seq!==REVISION_SEQ||k!==DOC||REV_TARGET!==tg)return;
    tg.commit=pick.id; tg.via=pick.via; tg.hit=pick.hit; showRevision(pick.id,'source'); return;}
  showRevision(data.revisions.some(r=>r.id===REVISION_COMMIT)?REVISION_COMMIT:data.revisions[0].id);
}
async function showRevision(id,format){
  const seq=++REVISION_SEQ,k=DOC;REVISION_COMMIT=id;REVISION_SOURCE_COMMIT='';REVISION_PDF_COMMIT='';clearRevisionPdf();
  const select=$('#revision-select');if(select)select.value=id;
  REVISION_SCOPE=null;REV_SCOPE.whole=REV_SCOPE.partial=REV_SCOPE.fallback=false;drawRevisionOther(null);
  $('#revision-diff').textContent='';$('#revision-file-row').hidden=true;$('#revision-warning').hidden=true;
  $('#revision-status').textContent='';
  setRevisionFormat(format||'pdf');
}
async function loadRevisionSource(id,seq,k){
  const out=$('#revision-diff');out.textContent='소스 변경 내용을 읽는 중입니다.';$('#revision-file-row').hidden=true;
  const tg0=revisionPinFor(id),pq=tg0?'&pin='+tg0.id:'';
  try{const r=(await api(dq('/api/revision-diff?commit='+encodeURIComponent(id)+pq,k),{what:'변경 내용 읽기',silent:true})).data;
    if(!revisionCurrent(seq,k,id))return;
    // v0.3: a pin's own hunks when it owns part of the commit; otherwise the whole commit exactly as before
    const sc=r.scope&&r.scope.mode==='pin'?r.scope:null;REVISION_SCOPE=r.scope||null;
    if(sc){REV_SCOPE.partial=true;syncRevisionWhole();}
    const cut='\n\n'+tr('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.');
    REVISION_WHOLE=sc?sc.diff+(sc.truncated?cut:''):(r.diff||tr('이 커밋에서 표시할 원고 텍스트 변경이 없습니다.'))+(r.truncated?cut:'');
    REVISION_FILES=revisionFiles(sc?sc.diff:(r.diff||''));drawRevisionOther(sc);
    const select=$('#revision-file');select.innerHTML='<option value="all">전체 파일</option>'+REVISION_FILES.map((f,i)=>'<option value="'+i+'">'+esc(f.name)+'</option>').join('');
    select.value='all';$('#revision-file-row').hidden=REVISION_FILES.length<2;REVISION_SOURCE_COMMIT=id;
    const tg=REV_TARGET,fi=tg?pinFileIndex(REVISION_FILES,tg.file):-1;
    if(fi>=0&&REVISION_FILES.length>1)select.value=String(fi);
    renderRevisionFile(); if(tg)revHighlight(tg);
  }catch(e){if(revisionCurrent(seq,k,id))out.textContent='소스 변경 내용을 읽지 못했습니다.';}
}
// ------------------------------------------------ [변경 보기] (docs/handbook/viewer.md §변경 보기): opens the changes tab from an awaiting-review/done pin.
// Commit selection: the commit hash (7+ characters) in the close-time reference (ref) > a commit whose subject contains the reference's PR number
// ('(#236)'/'pull request #236') > among the last 12 commits, the most recent one that touched the pin's file/lines (+-5 lines) > the most recent commit.
// Line matching exists only for the source diff - a line whose new-side line number falls within the pin's range is highlighted and scrolled to.
// The comparison PDF (latexdiff) has no SyncTeX mapping, so it only moves to roughly the pin's page.
let REV_TARGET=null,REVISION_PDF_COMMIT='';
function matchRevision(ref,revs){ref=String(ref||'');
  for(const m of ref.matchAll(/\b[0-9a-f]{7,40}\b/g)){const r=revs.find(x=>x.id.startsWith(m[0])); if(r)return {id:r.id,via:'sha',tok:m[0]};}
  for(const m of ref.matchAll(/#(\d+)/g)){const n=m[1],re=new RegExp('\\(#'+n+'\\)|pull request #'+n+'\\b|#'+n+'\\b');
    const r=revs.find(x=>re.test(x.subject||'')); if(r)return {id:r.id,via:'pr',tok:'#'+n};}
  return null;}
function pinFileIndex(files,file){file=String(file||''); let best=-1,len=0;
  files.forEach((f,i)=>{const n=f.name; if(n&&(file===n||file.endsWith('/'+n))&&n.length>len){best=i;len=n.length;}}); return best;}
function hunkRanges(text){const out=[]; for(const m of String(text||'').matchAll(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm)){
  const a=+m[1],n=m[2]===undefined?1:+m[2]; out.push([a,a+Math.max(n,1)-1]);} return out;}
function touchesPin(files,tg,slack){const i=pinFileIndex(files,tg.file); if(i<0)return false; slack=slack==null?5:slack;
  return hunkRanges(files[i].text).some(([a,b])=>b>=tg.lo-slack&&a<=tg.hi+slack);}
async function pickRevisionFor(tg,revs,seq,k){
  const m=matchRevision(tg.ref,revs); if(m)return m;
  if(!tg.region&&tg.file){for(const r of revs){if(seq!==REVISION_SEQ||k!==DOC)break;
    try{const d=(await api(dq('/api/revision-diff?commit='+encodeURIComponent(r.id),k),{what:'변경 내용 읽기',silent:true})).data;
      if(touchesPin(revisionFiles(d.diff||''),tg))return {id:r.id,via:'lines'};}catch(e){}}}
  return {id:revs[0].id,via:'latest'};}
function revTargetNote(msg){const tg=REV_TARGET,box=$('#revision-pin'); if(!tg){box.hidden=true;return;}
  const via={sha:tl('참조의 커밋 {tok}',{tok:tg.tokOf||''}),pr:tr('참조의 PR'),lines:tr('이 줄을 바꾼 가장 최근 커밋'),latest:tr('참조로 커밋을 찾지 못해 가장 최근 커밋')}[tg.via]||'';
  const where=tg.region?tl('쪽 {page} 영역',{page:tg.page}):tg.name+' '+rng(tg.lo,tg.hi);
  const sc=REVISION_FORMAT==='source'&&REVISION_SCOPE&&REVISION_SCOPE.mode==='pin'?REVISION_SCOPE:null;
  const scopeMsg=sc?tl('이 핀의 변경 {n}곳만 보입니다',{n:sc.hunks})+' ('+tr(sc.source==='changes'?'에이전트가 기록한 줄':'핀 자리로 추정')+') · ':'';
  let t=msg?tr(msg):scopeMsg+(REVISION_FORMAT==='pdf'?tl('비교 PDF에는 줄 대응이 없어 원고 {page}쪽 근처로만 옮겼습니다(삭제 문장이 끼어 쪽이 밀릴 수 있음). 정확한 줄은 [소스 diff]',{page:tg.page}):
    tr(tg.hit===false?'이 커밋의 diff에서 핀 범위를 찾지 못했습니다 — 가장 가까운 줄을 보입니다':
     tg.near?'핀 범위 줄 자체는 바뀌지 않았고 바로 곁(±5줄)이 바뀌었습니다 — 가장 가까운 줄을 보입니다':'강조한 줄이 핀 범위입니다'));
  const back=REV_BACK&&REV_BACK!==DOC&&docInfo(REV_BACK)?docInfo(REV_BACK).name:null;
  box.innerHTML='<span><b>'+esc(tl('핀 #{id}',{id:tg.id}))+'</b> · '+esc(where)+(tg.ref?' · '+esc(tl('참조 {ref}',{ref:tg.ref})):'')+(via?' · '+esc(via):'')+'</span><span class="rp-msg">'+esc(t)+'</span>'+
    '<button class="btn-sm" data-act="rev-back" data-tip="'+esc(back?tl('{name} 원고 보기로 돌아갑니다',{name:back}):tr('원고 보기로 돌아갑니다'))+'">'+esc(back?tl('{name}(으)로',{name:back}):tr('원고로'))+'</button>';
  box.hidden=false;}
function revHighlight(tg){const rows=$$('#revision-diff .rd-line'); let first=null;
  rows.forEach(el=>{if(!(el.classList.contains('rd-add')||el.classList.contains('rd-context')))return; const n=+el.querySelector('.rd-no').textContent;
    if(n>=tg.lo&&n<=tg.hi){el.classList.add('rd-pin'); if(!first)first=el;}});
  tg.hit=!!first||touchesPin(REVISION_FILES,tg,5); tg.near=!first&&tg.hit;   // when only a neighboring line changed, it's never described as "the highlighted line" (there is none)
  if(!first){const f=pinFileIndex(REVISION_FILES,tg.file); if(f<0)tg.hit=false;
    else{let best=null,dist=Infinity; rows.forEach(el=>{const n=+el.querySelector('.rd-no').textContent; if(!n)return; const d=Math.min(Math.abs(n-tg.lo),Math.abs(n-tg.hi)); if(d<dist){dist=d;best=el;}}); first=best;}}
  revTargetNote(); if(first)requestAnimationFrame(()=>first.scrollIntoView({block:'center'}));}
function findAnyPin(id){return OPEN_ALL.find(p=>p.id===id)||REVIEW_ALL.find(p=>p.id===id)||DONE_ALL.find(p=>p.id===id)||null;}
let REV_BACK=null;   // the document being viewed when [변경 보기] was pressed - [원고로] returns to that document (QA: opening it from a cover-letter pin used to leave you stuck on the cover letter)
async function showChange(id){const p=findAnyPin(id); if(!p)return; const k=pdoc(p); if(!document.body.classList.contains('revision-open'))REV_BACK=DOC;
  if(k!==DOC&&docInfo(k)){await switchDoc(k); if(DOC!==k)return;}
  REV_TARGET={id:p.id,file:p.file||p.pdf||'',name:p.name||String(p.file||p.pdf||'').split('/').pop(),lo:p.lo,hi:p.hi,page:p.page,ref:p.close_ref||'',region:isRegion(p)};
  const m=/\b[0-9a-f]{7,40}\b/.exec(REV_TARGET.ref); REV_TARGET.tokOf=m?m[0]:'';
  if(LAYOUT==='narrow')setSide(false);
  if(document.body.classList.contains('revision-open'))loadRevisions(); else setViewMode('revisions');}
async function loadRevisionPdf(id,seq,k){
  const statusBox=$('#revision-status'),warningBox=$('#revision-warning'),tg=REV_TARGET;
  // v0.3: for a pin, the comparison is old + only that pin's hunks unless [커밋 전체 비교] is on or that build already failed
  const pin=revisionPinFor(id)&&!REV_SCOPE.whole&&!REV_SCOPE.fallback?tg.id:null,pq=pin?'&pin='+pin:'';
  try{
    let status=(await api('/api/revision-build',{method:'POST',body:pin?{commit:id,doc:k,pin}:{commit:id,doc:k},what:'비교 PDF 만들기',silent:true})).data;
    if(!revisionCurrent(seq,k,id))return;
    if(pin&&status.scope){REV_SCOPE.partial=status.scope==='pin';syncRevisionWhole();}
    for(let tries=0;status.state==='running'&&tries<180;tries++){
      if(!revisionCurrent(seq,k,id))return;
      statusBox.textContent='선택 커밋의 비교 PDF를 만드는 중입니다. 원고와 핀은 그대로 사용할 수 있습니다.';
      await new Promise(resolve=>setTimeout(resolve,1000));
      if(!revisionCurrent(seq,k,id))return;
      status=(await api(dq('/api/revision-build?commit='+encodeURIComponent(id)+pq,k),{what:'비교 PDF 상태',silent:true})).data;
    }
    if(!revisionCurrent(seq,k,id))return;
    if(pin&&status.scope==='pin'&&status.state==='error'){   // the pin's hunks alone did not compile: show the whole commit, say so in one line
      REV_SCOPE.fallback=true;syncRevisionWhole();return loadRevisionPdf(id,seq,k);}
    if(status.state!=='ready')throw new Error(errText(status)||tr(status.state==='running'?'비교 PDF 대기 시간이 지났습니다. 다시 열어 재시도하세요.':'비교 PDF를 만들지 못했습니다.'));
    if(status.head&&status.head!==id)throw new Error(tr('요청한 커밋과 비교 PDF의 커밋이 다릅니다.'));
    const warnings=Array.isArray(status.warnings)?status.warnings:[];
    warningBox.hidden=!warnings.length;warningBox.querySelector('summary').textContent=tl('빌드 경고 {n}건 보기',{n:warnings.length});
    warningBox.querySelector('pre').textContent=warnings.join('\n');warningBox.open=false;
    statusBox.textContent='비교 PDF를 읽는 중입니다.';
    const response=await fetch(dq('/api/revision-pdf?commit='+encodeURIComponent(id)+pq,k));
    if(!response.ok)throw new Error(tl('비교 PDF를 열지 못했습니다 (HTTP {status}).',{status:response.status}));
    const bytes=new Uint8Array(await response.arrayBuffer());
    if(!revisionCurrent(seq,k,id))return;
    const lib=VEC.lib||await import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V);
    lib.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V;
    const loading=lib.getDocument({data:bytes,isEvalSupported:false,useWasm:false,enableXfa:false});REV_PDF.loading=loading;
    const pdf=await loading.promise;
    if(!revisionCurrent(seq,k,id)){try{loading.destroy();}catch(e){}return;}
    REV_PDF.doc=pdf;
    const lead=pin&&status.scope==='pin'?tl('핀 #{id}의 변경만',{id:pin})+' · ':REV_SCOPE.fallback&&tg?tr('이 핀의 변경만으로는 비교 PDF를 만들지 못해 커밋 전체를 비교합니다')+' · ':'';
    statusBox.textContent=lead+tl('첫 부모 {base} → {head} · {n}쪽 · 읽기 전용 · 빨강 삭제 / 파랑 추가',{base:String(status.base||'').slice(0,8),head:id.slice(0,8),n:pdf.numPages});
    const box=$('#revision-pdf');box.innerHTML=Array.from({length:pdf.numPages},(_,i)=>'<div class="revision-page" data-page="'+(i+1)+'" aria-label="'+esc(tl('비교 PDF {page}쪽',{page:i+1}))+'"></div>').join('');
    if(window.IntersectionObserver){REV_PDF.observer=new IntersectionObserver(rows=>{for(const row of rows)if(row.isIntersecting){
      REV_PDF.observer.unobserve(row.target);renderRevisionPage(row.target,pdf,seq,k,id);
    }},{root:box,rootMargin:'600px 0px'});box.querySelectorAll('.revision-page').forEach(el=>REV_PDF.observer.observe(el));}
    else for(const el of box.querySelectorAll('.revision-page'))renderRevisionPage(el,pdf,seq,k,id);
    if(REV_TARGET&&REV_TARGET.page){const el=box.querySelector('.revision-page[data-page="'+Math.min(REV_TARGET.page,pdf.numPages)+'"]'); if(el)el.scrollIntoView({block:'start'}); revTargetNote();}
  }catch(e){if(revisionCurrent(seq,k,id)){
    statusBox.textContent=tl('비교 PDF: {error} 소스 diff에서 변경 내용을 확인할 수 있습니다.',{error:e&&e.message?e.message:tr('표시하지 못했습니다.')});
  }}
}
async function renderRevisionPage(el,pdf,seq,k,id){
  if(el.dataset.state||!revisionCurrent(seq,k,id))return;el.dataset.state='loading';
  try{const page=await pdf.getPage(Number(el.dataset.page));if(!revisionCurrent(seq,k,id))return;
    const base=page.getViewport({scale:1}),cssWidth=Math.min(780,$('#revision-pdf').clientWidth-24),scale=Math.max(0.25,cssWidth/base.width);
    const viewport=page.getViewport({scale}),dpr=Math.min(2,window.devicePixelRatio||1),canvas=document.createElement('canvas');
    canvas.width=Math.ceil(viewport.width*dpr);canvas.height=Math.ceil(viewport.height*dpr);
    canvas.style.width=viewport.width+'px';canvas.style.height=viewport.height+'px';el.style.minHeight=viewport.height+'px';el.append(canvas);
    const task=page.render({canvasContext:canvas.getContext('2d'),viewport,transform:[dpr,0,0,dpr,0,0]});REV_PDF.tasks.add(task);
    try{await task.promise;el.dataset.state='ready';}finally{REV_PDF.tasks.delete(task);}
  }catch(e){if(revisionCurrent(seq,k,id)){$('#revision-status').textContent='일부 비교 PDF 쪽을 그리지 못했습니다. 소스 diff를 확인할 수 있습니다.';el.dataset.state='error';}}
}
function drawDocsMenu(){
  $('#docs-menu-list').innerHTML=DOCS.map(d=>{const on=d.key===DOC;
    return '<button class="dm-item'+(on?' on':'')+'" role="option" aria-selected="'+on+'" data-act="doc" data-doc="'+esc(d.key)+'" data-close="1">'+
      '<span class="tx"><span class="nm">'+esc(d.name)+(on?ic('check'):'')+'</span><span class="ph">'+esc(d.path)+'</span></span>'+docBadge(d)+'</button>';}).join('');}
function openDocsMenu(){const d=$('#docs-menu'); if(d.open)return; hideTip(); drawDocsMenu(); d.showModal();
  const on=d.querySelector('.dm-item.on'); if(on)on.focus();}
// Viewed position: page/fraction anchored at the top, page width, whether zoomed manually in compact, horizontal scroll. Kept in sessionStorage so it survives a reload.
function saveView(){if(!DOC||!META||!$('#doc .pg'))return; const a=topAnchor();
  VIEW_BY.set(DOC,{page:a?a.page:1,frac:a?a.frac:0,w:W,zoomed:ZOOMED,sl:$('#left').scrollLeft,lay:LAYOUT});
  if(multiDoc()){try{sessionStorage.setItem('pinDocView',JSON.stringify(Array.from(VIEW_BY.entries())));}catch(e){}}}
function loadViews(){if(!multiDoc())return; try{const a=JSON.parse(sessionStorage.getItem('pinDocView')||'[]');
  if(Array.isArray(a))a.forEach(x=>{if(Array.isArray(x)&&docInfo(x[0])&&x[1]&&typeof x[1]==='object')VIEW_BY.set(x[0],x[1]);});}catch(e){}}
// The page width is decided first (buildDoc builds pages using W). Only a width viewed in the same layout is restored - so a width fit for a folded screen is never applied on desktop.
function applyViewWidth(v){if(v&&typeof v.w==='number'&&v.lay===LAYOUT&&(LAYOUT==='wide'||v.zoomed)){W=v.w; ZOOMED=LAYOUT!=='wide'&&!!v.zoomed; return true;}
  ZOOMED=false; return false;}
function restoreView(v){if(!v)return; restoreAnchor({page:v.page,frac:v.frac}); if(typeof v.sl==='number')$('#left').scrollLeft=v.sl;}
addEventListener('pagehide',saveView);
// Switches documents. Remembers the current document's viewed position, and cancels any in-progress selection/re-place-location (a note's draft text is kept).
// If a meta cache exists, that document is drawn immediately without waiting, then the latest meta is fetched in the background, and pages are swapped only if the build changed.
async function switchDoc(k){
  if(!k||k===DOC||!docInfo(k))return; const seq=++SWITCHSEQ;
  if(document.body.classList.contains('revision-open'))setViewMode('manuscript');
  saveView(); cancelRepick(); if(CUR||!$('#composer').hidden)cancelSelection(false);
  if(EDIT&&!editDirty())cancelEdit();
  let m=META_BY.get(k),cached=!!m;
  if(!m){try{m=(await api(dq('/api/meta',k),{what:'문서 열기'})).data;}catch(e){return;} if(seq!==SWITCHSEQ)return;}
  DOC=k; META=m; META_BY.set(k,m); savePrefs({lastDoc:k}); setHash(k);
  hideTip(); showDoc(VIEW_BY.get(k));
  if(cached){try{const f=(await api(dq('/api/meta',k),{what:'문서 열기',silent:true})).data;
    if(seq===SWITCHSEQ&&DOC===k){const changed=f.pages_build!==META.pages_build||f.pages.length!==META.pages.length;
      META_BY.set(k,f); if(changed)await refreshDoc(); else{META=f; drawMeta();}}}catch(e){}}
}
// Redraws the screen from the current META (tab switching). The build chip, error panel, and auto-polling baseline are all switched to that document's values too.
function showDoc(v){
  drawMeta(); const hadW=applyViewWidth(v); buildDoc(); if(!hadW)autoW(); restoreView(v);
  if(!v&&$('#left'))$('#left').scrollTop=0;
  PINS=OPEN_ALL.filter(p=>pdoc(p)===DOC); drawPins(); marks(); drawDocTabs();
  $('#outline-items').textContent=tr('PDF 목차를 읽는 중입니다.');
  if(document.body.classList.contains('revision-open'))loadRevisions();
  vecOpen();
  if(BUILD_TIMER){clearInterval(BUILD_TIMER);BUILD_TIMER=null;} $('#build-chip').hidden=true; $('#btn-rebuild').disabled=false;
  LAST_BUILD_SEQ=(typeof META.build_seq==='number')?META.build_seq:0; LAST_BUILD_ERR=BUILD_ERR_BY.get(DOC)||null;
  if(LAST_BUILD_ERR)hideBuildErr(); else{$('#build-err').hidden=true; $('#build-err-chip').hidden=true;}
  BUILD_BOOTED=true; if(BUILD_INFLIGHT)BUILD_INFLIGHT.then(()=>pollBuild()); else pollBuild();   // if a previous document's request is still in flight, queue after it
  docTitle(false);
}
// The tab title: 'Limn · <label> · <document> · 열린 N' (+ ' · 검토 N' once the pin list knows the review count).
function docTitle(review){if(!META)return;
  document.title='Limn · '+(META.label?META.label+' · ':'')+(multiDoc()?META.doc_name||META.main:META.main)+' · '+tl('열린 {n}',{n:PINS.length})+
    (review&&REVIEW_ALL.length?' · '+tl('검토 {n}',{n:REVIEW_ALL.length}):'');}
function cycleDoc(step){if(!multiDoc())return; const i=DOCS.findIndex(d=>d.key===DOC);
  switchDoc(DOCS[(i+step+DOCS.length)%DOCS.length].key);}
window.addEventListener('hashchange',()=>{const k=hashDoc(); if(k&&k!==DOC&&docInfo(k))switchDoc(k);});
// A #number/[보기]/[수정] on another document's pin: switches to that document, then calls then again (used by jumpPin/openEdit at the very top). Returns true if it switched.
function viaDoc(id,then){const p=OPEN_ALL.find(x=>x.id===id);
  if(!p||pdoc(p)===DOC||!docInfo(pdoc(p)))return false;
  const k=pdoc(p); switchDoc(k).then(()=>{if(DOC===k)then(id);}); return true;}

// ------------------------------------------------ Document
async function boot(){i18nStart();
  // A link /#doc=<key>&pin=<n>[&act=restore] (a notification clicked with no tab open) is read first: the boot below rewrites the
  // hash to #doc=<key> on an instance with several documents, which used to lose pin= (0.2.1 and earlier).
  const link=takeLinkHash();
  applyTheme(); applyLayout(); initDiffWrap();
  // There's no keyboard shortcut on a touch device - "핀 저장 Ctrl+Enter" would just get clipped at phone width.
  $('#btn-save').innerHTML=saveBtnLabel();
  await loadDocs(); DOC=initialDoc();
  try{META=(await api(dq('/api/meta'),{what:'화면 정보 읽기'})).data;}catch(e){return;}
  if(META.doc)DOC=META.doc; META_BY.set(DOC,META); loadViews(); const v=VIEW_BY.get(DOC);
  if(multiDoc()){setHash(DOC); savePrefs({lastDoc:DOC});}
  drawMeta(); applySideWidth(); applyOutlineState(); const hadW=applyViewWidth(v); buildDoc(); if(!hadW)autoW(); vecBoot(); await loadPins();
  restoreView(v); drawDocTabs();
  if(MQ_COARSE.matches)coach('touch','PDF를 길게 누르면 그 문단을 고릅니다 · [선택]을 켜면 끌어서 고릅니다');
  LAST_PINS_REV=META.pins_rev; LAST_SRC_MTIME=META.src_sig||META.src_mtime;
  LAST_BUILD_SEQ=(typeof META.build_seq==='number')?META.build_seq:0;   // the build count this tab has already "seen"
  (META.docs||[]).forEach(d=>DOC_SEQ.set(d.key,d.build_seq));
  startLightPolling(); startBuildPolling();
  drawNotify(); if(prefs().notify&&notifySupported()&&notifyPerm()==='granted')notifyRegister();
  if(link.pin)openPinFromLink(link.doc||DOC,link.pin,link.restore);
}
function builtAtEpoch(s){const t=Date.parse(String(s||'').replace(' ','T')); return isNaN(t)?null:t/1000;}
// The "manuscript modified" badge - judged only from numbers the server provides (stale_build, src_age_s), independent of the browser's clock/timezone.
// Only a legacy response with no stale_build falls back to comparing src_mtime/build_src_mtime (both server epochs).
function updateStaleBadge(m){
  const badge=$('#meta-stale'), btn=$('#btn-rebuild');
  let stale;
  if(typeof m.stale_build==='boolean')stale=m.stale_build;
  else{const ref=(typeof m.build_src_mtime==='number')?m.build_src_mtime:builtAtEpoch(META&&META.built_at);
    stale=ref!=null&&typeof m.src_mtime==='number'&&m.src_mtime>ref+2;}
  if(!stale){badge.hidden=true; btn.classList.remove('btn-default'); return;}
  const age=(typeof m.src_age_s==='number')?m.src_age_s:(Date.now()/1000-m.src_mtime);
  const mins=Math.max(0,Math.round(age/60));
  badge.hidden=false; badge.textContent=tl('원고 수정됨 · {n}분 전',{n:mins});
  btn.classList.add('btn-default');
}
const SYNC_REASON={not_git:'Git 저장소가 아닙니다',no_upstream:'main 업스트림이 없습니다',not_main:'현재 체크아웃이 main이 아닙니다',
  dirty:'로컬에 커밋되지 않은 수정이 있습니다',diverged:'로컬 main과 원격 main이 갈라졌습니다',
  fetch_failed:'원격을 확인하지 못했습니다',fetch_timeout:'원격 확인 시간이 초과됐습니다',
  status_failed:'로컬 수정 상태를 읽지 못했습니다',unexpected:'동기화 중 오류가 났습니다',
  building:'다른 PDF 빌드가 진행 중입니다',build_failed:'새 원고의 PDF 빌드가 실패했습니다'};
function updateSyncBadge(s){const b=$('#meta-sync'); if(!b)return;
  if(!s||s.state==='disabled'||s.state==='current'){b.hidden=true; return;}
  b.hidden=false; b.classList.toggle('badge-warning',s.state==='blocked'||s.state==='error');
  const reason=tr(SYNC_REASON[s.reason]||s.reason||'');
  b.textContent=tr(s.state==='updating'?'최신 main PDF 반영 중':s.state==='updated'?'최신 main 반영됨':
    s.state==='deferred'?'빌드 뒤 main 확인':s.state==='checking'?'main 확인 중':'main 동기화 확인 필요');
  b.dataset.tip=reason?(b.textContent+' · '+reason+' · '+tr('기존 PDF가 보일 수 있습니다')):b.textContent;
}
function isViewer(){return !!(typeof META!=='undefined'&&META&&META.me&&META.me.role==='viewer');}
// A state change the viewer role cannot make (the server answers 403 anyway): say so once instead of sending it.
function viewerBlocked(){if(!isViewer())return false; toast('보기 권한(viewer)만 있는 계정이라 바꿀 수 없습니다','warn'); return true;}
function drawMeta(){
  document.body.classList.toggle('view-only',!!META.view_only);
  document.body.classList.toggle('role-viewer',isViewer());
  $('#meta-main').textContent=META.main; $('#meta-pages').textContent=tl('{n}쪽',{n:META.pages.length});
  $('#meta-head').textContent=META.head; $('#meta-built').textContent=String(META.built_at||'').slice(0,16).replace('T',' ');
  const me=META.me||{};
  $('#me').innerHTML=avatar(me)+'<span class="au-n">'+esc(who(me))+'</span>';
  $('#me').dataset.tip=tl('지금 이 화면을 쓰는 사람: {name}. 핀을 저장·수정·완료하면 이 이름으로 기록됩니다',{name:(isAgent(me)?who(me):me.name||'')+(me.login&&me.login!=='local'?' ('+me.login+')':'')});
  updateStaleBadge(META);
  updateSyncBadge(META.sync);
  $('#help-pins-md').textContent=META.pins_md||'';
  // In compact, #bar2's file/commit/time/author line is hidden and shown as a single line inside [⋯] instead (so a long filename never overflows).
  $('#more-info').textContent=[META.main,tl('{n}쪽',{n:META.pages.length}),META.head,String(META.built_at||'').slice(0,16).replace('T',' '),
    tl('나: {name}',{name:who(me)})].filter(Boolean).join(' · ');
}

// ------------------------------------------------ Auto sync (P0b-02) - lightweight meta polling
let LAST_PINS_REV=null,LAST_SRC_MTIME=null,POLL_FAILS=0,LIGHT_TIMER=null,LIGHT_INFLIGHT=null;
// Single-flight: same pattern as pollBuild - even if visibilitychange/focus/the 5-second timer overlap and
// call this together (e.g. focus returning at the same moment as a tab switch), /api/meta and loadPins only go out once (observed defect: overlapping calls fired loadPins 3 times).
function pollLight(){
  if(document.hidden)return Promise.resolve();   // a heavy refresh (including redrawing the list) is never sent while the tab is hidden
  if(LIGHT_INFLIGHT)return LIGHT_INFLIGHT;
  LIGHT_INFLIGHT=pollLightOnce().finally(()=>{LIGHT_INFLIGHT=null;});
  return LIGHT_INFLIGHT;
}
// While the tab is hidden, the list is never redrawn (observed defect: a hidden tab received no notifications at all), but if notifications
// are on (notifyOn), a light (slow - the browser throttles it anyway) /api/meta?light=1 call is still made just to surface events as notifications.
// This is a notification-only branch splitting off at the same point as pollLight's document.hidden bailout - it never touches the screen.
let NOTIFY_HIDDEN_TIMER=null,NOTIFY_HIDDEN_INFLIGHT=null;
const NOTIFY_HIDDEN_INTERVAL_MS=20000;
function pollHiddenNotify(){
  if(!document.hidden||!notifyOn())return Promise.resolve();
  if(NOTIFY_HIDDEN_INFLIGHT)return NOTIFY_HIDDEN_INFLIGHT;
  NOTIFY_HIDDEN_INFLIGHT=pollHiddenNotifyOnce().finally(()=>{NOTIFY_HIDDEN_INFLIGHT=null;});
  return NOTIFY_HIDDEN_INFLIGHT;
}
async function pollHiddenNotifyOnce(){
  let d;
  try{d=(await api(dq('/api/meta?light=1')+notifyQuery(),{what:'알림 확인',silent:true})).data;}catch(e){return;}
  if(document.hidden)notifyHandle(d);   // if the tab came back while waiting, normal polling has already handled it
}
// If the tab hides while notifications are on, the slow timer is started; it's stopped when the tab returns or notifications are turned off (avoids duplicate polling).
function syncHiddenNotifyTimer(){
  clearInterval(NOTIFY_HIDDEN_TIMER); NOTIFY_HIDDEN_TIMER=null;
  if(document.hidden&&notifyOn()){pollHiddenNotify(); NOTIFY_HIDDEN_TIMER=setInterval(pollHiddenNotify,NOTIFY_HIDDEN_INTERVAL_MS);}
}
async function pollLightOnce(){
  let d; const k=DOC;
  try{d=(await api(dq('/api/meta?light=1')+notifyQuery(),{what:'상태 확인',silent:true})).data; POLL_FAILS=0;}
  catch(e){POLL_FAILS++; if(POLL_FAILS>=2)$('#conn-lost').hidden=false; return;}
  $('#conn-lost').hidden=true;
  notifyHandle(d);                      // browser notifications - independent of the document (handled first even mid document-switch)
  if(k!==DOC)return;                    // the document changed while waiting - the screen is never painted with a stale document's state
  updateStaleBadge(d); updateSyncBadge(d.sync); noteOtherDocs(d.docs);
  // With multiple documents, re-read even if src_sig (per-document src_mtime) changed - another document's manuscript changing shifts that document's pins' lines too.
  const sig=d.src_sig||d.src_mtime;
  if(LAST_PINS_REV!==null&&(d.pins_rev!==LAST_PINS_REV||sig!==LAST_SRC_MTIME)) await loadPins();
  LAST_PINS_REV=d.pins_rev; LAST_SRC_MTIME=sig;
  // A build started via curl by another session/agent is also caught through light meta's build.state - the 1-second poll only
  // runs during that (or when this tab itself pressed rebuild()).
  if(d.build&&d.build.state==='running'&&!BUILD_TIMER)pollBuild();
  // If build_seq (number of finished builds) differs from what this tab has seen, it means a build started and finished entirely
  // within a 5-second polling gap, never observed as "running" - the details are fetched to sync up the screen/banner/chip.
  else if(typeof d.build_seq==='number'&&d.build_seq!==LAST_BUILD_SEQ)pollBuild();
}
// Reflects another document's staleness/in-progress build on its tab, and if that document's build finished in the background, notifies and then drops the meta cache (a fresh page when you switch back).
function noteOtherDocs(list){if(!Array.isArray(list)||!list.length)return; let redraw=false;
  list.forEach(n=>{const d=docInfo(n.key); if(!d)return;
    if(d.stale_build!==n.stale_build||d.building!==n.building){d.stale_build=n.stale_build; d.building=n.building; redraw=true;}
    const was=DOC_SEQ.get(n.key); DOC_SEQ.set(n.key,n.build_seq);
    if(n.key===DOC||was===undefined||was===n.build_seq)return;
    META_BY.delete(n.key); redraw=true;
    if(n.last_state==='ok')toast(tl(d.view_only?'{name} PDF 쪽을 새로 그렸습니다':'{name} PDF 재빌드 완료',{name:d.name}),'ok',{label:'열기',tip:'그 문서로 바꿉니다',fn:()=>switchDoc(n.key)});
    else if(n.last_state==='ok_errors'||n.last_state==='fail')toast(tl(n.last_state==='fail'?'{name} 빌드 실패':'{name} 빌드에 LaTeX 오류',{name:d.name}),n.last_state==='fail'?'err':'warn',{label:'열기',tip:'그 문서로 바꿔 오류를 봅니다',fn:()=>switchDoc(n.key)});});
  if(redraw)drawDocTabs();}
function startLightPolling(){
  clearInterval(LIGHT_TIMER); LIGHT_TIMER=setInterval(pollLight,5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollLight(); syncHiddenNotifyTimer();});
  window.addEventListener('focus',()=>pollLight());
  syncHiddenNotifyTimer();   // catches it right away if already hidden at boot (a rare case) and notifications are on
}
// This tab's own close/drop/reopen/restore already showed a local toast, so the next loadPins()'s
// diffToast never announces the same transition again - only the first diffToast judgment right after markMine(id) is swallowed
// (consumeMine removes it as soon as it's confirmed), and if that judgment hasn't arrived after 10 seconds (e.g. a lost response), it's
// given up on and subsequent values are announced normally. An action from another tab isn't in this map, so it's shown as usual.
const MY_ACTIONS=new Map();
function markMine(id){MY_ACTIONS.set(id,Date.now()+10000);}
function consumeMine(id){const until=MY_ACTIONS.get(id); if(until===undefined)return false;
  MY_ACTIONS.delete(id); return Date.now()<=until;}
function diffToast(prev,d,dropped){
  // prev is only the "open pins" this tab saw last time (PINS never holds done ones). d is every open+closed
  // pin (all=1) from this GET - if an id that was in prev is also in d with done=true, it was completed; if it's
  // not in d at all (neither open nor closed), it was dropped. The old implementation never distinguished the
  // two and announced everything as "completed" - if a co-author deleted a pin, the author's screen showed "#N 이 완료되었습니다" (observed).
  if(!prev||!prev.length)return;
  const byId=new Map(prev.map(p=>[p.id,p]));
  const known=new Map((d||[]).map(p=>[p.id,p]));
  const dropById=new Map((dropped||[]).map(p=>[p.id,p]));
  const closed=[],droppedIds=[],reviewed=[];
  byId.forEach((_,id)=>{const n=known.get(id);
    if(n&&n.done){if(!consumeMine(id))(n.review?reviewed:closed).push(id);}
    else if(!n){if(!consumeMine(id))droppedIds.push(id);}});
  if(closed.length)toast(tl('#{ids} 이 완료되었습니다',{ids:closed.join(', #'),n:closed.length}),'ok');
  if(reviewed.length)toast(tl('#{ids} 이 검토 대기로 넘어왔습니다 — 결과를 보고 [확인]하세요',{ids:reviewed.join(', #'),n:reviewed.length}),'ok',null,{keys:reviewed.map(i=>'review_requested:'+i)});
  droppedIds.forEach(id=>{const rec=dropById.get(id),nm=rec?who(rec.dropped_by):'';
    toast(tl('#{id} 을 {name} 가 삭제함',{id,name:nm||tr('다른 세션')}),'warn',{label:'되살리기',fn:()=>restorePin(id)},{keys:['dropped:'+id]});});
  (d||[]).filter(p=>!p.done).forEach(p=>{const was=byId.get(p.id); if(!was)return;
    if(!was.stale&&p.stale){toast(tl('#{id} 위치를 잃었습니다',{id:p.id}),'warn');return;}
    const m=/^moved ([+-]\d+)$/.exec(p.sync||''),wm=/^moved ([+-]\d+)$/.exec(was.sync||'');
    if(m&&(!wm||wm[1]!==m[1]))toast(tl('#{id} 줄 {delta} 이동',{id:p.id,delta:m[1]}),'ok');});
}

// Announces when a pin that was awaiting review gets confirmed (done) or reopened elsewhere. An action this tab performed (markMine) is swallowed.
function pinState(p){return (p&&p.state)||(p&&p.done?(p.review?'review':'done'):'open');}
function reviewToast(prev,d){if(!prev||!prev.length)return; const known=new Map((d||[]).map(p=>[p.id,p]));
  prev.forEach(p=>{const n=known.get(p.id); if(!n)return; const st=pinState(n); if(st==='review')return; if(consumeMine(p.id))return;
    if(st==='done')toast(tl('#{id} 확인됨',{id:p.id})+(n.confirmed_by?' · '+who(n.confirmed_by):''),'ok');
    else toast(tl('#{id} 다시 열림',{id:p.id})+(n.reopened_by?' · '+who(n.reopened_by):''),'warn',null,{keys:['reopened:'+p.id]});});}

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
  if(link.pin)history.replaceState(null,'',location.pathname+location.search+(link.doc?'#doc='+link.doc:''));
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

// ------------------------------------------------ Async build-progress chip (P0b-01)
// BUILD_TIMER only exists while a build is actually running - /api/build is never hit every second once there's
// nothing to do (already settled into idle/ok/fail). There are only three places it starts: this tab pressing rebuild(),
// pollLight (the 5-second poll) seeing build.state==='running', and catching an already-running build at boot.
// A finished build is counted via build_seq (the server bumps it by 1 per build). LAST_BUILD_SEQ is the value this tab
// has already processed - processing (swapping the screen, toasting) happens exactly once per seq. Counting via the
// started_at string or "was running ever observed" instead missed a build that finished within a 5-second gap, or
// double-processed the same completion when a hidden tab came back via two paths at once (observed: toast x2).
let BUILD_TIMER=null,LAST_BUILD_ERR=null,LAST_BUILD_SEQ=null,BUILD_BOOTED=false,BUILD_INFLIGHT=null;
function buildChipText(b){
  const label={pull:'원격 main 당겨오는 중',copy:'원고 복사 중',latex:'LaTeX 컴파일 중',render:'쪽 그리는 중'}[b.phase]||'재빌드 중';
  const el=Math.round(b.elapsed_s||0), last=b.last_s?' '+tl('(지난번 {s}초)',{s:Math.round(b.last_s)}):'';
  return tr(label)+' · '+tl('{s}초',{s:el})+last;
}
// §P0c-E: appends one line about the pull result to the build-complete toast. ok gets the applied commit range,
// skipped/error just the reason - up_to_date has nothing worth reporting, so nothing is appended.
function pullSuffix(b){
  const p=b&&b.pull; if(!p||!p.state)return '';
  if(p.state==='ok')return ' · '+tl('원격 반영 {range}',{range:String(p.head_before||'?').slice(0,7)+'..'+String(p.head_after||'?').slice(0,7)});
  if(p.state==='skipped'||p.state==='error')return ' · '+tl(p.state==='error'?'git pull 실패({reason})':'git pull 건너뜀({reason})',{reason:p.reason||'?'});
  return '';
}
// Single-flight: if a request is already in flight, that same promise is returned instead of sending a new one (even if the
// 1-second timer, visibilitychange, focus, and pollLight all call it together, /api/build only goes out once and completion is only processed once).
function pollBuild(){
  if(document.hidden)return Promise.resolve();   // the request is never even sent while the tab is hidden
  if(BUILD_INFLIGHT)return BUILD_INFLIGHT;
  BUILD_INFLIGHT=pollBuildOnce().finally(()=>{BUILD_INFLIGHT=null;});
  return BUILD_INFLIGHT;
}
async function pollBuildOnce(){
  let b; const k=DOC;
  try{b=(await api(dq('/api/build?log=1'),{what:'빌드 상태',silent:true})).data;}catch(e){return;}
  if(k!==DOC)return;                    // the document changed - showDoc will query the new one again
  const chip=$('#build-chip');
  if(b.state==='running'){
    chip.hidden=false; chip.textContent=buildChipText(b); $('#btn-rebuild').disabled=true;
    if(!BUILD_TIMER)BUILD_TIMER=setInterval(pollBuild,1000);
    BUILD_BOOTED=true; return;
  }
  chip.hidden=true; $('#btn-rebuild').disabled=false;
  if(BUILD_TIMER){clearInterval(BUILD_TIMER);BUILD_TIMER=null;}    // polling stops once there's nothing left to watch
  const seq=(typeof b.seq==='number')?b.seq:0;
  const booted=BUILD_BOOTED; BUILD_BOOTED=true;
  if(LAST_BUILD_SEQ===null)LAST_BUILD_SEQ=seq;
  if(seq!==LAST_BUILD_SEQ){
    LAST_BUILD_SEQ=seq;                 // claimed before the await - so the same completion is never processed twice
    DOC_SEQ.set(k,seq);
    try{await refreshDoc();}catch(e){}
    if(k!==DOC)return;
    const secs=Math.round(b.elapsed_s||0);
    if(b.state==='ok'){toast(tr(META.view_only?'PDF가 바뀌어 쪽을 새로 그렸습니다':'PDF 재빌드 완료')+' · '+tl('{n}쪽',{n:META.pages.length})+' · '+tl('{s}초',{s:secs})+pullSuffix(b),'ok'); LAST_BUILD_ERR=null; BUILD_ERR_BY.delete(k); hideBuildErr();}
    else if(b.state==='ok_errors'){toast(tr('PDF를 재빌드했지만 LaTeX 오류가 있습니다')+pullSuffix(b),'warn'); showBuildErr(b);}
    else if(b.state==='fail'){toast(tr('빌드 실패 — 화면은 이전 PDF입니다')+pullSuffix(b),'err'); showBuildErr(b);}
  }else if(!booted&&(b.state==='fail'||b.state==='ok_errors')){
    showBuildErr(b);   // a freshly opened tab - a build that already failed just opens the panel/chip with no toast (leaves a way to look at it again)
  }
}
function startBuildPolling(){
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollBuild();});
  window.addEventListener('focus',()=>pollBuild());
  pollBuild();   // once at boot - if a build is already running (started by another session), this turns on the 1-second poll
}

// ------------------------------------------------ Panel width (P0b-06 + docs/handbook/viewer.md §패널 정리)
// wide/mid adjusts the right panel's width; narrow adjusts the bottom sheet's height. Width is remembered separately
// per screen kind (pinPrefs.side = wide, pinPrefs.sideMid = mid) - so a width fit for a spread-out screen never covers the desktop width.
// If the saved value exceeds the current screen's limit (collapsing/expanding, shrinking the window), the saved value is kept
// and only the visible width is clamped within the limit. The limit: the minimum is the width where the panel's tool bar fits
// on one line, the maximum is the width that leaves the body (PDF) side its minimum width.
function outlineBounds(){if(LAYOUT==='mid')return {min:220,max:320};const max=Math.max(180,Math.min(320,innerWidth-curSideW()-290));return {min:Math.min(220,max),max};}
function showOutlineWidth(w){const b=outlineBounds();w=Math.round(Math.max(b.min,Math.min(b.max,w)));
  document.documentElement.style.setProperty('--outline-width',w+'px');
  const g=$('#outline-grip');g.setAttribute('aria-valuemin',b.min);g.setAttribute('aria-valuemax',b.max);g.setAttribute('aria-valuenow',w);return w;}
function applyOutlineState(){
  const p=prefs(),closed=LAYOUT==='mid'?!OUTLINE_MID_OPEN:p.outlineClosed===true;
  document.body.classList.toggle('outline-collapsed',closed);
  const t=$('#nav-toc-toggle');t.setAttribute('aria-expanded',String(!closed));t.setAttribute('aria-label',closed?'목차 펼치기':'목차 접기');
  if(LAYOUT!=='narrow')showOutlineWidth(typeof p.outlineWidth==='number'?p.outlineWidth:240);
}
function setOutlineWidth(w){if(LAYOUT==='narrow')return;w=showOutlineWidth(w);savePrefs({outlineWidth:w});relayout();}
function toggleOutline(){const a=topAnchor(),closed=!document.body.classList.contains('outline-collapsed');
  if(LAYOUT==='mid'){OUTLINE_MID_OPEN=!closed;if(!closed)setSide(false);}
  else savePrefs({outlineClosed:closed});
  applyOutlineState();relayout();restoreAnchor(a);$('#nav-toc-toggle').focus({preventScroll:true});}
function sideBounds(layout,iw){const cl=(w,a,b)=>Math.round(Math.min(b,Math.max(a,w)));
  if(layout==='mid'){const min=300,max=iw<=900?Math.min(440,iw-240):Math.max(min,iw-488);
    const def=cl(330,min,max); return {min,max,def,presets:[min,def,cl(iw*0.5,min,max)]};}
  const min=280,max=Math.max(min,Math.min(Math.round(iw*0.8),iw-486)),def=cl(348,min,max);
  return {min,max,def,presets:[cl(300,min,max),def,cl(iw*0.42,min,max)]};}
function clampSide(w,b){return Math.round(Math.min(b.max,Math.max(b.min,w)));}
// Cycles through preset steps: the next step wider than the current width, wrapping to the narrowest if already at the widest. presetIndex is the step within +-4px (or -1 if none matches).
function nextPreset(presets,w){const n=presets.find(p=>p>w+4); return n===undefined?presets[0]:n;}
function presetIndex(presets,w){return presets.findIndex(p=>Math.abs(p-w)<=4);}
function sideKey(){return LAYOUT==='mid'?'sideMid':'side';}
function curSideW(){return Math.round($('#right').getBoundingClientRect().width);}
function showSideW(w,b){$('#right').style.width=w+'px'; document.documentElement.style.setProperty('--side-w',w+'px');
  const g=$('#grip'); g.setAttribute('aria-valuenow',w); g.setAttribute('aria-valuemin',b.min); g.setAttribute('aria-valuemax',b.max);}
function applySideWidth(){
  if(LAYOUT==='narrow'){$('#right').style.width=''; applySheet(); return;}
  const b=sideBounds(LAYOUT,innerWidth),p=prefs()[sideKey()];
  showSideW(clampSide(typeof p==='number'?p:b.def,b),b);
}
// Sets and remembers the width, then re-fits page width/marks (position is preserved - relayout uses topAnchor/restoreAnchor).
function setSideWidth(w){if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth); w=clampSide(w,b);
  showSideW(w,b); savePrefs({[sideKey()]:w}); relayout(); renderSizeSeg();}
function cycleSideWidth(){if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth); setSideWidth(nextPreset(b.presets,curSideW()));}
// Sheet height is stored as a fraction of screen height (--sheet-f) - CSS shrinks it to fit within the visible height when the keyboard is up.
const SHEET_F=[0.45,0.64,1],SHEET_MIN_F=0.3,SHEET_CLOSE_F=0.25;
function sheetF(){const f=prefs().sheetF; return typeof f==='number'?Math.min(1,Math.max(SHEET_MIN_F,f)):0.64;}
function applySheet(){document.documentElement.style.setProperty('--sheet-f',String(sheetF()));}
function setSheetF(f){f=Math.min(1,Math.max(SHEET_MIN_F,f)); savePrefs({sheetF:Math.round(f*1000)/1000}); applySheet(); if(!SIDE_OPEN)setSide(true); renderSizeSeg();}
function cycleSheet(){const f=sheetF(),i=SHEET_F.findIndex(x=>x>f+0.02); setSheetF(SHEET_F[i<0?0:i]);}
// The '패널 폭' (wide/mid) / '시트 높이' (narrow) segment control inside [⋯].
function renderSizeSeg(){const box=$('#m-size'); if(!box)return; const narrow=LAYOUT==='narrow';
  $('#m-size-l').textContent=narrow?'시트 높이':'패널 폭'; box.setAttribute('aria-label',narrow?'시트 높이':'패널 폭');
  let names,cur;
  if(narrow){names=['낮게','보통','높게']; const f=sheetF(); cur=SHEET_F.findIndex(x=>Math.abs(x-f)<=0.02);}
  else{names=['좁게','보통','넓게']; cur=presetIndex(sideBounds(LAYOUT,innerWidth).presets,curSideW());}
  box.innerHTML=names.map((n,i)=>'<button class="'+(i===cur?'on':'')+'" aria-pressed="'+(i===cur)+'" data-act="size-preset" data-i="'+i+'">'+n+'</button>').join('');}
function sizePreset(i){if(LAYOUT==='narrow'){setSheetF(SHEET_F[i]);return;} setSideWidth(sideBounds(LAYOUT,innerWidth).presets[i]);}
function pageSrc(p){return dq('/pages/'+encodeURIComponent(p.name)+'?v='+encodeURIComponent(META.built_at));}
function buildDoc(){
  const doc=$('#doc'); doc.innerHTML=''; PENDING=null;
  META.pages.forEach((p,i)=>{const d=document.createElement('div'); d.className='pg'; d.id='p'+(i+1); d.dataset.page=i+1;
    d.style.width=W+'px'; d.style.aspectRatio=p.pt_w+' / '+p.pt_h;
    d.innerHTML='<span class="no">'+(i+1)+'</span><img loading="lazy" draggable="false" alt="'+esc(tl('{page}쪽',{page:i+1}))+'" src="'+esc(pageSrc(p))+'">';
    doc.appendChild(d);});
  marks(); vecObserve();
}
// save=false is auto-fit - never saved. If a width fit for a narrow first window persisted into a wider window, the pages would look too small.
// Width is never saved in compact (mid/narrow) - so a width fit for a folded screen never overrides the spread/desktop setting.
// The page width limit is ZOOM_MIN-ZOOM_MAX times the fit-width (minimum 160px). Overflow scrolls horizontally only within the PDF area (#left).
const ZOOM_MIN=0.5,ZOOM_MAX=5,ZOOM_STEP=1.2;
function wBounds(fit){const f=Math.max(160,fit),lo=Math.max(160,Math.round(f*ZOOM_MIN)); return [lo,Math.max(lo,Math.round(f*ZOOM_MAX))];}
function setW(w,save){const b=wBounds(fitWidth()); W=Math.round(Math.min(b[1],Math.max(b[0],w))); $$('.pg').forEach(e=>e.style.width=W+'px');
  if(save!==false&&LAYOUT==='wide')savePrefs({w:W}); vecInvalidate();}
function innerW(){const L=$('#left'),cs=getComputedStyle(L); return L.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);}
// Fit-width: in compact, the body's inner width; in wide, #left.clientWidth minus 48px (left/right margins).
function fitWidth(){return LAYOUT!=='wide'?innerW():$('#left').clientWidth-48;}
// compact always fits the screen width (unless the user pressed -/+, in which case it stays fixed for that layout). wide behaves as before.
function autoW(){if(LAYOUT!=='wide'){if(!ZOOMED)setW(innerW(),false);return;}
  if(prefs().w!==undefined)return; const f=$('#left').clientWidth-44-16; setW(f<900?f:900,false);}
// Zoom anchor: the page under screen coordinates (cx,cy) and its fraction within that page. If the point falls in the gap between pages, the vertically nearest page is used.
// Without coordinates, the center of the PDF area is used (keyboard/button).
function zoomAnchor(cx,cy){const L=$('#left'),lr=L.getBoundingClientRect();
  if(cx==null){cx=lr.left+L.clientWidth/2; cy=lr.top+L.clientHeight/2;}
  let best=null,bd=Infinity;
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(),d=cy<r.top?r.top-cy:(cy>r.bottom?cy-r.bottom:0);
    if(d<bd){bd=d; best={pg,r};} if(d===0)break;}
  return best?{pg:best.pg,cx,cy,fx:(cx-best.r.left)/best.r.width,fy:(cy-best.r.top)/best.r.height}:null;}
// Restores the anchor's in-page fractional position back to screen coordinates (cx,cy) - so the text under the pointer stays put even after zooming.
function zoomRestore(a,cx,cy){if(!a)return; const L=$('#left'),r=a.pg.getBoundingClientRect();
  L.scrollLeft+=r.left+a.fx*r.width-(cx==null?a.cx:cx); L.scrollTop+=r.top+a.fy*r.height-(cy==null?a.cy:cy);}
function zoomTo(w,cx,cy){const a=zoomAnchor(cx,cy); setW(w); if(LAYOUT!=='wide')ZOOMED=true; zoomRestore(a);}
function zoom(k){zoomTo(W*Math.pow(ZOOM_STEP,k));}
// Fit width: keeps the viewed page/position (anchored at the top) and resets horizontal scroll to the start.
function fitW(){const a=topAnchor(),L=$('#left');
  if(LAYOUT!=='wide'){ZOOMED=false; setW(innerW(),false);} else setW(L.clientWidth-48);
  restoreAnchor(a); L.scrollLeft=0;}
function goPage(v){const el=document.getElementById('p'+parseInt(v===undefined?$('#jump').value:v,10)); if(el) el.scrollIntoView({behavior:SMOOTH});}
$('#jump').addEventListener('keydown',e=>{if(e.key==='Enter')goPage();});
$('#m-jump').addEventListener('keydown',e=>{if(e.key==='Enter'){$('#more').close(); goPage($('#m-jump').value);}});

// ------------------------------------------------ Vector rendering (PDF.js) - docs/handbook/viewer.md §벡터 렌더링
// Each page draws the PDF directly onto a canvas. Backing size = page CSS size x devicePixelRatio (x the browser's pinch
// scale), and app zoom is already baked into the page CSS width (W). The page box, aspect ratio, and % coordinates stay
// exactly as they were for PNG, so drag frac/marks/pdf_build never change.
// - Only pages near the visible area (VEC_KEEP) are drawn; canvases for pages that scroll away are released (IntersectionObserver).
// - A single canvas never exceeds VEC_PIX_CAP pixels. At zoom beyond that, the page canvas is capped and a detail canvas (.dt)
//   rendered at native resolution for just the visible portion is overlaid on top.
// - When zoom changes, the existing canvas is stretched via CSS to stay visible while a debounced redraw happens (no flicker).
// - If pdf.js/the PDF fails to load or render, the canvas is torn down, falling back to the PNG <img>, and the status chip (#vec-chip) reports it.
// No text-selection layer is added - since dragging means selecting a region, it would conflict with text selection.
const PDFJS_V='__PDFJS_VERSION__';
const VEC_PIX_CAP=16777216, VEC_KEEP='150% 0px', VEC_DT_MARGIN=0.25;
const VEC={lib:null,doc:null,build:null,gen:0,failed:null,io:null,near:new Set(),st:new Map(),cur:null,
  pumping:false,timer:0,stats:[],tFirst:null,tDoc:null,cache:new Map()};
// Multiple documents: holds up to VEC_CACHE_MAX recently opened PDF document objects keyed by 'document|build' - switching tabs back
// draws immediately without re-fetching. Beyond that, the least recently used is closed first (worker memory). An old build of the same document is closed when a new build opens.
const VEC_CACHE_MAX=3;
function vecCacheKey(k,b){return (k||'')+'|'+(b||'');}
function vecCachePut(key,doc){const c=VEC.cache; c.delete(key); c.set(key,doc);
  const pre=key.split('|')[0]+'|';
  Array.from(c.keys()).forEach(x=>{if(x!==key&&x.startsWith(pre)){const d=c.get(x); c.delete(x); if(d!==VEC.doc)vecClose(d);}});
  while(c.size>VEC_CACHE_MAX){const x=c.keys().next().value,d=c.get(x); c.delete(x); if(d!==VEC.doc&&d!==doc)vecClose(d);}}
function vecCached(doc){for(const d of VEC.cache.values())if(d===doc)return true; return false;}
function vecForget(doc){VEC.cache.forEach((d,x)=>{if(d===doc)VEC.cache.delete(x);});}
window.__pinVec=VEC;   // for measurement (Playwright) - canvas count, render time
async function vecBoot(){
  if(!window.IntersectionObserver){vecFail('이 브라우저는 IntersectionObserver 가 없습니다');return;}
  try{VEC.lib=await import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V);
    VEC.lib.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V;}
  catch(e){VEC.lib=null; vecFail('pdf.js 를 불러오지 못했습니다',e); return;}
  await vecOpen();
}
// Opens the PDF for the currently displayed build (META.pages_build). Never used if the page count differs from what's on screen (coordinates would be off).
async function vecOpen(){
  if(!VEC.lib||!META)return;
  const gen=++VEC.gen, build=META.pages_build||'', n=META.pages.length, key=vecCacheKey(DOC,build); let doc=VEC.cache.get(key);
  vecCancel();
  if(!doc){
    // The old document (a different document/old build) is never used for the new page DOM - PNG is shown while fetching.
    const prev=VEC.doc; VEC.doc=null; VEC.build=null; if(prev&&!vecCached(prev))vecClose(prev);
    try{const r=await fetch(dq('/pdf?build='+encodeURIComponent(build)+'&v='+encodeURIComponent(META.built_at||'')));
      if(!r.ok)throw new Error('PDF HTTP '+r.status);
      const data=new Uint8Array(await r.arrayBuffer()); if(gen!==VEC.gen)return;
      doc=await VEC.lib.getDocument({data,isEvalSupported:false,useWasm:false,enableXfa:false}).promise;}
    catch(e){if(gen===VEC.gen)vecFail('PDF 를 벡터로 열지 못했습니다',e); return;}
    if(gen!==VEC.gen){vecClose(doc); return;}
    if(doc.numPages!==n){vecClose(doc); vecFail(tl('PDF 쪽 수({pdf})가 화면({view})과 다릅니다',{pdf:doc.numPages,view:n})); return;}
    vecCachePut(key,doc);
  }else vecCachePut(key,doc);           // promoted as most recently used
  if(gen!==VEC.gen)return;
  const old=VEC.doc; VEC.doc=doc; VEC.build=build; VEC.failed=null; VEC.tDoc=performance.now(); $('#vec-chip').hidden=true;
  loadOutline(doc,gen);
  VEC.st.forEach(s=>{s.stale=true;});
  if(old&&old!==doc&&!vecCached(old))vecClose(old);
  vecSchedule(0);
}
async function loadOutline(doc,gen){
  const box=$('#outline-items'); let entries=[];
  try{const items=await doc.getOutline();
    async function walk(rows,depth){for(const item of rows||[]){if(entries.length>=180)return;
      let dest=item.dest;
      if(typeof dest==='string')dest=await doc.getDestination(dest);
      if(Array.isArray(dest)&&dest[0]!=null){
        const page=typeof dest[0]==='number'?dest[0]+1:(await doc.getPageIndex(dest[0]))+1;
        const ptH=META&&META.pages&&META.pages[page-1]?+META.pages[page-1].pt_h:0;
        if(Number.isInteger(page)&&page>=1&&page<=doc.numPages)entries.push({title:item.title||tr('제목 없음'),page,depth,frac:destFrac(dest,ptH)});
      }
      if(depth<4)await walk(item.items,depth+1);
    }}
    await walk(items,0);
  }catch(e){entries=[];}
  if(gen!==VEC.gen||doc!==VEC.doc)return;
  if(entries.length){
    const k=DOC,build=META&&META.pages_build;
    try{const r=(await api(dq('/api/outline-labels',k),{what:'목차 번호 읽기',silent:true})).data;
      if(gen===VEC.gen&&doc===VEC.doc&&k===DOC&&build===META.pages_build&&r.build===build)
        entries=mergeOutlineLabels(entries,r.labels||[]);
    }catch(e){} // the PDF's own outline is still usable even if the numbering service can't be reached.
  }
  if(gen!==VEC.gen||doc!==VEC.doc)return;
  OUTLINE_ENTRIES=entries;OUTLINE_SELECTED=-1;OUTLINE_ACTIVE_PAGE=0;OUTLINE_PINNED=null;
  renderOutline();updateSectionStrip();
}
function mergeOutlineLabels(entries,labels){
  const norm=s=>String(s||'').normalize('NFKC').replace(/\s+/g,' ').trim().toLowerCase();
  const levels=['section','subsection','subsubsection','paragraph','subparagraph'];
  const depthGuard=labels.some(l=>l.level==='section'&&entries.some(e=>e.depth===0&&norm(e.title)===norm(l.title)));
  let cursor=0;
  return entries.map(entry=>{
    const title=norm(entry.title);let matched=null;
    if(title)for(let i=cursor;i<labels.length;i++){
      const label=labels[i];if(norm(label.title)!==title)continue;
      if(/^\d+$/.test(String(label.page||''))&&Number(label.page)!==entry.page)continue;
      if(depthGuard&&levels.includes(label.level)&&levels.indexOf(label.level)!==entry.depth)continue;
      matched=label;cursor=i+1;break;
    }
    return Object.assign({},entry,{number:matched?String(matched.number||''):'',
      pageLabel:matched?String(matched.page||''):''});
  });
}
let OUTLINE_ENTRIES=[],OUTLINE_SELECTED=-1,OUTLINE_ACTIVE_PAGE=0;
function renderOutline(){
  const box=$('#outline-items'),query=$('#outline-search').value.trim().toLowerCase();
  if(!OUTLINE_ENTRIES.length){box.className='outline-empty';box.textContent='이 PDF에는 이동할 수 있는 목차가 없습니다.';return;}
  const rows=OUTLINE_ENTRIES.map((x,i)=>Object.assign({index:i},x)).filter(x=>!query||(x.number+' '+x.title).toLowerCase().includes(query));
  if(!rows.length){box.className='outline-empty';box.textContent='찾은 장·절이 없습니다.';return;}
  box.className='';box.innerHTML=rows.map(x=>'<button class="ol-depth-'+Math.min(x.depth,4)+(x.index===OUTLINE_SELECTED?' ol-active':'')+'" data-act="outline-page" data-index="'+x.index+'" data-page="'+x.page+'" aria-current="'+(x.index===OUTLINE_SELECTED?'location':'false')+'" title="'+esc(x.title)+'"><span class="ol-no">'+esc(x.number||'·')+'</span><span class="ol-name">'+esc(x.title)+'</span><span class="ol-page">'+esc(tl('{page}쪽',{page:x.pageLabel||String(x.page)}))+'</span></button>').join('');
}
// Where a PDF outline destination sits on its page, as a fraction from the top (0 = top). An XYZ destination carries
// the top edge in PDF points from the bottom; anything else (Fit, no top) counts as the top of the page.
function destFrac(dest,ptH){const top=Array.isArray(dest)&&dest[1]&&dest[1].name==='XYZ'?dest[3]:null;
  if(typeof top!=='number'||!(ptH>0))return 0; return Math.min(1,Math.max(0,1-top/ptH));}
// The outline entry the reader is in at (page, frac): the last heading that starts at or above that point. Before the
// first heading (a title page, the top of page 1) it is the first entry - never a later heading on the same page
// (v0.2.0 showed "1.2" at the very top of page 1, because 1, 1.1 and 1.2 all start on page 1). -1 without entries.
function outlineIndexAt(entries,page,frac){let sel=-1;
  for(let i=0;i<entries.length;i++){const e=entries[i]; if(e.page<page||(e.page===page&&(e.frac||0)<=frac+1e-6))sel=i;}
  return sel<0&&entries.length?0:sel;}
let OUTLINE_PINNED=null;   // an entry picked in the outline wins until the reader leaves its page
function updateSectionStrip(){
  const L=$('#left'),probe=L?Math.min(160,L.clientHeight/4):0,anchor=topAnchor(probe),page=anchor?anchor.page:1,frac=anchor?anchor.frac:0;
  let sel;
  if(OUTLINE_PINNED&&OUTLINE_PINNED.page===page)sel=OUTLINE_PINNED.index;
  else{OUTLINE_PINNED=null; sel=outlineIndexAt(OUTLINE_ENTRIES,page,frac);}
  if(sel!==OUTLINE_SELECTED||page!==OUTLINE_ACTIVE_PAGE){OUTLINE_ACTIVE_PAGE=page;OUTLINE_SELECTED=sel;renderOutline();}
  const x=OUTLINE_ENTRIES[OUTLINE_SELECTED];$('#section-current').textContent=x?(x.number?x.number+'  ':'')+x.title:tr('원고');
  $('#section-page').textContent=tl('{page} / {n}쪽',{page,n:META&&META.pages?META.pages.length:0});
}
$('#outline-search').addEventListener('input',renderOutline);
$('#left').addEventListener('scroll',()=>{if(!document.body.classList.contains('revision-open'))requestAnimationFrame(updateSectionStrip);},{passive:true});
// Closes one document - PDFDocumentProxy has no destroy of its own; loadingTask frees the worker-side resources too.
function vecClose(doc){if(!doc)return; try{doc.loadingTask.destroy();}catch(e){}}
function vecFail(msg,err){
  VEC.failed=msg; VEC.gen++; vecCancel(); vecReleaseAll();
  vecForget(VEC.doc); vecClose(VEC.doc); VEC.doc=null;
  const c=$('#vec-chip'); c.hidden=false;
  c.dataset.tip=tl('PDF를 벡터로 그리지 못해 이미지(PNG)로 보입니다 — {reason}. 확대하면 흐릴 수 있습니다',{reason:tr(msg)+(err&&err.message?' ('+String(err.message).slice(0,100)+')':'')});
}
function vecState(n){let s=VEC.st.get(n); if(!s){s={base:null,bw:0,bh:0,dt:null,reg:null,dtCw:0,dtK:0,stale:false}; VEC.st.set(n,s);} return s;}
function vecDrop(cv){if(!cv)return; cv.width=0; cv.height=0; cv.remove();}   // must shrink to 0 for Safari to release memory right away too
function vecRelease(n){if(VEC.cur&&VEC.cur.n===n)vecCancel(); const s=VEC.st.get(n); if(!s)return;
  vecDrop(s.base); vecDrop(s.dt); VEC.st.delete(n);
  const pg=document.getElementById('p'+n); if(pg)pg.classList.remove('drawn');}
function vecReleaseAll(){vecCancel(); Array.from(VEC.st.keys()).forEach(vecRelease);}
function vecCancel(){const c=VEC.cur; VEC.cur=null; if(c&&c.task){try{c.task.cancel();}catch(e){}}}
function vecObserve(){if(VEC.io)VEC.io.disconnect(); vecReleaseAll(); VEC.near.clear(); if(!window.IntersectionObserver)return;
  VEC.io=new IntersectionObserver(es=>{es.forEach(en=>{const n=+en.target.dataset.page;
      if(en.isIntersecting)VEC.near.add(n); else {VEC.near.delete(n); vecRelease(n);}}); vecSchedule(0);},
    {root:$('#left'),rootMargin:VEC_KEEP});
  $$('.pg').forEach(pg=>VEC.io.observe(pg));}
function vecSchedule(ms){clearTimeout(VEC.timer); VEC.timer=setTimeout(vecPump,ms||0);}
// Zoom, window size, or DPR changed - whatever was being drawn (the old size) is discarded and redrawn shortly after. Meanwhile, the old canvas is shown stretched.
function vecInvalidate(){if(!VEC.doc)return; vecCancel(); vecSchedule(150);}
function vecK(){const vv=window.visualViewport; return (window.devicePixelRatio||1)*Math.max(1,(vv&&vv.scale)||1);}
// The page canvas's backing size. If it exceeds the cap, it's scaled down proportionally and marked capped (the detail canvas fills in the visible portion).
function vecTarget(cw,ch,k,cap){let bw=Math.round(cw*k),bh=Math.round(ch*k),capped=false;
  if(bw*bh>cap){const f=Math.sqrt(cap/(bw*bh)); bw=Math.max(1,Math.floor(bw*f)); bh=Math.max(1,Math.floor(bh*f)); capped=true;}
  return {cw,ch,k,bw,bh,capped};}
function vecTargetOf(pg){const cw=pg.clientWidth,ch=pg.clientHeight; return cw&&ch?vecTarget(cw,ch,vecK(),VEC_PIX_CAP):null;}
// The portion of a page visible on screen (page CSS px). margin is extra room relative to the viewport size (the detail canvas is drawn a bit larger).
function vecVisible(pg,margin){const L=$('#left'),lr=L.getBoundingClientRect(),r=pg.getBoundingClientRect();
  const ox=r.left+pg.clientLeft,oy=r.top+pg.clientTop,cw=pg.clientWidth,ch=pg.clientHeight;
  const vx0=lr.left+L.clientLeft,vy0=lr.top+L.clientTop,vw=L.clientWidth,vh=L.clientHeight,mx=vw*margin,my=vh*margin;
  const x0=Math.max(0,vx0-mx-ox),y0=Math.max(0,vy0-my-oy),x1=Math.min(cw,vx0+vw+mx-ox),y1=Math.min(ch,vy0+vh+my-oy);
  return x1>x0&&y1>y0?{x:x0,y:y0,w:x1-x0,h:y1-y0,cw,ch}:null;}
function vecCovers(reg,v){return !!reg&&reg.x<=v.x/v.cw+1e-6&&reg.y<=v.y/v.ch+1e-6&&
  reg.x+reg.w>=(v.x+v.w)/v.cw-1e-6&&reg.y+reg.h>=(v.y+v.h)/v.ch-1e-6;}
// The one thing to draw next: pages within the viewport first (nearest to center), page canvas before detail canvas.
function vecNextJob(){
  if(!VEC.doc)return null;
  const L=$('#left'),lr=L.getBoundingClientRect(),top=lr.top,bot=lr.top+L.clientHeight,cy=(top+bot)/2;
  const list=[];
  VEC.near.forEach(n=>{const pg=document.getElementById('p'+n); if(!pg)return; const r=pg.getBoundingClientRect();
    list.push({n,pg,vis:r.bottom>top&&r.top<bot,d:Math.abs((r.top+r.bottom)/2-cy)});});
  list.sort((a,b)=>(b.vis-a.vis)||(a.d-b.d));
  for(const it of list){const s=vecState(it.n),t=vecTargetOf(it.pg); if(!t)continue;
    if(!s.base||s.stale||s.bw!==t.bw||s.bh!==t.bh)return {n:it.n,kind:'base'};
    if(t.capped&&it.vis){const v=vecVisible(it.pg,0);
      if(v&&(!s.dt||s.dtCw!==t.cw||s.dtK!==t.k||!vecCovers(s.reg,v)))return {n:it.n,kind:'dt'};}
    else if(s.dt){vecDrop(s.dt); s.dt=null; s.reg=null;}}
  return null;
}
async function vecPump(){
  if(VEC.pumping||!VEC.doc)return; VEC.pumping=true;
  try{for(let i=0;i<400;i++){const job=vecNextJob(); if(!job)break; await vecRun(job);}}
  finally{VEC.pumping=false;}
}
async function vecRun(job){
  const n=job.n,pg=document.getElementById('p'+n),doc=VEC.doc,gen=VEC.gen; if(!pg||!doc)return;
  if(n>doc.numPages)return;   // a defensive check - just skips a case where another document/build's doc ends up running on a new n (the vecOpen bailout above is the real fix)
  let page; try{page=await doc.getPage(n);}catch(e){if(gen===VEC.gen)vecFail('쪽을 읽지 못했습니다',e); return;}
  if(gen!==VEC.gen||!VEC.near.has(n)||!document.contains(pg))return;
  const t=vecTargetOf(pg); if(!t)return;
  const vp1=page.getViewport({scale:1}),cv=document.createElement('canvas'); let scale,tf,reg=null;
  // Width and height are fit independently (the transform's vertical scale) - the page box's aspect ratio comes from
  // the PNG pixel dimensions and differs from the PDF page's aspect ratio by less than 0.1%. Since PNG was also drawn
  // filling that same box, this is needed for the canvas's text to land at the same % position it did for PNG.
  if(job.kind==='base'){cv.width=t.bw; cv.height=t.bh; scale=t.bw/vp1.width; tf=[1,0,0,t.bh/(vp1.height*scale),0,0];}
  else{const v=vecVisible(pg,VEC_DT_MARGIN); if(!v)return; let k=t.k;
    if(v.w*v.h*k*k>VEC_PIX_CAP)k=Math.sqrt(VEC_PIX_CAP/(v.w*v.h));
    scale=t.cw*k/vp1.width; cv.width=Math.max(1,Math.round(v.w*k)); cv.height=Math.max(1,Math.round(v.h*k));
    tf=[1,0,0,t.ch*k/(vp1.height*scale),-v.x*k,-v.y*k];
    reg={x:v.x/t.cw,y:v.y/t.ch,w:v.w/t.cw,h:v.h/t.ch};}
  const ctx=cv.getContext('2d',{alpha:false}),t0=performance.now();
  const task=page.render({canvasContext:ctx,viewport:page.getViewport({scale}),transform:tf});
  VEC.cur={n,task};
  try{await task.promise;}
  catch(e){if(VEC.cur&&VEC.cur.task===task)VEC.cur=null; vecDrop(cv);
    if(e&&e.name==='RenderingCancelledException')return;
    if(gen===VEC.gen)vecFail('쪽을 그리지 못했습니다',e); return;}
  if(VEC.cur&&VEC.cur.task===task)VEC.cur=null;
  const t2=gen===VEC.gen&&VEC.near.has(n)&&document.contains(pg)?vecTargetOf(pg):null;
  if(!t2||t2.cw!==t.cw||t2.ch!==t.ch||t2.k!==t.k){vecDrop(cv); return;}   // zoom or window size changed while drawing
  VEC.stats.push({n,kind:job.kind,ms:Math.round(performance.now()-t0),w:cv.width,h:cv.height});
  if(VEC.stats.length>200)VEC.stats.splice(0,VEC.stats.length-200);
  const s=vecState(n);
  if(job.kind==='base'){vecDrop(s.base); s.base=cv; s.bw=t.bw; s.bh=t.bh; s.stale=false; cv.className='vb';
    pg.prepend(cv); pg.classList.add('drawn'); if(VEC.tFirst===null)VEC.tFirst=performance.now();}
  else{vecDrop(s.dt); s.dt=cv; s.reg=reg; s.dtCw=t.cw; s.dtK=t.k; cv.className='dt';
    Object.assign(cv.style,{left:reg.x*100+'%',top:reg.y*100+'%',width:reg.w*100+'%',height:reg.h*100+'%'});
    if(s.base)s.base.after(cv); else pg.prepend(cv);}
}
$('#left').addEventListener('scroll',()=>{if(VEC.doc)vecSchedule(120);},{passive:true});
// devicePixelRatio changes with browser zoom (Ctrl+wheel outside the PDF, etc.) or moving the window to a different screen - redraws at that scale.
(function watchDpr(){if(!window.matchMedia)return;
  matchMedia('(resolution: '+(window.devicePixelRatio||1)+'dppx)').addEventListener('change',()=>{vecInvalidate(); watchDpr();},{once:true});})();
if(window.visualViewport)visualViewport.addEventListener('resize',()=>{if(VEC.doc)vecSchedule(300);});

// ------------------------------------------------ PDF-area-only zoom - docs/handbook/viewer.md §PDF 영역 전용 확대
// Browser zoom would also enlarge the sidebar and tool bar. Zoom input over the PDF area is intercepted to change only the page width (W).
// - Desktop: Ctrl(Cmd)+wheel over #left. Trackpad pinch also arrives as a wheel event with ctrlKey set, in Chrome/Firefox. Anchored to the pointer.
// - Safari trackpad pinch: gesturestart/gesturechange (e.scale).
// - Keyboard Ctrl(Cmd) + = / + / - / 0 -> zoom in/out/fit width (never intercepted while an input field has focus - see the key handler).
// - Touch: #left has touch-action:pan-x pan-y, so there's no browser pinch. W changes with the ratio of the two-finger distance, and the
//   point under the midpoint of the two fingers follows the fingers (drag while zooming). A page in selection mode has touch-action:none, so it goes through the same path.
function zoomKey(e){const k=e.key,c=e.code;
  if(k==='='||k==='+'||c==='Equal'||c==='NumpadAdd')return 'in';
  if(k==='-'||k==='_'||c==='Minus'||c==='NumpadSubtract')return 'out';
  if(k==='0'||c==='Digit0'||c==='Numpad0')return 'fit';
  return null;}
// The factor for one wheel tick. One mouse-wheel notch (|dy|>=50 pixels or a line unit) gets the same ZOOM_STEP as one button
// press; a trackpad pinch's finely divided dy is composed via exp(-dy/100) - the inverse of the formula Chrome uses to turn
// pinch scale into wheel events, so it grows in proportion to how far the fingers spread. dy is clamped to +-18 so a single
// event never exceeds one button press's worth (ZOOM_STEP ~ exp(0.18)).
function wheelFactor(dy,mode){if(!dy)return 1;
  if(mode===1||mode===2||Math.abs(dy)>=50)return dy<0?ZOOM_STEP:1/ZOOM_STEP;
  return Math.exp(-Math.max(-18,Math.min(18,dy))/100);}
(function(){const L=$('#left'); let acc=1,pt=null,raf=0,G=null,TP=null;
  const flush=()=>{raf=0; if(acc===1)return; const f=acc; acc=1; zoomTo(W*f,pt[0],pt[1]);};
  L.addEventListener('wheel',e=>{if(!(e.ctrlKey||e.metaKey))return; e.preventDefault();
    acc*=wheelFactor(e.deltaY,e.deltaMode); pt=[e.clientX,e.clientY]; if(!raf)raf=requestAnimationFrame(flush);},{passive:false});
  L.addEventListener('gesturestart',e=>{e.preventDefault(); if(!TP)G={w:W};},{passive:false});
  L.addEventListener('gesturechange',e=>{e.preventDefault(); if(G&&!TP&&e.scale>0)zoomTo(G.w*e.scale,e.clientX,e.clientY);},{passive:false});
  L.addEventListener('gestureend',e=>{e.preventDefault(); G=null;},{passive:false});
  const mid=(a,b)=>[(a.clientX+b.clientX)/2,(a.clientY+b.clientY)/2];
  const dist=(a,b)=>Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY)||1;
  let tr=0,last=null;
  const apply=()=>{tr=0; if(!TP||!last)return; const w=TP.w*last.d/TP.d;
    setW(w); if(LAYOUT!=='wide')ZOOMED=true; zoomRestore(TP.a,last.m[0],last.m[1]);};
  L.addEventListener('touchstart',e=>{if(e.touches.length!==2){if(e.touches.length>2)TP=null; return;}
    if(e.cancelable)e.preventDefault();
    const a=e.touches[0],b=e.touches[1],m=mid(a,b); cancelDrag(); cancelLP();
    TP={d:dist(a,b),w:W,a:zoomAnchor(m[0],m[1])}; last={d:TP.d,m};},{passive:false});
  L.addEventListener('touchmove',e=>{if(!TP||e.touches.length!==2)return; if(e.cancelable)e.preventDefault();
    const a=e.touches[0],b=e.touches[1]; last={d:dist(a,b),m:mid(a,b)}; if(!tr)tr=requestAnimationFrame(apply);},{passive:false});
  const end=e=>{if(TP&&e.touches.length<2){if(tr){cancelAnimationFrame(tr); apply();} TP=null; last=null;}};
  L.addEventListener('touchend',end); L.addEventListener('touchcancel',end);
})();

// ------------------------------------------------ Layout by screen width (mobile)
// wide: 1100px and up, a right sidebar (width-adjustable). mid: over 700px, under 1100px - a narrow side
// panel; when collapsed, only the bottom-right tool bar remains. narrow: 700px and below (a folded foldable/phone) -
// a bottom sheet, collapsed by default. If the width changes partway through a collapse/expand, the layout is re-chosen
// and the page width is re-fit while preserving the viewed position (topAnchor). Marks and the selection box are % coordinates within the page, so they fall back into place automatically once the page width is fit.
function layoutFor(){const w=innerWidth; if(w<=700)return 'narrow'; if(w<1100)return 'mid'; return 'wide';}
function applyLayout(){const L=layoutFor(),overlay=L==='mid'&&innerWidth<=900; if(L===LAYOUT&&overlay===MID_OVERLAY)return false;
  LAYOUT=L; MID_OVERLAY=overlay; OUTLINE_MID_OPEN=false; const b=document.body,p=prefs(); ZOOMED=false;
  ['wide','mid','narrow'].forEach(k=>b.classList.toggle('lay-'+k,k===L)); b.classList.toggle('compact',L!=='wide');
  SIDE_OPEN=L==='wide'?true:(L==='mid'?(typeof p.midClosed==='boolean'?!p.midClosed:!overlay):false);
  if(L!=='wide'&&!REPICK&&(CUR||EDIT||!$('#composer').hidden))SIDE_OPEN=true;   // an in-progress note/edit is never left hidden collapsed
  applySide(); stickTop(); return true;}
function applySide(){const open=LAYOUT==='wide'||SIDE_OPEN;
  document.body.classList.toggle('side-open',open);
  const btn=$('#btn-side'); btn.setAttribute('aria-expanded',String(open));
  $('#side-arrow').innerHTML=ic(LAYOUT==='narrow'?(open?'chevron-down':'chevron-up'):(open?'chevron-right':'chevron-left'));
  btn.setAttribute('aria-label',tr(open?'패널 접기':'패널 펴기')+' · '+tl('열린 핀 {n}',{n:PINS.length}));}
// remember: only remembers a manual collapse/expand by the user in mid (narrow always starts collapsed).
function setSide(open,remember){if(LAYOUT==='wide')return; open=!!open;
  if(open&&LAYOUT==='mid'){OUTLINE_MID_OPEN=false;applyOutlineState();}
  if(remember&&LAYOUT==='mid')savePrefs({midClosed:!open});
  if(SIDE_OPEN===open)return; SIDE_OPEN=open; applySide(); hideTip();}
function relayout(){const a=topAnchor(); applyLayout(); applySideWidth(); applyOutlineState();autoW(); restoreAnchor(a); hideTip(); if(CUR)renderComposer(); stickTop();updateSectionStrip();}
// The height a list section header (sticky) sticks below. In compact, #right is the scroll box and the tool bar (#bar1, below the
// sheet handle in narrow) is already stuck above it, so the header sticks below that. In wide, #list itself is the scroll box, so this is 0.
function stickTop(){let t=0; const b=$('#bar1');
  if(LAYOUT!=='wide'&&b){const cs=getComputedStyle(b); if(cs.position==='sticky')t=Math.round((parseFloat(cs.top)||0)+b.offsetHeight);}
  document.documentElement.style.setProperty('--stick-top',t+'px');}
if(window.ResizeObserver)new ResizeObserver(()=>stickTop()).observe($('#bar1'));
let RELAY=0;
function scheduleRelayout(){if(RELAY)return; RELAY=requestAnimationFrame(()=>{RELAY=0; if(META)relayout(); else applyLayout();});}
window.addEventListener('resize',scheduleRelayout);
MQ_COARSE.addEventListener('change',scheduleRelayout);
// Even a mere #left width change from expanding/collapsing the panel (compact) re-fits the page width. The layout is never
// changed directly in the callback - it's deferred to the next frame (avoids a ResizeObserver loop warning). wide still only reacts to window-size changes, as before.
// Never re-fit while the handle is being dragged (body.resizing) - setSideWidth fits it once on release.
if(window.ResizeObserver)new ResizeObserver(()=>{if(LAYOUT&&LAYOUT!=='wide'&&!document.body.classList.contains('resizing'))scheduleRelayout();}).observe($('#left'));

// Virtual keyboard: on Chrome Android, the layout itself shrinks via the viewport meta's interactive-widget=resizes-content.
// A browser that doesn't understand that value instead measures the keyboard height (--kb) via visualViewport and raises the
// whole screen by that amount. A visualViewport shrunk by pinch zoom is not the keyboard (undone by multiplying by scale).
// If an input field has focus, it's scrolled into view.
function onViewport(){const vv=window.visualViewport; if(!vv)return;
  const lh=document.documentElement.clientHeight;
  let kb=Math.round(lh-vv.height*vv.scale); if(!(kb>=80)||!MQ_COARSE.matches)kb=0;
  const R=document.documentElement.style, prev=R.getPropertyValue('--kb');
  R.setProperty('--kb',kb+'px'); R.setProperty('--vvh',(lh-kb)+'px');
  const a=document.activeElement;
  if(prev!==kb+'px'&&a&&(a.tagName==='TEXTAREA'||a.tagName==='INPUT')&&$('#right').contains(a))
    requestAnimationFrame(()=>a.scrollIntoView({block:'center'}));}
if(window.visualViewport){visualViewport.addEventListener('resize',onViewport); visualViewport.addEventListener('scroll',onViewport);}
document.addEventListener('focusin',e=>{const t=e.target;
  if(LAYOUT!=='wide'&&t&&t.tagName==='TEXTAREA'&&$('#right').contains(t))setTimeout(()=>t.scrollIntoView({block:'center'}),350);});

// Onboarding shown only the first time (remembers that it's been seen in localStorage pinPrefs.coach).
let COACH_T=null;
function coach(key,text){const seen=Object.assign({},prefs().coach||{}); if(seen[key])return; seen[key]=1; savePrefs({coach:seen});
  $('#coach-t').textContent=text; $('#coach').hidden=false; clearTimeout(COACH_T); COACH_T=setTimeout(()=>{$('#coach').hidden=true;},8000);}
function setSelMode(on){SELMODE=!!on; document.body.classList.toggle('selmode',SELMODE);
  const b=$('#btn-select'); b.setAttribute('aria-pressed',String(SELMODE)); b.querySelector('.lbl').textContent=SELMODE?'선택 중':'선택';
  if(SELMODE)coach('sel','끌어서 고칠 곳을 고르세요 · 탭하면 그 문단 · 두 손가락으로 확대');}
function openMore(){const d=$('#more'); if(d.open)return; hideTip(); renderSizeSeg(); d.showModal(); toastHost();}
// Expanding done/dropped pins from [⋯] opens the panel and scrolls to that list.
function revealList(sel,shown){if(!shown)return; setSide(true); requestAnimationFrame(()=>{const t=$(sel); if(t)t.scrollIntoView({block:'start'});});}
// Clicking outside a dialog (the backdrop) closes it - only for a click whose target is the dialog itself and that falls outside its box rectangle.
$('#more').addEventListener('click',e=>{const d=$('#more'); if(e.target!==d)return; const r=d.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});

// Panel width handle - mouse/touch/pen all share one Pointer Events path (replacing the old desktop-only mousedown
// implementation). The handle has touch-action:none, so dragging it never fights browser scrolling, and
// setPointerCapture keeps tracking it even outside the handle. While dragging, only the width changes (the body's
// page width stays put); relayout runs once on release. A tap (double-click for mouse) cycles presets, Left/Right moves
// 16px, Home/End go to the limits, and Enter/Space cycles presets.
(function(){const g=$('#grip'); let D=null;
  g.addEventListener('pointerdown',e=>{if(LAYOUT==='narrow'||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault(); D={id:e.pointerId,x:e.clientX,w:curSideW(),moved:false,mouse:e.pointerType==='mouse'};
    try{g.setPointerCapture(e.pointerId);}catch(_){}
    g.classList.add('on'); document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(!D||e.pointerId!==D.id)return; const dx=D.x-e.clientX;
    if(!D.moved&&Math.abs(dx)<4)return; D.moved=true; const b=sideBounds(LAYOUT,innerWidth); showSideW(clampSide(D.w+dx,b),b);});
  const end=e=>{if(!D||e.pointerId!==D.id)return; const d=D; D=null; g.classList.remove('on'); document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){applySideWidth(); relayout(); return;}
    if(d.moved)setSideWidth(curSideW()); else if(!d.mouse&&Date.now()>=SWALLOW_CLICK)cycleSideWidth();};
  g.addEventListener('pointerup',end); g.addEventListener('pointercancel',end);
  g.addEventListener('dblclick',()=>cycleSideWidth());
  g.addEventListener('keydown',e=>{if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth),w=curSideW();
    const k={ArrowLeft:w+16,ArrowRight:w-16,Home:b.max,End:b.min}[e.key];
    if(k!==undefined){e.preventDefault(); setSideWidth(k);} else if(e.key==='Enter'||e.key===' '){e.preventDefault(); cycleSideWidth();}});
})();
// Outline width is independent of the right work panel's handle. While dragging, only the width changes; the PDF position is restored when it ends.
(function(){const g=$('#outline-grip');let D=null;
  g.addEventListener('pointerdown',e=>{if(LAYOUT==='narrow'||document.body.classList.contains('outline-collapsed')||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault();D={id:e.pointerId,x:e.clientX,w:Math.round($('#outline').getBoundingClientRect().width)};
    try{g.setPointerCapture(e.pointerId);}catch(_){}g.classList.add('on');document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(D&&e.pointerId===D.id)showOutlineWidth(D.w+e.clientX-D.x);});
  const end=e=>{if(!D||e.pointerId!==D.id)return;D=null;g.classList.remove('on');document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){applyOutlineState();relayout();}else setOutlineWidth($('#outline').getBoundingClientRect().width);};
  g.addEventListener('pointerup',end);g.addEventListener('pointercancel',end);
  g.addEventListener('keydown',e=>{if(LAYOUT==='narrow')return;const b=outlineBounds(),w=Math.round($('#outline').getBoundingClientRect().width);
    const next={ArrowLeft:w-16,ArrowRight:w+16,Home:b.min,End:b.max}[e.key];
    if(next!==undefined){e.preventDefault();setOutlineWidth(next);}});
})();
// Sheet height handle (narrow) - dragging up raises it (a collapsed sheet expands); dropping it below 25% of the screen collapses it. A tap cycles presets.
(function(){const g=$('#sheet-grip'); let D=null;
  g.addEventListener('pointerdown',e=>{if(LAYOUT!=='narrow'||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault(); D={id:e.pointerId,y:e.clientY,h:$('#right').getBoundingClientRect().height,moved:false};
    try{g.setPointerCapture(e.pointerId);}catch(_){}
    g.classList.add('on'); document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(!D||e.pointerId!==D.id)return; const dy=D.y-e.clientY;
    if(!D.moved&&Math.abs(dy)<6)return; D.moved=true;
    if(!SIDE_OPEN&&dy>0)setSide(true);
    if(SIDE_OPEN)document.documentElement.style.setProperty('--sheet-f',String(Math.max(0.12,(D.h+dy)/innerHeight)));});
  const end=e=>{if(!D||e.pointerId!==D.id)return; const d=D; D=null; g.classList.remove('on'); document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){applySheet(); return;}
    if(!d.moved){if(Date.now()<SWALLOW_CLICK)return; if(!SIDE_OPEN)setSide(true,true); else cycleSheet(); return;}
    if(!SIDE_OPEN){applySheet(); return;}
    const f=$('#right').getBoundingClientRect().height/innerHeight;
    if(f<SHEET_CLOSE_F){applySheet(); setSide(false,true); return;}
    setSheetF(f);};
  g.addEventListener('pointerup',end); g.addEventListener('pointercancel',end);
  g.addEventListener('keydown',e=>{if(LAYOUT!=='narrow')return; const f=sheetF();
    if(e.key==='ArrowUp'){e.preventDefault(); setSheetF(f+0.05);} else if(e.key==='ArrowDown'){e.preventDefault(); setSheetF(f-0.05);}
    else if(e.key==='Enter'||e.key===' '){e.preventDefault(); cycleSheet();}});
})();

// ------------------------------------------------ Drag selection (mouse/touch/pen - one Pointer Events path)
// Mouse: press and drag draws a rectangle, as before. Touch/pen: a drag draws a rectangle only in selection mode
// (SELMODE), and a tap does quick selection; outside selection mode, scroll/pinch zoom work as usual and a
// long-press does quick selection. Only pages get touch-action:none in selection mode (a one-finger drag is
// handled by this code, two fingers by the app zoom - §PDF 영역 전용 확대).
// Coordinates are computed as fractions within the page from clientX/Y and getBoundingClientRect on the same
// basis (the layout viewport), so they stay correct even during a pinch zoom.
let DRAG=null,LP=null;
const c01=v=>Math.min(1,Math.max(0,v));
const LONGPRESS_MS=450,TAP_SLOP=8,QUICK_W=0.07,QUICK_H=0.006;
function fracAt(pg,cx,cy){const r=pg.getBoundingClientRect(); return [c01((cx-r.left)/r.width),c01((cy-r.top)/r.height)];}
function newBox(pg){const b=document.createElement('div'); b.className='sel'; pg.appendChild(b); return b;}
function drawBox(box,sx,sy,x,y){Object.assign(box.style,{left:Math.min(sx,x)*100+'%',top:Math.min(sy,y)*100+'%',
  width:Math.abs(x-sx)*100+'%',height:Math.abs(y-sy)*100+'%'});}
function cancelDrag(){if(DRAG&&DRAG.box)DRAG.box.remove(); DRAG=null;}
function cancelLP(){if(LP){clearTimeout(LP.t); LP=null;}}
// Prevents the default behavior of a mouse press on a page (focus shift, image dragging), as the old mousedown did - the note field's focus is preserved.
$('#doc').addEventListener('mousedown',e=>{if(e.button===0&&e.target.closest('.pg'))e.preventDefault();});
$('#doc').addEventListener('pointerdown',e=>{
  if(e.target.closest('.mark b'))return;
  if(!e.isPrimary){cancelDrag(); cancelLP(); return;}   // a second finger = a pinch - the box being drawn is discarded
  const pg=e.target.closest('.pg'); if(!pg)return;
  const mouse=e.pointerType==='mouse';
  if(mouse&&e.button!==0)return;
  if(mouse||SELMODE){const [sx,sy]=fracAt(pg,e.clientX,e.clientY);
    DRAG={pg,sx,sy,id:e.pointerId,mouse,cx:e.clientX,cy:e.clientY,box:mouse?newBox(pg):null};
    if(!mouse){try{pg.setPointerCapture(e.pointerId);}catch(_){}}
    return;}
  cancelLP();
  LP={id:e.pointerId,pg,cx:e.clientX,cy:e.clientY,t:setTimeout(()=>{const L=LP; LP=null; if(L)quickPick(L.pg,L.cx,L.cy);},LONGPRESS_MS)};
});
window.addEventListener('pointermove',e=>{
  if(LP&&e.pointerId===LP.id&&Math.hypot(e.clientX-LP.cx,e.clientY-LP.cy)>10)cancelLP();
  if(!DRAG||e.pointerId!==DRAG.id)return;
  if(!DRAG.box){if(Math.hypot(e.clientX-DRAG.cx,e.clientY-DRAG.cy)<TAP_SLOP)return; DRAG.box=newBox(DRAG.pg);}
  const [x,y]=fracAt(DRAG.pg,e.clientX,e.clientY); drawBox(DRAG.box,DRAG.sx,DRAG.sy,x,y);});
window.addEventListener('pointerup',e=>{
  if(LP&&e.pointerId===LP.id)cancelLP();
  if(!DRAG||e.pointerId!==DRAG.id)return;
  const D=DRAG; DRAG=null;
  if(!D.box){quickPick(D.pg,e.clientX,e.clientY);return;}   // a tap in selection mode = quick selection
  const [x,y]=fracAt(D.pg,e.clientX,e.clientY); finishRect(D.pg,D.box,D.sx,D.sy,x,y);});
window.addEventListener('pointercancel',e=>{if(LP&&e.pointerId===LP.id)cancelLP(); if(DRAG&&e.pointerId===DRAG.id)cancelDrag();});
// Quick selection: calls the existing /api/pick with a small box around the pressed point (page width +-7%, height
// +-0.6% ~ one line). The server's default level is used as-is - 'paragraph' in body text, 'environment' inside a
// figure/table - and then widened or narrowed via the range ladder.
function quickPick(pg,cx,cy){const [x,y]=fracAt(pg,cx,cy);
  finishRect(pg,newBox(pg),c01(x-QUICK_W),c01(y-QUICK_H),c01(x+QUICK_W),c01(y+QUICK_H));}
function finishRect(pg,box,sx,sy,x,y){
  const w=Math.abs(x-sx),h=Math.abs(y-sy);
  if(w<0.004&&h<0.004){box.remove();return;}
  drawBox(box,sx,sy,x,y);
  box.classList.add('pending');
  if(REPICK){ if(REPICK.box)REPICK.box.remove(); REPICK.box=box; box.innerHTML='<i>새 위치</i>'; }
  else { if(PENDING)PENDING.remove(); PENDING=box; box.innerHTML='<i>새 핀</i>'; }
  const page=+pg.dataset.page,p=META.pages[page-1];
  pick({page,x0:Math.min(sx,x)*p.pt_w,y0:Math.min(sy,y)*p.pt_h,x1:Math.max(sx,x)*p.pt_w,y1:Math.max(sy,y)*p.pt_h,
    frac:[Math.min(sx,x),Math.min(sy,y),w,h],pdf_build:META.pages_build||undefined,doc:DOC||undefined});}
// If the sheet/panel covers the selection box, the body scrolls up until the box is visible (compact only).
function revealBox(box){if(!box||LAYOUT==='wide'||!document.contains(box))return;
  const L=$('#left'),lr=L.getBoundingClientRect(),br=box.getBoundingClientRect();
  let bottom=lr.bottom; if(LAYOUT==='narrow'&&SIDE_OPEN)bottom=Math.min(bottom,$('#right').getBoundingClientRect().top);
  const top=lr.top+28; if(br.top>=top&&br.bottom<=bottom-8)return;
  L.scrollTop+=br.top-top-Math.max(0,(bottom-top-br.height)/3);}

// ------------------------------------------------ Range levels
function lvOf(obj,key){return (obj.levels||[]).find(l=>l.level===key||(l.merged||[]).includes(key));}
function kindFor(scope,env){if(!scope)return null; if(scope.startsWith('env'))return 'env:'+(env||'?');
  return scope==='para'?'paragraph':'lines';}
function scopeLabel(o){const lv=o.scope&&lvOf(o,o.scope); if(lv)return levelLabel(lv.label); if(o.scope==='lines')return tr('줄 직접 지정');
  return tr(({float:'그림/표',block:'환경 블록',paragraph:'문단',none:'생성 파일',lines:'줄'})[o.kind]||o.kind||'');}
// Range-level labels come from the server in Korean ('드래그한 줄', '문단', '환경 table', '환경 table (바깥)').
function levelLabel(s){s=String(s||''); if(LANG!=='en')return s; const m=/^환경 (.+?)( \(바깥( 2)?\))?$/.exec(s);
  return m?tl(m[3]?'환경 {env} (바깥 2)':m[2]?'환경 {env} (바깥)':'환경 {env}',{env:m[1]}):tr(s);}
// Shows the level matching the current range as pressed. If scope is set, that level (when the range also matches); otherwise the first level whose lo/hi match
// (shown as '지금 범위' on an edit card).
function curLevel(o){const ls=o.levels||[];
  const s=o.scope&&lvOf(o,o.scope); if(s&&s.lo===o.lo&&s.hi===o.hi)return s;
  return ls.find(l=>l.lo===o.lo&&l.hi===o.hi)||null;}
// Line-range notation: 'L159' for a single line, 'L155-L173' for multiple (the copy/pins.md format 'L159-L159' is left as-is).
function rng(lo,hi){return 'L'+lo+(hi!==lo?'-L'+hi:'');}
// Segment-control labels are kept short - '환경 abstract' -> 'abstract'. When the same environment name appears more than
// once, '(바깥)' is kept to distinguish them. The line range is left out of the label, going instead into the description (data-tip)/aria-label and the location line.
function levelName(lv,all){if(!lv.env)return levelLabel(lv.label);
  const dup=(all||[]).filter(o=>o.env===lv.env).length>1; return dup?levelLabel(lv.label).replace(/^(환경|Environment) /,''):lv.env;}
function levelBtns(o,isEdit){const cur=curLevel(o),ls=o.levels||[]; return ls.map(lv=>{const on=lv===cur;
  const tip=isEdit&&lv.level==='raw'?T.cur:(lv.level.startsWith('env')?T.env:T[lv.level]);
  const label=isEdit&&lv.level==='raw'?tr('지금 범위'):levelName(lv,ls),nl=tl('{n}줄',{n:lv.n});
  return '<button class="'+(on?'on':'')+'" data-act="level" data-level="'+esc(lv.level)+'" aria-pressed="'+on+'" aria-label="'+
    esc(label+' '+rng(lv.lo,lv.hi)+' · '+nl)+'" data-tip="'+esc(rng(lv.lo,lv.hi)+' · '+tr(tip))+'">'+
    esc(label)+' <span class="k'+(lv.n>50?' wn':'')+'">· '+esc(nl)+'</span></button>';}).join('');}
// Scrolls a horizontally overflowing segment control so the selected segment is visible (vertical scroll is left untouched).
function segReveal(seg){const on=seg&&seg.querySelector('.on'); if(!on){segFade(seg);return;}
  const l=on.offsetLeft,r=l+on.offsetWidth;
  if(l<seg.scrollLeft)seg.scrollLeft=Math.max(0,l-4); else if(r>seg.scrollLeft+seg.clientWidth)seg.scrollLeft=r-seg.clientWidth+4;
  segFade(seg);}
// If the range ladder is longer than the panel, the overflowing edge is faded - since the scrollbar is hidden, the right-side
// segment (after 'minipage - 43 lines') used to just get clipped with no indication there was more (QA 2026-09-24). The same idea as the document-links row (docLinksFade).
function segFade(seg){if(!seg)return; const over=seg.scrollWidth-seg.clientWidth;
  seg.classList.toggle('fade-l',over>1&&seg.scrollLeft>1); seg.classList.toggle('fade-r',over>1&&over-seg.scrollLeft>1);}
document.addEventListener('scroll',e=>{const t=e.target; if(t&&t.classList&&t.classList.contains('seg'))segFade(t);},true);
function useLevel(o,key){const lv=lvOf(o,key); if(!lv)return; o.lo=lv.lo;o.hi=lv.hi;o.scope=lv.level;o.env=lv.env||null;o.snippet=lv.snippet;}
function nudge(o,dir){let lo=o.lo,hi=o.hi; const max=o.n_lines||hi+1;
  if(dir==='up-grow')lo=Math.max(1,lo-1); else if(dir==='up-shrink')lo=Math.min(hi,lo+1);
  else if(dir==='down-grow')hi=Math.min(max,hi+1); else if(dir==='down-shrink')hi=Math.max(lo,hi-1);
  if(lo===o.lo&&hi===o.hi)return false; o.lo=lo;o.hi=hi;o.scope='lines';o.env=null;return true;}
let snipT=null;
function refetchSnip(o,after){clearTimeout(snipT); snipT=setTimeout(async()=>{
  try{const {data}=await api(dq('/api/snippet?file='+encodeURIComponent(o.file)+'&lo='+o.lo+'&hi='+o.hi,o.doc),{what:'원문 읽기'});
    if(data.lo===o.lo&&data.hi===o.hi){o.snippet=data.snippet;after();}}catch(e){}},250);}
function snipText(text,open){const ls=String(text||'').split('\n');
  return (open||ls.length<=8)?ls.join('\n'):ls.slice(0,8).join('\n')+'\n      … '+tl('{n}줄 접힘',{n:ls.length-8});}
// Location match-rate badge: hidden at 90% or above (a number on a location you can trust is just noise). Below that, '위치 불확실';
// below 30%, the warning color. The method used, match rate, and what to check go in the description instead ('match 100%' alone was meaningless). Shared by the composer panel and cards.
const VIA_HIDE=90,VIA_WARN=30;
function viaTag(p){if(!p.via)return null; const pct=Math.round((+p.score||0)*100);
  if(pct>=VIA_HIDE)return null; const low=pct<VIA_WARN;
  const how=p.via==='synctex'?tr('좌표로 찾음'):(p.via==='text'?tr('글자로 찾음'):tl('찾은 방법: {via}',{via:p.via}));
  const why=tr(p.via==='text'?T.text:T.synctex);
  return {t:tr('위치 불확실'),tip:tl('{how} · 일치 {pct}% — {why}',{how,pct,why})+(low?' '+tr('많이 어긋났을 수 있습니다.'):''),low};}

// ------------------------------------------------ composer
function setBusy(on){$('#c-spin').hidden=!on; $('#c-body').classList.toggle('busy',on);}
async function pick(r){
  const seq=++PICKSEQ,rp=REPICK;
  // When a new selection (not a re-place) starts, the previous CUR is cleared right away - so that a [핀 저장] within
  // this window (~1.1s) never silently saves the stale CUR, and instead goes through the PEND_SAVE queue (§P0c) to
  // save the just-chosen new location (regression: the old location used to get saved on a re-select).
  if(rp){banner('<span>되짚는 중…</span>');} else {CUR=null; $('#composer').hidden=false; setBusy(true); PICKING=true; $('#c-err').hidden=true; $('#c-body').hidden=false;
    if(LAYOUT!=='wide'){setSide(true); $('#right').scrollTop=0; revealBox(PENDING);}}
  let d;
  try{d=(await api('/api/pick',{method:'POST',body:r,what:'위치 찾기'})).data;}
  catch(e){if(seq!==PICKSEQ)return; setBusy(false); if(!rp){PICKING=false; clearPendingSave();}
    if(rp){bannerRepick();} else {if(PENDING){PENDING.remove();PENDING=null;} if(!CUR)$('#composer').hidden=true;} return;}
  if(seq!==PICKSEQ)return;
  setBusy(false); if(!rp)PICKING=false;
  if(d.error){
    if(d.pdf_build_gone){try{await refreshDoc();}catch(e){} if(rp&&rp.box){rp.box.remove();rp.box=null;} else if(!rp&&PENDING){PENDING.remove();PENDING=null;}}
    if(rp){bannerRepick(errText(d));return;}
    // Even a pending save is never carried out if pick fails - only the existing error panel is shown (regression: prevents a silent save failure).
    CUR=null; clearPendingSave(); $('#c-err').textContent=errText(d); $('#c-err').hidden=false; $('#c-body').hidden=true; return;}
  if(rp){rp.cand=d; bannerCompare(); return;}
  CUR=d; CUR.scope=null; if(!isRegion(d)){useLevel(CUR,d.default_level); if(!CUR.scope){CUR.lo=d.lo;CUR.hi=d.hi;}}
  OVERLAP_DISMISSED=null;   // a freshly chosen selection - re-notified even if [별도 핀으로 저장] was pressed for a previous selection
  CUR.overlaps=overlapsFor(CUR,PINS);
  // If a pin the server saw as overlapping isn't in this tab's PINS (someone else just saved it), the list is re-fetched - loadPins recomputes overlap too.
  if((d.overlaps||[]).some(o=>!PINS.some(p=>p.id===o.id)))loadPins();
  SNIP_OPEN=false; $('#c-err').hidden=true; $('#c-body').hidden=false; renderComposer();
  $('#composer').scrollTop=0;   // so a second drag's new location/ladder never hides above the scroll (the note stays as-is)
  if(LAYOUT!=='wide')$('#right').scrollTop=0;
  // Drag -> straight into the note field. Never focused on touch - the virtual keyboard would pop up immediately and cover the range ladder and page.
  if(LAST_PTR==='mouse')$('#note').focus({preventScroll:true});
  // If [핀 저장] was pressed while pick was still slow (~1.1s), the queued save runs here (CUR has just been filled in).
  if(PEND_SAVE){clearPendingSave(); savePin();}
}
// P0b-03: if the pre-save selection (CUR) overlaps an open pin, one representative is chosen and a "append" banner
// is drawn. Never auto-merged - the user picks between [메모에 덧붙이기]/[별도 핀으로 저장].
// Overlap is recomputed against this tab's PINS every time the range changes (drag/level switch/up-down). Computing
// it only once at pick time meant switching levels to produce the exact same range as an existing pin never showed
// the banner, and a duplicate pin got saved (observed). The rule matches the server's selection_rel (a regression
// test compares them): equal (same range) - inside (selection is inside the pin) - contains (selection wraps the pin) - partial.
function selRel(lo,hi,blo,bhi){
  if(hi<blo||bhi<lo)return null;
  if(lo===blo&&hi===bhi)return 'equal';
  if(blo<=lo&&hi<=bhi)return 'inside';
  if(lo<=blo&&bhi<=hi)return 'contains';
  return 'partial';
}
function overlapsFor(o,pins){const out=[]; if(!o||!o.file)return out;   // a selection on a view-only PDF has no line
  (pins||[]).forEach(p=>{if(p.done||p.file!==o.file)return; const rel=selRel(o.lo,o.hi,p.lo,p.hi);
    if(rel)out.push({id:p.id,lo:p.lo,hi:p.hi,rel:rel});});
  return out;}
// One representative: same range > inside (the narrowest enclosing pin) > contains (the widest inner pin) > overlap (the smallest id).
function pickOverlap(ovs){
  if(!ovs||!ovs.length)return null;
  const eq=ovs.filter(o=>o.rel==='equal');
  if(eq.length)return eq.reduce((a,b)=>b.id<a.id?b:a);
  const insides=ovs.filter(o=>o.rel==='inside');
  if(insides.length)return insides.reduce((a,b)=>(b.hi-b.lo)<(a.hi-a.lo)?b:a);
  const contains=ovs.filter(o=>o.rel==='contains');
  if(contains.length)return contains.reduce((a,b)=>(b.hi-b.lo)>(a.hi-a.lo)?b:a);
  const partials=ovs.filter(o=>o.rel==='partial');
  if(partials.length)return partials.reduce((a,b)=>b.id<a.id?b:a);
  return null;
}
// Overlap-banner wording: what relationship the selection has to that pin - '#4와 같은 범위' - '#4 범위 안' - '#4를 감쌈' - '#4와 일부 겹침'.
// The whole banner sentence in the UI language: '열린 핀 #4와 같은 범위입니다' / 'Same range as open pin #4'.
function overlapText(rel,id){const k={equal:'열린 핀 #{id}{p} 같은 범위입니다',inside:'열린 핀 #{id} 범위 안입니다',contains:'열린 핀 #{id}{p} 감쌉니다',
    partial:'열린 핀 #{id}{p} 일부 겹칩니다'}[rel]||'열린 핀 #{id}{p} 겹칩니다';
  return tl(k,{id,p:rel==='contains'?josa(id,'을','를'):josa(id,'과','와')});}
// [별도 핀으로 저장] turns off "that relationship with that pin" (id:rel). Re-announced if changing the range changes the
// relationship, and reset on a fresh drag (pick) - prevents a regression where one press permanently silenced it for every later selection.
let OVERLAP_DISMISSED=null;
function recomputeOverlap(){if(CUR)CUR.overlaps=overlapsFor(CUR,PINS);}
function renderOverlapBanner(){
  const box=$('#c-overlap'); const d=CUR;
  const ov=d?pickOverlap(d.overlaps):null;
  if(!ov||OVERLAP_DISMISSED===ov.id+':'+ov.rel){box.hidden=true;return;}
  box.hidden=false; box.dataset.rel=ov.rel;
  box.innerHTML='<span>'+overlapText(ov.rel,ov.id)+' <span class="dim">(L'+ov.lo+'-L'+ov.hi+')</span></span>'+
    '<button class="btn-sm" data-act="overlap-append" data-oid="'+ov.id+'" data-tip="'+tl('이 선택의 메모를 #{id} 에 덧붙이고, 지금 선택은 새 핀으로 만들지 않습니다',{id:ov.id})+'">'+
    tl('#{id} 메모에 덧붙이기',{id:ov.id})+'</button>'+
    '<button class="btn-sm" data-act="overlap-separate" data-key="'+ov.id+':'+ov.rel+'" data-tip="겹쳐도 별도 핀으로 저장합니다">별도 핀으로 저장</button>';
}
// Location is one line: 'file L159' + page + match badge + [copy]. Range kind/line count are never repeated, since the
// segment control's selected segment already shows them (if adjusted directly via up/down and it doesn't match any
// segment, '줄 직접 지정' is appended next to the page). The dragged line goes into the description.
// Selection on a view-only PDF: the location is '쪽 N - 영역', and the region's text (pdftotext) is shown in the source field. The range ladder/stepper are hidden.
function renderRegionComposer(d){
  $('#composer').classList.add('region');
  $('#c-loc').textContent=d.name+' · '+tl('쪽 {page} 영역',{page:d.page}); $('#c-loc').dataset.copy=d.name+' 쪽 '+d.page;
  const pg=$('#c-page'); pg.textContent=tr('보기 전용'); pg.dataset.tip='LaTeX 소스가 없는 PDF입니다 — 줄 번호 없이 쪽·영역과 영역 글자로 핀을 남깁니다';
  $('#c-tag').hidden=true; $('#c-warn').hidden=!d.warn; $('#c-warn').textContent=warnText(d.warn); $('#c-overlap').hidden=true;
  $('#c-levels').innerHTML='';
  const pre=$('#c-snip'); pre.className='wrap open'; pre.textContent=d.quote?tl('영역 글자: {text}',{text:d.quote}):tr('(이 영역에는 글자가 없습니다)');
  $('#c-expand').hidden=true;}
function renderComposer(){const d=CUR; if(!d)return;
  if(isRegion(d)){renderRegionComposer(d); return;}
  $('#composer').classList.remove('region');
  const copy=d.name+' L'+d.lo+'-L'+d.hi;
  $('#c-loc').textContent=d.name+' '+rng(d.lo,d.hi); $('#c-loc').dataset.copy=copy;
  const pg=$('#c-page'),pgn=tl('{page}쪽',{page:d.page}); pg.textContent=pgn+(curLevel(d)?'':' · '+tr('줄 직접 지정'));
  pg.dataset.tip=pgn+' · '+scopeLabel(d)+' · '+tl('{n}줄',{n:d.hi-d.lo+1})+' · '+tl('드래그한 줄 {range}',{range:rng(d.raw_lo,d.raw_hi)});
  const v=viaTag(d),tg=$('#c-tag'); tg.hidden=!v; if(v){tg.textContent=v.t;tg.dataset.tip=v.tip;tg.classList.toggle('badge-warning',!!v.low);}
  $('#c-warn').hidden=!d.warn; $('#c-warn').textContent=warnText(d.warn);
  renderOverlapBanner();
  $('#c-levels').innerHTML=levelBtns(d,false);
  segReveal($('#c-levels'));
  const pre=$('#c-snip'); pre.className=(WRAP?'wrap':'nowrap')+(SNIP_OPEN?' open':''); pre.textContent=snipText(d.snippet,SNIP_OPEN);
  // A collapsed source is cut to 4 lines by CSS. Whether it was cut is measured after rendering (a manuscript where one long line wraps into several is common).
  const over=SNIP_OPEN||pre.scrollHeight>pre.clientHeight+2, nl=String(d.snippet||'').split('\n').length;
  pre.classList.toggle('clip',!SNIP_OPEN&&over);
  $('#c-expand').hidden=!over; $('#c-expand').textContent=SNIP_OPEN?tr('원문 접기'):tr('원문 펼치기')+(nl>1?' · '+tl('{n}줄',{n:nl}):'');
  $('#c-wrap').setAttribute('aria-pressed',String(WRAP));
}
// When a selection ends via save/cancel/append, selection mode is turned off (scrolling resumes) and the narrow sheet collapses (the body comes forward again).
// The composer panel's pin kind (fix request / question). Reverts to fix request on save or discard (the default for the next pin).
function setKind(k){KIND_NEW=k==='question'?'question':'fix';
  $$('#c-kind button').forEach(b=>{const on=b.dataset.kind===KIND_NEW; b.classList.toggle('on',on); b.setAttribute('aria-checked',String(on));});
  $('#note').placeholder=KIND_NEW==='question'?'무엇이 궁금한지 적어 주세요':'메모: 여기를 어떻게 고칠지 (비워도 됩니다)'; renderAssignNew(); qHint($('#c-qhint'),$('#note').value,KIND_NEW);}
// A note that reads like a question (docs/handbook/viewer.md §스레드와 검토 - suggesting the kind). True if it ends in ?/? or a
// Korean interrogative ending (는가/나요/까요/인가/건가/니/냐/까). A trailing period/ellipsis/closing bracket/quote and a
// trailing @-tag (e.g. '맞나요? @Bob Park') are ignored. Only judges - never changes the kind itself.
function looksQuestion(text){let t=String(text||'').trim();
  for(let i=0;i<3;i++)t=t.replace(/[\s.…~!。)\]"'”’]+$/,'').replace(/(?:\s*@[^\s@?？]+(?:\s+[A-Za-z][A-Za-z.'-]*)?)+$/,'');
  return /[?？]$/.test(t)||/(는가|나요|까요|인가|건가|니|냐|까)$/.test(t);}
// If it's a fix request but the note reads like a question, a one-line suggestion appears next to the kind control. Never
// auto-changes it - only changes on click (author feedback 2026-09-25: "...표현한 의도가 있는건가?" got saved as a fix
// request). Disappears once it becomes a question or the text no longer reads like one.
function qHint(box,text,kind){if(box)box.hidden=kind==='question'||!looksQuestion(text);}
function cancelSelection(clearNote){CUR=null; PICKSEQ++; PICKING=false; clearPendingSave(); if(PENDING){PENDING.remove();PENDING=null;}
  OVERLAP_DISMISSED=null; setBusy(false); $('#composer').hidden=true; if(clearNote){$('#note').value=''; $('#note')._mentions=null; ASSIGN_NEW.touched=false; mentionPreview($('#note')); setKind('fix');}
  if(!REPICK)setSelMode(false); if(LAYOUT==='narrow'&&!EDIT)setSide(false);}
async function appendToPin(id,text){
  const prior=PINS.find(p=>p.id===id); const priorNote=prior?(prior.note||''):'';
  try{const {data}=await api('/api/pins/'+id+'/edit',{method:'POST',body:{note_append:text},what:'메모 덧붙이기'});
    const box=PENDING; PENDING=null; cancelSelection(true); if(box)box.remove();
    toast(tl('#{id} 에 덧붙였습니다',{id}),'ok',{label:'되돌리기',fn:()=>undoAppend(id,priorNote,data.pin.rev)});
    await loadPins();
  }catch(e){}}
async function undoAppend(id,note,rev){
  try{await api('/api/pins/'+id+'/edit',{method:'POST',body:{note:note,base_rev:rev},what:'되돌리기'});
    toast(tl('#{id} 메모를 되돌렸습니다',{id}),'ok');}catch(e){} await loadPins();}
// The normal label for the save-pin button (shared by boot and clearing the pending state).
function saveBtnLabel(){return MQ_COARSE.matches?tr('핀 저장'):tr('핀 저장')+' <span class="kh">'+(IS_MAC?'⌘ Enter':'Ctrl+Enter')+'</span>';}
// P0c: pressing [핀 저장] right after a drag but before SyncTeX pick finishes (~1.1s) used to just silently vanish, since
// CUR didn't exist yet (observed). Now that save request is queued and auto-saved once pick succeeds - the note re-reads
// #note at the moment of saving (when pick resolves), picking up even characters the user edited in the meantime. If pick
// fails or the selection is canceled, the queue is cleared too. Pressing the button again cancels the pending save (a toggle) - so it can be undone without a separate cancel button.
function togglePendingSave(){if(PEND_SAVE){clearPendingSave();return;}
  PEND_SAVE=true; const btn=$('#btn-save'); btn.dataset.pending='1';
  btn.innerHTML=tr('위치 찾는 중… 저장 대기')+' <span class="spin" aria-hidden="true"></span>';}
function clearPendingSave(){if(!PEND_SAVE)return; PEND_SAVE=false;
  const btn=$('#btn-save'); delete btn.dataset.pending; btn.innerHTML=saveBtnLabel();}
async function savePin(){
  if(SAVING)return;
  if(!CUR){if(PICKING)togglePendingSave(); return;}   // pick hasn't finished yet - queue it (toggle) or cancel the pending save
  SAVING=true; const btn=$('#btn-save'); btn.disabled=true;
  const d=CUR,note=$('#note').value.trim();
  let body={file:d.file,name:d.name,page:d.page,lo:d.lo,hi:d.hi,raw_lo:d.raw_lo,raw_hi:d.raw_hi,via:d.via,score:d.score,
    frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};
  if(d.scope){body.scope=d.scope; body.kind=kindFor(d.scope,d.env);} else body.kind=d.kind;
  if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};   // view-only: page/region only
  body.doc=d.doc||DOC||undefined;
  body.kind_req=KIND_NEW;
  const mh=mentionHints($('#note')); if(mh.length)body.mentions=mh;
  renderAssignNew(); body.assignee=ASSIGN_NEW.v||'agent';   // a pin created by the viewer always records an assignee (otherwise a legacy pin's inference rule applies)
  try{const {data}=await api('/api/pin',{method:'POST',body,what:'핀 저장'});
    const id=data.id,q=KIND_NEW==='question'; const box=PENDING; PENDING=null; cancelSelection(true); if(box)box.remove();
    if(SEC_SEEN.open)SEC_SEEN.open.add(id);   // my own new pin is never 'new' on a collapsed header
    toast(tl(q?'질문 #{id} 저장됨 · pins.md 갱신':'핀 #{id} 저장됨 · pins.md 갱신',{id}),'ok',{label:'되돌리기',fn:()=>dropPin(id,true)});
    await loadPins();
  }catch(e){} finally{SAVING=false; btn.disabled=false;}
}

// ------------------------------------------------ Pin list
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
// If the people list changes (a new person/name), the list is redrawn - the very first render can show a login instead of a name.
async function loadPeople(){try{const r=(await api('/api/people',{what:'사람 목록',silent:true})).data;
  if(Array.isArray(r.people)){const was=JSON.stringify(PEOPLE); PEOPLE=r.people; if(JSON.stringify(PEOPLE)!==was)drawPins();}}catch(e){}}
async function loadPins(){let d;
  try{d=(await api('/api/pins?all=1',{what:'핀 읽기'})).data;}catch(e){return;}
  loadPeople();
  let dropped=[];
  try{dropped=(await api('/api/pins/dropped',{what:'삭제한 핀',silent:true})).data.dropped||[];}catch(e){}
  // Multiple documents: the fetched list is for every document (diffToast also sees all of it too). PINS/DONE are only the current document's; if SHOW_ALL, only the rendered list shows everything.
  const prevOpen=OPEN_ALL,prevReview=REVIEW_ALL;
  const nextOpen=d.filter(p=>!p.done); REVIEW_ALL=d.filter(p=>pinState(p)==='review'); DONE_ALL=d.filter(p=>pinState(p)==='done'); DROPPED=dropped;
  diffToast(prevOpen,d,dropped); reviewToast(prevReview,d);
  OPEN_ALL=nextOpen; PINS=nextOpen.filter(p=>pdoc(p)===DOC||!DOC); DONE=DONE_ALL.filter(p=>pdoc(p)===DOC||!DOC);
  if(EDIT&&!OPEN_ALL.some(p=>p.id===EDIT.id)){toast(tl('편집 중이던 핀 #{id} 이 목록에서 빠졌습니다(다른 쪽에서 닫았거나 지움)',{id:EDIT.id}),'warn'); EDIT=null;}
  if(REPLY&&!d.some(p=>p.id===REPLY.id)){closeReply(false); toast('답글을 쓰던 핀이 목록에서 빠졌습니다(지워짐) — 쓰던 글은 남겨 둡니다','warn');}
  if(!SEC_SEEN.open){SEC_SEEN.open=new Set(OPEN_ALL.map(p=>p.id)); SEC_SEEN.review=new Set(REVIEW_ALL.map(p=>p.id)); SEC_SEEN.done=new Set(DONE_ALL.map(p=>p.id));}
  drawPins(); marks(); drawDocTabs();
  if(CUR){recomputeOverlap(); renderOverlapBanner();}   // if the list changes (someone else's save/completion), overlap is recomputed too
  docTitle(true);
}
// The list drawn in the sidebar: the current document by default, everything if 'all documents'. A pin being edited is kept even from another document (so the draft text doesn't disappear).
function listOpen(){return SHOW_ALL&&multiDoc()?OPEN_ALL:OPEN_ALL.filter(p=>pdoc(p)===DOC||!DOC||(EDIT&&EDIT.id===p.id));}
function listDone(){return SHOW_ALL&&multiDoc()?DONE_ALL:DONE;}
function listReview(){return SHOW_ALL&&multiDoc()?REVIEW_ALL:REVIEW_ALL.filter(p=>pdoc(p)===DOC||!DOC);}
// Awaiting-review count: counted across documents (the inbox of work for a person to confirm). The purple number next to [핀 N] (compact) / the tool bar chip (wide).
function updateReviewCount(){const n=REVIEW_ALL.length,pill=$('#side-rv'),chip=$('#rv-chip');
  pill.hidden=!n; pill.textContent=n; pill.setAttribute('aria-label',tl('검토 대기 {n}',{n}));
  const here=listReview().length; chip.hidden=!n||LAYOUT!=='wide'; chip.textContent=tl('검토 대기 {n}',{n})+(multiDoc()&&here!==n?' '+tl('(이 문서 {n})',{n:here}):'');}
function gotoReview(){if(!listReview().length&&REVIEW_ALL.length&&multiDoc())SHOW_ALL=true;
  if(!SEC.review){SEC.review=true; savePrefs({sec:SEC});} drawPins();
  setSide(true); requestAnimationFrame(()=>{const t=$('#sec-review'); if(t&&!t.hidden)t.scrollIntoView({block:'start',behavior:SMOOTH});});}
// The reviewer shown on an awaiting-review card: the author is suggested (anyone can confirm - a trust model). If I'm the author, '내 확인 차례'.
function isMe(a){const me=META&&META.me; return !!(a&&me&&me.login&&me.login!=='local'&&a.login===me.login);}
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
  b.innerHTML=ic(open?'chevron-down':'chevron-right')+'<span class="sec-name" id="'+SEC_NAME_ID[key]+'">'+esc(name)+' <span class="badge badge-secondary sec-n">'+ids.length+'</span></span>'+
    (nn?'<span class="sec-new">'+esc(tl('새 {n}',{n:nn}))+'</span>':'');
  b.setAttribute('aria-expanded',String(open));
  const body=document.getElementById(b.getAttribute('aria-controls')); if(body)body.hidden=!open;}
function toggleSec(key,force){if(!(key in SEC_DEFAULT))return; SEC[key]=force===undefined?!SEC[key]:!!force; savePrefs({sec:SEC}); drawPins();}
function drawPins(){
  const LIST=listOpen(),LDONE=listDone(),LDROP=listDropped();
  // The '나를 부른 핀' filter: only the open/awaiting-review pins across every document that @-tagged me (a cross-document inbox).
  const MINE=OPEN_ALL.concat(REVIEW_ALL).filter(mentionsMe),mf=$('#mention-filter');
  if(MENTION_ONLY&&!MINE.length)MENTION_ONLY=false;
  mf.hidden=!MINE.length; mf.setAttribute('aria-pressed',String(MENTION_ONLY)); mf.innerHTML=ic('at-sign')+MINE.length; mf.setAttribute('aria-label',tl('나를 부른 핀 {n}',{n:MINE.length}));
  const SHOWN=MENTION_ONLY?OPEN_ALL.filter(mentionsMe):LIST;
  // If the cursor was in the reply input field, it's restored to that position after redrawing (so auto-sync redrawing the list never interrupts typing).
  const rta=REPLY&&REPLY.el.querySelector('textarea'),rfocus=rta&&document.activeElement===rta?[rta.selectionStart,rta.selectionEnd]:null;
  secHead('open',tr(MENTION_ONLY?'나를 부른 열린 핀':SHOW_ALL&&multiDoc()?'모든 문서의 열린 핀':'열린 핀'),SHOWN.map(p=>p.id),OPEN_ALL.map(p=>p.id));
  const ab=$('#all-docs'); ab.setAttribute('aria-pressed',String(SHOW_ALL)); ab.innerHTML=(SHOW_ALL?ic('check'):'')+esc(tr('모든 문서'));
  $('#side-n').textContent=PINS.length; applySide();
  // In compact, the done toggle and the Trash are also in [⋯]. On desktop the Trash is the link under the list.
  $('#m-done').textContent=tl(SEC.done?'닫힌 핀 {n} 숨기기':'닫힌 핀 {n} 보기',{n:LDONE.length});
  const nTrash=LDROP.filter(p=>!PURGING.has(p.id)).length;
  $('#m-trash').textContent=tl('휴지통 {n}',{n:nTrash}); $('#trash-link').textContent=tl('휴지통 {n}',{n:nTrash}); $('#trash-link').hidden=!nTrash;
  $('#empty').hidden=SHOWN.length>0||OPEN_ALL.length>0||REVIEW_ALL.length>0;
  // Empty list: the header's count already says it - a separate '아직 없습니다.' line is never added too (QA). Only a note that another document has pins is left.
  $('#pins').innerHTML=SHOWN.length?SHOWN.map(card).join(''):(multiDoc()&&!SHOW_ALL&&OPEN_ALL.length?'<div class="dim list-empty">'+esc(tl('이 문서에는 없습니다 · 다른 문서에 {n}건',{n:OPEN_ALL.length}))+'</div>':'');
  if(EDIT){const slot=$('#pins .edit-slot'); if(slot)slot.replaceWith(EDIT.el);}
  // Awaiting-review section: between open pins and done. Hidden when empty. The card looks the same as an open pin (thread/replies); only the actions are [확인]/[답글].
  const LREV=MENTION_ONLY?REVIEW_ALL.filter(mentionsMe):listReview();
  $('#sec-review').hidden=!LREV.length; secHead('review',tr('검토 대기'),LREV.map(p=>p.id),REVIEW_ALL.map(p=>p.id));
  $('#review-pins').innerHTML=LREV.map(card).join('');
  updateReviewCount();
  // Done section: hidden header and all if empty. The header stays stuck to the top while scrolling.
  $('#sec-done').hidden=!LDONE.length; secHead('done',tr('완료'),LDONE.map(p=>p.id),DONE_ALL.map(p=>p.id));
  if(SEC.done)$('#done-list').innerHTML=LDONE.length?LDONE.slice().reverse().map(doneCard).join(''):'<div class="dim">없습니다.</div>';
  if($('#trash').open)drawTrash();
  if(REPLY){const slot=document.querySelector('#list .reply-slot'); if(slot)slot.replaceWith(REPLY.el); renderReplyOutcome();   // the pin may have changed state meanwhile
    if(rfocus&&document.contains(rta)){rta.focus(); try{rta.setSelectionRange(rfocus[0],rfocus[1]);}catch(e){}}}
}
// Location estimation (.est, dashed) is judged by the server and carried as est in /api/pins (pin_est - comparing the
// manuscript fingerprint of the build the pin was placed on with the current build). Back when the viewer judged this by
// wall clock, it was wrong across the board with browser timezone, a note-only edited_at, and a pin placed on a stale
// PDF (confirmed by independent verification). The viewer just renders the value it's given.
function isEstimated(p){return p.est===true;}
function marks(){
  $$('.mark').forEach(m=>m.remove());
  // Awaiting-review pins are also drawn as purple marks - so the reviewer can see right there what was fixed (unrelated to an open pin's overlap/editing).
  PINS.concat(REVIEW_ALL.filter(p=>pdoc(p)===DOC)).forEach(p=>{const el=document.getElementById('p'+p.page); if(!el||!Array.isArray(p.frac))return;
    const est=isEstimated(p);
    const m=document.createElement('div'); m.className='mark'+(p.stale?' st':'')+(est?' est':'')+(p.done?' rv':''); m.dataset.pin=p.id;
    Object.assign(m.style,{left:p.frac[0]*100+'%',top:p.frac[1]*100+'%',width:p.frac[2]*100+'%',height:p.frac[3]*100+'%'});
    const n=String(p.note||'').replace(/\s+/g,' ').trim();
    const tip='#'+p.id+' · '+(n?(n.length>60?n.slice(0,60)+'…':n):tr('(메모 없음)'))+(est?' '+tr('(PDF가 새로 만들어져 위치는 추정입니다)'):'');
    m.innerHTML='<b data-act="mark-jump" data-id="'+p.id+'" data-tip="'+esc(tip)+'">'+p.id+'</b>'; el.appendChild(m);});
}
// Clicking a badge scrolls to and flashes the card (never calls pick). The mark box itself has pointer-events:none, so
// a drag over it still becomes a new selection - only the badge (<b>) needs to block mousedown.
$('#doc').addEventListener('mousedown',e=>{
  if(e.target.closest('.mark b')){e.stopPropagation();e.preventDefault();}
},true);
// Clicking a badge -> scroll to the card + .cur highlight (spec) + a 1.2-second flash. The highlight is never left on -
// it releases; when it was a static box-shadow, it stayed on the card until the next click.
// compact: clicking a badge expands the panel/sheet and that card, then scrolls via jumpToCard.
// Expands the section that holds pin id if it is collapsed (a mark click, a notification, [검토 대기 N]). Returns true if it changed.
function secOpenFor(id){const p=findAnyPin(id); if(!p)return false; const st=pinState(p),key=st==='review'?'review':st==='done'?'done':'open';
  if(SEC[key])return false; SEC[key]=true; savePrefs({sec:SEC}); return true;}
function revealCard(id){if(secOpenFor(id))drawPins(); if(LAYOUT==='wide')return; setSide(true);
  if(!OPEN_CARDS.has(id)&&(PINS.some(p=>p.id===id)||REVIEW_ALL.some(p=>p.id===id))){OPEN_CARDS.add(id); drawPins();}}
function jumpToCard(id){if(secOpenFor(id))drawPins();
  const el=document.querySelector('.pin[data-id="'+id+'"]'); if(!el)return;
  el.scrollIntoView({behavior:SMOOTH,block:'nearest'});
  $$('.pin.cur').forEach(x=>{if(x!==el)x.classList.remove('cur');});
  clearTimeout(el._curT);
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('cur','flash');
  el._curT=setTimeout(()=>el.classList.remove('cur','flash'),1200);
}
// A '#12' link in text: expands and scrolls to that pin's card/archive row, then flashes it. If it's on another document, '모든 문서' is turned on.
function gotoPinRef(id){const p=findAnyPin(id); if(!p){if(DROPPED.some(x=>x.id===id))openTrash(id); return;}
  const st=pinState(p);
  if(multiDoc()&&DOC&&pdoc(p)!==DOC)SHOW_ALL=true;
  if(st==='done')SEC.done=true; else{OPEN_CARDS.add(id); SEC[st==='review'?'review':'open']=true;} savePrefs({sec:SEC});
  if(LAYOUT!=='wide')setSide(true); drawPins();
  requestAnimationFrame(()=>{const el=document.querySelector('.pin[data-id="'+id+'"],.arc-row[data-id="'+id+'"]'); if(!el)return;
    el.scrollIntoView({behavior:SMOOTH,block:'nearest'}); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    clearTimeout(el._flT); el._flT=setTimeout(()=>el.classList.remove('flash'),1200);});}
function jumpPin(id){if(viaDoc(id,jumpPin))return; const p=PINS.find(x=>x.id===id)||REVIEW_ALL.find(x=>x.id===id&&pdoc(x)===DOC);
  if(!p){const q=REVIEW_ALL.find(x=>x.id===id); if(q&&docInfo(pdoc(q)))switchDoc(pdoc(q)).then(()=>{if(DOC===pdoc(q))jumpPin(id);}); return;}
  if(document.body.classList.contains('revision-open'))setViewMode('manuscript');
  if(LAYOUT==='narrow')setSide(false);   // collapsed first so the sheet doesn't cover the page, then measured
  const m=document.querySelector('.mark[data-pin="'+id+'"]');
  if(m){
    const L=$('#left'),lr=L.getBoundingClientRect(),mr=m.getBoundingClientRect();
    L.scrollTop+=(mr.top-(lr.top+lr.height*0.30));
    m.classList.remove('flash');void m.offsetWidth;m.classList.add('flash');
  } else {
    const el=document.getElementById('p'+p.page); if(el)el.scrollIntoView({behavior:SMOOTH});
  }
}
// Hovering a card highlights its mark, along with any overlapping counterpart marks.
function markIdsFor(p){return [p.id].concat((p.rel||[]).map(x=>x.id));}
$('#pins').addEventListener('mouseover',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.add('hi');});});
$('#pins').addEventListener('mouseout',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.remove('hi');});});
async function closePin(id){try{const {data}=await api('/api/pins/'+id+'/close',{method:'POST',what:'완료'});
  if(!data.ok){toast(tl('완료 실패 — 핀 #{id} 이 없습니다',{id}),'err');}
  else {markMine(id); toast(tl(data.state==='review'?'핀 #{id} 검토 대기로 보냄 — 이 화면에 신원이 없어(로컬) 에이전트가 닫은 것으로 칩니다':'핀 #{id} 완료',{id}),
    'ok',{label:'되돌리기',fn:()=>reopenPin(id)});}}catch(e){} await loadPins();}
// Awaiting review -> done. The person who confirmed (confirmed_by) is recorded.
async function confirmPin(id){try{const {data}=await api('/api/pins/'+id+'/confirm',{method:'POST',what:'확인',expect:[409]});
  if(data&&data.error==='open')toast(tl('핀 #{id} 은 이미 다시 열렸습니다',{id}),'warn');
  else if(!data.ok)toast(tl('확인 실패 — 핀 #{id} 이 없습니다',{id}),'err');
  else{markMine(id); toast(tl('핀 #{id} 확인 · 완료로 옮겼습니다',{id}),'ok');}}catch(e){} await loadPins();}
// Undo of [완료] (the toast's [되돌리기]) - the viewer has no [다시 열기] button any more; a reply reopens by the server rule.
async function reopenPin(id){try{await api('/api/pins/'+id+'/reopen',{method:'POST',what:'다시 열기'});
  markMine(id); toast(tl('핀 #{id} 완료를 되돌렸습니다',{id}),'ok');}catch(e){} await loadPins();}
// [삭제] takes the pin off the list at once (no confirmation) and says so next to the action with [되돌리기]; it waits in the Trash.
async function dropPin(id,undoSave){const was={o:OPEN_ALL,p:PINS};
  OPEN_ALL=OPEN_ALL.filter(p=>p.id!==id); PINS=PINS.filter(p=>p.id!==id); if(EDIT&&EDIT.id===id)EDIT=null; drawPins(); marks();
  try{await api('/api/pins/'+id+'/drop',{method:'POST',what:'삭제'});
    markMine(id); toast(tl(undoSave?'핀 #{id} 저장을 되돌렸습니다':'핀 #{id} 삭제됨 · 휴지통에 30일 보관',{id}),'ok',{label:'되돌리기',fn:()=>restorePin(id)});}
  catch(e){OPEN_ALL=was.o; PINS=was.p; drawPins(); marks();} await loadPins();}
// [영구 삭제] (owner): the row leaves the Trash at once; the request goes out when the undo toast does (deferred).
const PURGING=new Set();
function purgePin(id){PURGING.add(id); drawTrash(); drawPins();
  deferred(tl('핀 #{id} 영구 삭제',{id}),async()=>{try{await api('/api/pins/'+id+'/purge',{method:'POST',what:'영구 삭제',keepalive:true});}catch(e){}
      PURGING.delete(id); await loadPins();},
    ()=>{PURGING.delete(id); drawTrash(); drawPins();});}
async function restorePin(id){try{await api('/api/pins/'+id+'/restore',{method:'POST',what:'되살리기'});
  markMine(id); toast(tl('핀 #{id} 되살림',{id}),'ok');}catch(e){} await loadPins();}
async function unclaimPin(id){try{await api('/api/pins/'+id+'/unclaim',{method:'POST',what:'처리 중 풀기'});
  markMine(id); toast(tl('핀 #{id} 처리 중 표시를 풀었습니다',{id}),'ok');}catch(e){} await loadPins();}

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
function mentionApply(i){const ta=MENTION.ta,p=MENTION.items[i]; if(!ta||!p)return; const pos=ta.selectionStart,ins='@'+p.name+' ';
  ta.value=ta.value.slice(0,MENTION.start)+ins+ta.value.slice(pos); const c=MENTION.start+ins.length; ta.setSelectionRange(c,c);
  (ta._mentions=ta._mentions||new Set()).add(p.login); mentionClose(); ta.focus(); autoGrow(ta); mentionPreview(ta);
  if(ta.id==='note')renderAssignNew(); else if(ta.classList.contains('e-note'))renderAssignEdit(); else if(ta.classList.contains('r-text'))renderReplyOutcome();}
const isMentionField=t=>!!t&&t.tagName==='TEXTAREA'&&(t.id==='note'||t.classList.contains('e-note')||t.classList.contains('r-text'));
document.addEventListener('input',e=>{if(isMentionField(e.target)){mentionUpdate(e.target); mentionPreview(e.target);
  if(e.target.id==='note'){renderAssignNew(); qHint($('#c-qhint'),e.target.value,KIND_NEW);}
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
function openReply(id){
  if(REPLY&&REPLY.id===id){const t=REPLY.el.querySelector('textarea'); if(t)t.focus(); return;}
  if(REPLY)closeReply(false);
  const p=findAnyPin(id);
  REPLY={id,flip:false,toggle:null,el:replyEl(p)}; OPEN_CARDS.add(id); if(LAYOUT!=='wide')setSide(true); drawPins();
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

// ------------------------------------------------ Edit
function openEdit(id){if(viaDoc(id,openEdit))return; const p=PINS.find(x=>x.id===id); if(!p)return;
  if(document.body.classList.contains('revision-open'))jumpPin(id);
  if(EDIT&&EDIT.id===id)return;
  const el=document.createElement('div'); el.className='edit';
  el.innerHTML='<div class="e-kind seg kind-seg" role="radiogroup" aria-label="핀 종류"><button data-act="e-kind" data-kind="fix" role="radio" data-tip="고쳐 달라는 요청">수정 요청</button>'+
    '<button data-act="e-kind" data-kind="question" role="radio" data-tip="'+esc(T.question)+'">질문</button></div>'+
    '<textarea class="e-note" rows="3" aria-label="메모 고치기" data-tip="메모를 고칩니다. ⌘ Enter / Ctrl+Enter 저장, Esc 취소"></textarea><div class="m-preview" aria-live="polite" hidden></div>'+
    '<div class="e-qhint q-hint" role="status" hidden>'+ic('circle-question-mark')+'<span>질문처럼 보입니다 —</span><button data-act="e-kind" data-kind="question" data-tip="이 핀을 질문으로 바꿉니다">질문으로 보내기</button></div>'+
    '<div class="e-assign assign-row" role="radiogroup" aria-label="담당" hidden></div>'+
    '<div class="e-levels seg" role="group" aria-label="범위 단계"></div>'+
    '<div class="c-tools"><div class="step" role="group" aria-label="한 줄씩 넓히고 좁히기">'+
    '<span class="sl" aria-hidden="true">위</span><button data-act="nudge" data-dir="up-grow" aria-label="위로 한 줄 넓히기" data-tip="위로 한 줄 넓힙니다">'+ic('plus')+'</button>'+
    '<button data-act="nudge" data-dir="up-shrink" aria-label="위에서 한 줄 좁히기" data-tip="위에서 한 줄 좁힙니다">'+ic('minus')+'</button>'+
    '<span class="sl" aria-hidden="true">아래</span><button data-act="nudge" data-dir="down-grow" aria-label="아래로 한 줄 넓히기" data-tip="아래로 한 줄 넓힙니다">'+ic('plus')+'</button>'+
    '<button data-act="nudge" data-dir="down-shrink" aria-label="아래에서 한 줄 좁히기" data-tip="아래에서 한 줄 좁힙니다">'+ic('minus')+'</button></div>'+
    '<span class="e-range loc" tabindex="0" data-tip="저장하면 핀이 가리킬 원문 줄. 누르면 복사"></span></div>'+
    '<pre class="e-snip wrap">원문 읽는 중…</pre>'+
    '<div class="e-acts"><button class="btn-sm b-repick" data-act="repick" data-tip="'+esc(T.repick)+'">위치 다시 잡기</button>'+
    '<button class="btn-sm b-ecancel" data-act="ecancel" data-tip="'+esc(T.ecancel)+'">취소</button>'+
    '<button class="btn-sm btn-default b-esave" data-act="esave" data-tip="'+esc(T.esave)+'">저장</button></div>';
  const ta=el.querySelector('.e-note'); ta.value=p.note||''; ta._mentions=new Set(p.mentions||[]); autoGrow(ta); mentionPreview(ta);
  EDIT={id,el,base_rev:p.rev||0,file:p.file,name:p.name||String(p.file||p.pdf||'').split('/').pop(),lo:p.lo,hi:p.hi,scope:p.scope||null,
    kind:p.kind,env:null,levels:[],n_lines:null,snippet:'',orig:{lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',kind_req:isQuestion(p)?'question':'fix',assignee:assigneeOf(p)},
    assignee:assigneeOf(p),
    doc:pdoc(p),region:isRegion(p),page:p.page,quote:p.quote||'',kind_req:isQuestion(p)?'question':'fix'};
  if(EDIT.region)el.classList.add('region');
  drawPins(); renderEdit(); ta.focus(); editSnip(true);
}
// Does the edit field have unsaved changes (whether it's safe to close the edit when switching documents)?
function editDirty(){const E=EDIT; if(!E)return false; const ta=E.el.querySelector('.e-note');
  return (ta&&ta.value!==E.orig.note)||E.lo!==E.orig.lo||E.hi!==E.orig.hi||E.kind_req!==E.orig.kind_req||E.assignee!==E.orig.assignee;}
function autoGrow(ta){ta.style.height='auto'; const lh=20; ta.style.height=Math.min(12*lh,Math.max(3*lh,ta.scrollHeight+2))+'px';}
document.addEventListener('input',e=>{if(e.target.classList&&(e.target.classList.contains('e-note')||e.target.classList.contains('r-text')||e.target.id==='note'))autoGrow(e.target);});
async function editSnip(withLevels){const E=EDIT; if(!E)return;
  if(E.region){E.snippet=E.quote?tl('영역 글자: {text}',{text:E.quote}):tr('(영역 글자 없음)'); renderEdit(); return;}   // view-only: there is no source line
  try{const {status,data}=await api(dq('/api/snippet?file='+encodeURIComponent(E.file)+'&lo='+E.lo+'&hi='+E.hi+(withLevels?'&levels=1':''),E.doc),
      {what:'원문 읽기',expect:[400]});
    if(EDIT!==E)return;
    if(status===400){E.snippet=tr('원문을 읽지 못했습니다')+' — '+errText(data)+'\n'+tr('위치 다시 잡기로 고치세요.'); renderEdit(); return;}
    E.snippet=data.snippet; E.n_lines=data.n_lines;
    if(withLevels&&data.levels){E.levels=data.levels; if(!E.scope||!lvOf(E,E.scope)){const cur=E.levels.find(l=>l.lo===E.lo&&l.hi===E.hi);
      if(cur&&!E.scope)E.scope=null;}}
    renderEdit();}catch(e){}}
function renderEdit(){const E=EDIT; if(!E)return; const el=E.el;
  el.querySelectorAll('.e-kind button').forEach(b=>{const on=b.dataset.kind===(E.kind_req||'fix'); b.classList.toggle('on',on); b.setAttribute('aria-checked',String(on));});
  el.querySelector('.e-range').textContent=E.region?tl('쪽 {page} · 영역',{page:E.page}):rng(E.lo,E.hi);
  el.querySelector('.e-range').dataset.copy=E.region?E.name+' 쪽 '+E.page:E.name+' L'+E.lo+'-L'+E.hi;
  el.querySelector('.e-levels').innerHTML=levelBtns(E,true); segReveal(el.querySelector('.e-levels'));
  const pre=el.querySelector('.e-snip'); pre.className='e-snip '+(WRAP?'wrap':'nowrap'); pre.textContent=snipText(E.snippet,false); renderAssignEdit();
  qHint(el.querySelector('.e-qhint'),el.querySelector('.e-note').value,E.kind_req);}
function cancelEdit(){EDIT=null; drawPins();}
async function saveEdit(){const E=EDIT; if(!E||ESAVING||viewerBlocked())return;
  const note=E.el.querySelector('.e-note').value, body={base_rev:E.base_rev};
  if(note!==E.orig.note)body.note=note;
  if(E.kind_req&&E.kind_req!==E.orig.kind_req)body.kind_req=E.kind_req;
  if(E.assignee&&E.assignee!==E.orig.assignee)body.assignee=E.assignee;
  if(body.note!==undefined){const mh=mentionHints(E.el.querySelector('.e-note')); if(mh.length)body.mentions=mh;}
  if(E.lo!==E.orig.lo||E.hi!==E.orig.hi||(E.scope||null)!==(E.orig.scope||null)){body.lo=E.lo;body.hi=E.hi;
    if(E.scope){body.scope=E.scope; body.kind=kindFor(E.scope,E.env);}}
  if(Object.keys(body).length===1){cancelEdit();return;}
  ESAVING=true;
  try{const {status,data}=await api('/api/pins/'+E.id+'/edit',{method:'POST',body,what:'핀 수정',expect:[409]});
    if(status===409){
      if(data&&data.error==='done'){toast(tl('핀 #{id} 은 이미 닫혀 범위를 바꿀 수 없습니다 — 메모만 고칠 수 있습니다',{id:E.id}),'warn'); EDIT=null; await loadPins(); return;}
      const p=data.pin; toast('다른 쪽(에이전트나 자동 줄 맞춤)이 이 핀을 먼저 바꿨습니다 — 최신 위치를 불러왔습니다','warn');
      E.base_rev=p.rev; E.lo=p.lo; E.hi=p.hi; E.scope=p.scope||null; E.file=p.file;
      E.orig={lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||'',kind_req:E.orig.kind_req,assignee:assigneeOf(p)}; editSnip(true); await loadPins(); return;}
    EDIT=null; toast(tl('핀 #{id} 수정됨',{id:E.id}),'ok'); await loadPins();
  }catch(e){} finally{ESAVING=false;}
}

// ------------------------------------------------ Re-place location
function banner(html){const b=$('#banner'); b.innerHTML=html; b.hidden=false;}
function bannerRepick(err){banner('<span>'+esc(tl('핀 #{id} 의 새 위치를 PDF에서 드래그하세요 · Esc 취소',{id:REPICK.id}))+'</span>'+
  (err?'<span class="errline" style="margin:0">'+esc(err)+'</span>':'')+'<span class="sp"></span>'+
  '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');}
function bannerCompare(){const c=REPICK.cand,lv=lvOf(c,c.default_level)||c,rg=isRegion(c);
  banner('<span class="loc" data-tip="지금 위치 → 새 위치" tabindex="0">'+esc(rg?tl('지금 쪽 {from} · 새 쪽 {to} 영역',{from:REPICK.from.page,to:c.page}):tl('지금 {from} · 새 {to}',{from:'L'+REPICK.from.lo+'-L'+REPICK.from.hi,to:'L'+lv.lo+'-L'+lv.hi}))+'</span>'+
    '<span class="dim">('+esc(rg?(c.quote?String(c.quote).slice(0,40):tr('글자 없는 영역')):(lv.label?levelLabel(lv.label):scopeLabel(c)))+')</span><span class="sp"></span>'+
    '<button class="btn-sm btn-default" data-act="rp-apply" data-tip="번호와 메모는 그대로 두고 위치만 바꿉니다">이 위치로 바꾸기</button>'+
    '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');}
// On touch, selection mode is turned on during a re-place, and narrow collapses the sheet to reveal the page (the banner stays visible even on the collapsed sheet).
async function startRepick(){if(!EDIT)return;
  if(EDIT.doc&&EDIT.doc!==DOC){const E=EDIT; await switchDoc(E.doc); if(DOC!==E.doc||EDIT!==E)return;}   // selection happens on that pin's document
  REPICK={id:EDIT.id,from:{lo:EDIT.lo,hi:EDIT.hi,page:EDIT.page},box:null,cand:null}; bannerRepick();
  if(MQ_COARSE.matches)setSelMode(true); if(LAYOUT==='narrow')setSide(false);}
function cancelRepick(){const was=!!REPICK; if(REPICK&&REPICK.box)REPICK.box.remove(); REPICK=null; $('#banner').hidden=true;
  if(was){if(!CUR)setSelMode(false); if(EDIT&&LAYOUT!=='wide')setSide(true);}}
async function applyRepick(){const R=REPICK; if(!R||!R.cand)return; const c=R.cand,lv=lvOf(c,c.default_level)||c;
  let loc={file:c.file,page:c.page,lo:lv.lo,hi:lv.hi,raw_lo:c.raw_lo,raw_hi:c.raw_hi,via:c.via,score:c.score,frac:c.frac,pdf_build:c.pdf_build||undefined,
    scope:lv.level||null,kind:lv.level?kindFor(lv.level,lv.env):c.kind};
  if(!loc.scope)delete loc.scope;
  if(isRegion(c))loc={page:c.page,frac:c.frac,quote:c.quote,pdf_build:c.pdf_build||undefined};   // view-only: only the region is re-placed
  const base=EDIT&&EDIT.id===R.id?EDIT.base_rev:0;
  try{const {status,data}=await api('/api/pins/'+R.id+'/edit',{method:'POST',body:{loc,base_rev:base},what:'위치 바꾸기',expect:[409]});
    if(status===409){toast(data&&data.error==='done'?'닫힌 핀은 위치를 바꿀 수 없습니다':'다른 쪽이 이 핀을 먼저 바꿨습니다 — 최신 값을 불러왔습니다','warn');
      if(EDIT&&data.pin){EDIT.base_rev=data.pin.rev;} cancelRepick(); await loadPins(); return;}
    const p=data.pin; cancelRepick();
    if(EDIT&&EDIT.id===p.id){Object.assign(EDIT,{base_rev:p.rev,lo:p.lo,hi:p.hi,file:p.file,name:p.name,scope:p.scope||null,page:p.page,quote:p.quote||''});
      EDIT.orig.lo=p.lo;EDIT.orig.hi=p.hi;EDIT.orig.scope=p.scope||null; editSnip(true);}
    toast(tl('핀 #{id} 위치를 {where} 로 바꿨습니다',{id:p.id,where:isRegion(p)?tl('쪽 {page} 영역',{page:p.page}):'L'+p.lo+'-L'+p.hi}),'ok'); await loadPins();
  }catch(e){}}

// ------------------------------------------------ PDF rebuild
function topAnchor(off){const L=$('#left'),top=L.getBoundingClientRect().top+(off||0);
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(); if(r.bottom>top+1)return {page:+pg.dataset.page,frac:Math.max(0,(top-r.top)/r.height)};}
  return null;}
function restoreAnchor(a){if(!a)return; const pg=document.getElementById('p'+a.page); if(!pg)return; const L=$('#left');
  L.scrollTop+=pg.getBoundingClientRect().top-L.getBoundingClientRect().top+a.frac*pg.getBoundingClientRect().height;}
async function refreshDoc(){const a=topAnchor(),k=DOC;
  const m=(await api(dq('/api/meta'),{what:'화면 정보 읽기'})).data; META_BY.set(k,m);
  if(k!==DOC)return;                    // switched to another document while waiting - only the cache is refreshed
  const same=META&&m.pages.length===META.pages.length; META=m; drawMeta();
  // The canvas was drawn from the old PDF - it's torn down to show the new PNG first, then redrawn once the new build's PDF is opened.
  if(same){vecReleaseAll(); $$('.pg').forEach((pg,i)=>{const p=META.pages[i]; pg.style.aspectRatio=p.pt_w+' / '+p.pt_h; pg.querySelector('img').src=pageSrc(p);});}
  else buildDoc();
  restoreAnchor(a); vecOpen(); if(document.body.classList.contains('revision-open'))loadRevisions(); await loadPins();}
// On ok_errors|fail, the panel itself is opened right away, not just a toast - once the toast disappeared after 6
// seconds there used to be no way to see it again. Even after closing it, #build-err-chip remains to reopen it (as long as LAST_BUILD_ERR exists).
function showBuildErr(r){LAST_BUILD_ERR=r; if(DOC)BUILD_ERR_BY.set(DOC,r); const b=$('#build-err');
  const title=tr(r.state==='fail'?'빌드 실패 — 화면은 이전 PDF입니다':'PDF를 재빌드했지만 LaTeX 오류가 있습니다');
  b.innerHTML='<div class="row"><b>'+esc(title)+'</b><span class="sp"></span>'+
    '<button class="btn-sm" data-act="err-close" data-tip="이 알림을 닫습니다(다시 보기는 위 배지로)">닫기</button></div>'+
    (r.errors||[]).map(e=>'<div class="dim">'+(e.line?'L'+e.line+' · ':'')+esc(e.msg)+'</div>').join('')+
    '<pre class="nowrap" style="max-height:30vh">'+esc(String(r.log_tail||r.log||'').split('\n').slice(-20).join('\n'))+'</pre>';
  b.hidden=false; $('#build-err-chip').hidden=true;}
function hideBuildErr(){$('#build-err').hidden=true; $('#build-err-chip').hidden=!LAST_BUILD_ERR;}
// P0b-01: rebuild is async - the POST returns immediately, and the #build-chip poller (startBuildPolling) shows
// progress, then does the in-place swap and notification once it finishes. A build started by someone else is caught by the same poller.
async function rebuild(){
  try{const {status}=await api(dq('/api/rebuild?async=1'),{method:'POST',what:'PDF 재빌드',expect:[409]});
    if(status===409){toast('이미 다른 곳에서 PDF를 재빌드하는 중입니다 — 끝난 뒤 다시 누르세요','warn');return;}
    $('#build-err').hidden=true;
    // If a request already went out before this POST, its completion is awaited before asking again - that request
    // carries a stale state (ok) and would never turn on 1-second polling. Completion is distinguished by build_seq, so this tab has nothing separate to remember.
    if(BUILD_INFLIGHT){try{await BUILD_INFLIGHT;}catch(e){}}
    await pollBuild();
  }catch(e){}}

// ------------------------------------------------ Help
let HELP_BACK=null;
function openHelp(){const d=$('#help'); if(d.open)return; HELP_BACK=document.activeElement; hideTip(); d.showModal(); toastHost();}
$('#help').addEventListener('close',()=>{if(HELP_BACK&&HELP_BACK.focus)HELP_BACK.focus(); HELP_BACK=null;});

// ------------------------------------------------ Event delegation (no inline handlers)
document.addEventListener('click',e=>{
  const cp=e.target.closest('[data-copy]'); if(cp){copyText(cp.dataset.copy);return;}
  const a=e.target.closest('[data-act]'); if(!a)return;
  const host=a.closest('[data-id]'),id=host?+host.dataset.id:null,inEdit=!!a.closest('.edit');
  const fromMore=!!a.closest('#more');
  if(fromMore&&(a.dataset.close||a.dataset.act==='help'))$('#more').close();
  switch(a.dataset.act){
    case 'side':setSide(!SIDE_OPEN,true);break;
    case 'selmode':setSelMode(!SELMODE);if(SELMODE&&LAYOUT==='narrow'&&!CUR&&!EDIT)setSide(false);break;
    case 'more':openMore();break; case 'more-close':$('#more').close();break;
    case 'size-preset':sizePreset(+a.dataset.i);break;
    case 'm-jump':$('#more').close();goPage($('#m-jump').value);break;
    case 'coach-close':$('#coach').hidden=true;break;
    case 'card-toggle':if(id==null)break; if(OPEN_CARDS.has(id))OPEN_CARDS.delete(id); else OPEN_CARDS.add(id); drawPins();break;
    case 'rebuild':rebuild();break; case 'reload':loadPins();break;
    case 'zoom-in':zoom(1);break; case 'zoom-out':zoom(-1);break; case 'fit':fitW();break;
    case 'theme':cycleTheme();break; case 'lang':switchLang();break; case 'notify-toggle':notifyToggle();break; case 'help':openHelp();break; case 'help-close':$('#help').close();break;
    case 'save':if(!viewerBlocked())savePin();break; case 'cancel':cancelSelection(true);break;
    case 'overlap-append':{const text=$('#note').value.trim();
      if(!text){toast('메모를 먼저 써야 덧붙일 수 있습니다','warn');break;}
      appendToPin(+a.dataset.oid,text);break;}
    case 'overlap-separate':OVERLAP_DISMISSED=a.dataset.key||null;renderOverlapBanner();break;
    case 'wrap':WRAP=!WRAP;savePrefs({wrap:WRAP});renderComposer();renderEdit();break;
    case 'copy-cur':if(CUR)copyText(CUR.name+' L'+CUR.lo+'-L'+CUR.hi);break;
    case 'expand':SNIP_OPEN=!SNIP_OPEN;renderComposer();break;
    case 'level':{const o=inEdit?EDIT:CUR; if(!o)break; useLevel(o,a.dataset.level); if(!inEdit)recomputeOverlap(); inEdit?renderEdit():renderComposer(); break;}
    case 'nudge':{const o=inEdit?EDIT:CUR; if(!o||!nudge(o,a.dataset.dir))break; if(!inEdit)recomputeOverlap(); const r=inEdit?renderEdit:renderComposer; r(); refetchSnip(o,r); break;}
    case 'view':jumpPin(id);break; case 'edit':openEdit(id);break;
    case 'doc':{const inMenu=!!a.closest('#docs-menu'); switchDoc(a.dataset.doc); if(inMenu)$('#docs-menu').close(); break;}
    // ^ inMenu is determined before calling switchDoc() - for a cached document, switchDoc finishes synchronously
    //   through drawDocTabs, and inside that it redraws the open #docs-menu (drawDocsMenu), detaching a from the DOM.
    //   Calling a.closest() after switchDoc would return null, leaving the menu open and blocking the next tab
    //   interaction (a touch regression).
    case 'doc-menu':openDocsMenu();break; case 'docs-menu-close':$('#docs-menu').close();break;
    case 'view-mode':setViewMode(a.dataset.mode);break;
    case 'rev-back':{const b=REV_BACK; REV_BACK=null; setViewMode('manuscript'); if(b&&b!==DOC&&docInfo(b))switchDoc(b); break;}
    case 'outline':toggleOutline();break;
    case 'outline-page':if(LAYOUT==='mid'&&OUTLINE_MID_OPEN)toggleOutline();OUTLINE_SELECTED=Number(a.dataset.index);OUTLINE_ACTIVE_PAGE=Number(a.dataset.page);OUTLINE_PINNED={index:OUTLINE_SELECTED,page:OUTLINE_ACTIVE_PAGE};renderOutline();updateSectionStrip();setViewMode('manuscript');goPage(a.dataset.page);break;
    case 'revision':showRevision(a.dataset.commit);break;
    case 'revision-format':setRevisionFormat(a.dataset.format);break;
    case 'all-docs':SHOW_ALL=!SHOW_ALL;drawPins();break;
    case 'mention-filter':MENTION_ONLY=!MENTION_ONLY;drawPins();break;
    case 'mention-pick':mentionApply(+a.dataset.i);break;
    case 'pin-ref':gotoPinRef(+a.dataset.ref);break;
    case 'assign-new':ASSIGN_NEW.v=a.dataset.v||'agent'; ASSIGN_NEW.touched=true; renderAssignNew(); break;
    case 'assign-edit':if(EDIT){EDIT.assignee=a.dataset.v||'agent'; renderAssignEdit();} break;
    case 'msg-more':{const k=a.dataset.key; if(!k)break; if(MSG_OPEN.has(k))MSG_OPEN.delete(k); else MSG_OPEN.add(k); drawPins(); break;}
    case 'diff-wrap':setDiffWrap(!DIFF_WRAP);break;
    case 'revision-other':toggleRevisionOther();break;
    case 'revision-whole':setRevisionWhole(!REV_SCOPE.whole);break;
    case 'mark-jump':revealCard(id);jumpToCard(id);break;
    case 'close':closePin(id);break; case 'drop':dropPin(id,false);break;
    case 'restore':restorePin(id);break; case 'purge':if(id!=null)purgePin(id);break; case 'unclaim':unclaimPin(id);break;
    case 'kind':{const fromHint=!!a.closest('#c-qhint'); setKind(a.dataset.kind);
      // [질문으로 보내기] hides itself (qHint), which would drop focus to <body> and make Ctrl+Enter do nothing - back to the memo.
      if(fromHint){const n=$('#note'); n.focus({preventScroll:true}); n.setSelectionRange(n.value.length,n.value.length);}
      break;}
    case 'e-kind':if(EDIT){EDIT.kind_req=a.dataset.kind==='question'?'question':'fix'; renderEdit();}break;
    case 'reply-open':if(id!=null)openReply(id);break;
    case 'reply-flip':if(REPLY){REPLY.flip=!REPLY.flip; renderReplyOutcome();}break;
    case 'confirm':if(id!=null)confirmPin(id);break;
    case 'change':if(id!=null)showChange(id);break;
    case 'goto-review':gotoReview();break;
    case 'reply-cancel':closeReply();break; case 'reply-send':sendReply();break;
    case 'thread-more':if(id==null)break; if(THREAD_OPEN.has(id))THREAD_OPEN.delete(id); else THREAD_OPEN.add(id); drawPins();break;
    case 'arc-toggle':{const k=a.dataset.key; if(!k)break; if(ARC_OPEN.has(k))ARC_OPEN.delete(k); else ARC_OPEN.add(k); drawPins(); break;}
    case 'esave':saveEdit();break; case 'ecancel':cancelEdit();break;
    case 'repick':startRepick();break; case 'rp-cancel':cancelRepick();break; case 'rp-apply':applyRepick();break;
    case 'sec-toggle':toggleSec(a.dataset.sec);break;
    case 'done-toggle':toggleSec('done');if(fromMore)revealList('#done-toggle',SEC.done);break;
    case 'trash-open':openTrash();break; case 'trash-close':$('#trash').close();break;
    case 'err-close':hideBuildErr();break;
    case 'build-err-reopen':if(LAST_BUILD_ERR)showBuildErr(LAST_BUILD_ERR);break;
  }
});
$('#doc-select').addEventListener('change',e=>switchDoc(e.target.value));
$('#revision-list').addEventListener('change',e=>{if(e.target.id==='revision-select')showRevision(e.target.value);});
$('#revision-file').addEventListener('change',renderRevisionFile);
document.addEventListener('keydown',e=>{
  if(e.isComposing||e.keyCode===229)return;
  const t=e.target,inField=t&&(t.tagName==='TEXTAREA'||t.tagName==='INPUT'||t.tagName==='SELECT'||t.isContentEditable);
  // Ctrl(Cmd) + = / - / 0 zooms/fits just the PDF page instead of the browser zoom. Left to the browser inside an input field.
  if((e.ctrlKey||e.metaKey)&&!e.altKey&&!inField){const z=zoomKey(e);
    if(z){e.preventDefault(); if(z==='fit')fitW(); else zoom(z==='in'?1:-1); return;}}
  // Document switching (multiple documents): Ctrl+PgUp/PgDn is previous/next, Alt+1...9 is that index (e.code - Option+digit on Mac produces a different character).
  // The selector uses default keyboard handling. Global shortcuts are never used inside an input field.
  if(multiDoc()&&!inField){
    if(e.ctrlKey&&!e.altKey&&!e.metaKey&&(e.key==='PageUp'||e.key==='PageDown')){e.preventDefault(); cycleDoc(e.key==='PageDown'?1:-1); return;}
    if(e.altKey&&!e.ctrlKey&&!e.metaKey&&/^Digit[1-9]$/.test(e.code||'')){const d=DOCS[+e.code.slice(5)-1]; if(d){e.preventDefault(); switchDoc(d.key);} return;}
  }
  if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){
    if(t&&(t.id==='note'||(t.closest&&t.closest('#composer')&&!$('#composer').hidden&&!inField))){e.preventDefault(); if(!viewerBlocked())savePin();}
    else if(t&&t.classList&&t.classList.contains('e-note')){e.preventDefault();saveEdit();}
    else if(t&&t.classList&&t.classList.contains('r-text')){e.preventDefault();sendReply();}
    return;}
  if(e.key==='Enter'&&t&&t.dataset&&t.dataset.copy!==undefined&&!inField){copyText(t.dataset.copy);return;}
  // A span with role=button (a card's #number) is also activated by Enter/Space - sent through the same data-act path as a click.
  if((e.key==='Enter'||e.key===' ')&&t&&t.getAttribute&&/^(button|link)$/.test(t.getAttribute('role')||'')&&t.dataset&&t.dataset.act&&!inField){e.preventDefault();t.click();return;}
  if(e.key==='Escape'){
    if($('#help').open||$('#more').open||$('#docs-menu').open||$('#trash').open)return;
    if(!TIP.hidden){hideTip(); if(!inField)return;}
    if(LAYOUT==='mid'&&OUTLINE_MID_OPEN){e.preventDefault();toggleOutline();return;}
    if(REPICK){cancelRepick();return;}
    if(REPLY){closeReply();return;}
    if(EDIT){cancelEdit();return;}
    if(CUR||!$('#composer').hidden){cancelSelection(true);return;}
    return;}
  if(e.key==='?'&&!inField&&!e.metaKey&&!e.ctrlKey&&!e.altKey){e.preventDefault();openHelp();}
});
boot();
