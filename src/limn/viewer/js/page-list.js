// ------------------------------------------------ The page list (docs/handbook/viewer.md §조작 한눈에, issue #187)
// Going to a page without typing. The page count above the page (wide: #section-page) or at the nav bar's end (mid, short and
// the tablet sheet: #nav-page) opens a popover (#page-pop): a page field on top and one row per page below it, each with the
// sections that start on that page. The phone's navigation sheet carries the same rows under its page field (#ns-pages).
// Choosing a row goes there at once - there is no confirm step.

// The names a row shows for each of n pages, index 0 for page 1: the top-level headings that start on the page joined with
// ' · ' ('1 Introduction · 2 Related work'), else the one the page continues ('… 2 Related work'); '' before the first heading.
// entries is the outline in document order (OUTLINE_ENTRIES). Pure.
function pageSections(entries,n){
  const name=e=>(e.number?e.number+' ':'')+e.title,top=entries.filter(e=>e.depth===0),out=[];
  let last='';
  for(let p=1;p<=n;p++){const on=top.filter(e=>e.page===p);
    if(on.length){out.push(on.map(name).join(' · ')); last=name(on[on.length-1]);}
    else out.push(last?'… '+last:'');}
  return out;}
// Whether the document on screen names sections in its page list: a LaTeX manuscript does; a figure document and a view-only
// PDF list page numbers only.
function pageListNamed(){const d=docInfo(DOC); return !d||buildsFromSource(d.kind);}
// The number of pages of the build on screen; 0 before /api/meta has answered.
function pageCount(){return META&&META.pages?META.pages.length:0;}
// The rows for pages 1..n: the page on screen (cur) is the selected option, carries the check and is the list's one tab stop.
// The section names are the manuscript's words (translate="no"); the page number is UI.
function pageRowsHtml(n,cur){const names=pageListNamed()?pageSections(OUTLINE_ENTRIES,n):[];
  return html`${Array.from({length:n},(_,i)=>{const p=i+1,on=p===cur;
    return html`<button class="pl-row${on?' on':''}" role="option" aria-selected="${on}" tabindex="${on?0:-1}" data-act="page-go" data-page="${p}" data-close="1"><span class="pl-n">${tl('{page}쪽',{page:p})}</span><span class="pl-s" translate="no">${names[i]||''}</span>${on?ic('check'):''}</button>`;})}`;}
// Scrolls list so that its selected row sits in the middle of the list's box (as far as the list can scroll).
function revealPageRow(list){const r=/** @type {HTMLElement|null} */(list.querySelector('[aria-selected=true]')); if(!r)return;
  list.scrollTop=r.offsetTop-(list.clientHeight-r.offsetHeight)/2;}

let PAGE_LIST_FROM=/** @type {HTMLElement|null} */(null);   // the page count that opened the popover; null while it is shut
// Opens the popover under the page count `from`, listing the pages with the current one in view. A mouse or keyboard gets the
// page field focused, so typing a number still works at once; touch gets the current row focused, so no keyboard comes up.
function openPageList(from){const pop=$('#page-pop'),list=$('#page-pop-list'),f=$('#page-pop-in'),n=pageCount();
  hideTip(); PAGE_LIST_FROM=from; from.setAttribute('aria-expanded','true');
  setHtml(list,pageRowsHtml(n,OUTLINE_ACTIVE_PAGE||1)); f.value=''; f.placeholder='1–'+n;
  pop.hidden=false; placePageList(); revealPageRow(list);
  const row=/** @type {HTMLElement|null} */(list.querySelector('[aria-selected=true]'));
  (MQ_COARSE.matches&&row?row:f).focus({preventScroll:true});}
// Puts the open popover under its page count, its right edge on the count's and inside the window by 8px, and lets it grow
// only down to 8px above the window's bottom (--pl-room; 480px at most); its list scrolls inside that. A count that is no longer shown shuts it.
function placePageList(){const pop=$('#page-pop'),from=PAGE_LIST_FROM; if(pop.hidden||!from)return;
  if(!from.getClientRects().length){closePageList(false); return;}
  const r=from.getBoundingClientRect(),w=pop.offsetWidth,top=r.bottom+4;
  pop.style.left=Math.max(8,Math.min(r.right-w,innerWidth-8-w))+'px'; pop.style.top=top+'px';
  pop.style.setProperty('--pl-room',Math.max(0,innerHeight-8-top)+'px');}
// Shuts the popover; back gives the focus back to the page count that opened it (Esc, a choice), an outside click leaves it.
function closePageList(back){const pop=$('#page-pop'); if(pop.hidden)return; pop.hidden=true;
  const from=PAGE_LIST_FROM; PAGE_LIST_FROM=null; if(!from)return;
  from.setAttribute('aria-expanded','false'); if(back)from.focus({preventScroll:true});}
// The page count's click: opens the popover under it, or shuts it when it is already open from there.
function togglePageList(from){const again=!$('#page-pop').hidden&&PAGE_LIST_FROM===from; closePageList(again); if(!again)openPageList(from);}
// Goes to page p from the list or its field: shuts the popover (the sheet shuts through its data-close), leaves the changes view
// for the manuscript, and scrolls to the page.
function goListedPage(p){closePageList(true);
  if(document.body.classList.contains('revision-open'))setViewMode(VIEW_MODE.MANUSCRIPT); goPage(p);}
// The phone's navigation sheet: its page rows under the page field, scrolled to the current page (openNavSheet).
function drawSheetPages(){const box=$('#ns-pages'),n=pageCount(); box.hidden=!n; setHtml(box,pageRowsHtml(n,OUTLINE_ACTIVE_PAGE||1));}

// Keys in a page list (the popover's and the sheet's): ↓/↑ move one row, Home/End to the ends - from the page field ↓/↑ go to
// the current page's row; Enter on a row is its click, Enter in the field goes to the typed page (clamped to 1..n).
function pageListKey(e){const t=/** @type {HTMLElement} */(e.target);
  if(e.isComposing)return;
  if(t.id==='page-pop-in'){
    if(e.key==='Enter'){e.preventDefault(); const p=clampPage(/** @type {HTMLInputElement} */(t).value,pageCount()); if(p!==null)goListedPage(p);}
    else if(e.key==='ArrowDown'||e.key==='ArrowUp'){const r=/** @type {HTMLElement|null} */($('#page-pop-list [aria-selected=true]')); if(r){e.preventDefault(); r.focus();}}
    return;}
  const row=/** @type {HTMLElement|null} */(t.closest('.pl-row')); if(!row)return;
  const rows=/** @type {HTMLElement[]} */([.../** @type {HTMLElement} */(row.parentElement).children]),i=rows.indexOf(row);
  const to={ArrowDown:i+1,ArrowUp:i-1,Home:0,End:rows.length-1}[e.key];
  if(to===undefined)return; e.preventDefault(); const next=rows[Math.max(0,Math.min(rows.length-1,to))]; next.focus(); next.scrollIntoView({block:'nearest'});}
$('#page-pop').addEventListener('keydown',pageListKey);
$('#ns-pages').addEventListener('keydown',pageListKey);
// A click outside the popover and its page count shuts it (the click still does what it does).
document.addEventListener('click',e=>{const t=/** @type {Node} */(e.target);
  if(!$('#page-pop').hidden&&!$('#page-pop').contains(t)&&!(PAGE_LIST_FROM&&PAGE_LIST_FROM.contains(t)))closePageList(false);},true);
addEventListener('resize',placePageList);
