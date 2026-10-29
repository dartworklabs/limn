// How much of a PDF's outline the viewer reads (docs/handbook/viewer.md §모바일 레이아웃): the first OUTLINE_MAX_ENTRIES entries in outline
// order, down to level OUTLINE_MAX_DEPTH (0 is the top level, so five levels). What is left unread is counted (OUTLINE_CUT) and said at
// the end of the outline and of its filter's results (outlineCutNote) - never dropped without a word.
const OUTLINE_MAX_ENTRIES=2000, OUTLINE_MAX_DEPTH=4;
const OUTLINE_BATCH=100;   // sibling entries whose destinations are resolved at once (each is a round trip to the PDF.js worker)
// How many entries that name a place (a destination) lie in item and below it. Counts without resolving anything, and with a stack
// of its own: an outline can nest deeper than the call stack.
function outlineCount(item){let n=0; const todo=[item];
  while(todo.length){const x=todo.pop(); if(x.dest!=null)n++; for(const c of x.items||[])todo.push(c);} return n;}
// Which document and build the entries in OUTLINE_ENTRIES were read for (outlineForget drops them when another document comes on
// screen; the page list names a figure's pages by them only while they are those of the build on screen, outlineOnScreen).
let OUTLINE_DOC=/** @type {string|null} */(null),OUTLINE_BUILD='';
async function loadOutline(doc,gen){
  const k=DOC,build=(META&&META.pages_build)||'',stale=()=>gen!==VEC.gen||doc!==VEC.doc;   // a newer open (another document or build) took over
  let entries=[],cut=0;
  try{const items=await doc.getOutline();
    // One outline item as an entry (without its depth), or null when it names no page of this PDF - or when its destination cannot
    // be resolved: one broken link leaves out that entry only, not the outline.
    async function entryOf(item){
      try{let dest=item.dest;
        if(typeof dest==='string')dest=await doc.getDestination(dest);
        if(!Array.isArray(dest)||dest[0]==null)return null;
        const page=typeof dest[0]==='number'?dest[0]+1:(await doc.getPageIndex(dest[0]))+1;
        const ptH=META&&META.pages&&META.pages[page-1]?+META.pages[page-1].pt_h:0;
        if(!(Number.isInteger(page)&&page>=1&&page<=doc.numPages))return null;
        return {title:item.title||tr('제목 없음'),page,depth:0,frac:destFrac(dest,ptH),x:destLeft(dest)};
      }catch(e){return null;}}
    async function walk(rows,depth){
      for(let i=0;i<rows.length;i+=OUTLINE_BATCH){
        if(stale())return;   // between batches: a document left behind does not go on asking the worker
        if(entries.length>=OUTLINE_MAX_ENTRIES){for(let j=i;j<rows.length;j++)cut+=outlineCount(rows[j]); return;}
        const batch=rows.slice(i,i+OUTLINE_BATCH),got=await Promise.all(batch.map(entryOf));
        if(stale())return;
        for(let j=0;j<batch.length;j++){
          if(entries.length>=OUTLINE_MAX_ENTRIES){cut+=outlineCount(batch[j]); continue;}
          if(got[j])entries.push(Object.assign(got[j],{depth}));
          if(depth<OUTLINE_MAX_DEPTH){await walk(batch[j].items,depth+1); if(stale())return;}
          else for(const c of batch[j].items||[])cut+=outlineCount(c);
        }
      }
    }
    await walk(items||[],0);
  }catch(e){entries=[];cut=0;}
  if(stale())return;
  if(entries.length){
    try{const r=(await api(dq('/api/outline-labels',k),{what:'목차 번호 읽기',silent:true})).data;
      if(!stale()&&k===DOC&&build===META.pages_build&&r.build===build)
        entries=mergeOutlineLabels(entries,r.labels||[]);
    }catch(e){} // the PDF's own outline is still usable even if the numbering service can't be reached.
  }
  if(stale())return;
  OUTLINE_ENTRIES=entries;OUTLINE_CUT=cut;OUTLINE_DOC=k;OUTLINE_BUILD=build;OUTLINE_SELECTED=-1;OUTLINE_ACTIVE_PAGE=0;OUTLINE_PINNED=null;
  renderOutline();updateSectionStrip();refreshPageLists();   // a page list opened while this was read names its pages now
}
// Drops the outline of the document that was on screen before, when another one comes on screen (vecOpen): the page list and the
// section strip would otherwise name its pages by the old document's headings until the new outline is read. The same document's
// new build keeps the old build's entries until its own are read - a rebuilt manuscript's strip does not blank meanwhile.
function outlineForget(){if(OUTLINE_DOC===DOC)return;
  OUTLINE_ENTRIES=[];OUTLINE_CUT=0;OUTLINE_DOC=DOC;OUTLINE_BUILD='';OUTLINE_SELECTED=-1;OUTLINE_ACTIVE_PAGE=0;OUTLINE_PINNED=null;
  $('#ns-outline').hidden=true;}   // the sheet's outline rows are the old document's
