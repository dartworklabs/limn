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
        return {title:item.title||tr('제목 없음'),page,depth:0,up:-1,frac:destFrac(dest,ptH),x:destLeft(dest)};
      }catch(e){return null;}}
    // up: the index in entries of the nearest entry above these rows (-1 at the top, or when every row above has no entry of its own)
    async function walk(rows,depth,up){
      for(let i=0;i<rows.length;i+=OUTLINE_BATCH){
        if(stale())return;   // between batches: a document left behind does not go on asking the worker
        if(entries.length>=OUTLINE_MAX_ENTRIES){for(let j=i;j<rows.length;j++)cut+=outlineCount(rows[j]); return;}
        const batch=rows.slice(i,i+OUTLINE_BATCH),got=await Promise.all(batch.map(entryOf));
        if(stale())return;
        for(let j=0;j<batch.length;j++){
          if(entries.length>=OUTLINE_MAX_ENTRIES){cut+=outlineCount(batch[j]); continue;}
          const at=entries.length; if(got[j])entries.push(Object.assign(got[j],{depth,up}));
          if(depth<OUTLINE_MAX_DEPTH){await walk(batch[j].items,depth+1,got[j]?at:up); if(stale())return;}
          else for(const c of batch[j].items||[])cut+=outlineCount(c);
        }
      }
    }
    await walk(items||[],0,-1);
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
  OUTLINE_ENTRIES=[];OUTLINE_CUT=0;OUTLINE_DOC=DOC;OUTLINE_BUILD='';OUTLINE_SELECTED=-1;OUTLINE_ACTIVE_PAGE=0;OUTLINE_PINNED=null;OUTLINE_MARKED=-1;OUTLINE_SNAP=true;OUTLINE_AIM=null;
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
 * Under a filter an entry whose name another entry has under another group says its group first (outlineGrouped), on a line of its
 * own above the row, small, muted and cut to one line: the results are a flat list, and `채택 › PL64` and `본문 그림 › PL64` are two
 * places, and a long group name must not push the names down.
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
  const grouped=query?outlineGrouped(OUTLINE_ENTRIES):null;
  setHtml(box,html`${rows.map(i=>{const x=OUTLINE_ENTRIES[i],on=i===OUTLINE_SELECTED;
    const page=x.pageLabel||String(x.page),grp=grouped&&grouped.has(i)?outlineGroupName(OUTLINE_ENTRIES[x.up]):'';
    return html`<button translate="no" class="ol-depth-${Math.min(x.depth,4)}${on?' ol-active':''}${grp?' ol-grouped':''}" data-act="outline-page" data-index="${i}" data-page="${x.page}" data-close="1" aria-current="${on?'location':'false'}" title="${grp?grp+' › '+x.title:x.title}">${grp?html`<span class="ol-grp">${grp} ›</span>`:''}<span class="ol-no">${x.number||'·'}</span><span class="ol-name">${x.title}</span><span class="ol-page">${page}</span></button>`;})}${note}`);
}
// The name of an outline entry as a group: its number and title.
function outlineGroupName(e){return e?(e.number?e.number+' ':'')+e.title:'';}
// The indices of the entries that a filter's flat results must say the group of: those under a group (up >= 0) whose number and
// title another entry has too under another group - a figure listed under its status and under the manuscript figure that holds
// it. Entries that differ in number or title tell themselves apart, and a title said twice under one group, or at the top, has no
// group to say. Over all the entries, not the rows found, so a row reads the same whatever is typed. Memoised on the entries.
let OUTLINE_GROUPED=/** @type {{for:object[]|null,set:Set<number>}} */({for:null,set:new Set()});
function outlineGrouped(entries){if(OUTLINE_GROUPED.for===entries)return OUTLINE_GROUPED.set;
  const norm=s=>String(s||'').normalize('NFKC').replace(/\s+/g,' ').trim().toLowerCase();   // as mergeOutlineLabels reads a title
  const under=new Map(),several=new Set(),set=/** @type {Set<number>} */(new Set());
  entries.forEach(e=>{const key=norm((e.number||'')+' '+e.title),up=typeof e.up==='number'?e.up:-1;
    if(!under.has(key))under.set(key,up); else if(under.get(key)!==up)several.add(key);});
  entries.forEach((e,i)=>{if(typeof e.up==='number'&&e.up>=0&&several.has(norm((e.number||'')+' '+e.title)))set.add(i);});
  OUTLINE_GROUPED={for:entries,set}; return set;}
