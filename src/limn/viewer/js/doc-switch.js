// ------------------------------------------------ Switching documents - the navigation sheet, remembered view positions (docs/handbook/domain.md §여러 문서)
// Draws the navigation sheet's document rows: the name and path are user text (translate="no"), the badges UI. One document
// leaves the section out - there is nothing to switch to.
function drawDocsMenu(){$('#ns-docs').hidden=!multiDoc();
  setHtml($('#ns-docs-list'),html`${DOCS.map(d=>{const on=d.key===DOC;
    return html`<button class="dm-item${on?' on':''}" role="option" aria-selected="${on}" data-act="doc" data-doc="${d.key}" data-close="1"><span class="tx"><span class="nm" translate="no">${d.name}${on?ic('check'):''}</span><span class="ph" translate="no">${d.path}</span></span>${docBadge(d)}</button>`;})}`);}
// The phone's navigation sheet (docs/handbook/viewer.md §모바일 레이아웃): documents, [원고 | 변경사항], the page field with the
// page rows under it (drawSheetPages, scrolled to the current page) and the outline, each a destination - picking one goes there and closes the sheet. The focus is the sheet itself (showSheet) and
// the outline's current section shows in the outline's own scroll while the rest keeps its place (navSheetReveal); the page field
// gets no focus, so no keyboard covers the sheet.
function openNavSheet(){const d=$('#nav-sheet'); if(d.open)return; hideTip(); drawDocsMenu(); drawNavView(); markOutline();   // its rows are drawn already (renderOutline when the outline was read): only the mark moves
  const n=META&&META.pages?META.pages.length:0,f=$('#ns-page-in');
  f.value=''; f.placeholder=String(OUTLINE_ACTIVE_PAGE||1); $('#ns-page-n').textContent=tl('/ {n}쪽',{n}); drawSheetPages();
  showSheet(d); revealPageRow($('#ns-pages')); tipCutTitles($('#ns-pages')); navSheetReveal(d);}
// The outline's current section in the open sheet d (docs/handbook/viewer.md §모바일 레이아웃): the sheet's outline is fitted around
// its current row (navSheetFit). Nothing but the sheet and its list scroll, and the focus stays on the sheet.
function navSheetReveal(d){const rows=navSheetRows(),cur=$('#ns-outline-items').querySelector(':scope>.ol-active');
  navSheetFit(d,cur?rows.indexOf(/** @type {HTMLElement} */(cur)):0,true);}
/** @returns {HTMLElement[]} the rows of the sheet's outline (the unread entries' note is not one) */
function navSheetRows(){return /** @type {HTMLElement[]} */([...$('#ns-outline-items').querySelectorAll(':scope>button')]);}
/** Fits the open sheet d to its outline's row `at` (docs/handbook/viewer.md §모바일 레이아웃). The open sheet is a column whose top
 * part - the head with the search, the documents, the view, the page field and its list - keeps its place, and the outline's rows
 * take what is left and scroll on their own (responsive.css). They show whole rows around `at` - centred on it, or from it down
 * (navSheetWindow) - and the list is made exactly as tall as they are, so no row is cut under the outline's filter or at its foot.
 * Only where the top part leaves less than three rows (several documents on a small phone, or the keyboard up) does the sheet
 * scroll too, by whole parts, with the current row of the documents (else the view) pinned under the head over what the step
 * brought there (navSheetStep), so no row is cut by the head or left half behind that row; the outline's foot gets the room the
 * last step needs. Fitted again after a filter's results and when the sheet's height changes.
 * @param {HTMLElement} d @param {number} at @param {boolean} centre */
