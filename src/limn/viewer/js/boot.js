// ------------------------------------------------ Document
// Starts the viewer: language, theme and layout, the document list and meta, pages, pins, this tab's kept draft, the first-visit
// hint (touch or mouse), polling and notifications, then a pin link from the hash (#doc=&pin=) if there was one.
async function boot(){i18nStart();
  // A link /#doc=<key>&pin=<n>[&act=restore] (a notification clicked with no tab open) is read first: the boot below rewrites the
  // hash to #doc=<key> on an instance with several documents, which used to lose pin= (0.2.1 and earlier).
  const link=takeLinkHash();
  applyTheme(); applyLayout();
  // There's no keyboard shortcut on a touch device - "핀 저장 Ctrl+Enter" would just get clipped at phone width.
  setHtml($('#btn-save'),saveBtnLabel());
  await loadDocs(); DOC=initialDoc();
  try{META=(await api(dq('/api/meta'),{what:'화면 정보 읽기',where:NOTICE_HOST.LINE})).data;}catch(e){return;}
  if(META.doc)DOC=META.doc; META_BY.set(DOC,META); loadViews(); const v=VIEW_BY.get(DOC);
  if(multiDoc()){setHash(DOC); savePrefs({lastDoc:DOC});}
  drawMeta(); applySideWidth(); applyOutlineState(); const hadW=applyViewWidth(v); buildDoc(); if(!hadW)autoW(); vecBoot(); const pinsLoaded=await loadPins();
  restoreView(v); drawDocTabs(); updateSectionStrip(); restoreDraft();   // the page count is there before the first scroll (mid shows it in the nav bar)
  if(MQ_COARSE.matches)coach('touch','PDF를 길게 누르면 그 문단을 고릅니다 · [선택]을 켜면 끌어서 고릅니다');
  else coach('mouse','PDF를 끌어서 고칠 곳을 고르세요');   // first-time mouse users had no hint how to pin (the PDF also shows a crosshair)
  // A failed first read has no pin baseline; the light poll must retry even when meta has not changed.
  if(pinsLoaded){LAST_PINS_REV=META.pins_rev; LAST_SRC_MTIME=META.src_sig||META.src_mtime;}
  BUILD.lastSeq=(typeof META.build_seq==='number')?META.build_seq:0;   // the build count this tab has already "seen"
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
// The main sync badge (--git-pull) from a meta's `sync` {state, reason}: hidden when off or current, a warning when blocked or
// failed. It also keeps s for the status line (STATUS_SYNC), which words the same state on compact bands.
function updateSyncBadge(s){STATUS_SYNC=s||null; const b=$('#meta-sync'); if(!b)return;
  if(!s||s.state===SYNC_STATE.DISABLED||s.state===SYNC_STATE.CURRENT){b.hidden=true; return;}
  b.hidden=false; b.classList.toggle('badge-warning',s.state===SYNC_STATE.BLOCKED||s.state===SYNC_STATE.ERROR);
  const reason=tr(SYNC_REASON[s.reason]||s.reason||'');
  b.textContent=tr(s.state===SYNC_STATE.UPDATING?'최신 main PDF 반영 중':s.state===SYNC_STATE.UPDATED?'최신 main 반영됨':
    s.state===SYNC_STATE.DEFERRED?'빌드 뒤 main 확인':s.state===SYNC_STATE.CHECKING?'main 확인 중':'main 동기화 확인 필요');
  b.dataset.tip=reason?(b.textContent+' · '+reason+' · '+tr('기존 PDF가 보일 수 있습니다')):b.textContent;
}
function isViewer(){return !!(typeof META!=='undefined'&&META&&META.me&&META.me.role===ROLE.VIEWER);}
/** Whether this server-provided identity is a person with write access; server authorization remains authoritative. */
function canConfirmReview(){return isHuman()&&!isViewer();}
/** Explain why this screen cannot confirm a reviewed result, without offering a request the server will refuse. */
function confirmAccessText(){return tr(isViewer()?'보기 권한만 있습니다 — 편집 권한이 있는 사람이 확인합니다':
  '에이전트 권한으로 접속 중입니다 — 사람 신원으로 접속해 확인하세요');}
// A state change the viewer role cannot make (the server answers 403 anyway): say so once instead of sending it, in a banner
// over the composer while one is open, else on top of the panel (bannerHost).
function viewerBlocked(){if(!isViewer())return false; bannerNote(undefined,'보기 권한(viewer)만 있는 계정이라 바꿀 수 없습니다',NOTICE_KIND.WARN); return true;}
// Paints the header and the info line from META (the document on screen): names, page count, commit, build time, who is
// signed in, the stale and sync badges and the pins.md help text; the rebuild button is hidden unless the document builds
// from source. Reads META only and sends nothing.
function drawMeta(){
  document.body.classList.toggle('no-rebuild',!buildsFromSource(META.kind));   // only a LaTeX document builds from source; a view-only PDF and a figure redraw when their files change
  document.body.classList.toggle('role-viewer',isViewer());
  $('#m-download').disabled=!META.pages_build;   // no build on screen, no PDF to save
  $('#meta-main').textContent=META.main; $('#meta-pages').textContent=tl('{n}쪽',{n:META.pages.length});
  const head=commitShown(META.head); $('#meta-head').textContent=head; $('#meta-head-w').hidden=!head;
  $('#meta-built').textContent=String(META.built_at||'').slice(0,16).replace('T',' ');
  const me=META.me||/** @type {Me} */({});
  setHtml($('#me'),html`${avatar(me)}<span class="au-n" translate="no">${who(me)}</span>`);
  $('#me').dataset.tip=tl('지금 이 화면을 쓰는 사람: {name}. 핀을 저장·수정·완료하면 이 이름으로 기록됩니다',{name:(isAgent(me)?who(me):me.name||'')+(me.login&&me.login!==LOCAL_LOGIN?' ('+me.login+')':'')});
  updateStaleBadge(META);
  updateSyncBadge(META.sync);
  $('#help-pins-md').textContent=META.pins_md||'';
  setHtml($('#more-info'),moreInfo(META,me));
}
// [더보기]'s meta (compact, where #bar2's line is hidden) as two lines: the file · pages · commit, then the build time · me. Each
// piece keeps its words together and the lines break only between pieces; a piece longer than the line (a long file name)
// breaks after / . _ - (<wbr>), never cut - it was one line cut at '…', its rest only in a 500ms long-press tip (UX audit P4.2).
// The words are the viewer's (tr/tl), the names the user's: #more-info is translate="no".
function moreInfo(m,me){const built=String(m.built_at||'').slice(5,16).replace('T',' ');
  const piece=t=>html`<span class="mc">${String(t).split(/([/._-])/).map((s,i)=>i%2?html`${s}<wbr>`:s)}</span>`;
  const line=a=>a.filter(Boolean).map((t,i)=>i?html` · ${piece(t)}`:piece(t));
  return html`${line([m.main,tl('{n}쪽',{n:m.pages.length}),commitShown(m.head)])}<br>${line([built&&built!=='?'?built+' '+tr('빌드'):'',tl('나: {name}',{name:who(me)})])}`;}
// The commit a meta names, or '' when it names none: the server sends '-' for a manuscript outside Git and nothing before
// the first build. The meta lines leave that piece out with its separator - they read 'main.tex · 2쪽 · -'. Pure.
function commitShown(h){const s=String(h==null?'':h).trim(); return s==='-'||s==='?'?'':s;}