// The outline's last line when the PDF has entries that were not read (OUTLINE_CUT): how many, and what the viewer reads at most.
// Under a filter it says the unread entries were not searched (it does not say they are not there). Quiet text, not a row: it names no place. Html, or '' with no cut.
function outlineCutNote(filtered){if(!OUTLINE_CUT)return '';
  const p={n:OUTLINE_CUT.toLocaleString('en-US'),max:OUTLINE_MAX_ENTRIES.toLocaleString('en-US'),depth:OUTLINE_MAX_DEPTH+1};
  return html`<p class="ol-more" role="note">${filtered
    ?tl('생략한 목차 항목 {n}개는 검색하지 않았습니다 — 읽는 한도는 {max}개, {depth}단계입니다',p)
    :tl('목차 항목 {n}개를 생략했습니다 — 읽는 한도는 {max}개, {depth}단계입니다',p)}</p>`;}
// Moves the current-section mark to OUTLINE_SELECTED in both lists without drawing them again. The section strip follows the
// reading line, so scrolling through a long document changes the section at every page, and redrawing thousands of rows each
// time is what a long outline cannot afford. A row is found by its data-index; one the filter hides has no row to mark. The panel
// follows the mark when it moves to another entry (outlineFollow) - not at every page of one entry, and not when a new build's list
// comes with the same entry current: then nothing has moved, and a list the person left somewhere stays there.
function markOutline(){for(const box of [$('#outline-items'),$('#ns-outline-items')]){
    for(const b of box.querySelectorAll('.ol-active')){b.classList.remove('ol-active'); b.setAttribute('aria-current','false');}
    const on=OUTLINE_SELECTED>=0?box.querySelector('[data-index="'+OUTLINE_SELECTED+'"]'):null;
    if(on){on.classList.add('ol-active'); on.setAttribute('aria-current','location');}}
  if(OUTLINE_SELECTED!==OUTLINE_MARKED){OUTLINE_MARKED=OUTLINE_SELECTED; outlineFollow();}}
// The outline panel keeps the current section in view (docs/handbook/viewer.md §모바일 레이아웃, 목차가 지금 절을 따라간다). The panel (#outline:
// the wide layout's panel, the overlay of mid and the tablet sheet) is its own scroller and a figure document's list is many times
// taller than it, so the mark alone moved out of sight. Only #outline scrolls - Element.scrollIntoView moves every scrolling ancestor
// too, the pages among them - and the focus stays where it is. A row clear of the margin moves nothing. The phone has no panel: its
// sheet is modal, so nothing moves under it, and it brings its own row up as it opens (navSheetReveal).
const OUTLINE_FOLLOW_HOLD_MS=3000;   // the list stays put this long after the person's own wheel, press, key or scroll in it
const OUTLINE_FOLLOW_MARGIN=48;      // px of the list kept between the current row and the panel's edges, at the least
const OUTLINE_FOLLOW_ROWS_UP=2;      // whole rows kept over the current row on the way up - and over its section's head where that fits
const OUTLINE_FOLLOW_FLIGHT_MS=600;  // how long a smooth follow can still be under way: a next one reckons from where it is heading
let OUTLINE_MARKED=-1,OUTLINE_SNAP=true,   // the entry last marked; the next follow jumps (a new document's list), it does not glide
  OUTLINE_FOLLOW_DUE=false,OUTLINE_FOLLOW_TIMER=0,   // a follow the person held back (or a list the filter drew again) is owed when they let go
  OUTLINE_OVER=false,OUTLINE_HANDLED=-Infinity,OUTLINE_SHOWN=false,   // the mouse is over the panel; when they last handled it; the panel is on screen
  OUTLINE_AIM=/** @type {{top:number,at:number}|null} */(null);   // where a smooth follow is heading, and since when
