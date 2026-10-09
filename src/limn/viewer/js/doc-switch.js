// ------------------------------------------------ Switching documents - the navigation sheet, remembered view positions (docs/handbook/domain.md §여러 문서)
// Draws the navigation sheet's document rows: the name and path are user text (translate="no"), the badges UI. One document
// leaves the section out - there is nothing to switch to.
function drawDocsMenu(){$('#ns-docs').hidden=!multiDoc();
  setHtml($('#ns-docs-list'),html`${DOCS.map(d=>{const on=d.key===DOC;
    return html`<button class="dm-item${on?' on':''}" role="option" aria-selected="${on}" data-act="doc" data-doc="${d.key}" data-close="1"><span class="tx"><span class="nm" translate="no">${d.name}${on?ic('check'):''}</span><span class="ph" translate="no">${d.path}</span></span>${docBadge(d)}</button>`;})}`);}
// The phone's navigation sheet (docs/handbook/viewer.md §모바일 레이아웃): documents, [원고 | 변경사항], the page field with the
// page rows under it (drawSheetPages, scrolled to the current page) and the outline, each a destination - picking one goes there and closes the sheet. The focus is the sheet itself (showSheet) and
// the outline's current section shows (navSheetReveal) without hiding the current document's row (else the chosen view); the
// page field gets no focus, so no keyboard covers the sheet.
function openNavSheet(){const d=$('#nav-sheet'); if(d.open)return; hideTip(); drawDocsMenu(); drawNavView(); renderOutline();
  const n=META&&META.pages?META.pages.length:0,f=$('#ns-page-in');
  f.value=''; f.placeholder=String(OUTLINE_ACTIVE_PAGE||1); $('#ns-page-n').textContent=tl('/ {n}쪽',{n}); drawSheetPages();
  showSheet(d); d.scrollTop=0; revealPageRow($('#ns-pages')); const on=(multiDoc()&&d.querySelector('.dm-item.on'))||d.querySelector('#ns-view [aria-checked=true]');
  navSheetReveal(d,on);}
// The outline's current section in the open sheet d: left where it is when it is already in view under the sticky head, else
// the sheet scrolls it towards the middle of that space - but never so far that the current row (keep: the document's or
// the view's) goes under the head, where it would show cut off. The whole sheet scrolls, so the documents above it move too.
function navSheetReveal(d,keep){const cur=d.querySelector('#ns-outline-items .ol-active'); if(!cur)return;
  const head=d.querySelector('.ns-head').getBoundingClientRect().bottom,box=d.getBoundingClientRect(),c=cur.getBoundingClientRect();
  if(c.top>=head&&c.bottom<=box.bottom)return;
  const want=c.top+c.height/2-(head+box.bottom)/2,room=keep?keep.getBoundingClientRect().top-head:Infinity;
  d.scrollTop+=Math.max(0,Math.min(want,room));}
// The navigation sheet's view switch: the view on screen is the checked radio.
function drawNavView(){const rev=document.body.classList.contains('revision-open');
  for(const b of $$('#ns-view [role=radio]')){const on=(b.dataset.mode===VIEW_MODE.REVISIONS)===rev; b.setAttribute('aria-checked',String(on)); b.classList.toggle('on',on);}}
// The phone's position button (docs/handbook/viewer.md §모바일 레이아웃): [본문 3/25 ▾] - the document's name only with several
// documents on a 400px-or-wider phone, the reading line's page of the pages, '–/–' before they are known, and '변경사항' in the
// changes view - as {name, pages, label}; label is its accessible name. Pure but for tr/tl.
function posLabel(doc,page,n,multi,wide,mode){
  if(mode===VIEW_MODE.REVISIONS)return {name:'',pages:tr('변경사항'),label:tr('이동')+' · '+tr('변경사항')};
  const name=multi&&wide?doc:'',p=n?page:'–',m=n?n:'–';
  return {name,pages:p+'/'+m,label:name?tl('이동 · {doc} · {page} / {n}쪽',{doc:name,page:p,n:m}):tl('이동 · {page} / {n}쪽',{page:p,n:m})};}
// Draws [본문 3/25 ▾] from the document on screen, the reading line's page and the view (posLabel), with a dot when another
// document's manuscript is newer or building. The button is translate="no" (a document name), so its UI words are tr()'d here.
function drawPos(){const b=$('#btn-pos'); if(!b)return; const cur=docInfo(DOC),n=META&&META.pages?META.pages.length:0;
  const L=posLabel(cur?cur.name:'',OUTLINE_ACTIVE_PAGE||1,n,multiDoc(),innerWidth>=400,document.body.classList.contains('revision-open')?VIEW_MODE.REVISIONS:VIEW_MODE.MANUSCRIPT);
  const nm=$('#btn-pos-n'); nm.textContent=L.name; nm.hidden=!L.name; $('#btn-pos-p').textContent=L.pages;
  b.setAttribute('aria-label',L.label); b.dataset.tip=tr('문서·보기·쪽·목차로 갑니다');
  $('#btn-pos-dot').hidden=!DOCS.some(d=>d.key!==DOC&&(d.stale_build||d.building));}
