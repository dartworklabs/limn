// ------------------------------------------------ Multiple documents - list/tabs/links (docs/handbook/domain.md §여러 문서)
function multiDoc(){return DOCS.length>1;}
function docInfo(k){return DOCS.find(d=>d.key===k)||null;}
/** @param {Pin} p */
function pdoc(p){return (p&&p.doc)||DEFAULT_DOC;}
function isRegion(p){return !!p&&(p.kind==='region'||(!p.file&&!!p.pdf));}
// Appends ?doc=<key> to a document-scoped path (the server treats it as the first document if absent).
function dq(u,k){k=k||DOC; if(!k)return u; return u+(u.indexOf('?')<0?'?':'&')+'doc='+encodeURIComponent(k);}
function hashDoc(){const m=/(?:^#|[#&])doc=([a-z0-9-]{1,24})(?:&|$)/.exec(location.hash||''); return m?m[1]:null;}
// Puts #doc=<key> in the address (several documents only) without a new history entry, keeping the entry's state - the back
// layer's pushed entry must stay recognizable after a document switch.
function setHash(k){if(!multiDoc())return; const h='#doc='+k; if(location.hash!==h)history.replaceState(history.state,'',location.pathname+location.search+h);}
// The document shown first: URL hash (link sharing/reload) > the last document viewed on this device > the first document.
function initialDoc(){const h=hashDoc(); if(h&&docInfo(h))return h; const l=prefs().lastDoc; if(l&&docInfo(l))return l;
  return DOCS.length?DOCS[0].key:null;}
async function loadDocs(){try{const r=(await api('/api/docs',{what:'문서 목록',silent:true})).data;
    DOCS=Array.isArray(r.docs)?r.docs:[]; DEFAULT_DOC=r.default||(DOCS[0]&&DOCS[0].key)||'main';}catch(e){DOCS=[];}
  document.body.classList.toggle('docs-multi',multiDoc()); $('#all-docs').hidden=!multiDoc();}
function docCount(k){return OPEN_ALL.filter(p=>pdoc(p)===k).length;}
// A document's build state in the documents lists: a spinner while it builds, else a dot when its manuscript is newer than its
// PDF; null for neither.
function docState(d){return d.building?html`<span class="spin" aria-label="빌드 중"></span>`:d.stale_build?html`<span class="ddot" aria-label="원고 수정됨"></span>`:null;}
// A document's marks in the documents list: its build state (docState), view-only 'PDF', figure '그림', and its open-pin count.
function docBadge(d){const n=docCount(d.key);
  const pdf=d.view_only?html`<span class="badge dvo" aria-label="보기 전용">PDF</span>`:'';
  const fig=isFigureKind(d.kind)?html`<span class="badge dfig" aria-label="${tr('그림 문서')}">${tr('그림')}</span>`:'';
  return html`${docState(d)}${pdf}${fig}<span class="badge badge-secondary dcnt${n?'':' z'}" aria-label="${tl('열린 핀 {n}',{n})}">${n}</span>`;}
// A document link's description: name, path, what kind of document it is, and its build state. The link is user text
// (translate="no", the name), so the UI words are translated here.
function docTip(d){return d.name+' · '+d.path+(d.view_only?tr(' · 보기 전용 PDF(줄 번호 없이 쪽·영역으로 핀을 남깁니다)'):'')+
  (isFigureKind(d.kind)?' · '+tr('그림 문서(드래그하면 요소와 그 요소를 그린 코드 줄을 찾습니다)'):'')+
  (d.building?tr(' · 빌드 중'):(d.stale_build?tr(' · 원고가 이 PDF보다 새롭습니다(그 탭에서 [PDF 재빌드])'):''));}
// Draws the document choosers: the select, the nav bar's links, the phone's position button (drawPos), an open navigation
// sheet's rows and an open documents popover's. A document's name is user text (translate="no"); the UI words beside it (build
// state, page count, the description) are translated here. A link's name is a span (.lbl) so CSS can trim it to its cap height,
// as the view tabs'. The links are replaced in front of [+N] (#doc-more), which stays in place - a redraw by polling does not
// take the focus from it - and a link that had the focus gives it to its document's new link; then the row is fitted (docFit).
function drawDocTabs(){
  const box=$('#doc-select');
  setHtml(box,html`${DOCS.map(d=>html`<option translate="no" value="${d.key}">${d.name}${d.building?tr(' · 빌드 중'):d.stale_build?tr(' · 원고 수정됨'):''}</option>`)}`);
  if(DOC)box.value=DOC;
  const row=$('#doc-links'),more=$('#doc-more'),had=/** @type {HTMLElement|null} */(document.activeElement),
    was=had&&had!==more&&row.contains(had)?had.dataset.doc:null,links=document.createElement('div');
  setHtml(links,html`${DOCS.map(d=>{const count=d.n_pages?html`<span class="doc-link-count">${tl('{n}쪽',{n:d.n_pages})}</span>`:'';
    return html`<button translate="no" data-act="doc" data-doc="${d.key}" aria-current="${d.key===DOC?'page':'false'}" title="${docTip(d)}"><span class="lbl">${d.name}</span>${count}</button>`;})}`);
  for(const a of row.querySelectorAll(':scope>[data-doc]'))a.remove();
  more.before(...links.children);
  drawPos(); docFit();
  const back=was?/** @type {HTMLElement[]} */([...row.querySelectorAll(':scope>[data-doc]')]).find(a=>a.dataset.doc===was&&!a.hidden):null;
  if(back)back.focus({preventScroll:true});
  if($('#nav-sheet').open)drawDocsMenu();
  if(!$('#doc-pop').hidden)drawDocMenu();}

// ---- The document row's fit (docs/handbook/viewer.md §문서 링크가 넘칠 때)
// Which links the row shows, as indices into w: every one when they all fit room - w are the links' widths, gap the row's gap -
// else the first k in order with [+N] after them (moreW(N): its width saying N), k as large as fits, and the current
// document's link (index cur, -1 for none) always among them: when it would be hidden it takes the k-th place. With no room
// even for one link and the button, the current link (else the first) alone. Pure.
function docTabsShown(w,gap,cur,room,moreW){
  const n=w.length,all=w.map((_,i)=>i),width=a=>a.reduce((s,i)=>s+w[i],0)+gap*Math.max(0,a.length-1),fits=x=>x<=room+0.01;
  if(fits(width(all)))return all;
  for(let k=n-1;k>=1;k--){const a=all.slice(0,k); if(cur>=k)a[k-1]=cur; if(fits(width(a)+gap+moreW(n-k)))return a;}
  return [cur>=0?cur:0];}
let DOC_FIT='';   // the row's last fit ('<shown keys>|<N>'): a measure that changes nothing writes nothing and re-fits nothing
// Fits the nav bar's document row to the room the bar leaves it: as many whole links as fit, in DOCS order, the current one
// always among them, and [+N] for the N left out (docTabsShown) - no link is cut and the row never scrolls. The room is the
// bar's content width less every other control at its own width and the gaps between them, two of them counted as they would
// stand: the search at its folded magnifier (the field gives way before the links, as it gives way before every neighbour -
// searchFit takes what the row leaves) and the paper's name at its whole width up to its max-width (the links give way before
// it is shortened). Measured with every link shown, then each hidden or shown whole; when the fit changes the search is fitted
// again, and an open popover whose button has gone shuts. Where the row is not drawn (the phone, one document) nothing is.
// Nothing that has the focus is hidden to be measured (a hidden control loses it): the links are measured all shown, the
// button where it stands. A link or the button that has the focus and is left out gives it to the button or the current link.
function docFit(){const row=$('#doc-links'),more=$('#doc-more'),nav=$('#doc-nav'),lbl=/** @type {HTMLElement} */(more.firstElementChild),
    tabs=/** @type {HTMLElement[]} */([...row.querySelectorAll(':scope>[data-doc]')]),px=v=>parseFloat(v)||0,had=document.activeElement;
  let fit='';
  if(row.getClientRects().length&&tabs.length>1){
    const cs=getComputedStyle(nav),rs=getComputedStyle(row); let used=0,n=0;
    for(const k of /** @type {HTMLElement[]} */([...nav.children])){if(k===row||!k.getClientRects().length)continue; const m=getComputedStyle(k); n++;
      if(k.id==='doc-search'){used+=px(getComputedStyle($('#search-open')).width); continue;}   // its margin is the bar's one flexible gap
      if(k.id==='paper-identity'){const t=/** @type {HTMLElement} */(k.lastElementChild);
        used+=Math.min(px(m.maxWidth)||Infinity,k.getBoundingClientRect().width+Math.max(0,t.scrollWidth-t.clientWidth));}
      else used+=k.getBoundingClientRect().width;
      if(!k.matches('#nav-page,#nav-side'))used+=px(m.marginLeft)+px(m.marginRight);}   // those two stand after the flexible gap
    const room=nav.clientWidth-px(cs.paddingLeft)-px(cs.paddingRight)-px(cs.columnGap)*n-used-px(rs.marginLeft)-px(rs.marginRight);
    tabs.forEach(a=>{a.hidden=false;});
    const w=tabs.map(a=>a.getBoundingClientRect().width),gap=px(rs.columnGap),seen=new Map(),was=more.hidden;
    const moreW=N=>{if(!seen.has(N)){lbl.textContent='+'+N; more.hidden=false; seen.set(N,more.getBoundingClientRect().width); more.hidden=was;} return seen.get(N);};
    const shown=docTabsShown(w,gap,tabs.findIndex(a=>a.dataset.doc===DOC),room,moreW),N=tabs.length-shown.length;
    tabs.forEach((a,i)=>{a.hidden=!shown.includes(i);});
    if(N){lbl.textContent='+'+N; more.setAttribute('aria-label',tl('문서 {n}개 더 보기',{n:N}));}
    more.hidden=!N; fit=shown.map(i=>tabs[i].dataset.doc).join()+'|'+N;}
  else{tabs.forEach(a=>{a.hidden=false;}); more.hidden=true;}
  const lost=had instanceof HTMLElement&&(row.contains(had)?had.hidden:!more.hidden?false:$('#doc-pop').contains(had));
  if(more.hidden)closeDocMenu(false);
  if(lost){const to=more.hidden?tabs.find(a=>a.getAttribute('aria-current')==='page'):more; if(to)to.focus({preventScroll:true});}
  if(fit!==DOC_FIT){DOC_FIT=fit; searchFit();}}
// Re-fits once a frame when the bar or a control beside the row changes size (the window, the pin panel, the page count, the
// status line in the short band, the search) - never on the row's own size, which the fit sets - and when a font arrives.
let DOC_FIT_FRAME=0;
function docFitSoon(){if(!DOC_FIT_FRAME)DOC_FIT_FRAME=requestAnimationFrame(()=>{DOC_FIT_FRAME=0; docFit();});}
if(window.ResizeObserver){const o=new ResizeObserver(docFitSoon); o.observe($('#doc-nav')); o.observe($('#status'));
  for(const k of $$('#doc-nav>*'))if(k.id!=='doc-links')o.observe(k);}
document.fonts.addEventListener('loadingdone',docFit);

// ---- The documents popover ([+N], docs/handbook/viewer.md §문서 링크가 넘칠 때)
// Every document in DOCS order, one row each: the current one's check, the name (user text) with its build state (docState),
// the page count and, for the first nine, the Alt+number that picks it. Choosing a row is a document link's click (data-act
// "doc": switchDoc). With nine documents or more a field on top filters the rows by name or path.
let DOC_MENU_DRAWING=false;   // the rows are being replaced: the focus leaving a row then is not the focus leaving the popover
// Draws the popover's rows; a redraw (polling) keeps the filter, the list's scroll and the focus on the same document's row.
function drawDocMenu(){const list=$('#doc-pop-list'),had=/** @type {HTMLElement|null} */(document.activeElement),
    was=had&&list.contains(had)?had.dataset.doc:null,top=list.scrollTop;
  DOC_MENU_DRAWING=true;
  setHtml(list,html`${DOCS.map((d,i)=>{const on=d.key===DOC;
    return html`<button class="dp-row${on?' on':''}" role="option" aria-selected="${on}" tabindex="${on?0:-1}" data-act="doc" data-doc="${d.key}"><span class="dp-c">${on?ic('check'):''}</span><span class="dp-n"><span class="dp-t" translate="no">${d.name}</span>${docState(d)}</span><span class="dp-p">${d.n_pages?tl('{n}쪽',{n:d.n_pages}):''}</span><span class="dp-k">${i<9?'Alt+'+(i+1):''}</span></button>`;})}`);
  docMenuFilter(); list.scrollTop=top;
  const back=was?/** @type {HTMLElement[]} */([...list.children]).find(r=>r.dataset.doc===was):null; if(back)back.focus({preventScroll:true});
  DOC_MENU_DRAWING=false;}
// Shows the rows whose document's name or path holds the field's text (case folded, as the outline's search), and says so
// when none does.
function docMenuFilter(){const q=/** @type {HTMLInputElement} */($('#doc-pop-in')).value.trim().toLowerCase(); let n=0;
  for(const r of /** @type {HTMLElement[]} */([...$('#doc-pop-list').children])){const d=docInfo(r.dataset.doc||'');
    r.hidden=!!q&&!(d&&(d.name+' '+d.path).toLowerCase().includes(q)); if(!r.hidden)n++;}
  $('#doc-pop-none').hidden=n>0;}
// Opens the popover under [+N]. A mouse or a keyboard gets the focus in the filter when there is one; touch - no keyboard
// comes up - and a list without it get the current document's row, scrolled into view.
function openDocMenu(){const pop=$('#doc-pop'),f=/** @type {HTMLInputElement} */($('#doc-pop-in'));
  hideTip(); closePageList(false); f.hidden=DOCS.length<9; f.value=''; $('#doc-more').setAttribute('aria-expanded','true');
  pop.hidden=false; drawDocMenu(); placeDocMenu();
  const row=/** @type {HTMLElement|null} */($('#doc-pop-list [aria-selected=true]')); if(row)row.scrollIntoView({block:'nearest'});
  const to=!f.hidden&&!MQ_COARSE.matches?f:row||pop; to.focus({preventScroll:true});}
// Puts the open popover under its button, its left edge on the button's and inside the window by 8px, and lets it grow down to
// 8px above the window's bottom (--dp-room); its list scrolls inside that.
function placeDocMenu(){const pop=$('#doc-pop'),more=$('#doc-more'); if(pop.hidden)return;
  if(!more.getClientRects().length){closeDocMenu(false); return;}
  const r=more.getBoundingClientRect(),top=Math.round(r.bottom)+4,w=pop.offsetWidth;
  pop.style.left=Math.max(8,Math.min(Math.round(r.left),innerWidth-8-w))+'px'; pop.style.top=top+'px';
  pop.style.setProperty('--dp-room',Math.max(0,innerHeight-8-top)+'px');}
// Shuts the popover; back gives the focus back to [+N] (Esc, a choice).
function closeDocMenu(back){const pop=$('#doc-pop'),more=$('#doc-more'); if(pop.hidden)return; pop.hidden=true;
  more.setAttribute('aria-expanded','false'); if(back&&more.getClientRects().length)more.focus({preventScroll:true});}
// [+N]'s click: opens the popover, or shuts it when it is open.
function toggleDocMenu(){if($('#doc-pop').hidden)openDocMenu(); else closeDocMenu(false);}
// Keys: ↓ on the button opens the popover (Enter and Space are its click). In the filter ↓ goes to the current row (the first
// shown when it is filtered out) and Enter chooses the first row shown; on a row ↓/↑ move one row, Home/End to the ends, ↑ on
// the first goes back to the filter. Esc is the viewer's (events.js): it shuts the popover with the focus on the button.
$('#doc-more').addEventListener('keydown',e=>{if(e.key==='ArrowDown'&&!e.altKey){e.preventDefault(); if($('#doc-pop').hidden)openDocMenu();}});
$('#doc-pop').addEventListener('keydown',e=>{const t=/** @type {HTMLElement} */(e.target),f=$('#doc-pop-in');
  if(e.isComposing)return;
  const rows=/** @type {HTMLElement[]} */([...$('#doc-pop-list').children]).filter(r=>!r.hidden);
  if(t===f){if(e.key==='ArrowDown'&&rows.length){e.preventDefault(); (rows.find(r=>r.classList.contains('on'))||rows[0]).focus();}
    else if(e.key==='Enter'&&rows.length){e.preventDefault(); rows[0].click();}
    return;}
  const i=rows.indexOf(t); if(i<0)return;
  if(e.key==='ArrowUp'&&i===0&&!f.hidden){e.preventDefault(); f.focus(); return;}
  const to={ArrowDown:i+1,ArrowUp:i-1,Home:0,End:rows.length-1}[e.key]; if(to===undefined)return;
  e.preventDefault(); const r=rows[Math.max(0,Math.min(rows.length-1,to))]; r.focus(); r.scrollIntoView({block:'nearest'});});
$('#doc-pop-in').addEventListener('input',docMenuFilter);
// Tab out of the popover, or a press anywhere outside it and its button, shuts it (the press still does what it does).
// Focus leaving for nowhere is a Tab past the page's last stop - but not the window losing the focus.
$('#doc-pop').addEventListener('focusout',e=>{const to=/** @type {Node|null} */(e.relatedTarget);
  if(DOC_MENU_DRAWING||(!to&&!document.hasFocus()))return;
  if(!to||(!$('#doc-pop').contains(to)&&!$('#doc-more').contains(to)))closeDocMenu(false);});
document.addEventListener('pointerdown',e=>{const t=/** @type {Node} */(e.target);
  if(!$('#doc-pop').hidden&&!$('#doc-pop').contains(t)&&!$('#doc-more').contains(t))closeDocMenu(false);},true);
addEventListener('resize',placeDocMenu);