// Where the list (scrollTop st, view height h, content height sh) scrolls to bring a row at [top, bottom] of its content into view:
// null when the row stands m px clear of both edges - else the nearest place where it does (less on a view too short for that, and a
// row taller than the view by its top). The view's top edge is cover px down: the filter's band stays there, so a row is only in
// view below it. The margin holds from the moment a row enters it: following only once a row has left the view brought it in with
// the margin, let the next rows use it up and then moved the list by all of it at once. Coming up, the list goes further than the
// margin: to what starts at near (the rows just above the row) where that fits with the row and the margin under it - 48px left the
// row a row and a half under the band, and from a section's second entry on its head out of sight - and to group (the row's section
// head and the rows above that) where that fits too, so the head shows and the rows up to it then move nothing. Only the landing
// changes: whether the list moves at all is the margin's alone, so two rows next to each other cannot send a short panel back and
// forth. Going up, the very top where only part of the panel's head would be left over the row (head: where the rows start), as long
// as the row keeps the margin over the view's foot there: from the section's head the very top lies lower, and on the tablet sheet
// it took the row under the folded sheet's bar. Within what the list can scroll, so the list's two ends are as near as a row gets.
// Pure.
function outlineRevealTop(st,h,sh,top,bottom,m,head,cover=0,near=top,group=top){
  const room=Math.max(0,Math.min(m,(h-cover-(bottom-top))/2)),edge=st+cover;
  if(top>=edge+room-.5&&bottom<=st+h-room+.5)return null;
  const fits=(/** @type {number} */l)=>l<top-room&&bottom+room-l<=h-cover;
  const up=top<edge+room||bottom-top>h-cover,want=up?Math.min(top-room,fits(near)?near:top,fits(group)?group:top)-cover:bottom-h+room;
  const to=Math.round(Math.max(0,Math.min(sh-h,up&&want<=head&&bottom+room<=h+.5?0:want)));
  return to===Math.round(st)?null:to;}
// Whether the filter is narrowing the list: its rows are the results, not the outline, and the current row is likely not among them.
function outlineFiltered(){return !!$('#outline-search').value.trim();}
// Whether the person has the list in hand, so it stays where they put it: the filter has text, the mouse is over the panel, its width
// grip is being dragged, they wheeled, pressed, touched, scrolled or typed in it in the last OUTLINE_FOLLOW_HOLD_MS, or the keyboard is
// on a row. Neither a focus left in an empty filter holds anything - a tap on the pages does not take it away, so the outline would
// wait for good - nor a row a mouse pressed, which keeps the focus after its pick: reading on must not leave the outline behind.
function outlineHeld(){const a=/** @type {HTMLElement|null} */(document.activeElement);
  const onRow=!!a&&!!a.closest&&!!a.closest('#outline-items');
  return outlineFiltered()||OUTLINE_OVER||$('#outline-grip').classList.contains('on')||performance.now()-OUTLINE_HANDLED<OUTLINE_FOLLOW_HOLD_MS
    ||(onRow&&document.documentElement.dataset.input==='key');}
/** Brings the current row into the panel's view (outlineRevealTop), gliding unless the reader asked for reduced motion, the list is
 * new or the way is longer than the panel is high - an outline out of page order sends a row a thousand px off, and rows racing past
 * read as noise. One read of the row's place, at a move of the mark. A glide reckons from where a glide under way is heading
 * (OUTLINE_AIM); a jump lands at once, so it reckons from where the list is. Held back (outlineHeld), it is owed until they let go. A panel closed or
 * absent has nothing to show: it starts at the current row when it opens.
 * @param {boolean} [open] the panel has just come on screen: nobody has the list in hand yet, whatever the pointer rests on */
