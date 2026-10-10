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
// The marks of a document link: its name (.lbl, trimmed to its cap height by CSS as the view tabs' words) and page count.
function docLinkInner(d){const count=d.n_pages?html`<span class="doc-link-count">${tl('{n}쪽',{n:d.n_pages})}</span>`:'';
  return html`<span class="lbl">${d.name}</span>${count}`;}
// What a link's or a popover row's inside was last drawn from, so a redraw that changes nothing writes nothing.
const DOC_DRAWN=/** @type {WeakMap<Element,string>} */(new WeakMap());
// Sets the inside of el to markup m, drawn from key - unless it was drawn from key already. el itself stays: one that has the
// focus keeps it, and no focusout or focusin is sent.
/**
 * @param {Element} el
 * @param {Html} m
 * @param {string} key
 */
function docInner(el,m,key){if(DOC_DRAWN.get(el)===key)return; setHtml(el,m); DOC_DRAWN.set(el,key);}
// Sets attribute a of el to v when it is not v already (an unchanged write still reaches the MutationObservers).
/**
 * @param {Element} el
 * @param {string} a
 * @param {string} v
 */
function setAttr(el,a,v){if(el.getAttribute(a)!==v)el.setAttribute(a,v);}
// Draws the document choosers: the select, the nav bar's links, the phone's position button (drawPos), an open navigation
// sheet's rows and an open documents popover's. A document's name is user text (translate="no"); the UI words beside it (build
// state, page count, the description) are translated here. With the same documents in the same order (a redraw by polling)
// each link is updated in place - only what changed - so a link or [+N] (#doc-more, after the links) that has the focus keeps
// the same node; otherwise the links are made again in front of [+N] and a link that had the focus gives it to its document's
// new link. Then the row is fitted (docFit).
function drawDocTabs(){
  const box=$('#doc-select');
  setHtml(box,html`${DOCS.map(d=>html`<option translate="no" value="${d.key}">${d.name}${d.building?tr(' · 빌드 중'):d.stale_build?tr(' · 원고 수정됨'):''}</option>`)}`);
  if(DOC)box.value=DOC;
  const row=$('#doc-links'),more=$('#doc-more'),had=/** @type {HTMLElement|null} */(document.activeElement),
    old=/** @type {HTMLElement[]} */([...row.querySelectorAll(':scope>[data-doc]')]);
  const same=old.length===DOCS.length&&old.every((a,i)=>a.dataset.doc===DOCS[i].key);
  let was=/** @type {string|null|undefined} */(null);
  if(!same){was=had&&had!==more&&row.contains(had)?had.dataset.doc:null; old.forEach(a=>a.remove());
    const links=document.createElement('div');
    setHtml(links,html`${DOCS.map(d=>html`<button translate="no" data-act="doc" data-doc="${d.key}"></button>`)}`);
    more.before(...links.children);}
  /** @type {HTMLElement[]} */([...row.querySelectorAll(':scope>[data-doc]')]).forEach((a,i)=>{const d=DOCS[i];
    setAttr(a,'aria-current',d.key===DOC?'page':'false'); setAttr(a,'title',docTip(d)); docInner(a,docLinkInner(d),d.name+'\u0001'+(d.n_pages||''));});
  drawPos(); docFit();
  const back=was?/** @type {HTMLElement[]} */([...row.querySelectorAll(':scope>[data-doc]')]).find(a=>a.dataset.doc===was&&!a.hidden):null;
  if(back)back.focus({preventScroll:true});
  if($('#nav-sheet').open)drawDocsMenu();
  if(!$('#doc-pop').hidden)drawDocMenu();}

// ---- The document row's fit (docs/handbook/viewer.md §문서 링크가 넘칠 때)
// Which links the row shows, as indices into w: every one when they all fit room - w are the links' widths, gap the row's gap -
// else the first k in order with [+N] after them (moreW(N): its width saying N), k as large as fits, and the current
// document's link (index cur, -1 for none) always among them: when it would be hidden it takes the k-th place. None ([]) when
// not even one link and [+N] fit: the row is then a single chooser (docFit). Pure.
function docTabsShown(w,gap,cur,room,moreW){
  const n=w.length,all=w.map((_,i)=>i),width=a=>a.reduce((s,i)=>s+w[i],0)+gap*Math.max(0,a.length-1),fits=x=>x<=room+0.01;
  if(fits(width(all)))return all;
  for(let k=n-1;k>=1;k--){const a=all.slice(0,k); if(cur>=k)a[k-1]=cur; if(fits(width(a)+gap+moreW(n-k)))return a;}
  return [];}