// Whether OUTLINE_ENTRIES were read for the build on screen.
function outlineOnScreen(){return OUTLINE_DOC===DOC&&OUTLINE_BUILD===((META&&META.pages_build)||'');}
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
let OUTLINE_ENTRIES=[],OUTLINE_CUT=0,OUTLINE_SELECTED=-1,OUTLINE_ACTIVE_PAGE=0;   // OUTLINE_CUT: entries the PDF has that were not read
// Draws the outline into both of its lists - the outline panel and the phone's navigation sheet - each filtered by its own
// search field; the sheet leaves its outline section out when the PDF has no outline.
function renderOutline(){outlineList($('#outline-items'),$('#outline-search').value);
  outlineList($('#ns-outline-items'),$('#ns-outline-search').value); $('#ns-outline').hidden=!(OUTLINE_ENTRIES.length||OUTLINE_CUT);}
/** Draw one filtered outline with bare printed-page labels and the current section marked, and - when the PDF has more entries
 * than were read (OUTLINE_CUT) - the note on the unread ones as its last line, under a filter's results too (outlineCutNote).
 * Entries keep manuscript wording unchanged; empty-state sentences remain translatable UI text.
 */
function outlineList(box,q){const query=String(q||'').trim().toLowerCase();
  if(!OUTLINE_ENTRIES.length){box.className='outline-empty';   // all of what it has was left unread (destinationless ancestors, entries below the depth limit): say that
    const note=outlineCutNote(false); if(note)setHtml(box,note); else box.textContent='이 PDF에는 이동할 수 있는 목차가 없습니다.'; return;}
  const rows=[]; OUTLINE_ENTRIES.forEach((x,i)=>{if(!query||(x.number+' '+x.title).toLowerCase().includes(query))rows.push(i);});
  const note=outlineCutNote(!!query);
  if(!rows.length){box.className='outline-empty';
    if(note)setHtml(box,html`${tr('찾은 장·절이 없습니다.')}${note}`); else box.textContent='찾은 장·절이 없습니다.'; return;}
  box.className='';
  setHtml(box,html`${rows.map(i=>{const x=OUTLINE_ENTRIES[i],on=i===OUTLINE_SELECTED;
    const page=x.pageLabel||String(x.page);
    return html`<button translate="no" class="ol-depth-${Math.min(x.depth,4)}${on?' ol-active':''}" data-act="outline-page" data-index="${i}" data-page="${x.page}" data-close="1" aria-current="${on?'location':'false'}" title="${x.title}"><span class="ol-no">${x.number||'·'}</span><span class="ol-name">${x.title}</span><span class="ol-page">${page}</span></button>`;})}${note}`);
}
// The outline's last line when the PDF has entries that were not read (OUTLINE_CUT): how many, and what the viewer reads at most.
// Under a filter it says the unread entries were not searched (it does not say they are not there). Quiet text, not a row: it names no place. Html, or '' with no cut.
function outlineCutNote(filtered){if(!OUTLINE_CUT)return '';
  const p={n:OUTLINE_CUT.toLocaleString('en-US'),max:OUTLINE_MAX_ENTRIES.toLocaleString('en-US'),depth:OUTLINE_MAX_DEPTH+1};
  return html`<p class="ol-more" role="note">${filtered
    ?tl('생략한 목차 항목 {n}개는 검색하지 않았습니다 — 읽는 한도는 {max}개, {depth}단계입니다',p)
    :tl('목차 항목 {n}개를 생략했습니다 — 읽는 한도는 {max}개, {depth}단계입니다',p)}</p>`;}