function outlineFollow(open){if(document.body.classList.contains('outline-collapsed')||BAND===LAYOUT_BAND.PHONE)return;
  if(open?outlineFiltered():outlineHeld()){OUTLINE_FOLLOW_DUE=true; outlineFollowLater(); return;}
  const list=$('#outline-items'),row=list.querySelector('.ol-active'); if(!row)return;
  const jump=!!open||OUTLINE_SNAP||MQ_REDUCED.matches; OUTLINE_FOLLOW_DUE=false; OUTLINE_SNAP=false;
  const box=$('#outline'),o=box.getBoundingClientRect(),r=row.getBoundingClientRect(),now=performance.now(),st=box.scrollTop;
  const from=o.top+box.clientTop-st,at=!jump&&OUTLINE_AIM&&now-OUTLINE_AIM.at<OUTLINE_FOLLOW_FLIGHT_MS?OUTLINE_AIM.top:st;
  // Where the rows OUTLINE_FOLLOW_ROWS_UP above a row start (the first row's top when there are fewer), and the section head of the
  // current row (its entry's up): read in the same pass as the row, so no further layout.
  const over=(/** @type {Element} */b)=>{for(let k=0;k<OUTLINE_FOLLOW_ROWS_UP&&b.previousElementSibling;k++)b=b.previousElementSibling; return b.getBoundingClientRect().top-from;};
  const e=OUTLINE_ENTRIES[Number(/** @type {HTMLElement} */(row).dataset.index)],sec=e&&e.up>=0?list.querySelector('[data-index="'+e.up+'"]'):null;
  // The tablet sheet's bar and the status line on it stand over the overlay's foot (frame.css: the overlay runs to the screen's
  // bottom): what they cover is out of view, so the view is that much shorter and so is what the list can scroll to bring a row up.
  const foot=outlineFoot(o),h=box.clientHeight,to=outlineRevealTop(at,h-foot,box.scrollHeight-foot,r.top-from,r.bottom-from,OUTLINE_FOLLOW_MARGIN,
    list.getBoundingClientRect().top-from,$('#outline-find').offsetHeight,over(row),sec?over(sec):undefined);
  if(to===null)return;
  const land=jump||Math.abs(to-st)>h;
  OUTLINE_AIM=land?null:{top:to,at:now}; box.scrollTo({top:to,behavior:land?'auto':'smooth'});}
// How many px at the foot of the panel (its box o) the bottom chrome covers: the collapsed sheet (#right) and the status line over
// it (#status-dock) where they are drawn across the panel. Only the tablet sheet's overlay has them there, and only it pads its
// foot to match (responsive.css). Elsewhere it is 0: a collapsed #right in mid or short is a transparent frame whose floating
// banner can reach across the panel without covering what lies below it, and nothing there pads the list for it.
/** @param {DOMRect} o */
function outlineFoot(o){if(BAND!==LAYOUT_BAND.TABLET_SHEET)return 0; let foot=0;
  for(const el of [$('#right'),$('#status-dock')]){if(!el||!el.getClientRects().length)continue; const b=el.getBoundingClientRect();
    if(b.height>0&&b.left<o.right&&b.right>o.left&&b.top<o.bottom&&b.bottom>o.top)foot=Math.max(foot,o.bottom-b.top);}
  return foot;}
// When a timed hold is over: the owed follow is made then. A hover, a keyboard's focus and a grip's drag end with an event of their own.
function outlineFollowLater(){clearTimeout(OUTLINE_FOLLOW_TIMER); const left=OUTLINE_HANDLED+OUTLINE_FOLLOW_HOLD_MS-performance.now();
  if(left>0)OUTLINE_FOLLOW_TIMER=setTimeout(outlineCatchUp,left+16);}
