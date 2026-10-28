async function loadOutline(doc,gen){
  let entries=[];
  try{const items=await doc.getOutline();
    async function walk(rows,depth){for(const item of rows||[]){if(entries.length>=180)return;
      let dest=item.dest;
      if(typeof dest==='string')dest=await doc.getDestination(dest);
      if(Array.isArray(dest)&&dest[0]!=null){
        const page=typeof dest[0]==='number'?dest[0]+1:(await doc.getPageIndex(dest[0]))+1;
        const ptH=META&&META.pages&&META.pages[page-1]?+META.pages[page-1].pt_h:0;
        if(Number.isInteger(page)&&page>=1&&page<=doc.numPages)entries.push({title:item.title||tr('제목 없음'),page,depth,frac:destFrac(dest,ptH),x:destLeft(dest)});
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
    const title=norm(entry.title);let matched=/** @type {any} */(null);
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
// Draws the outline into both of its lists - the outline panel and the phone's navigation sheet - each filtered by its own
// search field; the sheet leaves its outline section out when the PDF has no outline.
function renderOutline(){outlineList($('#outline-items'),$('#outline-search').value);
  outlineList($('#ns-outline-items'),$('#ns-outline-search').value); $('#ns-outline').hidden=!OUTLINE_ENTRIES.length;}
/** Draw one filtered outline with bare printed-page labels and the current section marked.
 * Entries keep manuscript wording unchanged; empty-state sentences remain translatable UI text.
 */
function outlineList(box,q){const query=String(q||'').trim().toLowerCase();
  if(!OUTLINE_ENTRIES.length){box.className='outline-empty';box.textContent='이 PDF에는 이동할 수 있는 목차가 없습니다.';return;}
  const rows=OUTLINE_ENTRIES.map((x,i)=>Object.assign({index:i},x)).filter(x=>!query||(x.number+' '+x.title).toLowerCase().includes(query));
  if(!rows.length){box.className='outline-empty';box.textContent='찾은 장·절이 없습니다.';return;}
  box.className='';
  setHtml(box,html`${rows.map(x=>{const on=x.index===OUTLINE_SELECTED;
    const page=x.pageLabel||String(x.page);
    return html`<button translate="no" class="ol-depth-${Math.min(x.depth,4)}${on?' ol-active':''}" data-act="outline-page" data-index="${x.index}" data-page="${x.page}" data-close="1" aria-current="${on?'location':'false'}" title="${x.title}"><span class="ol-no">${x.number||'·'}</span><span class="ol-name">${x.title}</span><span class="ol-page">${page}</span></button>`;})}`);
}
// Where a PDF outline destination sits on its page, as a fraction from the top (0 = top). An XYZ destination carries
// the top edge in PDF points from the bottom; anything else (Fit, no top) counts as the top of the page.
function destFrac(dest,ptH){const top=Array.isArray(dest)&&dest[1]&&dest[1].name==='XYZ'?dest[3]:null;
  if(typeof top!=='number'||!(ptH>0))return 0; return Math.min(1,Math.max(0,1-top/ptH));}
// The left edge of an XYZ destination in PDF points, or null (Fit, no left): two headings at the same height in a page's two
// columns are two spots, not one.
function destLeft(dest){const left=Array.isArray(dest)&&dest[1]&&dest[1].name==='XYZ'?dest[2]:null; return typeof left==='number'?left:null;}
// The outline entry the reader is in at (page, frac), from the entries that start at or above that point. The outline's
// order need not be the pages' order - a figure set's outline grouped by status lists page 3 before page 1 (issue #279) -
// so the page decides first: the latest page any of them starts on, which is this page when a heading on it starts above
// the reading line, else the nearest earlier page with an entry. On that page the outline's order is the reading order
// (a two-column page lists its left column's headings first), so the last of them wins; entries that start at the same
// spot - the same height and the same left edge (destLeft), as a group heading and its first figure at a page's top - have
// no reading order between them, so of those only the deepest counts, and of equally deep ones the first the outline
// lists. An outline in page order thus gets what it always got: the last heading that starts at or above the point.
// Before the first heading (a title page, the top of page 1) it is the first entry on the earliest page - never a later
// heading on the same page (v0.2.0 showed "1.2" at the very top of page 1, because 1, 1.1 and 1.2 all start on page 1).
// -1 without entries. Pure.
function outlineIndexAt(entries,page,frac){
  const at=e=>e.frac||0,deep=e=>e.depth||0,above=e=>e.page<page||(e.page===page&&at(e)<=frac+1e-6);
  const x=e=>typeof e.x==='number'?e.x:null,sameX=(a,b)=>x(a)===null||x(b)===null?x(a)===x(b):Math.abs(x(a)-x(b))<=1e-3;
  const same=(a,b)=>Math.abs(at(a)-at(b))<=1e-6&&sameX(a,b);
  let top=0; for(const e of entries)if(above(e)&&e.page>top)top=e.page;
  if(!top){let first=-1; entries.forEach((e,i)=>{if(first<0||e.page<entries[first].page)first=i;}); return first;}
  const on=[]; entries.forEach((e,i)=>{if(e.page===top&&above(e))on.push(i);});
  const outranked=i=>on.some(j=>{const a=entries[i],b=entries[j];
    return j!==i&&same(a,b)&&(deep(b)>deep(a)||(deep(b)===deep(a)&&j<i));});
  let sel=-1; for(const i of on)if(!outranked(i))sel=i;
  return sel;}
// An entry picked in the outline: it wins on its page from when the scroll it starts gets there until the reader leaves
// that page (`reached`); on the way there the strip follows the reading line. A pick whose scroll ends anywhere else is let
// go before it is reached, so that a later visit to its page by hand shows that page's own entry: when the reader takes
// over (a wheel, a touch, a press on the pages or the scroll bar, a scrolling key), when the window changes size, when
// another pick replaces it, and when the pages have stood still for OUTLINE_PICK_SETTLE_MS short of its page.
let OUTLINE_PINNED=/** @type {{page:number,index:number,reached:boolean}|null} */(null),OUTLINE_PICK_WAIT=0;
const OUTLINE_PICK_SETTLE_MS=250;   // a smooth scroll moves the pages every frame; this long without a scroll, it is over
const OUTLINE_PICK_GAP=8;   // px between the top of the free PDF area and a picked heading
// Pick entry i of the outline: the strip and the highlight name it, and the pages scroll to it (outlinePickTop).
function pickOutline(i){const e=OUTLINE_ENTRIES[i]; if(!e)return;
  OUTLINE_SELECTED=i; OUTLINE_ACTIVE_PAGE=e.page; OUTLINE_PINNED={index:i,page:e.page,reached:false}; outlinePickWait();
  renderOutline(); updateSectionStrip(); setViewMode('manuscript');
  const top=outlinePickTop(e); if(top===null)goPage(e.page); else $('#left').scrollTo({top,behavior:SMOOTH});}
// Where a pick scrolls the pages to, as #left's scrollTop: a heading with a place on its page (an XYZ destination below the
// page's top) OUTLINE_PICK_GAP under the top of the free PDF area (selPopArea: under the section strip, the instance band
// or the select mode's bar) - lower when it stands near its page's bottom, so that the reading line (readingDepth) still
// falls on its page and the strip names it - as far as the pages scroll; null - the page's top, as goPage - for an entry
// that names a whole page (frac 0) and for every entry of a figure document, whose pages are its figures.
function outlinePickTop(e){const pg=document.getElementById('p'+e.page),d=docInfo(DOC);
  if(!pg||!(e.frac>0)||(d&&isFigureKind(d.kind)))return null;
  const L=$('#left'),r=pg.getBoundingClientRect(),y=r.top+e.frac*r.height,read=L.getBoundingClientRect().top+readingDepth(L);
  const want=Math.max(selPopArea().top+OUTLINE_PICK_GAP,read+2-(r.bottom-y));
  return Math.max(0,Math.min(L.scrollHeight-L.clientHeight,Math.round(L.scrollTop+y-want)));}
// (Re)starts the wait after which a pick still on its way is over (any scroll of the pages restarts it).
function outlinePickWait(){clearTimeout(OUTLINE_PICK_WAIT); if(OUTLINE_PINNED&&!OUTLINE_PINNED.reached)OUTLINE_PICK_WAIT=setTimeout(dropOutlinePick,OUTLINE_PICK_SETTLE_MS);}
// Lets go of a pick that has not reached its page; one that has keeps to the end of its page.
function dropOutlinePick(){clearTimeout(OUTLINE_PICK_WAIT); if(!OUTLINE_PINNED||OUTLINE_PINNED.reached)return; OUTLINE_PINNED=null; updateSectionStrip();}
// The section strip under the nav bar (the section at the reading line and 'page / pages') and the outline's highlight; mid has no
// strip, so the same page count also goes to the nav bar's right end (#nav-page) and the phone's position button (drawPos). Both
// page counts open the page list (openPageList).
// How far under the top of the PDF pane the reading line is: a quarter of the pane's height, at most 160px.
function readingDepth(L){return L?Math.min(160,L.clientHeight/4):0;}
function updateSectionStrip(){
  const L=$('#left'),anchor=topAnchor(readingDepth(L)),page=anchor?anchor.page:1,frac=anchor?anchor.frac:0;
  const pin=OUTLINE_PINNED;
  if(pin&&pin.page===page){pin.reached=true; clearTimeout(OUTLINE_PICK_WAIT);} else if(pin&&pin.reached)OUTLINE_PINNED=null;
  const sel=OUTLINE_PINNED&&OUTLINE_PINNED.page===page?OUTLINE_PINNED.index:outlineIndexAt(OUTLINE_ENTRIES,page,frac);
  if(sel!==OUTLINE_SELECTED||page!==OUTLINE_ACTIVE_PAGE){OUTLINE_ACTIVE_PAGE=page;OUTLINE_SELECTED=sel;renderOutline();}
  const x=OUTLINE_ENTRIES[OUTLINE_SELECTED];$('#section-current').textContent=x?(x.number?x.number+'  ':'')+x.title:tr('원고');
  const n=META&&META.pages?META.pages.length:0,pg=tl('{page} / {n}쪽',{page,n}); $('#section-page-t').textContent=pg; $('#nav-page').textContent=pg;
  const name=tl('쪽 번호로 이동 · {page} / {n}쪽',{page,n}); $('#section-page').setAttribute('aria-label',name); $('#nav-page').setAttribute('aria-label',name); drawPos();
}
$('#outline-search').addEventListener('input',renderOutline);
$('#ns-outline-search').addEventListener('input',renderOutline);   // the navigation sheet's search filters its list only
$('#left').addEventListener('scroll',()=>{if(OUTLINE_PINNED&&!OUTLINE_PINNED.reached)outlinePickWait();
  if(!document.body.classList.contains('revision-open'))requestAnimationFrame(updateSectionStrip);},{passive:true});
// The reader taking over the pages lets go of a pick still on its way (dropOutlinePick); so does a new size of the window.
for(const t of ['wheel','touchstart','pointerdown'])$('#left').addEventListener(t,dropOutlinePick,{passive:true});
// A key scrolls the pages when nothing else has the focus, or something on the pages has it.
const SCROLL_KEYS=new Set(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' ']);
addEventListener('keydown',e=>{const a=document.activeElement;
  if(SCROLL_KEYS.has(e.key)&&(!a||a===document.body||$('#left').contains(a)))dropOutlinePick();});
addEventListener('resize',dropOutlinePick);