// How the chooser stands when no link and [+N] fit together: 'name' - the current document's name, shortened to an ellipsis
// as room needs - when room holds the whole name or at least the chooser's own width (chrome: padding, gap, chevron) and three
// em of name; else 'icon'. Pure.
function docChooser(room,full,chrome,em){return room+0.01>=Math.min(full,chrome+3*em)?'name':'icon';}
let DOC_FIT='';   // the row's last fit: a measure that changes nothing writes nothing and re-fits nothing
// Fits the nav bar's document row to the room the bar leaves it, down a ladder in which nothing is ever cut:
// (a) as many whole links as fit, in DOCS order, the current one always among them, and [+N] for the N left out
//     (docTabsShown) - or every link and no button;
// (b) when not even the current link and [+N] fit: one chooser, [+N]'s button (#doc-more, data-fit="name"), saying the
//     current document's name - ellipsis as needed - and opening the same popover;
// (c) when (b) could not show three em of the name: the same chooser as an icon (data-fit="icon").
// The room is the bar's content width less every other control at its own width and the gaps between them, three of them
// counted as they would stand: the search at its folded magnifier (the field gives way before the links, as it gives way
// before every neighbour - searchFit takes what the row leaves), and at their whole widths the paper's name (up to its
// max-width: the links give way before it is shortened) and the short band's status line (it gives way last). The row's
// least width is its content's (frame.css), so below (c) the bar's neighbours give way instead, each only after the row is
// down to its icon: the paper's name shortens (it may shrink), and the short band's status line - which never shrinks, as
// the search measures it whole - drops its words, whole or not at all: a stub of one or two letters said less than nothing
// (its icon and action stay, and its spoken label is its own node).
// Measured with every link shown, then each hidden or shown whole. Nothing that has the focus is hidden to be measured (a
// hidden control loses it): the links are measured all shown, the button where it stands; a link or the button that has the
// focus and is left out gives it to the button or the current link. When the fit changes the search is fitted again; an
// open popover is placed again under its button (which may have moved), or shuts when the button has gone. Where the row is
// not drawn (the phone, one document) nothing is.
function docFit(){const row=$('#doc-links'),more=$('#doc-more'),nav=$('#doc-nav'),lbl=/** @type {HTMLElement} */(more.querySelector('.lbl')),
    tabs=/** @type {HTMLElement[]} */([...row.querySelectorAll(':scope>[data-doc]')]),px=v=>parseFloat(v)||0,had=document.activeElement;
  let fit='',drop=false;
  const st=$('#status'); st.classList.remove('st-words-off');   // measured with its words; dropped again below when they do not fit
  if(row.getClientRects().length&&tabs.length>1){
    const cs=getComputedStyle(nav),rs=getComputedStyle(row);
    // its whole width: laid out for the moment as it would stand unshrunk (up to its max-width), to the fraction of a pixel
    const whole=(/** @type {HTMLElement} */k)=>{k.style.flex='none'; const x=k.getBoundingClientRect().width; k.style.flex=''; return x;};
    let used=0,n=0;
    for(const k of /** @type {HTMLElement[]} */([...nav.children])){if(k===row||!k.getClientRects().length)continue; const m=getComputedStyle(k); n++;
      if(k.id==='doc-search'){used+=px(getComputedStyle($('#search-open')).width); continue;}   // its margin is the bar's one flexible gap
      if(k.id==='paper-identity'||k.id==='status')used+=whole(k);
      else used+=k.getBoundingClientRect().width;
      if(!k.matches('#nav-page,#nav-side'))used+=px(m.marginLeft)+px(m.marginRight);}   // those two stand after the flexible gap
    const room=nav.clientWidth-px(cs.paddingLeft)-px(cs.paddingRight)-px(cs.columnGap)*n-used-px(rs.marginLeft)-px(rs.marginRight);
    tabs.forEach(a=>{a.hidden=false;});
    const ms=getComputedStyle(more),mm=px(ms.marginLeft)+px(ms.marginRight);   // the button's width counts its margins (frame.css)
    const w=tabs.map(a=>a.getBoundingClientRect().width),gap=px(rs.columnGap),seen=new Map(),was=more.hidden;
    const as=(/** @type {string} */mode,/** @type {string} */text)=>{more.dataset.fit=mode; lbl.textContent=text; more.style.maxWidth='';};
    const width=(/** @type {string} */mode,/** @type {string} */text)=>{as(mode,text); more.hidden=false; const x=more.getBoundingClientRect().width+mm; more.hidden=was; return x;};
    const moreW=N=>{if(!seen.has(N))seen.set(N,width('more','+'+N)); return seen.get(N);};
    const cur=Math.max(0,tabs.findIndex(a=>a.dataset.doc===DOC)),d=docInfo(tabs[cur].dataset.doc||'')||DOCS[cur];
    const shown=docTabsShown(w,gap,cur,room,moreW),N=tabs.length-shown.length;
    let mode='more',cap='';
    if(!shown.length){const full=width('name',d.name),chrome=width('name','');
      mode=docChooser(room,full,chrome,px(getComputedStyle(lbl).fontSize)); if(mode==='name'&&full>room)cap=Math.floor(room-mm)+'px';
      drop=mode==='icon'&&nav.contains(st)&&width('icon','')>room+0.5;}   // the short band's status line gives way: all its words
    tabs.forEach((a,i)=>{a.hidden=!shown.includes(i);});
    as(mode,mode==='more'?'+'+N:mode==='name'?d.name:''); more.style.maxWidth=cap;
    if(mode==='more'){more.setAttribute('aria-label',tl('+{n} 문서 더 보기',{n:N})); more.removeAttribute('title');}
    else{more.setAttribute('aria-label',d.name+' — '+tl('문서 {n}개 중 고르기',{n:DOCS.length})); more.setAttribute('title',docTip(d));}
    more.hidden=mode==='more'&&!N; fit=[mode,shown.map(i=>tabs[i].dataset.doc).join(),N,cap,d.name,drop].join('|');}
  else{tabs.forEach(a=>{a.hidden=false;}); more.hidden=true;}
  st.classList.toggle('st-words-off',drop);
  const lost=had instanceof HTMLElement&&(row.contains(had)?had.hidden:!more.hidden?false:$('#doc-pop').contains(had));
  if(more.hidden)closeDocMenu(false);
  if(lost){const to=more.hidden?tabs.find(a=>a.getAttribute('aria-current')==='page'):more; if(to)to.focus({preventScroll:true});}
  if(fit!==DOC_FIT){DOC_FIT=fit; searchFit();}
  placeDocMenu();}
