// ------------------------------------------------ Switching documents - the documents sheet, remembered view positions (docs/handbook/domain.md §여러 문서)
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
function applyViewWidth(v){if(v&&typeof v.w==='number'&&v.lay===LAYOUT&&(LAYOUT===LAYOUT_MODE.WIDE||v.zoomed)){W=v.w; ZOOMED=LAYOUT!==LAYOUT_MODE.WIDE&&!!v.zoomed; return true;}
  ZOOMED=false; return false;}
function restoreView(v){if(!v)return; restoreAnchor({page:v.page,frac:v.frac}); if(typeof v.sl==='number')$('#left').scrollLeft=v.sl;}
addEventListener('pagehide',saveView);
// Switches documents. Remembers the current view and draft, then opens only the destination document's draft.
// If a meta cache exists, that document is drawn immediately without waiting, then the latest meta is fetched in the background, and pages are swapped only if the build changed.
async function switchDoc(k){
  if(!k||k===DOC||!docInfo(k))return; const seq=++SWITCHSEQ;
  if(document.body.classList.contains('revision-open'))setViewMode(VIEW_MODE.MANUSCRIPT);
  saveView(); parkDraft(); cancelRepick(); if(COMPOSE.current||!$('#composer').hidden)cancelSelection(false);
  if(EDITOR.current&&!editDirty())cancelEdit();
  let m=META_BY.get(k),cached=!!m;
  if(!m){try{m=(await api(dq('/api/meta',k),{what:'문서 열기'})).data;}catch(e){if(seq===SWITCHSEQ)restoreDraft(); return;} if(seq!==SWITCHSEQ)return;}
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