function outlineCatchUp(){if(OUTLINE_FOLLOW_DUE)outlineFollow();}
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
  // winner (deepest, the first of them) outranks the rest, and only the winners are compared with one another - and each only with
  // the winners that could share its spot. Those are found in two lists, the winners sorted by height and those with a left edge
  // sorted by it (a finite one): a spot's rivals lie in its height window (+-1e-6) and, if it has a left edge, in its edge window (+-1e-3) too, so
  // the shorter window is walked and the other test made on its members. A page of entries at one height and spread along it (a
  // window of one in the edge list), or at one edge and spread down it (a window of one in the height list), is walked in linear
  // time; only winners crowded into one such box (more distinct spots than there are in a 1e-6 x 1e-3 box of a real page) cost a
  // walk of the box each. A winner outranked by a loser of a neighbouring spot is outranked by that spot's winner too (it is as
  // deep and as early or better), so the answer is the one the pairwise rule gives.
  const win=new Map();
  entries.forEach((e,i)=>{if(e.page!==top||!above(e))return; const key=at(e)+'|'+(x(e)===null?'-':x(e)),j=win.get(key);
    if(j===undefined||deep(e)>deep(entries[j]))win.set(key,i);});
  const reps=[...win.values()].sort((a,b)=>b-a);   // the last listed first: the first of them nothing outranks is the answer
  const byAt=reps.slice().sort((a,b)=>at(entries[a])-at(entries[b])||a-b),byX=reps.filter(i=>Number.isFinite(x(entries[i]))).sort((a,b)=>x(entries[a])-x(entries[b])||a-b);
  // [from, to) in list (sorted by key) for the members whose key lies within eps of v, a little wider to be safe from the rounding of
  // a difference; each is tested exactly below.
  const near=(list,key,v,eps)=>{const lower=t=>{let l=0,h=list.length; while(l<h){const m=(l+h)>>1; if(key(entries[list[m]])<t)l=m+1; else h=m;} return l;};
    return [lower(v-eps*1.001),lower(v+eps*1.001)];};
  const beats=(j,i)=>deep(entries[j])>deep(entries[i])||(deep(entries[j])===deep(entries[i])&&j<i);
  const outranked=i=>{const a=entries[i]; let list=byAt,[lo,hi]=near(byAt,at,at(a),1e-6);
    if(Number.isFinite(x(a))){const [l,h]=near(byX,x,x(a),1e-3); if(h-l<hi-lo){list=byX;lo=l;hi=h;}}
    for(let m=lo;m<hi;m++){const j=list[m]; if(j!==i&&Math.abs(at(a)-at(entries[j]))<=1e-6&&sameX(a,entries[j])&&beats(j,i))return true;}
    return false;};
  for(const i of reps)if(!outranked(i))return i;
  return -1;}   // (the loop always returns: the winner of the deepest, first spot is outranked by nothing)
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
  const top=outlinePickTop(e); if(top===null)goPage(e.page); else pvGlideTo(top);}
// Where a pick scrolls the pages to, as #left's scrollTop: a heading with a place on its page (an XYZ destination below the
// page's top) OUTLINE_PICK_GAP under the free PDF area's top (spotTop); null - goPage's arrival (arrivePage: the page's
// top, or a figure page's figure) - for an entry that names a whole page (frac 0) and for every entry of a figure
// document, whose pages are its figures.
function outlinePickTop(e){const pg=document.getElementById('p'+e.page),d=docInfo(DOC);
  if(!pg||!(e.frac>0)||(d&&isFigureKind(d.kind)))return null;
  return spotTop(pg,e.frac,OUTLINE_PICK_GAP);}