// Re-fits once a frame when the bar or a control beside the row changes size (the window, the pin panel, the page count, the
// status line in the short band, the search) - never on the row's own size, which the fit sets - and when a font arrives.
let DOC_FIT_FRAME=0;
function docFitSoon(){if(!DOC_FIT_FRAME)DOC_FIT_FRAME=requestAnimationFrame(()=>{DOC_FIT_FRAME=0; docFit();});}
if(window.ResizeObserver){const o=new ResizeObserver(docFitSoon); o.observe($('#doc-nav')); o.observe($('#status'));
  for(const k of $$('#doc-nav>*'))if(k.id!=='doc-links')o.observe(k);}
document.fonts.addEventListener('loadingdone',docFit);
// The row is a scroll box only for how it is painted (frame.css): it never scrolls. The current link's bar reaches 1px under
// it, which a browser lets keys scroll after a press in the row (the links moved up 1px) - undone at once - and which made
// Firefox give the row a Tab stop of its own, a ring round all the links (index.html takes it out of the Tab order).
$('#doc-links').addEventListener('scroll',e=>{const r=/** @type {HTMLElement} */(e.currentTarget); if(r.scrollTop||r.scrollLeft){r.scrollTop=0; r.scrollLeft=0;}},{passive:true});

// ---- The documents popover ([+N] or the chooser, docs/handbook/viewer.md §문서 링크가 넘칠 때)
// Every document in DOCS order, one row each: the current one's check, the name (user text) with its build state (docState),
// the page count and, for the first nine, the Alt+number that picks it. Choosing a row is a document link's click (data-act
// "doc": switchDoc). With nine documents or more a field on top filters the rows by name or path.
// Draws the popover's rows. A redraw with the same documents in the same order (polling) updates each row in place - only
// what changed - so a focused row keeps its node and the focus, and the filter and the list's scroll stay.
function drawDocMenu(){const list=$('#doc-pop-list'),old=/** @type {HTMLElement[]} */([...list.children]);
  if(!(old.length===DOCS.length&&old.every((r,i)=>r.dataset.doc===DOCS[i].key)))
    setHtml(list,html`${DOCS.map(d=>html`<button class="dp-row" role="option" data-act="doc" data-doc="${d.key}"></button>`)}`);
  /** @type {HTMLElement[]} */([...list.children]).forEach((r,i)=>{const d=DOCS[i],on=d.key===DOC,st=d.building?'spin':d.stale_build?'dot':'';
    r.classList.toggle('on',on); setAttr(r,'aria-selected',String(on)); setAttr(r,'tabindex',on?'0':'-1');
    docInner(r,html`<span class="dp-c">${on?ic('check'):''}</span><span class="dp-n"><span class="dp-t" translate="no">${d.name}</span>${docState(d)}</span><span class="dp-p">${d.n_pages?tl('{n}쪽',{n:d.n_pages}):''}</span><span class="dp-k">${i<9?'Alt+'+(i+1):''}</span>`,
      [d.name,d.n_pages||'',on,st,LANG].join('\u0001'));});
  docMenuFilter();}
