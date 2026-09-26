// ------------------------------------------------ Multiple documents - list/tabs/switching (docs/handbook/domain.md §여러 문서)
function multiDoc(){return DOCS.length>1;}
function docInfo(k){return DOCS.find(d=>d.key===k)||null;}
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
