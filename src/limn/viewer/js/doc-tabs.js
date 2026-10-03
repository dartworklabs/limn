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
// A document's marks in the documents list: building (spinner) or manuscript newer (dot), view-only 'PDF', figure '그림',
// and its open-pin count.
function docBadge(d){const n=docCount(d.key);
  const state=d.building?html`<span class="spin" aria-label="빌드 중"></span>`:d.stale_build?html`<span class="ddot" aria-label="원고 수정됨"></span>`:'';
  const pdf=d.view_only?html`<span class="badge dvo" aria-label="보기 전용">PDF</span>`:'';
  const fig=isFigureKind(d.kind)?html`<span class="badge dfig" aria-label="${tr('그림 문서')}">${tr('그림')}</span>`:'';
  return html`${state}${pdf}${fig}<span class="badge badge-secondary dcnt${n?'':' z'}" aria-label="${tl('열린 핀 {n}',{n})}">${n}</span>`;}
// A document link's description: name, path, what kind of document it is, and its build state. The link is user text
// (translate="no", the name), so the UI words are translated here.
function docTip(d){return d.name+' · '+d.path+(d.view_only?tr(' · 보기 전용 PDF(줄 번호 없이 쪽·영역으로 핀을 남깁니다)'):'')+
  (isFigureKind(d.kind)?' · '+tr('그림 문서(드래그하면 요소와 그 요소를 그린 코드 줄을 찾습니다)'):'')+
  (d.building?tr(' · 빌드 중'):(d.stale_build?tr(' · 원고가 이 PDF보다 새롭습니다(그 탭에서 [PDF 재빌드])'):''));}
// Draws the document choosers: the select, the nav bar's links, the phone's position button (drawPos) and an open navigation
// sheet's rows. A document's name is user text (translate="no"); the UI words beside it (build state, page count, the
// description) are translated here. A link's name is a span (.lbl) so CSS can trim it to its cap height, as the view tabs'.
function drawDocTabs(){
  const box=$('#doc-select');
  setHtml(box,html`${DOCS.map(d=>html`<option translate="no" value="${d.key}">${d.name}${d.building?tr(' · 빌드 중'):d.stale_build?tr(' · 원고 수정됨'):''}</option>`)}`);
  if(DOC)box.value=DOC;
  setHtml($('#doc-links'),html`${DOCS.map(d=>{const count=d.n_pages?html`<span class="doc-link-count">${tl('{n}쪽',{n:d.n_pages})}</span>`:'';
    return html`<button translate="no" data-act="doc" data-doc="${d.key}" aria-current="${d.key===DOC?'page':'false'}" title="${docTip(d)}"><span class="lbl">${d.name}</span>${count}</button>`;})}`);
  drawPos();
  if(DOC!==DOC_LINK_SHOWN){DOC_LINK_SHOWN=DOC; docLinksReveal();} else docLinksFade();
  if($('#nav-sheet').open)drawDocsMenu();}
// When the document-links row overflows (e.g. 5 documents in mid): the overflowing edge is faded (fade-l/fade-r) to show there's more,
// and when the document changes, the current document's link is scrolled into view. A polling redraw never touches wherever the user has scrolled to (only a document change does).
let DOC_LINK_SHOWN=/** @type {string|null} */(null);
function docLinksFade(){const d=$('#doc-links'); if(!d)return; const over=d.scrollWidth-d.clientWidth;
  d.classList.toggle('fade-l',over>1&&d.scrollLeft>1); d.classList.toggle('fade-r',over>1&&over-d.scrollLeft>1);}
function docLinksReveal(){const d=$('#doc-links'),a=d&&d.querySelector('[aria-current=page]');
  if(a&&d.scrollWidth>d.clientWidth){const dr=d.getBoundingClientRect(),ar=a.getBoundingClientRect(),pad=40;
    if(ar.left<dr.left+pad)d.scrollLeft-=dr.left+pad-ar.left; else if(ar.right>dr.right-pad)d.scrollLeft+=ar.right-(dr.right-pad);}
  docLinksFade();}
$('#doc-links').addEventListener('scroll',docLinksFade,{passive:true});
if(window.ResizeObserver)new ResizeObserver(()=>docLinksReveal()).observe($('#doc-links'));