function navSheetFit(d,at,centre){const list=/** @type {HTMLElement} */($('#ns-outline-items')),sec=/** @type {HTMLElement} */($('#ns-outline'));
  const head=/** @type {HTMLElement} */(d.querySelector('.ns-head')),R=(/** @type {Element} */e)=>e.getBoundingClientRect();
  list.style.maxHeight=list.style.minHeight=sec.style.flex=sec.style.paddingBottom=''; d.scrollTop=0;
  d.style.setProperty('--ns-head-h',head.offsetHeight+'px');
  const rows=navSheetRows(); if(sec.hidden||!rows.length)return;
  const c=Math.min(rows.length-1,Math.max(0,at)),room=list.clientHeight;
  // the rows a window can reach (each is a touch row, at least 44px), measured in the list's content
  const k=Math.ceil(room/44)+3,from=Math.max(0,c-k),o=R(list).top-list.scrollTop;
  const geo=rows.slice(from,c+k+1).map(r=>{const b=R(r); return {top:b.top-o,bottom:b.bottom-o};}),i=c-from,n=geo.length-1;
  const least=/** @type {[number,number]} */(centre?[Math.max(0,i-1),Math.min(n,i+1)]:[i,Math.min(n,i+2)]),tall=(/** @type {[number,number]} */w)=>geo[w[1]].bottom-geo[w[0]].top;
  const short=room<tall(least),w=short?least:navSheetWindow(geo,i,room,!centre),h=tall(w);
  list.style.maxHeight=h+'px'; list.scrollTop=geo[w[0]].top;
  if(!short)return;
  list.style.minHeight=h+'px'; sec.style.flex='none';
  const need=d.scrollHeight-d.clientHeight; if(need<=0)return;
  const top=R(head).bottom,keep=/** @type {HTMLElement} */(d.querySelector('#ns-docs:not([hidden]) .dm-item.on')||d.querySelector('#ns-view')),K=R(keep);
  const parts=[...d.querySelectorAll('#ns-docs,#ns-docs .dm-item,#ns-view,#ns-page,#ns-pages,#ns-outline')].filter(e=>e.getClientRects().length)
    .map(e=>R(e).top-top).sort((x,y)=>x-y);
  const by=navSheetStep(parts,need,{top:K.top-top,height:K.height,end:keep.matches('.dm-item')&&keep.parentElement?R(keep.parentElement).bottom-top:Infinity});
  if(by>need)sec.style.paddingBottom=(parseFloat(getComputedStyle(sec).paddingBottom)+by-need)+'px';   // padding: a margin collapses through the sheet's end
  d.scrollTop=by;}
// The keyboard coming up or going changes the sheet's height (--vvh, layout.js, which runs first): the outline is fitted again from
// the row at its top, so no row is left cut at the new edges.
for(const t of [window.visualViewport,window])if(t)t.addEventListener('resize',()=>{const d=/** @type {HTMLDialogElement} */($('#nav-sheet'));
  if(d.open)requestAnimationFrame(()=>{if(!d.open)return; const L=$('#ns-outline-items').getBoundingClientRect().top;
    navSheetFit(d,Math.max(0,navSheetRows().findIndex(r=>r.getBoundingClientRect().bottom>L+.5)),false);});});
/** The outline rows the sheet shows (rows: their tops and bottoms in the list, in order; c: the row to show): the most whole rows
 * around c that fit in room, taken one at a time on the side that has fewer, so c stands near the middle - or, down, below c
 * first and above only when the list ends; c alone when no more fit. Pure.
 * @param {{top:number,bottom:number}[]} rows @param {number} c @param {number} room @param {boolean} [down] @returns {[number,number]} */
function navSheetWindow(rows,c,room,down=false){let a=c,b=c;
  for(;;){const up=a>0&&rows[b].bottom-rows[a-1].top<=room,dn=b<rows.length-1&&rows[b+1].bottom-rows[a].top<=room;
    if(!up&&!dn)return [a,b]; if(dn&&(down||!up||b-c<c-a))b++; else a--;}}
/** How far the sheet scrolls when its top part leaves the outline too little (parts: their tops under the head with the sheet at its
 * top, ascending; need: how far it must go at least). Before the pinned row (pin: its top and height, and the end of what holds it)
 * reaches the head, a step stops on a part's top, so the head cuts none. Once it is pinned, a step stops where a part starts right
 * under it, and the parts between lie wholly behind it or the head; past what holds it, the pinned row has gone under the head and
 * a step stops on a part's top again. The least such step, in whole px since the sheet scrolls in them; the last part when there
 * is none. Pure. @param {number[]} parts @param {number} need @param {{top:number,height:number,end:number}|null} [pin] */
function navSheetStep(parts,need,pin=null){let best=Infinity; const ok=(/** @type {number} */s)=>s>=need-.5&&s<best;
  for(const p of parts){
    if(!pin||p<=pin.top+.5||pin.end-p<=.5){if(ok(p))best=p; continue;}
    const s=p-pin.height; if(s>=pin.top-.5&&pin.end-s>=pin.height-.5&&ok(s))best=s;}
  return Math.ceil(best<Infinity?best:parts.length?parts[parts.length-1]:0);}
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
