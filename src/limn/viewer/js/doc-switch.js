// ------------------------------------------------ Switching documents - the navigation sheet, remembered view positions (docs/handbook/domain.md §여러 문서)
// Draws the navigation sheet's document rows: the name and path are user text (translate="no"), the badges UI. One document
// leaves the section out - there is nothing to switch to.
function drawDocsMenu(){$('#ns-docs').hidden=!multiDoc();
  setHtml($('#ns-docs-list'),html`${DOCS.map(d=>{const on=d.key===DOC;
    return html`<button class="dm-item${on?' on':''}" role="option" aria-selected="${on}" data-act="doc" data-doc="${d.key}" data-close="1"><span class="tx"><span class="nm" translate="no">${d.name}${on?ic('check'):''}</span><span class="ph" translate="no">${d.path}</span></span>${docBadge(d)}</button>`;})}`);}
// The phone's navigation sheet (docs/handbook/viewer.md §모바일 레이아웃): documents, [원고 | 변경사항], the page field with the
// page rows under it (drawSheetPages, scrolled to the current page) and the outline, each a destination - picking one goes there and closes the sheet. The focus is the sheet itself (showSheet) and
// the outline's current section shows (navSheetReveal), with the current document's row (else the chosen view) whole above it
// where both fit; the page field gets no focus, so no keyboard covers the sheet.
function openNavSheet(){const d=$('#nav-sheet'); if(d.open)return; hideTip(); drawDocsMenu(); drawNavView(); markOutline();   // its rows are drawn already (renderOutline when the outline was read): only the mark moves
  const n=META&&META.pages?META.pages.length:0,f=$('#ns-page-in');
  f.value=''; f.placeholder=String(OUTLINE_ACTIVE_PAGE||1); $('#ns-page-n').textContent=tl('/ {n}쪽',{n}); drawSheetPages();
  showSheet(d); d.scrollTop=0; revealPageRow($('#ns-pages')); tipCutTitles($('#ns-pages')); const on=(multiDoc()&&d.querySelector('.dm-item.on'))||d.querySelector('#ns-view [aria-checked=true]');
  navSheetReveal(d,on);}
// The outline's current section in the open sheet d, brought into view under the sticky head (navSheetBy). The whole sheet scrolls
// (its scrollTop, so nothing else moves), the documents above the outline with it, and the focus stays on the sheet. Where the sheet
// ends too soon to take the current row of the documents or the view wholly under the head, the outline's section gets the room
// that is missing under it, so that row is not left cut off; a later open measures without it.
function navSheetReveal(d,keep){const cur=d.querySelector('#ns-outline-items .ol-active'),tail=/** @type {HTMLElement} */($('#ns-outline'));
  tail.style.paddingBottom=''; if(!cur)return;
  const max=d.scrollHeight-d.clientHeight-d.scrollTop,by=navSheetBy(d.querySelector('.ns-head').getBoundingClientRect().bottom,
    d.getBoundingClientRect().bottom,cur.getBoundingClientRect(),keep?keep.getBoundingClientRect():null,max);
  if(by>max)tail.style.paddingBottom=(parseFloat(getComputedStyle(tail).paddingBottom)+by-max)+'px';   // padding: a margin collapses through the sheet's end
  d.scrollTop+=by;}
/** How far the sheet scrolls down to show the outline's current row c in the space between the head's bottom edge (head) and the
 * sheet's (bottom), the sheet able to scroll max px further: none when c shows there whole, else towards the middle of that space as
 * far as the sheet goes. The current row of the documents or the view (k) stays whole above it as long as c then shows: only as far
 * as k reaches the head, if that is far enough. Further down - a long outline puts c thousands of px under k - c wins and k goes
 * wholly under the head, never cut off by it: past the middle if the middle alone would cut it, and past max if the sheet ends
 * before that (more than max: the caller adds the room), in whole px since the sheet scrolls in them. Pure.
 * @param {number} head @param {number} bottom @param {{top:number,bottom:number}} c @param {{top:number,bottom:number}|null} k
 * @param {number} [max] */