// Shows the rows whose document's name or path holds the field's text (case folded, as the outline's search), and says so
// when none does.
function docMenuFilter(){const q=/** @type {HTMLInputElement} */($('#doc-pop-in')).value.trim().toLowerCase(); let n=0;
  for(const r of /** @type {HTMLElement[]} */([...$('#doc-pop-list').children])){const d=docInfo(r.dataset.doc||'');
    r.hidden=!!q&&!(d&&(d.name+' '+d.path).toLowerCase().includes(q)); if(!r.hidden)n++;}
  $('#doc-pop-none').hidden=n>0;}
// Opens the popover under its button. A mouse or a keyboard gets the focus in the filter when there is one; touch - no
// keyboard comes up - and a list without it get the current document's row, scrolled into view.
function openDocMenu(){const pop=$('#doc-pop'),f=/** @type {HTMLInputElement} */($('#doc-pop-in'));
  hideTip(); closePageList(false); f.hidden=DOCS.length<9; f.value=''; $('#doc-more').setAttribute('aria-expanded','true');
  pop.hidden=false; drawDocMenu(); placeDocMenu();
  const row=/** @type {HTMLElement|null} */($('#doc-pop-list [aria-selected=true]')); if(row)row.scrollIntoView({block:'nearest'});
  const to=!f.hidden&&!MQ_COARSE.matches?f:row||pop; to.focus({preventScroll:true});}
// Puts the open popover under its button, its left edge on the button's and inside the window by 8px, and lets it grow down to
// 8px above the window's bottom (--dp-room); its list scrolls inside that. docFit calls it after every fit, so the popover
// follows its button when the bar changes (the window, the pin panel, the outline).
function placeDocMenu(){const pop=$('#doc-pop'),more=$('#doc-more'); if(pop.hidden)return;
  if(!more.getClientRects().length){closeDocMenu(false); return;}
  const r=more.getBoundingClientRect(),top=Math.round(r.bottom)+4,w=pop.offsetWidth;
  pop.style.left=Math.max(8,Math.min(Math.round(r.left),innerWidth-8-w))+'px'; pop.style.top=top+'px';
  pop.style.setProperty('--dp-room',Math.max(0,innerHeight-8-top)+'px');}
// Shuts the popover; back gives the focus back to its button (Esc, a choice, Shift+Tab out of it).
function closeDocMenu(back){const pop=$('#doc-pop'),more=$('#doc-more'); if(pop.hidden)return; pop.hidden=true;
  more.setAttribute('aria-expanded','false'); if(back&&more.getClientRects().length)more.focus({preventScroll:true});}