// Moves the current-section mark to OUTLINE_SELECTED in both lists without drawing them again. The section strip follows the
// reading line, so scrolling through a long document changes the section at every page, and redrawing thousands of rows each
// time is what a long outline cannot afford. A row is found by its data-index; one the filter hides has no row to mark.
function markOutline(){for(const box of [$('#outline-items'),$('#ns-outline-items')]){
    for(const b of box.querySelectorAll('.ol-active')){b.classList.remove('ol-active'); b.setAttribute('aria-current','false');}
    const on=OUTLINE_SELECTED>=0?box.querySelector('[data-index="'+OUTLINE_SELECTED+'"]'):null;
    if(on){on.classList.add('ol-active'); on.setAttribute('aria-current','location');}}}
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
  let top=0; for(const e of entries)if(above(e)&&e.page>top)top=e.page;
  if(!top){let first=-1; entries.forEach((e,i)=>{if(first<0||e.page<entries[first].page)first=i;}); return first;}
  // Of the entries on that page above the point only the last that nothing at its spot outranks counts. An entry is outranked by one at
  // the same spot (the same height within 1e-6 and the same left edge) that is deeper, or as deep and listed earlier. Comparing every
  // pair cost a figure document's page with hundreds of distinct entries tens of ms a scroll frame, so: at an exactly equal spot the
  // winner (deepest, the first of them) outranks the rest, and only the winners - sorted by height, a spot's neighbours within 1e-6 side
  // by side - are compared with one another. A winner outranked by a loser of a neighbouring spot is outranked by that spot's winner too
  // (it is as deep and as early or better), so the answer is the one the pairwise rule gives.
  const win=new Map();
  entries.forEach((e,i)=>{if(e.page!==top||!above(e))return; const key=at(e)+'|'+(x(e)===null?'-':x(e)),j=win.get(key);
    if(j===undefined||deep(e)>deep(entries[j]))win.set(key,i);});
  const reps=[...win.values()].sort((a,b)=>at(entries[a])-at(entries[b])||a-b);
  const beats=(j,i)=>deep(entries[j])>deep(entries[i])||(deep(entries[j])===deep(entries[i])&&j<i);
  let sel=-1;
  for(let k=0;k<reps.length;k++){const i=reps[k],a=entries[i]; let out=false;
    for(let m=k-1;m>=0&&!out;m--){const b=entries[reps[m]]; if(at(a)-at(b)>1e-6)break; out=sameX(a,b)&&beats(reps[m],i);}
    for(let m=k+1;m<reps.length&&!out;m++){const b=entries[reps[m]]; if(at(b)-at(a)>1e-6)break; out=sameX(a,b)&&beats(reps[m],i);}
    if(!out&&i>sel)sel=i;}
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
  markOutline(); updateSectionStrip(); setViewMode('manuscript');
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
  if(sel!==OUTLINE_SELECTED||page!==OUTLINE_ACTIVE_PAGE){OUTLINE_ACTIVE_PAGE=page;OUTLINE_SELECTED=sel;markOutline();}
  const x=OUTLINE_ENTRIES[OUTLINE_SELECTED];$('#section-current').textContent=x?(x.number?x.number+'  ':'')+x.title:tr('원고');
  const n=META&&META.pages?META.pages.length:0,pg=tl('{page} / {n}쪽',{page,n}); $('#section-page-t').textContent=pg; $('#nav-page').textContent=pg;
  const name=tl('쪽 번호로 이동 · {page} / {n}쪽',{page,n}); $('#section-page').setAttribute('aria-label',name); $('#nav-page').setAttribute('aria-label',name); drawPos();
}
$('#outline-search').addEventListener('input',()=>outlineList($('#outline-items'),$('#outline-search').value));
$('#ns-outline-search').addEventListener('input',()=>outlineList($('#ns-outline-items'),$('#ns-outline-search').value));   // each search filters its own list only
$('#left').addEventListener('scroll',()=>{if(OUTLINE_PINNED&&!OUTLINE_PINNED.reached)outlinePickWait();
  if(!document.body.classList.contains('revision-open'))requestAnimationFrame(updateSectionStrip);},{passive:true});
// The reader taking over the pages lets go of a pick still on its way (dropOutlinePick); so does a new size of the window.
for(const t of ['wheel','touchstart','pointerdown'])$('#left').addEventListener(t,dropOutlinePick,{passive:true});
// A key scrolls the pages when nothing else has the focus, or something on the pages has it.
const SCROLL_KEYS=new Set(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' ']);
addEventListener('keydown',e=>{const a=document.activeElement;
  if(SCROLL_KEYS.has(e.key)&&(!a||a===document.body||$('#left').contains(a)))dropOutlinePick();});
addEventListener('resize',dropOutlinePick);