// #left's scrollTop that puts the place `frac` down page pg `gap` px under the top of the free PDF area (selPopArea: under the
// section strip, the instance band or the select mode's bar) - lower when it stands near its page's bottom, so that the
// reading line (readingDepth) still falls on its page and the strip names it - as far as the pages scroll.
/** @param {HTMLElement} pg @param {number} frac @param {number} gap */
function spotTop(pg,frac,gap){const L=$('#left'),r=pg.getBoundingClientRect(),y=r.top+frac*r.height,read=L.getBoundingClientRect().top+readingDepth(L);
  const want=Math.max(selPopArea().top+gap,read+2-(r.bottom-y));
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
// The filter's keys (docs/handbook/viewer.md §모바일 레이아웃), the same in the panel and in the phone sheet, each with its own field,
// list and announcement. In the field, Enter chooses the first result and moves the focus onto it - not while nothing is typed: an
// empty filter lists every entry, and Enter must not pick the first of them - and ↓ moves the focus onto it without choosing. On a
// result, ↑/↓ move between the results (↑ on the first goes back to the field), Enter chooses (the row is a button), and Esc goes
// back to the field - and is not also taken by what Esc closes (the overlay panel, the navigation sheet). An Enter or an arrow that
// an input method is composing with (Korean typing commits its last syllable with Enter) is the method's, not ours. A key that
// moves the focus here makes the keyboard the input the focus ring answers (html[data-input], tooltip.js): a field is clicked
// with the mouse and typed in, and the first ↓ must show where the focus went.
/** @param {HTMLElement} box @returns {HTMLElement[]} the result rows (the unread-entries note is not one) */
function outlineRows(box){return /** @type {HTMLElement[]} */([...box.querySelectorAll('button[data-act="outline-page"]')]);}
/** @param {HTMLElement} field @param {HTMLElement} box @param {HTMLElement} sr */
function outlineFilter(field,box,sr){
  const fieldEl=/** @type {HTMLInputElement} */(field),keyed=()=>{document.documentElement.dataset.input='key';},
    mine=(/** @type {KeyboardEvent} */e)=>!(e.isComposing||e.keyCode===229||e.ctrlKey||e.metaKey||e.altKey||e.shiftKey);
  field.addEventListener('input',()=>{outlineList(box,fieldEl.value); outlineSay(box,fieldEl.value,sr);});
  field.addEventListener('keydown',e=>{if(!mine(e)||(e.key!=='Enter'&&e.key!=='ArrowDown'))return;
    if(e.key==='Enter'&&!fieldEl.value.trim())return;   // nothing typed: the whole outline is listed, and none of it was asked for
    const first=outlineRows(box)[0]; if(!first)return;   // nothing found: the key is the field's own
    e.preventDefault(); keyed(); first.focus(); if(e.key==='Enter')first.click();});   // the focus first: choosing in the sheet closes it and gives the focus back to where it was
  box.addEventListener('keydown',e=>{const row=/** @type {HTMLElement|null} */(e.target&&/** @type {HTMLElement} */(e.target).closest?/** @type {HTMLElement} */(e.target).closest('button[data-act="outline-page"]'):null);
    if(!row||!mine(e))return; const rows=outlineRows(box),at=rows.indexOf(row);
    if(e.key==='Escape'){e.preventDefault(); e.stopPropagation(); keyed(); field.focus();}
    else if(e.key==='ArrowDown'){e.preventDefault(); keyed(); if(rows[at+1])rows[at+1].focus();}
    else if(e.key==='ArrowUp'){e.preventDefault(); keyed(); if(at>0)rows[at-1].focus(); else field.focus();}});}
// What a screen reader is told after each keystroke of a filter (a polite status): how many results, or that there are none; nothing
// while the field is empty. The unread-entries note is not a result.
/** @param {HTMLElement} box @param {string} q @param {HTMLElement} sr */
function outlineSay(box,q,sr){const n=outlineRows(box).length,t=!String(q||'').trim()?'':n?tl('결과 {n}개',{n}):tr('찾은 장·절이 없습니다.');
  if(sr.textContent!==t)sr.textContent=t;}   // the same words again are not set again: a live region read '없습니다' at every keystroke
outlineFilter($('#outline-search'),$('#outline-items'),$('#outline-sr')); outlineFilter($('#ns-outline-search'),$('#ns-outline-items'),$('#ns-outline-sr'));   // each filter works on its own list only
// The sheet's filter draws its list again with rows of other heights (a group's line): the open sheet is fitted to them (navSheetFiltered),
// so none is left cut. After the filter's own drawing, which was set up just above.
$('#ns-outline-search').addEventListener('input',()=>{navSheetFiltered();});
// The person's hand on the panel (outlineHeld). A scroll inside a hold is theirs going on - a fling, a smooth wheel - and extends it;
// a follow never runs inside one, so its own scroll does not hold anything. A hand on the panel stops a glide, so nothing is heading
// anywhere any more (OUTLINE_AIM), and so do its end, a filter's new list, a panel closing and another document (outlineForget).
(function(){const box=$('#outline'),grip=$('#outline-grip'),handled=()=>{OUTLINE_HANDLED=performance.now(); OUTLINE_AIM=null;};
  for(const t of ['wheel','pointerdown','touchstart','touchmove','keydown'])box.addEventListener(t,handled,{passive:true});
  box.addEventListener('scroll',()=>{if(performance.now()-OUTLINE_HANDLED<OUTLINE_FOLLOW_HOLD_MS)handled();},{passive:true});
  box.addEventListener('scrollend',()=>{OUTLINE_AIM=null;},{passive:true});
  box.addEventListener('pointerenter',e=>{if(e.pointerType!=='touch')OUTLINE_OVER=true;});
  box.addEventListener('pointerleave',e=>{if(e.pointerType!=='touch'){OUTLINE_OVER=false; outlineCatchUp();}});
  box.addEventListener('focusout',()=>{setTimeout(outlineCatchUp,0);});   // by then the focus has landed: it may be on another row
  // The width grip stands beside the panel, and its press and keys are a hand on the panel all the same. A drag holds until it ends
  // (outlineHeld), whatever its length; the timed hold runs from the release or the cancel, so an owed follow is made after it.
  for(const t of ['pointerdown','pointerup','pointercancel','keydown'])grip.addEventListener(t,()=>{handled(); if(OUTLINE_FOLLOW_DUE)outlineFollowLater();});
  // A press ends the keyboard's hold (html[data-input], tooltip.js) without a focusout when it lands where a press takes no focus: the
  // pages leave it on the row. Not at once: this runs first of all, and a press in the panel or on its grip must hold before it looks.
  document.addEventListener('pointerdown',()=>{if(OUTLINE_FOLLOW_DUE)setTimeout(outlineCatchUp,0);},true);
  // Typing is a hand on the panel, and the list drawn again owes its row. Emptied, the filter ends with no event of its own: it is
  // made when this hold is over, with the focus left in the field.
  $('#outline-search').addEventListener('input',()=>{handled(); OUTLINE_FOLLOW_DUE=true; outlineFollowLater();});
  // Display none to shown: a panel opening, here and not in its toggle, so that a band change that brings it back counts too.
  if(window.ResizeObserver)new ResizeObserver(([e])=>{const shown=e.contentRect.height>0; if(!shown){OUTLINE_OVER=false; OUTLINE_AIM=null;}
    if(shown&&!OUTLINE_SHOWN)outlineFollow(true); OUTLINE_SHOWN=shown;}).observe(box);
  // A row the keyboard walks to stops below the filter's band (frame.css), which the hint makes taller while it shows.
  if(window.ResizeObserver){const find=$('#outline-find'); new ResizeObserver(()=>{box.style.scrollPaddingTop=find.offsetHeight+'px';}).observe(find);}})();
$('#left').addEventListener('scroll',()=>{if(OUTLINE_PINNED&&!OUTLINE_PINNED.reached)outlinePickWait();
  if(!document.body.classList.contains('revision-open'))requestAnimationFrame(updateSectionStrip);},{passive:true});
// The reader taking over the pages lets go of a pick still on its way (dropOutlinePick); so does a new size of the window.
for(const t of ['wheel','touchstart','pointerdown'])$('#left').addEventListener(t,dropOutlinePick,{passive:true});
// A key scrolls the pages when nothing else has the focus, or something on the pages has it.
const SCROLL_KEYS=new Set(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' ']);
addEventListener('keydown',e=>{const a=document.activeElement;
  if(SCROLL_KEYS.has(e.key)&&(!a||a===document.body||$('#left').contains(a)))dropOutlinePick();});
addEventListener('resize',dropOutlinePick);