// The button's click: opens the popover, or shuts it when it is open.
function toggleDocMenu(){if($('#doc-pop').hidden)openDocMenu(); else closeDocMenu(false);}
// The nav bar's next stop after the popover's button, in its order (DOM order, as Tab goes): what Tab out of the popover
// lands on. Null when the button is the bar's last.
function docMenuNext(){const more=$('#doc-more'),stops=/** @type {HTMLElement[]} */([...$('#doc-nav').querySelectorAll('button,input,select,a[href],[tabindex]')])
    .filter(e=>e===more||(e.tabIndex>=0&&!/** @type {HTMLButtonElement} */(e).disabled&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'));
  return stops[stops.indexOf(more)+1]||null;}
// Keys: ↓ on the button opens the popover (Enter and Space are its click). In the filter ↓ goes to the current row (the first
// shown when it is filtered out) and Enter chooses the first row shown; on a row ↓/↑ move one row, Home/End to the ends, ↑ on
// the first goes back to the filter. Alt+1…9 picks that document from anywhere in the popover, the filter too (the shortcut
// is otherwise not taken inside a text field). Tab leaves the popover forward: from the filter to the list's row, from a row
// out - the popover shuts and the focus goes to the bar's next stop after the button; Shift+Tab goes back: from a row to the
// filter, from the filter (or a row with no filter) out to the button, the popover shut. Esc is the viewer's (events.js): it
// shuts the popover with the focus on the button.
$('#doc-more').addEventListener('keydown',e=>{if(e.key==='ArrowDown'&&!e.altKey){e.preventDefault(); if($('#doc-pop').hidden)openDocMenu();}});
$('#doc-pop').addEventListener('keydown',e=>{const t=/** @type {HTMLElement} */(e.target),f=$('#doc-pop-in');
  if(e.isComposing)return;
  const rows=/** @type {HTMLElement[]} */([...$('#doc-pop-list').children]).filter(r=>!r.hidden),field=!f.hidden;
  if(e.altKey&&!e.ctrlKey&&!e.metaKey&&/^Digit[1-9]$/.test(e.code||'')){const d=DOCS[+e.code.slice(5)-1]; e.preventDefault(); e.stopPropagation();
    if(d){closeDocMenu(true); switchDoc(d.key);} return;}
  if(e.key==='Tab'&&!e.ctrlKey&&!e.altKey&&!e.metaKey){e.preventDefault();
    if(e.shiftKey){if(t!==f&&field)f.focus(); else closeDocMenu(true); return;}
    if(t===f&&rows.length){(rows.find(r=>r.classList.contains('on'))||rows[0]).focus(); return;}
    const next=docMenuNext(); closeDocMenu(!next); if(next)next.focus(); return;}
  if(t===f){if(e.key==='ArrowDown'&&rows.length){e.preventDefault(); (rows.find(r=>r.classList.contains('on'))||rows[0]).focus();}
    else if(e.key==='Enter'&&rows.length){e.preventDefault(); rows[0].click();}
    return;}
  const i=rows.indexOf(t); if(i<0)return;
  if(e.key==='ArrowUp'&&i===0&&field){e.preventDefault(); f.focus(); return;}
  const to={ArrowDown:i+1,ArrowUp:i-1,Home:0,End:rows.length-1}[e.key]; if(to===undefined)return;
  e.preventDefault(); const r=rows[Math.max(0,Math.min(rows.length-1,to))]; r.focus(); r.scrollIntoView({block:'nearest'});});
$('#doc-pop-in').addEventListener('input',docMenuFilter);
// The focus moving to a control outside the popover and its button (a click on another control, a shortcut that moves it)
// shuts it; a press anywhere outside them shuts it too (the press still does what it does). Focus that goes nowhere (the
// window losing it) leaves it open.
$('#doc-pop').addEventListener('focusout',e=>{const to=/** @type {Node|null} */(e.relatedTarget);
  if(to&&!$('#doc-pop').contains(to)&&!$('#doc-more').contains(to))closeDocMenu(false);});
document.addEventListener('pointerdown',e=>{const t=/** @type {Node} */(e.target);
  if(!$('#doc-pop').hidden&&!$('#doc-pop').contains(t)&&!$('#doc-more').contains(t))closeDocMenu(false);},true);
addEventListener('resize',placeDocMenu);