function navSheetBy(head,bottom,c,k,max=Infinity){if(c.top>=head&&c.bottom<=bottom)return 0;
  const want=Math.min((c.top+c.bottom)/2-(head+bottom)/2,max),room=k?k.top-head:Infinity;
  return Math.max(0,!k||want<=room||c.bottom-room<=bottom?Math.min(want,room):Math.max(want,Math.ceil(k.bottom-head)));}
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
// Viewed position: page/fraction anchored at the top, page scale (K), whether zoomed manually in compact, horizontal scroll. Kept in sessionStorage so it survives a reload.
function saveView(){if(!DOC||!META||!$('#doc .pg'))return; const a=topAnchor();
  VIEW_BY.set(DOC,{page:a?a.page:1,frac:a?a.frac:0,k:K,zoomed:ZOOMED,sl:$('#left').scrollLeft,lay:LAYOUT});
  if(multiDoc()){try{sessionStorage.setItem('pinDocView',JSON.stringify(Array.from(VIEW_BY.entries())));}catch(e){}}}
function loadViews(){if(!multiDoc())return; try{const a=JSON.parse(sessionStorage.getItem('pinDocView')||'[]');
  if(Array.isArray(a))a.forEach(x=>{if(Array.isArray(x)&&docInfo(x[0])&&x[1]&&typeof x[1]==='object')VIEW_BY.set(x[0],x[1]);});}catch(e){}}
// A kept view's scale: its k, or - kept by a release that stored the page width - that width over the widest page m (points);
// 0 when it has neither. Pure.
function viewScale(v,m){return typeof v.k==='number'&&v.k>0?v.k:typeof v.w==='number'&&v.w>0&&m>0?v.w/m:0;}
// The page scale is decided first (buildDoc sizes pages by K). Only a scale viewed in the same layout is restored - so a width fit
// for a folded screen is never applied on desktop; without one the document starts at its saved or default scale (startK).
// Returns whether a kept view decided it.
function applyViewWidth(v){if(v&&v.lay===LAYOUT&&(LAYOUT===LAYOUT_MODE.WIDE||v.zoomed)){const k=viewScale(v,ptMax());
    if(k){K=k; ZOOMED=LAYOUT!==LAYOUT_MODE.WIDE&&!!v.zoomed; return true;}}
  ZOOMED=false; K=startK(); return false;}
function restoreView(v){if(!v)return; restoreAnchor({page:v.page,frac:v.frac}); if(typeof v.sl==='number')$('#left').scrollLeft=v.sl;}
addEventListener('pagehide',saveView);
// Switches documents. Remembers the current view and draft, then opens only the destination document's draft.
// If a meta cache exists, that document is drawn immediately without waiting, then the latest meta is fetched in the background, and pages are swapped only if the build changed.
// A document that cannot be opened says so on the status line, with [다시 시도] when the server could not be reached.
// A focus in the pages (a line's control, the PDF area) stays on the PDF area: the new pages take the focused element away,
// and from nothing (body) the next Tab went to the first page's line and scrolled there.
async function switchDoc(k){
  if(!k||k===DOC||!docInfo(k))return; const seq=++SWITCHSEQ; searchLeave();   // the search belongs to the document left (search.js)
  const a=document.activeElement,inPages=!!a&&!!a.closest&&!!a.closest('#left');
  if(document.body.classList.contains('revision-open'))setViewMode(VIEW_MODE.MANUSCRIPT);
  saveView(); parkDraft(); cancelRepick(); if(COMPOSE.current||!$('#composer').hidden)cancelSelection(false);
  if(EDITOR.current&&!editDirty())cancelEdit();
  let m=META_BY.get(k),cached=!!m;
  if(!m){try{m=(await api(dq('/api/meta',k),{what:'문서 열기',where:NOTICE_HOST.LINE,retry:()=>{switchDoc(k);}})).data;}catch(e){if(seq===SWITCHSEQ)restoreDraft(); return;} if(seq!==SWITCHSEQ)return;}
  DOC=k; META=m; META_BY.set(k,m); savePrefs({lastDoc:k}); setHash(k);
  hideTip(); showDoc(VIEW_BY.get(k)); openDraftDoc();
  if(inPages&&(!document.activeElement||document.activeElement===document.body))searchToPage();
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
