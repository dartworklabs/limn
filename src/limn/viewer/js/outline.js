async function loadOutline(doc,gen){
  let entries=[];
  try{const items=await doc.getOutline();
    async function walk(rows,depth){for(const item of rows||[]){if(entries.length>=180)return;
      let dest=item.dest;
      if(typeof dest==='string')dest=await doc.getDestination(dest);
      if(Array.isArray(dest)&&dest[0]!=null){
        const page=typeof dest[0]==='number'?dest[0]+1:(await doc.getPageIndex(dest[0]))+1;
        const ptH=META&&META.pages&&META.pages[page-1]?+META.pages[page-1].pt_h:0;
        if(Number.isInteger(page)&&page>=1&&page<=doc.numPages)entries.push({title:item.title||tr('제목 없음'),page,depth,frac:destFrac(dest,ptH)});
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
// The outline entry the reader is in at (page, frac), from the entries that start at or above that point. The outline's
// order need not be the pages' order - a figure set's outline grouped by status lists page 3 before page 1 (issue #279) -
// so the page decides first: the latest page any of them starts on, which is this page when a heading on it starts above
// the reading line, else the nearest earlier page with an entry. On that page the outline's order is the reading order
// (a two-column page lists its left column's headings first), so the last of them wins; entries that start at the same
// spot have no reading order between them, so of those only the deepest counts, and of equally deep ones the first the
// outline lists. An outline in page order thus gets what it always got: the last heading that starts at or above the
// point. Before the first heading (a title page, the top of page 1) it is the first entry on the earliest page - never a
// later heading on the same page (v0.2.0 showed "1.2" at the very top of page 1, because 1, 1.1 and 1.2 all start on
// page 1). -1 without entries. Pure.
function outlineIndexAt(entries,page,frac){
  const at=e=>e.frac||0,deep=e=>e.depth||0,above=e=>e.page<page||(e.page===page&&at(e)<=frac+1e-6);
  let top=0; for(const e of entries)if(above(e)&&e.page>top)top=e.page;
  if(!top){let first=-1; entries.forEach((e,i)=>{if(first<0||e.page<entries[first].page)first=i;}); return first;}
  const on=[]; entries.forEach((e,i)=>{if(e.page===top&&above(e))on.push(i);});
  const outranked=i=>on.some(j=>{const a=entries[i],b=entries[j];
    return j!==i&&Math.abs(at(a)-at(b))<=1e-6&&(deep(b)>deep(a)||(deep(b)===deep(a)&&j<i));});
  let sel=-1; for(const i of on)if(!outranked(i))sel=i;
  return sel;}
let OUTLINE_PINNED=/** @type {{page:number,index:number}|null} */(null);   // an entry picked in the outline wins until the reader leaves its page
// The section strip under the nav bar (the section at the reading line and 'page / pages') and the outline's highlight; mid has no
// strip, so the same page count also goes to the nav bar's right end (#nav-page) and the phone's position button (drawPos). Both
// page counts open the page list (openPageList).
function updateSectionStrip(){
  const L=$('#left'),probe=L?Math.min(160,L.clientHeight/4):0,anchor=topAnchor(probe),page=anchor?anchor.page:1,frac=anchor?anchor.frac:0;
  let sel;
  if(OUTLINE_PINNED&&OUTLINE_PINNED.page===page)sel=OUTLINE_PINNED.index;
  else{OUTLINE_PINNED=null; sel=outlineIndexAt(OUTLINE_ENTRIES,page,frac);}
  if(sel!==OUTLINE_SELECTED||page!==OUTLINE_ACTIVE_PAGE){OUTLINE_ACTIVE_PAGE=page;OUTLINE_SELECTED=sel;renderOutline();}
  const x=OUTLINE_ENTRIES[OUTLINE_SELECTED];$('#section-current').textContent=x?(x.number?x.number+'  ':'')+x.title:tr('원고');
  const n=META&&META.pages?META.pages.length:0,pg=tl('{page} / {n}쪽',{page,n}); $('#section-page-t').textContent=pg; $('#nav-page').textContent=pg;
  const name=tl('쪽 번호로 이동 · {page} / {n}쪽',{page,n}); $('#section-page').setAttribute('aria-label',name); $('#nav-page').setAttribute('aria-label',name); drawPos();
}
$('#outline-search').addEventListener('input',renderOutline);
$('#ns-outline-search').addEventListener('input',renderOutline);   // the navigation sheet's search filters its list only
$('#left').addEventListener('scroll',()=>{if(!document.body.classList.contains('revision-open'))requestAnimationFrame(updateSectionStrip);},{passive:true});