// Viewed position: page/fraction anchored at the top, page width, whether zoomed manually in compact, horizontal scroll. Kept in sessionStorage so it survives a reload.
function saveView(){if(!DOC||!META||!$('#doc .pg'))return; const a=topAnchor();
  VIEW_BY.set(DOC,{page:a?a.page:1,frac:a?a.frac:0,w:W,zoomed:ZOOMED,sl:$('#left').scrollLeft,lay:LAYOUT});
  if(multiDoc()){try{sessionStorage.setItem('pinDocView',JSON.stringify(Array.from(VIEW_BY.entries())));}catch(e){}}}
function loadViews(){if(!multiDoc())return; try{const a=JSON.parse(sessionStorage.getItem('pinDocView')||'[]');
  if(Array.isArray(a))a.forEach(x=>{if(Array.isArray(x)&&docInfo(x[0])&&x[1]&&typeof x[1]==='object')VIEW_BY.set(x[0],x[1]);});}catch(e){}}
// The page width is decided first (buildDoc builds pages using W). Only a width viewed in the same layout is restored - so a width fit for a folded screen is never applied on desktop.
function applyViewWidth(v){if(v&&typeof v.w==='number'&&v.lay===LAYOUT&&(LAYOUT===LAYOUT_MODE.WIDE||v.zoomed)){W=v.w; ZOOMED=LAYOUT!==LAYOUT_MODE.WIDE&&!!v.zoomed; return true;}
  ZOOMED=false; return false;}
function restoreView(v){if(!v)return; restoreAnchor({page:v.page,frac:v.frac}); if(typeof v.sl==='number')$('#left').scrollLeft=v.sl;}
addEventListener('pagehide',saveView);
// Switches documents. Remembers the current view and draft, then opens only the destination document's draft.
// If a meta cache exists, that document is drawn immediately without waiting, then the latest meta is fetched in the background, and pages are swapped only if the build changed.
// A document that cannot be opened says so on the status line, with [다시 시도] when the server could not be reached.
async function switchDoc(k){
  if(!k||k===DOC||!docInfo(k))return; const seq=++SWITCHSEQ; searchLeave();   // the search belongs to the document left (search.js)
  if(document.body.classList.contains('revision-open'))setViewMode(VIEW_MODE.MANUSCRIPT);
  saveView(); parkDraft(); cancelRepick(); if(COMPOSE.current||!$('#composer').hidden)cancelSelection(false);
  if(EDITOR.current&&!editDirty())cancelEdit();
  let m=META_BY.get(k),cached=!!m;
  if(!m){try{m=(await api(dq('/api/meta',k),{what:'문서 열기',where:NOTICE_HOST.LINE,retry:()=>{switchDoc(k);}})).data;}catch(e){if(seq===SWITCHSEQ)restoreDraft(); return;} if(seq!==SWITCHSEQ)return;}
  DOC=k; META=m; META_BY.set(k,m); savePrefs({lastDoc:k}); setHash(k);
  hideTip(); showDoc(VIEW_BY.get(k)); openDraftDoc();
  if(cached){try{const f=(await api(dq('/api/meta',k),{what:'문서 열기',silent:true})).data;
    if(seq===SWITCHSEQ&&DOC===k){const changed=f.pages_build!==META.pages_build||f.pages.length!==META.pages.length;
      META_BY.set(k,f); if(changed)await refreshDoc(f); else{META=f; drawMeta();}}}catch(e){}}
}
// Redraws the screen from the current META (tab switching), including open and done rows from this document before the background refresh.
// The build chip, error panel, and auto-polling baseline are switched to that document's values too.
function showDoc(v){
  drawMeta(); const hadW=applyViewWidth(v); buildDoc(); if(!hadW)autoW(); restoreView(v);
  if(!v&&$('#left'))$('#left').scrollTop=0;
  PINS=OPEN_ALL.filter(p=>pdoc(p)===DOC); DONE=DONE_ALL.filter(p=>pdoc(p)===DOC);
  drawPins(); marks(); drawDocTabs();
  $('#outline-items').textContent=tr('PDF 목차를 읽는 중입니다.');
  if(document.body.classList.contains('revision-open'))loadRevisions();
  vecOpen();
  resetBuildForDoc();   // if a previous document's request is still in flight, queue after it
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
  const k=pdoc(p),opening=switchDoc(k),visit=SWITCHSEQ;
  opening.then(()=>{if(DOC===k&&visit===SWITCHSEQ)then(id);}); return true;}
